"""Unit-test delivery gate with baseline-aware regression classification.

Usage:
  python .agents/scripts/run_tests_gate.py

Runs the configured unit-test Gradle task, parses the JUnit XML reports, and
classifies every failure:

  NEW_REGRESSION    failed now and is absent from the baseline -> BLOCK (exit 1)
  BASELINE_IGNORED  failed now and is recorded in the baseline -> tolerated
                    (pre-existing debt, never reported as a regression)
  TASK_START_IGNORED failed the same way in this task's run before its first edit
                    (`--record-start` or `--capture-red`) and is not the
                    task's reproduction -> tolerated and named (O64)

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
from _repo_files import REPO, repo_glob  # noqa: E402


def report_paths(repo: Path, task: str | list[str]) -> list[Path]:
    if isinstance(task, (list, tuple)):
        return sorted({path for item in task for path in report_paths(repo, item)})
    parts = [item for item in task.strip().split(":") if item]
    if len(parts) >= 1:
        module = repo.joinpath(*parts[:-1])
        exact = module / "build" / "test-results" / parts[-1]
        return sorted(path for path in exact.rglob("*.xml") if path.is_file())
    return sorted(path for path in repo_glob(repo, "**/build/test-results/**/*.xml") if path.is_file() and "androidtest" not in path.as_posix().lower())


def collect_test_summary(repo: Path, task: str | list[str]) -> dict[str, int]:
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


def collect_executed_tests(repo: Path, task: str | list[str]) -> list[str]:
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


def collect_task_failures(repo: Path, task: str | list[str]) -> list[dict]:
    entries: dict[str, dict] = {}
    for report in report_paths(repo, task):
        for item in parse_report(report):
            entries[item["fingerprint"]] = item
    return sorted(entries.values(), key=lambda item: item["test_name"])


def report_signatures(repo: Path, task: str | list[str]) -> dict[str, tuple[int, int]]:
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


TASK_START_FAILURES = "task-start-failures.json"


def _task_directory(repo: Path, task_id: str) -> Path:
    state = repo / ".agents/state" if (repo / ".agents").is_dir() else repo / "agents/state"
    return state / "tasks" / task_id


def load_task_start_failures(repo: Path, task_id: str | None = None) -> dict:
    """Failures recorded before the task's fix, minus its RED reproduction.

    Returns {test_name: fingerprint}. A reproduction test must turn green, so it is never tolerated.
    """
    try:
        from _vnext_common import read_json

        if not task_id:
            from mutation_guard import active_plan

            task_id = str(active_plan(repo).get("task_id") or "")
        if not task_id:
            return {}
        directory = _task_directory(repo, task_id)
        path = directory / TASK_START_FAILURES
        if not path.is_file():
            return {}
        data = read_json(path)
        if str(data.get("task_id") or "") != task_id:
            return {}
        recorded = {
            str(item.get("test_name") or ""): str(item.get("fingerprint") or "")
            for item in data.get("failures") or []
            if item.get("test_name") and item.get("fingerprint")
        }
        red_path = directory / "red-evidence.json"
        if red_path.is_file():
            for item in read_json(red_path).get("failed_tests") or []:
                recorded.pop(str(item.get("test_id") or ""), None)
        return recorded
    except Exception:
        return {}


def split_task_start_failures(failed: list[dict], task_start: dict | None) -> tuple[list[dict], list[dict]]:
    """(still failing, predating the task): a match needs the same test and the same failure."""
    if not task_start:
        return list(failed), []
    remaining: list[dict] = []
    predating: list[dict] = []
    for item in failed:
        if task_start.get(str(item.get("test_name") or "")) == str(item.get("fingerprint") or ""):
            predating.append(item)
        else:
            remaining.append(item)
    return remaining, predating


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


def _unit_test_scope() -> str:
    try:
        import _product
        return str(getattr(_product, "UNIT_TEST_SCOPE", "legacy") or "legacy").strip().lower()
    except Exception:
        return "legacy"


def resolve_target_tasks(repo: Path, requested_task: str | None) -> list[str]:
    """Unit-test tasks for this run.

    Installs with UNIT_TEST_SCOPE = "changed_modules" test every changed module; a change that spans
    several modules no longer falls back to the default task, which may not run the changed tests.
    Other installs keep the single-task behaviour of resolve_target_task.
    """
    single = resolve_target_task(repo, requested_task)
    if requested_task or _unit_test_scope() != "changed_modules":
        return [single]
    from baseline_capture import _unit_test_task
    default_task = _unit_test_task()
    if single != default_task:
        return [single]
    try:
        from _repo_files import changed_paths
        changed = changed_paths(repo=repo)
        root_build_names = {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties", "libs.versions.toml"}
        if any(p.name in root_build_names or p.parent == repo for p in changed if p.suffix in {".gradle", ".kts", ".toml", ".properties"}):
            return [default_task]
        default_module = default_task.rsplit(":", 1)[0] or ":app"
        task_suffix = default_task.split(":")[-1] if ":" in default_task else "testDebugUnitTest"
        tasks: list[str] = []
        for p in changed:
            rel = p.relative_to(repo).as_posix()
            if "/src/" not in rel:
                continue
            mod_path = rel.split("/src/")[0]
            mod_name = ":" + mod_path.replace("/", ":") if mod_path and mod_path != "." else ":app"
            task = default_task if mod_name in (default_module, ":app") else f"{mod_name}:{task_suffix}"
            if task not in tasks:
                tasks.append(task)
        return sorted(tasks) or [default_task]
    except Exception:
        return [default_task]


def _failures_with_freshness(
    repo: Path,
    task: str,
    reports_before: dict[str, tuple[int, int]] | None,
) -> tuple[list[dict], bool]:
    """Failing tests in the reports, and whether every failing report was written by this run."""
    failed = collect_task_failures(repo, task)
    reports_after = report_signatures(repo, task)
    failing_paths = [path.resolve().as_posix() for path in report_paths(repo, task) if parse_report(path)]
    fresh = bool(failing_paths) and (
        reports_before is None or all(
            path in reports_after and reports_before.get(path) != reports_after[path]
            for path in failing_paths
        )
    )
    return failed, fresh


def _test_class_simple_name(test_name: str) -> str:
    return test_name.partition("#")[0].rpartition(".")[2].partition("$")[0]


def select_red_reproduction(
    failed: list[dict],
    baseline: dict | None,
    task_test_paths: list[str],
    planned_classes: set[str] | None = None,
) -> list[dict]:
    """Failing tests that reproduce this task's defect.

    Known baseline failures are never a reproduction. When the task added or changed
    test files, only failures from those files count; otherwise an existing failing
    test of a planned file may itself be the reproduction. A failure in another
    feature's test is not this defect (O64: a real app's unrelated failures were
    recorded as the reproduction and later blocked the gate as regressions).
    """
    candidates, _ignored, _known = classify_failures(failed, baseline)
    task_test_classes = {Path(p).stem for p in task_test_paths}
    if not task_test_classes:
        if planned_classes is None:
            return candidates
        task_test_classes = set(planned_classes)
    return [item for item in candidates if _test_class_simple_name(str(item.get("test_name") or "")) in task_test_classes]


def evaluate_unit_test_execution(
    repo: Path,
    task: str,
    code: int,
    reports_before: dict[str, tuple[int, int]] | None = None,
    outcome: dict | None = None,
    baseline: dict | None = None,
    task_start: dict | None = None,
) -> tuple[bool, str, dict]:
    """Evaluate unit-test execution results with baseline-aware regression semantics.

    Returns:
        (passed: bool, detail: str, evidence_data: dict)
    """
    if code == EXIT_ENV:
        return False, f"unit-test Gradle run failed environmentally; exit code {code}", {
            "status": "ENV",
            "exit_code": code,
            "env_class": "ENV",
        }

    summary = collect_test_summary(repo, task)
    summary["executed_tests"] = collect_executed_tests(repo, task)
    failed, fresh_failures = _failures_with_freshness(repo, task, reports_before)

    if code == 0 and summary.get("executed", 0) == 0:
        return False, "Gradle succeeded but zero tests were executed; required test evidence is absent", {
            "status": "FAIL",
            "exit_code": 1,
            **summary,
        }

    test_failure_only = bool((outcome or {}).get("test_failure_only"))
    if code != 0 and (not failed or not fresh_failures or not test_failure_only):
        first_error = str((outcome or {}).get("first_error") or "")
        if first_error:
            # A live run: the verdict said only "not attributable ... to fresh failing-test reports".
            detail = f"the build failed before the tests ran: compile error at {first_error}"
        else:
            detail = (
                f"the Gradle run failed for a reason other than failing tests (exit code {code}); "
                "read the [ERROR] lines above"
            )
        return False, detail, {
            "status": "FAIL",
            "exit_code": code,
            **summary,
        }

    if baseline is None:
        try:
            baseline = load_baseline(repo)
        except Exception:
            baseline = None

    if not failed and not baseline:
        return True, "no failing tests in the parsed reports", {
            "status": "PASS",
            "exit_code": 0,
            **summary,
        }

    new_regressions, ignored, baseline_size = classify_failures(failed, baseline)
    new_regressions, predating = split_task_start_failures(new_regressions, task_start)
    predating_names = [item["test_name"] for item in predating]
    if new_regressions:
        names = [item["test_name"] for item in new_regressions]
        detail = f"{len(new_regressions)} NEW_REGRESSION failure(s): {', '.join(names[:5])}"
        if baseline is None:
            detail += (
                ". No pre-existing-failure baseline exists; if these failures predate the task, the developer "
                "captures one on a clean working tree: python .agents/scripts/baseline_capture.py --run-tests"
            )
        return False, detail, {
            "status": "FAIL",
            "exit_code": 1,
            "new_regressions": names,
            "baseline_ignored": len(ignored),
            "task_start_ignored": predating_names,
            "total_failed": len(failed),
            **summary,
        }

    detail = f"{len(ignored)} pre-existing failure(s) ignored via baseline ({baseline_size} known)"
    if predating_names:
        detail += f"; {len(predating_names)} failure(s) predate this task (same failure before the fix)"
    return True, detail, {
        "status": "PASS",
        "exit_code": 0,
        "baseline_ignored": len(ignored),
        "task_start_ignored": predating_names,
        "total_failed": len(failed),
        **summary,
    }


def _predating_lines(task_start_ignored: list | None) -> list[tuple[str, bool]]:
    if not task_start_ignored:
        return []
    lines = [(
        f"[*] {len(task_start_ignored)} test(s) already failed the same way before this task's fix (recorded before "
        "its first edit); they are not this task's and are not edited under it. Tell the developer:",
        False,
    )]
    lines += [(f"  - {item}", False) for item in task_start_ignored[:30]]
    return lines


def verdict_lines(
    ok: bool, detail: str, code: int, new_regressions: list, task_start_ignored: list | None = None
) -> list[tuple[str, bool]]:
    """The gate's closing lines as (text, is_error)."""
    if new_regressions:
        lines = [(f"[FAIL] NEW_REGRESSION: {len(new_regressions)} test(s) failed that are absent from the baseline:", True)]
        lines += [(f"  - {item}", True) for item in new_regressions[:30]]
        if len(new_regressions) > 30:
            lines.append((f"  ... and {len(new_regressions) - 30} more", True))
        return lines + _predating_lines(task_start_ignored)
    if not ok:
        return [(f"[FAIL] Unit-test gate blocked: {detail}", True)]
    lines = _predating_lines(task_start_ignored)
    if code != 0:
        # Short certification O48: the Gradle result line above says FAIL; say why the gate still passes.
        lines.append(("[*] Gradle's FAIL above comes only from tests that already failed before this task.", False))
    lines.append((f"[SUCCESS] Unit-test gate passed: {detail}", False))
    return lines


def _record_task_start(
    task_label: str, failed: list[dict], baseline: dict | None, code: int, outcome: dict,
    reports_before: dict, task: str | list[str],
) -> int:
    """`--record-start`: the same record `--capture-red` writes, for any task kind (O64)."""
    from delivery_manifest import build_manifest, build_task_manifest, load_task_baseline
    from mutation_guard import active_plan
    from _vnext_common import atomic_write_json, utc_now

    try:
        plan = active_plan(REPO)
    except Exception:
        plan = {}
    task_id = str(plan.get("task_id") or "")
    if not task_id or plan.get("status") != "IMPLEMENTING":
        live_print("[FAIL] --record-start needs an active task in IMPLEMENTING.", err=True)
        return 1
    task_manifest = build_task_manifest(REPO, load_task_baseline(REPO, task_id), expected_files=plan.get("expected_files"))
    if task_manifest.get("task_changes"):
        live_print(
            "[FAIL] --record-start runs only before the task's first edit: this task already changed files, so a "
            "failure now cannot be shown to predate it. Nothing was recorded; continue the task.",
            err=True,
        )
        return 1
    _failed, fresh = _failures_with_freshness(REPO, task, reports_before)
    attributable = code == 0 or (bool(failed) and bool(fresh) and bool(outcome.get("test_failure_only")))
    # A green run means every test passed now; reports left by older runs prove nothing.
    recordable = failed if attributable and code != 0 else []
    start_failures, _known, _size = classify_failures(recordable, baseline)
    atomic_write_json(_task_directory(REPO, task_id) / TASK_START_FAILURES, {
        "schema_version": 1,
        "task_id": task_id,
        "captured_at": utc_now(),
        "pre_fix_delivery_snapshot_sha256": build_manifest(REPO)["delivery_snapshot_sha256"],
        "gradle_task": task_label,
        "status": "RECORDED" if attributable else "BUILD_FAILED",
        "failures": [
            {"test_name": str(item.get("test_name") or ""), "fingerprint": str(item.get("fingerprint") or "")}
            for item in start_failures
        ],
    })
    if not attributable:
        live_print(
            f"[!] The untouched project's unit tests did not run cleanly (exit {code}); nothing is recorded as "
            "failing before the task. Tell the developer the project does not build its tests before this change.",
            err=True,
        )
        return 0
    if start_failures:
        live_print(f"[*] {len(start_failures)} test(s) already fail before this task; they are recorded and are not this task's:")
        for item in start_failures[:30]:
            live_print(f"  - {item.get('test_name')}")
    else:
        live_print("[+] No unit test fails before this task (beyond the baseline).")
    return 0


def _test_source(repo: Path, simple: str) -> str:
    """The repository path of the test class `simple` (exactly one match), or ""."""
    import subprocess

    from plan_authority import is_test_path

    proc = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", f"*{simple}.kt", f"*{simple}.java"],
        cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    matches = [line for line in proc.stdout.splitlines() if Path(line).stem == simple and is_test_path(line)]
    return matches[0] if len(matches) == 1 else ""


def _unrelated_failures(repo: Path, plan: dict, task_id: str, failed: list[dict]) -> tuple[list[dict], list[str]]:
    """Failing tests this task cannot have caused as far as the source shows: (unrelated, refusals).

    Unrelated means the test is not a planned or changed test and its source names no type or
    top-level function declared in a production file the task changed. An indirect break (through a
    class the test does not name) cannot be seen this way, which is why the developer confirms.
    """
    from delivery_manifest import build_task_manifest, load_task_baseline
    from plan_authority import changed_file_paths, is_test_path, planned_test_classes
    from _source_outline import outline, reference_lines

    manifest = build_task_manifest(repo, load_task_baseline(repo, task_id), expected_files=plan.get("expected_files"))
    changed = changed_file_paths(manifest)
    owned = planned_test_classes(plan.get("expected_files") or []) | {Path(p).stem for p in changed if is_test_path(p)}
    names: set[str] = set()
    for rel in changed:
        if is_test_path(rel) or not rel.endswith((".kt", ".java")):
            continue
        names.add(Path(rel).stem)
        # Types, and functions a test can call by name (top level); a member named like a method the test
        # also calls (onCreate) says nothing about the test depending on this file.
        names |= {
            e["name"] for e in outline(repo / rel)
            if e["kind"] not in ("val", "var", "method", "fun") or (e["kind"] == "fun" and e.get("top_level"))
        }
    unrelated: list[dict] = []
    refusals: list[str] = []
    seen: dict[str, str] = {}
    for item in failed:
        name = str(item.get("test_name") or "")
        simple = name.partition("#")[0].rpartition(".")[2].partition("$")[0]
        if simple not in seen:
            source = _test_source(repo, simple) if simple else ""
            if not simple or simple in owned:
                seen[simple] = f"{simple or name}: a test of this task's own files"
            elif not source:
                seen[simple] = f"{simple}: its source file could not be found, so it cannot be shown to be unrelated"
            else:
                hits = reference_lines(repo / source, names)
                used = sorted(n for n in names if hits and reference_lines(repo / source, {n}))
                seen[simple] = f"{simple}: mentions {', '.join(used[:5])}, which this task changed" if hits else ""
        if seen[simple]:
            if seen[simple] not in refusals:
                refusals.append(seen[simple])
        else:
            unrelated.append(item)
    return unrelated, refusals


def _record_unrelated(failed: list[dict], code: int, outcome: dict, reports_before: dict, task, proof: str) -> int:
    """`--record-unrelated`: after the developer confirms, tolerate failing tests the change cannot touch.

    Real app: a task began without `--record-start`, another feature's stale test failed at the gate,
    and the only advice was a baseline capture on a clean tree, which the task's own edits made
    impossible; the agent offered to rewrite that test under a revised plan instead.
    """
    from mutation_guard import active_plan
    from _vnext_common import atomic_write_json, read_json, utc_now

    try:
        plan = active_plan(REPO)
    except Exception:
        plan = {}
    task_id = str(plan.get("task_id") or "")
    if not task_id or plan.get("status") not in ("IMPLEMENTING", "VERIFYING"):
        live_print("[FAIL] --record-unrelated needs an active task in IMPLEMENTING or VERIFYING.", err=True)
        return 1
    if not proof.strip():
        live_print("[FAIL] --record-unrelated needs --proof-reference with the developer's confirmation.", err=True)
        return 1
    _failed, fresh = _failures_with_freshness(REPO, task, reports_before)
    if code == 0 or not failed:
        live_print("[+] No unit test fails; nothing to record.")
        return 0
    if not fresh or not outcome.get("test_failure_only"):
        live_print(f"[FAIL] The Gradle run failed for a reason other than failing tests (exit {code}); nothing was recorded.", err=True)
        return 1
    # Tests already recorded (at the start or earlier) are tolerated by the gate; they are not judged again.
    failed, _already = split_task_start_failures(failed, load_task_start_failures(REPO, task_id))
    if not failed:
        live_print("[+] Every failing test is already recorded as not this task's; nothing new to record.")
        return 0
    unrelated, refusals = _unrelated_failures(REPO, plan, task_id, failed)
    path = _task_directory(REPO, task_id) / TASK_START_FAILURES
    try:
        data = read_json(path) if path.is_file() else {}
    except Exception:
        data = {}
    if str(data.get("task_id") or "") != task_id:
        data = {"schema_version": 1, "task_id": task_id, "captured_at": utc_now(), "status": "RECORDED_LATE", "failures": []}
    known = {(str(i.get("test_name")), str(i.get("fingerprint"))) for i in data.get("failures") or []}
    for item in unrelated:
        key = (str(item.get("test_name") or ""), str(item.get("fingerprint") or ""))
        if key not in known:
            data.setdefault("failures", []).append({
                "test_name": key[0], "fingerprint": key[1], "source": "DEVELOPER_CONFIRMED_UNRELATED",
                "proof_reference": proof.strip()[:500], "recorded_at": utc_now(),
            })
            known.add(key)
    if unrelated:
        atomic_write_json(path, data)
        live_print(f"[*] {len(unrelated)} failing test(s) recorded as not this task's (the developer confirmed; they name nothing this task changed):")
        for item in unrelated[:30]:
            live_print(f"  - {item.get('test_name')}")
        live_print("[*] Run `python .agents/harness.py test` again; these no longer count against the task.")
    for line in refusals:
        live_print(f"[FAIL] Not recorded: {line}. Fix it within the plan, or ask the developer.", err=True)
    return 1 if refusals else 0


def main(argv=None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Baseline-aware unit-test delivery gate")
    parser.add_argument("task", nargs="?", default=None, help="Gradle unit-test task (default: _product UNIT_TEST_TASK)")
    parser.add_argument("--capture-red", action="store_true", help="Record failing test reproduction evidence as RED evidence for BUG tasks")
    parser.add_argument(
        "--record-start", action="store_true",
        help="Before the task's first edit, record which unit tests already fail (they never count as this task's regressions)",
    )
    parser.add_argument(
        "--record-unrelated", action="store_true",
        help="After the developer confirms, record failing tests that name nothing this task changed as not this task's",
    )
    parser.add_argument("--proof-reference", default="", help="The developer's confirmation (with --record-unrelated)")
    args = parser.parse_args(argv)
    if args.record_unrelated and not args.proof_reference.strip():
        live_print("[FAIL] --record-unrelated needs --proof-reference with the developer's confirmation.", err=True)
        return 1

    from run_gradle_task import run_gradle

    tasks = resolve_target_tasks(REPO, args.task)
    task: str | list[str] = tasks[0] if len(tasks) == 1 else tasks
    task_label = " ".join(tasks)
    live_print(f"[*] Unit-test gate: {task_label}")
    reports_before = report_signatures(REPO, task)
    outcome: dict = {}
    code = 0
    if len(tasks) == 1:
        with step_progress(f"Running unit tests: {task_label}"):
            code = run_gradle(tasks, outcome=outcome)
    else:
        # One Gradle run per module keeps failure attribution per task and runs every module's tests.
        attributable = True
        for item in tasks:
            item_outcome: dict = {}
            with step_progress(f"Running unit tests: {item}"):
                item_code = run_gradle([item], outcome=item_outcome)
            if item_code == EXIT_ENV:
                code = item_code
                break
            if item_code != 0:
                code = code or item_code
                attributable = attributable and bool(item_outcome.get("test_failure_only"))
        if code != 0 and code != EXIT_ENV:
            outcome["test_failure_only"] = attributable
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
    baseline = load_baseline(REPO)
    advisory = baseline_advisory(baseline, head)
    if advisory:
        live_print(advisory, err=True)

    failed = collect_task_failures(REPO, task)
    if getattr(args, "record_start", False):
        return _record_task_start(task_label, failed, baseline, code, outcome, reports_before, task)
    if getattr(args, "record_unrelated", False):
        remaining, _known, _size = classify_failures(failed, baseline)
        return _record_unrelated(remaining, code, outcome, reports_before, task, args.proof_reference)
    if getattr(args, "capture_red", False):
        if not failed:
            live_print("[FAIL] --capture-red requested but no failing tests were detected.", err=True)
            return 1
        _failed, fresh = _failures_with_freshness(REPO, task, reports_before)
        if not fresh or (code != 0 and not outcome.get("test_failure_only")):
            live_print(
                f"[FAIL] Cannot capture RED evidence: Gradle failure (exit {code}) is not attributable exclusively to fresh failing-test reports from this run.",
                err=True,
            )
            return 1
        test_baseline = baseline
        try:
            from mutation_guard import active_plan
            from _vnext_common import atomic_write_json, canonical_sha256, read_json, utc_now
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
                norm_p = p.replace("\\", "/").lower().strip("/")
                pl = f"/{norm_p}"
                if "/src/test/" in pl or "/src/androidtest/" in pl:
                    return True
                if pl.endswith("test.kt") or pl.endswith("test.java") or pl.endswith("tests.kt") or pl.endswith("tests.java"):
                    return True
                if "/test/" in pl or "/androidtest/" in pl:
                    return True
                return False

            def _change_p(item: Any) -> str:
                return str(item.get("path", "") if isinstance(item, dict) else item or "")

            has_fix_code = any(
                is_delivery_relevant(_change_p(c)) and not is_test_repro_path(_change_p(c))
                for c in pre_red_changes
            )
            if has_fix_code:
                live_print("[FAIL] Cannot capture RED evidence: application source modifications already detected before capture.", err=True)
                return 1

            # Only a run on the untouched tree proves a failure predates the task: an edited shared
            # test helper could itself break other tests, so any task change records nothing.
            recorded_start = not pre_red_changes
            start_failures, _known_start, _size = classify_failures(failed, test_baseline)
            if recorded_start:
                atomic_write_json(task_d / TASK_START_FAILURES, {
                    "schema_version": 1,
                    "task_id": task_id,
                    "captured_at": utc_now(),
                    "pre_fix_delivery_snapshot_sha256": live_manifest["delivery_snapshot_sha256"],
                    "gradle_task": task_label,
                    "failures": [
                        {"test_name": str(item.get("test_name") or ""), "fingerprint": str(item.get("fingerprint") or "")}
                        for item in start_failures
                    ],
                })

            from plan_authority import planned_test_classes

            task_test_paths = [_change_p(c) for c in pre_red_changes if is_test_repro_path(_change_p(c))]
            all_failed = failed
            failed = select_red_reproduction(
                failed, test_baseline, task_test_paths, planned_test_classes(plan.get("expected_files") or [])
            )
            if not failed:
                outside = sorted({_test_class_simple_name(str(item.get("test_name") or "")) for item in all_failed})
                live_print(
                    "[FAIL] Cannot capture RED evidence: no failing test reproduces this task's defect. The failing "
                    f"tests ({', '.join(outside[:8]) or 'none'}) are known baseline debt or belong to files outside "
                    "this plan" + ("; they are recorded as failing before the task" if recorded_start else "")
                    + ". Write a test that fails because of the defect in the plan's test file, then run "
                    "--capture-red again.",
                    err=True,
                )
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
                "gradle_task": task_label,
                "failed_tests": failed_records,
            }
            red_payload["red_sha256"] = canonical_sha256({k: v for k, v in red_payload.items() if k != "red_sha256"})
            atomic_write_json(task_d / "red-evidence.json", red_payload)
            atomic_write_json(task_d / "debug-evidence.json", {"schema_version": 1, "task_id": task_id, "entries": repro_entries})

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

    ok, detail, data = evaluate_unit_test_execution(
        repo=REPO,
        task=task,
        code=code,
        reports_before=reports_before,
        outcome=outcome,
        baseline=baseline,
        task_start=load_task_start_failures(REPO),
    )
    for text, is_error in verdict_lines(
        ok, detail, code, data.get("new_regressions", []), data.get("task_start_ignored")
    ):
        live_print(text, err=is_error)

    write_gate_result("unit_tests", {
        "schema_version": 2,
        "producer": "run_tests_gate",
        "git_sha": head,
        "detail": detail,
        **data,
    })
    return 0 if ok else (code if code != 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
