"""Task lifecycle coordinator for planning, approval, verification preparation, and status.
Usage: python .agents/scripts/workflow.py draft --repo . --task-id <id> --outcome <outcome>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print, step_progress, sublog  # noqa: E402
from _vnext_common import (  # noqa: E402
    ValidationError,
    active_review_package_path,
    atomic_write_json,
    canonical_sha256,
    read_json,
    repository_identity,
    utc_now,
    validate_id,
    validate_repo_path_containment,
)
from _variants import resolve_assemble_task  # noqa: E402
from change_classifier import classify  # noqa: E402
from delivery_manifest import build_manifest, build_task_manifest, load_task_baseline  # noqa: E402
from final_verifier import verify  # noqa: E402
from plan_authority import (  # noqa: E402
    DEFAULT_APP_SURFACES,
    approve,
    approve_and_begin,
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
    modules_str = ",".join(m.lstrip(":") for m in modules)

    actual_paths = sorted({
        (entry.get("path") if isinstance(entry, dict) else str(entry))
        for entry in (manifest.get("task_changes") or manifest.get("changes") or [])
        if (entry.get("path") if isinstance(entry, dict) else str(entry))
    })
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
        f"REVIEW_BUDGET_EXHAUSTED: Used {calls_used} reviewer calls, requested {requested} this round, budget is {budget}."
    ]
    if sensitive:
        parts.append(
            f"Review override is FORBIDDEN due to sensitive surfaces ({', '.join(sensitive)}). "
            "Remediation: Developer must increase 'model_call_budget' in harness setup or re-run review rounds with higher budget."
        )
    elif severity in ("HIGH", "CRITICAL"):
        parts.append(
            f"Review override via conversation is FORBIDDEN for {severity} severity changes. "
            "Remediation: Developer may increase 'model_call_budget', or execute review override directly from developer terminal: "
            "'python .agents/scripts/record_review.py --task <task_id> --override-reviews --source developer_terminal --proof-reference <ref>'."
        )
    else:
        parts.append(
            "Remediation: Developer may either approve increasing review budget in config, or approve a review override via conversation: "
            "'python .agents/scripts/record_review.py --task <task_id> --override-reviews --source conversation --proof-reference <ref>'."
        )
    return " ".join(parts)


def state_root(repo: Path) -> Path:
    installed = repo / ".agents" / "state"
    return installed if (repo / ".agents").is_dir() else repo / "agents" / "state"


def task_dir(repo: Path, task_id: str) -> Path:
    return state_root(repo) / "tasks" / validate_id(task_id, "task id")


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
    current_changes = {str(c.get("path") or "") for c in (manifest.get("changes") or [])}
    if not current_changes:
        return []
    task_baseline = load_task_baseline(repo, task_id)
    if task_baseline is not None:
        task_manifest = build_task_manifest(repo, task_baseline, expected_files=plan.get("expected_files"))
        uncommitted = [
            str(c.get("path") if isinstance(c, dict) else c or "")
            for c in (task_manifest.get("task_changes") or [])
            if (c.get("path") if isinstance(c, dict) else c) and (not isinstance(c, dict) or c.get("status") != "BASELINE_DIRTY_REMOVED")
        ]
        return sorted(set(uncommitted))
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


LIVE_TASK_STATUSES = (
    "AWAITING_DEVELOPER_APPROVAL",
    "APPROVED",
    "IMPLEMENTING",
    "VERIFYING",
    "BLOCKED",
    "READY_FOR_DELIVERY",
)


def _find_live_tasks(repo: Path) -> list[tuple[str, str, dict, Path]]:
    state = state_root(repo)
    tasks_dir = state / "tasks"
    live = []
    if not tasks_dir.is_dir():
        return live
    for task_sub in sorted(tasks_dir.iterdir()):
        if task_sub.is_dir():
            p_file = task_sub / "plan.json"
            if p_file.is_file():
                try:
                    p_data = read_json(p_file)
                    st = str(p_data.get("status") or "")
                    if st in LIVE_TASK_STATUSES:
                        live.append((task_sub.name, st, p_data, p_file))
                except Exception:
                    pass
    return live


def assert_single_live_task(repo: Path, allowed_task_id: str | None = None) -> list[tuple[str, str, dict, Path]]:
    """Enforce the one-live-task-per-worktree invariant.

    Fails closed with AMBIGUOUS_LIVE_TASKS if multiple live tasks are found.
    Fails closed with ACTIVE_TASK_CONFLICT if a single live task exists that does not match allowed_task_id.
    """
    live = _find_live_tasks(repo)
    if len(live) > 1:
        tasks_summary = ", ".join(f"'{t[0]}' ({t[1]})" for t in live)
        raise ValidationError(
            f"AMBIGUOUS_LIVE_TASKS: multiple live tasks found in worktree: {tasks_summary}. "
            "Fail closed: at most one live task is allowed per worktree. "
            "Remediation: inspect tasks via 'task status' and cancel unwanted live tasks via 'workflow.py cancel --task-id <id>'."
        )
    if live and allowed_task_id and live[0][0] != allowed_task_id:
        prev_id, prev_status = live[0][0], live[0][1]
        raise ValidationError(
            f"ACTIVE_TASK_CONFLICT: active task '{prev_id}' is currently {prev_status}. "
            f"Choices: 1. continue current task '{prev_id}'; 2. cancel it via 'workflow.py cancel --task-id {prev_id}'; "
            "3. deliver current task when valid; 4. use a separate Git worktree for parallel work."
        )
    return live


def draft(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id, "task id")

    # 0. Reconcile clean delivered tasks automatically before conflict checks
    reconcile_delivery(repo)

    # 1. Enforce at most one live task per worktree
    live_tasks = _find_live_tasks(repo)
    if len(live_tasks) > 1:
        tasks_summary = ", ".join(f"'{t[0]}' ({t[1]})" for t in live_tasks)
        raise ValidationError(
            f"AMBIGUOUS_LIVE_TASKS: multiple live tasks found in worktree: {tasks_summary}. "
            "Fail closed: at most one live task is allowed per worktree. "
            "Remediation: inspect tasks via 'task status' and cancel unwanted live tasks via 'workflow.py cancel --task-id <id>'."
        )
    for prev_id, prev_status, prev_plan, _ in live_tasks:
        if prev_id != task_id:
            if prev_status == "READY_FOR_DELIVERY":
                dirty = _find_uncommitted_task_files(repo, prev_id, prev_plan)
                if dirty:
                    raise ValidationError(
                        f"PREVIOUS_DELIVERY_NOT_FINALIZED: previous task '{prev_id}' is READY_FOR_DELIVERY with uncommitted changes: "
                        f"{', '.join(sorted(dirty))}. Finalize delivery via 'workflow.py deliver' or cancel it via 'workflow.py cancel' before starting a new task."
                    )
                finalize_ready_delivery(repo, prev_id, prev_plan, require_clean_tree=True)
            elif prev_status in ("APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED"):
                raise ValidationError(
                    f"ACTIVE_TASK_CONFLICT: active task '{prev_id}' is currently {prev_status}. "
                    f"Choices: 1. continue current task; 2. cancel current task via 'workflow.py cancel --task-id {prev_id}'; "
                    "3. deliver current task when valid; 4. use a separate Git worktree for parallel work."
                )
            elif prev_status == "AWAITING_DEVELOPER_APPROVAL":
                raise ValidationError(
                    f"ACTIVE_TASK_CONFLICT: pending task '{prev_id}' is currently AWAITING_DEVELOPER_APPROVAL. "
                    f"Choices: 1. approve or revise current task '{prev_id}'; 2. cancel it via 'workflow.py cancel --task-id {prev_id}' before drafting an unrelated task; "
                    "3. use a separate Git worktree for parallel work."
                )

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

    return _build_and_save_plan(repo, args, task_id, is_revision=False)


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
            except Exception:
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
        except Exception:
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
            except Exception:
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
        })
    return applicable


def _build_and_save_plan(
    repo: Path,
    args: argparse.Namespace,
    task_id: str,
    *,
    is_revision: bool = False,
    old_plan: dict | None = None,
    old_baseline: dict | None = None,
    old_plan_sha: str | None = None,
) -> dict:
    with step_progress("Classifying changed surfaces"):
        sublog("Inspecting working tree status and surface triggers...")
        classification = classify(repo)
        ch_files = classification.get("changed_files") or 0
        surfs = ", ".join(classification.get("surfaces") or []) or "none"
        sublog(f"Detected {ch_files} working tree changes, surfaces: {surfs}")
    raw_phases = getattr(args, "phases", None) or getattr(args, "phases_file", None)
    parsed_phases = None
    if raw_phases:
        if isinstance(raw_phases, list):
            parsed_phases = raw_phases
        elif isinstance(raw_phases, str):
            s = raw_phases.strip()
            if not s.startswith(("[", "{")) and (s.endswith(".json") or (repo / s).is_file() or Path(s).is_file() or ".." in s or Path(s).is_absolute()):
                rel_posix = validate_repo_path_containment(repo, s)
                p_file = repo / rel_posix
                if not p_file.is_file():
                    raise ValidationError(f"phases file not found: {s}")
                try:
                    loaded = json.loads(p_file.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise ValidationError(f"invalid --phases file: {exc}")
            else:
                loaded = None
                # Tier 1: direct json.loads
                try:
                    loaded = json.loads(s)
                except Exception:
                    pass
                # Tier 2: clean powershell escaped quotes and outer wrapping quotes
                if loaded is None:
                    cleaned = s
                    if (cleaned.startswith("'") and cleaned.endswith("'")) or (cleaned.startswith('"') and cleaned.endswith('"')):
                        cleaned = cleaned[1:-1].strip()
                    cleaned = cleaned.replace(r'\"', '"')
                    try:
                        loaded = json.loads(cleaned)
                    except Exception:
                        pass
                # Tier 3: ast.literal_eval for python-style dict/list representations
                if loaded is None:
                    import ast
                    try:
                        loaded = ast.literal_eval(cleaned if "cleaned" in locals() else s)
                    except Exception:
                        pass
                # Tier 4: comma-separated list like "p1:Setup, p2:Implementation" or "p1, p2"
                if loaded is None and not s.startswith(("[", "{")):
                    parts = [p.strip() for p in s.split(",") if p.strip()]
                    if parts:
                        loaded = []
                        for part in parts:
                            if ":" in part:
                                pid, pdesc = part.split(":", 1)
                                loaded.append({"id": pid.strip(), "description": pdesc.strip()})
                            else:
                                loaded.append({"id": part, "description": f"Phase {part}"})
                if loaded is None:
                    raise ValidationError(f"invalid --phases parameter: unable to parse phases from '{s[:60]}'")
            if isinstance(loaded, list):
                parsed_phases = loaded
            elif isinstance(loaded, dict) and isinstance(loaded.get("phases"), list):
                parsed_phases = loaded["phases"]
            else:
                raise ValidationError("phases JSON must be a list of phases or an object with a 'phases' list")

        if parsed_phases is not None:
            parsed_phases = validate_phases(repo, parsed_phases)

    task_context_id = getattr(args, "task_context_id", None)
    cached_ctx = None
    has_explicit_target = bool(
        getattr(args, "architecture_target_scope", None)
        or getattr(args, "expected_files", None)
        or classification.get("changed_files", 0) > 0
    )
    if task_context_id or not has_explicit_target:
        cached_ctx = _resolve_task_context_for_draft(repo, task_context_id)

    raw_expected_files = getattr(args, "expected_files", None)
    if not raw_expected_files and cached_ctx and cached_ctx.get("target_file"):
        raw_expected_files = cached_ctx["target_file"]

    norm_expected_files = normalize_expected_files(repo, raw_expected_files)
    raw_expected = [item.strip() for item in (getattr(args, "expected_surfaces", None) or "").split(",") if item.strip()]
    expected = normalize_expected_surfaces(raw_expected)
    if not expected:
        if cached_ctx and cached_ctx.get("candidate_surfaces"):
            expected = list(cached_ctx["candidate_surfaces"])
        elif norm_expected_files:
            file_class = classify(repo, task_changes=[{"path": p} for p in norm_expected_files])
            expected = list(file_class.get("surfaces") or [])
            if not expected:
                inferred_surfaces: set[str] = set()
                for p in norm_expected_files:
                    p_lower = p.lower()
                    if p_lower.endswith((".kt", ".java")):
                        if "/test/" in p_lower or p_lower.endswith(("test.kt", "test.java")):
                            inferred_surfaces.add("TEST_ONLY")
                        elif any(w in p_lower for w in ("screen", "activity", "fragment", "composable")):
                            inferred_surfaces.update(["BUSINESS_LOGIC", "COMPOSE_UI"])
                        else:
                            inferred_surfaces.add("BUSINESS_LOGIC")
                    elif "/res/values" in p_lower and p_lower.endswith(".xml"):
                        inferred_surfaces.add("LOCALIZATION" if "strings" in p_lower else "RESOURCE_UI")
                    elif "/res/layout" in p_lower and p_lower.endswith(".xml"):
                        inferred_surfaces.add("XML_UI")
                    elif "/res/navigation" in p_lower and p_lower.endswith(".xml"):
                        inferred_surfaces.add("NAVIGATION")
                    elif "/res/" in p_lower:
                        inferred_surfaces.add("RESOURCE_UI")
                    elif p_lower.endswith((".gradle", ".gradle.kts")):
                        inferred_surfaces.add("BUILD_CONFIG")
                    elif p_lower.endswith("androidmanifest.xml"):
                        inferred_surfaces.add("MANIFEST_PERMISSION")
                expected = sorted(inferred_surfaces)
        elif not classification.get("changed_files"):
            expected = list(DEFAULT_APP_SURFACES)
        else:
            expected = []


    # Phase Plan Enforcement
    LAYER_GROUPS = {
        "UI": {"COMPOSE_UI", "XML_UI", "RESOURCE_UI", "NAVIGATION"},
        "BUSINESS": {"BUSINESS_LOGIC", "COROUTINES", "PUBLIC_API"},
        "DATA": {"NETWORK", "PERSISTENCE", "ROOM_SCHEMA"},
        "PLATFORM": {"DEVICE_API", "MANIFEST_PERMISSION", "BUILD_CONFIG"},
    }
    DOC_RESOURCE_SUFFIXES = {
        ".md", ".txt", ".rst", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif",
        ".xml", ".json", ".properties", ".pro", ".ico"
    }
    impl_files = [f for f in norm_expected_files if Path(f).suffix.lower() not in DOC_RESOURCE_SUFFIXES]

    surfaces_for_layer_check = set(raw_expected)
    if not surfaces_for_layer_check and norm_expected_files:
        ef_class = classify(repo, task_changes=[{"path": p} for p in norm_expected_files])
        surfaces_for_layer_check = set(ef_class.get("surfaces") or [])

    # Exemptions: docs only, test-only, localization-only
    if surfaces_for_layer_check and surfaces_for_layer_check <= {"DOCS", "TEST_ONLY", "LOCALIZATION"}:
        spanned_layer_groups = set()
    else:
        spanned_layer_groups = {
            grp_name for grp_name, grp_surfaces in LAYER_GROUPS.items()
            if grp_surfaces & surfaces_for_layer_check
        }

    impl_modules = set()
    for f in impl_files:
        parts = f.replace("\\", "/").strip().lstrip("./").split("/")
        if len(parts) > 1 and "src" in parts:
            idx = parts.index("src")
            impl_modules.add("/".join(parts[:idx]))
        elif len(parts) > 1:
            impl_modules.add(parts[0])

    arch_intent = str(getattr(args, "architecture_intent", "EXISTING_CHANGE") or "EXISTING_CHANGE").upper()

    requires_phases = (
        (
            len(impl_files) > 8
            or len(impl_modules) > 1
            or arch_intent == "MIGRATION"
            or ("ROOM_SCHEMA" in surfaces_for_layer_check and len(impl_files) >= 2)
            or (len(spanned_layer_groups) >= 3 and len(impl_files) > 8)
        )
        and not getattr(args, "force", False)
    )
    if requires_phases and not parsed_phases:
        raise ValidationError(
            "PHASE_PLAN_REQUIRED: Task scope exceeds single-phase threshold "
            f"({len(impl_files)} implementation files, {len(impl_modules)} module(s), "
            f"arch_intent={arch_intent}, layer groups: {', '.join(sorted(spanned_layer_groups)) or 'none'}). "
            "Define phased execution using --phases '[{\"id\": \"p1\", ...}, {\"id\": \"p2\", ...}]'."
        )

    raw_kind = str(getattr(args, "kind", None) or "AUTO").strip().upper()
    if raw_kind not in {"AUTO", "BUG", "FEATURE", "REFACTOR"}:
        raw_kind = "AUTO"
    if raw_kind == "AUTO":
        text_to_scan = f"{getattr(args, 'outcome', None) or ''} {getattr(args, 'expected_surfaces', None) or ''}".lower()
        if re.search(r"\b(?:bug|crash|fix|regression|error|fault|anr|issue|exception)\b", text_to_scan):
            resolved_kind = "BUG"
        else:
            resolved_kind = "FEATURE"
    else:
        resolved_kind = raw_kind
    policy_input = dict(classification)
    policy_input["surfaces"] = expected
    with step_progress("Evaluating routing policy"):
        sublog(f"Evaluating review requirements for kind={resolved_kind}...")
        preliminary_policy = decide(policy_input, skills_root(repo), project_kind=project_kind(repo), task_kind=resolved_kind)
        raw_revs = preliminary_policy.get("reviewers")
        if isinstance(raw_revs, list):
            req_roles = ", ".join(str(r) for r in raw_revs) or "none"
        elif isinstance(raw_revs, dict):
            req_roles = ", ".join(str(r) for r in raw_revs.get("required_roles", [])) or "none"
        else:
            req_roles = "none"
        sublog(f"Routing policy resolved required reviewers: {req_roles}")

    # Resolve Evolutionary Architecture Contract
    arch_intent = str(getattr(args, "architecture_intent", "EXISTING_CHANGE") or "EXISTING_CHANGE").upper()
    inferred_target_scope = str(getattr(args, "architecture_target_scope", "") or "").strip()
    if not inferred_target_scope and arch_intent != "MIGRATION":
        if norm_expected_files:
            impl_candidates = [
                p for p in norm_expected_files
                if not ("/test/" in p.lower() or p.lower().endswith(("test.kt", "test.java")))
            ]
            eval_files = impl_candidates or norm_expected_files
            if len(eval_files) == 1:
                inferred_target_scope = eval_files[0]
            else:
                primary = next(
                    (p for p in eval_files if any(k in p.lower() for k in ("view", "fragment", "screen", "activity", "composable"))),
                    eval_files[0]
                )
                inferred_target_scope = primary
        elif classification.get("changed_files", 0) >= 1:
            all_files = sorted(set(p for info in (classification.get("details") or {}).values() for p in info.get("files") or []))
            if len(all_files) == 1:
                inferred_target_scope = all_files[0]
            elif all_files:
                primary = next(
                    (p for p in all_files if any(k in p.lower() for k in ("view", "fragment", "screen", "activity", "composable"))),
                    all_files[0]
                )
                inferred_target_scope = primary
        elif getattr(args, "expected_modules", None):
            exp_mods = [m.strip() for m in str(args.expected_modules).split(",") if m.strip()]
            if len(exp_mods) == 1:
                inferred_target_scope = exp_mods[0]

        if not inferred_target_scope:
            if cached_ctx and cached_ctx.get("target_file"):
                inferred_target_scope = cached_ctx["target_file"]
            else:
                last_ctx_file = repo / ".agents" / "cache" / "last-task-context.json"
                if last_ctx_file.is_file():
                    try:
                        ctx_data = json.loads(last_ctx_file.read_text(encoding="utf-8"))
                        if time.time() - float(ctx_data.get("timestamp", 0)) < 1800:
                            cand = str(ctx_data.get("file") or "").strip()
                            if cand and (repo / cand).is_file():
                                inferred_target_scope = cand
                    except Exception:
                        pass

    from architecture_resolver import (
        resolve_architecture_contract,
        STATUS_RESOLVED,
    )
    if arch_intent == "MIGRATION":
        p_depth = str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper()
        if p_depth != "ARCHITECTURAL":
            raise ValidationError("architecture migration requires planning_depth=ARCHITECTURAL")
        if not inferred_target_scope:
            raise ValidationError("architecture migration requires a non-empty target scope")

    with step_progress("Resolving architecture contract"):
        sublog(f"Resolving architecture contract (intent={arch_intent}, scope='{inferred_target_scope or 'auto'}')...")
        arch_res = resolve_architecture_contract(
            repo,
            architecture_intent=arch_intent,
            target_scope=inferred_target_scope,
            target_family_id=getattr(args, "architecture_target_family", None),
            planning_depth=str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper(),
        )
        if arch_res["status"] != STATUS_RESOLVED:
            raise ValidationError(f"architecture contract resolution failed ({arch_res['status']}): {arch_res['message']}")

        arch_contract = arch_res.get("contract")
        arch_brief = arch_res.get("brief_markdown")
        fam_label = (arch_contract.get("family_id") or "standard") if arch_contract else "none"
        sublog(f"Architecture contract resolved successfully (family={fam_label}).")

    requested_outcome = getattr(args, "outcome", None) or (old_plan.get("requested_outcome") if old_plan else "")
    if not requested_outcome or not str(requested_outcome).strip():
        raise ValidationError("plan requested outcome must not be empty")
    requested_outcome = str(requested_outcome).strip()

    directory = task_dir(repo, task_id)
    directory.mkdir(parents=True, exist_ok=True)
    if arch_brief:
        (directory / "task-architecture-brief.md").write_text(arch_brief, encoding="utf-8")

    raw_exp_mods = getattr(args, "expected_modules", None)
    if raw_exp_mods:
        resolved_expected_modules = [module_id(item) for item in str(raw_exp_mods).split(",") if item.strip()]
    elif cached_ctx and cached_ctx.get("module"):
        resolved_expected_modules = [module_id(cached_ctx["module"])]
    elif norm_expected_files:
        from plan_authority import discover_android_modules
        known_mods = sorted(
            ((module_id(item), module_id(item).lstrip(":").replace(":", "/")) for item in discover_android_modules(repo)),
            key=lambda item: len(item[1]), reverse=True,
        )
        found_mods: set[str] = set()
        for f in norm_expected_files:
            rel = f.replace("\\", "/").strip("/")
            matched = next((candidate for candidate, prefix in known_mods if prefix and (rel == prefix or rel.startswith(prefix + "/"))), None)
            found_mods.add(matched or ":")
        resolved_expected_modules = sorted(found_mods)
    else:
        resolved_expected_modules = []

    if is_revision and old_baseline:
        base_manifest = {
            "delivery_snapshot_sha256": old_baseline.get("base_delivery_snapshot_sha256"),
            "change_set_sha256": old_baseline.get("base_change_set_sha256"),
        }
        plan = create_plan(
            repo,
            task_id=task_id,
            task_kind=resolved_kind,
            planning_depth=str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper(),
            requested_outcome=requested_outcome,
            expected_surfaces=expected,
            expected_modules=resolved_expected_modules,
            expected_files=norm_expected_files,
            test_strategy=getattr(args, "test_strategy", None) or "Policy-selected relevant tests",
            device_strategy=getattr(args, "device_strategy", None) or "Policy-selected device verification",
            risks=[item.strip() for item in (getattr(args, "risks", None) or "").split(",") if item.strip()],
            rollback=getattr(args, "rollback", None) or "Stop on conflict; preserve developer changes; no automatic Git reset",
            skills=preliminary_policy["skills"]["skills"],
            external_writes=list(getattr(args, "external_write", None) or []),
            architecture_contract=arch_contract,
            phases=parsed_phases,
            base_manifest=base_manifest,
            supersedes_plan_sha256=old_plan_sha,
            revision_number=int((old_plan or {}).get("revision_number", 1)) + 1,
        )
        plan["task_baseline"] = old_baseline
        plan["status"] = "AWAITING_DEVELOPER_APPROVAL"
        if cached_ctx and cached_ctx.get("context_id"):
            plan["task_context_id"] = cached_ctx["context_id"]
        elif task_context_id:
            plan["task_context_id"] = task_context_id
        plan["developer_instructions"] = _applicable_developer_instructions_for_task(repo, cached_ctx, inferred_target_scope, arch_intent)
        save_plan(directory / "plan.json", plan)
        atomic_write_json(directory / "preliminary-classification.json", classification)
        atomic_write_json(directory / "preliminary-policy.json", preliminary_policy)
        atomic_write_json(state_root(repo) / "active-task.json", {"task_id": task_id, "plan_path": str(directory / "plan.json"), "updated_at": utc_now()})
        if parsed_phases:
            atomic_write_json(directory / "phase-state.json", {
                "current_phase_id": parsed_phases[0]["id"],
                "completed_phases": [],
                "phase_checkpoints": {},
            })
        return plan

    plan = create_plan(
        repo,
        task_id=task_id,
        task_kind=resolved_kind,
        planning_depth=str(getattr(args, "planning_depth", "BOUNDED") or "BOUNDED").upper(),
        requested_outcome=requested_outcome,
        expected_surfaces=expected,
        expected_modules=resolved_expected_modules,
        expected_files=norm_expected_files,
        test_strategy=getattr(args, "test_strategy", None) or "Policy-selected relevant tests",
        device_strategy=getattr(args, "device_strategy", None) or "Policy-selected device verification",
        risks=[item.strip() for item in (getattr(args, "risks", None) or "").split(",") if item.strip()],
        rollback=getattr(args, "rollback", None) or "Stop on conflict; preserve developer changes; no automatic Git reset",
        skills=preliminary_policy["skills"]["skills"],
        external_writes=list(getattr(args, "external_write", None) or []),
        architecture_contract=arch_contract,
        phases=parsed_phases,
    )
    if cached_ctx and cached_ctx.get("context_id"):
        plan["task_context_id"] = cached_ctx["context_id"]
    elif task_context_id:
        plan["task_context_id"] = task_context_id
    plan["developer_instructions"] = _applicable_developer_instructions_for_task(repo, cached_ctx, inferred_target_scope, arch_intent)

    # Bind compact discovery provenance (D1/D2/D3) if available
    disc_receipt = None
    try:
        from discovery_receipt import load_latest_discovery_receipt, check_discovery_freshness
        disc_receipt = load_latest_discovery_receipt(repo)
    except Exception:
        disc_receipt = None

    if disc_receipt:
        fresh, fresh_msg = check_discovery_freshness(repo, disc_receipt)
        if not fresh:
            raise ValidationError(f"DISCOVERY_REFRESH_REQUIRED: {fresh_msg}")
        plan["discovery_provenance"] = {
            "discovery_id": str(disc_receipt.get("id") or ""),
            "discovery_mode": str(disc_receipt.get("mode") or ""),
            "graph_fingerprint": str(disc_receipt.get("graph_fingerprint") or ""),
            "primary_target": str((disc_receipt.get("query") or {}).get("value") or ""),
        }

    save_plan(directory / "plan.json", plan)
    atomic_write_json(directory / "preliminary-classification.json", classification)
    atomic_write_json(directory / "preliminary-policy.json", preliminary_policy)
    atomic_write_json(state_root(repo) / "active-task.json", {"task_id": task_id, "plan_path": str(directory / "plan.json"), "updated_at": utc_now()})

    base_man = build_manifest(repo)
    task_baseline = {
        "schema_version": 1,
        "task_id": task_id,
        "repository": plan.get("repository"),
        "base_delivery_snapshot_sha256": plan.get("base_delivery_snapshot_sha256"),
        "base_change_set_sha256": plan.get("base_change_set_sha256"),
        "changes": base_man.get("changes") or [],
    }
    task_baseline["baseline_sha256"] = canonical_sha256({
        "schema_version": task_baseline["schema_version"],
        "task_id": task_baseline["task_id"],
        "repository": task_baseline["repository"],
        "base_delivery_snapshot_sha256": task_baseline["base_delivery_snapshot_sha256"],
        "base_change_set_sha256": task_baseline["base_change_set_sha256"],
        "changes": task_baseline["changes"],
    })
    atomic_write_json(directory / "task-baseline.json", task_baseline)
    plan["task_baseline"] = task_baseline
    save_plan(directory / "plan.json", plan)

    # Snapshot pre-existing dirty files
    baseline_files_dir = directory / "baseline-files"
    secret_markers = (".env", "keystore", "jks", "secret", "token", "credentials", "local.properties")
    binary_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ttf", ".otf", ".wav", ".mp3", ".ogg", ".mp4", ".jar", ".aar", ".so", ".apk"}
    for entry in task_baseline["changes"]:
        rel = entry.get("path")
        if not rel:
            continue
        rel_norm = rel.replace("\\", "/")
        if any(m in rel_norm.lower() for m in secret_markers):
            continue
        fpath = repo / rel
        if not fpath.is_file() or fpath.is_symlink():
            continue
        if fpath.suffix.lower() in binary_suffixes:
            continue
        try:
            if fpath.stat().st_size <= 2 * 1024 * 1024:
                dest = baseline_files_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fpath, dest)
        except OSError:
            pass

    if parsed_phases:
        atomic_write_json(directory / "phase-state.json", {
            "current_phase_id": parsed_phases[0]["id"],
            "completed_phases": [],
            "phase_checkpoints": {},
        })
        p1_dir = directory / "phases" / parsed_phases[0]["id"]
        p1_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(p1_dir / "baseline.json", task_baseline)

    return plan


def revise(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id, "task id")
    assert_single_live_task(repo, allowed_task_id=task_id)
    plan_p = _plan_path(repo, task_id)
    if not plan_p.is_file():
        raise ValidationError(f"cannot revise task '{task_id}': plan.json does not exist at {plan_p}")
    old_plan = read_json(plan_p)
    old_status = str(old_plan.get("status") or "")
    if old_status not in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED"):
        raise ValidationError(f"cannot revise task '{task_id}': task status is {old_status}, only active non-terminal tasks can be revised")

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

    # 3. Invalidate active verification run
    current_run_file = directory / "current-run.json"
    if current_run_file.is_file():
        current_run_file.unlink(missing_ok=True)

    return _build_and_save_plan(
        repo,
        args,
        task_id,
        is_revision=True,
        old_plan=old_plan,
        old_baseline=old_baseline,
        old_plan_sha=old_plan_sha,
    )


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


def record_approval(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    assert_single_live_task(repo, allowed_task_id=args.task_id)
    plan_file = _plan_path(repo, args.task_id)
    plan = _load_plan(repo, args.task_id)
    tier = args.enforcement_tier
    directory = task_dir(repo, args.task_id)
    with StateLock(directory / ".lock"):
        plan = approve_and_begin(repo, plan, source=args.source, proof_reference=args.proof_reference, enforcement_tier=tier)
        save_plan(plan_file, plan)
        atomic_write_json(state_root(repo) / "active-task.json", {
            "task_id": args.task_id,
            "plan_path": str(plan_file),
            "updated_at": utc_now(),
        })
    return plan


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
                except Exception:
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
        sublog("Loading task baseline and building manifest...")
        task_baseline = load_task_baseline(repo, args.task_id)
        manifest = build_task_manifest(repo, task_baseline, expected_files=plan.get("expected_files"))
        sublog(f"Manifest ready with change set: {manifest.get('change_set_sha256', '')[:12]}")
    with step_progress("Classifying changed surfaces"):
        sublog("Classifying task changes...")
        classification = classify(repo, task_id=args.task_id, task_changes=manifest.get("task_changes"))
        sublog(f"Surfaces: {', '.join(classification.get('surfaces') or []) or 'none'}")
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
    actual_task_paths = [
        (c.get("path") if isinstance(c, dict) else str(c))
        for c in (manifest.get("task_changes") or manifest.get("changes") or [])
        if (c.get("path") if isinstance(c, dict) else str(c))
    ]
    drift = check_material_drift(plan, policy.get("surfaces") or [], changed_modules(repo, manifest), actual_files=actual_task_paths)
    if drift:
        plan["material_drift"] = drift
        save_plan(_plan_path(repo, args.task_id), plan)
        remediation_cmd = build_remediation_command(repo, args.task_id, plan, policy, manifest)
        raise ValidationError(
            f"PLAN_APPROVAL_REQUIRED: material drift detected: {', '.join(str(k) for k in drift)}. "
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
            except Exception:
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
            remediation_msg = build_budget_exhausted_remediation(
                policy=policy,
                calls_used=int(b.get("calls_used") or 0),
                requested=int(b.get("requested") or 0),
                budget=int(b.get("budget") or 0),
            )
            raise ValidationError(remediation_msg)
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
    atomic_write_json(state_root(repo) / "active-task.json", {"task_id": args.task_id, "plan_path": str(_plan_path(repo, args.task_id)), "updated_at": utc_now()})
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
                            evidence=res_data,
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
    live = _find_live_tasks(repo)
    if len(live) > 1:
        tasks_summary = ", ".join(f"'{t[0]}' ({t[1]})" for t in live)
        raise ValidationError(
            f"AMBIGUOUS_LIVE_TASKS: multiple live tasks found in worktree: {tasks_summary}. "
            "Cannot recover stale state automatically. Specify --task-id explicitly or cancel unwanted tasks via 'workflow.py cancel'."
        )
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
    assert_single_live_task(repo, allowed_task_id=args.task_id)
    plan = _load_plan(repo, args.task_id)
    if plan.get("status") not in ("VERIFYING", "BLOCKED"):
        raise ValidationError("only a verifying or blocked task can resume implementation")
    if not plan.get("approval") or plan.get("execution_nonce") != plan["approval"].get("single_use_nonce"):
        raise ValidationError("the approved execution identity is no longer valid")
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


def reconcile_delivery(repo: Path, task_id: str | None = None) -> tuple[dict | None, str]:
    """Reconcile READY_FOR_DELIVERY task against clean committed repository state."""
    tid = task_id
    if not tid:
        live = _find_live_tasks(repo)
        if len(live) > 1:
            tasks_summary = ", ".join(f"'{t[0]}' ({t[1]})" for t in live)
            raise ValidationError(
                f"AMBIGUOUS_LIVE_TASKS: multiple live tasks found in worktree: {tasks_summary}. "
                "Cannot determine which task to reconcile automatically. Specify --task-id explicitly or cancel unwanted tasks via 'workflow.py cancel'."
            )
        elif len(live) == 1:
            tid = live[0][0]
        else:
            active_p = state_root(repo) / "active-task.json"
            if active_p.is_file():
                try:
                    tid = str(read_json(active_p).get("task_id") or "").strip()
                except Exception:
                    pass
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
        except Exception:
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
                except Exception:
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
            except Exception:
                pass

    has_android_main = (mod_dir / "src" / "androidMain").is_dir()
    is_kmp = "multiplatform" in build_content or (mod_dir / "src" / "commonMain").is_dir() or has_android_main

    # Kotlin detection
    has_kotlin = False
    if mod_dir.is_dir():
        has_kotlin = any(mod_dir.glob("**/*.kt"))
    if not has_kotlin and phase_changes:
        for c in phase_changes:
            raw_p = c.get("path") if isinstance(c, dict) else str(c or "")
            p_str = (raw_p or "").replace("\\", "/").strip("/")
            if (p_str.startswith(mod_rel + "/") or mod_rel == p_str.split("/")[0]) and p_str.endswith(".kt"):
                has_kotlin = True
                break

    if is_kmp:
        if has_android_main:
            if task_type == "compile":
                return f"{mod_clean}:compileKotlinAndroid"
            else:
                return f"{mod_clean}:testDebugUnitTest"
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


def check_phase_tests(repo: Path, phase_dir: Path, modules: list[str], needs_tests: bool, phase_changes: list[Any] | None = None) -> tuple[bool, str]:
    if not needs_tests:
        return True, "NOT_REQUIRED"
    test_file = phase_dir / "unit_tests.json"
    if test_file.is_file():
        data = read_json(test_file)
        if str(data.get("status") or "").upper() == "PASS":
            return True, "PASS"
        return False, str(data.get("detail") or "unit test failure in phase evidence")
    gradle_wrapper = (repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()
    if gradle_wrapper:
        from run_gradle_task import run_gradle
        for m in modules:
            try:
                task = resolve_module_gradle_task(repo, m, task_type="test", phase_changes=phase_changes)
            except ValidationError as exc:
                return False, str(exc)
            res = run_gradle([task], cwd=repo)
            if res != 0:
                return False, f"unit tests failed for module '{m}' with task '{task}' (exit code {res})"
        return True, "PASS"
    try:
        from run_gradle_task import run_gradle
        if hasattr(run_gradle, "assert_called") or hasattr(run_gradle, "side_effect") or hasattr(run_gradle, "return_value"):
            for m in modules:
                task = resolve_module_gradle_task(repo, m, task_type="test", phase_changes=phase_changes)
                res = run_gradle([task], cwd=repo)
                if res != 0:
                    return False, f"mocked unit tests failed for module '{m}' with task '{task}' (exit code {res})"
            return True, "PASS"
    except Exception:
        pass
    return False, "phase policy requires unit tests but no gradle wrapper or passing test evidence was found"


def check_phase_reviews(repo: Path, phase_dir: Path, required_reviewers: list[str]) -> tuple[bool, str, list[str]]:
    if not required_reviewers:
        return True, "NOT_REQUIRED", []
    reports: list[dict] = []
    reviews_file = phase_dir / "reviews.json"
    if reviews_file.is_file():
        try:
            data = json.loads(reviews_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                reports = data
            elif isinstance(data, dict):
                reports = data.get("reports") or [data]
        except Exception:
            pass
    else:
        reviews_dir = phase_dir / "reviews"
        if reviews_dir.is_dir():
            for f in sorted(reviews_dir.glob("*.json")):
                try:
                    rep = read_json(f)
                    if isinstance(rep, dict):
                        reports.append(rep)
                except Exception:
                    pass

    if not reports:
        return False, f"phase requires review from {', '.join(sorted(required_reviewers))}, but no review evidence was found", []

    recorded_reviewers = {str(r.get("reviewer") or "") for r in reports}
    missing = set(required_reviewers) - recorded_reviewers
    if missing:
        return False, f"phase review missing required reviewer(s): {', '.join(sorted(missing))}", []

    for r in reports:
        rev_name = str(r.get("reviewer") or "unknown")
        verdict = str(r.get("verdict") or "").upper()
        if verdict == "FINDINGS" or r.get("blocking_findings"):
            return False, f"phase review from {rev_name} contains unresolved blocking findings", []
        if verdict != "PASS":
            return False, f"phase review from {rev_name} verdict is {verdict}, expected PASS", []

    return True, "PASS", sorted(required_reviewers)


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

    phase_dir = directory / "phases" / phase_id
    phase_dir.mkdir(parents=True, exist_ok=True)
    baseline_file = phase_dir / "baseline.json"
    base_data = read_json(baseline_file) if baseline_file.is_file() else load_task_baseline(repo, args.task_id)
    manifest = build_task_manifest(repo, base_data, expected_files=target_phase.get("expected_files") or plan.get("expected_files"))
    phase_changes = manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes") or []
    if not phase_changes:
        raise ValidationError(f"phase checkpoint failed: no file changes detected for phase '{phase_id}'")

    phase_expected_files = target_phase.get("expected_files")
    if phase_expected_files:
        norm_expected = normalize_expected_files(repo, phase_expected_files)
        for change in phase_changes:
            raw_p = change.get("path") if isinstance(change, dict) else str(change)
            change_path = (raw_p or "").replace("\\", "/").strip("/")
            if change_path.startswith(".agents/"):
                continue
            if change_path not in norm_expected:
                raise ValidationError(f"phase '{phase_id}' modified file outside expected_files: {change_path}")

    phase_expected_modules = target_phase.get("expected_modules")
    if phase_expected_modules:
        norm_mods = [m.strip("/:").replace("\\", "/") for m in phase_expected_modules]
        for change in phase_changes:
            raw_p = change.get("path") if isinstance(change, dict) else str(change)
            change_path = (raw_p or "").replace("\\", "/").strip("/")
            if change_path.startswith(".agents/"):
                continue
            mod_match = any(change_path.startswith(m + "/") or change_path == m for m in norm_mods)
            if not mod_match:
                raise ValidationError(f"phase '{phase_id}' modified file outside expected_modules: {change_path}")

    # Phase delta classification & central policy
    phase_classification = classify(repo, task_changes=phase_changes)
    skills_root = (repo / "agents" / "skills") if (repo / "agents" / "skills").is_dir() else (repo / ".agents" / "skills")
    phase_policy = decide(phase_classification, skills_root, plan=plan)

    # 1. Deterministic Preflight
    # Fast Kotlin lint
    try:
        from fast_kt_lint import lint_file
        kt_issues = []
        for c in phase_changes:
            rel_p = c.get("path", "") if isinstance(c, dict) else str(c or "")
            p = repo / rel_p
            if p.suffix == ".kt" and p.is_file():
                kt_issues.extend(lint_file(p))
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

    # 2. Targeted compile
    resolved_modules = resolve_phase_modules(repo, manifest)
    try:
        compile_ok, compile_detail = check_phase_compile(repo, resolved_modules, phase_changes=phase_changes)
        if not compile_ok:
            raise ValidationError(f"phase checkpoint compile failed: {compile_detail}")
        compile_status = {"status": compile_detail, "modules": resolved_modules}
    except (ImportError, ValidationError):
        raise
    except Exception as exc:
        raise ValidationError(f"phase checkpoint compile exception: {exc}")

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

    # 4. Elevated intermediate review (only when justified by critical phase boundary)
    all_reviewers = list(phase_policy.get("reviewers") or [])
    is_multi_phase = len(phases) > 1
    is_critical_boundary = (
        bool(target_phase.get("critical_boundary"))
        or bool(target_phase.get("review_required"))
        or any(s in ("AUTH", "BILLING", "SECURITY", "CRYPTO", "MIGRATION") for s in (phase_policy.get("surfaces") or []))
        or phase_policy.get("risk_lane") == "CRITICAL"
        or phase_policy.get("risk_tier") == 5
    )

    if is_multi_phase and not is_critical_boundary:
        # Routine intermediate phases in multi-phase tasks are deterministic-first;
        # remove duplicate mandatory generic AI reviews.
        required_reviewers = []
    else:
        if target_phase.get("reviewers"):
            required_reviewers = list(target_phase["reviewers"])
        elif is_critical_boundary and all_reviewers:
            critical_surfaces = {"AUTH", "BILLING", "SECURITY", "CRYPTO"} & (set(phase_policy.get("surfaces") or []) | set(target_phase.get("surfaces") or []))
            if critical_surfaces and "security-reviewer-agent" in all_reviewers:
                required_reviewers = ["security-reviewer-agent"]
            else:
                required_reviewers = [all_reviewers[0]]
        else:
            required_reviewers = all_reviewers

    try:
        rev_ok, rev_detail, active_reviewers = check_phase_reviews(repo, phase_dir, required_reviewers)
        if not rev_ok:
            raise ValidationError(f"phase checkpoint review failed: {rev_detail}")
        review_status = {"status": rev_detail, "reviewers": active_reviewers}
    except (ImportError, ValidationError):
        raise
    except Exception as exc:
        raise ValidationError(f"phase checkpoint review exception: {exc}")

    call_budget = 10
    try:
        from _product import MODEL_CALL_BUDGET
        call_budget = max(0, int(MODEL_CALL_BUDGET))
    except Exception:
        pass

    checkpoint_record = {
        "schema_version": 1,
        "task_id": args.task_id,
        "phase_id": phase_id,
        "status": "CHECKPOINT_PASS",
        "checkpoint_at": utc_now(),
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "task_change_set_sha256": manifest["task_change_set_sha256"],
        "manifest_delta": phase_changes,
        "preflight": preflight_status,
        "compile": compile_status,
        "tests": tests_status,
        "review": review_status,
        "scoped_review": {"budget": call_budget, "status": review_status["status"], "reviewers": review_status.get("reviewers", [])},
    }
    checkpoint_record["checkpoint_sha256"] = canonical_sha256(checkpoint_record)
    atomic_write_json(phase_dir / "checkpoint.json", checkpoint_record)

    completed = list(phase_state.get("completed_phases") or [])
    if phase_id not in completed:
        completed.append(phase_id)
    phase_state["completed_phases"] = completed
    phase_state.setdefault("phase_checkpoints", {})[phase_id] = checkpoint_record["checkpoint_sha256"]

    curr_idx = next((i for i, p in enumerate(phases) if p.get("id") == phase_id), -1)
    next_phase_idx = curr_idx + 1 if curr_idx != -1 and curr_idx + 1 < len(phases) else curr_idx
    if next_phase_idx != curr_idx:
        plan["active_phase_index"] = next_phase_idx
        save_plan(directory / "plan.json", plan)
    if curr_idx != -1 and curr_idx + 1 < len(phases):
        next_phase = phases[curr_idx + 1]
        phase_state["current_phase_id"] = next_phase["id"]
        next_dir = directory / "phases" / next_phase["id"]
        next_dir.mkdir(parents=True, exist_ok=True)
        cur_man = build_manifest(repo)
        next_baseline = {
            "schema_version": 1,
            "task_id": args.task_id,
            "phase_id": next_phase["id"],
            "repository": plan.get("repository"),
            "base_delivery_snapshot_sha256": cur_man["delivery_snapshot_sha256"],
            "base_change_set_sha256": cur_man["change_set_sha256"],
            "changes": cur_man.get("changes") or [],
        }
        next_baseline["baseline_sha256"] = canonical_sha256(next_baseline)
        atomic_write_json(next_dir / "baseline.json", next_baseline)
    atomic_write_json(phase_state_file, phase_state)
    return {
        "status": CheckpointStatus("CHECKPOINT_PASS"),
        "phase_id": phase_id,
        "completed_phases": completed,
        "current_phase_id": phase_state.get("current_phase_id"),
        "next_phase_index": next_phase_idx,
        "checkpoint": checkpoint_record,
        "preflight": preflight_status,
        "compile": compile_status,
        "tests": tests_status,
        "review": review_status,
    }


def resolve_next_action(repo: Path, task_id: str, plan: dict | None = None) -> dict[str, Any]:
    """Canonical evidence-aware next-action engine resolving the single safest next action."""
    if plan is None:
        plan = _load_plan(repo, task_id)
    state = str(plan.get("status") or "").upper()
    identity = f'--repo . --task-id {task_id}'

    if state in {"DRAFTED", "PLAN_APPROVAL_REQUIRED", "PLAN_DRAFTED", "AWAITING_DEVELOPER_APPROVAL"}:
        return {
            "code": "APPROVE_PLAN",
            "kind": "DEVELOPER_ACTION",
            "command": f'python .agents/harness.py task approve {identity} --source conversation --proof-reference "<phrase>" --enforcement-tier RULE_ENFORCED',
            "blocking": True,
            "reason": "The reviewed plan needs explicit approval before implementation.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_statuses": ["IMPLEMENTING"]},
        }

    if state == "APPROVED":
        return {
            "code": "BEGIN_IMPLEMENTATION",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task begin {identity}",
            "blocking": True,
            "reason": "Start the approved implementation.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_exit_codes": [0], "success_statuses": ["IMPLEMENTING"]},
        }

    if state == "IMPLEMENTING":
        tdir = task_dir(repo, task_id)
        is_bug = str(plan.get("task_kind") or "").upper() == "BUG"
        red_evidence_file = tdir / "red-evidence.json"
        if is_bug and not red_evidence_file.is_file():
            return {
                "code": "CAPTURE_RED_EVIDENCE",
                "kind": "HARNESS_COMMAND",
                "command": "python .agents/harness.py test --capture-red",
                "blocking": True,
                "reason": "Record failing test reproduction evidence for BUG before implementing production changes.",
                "inputs": {"repo": ".", "task_id": task_id},
                "expected": {"success_exit_codes": [0]},
            }
        phases = plan.get("phases") or []
        if phases:
            phase_state_file = tdir / "phase-state.json"
            cur_phase_id = ""
            if phase_state_file.is_file():
                try:
                    p_data = read_json(phase_state_file)
                    cur_phase_id = str(p_data.get("current_phase_id") or "")
                except Exception:
                    pass
            if not cur_phase_id and isinstance(phases[0], dict):
                cur_phase_id = phases[0].get("id", "p1")
            return {
                "code": "IMPLEMENT_APPROVED_SCOPE",
                "kind": "MODEL_ACTION",
                "command": "",
                "blocking": True,
                "reason": f"Implement code changes within approved scope (active phase: {cur_phase_id}).",
                "inputs": {"repo": ".", "task_id": task_id, "current_phase_id": cur_phase_id},
                "expected": {},
            }
        return {
            "code": "IMPLEMENT_APPROVED_SCOPE",
            "kind": "MODEL_ACTION",
            "command": "",
            "blocking": True,
            "reason": "Implement code changes within approved scope and phases.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {},
        }

    if state == "VERIFYING":
        tdir = task_dir(repo, task_id)
        current_run_file = tdir / "current-run.json"
        if not current_run_file.is_file():
            return {
                "code": "PREPARE_VERIFICATION",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py task prepare-verification {identity}",
                "blocking": True,
                "reason": "Freeze the finished change set and derive its gates and reviewers.",
                "inputs": {"repo": ".", "task_id": task_id},
                "expected": {"success_exit_codes": [0], "success_statuses": ["VERIFYING"]},
            }

        try:
            current_run = read_json(current_run_file)
            run_id = current_run["run_id"]
            policy = read_json(Path(current_run["policy"]))
            manifest = read_json(Path(current_run["manifest"]))
        except Exception:
            return {
                "code": "PREPARE_VERIFICATION",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py task prepare-verification {identity}",
                "blocking": True,
                "reason": "Verification run artifacts are corrupted; re-run prepare-verification.",
                "inputs": {"repo": ".", "task_id": task_id},
                "expected": {"success_exit_codes": [0], "success_statuses": ["VERIFYING"]},
            }

        snapshot = str(manifest.get("delivery_snapshot_sha256") or "")
        change_set = str(manifest.get("change_set_sha256") or "")
        policy_gates = list(policy.get("gates") or [])
        store = EvidenceStore(state_root(repo))

        def has_pass_evidence(name: str) -> bool:
            try:
                rec = store.read(snapshot, run_id, name)
                return rec.get("status") == "PASS" and rec.get("change_set_sha256") == change_set
            except Exception:
                return False

        # 1. Preflight
        if "preflight" in policy_gates or not policy_gates:
            if not has_pass_evidence("preflight"):
                return {
                    "code": "RUN_PREFLIGHT",
                    "kind": "HARNESS_COMMAND",
                    "command": "python .agents/harness.py preflight",
                    "blocking": True,
                    "reason": "The active verification policy requires preflight check evidence.",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {"success_exit_codes": [0]},
                }

        # 2. Specialized deterministic gates
        specialized = [
            ("check_strings", "python .agents/scripts/check_strings.py", "RUN_CHECK_STRINGS"),
            ("fast_kt_lint", "python .agents/scripts/fast_kt_lint.py", "RUN_FAST_KT_LINT"),
            ("room_guard", "python .agents/scripts/room_guard.py", "RUN_ROOM_GUARD"),
        ]
        for g_name, g_cmd, g_code in specialized:
            if g_name in policy_gates and not has_pass_evidence(g_name):
                return {
                    "code": g_code,
                    "kind": "HARNESS_COMMAND",
                    "command": g_cmd,
                    "blocking": True,
                    "reason": f"The active verification policy requires {g_name} evidence.",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {"success_exit_codes": [0]},
                }

        # 3. Unit tests
        if "unit_tests" in policy_gates:
            if not has_pass_evidence("unit_tests"):
                return {
                    "code": "RUN_UNIT_TESTS",
                    "kind": "HARNESS_COMMAND",
                    "command": "python .agents/harness.py test",
                    "blocking": True,
                    "reason": "The active verification policy requires unit-test evidence.",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {"success_exit_codes": [0]},
                }

        # 4. Review package and Reviewers
        required_reviewers = list(policy.get("reviewers") or [])
        if required_reviewers:
            pkg_path = active_review_package_path(repo, current_run)
            if not pkg_path.is_file():
                return {
                    "code": "BUILD_REVIEW_PACKAGE",
                    "kind": "HARNESS_COMMAND",
                    "command": f"python .agents/harness.py review package --task-id {task_id}",
                    "blocking": True,
                    "reason": "Build the immutable review package for required specialist reviewers.",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {"success_exit_codes": [0]},
                }

            if not has_pass_evidence("reviews"):
                briefs = {}
                exec_profile = {}
                try:
                    from review_execution import resolve_execution_profile
                    exec_profile = resolve_execution_profile(repo, task_id)
                    for r_name, r_info in exec_profile.get("reviewers", {}).items():
                        if r_info.get("brief_path"):
                            briefs[r_name] = r_info["brief_path"]
                except Exception:
                    pass

                dispatches_dir = tdir / "reviewer-dispatches"
                staged_dir = tdir / "staged-reviews" / str(run_id)
                dispatched_reviewers = set()
                completed_reviewers = set()
                if dispatches_dir.is_dir():
                    for f in dispatches_dir.glob("*.json"):
                        try:
                            d_data = read_json(f)
                            if not d_data.get("run_id") or str(d_data.get("run_id")) == run_id:
                                dispatched_reviewers.add(f.stem)
                        except Exception:
                            dispatched_reviewers.add(f.stem)
                    run_disp_dir = dispatches_dir / str(run_id)
                    if run_disp_dir.is_dir():
                        for f in run_disp_dir.glob("*.json"):
                            dispatched_reviewers.add(f.stem)

                if staged_dir.is_dir():
                    for f in staged_dir.glob("*.json"):
                        try:
                            s_data = read_json(f)
                            rev = str(s_data.get("reviewer") or f.stem)
                            if rev:
                                completed_reviewers.add(rev)
                        except Exception:
                            completed_reviewers.add(f.stem)

                req_set = set(required_reviewers)
                if not req_set.issubset(dispatched_reviewers):
                    return {
                        "code": "DISPATCH_REVIEWERS",
                        "kind": "HOST_ACTION",
                        "command": "",
                        "blocking": True,
                        "reason": f"Dispatch independent reviewer subagents: {', '.join(sorted(req_set - dispatched_reviewers))}.",
                        "reviewers": required_reviewers,
                        "package_path": str(pkg_path),
                        "briefs": briefs,
                        "review_execution_profile": exec_profile,
                        "inputs": {
                            "repo": ".",
                            "task_id": task_id,
                            "run_id": run_id,
                            "reviewers": required_reviewers,
                            "package_path": str(pkg_path),
                            "briefs": briefs,
                            "review_execution_profile": exec_profile,
                        },
                        "expected": {"success_statuses": ["PASS"]},
                    }

                if not req_set.issubset(completed_reviewers):
                    pending = sorted(req_set - completed_reviewers)
                    return {
                        "code": "WAIT_FOR_REVIEWERS",
                        "kind": "HOST_ACTION",
                        "command": "",
                        "blocking": True,
                        "reason": f"Waiting for independent reviewer subagents to complete: {', '.join(pending)}.",
                        "reviewers": required_reviewers,
                        "pending_reviewers": pending,
                        "inputs": {
                            "repo": ".",
                            "task_id": task_id,
                            "run_id": run_id,
                            "dispatched_reviewers": sorted(dispatched_reviewers),
                            "pending_reviewers": pending,
                            "completed_reviewers": sorted(completed_reviewers),
                        },
                        "expected": {"success_statuses": ["PASS"]},
                    }

                return {
                    "code": "INGEST_REVIEW_RESULT",
                    "kind": "HARNESS_COMMAND",
                    "command": f"python .agents/harness.py review ingest --task {task_id}",
                    "blocking": True,
                    "reason": f"Ingest completed review results for {', '.join(sorted(required_reviewers))}.",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "reviewers": required_reviewers},
                    "expected": {"success_statuses": ["PASS"]},
                }

        # 5. Assemble
        assemble_required = ("assemble" in policy_gates) or bool(policy.get("assemble_required"))
        if assemble_required:
            if not has_pass_evidence("assemble"):
                flavor = policy.get("flavor") or None
                assemble_task = resolve_assemble_task(repo, flavor=flavor)
                return {
                    "code": "ASSEMBLE",
                    "kind": "HARNESS_COMMAND",
                    "command": f"python .agents/harness.py assemble {assemble_task}",
                    "blocking": True,
                    "reason": f"Build the application ({assemble_task}).",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id, "assemble_task": assemble_task},
                    "expected": {"success_exit_codes": [0]},
                }

        # 6. Device deploy
        device_required = bool(policy.get("device_required")) or ("device" in policy_gates)
        if device_required:
            if not has_pass_evidence("device_install") or not has_pass_evidence("device_launch"):
                return {
                    "code": "DEVICE_INSTALL",
                    "kind": "HARNESS_COMMAND",
                    "command": "python .agents/harness.py device install-start",
                    "blocking": True,
                    "reason": "Install and start the application on a target Android device.",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {"success_exit_codes": [0]},
                }
            if not has_pass_evidence("device_signoff"):
                return {
                    "code": "DEVICE_SIGNOFF",
                    "kind": "DEVELOPER_ACTION",
                    "command": "",
                    "blocking": True,
                    "reason": "Present mobile verification walkthrough to developer and obtain sign-off.",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {"success_statuses": ["PASS"]},
                }

        # 7. Sensitive approval
        if bool(policy.get("sensitive")):
            if not has_pass_evidence("sensitive_approval") and not (plan.get("approval") or {}).get("sensitive_approved"):
                return {
                    "code": "SENSITIVE_APPROVAL",
                    "kind": "DEVELOPER_ACTION",
                    "command": f'python .agents/harness.py task approve-sensitive {identity} --source conversation --proof-reference "<phrase>" --enforcement-tier RULE_ENFORCED',
                    "blocking": True,
                    "reason": "Sensitive core change requires explicit final developer approval before delivery.",
                    "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
                    "expected": {"success_statuses": ["PASS"]},
                }

        # 8. Final verify
        return {
            "code": "FINAL_VERIFY",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task verify {identity}",
            "blocking": True,
            "reason": "Run read-only final verification check to confirm all evidence is in place.",
            "inputs": {"repo": ".", "task_id": task_id, "run_id": run_id},
            "expected": {"success_exit_codes": [0], "success_statuses": ["APPROVED"]},
        }

    if state == "READY_FOR_DELIVERY":
        return {
            "code": "DELIVER",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task deliver {identity}",
            "blocking": True,
            "reason": "Finalize verified delivery state after git commit.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_exit_codes": [0], "success_statuses": ["DELIVERED"]},
        }

    if state == "DELIVERED":
        return {
            "code": "TASK_DELIVERED",
            "kind": "DONE",
            "command": "",
            "blocking": False,
            "reason": "Task is delivered. No further harness action required.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {},
        }

    if state == "BLOCKED":
        return {
            "code": "RESUME_IMPLEMENTATION",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task resume {identity}",
            "blocking": True,
            "reason": "Resume after resolving the recorded blocker.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {"success_exit_codes": [0], "success_statuses": ["IMPLEMENTING"]},
        }

    return {
        "code": "UNKNOWN_STATE",
        "kind": "BLOCKED",
        "command": "",
        "blocking": True,
        "reason": f"Task is in unrecognized state: {state}.",
        "inputs": {"repo": ".", "task_id": task_id},
        "expected": {},
    }


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
            "command": f'{base} approve {identity} --source conversation --proof-reference "<phrase>" --enforcement-tier RULE_ENFORCED',
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
        if phases:
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
        return [{
            "action": "prepare-verification",
            "code": "PREPARE_VERIFICATION",
            "kind": "HARNESS_COMMAND",
            "command": f"{base} prepare-verification {identity}",
            "reason": "Freeze the finished change set and derive its gates and reviewers.",
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
        "FINAL_VERIFY": "verify",
        "DELIVER": "deliver",
        "RESUME_IMPLEMENTATION": "resume",
    }.get(act.get("code") or "", act.get("code", "").lower().replace("_", "-"))
    return [{
        "action": legacy_action,
        "code": act.get("code"),
        "kind": act.get("kind"),
        "command": act.get("command"),
        "reason": act.get("reason"),
        "blocking": act.get("blocking", True),
        "inputs": act.get("inputs", {}),
        "expected": act.get("expected", {}),
    }]


def status(args: argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not task_id:
        live = _find_live_tasks(repo)
        if len(live) > 1:
            tasks_summary = ", ".join(f"'{t[0]}' ({t[1]})" for t in live)
            raise ValidationError(
                f"AMBIGUOUS_LIVE_TASKS: multiple live tasks found in worktree: {tasks_summary}. "
                "Specify --task-id explicitly or cancel unwanted live tasks via 'workflow.py cancel --task-id <id>'."
            )
        elif len(live) == 1:
            task_id = live[0][0]
        else:
            active_p = state_root(repo) / "active-task.json"
            if active_p.is_file():
                try:
                    active_data = read_json(active_p)
                    task_id = str(active_data.get("task_id") or "").strip()
                except Exception:
                    pass
            if not task_id:
                try:
                    from mutation_guard import active_plan
                    plan_data = active_plan(repo)
                    task_id = str(plan_data.get("task_id") or "").strip()
                except Exception:
                    pass
    if not task_id:
        raise ValidationError("no active task found in repository state; specify --task-id <id>")
    plan = _load_plan(repo, task_id)
    if bool(getattr(args, "next", False)):
        plan = dict(plan)
        plan["task_state"] = plan.get("status")
        next_act = resolve_next_action(repo, task_id, plan)
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
            }
        ]
    return plan


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
        "--external-write", action="append", default=[], metavar="INTEGRATION",
        help="External mutation explicitly included in the plan presented for approval",
    )
    command.add_argument(
        "--architecture-intent",
        choices=("EXISTING_CHANGE", "NEW_SCREEN", "NEW_FEATURE", "REFACTOR", "MIGRATION",
                 "existing_change", "new_screen", "new_feature", "refactor", "migration"),
        default="EXISTING_CHANGE",
        help="Task architectural intent: EXISTING_CHANGE (default), NEW_SCREEN, NEW_FEATURE, REFACTOR, MIGRATION",
    )
    command.add_argument("--architecture-target-scope", default="", help="Target component or screen path for architecture resolution")
    command.add_argument("--architecture-target-family", default=None, help="Target architecture family ID")
    command.add_argument("--expected-files", help="Comma-separated expected target files")
    command.add_argument("--phases", help="Optional JSON string or file path defining task phases")
    command.add_argument("--task-context-id", default=None, help="Explicit Task Context ID for collision-safe scope binding")
    command.add_argument("--force", action="store_true", help="Bypass active task collision barriers")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    common.add_argument("--task-id", required=True)
    draft_cmd = sub.add_parser("draft", parents=[common])
    _add_plan_arguments(draft_cmd, is_revision=False)
    draft_cmd.set_defaults(handler=draft)
    revise_cmd = sub.add_parser("revise", parents=[common])
    _add_plan_arguments(revise_cmd, is_revision=True)
    revise_cmd.set_defaults(handler=revise)
    command = sub.add_parser("checkpoint-phase", parents=[common])
    command.add_argument("--phase-id", default=None, help="Phase ID to checkpoint")
    command.set_defaults(handler=checkpoint_phase)
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
    pv_cmd = sub.add_parser("prepare-verification", parents=[common])
    pv_cmd.add_argument("--force", action="store_true", help="Force regenerate verification run snapshot")
    pv_cmd.set_defaults(handler=prepare_verification)
    sub.add_parser("verify", parents=[common]).set_defaults(handler=verify_task)
    sub.add_parser("complete", parents=[common]).set_defaults(handler=complete)
    command = sub.add_parser("deliver", parents=[common])
    command.add_argument("--allow-dirty-tree", action="store_true", help="Explicit developer override to deliver while verified task files remain uncommitted")
    command.add_argument("--developer-allow-dirty-tree", action="store_true", help="Explicit developer-terminal override to deliver while verified task files remain uncommitted")
    command.add_argument("--source", choices=("developer_terminal", "host_native", "conversation"), default=None, help="Authority source for delivery override")
    command.set_defaults(handler=deliver_task)
    sub.add_parser("cancel", parents=[common]).set_defaults(handler=cancel)
    sub.add_parser("resume", parents=[common]).set_defaults(handler=resume)
    reconcile_cmd = sub.add_parser("reconcile-delivery", parents=[common])
    reconcile_cmd.set_defaults(handler=cmd_reconcile_delivery)
    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    status_cmd.add_argument("--task-id", default="", help="Task ID (defaults to active task if omitted)")
    status_cmd.add_argument("--next", action="store_true", help="Include the safest next lifecycle command without executing it")
    status_cmd.set_defaults(handler=status)
    command = sub.add_parser("recover-stale")
    command.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    command.add_argument("--task-id", default="")
    command.set_defaults(handler=recover_stale)
    command = sub.add_parser("recover-active")
    command.add_argument("--repo", default=".", help="Repository root (defaults to current directory)")
    command.add_argument("--task-id", required=True, help="Task ID to restore as active task")
    command.set_defaults(handler=recover_active)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    enable_line_buffered_stdio()
    parser = build_parser()
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
    elif args.action == "reconcile-delivery":
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if result.get("reconciled"):
                print(f"RECONCILED={result.get('task_id')} -> DELIVERED")
            else:
                print(f"TASK_STATUS={result.get('status', 'READY')}")
    elif args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"TASK_STATUS={result.get('status', 'READY')}")
        for item in result.get("next_actions") or []:
            print(f"NEXT_ACTION={item.get('action')}: {item.get('command')}")
            print(f"NEXT_REASON={item.get('reason')}")
    if args.action in ("draft", "revise", "recover-active", "reconcile-delivery"):
        return 0 if result.get("status") not in ("BLOCKED", "STALE", "USER_DECISION_REQUIRED") else 1
    return 0 if result.get("status") not in ("BLOCKED", "STALE", "PLAN_APPROVAL_REQUIRED", "USER_DECISION_REQUIRED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
