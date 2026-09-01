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
    e2e_line = (
        "E2E_CONFIRM=confirm: before authoring test cases or running E2E, ask the developer via ask_question ('Start E2E round?' / 'Skip E2E') in their language and wait for the choice. On Skip, do NOT author test cases, mark device verification 'skipped by developer' in the milestone card, and never pretend it passed. On Start E2E, author positive/negative/edge cases and execute."
        if bits["e2e_confirm"] != "allow"
        else "E2E execution does not need a confirmation modal on this project."
    )
    cap_note = f" {round_note}" if round_note else ""
    return (
        f"Harness Quality-First Guard: review rounds used {used_reviews}/{MAX_REVIEWS}.{pending_note}{expired_note}{cap_note}{update_directive} "
        "ZERO-NOISE CHAT & HUMAN-READABLE BACKGROUND TASKS: Match the developer's active conversation language (mirror whatever language they write in) across all cards and messages. When background tasks run, NEVER print raw task IDs (e.g. 'fd98ab26.../task-1004') or robotic meta-phrases (e.g. 'Output text must be strictly empty', 'Stopped calling tools to wait...'). If emitting a waiting update, state ONLY the concise action name in plain text (e.g. 'Running unit tests in background...', 'Assembling debug APK...', 'Awaiting code review verdicts...') or remain silent `\"\"`. "
        "ANTI-HALLUCINATION & SEQUENTIAL DEPENDENCY INVARIANT: NEVER fabricate, simulate, inject, or write `<MESSAGE_RECEIVED>`, `<SYSTEM_MESSAGE>`, or assume background task completion in thoughts or prose. When a background task is a prerequisite for the next step (e.g. assembleDebug before install-start; install-start before run_e2e_smoke), STOP calling tools IMMEDIATELY and wait passively for the genuine platform system message (`finished with result:`) before dispatching dependent tools. "
        "ENV-FAILURE HALT PROTOCOL: If run_device.py, run_e2e_smoke.py, or run_gradle_task.py exits with code 30 or prints [ENV-FAILURE], the problem is environmental or ambiguous. HALT IMMEDIATELY: never modify project code, Gradle files, or the manifest to bypass it; read .agents/state/env_failure.json, report the reason to the developer, and wait for instructions. "
        "SHIFT-LEFT QUALITY: Before requesting reviews, proactively satisfy all review pillars (null/network resilience, MVI single-source StateFlow, no inline FQCNs, Compose contentDescription & 48dp touch targets, dual-locale en/ar previews, zero Main-thread I/O, Room migration if @Entity changes). "
        f"SHIFT-LEFT TEST & LINT PRE-GATE: Before calling review_package.py and invoke_subagent, when code or unit tests are touched, ALWAYS run `python .agents/scripts/run_gradle_task.py {bits['unit_test_task']}` AND `python .agents/scripts/fast_kt_lint.py` to verify compiler/signature parity and zero lint violations (diff-scoped on modified lines) before dispatching subagents. "
        "PLAN FIRST: New features, screens, or multi-file changes MUST create implementation_plan.md artifact with RequestFeedback=true and get developer approval via Proceed button BEFORE writing code. "
        "ANSWER FIRST in chat before ask_question. Match ask_question language to the developer. "
        "(Recommended) is only for engineering tradeoffs — never on Pass/Fail. "
        "PARALLEL REVIEW: if subagents are not yet registered, call define_subagent for each from .agents/subagents/*.json. "
        "When diff touches test files (*Test.kt, src/test/), SMART TEST PROMOTION mandates all 6 leaves (+ test-quality-reviewer-agent -> TEST_PASS); "
        "otherwise dispatch the 5 standard review leaves in EXACTLY ONE invoke_subagent call: "
        "bug-reviewer-agent, convention-reviewer-agent, security-reviewer-agent, perf-anr-guardian-agent, regression-impact-reviewer-agent "
        "with the same HARNESS_REVIEW_PACKAGE. "
        "Do not use code-review-guard-agent. Do not fire separate invokes. "
        "REACTIVE WAKEUP & ZERO-TIMER INVARIANT: After invoke_subagent, stop calling tools immediately. NEVER use schedule, sleep, or polling timers for subagents. When woken up while some reviewers are still running, OUTPUT ZERO CHAT TEXT, call no tools, and end turn silently. "
        "ROUND SUMMARY CARDS: When all verdicts arrive, output a concise Review Round Summary Card in chat (detailing the findings and corrective fixes on findings, or listing the clean PASS verdicts when all reviewers clear the diff) before proceeding or re-dispatching. Review rounds must converge in <= 3 rounds. "
        "Wait for BUG_PASS, CONVENTION_PASS, SECURITY_PASS, PERF_PASS, REGRESSION_PASS (+ TEST_PASS for test diffs). "
        "Fix BLOCKER/MAJOR, verify with fast_kt_lint.py, regenerate the package, re-run the same leaves. "
        "On-demand specialists (when not auto-promoted): qa-diagnostics-agent, android-ui-expert-agent. "
        f"{device_line} {git_line} Assemble via python .agents/scripts/run_gradle_task.py {bits['assemble_task']}. {install_line} {e2e_line} "
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
        task_id = payload.get("taskId") or payload.get("task_id") or None
        round_note = round_cap_warning(task_id)
        print(json.dumps({
            "injectSteps": [{"ephemeralMessage": message_for(used_reviews, pending, update_dir, round_note)}]
        }))
    except Exception:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
