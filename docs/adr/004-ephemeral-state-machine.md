# ADR-004: Ephemeral per-conversation review state machine

## Context

Review rounds must be tied to exact code snapshots and to the conversation
that dispatched them, without a database or daemon, across processes and
tools on any OS.

## Decision

`_hook_state.py` keeps a JSON state file (under `agents/state/`, gitignored,
guarded by a cross-platform `state_lock()` with stale-lock recovery) keyed by
conversation id. It records: package hashes of dispatched rounds,
`pending_reviews`, `pending_since`, per-class invocation caps, poll counters,
and a `re_dispatch_allowed` unlock set when subagent templates are redefined
after a registration failure.

- Entry: a valid five-leaf dispatch whose package path resolves inside the
  repo (or the sanctioned temp dir) and whose content was not already
  reviewed.
- Exit: evidence-verified verdicts clear the barrier, or the round expires
  after `HARNESS_BARRIER_TTL` (default 21600s).
- Expiry: whole records are pruned after 7 days of disuse.

## Consequences

Deterministic, lock-safe, cross-process state with zero dependencies. Cost:
state is machine-local and ephemeral by design - long-term auditability is
the role of `audit_log.jsonl` (capped at 1000 sanitized records) and the
`verdicts/*.json` artifacts instead.
