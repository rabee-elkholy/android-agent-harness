---
description: Implement or refactor, 5-leaf review, assemble, physical-device Pass/Fail.
---

# Deliver an Android change

Follow `.agents/rules/harness-rules.md` exactly. Do not commit. Do not use worktrees. Do not invoke `code-review-guard-agent`.

## Steps

1. Inspect. Non-trivial work: write `implementation_plan.md` artifact (`RequestFeedback: true`), link it in chat, wait for developer approval (via native Proceed button or chat). Do not fire `ask_question`.
2. Implement against the files you opened. Compose + MVI for new UI. Dual-locale previews. Both string files.
3. `python .agents/scripts/review_package.py`
4. One `invoke_subagent` with all 5 leaves and the same `HARNESS_REVIEW_PACKAGE`. Wait for all `*_PASS`.
5. `python .agents/scripts/fast_kt_lint.py`. If test files (`*Test.kt`) were modified or added, audit quality with `test-quality-reviewer-agent`. Then `run_gradle_task.py` for tests and `:app:assembleDebug`.
6. `adb devices` then `python .agents/scripts/run_device.py install-start`.
7. One device phase at a time. Walkthrough + commit message only after every Pass.
8. If the work came from a Zoho id: one-line reminder that Zoho is not updated until `update zoho`. Playbook: `.agents/workflows/zoho-sprints.md`.
