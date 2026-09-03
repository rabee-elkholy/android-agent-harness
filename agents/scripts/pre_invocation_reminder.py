import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_state import (  # noqa: E402
    MAX_REVIEWS,
    invoke_count,
    latest_expired_note,
    reviews_pending,
    round_cap_warning,
)


def conversation_id(payload: dict) -> str:
    return str(payload.get("conversationId") or payload.get("conversation_id") or "unknown")


def _policy_bits() -> dict:
    """Read wizard-configured policies from _product.py (I.3/I.4/I.10 + tasks)."""
    try:
        import _product  # noqa: PLC0415
    except Exception:
        return {
            "unit_test_task": ":app:testDebugUnitTest",
            "assemble_task": ":app:assembleDebug",
            "allow_emulator": True,
            "git_policy": "never",
            "install_confirm": "confirm",
            "e2e_confirm": "confirm",
        }
    return {
        "unit_test_task": str(getattr(_product, "UNIT_TEST_TASK", ":app:testDebugUnitTest")),
        "assemble_task": str(getattr(_product, "ASSEMBLE_TASK", ":app:assembleDebug")),
        "allow_emulator": bool(getattr(_product, "ALLOW_EMULATOR", True)),
        "git_policy": str(getattr(_product, "GIT_POLICY", "never") or "never"),
        "install_confirm": str(getattr(_product, "INSTALL_CONFIRM", "confirm") or "confirm"),
        "e2e_confirm": str(getattr(_product, "E2E_CONFIRM", "confirm") or "confirm"),
    }


def check_update_directive() -> str:
    try:
        from check_kit_update import check_for_update

        info = check_for_update(force=False)
        if info.get("has_update"):
            curr = info.get("current", "")
            latest = info.get("latest", "")
            return (
                f" [KIT UPDATE AVAILABLE: v{latest}]: A newer version of Android Agent Harness (v{latest}) is available (installed: v{curr}). "
                f"In this opening turn, notify the developer via ask_question in their language: 'New Android Agent Harness v{latest} is available! What would you like to do?' "
                f"Choices: 'View Changes' / 'Remind me tomorrow' / 'Update now' (localize the labels to the developer's language). "
                f"If they pick 'Remind me tomorrow': run `python .agents/scripts/check_kit_update.py --snooze 1` and proceed with their request. "
                f"If they pick 'View Changes': run `python .agents/scripts/check_kit_update.py --show-changes` to show the changelog, then ask 'Update now' or 'Remind me tomorrow'. "
                f"If they pick 'Update now': ask the developer to paste the install-or-update prompt for v{latest} "
                f"(https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v{latest}/docs/install-or-update-prompt.md) in a new strong-model chat."
            )
    except Exception:
        pass
    return ""


def message_for(used_reviews: int, pending: bool, update_directive: str = "", round_note: str = "") -> str:
    if used_reviews >= MAX_REVIEWS:
        return (
            f"Harness Quality Guard: Runaway review cap reached ({used_reviews}/{MAX_REVIEWS}). "
            "This is an infinite-loop stop, not permission to skip quality. "
            "If more reviews are genuinely required, start a NEW conversation on this folder "
            "(the cap resets per conversation). Do not assemble a leftover APK."
        )
    bits = _policy_bits()
    expired_note = latest_expired_note()
    pending_note = (
        " [SILENCE MANDATE]: A 5-leaf review round is in flight. If some reviewers are still running, OUTPUT EXACTLY EMPTY STRING ('') AND DO NOT CALL TOOLS. Never output 'Waiting for...', 'Reviewers completing...', or 'Running tests...'. Do not assembleDebug until all 5 reply."
        if pending
        else ""
    )
    device_line = (
        "Physical device only. Do not touch emulator/AVD tooling."
        if not bits["allow_emulator"]
        else "Physical device or emulator are both allowed (prefer physical when both are connected)."
    )
    git_line = (
        "Never commit. Leave changes unstaged; the developer commits from their IDE."
        if bits["git_policy"] != "agent-may-commit"
        else "Git policy allows ONLY `git add` / `git commit`, and only when the developer explicitly asked in this chat. push/merge/rebase/reset/stash stay forbidden."
    )
    install_line = (
        "INSTALL_CONFIRM=confirm: before running run_device.py install-start or any install, ask the developer via ask_question and wait for approval."
        if bits["install_confirm"] != "allow"
        else "Device install does not need a confirmation modal on this project."
    )
    device_verif_line = (
        "DEVICE VERIFICATION: Default mode is interactive manual checklist. Run `run_device.py install-start`, write 2-3 simple test steps in chat, trigger `ask_question` confirmation ('PASS / FAIL'), and upon PASS deliver the drafted Conventional Commit message."
    )
    cap_note = f" {round_note}" if round_note else ""
    return (
        f"Harness Quality Guard: review rounds used {used_reviews}/{MAX_REVIEWS}.{pending_note}{expired_note}{cap_note}{update_directive} "
        "ACTIVE PIPELINE REMINDER: "
        f"1. Pre-gate: `{bits['unit_test_task']}` + `fast_kt_lint.py` before review. "
        "2. Review: Run `review_package.py`. SMART TEST PROMOTION mandates all 6 leaves (+ test-quality-reviewer-agent -> TEST_PASS) for test diffs (*Test.kt, src/test/); "
        "otherwise dispatch the 5 standard review leaves in EXACTLY ONE invoke_subagent call: "
        "bug-reviewer-agent, convention-reviewer-agent, security-reviewer-agent, perf-anr-guardian-agent, regression-impact-reviewer-agent. "
        "Do not use code-review-guard-agent. Zero chat noise on intermediate reviews; ZERO-TIMER INVARIANT: never use schedule or polling timers for subagents. "
        "3. ROUND SUMMARY CARDS: Emit structured card in developer's language when all verdicts arrive. Converge in <= 3 rounds. "
        "4. On-demand specialists: qa-diagnostics-agent, android-ui-expert-agent. "
        f"5. Build & Device: preflight_check.py (must pass with 0 errors) -> `{bits['assemble_task']}` -> `run_device.py install-start`. {device_line} {git_line} {install_line} {device_verif_line} "
        "6. AUTONOMOUS PHASE PIPELINE: Multi-phase tasks stop after device test + ask_question for developer commit before next phase. "
        "7. Project Trackers: Mutate only on 'update zoho' (zero emojis/jargon in QA comments). "
        "8. INTERACTIVE DISCOVERY & ATTACHED MEDIA: Inspect attached screenshots/media via view_file in Turn 1. If any edge cases, offline states, empty country/ISO, or missing scenarios are underspecified, PROACTIVELY INTERVIEW the developer via ask_question before authoring implementation_plan.md. Never invent business logic or fallbacks. ZERO-SCRAPING: never search host PC or scrape web for failed tracker tickets; fallback to prompt immediately."
    )


def should_inject(payload: dict, used_reviews: int, pending: bool) -> bool:
    if used_reviews >= MAX_REVIEWS or pending:
        return True
    invocation = payload.get("invocationNum")
    try:
        n = int(invocation)
    except (TypeError, ValueError):
        n = 0 if invocation in (0, "0", None) else -1
    return n in (0, 1) or (n > 0 and n % 4 == 0)


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        conv = conversation_id(payload)
        used_reviews = invoke_count(conv, "review")
        pending = reviews_pending(conv)
        if not should_inject(payload, used_reviews, pending):
            print(json.dumps({}))
            return
        invocation = payload.get("invocationNum")
        try:
            n = int(invocation)
        except (TypeError, ValueError):
            n = 0 if invocation in (0, "0", None) else -1
        update_dir = check_update_directive() if n in (0, 1) else ""
        task_id = payload.get("taskId") or payload.get("task_id") or None
        round_note = round_cap_warning(task_id)
        print(json.dumps({
            "injectSteps": [{"ephemeralMessage": message_for(used_reviews, pending, update_dir, round_note)}]
        }))
    except Exception:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
