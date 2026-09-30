"""A short-lived Zoho write grant from the developer's explicit `update zoho`.

Real app: after the code was committed, the developer reviewed the proposed Zoho text and typed
`update zoho`; the only way to write was to revise the code plan with --external-write zoho_sprints
and approve it again, which re-entered the plan and review loop for a tracker update. The
developer's `update zoho` is itself the approval the Zoho rules ask for, so it now grants Zoho
writes for a short time without touching the plan. Every other Zoho rule still applies (an
operation id per write, no Done/Solved, no edit of a Bug's description).
"""
from __future__ import annotations

import time
from pathlib import Path

GRANT_FILE = "zoho-write-grant.json"
GRANT_TTL_SECONDS = 30 * 60
TRIGGER = "update zoho"


def _state(repo: Path) -> Path:
    for candidate in (repo / ".agents" / "state", repo / "agents" / "state"):
        if candidate.parent.is_dir():
            return candidate
    return repo / ".agents" / "state"


def record_grant(repo: Path, proof_reference: str, source: str = "conversation") -> dict:
    """Record a grant; the proof must be the developer's message containing `update zoho`."""
    from _vnext_common import ValidationError, atomic_write_json, utc_now

    proof = " ".join(str(proof_reference or "").split())
    if TRIGGER not in proof.lower():
        raise ValidationError(
            f"ZOHO_GRANT_NEEDS_UPDATE_ZOHO: the proof must be the developer's message containing `{TRIGGER}`; "
            "show the developer what will be written first and wait for it."
        )
    grant = {
        "schema_version": 1,
        "source": source,
        "proof_reference": proof[:500],
        "granted_at": utc_now(),
        "granted_epoch": time.time(),
        "expires_epoch": time.time() + GRANT_TTL_SECONDS,
    }
    state = _state(repo)
    state.mkdir(parents=True, exist_ok=True)
    atomic_write_json(state / GRANT_FILE, grant)
    return grant


def active_grant(repo: Path) -> dict | None:
    """The unexpired grant, or None."""
    import json

    try:
        data = json.loads((_state(repo) / GRANT_FILE).read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        if float(data.get("expires_epoch") or 0) <= time.time():
            return None
        if float(data.get("expires_epoch") or 0) - float(data.get("granted_epoch") or 0) > GRANT_TTL_SECONDS + 1:
            return None
    except (TypeError, ValueError):
        return None
    if TRIGGER not in str(data.get("proof_reference") or "").lower():
        return None
    return data


def authorize_command() -> str:
    return 'python .agents/harness.py zoho authorize --proof-reference "<the developer\'s message with update zoho>"'
