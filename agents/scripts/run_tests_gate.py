"""Unit-test delivery gate with baseline-aware regression classification.

Usage:
  python .agents/scripts/run_tests_gate.py

Runs the configured unit-test Gradle task, parses the JUnit XML reports, and
classifies every failure:

  NEW_REGRESSION    failed now and is absent from the baseline -> BLOCK (exit 1)
  BASELINE_IGNORED  failed now and is recorded in the baseline -> tolerated
                    (pre-existing debt, never reported as a regression)

Writes the `unit_tests` gate artifact consumed by final_verdict.py. When the
Gradle run fails environmentally, the exit-30 protocol applies unchanged.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baseline_capture import (  # noqa: E402
    collect_failures,
    load_baseline,
)
from _env_codes import EXIT_ENV  # noqa: E402
from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _repo_files import REPO  # noqa: E402


def baseline_advisory(baseline: dict | None, head: str) -> str:
    if not baseline:
        return ""
    baseline_commit = str(baseline.get("baseline_commit") or "")
    if not baseline_commit or not head:
        return ""
    if baseline_commit == head:
        return ""
    return (
        f"[!] BASELINE ADVISORY: baseline was captured at {baseline_commit[:12]}, "
        f"current HEAD is {head[:12]}. Pre-existing debt is still honored; "
        "refresh the baseline (clean tree + --approve) only when the developer asks."
    )


def classify_failures(failed: list[dict], baseline: dict | None) -> tuple[list[dict], list[dict], int]:
    if not baseline:
        return list(failed), [], 0
    known = {str(item.get("fingerprint") or "") for item in (baseline.get("unit_tests") or []) if item.get("fingerprint")}
    new_regressions: list[dict] = []
    ignored: list[dict] = []
    for item in failed:
        if item.get("fingerprint") in known:
            ignored.append(item)
        else:
            new_regressions.append(item)
    return new_regressions, ignored, len(known)


def main(argv=None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Baseline-aware unit-test delivery gate")
    parser.add_argument("task", nargs="?", default=None, help="Gradle unit-test task (default: _product UNIT_TEST_TASK)")
    args = parser.parse_args(argv)

    from baseline_capture import _unit_test_task
    from run_gradle_task import run_gradle

    task = args.task or _unit_test_task()
    live_print(f"[*] Unit-test gate: {task}")
    code = run_gradle([task])
    if code != 0:
        status = "ENV" if code == EXIT_ENV else "FAIL"
        write_gate_result("unit_tests", {
            "schema_version": 1,
            "status": status,
            "exit_code": code,
            "env_class": "ENV" if code == EXIT_ENV else "",
            "git_sha": current_head_sha(),
            "detail": "unit-test Gradle run failed; see gradle log",
        })
        live_print(f"[FAIL] Unit-test gate blocked: gradle exited {code} ({status}).", err=True)
        return code

    head = current_head_sha()
    baseline = load_baseline()
    advisory = baseline_advisory(baseline, head)
    if advisory:
        live_print(advisory, err=True)

    failed = collect_failures(REPO)
    if not failed and not baseline:
        write_gate_result("unit_tests", {
            "schema_version": 1,
            "status": "PASS",
            "exit_code": 0,
            "env_class": "",
            "git_sha": head,
            "detail": "no failing tests in the parsed reports",
        })
        live_print("[SUCCESS] Unit-test gate passed: no failures, no baseline.")
        return 0

    new_regressions, ignored, baseline_size = classify_failures(failed, baseline)
    if new_regressions:
        live_print(f"[FAIL] NEW_REGRESSION: {len(new_regressions)} test(s) failed that are absent from the baseline:", err=True)
        for item in new_regressions[:30]:
            live_print(f"  - {item['test_name']}  ({str(item.get('message') or '')[:120]})", err=True)
        if len(new_regressions) > 30:
            live_print(f"  ... and {len(new_regressions) - 30} more", err=True)
        write_gate_result("unit_tests", {
            "schema_version": 1,
            "status": "FAIL",
            "exit_code": 1,
            "env_class": "",
            "git_sha": head,
            "detail": f"{len(new_regressions)} NEW_REGRESSION failure(s)",
            "new_regressions": [item["test_name"] for item in new_regressions],
            "baseline_ignored": len(ignored),
            "total_failed": len(failed),
        })
        return 1

    write_gate_result("unit_tests", {
        "schema_version": 1,
        "status": "PASS",
        "exit_code": 0,
        "env_class": "",
        "git_sha": head,
        "detail": f"{len(ignored)} pre-existing failure(s) ignored via baseline ({baseline_size} known)",
        "baseline_ignored": len(ignored),
        "total_failed": len(failed),
    })
    live_print(f"[SUCCESS] Unit-test gate passed: {len(ignored)} failure(s) ignored via baseline, 0 new regressions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
