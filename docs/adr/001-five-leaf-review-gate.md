# ADR-001: Five-Leaf Review Gate as the only delivery barrier

## Context

Before the harness, agents self-approved code and assembled unverified diffs.
A single "code review guard" agent proved insufficient, so it was retired and
replaced by five specialized reviewers (bug, convention, security, perf/ANR,
regression) dispatched in exactly one `invoke_subagent` call against one
hashed review package (`pre_tool_safety.py` `REVIEW_FIVE`; `harness-rules.md`
section 2). v0.9.0 added evidence-backed verdicts: a leaf's PASS token only
counts when its reply carries `EVIDENCE pkg=<sha256_12> cites=<n>` matching
the dispatched package (`HARNESS_EVIDENCE_MODE=strict` is the default;
`legacy` mode is a migration window).

## Decision

The five leaves are the ONLY delivery barrier. The barrier is machine-checked
from the conversation transcript (verdict tokens plus evidence footers) and
expires after a TTL (`HARNESS_BARRIER_TTL`, default 21600s). Assemble, test,
and device-install commands are denied while a review round is pending, when
the working tree changed without any review round, or when evidence footers
are missing or cite the wrong package. Every completed round is recorded as a
machine-verifiable artifact (`state/verdicts/verdict-<pkg12>.json`) that
`android-harness verify` re-checks against the working tree.

## Consequences

Deterministic, forge-resistant gating with runaway-loop caps. Cost: builds
fail closed if the transcript cannot be read (with remediation text), and
verdict parsing remains text-based until reviewer replies become structured
(a listed future item).
