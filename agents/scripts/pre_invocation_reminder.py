import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_state import MAX_REVIEWS, invoke_count, reviews_pending  # noqa: E402


def conversation_id(payload: dict) -> str:
    return str(payload.get("conversationId") or payload.get("conversation_id") or "unknown")


def message_for(used_reviews: int, pending: bool) -> str:
    if used_reviews >= MAX_REVIEWS:
        return (
            f"Rashaqa Quality Guard: Runaway review cap reached ({used_reviews}/{MAX_REVIEWS}). "
            "This is an infinite-loop stop, not permission to skip quality. "
            "Inspect why the same findings keep returning. Do not assemble a leftover APK."
        )
    pending_note = (
        " A 5-leaf review round is still pending — do not run unit tests or assembleDebug until all 5 reply."
        if pending
        else ""
    )
    return (
        f"Rashaqa Quality-First Guard: review rounds used {used_reviews}/{MAX_REVIEWS}.{pending_note} "
        "PRIORITY: uncompromising quality. Never skip the 5-leaf review to save tokens. "
        "ANSWER FIRST in chat before ask_question. Match ask_question language to the developer. "
        "(Recommended) is only for engineering tradeoffs — never on Pass/Fail or plan approval. "
        "PARALLEL REVIEW: dispatch bug-reviewer-agent, convention-reviewer-agent, "
        "security-reviewer-agent, perf-anr-guardian-agent, regression-impact-reviewer-agent "
        "in EXACTLY ONE invoke_subagent call with the same RASHAQA_REVIEW_PACKAGE. "
        "Do not use code-review-guard-agent. Do not fire 5 separate invokes. "
        "Wait for BUG_PASS, CONVENTION_PASS, SECURITY_PASS, PERF_PASS, REGRESSION_PASS. "
        "Fix BLOCKER/MAJOR, regenerate the package, re-run the same 5. "
        "On-demand only (not a substitute for the 5): qa-diagnostics-agent, android-ui-expert-agent. "
        "Physical device only. Never commit. Assemble via python .agents/scripts/run_gradle_task.py "
        ":app:assembleDebug. One manual phase at a time via ask_question. "
        "Commit message only after every phase Pass."
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
        print(json.dumps({
            "injectSteps": [{"ephemeralMessage": message_for(used_reviews, pending)}]
        }))
    except Exception:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
