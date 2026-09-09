---
description: Deliver an approved Android change through adaptive, evidence-bound verification.
---

# Deliver an Android change

Follow `.agents/rules/harness-rules.md`. Analysis and planning are read-only. No implementation begins until the developer explicitly approves the exact plan.

1. Draft the task with `workflow.py draft`; include expected surfaces, modules, risks, test strategy, device strategy, rollback, and routed skills.
2. Present the plan and wait. After explicit approval, record its proof with `workflow.py approve`, then consume it once with `workflow.py begin`.
3. Implement only the approved scope. Use TDD and domain skills selected by the plan. Material classifier drift invalidates approval.
4. Run `workflow.py prepare-verification`. Read the generated policy; do not invent extra gates or omit selected gates.
5. Run selected unit, preflight, assemble, and device gates. Build/install/launch evidence must refer to the same complete APK set.
6. If reviewers are selected, create one complete package, dispatch exactly those reviewer roles, and ingest their structured reports. Findings return the task to `BLOCKED`; use `resume` after fixing. Maximum three review rounds.
7. Run read-only `workflow.py verify`, then `workflow.py complete`. Present the result only when the exact snapshot remains ready.

Never commit or push; Git index/history remain developer-owned. Zoho mutation requires the explicit trigger, approved `zoho_sprints` external-write scope, and a stable operation id.
