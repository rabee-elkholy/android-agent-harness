# Android Agent Harness — Public Command Contract

> **Core Invariant**: During normal Android application tasks, installed harness engine source under `.agents/scripts/**` is an implementation detail. Do not inspect or recursively read harness Python implementation before executing a documented harness command. Use this documented public command contract and its output directly.

---

## 1. Discovery & Project Graph

### Purpose
Resolve project topology, feature boundaries, callers, callees, UI screens, ViewModel bindings, and architecture contracts before touching code.

### Command
```bash
python .agents/scripts/project_graph.py --feature <feature_name>
# or
python .agents/scripts/project_graph.py --find <SymbolName>
```

### Inputs
- `--feature <feature_name>`: Name or path token of the feature slice.
- `--find <SymbolName>`: Specific Kotlin class, interface, or symbol to locate.

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
  --test-strategy <UNIT_ONLY|DEVICE_ONLY|FULL|NONE> \
  --device-strategy <EMULATOR_PREFERRED|PHYSICAL_PREFERRED|ANY|NONE> \
  --risks "<comma-separated risks>" \
  --rollback "<rollback instructions>" \
  --external-write zoho_sprints \
  --architecture-intent <EXISTING_CHANGE|NEW_SCREEN|NEW_FEATURE|REFACTOR|MIGRATION> \
  --architecture-target-scope "<target scope when applicable>" \
  --architecture-target-family "<target family id when applicable>" \
  --phases "<phases json or file path when required>"

> `--planning-depth`: `BOUNDED` for normal scoped tasks (default); `ARCHITECTURAL` for explicit architecture migration or broad structural architectural work.
> `--external-write`: Append `zoho_sprints` when Zoho Sprints tracker mutation is explicitly included in the approved plan.

# 2. Record developer approval (after explicit developer approval via Proceed button or chat)
python .agents/scripts/workflow.py approve --repo . --task-id <id> --source conversation --proof-reference "<developer_confirmation>" --enforcement-tier RULE_ENFORCED

# 3. Begin implementation
python .agents/scripts/workflow.py begin --repo . --task-id <id>

# 4. Advance phase checkpoint (for multi-phase plans; autonomous execution without developer prompt)
python .agents/scripts/workflow.py checkpoint-phase --repo . --task-id <id>

# 5. Prepare verification (freezes review package and initializes run)
python .agents/scripts/workflow.py prepare-verification --repo . --task-id <id>

# 6. Resume implementation (if verification findings require code fixes)
python .agents/scripts/workflow.py resume --repo . --task-id <id>

# 7. Read-only verification check
python .agents/scripts/workflow.py verify --repo . --task-id <id>

# 8. Complete task (transitions to READY_FOR_DELIVERY)
python .agents/scripts/workflow.py complete --repo . --task-id <id>

# 9. Mark delivered (unlinks active task after Git commit)
python .agents/scripts/workflow.py deliver --repo . --task-id <id>

# Cancel task
python .agents/scripts/workflow.py cancel --repo . --task-id <id>
```

### Expected Output
- Lifecycle state confirmation message or JSON with task status, run ID, and frozen snapshot hash.
- Exit code: `0` on success; non-zero if state transition precondition is not satisfied.

> **Material Drift Reconciliation**: If `prepare-verification` reports material drift (e.g. `surface:BUSINESS_LOGIC`), do not inspect harness scripts. Reconcile by updating the plan draft with all active surfaces while preserving the original task outcome and intent:
> `python .agents/scripts/workflow.py draft --repo . --task-id <id> --outcome "<original_outcome>" --kind <original_kind> --expected-surfaces "<all_active_surfaces>"`
> and obtain developer approval.

> **Instruction**: Do not inspect `workflow.py` implementation before execution.

---

## 4. Fast Deterministic Preflight Verification

### Purpose
Execute deterministic checks (strings parity, fast Kotlin lint, plan authority, Room schemas) before any AI specialist reviews or device deployment.

### Command
```bash
python .agents/scripts/preflight.py
# or
python .agents/scripts/preflight_check.py
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
# 1. Run unit tests gate (GREEN phase verification)
python .agents/scripts/run_tests_gate.py

# 2. Capture executable RED failure proof (BUG tasks only, before fixing code)
python .agents/scripts/run_tests_gate.py --capture-red
```

### Expected Output
- For standard unit test gate: Execution status of Gradle unit test task, passed/failed test counts. Exit code: `0` = all tests pass; non-zero = unit test failure.
- For `--capture-red`: Schema 3 `red-evidence.json` capturing executed reproduction tests and failure signatures. Exit code: `0` on successful RED capture (real test assertion failure).
- Preconditions for `--capture-red`:
  - Active task kind must be `BUG`.
  - Must occur BEFORE modifying production/application files (enforces pre-RED task-delta check; fails if non-test files are modified).
  - Requires genuine assertion test failure (exit code 1); compilation failure (exit code 2) or clean pass (exit code 0) is rejected.
  - Debug evidence or logs cannot substitute for executable RED evidence.

> **Instruction**: Do not inspect test gate script before execution.

---

## 6. AI Specialist Reviewers & Evidence Recording

### Purpose
Generate immutable review package and record specialist subagent reviews.

### Commands
```bash
# 1. Generate review package (auto-detects active task; --task-id <id> is optional)
python .agents/scripts/review_package.py
# or explicitly: python .agents/scripts/review_package.py --task-id <id>

# 2. Auto-harvest subagent review from transcript (preferred):
python .agents/scripts/record_review.py --task <id> --from-subagent <reviewer_name>=<subagent_conversation_id>

# 3. Direct response text ingestion:
python .agents/scripts/record_review.py --task <id> --response-text "<reviewer_name>=<response_text>"

# 4. Ingest from file:
python .agents/scripts/record_review.py --task <id> --response <reviewer_name>=<path>

# 5. Validate or dispute reviewer findings (technical adjudication):
python .agents/scripts/workflow.py validate-finding --repo . --task-id <id> --finding-id <finding_id> --status <FALSE_POSITIVE|CONFIRMED> --reason "<technical_explanation>"

# 6. Developer review override (only if explicitly requested by developer on non-sensitive surfaces)
python .agents/scripts/record_review.py --task <id> --override-reviews --proof-reference "<developer_confirmation>"
```

### Expected Output
- Ingestion confirmation, evidence hash, and remaining required reviewers count.
- Exit code: `0` on success. Clean reviews with `cites=0` and explanatory prose are recognized as `PASS`.

> **Zero-Polling Invariant**: Never poll background tasks or subagents with `manage_subagents` or `schedule`. Yield execution and wait for reactive messages from the system.

> **Review Budget Exhaustion**: If `prepare-verification` fails with `REVIEW_BUDGET_EXHAUSTED`, do not inspect harness scripts. Prompt developer via `ask_question` for decision: either approve increasing the review call budget or approve a review override (if touching non-sensitive surfaces).

> **Windows/PowerShell formatting tip**: In terminal commands, write newlines in `--response-text` as `\n` (e.g. `--response-text "<reviewer>=PASS\nEVIDENCE pkg=<sha12> cites=0"`) or write the response to a file and use `--response <reviewer>=<file_path>`.

> **Instruction**: Do not inspect review scripts before execution. Reviewers must be launched as independent subagents.

---

## 7. Assemble & Device Verification

### Purpose
Build debug APK and verify application on connected Android physical device or emulator.

### Commands
```bash
# 1. Check connected device status and target resolution
python .agents/scripts/run_device.py status

# 2. Assemble APK
python .agents/scripts/run_gradle_task.py :app:assembleDebug

# 3. Install and launch on target device/emulator
python .agents/scripts/run_device.py install-start

# 4. Capture screen (optional)
python .agents/scripts/capture_screen.py
```

### Expected Output
- Build success / APK install confirmation / activity launch output.
- Exit code: `0` on success.

> **Reviewer Completion Precondition**: Diagnostic compile/assemble may run during `IMPLEMENTING` after task approval, but it is not delivery evidence. During `VERIFYING`, the final assemble and `run_device.py install-start` require all routed reviewers to finish and their evidence to be recorded via `record_review.py`.

> **Walkthrough Timing & Device Preconditions**: The agent MUST wait for `run_device.py install-start` to finish execution with exit code `0` BEFORE outputting any mobile verification walkthrough or invoking `ask_question`. If `run_device.py` is running in background, WAIT for completion; never output walkthrough or ask questions prematurely. If `run_device.py` fails (e.g. `[ENV-FAILURE] no Android device detected via adb`), report the environment blocker immediately to the developer; NEVER hallucinate device serials (such as `emulator-5554`), never claim the app is running when installation failed, and NEVER ask the developer to verify a build that was not installed.

> **Instruction**: Do not inspect assemble or device scripts before execution.

---

## 8. Harness Doctor & Health Verification

### Purpose
Verify harness installation health, tool adapters, file checksums, and configuration consistency.

### Commands
```bash
# Public CLI façade (preferred)
python harness_cli.py doctor --repo . --json

# Internal engine script
python .agents/scripts/harness_doctor.py
```

### Expected Output
- JSON report with check categories, check names, status (`PASS`, `WARN`, `FAIL`), and diagnosis messages.
- Exit code: `0` = all health checks passed.

> **Instruction**: Do not inspect doctor engine source before execution.

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

# 6. Feature module / slice scaffolding
python .agents/scripts/new_feature_scaffold.py --feature <feature_name>
```

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
| **Discovery** | `python .agents/scripts/project_graph.py --feature <name>` (or `--find <Symbol>`) | Fast AST/symbol project graph analysis |
| **Task Context** | `python .agents/harness.py task-context --file <path> --json` (or `--symbol <name>`) | Bounded, read-only context for one task target |
| **Clarification** | `ask_question` tool | Interactive question modal before drafting plan |
| **Context Note** | `python .agents/harness.py context note "<note>"` | Record architectural convention/note |
| **Preflight Gate** | `python .agents/scripts/preflight.py` (or `preflight_check.py`) | Deterministic check: room, fast ktlint, string parity |
| **Unit Tests** | `python .agents/scripts/run_tests_gate.py` | Run unit tests gate (GREEN phase) |
| **Capture RED** | `python .agents/scripts/run_tests_gate.py --capture-red` | Capture executable test failure proof for BUG tasks |
| **Checkpoint Phase** | `python .agents/scripts/workflow.py checkpoint-phase --repo . --task-id <id>` | Advance multi-phase plan checkpoint autonomously |
| **Strings Check** | `python .agents/scripts/check_strings.py` | Standalone strings parity across locales |
| **Fast Lint** | `python .agents/scripts/fast_kt_lint.py` | Standalone fast Kotlin AST linter |
| **Room Guard** | `python .agents/scripts/room_guard.py` | Standalone Room schema & migration check |
| **Arch Drift** | `python .agents/scripts/architecture_drift.py --repo . --task-id <id>` | Validate code against architecture contract |
| **Logcat Doctor** | `python .agents/scripts/logcat_doctor.py` | Triage crashes and runtime exceptions |
| **Feature Scaffold**| `python .agents/scripts/new_feature_scaffold.py --feature <name>` | Scaffold feature conventions and ViewModel |
| **Review Package** | `python .agents/scripts/review_package.py` | Generate immutable review package markdown |
| **Review Harvest** | `python .agents/scripts/record_review.py --task <id> --from-subagent <role>=<convId>` | Auto-harvest subagent transcript and record review |
| **Review Text** | `python .agents/scripts/record_review.py --task <id> --response-text "<role>=<text>"` | Direct review text ingestion with evidence footer |
| **Resume Task** | `python .agents/scripts/workflow.py resume --repo . --task-id <id>` | Resume task from BLOCKED or VERIFYING back to implementation |
| **Assemble Debug** | `python .agents/scripts/run_gradle_task.py :app:assembleDebug` | Diagnostic in IMPLEMENTING; final delivery build after all reviewers pass |
| **Device Status** | `python .agents/scripts/run_device.py status` | Inspect connected Android physical devices and emulators |
| **Device Deploy** | `python .agents/scripts/run_device.py install-start` | Install and launch on target device/emulator |
| **Screen Capture** | `python .agents/scripts/capture_screen.py --output-name <name>` | Capture device screen for verification proof |
| **Harness Doctor** | `python harness_cli.py doctor --repo . --json` | Health check harness installation & adapters |
| **Final Verify** | `python .agents/scripts/workflow.py verify --repo . --task-id <id>` | Read-only delivery verification check |
| **Deliver Task** | `python .agents/scripts/workflow.py deliver --repo . --task-id <id>` | Finalize delivery state after git commit |
