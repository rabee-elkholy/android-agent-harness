import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_state import MAX_REVIEWS, invoke_count, reviews_pending  # noqa: E402


def conversation_id(payload: dict) -> str:
    return str(payload.get("conversationId") or payload.get("conversation_id") or "unknown")


def check_update_directive() -> str:
    try:
        from check_kit_update import check_for_update
        info = check_for_update(force=False)
        if info.get("has_update"):
            curr = info.get("current", "0.2.8")
            latest = info.get("latest", "")
            return (
                f" [KIT UPDATE AVAILABLE: v{latest}]: A newer version of Android Harness Kit (v{latest}) is available (installed: v{curr}). "
                f"In this opening turn, notify the developer via ask_question in their language: 'New Android Harness Kit v{latest} is available! What would you like to do?' "
                f"Choices: 'View Changes (عرض التغييرات)' / 'Remind me tomorrow (ذكرني غداً)' / 'Update now (تحديث الآن)'. "
                f"If they pick 'Remind me tomorrow': run `python .agents/scripts/check_kit_update.py --snooze 1` and proceed with their request. "
                f"If they pick 'View Changes': run `python .agents/scripts/check_kit_update.py --show-changes` to show the changelog, then ask 'Update now' or 'Remind me tomorrow'. "
                f"If they pick 'Update now': execute docs/update-prompt.md."
            )
    except Exception:
        pass
    return ""


def message_for(used_reviews: int, pending: bool, update_directive: str = "") -> str:
    if used_reviews >= MAX_REVIEWS:
        return (
            f"Harness Quality Guard: Runaway review cap reached ({used_reviews}/{MAX_REVIEWS}). "
            "This is an infinite-loop stop, not permission to skip quality. "
            "Inspect why the same findings keep returning. Do not assemble a leftover APK."
        )
    pending_note = (
        " A 5-leaf review round is still pending — do not assembleDebug until all 5 reply."
        if pending
        else ""
    )
    return (
        f"Harness Quality-First Guard: review rounds used {used_reviews}/{MAX_REVIEWS}.{pending_note}{update_directive} "
        "PRIORITY: uncompromising quality. Never skip the 5-leaf review to save tokens. "
        "PLAN FIRST: New features, screens, or multi-file changes MUST create .agents/state/plans/implementation_plan.md and get developer approval BEFORE writing code. "
        "ANSWER FIRST in chat before ask_question. Match ask_question language to the developer. "
        "(Recommended) is only for engineering tradeoffs — never on Pass/Fail or plan approval. "
        "PARALLEL REVIEW: if subagents are not yet registered, call define_subagent for each from .agents/subagents/*.json, then dispatch bug-reviewer-agent, convention-reviewer-agent, "
        "security-reviewer-agent, perf-anr-guardian-agent, regression-impact-reviewer-agent "
        "in EXACTLY ONE invoke_subagent call with the same HARNESS_REVIEW_PACKAGE. "
        "Do not use code-review-guard-agent. Do not fire 5 separate invokes. "
        "REACTIVE WAKEUP: After invoke_subagent, immediately stop calling tools. NEVER use schedule or timers to wait for subagents (the harness wakes automatically). "
        "Wait for BUG_PASS, CONVENTION_PASS, SECURITY_PASS, PERF_PASS, REGRESSION_PASS. "
        "Fix BLOCKER/MAJOR, regenerate the package, re-run the same 5. "
        "On-demand only (not a substitute for the 5): qa-diagnostics-agent, android-ui-expert-agent. "
        "Physical device only. Never commit. Assemble via python .agents/scripts/run_gradle_task.py "
        ":app:assembleDebug. One manual phase at a time via ask_question. "
        "Commit message only after every phase Pass. "
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
