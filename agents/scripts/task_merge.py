"""Preview and explicitly consolidate two or three never-started task plans.

The normal planner still owns policy, scope, architecture and baseline creation.
A durable journal makes interrupted publication recoverable without granting write authority.
"""
from __future__ import annotations

import argparse
import copy
import posixpath
import shutil
import tempfile
from pathlib import Path

from _vnext_common import ValidationError, atomic_write_json, canonical_sha256, read_json, utc_now, validate_id
from delivery_manifest import build_manifest, disjoint_sibling_file_sets, task_owned_files
from plan_authority import plan_payload, save_plan, validate_plan_hash


def conflict_merge_option(repo: Path, task_id: str, tasks: list[dict], *, limit: bool = False) -> dict:
    import workflow
    candidates = tasks if limit else [{"task_id": task_id}, *tasks]
    eligible, reasons = [], []
    missing_request = False
    for item in candidates:
        tid = item["task_id"]
        path = workflow.task_dir(repo, tid) / "plan.json"
        if not path.exists():
            missing_request = True
            continue
        plan = read_json(path)
        reason = ineligible_reason(repo, tid, plan)
        if reason:
            reasons.append(reason)
        else:
            eligible.append(tid)
    option = {"id": "merge_plans", "label": "Combine plans before implementation", "available": False,
              "kind": "DEVELOPER_ACTION", "command": "", "recommended": False}
    if len(eligible) >= 2 and (limit or not reasons):
        ids = eligible[:3]
        target = "merged-" + canonical_sha256(ids)[:12]
        option.update(available=True, kind="HARNESS_COMMAND", task_ids=ids,
                      command=f"python .agents/harness.py task merge --task-id {target} " + " ".join(f"--from-task-id {tid}" for tid in ids),
                      description="Preview one combined plan, then apply only if you choose it. Source history stays; the new task needs one fresh approval. No project files or Git are merged.")
    elif missing_request and eligible and not reasons:
        option.update(available=True, task_ids=eligible,
                      description="This request has no saved task yet. On your explicit merge choice, include its complete goals and scope in a revision of the pending plan, then present it for fresh approval.")
    else:
        option["description"] = " ".join(reasons) or "Choose at least two plans awaiting their first approval. Started tasks keep separate approvals, evidence and budgets."
    return option


def ineligible_reason(repo: Path, task_id: str, plan: dict) -> str:
    """Cheap eligibility for conflict choices; application performs the complete checks again."""
    import workflow
    directory = workflow.task_dir(repo, task_id)
    if plan.get("status") != "AWAITING_DEVELOPER_APPROVAL":
        return f"{task_id} is {plan.get('status')}; only plans awaiting their first approval can merge."
    candidates = [plan]
    try:
        candidates.extend(read_json(p) for p in (directory / "plan-history").glob("*.json"))
        for old in candidates:
            if not validate_plan_hash(old)[0]:
                return f"{task_id} has an invalid plan identity."
            if (old.get("approval") or old.get("execution_nonce") or old.get("implementation_started_at")
                    or old.get("status") not in {"AWAITING_DEVELOPER_APPROVAL"}
                    or any(old.get(k) for k in ("review_calls_used", "review_rounds", "final_review_call_charges", "ready_run_id"))):
                return f"{task_id} has approval, execution or review history; finish it separately."
        if any(directory.glob("manifest-*.json")) or any(directory.glob("policy-*.json")):
            return f"{task_id} already has verification history."
        if any((directory / name).exists() for name in (
                "current-run.json", "run-history", "task-start-failures.json", "red-evidence.json", "pending-handoff.json", "git-checkpoints")):
            return f"{task_id} already has execution evidence."
        if any((directory / "phases").glob("*/checkpoint.json")):
            return f"{task_id} already has phase evidence."
        marker = workflow.state_root(repo) / "cancel-requested.json"
        if marker.is_file() and read_json(marker).get("task_id") == task_id:
            return f"{task_id} has a pending cancellation decision; resolve it first."
    except (OSError, ValidationError) as exc:
        return f"{task_id} has unreadable history: {exc}"
    return ""


def _combined_args(repo: Path, target: str, sources: list[dict]) -> argparse.Namespace:
    # One runtime architecture/acceptance/tracker contract cannot represent conflicting contracts.
    # Refuse rather than silently selecting one source or dropping an obligation.
    shared = {}
    for field in ("verification_contract", "zoho_link"):
        values = [p[field] for p in sources if p.get(field)]
        if values and any(v != values[0] for v in values[1:]):
            raise ValidationError(f"TASK_MERGE_INCOMPATIBLE: different {field} values need a developer-reviewed consolidated plan; work in order or use separate file scopes meanwhile.")
        shared[field] = values[0] if values else None
    contracts = [p["architecture_contract"] for p in sources if p.get("architecture_contract")]
    # A per-file contract contains the same decision with different observation metadata.
    # Compare the decisions, then let the canonical resolver evaluate the combined scope.
    observation = {"target_scope", "contract_sha256", "match_type", "resolution_confidence", "exemplar_paths"}
    decisions = [{k: v for k, v in c.items() if k not in observation} for c in contracts]
    if decisions and any(d != decisions[0] for d in decisions[1:]):
        raise ValidationError("TASK_MERGE_INCOMPATIBLE: different architecture decisions need a reviewed consolidated plan; work in order or use separate scopes meanwhile.")
    arch = copy.deepcopy(contracts[0]) if contracts else {}
    scopes = [str(c.get("target_scope") or "").replace("\\", "/") for c in contracts]
    if len(scopes) > 1:
        arch["target_scope"] = posixpath.commonpath(scopes) or "."

    def union(field):
        return sorted({v for p in sources for v in p.get(field) or []})

    def joined(field):
        return "\n\n".join(f"[{p['task_id']}] {p[field]}" for p in sources if p.get(field))

    phases = []
    for index, plan in enumerate(sources, 1):
        originals = plan.get("phases") or [{"id": "work", "title": plan["requested_outcome"][:200],
                                           "expected_files": plan.get("expected_files") or []}]
        for phase in originals:
            phases.append({**copy.deepcopy(phase), "id": f"t{index}-{phase['id']}"})
    intent = {"PRESERVE": "EXISTING_CHANGE", "NEW": "NEW_FEATURE", "REFACTOR": "REFACTOR",
              "MIGRATE": "MIGRATION", "MIGRATION": "MIGRATION"}.get(arch.get("mode"), "EXISTING_CHANGE")
    kinds = {p.get("task_kind") for p in sources}
    return argparse.Namespace(
        repo=str(repo), task_id=target, outcome=joined("requested_outcome"),
        kind="BUG" if "BUG" in kinds else ("REFACTOR" if kinds == {"REFACTOR"} else "FEATURE"),
        planning_depth="ARCHITECTURAL" if any(p.get("planning_depth") == "ARCHITECTURAL" for p in sources) else "BOUNDED",
        expected_files=sorted({f for p in sources for f in task_owned_files(repo, p["task_id"], p)}),
        expected_modules=",".join(union("expected_modules")), expected_surfaces=",".join(union("expected_surfaces")),
        test_strategy=joined("test_strategy"), device_strategy=joined("device_strategy"),
        risks=",".join(union("risks")), rollback=joined("rollback"), approach=joined("approach"),
        external_write=union("external_writes"), phases=phases, verification_contract=shared["verification_contract"],
        scoped_phase_review_enabled=any(p.get("scoped_phase_review_enabled") for p in sources),
        architecture_intent=intent, architecture_target_scope=arch.get("target_scope"),
        architecture_target_family=arch.get("target_family_id"),
        zoho_item_id=(shared["zoho_link"] or {}).get("item_id"),
        zoho_item_type=(shared["zoho_link"] or {}).get("item_type"),
        zoho_sprint_id=(shared["zoho_link"] or {}).get("sprint_id"),
    )


def _check_unchanged(repo: Path, plans: list[dict]) -> None:
    """Never absorb edits to source plans as a fresh, apparently unstarted baseline."""
    from plan_authority import _check_start_repository
    owned = {f for p in plans for f in task_owned_files(repo, p["task_id"], p)}
    current = build_manifest(repo)
    keys = {"path", "content_identity", "git_mode", "worktree_git_mode"}
    current_files = [{k: v for k, v in entry.items() if k in keys} for entry in current["files"]]
    for plan in plans:
        _check_start_repository(repo, plan)
        before = plan.get("base_file_identities")
        if (not isinstance(before, list) or canonical_sha256(before) != plan.get("base_delivery_snapshot_sha256")
                or plan.get("base_external_inputs_sha256") != current.get("external_inputs_sha256")):
            raise ValidationError("TASK_MERGE_BASELINE_CHANGED: source plan has missing or changed baseline inputs; refresh its plan before merging.")
        live, committed = disjoint_sibling_file_sets(repo, plan["task_id"], plan)
        excluded = (live | committed) - owned
        def filtered(entries):
            # A rename crossing the retained scope cannot disappear with a sibling's path.
            return [e for e in entries if not ({e.get("path"), e.get("old_path")} - {None}) <= excluded]
        if filtered(before) != filtered(current_files) or filtered(plan.get("base_change_identities") or []) != filtered(current["changes"]):
            raise ValidationError("TASK_MERGE_BASELINE_CHANGED: files changed after a source plan was drafted; preserve the edits and revise the affected plan before merging.")


def _finish_publication(repo: Path, journal: dict) -> dict:
    """Idempotent roll-forward, with unexpected state edits rejected before any writes."""
    import workflow
    root = workflow.state_root(repo)
    expected_hash = canonical_sha256({k: v for k, v in journal.items() if k != "journal_sha256"})
    if journal.get("journal_sha256") != expected_hash:
        raise ValidationError("TASK_MERGE_RECOVERY_REQUIRED: invalid merge journal; preserve it for Doctor inspection.")
    target = validate_id(journal["task_id"], "task id")
    if len(str(journal.get("preview_sha256") or "")) != 64 or any(c not in "0123456789abcdef" for c in journal["preview_sha256"]):
        raise ValidationError("TASK_MERGE_RECOVERY_REQUIRED: invalid preview identity in merge journal.")
    stage = root / "task-merges" / journal["preview_sha256"] / "candidate"
    destination = workflow.task_dir(repo, target)
    for source in journal["sources"]:
        source_id = validate_id(source["before"]["task_id"], "task id")
        if read_json(workflow.task_dir(repo, source_id) / "plan.json") not in (source["before"], source["after"]):
            raise ValidationError(f"TASK_MERGE_RECOVERY_REQUIRED: source '{source_id}' changed during publication.")
    existing = destination / "plan.json"
    if existing.exists() and read_json(existing) != journal["plan"]:
        raise ValidationError("TASK_MERGE_RECOVERY_REQUIRED: destination changed during publication.")
    if not existing.exists() and (not (stage / "plan.json").is_file() or read_json(stage / "plan.json") != journal["plan"]):
        raise ValidationError("TASK_MERGE_RECOVERY_REQUIRED: staged plan is missing or changed.")
    for source in journal["sources"]:
        directory = workflow.task_dir(repo, source["before"]["task_id"])
        atomic_write_json(directory / "plan-history" / f"{source['before']['plan_sha256']}.json", source["before"])
        save_plan(directory / "plan.json", source["after"])
        workflow._write_plan_document(repo, source["before"]["task_id"], source["after"])
    if not existing.exists():
        stage.replace(destination)
    atomic_write_json(root / "active-task.json", {"task_id": target, "plan_path": str(existing), "updated_at": utc_now()})
    atomic_write_json(root / "task-merges" / journal["preview_sha256"] / "receipt.json", journal)
    (root / "task-merge-pending.json").unlink()
    return {**journal["plan"], "merge_preview_sha256": journal["preview_sha256"],
            "merge_message": "Plans consolidated. Source tasks are CANCELLED with history retained. Present the new plan for one fresh approval before implementation."}


def merge_plans(args: argparse.Namespace) -> dict:
    import workflow
    from evidence_store import StateLock
    from host_continuation import assert_execution_session
    repo = Path(args.repo).resolve()
    target = validate_id(args.task_id, "task id")
    ids = [validate_id(tid, "task id") for tid in args.from_task_id]
    if len(ids) not in (2, 3) or len(set(ids)) != len(ids) or target in ids:
        raise ValidationError("TASK_MERGE_INPUT: choose two or three distinct source tasks and a new destination task id.")
    apply = bool(args.apply)
    if apply and (not args.expect_preview or not args.proof_reference.strip()):
        raise ValidationError("TASK_MERGE_DECISION_REQUIRED: preview first, then apply with --expect-preview <sha256> and --proof-reference <developer choice>. This does not approve implementation.")
    root = workflow.state_root(repo)
    with StateLock(root):
        pending = root / "task-merge-pending.json"
        if pending.exists():
            journal = read_json(pending)
            if not apply or target != journal.get("task_id") or ids != [s["before"]["task_id"] for s in journal["sources"]] or args.expect_preview != journal.get("preview_sha256"):
                raise ValidationError("TASK_MERGE_RECOVERY_REQUIRED: repeat the original merge --apply command with its source ids and preview hash.")
            for tid in ids:
                assert_execution_session(repo, tid)
            return _finish_publication(repo, journal)
        if workflow.task_dir(repo, target).exists():
            raise ValidationError("TASK_MERGE_INPUT: destination task id already exists; choose a new id.")
        plans = [read_json(workflow.task_dir(repo, tid) / "plan.json") for tid in ids]
        for tid, plan in zip(ids, plans):
            if plan.get("task_id") != tid:
                raise ValidationError("TASK_MERGE_INPUT: source task identity mismatch.")
            reason = ineligible_reason(repo, tid, plan)
            if reason:
                raise ValidationError(f"TASK_MERGE_INELIGIBLE: {reason} Work in order, revise file scopes, or use a separate worktree.")
            if apply:
                assert_execution_session(repo, tid)
        _check_unchanged(repo, plans)
        combined = _combined_args(repo, target, plans)
        with tempfile.TemporaryDirectory(prefix="harness-merge-") as temporary:
            directory = Path(temporary) / "candidate"
            plan = workflow._build_and_save_plan(repo, combined, target, output_directory=directory,
                                                  scope_exclusions=tuple(ids), activate=False)
            decision_keys = {"mode", "source_family_id", "target_family_id", "family_signature_sha256",
                             "source_dimensions", "target_dimensions", "migration_allowed"}
            resolved = plan.get("architecture_contract") or {}
            for source in plans:
                original = source.get("architecture_contract") or {}
                if original and (any(original.get(k) != resolved.get(k) for k in decision_keys)
                                 or not set(original.get("compatibility_boundaries") or []) <= set(resolved.get("compatibility_boundaries") or [])):
                    raise ValidationError("TASK_MERGE_INCOMPATIBLE: combined scope resolves different architecture decisions; review a consolidated architecture plan before merging.")
            plan["merged_from"] = [{"task_id": p["task_id"], "plan_sha256": p["plan_sha256"]} for p in plans]
            # Instructions are pinned separately from authority in ordinary plans; retain every source pin.
            for p in plans:
                for instruction in p.get("developer_instructions") or []:
                    if instruction not in plan.setdefault("developer_instructions", []):
                        plan["developer_instructions"].append(instruction)
            plan["plan_sha256"] = canonical_sha256(plan_payload(plan))
            save_plan(directory / "plan.json", plan)
            policy = read_json(directory / "preliminary-policy.json")
            from plan_document import write_plan_document
            write_plan_document(repo, directory, plan, policy=policy)
            semantic = plan_payload(plan)
            semantic.pop("plan_id")  # New UUIDs differ between a read-only preview and its application.
            preview = canonical_sha256({"plan": semantic, "policy": policy, "instructions": plan.get("developer_instructions")})
            if not apply:
                return {"status": "MERGE_PREVIEW", "task_id": target, "merge_preview_sha256": preview,
                        "source_tasks": plan["merged_from"], "plan": plan, "policy": policy,
                        "plan_summary": workflow.plan_summary(plan),
                        "consequences": ["No task state or project files changed.", "Applying replaces the source plans with one new pending plan; source history remains readable.",
                                         "One fresh implementation approval is required. No approval, evidence or spending is transferred."],
                        "next_action": {"kind": "DEVELOPER_ACTION", "code": "CONFIRM_PLAN_MERGE", "command": "",
                                        "reason": "Present the combined goals, order, files, tests and policy. Apply only on the developer's explicit merge choice, bound to this preview hash."}}
            if args.expect_preview != preview:
                raise ValidationError("TASK_MERGE_PREVIEW_STALE: plans, repository inputs or policy changed; show a fresh preview before applying.")
            # Recheck source identities and application inputs after building the candidate.
            if any(read_json(workflow.task_dir(repo, tid) / "plan.json") != p for tid, p in zip(ids, plans)):
                raise ValidationError("TASK_MERGE_PREVIEW_STALE: a source task changed while preparing the merge.")
            _check_unchanged(repo, plans)
            staged = root.resolve() / "task-merges" / preview / "candidate"
            if staged.is_symlink() or staged.resolve() != staged:
                raise ValidationError("TASK_MERGE_RECOVERY_REQUIRED: staging path escapes the merge directory; preserve it for inspection.")
            if staged.exists():
                if (staged.parent / "receipt.json").exists():
                    raise ValidationError("TASK_MERGE_RECOVERY_REQUIRED: a completed merge already owns this preview; preserve its receipt.")
                # No pending journal exists while holding the state lock, so no source
                # changes could have started. Rebuild only this resolved, unpublished
                # candidate after an interrupted copy; canonical source plans stay intact.
                shutil.rmtree(staged)
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(directory, staged)
            provenance = {"source": args.source, "proof_reference_sha256": canonical_sha256({"reference": args.proof_reference}),
                          "merged_at": utc_now(), "preview_sha256": preview, "merged_into": target}
            sources = [{"before": p, "after": {**p, "status": "CANCELLED", "approval": None, "execution_nonce": None,
                                               "cancelled_at": provenance["merged_at"], "merge": provenance}} for p in plans]
            journal = {"schema_version": 1, "task_id": target, "preview_sha256": preview, "sources": sources, "plan": plan}
            journal["journal_sha256"] = canonical_sha256(journal)
            atomic_write_json(pending, journal)
            return _finish_publication(repo, journal)
