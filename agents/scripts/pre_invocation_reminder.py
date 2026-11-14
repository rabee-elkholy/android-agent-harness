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


def _developer_instructions_reminder(plan: dict | None = None) -> str:
    try:
        bound = list((plan or {}).get("developer_instructions") or [])
        if bound:
            ids = ", ".join(str(i.get("id") or "inst") for i in bound[:3])
            return f" Active developer instructions bound to task ({len(bound)}: {ids}) — enforce strictly."
        from project_context import load_developer_instructions_cached
        active = load_developer_instructions_cached(REPO, active_only=True)
        if active:
            ids = ", ".join(str(i.get("id") or "inst") for i in active[:3])
            return (
                f" Active developer instructions in `.agents/project-context/developer-instructions.json` "
                f"({len(active)}: {ids}) — honor across discovery, planning, and edits."
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


def _has_subagent_transcript_signature(conversation_id: str) -> bool:
    """Detect Turn-0 subagent transcripts (#200026 prefix-cache lock) before ledger binding completes."""
    if not conversation_id or conversation_id == "claude-session":
        return False
    try:
        from antigravity_runtime import prefer_full_transcript, resolve_transcript
        tp = prefer_full_transcript(resolve_transcript(conversation_id))
        if tp is None or not tp.is_file():
            return False
        head = tp.read_text(encoding="utf-8", errors="replace")[:4096]
        if '"USER_EXPLICIT"' in head:
            return False
        return (
            "MESSAGE_PRIORITY_HIGH" in head
            or "HARNESS_SCOUT_FINGERPRINT=" in head
            or "HARNESS_WORKER_FINGERPRINT=" in head
            or "REVIEWER_FINGERPRINT=" in head
        )
    except Exception:
        return False


def _is_reviewer_conversation(repo: Path, conversation_id: str) -> bool:
    """Prevent injecting implementer workflow/ask_question prompts into isolated reviewer or utility subagents.

    Also enforces byte-identical Turn-0 systemInstruction+tools prefix stability (#200026) across
    Scout, Worker, Specialist, and Reviewer subagents before PostToolUse execution_id binding finishes.
    """
    if not conversation_id:
        return False
    try:
        from delegation_policy import utility_subagent_context
        if utility_subagent_context(repo, conversation_id, bind=False) is not None:
            return True
    except (ImportError, OSError, ValueError, KeyError, ValidationError):
        pass
    if _has_subagent_transcript_signature(conversation_id):
        return True
    try:
        from reviewer_host import active_reviews, reviewer_context
        if not any(True for _ in active_reviews(repo)):
            return False
        ctx = reviewer_context(repo, conversation_id, bind=False)
        if not ctx:
            return False
        if ctx.get("role"):
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
    from _vnext_common import configure_utf8_output
    configure_utf8_output()
    try:
        from mutation_guard import active_plan
        plan = active_plan(REPO)
    except (ImportError, OSError, ValueError, KeyError, ValidationError):
        plan = {}
    notes_rem = _project_notes_reminder() + _developer_instructions_reminder(plan)
    mode_tag = ""
    try:
        from execution_mode import resolve_effective_execution_mode
        em = resolve_effective_execution_mode(REPO, plan=plan if isinstance(plan, dict) and plan else None)
        if em.get("selection_required"):
            mode_tag = " [Execution Mode: unset — ask via `ask_question` before starting a new task]"
        elif em.get("configured_mode") == "auto":
            mode_tag = f" [Execution Mode: auto->{em['mode']} ({em.get('effective_scope')})]"
        elif em.get("mode") in {"normal", "web"}:
            mode_tag = f" [Execution Mode: {em['mode']} ({em.get('effective_scope')})]"
    except Exception:
        mode_tag = ""
    if not plan:
        bridge_rem = _bridge_reminder()
        return f"Android Harness: Idle (no active task).{mode_tag} Use `python .agents/harness.py graph` (or `harness-scout-agent` for multi-file sweeps) for discovery; ask execution mode if unset before starting an implementation task.{notes_rem}{bridge_rem}"
    status = str(plan.get("status") or "UNKNOWN")
    task_id = str(plan.get("task_id") or "unknown")
    if status == "IMPLEMENTING":
        return (
            f"Harness [Task {task_id}: IMPLEMENTING]{mode_tag}: Autonomous execution. Do not create new plans or ask for Proceed. "
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
    return f"Harness [Task {task_id}: {status}]{mode_tag}: Discovery uses `python .agents/harness.py graph`. Discuss edge cases in chat before planning; only cancel when explicitly asked (workflow.py cancel).{notes_rem}"


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
        raw = __import__('_vnext_common').read_utf8_stdin()
        payload = json.loads(raw) if raw.strip() else {}
        invocation = payload.get("invocationNum") if isinstance(payload, dict) else None
        conversation_id = str(
            (payload.get("conversationId") or payload.get("conversation_id") or "")
            if isinstance(payload, dict) else ""
        ).strip()
        model_name = str(
            (payload.get("modelName") or payload.get("model_name") or "")
            if isinstance(payload, dict) else ""
        ).strip()
        if conversation_id and _is_reviewer_conversation(REPO, conversation_id):
            print("{}")
            return
        model_hazard_prefix = ""
        m_low = model_name.lower()
        if "orchestrator" in m_low:
            model_hazard_prefix = (
                f"[HAZARD #200029: Built-in `{model_name}` active] Switch the main chat model selector to explicit "
                "`Gemini 4 Carbon (Medium)` (or `Claude Sonnet 5.5`) — built-in Orchestrator risks false-positive 403 TOS_VIOLATION "
                "suspensions, locks `--effort`, and bloats shared Carbon context (-24% vs Harness Native Orchestrator -65%..-92%). "
            )
        elif "4.6" in m_low and "claude" in m_low:
            model_hazard_prefix = (
                f"[DEPRECATION NOTICE: `{model_name}` retires Nov 18, 2026] Switch mid-week rotation to `Claude Sonnet 5.5 (Thinking)` or `Claude Opus 5.5 (Thinking)`. "
            )
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
        if model_hazard_prefix:
            msg = f"{model_hazard_prefix}{msg}"
        print(json.dumps({"injectSteps": [{"ephemeralMessage": msg}]}))
    except Exception:
        print("{}")


if __name__ == "__main__":
    main()
