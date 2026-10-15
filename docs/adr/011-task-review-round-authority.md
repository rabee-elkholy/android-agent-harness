# ADR-011: Developer-approved task review round extensions

## Context

A task can spend its three default final-review rounds while fixing legitimate
findings. The router previously prepared and requested a fourth round that native
hooks refused. Increasing the call budget could not resolve this separate limit,
and the host incorrectly proposed editing installed engine code or skipping reviews.

## Decision

The developer may extend the task's final-round limit through the existing
`task review-budget --round-limit` command, using explicit approval provenance.
The maintainer approved this change on 2026-10-14. The default stays three;
extensions accept limits from three to 100, above already completed rounds.
Call spending remains independently bounded by the setup default or its explicit
task decision. Both limits can be approved together, without a second setup prompt.

Keep both dimensions in the same integrity-checked task decision and preserve
schema-1 call decisions. Serialize updates and retain prior records. Changing one
dimension retains the other; no counters, findings, policies or review evidence
are reset or rewritten. A revised plan cannot inherit an old plan's extension.

Preparation, router, native hooks, V1/V2 review recording and delivery verification
consume the same effective round limit. Exhaustion requests an explicit developer
decision; the approved extension resumes the same task and frozen run where fresh.
A completed final round with valid PASS evidence still proceeds to delivery.

## Consequences

There is a bounded human decision after the default retries, with a supported
continuation path. The extension grants spending authority only: it cannot waive
reviewers, accept findings, fabricate proof or bypass sensitive-surface policy.
The developer approval provenance is rule-enforced, not a cryptographic human signal.
This supersedes the unconditional three-round ceiling described in ADR-006.

Final dispatches consume their call spending when recorded, including interrupted
executions. Task-local per-run role charges prevent double charging at finalization,
resume, revision or host transfer. Legacy outstanding dispatches are reconciled
from durable ledgers/receipts without rewriting review evidence. Revising a plan
retains consumed calls/rounds; it does not inherit a prior plan hash's limit grant.
