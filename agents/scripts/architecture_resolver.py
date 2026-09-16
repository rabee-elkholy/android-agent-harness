"""Deterministic Architecture Resolver and Task Architecture Contract Generator.

Zero-dependency standard library Python engine providing deterministic mapping of task intent
and scope to an effective architecture contract and compact task brief.
No LLM calls, no network access, no heuristic majority voting.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from project_context import _canonical_json, extract_project_facts, project_context_status, resolve_feature_scope

RESOLVER_SCHEMA_VERSION = 1

INTENT_MAP = {
    "EXISTING_CHANGE": "PRESERVE",
    "NEW_SCREEN": "NEW",
    "NEW_FEATURE": "NEW",
    "REFACTOR": "REFACTOR",
    "MIGRATION": "MIGRATE",
}

STATUS_RESOLVED = "RESOLVED"
STATUS_DECISION_REQUIRED = "ARCHITECTURE_DECISION_REQUIRED"
STATUS_STALE_CONTEXT = "CONTEXT_STALE_FOR_NEW_CODE"
STATUS_INVALID_POLICY = "INVALID_POLICY"


def compute_contract_hash(contract: dict[str, Any]) -> str:
    """Computes SHA-256 over all contract fields except 'contract_sha256'."""
    filtered = {k: v for k, v in contract.items() if k != "contract_sha256"}
    canonical = _canonical_json(filtered)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_family_by_id(families: list[dict[str, Any]], family_id: str | None) -> dict[str, Any] | None:
    if not family_id:
        return None
    for f in families:
        if f.get("id") == family_id:
            return f
    return None


def _is_path_prefix(prefix_str: str, full_str: str) -> bool:
    p_parts = prefix_str.replace("\\", "/").strip("/").split("/")
    f_parts = full_str.replace("\\", "/").strip("/").split("/")
    if not p_parts or not f_parts:
        return False
    return p_parts == f_parts[:len(p_parts)]


def _is_path_component_submatch(sub_path: str, full_path: str) -> bool:
    s_parts = sub_path.replace("\\", "/").strip("/").split("/")
    f_parts = full_path.replace("\\", "/").strip("/").split("/")
    if not s_parts or not f_parts or len(s_parts) > len(f_parts):
        return False
    for i in range(len(f_parts) - len(s_parts) + 1):
        if f_parts[i : i + len(s_parts)] == s_parts:
            return True
    return False


def _common_path_parts_len(path1: str, path2: str) -> int:
    parts1 = path1.replace("\\", "/").strip("/").split("/")
    parts2 = path2.replace("\\", "/").strip("/").split("/")
    common_len = 0
    for p1, p2 in zip(parts1, parts2):
        if p1 == p2:
            common_len += 1
        else:
            break
    return common_len


def _find_family_for_scope(families: list[dict[str, Any]], target_scope: str) -> dict[str, Any] | None:
    norm_scope = target_scope.replace("\\", "/").strip("/")
    if not norm_scope:
        return families[0] if len(families) == 1 else None

    # 1. Exact exemplar match (screen / component level)
    exemplar_matches: list[dict[str, Any]] = []
    for f in families:
        for ex in f.get("exemplars") or []:
            ex_norm = ex.replace("\\", "/").strip("/")
            if norm_scope == ex_norm or _is_path_prefix(norm_scope, ex_norm) or _is_path_prefix(ex_norm, norm_scope):
                if f not in exemplar_matches:
                    exemplar_matches.append(f)
    if len(exemplar_matches) == 1:
        return exemplar_matches[0]
    elif len(exemplar_matches) > 1:
        return None

    # 2. Scope match via resolve_feature_scope
    resolved_scope = resolve_feature_scope(norm_scope)
    if resolved_scope:
        scope_matches: list[dict[str, Any]] = []
        for f in families:
            for sc in f.get("scopes") or []:
                sc_norm = sc.replace("\\", "/").strip("/")
                if sc_norm and (_is_path_prefix(sc_norm, resolved_scope) or _is_path_prefix(resolved_scope, sc_norm)):
                    if f not in scope_matches:
                        scope_matches.append(f)
        if len(scope_matches) == 1:
            return scope_matches[0]
        elif len(scope_matches) > 1:
            return None

    # 2.5 Path component submatch (no prefix clash)
    component_matches: list[dict[str, Any]] = []
    for f in families:
        matched_f = False
        for ex in f.get("exemplars") or []:
            if _is_path_component_submatch(norm_scope, ex):
                matched_f = True
                break
        if not matched_f:
            for sc in f.get("scopes") or []:
                if _is_path_component_submatch(norm_scope, sc):
                    matched_f = True
                    break
        if matched_f and f not in component_matches:
            component_matches.append(f)
    if len(component_matches) == 1:
        return component_matches[0]
    elif len(component_matches) > 1:
        return None

    # 3. Path component based prefix match
    best_matches: list[dict[str, Any]] = []
    max_depth = 0
    for f in families:
        f_best_depth = 0
        for ex in f.get("exemplars") or []:
            depth = _common_path_parts_len(ex, norm_scope)
            if depth > f_best_depth:
                f_best_depth = depth
        for sc in f.get("scopes") or []:
            depth = _common_path_parts_len(sc, norm_scope)
            if depth > f_best_depth:
                f_best_depth = depth

        if f_best_depth > max_depth:
            max_depth = f_best_depth
            best_matches = [f]
        elif f_best_depth == max_depth and f_best_depth > 0:
            if f not in best_matches:
                best_matches.append(f)

    if max_depth > 0 and len(best_matches) == 1:
        return best_matches[0]

    return None


def resolve_architecture_contract(
    repo: Path,
    *,
    architecture_intent: str = "EXISTING_CHANGE",
    target_scope: str = "",
    target_family_id: str | None = None,
    planning_depth: str = "BOUNDED",
    intent: str | None = None,
) -> dict[str, Any]:
    if intent is not None:
        architecture_intent = intent
    """Deterministically resolves the architecture contract for a task.

    Returns a dict with:
      - status: RESOLVED | ARCHITECTURE_DECISION_REQUIRED | CONTEXT_STALE_FOR_NEW_CODE | INVALID_POLICY
      - mode: PRESERVE | NEW | REFACTOR | MIGRATE
      - contract: dict | None
      - brief_markdown: str | None
      - message: str
    """
    repo = repo.resolve()
    mode = INTENT_MAP.get(architecture_intent.upper(), "PRESERVE")

    # Load facts
    facts_file = repo / ".agents" / "project-context" / "project-facts.json"
    facts_payload = {}
    if facts_file.is_file():
        try:
            facts_payload = json.loads(facts_file.read_text(encoding="utf-8"))
        except Exception:
            facts_payload = {}

    if not facts_payload:
        facts_payload = extract_project_facts(repo, in_memory_graph=True)

    facts = facts_payload.get("facts") or {}
    arch = facts.get("architecture") or {}
    families = arch.get("families") or []

    # Check freshness
    ctx_status = project_context_status(repo)
    is_stale = ctx_status.get("status") == "STALE"

    if is_stale and mode in ("NEW", "MIGRATE"):
        return {
            "status": STATUS_STALE_CONTEXT,
            "mode": mode,
            "contract": None,
            "brief_markdown": None,
            "message": "Project context is stale; refresh context before planning new or migrated architecture.",
        }

    # Load developer evolution policy
    from architecture_policy import read_architecture_policy, validate_architecture_policy
    policy = read_architecture_policy(repo)
    if policy:
        val_ok, val_err = validate_architecture_policy(policy, facts=facts_payload)
        if not val_ok:
            return {
                "status": STATUS_INVALID_POLICY,
                "mode": mode,
                "contract": None,
                "brief_markdown": None,
                "message": f"Developer architecture policy is invalid: {val_err}",
            }

    source_family: dict[str, Any] | None = None
    target_family: dict[str, Any] | None = None
    compat_boundaries: list[str] = []

    if mode in ("PRESERVE", "REFACTOR"):
        # Resolve local source family
        matched = _find_family_for_scope(families, target_scope)
        if matched:
            source_family = matched
            target_family = matched
        elif len(families) == 1:
            source_family = families[0]
            target_family = families[0]
        elif len(families) > 1:
            # Ambiguous target with multiple candidates
            return {
                "status": STATUS_DECISION_REQUIRED,
                "mode": mode,
                "contract": None,
                "brief_markdown": None,
                "message": f"Multiple architecture families exist and target scope '{target_scope}' is ambiguous.",
            }
        else:
            # Zero detected families: synthesize empty/standard contract
            source_family = None
            target_family = None

    elif mode == "NEW":
        matched_scope_family = _find_family_for_scope(families, target_scope)
        preferred_id = policy.get("preferred_new_code_family") if policy else None
        target_id = target_family_id or preferred_id or (matched_scope_family.get("id") if matched_scope_family else None)
        if not target_id:
            return {
                "status": STATUS_DECISION_REQUIRED,
                "mode": mode,
                "contract": None,
                "brief_markdown": None,
                "message": "No preferred or explicit target architecture family configured for new code. Developer decision required.",
            }
        target_family = matched_scope_family if (matched_scope_family and matched_scope_family.get("id") == target_id) else _find_family_by_id(families, target_id)
        if not target_family:
            return {
                "status": STATUS_DECISION_REQUIRED,
                "mode": mode,
                "contract": None,
                "brief_markdown": None,
                "message": f"Configured architecture family '{target_id}' not found in active architecture inventory.",
            }
        # Check surrounding local scope for compatibility boundary
        surrounding_fam = _find_family_for_scope(families, target_scope)
        if surrounding_fam and surrounding_fam.get("id") != target_family.get("id"):
            surrounding_nav = (surrounding_fam.get("dimensions") or {}).get("navigation")
            surrounding_toolkit = (surrounding_fam.get("dimensions") or {}).get("ui_toolkit")
            if surrounding_nav != (target_family.get("dimensions") or {}).get("navigation"):
                compat_boundaries.append(f"Host feature uses {surrounding_nav}; use minimal compatibility bridge.")
            elif surrounding_toolkit != (target_family.get("dimensions") or {}).get("ui_toolkit"):
                compat_boundaries.append(f"Surrounding feature uses {surrounding_toolkit}; host in compatibility container without modifying legacy siblings.")

    elif mode == "MIGRATE":
        if planning_depth.upper() != "ARCHITECTURAL":
            return {
                "status": STATUS_DECISION_REQUIRED,
                "mode": mode,
                "contract": None,
                "brief_markdown": None,
                "message": "Architecture migration requires planning_depth=ARCHITECTURAL.",
            }
        # Resolve source family
        matched = _find_family_for_scope(families, target_scope)
        source_family = matched or (families[0] if len(families) == 1 else None)
        if not source_family:
            return {
                "status": STATUS_DECISION_REQUIRED,
                "mode": mode,
                "contract": None,
                "brief_markdown": None,
                "message": "Cannot identify source architecture family for migration.",
            }
        # Resolve target family
        t_id = target_family_id or (policy.get("preferred_new_code_family") if policy else None)
        target_family = _find_family_by_id(families, t_id)
        if not target_family:
            return {
                "status": STATUS_DECISION_REQUIRED,
                "mode": mode,
                "contract": None,
                "brief_markdown": None,
                "message": "Explicit target architecture family required for migration.",
            }
        if len(families) > 1 and source_family.get("id") == target_family.get("id"):
            return {
                "status": STATUS_DECISION_REQUIRED,
                "mode": mode,
                "contract": None,
                "brief_markdown": None,
                "message": "Source and target architecture families must differ for migration.",
            }

    # Build contract
    exemplars = (target_family.get("exemplars") or []) if target_family else []
    contract: dict[str, Any] = {
        "schema_version": RESOLVER_SCHEMA_VERSION,
        "mode": mode,
        "target_scope": target_scope,
        "source_family_id": source_family.get("id") if source_family else None,
        "target_family_id": target_family.get("id") if target_family else None,
        "family_signature_sha256": target_family.get("signature_sha256") if target_family else "",
        "source_dimensions": (source_family.get("dimensions") or {}) if source_family else {},
        "target_dimensions": (target_family.get("dimensions") or {}) if target_family else {},
        "migration_allowed": (mode == "MIGRATE"),
        "compatibility_boundaries": sorted(compat_boundaries),
        "exemplar_paths": sorted(exemplars)[:5],
        "resolution_confidence": "HIGH" if (target_family or mode == "PRESERVE") else "MEDIUM",
    }
    contract["contract_sha256"] = compute_contract_hash(contract)

    # Generate compact brief (100–250 words)
    brief_md = generate_task_architecture_brief(contract, target_family, source_family)

    return {
        "status": STATUS_RESOLVED,
        "mode": mode,
        "contract": contract,
        "brief_markdown": brief_md,
        "message": f"Successfully resolved architecture contract for {mode} mode.",
    }


def generate_task_architecture_brief(
    contract: dict[str, Any],
    target_family: dict[str, Any] | None,
    source_family: dict[str, Any] | None,
) -> str:
    """Generates a compact, unambiguous ~150-word brief for the implementing model."""
    mode = contract.get("mode", "PRESERVE")
    target_scope = contract.get("target_scope") or "entire task scope"
    target_label = target_family.get("label", "standard") if target_family else "project local"
    source_label = source_family.get("label", "standard") if source_family else target_label
    exemplars = contract.get("exemplar_paths") or []

    lines = [
        "# Task Architecture Brief",
        "",
        f"- **Architecture Mode**: `{mode}`",
        f"- **Target Scope**: `{target_scope}`",
    ]

    if mode in ("PRESERVE", "REFACTOR"):
        lines.extend([
            f"- **Active Local Family**: `{source_label}`",
            "- **Rule**: Preserve this local family. Do not modernize or convert UI toolkit, ViewModel base, or state stream.",
            "- **Forbidden**: Converting XML to Compose, replacing BaseViewModel with MviViewModel, or LiveData to StateFlow unless explicitly approved in a MIGRATE task.",
        ])
    elif mode == "NEW":
        lines.extend([
            f"- **Target Family**: `{target_label}`",
            "- **Rule**: Build the new screen/feature using this preferred family.",
            "- **Boundary Rule**: Surrounding legacy code serves only as a compatibility boundary. Do not convert neighboring legacy screens.",
        ])
        for b in contract.get("compatibility_boundaries") or []:
            lines.append(f"- **Compatibility Constraint**: {b}")
    elif mode == "MIGRATE":
        lines.extend([
            f"- **Source Family**: `{source_label}`",
            f"- **Target Family**: `{target_label}`",
            "- **Rule**: Execute architectural migration strictly within the approved target scope.",
            "- **Scope Rule**: Do not migrate components outside the approved scope.",
        ])

    if exemplars:
        lines.extend(["", "## Reference Exemplars"])
        for ex in exemplars:
            lines.append(f"- [`{ex}`](file:///{ex})")

    lines.append("")
    return "\n".join(lines)
