"""Read-only verifier for one approved plan and immutable delivery run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, canonical_sha256, read_json, sha256_file  # noqa: E402
from delivery_manifest import build_manifest  # noqa: E402
from change_classifier import classify  # noqa: E402
from evidence_store import EvidenceStore  # noqa: E402
from plan_authority import changed_modules, check_material_drift, plan_payload  # noqa: E402
from artifact_set import verify_artifact_set  # noqa: E402
from review_policy import decide, decide_later_round  # noqa: E402


SENSITIVE_SURFACES = {"BILLING", "AUTH", "SECURITY", "SENSITIVE_DATA", "CRYPTO"}
ALLOWED_PRODUCERS = {
    "unit_tests": {"run_tests_gate"},
    "preflight": {"preflight_check"},
    "localization": {"check_strings", "preflight_check"},
    "room": {"room_guard", "preflight_check"},
    "assemble": {"run_gradle_task"},
    "device_install": {"run_device"},
    "device_launch": {"run_device"},
    "reviews": {"review_orchestrator", "developer_approval"},
    "sensitive_approval": {"developer_approval"},
}


def _configured_project_kind() -> str:
    try:
        from _product import PROJECT_KIND
        value = str(PROJECT_KIND or "application")
    except Exception:
        value = "application"
    return value if value in ("application", "library") else "application"


def _blocked(status: str, reasons: list[str], checks: list[dict]) -> dict:
    return {"schema_version": 1, "status": status, "blocked_by": reasons, "checks": checks}


def _validate_artifact(
    store: EvidenceStore,
    snapshot: str,
    change_set: str,
    run_id: str,
    name: str,
    harness_version: str,
) -> tuple[dict | None, str | None]:
    try:
        record = store.read(snapshot, run_id, name)
    except ValidationError as exc:
        return None, str(exc)
    if record.get("change_set_sha256") != change_set:
        return None, f"{name} change-set mismatch"
    if record.get("producer") not in ALLOWED_PRODUCERS.get(name, set()):
        return None, f"{name} has an invalid producer"
    if record.get("schema_version") != 1:
        return None, f"{name} has an unsupported evidence schema"
    if record.get("harness_version") != harness_version:
        return None, f"{name} was produced by harness {record.get('harness_version')}, expected {harness_version}"
    if str(record.get("status") or "") == "ENV":
        return None, f"ENV:{name} is blocked by the environment"
    if str(record.get("status") or "") != "PASS":
        return None, f"{name} status is {record.get('status')}, not PASS"
    return record, None


def validate_policy_artifact(
    repo: Path,
    plan: dict,
    policy: dict,
    state_root: Path,
    policy_path: Path,
) -> tuple[dict | None, str | None, str]:
    """Validate policy artifact integrity, status, classification freshness, and deterministic rules."""
    if policy.get("classification_sha256") is None or policy.get("policy_sha256") != canonical_sha256(
        {k: v for k, v in policy.items() if k != "policy_sha256"}
    ):
        return None, "policy artifact integrity mismatch", "BLOCKED"
    if policy.get("status") == "USER_DECISION_REQUIRED":
        return None, "material UNKNOWN surface requires developer decision", "USER_DECISION_REQUIRED"
    if policy.get("status") != "PASS":
        return None, "policy or mandatory skill routing did not pass", "BLOCKED"
    current_classification = classify(repo)
    if current_classification.get("classification_sha256") != policy.get("classification_sha256"):
        return None, "current classification does not match the run policy", "STALE"
    agents_root = repo / ".agents" if (repo / ".agents" / "skills").is_dir() else Path(__file__).resolve().parents[1]
    configured_kind = _configured_project_kind()
    if policy.get("project_kind") != configured_kind:
        return None, "policy project kind does not match installed configuration", "BLOCKED"
    task_kind = str(plan.get("task_kind") or "FEATURE")
    expected_policy = decide(
        current_classification, agents_root / "skills", project_kind=configured_kind, task_kind=task_kind
    )
    if int(policy.get("review_round") or 1) > 1:
        basis = policy.get("later_round_source") or {}
        source_run_id = str(basis.get("run_id") or "")
        try:
            previous_policy = read_json(policy_path.parent / f"policy-{source_run_id}.json")
            if previous_policy.get("policy_sha256") != canonical_sha256(
                {key: value for key, value in previous_policy.items() if key != "policy_sha256"}
            ):
                raise ValidationError("previous policy integrity mismatch")
            source_reviews = EvidenceStore(state_root).read(
                str(basis.get("snapshot") or ""), source_run_id, "reviews",
            )
            if source_reviews.get("change_set_sha256") != basis.get("change_set"):
                raise ValidationError("previous review change-set mismatch")
            reviewed_roles = set((source_reviews.get("evidence") or {}).get("reviewers") or [])
            if reviewed_roles != set(previous_policy.get("reviewers") or []):
                raise ValidationError("previous reviewer coverage does not match its policy")
            passed_reviewers = [
                str(item.get("reviewer") or "")
                for item in (source_reviews.get("evidence") or {}).get("reports") or []
                if str(item.get("verdict") or "").upper() == "PASS"
            ]
            expected_policy = decide_later_round(
                current_classification,
                agents_root / "skills",
                previous_policy=previous_policy,
                finding_owners=list(plan.get("blocked_reviewers") or []),
                passed_reviewers=passed_reviewers,
                source_snapshot=str(basis.get("snapshot") or ""),
                source_change_set=str(basis.get("change_set") or ""),
                source_run_id=source_run_id,
                round_number=int(policy.get("review_round")),
                project_kind=configured_kind,
                task_kind=task_kind,
            )
        except (ValidationError, OSError, ValueError, TypeError) as exc:
            return None, f"later-round policy source is invalid: {exc}", "BLOCKED"
    if expected_policy != policy:
        return None, "policy artifact does not match deterministic policy evaluation", "BLOCKED"
    return expected_policy, None, "PASS"


def verify(repo: Path, *, plan_path: Path, policy_path: Path, manifest_path: Path, state_root: Path, run_id: str) -> dict:
    checks: list[dict] = []
    reasons: list[str] = []
    try:
        plan = read_json(plan_path)
        policy = read_json(policy_path)
        recorded_manifest = read_json(manifest_path)
    except ValidationError as exc:
        return _blocked("BLOCKED", [str(exc)], checks)

    expected_plan_hash = canonical_sha256(plan_payload(plan))
    approval = plan.get("approval") or {}
    if plan.get("plan_sha256") != expected_plan_hash or approval.get("plan_sha256") != expected_plan_hash:
        return _blocked("PLAN_APPROVAL_REQUIRED", ["plan or approval hash mismatch"], checks)
    if not plan.get("execution_nonce") or plan.get("execution_nonce") != approval.get("single_use_nonce"):
        return _blocked("PLAN_APPROVAL_REQUIRED", ["approval was not consumed by this task run"], checks)
    approval_source = str(approval.get("source") or "")
    approval_tier = str(approval.get("enforcement_tier") or "")
    proof_hash = str(approval.get("proof_reference_sha256") or "")
    if approval_source not in {"host_native", "conversation", "developer_terminal"} or approval_tier not in {"HARD_ENFORCED", "RULE_ENFORCED"}:
        return _blocked("PLAN_APPROVAL_REQUIRED", ["approval provenance is invalid"], checks)
    if approval_tier == "HARD_ENFORCED" and approval_source != "host_native":
        return _blocked("PLAN_APPROVAL_REQUIRED", ["approval trust tier overclaims its source"], checks)
    if len(proof_hash) != 64 or any(char not in "0123456789abcdef" for char in proof_hash.lower()):
        return _blocked("PLAN_APPROVAL_REQUIRED", ["approval proof reference is missing or malformed"], checks)
    if plan.get("status") not in ("IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"):
        return _blocked("PLAN_APPROVAL_REQUIRED", [f"plan status is {plan.get('status')}"], checks)

    current = build_manifest(repo)
    recorded_file_identity = [
        {"path": item.get("path"), "content_identity": item.get("content_identity")}
        for item in recorded_manifest.get("files") or []
    ]
    if canonical_sha256(recorded_file_identity) != recorded_manifest.get("delivery_snapshot_sha256"):
        return _blocked("BLOCKED", ["delivery manifest file identity is corrupted"], checks)
    if canonical_sha256(recorded_manifest.get("changes") or []) != recorded_manifest.get("change_set_sha256"):
        return _blocked("BLOCKED", ["delivery manifest change-set identity is corrupted"], checks)
    if canonical_sha256(recorded_manifest.get("external_inputs") or []) != recorded_manifest.get("external_inputs_sha256"):
        return _blocked("BLOCKED", ["delivery manifest external-input identity is corrupted"], checks)
    for field in ("delivery_snapshot_sha256", "change_set_sha256", "external_inputs_sha256"):
        if current.get(field) != recorded_manifest.get(field):
            reasons.append(f"current {field} does not match the delivery manifest")
    if reasons:
        return _blocked("STALE", reasons, checks)

    drift = check_material_drift(plan, policy.get("surfaces") or [], changed_modules(repo, recorded_manifest))
    if drift:
        return _blocked("PLAN_APPROVAL_REQUIRED", ["material plan drift: " + ", ".join(drift)], checks)
    expected_policy, policy_error, block_status = validate_policy_artifact(
        repo, plan, policy, state_root, policy_path
    )
    if policy_error:
        return _blocked(block_status, [policy_error], checks)
    agents_root = repo / ".agents" if (repo / ".agents" / "skills").is_dir() else Path(__file__).resolve().parents[1]
    planned_skills = {(item.get("id"), item.get("sha256")) for item in plan.get("skills") or []}
    selected_skills = {(item.get("id"), item.get("sha256")) for item in (policy.get("skills") or {}).get("skills") or []}
    if planned_skills != selected_skills:
        return _blocked("PLAN_APPROVAL_REQUIRED", ["mandatory skill selection drifted from the approved plan"], checks)
    for skill in (policy.get("skills") or {}).get("skills") or []:
        path = agents_root / str(skill.get("path") or "")
        if not path.is_file() or sha256_file(path) != skill.get("sha256"):
            return _blocked("STALE", [f"mandatory skill changed or is missing: {skill.get('id')}"], checks)

    snapshot = str(current["delivery_snapshot_sha256"])
    change_set = str(current["change_set_sha256"])
    version_file = agents_root / "VERSION"
    harness_version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"
    store = EvidenceStore(state_root)
    gate_names = [name for name in policy.get("gates") or [] if name not in ("manifest", "device")]
    if "device" in (policy.get("gates") or []):
        gate_names.extend(["device_install", "device_launch"])
    for name in gate_names:
        record, error = _validate_artifact(store, snapshot, change_set, run_id, name, harness_version)
        checks.append({"name": name, "status": "PASS" if error is None else "FAIL", "detail": error or "bound evidence PASS"})
        if error:
            reasons.append(error)

    reviewers = set(policy.get("reviewers") or [])
    review_record: dict | None = None
    if reviewers:
        review_record, error = _validate_artifact(store, snapshot, change_set, run_id, "reviews", harness_version)
        checks.append({"name": "reviews", "status": "PASS" if error is None else "FAIL", "detail": error or "bound review evidence PASS"})
        if error:
            reasons.append(error)
        elif review_record:
            evidence = review_record.get("evidence") or {}
            if evidence.get("developer_override"):
                severity = str(policy.get("severity") or "").upper()
                sensitive = sorted(set(policy.get("surfaces") or []) & SENSITIVE_SURFACES)
                if severity in ("HIGH", "CRITICAL"):
                    err_msg = f"developer review override is forbidden for {severity} severity changes"
                    reasons.append(err_msg)
                    checks[-1]["status"] = "FAIL"
                    checks[-1]["detail"] = err_msg
                elif sensitive:
                    err_msg = "developer review override is forbidden on sensitive surfaces: " + ", ".join(sensitive)
                    reasons.append(err_msg)
                    checks[-1]["status"] = "FAIL"
                    checks[-1]["detail"] = err_msg
                elif not str(evidence.get("proof_reference_sha256") or "").strip():
                    err_msg = "developer review override is missing proof reference"
                    reasons.append(err_msg)
                    checks[-1]["status"] = "FAIL"
                    checks[-1]["detail"] = err_msg
                else:
                    checks[-1]["detail"] = "bound developer override PASS"

            else:
                covered = set(evidence.get("reviewers") or [])
                if not reviewers <= covered:
                    reasons.append("required reviewer coverage is incomplete")
                if evidence.get("is_truncated"):
                    reasons.append("truncated review cannot approve delivery")
                if evidence.get("blocking_findings"):
                    reasons.append("review contains unresolved blocking findings")

    for carried in policy.get("carried_reviews") or []:
        reviewer = str(carried.get("reviewer") or "")
        try:
            source = store.read(
                str(carried.get("source_snapshot") or ""),
                str(carried.get("source_run_id") or ""),
                "reviews",
            )
            source_reports = (source.get("evidence") or {}).get("reports") or []
            source_passed = {
                str(item.get("reviewer") or "")
                for item in source_reports
                if str(item.get("verdict") or "").upper() == "PASS"
            }
            if source.get("producer") != "review_orchestrator":
                raise ValidationError("invalid carried-review producer")
            if source.get("change_set_sha256") != carried.get("source_change_set"):
                raise ValidationError("carried-review change-set mismatch")
            if reviewer not in source_passed:
                raise ValidationError("source reviewer did not PASS")
            if carried.get("invalidation_reason"):
                raise ValidationError("carried review was invalidated")
            checks.append({"name": f"carried:{reviewer}", "status": "PASS", "detail": "prior PASS coverage verified"})
        except (ValidationError, KeyError) as exc:
            checks.append({"name": f"carried:{reviewer or 'unknown'}", "status": "FAIL", "detail": str(exc)})
            reasons.append(f"carried review is invalid for {reviewer or 'unknown'}: {exc}")

    if set(policy.get("surfaces") or []) & SENSITIVE_SURFACES:
        approval_record, error = _validate_artifact(store, snapshot, change_set, run_id, "sensitive_approval", harness_version)
        checks.append({"name": "sensitive_approval", "status": "PASS" if error is None else "FAIL", "detail": error or "bound sensitive approval PASS"})
        if error:
            reasons.append(error)
        elif approval_record:
            final_approval = approval_record.get("evidence") or {}
            final_source = str(final_approval.get("approval_source") or "")
            final_tier = str(final_approval.get("enforcement_tier") or "")
            final_proof = str(final_approval.get("proof_reference_sha256") or "")
            required_sensitive = set(policy.get("surfaces") or []) & SENSITIVE_SURFACES
            covered_sensitive = set(final_approval.get("surfaces") or [])
            if final_approval.get("plan_sha256") != plan.get("plan_sha256"):
                reasons.append("sensitive approval is not bound to the approved plan")
            if (final_source, final_tier) not in {
                ("host_native", "HARD_ENFORCED"),
                ("developer_terminal", "RULE_ENFORCED"),
                ("conversation", "RULE_ENFORCED"),
            }:
                reasons.append("sensitive approval provenance is invalid")
            if len(final_proof) != 64 or any(char not in "0123456789abcdef" for char in final_proof.lower()):
                reasons.append("sensitive approval proof reference is missing or malformed")
            if not required_sensitive <= covered_sensitive:
                reasons.append("sensitive approval surface coverage is incomplete")

    assemble = None
    install = None
    launch = None
    for name in ("assemble", "device_install", "device_launch"):
        try:
            record = store.read(snapshot, run_id, name)
        except ValidationError:
            continue
        if name == "assemble":
            assemble = record
        elif name == "device_install":
            install = record
        else:
            launch = record
    if install or launch:
        assemble_evidence = (assemble or {}).get("evidence") or {}
        assembled_hash = str(
            assemble_evidence.get("artifact_set_sha256")
            or (assemble_evidence.get("artifact_set") or {}).get("artifact_set_sha256")
            or ""
        )
        installed_hash = str(((install or {}).get("evidence") or {}).get("artifact_set_sha256") or "")
        launched_hash = str(((launch or {}).get("evidence") or {}).get("artifact_set_sha256") or "")
        if not assembled_hash or assembled_hash != installed_hash or installed_hash != launched_hash:
            reasons.append("assemble/install/launch artifact-set chain mismatch")
    if assemble:
        artifact_set = ((assemble.get("evidence") or {}).get("artifact_set"))
        if artifact_set:
            try:
                verify_artifact_set(repo, artifact_set)
            except Exception as exc:
                reasons.append(f"assemble artifact set is stale or invalid: {exc}")

    emergency = False
    for name in gate_names:
        if not (store.run_dir(snapshot, run_id) / f"{name}.json").is_file():
            continue
        try:
            emergency = emergency or store.read(snapshot, run_id, name).get("status") == "EMERGENCY_UNVERIFIED"
        except ValidationError:
            pass
    if emergency:
        return _blocked("EMERGENCY_UNVERIFIED", ["emergency evidence cannot approve delivery"], checks)
    if reasons:
        status = "ENV_BLOCKED" if all(reason.startswith("ENV:") for reason in reasons) else "BLOCKED"
        return _blocked(status, reasons, checks)
    return {
        "schema_version": 1,
        "status": "APPROVED",
        "delivery_snapshot_sha256": snapshot,
        "change_set_sha256": change_set,
        "plan_sha256": expected_plan_hash,
        "policy_sha256": policy["policy_sha256"],
        "run_id": run_id,
        "checks": checks,
        "blocked_by": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = verify(
        Path(args.repo),
        plan_path=Path(args.plan),
        policy_path=Path(args.policy),
        manifest_path=Path(args.manifest),
        state_root=Path(args.state_root),
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "APPROVED" else 30 if result["status"] == "ENV_BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
