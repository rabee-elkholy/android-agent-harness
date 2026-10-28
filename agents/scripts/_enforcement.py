"""Detect the enforcement capability actually installed for each AI host."""
from __future__ import annotations

import json
import re
import shlex
import shutil
from pathlib import Path


RULE_ONLY = {"codex", "cursor", "gemini", "qwen", "windsurf", "continue", "cline", "roo", "junie", "amazonq"}


def _antigravity_hooks_valid(root: Path) -> bool:
    """Validate installed interception configuration, not host execution attestation."""
    try:
        data = json.loads((root / ".agents/hooks.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False
        required = {"run_command", "write_to_file", "replace_file_content", "multi_replace_file_content", "call_mcp_tool", "invoke_subagent"}
        covered = set()
        for group in data.values():
            if not isinstance(group, dict) or group.get("enabled") is not True:
                continue
            for entry in group.get("PreToolUse", []):
                if not isinstance(entry, dict):
                    continue
                matcher = re.compile(str(entry.get("matcher") or "(?!)"))
                for hook in entry.get("hooks", []):
                    if not isinstance(hook, dict) or hook.get("type") != "command":
                        continue
                    tokens = [s.strip('"\'') for s in shlex.split(str(hook.get("command") or ""), posix=False)]
                    if len(tokens) != 2 or not re.fullmatch(r"(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?", Path(tokens[0]).name, re.I):
                        continue
                    script = Path(tokens[1])
                    script = script if script.is_absolute() else root / ".agents" / script
                    if script.resolve() != (root / ".agents/scripts/pre_tool_safety.py").resolve() or not script.is_file():
                        continue
                    if not shutil.which(tokens[0]) or not isinstance(hook.get("timeout"), (int, float)) or hook["timeout"] <= 0:
                        continue
                    covered.update(tool for tool in required if matcher.fullmatch(tool))
        return required <= covered
    except (OSError, ValueError, TypeError, re.error):
        return False


def _contains(path: Path, marker: str) -> bool:
    try:
        return marker in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def detect(repo: Path, tools: list[str] | None = None) -> dict:
    root = repo.resolve()
    if tools is None:
        answers_file = root / ".harness-setup" / "answers.json"
        if answers_file.is_file():
            try:
                data = json.loads(answers_file.read_text(encoding="utf-8"))
                tools = data.get("tools")
            except (OSError, ValueError):
                pass
        if not tools and (root / ".agents/hooks.json").is_file():
            tools = ["antigravity"]

    selected = sorted({str(item).strip().lower() for item in (tools or []) if str(item).strip()})
    by_host: dict[str, str] = {}
    for host in selected:
        if host in {"antigravity", "gemini-antigravity"}:
            hard = _antigravity_hooks_valid(root)
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
