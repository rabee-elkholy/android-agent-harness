"""Task-local, preview-bound decisions for concurrent developer edits.

These receipts supplement file authority; they never rewrite an approval,
baseline, frozen run, reviewer result, or spending counter.
"""
from pathlib import Path, PurePosixPath

from _vnext_common import (ValidationError, canonical_sha256, read_json, state_root,
                           utc_now, validate_id, validate_repo_path_containment)


def decisions(plan):
    for row in plan.get("change_decisions") or []:
        if not isinstance(row, dict) or row.get("receipt_sha256") != canonical_sha256(
                {k: v for k, v in row.items() if k != "receipt_sha256"}):
            raise ValidationError("invalid task change decision receipt")
        if row.get("task_id") != plan.get("task_id"):
            raise ValidationError("task change decision identity mismatch")
        if (row.get("plan_sha256") == plan.get("plan_sha256")
                and row.get("execution_nonce") == plan.get("execution_nonce")):
            yield row


def additional_files(plan):
    return {path for row in decisions(plan) if row["mode"] == "extend-scope" for path in row["files"]}


def reserved_files(plan):
    return {path for row in decisions(plan) for path in row["files"]}


def accepted_files(plan, previous_run_id, previous, current):
    """Exact before/after identities only; later edits cannot inherit consent."""
    from delivery_equivalence import _file_identities
    before, after = _file_identities(previous), _file_identities(current)
    result, resolved = set(), set()
    for row in reversed(list(decisions(plan))):
        if row["mode"] not in {"accept-edits", "review-edits"} or row.get("source_run_id") != previous_run_id:
            continue
        if row.get("repository") != current.get("repository"):
            continue
        if row.get("external_inputs_sha256") != current.get("external_inputs_sha256"):
            continue
        for path in row["files"]:
            if (path not in resolved and row["before"].get(path) == before.get(path)
                    and row["after"].get(path) == after.get(path)):
                resolved.add(path)
                if row["mode"] == "accept-edits":
                    result.add(path)
    return result


def observed_files(plan, repo):
    """Personal edits grant verification scope at these bytes, never write scope."""
    from delivery_manifest import build_manifest
    from delivery_equivalence import _file_identities
    rows = [row for row in decisions(plan) if row["mode"] in {"accept-edits", "review-edits"}]
    if not rows:
        return set()
    live = _file_identities(build_manifest(Path(repo)))
    return {path for row in rows for path in row["files"] if row["after"].get(path) == live.get(path)}


def register_parser(sub, common):
    parser = sub.add_parser("change-decision", parents=[common])
    parser.add_argument("--mode", choices=("extend-scope", "accept-edits", "review-edits"), required=True)
    parser.add_argument("--file", action="append", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-preview")
    parser.add_argument("--source", choices=("approved-plan", "conversation", "developer_terminal"))
    parser.add_argument("--proof-reference", default="")
    parser.set_defaults(handler=record_decision)


def record_decision(args):
    from evidence_store import StateLock
    with StateLock(state_root(Path(args.repo).resolve())):
        return _record_locked(args)


def _record_locked(args):
    from _workflow import engine
    from plan_authority import validate_plan_hash, check_material_drift, changed_modules, save_plan
    from delivery_manifest import build_manifest, assert_disjoint_task_scope, is_delivery_relevant
    from delivery_equivalence import _file_identities
    from change_classifier import classify
    from review_budget import settle_final_review_calls

    repo = Path(args.repo).resolve()
    engine.assert_single_live_task(repo, allowed_task_id=args.task_id)
    plan = engine._load_plan(repo, args.task_id)
    if (plan.get("status") not in {"IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"}
            or not validate_plan_hash(plan)[0] or not plan.get("approval")
            or plan.get("execution_nonce") != plan["approval"].get("single_use_nonce")):
        raise ValidationError("change decision requires a valid approved live task")
    files = []
    for raw in args.file:
        path = validate_repo_path_containment(repo, raw)
        if path != PurePosixPath(raw.replace("\\", "/")).as_posix():
            raise ValidationError("change decision paths must not traverse symlinks or aliases")
        files.append(path)
    files = sorted(set(files))
    for path in files:
        if (any(c in path for c in "*?[:") or not is_delivery_relevant(path)
                or path.lower().startswith((".agents/", ".git/", ".harness-setup/"))
                or (repo / path).is_dir() or (repo / path).is_symlink()):
            raise ValidationError("change decisions require exact application files")
    reason = args.reason.strip()
    if not reason:
        raise ValidationError("a concrete same-goal/change explanation is required")
    manifest = build_manifest(repo)
    for key in ("root_sha256", "git_common_dir_sha256", "branch"):
        if (plan.get("repository") or {}).get(key) != (manifest.get("repository") or {}).get(key):
            raise ValidationError("change decision repository identity mismatch: " + key)
    identities = _file_identities(manifest)
    directory = engine.task_dir(repo, args.task_id)
    current_file = directory / "current-run.json"
    current = read_json(current_file) if current_file.is_file() else {}
    committed = str(plan.get("verification_run_id") or "")
    source_run = committed if committed and (directory / f"manifest-{validate_id(committed, 'run id')}.json").is_file() else str(current.get("run_id") or "")
    # A stale follow-up may not have reached review yet. Bind consent to the
    # same last reviewed source that prepare-verification will compare against.
    visited = set()
    while source_run:
        validate_id(source_run, "run id")
        if source_run in visited or len(visited) >= 10:
            raise ValidationError("invalid review source chain")
        visited.add(source_run)
        source_manifest = read_json(directory / f"manifest-{source_run}.json")
        from evidence_store import EvidenceStore
        evidence_path = EvidenceStore(state_root(repo)).run_dir(source_manifest["delivery_snapshot_sha256"], source_run) / "reviews.json"
        if evidence_path.is_file():
            break
        source_policy = read_json(directory / f"policy-{source_run}.json")
        prior = str((source_policy.get("later_round_source") or {}).get("run_id") or "")
        if not prior:
            break
        source_run = prior
    if source_run:
        validate_id(source_run, "run id")
    previous = read_json(directory / f"manifest-{source_run}.json") if source_run else {}
    before = _file_identities(previous) if previous else {item["path"]: item for item in plan.get("base_file_identities") or []}
    if args.mode != "extend-scope" and any(before.get(p) == identities.get(p) for p in files):
        raise ValidationError("select only files changed since the frozen run; use extend-scope for planned support files")
    proposed = {**plan, "expected_files": sorted(set(plan.get("expected_files") or []) | additional_files(plan) | set(files))}
    assert_disjoint_task_scope(repo, args.task_id, proposed)
    classification = classify(repo, task_changes=[{"path": p} for p in files], candidate_paths=files, progress=False)
    drift = check_material_drift(proposed, classification.get("surfaces") or [],
                                 changed_modules(repo, {"task_changes": [{"path": p} for p in files]}), repo=repo)
    preview = {
        "schema_version": 1, "task_id": args.task_id, "plan_sha256": plan["plan_sha256"],
        "execution_nonce": plan["execution_nonce"],
        "phase_checkpoints": (read_json(directory / "phase-state.json").get("phase_checkpoints", {})
                              if source_run and (directory / "phase-state.json").is_file() else {}),
        "mode": args.mode, "files": files, "reason": reason, "source_run_id": source_run,
        "repository": manifest.get("repository"), "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "change_set_sha256": manifest["change_set_sha256"], "external_inputs_sha256": manifest.get("external_inputs_sha256"),
        "before": {p: before.get(p) for p in files}, "after": {p: identities.get(p) for p in files},
        "material_drift": drift,
        "effect": "Preserve task, approval, phases, prior review evidence and spending. Refresh deterministic verification. "
                  "accept-edits exempts only this exact post-review delta; initial reviews, open findings and new responsibilities remain required.",
    }
    preview["preview_sha256"] = canonical_sha256(preview)
    if not args.apply:
        review_diff = None
        if previous:
            from review_fix_delta import _comparison_texts
            import difflib
            texts = _comparison_texts(repo, previous, manifest, plan, source_run, files)
            if texts is not None:
                review_diff = "\n".join("".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                    fromfile="a/" + path, tofile="b/" + path, n=3)) for path, (old, new) in sorted(texts.items()))
                from _vnext_common import redact_text
                review_diff = redact_text(review_diff)[:24000]
        return {"status": "PREVIEW", **preview, "review_diff": review_diff,
                "inspection_note": "Inspect the complete named delta before consent; the displayed text is bounded and may be unavailable for binary or uncached files."}
    if args.expect_preview != preview["preview_sha256"]:
        raise ValidationError("CHANGE_PREVIEW_STALE: show a fresh preview before applying the decision")
    if drift:
        raise ValidationError("PLAN_APPROVAL_REQUIRED: material expansion beyond file membership: " + ", ".join(drift))
    if args.source == "approved-plan":
        if args.mode != "extend-scope":
            raise ValidationError("accepting personal edits requires explicit developer consent")
    elif args.source not in {"conversation", "developer_terminal"} or not args.proof_reference.strip():
        raise ValidationError("explicit developer source and proof-reference are required")
    for row in decisions(plan):
        if row.get("preview_sha256") == preview["preview_sha256"]:
            return {"status": plan["status"], "task_id": args.task_id, "decision": row, "already_applied": True}
    # Validate lineage before publishing any receipt, including while IMPLEMENTING.
    from task_git_lineage import is_valid_task_lineage
    valid, why = is_valid_task_lineage(repo, args.task_id, manifest["repository"]["head"])
    if not valid:
        raise ValidationError(why)
    settle_final_review_calls(repo, plan)
    receipt = {**preview, "source": args.source, "proof_reference": args.proof_reference.strip(), "recorded_at": utc_now()}
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    plan.setdefault("change_decisions", []).append(receipt)
    # One atomic plan publication; no partial resume or approval rewrite.
    if plan["status"] != "IMPLEMENTING":
        plan["status"] = "IMPLEMENTING"
        plan["resumed_at"] = utc_now()
        for key in ("ready_at", "ready_delivery_snapshot_sha256", "ready_change_set_sha256", "ready_run_id"):
            plan.pop(key, None)
    plan.pop("material_drift", None)
    plan.pop("material_drift_causes", None)
    plan.pop("review_budget_blocked", None)  # Recompute demand from the fresh delta, never reset spending.
    save_plan(engine._plan_path(repo, args.task_id), plan)
    return {"status": "IMPLEMENTING", "task_id": args.task_id, "decision": receipt,
            "next_command": f"python .agents/harness.py task status --task-id {args.task_id} --next --brief"}
