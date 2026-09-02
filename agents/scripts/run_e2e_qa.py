"""Senior-QA test-case-aware E2E runner for Android powered by Maestro.

Executes declarative Maestro test cases on a physical device or emulator.
Supports native Maestro multi-flow directories (.agents/e2e_cases/<task>/) and
standalone flow files.

Usage:
  python .agents/scripts/run_e2e_qa.py --cases .agents/e2e_cases/<task>/
  python .agents/scripts/run_e2e_qa.py --generate-cases --task <task> --output .agents/e2e_cases/<task>/
  python .agents/scripts/run_e2e_qa.py --cases <path> --lint
  python .agents/scripts/run_e2e_qa.py --cases <path> --json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
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
    generate_maestro_scaffold,
    get_maestro_install_instructions,
    validate_maestro_flow,
)
from _product import ALLOW_EMULATOR, APPLICATION_ID, PRODUCT_NAME  # noqa: E402
from _repo_files import REPO, first_adb_serial  # noqa: E402
from _variants import apk_relative  # noqa: E402

E2E_STATE_DIR = REPO / ".agents" / "state" / "e2e"
SCREENSHOTS_DIR = REPO / ".agents" / "state" / "screenshots"
REPORTS_DIR = E2E_STATE_DIR / "reports"


def lint_target_path(target: Path) -> tuple[bool, list[str]]:
    """Lint a Maestro flow file or all flow files in a directory."""
    errors: list[str] = []
    if not target.exists():
        return False, [f"Target path does not exist: {target}"]

    files_to_lint: list[Path] = []
    if target.is_dir():
        files_to_lint.extend(sorted(target.glob("*.yaml")))
        files_to_lint.extend(sorted(target.glob("*.yml")))
        if not files_to_lint:
            return False, [f"No .yaml flow files found in directory: {target}"]
    else:
        files_to_lint.append(target)

    for f in files_to_lint:
        ok, errs = validate_maestro_flow(f)
        if not ok:
            errors.extend(errs)

    return (len(errors) == 0), errors


def print_qa_milestone_table(parsed_report: dict) -> None:
    """Print structured PASS/FAIL table for Phase Milestone Card."""
    live_print("\n" + "=" * 60)
    live_print(f"[*] Maestro E2E QA Results: {parsed_report.get('verdict', 'UNKNOWN')}")
    live_print("=" * 60)
    cases = parsed_report.get("cases", [])
    if not cases:
        live_print("  No individual test cases reported.")
        return

    live_print(f"{'Status':<8} | {'Case ID / Title':<35} | {'Duration':<8}")
    live_print("-" * 60)
    for c in cases:
        st = f"[{c.get('status', 'FAIL')}]"
        title = c.get("title", c.get("id", "Unknown"))[:35]
        dur = f"{c.get('duration_seconds', 0.0):.1f}s"
        live_print(f"{st:<8} | {title:<35} | {dur:<8}")
        if c.get("reason"):
            live_print(f"         └─ Reason: {c.get('reason')}")
    live_print("=" * 60)


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Maestro Senior-QA E2E test runner.")
    parser.add_argument("--cases", type=str, help="Path to Maestro .yaml file or flow directory.")
    parser.add_argument("--generate-cases", action="store_true", help="Generate multi-flow scaffold.")
    parser.add_argument("--lint", action="store_true", help="Lint cases without executing on device.")
    parser.add_argument("--output", type=str, help="Output directory or file for generated cases.")
    parser.add_argument("--task", type=str, default="default", help="Task / phase identifier.")
    parser.add_argument("--json", action="store_true", help="Print result summary JSON.")
    parser.add_argument("--serial", type=str, default=None, help="Explicit device serial.")
    args = parser.parse_args()

    # 1. Handle scaffold generation
    if args.generate_cases:
        out_path = Path(args.output) if args.output else (REPO / ".agents" / "e2e_cases" / args.task)
        diff = discover_diff_targets(REPO)
        diff_names = [f.name for f in diff.get("modified_files", [])]
        created = generate_maestro_scaffold(args.task, out_path, APPLICATION_ID, diff_names)
        live_print(f"[OK] Generated {len(created)} Maestro test case(s) in {out_path}:")
        for c in created:
            live_print(f"  - {c.name}")
        return 0

    if not args.cases:
        live_print("[FAIL] Specify --cases <path> or --generate-cases.")
        return 1

    target_path = Path(args.cases)
    if not target_path.is_absolute():
        target_path = (REPO / target_path).resolve()

    # 2. Handle Lint mode
    if args.lint:
        ok, errors = lint_target_path(target_path)
        if ok:
            live_print(f"[OK] Maestro flow(s) in {target_path} are valid.")
            return 0
        live_print(f"[FAIL] Maestro flow validation errors in {target_path}:")
        for err in errors:
            live_print(f"  - {err}")
        return 1

    # 3. Execution on device: Check Maestro installation first
    maestro_ok, maestro_info, _ = ensure_maestro_installed()
    if not maestro_ok:
        live_print("\n[ENV-FAILURE] Maestro CLI is required but not available.")
        live_print(f"Reason: {maestro_info}")
        live_print("\nInstallation Instructions:")
        live_print(get_maestro_install_instructions())
        emit_env_failure(
            stage="e2e_qa",
            reason=f"Maestro CLI missing: {maestro_info}",
            remediation=get_maestro_install_instructions(),
        )
        return EXIT_ENV

    # Check device availability
    serial = args.serial or first_adb_serial(allow_emulator=ALLOW_EMULATOR)
    if not serial:
        verdict = no_device_verdict(allow_emulator=ALLOW_EMULATOR)
        live_print(f"\n[ENV-FAILURE] {verdict.summary}")
        emit_env_failure(
            stage="e2e_qa",
            reason=verdict.summary,
            remediation=verdict.remediation,
        )
        return EXIT_ENV

    # Check APK freshness
    apk_path = apk_relative()
    if apk_path:
        fresh_ok, fresh_err = check_apk_freshness(apk_path)
        if not fresh_ok:
            live_print(f"\n[FAIL] APK freshness check failed:\n{format_freshness_error(fresh_err)}")
            return 1

    # 4. Run Maestro Suite
    report = execute_maestro_suite(
        target_path=target_path,
        serial=serial,
        package=APPLICATION_ID,
        reports_dir=REPORTS_DIR,
        task_id=args.task,
    )

    print_qa_milestone_table(report)

    # 5. Write Gate Result for final_verdict.py
    is_pass = report.get("verdict") == "PASS"
    write_gate_result("e2e", {
        "schema_version": 1,
        "engine": "maestro",
        "status": "PASS" if is_pass else "FAIL",
        "exit_code": 0 if is_pass else 1,
        "git_sha": current_head_sha(),
        "task_id": args.task,
        "cases_total": report.get("total", 0),
        "cases_passed": report.get("passed", 0),
        "cases_failed": report.get("failed", 0),
        "report_summary": report.get("summary_path"),
        "detail": "" if is_pass else f"{report.get('failed', 0)} case(s) failed",
    })

    if args.json:
        live_print("\n" + json.dumps(report, indent=2, ensure_ascii=False))

    return 0 if is_pass else 1


if __name__ == "__main__":
    sys.exit(main())
