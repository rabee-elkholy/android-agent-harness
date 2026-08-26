"""Zoho Sprints MCP server (stdio JSON-RPC). Credentials stay in a user-level file."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _client import WORKFLOW_KEYS, ZohoSprintsAPI, _workflow_defaults  # noqa: E402
from _config import ENV_CONFIG, resolve_config_path  # noqa: E402
from _dns import _dns_query_fallback, apply_dns_fallback  # noqa: E402
from _formatter import _EMOJI_RE, _strip_emoji, format_zoho_html  # noqa: E402

_api: ZohoSprintsAPI | None = None

TOOLS = [
    {
        "name": "zoho_list_sprints",
        "description": "List all sprints in the Zoho Sprints project with their IDs, names, dates, and status.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "zoho_list_tasks",
        "description": "List tasks/items in a sprint. Defaults to the current sprint if sprint_id is omitted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sprint_id": {"type": "string", "description": "Sprint ID. If omitted, the current active sprint is used."},
                "user_name": {"type": "string", "description": "Optional assignee name filter."},
                "status": {"type": "string", "description": "Optional status filter (e.g. In progress, To do)."},
            },
        },
    },
    {
        "name": "zoho_get_task_details",
        "description": "Get detailed information about a specific task/item.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sprint_id": {"type": "string", "description": "Sprint ID containing the item."},
                "item_id": {"type": "string", "description": "Task/item ID or display number."},
            },
            "required": ["sprint_id", "item_id"],
        },
    },
    {
        "name": "zoho_create_task",
        "description": "Create a new task, story, or bug in a sprint in Zoho Sprints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sprint_id": {"type": "string", "description": "Sprint ID where the item should be created."},
                "name": {"type": "string", "description": "Title of the task."},
                "type": {"type": "string", "enum": ["Task", "Bug", "Story"], "description": "Item type. Default Task."},
                "priority": {
                    "type": "string",
                    "enum": ["Low", "Medium", "High", "None"],
                    "description": "Priority. Default Medium.",
                },
                "description": {"type": "string", "description": "Optional task description."},
                "points": {"type": "string", "description": "Story points (default 0)."},
                "parent_item_id": {"type": "string", "description": "Optional parent item ID for a sub-item."},
            },
            "required": ["sprint_id", "name"],
        },
    },
    {
        "name": "zoho_update_task_status",
        "description": "Update the status of an existing task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sprint_id": {"type": "string", "description": "Sprint ID containing the task."},
                "item_id": {"type": "string", "description": "Task/item ID."},
                "status": {
                    "type": "string",
                    "enum": ["To do", "In progress", "Ready To ReTest", "Solved", "Done", "Re Opened"],
                    "description": "The target status.",
                },
            },
            "required": ["sprint_id", "item_id", "status"],
        },
    },
    {
        "name": "zoho_add_comment",
        "description": "Add a note or comment to a task in Zoho Sprints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sprint_id": {"type": "string", "description": "Sprint ID containing the task."},
                "item_id": {"type": "string", "description": "Task/item ID."},
                "comment": {"type": "string", "description": "Content of the comment/note."},
            },
            "required": ["sprint_id", "item_id", "comment"],
        },
    },
    {
        "name": "zoho_update_task_description",
        "description": "Update or set the description of an existing task in Zoho Sprints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sprint_id": {"type": "string", "description": "Sprint ID containing the task."},
                "item_id": {"type": "string", "description": "Task/item ID."},
                "description": {"type": "string", "description": "The new description text."},
            },
            "required": ["sprint_id", "item_id", "description"],
        },
    },
]


def get_api() -> ZohoSprintsAPI:
    global _api
    if _api is None:
        path = resolve_config_path()
        if path is None:
            raise RuntimeError(
                "Zoho Sprints config not found. Copy "
                "`.agents/mcp/zoho_sprints/config.example.json` to "
                "`~/.android-harness/zoho_sprints.json` and fill team_id, project_id, "
                "and OAuth fields. Never put tokens in the repo. "
                f"You can also set {ENV_CONFIG} to an existing config file."
            )
        _api = ZohoSprintsAPI(str(path))
    return _api


def _lookup_maps(api: ZohoSprintsAPI) -> tuple[dict, dict, dict, dict, dict, dict]:
    statuses_data = api.get_statuses()
    status_id_by_name: dict[str, str] = {}
    status_name_by_id: dict[str, str] = {}
    if "statusJObj" in statuses_data:
        for sid, sval in statuses_data["statusJObj"].items():
            status_name_by_id[sid] = sval[0]
            status_id_by_name[sval[0].lower()] = sid
    types_data = api.get_item_types()
    type_id_by_name: dict[str, str] = {}
    type_name_by_id: dict[str, str] = {}
    if "projItemTypeJObj" in types_data:
        for tid, tval in types_data["projItemTypeJObj"].items():
            type_name_by_id[tid] = tval[1]
            type_id_by_name[tval[1].lower()] = tid
    priorities_data = api.get_priorities()
    prio_id_by_name: dict[str, str] = {}
    prio_name_by_id: dict[str, str] = {}
    if "projPriorityJObj" in priorities_data:
        for pid, pval in priorities_data["projPriorityJObj"].items():
            prio_name_by_id[pid] = pval[0]
            prio_id_by_name[pval[0].lower()] = pid
    return status_id_by_name, status_name_by_id, type_id_by_name, type_name_by_id, prio_id_by_name, prio_name_by_id


def handle_call_tool(name: str, arguments: dict) -> dict:
    api = get_api()
    status_id_by_name, status_name_by_id, type_id_by_name, type_name_by_id, prio_id_by_name, prio_name_by_id = _lookup_maps(api)

    if name == "zoho_list_sprints":
        res = api.get_sprints()
        sprint_ids = res.get("sprintIds") or []
        sprint_jobj = res.get("sprintJObj") or {}
        sprints_list = []
        for sid in sprint_ids:
            info = sprint_jobj.get(sid) or []
            sprints_list.append(
                {
                    "sprint_id": sid,
                    "name": info[0] if len(info) > 0 else "",
                    "start_date": info[1] if len(info) > 1 else "",
                    "end_date": info[2] if len(info) > 2 else "",
                    "status_code": info[5] if len(info) > 5 else "",
                    "sequence": info[10] if len(info) > 10 else "",
                }
            )
        return {"content": [{"type": "text", "text": json.dumps(sprints_list, ensure_ascii=False, indent=2)}]}

    if name == "zoho_list_tasks":
        sprint_id = arguments.get("sprint_id") or api.get_active_sprint_id()
        items_data = api.list_items(sprint_id)
        user_display = items_data.get("userDisplayName") or {}
        item_prop = items_data.get("item_prop") or {}
        name_idx = item_prop.get("itemName", 0)
        item_no_idx = item_prop.get("itemNo", 3)
        status_idx = item_prop.get("statusId", 33)
        type_idx = item_prop.get("projItemTypeId", 34)
        prio_idx = item_prop.get("projPriorityId", 35)
        owner_idx = item_prop.get("ownerId", 37)
        item_jobj = items_data.get("itemJObj") or {}
        item_ids = items_data.get("itemIds") or []
        user_filter = str(arguments.get("user_name") or "").strip().lower()
        status_filter = str(arguments.get("status") or "").strip().lower()
        tasks = []
        prefix = api.item_prefix
        for item_id in item_ids:
            row = item_jobj.get(item_id)
            if not row:
                continue
            t_name = row[name_idx] if len(row) > name_idx else "Unknown"
            item_no = row[item_no_idx] if len(row) > item_no_idx else ""
            s_id = str(row[status_idx]) if len(row) > status_idx else ""
            t_id = str(row[type_idx]) if len(row) > type_idx else ""
            p_id = str(row[prio_idx]) if len(row) > prio_idx else ""
            owner_names = []
            if len(row) > owner_idx and isinstance(row[owner_idx], list):
                owner_names = [user_display.get(str(oid), str(oid)) for oid in row[owner_idx]]
            elif len(row) > owner_idx:
                owner_names = [user_display.get(str(row[owner_idx]), str(row[owner_idx]))]
            st_name = status_name_by_id.get(s_id, s_id)
            if user_filter and not any(user_filter in o.lower() for o in owner_names):
                continue
            if status_filter and status_filter != st_name.lower():
                continue
            display_no = f"{prefix}{item_no}" if prefix and item_no else (f"I{item_no}" if item_no else item_id)
            tasks.append(
                {
                    "id": item_id,
                    "item_no": display_no,
                    "name": t_name,
                    "status": st_name,
                    "type": type_name_by_id.get(t_id, t_id),
                    "priority": prio_name_by_id.get(p_id, p_id),
                    "assigned_to": owner_names,
                }
            )
        return {"content": [{"type": "text", "text": json.dumps(tasks, ensure_ascii=False, indent=2)}]}

    if name == "zoho_get_task_details":
        sprint_id, item_id = api.resolve_item(arguments.get("item_id"), arguments.get("sprint_id"))
        res = api.get_item_details(sprint_id, item_id)
        return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]}

    if name == "zoho_create_task":
        sprint_id = arguments.get("sprint_id")
        parent_item_id = arguments.get("parent_item_id")
        if parent_item_id:
            sprint_id, parent_item_id = api.resolve_item(parent_item_id, sprint_id)
        if not sprint_id:
            sprint_id = api.get_active_sprint_id()
        task_type = str(arguments.get("type") or "Task")
        task_prio = str(arguments.get("priority") or "Medium")
        type_id = type_id_by_name.get(task_type.lower()) or api.fallback_item_type_id
        prio_id = prio_id_by_name.get(task_prio.lower()) or api.fallback_priority_id
        if not type_id:
            raise RuntimeError(f"Unknown item type: {task_type}. Allowed: {sorted(type_id_by_name)}")
        if not prio_id:
            raise RuntimeError(f"Unknown priority: {task_prio}. Allowed: {sorted(prio_id_by_name)}")
        res = api.create_item(
            sprint_id,
            arguments["name"],
            type_id,
            prio_id,
            arguments.get("description") or "",
            str(arguments.get("points") or "0"),
            parent_item_id=parent_item_id,
        )
        return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]}

    if name == "zoho_update_task_status":
        sprint_id, item_id = api.resolve_item(arguments["item_id"], arguments.get("sprint_id"))
        target_status = arguments["status"]
        status_id = status_id_by_name.get(str(target_status).lower())
        if not status_id:
            raise RuntimeError(f"Unknown status: {target_status}. Allowed: {sorted(status_id_by_name)}")
        res = api.update_item_status(sprint_id, item_id, status_id)
        return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]}

    if name == "zoho_add_comment":
        sprint_id, item_id = api.resolve_item(arguments["item_id"], arguments.get("sprint_id"))
        res = api.add_comment(sprint_id, item_id, arguments["comment"])
        return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]}

    if name == "zoho_update_task_description":
        sprint_id, item_id = api.resolve_item(arguments["item_id"], arguments.get("sprint_id"))
        res = api.update_item_description(sprint_id, item_id, arguments["description"])
        return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]}

    raise RuntimeError(f"Unknown tool: {name}")


def _write(resp: dict) -> None:
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    apply_dns_fallback()
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            if method == "initialize":
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "zoho-sprints-mcp", "version": "1.0.0"},
                        },
                    }
                )
            elif method == "notifications/initialized":
                pass
            elif method == "ping":
                _write({"jsonrpc": "2.0", "id": req_id, "result": {}})
            elif method == "tools/list":
                _write({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
            elif method == "tools/call":
                params = req.get("params") or {}
                try:
                    result = handle_call_tool(params.get("name"), params.get("arguments") or {})
                    _write({"jsonrpc": "2.0", "id": req_id, "result": result})
                except Exception as exc:
                    _write(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [{"type": "text", "text": f"Error: {exc}"}],
                                "isError": True,
                            },
                        }
                    )
            elif req_id is not None:
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Method not found: {method}"},
                    }
                )
        except Exception as exc:
            _write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}})


if __name__ == "__main__":
    main()
