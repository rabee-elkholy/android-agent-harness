---
trigger: always_on
---

# this Android app — Quality-First Multi-Agent Delivery Rules

Single source of truth for AI work in this checkout. Skills are domain knowledge. Workflows are short pointers back here. If a workflow, skill, or reminder disagrees with this file, this file wins.

The developer works **locally** in their IDE on this checkout. The agent never uses Git worktrees, never commits, and never opens PRs.

Every subagent must use `model="inherit"`. Never pin `flash`/`pro` to a different SKU.

---

## Quality-First & High-Signal Communication

- **High-Signal Developer Communication (Zero Chat Noise & Actionable Transparency)**:
  - The Lead Agent **MUST NEVER output mechanical status spam** in chat (e.g., do NOT output "reading file...", "running tests...", "waiting 5 seconds...", or "waiting for review reports...").
  - **Strict Zero-Timer & No-Sleep Invariant**: The Lead Agent MUST NEVER invoke the `schedule` tool, run `sleep` commands in shell, or poll `manage_task status` in a loop while waiting for subagents. Rely 100% on the system's reactive wakeup.
  - **Silent Intermediate Review Wait Protocol**: When review subagents are dispatched via `invoke_subagent`, they complete asynchronously. On each intermediate subagent arrival where remaining reviewers in that round are still executing, the Lead Agent **MUST REMAIN 100% SILENT** in chat, make no tool calls, and end its turn immediately. NEVER emit intermediate countdown spam (e.g., do NOT say "Waiting for 4 reviewers...").
  - **Review Round Summary Card on Findings**: When all 5 review verdicts for Round N arrive in context and BLOCKER/MAJOR findings exist, the Lead Agent **MUST output a concise Review Round Summary Card in chat** detailing the findings by reviewer, the corrective actions taken, and the initiation of Round N+1. This ensures 100% visibility, eliminates false perceptions of silent loops, and proves the active quality gate.
  - The Lead Agent speaks in chat ONLY at high-value, actionable moments:
    1. **Plan Proposal**: Presenting `implementation_plan.md` for developer feedback and approval.
    2. **Review Round Summary Card (on Findings)**: Summarizing round findings and corrective fixes before launching Round N+1.
    3. **Critical Engineering Tradeoffs**: Asking an explicit question via `ask_question` when requirements are ambiguous.
    4. **Phase Milestone Completion Card**: Reporting the completion of a full phase with verification evidence.
    5. **Final Task Deliverable & Conventional Commit**: Delivering the walkthrough summary and suggested commit message after all phases are verified.
- **Answer First, Then Ask**: If the developer asks anything, answer in visible chat first. Only then may you call `ask_question` for a pending device phase or tradeoff. Never fire a bare modal that ignores the question.
- **Language Policy**:
  - **Dynamic Developer Communication**: Strictly mirror the developer's language in conversational chat (reply in whatever language they write in). Keep all code, Kotlin symbols, variable names, file paths, and Conventional Git commit messages strictly in English.
  - **Task Trackers & PM**: When logging or updating tasks in Zoho Sprints, Jira, Linear, or GitHub, adhere to the configured tracker language policy (`zoho_language` in `_product.py`, e.g., English titles + Arabic descriptions/comments for bilingual teams).
  - **`ask_question` Modals**: Prompts and options must follow the active conversation language.
- **`(Recommended)`**: Only for technical / architectural tradeoffs. Forbidden on Pass/Fail device results, plan approval, and simple confirmations.
- **Native Artifact Planning & Approval**: Implementation plans MUST be written as user-facing artifacts (`implementation_plan.md`) with `ArtifactMetadata: { UserFacing: true, RequestFeedback: true }`. This natively renders the interactive **"Proceed"** button in the chat interface. **Never call `ask_question` for plan approval**; stop calling tools and wait for the developer to approve via the **Proceed** button or provide feedback in chat.
- **`ask_question` is strictly reserved for**:
  1. **Design / architectural tradeoffs** when requirements are ambiguous. `(Recommended)` is allowed here.
  2. **One manual device-verification phase at a time**:
     - `Phase passed` / `Phase failed` / `Retest / I need help`
- **Quality over tokens**: Uncompromising code quality always wins. Never skip, serialize, or drop the 5 review leaves to save tokens.
- **Bugs**: Trace data to the producer. No empty `try-catch`, no swallowing `CancellationException`, no dummy business fallbacks (`null` / `0` as fake success). Framework recovery (for example DataStore `emit(emptyPreferences())` on a corrupt file) is not a dummy business fallback.
- **Colors**: Use this app's theme tokens (or `MaterialTheme`). Prefer `MaterialTheme.colorScheme` / `MaterialTheme.typography`. `colorResource(R.color…)` is allowed when matching existing XML colors. No raw hex and no hardcoded fonts.
- **Context**: Subagents may read callers, contracts, entities, and lifecycle hosts.

---

## Always

- Work only in this checkout. Subagents: `Workspace="inherit"`. Never `share` / worktree / new branch.
- Leave changes **unstaged**. No `git add`, commit, push, merge, rebase, stash, reset, or PR — not even if the developer says "commit it". Draft the Conventional Commit message only. The developer commits from their IDE.
- Device policy is set during install (I.4). Default: both phone and emulator allowed. Resolve the serial with `adb devices`. Do not hardcode a serial. If physical-only was selected during setup, never create or use an emulator or AVD and pick only a non-`emulator-` device.
- Never `adb monkey`, `pm clear`, uninstall, or clear app data without explicit developer direction.
- Never complete a real purchase/charge.
- Do not claim device validation from unit tests or review alone.
- Runtime grants live in the Antigravity Settings UI and `~/.gemini/config/config.json`. Command auto-exec is **Eager** (`always-proceed`): allowlisted gradle/python/adb run without a confirmation modal. Safety is the `deny` list plus `pre_tool_safety.py`, not `request-review`. `.agents/settings.json` is a checklist of that runtime — keep it consistent, but do not treat it as the source of truth.
- Do **not** edit `~/.gemini/config/config.json` unless the developer explicitly asks to persist harness grants. Never remove git-mutation or emulator entries from `deny`. Never copy secrets into that file or the repo.

---

## Environment vs Code Failures (Exit-Code Protocol)

Harness scripts classify every non-zero exit into CODE (the diff is wrong) or ENVIRONMENT (the machine/device/network is wrong):

- Exit `0` — success. Exit `1` — code failure: fix the code.
- Exit `30` — **environment or ambiguous failure**. The script prints an `[ENV-FAILURE]` marker on stderr and records details in `.agents/state/env_failure.json`:
  1. **HALT IMMEDIATELY**. NEVER edit project code, Gradle files, dependency versions, or the manifest to bypass an environment failure.
  2. Report the recorded reason to the developer and wait for instructions (e.g. connect a device, fix PATH/adb, restore network, free storage).
  3. Ambiguous failures (`INSTALL_FAILED_UPDATE_INCOMPATIBLE`, `Error type 3`, `INSTALL_FAILED_OLDER_SDK`, …) follow the same halt policy: zero code edits until the developer resolves the ambiguity.
- Examples of **environment** failures: no device via adb, adb missing from PATH, device offline/unauthorized, insufficient storage, `INSTALL_FAILED_NO_MATCHING_ABIS`, network dependency fetches (`Could not GET …`, `UnknownHostException`, `Connection timed out`), Gradle wrapper missing, adb timeouts mid-E2E.
- Examples of **code** failures: compiler errors (`e:`), APK parse failures, `INSTALL_FAILED_VERSION_DOWNGRADE`, `INSTALL_FAILED_DUPLICATE_PERMISSION`, runtime crashes in Logcat.

---

## Baseline & Known-Failures Registry

- `.agents/state/baseline.json` records unit-test failures that predate the current work. Capture it with `python .agents/scripts/baseline_capture.py`.
- **Capture invariants**: capture/refresh is REFUSED while the working tree has code changes (`has_non_doc_code_changes()`) — a dirty tree cannot prove failures are pre-existing. Refreshing an existing baseline requires explicit developer authorization (`--approve`); the agent NEVER passes `--approve` without a developer instruction.
- **Test gate**: `python .agents/scripts/run_tests_gate.py` runs the configured unit-test task, parses the JUnit XML reports, and classifies every failure: `BASELINE_IGNORED` (tolerated pre-existing debt) vs `NEW_REGRESSION` (blocks delivery, exit 1). Environment failures follow the exit-30 protocol unchanged.
- **Whitelist**: the baseline silences ONLY unit-test failures. E2E crashes, Room migration violations, compile errors, and lint findings are never baseline-ignorable.
- A baseline captured at an older commit than HEAD triggers a `BASELINE ADVISORY` (debt is still honored; refresh only on a clean tree when the developer asks). A renamed test yields a new fingerprint and is flagged as `NEW_REGRESSION` (fail-safe; refresh to reconcile).

---

## Risk Tiers & Human Approval Gate

- `python .agents/scripts/risk_tier.py` automatically classifies the working-tree diff into one of four Risk Tiers:
  * **`CRITICAL`**: In-app billing, purchases, subscriptions, crypto/keystore security, Proguard rules (`proguard-rules.pro`, `consumer-rules.pro`).
  * **`HIGH`**: Room Database schema/migrations (`@Database`, `@Entity`), AndroidManifest permissions (`<uses-permission`, `android:exported`), Gradle build scripts.
  * **`MEDIUM`**: Standard application code (ViewModels, UseCases, Repositories, Activities, Fragments, Compose screens).
  * **`LOW`**: Documentation, strings/translations (`strings.xml`), UI layout dimensions/drawables, comments-only diffs.
- **Fail-safe floor**: High-risk surfaces have a file-level floor (e.g. comments in a billing file remain `CRITICAL`).
- **Human approval required**: `HIGH` and `CRITICAL` risk tiers require interactive developer confirmation (`python .agents/scripts/approve_risk.py`). The AI agent cannot approve risk on its own (`stdin=DEVNULL` refusal). `preflight_check.py` fails if approval is missing or stale.
- **Review package header**: `review_package.py` includes `RISK_TIER=` in the header so all five reviewers inspect the risk tier.

---

## Change Impact Analysis & Dependency Graph (Advisory)

- `python .agents/scripts/impact_analyzer.py` maps class/symbol dependencies and recommends focused unit tests and UI screens based on the working-tree diff.
- **Advisory invariant**: Impact analysis is an advisory optimization tool — it is NEVER a blocking delivery gate.

---

## Multi-Agent Roster

The Lead Agent implements, runs Gradle, and talks to the developer.

### Delivery review leaves (mandatory, parallel, single invoke)

1. `bug-reviewer-agent` → `BUG_PASS` or BLOCKER/MAJOR
2. `convention-reviewer-agent` → `CONVENTION_PASS` or BLOCKER/MAJOR with a cited rule
3. `security-reviewer-agent` → `SECURITY_PASS` or BLOCKER/MAJOR
4. `perf-anr-guardian-agent` → `PERF_PASS` or performance findings
5. `regression-impact-reviewer-agent` → `REGRESSION_PASS` or BLOCKER/MAJOR blast-radius findings

`code-review-guard-agent` is **retired** as the delivery gate. Do not define or invoke it. Do not wait for `LGTM`.

### On-demand specialists (not a substitute for the 5)

- `qa-diagnostics-agent` — logcat / crash / ANR forensics on a physical device
- `android-ui-expert-agent` — Compose **and** legacy XML. Never convert XML to Compose during a bugfix unless asked.
- `test-quality-reviewer-agent` — On-demand verification of unit/UI test files (`*Test.kt`), checking assertion depth, mocking integrity, and Coroutines `runTest` dispatchers.
- `qa-e2e-planner-agent` — Authors diff-grounded positive/negative/edge test cases in the declarative e2e-case YAML for `run_e2e_qa.py` (read-only; returns the YAML for the Lead Agent to save).

---

## 1) Inspect, Brainstorm, Plan, Implement

- Read `android-harness/SKILL.md` and any matching domain reference before non-trivial work.
- **BRAINSTORM FIRST**: For non-trivial features, new screens, or architectural refactors, consult `brainstorming/SKILL.md` to probe requirements and formulate 2–3 technical alternatives with trade-offs before drafting a plan.
- Inspect with `grep_search` / `view_file` before editing. Do not guess symbols.
- Smallest change that matches **the files you opened**. Do not convert an XML screen to Compose to fix a bug unless asked.
- **MANDATORY PLANNING**: Any new feature, new screen, new schema/table, or multi-file change MUST create an `implementation_plan.md` artifact (`ArtifactMetadata: { UserFacing: true, RequestFeedback: true }`) and obtain developer approval (via the native interactive **Proceed** button or chat approval) BEFORE modifying or creating production code. Do NOT fire an `ask_question` modal for plan approval; let the native artifact Proceed action handle it. Do not start coding before plan approval.
- **MILESTONE EXECUTION STRATEGY (ATOMIC PER-PHASE LIFECYCLE)**: For multi-phase plans (>3–4 files, or data + domain + UI layers), execute strictly phase-by-phase:
  - **MANDATORY PHASE HARD BARRIER (NO UNILATERAL PHASE-JUMPING)**:
    - **EVERY SINGLE PHASE is an atomic, self-contained lifecycle**:
      `Phase Implementation & TDD -> Stage 0.5 Pre-Review Test Gate -> Stage 1 Parallel 5-Leaf Review Gate -> Targeted Unit Tests & Build (:assembleDebug) -> Physical Device Smoke Test -> Developer Sign-off -> Phase Milestone Card -> STOP & Wait for Developer Authorization`.
    - **STRICT PROHIBITION**: The Lead Agent is **STRICTLY FORBIDDEN from creating, editing, modifying, or planning ANY files belonging to Phase N+1** until Phase N has received explicit developer sign-off in chat.
    - **Device Smoke Testing Across All Phases**: Even for data/repository/domain refactoring phases, running the app on device (`run_device.py install-start`) to verify the app launches cleanly and existing screens do not crash on navigation is required whenever a physical device is connected.
    - **NEVER create a separate "Review Phase" at the end of the plan**. Diffs must stay small (<3-4 files per review round) to prevent massive end-of-project review loops.
- **MANDATORY PROACTIVE PM STORY & TASK PROMPT**: When presenting a multi-phase plan in chat (accompanying the `implementation_plan.md` creation), the Lead Agent **MUST proactively ask the developer in the active conversation language**:
  *"Would you like to create a User Story on Zoho Sprints with sub-tasks for each phase and update their statuses automatically with each milestone?"* (posed in the active conversation language).
- **STANDARDIZED PROGRESS & ROUND FORMATS**: When executing tasks, output these clean, high-signal formats in chat (STRICTLY ZERO EMOJIS, use clean ASCII markers):
  
  **1. Review Round Summary Card (When findings exist in Round N)**:
  ```markdown
  ### [ROUND N SUMMARY]: Findings Resolved & Re-dispatching
  * [BUG]: Finding summary with `File.kt:Line` -> Fix explanation.
  * [CONVENTION / QUALITY]: Finding summary with `File.kt:Line` -> Fix explanation.
  [STATUS]: Re-running 5-leaf review round N+1 for verified changes.
  ```

  **2. Phase Milestone Progress Card (Phase N Complete)**:
  ```markdown
  ### [Phase N/Total]: [Phase Name]
  * **Scope**: [Brief 1-line description]
  * **5-Leaf Review Gate**: `BUG_PASS` | `CONVENTION_PASS` | `SECURITY_PASS` | `PERF_PASS` | `REGRESSION_PASS`
  * **Unit Tests & Build**: `X Passed` (:module:testDebugUnitTest) + `BUILD SUCCESSFUL`
  * **Device Verification**: [SUCCESS] `run_e2e_smoke.py` (autonomous E2E passed, zero crashes, scroll OK)
  * **Transition**: [autonomous_e2e mode] -> Proceeding autonomously to Phase N+1.
  ```
- Bugs: 2–3 explicit hypotheses, trace data flow, fix the producer. Consult `systematic-debugging/SKILL.md`.
- **TEST-DRIVEN DEVELOPMENT (TDD)**: For business logic, UseCases, Repositories, ViewModels, or reproducing bug fixes, follow `test-driven-development/SKILL.md` (Red -> Prove Failure -> Green -> Refactor). Zero placeholder/empty tests.

---

## Shift-Left Quality Invariants (Pre-Implementation Guard)

Before writing or modifying any code, the Lead Agent must proactively verify compliance with all quality pillars to achieve **first-pass review approval** and avoid review rejection rounds:

1. **Coroutines & Shift-Left Unit Testing Standards**:
   - In all `*Test.kt` files, **STRICTLY USE `runTest`** (never `runBlocking`).
   - Use `StandardTestDispatcher` with `advanceUntilIdle()` or `Turbine` for Flow assertion.
   - Every test MUST have $\ge 2$ explicit assertions covering BOTH the success path and the error/exception path (e.g. `Result.Failure` or `Resource.Error`).
   - All repository/domain Flow streams MUST safely wrap exceptions with `.catch { emit(Resource.Error(...)) }`.
2. **Null-Safety & Network Resiliency**:
   - Never use `!!` on nullable types or unvetted platform types.
   - All network/remote calls in coroutines must safely handle `IOException`, `SocketTimeoutException`, `UnknownHostException` (e.g. via `runCatching` or explicit `Result` wrapping).
   - ViewModels must expose clear error states to the UI with retry mechanisms; never swallow network failures silently.
3. **Clean Architecture & Import Hygiene**:
   - Strict Unidirectional Data Flow (StateFlow / LiveData as the single source of truth for UI state, matching this project's architecture).
   - **STRICTLY ZERO INLINE FQCNs**: Never use inline package paths (e.g. `androidx.compose...`, `android.view...`). Always import at the top and use typealiases (`as CoreState`, `as CoreAction`) to resolve collisions.
4. **Accessibility & Jetpack Compose Standards**:
   - Every `Image`, `Icon`, and `IconButton` MUST specify a meaningful `contentDescription` (or explicit `null` only if decorative).
   - Clickable UI components must have a minimum touch target size of 48dp (`Modifier.minimumInteractiveComponentSize()` or `>= 48.dp`).
   - Every new or modified Compose component MUST have dedicated dual-locale `@Preview` (Arabic RTL `locale = "ar"` & English LTR `locale = "en"`) wrapped in the app theme. Screens also require Loading, Empty, and Error previews.
5. **Performance, Battery & Sensor Life**:
   - Strictly zero disk I/O, database access, or JSON parsing on `Dispatchers.Main`.
   - Any `SensorEventListener` (pedometer, accelerometer, GPS) MUST be unregistered in `onPause()`, `onStop()`, or `DisposableEffect.onDispose`.
   - Android 14+ Foreground Services must specify valid `foregroundServiceType` in the Manifest and handle start restrictions gracefully.
6. **Room Database & Migrations**:
   - Any modification to an `@Entity` class or `@Database` schema MUST increment the database `version` and supply an explicit `Migration(from, to)` registered via `addMigrations(...)`.
7. **Blast Radius & Contract Integrity**:
   - Check all usages across the codebase before altering public function signatures, ViewModel contracts, or navigation arguments.
8. **Mandatory Architectural KDoc Documentation**:
   - Every newly created or refactored Repository interface method, UseCase class & `invoke()`, ViewModel public state/events contract, and DataSource method MUST proactively include standard, meaningful KDoc (`/** ... */`) documenting its architectural purpose, `@param` parameters, `@return` value, and `@throws` exceptions (if any).
   - KDoc must document business intent and contract boundaries clearly (never generate bare uncommented domain/data layers).
9. **Mandatory Base ViewModel Inheritance**:
   - When the project defines a standardized Base ViewModel (e.g. `MVIViewModel<S, E, A>` or `BaseViewModel` documented in `architecture-guidelines.md`), all new and refactored feature ViewModels MUST inherit directly from that Base Class.
   - Strictly prohibit creating ad-hoc, reinvented state/event pipelines (`_uiState = MutableStateFlow`, custom Channel emitters) from scratch when a central base class exists.

---

### New production code

- New UI: Jetpack Compose unless the surrounding screen is XML and the developer did not ask to convert it.
- Typography: `MaterialTheme.typography.*` only.
- One-shot UI effects: never sticky `MutableLiveData`. Consume-to-null, `Channel`/`sendEvent()`, or `SharedFlow`.
- Strings: `values/strings.xml` **and** `values-ar/strings.xml`. No hardcoded user-facing text.

---

## 2) Parallel Review Fan-Out (the only delivery gate)

Required after any non-trivial implementation (UI, state/lifecycle, payment, networking, database, running/sensors, streak, ads/privacy, refactor, multi-file, new Kotlin).

### Stage 0: Narrow skip (reviews only)

Skip the **5 review leaves** only when the working tree is strictly:

1. Documentation (`*.md`, `*.txt`), or
2. Version-number-only bumps in `gradle/libs.versions.toml`, or
3. String-only edits in `values/strings.xml` + `values-ar/strings.xml` with no Kotlin/layout/ViewModel changes — still run `python .agents/scripts/check_strings.py`.

This skip is not a token optimization. Code changes never skip reviews.

### Stage 0.5: Pre-Review Test Quality Gate (Mandatory for test diffs)

If the package diff contains any modified or newly created unit/UI test files (`*Test.kt` or `src/test/`):

1. Dispatch `test-quality-reviewer-agent` in a dedicated pre-review invocation.
2. The reviewer audits:
   - **Assertion Depth**: $\ge 2$ meaningful assertions per `@Test` (no `assertTrue(true)` or empty checks).
   - **Coroutines Concurrency**: Use of `StandardTestDispatcher` with `advanceUntilIdle()` or `Turbine` for Flow assertion.
   - **Mock Isolation**: Pure Fakes or explicit `coEvery` definitions with `@After` teardown.
   - **Zero Test Stubs**: No placeholder tests or empty stubs.
3. Advance to Stage 1 only upon receiving `TEST_PASS`. If findings are returned, fix test assertions before triggering the 5-leaf gate.

### Stage 1: One tool call, parallel leaves (with Smart Test Promotion & Silent Wait)

From repo root:

0. **Shift-Left Test & Lint Pre-Gate**: When code or unit tests are touched, ALWAYS run BOTH before requesting review packages:
   a. `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest` (Compiler, signature parity & unit tests — permitted before review as a pre-gate).
   b. `python .agents/scripts/fast_kt_lint.py` (Diff-Scoped Fast Kotlin Lint: catches `!!`, `TODO` stubs, `runBlocking` in tests, inline FQCNs on modified/added lines without penalizing untouched legacy code).
   *Fix any compiler or lint issues BEFORE generating the review package. `review_package.py` strictly validates lint and will refuse package generation on lint violations.*
1. `python .agents/scripts/review_package.py` (optional paths). Use the printed `HARNESS_REVIEW_PACKAGE=`.
2. **Smart Test Promotion & Parallel Dispatch**:
   - **Non-test diff (pure production code)**: Dispatch **all 5** standard review leaves in **exactly one** `invoke_subagent` call with `Subagents: [...]`: `bug-reviewer-agent`, `convention-reviewer-agent`, `security-reviewer-agent`, `perf-anr-guardian-agent`, and `regression-impact-reviewer-agent`.
   - **Test diff (touches `*Test.kt`, `src/test/`, `src/androidTest/`)**: **`test-quality-reviewer-agent` is automatically promoted to a mandatory 6th reviewer**. Dispatch **all 6** leaves together in **exactly one** `invoke_subagent` call.
   - Same package path in every Prompt. `Workspace="inherit"`. Write tools off.
3. **SILENT REVIEW WAIT (Zero Chat Noise)**:
   - When subagents are running in the background, the Lead Agent **MUST REMAIN COMPLETELY SILENT in chat** upon receiving intermediate notifications (e.g. do NOT output *"Waiting for 4 remaining..."* or *"Waiting for 3 remaining..."*).
   - The IDE interface natively displays live progress cards and spinners for each subagent.
   - Output a single, consolidated, professional summary in chat **ONLY when all subagents have finished and all verdicts are in context**.
4. Collect verdicts. BLOCKER/MAJOR → output Review Round Summary Card in chat -> fix at the producer -> verify with `fast_kt_lint.py` -> regenerate the package -> dispatch the same leaves again. Identical package content is rejected; the diff must change.
5. Advance only when all required leaves return their PASS tokens: `BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS` (+ `TEST_PASS` when test files are touched).

Never fire separate `invoke_subagent` calls. That burns the round counter and is denied.

Optional sixth slot in non-test diffs: `qa-diagnostics-agent` or `android-ui-expert-agent`.

---

## 3) Preflight Gate, Build, Install, Launch

Only after the 5 leaves have finished (all 5 PASS):

1. `python .agents/scripts/preflight_check.py` — **Mandatory Preflight Quality Gate** (verifies string parity, Room migrations, and fast Kotlin lint).
   - **STRICT PREFLIGHT INVARIANT**: If `preflight_check.py` returns exit code 1 (`[FAIL]`), the agent is **STRICTLY PROHIBITED from running `:app:assembleDebug` or delivering**. The agent MUST fix all string/lint/Room issues or halt and report them to the developer.
2. `python .agents/scripts/run_gradle_task.py :app:assembleDebug`. Wait for `BUILD SUCCESSFUL` from **this** command. Daily work is **debug**. Do not install a leftover APK. Do **not** run raw `gradlew.bat` from the agent — the Python runner streams executing tasks and a 10s heartbeat so the task log is not empty during compile.
3. Live Device Install & Launch: `python .agents/scripts/run_device.py install-start`.
   - **APK Freshness & Stale Build Barrier**: `run_device.py` and `run_e2e_smoke.py` automatically verify that the target APK is strictly newer than all repository code/resource files and build configurations via `_apk_freshness.py`. If source files were touched after the APK was built or if git HEAD moved past the last assemble gate, installation is **immediately rejected with exit code 1**, forcing a fresh `:app:assembleDebug` compile before any bytecode reaches the device.
4. **Final Verdict Artifact**: after every gate (unit tests, preflight, assemble, device, E2E, 5 leaves), run `python .agents/scripts/final_verdict.py`. It aggregates the per-gate result artifacts (`.agents/state/results/*.json`) and the review verdict records into `.agents/state/last_verdict.json`:
   - `APPROVED` — every gate PASS and the 5-leaf verdict is APPROVED for the same tree fingerprint; required before delivery.
   - `ENV_BLOCKED` — a gate failed environmentally; exit 30 halt protocol (never edit code to bypass).
   - `STALE` — code changed after the review package was generated; regenerate the package and re-run the 5 leaves.
   - `EXPIRED` — the review round expired via the barrier TTL; re-dispatch the 5 leaves.
   - `BLOCKED` — a required gate FAIL/MISSING, an artifact predates the current HEAD, or the checkout has no git HEAD.
   - CI must re-run the gates itself and never trust the local artifact file.

Helpers: `python .agents/scripts/capture_screen.py` and `python .agents/scripts/logcat_doctor.py` (optional `--device <serial>`).

---

## 4) Device Verification & Phase Pipeline (`DEVICE_VERIFICATION_MODE` in `_product.py`)

- **Phase Quality Pre-Gate & Checkpoint Commit Invariant**:
  - In multi-phase refactors or features, execute strictly phase-by-phase.
  - Before concluding Phase N, the agent MUST run:
    1. `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest`
    2. `python .agents/scripts/preflight_check.py` (Shift-Left validation: guarantees zero lint errors, zero hardcoded string mismatches, and zero Room migration issues before handoff).
    3. `python .agents/scripts/run_gradle_task.py :app:assembleDebug`
    4. `python .agents/scripts/run_device.py install-start` + Device Verification (E2E smoke or manual checklist).
  - **MANDATORY PHASE CHECKPOINT COMMIT & HANDSHAKE**:
    * Upon passing all Phase N gates, output the **Phase Milestone Card** in chat containing verification evidence and a drafted Conventional Commit message for Phase N.
    * **HARD STOP**: The agent **MUST STOP IMMEDIATELY** and wait for the developer to commit Phase N.
    * **STRICT PROHIBITION**: The agent MUST NOT edit, create, open, or start any files for Phase N+1 until the developer explicitly confirms they have committed Phase N and commands the agent to proceed (e.g. *"Start Phase N+1"*).

- **Strict Device Verification & No-Device Halt Policy**:
  - Running on device (`run_device.py install-start`) and smoke testing (`run_e2e_smoke.py` or interactive manual checklist) is an **absolute delivery gate requirement**.
  - **IF NO DEVICE / EMULATOR IS CONNECTED** (when `run_device.py` or `adb devices` reports no devices):
    * The agent is **STRICTLY FORBIDDEN from silently skipping device verification, swallowing the error, or claiming verification passed**.
    * The agent **MUST HALT** and trigger an interactive modal (`ask_question` in the conversation language) or alert the developer in chat:
      > *"No connected Android device or emulator detected. Please connect a physical device or start an emulator to proceed with installation and E2E verification."*
    * The agent must wait for the developer to connect a device or explicitly grant permission to proceed.

- **Dual Device Verification Modes**:
   - **Mode A: `autonomous_e2e` (Autonomous Senior QA E2E Verification - Default)**:
     1. Run `python .agents/scripts/run_device.py install-start`.
     2. **PRE-E2E CONFIRMATION (`E2E_CONFIRM=confirm`)**: Before executing any E2E step, the agent **MUST** ask the developer via `ask_question` (in the active conversation language): *"Start E2E round?"* with options **`Start E2E`** / **`Skip E2E`**, then wait for the choice. If **Skip E2E**, proceed to the Phase Milestone Card and mark device verification explicitly as `skipped by developer` (never silently claim it passed). If **Start E2E**, continue to step 3.
     3. **MANDATORY E2E EXECUTION BY TASK TYPE**:
       - **Primary engine**: `run_e2e_qa.py` is the test-case-aware Senior QA runner. For every phase, derive test cases from the diff (`.agents/workflows/e2e-qa.md`), validate with `run_e2e_qa.py --cases <path> --lint`, then execute `run_e2e_qa.py --cases .agents/e2e_cases/<task>/<phase>.yaml`. `run_e2e_smoke.py` remains a fast diff-aware fallback.
       - **Scenario A (New Features & User Journeys)**: The agent **MUST author and execute a declarative test-case file** in `.agents/e2e_cases/<task>/<phase>.yaml` covering the complete user journey with positive/negative/edge cases (`launchApp`, `tapOn`, `inputText`, `scrollUntilVisible`, `assertVisible`, `assertText`, `assertNotVisible`), capturing screenshots for every major step.
       - **Scenario B (UI Bugfixes & Screen Refactors)**: The agent runs `python .agents/scripts/run_e2e_qa.py` with diff-grounded cases (or `run_e2e_smoke.py` for a fast pass). The diff-aware auto-discovery engine automatically launches modified Activities/Screens directly (`am start -n`), validates visible target texts, asserts clickable buttons, and stress-tests scroll gestures.
       - **Scenario C (Deep Links & Navigation Routing)**: For deep-link or routing changes, the agent executes `python .agents/scripts/run_e2e_smoke.py --target-deeplink <uri>` to verify URI resolution and screen rendering.
       - **Scenario D (Pure Data / Domain / Room / Worker Logic)**: The agent executes standard launch verification to confirm DI (Hilt), Room database schema migrations, and background workers boot cleanly on real Android runtime without Logcat crashes or ANRs.
     4. **Declarative Maestro Flows & In-App Locale Support**: Supports YAML/JSON flows (`.agents/e2e_flows/*.yaml`) compatible with Maestro syntax. Dynamically resolves string keys against `res/values-*/strings.xml` based on in-app locale fingerprinting. Runs via `maestro` CLI if installed or native zero-dependency Python ADB engine.
     5. **Diagnostic Probing Sandbox & Zero-Leakage Barrier**: During bug investigation, temporary diagnostic logs tagged with `// [HARNESS-PROBE]` may be used to observe state flow in Logcat without invoking the 6-leaf review round. All probes MUST be removed before generating `review_package.py`. `fast_kt_lint.py` and `preflight_check.py` strictly reject stray probes with `exit 1` (`STRAY_DIAGNOSTIC_PROBE`).
     6. **Deep Failure Forensics**: On E2E step failure, the engine captures an instant failure screenshot, dumps the UI hierarchy to `.agents/state/e2e/failed_hierarchy.xml`, and extracts the last 50 Logcat lines to `.agents/state/e2e/failed_logcat.txt` with failure classification (`ASSERTION_FAILED`, `RUNTIME_CRASH`, `TIMEOUT_UNRESPONSIVE`).
     7. **On E2E [SUCCESS]**: Output the **Phase Milestone Card** with E2E evidence and Phase N commit message, then stop and await developer commit and instruction to start Phase N+1.
     8. **On E2E [FAIL] / Crash**: STOP immediately, inspect forensics or dispatch `qa-diagnostics-agent`, report findings in chat, fix at root cause, re-run tests, re-install, and re-verify.
  - **Mode B: `interactive_device` / `manual_only` (Developer-in-the-Loop Manual Verification)**:
    1. Run `python .agents/scripts/run_device.py install-start`.
    2. Output the **Phase Milestone Card** with numbered manual smoke test steps and Phase N commit message.
    3. Trigger interactive verification via `ask_question`:
       - **Question**: "Please test the steps above on your device and confirm the result:"
       - **Options**: `PASS — Device testing passed successfully` / `FAIL — Issue or crash encountered on device`.
    4. Upon PASS, wait for the developer to commit Phase N and give the green light for Phase N+1.
  - **Mode C: `disabled`**:
    1. Proceeds to Phase N Milestone Card after Unit Tests (`:app:testDebugUnitTest`) + `preflight_check.py` + `:app:assembleDebug`, then stops and awaits developer commit.

- **Phase Milestone Card Requirements**:
  1. Scope & Changes.
  2. Quality Gates (`5-Leaf Review Gate`, `Unit Tests`, `preflight_check.py` PASS, `:assembleDebug` BUILD SUCCESSFUL).
  3. Device Verification Evidence (`Autonomous E2E Smoke Test` results or manual checklist).
  4. Drafted Conventional Commit message for Phase N.
  5. Clear message that the agent is waiting for developer commit before beginning Phase N+1.

- **Single-Phase Task Completion / Final Sign-off**:
  - When all phases are completed and verified on device:
    1. Write `.agents/state/plans/walkthrough.md`
    2. Final Task Summary in chat: what / why / files / gates (`*_PASS` + `BUILD SUCCESSFUL`)
    3. Conventional Commit message for Android Studio
    4. If the work came from a Zoho id: one-line reminder that Zoho is not updated — wait for `update zoho`. No modal.
    5. Never present the commit message before every phase is Pass.

---

## 5) Zoho

Same Sprints workflow as the original engine. Playbook: `.agents/workflows/zoho-sprints.md`. Credentials stay in the user-level config — never copy tokens into the repo.

- Never mutate Zoho unless the developer explicitly says to (for example `update zoho` or when implementation plan is approved to move to `In progress`).
- Allowed statuses: `In progress` when started; `Ready To ReTest` when verified. Never `Done` / `Solved`.
- **Status Change at Work Start**: When implementation plan is approved and coding begins, transition status to `In progress` silently without posting comments.
- **Description vs. Comment Placement Policy (`update zoho`)**:
  - **Bug Items**: Post the full QA delivery report exclusively as a **Comment**. **NEVER modify or overwrite the Bug Description** (to strictly preserve the original QA report, environment info, and reproduction steps).
  - **Task / Story / Sub-task / Improvement Items**: Write or update the full delivery report in the **Description** (as the permanent record of feature scope). Post a short comment with `Commit: <hash>`.
- **Zoho Quality & Communication Policy (QA-Centric)**:
  - **Audience**: Descriptions and comments are written exclusively for **QA / Testers and Product Stakeholders**.
  - **No Technical Code Internals**: Strictly prohibit raw code artifacts (e.g. no XML layout file names like `fragment_food_plan.xml`, no Kotlin source files, no XML attributes like `clipToPadding`, no framework class names, no raw `dp`/`px` numbers unless part of product design specs). Describe issues and solutions in **clear, functional, and user-facing terms**.
  - **Mandatory Commit Hash**: The first line MUST always be `Commit: <hash>` (retrieved via `git log -1 --format=%h` or provided by developer).
  - **Mandatory Sections for ALL Zoho items** (Bugs, Features, Tasks, Stories, Improvements):
    1. `Commit: <hash>`
    2. **سبب المشكلة / الهدف من المهمة** (Functional root cause or business goal).
    3. **الحل / ما تم تنفيذه** (Functional solution and UI behavior changes).
    4. **نطاق التأثير** (`Impact Area / Blast Radius` — list screens, related features, and flows QA must verify for regression).
    5. **خطوات الفحص وحالات الاختبار** (`Test Cases & Verification Steps` — explicit positive, negative, and edge scenarios).
- **Zoho Language Policy**:
  - Per `_product.py` (`ZOHO_LANGUAGE = "en_titles_ar_comments"` by default):
    - **Task Titles**: MUST be in **English** (e.g. `Ras-I725: Fix Scroll in Food Plan Screen`). Never put developer or assignee names in titles.
    - **Task Descriptions & Comments**: Written in **Arabic** (human tone, QA-centric, no emoji, no internal engine tokens), starting with the commit hash `Commit: <hash>`.
    - If `ZOHO_LANGUAGE = "all_en"`, use English for titles, descriptions, and comments. If `all_ar`, use Arabic for all.
- Assignment: the default user from MCP workflow defaults. No name in titles. New items use the default Sprints assignee (overridable in the user config).
- **If Zoho MCP tools are not available in this session**, do not invent ticket fields. Ask the developer to paste the ticket or enable Zoho. Continue local implementation using what they provide.
- This checkout wires **Zoho Sprints only** through `.agents/mcp_config.json` to `.agents/mcp/zoho_sprints/server.py`. **Zoho Desk is not used.** Do not invoke Desk tools, do not add a Desk MCP server, and do not treat Desk ticket numbers as Sprints item ids.
- Bug id ingestion: fetch if tools exist, check and list any attached screenshots/logs (`attachments`), explain in chat, start analysis. Still write a plan for non-trivial bugs and request approval.
- Feature task id: fetch, check attachments, explain, then ask whether to start the plan.
- Templates for comments/descriptions: Follow `.agents/workflows/zoho-sprints.md` strictly (Commit / السبب أو الهدف / الحل / نطاق التأثير / خطوات الفحص وحالات الاختبار).
- Other trackers (GitHub Projects via gh CLI; Jira / Linear via upstream MCP): the same section-5 policy applies with provider-specific status labels and trigger phrases — see `.agents/scripts/pm_policy.py` (status maps, handoff validation) and `.agents/pm/mcp_registration.*.md`; full playbook in the kit repository at `docs/workflows/pm-integrations.md`.


---

## 6) High-Signal Chat, Zero-Noise UI & Anti-Spam Governance

To preserve a clean, professional, and readable IDE chat interface, the agent must distinguish between ephemeral tool widgets and permanent chat prose:

1. **Tool Execution Widgets (Ephemeral / Collapsed)**:
   - Command runs (`run_gradle_task.py`, `fast_kt_lint.py`, `review_package.py`) and file operations are rendered by the IDE as collapsible badges (`Worked for 15s >`, `Ran command >`).
   - The agent MUST NOT narrate routine tool executions in permanent chat prose (e.g. NEVER write *"Running all unit tests to ensure complete stability..."*, *"Cleaning stale kapt cache..."*, *"Re-running tests with fresh task execution..."*, *"Reading file..."*).

2. **Silent Intermediate Review Wait (Zero Chat Noise)**:
   - When a 5-leaf review round or background tasks are in-flight, the agent receives intermediate reactive notifications as individual subagents finish.
   - On EVERY intermediate wakeup where not all 5 verdicts are present, the agent **MUST OUTPUT AN EMPTY STRING (`""`) AND CALL NO TOOLS**, ending the turn instantly and silently.
   - NEVER output status countdowns or waiting narrations (e.g. NEVER write *"Waiting for Bug Reviewer to finalize its verdict..."*, *"Reviewers are completing their final evaluations..."*, *"Waiting for remaining reviewers to complete their evaluations..."*).

3. **The 4 Permitted Conversational Touchpoints**:
   Permanent chat prose is reserved strictly for high-signal engineering milestones:
   - **Touchpoint 1: Plan Presentation & Approval**: `implementation_plan.md` artifact presentation before starting non-trivial work.
   - **Touchpoint 2: Review Round Summary Card**: EXACTLY ONE structured card emitted when all 5 (or 6) reviewers finish (detailing findings and corrective fixes on findings, or listing the clean PASS verdicts when all reviewers clear the diff).
   - **Touchpoint 3: Phase Milestone Card**: Verification evidence, automated E2E results, and phase progression cards upon completing a milestone.
   - **Touchpoint 4: Final Task Delivery**: Final walkthrough summary, verification evidence, and Conventional Commit draft.

4. **Review Churn & Fast Convergence**:
   - When addressing review findings, the agent must fix all findings across all 5 pillars comprehensively in a single pass.
   - Empirically verify with `testDebugUnitTest` and `fast_kt_lint.py` before re-dispatching.
   - Review rounds MUST converge in at most 3 rounds. High round churn (e.g. Round 5, Round 6, Round 7) is strictly prohibited.
   - **Round tracking is programmatic**: `review_package.py` records every generated package as a round for the task (task id from `--task` / `HARNESS_TASK_ID`, ledger in `.agents/state/review_rounds.json`; counters reset when HEAD moves after the developer commits). At the round cap (3, override `HARNESS_MAX_REVIEW_ROUNDS`), package generation prints a `REVIEW ROUND CAP` warning and the reminder injects an escalation note — the agent MUST present a Review Round Summary Card and ask the developer to choose: continue one more round / roll back the last fixes / stop the task. Never silently loop.

5. **Conversation Language Parity Across All Developer Touchpoints**:
   - The agent MUST dynamically match the active conversation language of the developer across ALL cards, interactive modals, and summaries:
     * **Interactive Modals (`ask_question`)**: Questions, choices, and explanations must match the developer's language (mirror whatever language they write in).
     * **Review Round Summary Cards**: Summary of findings and corrective fixes or clean PASS verdicts rendered in the active conversation language.
     * **Phase Milestone Cards**: Scope, verified evidence, manual smoke test steps, and waiting status rendered in the active conversation language.
     * **Final Delivery**: Task overview, file changes, and walkthrough rendered in the active conversation language (while keeping Conventional Commit format in English).

6. **Background Tasks, Sequential Dependencies & Anti-Hallucination Invariant**:
   - When launching asynchronous background commands (`run_command`, Gradle tasks, preflight checks, device install, E2E smoke):
   - **MANDATORY HUMAN-READABLE PROTOCOL**: The agent may proceed silently (`""`) or emit a short, clean status line in plain text (e.g. `Running unit tests in background...`, `Assembling debug APK...`, `Awaiting code review verdicts...`).
   - The agent is **STRICTLY PROHIBITED** from printing raw technical task IDs (e.g. NEVER print `fd98ab26.../task-1004`) or robotic justification sentences (e.g. NEVER write *"Output text must be strictly empty"*, *"Stopped calling tools to wait..."*, or *"An intermediate reviewer has reported"*).
   - **STRICT PROHIBITION ON FAKE SYSTEM MESSAGES (`<MESSAGE_RECEIVED>`)**: The agent **MUST NEVER** fabricate, simulate, inject, or write `<MESSAGE_RECEIVED>`, `<SYSTEM_MESSAGE>`, or assume task completion in thoughts or chat prose.
   - **SEQUENTIAL DEPENDENCY INVARIANT**: When the next step in the pipeline depends on the current background task finishing (e.g. `:assembleDebug` must complete before `run_device.py install-start`; `install-start` must complete before `run_e2e_smoke.py`), the agent **MUST STOP CALLING TOOLS IMMEDIATELY**. Never invoke dependent tools concurrently. The agent must wait passively for the genuine platform `<SYSTEM_MESSAGE>` notifying task completion (`finished with result:`) before dispatching the next dependent step.

---

## Skills (read on demand)

- `android-harness` and its `references/` — architecture, Compose, Room, performance, checkout facts
- `brainstorming` — requirements exploration & architectural trade-offs
- `test-driven-development` — strict Red-Green-Refactor test-first development
- `systematic-debugging` — root-cause hypothesis isolation
- `compose-inspector` — Compose performance, recomposition, stability & RTL
- `kotlin-coroutines-expert` — structured concurrency & Flow dispatchers
- `gradle-build-optimizer` — daemon, build cache & speed optimization
- `git-pr-automator` — commit **message** format only
- Zoho Sprints playbook: `.agents/workflows/zoho-sprints.md` (mutate only on `update zoho`)
- Senior-QA E2E testing: `.agents/workflows/e2e-qa.md` (derive + run test cases via `run_e2e_qa.py`)
