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
from _live_process import enable_line_buffered_stdio, live_print, step_progress  # noqa: E402
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


def collect_executed_tests(repo: Path, task: str) -> list[str]:
    names: set[str] = set()
    for report in report_paths(repo, task):
        try:
            root = ET.fromstring(report.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for case in root.iter("testcase"):
            classname = str(case.get("classname") or "").strip()
            name = str(case.get("name") or "").strip()
            if classname and name:
                names.add(f"{classname}#{name}")
                names.add(f"{classname}.{name}")
                names.add(name)
            elif name:
                names.add(name)
            elif classname:
                names.add(classname)
    return sorted(names)


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


def resolve_target_task(repo: Path, requested_task: str | None) -> str:
    if requested_task:
        return requested_task
    from baseline_capture import _unit_test_task
    default_task = _unit_test_task()
    try:
        from _repo_files import changed_paths
        changed = changed_paths(repo=repo)
        if not changed:
            return default_task
        root_build_names = {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties", "libs.versions.toml"}
        if any(p.name in root_build_names or p.parent == repo for p in changed if p.suffix in {".gradle", ".kts", ".toml", ".properties"}):
            return default_task
        mods = set()
        for p in changed:
            rel = p.relative_to(repo).as_posix()
            if "/src/" in rel:
                mod_path = rel.split("/src/")[0]
                mod_name = ":" + mod_path.replace("/", ":") if mod_path and mod_path != "." else ":app"
                mods.add(mod_name)
        if len(mods) == 1 and ":app" not in mods:
            single_mod = list(mods)[0]
            task_suffix = default_task.split(":")[-1] if ":" in default_task else "testDebugUnitTest"
            return f"{single_mod}:{task_suffix}"
    except Exception:
        pass
    return default_task


def main(argv=None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Baseline-aware unit-test delivery gate")
    parser.add_argument("task", nargs="?", default=None, help="Gradle unit-test task (default: _product UNIT_TEST_TASK)")
    parser.add_argument("--capture-red", action="store_true", help="Record failing test reproduction evidence as RED evidence for BUG tasks")
    args = parser.parse_args(argv)

    from run_gradle_task import run_gradle

    task = resolve_target_task(REPO, args.task)
    live_print(f"[*] Unit-test gate: {task}")
    reports_before = report_signatures(REPO, task)
    outcome: dict = {}
    with step_progress(f"Running unit tests: {task}"):
        code = run_gradle([task], outcome=outcome)
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
    if getattr(args, "capture_red", False):
        if not failed:
            live_print("[FAIL] --capture-red requested but no failing tests were detected.", err=True)
            return 1
        repro_entries = [
            {
                "kind": "failing_test",
                "test_name": item.get("test_name"),
                "message": item.get("message"),
                "fingerprint": item.get("fingerprint"),
            }
            for item in failed
        ]
        try:
            from mutation_guard import active_plan
            from _vnext_common import canonical_sha256, read_json, utc_now, write_json
            from delivery_manifest import build_manifest, build_task_manifest, is_delivery_relevant, load_task_baseline

            plan = active_plan(REPO)
            task_id = str(plan.get("task_id") or "")
            if not task_id:
                live_print("[FAIL] --capture-red requires an active task plan.", err=True)
                return 1

            state = REPO / ".agents/state" if (REPO / ".agents").is_dir() else REPO / "agents/state"
            task_d = state / "tasks" / task_id
            task_d.mkdir(parents=True, exist_ok=True)

            baseline = load_task_baseline(REPO, task_id)
            live_manifest = build_manifest(REPO)
            task_manifest = build_task_manifest(REPO, baseline, expected_files=plan.get("expected_files"))
            pre_red_changes = task_manifest.get("task_changes") or []

            def is_test_repro_path(p: str) -> bool:
                pl = f"/{p.replace('\\', '/').lower().strip('/')}"
                if "/src/test/" in pl or "/src/androidtest/" in pl:
                    return True
                if pl.endswith("test.kt") or pl.endswith("test.java") or pl.endswith("tests.kt") or pl.endswith("tests.java"):
                    return True
                if "/test/" in pl or "/androidtest/" in pl:
                    return True
                return False

            has_fix_code = any(
                is_delivery_relevant(c.get("path", "")) and not is_test_repro_path(c.get("path", ""))
                for c in pre_red_changes
            )
            if has_fix_code:
                live_print("[FAIL] Cannot capture RED evidence: application source modifications already detected before capture.", err=True)
                return 1

            current_p = task_d / "current-run.json"
            current_run = read_json(current_p) if current_p.is_file() else {}
            pre_fix_snapshot = live_manifest["delivery_snapshot_sha256"]
            pre_fix_change_set = live_manifest["change_set_sha256"]
            pre_fix_task_change_set = task_manifest.get("task_change_set_sha256") or ""
            baseline_sha = str(baseline.get("baseline_sha256") or "") if baseline else ""
            plan_sha = str(plan.get("plan_sha256") or "")

            failed_records = [
                {
                    "test_id": str(item.get("test_name") or ""),
                    "failure_fingerprint": str(item.get("fingerprint") or ""),
                    "message_fingerprint": canonical_sha256({"message": item.get("message")}),
                }
                for item in failed
            ]
            red_payload = {
                "schema_version": 3,
                "task_id": task_id,
                "plan_sha256": plan_sha,
                "captured_at": utc_now(),
                "producer": "run_tests_gate",
                "pre_fix_delivery_snapshot_sha256": pre_fix_snapshot,
                "pre_fix_change_set_sha256": pre_fix_change_set,
                "pre_fix_task_change_set_sha256": pre_fix_task_change_set,
                "baseline_sha256": baseline_sha,
                "reproduction_kind": "FAILING_TEST",
                "gradle_task": task,
                "failed_tests": failed_records,
            }
            red_payload["red_sha256"] = canonical_sha256({k: v for k, v in red_payload.items() if k != "red_sha256"})
            write_json(task_d / "red-evidence.json", red_payload)
            write_json(task_d / "debug-evidence.json", {"schema_version": 1, "task_id": task_id, "entries": repro_entries})

            if current_run:
                from evidence_store import EvidenceStore
                store = EvidenceStore(state)
                store.write(
                    snapshot=pre_fix_snapshot,
                    run_id=str(current_run["run_id"]),
                    name="red_evidence",
                    producer="run_tests_gate",
                    harness_version=str(current_run.get("harness_version") or "1.0.0"),
                    change_set=pre_fix_change_set,
                    status="PASS",
                    evidence={
                        "plan_sha256": plan_sha,
                        "pre_fix_delivery_snapshot_sha256": pre_fix_snapshot,
                        "failed_tests": repro_entries,
                        "total_failed": len(failed),
                        "red_payload": red_payload,
                    },
                )
            live_print(f"[+] Recorded {len(repro_entries)} RED test reproduction entries (schema 3).")
            return 0
        except Exception as exc:
            live_print(f"[FAIL] Could not record RED evidence: {exc}", err=True)
            return 1
    summary = collect_test_summary(REPO, task)
    summary["executed_tests"] = collect_executed_tests(REPO, task)
    reports_after = report_signatures(REPO, task)
    failing_paths = [path.resolve().as_posix() for path in report_paths(REPO, task) if parse_report(path)]
    fresh_failures = bool(failing_paths) and all(
        path in reports_after and reports_before.get(path) != reports_after[path] for path in failing_paths
    )
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
    if code != 0 and (not failed or not fresh_failures or not outcome.get("test_failure_only")):
        write_gate_result("unit_tests", {
            "schema_version": 2,
            "producer": "run_tests_gate",
            "status": "FAIL",
            "exit_code": code,
            "env_class": "",
            "git_sha": head,
            "detail": "Gradle failure is not attributable exclusively to fresh failing-test reports for this task; stale reports and unrelated build failures cannot satisfy the gate",
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
