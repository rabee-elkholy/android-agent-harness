"""Human-only interactive approval for HIGH and CRITICAL risk tiers.

Usage:
  # Automated AI Agent Flow (Challenge-Nonce Protocol):
  # 1. Generate challenge token:
  python .agents/scripts/approve_risk.py --challenge
  # 2. Agent presents challenge to developer via interactive chat modal (ask_question)
  # 3. Upon explicit human confirmation, redeem token:
  python .agents/scripts/approve_risk.py --token AUTH-XXXXXX

  # Interactive Developer Terminal Flow:
  python .agents/scripts/approve_risk.py

Safety invariants:
- Bare --approve flag is strictly disabled outside selftests to prevent AI self-approval.
- Challenge tokens are single-use, expire after 15 minutes, and are cryptographically bound
  to the exact working tree code fingerprint.
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
    consume_risk_challenge,
    create_risk_challenge,
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
    parser.add_argument(
        "--challenge",
        action="store_true",
        help="Generate a single-use challenge token bound to the current working tree",
    )
    parser.add_argument(
        "--token",
        type=str,
        default="",
        help="Redeem a challenge token authorized by the developer",
    )
    parser.add_argument(
        "--approve",
        "--yes",
        action="store_true",
        dest="approve",
        help="Approve current risk tier (selftest only; disabled in production)",
    )
    args = parser.parse_args(argv)

    tier, reasons = classify_working_tree_risk(REPO)
    fp = tree_code_fingerprint(REPO) or ""

    # Mode 1: Challenge Generation
    if args.challenge:
        if tier in (TIER_LOW, TIER_MEDIUM):
            live_print(f"[OK] Current working tree risk tier is {tier}; no human approval required.")
            return 0
        token, ch_path, ch_tier, ch_reasons = create_risk_challenge(REPO)
        live_print("==================================================")
        live_print(f"[!] Risk Approval Challenge Created: {ch_tier} Tier")
        live_print("==================================================")
        live_print(f"Challenge Token : {token}")
        live_print(f"Tree Fingerprint: {fp[:12] if fp else '(clean)'}")
        live_print("Expires In      : 15 minutes")
        live_print("Identified Risk Factors:")
        for r in ch_reasons[:10]:
            live_print(f"  - {r}")
        if len(ch_reasons) > 10:
            live_print(f"  ... and {len(ch_reasons) - 10} more")
        live_print("--------------------------------------------------")
        live_print("Instructions for AI Agent:")
        live_print("1. Present the challenge to the developer in chat via ask_question modal:")
        live_print(f"   Question: High-risk modifications detected ({ch_tier} tier: {ch_reasons[0] if ch_reasons else 'sensitive changes'}). Do you authorize proceeding with approval token {token}?")
        live_print(f"   Options: ['Approve {ch_tier} changes (Token: {token})', 'Reject / abort changes']")
        live_print("2. Upon developer confirmation, redeem the token by running:")
        live_print(f"   python .agents/scripts/approve_risk.py --token {token}")
        live_print("==================================================")
        return 0

    # Mode 2: Challenge Token Redemption
    if args.token:
        ok, res_tier, msg = consume_risk_challenge(args.token, REPO)
        if ok:
            live_print(f"[SUCCESS] {msg}")
            return 0
        else:
            live_print(f"[REFUSED] {msg}", err=True)
            return 1

    # Mode 3: Bare --approve check
    if args.approve:
        if os.environ.get("_IN_HOOK_SELFTEST") == "1":
            target = write_risk_approval(tier, fp, REPO, approved_by="selftest_approve")
            if not target:
                live_print("[FAIL] Could not write risk approval file.", err=True)
                return 1
            live_print(f"[SUCCESS] [SELFTEST] Risk tier {tier} approved: {target}")
            return 0
        live_print(
            "[REFUSED] Bare --approve flag is disabled for security.\n"
            "AI agents cannot self-approve HIGH/CRITICAL risks.\n"
            "1. Generate a challenge: python .agents/scripts/approve_risk.py --challenge\n"
            "2. Request developer confirmation via ask_question modal in chat\n"
            "3. Redeem with: python .agents/scripts/approve_risk.py --token <TOKEN>",
            err=True,
        )
        return 1

    # If already low/medium risk and run without args
    if tier in (TIER_LOW, TIER_MEDIUM):
        live_print(f"[OK] Current working tree risk tier is {tier}; no human approval required.")
        return 0

    # Mode 4: Non-interactive automated execution without challenge or token
    if not is_interactive():
        live_print(
            f"[REFUSED] approve_risk requires developer confirmation.\n"
            f"1. Generate a challenge token: python .agents/scripts/approve_risk.py --challenge\n"
            f"2. Prompt the developer in chat via ask_question modal with the token.\n"
            f"3. Redeem the token upon confirmation: python .agents/scripts/approve_risk.py --token <TOKEN>",
            err=True,
        )
        return 1

    # Mode 5: Interactive Developer Terminal Execution (TTY)
    live_print("==================================================")
    live_print(f"[!] Risk Approval Request: {tier} Tier")
    live_print("==================================================")
    live_print(f"Tree Fingerprint: {fp or '(clean)'}")
    live_print("Identified Risk Factors:")
    for r in reasons[:10]:
        live_print(f"  - {r}")
    if len(reasons) > 10:
        live_print(f"  ... and {len(reasons) - 10} more")
    live_print("--------------------------------------------------")

    try:
        prompt = f"Type 'YES' to authorize this {tier} risk tier for tree fingerprint {fp[:8]}: "
        confirm = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        live_print("\n[REFUSED] Approval aborted (EOF or interrupt).", err=True)
        return 1

    if confirm != "YES":
        live_print(f"[REFUSED] Authorization failed: expected 'YES', received '{confirm}'.", err=True)
        return 1

    target = write_risk_approval(tier, fp, REPO, approved_by="interactive_tty")
    if not target:
        live_print("[FAIL] Could not write risk approval file.", err=True)
        return 1

    live_print(f"[SUCCESS] Risk tier {tier} successfully authorized by developer: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
