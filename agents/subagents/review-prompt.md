# Round-1 reviewer user prompt (all 5 leaves)

Copy the same Prompt into every entry of a **single** `invoke_subagent` `Subagents` array. Do not invoke `code-review-guard-agent`. Do not narrate the intended fix.

```
HARNESS_REVIEW_PACKAGE=[PATH from python .agents/scripts/review_package.py]
HARNESS_PACKAGE_SHA256_12=[12-hex digest printed by review_package.py]
Listed paths:
- [path]
- [path]

Examine the review package. Read surrounding callers/contracts when a finding depends on them.

High-signal only: BLOCKER / MAJOR. Drop MINOR/NIT. Cite a project rule when the finding is architectural.

Output exactly one of:
- BUG_PASS / CONVENTION_PASS / SECURITY_PASS / PERF_PASS / REGRESSION_PASS (your leaf)
- or Findings with file:line, evidence, and a fix snippet.

End your reply with the evidence footer:
`EVIDENCE pkg=<HARNESS_PACKAGE_SHA256_12> cites=<n>` where <n> is your citation count
(cites=0 for a clean PASS). A reply without a valid matching footer does not clear
the delivery barrier.
```
