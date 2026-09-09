---
description: Run only preflight checks selected by the active immutable policy.
---

# Adaptive preflight

After `workflow.py prepare-verification`, run `python .agents/scripts/preflight_check.py`. It always checks plan authority and harness safety; localization, Room, and fast Kotlin checks run only when selected by policy. The command writes snapshot-bound evidence and never edits project files.

Do not run assemble or device phases unless their policy gates are present.
