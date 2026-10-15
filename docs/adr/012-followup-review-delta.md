# ADR-012: Full initial review and strongly related follow-up reviewers

## Context

The maintainer requested on 2026-10-15 that the first final integration review
remain complete while later corrections recall only strongly related reviewers.
The existing file-level fix detector reread each file's entire task-start diff.
A caption edit in a newly migrated billing screen therefore inherited the
original billing, architecture and test surfaces and repeatedly called the full
roster. Repeated manifests and full-plan status output added avoidable latency.

## Decision

Keep the central policy as the sole reviewer authority. The first final review
still selects its complete roster. For a later round, compare the frozen reviewed
source with the newly frozen source, including additions, deletions and modes.
Classify changed lines with bounded enclosing structural context; retain critical
surface/dependency checks, rather than routing from a filename or line count alone.

In follow-up scope, route sensitive changes to Bug, Security and Regression;
route Coroutines/Device/Native changes to Performance where applicable, and
public/build/manifest contracts to Convention where applicable. Original
architectural planning depth alone does not recall Convention or Specification.
Unresolved finding owners remain required; production finding corrections retain
Regression. A test-only correction does not recall unrelated production specialists.
Newly uncovered obligations still require review. A successful round clears stale
blocked-reviewer bookkeeping.

Unaffected independent PASS results remain bound to their original evidence,
snapshot, package and execution through existing validated carries. The final
verifier recomputes the same selection. Follow-up packages show the new patch
and links to prior integration context, without changing full delivery identity.

An optional repository-local source comparison cache stores only bounded text
that has no detected secret-shaped values, and never writes Git objects/history.
Its bytes must reproduce the frozen manifest's Git blob identity (raw or normalized
LF); file inventory is checked against the snapshot hash. Binary, filtered,
secret-bearing, missing, unsupported or invalid inputs fall back conservatively;
they cannot authorize a narrower PASS. Cache data is never proof of review.

Batch read-only Git hash-object calls preserve attributes/filters and symlink
semantics, with the original single-file fallback. Freshness checks reuse a live
manifest within that one read operation only; no cross-invocation TTL or mtime
cache weakens change detection. Opt-in `task status --next --brief --json` retains
the exact next action while omitting repeated plan and duplicate action fields.

## Consequences

Small corrections do not automatically cost another full integration roster.
Affected critical code still gets its specialist; unknown coverage cannot silently
be carried. The global spending/round limits, initial approval, sensitive sign-off,
phase policy, immutable evidence and exact-head release validation remain intact.
