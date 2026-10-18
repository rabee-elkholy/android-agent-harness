"""Run consecutive deterministic verification steps selected by the task router.

This command never dispatches reviewers, installs builds, records approvals or
completes delivery. A successful stop means only that the next action is ready.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))


def _dispatch(repo: Path, script: str, arguments: list[str]) -> int:
    env = dict(os.environ, HARNESS_REPO=str(repo))
    return subprocess.run([sys.executable, "-u", str(SCRIPTS / script), *arguments],
                          cwd=str(repo), env=env, check=False).returncode


def run_steps(repo: Path, task_id: str, host: str | None = None) -> tuple[int, dict]:
    from _vnext_common import ValidationError
    from evidence_store import StateLock
    from host_continuation import assert_execution_session
    from mutation_guard import active_plan
    from workflow import _compact_for_host, resolve_next_action, task_dir

    completed: list[str] = []
    action: dict = {}
    summary = {"task_id": task_id, "status": "STOPPED", "completed_steps": completed}
    timings: list[dict] = []
    summary["step_timings"] = timings
    # CLI review routing must not override the process-local execution identity.
    assert_execution_session(repo, task_id)
    session = task_dir(repo, task_id) / "host-session.json"
    lease = StateLock(session.parent / "execution", timeout_seconds=0) if session.is_file() else nullcontext()
    with lease:
        while True:
            plan = active_plan(repo) or {}
            if plan.get("task_id") != task_id:
                raise ValidationError("TASK_FOCUS_CHANGED: focus the requested task before running verify-steps.")
            assert_execution_session(repo, task_id)
            action = resolve_next_action(repo, task_id, plan, host=host)
            code = str(action.get("code") or "")
            arguments: list[str] = []
            script = ""
            if (plan.get("status") == "IMPLEMENTING" and
                    (code == "PREPARE_VERIFICATION" or
                     (code == "IMPLEMENT_APPROVED_SCOPE" and
                      (action.get("on_complete") or {}).get("code") == "PREPARE_VERIFICATION"))):
                code, script = "PREPARE_VERIFICATION", "workflow.py"
                arguments = ["prepare-verification", "--repo", str(repo), "--task-id", task_id]
                if host:
                    arguments.extend(["--host", host])
            elif plan.get("status") == "VERIFYING":
                script = {"RUN_PREFLIGHT": "preflight_check.py", "RUN_UNIT_TESTS": "run_tests_gate.py",
                          "BUILD_REVIEW_PACKAGE": "review_package.py"}.get(code, "")
                if script in {"preflight_check.py", "review_package.py"}:
                    arguments = ["--repo", str(repo), "--task-id", task_id]
            if not script:
                summary["next_action"] = _compact_for_host(action)
                return 0, summary
            if code in completed:
                summary.update(status="FAILED", next_action=_compact_for_host(action),
                               reason="NO_VERIFICATION_PROGRESS: the router repeated a completed step. Diagnose before retrying.")
                return 1, summary
            print(f"VERIFICATION_STEP={code}", flush=True)
            started = time.monotonic()
            exit_code = _dispatch(repo, script, arguments)
            timings.append({"step": code, "duration_seconds": round(time.monotonic() - started, 3), "exit_code": exit_code})
            if exit_code:
                summary.update(status="FAILED", failed_step=code, exit_code=exit_code,
                               reason="The step failed. Diagnose its output; no later step was executed.")
                return exit_code, summary
            completed.append(code)


def main(argv: list[str] | None = None) -> int:
    from _vnext_common import ValidationError
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--host", default=None)
    args = parser.parse_args(argv)
    try:
        code, result = run_steps(Path(args.repo).resolve(), args.task_id, args.host)
    except (ValidationError, OSError) as exc:
        code, result = 1, {"status": "FAILED", "task_id": args.task_id, "reason": str(exc)}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
