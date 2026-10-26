# ADR-018: Integration corrections preserve completed phases

## Context

An Antigravity task repeatedly reviewed phase p1 after a badge removal, a late
AUTH reconciliation and a final-review caption correction. Updating plan prose
with revise invalidated completed checkpoints and recalled phase specialists
before the already required final integration review.

## Decision

In-scope findings use resume, correction and fresh final verification under the
same approval. When all semantic phases are complete, checkpoints describe the
historical execution of those phases. Validate every checkpoint and its required
independent dispatch, package, ledger and results before final preparation; do
not compare their historical bytes with integration corrections. Final gates,
material-drift classification, complete initial integration review and the
central policy's affected-specialist follow-ups cover the current frozen bytes.
No phase proof becomes current delivery evidence.

A genuine revision with unchanged semantic phases may retain this validated
history after all phases completed. Changed phase definitions or incomplete
phase sequences retain conservative transition/freshness checks. Missing or
corrupt proof never authorizes advancement. Review budgets, round counters,
finding owners and original result identities are not reset.

Use task plan-note to append bounded, source-referenced, plan-bound clarifications
outside the approval payload. The generated plan document labels notes as having
no additional authority; newly published review packages include a frozen copy
for reviewers assessing plan completeness. Later notes do not rewrite existing
packages. Notes never grant files, alter requirements, accept
developer edits, waive tests or certify PASS. Narrative-only revision of an
approved plan requires an explicit material-change-reason and normal reapproval.
This check cannot determine the meaning of prose; client instructions prohibit
inventing an expansion merely to bypass it.

## Consequences

Clients receive both deterministic routing and always-loaded instructions.
Existing completed tasks need no state migration. The old final checkpoint is
retained byte-for-byte; final deterministic, build/device and independent review
evidence remains snapshot-bound. Unfinished/intermediate reviews still fail on
source drift. Host capability boundaries and Zoho authorization are unchanged.
Native hooks recognize the administrative plan-note command, including during
blocked or verifying work; its handler requires a valid approved live task.
