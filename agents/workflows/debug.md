---
description: Hypothesis-driven debug with forensics, 5-leaf review, and physical-device validation.
---

# Debug a Rashaqa Android bug

Follow `.agents/rules/harness-rules.md` and `systematic-debugging`. Do not commit.

## Steps

1. Hypotheses first. Crashes/ANRs: `qa-diagnostics-agent` + `python .agents/scripts/logcat_doctor.py`.
2. Fix the producer. No empty catch, no dummy business fallbacks.
3. `review_package.py` then all 5 review leaves in one invoke. Re-review until `*_PASS`.
4. `fast_kt_lint.py` → targeted tests → `run_gradle_task.py :app:assembleDebug`.
5. Install + launch on a physical device. Structured phases. Walkthrough only after Pass.
