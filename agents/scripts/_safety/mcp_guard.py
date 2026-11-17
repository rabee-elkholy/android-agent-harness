"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


def validate_external_write(integration, tool_name: str, args: dict, plan: dict, *, grant=None) -> tuple[bool, str]:
    from integrations.base import validate_external_write as _vew
    return _vew(integration, tool_name, args, plan, grant=grant)
def _handle_external_mutation(integration, tool_name: str, args: dict, server: str = "") -> None:
    try:
        try:
            plan = _engine.active_plan(_engine.REPO) or {}
        except (OSError, ValueError, _engine.ValidationError):
            plan = {}
        if isinstance(plan, dict) and plan:
            plan = {**plan, "repo_root": str(_engine.REPO)}
            if not plan.get("repository"):
                plan["repository"] = str(_engine.REPO)
        elif not isinstance(plan, dict):
            plan = {}

        if integration.name == "universal_pm":
            from zoho_grant import active_pm_grant, pm_authorize_command
            from integrations.external_write_policy import sensitive_values
            secrets = sensitive_values([args])
            if secrets:
                _engine.emit(
                    "deny",
                    f"External PM operation '{tool_name}' would send a credential or signing file "
                    f"({', '.join(sorted(set(secrets)))}).",
                    tool=tool_name,
                    reason_code="SENSITIVE_EXTERNAL_UPLOAD",
                )
                return
            provider_id = integration.resolve_provider_id(server, tool_name)
            display = integration.resolve_display_name(server, tool_name)
            grant = active_pm_grant(_engine.REPO, provider=provider_id)
            ok, policy_reason = integration.validate_pm_mutation(server, tool_name, args, plan, grant=grant)
            if not ok:
                _engine.emit("deny", policy_reason, tool=tool_name, reason_code="PM_POLICY_VIOLATION")
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
                _engine.emit(
                    "allow",
                    f"{display} mutation '{tool_name}' is authorized by active PM grant/plan and complies with PM guardrails.",
                    tool=tool_name,
                    reason_code="PM_MUTATION_ALLOWED",
                )
                return
            _engine.emit(
                "deny",
                f"PM_PREVIEW_AND_APPROVAL_REQUIRED: Before calling '{tool_name}' on {display}, you MUST: "
                f"(1) present the exact preview of the tracker changes (target item ID, fields/status/comment to be written) "
                f"to the developer in chat and ask for their approval; "
                f"(2) once the developer confirms (e.g. 'update pm' / 'update tracker'), run "
                f"`{pm_authorize_command(provider_id.replace('_projects', '').replace('_sprints', ''))}` with their exact message; "
                f"then retry '{tool_name}'.",
                tool=tool_name,
                reason_code="PM_PREVIEW_AND_APPROVAL_REQUIRED",
            )
            return

        grant = None
        if integration.name == "zoho_sprints":
            from zoho_grant import active_grant
            grant = active_grant(_engine.REPO)
        if not plan and not grant:
            _engine.emit("deny", f"{integration.display_name} mutation is not included in the active approved plan.", tool=tool_name)
            return
        allowed, reason = _engine.validate_external_write(integration, tool_name, args, plan, grant=grant)
        if not allowed:
            _engine.emit("deny", reason, tool=tool_name)
            return
        _engine.emit("allow", f"{integration.display_name} mutation is plan-bound and idempotency-bound.", tool=tool_name)
    except Exception as exc:
        _engine.emit("deny", f"{integration.display_name} mutation authorization failed closed: {exc}", tool=tool_name)
def _handle_mcp_tool(name: str, args: dict) -> None:
    server = str(args.get("ServerName") or args.get("server_name") or args.get("server") or "").lower().strip()
    tool_name = str(args.get("ToolName") or args.get("tool_name") or args.get("tool") or "").strip()
    raw_tool_args = args.get("Arguments") or args.get("arguments") or args.get("args") or {}
    if isinstance(raw_tool_args, str):
        try:
            tool_args = _engine.json.loads(raw_tool_args)
        except Exception:
            tool_args = {}
    elif isinstance(raw_tool_args, dict):
        tool_args = raw_tool_args
    else:
        tool_args = {}

    # 1. Query specialized integration registry (e.g. Zoho Sprints & Universal PM MCPs)
    integration = _engine._get_registry().resolve(server, tool_name)
    if integration is not None:
        if integration.is_read_only(tool_name, tool_args):
            disp = integration.resolve_display_name(server, tool_name) if hasattr(integration, "resolve_display_name") else integration.display_name
            _engine.emit("allow", f"Read-only {disp} inspection is allowed.", tool=name, reason_code="READ_ALLOWED")
            return
        _engine._handle_external_mutation(integration, tool_name, tool_args, server=server)
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
        _engine.emit("allow", f"Read-only MCP tool execution '{tool_name}' on server '{server}' is allowed.", tool=name, reason_code="MCP_READ_ALLOWED")
        return

    # WRITE, HIGH_IMPACT and UNKNOWN calls never carry a credential or signing file off the machine.
    secrets = sensitive_values([tool_args, raw_tool_args])
    if secrets:
        _engine.emit(
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
        plan = _engine.active_plan(_engine.REPO) or {}
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
        _engine.emit(decision, prompt_reason, tool=name, reason_code=reason_code, task_id=task_id, mcp_fingerprint=fingerprint)
        return

    _engine.emit(
        "allow",
        f"Generic MCP mutation '{tool_name}' on server '{server}' is authorized.",
        tool=name,
        reason_code=reason_code,
        task_id=task_id,
        mcp_fingerprint=fingerprint,
    )
