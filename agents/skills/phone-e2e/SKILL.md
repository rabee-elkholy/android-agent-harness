---
name: phone-e2e
description: Live agent-driven phone E2E testing session over ADB on an installed Android build. Use when running interactive phone E2E scenarios (`e2e start`) before device sign-off.
version: 1.0.0
kernel-major: 1
---

# Phone E2E Verification Skill

Follow `.agents/workflows/phone-e2e.md` and `.agents/rules/harness-rules.md`. Drive the already-installed verified build scenario by scenario (`e2e start`, observe hierarchy, tap/type/swipe, `e2e need-developer` + `ask_question` for human steps, `e2e resume`), keeping final sign-off developer-owned.

## Maestro YAML Flows & Automatic LeakCanary Checks
- Probe Maestro flows via `python .agents/harness.py maestro capabilities --json`.
- When `.maestro/*.yaml` flows exist and the developer chooses Maestro verification, run `python .agents/harness.py maestro run --flow <path.yaml> --task-id <id>` (blocks `clearState`/`uninstallApp` automatically unless developer-authorized).
- After a passing `e2e finish` session, offer to save it as a repeatable regression flow via `python .agents/harness.py maestro export-e2e --task-id <id>`. Post-session `LeakCanary` checks run automatically when configured.
