# ADR-021: Bounded Android inspection and scoped Antigravity guidance

Status: accepted for implementation in the current maintenance change.

## Context

The existing harness already owns task approval, Gradle execution, preview locking,
reviewer proof and delivery gates. Replacing these with speculative host hook fields
would weaken portability. Supported Android CLI inspection can reduce broad searches
and shorten feedback loops without introducing another correctness authority.

## Decision

1. Keep existing hooks and validate managed Antigravity rule frontmatter in doctor.
   The kernel uses `always_on`; Compose, KMP and Gradle guides use quoted comma-separated
   `glob` patterns. Core obligations and central skill routing remain unconditional.
2. Expose `android-inspect` for declaration, usages, file analysis, IDE status and
   official docs search/fetch. Bind Studio queries to the repository, constrain
   inputs, probe the actual CLI, bound output/time and report unavailable capabilities.
   Inspection is read-only and needs no mutation plan. It cannot grant discovery scope.
3. Extend the existing preview adapter with dependency discovery and local substring
   filtering. Preserve approval, build locking, freshness and non-evidence semantics.
   Only advertised `--all` is used; locale/theme coverage comes from actual previews.
4. Bound Gradle live output and final error summaries in the runner itself. Preserve
   full logs, process exit status, classification and artifact/evidence validation.
   Keep 20 logs with collision-resistant names. Heartbeats remain active.
5. Keep all runtime dependencies in the Python standard library. Missing optional
   tools leave native discovery, tests and delivery paths available on every host.

## Rejected assumptions and limits

Antigravity PostToolUse does not provide a documented `overwriteResult` contract;
log compaction belongs in the runner. `studio check` is not a lint gate. Successful
`analyze-file` transport is not clean source proof. Preview compilation can execute
project build logic and therefore is not a read-only action. No model aliases,
plugin manifests, remote devices, dependency upgrades or claimed speedup percentages
are introduced by this change.

Glob rules are host convenience, not guaranteed policy enforcement. Static doctor
validation cannot establish live Antigravity behavior. Contract tests use controlled
CLI responses and process tests; real Studio/Antigravity smoke tests and exact-commit
cross-platform CI remain necessary before publication.

References:
- https://antigravity.google/docs/hooks
- https://antigravity.google/docs/rules
- https://developer.android.com/tools/agents/android-cli
