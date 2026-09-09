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
from mutation_guard import active_plan, command_allowed, file_mutation_allowed  # noqa: E402
from _vnext_common import read_json  # noqa: E402


MAX_STDIN_BYTES = 5 * 1024 * 1024
AUDIT_MAX_RECORDS = 1000
WRITE_TOOLS = {
    "write_to_file", "replace_file_content", "apply_patch", "edit", "multiedit",
    "create_file", "delete_file", "move_file", "rename_file",
}
SUBAGENT_TOOLS = {"define_subagent", "invoke_subagent", "manage_subagents", "manage_task", "schedule"}
SEARCH_TOOLS = {"grep_search", "find_by_name"}
ZOHO_MUTATION_TOOLS = {
    "zoho_create_task", "zoho_update_task_status", "zoho_add_comment",
    "zoho_update_task_description",
}
PROTECTED_ROOTS = (
    ".agents", "agents/scripts", "agents/state", ".harness-setup/ownership-v1.json",
)

# These stay denied even during approved implementation: they cross the local
# development boundary or make recovery materially harder.
DANGEROUS = (
    ("developer_authority", re.compile(
        r"(?:workflow\.py\b.*\bcancel\b|"
        r"workflow\.py\b.*\b(?:approve|approve-sensitive)\b(?!.*\s--source\s+conversation\b)|"
        r"(?:android-harness|harness_cli\.py)\s+task\b.*\bcancel\b|"
        r"(?:android-harness|harness_cli\.py)\s+task\b.*\b(?:approve|approve-sensitive)\b(?!.*\s--source\s+conversation\b))",
        re.I,
    )),
    ("git_mutation", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*g[i\u0131]t(?:\.exe)?(?:\s+-c\s+\S+)*\s+(?:add|am|apply|branch|checkout|clean|commit|config|fetch|gc|merge|mv|prune|pull|push|rebase|remote\s+(?:add|remove|set-url)|reset|restore|rm|stash|switch|tag|update-index|worktree)\b", re.I)),
    ("shell_indirection", re.compile(r"\b(?:base64\s+(?:-d|--decode)|frombase64string|invoke-expression|iex|eval)\b", re.I)),
    ("adb_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:root|remount|backup|restore|disable-verity|enable-verity|uninstall|clear)\b", re.I | re.S)),
    ("package_destructive", re.compile(r"\badb(?:\.exe)?\b.*\b(?:pm|cmd\s+package)\s+(?:clear|uninstall|disable|suspend|install-existing)\b", re.I | re.S)),
    ("raw_adb", re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*adb(?:\.exe)?\b", re.I)),
    ("harness_device_emergency", re.compile(r"run_device\.py\b(?:(?=.*\s--force\b)|(?=.*\s--grant-runtime-permissions\b)|\s+uninstall\b)", re.I)),
    ("live_network", re.compile(r"\b(?:curl|wget|invoke-webrequest|invoke-restmethod)\b|urllib\.request|requests\.(?:get|post|put|patch|delete)\s*\(", re.I)),
    ("tracker_write", re.compile(r"(?:\b(?:zoho|jira|linear)\b.*\b(?:create|update|delete|close|transition|done|solved)\b|\b(?:create|update|delete|close|transition|done|solved)[_\s-]*(?:zoho|jira|linear)\b)", re.I | re.S)),
)
RAW_GRADLE = re.compile(r"(?:^|[;&|\n]\s*)(?:\.\/?|[^\s]+[/\\])?gradlew(?:\.bat)?\s+", re.I)
ALLOWED_GRADLE_WRAPPER = re.compile(r"(?:run_gradle_task|run_tests_gate)\.py\b", re.I)


def _audit_path() -> Path:
    override = os.environ.get("HARNESS_HOOK_STATE")
    base = Path(override) if override else Path(__file__).resolve().parent.parent / "state" / "hook-state.json"
    return base.with_name("audit_log.jsonl")


def _audit(decision: str, reason: str, tool: str, command: str) -> None:
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "decision": decision,
            "tool": tool[:80],
            "reason": reason[:160],
            "command_sha256_12": hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest()[:12] if command else "",
        }
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


def emit(decision: str, reason: str, *, tool: str = "", command: str = "") -> None:
    _audit(decision, reason, tool, command)
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
    try:
        relative = resolved.relative_to(REPO.resolve()).as_posix()
    except ValueError:
        temp_dir = Path(tempfile.gettempdir()).resolve()
        if (resolved == temp_dir or temp_dir in resolved.parents) and resolved.suffix.lower() == ".json":
            return True, str(resolved), True
        if _is_ide_artifact(resolved):
            return True, str(resolved), True
        return False, "File mutation escapes the approved repository.", False
    if any(relative == root or relative.startswith(root + "/") for root in PROTECTED_ROOTS):
        return False, "Harness engine, state, and ownership evidence are immutable to agent file tools.", False
    return True, relative, False


def _handle_stop() -> None:
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
    except Exception:
        emit("allow", "No active vNext task requires a delivery stop.", tool="stop")
        return
    emit("allow", f"Turn completion permitted for task in status {status or 'unknown'}.", tool="stop")


def _handle_command(command: str) -> None:
    for code, pattern in DANGEROUS:
        if pattern.search(command):
            emit("deny", f"Denied by local safety boundary: {code}.", tool="run_command", command=command)
            return
    if RAW_GRADLE.search(command) and not ALLOWED_GRADLE_WRAPPER.search(command):
        emit("deny", "Raw Gradle execution is blocked; use the harness Gradle/test gate.", tool="run_command", command=command)
        return
    allowed, reason = command_allowed(REPO, command)
    if allowed and re.search(r"project_graph(?:\.py)?\b", command):
        reason = f"project_graph executed: {reason}"
    emit("allow" if allowed else "deny", reason, tool="run_command", command=command)


def _handle_subagent(name: str, args: dict) -> None:
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
        if status == "IMPLEMENTING":
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
        actual = {
            str(item.get("TypeName") or item.get("typeName") or item.get("name") or "")
            for item in raw_subs if isinstance(item, dict)
        }
        if actual != expected:
            emit("deny", f"Reviewer roster mismatch: expected {sorted(expected)}, got {sorted(actual)}.", tool=name)
            return
        if any(str(item.get("model") or "inherit").lower() not in {"", "inherit"} for item in raw_subs if isinstance(item, dict)):
            emit("deny", "Reviewer model escalation requires explicit central-policy authorization.", tool=name)
            return
        if int(plan.get("review_rounds") or 0) >= int(policy.get("max_review_rounds") or 3):
            emit("deny", "Review round cap reached; developer decision is required.", tool=name)
            return
        used_calls = int(plan.get("review_calls_used") or 0)
        if used_calls + len(actual) > int(policy.get("model_call_budget") or 0):
            emit("deny", "Reviewer model-call budget reached; developer decision is required.", tool=name)
            return
        emit("allow", "Reviewer roster exactly matches the immutable adaptive policy.", tool=name)
    except Exception as exc:
        emit("deny", f"Reviewer policy validation failed closed: {exc}", tool=name)


def _handle_zoho_mutation(name: str, args: dict) -> None:
    try:
        plan = active_plan(REPO)
        status = str(plan.get("status") or "")
        approval = plan.get("approval") or {}
        authorized = (
            status in {"IMPLEMENTING", "READY_FOR_DELIVERY"}
            and plan.get("execution_nonce")
            and plan.get("execution_nonce") == approval.get("single_use_nonce")
            and "zoho_sprints" in set(plan.get("external_writes") or [])
        )
        if not authorized:
            emit("deny", "Zoho mutation is not included in the active approved plan.", tool=name)
            return
        operation_id = str(args.get("operation_id") or "").strip()
        if not operation_id:
            emit("deny", "Zoho mutations require a stable operation_id for idempotency.", tool=name)
            return
        requested_status = str(args.get("status") or "").strip().lower()
        if requested_status in {"done", "solved", "closed", "completed"}:
            emit("deny", "Terminal tracker states are developer-owned.", tool=name)
            return
        emit("allow", "Zoho mutation is plan-bound and idempotency-bound.", tool=name)
    except Exception as exc:
        emit("deny", f"Zoho mutation authorization failed closed: {exc}", tool=name)


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


def _handle_search(name: str, args: dict) -> None:
    if name == "grep_search":
        target = str(args.get("SearchPath") or args.get("searchPath") or "")
    else:
        target = str(args.get("SearchDirectory") or args.get("searchDirectory") or "")

    if _is_targeted_search_path(target):
        emit("allow", "Search is targeted to a specific file or feature directory.", tool=name)
        return

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
                for rec in reversed(records[-20:]):
                    if rec.get("tool") == "run_command" and "project_graph executed" in rec.get("reason", "").lower() and rec.get("decision") == "allow":
                        has_run_graph = True
                        break
        except Exception:
            has_run_graph = False

        if not has_run_graph:
            emit(
                "deny",
                "Unanchored repository-wide search is paused during initial discovery. "
                "Start by running 'python .agents/scripts/project_graph.py --feature <name>' or '--find <symbol>' "
                "to inspect the architectural slice, or specify a targeted SearchPath for literal text.",
                tool=name,
            )
            return

    emit("allow", "Search is permitted outside cascade limits.", tool=name)


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
                emit("deny", detail, tool=name)
                return
            if is_temp:
                emit("allow", "Temporary setup answers or IDE artifact write is allowed.", tool=name)
                return
            allowed, reason = file_mutation_allowed(REPO)
            emit("allow" if allowed else "deny", reason, tool=name)
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
        if name in ZOHO_MUTATION_TOOLS:
            _handle_zoho_mutation(name, args)
            return
        emit("allow", "Tool is outside the harness mutation boundary.", tool=name)
    except json.JSONDecodeError:
        emit("deny", "Safety hook received invalid JSON.")
    except Exception as exc:
        emit("deny", f"Safety hook failed closed ({type(exc).__name__}: {exc}).")


if __name__ == "__main__":
    main()
