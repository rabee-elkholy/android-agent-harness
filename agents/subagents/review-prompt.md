# Round-1 reviewer user prompt (policy-selected reviewers)

Copy the prompt into each subagent entry for the reviewers selected by the current run policy. Do not invoke `code-review-guard-agent`. Do not narrate the intended fix.

```
HARNESS_REVIEW_PACKAGE=[PATH from python .agents/scripts/review_package.py]
HARNESS_PACKAGE_SHA256_12=[12-hex digest printed by review_package.py]
Listed paths:
- [path]
- [path]

Examine the review package and its embedded ARCHITECTURAL GRAPH & BLAST RADIUS TOPOLOGY. Read identified callers/contracts directly with view_file when a finding depends on them.

High-signal only: BLOCKER / MAJOR. Drop MINOR/NIT. Cite a project rule when the finding is architectural.

Output exactly one of:
- BUG_PASS / CONVENTION_PASS / SECURITY_PASS / PERF_PASS / REGRESSION_PASS / TEST_PASS (your role token)
- or Findings with file:line, evidence, and a fix snippet.

End your reply with the evidence footer:
`EVIDENCE pkg=<HARNESS_PACKAGE_SHA256_12> cites=<n>` where <n> is your citation count
(cites=0 for a clean PASS). A reply without a valid matching footer does not clear
the delivery barrier.
```
