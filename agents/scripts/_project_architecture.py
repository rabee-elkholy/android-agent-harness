"""Derive local architecture families from scanned source evidence."""
from __future__ import annotations

import re
from typing import Any


def resolve_architecture_families(discovered_screens, discovered_viewmodels, di_frameworks, nav_elements, vm_candidates, has_compose, has_xml_views):
    from project_context import resolve_feature_scope, _canonical_json, _sha256_text
    families_by_sig: dict[str, dict[str, Any]] = {}

    # Synthesize families from discovered pairs or standalone bases
    if discovered_screens:
        for sc in discovered_screens:
            sc_scope = resolve_feature_scope(sc["path"])
            sc_stem = re.sub(r"(Screen|Fragment|Activity|Content)$", "", sc["name"])
            matching_vm = None
            ambiguous = False

            # Tier 1: exact normalized stem match (Screen stem == ViewModel stem)
            if sc_stem:
                t1 = [
                    v for v in discovered_viewmodels
                    if re.sub(r"(ViewModel|VM)$", "", v["name"]).lower() == sc_stem.lower()
                ]
                if len(t1) == 1:
                    matching_vm = t1[0]
                elif len(t1) > 1:
                    scoped = [v for v in t1 if resolve_feature_scope(v["path"]) == sc_scope]
                    if len(scoped) == 1:
                        matching_vm = scoped[0]
                    else:
                        ambiguous = True

            # Tier 2: same local feature scope + compatible name
            if not matching_vm and not ambiguous and sc_stem:
                t2 = [
                    v for v in discovered_viewmodels
                    if resolve_feature_scope(v["path"]) == sc_scope
                    and (
                        sc_stem.lower() in re.sub(r"(ViewModel|VM)$", "", v["name"]).lower()
                        or re.sub(r"(ViewModel|VM)$", "", v["name"]).lower() in sc_stem.lower()
                    )
                ]
                if len(t2) == 1:
                    matching_vm = t2[0]
                elif len(t2) > 1:
                    ambiguous = True

            # Tier 3: graph reference / source text association
            if not matching_vm and not ambiguous:
                sc_text = sc.get("text", "")
                if sc_text:
                    t3 = [v for v in discovered_viewmodels if v["name"] in sc_text]
                    if len(t3) == 1:
                        matching_vm = t3[0]
                    elif len(t3) > 1:
                        scoped = [v for v in t3 if resolve_feature_scope(v["path"]) == sc_scope]
                        if len(scoped) == 1:
                            matching_vm = scoped[0]
                        else:
                            ambiguous = True

            # Tier 4: one and only one candidate in local scope
            if not matching_vm and not ambiguous:
                local_vms = [v for v in discovered_viewmodels if resolve_feature_scope(v["path"]) == sc_scope]
                if len(local_vms) == 1:
                    matching_vm = local_vms[0]
                elif len(local_vms) > 1:
                    ambiguous = True

            dims = {
                "ui_toolkit": sc["ui_toolkit"],
                "screen_host": sc["screen_host"],
                "state_holder_base": matching_vm["base"] if matching_vm else "unknown",
                "state_stream": matching_vm["state_stream"] if matching_vm else "unknown",
                "presentation_flow": matching_vm["presentation_flow"] if matching_vm else "unknown",
                "input_contract": matching_vm["input_contract"] if matching_vm else "unknown",
                "effect_contract": matching_vm["effect_contract"] if matching_vm else "unknown",
                "domain_boundary": matching_vm["domain_boundary"] if matching_vm else "unknown",
                "data_boundary": matching_vm["data_boundary"] if matching_vm else "unknown",
                "di": matching_vm["di"] if matching_vm else (di_frameworks[0] if di_frameworks else "unknown"),
                "navigation": sc["nav_type"] if sc["nav_type"] != "unknown" else ("compose_navigation" if sc["ui_toolkit"] == "compose" else "xml_navigation" if nav_elements else "unknown"),
            }
            core_dims = {
                "ui_toolkit": sc["ui_toolkit"],
                "screen_host": sc["screen_host"],
                "state_holder_base": dims["state_holder_base"],
                "state_stream": dims["state_stream"],
                "presentation_flow": dims["presentation_flow"],
                "di": dims["di"],
            }
            sig_str = _canonical_json(core_dims)
            sig_hash = _sha256_text(sig_str)
            fid = f"af-{sig_hash[:12]}"
            initial_confidence = "HIGH" if matching_vm else ("LOW/AMBIGUOUS" if ambiguous else "MEDIUM")
            if fid not in families_by_sig:
                label_parts = [core_dims["ui_toolkit"]]
                if core_dims["screen_host"] != "unknown":
                    label_parts.append(core_dims["screen_host"])
                if core_dims["state_holder_base"] != "unknown":
                    label_parts.append(core_dims["state_holder_base"].lower())
                if core_dims["state_stream"] != "unknown":
                    label_parts.append(core_dims["state_stream"])
                if core_dims["di"] != "unknown":
                    label_parts.append(core_dims["di"])
                label = "-".join(label_parts) or "android-standard"
                families_by_sig[fid] = {
                    "id": fid,
                    "signature_sha256": sig_hash,
                    "label": label,
                    "dimensions": dims,
                    "confidence": initial_confidence,
                    "scopes": set(),
                    "exemplars": set(),
                    "evidence": [],
                }
            fam = families_by_sig[fid]
            # Coalesce richer dimensions into existing family
            if fam["dimensions"].get("navigation") == "unknown" and dims["navigation"] != "unknown":
                fam["dimensions"]["navigation"] = dims["navigation"]
            if fam["dimensions"].get("input_contract") == "unknown" and dims["input_contract"] != "unknown":
                fam["dimensions"]["input_contract"] = dims["input_contract"]
            if fam["dimensions"].get("effect_contract") == "unknown" and dims["effect_contract"] != "unknown":
                fam["dimensions"]["effect_contract"] = dims["effect_contract"]
            if matching_vm and fam["confidence"] != "LOW/AMBIGUOUS":
                fam["confidence"] = "HIGH"
            elif ambiguous:
                fam["confidence"] = "LOW/AMBIGUOUS"
            fam["scopes"].add(sc_scope)
            fam["exemplars"].add(sc["path"])
            if matching_vm:
                fam["exemplars"].add(matching_vm["path"])
    elif vm_candidates or has_compose or has_xml_views:
        # Synthesize from candidates or framework presence
        candidates_to_use = vm_candidates if vm_candidates else [{"symbol": "ViewModel", "path": ""}]
        for cand in candidates_to_use:
            cand_name = cand["symbol"]
            cand_scope = resolve_feature_scope(cand["path"]) if cand.get("path") else ""
            is_mvi = "mvi" in cand_name.lower() or "state" in cand_name.lower()
            u_toolkit = "compose" if has_compose else "xml" if has_xml_views else "unknown"
            s_host = "composable" if u_toolkit == "compose" else "fragment" if u_toolkit == "xml" else "unknown"
            s_stream = "stateflow" if is_mvi else "livedata" if u_toolkit == "xml" else "unknown"
            p_flow = "unidirectional" if (is_mvi and s_stream == "stateflow") else "unknown"
            dims = {
                "ui_toolkit": u_toolkit,
                "screen_host": s_host,
                "state_holder_base": cand_name,
                "state_stream": s_stream,
                "presentation_flow": p_flow,
                "input_contract": "UiAction" if is_mvi else "unknown",
                "effect_contract": "UiEvent" if is_mvi else "unknown",
                "domain_boundary": "usecase" if is_mvi else "repository",
                "data_boundary": "repository",
                "di": di_frameworks[0] if di_frameworks else "unknown",
                "navigation": "compose_navigation" if u_toolkit == "compose" else "xml_navigation" if nav_elements else "unknown",
            }
            core_dims = {
                "ui_toolkit": u_toolkit,
                "screen_host": s_host,
                "state_holder_base": cand_name,
                "state_stream": s_stream,
                "presentation_flow": p_flow,
                "di": dims["di"],
            }
            sig_str = _canonical_json(core_dims)
            sig_hash = _sha256_text(sig_str)
            fid = f"af-{sig_hash[:12]}"
            if fid not in families_by_sig:
                label_parts = [u_toolkit]
                if s_host != "unknown":
                    label_parts.append(s_host)
                label_parts.append(cand_name.lower())
                if s_stream != "unknown":
                    label_parts.append(s_stream)
                if dims["di"] != "unknown":
                    label_parts.append(dims["di"])
                label = "-".join(label_parts)
                families_by_sig[fid] = {
                    "id": fid,
                    "signature_sha256": sig_hash,
                    "label": label,
                    "dimensions": dims,
                    "confidence": "HIGH" if cand.get("path") else "MEDIUM",
                    "scopes": set(),
                    "exemplars": set(),
                    "evidence": [],
                }
            fam = families_by_sig[fid]
            if cand_scope:
                fam["scopes"].add(cand_scope)
            if cand.get("path"):
                fam["exemplars"].add(cand["path"])

    final_families: list[dict[str, Any]] = []
    scope_assignments: list[dict[str, Any]] = []

    for fid in sorted(families_by_sig.keys()):
        raw_fam = families_by_sig[fid]
        sorted_exemplars = sorted(raw_fam["exemplars"])[:5]  # Cap at 5 exemplars
        sorted_scopes = sorted(raw_fam["scopes"])
        fam_entry = {
            "id": raw_fam["id"],
            "signature_sha256": raw_fam["signature_sha256"],
            "label": raw_fam["label"],
            "dimensions": raw_fam["dimensions"],
            "confidence": raw_fam["confidence"],
            "scopes": sorted_scopes,
            "exemplars": sorted_exemplars,
            "evidence": sorted(raw_fam["evidence"]),
        }
        final_families.append(fam_entry)
        for sc in sorted_scopes:
            scope_assignments.append({"scope": sc, "family_id": raw_fam["id"]})

    return final_families, scope_assignments
