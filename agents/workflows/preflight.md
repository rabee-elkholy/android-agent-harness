---
description: Hook selftest, string parity, Room migration gate, and fast Kotlin lint before assemble.
---

# Preflight Build Sanity Check

Follow `.agents/rules/harness-rules.md`.

## Steps

1. `python .agents/scripts/preflight_check.py` — includes a cached `_hook_selftest.py` run when harness files changed.
2. If it fails, stop. If it passes, targeted tests then `python .agents/scripts/run_gradle_task.py :app:assembleDebug` — only after the 5-leaf review when code changed.
