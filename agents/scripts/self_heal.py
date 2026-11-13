"""Self-Healing & Last-Known-Good State Rollback Engine for Android Agent Harness.

Ensures the harness state machine adapts to unexpected interruptions, corrupt
transient state files, stale verification runs, or post-verification edits by
stepping back ONLY the internal harness task state (`.agents/state/tasks/<id>/`)
to the nearest valid stable checkpoint while preserving:
- All developer code changes in the repository (never runs git reset/checkout)
- Plan approvals and execution nonces
- Completed phase checkpoints (`phase-state.json`)
- Previously passed reviewers and review call accounting

Every automatic heal event is recorded via `incident_reporter` so the harness
maintainer can inspect and resolve recurring edge cases.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _vnext_common import (  # noqa: E402
    HarnessError,
    ValidationError,
    atomic_write_json,
    read_json,
    state_root,
    task_dir,
    utc_now,
)
from plan_authority import save_plan, validate_plan_hash  # noqa: E402


def _snapshots_dir(repo: Path, task_id: str) -> Path:
    d = task_dir(repo, task_id) / "snapshots"
    if d.is_symlink() or not d.resolve().is_relative_to(task_dir(repo, task_id).resolve()):
        raise ValidationError("snapshot directory escapes task storage")
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_stable_snapshot(
    repo: Path,
    task_id: str,
    stage: str,
    *,
    plan: dict[str, Any] | None = None,
    phase_state: dict[str, Any] | None = None,
    current_run: dict[str, Any] | None = None,
) -> Path | None:
    """Persist a last-known-good state checkpoint for `task_id` at `stage`."""
    try:
        tdir = task_dir(repo, task_id)
        plan_file = tdir / "plan.json"
        if plan is None:
            if not plan_file.is_file():
                return None
            plan = read_json(plan_file)
        if phase_state is None:
            phase_file = tdir / "phase-state.json"
            phase_state = read_json(phase_file) if phase_file.is_file() else None
        if current_run is None:
            run_file = tdir / "current-run.json"
            current_run = read_json(run_file) if run_file.is_file() else None

        snap_dir = _snapshots_dir(repo, task_id)
        clean_stage = str(stage or plan.get("status") or "implementing").strip().lower().replace("_", "-")
        payload = {
            "schema_version": 1,
            "task_id": task_id,
            "stage": clean_stage,
            "saved_at": utc_now(),
            "plan": plan,
            "phase_state": phase_state,
            "current_run": current_run,
        }
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", clean_stage) or not _valid_snapshot(payload, task_id):
            return None
        stage_path = snap_dir / f"stable-{clean_stage}.json"
        atomic_write_json(stage_path, payload)
        atomic_write_json(snap_dir / "stable-latest.json", payload)
        return stage_path
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ValidationError):
        return None


def _valid_snapshot(data: Any, task_id: str) -> bool:
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        return False
    plan = data.get("plan")
    if data.get("task_id") != task_id or not isinstance(plan, dict) or plan.get("task_id") != task_id:
        return False
    if not validate_plan_hash(plan)[0]:
        return False
    approval = plan.get("approval")
    if plan.get("status") in {"APPROVED", "IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"}:
        if not isinstance(approval, dict) or approval.get("plan_sha256") != plan.get("plan_sha256"):
            return False
        nonce = approval.get("single_use_nonce")
        if not nonce or (plan.get("status") != "APPROVED" and plan.get("execution_nonce") != nonce):
            return False
    for key in ("phase_state", "current_run"):
        value = data.get(key)
        if value is not None and (not isinstance(value, dict) or value.get("task_id") != task_id):
            return False
    return True


def load_stable_snapshot(repo: Path, task_id: str, stage: str = "latest") -> dict[str, Any] | None:
    """Load a saved stable state checkpoint if present and valid."""
    try:
        snap_dir = task_dir(repo, task_id) / "snapshots"
        clean_stage = str(stage or "latest").strip().lower().replace("_", "-")
        target = snap_dir / f"stable-{clean_stage}.json"
        if (not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", clean_stage)
                or target.is_symlink() or not target.resolve().is_relative_to(task_dir(repo, task_id).resolve())
                or not target.is_file() or target.stat().st_size > 4 * 1024 * 1024):
            return None
        data = read_json(target)
        return data if _valid_snapshot(data, task_id) else None
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ValidationError):
        return None


def heal_task_state(
    repo: Path,
    task_id: str | None = None,
    *,
    reason: str = "",
    command: str = "heal",
    host: str | None = None,
    prepare_fresh_run: bool = False,
) -> dict[str, Any]:
    """Inspect and self-heal a stuck, stale, or inconsistent task state back to a stable step.

    Never mutates repository source files or Git history.
    """
    repo = Path(repo).resolve()
    sroot = state_root(repo)
    active_file = sroot / "active-task.json"

    # 1. Heal missing or corrupt active-task.json if a single live task exists
    resolved_tid = str(task_id or "").strip()
    healed_actions: list[str] = []

    if not resolved_tid:
        if active_file.is_file():
            try:
                active_data = read_json(active_file)
                resolved_tid = str(active_data.get("task_id") or "").strip()
            except (OSError, ValueError, ValidationError):
                healed_actions.append("repaired_corrupt_active_task_pointer")
                active_file.unlink(missing_ok=True)
        if not resolved_tid:
            from delivery_manifest import live_task_plans
            live = list(live_task_plans(repo))
            if len(live) == 1:
                resolved_tid = live[0][0]
                plan_p = live[0][2]
                atomic_write_json(active_file, {
                    "task_id": resolved_tid,
                    "plan_path": str(plan_p),
                    "updated_at": utc_now(),
                })
                healed_actions.append(f"restored_active_pointer:{resolved_tid}")

    if not resolved_tid:
        return {
            "status": "NOOP",
            "healed": bool(healed_actions),
            "actions": healed_actions,
            "message": "No active or live task found to heal.",
        }

    tdir = task_dir(repo, resolved_tid)
    plan_file = tdir / "plan.json"

    # 2. Heal corrupt plan.json from snapshots if needed
    plan: dict[str, Any] | None = None
    if plan_file.is_file():
        try:
            plan = read_json(plan_file)
        except (OSError, ValueError, ValidationError):
            snap = load_stable_snapshot(repo, resolved_tid, "latest")
            if snap and isinstance(snap.get("plan"), dict):
                plan = snap["plan"]
                save_plan(plan_file, plan)
                healed_actions.append("restored_corrupt_plan_from_snapshot")

    if not isinstance(plan, dict):
        return {
            "status": "UNRECOVERABLE",
            "task_id": resolved_tid,
            "healed": False,
            "actions": healed_actions,
            "message": f"Task '{resolved_tid}' has no readable plan.json or stable snapshot.",
        }

    status = str(plan.get("status") or "").upper()

    # 3. Ensure execution session is bound for the current host if missing
    if status in {"APPROVED", "IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"}:
        try:
            from host_continuation import load_session
            from review_sources import detected_current_host
            cur_host = host or detected_current_host()
            if cur_host and load_session(repo, resolved_tid) is None:
                from host_continuation import continue_task
                import contextlib
                import io
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    continue_task(argparse.Namespace(
                        repo=str(repo),
                        task_id=resolved_tid,
                        host=cur_host,
                        source_stopped=False,
                        expect_session=None,
                    ))
                healed_actions.append(f"bound_missing_host_session:{cur_host}")
        except (OSError, ValueError, ValidationError):
            pass

    # 3a. Clear stuck intra-wave retry cap in worker-friction.json while preserving Zero-Scratch worker-handoff.json
    if status == "IMPLEMENTING" and (tdir / "worker-friction.json").is_file():
        try:
            wf_doc = read_json(tdir / "worker-friction.json")
            if isinstance(wf_doc, dict) and isinstance(wf_doc.get("by_phase"), dict):
                cleared_iw = False
                for _pk, pb in wf_doc["by_phase"].items():
                    if isinstance(pb, dict) and int(pb.get("intra_wave_gate_failures") or 0) > 0:
                        pb["intra_wave_gate_failures"] = 0
                        cleared_iw = True
                if cleared_iw:
                    atomic_write_json(tdir / "worker-friction.json", wf_doc)
                    healed_actions.append("cleared_stuck_intra_wave_gate_counter")
        except (OSError, ValueError, ValidationError):
            healed_noop = None

    # 3b. Handle IMPLEMENTING phase-review ENV_BLOCKED in-place without losing phase progress
    if status == "IMPLEMENTING" and (tdir / "phase-state.json").is_file():
        try:
            from phase_review import PHASE_REVIEWING, compute_ledger_sha, get_phase_substate, load_phase_ledger, phase_ledger_file, phase_review_dir, phase_run_file
            from review_orchestrator import REVIEW_ENV_BLOCKED, REVIEW_NOT_DISPATCHED
            pstate_cur = read_json(tdir / "phase-state.json")
            cur_pid = str(pstate_cur.get("current_phase_id") or "").strip()
            if cur_pid and get_phase_substate(pstate_cur, cur_pid) == PHASE_REVIEWING:
                rdir_p = phase_review_dir(tdir, cur_pid)
                prun_f = phase_run_file(tdir, cur_pid)
                prun_id = str(read_json(prun_f).get("phase_review_run_id") or "") if prun_f.is_file() else ""
                ok_pl, _, pledger = load_phase_ledger(tdir, cur_pid, expected_run_id=prun_id or None)
                reset_proles: list[str] = []
                if ok_pl and isinstance(pledger, dict):
                    for r_role, r_entry in (pledger.get("reviewers") or {}).items():
                        if isinstance(r_entry, dict) and r_entry.get("state") == REVIEW_ENV_BLOCKED:
                            r_entry["state"] = REVIEW_NOT_DISPATCHED
                            r_entry["last_error"] = None
                            r_entry["last_error_code"] = None
                            r_entry.pop("execution_id", None)
                            r_entry.pop("execution_id_sha256", None)
                            if prun_id:
                                (rdir_p / "dispatch" / prun_id / f"{r_role}.json").unlink(missing_ok=True)
                            reset_proles.append(r_role)
                pm1 = rdir_p / "post-tool-reconcile-error.json"
                pm2 = (rdir_p / prun_id / "post-tool-reconcile-error.json") if prun_id else None
                had_pm = pm1.is_file() or bool(pm2 and pm2.is_file())
                pm1.unlink(missing_ok=True)
                if pm2:
                    pm2.unlink(missing_ok=True)
                if reset_proles and isinstance(pledger, dict):
                    pledger["ledger_sha256"] = compute_ledger_sha(pledger)
                    atomic_write_json(phase_ledger_file(tdir, cur_pid), pledger)
                    healed_actions.append(f"reset_env_blocked_phase_reviewers:{cur_pid}:{','.join(sorted(reset_proles))}")
                elif had_pm:
                    healed_actions.append(f"cleared_phase_post_tool_error_marker:{cur_pid}")
        except (OSError, ValueError, KeyError, ImportError, ValidationError):
            pass

    # 4. Handle VERIFYING state: corrupt current-run.json or STALE verification run
    if status == "VERIFYING":
        from _workflow import engine as _engine
        crun_file = tdir / "current-run.json"
        crun: dict[str, Any] | None = None
        if crun_file.is_file():
            try:
                crun = read_json(crun_file)
            except (OSError, ValueError, ValidationError):
                crun = None

        if crun is None:
            snap_ver = load_stable_snapshot(repo, resolved_tid, "verifying")
            if snap_ver and isinstance(snap_ver.get("current_run"), dict):
                crun = snap_ver["current_run"]
                atomic_write_json(crun_file, crun)
                healed_actions.append("restored_current_run_from_snapshot")

        # 4a. Unblock ENV_BLOCKED final reviewers in-place without discarding passed reviewers or Gradle evidence!
        if isinstance(crun, dict) and crun.get("run_id"):
            run_id_cur = str(crun["run_id"])
            try:
                from review_orchestrator import REVIEW_ENV_BLOCKED, REVIEW_NOT_DISPATCHED, dispatch_receipt_file, load_ledger, review_execution_dir, save_ledger
                ledger_cur = load_ledger(tdir, run_id_cur)
                revs_cur = ledger_cur.get("reviewers") or {}
                reset_roles: list[str] = []
                for r_role, r_entry in revs_cur.items():
                    if isinstance(r_entry, dict) and r_entry.get("state") == REVIEW_ENV_BLOCKED:
                        r_entry["state"] = REVIEW_NOT_DISPATCHED
                        r_entry["last_error"] = None
                        r_entry["last_error_code"] = None
                        r_entry.pop("execution_id", None)
                        r_entry.pop("execution_id_sha256", None)
                        dispatch_receipt_file(tdir, run_id_cur, r_role).unlink(missing_ok=True)
                        reset_roles.append(r_role)
                err_marker = review_execution_dir(tdir, run_id_cur) / "post-tool-reconcile-error.json"
                if reset_roles or err_marker.is_file():
                    err_marker.unlink(missing_ok=True)
                    if reset_roles:
                        save_ledger(tdir, run_id_cur, ledger_cur)
                        healed_actions.append(f"reset_env_blocked_reviewers:{','.join(sorted(reset_roles))}")
                    else:
                        healed_actions.append("cleared_post_tool_reconcile_error_marker")
            except (OSError, ValueError, KeyError, ImportError, ValidationError):
                pass

        freshness = _engine.verification_freshness(repo, resolved_tid, crun)
        if not freshness.get("fresh"):
            # Auto Step-Back to IMPLEMENTING while preserving passed reviewers and completed phases!
            if plan.get("approval") and plan.get("execution_nonce") == plan["approval"].get("single_use_nonce"):
                try:
                    from review_budget import settle_final_review_calls
                    settle_final_review_calls(repo, plan)
                except (OSError, ValueError, ValidationError):
                    pass
                plan["status"] = "IMPLEMENTING"
                plan["resumed_at"] = utc_now()
                plan["last_auto_heal"] = {
                    "from_status": "VERIFYING",
                    "to_status": "IMPLEMENTING",
                    "reason_code": freshness.get("reason_code", "STALE"),
                    "reason": freshness.get("reason", reason),
                    "healed_at": utc_now(),
                }
                save_plan(plan_file, plan)
                save_stable_snapshot(repo, resolved_tid, "implementing")
                status = "IMPLEMENTING"
                healed_actions.append(f"stepped_back_stale_verifying_to_implementing:{freshness.get('reason_code')}")

                if prepare_fresh_run:
                    try:
                        import contextlib
                        import io
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            _engine.prepare_verification(argparse.Namespace(
                                repo=str(repo),
                                task_id=resolved_tid,
                                host=host,
                            ))
                        plan = read_json(plan_file)
                        status = str(plan.get("status") or "VERIFYING")
                        save_stable_snapshot(repo, resolved_tid, "verifying")
                        healed_actions.append("prepared_fresh_delta_verification_run")
                    except (OSError, ValueError, ValidationError) as prep_exc:
                        healed_actions.append(f"stayed_at_implementing_for_reconciliation:{prep_exc}")

    # 5. Handle READY_FOR_DELIVERY when repository snapshot changed before commit
    elif status == "READY_FOR_DELIVERY":
        from _workflow import engine as _engine
        from delivery_manifest import build_manifest
        from delivery_equivalence import evaluate_post_ready_changes
        ready_snapshot = str(plan.get("ready_delivery_snapshot_sha256") or "")
        try:
            live_manifest = build_manifest(repo)
            live_snapshot = str(live_manifest.get("delivery_snapshot_sha256") or "")
        except (OSError, ValueError, HarnessError):
            live_manifest = {}
            live_snapshot = "modified" if reason else ""
        if ready_snapshot and live_snapshot and ready_snapshot != live_snapshot:
            eval_res = (
                evaluate_post_ready_changes(repo, resolved_tid, plan, live_manifest)
                if live_manifest
                else {"is_benign": False, "reason": reason or "POST_READY_SOURCE_MODIFIED"}
            )
            if eval_res.get("is_benign"):
                plan["post_ready_normalization"] = {
                    "accepted_at": utc_now(),
                    "ready_delivery_snapshot_sha256": ready_snapshot,
                    "live_delivery_snapshot_sha256": live_snapshot,
                    "normalized_files": eval_res.get("normalized_files") or [],
                }
                save_plan(plan_file, plan)
                healed_actions.append("normalized_benign_post_ready_changes")
            elif plan.get("approval") and plan.get("execution_nonce") == plan["approval"].get("single_use_nonce"):
                # Non-benign source edit before commit: step back cleanly to IMPLEMENTING (and optionally VERIFYING)
                plan["status"] = "IMPLEMENTING"
                plan["resumed_at"] = utc_now()
                plan.pop("ready_at", None)
                plan.pop("ready_delivery_snapshot_sha256", None)
                plan.pop("ready_change_set_sha256", None)
                plan.pop("ready_run_id", None)
                plan["last_auto_heal"] = {
                    "from_status": "READY_FOR_DELIVERY",
                    "to_status": "IMPLEMENTING",
                    "reason_code": eval_res.get("reason") or "POST_READY_SOURCE_MODIFIED",
                    "healed_at": utc_now(),
                }
                save_plan(plan_file, plan)
                save_stable_snapshot(repo, resolved_tid, "implementing")
                status = "IMPLEMENTING"
                healed_actions.append("stepped_back_modified_ready_to_implementing")
                if prepare_fresh_run:
                    try:
                        import contextlib
                        import io
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            _engine.prepare_verification(argparse.Namespace(
                                repo=str(repo),
                                task_id=resolved_tid,
                                host=host,
                            ))
                        plan = read_json(plan_file)
                        status = str(plan.get("status") or "VERIFYING")
                        save_stable_snapshot(repo, resolved_tid, "verifying")
                        healed_actions.append("prepared_fresh_delta_verification_run")
                    except (OSError, ValueError, ValidationError):
                        pass

    if healed_actions:
        try:
            from incident_reporter import record_incident
            record_incident(
                repo,
                code="AUTO_HEAL_TRIGGERED",
                command=command,
                message=reason or "; ".join(healed_actions),
                task_id=resolved_tid,
                task_state=status,
                healed=True,
                heal_action=", ".join(healed_actions),
                auto_submit=False,
            )
        except (OSError, ValueError, ImportError):
            pass

    next_act: dict[str, Any] = {}
    try:
        from workflow import resolve_next_action
        next_act = resolve_next_action(repo, resolved_tid, plan, host=host)
    except (OSError, ValueError, ValidationError):
        next_act = {}

    return {
        "status": "HEALED" if healed_actions else "HEALTHY",
        "task_id": resolved_tid,
        "task_state": status,
        "to_status": status,
        "healed": bool(healed_actions),
        "actions": healed_actions,
        "preserved_review_calls_used": int(plan.get("review_calls_used") or 0),
        "preserved_review_rounds": int(plan.get("review_rounds") or 0),
        "next_action": next_act,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Self-heal stuck or stale task state back to the nearest stable checkpoint.")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--task-id", default=None, help="Task ID (defaults to active task)")
    parser.add_argument("--host", default=None, help="Host identifier")
    parser.add_argument("--prepare-fresh-run", action="store_true", help="Automatically prepare a fresh verification run after stepping back")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)

    result = heal_task_state(
        Path(args.repo).resolve(),
        args.task_id,
        command="task heal",
        host=args.host,
        prepare_fresh_run=args.prepare_fresh_run,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"HEAL_STATUS={result['status']} TASK={result.get('task_id', '')} STATE={result.get('task_state', '')}")
        if result.get("actions"):
            print("HEAL_ACTIONS=" + ", ".join(result["actions"]))
        nxt = result.get("next_action") or {}
        if nxt.get("code"):
            print(f"NEXT_ACTION={nxt.get('code')}: {nxt.get('command') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
