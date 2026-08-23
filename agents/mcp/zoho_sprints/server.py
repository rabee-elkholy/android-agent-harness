"""Zoho Sprints MCP server (stdio JSON-RPC). Credentials stay in a user-level file."""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _config import ENV_CONFIG, resolve_config_path  # noqa: E402

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000200D"
    "\U00002B50\U00002B05-\U00002B07\U00002934-\U00002935"
    "\U000023CF\U000023E9-\U000023F3\U000023F8-\U000023FA"
    "]+",
    flags=re.UNICODE,
)


def _dns_query_fallback(hostname: str, dns_servers: tuple[str, ...] = ("8.8.8.8", "1.1.1.1")) -> Optional[str]:
    tx_id = secrets.randbelow(65535) + 1
    packet = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
    for part in hostname.split("."):
        packet += struct.pack("B", len(part)) + part.encode("ascii")
    packet += b"\x00\x00\x01\x00\x01"
    for dns_ip in dns_servers:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            sock.sendto(packet, (dns_ip, 53))
            data, _ = sock.recvfrom(1024)
            sock.close()
            if len(data) < 12:
                continue
            resp_tx_id = struct.unpack(">H", data[0:2])[0]
            if resp_tx_id != tx_id:
                continue
            idx = 12
            while idx < len(data) and data[idx] != 0:
                if (data[idx] & 0xC0) == 0xC0:
                    idx += 2
                    break
                idx += 1 + data[idx]
            else:
                idx += 5
            if idx > len(data):
                continue
            ancount = struct.unpack(">H", data[6:8])[0]
            for _ in range(ancount):
                if idx >= len(data):
                    break
                if (data[idx] & 0xC0) == 0xC0:
                    idx += 2
                else:
                    while idx < len(data) and data[idx] != 0:
                        idx += 1 + data[idx]
                    idx += 1
                if idx + 10 > len(data):
                    break
                rtype, _rclass, _ttl, rdlength = struct.unpack(">HHIH", data[idx : idx + 10])
                idx += 10
                if rtype == 1 and rdlength == 4 and idx + 4 <= len(data):
                    return socket.inet_ntoa(data[idx : idx + 4])
                idx += rdlength
        except Exception:
            continue
    return None


def apply_dns_fallback() -> None:
    orig = socket.getaddrinfo
    cache: dict[str, str] = {}

    def custom(host, port, family=0, type=0, proto=0, flags=0):
        if isinstance(host, str) and "zoho" in host.lower():
            if host not in cache:
                resolved = _dns_query_fallback(host)
                if resolved:
                    cache[host] = resolved
            if host in cache:
                return orig(cache[host], port, family, type, proto, flags)
        try:
            return orig(host, port, family, type, proto, flags)
        except Exception:
            resolved = _dns_query_fallback(host) if isinstance(host, str) else None
            if resolved:
                cache[host] = resolved
                return orig(resolved, port, family, type, proto, flags)
            raise

    socket.getaddrinfo = custom  # type: ignore[method-assign]


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def format_zoho_html(text: str) -> str:
    if not text:
        return text
    text = _strip_emoji(text)
    if not text:
        return text
    if text.strip().startswith("<div dir="):
        return text
    has_arabic = bool(re.search(r"[\u0600-\u06FF]", text))
    code_blocks: list[str] = []

    def _save_code_block(match: re.Match[str]) -> str:
        code_blocks.append(match.group(1))
        return f"___CODE_BLOCK_{len(code_blocks) - 1}___"

    text = re.sub(r"```(?:\w+)?\n?(.*?)```", _save_code_block, text, flags=re.DOTALL)
    html_parts: list[str] = []
    in_list = False
    list_type = "ul"

    def _format_inline(s: str) -> str:
        s = re.sub(
            r"`([^`]+)`",
            r'<code style="color: #ffffff; font-family: Consolas, Monaco, monospace; font-size: 0.95em; direction: ltr; display: inline-block; font-weight: bold;">\1</code>',
            s,
        )
        return re.sub(r"\*\*(.+?)\*\*", r'<strong style="color: #ffffff; font-weight: 700;">\1</strong>', s)

    for line in text.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            continue
        cb_match = re.match(r"^___CODE_BLOCK_(\d+)___$", stripped)
        if cb_match:
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            code_content = code_blocks[int(cb_match.group(1))].strip()
            code_content = code_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_parts.append(
                f'<pre style="color: #ffffff; font-family: Consolas, Monaco, monospace; font-size: 13px; direction: ltr; text-align: left; margin: 8px 0; overflow-x: auto;"><code>{code_content}</code></pre>'
            )
            continue
        if stripped in ("---", "***", "___"):
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            html_parts.append('<hr style="border: 0; border-top: 1px solid rgba(255, 255, 255, 0.2); margin: 14px 0;">')
            continue
        heading = None
        if stripped.startswith("# "):
            heading = (stripped[2:], "1.25em", "12px 0 10px 0")
        elif stripped.startswith("## "):
            heading = (stripped[3:], "1.1em", "12px 0 6px 0")
        elif stripped.startswith("### "):
            heading = (stripped[4:], "1.05em", "10px 0 4px 0")
        if heading:
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            title, size, margin = heading
            html_parts.append(
                f'<div style="font-size: {size}; font-weight: 700; color: #ffffff; margin: {margin};">{_format_inline(title)}</div>'
            )
            continue
        if re.match(r"^\d+\.\s+", stripped):
            if not in_list or list_type != "ol":
                if in_list:
                    html_parts.append(f"</{list_type}>")
                html_parts.append("<ol style='margin-right: 22px; padding-right: 0; margin-bottom: 10px; color: #ffffff;'>")
                in_list = True
                list_type = "ol"
            item_text = _format_inline(re.sub(r"^\d+\.\s+", "", stripped))
            html_parts.append(f"<li style='margin-bottom: 6px; color: #ffffff; font-size: 14px;'>{item_text}</li>")
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list or list_type != "ul":
                if in_list:
                    html_parts.append(f"</{list_type}>")
                html_parts.append("<ul style='margin-right: 22px; padding-right: 0; margin-bottom: 10px; color: #ffffff;'>")
                in_list = True
                list_type = "ul"
            html_parts.append(
                f"<li style='margin-bottom: 6px; color: #ffffff; font-size: 14px;'>{_format_inline(stripped[2:])}</li>"
            )
            continue
        if in_list:
            html_parts.append(f"</{list_type}>")
            in_list = False
        html_parts.append(f"<p style='margin: 6px 0; color: #ffffff; font-size: 14px;'>{_format_inline(stripped)}</p>")
    if in_list:
        html_parts.append(f"</{list_type}>")
    inner = "\n".join(html_parts)
    if has_arabic:
        return (
            '<div dir="rtl" style="text-align: right; direction: rtl; line-height: 1.85; '
            "font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Tahoma, Arial, sans-serif; "
            f'color: #ffffff; font-size: 14px;">\n{inner}\n</div>'
        )
    return inner


class ZohoSprintsAPI:
    METADATA_CACHE_TTL = 300

    def __init__(self, config_path: str):
        self.config_path = config_path
        self._meta_cache: dict[str, tuple[float, dict]] = {}
        self.base_url = "https://sprintsapi.zoho.com/zsapi"
        self.load_config()

    def load_config(self) -> None:
        with open(self.config_path, encoding="utf-8") as f:
            user = json.load(f)
        if not isinstance(user, dict):
            raise RuntimeError("Zoho Sprints config must be a JSON object.")
        defaults = _workflow_defaults()
        self.config = dict(user)
        for key in WORKFLOW_KEYS:
            if key not in user or user.get(key) in (None, "", []):
                if key in defaults:
                    self.config[key] = defaults[key]
        self.access_token = user.get("access_token")
        self.refresh_token = user.get("refresh_token")
        self.client_id = user.get("client_id")
        self.client_secret = user.get("client_secret")
        self.auth_domain = user.get("auth_domain") or "https://accounts.zoho.com"
        self.team_id = str(self.config.get("team_id") or "").strip()
        self.project_id = str(self.config.get("project_id") or "").strip()
        self.default_user_id = str(self.config.get("default_user_id") or "").strip()
        self.item_prefix = str(self.config.get("item_prefix") or "").strip()
        self.fallback_item_type_id = str(self.config.get("fallback_item_type_id") or "").strip()
        self.fallback_priority_id = str(self.config.get("fallback_priority_id") or "").strip()
        self.fallback_sprint_id = str(self.config.get("fallback_sprint_id") or "").strip()
        suffixes = self.config.get("title_strip_suffixes") or []
        self.title_strip_suffixes = [str(s) for s in suffixes if str(s).strip()]
        if not self.team_id or not self.project_id:
            raise RuntimeError("Zoho Sprints config needs team_id and project_id.")

    def save_config(self) -> None:
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if hasattr(os, "O_CREAT") and os.name != "nt":
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with open(fd, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=2)
            else:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=2)
        except Exception:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)

    def sanitize_task_name(self, name: str) -> str:
        cleaned = name.strip()
        for suffix in self.title_strip_suffixes:
            cleaned = re.sub(
                r"\s*[-–—]\s*" + re.escape(suffix) + r"\s*$",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()
        return cleaned

    def refresh_token_if_needed(self) -> None:
        url = f"{self.auth_domain}/oauth/v2/token"
        params = {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }
        encoded = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=encoded, method="POST")
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        if "access_token" in res:
            self.access_token = res["access_token"]
            self.config["access_token"] = self.access_token
            self.save_config()

    def _request(self, path: str, method: str = "GET", params: dict | None = None, data: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}"}
        encoded_data = None
        if data is not None:
            encoded_data = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_msg = exc.read().decode("utf-8")
            if exc.code == 401 or "Invalid oauthToken" in err_msg or "invalid_token" in err_msg:
                self.refresh_token_if_needed()
                headers["Authorization"] = f"Zoho-oauthtoken {self.access_token}"
                req2 = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
                with urllib.request.urlopen(req2) as resp2:
                    return json.loads(resp2.read().decode("utf-8"))
            raise RuntimeError(f"HTTP Error {exc.code}: {err_msg}") from exc

    def get_sprints(self) -> dict:
        return self._request(
            f"/team/{self.team_id}/projects/{self.project_id}/sprints/",
            params={"action": "data", "type": "[1,2,3,4]"},
        )

    def get_active_sprint_id(self) -> str:
        ids = self.get_sprints().get("sprintIds") or []
        if ids:
            return ids[0]
        if self.fallback_sprint_id:
            return self.fallback_sprint_id
        raise RuntimeError("No sprints found for this Zoho project.")

    def _cached_request(self, cache_key: str, path: str, params: dict | None = None) -> dict:
        cached = self._meta_cache.get(cache_key)
        if cached:
            ts, data = cached
            if time.time() - ts < self.METADATA_CACHE_TTL:
                return data
        result = self._request(path, params=params)
        self._meta_cache[cache_key] = (time.time(), result)
        return result

    def get_item_types(self) -> dict:
        return self._cached_request(
            "item_types",
            f"/team/{self.team_id}/projects/{self.project_id}/itemtype/",
            params={"action": "data"},
        )

    def get_statuses(self) -> dict:
        return self._cached_request(
            "statuses",
            f"/team/{self.team_id}/projects/{self.project_id}/itemstatus/",
            params={"action": "data"},
        )

    def get_priorities(self) -> dict:
        return self._cached_request(
            "priorities",
            f"/team/{self.team_id}/projects/{self.project_id}/priority/",
            params={"action": "data"},
        )

    def list_items(self, sprint_id: str) -> dict:
        return self._request(
            f"/team/{self.team_id}/projects/{self.project_id}/sprints/{sprint_id}/item/",
            params={"action": "sprintitems", "subitem": "true"},
        )

    def resolve_item(self, item_input: str, sprint_id: str | None = None) -> tuple[str, str]:
        raw_input = str(item_input).strip()
        match = re.search(r"(\d+)", raw_input)
        target_num = match.group(1) if match else raw_input
        sprint_ids = self.get_sprints().get("sprintIds") or []
        if len(raw_input) >= 15 and raw_input.isdigit():
            if sprint_id:
                return sprint_id, raw_input
            for sid in sprint_ids:
                try:
                    res = self.get_item_details(sid, raw_input)
                    if res.get("status") == "success":
                        return sid, raw_input
                except Exception:
                    continue
        search_sprints = [sprint_id] if sprint_id else sprint_ids
        prefix = self.item_prefix
        for sid in search_sprints:
            items_data = self.list_items(sid)
            item_prop = items_data.get("item_prop") or {}
            item_no_idx = item_prop.get("itemNo")
            item_jobj = items_data.get("itemJObj") or {}
            for iid, row in item_jobj.items():
                if iid == raw_input:
                    return sid, iid
                if item_no_idx is not None and len(row) > item_no_idx:
                    item_no = str(row[item_no_idx])
                    labels = {item_no, f"I{item_no}", target_num}
                    if prefix:
                        labels.add(f"{prefix}{item_no}")
                    if raw_input in labels or item_no == target_num:
                        return sid, iid
        raise RuntimeError(
            f"Item '{raw_input}' not found in {len(search_sprints)} sprint(s). "
            "Verify the task id or pass sprint_id."
        )

    def get_item_details(self, sprint_id: str | None = None, item_id: str | None = None) -> dict:
        if not sprint_id or (item_id and (not str(item_id).isdigit() or len(str(item_id)) < 15)):
            sprint_id, item_id = self.resolve_item(item_id or sprint_id or "", sprint_id)
        return self._request(
            f"/team/{self.team_id}/projects/{self.project_id}/sprints/{sprint_id}/item/{item_id}/",
            params={"action": "details"},
        )

    def create_item(
        self,
        sprint_id: str,
        name: str,
        item_type_id: str,
        priority_id: str,
        description: str = "",
        points: str = "0",
        parent_item_id: str | None = None,
        users: list | None = None,
    ) -> dict:
        data: dict[str, str] = {
            "name": self.sanitize_task_name(name),
            "projitemtypeid": item_type_id,
            "projpriorityid": priority_id,
            "description": format_zoho_html(description),
        }
        assigned = users if users is not None else ([self.default_user_id] if self.default_user_id else None)
        if assigned:
            data["users"] = json.dumps(assigned)
        if points and points != "0":
            data["points"] = points
        if parent_item_id:
            path = f"/team/{self.team_id}/projects/{self.project_id}/sprints/{sprint_id}/item/{parent_item_id}/subitem/"
        else:
            path = f"/team/{self.team_id}/projects/{self.project_id}/sprints/{sprint_id}/item/"
        return self._request(path, method="POST", data=data)

    def update_item_status(self, sprint_id: str, item_id: str, status_id: str) -> dict:
        return self._request(
            f"/team/{self.team_id}/projects/{self.project_id}/sprints/{sprint_id}/item/{item_id}/",
            method="POST",
            data={"statusid": status_id},
        )

    def update_item_description(self, sprint_id: str, item_id: str, description: str) -> dict:
        return self._request(
            f"/team/{self.team_id}/projects/{self.project_id}/sprints/{sprint_id}/item/{item_id}/",
            method="POST",
            data={"description": format_zoho_html(description)},
        )

    def add_comment(self, sprint_id: str, item_id: str, content: str) -> dict:
        return self._request(
            f"/team/{self.team_id}/projects/{self.project_id}/sprints/{sprint_id}/item/{item_id}/notes/",
            method="POST",
            data={"name": format_zoho_html(content)},
        )


_api: ZohoSprintsAPI | None = None
WORKFLOW_KEYS = (
    "team_id",
    "project_id",
    "default_user_id",
    "item_prefix",
    "title_strip_suffixes",
    "fallback_item_type_id",
    "fallback_priority_id",
    "fallback_sprint_id",
)


def _workflow_defaults() -> dict:
    path = HERE / "workflow_defaults.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}

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
