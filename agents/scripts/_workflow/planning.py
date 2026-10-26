"""Plan construction and persistence."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import engine as _engine


def _build_and_save_plan(
    repo: Path,
    args: argparse.Namespace,
    task_id: str,
    *,
    is_revision: bool = False,
    old_plan: dict | None = None,
    old_baseline: dict | None = None,
    old_plan_sha: str | None = None,
    output_directory: Path | None = None,
    scope_exclusions: tuple[str, ...] = (),
    activate: bool = True,
) -> dict:
    with _engine.step_progress("Classifying changed surfaces"):
        _engine.sublog("Inspecting working tree status and surface triggers...")
        classification = _engine.classify(repo)
        ch_files = classification.get("changed_files") or 0
        surfs = ", ".join(classification.get("surfaces") or []) or "none"
        _engine.sublog(f"Detected {ch_files} working tree changes, surfaces: {surfs}")
    raw_phases = getattr(args, "phases", None) or getattr(args, "phases_file", None)
    parsed_phases = _parse_plan_phases(repo, raw_phases)

    task_context_id = getattr(args, "task_context_id", None)
    cached_ctx = None
    has_explicit_target = bool(
        getattr(args, "architecture_target_scope", None)
        or getattr(args, "expected_files", None)
        or classification.get("changed_files", 0) > 0
    )
    if task_context_id or not has_explicit_target:
        cached_ctx = _engine._resolve_task_context_for_draft(repo, task_context_id)

    raw_expected_files = getattr(args, "expected_files", None)
    files_named_by_plan = bool(raw_expected_files) or any((phase.get("expected_files") or []) for phase in (parsed_phases or []))
    if not raw_expected_files and parsed_phases:
        # The phases name the files; the task context's single target file is not the scope (N2).
        raw_expected_files = [f for phase in parsed_phases for f in (phase.get("expected_files") or [])]
    if not raw_expected_files and cached_ctx and cached_ctx.get("target_file"):
        raw_expected_files = cached_ctx["target_file"]

    norm_expected_files = _engine.normalize_expected_files(repo, raw_expected_files)
    raw_expected = [item.strip() for item in (getattr(args, "expected_surfaces", None) or "").split(",") if item.strip()]
    expected = _engine.normalize_expected_surfaces(raw_expected)
    unknown_surfaces = sorted(set(expected) - _engine.KNOWN_SURFACES)
    if unknown_surfaces:
        raise _engine.ValidationError(
            f"unknown --expected-surfaces value(s): {', '.join(unknown_surfaces)}. "
            f"Valid surfaces: {', '.join(sorted(_engine.KNOWN_SURFACES))}. File paths belong in --expected-files."
        )
    if not expected:
        if cached_ctx and cached_ctx.get("candidate_surfaces") and not files_named_by_plan:
            expected = list(cached_ctx["candidate_surfaces"])
        elif norm_expected_files and files_named_by_plan:
            # The planned files, not the context file, set the surfaces (N2 residual). Each file is read
            # the way the write guard reads it: a tracked file's existing sign-in or purchase text does
            # not make the plan sensitive; its diff is judged at verification.
            planned_surfaces, unread = _engine._planned_file_surfaces(repo, norm_expected_files)
            expected = sorted(planned_surfaces | set(_engine._surfaces_from_paths(unread)))
        elif norm_expected_files:
            file_class = _engine.classify(repo, task_changes=[{"path": p} for p in norm_expected_files])
            expected = list(file_class.get("surfaces") or [])
            if not expected:
                expected = _engine._surfaces_from_paths(norm_expected_files)
        elif not classification.get("changed_files"):
            expected = list(_engine.DEFAULT_APP_SURFACES)
        else:
            expected = []



    # Phase Plan Enforcement
    LAYER_GROUPS = {
        "UI": {"COMPOSE_UI", "XML_UI", "RESOURCE_UI", "NAVIGATION"},
        "BUSINESS": {"BUSINESS_LOGIC", "COROUTINES", "PUBLIC_API"},
        "DATA": {"NETWORK", "PERSISTENCE", "ROOM_SCHEMA"},
        "PLATFORM": {"DEVICE_API", "MANIFEST_PERMISSION", "BUILD_CONFIG"},
    }
    DOC_RESOURCE_SUFFIXES = {
        ".md", ".txt", ".rst", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif",
        ".xml", ".json", ".properties", ".pro", ".ico"
    }
    impl_files = [f for f in norm_expected_files if _engine.Path(f).suffix.lower() not in DOC_RESOURCE_SUFFIXES]

    surfaces_for_layer_check = set(raw_expected)
    if not surfaces_for_layer_check and norm_expected_files:
        ef_class = _engine.classify(repo, task_changes=[{"path": p} for p in norm_expected_files])
        surfaces_for_layer_check = set(ef_class.get("surfaces") or [])

    # Exemptions: docs only, test-only, localization-only
    if surfaces_for_layer_check and surfaces_for_layer_check <= {"DOCS", "TEST_ONLY", "LOCALIZATION"}:
        spanned_layer_groups = set()
    else:
        spanned_layer_groups = {
            grp_name for grp_name, grp_surfaces in LAYER_GROUPS.items()
            if grp_surfaces & surfaces_for_layer_check
        }

    impl_modules = set()
    for f in impl_files:
        parts = f.replace("\\", "/").strip().lstrip("./").split("/")
        if len(parts) > 1 and "src" in parts:
            idx = parts.index("src")
            impl_modules.add("/".join(parts[:idx]))
        elif len(parts) > 1:
            impl_modules.add(parts[0])

    arch_intent = str(getattr(args, "architecture_intent", "EXISTING_CHANGE") or "EXISTING_CHANGE").upper()

    requires_phases = (
        (
            len(impl_files) > 8
            or len(impl_modules) > 1
            or arch_intent == "MIGRATION"
            or ("ROOM_SCHEMA" in surfaces_for_layer_check and len(impl_files) >= 2)
            or (len(spanned_layer_groups) >= 3 and len(impl_files) > 8)
        )
        and not getattr(args, "force", False)
    )
    if requires_phases and not parsed_phases:
        raise _engine.ValidationError(
            "PHASE_PLAN_REQUIRED: Task scope exceeds single-phase threshold "
            f"({len(impl_files)} implementation files, {len(impl_modules)} module(s), "
            f"arch_intent={arch_intent}, layer groups: {', '.join(sorted(spanned_layer_groups)) or 'none'}). "
            'Define semantic phases, for example --phases "p1:Introduce shared API,p2:Migrate feature callers". '
            "Replace the example titles with the task's semantic boundaries. "
            "A JSON list with id/title and optional expected_files is also supported; "
            "no helper file or shell redirection is needed."
        )

    raw_kind = str(getattr(args, "kind", None) or "AUTO").strip().upper()
    if raw_kind not in {"AUTO", "BUG", "FEATURE", "REFACTOR"}:
        raw_kind = "AUTO"
    if raw_kind == "AUTO":
        text_to_scan = f"{getattr(args, 'outcome', None) or ''} {getattr(args, 'expected_surfaces', None) or ''}".lower()
        if _engine.re.search(r"\b(?:bug|crash|fix|regression|error|fault|anr|issue|exception)\b", text_to_scan):
            resolved_kind = "BUG"
        else:
            resolved_kind = "FEATURE"
    else:
        resolved_kind = raw_kind
    if norm_expected_files and files_named_by_plan and raw_expected:
        expected = _engine._with_planned_file_surfaces(repo, expected, norm_expected_files, classification, resolved_kind,
                                               getattr(args, "outcome", None) or "")
    policy_input = dict(classification)
    policy_input["surfaces"] = expected
    verification_contract = getattr(args, "verification_contract", None)
    if verification_contract is not None:
        from verification_contract import load_definition, validate_contract
        if isinstance(verification_contract, str):
            verification_contract = load_definition(repo, verification_contract)
        verification_contract = validate_contract(verification_contract)

    with _engine.step_progress("Evaluating routing policy"):
        _engine.sublog(f"Evaluating review requirements for kind={resolved_kind}...")
        preliminary_policy = _engine.decide(policy_input, _engine.skills_root(repo), project_kind=_engine.project_kind(repo), task_kind=resolved_kind,
                                    plan={"verification_contract": verification_contract} if verification_contract is not None else None)
        raw_revs = preliminary_policy.get("reviewers")
        if isinstance(raw_revs, list):
            req_roles = ", ".join(str(r) for r in raw_revs) or "none"
        elif isinstance(raw_revs, dict):
            req_roles = ", ".join(str(r) for r in raw_revs.get("required_roles", [])) or "none"
        else:
            req_roles = "none"
        _engine.sublog(f"Routing policy resolved required reviewers: {req_roles}")

    # Resolve Evolutionary Architecture Contract
    arch_intent, architecture_scope_files, inferred_target_scope, arch_contract, arch_brief = _resolve_plan_architecture(
        repo, args, is_revision, norm_expected_files, parsed_phases, expected, raw_expected, classification, cached_ctx, preliminary_policy, resolved_kind
    )
    requested_outcome = getattr(args, "outcome", None) or (old_plan.get("requested_outcome") if old_plan else "")
    if not requested_outcome or not str(requested_outcome).strip():
        raise _engine.ValidationError("plan requested outcome must not be empty")
    requested_outcome = str(requested_outcome).strip()

    directory = output_directory or _engine.task_dir(repo, task_id)
    directory.mkdir(parents=True, exist_ok=True)
    if arch_brief:
        (directory / "task-architecture-brief.md").write_text(arch_brief, encoding="utf-8")

    def _modules_of_expected_files() -> set[str]:
        from plan_authority import discover_android_modules
        known_mods = sorted(
            ((_engine.module_id(item), _engine.module_id(item).lstrip(":").replace(":", "/")) for item in discover_android_modules(repo)),
            key=lambda item: len(item[1]), reverse=True,
        )
        found_mods: set[str] = set()
        for f in norm_expected_files:
            rel = f.replace("\\", "/").strip("/")
            matched = next((candidate for candidate, prefix in known_mods if prefix and (rel == prefix or rel.startswith(prefix + "/"))), None)
            found_mods.add(matched or ":")
        return found_mods

    raw_exp_mods = getattr(args, "expected_modules", None)
    if raw_exp_mods:
        declared_mods = {_engine.module_id(item) for item in str(raw_exp_mods).split(",") if item.strip()}
        # Planned files in another module are part of the plan; naming them avoids a later drift approval.
        resolved_expected_modules = sorted(declared_mods | (_modules_of_expected_files() if norm_expected_files else set()))
    elif cached_ctx and cached_ctx.get("module") and not files_named_by_plan:
        resolved_expected_modules = [_engine.module_id(cached_ctx["module"])]
    elif norm_expected_files:
        resolved_expected_modules = sorted(_modules_of_expected_files())
    else:
        resolved_expected_modules = []

    scoped_phase_review_val = None
    raw_spr = getattr(args, "scoped_phase_review", None)
    if raw_spr is not None:
        if isinstance(raw_spr, bool):
            scoped_phase_review_val = raw_spr
        elif str(raw_spr).lower() in ("true", "1", "yes"):
            scoped_phase_review_val = True
        elif str(raw_spr).lower() in ("false", "0", "no"):
            scoped_phase_review_val = False
    elif getattr(args, "scoped_phase_review_enabled", None) is not None:
        scoped_phase_review_val = bool(args.scoped_phase_review_enabled)

    zoho_link = _engine._parse_zoho_link(args)
    if is_revision and zoho_link is None and old_plan and old_plan.get("zoho_link"):
        zoho_link = old_plan["zoho_link"]

    if is_revision and old_baseline:
        # Approval binds to the tree the developer is reviewing now. The
        # original task baseline remains separate for task-delta attribution.
        base_manifest = _engine.build_manifest(repo)
        plan = _engine.create_plan(
            repo,
            task_id=task_id,
            task_kind=resolved_kind,
            planning_depth=str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper(),
            requested_outcome=requested_outcome,
            expected_surfaces=expected,
            expected_modules=resolved_expected_modules,
            expected_files=norm_expected_files,
            test_strategy=getattr(args, "test_strategy", None) or "Policy-selected relevant tests",
            device_strategy=getattr(args, "device_strategy", None) or "Policy-selected device verification",
            risks=[item.strip() for item in (getattr(args, "risks", None) or "").split(",") if item.strip()],
            rollback=getattr(args, "rollback", None) or "Stop on conflict; preserve developer changes; no automatic Git reset",
            skills=preliminary_policy["skills"]["skills"],
            external_writes=list(getattr(args, "external_write", None) or []),
            architecture_contract=arch_contract,
            phases=parsed_phases,
            base_manifest=base_manifest,
            supersedes_plan_sha256=old_plan_sha,
            revision_number=int((old_plan or {}).get("revision_number", 1)) + 1,
            zoho_link=zoho_link,
            scoped_phase_review_enabled=scoped_phase_review_val,
            approach=getattr(args, "approach", None) or "",
            verification_contract=verification_contract,
        )
        from review_budget import forecast_review_calls
        plan["review_budget_forecast"] = forecast_review_calls(plan, preliminary_policy)
        if (old_plan or {}).get("merged_from"):
            plan["merged_from"] = old_plan["merged_from"]
            plan["plan_sha256"] = _engine.canonical_sha256(_engine.plan_payload(plan))
        plan["task_baseline"] = old_baseline
        plan["status"] = "AWAITING_DEVELOPER_APPROVAL"
        _engine.assert_disjoint_task_scope(repo, task_id, plan, exclude_task_ids=scope_exclusions)
        for key in ("review_calls_used", "review_rounds", "final_review_call_charges"):
            if key in (old_plan or {}):
                plan[key] = old_plan[key]
        if cached_ctx and cached_ctx.get("context_id"):
            plan["task_context_id"] = cached_ctx["context_id"]
        elif task_context_id:
            plan["task_context_id"] = task_context_id
        plan["developer_instructions"] = _engine._applicable_developer_instructions_for_task(repo, cached_ctx, inferred_target_scope, arch_intent)
        # Reject non-material revisions before touching phase progress or baselines.
        if (old_plan or {}).get("approval") and _engine._same_plan(old_plan, plan):
            return old_plan
        if (old_plan or {}).get("approval"):
            # Prose can describe new requirements, so never silently adopt it as
            # a clarification. Require an explicit explanation before reapproval.
            before, after = _engine.plan_payload(old_plan), _engine.plan_payload(plan)
            lineage = {"plan_id", "supersedes_plan_sha256", "base_delivery_snapshot_sha256",
                       "base_change_set_sha256", "base_file_identities", "base_change_identities",
                       "base_external_inputs_sha256"}
            changed = {key for key in set(before) | set(after)
                       if key not in lineage and before.get(key) != after.get(key)}
            narrative = {"requested_outcome", "approach", "risks", "rollback", "test_strategy", "device_strategy"}
            reason = str(getattr(args, "material_change_reason", None) or "").strip()
            if changed and changed <= narrative and not reason:
                raise _engine.ValidationError(
                    "PLAN_NOTE_REQUIRED: do not restart an approved task to clarify its description or fix review findings. "
                    "Use task plan-note --text <clarification> --source conversation --proof-reference <decision>. "
                    "For genuinely changed requirements, repeat revise with --material-change-reason <concrete expansion>; "
                    "the revised plan still requires developer approval."
                )
            if reason:
                plan["material_change_reason"] = reason
        # Completed phases are checked against the plan they were reviewed under, before the
        # revision replaces it; checked afterwards, every review proof reads as stale (N4).
        if parsed_phases:
            phase_state_file = directory / "phase-state.json"
            old_state = _engine.read_json(phase_state_file) if phase_state_file.is_file() else {}
            old_phases = (old_plan or {}).get("phases") or []
            preserved: list[str] = []
            from phase_review import phase_path_states, validate_completed_phase_review_proof
            # Once every phase completed, final integration gates own later
            # corrections. Keep historical proof; never re-label it as live PASS.
            historical = bool(old_phases) and old_phases == parsed_phases and all(
                phase["id"] in (old_state.get("completed_phases") or []) for phase in old_phases
            )

            for old_phase, new_phase in zip(old_phases, parsed_phases):
                phase_id = new_phase["id"]
                if old_phase != new_phase or phase_id not in (old_state.get("completed_phases") or []):
                    break
                checkpoint_file = directory / "phases" / phase_id / "checkpoint.json"
                try:
                    checkpoint = _engine.read_json(checkpoint_file)
                    checkpoint_sha = checkpoint.get("checkpoint_sha256")
                    if (
                        checkpoint.get("status") != "CHECKPOINT_PASS"
                        or checkpoint_sha != _engine.canonical_sha256({k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"})
                        or old_state.get("phase_checkpoints", {}).get(phase_id) != checkpoint_sha
                        or (not historical and checkpoint.get("phase_path_states") != phase_path_states(repo, checkpoint.get("manifest_delta") or []))
                    ):
                        break
                    if (checkpoint.get("review") or {}).get("status") == "REVIEW_PACKAGE_REQUIRED":
                        validate_completed_phase_review_proof(repo, task_id, phase_id, checkpoint_sha,
                                                              historical_for_final=historical)
                except (OSError, ValueError, _engine.ValidationError):
                    break
                preserved.append(phase_id)

        _engine.save_plan(directory / "plan.json", plan)
        _engine.atomic_write_json(directory / "preliminary-classification.json", classification)
        _engine.atomic_write_json(directory / "preliminary-policy.json", preliminary_policy)
        _engine.atomic_write_json(_engine.state_root(repo) / "active-task.json", {"task_id": task_id, "plan_path": str(directory / "plan.json"), "updated_at": _engine.utc_now()})
        if parsed_phases:
            phase_state_file = directory / "phase-state.json"
            next_index = min(len(preserved), len(parsed_phases) - 1)
            next_id = parsed_phases[next_index]["id"]
            # A pre-existing phase baseline is required to distinguish prior
            # completed work from edits to the still-active phase.
            if preserved and len(preserved) < len(parsed_phases) and not (directory / "phases" / next_id / "baseline.json").is_file():
                preserved = []
                next_index = 0
                next_id = parsed_phases[0]["id"]
            # A later phase's baseline is the snapshot at which the phase before it completed. Once that
            # phase is no longer complete, the baseline belongs to an invalidated pass: keep it as
            # history and let begin-next-phase derive a fresh one (N14).
            for index, later in enumerate(parsed_phases):
                stale_baseline = directory / "phases" / later["id"] / "baseline.json"
                if index > len(preserved) and stale_baseline.is_file():
                    history = stale_baseline.parent / "baseline-history"
                    history.mkdir(parents=True, exist_ok=True)
                    stale_baseline.replace(history / f"{_engine.utc_now().replace(':', '')}-{_engine.canonical_sha256(_engine.read_json(stale_baseline))[:12]}.json")
            plan["active_phase_index"] = next_index
            _engine.atomic_write_json(phase_state_file, {
                "current_phase_id": next_id,
                "completed_phases": preserved,
                "phase_checkpoints": {key: old_state.get("phase_checkpoints", {})[key] for key in preserved},
                "phase_substates": {key: {"substate": "COMPLETE", "updated_at": _engine.utc_now()} for key in preserved},
                "substate": "COMPLETE" if next_id in preserved else "IMPLEMENTING",
            })
            _engine.save_plan(directory / "plan.json", plan)
        return plan

    plan = _engine.create_plan(
        repo,
        task_id=task_id,
        task_kind=resolved_kind,
        planning_depth=str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper(),
        requested_outcome=requested_outcome,
        expected_surfaces=expected,
        expected_modules=resolved_expected_modules,
        expected_files=norm_expected_files,
        test_strategy=getattr(args, "test_strategy", None) or "Policy-selected relevant tests",
        device_strategy=getattr(args, "device_strategy", None) or "Policy-selected device verification",
        risks=[item.strip() for item in (getattr(args, "risks", None) or "").split(",") if item.strip()],
        rollback=getattr(args, "rollback", None) or "Stop on conflict; preserve developer changes; no automatic Git reset",
        skills=preliminary_policy["skills"]["skills"],
        external_writes=list(getattr(args, "external_write", None) or []),
        architecture_contract=arch_contract,
        phases=parsed_phases,
        zoho_link=zoho_link,
        scoped_phase_review_enabled=scoped_phase_review_val,
        approach=getattr(args, "approach", None) or "",
        verification_contract=verification_contract,
    )
    from review_budget import forecast_review_calls
    plan["review_budget_forecast"] = forecast_review_calls(plan, preliminary_policy)
    if cached_ctx and cached_ctx.get("context_id"):
        plan["task_context_id"] = cached_ctx["context_id"]
    elif task_context_id:
        plan["task_context_id"] = task_context_id
    plan["developer_instructions"] = _engine._applicable_developer_instructions_for_task(repo, cached_ctx, inferred_target_scope, arch_intent)

    # Bind compact discovery provenance (D1/D2/D3) if available
    disc_receipt = None
    try:
        from discovery_receipt import load_latest_discovery_receipt, check_discovery_freshness
        disc_receipt = load_latest_discovery_receipt(repo)
    except Exception:
        disc_receipt = None

    explicit_targets = set(architecture_scope_files)
    explicit_scope = str(getattr(args, "architecture_target_scope", "") or "").replace("\\", "/").strip().strip("/")
    if disc_receipt and (explicit_targets or explicit_scope):
        # An explicit target outranks whatever was queried last; only a receipt
        # about that target may become this task's discovery provenance.
        receipt_paths = {str(p).replace("\\", "/").strip("/") for p in disc_receipt.get("resolved_paths") or []}
        receipt_paths.add(str((disc_receipt.get("query") or {}).get("value") or "").replace("\\", "/").strip("/"))
        if not (receipt_paths & explicit_targets) and not (explicit_scope and explicit_scope in receipt_paths):
            disc_receipt = None

    if disc_receipt:
        fresh, fresh_msg = check_discovery_freshness(repo, disc_receipt)
        if not fresh:
            raise _engine.ValidationError(f"DISCOVERY_REFRESH_REQUIRED: {fresh_msg}")
        plan["discovery_provenance"] = {
            "discovery_id": str(disc_receipt.get("id") or ""),
            "discovery_mode": str(disc_receipt.get("mode") or ""),
            "graph_fingerprint": str(disc_receipt.get("graph_fingerprint") or ""),
            "primary_target": str((disc_receipt.get("query") or {}).get("value") or ""),
        }

    _engine.assert_disjoint_task_scope(repo, task_id, plan, exclude_task_ids=scope_exclusions)
    _engine.save_plan(directory / "plan.json", plan)
    _engine.atomic_write_json(directory / "preliminary-classification.json", classification)
    _engine.atomic_write_json(directory / "preliminary-policy.json", preliminary_policy)
    if activate:
        _engine.atomic_write_json(_engine.state_root(repo) / "active-task.json", {"task_id": task_id, "plan_path": str(directory / "plan.json"), "updated_at": _engine.utc_now()})

    return _save_initial_baseline(repo, task_id, directory, plan, parsed_phases)


def _parse_plan_phases(repo, raw_phases):
    parsed_phases = None
    if raw_phases:
        if isinstance(raw_phases, list):
            parsed_phases = raw_phases
        elif isinstance(raw_phases, str):
            s = raw_phases.strip()
            if not s.startswith(("[", "{")) and (s.endswith(".json") or (repo / s).is_file() or _engine.Path(s).is_file() or ".." in s or _engine.Path(s).is_absolute()):
                rel_posix = _engine.validate_repo_path_containment(repo, s)
                p_file = repo / rel_posix
                if not p_file.is_file():
                    raise _engine.ValidationError(f"phases file not found: {s}")
                try:
                    loaded = _engine.json.loads(p_file.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise _engine.ValidationError(f"invalid --phases file: {exc}")
            else:
                loaded = None
                # Tier 1: direct json.loads
                try:
                    loaded = _engine.json.loads(s)
                except (OSError, ValueError, _engine.ValidationError):
                    pass
                # Tier 2: clean powershell escaped quotes and outer wrapping quotes
                if loaded is None:
                    cleaned = s
                    if (cleaned.startswith("'") and cleaned.endswith("'")) or (cleaned.startswith('"') and cleaned.endswith('"')):
                        cleaned = cleaned[1:-1].strip()
                    cleaned = cleaned.replace(r'\"', '"')
                    try:
                        loaded = _engine.json.loads(cleaned)
                    except (OSError, ValueError, _engine.ValidationError):
                        pass
                # Tier 3: ast.literal_eval for python-style dict/list representations
                if loaded is None:
                    import ast
                    try:
                        loaded = ast.literal_eval(cleaned if "cleaned" in locals() else s)
                    except (OSError, ValueError, SyntaxError, _engine.ValidationError):
                        pass
                # Tier 4: comma-separated list like "p1:Setup, p2:Implementation" or "p1, p2"
                if loaded is None and not s.startswith(("[", "{")):
                    parts = [p.strip() for p in s.split(",") if p.strip()]
                    if parts:
                        loaded = []
                        for part in parts:
                            if ":" in part:
                                pid, pdesc = part.split(":", 1)
                                loaded.append({"id": pid.strip(), "description": pdesc.strip()})
                            else:
                                loaded.append({"id": part, "description": f"Phase {part}"})
                if loaded is None:
                    raise _engine.ValidationError(
                        "invalid --phases parameter: use a JSON list with an id and title for each phase, "
                        'or --phases "p1:Introduce shared API,p2:Migrate feature callers". '
                        "Use semantic phase titles for this task; no helper file or shell redirection is needed."
                    )
            if isinstance(loaded, list):
                parsed_phases = loaded
            elif isinstance(loaded, dict) and isinstance(loaded.get("phases"), list):
                parsed_phases = loaded["phases"]
            else:
                raise _engine.ValidationError("phases JSON must be a list of phases or an object with a 'phases' list")

        if parsed_phases is not None:
            parsed_phases = _engine.validate_phases(repo, parsed_phases)
    return parsed_phases


def _resolve_plan_architecture(repo, args, is_revision, norm_expected_files, parsed_phases, expected, raw_expected, classification, cached_ctx, preliminary_policy, resolved_kind):
    arch_intent = str(getattr(args, "architecture_intent", "EXISTING_CHANGE") or "EXISTING_CHANGE").upper()
    architecture_scope_files = list(norm_expected_files)
    for phase in parsed_phases or []:
        architecture_scope_files.extend(phase.get("expected_files") or [])
    if not is_revision:
        _engine._require_plan_files(repo, architecture_scope_files, preliminary_policy, resolved_kind)

    target_surfaces = set(expected) if expected else set(raw_expected)
    if not target_surfaces and norm_expected_files:
        ef_class = _engine.classify(repo, task_changes=[{"path": p} for p in norm_expected_files])
        target_surfaces = set(ef_class.get("surfaces") or [])

    architecture_neutral_exempt = _engine.is_architecture_neutral_scope(
        scope_files=architecture_scope_files,
        surfaces=target_surfaces,
        arch_intent=arch_intent,
        target_scope=getattr(args, "architecture_target_scope", None),
        target_family=getattr(args, "architecture_target_family", None),
    )
    inferred_target_scope = str(getattr(args, "architecture_target_scope", "") or "").strip()
    if not inferred_target_scope and arch_intent != "MIGRATION":
        if norm_expected_files:
            from _modules import is_kmp_or_android_test_path
            impl_candidates = [
                p for p in norm_expected_files
                if not _engine.is_documentation_path(p)
                and not is_kmp_or_android_test_path(p)
            ]
            eval_files = impl_candidates or norm_expected_files
            if len(eval_files) == 1:
                inferred_target_scope = eval_files[0]
            else:
                primary = next(
                    (p for p in eval_files if any(k in p.lower() for k in ("view", "fragment", "screen", "activity", "composable"))),
                    eval_files[0]
                )
                inferred_target_scope = primary
        elif classification.get("changed_files", 0) >= 1:
            all_files = sorted(set(p for info in (classification.get("details") or {}).values() for p in info.get("files") or []))
            if len(all_files) == 1:
                inferred_target_scope = all_files[0]
            elif all_files:
                primary = next(
                    (p for p in all_files if any(k in p.lower() for k in ("view", "fragment", "screen", "activity", "composable"))),
                    all_files[0]
                )
                inferred_target_scope = primary
        elif getattr(args, "expected_modules", None):
            exp_mods = [m.strip() for m in str(args.expected_modules).split(",") if m.strip()]
            if len(exp_mods) == 1:
                inferred_target_scope = exp_mods[0]

        if not inferred_target_scope:
            if cached_ctx and cached_ctx.get("target_file"):
                inferred_target_scope = cached_ctx["target_file"]
            else:
                last_ctx_file = repo / ".agents" / "cache" / "last-task-context.json"
                if last_ctx_file.is_file():
                    try:
                        ctx_data = _engine.json.loads(last_ctx_file.read_text(encoding="utf-8"))
                        if _engine.time.time() - float(ctx_data.get("timestamp", 0)) < 1800:
                            cand = str(ctx_data.get("file") or "").strip()
                            if cand and (repo / cand).is_file():
                                inferred_target_scope = cand
                    except (OSError, ValueError, _engine.ValidationError):
                        pass

    from architecture_resolver import (
        resolve_architecture_contract,
        STATUS_RESOLVED,
    )
    if arch_intent == "MIGRATION":
        p_depth = str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper()
        if p_depth != "ARCHITECTURAL":
            raise _engine.ValidationError("architecture migration requires planning_depth=ARCHITECTURAL")
        if not inferred_target_scope:
            raise _engine.ValidationError("architecture migration requires a non-empty target scope")

    arch_contract = None
    arch_brief = None
    if not architecture_neutral_exempt:
        with _engine.step_progress("Resolving architecture contract"):
            _engine.sublog(f"Resolving architecture contract (intent={arch_intent}, scope='{inferred_target_scope or 'auto'}')...")
            arch_res = resolve_architecture_contract(
                repo,
                architecture_intent=arch_intent,
                target_scope=inferred_target_scope,
                target_family_id=getattr(args, "architecture_target_family", None),
                planning_depth=str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper(),
            )
            if arch_res["status"] != STATUS_RESOLVED:
                raise _engine.ValidationError(f"architecture contract resolution failed ({arch_res['status']}): {arch_res['message']}")

            arch_contract = arch_res.get("contract")
            arch_brief = arch_res.get("brief_markdown")
            fam_label = (arch_contract.get("family_id") or "standard") if arch_contract else "none"
            _engine.sublog(f"Architecture contract resolved successfully (family={fam_label}).")

    return arch_intent, architecture_scope_files, inferred_target_scope, arch_contract, arch_brief


def _save_initial_baseline(repo, task_id, directory, plan, parsed_phases):
    base_man = _engine.build_manifest(repo)
    sensitive_changes = []
    try:
        raw_status = _engine.git(repo, "status", "--porcelain=v2", "-z", "-u", "--untracked-files=all")
        secret_markers = (".env", "keystore", "jks", "secret", "token", "credentials", "local.properties")
        chunks = raw_status.split(b"\0")
        idx = 0
        while idx < len(chunks):
            chunk = chunks[idx]
            idx += 1
            if not chunk:
                continue
            line = chunk.decode("utf-8", errors="surrogateescape")
            rel = ""
            if line.startswith("1 "):
                parts = line.split(" ", 8)
                if len(parts) >= 9:
                    rel = parts[8]
            elif line.startswith("2 "):
                parts = line.split(" ", 9)
                if len(parts) >= 10:
                    rel = parts[9]
                idx += 1
            elif line.startswith("? "):
                rel = line[2:]
            rel_norm = rel.replace("\\", "/").strip("/")
            if rel_norm and any(m in rel_norm.lower() for m in secret_markers):
                p = repo / rel_norm
                if p.is_file():
                    h_oid = _engine.git_text(repo, "hash-object", "--path", rel_norm, "--stdin", input_bytes=p.read_bytes()).strip()
                    sensitive_changes.append({"path": rel_norm, "content_identity": f"git:{h_oid}"})
    except (OSError, ValueError, _engine.ValidationError):
        pass

    task_baseline = {
        "schema_version": 1,
        "task_id": task_id,
        "repository": plan.get("repository"),
        "base_delivery_snapshot_sha256": plan.get("base_delivery_snapshot_sha256"),
        "base_change_set_sha256": plan.get("base_change_set_sha256"),
        "changes": base_man.get("changes") or [],
        "sensitive_changes": sensitive_changes,
    }
    task_baseline["baseline_sha256"] = _engine.canonical_sha256({
        "schema_version": task_baseline["schema_version"],
        "task_id": task_baseline["task_id"],
        "repository": task_baseline["repository"],
        "base_delivery_snapshot_sha256": task_baseline["base_delivery_snapshot_sha256"],
        "base_change_set_sha256": task_baseline["base_change_set_sha256"],
        "changes": task_baseline["changes"],
    })
    _engine.atomic_write_json(directory / "task-baseline.json", task_baseline)
    plan["task_baseline"] = task_baseline
    _engine.save_plan(directory / "plan.json", plan)

    # Snapshot pre-existing dirty files
    baseline_files_dir = directory / "baseline-files"
    secret_markers = (".env", "keystore", "jks", "secret", "token", "credentials", "local.properties")
    binary_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ttf", ".otf", ".wav", ".mp3", ".ogg", ".mp4", ".jar", ".aar", ".so", ".apk"}
    for entry in task_baseline["changes"]:
        rel = entry.get("path")
        if not rel:
            continue
        rel_norm = rel.replace("\\", "/")
        if any(m in rel_norm.lower() for m in secret_markers):
            continue
        fpath = repo / rel
        if not fpath.is_file() or fpath.is_symlink():
            continue
        if fpath.suffix.lower() in binary_suffixes:
            continue
        try:
            if fpath.stat().st_size <= 2 * 1024 * 1024:
                dest = baseline_files_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                _engine.shutil.copy2(fpath, dest)
        except OSError:
            pass

    if parsed_phases:
        _engine.atomic_write_json(directory / "phase-state.json", {
            "current_phase_id": parsed_phases[0]["id"],
            "completed_phases": [],
            "phase_checkpoints": {},
        })
        p1_dir = directory / "phases" / parsed_phases[0]["id"]
        p1_dir.mkdir(parents=True, exist_ok=True)
        _engine.atomic_write_json(p1_dir / "baseline.json", task_baseline)

    return plan

