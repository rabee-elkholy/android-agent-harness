# ADR-016: Incremental developer edits and same-goal support files

## Context

The maintainer approved flexible concurrent edits on 2026-10-21. In a reported
Antigravity task, two XML edits outside `expected_files` forced `revise`, which
discarded the active run and recalled six reviewers despite earlier PASS results.
An extra filename is not sufficient evidence of new behavioral scope.

## Decision

Add `task change-decision` with a read-only preview and snapshot-bound apply:

- `extend-scope` reserves exact support files for the approved outcome. The agent
  records a concrete same-goal reason with `--source approved-plan`; no repeat
  plan approval is needed. This is not authority for unrelated feature work.
- `review-edits` records intentional personal edits at exact content identities
  and resumes the existing task for affected review.
- `accept-edits` records explicit developer consent to omit additional AI review
  of the exact delta since the referenced reviewed run. It is not reviewer PASS.

The last two modes require a developer source and nonempty proof reference. Show
the concrete diff and consequences before asking. Do not infer authorship from
file timestamps, assume unexpected changes are developer edits, or infer consent
from silence. There is no new lifecycle state and no manual shell work for users.

Receipts live in the task plan outside its immutable approved payload, with
integrity hashes, task/plan/execution identity, repository, source run, full
preview snapshot and exact before/after file identities. Original approvals,
baselines, runs, review reports and spending remain intact. Apply checks the
preview again and publishes the receipt and resume in one atomic plan write.
Repeated apply is idempotent. A different plan/execution cannot reuse receipts.

Both final policy preparation and verification use the same delta computation.
Accepted paths are excluded only from additional delta review routing. Initial
reviews, unresolved finding owners and new specialist responsibilities remain.
Later bytes, modes, deletion/restoration, repository or external-input changes
cannot inherit acceptance. Unknown review comparisons remain conservative.
Tests, builds, artifacts, install and device checks are not waived or relabeled.

Personal edit receipts permit verification of those bytes without granting the
agent write authority. All receipt files participate in sibling-task isolation.
Whole-tree builds still include personal edits. Material surfaces/modules and
mandatory skills remain checked; scope receipts do not suppress their drift.
Protected engine paths, traversal, broad scopes and conflicting tasks are refused.

After final verification has begun, decisions can retain the completed final
phase checkpoint as historical proof when the delta since that final run is
entirely covered by the recorded paths/identities. The checkpoint and independent
review records must remain intact. Fresh final integration verifies the delta.
This never advances an intermediate phase on stale proof or skips the first
final freeze. Unexplained edits still require a fresh checkpoint.

## Compatibility

Existing tasks without receipts retain their approval and evidence contracts.
File-only drift offers this path instead of demanding revision. Genuine scope
expansion continues through `revise`. Already-invalidated runs are not fabricated
or resurrected; this change prevents unnecessary revision going forward.
Host adapters use the same public command and report conversation authority as
rule-enforced, without pretending to have native proof on unsupported hosts.
