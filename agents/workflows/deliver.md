---
description: Implement or refactor, atomic per-phase review, test gate, assemble, device validation, and sign-off.
---

# Deliver an Android change

Follow `.agents/rules/harness-rules.md` exactly. Do not commit. Do not use worktrees. Do not invoke `code-review-guard-agent`.

## Steps

1. **Inspect & Plan**: For non-trivial work, consult `brainstorming/SKILL.md` and write `implementation_plan.md` artifact (`RequestFeedback: true`). Present Milestone Delivery Strategy for multi-phase tasks and proactively ask in chat about Zoho Sprints story/tasks creation. Wait for developer approval via native Proceed button.
2. **Atomic Phase Execution (Repeat per Phase)**:
   - **TDD & Code**: Follow `test-driven-development/SKILL.md` (Red -> Prove Failure -> Green -> Refactor).
   - **Stage 0.5 Test Gate**: If test files (`*Test.kt`) are modified/added, dispatch `test-quality-reviewer-agent` first until `TEST_PASS`.
   - **Stage 1 Review Gate**: Dispatch 5 review leaves in one invoke with **Silent Review Wait**. Wait for all `*_PASS`.
   - **Assemble & Unit Tests**: `run_gradle_task.py :app:testDebugUnitTest` and `:app:assembleDebug`.
   - **Physical Device Validation**: For UI phases, install via `run_device.py install-start` and conduct interactive developer sign-off.
   - **Phase Sign-off & Commit**: Output standardized milestone progress format, write walkthrough, and suggest Conventional Commit message before advancing to the next phase.
