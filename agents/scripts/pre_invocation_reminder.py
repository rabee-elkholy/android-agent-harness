"""Low-noise task-state reminder for hosts that support PreInvocation hooks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import REPO  # noqa: E402


def _project_notes_reminder() -> str:
    try:
        from project_context import load_project_notes
        notes = load_project_notes(REPO)
        if notes.get("has_custom_notes"):
            secs = ", ".join(notes.get("sections") or []) or "custom rules"
            return (
                f" Mandatory repo conventions in `.agents/project-context/project-notes.md` ({secs}) — "
                "read and strictly follow before planning, coding, or Zoho updates."
            )
    except (ImportError, OSError, ValueError, KeyError):
        return ""
    return ""


def _message() -> str:
    # Keep this hook read-only and independent of the evidence router. Native
    # ephemeral messages need a current reminder, not a second policy document.
    return (_compact_message() +
            " Use the canonical language-adaptive task cards in .agents/rules/harness-rules.md. Follow the returned NEXT_ACTION; query task status only when it is missing. "
            "For an unresolved material decision, ask the developer about it with `ask_question` before you draft.")


def _compact_message() -> str:
    try:
        from mutation_guard import active_plan
        plan = active_plan(REPO)
    except Exception:
        plan = {}
    notes_rem = _project_notes_reminder()
    if not plan:
        return f"Android Harness: Idle (no active task). Use `python .agents/harness.py graph` for discovery or run `python .agents/scripts/workflow.py draft` to begin a task.{notes_rem}"
    status = str(plan.get("status") or "UNKNOWN")
    task_id = str(plan.get("task_id") or "unknown")
    if status == "IMPLEMENTING":
        return f"Harness [Task {task_id}: IMPLEMENTING]: Autonomous multi-phase execution. Do not create new plans or ask for Proceed. Wait for background task completion; on partial reviewer completion output at most one short count line (e.g. `1/2`) without listing reviewer names or `[<model>]` tags in prose. For a separate disjoint task, draft a new task-id or use `task switch --task-id <id>`.{notes_rem}"
    if status == "VERIFYING":
        return f"Harness [Task {task_id}: VERIFYING]: Order: 1. preflight -> 2. unit tests -> 3. routed reviewers -> 4. device install (only after ALL reviewers pass) -> 5. mobile walkthrough -> 6. verify. Phone E2E requests require device journeys, not unit-test substitution; follow the router and .agents/workflows/phone-e2e.md. Run workflow.py resume for fixes; do not stall on follow-ups. Disjoint tasks can be drafted concurrently (`task draft` / `task switch`); editing tracked files stales frozen verification.{notes_rem}"
    if status == "BLOCKED":
        blocked = plan.get("blocked_reviewers", [])
        blocked_str = f" ({', '.join(blocked)})" if blocked else ""
        return f"Harness [Task {task_id}: BLOCKED{blocked_str}]: Resume before fixing issues: `python .agents/scripts/workflow.py resume --repo . --task-id {task_id}`{notes_rem}"
    if status == "READY_FOR_DELIVERY":
        return f"Harness [Task {task_id}: READY_FOR_DELIVERY]: Git actions belong to the developer. Follow the returned delivery action.{notes_rem}"
    return f"Harness [Task {task_id}: {status}]: Discovery uses `python .agents/harness.py graph`. Discuss requested edge cases in chat before planning. Up to 3 disjoint tasks may coexist (`task draft` / `task switch --task-id <id>`); only cancel when explicitly asked (workflow.py cancel). Ask developer before guessing missing scenarios.{notes_rem}"


def _update_notice() -> str:
    """Newer-release notice at the start of a conversation (cached, at most once a day, never raises)."""
    try:
        from check_kit_update import update_notice
        return update_notice()
    except Exception:
        return ""


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        invocation = payload.get("invocationNum") if isinstance(payload, dict) else None
        initial = type(invocation) is int and invocation in (0, 1)
        msg = _message() if initial else _compact_message()
        if initial:
            msg = f"{msg} {_update_notice()}".strip()
        print(json.dumps({"injectSteps": [{"ephemeralMessage": msg}]}))
    except Exception:
        print("{}")


if __name__ == "__main__":
    main()
