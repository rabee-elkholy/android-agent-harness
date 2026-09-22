"""PostToolUse hook reconciler for invoke_subagent failures."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import read_json
from evidence_store import StateLock
from review_orchestrator import load_ledger, save_ledger, REVIEW_DISPATCHED, REVIEW_ENV_BLOCKED
from workflow import state_root, task_dir


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({}))
            return 0
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            print(json.dumps({}))
            return 0

        err = payload.get("error")
        if not err:
            print(json.dumps({}))
            return 0

        call = payload.get("toolCall") or payload.get("tool_call") or {}
        args = call.get("args") or payload.get("toolArgs") or payload.get("tool_input") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}

        subagents = args.get("Subagents") or args.get("subagents") or []
        roles = []
        if isinstance(subagents, list):
            for sa in subagents:
                if isinstance(sa, dict):
                    r = sa.get("TypeName") or sa.get("typeName") or sa.get("Role") or sa.get("role")
                    if r:
                        roles.append(str(r).strip())

        repo_str = os.environ.get("HARNESS_REPO", ".")
        repo = Path(repo_str).resolve()
        st_root = state_root(repo)
        active_task_file = st_root / "active-task.json"
        if not active_task_file.is_file():
            print(json.dumps({}))
            return 0

        active_data = read_json(active_task_file)
        task_id = str(active_data.get("task_id") or "")
        if not task_id:
            print(json.dumps({}))
            return 0

        tdir = task_dir(repo, task_id)
        current_run_file = tdir / "current-run.json"
        if not current_run_file.is_file():
            print(json.dumps({}))
            return 0

        current_run = read_json(current_run_file)
        run_id = str(current_run.get("run_id") or "")
        if not run_id:
            print(json.dumps({}))
            return 0

        sanitized_err = str(err).strip()[:1000]

        target_roles = set(roles)
        try:
            with StateLock(st_root):
                ledger = load_ledger(tdir, run_id)
                reviewers = ledger.get("reviewers", {})
                to_transition = []
                for r_name, r_data in reviewers.items():
                    if r_data.get("state") == REVIEW_DISPATCHED and not r_data.get("execution_id"):
                        if target_roles:
                            if r_name in target_roles:
                                to_transition.append(r_name)
                        else:
                            to_transition.append(r_name)

                # Fallback if target_roles didn't match any dispatched reviewer
                if not to_transition:
                    to_transition = [
                        r_name for r_name, r_data in reviewers.items()
                        if r_data.get("state") == REVIEW_DISPATCHED and not r_data.get("execution_id")
                    ]

                for r in to_transition:
                    reviewers[r]["state"] = REVIEW_ENV_BLOCKED
                    reviewers[r]["last_error"] = sanitized_err

                save_ledger(tdir, run_id, ledger)
        except Exception as exc:
            try:
                marker_file = tdir / "review-execution" / run_id / "post-tool-reconcile-error.json"
                marker_file.parent.mkdir(parents=True, exist_ok=True)
                from _vnext_common import atomic_write_json, utc_now
                atomic_write_json(marker_file, {
                    "schema_version": 1,
                    "task_id": task_id,
                    "run_id": run_id,
                    "error_type": type(exc).__name__,
                    "error_code": "POST_TOOL_RECONCILE_FAILED",
                    "occurred_at": utc_now(),
                })
            except Exception:
                pass

        print(json.dumps({}))
        return 0
    except Exception:
        print(json.dumps({}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
