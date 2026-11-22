"""Short-lived PM write grants from explicit developer confirmation.

Supports any Project Management MCP installed in Antigravity (Zoho Sprints,
Zoho Projects, Jira, Linear, Monday, GitHub Projects, ClickUp, Asana, Trello,
etc.). Terminal status transitions require explicit `--allow-close`
authorization rather than prose keyword matching.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

GRANT_FILE = "pm-write-grant.json"
LEGACY_GRANT_FILE = "zoho-write-grant.json"
GRANT_TTL_SECONDS = 30 * 60


def _resolve_providers(explicit_provider: str = "all") -> list[str]:
    norm = str(explicit_provider or "").strip().lower()
    if not norm or norm in ("all", "auto", "*", "pm", "any"):
        return ["all"]
    return [norm]


def _state(repo: Path) -> Path:
    for candidate in (repo / ".agents" / "state", repo / "agents" / "state"):
        if candidate.parent.is_dir():
            return candidate
    return repo / ".agents" / "state"


def record_pm_grant(
    repo: Path,
    proof_reference: str,
    provider: str = "all",
    source: str = "conversation",
    *,
    allow_close: bool = False,
) -> dict:
    """Record a universal PM write grant for any installed PM MCP."""
    from _vnext_common import ValidationError, atomic_write_json, utc_now

    # Support legacy positional call pattern: record_pm_grant(repo, "conversation", "<proof>")
    if (
        proof_reference in ("conversation", "developer_terminal", "host_native")
        and provider not in ("all", "auto", "*")
        and source == "conversation"
    ):
        source, proof_reference, provider = proof_reference, provider, "all"

    norm_source = str(source or "").strip().lower()
    if norm_source not in ("conversation", "developer_terminal", "host_native"):
        raise ValidationError(
            "PM_GRANT_INVALID_SOURCE: `--source` must be `conversation` or `developer_terminal`."
        )

    proof = " ".join(str(proof_reference or "").split())
    if len(proof) < 2:
        raise ValidationError(
            "PM_GRANT_NEEDS_CONFIRMATION: `--proof-reference` must contain the developer's explicit "
            "confirmation after reviewing the PM preview."
        )
    if proof.rstrip().endswith(("?", "\u061f")):
        raise ValidationError(
            "PM_GRANT_NEEDS_CONFIRMATION: `--proof-reference` appears to be an unanswered question "
            "rather than explicit developer confirmation."
        )

    providers = _resolve_providers(provider)
    grant = {
        "schema_version": 1,
        "source": norm_source,
        "proof_reference": proof[:500],
        "providers": providers,
        "allow_close": bool(allow_close),
        "granted_at": utc_now(),
        "granted_epoch": time.time(),
        "expires_epoch": time.time() + GRANT_TTL_SECONDS,
    }
    state = _state(repo)
    state.mkdir(parents=True, exist_ok=True)
    atomic_write_json(state / GRANT_FILE, grant)
    return grant


def record_grant(
    repo: Path,
    proof_reference: str,
    source: str = "conversation",
    *,
    allow_close: bool = False,
) -> dict:
    """Record a short-lived PM write grant from the developer's explicit confirmation."""
    return record_pm_grant(
        repo,
        proof_reference,
        provider="all",
        source=source,
        allow_close=allow_close,
    )


def active_grant(repo: Path) -> dict | None:
    """Return the unexpired PM write grant (with legacy filename fallback), or None."""
    state = _state(repo)
    grant_path = state / GRANT_FILE
    if not grant_path.is_file():
        legacy_path = state / LEGACY_GRANT_FILE
        if legacy_path.is_file():
            grant_path = legacy_path
    try:
        data = json.loads(grant_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    try:
        if float(data.get("expires_epoch") or 0) <= time.time():
            return None
        if float(data.get("expires_epoch") or 0) - float(data.get("granted_epoch") or 0) > GRANT_TTL_SECONDS + 1:
            return None
    except (TypeError, ValueError):
        return None
    proof = " ".join(str(data.get("proof_reference") or "").split())
    if len(proof) < 2 or proof.rstrip().endswith(("?", "\u061f")):
        return None
    return data


def active_pm_grant(repo: Path, provider: str | None = None) -> dict | None:
    """Return the active PM write grant if unexpired and matching `provider` (or `'all'`)."""
    data = active_grant(repo)
    if not data:
        return None
    if not provider:
        return data
    allowed_providers = data.get("providers") or ["all"]
    if "all" in allowed_providers or provider.lower() in allowed_providers:
        return data
    return None


def pm_authorize_command(provider: str = "pm") -> str:
    """Return the canonical CLI command to record developer confirmation for PM writes."""
    norm = str(provider or "").strip().lower()
    if norm and norm not in ("pm", "all", "auto", "*"):
        return f'python .agents/harness.py pm authorize --provider {norm} --source conversation --proof-reference "<developer confirmation>"'
    return 'python .agents/harness.py pm authorize --source conversation --proof-reference "<developer confirmation>"'


def authorize_command() -> str:
    return pm_authorize_command()
