"""Self-test for run_e2e_qa.py case parsing/validation/generation. No device."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from run_e2e_qa import (  # noqa: E402
    _dump_cases_yaml,
    generate_cases_definition,
    parse_cases_definition,
    validate_cases,
)

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"[PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label}")


def test_parse_yaml() -> None:
    yaml = """appId: com.acme.app
cases:
  - id: TC-001
    title: "Login succeeds"
    type: positive
    preconditions: "On login"
    isolation: relaunch
    steps:
      - launchApp
      - tapOn: "username"
      - inputText: "user@x.com"
      - assertVisible: "dashboard"
    expectedResult: "Lands on dashboard"
  - id: TC-002
    title: "Login fails on empty"
    type: negative
    steps:
      - launchApp
      - assertVisible: "error"
"""
    d = parse_cases_definition(yaml)
    check(d["appId"] == "com.acme.app", "appId parsed")
    check(len(d["cases"]) == 2, "two cases parsed")
    c1 = d["cases"][0]
    check(c1["id"] == "TC-001", "case id parsed")
    check(c1["type"] == "positive", "case type parsed")
    check(c1["isolation"] == "relaunch", "case isolation parsed")
    check(len(c1["steps"]) == 4, "case steps parsed")
    check(c1["steps"][0]["action"] == "launchApp", "launchApp step parsed")
    check(c1["steps"][1]["target"] == "username", "tapOn target parsed")
    c2 = d["cases"][1]
    check(c2.get("isolation") is None, "default isolation left unset")
    check(c2["steps"][1]["target"] == "error", "second case steps parsed")


def test_parse_json() -> None:
    data = {"appId": "com.acme.app", "cases": [{"id": "TC-1", "title": "T", "steps": [{"action": "launchApp"}]}]}
    d = parse_cases_definition(json.dumps(data))
    check(len(d["cases"]) == 1 and d["cases"][0]["id"] == "TC-1", "json cases parsed")


def test_validate() -> None:
    good = parse_cases_definition("cases:\n  - id: TC-1\n    steps:\n      - launchApp\n      - assertVisible: x\n")
    check(validate_cases(good) == [], "valid case validates clean")

    bad_missing_id = parse_cases_definition("cases:\n  - title: T\n    steps:\n      - launchApp\n")
    check(any("no 'id'" in e for e in validate_cases(bad_missing_id)), "missing id flagged")

    bad_type = parse_cases_definition("cases:\n  - id: TC-1\n    type: weirD\n    steps:\n      - launchApp\n")
    check(any("unknown type" in e for e in validate_cases(bad_type)), "unknown type flagged")

    bad_no_steps = parse_cases_definition("cases:\n  - id: TC-1\n")
    check(any("no steps" in e for e in validate_cases(bad_no_steps)), "missing steps flagged")

    bad_action = parse_cases_definition("cases:\n  - id: TC-1\n    steps:\n      - launchApp\n      - tappOn: x\n")
    check(any("unknown action" in e for e in validate_cases(bad_action)), "unknown step action flagged")


def test_generate_scaffold() -> None:
    d = generate_cases_definition()
    check(isinstance(d, dict) and "cases" in d and len(d["cases"]) >= 1, "scaffold produces at least one case")
    check(validate_cases(d) == [], "generated scaffold is valid")


def test_dump_roundtrip() -> None:
    d = generate_cases_definition()
    yaml = _dump_cases_yaml(d)
    d2 = parse_cases_definition(yaml)
    check(len(d2["cases"]) == len(d["cases"]), "dump/parse roundtrip preserves case count")
    check(d2["cases"][0]["id"] == d["cases"][0]["id"], "roundtrip preserves id")


def test_advanced_actions() -> None:
    yaml = """
cases:
  - id: TC-ADV-001
    title: "Test gestures, state assertions, and offline mode"
    type: edge
    isolation: stop
    steps:
      - launchApp
      - swipeLeft: "Stories"
      - assertChecked:
          id: toggle_switch
          checked: true
      - assertSelected:
          text: "Tab 2"
          selected: true
      - setNetwork: "offline"
      - assertVisible: "Offline Banner"
      - setNetwork: "online"
"""
    d = parse_cases_definition(yaml)
    check(len(d["cases"]) == 1, "advanced test case parsed")
    check(validate_cases(d) == [], "advanced test case validates clean")
    c = d["cases"][0]
    check(len(c["steps"]) == 7, "seven advanced steps parsed")


def main() -> int:
    test_parse_yaml()
    test_parse_json()
    test_validate()
    test_generate_scaffold()
    test_dump_roundtrip()
    test_advanced_actions()
    if FAILURES:
        print(f"\n[FAIL] {len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("\n[SUCCESS] E2E QA SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
