# ADR-010: Temporarily reserve execution for active-task updates

Status: Accepted by the maintainer on 2026-10-13.

## Context

Compatible updates previously refused every live task. A task blocked by a harness
defect could not receive the fix without cancellation. The maintainer explicitly
approved preserving the active task and temporarily stopping execution for update.

## Decision

Keep ordinary updates idle-only. Add `--preserve-active-task <task-id>` with
`--source-stopped` for explicitly authorized updates of approved active tasks.
Validate task/approval identity and accepted repository lineage. Reject concurrent
state, execution and phase-review writers. Hold a lifecycle reservation outside
the engine directory while it is replaced. Native mutation hooks and the launcher
honor that reservation; rule-only hosts require the executor to be stopped.

Preserve all task state and proof byte-for-byte, excluding transient lock records.
Do not change setup answers, refresh context, consume approval, cancel the task,
reroute reviewers, or rebind existing evidence. Verify preservation before declaring
completion; use the existing transaction backup and recovery journal on failure.
Release the reservation after success or rollback. An interrupted transaction
blocks task mutations until recovery.

## Consequences

No new task status or approval flow is introduced. Updating the engine does not
upgrade reviewer trust, refresh stale proof, grant application scope, or move Git
state. Keeping an executor stopped remains a required human/host assertion; the
reservation is not an operating-system lock over unrelated editors.
