"""Shared per-worktree lease for harness-owned Android build operations."""
from pathlib import Path
from _vnext_common import state_root
from evidence_store import StateLock


def build_lock(repo: Path) -> StateLock:
    return StateLock(state_root(repo) / "android-build-execution", timeout_seconds=0)
