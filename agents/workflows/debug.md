---
description: Hypothesis-driven debug with forensics, 5-leaf review, and physical-device validation.
---

# Debug an Android bug

Follow `.agents/rules/harness-rules.md` and `systematic-debugging`. Do not commit.

## Steps

1. If the developer gave a Zoho id: fetch it (read-only). Explain in chat, then hypotheses. Playbook: `.agents/workflows/zoho-sprints.md`.
2. Hypotheses first. Crashes/ANRs: `qa-diagnostics-agent` + `python .agents/scripts/logcat_doctor.py`.
3. Fix the producer. No empty catch, no dummy business fallbacks.
4. `review_package.py` then all 5 review leaves in one invoke. Re-review until `*_PASS`.
5. `fast_kt_lint.py` → targeted tests → `run_gradle_task.py :app:assembleDebug`.
6. Install + launch on a physical device. Structured phases. Walkthrough only after Pass.
