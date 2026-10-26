---
description: Deliver an approved Android change through adaptive, evidence-bound verification.
---

# Deliver an Android change

Follow `.agents/rules/harness-rules.md`. Analysis and planning are read-only. No implementation begins until the developer explicitly approves the exact plan.

## 1. PLAN
- **Discovery**: Graph-backed discovery via `python .agents/harness.py task-context` or `project_graph.py`.
- **Draft**: Create plan via `python .agents/harness.py task draft` (including expected surfaces, modules, risks, test strategy, and any Zoho link or MCP write scopes).
- **Present Plan**: Present native plan artifact or chat plan to developer (`workflow.py present-plan`).
- **Approve**: Record explicit developer approval via `python .agents/harness.py task approve` (which atomically transitions directly to `IMPLEMENTING`; `begin` is idempotent compatibility).

## 2. BUILD
- **Zoho Start Sync**: If plan includes approved `zoho_link`, sync task start via `python .agents/harness.py zoho start-sync --task-id <id>`.
- **Implementation**: Implement code changes within approved scope. Use `python .agents/harness.py compile` for the diagnostic compile check before freezing verification; it is not final delivery evidence.
- **Phase Checkpoints**: For multi-phase plans, advance checkpoints via `workflow.py checkpoint-phase`.

## 3. VERIFY
- **Consecutive deterministic steps**: Once implementation is finished, use `python .agents/harness.py verify-steps --task-id <id> --host <actual-host>`. It follows the router through preparation, required preflight/tests and package creation, stopping at failure, stale inputs, reviews or human decisions. Follow its returned `next_action`; `STOPPED` is not task completion. The individual steps below remain available when specifically routed or diagnosing a failure. Never repeat a status or package command when the previous result already includes the next payload.
- **Prepare**: Freeze the delivery manifest/run and transition to `VERIFYING` via `python .agents/harness.py task prepare-verification --repo . --task-id <id> --host <actual-host>`.
- **Preflight**: Run deterministic preflight gate via `python .agents/harness.py preflight`.
- **Unit Tests**: Run unit tests gate via `python .agents/harness.py test` (when required by policy).
- **Review Package & Dispatch**: Build a review package only when routed (`python .agents/harness.py review package --task-id <id>`); the public deterministic-step commands can already prepare it. Dispatch exactly the returned reviewers with their payload. While reviewers run, Next Action indicates `WAIT_FOR_REVIEWERS`. Zero-polling invariant: wait for reactive completion.
- **Review Completion**: On reactive completion, record trusted results via `python .agents/harness.py review complete --task <id> --reviewer <role> --execution-id <convId>`.
- **Aggregate Reviews**: Once all complete, aggregate reviews via `python .agents/harness.py review finalize --task <id>`. Findings return task to `BLOCKED`; use `task resume` before fixing. Keep the same approved task and completed phases, then run fresh final verification and only the returned follow-up reviewers. Do not re-draft, revise plan prose or replay completed phases to clear findings. A clarification belongs in `task plan-note`; new requirements require `revise` and approval, with `--material-change-reason` for narrative-only changes.
- **Assemble**: Build application debug artifact via `python .agents/harness.py assemble` (derived assemble task).
- **Mobile Validation**: When device verification is required, execute `python .agents/harness.py device install-start` or, if developer explicitly requests skip, record honest skip via `python .agents/harness.py device skip-validation --task-id <id> --proof-reference "<phrase>"`.
- **Sensitive Approval**: If sensitive surfaces were touched, record explicit approval via `workflow.py approve-sensitive`.
- **Final Verify**: Run read-only delivery verification via `python .agents/harness.py verify --task-id <id>`.
- **Optional Approved Contract**: Follow `task status --next` after installation. For an approved complete executable walkthrough, present its steps with manual PASS/FAIL and Run Automatically. Execute only the developer's choice; complete automatic PASS replaces manual repetition and binds criteria automatically. ENV may offer manual fallback; FAIL requires diagnosis. Partial journeys retain human sign-off. Inspect `task coverage` for remaining required evidence. Sensitive approval remains independent.
- **Complete**: Seal task to `READY_FOR_DELIVERY` via `python .agents/harness.py task complete --repo . --task-id <id>`.

## 4. SHIP
- **Developer Commit**: Developer creates git commit (never auto-committed by agent; working tree remains unstaged).
- **Reconcile Delivery**: Finalize task delivery state via `python .agents/harness.py task reconcile-delivery --repo . --task-id <id>`.
- **Zoho Delivery Sync**: If plan has approved `zoho_link`, sync delivery report via `python .agents/harness.py zoho delivery-sync --task-id <id>`.
