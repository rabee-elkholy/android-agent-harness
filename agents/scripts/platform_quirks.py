"""Centralized Antigravity & Host Platform Quirks Registry.

Consolidates temporary workarounds and diagnostics for upstream IDE, CLI, and OS bugs
(#640, #198333..#201621) into one declarative catalog with instant kill-switches via
`HARNESS_DISABLE_QUIRKS=201621,200687` or `.agents/project-context/quirks.json`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping


PLATFORM_QUIRKS: dict[str, dict[str, Any]] = {
    "AGY_640_PRETOOL_SUBAGENT_BYPASS": {
        "issues": ("#640",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "PostToolUse audit catches executed invoke_subagent calls that bypassed PreToolUse denials.",
    },
    "AGY_1618_548_DEFAULT_PROJECT_PERM_LEAK": {
        "issues": ("#1618", "#548"),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Warns when ~/.gemini/config/projects/default-cli-project.json stores broad allow rules that leak across non-Git or --project-omitted directories.",
    },
    "AGY_1620_BUILTIN_SLASH_SKILL_COLLISION": {
        "issues": ("#1620",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Warns when custom project skills collide with non-disableable agy CLI built-in slash commands (/grill-me, /plan, /compact, /goal).",
    },
    "AGY_1623_171228_LONG_WAIT_KV_CACHE_TTL": {
        "issues": ("#1623", "#171228"),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Detects >=120s tool/subagent wait gaps followed by cachedContentTokenCount=0 KV prompt-cache TTL expiration drops.",
    },
    "AGY_1649_201731_WIN_HYDROGEN_MEDIUM_ZERO_THINKING": {
        "issues": ("#1649", "#201731"),
        "platforms": ("win32",),
        "default_enabled": True,
        "summary": "Detects 0-thinking-token collapse on Gemini 4 Hydrogen (Medium) after workspace read_file/view_file calls on Windows (#1649/#201731), warns on Hydrogen Medium Lead sessions, and escalates Scout/subagents via Model='flash' (routes natively to Hydrogen Tiered High 1x).",
    },
    "AGY_198333_FLASH_503_BACKOFF": {
        "issues": ("#198333",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Detects silent Gemini 3.8 Flash HTTP 503 regional capacity backoff loops.",
    },
    "AGY_198417_199301_WIN_STDIO_MCP": {
        "issues": ("#198417", "#199301"),
        "platforms": ("win32",),
        "default_enabled": True,
        "fixed_upstream_in": {"agy_cli": "1.5.10", "antigravity_app": "2.33.0"},
        "summary": "Warns on pre-v2.33.0 / pre-1.5.10 Windows setups when multiple high-churn stdio MCP servers risk Win32 pipe-handle collisions.",
    },
    "AGY_198689_LANGUAGE_SERVER_LOG_BLOAT": {
        "issues": ("#198689",),
        "platforms": ("all",),
        "default_enabled": True,
        "fixed_upstream_in": {"antigravity_app": "2.33.0"},
        "summary": "Detects multi-GB language_server.log WatchVersionControlState spin bloat (background git.exe leak fixed in App v2.33.0).",
    },
    "AGY_198819_REMOTE_MODE_ARGON_LEAK": {
        "issues": ("#198819",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Guards against Remote Mode ignoring Model='flash' and draining 3x Argon weekly quota.",
    },
    "AGY_199713_ZOMBIE_SUBAGENT_SCHEDULE": {
        "issues": ("#199713",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Blocks >=180s subagent schedule timers and detects >=2h zombie reactive-wakeup spikes.",
    },
    "AGY_199748_199756_HEADLESS_LOOP_TOS": {
        "issues": ("#199748", "#199756"),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Blocks unattended agy -p / --headless loops and UI keystroke injection.",
    },
    "AGY_199769_199770_ZERO_QUOTA_429": {
        "issues": ("#199769", "#199770"),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Detects Managed Agent API zero-quota (limit: 0) HTTP 429 responses on Argon/Carbon/Neon.",
    },
    "AGY_199971_200029_HYDROGEN_BURST_403": {
        "issues": ("#199971", "#200029"),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Human-cadence burst pacer smoothing rapid sequential tool turns to prevent false 403 bans.",
    },
    "AGY_199992_200147_ENTITLEMENT_DESYNC": {
        "issues": ("#199992", "#200147"),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Classifies transient Gemini 4 Hydrogen/Neon/Argon entitlement desync Unavailable states.",
    },
    "AGY_200026_TURN3_KV_CACHE_DROP": {
        "issues": ("#200026",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Preserves Turn-0 {} subagent prefix-cache lock and detects Turn-3 +701 cache=0 drops.",
    },
    "AGY_200037_WIN11_SAC_ERROR_4551": {
        "issues": ("#200037", "#203416"),
        "platforms": ("win32",),
        "default_enabled": True,
        "fixed_upstream_in": {"antigravity_app": "2.33.0", "agy_cli": "1.5.11"},
        "summary": "Detects unsigned Antigravity IDE v2.7.0 / v2.8.0 installs and installers triggering Windows 11 Smart App Control Error 4551 (re-regressed in IDE v2.8.0 #203416; App v2.33.0+ and agy CLI v1.5.11+ remain signed).",
    },
    "AGY_200144_CLI_SUBAGENT_MODEL_ID": {
        "issues": ("#200144", "#171228"),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Omits unsupported explicit model IDs from subagent YAML frontmatter (#200144) and offloads Hydrogen Scout/Reviewer subagents on Carbon/Neon/Argon Lead sessions via Model='flash' (routes natively to Gemini 4 Hydrogen Tiered High 1x).",
    },
    "AGY_200467_HYDROGEN_EXTRA_ARGON_LEAK": {
        "issues": ("#200467",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Warns when Hydrogen Extra / xhigh silently drains 3x Argon weekly quota.",
    },
    "AGY_200619_INLINE_DIFF_AUTO_ACCEPT": {
        "issues": ("#200619",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Warns when antigravity.autoAcceptOnChat=true risks silent inline diff corruption.",
    },
    "AGY_200632_WIN_POWERSHELL_TURBO": {
        "issues": ("#200632", "#1718"),
        "platforms": ("win32",),
        "default_enabled": True,
        "summary": "Blocks PowerShell pipes, chaining, inline powershell -c (#200632), and direct Start-Process / saps child launches (#1718 inherited stdout/stderr pipe EOF 'Empty log' hangs) inside run_command.",
    },
    "AGY_200671_CARBON_TOOL_TURN_TRUNCATION": {
        "issues": ("#200671",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Guides plain-text reasoning summaries before tool batches on standalone Carbon sessions.",
    },
    "AGY_200687_200763_WIN_GOGC_ACCEPTEX_995": {
        "issues": ("#200687", "#199301", "#200763"),
        "platforms": ("win32",),
        "default_enabled": True,
        "fixed_upstream_in": {"antigravity_ide": "2.8.0"},
        "summary": "Checks GOMEMLIMIT/GOGC tuning (#200687) and detects pre-IDE-2.8.0 post-wipe main.log AcceptEx code-2 recovery loops (#200763 fixed upstream in IDE v2.8.0).",
    },
    "AGY_201208_PREAMBLE_BOILERPLATE_QUOTA": {
        "issues": ("#201208",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Keeps adapter templates free of boilerplate preambles that trigger false quota errors.",
    },
    "AGY_201209_EMPTY_SUBAGENT_PAYLOAD": {
        "issues": ("#201209",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Detects silent DONE subagent turns with empty/<16-char payloads immediately.",
    },
    "AGY_201491_201582_NESTED_AGY_CLI_TOS": {
        "issues": ("#201491", "#201582", "#1707"),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Blocks verb-position agy/antigravity subprocess calls inside run_command (Section 6 ToS and concurrent Remote MCP OAuth rotating refresh-token invalid_grant #1707).",
    },
    "AGY_201621_SEARCH_WEB_PARALLEL_EOF": {
        "issues": ("#201621",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Caps parallel search_web bursts at <=2 per turn and diagnoses >300s unexpected EOF stalls.",
    },
    "AGY_WIN_CRLF_EDIT_NORMALIZATION": {
        "issues": ("#crlf-edit",),
        "platforms": ("all",),
        "default_enabled": True,
        "fixed_upstream_in": {"agy_cli": "1.5.1", "antigravity_app": "2.33.0", "antigravity_ide": "2.7.1"},
        "summary": "Pre-1.5.1 PreToolUse CRLF->LF target normalization for host edit_file (fixed upstream in agy CLI 1.5.1 / 1.5.10 and App 2.33.0; bypassed automatically on >=1.5.1).",
    },
    "AGY_WIN_HOOK_QUOTE_AND_BOM": {
        "issues": ("#hook-quote-bom",),
        "platforms": ("win32",),
        "default_enabled": True,
        "fixed_upstream_in": {"agy_cli": "1.5.8", "antigravity_app": "2.33.0"},
        "summary": "Pre-1.5.8 Windows hooks.json double-quote command parsing and UTF-8 BOM hazard check (fixed upstream in agy CLI 1.5.8 and plugin.json BOM in 1.5.11).",
    },
    "AGY_1697_MODEL_STEERING_STREAM_LOOP": {
        "issues": ("#1697",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Warns when experimental.modelSteering=true in agy CLI settings.json risks unclosed <SYSTEM_MESSAGE> 166k-token EOS loops and flags runaway separator loops in session forensics.",
    },
    "AGY_1691_1667_IMAGE_READ_BATCH_AND_JPEG": {
        "issues": ("#1691", "#1667"),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Caps parallel image read bursts at <=6 per wave (#1691 recitation hang) and validates JPEG SOI/EOI markers (FFD8..FFD9) before read_file (#1667 400 INVALID_ARGUMENT).",
    },
    "AGY_1720_NEON_XHIGH_CACHE_COLLAPSE": {
        "issues": ("#1720",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Warns when Gemini 4 Neon (XHigh / Extra) is selected for long multi-turn sessions (~44.6% cache hit rate from unshared multi-replica KV routing; Neon High/Medium and Hydrogen High stabilized at ~89.8%-99.4% after Nov 21 patch).",
    },
    "AGY_1722_ACP_ADC_60M_OAUTH_CANCEL": {
        "issues": ("#1722",),
        "platforms": ("all",),
        "default_enabled": True,
        "summary": "Detects agy acp (mode=adc / agent-platform) 60-minute OAuth token refresh context-canceled errors and silent empty end_turn responses after >=59m.",
    },
}


def _normalize_token(raw: str) -> str:
    return re.sub(r"^#+", "", str(raw or "").strip()).upper()


def _disabled_tokens(repo: Path | None = None, env: Mapping[str, str] | None = None) -> set[str]:
    environ = env if env is not None else os.environ
    disabled: set[str] = set()
    raw_env = str(environ.get("HARNESS_DISABLE_QUIRKS") or "").strip()
    if raw_env:
        for part in re.split(r"[,;\s]+", raw_env):
            tok = _normalize_token(part)
            if tok:
                disabled.add(tok)
    if repo is not None:
        for rel in (".agents/project-context/quirks.json", "agents/project-context/quirks.json"):
            cfg_path = repo / rel
            if cfg_path.is_file():
                try:
                    data = json.loads(cfg_path.read_text(encoding="utf-8-sig", errors="replace"))
                    if isinstance(data, dict):
                        for item in data.get("disabled") or []:
                            tok = _normalize_token(str(item))
                            if tok:
                                disabled.add(tok)
                except (OSError, ValueError):
                    pass
                break
    return disabled


def _matching_quirk_ids(quirk_id_or_issue: str) -> list[str]:
    needle = _normalize_token(quirk_id_or_issue)
    if not needle:
        return []
    if needle in PLATFORM_QUIRKS:
        return [needle]
    hits: list[str] = []
    for qid, spec in PLATFORM_QUIRKS.items():
        issue_nums = {_normalize_token(i) for i in spec.get("issues") or ()}
        if needle in issue_nums or f"_{needle}_" in f"_{qid}_":
            hits.append(qid)
    return hits


def resolve_quirk_id(quirk_id_or_issue: str) -> str | None:
    hits = _matching_quirk_ids(quirk_id_or_issue)
    return hits[0] if hits else None


def _parse_semver_tuple(raw: str) -> tuple[int, int, int] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(raw or ""))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def is_quirk_mitigated_upstream(
    quirk_id_or_issue: str,
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return True when declared Antigravity CLI/App/IDE version meets or exceeds the quirk's `fixed_upstream_in` floor."""
    environ = env if env is not None else os.environ
    hits = _matching_quirk_ids(quirk_id_or_issue)
    if not hits:
        return False
    cli_v = _parse_semver_tuple(str(environ.get("ANTIGRAVITY_CLI_VERSION") or environ.get("AGY_CLI_VERSION") or ""))
    app_v = _parse_semver_tuple(str(environ.get("ANTIGRAVITY_APP_VERSION") or environ.get("AGY_APP_VERSION") or ""))
    ide_v = _parse_semver_tuple(str(environ.get("ANTIGRAVITY_IDE_VERSION") or environ.get("AGY_IDE_VERSION") or ""))
    for qid in hits:
        fixed_in = PLATFORM_QUIRKS[qid].get("fixed_upstream_in")
        if not isinstance(fixed_in, dict) or not fixed_in:
            return False
        mitigated = False
        if cli_v is not None and fixed_in.get("agy_cli"):
            req_cli = _parse_semver_tuple(str(fixed_in["agy_cli"]))
            if req_cli is not None and cli_v >= req_cli:
                mitigated = True
        if app_v is not None and fixed_in.get("antigravity_app"):
            req_app = _parse_semver_tuple(str(fixed_in["antigravity_app"]))
            if req_app is not None and app_v >= req_app:
                mitigated = True
        if ide_v is not None and fixed_in.get("antigravity_ide"):
            req_ide = _parse_semver_tuple(str(fixed_in["antigravity_ide"]))
            if req_ide is not None and ide_v >= req_ide:
                mitigated = True
        if not mitigated:
            return False
    return True


def is_quirk_enabled(
    quirk_id_or_issue: str,
    *,
    repo: Path | None = None,
    env: Mapping[str, str] | None = None,
    respect_platform: bool = False,
    respect_upstream: bool = False,
) -> bool:
    environ = env if env is not None else os.environ
    disabled = _disabled_tokens(repo=repo, env=environ)
    if "ALL" in disabled or "*" in disabled:
        return False
    hits = _matching_quirk_ids(quirk_id_or_issue)
    if not hits:
        return _normalize_token(quirk_id_or_issue) not in disabled
    sim_plat = str(environ.get("HARNESS_SIMULATE_PLATFORM") or "").strip().lower()
    active_plat = sim_plat or sys.platform.lower()
    for qid in hits:
        spec = PLATFORM_QUIRKS[qid]
        if qid in disabled or any(_normalize_token(iss) in disabled for iss in (spec.get("issues") or ())):
            return False
        if respect_upstream and is_quirk_mitigated_upstream(qid, env=environ):
            continue
        if respect_platform:
            plats = tuple(str(p).lower() for p in (spec.get("platforms") or ("all",)))
            if "all" not in plats and not any(active_plat.startswith(p) for p in plats):
                continue
        if bool(spec.get("default_enabled", True)):
            return True
    return False


def list_platform_quirks(
    repo: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for qid, spec in PLATFORM_QUIRKS.items():
        fixed_map = dict(spec.get("fixed_upstream_in") or {})
        mitigated = is_quirk_mitigated_upstream(qid, env=env)
        rows.append({
            "id": qid,
            "issues": list(spec.get("issues") or ()),
            "platforms": list(spec.get("platforms") or ("all",)),
            "enabled": is_quirk_enabled(qid, repo=repo, env=env),
            "mitigated_upstream": mitigated,
            **({"fixed_upstream_in": fixed_map} if fixed_map else {}),
            "summary": str(spec.get("summary") or ""),
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect active and disabled platform quirks.")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    ns = parser.parse_args(argv)
    repo = Path(ns.repo).resolve()
    rows = list_platform_quirks(repo=repo)
    active_n = sum(1 for r in rows if r["enabled"])
    if ns.json:
        print(json.dumps({"total": len(rows), "active": active_n, "disabled": len(rows) - active_n, "quirks": rows}, indent=2))
    else:
        print(f"Platform Quirks Registry: {active_n}/{len(rows)} active (disable via HARNESS_DISABLE_QUIRKS=<issue_id>)")
        for r in rows:
            st = "ON " if r["enabled"] else "OFF"
            print(f"  [{st}] {r['id']} ({', '.join(r['issues'])}): {r['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
