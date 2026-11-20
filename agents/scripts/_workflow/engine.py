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
    HarnessError,
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
from change_classifier import (  # noqa: E402
    CRITICAL_SURFACES,
    HIGH_SURFACES,
    PRESENTATIONAL_ASSET_EXTENSIONS,
    classify,
    is_documentation_path,
)
from delivery_manifest import (  # noqa: E402
    assert_no_unresolved_conflicts,
    build_manifest,
    build_task_manifest,
    find_conflict_markers,
    git_merge_in_progress,
    load_task_baseline,
    unmerged_paths,
)
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
_CONFLICT_KIND_ALIASES = {"CONFLICT", "FIX_CONFLICT", "MERGE"}


def normalize_task_kind(raw_kind: str | None, repo: Path | None = None, text_to_scan: str = "") -> str:
    """Resolve and normalize task kind (`BUG`, `FEATURE`, `REFACTOR`, or `CONFLICT`)."""
    raw = str(raw_kind or "AUTO").strip().upper()
    if raw in _CONFLICT_KIND_ALIASES:
        return "CONFLICT"
    if raw not in {"AUTO", "BUG", "FEATURE", "REFACTOR"}:
        raw = "AUTO"
    if raw == "AUTO":
        # Outcome text can describe application/data conflicts. Only Git evidence
        # or an explicit kind may select the merge-specific verification policy.
        if repo is not None:
            try:
                if unmerged_paths(repo):
                    return "CONFLICT"
            except (OSError, ValueError, ValidationError):
                pass
        if re.search(r"\b(?:bug|crash|fix|regression|error|fault|anr|issue|exception)\b", (text_to_scan or "").lower()):
            return "BUG"
        return "FEATURE"
    return raw


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


def _flatten_multi_arg(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Flatten CLI/programmatic multi-value flags accepting CSV, space-separated, mixed, or repeated values."""
    if not raw:
        return []
    chunks = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, (list, tuple)) else []
    items: list[str] = []
    for chunk in chunks:
        for part in str(chunk or "").split(","):
            cleaned = part.strip()
            if cleaned:
                items.append(cleaned)
    return items


def normalize_expected_files(repo: Path, raw_files: str | list[str] | None) -> list[str]:
    items = _flatten_multi_arg(raw_files)
    if not items:
        return []
    normalized = set()
    for item in items:
        posix_str = validate_repo_path_containment(repo, item)
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


def _find_uncommitted_task_files(repo: Path, task_id: str, plan: dict, live_manifest: dict | None = None) -> list[str]:
    manifest = live_manifest if live_manifest is not None else build_manifest(repo)
    changes_list_live = manifest.get("changes") or []
    current_changes = {str(c.get(k) or "") for c in changes_list_live for k in ("path", "old_path")}
    if not current_changes:
        return []
    from change_classifier import is_documentation_path
    from change_decision import additional_files
    planned_paths = {
        str(p).replace("\\", "/").strip("/")
        for p in list(plan.get("expected_files") or []) + list(additional_files(plan))
        if str(p).strip()
    }
    verified_paths: set[str] = set()
    ready_run_id = str(plan.get("ready_run_id") or "")
    if ready_run_id:
        ready_manifest_path = task_dir(repo, task_id) / f"manifest-{ready_run_id}.json"
        if ready_manifest_path.is_file():
            try:
                rm = read_json(ready_manifest_path)
                for c in (rm.get("task_changes") if "task_changes" in rm else rm.get("changes") or []):
                    p = str(c.get("path") if isinstance(c, dict) else c or "").replace("\\", "/").strip("/")
                    if p:
                        verified_paths.add(p)
            except (OSError, ValueError, ValidationError):
                pass
    untracked_unplanned_docs = {
        str(c.get("path") or "")
        for c in changes_list_live
        if isinstance(c, dict)
        and c.get("status") == "?"
        and c.get("path")
        and is_documentation_path(str(c["path"]))
        and str(c["path"]).replace("\\", "/").strip("/") not in (planned_paths | verified_paths)
    }
    effective_changes = current_changes - untracked_unplanned_docs
    if not effective_changes:
        return []
    task_baseline = load_task_baseline(repo, task_id)
    if task_baseline is not None:
        task_manifest = build_task_manifest(repo, task_baseline, expected_files=plan.get("expected_files"), live_manifest=manifest)
        uncommitted = [
            str(c.get("path") if isinstance(c, dict) else c or "")
            for c in (task_manifest.get("task_changes") or [])
            if (c.get("path") if isinstance(c, dict) else c) and (not isinstance(c, dict) or c.get("status") != "BASELINE_DIRTY_REMOVED")
        ]
        return sorted(set(uncommitted) & effective_changes)
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
            return sorted(task_files & effective_changes)
    expected = set(plan.get("expected_files") or [])
    return sorted(expected & effective_changes)


from delivery_manifest import (
    LIVE_TASK_STATUSES,
    TaskConflictError,
    assert_disjoint_task_scope,
    disjoint_sibling_file_sets,
    live_task_plans,
)

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
            req_kind = normalize_task_kind(
                getattr(args, "kind", "AUTO"),
                repo=repo,
                text_to_scan=f"{req_outcome} {' '.join(_flatten_multi_arg(getattr(args, 'expected_surfaces', None)))}",
            )
            exist_depth = str(existing_plan.get("planning_depth") or "BOUNDED").upper()
            req_depth = str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper()
            norm_expected_files = normalize_expected_files(repo, getattr(args, "expected_files", None))
            raw_expected = _flatten_multi_arg(getattr(args, "expected_surfaces", None))
            expected_surfs = normalize_expected_surfaces(raw_expected)
            exist_surfs = sorted(existing_plan.get("expected_surfaces") or [])
            exist_files = sorted(existing_plan.get("expected_files") or [])
            exist_modules = sorted(existing_plan.get("expected_modules") or [])
            req_modules = sorted(module_id(item) for item in _flatten_multi_arg(getattr(args, "expected_modules", None)))
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

    inline_ctx_summary: dict[str, Any] | None = None
    if getattr(args, "with_context", False):
        try:
            from task_context import resolve_task_contexts
            existing_targets = [
                rel for rel in (candidate.get("expected_files") or [])
                if (repo / rel).is_file() and Path(rel).suffix.lower() in {".kt", ".java", ".xml", ".swift"}
            ][:8]
            if existing_targets:
                ctx_res = resolve_task_contexts(repo, files=existing_targets, trust_stat=True)
                rows = ctx_res.get("results") if isinstance(ctx_res.get("results"), list) else [ctx_res]
                bound_impls = [
                    b.get("path") or b.get("name")
                    for r in rows if isinstance(r, dict)
                    for b in (r.get("bound_implementations") or [])
                    if isinstance(b, dict) and (b.get("path") or b.get("name"))
                ]
                cand_tests = [
                    t.get("path") or t.get("name")
                    for r in rows if isinstance(r, dict)
                    for t in (r.get("tests") or [])
                    if isinstance(t, dict) and (t.get("path") or t.get("name"))
                ]
                inline_ctx_summary = {
                    "status": ctx_res.get("status"),
                    "discovery_id": (ctx_res.get("discovery") or {}).get("id") or (rows[0].get("discovery") or {}).get("id") if rows and isinstance(rows[0], dict) else None,
                    "read_ranges": list(ctx_res.get("read_ranges") or [])[:16],
                    "bound_implementations": list(dict.fromkeys(bound_impls))[:12],
                    "candidate_tests": list(dict.fromkeys(cand_tests))[:12],
                }
        except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
            inline_ctx_summary = None

    plan = _build_and_save_plan(repo, args, task_id, is_revision=False)
    try:
        from execution_mode import bind_pending_execution_mode_to_task
        bind_pending_execution_mode_to_task(repo, task_id)
    except (ImportError, OSError, ValueError, ValidationError):
        pass
    _write_plan_document(repo, task_id, plan)
    if inline_ctx_summary is not None:
        return {**plan, "inline_task_context": inline_ctx_summary}
    return plan


EXPRESS_DISALLOWED_SURFACES = frozenset(
    set(CRITICAL_SURFACES)
    | set(HIGH_SURFACES)
    | {
        "ROOM_SCHEMA",
        "BUILD_CONFIG",
        "MANIFEST_PERMISSION",
        "SECURITY",
        "AUTH",
        "BILLING",
        "SENSITIVE_DATA",
        "CRYPTO",
        "PUBLIC_API",
        "UNKNOWN",
        "DEVICE_API",
        "PERSISTENCE",
        "NETWORK",
        "NATIVE_CODE",
        "NAVIGATION",
    }
)


_EXPRESS_OUTCOME_SENSITIVE_RE = re.compile(
    r"\b(?:oauth|auth|authentication|login|signup|signin|credential|password|biometric|"
    r"billing|payment|subscription|purchase|revenuecat|paywall|iap|"
    r"room|migration|schema|datastore|sharedpreferences|sqlite|"
    r"retrofit|okhttp|graphql|websocket|endpoint|"
    r"permission|permissions|androidmanifest|keystore|crypto|encrypt|decrypt|"
    r"navhost|navgraph|deeplink|jni|ndk)\b",
    re.IGNORECASE,
)


def _auto_quick_start_task_id(repo: Path, outcome: str, files_raw: str) -> str:
    base_txt = str(outcome or "").strip() or Path(str(files_raw or "micro-task").split(",")[0].strip()).stem
    slug = re.sub(r"[^a-z0-9]+", "-", base_txt.lower()).strip("-")[:28].strip("-")
    if len(slug) < 3:
        slug = "micro-task"
    cand = f"qs-{slug}"
    if not (state_root(repo) / "tasks" / cand).exists():
        return cand
    suffix = canonical_sha256({"outcome": outcome, "files": files_raw, "ts": utc_now()})[:6]
    return f"qs-{slug[:22].rstrip('-')}-{suffix}"


def _partition_express_files(norm_files: list[str]) -> tuple[list[str], list[str]]:
    from _modules import is_kmp_or_android_test_path
    primary: list[str] = []
    companion: list[str] = []
    for rel in norm_files:
        clean = str(rel).replace("\\", "/").strip("/")
        is_test = is_kmp_or_android_test_path(clean)
        is_locale_parity = bool("/res/values-" in f"/{clean}" and clean.endswith(".xml"))
        if is_test or is_locale_parity:
            companion.append(clean)
        else:
            primary.append(clean)
    if not primary and companion:
        # Pure unit-test or pure localized strings update: count those directly as primary targets
        return companion, []
    return primary, companion


@_serialize_task_scope
def quick_start(args: argparse.Namespace) -> dict:
    """Single-command Express Track for bounded direct-request T0/T1 micro-tasks with safe fallback to AWAITING_DEVELOPER_APPROVAL."""
    repo = Path(args.repo).resolve()
    source = str(getattr(args, "source", "") or "").strip().lower()
    proof_ref = str(getattr(args, "proof_reference", "") or "").strip()
    enforcement_tier = str(getattr(args, "enforcement_tier", "RULE_ENFORCED") or "RULE_ENFORCED").strip().upper()
    if source not in ("conversation", "developer_terminal", "host_native"):
        raise ValidationError("DEVELOPER_AUTHORITY_REQUIRED: `task quick-start` requires `--source conversation` (or `developer_terminal`).")
    if not proof_ref or len(proof_ref) < 2:
        raise ValidationError("DEVELOPER_AUTHORITY_REQUIRED: `task quick-start` requires a non-empty `--proof-reference \"<developer request>\"`.")
    if proof_ref.rstrip().endswith(("?", "\u061f")) and not any(
        tok in proof_ref.lower() for tok in ("fix", "add", "update", "change", "remove", "\u0639\u062f\u0644", "\u0636\u064a\u0641", "\u0627\u0635\u0644\u062d", "\u0635\u0644\u062d", "\u062d\u062f\u062b", "\u063a\u064a\u0631")
    ):
        raise ValidationError(
            "DEVELOPER_AUTHORITY_REQUIRED: `--proof-reference` appears to be a question rather than an explicit implementation request."
        )
    raw_outcome = str(getattr(args, "outcome", "") or "").strip()
    if not raw_outcome:
        raise ValidationError("`task quick-start` requires `--outcome \"<requested change>\"`.")
    raw_files_list = _flatten_multi_arg(getattr(args, "expected_files", None))
    if not raw_files_list:
        raise ValidationError("`task quick-start` requires `--files <1-2 target files>` (or `--expected-files`).")
    norm_files = normalize_expected_files(repo, raw_files_list)
    if not norm_files:
        raise ValidationError("`task quick-start` requires at least one valid repository-relative target file.")
    raw_files = ",".join(norm_files)

    raw_tid = str(getattr(args, "task_id", "") or "").strip()
    task_id = validate_id(raw_tid, "task id") if raw_tid else _auto_quick_start_task_id(repo, raw_outcome, raw_files)
    args.task_id = task_id
    if not str(getattr(args, "approach", "") or "").strip():
        args.approach = f"Apply bounded update to {', '.join(Path(f).name for f in norm_files[:3])} for: {raw_outcome[:140]}"

    assert_single_live_task(repo, allowed_task_id=task_id)
    proposed_scope = {"expected_files": norm_files}
    assert_disjoint_task_scope(repo, task_id, proposed_scope)

    existing_p = _plan_path(repo, task_id)
    if existing_p.is_file():
        existing_plan = read_json(existing_p)
        if str(existing_plan.get("status") or "") == "IMPLEMENTING" and existing_plan.get("express_track") is True:
            return existing_plan
        raise ValidationError(
            f"TASK_PLAN_ALREADY_EXISTS: task '{task_id}' already exists with status '{existing_plan.get('status')}'. "
            "Pass a distinct `--task-id` or manage the existing task."
        )

    plan = _build_and_save_plan(repo, args, task_id, is_revision=False)
    directory = task_dir(repo, task_id)
    prelim_cls_file = directory / "preliminary-classification.json"
    prelim_pol_file = directory / "preliminary-policy.json"
    prelim_cls = read_json(prelim_cls_file) if prelim_cls_file.is_file() else {"surfaces": plan.get("expected_surfaces") or [], "severity": "LOW", "changed_files": len(norm_files), "changed_lines": 20}

    primary_files, _companion_files = _partition_express_files(list(plan.get("expected_files") or norm_files))
    fallback_reasons: list[str] = []
    if len(primary_files) > 2:
        fallback_reasons.append(f"primary_files={len(primary_files)} exceeds Express limit of 2")
    if len(plan.get("expected_files") or []) > 4:
        fallback_reasons.append(f"total_files={len(plan.get('expected_files') or [])} exceeds Express limit of 4")
    if plan.get("external_writes"):
        fallback_reasons.append("external_writes require explicit plan approval")
    if plan.get("phases"):
        fallback_reasons.append("multi-phase plans require explicit plan approval")
    if str(plan.get("planning_depth") or "BOUNDED").upper() == "ARCHITECTURAL":
        fallback_reasons.append("ARCHITECTURAL planning_depth requires explicit plan approval")
    if str(plan.get("task_kind") or "").upper() in {"CONFLICT", "FIX_CONFLICT", "MERGE"}:
        fallback_reasons.append(f"task_kind={plan.get('task_kind')} requires standard workflow")
    if len(plan.get("expected_modules") or []) > 1:
        fallback_reasons.append("cross-module scope requires explicit plan approval")
    arch_status = str((plan.get("architecture_contract") or {}).get("status") or "")
    if arch_status == "ARCHITECTURE_DECISION_REQUIRED":
        fallback_reasons.append("ARCHITECTURE_DECISION_REQUIRED")
    gaps = list((plan.get("readiness_assessment") or {}).get("gaps") or [])
    if gaps:
        fallback_reasons.append(f"plan_gaps={','.join(str(g) for g in gaps[:3])}")

    cand_plan = {**plan, "express_track": True, "changed_modules": list(plan.get("expected_modules") or [])}
    cand_cls = {
        **prelim_cls,
        "changed_files": max(1, len(primary_files)),
        "changed_lines": min(int(prelim_cls.get("changed_lines") or 20), 60) if int(prelim_cls.get("changed_lines") or 0) == 0 else int(prelim_cls.get("changed_lines") or 20),
    }
    cand_policy = decide(
        cand_cls,
        skills_root(repo),
        project_kind=project_kind(repo),
        task_kind=str(plan.get("task_kind") or "FEATURE"),
        plan=cand_plan,
    )
    all_surfs = set(cand_policy.get("surfaces") or []) | set(plan.get("expected_surfaces") or [])
    blocked_surfs = sorted(all_surfs & EXPRESS_DISALLOWED_SURFACES)
    if blocked_surfs:
        fallback_reasons.append(f"sensitive_or_structural_surfaces={','.join(blocked_surfs)}")
    kw_hits = sorted({m.group(0).lower() for m in _EXPRESS_OUTCOME_SENSITIVE_RE.finditer(f"{raw_outcome} {raw_files}")})
    if kw_hits:
        fallback_reasons.append(f"sensitive_or_structural_keywords={','.join(kw_hits[:5])}")
    if cand_policy.get("risk_tier") not in {"T0_TRIVIAL", "T1_LOW_RISK"} or not cand_policy.get("micro_eligible") or cand_policy.get("reviewers"):
        fallback_reasons.append(f"policy_risk_tier={cand_policy.get('risk_tier')}")

    try:
        from execution_mode import bind_pending_execution_mode_to_task
        bind_pending_execution_mode_to_task(repo, task_id)
    except (ImportError, OSError, ValueError, ValidationError):
        pass

    if fallback_reasons:
        _write_plan_document(repo, task_id, plan)
        return {
            **plan,
            "express_track": False,
            "express_eligible": False,
            "express_fallback_reason": "; ".join(fallback_reasons),
        }

    with StateLock(directory / ".lock"):
        plan["express_track"] = True
        if isinstance(plan.get("readiness_assessment"), dict):
            plan["readiness_assessment"]["risk_tier"] = cand_policy.get("risk_tier", "T1_LOW_RISK")
        plan["plan_sha256"] = canonical_sha256(plan_payload(plan))
        atomic_write_json(prelim_pol_file, cand_policy)
        plan = approve_and_begin(
            repo,
            plan,
            source=source,
            proof_reference=proof_ref,
            enforcement_tier=enforcement_tier,
        )
        save_plan(existing_p, plan)
        atomic_write_json(state_root(repo) / "active-task.json", {
            "task_id": task_id,
            "plan_path": str(existing_p),
            "updated_at": utc_now(),
        })
        try:
            from self_heal import save_stable_snapshot
            save_stable_snapshot(repo, task_id, "approved", plan=plan)
        except (OSError, ValueError, ImportError, ValidationError):
            pass
    _write_plan_document(repo, task_id, plan)
    return {
        **plan,
        "express_eligible": True,
        "express_risk_tier": cand_policy.get("risk_tier"),
        "express_gates": cand_policy.get("gates") or [],
    }


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
                data = json.loads(inst_file.read_text(encoding="utf-8-sig"))
                raw_instructions = data.get("instructions", [])
            except (OSError, ValueError, ValidationError):
                pass

    applicable: list[dict[str, Any]] = []
    from project_context import normalize_instruction_record, normalize_instruction_scope
    for raw_inst in raw_instructions:
        if not isinstance(raw_inst, dict):
            continue
        inst = normalize_instruction_record(raw_inst)
        if inst.get("status") != "ACTIVE":
            continue

        scope = inst["scope"]
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
    from _modules import is_kmp_or_android_test_path
    if surfaces and (surfaces <= (NEUTRAL_ARCHITECTURE_SURFACES | {"TEST_ONLY"})):
        if all(is_architecture_neutral_path(p) or is_kmp_or_android_test_path(p) for p in scope_files):
            return True
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
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple)):
            return any(str(item or "").strip() for item in value)
        return bool(value)

    def joined(values: Any) -> str:
        return ",".join(str(item) for item in values or [] if str(item).strip())

    raw_arg_kind = str(getattr(args, "kind", None) or "AUTO").upper()
    if raw_arg_kind == "AUTO" and old_plan.get("task_kind"):
        merged.kind = old_plan["task_kind"]
    elif raw_arg_kind in _CONFLICT_KIND_ALIASES:
        merged.kind = "CONFLICT"
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
    if _flatten_multi_arg(getattr(args, "expected_files", None)):
        proposed["expected_files"] = normalize_expected_files(repo, args.expected_files)
    assert_disjoint_task_scope(repo, task_id, proposed)
    old_status = str(old_plan.get("status") or "")
    restore_cancelled = bool(getattr(args, "restore_cancelled", False))
    allowed_revise_statuses = {"AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED"}
    if restore_cancelled:
        allowed_revise_statuses.add("CANCELLED")
    if old_status not in allowed_revise_statuses:
        hint = " (pass --restore-cancelled to reactivate this cancelled plan losslessly)" if old_status == "CANCELLED" else ""
        raise ValidationError(f"cannot revise task '{task_id}': task status is {old_status}, only active non-terminal tasks can be revised{hint}")
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
        (directory / "reopen-carry.json").unlink(missing_ok=True)
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
    reopen_marker_path = directory / "reopen-carry.json"
    is_reopen_carry = False
    if not marker_path.is_file():
        if reopen_marker_path.is_file():
            marker_path = reopen_marker_path
            is_reopen_carry = True
        else:
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
        if is_reopen_carry:
            if marker.get("plan_sha256") != plan.get("plan_sha256") or marker.get("run_id") != run_id or current.get("task_id") != task_id:
                return give_up("the plan or run changed after reopen")
        else:
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
        drift = [
            d for d in check_material_drift(
                plan, new_policy.get("surfaces") or [], changed_modules(repo, manifest),
                actual_files=changed_file_paths(manifest), repo=repo,
            )
            if not d.startswith("file:")
        ]
        if drift or unplanned_mandatory_skills(plan, new_policy):
            return give_up("material drift")
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        return give_up(str(exc))

    if new_policy != old_policy:
        atomic_write_json(directory / f"policy-{run_id}.superseded-{str(old_policy.get('policy_sha256') or '')[:12]}.json", old_policy)
        atomic_write_json(old_policy_path, new_policy)
    current["plan_revision_carry"] = {
        "from_plan_sha256": marker.get("from_plan_sha256") or marker.get("plan_sha256"),
        "to_plan_sha256": plan.get("plan_sha256"),
        "previous_policy_sha256": old_policy.get("policy_sha256"),
        "policy_sha256": new_policy.get("policy_sha256"),
        "reopen_unchanged_carry": bool(is_reopen_carry),
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
        try:
            from self_heal import save_stable_snapshot
            save_stable_snapshot(repo, args.task_id, "approved", plan=plan)
        except (OSError, ValueError, ImportError, ValidationError):
            pass
    if getattr(args, "with_delegation", False):
        try:
            from delegation_policy import evaluate_delegation_policy
            del_plan = evaluate_delegation_policy(repo, task_id=args.task_id, plan=plan)
            compact_del = {
                "strategy": del_plan.get("strategy") or del_plan.get("execution_strategy") or "INLINE_LEAD_DIRECT",
                "risk_tier": del_plan.get("risk_tier") or plan.get("risk_tier"),
                "quota_strategy": del_plan.get("quota_strategy"),
                "phases": [
                    {
                        "id": ph.get("id") or ph.get("phase_id"),
                        "mode": ph.get("mode") or ph.get("execution_mode") or "INLINE_LEAD_DIRECT",
                        "expected_files": (ph.get("expected_files") or [])[:12],
                    }
                    for ph in (del_plan.get("phases") or [])
                    if isinstance(ph, dict)
                ],
            }
            return {**plan, "delegation_brief": compact_del}
        except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError) as _del_exc:
            sublog(f"Optional delegation brief skipped: {_del_exc}")
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
        try:
            from self_heal import save_stable_snapshot
            save_stable_snapshot(repo, args.task_id, "implementing", plan=plan)
        except (OSError, ValueError, ImportError, ValidationError):
            pass
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

        fid_clean = str(args.finding_id).strip()
        resolved_reviewer = str(getattr(args, "reviewer", "") or "").strip()
        if not resolved_reviewer and fid_clean:
            for rev_file in sorted(directory.glob("reviews-*.json"), reverse=True):
                try:
                    rev_payload = read_json(rev_file)
                    review_entries = (
                        rev_payload.get("reviews")
                        if isinstance(rev_payload, dict) and isinstance(rev_payload.get("reviews"), list)
                        else ([rev_payload] if isinstance(rev_payload, dict) else [])
                    )
                    for r_entry in review_entries:
                        if not isinstance(r_entry, dict):
                            continue
                        r_name = str(r_entry.get("reviewer") or "").strip()
                        for f_item in r_entry.get("findings") or []:
                            if isinstance(f_item, dict) and str(f_item.get("id") or f_item.get("finding_id") or "").strip().lower() == fid_clean.lower():
                                resolved_reviewer = r_name
                                break
                        if resolved_reviewer:
                            break
                except (OSError, ValueError, ValidationError):
                    continue
                if resolved_reviewer:
                    break
        if not resolved_reviewer and fid_clean:
            for ledger_file in sorted(directory.glob("phases/*/review/ledger.json"), reverse=True):
                try:
                    l_payload = read_json(ledger_file)
                    for r_name, r_data in (l_payload.get("reviewers") or {}).items():
                        if not isinstance(r_data, dict):
                            continue
                        for f_item in r_data.get("findings") or []:
                            if isinstance(f_item, dict) and str(f_item.get("id") or f_item.get("finding_id") or "").strip().lower() == fid_clean.lower():
                                resolved_reviewer = str(r_name).strip()
                                break
                        if resolved_reviewer:
                            break
                except (OSError, ValueError, ValidationError):
                    continue
                if resolved_reviewer:
                    break

        entry = {
            "finding_id": fid_clean,
            "status": status,
            "reason": reason,
            "evidence_reference": evidence_ref,
            "recorded_at": utc_now(),
        }
        if resolved_reviewer:
            entry["reviewer"] = resolved_reviewer
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
    from debug_instrumentation import assert_clean, regression_guard
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
    assert_clean(repo, plan)
    with step_progress("Building delivery manifest & snapshot"):
        sublog("Loading task baseline and building manifest...")
        task_baseline = load_task_baseline(repo, args.task_id)
        try:
            assert_no_unresolved_conflicts(repo, task_baseline, extra_paths=plan.get("expected_files"))
        except Exception as exc:
            raise ValidationError(str(exc)) from exc
        task_base_head = (
            plan.get("task_base_head")
            or ((task_baseline or {}).get("repository") or {}).get("head")
            or base_repo.get("head")
        )
        manifest = build_task_manifest(repo, task_baseline, expected_files=plan.get("expected_files"), task_base_head=task_base_head)
        sublog(f"Manifest ready with change set: {manifest.get('change_set_sha256', '')[:12]}")
    with step_progress("Classifying changed surfaces"):
        sublog("Classifying task changes...")
        classification = classify(repo, task_id=args.task_id, task_changes=manifest.get("task_changes"))
        sublog(f"Surfaces: {', '.join(classification.get('surfaces') or []) or 'none'}")
    regression_guard(repo, plan, manifest)
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
    actual_task_paths = changed_file_paths(manifest)
    pre_extra_files = [
        item[5:]
        for item in check_material_drift(plan, [], [], actual_files=actual_task_paths, repo=repo)
        if item.startswith("file:")
    ]
    if pre_extra_files and isinstance(plan.get("approval"), dict) and plan.get("approval", {}).get("plan_sha256"):
        from mutation_guard import file_mutation_allowed as _pre_file_mutation_allowed
        if all(_pre_file_mutation_allowed(repo, targets=[f])[0] for f in pre_extra_files):
            old_plan_sha = str(plan.get("plan_sha256") or "")
            if old_plan_sha:
                history_dir = task_dir(repo, args.task_id) / "plan-history"
                history_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_json(history_dir / f"{old_plan_sha}.json", dict(plan))
                plan["supersedes_plan_sha256"] = old_plan_sha
                plan["in_place_absorbed_plan_shas"] = sorted(set(plan.get("in_place_absorbed_plan_shas") or []) | {old_plan_sha})
            plan["expected_files"] = sorted(set(plan.get("expected_files") or []) | set(pre_extra_files))
            plan.pop("material_drift", None)
            plan.pop("material_drift_causes", None)
            plan["plan_sha256"] = canonical_sha256(plan_payload(plan))
            plan["approval"]["plan_sha256"] = plan["plan_sha256"]
            save_plan(_plan_path(repo, args.task_id), plan)

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
    if plan.get("express_track") is True:
        primary_actual, _ = _partition_express_files(actual_task_paths)
        actual_surfs = set(policy.get("surfaces") or [])
        escalated_surfs = sorted(actual_surfs & EXPRESS_DISALLOWED_SURFACES)
        actual_lines = int(classification.get("changed_lines") or 0)
        actual_mods = changed_modules(repo, manifest)
        esc_reasons: list[str] = []
        if escalated_surfs:
            esc_reasons.append(f"disallowed_surfaces={','.join(escalated_surfs)}")
        if len(primary_actual) > 2:
            esc_reasons.append(f"primary_changed_files={len(primary_actual)} (>2)")
        if len(actual_task_paths) > 4:
            esc_reasons.append(f"total_changed_files={len(actual_task_paths)} (>4)")
        if actual_lines > 100:
            esc_reasons.append(f"changed_lines={actual_lines} (>100)")
        if len(actual_mods) > 1:
            esc_reasons.append(f"changed_modules={','.join(actual_mods)}")
        if policy.get("risk_tier") not in {"T0_TRIVIAL", "T1_LOW_RISK"} or policy.get("reviewers"):
            esc_reasons.append(f"risk_tier={policy.get('risk_tier')}")
        if esc_reasons:
            old_sha = str(plan.get("plan_sha256") or "")
            if old_sha:
                history_dir = task_dir(repo, args.task_id) / "plan-history"
                history_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_json(history_dir / f"{old_sha}.json", dict(plan))
                plan["supersedes_plan_sha256"] = old_sha
            plan.pop("express_track", None)
            plan["expected_files"] = sorted(set(plan.get("expected_files") or []) | set(actual_task_paths))
            plan["expected_surfaces"] = sorted(set(plan.get("expected_surfaces") or []) | actual_surfs)
            if actual_mods:
                plan["expected_modules"] = sorted(set(plan.get("expected_modules") or []) | set(actual_mods))
            plan["status"] = "AWAITING_DEVELOPER_APPROVAL"
            plan["approval"] = None
            plan["execution_nonce"] = None
            plan["plan_sha256"] = canonical_sha256(plan_payload(plan))
            save_plan(_plan_path(repo, args.task_id), plan)
            _write_plan_document(repo, args.task_id, plan)
            raise ValidationError(
                f"EXPRESS_SCOPE_ESCALATED_APPROVAL_REQUIRED: Actual changes exceeded Express Track micro-task bounds "
                f"({'; '.join(esc_reasons)}). Task '{args.task_id}' has been demoted to AWAITING_DEVELOPER_APPROVAL "
                f"(PLAN_HASH={plan['plan_sha256'][:12]}). Present PLAN_SUMMARY via ask_question and obtain explicit developer approval."
            )
    drift = check_material_drift(plan, policy.get("surfaces") or [], changed_modules(repo, manifest), actual_files=actual_task_paths, repo=repo)
    from final_verifier import unplanned_mandatory_skills
    drift = [*drift, *(f"skill:{skill}" for skill in unplanned_mandatory_skills(plan, policy))]
    extra_files = [item[5:] for item in drift if item.startswith("file:")]
    if extra_files and isinstance(plan.get("approval"), dict) and plan.get("approval", {}).get("plan_sha256"):
        from mutation_guard import file_mutation_allowed
        if all(file_mutation_allowed(repo, targets=[f])[0] for f in extra_files):
            old_plan_sha = str(plan.get("plan_sha256") or "")
            if old_plan_sha:
                history_dir = task_dir(repo, args.task_id) / "plan-history"
                history_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_json(history_dir / f"{old_plan_sha}.json", dict(plan))
                plan["supersedes_plan_sha256"] = old_plan_sha
                plan["in_place_absorbed_plan_shas"] = sorted(set(plan.get("in_place_absorbed_plan_shas") or []) | {old_plan_sha})
            plan["expected_files"] = sorted(set(plan.get("expected_files") or []) | set(extra_files))
            plan.pop("material_drift", None)
            plan.pop("material_drift_causes", None)
            plan["plan_sha256"] = canonical_sha256(plan_payload(plan))
            plan["approval"]["plan_sha256"] = plan["plan_sha256"]
            save_plan(_plan_path(repo, args.task_id), plan)
            if "plan_sha256" in policy:
                policy["plan_sha256"] = plan["plan_sha256"]
            policy["policy_sha256"] = canonical_sha256({key: value for key, value in policy.items() if key != "policy_sha256"})
            drift = [item for item in drift if not item.startswith("file:")]
    if drift:
        plan["material_drift"] = drift
        causes = _drift_causes(repo, manifest, drift, plan)
        plan["material_drift_causes"] = causes
        save_plan(_plan_path(repo, args.task_id), plan)
        remediation_cmd = build_remediation_command(repo, args.task_id, plan, policy, manifest)
        # A live run: the developer re-approved without being told which change pulled in AUTH/BILLING.
        named = [f"{item} (from {', '.join(causes[item])})" if causes.get(item) else str(item) for item in drift]
        raise ValidationError(
            f"PLAN_APPROVAL_REQUIRED: material drift detected: {', '.join(named)}. "
            "Reconciliation and plan approval are required before verification run can begin.\n"
            f"To reconcile, update the plan using:\n{remediation_cmd}\nand obtain developer approval."
        )
    if plan.get("developer_instructions"):
        from project_context import load_developer_instructions_cached, normalize_instruction_record
        active_insts = {
            i["id"]: i
            for i in load_developer_instructions_cached(repo, active_only=True)
            if isinstance(i, dict) and i.get("id")
        }
        for pinned in plan["developer_instructions"]:
            norm_pinned = normalize_instruction_record(pinned) if isinstance(pinned, dict) else pinned
            pid = norm_pinned.get("id")
            cur = active_insts.get(pid)
            cur_sha = cur.get("sha256") if cur else None
            pinned_sha = norm_pinned.get("sha256")
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
    try:
        from self_heal import save_stable_snapshot
        save_stable_snapshot(repo, args.task_id, "verifying", plan=plan, current_run=current)
    except (OSError, ValueError, ImportError, ValidationError):
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
        sublog("Validating delivery manifest, test results, and reviewer evidence...")
        res = verify(
            repo,
            plan_path=_plan_path(repo, args.task_id),
            policy_path=Path(current["policy"]),
            manifest_path=Path(current["manifest"]),
            state_root=state_root(repo),
            run_id=str(current["run_id"]),
        )
        if res.get("status") == "STALE":
            try:
                plan_now = _load_plan(repo, args.task_id)
                blocked_set = set(res.get("blocked_by") or [])
                commit_only_reasons = {
                    "current change_set_sha256 does not match the delivery manifest",
                    "current repository head does not match the delivery manifest",
                }
                if (
                    plan_now.get("status") == "READY_FOR_DELIVERY"
                    and blocked_set
                    and blocked_set <= commit_only_reasons
                ):
                    next_act = resolve_next_action(repo, args.task_id, plan_now)
                    if isinstance(next_act, dict) and next_act.get("code") == "DELIVER":
                        from task_git_lineage import accept_requested_delivery_commit
                        if accept_requested_delivery_commit(repo, args.task_id, plan_now):
                            save_plan(_plan_path(repo, args.task_id), plan_now)
                        res = {
                            "schema_version": 1,
                            "status": "APPROVED",
                            "blocked_by": [],
                            "post_commit_ready_to_deliver": True,
                            "next_action": f"python .agents/harness.py task deliver --repo . --task-id {args.task_id}",
                            "checks": [
                                {
                                    "name": "post_commit_delivery_equivalence",
                                    "status": "PASS",
                                    "detail": "Developer delivery commit matches verified snapshot; ready for task deliver.",
                                }
                            ],
                        }
            except (OSError, ValueError, ImportError, ValidationError):
                pass
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
        try:
            next_act = resolve_next_action(repo, args.task_id, plan)
            if isinstance(next_act, dict) and next_act.get("code") == "COMPLETE_TASK":
                from incident_reporter import record_incident
                record_incident(
                    repo,
                    code="HARNESS_CONTRADICTION",
                    title="task complete blocked while router still returns COMPLETE_TASK",
                    command=f"workflow.py complete --task-id {args.task_id}",
                    error_message="; ".join(result.get("blocked_by") or [str(result.get("status"))]),
                    task_id=args.task_id,
                    task_status=str(plan.get("status") or ""),
                    next_action="COMPLETE_TASK",
                )
        except (OSError, ValueError, ImportError, ValidationError):
            pass
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
    try:
        from self_heal import save_stable_snapshot
        save_stable_snapshot(repo, args.task_id, "ready_for_delivery", plan=plan)
    except (OSError, ValueError, ImportError, ValidationError):
        pass
    return plan


def ship_task(args: argparse.Namespace) -> dict:
    """Compound verification-to-commit-card pipeline: runs verify-steps (including assemble), seals complete when ready, or stops safely at any review/human checkpoint."""
    import contextlib
    import io

    repo = Path(args.repo).resolve()
    tid = str(getattr(args, "task_id", "") or "").strip()
    if not tid:
        active_file = state_root(repo) / "active-task.json"
        if active_file.is_file():
            tid = str(read_json(active_file).get("task_id") or "").strip()
    if not tid:
        raise ValidationError("no active task found; pass --task-id <id>")
    args.task_id = tid
    host = getattr(args, "host", None)
    want_json = bool(getattr(args, "json", False))

    plan = _load_plan(repo, tid)
    cur_status = str(plan.get("status") or "")
    if cur_status == "DELIVERED":
        return {"status": "DELIVERED", "ship_outcome": "ALREADY_DELIVERED", "task_id": tid}
    if cur_status not in {"IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"}:
        raise ValidationError(
            f"TASK_SHIP_INVALID_STATE: `task ship` requires IMPLEMENTING, VERIFYING, or READY_FOR_DELIVERY (current status: {cur_status})."
        )

    steps_report: dict[str, Any] = {}
    if cur_status in {"IMPLEMENTING", "VERIFYING"}:
        from verification_steps import run_steps
        buf = io.StringIO()
        if want_json:
            with contextlib.redirect_stdout(buf):
                rc, steps_report = run_steps(repo, tid, host=host, json_only=True, include_assemble=True)
        else:
            rc, steps_report = run_steps(repo, tid, host=host, json_only=False, include_assemble=True)
        if rc != 0:
            plan_after = _load_plan(repo, tid)
            try:
                fail_act = resolve_next_action(repo, tid, plan_after, host=host)
            except Exception:
                fail_act = {}
            return {
                "status": "BLOCKED",
                "ship_outcome": "VERIFICATION_STEP_FAILED",
                "exit_code": rc,
                "task_id": tid,
                "task_state": plan_after.get("status"),
                "verification_steps": steps_report,
                "next_action": _compact_for_host(fail_act) if isinstance(fail_act, dict) and fail_act else {},
            }

    plan = _load_plan(repo, tid)
    act = resolve_next_action(repo, tid, plan, host=host)
    if plan.get("status") == "VERIFYING" and act.get("code") in {"COMPLETE_TASK", "FINAL_VERIFY"}:
        complete(argparse.Namespace(repo=str(repo), task_id=tid))
        plan = _load_plan(repo, tid)
        act = resolve_next_action(repo, tid, plan, host=host)

    if plan.get("status") == "READY_FOR_DELIVERY":
        if act.get("code") == "DELIVER":
            delivered_plan = deliver_task(
                argparse.Namespace(
                    repo=str(repo),
                    task_id=tid,
                    allow_dirty_tree=False,
                    developer_allow_dirty_tree=False,
                    source=None,
                )
            )
            return {
                "status": "DELIVERED",
                "ship_outcome": "DELIVERED",
                "task_id": tid,
                "delivery_commit_sha": delivered_plan.get("delivery_commit_sha"),
            }
        return {
            "status": "READY_FOR_DELIVERY",
            "ship_outcome": "AWAITING_GIT_COMMIT",
            "task_id": tid,
            "express_track": bool(plan.get("express_track")),
            "suggested_commit": act.get("suggested_commit"),
            "suggested_commit_block": act.get("suggested_commit_block"),
            "dirty_task_files": (act.get("inputs") or {}).get("dirty_task_files") or [],
            "verification_steps": steps_report or None,
            "next_action": _compact_for_host(act),
        }

    return {
        "status": str(plan.get("status") or "VERIFYING"),
        "ship_outcome": "STOPPED_AT_CHECKPOINT",
        "task_id": tid,
        "verification_steps": steps_report or None,
        "next_action": _compact_for_host(act),
    }


@_serialize_task_scope
def cancel(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    plan = _load_plan(repo, args.task_id)
    source = str(getattr(args, "source", None) or "developer_terminal")
    proof = str(getattr(args, "proof_reference", None) or "").strip()
    if source == "conversation" and not proof:
        raise ValidationError("cancel --source conversation needs --proof-reference with the developer's words")
    from debug_instrumentation import strip
    try:
        conflicts = strip(repo, plan)
    except (HarnessError, OSError) as exc:
        conflicts = [str(exc)]
    if conflicts:
        print(f"Debug cleanup requires manual resolution: {conflicts}", file=sys.stderr)
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
    try:
        from execution_mode import pending_task_mode_file
        pend_f = pending_task_mode_file(repo)
        if pend_f.is_file():
            pend_data = read_json(pend_f)
            if str(pend_data.get("intended_task_id") or "") in {"", args.task_id}:
                pend_f.unlink(missing_ok=True)
    except (ImportError, OSError, ValueError, ValidationError):
        pass
    _clear_cancel_request(repo, args.task_id)
    return plan


def _clear_cancel_request(repo: Path, task_id: str) -> None:
    """A lifecycle command that actually ran settles a pending cancel request (the hook's CANCEL_PENDING)."""
    path = state_root(repo) / "cancel-requested.json"
    if path.is_file() and read_json(path).get("task_id") == task_id:
        path.unlink(missing_ok=True)


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
    if state == "IMPLEMENTING" and plan.get("phases"):
        phases = plan.get("phases") or []
        idx = int(plan.get("active_phase_index") or 0)
        if not repo.is_dir() or not (task_dir(repo, task_id) / "phase-state.json").is_file():
            if 0 <= idx < len(phases) and isinstance(phases[idx], dict):
                pid = str(phases[idx].get("id") or f"p{idx + 1}")
                return [{
                    "action": "checkpoint-phase",
                    "code": "CHECKPOINT_PHASE",
                    "kind": "HARNESS_COMMAND",
                    "command": f"{base} checkpoint-phase {identity} --phase-id {pid}",
                    "reason": f"Complete and checkpoint active phase '{pid}'.",
                }]
    try:
        act = resolve_next_action(repo, task_id, plan)
    except HarnessError:
        if state == "IMPLEMENTING":
            return [{
                "action": "prepare-verification",
                "code": "PREPARE_VERIFICATION",
                "kind": "HARNESS_COMMAND",
                "command": f"{base} prepare-verification {identity}",
                "reason": "Prepare verification when implementation is complete.",
            }]
        raise
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
    for k in ("tool", "instructions", "choices", "before_first_dispatch", "reviewer_prompts", "reviewers", "reviewer_models", "briefs", "package_path", "review_execution_profile", "pending_reviewers", "context_rotation"):
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
    plan = dict(_load_plan(repo, task_id))
    try:
        from execution_mode import resolve_effective_execution_mode
        em_info = resolve_effective_execution_mode(repo, task_id=task_id, plan=plan)
        plan["execution_mode"] = {
            "mode": em_info.get("mode"),
            "choice": em_info.get("choice"),
            "scope": em_info.get("effective_scope"),
            **(
                {"conflict_auto_local_override": True}
                if em_info.get("conflict_auto_local_override")
                else {}
            ),
        }
    except (ImportError, OSError, ValueError, ValidationError):
        plan.setdefault("execution_mode", None)
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
                **({"context_rotation": next_act["context_rotation"]} if "context_rotation" in next_act else {}),
            }
        ]
        # Antigravity keeps only the end of long tool output. With the full review briefs inside, the
        # reviewer prompts were cut off and the agent made up brief hashes. The host-facing JSON carries
        # brief paths and one-line prompts only, and ends with the next step and its prompts.
        last = ("task_state", "next_actions", "next_action")
        compact = {key: _compact_for_host(plan[key]) for key in last}
        plan = {**{k: v for k, v in plan.items() if k not in last}, **compact}
        # Strip heavy baseline/history arrays when querying --next so output never balloons to 40,000+ lines
        for heavy_key in (
            "baseline", "task_baseline", "base_file_identities", "base_change_identities",
            "plan_history", "history", "verification_recipes",
        ):
            plan.pop(heavy_key, None)
    try:
        from pre_tool_safety import _detect_live_verification_or_build_owner
        bg_pid = _detect_live_verification_or_build_owner(repo, task_id)
        if bg_pid > 0:
            plan["background_execution_active"] = {
                "pid": bg_pid,
                "instruction": (
                    "Background verification or Gradle build is actively running for this task. "
                    "Do NOT launch overlapping commands or reviewer subagents; wait for background completion."
                ),
            }
    except (ImportError, OSError, ValueError, TypeError, ValidationError):
        pass
    if bool(getattr(args, "brief", False)):
        keys = (
            "task_id",
            "status",
            "plan_sha256",
            "review_rounds",
            "review_calls_used",
            "verification_run_id",
            "background_execution_active",
            "next_action",
        )
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
        choices=(
            "AUTO", "BUG", "FEATURE", "REFACTOR", "CONFLICT", "FIX_CONFLICT", "MERGE",
            "auto", "bug", "feature", "refactor", "conflict", "fix_conflict", "merge",
        ),
        default="AUTO",
        help="Task kind classification: AUTO, BUG, FEATURE, REFACTOR, or CONFLICT (aliases: FIX_CONFLICT, MERGE)",
    )
    command.add_argument(
        "--planning-depth",
        choices=("BOUNDED", "ARCHITECTURAL", "bounded", "architectural"),
        default=None if is_revision else "BOUNDED",
        help="Planning depth scope: BOUNDED (default) or ARCHITECTURAL; revise keeps the plan's depth when omitted",
    )
    command.add_argument(
        "--expected-surfaces",
        nargs="+",
        action="extend",
        default=None,
        help="Expected surfaces (comma- or space-separated, or repeatable)",
    )
    command.add_argument(
        "--expected-modules",
        nargs="+",
        action="extend",
        default=None,
        help="Expected modules (comma- or space-separated, or repeatable)",
    )
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
    command.add_argument(
        "--expected-files",
        "--files",
        dest="expected_files",
        nargs="+",
        action="extend",
        default=None,
        help="Expected target files (comma- or space-separated, or repeatable)",
    )
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


def cmd_plan_check(args: argparse.Namespace) -> dict:
    """Read-only readiness, YAGNI reuse, file grounding, and module DAG audit for a task plan."""
    from _workflow.planning import _discover_reuse_candidates, _evaluate_plan_readiness

    repo = Path(args.repo).resolve()
    tid = str(getattr(args, "task_id", "") or "").strip()
    if not tid:
        active_file = state_root(repo) / "active-task.json"
        if active_file.is_file():
            try:
                tid = str(read_json(active_file).get("task_id") or "").strip()
            except (OSError, ValueError, ValidationError):
                tid = ""
    if not tid:
        raise ValidationError("no active task found; pass --task-id <id>")
    plan = _load_plan(repo, tid)
    directory = task_dir(repo, tid)
    policy_file = directory / "preliminary-policy.json"
    policy: dict[str, Any] = {}
    current_file = directory / "current-run.json"
    if current_file.is_file():
        try:
            cur_pol_raw = str(read_json(current_file).get("policy") or "").strip()
            if cur_pol_raw:
                cur_pol = Path(cur_pol_raw)
                if not cur_pol.is_absolute():
                    cur_pol = (repo / cur_pol).resolve()
                if cur_pol.is_file():
                    policy = read_json(cur_pol)
        except (OSError, ValueError, ValidationError):
            policy = {}
    if not policy and policy_file.is_file():
        try:
            policy = read_json(policy_file)
        except (OSError, ValueError, ValidationError):
            policy = {}
    if not policy:
        fallback_tier = str(
            (plan.get("readiness_assessment") or {}).get("risk_tier")
            or plan.get("risk_tier")
            or "T1_LOW_RISK"
        )
        policy = {"risk_tier": fallback_tier}

    all_files: list[str] = list(plan.get("expected_files") or [])
    for phase in plan.get("phases") or []:
        if isinstance(phase, dict):
            for f in phase.get("expected_files") or []:
                if f not in all_files:
                    all_files.append(f)

    existing_files: list[str] = []
    new_files: list[str] = []
    for rel in all_files:
        rel_norm = str(rel).replace("\\", "/").strip("/")
        if not rel_norm:
            continue
        if (repo / rel_norm).exists():
            existing_files.append(rel_norm)
        else:
            new_files.append(rel_norm)

    reuse_cands = _discover_reuse_candidates(repo, all_files)
    plan_for_eval = dict(plan)
    plan_for_eval["reuse_candidates"] = reuse_cands
    readiness = _evaluate_plan_readiness(plan_for_eval, policy, repo=repo)
    return {
        "status": readiness["status"],
        "readiness_status": readiness["status"],
        "task_id": tid,
        "task_state": plan.get("status"),
        "planning_depth": readiness["planning_depth"],
        "risk_tier": readiness["risk_tier"],
        "existing_files": existing_files,
        "new_files": new_files,
        "reuse_candidates": reuse_cands,
        "path_grounding_warnings": readiness.get("path_grounding_warnings", []),
        "phase_dag_warnings": readiness.get("phase_dag_warnings", []),
        "advisories": readiness.get("advisories", []),
        "readiness_assessment": readiness,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    common.add_argument("--task-id", "--task", dest="task_id", required=True)
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
    draft_cmd.add_argument(
        "--adopt-dirty",
        action="store_true",
        help="Adopt pre-existing uncommitted WIP edits in expected_files into this task's delta rather than isolating them in task-baseline.json",
    )
    draft_cmd.add_argument(
        "--with-context",
        action="store_true",
        help="Resolve graph task-context (including DI-bound implementations, read_ranges, and candidate tests) and publish DiscoveryReceipt in the same call",
    )
    draft_cmd.set_defaults(handler=draft)
    qs_cmd = sub.add_parser(
        "quick-start",
        help="Single-command Express Track for direct developer requests on bounded 1-2 file T0/T1 micro-tasks (falls back to AWAITING_DEVELOPER_APPROVAL if ineligible)",
    )
    qs_cmd.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    qs_cmd.add_argument("--task-id", "--task", dest="task_id", default="", help="Optional task ID (auto-generated from outcome/files when omitted)")
    _add_plan_arguments(qs_cmd, is_revision=False)
    qs_cmd.add_argument(
        "--adopt-dirty",
        action="store_true",
        help="Adopt pre-existing uncommitted WIP edits in expected_files into this task's delta",
    )
    qs_cmd.add_argument("--source", choices=("host_native", "conversation", "developer_terminal"), required=True)
    qs_cmd.add_argument("--proof-reference", required=True, help="Exact developer words requesting this bounded change")
    qs_cmd.add_argument("--enforcement-tier", choices=("HARD_ENFORCED", "RULE_ENFORCED"), default="RULE_ENFORCED")
    qs_cmd.set_defaults(handler=quick_start)
    revise_cmd = sub.add_parser("revise", parents=[common])
    _add_plan_arguments(revise_cmd, is_revision=True)
    revise_cmd.add_argument("--material-change-reason", help="Concrete requirement expansion when revising only approved plan prose")
    revise_cmd.add_argument(
        "--restore-cancelled",
        action="store_true",
        help="Reactivate a CANCELLED task's lossless plan.json back to AWAITING_DEVELOPER_APPROVAL with fresh baseline and hash",
    )
    revise_cmd.set_defaults(handler=revise)
    from plan_notes import register_parser as register_plan_notes
    register_plan_notes(sub, common)
    command = sub.add_parser("checkpoint-phase", parents=[common])
    command.add_argument("--phase-id", default=None, help="Phase ID to checkpoint")
    command.add_argument(
        "--advance-all-ready",
        action="store_true",
        help="When subsequent phases already have all expected files materialized at the verified snapshot (and no phase review is required), advance and checkpoint them in one pass",
    )
    command.add_argument(
        "--defer-gradle-to-final",
        action="store_true",
        help="Run fast deterministic phase checks and defer Gradle compile/unit-test execution to the immediate final verification pass when no scoped phase review is required",
    )
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
    command.add_argument(
        "--with-delegation",
        action="store_true",
        help="Compute and attach the delegate-plan execution brief in the same approval call to eliminate a separate post-approval CLI roundtrip",
    )
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
    ship_cmd = sub.add_parser(
        "ship",
        help="Run verification steps (including assemble), seal task complete to READY_FOR_DELIVERY when ready, or seal deliver after git commit",
    )
    ship_cmd.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    ship_cmd.add_argument("--task-id", "--task", dest="task_id", default="", help="Task ID (defaults to focused active task if omitted)")
    ship_cmd.add_argument("--host", default=None, help="Host environment for reviewer/router resolution")
    ship_cmd.set_defaults(handler=ship_task)
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
    status_cmd.add_argument("--task-id", "--task", dest="task_id", default="", help="Task ID (defaults to active task if omitted)")
    status_cmd.add_argument("--next", action="store_true", help="Include the safest next lifecycle command without executing it")
    status_cmd.add_argument("--brief", action="store_true", help="Show lifecycle identity, spending and the exact next action without repeating the full plan")
    status_cmd.add_argument("--host", default=None, help="Host running this task; binds routed review commands")
    status_cmd.set_defaults(handler=status)
    command = sub.add_parser("recover-stale")
    command.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    command.add_argument("--task-id", "--task", dest="task_id", default="")
    command.set_defaults(handler=recover_stale)
    command = sub.add_parser("switch", help="Focus a live task without changing its approval or verification state")
    command.add_argument("--repo", default=".")
    command.add_argument("--task-id", "--task", dest="task_id", required=True)
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
    command.add_argument("--task-id", "--task", dest="task_id", required=True, help="Task ID to restore as active task")
    command.set_defaults(handler=recover_active)
    heal_cmd = sub.add_parser("heal", help="Self-heal a stale or corrupted task state back to the nearest valid stable step")
    heal_cmd.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    heal_cmd.add_argument("--task-id", "--task", dest="task_id", default="", help="Task ID (defaults to active task if omitted)")
    heal_cmd.add_argument("--reason", default="", help="Reason for self-healing rollback")
    heal_cmd.add_argument("--prepare-fresh-run", action="store_true", help="Immediately prepare a fresh delta verification run after healing")
    heal_cmd.add_argument("--host", default=None, help="Host environment when preparing a fresh verification run")
    heal_cmd.set_defaults(handler=cmd_heal_task)
    plan_check_cmd = sub.add_parser("plan-check", help="Audit a task plan for Zero-Decision readiness, file grounding, YAGNI reuse candidates, and phase module DAG order")
    plan_check_cmd.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    plan_check_cmd.add_argument("--task-id", "--task", dest="task_id", default="", help="Task ID (defaults to active task if omitted)")
    plan_check_cmd.set_defaults(handler=cmd_plan_check)
    from task_bridge import cmd_task_bridge
    bridge_cmd = sub.add_parser("bridge", help="Save, load, inspect, or snooze a Smart Context Rotation & Task-to-Task Context Bridge")
    bridge_cmd.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    bridge_cmd.add_argument("--task-id", "--task", dest="task_id", default="", help="Task ID (defaults to active or most recently delivered task)")
    bridge_cmd.add_argument("--bridge-id", default="", help="Specific bridge ID when loading or clearing from a multi-bridge queue")
    bridge_cmd.add_argument("--save", action="store_true", help="Save a context bridge artifact for a new conversation")
    bridge_cmd.add_argument("--load", action="store_true", help="Load the saved context bridge in a new conversation (default action)")
    bridge_cmd.add_argument("--clear", action="store_true", help="Clear the active task-bridge.json while keeping bridge-history archived")
    bridge_cmd.add_argument("--all", action="store_true", help="With --clear, clear all pending bridges in the queue")
    bridge_cmd.add_argument("--status", action="store_true", help="Inspect conversation bloat metrics, rotation advisory, and saved bridge status")
    bridge_cmd.add_argument("--snooze", action="store_true", help="Snooze context rotation advisories for the current conversation")
    bridge_cmd.add_argument("--snooze-steps", type=int, default=120, help="Number of additional steps before recommending rotation again (default: 120)")
    bridge_cmd.add_argument("--mode", choices=("auto", "follow-up", "mid-task", "FOLLOW_UP_TASK", "MID_TASK_HANDOFF"), default="auto", help="Bridge mode: auto (default), follow-up, or mid-task")
    bridge_cmd.add_argument("--next-outcome", default="", help="Follow-up task outcome or request to carry into the new conversation")
    bridge_cmd.add_argument("--summary", default="", help="Concise summary of architectural decisions and task context")
    bridge_cmd.add_argument(
        "--expected-files",
        "--files",
        dest="expected_files",
        nargs="+",
        action="extend",
        default=None,
        help="Target files (comma- or space-separated, or repeatable) to seed into the bridged Discovery Receipt",
    )
    bridge_cmd.add_argument("--host", default=None, help="Host environment (antigravity or generic)")
    bridge_cmd.set_defaults(handler=cmd_task_bridge)
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


_COMPILED_SUFFIXES = (".kt", ".kts", ".java", ".xml", ".aidl")


QUESTION_FORMAT = (
    "a short bold heading, then one bullet per line starting with a bold label (what changes broken into 2-4 concise "
    "1-line functional sub-bullets without low-level XML/ID walls, phases & file count, sensitive areas or outside writes "
    "only when present, and 2-3 concise phone check steps; omit internal CLI flags or raw 17-digit tracker IDs); "
    "numbered sub-steps for phone checks; no emoji. "
    "Translate all headings, labels, link text, and ask_question options into the developer's active conversation language "
    "(never hardcode a fixed language). "
    "For a right-to-left language, start every line with a word in that language (including every bullet, markdown link "
    "label `[...](...)`, and ask_question option; never start a line, link label, or option with a code name, English word, "
    "or backtick, which flips dir='auto' to LTR), and put every code name, file name, value and English term in backticks "
    "so it keeps its place in the sentence."
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


_DIFF_FIELDS = (
    ("expected_surfaces", "Surfaces"), ("expected_files", "Files"), ("expected_modules", "Modules"),
    ("external_writes", "External writes"), ("skills", "Skills"), ("risks", "Risks"),
)
_TEXT_FIELDS = (
    ("requested_outcome", "Outcome"), ("approach", "Approach"), ("device_strategy", "Phone checks"),
    ("test_strategy", "Tests"),
)


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
        if args.action == "ship" and not getattr(args, "task_id", ""):
            act_f = state_root(Path(args.repo).resolve()) / "active-task.json"
            if act_f.is_file():
                args.task_id = str(read_json(act_f).get("task_id") or "").strip()
        if args.action not in {"continue", "bridge", "status", "coverage", "metrics", "draft", "quick-start", "recover-stale", "merge", "heal", "plan-check"}:
            from host_continuation import assert_execution_session
            assert_execution_session(Path(args.repo).resolve(), args.task_id)
        if args.action in {"continue", "merge", "bridge", "prepare-verification", "quick-start"} and args.json:
            import contextlib
            with contextlib.redirect_stdout(sys.stderr):
                result = args.handler(args)
        else:
            result = args.handler(args)
        if args.action in ("approve", "quick-start") and result.get("status") == "IMPLEMENTING":
            from review_sources import detected_current_host
            from host_continuation import continue_task, load_session
            current_host = detected_current_host()
            repo = Path(args.repo).resolve()
            bound_tid = str(result.get("task_id") or args.task_id)
            if current_host and bound_tid and load_session(repo, bound_tid) is None:
                import contextlib
                with contextlib.redirect_stdout(sys.stderr):
                    continue_task(argparse.Namespace(repo=str(repo), task_id=bound_tid, host=current_host,
                                                     source_stopped=False, expect_session=None))
    except (ValidationError, OSError) as exc:
        if args.action == "bridge" and getattr(args, "json", False):
            message = str(exc)
            code = message.split(":", 1)[0] if message.startswith("TASK_BRIDGE_") else "TASK_BRIDGE_FAILED"
            print(json.dumps({"status": "BLOCKED", "code": code, "reason": message}, ensure_ascii=False, indent=2))
            return 1
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
    except Exception as exc:
        import traceback
        tb_text = traceback.format_exc()
        repo_path = Path(getattr(args, "repo", ".") or ".").resolve()
        t_id = str(getattr(args, "task_id", "") or "")
        t_state = ""
        try:
            if t_id:
                t_state = str(_load_plan(repo_path, t_id).get("status") or "")
        except (OSError, ValueError, ValidationError):
            t_state = ""
        try:
            from incident_reporter import record_incident
            inc = record_incident(
                repo_path,
                code="UNEXPECTED_EXCEPTION",
                command=f"workflow.py {getattr(args, 'action', '')}",
                message=f"{type(exc).__name__}: {exc}",
                task_id=t_id,
                task_state=t_state,
                traceback_text=tb_text,
            )
            inc_id = inc.get("incident_id", "")
            guidance = inc.get("ask_question_guidance") or {}
            sub = inc.get("submission") or {}
            print(f"[FAIL] Unexpected harness exception ({type(exc).__name__}: {exc})", file=sys.stderr)
            print(f"INCIDENT_RECORDED={inc_id}", file=sys.stderr)
            print(f"INCIDENT_LOCAL_REPORT=.agents/state/incidents/{inc_id}.md", file=sys.stderr)
            if sub.get("status") in {"REPORTED", "DEDUPLICATED_EXISTING_ISSUE"}:
                print(f"INCIDENT_AUTO_SUBMITTED={sub.get('issue_url', '')}", file=sys.stderr)
            elif guidance:
                print("TOOL_CALL_REQUIRED=ask_question", file=sys.stderr)
                print(f"INCIDENT_SUBMIT_ONCE={guidance.get('submit_once_command', '')}", file=sys.stderr)
                print(f"INCIDENT_SUBMIT_ALWAYS={guidance.get('submit_always_command', '')}", file=sys.stderr)
                print(f"NEXT_INSTRUCTIONS={guidance.get('instructions', '')}", file=sys.stderr)
        except Exception:
            print(tb_text, file=sys.stderr)
        return 1
    if args.action == "prepare-verification":
        if args.json:
            print(json.dumps(_compact_plan_json_for_cli_stdout(result) if isinstance(result, dict) else result, ensure_ascii=False, indent=2))
        else:
            print(f"HARNESS_RUN_ID={result['run_id']}")
            print(f"HARNESS_DELIVERY_SNAPSHOT={result['delivery_snapshot_sha256']}")
            if result.get("verification_recipes"):
                print("VERIFICATION_RECIPES:")
                for recipe in result["verification_recipes"]:
                    print(f"  [{recipe['surface']}]:")
                    for step in recipe["steps"]:
                        print(f"    - {step}")
    elif args.action in ("change-decision", "plan-note", "heal"):
        print(json.dumps(_compact_plan_json_for_cli_stdout(result) if isinstance(result, dict) else result, ensure_ascii=False, indent=2))
    elif args.action == "plan-check":
        if args.json:
            print(json.dumps(_compact_plan_json_for_cli_stdout(result) if isinstance(result, dict) else result, ensure_ascii=False, indent=2))
        else:
            print(f"PLAN_READINESS_STATUS={result.get('status', 'READY')}")
            print(f"TASK_ID={result.get('task_id')} ({result.get('planning_depth')}, {result.get('risk_tier')})")
            print(f"EXISTING_FILES={len(result.get('existing_files') or [])} NEW_FILES={len(result.get('new_files') or [])}")
            for adv in (result.get("readiness_assessment") or {}).get("advisories") or []:
                print(f"ADVISORY: {adv}")
        return 0
    elif args.action == "bridge":
        if args.json:
            print(json.dumps(_compact_plan_json_for_cli_stdout(result) if isinstance(result, dict) else result, ensure_ascii=False, indent=2))
        else:
            b_status = str(result.get("status") or "READY")
            print(f"TASK_STATUS={b_status}")
            if result.get("bridge_id"):
                print(f"BRIDGE_ID={result['bridge_id']} MODE={result.get('mode', '')}")
            if b_status == "BRIDGE_SAVED":
                print(f"BRIDGE_SHA256={result.get('bridge_sha256', '')}")
                print(f"NEW_CHAT_COMMAND={result.get('new_chat_command', 'python .agents/harness.py task bridge')}")
                print(f"CLEAR_COMMAND={result.get('clear_command', 'python .agents/harness.py task bridge --clear')}")
                print(f"NEW_CHAT_PROMPT={result.get('new_chat_prompt', '')}")
                if result.get("optional_notice"):
                    print(f"OPTIONAL_NOTICE={result.get('optional_notice')}")
                if result.get("handoff_card"):
                    print(result["handoff_card"])
            elif b_status == "BRIDGE_CLEARED":
                print(f"ARCHIVED_IN_HISTORY={result.get('archived_in_history', False)}")
                print(f"REMAINING_BRIDGES={result.get('remaining_count', 0)}")
            elif b_status == "MULTIPLE_BRIDGES_PENDING":
                print(f"PENDING_BRIDGES_COUNT={result.get('pending_bridges_count', 0)}")
                for pb in result.get("pending_bridges") or []:
                    print(f"PENDING_BRIDGE={pb.get('bridge_id')} TASK={pb.get('task_id')} MODE={pb.get('mode')} LOAD={pb.get('load_command')}")
                upcoming = result.get("next_action") or {}
                if upcoming.get("code"):
                    print(f"NEXT_ACTION={upcoming.get('code')}: {upcoming.get('command') or ''}")
                    print(f"NEXT_REASON={upcoming.get('reason') or ''}")
                    if upcoming.get("instructions"):
                        print(f"NEXT_INSTRUCTIONS={upcoming.get('instructions')}")
            elif b_status in ("BRIDGE_LOADED", "BRIDGE_CONTINUED"):
                if result.get("session_id"):
                    print(f"HOST_EXECUTOR={result.get('host')} SESSION={result.get('session_id')} ENFORCEMENT={result.get('enforcement_tier')}")
                disc = result.get("discovery_receipt") or {}
                if disc.get("id"):
                    print(f"DISCOVERY_RECEIPT={disc.get('id')} FILES={len(disc.get('resolved_paths') or [])}")
                prev = result.get("previous_task") or {}
                idelta = prev.get("interface_delta") or []
                if idelta:
                    print(f"INTERFACE_DELTA_FILES={len(idelta)}")
                if result.get("context_summary"):
                    print(f"CONTEXT_SUMMARY={result.get('context_summary')}")
                if result.get("next_outcome"):
                    print(f"NEXT_OUTCOME={result.get('next_outcome')}")
                if result.get("suggested_draft_command"):
                    print(f"SUGGESTED_DRAFT_COMMAND={result.get('suggested_draft_command')}")
                upcoming = result.get("next_action") or {}
                if upcoming.get("code"):
                    print(f"NEXT_ACTION={upcoming.get('code')}: {upcoming.get('command') or ''}")
                    print(f"NEXT_REASON={upcoming.get('reason') or ''}")
            elif b_status == "ROTATION_SNOOZED":
                print(f"SNOOZED_UNTIL_STEPS={result.get('snooze_until_steps')}")
            else:
                health = result.get("conversation_health") or {}
                print(f"CONVERSATION_STEPS={health.get('steps', 0)} EST_TOKENS={health.get('estimated_context_tokens', 0)}")
                rot = result.get("context_rotation")
                if isinstance(rot, dict) and rot.get("recommended"):
                    print(f"CONTEXT_ROTATION_RECOMMENDED={rot.get('mode')}: {rot.get('save_command')}")
                    print(f"CONTEXT_ROTATION_REASON={rot.get('reason')}")
                    if rot.get("instructions"):
                        print(f"CONTEXT_ROTATION_INSTRUCTIONS={rot.get('instructions')}")
        return 0
    elif args.action == "debug-evidence":
        print(f"DEBUG_EVIDENCE_RECORDED={len(result.get('entries', []))}")
    elif args.action == "validate-finding":
        print(f"FINDING_VALIDATION_RECORDED={len(result.get('validations', []))}")
    elif args.action == "verify":
        print(json.dumps(_compact_plan_json_for_cli_stdout(result) if isinstance(result, dict) else result, ensure_ascii=False, indent=2))
    elif args.action == "reconcile-delivery":
        if args.json:
            print(json.dumps(_compact_plan_json_for_cli_stdout(result) if isinstance(result, dict) else result, ensure_ascii=False, indent=2))
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
    elif args.action == "ship":
        if args.json:
            print(json.dumps(_compact_plan_json_for_cli_stdout(result) if isinstance(result, dict) else result, ensure_ascii=False, indent=2))
        else:
            print(f"TASK_STATUS={result.get('status', 'READY')}")
            print(f"SHIP_OUTCOME={result.get('ship_outcome', '')}")
            if result.get("suggested_commit"):
                print(f"SUGGESTED_COMMIT={result['suggested_commit']}")
            nxt = result.get("next_action") or {}
            if nxt.get("code"):
                cmd_s = nxt.get("command") or ("invoke ask_question tool in this turn (DEVELOPER_ACTION)" if nxt.get("tool") == "ask_question" else "")
                print(f"NEXT_ACTION={nxt['code']}: {cmd_s}")
                if nxt.get("reason"):
                    print(f"NEXT_REASON={nxt['reason']}")
                if nxt.get("instructions") and (nxt.get("tool") == "ask_question" or nxt.get("kind") == "DEVELOPER_ACTION"):
                    print(f"NEXT_INSTRUCTIONS={nxt['instructions']}")
                if nxt.get("code") in {"DISPATCH_REVIEWERS", "DISPATCH_PHASE_REVIEWERS"} and nxt.get("inputs"):
                    print("NEXT_ACTION_INPUTS=" + json.dumps(nxt["inputs"], ensure_ascii=False))
        return int(result.get("exit_code") or (1 if result.get("status") == "BLOCKED" else 0))
    elif args.json:
        if args.action in ("draft", "revise") or (args.action == "quick-start" and result.get("status") == "AWAITING_DEVELOPER_APPROVAL") or (args.action == "merge" and args.apply):
            # A live run passed --json to draft and revise and got none of this, so the agent wrote the
            # approval question itself (no Cancel option, no files).
            lines = approval_material_lines(Path(args.repo).resolve(), result, args.action)
            result = {**result, "approval_material": "\n".join(lines)}
        if isinstance(result, dict):
            result = _compact_plan_json_for_cli_stdout(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.action == "merge" and not args.apply:
            print(result["plan_summary"])
            print(f"MERGE_PREVIEW_SHA256={result['merge_preview_sha256']}")
            for consequence in result["consequences"]:
                print(consequence)
            print("NEXT_ACTION=CONFIRM_PLAN_MERGE: present the preview and wait for the developer's merge choice.")
        if args.action in ("draft", "revise") or (args.action == "quick-start" and result.get("status") == "AWAITING_DEVELOPER_APPROVAL") or (args.action == "merge" and args.apply):
            if args.action == "quick-start" and result.get("express_fallback_reason"):
                print(f"EXPRESS_FALLBACK_REASON={result['express_fallback_reason']}")
            inline_ctx = result.get("inline_task_context") if isinstance(result, dict) else None
            if isinstance(inline_ctx, dict):
                if inline_ctx.get("bound_implementations"):
                    print("CONTEXT_BOUND_IMPLEMENTATIONS=" + ",".join(str(x) for x in inline_ctx["bound_implementations"]))
                if inline_ctx.get("candidate_tests"):
                    print("CONTEXT_CANDIDATE_TESTS=" + ",".join(str(x) for x in inline_ctx["candidate_tests"]))
                for rng in inline_ctx.get("read_ranges") or []:
                    print(f"CONTEXT_READ_RANGE={rng}")
            for line in approval_material_lines(Path(args.repo).resolve(), result, "draft" if args.action == "quick-start" else args.action):
                print(line)
        if args.action in ("approve", "quick-start") and result.get("status") == "IMPLEMENTING":
            print(f"TASK_ID={result.get('task_id')}")
            if result.get("express_track"):
                print(f"EXPRESS_TRACK=true RISK_TIER={result.get('express_risk_tier', 'T1_LOW_RISK')}")
            print(f"APPROVED_PLAN_HASH={str(result.get('plan_sha256') or '')[:12]}")
            del_brief = result.get("delegation_brief") if isinstance(result, dict) else None
            if isinstance(del_brief, dict):
                print("DELEGATION_BRIEF=" + json.dumps(del_brief, ensure_ascii=False))
        print(f"TASK_STATUS={result.get('status', 'READY')}")
        if args.action == "checkpoint-phase" and result.get("auto_advanced_phases"):
            print("AUTO_ADVANCED_PHASES=" + ",".join(str(x) for x in result["auto_advanced_phases"]))
            try:
                _nxt_cp = resolve_next_action(Path(args.repo).resolve(), str(args.task_id))
                if _nxt_cp.get("code") == "PREPARE_VERIFICATION":
                    print(
                        f"NEXT_ACTION=VERIFY_STEPS: python .agents/harness.py verify-steps --task-id {args.task_id} --host antigravity"
                    )
                elif _nxt_cp.get("code") and _nxt_cp.get("command"):
                    print(f"NEXT_ACTION={_nxt_cp['code']}: {_nxt_cp['command']}")
            except (OSError, ValueError, KeyError, TypeError, ValidationError):
                _nxt_cp = {}
        if args.action in ("approve", "quick-start") and result.get("status") == "IMPLEMENTING" and result.get("task_id"):
            # Real app: approve printed only the status, the agent started editing, and the test record
            # the router asks for before the first edit never happened; an old failing test in another
            # feature then stopped verification and cost two approvals.
            _repo_resolved = Path(args.repo).resolve()
            _tid_str = str(result["task_id"])
            try:
                upcoming = resolve_next_action(_repo_resolved, _tid_str, result)
            except Exception:
                upcoming = {}
            _pre_web_pack_cmd = ""
            try:
                from execution_mode import inspect_web_phase_progress, resolve_effective_execution_mode
                _em_app = resolve_effective_execution_mode(_repo_resolved, task_id=_tid_str, plan=result)
                if _em_app.get("mode") == "web" and not _em_app.get("conflict_auto_local_override"):
                    _wp_app = inspect_web_phase_progress(_repo_resolved, result)
                    if not _wp_app.get("has_applied_web_changes"):
                        _pre_web_pack_cmd = f"python .agents/harness.py web-pack --task-id {_tid_str}"
            except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
                _pre_web_pack_cmd = ""
            if _pre_web_pack_cmd:
                print(f"NEXT_ACTION=WEB_RELAY_PACK: {_pre_web_pack_cmd}")
                print(
                    "NEXT_REASON=Web execution mode is active; build the Web-Relay Context Pack first "
                    "(co-authored BUG regression tests are validated automatically on web-apply and verify-steps)."
                )
            else:
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
            if item.get("instructions") and (item.get("tool") == "ask_question" or item.get("kind") == "DEVELOPER_ACTION"):
                print(f"NEXT_INSTRUCTIONS={item.get('instructions')}")
            rot = item.get("context_rotation")
            if isinstance(rot, dict) and rot.get("recommended"):
                print(f"CONTEXT_ROTATION_RECOMMENDED={rot.get('mode')}: {rot.get('save_command')}")
                print(f"CONTEXT_ROTATION_REASON={rot.get('reason')}")
                if rot.get("instructions"):
                    print(f"CONTEXT_ROTATION_INSTRUCTIONS={rot.get('instructions')}")
            if item.get("code") in {"DISPATCH_REVIEWERS", "DISPATCH_PHASE_REVIEWERS"}:
                # Preserve the router's exact payload once, including current briefs.
                print("NEXT_ACTION_INPUTS=" + json.dumps(item.get("inputs", {}), ensure_ascii=False))
        if args.action in ("deliver", "begin-next-phase"):
            try:
                from task_bridge import evaluate_rotation_advisory
                ck = "FOLLOW_UP_BOUNDARY" if args.action == "deliver" else "MID_TASK_CHECKPOINT"
                rot_adv = evaluate_rotation_advisory(Path(args.repo).resolve(), ck, task_id=str(getattr(args, "task_id", "") or ""), plan=result if isinstance(result, dict) else None)
                if rot_adv:
                    print(f"CONTEXT_ROTATION_RECOMMENDED={rot_adv.get('mode')}: {rot_adv.get('save_command')}")
                    print(f"CONTEXT_ROTATION_REASON={rot_adv.get('reason')}")
                    if rot_adv.get("instructions"):
                        print(f"CONTEXT_ROTATION_INSTRUCTIONS={rot_adv.get('instructions')}")
            except (ImportError, OSError, ValueError, ValidationError):
                pass
    if args.action in ("draft", "quick-start", "revise", "recover-active", "reconcile-delivery"):
        return 0 if result.get("status") not in ("BLOCKED", "STALE", "USER_DECISION_REQUIRED") else 1
    return 0 if result.get("status") not in ("BLOCKED", "STALE", "PLAN_APPROVAL_REQUIRED", "USER_DECISION_REQUIRED") else 1



from .phase_checkpoints import (
    CheckpointStatus,
    resolve_phase_modules,
    resolve_module_gradle_task,
    check_phase_compile,
    new_kotlin_lint_issues,
    _is_non_code_resource_or_schema_path,
    _phase_module_skips_unit_tests,
    _has_prerecorded_phase_test_pass,
    check_phase_tests,
    _safe_phase_failure_excerpt,
    _compact_plan_json_for_cli_stdout,
    checkpoint_phase,
    all_remaining_phases_ready_for_final,
    validated_completed_phase_manifest,
    begin_next_phase,
)
from .delivery_ops import (
    recover_stale,
    resume,
    _ready_external_inputs_changed,
    _resume_locked,
    finalize_ready_delivery,
    reconcile_delivery,
    cmd_reconcile_delivery,
    cmd_heal_task,
    installed_harness_version,
    verification_engine_freshness,
    verification_freshness,
    assert_active_run_fresh,
    deliver_task,
    plan_summary,
    _drift_causes,
    _should_record_task_start,
    _compile_check_hint,
    _task_has_changes,
    _task_has_production_changes,
    _task_was_approved_before,
    pre_existing_changes_line,
    approval_brief,
    _names,
    revision_changes,
    changed_since_verification,
    _fix_delta,
    _outcome_confirmed_sensitive_surfaces,
    _with_planned_file_surfaces,
    _planned_file_surfaces,
    sensitive_planned_files_line,
    approval_material_lines,
)

if __name__ == "__main__":
    raise SystemExit(main())
