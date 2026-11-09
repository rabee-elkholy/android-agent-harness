"""Universal Multi-Provider PM MCP Integration for Antigravity.

Applies unified harness PM guardrails across all installed PM MCP servers
(Zoho Projects, Jira/Atlassian, Linear, Monday.com, GitHub Projects, ClickUp,
Asana, Trello, and any schema-discovered PM MCP in Antigravity):
- Immediate read access for all query/get/list/search tools.
- Bug/Issue description preservation (delivery reports must be posted as comments).
- Terminal status protection (Done/Closed/Solved blocked unless the developer
  explicitly ordered closing the task in their grant message).
- Seamless authorization via `python .agents/harness.py pm authorize --proof-reference "..."`
  (`update pm` / `حدث التاسك` / `update zoho` / `update jira` / etc.) or plan `external_writes`.
"""
from __future__ import annotations

import re

from typing import Any, Mapping
from integrations.base import ExternalIntegration
from pm_discovery import BUILTIN_PM_CATALOG, classify_pm_tool, identify_pm_provider, unwrap_zoho_mcp_execute

TERMINAL_STATUS_VALUES = frozenset({
    "done", "closed", "solved", "completed", "resolved", "shipped", "archived",
})


class UniversalPmIntegration(ExternalIntegration):
    """Dynamic PM integration covering all PM MCP providers (including official Zoho Sprints MCP)."""

    name = "universal_pm"
    display_name = "Project Tracker (PM MCP)"

    def matches(self, server: str, tool_name: str) -> bool:
        provider = identify_pm_provider(server, tool_name)
        if not provider:
            return False
        if provider == "zoho_sprints":
            server_lower = (server or "").lower().strip()
            tool_lower = (tool_name or "").lower().strip()
            if (
                "zoho-sprints_mcp" in server_lower
                or "zoho_sprints_mcp" in server_lower
                or tool_lower.startswith("zohomcp_")
                or tool_lower.startswith("zohosprints_")
            ):
                return True
            return False
        return True

    def owns_tool(self, tool_name: str, args: Mapping[str, Any] | None = None) -> bool:
        args_map = dict(args or {})
        if str(tool_name or "").strip().lower() in ("call_mcp_tool", "mcp_tool"):
            srv = str(args_map.get("ServerName") or args_map.get("server_name") or args_map.get("server") or "")
            tl = str(args_map.get("ToolName") or args_map.get("tool_name") or args_map.get("tool") or "")
            return self.matches(srv, tl)
        return self.matches("", tool_name)

    def resolve_provider_id(self, server: str, tool_name: str) -> str:
        return identify_pm_provider(server, tool_name) or "universal_pm"

    def resolve_display_name(self, server: str, tool_name: str) -> str:
        pid = self.resolve_provider_id(server, tool_name)
        meta = BUILTIN_PM_CATALOG.get(pid)
        if meta:
            return str(meta.get("display") or self.display_name)
        if pid.startswith("custom:"):
            return f"PM MCP ({pid.split(':', 1)[1]})"
        return self.display_name

    def is_read_only(self, tool_name: str, args: Mapping[str, Any] | None = None) -> bool:
        args_map = dict(args or {})
        if str(tool_name or "").strip().lower() in ("call_mcp_tool", "mcp_tool"):
            tl = str(args_map.get("ToolName") or args_map.get("tool_name") or args_map.get("tool") or "")
            nested = args_map.get("Arguments") or args_map.get("arguments") or args_map.get("args") or {}
            nested_map = dict(nested) if isinstance(nested, Mapping) else {}
            return classify_pm_tool(tl, nested_map) == "READ"
        return classify_pm_tool(tool_name, args_map) == "READ"

    def validate_mutation(
        self,
        tool_name: str,
        args: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> tuple[bool, str]:
        args_map = dict(args or {})
        srv = ""
        tl = tool_name
        inner_args: Mapping[str, Any] = args_map
        if str(tool_name or "").strip().lower() in ("call_mcp_tool", "mcp_tool"):
            srv = str(args_map.get("ServerName") or args_map.get("server_name") or args_map.get("server") or "")
            tl = str(args_map.get("ToolName") or args_map.get("tool_name") or args_map.get("tool") or "")
            nested = args_map.get("Arguments") or args_map.get("arguments") or args_map.get("args") or {}
            if isinstance(nested, Mapping):
                inner_args = nested
        grant = None
        repo_cand = (plan.get("repo_root") or plan.get("repository")) if isinstance(plan, Mapping) else None
        if isinstance(repo_cand, Mapping):
            repo_cand = None
        if not repo_cand:
            try:
                from _repo_files import REPO
                repo_cand = str(REPO)
            except (ImportError, OSError):
                repo_cand = None
        if repo_cand:
            from pathlib import Path
            from zoho_grant import active_pm_grant
            pid = self.resolve_provider_id(srv, tl)
            grant = active_pm_grant(Path(str(repo_cand)), provider=pid)
        return self.validate_pm_mutation(srv, tl, inner_args, plan, grant=grant)

    def validate_pm_mutation(
        self,
        server: str,
        tool_name: str,
        args: Mapping[str, Any],
        plan: Mapping[str, Any],
        grant: Mapping[str, Any] | None = None,
    ) -> tuple[bool, str]:
        unwrapped_tool, args = unwrap_zoho_mcp_execute(tool_name, args)
        tl = str(unwrapped_tool or "").strip().lower()
        tool_class = classify_pm_tool(unwrapped_tool, args)
        allow_close = bool(grant and grant.get("allow_close"))

        # 1. Terminal Status Protection (Done / Closed / Solved / Resolved)
        status_candidates = []
        fields_obj = args.get("fields")

        # Names supplied alongside an ID are not trusted provider metadata. An
        # opaque target needs explicit close authority until the adapter can
        # establish its nonterminal meaning from authoritative provider state.
        opaque = False
        for container in (args, fields_obj if isinstance(fields_obj, Mapping) else {}):
            for key, value in container.items():
                normalized = str(key).replace("_", "").lower()
                if normalized in {"statusid", "stateid", "transitionid"}:
                    opaque = True
                elif normalized in {"status", "state", "transition", "statusname", "statename", "transitionname"}:
                    if isinstance(value, Mapping):
                        if isinstance(value.get("name"), str):
                            status_candidates.append(value["name"].strip().lower())
                        if "id" in value or not isinstance(value.get("name"), str):
                            opaque = True
                    elif isinstance(value, str):
                        status_candidates.append(value.strip().lower())
                        if not value.strip() or value.strip().isdigit() or re.fullmatch(r"[0-9a-fA-F-]{32,36}", value.strip()):
                            opaque = True
                    else:
                        opaque = True
        if not allow_close and (opaque or (tool_class == "UPDATE_STATUS" and not status_candidates)):
            return False, ("PM_STATUS_UNVERIFIED: The target status/transition is opaque. "
                           "Use a supported named nonterminal status or obtain explicit developer close authority; "
                           "a caller-supplied name alongside an ID does not prove its meaning.")

        for st in status_candidates:
            if st in TERMINAL_STATUS_VALUES and not allow_close:
                return (
                    False,
                    "PM_POLICY_VIOLATION: Terminal tracker states (Done/Closed/Solved/Resolved) are developer/QA-owned "
                    "and cannot be set automatically. Move the item to 'Ready To ReTest' / 'In Review' / 'Ready for Testing', "
                    "or if the developer explicitly ordered closing the task, authorize with their message (`close task` / `اقفل التاسك`).",
                )

        # 2. Bug / Issue Description Protection
        z_link = plan.get("zoho_link") if isinstance(plan, Mapping) and isinstance(plan.get("zoho_link"), Mapping) else {}
        pm_link = plan.get("pm_link") if isinstance(plan, Mapping) and isinstance(plan.get("pm_link"), Mapping) else {}
        item_type = str(
            args.get("item_type")
            or args.get("type")
            or args.get("issue_type")
            or args.get("issuetype")
            or z_link.get("item_type")
            or pm_link.get("item_type")
            or ""
        ).strip().lower()
        if isinstance(fields_obj, Mapping) and not item_type:
            it_obj = fields_obj.get("issuetype")
            if isinstance(it_obj, Mapping):
                item_type = str(it_obj.get("name") or "").strip().lower()

        is_bug_update = (
            tl in ("zohoprojects_update_issue", "update_issue", "update_bug")
            or ("issue" in tl and any(verb in tl for verb in ("update", "edit"))
                and "create" not in tl and "comment" not in tl)
            or (item_type in ("bug", "defect", "issue") and tool_class in ("UPDATE_DESCRIPTION", "WRITE") and "create" not in tl and "comment" not in tl)
        )
        has_desc_override = (
            "description" in args
            or (isinstance(fields_obj, Mapping) and "description" in fields_obj)
        )
        if is_bug_update and has_desc_override:
            return (
                False,
                "PM_POLICY_VIOLATION: Editing a Bug/Issue description is strictly prohibited to preserve the original QA bug report. "
                "Post the delivery report as a Comment instead (e.g., ZohoProjects_add_issue_comments / addCommentToJiraIssue).",
            )

        # 3. Permanent deletion guard (prefer trash over permanent delete)
        if tool_class == "DELETE" and "delete" in tl and "trash" not in tl and "comment" not in tl and not allow_close:
            return (
                False,
                "PM_POLICY_VIOLATION: Permanent deletion of tracker records is blocked by default. "
                "Prefer moving records to trash or obtain an explicit developer close/delete order.",
            )

        # 4. Enforce project-notes.md 5-section Arabic HTML & No-Code-Leak rules when creating/updating descriptions
        from integrations.zoho_sprints.integration import ZohoSprintsIntegration
        ok_notes, reason_notes = ZohoSprintsIntegration._validate_project_notes_zoho_rules(tl, args, plan, item_type)
        if not ok_notes:
            return False, reason_notes

        return True, ""
