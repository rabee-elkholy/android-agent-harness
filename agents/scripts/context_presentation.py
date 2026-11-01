"""Bounded advisory architecture and explicit context compaction; no authority."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def architecture_context(payload):
    target = payload.get("target") or {}
    relationships = []
    for key, direction in (("direct_dependencies", "dependency"), ("direct_dependents", "dependent")):
        for node in payload.get(key) or []:
            path = node.get("file_path") or node.get("path")
            if path and not Path(path).is_absolute() and ".." not in Path(path).parts:
                relationships.append({"path": path, "symbol": node.get("name", ""),
                                      "relationship": direction, "derivation": "NATIVE_GRAPH", "confidence": "HEURISTIC"})
    profiles = payload.get("local_profiles") or []
    contract = payload.get("architecture_contract") or {}
    value = {"schema_version": 1, "status": "PARTIAL" if target else "UNAVAILABLE",
             "graph_fingerprint": (payload.get("graph_basis") or {}).get("graph_fingerprint"),
             "target_modules": [target["module"]] if target.get("module") else [],
             "source_sets": [target["source_set"]] if target.get("source_set") else [],
             "local_families": sorted({p.get("family_id", "UNKNOWN") for p in profiles}),
             "relevant_relationships": relationships[:12],
             "representative_existing_patterns": sorted({x for p in profiles for x in p.get("paths", []) if isinstance(x, str)})[:5],
             "affected_tests": (payload.get("tests") or [])[:8],
             "compatibility_boundaries": contract.get("compatibility_boundaries") or payload.get("interop_boundaries") or [],
             "warnings": payload.get("warnings") or [],
             "unknowns": ["Graph relationships are heuristic; test candidates do not prove complete coverage.",
                          "Platform implementations not present in this slice require normal graph expansion."],
             "truncated": len(relationships) > 12 or bool(payload.get("graph_expansion_required")),
             "omitted_counts": {"relationships": max(0, len(relationships)-12), "tests": max(0, len(payload.get("tests") or [])-8)},
             "scope_authorization": False}
    if contract.get("contract_sha256"):
        value["contract_sha256"] = contract["contract_sha256"]
    if not profiles:
        value["unknowns"].append("No current validated local architecture profile is available.")
    if len(_encoded(value)) > 8192:
        return {"schema_version": 1, "status": "PARTIAL", "truncated": True,
                "scope_authorization": False, "warnings": ["Architecture summary exceeded 8 KiB; read the full context warnings and contract."],
                "unknowns": ["No complete bounded architecture summary available."]}
    return value


def present_context(repo, payload, *, since=None):
    # Native dictionaries stay complete. Receipts remain independently validated.
    def semantic(row):
        result = {k: v for k, v in row.items() if k not in {"graph_sync", "context_id", "discovery"}}
        if "discovery" in row:
            result["discovery_scope"] = {k: v for k, v in row["discovery"].items()
                if k not in {"created_at", "timestamp", "receipt_id", "expires_at"}}
        if "results" in result:
            result["results"] = [semantic(r) for r in result["results"]]
        return result
    digest = hashlib.sha256(_encoded({"repo": str(Path(repo).resolve()), "context": semantic(payload)})).hexdigest()
    result = {**payload, "context_digest": digest, "presentation": "FULL"}
    if since != digest or payload.get("status") not in {"RESOLVED", "BATCH_RESOLVED"}:
        if since:
            result["presentation_reason"] = "BASELINE_MISMATCH"
        return result
    # Keep safety, identity, current receipts, instructions and warnings intact.
    def compact(row):
        row = dict(row)
        omitted = []
        for key in ("direct_dependencies", "direct_dependents", "tests", "local_profiles", "read_ranges_note"):
            if key in row:
                row.pop(key)
                omitted.append(key)
        notes = row.get("project_notes")
        if isinstance(notes, dict) and "content" in notes:
            row["project_notes"] = {k: v for k, v in notes.items() if k != "content"}
            row["project_notes"].update(content_omitted=True, path=".agents/project-context/project-notes.md")
            omitted.append("project_notes.content")
        row["omitted_unchanged_fields"] = omitted
        if "results" in row:
            row["results"] = [compact(r) for r in row["results"]]
        return row
    result = compact(result)
    result["presentation"] = "UNCHANGED"
    return result
