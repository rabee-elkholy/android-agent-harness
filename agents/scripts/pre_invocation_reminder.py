import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_state import MAX_REVIEWS, invoke_count, latest_expired_note, reviews_pending  # noqa: E402


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
        }
    return {
        "unit_test_task": str(getattr(_product, "UNIT_TEST_TASK", ":app:testDebugUnitTest")),
        "assemble_task": str(getattr(_product, "ASSEMBLE_TASK", ":app:assembleDebug")),
        "allow_emulator": bool(getattr(_product, "ALLOW_EMULATOR", True)),
        "git_policy": str(getattr(_product, "GIT_POLICY", "never") or "never"),
        "install_confirm": str(getattr(_product, "INSTALL_CONFIRM", "confirm") or "confirm"),
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


def message_for(used_reviews: int, pending: bool, update_directive: str = "") -> str:
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
    return (
        f"Harness Quality-First Guard: review rounds used {used_reviews}/{MAX_REVIEWS}.{pending_note}{expired_note}{update_directive} "
        "ZERO-NOISE CHAT & BACKGROUND TASKS: Match the developer's active conversation language (mirror whatever language they write in) across all cards (Review Round, Phase Milestone, Final Delivery) and interactive modals. Never emit mechanical status updates in chat prose (e.g. 'Running tests...', 'Cleaning kapt cache...', 'Waiting for...'). When launching background commands, ALWAYS choose Option A (proceed silently or return zero chat text ''); NEVER write '# Background Task Started' in chat. Rely on IDE tool widgets for routine actions. Chat is reserved exclusively for Plan Approval, Review Round Cards (on findings), Phase Milestone Cards, and Final Delivery. "
        "ANTI-HALLUCINATION & SEQUENTIAL DEPENDENCY INVARIANT: NEVER fabricate, simulate, inject, or write `<MESSAGE_RECEIVED>`, `<SYSTEM_MESSAGE>`, or assume background task completion in thoughts or prose. When a background task is a prerequisite for the next step (e.g. assembleDebug before install-start; install-start before run_e2e_smoke), STOP calling tools IMMEDIATELY and END TURN with zero chat text `\"\"`. Wait passively for the genuine platform system message (`finished with result:`) before dispatching dependent tools. "
        "SHIFT-LEFT QUALITY: Before requesting reviews, proactively satisfy all review pillars (null/network resilience, MVI single-source StateFlow, no inline FQCNs, Compose contentDescription & 48dp touch targets, dual-locale en/ar previews, zero Main-thread I/O, Room migration if @Entity changes). "
        f"SHIFT-LEFT TEST & LINT PRE-GATE: Before calling review_package.py and invoke_subagent, when code or unit tests are touched, ALWAYS run `python .agents/scripts/run_gradle_task.py {bits['unit_test_task']}` AND `python .agents/scripts/fast_kt_lint.py` to verify compiler/signature parity and zero lint violations (diff-scoped on modified lines) before dispatching subagents. "
        "PLAN FIRST: New features, screens, or multi-file changes MUST create implementation_plan.md artifact with RequestFeedback=true and get developer approval via Proceed button BEFORE writing code. "
        "ANSWER FIRST in chat before ask_question. Match ask_question language to the developer. "
        "(Recommended) is only for engineering tradeoffs — never on Pass/Fail. "
        "PARALLEL REVIEW: if subagents are not yet registered, call define_subagent for each from .agents/subagents/*.json, then dispatch bug-reviewer-agent, convention-reviewer-agent, "
        "security-reviewer-agent, perf-anr-guardian-agent, regression-impact-reviewer-agent "
        "in EXACTLY ONE invoke_subagent call with the same HARNESS_REVIEW_PACKAGE. "
        "Do not use code-review-guard-agent. Do not fire 5 separate invokes. "
        "REACTIVE WAKEUP & ZERO-TIMER INVARIANT: After invoke_subagent, stop calling tools immediately. NEVER use schedule, sleep, or polling timers for subagents. When woken up while some reviewers are still running, OUTPUT ZERO CHAT TEXT, call no tools, and end turn silently. "
        "ROUND SUMMARY CARDS: When all 5 verdicts arrive and BLOCKER/MAJOR findings exist, output a concise Review Round Summary Card in chat detailing the findings and corrective fixes before re-dispatching the next round. Review rounds must converge in <= 2 rounds. "
        "Wait for BUG_PASS, CONVENTION_PASS, SECURITY_PASS, PERF_PASS, REGRESSION_PASS. "
        "Fix BLOCKER/MAJOR, verify with fast_kt_lint.py, regenerate the package, re-run the same 5. "
        "On-demand only (not a substitute for the 5): qa-diagnostics-agent, android-ui-expert-agent, test-quality-reviewer-agent. "
        f"{device_line} {git_line} Assemble via python .agents/scripts/run_gradle_task.py {bits['assemble_task']}. {install_line} "
        f"AUTONOMOUS PHASE PIPELINE & CHECKPOINT COMMITS: When Phase N finishes, run {bits['unit_test_task']} + preflight_check.py (MUST PASS with 0 errors; if [FAIL], NEVER run assembleDebug) + {bits['assemble_task']} + install-start + E2E smoke. If no device is connected, HALT and prompt the developer; NEVER silently skip device verification. Output Phase Milestone Card with drafted Phase N commit message, STOP IMMEDIATELY, and wait for the developer to commit Phase N and command start of Phase N+1. Never touch Phase N+1 files before developer commit. "
        "Zoho: never mutate unless the developer says update zoho. Arabic Zoho prose. "
        "Status In progress or Ready To ReTest only. Never Done or Solved."
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
        print(json.dumps({
            "injectSteps": [{"ephemeralMessage": message_for(used_reviews, pending, update_dir)}]
        }))
    except Exception:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
