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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import REPO  # noqa: E402
from mutation_guard import _entry, active_plan, command_allowed, file_mutation_allowed, join_continuations  # noqa: E402
from _vnext_common import active_review_package_path, read_json, sha256_file, validate_id  # noqa: E402


from policy_vocab import (
    ANTIGRAVITY_REVIEWER_TOOLS,
    ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS,
    CORE_ROUTED_REVIEWERS,
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
WRITE_TOOLS = {
    "write_to_file", "replace_file_content", "multi_replace_file_content", "apply_patch", "edit", "multiedit",
    "create_file", "delete_file", "move_file", "rename_file",
}
SUBAGENT_TOOLS = frozenset(SUBAGENT_ORCHESTRATION_TOOLS)
SEARCH_TOOLS = {"grep_search", "find_by_name"}
from integrations.registry import registry  # noqa: E402
from integrations.base import validate_external_write  # noqa: E402
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
    ".agents", "agents/scripts", "agents/state", ".harness-setup/ownership-v1.json",
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
}
DANGEROUS = (
    ("git_mutation", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*g[i\u0131]t(?:\.exe)?(?:\s+-c\s+\S+)*\s+(?:add|am|apply|branch|checkout|clean|commit|config|fetch|gc|merge|mv|prune|pull|push|rebase|remote\s+(?:add|remove|set-url)|reset|restore|rm|stash|switch|tag|update-index|worktree)\b", re.I)),
    ("shell_indirection", re.compile(r"\b(?:base64\s+(?:-d|--decode)|frombase64string|invoke-expression|iex|eval)\b", re.I)),
    ("adb_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:root|remount|backup|restore|disable-verity|enable-verity|uninstall|clear)\b", re.I | re.S)),
    ("package_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:pm|cmd\s+package)\s+(?:clear|uninstall|disable|suspend|install-existing)\b", re.I | re.S)),
    ("raw_adb", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*adb(?:\.exe)?\b", re.I)),
    ("harness_device_emergency", re.compile(r"run_device\.py\b(?:(?=.*\s--force\b)|(?=.*\s--grant-runtime-permissions\b)|\s+uninstall\b)", re.I)),
    ("tracker_write", re.compile(r"(?:\b(?:zoho|jira|linear)\b.*\b(?:create|update|delete|close|transition|done|solved)\b|\b(?:create|update|delete|close|transition|done|solved)[_\s-]*(?:zoho|jira|linear)\b)", re.I | re.S)),
    ("draft_force", re.compile(r"(?:workflow\.py\b.*\bdraft\b.*--force\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task\b.*\bdraft\b.*--force\b)", re.I)),
    ("review_override_provenance", re.compile(r"record_review\.py\b.*--override-reviews\b.*--source\s+developer_terminal\b", re.I)),
    ("review_complete_text_bypass", re.compile(r"(?:review_orchestrator(?:\.py)?|harness(?:\.py)?\s+review)\b.*\bcomplete\b.*--text\b", re.I)),
    ("signoff_authority", re.compile(r"run_device(?:\.py)?\b.*\bsignoff\b", re.I)),
    ("dirty_tree_delivery_override", re.compile(r"(?:workflow(?:\.py)?\b.*\bdeliver\b.*--(?:allow-dirty-tree|developer-allow-dirty-tree)\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task\b.*\bdeliver\b.*--(?:allow-dirty-tree|developer-allow-dirty-tree)\b)", re.I)),
)
WORKFLOW_ENTRYPOINTS = {"workflow.py", "workflow"}
TASK_ENTRYPOINTS = {"harness.py", "harness", "harness_cli.py", "harness_cli", "android-harness"}
WORKFLOW_VALUE_FLAGS = {"--repo", "--task-id"}


def _developer_authority_violation(command: str) -> bool:
    """Cancel, and approval from any source other than the conversation, belong to the developer.

    Decided from the actual lifecycle subcommand and its --source value, never from
    free text such as an outcome ("Fix cancel button") or an approval quote.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    for index, token in enumerate(tokens):
        name = token.strip(";&|").replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name in WORKFLOW_ENTRYPOINTS:
            rest = tokens[index + 1:]
        elif name in TASK_ENTRYPOINTS and index + 1 < len(tokens) and tokens[index + 1].lower() == "task":
            rest = tokens[index + 2:]
        else:
            continue
        subcommand, skip_value = "", False
        for part in rest:
            if skip_value:
                skip_value = False
                continue
            if part.startswith("-"):
                skip_value = part.lower() in WORKFLOW_VALUE_FLAGS
                continue
            subcommand = part.strip(";&|").lower()
            break
        if "-h" in rest or "--help" in rest:
            continue  # reading usage changes nothing
        if subcommand == "cancel":
            return True
        if subcommand in ("approve", "approve-sensitive"):
            source = ""
            for pos, part in enumerate(rest):
                if part.startswith("--source="):
                    source = part.split("=", 1)[1]
                elif part == "--source" and pos + 1 < len(rest):
                    source = rest[pos + 1]
            if source.strip(";&|").lower() != "conversation":
                return True
    return False


RAW_GRADLE = re.compile(r"(?:^|[;&|\n]\s*)(?:\.\/?|[^\s]+[/\\])?(?:gradlew|gradle)(?:\.bat)?\s+", re.I)
ALLOWED_GRADLE_WRAPPER = re.compile(r"(?:run_gradle_task|run_tests_gate)\.py\b", re.I)
IMMUTABLE_ADAPTER_FILES = frozenset({
    "agents.md", "gemini.md", "claude.md", "copilot-instructions.md",
    ".cursorrules", ".windsurfrules", "continue-android-harness.md",
    "codex.md", "qwen.md", "github-instructions.md",
})


def _audit_path() -> Path:
    override = os.environ.get("HARNESS_HOOK_STATE")
    base = Path(override) if override else Path(__file__).resolve().parent.parent / "state" / "hook-state.json"
    return base.with_name("audit_log.jsonl")


def _audit(
    decision: str,
    reason: str,
    tool: str,
    command: str,
    *,
    reason_code: str = "",
    conv_hint: str = "",
    task_id: str = "",
    mcp_fingerprint: str = "",
) -> None:
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import time
        cmd_hash = hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest()[:12] if command else ""
        code = reason_code or ("DENIED" if decision == "deny" else "ALLOWED")
        record = {
            "schema_version": 1,
            "ts": time.time(),
            "decision": decision,
            "tool": tool[:80],
            "reason_code": code,
            "reason_short": reason[:160],
            "reason": reason[:160],
            "cmd_sha256_12": cmd_hash,
            "command_sha256_12": cmd_hash,
            "conv_hint": conv_hint,
        }
        if task_id:
            record["task_id"] = task_id
        if mcp_fingerprint:
            record["mcp_fingerprint"] = mcp_fingerprint
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > AUDIT_MAX_RECORDS:
            fd, temp_name = tempfile.mkstemp(prefix=".audit-", suffix=".tmp", dir=str(path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines[-AUDIT_MAX_RECORDS:]) + "\n")
            os.replace(temp_name, path)
    except Exception:
        pass


def emit(
    decision: str,
    reason: str,
    *,
    tool: str = "",
    command: str = "",
    reason_code: str = "",
    conv_hint: str = "",
    task_id: str = "",
    mcp_fingerprint: str = "",
) -> None:
    _audit(decision, reason, tool, command, reason_code=reason_code, conv_hint=conv_hint, task_id=task_id, mcp_fingerprint=mcp_fingerprint)
    # Antigravity decodes hook stdout with protojson and rejects unknown fields, so the
    # result carries only its schema; reason codes and fingerprints live in the audit log.
    print(json.dumps({"decision": decision, "reason": reason}, ensure_ascii=False))


def _tool_name_and_args(payload: dict) -> tuple[str, dict]:
    call = payload.get("toolCall") or payload.get("tool_call") or {}
    name = str(call.get("name") or payload.get("toolName") or payload.get("tool_name") or "").lower()
    args = call.get("args") or payload.get("toolArgs") or payload.get("tool_input") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return name, args if isinstance(args, dict) else {}


def _target(args: dict) -> str:
    for key in ("TargetFile", "targetFile", "path", "file_path", "filePath"):
        if args.get(key):
            return str(args[key]).replace("\\", "/")
    return ""


def _extract_all_targets(args: dict) -> list[str]:
    targets = []
    single = _target(args)
    if single:
        targets.append(single)
    for key in ("files", "Files", "paths", "Paths", "targets", "Targets", "edits", "Edits"):
        val = args.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    targets.append(item.replace("\\", "/"))
                elif isinstance(item, dict):
                    t = _target(item)
                    if t:
                        targets.append(t)
    return list(dict.fromkeys(targets))


def _is_ide_artifact(resolved: Path) -> bool:
    try:
        from antigravity_runtime import is_trusted_antigravity_path
        return is_trusted_antigravity_path(resolved)
    except Exception:
        return False


def _safe_target(raw_target: str, repo: Path | None = None) -> tuple[bool, str, bool]:
    root = (repo or REPO).resolve()
    if not raw_target.strip():
        return False, "Mutating file tool did not expose a target path; refusing an unscoped write.", False
    raw = Path(raw_target).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    user_harness = (Path.home() / ".android-harness").resolve()
    if resolved == user_harness or user_harness in resolved.parents:
        return False, "User-level Android Harness configuration and model routes are developer-owned and immutable to model file tools.", False
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError:
        temp_dir = Path(tempfile.gettempdir()).resolve()
        if (resolved == temp_dir or temp_dir in resolved.parents) and resolved.suffix.lower() == ".json":
            return True, str(resolved), True
        if _is_ide_artifact(resolved):
            return True, str(resolved), True
        return False, f"Target path '{raw_target}' is outside the repository boundary.", False
    if (
        relative == ".agents/project-context/project-notes.md"
        or relative == ".agents/project-context/developer-instructions.json"
        or relative == ".agents/project-context/architecture-policy.json"
        or relative.startswith(".agents/project-context/legacy-overrides/")
    ):
        return False, "Project context notes, instructions, and architecture policies are developer-owned and immutable to model file tools to prevent context poisoning.", False
    if any(relative == r or relative.startswith(r + "/") for r in PROTECTED_ROOTS):
        return False, "Harness engine, state, and ownership evidence are immutable to agent file tools.", False
    is_kit_dev = (root / "harness_cli.py").is_file() and (root / "scripts_dev").is_dir()
    if not is_kit_dev:
        rel_lower = relative.lower()
        rel_name = Path(relative).name.lower()
        if (
            rel_name in IMMUTABLE_ADAPTER_FILES
            or rel_lower.startswith(".github/workflows/")
            or rel_name in {"gradlew", "gradlew.bat"}
            or rel_lower.startswith("gradle/wrapper/")
        ):
            return False, "Root harness instructions, agent adapters, CI workflows, and Gradle wrappers are developer-owned and immutable during task execution.", False
    if EPHEMERAL_GENERATED_RE.search(relative):
        return False, f"Cannot mutate generated build output '{relative}'. Generated code is diagnostic evidence only; edit the source entity/DAO/contract or generator configuration instead.", False
    return True, relative, False


def check_write_safety(repo: Path | str, target: str, tool_name: str = "write_to_file") -> dict[str, Any]:
    safe, detail, is_temp = _safe_target(str(target), repo=Path(repo))
    if not safe:
        return {"decision": "DENY", "reason": detail, "reason_code": "PROTECTED_PATH"}
    return {"decision": "ALLOW", "reason": detail, "reason_code": "TEMP_WRITE_ALLOWED" if is_temp else "PATH_ALLOWED"}


def _handle_stop() -> None:
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
    except Exception:
        emit("allow", "No active vNext task requires a delivery stop.", tool="stop", reason_code="STOP_IDLE")
        return
    emit("allow", f"Turn completion permitted for task in status {status or 'unknown'}.", tool="stop", reason_code="STOP_ALLOWED")


def _handle_command(command: str) -> None:
    # A backslash-newline continuation is one command; join it so pattern checks see the whole line.
    command = join_continuations(command)
    active_tid = ""
    try:
        p = active_plan(REPO)
        active_tid = str(p.get("task_id") or "")
    except Exception:
        pass
    if _developer_authority_violation(command):
        emit("deny", "Denied by local safety boundary: developer_authority.", tool="run_command", command=command, reason_code="DEVELOPER_AUTHORITY", task_id=active_tid)
        return
    for code, pattern in DANGEROUS:
        if pattern.search(command):
            hint = f" {DENY_HINTS[code]}" if code in DENY_HINTS else ""
            emit("deny", f"Denied by local safety boundary: {code}.{hint}", tool="run_command", command=command, reason_code=code.upper(), task_id=active_tid)
            return
    if RAW_GRADLE.search(command) and not ALLOWED_GRADLE_WRAPPER.search(command):
        emit("deny", "Raw Gradle execution is blocked; use the harness Gradle/test gate.", tool="run_command", command=command, reason_code="RAW_GRADLE", task_id=active_tid)
        return
    # Bridges for other hosts set HARNESS_HOOK_HOST; Antigravity calls the engine directly.
    hook_host = os.environ.get("HARNESS_HOOK_HOST", "").strip().lower() or "antigravity"
    if hook_host == "antigravity":
        required_host_message = "Antigravity verification must be prepared with --host antigravity\nso trusted Review Protocol V2 can be used."
    else:
        required_host_message = f"Verification in this host must be prepared with --host {hook_host};\nit must not claim another host's review protocol."
    if (
        re.search(r"(?:workflow(?:\.py)?\s+prepare-verification|harness(?:\.py)?\s+task\s+prepare-verification)\b", command, re.I)
        and not re.search(rf"--host\s+{re.escape(hook_host)}(?![\w-])", command, re.I)
    ):
        emit(
            "deny",
            f"REVIEW_HOST_REQUIRED:\n{required_host_message}",
            tool="run_command",
            command=command,
            reason_code="REVIEW_HOST_REQUIRED",
            task_id=active_tid,
        )
        return
    allowed, reason = command_allowed(REPO, command)
    if allowed and re.search(r"project_graph(?:\.py)?\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+graph\b", command, re.I):
        reason = f"project_graph executed: {reason}"
    elif allowed and re.search(r"task_context(?:\.py)?\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task-context\b", command, re.I):
        # This is a pre-tool hook, so validate the target independently before
        # recording it as a discovery anchor. Merely invoking a missing or
        # invalid target must not unlock broad repository search.
        try:
            entry, command_args = _entry(command, REPO)
            if entry in {"harness_cli", "android-harness"} and command_args[:1] == ["task-context"]:
                command_args = command_args[1:]

            def option(name: str) -> str | None:
                return command_args[command_args.index(name) + 1] if name in command_args and command_args.index(name) + 1 < len(command_args) else None

            from task_context import resolve_task_context
            probe = resolve_task_context(
                REPO,
                file=option("--file"),
                symbol=option("--symbol"),
                module=option("--module"),
                source_set=option("--source-set"),
                limit=1,
            )
            if probe.get("status") in {"RESOLVED", "AMBIGUOUS"}:
                reason = f"targeted task_context executed: {reason}"
        except Exception:
            pass
    emit("allow" if allowed else "deny", reason, tool="run_command", command=command, reason_code="HARNESS_COMMAND" if allowed else "COMMAND_MUTATION_GUARD", task_id=active_tid)

def _handle_phase_reviewer_dispatch(act: dict[str, Any], plan: dict[str, Any], args: dict, tool_name: str) -> None:
    raw_subs = args.get("Subagents") or args.get("subagents") or []
    if not isinstance(raw_subs, list) or not raw_subs:
        emit("deny", "No reviewers specified in Subagents array.", tool=tool_name, reason_code="REVIEWER_ROSTER_EMPTY")
        return

    dispatchable = list(act.get("reviewers") or [])
    phase_id = str(act.get("phase_id") or act.get("inputs", {}).get("phase_id") or "")
    if not phase_id:
        try:
            state_dir = REPO / ".agents/state" if (REPO / ".agents").is_dir() else REPO / "agents/state"
            ps_file = state_dir / "tasks" / str(plan.get("task_id") or "") / "phase-state.json"
            if ps_file.is_file():
                phase_id = str(read_json(ps_file).get("current_phase_id") or "")
        except Exception:
            pass
    briefs = dict(act.get("briefs") or {})

    from phase_review import check_phase_safety_cap
    cap_ok, cap_msg = check_phase_safety_cap(plan, len(dispatchable))
    if not cap_ok:
        emit("deny", cap_msg, tool=tool_name, reason_code="REVIEWER_CALL_SAFETY_CAP_REACHED")
        return

    allowed_keys_set = set(ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS)
    actual = []
    for item in raw_subs:
        if not isinstance(item, dict):
            emit("deny", "Each entry in Subagents array must be an object.", tool=tool_name, reason_code="SUBAGENT_NOT_OBJECT")
            return

        if "model" in item or "Model" in item:
            emit(
                "deny",
                (
                    "REVIEWER_MODEL_OVERRIDE_FORBIDDEN: Do not send 'model' or 'Model' "
                    "in reviewer invocation. Reviewer model inheritance is achieved by omission."
                ),
                tool=tool_name,
                reason_code="REVIEWER_MODEL_OVERRIDE_FORBIDDEN",
            )
            return

        supplied_reasoning_keys = [k for k in item if k in COMMON_REASONING_KEYS]
        if supplied_reasoning_keys:
            emit(
                "deny",
                "This host does not expose trusted per-subagent reasoning control. Omit reasoning override and inherit the parent setting.",
                tool=tool_name,
                reason_code="UNSUPPORTED_REASONING_KEY",
            )
            return

        for k in item:
            if k not in allowed_keys_set:
                emit(
                    "deny",
                    f"Unexpected key '{k}' in subagent invocation. Allowed keys: {sorted(allowed_keys_set)}.",
                    tool=tool_name,
                    reason_code="UNEXPECTED_SUBAGENT_KEY",
                )
                return

        if "Role" not in item:
            emit("deny", "Subagent entry missing mandatory Role.", tool=tool_name, reason_code="MISSING_SUBAGENT_ROLE")
            return
        r_role = str(item["Role"]).strip()
        if not r_role:
            emit("deny", "Subagent entry Role is empty.", tool=tool_name, reason_code="MISSING_SUBAGENT_ROLE")
            return

        if "TypeName" not in item:
            emit("deny", "Subagent entry missing mandatory TypeName.", tool=tool_name, reason_code="MISSING_SUBAGENT_TYPENAME")
            return
        r_type = str(item["TypeName"]).strip()
        if not r_type:
            emit("deny", "Subagent entry TypeName is empty.", tool=tool_name, reason_code="MISSING_SUBAGENT_TYPENAME")
            return

        if r_type != r_role:
            emit(
                "deny",
                f"Reviewer invocation mismatch: TypeName '{r_type}' does not match Role '{r_role}'. Both must refer to the same reviewer.",
                tool=tool_name,
                reason_code="REVIEWER_ROLE_MISMATCH",
            )
            return

        if r_role not in dispatchable:
            emit(
                "deny",
                f"Reviewer '{r_role}' is not in dispatchable reviewers: {sorted(dispatchable)}.",
                tool=tool_name,
                reason_code="REVIEWER_ROSTER_EXTRA",
            )
            return

        if r_role in actual:
            emit("deny", f"Reviewer batch contains duplicate reviewer: '{r_role}'.", tool=tool_name, reason_code="DUPLICATE_REVIEWER")
            return
        actual.append(r_role)

        if "Prompt" not in item:
            emit("deny", "Subagent entry missing mandatory Prompt.", tool=tool_name, reason_code="MISSING_SUBAGENT_PROMPT")
            return
        supplied_prompt = str(item["Prompt"]).replace("\r\n", "\n").strip()
        if not supplied_prompt:
            emit("deny", "Subagent entry Prompt is empty.", tool=tool_name, reason_code="MISSING_SUBAGENT_PROMPT")
            return

        brief_val = briefs.get(r_role)
        if brief_val and Path(str(brief_val)).is_file():
            expected_prompt = Path(str(brief_val)).read_text(encoding="utf-8").replace("\r\n", "\n").strip()
        elif isinstance(brief_val, str) and brief_val.strip():
            expected_prompt = brief_val.replace("\r\n", "\n").strip()
        else:
            emit("deny", f"Reviewer brief missing or unreadable for '{r_role}'.", tool=tool_name, reason_code="REVIEW_PROFILE_BLOCKED")
            return

        if supplied_prompt != expected_prompt:
            emit(
                "deny",
                f"Reviewer prompt for '{r_role}' does not match the generated reviewer brief.",
                tool=tool_name,
                reason_code="REVIEWER_PROMPT_MISMATCH",
            )
            return

    actual_set = set(actual)
    disp_set = set(dispatchable)
    if actual_set != disp_set:
        missing = disp_set - actual_set
        extra = actual_set - disp_set
        if missing:
            emit(
                "deny",
                f"Reviewer batch incomplete: expected {len(disp_set)} reviewers ({sorted(disp_set)}), got {len(actual_set)} ({sorted(actual_set)}). All dispatchable reviewers must be launched in a single invoke_subagent call.",
                tool=tool_name,
                reason_code="REVIEWER_ROSTER_INCOMPLETE",
            )
            return
        if extra:
            emit(
                "deny",
                f"Reviewer batch contains extra reviewers: expected {sorted(disp_set)}, got {sorted(actual_set)}.",
                tool=tool_name,
                reason_code="REVIEWER_ROSTER_EXTRA",
            )
            return

    try:
        from phase_review import record_phase_dispatch_batch
        record_phase_dispatch_batch(
            REPO,
            str(plan.get("task_id") or ""),
            phase_id,
            sorted(actual),
            host="antigravity",
        )
    except Exception as exc:
        emit(
            "deny",
            f"[PHASE_REVIEW_RECEIPT_WRITE_FAILED] Failed creating phase reviewer dispatch receipt ({type(exc).__name__}): {exc}",
            tool=tool_name,
            reason_code="PHASE_REVIEW_RECEIPT_WRITE_FAILED",
        )
        return

    emit("allow", "Phase reviewer roster exactly matches the approved phase review plan.", tool=tool_name, reason_code="DISPATCH_PHASE_REVIEWERS_ALLOWED")


def _handle_subagent(name: str, args: dict) -> None:
    # Zero-polling invariant: block busy-waiting loops
    if name == "manage_task":
        act = str(args.get("Action") or args.get("action") or "").strip().lower()
        if act == "status":
            emit("deny", "ZERO-POLLING INVARIANT: manage_task(Action='status') is blocked to prevent polling loops. Background tasks notify you reactively upon completion. Yield execution now without calling tools.", tool=name)
            return
    elif name == "manage_subagents":
        act = str(args.get("Action") or args.get("action") or "").strip().lower()
        if act == "list":
            emit("deny", "ZERO-POLLING INVARIANT: manage_subagents(Action='list') is blocked to prevent polling loops. Subagents notify you reactively upon completion. Yield execution now without calling tools.", tool=name)
            return
    elif name == "schedule":
        cond = str(args.get("TimerCondition") or args.get("timerCondition") or "").strip().lower()
        dur = args.get("DurationSeconds") or args.get("durationSeconds")
        if cond in ("any",) or (dur is not None and int(dur) < 180):
            emit("deny", "ZERO-POLLING INVARIANT: Short schedule timers and condition-based busy-waiting are blocked. Yield execution and await reactive wakeup notifications from the system.", tool=name)
            return

    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
        if status == "IMPLEMENTING":
            task_id = str(plan.get("task_id") or "")
            if not task_id:
                state_dir = REPO / ".agents/state" if (REPO / ".agents").is_dir() else REPO / "agents/state"
                active_f = state_dir / "active-task.json"
                if active_f.is_file():
                    task_id = str(read_json(active_f).get("task_id") or "")
            from workflow import resolve_next_action
            act = resolve_next_action(REPO, task_id, plan)
            act_code = act.get("code")

            if act_code == "RETRY_PHASE_REVIEW_PROTOCOL":
                if name != "send_message":
                    emit(
                        "deny",
                        f"send_message is required to retry phase review protocol (got tool '{name}').",
                        tool=name,
                        reason_code="RETRY_PHASE_REVIEW_PROTOCOL_REQUIRED",
                    )
                    return
                expected_recipient = str(act.get("recipient") or "").strip()
                expected_msg = str(act.get("message") or "").strip()
                supplied_recipient = str(args.get("Recipient") or args.get("recipient") or "").strip()
                supplied_msg = str(args.get("Message") or args.get("message") or "").strip()
                if not supplied_recipient or supplied_recipient != expected_recipient:
                    emit(
                        "deny",
                        f"send_message recipient mismatch: expected '{expected_recipient}', got '{supplied_recipient}'.",
                        tool=name,
                        reason_code="RETRY_RECIPIENT_MISMATCH",
                    )
                    return
                if not supplied_msg or supplied_msg.replace("\r\n", "\n").strip() != expected_msg.replace("\r\n", "\n").strip():
                    emit(
                        "deny",
                        "send_message message does not match the required protocol retry prompt.",
                        tool=name,
                        reason_code="RETRY_MESSAGE_MISMATCH",
                    )
                    return
                emit("allow", "Protocol retry send_message matches router requirements.", tool=name, reason_code="RETRY_PHASE_REVIEW_PROTOCOL_ALLOWED")
                return

            if act_code == "DISPATCH_PHASE_REVIEWERS":
                if name != "invoke_subagent":
                    emit(
                        "deny",
                        f"invoke_subagent is required to dispatch phase reviewers (got tool '{name}').",
                        tool=name,
                        reason_code="DISPATCH_PHASE_REVIEWERS_REQUIRED",
                    )
                    return
                _handle_phase_reviewer_dispatch(act, plan, args, name)
                return

            raw_subs = args.get("Subagents") or args.get("subagents") or []
            if isinstance(raw_subs, list) and len(raw_subs) > 5:
                emit("deny", f"Subagent batch size {len(raw_subs)} exceeds the safety limit of 5.", tool=name)
                return
            emit("allow", "On-demand specialist action is inside the approved implementation.", tool=name)
            return
        if status != "VERIFYING":
            emit("deny", f"Subagent action is unavailable while task status is {status or 'missing'}.", tool=name)
            return
        if name == "send_message":
            state = REPO / ".agents/state" if (REPO / ".agents").is_dir() else REPO / "agents/state"
            active = read_json(state / "active-task.json")
            from workflow import resolve_next_action
            act = resolve_next_action(REPO, str(active["task_id"]), plan)
            if act.get("code") != "RETRY_REVIEW_PROTOCOL":
                emit(
                    "deny",
                    f"send_message is not permitted during VERIFYING unless retrying review protocol (current router action: {act.get('code')}).",
                    tool=name,
                    reason_code="REVIEW_VERIFY_SEND_MESSAGE_FORBIDDEN",
                )
                return
            expected_recipient = str(act.get("recipient") or "").strip()
            expected_msg = str(act.get("message") or "").strip()
            supplied_recipient = str(args.get("Recipient") or args.get("recipient") or "").strip()
            supplied_msg = str(args.get("Message") or args.get("message") or "").strip()
            if not supplied_recipient or supplied_recipient != expected_recipient:
                emit(
                    "deny",
                    f"send_message recipient mismatch: expected '{expected_recipient}', got '{supplied_recipient}'.",
                    tool=name,
                    reason_code="RETRY_RECIPIENT_MISMATCH",
                )
                return
            if not supplied_msg or supplied_msg.replace("\r\n", "\n").strip() != expected_msg.replace("\r\n", "\n").strip():
                emit(
                    "deny",
                    "send_message message does not match the required protocol retry prompt.",
                    tool=name,
                    reason_code="RETRY_MESSAGE_MISMATCH",
                )
                return
            emit("allow", "Protocol retry send_message matches router requirements.", tool=name, reason_code="RETRY_REVIEW_PROTOCOL_ALLOWED")
            return

        if name != "invoke_subagent":
            emit("allow", "Reviewer management is allowed during verification.", tool=name)
            return

        try:
            state = REPO / ".agents/state" if (REPO / ".agents").is_dir() else REPO / "agents/state"
            active = read_json(state / "active-task.json")
            current = read_json(state / "tasks" / str(active["task_id"]) / "current-run.json")
            protocol = int(current.get("review_protocol_version") or 1)
            policy = read_json(Path(current["policy"]))
        except Exception:
            emit("deny", "Review execution profile resolution failed.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
            return
        required_reviewers = list(policy.get("reviewers") or [])

        # Determine dispatchable reviewers
        if protocol >= 2:
            from review_orchestrator import load_ledger, dispatchable_reviewers, ledger_file
            directory = state / "tasks" / str(active["task_id"])
            run_id_val = str(current.get("run_id") or "")
            l_path = ledger_file(directory, run_id_val)
            if l_path.is_file():
                ledger = load_ledger(directory, run_id_val)
                dispatchable = dispatchable_reviewers(ledger, required_reviewers)
            else:
                dispatchable = list(required_reviewers)
        else:
            dispatchable = list(required_reviewers)

        reviewer_routes = {}
        if protocol >= 2:
            try:
                from review_execution import resolve_execution_profile
                review_host = str(current.get("review_host") or "").strip().lower()
                profile = resolve_execution_profile(REPO, str(active["task_id"]), host=review_host)
                if not isinstance(profile, dict) or not profile.get("reviewers"):
                    emit("deny", "Review execution profile is empty or invalid.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                    return
                reviewer_routes = profile.get("reviewers", {})
            except Exception:
                emit("deny", "Review execution profile resolution failed.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                return

            for r in dispatchable:
                r_info = reviewer_routes.get(r)
                if not r_info:
                    emit("deny", f"Reviewer '{r}' missing from execution profile.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                    return
                brief_p = Path(r_info.get("brief_path") or "")
                if not brief_p.is_file() or brief_p.stat().st_size == 0:
                    emit("deny", f"Reviewer brief missing or empty for '{r}'.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                    return
                brief_content = str(r_info.get("brief_content") or "").replace("\r\n", "\n").strip()
                if not brief_content:
                    emit("deny", f"Reviewer brief unreadable or empty for '{r}'.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                    return
        else:
            try:
                from review_execution import resolve_execution_profile
                review_host = str(current.get("review_host") or "").strip().lower()
                profile = resolve_execution_profile(REPO, str(active["task_id"]), host=review_host)
                reviewer_routes = profile.get("reviewers", {}) if isinstance(profile, dict) else {}
            except Exception:
                reviewer_routes = {}

        raw_subs = args.get("Subagents") or args.get("subagents") or []
        if not isinstance(raw_subs, list) or not raw_subs:
            emit("deny", "No reviewers specified in Subagents array.", tool=name, reason_code="REVIEWER_ROSTER_EMPTY")
            return

        # Check safety cap / round cap
        if int(plan.get("review_rounds") or 0) >= int(policy.get("max_review_rounds") or 3):
            emit("deny", "Review round cap reached; developer decision is required.", tool=name)
            return
        used_calls = int(plan.get("review_calls_used") or 0)
        safety_cap = int(policy.get("model_call_budget") or 20)
        if used_calls + len(dispatchable) > safety_cap:
            emit(
                "deny",
                "Reviewer Call Safety Cap reached; developer decision is required.",
                tool=name,
                reason_code="REVIEWER_CALL_SAFETY_CAP_REACHED",
            )
            return

        allowed_keys_set = set(ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS)
        actual = []
        for item in raw_subs:
            if not isinstance(item, dict):
                emit("deny", "Each entry in Subagents array must be an object.", tool=name, reason_code="SUBAGENT_NOT_OBJECT")
                return

            # Check model/Model key rejection: ANY model key must be denied
            if "model" in item or "Model" in item:
                emit(
                    "deny",
                    (
                        "REVIEWER_MODEL_OVERRIDE_FORBIDDEN: Do not send 'model' or 'Model' "
                        "in reviewer invocation. Reviewer model inheritance is achieved by omission."
                    ),
                    tool=name,
                    reason_code="REVIEWER_MODEL_OVERRIDE_FORBIDDEN",
                )
                return

            if protocol >= 2:
                if "Role" not in item:
                    emit("deny", "Subagent entry missing mandatory Role.", tool=name, reason_code="MISSING_SUBAGENT_ROLE")
                    return
                r_role = str(item["Role"]).strip()
                if not r_role:
                    emit("deny", "Subagent entry Role is empty.", tool=name, reason_code="MISSING_SUBAGENT_ROLE")
                    return

                if "TypeName" not in item:
                    emit("deny", "Subagent entry missing mandatory TypeName.", tool=name, reason_code="MISSING_SUBAGENT_TYPENAME")
                    return
                r_type = str(item["TypeName"]).strip()
                if not r_type:
                    emit("deny", "Subagent entry TypeName is empty.", tool=name, reason_code="MISSING_SUBAGENT_TYPENAME")
                    return

                if r_type != r_role:
                    emit(
                        "deny",
                        f"Reviewer invocation mismatch: TypeName '{r_type}' does not match Role '{r_role}'. Both must refer to the same reviewer.",
                        tool=name,
                        reason_code="REVIEWER_ROLE_MISMATCH",
                    )
                    return

                matched = r_role
                if matched not in dispatchable:
                    emit(
                        "deny",
                        f"Reviewer '{matched}' is not in dispatchable reviewers: {sorted(dispatchable)}.",
                        tool=name,
                        reason_code="REVIEWER_ROSTER_EXTRA",
                    )
                    return
            else:
                r_role = str(item.get("Role") or item.get("role") or "").strip()
                r_type = str(item.get("TypeName") or item.get("typeName") or item.get("name") or "").strip()
                if not r_type and not r_role:
                    emit("deny", "Subagent entry missing TypeName/Role.", tool=name, reason_code="MISSING_SUBAGENT_ROLE")
                    return
                matched = r_type if r_type in dispatchable else (r_role if r_role in dispatchable else None)
                if not matched:
                    all_exp = set(required_reviewers)
                    matched = r_type if r_type in all_exp else (r_role if r_role in all_exp else (r_type or r_role))

            rev_info = reviewer_routes.get(matched, {})
            rev_reasoning = rev_info.get("reasoning", {}) if isinstance(rev_info, dict) else {}
            control = rev_reasoning.get("control")
            native_val = rev_reasoning.get("native_value")
            arg_name = rev_reasoning.get("argument_name")

            item_allowed_keys = set(allowed_keys_set)
            if control == "SUPPORTED" and arg_name:
                item_allowed_keys.add(arg_name)

            supplied_reasoning_keys = [k for k in item if k in COMMON_REASONING_KEYS]
            if control != "SUPPORTED":
                if supplied_reasoning_keys:
                    emit(
                        "deny",
                        (
                            "This host does not expose trusted per-subagent reasoning control. "
                            "Omit reasoning override and inherit the parent setting."
                        ),
                        tool=name,
                    )
                    return
            else:
                if native_val is not None:
                    if arg_name not in item or str(item[arg_name]) != str(native_val):
                        emit(
                            "deny",
                            f"Reviewer reasoning override for '{matched}' must use '{arg_name}={native_val}'.",
                            tool=name,
                        )
                        return
                    other_keys = [k for k in supplied_reasoning_keys if k != arg_name]
                    if other_keys:
                        emit(
                            "deny",
                            f"Unexpected reasoning key '{other_keys[0]}' for '{matched}'. Expected '{arg_name}'.",
                            tool=name,
                        )
                        return
                else:
                    if supplied_reasoning_keys:
                        emit(
                            "deny",
                            (
                                "This host does not expose trusted per-subagent reasoning control. "
                                "Omit reasoning override and inherit the parent setting."
                            ),
                            tool=name,
                        )
                        return

            for k in item:
                if k not in item_allowed_keys:
                    emit(
                        "deny",
                        f"Unexpected key '{k}' in subagent invocation. Allowed keys: {sorted(item_allowed_keys)}.",
                        tool=name,
                        reason_code="UNEXPECTED_SUBAGENT_KEY",
                    )
                    return

            if matched in actual:
                emit("deny", f"Reviewer batch contains duplicate reviewer: '{matched}'.", tool=name, reason_code="DUPLICATE_REVIEWER")
                return
            actual.append(matched)

            if protocol >= 2:
                if "Prompt" not in item:
                    emit("deny", "Subagent entry missing mandatory Prompt.", tool=name, reason_code="MISSING_SUBAGENT_PROMPT")
                    return
                supplied_prompt = str(item["Prompt"]).replace("\r\n", "\n").strip()
                if not supplied_prompt:
                    emit("deny", "Subagent entry Prompt is empty.", tool=name, reason_code="MISSING_SUBAGENT_PROMPT")
                    return
                expected_prompt = str(reviewer_routes[matched].get("brief_content") or "").replace("\r\n", "\n").strip()
                if supplied_prompt != expected_prompt:
                    emit(
                        "deny",
                        f"Reviewer prompt for '{matched}' does not match the generated reviewer brief.",
                        tool=name,
                        reason_code="REVIEWER_PROMPT_MISMATCH",
                    )
                    return

        # Exact batch check
        actual_set = set(actual)
        dispatchable_set = set(dispatchable)
        if actual_set != dispatchable_set:
            missing = dispatchable_set - actual_set
            extra = actual_set - dispatchable_set
            if missing:
                emit(
                    "deny",
                    f"Reviewer batch incomplete: expected {len(dispatchable_set)} reviewers ({sorted(dispatchable_set)}), got {len(actual_set)} ({sorted(actual_set)}). All dispatchable reviewers must be launched in a single invoke_subagent call.",
                    tool=name,
                    reason_code="REVIEWER_ROSTER_INCOMPLETE",
                )
                return
            if extra:
                emit(
                    "deny",
                    f"Reviewer batch contains extra reviewers: expected {sorted(dispatchable_set)}, got {sorted(actual_set)}.",
                    tool=name,
                    reason_code="REVIEWER_ROSTER_EXTRA",
                )
                return

        # Persist reviewer dispatch receipts for provable independent execution
        try:
            task_id = str(active.get("task_id") or "")
            if not task_id:
                raise RuntimeError("active task_id is missing")
            run_id = validate_id(str(current.get("run_id") or ""), "run_id")
            manifest_p = str(current.get("manifest") or "").strip()
            if not manifest_p:
                raise RuntimeError("active run manifest is missing")
            manifest = read_json(Path(manifest_p))
            snapshot = str(manifest.get("delivery_snapshot_sha256") or "").strip()
            if not re.fullmatch(r"[0-9a-f]{64}", snapshot):
                raise RuntimeError("delivery snapshot identity is missing or invalid")
            package_path = active_review_package_path(REPO, current)
            if not package_path.is_file():
                raise RuntimeError("review package is missing")
            package_sha = sha256_file(package_path)
            if not re.fullmatch(r"[0-9a-f]{64}", package_sha):
                raise RuntimeError("review package digest is invalid")
            if protocol >= 2:
                from review_orchestrator import record_dispatch_batch
                review_host = str(current.get("review_host") or "").strip().lower()
                record_dispatch_batch(
                    REPO,
                    task_id,
                    sorted(actual),
                    host=review_host,
                )
            else:
                receipts_dir = state / "tasks" / task_id / "reviewer-dispatches"
                receipts_dir.mkdir(parents=True, exist_ok=True)
                from _vnext_common import atomic_write_json, canonical_sha256, utc_now
                for r in actual:
                    receipt_file = receipts_dir / f"{r}.json"
                    receipt_data = {
                        "schema_version": 1,
                        "task_id": task_id,
                        "run_id": run_id,
                        "reviewer": r,
                        "subagent_id": "",
                        "review_package_sha256": package_sha,
                        "dispatched_at": utc_now(),
                        "host": str(current.get("review_host") or "antigravity"),
                    }
                    receipt_data["receipt_sha256"] = canonical_sha256({
                        k: v for k, v in receipt_data.items() if k != "receipt_sha256"
                    })
                    atomic_write_json(receipt_file, receipt_data)
        except Exception as exc:
            emit(
                "deny",
                f"[REVIEW_RECEIPT_WRITE_FAILED] Failed creating reviewer dispatch receipt ({type(exc).__name__}).",
                tool=name,
            )
            return

        emit("allow", "Reviewer roster exactly matches the immutable adaptive policy.", tool=name)
    except Exception as exc:
        emit("deny", f"Reviewer policy validation failed closed: {exc}", tool=name)


def _handle_external_mutation(integration, tool_name: str, args: dict) -> None:
    try:
        try:
            plan = active_plan(REPO)
        except Exception:
            emit("deny", f"{integration.display_name} mutation is not included in the active approved plan.", tool=tool_name)
            return
        allowed, reason = validate_external_write(integration, tool_name, args, plan)
        if not allowed:
            emit("deny", reason, tool=tool_name)
            return
        emit("allow", f"{integration.display_name} mutation is plan-bound and idempotency-bound.", tool=tool_name)
    except Exception as exc:
        emit("deny", f"{integration.display_name} mutation authorization failed closed: {exc}", tool=tool_name)


def _handle_mcp_tool(name: str, args: dict) -> None:
    server = str(args.get("ServerName") or args.get("server_name") or args.get("server") or "").lower().strip()
    tool_name = str(args.get("ToolName") or args.get("tool_name") or args.get("tool") or "").strip()
    raw_tool_args = args.get("Arguments") or args.get("arguments") or args.get("args") or {}
    if isinstance(raw_tool_args, str):
        try:
            tool_args = json.loads(raw_tool_args)
        except Exception:
            tool_args = {}
    elif isinstance(raw_tool_args, dict):
        tool_args = raw_tool_args
    else:
        tool_args = {}

    # 1. Query specialized integration registry (e.g. Zoho)
    integration = registry.resolve(server, tool_name)
    if integration is not None:
        if integration.is_read_only(tool_name, tool_args):
            emit("allow", f"Read-only {integration.display_name} inspection is allowed.", tool=name, reason_code="READ_ALLOWED")
            return
        _handle_external_mutation(integration, tool_name, tool_args)
        return

    # 2. Generic MCP classification and authorization (Sections 57-63)
    from integrations.generic_mcp import (
        classify_generic_mcp_tool,
        validate_generic_mcp_mutation,
        compute_generic_mcp_fingerprint,
        READ,
        UNKNOWN,
    )

    tool_class = classify_generic_mcp_tool(tool_name)
    if tool_class == READ:
        emit("allow", f"Read-only MCP tool execution '{tool_name}' on server '{server}' is allowed.", tool=name, reason_code="MCP_READ_ALLOWED")
        return

    if tool_class == UNKNOWN:
        emit("deny", f"External MCP operation '{tool_name}' on server '{server}' cannot be classified safely and is denied.", tool=name, reason_code="UNKNOWN_MCP_TOOL")
        return

    # WRITE or HIGH_IMPACT requires an active approved task plan
    try:
        plan = active_plan(REPO)
    except Exception:
        emit("deny", "External MCP mutation requires an active approved task plan.", tool=name, reason_code="PLAN_NOT_APPROVED")
        return

    allowed, reason, reason_code = validate_generic_mcp_mutation(
        server=server,
        tool_name=tool_name,
        plan=plan,
    )
    task_id = str(plan.get("task_id") or "")
    if not allowed:
        emit("deny", reason, tool=name, reason_code=reason_code, task_id=task_id)
        return

    fingerprint = compute_generic_mcp_fingerprint(
        task_id=task_id,
        plan_sha256=str(plan.get("plan_sha256") or ""),
        server=server,
        tool_name=tool_name,
        arguments=tool_args,
    )
    emit(
        "allow",
        f"Generic MCP mutation '{tool_name}' on server '{server}' is authorized.",
        tool=name,
        reason_code=reason_code,
        task_id=task_id,
        mcp_fingerprint=fingerprint,
    )


def _is_targeted_search_path(target: str) -> bool:
    if not target or target.strip() in {".", "./", "", "/", "\\"}:
        return False
    p = target.replace("\\", "/").strip().rstrip("/")
    file_exts = (
        ".kt", ".java", ".xml", ".gradle", ".kts", ".json", ".properties",
        ".pro", ".txt", ".md", ".toml", ".png", ".jpg", ".webp", ".svg",
    )
    if any(p.lower().endswith(ext) for ext in file_exts):
        return True

    generic_roots = {
        "app", "core", "domain", "data", "feature", "features",
        "app/src", "app/src/main", "app/src/main/java", "app/src/main/res",
        "core/src", "core/src/main", "core/src/main/java",
    }
    try:
        resolved = Path(target).resolve()
        rel = resolved.relative_to(REPO.resolve()).as_posix().lower()
    except Exception:
        rel = p.lstrip("./").lower()

    if rel in generic_roots or rel in {".", ""}:
        return False

    parts = [part for part in rel.split("/") if part]
    if len(parts) >= 4:
        return True
    if any(segment in {"feature", "features", "navigation", "ui", "viewmodel", "repository", "datasource"} for segment in parts):
        return True
    return False


BROAD_SEARCH_PATTERNS = {
    "*", "*.*", "*.kt", "*.java", "*.xml", "*.gradle", "*.kts", "*.json",
    "*.properties", "*.pro", "**/*", "**", "",
}


def _is_targeted_pattern(pattern: str) -> bool:
    if not pattern:
        return False
    clean = pattern.strip().replace("\\", "/")
    if clean.lower() in BROAD_SEARCH_PATTERNS:
        return False
    if re.match(r"^\*+\.[a-zA-Z0-9]+$", clean):
        return False
    core = re.sub(r"[*?]", "", clean)
    core_name = Path(core).name
    return len(core_name) >= 3 and core_name.lower() not in {"src", "main", "test", "app", "core", "file"}


def _is_targeted_search(name: str, args: dict) -> bool:
    if name == "grep_search":
        target = str(args.get("SearchPath") or args.get("searchPath") or "")
        if _is_targeted_search_path(target):
            return True
        includes = args.get("Includes") or args.get("includes") or []
        if isinstance(includes, list) and any(_is_targeted_pattern(str(inc)) for inc in includes):
            return True
        return False
    elif name == "find_by_name":
        target = str(args.get("SearchDirectory") or args.get("searchDirectory") or "")
        if _is_targeted_search_path(target):
            return True
        pattern = str(args.get("Pattern") or args.get("pattern") or "")
        if _is_targeted_pattern(pattern):
            return True
        return False
    return False


def _get_active_task_scope(repo: Path, plan: dict) -> tuple[set[str], set[str]]:
    roots: set[str] = set()
    files: set[str] = set()

    for ef in plan.get("expected_files") or []:
        norm = str(ef).replace("\\", "/").strip().lstrip("/")
        if not norm:
            continue
        files.add(norm.lower())
        p = Path(norm)
        parent = p.parent.as_posix().lower()
        if parent and parent != ".":
            roots.add(parent)

    prov = plan.get("discovery_provenance") or {}
    for r in prov.get("allowed_search_roots") or []:
        norm_r = str(r).replace("\\", "/").strip().lstrip("/").lower().rstrip("/")
        if norm_r:
            roots.add(norm_r)
    for p in prov.get("resolved_paths") or []:
        norm_p = str(p).replace("\\", "/").strip().lstrip("/").lower()
        if norm_p:
            files.add(norm_p)
            parent = Path(norm_p).parent.as_posix().lower()
            if parent and parent != ".":
                roots.add(parent)

    try:
        from discovery_receipt import load_latest_discovery_receipt, load_discovery_receipt
        rec_id = str(prov.get("discovery_id") or "")
        receipts_to_check = []
        if rec_id:
            r = load_discovery_receipt(repo, rec_id)
            if r:
                receipts_to_check.append(r)
        latest = load_latest_discovery_receipt(repo)
        if latest and latest not in receipts_to_check:
            receipts_to_check.append(latest)

        for rec in receipts_to_check:
            for r in rec.get("allowed_search_roots") or []:
                norm_r = str(r).replace("\\", "/").strip().lstrip("/").lower().rstrip("/")
                if norm_r:
                    roots.add(norm_r)
            for p in rec.get("resolved_paths") or []:
                norm_p = str(p).replace("\\", "/").strip().lstrip("/").lower()
                if norm_p:
                    files.add(norm_p)
                    parent = Path(norm_p).parent.as_posix().lower()
                    if parent and parent != ".":
                        roots.add(parent)
            for er in rec.get("expanded_roots") or []:
                norm_er = str(er).replace("\\", "/").strip().lstrip("/").lower().rstrip("/")
                if norm_er:
                    roots.add(norm_er)
    except Exception:
        pass

    arch = plan.get("architecture_contract") or {}
    arch_scope = str(arch.get("target_scope") or "").replace("\\", "/").strip().lstrip("/")
    if arch_scope:
        files.add(arch_scope.lower())
        parent = Path(arch_scope).parent.as_posix().lower()
        if parent and parent != ".":
            roots.add(parent)

    return roots, files


def _is_path_in_active_scope(repo: Path, target_path: str, plan: dict) -> bool:
    target_str = str(target_path or "").replace("\\", "/").strip().rstrip("/")
    if not target_str or target_str in {".", "./"}:
        return False
    try:
        p = Path(target_str)
        if p.is_absolute():
            rel = p.resolve().relative_to(repo.resolve()).as_posix().lower()
        else:
            rel = target_str.lstrip("./").lower()
    except Exception:
        rel = target_str.lstrip("./").lower()

    try:
        from discovery_router import _is_exact_non_architectural_file
        if _is_exact_non_architectural_file(target_str):
            return True
    except Exception:
        pass

    roots, files = _get_active_task_scope(repo, plan)
    if not roots and not files:
        try:
            from discovery_receipt import load_latest_discovery_receipt, is_path_in_discovery_scope
            rec = load_latest_discovery_receipt(repo)
            if rec and is_path_in_discovery_scope(repo, target_str, rec):
                return True
        except Exception:
            pass
        return False

    if rel in files:
        return True
    for r in roots:
        if not r:
            continue
        if rel == r or rel.startswith(r + "/"):
            return True

    return False


def _is_contract_file(path: str) -> bool:
    if not path:
        return False
    norm = str(path).replace("\\", "/").strip().lower().lstrip("./")
    if norm in {"agents.md", "gemini.md", "claude.md", "readme.md"}:
        return True
    if norm.startswith("agents/rules/") or norm.startswith(".agents/") or norm.startswith("agents/contracts/"):
        return True
    try:
        from discovery_router import _is_exact_non_architectural_file
        if _is_exact_non_architectural_file(norm):
            return True
    except Exception:
        pass
    return False


def _is_path_in_verifying_scope(repo: Path, target_path: str, plan: dict) -> tuple[bool, str]:
    target_str = str(target_path or "").replace("\\", "/").strip().rstrip("/")
    if not target_str or target_str in {".", "./"}:
        return False, "ROOT_SEARCH_FORBIDDEN"

    repo_root = repo.resolve()
    try:
        p = Path(target_str)
        if p.is_absolute():
            rel = p.resolve().relative_to(repo_root).as_posix().lower()
        else:
            rel = target_str.lstrip("./").lower()
    except Exception:
        rel = target_str.lstrip("./").lower()

    if not rel or rel in {".", "./"}:
        return False, "ROOT_SEARCH_FORBIDDEN"

    if _is_contract_file(rel):
        return True, "CONTRACT_FILE_ALLOWED"

    review_scope = {}
    task_id = str(plan.get("task_id") or "")
    if task_id:
        try:
            from workflow import task_dir
            run_file = task_dir(repo, task_id) / "current-run.json"
        except Exception:
            run_file = state_root(repo) / "tasks" / task_id / "current-run.json"
        if run_file.is_file():
            try:
                run_data = json.loads(run_file.read_text(encoding="utf-8"))
                review_scope = run_data.get("review_scope") or {}
            except Exception:
                pass
    if not review_scope:
        review_scope = plan.get("review_scope") or {}

    changed_files = {str(f).replace("\\", "/").lower().lstrip("./") for f in review_scope.get("changed_files") or []}
    allowed_roots = {str(r).replace("\\", "/").lower().lstrip("./").rstrip("/") for r in review_scope.get("allowed_roots") or []}
    direct_callers = {str(f).replace("\\", "/").lower().lstrip("./") for f in review_scope.get("direct_callers") or []}

    for dc in direct_callers:
        parent = Path(dc).parent.as_posix().lower()
        if parent and parent != ".":
            allowed_roots.add(parent)

    if not changed_files and not allowed_roots and not direct_callers:
        plan_roots, plan_files = _get_active_task_scope(repo, plan)
        allowed_roots.update(plan_roots)
        changed_files.update(plan_files)

    if rel in changed_files:
        return True, "CHANGED_FILE_ALLOWED"
    if rel in direct_callers:
        return True, "DIRECT_CALLER_ALLOWED"

    for r in allowed_roots:
        if not r:
            continue
        if rel == r or rel.startswith(r + "/"):
            return True, "ALLOWED_ROOT"

    try:
        from discovery_receipt import load_latest_discovery_receipt, is_path_in_discovery_scope, check_discovery_freshness
        receipt = load_latest_discovery_receipt(repo)
        if receipt:
            fresh, _ = check_discovery_freshness(repo, receipt)
            if fresh and is_path_in_discovery_scope(repo, target_str, receipt):
                return True, "GRAPH_EXPANSION_ALLOWED"
    except Exception:
        pass

    return False, "OUT_OF_SCOPE"


def _handle_list_dir(name: str, args: dict) -> None:
    plan: dict = {}
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
    except Exception:
        status = ""

    dir_target = str(args.get("DirectoryPath") or args.get("directoryPath") or args.get("path") or ".")

    if status in ("IMPLEMENTING", "READY_FOR_DELIVERY"):
        if _is_path_in_active_scope(REPO, dir_target, plan):
            emit("allow", "Directory listing is within active task scope.", tool=name, reason_code="LIST_DIR_ALLOWED")
            return
        try:
            from discovery_router import _is_exact_non_architectural_file
            if dir_target and _is_exact_non_architectural_file(dir_target):
                emit("allow", "Exact non-architectural directory listing allowed under D0.", tool=name, reason_code="LIST_DIR_ALLOWED")
                return
        except Exception:
            pass
        emit(
            "deny",
            f"DISCOVERY_SCOPE_EXPANSION_REQUIRED: Directory listing '{dir_target}' is outside the active task scope. "
            "Expand scope through Project Graph: 'python .agents/harness.py graph --feature <name> --json' "
            "or 'python .agents/harness.py task-context --file <path> --json'.",
            tool=name,
            reason_code="DISCOVERY_SCOPE_EXPANSION_REQUIRED",
        )
        return

    if status == "VERIFYING":
        allowed, reason = _is_path_in_verifying_scope(REPO, dir_target, plan)
        if allowed:
            emit("allow", "Directory listing is within verified review scope.", tool=name, reason_code="LIST_DIR_ALLOWED")
            return
        emit(
            "deny",
            f"REVIEW_SCOPE_EXPANSION_REQUIRED: Directory listing '{dir_target}' is outside the frozen review scope. "
            "Reviewers must stay within review_scope or run graph expansion.",
            tool=name,
            reason_code="REVIEW_SCOPE_EXPANSION_REQUIRED",
        )
        return

    try:
        from discovery_receipt import load_latest_discovery_receipt, is_path_in_discovery_scope, check_discovery_freshness
        receipt = load_latest_discovery_receipt(REPO)
        if receipt:
            fresh, _ = check_discovery_freshness(REPO, receipt)
            if fresh and is_path_in_discovery_scope(REPO, dir_target, receipt):
                emit("allow", "Directory listing is within active discovery scope.", tool=name, reason_code="LIST_DIR_ALLOWED")
                return
    except Exception:
        receipt = None

    rel = dir_target.replace("\\", "/").strip().rstrip("/")
    try:
        p = Path(dir_target)
        if p.is_absolute():
            rel = p.resolve().relative_to(REPO.resolve()).as_posix().lower()
        else:
            rel = rel.lstrip("./").lower()
    except Exception:
        rel = rel.lstrip("./").lower()

    parts = [part for part in rel.split("/") if part]

    consecutive_list_dirs = 0
    try:
        audit_file = _audit_path()
        if audit_file.exists():
            lines = audit_file.read_text(encoding="utf-8", errors="replace").splitlines()
            records = [json.loads(line) for line in lines if line.strip()]
            for rec in reversed(records[-10:]):
                t = rec.get("tool", "")
                if t == "list_dir":
                    consecutive_list_dirs += 1
                elif t in ("run_command", "write_to_file", "replace_file_content"):
                    break
    except Exception:
        consecutive_list_dirs = 0

    if len(parts) >= 2 or consecutive_list_dirs >= 2:
        emit(
            "deny",
            "DISCOVERY_ANCHOR_REQUIRED: Directory traversal cascade detected before architectural discovery. "
            "Anchor discovery with 'python .agents/harness.py task-context --file <path> --json' "
            "or 'python .agents/harness.py graph --feature <name> --json'.",
            tool=name,
            reason_code="DISCOVERY_ANCHOR_REQUIRED",
        )
        return

    emit("allow", "Minimal repository orientation directory listing permitted.", tool=name, reason_code="LIST_DIR_ALLOWED")


def _handle_search(name: str, args: dict) -> None:
    plan: dict = {}
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
    except Exception:
        status = ""

    target = ""
    query = ""
    if name == "grep_search":
        target = str(args.get("SearchPath") or args.get("searchPath") or "")
        query = str(args.get("Query") or args.get("query") or "")
    elif name == "find_by_name":
        target = str(args.get("SearchDirectory") or args.get("searchDirectory") or "")
        query = str(args.get("Pattern") or args.get("pattern") or "")

    if status == "VERIFYING":
        allowed, reason = _is_path_in_verifying_scope(REPO, target, plan)
        if allowed:
            emit("allow", "Search is within verified review scope.", tool=name, reason_code="VERIFIER_SEARCH_ALLOWED")
            return
        emit(
            "deny",
            f"REVIEW_SCOPE_EXPANSION_REQUIRED: Search path '{target or '.'}' is outside the frozen review scope. "
            "Reviewers must stay within review_scope or run graph expansion.",
            tool=name,
            reason_code="REVIEW_SCOPE_EXPANSION_REQUIRED",
        )
        return

    # 1. If actively implementing, search must stay inside discovered / approved task scope
    if status in ("IMPLEMENTING", "READY_FOR_DELIVERY"):
        if _is_path_in_active_scope(REPO, target, plan):
            emit("allow", "Search is targeted to active task implementation scope.", tool=name, reason_code="SEARCH_ALLOWED")
            return

        try:
            from discovery_router import _is_exact_non_architectural_file
            if target and _is_exact_non_architectural_file(target):
                emit("allow", "Exact non-architectural file search allowed under D0.", tool=name, reason_code="SEARCH_ALLOWED")
                return
        except Exception:
            pass

        clean_target = target.replace("\\", "/").strip()
        emit(
            "deny",
            f"DISCOVERY_SCOPE_EXPANSION_REQUIRED: Search path '{clean_target or '.'}' is outside the active task implementation scope. "
            "Expand scope through Project Graph: 'python .agents/harness.py graph --find <symbol> --json' "
            "or 'python .agents/harness.py graph --feature <feature> --json' rather than unanchored search.",
            tool=name,
            reason_code="DISCOVERY_SCOPE_EXPANSION_REQUIRED",
        )
        return

    # 2. In Discovery Phase: Check if a fresh discovery receipt exists
    receipt = None
    try:
        from discovery_receipt import load_latest_discovery_receipt, is_path_in_discovery_scope, check_discovery_freshness
        receipt = load_latest_discovery_receipt(REPO)
    except Exception:
        receipt = None

    if receipt:
        fresh, _ = check_discovery_freshness(REPO, receipt)
        if fresh:
            if target and is_path_in_discovery_scope(REPO, target, receipt):
                emit("allow", "Search is targeted within active discovery scope.", tool=name, reason_code="SEARCH_ALLOWED")
                return
            else:
                emit(
                    "deny",
                    f"DISCOVERY_SCOPE_EXPANSION_REQUIRED: Search path '{target or '.'}' is outside the active discovery scope. "
                    "Expand discovery through Project Graph: 'python .agents/harness.py graph --find <symbol> --json' "
                    "or '--feature <feature> --json' rather than unanchored search.",
                    tool=name,
                    reason_code="DISCOVERY_SCOPE_EXPANSION_REQUIRED",
                )
                return

    # 3. No discovery receipt yet: Check exact non-architectural file exception (D0)
    try:
        from discovery_router import _is_exact_non_architectural_file
        if target and _is_exact_non_architectural_file(target):
            emit("allow", "Exact non-architectural file search allowed under D0.", tool=name, reason_code="SEARCH_ALLOWED")
            return
    except Exception:
        pass

    # Deny initial code search without discovery anchor
    clean_q = query.strip()
    is_symbol_q = bool(re.match(r"^[A-Z][a-zA-Z0-9_]+$", clean_q))
    target_clean = target.replace("\\", "/").strip().lower()
    feature_match = re.search(r"\b(?:feature|features|flow)/([a-zA-Z0-9_-]+)", target_clean)
    if not feature_match:
        feature_match = re.search(r"([a-zA-Z0-9_-]+)(?:ViewModel|Screen|Fragment|Repository|Service)", clean_q)

    if is_symbol_q:
        anchor_cmd = f"python .agents/harness.py task-context --symbol {clean_q} --json"
    elif feature_match:
        feat = feature_match.group(1).lower()
        anchor_cmd = f"python .agents/harness.py graph --feature {feat} --json"
    else:
        anchor_cmd = "python .agents/harness.py graph --feature <name> --json or python .agents/harness.py task-context --file <path> --json"

    emit(
        "deny",
        f"DISCOVERY_ANCHOR_REQUIRED: Search cannot be the initial discovery mechanism for code tasks. "
        f"Anchor discovery first with '{anchor_cmd}'.",
        tool=name,
        reason_code="DISCOVERY_ANCHOR_REQUIRED",
    )


CONVERSATION_LIMIT = 50
CODE_READ_SUFFIXES = (".kt", ".kts", ".java", ".xml", ".gradle")


def _conversation_started_at(payload: dict) -> float | None:
    """First time this hook saw the calling conversation; None when the host sends no identity."""
    conversation = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()
    if not conversation or conversation == "claude-session":
        return None
    try:
        import time
        path = _audit_path().with_name("hook-conversations.json")
        try:
            seen = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(seen, dict):
                seen = {}
        except (OSError, ValueError):
            seen = {}
        if conversation in seen:
            return float(seen[conversation])
        seen[conversation] = time.time()
        newest = sorted(seen.items(), key=lambda item: float(item[1]))[-CONVERSATION_LIMIT:]
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".conversations-", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(newest), handle)
        os.replace(temp_name, path)
        return float(seen[conversation])
    except Exception:
        return None


def _flag_out_of_scope_read(name: str, args: dict) -> None:
    """Audit a code read outside the task or discovery scope. Reads are never blocked."""
    try:
        target = str(args.get("AbsolutePath") or args.get("absolutePath") or _target(args) or "").replace("\\", "/")
        if not target.lower().endswith(CODE_READ_SUFFIXES):
            return
        path = Path(target)
        rel = path.resolve().relative_to(REPO.resolve()).as_posix() if path.is_absolute() else target.lstrip("./")
        if rel.startswith(".agents/"):
            return
        try:
            plan = active_plan(REPO)
        except Exception:
            plan = {}
        if plan.get("status") in ("IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"):
            in_scope = _is_path_in_active_scope(REPO, rel, plan)
        else:
            from discovery_receipt import check_discovery_freshness, is_path_in_discovery_scope, load_latest_discovery_receipt
            receipt = load_latest_discovery_receipt(REPO)
            if not receipt or not check_discovery_freshness(REPO, receipt)[0]:
                return
            in_scope = is_path_in_discovery_scope(REPO, rel, receipt)
        if not in_scope:
            _audit("allow", f"READ_OUTSIDE_SCOPE: {rel}", name, "", reason_code="READ_OUTSIDE_SCOPE", task_id=str(plan.get("task_id") or ""))
    except Exception:
        return


def main() -> None:
    try:
        raw = sys.stdin.read()
        if len(raw.encode("utf-8", errors="replace")) > MAX_STDIN_BYTES:
            emit("deny", "Hook payload exceeds the 5 MiB safety limit.")
            return
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            raise ValueError("hook payload must be an object")
        if any(key in payload for key in ("terminationReason", "termination_reason")) or payload.get("event") == "Stop" or payload.get("hook") == "Stop":
            _handle_stop()
            return
        started = _conversation_started_at(payload)
        if started is not None:
            import discovery_receipt
            discovery_receipt.RECEIPT_NOT_BEFORE = started
        name, args = _tool_name_and_args(payload)
        if name in WRITE_TOOLS:
            targets = _extract_all_targets(args)
            if not targets:
                targets = [""]
            all_safe = True
            all_temp = True
            first_detail = ""
            for t in targets:
                safe, detail, is_temp = _safe_target(t)
                if not safe:
                    all_safe = False
                    first_detail = detail
                    break
                if not is_temp:
                    all_temp = False
            if not all_safe:
                emit("deny", first_detail, tool=name, reason_code="PROTECTED_PATH")
                return
            if all_temp:
                emit("allow", "Temporary setup answers or IDE artifact write is allowed.", tool=name, reason_code="TEMP_WRITE_ALLOWED")
                return
            allowed, reason, code = file_mutation_allowed(REPO, targets=targets)
            emit("allow" if allowed else "deny", reason, tool=name, reason_code=code)
            return
        if name == "run_command":
            command = str(args.get("CommandLine") or args.get("commandLine") or args.get("command") or "")
            _handle_command(command)
            return
        if name in SUBAGENT_TOOLS:
            _handle_subagent(name, args)
            return
        if name in SEARCH_TOOLS:
            _handle_search(name, args)
            return
        if name == "list_dir":
            _handle_list_dir(name, args)
            return
        # External integrations called directly as host tools (e.g. zoho_add_comment)
        integration = registry.resolve("", name)
        if integration is not None:
            if integration.is_read_only(name, args):
                emit("allow", f"Read-only {integration.display_name} inspection is allowed.", tool=name)
                return
            _handle_external_mutation(integration, name, args)
            return
        if name in ("call_mcp_tool", "mcp_tool"):
            _handle_mcp_tool(name, args)
            return

        mcp_match = re.match(r"^mcp_([a-zA-Z0-9_-]+)_(.+)$", name)
        if mcp_match:
            _handle_mcp_tool(name, {
                "ServerName": mcp_match.group(1),
                "ToolName": mcp_match.group(2),
                "Arguments": args,
            })
            return

        # Known read-only tools
        if name in ("view_file", "read_url_content", "search_web", "read_resource", "list_resources", "ask_question", "generate_image"):
            if name == "view_file":
                _flag_out_of_scope_read(name, args)
            emit("allow", "Tool is outside the harness mutation boundary.", tool=name, reason_code="KNOWN_READ_TOOL")
            return

        # Capability-based safety for unknown host tools
        tgt = _target(args)
        mutation_verbs = (
            "write", "edit", "delete", "remove", "move", "rename", "create",
            "apply", "patch", "execute", "run", "send", "publish", "post",
            "put", "mutate", "destroy", "drop", "grant", "modify",
        )
        has_mutation_verb = any(v in name for v in mutation_verbs)
        has_mutation_args = bool(tgt and any(k in args for k in ("content", "code", "patch", "replacement", "text", "data")))

        if has_mutation_verb or has_mutation_args:
            emit("deny", f"Denied unknown mutation-like tool '{name}'; not authorized by harness safety boundary.", tool=name, reason_code="UNKNOWN_MUTATION_TOOL")
            return

        emit("allow", "Tool is outside the harness mutation boundary.", tool=name, reason_code="UNKNOWN_TOOL_READ_ASSUMED")
    except json.JSONDecodeError:
        emit("deny", "Safety hook received invalid JSON.")
    except Exception as exc:
        emit("deny", f"Safety hook failed closed ({type(exc).__name__}: {exc}).")


if __name__ == "__main__":
    main()
