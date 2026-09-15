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
            "or `--find <Symbol>` (mandatory even with known commits/files) before inspecting files. Unanchored grep cascades are forbidden. "
            "Pre-planning clarification: Guessing edge cases or missing business logic is strictly prohibited. "
            "If any requirement, fallback, or scenario is ambiguous, invoke `ask_question` to clarify with developer BEFORE drafting the plan. "
            "Verification plan must use strict 6-step headings."
        )
    status = str(plan.get("status") or "UNKNOWN")
    task_id = str(plan.get("task_id") or "unknown")
    if status == "AWAITING_DEVELOPER_APPROVAL":
        next_step = "Wait for explicit approval; do not edit files or run mutating commands."
    elif status == "IMPLEMENTING":
        next_step = (
            "Implement approved scope. Multi-phase execution is fully autonomous: single intake approval covers all phases; "
            "never pause, demand 'Proceed', or ask developer between phases. Self-heal compile errors. Do NOT poll background tasks."
        )
    elif status == "VERIFYING":
        next_step = (
            "Strict verification order: 1. preflight -> 2. unit tests -> 3. routed reviewers (parallel) -> 4. device install (ONLY after all reviewers pass) -> 5. ask_question device check -> 6. verify. "
            "Reviewer dispatch is 100% autonomous via subagents; never pause, ask developer, or demand 'Proceed'. Never assemble or install on device while reviewers are still executing. "
            "Passing gates bridge automatically into evidence. If fixes needed, run workflow.py resume; never stall on new plans or demand 'Proceed'."
        )
    elif status == "BLOCKED":
        blocked = plan.get("blocked_reviewers", [])
        blocked_str = f" from: {', '.join(blocked)}" if blocked else ""
        next_step = f"Task is BLOCKED due to findings{blocked_str}. Fix code issues, then resume via: `python .agents/scripts/workflow.py resume --repo . --task-id {task_id}`."
    elif status == "READY_FOR_DELIVERY":
        try:
            from workflow import finalize_ready_delivery
            plan, delivered = finalize_ready_delivery(REPO, task_id, plan, require_clean_tree=True)
            if delivered:
                return (
                    "Android Harness: discovery MUST start with `python .agents/scripts/project_graph.py --feature <name>` "
                    "or `--find <Symbol>` before inspecting files. Unanchored grep cascades are forbidden. "
                    "Pre-planning clarification: clarify missing scenarios via ask_question before drafting plan."
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
            return f"Harness [Task {task_id}: IMPLEMENTING]: Autonomous multi-phase execution. Do not create new plans or ask for Proceed. Wait for background task completion."
        if status == "VERIFYING":
            return f"Harness [Task {task_id}: VERIFYING]: Order: 1. preflight -> 2. unit tests -> 3. routed reviewers -> 4. device install (only after ALL reviewers pass) -> 5. verify. Run workflow.py resume for fixes; do not stall on follow-ups."
        if status == "BLOCKED":
            blocked = plan.get("blocked_reviewers", [])
            blocked_str = f" ({', '.join(blocked)})" if blocked else ""
            return f"Harness [Task {task_id}: BLOCKED{blocked_str}]: Fix issues and run: `python .agents/scripts/workflow.py resume --repo . --task-id {task_id}`"
        if status == "READY_FOR_DELIVERY":
            return f"Harness [Task {task_id}: READY_FOR_DELIVERY]: Commit changes with Conventional Commit, or run 'workflow.py deliver' to close."
        return f"Harness [Task {task_id}: {status}]: Discovery uses `project_graph.py`. Ask developer before guessing missing scenarios."
    except Exception:
        return "Android Harness: Use `project_graph.py --feature <name>` or `--find <Symbol>`. Unanchored grep cascades and guesswork are forbidden."


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
