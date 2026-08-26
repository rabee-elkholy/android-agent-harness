# ADR-006: Reviewer Conflict Adjudication & Structured Findings

## Context

The five specialized reviewers (bug, convention, security, perf/ANR, regression) operate concurrently against a single review package. In non-trivial Android changes, reviewers may reach conflicting conclusions (for instance, Performance Guardian recommending memory caching while Bug Reviewer flags cache invalidation edge cases, or Security Reviewer identifying strict permission boundaries).

Prior to this ADR, review transcript evaluation was binary (PASS token vs missing/denied), lacking structured severity semantics or a deterministic escalation framework when leaves disagree. Agents faced potential infinite review loops or untracked manual overrides.

## Decision

Establish a deterministic two-tier conflict adjudication model backed by structured findings:

1. **Severity Classification**:
   - `HARD_BLOCKER`: Security vulnerabilities, plaintext PII/token exposure, unhandled crash vectors on primary user flows, and compile/build breakage. A single `HARD_BLOCKER` from any reviewer results in an immediate `FAIL` verdict. Agents cannot override a `HARD_BLOCKER` without modifying the code and triggering a new review round.
   - `SOFT_FINDING`: Code convention deviations, minor performance optimizations, or non-critical refactoring suggestions.

2. **Adjudication Hierarchy**:
   - Security and Safety take precedence over Performance and Conventions.
   - If reviewers disagree on a `SOFT_FINDING`, the human authority may adjudicate the conflict by supplying an explicit override reason recorded in `state/verdicts/verdict-<pkg12>.json` under the `adjudications` ledger.

3. **Structured Findings Schema**:
   - Reviewers emit or serialize findings containing exact `file`, `line`, `severity` (`HARD_BLOCKER` | `SOFT_FINDING`), `category`, and `suggested_fix`.

## Consequences

- Prevents deadlock and loop regression while maintaining absolute security guarantees.
- Provides machine-readable finding records for CI dashboards and audit logs.
- Preserves the principle that human developers hold ultimate authority for non-security trade-offs while safety boundaries remain non-negotiable.
