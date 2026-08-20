---
description: Static + optional device ANR audit. Not a substitute for the 5-leaf delivery gate.
---

# Performance & ANR Audit Workflow (`/perf-audit`)

Follow `.agents/rules/harness-rules.md`. Solo perf audit does not replace delivery review.

## Steps

1. `python .agents/scripts/perf_guard.py`
2. Optional: `python .agents/scripts/perf_guard.py --device <SERIAL>`
3. Optional: invoke only `perf-anr-guardian-agent` for a deeper read of named files.
4. If this audit is part of shipping a code change, still run the full 5-leaf gate.
5. Reference: `.agents/skills/android-harness/references/performance-anr-optimization.md`
