"""Small fail-closed host hook for the vNext plan and safety boundary.

The hook does not implement review policy. It protects infrastructure, blocks
irreversible or external command classes, and delegates task authority to
``mutation_guard.py``. Adaptive reviewers and gates come only from run policy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path

__file__ = str(Path(__file__).resolve().parents[1] / "pre_tool_safety.py")

sys.path.insert(0, str(Path(__file__).resolve().parent))
_SCRIPTS_DIR = Path(__file__).resolve().parent
_env_repo = os.environ.get("HARNESS_REPO", "").strip()
REPO = Path(_env_repo).resolve() if _env_repo else _SCRIPTS_DIR.parent.parent
from _vnext_common import ValidationError, active_review_package_path, read_json, sha256_file, state_root, validate_id  # noqa: E402


def active_plan(repo: Path | str, *, allow_missing: bool = False) -> dict:
    """Resolve a live task; optional diagnostics tolerate absence, never a broken pointer."""
    repo_path = Path(repo)
    installed = repo_path / ".agents" / "state"
    state = installed if installed.parent.is_dir() else repo_path / "agents" / "state"
    active_file = state / "active-task.json"
    if active_file.is_file():
        try:
            active = read_json(active_file)
            plan_path = Path(str(active.get("plan_path") or ""))
            if not plan_path.is_absolute():
                plan_path = repo_path / plan_path
            plan_resolved = plan_path.resolve()
            state_resolved = state.resolve()
            if state_resolved != plan_resolved and state_resolved not in plan_resolved.parents:
                raise ValidationError("active plan path escapes harness state")
            if plan_resolved.is_file():
                return read_json(plan_resolved)
        except ValidationError:
            raise
        except (OSError, ValueError):
            pass
    from mutation_guard import active_plan as _full_active_plan
    return _full_active_plan(repo, allow_missing=allow_missing)


def _entry(command: str, repo: Path | str = ".") -> tuple[str, list[str]]:
    from mutation_guard import _entry as _mg_entry
    return _mg_entry(command, repo)


def command_allowed(repo: Path | str, command: str) -> tuple[bool, str]:
    from mutation_guard import command_allowed as _mg_command_allowed
    return _mg_command_allowed(repo, command)


def file_mutation_allowed(repo: Path | str, targets: list[str] | None = None) -> tuple[bool, str, str]:
    from mutation_guard import file_mutation_allowed as _mg_file_mutation_allowed
    return _mg_file_mutation_allowed(repo, targets=targets)


from policy_vocab import (
    ON_DEMAND_SPECIALIST_AGENTS,
    ANTIGRAVITY_REVIEWER_TOOLS,
    ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS,
    CORE_ROUTED_REVIEWERS,
    CORE_UTILITY_AGENTS,
    SUBAGENT_ORCHESTRATION_TOOLS,
)

COMMON_REASONING_KEYS = {
    "reasoning",
    "Reasoning",
    "reasoning_effort",
    "ReasoningEffort",
    "effort",
    "Effort",
    "thinking_level",
    "ThinkingLevel",
}

MAX_STDIN_BYTES = 5 * 1024 * 1024
AUDIT_MAX_RECORDS = 1000
AUDIT_ROTATE_BYTES = 1024 * 1024
WRITE_TOOLS = {
    "write_to_file", "write_file", "replace_file_content", "multi_replace_file_content", "edit_file",
    "apply_patch", "edit", "multiedit",
    "create_file", "delete_file", "move_file", "rename_file",
}
SUBAGENT_TOOLS = frozenset(SUBAGENT_ORCHESTRATION_TOOLS)
SEARCH_TOOLS = {"grep_search", "find_by_name"}


def _get_registry():
    from integrations.registry import registry as _reg
    return _reg


KNOWN_MCP_READ_PREFIXES = (
    "get_", "list_", "read_", "search_", "fetch_", "query_", "check_", "inspect_",
    "api-get-", "api-retrieve-", "api-query-", "developerknowledge_",
)
KNOWN_MCP_MUTATION_KEYWORDS = (
    "create", "update", "delete", "patch", "post", "put", "deploy", "write",
    "mutate", "drop", "send", "publish", "archive", "grant", "merge", "assign",
    "close", "trigger", "resolve", "execute", "destroy", "set_", "add_", "remove_",
)
PROTECTED_ROOTS = (
    ".agents", "agents/scripts", "agents/state", ".harness-setup",
    ".git", ".gradle", ".idea",
)
EPHEMERAL_GENERATED_RE = re.compile(
    r"(?:^|/)build/(?:generated|intermediates)/|^generated/(?:source|ksp|kapt)/",
    re.I,
)

# These stay denied even during approved implementation: they cross the local
# development boundary or make recovery materially harder.
DENY_HINTS = {
    "draft_force": "To correct a plan that awaits approval, run `python .agents/scripts/workflow.py revise --repo . --task-id <id>` "
                   "with the corrected arguments. To replace a different live task, ask the developer to cancel it.",
    "raw_adb": "To read logcat without breaking Windows PowerShell Turbo Mode (#200632 — never use PowerShell pipes), run "
               "`python .agents/harness.py debug logs` or standalone `adb logcat -d -t 500`. For device status or app install/launch, use "
               "`python .agents/harness.py device status` or `python .agents/harness.py device install-start`.",
    "agy_headless_loop_tos_guard": "Subprocess invocations of `agy` / `antigravity` CLI and programmatic UI keystroke injection inside `run_command` are blocked because driving `agy` from an agent or testing `AGENTS.md` via nested `agy` triggers automated Google Section 6 ToS 403 PERMISSION_DENIED account suspension (#201582/#201491/#199748/#199756). Validate rules deterministically via `python harness_cli.py selftest` / `validate_release.py` instead.",
}
DANGEROUS = (
    ("git_mutation", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*g[i\u0131]t(?:\.exe)?(?:\s+-c\s+\S+)*\s+(?:add|am|apply|branch|checkout|clean|commit|config|fetch|gc|merge|mv|prune|pull|push|rebase|remote\s+(?:add|remove|set-url)|reset|restore|rm|stash|switch|tag|update-index|worktree)(?![\w-])", re.I)),
    ("shell_indirection", re.compile(r"\b(?:base64\s+(?:-d|--decode)|frombase64string|invoke-expression|iex|eval)\b", re.I)),
    ("adb_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:root|remount|backup|restore|disable-verity|enable-verity|uninstall|clear)\b", re.I | re.S)),
    ("package_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:pm|cmd\s+package)\s+(?:clear|uninstall|disable|suspend|install-existing)\b", re.I | re.S)),
    ("raw_adb", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*adb(?:\.exe)?\b", re.I)),
    ("harness_device_emergency", re.compile(r"(?:run_device(?:\.py)?\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+(?:--\S+\s+)*device\b)(?:(?=.*\s--force(?:=|\b))|(?=.*\s--grant-runtime-permissions(?:=|\b))|(?:\s+--\S+)*\s+uninstall\b)", re.I)),
    ("tracker_write", re.compile(r"(?:\b(?:zoho|jira|linear)\b.*\b(?:create|update|delete|close|transition|done|solved)\b|\b(?:create|update|delete|close|transition|done|solved)[_\s-]*(?:zoho|jira|linear)\b)", re.I | re.S)),
    ("draft_force", re.compile(r"(?:workflow(?:\.py)?\b.*\bdraft\b.*--force(?:=|\b)|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+(?:--\S+\s+)*task\b.*\bdraft\b.*--force(?:=|\b))", re.I)),
    ("review_override_provenance", re.compile(r"(?:record_review(?:\.py)?\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+(?:--\S+\s+)*review\b)(?=.*--override-reviews\b)(?=.*--source(?:\s+|=)[\x22\x27]?developer_terminal\b)", re.I)),
    ("lead_verdict_bypass", re.compile(r"(?:record_review(?:\.py)?\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+(?:--\S+\s+)*review\b).*--allow-lead-verdict(?:=|\b)", re.I)),
    ("exported_component_acceptance", re.compile(r"exported_component_guard(?:\.py)?\b.*--accept(?:=|\b)", re.I)),
    ("review_complete_text_bypass", re.compile(r"(?:review_orchestrator(?:\.py)?|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+(?:--\S+\s+)*review)\b.*\bcomplete\b.*--text(?:=|\b)", re.I)),
    ("signoff_authority", re.compile(r"(?:run_device(?:\.py)?\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+(?:--\S+\s+)*device\b).*\bsignoff\b", re.I)),
    ("dirty_tree_delivery_override", re.compile(r"(?:workflow(?:\.py)?\b.*\bdeliver\b.*--(?:allow-dirty-tree|developer-allow-dirty-tree)(?:=|\b)|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+(?:--\S+\s+)*task\b.*\bdeliver\b.*--(?:allow-dirty-tree|developer-allow-dirty-tree)(?:=|\b))", re.I)),
    ("agy_headless_loop_tos_guard", re.compile(r"(?:^|[;&|\n]\s*|\b(?:do|then|else|xargs|env|command|exec|start|call)\s+)(?:&\s*)?(?:\"[^\"]*[/\\]|'[^']*[/\\]|[^\s\"';&|]*[/\\])?(?:agy(?:\.exe|\.cmd|\.bat|\.ps1)?|antigravity(?:\.exe|\.cmd|\.bat)?)(?=\s|$|[\"';&|])|(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*(?:agy|antigravity)(?:\.exe|\.cmd)?\s+(?:-[a-z]*p\b|--prompt\b|--headless\b)|(?:\b(?:xdotool|pyautogui|sendkeys|wscript\.shell)\b.*\b(?:antigravity|agy)\b)", re.I)),
)
WORKFLOW_ENTRYPOINTS = {"workflow.py", "workflow"}
TASK_ENTRYPOINTS = {"harness.py", "harness", "harness_cli.py", "harness_cli", "android-harness"}
WORKFLOW_VALUE_FLAGS = {"--repo", "--task-id", "--task", "--kit"}


AUDITED_HARNESS_ENTRY = re.compile(
    r"^\s*(?:\"[^\"]+\"|'[^']+'|\S+)?(?:python(?:\d+(?:\.\d+)?)?(?:\.exe)?|py(?:\.exe)?)\s+(?:-(?:3(?:\.\d+)?|u|B|S|E)\s+)*(?:\"[^\"]*?(?:harness|harness_cli|workflow|zoho_sync|pm_discovery|web_relay|execution_mode|generate_project_context)\.py\"|'[^']*?(?:harness|harness_cli|workflow|zoho_sync|pm_discovery|web_relay|execution_mode|generate_project_context)\.py'|\S*?(?:harness|harness_cli|workflow|zoho_sync|pm_discovery|web_relay|execution_mode|generate_project_context)\.py)\s", re.I,
)



CANCEL_REQUEST_FILE = "cancel-requested.json"
CANCEL_REQUEST_TTL_SECONDS = 30 * 60


def _cancel_command(task_id: str) -> str:
    return f"python .agents/scripts/workflow.py cancel --repo . --task-id {task_id or '<id>'}"


def _record_cancel_request(task_id: str) -> None:
    """The agent tried to cancel: until the developer does, it may not resume or edit to undo the work."""
    if not task_id:
        return
    try:
        from _vnext_common import atomic_write_json
        atomic_write_json(state_root(REPO) / CANCEL_REQUEST_FILE, {"task_id": task_id, "requested_at": time.time()})
    except (OSError, ValueError, ImportError, ValidationError):
        pass


def _detect_live_verification_or_build_owner(repo: Path, active_tid: str | None) -> int:
    """Return external live PID holding the workspace build lock or task execution lease, or 0."""
    try:
        from _vnext_common import state_root, task_dir
        from evidence_store import StateLock
        lock_roots = [state_root(repo) / "android-build-execution"]
        if active_tid:
            lock_roots.append(task_dir(repo, active_tid) / "execution")
        cur_pid = os.getpid()
        for lr in lock_roots:
            sl = StateLock(lr, timeout_seconds=0)
            if not sl.path.is_file():
                continue
            live, owner = sl._owner_live()
            if live and isinstance(owner, dict):
                opid = int(owner.get("pid") or 0)
                if opid > 0 and opid != cur_pid:
                    return opid
    except (ImportError, OSError, ValueError, TypeError, ValidationError):
        return 0
    return 0


def _pending_cancel(task_id: str) -> bool:
    if not task_id:
        return False
    marker = state_root(REPO) / CANCEL_REQUEST_FILE
    try:
        data = json.loads(marker.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    fresh = time.time() - float(data.get("requested_at") or 0) < CANCEL_REQUEST_TTL_SECONDS
    return fresh and str(data.get("task_id") or "") == task_id


def _cancel_pending_message(task_id: str) -> str:
    return (
        f"Cancelling task '{task_id}' is the developer's decision. Only when the developer asked for it in the chat, run "
        f"`{_cancel_command(task_id)} --source conversation --proof-reference \"<the developer's words>\"`. Never cancel on "
        "your own, and never resume the task or edit files to undo the work: the task closes and the files stay as they "
        "are for the developer to keep or restore. If they did not ask, ask them with ask_question first."
    )


RAW_GRADLE = re.compile(r"(?:^|[;&|\n]\s*)(?:\.\/?|[^\s]+[/\\])?(?:gradlew|gradle)(?:\.bat)?\s+", re.I)
IMMUTABLE_ADAPTER_FILES = frozenset({
    "agents.md",
    "gemini.md",
})


_ACTIVE_HOOK_CONVERSATION_ID: str = ""
_ACTIVE_HOOK_MODEL_NAME: str = ""

# HYDROGEN_ANTI_BURST_PACER (#200029 / #199971):
# Protects Google AI Ultra / Pro accounts from false-positive 403 PERMISSION_DENIED (TOS_VIOLATION)
# suspensions caused by Gemini 4 Hydrogen firing rapid sequential single-tool turns (<0.5s apart)
# during Plan Execution, while keeping same-turn parallel tool batches (<=200ms delta) at 0ms delay.
BURST_COALESCE_PARALLEL_SEC = 0.20
BURST_WINDOW_SEC = 6.0
BURST_TURN_THRESHOLD = 4
BURST_BASE_DELAY_SEC = 0.80
BURST_STEP_DELAY_SEC = 0.15
BURST_MAX_DELAY_SEC = 1.40


def _tool_name_and_args(payload: dict) -> tuple[str, dict]:
    raw_tc = payload.get("toolCall")
    raw_tc_snake = payload.get("tool_call")
    call = raw_tc if isinstance(raw_tc, dict) else (raw_tc_snake if isinstance(raw_tc_snake, dict) else {})
    name = str(call.get("name") or call.get("toolName") or payload.get("toolName") or payload.get("tool_name") or payload.get("tool") or "").lower()
    args = call.get("args") or payload.get("toolArgs") or payload.get("tool_input") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return name, args if isinstance(args, dict) else {}


_ALL_ENDPOINT_KEYS = (
    "TargetFile", "targetFile", "Path", "path", "AbsolutePath", "absolutePath",
    "file_path", "filePath", "source", "source_path", "sourcePath", "old_path", "oldPath",
    "from", "from_path", "fromPath", "destination", "destination_path", "destinationPath",
    "new_path", "newPath", "to", "to_path", "toPath", "target_path", "targetPath",
)
_PATCH_FILE_HEADER_RE = re.compile(
    r"^(?:\+\+\+\s+(?:b/)?|---\s+(?:a/)?|\*\*\*\s+(?:Update|Add|Delete)\s+File:\s*|\*\*\*\s+Move\s+to:\s*)(.+)$",
    re.MULTILINE,
)


def _target(args: dict) -> str:
    for key in _ALL_ENDPOINT_KEYS:
        if args.get(key):
            return str(args[key]).replace("\\", "/")
    return ""


def _extract_all_targets(args: dict) -> list[str]:
    targets = []
    for key in _ALL_ENDPOINT_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            targets.append(val.strip().replace("\\", "/"))
    for key in ("files", "Files", "paths", "Paths", "targets", "Targets", "edits", "Edits"):
        val = args.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    targets.append(item.replace("\\", "/"))
                elif isinstance(item, dict):
                    for ek in _ALL_ENDPOINT_KEYS:
                        ev = item.get(ek)
                        if isinstance(ev, str) and ev.strip():
                            targets.append(ev.strip().replace("\\", "/"))
    for pkey in ("patch", "Patch", "diff", "Diff", "patch_text", "patchText"):
        pval = args.get(pkey)
        if isinstance(pval, str) and pval.strip():
            for m in _PATCH_FILE_HEADER_RE.finditer(pval):
                cand = m.group(1).strip().split("\t", 1)[0].strip()
                if cand and cand != "/dev/null":
                    targets.append(cand.replace("\\", "/"))
    return list(dict.fromkeys(targets))


def _resolve_hook_cwd(raw_cwd: Any) -> Path:
    if not raw_cwd:
        return REPO.resolve()
    p = Path(str(raw_cwd)).expanduser()
    return p.resolve() if p.is_absolute() else (REPO / p).resolve()


def _is_side_question_payload(payload: dict) -> bool:
    """Detect Antigravity v2.32.2+ multi-turn `/btw` Side Question read-only tabs."""
    if not isinstance(payload, dict):
        return False
    if bool(payload.get("isSideQuestion") or payload.get("is_side_question") or payload.get("sideQuestion") or payload.get("side_question")):
        return True
    for key in ("mode", "Mode", "surface", "Surface", "conversationKind", "conversation_kind", "tabKind", "tab_kind"):
        val = str(payload.get(key) or "").strip().lower()
        if val in {"btw", "/btw", "side_question", "side-question", "sidequestion"}:
            return True
    return False


def _handle_stop() -> None:
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
    except Exception:
        _self.emit("allow", "No active vNext task requires a delivery stop.", tool="stop", reason_code="STOP_IDLE")
        return
    _self.emit("allow", f"Turn completion permitted for task in status {status or 'unknown'}.", tool="stop", reason_code="STOP_ALLOWED")


CONVERSATION_LIMIT = 50
CODE_READ_SUFFIXES = (".kt", ".kts", ".java", ".xml", ".gradle")


SEARCH_WEB_BURST_WINDOW_SEC = 8.0
SEARCH_WEB_MAX_PARALLEL_CALLS = 2
SEARCH_WEB_WAVE_WINDOW_SEC = 45.0
SEARCH_WEB_MAX_WAVE_CALLS = 4


def main() -> None:
    from _vnext_common import configure_utf8_output
    configure_utf8_output()
    previous = os.environ.get("HARNESS_HOST")
    os.environ["HARNESS_HOST"] = "antigravity"
    try:
        _main()
    finally:
        if previous is None:
            os.environ.pop("HARNESS_HOST", None)
        else:
            os.environ["HARNESS_HOST"] = previous


def _main() -> None:
    try:
        raw = __import__('_vnext_common').read_utf8_stdin()
        if len(raw.encode("utf-8", errors="replace")) > MAX_STDIN_BYTES:
            _self.emit("deny", "Hook payload exceeds the 5 MiB safety limit.")
            return
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            raise ValueError("hook payload must be an object")
        if (
            any(key in payload for key in ("terminationReason", "termination_reason", "continuation_active", "continuationActive"))
            or payload.get("event") == "Stop"
            or payload.get("hook") == "Stop"
            or payload.get("hookEventName") == "Stop"
        ):
            _handle_stop()
            return
        started = _self._conversation_started_at(payload)
        if started is not None:
            import discovery_receipt
            discovery_receipt.RECEIPT_NOT_BEFORE = started
        name, args = _tool_name_and_args(payload)
        is_side_question = _is_side_question_payload(payload)
        if is_side_question:
            if name in WRITE_TOOLS or name in SUBAGENT_TOOLS or name.startswith("schedules:") or name in ("call_mcp_tool", "mcp_tool") or name.startswith("mcp_"):
                _self.emit(
                    "deny",
                    "SIDE_QUESTION_READ_ONLY_BOUNDARY: `/btw` side-question tabs are strictly read-only; ask in the main conversation to mutate files, invoke subagents, or call MCP tools.",
                    tool=name,
                    reason_code="SIDE_QUESTION_READ_ONLY_BOUNDARY",
                )
                return
        reviewer = None
        conversation = str(payload.get("conversationId") or payload.get("conversation_id") or "")
        transcript_hint = str(payload.get("transcriptPath") or payload.get("transcript_path") or "")
        global _ACTIVE_HOOK_CONVERSATION_ID, _ACTIVE_HOOK_MODEL_NAME
        _ACTIVE_HOOK_CONVERSATION_ID = conversation.strip()
        _ACTIVE_HOOK_MODEL_NAME = str(payload.get("modelName") or payload.get("model_name") or "").strip()
        if conversation and os.environ.get("HARNESS_HOST") == "antigravity":
            from reviewer_host import reviewer_context, discovery_command_allowed
            reviewer = reviewer_context(REPO, conversation, bind=True)
            if reviewer:
                if name == "run_command":
                    command = str(args.get("CommandLine") or args.get("commandLine") or args.get("command") or "")
                    cwd = _resolve_hook_cwd(args.get("Cwd") or args.get("cwd"))
                    if cwd != REPO.resolve() or not discovery_command_allowed(command):
                        _self.emit("deny", "Reviewer run_command permits only bounded graph/task-context discovery.", tool=name, reason_code="REVIEWER_READ_ONLY_BOUNDARY")
                        return
                elif name not in {"view_file", "read_file", "read", "grep_search", "find_by_name", "list_dir"}:
                    _self.emit("deny", "Reviewer tools are limited to source reads and bounded discovery. Do NOT call send_message; output your final review response directly as plain assistant text and end your turn.", tool=name, reason_code="REVIEWER_READ_ONLY_BOUNDARY")
                    return
                if reviewer.get("role"):
                    from delegation_policy import check_and_record_subagent_step_budget
                    r_run = reviewer.get("run") or {}
                    r_run_id = str(r_run.get("run_id") or r_run.get("phase_review_run_id") or "")
                    ok_rb, reason_rb, code_rb = check_and_record_subagent_step_budget(
                        REPO,
                        conversation,
                        kind="REVIEWER",
                        tool_name=name,
                        run_id=r_run_id,
                        role=str(reviewer.get("role") or ""),
                    )
                    if not ok_rb:
                        _self.emit("deny", reason_rb, tool=name, reason_code=code_rb)
                        return
                if name in SEARCH_TOOLS:
                    from discovery_receipt import load_latest_discovery_receipt, check_discovery_freshness, is_path_in_discovery_scope
                    receipt = load_latest_discovery_receipt(REPO)
                    target = str(args.get("SearchPath") or args.get("searchPath") or args.get("SearchDirectory") or args.get("searchDirectory") or "")
                    if receipt and check_discovery_freshness(REPO, receipt)[0] and is_path_in_discovery_scope(REPO, target, receipt) and not _self._installed_engine_target(target, recursive=True):
                        _self.emit("allow", "Reviewer search is inside its graph discovery scope.", tool=name, reason_code="REVIEWER_DISCOVERY_SEARCH_ALLOWED")
                        return
        utility_ctx = None
        if not reviewer and (conversation or os.environ.get("HARNESS_UTILITY_AGENT")):
            try:
                from delegation_policy import (
                    SCOUT_AGENT,
                    SPECIALIST_AGENT,
                    check_and_record_subagent_step_budget,
                    scout_command_allowed,
                    utility_subagent_context,
                )
                utility_ctx = utility_subagent_context(REPO, conversation, bind=True)
            except (ImportError, OSError, ValueError, KeyError, ValidationError):
                utility_ctx = None

        if utility_ctx is not None:
            u_type = str(utility_ctx.get("agent_type") or "")
            u_exec = str(utility_ctx.get("execution_id") or conversation or f"env-{u_type}")
            if u_type == SCOUT_AGENT:
                try:
                    import discovery_receipt
                    discovery_receipt.RECEIPT_NOT_BEFORE = 0.0
                except (ImportError, AttributeError):
                    pass
                if name == "run_command":
                    cmd_str = str(args.get("CommandLine") or args.get("commandLine") or args.get("command") or "")
                    cwd_p = _resolve_hook_cwd(args.get("Cwd") or args.get("cwd"))
                    if cwd_p != REPO.resolve() or not scout_command_allowed(cmd_str):
                        _self.emit(
                            "deny",
                            "Scout subagent run_command permits only standalone read-only graph, task-context, symbol outline/read, android-inspect, doctor, or git status/diff/log/grep/ls-files inspection (no pipes/chaining). Use `git grep -n \"<pattern>\"` / `git ls-files` or native `grep_search` / `find_by_name` instead of shell `findstr`/`rg`.",
                            tool=name,
                            reason_code="SCOUT_READ_ONLY_BOUNDARY",
                        )
                        return
                elif name in {"view_file", "read_file", "read"}:
                    _sc_tgt = str(args.get("AbsolutePath") or args.get("absolutePath") or _target(args) or "")
                    if _self._is_raw_graph_cache_read_target(_sc_tgt):
                        _self.emit(
                            "deny",
                            "RAW_GRAPH_CACHE_READ_BLOCKED: Never read raw machine cache `.agents/cache/project_graph.json` directly with `read_file`/`view_file` (causes massive token bloat). Query indexed symbols/features compactly via `python .agents/harness.py graph --find <Symbol>` or native `grep_search`.",
                            tool=name,
                            reason_code="RAW_GRAPH_CACHE_READ_BLOCKED",
                        )
                        return
                    if _self._is_large_step_output_paginated_read(_sc_tgt, args):
                        _self.emit(
                            "deny",
                            "LARGE_STEP_OUTPUT_PAGINATION_BLOCKED: Never paginate large `.system_generated/steps/*/output.txt` dumps via `read_file` `ByteOffset` (causes 200K+ token bloat). Run `python .agents/harness.py pm find-item --item <id> --file \"<output.txt>\"` or `grep_search` instead.",
                            tool=name,
                            reason_code="LARGE_STEP_OUTPUT_PAGINATION_BLOCKED",
                        )
                        return
                elif name not in {"view_file", "read_file", "read", "grep_search", "find_by_name", "list_dir", "search_web"}:
                    _self.emit(
                        "deny",
                        f"`{SCOUT_AGENT}` is strictly read-only; mutations, subagent calls, `send_message`, and developer prompts are forbidden. Output your digest directly as plain assistant text.",
                        tool=name,
                        reason_code="SCOUT_READ_ONLY_BOUNDARY",
                    )
                    return
                ok_sb, reason_sb, code_sb = check_and_record_subagent_step_budget(
                    REPO, u_exec, kind="SCOUT", tool_name=name, role=SCOUT_AGENT,
                )
                if not ok_sb:
                    _self.emit("deny", reason_sb, tool=name, reason_code=code_sb)
                    return
            elif u_type == SPECIALIST_AGENT:
                try:
                    import discovery_receipt
                    discovery_receipt.RECEIPT_NOT_BEFORE = 0.0
                except (ImportError, AttributeError):
                    pass
                if name in SUBAGENT_TOOLS | {"ask_question"}:
                    _self.emit(
                        "deny",
                        f"Specialist subagent `{utility_ctx.get('role')}` cannot call `{name}`; output your final report directly as plain assistant text and end your turn.",
                        tool=name,
                        reason_code="SUBAGENT_SEND_MESSAGE_FORBIDDEN",
                    )
                    return
                if utility_ctx.get("read_only_specialist"):
                    if name == "run_command":
                        cmd_str = str(args.get("CommandLine") or args.get("commandLine") or args.get("command") or "")
                        cwd_p = _resolve_hook_cwd(args.get("Cwd") or args.get("cwd"))
                        if cwd_p != REPO.resolve() or not scout_command_allowed(cmd_str):
                            _self.emit(
                                "deny",
                                f"Specialist subagent `{utility_ctx.get('role')}` is read-only for repository code.",
                                tool=name,
                                reason_code="SPECIALIST_READ_ONLY_BOUNDARY",
                            )
                            return
                    elif name not in {"view_file", "read_file", "read", "grep_search", "find_by_name", "list_dir", "search_web"}:
                        _self.emit(
                            "deny",
                            f"Specialist subagent `{utility_ctx.get('role')}` is strictly read-only.",
                            tool=name,
                            reason_code="SPECIALIST_READ_ONLY_BOUNDARY",
                        )
                        return
                ok_spb, reason_spb, code_spb = check_and_record_subagent_step_budget(
                    REPO, u_exec, kind="SPECIALIST", tool_name=name, role=str(utility_ctx.get("role") or SPECIALIST_AGENT),
                )
                if not ok_spb:
                    _self.emit("deny", reason_spb, tool=name, reason_code=code_spb)
                    return

        if conversation and not is_side_question and not reviewer and utility_ctx is None:
            try:
                from task_bridge import record_active_conversation_turn
                record_active_conversation_turn(REPO, conversation)
            except (ImportError, OSError, ValueError):
                pass
        if name in {"view_file", "read_file", "read", "grep_search", "find_by_name", "list_dir"}:
            target = str(args.get("AbsolutePath") or args.get("absolutePath") or args.get("SearchPath")
                         or args.get("searchPath") or args.get("SearchDirectory") or args.get("searchDirectory")
                         or args.get("DirectoryPath") or args.get("directoryPath") or _target(args) or "")
            if name in {"view_file", "read_file", "read"} and _self._is_background_task_log_target(target):
                _self.emit(
                    "deny",
                    "BACKGROUND_TASK_LOG_POLLING_FORBIDDEN: Never read in-progress background task logs (`.system_generated/tasks/*.log`). "
                    "Yield your turn with ZERO tool calls and wait for the host completion notification.",
                    tool=name,
                    reason_code="BACKGROUND_TASK_LOG_POLLING_FORBIDDEN",
                )
                return
            if name in {"view_file", "read_file", "read"} and _self._is_raw_graph_cache_read_target(target):
                _self.emit(
                    "deny",
                    "RAW_GRAPH_CACHE_READ_BLOCKED: Never read raw machine cache `.agents/cache/project_graph.json` directly with `read_file`/`view_file` (causes massive token bloat). "
                    "Use `python .agents/harness.py graph --find <Symbol>` or native `grep_search` instead.",
                    tool=name,
                    reason_code="RAW_GRAPH_CACHE_READ_BLOCKED",
                )
                return
            if name in {"view_file", "read_file", "read"} and _self._is_large_step_output_paginated_read(target, args):
                _self.emit(
                    "deny",
                    f"LARGE_STEP_OUTPUT_PAGINATION_BLOCKED: Never paginate large tool output dumps (`.system_generated/steps/*/output.txt`) via `read_file` `ByteOffset` (causes 200K+ token cache bloat). "
                    f"Extract Zoho/Jira items in <20ms via `python .agents/harness.py pm find-item --item <I1454|id> --file \"{target}\"` or search specific keys via `grep_search`.",
                    tool=name,
                    reason_code="LARGE_STEP_OUTPUT_PAGINATION_BLOCKED",
                )
                return
            if name in {"view_file", "read_file", "read"} and _self._is_large_build_artifact_paginated_read(target, args):
                _self.emit(
                    "deny",
                    "BUILD_ARTIFACT_PAGINATION_BLOCKED: Never paginate large generated or bytecode dump files inside `build/**` via `ByteOffset` (causes 200K+ token context bloat). "
                    "Inspect third-party library Kotlin/Java sources (`-sources.jar`, auto-fetched even before Android Studio Sync) via "
                    "`python .agents/harness.py dep-inspect <group:artifact[:version]> --query <symbol>`.",
                    tool=name,
                    reason_code="BUILD_ARTIFACT_PAGINATION_BLOCKED",
                )
                return
            if _self._is_native_transcript_read_target(target):
                _self.emit(
                    "deny",
                    "NATIVE_TRANSCRIPT_READ_FORBIDDEN: Never read raw Antigravity `transcript.jsonl` logs into agent context (causes severe token bloat). "
                    "Run `python .agents/harness.py task status`, `python .agents/harness.py task bridge`, or `git diff --stat` instead.",
                    tool=name,
                    reason_code="NATIVE_TRANSCRIPT_READ_FORBIDDEN",
                )
                return
            if _self._installed_engine_target(target, recursive=name in SEARCH_TOOLS | {"list_dir"}):
                _self._deny_engine_read(name)
                return
        if name in WRITE_TOOLS:
            targets = _extract_all_targets(args)
            if name in {"move_file", "rename_file"} and len(targets) < 2:
                _self.emit(
                    "deny",
                    f"{name} must expose both source and destination paths for boundary validation.",
                    tool=name,
                    reason_code="PROTECTED_PATH",
                )
                return
            if not targets:
                targets = [""]
            all_safe = True
            all_temp = True
            first_detail = ""
            resolved_details: list[str] = []
            for t in targets:
                safe, detail, is_temp = _self._safe_target(t)
                if not safe:
                    all_safe = False
                    first_detail = detail
                    break
                resolved_details.append(str(detail).replace("\\", "/").lower())
                if not is_temp:
                    all_temp = False
            if not all_safe:
                _self.emit("deny", first_detail, tool=name, reason_code="PROTECTED_PATH")
                return
            if all_temp:
                if reviewer and any(
                    "/.agents/cache/" in ("/" + d.lstrip("/")) for d in resolved_details
                ):
                    _self.emit(
                        "deny",
                        "Reviewer agents are strictly read-only and may not write temporary contract files under `.agents/cache/`.",
                        tool=name,
                        reason_code="REVIEWER_MUTATION_FORBIDDEN",
                    )
                    return
                if (utility_ctx is not None or reviewer) and any(
                    "/.agents/state/web-relay/inbox/" in ("/" + d.lstrip("/")) for d in resolved_details
                ):
                    _self.emit(
                        "deny",
                        "WORKER_INBOX_WRITE_FORBIDDEN: `.agents/state/web-relay/inbox/` is reserved exclusively for the Lead session when staging incoming Web-Relay payloads.",
                        tool=name,
                        reason_code="WORKER_INBOX_WRITE_FORBIDDEN",
                    )
                    return
                if name in {"edit_file", "replace_file_content", "multi_replace_file_content", "apply_patch", "edit", "multiedit"}:
                    _self._normalize_crlf_for_edit(REPO, targets, args)
                _self.emit("allow", "Temporary setup answers, IDE artifact, or external user document write is allowed.", tool=name, reason_code="TEMP_WRITE_ALLOWED")
                return
            try:
                pending_tid = str(active_plan(REPO).get("task_id") or "")
            except Exception:
                pending_tid = ""
            if _pending_cancel(pending_tid):
                _self.emit("deny", _cancel_pending_message(pending_tid), tool=name, reason_code="CANCEL_PENDING")
                return
            allowed, reason, code = file_mutation_allowed(REPO, targets=targets)
            if allowed and not reviewer:
                w_ok, w_reason, w_code = _self._check_web_mode_direct_write_guard(
                    REPO, targets, conversation=conversation, transcript_hint=transcript_hint,
                )
                if not w_ok:
                    allowed, reason, code = w_ok, w_reason, w_code
            if allowed and name in {"edit_file", "replace_file_content", "multi_replace_file_content", "apply_patch", "edit", "multiedit"}:
                _self._normalize_crlf_for_edit(REPO, targets, args)
            if allowed and conversation and not reviewer and utility_ctx is None:
                try:
                    from delegation_policy import mark_lead_edit_or_transition
                    mark_lead_edit_or_transition(REPO, conversation)
                except (ImportError, OSError, ValueError):
                    pass
            _self.emit("allow" if allowed else "deny", reason, tool=name, reason_code=code)
            return
        lead_conv = conversation if (conversation and not is_side_question and not reviewer and utility_ctx is None) else ""
        if lead_conv and _ACTIVE_HOOK_MODEL_NAME:
            try:
                from delegation_policy import record_live_lead_session_model
                record_live_lead_session_model(REPO, lead_conv, _ACTIVE_HOOK_MODEL_NAME)
            except (ImportError, OSError, ValueError):
                pass
        if name == "run_command":
            command = str(args.get("CommandLine") or args.get("commandLine") or args.get("command") or "")
            _self._handle_command(command, conversation=lead_conv, transcript_hint=transcript_hint)
            return
        if name in SUBAGENT_TOOLS or name.startswith("schedules:"):
            _self._handle_subagent(name, args, parent_conversation_id=conversation)
            return
        if name in SEARCH_TOOLS:
            _self._handle_search(name, args, conversation=lead_conv, is_utility_subagent=(utility_ctx is not None))
            return
        if name == "list_dir":
            _self._handle_list_dir(name, args, conversation=lead_conv, is_utility_subagent=(utility_ctx is not None))
            return
        # Known read-only tools (checked before loading external integration registry)
        if name in ("view_file", "read_file", "read", "read_url_content", "search_web", "read_resource", "list_resources", "ask_question", "generate_image"):
            if name == "search_web" and _self._enforce_search_web_parallel_cap(conversation or lead_conv):
                return
            if name in ("view_file", "read_file", "read"):
                if lead_conv and _self._enforce_lead_anti_reread(lead_conv, name, args):
                    return
                if not is_side_question:
                    _self._flag_out_of_scope_read(name, args)
            _self.emit("allow", "Tool is outside the harness mutation boundary.", tool=name, reason_code="KNOWN_READ_TOOL")
            return
        # External integrations called directly as host tools (e.g. zoho_add_comment)
        integration = _get_registry().resolve("", name)
        if integration is not None:
            if integration.is_read_only(name, args):
                _self.emit("allow", f"Read-only {integration.display_name} inspection is allowed.", tool=name)
                return
            _self._handle_external_mutation(integration, name, args)
            return
        if name in ("call_mcp_tool", "mcp_tool"):
            _self._handle_mcp_tool(name, args)
            return

        mcp_match = (
            re.match(r"^mcp__([a-zA-Z0-9_-]+?)__(.+)$", name)
            or re.match(
                r"^mcp_(zoho_sprints|zoho_projects|github_projects|google_workspace|android_studio|play_console|firebase_crashlytics)_(.+)$",
                name,
                re.I,
            )
            or re.match(
                r"^mcp_([a-zA-Z0-9_-]+?)_((?:get|list|read|view|fetch|find|search|query|inspect|describe|show|lookup|retrieve|answer|"
                r"create|update|edit|write|set|add|comment|rename|copy|upload|patch|post|put|assign|replace|insert|upsert|append|merge|"
                r"import|sync|push|commit|execute|run|invoke|trigger|archive|close|reopen|approve|save|modify|restore|"
                r"delete|remove|drop|destroy|deploy|publish|revoke|disable|rotate|truncate|purge|reset|clear|wipe|"
                r"send|share|unshare|trash|move|transfer)(?:_[a-zA-Z0-9_-]+)?)$",
                name,
                re.I,
            )
            or re.match(r"^mcp_([a-zA-Z0-9-]+)_(.+)$", name)
            or re.match(r"^mcp_([a-zA-Z0-9_-]+?)_([a-zA-Z0-9-]+)$", name)
        )
        if mcp_match:
            _self._handle_mcp_tool(name, {
                "ServerName": mcp_match.group(1),
                "ToolName": mcp_match.group(2),
                "Arguments": args,
            })
            return

        # Capability-based safety for unknown host tools
        from integrations.external_write_policy import sensitive_values as _unknown_tool_secrets
        if _unknown_tool_secrets([args]):
            _self.emit("deny", f"Denied unknown tool '{name}' carrying credential or signing file path.", tool=name, reason_code="SENSITIVE_EXTERNAL_UPLOAD")
            return
        tgt = _target(args)
        hard_mutation_verbs = frozenset({
            "write", "edit", "delete", "remove", "move", "rename", "create",
            "apply", "patch", "execute", "send", "publish", "post",
            "put", "mutate", "destroy", "drop", "grant", "modify",
            "upload", "replace", "insert", "upsert", "append",
            "copy", "sync", "archive", "reset", "clear", "truncate", "purge",
            "share", "unshare", "revoke", "trash", "undelete", "reply", "forward",
            "actuate", "merge", "close", "reopen", "assign", "transition",
            "approve", "reject", "cancel", "invite", "transfer", "deploy",
            "rotate", "wipe", "disable", "label", "unlabel", "unsubscribe",
            "comment", "restore",
        })
        contextual_mutation_verbs = frozenset({"run", "update", "save"})
        read_lead_verbs = frozenset({
            "get", "list", "read", "view", "fetch", "find", "search",
            "check", "inspect", "describe", "status", "show", "query",
        })
        _tc_raw = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
        raw_tool_name = str(
            _tc_raw.get("name") or _tc_raw.get("toolName")
            or payload.get("toolName") or payload.get("tool_name") or payload.get("tool") or name
        ).strip()
        snake_parts = [t for t in re.split(r"[_\-.:/]+", name.lower()) if t]
        camel_parts = [t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", raw_tool_name) if t]
        name_tokens = set(snake_parts) | set(camel_parts)
        lead_token = camel_parts[0] if len(camel_parts) > 1 else (snake_parts[0] if snake_parts else (camel_parts[0] if camel_parts else ""))
        concat_prefix_mut = (
            len(snake_parts) == 1
            and len(camel_parts) <= 1
            and not any(name.startswith(rv) for rv in read_lead_verbs)
            and any(name.startswith(mv) for mv in (hard_mutation_verbs | contextual_mutation_verbs))
        )
        has_mutation_verb = (
            bool(name_tokens & hard_mutation_verbs)
            or (bool(name_tokens & contextual_mutation_verbs) and lead_token not in read_lead_verbs)
            or concat_prefix_mut
        )
        has_mutation_args = bool(tgt and any(k in args for k in ("content", "code", "patch", "replacement", "text", "data")))

        if has_mutation_verb or has_mutation_args:
            _self.emit("deny", f"Denied unknown mutation-like tool '{name}'; not authorized by harness safety boundary.", tool=name, reason_code="UNKNOWN_MUTATION_TOOL")
            return

        _self.emit("allow", "Tool is outside the harness mutation boundary.", tool=name, reason_code="UNKNOWN_TOOL_READ_ASSUMED")
    except json.JSONDecodeError:
        _self.emit("deny", "Safety hook received invalid JSON.")
    except Exception as exc:
        _self.emit("deny", f"Safety hook failed closed ({type(exc).__name__}: {exc}).")



_self = sys.modules[__name__]

_LAZY_SUBMODULE_EXPORTS: dict[str, str] = {
    "_audit_path": "audit_and_pacer",
    "_audit": "audit_and_pacer",
    "_burst_pacer_default_mode": "audit_and_pacer",
    "_model_exempt_from_hydrogen_burst_pacer": "audit_and_pacer",
    "check_and_apply_hydrogen_burst_pacer": "audit_and_pacer",
    "emit": "audit_and_pacer",
    "_enforce_search_web_parallel_cap": "audit_and_pacer",
    "_split_command_tokens": "command_policy",
    "_lifecycle_calls": "command_policy",
    "_developer_authority_violation": "command_policy",
    "_flag": "command_policy",
    "_is_live_interactive_antigravity_lead": "command_policy",
    "_check_web_mode_direct_write_guard": "command_policy",
    "_extract_execution_mode_kickoff": "command_policy",
    "_audited_harness_command": "command_policy",
    "_read_only_git_branch_command": "command_policy",
    "_read_only_adb_command": "command_policy",
    "_handle_command": "command_policy",
    "_normalize_subagent_items": "subagent_guard",
    "_handle_phase_reviewer_dispatch": "subagent_guard",
    "_handle_run_workflow": "subagent_guard",
    "_handle_subagent": "subagent_guard",
    "_canonical_subagent_role": "subagent_guard",
    "_has_unfinalized_active_review_wave": "subagent_guard",
    "_validate_define_subagent": "subagent_guard",
    "validate_external_write": "mcp_guard",
    "_handle_external_mutation": "mcp_guard",
    "_handle_mcp_tool": "mcp_guard",
    "_is_ide_artifact": "path_and_read_guard",
    "_is_external_user_doc": "path_and_read_guard",
    "_safe_target": "path_and_read_guard",
    "_normalize_crlf_for_edit": "path_and_read_guard",
    "check_write_safety": "path_and_read_guard",
    "_is_within_repo": "path_and_read_guard",
    "_get_active_task_scope": "path_and_read_guard",
    "_is_path_in_active_scope": "path_and_read_guard",
    "_enforce_lead_anti_reread": "path_and_read_guard",
    "_handle_list_dir": "path_and_read_guard",
    "_handle_search": "path_and_read_guard",
    "_conversation_started_at": "path_and_read_guard",
    "_flag_out_of_scope_read": "path_and_read_guard",
    "_installed_engine_target": "path_and_read_guard",
    "_is_raw_graph_cache_read_target": "path_and_read_guard",
    "_is_native_transcript_read_target": "path_and_read_guard",
    "_is_background_task_log_target": "path_and_read_guard",
    "_deny_engine_read": "path_and_read_guard",
    "_is_large_step_output_paginated_read": "path_and_read_guard",
    "_is_large_build_artifact_paginated_read": "path_and_read_guard",
}


def __getattr__(name: str):
    submod_name = _LAZY_SUBMODULE_EXPORTS.get(name)
    if submod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    mod = importlib.import_module(f".{submod_name}", __package__ or "_safety")
    for exp_name, owner in _LAZY_SUBMODULE_EXPORTS.items():
        if owner == submod_name and hasattr(mod, exp_name):
            globals().setdefault(exp_name, getattr(mod, exp_name))
    return globals()[name]


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_SUBMODULE_EXPORTS))


if __name__ == "__main__":
    main()
