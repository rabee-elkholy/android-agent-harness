---
description: Derive test cases from a diff and execute them on device as a Senior QA tester.
---

# Senior-QA E2E Testing

Follow `.agents/rules/harness-rules.md`. This is the test-case-aware device
verification path (use `run_e2e_smoke.py` only as the quick fallback).

## 1. Derive test cases from the diff

For each plan phase (or bug fix / refactor), before executing on device:

1. Inspect the phase diff with `git diff`, the implementation plan, and (for
   bugs) the tracker description.
2. Run `python .agents/scripts/impact_analyzer.py --json` for affected screens.
3. Generate a grounded scaffold:
   `python .agents/scripts/run_e2e_qa.py --generate-cases --task <task> --output .agents/e2e_cases/<task>/<phase>.yaml`
4. Dispatch `qa-e2e-planner-agent` with the diff, impact report, and scaffold to
   author **positive / negative / edge** cases. Write the returned YAML to
   `.agents/e2e_cases/<task>/<phase>.yaml`.

Cases must cover: entry-to-exit happy path, at least one negative path, and one
edge condition. Every assertion uses `assertVisible` / `assertNotVisible` /
`assertText` / `assertEnabled` / `assertClickable` with a concrete target.

## 2. Validate offline

`python .agents/scripts/run_e2e_qa.py --cases <path> --lint`

Fix any validation errors before touching a device.

## 3. Execute on device / emulator

1. `python .agents/scripts/run_gradle_task.py :app:assembleDebug`
2. `python .agents/scripts/run_device.py install-start`
3. `python .agents/scripts/run_e2e_qa.py --cases <path> --task <task> --json`

On any failure, read the per-case `reason` + `classification` and the evidence
(screenshot / hierarchy) in `.agents/state/e2e/`, or dispatch
`qa-diagnostics-agent` for crash forensics.

## 4. Report

- Output the **Phase Milestone Card** with the per-case PASS/FAIL table.
- The JSON report lives in `.agents/state/e2e/reports/<task>/`.
- Never deliver with a failing case. Fix the producer and re-run.
