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

### Stage 1: One tool call, five leaves (with Silent Review Wait)

From repo root:

0. **Shift-Left Test & Lint Pre-Gate**: When code or unit tests are touched, ALWAYS run BOTH before requesting review packages:
   a. `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest` (Compiler, signature parity & unit tests — permitted before review as a pre-gate).
   b. `python .agents/scripts/fast_kt_lint.py` (Diff-Scoped Fast Kotlin Lint: catches `!!`, `TODO` stubs, `runBlocking` in tests, inline FQCNs on modified/added lines without penalizing untouched legacy code).
   *Fix any compiler or lint issues BEFORE generating the review package. `review_package.py` strictly validates lint and will refuse package generation on lint violations.*
1. `python .agents/scripts/review_package.py` (optional paths). Use the printed `HARNESS_REVIEW_PACKAGE=`.
2. Dispatch **all 5** in **exactly one** `invoke_subagent` with `Subagents: [...]`. Same package path in every Prompt. `Workspace="inherit"`. Write tools off.
3. **SILENT REVIEW WAIT (Zero Chat Noise)**:
   - When subagents are running in the background, the Lead Agent **MUST REMAIN COMPLETELY SILENT in chat** upon receiving intermediate notifications (e.g. do NOT output *"Waiting for 4 remaining..."* or *"Waiting for 3 remaining..."*).
   - The IDE interface natively displays live progress cards and spinners for each subagent.
   - Output a single, consolidated, professional summary in chat **ONLY when all 5 subagents have finished and all verdicts are in context**.
4. Collect verdicts. BLOCKER/MAJOR → output Review Round Summary Card in chat -> fix at the producer -> verify with `fast_kt_lint.py` -> regenerate the package -> dispatch the same 5 again. Identical package content is rejected; the diff must change.
5. Advance only when all five returned `BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`.

Never fire five separate `invoke_subagent` calls. That burns the round counter and is denied.

Optional sixth slot in the same invoke: `qa-diagnostics-agent`, `android-ui-expert-agent`, or `test-quality-reviewer-agent`.

---

## 3) Preflight Gate, Build, Install, Launch

Only after the 5 leaves have finished (all 5 PASS):

1. `python .agents/scripts/preflight_check.py` — **Mandatory Preflight Quality Gate** (verifies string parity, Room migrations, and fast Kotlin lint).
   - **STRICT PREFLIGHT INVARIANT**: If `preflight_check.py` returns exit code 1 (`[FAIL]`), the agent is **STRICTLY PROHIBITED from running `:app:assembleDebug` or delivering**. The agent MUST fix all string/lint/Room issues or halt and report them to the developer.
2. `python .agents/scripts/run_gradle_task.py :app:assembleDebug`. Wait for `BUILD SUCCESSFUL` from **this** command. Daily work is **debug**. Do not install a leftover APK. Do **not** run raw `gradlew.bat` from the agent — the Python runner streams executing tasks and a 10s heartbeat so the task log is not empty during compile.
3. Live Device Install & Launch: `python .agents/scripts/run_device.py install-start`.

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
  - **Mode A: `autonomous_e2e` (Autonomous E2E Verification - Default)**:
    1. Run `python .agents/scripts/run_device.py install-start`.
    2. **MANDATORY**: Run `python .agents/scripts/run_e2e_smoke.py`. The E2E engine inspects the UI hierarchy, asserts component visibility and scroll responsiveness, verifies zero fatal crashes in Logcat, and captures a verification screenshot to `.agents/state/screenshots/`.
    3. **On E2E [SUCCESS]**: Output the **Phase Milestone Card** with E2E evidence and Phase N commit message, then stop and await developer commit and instruction to start Phase N+1.
    4. **On E2E [FAIL] / Crash**: STOP immediately, capture Logcat via `logcat_doctor.py` or dispatch `qa-diagnostics-agent`, report findings in chat, fix at root cause, re-run tests, re-install, and re-verify.
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

- Never mutate Zoho unless the developer explicitly says to (for example `update zoho`).
- Allowed statuses: `In progress` when started; `Ready To ReTest` when verified. Never `Done` / `Solved`.
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
   - **Touchpoint 2: Review Round Summary Card**: EXACTLY ONE structured table emitted when all 5 reviewers finish and findings require corrective action.
   - **Touchpoint 3: Phase Milestone Card**: Verification evidence, automated E2E results, and phase progression cards upon completing a milestone.
   - **Touchpoint 4: Final Task Delivery**: Final walkthrough summary, verification evidence, and Conventional Commit draft.

4. **Review Churn & Fast Convergence**:
   - When addressing review findings, the agent must fix all findings across all 5 pillars comprehensively in a single pass.
   - Empirically verify with `testDebugUnitTest` and `fast_kt_lint.py` before re-dispatching.
   - Review rounds MUST converge in at most 2 rounds. High round churn (e.g. Round 5, Round 6, Round 7) is strictly prohibited.

5. **Conversation Language Parity Across All Developer Touchpoints**:
   - The agent MUST dynamically match the active conversation language of the developer across ALL cards, interactive modals, and summaries:
     * **Interactive Modals (`ask_question`)**: Questions, choices, and explanations must match the developer's language (mirror whatever language they write in).
     * **Review Round Summary Cards**: Summary of findings and corrective fixes rendered in the active conversation language.
     * **Phase Milestone Cards**: Scope, verified evidence, manual smoke test steps, and waiting status rendered in the active conversation language.
     * **Final Delivery**: Task overview, file changes, and walkthrough rendered in the active conversation language (while keeping Conventional Commit format in English).

6. **Background Tasks & Zero-Noise Tool Notice Handling**:
   - When launching asynchronous background commands (`run_command`, Gradle tasks, preflight checks), the IDE engine may prompt: `YOU MUST TAKE ONE OF THE FOLLOWING TWO ACTIONS: A) either proceed to other relevant work or B) simply update the user with a short message...`.
   - **MANDATORY OPTION A PROTOCOL**: The agent **MUST ALWAYS CHOOSE OPTION A** (proceed silently with other work or end the turn with zero chat text `""`).
   - The agent is **STRICTLY PROHIBITED** from choosing Option B and writing status announcements in chat (e.g. NEVER write `# Background Task Started`, *"The Gradle build has been started in the background..."*, or *"Preflight checks have been started in the background..."*). The IDE's native tool execution badge already displays running status to the developer.

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
