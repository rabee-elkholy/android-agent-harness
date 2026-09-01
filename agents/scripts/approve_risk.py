"""Human-only interactive approval for HIGH and CRITICAL risk tiers.

Usage:
  python .agents/scripts/approve_risk.py

Safety invariant:
- This script requires interactive confirmation from a real developer (via stdin tty).
- AI agents executing automated commands run with stdin=DEVNULL, which causes this
  script to REFUSE self-approval.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_state import tree_code_fingerprint  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _repo_files import REPO  # noqa: E402
from risk_tier import (  # noqa: E402
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_LOW,
    TIER_MEDIUM,
    classify_working_tree_risk,
    write_risk_approval,
)


def is_interactive() -> bool:
    """Check if execution is attached to an interactive terminal."""
    if os.environ.get("_IN_HOOK_SELFTEST") == "1":
        # Allow testing harness to pass simulated stdin when selftest flag is explicitly present
        return True
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def main(argv=None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Authorize HIGH or CRITICAL risk changes")
    parser.add_argument("--yes", action="store_true", help="Non-interactive approval flag (selftest/developer CI only)")
    args = parser.parse_args(argv)

    tier, reasons = classify_working_tree_risk(REPO)
    fp = tree_code_fingerprint(REPO) or ""

    if tier in (TIER_LOW, TIER_MEDIUM):
        live_print(f"[OK] Current working tree risk tier is {tier}; no human approval required.")
        return 0

    if not is_interactive() and not (args.yes and os.environ.get("_IN_HOOK_SELFTEST") == "1"):
        live_print(
            f"[REFUSED] approve_risk requires interactive developer confirmation (stdin).\n"
            f"The AI agent cannot approve risk on its own.\n"
            f"Please run 'python .agents/scripts/approve_risk.py' manually in your terminal to approve {tier} risk.",
            err=True,
        )
        return 1

    live_print(f"==================================================")
    live_print(f"[!] Risk Approval Request: {tier} Tier")
    live_print(f"==================================================")
    live_print(f"Tree Fingerprint: {fp or '(clean)'}")
    live_print("Identified Risk Factors:")
    for r in reasons[:10]:
        live_print(f"  - {r}")
    if len(reasons) > 10:
        live_print(f"  ... and {len(reasons) - 10} more")
    live_print("--------------------------------------------------")

    if args.yes and os.environ.get("_IN_HOOK_SELFTEST") == "1":
        confirm = "YES"
    else:
        try:
            prompt = f"Type 'YES' to authorize this {tier} risk tier for tree fingerprint {fp[:8]}: "
            confirm = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            live_print("\n[REFUSED] Approval aborted (EOF or interrupt).", err=True)
            return 1

    if confirm != "YES":
        live_print(f"[REFUSED] Authorization failed: expected 'YES', received '{confirm}'.", err=True)
        return 1

    target = write_risk_approval(tier, fp, REPO)
    if not target:
        live_print("[FAIL] Could not write risk approval file.", err=True)
        return 1

    live_print(f"[SUCCESS] Risk tier {tier} successfully authorized by developer: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
