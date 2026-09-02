---
description: Derive Maestro test cases from a diff and execute them on device as a Senior QA tester.
---

# Senior-QA Maestro E2E Testing

Follow `.agents/rules/harness-rules.md`. This is the test-case-aware device
verification path powered by **Maestro** (use `run_e2e_smoke.py` only as the quick fallback).

> **Strict Runner Invariant**: ALWAYS execute E2E testing via `python .agents/scripts/run_e2e_qa.py --cases ...` (or `run_e2e_smoke.py`). NEVER invoke raw `maestro` commands directly in shell, NEVER author custom scratch python scripts (`scratch/test_*.py`) to simulate ADB interactions, and NEVER hardcode device serials (`SERIAL = '...'`).

## 1. Confirm with the developer (Gate 0)

Before creating or planning any E2E test cases:
1. Ask the developer via `ask_question` (in the active conversation language):
   *"Start E2E round?"* with options **`Start E2E`** / **`Skip E2E`**, then wait for the choice.
2. If **`Skip E2E`**: STOP immediately — do NOT author test cases or invoke `qa-e2e-planner-agent`. Mark device verification as `skipped by developer`, output the Phase Milestone Card, and proceed.
3. If **`Start E2E`**: Proceed to Step 2 below to plan and author test cases.

## 2. Derive test cases from the diff (After developer approval)

For each plan phase (or bug fix / refactor), after the developer approves E2E:

1. Inspect the phase diff with `git diff`, the implementation plan, and (for
   bugs) the tracker description.
2. Run `python .agents/scripts/impact_analyzer.py --json` for affected screens.
3. Generate a grounded multi-flow scaffold:
   `python .agents/scripts/run_e2e_qa.py --generate-cases --task <task> --output .agents/e2e_cases/<task>/`
4. Dispatch `qa-e2e-planner-agent` with the diff, impact report, and scaffold directory to
   author **positive / negative / edge** Maestro YAML flows. Write the returned YAML files to:
   - `.agents/e2e_cases/<task>/TC01_positive_flow.yaml`
   - `.agents/e2e_cases/<task>/TC02_negative_flow.yaml`
   - `.agents/e2e_cases/<task>/TC03_edge_flow.yaml`

Cases must cover: entry-to-exit happy path, at least one negative path, and one
edge condition. Assertions use native Maestro syntax (`assertVisible`, `assertNotVisible`, `assertTrue`).

## 3. Validate offline

`python .agents/scripts/run_e2e_qa.py --cases .agents/e2e_cases/<task>/ --lint`

Fix any validation errors before touching a device.

## 4. Execute on device / emulator via Maestro

1. `python .agents/scripts/run_gradle_task.py :app:assembleDebug`
2. `python .agents/scripts/run_device.py install-start`
3. `python .agents/scripts/run_e2e_qa.py --cases .agents/e2e_cases/<task>/ --task <task> --json`

On any failure, read the per-case `reason` and failure diagnostics (screenshot and crash logcat) in `.agents/state/e2e/reports/<task>/`, or dispatch `qa-diagnostics-agent` for crash forensics.

## 5. Report

- Output the **Phase Milestone Card** with the per-case PASS/FAIL table.
- The JSON report lives in `.agents/state/e2e/reports/<task>/summary.json`.
- Never deliver with a failing case. Fix the producer and re-run.
