"""Trusted review execution source adapter and registry."""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Protocol

from _vnext_common import ValidationError


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
    selected = [
        str(part).strip().lower()
        for part in (tools.split(",") if isinstance(tools, str) else tools or [])
        if str(part).strip()
    ]
    if "antigravity" in selected:
        return "antigravity"
    if "gemini" in selected:
        return "gemini"
    return "generic"


def detected_current_host() -> str | None:
    """Declared host identity via HARNESS_HOST."""
    value = os.environ.get("HARNESS_HOST")
    if value and value.strip():
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
            raise ValidationError(f"invalid review host '{value}'")
        return value
    return None


def resolve_review_host(repo: Path, explicit: str | None = None) -> str:
    """Resolve a frozen review host without executing installed configuration code."""
    if explicit and str(explicit).strip():
        host = str(explicit).strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", host):
            raise ValidationError(f"invalid review host '{explicit}'")
        return host
    detected = detected_current_host()
    if detected:
        return detected
    from _vnext_common import state_root
    active = state_root(repo) / "active-task.json"
    if active.exists():
        from _vnext_common import read_json, validate_id
        task_id = validate_id(str(read_json(active).get("task_id") or ""))
        from host_continuation import load_session
        session = load_session(repo, task_id)
        if session:
            return session["host"]
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
