---
description: Pull physical-device fatals and hand them to qa-diagnostics-agent.
---

# Triage Android Device Crash

Follow `.agents/rules/harness-rules.md`.

## Steps

1. Physical device via USB/Wi-Fi. `adb devices` — no emulators.
2. `python .agents/scripts/logcat_doctor.py` (optional `--device <serial>`).
3. If fatals or sensor issues: invoke `qa-diagnostics-agent`.
4. Report producer-level hypotheses. Do not guess a patch before the developer confirms symptoms.
