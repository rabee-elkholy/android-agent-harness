"""Authoritative tool vocabulary for Google Antigravity and the Android Agent Harness."""
from __future__ import annotations

ANTIGRAVITY_TOOLS = frozenset({
    "run_command",
    "manage_task",
    "schedule",
    "view_file",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "list_dir",
    "find_by_name",
    "grep_search",
    "invoke_subagent",
    "define_subagent",
    "send_message",
    "manage_subagents",
    "ask_question",
    "read_url_content",
    "search_web",
    "read_resource",
    "list_resources",
    "generate_image",
    "call_mcp_tool",
})

MUTATION_TOOLS = frozenset({
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "apply_patch",
    "edit",
    "multiedit",
    "create_file",
    "delete_file",
    "move_file",
    "rename_file",
})

READ_ONLY_TOOLS = frozenset({
    "view_file",
    "list_dir",
    "find_by_name",
    "grep_search",
    "read_url_content",
    "search_web",
    "read_resource",
    "list_resources",
    "ask_question",
    "generate_image",
})

SUBAGENT_ORCHESTRATION_TOOLS = frozenset({
    "invoke_subagent",
    "send_message",
    "define_subagent",
    "manage_subagents",
    "manage_task",
    "schedule",
})
