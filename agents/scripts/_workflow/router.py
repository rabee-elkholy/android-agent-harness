"""Canonical task routing and state-specific next actions."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


def resolve_next_action(repo: Path, task_id: str, plan: dict | None = None, host: str | None = None) -> dict[str, Any]:
    """Canonical evidence-aware next-action engine resolving the single safest next action."""
    if plan is None:
        plan = _engine._load_plan(repo, task_id)
    state = str(plan.get("status") or "").upper()
    pending = _engine.state_root(repo) / "review-model-update.json"
    if pending.exists():
        return {"code": "REVIEW_MODEL_UPDATE_INCOMPLETE", "kind": "HARNESS_DIAGNOSTIC", "blocking": True,
                "command": "", "reason": "Repeat the recorded reviewer-model command to finish interrupted publication before dispatch.",
                "inputs": _engine.read_json(pending), "expected": {}}
    identity = f'--repo . --task-id {task_id}'
    run_host = _engine.resolve_review_host(repo, host)
    from host_continuation import CONTINUABLE_STATES, load_session
    session = load_session(repo, task_id)
    actor_id = _engine.os.environ.get("CODEX_THREAD_ID", "").strip() if run_host == "codex" else ""
    if state in CONTINUABLE_STATES and session and (session["host"] != run_host or (actor_id and session.get("actor_id") and actor_id != session["actor_id"])):
        return {"code": "CONTINUE_ON_CURRENT_HOST", "kind": "HARNESS_COMMAND", "blocking": True,
                "command": f"python .agents/harness.py task continue {identity} --host {run_host} --source-stopped --expect-session {session['session_id']}",
                "reason": "Stop the former executor, then continue the same approved task on this host.",
                "inputs": {"task_id": task_id, "host": run_host}, "expected": {"success_statuses": ["CONTINUED"]}}
    from host_continuation import review_host_mismatch_action
    from review_sources import detected_current_host
    mismatch = review_host_mismatch_action(repo, task_id, plan, run_host, session) if (host or session or detected_current_host()) else None
    if mismatch:
        return mismatch
    if host is None and session is None and not _engine.os.environ.get("HARNESS_HOST") and not _engine.os.environ.get("HARNESS_HOOK_HOST") and not _engine.os.environ.get("CODEX_THREAD_ID"):
        from phase_review import phase_run_file
        for phase in reversed(plan.get("phases") or []):
            run_file = phase_run_file(_engine.task_dir(repo, task_id), str(phase.get("id") or ""))
            if run_file.is_file():
                try:
                    frozen_host = str(_engine.read_json(run_file).get("review_host") or "")
                    if frozen_host:
                        run_host = frozen_host
                        break
                except (OSError, ValueError, _engine.ValidationError):
                    pass

    if state in {"DRAFTED", "PLAN_APPROVAL_REQUIRED", "PLAN_DRAFTED", "AWAITING_DEVELOPER_APPROVAL"}:
        return {
            "code": "APPROVE_PLAN",
            "kind": "DEVELOPER_ACTION",
            "command": f'python .agents/harness.py task approve {identity} --source conversation --proof-reference "<phrase>" --enforcement-tier RULE_ENFORCED{_engine._plan_hash_arg(plan)}',
            "blocking": True,
            "reason": "The reviewed plan needs explicit approval before implementation.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_statuses": ["IMPLEMENTING"]},
        }

    if state == "APPROVED":
        return {
            "code": "BEGIN_IMPLEMENTATION",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task begin {identity}",
            "blocking": True,
            "reason": "Start the approved implementation.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_exit_codes": [0], "success_statuses": ["IMPLEMENTING"]},
        }

    if state in {"IMPLEMENTING", "VERIFYING", "BLOCKED"}:
        from task_base import base_moved, moved_message

        moved = base_moved(repo, task_id)
        if moved:
            return {
                "code": "TASK_BASE_MOVED",
                "kind": "DEVELOPER_ACTION",
                "command": "",
                "blocking": True,
                "reason": moved_message(moved, task_id),
                "inputs": {"repo": ".", "task_id": task_id, **moved},
                "expected": {},
            }

    if state == "IMPLEMENTING":
        return _next_implementation(repo, task_id, plan, host, identity, run_host, state, session)

    if state == "VERIFYING":
        return _next_verification(repo, task_id, plan, host, identity, run_host, state, session)

    if state == "READY_FOR_DELIVERY":
        return _next_delivery(repo, task_id, plan, host, identity, run_host, state, session)

    if state == "DELIVERED":
        return _next_delivered(repo, task_id, plan, host, identity, run_host, state, session)

    if state == "BLOCKED":
        return _next_blocked(repo, task_id, plan, host, identity, run_host, state, session)

    if state == "CANCELLED":
        return {
            "code": "CANCELLED",
            "kind": "TASK_STATE",
            "command": "",
            "blocking": False,
            "reason": "The task was cancelled; start a new task to continue work.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {},
        }

    return {
        "code": "UNKNOWN_STATE",
        "kind": "BLOCKED",
        "command": "",
        "blocking": True,
        "reason": f"Task is in unrecognized state: {state}.",
        "inputs": {"repo": ".", "task_id": task_id},
        "expected": {},
    }


def _next_implementation(repo, task_id, plan, host, identity, run_host, state, session):
    tdir = _engine.task_dir(repo, task_id)
    from change_decision import decisions
    has_accept_edits = not plan.get("blocked_reviewers") and any(
        row.get("mode") == "accept-edits" for row in decisions(plan)
    )
    if plan.get("review_rounds") and not has_accept_edits:
        from review_budget import review_round_cap_action
        previous = tdir / "current-run.json"
        previous_policy = _engine.read_json(_engine.Path(_engine.read_json(previous)["policy"])) if previous.is_file() else {}
        round_block = review_round_cap_action(repo, plan, previous_policy)
        if round_block:
            return round_block
    budget_block = plan.get("review_budget_blocked") or {}
    if budget_block.get("plan_sha256") == plan.get("plan_sha256") and budget_block:
        from review_budget import effective_review_budget
        budget = effective_review_budget(repo, plan)
        from review_budget import effective_review_calls_used
        used = effective_review_calls_used(repo, plan)
        requested = int(budget_block.get("requested") or 0)
        if used + requested > budget:
            return {"code": "REVIEW_BUDGET_EXHAUSTED", "kind": "DEVELOPER_ACTION", "command": "", "blocking": True,
                    "reason": _engine.build_budget_exhausted_remediation(
                        {"surfaces": budget_block.get("surfaces", []),
                         "severity": budget_block.get("severity", "CRITICAL")}, used, requested, budget),
                    "inputs": {"repo": ".", "task_id": task_id}, "expected": {}}
    # Check Zoho start sync (Sections 46, 47)
    if plan.get("zoho_link") and "zoho_sprints" in (plan.get("external_writes") or []):
        start_sync_file = tdir / "zoho-start-sync.json"
        if not start_sync_file.exists():
            return {
                "code": "SYNC_ZOHO_START",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/scripts/zoho_sync.py start --repo . --task-id {task_id}",
                "blocking": True,
                "reason": "Sync In progress status to linked Zoho item for approved task.",
                "inputs": {"repo": ".", "task_id": task_id},
                "expected": {"success_exit_codes": [0]},
            }
    from final_verifier import alternate_reproduction_recorded, bug_requires_executable_red
    red_evidence_file = tdir / "red-evidence.json"
    if not red_evidence_file.is_file() and bug_requires_executable_red(
        plan, plan.get("expected_surfaces") or [], alternate_reproduction=alternate_reproduction_recorded(tdir),
    ):
        capture = {
            "code": "CAPTURE_RED_EVIDENCE",
            "kind": "HARNESS_COMMAND",
            "command": "python .agents/harness.py test --capture-red",
            "blocking": True,
            "reason": "Record failing test reproduction evidence for BUG before implementing production changes.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_exit_codes": [0]},
        }
        if _engine._should_record_task_start(repo, task_id, plan) and not _engine._task_has_changes(repo, task_id, plan):
            # O64: once the reproduction test is written, nothing can be shown to predate the task.
            record = "python .agents/harness.py test --record-start"
            capture["reason"] = (
                f"Before writing the reproduction test, run `{record}` once to record which unit tests already "
                "fail on the untouched project. Then write a test that fails because of the defect and run "
                "`python .agents/harness.py test --capture-red` before changing production code."
            )
            capture["before_first_edit"] = {"code": "RECORD_TASK_START_FAILURES", "kind": "HARNESS_COMMAND", "command": record}
        return capture

    pending_handoff_f = tdir / "pending-handoff.json"
    if pending_handoff_f.is_file():
        pending = _engine.read_json(pending_handoff_f)
        parent_head = pending.get("parent_head")
        cur_head = _engine.git_text(repo, "rev-parse", "HEAD")
        if cur_head != parent_head:
            return {
                "code": "RECONCILE_HANDOFF",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py task reconcile-handoff --repo . --task-id {task_id}",
                "blocking": True,
                "reason": "Developer WIP commit detected. Reconcile handoff to validate checkpoint receipt.",
                "inputs": {"repo": ".", "task_id": task_id},
                "expected": {"success_statuses": ["WORKTREE_SWITCH_READY"]},
            }
        return {
            "code": "DEVELOPER_WIP_COMMIT_REQUIRED",
            "kind": "DEVELOPER_ACTION",
            "command": "",
            "blocking": True,
            "reason": "Developer WIP commit required for task checkpoint.",
            "inputs": {"repo": ".", "task_id": task_id, "parent_head": parent_head},
            "expected": {},
        }

    phases = plan.get("phases") or []
    if phases:
        from .phase_routing import phase_implementation_action
        return phase_implementation_action(repo, task_id, plan, run_host, identity, tdir, phases)
    action = {
        "code": "IMPLEMENT_APPROVED_SCOPE",
        "kind": "MODEL_ACTION",
        "command": "",
        "blocking": True,
        "reason": "Implement code changes within approved scope and phases.",
        "inputs": {"repo": ".", "task_id": task_id},
        "expected": {},
    }
    try:
        task_manifest = _engine.build_task_manifest(repo, _engine.load_task_baseline(repo, task_id), expected_files=plan.get("expected_files"))
        task_changes = task_manifest.get("task_changes") if "task_changes" in task_manifest else task_manifest.get("changes")
        has_task_changes = bool(task_changes)
    except Exception:
        task_changes, has_task_changes = [], False
    if has_task_changes:
        # Only the model knows when the approved change is finished; hand it the exit.
        done_command = f"python .agents/harness.py task prepare-verification {identity} --host {run_host}"
        action["reason"] = f"Continue the approved change. When it is complete, run: {done_command}"
        compile_hint = _engine._compile_check_hint(repo, task_changes)
        if compile_hint:
            action["reason"] = f"Continue the approved change. {compile_hint} Then run: {done_command}"
        action["on_complete"] = {"code": "PREPARE_VERIFICATION", "kind": "HARNESS_COMMAND", "command": done_command}
    elif _engine._should_record_task_start(repo, task_id, plan):
        # O64: without a record, an old failing test in another feature blocks the gate later and
        # has to go to the developer; one run on the untouched tree settles it up front.
        record = "python .agents/harness.py test --record-start"
        action["reason"] += (
            f" Before the first edit, run `{record}` once: it records which unit tests already fail "
            "on the untouched project, so the gate never counts them against this task."
        )
        action["before_first_edit"] = {"code": "RECORD_TASK_START_FAILURES", "kind": "HARNESS_COMMAND", "command": record}
    return action


def _next_verification(repo, task_id, plan, host, identity, run_host, state, session):
    tdir = _engine.task_dir(repo, task_id)
    current_run_file = tdir / "current-run.json"
    if not current_run_file.is_file():
        return {
            "code": "RESUME_IMPLEMENTATION",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task resume --task-id {task_id}",
            "blocking": True,
            "reason": "The VERIFYING task has no current run. Resume implementation, then prepare verification again.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_exit_codes": [0], "success_statuses": ["IMPLEMENTING"]},
        }

    try:
        current_run = _engine.read_json(current_run_file)
        run_id = current_run["run_id"]
        policy = _engine.read_json(_engine.Path(current_run["policy"]))
        manifest = _engine.read_json(_engine.Path(current_run["manifest"]))
    except Exception:
        return {
            "code": "RESUME_IMPLEMENTATION",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task resume --task-id {task_id}",
            "blocking": True,
            "reason": "Verification run artifacts are corrupted. Resume implementation, then prepare verification again.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_exit_codes": [0], "success_statuses": ["IMPLEMENTING"]},
        }

    from final_verifier import policy_integrity_error
    integrity_error = policy_integrity_error(policy, _engine.Path(current_run["policy"]))
    if integrity_error:
        return {"code": "VERIFICATION_POLICY_INVALID", "kind": "TASK_STATE", "command": "", "blocking": True,
                "reason": integrity_error + ". Stop for harness diagnosis; do not edit policy/evidence, skip device checks "
                          "as a workaround, or run complete. Keep the task open for repair or explicitly cancel it.",
                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id}, "expected": {}}
    freshness = _engine.verification_freshness(repo, task_id, current_run)
    if not freshness.get("fresh"):
        return {
            "code": "VERIFICATION_STALE",
            "kind": "DEVELOPER_ACTION",
            "command": f"python .agents/harness.py task resume --task-id {task_id}",
            "blocking": True,
            "reason": (
                "The frozen verification run no longer represents current repository content "
                f"({freshness.get('reason_code')}: {freshness.get('reason', '')}). "
                "No further gates or reviewers will be consumed. Preserve the same task and completed work. "
                "For unexpected source edits, show the diff and ask whether these are intentional developer edits: "
                "accept the exact edits without additional AI review, or review the affected delta. "
                "Preview task change-decision --mode accept-edits or review-edits --file <changed-file> "
                "--reason <explanation>, then apply --expect-preview <hash> --source conversation "
                "--proof-reference <answer>. Never infer authorship or consent. "
                "For agent fixes already authorized, resume and verify only the affected scope; do not restart the plan. "
                "Non-source/environment drift still requires its normal recovery."
            ),
            "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
            "expected": {"success_statuses": ["IMPLEMENTING"]},
        }

    snapshot = str(manifest.get("delivery_snapshot_sha256") or "")
    change_set = str(manifest.get("change_set_sha256") or "")
    policy_gates = list(policy.get("gates") or [])
    store = _engine.EvidenceStore(_engine.state_root(repo))

    def has_pass_evidence(name: str) -> bool:
        try:
            rec = store.read(snapshot, run_id, name)
            if name == 'unit_tests':
                from final_verifier import unit_test_retry_error
                if unit_test_retry_error(store, snapshot, run_id, rec):
                    return False
            return rec.get("status") == "PASS" and rec.get("change_set_sha256") == change_set
        except Exception:
            return False

    def has_skip_evidence(name: str) -> bool:
        try:
            rec = store.read(snapshot, run_id, name)
            return rec.get("status") == "SKIPPED" and rec.get("change_set_sha256") == change_set
        except Exception:
            return False

    if policy.get("reviewers") and not has_pass_evidence("reviews"):
        from review_budget import review_round_cap_action
        round_block = review_round_cap_action(repo, plan, policy)
        if round_block:
            return round_block

    # The final verifier requires a run-bound sensitive approval whenever the run's surfaces include a
    # sensitive one. The router asked only when `policy.sensitive` was set, so a real task was sent to
    # `complete`, failed on a missing sensitive_approval.json, and was sent to `complete` again.
    sensitive_touched = sorted(set(policy.get("surfaces") or []) & _engine.SENSITIVE_SURFACES)
    # Exactly the condition `approve-sensitive` accepts and the verifier requires, so the router never
    # asks for an approval the command would refuse (nothing sets a bare `policy.sensitive` flag).
    sensitive_pending = bool(sensitive_touched) and not has_pass_evidence("sensitive_approval")
    sensitive_command = (
        f'python .agents/harness.py task approve-sensitive {identity} --source conversation '
        '--proof-reference "<developer answer>" --enforcement-tier RULE_ENFORCED'
    )

    def failed_gate_action(name: str) -> dict | None:
        # A deterministic FAIL on this frozen change set will fail again if re-run;
        # the fix happens in IMPLEMENTING under the same approval. ENV is retried.
        try:
            rec = store.read(snapshot, run_id, name)
        except Exception:
            return None
        if rec.get("change_set_sha256") != change_set:
            return None
        detail = str((rec.get("evidence") or {}).get("detail") or "see gate output")
        if rec.get('status') != 'FAIL':
            if name != 'unit_tests' or rec.get('status') != 'PASS':
                return None
            from final_verifier import unit_test_retry_error
            detail = unit_test_retry_error(store, snapshot, run_id, rec)
            if not detail:
                return None
        reason = f"The {name} gate failed on the frozen change set: {detail}. Resume implementation, fix it within the approved scope, then prepare verification again."
        outside = _engine._regressions_outside_plan(plan, manifest, (rec.get("evidence") or {}).get("new_regressions"))
        if outside:
            # O64: "fix it within the approved scope" sent the agent into another feature's tests.
            reason += (
                f" {len(outside)} failing test(s) belong to files outside this plan ({', '.join(outside[:5])}). "
                "Never edit those tests under this plan. If this change broke them, fix the production code in "
                "the planned files. If they were already failing before the task, do not resume: ask the developer "
                "with ask_question whether they were failing before this task (options: 'Yes, not this task's' / "
                "'No, fix them in this task' / 'Cancel task'). On yes, run `python .agents/harness.py test "
                "--record-unrelated --proof-reference \"<the developer's answer>\"` (it records only tests that "
                "name nothing this task changed and says why it refuses any other), then `python .agents/harness.py "
                "test` again, without resuming. On 'fix them', resume and revise the plan to include them."
            )
        return {
            "code": "RESUME_IMPLEMENTATION",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task resume --task-id {task_id}",
            "blocking": True,
            "reason": reason,
            "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "failed_gate": name},
            "expected": {"success_statuses": ["IMPLEMENTING"]},
        }

    # 1. Preflight
    from .verification import VerificationContext, deterministic_action, review_action, build_device_action, completion_action
    context = VerificationContext(
        repo=repo,
        task_id=task_id,
        plan=plan,
        identity=identity,
        run_host=run_host,
        tdir=tdir,
        current_run=current_run,
        run_id=run_id,
        policy=policy,
        manifest=manifest,
        snapshot=snapshot,
        change_set=change_set,
        policy_gates=policy_gates,
        store=store,
        has_pass_evidence=has_pass_evidence,
        has_skip_evidence=has_skip_evidence,
        failed_gate_action=failed_gate_action,
        sensitive_touched=sensitive_touched,
        sensitive_pending=sensitive_pending,
        sensitive_command=sensitive_command,
    )
    for resolve in (deterministic_action, review_action, build_device_action):
        action = resolve(context)
        if action is not None:
            return action
    return completion_action(context)


def _next_delivery(repo, task_id, plan, host, identity, run_host, state, session):
    ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
    ready_run_id = str(plan.get("ready_run_id") or "")
    if not ready_snapshot or not ready_run_id:
        tdir = _engine.task_dir(repo, task_id)
        crun_path = tdir / "current-run.json"
        if crun_path.is_file():
            try:
                crun = _engine.read_json(crun_path)
                if not ready_snapshot:
                    ready_snapshot = str(crun.get("delivery_snapshot_sha256") or "")
                if not ready_run_id:
                    ready_run_id = str(crun.get("run_id") or "")
            except (OSError, ValueError, _engine.ValidationError):
                pass

    live_manifest = _engine.build_manifest(repo)
    live_snapshot = str(live_manifest.get("delivery_snapshot_sha256") or "")
    external_changed = _engine._ready_external_inputs_changed(repo, task_id, ready_run_id, live_manifest)
    sibling_only_drift = False
    if ready_snapshot and live_snapshot and ready_snapshot != live_snapshot:
        from delivery_equivalence import evaluate_post_ready_changes
        equivalence = evaluate_post_ready_changes(repo, task_id, plan, live_manifest)
        sibling_only_drift = equivalence.get("is_benign") and equivalence.get("reason") == "DISJOINT_SIBLING_TASK_CHANGES_ONLY"
    if ready_snapshot and live_snapshot and (ready_snapshot != live_snapshot or external_changed) and not sibling_only_drift:
        dirty = _engine._find_uncommitted_task_files(repo, task_id, plan)
        if not dirty:
            from delivery_equivalence import evaluate_post_ready_changes
            eval_res = evaluate_post_ready_changes(repo, task_id, plan, live_manifest)
            if eval_res.get("is_benign"):
                identity = f"--repo . --task-id {task_id}"
                return {
                    "code": "DELIVER",
                    "kind": "HARNESS_COMMAND",
                    "command": f"python .agents/harness.py task deliver {identity}",
                    "blocking": True,
                    "reason": (
                        f"Developer git commit accepted with benign normalization ({eval_res.get('diff_summary')}). "
                        "Finalize verified delivery state."
                    ),
                    "inputs": {"repo": ".", "task_id": task_id},
                    "expected": {"success_exit_codes": [0], "success_statuses": ["DELIVERED"]},
                }

        changed = _engine.changed_since_verification(repo, task_id, plan, live_manifest)
        named = ", ".join(changed[:10]) if changed else ("external build inputs" if external_changed else "files outside the task's list")
        diff_detail = ""
        if not dirty:
            from delivery_equivalence import evaluate_post_ready_changes
            eval_res = evaluate_post_ready_changes(repo, task_id, plan, live_manifest)
            if eval_res.get("diff_summary"):
                diff_detail = f" Detected differences: {eval_res['diff_summary']}."

        return {
            "code": "DELIVERY_STALE_AFTER_COMMIT",
            "kind": "DEVELOPER_ACTION",
            "command": f"python .agents/harness.py task resume --task-id {task_id}",
            "blocking": True,
            # Real app: the developer edited a verified file before committing; the router said "resume",
            # the agent resumed without asking, and a full re-review ran out of review budget.
            "reason": (
                f"Content changed after verification: {named}.{diff_detail} "
                "Git attributes normalize line endings when configured; unproven content differences still require verification. "
                "Show the diff and ask the developer whether these are intentional developer edits: accept the exact delta without additional AI review, "
                "or verify the affected changes. Preview task change-decision --mode accept-edits or review-edits "
                "--file <changed-file> --reason <explanation>; apply its --expect-preview <hash> with "
                "--source conversation --proof-reference <answer>. Keep this task and prior review coverage. "
                "Tests/build/device evidence must still match the new source. Cancel only on an explicit cancellation request."
            ),
            "changed_files": changed,
            "inputs": {
                "repo": ".",
                "task_id": task_id,
                "ready_snapshot": ready_snapshot,
                "live_snapshot": live_snapshot,
            },
            "expected": {"success_statuses": ["IMPLEMENTING"]},
        }

    dirty = _engine._find_uncommitted_task_files(repo, task_id, plan)
    if dirty:
        kind = str(plan.get("task_kind") or "AUTO").upper()
        outcome = str(plan.get("requested_outcome") or "deliver verified changes").strip().rstrip(".")
        if outcome:
            outcome = outcome[0].lower() + outcome[1:]

        if kind == "FEATURE":
            prefix = "feat"
        elif kind == "BUG":
            prefix = "fix"
        elif kind == "REFACTOR":
            prefix = "refactor"
        else:
            outcome_lower = outcome.lower()
            if "fix" in outcome_lower or "bug" in outcome_lower:
                prefix = "fix"
            elif "refactor" in outcome_lower or "clean" in outcome_lower:
                prefix = "refactor"
            elif "doc" in outcome_lower:
                prefix = "docs"
            elif "test" in outcome_lower:
                prefix = "test"
            else:
                prefix = "feat"

        surfaces = plan.get("expected_surfaces") or []
        modules = plan.get("expected_modules") or []
        scope = ""
        if surfaces:
            scope = str(surfaces[0]).lower()
        elif modules:
            scope = str(modules[0]).lstrip(":").replace(":", "-").lower()

        scope_part = f"({scope})" if scope else ""
        suggested_commit = f"{prefix}{scope_part}: {outcome}"
        try:
            baseline_paths = {
                str(item.get("path") or "") for item in (_engine.load_task_baseline(repo, task_id) or {}).get("changes") or []
            }
        except Exception:
            baseline_paths = set()
        mixed = sorted(path for path in dirty if path in baseline_paths)
        mixed_note = (
            f" These files also hold the developer's own edits from before the task, which a whole-file commit "
            f"includes; say so in the commit question: {', '.join(mixed)}."
            if mixed else ""
        )

        return {
            "code": "DEVELOPER_GIT_COMMIT_REQUIRED",
            "kind": "DEVELOPER_ACTION",
            "command": "",
            "blocking": True,
            "reason": (
                f"Verified task files remain uncommitted: {', '.join(sorted(dirty))}.{mixed_note} "
                "Human Git Authority requires the developer to review and commit changes before final delivery. "
                "Tip: commit the verified files as-is. In the Android Studio commit dialog, keep 'Optimize imports' and 'Reformat code' unchecked to preserve the exact verified snapshot. "
                f"If the developer requests changes instead, reopen with: python .agents/harness.py task resume --task-id {task_id} --reopen"
            ),
            "suggested_commit": suggested_commit,
            "inputs": {
                "repo": ".",
                "task_id": task_id,
                "verified_run_id": ready_run_id,
                "verified_snapshot_sha256": ready_snapshot,
                "dirty_task_files": sorted(dirty),
                "suggested_commit_message": suggested_commit,
            },
            "instructions": (
                f"Developer action required: Commit uncommitted task files ({', '.join(sorted(dirty))}).\n"
                + (f"Tell the developer these files also contain their own uncommitted edits from before the task: {', '.join(mixed)}.\n" if mixed else "")
                + f"Suggested commit: {suggested_commit}\n"
                "Tip: Commit files as-is without reformatting or reordering imports.\n"
                "The model must NOT run git commit commands. Await developer commit."
            ),
            "expected": {},
        }

    return {
        "code": "DELIVER",
        "kind": "HARNESS_COMMAND",
        "command": f"python .agents/harness.py task deliver {identity}",
        "blocking": True,
        "reason": "Finalize verified delivery state after git commit.",
        "inputs": {"repo": ".", "task_id": task_id},
        "expected": {"success_exit_codes": [0], "success_statuses": ["DELIVERED"]},
    }


def _next_delivered(repo, task_id, plan, host, identity, run_host, state, session):
    tdir = _engine.task_dir(repo, task_id)
    if plan.get("zoho_link") and "zoho_sprints" in (plan.get("external_writes") or []):
        delivery_sync_file = tdir / "zoho-delivery-sync.json"
        if delivery_sync_file.exists():
            try:
                dsync = _engine.read_json(delivery_sync_file)
                if dsync.get("status") == "PASS":
                    return {
                        "code": "TASK_DELIVERED",
                        "kind": "DONE",
                        "command": "",
                        "blocking": False,
                        "reason": "Task is delivered and linked Zoho item is synced. No further harness action required.",
                        "inputs": {"repo": ".", "task_id": task_id},
                        "expected": {},
                    }
                elif dsync.get("status") == "ENV":
                    return {
                        "code": "ZOHO_ENV_BLOCKED",
                        "kind": "HARNESS_COMMAND",
                        "command": f"python .agents/scripts/zoho_sync.py delivery --repo . --task-id {task_id}",
                        "blocking": False,
                        "reason": "Zoho delivery sync is blocked by external environment/credentials. Local code remains delivered.",
                        "inputs": {"repo": ".", "task_id": task_id},
                        "expected": {"success_exit_codes": [0]},
                    }
            except (OSError, ValueError, _engine.ValidationError):
                pass

        report_file = tdir / "zoho-delivery-report.json"
        if not report_file.exists():
            from zoho_sync import prepare_report_command

            return {
                "code": "PREPARE_ZOHO_DELIVERY_REPORT",
                "kind": "HOST_ACTION",
                "command": "",
                "blocking": True,
                "reason": (
                    "Prepare the structured functional report for the Zoho delivery sync, then run "
                    f"`python .agents/harness.py zoho delivery-sync --task-id {task_id}`: {prepare_report_command(task_id)}"
                ),
                "required_schema": {
                    "objective_or_root_cause": "string",
                    "solution_or_changes": "string",
                    "impact_area": "string[]",
                    "test_cases": "string[]",
                },
                "inputs": {"repo": ".", "task_id": task_id},
                "expected": {"success_statuses": ["PREPARED"]},
            }

        return {
            "code": "SYNC_ZOHO_DELIVERY",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/scripts/zoho_sync.py delivery --repo . --task-id {task_id}",
            "blocking": True,
            "reason": "Sync verified delivery report and status to linked Zoho item.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_exit_codes": [0]},
        }

    return {
        "code": "TASK_DELIVERED",
        "kind": "DONE",
        "command": "",
        "blocking": False,
        "reason": "Task is delivered. No further harness action required.",
        "inputs": {"repo": ".", "task_id": task_id},
        "expected": {},
    }


def _next_blocked(repo, task_id, plan, host, identity, run_host, state, session):
    from review_budget import review_round_cap_action
    current_file = _engine.task_dir(repo, task_id) / "current-run.json"
    last_policy = _engine.read_json(_engine.Path(_engine.read_json(current_file)["policy"])) if current_file.is_file() else {}
    round_block = review_round_cap_action(repo, plan, last_policy)
    if round_block:
        return round_block
    return {
        "code": "RESUME_IMPLEMENTATION",
        "kind": "HARNESS_COMMAND",
        "command": f"python .agents/harness.py task resume {identity}",
        "blocking": True,
        "reason": "Resume after resolving the recorded blocker.",
        "inputs": {"repo": ".", "task_id": task_id},
        "expected": {"success_exit_codes": [0], "success_statuses": ["IMPLEMENTING"]},
    }

