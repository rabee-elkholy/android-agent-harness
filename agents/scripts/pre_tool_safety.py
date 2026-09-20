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
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import REPO  # noqa: E402
from mutation_guard import _entry, active_plan, command_allowed, file_mutation_allowed  # noqa: E402
from _vnext_common import read_json, sha256_file, validate_id  # noqa: E402


MAX_STDIN_BYTES = 5 * 1024 * 1024
AUDIT_MAX_RECORDS = 1000
WRITE_TOOLS = {
    "write_to_file", "replace_file_content", "apply_patch", "edit", "multiedit",
    "create_file", "delete_file", "move_file", "rename_file",
}
SUBAGENT_TOOLS = {"define_subagent", "invoke_subagent", "manage_subagents", "manage_task", "schedule"}
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
DANGEROUS = (
    ("developer_authority", re.compile(
        r"(?:workflow\.py\b.*\bcancel\b|"
        r"workflow\.py\b.*\b(?:approve|approve-sensitive)\b(?!.*\s--source\s+conversation\b)|"
        r"(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task\b.*\bcancel\b|"
        r"(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task\b.*\b(?:approve|approve-sensitive)\b(?!.*\s--source\s+conversation\b))",
        re.I,
    )),
    ("git_mutation", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*g[i\u0131]t(?:\.exe)?(?:\s+-c\s+\S+)*\s+(?:add|am|apply|branch|checkout|clean|commit|config|fetch|gc|merge|mv|prune|pull|push|rebase|remote\s+(?:add|remove|set-url)|reset|restore|rm|stash|switch|tag|update-index|worktree)\b", re.I)),
    ("shell_indirection", re.compile(r"\b(?:base64\s+(?:-d|--decode)|frombase64string|invoke-expression|iex|eval)\b", re.I)),
    ("adb_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:root|remount|backup|restore|disable-verity|enable-verity|uninstall|clear)\b", re.I | re.S)),
    ("package_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:pm|cmd\s+package)\s+(?:clear|uninstall|disable|suspend|install-existing)\b", re.I | re.S)),
    ("raw_adb", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*adb(?:\.exe)?\b", re.I)),
    ("harness_device_emergency", re.compile(r"run_device\.py\b(?:(?=.*\s--force\b)|(?=.*\s--grant-runtime-permissions\b)|\s+uninstall\b)", re.I)),
    ("tracker_write", re.compile(r"(?:\b(?:zoho|jira|linear)\b.*\b(?:create|update|delete|close|transition|done|solved)\b|\b(?:create|update|delete|close|transition|done|solved)[_\s-]*(?:zoho|jira|linear)\b)", re.I | re.S)),
    ("draft_force", re.compile(r"(?:workflow\.py\b.*\bdraft\b.*--force\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task\b.*\bdraft\b.*--force\b)", re.I)),
    ("review_override_provenance", re.compile(r"record_review\.py\b.*--override-reviews\b.*--source\s+developer_terminal\b", re.I)),
    ("signoff_authority", re.compile(r"run_device(?:\.py)?\b.*\bsignoff\b", re.I)),
    ("dirty_tree_delivery_override", re.compile(r"(?:workflow(?:\.py)?\b.*\bdeliver\b.*--(?:allow-dirty-tree|developer-allow-dirty-tree)\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task\b.*\bdeliver\b.*--(?:allow-dirty-tree|developer-allow-dirty-tree)\b)", re.I)),
)
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
) -> None:
    _audit(decision, reason, tool, command, reason_code=reason_code, conv_hint=conv_hint, task_id=task_id)
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


def _is_ide_artifact(resolved: Path) -> bool:
    try:
        parts = {p.lower() for p in resolved.parts}
        if ".gemini" in parts and "antigravity" in parts and "brain" in parts:
            return True
        brain_root = (Path.home() / ".gemini" / "antigravity" / "brain").resolve()
        return resolved == brain_root or brain_root in resolved.parents
    except Exception:
        return False


def _safe_target(raw_target: str) -> tuple[bool, str, bool]:
    if not raw_target.strip():
        return False, "Mutating file tool did not expose a target path; refusing an unscoped write.", False
    raw = Path(raw_target).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (REPO / raw).resolve()
    user_harness = (Path.home() / ".android-harness").resolve()
    if resolved == user_harness or user_harness in resolved.parents:
        return False, "User-level Android Harness configuration and model routes are developer-owned and immutable to model file tools.", False
    try:
        relative = resolved.relative_to(REPO.resolve()).as_posix()
    except ValueError:
        temp_dir = Path(tempfile.gettempdir()).resolve()
        if (resolved == temp_dir or temp_dir in resolved.parents) and resolved.suffix.lower() == ".json":
            return True, str(resolved), True
        if _is_ide_artifact(resolved):
            return True, str(resolved), True
    if relative == ".agents/project-context/project-notes.md":
        return True, str(resolved), True
    if relative == ".agents/project-context/architecture-policy.json" or relative.startswith(".agents/project-context/legacy-overrides/"):
        return False, "Architecture policy and legacy overrides are developer-owned and immutable to model file tools to prevent context poisoning.", False
    if any(relative == root or relative.startswith(root + "/") for root in PROTECTED_ROOTS):
        return False, "Harness engine, state, and ownership evidence are immutable to agent file tools.", False
    is_kit_dev = (REPO / "harness_cli.py").is_file() and (REPO / "scripts_dev").is_dir()
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


def _handle_stop() -> None:
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
    except Exception:
        emit("allow", "No active vNext task requires a delivery stop.", tool="stop", reason_code="STOP_IDLE")
        return
    emit("allow", f"Turn completion permitted for task in status {status or 'unknown'}.", tool="stop", reason_code="STOP_ALLOWED")


def _handle_command(command: str) -> None:
    active_tid = ""
    try:
        p = active_plan(REPO)
        active_tid = str(p.get("task_id") or "")
    except Exception:
        pass
    for code, pattern in DANGEROUS:
        if pattern.search(command):
            emit("deny", f"Denied by local safety boundary: {code}.", tool="run_command", command=command, reason_code=code.upper(), task_id=active_tid)
            return
    if RAW_GRADLE.search(command) and not ALLOWED_GRADLE_WRAPPER.search(command):
        emit("deny", "Raw Gradle execution is blocked; use the harness Gradle/test gate.", tool="run_command", command=command, reason_code="RAW_GRADLE", task_id=active_tid)
        return
    allowed, reason = command_allowed(REPO, command)
    if allowed and re.search(r"project_graph(?:\.py)?\b", command):
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
            raw_subs = args.get("Subagents") or args.get("subagents") or []
            if isinstance(raw_subs, list) and len(raw_subs) > 5:
                emit("deny", f"Subagent batch size {len(raw_subs)} exceeds the safety limit of 5.", tool=name)
                return
            emit("allow", "On-demand specialist action is inside the approved implementation.", tool=name)
            return
        if status != "VERIFYING":
            emit("deny", f"Subagent action is unavailable while task status is {status or 'missing'}.", tool=name)
            return
        if name != "invoke_subagent":
            emit("allow", "Reviewer management is allowed during verification.", tool=name)
            return
        state = REPO / ".agents/state" if (REPO / ".agents").is_dir() else REPO / "agents/state"
        active = read_json(state / "active-task.json")
        current = read_json(state / "tasks" / str(active["task_id"]) / "current-run.json")
        policy = read_json(Path(current["policy"]))
        expected = set(policy.get("reviewers") or [])
        raw_subs = args.get("Subagents") or args.get("subagents") or []
        actual = set()
        for item in raw_subs:
            if not isinstance(item, dict):
                continue
            r_role = str(item.get("Role") or item.get("role") or "").strip()
            r_type = str(item.get("TypeName") or item.get("typeName") or item.get("name") or "").strip()
            if r_role in expected:
                actual.add(r_role)
            elif r_type in expected:
                actual.add(r_type)
            else:
                actual.add(r_role or r_type)
        if not actual or not (actual <= expected):
            emit("deny", f"Reviewer roster mismatch: expected subset of {sorted(expected)}, got unexpected {sorted(actual - expected)}.", tool=name)
            return
        try:
            from review_execution import resolve_execution_profile
            profile = resolve_execution_profile(REPO, str(active["task_id"]), host="antigravity")
            reviewer_routes = profile.get("reviewers", {})
        except Exception:
            reviewer_routes = {}

        for item in raw_subs:
            if not isinstance(item, dict):
                continue
            r_role = str(item.get("Role") or item.get("role") or "").strip()
            r_type = str(item.get("TypeName") or item.get("typeName") or item.get("name") or "").strip()
            key = r_role if r_role in reviewer_routes else r_type
            req_model = str(item.get("Model") or item.get("model") or "inherit").lower().strip()
            if req_model in {"", "inherit"}:
                continue
            allowed_model = reviewer_routes.get(key, {}).get("preferred_model", "inherit").lower().strip()
            if req_model != allowed_model:
                emit("deny", f"Reviewer model escalation for '{key}' ({req_model}) requires explicit central-policy authorization (allowed: {allowed_model}).", tool=name)
                return
        if int(plan.get("review_rounds") or 0) >= int(policy.get("max_review_rounds") or 3):
            emit("deny", "Review round cap reached; developer decision is required.", tool=name)
            return
        used_calls = int(plan.get("review_calls_used") or 0)
        if used_calls + len(actual) > int(policy.get("model_call_budget") or 0):
            emit("deny", "Reviewer model-call budget reached; developer decision is required.", tool=name)
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
            package_path = state / "runs" / snapshot / run_id / "review-package.md"
            if not package_path.is_file():
                raise RuntimeError("review package is missing")
            package_sha = sha256_file(package_path)
            if not re.fullmatch(r"[0-9a-f]{64}", package_sha):
                raise RuntimeError("review package digest is invalid")
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
                    "host": "antigravity",
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

    tool_lower = tool_name.lower()

    # Query integration registry (e.g. Zoho, Jira, Linear)
    integration = registry.resolve(server, tool_name)
    if integration is not None:
        if integration.is_read_only(tool_name, tool_args):
            emit("allow", f"Read-only {integration.display_name} inspection is allowed.", tool=name)
            return
        _handle_external_mutation(integration, tool_name, tool_args)
        return

    is_read = (
        any(tool_lower.startswith(p) for p in KNOWN_MCP_READ_PREFIXES)
        and not any(kw in tool_lower for kw in KNOWN_MCP_MUTATION_KEYWORDS)
    )
    if is_read:
        emit("allow", f"Read-only MCP tool execution '{tool_name}' is allowed.", tool=name)
        return

    emit("deny", f"External MCP operation '{tool_name}' on server '{server}' is not registered as read-only and is not authorized by the active approved plan.", tool=name)


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


def _handle_search(name: str, args: dict) -> None:
    if _is_targeted_search(name, args):
        emit("allow", "Search is targeted to a specific file or feature directory.", tool=name)
        return

    plan: dict = {}
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
    except Exception:
        status = ""

    if status == "VERIFYING":
        emit("allow", "Reviewer verification search is permitted.", tool=name)
        return

    consecutive_broad_searches = 0
    try:
        audit_file = _audit_path()
        if audit_file.exists():
            lines = audit_file.read_text(encoding="utf-8", errors="replace").splitlines()
            records = [json.loads(line) for line in lines if line.strip()]
            for rec in reversed(records[-10:]):
                t = rec.get("tool", "")
                if t in SEARCH_TOOLS:
                    if "targeted" not in rec.get("reason", "").lower():
                        consecutive_broad_searches += 1
                elif t in ("run_command", "view_file", "write_to_file", "replace_file_content"):
                    break
    except Exception:
        consecutive_broad_searches = 0

    if consecutive_broad_searches >= 2:
        emit(
            "deny",
            "Unanchored search cascade detected (multiple consecutive repository-wide searches). "
            "Run 'python .agents/scripts/project_graph.py --feature <name>' or '--find <symbol>' for architectural discovery, "
            "or narrow SearchPath to a specific file or feature directory.",
            tool=name,
        )
        return

    if status not in {"IMPLEMENTING", "READY_FOR_DELIVERY"}:
        has_run_graph = False
        try:
            audit_file = _audit_path()
            if audit_file.exists():
                lines = audit_file.read_text(encoding="utf-8", errors="replace").splitlines()
                records = [json.loads(line) for line in lines if line.strip()]
                task_id = str(plan.get("task_id") or "")
                draft_time = 0.0
                if task_id:
                    tb_file = REPO / ".agents" / "state" / "tasks" / task_id / "task-baseline.json"
                    if tb_file.is_file():
                        draft_time = tb_file.stat().st_mtime
                import time
                cutoff = draft_time or (time.time() - 3600.0)
                for rec in reversed(records):
                    discovery_reason = rec.get("reason", "").lower()
                    if (
                        rec.get("tool") == "run_command"
                        and rec.get("decision") == "allow"
                        and ("project_graph executed" in discovery_reason or "targeted task_context executed" in discovery_reason)
                    ):
                        r_tid = rec.get("task_id")
                        r_ts = float(rec.get("ts") or 0.0)
                        if task_id and r_tid == task_id:
                            has_run_graph = True
                            break
                        if r_ts >= cutoff:
                            has_run_graph = True
                            break
        except Exception:
            has_run_graph = False

        if not has_run_graph:
            emit(
                "deny",
                "Unanchored repository-wide search is paused during initial discovery. "
                "Anchor discovery with 'python .agents/harness.py task-context --file <path> --json' "
                "or 'python .agents/scripts/project_graph.py --feature <name>' / '--find <symbol>', "
                "or specify a targeted SearchPath for literal text in a specific file or feature directory.",
                tool=name,
                reason_code="GRAPH_FIRST_REQUIRED",
            )
            return

    emit("allow", "Search is permitted outside cascade limits.", tool=name, reason_code="SEARCH_ALLOWED")


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
        name, args = _tool_name_and_args(payload)
        if name in WRITE_TOOLS:
            safe, detail, is_temp = _safe_target(_target(args))
            if not safe:
                emit("deny", detail, tool=name, reason_code="PROTECTED_PATH")
                return
            if is_temp:
                emit("allow", "Temporary setup answers or IDE artifact write is allowed.", tool=name, reason_code="TEMP_WRITE_ALLOWED")
                return
            allowed, reason = file_mutation_allowed(REPO)
            emit("allow" if allowed else "deny", reason, tool=name, reason_code="FILE_MUTATION_ALLOWED" if allowed else "FILE_MUTATION_GUARD")
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

        # Known read-only tools
        if name in ("view_file", "list_dir", "read_url_content", "search_web", "read_resource", "list_resources", "ask_question", "generate_image"):
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
