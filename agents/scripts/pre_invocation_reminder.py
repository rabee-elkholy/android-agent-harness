"""Low-noise task-state reminder for hosts that support PreInvocation hooks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import REPO  # noqa: E402


def _message() -> str:
    try:
        from mutation_guard import active_plan
        plan = active_plan(REPO)
    except Exception:
        return (
            "Android Harness: discovery MUST start with `python .agents/scripts/project_graph.py --feature <name>` "
            "or `--find <Symbol>` before inspecting files. Unanchored grep cascades are forbidden. "
            "Analysis and planning are read-only. Before implementation, draft a task plan and obtain explicit developer approval."
        )
    status = str(plan.get("status") or "UNKNOWN")
    task_id = str(plan.get("task_id") or "unknown")
    if status == "AWAITING_DEVELOPER_APPROVAL":
        next_step = "Wait for explicit approval; do not edit files or run mutating commands."
    elif status == "IMPLEMENTING":
        next_step = "Implement approved scope. Do not create new plans or demand 'Proceed' on follow-ups. Do NOT poll background tasks with manage_task status; wait for background notification."
    elif status == "VERIFYING":
        next_step = "Strict verification order: 1. preflight -> 2. unit tests -> 3. routed reviewers (parallel) -> 4. device install (if required) -> 5. ask_question device check -> 6. verify. If code fixes or developer critique needed, run workflow.py resume; never stall on new plans or demand 'Proceed'."
    elif status == "BLOCKED":
        next_step = "Fix recorded findings with workflow.py resume, or request developer decision at the round cap."
    elif status == "READY_FOR_DELIVERY":
        try:
            from workflow import _find_uncommitted_task_files, state_root
            from plan_authority import deliver as deliver_plan, save_plan
            dirty = _find_uncommitted_task_files(REPO, task_id, plan)
            if not dirty:
                plan = deliver_plan(plan)
                task_plan_path = state_root(REPO) / "tasks" / task_id / "plan.json"
                if task_plan_path.is_file():
                    save_plan(task_plan_path, plan)
                active_file = state_root(REPO) / "active-task.json"
                if active_file.is_file():
                    active_file.unlink(missing_ok=True)
                return (
                    "Android Harness: discovery MUST start with `python .agents/scripts/project_graph.py --feature <name>` "
                    "or `--find <Symbol>` before inspecting files. Unanchored grep cascades are forbidden. "
                    "Analysis and planning are read-only. Before implementation, draft a task plan and obtain explicit developer approval."
                )
        except Exception:
            pass
        next_step = "Commit changes with Conventional Commit, or run 'python .agents/scripts/workflow.py deliver' to complete delivery. Do not mutate the delivery."
    else:
        next_step = "Follow the central task lifecycle; do not infer authorization from this reminder."
    return f"Android Harness task {task_id}: {status}. {next_step} Zoho mutates only after explicit `update zoho`."


def _compact_message() -> str:
    try:
        from mutation_guard import active_plan
        plan = active_plan(REPO)
        status = str(plan.get("status") or "UNKNOWN")
        task_id = str(plan.get("task_id") or "unknown")
        if status == "IMPLEMENTING":
            return f"Harness [Task {task_id}: IMPLEMENTING]: Mutate only approved files. Do not create new plans or ask for Proceed. Wait for background task completion."
        if status == "VERIFYING":
            return f"Harness [Task {task_id}: VERIFYING]: Order: 1. preflight -> 2. unit tests -> 3. routed reviewers -> 4. device install -> 5. verify. Run workflow.py resume for fixes; do not stall on follow-ups."
        if status == "READY_FOR_DELIVERY":
            return f"Harness [Task {task_id}: READY_FOR_DELIVERY]: Commit changes with Conventional Commit, or run 'workflow.py deliver' to close."
        return f"Harness [Task {task_id}: {status}]: Architectural discovery uses `project_graph.py`. Unanchored grep cascades are blocked."
    except Exception:
        return "Android Harness: Use `project_graph.py --feature <name>` or `--find <Symbol>`. Unanchored grep cascades are forbidden."


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        invocation = int(payload.get("invocationNum") or 0) if isinstance(payload, dict) else 0
        msg = _message() if invocation in (0, 1) else _compact_message()
        print(json.dumps({"injectSteps": [{"ephemeralMessage": msg}]}))
    except Exception:
        print("{}")


if __name__ == "__main__":
    main()
