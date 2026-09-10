"""Capture or refresh the pre-existing test-failure baseline.

Usage:
  python .agents/scripts/baseline_capture.py [--run-tests] [--approve]

The baseline records unit-test failures that predate the current work so the
test gate can tolerate them (BASELINE_IGNORED) and block only NEW_REGRESSION.

Safety invariants:
- Capture/refresh is REFUSED while the working tree has code changes
  (has_non_doc_code_changes()) — a dirty tree cannot prove failures are
  pre-existing.
- --run-tests executes the configured unit-test task first (via
  run_gradle_task.run_gradle) and then parses the fresh reports.
- Refreshing an existing baseline requires --approve (explicit developer
  authorization); agents must never pass it without developer instruction.
- The baseline can only silence unit-test failures. E2E crashes, Room
  migrations, compile errors, and lint findings are never baseline-ignorable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gate_results import current_head_sha  # noqa: E402
from _env_codes import EXIT_ENV  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _repo_files import REPO, has_non_doc_code_changes  # noqa: E402

BASELINE_SCHEMA = 1


def _unit_test_task() -> str:
    try:
        import _product  # noqa: PLC0415

        return str(getattr(_product, "UNIT_TEST_TASK", ":app:testDebugUnitTest"))
    except Exception:
        return ":app:testDebugUnitTest"


def _project_name() -> str:
    try:
        import _product  # noqa: PLC0415

        return str(getattr(_product, "PRODUCT_NAME", "") or "unknown")
    except Exception:
        return "unknown"


def find_test_reports(repo: Path) -> list[Path]:
    reports: list[Path] = []
    try:
        for path in repo.glob("**/build/test-results/**/TEST-*.xml"):
            if "androidtest" in path.as_posix().lower():
                continue
            if path.is_file():
                reports.append(path)
    except Exception:
        pass
    return sorted(reports)


HEX_ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
LINE_NUM_RE = re.compile(r":\d+\b")
PATH_RE = re.compile(r"([A-Za-z]:[\\/]|/(?:home|Users|tmp|var|private|workspace|app)[^:\s]+)")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b")


def normalize_failure_message(msg: str) -> str:
    """Normalize volatile data (hex addresses, paths, line numbers, timestamps, UUIDs) in test messages."""
    if not msg:
        return ""
    text = msg.strip().lower()
    text = UUID_RE.sub("<UUID>", text)
    text = TIMESTAMP_RE.sub("<TIMESTAMP>", text)
    text = HEX_ADDR_RE.sub("<HEX>", text)
    text = PATH_RE.sub("<PATH>", text)
    text = LINE_NUM_RE.sub(":<LINE>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120]


def test_key(classname: str, name: str) -> str:
    return f"{classname}#{name}"


def fingerprint(key: str, error_type: str = "", message: str = "") -> str:
    norm_msg = normalize_failure_message(message)
    clean_type = (error_type or "").strip().lower()
    payload = f"{key}|{clean_type}|{norm_msg}" if (clean_type or norm_msg) else key
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def parse_report(path: Path) -> list[dict]:
    failures: list[dict] = []
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return failures
    for case in root.iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        if failure is None and error is None:
            continue
        problem = failure if failure is not None else error
        if problem is None:
            continue
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        key = test_key(classname, name)
        error_type = problem.get("type") or ""
        message = str(problem.get("message") or problem.text or "").strip()
        fp = fingerprint(key, error_type=error_type, message=message)
        leg_fp = fingerprint(key)
        failures.append({
            "test_name": key,
            "fingerprint": fp,
            "legacy_fingerprint": leg_fp,
            "error_type": error_type,
            "status": "FAILED_PRE_EXISTING",
            "message": message[:300],
        })
    return failures


def collect_failures(repo: Path) -> list[dict]:
    entries: dict[str, dict] = {}
    for report in find_test_reports(repo):
        for item in parse_report(report):
            entries[item["fingerprint"]] = item
    return sorted(entries.values(), key=lambda item: item["test_name"])


def baseline_path() -> Path:
    override = os.environ.get("HARNESS_HOOK_STATE", "").strip()
    return Path(override).with_name("baseline.json") if override else Path(__file__).resolve().parent.parent / "state" / "baseline.json"


def write_baseline(data: dict) -> Path | None:
    target = baseline_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, target)
        return target
    except Exception:
        return None


def load_baseline() -> dict | None:
    try:
        path = baseline_path()
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def main(argv=None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Capture or refresh the pre-existing test-failure baseline")
    parser.add_argument("--run-tests", action="store_true", help="Run the unit-test task before parsing reports")
    parser.add_argument("--approve", action="store_true", help="Confirm refresh of an existing baseline (developer-only)")
    args = parser.parse_args(argv)

    if has_non_doc_code_changes():
        live_print(
            "[REFUSED] Baseline capture requires a clean working tree (no code changes). "
            "Capture the baseline before starting task changes, or after committing them.",
            err=True,
        )
        return 1

    existing = load_baseline()
    if existing and not args.approve:
        live_print(
            "[REFUSED] A baseline already exists. Refreshing it requires explicit developer "
            "authorization: rerun with --approve. Do not add --approve without the developer's instruction.",
            err=True,
        )
        return 1

    if args.run_tests:
        task = _unit_test_task()
        live_print(f"[*] Running {task} before capturing the baseline...")
        from run_gradle_task import run_gradle
        from run_tests_gate import report_signatures

        reports_before = report_signatures(REPO, task)
        code = run_gradle([task])
        reports_after = report_signatures(REPO, task)
        fresh_reports = any(reports_before.get(path) != signature for path, signature in reports_after.items())
        if code == EXIT_ENV:
            live_print(f"[REFUSED] Unit tests were blocked by the environment (exit {code}); baseline not captured.", err=True)
            return code
        if code != 0 and (not collect_failures(REPO) or not fresh_reports):
            live_print("[REFUSED] Gradle failed without fresh parsed test failures; baseline not captured.", err=True)
            return code

    head = current_head_sha()
    entries = collect_failures(REPO)
    reports = find_test_reports(REPO)
    baseline = {
        "schema_version": BASELINE_SCHEMA,
        "project": _project_name(),
        "baseline_commit": head,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "unit_tests": entries,
        "report_files_parsed": len(reports),
    }
    target = write_baseline(baseline)
    if not target:
        live_print("[FAIL] Could not write the baseline file.", err=True)
        return 1
    live_print(f"[+] Baseline captured: {target}")
    live_print(f"    commit: {head or '(no git HEAD)'}")
    live_print(f"    pre-existing failures recorded: {len(entries)}")
    live_print(f"    test reports parsed: {len(reports)}")
    if not head:
        live_print("[!] No git HEAD: the baseline has no commit anchor; capture after the first commit.", err=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
