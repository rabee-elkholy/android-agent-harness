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


def join_continuations(command: str) -> str:
    from mutation_guard import join_continuations as _mg_join_continuations
    return _mg_join_continuations(command)


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


def validate_external_write(integration, tool_name: str, args: dict, plan: dict, *, grant=None) -> tuple[bool, str]:
    from integrations.base import validate_external_write as _vew
    return _vew(integration, tool_name, args, plan, grant=grant)
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
    "raw_adb": "To read logcat, pass -d or -t <lines> so adb logcat dumps and exits (e.g. `adb logcat -d -t 500` or "
               "`adb logcat -d -t 500 | Select-String -Pattern \"...\"`). For device status or app install/launch, use "
               "`python .agents/harness.py device status` or `python .agents/harness.py device install-start`.",
}
DANGEROUS = (
    ("git_mutation", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*g[i\u0131]t(?:\.exe)?(?:\s+-c\s+\S+)*\s+(?:add|am|apply|branch|checkout|clean|commit|config|fetch|gc|merge|mv|prune|pull|push|rebase|remote\s+(?:add|remove|set-url)|reset|restore|rm|stash|switch|tag|update-index|worktree)(?![\w-])", re.I)),
    ("shell_indirection", re.compile(r"\b(?:base64\s+(?:-d|--decode)|frombase64string|invoke-expression|iex|eval)\b", re.I)),
    ("adb_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:root|remount|backup|restore|disable-verity|enable-verity|uninstall|clear)\b", re.I | re.S)),
    ("package_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:pm|cmd\s+package)\s+(?:clear|uninstall|disable|suspend|install-existing)\b", re.I | re.S)),
    ("raw_adb", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*adb(?:\.exe)?\b", re.I)),
    ("harness_device_emergency", re.compile(r"run_device\.py\b(?:(?=.*\s--force\b)|(?=.*\s--grant-runtime-permissions\b)|\s+uninstall\b)", re.I)),
    ("tracker_write", re.compile(r"(?:\b(?:zoho|jira|linear)\b.*\b(?:create|update|delete|close|transition|done|solved)\b|\b(?:create|update|delete|close|transition|done|solved)[_\s-]*(?:zoho|jira|linear)\b)", re.I | re.S)),
    ("draft_force", re.compile(r"(?:workflow\.py\b.*\bdraft\b.*--force\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task\b.*\bdraft\b.*--force\b)", re.I)),
    ("review_override_provenance", re.compile(r"record_review\.py\b.*--override-reviews\b.*--source\s+developer_terminal\b", re.I)),
    ("exported_component_acceptance", re.compile(r"exported_component_guard\.py\b.*--accept\b", re.I)),
    ("review_complete_text_bypass", re.compile(r"(?:review_orchestrator(?:\.py)?|harness(?:\.py)?\s+review)\b.*\bcomplete\b.*--text\b", re.I)),
    ("signoff_authority", re.compile(r"run_device(?:\.py)?\b.*\bsignoff\b", re.I)),
    ("dirty_tree_delivery_override", re.compile(r"(?:workflow(?:\.py)?\b.*\bdeliver\b.*--(?:allow-dirty-tree|developer-allow-dirty-tree)\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task\b.*\bdeliver\b.*--(?:allow-dirty-tree|developer-allow-dirty-tree)\b)", re.I)),
)
WORKFLOW_ENTRYPOINTS = {"workflow.py", "workflow"}
TASK_ENTRYPOINTS = {"harness.py", "harness", "harness_cli.py", "harness_cli", "android-harness"}
WORKFLOW_VALUE_FLAGS = {"--repo", "--task-id"}


def _lifecycle_calls(command: str) -> list[tuple[str, list[str]]]:
    """(subcommand, arguments) for each workflow.py / `harness.py task` call in the command.

    Read from the actual command tokens, never from free text such as an outcome
    ("Fix cancel button") or an approval quote.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    calls: list[tuple[str, list[str]]] = []
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
        calls.append((subcommand, rest))
    return calls


def _developer_authority_violation(command: str) -> str:
    """Cancel, and approval from any source other than the conversation, belong to the developer.

    Returns the violated action ("cancel" or "approve"), or "" when the command is allowed.
    """
    for subcommand, rest in _lifecycle_calls(command):
        if subcommand == "change-decision" and "--apply" in rest:
            support = _flag(rest, "--mode") == "extend-scope" and _flag(rest, "--source") == "approved-plan"
            if not support and (_flag(rest, "--source") != "conversation" or not _flag(rest, "--proof-reference")):
                return "change-decision"
        if subcommand == "merge" and "--apply" in rest:
            if _flag(rest, "--source").lower() != "conversation" or not _flag(rest, "--proof-reference"):
                return "merge"
        if subcommand == "cancel":
            # The developer asked in chat: the agent runs it with their words as proof, like an approval.
            if _flag(rest, "--source").lower() != "conversation" or not _flag(rest, "--proof-reference"):
                return "cancel"
        if subcommand in ("approve", "approve-sensitive"):
            if _flag(rest, "--source").lower() != "conversation":
                return "approve"
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    for pos, token in enumerate(tokens):
        name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
        rest = tokens[pos + 1:]
        is_models = name == "review_models.py" or (name in TASK_ENTRYPOINTS and rest[:2] == ["review", "models"])
        if is_models and "set" in rest and not any(flag in rest for flag in ("-h", "--help")):
            if _flag(rest, "--source") != "conversation" or not _flag(rest, "--proof-reference"):
                return "review-models"
    return ""


def _flag(rest: list[str], name: str) -> str:
    for pos, part in enumerate(rest):
        if part.startswith(name + "="):
            return part.split("=", 1)[1].strip(";&|").strip()
        if part == name and pos + 1 < len(rest):
            return rest[pos + 1].strip(";&|").strip()
    return ""


AUDITED_HARNESS_ENTRY = re.compile(
    r"^\s*(?:python(?:\d+(?:\.\d+)?)?(?:\.exe)?|py)\s+\S*?(?:harness|harness_cli|workflow|zoho_sync|pm_discovery)\.py\s", re.I,
)


def _audited_harness_command(command: str) -> bool:
    """One harness entry-point call and nothing chained to it.

    `tracker_write` stops tracker writes through raw shell (curl, ad-hoc scripts). Real app: it also
    refused the harness's own audited `zoho authorize --proof-reference "... update zoho ..."` (the
    words that grant the write) and a `draft` whose outcome said "Update Zoho". The harness commands
    enforce Zoho authority themselves; a chained command is never exempt.
    """
    if not AUDITED_HARNESS_ENTRY.match(command or ""):
        return False
    try:
        from mutation_guard import SHELL_LAUNDERING, _operator_text_any_shell
    except Exception:
        return False
    outside_quotes = _operator_text_any_shell(command)
    if outside_quotes is None or SHELL_LAUNDERING.search(outside_quotes):
        return False
    return not re.search(r";|&&|\|\||\n", outside_quotes)


def _read_only_git_branch_command(command: str) -> bool:
    """True when every `git_mutation` match in `command` is a read-only `git branch` segment."""
    try:
        from mutation_guard import (
            SHELL_LAUNDERING,
            _entry,
            _operator_text_any_shell,
            _split_segments,
            is_read_only_git_branch,
        )
    except Exception:
        return False
    outside_quotes = _operator_text_any_shell(command or "")
    if outside_quotes is None or SHELL_LAUNDERING.search(outside_quotes):
        return False
    segments = _split_segments(command or "")
    if not segments:
        return False
    git_mut_re = DANGEROUS[0][1]
    saw_branch = False
    for seg in segments:
        if not git_mut_re.search(seg):
            continue
        name, args = _entry(seg, REPO)
        if name != "git":
            return False
        if args[:1] == ["-C"] and len(args) >= 3:
            args = args[2:]
        if not is_read_only_git_branch(args):
            return False
        saw_branch = True
    return saw_branch


def _read_only_adb_command(command: str) -> bool:
    """True when every `adb` match in `command` is a bounded read-only `adb logcat` or `pidof` command."""
    try:
        from mutation_guard import (
            SHELL_LAUNDERING,
            _entry,
            _operator_text_any_shell,
            _split_segments,
            _strip_adb_logcat_pipes,
            is_read_only_adb,
        )
    except Exception:
        return False
    normalized = _strip_adb_logcat_pipes(command or "", REPO) or (command or "")
    outside_quotes = _operator_text_any_shell(normalized)
    if outside_quotes is None or SHELL_LAUNDERING.search(outside_quotes):
        return False
    segments = _split_segments(normalized)
    if not segments:
        return False
    adb_re = re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*adb(?:\.exe)?\b", re.I)
    saw_adb = False
    for seg in segments:
        if not adb_re.search(seg):
            continue
        name, args = _entry(seg, REPO)
        if name != "adb" or not is_read_only_adb(args):
            return False
        saw_adb = True
    return saw_adb


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


def _pending_cancel(task_id: str) -> bool:
    if not task_id:
        return False
    marker = state_root(REPO) / CANCEL_REQUEST_FILE
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
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
        from evidence_store import StateLock
        # Separate from the task lock: audit may be called while task state is
        # locked. Serialize append/rotation so concurrent reviewers lose no rows.
        with StateLock(path.parent / ".audit-lock"):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            if path.stat().st_size > AUDIT_ROTATE_BYTES:
                # Read only a bounded tail, and amortize rotation across calls.
                with path.open("rb") as handle:
                    handle.seek(max(0, path.stat().st_size - AUDIT_ROTATE_BYTES // 2))
                    handle.readline()  # discard the possibly partial first row
                    tail = handle.read().splitlines()[-AUDIT_MAX_RECORDS:]
                from _vnext_common import atomic_write_bytes
                atomic_write_bytes(path, b"\n".join(tail) + b"\n")
    except (OSError, ValueError, ImportError, ValidationError):
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
    for key in ("TargetFile", "targetFile", "Path", "path", "AbsolutePath", "absolutePath", "file_path", "filePath"):
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
        from antigravity_runtime import candidate_brain_roots
        for root in candidate_brain_roots():
            if resolved.is_relative_to(root):
                parts = resolved.relative_to(root).parts
                return len(parts) == 2 and parts[1] in {"implementation_plan.md", "task.md", "walkthrough.md"}
        return False
    except Exception:
        return False


def _is_external_user_doc(raw: Path, resolved: Path) -> bool:
    """Allow standalone documentation/notes files outside the repository when explicitly targeted by absolute path."""
    if not raw.is_absolute():
        return False
    try:
        if raw.is_symlink() or resolved.is_symlink():
            return False
    except OSError:
        return False
    if resolved.suffix.lower() not in {".md", ".txt", ".rst", ".adoc"}:
        return False
    if resolved.name.lower() in IMMUTABLE_ADAPTER_FILES or resolved.name.lower() in {
        "cmakelists.txt", "baseline-prof.txt", "startup-prof.txt",
        "requirements.txt", "constraints.txt", "runtime.txt", "version.txt",
    }:
        return False
    if any(part.startswith(".") for part in raw.parts) or any(part.startswith(".") for part in resolved.parts):
        return False
    resolved_str = str(resolved).replace("\\", "/").lower()
    if any(
        seg in resolved_str
        for seg in (
            "/appdata/roaming/",
            "/appdata/local/programs/",
            "/appdata/local/microsoft/",
            "/programdata/",
            "/windows/",
            "/system32/",
            "/program files/",
            "/program files (x86)/",
            "/library/",
        )
    ):
        return False
    try:
        for parent in (resolved.parent, *resolved.parents):
            if (
                (parent / ".git").exists()
                or (parent / ".harness-setup").exists()
                or (parent / ".agents" / "harness.py").exists()
                or (parent / ".agents" / "VERSION").exists()
                or (parent / ".agents" / "state").exists()
            ):
                return False
    except OSError:
        return False
    return True


def _safe_target(raw_target: str, repo: Path | None = None) -> tuple[bool, str, bool]:
    root = (repo or REPO).resolve()
    if not raw_target.strip():
        return False, "Mutating file tool did not expose a target path; refusing an unscoped write.", False
    raw = Path(raw_target).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    user_harness = (Path.home() / ".android-harness").resolve()
    if resolved == user_harness or user_harness in resolved.parents:
        return False, "User-level Android Harness configuration and model routes are developer-owned and immutable to model file tools.", False
    # Check native evidence BEFORE the generic temporary JSON exception: test
    # and custom host roots may themselves live under the temporary directory.
    from antigravity_runtime import candidate_runtime_roots
    if any(resolved == native or native in resolved.parents for native in candidate_runtime_roots()):
        if _is_ide_artifact(resolved):
            return True, str(resolved), True
        return False, "Antigravity native transcripts, metadata and runtime evidence are immutable to agent file tools.", False
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError:
        temp_dir = Path(tempfile.gettempdir()).resolve()
        if (resolved == temp_dir or temp_dir in resolved.parents) and resolved.suffix.lower() == ".json":
            return True, str(resolved), True
        if _is_ide_artifact(resolved) or _is_external_user_doc(raw, resolved):
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


def _normalize_crlf_for_edit(repo: Path, targets: list[str], args: dict) -> None:
    """Normalize CRLF to LF on authorized edit targets before host edit tools run.

    Host edit_file tools match multi-line Target strings byte-for-byte, while LLM tool
    payloads emit LF (`\\n`). Normalizing CRLF (`\\r\\n`) to LF (`\\n`) on disk right before
    an authorized edit prevents `target content not found` failures on Windows checkouts.
    """
    target_chunks: list[str] = []
    for key in ("Target", "target", "TargetContent", "targetContent"):
        val = args.get(key)
        if isinstance(val, str) and val:
            target_chunks.append(val)
    for key in ("ReplacementChunks", "replacementChunks", "Replacements", "replacements", "chunks", "edits"):
        items = args.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    for subkey in ("Target", "target", "TargetContent", "targetContent", "OldStr", "old_str"):
                        subval = item.get(subkey)
                        if isinstance(subval, str) and subval:
                            target_chunks.append(subval)
    multiline_lf_targets = [
        chunk.encode("utf-8", errors="surrogateescape")
        for chunk in target_chunks
        if "\n" in chunk and "\r\n" not in chunk
    ]
    if not multiline_lf_targets:
        return
    from _vnext_common import atomic_write_bytes
    for t in targets:
        if not t:
            continue
        try:
            cand = Path(t) if Path(t).is_absolute() else (repo / t)
            if not cand.is_file() or cand.is_symlink():
                continue
            data = cand.read_bytes()
            if b"\r\n" in data and b"\x00" not in data:
                lf_data = data.replace(b"\r\n", b"\n")
                if any(chunk in lf_data for chunk in multiline_lf_targets):
                    atomic_write_bytes(cand, lf_data)
        except OSError:
            pass


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
    # Bash (the Claude bridge) joins backslash-newline into one command, so pattern checks must see
    # the joined line. PowerShell and cmd have no such continuation: other hosts keep every line.
    if os.environ.get("HARNESS_HOOK_HOST", "").strip().lower() == "claude":
        command = join_continuations(command)
    from mutation_guard import _split_segments, _tokens
    read_commands = {"cat", "type", "more", "head", "tail", "sed", "rg", "grep", "get-content", "gc", "select-string", "sls"}
    for segment in _split_segments(command) or []:
        tokens = _tokens(segment)
        if tokens and tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe") in read_commands:
            if any(_installed_engine_target(token, recursive=True) for token in tokens[1:]):
                _deny_engine_read("run_command", command)
                return
    active_tid = ""
    try:
        p = active_plan(REPO)
        active_tid = str(p.get("task_id") or "")
    except (OSError, ValueError, ValidationError):
        pass
    violated = _developer_authority_violation(command)
    if violated == "cancel":
        _record_cancel_request(active_tid)
        emit("deny", "Denied by local safety boundary: developer_authority. " + _cancel_pending_message(active_tid or "<id>"),
             tool="run_command", command=command, reason_code="DEVELOPER_AUTHORITY", task_id=active_tid)
        return
    if violated:
        emit("deny", "Denied by local safety boundary: developer_authority.", tool="run_command", command=command, reason_code="DEVELOPER_AUTHORITY", task_id=active_tid)
        return
    if _pending_cancel(active_tid) and any(sub in ("resume", "revise", "change-decision") for sub, _ in _lifecycle_calls(command)):
        emit("deny", _cancel_pending_message(active_tid), tool="run_command", command=command, reason_code="CANCEL_PENDING", task_id=active_tid)
        return
    for code, pattern in DANGEROUS:
        if pattern.search(command):
            if code in ("tracker_write", "git_mutation", "raw_adb") and _audited_harness_command(command):
                continue
            if code == "git_mutation" and _read_only_git_branch_command(command):
                continue
            if code in ("raw_adb", "adb_destructive") and _read_only_adb_command(command):
                continue
            hint = f" {DENY_HINTS[code]}" if code in DENY_HINTS else ""
            emit("deny", f"Denied by local safety boundary: {code}.{hint}", tool="run_command", command=command, reason_code=code.upper(), task_id=active_tid)
            return
    if RAW_GRADLE.search(command):
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
    # Google Workspace skill CLIs (gdrive, gdocs, gsheets, ...) are external integrations, not project
    # mutations: their readonly namespace is allowed and their mutate namespace asks the developer,
    # whatever state the code task plan is in. Chained or redirected commands are never recognized.
    from integrations.external_write_policy import classify_workspace_cli, workspace_cli_tokens
    workspace_tokens = workspace_cli_tokens(command)
    if workspace_tokens:
        decision, reason, code = classify_workspace_cli(workspace_tokens)
        emit(decision, reason, tool="run_command", command=command, reason_code=code, task_id=active_tid)
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

            from task_context import lightweight_target_probe
            probe_status = lightweight_target_probe(
                REPO,
                file=option("--file"),
                symbol=option("--symbol"),
                module=option("--module"),
                source_set=option("--source-set"),
            )
            if probe_status in {"RESOLVED", "AMBIGUOUS"}:
                reason = f"targeted task_context executed: {reason}"
        except (OSError, ValueError, ImportError, ValidationError):
            pass
    emit("allow" if allowed else "deny", reason, tool="run_command", command=command, reason_code="HARNESS_COMMAND" if allowed else "COMMAND_MUTATION_GUARD", task_id=active_tid)

def _normalize_subagent_items(args: dict) -> tuple[list[Any], bool]:
    if not isinstance(args, dict):
        return [], False
    if "Subagents" in args or "subagents" in args:
        raw = args.get("Subagents") if "Subagents" in args else args.get("subagents")
        return (raw if isinstance(raw, list) else []), False
    top_level_markers = {
        "Role", "role", "TypeName", "typeName", "Prompt", "prompt",
        "Workspace", "workspace", "Model", "model", "name",
    } | set(COMMON_REASONING_KEYS)
    if any(k in args for k in top_level_markers):
        host_meta_keys = {"toolAction", "toolSummary", "waitForPreviousTools"}
        cleaned = {k: v for k, v in args.items() if k not in host_meta_keys}
        return [cleaned], True
    return [], False


def _handle_phase_reviewer_dispatch(act: dict[str, Any], plan: dict[str, Any], args: dict, tool_name: str) -> None:
    raw_subs, is_single_top_level = _normalize_subagent_items(args)
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
        except (OSError, ValueError, ValidationError):
            pass
    briefs = dict(act.get("briefs") or {})
    is_unbound_replay = bool(act.get("_unbound_replay"))
    if is_single_top_level and len(raw_subs) == 1 and isinstance(raw_subs[0], dict):
        hint_role = str(raw_subs[0].get("Role") or raw_subs[0].get("TypeName") or "").strip()
        if hint_role and hint_role not in dispatchable:
            try:
                from _vnext_common import task_dir as _tdir
                from phase_review import load_phase_ledger, phase_run_file
                td = _tdir(REPO, str(plan.get("task_id") or ""))
                prun_f = phase_run_file(td, phase_id)
                run_meta = read_json(prun_f) if prun_f.is_file() else {}
                ok, _, ledger = load_phase_ledger(td, phase_id, expected_run_id=run_meta.get("phase_review_run_id"))
                rev_entry = ((ledger or {}).get("reviewers") or {}).get(hint_role) or {}
                if ok and rev_entry.get("state") == "DISPATCHED" and not rev_entry.get("execution_id"):
                    dispatchable.append(hint_role)
                    is_unbound_replay = True
                    if not briefs:
                        briefs = dict(run_meta.get("briefs") or {})
            except (OSError, ValueError, ValidationError):
                briefs = dict(briefs)

    from phase_review import check_phase_safety_cap
    new_phase_dispatches = 0 if is_unbound_replay else (len(raw_subs) if is_single_top_level else len(dispatchable))
    cap_ok, cap_msg = check_phase_safety_cap(plan, new_phase_dispatches, repo=REPO)
    if not cap_ok:
        emit("deny", cap_msg, tool=tool_name, reason_code="REVIEWER_CALL_SAFETY_CAP_REACHED")
        return

    allowed_keys_set = set(ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS)
    phase_run_models: dict[str, Any] = {}
    try:
        from _vnext_common import task_dir as _tdir
        from phase_review import phase_run_file
        prun_f = phase_run_file(_tdir(REPO, str(plan.get("task_id") or "")), phase_id)
        if prun_f.is_file():
            phase_run_models = ((read_json(prun_f).get("review_models") or {}).get("reviewers") or {})
    except Exception:
        phase_run_models = {}
    actual = []
    for item in raw_subs:
        if not isinstance(item, dict):
            emit("deny", "Each entry in Subagents array must be an object.", tool=tool_name, reason_code="SUBAGENT_NOT_OBJECT")
            return

        r_role_hint = str(item.get("Role") or item.get("TypeName") or "").strip()
        sel_info = phase_run_models.get(r_role_hint) if isinstance(phase_run_models, dict) else None
        resolved_m = str((sel_info or {}).get("resolved_model") or "")
        allowed_native_model = "flash" if "flash" in resolved_m else ("pro" if "pro" in resolved_m else None)

        if "model" in item or (not allowed_native_model and "Model" in item):
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
        if allowed_native_model and item.get("Model") != allowed_native_model:
            emit(
                "deny",
                (
                    f"REVIEWER_MODEL_MISMATCH: Reviewer '{r_role_hint}' is configured for '{resolved_m}'; "
                    f"you MUST pass Model='{allowed_native_model}' in invoke_subagent."
                ),
                tool=tool_name,
                reason_code="REVIEWER_MODEL_MISMATCH",
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

        item_allowed_keys = set(allowed_keys_set) | ({"Model"} if allowed_native_model else set())
        for k in item:
            if k not in item_allowed_keys:
                emit(
                    "deny",
                    f"Unexpected key '{k}' in subagent invocation. Allowed keys: {sorted(item_allowed_keys)}.",
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

        from review_execution import pointer_matches
        if supplied_prompt != expected_prompt and not pointer_matches(
            supplied_prompt, r_role, str(brief_val), expected_prompt,
        ):
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
        if extra:
            emit(
                "deny",
                f"Reviewer batch contains extra reviewers: expected {sorted(disp_set)}, got {sorted(actual_set)}.",
                tool=tool_name,
                reason_code="REVIEWER_ROSTER_EXTRA",
            )
            return
        if missing and not is_single_top_level:
            emit(
                "deny",
                f"Reviewer batch incomplete: expected {len(disp_set)} reviewers ({sorted(disp_set)}), got {len(actual_set)} ({sorted(actual_set)}). All dispatchable reviewers must be launched in a single invoke_subagent call.",
                tool=tool_name,
                reason_code="REVIEWER_ROSTER_INCOMPLETE",
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
            allow_single=is_single_top_level,
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
    try:
        plan = active_plan(REPO)
    except ValidationError:
        plan = None
    try:
        from host_continuation import assert_execution_session
        if plan:
            assert_execution_session(REPO, plan.get("task_id"))
    except ValidationError as exc:
        emit("deny", str(exc), tool=name, reason_code="HOST_SESSION_MISMATCH")
        return

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

    if plan and plan.get("task_id"):
        from reviewer_host import active_reviews, _load_ledger, lifecycle_action
        for run, ledger_path in active_reviews(REPO):
            if run.get("task_id") != str(plan["task_id"]) or not ledger_path.is_file():
                continue
            try:
                ledger = _load_ledger(run, ledger_path)
            except ValidationError:
                continue
            action = lifecycle_action(REPO, run, ledger.get("reviewers", {}))
            if action and action.get("code") in {"REVIEWER_CANCELLED", "RESUME_REVIEWER", "REVIEWER_RESUME_ENV_BLOCKED"}:
                if action["code"] != "RESUME_REVIEWER":
                    emit("deny", action["reason"], tool=name, reason_code="REVIEWER_CANCELLED")
                    return
                if name != "send_message":
                    emit("deny", "Resume the existing reviewer with the routed send_message.", tool=name, reason_code="REVIEWER_RESUME_REQUIRED")
                    return
                recipient = str(args.get("Recipient") or args.get("recipient") or "")
                message = str(args.get("Message") or args.get("message") or "")
                if recipient != action["recipient"] or message != action["message"]:
                    emit("deny", "Resume must target the same execution with the routed message.", tool=name, reason_code="REVIEWER_RESUME_MISMATCH")
                    return
                from reviewer_host import mark_resume_dispatched
                mark_resume_dispatched(REPO, str(plan["task_id"]), action["inputs"]["reviewer"], recipient)
                emit("allow", "Explicit reviewer resume decision recorded for this execution.", tool=name, reason_code="REVIEWER_RESUME_ALLOWED")
                return

    if name == "invoke_subagent" and (plan is None or str(plan.get("status") or "") not in {"IMPLEMENTING", "VERIFYING"}):
        raw_subs, _ = _normalize_subagent_items(args)
        if raw_subs and all(
            isinstance(s, dict) and str(s.get("TypeName") or s.get("typeName") or "").strip().lower() in {"research", "explore"}
            for s in raw_subs
        ):
            if len(raw_subs) > 5:
                emit("deny", f"Subagent batch size {len(raw_subs)} exceeds the safety limit of 5.", tool=name)
                return
            emit("allow", "Read-only research subagent is allowed for bounded codebase exploration.", tool=name)
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
                if name == "define_subagent":
                    emit("allow", "Reviewer subagent definition is allowed before phase reviewer dispatch.", tool=name)
                    return
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

            if act_code == "WAIT_FOR_PHASE_REVIEWERS" and name == "invoke_subagent":
                from phase_review import load_phase_ledger, phase_run_file
                from _vnext_common import task_dir as _tdir
                phase_id = str(act.get("inputs", {}).get("phase_id") or "")
                td = _tdir(REPO, task_id)
                prun_f = phase_run_file(td, phase_id)
                run_meta = read_json(prun_f) if prun_f.is_file() else {}
                ok, _, ledger = load_phase_ledger(td, phase_id, expected_run_id=run_meta.get("phase_review_run_id"))
                revs = (ledger or {}).get("reviewers") or {}
                if ok and revs and all(
                    d.get("state") == "DISPATCHED" and not d.get("execution_id")
                    for d in revs.values()
                ):
                    replay_act = {
                        **act,
                        "_unbound_replay": True,
                        "phase_id": phase_id,
                        "reviewers": sorted(run_meta.get("selected_reviewers") or list(revs.keys())),
                        "briefs": dict(run_meta.get("briefs") or {}),
                    }
                    _handle_phase_reviewer_dispatch(replay_act, plan, args, name)
                    return

            if name in {"invoke_subagent", "send_message"} and act_code in {
                "WAIT_FOR_PHASE_REVIEWERS", "COMPLETE_REVIEWER", "PHASE_REVIEW_ENV_BLOCKED", "PHASE_REVIEW_PROTOCOL_BLOCKED",
            }:
                emit("deny", "Follow the existing phase review execution; no replacement or extra reviewer message is routed.",
                     tool=name, reason_code="PHASE_REVIEW_EXECUTION_ALREADY_STARTED")
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

        raw_subs, is_single_top_level = _normalize_subagent_items(args)

        # Determine dispatchable reviewers
        is_unbound_replay = False
        if protocol >= 2:
            from review_orchestrator import load_ledger, dispatchable_reviewers, ledger_file
            directory = state / "tasks" / str(active["task_id"])
            run_id_val = str(current.get("run_id") or "")
            l_path = ledger_file(directory, run_id_val)
            if l_path.is_file():
                ledger = load_ledger(directory, run_id_val)
                dispatchable = dispatchable_reviewers(ledger, required_reviewers)
                revs = ledger.get("reviewers") or {}
                if not dispatchable:
                    if revs and all(
                        d.get("state") == "DISPATCHED" and not d.get("execution_id")
                        for d in revs.values()
                    ):
                        dispatchable = list(required_reviewers)
                        is_unbound_replay = True
                if is_single_top_level and len(raw_subs) == 1 and isinstance(raw_subs[0], dict):
                    hint_role = str(raw_subs[0].get("Role") or raw_subs[0].get("TypeName") or "").strip()
                    rev_entry = revs.get(hint_role) or {}
                    if hint_role and hint_role not in dispatchable and rev_entry.get("state") == "DISPATCHED" and not rev_entry.get("execution_id"):
                        dispatchable.append(hint_role)
                        is_unbound_replay = True
            else:
                dispatchable = list(required_reviewers)
        else:
            dispatchable = list(required_reviewers)

        reviewer_routes = {}
        if protocol >= 2:
            try:
                from review_execution import pointer_matches, resolve_execution_profile
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

        if not isinstance(raw_subs, list) or not raw_subs:
            emit("deny", "No reviewers specified in Subagents array.", tool=name, reason_code="REVIEWER_ROSTER_EMPTY")
            return

        # Check safety cap / round cap
        from review_budget import review_round_cap_action
        round_block = review_round_cap_action(REPO, plan, policy)
        if round_block:
            emit("deny", round_block["reason"], tool=name, reason_code=round_block["code"])
            return
        from review_budget import effective_review_calls_used
        used_calls = effective_review_calls_used(REPO, plan)
        from review_budget import effective_review_budget
        safety_cap = effective_review_budget(REPO, plan, policy)
        new_final_dispatches = 0 if is_unbound_replay else (len(raw_subs) if is_single_top_level else len(dispatchable))
        if used_calls + new_final_dispatches > safety_cap:
            emit(
                "deny",
                "Reviewer Call Safety Cap reached; developer decision is required.",
                tool=name,
                reason_code="REVIEWER_CALL_SAFETY_CAP_REACHED",
            )
            return

        allowed_keys_set = set(ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS)
        final_run_models = ((current or {}).get("review_models") or {}).get("reviewers") or {}
        actual = []
        for item in raw_subs:
            if not isinstance(item, dict):
                emit("deny", "Each entry in Subagents array must be an object.", tool=name, reason_code="SUBAGENT_NOT_OBJECT")
                return

            r_role_hint = str(item.get("Role") or item.get("TypeName") or item.get("role") or item.get("typeName") or "").strip()
            sel_info = final_run_models.get(r_role_hint) if isinstance(final_run_models, dict) else None
            resolved_m = str((sel_info or {}).get("resolved_model") or "")
            allowed_native_model = "flash" if "flash" in resolved_m else ("pro" if "pro" in resolved_m else None)

            if "model" in item or (not allowed_native_model and "Model" in item):
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
            if allowed_native_model and item.get("Model") != allowed_native_model:
                emit(
                    "deny",
                    (
                        f"REVIEWER_MODEL_MISMATCH: Reviewer '{r_role_hint}' is configured for '{resolved_m}'; "
                        f"you MUST pass Model='{allowed_native_model}' in invoke_subagent."
                    ),
                    tool=name,
                    reason_code="REVIEWER_MODEL_MISMATCH",
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

            item_allowed_keys = set(allowed_keys_set) | ({"Model"} if allowed_native_model else set())
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
                route = reviewer_routes[matched]
                expected_prompt = str(route.get("brief_content") or "").replace("\r\n", "\n").strip()
                if supplied_prompt != expected_prompt and not pointer_matches(
                    supplied_prompt, matched, str(route.get("brief_path") or ""), expected_prompt,
                ):
                    emit(
                        "deny",
                        f"Reviewer prompt for '{matched}' does not match the generated reviewer brief. Pass the router's "
                        "`reviewer_prompts[role]` one-line pointer (preferred) or the exact current brief content.",
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
            if extra:
                emit(
                    "deny",
                    f"Reviewer batch contains extra reviewers: expected {sorted(dispatchable_set)}, got {sorted(actual_set)}.",
                    tool=name,
                    reason_code="REVIEWER_ROSTER_EXTRA",
                )
                return
            if missing and not is_single_top_level:
                emit(
                    "deny",
                    f"Reviewer batch incomplete: expected {len(dispatchable_set)} reviewers ({sorted(dispatchable_set)}), got {len(actual_set)} ({sorted(actual_set)}). All dispatchable reviewers must be launched in a single invoke_subagent call.",
                    tool=name,
                    reason_code="REVIEWER_ROSTER_INCOMPLETE",
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
                    allow_single=is_single_top_level,
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


def _handle_external_mutation(integration, tool_name: str, args: dict, server: str = "") -> None:
    try:
        try:
            plan = active_plan(REPO) or {}
        except (OSError, ValueError, ValidationError):
            plan = {}
        if isinstance(plan, dict) and plan:
            plan = {**plan, "repo_root": str(REPO)}
            if not plan.get("repository"):
                plan["repository"] = str(REPO)
        elif not isinstance(plan, dict):
            plan = {}

        if integration.name == "universal_pm":
            from zoho_grant import active_pm_grant, pm_authorize_command
            from integrations.external_write_policy import sensitive_values
            secrets = sensitive_values([args])
            if secrets:
                emit(
                    "deny",
                    f"External PM operation '{tool_name}' would send a credential or signing file "
                    f"({', '.join(sorted(set(secrets)))}).",
                    tool=tool_name,
                    reason_code="SENSITIVE_EXTERNAL_UPLOAD",
                )
                return
            provider_id = integration.resolve_provider_id(server, tool_name)
            display = integration.resolve_display_name(server, tool_name)
            grant = active_pm_grant(REPO, provider=provider_id)
            ok, policy_reason = integration.validate_pm_mutation(server, tool_name, args, plan, grant=grant)
            if not ok:
                emit("deny", policy_reason, tool=tool_name, reason_code="PM_POLICY_VIOLATION")
                return
            ext_writes = set(plan.get("external_writes") or []) if isinstance(plan, dict) else set()
            nonce_ok = bool(
                isinstance(plan, dict)
                and plan.get("execution_nonce")
                and isinstance(plan.get("approval"), dict)
                and plan.get("execution_nonce") == plan["approval"].get("single_use_nonce")
            )
            plan_authorized = nonce_ok and bool(
                ext_writes & {provider_id, "universal_pm", "pm", f"mcp:{server}"}
            )
            if grant or plan_authorized:
                emit(
                    "allow",
                    f"{display} mutation '{tool_name}' is authorized by active PM grant/plan and complies with PM guardrails.",
                    tool=tool_name,
                    reason_code="PM_MUTATION_ALLOWED",
                )
                return
            emit(
                "deny",
                f"PM_PREVIEW_AND_APPROVAL_REQUIRED: Before calling '{tool_name}' on {display}, you MUST: "
                f"(1) present the exact preview of the tracker changes (target item ID, fields/status/comment to be written) "
                f"to the developer in chat and ask for their approval; "
                f"(2) once the developer confirms (e.g. 'حدث التاسك' / 'update pm' / 'موافق حدث التاسك'), run "
                f"`{pm_authorize_command(provider_id.replace('_projects', '').replace('_sprints', ''))}` with their exact message; "
                f"then retry '{tool_name}'.",
                tool=tool_name,
                reason_code="PM_PREVIEW_AND_APPROVAL_REQUIRED",
            )
            return

        grant = None
        if integration.name == "zoho_sprints":
            from zoho_grant import active_grant
            grant = active_grant(REPO)
        if not plan and not grant:
            emit("deny", f"{integration.display_name} mutation is not included in the active approved plan.", tool=tool_name)
            return
        allowed, reason = validate_external_write(integration, tool_name, args, plan, grant=grant)
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

    # 1. Query specialized integration registry (e.g. Zoho Sprints & Universal PM MCPs)
    integration = _get_registry().resolve(server, tool_name)
    if integration is not None:
        if integration.is_read_only(tool_name, tool_args):
            disp = integration.resolve_display_name(server, tool_name) if hasattr(integration, "resolve_display_name") else integration.display_name
            emit("allow", f"Read-only {disp} inspection is allowed.", tool=name, reason_code="READ_ALLOWED")
            return
        _handle_external_mutation(integration, tool_name, tool_args, server=server)
        return

    # 2. Generic MCP classification and authorization (Sections 57-63)
    from integrations.generic_mcp import (
        classify_generic_mcp_tool,
        validate_generic_mcp_mutation,
        compute_generic_mcp_fingerprint,
        READ,
    )
    from integrations.external_write_policy import generic_mcp_prompt, sensitive_values

    tool_class = classify_generic_mcp_tool(tool_name)
    if tool_class == READ:
        emit("allow", f"Read-only MCP tool execution '{tool_name}' on server '{server}' is allowed.", tool=name, reason_code="MCP_READ_ALLOWED")
        return

    # WRITE, HIGH_IMPACT and UNKNOWN calls never carry a credential or signing file off the machine.
    secrets = sensitive_values([tool_args])
    if secrets:
        emit(
            "deny",
            f"External MCP operation '{tool_name}' on '{server}' would send a credential or signing file "
            f"({', '.join(sorted(set(secrets)))}). Use a copy without secrets instead.",
            tool=name,
            reason_code="SENSITIVE_EXTERNAL_UPLOAD",
        )
        return

    # An approved plan scope (--external-write mcp:<server>[:high-impact]) authorizes the call silently.
    # Anything else asks the developer through the host prompt instead of tying the write to the code
    # plan's state: an upload the developer asked for must not wait for an unrelated plan approval.
    plan: dict = {}
    try:
        plan = active_plan(REPO) or {}
    except Exception:
        plan = {}
    if tool_class == "UNKNOWN":
        allowed = False
        reason = f"'{tool_name}' cannot be classified safely"
        reason_code = "UNKNOWN_MCP_TOOL"
    elif plan:
        allowed, reason, reason_code = validate_generic_mcp_mutation(
            server=server,
            tool_name=tool_name,
            plan=plan,
        )
    else:
        allowed, reason, reason_code = False, "no approved plan covers this server", "PLAN_NOT_APPROVED"
    task_id = str(plan.get("task_id") or "")
    fingerprint = compute_generic_mcp_fingerprint(
        task_id=task_id,
        plan_sha256=str(plan.get("plan_sha256") or ""),
        server=server,
        tool_name=tool_name,
        arguments=tool_args,
    )
    if not allowed:
        decision, prompt_reason = generic_mcp_prompt(tool_class, server, tool_name, reason)
        emit(decision, prompt_reason, tool=name, reason_code=reason_code, task_id=task_id, mcp_fingerprint=fingerprint)
        return

    emit(
        "allow",
        f"Generic MCP mutation '{tool_name}' on server '{server}' is authorized.",
        tool=name,
        reason_code=reason_code,
        task_id=task_id,
        mcp_fingerprint=fingerprint,
    )


def _is_within_repo(repo: Path, raw: str) -> bool:
    clean = str(raw or "").strip().replace("\\", "/")
    if not clean or clean in {".", "./"}:
        return True
    try:
        root = repo.resolve()
        path = Path(clean)
        resolved = (path if path.is_absolute() else root / path).resolve()
        return resolved == root or resolved.is_relative_to(root)
    except (OSError, ValueError, RuntimeError):
        return False


def _get_active_task_scope(repo: Path, plan: dict) -> tuple[set[str], set[str]]:
    from discovery_receipt import source_search_root
    roots: set[str] = set()
    files: set[str] = set()

    from change_decision import reserved_files
    for ef in set(plan.get("expected_files") or []) | reserved_files(plan):
        norm = str(ef).replace("\\", "/").strip().lstrip("/")
        if not norm:
            continue
        files.add(norm.lower())
        parent = source_search_root(norm).lower()
        if parent:
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
            parent = source_search_root(norm_p).lower()
            if parent:
                roots.add(parent)

    try:
        from discovery_receipt import load_latest_discovery_receipt, load_discovery_receipt, check_discovery_freshness
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
            if not check_discovery_freshness(repo, rec)[0]:
                continue
            for r in rec.get("allowed_search_roots") or []:
                norm_r = str(r).replace("\\", "/").strip().lstrip("/").lower().rstrip("/")
                if norm_r:
                    roots.add(norm_r)
            for p in rec.get("resolved_paths") or []:
                norm_p = str(p).replace("\\", "/").strip().lstrip("/").lower()
                if norm_p:
                    files.add(norm_p)
                    parent = source_search_root(norm_p).lower()
                    if parent:
                        roots.add(parent)
            for er in rec.get("expanded_roots") or []:
                norm_er = str(er).replace("\\", "/").strip().lstrip("/").lower().rstrip("/")
                if norm_er:
                    roots.add(norm_er)
    except (OSError, ValueError, ImportError, ValidationError):
        pass

    arch = plan.get("architecture_contract") or {}
    arch_scope = str(arch.get("target_scope") or "").replace("\\", "/").strip().lstrip("/")
    if arch_scope:
        files.add(arch_scope.lower())
        parent = source_search_root(arch_scope).lower()
        if parent:
            roots.add(parent)

    return roots, files


def _is_path_in_active_scope(repo: Path, target_path: str, plan: dict) -> bool:
    target_str = str(target_path or "").replace("\\", "/").strip().rstrip("/")
    if not target_str or target_str in {".", "./"}:
        return False
    from discovery_receipt import relative_search_target
    rel = relative_search_target(repo, target_str)
    if rel is None:
        return False

    try:
        from discovery_router import _is_exact_non_architectural_file
        if _is_exact_non_architectural_file(target_str):
            return True
    except (OSError, ValueError, ImportError, ValidationError):
        pass

    roots, files = _get_active_task_scope(repo, plan)
    if not roots and not files:
        try:
            from discovery_receipt import load_latest_discovery_receipt, is_path_in_discovery_scope, check_discovery_freshness
            rec = load_latest_discovery_receipt(repo)
            if rec and check_discovery_freshness(repo, rec)[0] and is_path_in_discovery_scope(repo, target_str, rec):
                return True
        except (OSError, ValueError, ImportError, ValidationError):
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


def _handle_list_dir(name: str, args: dict) -> None:
    plan: dict = {}
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
    except Exception:
        status = ""

    dir_target = str(args.get("DirectoryPath") or args.get("directoryPath") or args.get("path") or ".")
    if not _is_within_repo(REPO, dir_target):
        emit("deny", "Directory target is outside the repository root.", tool=name, reason_code="PROTECTED_PATH")
        return

    if status in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"):
        emit("allow", "Directory listing is allowed during active task lifecycle.", tool=name, reason_code="LIST_DIR_ALLOWED")
        return

    try:
        from discovery_receipt import load_latest_discovery_receipt, check_discovery_freshness
        receipt = load_latest_discovery_receipt(REPO)
        if receipt:
            fresh, _ = check_discovery_freshness(REPO, receipt)
            if fresh:
                emit("allow", "Directory listing is allowed after initial discovery anchor.", tool=name, reason_code="LIST_DIR_ALLOWED")
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
            with audit_file.open("rb") as handle:
                size = audit_file.stat().st_size
                handle.seek(max(0, size - 16384))
                if size > 16384:
                    handle.readline()
                lines = handle.read().decode("utf-8", errors="replace").splitlines()
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

    if target and not _is_within_repo(REPO, target):
        emit("deny", "Search target is outside the repository root.", tool=name, reason_code="PROTECTED_PATH")
        return

    if status == "VERIFYING":
        emit("allow", "Search is allowed during verification.", tool=name, reason_code="VERIFIER_SEARCH_ALLOWED")
        return

    if status in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "READY_FOR_DELIVERY"):
        emit("allow", "Search is allowed during active task lifecycle.", tool=name, reason_code="SEARCH_ALLOWED")
        return

    # In Discovery Phase: Check if a fresh discovery receipt exists
    receipt = None
    try:
        from discovery_receipt import load_latest_discovery_receipt, check_discovery_freshness
        receipt = load_latest_discovery_receipt(REPO)
    except Exception:
        receipt = None

    if receipt:
        fresh, _ = check_discovery_freshness(REPO, receipt)
        if fresh:
            emit("allow", "Search is allowed after initial discovery anchor.", tool=name, reason_code="SEARCH_ALLOWED")
            return

    # 3. No discovery receipt yet: Check exact non-architectural file exception (D0)
    try:
        from discovery_router import _is_exact_non_architectural_file
        if target and _is_exact_non_architectural_file(target):
            emit("allow", "Exact non-architectural file search allowed under D0.", tool=name, reason_code="SEARCH_ALLOWED")
            return
    except (OSError, ValueError, ImportError, ValidationError):
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


def _installed_engine_target(raw: str, *, recursive: bool = False) -> bool:
    """Managed implementation only; rules, plans, evidence and application source remain readable."""
    try:
        path = Path(str(raw).strip().replace("\\", "/"))
        path = path if path.is_absolute() else REPO / path
        # Check both lexical and canonical paths: a symlink cannot hide managed
        # implementation, or expose it through an application-looking alias.
        candidates = (Path(os.path.abspath(path)), path.resolve())
        for candidate in candidates:
            try:
                relative = candidate.relative_to((REPO / ".agents").resolve())
            except ValueError:
                continue
            if not relative.parts:
                return recursive
            first = relative.parts[0].lower()
            if first in {"scripts", "mcp"} or relative.as_posix().lower() == "harness.py":
                return True
            if recursive and any(mark in first for mark in "*?["):
                return True
        return False
    except (ValueError, OSError):
        return False


def _deny_engine_read(tool: str, command: str = "") -> None:
    emit("deny", "HARNESS_IMPLEMENTATION_BOUNDARY: use documented commands and their diagnostics first. "
         "For an unexpected command failure, contract violation, Doctor issue or explicit developer request, "
         "use python .agents/harness.py doctor --inspect-file scripts/<exact-file>.py "
         "--inspection-reason <reason> --reference <concrete-output-or-request> "
         "--inspect-start-line <line> --inspect-lines <1-200>. "
         "Inspect only the relevant excerpt; do not browse dependencies recursively or patch the installed engine.",
         tool=tool, command=command, reason_code="HARNESS_IMPLEMENTATION_BOUNDARY")


def main() -> None:
    # The installed native adapter identifies this hook process. Its current
    # host takes precedence over the project's preferred host and stale callers.
    previous = os.environ.get("HARNESS_HOST")
    os.environ["HARNESS_HOST"] = os.environ.get("HARNESS_HOOK_HOST", "").strip().lower() or "antigravity"
    try:
        _main()
    finally:
        if previous is None:
            os.environ.pop("HARNESS_HOST", None)
        else:
            os.environ["HARNESS_HOST"] = previous


def _main() -> None:
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
        reviewer = None
        conversation = str(payload.get("conversationId") or payload.get("conversation_id") or "")
        if conversation and os.environ.get("HARNESS_HOST") == "antigravity":
            from reviewer_host import reviewer_context, discovery_command_allowed
            reviewer = reviewer_context(REPO, conversation, bind=True)
            if reviewer:
                if name == "run_command":
                    command = str(args.get("CommandLine") or args.get("commandLine") or args.get("command") or "")
                    cwd = Path(str(args.get("Cwd") or args.get("cwd") or REPO)).resolve()
                    if cwd != REPO.resolve() or not discovery_command_allowed(command):
                        emit("deny", "Reviewer run_command permits only bounded graph/task-context discovery.", tool=name, reason_code="REVIEWER_READ_ONLY_BOUNDARY")
                        return
                elif name not in {"view_file", "read_file", "read", "grep_search", "find_by_name", "list_dir"}:
                    emit("deny", "Reviewer tools are limited to source reads and bounded discovery. Do NOT call send_message; output your final review response directly as plain assistant text and end your turn.", tool=name, reason_code="REVIEWER_READ_ONLY_BOUNDARY")
                    return
                if name in SEARCH_TOOLS:
                    from discovery_receipt import load_latest_discovery_receipt, check_discovery_freshness, is_path_in_discovery_scope
                    receipt = load_latest_discovery_receipt(REPO)
                    target = str(args.get("SearchPath") or args.get("searchPath") or args.get("SearchDirectory") or args.get("searchDirectory") or "")
                    if receipt and check_discovery_freshness(REPO, receipt)[0] and is_path_in_discovery_scope(REPO, target, receipt) and not _installed_engine_target(target, recursive=True):
                        emit("allow", "Reviewer search is inside its graph discovery scope.", tool=name, reason_code="REVIEWER_DISCOVERY_SEARCH_ALLOWED")
                        return
        if conversation and not reviewer:
            try:
                from task_bridge import record_active_conversation_turn
                record_active_conversation_turn(REPO, conversation)
            except (ImportError, OSError, ValueError):
                pass
        if name in {"view_file", "read_file", "read", "grep_search", "find_by_name", "list_dir"}:
            target = str(args.get("AbsolutePath") or args.get("absolutePath") or args.get("SearchPath")
                         or args.get("searchPath") or args.get("SearchDirectory") or args.get("searchDirectory")
                         or args.get("DirectoryPath") or args.get("directoryPath") or _target(args) or "")
            if _installed_engine_target(target, recursive=name in SEARCH_TOOLS | {"list_dir"}):
                _deny_engine_read(name)
                return
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
                if name in {"edit_file", "replace_file_content", "multi_replace_file_content", "apply_patch", "edit", "multiedit"}:
                    _normalize_crlf_for_edit(REPO, targets, args)
                emit("allow", "Temporary setup answers, IDE artifact, or external user document write is allowed.", tool=name, reason_code="TEMP_WRITE_ALLOWED")
                return
            try:
                pending_tid = str(active_plan(REPO).get("task_id") or "")
            except Exception:
                pending_tid = ""
            if _pending_cancel(pending_tid):
                emit("deny", _cancel_pending_message(pending_tid), tool=name, reason_code="CANCEL_PENDING")
                return
            allowed, reason, code = file_mutation_allowed(REPO, targets=targets)
            if allowed and name in {"edit_file", "replace_file_content", "multi_replace_file_content", "apply_patch", "edit", "multiedit"}:
                _normalize_crlf_for_edit(REPO, targets, args)
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
        # Known read-only tools (checked before loading external integration registry)
        if name in ("view_file", "read_file", "read", "read_url_content", "search_web", "read_resource", "list_resources", "ask_question", "generate_image"):
            if name in ("view_file", "read_file", "read"):
                _flag_out_of_scope_read(name, args)
            emit("allow", "Tool is outside the harness mutation boundary.", tool=name, reason_code="KNOWN_READ_TOOL")
            return
        # External integrations called directly as host tools (e.g. zoho_add_comment)
        integration = _get_registry().resolve("", name)
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
