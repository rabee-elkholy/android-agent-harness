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
        from antigravity_runtime import resolve_transcript
        return resolve_transcript(execution_id)


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
