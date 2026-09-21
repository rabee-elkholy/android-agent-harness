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
from plan_authority import changed_modules, check_material_drift, plan_payload, validate_plan_hash  # noqa: E402
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
    "device_signoff": {"developer_approval", "ask_question", "run_device"},
    "reviews": {"review_orchestrator", "developer_approval", "developer_override"},
    "sensitive_approval": {"developer_approval"},
    "red_evidence": {"run_tests_gate", "workflow", "developer_approval"},
    "mobile_validation_skip": {"developer_approval"},
}


def _configured_project_kind() -> str:
    try:
        from _product import PROJECT_KIND
        value = str(PROJECT_KIND or "application")
    except Exception:
        value = "application"
    return value if value in ("application", "library") else "application"


def verify_task(repo: Path, task_id: str) -> dict:
    from workflow import task_dir, state_root
    directory = task_dir(repo, task_id)
    current = read_json(directory / "current-run.json")
    manifest_p = current.get("manifest")
    if manifest_p and Path(manifest_p).exists():
        manifest_path = Path(manifest_p)
    elif (directory / f"manifest-{current.get('run_id')}.json").exists():
        manifest_path = directory / f"manifest-{current.get('run_id')}.json"
    elif (directory / "manifest.json").exists():
        manifest_path = directory / "manifest.json"
    else:
        manifest_path = Path(manifest_p) if manifest_p else (directory / "manifest.json")

    policy_p = current.get("policy")
    if policy_p and Path(policy_p).exists():
        policy_path = Path(policy_p)
    elif (directory / f"policy-{current.get('run_id')}.json").exists():
        policy_path = directory / f"policy-{current.get('run_id')}.json"
    elif (directory / "policy.json").exists():
        policy_path = directory / "policy.json"
    else:
        policy_path = Path(policy_p) if policy_p else (directory / "policy.json")

    return verify(
        repo,
        plan_path=directory / "plan.json",
        policy_path=policy_path,
        manifest_path=manifest_path,
        state_root=state_root(repo),
        run_id=str(current["run_id"]),
    )


verify_delivery = verify_task



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


def _validate_mobile_skip(
    store: EvidenceStore,
    snapshot: str,
    change_set: str,
    run_id: str,
    harness_version: str,
    plan_task_id: str | None = None,
    plan_sha256: str | None = None,
) -> tuple[dict | None, str | None]:
    try:
        record = store.read(snapshot, run_id, "mobile_validation_skip")
    except ValidationError:
        return None, None

    if str(record.get("status") or "") != "SKIPPED":
        return None, f"mobile_validation_skip status is {record.get('status')}, not SKIPPED"
    if record.get("schema_version") != 1:
        return None, "mobile_validation_skip has an unsupported evidence schema"
    if record.get("producer") not in ALLOWED_PRODUCERS.get("mobile_validation_skip", set()):
        return None, "mobile_validation_skip has an invalid producer"
    if record.get("harness_version") != harness_version:
        return None, f"mobile_validation_skip was produced by harness {record.get('harness_version')}, expected {harness_version}"
    if record.get("change_set_sha256") != change_set:
        return None, "mobile_validation_skip change-set mismatch"

    ev = record.get("evidence") or {}
    if ev.get("run_id") and ev.get("run_id") != run_id:
        return None, "mobile_validation_skip run_id mismatch"
    if plan_task_id and ev.get("task_id") and ev.get("task_id") != plan_task_id:
        return None, "mobile_validation_skip task_id mismatch"
    if plan_sha256 and ev.get("plan_sha256") and ev.get("plan_sha256") != plan_sha256:
        return None, "mobile_validation_skip plan_sha256 mismatch"

    approval_source = str(ev.get("approval_source") or "")
    if approval_source not in {"host_native", "conversation", "developer_terminal"}:
        return None, "mobile_validation_skip approval source is invalid"

    tier = str(ev.get("enforcement_tier") or "")
    if tier not in {"HARD_ENFORCED", "RULE_ENFORCED"}:
        return None, "mobile_validation_skip enforcement tier is invalid"
    if tier == "HARD_ENFORCED" and approval_source != "host_native":
        return None, "mobile_validation_skip enforcement tier overclaims its source"

    proof_hash = str(ev.get("proof_reference_sha256") or "")
    if len(proof_hash) != 64 or any(c not in "0123456789abcdef" for c in proof_hash.lower()):
        return None, "mobile_validation_skip proof reference hash is missing or malformed"

    return record, None


def validate_policy_artifact(
    repo: Path,
    plan: dict,
    policy: dict,
    state_root: Path,
    policy_path: Path,
    current_change_set: str | None = None,
    task_changes: list[dict] | None = None,
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
    current_classification = classify(repo, task_id=plan.get("task_id"), task_changes=task_changes)
    if current_classification.get("classification_sha256") != policy.get("classification_sha256"):
        return None, "current classification does not match the run policy", "STALE"
    agents_root = repo / ".agents" if (repo / ".agents" / "skills").is_dir() else Path(__file__).resolve().parents[1]
    configured_kind = _configured_project_kind()
    if policy.get("project_kind") != configured_kind:
        return None, "policy project kind does not match installed configuration", "BLOCKED"
    task_kind = str(plan.get("task_kind") or "FEATURE")
    expected_policy = decide(
        current_classification, agents_root / "skills", project_kind=configured_kind, task_kind=task_kind, plan=plan
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
                current_change_set=current_change_set,
                plan=plan,
            )
        except (ValidationError, OSError, ValueError, TypeError) as exc:
            return None, f"later-round policy source is invalid: {exc}", "BLOCKED"
    if expected_policy != policy:
        return None, "policy artifact does not match deterministic policy evaluation", "BLOCKED"
    return expected_policy, None, "PASS"


def device_chain_errors(assemble: dict | None, install: dict | None, launch: dict | None) -> list[str]:
    reasons: list[str] = []
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
        install_evidence = (install or {}).get("evidence") or {}
        launch_evidence = (launch or {}).get("evidence") or {}
        for field in ("serial_sha256", "target_user", "application_id"):
            if not install_evidence.get(field) or install_evidence.get(field) != launch_evidence.get(field):
                reasons.append(f"install/launch target identity mismatch: {field}")
        user = str(install_evidence.get("target_user") or "")
        if not user.isascii() or not user.isdecimal():
            reasons.append("install/launch must identify a numeric Android user")
        application_id = (assemble_evidence.get("artifact_set") or {}).get("application_id")
        if not application_id or application_id != install_evidence.get("application_id"):
            reasons.append("assemble/install application id mismatch")
        if launch_evidence.get("install_reference") != installed_hash:
            reasons.append("launch install reference mismatch")
    return reasons


def verify(repo: Path, *, plan_path: Path, policy_path: Path, manifest_path: Path, state_root: Path, run_id: str) -> dict:
    checks: list[dict] = []
    reasons: list[str] = []
    try:
        plan = read_json(plan_path)
        policy = read_json(policy_path)
        recorded_manifest = read_json(manifest_path)
    except ValidationError as exc:
        return _blocked("BLOCKED", [str(exc)], checks)

    valid_plan, expected_plan_hash = validate_plan_hash(
        plan, plan.get("plan_sha256"), payload_fn=plan_payload, hash_fn=canonical_sha256
    )
    approval = plan.get("approval") or {}
    if not valid_plan or approval.get("plan_sha256") != expected_plan_hash:
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
    rec_repo = recorded_manifest.get("repository") or {}
    cur_repo = current.get("repository") or {}
    for repo_field in ("root_sha256", "git_common_dir_sha256", "branch", "head"):
        if cur_repo.get(repo_field) != rec_repo.get(repo_field):
            reasons.append(f"current repository {repo_field} does not match the delivery manifest")
    lingering_scratch = list(repo.glob("scratch_*.py")) + list(repo.glob("script_step*.py"))
    if lingering_scratch:
        reasons.append(f"lingering scratch scripts detected in repository: {', '.join(p.name for p in lingering_scratch)}")
    if reasons:
        return _blocked("STALE", reasons, checks)

    task_directory = plan_path.parent
    snapshot = str(current["delivery_snapshot_sha256"])
    change_set = str(current["change_set_sha256"])
    task_changes = recorded_manifest.get("task_changes") if "task_changes" in recorded_manifest else None
    drift = check_material_drift(plan, policy.get("surfaces") or [], changed_modules(repo, recorded_manifest, task_only=True))
    if drift:
        return _blocked("PLAN_APPROVAL_REQUIRED", ["material plan drift: " + ", ".join(drift)], checks)
    expected_policy, policy_error, block_status = validate_policy_artifact(
        repo, plan, policy, state_root, policy_path, current_change_set=change_set, task_changes=task_changes
    )
    if policy_error:
        return _blocked(block_status, [policy_error], checks)
    agents_root = repo / ".agents" if (repo / ".agents" / "skills").is_dir() else Path(__file__).resolve().parents[1]
    planned_skills = {(item.get("id"), item.get("sha256")) for item in plan.get("skills") or []}
    planned_ids = {item.get("id") for item in plan.get("skills") or []}
    selected_skills = {(item.get("id"), item.get("sha256")) for item in (policy.get("skills") or {}).get("skills") or []}
    benign_skills = {"android-harness", "test-driven-development", "kotlin-coroutines-expert"}
    missing_skills = set()
    for skill_id, sha in selected_skills:
        if (skill_id, sha) in planned_skills:
            continue
        if skill_id not in planned_ids and skill_id in benign_skills:
            continue
        missing_skills.add(skill_id)
    if missing_skills:
        missing_ids = sorted(missing_skills)
        return _blocked("PLAN_APPROVAL_REQUIRED", [f"mandatory skill selection drifted from the approved plan: {', '.join(missing_ids)}"], checks)
    for skill in (policy.get("skills") or {}).get("skills") or []:
        path = agents_root / str(skill.get("path") or "")
        if not path.is_file() or sha256_file(path) != skill.get("sha256"):
            return _blocked("STALE", [f"mandatory skill changed or is missing: {skill.get('id')}"], checks)

    version_file = agents_root / "VERSION"
    harness_version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"
    store = EvidenceStore(state_root)
    mobile_skip, skip_error = _validate_mobile_skip(
        store,
        snapshot,
        change_set,
        run_id,
        harness_version,
        plan_task_id=plan.get("task_id"),
        plan_sha256=expected_plan_hash,
    )
    device_skipped = mobile_skip is not None and skip_error is None
    if skip_error:
        reasons.append(skip_error)
        checks.append({"name": "mobile_validation", "status": "FAIL", "detail": skip_error})

    gate_names = [name for name in policy.get("gates") or [] if name not in ("manifest", "device")]
    if "device" in (policy.get("gates") or []) and not device_skipped:
        gate_names.extend(["device_install", "device_launch"])
    for name in gate_names:
        record, error = _validate_artifact(store, snapshot, change_set, run_id, name, harness_version)
        checks.append({"name": name, "status": "PASS" if error is None else "FAIL", "detail": error or "bound evidence PASS"})
        if error:
            reasons.append(error)

    if policy.get("device_required") or "device" in (policy.get("gates") or []):
        if device_skipped:
            checks.append({
                "name": "mobile_validation",
                "status": "SKIPPED",
                "detail": "developer explicitly skipped manual mobile validation",
            })
        else:
            signoff_rec, signoff_err = _validate_artifact(store, snapshot, change_set, run_id, "device_signoff", harness_version)
            if signoff_err:
                checks.append({"name": "device_signoff", "status": "FAIL", "detail": f"device verification sign-off is required: {signoff_err}"})
                reasons.append(f"device verification sign-off is required: {signoff_err}")
            else:
                signoff_ev = signoff_rec.get("evidence") or {}
                signoff_detail = "bound developer device signoff PASS"
                art_err = None
                if not signoff_ev.get("proof_reference_sha256") and not signoff_ev.get("proof_reference"):
                    art_err = "device sign-off proof reference is missing"
                appr_source = str(signoff_ev.get("approval_source") or "")
                appr_tier = str(signoff_ev.get("enforcement_tier") or "")
                if appr_source and appr_source not in ("developer_terminal", "host_native", "conversation"):
                    art_err = f"untrusted device signoff approval source: '{appr_source}'"
                elif appr_tier and appr_tier not in ("HARD_ENFORCED", "RULE_ENFORCED"):
                    art_err = f"unsupported device signoff enforcement tier: '{appr_tier}'"
                elif appr_tier == "HARD_ENFORCED" and appr_source != "host_native":
                    art_err = "device signoff enforcement tier overclaims its source (HARD_ENFORCED requires host_native)"

                # Exact artifact chain & device identity validation: assemble == install == signoff
                install_rec, _ = _validate_artifact(store, snapshot, change_set, run_id, "device_install", harness_version)
                if install_rec:
                    install_ev = install_rec.get("evidence") or {}
                    inst_sha = str(install_ev.get("artifact_set_sha256") or "")
                    sign_sha = str(signoff_ev.get("artifact_set_sha256") or "")
                    if inst_sha and sign_sha and inst_sha != sign_sha:
                        art_err = f"device sign-off artifact mismatch: signoff ({sign_sha[:12]}) != device_install ({inst_sha[:12]})"
                    inst_user = str(install_ev.get("target_user") or install_ev.get("user") or "")
                    sign_user = str(signoff_ev.get("target_user") or signoff_ev.get("user") or "")
                    if inst_user and sign_user and inst_user != sign_user:
                        art_err = f"device sign-off target user mismatch: signoff ({sign_user}) != device_install ({inst_user})"
                    inst_serial = str(install_ev.get("serial_sha256") or install_ev.get("serial_hash") or "")
                    sign_serial = str(signoff_ev.get("serial_sha256") or signoff_ev.get("serial_hash") or "")
                    if inst_serial and sign_serial and inst_serial != sign_serial:
                        art_err = f"device sign-off serial mismatch: signoff ({sign_serial[:12]}) != device_install ({inst_serial[:12]})"
                if art_err:
                    checks.append({"name": "device_signoff", "status": "FAIL", "detail": art_err})
                    reasons.append(art_err)
                else:
                    checks.append({"name": "device_signoff", "status": "PASS", "detail": signoff_detail})

    is_bug = str(plan.get("task_kind") or plan.get("kind") or "").upper() == "BUG"
    if is_bug:
        debug_ev_path = task_directory / "debug-evidence.json"
        red_ev_path = task_directory / "red-evidence.json"
        has_executable_red = False
        alternate_reproduction = False
        repro_defect_ids: set[str] = set()
        repro_classes: set[str] = set()
        binding_errors: list[str] = []

        if red_ev_path.is_file():
            try:
                r2 = read_json(red_ev_path)
                schema_ver = r2.get("schema_version")
                producer = r2.get("producer")
                exp_red_hash = canonical_sha256({k: v for k, v in r2.items() if k != "red_sha256"})
                is_hash_valid = (r2.get("red_sha256") == exp_red_hash)
                if not is_hash_valid and schema_ver == 3:
                    binding_errors.append("RED evidence SHA-256 signature is invalid or corrupted")
                if r2.get("task_id") and r2.get("task_id") != plan.get("task_id"):
                    binding_errors.append(f"RED evidence task_id mismatch: {r2.get('task_id')} != {plan.get('task_id')}")
                if r2.get("plan_sha256") and r2.get("plan_sha256") != expected_plan_hash:
                    binding_errors.append("RED defect evidence is bound to a different plan hash")
                base_file = task_directory / "task-baseline.json"
                base_matches = True
                if base_file.is_file() and r2.get("baseline_sha256"):
                    try:
                        base_data = read_json(base_file)
                        if r2.get("baseline_sha256") != base_data.get("baseline_sha256"):
                            base_matches = False
                            binding_errors.append("RED evidence baseline_sha256 does not match task baseline")
                    except Exception:
                        pass
                for t in r2.get("failed_tests") or []:
                    if isinstance(t, dict):
                        if t.get("test_id"):
                            repro_defect_ids.add(str(t.get("test_id")))
                        if t.get("failure_fingerprint"):
                            repro_defect_ids.add(str(t.get("failure_fingerprint")))
                pre_fix_snap = r2.get("pre_fix_delivery_snapshot_sha256")
                if pre_fix_snap and pre_fix_snap == snapshot:
                    if any(s in ("BUSINESS_LOGIC", "ROOM_SCHEMA", "PERSISTENCE", "COMPOSE_UI", "XML_UI") for s in (policy.get("surfaces") or [])):
                        binding_errors.append("final delivery snapshot matches RED pre-fix snapshot; no code fix was applied")

                is_modern_executable_red = (
                    schema_ver == 3
                    and producer == "run_tests_gate"
                    and is_hash_valid
                    and r2.get("task_id") == plan.get("task_id")
                    and r2.get("plan_sha256") == expected_plan_hash
                    and base_matches
                    and r2.get("reproduction_kind") == "FAILING_TEST"
                    and bool(r2.get("failed_tests"))
                )
                if is_modern_executable_red:
                    has_executable_red = True
                else:
                    task_created_version = str(plan.get("harness_version") or plan.get("created_version") or "")
                    is_provably_legacy = False
                    if task_created_version and task_created_version.startswith("1.0."):
                        try:
                            minor = int(task_created_version.split(".")[2].split("-")[0])
                            if minor < 41:
                                is_provably_legacy = True
                        except Exception:
                            pass
                    if is_provably_legacy and schema_ver in (1, 2) and not binding_errors:
                        has_executable_red = True
            except Exception as exc:
                binding_errors.append(f"could not parse red-evidence.json: {exc}")

        if debug_ev_path.is_file():
            try:
                c = read_json(debug_ev_path)
                for e in c.get("entries", []):
                    kind = str(e.get("kind") or "").lower()
                    if kind in ("manual_repro", "device_repro", "log_repro"):
                        alternate_reproduction = True
                        repro_classes.add(kind.upper())
                    elif kind in ("failing_test", "test_failure"):
                        if e.get("test_name"):
                            repro_defect_ids.add(str(e.get("test_name")))
                        if e.get("test_id"):
                            repro_defect_ids.add(str(e.get("test_id")))
            except Exception:
                pass
        try:
            red_rec, red_err = _validate_artifact(store, snapshot, change_set, run_id, "red_evidence", harness_version)
            if red_err is None and str(red_rec.get("status") or "").upper() == "PASS":
                rev = red_rec.get("evidence") or {}
                red_plan_hash = rev.get("plan_sha256")
                if red_plan_hash and red_plan_hash != expected_plan_hash:
                    binding_errors.append("RED defect evidence is bound to a different plan hash")
                pre_fix_snap = rev.get("pre_fix_delivery_snapshot_sha256")
                if pre_fix_snap and pre_fix_snap == snapshot:
                    if any(s in ("BUSINESS_LOGIC", "ROOM_SCHEMA", "PERSISTENCE", "COMPOSE_UI", "XML_UI") for s in (policy.get("surfaces") or [])):
                        binding_errors.append("final delivery snapshot matches RED pre-fix snapshot; no code fix was applied")
                for t in rev.get("failed_tests") or []:
                    if isinstance(t, dict):
                        if t.get("test_name"):
                            repro_defect_ids.add(str(t.get("test_name")))
                        if t.get("fingerprint"):
                            repro_defect_ids.add(str(t.get("fingerprint")))
                rp = rev.get("red_payload") or {}
                if rp.get("schema_version") == 3 and red_rec.get("producer") == "run_tests_gate":
                    exp_rp_hash = canonical_sha256({k: v for k, v in rp.items() if k != "red_sha256"})
                    if rp.get("red_sha256") == exp_rp_hash and rp.get("task_id") == plan.get("task_id") and rp.get("plan_sha256") == expected_plan_hash and bool(rp.get("failed_tests")):
                        has_executable_red = True
        except Exception:
            pass

        # Validate that defects captured in RED do not remain failing in GREEN and were executed
        if repro_defect_ids:
            unit_test_rec, ut_err = _validate_artifact(store, snapshot, change_set, run_id, "unit_tests", harness_version)
            if unit_test_rec and ut_err is None:
                ut_ev = unit_test_rec.get("evidence") or {}
                new_regs = set(ut_ev.get("new_regressions") or [])
                still_failing = repro_defect_ids & new_regs
                if still_failing:
                    binding_errors.append(f"RED defect(s) still failing in GREEN verification: {', '.join(sorted(still_failing))}")

                executed_tests = ut_ev.get("executed_tests")
                if executed_tests is not None and isinstance(executed_tests, list):
                    executed_set = set(executed_tests)
                    executed_clean = {t.replace("#", ".").strip() for t in executed_set}
                    executed_methods = {t.split(".")[-1] for t in executed_clean if "." in t}
                    executed_classes = {".".join(t.split(".")[:-1]) for t in executed_clean if "." in t}

                    def _was_executed(defect_id: str) -> bool:
                        d_clean = defect_id.replace("#", ".").strip()
                        if d_clean in executed_clean or defect_id in executed_set:
                            return True
                        if any(d_clean.endswith(f".{ex}") or ex.endswith(f".{d_clean}") for ex in executed_clean):
                            return True
                        if d_clean in executed_methods or d_clean in executed_classes:
                            return True
                        return False

                    executed_any = any(_was_executed(did) for did in repro_defect_ids)
                    if not executed_any:
                        binding_errors.append(f"RED defect(s) not executed in GREEN verification run: {', '.join(sorted(repro_defect_ids))}")

        if binding_errors:
            for b_err in binding_errors:
                checks.append({"name": "red_evidence", "status": "FAIL", "detail": b_err})
                reasons.append(b_err)
        elif has_executable_red:
            checks.append({"name": "red_evidence", "status": "PASS", "detail": "bound RED reproduction evidence present and resolved for BUG task"})
        elif plan.get("test_strategy") in ("none", "") and (alternate_reproduction or not any(s in ("BUSINESS_LOGIC", "ROOM_SCHEMA", "PERSISTENCE") for s in (policy.get("surfaces") or []))):
            checks.append({"name": "red_evidence", "status": "PASS", "detail": "executable test-bound RED reproduction exempted (non-code surface or alternate reproduction declared)"})
        else:
            err_msg = "missing executable RED test failure evidence: applicable BUG task requires bound RED reproduction/failing-test evidence before fix"
            checks.append({"name": "red_evidence", "status": "FAIL", "detail": err_msg})
            reasons.append(err_msg)

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
                source = str(evidence.get("source") or "")
                if sensitive:
                    err_msg = f"developer review override is strictly forbidden for sensitive changes ({', '.join(sensitive)})"
                    reasons.append(err_msg)
                    checks[-1]["status"] = "FAIL"
                    checks[-1]["detail"] = err_msg
                elif source != "developer_terminal" and severity in ("HIGH", "CRITICAL"):
                    err_msg = f"developer review override via {source or 'non-terminal'} is forbidden for {severity} severity changes; requires developer_terminal"
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
                severity = str(policy.get("severity") or "").upper()
                sensitive = sorted(set(policy.get("surfaces") or []) & SENSITIVE_SURFACES)
                if severity in ("HIGH", "CRITICAL") or sensitive:
                    for rep in evidence.get("reports") or []:
                        rev_name = str(rep.get("reviewer") or "")
                        if not rep.get("independent_execution_verified"):
                            err_msg = (
                                f"reviewer {rev_name} lacks verified independent execution proof "
                                f"(self-certified by lead agent / independent_execution_verified=false) required for {severity} severity changes"
                            )
                            reasons.append(err_msg)
                            checks[-1]["status"] = "FAIL"
                            checks[-1]["detail"] = err_msg
                            break
                        proof = rep.get("execution_proof") or {}
                        if proof.get("task_id") and (proof.get("task_id") != plan.get("task_id") or proof.get("run_id") != run_id):
                            err_msg = f"reviewer {rev_name} execution proof task/run mismatch"
                            reasons.append(err_msg)
                            checks[-1]["status"] = "FAIL"
                            checks[-1]["detail"] = err_msg
                            break
                        if proof.get("package_sha256"):
                            pkg = str(proof.get("package_sha256") or "").lower()
                            exp_pkg = str(evidence.get("package_sha256") or "").lower()
                            if not (pkg.startswith(exp_pkg[:12]) or exp_pkg[:12].startswith(pkg)):
                                err_msg = f"reviewer {rev_name} execution proof package hash mismatch"
                                reasons.append(err_msg)
                                checks[-1]["status"] = "FAIL"
                                checks[-1]["detail"] = err_msg
                                break
                        if rep.get("provenance") == "subagent_execution" or proof.get("proof_kind") == "ANTIGRAVITY_SUBAGENT_TRANSCRIPT":
                            receipt_file = task_directory / "reviewer-dispatches" / f"{rev_name}.json"
                            if not receipt_file.is_file():
                                err_msg = f"reviewer {rev_name} provenance claims subagent_execution but dispatch receipt is missing"
                                reasons.append(err_msg)
                                checks[-1]["status"] = "FAIL"
                                checks[-1]["detail"] = err_msg
                                break
                            try:
                                rc = read_json(receipt_file)
                                if rc.get("schema_version") != 1 or rc.get("reviewer") != rev_name or rc.get("task_id") != plan.get("task_id") or rc.get("run_id") != run_id:
                                    err_msg = f"reviewer {rev_name} dispatch receipt does not match active task/run"
                                    reasons.append(err_msg)
                                    checks[-1]["status"] = "FAIL"
                                    checks[-1]["detail"] = err_msg
                                    break
                                expected_rc_hash = canonical_sha256({k: v for k, v in rc.items() if k != "receipt_sha256"})
                                if expected_rc_hash != rc.get("receipt_sha256"):
                                    err_msg = f"reviewer {rev_name} dispatch receipt SHA-256 is invalid"
                                    reasons.append(err_msg)
                                    checks[-1]["status"] = "FAIL"
                                    checks[-1]["detail"] = err_msg
                                    break
                            except Exception:
                                err_msg = f"reviewer {rev_name} dispatch receipt is corrupted"
                                reasons.append(err_msg)
                                checks[-1]["status"] = "FAIL"
                                checks[-1]["detail"] = err_msg
                                break

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
    if not device_skipped:
        reasons.extend(device_chain_errors(assemble, install, launch))
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
