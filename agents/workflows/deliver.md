---
description: Deliver an approved Android change through adaptive, evidence-bound verification.
---

# Deliver an Android change

Follow `.agents/rules/harness-rules.md`. Analysis and planning are read-only. No implementation begins until the developer explicitly approves the exact plan.

## 1. PLAN
- **Discovery**: Graph-backed discovery via `python .agents/harness.py task-context` or `project_graph.py`.
- **Draft**: Create plan via `python .agents/scripts/workflow.py draft` (including expected surfaces, modules, risks, test strategy, and any Zoho link or MCP write scopes).
- **Present Plan**: Present native plan artifact or chat plan to developer (`workflow.py present-plan`).
- **Approve**: Record explicit developer approval via `python .agents/scripts/workflow.py approve` (which atomically transitions directly to `IMPLEMENTING`; `begin` is idempotent compatibility).

## 2. BUILD
- **Zoho Start Sync**: If plan includes approved `zoho_link`, sync task start via `python .agents/harness.py zoho start-sync --task-id <id>`.
- **Implementation**: Implement code changes within approved scope. Diagnostic compile via `python .agents/harness.py assemble`.
- **Phase Checkpoints**: For multi-phase plans, advance checkpoints via `workflow.py checkpoint-phase`.

## 3. VERIFY
- **Prepare**: Freeze review package and transition to `VERIFYING` via `python .agents/scripts/workflow.py prepare-verification --repo . --task-id <id>`.
- **Preflight**: Run deterministic preflight gate via `python .agents/harness.py preflight`.
- **Unit Tests**: Run unit tests gate via `python .agents/harness.py test` (when required by policy).
- **Review Package & Dispatch**: Build review package (`python .agents/harness.py review package`) and dispatch routed reviewers in parallel. While reviewers run, Next Action indicates `WAIT_FOR_REVIEWERS`. Zero-polling invariant: wait for reactive completion.
- **Review Completion**: On reactive completion, record trusted results via `python .agents/harness.py review complete --task <id> --reviewer <role> --execution-id <convId>`.
- **Aggregate Reviews**: Once all complete, aggregate reviews via `python .agents/harness.py review finalize --task <id>`. Findings return task to `BLOCKED`; fix and use `workflow.py resume`.
- **Assemble**: Build application debug artifact via `python .agents/harness.py assemble` (derived assemble task).
- **Mobile Validation**: When device verification is required, execute `python .agents/harness.py device install-start` or, if developer explicitly requests skip, record honest skip via `python .agents/harness.py device skip-validation --task-id <id> --proof-reference "<phrase>"`.
- **Sensitive Approval**: If sensitive surfaces were touched, record explicit approval via `workflow.py approve-sensitive`.
- **Final Verify**: Run read-only delivery verification via `python .agents/harness.py verify --task-id <id>`.
- **Complete**: Seal task to `READY_FOR_DELIVERY` via `python .agents/scripts/workflow.py complete --repo . --task-id <id>`.

## 4. SHIP
- **Developer Commit**: Developer creates git commit (never auto-committed by agent; working tree remains unstaged).
- **Reconcile Delivery**: Finalize task delivery state via `python .agents/scripts/workflow.py reconcile-delivery --repo . --task-id <id>`.
- **Zoho Delivery Sync**: If plan has approved `zoho_link`, sync delivery report via `python .agents/harness.py zoho delivery-sync --task-id <id>`.
