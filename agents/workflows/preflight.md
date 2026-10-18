---
description: Run only preflight checks selected by the active immutable policy.
---

# Adaptive preflight

When routed after `task prepare-verification`, run `python .agents/harness.py preflight`. `verify-steps` can already execute this step; follow its result instead of repeating it. Preflight checks plan authority and harness safety; localization, Room, and fast Kotlin checks run only when selected by policy. It writes snapshot-bound evidence and never edits project files.

Let every selected independent check finish. Ordinary failures and checker exceptions are collected into one final failure report, including failed subprocess output. Fix all reported issues together before rerunning. Stale engine/policy inputs allow independent diagnostics but block proof publication and return an environment failure. A failed preflight must never advance to tests or review.

Do not run assemble or device phases unless their policy gates are present.
