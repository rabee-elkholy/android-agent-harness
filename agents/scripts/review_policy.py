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


def decide(classification: dict, skills_root: Path, *, project_kind: str = "application", task_kind: str = "FEATURE", plan: dict | None = None) -> dict:
    surfaces = set(classification.get("surfaces") or [])
    severity = str(classification.get("severity") or "HIGH")
    reviewers: set[str] = set()
    for surface in surfaces:
        reviewers.update(ROUTING.get(surface, set()))
    if severity == "CRITICAL":
        reviewers = set(FIVE_REVIEWERS)
    if "TEST_ONLY" in surfaces:
        reviewers.add("test-quality-reviewer-agent")
    planning_depth = str(classification.get("planning_depth") or (plan or {}).get("planning_depth") or "BOUNDED").upper()
    if planning_depth == "ARCHITECTURAL" and not _micro_eligible(classification) and "UNKNOWN" not in surfaces:
        reviewers.add("spec-compliance-agent")
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
    current_change_set: str | None = None,
    plan: dict | None = None,
) -> dict:
    """Narrow a later round while retaining tamper-evident prior PASS coverage."""
    result = decide(classification, skills_root, project_kind=project_kind, task_kind=task_kind, plan=plan)
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

    # Finding L / REVIEW-RERUN-001: Any post-review production-code mutation
    # invalidates prior required reviewer PASS coverage.
    prod_surfaces = set(result.get("surfaces") or []) - {"TEST_ONLY", "DOCS"}
    current_cs = current_change_set or classification.get("change_set_sha256")
    if current_cs and current_cs != source_change_set and prod_surfaces:
        carried = []
        rerun = set(current_required)

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


CAPABILITY_STANDARD = "STANDARD"
CAPABILITY_STRONG = "STRONG"


def reviewer_capability_for(
    reviewer: str,
    surfaces: list[str] | set[str],
    severity: str = "HIGH",
    round_number: int = 1,
    is_finding_owner: bool = False,
    planning_depth: str = "BOUNDED",
    changed_modules_count: int = 1,
) -> tuple[str, str]:
    """Derive abstract capability (STANDARD or STRONG) and reasoning effort (MEDIUM or HIGH).

    Pure deterministic helper per Section 19.6.
    """
    surfaces_set = set(surfaces)
    sev_upper = str(severity or "HIGH").upper()

    # Rule 1: Security reviewer
    if reviewer == "security-reviewer-agent":
        if surfaces_set & {"AUTH", "BILLING", "SECURITY", "SENSITIVE_DATA", "CRYPTO", "NATIVE_CODE"} or sev_upper == "CRITICAL":
            return CAPABILITY_STRONG, "HIGH"

    # Rule 2: Performance reviewer
    elif reviewer == "perf-anr-guardian-agent":
        if sev_upper == "CRITICAL" or (sev_upper == "HIGH" and surfaces_set & {"NATIVE_CODE", "DEVICE_API", "COROUTINES"}):
            return CAPABILITY_STRONG, "HIGH"

    # Rule 3: Regression reviewer
    elif reviewer == "regression-impact-reviewer-agent":
        if sev_upper == "CRITICAL" or (sev_upper == "HIGH" and surfaces_set & {"PUBLIC_API", "ROOM_SCHEMA", "BUILD_CONFIG"}):
            return CAPABILITY_STRONG, "HIGH"
        if "NAVIGATION" in surfaces_set and changed_modules_count > 1:
            return CAPABILITY_STRONG, "HIGH"

    # Rule 4: Bug reviewer
    elif reviewer == "bug-reviewer-agent":
        if sev_upper == "CRITICAL" or (round_number > 1 and is_finding_owner):
            return CAPABILITY_STRONG, "HIGH"

    # Rule 5: Spec compliance reviewer
    elif reviewer == "spec-compliance-agent":
        if str(planning_depth or "").upper() == "ARCHITECTURAL" or sev_upper in ("HIGH", "CRITICAL"):
            return CAPABILITY_STRONG, "HIGH"

    # Round 3 escalation for core judgment reviewers
    if round_number >= 3 and reviewer in {"bug-reviewer-agent", "security-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"}:
        return CAPABILITY_STRONG, "HIGH"

    return CAPABILITY_STANDARD, "MEDIUM"


def review_execution_requirements(
    policy: dict,
    plan: dict | None = None,
    round_number: int | None = None,
    changed_modules_count: int | None = None,
) -> dict:
    """Derive the full execution profile mapping for all required reviewers in a policy."""
    surfaces = policy.get("surfaces") or []
    severity = policy.get("severity") or "HIGH"
    reviewers = policy.get("reviewers") or []
    finding_owners = set((policy.get("later_round_source") or {}).get("finding_owners") or [])
    planning_depth = str((plan or {}).get("planning_depth") or "BOUNDED")
    if changed_modules_count is None:
        raw_modules = (plan or {}).get("changed_modules") or []
        changed_modules_count = len(raw_modules) if isinstance(raw_modules, list) else int((plan or {}).get("changed_modules_count") or 1)

    if round_number is None:
        round_number = int(policy.get("review_round") or (((plan or {}).get("review_rounds") or 0) + 1))

    requirements = {}
    for r in reviewers:
        cap, reas = reviewer_capability_for(
            r,
            surfaces=surfaces,
            severity=severity,
            round_number=round_number,
            is_finding_owner=(r in finding_owners),
            planning_depth=planning_depth,
            changed_modules_count=changed_modules_count,
        )
        requirements[r] = {
            "requested_capability": cap,
            "requested_reasoning": reas,
            "diversity": "PREFERRED" if cap == CAPABILITY_STRONG else "NONE",
            "context": "ISOLATED_PREFERRED",
        }
    return {
        "schema_version": 1,
        "round_number": round_number,
        "reviewers": requirements,
    }


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
