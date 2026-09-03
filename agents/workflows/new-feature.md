---
description: Implement a new feature with brainstorming, TDD, atomic milestone delivery, and quality gates.
---

# New feature

Follow `.agents/rules/harness-rules.md`. Do not commit.

`new_feature_scaffold.py` is **disabled**. It still holds `VIEWMODEL` / `SCREEN` strings for selftest only. Do not run it.

## Steps

1. **Brainstorm & Interactive Clarification (The Zero-Assumption Barrier)**:
   - If screenshots/media are attached, inspect via `view_file` in Turn 1. Never ignore visual evidence.
   - If an issue/ticket ID is provided: fetch read-only with at most 1 attempt (fail-fast to prompt description if unavailable; zero scraping/PC scanning).
   - Systematically audit for unaddressed edge cases: offline/no-network behavior, raw exception mapping to friendly Arabic/English texts, missing country/ISO, cache TTL, empty states, and error handling.
   - If ANY edge case or requirement is underspecified, **proactively interview the developer via the interactive modal `ask_question`** (with concrete selectable options) before authoring `implementation_plan.md`. Never output questions as conversational chat prose and never leave them as open questions in the plan. Never guess or assume business logic from your own head. Build the plan right the first time.
2. **Plan & Proactive PM Proposal**: Author `implementation_plan.md` artifact (`RequestFeedback: true`). For multi-phase plans, offer Strategy 1 (Atomic Step-by-Step Phase Delivery) vs Strategy 2 (All-in-One), and **proactively ask in chat** about creating a User Story with Phase sub-tasks on Zoho Sprints. Wait for developer approval via native Proceed button.
3. **Atomic Phase Implementation (Iterative Cycle)**:
   - **TDD Cycle**: `test-driven-development/SKILL.md` (Red -> Prove Failure -> Green -> Refactor).
   - **Quality Review Gates**: Stage 0.5 `test-quality-reviewer-agent` (if tests present) -> Stage 1 5-Leaf Review Gate with **Silent Review Wait**.
   - **Build & Device Sign-off**: Run unit tests, `:app:assembleDebug`, install via `run_device.py install-start` for UI phases, obtain developer sign-off, and commit before next phase.
