"""Zero-Config Multi-Provider PM MCP Discovery & Lifecycle Engine for Antigravity.

Automatically detects all Project Management (PM) MCP servers and plugins
installed in Antigravity (`~/.gemini/antigravity/mcp/*`, `~/.gemini/config/plugins/*`,
and project `.agents/mcp_config.json` / `.cursor/mcp.json`) at runtime without
requiring manual setup reconfiguration.

Supports built-in profiles for Zoho Projects, Zoho Sprints, Jira (Atlassian),
Linear, Notion, Monday.com, GitHub Projects, ClickUp, Asana, Trello, and
dynamically classifies any other PM MCP server whose tool schemas operate on
tasks, issues, bugs, sprints, phases, or milestones.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _vnext_common import ValidationError, read_json  # noqa: E402


BUILTIN_PM_CATALOG: dict[str, dict[str, Any]] = {
    "zoho_projects": {
        "display": "Zoho Projects",
        "server_aliases": ("zoho-projects_mcp", "zoho-projects", "zoho_projects"),
        "plugin_aliases": ("zoho-projects",),
        "tool_prefixes": ("zohoprojects_",),
        "triggers_en": ("update zoho", "update zoho projects", "update pm", "update task"),
        "triggers_ar": ("زوهو", "بروجكتس", "التاسك", "المهمة"),
        "in_progress_labels": ("in progress", "open", "active"),
        "retest_labels": ("ready to retest", "in review", "testing", "ready for testing"),
        "terminal_labels": ("closed", "completed", "done", "resolved", "solved"),
    },
    "zoho_sprints": {
        "display": "Zoho Sprints",
        "server_aliases": ("zoho-sprints", "zoho_sprints", "zoho-sprints_mcp", "zoho_sprints_mcp", "zsprints"),
        "plugin_aliases": ("zoho-sprints", "zoho_sprints"),
        "tool_prefixes": ("zohosprints_", "zoho_sprints_", "zohomcp_", "zoho_list_sprints", "zoho_list_tasks", "zoho_get_task_details", "zoho_create_task", "zoho_update_task_status", "zoho_add_comment", "zoho_update_task_description"),
        "triggers_en": ("update zoho", "update zoho sprints", "update pm", "update task"),
        "triggers_ar": ("زوهو", "سبرنت", "التاسك", "المهمة"),
        "in_progress_labels": ("in progress",),
        "retest_labels": ("ready to retest",),
        "terminal_labels": ("done", "solved", "closed", "completed"),
    },
    "jira": {
        "display": "Jira (Atlassian)",
        "server_aliases": ("atlassian-mcp-server", "atlassian", "jira", "jira-mcp", "jira_mcp"),
        "plugin_aliases": ("atlassian", "jira", "atlassian-mcp"),
        "tool_prefixes": ("getjira", "editjira", "createjira", "transitionjira", "searchjira", "lookupjira", "addcommenttojira", "addworklogtojira", "gettransitionsforjira", "getvisiblejiraprojects", "atlassianuserinfo", "getaccessibleatlassianresources"),
        "triggers_en": ("update jira", "update atlassian", "update pm", "update task"),
        "triggers_ar": ("جيرا", "اتلاسيان", "التاسك", "المهمة"),
        "in_progress_labels": ("in progress",),
        "retest_labels": ("ready for testing", "in review", "qa", "ready to retest"),
        "terminal_labels": ("done", "closed", "resolved"),
    },
    "linear": {
        "display": "Linear",
        "server_aliases": ("linear", "linear-mcp", "linear_mcp"),
        "plugin_aliases": ("linear",),
        "tool_prefixes": ("linear_", "linear-"),
        "triggers_en": ("update linear", "update pm", "update task"),
        "triggers_ar": ("لينير", "التاسك", "المهمة"),
        "in_progress_labels": ("in progress", "started"),
        "retest_labels": ("in review", "ready for testing", "ready to retest"),
        "terminal_labels": ("done", "completed", "canceled", "cancelled"),
    },
    "monday": {
        "display": "Monday.com",
        "server_aliases": ("monday", "monday-mcp", "monday_mcp"),
        "plugin_aliases": ("monday",),
        "tool_prefixes": ("monday_", "monday-"),
        "triggers_en": ("update monday", "update pm", "update task"),
        "triggers_ar": ("مانداي", "التاسك", "المهمة"),
        "in_progress_labels": ("working on it", "in progress"),
        "retest_labels": ("in review", "ready for testing"),
        "terminal_labels": ("done", "completed"),
    },
    "github_projects": {
        "display": "GitHub Projects & Issues",
        "server_aliases": ("github", "github-mcp", "github_projects"),
        "plugin_aliases": ("github",),
        "tool_prefixes": ("github_", "issue_", "pull_request_"),
        "triggers_en": ("update github", "update pm", "update task"),
        "triggers_ar": ("جيتهاب", "التاسك", "المهمة"),
        "in_progress_labels": ("in progress",),
        "retest_labels": ("in review", "ready for review"),
        "terminal_labels": ("done", "closed", "shipped"),
    },
    "clickup": {
        "display": "ClickUp",
        "server_aliases": ("clickup", "clickup-mcp", "clickup_mcp"),
        "plugin_aliases": ("clickup",),
        "tool_prefixes": ("clickup_", "clickup-"),
        "triggers_en": ("update clickup", "update pm", "update task"),
        "triggers_ar": ("كليك اب", "التاسك", "المهمة"),
        "in_progress_labels": ("in progress",),
        "retest_labels": ("in review", "ready for review"),
        "terminal_labels": ("complete", "closed", "done"),
    },
    "asana": {
        "display": "Asana",
        "server_aliases": ("asana", "asana-mcp", "asana_mcp"),
        "plugin_aliases": ("asana",),
        "tool_prefixes": ("asana_", "asana-"),
        "triggers_en": ("update asana", "update pm", "update task"),
        "triggers_ar": ("اسانا", "التاسك", "المهمة"),
        "in_progress_labels": ("in progress",),
        "retest_labels": ("in review",),
        "terminal_labels": ("completed", "done"),
    },
    "trello": {
        "display": "Trello",
        "server_aliases": ("trello", "trello-mcp", "trello_mcp"),
        "plugin_aliases": ("trello",),
        "tool_prefixes": ("trello_", "trello-"),
        "triggers_en": ("update trello", "update pm", "update task"),
        "triggers_ar": ("تريلو", "التاسك", "المهمة"),
        "in_progress_labels": ("in progress", "doing"),
        "retest_labels": ("in review", "testing"),
        "terminal_labels": ("done", "Archived"),
    },
}

PM_DOMAIN_NOUNS = frozenset({
    "task", "tasks", "tasklist", "tasklists",
    "issue", "issues", "bug", "bugs",
    "sprint", "sprints", "milestone", "milestones",
    "phase", "phases", "workitem", "workitems",
    "ticket", "tickets", "story", "stories", "epic", "epics",
    "worklog", "timelog", "timelogs", "subtask", "subtasks",
})

# Non-PM servers that should stay on generic MCP rules (e.g. design/cloud/docs)
NON_PM_SERVERS = frozenset({
    "stitchmcp", "figma", "figma_figma", "mobbin", "mobbin_mobbin",
    "postman", "postman-mcp-server", "postman_postman", "firebase", "firebase-mcp-server",
    "supabase", "vercel", "netlify", "railway", "chrome-devtools", "backend", "auth",
    "notion", "notion_notion", "notion-mcp-server", "canva", "canva_canva",
    "context7", "context7_context7",
})


def _candidate_antigravity_mcp_dirs() -> list[Path]:
    dirs: list[Path] = []
    override = os.environ.get("HARNESS_ANTIGRAVITY_MCP_DIR", "").strip()
    if override:
        p = Path(override)
        if p.is_dir():
            dirs.append(p)
        return dirs
    try:
        home = Path.home()
        for rel in (".gemini/antigravity/mcp", ".antigravity/mcp"):
            cand = home / rel
            if cand.is_dir() and cand not in dirs:
                dirs.append(cand)
    except OSError:
        pass
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        cand = Path(appdata) / "antigravity" / "mcp"
        if cand.is_dir() and cand not in dirs:
            dirs.append(cand)
    return dirs


def _candidate_antigravity_plugin_dirs() -> list[Path]:
    dirs: list[Path] = []
    override = os.environ.get("HARNESS_ANTIGRAVITY_PLUGINS_DIR", "").strip()
    if override:
        p = Path(override)
        if p.is_dir():
            dirs.append(p)
        return dirs
    try:
        home = Path.home()
        for rel in (".gemini/config/plugins", ".antigravity/plugins"):
            cand = home / rel
            if cand.is_dir() and cand not in dirs:
                dirs.append(cand)
    except OSError:
        pass
    return dirs


def identify_pm_provider(server: str, tool_name: str = "") -> str | None:
    """Resolve `(server, tool_name)` to a canonical PM provider id, or None if not a PM MCP."""
    srv = (server or "").strip().lower()
    tl = (tool_name or "").strip().lower()

    if srv in NON_PM_SERVERS:
        return None

    # Check Zoho Projects BEFORE Zoho Sprints so `zoho-projects_mcp` / `ZohoProjects_*` never collide with zoho_sprints
    for provider_id, meta in BUILTIN_PM_CATALOG.items():
        if srv and srv in meta["server_aliases"]:
            return provider_id
        for pref in meta["tool_prefixes"]:
            if tl.startswith(pref):
                return provider_id

    if "zoho-projects" in srv or "zoho_projects" in srv or tl.startswith("zohoprojects_"):
        return "zoho_projects"
    if "zoho" in srv or tl.startswith("zoho_"):
        return "zoho_sprints"
    if "atlassian" in srv or "jira" in srv or "jira" in tl:
        return "jira"
    if "linear" in srv or tl.startswith("linear_"):
        return "linear"
    if "monday" in srv or tl.startswith("monday_"):
        return "monday"
    if "clickup" in srv or tl.startswith("clickup_"):
        return "clickup"
    if "asana" in srv or tl.startswith("asana_"):
        return "asana"
    if "trello" in srv or tl.startswith("trello_"):
        return "trello"

    # Dynamic schema check: if server exists in Antigravity MCP directory and has PM domain tools
    if srv:
        for mcp_root in _candidate_antigravity_mcp_dirs():
            srv_dir = mcp_root / server
            if not srv_dir.is_dir():
                srv_dir = mcp_root / srv
            if srv_dir.is_dir() and _dir_looks_like_pm_mcp(srv_dir):
                return f"custom:{srv}"
    return None


def _dir_looks_like_pm_mcp(server_dir: Path) -> bool:
    """Return True if at least 2 tool schemas in `server_dir` target PM domain nouns."""
    if server_dir.name.lower() in NON_PM_SERVERS:
        return False
    pm_matches = 0
    try:
        for entry in server_dir.iterdir():
            if entry.suffix.lower() != ".json" or entry.name == "instructions.md":
                continue
            tokens = set(re.split(r"[_\-.:]+", entry.stem.lower()))
            # Also split camelCase (e.g. getJiraIssue -> get, jira, issue)
            camel_tokens = {tok.lower() for tok in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", entry.stem)}
            if (tokens | camel_tokens) & PM_DOMAIN_NOUNS:
                pm_matches += 1
                if pm_matches >= 2:
                    return True
    except OSError:
        return False
    return False


def unwrap_zoho_mcp_execute(
    tool_name: str, args: Mapping[str, Any] | None = None
) -> tuple[str, Mapping[str, Any]]:
    """Unwrap ZohoMCP_executeTool into its inner (tool_name, arguments) when present."""
    raw = str(tool_name or "").strip()
    args_map = dict(args or {})
    if raw.lower() == "zohomcp_executetool":
        body = args_map.get("body")
        container = dict(body) if isinstance(body, Mapping) else args_map
        inner_name = str(container.get("tool_name") or container.get("toolName") or "").strip()
        inner_args = container.get("arguments") or container.get("args") or {}
        if isinstance(inner_args, str):
            try:
                inner_args = json.loads(inner_args)
            except Exception:
                inner_args = {}
        if inner_name:
            return inner_name, (dict(inner_args) if isinstance(inner_args, Mapping) else {})
    return raw, args_map


def classify_pm_tool(tool_name: str, args: Mapping[str, Any] | None = None) -> str:
    """Classify a PM MCP tool into READ, COMMENT, UPDATE_DESCRIPTION, UPDATE_STATUS, CREATE, DELETE, or WRITE."""
    raw, args_dict = unwrap_zoho_mcp_execute(tool_name, args)
    tl = raw.lower()
    # Split both snake_case and camelCase
    snake_parts = [p for p in re.split(r"[_\-.:]+", tl) if p]
    camel_parts = [p.lower() for p in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", raw) if p]
    tokens = set(snake_parts) | set(camel_parts)

    # 1. Explicit read-only check
    read_starters = (
        "get_", "list_", "read_", "fetch_", "search_", "find_", "query_",
        "inspect_", "describe_", "show_", "lookup_", "check_", "preview_",
        "get", "list", "search", "fetch", "lookup", "whoami", "atlassianuserinfo",
    )
    write_verbs = {
        "create", "update", "edit", "delete", "remove", "trash", "restore",
        "add", "clone", "move", "reorder", "transition", "execute",
        "associate", "disassociate", "dissociate", "unlink", "follow",
        "unfollow", "activate", "deactivate", "mark", "unmark", "set",
        "make", "schedule", "bulk",
    }
    has_write_verb = bool(tokens & write_verbs)
    if not has_write_verb and (any(tl.startswith(p) for p in read_starters) or bool(tokens & {"get", "list", "search", "fetch", "lookup", "check", "preview"})):
        return "READ"

    # Special case: ZohoProjects_get_*, ZohoSprints_get_*, ZohoMCP_get*, and getJira* are always READ
    if (
        tl.startswith("zohoprojects_get_")
        or tl.startswith("zohoprojects_list_")
        or tl.startswith("zohoprojects_check_")
        or tl.startswith("zohoprojects_preview_")
        or tl.startswith("zohosprints_get")
        or tl.startswith("zohosprints_list")
        or tl in {"zohomcp_getfeatures", "zohomcp_listtools", "zohomcp_getschema", "getjiraissue", "gettransitionsforjiraissue", "getjiraissueremoteissuelinks", "getvisiblejiraprojects", "getjiraprojectissuetypesmetadata", "getjiraissuetypemetawithfields", "searchjiraissuesusingjql", "lookupjiraaccountid", "getissuelinktypes", "atlassianuserinfo", "getaccessibleatlassianresources", "getcontentformatguide", "search", "fetch"}
    ):
        return "READ"

    # 2. Destructive / Trash / Delete
    if tokens & {"delete", "trash", "remove", "purge", "destroy"}:
        return "DELETE"

    # 3. Commenting
    if "comment" in tokens or "comments" in tokens:
        if tokens & {"add", "create", "post"}:
            return "COMMENT"
        if tokens & {"update", "edit"}:
            return "COMMENT"

    # 4. Creating new items
    if tokens & {"create", "clone"} and not (tokens & {"update", "edit", "transition"}):
        return "CREATE"

    # 5. Updating / Editing / Transitioning
    if tokens & {"transition"} or "status" in args_dict or "status_id" in args_dict or "transition" in args_dict:
        return "UPDATE_STATUS"
    if "description" in tokens or ("description" in args_dict and tokens & {"update", "edit"}):
        return "UPDATE_DESCRIPTION"

    return "WRITE"


def _active_antigravity_server_names(repo: Path | None = None) -> set[str] | None:
    """Return lowercase active MCP server names from Antigravity config/plugins and repo config, or None if no host config root exists."""
    if os.environ.get("HARNESS_ANTIGRAVITY_MCP_DIR", "").strip() or os.environ.get("HARNESS_ANTIGRAVITY_PLUGINS_DIR", "").strip():
        return None
    try:
        home = Path.home()
    except OSError:
        return None
    config_root = home / ".gemini" / "config"
    if not config_root.is_dir():
        return None
    active: set[str] = set()
    mcp_cfg = config_root / "mcp_config.json"
    if mcp_cfg.is_file():
        try:
            data = read_json(mcp_cfg)
            servers = data.get("mcpServers") if isinstance(data, dict) else {}
            if isinstance(servers, dict):
                for k in servers:
                    active.add(str(k).strip().lower())
        except (OSError, ValueError, KeyError, TypeError):
            pass
    plugins_dir = config_root / "plugins"
    if plugins_dir.is_dir():
        try:
            for plug_dir in plugins_dir.iterdir():
                if not plug_dir.is_dir():
                    continue
                pname = plug_dir.name.strip().lower()
                active.add(pname)
                for cfg_name in ("mcp_config.json", "mcp.json"):
                    pcfg = plug_dir / cfg_name
                    if pcfg.is_file():
                        try:
                            pdata = read_json(pcfg)
                            pservers = pdata.get("mcpServers") if isinstance(pdata, dict) else {}
                            if isinstance(pservers, dict):
                                for subk in pservers:
                                    sub_lower = str(subk).strip().lower()
                                    active.add(sub_lower)
                                    active.add(f"{pname}_{sub_lower}")
                                    active.add(f"{pname}-{sub_lower}")
                        except (OSError, ValueError, KeyError, TypeError):
                            pass
        except OSError:
            pass
    if repo is not None:
        for cfg_rel in (".agents/mcp_config.json", "agents/mcp_config.json", ".cursor/mcp.json"):
            rcfg = Path(repo) / cfg_rel
            if rcfg.is_file():
                try:
                    rdata = read_json(rcfg)
                    rservers = rdata.get("mcpServers") if isinstance(rdata, dict) else {}
                    if isinstance(rservers, dict):
                        for k in rservers:
                            active.add(str(k).strip().lower())
                except (OSError, ValueError, KeyError, TypeError):
                    pass
    return active if active else None


def discover_installed_pm_mcps(
    repo: Path | None = None,
    *,
    extra_mcp_roots: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """Scan Antigravity MCP directories, plugins, and repo configs for all installed PM MCPs."""
    discovered: dict[str, dict[str, Any]] = {}
    explicit_roots = {Path(p).resolve() for p in (extra_mcp_roots or [])}
    active_servers = _active_antigravity_server_names(repo)

    # 1. Scan Antigravity MCP server schema directories (<appDataDir>/mcp/<serverName>)
    mcp_dirs = list(extra_mcp_roots or []) + _candidate_antigravity_mcp_dirs()
    for mcp_dir in mcp_dirs:
        is_explicit_root = Path(mcp_dir).resolve() in explicit_roots
        try:
            for srv_dir in sorted(mcp_dir.iterdir()):
                if not srv_dir.is_dir():
                    continue
                srv_name = srv_dir.name
                if not is_explicit_root and active_servers is not None and srv_name.strip().lower() not in active_servers:
                    continue
                provider_id = identify_pm_provider(srv_name)
                if not provider_id and _dir_looks_like_pm_mcp(srv_dir):
                    provider_id = f"custom:{srv_name.lower()}"
                if not provider_id:
                    continue
                tool_files = [f.stem for f in srv_dir.glob("*.json") if f.is_file()]
                read_tools = sorted(t for t in tool_files if classify_pm_tool(t) == "READ")
                write_tools = sorted(t for t in tool_files if t not in read_tools)
                create_tools = sorted(t for t in write_tools if classify_pm_tool(t) == "CREATE")
                comment_tools = sorted(t for t in write_tools if classify_pm_tool(t) == "COMMENT")
                status_tools = sorted(t for t in write_tools if classify_pm_tool(t) == "UPDATE_STATUS")
                desc_tools = sorted(t for t in write_tools if classify_pm_tool(t) in ("UPDATE_DESCRIPTION", "WRITE") and t not in create_tools and t not in comment_tools)
                read_count = len(read_tools)
                write_count = len(write_tools)
                meta = BUILTIN_PM_CATALOG.get(provider_id, {
                    "display": srv_name,
                    "triggers_en": (f"update {srv_name.lower()}", "update pm"),
                    "triggers_ar": ("التاسك", "المهمة"),
                })
                entry = discovered.setdefault(provider_id, {
                    "provider_id": provider_id,
                    "display": meta.get("display", srv_name),
                    "server_name": srv_name,
                    "servers": [],
                    "sources": [],
                    "tool_count": 0,
                    "read_tools": 0,
                    "write_tools": 0,
                    "tools": {
                        "read_tools": [],
                        "write_tools": [],
                        "create_tools": [],
                        "comment_tools": [],
                        "update_status_tools": [],
                        "update_description_tools": [],
                    },
                    "triggers": list(meta.get("triggers_en", ("update pm",))),
                })
                if srv_name not in entry["servers"]:
                    entry["servers"].append(srv_name)
                if "antigravity_mcp" not in entry["sources"]:
                    entry["sources"].append("antigravity_mcp")
                entry["tool_count"] += len(tool_files)
                entry["read_tools"] += read_count
                entry["write_tools"] += write_count
                entry["tools"]["read_tools"] = sorted(set(entry["tools"]["read_tools"]) | set(read_tools))
                entry["tools"]["write_tools"] = sorted(set(entry["tools"]["write_tools"]) | set(write_tools))
                entry["tools"]["create_tools"] = sorted(set(entry["tools"]["create_tools"]) | set(create_tools))
                entry["tools"]["comment_tools"] = sorted(set(entry["tools"]["comment_tools"]) | set(comment_tools))
                entry["tools"]["update_status_tools"] = sorted(set(entry["tools"]["update_status_tools"]) | set(status_tools))
                entry["tools"]["update_description_tools"] = sorted(set(entry["tools"]["update_description_tools"]) | set(desc_tools))
        except OSError:
            continue

    # 2. Scan Antigravity installed plugins (~/.gemini/config/plugins/<pluginName>)
    for plugin_root in _candidate_antigravity_plugin_dirs():
        try:
            for plug_dir in sorted(plugin_root.iterdir()):
                if not plug_dir.is_dir():
                    continue
                plug_name = plug_dir.name.lower()
                for provider_id, meta in BUILTIN_PM_CATALOG.items():
                    if plug_name in meta.get("plugin_aliases", ()) or plug_name in meta.get("server_aliases", ()):
                        entry = discovered.setdefault(provider_id, {
                            "provider_id": provider_id,
                            "display": meta["display"],
                            "server_name": plug_dir.name,
                            "servers": [plug_dir.name],
                            "sources": [],
                            "tool_count": 0,
                            "read_tools": 0,
                            "write_tools": 0,
                            "tools": {
                                "read_tools": [],
                                "write_tools": [],
                                "create_tools": [],
                                "comment_tools": [],
                                "update_status_tools": [],
                                "update_description_tools": [],
                            },
                            "triggers": list(meta.get("triggers_en", ("update pm",))),
                        })
                        if "antigravity_plugin" not in entry["sources"]:
                            entry["sources"].append("antigravity_plugin")
        except OSError:
            continue

    # 3. Scan repository MCP configs (.agents/mcp_config.json, .cursor/mcp.json)
    if repo is not None:
        for cfg_rel in (".agents/mcp_config.json", "agents/mcp_config.json", ".cursor/mcp.json"):
            cfg_path = Path(repo) / cfg_rel
            if not cfg_path.is_file():
                continue
            try:
                data = read_json(cfg_path)
                servers = data.get("mcpServers") if isinstance(data, dict) else {}
                if not isinstance(servers, dict):
                    continue
                for srv_name, srv_cfg in servers.items():
                    if isinstance(srv_cfg, dict):
                        srv_args = " ".join(str(x) for x in (srv_cfg.get("args") or []))
                        if "mcp/zoho_sprints/server.py" in srv_args.replace("\\", "/") and not (Path(repo) / ".agents/mcp/zoho_sprints/server.py").is_file():
                            continue
                    provider_id = identify_pm_provider(srv_name)
                    if not provider_id:
                        continue
                    meta = BUILTIN_PM_CATALOG.get(provider_id, {"display": srv_name, "triggers_en": ("update pm",)})
                    entry = discovered.setdefault(provider_id, {
                        "provider_id": provider_id,
                        "display": meta.get("display", srv_name),
                        "server_name": srv_name,
                        "servers": [],
                        "sources": [],
                        "tool_count": 0,
                        "read_tools": 0,
                        "write_tools": 0,
                        "tools": {
                            "read_tools": [],
                            "write_tools": [],
                            "create_tools": [],
                            "comment_tools": [],
                            "update_status_tools": [],
                            "update_description_tools": [],
                        },
                        "triggers": list(meta.get("triggers_en", ("update pm",))),
                    })
                    if srv_name not in entry["servers"]:
                        entry["servers"].append(srv_name)
                    if "repo_mcp_config" not in entry["sources"]:
                        entry["sources"].append("repo_mcp_config")
            except (OSError, ValueError, ValidationError):
                continue

    return list(discovered.values())


LANGUAGE_RULE_DESCRIPTIONS = {
    "en_titles_ar_comments": "English task/bug titles + Arabic descriptions and comments",
    "all_en": "All English (titles, descriptions, and comments in English)",
    "all_ar": "All Arabic (titles, descriptions, and comments in Arabic)",
}


def resolve_configured_pm_language(repo: Path | None = None, plan: Mapping[str, Any] | None = None) -> str:
    """Resolve the user's configured PM task/comment language from plan or `_product.py` (installation choice i18)."""
    if isinstance(plan, Mapping):
        plan_lang = str(plan.get("language") or "").strip()
        if plan_lang in LANGUAGE_RULE_DESCRIPTIONS:
            return plan_lang
    candidates: list[Path] = []
    if repo is not None:
        r = Path(repo).resolve()
        candidates.extend([
            r / ".agents" / "scripts" / "_product.py",
            r / "agents" / "scripts" / "_product.py",
        ])
    candidates.append(SCRIPTS_DIR / "_product.py")
    for p in candidates:
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
            m = re.search(r"^(?:TRACKER_LANGUAGE|ZOHO_LANGUAGE)\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
            if m and m.group(1) in LANGUAGE_RULE_DESCRIPTIONS:
                return m.group(1)
        except OSError:
            continue
    return "en_titles_ar_comments"


def main(argv: list[str] | None = None) -> int:
    from _live_process import enable_line_buffered_stdio
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Universal Multi-Provider PM MCP CLI for Android Agent Harness.")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_disc = sub.add_parser("discover", help="Auto-discover all PM MCPs installed in Antigravity and the repository")
    p_disc.add_argument("--repo", default=".")
    p_disc.add_argument("--json", action="store_true")

    p_stat = sub.add_parser("status", help="Show discovered PM MCPs and active PM write grant status")
    p_stat.add_argument("--repo", default=".")
    p_stat.add_argument("--json", action="store_true")

    p_auth = sub.add_parser("authorize", help="Record a short-lived PM write grant from the developer's update command")
    p_auth.add_argument("--repo", default=".")
    p_auth.add_argument("--proof-reference", required=True, help="Developer's exact message ordering the PM update")
    p_auth.add_argument("--provider", default="all", help="Optional provider ID (default: all matching or all active)")
    p_auth.add_argument("--source", default="conversation", choices=("conversation", "developer_terminal"))
    p_auth.add_argument("--json", action="store_true")

    p_rep = sub.add_parser("prepare-report", help="Prepare a structured QA handoff report for any PM tracker")
    p_rep.add_argument("--repo", default=".")
    p_rep.add_argument("--task-id", required=True)
    p_rep.add_argument("--objective", required=True)
    p_rep.add_argument("--changes", required=True)
    p_rep.add_argument("--impact", action="append", help="Impact item (repeat once per item)")
    p_rep.add_argument("--impact-json", default=None)
    p_rep.add_argument("--tests", action="append", help="Test case item (repeat once per item)")
    p_rep.add_argument("--tests-json", default=None)

    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()

    if args.subcommand in ("discover", "status"):
        from zoho_grant import active_pm_grant
        providers = discover_installed_pm_mcps(repo)
        grant = active_pm_grant(repo)
        tracker_lang = resolve_configured_pm_language(repo)
        payload = {
            "status": "PASS",
            "discovered_count": len(providers),
            "tracker_language": tracker_lang,
            "tracker_language_rule": LANGUAGE_RULE_DESCRIPTIONS.get(tracker_lang, ""),
            "providers": providers,
            "active_grant": grant,
        }
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            if not providers:
                print("PM_DISCOVERY=NONE (no PM MCP servers detected on host or repo)")
            else:
                names = ", ".join(f"{p['display']} ({p['provider_id']}: {p['tool_count']} tools)" for p in providers)
                print(f"PM_DISCOVERED={names}")
            print(f"TRACKER_LANGUAGE={tracker_lang} ({LANGUAGE_RULE_DESCRIPTIONS.get(tracker_lang, '')})")
            if grant:
                print(
                    f"PM_WRITE_GRANT=ACTIVE providers={grant.get('providers')} "
                    f"allow_close={grant.get('allow_close', False)} expires_epoch={int(grant.get('expires_epoch', 0))}"
                )
            else:
                print("PM_WRITE_GRANT=NONE (use `update pm` / `حدث التاسك` or `update <provider>` to grant writes)")
        return 0

    if args.subcommand == "authorize":
        from zoho_grant import record_pm_grant
        try:
            grant = record_pm_grant(repo, args.proof_reference, provider=args.provider, source=args.source)
        except ValidationError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 1
        tracker_lang = resolve_configured_pm_language(repo)
        grant["tracker_language"] = tracker_lang
        grant["tracker_language_rule"] = LANGUAGE_RULE_DESCRIPTIONS.get(tracker_lang, "")
        if args.json:
            print(json.dumps(grant, indent=2, ensure_ascii=False))
        else:
            print(
                f"PM_WRITE_GRANTED=true ZOHO_WRITE_GRANTED=true PROVIDERS={','.join(grant.get('providers') or ['all'])} "
                f"TRACKER_LANGUAGE={tracker_lang} ALLOW_CLOSE={grant.get('allow_close', False)} EXPIRES_IN_SECONDS=1800"
            )
            print(f"LANGUAGE_POLICY: {LANGUAGE_RULE_DESCRIPTIONS.get(tracker_lang, '')}")
            try:
                from project_context import extract_pm_notes_section, load_project_notes
                notes = load_project_notes(repo)
                if notes.get("has_custom_notes"):
                    pm_sec = extract_pm_notes_section(notes.get("content") or "")
                    if pm_sec:
                        print("\nMANDATORY PM RULES FROM .agents/project-context/project-notes.md:")
                        print(pm_sec)
            except (ImportError, OSError, ValueError, KeyError):
                pass
        return 0

    if args.subcommand == "prepare-report":
        import zoho_sync
        return zoho_sync.cmd_prepare_report(args)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
