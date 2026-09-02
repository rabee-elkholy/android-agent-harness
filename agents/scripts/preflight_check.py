"""Preflight: hook selftest, string parity, Room migrations, fast Kotlin lint.

Usage: python .agents/scripts/preflight_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print, run_streaming  # noqa: E402
from _repo_files import REPO, changed_paths, ensure_local_git_privacy  # noqa: E402
from risk_tier import check_risk_approval  # noqa: E402
from room_guard import check_room_working_tree  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent


def run_step(title: str, script_name: str) -> int:
    live_print(f"\n{title}")
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
    ensure_local_git_privacy(REPO)
    live_print("==================================================")
    live_print("[Preflight] Harness preflight verification")
    live_print("==================================================")

    modified = [p.relative_to(REPO).as_posix() for p in changed_paths()]
    live_print(f"[*] Working-tree files (including untracked): {len(modified)}")

    hook_code = run_step("0. Checking harness hook selftest (cached)...", "ensure_hook_selftest.py")
    str_code = run_step("1. Checking String Parity...", "check_strings.py")

    live_print("\n2. Checking Room Database Migrations...")
    db_ok, db_msg = check_room_working_tree()
    live_print(f"[{'OK' if db_ok else 'FAIL'}] {db_msg}")

    lint_code = run_step("3. Checking Kotlin Syntax & Architectural Rules (Fast Lint)...", "fast_kt_lint.py")

    live_print("\n4. Checking Risk Tier & Human Approvals...")
    risk_ok, risk_tier_name, risk_msg = check_risk_approval(REPO)
    live_print(f"[{'OK' if risk_ok else 'FAIL'}] [{risk_tier_name}] {risk_msg}")

    live_print("\n==================================================")
    overall_pass = (hook_code == 0) and (str_code == 0) and db_ok and (lint_code == 0) and risk_ok
    write_gate_result("preflight", {
        "schema_version": 1,
        "status": "PASS" if overall_pass else "FAIL",
        "exit_code": 0 if overall_pass else 1,
        "git_sha": current_head_sha(),
        "steps": {
            "hook_selftest": hook_code,
            "string_parity": str_code,
            "room_migrations": db_ok,
            "fast_kt_lint": lint_code,
            "risk_approval": risk_ok,
        },
        "detail": "" if overall_pass else "preflight steps failed; see step exit codes",
    })
    if overall_pass:
        live_print("[SUCCESS] PREFLIGHT PASSED: ready for assembleDebug.")
        try:
            from check_kit_update import update_banner
            banner = update_banner()
            if banner:
                live_print("\n" + banner)
        except Exception:
            pass
        return 0
    live_print("[FAIL] PREFLIGHT FAILED: fix the issues above before assembling.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
