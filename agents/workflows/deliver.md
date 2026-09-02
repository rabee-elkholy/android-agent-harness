---
description: Implement or refactor, atomic per-phase review, test gate, assemble, device validation, and sign-off.
---

# Deliver an Android change

Follow `.agents/rules/harness-rules.md` exactly. Do not commit. Do not use worktrees. Do not invoke `code-review-guard-agent`.

## Steps

1. **Inspect & Plan**: For non-trivial work, consult `brainstorming/SKILL.md` and write `implementation_plan.md` artifact (`RequestFeedback: true`). Present Milestone Delivery Strategy for multi-phase tasks and proactively ask in chat about Zoho Sprints story/tasks creation. Wait for developer approval via native Proceed button.
2. **Atomic Phase Execution (Repeat per Phase)**:
   - **TDD & Code**: Follow `test-driven-development/SKILL.md` (Red -> Prove Failure -> Green -> Refactor).
   - **Stage 0 Shift-Left Test & Lint Pre-Gate**: Run `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest` AND `python .agents/scripts/fast_kt_lint.py` to catch compiler mismatches, `!!`, `TODO`s, and missing `@Preview`s before requesting reviews.
   - **Stage 0.5 Test Specialist Gate**: If test files (`*Test.kt`) are modified/added, dispatch `test-quality-reviewer-agent` until `TEST_PASS`.
   - **Stage 1 Review Gate**: Dispatch 5 review leaves in one invoke. Zero timers/sleep. Silent wait on intermediate arrivals. When a round finishes with findings, output a **Review Round Summary Card** in chat, fix at root cause, verify with `fast_kt_lint.py`, and re-dispatch until all 5 emit `*_PASS`.
   - **Stage 2 Mandatory Preflight Gate & Assemble**: Run `python .agents/scripts/preflight_check.py` (MUST be `[SUCCESS]`; never proceed if `[FAIL]`) and `python .agents/scripts/run_gradle_task.py :app:assembleDebug`.
   - **Stage 3 Device Verification & Checkpoint Commit**:
     * Run `python .agents/scripts/run_device.py install-start` to install and launch the target Activity/Screen on the connected device. If no device is connected, HALT and prompt developer via `ask_question`; never silently skip.
     * Output 2-3 **diff-grounded** numbered test steps in chat strictly derived from the modified code (1. Navigation: path to modified screen, 2. Interaction: specific action matching the diff, 3. Verification: expected visual/behavioral outcome).
     * Trigger interactive confirmation modal (`ask_question`): *"Please test the steps above on your device and confirm the result:"* with options `PASS — Device testing passed successfully` / `FAIL — Issue or crash encountered on device`.
     * Upon **PASS**: Output the Phase Milestone Card with the drafted Conventional Commit message for Phase N.
     * **MANDATORY HARD STOP**: Stop immediately and wait for the developer to commit Phase N and explicitly instruct to begin Phase N+1. Never touch Phase N+1 files before developer commit.
3. **Task Completion**: Output walkthrough summary and final task summary in the active conversation language after all phases are verified and committed.
