"""Verification routing stages over one validated, frozen run context."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import engine as _engine


@dataclass(frozen=True)
class VerificationContext:
    repo: Any
    task_id: Any
    plan: Any
    identity: Any
    run_host: Any
    tdir: Any
    current_run: Any
    run_id: Any
    policy: Any
    manifest: Any
    snapshot: Any
    change_set: Any
    policy_gates: Any
    store: Any
    has_pass_evidence: Any
    has_skip_evidence: Any
    failed_gate_action: Any
    sensitive_touched: Any
    sensitive_pending: Any
    sensitive_command: Any


def deterministic_action(context: VerificationContext) -> dict | None:
    task_id = context.task_id
    run_id = context.run_id
    policy_gates = context.policy_gates
    has_pass_evidence = context.has_pass_evidence
    failed_gate_action = context.failed_gate_action
    if "preflight" in policy_gates or not policy_gates:
        if not has_pass_evidence("preflight"):
            failed = failed_gate_action("preflight")
            if failed:
                return failed
            return {
                "code": "RUN_PREFLIGHT",
                "kind": "HARNESS_COMMAND",
                "command": "python .agents/harness.py preflight",
                "blocking": True,
                "reason": "The active verification policy requires preflight check evidence.",
                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                "expected": {"success_exit_codes": [0]},
            }

    # 2. Specialized deterministic gates
    specialized = [
        ("check_strings", "python .agents/scripts/check_strings.py", "RUN_CHECK_STRINGS"),
        ("fast_kt_lint", "python .agents/scripts/fast_kt_lint.py", "RUN_FAST_KT_LINT"),
        ("room_guard", "python .agents/scripts/room_guard.py", "RUN_ROOM_GUARD"),
    ]
    for g_name, g_cmd, g_code in specialized:
        if g_name in policy_gates and not has_pass_evidence(g_name):
            failed = failed_gate_action(g_name)
            if failed:
                return failed
            return {
                "code": g_code,
                "kind": "HARNESS_COMMAND",
                "command": g_cmd,
                "blocking": True,
                "reason": f"The active verification policy requires {g_name} evidence.",
                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                "expected": {"success_exit_codes": [0]},
            }

    # 3. Unit tests
    if "unit_tests" in policy_gates:
        if not has_pass_evidence("unit_tests"):
            failed = failed_gate_action("unit_tests")
            if failed:
                return failed
            return {
                "code": "RUN_UNIT_TESTS",
                "kind": "HARNESS_COMMAND",
                "command": "python .agents/harness.py test",
                "blocking": True,
                "reason": "The active verification policy requires unit-test evidence.",
                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                "expected": {"success_exit_codes": [0]},
            }

    # 4. Review package and Reviewers


def review_action(context: VerificationContext) -> dict | None:
    repo = context.repo
    task_id = context.task_id
    tdir = context.tdir
    current_run = context.current_run
    run_id = context.run_id
    policy = context.policy
    snapshot = context.snapshot
    store = context.store
    has_pass_evidence = context.has_pass_evidence
    required_reviewers = list(policy.get("reviewers") or [])
    if required_reviewers:
        pkg_path = _engine.active_review_package_path(repo, current_run)
        if not pkg_path.is_file():
            return {
                "code": "BUILD_REVIEW_PACKAGE",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py review package --task-id {task_id}",
                "blocking": True,
                "reason": "Build the immutable review package for required specialist reviewers.",
                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                "expected": {"success_exit_codes": [0]},
            }

        # Check for existing reviews evidence
        try:
            rev_evidence = store.read(snapshot, run_id, "reviews")
            if rev_evidence.get("status") == "FAIL":
                return {
                    "code": "BLOCKED",
                    "kind": "TASK_STATE",
                    "command": f"python .agents/harness.py task resume --task-id {task_id}",
                    "blocking": True,
                    "reason": "Review evidence has blocking findings; resolve findings and resume task.",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {"success_statuses": ["IMPLEMENTING"]},
                }
        except (OSError, ValueError, _engine.ValidationError):
            pass

        if not has_pass_evidence("reviews"):
            briefs = {}
            exec_profile = {}
            profile_exc = None
            try:
                from review_execution import resolve_execution_profile
                review_host = str(
                    current_run.get("review_host") or "generic"
                ).strip().lower()

                exec_profile = resolve_execution_profile(
                    repo,
                    task_id,
                    host=review_host,
                )
                for r_name, r_info in exec_profile.get("reviewers", {}).items():
                    if r_info.get("brief_path"):
                        briefs[r_name] = r_info["brief_path"]
            except Exception as exc:
                profile_exc = exc
                exec_profile = {}

            review_protocol_version = int(current_run.get("review_protocol_version") or 1)
            if profile_exc is not None and current_run.get("review_models"):
                return {"code": "REVIEW_PROFILE_BLOCKED", "kind": "HOST_ACTION", "command": "", "blocking": True,
                        "reason": f"Frozen reviewer execution settings are invalid: {profile_exc}", "inputs": {"task_id": task_id}, "expected": {}}
            if review_protocol_version >= 2:
                if profile_exc is not None or not exec_profile:
                    return {
                        "code": "REVIEW_PROFILE_BLOCKED",
                        "kind": "HOST_ACTION",
                        "command": "",
                        "blocking": True,
                        "reason": f"Review execution profile resolution failed: {type(profile_exc).__name__ if profile_exc else 'missing profile'}.",
                        "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                        "expected": {},
                    }

                from review_orchestrator import (
                    get_review_execution_status,
                    REVIEW_NOT_DISPATCHED,
                    REVIEW_DISPATCHED,
                    REVIEW_PROTOCOL_RETRY_REQUIRED,
                    REVIEW_COMPLETED,
                    REVIEW_INGESTED,
                    REVIEW_FAILED_PROTOCOL,
                    REVIEW_ENV_BLOCKED,
                )
                st = get_review_execution_status(repo, task_id)
                rev_states = st.get("reviewers", {})
                from reviewer_host import lifecycle_action
                host_action = lifecycle_action(repo, current_run, rev_states)
                if host_action:
                    return host_action

                failed_proto = [r for r in required_reviewers if rev_states.get(r, {}).get("state") == REVIEW_FAILED_PROTOCOL]
                if failed_proto:
                    r = failed_proto[0]
                    return {
                        "code": "REVIEW_PROTOCOL_BLOCKED",
                        "kind": "HOST_ACTION",
                        "command": "",
                        "blocking": True,
                        "reviewer": r,
                        "reason": f"Reviewer '{r}' repeatedly failed protocol: {rev_states.get(r, {}).get('last_error')}.",
                        "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "reviewer": r},
                        "expected": {},
                    }

                env_blocked = [r for r in required_reviewers if rev_states.get(r, {}).get("state") == REVIEW_ENV_BLOCKED]
                if env_blocked:
                    r = env_blocked[0]
                    return {
                        "code": "REVIEW_ENV_BLOCKED",
                        "kind": "HOST_ACTION",
                        "command": "",
                        "blocking": True,
                        "reviewer": r,
                        "reason": f"Reviewer '{r}' is blocked by environment: {rev_states.get(r, {}).get('last_error')}.",
                        "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "reviewer": r},
                        "expected": {},
                    }

                retry_required = [r for r in required_reviewers if rev_states.get(r, {}).get("state") == REVIEW_PROTOCOL_RETRY_REQUIRED]
                if retry_required:
                    r = retry_required[0]
                    recipient = rev_states.get(r, {}).get("execution_id") or ""
                    if not recipient:
                        return {
                            "code": "REVIEW_PROTOCOL_BLOCKED",
                            "kind": "HOST_ACTION",
                            "command": "",
                            "blocking": True,
                            "reviewer": r,
                            "reason": "PROTOCOL_RETRY_MISSING_EXECUTION_ID",
                            "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "reviewer": r},
                            "expected": {},
                        }
                    pkg_sha_full = _engine.sha256_file(pkg_path) if pkg_path.is_file() else ""
                    correction_msg = (
                        f"Your previous review response did not include a valid HARNESS_REVIEW_RESULT_V2 JSON block.\n\n"
                        f"Please emit your final structured review result as exactly ONE JSON block matching schema_version 2:\n"
                        f"```json\n"
                        f'{{\n'
                        f'  "schema_version": 2,\n'
                        f'  "task_id": "{task_id}",\n'
                        f'  "run_id": "{run_id}",\n'
                        f'  "reviewer": "{r}",\n'
                        f'  "review_package_sha256": "{pkg_sha_full}",\n'
                        f'  "verdict": "PASS",\n'
                        f'  "findings": []\n'
                        f'}}\n'
                        f"```\n"
                        f"Or with verdict 'FINDINGS' and at least one finding object.\n\n"
                        f"Requirements:\n"
                        f"- Return the corrected final JSON block only.\n"
                        f"- Do NOT redo the review unless needed to correct factual content.\n"
                        f"- No prose after the final JSON code block.\n"
                    )
                    return {
                        "code": "RETRY_REVIEW_PROTOCOL",
                        "kind": "HOST_ACTION",
                        "command": "",
                        "blocking": True,
                        "tool": "send_message",
                        "reviewer": r,
                        "recipient": recipient,
                        "message": correction_msg,
                        "reason": f"Reviewer '{r}' output was malformed: {rev_states.get(r, {}).get('last_error')}. Request structured result correction via send_message to {recipient}.",
                        "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "reviewer": r, "recipient": recipient},
                        "expected": {
                            "same_execution_id": True,
                            "new_dispatch": False,
                        },
                    }

                not_dispatched = [r for r in required_reviewers if rev_states.get(r, {}).get("state") in (REVIEW_NOT_DISPATCHED, None)]
                if not_dispatched:
                    for r in not_dispatched:
                        r_info = exec_profile.get("reviewers", {}).get(r)
                        if not r_info:
                            return {
                                "code": "REVIEW_PROFILE_BLOCKED",
                                "kind": "HOST_ACTION",
                                "command": "",
                                "blocking": True,
                                "reason": f"Reviewer '{r}' missing from execution profile.",
                                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "reviewer": r},
                                "expected": {},
                            }
                        brief_p = _engine.Path(r_info.get("brief_path") or "")
                        if not brief_p.is_file() or brief_p.stat().st_size == 0:
                            return {
                                "code": "REVIEW_PROFILE_BLOCKED",
                                "kind": "HOST_ACTION",
                                "command": "",
                                "blocking": True,
                                "reason": f"Reviewer brief missing or empty for '{r}': {brief_p.name}.",
                                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "reviewer": r},
                                "expected": {},
                            }

                    prompts = _engine._reviewer_prompts(exec_profile, sorted(not_dispatched))
                    before_first_dispatch = None
                    if (
                        str(review_host).strip().lower() == "antigravity"
                        and (current_run.get("review_models") or {}).get("source", "default") == "default"
                        and len(not_dispatched) == len(required_reviewers)
                    ):
                        from review_models import build_antigravity_model_prompt
                        before_first_dispatch = build_antigravity_model_prompt(
                            repo,
                            task_id,
                            sorted(not_dispatched),
                            run_id=run_id,
                        )
                        exec_profile["reviewer_model_prompt"] = before_first_dispatch
                    action_payload = {
                        "code": "DISPATCH_REVIEWERS",
                        "kind": "HOST_ACTION",
                        "command": "",
                        "blocking": True,
                        "reason": ("Record the developer's separate reviewer-model choice before launching reviewers." if before_first_dispatch else
                                   f"Dispatch independent reviewer subagents: {', '.join(sorted(not_dispatched))}.{_engine._prompt_hint(prompts)}"),
                        **({"before_first_dispatch": before_first_dispatch} if before_first_dispatch else {}),
                        "reviewers": sorted(not_dispatched),
                        "package_path": str(pkg_path),
                        "briefs": briefs,
                        "review_execution_profile": exec_profile,
                        "inputs": {
                            "repo": ".",
                            "task_id": task_id,
                            "run_id": run_id,
                            **({"before_first_dispatch": before_first_dispatch} if before_first_dispatch else {}),
                            "reviewers": sorted(not_dispatched),
                            "package_path": str(pkg_path),
                            "briefs": briefs,
                            "review_execution_profile": exec_profile,
                            "reviewer_prompts": _engine._reviewer_prompts(exec_profile, sorted(not_dispatched)),
                        },
                        "expected": {"success_statuses": ["PASS"]},
                        "reviewer_prompts": prompts,
                    }
                    return action_payload

                reconcile_err_marker = tdir / "review-execution" / run_id / "post-tool-reconcile-error.json"
                if reconcile_err_marker.is_file():
                    marker_data = {}
                    try:
                        marker_data = _engine.read_json(reconcile_err_marker)
                    except (OSError, ValueError, _engine.ValidationError):
                        pass
                    err_code = marker_data.get("error_code") or "POST_TOOL_RECONCILE_FAILED"
                    return {
                        "code": "REVIEW_ENV_BLOCKED",
                        "kind": "HOST_ACTION",
                        "command": "",
                        "blocking": True,
                        "reason": f"Post-tool-use reviewer reconciliation failed: {err_code}.",
                        "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                        "expected": {},
                    }

                dispatched = [r for r in required_reviewers if rev_states.get(r, {}).get("state") == REVIEW_DISPATCHED]
                if dispatched:
                    return {
                        "code": "WAIT_FOR_REVIEWERS",
                        "kind": "HOST_ACTION",
                        "command": "",
                        "blocking": True,
                        "reason": f"Waiting for independent reviewer subagents to complete: {', '.join(sorted(dispatched))}.",
                        "reviewers": required_reviewers,
                        "pending_reviewers": sorted(dispatched),
                        "inputs": {
                            "repo": ".",
                            "task_id": task_id,
                            "run_id": run_id,
                            "pending_reviewers": sorted(dispatched),
                        },
                        "expected": {"success_statuses": ["PASS"]},
                    }

                all_completed = all(rev_states.get(r, {}).get("state") in (REVIEW_COMPLETED, REVIEW_INGESTED) for r in required_reviewers)
                if all_completed:
                    return {
                        "code": "INGEST_REVIEW_RESULT",
                        "kind": "HARNESS_COMMAND",
                        "command": f"python .agents/harness.py review finalize --task {task_id}",
                        "blocking": True,
                        "reason": f"Finalize and aggregate completed review results for {', '.join(sorted(required_reviewers))}.",
                        "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "reviewers": required_reviewers},
                        "expected": {"success_statuses": ["PASS"]},
                    }

            # Legacy protocol v1 fallback
            dispatches_dir = tdir / "reviewer-dispatches"
            staged_dir = tdir / "staged-reviews" / str(run_id)
            dispatched_reviewers = set()
            completed_reviewers = set()
            if dispatches_dir.is_dir():
                for f in dispatches_dir.glob("*.json"):
                    try:
                        d_data = _engine.read_json(f)
                        if not d_data.get("run_id") or str(d_data.get("run_id")) == run_id:
                            dispatched_reviewers.add(f.stem)
                    except Exception:
                        dispatched_reviewers.add(f.stem)
                run_disp_dir = dispatches_dir / str(run_id)
                if run_disp_dir.is_dir():
                    for f in run_disp_dir.glob("*.json"):
                        dispatched_reviewers.add(f.stem)

            if staged_dir.is_dir():
                for f in staged_dir.glob("*.json"):
                    try:
                        s_data = _engine.read_json(f)
                        rev = str(s_data.get("reviewer") or f.stem)
                        if rev:
                            completed_reviewers.add(rev)
                    except Exception:
                        completed_reviewers.add(f.stem)

            req_set = set(required_reviewers)
            # A recorded reply proves the reviewer was launched; hosts without a dispatch hook
            # (Claude Code) never write a V1 receipt, so do not ask to launch it again.
            dispatched_reviewers |= completed_reviewers
            v1_host = str(current_run.get("review_host") or "").strip().lower()
            record_hint = ""
            if not _engine.has_trusted_review_source(v1_host):
                record_hint = (
                    f" Record each finished reviewer's reply with `python .agents/scripts/record_review.py --task {task_id} "
                    "--from-subagent <role>=<transcript-path>`."
                )
            if not req_set.issubset(dispatched_reviewers):
                prompts = _engine._reviewer_prompts(exec_profile, sorted(req_set - dispatched_reviewers))
                return {
                    "code": "DISPATCH_REVIEWERS",
                    "kind": "HOST_ACTION",
                    "command": "",
                    "blocking": True,
                    "reason": f"Dispatch independent reviewer subagents: {', '.join(sorted(req_set - dispatched_reviewers))}.{_engine._prompt_hint(prompts)}{record_hint}",
                    "reviewer_prompts": prompts,
                    "reviewers": sorted(req_set - dispatched_reviewers),
                    "package_path": str(pkg_path),
                    "briefs": briefs,
                    "review_execution_profile": exec_profile,
                    "inputs": {
                        "repo": ".",
                        "task_id": task_id,
                        "run_id": run_id,
                        "reviewers": sorted(req_set - dispatched_reviewers),
                        "package_path": str(pkg_path),
                        "briefs": briefs,
                        "reviewer_prompts": _engine._reviewer_prompts(exec_profile, sorted(req_set - dispatched_reviewers)),
                        "review_execution_profile": exec_profile,
                    },
                    "expected": {"success_statuses": ["PASS"]},
                }

            if not req_set.issubset(completed_reviewers):
                pending = sorted(req_set - completed_reviewers)
                return {
                    "code": "WAIT_FOR_REVIEWERS",
                    "kind": "HOST_ACTION",
                    "command": "",
                    "blocking": True,
                    "reason": f"Waiting for independent reviewer subagents to complete: {', '.join(pending)}.{record_hint}",
                    "reviewers": required_reviewers,
                    "pending_reviewers": pending,
                    "inputs": {
                        "repo": ".",
                        "task_id": task_id,
                        "run_id": run_id,
                        "dispatched_reviewers": sorted(dispatched_reviewers),
                        "pending_reviewers": pending,
                        "completed_reviewers": sorted(completed_reviewers),
                    },
                    "expected": {"success_statuses": ["PASS"]},
                }

            return {
                "code": "INGEST_REVIEW_RESULT",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py review ingest --task {task_id}",
                "blocking": True,
                "reason": f"Ingest completed review results for {', '.join(sorted(required_reviewers))}.",
                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "reviewers": required_reviewers},
                "expected": {"success_statuses": ["PASS"]},
            }

    # 4b. Hosts without trusted transcripts (review protocol V1) cannot prove independent review
    # execution, which the final verifier requires for HIGH/CRITICAL and sensitive changes.
    # Say so before assemble instead of failing at completion.
    if required_reviewers and int(current_run.get("review_protocol_version") or 1) < 2 and has_pass_evidence("reviews"):
        try:
            review_ev = store.read(snapshot, run_id, "reviews").get("evidence") or {}
        except Exception:
            review_ev = {}
        severity = str(policy.get("severity") or "").upper()
        sensitive = sorted(set(policy.get("surfaces") or []) & _engine.SENSITIVE_SURFACES)
        unverified = any(not r.get("independent_execution_verified") for r in review_ev.get("reports") or [])
        overridden = review_ev.get("developer_override") or (store.run_dir(snapshot, run_id) / "review_override.json").is_file()
        if not overridden and unverified and (sensitive or severity in ("HIGH", "CRITICAL")):
            if sensitive:
                return {
                    "code": "SENSITIVE_REVIEW_PROOF_UNAVAILABLE",
                    "kind": "DEVELOPER_ACTION",
                    "command": "",
                    "blocking": True,
                    "reason": (
                        f"This change touches sensitive surfaces ({', '.join(sensitive)}). Delivery needs reviewer "
                        "execution proof that this host cannot produce, and a developer override is not allowed for "
                        "sensitive changes. Ask the developer: run the review on a host with trusted transcripts "
                        "(Antigravity), or cancel and split the sensitive part out of this task."
                    ),
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {},
                }
            return {
                "code": "REVIEW_OVERRIDE_REQUIRED",
                "kind": "DEVELOPER_ACTION",
                "command": (
                    f'python .agents/scripts/record_review.py --task {task_id} --override-reviews '
                    '--source developer_terminal --proof-reference "<why the recorded reviews are accepted>"'
                ),
                "blocking": True,
                "reason": (
                    f"This {severity} change was reviewed on a host that cannot prove independent reviewer execution. "
                    "The developer must accept the recorded reviews by running the command in their own terminal; "
                    "the agent must not run it."
                ),
                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                "expected": {"success_exit_codes": [0]},
            }

    # 5. Assemble


def build_device_action(context: VerificationContext) -> dict | None:
    repo = context.repo
    task_id = context.task_id
    plan = context.plan
    current_run = context.current_run
    run_id = context.run_id
    policy = context.policy
    snapshot = context.snapshot
    policy_gates = context.policy_gates
    store = context.store
    has_pass_evidence = context.has_pass_evidence
    has_skip_evidence = context.has_skip_evidence
    failed_gate_action = context.failed_gate_action
    sensitive_touched = context.sensitive_touched
    sensitive_pending = context.sensitive_pending
    sensitive_command = context.sensitive_command
    assemble_required = ("assemble" in policy_gates) or bool(policy.get("assemble_required"))
    if assemble_required:
        if not has_pass_evidence("assemble"):
            failed = failed_gate_action("assemble")
            if failed:
                return failed
            flavor = policy.get("flavor") or None
            assemble_task = _engine.resolve_assemble_task(repo, flavor=flavor)
            return {
                "code": "ASSEMBLE",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py assemble {assemble_task}",
                "blocking": True,
                "reason": f"Build the application ({assemble_task}).",
                "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "assemble_task": assemble_task},
                "expected": {"success_exit_codes": [0]},
            }

    # 6. Device deploy
    device_required = bool(policy.get("device_required")) or ("device" in policy_gates)
    if device_required:
        if not has_skip_evidence("mobile_validation_skip"):
            if not has_pass_evidence("device_install") or not has_pass_evidence("device_launch"):
                try:
                    install_record = store.read(snapshot, run_id, "device_install")
                    install_attempted = True
                except Exception:
                    install_record = {}
                    install_attempted = False
                if _engine._install_confirm_policy() == "allow" and not install_attempted:
                    # The developer chose unattended install at setup; ask only if it does not work.
                    return {
                        "code": "DEVICE_INSTALL",
                        "kind": "HARNESS_COMMAND",
                        "command": "python .agents/harness.py device install-start",
                        "blocking": True,
                        "reason": "Install and launch on the connected phone (setup: install without asking). "
                                  "If it fails, the developer decides whether to retry or skip.",
                        "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                        "expected": {"success_exit_codes": [0]},
                    }
                reason = "Mobile validation is recommended/required by policy, but the developer may explicitly skip it."
                choices = [
                    {
                        "id": "run",
                        "label": "Run Mobile Validation",
                        "command": "python .agents/harness.py device install-start",
                    },
                    {
                        "id": "skip",
                        "label": "Skip Mobile Validation",
                        "command": f'python .agents/harness.py device skip-validation --task-id {task_id} --source conversation --proof-reference "<developer phrase>"',
                    },
                ]
                failed_detail = str(((install_record or {}).get("evidence") or {}).get("detail") or "")
                if install_attempted and str((install_record or {}).get("status") or "").upper() != "PASS":
                    # Real app: a newer build on the phone failed the install and the agent recommended
                    # skipping the phone check of a payment change. A failed install is fixed and retried.
                    reason = (
                        f"The install failed{': ' + failed_detail[:200] if failed_detail else ''}. Ask the developer how "
                        "to fix it and retry; recommend a retry, never skipping (skip only when the developer chooses it"
                        f"{', and this change touches ' + ', '.join(sensitive_touched) if sensitive_touched else ''})."
                    )
                    if "VERSION_DOWNGRADE" in failed_detail.upper():
                        choices.insert(1, {
                            "id": "allow_downgrade",
                            "label": "Install over the newer build on the phone (keeps the app's data)",
                            "command": "python .agents/harness.py device install-start --allow-downgrade",
                        })
                return {
                    "code": "MOBILE_VALIDATION_DECISION",
                    "kind": "DEVELOPER_ACTION",
                    "command": "python .agents/harness.py device install-start",
                    "blocking": True,
                    "reason": reason,
                    "choices": choices,
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {},
                }
            if (plan.get("verification_contract") or {}).get("journeys"):
                from verification_contract import journey_next_action
                journey_action = journey_next_action(plan, current_run, store)
                if journey_action:
                    return journey_action
            try:
                sign_rec = store.read(snapshot, run_id, "device_signoff")
                if str(sign_rec.get("status") or "").upper() == "FAIL":
                    return {
                        "code": "RESUME_IMPLEMENTATION",
                        "kind": "TASK_STATE",
                        "command": f"python .agents/harness.py task resume --task-id {task_id}",
                        "blocking": True,
                        "reason": "Developer marked device sign-off as FAIL; resume implementation to resolve issues.",
                        "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                        "expected": {"success_statuses": ["IMPLEMENTING"]},
                    }
            except (OSError, ValueError, _engine.ValidationError):
                pass

            signoff_satisfied = has_pass_evidence("device_signoff")
            validation_choice = (plan.get("verification_contract") or {}).get("device_validation") == "manual_or_automatic"
            if validation_choice:
                from verification_contract import automatic_validation_result, manual_journey_source
                signoff_satisfied = False
                try:
                    automatic = automatic_validation_result(plan, current_run, store)
                    signoff_satisfied = automatic.get("status") == "PASS"
                except _engine.ValidationError:
                    try:
                        manual_journey_source(plan, current_run, store)
                        signoff_satisfied = has_pass_evidence("device_signoff")
                    except _engine.ValidationError:
                        pass
            if not signoff_satisfied:
                inst_ev = {}
                try:
                    inst_ev = store.read(snapshot, run_id, "device_install").get("evidence") or {}
                except (OSError, ValueError, _engine.ValidationError):
                    pass
                app_id = str(inst_ev.get("application_id") or "")
                serial_hash = str(inst_ev.get("serial_sha256") or inst_ev.get("serial_hash") or "")[:12]
                signoff_reason = "Present mobile verification walkthrough to developer and obtain explicit PASS or FAIL sign-off."
                if sensitive_pending:
                    # One question instead of two: the final approval of sensitive changes rides on the sign-off.
                    signoff_reason += (
                        f" This change also touches {', '.join(sensitive_touched) or 'sensitive code'}, which needs the "
                        "developer's final approval: ask both in the same ask_question (options 'Works - approve the "
                        f"changes' / 'Failed'). On the first, run the device signoff with --verdict PASS, then `{sensitive_command}`, "
                        "both with the developer's answer as --proof-reference."
                    )
                response_choices = []
                accepted_responses = ["PASS", "FAIL"]
                from verification_contract import phone_e2e_setup
                automation_setup = phone_e2e_setup(plan, device_required=True) if not validation_choice else None
                if automation_setup:
                    accepted_responses.append("PREPARE_E2E")
                    signoff_reason += " Offer Prepare phone E2E alongside manual PASS/FAIL. " + automation_setup["instructions"]
                    response_choices = [
                        {"id": "PASS", "label": "Works - approve the changes" if sensitive_pending else "PASS - I tested manually"},
                        {"id": "FAIL", "label": "FAIL - Manual validation failed"},
                        {"id": "PREPARE_E2E", "label": "Prepare phone E2E"},
                    ]
                if validation_choice:
                    journey_criteria = sorted({c for j in plan["verification_contract"]["journeys"] for c in j["criteria"]})
                    criterion_args = " ".join(f"--criterion-id {c}" for c in journey_criteria)
                    response_choices = [
                        {"id": "PASS", "label": "PASS - I tested this walkthrough manually",
                         "command": f'python .agents/harness.py device signoff --task-id {task_id} --verdict PASS --source conversation --proof-reference "<developer answer>" {criterion_args}'},
                        {"id": "FAIL", "label": "FAIL - Manual validation failed",
                         "command": f'python .agents/harness.py device signoff --task-id {task_id} --verdict FAIL --source conversation --proof-reference "<developer answer>"'},
                        {"id": "AUTOMATIC", "label": "Run Automatically",
                         "command": f'python .agents/harness.py device validate-automatically --task-id {task_id} --serial <installed-device-serial> --source conversation --proof-reference "<developer answer>"'},
                    ]
                    accepted_responses.append("AUTOMATIC")
                    signoff_reason += " Offer Run Automatically for the complete approved walkthrough. Its PASS replaces manual repetition; environment failure offers manual validation. Automatic PASS never supplies sensitive approval."
                    try:
                        previous_validation = store.read(snapshot, run_id, "device_validation_result")
                        if previous_validation.get("status") == "ENV":
                            signoff_reason += " Previous automatic execution could not finish in this environment. Offer manual validation or let the developer resolve the environment; never retry automatically."
                    except _engine.ValidationError:
                        pass
                return {
                    "code": "DEVICE_SIGNOFF_REQUIRED",
                    "kind": "DEVELOPER_ACTION",
                    "command": "",
                    "blocking": True,
                    "reason": signoff_reason,
                    "inputs": {
                        "repo": ".",
                        "task_id": task_id,
                        "run_id": run_id,
                        "application_id": app_id,
                        "device_target_identity": serial_hash,
                    },
                    "instructions": "Present the complete mobile verification walkthrough and await the developer's selected response. Do not run automatic validation before selection.",
                    "accepted_responses": accepted_responses,
                    **({"choices": response_choices, "automation_setup": automation_setup} if automation_setup else {}),
                    **({"choices": response_choices, "walkthrough": plan["verification_contract"]["journeys"]} if validation_choice else {}),
                    "expected": {"success_statuses": ["PASS"]},
                }

    # 7. Sensitive approval


def completion_action(context: VerificationContext) -> dict | None:
    repo = context.repo
    task_id = context.task_id
    plan = context.plan
    current_run = context.current_run
    run_id = context.run_id
    policy = context.policy
    store = context.store
    sensitive_touched = context.sensitive_touched
    sensitive_pending = context.sensitive_pending
    sensitive_command = context.sensitive_command
    if sensitive_pending:
        return {
            "code": "SENSITIVE_APPROVAL",
            "kind": "DEVELOPER_ACTION",
            "command": sensitive_command,
            "blocking": True,
            "reason": (
                f"This change touches {', '.join(sensitive_touched) or 'sensitive code'}: ask the developer with "
                "ask_question for the final approval of those changes (options 'Approve' / 'Request changes'), "
                "then run the command with their answer as --proof-reference."
            ),
            "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
            "expected": {"success_statuses": ["PASS"]},
        }

    # 8. A BUG task that skipped CAPTURE_RED cannot complete; the final verifier applies this rule.
    from final_verifier import alternate_reproduction_recorded, bug_requires_executable_red
    red_dir = _engine.task_dir(repo, task_id)
    if not (red_dir / "red-evidence.json").is_file() and bug_requires_executable_red(
        plan, policy.get("surfaces") or [], alternate_reproduction=alternate_reproduction_recorded(red_dir),
    ):
        return {
            "code": "RED_EVIDENCE_MISSING",
            "kind": "DEVELOPER_ACTION",
            "command": "",
            "blocking": True,
            "reason": (
                "This BUG task has no failing-test RED reproduction captured before the fix, so it cannot complete. "
                "Ask the developer: if the task is not a bug, correct the task kind through workflow.py revise; "
                "otherwise cancel and restart the task, capturing RED before changing production code."
            ),
            "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
            "expected": {},
        }

    if "verification_contract" in plan:
        from verification_contract import coverage_report
        coverage = coverage_report(plan, current_run, store)
        if coverage["blocking"]:
            pending = [row for row in coverage["criteria"] if row["id"] in coverage["blocking"]]
            return {
                "code": "ACCEPTANCE_EVIDENCE_REQUIRED", "kind": "HOST_ACTION", "blocking": True,
                "command": f"python .agents/harness.py task coverage --task-id {task_id} --json",
                "reason": "Inspect uncovered approved criteria and associate relevant current evidence with task bind-evidence. "
                          "Missing manual checks require explicit developer sign-off with --criterion-id; missing or failing "
                          "behavior requires resume and correction. Never invent a passing test or reviewer verdict.",
                "inputs": {"task_id": task_id, "run_id": run_id, "criteria": pending},
                "expected": {"success_statuses": ["VERIFIED"]},
            }

    # 9. Complete task
    return {
        "code": "COMPLETE_TASK",
        "kind": "HARNESS_COMMAND",
        "command": f"python .agents/scripts/workflow.py complete --repo . --task-id {task_id}",
        "blocking": True,
        "reason": "All required gates, reviews, and verifications have passed; seal task to READY_FOR_DELIVERY.",
        "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
        "expected": {"success_exit_codes": [0], "success_statuses": ["READY_FOR_DELIVERY"]},
    }

