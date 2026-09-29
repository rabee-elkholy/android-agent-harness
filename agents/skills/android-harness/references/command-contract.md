# Android Agent Harness — Public Command Contract

> **Core Invariant**: During normal Android application tasks, installed harness engine source under `.agents/scripts/**` is an implementation detail. Do not inspect or recursively read harness Python implementation before executing a documented harness command. Use this documented public command contract and its output directly.

---

## 1. Discovery & Project Graph

### Purpose
Resolve project topology, feature boundaries, callers, callees, UI screens, ViewModel bindings, and architecture contracts before touching code.

### Command
```bash
# Public façade (preferred)
python .agents/harness.py graph --feature <feature_name> --json
python .agents/harness.py graph --find <SymbolName> --json
python .agents/harness.py task-context --file <path> --json   # or --symbol <name>

# Engine scripts
python .agents/scripts/project_graph.py --feature <feature_name>
# or
python .agents/scripts/project_graph.py --find <SymbolName>
```

### Inputs
- `--feature <feature_name>`: Name or path token of the feature slice.
- `--find <SymbolName>`: Specific Kotlin class, interface, or symbol to locate. A missing symbol prints the closest names; query one of them.
- `task-context --file <path>`: bounded context for one exact target file. It records a discovery receipt that `draft` binds to the plan; the receipt and the saved graph always carry the same fingerprint.

### Expected Output
- Human-readable slice and call hierarchy (callers, callees, UI layer, ViewModel, Data layer).
- Architectural anchors and associated files.
- Exit code: `0` on success.

> **Instruction**: Do not inspect `project_graph.py` or its internal helpers before execution. Run the command and inspect the discovered application source files.

---

## 2. Change Classification & Review Policy

### Purpose
Classify affected application surfaces, assess change risk, and determine the exact deterministic gates and AI specialist reviewers required.

### Commands
```bash
python .agents/scripts/change_classifier.py --repo . --json
python .agents/scripts/review_policy.py --repo . --json
```

### Expected Output
- JSON payload containing:
  - `surfaces`: List of affected surfaces (e.g. `COMPOSE_UI`, `ROOM_SCHEMA`, `BUSINESS_LOGIC`).
  - `severity`: `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`.
  - `reviewers`: List of specialist reviewer roles.
  - `gates`: List of mandatory deterministic verification gates.
- Exit code: `0` on success.
- `UNKNOWN` surfaces block verification until the developer decides: name the unclassifiable file explicitly in `--expected-files`, and approving that plan resolves it (`unknown_resolution: APPROVED_PLAN_FILES`, reviewed at T2 or higher, never T0). An UNKNOWN file outside the approved plan stays blocked.

> **Instruction**: Do not inspect implementation source of the classifier or policy engine before execution.

---

## 3. Workflow Lifecycle Management

### Purpose
Record task lifecycle state deterministically from intake to final delivery:
`INTAKE` -> `DISCOVERY` -> `PLAN_DRAFTED` -> `AWAITING_DEVELOPER_APPROVAL` -> `IMPLEMENTING` -> `VERIFYING` -> `READY_FOR_DELIVERY` -> `DELIVERED`.

### Commands
```bash
# 1. Draft task plan
python .agents/scripts/workflow.py draft \
  --repo . \
  --task-id <id> \
  --outcome "<requested outcome>" \
  --kind <AUTO|BUG|FEATURE|REFACTOR> \
  --planning-depth <BOUNDED|ARCHITECTURAL> \
  --expected-surfaces "<comma-separated surfaces>" \
  --expected-modules "<comma-separated modules>" \
  --expected-files "<comma-separated expected files>" \
  --test-strategy "<test plan; default: Policy-selected relevant tests>" \
  --approach "<how the change is made: which classes/functions change and why>" \
  --device-strategy "<numbered phone checks, each with its expected result: 1. Open X -> Y shows; 2. ...>" \
  --risks "<comma-separated risks>" \
  --rollback "<rollback instructions>" \
  --external-write "<scope: zoho_sprints, mcp:<server>, mcp:<server>:high-impact>" \
  --zoho-item-id "<item_id>" \
  --zoho-item-type "<Bug|Task|Story>" \
  --zoho-sprint-id "<sprint_id>" \
  --architecture-intent <EXISTING_CHANGE|NEW_SCREEN|NEW_FEATURE|REFACTOR|MIGRATION> \
  --architecture-target-scope "<target scope when applicable>" \
  --architecture-target-family "<target family id when applicable>" \
  --phases "<phases json or file path when required>"

> `--planning-depth`: `BOUNDED` for normal scoped tasks (default); `ARCHITECTURAL` for explicit architecture migration or broad structural architectural work.
> `--external-write`: Append `--external-write zoho_sprints` for Zoho mutation, `mcp:<server>` for generic MCP write operations, or `mcp:<server>:high-impact` for sensitive MCP mutations (deploy, drop, delete).
> `--zoho-*`: Optional flags to bind the task to an existing Zoho Sprints item. When the developer wants the item's status or a comment updated, also pass `--external-write zoho_sprints` (draft prints `ZOHO_WRITE_NOT_PLANNED=` when it is missing).
> Draft and revise print, in order: `PLAN_SUMMARY_BEGIN`..`PLAN_SUMMARY_END` (a list, one field per line), `PLAN_DOCUMENT_URI=` (the plan.md link), `APPROVAL_CALLOUTS:` (`/goal`, `/grill-me` reminders), `PRE_EXISTING_CHANGES=` (the developer's uncommitted files that predate the task), `ZOHO_WRITE_NOT_PLANNED=`, `PLAN_GAPS=` (revise first) and `APPROVAL_QUESTION:` (how to ask). Ask with `ask_question`: the plan.md link as a clickable Markdown link, a short explanation, then the summary lines as plain text, never in a code block.

# 1b. Revise the plan (new scope, missing fields, Zoho write); a revised plan needs approval again
python .agents/scripts/workflow.py revise --repo . --task-id <id> [any draft flag to change]

# 2. Record developer approval (atomically transitions directly to IMPLEMENTING)
python .agents/scripts/workflow.py approve --repo . --task-id <id> --source conversation --proof-reference "<developer_confirmation>" --enforcement-tier RULE_ENFORCED --plan-hash <Plan hash from PLAN_SUMMARY>

# Authoritative next action at any point (the router)
python .agents/harness.py task status --task-id <id> --next --json

# 2b. Linked Zoho start sync (when task has approved zoho_link)
python .agents/harness.py zoho start-sync --task-id <id>

# 3. (Legacy compatibility only) Begin implementation (idempotent when already IMPLEMENTING)
# python .agents/scripts/workflow.py begin --repo . --task-id <id>

# 4. Advance phase checkpoint (for multi-phase plans; autonomous execution without developer prompt)
python .agents/scripts/workflow.py checkpoint-phase --repo . --task-id <id>

# 5. Prepare verification (freezes review package and initializes run); the router names the host
python .agents/harness.py task prepare-verification --repo . --task-id <id> --host <antigravity|claude|...>
# engine form: python .agents/scripts/workflow.py prepare-verification --repo . --task-id <id>

# 6. Resume implementation (if verification findings require code fixes)
python .agents/scripts/workflow.py resume --repo . --task-id <id>
# READY_FOR_DELIVERY and the developer requested changes before committing:
python .agents/scripts/workflow.py resume --repo . --task-id <id> --reopen

# 7. Read-only verification check
python .agents/scripts/workflow.py verify --repo . --task-id <id>

# 8. Complete task (transitions to READY_FOR_DELIVERY)
python .agents/scripts/workflow.py complete --repo . --task-id <id>

# 9. Mark delivered / reconcile delivery (unlinks active task after Git commit)
python .agents/scripts/workflow.py deliver --repo . --task-id <id>
# or python .agents/scripts/workflow.py reconcile-delivery --repo . --task-id <id>

# 9b. Linked Zoho delivery sync (when task has approved zoho_link, after developer git commit)
python .agents/harness.py zoho delivery-sync --task-id <id>

# Cancel task: developer-owned. The agent puts this exact command in an ask_question and never runs
# cancel, resume or file edits to undo the work itself.
python .agents/scripts/workflow.py cancel --repo . --task-id <id>
```

### Expected Output
- Lifecycle state confirmation message or JSON with task status, run ID, and frozen snapshot hash.
- Exit code: `0` on success; non-zero if state transition precondition is not satisfied.

> **Material Drift Reconciliation**: If `prepare-verification` reports material drift (e.g. `surface:BUSINESS_LOGIC`), do not inspect harness scripts. Material drift produces `PLAN_REVISION_REQUIRED`. Reconcile with the canonical command produced by `build_remediation_command()`:
> `python .agents/scripts/workflow.py revise --repo . --task-id <id> --outcome "<original_outcome>" --kind <original_kind> --planning-depth <depth> --expected-surfaces "<all_active_surfaces>" ...`
> This archives the old plan, invalidates prior approval, and requires developer approval of the revised plan. Never use `workflow.py draft` to re-draft or overwrite an active task.

> **Instruction**: Do not inspect `workflow.py` implementation before execution.

---

## 4. Fast Deterministic Preflight Verification

### Purpose
Execute deterministic checks (strings parity, fast Kotlin lint, plan authority, Room schemas) before any AI specialist reviews or device deployment.

### Command
```bash
python .agents/harness.py preflight
# engine scripts: python .agents/scripts/preflight.py  (or preflight_check.py)
```

### Expected Output
- Step-by-step PASS/FAIL report for active gates.
- Exit code: `0` = all checks passed; non-zero = inspect reported failure details in terminal output.

> **Instruction**: Do not inspect `preflight.py` or `preflight_check.py` before execution.

---

## 5. Automated Unit Tests Gate

### Purpose
Run project unit tests (`testDebugUnitTest`) through Gradle Wrapper.

### Commands
```bash
# 0. Before the task's first edit: record which unit tests already fail (the router asks for it once)
python .agents/harness.py test --record-start

# 1. Run unit tests gate (GREEN phase verification)
python .agents/harness.py test
# engine form: python .agents/scripts/run_tests_gate.py

# 2. Capture executable RED failure proof (BUG tasks, after writing the failing test, before fixing code)
python .agents/harness.py test --capture-red
# engine form: python .agents/scripts/run_tests_gate.py --capture-red
```

### Expected Output
- For standard unit test gate: Execution status of Gradle unit test task, passed/failed test counts. Exit code: `0` = the gate passed; non-zero = `NEW_REGRESSION` or a build failure.
- For `--record-start`: writes `task-start-failures.json` in the task folder and lists the tests that already fail; exit code `0`. It runs only while the task has changed nothing (after any task edit it refuses and records nothing). If the untouched project's tests do not run, it records nothing (`status: BUILD_FAILED`) and says to tell the developer.
- For `--capture-red`: Schema 3 `red-evidence.json` capturing executed reproduction tests and failure signatures. Exit code: `0` on successful RED capture (real test assertion failure).
- Preconditions for `--capture-red`:
  - Used for `BUG` tasks whose router step is `CAPTURE_RED_EVIDENCE`.
  - Must occur BEFORE modifying production/application files (enforces pre-RED task-delta check; fails if non-test files are modified).
  - Requires a genuine failing test written by this run; a build failure or a clean pass is rejected, and stale reports from an earlier run are rejected.
  - Only failures that reproduce this task are recorded: known baseline failures never count; when the task added or changed test files, only failures from those files count; otherwise only the tests of planned files (`Foo` -> `FooTest`, `FooTests`, `FooSpec`) count. Another feature's failing test is never the reproduction.
  - On an untouched tree it also writes `task-start-failures.json`, like `--record-start`.
  - Debug evidence or logs cannot substitute for executable RED evidence.
- Pre-existing failures:
  - Baseline (`.agents/state/baseline.json`, captured at install on a clean tree) failures are tolerated as `BASELINE_IGNORED`.
  - A failure recorded in `task-start-failures.json` that fails the same way after the change is tolerated and printed as "already failed the same way before this task's fix ... Tell the developer" (`task_start_ignored`). The RED reproduction itself and any failure that changed still block.
  - Anything else is `NEW_REGRESSION`. When those tests belong to files outside the plan, never edit them under this plan: fix the planned production code if the change broke them; otherwise ask the developer with `ask_question` (revise the plan to include them, have them record a baseline on a clean tree with `python .agents/scripts/baseline_capture.py --run-tests`, or cancel).
- Editing an existing test file outside `expected_files` is scope drift unless it is the test of a planned file; new test files stay allowed.

> **Instruction**: Do not inspect test gate script before execution.

---

## 6. AI Specialist Reviewers & Evidence Recording

### Purpose
Generate immutable review package and record specialist subagent reviews.

### Commands
```bash
# 1. Generate review package (auto-detects active task; --task-id <id> is optional)
python .agents/harness.py review package --task-id <id>
# engine form: python .agents/scripts/review_package.py [--task-id <id>]

# 2. Record reviewer completion (Protocol V2 trusted completion):
python .agents/harness.py review complete --task <id> --reviewer <role> --execution-id <subagent_conversation_id>

# 3. Finalize reviews (aggregates completed reviews into immutable evidence):
python .agents/harness.py review finalize --task <id>

# 4. (Compatibility) Auto-harvest subagent review from transcript:
python .agents/scripts/record_review.py --task <id> --from-subagent <reviewer_name>=<subagent_conversation_id>

# 5. Validate or dispute reviewer findings (technical adjudication):
python .agents/scripts/workflow.py validate-finding --repo . --task-id <id> --finding-id <finding_id> --status <FALSE_POSITIVE|CONFIRMED> --reason "<technical_explanation>"

# 6. Developer review override (router step REVIEW_OVERRIDE_REQUIRED; non-sensitive surfaces only).
#    Show the developer this exact command; they run it in their own terminal, never the agent.
python .agents/scripts/record_review.py --task <id> --override-reviews --source developer_terminal --proof-reference "<developer_confirmation>"
```

### Expected Output
- Ingestion confirmation, evidence hash, and remaining required reviewers count.
- Exit code: `0` on success. Clean reviews with `findings: []` are recognized as `PASS`.

> **Zero-Polling Invariant**: Never poll background tasks or subagents with `manage_subagents` or `schedule`. Yield execution and wait for reactive messages from the system.

> **Review Budget Exhaustion**: If `prepare-verification` fails with `REVIEW_BUDGET_EXHAUSTED`, do not inspect harness scripts. Prompt developer via `ask_question` for decision: either approve increasing the review call budget or approve a review override (if touching non-sensitive surfaces).

> **Instruction**: Do not inspect review scripts before execution. Reviewers must be launched as independent subagents.

---

## 7. Assemble & Device Verification

### Purpose
Build debug APK and verify application on connected Android physical device or emulator.

### Commands
```bash
# 1. Check connected device status and target resolution
python .agents/scripts/run_device.py status

# 2. Assemble APK (resolved by project configuration; runs resolved task via run_gradle_task.py)
python .agents/harness.py assemble

# 3. Install and launch on target device/emulator
python .agents/harness.py device install-start
# engine form: python .agents/scripts/run_device.py install-start

# 3a. Device sign-off (router step DEVICE_SIGNOFF_REQUIRED): ask the developer with ask_question, giving the
#     numbered walkthrough steps and the expected result of each; the answer is PASS or FAIL.

# 3b. Optional skip validation (when developer explicitly requests to skip device verification)
python .agents/scripts/run_device.py skip-validation --task-id <id> --proof-reference "<developer_skip_confirmation>"

# 4. Capture screen (optional)
python .agents/scripts/capture_screen.py [--name <prefix>]
```

### Expected Output
- Build success / APK install confirmation / activity launch output.
- Exit code: `0` on success.
- For `skip-validation`: honest evidence recorded with `status: "SKIPPED"` (never synthetic PASS).

> **Reviewer Completion Precondition**: Diagnostic compile/assemble may run during `IMPLEMENTING` after task approval, but it is not delivery evidence. During `VERIFYING`, the final assemble and `run_device.py install-start` require all routed reviewers to finish and their evidence to be finalized.

> **Walkthrough Timing & Device Preconditions**: The agent MUST wait for `run_device.py install-start` to finish execution with exit code `0` BEFORE outputting any mobile verification walkthrough or invoking `ask_question`. If `run_device.py` is running in background, WAIT for completion; never output walkthrough or ask questions prematurely. If `run_device.py` fails (e.g. `[ENV-FAILURE] no Android device detected via adb`), report the environment blocker immediately to the developer; NEVER hallucinate device serials (such as `emulator-5554`), never claim the app is running when installation failed, and NEVER ask the developer to verify a build that was not installed.

> **Instruction**: Do not inspect assemble or device scripts before execution.

---

## 8. Harness Doctor & Health Verification

### Purpose
Verify harness installation health, tool adapters, file checksums, and configuration consistency.

### Commands
```bash
# In the Android project (preferred)
python .agents/harness.py doctor

# From the kit checkout, against a project
python harness_cli.py doctor --repo <app-root> --json

# Internal engine script
python .agents/scripts/harness_doctor.py
```

### Version and updates
```bash
python .agents/harness.py version       # installed harness version
python .agents/harness.py update-info   # newer release? prints exactly how the developer updates
```
When the developer asks to update the harness, run `update-info` and follow what it prints; never look for another way (package managers, the web, copying files). A task that is still open blocks an update; cancelling it is the developer's.

### Project context
```bash
python .agents/harness.py context status    # freshness of the derived project context
python .agents/harness.py context refresh   # refresh it when doctor reports it stale
```

### Expected Output
- JSON report with check categories, check names, status (`PASS`, `WARN`, `FAIL`), and diagnosis messages.
- Exit code: `0` = all health checks passed.

> **Instruction**: Do not inspect doctor engine source before execution.

---

## 8b. Test Suite Verification (Selftest)

### Purpose
Run deterministic safety suite verifying all harness invariants.

### Commands
Runs from the harness kit checkout (maintainers), not from an Android project.

```bash
# Quick selftest (7 developer-loop suites: hook, security, critical_safety, daily_workflow, public_cli, graph_discovery, antigravity_stability)
python harness_cli.py selftest --quick

# Full selftest (all 22 deterministic test suites, run in parallel; --jobs N sets the workers)
python harness_cli.py selftest
```

---

## 9. Diagnostic & Utility Scripts

### Purpose
Run targeted diagnostic checks, standalone lint/schema validators, crash analysis, or feature scaffolding directly without running the entire preflight suite.

### Commands
```bash
# 1. Logcat triage & crash diagnosis (ANRs, FATAL EXCEPTION, stack traces)
python .agents/scripts/logcat_doctor.py

# 2. Standalone localization & strings parity verification across locales
python .agents/scripts/check_strings.py

# 3. Standalone fast Kotlin AST linter (naming, coroutine dispatchers, empty catches)
python .agents/scripts/fast_kt_lint.py

# 4. Standalone Room database schema & migration integrity check
python .agents/scripts/room_guard.py

# 5. Architecture contract drift check (verifies code adheres to architectural policy)
python .agents/scripts/architecture_drift.py --repo . --task-id <id>
```

New screens and features are written by hand following the project's existing patterns (the task context names them); `new_feature_scaffold.py` is disabled and generates nothing.

---

## 10. Failure Escape Hatch & Debugging Protocol

Harness source inspection under `.agents/scripts/**` is strictly prohibited during normal development, with exactly **four exceptions**:

1. **Documented command fails unexpectedly**: Unhandled exception, Python traceback, or unexpected non-zero exit code with unclear error message.
2. **Output violates documented contract**: The command output produces malformed data, schema mismatch, or fails to generate an expected artifact.
3. **Doctor reports corruption/inconsistency**: Harness Doctor reports missing files, tampered checksums, or configuration inconsistency.
4. **Explicit developer request**: The developer explicitly asks you to inspect, debug, modify, or extend the harness itself.

### Debugging Protocol
When an exception occurs:
1. Read the failing command's terminal output and error message first.
2. Inspect **only** the specific, directly relevant harness script or helper function.
3. Do **not** recursively scan unrelated harness scripts.
4. Return to normal public-contract execution immediately after diagnosing the issue.

---

## 11. Canonical Command Catalog

| Step / Tool | Canonical Command | Description |
| :--- | :--- | :--- |
| **Discovery** | `python .agents/harness.py graph --feature <name> --json` (or `--find <Symbol>`; engine: `project_graph.py`) | Fast AST/symbol project graph analysis |
| **Task Context** | `python .agents/harness.py task-context --file <path> --json` (or `--symbol <name>`) | Bounded context for one task target; records the discovery receipt |
| **Clarification** | `ask_question` tool | Interactive question modal before drafting plan |
| **Draft Plan** | `python .agents/scripts/workflow.py draft --repo . --task-id <id> ...` | Register the plan and print the approval material |
| **Revise Plan** | `python .agents/scripts/workflow.py revise --repo . --task-id <id> ...` | Change the plan; approval is asked again |
| **Approve** | `python .agents/scripts/workflow.py approve --repo . --task-id <id> --source conversation --proof-reference "<reply>" --enforcement-tier RULE_ENFORCED --plan-hash <hash>` | Record the developer's approval of the shown plan |
| **Next Action** | `python .agents/harness.py task status --task-id <id> --next --json` | The router: the single next step and why |
| **Cancel Task** | `python .agents/scripts/workflow.py cancel --repo . --task-id <id>` | Developer-owned: put it in an ask_question, never run it |
| **Context Note** | `python .agents/harness.py context note "<note>"` | Record architectural convention/note |
| **Zoho Start Sync**| `python .agents/harness.py zoho start-sync --task-id <id>` | Sync In progress status to linked Zoho item; on `ENV`, tell the developer |
| **Preflight Gate** | `python .agents/harness.py preflight` (engine: `preflight.py` / `preflight_check.py`) | Deterministic check: room, fast ktlint, string parity |
| **Record Start** | `python .agents/harness.py test --record-start` | Before the first edit: record the tests that already fail |
| **Unit Tests** | `python .agents/harness.py test` (engine: `run_tests_gate.py`) | Run unit tests gate (GREEN phase) |
| **Capture RED** | `python .agents/harness.py test --capture-red` (engine: `run_tests_gate.py --capture-red`) | Capture executable test failure proof for BUG tasks |
| **Checkpoint Phase** | `python .agents/scripts/workflow.py checkpoint-phase --repo . --task-id <id>` | Advance multi-phase plan checkpoint autonomously |
| **Strings Check** | `python .agents/scripts/check_strings.py` | Standalone strings parity across locales |
| **Fast Lint** | `python .agents/scripts/fast_kt_lint.py` | Standalone fast Kotlin AST linter |
| **Room Guard** | `python .agents/scripts/room_guard.py` | Standalone Room schema & migration check |
| **Arch Drift** | `python .agents/scripts/architecture_drift.py --repo . --task-id <id>` | Validate code against architecture contract |
| **Logcat Doctor** | `python .agents/scripts/logcat_doctor.py` | Triage crashes and runtime exceptions |
| **Prepare Verification** | `python .agents/harness.py task prepare-verification --repo . --task-id <id> --host <host>` | Freeze the change and start the verification run |
| **Review Package** | `python .agents/harness.py review package --task-id <id>` (engine: `review_package.py`) | Generate immutable review package markdown |
| **Review Complete**| `python .agents/harness.py review complete --task <id> --reviewer <role> --execution-id <convId>` | Record trusted reviewer completion |
| **Review Finalize**| `python .agents/harness.py review finalize --task <id>` | Aggregate review evidence once all reviewers complete |
| **Resume Task** | `python .agents/scripts/workflow.py resume --repo . --task-id <id>` | Resume task from BLOCKED or VERIFYING back to implementation; add `--reopen` at READY_FOR_DELIVERY when the developer requests changes |
| **Assemble** | `python .agents/harness.py assemble` | Build application debug artifact (derived assemble task) |
| **Device Status** | `python .agents/scripts/run_device.py status` | Inspect connected Android physical devices and emulators |
| **Device Deploy** | `python .agents/harness.py device install-start` (engine: `run_device.py install-start`) | Install and launch on target device/emulator |
| **Device Skip** | `python .agents/scripts/run_device.py skip-validation --task-id <id> --proof-reference "<phrase>"` | Record explicit developer skip of mobile validation |
| **Screen Capture** | `python .agents/scripts/capture_screen.py --name <prefix>` | Capture device screen for verification proof |
| **Harness Doctor** | `python .agents/harness.py doctor` (kit: `harness_cli.py doctor --repo <app> --json`) | Health check harness installation & adapters |
| **Version / Update** | `python .agents/harness.py version` / `python .agents/harness.py update-info` | Installed version; how to update to a newer release |
| **Selftest Quick** | `python harness_cli.py selftest --quick` | Kit checkout only: developer-loop selftest (7 suites) |
| **Selftest Full** | `python harness_cli.py selftest` | Kit checkout only: complete deterministic selftest (22 suites) |
| **Final Verify** | `python .agents/scripts/workflow.py verify --repo . --task-id <id>` | Read-only delivery verification check |
| **Deliver Task** | `python .agents/scripts/workflow.py deliver --repo . --task-id <id>` | Finalize delivery state after git commit |
| **Zoho Delivery Sync**| `python .agents/harness.py zoho delivery-sync --task-id <id>` | Sync delivery report & resolution to linked Zoho item |
