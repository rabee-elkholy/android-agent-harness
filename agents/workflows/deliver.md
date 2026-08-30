---
description: Implement or refactor, atomic per-phase review, test gate, assemble, device validation, and sign-off.
---

# Deliver an Android change

Follow `.agents/rules/harness-rules.md` exactly. Do not commit. Do not use worktrees. Do not invoke `code-review-guard-agent`.

## Steps

1. **Inspect & Plan**: For non-trivial work, consult `brainstorming/SKILL.md` and write `implementation_plan.md` artifact (`RequestFeedback: true`). Present Milestone Delivery Strategy for multi-phase tasks and proactively ask in chat about Zoho Sprints story/tasks creation. Wait for developer approval via native Proceed button.
2. **Atomic Phase Execution (Repeat per Phase)**:
   - **TDD & Code**: Follow `test-driven-development/SKILL.md` (Red -> Prove Failure -> Green -> Refactor).
   - **Stage 0 Shift-Left Test Pre-Gate**: Run `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest` to catch signature mismatches and broken call sites.
   - **Stage 0.5 Test Specialist Gate**: If test files (`*Test.kt`) are modified/added, dispatch `test-quality-reviewer-agent` until `TEST_PASS`.
   - **Stage 1 Review Gate**: Dispatch 5 review leaves in one invoke. Zero timers/sleep. Silent wait on intermediate arrivals. When a round finishes with findings, output a **Review Round Summary Card** in chat and fix before re-dispatching until all 5 emit `*_PASS`.
   - **Stage 2 Assemble & Lint**: `python .agents/scripts/fast_kt_lint.py` and `python .agents/scripts/run_gradle_task.py :app:assembleDebug`.
   - **Stage 3 Device Verification & Transition**:
     * In `autonomous_e2e` mode: Run `run_device.py install-start` and `run_e2e_smoke.py`. On [SUCCESS], output Phase Milestone Card and proceed autonomously to Phase N+1 without blocking the developer.
     * In `manual_only` mode: Install on device, output numbered checklist, and trigger `ask_question`.
3. **Task Completion**: Output walkthrough summary and suggest Conventional Commit message after all phases are verified.
