"""Android Agent Harness System Diagnostic & Health Check Engine.

Comprehensive 12-Dimension diagnostic suite inspecting every layer of the
installed harness: Host & Environment, File Structure, Subagent Roster,
Product Configuration, Template Leakage, Domain Skills & Workflows, Multi-IDE
Adapters, Safety Hooks & State Locking, Live Process Streaming, Preflight
Pipeline, Project Tracker & PM Security, and Connected Android Devices.

Usage:
    python .agents/scripts/harness_doctor.py
    python .agents/scripts/harness_doctor.py --json
    python .agents/scripts/harness_doctor.py --device
    python .agents/scripts/harness_doctor.py --repo /path/to/app
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _repo_files import REPO  # noqa: E402
from doctor.engine import AGENTS_DIR, HarnessDoctor  # noqa: E402
from doctor.models import (  # noqa: E402
    CORE_REFERENCES,
    CORE_SCRIPTS,
    CORE_SUBAGENTS,
    CORE_WORKFLOWS,
    KNOWN_DOMAINS,
    CheckResult,
)

enable_line_buffered_stdio()

__all__ = [
    "AGENTS_DIR",
    "CORE_SUBAGENTS",
    "CORE_SCRIPTS",
    "CORE_WORKFLOWS",
    "CORE_REFERENCES",
    "KNOWN_DOMAINS",
    "CheckResult",
    "HarnessDoctor",
    "print_report",
    "main",
]


def print_report(results: list[CheckResult], already_streamed: bool = False) -> int:
    if not already_streamed:
        print("==================================================", flush=True)
        print("  Android Agent Harness: 12-Dimension Diagnostic Report", flush=True)
        print("==================================================", flush=True)

        current_cat = ""
        for r in results:
            if r.category != current_cat:
                current_cat = r.category
                print(f"\n[*] {current_cat}", flush=True)

            badge = f"[{r.status}]"
            print(f"  {badge:<6} {r.name}: {r.message}", flush=True)
            if r.details:
                for d in r.details:
                    print(f"         - {d}", flush=True)

    pass_count = sum(1 for r in results if r.status == "PASS")
    warn_count = sum(1 for r in results if r.status == "WARN")
    fail_count = sum(1 for r in results if r.status == "FAIL")

    print("\n==================================================", flush=True)
    print(f"  Diagnostic Summary: {pass_count} Passed, {warn_count} Warnings, {fail_count} Failures", flush=True)
    print("==================================================", flush=True)

    if fail_count == 0:
        print("\n[SUCCESS] All core systems operational. Harness is 100% healthy and ready for active delivery.", flush=True)
        return 0
    else:
        print(f"\n[FAIL] {fail_count} critical failure(s) detected. Please remediate the issues above.", flush=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Android Agent Harness 12-Dimension Diagnostic Engine")
    parser.add_argument("--repo", default=str(REPO), help="Path to Android project root")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON report")
    parser.add_argument("--device", action="store_true", help="Include connected ADB device diagnostics")
    parser.add_argument("--no-selftest", action="store_true", help="Skip re-running full hook selftest suite")
    args = parser.parse_args(argv)

    repo_path = Path(args.repo).resolve()
    live_stream = not args.json
    doctor = HarnessDoctor(repo_path, check_device=args.device, run_selftest=not args.no_selftest, live_stream=live_stream)
    results = doctor.run_all()

    if args.json:
        report_data = {
            "passed": sum(1 for r in results if r.status == "PASS"),
            "warnings": sum(1 for r in results if r.status == "WARN"),
            "failures": sum(1 for r in results if r.status == "FAIL"),
            "checks": [asdict(r) for r in results],
        }
        print(json.dumps(report_data, indent=2), flush=True)
        return 0 if report_data["failures"] == 0 else 1

    return print_report(results, already_streamed=live_stream)


if __name__ == "__main__":
    sys.exit(main())
