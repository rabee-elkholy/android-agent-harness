"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


def recover_stale(args: _engine.argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    active_path = _engine.state_root(repo) / "active-task.json"
    if not active_path.is_file():
        return {"status": "NOOP", "cleared_active_task": False, "message": "no active task to recover"}
    try:
        active = _engine.read_json(active_path)
    except Exception:
        active_path.unlink(missing_ok=True)
        return {"status": "RECOVERED", "cleared_active_task": True, "reason": "corrupt_active_task_json"}

    tid = str(active.get("task_id") or getattr(args, "task_id", "") or "")
    if not tid:
        active_path.unlink(missing_ok=True)
        return {"status": "RECOVERED", "cleared_active_task": True, "reason": "missing_task_id"}

    plan_path = _engine._plan_path(repo, tid)
    if not plan_path.is_file():
        active_path.unlink(missing_ok=True)
        return {"status": "RECOVERED", "cleared_active_task": True, "reason": "missing_plan_file"}

    try:
        plan = _engine.read_json(plan_path)
    except Exception:
        active_path.unlink(missing_ok=True)
        return {"status": "RECOVERED", "cleared_active_task": True, "reason": "corrupt_plan_json"}

    status_val = str(plan.get("status") or "")
    if _engine.is_live_task_status(status_val):
        raise _engine.ValidationError(
            f"Cannot auto-recover healthy active task '{tid}' in status '{status_val}'. "
            "Explicit developer cancellation is required."
        )

    active_path.unlink(missing_ok=True)
    return {"status": "RECOVERED", "cleared_active_task": True, "reason": f"cleared_terminal_task_status_{status_val}"}
def resume(args: _engine.argparse.Namespace) -> dict:
    with _engine.StateLock(_engine.state_root(Path(args.repo).resolve())):
        return _engine._resume_locked(args)
def _ready_external_inputs_changed(repo: Path, task_id: str, run_id: str, live_manifest: dict) -> bool:
    if not run_id:
        return False
    _engine.validate_id(run_id, "run id")
    path = _engine.task_dir(repo, task_id) / f"manifest-{run_id}.json"
    if not path.is_file():
        return False  # Legacy READY plans may not have frozen run artifacts.
    frozen = _engine.read_json(path)
    return bool(frozen.get("external_inputs_sha256")) and frozen["external_inputs_sha256"] != live_manifest.get("external_inputs_sha256")
def _resume_locked(args: _engine.argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    _engine.assert_single_live_task(repo, allowed_task_id=args.task_id)
    _engine._clear_cancel_request(repo, args.task_id)
    plan = _engine._load_plan(repo, args.task_id)
    status = plan.get("status")

    if status == "READY_FOR_DELIVERY":
        ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
        ready_run_id = str(plan.get("ready_run_id") or "")
        if not ready_snapshot or not ready_run_id:
            tdir = _engine.task_dir(repo, args.task_id)
            crun_path = tdir / "current-run.json"
            if crun_path.is_file():
                try:
                    crun = _engine.read_json(crun_path)
                    if not ready_snapshot:
                        ready_snapshot = str(crun.get("delivery_snapshot_sha256") or "")
                    if not ready_run_id:
                        ready_run_id = str(crun.get("run_id") or "")
                except (OSError, ValueError, _engine.ValidationError):
                    pass
        live_manifest = _engine.build_manifest(repo)
        live_snapshot = str(live_manifest.get("delivery_snapshot_sha256") or "")
        unchanged = (not ready_snapshot or not live_snapshot or ready_snapshot == live_snapshot) and not _engine._ready_external_inputs_changed(repo, args.task_id, ready_run_id, live_manifest)
        # --reopen: the developer reviewed the verified diff and requested changes before committing.
        if unchanged and not getattr(args, "reopen", False):
            raise _engine.ValidationError(
                f"task '{args.task_id}' is in status 'READY_FOR_DELIVERY' with matching snapshot; resume is only permitted when delivery snapshot is stale. "
                f"If the developer requested changes before committing, reopen with: python .agents/harness.py task resume --task-id {args.task_id} --reopen"
            )
        if not plan.get("approval") or plan.get("execution_nonce") != plan["approval"].get("single_use_nonce"):
            raise _engine.ValidationError("the approved execution identity is no longer valid")
        from task_git_lineage import accept_requested_delivery_commit
        accept_requested_delivery_commit(repo, args.task_id, plan)
        if unchanged and ready_run_id and ready_snapshot:
            try:
                _engine.atomic_write_json(
                    _engine.task_dir(repo, args.task_id) / "reopen-carry.json",
                    {
                        "task_id": args.task_id,
                        "plan_sha256": plan.get("plan_sha256"),
                        "run_id": ready_run_id,
                        "delivery_snapshot_sha256": ready_snapshot,
                        "recorded_at": _engine.utc_now(),
                    },
                )
            except OSError:
                pass
        plan["status"] = "IMPLEMENTING"
        plan["resumed_at"] = _engine.utc_now()
        plan.pop("ready_at", None)
        plan.pop("ready_delivery_snapshot_sha256", None)
        plan.pop("ready_change_set_sha256", None)
        plan.pop("ready_run_id", None)
        _engine.save_plan(_engine._plan_path(repo, args.task_id), plan)
        wr_rec_f = _engine.task_dir(repo, args.task_id) / "web-relay-receipt.json"
        if wr_rec_f.is_file():
            try:
                wr_d = _engine.read_json(wr_rec_f)
                if isinstance(wr_d, dict):
                    wr_d["stale_after_reopen"] = True
                    _engine.atomic_write_json(wr_rec_f, wr_d)
            except (OSError, ValueError, _engine.ValidationError):
                pass
        _engine.atomic_write_json(_engine.state_root(repo) / "active-task.json", {"task_id": args.task_id, "plan_path": str(_engine._plan_path(repo, args.task_id)), "updated_at": _engine.utc_now()})
        return plan

    if status not in ("VERIFYING", "BLOCKED"):
        raise _engine.ValidationError("only a verifying or blocked task can resume implementation")
    if not plan.get("approval") or plan.get("execution_nonce") != plan["approval"].get("single_use_nonce"):
        raise _engine.ValidationError("the approved execution identity is no longer valid")
    from review_budget import settle_final_review_calls
    settle_final_review_calls(repo, plan)
    plan["status"] = "IMPLEMENTING"
    plan["resumed_at"] = _engine.utc_now()
    _engine.save_plan(_engine._plan_path(repo, args.task_id), plan)
    wr_rec_v = _engine.task_dir(repo, args.task_id) / "web-relay-receipt.json"
    if wr_rec_v.is_file():
        try:
            wr_dv = _engine.read_json(wr_rec_v)
            if isinstance(wr_dv, dict):
                wr_dv["resumed_from_verification"] = True
                _engine.atomic_write_json(wr_rec_v, wr_dv)
        except (OSError, ValueError, _engine.ValidationError):
            pass
    _engine.atomic_write_json(_engine.state_root(repo) / "active-task.json", {"task_id": args.task_id, "plan_path": str(_engine._plan_path(repo, args.task_id)), "updated_at": _engine.utc_now()})
    return plan
def finalize_ready_delivery(
    repo: Path,
    task_id: str,
    plan: dict | None = None,
    *,
    require_clean_tree: bool = False,
    live_manifest: dict | None = None,
) -> tuple[dict, bool]:
    """Centralized delivery finalizer.

    Validates:
    1. Task is in READY_FOR_DELIVERY.
    2. If require_clean_tree is True, no verified task files remain dirty/uncommitted in the working tree.
    3. If ready_delivery_snapshot_sha256 is present, the current repository delivery snapshot must match.

    Only then marks plan DELIVERED and clears active-task.json.
    """
    if plan is None:
        plan = _engine._load_plan(repo, task_id)
    if plan.get("status") == "DELIVERED":
        return plan, False
    if plan.get("status") != "READY_FOR_DELIVERY":
        raise _engine.ValidationError(f"task '{task_id}' is in status '{plan.get('status')}', not READY_FOR_DELIVERY")

    ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
    manifest = live_manifest if live_manifest is not None else (_engine.build_manifest(repo) if (require_clean_tree or ready_snapshot) else None)
    if require_clean_tree:
        dirty = _engine._find_uncommitted_task_files(repo, task_id, plan, live_manifest=manifest)
        if dirty:
            raise _engine.ValidationError(
                f"cannot deliver task '{task_id}' with dirty working tree; verified task files remain uncommitted: {', '.join(sorted(dirty))}"
            )

    live_identity = (manifest or {}).get("repository") or _engine.repository_identity(repo)
    for field in ("root_sha256", "git_common_dir_sha256", "branch"):
        approved_value = (plan.get("repository") or {}).get(field)
        if approved_value and live_identity.get(field) != approved_value:
            raise _engine.ValidationError(f"delivery repository identity mismatch: {field}")
    if ready_snapshot and manifest is not None:
        if plan.get("ready_run_id"):
            from delivery_equivalence import _ready_manifest
            _, frozen, _ = _ready_manifest(repo, task_id, plan)
            if frozen.get("external_inputs_sha256") != manifest.get("external_inputs_sha256"):
                raise _engine.ValidationError("delivery external inputs changed after verification")
        current_snapshot = manifest["delivery_snapshot_sha256"]
        if current_snapshot != ready_snapshot:
            from delivery_equivalence import evaluate_post_ready_changes
            eval_res = evaluate_post_ready_changes(repo, task_id, plan, manifest)
            if eval_res.get("is_benign"):
                plan["post_ready_normalization"] = {
                    "accepted_at": _engine.utc_now(),
                    "ready_delivery_snapshot_sha256": ready_snapshot,
                    "live_delivery_snapshot_sha256": current_snapshot,
                    "normalized_files": eval_res.get("normalized_files") or [],
                }
            else:
                changed = _engine.changed_since_verification(repo, task_id, plan, manifest)
                named = f" Changed after verification: {', '.join(changed[:10])}." if changed else ""
                diff_detail = f"\nDetails: {eval_res.get('diff_summary')}" if eval_res.get("diff_summary") else ""
                raise _engine.ValidationError(
                    f"delivery snapshot mismatch: current repository ({current_snapshot[:12]}) "
                    f"differs from verified ready snapshot ({ready_snapshot[:12]}). Content was modified after verification.{named}{diff_detail}\n"
                    "Git attributes normalize line endings when configured; unproven content differences still require verification.\n"
                    "Do not resume on your own: ask the developer whether to verify these changes (their own edits "
                    "before the commit count too)."
                )

    try:
        delivery_commit_sha = _engine.git_text(repo, "rev-parse", "HEAD")
    except Exception:
        delivery_commit_sha = ""
    if plan.get("ready_run_id") and delivery_commit_sha:
        from task_git_lineage import accept_requested_delivery_commit, is_valid_task_lineage
        accept_requested_delivery_commit(repo, task_id, plan)
        # Validate against the persisted plan plus a freshly validated delivery receipt.
        valid_lineage, reason = is_valid_task_lineage(repo, task_id, delivery_commit_sha)
        if not valid_lineage:
            raise _engine.ValidationError(
                f"{reason}. If the developer committed verified changes across multiple commits or alongside pre-existing files without modifying verified file contents, "
                f"confirm lineage in place (preserving READY_FOR_DELIVERY) via: "
                f"python .agents/harness.py task change-decision --task-id {task_id} --reconcile-lineage --reason \"Confirm developer delivery commit\" --apply --source conversation --proof-reference \"<developer confirmation>\""
            )
    plan = _engine.deliver_plan(plan)
    if delivery_commit_sha:
        plan["delivery_commit_sha"] = delivery_commit_sha
    _engine.save_plan(_engine._plan_path(repo, task_id), plan)
    active_path = _engine.state_root(repo) / "active-task.json"
    if active_path.is_file():
        try:
            active = _engine.read_json(active_path)
            if str(active.get("task_id") or "") == task_id:
                active_path.unlink(missing_ok=True)
        except Exception:
            active_path.unlink(missing_ok=True)
    from discovery_receipt import clear_latest_discovery_receipt
    clear_latest_discovery_receipt(repo)
    return plan, True
def reconcile_delivery(repo: Path, task_id: str | None = None) -> tuple[dict | None, str]:
    """Reconcile READY_FOR_DELIVERY task against clean committed repository state."""
    _engine.assert_single_live_task(repo, allowed_task_id=task_id)
    tid = task_id
    if not tid:
        tid = _engine._focused_task_id(repo)
    if not tid:
        return None, "NOOP"
    plan_p = _engine._plan_path(repo, tid)
    if not plan_p.is_file():
        return None, "NOOP"
    try:
        plan = _engine.read_json(plan_p)
    except Exception:
        return None, "NOOP"
    status_val = str(plan.get("status") or "")
    if status_val == "DELIVERED":
        return plan, "DELIVERED"
    if status_val != "READY_FOR_DELIVERY":
        return plan, status_val
    manifest = _engine.build_manifest(repo)
    dirty = _engine._find_uncommitted_task_files(repo, tid, plan, live_manifest=manifest)
    if dirty:
        return plan, "DIRTY_UNCOMMITTED"
    ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
    if ready_snapshot and manifest.get("delivery_snapshot_sha256") != ready_snapshot:
        from delivery_equivalence import evaluate_post_ready_changes
        eval_res = evaluate_post_ready_changes(repo, tid, plan, manifest)
        if not eval_res.get("is_benign"):
            return plan, "SNAPSHOT_MISMATCH"
    plan, _ = _engine.finalize_ready_delivery(repo, tid, plan, require_clean_tree=True, live_manifest=manifest)
    return plan, "DELIVERED"
def cmd_reconcile_delivery(args: _engine.argparse.Namespace) -> dict:
    repo = Path(args.repo).resolve()
    task_id = getattr(args, "task_id", None) or None
    plan, status_code = _engine.reconcile_delivery(repo, task_id)
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
def cmd_heal_task(args: _engine.argparse.Namespace) -> dict:
    from self_heal import heal_task_state
    repo = Path(args.repo).resolve()
    task_id = str(getattr(args, "task_id", "") or "").strip() or None
    reason = str(getattr(args, "reason", "") or "").strip()
    prepare_fresh = bool(getattr(args, "prepare_fresh_run", False))
    host = getattr(args, "host", None)
    return heal_task_state(
        repo,
        task_id=task_id,
        reason=reason,
        prepare_fresh_run=prepare_fresh,
        host=host,
    )
def installed_harness_version(repo: Path) -> str:
    root = repo / ".agents" if (repo / ".agents").is_dir() else repo / "agents"
    path = root / "VERSION"
    version = path.read_text(encoding="utf-8").strip() if path.is_file() else "1.0.0"
    if not version:
        raise _engine.ValidationError("installed harness version is empty")
    return version
def verification_engine_freshness(repo: Path, task_id: str, current: dict) -> dict:
    """Reject a preserved verification run after its evidence producer changes.

    Older runs did not freeze an engine version. The completed preserving-update
    journal establishes that those runs predate an engine replacement. Never
    rewrite their proof or infer that an engine update refreshed it.
    """
    try:
        live_version = _engine.installed_harness_version(repo)
        frozen_version = current.get("harness_version")
        if frozen_version is None:
            journal_path = repo / ".harness-setup/update-journal.json"
            if journal_path.is_file():
                journal = _engine.read_json(journal_path)
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
    except (OSError, ValueError, TypeError, AttributeError, _engine.ValidationError) as exc:
        return {"fresh": False, "reason_code": "HARNESS_VERSION_UNAVAILABLE",
                "reason": f"Cannot establish verification engine identity: {exc}"}
    return {"fresh": True, "reason_code": "FRESH"}
def verification_freshness(repo: Path, task_id: str, current_run: dict | None = None, *, allow_completed: bool = False) -> dict:
    """Non-mutating verification freshness resolver comparing live repository state with frozen run."""
    try:
        plan = _engine._load_plan(repo, task_id)
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
        directory = _engine.task_dir(repo, task_id)
        current_path = directory / "current-run.json"
        if not current_path.is_file():
            return {
                "fresh": False,
                "reason_code": "RUN_NOT_INITIALIZED",
                "reason": f"task '{task_id}' verification run is not initialized",
            }
        try:
            current = _engine.read_json(current_path)
        except Exception as exc:
            return {"fresh": False, "reason_code": "CURRENT_RUN_CORRUPTED", "reason": str(exc)}

    if str(current.get("task_id") or "") != task_id:
        return {
            "fresh": False,
            "reason_code": "TASK_MISMATCH",
            "reason": f"current-run task mismatch: expected '{task_id}', found '{current.get('task_id')}'",
        }

    engine = _engine.verification_engine_freshness(repo, task_id, current)
    if not engine["fresh"]:
        return engine

    manifest = _engine.build_manifest(repo)
    frozen_repo = current.get("repository")
    if not isinstance(frozen_repo, dict) and current.get("manifest"):
        # Runs created by earlier versions froze the repository identity only
        # inside their manifest. Keep those runs recoverable after an update.
        try:
            frozen_manifest = _engine.read_json(Path(current["manifest"]))
            if all(frozen_manifest.get(key) == current.get(key) for key in ("delivery_snapshot_sha256", "change_set_sha256")):
                frozen_repo = frozen_manifest.get("repository")
        except (OSError, ValueError):
            pass
    live_repo = manifest.get("repository") or {}
    if not isinstance(frozen_repo, dict):
        return {"fresh": False, "reason_code": "REPOSITORY_IDENTITY_MISSING", "reason": "verification run has no frozen repository identity"}
    is_ready_completed = bool(allow_completed and plan.get("status") == "READY_FOR_DELIVERY")
    repo_fields = ("root_sha256", "git_common_dir_sha256", "branch") if is_ready_completed else ("root_sha256", "git_common_dir_sha256", "branch", "head")
    for field in repo_fields:
        if frozen_repo.get(field) != live_repo.get(field):
            return {
                "fresh": False,
                "reason_code": "REPOSITORY_IDENTITY_CHANGED",
                "reason": f"STALE: repository {field} changed after verification freeze",
            }
    checks = [
        ("delivery_snapshot_sha256", "DELIVERY_SNAPSHOT_CHANGED"),
        *([] if is_ready_completed else [("change_set_sha256", "CHANGE_SET_CHANGED")]),
        ("external_inputs_sha256", "EXTERNAL_INPUTS_CHANGED"),
    ]
    for key, reason_code in checks:
        curr_val = current.get(key)
        if not curr_val and key == "external_inputs_sha256" and current.get("manifest"):
            try:
                curr_val = _engine.read_json(Path(current["manifest"])).get("external_inputs_sha256")
            except (OSError, ValueError, _engine.ValidationError):
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
    if task_cs and not is_ready_completed:
        try:
            task_baseline = _engine.load_task_baseline(repo, task_id)
            task_base_head = (
                plan.get("task_base_head")
                or ((task_baseline or {}).get("repository") or {}).get("head")
                or (plan.get("repository") or {}).get("head")
            )
            task_manifest = _engine.build_task_manifest(repo, task_baseline, expected_files=plan.get("expected_files"), live_manifest=manifest, task_base_head=task_base_head)
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
def assert_active_run_fresh(repo: Path, task_id: str, run_id: str | None = None, *, allow_completed: bool = False) -> dict:
    """Validate that the active verification run is fresh and matches current repository state."""
    plan = _engine._load_plan(repo, task_id)
    if plan.get("status") != "VERIFYING" and not (allow_completed and plan.get("status") == "READY_FOR_DELIVERY"):
        raise _engine.ValidationError(f"task '{task_id}' is in status '{plan.get('status')}', not VERIFYING")
    directory = _engine.task_dir(repo, task_id)
    current_path = directory / "current-run.json"
    if not current_path.is_file():
        try:
            from self_heal import load_stable_snapshot
            snap = load_stable_snapshot(repo, task_id, "verifying")
            if isinstance(snap, dict) and isinstance(snap.get("current_run"), dict):
                _engine.atomic_write_json(current_path, snap["current_run"])
        except (OSError, ValueError, ImportError, _engine.ValidationError):
            pass
    if not current_path.is_file():
        raise _engine.ValidationError(f"task '{task_id}' verification run is not initialized")
    try:
        current = _engine.read_json(current_path)
    except (OSError, ValueError, _engine.ValidationError):
        try:
            from self_heal import load_stable_snapshot
            snap = load_stable_snapshot(repo, task_id, "verifying")
            if isinstance(snap, dict) and isinstance(snap.get("current_run"), dict):
                _engine.atomic_write_json(current_path, snap["current_run"])
                current = snap["current_run"]
            else:
                raise
        except (OSError, ValueError, ImportError, _engine.ValidationError) as exc:
            raise _engine.ValidationError(f"task '{task_id}' current-run.json is corrupted: {exc}") from exc
    if str(current.get("task_id") or "") != task_id:
        raise _engine.ValidationError(f"current-run task mismatch: expected '{task_id}', found '{current.get('task_id')}'")
    active_run_id = str(current.get("run_id") or "")
    if run_id and active_run_id != run_id:
        raise _engine.ValidationError(f"verification run mismatch: expected run '{run_id}', found '{active_run_id}'")
    freshness = _engine.verification_freshness(repo, task_id, current, allow_completed=allow_completed)
    if not freshness.get("fresh"):
        raise _engine.ValidationError(freshness.get("reason", "Verification run is stale"))
    return current
def deliver_task(
    args_or_repo: _engine.argparse.Namespace | Path | str,
    task_id: str | None = None,
    *,
    allow_dirty_tree: bool = False,
    require_clean_tree: bool | None = None,
    source: str | None = None,
) -> dict:
    if isinstance(args_or_repo, (str, Path)):
        repo = Path(args_or_repo).resolve()
        tid = str(task_id or "")
        auth_source = source or _engine.os.environ.get("HARNESS_AUTHORITY_SOURCE")
        is_dirty_override = bool(allow_dirty_tree)
        if is_dirty_override and auth_source != "developer_terminal":
            raise _engine.ValidationError(
                "Dirty-tree delivery override requires explicit developer terminal authority via '--source developer_terminal'."
            )
        clean = require_clean_tree if require_clean_tree is not None else (not allow_dirty_tree)
    else:
        args = args_or_repo
        repo = Path(args.repo).resolve()
        tid = str(args.task_id)
        auth_source = getattr(args, "source", None) or _engine.os.environ.get("HARNESS_AUTHORITY_SOURCE")
        is_dirty_override = bool(getattr(args, "allow_dirty_tree", False) or getattr(args, "developer_allow_dirty_tree", False))
        if is_dirty_override and auth_source != "developer_terminal":
            raise _engine.ValidationError(
                "Dirty-tree delivery override requires explicit developer terminal authority via '--source developer_terminal'."
            )
        clean = require_clean_tree if require_clean_tree is not None else (not is_dirty_override)
    plan, _ = _engine.finalize_ready_delivery(repo, tid, require_clean_tree=clean)
    return plan
def plan_summary(plan: dict, plan_document: Path | None = None) -> str:
    """Canonical, reviewable text of the registered plan; the agent presents it verbatim for approval.

    The full redacted approval payload (bindings, skills, architecture contract) lives in the
    generated plan.md, which the summary links; the plan hash covers both.
    """
    authority = _engine.plan_payload(plan)

    def listed(values: Any) -> str:
        items = [str(_engine.redact(v)) for v in (values or []) if str(v)]
        return ", ".join(items) if items else "none"

    def displayed(value: Any, *, default: str = "none") -> str:
        if value in (None, "", [], {}):
            return default
        redacted = _engine.redact(value)
        if isinstance(redacted, (dict, list)):
            return _engine.json.dumps(redacted, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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

    if str(plan.get("task_kind") or "").upper() in _engine._CONFLICT_KIND_ALIASES:
        return False
    tdir = _engine.task_dir(repo, task_id)
    if (tdir / "task-start-failures.json").is_file() or (tdir / "red-evidence.json").is_file():
        return False
    try:
        base = _engine.load_task_baseline(repo, task_id) or {}
        if any(isinstance(c, dict) and c.get("status") == "U" for c in (base.get("changes") or [])):
            return False
        if (base.get("git_merge_state") or {}).get("unmerged_paths"):
            return False
    except (OSError, ValueError, _engine.ValidationError):
        pass
    return bool(set(plan.get("expected_surfaces") or []) & set(CODE_SURFACES))
def _compile_check_hint(repo: Path, task_changes) -> str:
    """P7: ask for a compile-only build before prepare-verification when source files changed.

    A compile error found after prepare-verification costs a full test-gate run and a resume;
    the compile task catches it in seconds. Returns "" when no source changed or when the
    project's build task cannot be turned into a compile task (no Gradle wrapper, unknown
    or non-assemble task), so the agent is never sent to a command that cannot work.
    """
    paths = [str((item or {}).get("path") or "") for item in (task_changes or []) if isinstance(item, dict)]
    if not any(path.lower().endswith(_engine._COMPILED_SUFFIXES) for path in paths):
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
        manifest = _engine.build_task_manifest(repo, _engine.load_task_baseline(repo, task_id), expected_files=plan.get("expected_files"))
    except Exception:
        return True
    return bool(manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes"))
def _task_has_production_changes(repo: Path, task_id: str, plan: dict) -> bool:
    """True when the task has already modified production source code (.kt/.java outside tests)."""
    try:
        from mutation_guard import _is_production_code

        manifest = _engine.build_task_manifest(repo, _engine.load_task_baseline(repo, task_id), expected_files=plan.get("expected_files"))
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
    history = _engine.task_dir(repo, task_id) / "plan-history"
    try:
        return any(_engine.read_json(path).get("approval") for path in history.glob("*.json"))
    except (OSError, ValueError, _engine.ValidationError):
        return False
def pre_existing_changes_line(repo: Path, plan: dict) -> str:
    """Name the developer's uncommitted files that predate the task (O66).

    Task deltas already exclude them, but a planned file among them carries the developer's
    own edits into the task's commit, and the developer should know that before approving.
    """
    try:
        baseline = _engine.load_task_baseline(repo, str(plan.get("task_id") or "")) or {}
    except Exception:
        return ""
    paths = sorted({str(item.get("path") or "") for item in baseline.get("changes") or [] if item.get("path")})
    paths = [path for path in paths if not path.startswith((".agents/", ".harness-"))]
    if not paths:
        return ""
    merge_state = baseline.get("git_merge_state") or {}
    unmerged = {
        str(p).replace("\\", "/").strip("/")
        for p in (merge_state.get("unmerged_paths") or [])
        if str(p).strip()
    } | {
        str(item.get("path") or "").replace("\\", "/").strip("/")
        for item in (baseline.get("changes") or [])
        if isinstance(item, dict) and item.get("status") == "U" and item.get("path")
    }
    if str(plan.get("task_kind") or "").upper() in _engine._CONFLICT_KIND_ALIASES or merge_state.get("merge_in_progress") or unmerged:
        auto_merged_count = len([p for p in paths if p not in unmerged])
        unmerged_list = ", ".join(sorted(unmerged)[:10]) or "none"
        return (
            f"MERGE_BASELINE={len(unmerged)} unmerged conflict file(s) ({unmerged_list}) "
            f"and {auto_merged_count} clean auto-merged/pre-existing file(s) recorded in baseline. "
            "Only the conflicted/planned files are in task scope; auto-merged baseline files remain untouched until the merge commit."
        )
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
def approval_brief(plan: dict, sensitive_advisory: str | None = None) -> str:
    """What the developer needs to decide on, once (the approval question shows this, not the full plan).

    A real approval question carried the plan twice (a translated summary, then every summary field
    verbatim, full paths, hashes, "Rollback", "External writes: none"). The full plan stays in plan.md.
    """
    authority = _engine.plan_payload(plan)
    files = [str(item) for item in authority.get("expected_files") or [] if str(item)]
    names = [Path(item).name for item in files]
    attention = sorted(set(authority.get("expected_surfaces") or []) & _engine.SENSITIVE_SURFACES)
    lines = [f"What changes: {_engine.redact(authority.get('approach') or plan.get('requested_outcome') or 'not stated')}"]
    phases = [phase for phase in authority.get("phases") or [] if isinstance(phase, dict)]
    if len(phases) > 1:
        lines.append("Phases: " + "; ".join(
            f"{index}. {_engine.redact(phase.get('title') or phase.get('description') or phase.get('id'))}"
            for index, phase in enumerate(phases, 1)))
    if plan.get("review_budget_forecast") and plan["review_budget_forecast"].get("status") != "WITHIN_LIMIT":
        from review_budget import forecast_summary
        lines.append(forecast_summary(plan["review_budget_forecast"]))
    if names:
        shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        lines.append(f"Files ({len(names)}): {shown}")
    reuse_cands = [
        c for c in (plan.get("reuse_candidates") or [])
        if isinstance(c, dict) and c.get("exact_symbol_match")
    ]
    if reuse_cands:
        shown_reuse = ", ".join(
            f"{c.get('symbol')} ({Path(str(c.get('existing_file') or '')).name})"
            for c in reuse_cands[:3]
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
        lines.append(f"Phone checks: {_engine.redact(device)}")
    from verification_contract import phone_e2e_setup
    e2e_setup = phone_e2e_setup(plan)
    if e2e_setup:
        lines.append("Phone E2E: " + e2e_setup["summary"])
    if "verification_contract" in authority:
        contract = authority["verification_contract"]
        lines.append("Acceptance criteria: " + "; ".join(
            f"{c['id']} ({'required' if c['required'] else 'advisory'}, {c['method']}): {_engine.redact(c['expected'])}"
            for c in contract["criteria"]))
        if contract["journeys"]:
            lines.append("Selected device replays: " + "; ".join(
                f"{j['id']}: {_engine.redact(j['purpose'])}; effects: {j['effects']}" for j in contract["journeys"]))
    risks = [str(_engine.redact(item)) for item in authority.get("risks") or [] if str(item)]
    if risks:
        lines.append(f"Risks: {'; '.join(risks)}")
    return "\n".join(["APPROVAL_BRIEF_BEGIN", *(f"- {line}" for line in lines), "APPROVAL_BRIEF_END"])
def _names(values: Any) -> set[str]:
    out = set()
    for item in values or []:
        out.add(str(item.get("id") or item.get("name") or item) if isinstance(item, dict) else str(item))
    return out
def revision_changes(old: dict, new: dict) -> list[str]:
    """Field-by-field changes between a superseded plan and its revision (P6: ask only about the change)."""
    lines = []
    for key, label in _engine._DIFF_FIELDS:
        before, after = _engine._names(old.get(key)), _engine._names(new.get(key))
        added, removed = sorted(after - before), sorted(before - after)
        if added or removed:
            parts = [f"+ {item}" for item in added] + [f"- {item}" for item in removed]
            lines.append(f"{label}: {', '.join(parts)}")
    for key, label in _engine._TEXT_FIELDS:
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
            run_id = str(_engine.read_json(_engine.task_dir(repo, task_id) / "current-run.json").get("run_id") or "")
        except (OSError, ValueError, _engine.ValidationError):
            return []
    try:
        _engine.validate_id(run_id, "run_id")
        ready = _engine.read_json(_engine.task_dir(repo, task_id) / f"manifest-{run_id}.json")
    except (OSError, ValueError, _engine.ValidationError):
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

    return compute_fix_delta(repo, _engine.task_dir(repo, task_id), previous_run_id, manifest, plan, _engine.skills_root(repo), _engine.project_kind(repo))
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
    from_content, _unread = _engine._planned_file_surfaces(repo, files)
    if "SENSITIVE_DATA" not in expected and _engine.re.search(
        r"\b(location|gps|geofence|biometric|healthconnect)\b",
        f"{outcome} {' '.join(files)}",
        _engine.re.I,
    ):
        for _rel in files:
            try:
                _raw_s = set(_engine.classify(repo, task_changes=[{"path": _rel}], candidate_paths=[_rel], progress=False).get("surfaces") or [])
            except (OSError, ValueError, KeyError, _engine.ValidationError):
                _raw_s = set()
            if "SENSITIVE_DATA" in _raw_s:
                from_content = set(from_content) | {"SENSITIVE_DATA"}
                break
    extra = sorted(from_content - set(expected))
    if not extra:
        return expected
    drifting = {item.split(":", 1)[1] for item in check_material_drift(
        {"expected_surfaces": expected, "requested_outcome": outcome}, extra) if item.startswith("surface:")}

    def skills_for(surfaces: list[str]) -> dict:
        return _engine.decide({**classification, "surfaces": surfaces}, _engine.skills_root(repo), project_kind=_engine.project_kind(repo), task_kind=task_kind)

    try:
        planned_skills = {"skills": skills_for(list(expected))["skills"]["skills"]}
        for surface in extra:
            if surface not in drifting and unplanned_mandatory_skills(planned_skills, skills_for([*expected, surface])):
                drifting.add(surface)
    except (OSError, ValueError, _engine.ValidationError):
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
            found = set(_engine.classify(repo, task_changes=[{"path": rel}], candidate_paths=[rel], progress=False).get("surfaces") or [])
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
    directory = _engine.task_dir(repo, result["task_id"])
    document = plan_document_path(directory)
    old: dict = {}
    superseded = str(result.get("supersedes_plan_sha256") or "")
    if action == "revise" and superseded and _engine._task_was_approved_before(repo, result["task_id"]):
        try:
            old = _engine.read_json(directory / "plan-history" / f"{superseded}.json")
        except (OSError, ValueError, _engine.ValidationError):
            old = {}
    reapproval = bool(old)
    sensitive = _engine.sensitive_planned_files_line(repo, result)
    if not reapproval:
        lines.append(_engine.approval_brief(result, sensitive_advisory=sensitive))
    lines.append(f"PLAN_HASH={str(result.get('plan_sha256') or '')[:12]}")
    if result.get("material_change_reason"):
        lines.append("MATERIAL_CHANGE_REASON=" + str(_engine.redact(result["material_change_reason"])))
    from review_models import model_choice_summary
    lines.append(model_choice_summary(repo, str(result["task_id"])))
    try:
        from execution_mode import resolve_effective_execution_mode
        em_eff = resolve_effective_execution_mode(repo, task_id=str(result["task_id"]), plan=result)
        if em_eff.get("mode") in ("normal", "web") and not em_eff.get("selection_required"):
            lines.append(
                f"Execution mode: {em_eff['mode']} (choice: {em_eff.get('choice') or 'default_local'}; {em_eff.get('reason') or ''})"
            )
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        pass
    if document.is_file():
        lines.append(f"PLAN_DOCUMENT_URI={Path(document).resolve().as_uri()}")
    pre_existing = _engine.pre_existing_changes_line(repo, result)
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
    readiness = result.get("readiness_assessment") if isinstance(result.get("readiness_assessment"), dict) else {}
    if readiness.get("path_grounding_warnings"):
        lines.append("PATH_GROUNDING_WARNINGS=" + " | ".join(str(w) for w in readiness["path_grounding_warnings"]))
    if readiness.get("phase_dag_warnings"):
        lines.append("PHASE_DAG_WARNINGS=" + " | ".join(str(w) for w in readiness["phase_dag_warnings"]))
    if action == "draft":
        try:
            from task_bridge import evaluate_rotation_advisory
            rot_adv = evaluate_rotation_advisory(repo, "FOLLOW_UP_BOUNDARY", task_id=str(result.get("task_id") or ""), plan=result)
            if rot_adv:
                lines.append(f"CONTEXT_ROTATION_RECOMMENDED={rot_adv.get('mode')}: {rot_adv.get('save_command')}")
                lines.append(f"CONTEXT_ROTATION_REASON={rot_adv.get('reason')}")
                if rot_adv.get("instructions"):
                    lines.append(f"CONTEXT_ROTATION_INSTRUCTIONS={rot_adv.get('instructions')}")
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            pass
    if reapproval:
        changes = _engine.revision_changes(old, result)
        lines.append("REVISION_CHANGES=" + ("; ".join(changes) if changes else "no scope change"))
        causes = old.get("material_drift_causes") or {}
        if causes:
            lines.append("DRIFT_CAUSES=" + "; ".join(f"{item} from {', '.join(files)}" for item, files in causes.items()))
        lines.append(_engine.REAPPROVAL_QUESTION_GUIDE)
    else:
        lines.append(_engine.APPROVAL_QUESTION_GUIDE)
    return lines
