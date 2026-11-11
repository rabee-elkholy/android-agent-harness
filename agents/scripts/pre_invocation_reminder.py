"""Low-noise task-state reminder for hosts that support PreInvocation hooks."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import REPO  # noqa: E402
from _vnext_common import ValidationError  # noqa: E402


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
    except (ImportError, OSError, ValueError, KeyError, ValidationError):
        return ""
    return ""


def _bridge_reminder() -> str:
    try:
        from task_bridge import pending_bridge_reminder
        return pending_bridge_reminder(REPO)
    except (ImportError, OSError, ValueError, KeyError, ValidationError):
        return ""


def _post_subagent_directive(conversation_id: str) -> tuple[str, str]:
    if not conversation_id:
        return ("", "")
    try:
        from delegation_policy import pending_post_subagent_directive
        return pending_post_subagent_directive(REPO, conversation_id)
    except (ImportError, OSError, ValueError, KeyError, ValidationError):
        return ("", "")


def _is_reviewer_conversation(repo: Path, conversation_id: str) -> bool:
    """Prevent injecting implementer workflow/ask_question prompts into isolated reviewer or utility subagents."""
    if not conversation_id:
        return False
    try:
        from delegation_policy import utility_subagent_context
        if utility_subagent_context(repo, conversation_id, bind=False) is not None:
            return True
    except (ImportError, OSError, ValueError, KeyError, ValidationError):
        pass
    try:
        from reviewer_host import active_reviews, reviewer_context
        if not any(True for _ in active_reviews(repo)):
            return False
        ctx = reviewer_context(repo, conversation_id, bind=False)
        if not ctx:
            return False
        # Only treat as reviewer when bound to a real reviewer role, or when
        # the conversation actually has a subagent SYSTEM_MESSAGE transcript
        # (never suppress an unknown parent conversation before any child launches).
        if ctx.get("role"):
            return True
        if ctx.get("unverified_reviewer"):
            from antigravity_runtime import resolve_transcript
            tp = resolve_transcript(conversation_id)
            if tp is not None and tp.is_file():
                head = tp.read_text(encoding="utf-8", errors="replace")[:4096]
                if "MESSAGE_PRIORITY_HIGH" in head and '"USER_EXPLICIT"' not in head:
                    return True
        return False
    except Exception:
        return False


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
    except (ImportError, OSError, ValueError, KeyError, ValidationError):
        plan = {}
    notes_rem = _project_notes_reminder()
    if not plan:
        bridge_rem = _bridge_reminder()
        return f"Android Harness: Idle (no active task). Use `python .agents/harness.py graph` (or `harness-scout-agent` on Flash for multi-file sweeps) for discovery, or run `python .agents/scripts/workflow.py draft` to begin a task.{notes_rem}{bridge_rem}"
    status = str(plan.get("status") or "UNKNOWN")
    task_id = str(plan.get("task_id") or "unknown")
    if status == "IMPLEMENTING":
        return (
            f"Harness [Task {task_id}: IMPLEMENTING]: Autonomous execution. Do not create new plans or ask for Proceed. "
            f"Record in-scope developer refinements via `python .agents/harness.py task plan-note --task-id {task_id} --text \"<english summary>\" --source conversation --proof-reference \"<words>\"` before `prepare-verification`. "
            f"When a background command or subagent is still running, yield immediately with ZERO tool calls and never read `.system_generated/tasks/*.log` or emit '!]', '[Message]', '<SYSTEM_MESSAGE>'.{notes_rem}"
        )
    if status == "VERIFYING":
        return (
            f"Harness [Task {task_id}: VERIFYING]: Order: 1. preflight -> 2. unit tests -> 3. routed reviewers -> 4. device install (after ALL reviewers pass) -> 5. immediate `ask_question` first token (zero pre-tool prose, 3-section mobile walkthrough, no `|` tables) -> 6. task complete. "
            f"Run workflow.py resume for fixes; do not stall on follow-ups (phone E2E follows .agents/workflows/phone-e2e.md). "
            f"When a background command or subagent is running, yield immediately with ZERO tool calls; never read `.system_generated/tasks/*.log` or emit '!]', '[Message]'.{notes_rem}"
        )
    if status == "BLOCKED":
        blocked = plan.get("blocked_reviewers", [])
        blocked_str = f" ({', '.join(blocked)})" if blocked else ""
        return f"Harness [Task {task_id}: BLOCKED{blocked_str}]: Resume before fixing issues: `python .agents/scripts/workflow.py resume --repo . --task-id {task_id}`{notes_rem}"
    if status == "READY_FOR_DELIVERY":
        return f"Harness [Task {task_id}: READY_FOR_DELIVERY]: Git actions belong to the developer. Invoke `ask_question` IMMEDIATELY as your first token (ZERO pre-tool chat prose) with the Commit & Delivery Card inside `question`.{notes_rem}"
    return f"Harness [Task {task_id}: {status}]: Discovery uses `python .agents/harness.py graph`. Discuss edge cases in chat before planning; only cancel when explicitly asked (workflow.py cancel).{notes_rem}"


def _current_task_state() -> tuple[str, str]:
    try:
        from mutation_guard import active_plan
        plan = active_plan(REPO)
    except (ImportError, OSError, ValueError, KeyError, ValidationError):
        plan = {}
    if not plan:
        return ("", "IDLE")
    return (str(plan.get("task_id") or "unknown"), str(plan.get("status") or "UNKNOWN"))


def _unchanged_state_message(task_id: str, status: str) -> str:
    if not task_id or status == "IDLE":
        return "Android Harness: Idle (no active task)."
    return f"Harness [{task_id}:{status}]: State unchanged; yield with ZERO tool calls if a bg task runs, else run NEXT_ACTION."


def _is_raw_kit_repo(repo: Path) -> bool:
    return (repo / "harness_cli.py").is_file() and (repo / "agents" / "VERSION").is_file() and not (repo / ".agents").is_dir()


def _has_any_seen_state(conversation_id: str) -> bool:
    if not conversation_id or _is_raw_kit_repo(REPO):
        return False
    cache_path = REPO / ".agents" / "cache" / "reminder-state.json"
    try:
        if cache_path.is_file():
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return isinstance(data, dict) and conversation_id in data
    except (OSError, ValueError):
        return False
    return False


def _has_seen_state(conversation_id: str, state_key: str) -> bool:
    if not conversation_id or _is_raw_kit_repo(REPO):
        return False
    cache_path = REPO / ".agents" / "cache" / "reminder-state.json"
    try:
        if cache_path.is_file():
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get(conversation_id) == state_key:
                return True
    except (OSError, ValueError):
        return False
    return False


def _record_seen_state(conversation_id: str, state_key: str) -> None:
    if not conversation_id or _is_raw_kit_repo(REPO):
        return
    cache_path = REPO / ".agents" / "cache" / "reminder-state.json"
    try:
        data: dict[str, str] = {}
        if cache_path.is_file():
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = {str(k): str(v) for k, v in list(raw.items())[-49:]}
            except (OSError, ValueError):
                data = {}
        data[conversation_id] = state_key
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(f".{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp_path, cache_path)
    except (OSError, ValueError):
        return


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
        conversation_id = str(
            (payload.get("conversationId") or payload.get("conversation_id") or "")
            if isinstance(payload, dict) else ""
        ).strip()
        if conversation_id and _is_reviewer_conversation(REPO, conversation_id):
            print("{}")
            return
        wave_key, wave_directive = _post_subagent_directive(conversation_id)
        # Antigravity is 0-indexed (0 is first call); 1-indexed hosts start at 1.
        # Avoid dumping the full initial reminder + update check twice when invocation 0 already ran.
        initial = type(invocation) is int and (
            invocation == 0
            or (invocation == 1 and (not conversation_id or not _has_any_seen_state(conversation_id)))
        )
        if initial:
            msg = f"{_message()} {_update_notice()}".strip()
            if wave_directive:
                msg = f"{msg} {wave_directive}"
            if conversation_id:
                tid, st = _current_task_state()
                state_key = f"{tid}:{st}:{wave_key}" if wave_key else f"{tid}:{st}"
                _record_seen_state(conversation_id, state_key)
        elif conversation_id:
            tid, st = _current_task_state()
            state_key = f"{tid}:{st}:{wave_key}" if wave_key else f"{tid}:{st}"
            if _has_seen_state(conversation_id, state_key):
                msg = _unchanged_state_message(tid, st)
                if wave_directive:
                    msg = f"{msg} {wave_directive}"
            else:
                msg = _compact_message() if not wave_directive else f"{_unchanged_state_message(tid, st)} {wave_directive}"
                _record_seen_state(conversation_id, state_key)
        else:
            msg = _compact_message()
        print(json.dumps({"injectSteps": [{"ephemeralMessage": msg}]}))
    except Exception:
        print("{}")


if __name__ == "__main__":
    main()
