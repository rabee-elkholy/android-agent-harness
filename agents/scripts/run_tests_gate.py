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
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baseline_capture import (  # noqa: E402
    load_baseline,
    parse_report,
)
from _env_codes import EXIT_ENV  # noqa: E402
from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _repo_files import REPO  # noqa: E402


def report_paths(repo: Path, task: str) -> list[Path]:
    parts = [item for item in task.strip().split(":") if item]
    if len(parts) >= 1:
        module = repo.joinpath(*parts[:-1])
        exact = module / "build" / "test-results" / parts[-1]
        return sorted(path for path in exact.rglob("*.xml") if path.is_file())
    return sorted(path for path in repo.glob("**/build/test-results/**/*.xml") if path.is_file() and "androidtest" not in path.as_posix().lower())


def collect_test_summary(repo: Path, task: str) -> dict[str, int]:
    totals = {"executed": 0, "skipped": 0, "failed": 0, "reports": 0}
    for report in report_paths(repo, task):
        try:
            root = ET.parse(report).getroot()
        except (OSError, ET.ParseError):
            continue
        suites = [root] if root.tag.endswith("testsuite") else list(root.findall(".//testsuite"))
        for suite in suites:
            tests = int(float(suite.attrib.get("tests", "0") or 0))
            skipped = int(float(suite.attrib.get("skipped", "0") or 0))
            failures = int(float(suite.attrib.get("failures", "0") or 0))
            errors = int(float(suite.attrib.get("errors", "0") or 0))
            totals["executed"] += max(0, tests - skipped)
            totals["skipped"] += skipped
            totals["failed"] += failures + errors
            totals["reports"] += 1
    return totals


def collect_task_failures(repo: Path, task: str) -> list[dict]:
    entries: dict[str, dict] = {}
    for report in report_paths(repo, task):
        for item in parse_report(report):
            entries[item["fingerprint"]] = item
    return sorted(entries.values(), key=lambda item: item["test_name"])


def report_signatures(repo: Path, task: str) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for path in report_paths(repo, task):
        try:
            stat = path.stat()
            result[path.resolve().as_posix()] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            continue
    return result


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
    unit_tests = baseline.get("unit_tests") or []
    known = {str(item.get("fingerprint") or "") for item in unit_tests if item.get("fingerprint")}
    # If baseline was captured before enhanced fingerprinting, allow fallback to legacy_fingerprint
    has_enhanced_schema = any(item.get("error_type") is not None for item in unit_tests)

    new_regressions: list[dict] = []
    ignored: list[dict] = []
    for item in failed:
        fp = item.get("fingerprint")
        leg_fp = item.get("legacy_fingerprint") or fp
        if fp in known:
            ignored.append(item)
        elif not has_enhanced_schema and leg_fp in known:
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
    reports_before = report_signatures(REPO, task)
    code = run_gradle([task])
    if code == EXIT_ENV:
        write_gate_result("unit_tests", {
            "schema_version": 2,
            "producer": "run_tests_gate",
            "status": "ENV",
            "exit_code": code,
            "env_class": "ENV",
            "git_sha": current_head_sha(),
            "detail": "unit-test Gradle run failed environmentally; see gradle log",
        })
        live_print(f"[FAIL] Unit-test gate blocked: gradle exited {code} (ENV).", err=True)
        return code

    head = current_head_sha()
    baseline = load_baseline()
    advisory = baseline_advisory(baseline, head)
    if advisory:
        live_print(advisory, err=True)

    failed = collect_task_failures(REPO, task)
    summary = collect_test_summary(REPO, task)
    reports_after = report_signatures(REPO, task)
    fresh_reports = any(reports_before.get(path) != signature for path, signature in reports_after.items())
    if code == 0 and summary["executed"] == 0:
        write_gate_result("unit_tests", {
            "schema_version": 2,
            "producer": "run_tests_gate",
            "status": "FAIL",
            "exit_code": 1,
            "env_class": "",
            "git_sha": head,
            "detail": "Gradle succeeded but zero tests were executed; required test evidence is absent",
            **summary,
        })
        live_print("[FAIL] Unit-test gate blocked: zero tests were executed.", err=True)
        return 1
    if code != 0 and (not failed or not fresh_reports):
        write_gate_result("unit_tests", {
            "schema_version": 2,
            "producer": "run_tests_gate",
            "status": "FAIL",
            "exit_code": code,
            "env_class": "",
            "git_sha": head,
            "detail": "unit-test Gradle failed without fresh failing-test reports; stale reports cannot satisfy the gate",
            **summary,
        })
        live_print(f"[FAIL] Unit-test gate blocked: gradle exited {code} (build/compilation failure).", err=True)
        return code

    if not failed and not baseline:
        write_gate_result("unit_tests", {
            "schema_version": 2,
            "producer": "run_tests_gate",
            "status": "PASS",
            "exit_code": 0,
            "env_class": "",
            "git_sha": head,
            "detail": "no failing tests in the parsed reports",
            **summary,
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
            "schema_version": 2,
            "producer": "run_tests_gate",
            "status": "FAIL",
            "exit_code": 1,
            "env_class": "",
            "git_sha": head,
            "detail": f"{len(new_regressions)} NEW_REGRESSION failure(s)",
            "new_regressions": [item["test_name"] for item in new_regressions],
            "baseline_ignored": len(ignored),
            "total_failed": len(failed),
            **summary,
        })
        return 1

    write_gate_result("unit_tests", {
        "schema_version": 2,
        "producer": "run_tests_gate",
        "status": "PASS",
        "exit_code": 0,
        "env_class": "",
        "git_sha": head,
        "detail": f"{len(ignored)} pre-existing failure(s) ignored via baseline ({baseline_size} known)",
        "baseline_ignored": len(ignored),
        "total_failed": len(failed),
        **summary,
    })
    live_print(f"[SUCCESS] Unit-test gate passed: {len(ignored)} failure(s) ignored via baseline, 0 new regressions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
