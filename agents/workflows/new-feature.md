---
description: Implement a new feature with brainstorming, TDD, atomic milestone delivery, and quality gates.
---

# New feature

Follow `.agents/rules/harness-rules.md`. Do not commit.

`new_feature_scaffold.py` is **disabled**. It still holds `VIEWMODEL` / `SCREEN` strings for selftest only. Do not run it.

## Steps

1. **Brainstorm & Clarify**: Consult `brainstorming/SKILL.md` to explore 2–3 architectural approaches with trade-offs. If a Zoho id was provided: fetch it (read-only), explain, and ask whether to start the plan. Playbook: `.agents/workflows/zoho-sprints.md`.
2. **Plan & Proactive PM Proposal**: Author `implementation_plan.md` artifact (`RequestFeedback: true`). For multi-phase plans, offer Strategy 1 (Atomic Step-by-Step Phase Delivery) vs Strategy 2 (All-in-One), and **proactively ask in chat** about creating a User Story with Phase sub-tasks on Zoho Sprints. Wait for developer approval via native Proceed button.
3. **Atomic Phase Implementation (Iterative Cycle)**:
   - **TDD Cycle**: `test-driven-development/SKILL.md` (Red -> Prove Failure -> Green -> Refactor).
   - **Quality Review Gates**: Stage 0.5 `test-quality-reviewer-agent` (if tests present) -> Stage 1 5-Leaf Review Gate with **Silent Review Wait**.
   - **Build & Device Sign-off**: Run unit tests, `:app:assembleDebug`, install via `run_device.py install-start` for UI phases, obtain developer sign-off, and commit before next phase.
