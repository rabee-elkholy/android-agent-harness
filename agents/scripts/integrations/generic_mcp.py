"""Generic MCP server authorization, classification, and auditing."""
from __future__ import annotations

import re
from typing import Any, Mapping

from _vnext_common import ValidationError, canonical_sha256

READ = "READ"
WRITE = "WRITE"
HIGH_IMPACT = "HIGH_IMPACT"
UNKNOWN = "UNKNOWN"

READ_PREFIXES = (
    "get_", "list_", "read_", "fetch_", "search_", "find_",
    "query_", "inspect_", "describe_", "show_", "lookup_",
    "api-get-", "api-retrieve-", "api-query-", "developerknowledge_",
)

READ_ACTIONS = frozenset({
    "get", "list", "read", "fetch", "search", "find",
    "query", "inspect", "describe", "show", "lookup", "retrieve", "answer",
})

WRITE_ACTIONS = frozenset({
    "create", "update", "edit", "write", "set", "add",
    "comment", "rename", "move", "copy", "upload",
    "patch", "post", "put", "assign",
})

HIGH_IMPACT_ACTIONS = frozenset({
    "delete", "remove", "drop", "destroy",
    "deploy", "publish", "revoke", "disable",
    "rotate", "truncate", "purge",
})

SENSITIVE_TARGETS = frozenset({
    "production", "prod",
    "security", "rule", "rules",
    "permission", "permissions",
    "auth",
})


def normalize_mcp_server(server: str) -> str:
    value = str(server or "").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value).strip("-")
    if not value:
        raise ValidationError("MCP server identity is empty")
    return value[:64]


def classify_generic_mcp_tool(tool_name: str) -> str:
    """Classify generic MCP tool into READ, WRITE, HIGH_IMPACT, or UNKNOWN.

    Action-aware classification order:
    1. destructive/deploy/publish action token -> HIGH_IMPACT
    2. known read prefix/action and no write action -> READ
    3. write action + sensitive target -> HIGH_IMPACT
    4. normal write action -> WRITE
    5. otherwise -> UNKNOWN (fail closed)
    """
    t_lower = str(tool_name or "").lower().strip()
    if not t_lower:
        return UNKNOWN

    tokens = [t for t in re.split(r"[_\-.:]+", t_lower) if t]
    token_set = set(tokens)

    # 1. destructive/deploy/publish action token -> HIGH_IMPACT
    if bool(token_set & HIGH_IMPACT_ACTIONS):
        return HIGH_IMPACT

    # 2. known read prefix / action and no write action -> READ
    has_read = any(t_lower.startswith(p) for p in READ_PREFIXES) or bool(token_set & READ_ACTIONS)
    has_write = bool(token_set & WRITE_ACTIONS)
    if has_read and not has_write:
        return READ

    # 3. write action + sensitive target -> HIGH_IMPACT
    if has_write and bool(token_set & SENSITIVE_TARGETS):
        return HIGH_IMPACT

    # 4. normal write action -> WRITE
    if has_write:
        return WRITE

    # 5. otherwise -> UNKNOWN (fail closed)
    return UNKNOWN


def validate_generic_mcp_mutation(
    *,
    server: str,
    tool_name: str,
    plan: Mapping[str, Any],
) -> tuple[bool, str, str]:
    """Validate generic MCP tool invocation against active approved plan.

    Returns:
        (allowed: bool, reason: str, reason_code: str)
    """
    try:
        norm_server = normalize_mcp_server(server)
    except Exception as exc:
        return False, f"Invalid MCP server identity: {exc}", "INVALID_SERVER"

    tool_class = classify_generic_mcp_tool(tool_name)

    # READ: allowed without external-write scope
    if tool_class == READ:
        return True, f"Read-only MCP tool execution '{tool_name}' on server '{norm_server}' is allowed.", "READ_ALLOWED"

    # UNKNOWN: fail closed
    if tool_class == UNKNOWN:
        return False, f"External MCP operation '{tool_name}' on server '{norm_server}' cannot be classified safely and is denied.", "UNKNOWN_MCP_TOOL"

    # For WRITE and HIGH_IMPACT:
    status = str(plan.get("status") or "")
    approval = plan.get("approval") or {}
    execution_nonce = plan.get("execution_nonce")
    single_use_nonce = approval.get("single_use_nonce") if isinstance(approval, dict) else None
    external_writes = set(plan.get("external_writes") or [])

    authorized_lifecycle = (
        status in {"IMPLEMENTING", "READY_FOR_DELIVERY"}
        and execution_nonce
        and execution_nonce == single_use_nonce
    )
    if not authorized_lifecycle:
        return False, "EXTERNAL_WRITE_SCOPE_REQUIRED: MCP mutation is not authorized by active approved plan.", "PLAN_NOT_APPROVED"

    if tool_class == HIGH_IMPACT:
        required_scope = f"mcp:{norm_server}:high-impact"
        if required_scope not in external_writes:
            msg = (
                f"EXTERNAL_HIGH_IMPACT_SCOPE_REQUIRED: revise with --external-write {required_scope} "
                "and obtain developer approval."
            )
            return False, msg, "EXTERNAL_HIGH_IMPACT_SCOPE_REQUIRED"
        return True, f"High-impact MCP mutation '{tool_name}' on server '{norm_server}' authorized.", "MUTATION_ALLOWED"

    # tool_class == WRITE
    required_scope = f"mcp:{norm_server}"
    required_hi = f"mcp:{norm_server}:high-impact"
    if required_scope not in external_writes and required_hi not in external_writes:
        msg = (
            f"EXTERNAL_WRITE_SCOPE_REQUIRED: revise the plan with --external-write {required_scope} "
            "and obtain developer approval."
        )
        return False, msg, "EXTERNAL_WRITE_SCOPE_REQUIRED"
    return True, f"MCP mutation '{tool_name}' on server '{norm_server}' authorized.", "MUTATION_ALLOWED"


def compute_generic_mcp_fingerprint(
    *,
    task_id: str,
    plan_sha256: str,
    server: str,
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
) -> str:
    norm_server = normalize_mcp_server(server)
    args_dict = dict(arguments or {})
    redacted: dict[str, Any] = {}
    for k, v in args_dict.items():
        if any(secret_kw in str(k).lower() for secret_kw in ("key", "token", "secret", "password", "auth", "credential")):
            redacted[str(k)] = "[REDACTED]"
        else:
            redacted[str(k)] = v
    return canonical_sha256({
        "task_id": str(task_id or ""),
        "plan_sha256": str(plan_sha256 or ""),
        "server": norm_server,
        "tool_name": str(tool_name or ""),
        "arguments": redacted,
    })
