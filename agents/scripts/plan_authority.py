"""Single-task plan approval and material-drift authority."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import (  # noqa: E402
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    read_json,
    repository_identity,
    utc_now,
    validate_id,
)
from delivery_manifest import build_manifest  # noqa: E402
from wizard.discovery import discover_android_modules  # noqa: E402


SCHEMA_VERSION = 1
STATES = {
    "PLAN_DRAFTED", "AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING",
    "VERIFYING", "READY_FOR_DELIVERY", "BLOCKED", "CANCELLED", "DELIVERED",
}
APPROVAL_SOURCES = {"host_native", "conversation", "developer_terminal"}
ENFORCEMENT_TIERS = {"HARD_ENFORCED", "RULE_ENFORCED"}
EXTERNAL_WRITES = {"zoho_sprints"}

SURFACE_ALIASES: dict[str, list[str]] = {
    "CODE": ["BUSINESS_LOGIC"],
    "LOGIC": ["BUSINESS_LOGIC"],
    "BUSINESS": ["BUSINESS_LOGIC"],
    "UI": ["COMPOSE_UI", "XML_UI", "RESOURCE_UI"],
    "COMPOSE": ["COMPOSE_UI"],
    "COMPOSE_UI": ["COMPOSE_UI"],
    "XML": ["XML_UI"],
    "XML_UI": ["XML_UI"],
    "RESOURCE": ["RESOURCE_UI"],
    "RESOURCES": ["RESOURCE_UI"],
    "RESOURCE_UI": ["RESOURCE_UI"],
    "STRINGS": ["LOCALIZATION"],
    "LOCALIZATION": ["LOCALIZATION"],
    "TEST": ["TEST_ONLY"],
    "TESTS": ["TEST_ONLY"],
    "TEST_ONLY": ["TEST_ONLY"],
    "DB": ["ROOM_SCHEMA", "PERSISTENCE"],
    "DATABASE": ["ROOM_SCHEMA", "PERSISTENCE"],
    "PERSISTENCE": ["PERSISTENCE"],
    "ROOM": ["ROOM_SCHEMA"],
    "ROOM_SCHEMA": ["ROOM_SCHEMA"],
    "NETWORK": ["NETWORK"],
    "API": ["NETWORK", "PUBLIC_API"],
    "PUBLIC_API": ["PUBLIC_API"],
    "PERMISSIONS": ["MANIFEST_PERMISSION"],
    "PERMISSION": ["MANIFEST_PERMISSION"],
    "MANIFEST_PERMISSION": ["MANIFEST_PERMISSION"],
    "BUILD": ["BUILD_CONFIG"],
    "BUILD_CONFIG": ["BUILD_CONFIG"],
    "GRADLE": ["BUILD_CONFIG"],
    "DOCS": ["DOCS"],
    "NATIVE": ["NATIVE_CODE"],
    "NATIVE_CODE": ["NATIVE_CODE"],
    "SECURITY": ["SECURITY"],
    "AUTH": ["AUTH"],
    "BILLING": ["BILLING"],
    "CRYPTO": ["CRYPTO"],
    "SENSITIVE_DATA": ["SENSITIVE_DATA"],
    "COROUTINES": ["COROUTINES"],
    "DEVICE_API": ["DEVICE_API"],
}

DEFAULT_APP_SURFACES: list[str] = [
    "BUSINESS_LOGIC",
    "COMPOSE_UI",
    "XML_UI",
    "RESOURCE_UI",
]


def normalize_expected_surfaces(raw_surfaces: list[str] | None) -> list[str]:
    if not raw_surfaces:
        return []
    normalized: set[str] = set()
    for item in raw_surfaces:
        cleaned = str(item or "").strip().upper()
        if not cleaned:
            continue
        if cleaned in SURFACE_ALIASES:
            normalized.update(SURFACE_ALIASES[cleaned])
        else:
            normalized.add(cleaned)
    return sorted(normalized)


def module_id(value: str) -> str:
    parts = [part for part in str(value or "").strip().replace("/", ":").split(":") if part]
    return ":" + ":".join(parts) if parts else ":"


def changed_modules(repo: Path, manifest: dict) -> list[str]:
    modules = sorted(
        ((module_id(item), module_id(item).lstrip(":").replace(":", "/")) for item in discover_android_modules(repo)),
        key=lambda item: len(item[1]), reverse=True,
    )
    found: set[str] = set()
    for change in manifest.get("changes") or []:
        for raw in (change.get("path"), change.get("old_path")):
            rel = str(raw or "").strip("/")
            if not rel:
                continue
            matched = next((candidate for candidate, prefix in modules if prefix and (rel == prefix or rel.startswith(prefix + "/"))), None)
            found.add(matched or ":")
    return sorted(found)


def plan_payload(plan: dict) -> dict:
    return {
        "schema_version": plan.get("schema_version"),
        "plan_id": plan.get("plan_id"),
        "task_id": plan["task_id"],
        "requested_outcome": plan["requested_outcome"],
        "expected_surfaces": sorted(plan.get("expected_surfaces") or []),
        "expected_modules": sorted(module_id(item) for item in (plan.get("expected_modules") or [])),
        "expected_files": sorted(plan.get("expected_files") or []),
        "test_strategy": plan.get("test_strategy") or "",
        "device_strategy": plan.get("device_strategy") or "",
        "risks": sorted(plan.get("risks") or []),
        "rollback": plan.get("rollback") or "",
        "external_writes": sorted(plan.get("external_writes") or []),
        "skills": sorted(plan.get("skills") or [], key=lambda item: (item.get("id", ""), item.get("sha256", ""))),
        "base_delivery_snapshot_sha256": plan.get("base_delivery_snapshot_sha256"),
        "base_change_set_sha256": plan.get("base_change_set_sha256"),
        "repository": plan.get("repository"),
    }


def create_plan(
    repo: Path,
    *,
    task_id: str,
    requested_outcome: str,
    expected_surfaces: list[str],
    expected_modules: list[str] | None = None,
    expected_files: list[str] | None = None,
    test_strategy: str = "",
    device_strategy: str = "",
    risks: list[str] | None = None,
    rollback: str = "",
    skills: list[dict] | None = None,
    external_writes: list[str] | None = None,
) -> dict:
    task_id = validate_id(task_id, "task id")
    if not requested_outcome.strip():
        raise ValidationError("plan requested outcome must not be empty")
    requested_external = sorted(set(external_writes or []))
    unknown_external = set(requested_external) - EXTERNAL_WRITES
    if unknown_external:
        raise ValidationError("unsupported external write authority: " + ", ".join(sorted(unknown_external)))
    base = build_manifest(repo)
    record = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": uuid.uuid4().hex,
        "task_id": task_id,
        "created_at": utc_now(),
        "status": "AWAITING_DEVELOPER_APPROVAL",
        "requested_outcome": requested_outcome.strip(),
        "expected_surfaces": normalize_expected_surfaces(expected_surfaces),
        "expected_modules": sorted({module_id(item) for item in (expected_modules or [])}),
        "expected_files": sorted(set(expected_files or [])),
        "test_strategy": test_strategy,
        "device_strategy": device_strategy,
        "risks": list(risks or []),
        "rollback": rollback,
        "external_writes": requested_external,
        "skills": skills or [],
        "base_delivery_snapshot_sha256": base["delivery_snapshot_sha256"],
        "base_change_set_sha256": base["change_set_sha256"],
        "repository": repository_identity(repo),
        "approval": None,
        "execution_nonce": None,
    }
    record["plan_sha256"] = canonical_sha256(plan_payload(record))
    return record


def approve(plan: dict, *, source: str, proof_reference: str, enforcement_tier: str) -> dict:
    if plan.get("status") != "AWAITING_DEVELOPER_APPROVAL":
        raise ValidationError("only a pending plan can be approved")
    if source not in APPROVAL_SOURCES:
        raise ValidationError(f"unsupported approval source: {source}")
    if enforcement_tier not in ENFORCEMENT_TIERS:
        raise ValidationError(f"unsupported enforcement tier: {enforcement_tier}")
    if enforcement_tier == "HARD_ENFORCED" and source != "host_native":
        raise ValidationError("only non-synthesizable host-native approval proof may be HARD_ENFORCED")
    if not str(proof_reference).strip():
        raise ValidationError("approval proof reference must not be empty")
    expected = canonical_sha256(plan_payload(plan))
    if plan.get("plan_sha256") != expected:
        raise ValidationError("plan content changed after its hash was created")
    plan["status"] = "APPROVED"
    plan["approval"] = {
        "source": source,
        "proof_reference_sha256": canonical_sha256({"reference": proof_reference}),
        "enforcement_tier": enforcement_tier,
        "approved_at": utc_now(),
        "plan_sha256": expected,
        "single_use_nonce": uuid.uuid4().hex,
    }
    return plan


def begin(repo: Path, plan: dict) -> dict:
    if plan.get("status") != "APPROVED" or not isinstance(plan.get("approval"), dict):
        raise ValidationError("implementation requires an approved plan")
    approval = plan["approval"]
    if approval.get("plan_sha256") != plan.get("plan_sha256"):
        raise ValidationError("approval is not bound to this plan")
    if plan.get("execution_nonce"):
        raise ValidationError("approval has already been consumed")
    current_repo = repository_identity(repo)
    for key in ("root_sha256", "git_common_dir_sha256", "head", "branch"):
        if current_repo.get(key) != (plan.get("repository") or {}).get(key):
            raise ValidationError(f"repository identity changed before implementation: {key}")
    current = build_manifest(repo)
    if current["delivery_snapshot_sha256"] != plan.get("base_delivery_snapshot_sha256"):
        raise ValidationError("delivery snapshot changed before implementation")
    if current["change_set_sha256"] != plan.get("base_change_set_sha256"):
        raise ValidationError("working change set changed before implementation")
    plan["execution_nonce"] = approval["single_use_nonce"]
    plan["status"] = "IMPLEMENTING"
    plan["implementation_started_at"] = utc_now()
    return plan


def require_mutation(plan: dict) -> None:
    if plan.get("status") != "IMPLEMENTING":
        raise ValidationError("mutation blocked: active plan is not IMPLEMENTING")
    approval = plan.get("approval") or {}
    if not plan.get("execution_nonce") or plan.get("execution_nonce") != approval.get("single_use_nonce"):
        raise ValidationError("mutation blocked: approval was not consumed by this task")


def check_material_drift(plan: dict, actual_surfaces: list[str], actual_modules: list[str] | None = None) -> list[str]:
    expected_surfaces = set(normalize_expected_surfaces(plan.get("expected_surfaces") or []))
    actual_surface_set = set(normalize_expected_surfaces(actual_surfaces))
    expected_modules = set(plan.get("expected_modules") or [])
    actual_module_set = set(actual_modules or [])
    return sorted(
        [f"surface:{item}" for item in actual_surface_set - expected_surfaces]
        + [f"module{item}" if item.startswith(":") else f"module:{item}" for item in actual_module_set - expected_modules]
    )


def deliver(plan: dict) -> dict:
    if plan.get("status") != "READY_FOR_DELIVERY":
        raise ValidationError("only a task in READY_FOR_DELIVERY can be marked DELIVERED")
    plan["status"] = "DELIVERED"
    plan["delivered_at"] = utc_now()
    return plan


def save_plan(path: Path, plan: dict) -> None:
    atomic_write_json(path, plan)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="Plan JSON path")
    parser.add_argument("--check", action="store_true", help="Validate the stored plan")
    args = parser.parse_args()
    plan = read_json(Path(args.plan))
    if args.check:
        if plan.get("status") not in STATES:
            raise SystemExit("[FAIL] invalid plan status")
        if canonical_sha256(plan_payload(plan)) != plan.get("plan_sha256"):
            raise SystemExit("[FAIL] plan hash mismatch")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
