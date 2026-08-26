---
description: Implement or refactor, test quality pre-gate, 5-leaf review with silent wait, assemble, physical-device Pass/Fail.
---

# Deliver an Android change

Follow `.agents/rules/harness-rules.md` exactly. Do not commit. Do not use worktrees. Do not invoke `code-review-guard-agent`.

## Steps

1. **Inspect & Plan**: For non-trivial work, consult `brainstorming/SKILL.md` and write `implementation_plan.md` artifact (`RequestFeedback: true`). Present Milestone Delivery Strategy for multi-phase tasks. Wait for developer approval via native Proceed button.
2. **Implement & TDD**: Follow `test-driven-development/SKILL.md` (Red -> Prove Failure -> Green -> Refactor) for logic. Compose + MVI for new UI. Dual-locale previews. Both string files.
3. **Preflight & Review Package**: Run `check_strings.py`, `fast_kt_lint.py`, and `python .agents/scripts/review_package.py`.
4. **Pre-Review Test Quality Gate (Stage 0.5)**: If test files (`*Test.kt`) are modified/added, dispatch `test-quality-reviewer-agent` first until `TEST_PASS`.
5. **Parallel 5-Leaf Review Gate (Stage 1)**: One `invoke_subagent` with all 5 leaves and the same `HARNESS_REVIEW_PACKAGE`. Adhere strictly to **Silent Review Wait** (zero intermediate chat spam). Wait for all `*_PASS`.
6. **Assemble & Test**: Run targeted unit tests and `run_gradle_task.py :app:assembleDebug`.
7. **Physical Device Validation**: `adb devices` then `python .agents/scripts/run_device.py install-start`. One device phase at a time.
8. **Phase Completion & Sign-off**: Output standardized milestone progress / final task summary. Walkthrough + commit message only after every phase is Pass.
