"""Trusted review execution source adapter and registry."""
from __future__ import annotations

import os
import ast
import re
from pathlib import Path
from typing import Protocol


class TrustedReviewSource(Protocol):
    def resolve(self, execution_id: str) -> Path | None:
        ...


class AntigravityReviewSource:
    def resolve(self, execution_id: str) -> Path | None:
        from antigravity_runtime import resolve_transcript
        return resolve_transcript(execution_id)


TRUSTED_REVIEW_SOURCES: dict[str, TrustedReviewSource] = {
    "antigravity": AntigravityReviewSource(),
}


def primary_host_from_tools(tools: list[str] | tuple[str, ...] | str | None) -> str:
    selected = [str(part).strip().lower() for part in (tools.split(",") if isinstance(tools, str) else tools or []) if str(part).strip()]
    if "antigravity" in selected:
        return "antigravity"
    supported = {"claude", "codex", "cursor", "windsurf", "copilot", "continue", "qwen", "junie", "kilocode", "roo", "goose", "amazonq"}
    return selected[0] if len(selected) == 1 and selected[0] in supported else "generic"


def resolve_review_host(repo: Path, explicit: str | None = None) -> str:
    """Resolve a frozen review host without executing installed configuration code."""
    for value in (explicit, os.environ.get("HARNESS_HOST")):
        if value and str(value).strip():
            host = str(value).strip().lower()
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", host):
                raise ValueError(f"invalid review host '{value}'")
            return host
    product_file = repo / ".agents" / "scripts" / "_product.py"
    if product_file.is_file():
        try:
            tree = ast.parse(product_file.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    if node.targets[0].id == "PRIMARY_AI_HOST":
                        host = ast.literal_eval(node.value)
                        if isinstance(host, str) and re.fullmatch(r"[a-z][a-z0-9_-]*", host):
                            return host
        except (OSError, SyntaxError, ValueError, TypeError):
            pass
    return "generic"


def has_trusted_review_source(host: str) -> bool:
    return (host or "").strip().lower() in TRUSTED_REVIEW_SOURCES


def resolve_trusted_review_source(host: str, execution_id: str) -> Path | None:
    host_key = (host or "").strip().lower()
    source = TRUSTED_REVIEW_SOURCES.get(host_key)
    if not source:
        return None
    return source.resolve(execution_id)


# Claude Code writes subagent transcripts as JSONL under its projects directory, and background
# task output (`tasks/<id>.output`) under a `claude-*` directory in the system temp directory.
# Reading one gives an unchanged reviewer response; it is not proof of independent execution.
CLAUDE_TRANSCRIPT_LOCATIONS = "~/.claude/projects/**/*.jsonl or <tmp>/claude-*/**/tasks/*.output"


def _claude_transcript_location_allowed(path: Path) -> bool:
    import tempfile
    resolved = path.resolve()
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    try:
        if resolved.suffix in (".jsonl", ".output") and resolved.relative_to((home / "projects").resolve()).parts:
            return True
    except ValueError:
        pass
    if resolved.suffix != ".output" or resolved.parent.name != "tasks":
        return False
    temp_roots = {Path(tempfile.gettempdir()).resolve()}
    if os.name != "nt":
        temp_roots.add(Path("/tmp").resolve())
    for root in temp_roots:
        try:
            parts = resolved.relative_to(root).parts
        except ValueError:
            continue
        if len(parts) >= 3 and parts[0].startswith("claude-"):
            return True
    return False


def _claude_transcript_entries(raw: str) -> list[dict] | None:
    """Parsed JSONL lines when the text is a Claude Code transcript, else None."""
    import json
    entries = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            return None
        if not isinstance(entry, dict):
            return None
        entries.append(entry)
    is_claude = any(entry.get("type") == "assistant" and isinstance(entry.get("message"), dict) for entry in entries)
    return entries if is_claude else None


def find_claude_subagent_transcript(agent_id: str) -> Path | None:
    """The transcript of a Claude Code subagent, found by its agent id in Claude's projects directory."""
    value = str(agent_id or "").strip()
    if value.startswith("agent-"):
        value = value[len("agent-"):]
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", value):
        return None
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    matches = [path for path in (home / "projects").glob(f"*/*/subagents/agent-{value}.jsonl") if path.is_file()]
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def is_claude_transcript(path: Path) -> bool:
    try:
        return path.is_file() and _claude_transcript_entries(path.read_text(encoding="utf-8", errors="replace")) is not None
    except OSError:
        return False


def read_claude_subagent_transcript(path: Path) -> tuple[str, dict]:
    """Return the last assistant text of a Claude Code subagent transcript and its identity.

    Only Claude's own transcript locations are accepted, so the agent cannot hand in a file it
    wrote. The identity (path, sha256) is recorded; independent execution stays unverified.
    """
    import hashlib
    from _vnext_common import ValidationError
    if not path.is_file():
        raise ValidationError(f"Claude subagent transcript not found: {path}")
    if not _claude_transcript_location_allowed(path):
        raise ValidationError(
            f"Claude subagent transcript {path} is outside Claude's transcript locations "
            f"({CLAUDE_TRANSCRIPT_LOCATIONS}); pass the transcript path Claude Code reported for the reviewer"
        )
    data = path.read_bytes()
    entries = _claude_transcript_entries(data.decode("utf-8", errors="replace"))
    if entries is None:
        raise ValidationError(f"{path} is not a Claude Code transcript (JSONL with assistant messages)")

    def text_of(entry: dict) -> str:
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        return "".join(
            str(block.get("text") or "") for block in content or []
            if isinstance(block, dict) and block.get("type") == "text"
        )

    # A failed API call is recorded as an assistant line with isApiErrorMessage; it is not a reply.
    assistant = [
        entry for entry in entries
        if entry.get("type") == "assistant" and isinstance(entry.get("message"), dict) and not entry.get("isApiErrorMessage")
    ]
    last = next((entry for entry in reversed(assistant) if text_of(entry).strip()), None)
    if last is None:
        raise ValidationError(f"Claude subagent transcript {path} has no assistant text")
    message_id = (last.get("message") or {}).get("id")
    # Claude writes one line per content block; the reply is every text block of the last message.
    parts = [text_of(entry) for entry in assistant if message_id and (entry.get("message") or {}).get("id") == message_id]
    text = "".join(parts) if parts else text_of(last)
    return text, {
        "transcript_path": str(path.resolve()),
        "transcript_sha256": hashlib.sha256(data).hexdigest(),
    }
