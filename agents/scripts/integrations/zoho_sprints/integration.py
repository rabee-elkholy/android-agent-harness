"""Zoho Sprints external integration implementation."""
from __future__ import annotations

from typing import Any, Mapping
from integrations.base import ExternalIntegration

ZOHO_MUTATION_TOOLS = frozenset({
    "zoho_create_task",
    "zoho_update_task_status",
    "zoho_add_comment",
    "zoho_update_task_description",
})

ZOHO_READ_TOOLS = frozenset({
    "zoho_list_sprints",
    "zoho_list_tasks",
    "zoho_get_task_details",
    "zoho_list_task_attachments",
})

ZOHO_MUTATION_VERBS = ("create", "update", "delete", "close", "add_comment")


class ZohoSprintsIntegration(ExternalIntegration):
    """ExternalIntegration implementation for Zoho Sprints."""

    name = "zoho_sprints"
    display_name = "Zoho"

    def matches(self, server: str, tool_name: str) -> bool:
        server_lower = (server or "").lower().strip()
        tool_lower = (tool_name or "").lower().strip()
        if "zoho" in server_lower or "zoho" in tool_lower:
            return True
        if tool_lower in ZOHO_MUTATION_TOOLS or tool_lower in ZOHO_READ_TOOLS:
            return True
        return False

    def is_read_only(self, tool_name: str, args: Mapping[str, Any]) -> bool:
        tool_lower = (tool_name or "").lower().strip()
        if tool_lower in ZOHO_READ_TOOLS:
            return True
        if tool_lower in ZOHO_MUTATION_TOOLS:
            return False
        if any(verb in tool_lower for verb in ZOHO_MUTATION_VERBS):
            return False
        return True

    def validate_mutation(
        self,
        tool_name: str,
        args: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> tuple[bool, str]:
        return True, ""
