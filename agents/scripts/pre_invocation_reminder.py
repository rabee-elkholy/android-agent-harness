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
        next_step = "Implement approved scope. Do NOT poll background tasks with manage_task status; wait for background notification."
    elif status == "VERIFYING":
        next_step = "Run only gates/reviewers in current-run policy. Record reviewer verdicts with `record_review.py --task <id> --reviewer <name> --verdict PASS`. If code fixes needed, run workflow.py resume."
    elif status == "BLOCKED":
        next_step = "Fix recorded findings with workflow.py resume, or request developer decision at the round cap."
    elif status == "READY_FOR_DELIVERY":
        next_step = "Do not mutate the delivery. Present the verified result and leave Git/Zoho actions to explicit requests."
    else:
        next_step = "Follow the central task lifecycle; do not infer authorization from this reminder."
    return f"Android Harness task {task_id}: {status}. {next_step} Zoho mutates only after explicit `update zoho`."


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        invocation = int(payload.get("invocationNum") or 0) if isinstance(payload, dict) else 0
        print(json.dumps({"injectSteps": [{"ephemeralMessage": _message()}]} if invocation in (0, 1) else {}))
    except Exception:
        print("{}")


if __name__ == "__main__":
    main()
