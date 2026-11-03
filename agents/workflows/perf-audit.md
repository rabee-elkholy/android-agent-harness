---
description: Static and optional device performance audit under the adaptive delivery policy.
---

# Performance & ANR Audit Workflow (`/perf-audit`)

Follow `.agents/rules/harness-rules.md`. Solo perf audit does not replace delivery review.

## Steps

1. `python .agents/scripts/perf_guard.py`
2. Optional: `python .agents/scripts/perf_guard.py --device <SERIAL>`
3. Optional: invoke `security-perf-reviewer-agent` for a deeper performance/ANR read of named files.
4. If this audit is part of a delivery, run the reviewers and gates selected by the immutable policy.
5. Reference: `.agents/skills/android-harness/references/performance-and-optimization.md`
