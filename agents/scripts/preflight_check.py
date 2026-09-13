"""Offline preflight: hook integrity plus policy-selected deterministic checks.

Usage: python .agents/scripts/preflight_check.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print, run_streaming, step_progress  # noqa: E402
from _repo_files import REPO, changed_paths, working_tree_fingerprint  # noqa: E402
from room_guard import check_room_working_tree  # noqa: E402
from change_classifier import classify  # noqa: E402
from mutation_guard import active_plan  # noqa: E402
from _vnext_common import ValidationError  # noqa: E402
from workflow import state_root, task_dir  # noqa: E402
from _vnext_common import read_json  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent


def run_step(title: str, script_name: str) -> int:
    with step_progress(title):
        code, _, _ = run_streaming(
            [sys.executable, str(SCRIPTS_DIR / script_name)],
            cwd=str(REPO),
            heartbeat_sec=10.0,
            should_echo=lambda line: bool(line.strip()),
            label=script_name,
        )
    return code


def main() -> int:
    enable_line_buffered_stdio()
    diagnostic = "--diagnostic" in sys.argv
    live_print("==================================================")
    live_print("[Preflight] Harness preflight verification")
    live_print("==================================================")

    modified = [p.relative_to(REPO).as_posix() for p in changed_paths()]
    live_print(f"[*] Working-tree files (including untracked): {len(modified)}")

    selected_gates = {"preflight", "localization", "room"}
    if not diagnostic and os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") != "1":
        try:
            active = read_json(state_root(REPO) / "active-task.json")
            t_dir = task_dir(REPO, str(active["task_id"]))
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
    skip_hook = diagnostic or "--skip-hook-selftest" in sys.argv or os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") == "1"
    hook_code = 0 if skip_hook else run_step("0. Hook selftest (cached)", "ensure_hook_selftest.py")
    str_code = run_step("1. String parity", "check_strings.py") if "localization" in selected_gates else 0

    import time as _time
    live_print("⏳ [IN PROGRESS] 2. Room Database Migrations")
    _t2 = _time.time()
    db_ok, db_msg = check_room_working_tree() if "room" in selected_gates else (True, "not required by policy")
    live_print(f"[{'OK' if db_ok else 'FAIL'}] {db_msg}")
    live_print(f"{'✅ [DONE]' if db_ok else '❌ [FAIL]'} 2. Room Database Migrations ({_time.time() - _t2:.1f}s)")

    lint_code = run_step("3. Kotlin Syntax & Architectural Rules (Fast Lint)", "fast_kt_lint.py") if selected_gates - {"manifest", "preflight", "localization", "room"} else 0

    classification = classify(REPO)
    risk_tier_name = classification["severity"]
    live_print("⏳ [IN PROGRESS] 4. Approved plan authority")
    _t4 = _time.time()
    if diagnostic:
        risk_ok, risk_msg = True, "diagnostic mode; task approval is checked only during delivery preflight"
    elif os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") == "1":
        risk_ok, risk_msg = True, "selftest fixture"
    else:
        try:
            plan = active_plan(REPO)
            approval = plan.get("approval") or {}
            risk_ok = (
                plan.get("status") in ("IMPLEMENTING", "VERIFYING")
                and plan.get("execution_nonce")
                and plan.get("execution_nonce") == approval.get("single_use_nonce")
                and approval.get("plan_sha256") == plan.get("plan_sha256")
            )
            risk_msg = "approved task plan is active" if risk_ok else "active task approval is missing or stale"
        except ValidationError as exc:
            risk_ok, risk_msg = False, str(exc)
    live_print(f"[{'OK' if risk_ok else 'FAIL'}] [{risk_tier_name}] {risk_msg}")
    live_print(f"{'✅ [DONE]' if risk_ok else '❌ [FAIL]'} 4. Approved plan authority ({_time.time() - _t4:.1f}s)")

    live_print("\n==================================================")
    overall_pass = (hook_code == 0) and (str_code == 0) and db_ok and (lint_code == 0) and risk_ok
    common = {
        "schema_version": 2,
        "producer": "preflight_check",
        "status": "PASS" if overall_pass else "FAIL",
        "exit_code": 0 if overall_pass else 1,
        "git_sha": current_head_sha(),
        "working_tree_fingerprint": working_tree_fingerprint(REPO),
        "steps": {
            "hook_selftest": hook_code,
            "string_parity": str_code,
            "room_migrations": db_ok,
            "fast_kt_lint": lint_code,
            "risk_approval": risk_ok,
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
