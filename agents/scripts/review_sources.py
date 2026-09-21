"""Trusted review execution source adapter and registry."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class TrustedReviewSource(Protocol):
    def resolve(self, execution_id: str) -> Path | None:
        ...


class AntigravityReviewSource:
    def resolve(self, execution_id: str) -> Path | None:
        if not execution_id:
            return None
        clean_id = str(execution_id).strip().strip("'\"")
        if "/" in clean_id or "\\" in clean_id or ".." in clean_id or ":" in clean_id or clean_id.startswith("file:"):
            return None

        app_data = os.environ.get("ANTIGRAVITY_APP_DATA")
        base_root = Path(app_data).resolve() if app_data else (Path.home() / ".gemini" / "antigravity").resolve()
        brain_dir = (base_root / "brain").resolve()
        candidates = [
            brain_dir / clean_id / ".system_generated" / "logs" / "transcript.jsonl",
            brain_dir / clean_id / "transcript.jsonl",
        ]
        for cand in candidates:
            try:
                resolved = cand.resolve()
                if brain_dir in resolved.parents and resolved.is_file():
                    return resolved
            except Exception:
                continue
        return None


TRUSTED_REVIEW_SOURCES: dict[str, TrustedReviewSource] = {
    "antigravity": AntigravityReviewSource(),
}


def has_trusted_review_source(host: str) -> bool:
    return (host or "").strip().lower() in TRUSTED_REVIEW_SOURCES


def resolve_trusted_review_source(host: str, execution_id: str) -> Path | None:
    host_key = (host or "").strip().lower()
    source = TRUSTED_REVIEW_SOURCES.get(host_key)
    if not source:
        return None
    return source.resolve(execution_id)
