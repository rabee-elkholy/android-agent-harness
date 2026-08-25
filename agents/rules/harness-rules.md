---
trigger: always_on
---

# this Android app — Quality-First Multi-Agent Delivery Rules

Single source of truth for AI work in this checkout. Skills are domain knowledge. Workflows are short pointers back here. If a workflow, skill, or reminder disagrees with this file, this file wins.

The developer works **locally** in their IDE on this checkout. The agent never uses Git worktrees, never commits, and never opens PRs.

Every subagent must use `model="inherit"`. Never pin `flash`/`pro` to a different SKU.

---

## Quality-First & Clarification

- **Answer First, Then Ask**: If the developer asks anything, answer in visible chat first. Only then may you call `ask_question` for a pending device phase or tradeoff. Never fire a bare modal that ignores the question.
- **Language Policy**:
  - **Engineering & System Language**: Per `_product.py` (`CHAT_LANGUAGE = "en"` by default): All reasoning, chat responses, implementation plans (`implementation_plan.md`), walkthroughs (`walkthrough.md`), subagent review findings, and Conventional Commit drafts MUST be written in **clear, standard English** to ensure technical precision and prevent RTL/LTR formatting issues. If `CHAT_LANGUAGE = "mirror"`, strictly mirror the developer's language (English if addressed in English, Arabic if addressed in Arabic).
  - **`ask_question` Modals**: Prompts and options must follow `CHAT_LANGUAGE` (English by default, or mirror developer language).
- **`(Recommended)`**: Only for technical / architectural tradeoffs. Forbidden on Pass/Fail device results, plan approval, and simple confirmations.
- **Native Artifact Planning & Approval**: Implementation plans MUST be written as user-facing artifacts (`implementation_plan.md`) with `ArtifactMetadata: { UserFacing: true, RequestFeedback: true }`. This natively renders the interactive **"Proceed"** button in the chat interface. **Never call `ask_question` for plan approval**; stop calling tools and wait for the developer to approve via the **Proceed** button or provide feedback in chat.
- **`ask_question` is strictly reserved for**:
  1. **Design / architectural tradeoffs** when requirements are ambiguous. `(Recommended)` is allowed here.
  2. **One manual device-verification phase at a time**:
     - `Phase passed` / `Phase failed` / `Retest / I need help`
- **Clean chat**: No filler per tool step. Never echo `<SYSTEM_MESSAGE>`, raw Gradle dumps, or internal task dumps. Speak when answering, presenting a plan, presenting one device phase, or delivering the final summary.
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

## 1) Inspect, Plan, Implement

- Read `android-harness/SKILL.md` and any matching domain reference before non-trivial work.
- Inspect with `grep_search` / `view_file` before editing. Do not guess symbols.
- Smallest change that matches **the files you opened**. Do not convert an XML screen to Compose to fix a bug unless asked.
- **MANDATORY PLANNING**: Any new feature, new screen, new schema/table, or multi-file change MUST create an `implementation_plan.md` artifact (`ArtifactMetadata: { UserFacing: true, RequestFeedback: true }`) and obtain developer approval (via the native interactive **Proceed** button or chat approval) BEFORE modifying or creating production code. Do NOT fire an `ask_question` modal for plan approval; let the native artifact Proceed action handle it. Do not start coding before plan approval.
- Large work (>3–4 files, or a shared ViewModel / service): split into milestones (data → domain → state → UI). One milestone per increment. No 10-file big-bang turns.
- Bugs: 2–3 explicit hypotheses, trace data flow, fix the producer.
- TDD when it protects real logic. No placeholder tests.

---

## Shift-Left Quality Invariants (Pre-Implementation Guard)

Before writing or modifying any code, the Lead Agent must proactively verify compliance with all 6 quality pillars to achieve **first-pass review approval** and avoid review rejection rounds:

1. **Null-Safety & Network Resiliency**:
   - Never use `!!` on nullable types or unvetted platform types.
   - All network/remote calls in coroutines must safely handle `IOException`, `SocketTimeoutException`, `UnknownHostException` (e.g. via `runCatching` or explicit `Result` wrapping).
   - ViewModels must expose clear error states to the UI with retry mechanisms; never swallow network failures silently.
2. **Clean Architecture & Import Hygiene**:
   - Strict Unidirectional Data Flow (MVI StateFlow as the single source of truth).
   - **STRICTLY ZERO INLINE FQCNs**: Never use inline package paths (e.g. `androidx.compose...`). Always import at the top and use typealiases (`as CoreState`, `as CoreAction`) to resolve collisions.
3. **Accessibility & Jetpack Compose Standards**:
   - Every `Image`, `Icon`, and `IconButton` MUST specify a meaningful `contentDescription` (or explicit `null` only if decorative).
   - Clickable UI components must have a minimum touch target size of 48dp (`Modifier.minimumInteractiveComponentSize()` or `>= 48.dp`).
   - Every new or modified Compose component MUST have dedicated dual-locale `@Preview` (Arabic RTL `locale = "ar"` & English LTR `locale = "en"`) wrapped in the app theme. Screens also require Loading, Empty, and Error previews.
4. **Performance, Battery & Sensor Life**:
   - Strictly zero disk I/O, database access, or JSON parsing on `Dispatchers.Main`.
   - Any `SensorEventListener` (pedometer, accelerometer, GPS) MUST be unregistered in `onPause()`, `onStop()`, or `DisposableEffect.onDispose`.
   - Android 14+ Foreground Services must specify valid `foregroundServiceType` in the Manifest and handle start restrictions gracefully.
5. **Room Database & Migrations**:
   - Any modification to an `@Entity` class or `@Database` schema MUST increment the database `version` and supply an explicit `Migration(from, to)` registered via `addMigrations(...)`.
6. **Blast Radius & Contract Integrity**:
   - Check all usages across the codebase before altering public function signatures, ViewModel contracts, or navigation arguments.

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

### Stage 1: One tool call, five leaves

From repo root:

1. `python .agents/scripts/review_package.py` (optional paths). Use the printed `HARNESS_REVIEW_PACKAGE=`.
2. Dispatch **all 5** in **exactly one** `invoke_subagent` with `Subagents: [...]`. Same package path in every Prompt. `Workspace="inherit"`. Write tools off.
3. Stop calling tools. Do not poll `transcript.jsonl`. Do not run lint/tests/assemble while they run.
4. Collect verdicts. BLOCKER/MAJOR → fix at the producer → regenerate the package → dispatch the same 5 again. Identical package content is rejected; the diff must change.
5. Advance only when all five returned `BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`.

Never fire five separate `invoke_subagent` calls. That burns the round counter and is denied.

Optional sixth slot in the same invoke: `qa-diagnostics-agent`, `android-ui-expert-agent`, or `test-quality-reviewer-agent`.

---

## 3) Lint, Tests, Build, Install, Launch

Only after the 5 leaves have finished (PASS, not still running):

1. `python .agents/scripts/fast_kt_lint.py` — dual-locale `@Preview` is required on Compose `*Screen.kt`, `*Card.kt`, `*Dialog.kt`, `*BottomSheet.kt`, `*Sheet.kt`, and `*Banner.kt`. Screens also need Loading/Empty/Error.
2. Targeted tests: If test files (`*Test.kt`) were modified or added, audit test quality via `test-quality-reviewer-agent`. Run `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest --tests "..."` when this checkout has unit tests. Use this module, not a leftover test path.
3. `python .agents/scripts/run_gradle_task.py :app:assembleDebug`. Wait for `BUILD SUCCESSFUL` from **this** command. Daily work is **debug**. Do not install a leftover APK. Do **not** run raw `gradlew.bat` from the agent — the Python runner streams executing tasks and a 10s heartbeat so the task log is not empty during compile.
4. `adb devices` — physical serial only.
5. `python .agents/scripts/run_device.py install-start` (live adb install + launch). Equivalent: `adb -s <DEVICE_ID> install -r -d app/build/outputs/apk/debug/app-debug.apk` then `adb -s <DEVICE_ID> shell am start -n <APPLICATION_ID>/<LAUNCHER_ACTIVITY>`.

Helpers: `python .agents/scripts/capture_screen.py` and `python .agents/scripts/logcat_doctor.py` (optional `--device <serial>`). Both reject emulators.

---

## 4) Manual Device Verification & Sign-off

- Short phases: Happy path, then edge/offline, then RTL/orientation, then lifecycle/re-entry. **One phase per `ask_question`.**
- On Fail: ask for symptoms in chat (not a modal). Do not guess. For crashes, offer `qa-diagnostics-agent` + `logcat_doctor.py`. Then fix producer, re-run gates, re-install, re-present the **same** phase.
- After **every** phase is Pass:
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

## Skills (read on demand)

- `android-harness` and its `references/` — architecture, Compose, Room, performance, checkout facts
- `kotlin-coroutines-expert`
- `systematic-debugging`
- `compose-inspector`
- `gradle-build-optimizer`
- `git-pr-automator` — commit **message** format only
- Zoho Sprints playbook: `.agents/workflows/zoho-sprints.md` (mutate only on `update zoho`)
