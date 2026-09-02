"""Autonomous E2E smoke-testing engine powered by Maestro.

Fast diff-aware smoke pass using Maestro. Use ``run_e2e_qa.py`` for
test-case-aware Senior QA runs with positive/negative/edge cases.

Usage:
  python .agents/scripts/run_e2e_smoke.py --auto-diff
  python .agents/scripts/run_e2e_smoke.py --flow <path.yaml>
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _adb_core import discover_diff_targets  # noqa: E402
from _apk_freshness import check_apk_freshness, format_freshness_error  # noqa: E402
from _env_codes import (  # noqa: E402
    CLASS_ENV,
    EXIT_ENV,
    FailureVerdict,
    emit_env_failure,
    no_device_verdict,
)
from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _maestro_core import (  # noqa: E402
    ensure_maestro_installed,
    execute_maestro_suite,
    get_maestro_install_instructions,
)
from _product import ALLOW_EMULATOR, APPLICATION_ID, PRODUCT_NAME  # noqa: E402
from _repo_files import REPO, first_adb_serial  # noqa: E402
from _variants import apk_relative  # noqa: E402

SCREENSHOTS_DIR = REPO / ".agents" / "state" / "screenshots"
E2E_STATE_DIR = REPO / ".agents" / "state" / "e2e"
REPORTS_DIR = E2E_STATE_DIR / "reports"


def create_quick_smoke_flow(app_id: str, target_texts: list[str] | None = None) -> Path:
    """Create a temporary Maestro smoke flow."""
    temp_dir = Path(tempfile.mkdtemp(prefix="maestro_smoke_"))
    flow_file = temp_dir / "smoke_flow.yaml"

    lines = [
        f"appId: {app_id}",
        "---",
        "- launchApp:",
        "    clearState: false",
        "- assertVisible:",
        "    text: \".*\"",
    ]
    if target_texts:
        for t in target_texts:
            lines.extend([
                f"- assertVisible:",
                f"    text: \"{t}\"",
            ])

    flow_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return flow_file


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Maestro fast smoke runner.")
    parser.add_argument("--auto-diff", action="store_true", help="Auto-discover modified targets from diff.")
    parser.add_argument("--flow", type=str, help="Custom Maestro flow path.")
    parser.add_argument("--serial", type=str, default=None, help="Explicit device serial.")
    args = parser.parse_args()

    maestro_ok, maestro_info, _ = ensure_maestro_installed()
    if not maestro_ok:
        live_print("\n[ENV-FAILURE] Maestro CLI is required for smoke testing.")
        live_print(f"Reason: {maestro_info}")
        live_print(get_maestro_install_instructions())
        emit_env_failure(
            stage="smoke_test",
            reason=f"Maestro CLI missing: {maestro_info}",
            remediation=get_maestro_install_instructions(),
        )
        return EXIT_ENV

    serial = args.serial or first_adb_serial(allow_emulator=ALLOW_EMULATOR)
    if not serial:
        verdict = no_device_verdict(allow_emulator=ALLOW_EMULATOR)
        live_print(f"\n[ENV-FAILURE] {verdict.summary}")
        emit_env_failure(
            stage="smoke_test",
            reason=verdict.summary,
            remediation=verdict.remediation,
        )
        return EXIT_ENV

    apk_path = apk_relative()
    if apk_path:
        fresh_ok, fresh_err = check_apk_freshness(apk_path)
        if not fresh_ok:
            live_print(f"\n[FAIL] APK freshness check failed:\n{format_freshness_error(fresh_err)}")
            return 1

    if args.flow:
        flow_path = Path(args.flow)
    else:
        diff_targets = []
        if args.auto_diff:
            diff = discover_diff_targets(REPO)
            diff_targets = diff.get("modified_strings", [])[:3]
        flow_path = create_quick_smoke_flow(APPLICATION_ID, diff_targets)

    report = execute_maestro_suite(
        target_path=flow_path,
        serial=serial,
        package=APPLICATION_ID,
        reports_dir=REPORTS_DIR,
        task_id="smoke",
    )

    is_pass = report.get("verdict") == "PASS"
    write_gate_result("e2e", {
        "schema_version": 1,
        "engine": "maestro_smoke",
        "status": "PASS" if is_pass else "FAIL",
        "exit_code": 0 if is_pass else 1,
        "git_sha": current_head_sha(),
        "cases_total": report.get("total", 0),
        "cases_passed": report.get("passed", 0),
        "cases_failed": report.get("failed", 0),
        "report_summary": report.get("summary_path"),
        "detail": "" if is_pass else f"Smoke test failed on {serial}",
    })

    return 0 if is_pass else 1


if __name__ == "__main__":
    sys.exit(main())
