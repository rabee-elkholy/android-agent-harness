# ADR-007: Antigravity-First Hardening and Review Protocol V2

- **Status**: Accepted
- **Date**: 2026-09-22

## Context

Previous iterations treated Google Antigravity and generic Gemini CLI interchangeably under a merged host identity, while attempting to balance cross-host model routing, multi-tier model escalation (`NORMAL`, `DEEP`, `MAX`), and unstructured text-based verdict tokens (`*_PASS + EVIDENCE`).

In production practice on Google Antigravity:
1. Antigravity subagent dispatch achieves same-model inheritance by omission (passing explicit `model="inherit"` or reasoning parameters when unsupported triggered syntax or safety errors).
2. Unstructured text tokens in reviewer outputs were fragile and vulnerable to hallucination or formatting divergence.
3. Mid-invocation host launch failures could leave reviewer ledgers in a pending state, causing deadlocks under zero-polling constraints.
4. Clean installation must provision dedicated Antigravity custom reviewer agent definitions (`.agents/agents/<reviewer>/agent.md`) so that routed reviewer subagents execute with specialist system prompts.

## Decision

1. **Google Antigravity as Primary Production Host**: Antigravity is the primary, authoritative development and verification host. Legacy host parity is a non-goal.
2. **Review Protocol V2**: All specialist reviewers adhere to Review Protocol V2, returning structured JSON blocks (`HARNESS_REVIEW_RESULT_V2`) containing explicit task, run, package digest, verdict (`PASS` / `FAIL`), and typed findings.
3. **Transcript-Backed Verification**: Review completion is ingested from trusted Antigravity conversation transcripts (`review complete`), cryptographically bound to the frozen delivery snapshot, change set, and review package SHA-256.
4. **Model Inheritance by Omission**: Reviewer subagent dispatch omits `model` and `reasoning` override keys unless a trusted native host control exists. Reviewers run on the same authoritative model as the parent.
5. **Parallel Autonomous Dispatch**: The active review policy calculates required reviewers dynamically; all routed reviewers are dispatched concurrently in one tool call. No intermediate developer approval is required between plan approval and verification.
6. **Same-Conversation Protocol Retry**: If a reviewer returns malformed JSON or legacy text on initial completion, the router issues an actionable `send_message` protocol retry to the same subagent conversation ID without initiating a new dispatch or consuming additional model calls.
7. **PostToolUse Reconciliation**: A native `PostToolUse` hook intercepts subagent launch failures and marks affected reviewers as `ENV_BLOCKED`, ensuring the router returns an actionable blocker rather than stalling indefinitely.
8. **Hard Mutation Interception**: `.agents/hooks.json` enforces mutation boundaries across file edits (`multi_replace_file_content`, `replace_file_content`, `write_to_file`) and tool safety checks.

## Consequences

- Specialist reviews execute with high fidelity, zero hallucinated PASS tokens, and cryptographic snapshot binding.
- Antigravity onboarding is clean, deterministic, and free from model-routing drift.
- Downstream verification gates and routers operate on structured, machine-verified evidence artifacts.
