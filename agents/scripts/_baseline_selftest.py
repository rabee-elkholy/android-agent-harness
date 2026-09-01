"""Self-test for baseline capture and the baseline-aware test gate. Stdlib only."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

HEAD = "a" * 40
OTHER_HEAD = "b" * 40

from _hook_state import state_path  # noqa: E402
from baseline_capture import (  # noqa: E402
    collect_failures,
    fingerprint,
    load_baseline,
    parse_report,
    test_key,
)
from run_tests_gate import baseline_advisory, classify_failures  # noqa: E402

FAILURES: list[str] = []
ROOT = Path(tempfile.mkdtemp())
os.environ["HARNESS_HOOK_STATE"] = str(ROOT / "review-invokes.json")

XML_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="app" tests="4" failures="2" errors="1" skipped="1">
  <testcase classname="com.acme.calc.FormatterTest" name="testPassing" time="0.01"/>
  <testcase classname="com.acme.calc.FormatterTest" name="testLegacyFormula" time="0.02">
    <failure message="expected:&lt;42&gt; but was:&lt;43&gt;">formula mismatch</failure>
  </testcase>
  <testcase classname="com.acme.calc.ParserTest" name="testNullInput" time="0.01">
    <error message="null pointer in parse">stacktrace</error>
  </testcase>
  <testcase classname="com.acme.calc.FlakyTest" name="testSkipped" time="0.00">
    <skipped/>
  </testcase>
</testsuite>
"""


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"[PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label}")


def write_report(directory: Path, content: str = XML_SAMPLE) -> Path:
    report_dir = directory / "build" / "test-results" / "testDebugUnitTest"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "TEST-com.acme.calc.FormatterTest.xml"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_report() -> None:
    directory = ROOT / "parse"
    write_report(directory)
    entries = parse_report(write_report(directory))
    check(len(entries) == 2, "failure + error counted, skip and pass excluded")
    names = {item["test_name"] for item in entries}
    check("com.acme.calc.FormatterTest#testLegacyFormula" in names, "failure test captured")
    check("com.acme.calc.ParserTest#testNullInput" in names, "error test captured")
    check(all(item["status"] == "FAILED_PRE_EXISTING" for item in entries), "status stamped")
    check(all(item.get("message") for item in entries), "failure message captured")


def test_parse_corrupt() -> None:
    directory = ROOT / "corrupt"
    path = write_report(directory)
    path.write_text("<not-xml", encoding="utf-8")
    check(parse_report(path) == [], "corrupt report parses as empty (no crash)")
    check(parse_report(ROOT / "missing.xml") == [], "missing report parses as empty")


def test_fingerprint_stability() -> None:
    key = test_key("com.acme.calc.FormatterTest", "testLegacyFormula")
    check(fingerprint(key) == fingerprint(key), "fingerprint deterministic")
    check(fingerprint(key) != fingerprint(test_key("com.acme.calc.FormatterTest", "testOther")), "different test -> different fingerprint")
    check(len(fingerprint(key)) == 16, "fingerprint length 16")


def test_classify_without_baseline() -> None:
    failed = [
        {"test_name": "A#a", "fingerprint": "1"},
        {"test_name": "B#b", "fingerprint": "2"},
    ]
    new_regressions, ignored, known = classify_failures(failed, None)
    check(len(new_regressions) == 2 and not ignored, "no baseline: every failure is NEW_REGRESSION")
    check(known == 0, "no baseline: known size 0")


def test_classify_with_baseline() -> None:
    baseline = {"unit_tests": [
        {"test_name": "A#a", "fingerprint": "1", "status": "FAILED_PRE_EXISTING"},
    ]}
    failed = [
        {"test_name": "A#a", "fingerprint": "1"},
        {"test_name": "B#b", "fingerprint": "2"},
    ]
    new_regressions, ignored, known = classify_failures(failed, baseline)
    check([item["test_name"] for item in ignored] == ["A#a"], "baseline entry ignored")
    check([item["test_name"] for item in new_regressions] == ["B#b"], "unknown failure flagged NEW_REGRESSION")
    check(known == 1, "known size reported")


def test_classify_malformed_baseline() -> None:
    failed = [{"test_name": "B#b", "fingerprint": "2"}]
    new_regressions, ignored, known = classify_failures(failed, {"unit_tests": [{"bad": True}]})
    check(len(new_regressions) == 1, "baseline entries without fingerprints never match")
    check(known == 0, "fingerprint-less baseline contributes nothing")


def test_baseline_advisory() -> None:
    baseline = {"baseline_commit": HEAD}
    check(baseline_advisory(baseline, HEAD) == "", "same commit: no advisory")
    note = baseline_advisory(baseline, OTHER_HEAD)
    check("BASELINE ADVISORY" in note, "different commit: advisory emitted")
    check(baseline_advisory(None, HEAD) == "", "no baseline: no advisory")
    check(baseline_advisory({"baseline_commit": ""}, HEAD) == "", "empty commit: no advisory")


def test_collect_failures_dedup() -> None:
    directory = ROOT / "collect"
    report = write_report(directory)
    other = directory / "build" / "test-results" / "testDebugUnitTest" / "TEST-other.xml"
    other.write_text(XML_SAMPLE, encoding="utf-8")
    entries = collect_failures(directory)
    fps = [item["fingerprint"] for item in entries]
    check(len(fps) == len(set(fps)) == 2, "duplicate reports deduplicated by fingerprint")
    check(entries[0]["test_name"] < entries[1]["test_name"], "entries sorted by test name")


def test_load_baseline() -> None:
    path = state_path().with_name("baseline.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema_version": 1, "unit_tests": [{"test_name": "A#a", "fingerprint": "1"}]}', encoding="utf-8")
    data = load_baseline()
    check(data is not None and data.get("schema_version") == 1, "baseline loads")
    path.write_text("{corrupt", encoding="utf-8")
    check(load_baseline() is None, "corrupt baseline reads as absent")


def main() -> int:
    test_parse_report()
    test_parse_corrupt()
    test_fingerprint_stability()
    test_classify_without_baseline()
    test_classify_with_baseline()
    test_classify_malformed_baseline()
    test_baseline_advisory()
    test_collect_failures_dedup()
    test_load_baseline()
    if FAILURES:
        print(f"\n[FAIL] {len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("\n[SUCCESS] BASELINE SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
