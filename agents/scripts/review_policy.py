"""Central adaptive reviewer, gate, device, skill, and cost policy."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import canonical_sha256  # noqa: E402
from change_classifier import CRITICAL_SURFACES, HIGH_SURFACES, classify  # noqa: E402
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
    "COMPOSE_UI": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
    "XML_UI": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
    "RESOURCE_UI": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
    "NAVIGATION": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
    "COROUTINES": {"bug-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"},
    "NETWORK": {"bug-reviewer-agent", "security-reviewer-agent", "regression-impact-reviewer-agent"},
    "ROOM_SCHEMA": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
    "PERSISTENCE": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
    "MANIFEST_PERMISSION": {"security-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"},
    "BUILD_CONFIG": {"security-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"},
    "NATIVE_CODE": {"bug-reviewer-agent", "security-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"},
    "DEVICE_API": {"bug-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"},
    "ANALYTICS": {"bug-reviewer-agent", "regression-impact-reviewer-agent"},
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
        return 10


def _configured_device_verification_mode() -> str:
    try:
        from _product import DEVICE_VERIFICATION_MODE
        mode = str(DEVICE_VERIFICATION_MODE or "").strip().lower()
    except Exception:
        mode = "manual_only"

    if mode not in {
        "manual_only",
        "disabled",
    }:
        return "manual_only"

    return mode


def _is_visual_compose(classification: dict) -> bool:
    details = classification.get("details") or {}
    compose_info = details.get("COMPOSE_UI")
    if compose_info is None:
        return classification.get("severity") == "LOW" and "BUSINESS_LOGIC" not in (classification.get("surfaces") or [])
    reasons = compose_info.get("reasons") or []
    return any("VISUAL" in str(r).upper() for r in reasons)


ANALYTICS_SYMBOL_RE = re.compile(
    r"\b(?:FirebaseAnalytics|Mixpanel|Segment|Amplitude|AnalyticsTracker|"
    r"trackEvent|logEvent|analytics\.log|Analytics\.log|analytics\.track|Analytics\.track)\b"
)


def _is_analytics_scope(classification: dict, plan: dict | None = None, task_kind: str = "FEATURE") -> bool:
    if str(task_kind).upper() in ("ANALYTICS", "TELEMETRY", "UI_TWEAK"):
        return True
    if plan and str(plan.get("task_kind") or "").upper() in ("ANALYTICS", "TELEMETRY", "UI_TWEAK"):
        return True
    surfaces = set(classification.get("surfaces") or [])
    if "ANALYTICS" in surfaces:
        return True
    text_signals = []
    if plan:
        text_signals.extend([str(plan.get("title") or ""), str(plan.get("requested_outcome") or ""), str(plan.get("task_id") or "")])
    task_changes = classification.get("task_changes") or []
    paths = [str(c.get("path") if isinstance(c, dict) else c) for c in task_changes]
    diff_texts = [str(c.get("diff") or "") for c in task_changes if isinstance(c, dict)]
    combined = " ".join(text_signals) + " " + " ".join(paths) + " " + " ".join(diff_texts)

    lower_combined = combined.lower()
    if "analytic" in lower_combined or "telemetry" in lower_combined:
        return True
    if ANALYTICS_SYMBOL_RE.search(combined):
        return True
    return False


def _micro_eligible(classification: dict, plan: dict | None = None, task_kind: str = "FEATURE") -> bool:
    surfaces = set(classification.get("surfaces") or [])
    if not surfaces and plan:
        surfaces = set(plan.get("expected_surfaces") or plan.get("surfaces") or [])
    if not surfaces:
        return False
    disallowed = (
        CRITICAL_SURFACES | {"ROOM_SCHEMA", "BUILD_CONFIG", "MANIFEST_PERMISSION", "TEST_ONLY",
                             "SECURITY", "AUTH", "BILLING", "SENSITIVE_DATA", "CRYPTO", "PUBLIC_API",
                             "UNKNOWN", "DEVICE_API", "PERSISTENCE", "NETWORK", "NATIVE_CODE"}
    )
    if bool(surfaces & disallowed):
        return False
    if int(classification.get("changed_files") or 0) > 8:
        return False
    if int(classification.get("changed_lines") or 0) > 120:
        return False
    if bool(classification.get("has_delete_or_rename")):
        return False
    if plan:
        planning_depth = str(plan.get("planning_depth") or "").upper()
        if planning_depth == "ARCHITECTURAL":
            return False
        arch_intent = str(plan.get("architecture_intent") or "").upper()
        if arch_intent == "MIGRATION":
            return False
        changed_modules = plan.get("changed_modules") or []
        if isinstance(changed_modules, list) and len(changed_modules) > 1:
            return False

    # Tier 0: Pure resources, strings, docs
    if surfaces <= {"DOCS", "LOCALIZATION", "RESOURCE_UI"}:
        return True

    # Tier 1 (Visual): Visual Compose / UI
    if surfaces <= {"DOCS", "LOCALIZATION", "RESOURCE_UI", "COMPOSE_UI"}:
        if "COMPOSE_UI" in surfaces and not _is_visual_compose(classification):
            return False
        return True

    # Tier 1 (Analytics): Bounded event wiring across UI and ViewModel/Contract
    if _is_analytics_scope(classification, plan=plan, task_kind=task_kind):
        if surfaces <= {"DOCS", "LOCALIZATION", "RESOURCE_UI", "COMPOSE_UI", "XML_UI", "BUSINESS_LOGIC", "COROUTINES", "ANALYTICS"}:
            severity = str(classification.get("severity") or "").upper()
            if severity in ("CRITICAL", "HIGH"):
                return False
            return True

    return False


def _derive_ui_verification_class(surfaces: set[str], micro: bool, classification: dict | None = None) -> str:
    """Derive UI verification class: VISUAL_MICRO, UI_BEHAVIOR, DEVICE_BEHAVIOR, or NONE."""
    device_behavior_surfaces = {"DEVICE_API", "MANIFEST_PERMISSION", "BILLING", "AUTH", "ROOM_SCHEMA"}
    if surfaces & device_behavior_surfaces:
        return "DEVICE_BEHAVIOR"
    ui_surfaces = {"COMPOSE_UI", "XML_UI", "NAVIGATION", "RESOURCE_UI", "LOCALIZATION"}
    if not (surfaces & ui_surfaces):
        return "NONE"
    if micro and not (surfaces & device_behavior_surfaces):
        return "VISUAL_MICRO"
    if "XML_UI" in surfaces or "NAVIGATION" in surfaces or "BUSINESS_LOGIC" in surfaces or not micro:
        return "UI_BEHAVIOR"
    if "COMPOSE_UI" in surfaces and classification and not _is_visual_compose(classification):
        return "UI_BEHAVIOR"
    return "UI_BEHAVIOR"


CANONICAL_TIERS = {
    "T0": "T0_TRIVIAL",
    "T0_TRIVIAL": "T0_TRIVIAL",
    "TRIVIAL": "T0_TRIVIAL",
    "T1": "T1_LOW_RISK",
    "T1_LOW_RISK": "T1_LOW_RISK",
    "LOW_RISK": "T1_LOW_RISK",
    "T2": "T2_FEATURE",
    "T2_FEATURE": "T2_FEATURE",
    "FEATURE": "T2_FEATURE",
    "T3": "T3_SUBSYSTEM",
    "T3_SUBSYSTEM": "T3_SUBSYSTEM",
    "SUBSYSTEM": "T3_SUBSYSTEM",
    "T4": "T4_DATA_DEVICE",
    "T4_DATA_DEVICE": "T4_DATA_DEVICE",
    "DATA_DEVICE": "T4_DATA_DEVICE",
    "DATA": "T4_DATA_DEVICE",
    "T5": "T5_CRITICAL",
    "T5_CRITICAL": "T5_CRITICAL",
    "CRITICAL": "T5_CRITICAL",
}


def canonical_risk_tier(tier_or_lane: str, surfaces: set[str] | None = None) -> str:
    """Normalize any legacy risk lane or tier identifier to one of the 6 canonical risk tiers."""
    norm = str(tier_or_lane or "").strip().upper()
    if norm in CANONICAL_TIERS:
        return CANONICAL_TIERS[norm]
    if norm == "MICRO":
        if surfaces and surfaces <= {"DOCS", "LOCALIZATION", "RESOURCE_UI"}:
            return "T0_TRIVIAL"
        return "T1_LOW_RISK"
    if norm == "STANDARD":
        return "T2_FEATURE"
    return "T2_FEATURE"


def decide(classification: dict, skills_root: Path, *, project_kind: str = "application", task_kind: str = "FEATURE", plan: dict | None = None) -> dict:
    surfaces = set(classification.get("surfaces") or [])
    if not surfaces and plan:
        surfaces = set(plan.get("expected_surfaces") or plan.get("surfaces") or [])
    severity = str(classification.get("severity") or "HIGH")
    if surfaces and severity == "LOW":
        if set(surfaces) & CRITICAL_SURFACES:
            severity = "CRITICAL"
        elif set(surfaces) & HIGH_SURFACES:
            severity = "HIGH"

    micro = _micro_eligible(classification, plan=plan, task_kind=task_kind)
    planning_depth = str(classification.get("planning_depth") or (plan or {}).get("planning_depth") or "BOUNDED").upper()
    arch_intent = str((plan or {}).get("architecture_intent") or "").upper()
    changed_modules = (plan or {}).get("changed_modules") or []
    changed_modules_count = len(changed_modules) if isinstance(changed_modules, list) else int((plan or {}).get("changed_modules_count") or 1)

    if micro:
        if surfaces <= {"DOCS", "LOCALIZATION", "RESOURCE_UI"}:
            risk_tier = "T0_TRIVIAL"
            risk_lane = "MICRO"
        else:
            risk_tier = "T1_LOW_RISK"
            risk_lane = "MICRO"
    elif (
        severity == "CRITICAL"
        or bool(surfaces & CRITICAL_SURFACES)
        or bool(surfaces & {"NATIVE_CODE", "MANIFEST_PERMISSION"})
    ):
        risk_tier = "T5_CRITICAL"
        risk_lane = "CRITICAL"
    elif surfaces & {"ROOM_SCHEMA", "PERSISTENCE", "DEVICE_API"}:
        risk_tier = "T4_DATA_DEVICE"
        risk_lane = "DATA"
    elif (
        changed_modules_count > 1
        or planning_depth == "ARCHITECTURAL"
        or arch_intent in ("MIGRATION", "NEW_SUBSYSTEM")
    ):
        risk_tier = "T3_SUBSYSTEM"
        risk_lane = "STANDARD"
    else:
        risk_tier = "T2_FEATURE"
        risk_lane = "STANDARD"

    ui_verification_class = _derive_ui_verification_class(surfaces, micro, classification)

    reviewers: set[str] = set()
    for surface in surfaces:
        reviewers.update(ROUTING.get(surface, set()))
    if risk_tier == "T5_CRITICAL":
        reviewers = set(FIVE_REVIEWERS)
    if "TEST_ONLY" in surfaces:
        reviewers.add("test-quality-reviewer-agent")
    if planning_depth == "ARCHITECTURAL" and not micro and "UNKNOWN" not in surfaces:
        reviewers.add("spec-compliance-agent")
        reviewers.add("convention-reviewer-agent")
    if arch_intent in ("MIGRATION", "NEW_SUBSYSTEM") and not micro and "UNKNOWN" not in surfaces:
        reviewers.add("convention-reviewer-agent")
    if changed_modules_count > 1 and not micro and "UNKNOWN" not in surfaces and (surfaces & {"COMPOSE_UI", "XML_UI", "NAVIGATION", "BUSINESS_LOGIC"}):
        reviewers.add("convention-reviewer-agent")

    if micro:
        reviewers.clear()
    if "UNKNOWN" in surfaces:
        reviewers.clear()

    if project_kind != "application":
        intrinsic_device_required = False
    elif ui_verification_class == "VISUAL_MICRO":
        intrinsic_device_required = False
    elif ui_verification_class in ("UI_BEHAVIOR", "DEVICE_BEHAVIOR"):
        intrinsic_device_required = True
    else:
        intrinsic_device_required = False

    device_verification_mode = _configured_device_verification_mode()
    device_required = (
        intrinsic_device_required
        and device_verification_mode != "disabled"
    )

    gates: set[str] = {"manifest", "preflight"}
    if surfaces & TEST_SURFACES:
        gates.add("unit_tests")
    if surfaces & {"LOCALIZATION", "RESOURCE_UI", "COMPOSE_UI", "XML_UI"}:
        gates.add("localization")
    if "ROOM_SCHEMA" in surfaces:
        gates.add("room")
    if risk_tier != "T0_TRIVIAL" and (surfaces - {"DOCS"}):
        gates.add("assemble")
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
        "risk_lane": risk_lane,
        "risk_tier": risk_tier,
        "ui_verification_class": ui_verification_class,
        "micro_eligible": micro,
        "review_status": "REVIEW_NOT_REQUIRED_BY_POLICY" if micro else "REQUIRED" if reviewers else "NONE",
        "reviewers": sorted(reviewers),
        "gates": sorted(gates, key=lambda g: (PIPELINE_GATE_ORDER.index(g) if g in PIPELINE_GATE_ORDER else 99, g)),
        "device_verification_mode": device_verification_mode,
        "intrinsic_device_required": intrinsic_device_required,
        "device_required": device_required,
        "project_kind": project_kind,
        "max_review_rounds": 3,
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


REVIEW_EFFORT_NORMAL = "NORMAL"
REVIEW_EFFORT_DEEP = "DEEP"
REVIEW_EFFORT_MAX = "MAX"

VALID_REVIEW_EFFORTS = {
    REVIEW_EFFORT_NORMAL,
    REVIEW_EFFORT_DEEP,
    REVIEW_EFFORT_MAX,
}


def reviewer_effort_for(
    reviewer: str,
    surfaces: list[str] | set[str],
    severity: str = "HIGH",
    round_number: int = 1,
    is_finding_owner: bool = False,
    planning_depth: str = "BOUNDED",
    changed_modules_count: int = 1,
) -> str:
    surfaces_set = set(surfaces)
    sev = str(severity or "HIGH").upper()

    core_judgment_reviewers = {
        "bug-reviewer-agent",
        "security-reviewer-agent",
        "perf-anr-guardian-agent",
        "regression-impact-reviewer-agent",
    }

    if (
        round_number >= 3
        and reviewer in core_judgment_reviewers
    ):
        return REVIEW_EFFORT_MAX

    if reviewer == "security-reviewer-agent":
        sensitive = {
            "AUTH",
            "BILLING",
            "SECURITY",
            "SENSITIVE_DATA",
            "CRYPTO",
            "NATIVE_CODE",
        }

        if (
            sev == "CRITICAL"
            and surfaces_set & sensitive
        ):
            return REVIEW_EFFORT_MAX

        if (
            sev == "CRITICAL"
            or surfaces_set & sensitive
        ):
            return REVIEW_EFFORT_DEEP

    if reviewer == "perf-anr-guardian-agent":
        if sev == "CRITICAL":
            return REVIEW_EFFORT_DEEP

        if (
            sev == "HIGH"
            and surfaces_set & {
                "NATIVE_CODE",
                "DEVICE_API",
                "COROUTINES",
            }
        ):
            return REVIEW_EFFORT_DEEP

    if reviewer == "regression-impact-reviewer-agent":
        if sev == "CRITICAL":
            return REVIEW_EFFORT_DEEP

        if (
            sev == "HIGH"
            and surfaces_set & {
                "PUBLIC_API",
                "ROOM_SCHEMA",
                "BUILD_CONFIG",
            }
        ):
            return REVIEW_EFFORT_DEEP

        if (
            "NAVIGATION" in surfaces_set
            and changed_modules_count > 1
        ):
            return REVIEW_EFFORT_DEEP

    if reviewer == "bug-reviewer-agent":
        if sev == "CRITICAL":
            return REVIEW_EFFORT_DEEP

        if (
            round_number > 1
            and is_finding_owner
        ):
            return REVIEW_EFFORT_DEEP

    if reviewer == "spec-compliance-agent":
        if (
            str(planning_depth or "").upper()
            == "ARCHITECTURAL"
            or sev in {"HIGH", "CRITICAL"}
        ):
            return REVIEW_EFFORT_DEEP

    return REVIEW_EFFORT_NORMAL


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
    for reviewer in reviewers:
        effort = reviewer_effort_for(
            reviewer,
            surfaces=surfaces,
            severity=severity,
            round_number=round_number,
            is_finding_owner=(reviewer in finding_owners),
            planning_depth=planning_depth,
            changed_modules_count=changed_modules_count,
        )
        requirements[reviewer] = {
            "reasoning_intent": effort,
            "model_policy": "INHERIT_PARENT",
            "context": "ISOLATED_PREFERRED",
        }
    return {
        "schema_version": 2,
        "round_number": round_number,
        "reviewers": requirements,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--task", default=None, help="Task ID (alias for --task-id)")
    parser.add_argument("--task-id", default=None, help="Task ID")
    args, _unknown = parser.parse_known_args()
    repo = Path(args.repo).resolve()
    task_id = args.task or args.task_id or os.environ.get("HARNESS_TASK_ID")
    if not task_id:
        active_p = repo / ".agents" / "state" / "active-task.json"
        if active_p.is_file():
            try:
                active_data = json.loads(active_p.read_text(encoding="utf-8"))
                task_id = active_data.get("task_id")
            except Exception:
                pass
    task_kind = "FEATURE"
    plan = None
    if task_id:
        plan_p = repo / ".agents" / "state" / "tasks" / task_id / "plan.json"
        if plan_p.is_file():
            try:
                plan = json.loads(plan_p.read_text(encoding="utf-8"))
                task_kind = str(plan.get("task_kind") or "FEATURE")
            except Exception:
                pass
    skills_root = (repo / ".agents" / "skills") if (repo / ".agents" / "skills").is_dir() else Path(__file__).resolve().parents[1] / "skills"
    try:
        from _product import PROJECT_KIND
    except ImportError:
        PROJECT_KIND = "application"
    classification = classify(repo, task_id=task_id, progress=not args.json)
    result = decide(classification, skills_root, project_kind=str(PROJECT_KIND), task_kind=task_kind, plan=plan)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"POLICY_STATUS={result['status']}")
        print(f"RISK_LANE={result['risk_lane']}")
        print(f"UI_VERIFICATION_CLASS={result['ui_verification_class']}")
        print(f"REVIEWERS={','.join(result['reviewers']) or 'NONE'}")
        print(f"GATES={','.join(result['gates'])}")
        print(f"DEVICE_REQUIRED={str(result['device_required']).lower()}")
    return 0 if result["status"] in ("PASS", "NO_DELIVERY_CHANGES") else 2 if result["status"] == "USER_DECISION_REQUIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
