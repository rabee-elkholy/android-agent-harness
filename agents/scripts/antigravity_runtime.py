"""Authoritative owner of Google Antigravity runtime-root and transcript resolution."""
from __future__ import annotations

import os
from pathlib import Path


def candidate_runtime_roots() -> tuple[Path, ...]:
    """Returns candidate runtime roots in precedence order.
    
    1. explicit ANTIGRAVITY_APP_DATA environment variable when present;
    2. ~/.gemini/antigravity;
    3. ~/.gemini/antigravity-cli;
    4. ~/.gemini/antigravity-ide.
    """
    roots: list[Path] = []
    override = os.environ.get("ANTIGRAVITY_APP_DATA")
    if override and override.strip():
        try:
            resolved_override = Path(override.strip()).expanduser().resolve()
            roots.append(resolved_override)
        except Exception:
            pass

    home = Path.home().resolve()
    for suffix in ("antigravity", "antigravity-cli", "antigravity-ide"):
        standard = (home / ".gemini" / suffix).resolve()
        if standard not in roots:
            roots.append(standard)

    return tuple(roots)


def candidate_brain_roots() -> tuple[Path, ...]:
    """Returns candidate brain roots corresponding to candidate runtime roots."""
    return tuple((root / "brain").resolve() for root in candidate_runtime_roots())


def is_trusted_antigravity_path(path: Path | str) -> bool:
    """Checks whether the given path resolves within any trusted brain root."""
    try:
        resolved = Path(path).expanduser().resolve()
        brain_roots = candidate_brain_roots()
        for brain_root in brain_roots:
            if resolved == brain_root or brain_root in resolved.parents:
                return True
        return False
    except Exception:
        return False


def _is_invalid_conversation_id(conversation_id: str) -> bool:
    if not conversation_id or not isinstance(conversation_id, str):
        return True
    if "\0" in conversation_id:
        return True
    cid = conversation_id.strip().strip("'\"")
    if not cid or len(cid) > 255:
        return True
    if "/" in cid or "\\" in cid or ".." in cid or ":" in cid or cid.startswith("file:"):
        return True
    try:
        if Path(cid).is_absolute():
            return True
    except Exception:
        return True
    return False


def resolve_transcript(conversation_id: str) -> Path | None:
    """Resolves a trusted subagent transcript for conversation_id.
    
    Rejects path traversal, slashes, colons, absolute paths, and URIs.
    Checks candidate brain roots in precedence order for:
      - <root>/brain/<id>/.system_generated/logs/transcript.jsonl
      - <root>/brain/<id>/transcript.jsonl
    """
    if _is_invalid_conversation_id(conversation_id):
        return None

    clean_id = conversation_id.strip().strip("'\"")
    brain_roots = candidate_brain_roots()

    for brain_root in brain_roots:
        candidates = [
            brain_root / clean_id / ".system_generated" / "logs" / "transcript.jsonl",
            brain_root / clean_id / "transcript.jsonl",
        ]
        for cand in candidates:
            try:
                resolved = cand.resolve()
                if brain_root in resolved.parents and resolved.is_file():
                    return resolved
            except Exception:
                continue

    return None
