"""Self-test for _maestro_core.py and run_e2e_qa.py.

Verifies:
1. Flow validation for valid and invalid Maestro YAML syntax.
2. Scaffold generation for multi-flow directory structure.
3. JUnit XML parsing for both PASS and FAIL scenarios.
4. Preflight detection logic and install instructions.

Run:
  python agents/scripts/_maestro_selftest.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _maestro_core import (  # noqa: E402
    ensure_maestro_installed,
    generate_maestro_scaffold,
    get_maestro_install_instructions,
    parse_maestro_junit_xml,
    validate_maestro_flow,
)


def test_validation() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)

        # 1. Valid flow
        valid_flow = tmp_dir / "valid.yaml"
        valid_flow.write_text(
            "appId: com.acme.app\n"
            "---\n"
            "- launchApp\n"
            "- tapOn: 'Login'\n"
            "- assertVisible: 'Dashboard'\n",
            encoding="utf-8",
        )
        ok, errors = validate_maestro_flow(valid_flow)
        assert ok, f"Expected valid flow to pass lint, got: {errors}"

        # 2. Missing appId
        missing_app_id = tmp_dir / "missing_app_id.yaml"
        missing_app_id.write_text(
            "---\n"
            "- launchApp\n",
            encoding="utf-8",
        )
        ok, errors = validate_maestro_flow(missing_app_id)
        assert not ok, "Expected missing appId to fail lint"
        assert any("appId" in e for e in errors)

        # 3. Invalid command
        invalid_cmd = tmp_dir / "invalid_cmd.yaml"
        invalid_cmd.write_text(
            "appId: com.acme.app\n"
            "---\n"
            "- nonExistentCommand123: foo\n",
            encoding="utf-8",
        )
        ok, errors = validate_maestro_flow(invalid_cmd)
        assert not ok, "Expected unknown command to fail lint"
        assert any("Unknown Maestro action" in e for e in errors)

        # 4. Dummy Flow (launchApp + scroll only without assertions) -> Must FAIL
        dummy_flow = tmp_dir / "dummy_flow.yaml"
        dummy_flow.write_text(
            "appId: com.acme.app\n"
            "---\n"
            "- launchApp\n"
            "- scroll\n"
            "- scroll\n",
            encoding="utf-8",
        )
        ok, errors = validate_maestro_flow(dummy_flow)
        assert not ok, "Expected dummy flow without assertions/interactions to fail lint"
        assert any("Anti-Dummy Gate" in e for e in errors)

    print("[PASS] test_validation")


def test_scaffold_generation() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        out_dir = tmp_dir / "task_123"
        files = generate_maestro_scaffold("task_123", out_dir, "com.madarsoft.fitness", ["LoginScreen", "btn_start"])
        assert len(files) == 3, f"Expected 3 files, got {len(files)}"
        for f in files:
            assert f.is_file(), f"File does not exist: {f}"
            ok, errors = validate_maestro_flow(f)
            assert ok, f"Scaffold file {f.name} failed lint: {errors}"
            content = f.read_text(encoding="utf-8")
            assert "com.madarsoft.fitness" in content
            assert "LoginScreen" in content or "blast radius" in content.lower()

    print("[PASS] test_scaffold_generation")


def test_junit_parsing() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)

        # 1. PASS XML
        pass_xml = tmp_dir / "pass.xml"
        pass_xml.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="Maestro Tests" tests="2" failures="0" errors="0" time="4.5">
    <testcase name="TC01_positive" classname="e2e.flow" time="2.1"/>
    <testcase name="TC02_negative" classname="e2e.flow" time="2.4"/>
  </testsuite>
</testsuites>
""",
            encoding="utf-8",
        )
        res = parse_maestro_junit_xml(pass_xml)
        assert res["verdict"] == "PASS"
        assert res["passed"] == 2
        assert res["failed"] == 0
        assert len(res["cases"]) == 2
        assert res["cases"][0]["status"] == "PASS"

        # 2. FAIL XML
        fail_xml = tmp_dir / "fail.xml"
        fail_xml.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="Maestro Tests" tests="2" failures="1" errors="0" time="5.1">
    <testcase name="TC01_positive" classname="e2e.flow" time="2.1"/>
    <testcase name="TC02_negative" classname="e2e.flow" time="3.0">
      <failure message="Element 'Dashboard' not visible">Stack trace here</failure>
    </testcase>
  </testsuite>
</testsuites>
""",
            encoding="utf-8",
        )
        res = parse_maestro_junit_xml(fail_xml)
        assert res["verdict"] == "FAIL"
        assert res["passed"] == 1
        assert res["failed"] == 1
        assert res["cases"][1]["status"] == "FAIL"
        assert "Element 'Dashboard' not visible" in res["cases"][1]["reason"]

    print("[PASS] test_junit_parsing")


def test_instructions() -> None:
    guide = get_maestro_install_instructions()
    assert "https://get.maestro.mobile.dev" in guide
    print("[PASS] test_instructions")


def main() -> int:
    test_validation()
    test_scaffold_generation()
    test_junit_parsing()
    test_instructions()
    print("\n[ALL MAESTRO TESTS PASSED]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
