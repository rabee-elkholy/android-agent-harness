---
description: Implement a new feature with brainstorming, TDD, milestone delivery, and quality gates.
---

# New feature

Follow `.agents/rules/harness-rules.md`. Do not commit.

`new_feature_scaffold.py` is **disabled**. It still holds `VIEWMODEL` / `SCREEN` strings for selftest only. Do not run it.

## Steps

1. **Brainstorm & Clarify**: Consult `brainstorming/SKILL.md` to explore 2–3 architectural approaches with trade-offs. If a Zoho id was provided: fetch it (read-only), explain, and ask whether to start the plan. Playbook: `.agents/workflows/zoho-sprints.md`.
2. **Plan & Milestone Strategy**: Author `implementation_plan.md` artifact (`RequestFeedback: true`). For multi-phase plans, offer Strategy 1 (Iterative Phase-by-Phase) vs Strategy 2 (All-in-One). If PM/Zoho is active, offer to create a User Story with Phase sub-tasks. Wait for developer approval via native Proceed button.
3. **Test-Driven Development (TDD)**: Follow `test-driven-development/SKILL.md` (Red -> Prove Failure -> Green -> Refactor) for logic, UseCases, Repositories, and ViewModels.
4. **Implement UI & Domain**: Add files in **this** app's real packages. UI guidance: `android-ui-expert-agent`.
5. **Quality Review Gates**:
   - `python .agents/scripts/check_strings.py` and `fast_kt_lint.py`.
   - **Stage 0.5**: If tests (`*Test.kt`) were modified/created, dispatch `test-quality-reviewer-agent` first until `TEST_PASS`.
   - **Stage 1**: Dispatch all 5 review leaves in one invoke with **Silent Review Wait** (zero intermediate chat noise).
6. **Build & Device Validation**: Run tests, then `:app:assembleDebug`, install on physical device, and validate phases.
