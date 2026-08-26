---
description: Hypothesis-driven debug with forensics, failing test reproduction (TDD), 5-leaf review with silent wait, and physical-device validation.
---

# Debug an Android bug

Follow `.agents/rules/harness-rules.md` and `systematic-debugging`. Do not commit.

## Steps

1. If the developer gave a Zoho id: fetch it (read-only). Explain in chat, then hypotheses. Playbook: `.agents/workflows/zoho-sprints.md`.
2. **Hypotheses & Forensics**: List 2–3 explicit root-cause hypotheses. For crashes/ANRs: `qa-diagnostics-agent` + `python .agents/scripts/logcat_doctor.py`.
3. **Reproduce via Failing Test (TDD)**: Whenever feasible, write a targeted unit test (`*Test.kt`) reproducing the bug condition and prove it fails (Red).
4. **Fix Producer**: Fix the root cause at the producer level. No empty catch, no dummy fallbacks. Re-run unit test to verify Green.
5. **Quality Review Gates**:
   - `python .agents/scripts/review_package.py`.
   - **Stage 0.5**: If tests were added/modified, audit with `test-quality-reviewer-agent` first until `TEST_PASS`.
   - **Stage 1**: Dispatch all 5 review leaves in one invoke with **Silent Review Wait**.
6. **Assemble & Verify**: `fast_kt_lint.py` → targeted tests → `run_gradle_task.py :app:assembleDebug`.
7. **Physical Device Validation**: Structured phases on physical device. Walkthrough only after Pass.
