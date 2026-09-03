"""Zoho Sprints API client, OAuth authentication, caching and endpoints."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from _formatter import format_zoho_html

HERE = Path(__file__).resolve().parent

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
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"Zoho OAuth token refresh network error: {e}") from e
        if "access_token" in res:
            self.access_token = res["access_token"]
            self.config["access_token"] = self.access_token
            self.save_config()
        else:
            err = res.get("error", "unknown_oauth_error")
            raise RuntimeError(f"Zoho OAuth token refresh failed: {err}. Re-authenticate in config.")

    def _request(self, path: str, method: str = "GET", params: dict | None = None, data: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}"}
        encoded_data = None
        if data is not None:
            encoded_data = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        max_retries = 3
        for attempt in range(max_retries):
            req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                err_msg = exc.read().decode("utf-8", errors="replace")
                if exc.code in (429, 502, 503, 504) and attempt < max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                if exc.code == 401 or "Invalid oauthToken" in err_msg or "invalid_token" in err_msg:
                    self.refresh_token_if_needed()
                    headers["Authorization"] = f"Zoho-oauthtoken {self.access_token}"
                    req2 = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
                    try:
                        with urllib.request.urlopen(req2, timeout=30.0) as resp2:
                            return json.loads(resp2.read().decode("utf-8"))
                    except Exception as retry_exc:
                        raise RuntimeError(f"Zoho request failed after token refresh: {retry_exc}") from retry_exc
                raise RuntimeError(f"HTTP Error {exc.code}: {err_msg}") from exc
            except Exception as exc:
                if attempt < max_retries - 1 and isinstance(exc, (urllib.error.URLError, TimeoutError)):
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise RuntimeError(f"Zoho request failed ({method} {path}): {exc}") from exc

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

    def get_backlog_id(self) -> str:
        try:
            res = self._cached_request(
                "backlog_id",
                f"/team/{self.team_id}/projects/{self.project_id}/",
                params={"action": "getbacklog"},
            )
            return str(res.get("backlogId") or "").strip()
        except Exception:
            return ""

    def list_items(self, sprint_id: str) -> dict:
        return self._request(
            f"/team/{self.team_id}/projects/{self.project_id}/sprints/{sprint_id}/item/",
            params={"action": "sprintitems", "subitem": "true"},
        )

    def resolve_item(self, item_input: str, sprint_id: str | None = None) -> tuple[str, str]:
        raw_input = str(item_input).strip()
        match = re.search(r"(\d+)", raw_input)
        target_num = match.group(1) if match else raw_input
        sprint_ids = list(self.get_sprints().get("sprintIds") or [])
        bid = self.get_backlog_id()
        if bid and bid not in sprint_ids:
            sprint_ids.append(bid)
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
        if sprint_id:
            search_sprints = [sprint_id] + [s for s in sprint_ids if s != sprint_id]
        else:
            search_sprints = sprint_ids
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
