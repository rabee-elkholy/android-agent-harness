# Round-1 reviewer user prompt (all 5 leaves)

Copy the same Prompt into every entry of a **single** `invoke_subagent` `Subagents` array. Do not invoke `code-review-guard-agent`. Do not narrate the intended fix.

```
RASHAQA_REVIEW_PACKAGE=[PATH from python .agents/scripts/review_package.py]
Listed paths:
- [path]
- [path]

Examine the review package. Read surrounding callers/contracts when a finding depends on them.

High-signal only: BLOCKER / MAJOR. Drop MINOR/NIT. Cite a project rule when the finding is architectural.

Output exactly one of:
- BUG_PASS / CONVENTION_PASS / SECURITY_PASS / PERF_PASS / REGRESSION_PASS (your leaf)
- or Findings with file:line, evidence, and a fix snippet.
```
