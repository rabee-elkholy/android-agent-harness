"""Central adaptive reviewer, gate, device, skill, and cost policy."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import canonical_sha256  # noqa: E402
from change_classifier import classify  # noqa: E402
from skill_router import route  # noqa: E402


SCHEMA_VERSION = 1
PIPELINE_GATE_ORDER = ("preflight", "localization", "manifest", "unit_tests", "assemble", "device")
FIVE_REVIEWERS = {
    "bug-reviewer-agent", "convention-reviewer-agent", "security-reviewer-agent",
    "perf-anr-guardian-agent", "regression-impact-reviewer-agent",
}
DEVICE_SURFACES = {
    "COMPOSE_UI", "XML_UI", "RESOURCE_UI", "NAVIGATION", "DEVICE_API", "MANIFEST_PERMISSION",
    "ROOM_SCHEMA", "BILLING", "AUTH",
}
TEST_SURFACES = {
    "BUSINESS_LOGIC", "PUBLIC_API", "COROUTINES", "NETWORK", "ROOM_SCHEMA",
    "PERSISTENCE",
    "NATIVE_CODE", "DEVICE_API", "BILLING", "AUTH", "SECURITY",
    "SENSITIVE_DATA", "CRYPTO", "TEST_ONLY",
}

ROUTING = {
    "BUSINESS_LOGIC": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
    "PUBLIC_API": {"bug-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"},
    "COMPOSE_UI": {"bug-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"},
    "XML_UI": {"bug-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"},
    "RESOURCE_UI": {"bug-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"},
    "NAVIGATION": {"bug-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"},
    "COROUTINES": {"bug-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"},
    "NETWORK": {"bug-reviewer-agent", "security-reviewer-agent", "regression-impact-reviewer-agent"},
    "ROOM_SCHEMA": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
    "PERSISTENCE": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
    "MANIFEST_PERMISSION": {"security-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"},
    "BUILD_CONFIG": {"security-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"},
    "NATIVE_CODE": {"bug-reviewer-agent", "security-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"},
    "DEVICE_API": {"bug-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"},
    "BILLING": FIVE_REVIEWERS,
    "AUTH": FIVE_REVIEWERS,
    "SECURITY": FIVE_REVIEWERS,
    "SENSITIVE_DATA": FIVE_REVIEWERS,
    "CRYPTO": FIVE_REVIEWERS,
}


def _configured_model_call_budget() -> int:
    try:
        from _product import MODEL_CALL_BUDGET
        return max(0, int(MODEL_CALL_BUDGET))
    except (ImportError, TypeError, ValueError):
        return 8


def _micro_eligible(classification: dict) -> bool:
    surfaces = set(classification.get("surfaces") or [])
    allowed = {"DOCS", "LOCALIZATION", "RESOURCE_UI"}
    disallowed = {
        "TEST_ONLY", "ROOM_SCHEMA", "BUILD_CONFIG", "MANIFEST_PERMISSION", "SECURITY",
        "AUTH", "BILLING", "SENSITIVE_DATA", "CRYPTO", "PUBLIC_API", "UNKNOWN",
    }
    return (
        bool(surfaces)
        and surfaces <= allowed
        and not surfaces & disallowed
        and int(classification.get("changed_files") or 0) <= 5
        and int(classification.get("changed_lines") or 0) <= 80
        and not bool(classification.get("has_delete_or_rename"))
    )


def decide(classification: dict, skills_root: Path, *, project_kind: str = "application", task_kind: str = "FEATURE") -> dict:
    surfaces = set(classification.get("surfaces") or [])
    severity = str(classification.get("severity") or "HIGH")
    reviewers: set[str] = set()
    for surface in surfaces:
        reviewers.update(ROUTING.get(surface, set()))
    if severity == "CRITICAL":
        reviewers = set(FIVE_REVIEWERS)
    if "TEST_ONLY" in surfaces:
        reviewers.add("test-quality-reviewer-agent")
    micro = _micro_eligible(classification)
    if micro:
        reviewers.clear()
    if "UNKNOWN" in surfaces:
        reviewers.clear()

    gates: set[str] = {"manifest", "preflight"}
    if surfaces & TEST_SURFACES:
        gates.add("unit_tests")
    if surfaces & {"LOCALIZATION", "RESOURCE_UI", "COMPOSE_UI", "XML_UI"}:
        gates.add("localization")
    if "ROOM_SCHEMA" in surfaces:
        gates.add("room")
    if surfaces - {"DOCS"}:
        gates.add("assemble")
    device_required = project_kind == "application" and bool(surfaces & DEVICE_SURFACES)
    if device_required:
        gates.add("device")

    skills = route(skills_root, sorted(surfaces), task_kind=task_kind)
    call_budget = _configured_model_call_budget()
    status = "NO_DELIVERY_CHANGES" if not surfaces else "USER_DECISION_REQUIRED" if "UNKNOWN" in surfaces else skills["status"]
    if len(reviewers) > call_budget:
        status = "USER_DECISION_REQUIRED"
    result = {
        "schema_version": SCHEMA_VERSION,
        "classification_sha256": classification.get("classification_sha256"),
        "surfaces": sorted(surfaces),
        "severity": severity,
        "confidence": classification.get("confidence"),
        "status": status,
        "micro_eligible": micro,
        "review_status": "REVIEW_NOT_REQUIRED_BY_POLICY" if micro else "REQUIRED" if reviewers else "NONE",
        "reviewers": sorted(reviewers),
        "gates": sorted(gates, key=lambda g: (PIPELINE_GATE_ORDER.index(g) if g in PIPELINE_GATE_ORDER else 99, g)),
        "device_required": device_required,
        "project_kind": project_kind,
        "max_review_rounds": 3,
        "model_escalation": "EXPLICIT_POLICY_OR_DEVELOPER_APPROVAL",
        "model_call_budget": call_budget,
        "estimated_calls_this_round": len(reviewers),
        "skills": skills,
    }
    result["policy_sha256"] = canonical_sha256(result)
    return result


def decide_later_round(
    classification: dict,
    skills_root: Path,
    *,
    previous_policy: dict,
    finding_owners: list[str],
    passed_reviewers: list[str],
    source_snapshot: str,
    source_change_set: str,
    source_run_id: str,
    round_number: int,
    project_kind: str = "application",
    task_kind: str = "FEATURE",
) -> dict:
    """Narrow a later round while retaining tamper-evident prior PASS coverage."""
    result = decide(classification, skills_root, project_kind=project_kind, task_kind=task_kind)
    current_required = set(result.get("reviewers") or [])
    previous_required = set(previous_policy.get("reviewers") or [])
    owners = set(finding_owners) & previous_required
    promoted = current_required - previous_required
    rerun = owners | promoted
    if rerun or previous_required:
        rerun.add("regression-impact-reviewer-agent")
    if "TEST_ONLY" in set(result.get("surfaces") or []):
        rerun.add("test-quality-reviewer-agent")
    # A role remains required only if it is still applicable, was a finding
    # owner, or is Regression/Test Quality mandated for the fix delta.
    allowed = current_required | owners | {"regression-impact-reviewer-agent", "test-quality-reviewer-agent"}
    rerun &= allowed
    carried = sorted((set(passed_reviewers) & previous_required & current_required) - rerun)
    result["reviewers"] = sorted(rerun)
    result["review_status"] = "REQUIRED" if rerun else "NONE"
    result["review_round"] = round_number
    result["estimated_calls_this_round"] = len(rerun)
    result["later_round_source"] = {
        "snapshot": source_snapshot,
        "change_set": source_change_set,
        "run_id": source_run_id,
        "finding_owners": sorted(owners),
    }
    fresh_carries = [
        {
            "reviewer": reviewer,
            "source_snapshot": source_snapshot,
            "source_change_set": source_change_set,
            "source_run_id": source_run_id,
            "covered_surfaces": sorted(previous_policy.get("surfaces") or []),
            "invalidation_reason": None,
        }
        for reviewer in carried
    ]
    inherited_carries = [
        dict(item)
        for item in previous_policy.get("carried_reviews") or []
        if str(item.get("reviewer") or "") in current_required
        and str(item.get("reviewer") or "") not in rerun
        and not item.get("invalidation_reason")
    ]
    by_reviewer = {
        str(item.get("reviewer") or ""): item
        for item in (*inherited_carries, *fresh_carries)
        if str(item.get("reviewer") or "")
    }
    result["carried_reviews"] = [by_reviewer[key] for key in sorted(by_reviewer)]
    result["policy_sha256"] = canonical_sha256({key: value for key, value in result.items() if key != "policy_sha256"})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    skills_root = (repo / ".agents" / "skills") if (repo / ".agents" / "skills").is_dir() else Path(__file__).resolve().parents[1] / "skills"
    try:
        from _product import PROJECT_KIND
    except ImportError:
        PROJECT_KIND = "application"
    result = decide(classify(repo), skills_root, project_kind=str(PROJECT_KIND))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"POLICY_STATUS={result['status']}")
        print(f"REVIEWERS={','.join(result['reviewers']) or 'NONE'}")
        print(f"GATES={','.join(result['gates'])}")
        print(f"DEVICE_REQUIRED={str(result['device_required']).lower()}")
    return 0 if result["status"] == "PASS" else 2 if result["status"] == "USER_DECISION_REQUIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
