"""Detect the enforcement capability actually installed for each AI host."""
from __future__ import annotations

import json
from pathlib import Path


RULE_ONLY = {"codex", "cursor", "gemini", "qwen", "windsurf", "continue", "cline", "roo", "junie", "amazonq"}


def _contains(path: Path, marker: str) -> bool:
    try:
        return marker in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def detect(repo: Path, tools: list[str] | None = None) -> dict:
    root = repo.resolve()
    selected = sorted({str(item).strip().lower() for item in (tools or []) if str(item).strip()})
    by_host: dict[str, str] = {}
    for host in selected:
        if host in {"antigravity", "gemini-antigravity"}:
            hard = (root / ".agents/hooks.json").is_file()
        elif host in {"claude", "claude-code"}:
            hard = _contains(root / ".claude/settings.json", "cc_pre_tool_safety.py")
        elif host in {"copilot", "github-copilot"}:
            hard = _contains(root / ".github/hooks/android-harness-pre-tool-use.json", "copilot_pre_tool_safety.py")
        else:
            hard = False
        by_host[host] = "HARD_ENFORCED" if hard else "RULE_ENFORCED"
    # Executable hooks can hard-enforce covered file/command mutations, but the
    # current adapters cannot cryptographically distinguish a conversational
    # user approval from agent-authored text. The universal tier is therefore
    # honestly rule-enforced even when mutation coverage is hard-enforced.
    return {
        "schema_version": 1,
        "overall": "RULE_ENFORCED",
        "approval_trust": "RULE_ENFORCED",
        "mutation_boundary_by_host": by_host,
        "by_host": by_host,
        "selected_tools": selected,
    }
