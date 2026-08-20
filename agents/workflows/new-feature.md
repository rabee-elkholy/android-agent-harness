---
description: Implement a new feature, then run the 5-leaf gate. Do not use the example-product scaffold.
---

# New feature

Follow `.agents/rules/harness-rules.md`. Do not commit.

`new_feature_scaffold.py` is **disabled**. It still holds `VIEWMODEL` / `SCREEN` strings for selftest only. Do not run it.

## Steps

1. If the developer gave a Zoho id: fetch it (read-only). Explain. Ask whether to start the plan. Playbook: `.agents/workflows/zoho-sprints.md`.
2. If name/scope/API is missing, `ask_question` in the developer's language.
3. Add the files in **this** app's real packages (whatever architecture setup recorded). Do not run the disabled scaffold.
4. Implement real behavior. UI guidance: `android-ui-expert-agent`.
5. `check_strings.py`, then the 5-leaf review, tests, assemble.
