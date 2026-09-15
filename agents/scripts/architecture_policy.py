"""Developer Evolution Policy management for Android Agent Harness.

Provides schema validation, canonical hashing, and safe reading/writing of
.agents/project-context/architecture-policy.json.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

POLICY_FILE_NAME = "architecture-policy.json"
POLICY_SCHEMA_VERSION = 1

VALID_EXISTING_POLICIES = {"PRESERVE_LOCAL_FAMILY"}
VALID_NEW_POLICIES = {"PREFERRED_FAMILY"}
VALID_REFACTOR_POLICIES = {"PRESERVE_LOCAL_FAMILY"}
VALID_IMPLICIT_MIGRATION = {"FORBIDDEN"}


def _canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_policy_hash(policy: dict[str, Any]) -> str:
    """Computes SHA-256 over all policy fields except 'policy_sha256'."""
    filtered = {k: v for k, v in policy.items() if k != "policy_sha256"}
    canonical = _canonical_json(filtered)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_architecture_policy(
    preferred_new_code_family: str | None = None,
    *,
    existing_code_policy: str = "PRESERVE_LOCAL_FAMILY",
    new_screen_policy: str = "PREFERRED_FAMILY",
    new_feature_policy: str = "PREFERRED_FAMILY",
    refactor_policy: str = "PRESERVE_LOCAL_FAMILY",
    implicit_family_migration: str = "FORBIDDEN",
) -> dict[str, Any]:
    """Creates a new validated architecture policy dictionary with canonical hash."""
    policy: dict[str, Any] = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "preferred_new_code_family": preferred_new_code_family,
        "existing_code_policy": existing_code_policy,
        "new_screen_policy": new_screen_policy,
        "new_feature_policy": new_feature_policy,
        "refactor_policy": refactor_policy,
        "implicit_family_migration": implicit_family_migration,
    }
    policy["policy_sha256"] = compute_policy_hash(policy)
    return policy


def validate_architecture_policy(policy: dict[str, Any], facts: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Validates the schema, field values, hash, and family references of a policy."""
    if not isinstance(policy, dict):
        return False, "policy is not a dictionary"

    if "_parse_error" in policy:
        return False, f"malformed architecture-policy.json: {policy.get('_parse_error')}"

    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        return False, f"unsupported policy schema_version: {policy.get('schema_version')}"

    if policy.get("existing_code_policy") not in VALID_EXISTING_POLICIES:
        return False, f"invalid existing_code_policy: {policy.get('existing_code_policy')}"

    if policy.get("new_screen_policy") not in VALID_NEW_POLICIES:
        return False, f"invalid new_screen_policy: {policy.get('new_screen_policy')}"

    if policy.get("new_feature_policy") not in VALID_NEW_POLICIES:
        return False, f"invalid new_feature_policy: {policy.get('new_feature_policy')}"

    if policy.get("refactor_policy") not in VALID_REFACTOR_POLICIES:
        return False, f"invalid refactor_policy: {policy.get('refactor_policy')}"

    if policy.get("implicit_family_migration") not in VALID_IMPLICIT_MIGRATION:
        return False, f"invalid implicit_family_migration: {policy.get('implicit_family_migration')}"

    recorded_hash = policy.get("policy_sha256")
    if not recorded_hash or not isinstance(recorded_hash, str):
        return False, "missing or invalid policy_sha256"

    expected_hash = compute_policy_hash(policy)
    if recorded_hash != expected_hash:
        return False, f"policy_sha256 mismatch (recorded: {recorded_hash[:12]}..., expected: {expected_hash[:12]}...)"

    # Optional cross-check against project facts
    pref_family = policy.get("preferred_new_code_family")
    if pref_family is not None and facts:
        arch = facts.get("architecture") if "architecture" in facts else (facts.get("facts") or {}).get("architecture") or {}
        families = arch.get("families") or []
        family_ids = {f.get("id") for f in families if isinstance(f, dict)}
        if family_ids and pref_family not in family_ids:
            return False, f"preferred_new_code_family '{pref_family}' not found in active architecture inventory"

    return True, "valid"


def read_architecture_policy(repo: Path) -> dict[str, Any] | None:
    """Reads architecture-policy.json if present on disk."""
    policy_path = repo / ".agents" / "project-context" / POLICY_FILE_NAME
    if not policy_path.is_file():
        return None
    try:
        return json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_parse_error": str(exc), "schema_version": -1}


def write_architecture_policy(repo: Path, policy: dict[str, Any], *, overwrite: bool = False) -> Path:
    """Atomically writes architecture-policy.json to .agents/project-context/."""
    context_dir = repo / ".agents" / "project-context"
    context_dir.mkdir(parents=True, exist_ok=True)
    policy_path = context_dir / POLICY_FILE_NAME

    if policy_path.exists() and not overwrite:
        return policy_path

    # Ensure hash is fresh
    policy["policy_sha256"] = compute_policy_hash(policy)

    content = json.dumps(policy, ensure_ascii=False, indent=2) + "\n"
    tmp_path = context_dir / f".{POLICY_FILE_NAME}.tmp.{os.getpid()}"
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, policy_path)
    return policy_path
