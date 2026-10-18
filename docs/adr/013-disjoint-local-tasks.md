# ADR-013: Three disjoint local tasks in one worktree

Status: Accepted by the maintainer in Antigravity conversation
`2ce12edc-f32c-4d57-b7a5-66a9cb7f286c`, with the three-task limit confirmed
in the continuation on 2026-10-18.

The former one-live-task rule forced developers to commit or create worktrees
even for unrelated local changes. Task-local baselines already isolate dirty
changes, but task admission, focus, lineage and ready reconciliation assumed
only one live task.

Allow at most three live tasks with explicit disjoint file ownership. Pending,
approved, implementing, verifying, blocked and ready tasks occupy slots. File
reservations are checked on draft, revision, approval, switching and mutation;
admission and scope changes serialize through the existing state lock. No new
lifecycle status or approval gate is introduced.

The active pointer selects one task for commands and hooks without a task ID.
An absent pointer with several live tasks requires explicit selection. Switching
keeps approvals, review budgets, status and run identities unchanged.

Sibling changes are excluded from task review deltas. A sibling commit may
advance lineage only when every changed path, blob and mode matches a bound
ready or delivered sibling manifest. Post-ready reconciliation can tolerate
proven sibling-only changes while still requiring the current task's files to
be committed and verified content to match. Unrelated changes fail closed.

Builds, tests, assembly and device artifacts remain bound to the complete
working tree. A sibling edit during frozen verification makes the run stale.
Separate developer-created worktrees remain the solution for overlapping file
ownership and independent builds. Git mutations and tracker writes remain
developer-owned; Zoho writes still require `update zoho`.

Old single-task plans keep their hashes and baseline semantics. Plans without
explicit file ownership cannot participate in shared-worktree execution.
Updates cannot reserve one task while leaving other live executors unreserved.

The maintainer additionally requested easy conflict choices and plan merging on
2026-10-18. Conflict results carry simple structured options, affected tasks/files,
a recommendation, and a developer-owned next action. Nothing is auto-cancelled.

Plan merging is deliberately limited to two or three pending plans with no prior
approval, execution or review spending, including their archived revisions. A
read-only preview uses the normal planner and central policy. Applying requires
an explicit developer choice bound to that preview, creates a new pending task,
and cancels sources with their original plan history and merge provenance intact.
Combined semantic phases retain source order; conflicting single-valued contracts
require a reviewed consolidation instead of silently selecting one source.

The new plan has no inherited approval or execution evidence and requires one
fresh approval. Application files, Git and tracker state are unaffected. Source
inputs are checked before publication to avoid hiding pre-approval edits in a new
baseline. A durable publication journal blocks scope admission and project writes
until an interrupted merge rolls forward. There is no new task lifecycle status.
