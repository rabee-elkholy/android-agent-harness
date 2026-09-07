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
   - Shift-left pre-audit against reviewer criteria (zero FQCNs, Compose Previews, RTL/strings parity) to achieve clean 1st-round PASS.
   - `python .agents/scripts/review_package.py`.
   - Dispatch review leaves in EXACTLY ONE parallel `invoke_subagent` call: 5 standard leaves, or 6 leaves (+ `test-quality-reviewer-agent` via Smart Test Promotion if tests changed).
   - Quorum patience: silent wait (`""`), no premature completion declarations, and emit a Review Round Summary Card upon full completion.
6. **Assemble & Verify**: `run_gradle_task.py <unit-test-task>` → `fast_kt_lint.py` → `run_gradle_task.py :app:assembleDebug` (same Shift-Left order as `harness-rules.md` Stage 1 step 0).
7. **Physical Device Validation**: Structured phases on physical device. Walkthrough only after Pass.
