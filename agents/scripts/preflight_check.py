"""Offline preflight: hook integrity plus policy-selected deterministic checks.

Usage: python .agents/scripts/preflight_check.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print, run_streaming, step_progress, sublog  # noqa: E402
from _repo_files import REPO, changed_paths, working_tree_fingerprint  # noqa: E402
from room_guard import check_room_working_tree  # noqa: E402
from change_classifier import classify  # noqa: E402
from mutation_guard import active_plan  # noqa: E402
from _vnext_common import ValidationError  # noqa: E402
from workflow import state_root, task_dir  # noqa: E402
from _vnext_common import read_json  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent


def run_step(title: str, script_name: str, cwd: Path | None = None) -> int:
    with step_progress(title):
        code, _, _ = run_streaming(
            [sys.executable, str(SCRIPTS_DIR / script_name)],
            cwd=str(cwd or REPO),
            heartbeat_sec=10.0,
            should_echo=lambda line: bool(line.strip()),
            label=script_name,
        )
    return code


def main(argv: list[str] | None = None) -> int:
    enable_line_buffered_stdio()
    args_list = sys.argv[1:] if argv is None else argv
    diagnostic = "--diagnostic" in args_list
    repo_target = REPO
    task_id_arg = ""
    for idx, arg in enumerate(args_list):
        if arg == "--repo" and idx + 1 < len(args_list):
            repo_target = Path(args_list[idx + 1]).resolve()
            os.environ["HARNESS_REPO"] = str(repo_target)
            import _repo_files
            _repo_files.REPO = repo_target
        elif arg == "--task-id" and idx + 1 < len(args_list):
            task_id_arg = args_list[idx + 1]

    live_print("==================================================")
    live_print("[Preflight] Harness preflight verification")
    live_print("==================================================")

    modified = [p.relative_to(repo_target).as_posix() for p in changed_paths(repo=repo_target)]
    live_print(f"[*] Working-tree files (including untracked): {len(modified)}")

    selected_gates = {"preflight", "localization", "room"}
    task_changes: list | None = None
    if not diagnostic and os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") != "1":
        try:
            if task_id_arg:
                from workflow import _load_plan
                plan = _load_plan(repo_target, task_id_arg)
                task_id = task_id_arg
            else:
                plan = active_plan(repo_target)
                task_id = str(plan.get("task_id") or "")
            if task_id:
                from workflow import load_task_baseline, build_task_manifest
                base = load_task_baseline(repo_target, task_id)
                if base:
                    task_manifest = build_task_manifest(repo_target, base)
                    task_changes = task_manifest.get("task_changes")
                t_dir = task_dir(repo_target, task_id)
                current_p = t_dir / "current-run.json"
                if current_p.is_file():
                    current = read_json(current_p)
                    selected_gates = set(read_json(Path(current["policy"])).get("gates") or [])
                else:
                    prelim_p = t_dir / "preliminary-policy.json"
                    if prelim_p.is_file():
                        selected_gates = set(read_json(prelim_p).get("gates") or [])
        except Exception:
            selected_gates = {"preflight", "localization", "room"}
            task_changes = None

    if task_changes is not None:
        classification = classify(repo_target, task_changes=task_changes)
    else:
        classification = classify(repo_target)
    risk_tier_name = classification["severity"]
    task_surfaces = set(classification.get("surfaces") or [])

    task_change_paths = [
        (p.get("path", "") if isinstance(p, dict) else str(p))
        for p in (task_changes or [])
        if (p.get("path", "") if isinstance(p, dict) else str(p))
    ] if task_changes is not None else None

    task_touches_room = bool(
        task_surfaces & {"PERSISTENCE", "ROOM_SCHEMA"}
        or (task_change_paths and any("room" in p.lower() or "dao" in p.lower() or "entity" in p.lower() or "database" in p.lower() for p in task_change_paths))
    )

    skip_hook = diagnostic or "--skip-hook-selftest" in sys.argv or os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") == "1"
    hook_code = 0 if skip_hook else run_step("0. Hook selftest (cached)", "ensure_hook_selftest.py", cwd=repo_target)
    str_code = run_step("1. String parity", "check_strings.py", cwd=repo_target) if "localization" in selected_gates else 0

    with step_progress("2. Room Database Migrations"):
        if "room" not in selected_gates:
            db_ok, db_msg = True, "not required by policy"
        elif task_changes is not None and not task_touches_room:
            db_ok, db_msg = True, "room check not required for current task changes"
        else:
            task_paths = task_change_paths if task_change_paths is not None else None
            db_ok, db_msg = check_room_working_tree(repo_target, paths=task_paths)
        sublog(f"[{'OK' if db_ok else 'FAIL'}] {db_msg}")

    lint_code = run_step("3. Kotlin Syntax & Architectural Rules (Fast Lint)", "fast_kt_lint.py", cwd=repo_target) if selected_gates - {"manifest", "preflight", "localization", "room"} else 0
    with step_progress("4. Approved plan authority"):
        if diagnostic:
            risk_ok, risk_msg = True, "diagnostic mode; task approval is checked only during delivery preflight"
        elif os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") == "1":
            risk_ok, risk_msg = True, "selftest fixture"
        else:
            try:
                if task_id_arg:
                    from workflow import _load_plan
                    plan = _load_plan(repo_target, task_id_arg)
                else:
                    plan = active_plan(repo_target)
                approval = plan.get("approval") or {}
                risk_ok = (
                    plan.get("status") in ("IMPLEMENTING", "VERIFYING")
                    and plan.get("execution_nonce")
                    and plan.get("execution_nonce") == approval.get("single_use_nonce")
                    and approval.get("plan_sha256") == plan.get("plan_sha256")
                )
                risk_msg = "approved task plan is active" if risk_ok else "active task approval is missing or stale"
            except (ValidationError, OSError) as exc:
                risk_ok, risk_msg = False, str(exc)
        sublog(f"[{'OK' if risk_ok else 'FAIL'}] [{risk_tier_name}] {risk_msg}")

    # 5. Architecture Drift Verification (Fast Drift Check)
    with step_progress("5. Architecture Drift Check"):
        arch_ok = True
        arch_msg = "no architecture contract bound (exempted)"
        if not diagnostic and os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") != "1":
            contract = None
            try:
                plan = active_plan(repo_target)
                contract = plan.get("architecture_contract")
            except Exception:
                contract = None

            if contract:
                try:
                    from architecture_drift import check_architecture_drift
                    arch_ok, arch_msg, _ = check_architecture_drift(repo_target, contract, task_id=plan.get("task_id") if plan else None)
                except Exception as exc:
                    arch_ok = False
                    arch_msg = f"ARCHITECTURE_DRIFT_CHECK_ERROR: {exc}"
            else:
                arch_ok = True
                arch_msg = "no architecture contract bound (exempted)"
        sublog(f"[{'OK' if arch_ok else 'FAIL'}] [ARCHITECTURE] {arch_msg}")

    live_print("\n==================================================")
    overall_pass = (hook_code == 0) and (str_code == 0) and db_ok and (lint_code == 0) and risk_ok and arch_ok
    common = {
        "schema_version": 2,
        "producer": "preflight_check",
        "status": "PASS" if overall_pass else "FAIL",
        "exit_code": 0 if overall_pass else 1,
        "git_sha": current_head_sha(repo_target),
        "working_tree_fingerprint": working_tree_fingerprint(repo_target),
        "steps": {
            "hook_selftest": hook_code,
            "string_parity": str_code,
            "room_migrations": db_ok,
            "fast_kt_lint": lint_code,
            "risk_approval": risk_ok,
            "architecture_drift": arch_ok,
        },
        "detail": "" if overall_pass else "preflight steps failed; see step exit codes",
    }
    if not diagnostic:
        write_gate_result("preflight", common)
        if "localization" in selected_gates:
            write_gate_result("localization", {
                **common, "producer": "check_strings", "status": "PASS" if str_code == 0 else "FAIL",
                "exit_code": str_code, "detail": "string parity and localization gate",
            })
        if "room" in selected_gates:
            write_gate_result("room", {
                **common, "producer": "room_guard", "status": "PASS" if db_ok else "FAIL",
                "exit_code": 0 if db_ok else 1, "detail": db_msg,
            })
    if overall_pass:
        live_print("[SUCCESS] PREFLIGHT PASSED: ready for review packaging.")
        return 0
    live_print("[FAIL] PREFLIGHT FAILED: fix the issues above before review packaging.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
