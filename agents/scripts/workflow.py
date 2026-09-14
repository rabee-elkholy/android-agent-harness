"""Task lifecycle coordinator for planning, approval, verification preparation, and status."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print, step_progress  # noqa: E402
from _vnext_common import ValidationError, atomic_write_json, canonical_sha256, read_json, repository_identity, utc_now, validate_id  # noqa: E402
from change_classifier import classify  # noqa: E402
from delivery_manifest import build_manifest  # noqa: E402
from final_verifier import verify  # noqa: E402
from plan_authority import (  # noqa: E402
    DEFAULT_APP_SURFACES,
    approve,
    begin,
    changed_modules,
    check_material_drift,
    create_plan,
    deliver as deliver_plan,
    module_id,
    normalize_expected_surfaces,
    save_plan,
)
from review_policy import decide, decide_later_round  # noqa: E402
from evidence_store import EvidenceStore, StateLock  # noqa: E402
from _verification_recipes import get_verification_recipes  # noqa: E402


SENSITIVE_SURFACES = {"BILLING", "AUTH", "SECURITY", "SENSITIVE_DATA", "CRYPTO"}


def state_root(repo: Path) -> Path:
    installed = repo / ".agents" / "state"
    return installed if (repo / ".agents").is_dir() else repo / "agents" / "state"


def task_dir(repo: Path, task_id: str) -> Path:
    return state_root(repo) / "tasks" / validate_id(task_id, "task id")


def skills_root(repo: Path) -> Path:
    installed = repo / ".agents" / "skills"
    return installed if installed.is_dir() else Path(__file__).resolve().parents[1] / "skills"


def project_kind(repo: Path) -> str:
    try:
        import _product
        return str(getattr(_product, "PROJECT_KIND", "application") or "application")
    except Exception:
        return "application"


def _plan_path(repo: Path, task_id: str) -> Path:
    return task_dir(repo, task_id) / "plan.json"


def _load_plan(repo: Path, task_id: str) -> dict:
    return read_json(_plan_path(repo, task_id))


def _find_uncommitted_task_files(repo: Path, task_id: str, plan: dict) -> list[str]:
    manifest = build_manifest(repo)
    current_changes = {str(c.get("path") or "") for c in (manifest.get("changes") or [])}
    if not current_changes:
        return []
    task_current = task_dir(repo, task_id) / "current-run.json"
    if task_current.is_file():
        run_info = read_json(task_current)
        run_manifest_path = Path(str(run_info.get("manifest") or ""))
        if not run_manifest_path.is_absolute():
            run_manifest_path = repo / run_manifest_path
        if run_manifest_path.is_file():
            run_manifest = read_json(run_manifest_path)
            task_files = {str(c.get("path") or "") for c in (run_manifest.get("changes") or [])}
            return sorted(task_files & current_changes)
    expected = set(plan.get("expected_files") or [])
    return sorted(expected & current_changes)


def draft(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    active_path = state_root(repo) / "active-task.json"
    if active_path.is_file():
        try:
            active = read_json(active_path)
            prev_id = str(active.get("task_id") or "")
            if prev_id and prev_id != args.task_id:
                prev_plan_path = Path(str(active.get("plan_path") or ""))
                if not prev_plan_path.is_absolute():
                    prev_plan_path = repo / prev_plan_path
                if prev_plan_path.is_file():
                    prev_plan = read_json(prev_plan_path)
                    prev_status = str(prev_plan.get("status") or "")
                    if prev_status == "READY_FOR_DELIVERY":
                        dirty = _find_uncommitted_task_files(repo, prev_id, prev_plan)
                        if dirty and not getattr(args, "force", False):
                            raise ValidationError(
                                f"previous task '{prev_id}' is READY_FOR_DELIVERY with uncommitted changes: "
                                f"{', '.join(sorted(dirty))}. Commit or stash them before starting a new task, or pass --force."
                            )
                        if not dirty or getattr(args, "force", False):
                            finalize_ready_delivery(repo, prev_id, prev_plan, require_clean_tree=False)
                    elif prev_status in ("IMPLEMENTING", "VERIFYING", "APPROVED"):
                        if not getattr(args, "force", False):
                            raise ValidationError(
                                f"active task '{prev_id}' is currently {prev_status}. "
                                f"Complete or cancel it first via 'workflow.py cancel', or pass --force."
                            )
                        active_path.unlink(missing_ok=True)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(f"failed to verify prior task collision safety: {exc}")
    with step_progress("Classifying changed surfaces"):
        classification = classify(repo)
    raw_expected = [item.strip() for item in (args.expected_surfaces or "").split(",") if item.strip()]
    expected = normalize_expected_surfaces(raw_expected)
    if not expected:
        expected = list(classification.get("surfaces") or [])
    if not expected and not classification.get("changed_files"):
        expected = list(DEFAULT_APP_SURFACES)
    raw_kind = str(getattr(args, "kind", None) or "AUTO").strip().upper()
    if raw_kind not in {"AUTO", "BUG", "FEATURE", "REFACTOR"}:
        raw_kind = "AUTO"
    if raw_kind == "AUTO":
        text_to_scan = f"{args.outcome or ''} {args.expected_surfaces or ''}".lower()
        if re.search(r"\b(?:bug|crash|fix|regression|error|fault|anr|issue|exception)\b", text_to_scan):
            resolved_kind = "BUG"
        else:
            resolved_kind = "FEATURE"
    else:
        resolved_kind = raw_kind
    policy_input = dict(classification)
    policy_input["surfaces"] = expected
    with step_progress("Evaluating routing policy"):
        preliminary_policy = decide(policy_input, skills_root(repo), project_kind=project_kind(repo), task_kind=resolved_kind)
    plan = create_plan(
        repo,
        task_id=args.task_id,
        task_kind=resolved_kind,
        planning_depth=str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper(),
        requested_outcome=args.outcome,
        expected_surfaces=expected,
        expected_modules=[module_id(item) for item in (args.expected_modules or "").split(",") if item.strip()],
        test_strategy=args.test_strategy or "Policy-selected relevant tests",
        device_strategy=args.device_strategy or "Policy-selected device verification",
        risks=[item.strip() for item in (args.risks or "").split(",") if item.strip()],
        rollback=args.rollback or "Stop on conflict; preserve developer changes; no automatic Git reset",
        skills=preliminary_policy["skills"]["skills"],
        external_writes=list(getattr(args, "external_write", None) or []),
    )
    directory = task_dir(repo, args.task_id)
    directory.mkdir(parents=True, exist_ok=True)
    save_plan(directory / "plan.json", plan)
    atomic_write_json(directory / "preliminary-classification.json", classification)
    atomic_write_json(directory / "preliminary-policy.json", preliminary_policy)
    atomic_write_json(state_root(repo) / "active-task.json", {"task_id": args.task_id, "plan_path": str(directory / "plan.json"), "updated_at": utc_now()})
    return plan


def record_approval(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    tier = args.enforcement_tier
    plan = approve(plan, source=args.source, proof_reference=args.proof_reference, enforcement_tier=tier)
    save_plan(_plan_path(repo, args.task_id), plan)
    return plan


def begin_task(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    plan = begin(repo, _load_plan(repo, args.task_id))
    save_plan(_plan_path(repo, args.task_id), plan)
    return plan


def record_debug_evidence(args: argparse.Namespace) -> dict:
    """Record debug evidence for a task outside plan.json to preserve plan hash immutability."""
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    directory = task_dir(repo, args.task_id)
    directory.mkdir(parents=True, exist_ok=True)
    evidence_path = directory / "debug-evidence.json"

    with StateLock(directory / ".lock"):
        entries = []
        if evidence_path.is_file():
            try:
                content = read_json(evidence_path)
                if isinstance(content, dict) and isinstance(content.get("entries"), list):
                    entries = content["entries"]
                elif isinstance(content, list):
                    entries = content
                else:
                    raise ValidationError(f"corrupt debug evidence payload in {evidence_path}")
            except Exception as exc:
                raise ValidationError(f"cannot read existing debug evidence: {exc}")

        entry = {
            "kind": args.kind,
            "reference": args.reference,
            "hypothesis": getattr(args, "hypothesis", None) or "",
            "risk": getattr(args, "risk", None) or "",
            "recorded_at": utc_now(),
        }
        entries.append(entry)
        payload = {
            "task_id": args.task_id,
            "plan_sha256": plan.get("plan_sha256"),
            "status": plan.get("status"),
            "entries": entries,
        }
        atomic_write_json(evidence_path, payload)
        return payload


VALID_FINDING_STATES = {"CONFIRMED", "FALSE_POSITIVE", "NEEDS_CONTEXT", "NOT_REPRODUCIBLE"}


def record_finding_validation(args: argparse.Namespace) -> dict:
    """Record validation of a reviewer finding outside plan.json under state lock."""
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    directory = task_dir(repo, args.task_id)
    directory.mkdir(parents=True, exist_ok=True)
    validation_path = directory / "finding-validations.json"

    status = str(args.status or "").strip().upper()
    if status not in VALID_FINDING_STATES:
        raise ValidationError(f"invalid finding status '{status}'; must be one of {sorted(VALID_FINDING_STATES)}")

    reason = str(getattr(args, "reason", "") or "").strip()
    evidence_ref = str(getattr(args, "evidence_reference", "") or "").strip()
    if status == "FALSE_POSITIVE" and not reason:
        raise ValidationError("FALSE_POSITIVE status requires a non-empty technical reason")

    with StateLock(directory / ".lock"):
        validations = []
        if validation_path.is_file():
            try:
                content = read_json(validation_path)
                if isinstance(content, dict) and isinstance(content.get("validations"), list):
                    validations = content["validations"]
                elif isinstance(content, list):
                    validations = content
                else:
                    raise ValidationError(f"corrupt finding validations payload in {validation_path}")
            except Exception as exc:
                raise ValidationError(f"cannot read existing finding validations: {exc}")

        entry = {
            "finding_id": str(args.finding_id).strip(),
            "status": status,
            "reason": reason,
            "evidence_reference": evidence_ref,
            "recorded_at": utc_now(),
        }
        validations.append(entry)
        payload = {
            "task_id": args.task_id,
            "plan_sha256": plan.get("plan_sha256"),
            "validations": validations,
        }
        atomic_write_json(validation_path, payload)
        return payload


def prepare_verification(args_or_repo: argparse.Namespace | Path | str, task_id_or_args: Any = None) -> dict:
    if isinstance(args_or_repo, (str, Path)):
        repo = Path(args_or_repo).resolve()
        if hasattr(task_id_or_args, "task_id"):
            args = task_id_or_args
        else:
            args = argparse.Namespace(repo=str(repo), task_id=str(task_id_or_args or ""), force=False)
    else:
        args = args_or_repo
        repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    if plan.get("status") != "IMPLEMENTING":
        raise ValidationError("verification preparation requires an IMPLEMENTING plan")
    base_repo = plan.get("repository") or {}
    if base_repo:
        current_identity = repository_identity(repo)
        if base_repo.get("branch") and current_identity.get("branch") != base_repo.get("branch"):
            raise ValidationError(
                f"HEAD/branch lineage mismatch: repository branch changed from '{base_repo.get('branch')}' "
                f"to '{current_identity.get('branch')}' after task approval"
            )
        if base_repo.get("head") and current_identity.get("head") != base_repo.get("head"):
            raise ValidationError(
                f"HEAD/branch lineage mismatch: repository HEAD commit changed from '{base_repo.get('head')[:12]}' "
                f"to '{current_identity.get('head')[:12]}' after task approval"
            )
    with step_progress("Building delivery manifest & snapshot"):
        manifest = build_manifest(repo)
    with step_progress("Classifying changed surfaces"):
        classification = classify(repo)
    completed_rounds = int(plan.get("review_rounds") or 0)
    if completed_rounds:
        previous_current = read_json(task_dir(repo, args.task_id) / "current-run.json")
        previous_policy = read_json(Path(previous_current["policy"]))
        previous_reviews = EvidenceStore(state_root(repo)).read(
            str(previous_current["delivery_snapshot_sha256"]),
            str(previous_current["run_id"]),
            "reviews",
        )
        passed_reviewers = [
            str(item.get("reviewer") or "")
            for item in (previous_reviews.get("evidence") or {}).get("reports") or []
            if str(item.get("verdict") or "").upper() == "PASS"
        ]
        policy = decide_later_round(
            classification,
            skills_root(repo),
            previous_policy=previous_policy,
            finding_owners=list(plan.get("blocked_reviewers") or []),
            passed_reviewers=passed_reviewers,
            source_snapshot=str(previous_current["delivery_snapshot_sha256"]),
            source_change_set=str(previous_current["change_set_sha256"]),
            source_run_id=str(previous_current["run_id"]),
            round_number=completed_rounds + 1,
            project_kind=project_kind(repo),
            task_kind=str(plan.get("task_kind") or "FEATURE"),
            current_change_set=str(manifest["change_set_sha256"]),
            plan=plan,
        )
        calls_used = int(plan.get("review_calls_used") or 0)
        if calls_used + int(policy.get("estimated_calls_this_round") or 0) > int(policy.get("model_call_budget") or 0):
            policy["status"] = "USER_DECISION_REQUIRED"
            policy["budget_blocked"] = {
                "calls_used": calls_used,
                "requested": int(policy.get("estimated_calls_this_round") or 0),
                "budget": int(policy.get("model_call_budget") or 0),
            }
            policy["policy_sha256"] = canonical_sha256({key: value for key, value in policy.items() if key != "policy_sha256"})
    else:
        policy = decide(classification, skills_root(repo), project_kind=project_kind(repo), task_kind=str(plan.get("task_kind") or "FEATURE"), plan=plan)
    drift = check_material_drift(plan, policy.get("surfaces") or [], changed_modules(repo, manifest))
    if drift:
        plan["material_drift"] = drift
        save_plan(_plan_path(repo, args.task_id), plan)
        raise ValidationError(
            f"PLAN_APPROVAL_REQUIRED: material drift detected: {', '.join(str(k) for k in drift)}. "
            "Reconciliation and plan approval are required before verification run can begin."
        )
    if policy.get("status") != "PASS":
        raise ValidationError(f"policy preparation blocked: {policy.get('status')}")
    run_id = f"run-{uuid.uuid4().hex}"
    directory = task_dir(repo, args.task_id)
    manifest_path = directory / f"manifest-{run_id}.json"
    policy_path = directory / f"policy-{run_id}.json"
    atomic_write_json(manifest_path, manifest)
    atomic_write_json(policy_path, policy)
    plan["status"] = "VERIFYING"
    plan["verification_run_id"] = run_id
    save_plan(_plan_path(repo, args.task_id), plan)
    recipes = get_verification_recipes(policy.get("surfaces") or [])
    current = {
        "task_id": args.task_id,
        "run_id": run_id,
        "manifest": str(manifest_path),
        "policy": str(policy_path),
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "change_set_sha256": manifest["change_set_sha256"],
        "external_inputs_sha256": manifest.get("external_inputs_sha256") or "",
        "verification_recipes": recipes,
        "created_at": utc_now(),
    }
    atomic_write_json(directory / "current-run.json", current)

    # Bridge valid pre-existing gate results into EvidenceStore for this new run_id
    try:
        store = EvidenceStore(state_root(repo))
        results_dir = state_root(repo) / "results"
        if results_dir.is_dir():
            harness_version_p = repo / "VERSION" if (repo / "VERSION").is_file() else Path(__file__).resolve().parents[1] / "VERSION"
            h_ver = harness_version_p.read_text(encoding="utf-8").strip() if harness_version_p.is_file() else "1.0.0"
            producer_defaults = {
                "assemble": "run_gradle_task",
                "preflight": "preflight_check",
                "localization": "check_strings",
                "room": "room_guard",
                "unit_tests": "run_tests_gate",
                "device_install": "run_device",
                "device_launch": "run_device",
            }
            for res_path in sorted(results_dir.glob("*.json")):
                try:
                    res_data = read_json(res_path)
                    if (
                        res_data.get("delivery_snapshot_sha256") == manifest["delivery_snapshot_sha256"]
                        and res_data.get("change_set_sha256") == manifest["change_set_sha256"]
                        and str(res_data.get("status") or "").upper() == "PASS"
                    ):
                        gate_name = res_path.stem
                        if gate_name == "device":
                            continue
                        producer = str(res_data.get("producer") or producer_defaults.get(gate_name) or gate_name).replace(".py", "").replace("-", "_")
                        store.write(
                            snapshot=manifest["delivery_snapshot_sha256"],
                            run_id=run_id,
                            name=gate_name,
                            producer=producer,
                            harness_version=str(res_data.get("harness_version") or h_ver),
                            change_set=manifest["change_set_sha256"],
                            status="PASS",
                            exit_code=int(res_data.get("exit_code") or 0),
                            detail=str(res_data.get("detail") or "bridged from pre-verification gate execution"),
                        )
                except Exception:
                    pass
    except Exception:
        pass

    return current


def record_sensitive_approval(args: argparse.Namespace) -> dict:
    """Record a separate final-snapshot approval that an agent hook may not synthesize."""
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    if plan.get("status") != "VERIFYING":
        raise ValidationError("sensitive final approval requires a VERIFYING task")
    if args.source not in ("conversation", "developer_terminal", "host_native"):
        raise ValidationError("sensitive final approval source must be conversation, developer_terminal, or host_native")
    if args.source == "host_native" and args.enforcement_tier != "HARD_ENFORCED":
        raise ValidationError("host-native sensitive approval must use HARD_ENFORCED proof")
    if args.source in ("conversation", "developer_terminal") and args.enforcement_tier != "RULE_ENFORCED":
        raise ValidationError(f"{args.source} sensitive approval is RULE_ENFORCED")
    if not str(args.proof_reference).strip():
        raise ValidationError("sensitive approval proof reference must not be empty")
    current = read_json(task_dir(repo, args.task_id) / "current-run.json")
    policy = read_json(Path(current["policy"]))
    sensitive = sorted(set(policy.get("surfaces") or []) & SENSITIVE_SURFACES)
    if not sensitive:
        raise ValidationError("the active policy does not require sensitive final approval")
    manifest = build_manifest(repo)
    for field in ("delivery_snapshot_sha256", "change_set_sha256"):
        if manifest.get(field) != current.get(field):
            raise ValidationError(f"final delivery changed before sensitive approval: {field}")
    approval = {
        "plan_sha256": plan.get("plan_sha256"),
        "approval_source": args.source,
        "enforcement_tier": args.enforcement_tier,
        "proof_reference_sha256": canonical_sha256({"reference": args.proof_reference}),
        "surfaces": sensitive,
    }
    EvidenceStore(state_root(repo)).write(
        snapshot=manifest["delivery_snapshot_sha256"],
        run_id=str(current["run_id"]),
        name="sensitive_approval",
        producer="developer_approval",
        harness_version=(repo / ".agents" / "VERSION").read_text(encoding="utf-8").strip() if (repo / ".agents" / "VERSION").is_file() else "1.0.0",
        change_set=manifest["change_set_sha256"],
        status="PASS",
        evidence=approval,
    )
    return {"status": "PASS", **approval}


def verify_task(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    current = read_json(task_dir(repo, args.task_id) / "current-run.json")
    with step_progress("Executing deterministic verification checks"):
        return verify(
            repo,
            plan_path=_plan_path(repo, args.task_id),
            policy_path=Path(current["policy"]),
            manifest_path=Path(current["manifest"]),
            state_root=state_root(repo),
            run_id=str(current["run_id"]),
        )


def complete(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    result = verify_task(args)
    if result.get("status") != "APPROVED":
        raise ValidationError("delivery cannot be completed: " + "; ".join(result.get("blocked_by") or [str(result.get("status"))]))
    plan = _load_plan(repo, args.task_id)
    plan["status"] = "READY_FOR_DELIVERY"
    plan["ready_at"] = utc_now()
    plan["ready_delivery_snapshot_sha256"] = result["delivery_snapshot_sha256"]
    plan["ready_change_set_sha256"] = result["change_set_sha256"]
    plan["ready_run_id"] = result["run_id"]
    save_plan(_plan_path(repo, args.task_id), plan)
    return plan


def cancel(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    plan["status"] = "CANCELLED"
    plan["approval"] = None
    plan["execution_nonce"] = None
    plan["cancelled_at"] = utc_now()
    save_plan(_plan_path(repo, args.task_id), plan)
    active_path = state_root(repo) / "active-task.json"
    if active_path.is_file():
        try:
            active = read_json(active_path)
            if str(active.get("task_id") or "") == args.task_id:
                active_path.unlink(missing_ok=True)
        except Exception:
            pass
    return plan


def recover_stale(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    active_path = state_root(repo) / "active-task.json"
    if not active_path.is_file():
        return {"status": "NOOP", "cleared_active_task": False, "message": "no active task to recover"}
    try:
        active = read_json(active_path)
    except Exception:
        active_path.unlink(missing_ok=True)
        return {"status": "RECOVERED", "cleared_active_task": True, "reason": "corrupt_active_task_json"}

    tid = str(active.get("task_id") or getattr(args, "task_id", "") or "")
    if not tid:
        active_path.unlink(missing_ok=True)
        return {"status": "RECOVERED", "cleared_active_task": True, "reason": "missing_task_id"}

    plan_path = _plan_path(repo, tid)
    if not plan_path.is_file():
        active_path.unlink(missing_ok=True)
        return {"status": "RECOVERED", "cleared_active_task": True, "reason": "missing_plan_file"}

    try:
        plan = read_json(plan_path)
    except Exception:
        active_path.unlink(missing_ok=True)
        return {"status": "RECOVERED", "cleared_active_task": True, "reason": "corrupt_plan_json"}

    status_val = str(plan.get("status") or "")
    if status_val in ("APPROVED", "IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"):
        raise ValidationError(
            f"Cannot auto-recover healthy active task '{tid}' in status '{status_val}'. "
            f"To cancel active work, the developer must use explicit 'workflow.py cancel'."
        )

    active_path.unlink(missing_ok=True)
    return {"status": "RECOVERED", "cleared_active_task": True, "reason": f"cleared_terminal_task_status_{status_val}"}


def resume(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    if plan.get("status") not in ("VERIFYING", "BLOCKED"):
        raise ValidationError("only a verifying or blocked task can resume implementation")
    if not plan.get("approval") or plan.get("execution_nonce") != plan["approval"].get("single_use_nonce"):
        raise ValidationError("the approved execution identity is no longer valid")
    plan["status"] = "IMPLEMENTING"
    plan["resumed_at"] = utc_now()
    save_plan(_plan_path(repo, args.task_id), plan)
    return plan


def finalize_ready_delivery(
    repo: Path,
    task_id: str,
    plan: dict | None = None,
    *,
    require_clean_tree: bool = False,
) -> tuple[dict, bool]:
    """Centralized delivery finalizer.

    Validates:
    1. Task is in READY_FOR_DELIVERY.
    2. If require_clean_tree is True, no verified task files remain dirty/uncommitted in the working tree.
    3. If ready_delivery_snapshot_sha256 is present, the current repository delivery snapshot must match.

    Only then marks plan DELIVERED and clears active-task.json.
    """
    if plan is None:
        plan = _load_plan(repo, task_id)
    if plan.get("status") != "READY_FOR_DELIVERY":
        raise ValidationError(f"task '{task_id}' is in status '{plan.get('status')}', not READY_FOR_DELIVERY")

    if require_clean_tree:
        dirty = _find_uncommitted_task_files(repo, task_id, plan)
        if dirty:
            raise ValidationError(
                f"cannot deliver task '{task_id}' with dirty working tree; verified task files remain uncommitted: {', '.join(sorted(dirty))}"
            )

    ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
    if ready_snapshot:
        manifest = build_manifest(repo)
        current_snapshot = manifest["delivery_snapshot_sha256"]
        if current_snapshot != ready_snapshot:
            raise ValidationError(
                f"delivery snapshot mismatch: current repository ({current_snapshot[:12]}) "
                f"differs from verified ready snapshot ({ready_snapshot[:12]}). Content was modified after verification."
            )

    plan = deliver_plan(plan)
    save_plan(_plan_path(repo, task_id), plan)
    active_path = state_root(repo) / "active-task.json"
    if active_path.is_file():
        try:
            active = read_json(active_path)
            if str(active.get("task_id") or "") == task_id:
                active_path.unlink(missing_ok=True)
        except Exception:
            active_path.unlink(missing_ok=True)
    return plan, True


def assert_active_run_fresh(repo: Path, task_id: str, run_id: str | None = None) -> dict:
    """Validate that the active verification run is fresh and matches current repository state."""
    plan = _load_plan(repo, task_id)
    if plan.get("status") != "VERIFYING":
        raise ValidationError(f"task '{task_id}' is in status '{plan.get('status')}', not VERIFYING")
    directory = task_dir(repo, task_id)
    current_path = directory / "current-run.json"
    if not current_path.is_file():
        raise ValidationError(f"task '{task_id}' verification run is not initialized")
    current = read_json(current_path)
    if str(current.get("task_id") or "") != task_id:
        raise ValidationError(f"current-run task mismatch: expected '{task_id}', found '{current.get('task_id')}'")
    active_run_id = str(current.get("run_id") or "")
    if run_id and active_run_id != run_id:
        raise ValidationError(f"verification run mismatch: expected run '{run_id}', found '{active_run_id}'")
    manifest = build_manifest(repo)
    for key in ("delivery_snapshot_sha256", "change_set_sha256", "external_inputs_sha256"):
        curr_val = current.get(key)
        if not curr_val and key == "external_inputs_sha256" and current.get("manifest"):
            try:
                curr_val = read_json(Path(current["manifest"])).get("external_inputs_sha256")
            except Exception:
                pass
        live_val = manifest.get(key)
        if curr_val and live_val and curr_val != live_val:
            raise ValidationError(
                f"STALE: repository {key} modified after verification freeze: {curr_val[:12]} != live {live_val[:12]}"
            )
    return current


def deliver_task(
    args_or_repo: argparse.Namespace | Path | str,
    task_id: str | None = None,
    *,
    allow_dirty_tree: bool = False,
    require_clean_tree: bool | None = None,
    source: str | None = None,
) -> dict:
    if isinstance(args_or_repo, (str, Path)):
        repo = Path(args_or_repo).resolve()
        tid = str(task_id or "")
        auth_source = source or os.environ.get("HARNESS_AUTHORITY_SOURCE")
        is_dirty_override = bool(allow_dirty_tree)
        if is_dirty_override and auth_source != "developer_terminal":
            raise ValidationError(
                "Dirty-tree delivery override requires explicit developer terminal authority via '--source developer_terminal'."
            )
        clean = require_clean_tree if require_clean_tree is not None else (not allow_dirty_tree)
    else:
        args = args_or_repo
        repo = Path(args.repo).resolve()
        tid = str(args.task_id)
        auth_source = getattr(args, "source", None) or os.environ.get("HARNESS_AUTHORITY_SOURCE")
        is_dirty_override = bool(getattr(args, "allow_dirty_tree", False) or getattr(args, "developer_allow_dirty_tree", False))
        if is_dirty_override and auth_source != "developer_terminal":
            raise ValidationError(
                "Dirty-tree delivery override requires explicit developer terminal authority via '--source developer_terminal'."
            )
        clean = require_clean_tree if require_clean_tree is not None else (not is_dirty_override)
    plan, _ = finalize_ready_delivery(repo, tid, require_clean_tree=clean)
    return plan


def status(args: argparse.Namespace) -> dict:
    return _load_plan(Path(args.repo).resolve(), args.task_id)


def main(argv: list[str] | None = None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", required=True)
    common.add_argument("--task-id", required=True)
    command = sub.add_parser("draft", parents=[common])
    command.add_argument("--outcome", required=True)
    command.add_argument(
        "--kind",
        choices=("AUTO", "BUG", "FEATURE", "REFACTOR", "auto", "bug", "feature", "refactor"),
        default="AUTO",
        help="Task kind classification: AUTO, BUG, FEATURE, or REFACTOR",
    )
    command.add_argument(
        "--planning-depth",
        choices=("BOUNDED", "ARCHITECTURAL", "bounded", "architectural"),
        default="BOUNDED",
        help="Planning depth scope: BOUNDED (default) or ARCHITECTURAL",
    )
    command.add_argument("--expected-surfaces")
    command.add_argument("--expected-modules")
    command.add_argument("--test-strategy")
    command.add_argument("--device-strategy")
    command.add_argument("--risks")
    command.add_argument("--rollback")
    command.add_argument(
        "--external-write", action="append", choices=("zoho_sprints",), default=[],
        help="External mutation explicitly included in the plan presented for approval",
    )
    command.add_argument("--force", action="store_true", help="Bypass active task collision barriers")
    command.set_defaults(handler=draft)
    command = sub.add_parser("approve", parents=[common])
    command.add_argument("--source", choices=("host_native", "conversation", "developer_terminal"), required=True)
    command.add_argument("--proof-reference", required=True)
    command.add_argument("--enforcement-tier", choices=("HARD_ENFORCED", "RULE_ENFORCED"), required=True)
    command.set_defaults(handler=record_approval)
    command = sub.add_parser("approve-sensitive", parents=[common])
    command.add_argument("--source", choices=("host_native", "conversation", "developer_terminal"), required=True)
    command.add_argument("--proof-reference", required=True)
    command.add_argument("--enforcement-tier", choices=("HARD_ENFORCED", "RULE_ENFORCED"), required=True)
    command.set_defaults(handler=record_sensitive_approval)
    sub.add_parser("begin", parents=[common]).set_defaults(handler=begin_task)
    command = sub.add_parser("debug-evidence", parents=[common])
    command.add_argument("--kind", required=True, help="Evidence category (e.g. reproduction, logcat, stacktrace, test_failure, limited)")
    command.add_argument("--reference", required=True, help="Path, URI, or description of the concrete evidence")
    command.add_argument("--hypothesis", default="", help="Root cause hypothesis")
    command.add_argument("--risk", default="", help="Potential risks or side effects")
    command.set_defaults(handler=record_debug_evidence)
    command = sub.add_parser("validate-finding", parents=[common])
    command.add_argument("--finding-id", required=True, help="Identifier of the reviewer finding")
    command.add_argument("--status", choices=("CONFIRMED", "FALSE_POSITIVE", "NEEDS_CONTEXT", "NOT_REPRODUCIBLE"), required=True, help="Validation verdict of the technical claim")
    command.add_argument("--reason", default="", help="Concise technical explanation (mandatory for FALSE_POSITIVE)")
    command.add_argument("--evidence-reference", default="", help="File:line or package reference")
    command.set_defaults(handler=record_finding_validation)
    sub.add_parser("prepare-verification", parents=[common]).set_defaults(handler=prepare_verification)
    sub.add_parser("verify", parents=[common]).set_defaults(handler=verify_task)
    sub.add_parser("complete", parents=[common]).set_defaults(handler=complete)
    command = sub.add_parser("deliver", parents=[common])
    command.add_argument("--allow-dirty-tree", action="store_true", help="Explicit developer override to deliver while verified task files remain uncommitted")
    command.add_argument("--developer-allow-dirty-tree", action="store_true", help="Explicit developer-terminal override to deliver while verified task files remain uncommitted")
    command.add_argument("--source", choices=("developer_terminal", "host_native", "conversation"), default=None, help="Authority source for delivery override")
    command.set_defaults(handler=deliver_task)
    sub.add_parser("cancel", parents=[common]).set_defaults(handler=cancel)
    sub.add_parser("resume", parents=[common]).set_defaults(handler=resume)
    sub.add_parser("status", parents=[common]).set_defaults(handler=status)
    command = sub.add_parser("recover-stale")
    command.add_argument("--repo", required=True)
    command.add_argument("--task-id", default="")
    command.set_defaults(handler=recover_stale)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except (ValidationError, OSError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    if args.action == "prepare-verification":
        print(f"HARNESS_RUN_ID={result['run_id']}")
        print(f"HARNESS_DELIVERY_SNAPSHOT={result['delivery_snapshot_sha256']}")
        if result.get("verification_recipes"):
            print("VERIFICATION_RECIPES:")
            for recipe in result["verification_recipes"]:
                print(f"  [{recipe['surface']}]:")
                for step in recipe["steps"]:
                    print(f"    - {step}")
    elif args.action == "debug-evidence":
        print(f"DEBUG_EVIDENCE_RECORDED={len(result.get('entries', []))}")
    elif args.action == "validate-finding":
        print(f"FINDING_VALIDATION_RECORDED={len(result.get('validations', []))}")
    elif args.action == "verify":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"TASK_STATUS={result.get('status', 'READY')}")
    return 0 if result.get("status") not in ("BLOCKED", "STALE", "PLAN_APPROVAL_REQUIRED", "USER_DECISION_REQUIRED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
