"""Run consecutive deterministic steps selected by the canonical task router.

Provides two cleanly bounded layers over ONE single source of truth:

1. `advance_fast_steps(...)` — sub-second local deterministic handoffs only
   (`FAST_AUTO_ADVANCE_CODES`: zero Gradle, zero ADB, zero external writes,
   zero human/reviewer/model bypasses). Used automatically by `harness.py` after
   successful non-JSON lifecycle commands to eliminate redundant LLM thinking
   turns between back-to-back local scripts.
2. `run_steps(...)` — consecutive verification / ship pump (`verify-steps` and
   `task ship`). Never dispatches reviewers, records approvals, or crosses human
   authority boundaries; fails closed on any error, cycle, or stale state.
"""
from __future__ import annotations

import argparse
import contextlib
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

# Strictly sub-second, local, deterministic state/packaging/finalization steps.
# Zero Gradle invocations, zero ADB/device calls, zero external network writes.
FAST_AUTO_ADVANCE_CODES: frozenset[str] = frozenset({
    "BEGIN_IMPLEMENTATION",
    "BUILD_PHASE_REVIEW_PACKAGE",
    "FINALIZE_PHASE_REVIEW",
    "BEGIN_NEXT_PHASE",
    "BUILD_REVIEW_PACKAGE",
    "INGEST_REVIEW_RESULT",
    "COMPLETE_TASK",
    "DELIVER",
})

# Explicit fail-closed denylist: even though the router classifies these as
# HARNESS_COMMAND, they require model diagnosis, test-authoring timing,
# external tracker authority, or cross-host stop confirmation and must NEVER
# be auto-executed by any pump.
NEVER_AUTO_ADVANCE_CODES: frozenset[str] = frozenset({
    "RESUME_IMPLEMENTATION",
    "CAPTURE_RED_EVIDENCE",
    "RECORD_TASK_START_FAILURES",
    "SYNC_ZOHO_START",
    "SYNC_ZOHO_DELIVERY",
    "PREPARE_ZOHO_DELIVERY_REPORT",
    "CONTINUE_ON_CURRENT_HOST",
    "RECONCILE_HANDOFF",
})

DEFAULT_MAX_AUTO_ADVANCE_STEPS = 8
DEFAULT_MAX_PUMP_STEPS = 16


def auto_advance_disabled(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    raw = str(source.get("HARNESS_AUTO_ADVANCE") or "").strip().lower()
    return raw in {"0", "false", "off", "no", "disabled"}


def _dispatch(repo: Path, script: str, arguments: list[str], *, quiet_stdout: bool = False) -> int:
    env = dict(os.environ, HARNESS_REPO=str(repo))
    if quiet_stdout:
        proc = subprocess.run(
            [sys.executable, "-u", str(SCRIPTS / script), *arguments],
            cwd=str(repo), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if proc.returncode and proc.stdout:
            print(proc.stdout, file=sys.stderr, end="" if proc.stdout.endswith("\n") else "\n")
        return proc.returncode
    return subprocess.run([sys.executable, "-u", str(SCRIPTS / script), *arguments],
                          cwd=str(repo), env=env, check=False).returncode


def _execute_fast_step(
    repo: Path,
    task_id: str,
    action: dict[str, Any],
    *,
    host: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Execute one allowlisted fast deterministic step in-process.

    Returns ``(executed, metadata)``. Returns ``(False, {})`` when the step is
    not eligible for safe in-process fast handoff (e.g., V1 non-finalize review
    ingest or missing phase identity).
    """
    code = str(action.get("code") or "")
    if code not in FAST_AUTO_ADVANCE_CODES or code in NEVER_AUTO_ADVANCE_CODES:
        return False, {}

    if code == "BEGIN_IMPLEMENTATION":
        import workflow
        workflow.begin_task(argparse.Namespace(repo=str(repo), task_id=task_id))
        return True, {}

    if code == "BUILD_PHASE_REVIEW_PACKAGE":
        phase_id = str((action.get("inputs") or {}).get("phase_id") or "").strip()
        if not phase_id:
            return False, {}
        import phase_review
        phase_review.build_phase_package(repo, task_id, phase_id, host=host)
        return True, {"phase_id": phase_id}

    if code == "FINALIZE_PHASE_REVIEW":
        phase_id = str((action.get("inputs") or {}).get("phase_id") or "").strip()
        if not phase_id:
            return False, {}
        import phase_review
        res = phase_review.finalize_phase_review(repo, task_id, phase_id)
        return True, {"phase_id": phase_id, "phase_finalized": res if isinstance(res, dict) else {}}

    if code == "BEGIN_NEXT_PHASE":
        import workflow
        workflow.begin_next_phase(argparse.Namespace(repo=str(repo), task_id=task_id))
        return True, {}

    if code == "BUILD_REVIEW_PACKAGE":
        import review_package
        review_package.build_package(repo, task_id)
        return True, {}

    if code == "INGEST_REVIEW_RESULT":
        cmd_str = str(action.get("command") or "")
        # Auto-finalize only V2 transcript-backed review runs (`review finalize`).
        # Legacy V1 `review ingest` remains explicit.
        if "review finalize" not in cmd_str:
            return False, {}
        import review_orchestrator
        res = review_orchestrator.finalize_review_execution(repo, task_id)
        return True, {"finalized_review": res if isinstance(res, dict) else {}}

    if code == "COMPLETE_TASK":
        import workflow
        workflow.complete(argparse.Namespace(repo=str(repo), task_id=task_id))
        return True, {}

    if code == "DELIVER":
        import workflow
        delivered = workflow.deliver_task(
            argparse.Namespace(
                repo=str(repo),
                task_id=task_id,
                allow_dirty_tree=False,
                developer_allow_dirty_tree=False,
                source=None,
            )
        )
        return True, {"delivered_plan": delivered if isinstance(delivered, dict) else {}}

    return False, {}


def advance_fast_steps(
    repo: Path,
    task_id: str,
    *,
    host: str | None = None,
    max_steps: int = DEFAULT_MAX_AUTO_ADVANCE_STEPS,
    hold_lease: bool = True,
    enabled: bool = True,
) -> dict[str, Any]:
    """Advance all consecutive fast local deterministic steps until a real boundary.

    Stops cleanly (fail-closed) on any non-allowlisted action (`MODEL_ACTION`,
    `HOST_ACTION`, `DEVELOPER_ACTION`, heavy Gradle/ADB gates, failure recovery),
    cycle detection, step cap, focus change, or step error.
    """
    import mutation_guard
    import workflow
    from _vnext_common import HarnessError, ValidationError
    from evidence_store import StateLock
    from host_continuation import assert_execution_session

    completed: list[str] = []
    timings: list[dict[str, Any]] = []
    finalized_reviews: list[dict[str, Any]] = []
    stopped_error = ""
    action: dict[str, Any] = {}
    plan: dict[str, Any] = {}
    host_kw = {"host": host} if host else {}

    tdir = workflow.task_dir(repo, task_id)
    lease = (
        StateLock(tdir / "execution", timeout_seconds=0)
        if (hold_lease and tdir.is_dir())
        else nullcontext()
    )
    can_advance = bool(enabled) and not auto_advance_disabled()
    step_limit = max(0, int(max_steps))

    with lease:
        while True:
            plan = mutation_guard.active_plan(repo) or {}
            live_tid = str(plan.get("task_id") or "")
            live_status = str(plan.get("status") or "")
            if live_tid != task_id:
                if completed:
                    try:
                        loaded = workflow._load_plan(repo, task_id)
                    except (HarnessError, ValidationError, OSError, ValueError):
                        loaded = {}
                    if str(loaded.get("status") or "") == "DELIVERED":
                        plan = loaded
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            try:
                                action = workflow.resolve_next_action(repo, task_id, plan, **host_kw)
                            except (HarnessError, ValidationError, OSError, ValueError):
                                action = {"code": "TASK_DELIVERED", "kind": "TASK_STATE", "command": ""}
                break
            if live_status in ("", "DELIVERED", "CANCELLED"):
                if live_status == "DELIVERED" and completed:
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        try:
                            action = workflow.resolve_next_action(repo, task_id, plan, **host_kw)
                        except (HarnessError, ValidationError, OSError, ValueError):
                            action = {"code": "TASK_DELIVERED", "kind": "TASK_STATE", "command": ""}
                break

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                action = workflow.resolve_next_action(repo, task_id, plan, **host_kw)

            if not isinstance(action, dict):
                action = {}
                break

            code = str(action.get("code") or "")
            if (
                not can_advance
                or not code
                or code not in FAST_AUTO_ADVANCE_CODES
                or code in NEVER_AUTO_ADVANCE_CODES
                or code in completed
                or len(completed) >= step_limit
            ):
                break

            if tdir.is_dir():
                assert_execution_session(repo, task_id)

            started = time.monotonic()
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    executed, meta = _execute_fast_step(repo, task_id, action, host=host)
            except (ValidationError, HarnessError, OSError, ValueError, ImportError) as exc:
                timings.append({
                    "step": code,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "exit_code": 1,
                })
                stopped_error = f"{code}: {exc}"
                break

            if not executed:
                break

            timings.append({
                "step": code,
                "duration_seconds": round(time.monotonic() - started, 3),
                "exit_code": 0,
            })
            completed.append(code)
            if isinstance(meta.get("finalized_review"), dict) and meta["finalized_review"]:
                finalized_reviews.append(meta["finalized_review"])

    return {
        "task_id": task_id,
        "completed_steps": completed,
        "step_timings": timings,
        "action": action,
        "plan": plan,
        "stopped_error": stopped_error,
        "finalized_reviews": finalized_reviews,
    }


def run_steps(
    repo: Path,
    task_id: str,
    host: str | None = None,
    *,
    json_only: bool = False,
    include_assemble: bool = False,
    include_fast_tail: bool = False,
    include_device: bool = False,
    max_steps: int = DEFAULT_MAX_PUMP_STEPS,
) -> tuple[int, dict]:
    from _vnext_common import HarnessError, ValidationError
    from evidence_store import StateLock
    from host_continuation import assert_execution_session
    from mutation_guard import active_plan
    from workflow import _compact_for_host, all_remaining_phases_ready_for_final, resolve_next_action, task_dir

    completed: list[str] = []
    action: dict = {}
    summary: dict[str, Any] = {"task_id": task_id, "status": "STOPPED", "completed_steps": completed}
    timings: list[dict] = []
    summary["step_timings"] = timings
    # CLI review routing must not override the process-local execution identity.
    assert_execution_session(repo, task_id)
    tdir = task_dir(repo, task_id)
    lease = StateLock(tdir / "execution", timeout_seconds=0) if tdir.is_dir() else nullcontext()
    step_limit = max(1, int(max_steps))
    with lease:
        while True:
            plan = active_plan(repo) or {}
            if plan.get("task_id") != task_id:
                raise ValidationError("TASK_FOCUS_CHANGED: focus the requested task before running verify-steps.")
            assert_execution_session(repo, task_id)
            action = resolve_next_action(repo, task_id, plan, host=host)
            code = str(action.get("code") or "")
            if code in NEVER_AUTO_ADVANCE_CODES:
                summary["next_action"] = _compact_for_host(action)
                return 0, summary
            if len(completed) >= step_limit:
                summary["next_action"] = _compact_for_host(action)
                summary["step_cap_reached"] = True
                return 0, summary

            # Fast local tail steps (used by `task ship` / full deterministic pump).
            # `verify-steps` keeps `include_fast_tail=False` so it stops before `COMPLETE_TASK` / `DELIVER`.
            if include_fast_tail and code in FAST_AUTO_ADVANCE_CODES and code != "BUILD_REVIEW_PACKAGE":
                if code in completed:
                    summary.update(
                        status="FAILED",
                        next_action=_compact_for_host(action),
                        reason="NO_VERIFICATION_PROGRESS: the router repeated a completed step. Diagnose before retrying.",
                    )
                    return 1, summary
                if not json_only:
                    print(f"VERIFICATION_STEP={code}", flush=True)
                started = time.monotonic()
                try:
                    if json_only:
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            executed, meta = _execute_fast_step(repo, task_id, action, host=host)
                    else:
                        executed, meta = _execute_fast_step(repo, task_id, action, host=host)
                        if isinstance(meta.get("finalized_review"), dict) and meta["finalized_review"]:
                            from review_orchestrator import _print_finalized_review_summary
                            _print_finalized_review_summary(meta["finalized_review"])
                except (ValidationError, HarnessError, OSError, ValueError) as exc:
                    timings.append({"step": code, "duration_seconds": round(time.monotonic() - started, 3), "exit_code": 1})
                    summary.update(status="FAILED", failed_step=code, exit_code=1, reason=str(exc))
                    return 1, summary
                if not executed:
                    summary["next_action"] = _compact_for_host(action)
                    return 0, summary
                timings.append({"step": code, "duration_seconds": round(time.monotonic() - started, 3), "exit_code": 0})
                completed.append(code)
                if code == "DELIVER":
                    # Terminal state reached cleanly (`deliver_task` clears active-task.json); load persisted plan directly.
                    import workflow as _wf_mod
                    try:
                        refreshed_plan = _wf_mod._load_plan(repo, task_id)
                    except (ValidationError, HarnessError, OSError, ValueError):
                        refreshed_plan = plan
                    summary["next_action"] = _compact_for_host(
                        resolve_next_action(repo, task_id, refreshed_plan, host=host)
                    )
                    return 0, summary
                continue

            arguments: list[str] = []
            script = ""
            if plan.get("status") == "IMPLEMENTING":
                if (
                    code == "PREPARE_VERIFICATION"
                    or (
                        code == "IMPLEMENT_APPROVED_SCOPE"
                        and (action.get("on_complete") or {}).get("code") == "PREPARE_VERIFICATION"
                    )
                ):
                    code, script = "PREPARE_VERIFICATION", "workflow.py"
                    arguments = ["prepare-verification", "--repo", str(repo), "--task-id", task_id]
                    if host:
                        arguments.extend(["--host", host])
                elif code in {"CHECKPOINT_PHASE", "BEGIN_NEXT_PHASE"}:
                    ready_final, cur_pid = all_remaining_phases_ready_for_final(repo, task_id, plan)
                    if ready_final and cur_pid:
                        if code == "BEGIN_NEXT_PHASE":
                            code, script = "BEGIN_NEXT_PHASE", "workflow.py"
                            arguments = ["begin-next-phase", "--repo", str(repo), "--task-id", task_id]
                        else:
                            code, script = "CHECKPOINT_READY_PHASES", "workflow.py"
                            arguments = [
                                "checkpoint-phase",
                                "--repo",
                                str(repo),
                                "--task-id",
                                task_id,
                                "--phase-id",
                                cur_pid,
                                "--advance-all-ready",
                                "--defer-gradle-to-final",
                            ]
            elif plan.get("status") == "VERIFYING":
                script = {
                    "RUN_PREFLIGHT": "preflight_check.py",
                    "RUN_CHECK_STRINGS": "check_strings.py",
                    "RUN_FAST_KT_LINT": "fast_kt_lint.py",
                    "RUN_ROOM_GUARD": "room_guard.py",
                    "RUN_UNIT_TESTS": "run_tests_gate.py",
                    "BUILD_REVIEW_PACKAGE": "review_package.py",
                    **({"ASSEMBLE": "run_gradle_task.py"} if include_assemble else {}),
                    **({"DEVICE_INSTALL": "run_device.py"} if include_device else {}),
                }.get(code, "")
                if script in {"preflight_check.py", "review_package.py"}:
                    arguments = ["--repo", str(repo), "--task-id", task_id]
                elif script == "room_guard.py":
                    arguments = ["--repo", str(repo)]
                elif script == "run_gradle_task.py" and code == "ASSEMBLE":
                    asm_task = str((action.get("inputs") or {}).get("assemble_task") or "").strip()
                    if not asm_task:
                        from _variants import resolve_assemble_task
                        asm_task = resolve_assemble_task(repo)
                    arguments = [asm_task]
                elif script == "run_device.py" and code == "DEVICE_INSTALL":
                    arguments = ["install-start"]
            if not script:
                summary["next_action"] = _compact_for_host(action)
                return 0, summary
            if code in completed:
                summary.update(status="FAILED", next_action=_compact_for_host(action),
                               reason="NO_VERIFICATION_PROGRESS: the router repeated a completed step. Diagnose before retrying.")
                return 1, summary
            if not json_only:
                print(f"VERIFICATION_STEP={code}", flush=True)
            started = time.monotonic()
            from task_metrics import operation_span
            with operation_span(repo, "verification-dispatch", task_id=task_id, counters={"dispatches": 1}):
                exit_code = _dispatch(repo, script, arguments, quiet_stdout=True) if json_only else _dispatch(repo, script, arguments)
            timings.append({"step": code, "duration_seconds": round(time.monotonic() - started, 3), "exit_code": exit_code})
            if exit_code:
                reason_msg = "The step failed. Diagnose its output; no later step was executed."
                web_active = (tdir / "web-relay-receipt.json").is_file() or (tdir / "latest-web-pack.json").is_file()
                if not web_active:
                    try:
                        from execution_mode import resolve_effective_execution_mode
                        web_active = resolve_effective_execution_mode(repo, task_id=task_id).get("mode") == "web"
                    except (ImportError, OSError, ValueError, ValidationError):
                        web_active = False
                if web_active:
                    retry_cmd = f"python .agents/harness.py web-pack --task-id {task_id} --retry-failure"
                    summary["web_retry_command"] = retry_cmd
                    reason_msg += (
                        f" Web-Relay active: for non-trivial compile/test/gate repairs, run `{retry_cmd}` "
                        "to emit a compact failure-only delta for the SAME external AI chat (zero full-file re-upload)."
                    )
                summary.update(status="FAILED", failed_step=code, exit_code=exit_code, reason=reason_msg)
                return exit_code, summary
            completed.append(code)


def main(argv: list[str] | None = None) -> int:
    from _vnext_common import ValidationError
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task-id", "--task", dest="task_id", required=True)
    parser.add_argument("--host", default=None)
    parser.add_argument("--json", action="store_true", help="Emit pure JSON output on stdout")
    args = parser.parse_args(argv)
    try:
        code, result = run_steps(Path(args.repo).resolve(), args.task_id, args.host, json_only=bool(args.json))
    except (ValidationError, OSError) as exc:
        code, result = 1, {"status": "FAILED", "task_id": args.task_id, "reason": str(exc)}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
