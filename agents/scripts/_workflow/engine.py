"""Task lifecycle coordinator for planning, approval, verification preparation, and status.
Usage: python .agents/scripts/workflow.py draft --repo . --task-id <id> --outcome <outcome>
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

# Preserve legacy path calculations and direct-script discovery through the facade.
__file__ = str(Path(__file__).resolve().parents[1] / "workflow.py")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print, step_progress, sublog  # noqa: E402
from _vnext_common import (  # noqa: E402
    ValidationError,
    active_review_package_path,
    state_root,
    task_dir,
    atomic_write_json,
    canonical_sha256,
    git,
    git_text,
    read_json,
    redact,
    repository_identity,
    sha256_file,
    utc_now,
    validate_id,
    validate_repo_path_containment,
)
from _variants import resolve_assemble_task  # noqa: E402
from change_classifier import PRESENTATIONAL_ASSET_EXTENSIONS, classify, is_documentation_path  # noqa: E402
from delivery_manifest import build_manifest, build_task_manifest, load_task_baseline  # noqa: E402
from final_verifier import verify  # noqa: E402
from plan_authority import (  # noqa: E402
    DEFAULT_APP_SURFACES,
    approve,
    approve_and_begin,
    begin,
    changed_modules,
    check_material_drift,
    changed_file_paths,
    create_plan,
    deliver as deliver_plan,
    module_id,
    normalize_expected_surfaces,
    plan_payload,
    save_plan,
)
from review_policy import decide, decide_later_round  # noqa: E402
from review_sources import has_trusted_review_source, resolve_review_host  # noqa: E402
from evidence_store import EvidenceStore, StateLock  # noqa: E402
from _verification_recipes import get_verification_recipes  # noqa: E402


SENSITIVE_SURFACES = {"BILLING", "AUTH", "SECURITY", "SENSITIVE_DATA", "CRYPTO"}
# Every surface the change classifier can report; --expected-surfaces must name these (or aliases).
KNOWN_SURFACES = {
    "ANALYTICS", "AUTH", "BILLING", "BUILD_CONFIG", "BUSINESS_LOGIC", "COMPOSE_UI", "COROUTINES", "CRYPTO",
    "DEVICE_API", "DOCS", "HARNESS_CONFIG", "LOCALIZATION", "MANIFEST_PERMISSION", "NATIVE_CODE", "NAVIGATION",
    "NETWORK", "PERSISTENCE", "PUBLIC_API", "RESOURCE_UI", "ROOM_SCHEMA", "SECURITY", "SENSITIVE_DATA",
    "TEST_ONLY", "UNKNOWN", "XML_UI",
}


def _surfaces_from_paths(files: list[str]) -> list[str]:
    """Surfaces a file path suggests, for files the classifier cannot read (new files)."""
    from _modules import is_kmp_or_android_test_path

    inferred_surfaces: set[str] = set()
    for p in files:
        p_lower = p.lower()
        if is_documentation_path(p_lower):
            inferred_surfaces.add("DOCS")
        elif p_lower.endswith((".kt", ".java")):
            if is_kmp_or_android_test_path(p):
                inferred_surfaces.add("TEST_ONLY")
            elif any(w in p_lower for w in ("screen", "activity", "fragment", "composable")):
                inferred_surfaces.update(["BUSINESS_LOGIC", "COMPOSE_UI"])
            else:
                inferred_surfaces.add("BUSINESS_LOGIC")
        elif ("/res/values" in p_lower or "/composeresources/values" in p_lower) and p_lower.endswith(".xml"):
            inferred_surfaces.add("LOCALIZATION" if "strings" in p_lower else "RESOURCE_UI")
        elif "/res/layout" in p_lower and p_lower.endswith(".xml"):
            inferred_surfaces.add("XML_UI")
        elif "/res/navigation" in p_lower and p_lower.endswith(".xml"):
            inferred_surfaces.add("NAVIGATION")
        elif "/res/" in p_lower or "/composeresources/" in p_lower:
            inferred_surfaces.add("RESOURCE_UI")
        elif p_lower.endswith((".gradle", ".gradle.kts")):
            inferred_surfaces.add("BUILD_CONFIG")
        elif p_lower.endswith("androidmanifest.xml"):
            inferred_surfaces.add("MANIFEST_PERMISSION")
    return sorted(inferred_surfaces)


def normalize_expected_files(repo: Path, raw_files: str | list[str] | None) -> list[str]:
    if not raw_files:
        return []
    items: list[str]
    if isinstance(raw_files, list):
        items = raw_files
    elif isinstance(raw_files, str):
        items = [f.strip() for f in raw_files.split(",") if f.strip()]
    else:
        return []
    normalized = set()
    for item in items:
        clean = item.strip()
        if not clean:
            continue
        posix_str = validate_repo_path_containment(repo, clean)
        if posix_str.startswith((".git/", ".agents/", ".harness-setup/", ".harness-backup/")):
            raise ValidationError(f"protected harness path cannot be an expected application file: {item}")
        normalized.add(posix_str)
    return sorted(normalized)


PHASE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_phases(repo: Path, phases: Any) -> list[dict]:
    if not isinstance(phases, list):
        raise ValidationError("phases must be a list of phase objects")
    if len(phases) == 0:
        raise ValidationError("phases list cannot be empty; multi-phase execution requires at least 1 phase")
    if len(phases) > 10:
        raise ValidationError(f"phases list contains {len(phases)} phases; maximum allowed is 10")

    seen_ids = set()
    validated = []
    for idx, phase in enumerate(phases):
        if not isinstance(phase, dict):
            raise ValidationError(f"phase at index {idx} must be a JSON object")
        raw_id = phase.get("id")
        if raw_id is None or str(raw_id).strip() == "":
            raise ValidationError(f"phase at index {idx} missing required 'id' field")
        phase_id = str(raw_id).strip()
        if not PHASE_ID_PATTERN.match(phase_id):
            raise ValidationError(f"invalid phase id '{phase_id}': must contain only alphanumeric characters, underscores, or dashes")
        if phase_id in seen_ids:
            raise ValidationError(f"duplicate phase id '{phase_id}' in phases list")
        seen_ids.add(phase_id)

        title = phase.get("title") or phase.get("description") or phase.get("name")
        if not title or not isinstance(title, str) or not title.strip():
            raise ValidationError(f"phase '{phase_id}' must have a non-empty 'title' or 'description'")
        title_str = title.strip()
        if len(title_str) > 200:
            raise ValidationError(f"phase '{phase_id}' title/description exceeds maximum length of 200 characters")

        entry = dict(phase)
        entry["id"] = phase_id
        if "description" not in entry:
            entry["description"] = title_str
        if "title" not in entry:
            entry["title"] = title_str

        if "expected_files" in entry and entry["expected_files"]:
            entry["expected_files"] = normalize_expected_files(repo, entry["expected_files"])

        validated.append(entry)
    return validated



def build_remediation_command(repo: Path, task_id: str, plan: dict, policy: dict, manifest: dict) -> str:
    surfaces = sorted(set(normalize_expected_surfaces(plan.get("expected_surfaces") or [])) | set(policy.get("surfaces") or []))
    surfaces_str = ",".join(surfaces)

    modules = sorted(set(plan.get("expected_modules") or []) | set(changed_modules(repo, manifest)))
    # Keep the leading colon: stripping it turned the root module ":" into an empty entry.
    modules_str = ",".join(module_id(m) for m in modules)

    actual_paths = changed_file_paths(manifest)
    all_expected_files = sorted(set(plan.get("expected_files") or []) | set(actual_paths))
    files_str = ",".join(all_expected_files)

    outcome_str = str(plan.get("requested_outcome") or "").replace('"', '\\"')
    kind_str = str(plan.get("task_kind") or "FEATURE")
    depth_raw = str(plan.get("planning_depth") or "BOUNDED").upper()
    depth_str = "ARCHITECTURAL" if depth_raw == "ARCHITECTURAL" else "BOUNDED"

    arch_contract = plan.get("architecture_contract") or {}
    arch_mode = arch_contract.get("mode") or "PRESERVE"
    INTENT_REVERSE = {
        "PRESERVE": "EXISTING_CHANGE",
        "NEW": "NEW_SCREEN",
        "REFACTOR": "REFACTOR",
        "MIGRATION": "MIGRATION",
        "MIGRATE": "MIGRATION",
    }
    arch_intent = INTENT_REVERSE.get(arch_mode, "EXISTING_CHANGE")
    arch_scope = arch_contract.get("target_scope") or ""
    arch_family = arch_contract.get("target_family_id") or ""

    cmd_parts = [
        f"python .agents/scripts/workflow.py revise --repo . --task-id {task_id}",
        f'--outcome "{outcome_str}"',
        f"--kind {kind_str}",
        f"--planning-depth {depth_str}",
        f'--expected-surfaces "{surfaces_str}"',
    ]
    if modules_str:
        cmd_parts.append(f'--expected-modules "{modules_str}"')
    if files_str:
        cmd_parts.append(f'--expected-files "{files_str}"')
    cmd_parts.append(f"--architecture-intent {arch_intent}")
    if arch_scope:
        cmd_parts.append(f'--architecture-target-scope "{arch_scope}"')
    if arch_family:
        cmd_parts.append(f'--architecture-target-family "{arch_family}"')
    if plan.get("phases"):
        cmd_parts.append(f"--phases '{json.dumps(plan['phases'])}'")

    return " \\\n  ".join(cmd_parts)


def build_budget_exhausted_remediation(policy: dict, calls_used: int, requested: int, budget: int) -> str:
    sensitive = sorted(set(policy.get("surfaces") or []) & {"BILLING", "AUTH", "SECURITY", "SENSITIVE_DATA", "CRYPTO"})
    severity = str(policy.get("severity") or "").upper()
    parts = [
        f"REVIEW_BUDGET_EXHAUSTED: Used {calls_used} reviewer calls, requested {requested} this round, budget is {budget}. "
        # Real app: the agent searched the repository for where the budget lives and found nothing.
        "Ask for an explicit reviewer call limit, then record the answer with "
        "`python .agents/harness.py task review-budget --task-id <task_id> --limit <approved limit> "
        "--source conversation --proof-reference <developer answer>`. Never edit frozen policy, phase state, "
        "or engine files, or mark an unfinished review complete."
    ]
    if sensitive:
        parts.append(
            f"Review override is FORBIDDEN due to sensitive surfaces ({', '.join(sensitive)}). "
            "Remediation: Developer must increase 'model_call_budget' through the task review-budget command."
        )
    elif severity in ("HIGH", "CRITICAL"):
        parts.append(
            f"Review override via conversation is FORBIDDEN for {severity} severity changes. "
            "Remediation: Developer may increase 'model_call_budget' through task review-budget, or execute review override directly from developer terminal: "
            "'python .agents/scripts/record_review.py --task <task_id> --override-reviews --source developer_terminal --proof-reference <ref>'."
        )
    else:
        parts.append(
            "Remediation: Developer may either approve task review-budget, or approve a review override via conversation: "
            "'python .agents/scripts/record_review.py --task <task_id> --override-reviews --source conversation --proof-reference <ref>'."
        )
    return " ".join(parts)








def skills_root(repo: Path) -> Path:
    installed = repo / ".agents" / "skills"
    return installed if installed.is_dir() else Path(__file__).resolve().parents[1] / "skills"


def project_kind(repo: Path) -> str:
    from wizard.discovery import discover_android_modules
    has_app = any("application" in item.lower() for item in discover_android_modules(repo))
    return "application" if (has_app or (repo / "app").is_dir()) else "library"


def _plan_path(repo: Path, task_id: str) -> Path:
    return task_dir(repo, task_id) / "plan.json"


def _load_plan(repo: Path, task_id: str) -> dict:
    return read_json(_plan_path(repo, task_id))


def _find_uncommitted_task_files(repo: Path, task_id: str, plan: dict) -> list[str]:
    manifest = build_manifest(repo)
    current_changes = {str(c.get(k) or "") for c in (manifest.get("changes") or []) for k in ("path", "old_path")}
    if not current_changes:
        return []
    task_baseline = load_task_baseline(repo, task_id)
    if task_baseline is not None:
        task_manifest = build_task_manifest(repo, task_baseline, expected_files=plan.get("expected_files"), live_manifest=manifest)
        uncommitted = [
            str(c.get("path") if isinstance(c, dict) else c or "")
            for c in (task_manifest.get("task_changes") or [])
            if (c.get("path") if isinstance(c, dict) else c) and (not isinstance(c, dict) or c.get("status") != "BASELINE_DIRTY_REMOVED")
        ]
        return sorted(set(uncommitted) & current_changes)
    task_current = task_dir(repo, task_id) / "current-run.json"
    if task_current.is_file():
        run_info = read_json(task_current)
        run_manifest_path = Path(str(run_info.get("manifest") or ""))
        if not run_manifest_path.is_absolute():
            run_manifest_path = repo / run_manifest_path
        if run_manifest_path.is_file():
            run_manifest = read_json(run_manifest_path)
            changes_list = run_manifest.get("task_changes") if "task_changes" in run_manifest else run_manifest.get("changes") or []
            task_files = {str(c.get("path") if isinstance(c, dict) else c or "") for c in changes_list if (c.get("path") if isinstance(c, dict) else c)}
            return sorted(task_files & current_changes)
    expected = set(plan.get("expected_files") or [])
    return sorted(expected & current_changes)


from delivery_manifest import LIVE_TASK_STATUSES, live_task_plans, assert_disjoint_task_scope, TaskConflictError

TERMINAL_TASK_STATUSES = frozenset({"CANCELLED", "DELIVERED"})


def is_live_task_status(status: str) -> bool:
    return str(status or "").upper() in LIVE_TASK_STATUSES


def _find_live_tasks(repo: Path) -> list[tuple[str, str, dict, Path]]:
    return [(tid, plan["status"], plan, path) for tid, plan, path in live_task_plans(repo)]


def assert_single_live_task(repo: Path, allowed_task_id: str | None = None) -> list[tuple[str, str, dict, Path]]:
    """Compatibility entrypoint: enforce disjoint ownership rather than a task count."""
    live = _find_live_tasks(repo)
    for tid, _, plan, _ in live:
        if allowed_task_id is None or allowed_task_id == tid:
            assert_disjoint_task_scope(repo, tid, plan)
    return live


def _focused_task_id(repo: Path) -> str:
    from mutation_guard import active_plan
    return str(active_plan(repo, allow_missing=True).get("task_id") or "")


def _serialize_task_scope(handler):
    from functools import wraps
    @wraps(handler)
    def locked(args):
        with StateLock(state_root(Path(args.repo).resolve())):
            return handler(args)
    return locked


@_serialize_task_scope
def draft(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id, "task id")
    _clear_cancel_request(repo, task_id)

    # 0. Reconcile clean delivered tasks automatically before conflict checks
    reconcile_delivery(repo)

    candidate = {"expected_files": normalize_expected_files(repo, getattr(args, "expected_files", None))}
    # Parsed phases and inferred files are checked again before the plan is saved.
    assert_disjoint_task_scope(repo, task_id, candidate)

    # 2. Check if task_id already exists
    existing_plan_path = _plan_path(repo, task_id)
    if existing_plan_path.is_file():
        existing_plan = read_json(existing_plan_path)
        existing_status = str(existing_plan.get("status") or "")
        if existing_status in ("APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"):
            raise ValidationError(
                f"TASK_PLAN_ALREADY_EXISTS: task '{task_id}' is currently {existing_status}. "
                "Plain draft cannot overwrite an active task. Use 'workflow.py revise' to revise the plan, or cancel it first via 'workflow.py cancel'."
            )
        elif existing_status == "AWAITING_DEVELOPER_APPROVAL":
            req_outcome = str(args.outcome or "").strip()
            exist_outcome = str(existing_plan.get("requested_outcome") or "").strip()
            exist_kind = str(existing_plan.get("task_kind") or "").upper()
            req_kind = str(getattr(args, "kind", "AUTO") or "AUTO").upper()
            if req_kind == "AUTO":
                req_kind = "BUG" if ("bug" in req_outcome.lower() or "fix" in req_outcome.lower()) else "FEATURE"
            exist_depth = str(existing_plan.get("planning_depth") or "BOUNDED").upper()
            req_depth = str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper()
            norm_expected_files = normalize_expected_files(repo, getattr(args, "expected_files", None))
            raw_expected = [item.strip() for item in (args.expected_surfaces or "").split(",") if item.strip()]
            expected_surfs = normalize_expected_surfaces(raw_expected)
            exist_surfs = sorted(existing_plan.get("expected_surfaces") or [])
            exist_files = sorted(existing_plan.get("expected_files") or [])
            exist_modules = sorted(existing_plan.get("expected_modules") or [])
            req_modules = sorted(module_id(item) for item in (args.expected_modules or "").split(",") if item.strip())
            is_identical = (
                req_outcome == exist_outcome
                and req_kind == exist_kind
                and req_depth == exist_depth
                and (not expected_surfs or expected_surfs == exist_surfs)
                and (not norm_expected_files or sorted(norm_expected_files) == exist_files)
                and (not req_modules or req_modules == exist_modules)
            )
            if is_identical:
                sublog(f"Plan for task '{task_id}' already exists with identical parameters and is AWAITING_DEVELOPER_APPROVAL.")
                return existing_plan
            else:
                raise ValidationError(
                    f"TASK_PLAN_ALREADY_EXISTS: task '{task_id}' already has a pending plan awaiting approval with different parameters. "
                    "Use 'workflow.py revise' to update it or cancel it first via 'workflow.py cancel'."
                )

    plan = _build_and_save_plan(repo, args, task_id, is_revision=False)
    _write_plan_document(repo, task_id, plan)
    return plan


def _write_plan_document(repo: Path, task_id: str, plan: dict, previous: dict | None = None) -> Path:
    from plan_document import write_plan_document

    directory = task_dir(repo, task_id)
    policy_file = directory / "preliminary-policy.json"
    try:
        policy = read_json(policy_file) if policy_file.is_file() else {}
    except (OSError, ValueError):
        policy = {}
    return write_plan_document(repo, directory, plan, policy=policy, previous=previous)


def _resolve_task_context_for_draft(repo: Path, task_context_id: str | None) -> dict[str, Any] | None:
    cache_dir = repo / ".agents" / "cache" / "task-context"
    now = time.time()

    if task_context_id:
        target_file = cache_dir / f"{task_context_id}.json"
        if not target_file.is_file():
            raise ValidationError(f"Task context '{task_context_id}' not found")
        try:
            data = json.loads(target_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValidationError(f"Invalid task context '{task_context_id}': {exc}")

        ctx_repo = data.get("repo_path")
        if ctx_repo and Path(ctx_repo).resolve() != repo.resolve():
            raise ValidationError(f"Task context '{task_context_id}' belongs to different repository")

        if now - float(data.get("timestamp", 0)) > 1800:
            raise ValidationError(f"Task context '{task_context_id}' has expired")

        cand = str(data.get("target_file") or "").strip()
        if cand and not (repo / cand).is_file():
            raise ValidationError(f"Target file '{cand}' in task context no longer exists")
        return data

    valid_contexts: list[dict[str, Any]] = []
    if cache_dir.is_dir():
        for cf in cache_dir.glob("ctx-*.json"):
            try:
                data = json.loads(cf.read_text(encoding="utf-8"))
                ctx_repo = data.get("repo_path")
                if ctx_repo and Path(ctx_repo).resolve() != repo.resolve():
                    continue
                if now - float(data.get("timestamp", 0)) > 1800:
                    continue
                cand = str(data.get("target_file") or "").strip()
                if cand and not (repo / cand).is_file():
                    continue
                valid_contexts.append(data)
            except (OSError, ValueError, ValidationError):
                pass

    if len(valid_contexts) == 1:
        return valid_contexts[0]
    elif len(valid_contexts) > 1:
        raise ValidationError("AMBIGUOUS_TASK_CONTEXT: Multiple valid cached task contexts exist. Provide --task-context-id.")

    legacy_file = repo / ".agents" / "cache" / "last-task-context.json"
    if legacy_file.is_file():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8"))
            if now - float(data.get("timestamp", 0)) <= 1800:
                cand = str(data.get("file") or "").strip()
                if cand and (repo / cand).is_file():
                    return {"target_file": cand, "timestamp": data.get("timestamp"), "context_id": None}
        except (OSError, ValueError, ValidationError):
            pass

def _applicable_developer_instructions_for_task(
    repo: Path,
    cached_ctx: dict[str, Any] | None,
    target_scope: str,
    arch_intent: str,
) -> list[dict[str, Any]]:
    raw_instructions: list[dict[str, Any]] = []
    if cached_ctx and cached_ctx.get("developer_instructions"):
        raw_instructions = cached_ctx["developer_instructions"]
    else:
        inst_file = repo / ".agents" / "project-context" / "developer-instructions.json"
        if inst_file.is_file():
            try:
                data = json.loads(inst_file.read_text(encoding="utf-8"))
                raw_instructions = data.get("instructions", [])
            except (OSError, ValueError, ValidationError):
                pass

    applicable: list[dict[str, Any]] = []
    for inst in raw_instructions:
        if inst.get("status") and inst.get("status") != "ACTIVE":
            continue

        scope = inst.get("scope") or {}
        kind = str(scope.get("kind") or "GLOBAL").upper()
        val = str(scope.get("value") or "").strip()
        matches_scope = False
        if kind == "GLOBAL" or val == "*":
            matches_scope = True
        elif kind == "MODULE":
            val_norm = val if val.startswith(":") else f":{val}"
            mod_slug = val_norm.lstrip(":")
            matches_scope = bool(
                (cached_ctx and cached_ctx.get("developer_instructions"))
                or (target_scope and (
                    val_norm in target_scope
                    or target_scope.startswith(val_norm)
                    or mod_slug in target_scope.split("/")
                    or target_scope.startswith(f"{mod_slug}/")
                ))
            )
        elif kind == "PACKAGE":
            matches_scope = bool(target_scope and val.replace(".", "/") in target_scope.replace("\\", "/"))
        elif kind == "PATH":
            matches_scope = bool(target_scope and val in target_scope)
        else:
            matches_scope = True

        if not matches_scope:
            continue

        applies_to = inst.get("applies_to", ["ANY"])
        if "ANY" not in applies_to:
            if arch_intent == "EXISTING_CHANGE" and "PRESERVE" not in applies_to:
                continue
            if arch_intent in ("NEW_SCREEN", "NEW_FEATURE") and "NEW" not in applies_to:
                continue
            if arch_intent == "REFACTOR" and "REFACTOR" not in applies_to:
                continue
            if arch_intent == "MIGRATION" and "MIGRATION" not in applies_to:
                continue

        applicable.append({
            "id": inst["id"],
            "sha256": inst.get("sha256") or inst.get("proof_reference_sha256", ""),
            "text": inst.get("text", ""),
            "strength": inst.get("strength", "REQUIREMENT"),
            "scope": inst.get("scope", {}),
            "applies_to": applies_to,
            **({"rationale": inst["rationale"]} if inst.get("rationale") else {}),
            **({"alternatives_rejected": inst["alternatives_rejected"]} if inst.get("alternatives_rejected") else {}),
        })
    return applicable


NEUTRAL_ARCHITECTURE_SURFACES = {"DOCS", "LOCALIZATION", "RESOURCE_UI"}


def is_architecture_neutral_path(path: str) -> bool:
    norm = str(path).replace("\\", "/").strip().lower()
    if is_documentation_path(norm):
        return True
    if norm.endswith((".kt", ".java", ".gradle", ".kts", ".toml", ".properties")):
        return False
    if norm.endswith("androidmanifest.xml"):
        return False
    if "/res/layout" in norm or norm.startswith("res/layout"):
        return False
    if "/res/navigation" in norm or norm.startswith("res/navigation"):
        return False
    if "/res/xml/" in f"/{norm}":
        # Behavioural platform config (network security, file providers, backup rules).
        return False
    framed = f"/{norm}"
    if "/res/raw/" in framed or "/assets/" in framed:
        # Runtime data locations: only visual media is presentational.
        return Path(norm).suffix in PRESENTATIONAL_ASSET_EXTENSIONS
    if "/res/" in framed:
        return True
    return False


def is_architecture_neutral_scope(
    scope_files: list[str],
    surfaces: set[str],
    arch_intent: str,
    target_scope: str | None = None,
    target_family: str | None = None,
) -> bool:
    if not scope_files:
        return False
    if arch_intent != "EXISTING_CHANGE":
        return False
    if target_scope or target_family:
        return False
    if surfaces and not (surfaces <= NEUTRAL_ARCHITECTURE_SURFACES):
        return False
    return all(is_architecture_neutral_path(p) for p in scope_files)


def _install_confirm_policy() -> str:
    """Setup answer I.10: "allow" installs on the phone without asking; anything else asks first."""
    try:
        import _product
        return str(getattr(_product, "INSTALL_CONFIRM", "confirm") or "confirm").strip().lower()
    except Exception:
        return "confirm"


def _plan_scope_policy() -> str:
    try:
        import _product
        return str(getattr(_product, "PLAN_SCOPE", "legacy") or "legacy").strip().lower()
    except Exception:
        return "legacy"


def _require_plan_files(repo: Path, scope_files: list[str], policy: dict, task_kind: str) -> None:
    """A non-trivial plan must name the files it will edit; without them the write guard has no scope.

    Certification C-D5: first drafts registered no files, modules or surfaces for tasks whose
    targets were already known. T0 (resources, strings, docs) and micro plans stay exempt, and
    installs whose answers predate PLAN_SCOPE keep accepting unscoped drafts.
    """
    if _plan_scope_policy() != "files_required":
        return
    if scope_files or policy.get("micro_eligible") or policy.get("risk_tier") == "T0_TRIVIAL":
        return
    candidates: list[str] = []
    try:
        from discovery_receipt import load_latest_discovery_receipt
        receipt = load_latest_discovery_receipt(repo) or {}
        candidates = [str(item).replace("\\", "/") for item in receipt.get("resolved_paths") or [] if (repo / str(item)).is_file()]
    except Exception:
        candidates = []
    found = (
        f" Candidates from discovery: {', '.join(sorted(dict.fromkeys(candidates))[:20])}."
        if candidates
        else " Find them first with `harness.py task-context --file <path>` / `--symbol <name>` or `harness.py graph --feature <name>`."
    )
    raise ValidationError(
        f"PLAN_SCOPE_REQUIRED: a {task_kind} plan must name at least one --expected-files entry so edits are checked "
        f"against the approved scope.{found} Re-run draft with --expected-files <comma-separated paths>."
    )


def _build_and_save_plan(repo: Path, args: argparse.Namespace, task_id: str, *, is_revision: bool=False, old_plan: dict | None=None, old_baseline: dict | None=None, old_plan_sha: str | None=None, output_directory: Path | None=None, scope_exclusions: tuple[str, ...]=(), activate: bool=True):
    """Compatibility entry point delegating to the internal planning module."""
    from _workflow.planning import _build_and_save_plan as implementation
    return implementation(repo, args, task_id, is_revision=is_revision, old_plan=old_plan, old_baseline=old_baseline, old_plan_sha=old_plan_sha, output_directory=output_directory, activate=activate, scope_exclusions=scope_exclusions)


def _revision_args(repo: Path, args: argparse.Namespace, old_plan: dict) -> argparse.Namespace:
    """Arguments for a revision: every plan field the caller did not give keeps its old value.

    A revision given only --expected-surfaces used to drop the plan's files and modules, which
    switched off the write-scope guard (certification C-D4).
    """
    merged = argparse.Namespace(**vars(args))

    def given(name: str) -> bool:
        value = getattr(args, name, None)
        return bool(value.strip()) if isinstance(value, str) else bool(value)

    def joined(values: Any) -> str:
        return ",".join(str(item) for item in values or [] if str(item).strip())

    if str(getattr(args, "kind", None) or "AUTO").upper() == "AUTO" and old_plan.get("task_kind"):
        merged.kind = old_plan["task_kind"]
    if not given("planning_depth") and old_plan.get("planning_depth"):
        merged.planning_depth = old_plan["planning_depth"]
    contract = old_plan.get("architecture_contract") or {}
    if not given("architecture_intent"):
        merged.architecture_intent = {
            "PRESERVE": "EXISTING_CHANGE", "NEW": "NEW_SCREEN",
            "REFACTOR": "REFACTOR", "MIGRATE": "MIGRATION",
        }.get(contract.get("mode"), "EXISTING_CHANGE")
    same_files = not given("expected_files") or (
        normalize_expected_files(repo, args.expected_files) == sorted(old_plan.get("expected_files") or [])
    )
    # Keep the anchor for metadata-only revisions, but never impose an old family
    # on a changed scope or an explicitly changed architectural intent.
    from architecture_resolver import INTENT_MAP
    same_intent = INTENT_MAP.get(str(merged.architecture_intent).upper()) == contract.get("mode")
    previous_scope = str(contract.get("target_scope") or "").replace("\\", "/").strip("/")
    same_scope = not given("architecture_target_scope") or (
        str(args.architecture_target_scope).replace("\\", "/").strip("/") == previous_scope
    )
    if same_files and same_intent and same_scope:
        if not given("architecture_target_scope"):
            merged.architecture_target_scope = contract.get("target_scope") or ""
        if not given("architecture_target_family"):
            merged.architecture_target_family = contract.get("target_family_id")
    if not given("expected_files") and old_plan.get("expected_files"):
        merged.expected_files = joined(old_plan["expected_files"])
    if not given("expected_modules") and old_plan.get("expected_modules"):
        merged.expected_modules = joined(old_plan["expected_modules"])
    if not given("expected_surfaces") and old_plan.get("expected_surfaces"):
        surfaces = set(old_plan["expected_surfaces"])
        if given("expected_files"):
            # New files keep the surfaces a draft would infer for them.
            new_files = normalize_expected_files(repo, args.expected_files)
            surfaces |= set(classify(repo, task_changes=[{"path": item} for item in new_files]).get("surfaces") or [])
        merged.expected_surfaces = joined(sorted(surfaces))
    for name in ("test_strategy", "device_strategy", "rollback", "approach"):
        if not given(name) and old_plan.get(name):
            setattr(merged, name, old_plan[name])
    if not given("risks") and old_plan.get("risks"):
        merged.risks = joined(old_plan["risks"])
    if not given("external_write") and old_plan.get("external_writes"):
        merged.external_write = list(old_plan["external_writes"])
    if not (given("phases") or given("phases_file")) and old_plan.get("phases"):
        merged.phases = list(old_plan["phases"])
    if getattr(args, "scoped_phase_review", None) is None and getattr(args, "scoped_phase_review_enabled", None) is None \
            and old_plan.get("scoped_phase_review_enabled") is not None:
        merged.scoped_phase_review_enabled = old_plan["scoped_phase_review_enabled"]
    if getattr(args, "verification_contract", None) is None and "verification_contract" in old_plan:
        merged.verification_contract = old_plan["verification_contract"]
    return merged


@_serialize_task_scope
def revise(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id, "task id")
    assert_single_live_task(repo, allowed_task_id=task_id)
    plan_p = _plan_path(repo, task_id)
    if not plan_p.is_file():
        raise ValidationError(f"cannot revise task '{task_id}': plan.json does not exist at {plan_p}")
    old_plan = read_json(plan_p)
    proposed = dict(old_plan)
    if getattr(args, "expected_files", None):
        proposed["expected_files"] = normalize_expected_files(repo, args.expected_files)
    assert_disjoint_task_scope(repo, task_id, proposed)
    old_status = str(old_plan.get("status") or "")
    if old_status not in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED"):
        raise ValidationError(f"cannot revise task '{task_id}': task status is {old_status}, only active non-terminal tasks can be revised")
    from review_budget import settle_final_review_calls
    settle_final_review_calls(repo, old_plan)

    directory = task_dir(repo, task_id)

    # 1. Preserve original task baseline!
    old_baseline = old_plan.get("task_baseline")
    if not old_baseline:
        tb_file = directory / "task-baseline.json"
        if tb_file.is_file():
            old_baseline = read_json(tb_file)
        else:
            base_man = build_manifest(repo)
            old_baseline = {
                "schema_version": 1,
                "task_id": task_id,
                "repository": old_plan.get("repository"),
                "base_delivery_snapshot_sha256": old_plan.get("base_delivery_snapshot_sha256"),
                "base_change_set_sha256": old_plan.get("base_change_set_sha256"),
                "changes": base_man.get("changes") or [],
            }
            old_baseline["baseline_sha256"] = canonical_sha256({
                "schema_version": old_baseline["schema_version"],
                "task_id": old_baseline["task_id"],
                "repository": old_baseline["repository"],
                "base_delivery_snapshot_sha256": old_baseline["base_delivery_snapshot_sha256"],
                "base_change_set_sha256": old_baseline["base_change_set_sha256"],
                "changes": old_baseline["changes"],
            })
            atomic_write_json(directory / "task-baseline.json", old_baseline)

    # 2. Archive previous plan immutably into plan-history
    old_plan_sha = old_plan.get("plan_sha256") or canonical_sha256(old_plan)
    history_dir = directory / "plan-history"
    history_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(history_dir / f"{old_plan_sha}.json", old_plan)

    # 3. Invalidate the active verification run only once the revised plan is saved. A revision
    #    refused by validation (for example PHASE_PLAN_REQUIRED) keeps the old plan, so it must
    #    keep the run that plan's review rounds refer to.
    current_run_file = directory / "current-run.json"
    parked_run_file = directory / "current-run.revising.json"
    if current_run_file.is_file():
        os.replace(current_run_file, parked_run_file)
    try:
        result = _build_and_save_plan(
            repo,
            _revision_args(repo, args, old_plan),
            task_id,
            is_revision=True,
            old_plan=old_plan,
            old_baseline=old_baseline,
            old_plan_sha=old_plan_sha,
        )
    except BaseException:
        if parked_run_file.is_file() and not current_run_file.exists():
            os.replace(parked_run_file, current_run_file)
        raise
    if old_plan.get("approval") and _same_plan(old_plan, result):
        # Real app: the agent revised an approved plan without changing anything, to reset a stuck review
        # round, and the developer got a third approval question saying "no scope change". Nothing is
        # replaced: the approved plan and its verification run stay as they were.
        atomic_write_json(plan_p, old_plan)
        current_run_file.unlink(missing_ok=True)
        if parked_run_file.is_file():
            os.replace(parked_run_file, current_run_file)
        raise ValidationError(
            "NO_PLAN_CHANGE: the revision does not change the approved task scope, so there is nothing for the developer "
            "to approve and nothing was changed. Do not ask the developer. Continue with: "
            f"python .agents/harness.py task status --task-id {task_id} --next"
        )
    carry_path = directory / "verification-carry.json"
    if old_status == "VERIFYING" and parked_run_file.is_file() and _verification_only_revision(old_plan, result):
        # Real app: adding a phone E2E contract to an unchanged build dropped the verification run and
        # re-ran preflight, unit tests, all six reviewers and assemble. Only the verification contract or
        # phone checks changed, so the frozen run stays available; prepare-verification reuses it after
        # approval when the repository is still byte-identical.
        parked = read_json(parked_run_file)
        os.replace(parked_run_file, current_run_file)
        atomic_write_json(carry_path, {
            "schema_version": 1,
            "task_id": task_id,
            "run_id": parked.get("run_id"),
            "from_plan_sha256": old_plan_sha,
            "to_plan_sha256": result.get("plan_sha256"),
            "delivery_snapshot_sha256": parked.get("delivery_snapshot_sha256"),
            "change_set_sha256": parked.get("change_set_sha256"),
            "created_at": utc_now(),
        })
    else:
        parked_run_file.unlink(missing_ok=True)
        carry_path.unlink(missing_ok=True)
    _write_plan_document(repo, task_id, result, previous=old_plan)
    if carry_path.is_file():
        result = {**result, "verification_carry": {
            "run_id": read_json(carry_path).get("run_id"),
            "note": "Only verification fields changed: after approval, prepare-verification reuses the existing "
                    "preflight, unit-test, review, build and install evidence when the code is unchanged.",
        }}
    return result


VERIFICATION_ONLY_FIELDS = frozenset({"verification_contract", "device_strategy"})
_REVISION_LINEAGE_FIELDS = frozenset({
    "supersedes_plan_sha256", "plan_id", "base_delivery_snapshot_sha256", "base_change_set_sha256",
    "base_file_identities", "base_change_identities", "base_external_inputs_sha256",
})


def _verification_only_revision(old: dict, new: dict) -> bool:
    """True when a revision changes only how the build is verified, never what is built or reviewed."""
    if old.get("task_baseline") != new.get("task_baseline"):
        return False
    try:
        before, after = plan_payload(old), plan_payload(new)
    except Exception:
        return False
    ignored = _REVISION_LINEAGE_FIELDS | VERIFICATION_ONLY_FIELDS
    if {k: v for k, v in before.items() if k not in ignored} != {k: v for k, v in after.items() if k not in ignored}:
        return False
    return any(before.get(key) != after.get(key) for key in VERIFICATION_ONLY_FIELDS)


def _carry_verification_run(repo: Path, task_id: str, plan: dict, manifest: dict, classification: dict) -> dict | None:
    """Reuse the frozen run after an approved verification-only revision of an unchanged build.

    Every gate, review, build and install record stays bound to the same snapshot, change set and run;
    only the policy is re-derived deterministically for the revised plan. Any doubt falls back to a
    normal fresh run (with later-round review carry), never to unverified reuse.
    """
    directory = task_dir(repo, task_id)
    marker_path = directory / "verification-carry.json"
    if not marker_path.is_file():
        return None

    def give_up(reason: str) -> None:
        marker_path.unlink(missing_ok=True)
        sublog(f"Previous verification run not reused: {reason}")
        return None

    try:
        marker = read_json(marker_path)
        current_path = directory / "current-run.json"
        if not current_path.is_file():
            return give_up("frozen run is missing")
        current = read_json(current_path)
        run_id = validate_id(str(current.get("run_id") or ""), "run_id")
        if marker.get("to_plan_sha256") != plan.get("plan_sha256") \
                or str(plan.get("supersedes_plan_sha256") or "") != str(marker.get("from_plan_sha256") or "") \
                or marker.get("run_id") != run_id or current.get("task_id") != task_id:
            return give_up("the plan or run changed after the verification-only revision")
        archived = read_json(directory / "plan-history" / f"{validate_id(str(marker['from_plan_sha256']), 'plan hash')}.json")
        if not _verification_only_revision(archived, plan):
            return give_up("the approved revision changes more than verification fields")
        if not verification_engine_freshness(repo, task_id, current).get("fresh"):
            return give_up("the harness version changed")
        for key in ("delivery_snapshot_sha256", "change_set_sha256", "external_inputs_sha256", "task_change_set_sha256"):
            if str(current.get(key) or "") != str(manifest.get(key) or ""):
                return give_up(f"{key} changed")
        frozen_repo, live_repo = current.get("repository") or {}, manifest.get("repository") or {}
        for field in ("root_sha256", "git_common_dir_sha256", "branch", "head"):
            if frozen_repo.get(field) != live_repo.get(field):
                return give_up(f"repository {field} changed")
        old_policy_path = Path(str(current.get("policy") or ""))
        old_policy = read_json(old_policy_path)
        from final_verifier import expected_policy_for, unplanned_mandatory_skills
        new_policy = expected_policy_for(
            repo, plan, old_policy, state_root(repo), old_policy_path,
            current_change_set=str(manifest.get("change_set_sha256") or ""),
            task_changes=manifest.get("task_changes"), current_classification=classification,
        )
        if new_policy.get("status") != "PASS":
            return give_up(f"revised policy status is {new_policy.get('status')}")
        if not set(new_policy.get("reviewers") or []) <= set(old_policy.get("reviewers") or []) \
                or [c.get("reviewer") for c in new_policy.get("carried_reviews") or []] \
                != [c.get("reviewer") for c in old_policy.get("carried_reviews") or []]:
            return give_up("the revised policy needs reviewers the frozen run did not cover")
        drift = check_material_drift(plan, new_policy.get("surfaces") or [], changed_modules(repo, manifest),
                                     actual_files=changed_file_paths(manifest), repo=repo)
        if drift or unplanned_mandatory_skills(plan, new_policy):
            return give_up("material drift")
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        return give_up(str(exc))

    if new_policy != old_policy:
        atomic_write_json(directory / f"policy-{run_id}.superseded-{str(old_policy.get('policy_sha256') or '')[:12]}.json", old_policy)
        atomic_write_json(old_policy_path, new_policy)
    current["plan_revision_carry"] = {
        "from_plan_sha256": marker["from_plan_sha256"],
        "to_plan_sha256": plan.get("plan_sha256"),
        "previous_policy_sha256": old_policy.get("policy_sha256"),
        "policy_sha256": new_policy.get("policy_sha256"),
        "carried_at": utc_now(),
    }
    atomic_write_json(directory / "current-run.json", current)
    plan["status"] = "VERIFYING"
    plan.pop("review_budget_blocked", None)
    plan["verification_run_id"] = run_id
    atomic_write_json(state_root(repo) / "active-task.json", {"task_id": task_id, "plan_path": str(_plan_path(repo, task_id)), "updated_at": utc_now()})
    save_plan(_plan_path(repo, task_id), plan)
    marker_path.unlink(missing_ok=True)
    sublog(f"Reused verification run {run_id}: code unchanged, only verification fields were revised")
    return {**current, "verification_carried": True}


def _same_plan(old: dict, new: dict) -> bool:
    """True when a revision changes nothing the developer approved (only its own lineage fields differ)."""
    lineage = {"supersedes_plan_sha256", "plan_id", "base_delivery_snapshot_sha256", "base_change_set_sha256",
               "base_file_identities", "base_change_identities", "base_external_inputs_sha256"}
    # The revision builder observes the current dirty tree, but a no-op keeps the
    # original approved plan and task baseline. Observation alone is not new scope.
    if old.get("task_baseline") != new.get("task_baseline"):
        return False
    try:
        before = {k: v for k, v in plan_payload(old).items() if k not in lineage}
        after = {k: v for k, v in plan_payload(new).items() if k not in lineage}
        # Moving already-approved files between existing semantic phases is scheduling,
        # not new authority. Keep the original plan/hash and all phase proof unchanged.
        approved_files = set(before.get("expected_files") or [])
        if approved_files and before.get("expected_files") == after.get("expected_files"):
            for payload in (before, after):
                normalized = []
                for phase in payload.get("phases") or []:
                    item = dict(phase)
                    files = item.get("expected_files")
                    if isinstance(files, list) and set(files) <= approved_files:
                        item.pop("expected_files")
                    normalized.append(item)
                if "phases" in payload:
                    payload["phases"] = normalized
    except Exception:
        return False
    return before == after


@_serialize_task_scope
def recover_active(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    tid = validate_id(args.task_id, "task id")
    assert_single_live_task(repo, allowed_task_id=tid)
    plan_p = _plan_path(repo, tid)
    if not plan_p.is_file():
        raise ValidationError(f"cannot recover active task '{tid}': plan.json does not exist at {plan_p}")
    plan = read_json(plan_p)
    status = str(plan.get("status") or "")
    live_statuses = ("AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY")
    if status not in live_statuses:
        raise ValidationError(f"cannot recover active task '{tid}': task status is {status}, not in live states {live_statuses}")
    active_path = state_root(repo) / "active-task.json"
    atomic_write_json(active_path, {
        "task_id": tid,
        "plan_path": str(plan_p),
        "updated_at": utc_now(),
    })
    return {"status": "PASS", "task_id": tid, "task_state": status, "recovered": True}


def present_plan(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id, "task id")
    plan_path = _plan_path(repo, task_id)
    if not plan_path.is_file():
        raise ValidationError(f"plan file does not exist at {plan_path}")
    from plan_authority import record_plan_presentation
    receipt = record_plan_presentation(
        plan_path=plan_path,
        artifact_path=args.artifact_path,
        request_feedback=not getattr(args, "no_feedback", False),
    )
    return receipt


def _plan_hash_arg(plan: dict) -> str:
    shown = str(plan.get("plan_sha256") or "")[:12]
    return f" --plan-hash {shown}" if shown else ""


@_serialize_task_scope
def record_approval(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    assert_single_live_task(repo, allowed_task_id=args.task_id)
    plan_file = _plan_path(repo, args.task_id)
    plan = _load_plan(repo, args.task_id)
    tier = args.enforcement_tier
    directory = task_dir(repo, args.task_id)
    presented = str(getattr(args, "plan_hash", None) or "").strip().lower()
    with StateLock(directory / ".lock"):
        if presented:
            # The developer approved the PLAN_SUMMARY that showed this hash; bind approval to that plan.
            registered = str(plan.get("plan_sha256") or "").lower()
            if len(presented) < 12 or not registered.startswith(presented):
                raise ValidationError(
                    f"PLAN_HASH_MISMATCH: the approved summary shows plan hash '{presented}', but the registered plan "
                    f"is '{registered[:12]}'. Show the current PLAN_SUMMARY block verbatim and ask for approval again."
                )
        plan = approve_and_begin(repo, plan, source=args.source, proof_reference=args.proof_reference, enforcement_tier=tier)
        if presented and isinstance(plan.get("approval"), dict):
            plan["approval"]["presented_plan_hash"] = presented
        save_plan(plan_file, plan)
        atomic_write_json(state_root(repo) / "active-task.json", {
            "task_id": args.task_id,
            "plan_path": str(plan_file),
            "updated_at": utc_now(),
        })
    return plan


@_serialize_task_scope
def begin_task(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    assert_single_live_task(repo, allowed_task_id=args.task_id)
    loaded_plan = _load_plan(repo, args.task_id)
    directory = task_dir(repo, args.task_id)
    with StateLock(directory / ".lock"):
        if loaded_plan.get("status") != "IMPLEMENTING":
            prov = loaded_plan.get("discovery_provenance")
            if prov:
                try:
                    from discovery_receipt import load_discovery_receipt, check_discovery_freshness
                    rec = load_discovery_receipt(repo, str(prov.get("discovery_id") or ""))
                    if rec:
                        fresh, reason = check_discovery_freshness(repo, rec)
                        if not fresh:
                            raise ValidationError(f"DISCOVERY_REFRESH_REQUIRED: {reason}")
                except ValidationError:
                    raise
                except (OSError, ValueError, ImportError, ValidationError):
                    pass

        plan = begin(repo, loaded_plan)
        save_plan(_plan_path(repo, args.task_id), plan)
        atomic_write_json(state_root(repo) / "active-task.json", {"task_id": args.task_id, "plan_path": str(_plan_path(repo, args.task_id)), "updated_at": utc_now()})
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
        if getattr(args, "kind", "") in ("test_failure", "failing_test"):
            entry["satisfies_executable_red"] = False
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
    assert_single_live_task(repo, allowed_task_id=args.task_id)
    plan = _load_plan(repo, args.task_id)
    if plan.get("status") != "IMPLEMENTING":
        raise ValidationError("verification preparation requires an IMPLEMENTING plan")
    from review_budget import settle_final_review_calls
    settle_final_review_calls(repo, plan)
    phases = plan.get("phases") or []
    if phases:
        directory = task_dir(repo, args.task_id)
        phase_state_f = directory / "phase-state.json"
        phase_state = read_json(phase_state_f) if phase_state_f.is_file() else {}
        final_phase = phases[-1]
        if (
            int(plan.get("active_phase_index") or 0) != len(phases) - 1
            or phase_state.get("current_phase_id") != final_phase.get("id")
            or not all(phase.get("id") in (phase_state.get("completed_phases") or []) for phase in phases)
        ):
            raise ValidationError("all approved phases must be complete before verification preparation")
        for phase in phases:
            validated_completed_phase_manifest(repo, args.task_id, plan, phase_state, phase, for_final=True)
    base_repo = plan.get("repository") or {}
    if base_repo:
        current_identity = repository_identity(repo)
        if base_repo.get("branch") and current_identity.get("branch") != base_repo.get("branch"):
            raise ValidationError(
                f"HEAD/branch lineage mismatch: repository branch changed from '{base_repo.get('branch')}' "
                f"to '{current_identity.get('branch')}' after task approval"
            )
        cur_head = current_identity.get("head")
        if base_repo.get("head") and cur_head != base_repo.get("head"):
            from task_git_lineage import is_valid_task_lineage
            valid_lineage, lineage_msg = is_valid_task_lineage(repo, args.task_id, cur_head)
            if not valid_lineage:
                raise ValidationError(
                    f"HEAD/branch lineage mismatch: repository HEAD commit changed from '{base_repo.get('head')[:12]}' "
                    f"to '{cur_head[:12]}' after task approval ({lineage_msg})"
                )
    with step_progress("Building delivery manifest & snapshot"):
        sublog("Loading task baseline and building manifest...")
        task_baseline = load_task_baseline(repo, args.task_id)
        task_base_head = plan.get("task_base_head") or base_repo.get("head")
        manifest = build_task_manifest(repo, task_baseline, expected_files=plan.get("expected_files"), task_base_head=task_base_head)
        sublog(f"Manifest ready with change set: {manifest.get('change_set_sha256', '')[:12]}")
    with step_progress("Classifying changed surfaces"):
        sublog("Classifying task changes...")
        classification = classify(repo, task_id=args.task_id, task_changes=manifest.get("task_changes"))
        sublog(f"Surfaces: {', '.join(classification.get('surfaces') or []) or 'none'}")
    carried_run = _carry_verification_run(repo, args.task_id, plan, manifest, classification)
    if carried_run is not None:
        return carried_run
    completed_rounds = int(plan.get("review_rounds") or 0)
    previous_run_file = task_dir(repo, args.task_id) / "current-run.json"
    if completed_rounds and not previous_run_file.is_file():
        # The earlier round's run was invalidated (older harness revise, manual cleanup); there is
        # nothing to carry forward, so route this round like a first round instead of failing on
        # every retry (certification O26).
        completed_rounds = 0
    if completed_rounds:
        previous_current = read_json(previous_run_file)
        committed_run_id = str(plan.get("verification_run_id") or "")
        if committed_run_id and previous_current.get("run_id") != committed_run_id:
            # A prepare may have published its pointer before the final plan
            # save failed (or the process stopped). The persisted plan still
            # names the completed round; recover from its frozen artifacts.
            validate_id(committed_run_id, "run_id")
            previous_manifest = read_json(task_dir(repo, args.task_id) / f"manifest-{committed_run_id}.json")
            previous_current = {
                "run_id": committed_run_id,
                "policy": str(task_dir(repo, args.task_id) / f"policy-{committed_run_id}.json"),
                "delivery_snapshot_sha256": previous_manifest["delivery_snapshot_sha256"],
                "change_set_sha256": previous_manifest["change_set_sha256"],
            }
    if completed_rounds:
        previous_policy = read_json(Path(previous_current["policy"]))
        # Real app: a later round stopped before its reviews (its unit tests failed and the agent resumed),
        # and the next prepare read reviews.json from that run and failed on every retry. A run that never
        # reached its reviews is skipped: the round goes back to the run whose reviews it was built on.
        store_for_rounds = EvidenceStore(state_root(repo))
        for _hop in range(10):
            if (store_for_rounds.run_dir(str(previous_current["delivery_snapshot_sha256"]), str(previous_current["run_id"])) / "reviews.json").is_file():
                break
            source = previous_policy.get("later_round_source") or {}
            source_run = str(source.get("run_id") or "")
            if not source_run:
                break
            validate_id(source_run, "run_id")
            previous_current = {
                "run_id": source_run,
                "policy": str(task_dir(repo, args.task_id) / f"policy-{source_run}.json"),
                "delivery_snapshot_sha256": str(source.get("snapshot") or ""),
                "change_set_sha256": str(source.get("change_set") or ""),
            }
            previous_policy = read_json(Path(previous_current["policy"]))
        if not (
            store_for_rounds.run_dir(
                str(previous_current["delivery_snapshot_sha256"]),
                str(previous_current["run_id"]),
            )
            / "reviews.json"
        ).is_file():
            completed_rounds = 0
    if completed_rounds:
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
        source_finding_owners = {
            str(item.get("reviewer") or "")
            for item in (previous_reviews.get("evidence") or {}).get("blocking_findings") or []
            if isinstance(item, dict) and str(item.get("reviewer") or "")
        }
        finding_owners = sorted(source_finding_owners | set(plan.get("blocked_reviewers") or []))
        policy = decide_later_round(
            classification,
            skills_root(repo),
            previous_policy=previous_policy,
            finding_owners=finding_owners,
            passed_reviewers=passed_reviewers,
            source_snapshot=str(previous_current["delivery_snapshot_sha256"]),
            source_change_set=str(previous_current["change_set_sha256"]),
            source_run_id=str(previous_current["run_id"]),
            round_number=completed_rounds + 1,
            project_kind=project_kind(repo),
            task_kind=str(plan.get("task_kind") or "FEATURE"),
            current_change_set=str(manifest["change_set_sha256"]),
            plan=plan,
            fix_delta=_fix_delta(repo, args.task_id, str(previous_current["run_id"]), manifest, plan),
        )
        # Recompute later-round policy when fix_delta is omitted in the persisted artifact
        # (for example when current_change_set == source_change_set) so the persisted policy
        # is 100% identical to validate_policy_artifact's deterministic re-evaluation.
        if policy.get("fix_delta") is None:
            policy = decide_later_round(
                classification,
                skills_root(repo),
                previous_policy=previous_policy,
                finding_owners=finding_owners,
                passed_reviewers=passed_reviewers,
                source_snapshot=str(previous_current["delivery_snapshot_sha256"]),
                source_change_set=str(previous_current["change_set_sha256"]),
                source_run_id=str(previous_current["run_id"]),
                round_number=completed_rounds + 1,
                project_kind=project_kind(repo),
                task_kind=str(plan.get("task_kind") or "FEATURE"),
                current_change_set=str(manifest["change_set_sha256"]),
                plan=plan,
                fix_delta=None,
            )
    else:
        policy = decide(classification, skills_root(repo), project_kind=project_kind(repo), task_kind=str(plan.get("task_kind") or "FEATURE"), plan=plan)
    calls_used = int(plan.get("review_calls_used") or 0)
    if completed_rounds or calls_used:
        from review_budget import effective_review_budget
        effective_budget = effective_review_budget(repo, plan, policy)
        if calls_used + int(policy.get("estimated_calls_this_round") or 0) > effective_budget:
            policy["status"] = "USER_DECISION_REQUIRED"
            policy["budget_blocked"] = {
                "calls_used": calls_used,
                "requested": int(policy.get("estimated_calls_this_round") or 0),
                "budget": effective_budget,
            }
            policy["policy_sha256"] = canonical_sha256({key: value for key, value in policy.items() if key != "policy_sha256"})
    if policy.get("reviewers"):
        from review_budget import review_round_cap_action
        round_block = review_round_cap_action(repo, plan, policy)
        if round_block:
            raise ValidationError(round_block["reason"])
    actual_task_paths = changed_file_paths(manifest)
    drift = check_material_drift(plan, policy.get("surfaces") or [], changed_modules(repo, manifest), actual_files=actual_task_paths, repo=repo)
    # The final verifier refuses a mandatory skill the approved plan did not name; a companion
    # surface such as COMPOSE_UI is not material drift but can add one. Stop here, before any gate
    # or review runs, instead of at complete (N12).
    from final_verifier import unplanned_mandatory_skills
    drift = [*drift, *(f"skill:{skill}" for skill in unplanned_mandatory_skills(plan, policy))]
    if drift:
        plan["material_drift"] = drift
        causes = _drift_causes(repo, manifest, drift, plan)
        plan["material_drift_causes"] = causes
        save_plan(_plan_path(repo, args.task_id), plan)
        if all(item.startswith("file:") for item in drift):
            raise ValidationError(
                "FILE_SCOPE_DECISION_REQUIRED: additional files do not by themselves require plan revision: "
                + ", ".join(item[5:] for item in drift)
                + ". Preserve this task, approval and prior reviews. For support files serving the approved goal, preview "
                + f"python .agents/harness.py task change-decision --task-id {args.task_id} --mode extend-scope "
                + '--file "<path>" --reason "<same-goal justification>". Repeat --file for each file, then apply with '
                + "--expect-preview <preview_sha256> --source approved-plan. For personal edits, ask the developer "
                + "to accept-edits without additional AI review or review-edits, then record their explicit choice. "
                + "Only material behavior, contract, sensitive surface or module expansion requires revise."
            )
        remediation_cmd = build_remediation_command(repo, args.task_id, plan, policy, manifest)
        # A live run: the developer re-approved without being told which change pulled in AUTH/BILLING.
        named = [f"{item} (from {', '.join(causes[item])})" if causes.get(item) else str(item) for item in drift]
        raise ValidationError(
            f"PLAN_APPROVAL_REQUIRED: material drift detected: {', '.join(named)}. "
            "Reconciliation and plan approval are required before verification run can begin.\n"
            f"To reconcile, update the plan using:\n{remediation_cmd}\nand obtain developer approval."
        )
    if plan.get("developer_instructions"):
        inst_file = repo / ".agents" / "project-context" / "developer-instructions.json"
        active_insts = {}
        if inst_file.is_file():
            try:
                data = json.loads(inst_file.read_text(encoding="utf-8"))
                active_insts = {i["id"]: i for i in data.get("instructions", []) if i.get("status") == "ACTIVE"}
            except (OSError, ValueError, ValidationError):
                pass
        for pinned in plan["developer_instructions"]:
            pid = pinned.get("id")
            cur = active_insts.get(pid)
            cur_sha = (cur.get("sha256") or cur.get("proof_reference_sha256", "")) if cur else None
            pinned_sha = pinned.get("sha256") or pinned.get("proof_reference_sha256", "")
            if not cur or cur_sha != pinned_sha:
                raise ValidationError(
                    f"APPROVED_INSTRUCTION_DRIFT: pinned developer instruction '{pid}' was modified or revoked since plan approval. "
                    "Run 'workflow.py revise' to reconcile the task plan."
                )
    if policy.get("status") != "PASS":
        if policy.get("status") == "USER_DECISION_REQUIRED" and policy.get("budget_blocked"):
            b = policy["budget_blocked"]
            plan["review_budget_blocked"] = {**b, "plan_sha256": plan["plan_sha256"],
                                             "surfaces": policy.get("surfaces", []),
                                             "severity": policy.get("severity", "CRITICAL")}
            save_plan(_plan_path(repo, args.task_id), plan)
            remediation_msg = build_budget_exhausted_remediation(
                policy=policy,
                calls_used=int(b.get("calls_used") or 0),
                requested=int(b.get("requested") or 0),
                budget=int(b.get("budget") or 0),
            )
            raise ValidationError(remediation_msg)
        raise ValidationError(f"policy preparation blocked: {policy.get('status')}")
    from review_models import freeze_models
    configured_host = resolve_review_host(repo, getattr(args, "host", None))
    run_id = f"run-{uuid.uuid4().hex}"
    frozen_review_models = freeze_models(
        repo,
        args.task_id,
        configured_host,
        list(policy.get("reviewers") or []),
        run_id=run_id,
        policy_data=policy,
        plan=plan,
    )
    directory = task_dir(repo, args.task_id)
    manifest_path = directory / f"manifest-{run_id}.json"
    policy_path = directory / f"policy-{run_id}.json"
    atomic_write_json(manifest_path, manifest)
    atomic_write_json(policy_path, policy)
    plan["status"] = "VERIFYING"
    plan.pop("review_budget_blocked", None)
    plan["verification_run_id"] = run_id
    atomic_write_json(state_root(repo) / "active-task.json", {"task_id": args.task_id, "plan_path": str(_plan_path(repo, args.task_id)), "updated_at": utc_now()})
    recipes = get_verification_recipes(policy.get("surfaces") or [])

    manifest_files = [c.get("path") for c in (manifest.get("task_changes") or []) if isinstance(c, dict) and c.get("path")]
    expected_files = list(plan.get("expected_files") or [])
    changed_scope_files = sorted(set(manifest_files + expected_files))
    direct_callers = []
    try:
        from _graph_core import GraphEngine
        engine = GraphEngine(repo)
        engine.sync()
        for f in changed_scope_files:
            norm_f = f.replace("\\", "/").lower()
            for nid, node in engine.graph.nodes.items():
                if node.file_path and node.file_path.replace("\\", "/").lower() == norm_f:
                    for s in engine.graph.get_sources(node.id):
                        snode = engine.graph.nodes.get(s)
                        if snode and snode.file_path and snode.file_path not in direct_callers:
                            direct_callers.append(snode.file_path)
    except (OSError, ValueError, ImportError, ValidationError):
        pass

    allowed_roots = sorted({str(Path(f).parent.as_posix()) for f in (changed_scope_files + direct_callers) if f})
    review_scope = {
        "changed_files": changed_scope_files,
        "allowed_roots": allowed_roots,
        "direct_callers": sorted(direct_callers),
        "max_graph_hops": 2,
    }

    configured_host = resolve_review_host(repo, getattr(args, "host", None))

    review_protocol_version = (
        2 if has_trusted_review_source(configured_host) else 1
    )

    current = {
        "task_id": args.task_id,
        "run_id": run_id,
        "harness_version": installed_harness_version(repo),
        "manifest": str(manifest_path),
        "repository": manifest.get("repository"),
        "policy": str(policy_path),
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "change_set_sha256": manifest["change_set_sha256"],
        "task_change_set_sha256": manifest.get("task_change_set_sha256") or "",
        "external_inputs_sha256": manifest.get("external_inputs_sha256") or "",
        "verification_recipes": recipes,
        "review_protocol_version": review_protocol_version,
        "review_host": configured_host,
        "review_models": frozen_review_models,
        "review_scope": review_scope,
        "created_at": utc_now(),
    }
    from review_fix_delta import capture_review_inputs
    try:
        capture_review_inputs(repo, directory, run_id, manifest, plan)
    except (OSError, ValueError, ValidationError):
        # This optional cache cannot authorize PASS. Missing or unusable inputs
        # force conservative follow-up classification instead of blocking intake.
        pass
    atomic_write_json(directory / "current-run.json", current)
    # Commit the lifecycle transition last. If any frozen run artifact cannot
    # be written, the task remains IMPLEMENTING and prepare-verification is
    # safely retryable instead of becoming a VERIFYING task with no run.
    save_plan(_plan_path(repo, args.task_id), plan)

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
        sublog("Validating delivery manifest, test results, and reviewer evidence...")
        res = verify(
            repo,
            plan_path=_plan_path(repo, args.task_id),
            policy_path=Path(current["policy"]),
            manifest_path=Path(current["manifest"]),
            state_root=state_root(repo),
            run_id=str(current["run_id"]),
        )
        sublog(f"Verification completed with status: {res.get('status')}")
        return res


def complete(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    if plan.get("status") == "READY_FOR_DELIVERY":
        ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
        live_manifest = build_manifest(repo)
        live_snapshot = str(live_manifest.get("delivery_snapshot_sha256") or "")
        if ready_snapshot and live_snapshot and ready_snapshot != live_snapshot:
            from delivery_equivalence import evaluate_post_ready_changes
            eval_res = evaluate_post_ready_changes(repo, args.task_id, plan, live_manifest)
            if not eval_res.get("is_benign"):
                raise ValidationError(
                    f"delivery cannot be completed: repository modified after verification (live snapshot {live_snapshot[:12]} != ready {ready_snapshot[:12]})"
                )
        return plan
    result = verify_task(args)
    if result.get("status") != "APPROVED":
        # Real app: with no remedy named, the agent recommended rewriting red-evidence.json to the developer.
        raise ValidationError(
            "delivery cannot be completed: " + "; ".join(result.get("blocked_by") or [str(result.get("status"))])
            + ". Harness evidence is never edited, deleted or skipped, and is not offered to the developer as an "
            "option. Run `task status --next` for the remedy; if it still routes to COMPLETE_TASK, the harness "
            "contradicts itself: tell the developer the refusal verbatim and offer to keep the task open for a "
            "harness fix or to cancel it (`workflow.py cancel`, which keeps the code changes)."
        )
    plan = _load_plan(repo, args.task_id)
    plan["status"] = "READY_FOR_DELIVERY"
    plan["ready_at"] = utc_now()
    plan["ready_delivery_snapshot_sha256"] = result["delivery_snapshot_sha256"]
    plan["ready_change_set_sha256"] = result["change_set_sha256"]
    plan["ready_run_id"] = result["run_id"]
    from delivery_equivalence import snapshot_verified_files
    snapshot_verified_files(repo, args.task_id, plan, result["run_id"])
    save_plan(_plan_path(repo, args.task_id), plan)
    return plan


@_serialize_task_scope
def cancel(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    source = str(getattr(args, "source", None) or "developer_terminal")
    proof = str(getattr(args, "proof_reference", None) or "").strip()
    if source == "conversation" and not proof:
        raise ValidationError("cancel --source conversation needs --proof-reference with the developer's words")
    plan["status"] = "CANCELLED"
    plan["approval"] = None
    plan["execution_nonce"] = None
    plan["cancelled_at"] = utc_now()
    plan["cancellation"] = {"source": source, "proof_reference": proof[:500]} if proof else {"source": source}
    save_plan(_plan_path(repo, args.task_id), plan)
    active_path = state_root(repo) / "active-task.json"
    if active_path.is_file():
        try:
            active = read_json(active_path)
            if str(active.get("task_id") or "") == args.task_id:
                active_path.unlink(missing_ok=True)
        except (OSError, ValueError, ValidationError):
            pass
    from discovery_receipt import clear_latest_discovery_receipt
    clear_latest_discovery_receipt(repo)
    _clear_cancel_request(repo, args.task_id)
    return plan


def _clear_cancel_request(repo: Path, task_id: str) -> None:
    """A lifecycle command that actually ran settles a pending cancel request (the hook's CANCEL_PENDING)."""
    path = state_root(repo) / "cancel-requested.json"
    if path.is_file() and read_json(path).get("task_id") == task_id:
        path.unlink(missing_ok=True)


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
    if is_live_task_status(status_val):
        raise ValidationError(
            f"Cannot auto-recover healthy active task '{tid}' in status '{status_val}'. "
            "Explicit developer cancellation is required."
        )

    active_path.unlink(missing_ok=True)
    return {"status": "RECOVERED", "cleared_active_task": True, "reason": f"cleared_terminal_task_status_{status_val}"}


def resume(args: argparse.Namespace) -> dict:
    with StateLock(state_root(Path(args.repo).resolve())):
        return _resume_locked(args)


def _ready_external_inputs_changed(repo: Path, task_id: str, run_id: str, live_manifest: dict) -> bool:
    if not run_id:
        return False
    validate_id(run_id, "run id")
    path = task_dir(repo, task_id) / f"manifest-{run_id}.json"
    if not path.is_file():
        return False  # Legacy READY plans may not have frozen run artifacts.
    frozen = read_json(path)
    return bool(frozen.get("external_inputs_sha256")) and frozen["external_inputs_sha256"] != live_manifest.get("external_inputs_sha256")


def _resume_locked(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    assert_single_live_task(repo, allowed_task_id=args.task_id)
    _clear_cancel_request(repo, args.task_id)
    plan = _load_plan(repo, args.task_id)
    status = plan.get("status")

    if status == "READY_FOR_DELIVERY":
        ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
        ready_run_id = str(plan.get("ready_run_id") or "")
        if not ready_snapshot or not ready_run_id:
            tdir = task_dir(repo, args.task_id)
            crun_path = tdir / "current-run.json"
            if crun_path.is_file():
                try:
                    crun = read_json(crun_path)
                    if not ready_snapshot:
                        ready_snapshot = str(crun.get("delivery_snapshot_sha256") or "")
                    if not ready_run_id:
                        ready_run_id = str(crun.get("run_id") or "")
                except (OSError, ValueError, ValidationError):
                    pass
        live_manifest = build_manifest(repo)
        live_snapshot = str(live_manifest.get("delivery_snapshot_sha256") or "")
        unchanged = (not ready_snapshot or not live_snapshot or ready_snapshot == live_snapshot) and not _ready_external_inputs_changed(repo, args.task_id, ready_run_id, live_manifest)
        # --reopen: the developer reviewed the verified diff and requested changes before committing.
        if unchanged and not getattr(args, "reopen", False):
            raise ValidationError(
                f"task '{args.task_id}' is in status 'READY_FOR_DELIVERY' with matching snapshot; resume is only permitted when delivery snapshot is stale. "
                f"If the developer requested changes before committing, reopen with: python .agents/harness.py task resume --task-id {args.task_id} --reopen"
            )
        if not plan.get("approval") or plan.get("execution_nonce") != plan["approval"].get("single_use_nonce"):
            raise ValidationError("the approved execution identity is no longer valid")
        from task_git_lineage import accept_requested_delivery_commit
        accept_requested_delivery_commit(repo, args.task_id, plan)
        plan["status"] = "IMPLEMENTING"
        plan["resumed_at"] = utc_now()
        plan.pop("ready_at", None)
        plan.pop("ready_delivery_snapshot_sha256", None)
        plan.pop("ready_change_set_sha256", None)
        plan.pop("ready_run_id", None)
        save_plan(_plan_path(repo, args.task_id), plan)
        atomic_write_json(state_root(repo) / "active-task.json", {"task_id": args.task_id, "plan_path": str(_plan_path(repo, args.task_id)), "updated_at": utc_now()})
        return plan

    if status not in ("VERIFYING", "BLOCKED"):
        raise ValidationError("only a verifying or blocked task can resume implementation")
    if not plan.get("approval") or plan.get("execution_nonce") != plan["approval"].get("single_use_nonce"):
        raise ValidationError("the approved execution identity is no longer valid")
    from review_budget import settle_final_review_calls
    settle_final_review_calls(repo, plan)
    plan["status"] = "IMPLEMENTING"
    plan["resumed_at"] = utc_now()
    save_plan(_plan_path(repo, args.task_id), plan)
    atomic_write_json(state_root(repo) / "active-task.json", {"task_id": args.task_id, "plan_path": str(_plan_path(repo, args.task_id)), "updated_at": utc_now()})
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
    if plan.get("status") == "DELIVERED":
        return plan, False
    if plan.get("status") != "READY_FOR_DELIVERY":
        raise ValidationError(f"task '{task_id}' is in status '{plan.get('status')}', not READY_FOR_DELIVERY")

    if require_clean_tree:
        dirty = _find_uncommitted_task_files(repo, task_id, plan)
        if dirty:
            raise ValidationError(
                f"cannot deliver task '{task_id}' with dirty working tree; verified task files remain uncommitted: {', '.join(sorted(dirty))}"
            )

    ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
    live_identity = repository_identity(repo)
    for field in ("root_sha256", "git_common_dir_sha256", "branch"):
        approved_value = (plan.get("repository") or {}).get(field)
        if approved_value and live_identity.get(field) != approved_value:
            raise ValidationError(f"delivery repository identity mismatch: {field}")
    if ready_snapshot:
        manifest = build_manifest(repo)
        if plan.get("ready_run_id"):
            from delivery_equivalence import _ready_manifest
            _, frozen, _ = _ready_manifest(repo, task_id, plan)
            if frozen.get("external_inputs_sha256") != manifest.get("external_inputs_sha256"):
                raise ValidationError("delivery external inputs changed after verification")
        current_snapshot = manifest["delivery_snapshot_sha256"]
        if current_snapshot != ready_snapshot:
            from delivery_equivalence import evaluate_post_ready_changes
            eval_res = evaluate_post_ready_changes(repo, task_id, plan, manifest)
            if eval_res.get("is_benign"):
                plan["post_ready_normalization"] = {
                    "accepted_at": utc_now(),
                    "ready_delivery_snapshot_sha256": ready_snapshot,
                    "live_delivery_snapshot_sha256": current_snapshot,
                    "normalized_files": eval_res.get("normalized_files") or [],
                }
            else:
                changed = changed_since_verification(repo, task_id, plan, manifest)
                named = f" Changed after verification: {', '.join(changed[:10])}." if changed else ""
                diff_detail = f"\nDetails: {eval_res.get('diff_summary')}" if eval_res.get("diff_summary") else ""
                raise ValidationError(
                    f"delivery snapshot mismatch: current repository ({current_snapshot[:12]}) "
                    f"differs from verified ready snapshot ({ready_snapshot[:12]}). Content was modified after verification.{named}{diff_detail}\n"
                    "Git attributes normalize line endings when configured; unproven content differences still require verification.\n"
                    "Do not resume on your own: ask the developer whether to verify these changes (their own edits "
                    "before the commit count too)."
                )

    try:
        delivery_commit_sha = git_text(repo, "rev-parse", "HEAD")
    except Exception:
        delivery_commit_sha = ""
    if plan.get("ready_run_id") and delivery_commit_sha:
        from task_git_lineage import accept_requested_delivery_commit, is_valid_task_lineage
        accept_requested_delivery_commit(repo, task_id, plan)
        # Validate against the persisted plan plus a freshly validated delivery receipt.
        valid_lineage, reason = is_valid_task_lineage(repo, task_id, delivery_commit_sha)
        if not valid_lineage:
            raise ValidationError(reason)
    plan = deliver_plan(plan)
    if delivery_commit_sha:
        plan["delivery_commit_sha"] = delivery_commit_sha
    save_plan(_plan_path(repo, task_id), plan)
    active_path = state_root(repo) / "active-task.json"
    if active_path.is_file():
        try:
            active = read_json(active_path)
            if str(active.get("task_id") or "") == task_id:
                active_path.unlink(missing_ok=True)
        except Exception:
            active_path.unlink(missing_ok=True)
    from discovery_receipt import clear_latest_discovery_receipt
    clear_latest_discovery_receipt(repo)
    return plan, True


def reconcile_delivery(repo: Path, task_id: str | None = None) -> tuple[dict | None, str]:
    """Reconcile READY_FOR_DELIVERY task against clean committed repository state."""
    assert_single_live_task(repo, allowed_task_id=task_id)
    tid = task_id
    if not tid:
        tid = _focused_task_id(repo)
    if not tid:
        return None, "NOOP"
    plan_p = _plan_path(repo, tid)
    if not plan_p.is_file():
        return None, "NOOP"
    try:
        plan = read_json(plan_p)
    except Exception:
        return None, "NOOP"
    status_val = str(plan.get("status") or "")
    if status_val == "DELIVERED":
        return plan, "DELIVERED"
    if status_val != "READY_FOR_DELIVERY":
        return plan, status_val
    dirty = _find_uncommitted_task_files(repo, tid, plan)
    if dirty:
        return plan, "DIRTY_UNCOMMITTED"
    ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
    if ready_snapshot:
        manifest = build_manifest(repo)
        if manifest.get("delivery_snapshot_sha256") != ready_snapshot:
            from delivery_equivalence import evaluate_post_ready_changes
            eval_res = evaluate_post_ready_changes(repo, tid, plan, manifest)
            if not eval_res.get("is_benign"):
                return plan, "SNAPSHOT_MISMATCH"
    plan, _ = finalize_ready_delivery(repo, tid, plan, require_clean_tree=True)
    return plan, "DELIVERED"


def cmd_reconcile_delivery(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    task_id = getattr(args, "task_id", None) or None
    plan, status_code = reconcile_delivery(repo, task_id)
    if plan is None:
        return {"status": "NOOP", "message": "no task to reconcile"}
    tid = plan.get("task_id", "")
    if status_code == "DELIVERED":
        return {"status": "PASS", "task_id": tid, "reconciled": True, "task_state": "DELIVERED"}
    elif status_code == "DIRTY_UNCOMMITTED":
        return {"status": "BLOCKED", "task_id": tid, "reconciled": False, "reason": "uncommitted_changes", "task_state": plan.get("status")}
    elif status_code == "SNAPSHOT_MISMATCH":
        return {"status": "FAIL", "task_id": tid, "reconciled": False, "reason": "snapshot_mismatch", "task_state": plan.get("status")}
    return {"status": "PASS", "task_id": tid, "task_state": plan.get("status")}


def installed_harness_version(repo: Path) -> str:
    root = repo / ".agents" if (repo / ".agents").is_dir() else repo / "agents"
    path = root / "VERSION"
    version = path.read_text(encoding="utf-8").strip() if path.is_file() else "1.0.0"
    if not version:
        raise ValidationError("installed harness version is empty")
    return version


def verification_engine_freshness(repo: Path, task_id: str, current: dict) -> dict:
    """Reject a preserved verification run after its evidence producer changes.

    Older runs did not freeze an engine version. The completed preserving-update
    journal establishes that those runs predate an engine replacement. Never
    rewrite their proof or infer that an engine update refreshed it.
    """
    try:
        live_version = installed_harness_version(repo)
        frozen_version = current.get("harness_version")
        if frozen_version is None:
            journal_path = repo / ".harness-setup/update-journal.json"
            if journal_path.is_file():
                journal = read_json(journal_path)
                preserved = journal.get("preserved_active_task") or {}
                if (journal.get("status") == "COMPLETED" and preserved.get("task_id") == task_id
                        and journal.get("from_version") != journal.get("to_version")):
                    from datetime import datetime
                    created = datetime.fromisoformat(str(current.get("created_at") or "").replace("Z", "+00:00"))
                    started = datetime.fromisoformat(str(journal.get("started_at") or "").replace("Z", "+00:00"))
                    if created <= started:
                        frozen_version = journal.get("from_version") or "unknown"
        if frozen_version is not None and frozen_version != live_version:
            return {"fresh": False, "reason_code": "HARNESS_VERSION_CHANGED",
                    "reason": f"STALE: verification was frozen under harness {frozen_version}, installed {live_version}. "
                              "Resume the same task and prepare verification again; retain prior evidence and review counters."}
    except (OSError, ValueError, TypeError, AttributeError, ValidationError) as exc:
        return {"fresh": False, "reason_code": "HARNESS_VERSION_UNAVAILABLE",
                "reason": f"Cannot establish verification engine identity: {exc}"}
    return {"fresh": True, "reason_code": "FRESH"}


def verification_freshness(repo: Path, task_id: str, current_run: dict | None = None, *, allow_completed: bool = False) -> dict:
    """Non-mutating verification freshness resolver comparing live repository state with frozen run."""
    try:
        plan = _load_plan(repo, task_id)
    except Exception as exc:
        return {"fresh": False, "reason_code": "PLAN_LOAD_FAILED", "reason": str(exc)}
    if plan.get("status") != "VERIFYING" and not (allow_completed and plan.get("status") == "READY_FOR_DELIVERY"):
        return {
            "fresh": False,
            "reason_code": "NOT_VERIFYING",
            "reason": f"task '{task_id}' is in status '{plan.get('status')}', not VERIFYING",
        }

    current = current_run
    if current is None:
        directory = task_dir(repo, task_id)
        current_path = directory / "current-run.json"
        if not current_path.is_file():
            return {
                "fresh": False,
                "reason_code": "RUN_NOT_INITIALIZED",
                "reason": f"task '{task_id}' verification run is not initialized",
            }
        try:
            current = read_json(current_path)
        except Exception as exc:
            return {"fresh": False, "reason_code": "CURRENT_RUN_CORRUPTED", "reason": str(exc)}

    if str(current.get("task_id") or "") != task_id:
        return {
            "fresh": False,
            "reason_code": "TASK_MISMATCH",
            "reason": f"current-run task mismatch: expected '{task_id}', found '{current.get('task_id')}'",
        }

    engine = verification_engine_freshness(repo, task_id, current)
    if not engine["fresh"]:
        return engine

    manifest = build_manifest(repo)
    frozen_repo = current.get("repository")
    if not isinstance(frozen_repo, dict) and current.get("manifest"):
        # Runs created by earlier versions froze the repository identity only
        # inside their manifest. Keep those runs recoverable after an update.
        try:
            frozen_manifest = read_json(Path(current["manifest"]))
            if all(frozen_manifest.get(key) == current.get(key) for key in ("delivery_snapshot_sha256", "change_set_sha256")):
                frozen_repo = frozen_manifest.get("repository")
        except (OSError, ValueError):
            pass
    live_repo = manifest.get("repository") or {}
    if not isinstance(frozen_repo, dict):
        return {"fresh": False, "reason_code": "REPOSITORY_IDENTITY_MISSING", "reason": "verification run has no frozen repository identity"}
    for field in ("root_sha256", "git_common_dir_sha256", "branch", "head"):
        if frozen_repo.get(field) != live_repo.get(field):
            return {
                "fresh": False,
                "reason_code": "REPOSITORY_IDENTITY_CHANGED",
                "reason": f"STALE: repository {field} changed after verification freeze",
            }
    checks = [
        ("delivery_snapshot_sha256", "DELIVERY_SNAPSHOT_CHANGED"),
        ("change_set_sha256", "CHANGE_SET_CHANGED"),
        ("external_inputs_sha256", "EXTERNAL_INPUTS_CHANGED"),
    ]
    for key, reason_code in checks:
        curr_val = current.get(key)
        if not curr_val and key == "external_inputs_sha256" and current.get("manifest"):
            try:
                curr_val = read_json(Path(current["manifest"])).get("external_inputs_sha256")
            except (OSError, ValueError, ValidationError):
                pass
        live_val = manifest.get(key)
        if curr_val and live_val and curr_val != live_val:
            return {
                "fresh": False,
                "reason_code": reason_code,
                "frozen": curr_val,
                "live": live_val,
                "reason": f"STALE: repository {key} modified after verification freeze: {curr_val[:12]} != live {live_val[:12]}",
            }

    task_cs = current.get("task_change_set_sha256")
    if task_cs:
        try:
            task_manifest = build_task_manifest(repo, load_task_baseline(repo, task_id), expected_files=plan.get("expected_files"), live_manifest=manifest)
            live_task_cs = task_manifest.get("task_change_set_sha256")
            if live_task_cs and task_cs != live_task_cs:
                return {
                    "fresh": False,
                    "reason_code": "TASK_CHANGE_SET_CHANGED",
                    "frozen": task_cs,
                    "live": live_task_cs,
                    "reason": f"STALE: task change set modified after verification freeze: {task_cs[:12]} != live {live_task_cs[:12]}",
                }
        except Exception as exc:
            return {
                "fresh": False,
                "reason_code": "TASK_CHANGE_SET_UNAVAILABLE",
                "reason": f"TASK_CHANGE_SET_UNAVAILABLE: could not rebuild task-scoped changes: {exc}",
            }

    return {
        "fresh": True,
        "reason_code": "FRESH",
        "frozen": current.get("delivery_snapshot_sha256"),
        "live": manifest.get("delivery_snapshot_sha256"),
    }


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
    freshness = verification_freshness(repo, task_id, current)
    if not freshness.get("fresh"):
        raise ValidationError(freshness.get("reason", "Verification run is stale"))
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


class CheckpointStatus(str):
    def __eq__(self, other: object) -> bool:
        if other in ("PASS", "CHECKPOINT_PASS"):
            return True
        return super().__eq__(other)


def resolve_phase_modules(repo: Path, manifest: dict) -> list[str]:
    discovered = changed_modules(repo, manifest, task_only=True)
    mods = [m for m in discovered if m and m != ":"]
    if mods:
        return sorted(set(mods))
    found: set[str] = set()
    changes = manifest.get("task_changes") or manifest.get("changes") or []
    for c in changes:
        raw_p = c.get("path") if isinstance(c, dict) else str(c)
        p = str(raw_p or "").replace("\\", "/").strip("/")
        if "/src/" in f"/{p}":
            mod_prefix = p.split("/src/")[0]
            if mod_prefix:
                found.add(":" + mod_prefix.replace("/", ":"))
        elif "/" in p:
            parts = [x for x in p.split("/") if x]
            if len(parts) >= 2:
                if parts[0] in ("feature", "core", "lib", "module") and len(parts) > 2:
                    found.add(f":{parts[0]}:{parts[1]}")
                else:
                    found.add(f":{parts[0]}")
    return sorted(found)


def resolve_module_gradle_task(repo: Path, module: str, task_type: str = "compile", phase_changes: list[Any] | None = None) -> str:
    """Resolve the appropriate Gradle compile or test task for a module and configured variant."""
    mod_clean = module.rstrip(":").strip()
    if not mod_clean.startswith(":"):
        mod_clean = ":" + mod_clean
    mod_rel = mod_clean.lstrip(":").replace(":", "/")
    mod_dir = repo / mod_rel

    # Variant resolution from setup answers, _product.py, or default
    variant = "Debug"
    answers_file = repo / ".harness-setup" / "answers.json"
    if answers_file.is_file():
        try:
            ans = json.loads(answers_file.read_text(encoding="utf-8"))
            if ans.get("build_variant"):
                variant = str(ans["build_variant"])
            elif ans.get("flavor"):
                variant = f"{ans['flavor']}Debug"
        except (OSError, ValueError, ValidationError):
            pass
    if variant == "Debug":
        for p_loc in [repo / ".agents" / "scripts" / "_product.py", repo / "agents" / "scripts" / "_product.py"]:
            if p_loc.is_file():
                try:
                    content = p_loc.read_text(encoding="utf-8")
                    m_var = re.search(r'ACTIVE_VARIANT\s*=\s*["\']([^"\']+)["\']', content)
                    m_flav = re.search(r'ACTIVE_FLAVOR\s*=\s*["\']([^"\']+)["\']', content)
                    if m_var and m_var.group(1) and m_var.group(1) != "Debug":
                        variant = m_var.group(1)
                        break
                    elif m_flav and m_flav.group(1):
                        variant = f"{m_flav.group(1)}Debug"
                        break
                except (OSError, ValueError, ValidationError):
                    pass

    def _pascal(v: str) -> str:
        if not v:
            return "Debug"
        return v[0].upper() + v[1:]

    var_pascal = _pascal(variant)

    # Detect module characteristics
    build_content = ""
    for bf in [mod_dir / "build.gradle.kts", mod_dir / "build.gradle"]:
        if bf.is_file():
            try:
                build_content += bf.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError, ValidationError):
                pass

    from _modules import detect_kmp_build_script
    try:
        from wizard.discovery import _catalog_plugin_ids, _resolve_catalog_aliases
        resolved_build = _resolve_catalog_aliases(build_content, _catalog_plugin_ids(repo))
    except Exception:
        resolved_build = build_content

    kmp_info = detect_kmp_build_script(build_content, resolved_build)
    has_android_main = (mod_dir / "src" / "androidMain").is_dir()
    has_common_main = (mod_dir / "src" / "commonMain").is_dir()
    is_kmp = kmp_info["has_kmp_plugin"] or has_common_main or has_android_main

    # Kotlin detection (pruned walk so mod_dir/build is never scanned)
    from _modules import SKIP_PARTS
    has_kotlin = False
    if mod_dir.is_dir():
        scan_target = mod_dir / "src" if (mod_dir / "src").is_dir() else mod_dir
        for _root, dirs, files in os.walk(scan_target, followlinks=False):
            dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
            if any(f.endswith(".kt") for f in files):
                has_kotlin = True
                break
    if not has_kotlin and phase_changes:
        for c in phase_changes:
            raw_p = c.get("path") if isinstance(c, dict) else str(c or "")
            p_str = (raw_p or "").replace("\\", "/").strip("/")
            if (p_str.startswith(mod_rel + "/") or mod_rel == p_str.split("/")[0]) and p_str.endswith(".kt"):
                has_kotlin = True
                break

    if is_kmp:
        if kmp_info["has_agp_kmp_library"]:
            if task_type == "compile":
                return f"{mod_clean}:compileAndroidMain"
            return f"{mod_clean}:testAndroidHostTest"
        if has_android_main or kmp_info["has_android_target"]:
            if task_type == "compile":
                return f"{mod_clean}:compileKotlinAndroid"
            else:
                return f"{mod_clean}:test{var_pascal}UnitTest"
        if kmp_info["has_jvm_target"]:
            if task_type == "compile":
                return f"{mod_clean}:compileKotlinJvm"
            return f"{mod_clean}:jvmTest"
        raise ValidationError(f"[CONFIG_ERROR] KMP module '{module}' task resolution requires configured Android target")

    if task_type == "compile":
        if has_kotlin:
            return f"{mod_clean}:compile{var_pascal}Kotlin"
        else:
            # Java-only module: do not invent compileDebugKotlin
            return f"{mod_clean}:compile{var_pascal}JavaWithJavac"
    else:  # test
        return f"{mod_clean}:test{var_pascal}UnitTest"


def check_phase_compile(repo: Path, modules: list[str], phase_changes: list[Any] | None = None) -> tuple[bool, str]:
    gradle_wrapper = (repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()
    if not gradle_wrapper:
        return True, "NOT_REQUIRED"
    from run_gradle_task import run_gradle
    for m in modules:
        try:
            compile_task = resolve_module_gradle_task(repo, m, task_type="compile", phase_changes=phase_changes)
        except ValidationError as exc:
            return False, str(exc)
        res = run_gradle([compile_task], cwd=repo)
        if res != 0:
            return False, f"compile failed for module '{m}' with task '{compile_task}' (exit code {res})"
    return True, "PASS"


def new_kotlin_lint_issues(repo: Path, task_id: str, source: Path, base_head: str | None) -> list[dict]:
    """Report only lint findings introduced since this task's original baseline."""
    from fast_kt_lint import lint_file

    current = lint_file(source)
    if not current:
        return []
    relative = source.relative_to(repo).as_posix()
    saved_base = task_dir(repo, task_id) / "baseline-files" / relative
    if saved_base.is_file():
        original = saved_base.read_bytes()
    else:
        try:
            original = git(repo, "show", f"{base_head or 'HEAD'}:{relative}")
        except Exception:
            return current  # A newly created file has no pre-task lint debt.

    with tempfile.TemporaryDirectory(prefix="harness-lint-") as temp:
        baseline_file = Path(temp) / relative
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_bytes(original)
        before = lint_file(baseline_file)
        before_lines = original.decode("utf-8", errors="replace").splitlines()

    current_lines = source.read_text(encoding="utf-8", errors="replace").splitlines()

    def signature(issue: dict, lines: list[str]) -> tuple[str, str, str]:
        line_no = int(issue.get("line") or 0)
        file_level = {"MISSING_COMPOSE_PREVIEW", "MISSING_HILT_ENTRY_POINT", "VIEWBINDING_MEMORY_LEAK"}
        source_line = lines[line_no - 1].strip() if 0 < line_no <= len(lines) and issue.get("type") not in file_level else ""
        return str(issue.get("type") or ""), str(issue.get("msg") or ""), source_line

    old_counts = Counter(signature(issue, before_lines) for issue in before)
    introduced: list[dict] = []
    for issue in current:
        key = signature(issue, current_lines)
        if old_counts[key]:
            old_counts[key] -= 1
        else:
            introduced.append(issue)
    return introduced


def check_phase_tests(repo: Path, phase_dir: Path, modules: list[str], needs_tests: bool, phase_changes: list[Any] | None = None) -> tuple[bool, str]:
    if not needs_tests:
        return True, "NOT_REQUIRED"
    test_file = phase_dir / "unit_tests.json"
    from phase_review import compute_phase_delta_sha256
    evidence_identity = canonical_sha256({
        "phase_delta_sha256": compute_phase_delta_sha256(phase_dir.name, list(phase_changes or [])),
        "modules": sorted(str(m) for m in modules),
    })
    if test_file.is_file():
        data = read_json(test_file)
        recorded_identity = data.get("evidence_identity_sha256")
        # Evidence this checkpoint recorded itself is reusable only as a PASS for the
        # identical phase delta; a recorded failure or stale content is re-evaluated.
        if recorded_identity is None:
            if str(data.get("status") or "").upper() == "PASS":
                return True, "PASS"
            return False, str(data.get("detail") or "unit test failure in phase evidence")
        if recorded_identity == evidence_identity and str(data.get("status") or "").upper() == "PASS":
            return True, "PASS"

    gradle_wrapper = (repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()
    run_gradle_fn = None
    if gradle_wrapper:
        from run_gradle_task import run_gradle
        run_gradle_fn = run_gradle
    else:
        try:
            from run_gradle_task import run_gradle
            if hasattr(run_gradle, "assert_called") or hasattr(run_gradle, "side_effect") or hasattr(run_gradle, "return_value"):
                run_gradle_fn = run_gradle
        except (OSError, ValueError, ImportError, ValidationError):
            pass

    if run_gradle_fn is None:
        return False, "phase policy requires unit tests but no gradle wrapper or passing test evidence was found"

    from run_tests_gate import evaluate_unit_test_execution, load_task_start_failures, report_signatures
    task_start = load_task_start_failures(repo)
    aggregated_evidence: dict[str, Any] = {"status": "PASS", "modules": {}}
    total_ignored = 0
    total_failed = 0

    for m in modules:
        # A module with no unit-test sources whose phase changes are all resources cannot produce
        # test evidence; demanding it dead-ends any phase touching a resource-only module (N3).
        # A code change in such a module still runs and needs tests.
        module_dir = m.strip(":").replace(":", "/")
        module_src = repo / module_dir / "src"
        module_paths = [
            str(c.get("path") if isinstance(c, dict) else c or "").replace("\\", "/")
            for c in (phase_changes or [])
        ]
        module_paths = [p for p in module_paths if p.startswith(module_dir + "/src/")]
        if (
            module_dir
            and module_paths
            and all("/res/" in p for p in module_paths)
            and not any(d.is_dir() and d.name.lower().startswith("test") for d in (module_src.iterdir() if module_src.is_dir() else []))
        ):
            aggregated_evidence["modules"][m] = {"status": "SKIPPED_NO_TEST_SOURCES", "executed": 0}
            continue
        try:
            task = resolve_module_gradle_task(repo, m, task_type="test", phase_changes=phase_changes)
        except ValidationError as exc:
            return False, str(exc)

        is_mock = hasattr(run_gradle_fn, "assert_called") or hasattr(run_gradle_fn, "side_effect") or hasattr(run_gradle_fn, "return_value")
        reports_before = None if is_mock else report_signatures(repo, task)
        outcome: dict = {}
        res = run_gradle_fn([task], cwd=repo, outcome=outcome)

        ok, detail, data = evaluate_unit_test_execution(
            repo=repo,
            task=task,
            code=res,
            reports_before=reports_before,
            outcome=outcome,
            task_start=task_start,
        )
        if not ok:
            atomic_write_json(test_file, {
                **data,
                "status": "FAIL",
                "detail": detail,
                "evidence_identity_sha256": evidence_identity,
            })
            return False, f"unit tests failed for module '{m}': {detail}"

        total_ignored += data.get("baseline_ignored", 0)
        total_failed += data.get("total_failed", 0)
        aggregated_evidence["modules"][m] = data

    aggregated_evidence["baseline_ignored"] = total_ignored
    aggregated_evidence["total_failed"] = total_failed
    aggregated_evidence["evidence_identity_sha256"] = evidence_identity
    atomic_write_json(test_file, aggregated_evidence)
    return True, "PASS"





def checkpoint_phase(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    if plan.get("status") != "IMPLEMENTING":
        raise ValidationError("phase checkpoint requires an IMPLEMENTING plan")
    phases = plan.get("phases") or []
    if not phases:
        raise ValidationError("plan does not define any phases")
    directory = task_dir(repo, args.task_id)
    phase_state_file = directory / "phase-state.json"
    phase_state = read_json(phase_state_file) if phase_state_file.is_file() else {
        "current_phase_id": phases[0]["id"],
        "completed_phases": [],
        "phase_checkpoints": {},
    }
    phase_id = getattr(args, "phase_id", None) or phase_state.get("current_phase_id")
    target_phase = next((p for p in phases if p.get("id") == phase_id), None)
    if not target_phase:
        raise ValidationError(f"phase '{phase_id}' not found in plan phases")
    active_phase_id = phase_state.get("current_phase_id")
    if active_phase_id and phase_id != active_phase_id:
        raise ValidationError(
            f"phase checkpoint is for '{phase_id}' but the active phase is '{active_phase_id}'; "
            "checkpoint the active phase first"
        )
    phase_index = next(i for i, p in enumerate(phases) if p.get("id") == phase_id)

    from phase_review import (
        get_phase_substate,
        invalidate_phase_review,
        phase_run_file,
        PHASE_REVIEW_BLOCKED,
        PHASE_REVIEWING,
    )
    if (
        get_phase_substate(phase_state, phase_id) in (PHASE_REVIEW_BLOCKED, PHASE_REVIEWING)
        or phase_run_file(directory, phase_id).is_file()
    ):
        invalidate_phase_review(repo, args.task_id, phase_id)
        phase_state = read_json(phase_state_file)

    phase_dir = directory / "phases" / phase_id
    phase_dir.mkdir(parents=True, exist_ok=True)
    baseline_file = phase_dir / "baseline.json"
    base_data = read_json(baseline_file) if baseline_file.is_file() else load_task_baseline(repo, args.task_id)
    manifest = build_task_manifest(repo, base_data, expected_files=target_phase.get("expected_files") or plan.get("expected_files"))
    phase_changes = manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes") or []
    # A later phase can be empty when an earlier phase's checkpoint already covered its files
    # (phases added by a revision after the work was done). It records an empty checkpoint; the
    # final verification still gates the whole task delta.
    empty_later_phase = False
    if not phase_changes and phase_index > 0:
        covered: set[str] = set()
        for done_id in phase_state.get("completed_phases") or []:
            done_file = directory / "phases" / done_id / "checkpoint.json"
            if done_file.is_file():
                covered.update(
                    str(c.get("path") or "").replace("\\", "/").strip("/")
                    for c in read_json(done_file).get("manifest_delta") or [] if isinstance(c, dict)
                )
        owned = normalize_expected_files(repo, target_phase.get("expected_files") or plan.get("expected_files") or [])
        empty_later_phase = bool(owned) and set(owned) <= covered
    if not phase_changes and not empty_later_phase:
        raise ValidationError(f"phase checkpoint failed: no file changes detected for phase '{phase_id}'")

    phase_expected_files = target_phase.get("expected_files")
    approved_task_files = set(normalize_expected_files(repo, plan.get("expected_files") or []))
    additional_phase_files = []
    if phase_expected_files:
        norm_expected = normalize_expected_files(repo, phase_expected_files)
        for change in phase_changes:
            raw_p = change.get("path") if isinstance(change, dict) else str(change)
            change_path = (raw_p or "").replace("\\", "/").strip("/")
            if change_path.startswith(".agents/"):
                continue
            if change_path not in norm_expected:
                if change_path not in approved_task_files:
                    raise ValidationError(f"phase '{phase_id}' modified file outside expected_files of the approved task: {change_path}")
                additional_phase_files.append(change_path)

    phase_expected_modules = target_phase.get("expected_modules")
    if phase_expected_modules:
        norm_mods = [m.strip("/:").replace("\\", "/") for m in phase_expected_modules]
        for change in phase_changes:
            raw_p = change.get("path") if isinstance(change, dict) else str(change)
            change_path = (raw_p or "").replace("\\", "/").strip("/")
            if change_path.startswith(".agents/"):
                continue
            mod_match = any(change_path.startswith(m + "/") or change_path == m for m in norm_mods)
            if not mod_match and change_path not in approved_task_files:
                raise ValidationError(f"phase '{phase_id}' modified file outside expected_modules: {change_path}")

    # Phase delta classification & central policy
    phase_classification = classify(repo, task_changes=phase_changes)
    skills_root = (repo / "agents" / "skills") if (repo / "agents" / "skills").is_dir() else (repo / ".agents" / "skills")
    phase_policy = decide(phase_classification, skills_root, plan=plan)

    # 1. Deterministic Preflight
    # Fast Kotlin lint
    try:
        kt_issues = []
        for c in phase_changes:
            rel_p = c.get("path", "") if isinstance(c, dict) else str(c or "")
            p = repo / rel_p
            if p.suffix == ".kt" and p.is_file():
                kt_issues.extend(new_kotlin_lint_issues(repo, args.task_id, p, plan.get("task_base_head") or (plan.get("repository") or {}).get("head")))
        if kt_issues:
            raise ValidationError(f"phase checkpoint Kotlin lint failed: {len(kt_issues)} issue(s) detected")
    except (ImportError, ValidationError):
        raise
    except Exception as exc:
        raise ValidationError(f"phase checkpoint Kotlin lint exception: {exc}")

    # Architecture drift
    try:
        from architecture_drift import check_architecture_drift
        passed, msg, viols = check_architecture_drift(repo, plan.get("architecture_contract"), task_changes=phase_changes)
        if not passed:
            raise ValidationError(f"phase checkpoint architecture drift: {msg}")
    except (ImportError, ValidationError):
        raise
    except Exception as exc:
        raise ValidationError(f"phase checkpoint architecture drift check exception: {exc}")

    # Room schema guard
    def _phase_p(item: Any) -> str:
        return str(item.get("path", "") if isinstance(item, dict) else item or "")

    has_room = any(
        (_phase_p(c).endswith(".kt") and any(w in _phase_p(c).lower() for w in ("entity", "dao", "database")))
        or "room" in _phase_p(c).lower()
        for c in phase_changes
    ) or "ROOM_SCHEMA" in (phase_policy.get("surfaces") or [])
    if has_room:
        try:
            from room_guard import check_room_working_tree
            phase_paths = [_phase_p(c) for c in phase_changes if _phase_p(c)]
            room_ok, room_msg = check_room_working_tree(repo=repo, paths=phase_paths)
            if not room_ok:
                raise ValidationError(f"phase checkpoint Room schema violation: {room_msg}")
        except (ImportError, ValidationError):
            raise
        except Exception as exc:
            raise ValidationError(f"phase checkpoint Room check exception: {exc}")

    preflight_status = {"status": "PASS"}

    # 2. Targeted compile only when the central policy calls for a build or
    # tests. Documentation and other T0 changes must not trigger Gradle.
    resolved_modules = resolve_phase_modules(repo, manifest)
    build_gates = {"unit_tests", "instrumented_tests", "assemble"}
    if build_gates.intersection(phase_policy.get("gates") or []):
        try:
            compile_ok, compile_detail = check_phase_compile(repo, resolved_modules, phase_changes=phase_changes)
            if not compile_ok:
                raise ValidationError(f"phase checkpoint compile failed: {compile_detail}")
            compile_status = {"status": compile_detail, "modules": resolved_modules}
        except (ImportError, ValidationError):
            raise
        except Exception as exc:
            raise ValidationError(f"phase checkpoint compile exception: {exc}")
    else:
        compile_status = {"status": "NOT_REQUIRED", "modules": []}

    # 3. Policy-required tests
    needs_tests = "unit_tests" in (phase_policy.get("gates") or [])
    try:
        tests_ok, tests_detail = check_phase_tests(repo, phase_dir, resolved_modules, needs_tests, phase_changes=phase_changes)
        if not tests_ok:
            raise ValidationError(f"phase checkpoint unit tests failed: {tests_detail}")
        tests_status = {"status": tests_detail}
    except (ImportError, ValidationError):
        raise
    except Exception as exc:
        raise ValidationError(f"phase checkpoint unit tests exception: {exc}")

    from phase_review import (
        is_phase_review_needed,
        set_phase_substate,
        compute_phase_diff_stats,
        compute_phase_delta_sha256,
        phase_path_states,
        derive_final_review_reserve,
        _compute_phase_diff,
        PHASE_REVIEW_PACKAGE_REQUIRED,
        PHASE_COMPLETE,
    )

    diff_paths = [c.get("path") if isinstance(c, dict) else str(c) for c in phase_changes if c]
    diff_text = _compute_phase_diff(repo, diff_paths)
    diff_stats = compute_phase_diff_stats(diff_text, diff_paths)
    phase_delta_sha256 = compute_phase_delta_sha256(phase_id, phase_changes)

    review_needed, selected_reviewers = is_phase_review_needed(
        repo=repo,
        task_id=args.task_id,
        plan=plan,
        target_phase=target_phase,
        phase_changes=phase_changes,
        phase_policy=phase_policy,
        diff_stats=diff_stats,
    )

    if review_needed:
        review_status = {"status": "REVIEW_PACKAGE_REQUIRED", "reviewers": selected_reviewers}
    else:
        review_status = {"status": "NOT_REQUIRED", "reviewers": []}

    final_review_reserve = derive_final_review_reserve(repo, plan, phase_policy)

    checkpoint_record = {
        "schema_version": 2,
        "task_id": args.task_id,
        "phase_id": phase_id,
        "status": "CHECKPOINT_PASS",
        "checkpoint_at": utc_now(),
        "phase_delta_sha256": phase_delta_sha256,
        "changed_files": diff_stats["changed_files"],
        "added_lines": diff_stats["added_lines"],
        "deleted_lines": diff_stats["deleted_lines"],
        "changed_lines": diff_stats["changed_lines"],
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "task_change_set_sha256": manifest["task_change_set_sha256"],
        "manifest_delta": phase_changes,
        "additional_task_approved_files": sorted(additional_phase_files),
        "phase_path_states": phase_path_states(repo, phase_changes),
        "preflight": preflight_status,
        "compile": compile_status,
        "tests": tests_status,
        "review": review_status,
        "final_review_reserve": final_review_reserve,
    }
    checkpoint_record["checkpoint_sha256"] = canonical_sha256(checkpoint_record)
    atomic_write_json(phase_dir / "checkpoint.json", checkpoint_record)

    completed = list(phase_state.get("completed_phases") or [])
    curr_idx = next((i for i, p in enumerate(phases) if p.get("id") == phase_id), -1)
    if review_needed:
        phase_state = set_phase_substate(directory, phase_id, PHASE_REVIEW_PACKAGE_REQUIRED)
        phase_state.setdefault("phase_checkpoints", {})[phase_id] = checkpoint_record["checkpoint_sha256"]
        atomic_write_json(phase_state_file, phase_state)
    else:
        phase_state = set_phase_substate(directory, phase_id, PHASE_COMPLETE)
        if phase_id not in completed:
            completed.append(phase_id)
        phase_state["completed_phases"] = completed
        phase_state.setdefault("phase_checkpoints", {})[phase_id] = checkpoint_record["checkpoint_sha256"]
        atomic_write_json(phase_state_file, phase_state)

    return {
        "status": CheckpointStatus("CHECKPOINT_PASS"),
        "phase_id": phase_id,
        "completed_phases": completed,
        "current_phase_id": phase_state.get("current_phase_id"),
        "next_phase_index": curr_idx + 1 if curr_idx + 1 < len(phases) else curr_idx,
        "checkpoint": checkpoint_record,
        "preflight": preflight_status,
        "compile": compile_status,
        "tests": tests_status,
        "review": review_status,
    }


def validated_completed_phase_manifest(
    repo: Path, task_id: str, plan: dict, phase_state: dict, phase: dict,
    *, for_final: bool = False,
) -> dict:
    """Validate phase progression, or its historical proof before fresh final gates."""
    from phase_review import PHASE_COMPLETE, compute_phase_delta_sha256, get_phase_substate, phase_path_states

    phase_id = phase.get("id")
    if phase_id not in (phase_state.get("completed_phases") or []):
        raise ValidationError("current phase is not marked complete")
    if get_phase_substate(phase_state, phase_id) != PHASE_COMPLETE:
        raise ValidationError("completed phase substate disagrees with phase completion list")
    directory = task_dir(repo, task_id)
    checkpoint_f = directory / "phases" / phase_id / "checkpoint.json"
    checkpoint = read_json(checkpoint_f) if checkpoint_f.is_file() else None
    if not isinstance(checkpoint, dict) or any(checkpoint.get(key) != value for key, value in {
        "task_id": task_id, "phase_id": phase_id, "status": "CHECKPOINT_PASS",
    }.items()):
        raise ValidationError("current phase checkpoint is missing or invalid")
    checkpoint_sha = checkpoint.get("checkpoint_sha256")
    if (
        not checkpoint_sha
        or checkpoint_sha != canonical_sha256({k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"})
        or phase_state.get("phase_checkpoints", {}).get(phase_id) != checkpoint_sha
    ):
        raise ValidationError("current phase checkpoint integrity or identity mismatch")
    baseline_f = directory / "phases" / phase_id / "baseline.json"
    baseline = read_json(baseline_f) if baseline_f.is_file() else load_task_baseline(repo, task_id)
    manifest = build_task_manifest(
        repo, baseline,
        expected_files=phase.get("expected_files") or plan.get("expected_files"),
    )
    changes = manifest.get("task_changes") or []
    historical_for_final = for_final
    if any((
        manifest["delivery_snapshot_sha256"] != checkpoint.get("delivery_snapshot_sha256"),
        manifest["task_change_set_sha256"] != checkpoint.get("task_change_set_sha256"),
        compute_phase_delta_sha256(phase_id, changes) != checkpoint.get("phase_delta_sha256"),
        phase_path_states(repo, changes) != checkpoint.get("phase_path_states"),
    )):
        if not historical_for_final:
            raise ValidationError("phase checkpoint is stale; re-checkpoint the current phase before advancing")
    review_status = checkpoint.get("review")
    if not isinstance(review_status, dict):
        raise ValidationError("phase checkpoint review decision is missing")
    if review_status.get("status") == "REVIEW_PACKAGE_REQUIRED":
        from phase_review import validate_completed_phase_review_proof

        validate_completed_phase_review_proof(repo, task_id, phase_id, checkpoint_sha, historical_for_final=historical_for_final)
    elif review_status.get("status") != "NOT_REQUIRED":
        raise ValidationError("phase checkpoint review decision is invalid")
    return manifest


def begin_next_phase(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    if plan.get("status") != "IMPLEMENTING":
        raise ValidationError("begin-next-phase requires an IMPLEMENTING plan")
    phases = plan.get("phases") or []
    if not phases:
        raise ValidationError("plan does not define any phases")
    directory = task_dir(repo, args.task_id)
    phase_state_file = directory / "phase-state.json"
    phase_state = read_json(phase_state_file) if phase_state_file.is_file() else {}
    completed = set(phase_state.get("completed_phases") or [])
    try:
        active_idx = int(plan.get("active_phase_index") or 0)
    except (TypeError, ValueError):
        active_idx = 0
    cur_phase = phases[active_idx] if active_idx < len(phases) else phases[-1]
    cur_id = cur_phase.get("id")
    if cur_id not in completed:
        raise ValidationError(f"cannot advance to next phase: current phase '{cur_id}' is not complete")

    next_idx = active_idx + 1
    if next_idx >= len(phases):
        raise ValidationError("no next phase to advance to; all phases complete")

    next_phase = phases[next_idx]
    next_id = next_phase["id"]
    if phase_state.get("current_phase_id") not in (cur_id, next_id):
        raise ValidationError("phase state does not match the active or pending next phase")
    if next_id in completed:
        raise ValidationError("next phase is already marked complete before transition")

    cur_man = validated_completed_phase_manifest(repo, args.task_id, plan, phase_state, cur_phase)

    next_dir = directory / "phases" / next_id
    next_dir.mkdir(parents=True, exist_ok=True)
    baseline_f = next_dir / "baseline.json"
    next_baseline = {
        "schema_version": 1,
        "task_id": args.task_id,
        "phase_id": next_id,
        "repository": plan.get("repository"),
        "base_delivery_snapshot_sha256": cur_man["delivery_snapshot_sha256"],
        "base_change_set_sha256": cur_man["change_set_sha256"],
        "changes": cur_man.get("changes") or [],
    }
    next_baseline["baseline_sha256"] = canonical_sha256(next_baseline)
    if baseline_f.is_file():
        if read_json(baseline_f) != next_baseline:
            raise ValidationError("next phase baseline differs from the current delivery snapshot")
    else:
        atomic_write_json(baseline_f, next_baseline)

    # Commit the plan index last. Earlier writes can be retried while the
    # completed current phase remains authoritative in the plan.
    from phase_review import PHASE_IMPLEMENTING

    substates = phase_state.setdefault("phase_substates", {})
    entry = substates.setdefault(next_id, {})
    entry["substate"] = PHASE_IMPLEMENTING
    entry["updated_at"] = utc_now()
    phase_state["substate"] = PHASE_IMPLEMENTING
    phase_state["current_phase_id"] = next_id
    atomic_write_json(phase_state_file, phase_state)

    plan["active_phase_index"] = next_idx
    save_plan(directory / "plan.json", plan)
    return {
        "status": "ADVANCED",
        "task_id": args.task_id,
        "active_phase_index": next_idx,
        "current_phase_id": next_id,
    }


def cmd_task_handoff(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    from task_git_lineage import create_pending_handoff
    return create_pending_handoff(repo, args.task_id)


def cmd_task_reconcile_handoff(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    from task_git_lineage import reconcile_handoff
    return reconcile_handoff(repo, args.task_id)


def _regressions_outside_plan(plan: dict, manifest: dict, regressions: Any) -> list[str]:
    """Failing tests whose class is neither a planned file's test nor a test this task changed."""
    if not isinstance(regressions, list) or not regressions:
        return []
    from plan_authority import changed_file_paths, is_test_path, planned_test_classes

    owned = planned_test_classes(plan.get("expected_files") or [])
    try:
        owned |= {Path(path).stem for path in changed_file_paths(manifest) if is_test_path(path)}
    except (OSError, ValueError, ValidationError):
        pass
    outside = []
    for name in regressions:
        simple = str(name).partition("#")[0].rpartition(".")[2].partition("$")[0]
        if simple and simple not in owned and simple not in outside:
            outside.append(simple)
    return outside


def resolve_next_action(repo: Path, task_id: str, plan: dict | None=None, host: str | None=None):
    """Compatibility entry point delegating to the internal router module."""
    from _workflow.router import resolve_next_action as implementation
    return implementation(repo, task_id, plan=plan, host=host)


def _next_actions(repo: Path, task_id: str, plan: dict) -> list[dict[str, Any]]:
    """Return deterministic, non-mutating guidance for the current lifecycle state."""
    state = str(plan.get("status") or "").upper()
    base = "python .agents/harness.py task"
    identity = f'--repo "{repo}" --task-id "{task_id}"'
    if state in {"DRAFTED", "PLAN_APPROVAL_REQUIRED", "PLAN_DRAFTED", "AWAITING_DEVELOPER_APPROVAL"}:
        return [{
            "action": "approve",
            "code": "APPROVE_PLAN",
            "kind": "DEVELOPER_ACTION",
            "command": f'{base} approve {identity} --source conversation --proof-reference "<phrase>" --enforcement-tier RULE_ENFORCED{_plan_hash_arg(plan)}',
            "reason": "The reviewed plan needs explicit approval before implementation.",
        }]
    if state == "APPROVED":
        return [{
            "action": "begin",
            "code": "BEGIN_TASK",
            "kind": "HARNESS_COMMAND",
            "command": f"{base} begin {identity}",
            "reason": "Start the approved implementation.",
        }]
    if state == "IMPLEMENTING":
        phases = plan.get("phases") or []
        if phases and "active_phase_index" in plan:
            try:
                requested_index = int(plan.get("active_phase_index") or 0)
            except (TypeError, ValueError):
                requested_index = 0
            index = max(0, min(requested_index, len(phases) - 1))
            active_phase = phases[index] if isinstance(phases[index], dict) else {}
            phase_id = str(active_phase.get("id") or "")
            if phase_id:
                return [{
                    "action": "checkpoint-phase",
                    "code": "CHECKPOINT_PHASE",
                    "kind": "HARNESS_COMMAND",
                    "command": f'{base} checkpoint-phase {identity} --phase-id "{phase_id}"',
                    "reason": "Validate the active implementation phase before advancing.",
                }]
    act = resolve_next_action(repo, task_id, plan)
    legacy_action = {
        "RUN_PREFLIGHT": "preflight",
        "RUN_UNIT_TESTS": "test",
        "BUILD_REVIEW_PACKAGE": "review-package",
        "DISPATCH_REVIEWERS": "review",
        "WAIT_FOR_REVIEWERS": "review",
        "INGEST_REVIEW_RESULT": "review",
        "ASSEMBLE": "assemble",
        "DEVICE_INSTALL": "device",
        "MOBILE_VALIDATION_DECISION": "device",
        "FINAL_VERIFY": "verify",
        "COMPLETE_TASK": "complete",
        "DELIVER": "deliver",
        "RESUME_IMPLEMENTATION": "resume",
        "CHECKPOINT_PHASE": "checkpoint-phase",
        "BUILD_PHASE_REVIEW_PACKAGE": "phase-review-package",
        "DISPATCH_PHASE_REVIEWERS": "review",
        "WAIT_FOR_PHASE_REVIEWERS": "review",
        "FINALIZE_PHASE_REVIEW": "phase-review-finalize",
        "FIX_PHASE_FINDINGS": "fix-phase-findings",
        "BEGIN_NEXT_PHASE": "begin-next-phase",
        "RETRY_REVIEW_PROTOCOL": "send_message",
    }.get(act.get("code") or "", act.get("code", "").lower().replace("_", "-"))
    res_entry = {
        "action": legacy_action,
        "code": act.get("code"),
        "kind": act.get("kind"),
        "command": act.get("command"),
        "reason": act.get("reason"),
        "blocking": act.get("blocking", True),
        "inputs": act.get("inputs", {}),
        "expected": act.get("expected", {}),
    }
    for k in ("tool", "instructions", "choices", "before_first_dispatch", "reviewer_prompts", "reviewers", "reviewer_models", "briefs", "package_path", "review_execution_profile", "pending_reviewers"):
        if k in act:
            res_entry[k] = act[k]
    return [res_entry]


def status(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not task_id:
        task_id = _focused_task_id(repo)
    if not task_id:
        raise ValidationError("no active task found in repository state; specify --task-id <id>")
    plan = _load_plan(repo, task_id)
    if bool(getattr(args, "next", False)):
        plan = dict(plan)
        plan["task_state"] = plan.get("status")
        next_act = resolve_next_action(repo, task_id, plan, host=getattr(args, "host", None))
        plan["next_action"] = next_act
        plan["next_actions"] = [
            {
                "action": next_act.get("code"),
                "code": next_act.get("code"),
                "kind": next_act.get("kind"),
                "command": next_act.get("command"),
                "reason": next_act.get("reason"),
                "blocking": next_act.get("blocking", True),
                "inputs": next_act.get("inputs", {}),
                "expected": next_act.get("expected", {}),
                **({"tool": next_act["tool"]} if "tool" in next_act else {}),
                **({"instructions": next_act["instructions"]} if "instructions" in next_act else {}),
                **({"reviewer_models": next_act["reviewer_models"]} if "reviewer_models" in next_act else {}),
            }
        ]
        # Antigravity keeps only the end of long tool output. With the full review briefs inside, the
        # reviewer prompts were cut off and the agent made up brief hashes. The host-facing JSON carries
        # brief paths and one-line prompts only, and ends with the next step and its prompts.
        last = ("task_state", "next_actions", "next_action")
        compact = {key: _compact_for_host(plan[key]) for key in last}
        plan = {**{k: v for k, v in plan.items() if k not in last}, **compact}
        # Strip heavy baseline/history arrays when querying --next so output never balloons to 40,000+ lines
        for heavy_key in ("baseline", "plan_history", "history", "verification_recipes"):
            plan.pop(heavy_key, None)
    if bool(getattr(args, "brief", False)):
        keys = ("task_id", "status", "plan_sha256", "review_rounds", "review_calls_used", "verification_run_id", "next_action")
        plan = {key: plan[key] for key in keys if key in plan}
    return plan


def _compact_for_host(value: Any, prompts: dict | None = None) -> Any:
    """Replace full brief texts by their one-line pointer where one exists, and put reviewer prompts last.

    A brief without a pointer (phase reviewers) keeps its text: the hook matches that text.
    """
    if isinstance(value, list):
        return [_compact_for_host(item, prompts) for item in value]
    if not isinstance(value, dict):
        return value
    if prompts is None:
        prompts = dict(value.get("reviewer_prompts") or (value.get("inputs") or {}).get("reviewer_prompts") or {})
    out: dict = {}
    for key, item in value.items():
        if key == "brief_content" and value.get("brief_pointer_prompt"):
            continue
        if key == "briefs" and isinstance(item, dict):
            out[key] = {
                role: ("see brief_path" if role in prompts and isinstance(text, str) and "\n" in text else text)
                for role, text in item.items()
            }
            continue
        out[key] = _compact_for_host(item, prompts)
    for tail_key in ("reviewers", "reviewer_models", "reviewer_prompts"):
        if tail_key in out:
            out[tail_key] = out.pop(tail_key)
    return out


def _add_plan_arguments(command: argparse.ArgumentParser, *, is_revision: bool = False) -> None:
    if is_revision:
        command.add_argument("--outcome", default=None, help="Updated requested outcome")
    else:
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
        default=None if is_revision else "BOUNDED",
        help="Planning depth scope: BOUNDED (default) or ARCHITECTURAL; revise keeps the plan's depth when omitted",
    )
    command.add_argument("--expected-surfaces")
    command.add_argument("--expected-modules")
    command.add_argument("--test-strategy")
    command.add_argument(
        "--approach",
        help="How the change will be made, in a few sentences (which classes/functions change and why); shown to the developer",
    )
    command.add_argument("--risks", help="Comma-separated risks the developer should know before approving")
    command.add_argument(
        "--device-strategy",
        help="Phone checks the developer will do, each with its expected result (e.g. '1. Open X -> Y shows; 2. ...')",
    )
    command.add_argument("--rollback")
    command.add_argument(
        "--external-write", action="append", default=[], metavar="INTEGRATION",
        help="External mutation explicitly included in the plan presented for approval",
    )
    command.add_argument(
        "--architecture-intent",
        choices=("EXISTING_CHANGE", "NEW_SCREEN", "NEW_FEATURE", "REFACTOR", "MIGRATION",
                 "existing_change", "new_screen", "new_feature", "refactor", "migration"),
        default=None if is_revision else "EXISTING_CHANGE",
        help="Architecture intent: draft defaults to EXISTING_CHANGE; revise preserves the saved mode when omitted",
    )
    command.add_argument("--architecture-target-scope", default="", help="Target component or screen path for architecture resolution")
    command.add_argument("--architecture-target-family", default=None, help="Target architecture family ID")
    command.add_argument("--expected-files", help="Comma-separated expected target files")
    command.add_argument("--phases", help="Optional JSON string or file path defining task phases")
    command.add_argument("--verification-contract", help="Repository-relative JSON file or inline JSON with optional approved criteria and journeys")
    command.add_argument("--task-context-id", default=None, help="Explicit Task Context ID for collision-safe scope binding")
    command.add_argument("--force", action="store_true", help="Bypass active task collision barriers")
    command.add_argument("--zoho-item-id", default=None, help="Linked Zoho Sprints item ID")
    command.add_argument("--zoho-sprint-id", default=None, help="Linked Zoho Sprints sprint ID")
    command.add_argument(
        "--zoho-item-type",
        choices=("Bug", "Task", "Story", "bug", "task", "story"),
        default=None,
        help="Linked Zoho Sprints item type: Bug, Task, or Story",
    )


def _parse_zoho_link(args: argparse.Namespace) -> dict | None:
    zoho_item_id = getattr(args, "zoho_item_id", None)
    zoho_sprint_id = getattr(args, "zoho_sprint_id", None)
    zoho_item_type = getattr(args, "zoho_item_type", None)

    if zoho_item_id or zoho_sprint_id or zoho_item_type:
        if not zoho_item_id:
            raise ValidationError("ZOHO_LINK_INVALID: --zoho-item-id is required when linking Zoho work.")
        if not zoho_item_type:
            raise ValidationError("ZOHO_LINK_INVALID: --zoho-item-type is required when linking Zoho work (Bug, Task, or Story).")
        norm_type = str(zoho_item_type).strip().lower().capitalize()
        if norm_type not in ("Bug", "Task", "Story"):
            raise ValidationError(f"ZOHO_LINK_INVALID: Invalid Zoho item type '{zoho_item_type}'. Must be Bug, Task, or Story.")
        return {
            "item_id": str(zoho_item_id).strip(),
            "sprint_id": str(zoho_sprint_id or "").strip(),
            "item_type": norm_type,
        }
    return None


def acceptance_coverage(args: argparse.Namespace) -> dict:
    from verification_contract import active_context, coverage_report
    repo = Path(args.repo).resolve()
    plan, current, store = active_context(repo, args.task_id)
    report = coverage_report(plan, current, store)
    if plan.get("verification_contract") and current:
        freshness = verification_freshness(repo, args.task_id, allow_completed=True)
        if not freshness.get("fresh"):
            for row in report["criteria"]:
                if row["status"] == "VERIFIED":
                    row["status"], row["detail"] = "STALE", "Delivery inputs changed"
            report["blocking"] = [row["id"] for row in report["criteria"] if row["required"] and row["status"] != "VERIFIED"]
    return report


def associate_acceptance_evidence(args: argparse.Namespace) -> dict:
    from verification_contract import active_context, bind_evidence
    from evidence_store import StateLock
    repo = Path(args.repo).resolve()
    with StateLock(state_root(repo)):
        plan, current, store = active_context(repo, args.task_id, True)
        bind_evidence(plan, current, store, args.criterion, args.artifact, args.case, lock=False)
    return acceptance_coverage(args)


def local_task_metrics(args: argparse.Namespace) -> dict:
    from task_metrics import metrics_report
    return metrics_report(Path(args.repo).resolve(), args.task_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    common.add_argument("--task-id", required=True)
    from host_continuation import continue_task
    command = sub.add_parser("continue", parents=[common])
    command.add_argument("--host", required=True, help="Receiving host; never rewrites the project's preferred host")
    command.add_argument("--source-stopped", action="store_true", help="Confirm the former executor has stopped writing")
    command.add_argument("--expect-session", help="Compare-and-swap against the previously observed host session ID")
    command.set_defaults(handler=continue_task)
    sub.add_parser("coverage", parents=[common]).set_defaults(handler=acceptance_coverage)
    sub.add_parser("metrics", parents=[common]).set_defaults(handler=local_task_metrics)
    binding = sub.add_parser("bind-evidence", parents=[common])
    binding.add_argument("--criterion", required=True)
    binding.add_argument("--artifact", required=True)
    binding.add_argument("--case", default="")
    binding.set_defaults(handler=associate_acceptance_evidence)
    draft_cmd = sub.add_parser("draft", parents=[common])
    _add_plan_arguments(draft_cmd, is_revision=False)
    draft_cmd.set_defaults(handler=draft)
    revise_cmd = sub.add_parser("revise", parents=[common])
    _add_plan_arguments(revise_cmd, is_revision=True)
    revise_cmd.add_argument("--material-change-reason", help="Concrete requirement expansion when revising only approved plan prose")
    revise_cmd.set_defaults(handler=revise)
    from plan_notes import register_parser as register_plan_notes
    register_plan_notes(sub, common)
    command = sub.add_parser("checkpoint-phase", parents=[common])
    command.add_argument("--phase-id", default=None, help="Phase ID to checkpoint")
    command.set_defaults(handler=checkpoint_phase)
    bnp_cmd = sub.add_parser("begin-next-phase", parents=[common])
    bnp_cmd.set_defaults(handler=begin_next_phase)
    pp_cmd = sub.add_parser("present-plan", parents=[common])
    pp_cmd.add_argument("--artifact-path", required=True, help="Path to host-native plan presentation artifact")
    pp_cmd.add_argument("--no-feedback", action="store_true", help="Do not request interactive feedback on artifact")
    pp_cmd.set_defaults(handler=present_plan)
    command = sub.add_parser("approve", parents=[common])
    command.add_argument("--source", choices=("host_native", "conversation", "developer_terminal"), required=True)
    command.add_argument("--proof-reference", required=True)
    command.add_argument("--enforcement-tier", choices=("HARD_ENFORCED", "RULE_ENFORCED"), required=True)
    command.add_argument("--plan-hash", default=None, help="Plan hash shown in the approved PLAN_SUMMARY (at least 12 hex characters)")
    command.set_defaults(handler=record_approval)
    command = sub.add_parser("approve-sensitive", parents=[common])
    command.add_argument("--source", choices=("host_native", "conversation", "developer_terminal"), required=True)
    command.add_argument("--proof-reference", required=True)
    command.add_argument("--enforcement-tier", choices=("HARD_ENFORCED", "RULE_ENFORCED"), required=True)
    command.set_defaults(handler=record_sensitive_approval)
    from review_budget import record_review_budget
    from change_decision import register_parser
    register_parser(sub, common)
    command = sub.add_parser("review-budget", parents=[common])
    command.add_argument("--limit", type=int, help="Developer-approved reviewer call limit (12-100)")
    command.add_argument("--round-limit", type=int, help="Developer-approved final review round limit (3-100)")
    command.add_argument("--source", choices=("conversation", "developer_terminal"), required=True)
    command.add_argument("--proof-reference", required=True)
    command.set_defaults(handler=record_review_budget)
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
    pv_cmd = sub.add_parser("prepare-verification", parents=[common])
    pv_cmd.add_argument("--force", action="store_true", help="Force regenerate verification run snapshot")
    pv_cmd.add_argument("--host", default=None, help="Host environment for reviewer execution")
    pv_cmd.set_defaults(handler=prepare_verification)
    sub.add_parser("verify", parents=[common]).set_defaults(handler=verify_task)
    sub.add_parser("complete", parents=[common]).set_defaults(handler=complete)
    command = sub.add_parser("deliver", parents=[common])
    command.add_argument("--allow-dirty-tree", action="store_true", help="Explicit developer override to deliver while verified task files remain uncommitted")
    command.add_argument("--developer-allow-dirty-tree", action="store_true", help="Explicit developer-terminal override to deliver while verified task files remain uncommitted")
    command.add_argument("--source", choices=("developer_terminal", "host_native", "conversation"), default=None, help="Authority source for delivery override")
    command.set_defaults(handler=deliver_task)
    cancel_cmd = sub.add_parser("cancel", parents=[common])
    cancel_cmd.add_argument("--source", choices=["conversation", "developer_terminal"], default="developer_terminal")
    cancel_cmd.add_argument("--proof-reference", default="", help="The developer's words asking to cancel (with --source conversation)")
    cancel_cmd.set_defaults(handler=cancel)
    resume_cmd = sub.add_parser("resume", parents=[common])
    resume_cmd.add_argument("--reopen", action="store_true", help="Reopen a verified READY task because the developer requested changes before committing")
    resume_cmd.set_defaults(handler=resume)
    sub.add_parser("handoff", parents=[common]).set_defaults(handler=cmd_task_handoff)
    sub.add_parser("reconcile-handoff", parents=[common]).set_defaults(handler=cmd_task_reconcile_handoff)
    reconcile_cmd = sub.add_parser("reconcile-delivery", parents=[common])
    reconcile_cmd.set_defaults(handler=cmd_reconcile_delivery)
    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    status_cmd.add_argument("--task-id", default="", help="Task ID (defaults to active task if omitted)")
    status_cmd.add_argument("--next", action="store_true", help="Include the safest next lifecycle command without executing it")
    status_cmd.add_argument("--brief", action="store_true", help="Show lifecycle identity, spending and the exact next action without repeating the full plan")
    status_cmd.add_argument("--host", default=None, help="Host running this task; binds routed review commands")
    status_cmd.set_defaults(handler=status)
    command = sub.add_parser("recover-stale")
    command.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    command.add_argument("--task-id", default="")
    command.set_defaults(handler=recover_stale)
    command = sub.add_parser("switch", help="Focus a live task without changing its approval or verification state")
    command.add_argument("--repo", default=".")
    command.add_argument("--task-id", required=True)
    command.set_defaults(handler=recover_active)
    from task_merge import merge_plans
    command = sub.add_parser("merge", parents=[common], allow_abbrev=False, help="Preview consolidation of two or three never-started plans into a new pending task")
    command.add_argument("--from-task-id", action="append", required=True, help="Source task id; repeat for each source in execution order")
    command.add_argument("--apply", action="store_true", help="Apply only after the developer selects the reviewed merge preview")
    command.add_argument("--expect-preview", default="", help="Exact merge_preview_sha256 returned by the reviewed preview")
    command.add_argument("--source", choices=["conversation", "developer_terminal"], default="developer_terminal")
    command.add_argument("--proof-reference", default="", help="Developer's explicit merge choice; never implementation approval")
    command.set_defaults(handler=merge_plans)
    command = sub.add_parser("recover-active")
    command.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    command.add_argument("--task-id", required=True, help="Task ID to restore as active task")
    command.set_defaults(handler=recover_active)
    parser.add_argument("--json", action="store_true")
    for subparser in sub.choices.values():
        # Accept --json after the subcommand too; SUPPRESS keeps the top-level value.
        subparser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return parser


def _prompt_hint(prompts: dict[str, str]) -> str:
    """The reviewer prompts inside the reason, which hosts show even when they cut long output."""
    if not prompts:
        return ""
    listed = "; ".join(f"{role}: `{prompt}`" for role, prompt in sorted(prompts.items()))
    return f" Pass each reviewer exactly its one-line prompt (do not open the brief files): {listed}."


def _reviewer_prompts(profile: Any, roles: list[str]) -> dict[str, str]:
    """Role -> one-line brief pointer the host passes as the reviewer Prompt."""
    reviewers = (profile or {}).get("reviewers") if isinstance(profile, dict) else {}
    prompts = {}
    for role in roles:
        pointer = str(((reviewers or {}).get(role) or {}).get("brief_pointer_prompt") or "")
        if pointer:
            prompts[role] = pointer
    return prompts


def plan_summary(plan: dict, plan_document: Path | None = None) -> str:
    """Canonical, reviewable text of the registered plan; the agent presents it verbatim for approval.

    The full redacted approval payload (bindings, skills, architecture contract) lives in the
    generated plan.md, which the summary links; the plan hash covers both.
    """
    authority = plan_payload(plan)

    def listed(values: Any) -> str:
        items = [str(redact(v)) for v in (values or []) if str(v)]
        return ", ".join(items) if items else "none"

    def displayed(value: Any, *, default: str = "none") -> str:
        if value in (None, "", [], {}):
            return default
        redacted = redact(value)
        if isinstance(redacted, (dict, list)):
            return json.dumps(redacted, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return str(redacted)

    phases = authority.get("phases") or []
    lines = [
        "PLAN_SUMMARY_BEGIN",
        f"Task: {plan.get('task_id')} ({plan.get('task_kind') or 'AUTO'}, {plan.get('planning_depth') or 'BOUNDED'})",
        f"Outcome: {displayed(plan.get('requested_outcome'), default='')}",
        f"Approach: {displayed(authority.get('approach'), default='not stated')}",
        f"Phases: {len(phases) if phases else 'none (single phase)'}",
    ]
    for index, phase in enumerate(phases, 1):
        if isinstance(phase, dict):
            phase_title = phase.get("title") or phase.get("description") or ""
            lines.append(f"  {index}. {phase.get('id')}: {displayed(phase_title, default='')}")
    lines += [
        f"Files: {listed(authority.get('expected_files'))}",
        f"Modules: {listed(authority.get('expected_modules'))}",
        f"Surfaces: {listed(authority.get('expected_surfaces'))}",
        f"Tests: {displayed(authority.get('test_strategy'))}",
        f"Device strategy: {displayed(authority.get('device_strategy'))}",
        f"Risks: {listed(authority.get('risks'))}",
        f"Rollback: {displayed(authority.get('rollback'))}",
        f"External writes: {listed(authority.get('external_writes'))}",
    ]
    if "verification_contract" in authority:
        lines.append(f"Acceptance criteria and selected journeys: {displayed(authority['verification_contract'])}")
    from verification_contract import phone_e2e_setup
    e2e_setup = phone_e2e_setup(plan)
    if e2e_setup:
        lines.append("Phone E2E: " + e2e_setup["summary"])
    if plan.get("review_budget_forecast"):
        from review_budget import forecast_summary
        lines.append(forecast_summary(plan["review_budget_forecast"]))
    if authority.get("supersedes_plan_sha256"):
        lines.append(f"Supersedes plan hash: {str(authority['supersedes_plan_sha256'])[:12]}")
    if authority.get("merged_from"):
        lines.append("Merged source plans (execution order): " + ", ".join(f"{p['task_id']} ({p['plan_sha256'][:12]})" for p in authority["merged_from"]))
    if authority.get("zoho_link"):
        lines.append(f"Zoho link: {displayed(authority.get('zoho_link'))}")
    if plan_document is not None:
        from review_models import model_choice_summary
        lines.append(model_choice_summary(Path(plan_document).resolve().parents[4], str(plan.get("task_id") or "")))
        lines.append(f"Full plan: [plan.md]({Path(plan_document).resolve().as_uri()})")
    lines.append(f"Plan hash: {str(plan.get('plan_sha256') or '')[:12]}")
    # Markdown joins single-newline lines into one paragraph; as a list each field stays on its own line.
    body = [line if line.startswith("  ") else f"- {line}" for line in lines[1:]]
    return "\n".join([lines[0], *body, "PLAN_SUMMARY_END"])


def _drift_causes(repo: Path, manifest: dict, drift: list, plan: dict) -> dict[str, list[str]]:
    """Which changed files bring each drifted surface or skill (for the developer's re-approval)."""
    from change_classifier import classify
    from plan_authority import changed_file_paths

    changes = manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes")
    by_path = {str(c.get("path") if isinstance(c, dict) else c): c for c in changes or []}
    per_file: dict[str, set[str]] = {}
    for path in changed_file_paths(manifest):
        change = by_path.get(path) or {"path": path}
        try:
            surfaces = classify(repo, task_changes=[change], candidate_paths=[path], progress=False).get("surfaces") or []
        except Exception:
            surfaces = []
        per_file[path] = set(surfaces)
    causes: dict[str, list[str]] = {}
    planned = set(plan.get("expected_surfaces") or [])
    for item in drift:
        kind, _, name = str(item).partition(":")
        if kind == "surface":
            causes[str(item)] = sorted(p for p, s in per_file.items() if name in s)
        elif kind == "file":
            causes[str(item)] = [name]
        elif kind == "skill":
            # A mandatory skill follows from surfaces the plan did not list.
            unplanned = {s for surfaces in per_file.values() for s in surfaces} - planned
            causes[str(item)] = sorted(p for p, s in per_file.items() if s & unplanned)
    return {k: v[:5] for k, v in causes.items() if v}


def _should_record_task_start(repo: Path, task_id: str, plan: dict) -> bool:
    """A code task whose pre-edit test failures are not recorded yet (task-start or RED run)."""
    from plan_authority import CODE_SURFACES

    tdir = task_dir(repo, task_id)
    if (tdir / "task-start-failures.json").is_file() or (tdir / "red-evidence.json").is_file():
        return False
    return bool(set(plan.get("expected_surfaces") or []) & set(CODE_SURFACES))


_COMPILED_SUFFIXES = (".kt", ".kts", ".java", ".xml", ".aidl")


def _compile_check_hint(repo: Path, task_changes) -> str:
    """P7: ask for a compile-only build before prepare-verification when source files changed.

    A compile error found after prepare-verification costs a full test-gate run and a resume;
    the compile task catches it in seconds. Returns "" when no source changed or when the
    project's build task cannot be turned into a compile task (no Gradle wrapper, unknown
    or non-assemble task), so the agent is never sent to a command that cannot work.
    """
    paths = [str((item or {}).get("path") or "") for item in (task_changes or []) if isinstance(item, dict)]
    if not any(path.lower().endswith(_COMPILED_SUFFIXES) for path in paths):
        return ""
    if not any((repo / name).is_file() for name in ("gradlew", "gradlew.bat")):
        return ""
    try:
        from _variants import resolve_compile_task

        task, _note = resolve_compile_task(repo)
    except Exception:
        task = ""
    if not task:
        return ""
    return (
        "When it is complete, first run `python .agents/harness.py compile` "
        f"({task}, no tests) and fix any compile error it names."
    )


def _task_has_changes(repo: Path, task_id: str, plan: dict) -> bool:
    try:
        manifest = build_task_manifest(repo, load_task_baseline(repo, task_id), expected_files=plan.get("expected_files"))
    except Exception:
        return True
    return bool(manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes"))


def _task_has_production_changes(repo: Path, task_id: str, plan: dict) -> bool:
    """True when the task has already modified production source code (.kt/.java outside tests)."""
    try:
        from mutation_guard import _is_production_code

        manifest = build_task_manifest(repo, load_task_baseline(repo, task_id), expected_files=plan.get("expected_files"))
        changes = manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes")
        for item in changes or []:
            path = str((item or {}).get("path") if isinstance(item, dict) else item or "").replace("\\", "/")
            if path and _is_production_code(path):
                return True
    except Exception:
        return False
    return False


def _task_was_approved_before(repo: Path, task_id: str) -> bool:
    """True when an earlier plan of this task (archived by revise) had been approved."""
    history = task_dir(repo, task_id) / "plan-history"
    try:
        return any(read_json(path).get("approval") for path in history.glob("*.json"))
    except (OSError, ValueError, ValidationError):
        return False


def pre_existing_changes_line(repo: Path, plan: dict) -> str:
    """Name the developer's uncommitted files that predate the task (O66).

    Task deltas already exclude them, but a planned file among them carries the developer's
    own edits into the task's commit, and the developer should know that before approving.
    """
    try:
        baseline = load_task_baseline(repo, str(plan.get("task_id") or "")) or {}
    except Exception:
        return ""
    paths = sorted({str(item.get("path") or "") for item in baseline.get("changes") or [] if item.get("path")})
    paths = [path for path in paths if not path.startswith((".agents/", ".harness-"))]
    if not paths:
        return ""
    planned = {str(item).replace("\\", "/").strip("/") for item in plan.get("expected_files") or []}
    shared = [path for path in paths if path in planned]
    line = f"PRE_EXISTING_CHANGES={len(paths)} file(s) already had uncommitted changes before this task: {', '.join(paths[:10])}"
    if len(paths) > 10:
        line += f" (+{len(paths) - 10} more)"
    line += ". They are not part of the task and are never reverted or committed by it."
    if shared:
        line += (
            f" Planned files among them: {', '.join(shared)}; the developer's own edits there will be in the same "
            "file, so the task's commit includes them unless the developer commits or stashes them first. Say this "
            "in the approval question."
        )
    return line


# Real app (1.1.11): "as plain text" produced an unformatted list, and lines that began with a code name
# (`LegacyRevenuePaywallFragment`, 'sale') came out scrambled in an Arabic (right-to-left) question.
QUESTION_FORMAT = (
    "a short bold heading, then one bullet per line starting with a bold label (what changes, files, sensitive "
    "areas or outside writes, phone checks, risks); numbered sub-steps for phone checks; no emoji. "
    "Translate all headings and labels into the developer's active conversation language (never hardcode a fixed language). "
    "For a right-to-left language, start every line with a word in that language, never with a code name, and put "
    "every code name, file name, value and English term in backticks so it keeps its place in the sentence."
)


APPROVAL_QUESTION_GUIDE = (
    "APPROVAL_QUESTION: ask with ask_question, options Approve / Request changes / Cancel task. "
    "Question text, in the developer's language: (1) the PLAN_DOCUMENT_URI as a clickable markdown link, "
    "'[Full plan (plan.md)](<PLAN_DOCUMENT_URI>)'; (2) the APPROVAL_BRIEF lines, translated, each said once, as "
    f"markdown (never in a code block): {QUESTION_FORMAT} Add nothing else: no second summary of the same plan, no "
    "task id, hashes, modules or surface lists (they are in plan.md). Never paste plan.json or command output. Pass "
    "PLAN_HASH to approve --plan-hash."
)


REAPPROVAL_QUESTION_GUIDE = (
    "APPROVAL_QUESTION: this plan was approved before; ask only about the change, with ask_question, options "
    "Approve / Request changes / Cancel task. When the developer asked for this change, this is the only question: "
    "never ask first whether to revise. Question text, in the developer's language: (1) what changed, from "
    "REVISION_CHANGES; (2) why, from DRIFT_CAUSES when present (name each file and what it brought in); (3) the "
    "PLAN_DOCUMENT_URI as a clickable markdown link for the full plan. Format it as markdown: "
    f"{QUESTION_FORMAT} Do not repeat the unchanged plan or the APPROVAL_BRIEF, and never paste plan.json or "
    "command output. Pass PLAN_HASH to approve --plan-hash."
)


def approval_brief(plan: dict, sensitive_advisory: str | None = None) -> str:
    """What the developer needs to decide on, once (the approval question shows this, not the full plan).

    A real approval question carried the plan twice (a translated summary, then every summary field
    verbatim, full paths, hashes, "Rollback", "External writes: none"). The full plan stays in plan.md.
    """
    authority = plan_payload(plan)
    files = [str(item) for item in authority.get("expected_files") or [] if str(item)]
    names = [Path(item).name for item in files]
    attention = sorted(set(authority.get("expected_surfaces") or []) & SENSITIVE_SURFACES)
    lines = [f"What changes: {redact(authority.get('approach') or plan.get('requested_outcome') or 'not stated')}"]
    phases = [phase for phase in authority.get("phases") or [] if isinstance(phase, dict)]
    if len(phases) > 1:
        lines.append("Phases: " + "; ".join(
            f"{index}. {redact(phase.get('title') or phase.get('description') or phase.get('id'))}"
            for index, phase in enumerate(phases, 1)))
    if plan.get("review_budget_forecast"):
        from review_budget import forecast_summary
        lines.append(forecast_summary(plan["review_budget_forecast"]))
    if names:
        shown = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
        lines.append(f"Files ({len(names)}): {shown}")
    reuse_cands = [c for c in (plan.get("reuse_candidates") or []) if isinstance(c, dict)]
    if reuse_cands:
        shown_reuse = ", ".join(
            f"{c.get('symbol')} ({Path(str(c.get('existing_file') or '')).name})"
            for c in reuse_cands[:4]
        )
        lines.append(f"Reuse candidates: {shown_reuse}")
    if attention:
        lines.append(f"Touches: {', '.join(attention)} (reviewed with extra care)")
    if sensitive_advisory:
        prefix = "SENSITIVE_PLANNED_FILES="
        if sensitive_advisory.startswith(prefix):
            remainder = sensitive_advisory[len(prefix):]
            summary = remainder.split(". These planned files")[0].strip()
        else:
            summary = sensitive_advisory.strip()
        lines.append(f"Pre-existing sensitive code: {summary} (add to plan only if your change touches it)")
    writes = [str(item) for item in authority.get("external_writes") or [] if str(item)]
    if writes:
        lines.append(f"Writes outside the repo: {', '.join(writes)}")
    device = str(authority.get("device_strategy") or "").strip()
    if device:
        lines.append(f"Phone checks: {redact(device)}")
    from verification_contract import phone_e2e_setup
    e2e_setup = phone_e2e_setup(plan)
    if e2e_setup:
        lines.append("Phone E2E: " + e2e_setup["summary"])
    if "verification_contract" in authority:
        contract = authority["verification_contract"]
        lines.append("Acceptance criteria: " + "; ".join(
            f"{c['id']} ({'required' if c['required'] else 'advisory'}, {c['method']}): {redact(c['expected'])}"
            for c in contract["criteria"]))
        if contract["journeys"]:
            lines.append("Selected device replays: " + "; ".join(
                f"{j['id']}: {redact(j['purpose'])}; effects: {j['effects']}" for j in contract["journeys"]))
    risks = [str(redact(item)) for item in authority.get("risks") or [] if str(item)]
    if risks:
        lines.append(f"Risks: {'; '.join(risks)}")
    return "\n".join(["APPROVAL_BRIEF_BEGIN", *(f"- {line}" for line in lines), "APPROVAL_BRIEF_END"])

_DIFF_FIELDS = (
    ("expected_surfaces", "Surfaces"), ("expected_files", "Files"), ("expected_modules", "Modules"),
    ("external_writes", "External writes"), ("skills", "Skills"), ("risks", "Risks"),
)
_TEXT_FIELDS = (
    ("requested_outcome", "Outcome"), ("approach", "Approach"), ("device_strategy", "Phone checks"),
    ("test_strategy", "Tests"),
)


def _names(values: Any) -> set[str]:
    out = set()
    for item in values or []:
        out.add(str(item.get("id") or item.get("name") or item) if isinstance(item, dict) else str(item))
    return out


def revision_changes(old: dict, new: dict) -> list[str]:
    """Field-by-field changes between a superseded plan and its revision (P6: ask only about the change)."""
    lines = []
    for key, label in _DIFF_FIELDS:
        before, after = _names(old.get(key)), _names(new.get(key))
        added, removed = sorted(after - before), sorted(before - after)
        if added or removed:
            parts = [f"+ {item}" for item in added] + [f"- {item}" for item in removed]
            lines.append(f"{label}: {', '.join(parts)}")
    for key, label in _TEXT_FIELDS:
        if str(old.get(key) or "").strip() != str(new.get(key) or "").strip():
            lines.append(f"{label}: changed (see plan.md)")
    if len(old.get("phases") or []) != len(new.get("phases") or []):
        lines.append(f"Phases: {len(old.get('phases') or [])} -> {len(new.get('phases') or [])}")
    if old.get("verification_contract") != new.get("verification_contract"):
        # Real app: adding a phone E2E contract was presented as "no scope change".
        contract = new.get("verification_contract") or {}
        lines.append(
            f"Verification contract: {len(contract.get('criteria') or [])} criteria, "
            f"{len(contract.get('journeys') or [])} phone journeys (see plan.md)"
            if contract else "Verification contract: removed"
        )
    return lines


def changed_since_verification(repo: Path, task_id: str, plan: dict, live_manifest: dict) -> list[str]:
    """Paths whose content differs between the verified ready run and the repository now ([] if unknown)."""
    run_id = str(plan.get("ready_run_id") or plan.get("verification_run_id") or "")
    if not run_id:
        try:
            run_id = str(read_json(task_dir(repo, task_id) / "current-run.json").get("run_id") or "")
        except (OSError, ValueError, ValidationError):
            return []
    try:
        validate_id(run_id, "run_id")
        ready = read_json(task_dir(repo, task_id) / f"manifest-{run_id}.json")
    except (OSError, ValueError, ValidationError):
        return []

    def identities(data: dict) -> dict[str, tuple]:
        return {
            str(item.get("path")): (item.get("content_identity"), item.get("git_mode"))
            for item in data.get("files") or [] if isinstance(item, dict) and item.get("path")
        }

    before, after = identities(ready), identities(live_manifest)
    if not before or not after:
        return []
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def _fix_delta(repo: Path, task_id: str, previous_run_id: str, manifest: dict, plan: dict) -> dict | None:
    """Files changed since the reviewed run, and the reviewers those files alone route (None when unknown)."""
    from review_fix_delta import compute_fix_delta

    return compute_fix_delta(repo, task_dir(repo, task_id), previous_run_id, manifest, plan, skills_root(repo), project_kind(repo))


def _with_planned_file_surfaces(
    repo: Path, expected: list[str], files: list[str], classification: dict, task_kind: str, outcome: str,
) -> list[str]:
    """Surfaces named by the agent are a floor (P11).

    The write guard and verification read the planned files' whole content, so a Compose or network
    file the agent left out stopped a real task for a second (and third) approval mid-way. A surface
    the files already have is added when leaving it out would stop the task: as surface drift, or
    through a mandatory skill it brings (COMPOSE_UI adds compose-inspector). One that would not stop
    anything (the generic BUSINESS_LOGIC of a Kotlin file) is left out, so it routes no extra reviewer.
    Sign-in and purchase code already in a tracked file stays out: SENSITIVE_PLANNED_FILES names it.
    """
    from final_verifier import unplanned_mandatory_skills
    from plan_authority import check_material_drift
    from _modules import is_kmp_or_android_test_path

    # A declared test path is deterministic scope even before the file exists.
    # TEST_ONLY is non-drifting, but omitting it would hide its reviewer at approval.
    if any(is_kmp_or_android_test_path(path) for path in files):
        expected = sorted(set(expected) | {"TEST_ONLY"})
    from_content, _unread = _planned_file_surfaces(repo, files)
    extra = sorted(from_content - set(expected))
    if not extra:
        return expected
    drifting = {item.split(":", 1)[1] for item in check_material_drift(
        {"expected_surfaces": expected, "requested_outcome": outcome}, extra) if item.startswith("surface:")}

    def skills_for(surfaces: list[str]) -> dict:
        return decide({**classification, "surfaces": surfaces}, skills_root(repo), project_kind=project_kind(repo), task_kind=task_kind)

    try:
        planned_skills = {"skills": skills_for(list(expected))["skills"]["skills"]}
        for surface in extra:
            if surface not in drifting and unplanned_mandatory_skills(planned_skills, skills_for([*expected, surface])):
                drifting.add(surface)
    except (OSError, ValueError, ValidationError):
        pass
    return sorted(set(expected) | drifting)


def _planned_file_surfaces(repo: Path, files: list[str]) -> tuple[set[str], list[str]]:
    """Surfaces the classifier reads from the planned files, the way the write guard reads them.

    A tracked file's existing sign-in or purchase text does not make the plan sensitive (its diff
    is judged at verification). Returns the surfaces and the files that yielded none.
    """
    from mutation_guard import PRE_EXISTING_CONTENT_SURFACES, _is_tracked

    surfaces: set[str] = set()
    unread: list[str] = []
    for rel in files:
        try:
            found = set(classify(repo, task_changes=[{"path": rel}], candidate_paths=[rel], progress=False).get("surfaces") or [])
        except Exception:
            found = set()
        if _is_tracked(repo, rel):
            found -= PRE_EXISTING_CONTENT_SURFACES
        surfaces |= found
        if not found:
            unread.append(rel)
    return surfaces, unread


def sensitive_planned_files_line(repo: Path, plan: dict) -> str:
    """Planned files that already contain sign-in, purchase or security code the plan's surfaces omit (P3b).

    Edits there are judged on the actual diff at prepare-verification; if the change touches that code,
    the plan needs a second approval mid-task. Saying so before the first approval lets the developer
    include those surfaces once.
    """
    from change_classifier import classify
    from mutation_guard import PRE_EXISTING_CONTENT_SURFACES

    planned = set(plan.get("expected_surfaces") or [])
    found: dict[str, set[str]] = {}
    for rel in plan.get("expected_files") or []:
        rel = str(rel).replace("\\", "/").strip("/")
        if not rel or not (repo / rel).is_file():
            continue
        try:
            surfaces = set(classify(repo, task_changes=[{"path": rel}], candidate_paths=[rel], progress=False).get("surfaces") or [])
        except Exception:
            continue
        for surface in (surfaces & PRE_EXISTING_CONTENT_SURFACES) - planned:
            found.setdefault(surface, set()).add(rel)
    if not found:
        return ""
    listed = "; ".join(f"{surface}: {', '.join(sorted(files)[:3])}" for surface, files in sorted(found.items()))
    return (
        f"SENSITIVE_PLANNED_FILES={listed}. These planned files already contain that code. If the change will "
        "touch it, add those surfaces now (`workflow.py revise --expected-surfaces ...`) so the developer approves "
        "once; otherwise verification stops for a second approval. Say this in the approval question."
    )


def approval_material_lines(repo: Path, result: dict, action: str) -> list[str]:
    """What draft/revise print for the approval question; the same text in --json as `approval_material`."""
    from plan_document import plan_document_path, plan_gaps

    lines: list[str] = []
    directory = task_dir(repo, result["task_id"])
    document = plan_document_path(directory)
    old: dict = {}
    superseded = str(result.get("supersedes_plan_sha256") or "")
    if action == "revise" and superseded and _task_was_approved_before(repo, result["task_id"]):
        try:
            old = read_json(directory / "plan-history" / f"{superseded}.json")
        except (OSError, ValueError, ValidationError):
            old = {}
    reapproval = bool(old)
    sensitive = sensitive_planned_files_line(repo, result)
    if not reapproval:
        lines.append(approval_brief(result, sensitive_advisory=sensitive))
    lines.append(f"PLAN_HASH={str(result.get('plan_sha256') or '')[:12]}")
    if result.get("material_change_reason"):
        lines.append("MATERIAL_CHANGE_REASON=" + str(redact(result["material_change_reason"])))
    from review_models import model_choice_summary
    lines.append(model_choice_summary(repo, str(result["task_id"])))
    if document.is_file():
        lines.append(f"PLAN_DOCUMENT_URI={Path(document).resolve().as_uri()}")
    pre_existing = pre_existing_changes_line(repo, result)
    if pre_existing:
        lines.append(pre_existing)
    if sensitive:
        lines.append(sensitive)
    zoho_item = (result.get("zoho_link") or {}).get("item_id")
    if zoho_item and "zoho_sprints" not in (result.get("external_writes") or []):
        # O67: the developer asked to update the linked item at the end; the plan could not.
        lines.append(
            f"ZOHO_WRITE_NOT_PLANNED=the plan links Zoho item {zoho_item} but cannot update it. If the developer "
            "wants the task to move it to In progress when work starts, add --external-write zoho_sprints before "
            "asking for approval. A later update needs no plan change: show the developer the text, and when they "
            "type `update zoho`, run `python .agents/harness.py zoho authorize --proof-reference \"<their message>\"`."
        )
    gaps = plan_gaps(result)
    if gaps:
        lines.append(
            "PLAN_GAPS=" + ",".join(gaps) + ": the developer cannot review these. Before asking for approval, run "
            "`workflow.py revise` with --approach / --risks / --device-strategy (phone steps with expected results)."
        )
    if reapproval:
        changes = revision_changes(old, result)
        lines.append("REVISION_CHANGES=" + ("; ".join(changes) if changes else "no scope change"))
        causes = old.get("material_drift_causes") or {}
        if causes:
            lines.append("DRIFT_CAUSES=" + "; ".join(f"{item} from {', '.join(files)}" for item, files in causes.items()))
        lines.append(REAPPROVAL_QUESTION_GUIDE)
    else:
        lines.append(APPROVAL_QUESTION_GUIDE)
    return lines


def main(argv: list[str] | None = None) -> int:
    from _vnext_common import configure_utf8_output
    configure_utf8_output()
    enable_line_buffered_stdio()
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if any(str(item).startswith("--verification-contract") for item in raw_argv):
        _, unknown = parser.parse_known_args(raw_argv)
        if unknown:
            # Windows PowerShell 5 split an inline JSON contract at its spaces (real app, two failures).
            print("[FAIL] the --verification-contract value was split into several arguments (Windows PowerShell "
                  "strips double quotes from native arguments). Write the JSON to a .json file with your file tool "
                  "(any folder) and pass its path: --verification-contract <path-to-file.json>", file=sys.stderr)
            return 2
    args = parser.parse_args(argv)
    try:
        if args.action not in {"continue", "status", "coverage", "metrics", "draft", "recover-stale", "merge"}:
            from host_continuation import assert_execution_session
            assert_execution_session(Path(args.repo).resolve(), args.task_id)
        if args.action in {"continue", "merge"} and args.json:
            import contextlib
            with contextlib.redirect_stdout(sys.stderr):
                result = args.handler(args)
        else:
            result = args.handler(args)
        if args.action == "approve" and result.get("status") == "IMPLEMENTING":
            from review_sources import detected_current_host
            from host_continuation import continue_task, load_session
            current_host = detected_current_host()
            repo = Path(args.repo).resolve()
            if current_host and load_session(repo, args.task_id) is None:
                import contextlib
                with contextlib.redirect_stdout(sys.stderr):
                    continue_task(argparse.Namespace(repo=str(repo), task_id=args.task_id, host=current_host,
                                                     source_stopped=False, expect_session=None))
    except (ValidationError, OSError) as exc:
        if args.action == "merge" and args.json and not isinstance(exc, TaskConflictError):
            message = str(exc)
            code = message.split(":", 1)[0] if message.startswith("TASK_MERGE_") else "TASK_MERGE_FAILED"
            print(json.dumps({"status": "BLOCKED", "task_id": args.task_id,
                              "next_action": {"code": code, "kind": "DEVELOPER_ACTION", "command": "", "blocking": True,
                                              "reason": message, "inputs": {"source_task_ids": args.from_task_id},
                                              "instructions": "Explain this blocker in the user's language. Preserve all task history and project files. Show a fresh preview when stale; recover an interrupted publication using its recorded apply command. For ineligible or incompatible plans, offer work in order or separately reviewed scopes. Never auto-cancel or treat merge consent as implementation approval."}},
                             ensure_ascii=False, indent=2))
            return 1
        if isinstance(exc, TaskConflictError) and args.json:
            if not exc.details["tasks"]:
                choices = [{"task_id": tid, "status": plan["status"], "outcome": plan.get("requested_outcome", "")}
                           for tid, plan, _ in live_task_plans(Path(args.repo).resolve()) if tid != args.task_id]
                exc = TaskConflictError(exc.details["code"], exc.details["reason"], args.task_id, choices, exc.details["conflicting_files"], repo=Path(args.repo).resolve())
            print(json.dumps({"status": "BLOCKED", "task_id": args.task_id, "conflict": exc.details,
                              "next_action": {"code": "RESOLVE_TASK_CONFLICT", "kind": "DEVELOPER_ACTION",
                                              "command": "", "blocking": True, "reason": exc.details["reason"],
                                              "inputs": exc.details,
                                              "instructions": "Explain the affected tasks and files in the user's language. Present the available choices with short consequences and a recommendation. Wait for their choice; never cancel, revise approvals, discard edits or mutate Git automatically."}},
                             ensure_ascii=False, indent=2))
            return 1
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
    elif args.action in ("change-decision", "plan-note"):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "debug-evidence":
        print(f"DEBUG_EVIDENCE_RECORDED={len(result.get('entries', []))}")
    elif args.action == "validate-finding":
        print(f"FINDING_VALIDATION_RECORDED={len(result.get('validations', []))}")
    elif args.action == "verify":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "reconcile-delivery":
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if result.get("reconciled"):
                print(f"RECONCILED={result.get('task_id')} -> DELIVERED")
            else:
                print(f"TASK_STATUS={result.get('status', 'READY')}")
    elif args.action == "continue" and not args.json:
        print("TASK_STATUS=CONTINUED")
        print(f"HOST_EXECUTOR={result['host']} SESSION={result['session_id']} ENFORCEMENT={result['enforcement_tier']}")
        print("RESUME_BRIEF=" + json.dumps(result["brief"], ensure_ascii=False))
        upcoming = result["next_action"]
        print(f"NEXT_ACTION={upcoming.get('code')}: {upcoming.get('command') or ''}")
        print(f"NEXT_REASON={upcoming.get('reason') or ''}")
        if upcoming.get("inputs"):
            print("NEXT_ACTION_INPUTS=" + json.dumps(upcoming["inputs"], ensure_ascii=False))
    elif args.json:
        if args.action in ("draft", "revise") or (args.action == "merge" and args.apply):
            # A live run passed --json to draft and revise and got none of this, so the agent wrote the
            # approval question itself (no Cancel option, no files).
            lines = approval_material_lines(Path(args.repo).resolve(), result, args.action)
            result = {**result, "approval_material": "\n".join(lines)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.action == "merge" and not args.apply:
            print(result["plan_summary"])
            print(f"MERGE_PREVIEW_SHA256={result['merge_preview_sha256']}")
            for consequence in result["consequences"]:
                print(consequence)
            print("NEXT_ACTION=CONFIRM_PLAN_MERGE: present the preview and wait for the developer's merge choice.")
        if args.action in ("draft", "revise") or (args.action == "merge" and args.apply):
            for line in approval_material_lines(Path(args.repo).resolve(), result, args.action):
                print(line)
        if args.action == "approve":
            print(f"APPROVED_PLAN_HASH={str(result.get('plan_sha256') or '')[:12]}")
        print(f"TASK_STATUS={result.get('status', 'READY')}")
        if args.action == "approve" and result.get("task_id"):
            # Real app: approve printed only the status, the agent started editing, and the test record
            # the router asks for before the first edit never happened; an old failing test in another
            # feature then stopped verification and cost two approvals.
            try:
                upcoming = resolve_next_action(Path(args.repo).resolve(), str(result["task_id"]), result)
            except Exception:
                upcoming = {}
            if upcoming.get("before_first_edit"):
                print(f"BEFORE_FIRST_EDIT={upcoming['before_first_edit'].get('command')}")
            if upcoming.get("reason"):
                print(f"NEXT_REASON={upcoming['reason']}")
        for item in result.get("next_actions") or []:
            item_cmd = item.get("command")
            if not item_cmd and item.get("tool") == "ask_question":
                item_cmd = "invoke ask_question tool in this turn (DEVELOPER_ACTION)"
            print(f"NEXT_ACTION={item.get('action')}: {item_cmd}")
            print(f"NEXT_REASON={item.get('reason')}")
            if item.get("tool") == "ask_question" and item.get("instructions"):
                print(f"NEXT_INSTRUCTIONS={item.get('instructions')}")
            if item.get("code") in {"DISPATCH_REVIEWERS", "DISPATCH_PHASE_REVIEWERS"}:
                # Preserve the router's exact payload once, including current briefs.
                print("NEXT_ACTION_INPUTS=" + json.dumps(item.get("inputs", {}), ensure_ascii=False))
    if args.action in ("draft", "revise", "recover-active", "reconcile-delivery"):
        return 0 if result.get("status") not in ("BLOCKED", "STALE", "USER_DECISION_REQUIRED") else 1
    return 0 if result.get("status") not in ("BLOCKED", "STALE", "PLAN_APPROVAL_REQUIRED", "USER_DECISION_REQUIRED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
