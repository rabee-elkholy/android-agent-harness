---
description: Deliver an approved Android change through adaptive, evidence-bound verification.
---

# Deliver an Android change

Follow `.agents/rules/harness-rules.md`. Analysis and planning are read-only. No implementation begins until the developer explicitly approves the exact plan.

1. Draft the task with `workflow.py draft`; include expected surfaces, modules, risks, test strategy, device strategy, rollback, and routed skills.
2. Present the plan and wait. After explicit approval, record its proof with `workflow.py approve`, then consume it once with `workflow.py begin`.
3. Implement only the approved scope. Use TDD and domain skills selected by the plan. Material classifier drift invalidates approval.
4. Run `workflow.py prepare-verification`. Read the generated policy; execute selected gates and reviewers in strict pipeline order:
   a. **Preflight**: Run `python .agents/scripts/preflight_check.py` (String parity, fast Kotlin lint, plan authority).
   b. **Unit Tests**: Run `python .agents/scripts/run_tests_gate.py` (`testDebugUnitTest`). Never dispatch reviewers or install on device if tests fail.
   c. **Reviewers**: If reviewers are selected, create `review-package.md`, dispatch the routed reviewer subagents in parallel, and record verdicts with `record_review.py`. Findings return the task to `BLOCKED`; use `workflow.py resume` after fixing. Maximum three review rounds.
   d. **Assemble & Device**: If device verification is selected, run `python .agents/scripts/run_device.py install-start` to install and launch on target device/emulator. Then provide concise numbered manual test steps and prompt developer confirmation via `ask_question`.
5. Run read-only `python .agents/scripts/workflow.py verify`, then `python .agents/scripts/workflow.py complete`. Present the result only when the exact snapshot remains ready.

Never commit or push; Git index/history remain developer-owned. Zoho mutation requires the explicit trigger, approved `zoho_sprints` external-write scope, and a stable operation id.
