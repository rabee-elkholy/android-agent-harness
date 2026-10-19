"""Implementation routing for sequential, checkpointed task phases."""
from __future__ import annotations

from . import engine as _engine


def phase_implementation_action(repo, task_id, plan, run_host, identity, tdir, phases):
    from phase_review import (
        get_phase_substate,
        set_phase_substate,
        is_phase_review_needed,
        check_phase_safety_cap,
        load_phase_ledger,
        phase_dir,
        phase_review_dir,
        phase_run_file,
        phase_ledger_file,
        PHASE_IMPLEMENTING,
        PHASE_CHECKS_PASSED,
        PHASE_REVIEW_PACKAGE_REQUIRED,
        PHASE_REVIEWING,
        PHASE_REVIEW_BLOCKED,
        PHASE_COMPLETE,
    )
    from review_orchestrator import (
        REVIEW_NOT_DISPATCHED,
        REVIEW_DISPATCHED,
        REVIEW_COMPLETED,
        REVIEW_ENV_BLOCKED,
        REVIEW_FAILED_PROTOCOL,
        REVIEW_PROTOCOL_RETRY_REQUIRED,
    )

    phase_state_f = tdir / "phase-state.json"
    p_state = _engine.read_json(phase_state_f) if phase_state_f.is_file() else {
        "current_phase_id": phases[0]["id"],
        "completed_phases": [],
        "phase_checkpoints": {},
    }
    try:
        active_idx = int(plan.get("active_phase_index") or 0)
    except (TypeError, ValueError):
        active_idx = 0
    active_idx = max(0, min(active_idx, len(phases) - 1))
    cur_phase = phases[active_idx] if isinstance(phases[active_idx], dict) else {}
    phase_id = str(cur_phase.get("id") or p_state.get("current_phase_id") or "")
    substate = get_phase_substate(p_state, phase_id)

    completed_set = set(p_state.get("completed_phases") or [])
    all_done = all(p.get("id") in completed_set for p in phases)
    if all_done or substate == PHASE_COMPLETE:
        try:
            _engine.validated_completed_phase_manifest(repo, task_id, plan, p_state, cur_phase)
        except Exception as exc:
            stale = isinstance(exc, _engine.ValidationError) and str(exc).startswith("phase checkpoint is stale")
            return {
                "code": "CHECKPOINT_PHASE" if stale else "PHASE_CHECKPOINT_STATE_BLOCKED",
                "kind": "HARNESS_COMMAND" if stale else "HARNESS_DIAGNOSTIC",
                "command": f'python .agents/harness.py task checkpoint-phase {identity} --phase-id "{phase_id}"' if stale else "",
                "blocking": True,
                "reason": f"Completed phase '{phase_id}' cannot advance: {exc}",
                "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
                "expected": {"success_statuses": ["CHECKPOINT_PASS"]} if stale else {},
            }
    if all_done:
        return {
            "code": "PREPARE_VERIFICATION",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task prepare-verification {identity} --host {run_host}",
            "blocking": True,
            "reason": "All implementation phases complete. Freeze change set and prepare final verification.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_statuses": ["VERIFYING"]},
        }

    if substate == PHASE_REVIEW_BLOCKED:
        return {
            "code": "FIX_PHASE_FINDINGS",
            "kind": "MODEL_ACTION",
            "command": "",
            "blocking": True,
            "reason": f"Phase '{phase_id}' review identified findings. Fix defects in active phase before re-checkpointing.",
            "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
            "expected": {},
        }

    if substate == PHASE_REVIEW_PACKAGE_REQUIRED:
        return {
            "code": "BUILD_PHASE_REVIEW_PACKAGE",
            "kind": "HARNESS_COMMAND",
            "command": f'python .agents/harness.py phase-review package --repo . --task-id {task_id} --phase-id "{phase_id}" --host {run_host}',
            "blocking": True,
            "reason": f"Build immutable phase review package for phase '{phase_id}'.",
            "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
            "expected": {"success_exit_codes": [0]},
        }

    if substate == PHASE_REVIEWING:
        lpath = phase_ledger_file(tdir, phase_id)
        prun_f = phase_run_file(tdir, phase_id)
        try:
            run_meta = _engine.read_json(prun_f) if prun_f.is_file() else None
        except Exception:
            run_meta = None
        if not isinstance(run_meta, dict) or (
            run_meta.get("task_id") != task_id
            or run_meta.get("phase_id") != phase_id
            or not run_meta.get("phase_review_run_id")
        ):
            return {
                "code": "PHASE_REVIEW_STATE_BLOCKED",
                "kind": "HARNESS_DIAGNOSTIC",
                "blocking": True,
                "reason": "Phase REVIEWING state has a missing, corrupt, or mismatched active review run. Re-checkpoint the phase after diagnosis.",
                "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
                "expected": {},
            }
        run_id = str(run_meta["phase_review_run_id"])
        roster = run_meta.get("selected_reviewers")
        if (
            not isinstance(roster, list) or not roster
            or not all(isinstance(r, str) and r for r in roster)
            or len(roster) != len(set(roster))
        ):
            return {
                "code": "PHASE_REVIEW_STATE_BLOCKED",
                "kind": "HARNESS_DIAGNOSTIC",
                "blocking": True,
                "reason": "Phase review run has an invalid reviewer roster. Re-checkpoint the phase after diagnosis.",
                "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
                "expected": {},
            }
        ok, err, ledger = load_phase_ledger(
            tdir, phase_id, expected_run_id=run_id,
            expected_task_id=task_id, expected_reviewers=roster,
        )
        if not ok or not ledger:
            return {
                "code": "PHASE_REVIEW_LEDGER_BLOCKED",
                "kind": "HARNESS_DIAGNOSTIC",
                "blocking": True,
                "reason": f"Phase review ledger missing, corrupt, or mismatched: {err}",
                "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
                "expected": {},
            }

        # Check for durable post-tool reconciliation error marker
        rdir = phase_review_dir(tdir, phase_id)
        marker_1 = rdir / "post-tool-reconcile-error.json"
        marker_2 = rdir / run_id / "post-tool-reconcile-error.json" if run_id else None
        if marker_1.is_file() or (marker_2 and marker_2.is_file()):
            return {
                "code": "PHASE_REVIEW_ENV_BLOCKED",
                "kind": "HARNESS_DIAGNOSTIC",
                "blocking": True,
                "reason": "Phase reviewer subagent launch failed and post-tool reconciliation encountered an error.",
                "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
                "expected": {},
            }

        if lpath.is_file():
            ok, err, ledger = load_phase_ledger(tdir, phase_id, expected_run_id=run_id or None)
            if not ok or not ledger:
                return {
                    "code": "PHASE_REVIEW_LEDGER_BLOCKED",
                    "kind": "HARNESS_DIAGNOSTIC",
                    "blocking": True,
                    "reason": f"Phase review ledger corrupted or invalid: {err}",
                    "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
                    "expected": {},
                }

            revs = ledger.get("reviewers") or {}
            from reviewer_host import lifecycle_action
            host_action = lifecycle_action(repo, run_meta, revs)
            if host_action:
                return host_action

            # 1. Environment blocked reviewers
            for r_name, r_info in revs.items():
                if r_info.get("state") == REVIEW_ENV_BLOCKED:
                    return {
                        "code": "PHASE_REVIEW_ENV_BLOCKED",
                        "kind": "HARNESS_DIAGNOSTIC",
                        "blocking": True,
                        "reason": f"Phase reviewer '{r_name}' launch/execution blocked by host environment: {r_info.get('last_error') or 'launch failed'}.",
                        "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
                        "expected": {},
                    }

            # 2. Failed protocol reviewers
            for r_name, r_info in revs.items():
                if r_info.get("state") == REVIEW_FAILED_PROTOCOL:
                    return {
                        "code": "PHASE_REVIEW_PROTOCOL_BLOCKED",
                        "kind": "HARNESS_DIAGNOSTIC",
                        "blocking": True,
                        "reason": f"Phase reviewer '{r_name}' failed review protocol repeatedly: {r_info.get('last_error')}.",
                        "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
                        "expected": {},
                    }

            # 3. Protocol retry required
            for r_name, r_info in revs.items():
                if r_info.get("state") == REVIEW_PROTOCOL_RETRY_REQUIRED:
                    exec_id = str(r_info.get("execution_id") or "")
                    err_msg = str(r_info.get("last_error") or r_info.get("protocol_error") or "")
                    phase_host = str(run_meta.get("review_host") or run_host)
                    if not _engine.has_trusted_review_source(phase_host):
                        return {
                            "code": "RETRY_PHASE_REVIEW_RESPONSE",
                            "kind": "HOST_ACTION",
                            "command": (
                                f"python .agents/harness.py phase-review complete --repo . --task-id {task_id} "
                                f"--phase-id {phase_id} --reviewer {r_name} --execution-id {exec_id} "
                                f"--host {phase_host} --response-file <corrected-response-file>"
                            ),
                            "blocking": True,
                            "reason": f"Obtain a corrected response from the same reviewer execution and ingest it: {err_msg}.",
                            "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id, "reviewer": r_name, "execution_id": exec_id},
                            "expected": {},
                        }
                    correction_msg = (
                        f"Protocol error from `{r_name}`: {err_msg}.\n"
                        "Please submit your review conforming strictly to HARNESS_REVIEW_RESULT_V2 JSON format."
                    )
                    return {
                        "action": "send_message",
                        "code": "RETRY_PHASE_REVIEW_PROTOCOL",
                        "kind": "HOST_ACTION",
                        "command": "send_message",
                        "blocking": True,
                        "reason": f"Protocol retry required for phase reviewer '{r_name}': {err_msg}.",
                        "reviewer": r_name,
                        "recipient": exec_id,
                        "message": correction_msg,
                        "retry_prompt": correction_msg,
                        "inputs": {
                            "repo": ".",
                            "task_id": task_id,
                            "phase_id": phase_id,
                            "reviewer": r_name,
                            "recipient": exec_id,
                            "message": correction_msg,
                            "send_message": {
                                "recipient": exec_id,
                                "prompt": correction_msg,
                            },
                        },
                        "expected": {},
                    }

            # 4. Not yet dispatched
            not_dispatched = [r for r, d in revs.items() if d.get("state") == REVIEW_NOT_DISPATCHED]
            if not_dispatched:
                checkpoint_file = phase_dir(tdir, phase_id) / "checkpoint.json"
                reserve = (_engine.read_json(checkpoint_file).get("final_review_reserve") or {}) if checkpoint_file.is_file() else {}
                cap_ok, cap_msg = check_phase_safety_cap(plan, len(not_dispatched), reserve, repo=repo)
                if not cap_ok:
                    return {
                        "code": "REVIEWER_CALL_SAFETY_CAP_REACHED",
                        "kind": "DEVELOPER_ACTION",
                        "command": "",
                        "blocking": True,
                        "reason": cap_msg + " Ask the developer for a higher call limit, then record that explicit answer with "
                                  "`task review-budget --task-id " + task_id + " --limit <approved limit> --source conversation "
                                  "--proof-reference <developer answer>`. Never edit policy, phase state or engine files, "
                                  "mark unfinished review COMPLETE, or offer review bypass as a remedy.",
                        "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
                        "expected": {},
                    }

                run_meta = _engine.read_json(prun_f) if prun_f.is_file() else {}
                briefs = run_meta.get("briefs") or {}
                phase_host = str(run_meta.get("review_host") or run_host)
                dispatch_receipt_command = ""
                if not _engine.has_trusted_review_source(phase_host):
                    roster_args = " ".join(f"--reviewer {reviewer}" for reviewer in sorted(not_dispatched))
                    dispatch_receipt_command = (
                        f"python .agents/harness.py phase-review dispatch --repo . --task-id {task_id} "
                        f"--phase-id {phase_id} --host {phase_host} {roster_args}"
                    )
                exec_profile = {
                    "model_policy": "INHERIT_PARENT_BY_OMISSION" if _engine.has_trusted_review_source(str(run_meta.get("review_host") or "")) else "HOST_MANAGED_UNVERIFIED",
                    "workspace": "inherit",
                    "reviewers": {
                        r: {"role": r, "type_name": r, "brief_path": briefs.get(r, "")}
                        for r in not_dispatched
                    },
                }

                from review_models import effective_reviewer_model, format_reviewers_with_models, frozen_models, reviewer_model_map
                try:
                    frozen_selections = frozen_models(run_meta)
                except (_engine.ValidationError, OSError, ValueError) as exc:
                    return {"code": "REVIEW_PROFILE_BLOCKED", "kind": "HOST_ACTION", "command": "", "blocking": True,
                            "reason": str(exc), "inputs": {"task_id": task_id, "phase_id": phase_id}, "expected": {}}
                for role, selection in frozen_selections.items():
                    if role in exec_profile["reviewers"]:
                        exec_profile["reviewers"][role].update(selection)
                for role, r_info in exec_profile["reviewers"].items():
                    r_info["effective_model"] = effective_reviewer_model(r_info)
                dispatch_models = reviewer_model_map(exec_profile, sorted(not_dispatched))
                dispatch_with_models = format_reviewers_with_models(exec_profile, sorted(not_dispatched))
                exec_profile["reviewer_models"] = dispatch_models
                if any(r.get("model_policy") == "DEVELOPER_SELECTED_NATIVE" for r in exec_profile["reviewers"].values()):
                    exec_profile["model_policy"] = "DEVELOPER_SELECTED_NATIVE"
                before_first_dispatch = None
                if (
                    str(phase_host).strip().lower() == "antigravity"
                    and (run_meta.get("review_models") or {}).get("source", "default") == "default"
                    and len(not_dispatched) == len(revs)
                ):
                    from review_models import build_antigravity_model_prompt
                    before_first_dispatch = build_antigravity_model_prompt(
                        repo,
                        task_id,
                        sorted(not_dispatched),
                        run_id=str(run_meta.get("phase_review_run_id") or ""),
                        phase_id=phase_id,
                    )
                    exec_profile["reviewer_model_prompt"] = before_first_dispatch

                return {
                    "code": "DISPATCH_PHASE_REVIEWERS",
                    "kind": "HOST_ACTION",
                    "command": dispatch_receipt_command,
                    "blocking": True,
                    "phase_id": phase_id,
                    "reason": ("Record the developer's separate reviewer-model choice before launching reviewers." if before_first_dispatch else
                               f"Launch the phase reviewers with their exact briefs, then record the dispatch receipt: {', '.join(sorted(not_dispatched))} (models: {dispatch_with_models})."),
                    **({"before_first_dispatch": before_first_dispatch} if before_first_dispatch else {}),
                    "reviewers": sorted(not_dispatched),
                    "reviewer_models": dispatch_models,
                    "package_path": run_meta.get("package_path", ""),
                    "briefs": briefs,
                    "review_execution_profile": exec_profile,
                    "inputs": {
                        "repo": ".",
                        "task_id": task_id,
                        "phase_id": phase_id,
                        **({"before_first_dispatch": before_first_dispatch} if before_first_dispatch else {}),
                        "reviewers": sorted(not_dispatched),
                        "reviewer_models": dispatch_models,
                        "briefs": briefs,
                        "review_execution_profile": exec_profile,
                    },
                    "expected": {"success_statuses": ["PASS"]},
                }

            # 5. Waiting for dispatched reviewers
            dispatched = [r for r, d in revs.items() if d.get("state") == REVIEW_DISPATCHED]
            if dispatched:
                from review_models import format_reviewers_with_models, reviewer_model_map
                run_meta_wait = _engine.read_json(prun_f) if prun_f.is_file() else {}
                pending_models = reviewer_model_map(run_meta_wait, sorted(dispatched))
                pending_with_models = format_reviewers_with_models(run_meta_wait, sorted(dispatched))
                return {
                    "code": "WAIT_FOR_PHASE_REVIEWERS",
                    "kind": "HOST_ACTION",
                    "command": "",
                    "blocking": True,
                    "reason": f"Waiting for phase reviewer subagents: {', '.join(sorted(dispatched))} (models: {pending_with_models}).",
                    "pending_reviewers": sorted(dispatched),
                    "reviewer_models": pending_models,
                    "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id, "pending_reviewers": sorted(dispatched), "reviewer_models": pending_models},
                    "expected": {"success_statuses": ["PASS"]},
                }

            # 6. Finalize
            all_completed = all(d.get("state") == REVIEW_COMPLETED for d in revs.values())
            if all_completed:
                from review_models import format_reviewers_with_models, reviewer_model_map
                run_meta_fin = _engine.read_json(prun_f) if prun_f.is_file() else {}
                all_models = reviewer_model_map(run_meta_fin, sorted(revs.keys()))
                all_with_models = format_reviewers_with_models(run_meta_fin, sorted(revs.keys()))
                return {
                    "code": "FINALIZE_PHASE_REVIEW",
                    "kind": "HARNESS_COMMAND",
                    "command": f'python .agents/harness.py phase-review finalize --repo . --task-id {task_id} --phase-id "{phase_id}"',
                    "blocking": True,
                    "reason": f"Finalize review results for phase '{phase_id}' (models: {all_with_models}).",
                    "reviewer_models": all_models,
                    "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id, "reviewer_models": all_models},
                    "expected": {"success_statuses": ["PASS"]},
                }

    if substate == PHASE_COMPLETE:
        if active_idx + 1 < len(phases):
            next_phase = phases[active_idx + 1]
            next_id = next_phase.get("id", f"p{active_idx+2}")
            return {
                "code": "BEGIN_NEXT_PHASE",
                "kind": "HARNESS_COMMAND",
                "command": f'python .agents/harness.py task begin-next-phase {identity}',
                "blocking": True,
                "reason": f"Phase '{phase_id}' complete. Advance to next phase '{next_id}'.",
                "inputs": {"repo": ".", "task_id": task_id, "next_phase_id": next_id},
                "expected": {"success_statuses": ["IMPLEMENTING"]},
            }
        else:
            return {
                "code": "PREPARE_VERIFICATION",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py task prepare-verification {identity} --host {run_host}",
                "blocking": True,
                "reason": "Final phase complete. Freeze change set and prepare final verification.",
                "inputs": {"repo": ".", "task_id": task_id},
                "expected": {"success_statuses": ["VERIFYING"]},
            }

    phase_dir_path = phase_dir(tdir, phase_id)
    baseline_file = phase_dir_path / "baseline.json"
    base_data = _engine.read_json(baseline_file) if baseline_file.is_file() else _engine.load_task_baseline(repo, task_id)
    phase_changes = []
    try:
        manifest = _engine.build_task_manifest(repo, base_data, expected_files=cur_phase.get("expected_files") or plan.get("expected_files"))
        phase_changes = manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes") or []
    except (OSError, ValueError, _engine.ValidationError):
        pass
    if not phase_changes:
        return {
            "code": "IMPLEMENT_APPROVED_SCOPE",
            "kind": "MODEL_ACTION",
            "command": "",
            "blocking": True,
            "reason": f"Implement code changes within approved scope (active phase: {phase_id}).",
            "inputs": {"repo": ".", "task_id": task_id, "current_phase_id": phase_id},
            "expected": {},
        }

    return {
        "code": "CHECKPOINT_PHASE",
        "kind": "HARNESS_COMMAND",
        "command": f'python .agents/harness.py task checkpoint-phase {identity} --phase-id "{phase_id}"',
        "blocking": True,
        "reason": f"Validate and checkpoint phase '{phase_id}'.",
        "inputs": {"repo": ".", "task_id": task_id, "phase_id": phase_id},
        "expected": {"success_exit_codes": [0]},
    }

