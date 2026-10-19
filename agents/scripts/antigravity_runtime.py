"""Authoritative owner of Google Antigravity runtime-root and transcript resolution."""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from _vnext_common import ValidationError, canonical_sha256


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
        except (OSError, ValueError, RuntimeError):
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


def _protobuf_fields(data: bytes) -> dict[int, list]:
    """Read only protobuf wire types; never deserialize or execute host payloads."""
    fields: dict[int, list] = {}
    offset = 0

    def integer() -> int:
        nonlocal offset
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(data):
                raise ValueError("truncated native metadata")
            byte = data[offset]
            offset += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError("invalid native metadata varint")

    while offset < len(data):
        tag = integer()
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError("invalid native metadata field")
        if wire == 0:
            value = integer()
        elif wire in (1, 2, 5):
            length = integer() if wire == 2 else (8 if wire == 1 else 4)
            if length > len(data) - offset:
                raise ValueError("truncated native metadata field")
            value = data[offset:offset + length]
            offset += length
        else:
            raise ValueError("unsupported native metadata wire type")
        fields.setdefault(field, []).append(value)
    return fields


def _native_model_field(blob: bytes, path: tuple[int, ...]) -> str | None:
    value = blob
    for field in path:
        values = _protobuf_fields(value).get(field, [])
        if not values:
            return None
        if len(values) != 1 or not isinstance(values[0], bytes):
            raise ValueError("ambiguous native model metadata")
        value = values[0]
    model = value.decode("ascii")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,127}", model):
        raise ValueError("invalid native model identifier")
    return model


def native_model_metadata(transcript: Path) -> dict:
    """Read observed Antigravity model fields from this execution's native DB.

    Known field paths are intentionally explicit. An unknown schema produces no
    model proof; prompt text and reviewer claims are never searched for models.
    """
    resolved = Path(transcript).resolve()
    root = next((p for p in candidate_brain_roots() if p in resolved.parents), None)
    if root is None:
        raise ValidationError("REVIEW_MODEL_UNVERIFIED: transcript is outside trusted Antigravity storage")
    parts = resolved.relative_to(root).parts
    execution_id = parts[0]
    canonical = resolve_transcript(execution_id)
    if canonical is None or canonical.resolve() != resolved:
        raise ValidationError("REVIEW_MODEL_UNVERIFIED: model proof requires the canonical execution transcript")
    database = root.parent / "conversations" / f"{execution_id}.db"
    if database.is_symlink() or not database.resolve().is_relative_to(root.parent.resolve()) or not database.is_file():
        return {}
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as connection:
            configured_rows = connection.execute("SELECT data FROM executor_metadata WHERE idx = 0").fetchall()
            generation_rows = connection.execute("SELECT data FROM gen_metadata ORDER BY idx LIMIT 4097").fetchall()
        if len(generation_rows) > 4096 or any(not isinstance(r[0], bytes) or len(r[0]) > 32 * 1024 * 1024 for r in configured_rows + generation_rows):
            raise ValueError("native metadata exceeds inspection limits")
        configured = {_native_model_field(r[0], (10, 1, 28)) for r in configured_rows} - {None}
        observed = {_native_model_field(r[0], (1, 19)) for r in generation_rows} - {None}
        if len(configured) != 1 or not observed:
            return {}
        result = {"execution_id": execution_id, "host_configured_model": next(iter(configured)),
                  "host_reported_models": sorted(observed), "native_metadata_source": "antigravity_execution_database"}
        result["native_metadata_sha256"] = canonical_sha256(result)
        return result
    except (sqlite3.Error, OSError, ValueError, UnicodeError) as exc:
        raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: native model metadata is unavailable or unsupported: {type(exc).__name__}") from exc
