---
trigger: always_on
---

# this Android app — Quality-First Multi-Agent Delivery Rules

Single source of truth for AI work in this checkout. Skills are domain knowledge. Workflows are short pointers back here. If a workflow, skill, or reminder disagrees with this file, this file wins.

The developer works **locally** in their IDE on this checkout. The agent never uses Git worktrees, never commits, and never opens PRs.

Every subagent must use `model="inherit"`. Never pin `flash`/`pro` to a different SKU.

---

## Quality-First & Clarification

- **Answer First, Then Ask**: If the developer asks anything, answer in visible chat first. Only then may you call `ask_question` for a pending plan or device phase. Never fire a bare modal that ignores the question.
- **Language**: `ask_question` prompts and options MUST match the developer's language. Translate the English options below when the conversation is not English.
- **`(Recommended)`**: Only for technical / architectural tradeoffs. Forbidden on Pass/Fail device results, plan approval, and simple confirmations.
- **`ask_question` is only for**:
  1. **Plan approval** after writing `.agents/state/plans/implementation_plan.md`. Put a clickable link and highlights in chat first.
     - `Approve the plan and start implementation` / `I have notes or changes to the plan`
  2. **Design tradeoffs** when requirements are ambiguous. `(Recommended)` is allowed here.
  3. **One device-verification phase at a time**:
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

---

## 1) Inspect, Plan, Implement

- Read `android-harness/SKILL.md` and any matching domain reference before non-trivial work.
- Inspect with `grep_search` / `view_file` before editing. Do not guess symbols.
- Smallest change that matches **the files you opened**. Do not convert an XML screen to Compose to fix a bug unless asked.
- **MANDATORY PLANNING**: Any new feature, new screen, new schema/table, or multi-file change MUST create `.agents/state/plans/implementation_plan.md` and obtain developer approval via `ask_question` BEFORE modifying or creating production code. Do not start coding before plan approval.
- Large work (>3–4 files, or a shared ViewModel / service): split into milestones (data → domain → state → UI). One milestone per increment. No 10-file big-bang turns.
- Bugs: 2–3 explicit hypotheses, trace data flow, fix the producer.
- TDD when it protects real logic. No placeholder tests.

### New production code

- New UI: Jetpack Compose unless the surrounding screen is XML and the developer did not ask to convert it.
- Any new or modified Compose UI: dual-locale `@Preview` — Arabic RTL (`locale = "ar"` for AndroidX, or `CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl)` for Compose Multiplatform / KMP) and English LTR (`locale = "en"` or `LayoutDirection.Ltr`). Wrap in this app's theme (or `MaterialTheme` if none). **Screens** also need Loading, Empty, and Error. Cards, dialogs, sheets, and banners need the two locales; they do not need the three state previews.
- New ViewModels: the base required by `architecture-mvi.md` and the files you opened. Data through the same layers those files already use.
- Zero inline FQCNs. Import at the top. Typealias collisions (`as CoreState`, `as CoreAction`, `as CoreEvent`).
- Typography: `MaterialTheme.typography.*` only.
- One-shot UI effects: never sticky `MutableLiveData`. Consume-to-null, `Channel`/`sendEvent()`, or `SharedFlow`.
- Strings: `values/strings.xml` **and** `values-ar/strings.xml`. No hardcoded user-facing text.

---

## 2) Parallel Review Fan-Out (the only delivery gate)

Required after any non-trivial implementation (UI, state/lifecycle, networking, database, refactor, multi-file, new Kotlin).

### Stage 0: Narrow skip (reviews only)

Skip the **5 review leaves** only when the working tree is strictly:

1. Documentation (`*.md`, `*.txt`), or
2. Version-number-only bumps in `gradle/libs.versions.toml`, or
3. String-only edits in `values/strings.xml` + `values-ar/strings.xml` with no Kotlin/layout/ViewModel changes — still run `python .agents/scripts/check_strings.py`.

This skip is not a token optimization. Code changes never skip reviews.

## 2) Preflight Verification & Unit Tests

Before dispatching code to the review gate:

1. `python .agents/scripts/preflight_check.py` — runs fast Kotlin lint, Room database migration checks, and localization string parity.
2. Targeted Unit Tests: `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest` when this checkout has unit tests (`I.15: yes`). Fix any test failures at the source before review.

---

## 3) Five-Leaf Review Delivery Gate

Once the working tree passes preflight and unit tests:

### Stage 1: One tool call, five leaves

From repo root:

1. `python .agents/scripts/review_package.py` (optional paths). Use the printed `HARNESS_REVIEW_PACKAGE=`.
2. Dispatch **all 5** in **exactly one** `invoke_subagent` with `Subagents: [...]`. Same package path in every Prompt. `Workspace="inherit"`. Write tools off.
3. **Stop calling tools immediately.** Antigravity wakes you up automatically via **Reactive Wakeup** when subagents finish. **NEVER** use the `schedule` tool or timers to wait for subagents. Do not poll `transcript.jsonl` or `manage_subagents` in a loop. Do not run assemble while they run.
4. Collect verdicts. BLOCKER/MAJOR → fix at the producer → re-run preflight/tests → regenerate package → dispatch the same 5 again. Identical package content is rejected; the diff must change.
5. Advance only when all five returned `BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`.

Never fire five separate `invoke_subagent` calls. That burns the round counter and is denied.

Optional sixth slot in the same invoke: `qa-diagnostics-agent` **or** `android-ui-expert-agent`, not both.

---

## 4) Build, Install, Launch & Manual Sign-off

Only after the 5 leaves have finished (PASS, not still running):

1. `python .agents/scripts/run_gradle_task.py :app:assembleDebug`. Wait for `BUILD SUCCESSFUL` from **this** command. Daily work is **debug**. Do not install a leftover APK. Do **not** run raw `gradlew.bat` from the agent — the Python runner streams executing tasks and a 10s heartbeat so the task log is not empty during compile.
2. `adb devices` — physical serial only.
3. `python .agents/scripts/run_device.py install-start` (live adb install + launch). Equivalent: `adb -s <DEVICE_ID> install -r -d app/build/outputs/apk/debug/app-debug.apk` then `adb -s <DEVICE_ID> shell am start -n com.example.app/.MainActivity`.

Helpers: `python .agents/scripts/capture_screen.py` and `python .agents/scripts/logcat_doctor.py` (optional `--device <serial>`). Both reject emulators.

---

## 5) Manual Device Verification & Sign-off

- Short phases: Happy path, then edge/offline, then RTL/orientation, then lifecycle/re-entry. **One phase per `ask_question`.**
- On Fail: ask for symptoms in chat (not a modal). Do not guess. For crashes, offer `qa-diagnostics-agent` + `logcat_doctor.py`. Then fix producer, re-run gates, re-install, re-present the **same** phase.
- After **every** phase is Pass:
  1. Write `.agents/state/plans/walkthrough.md`
  2. Final Task Summary in chat: what / why / files / gates (`*_PASS` + `BUILD SUCCESSFUL`)
  3. Conventional Commit message for Android Studio
  4. If the work came from a Zoho id: one-line reminder that Zoho is not updated — wait for `update zoho`. No modal.
  5. Never present the commit message before every phase is Pass.

---

## 6) Zoho Sprints (Task & Project Management)

Same Sprints workflow as the original engine. Playbook: `.agents/workflows/zoho-sprints.md`. Credentials stay in the user-level config — never copy tokens into the repo.

- Never mutate Zoho unless the developer explicitly says to (for example `update zoho`).
- Allowed statuses: `In progress` when started; `Ready To ReTest` when verified. Never `Done` / `Solved`.
- Zoho prose: Arabic, no emoji, human tone, no engine internals, include `git log -1 --format=%h` (developer may paste the hash if HEAD has not moved).
- Assignment: the default user from MCP workflow defaults. No name in titles. New items use the default Sprints assignee (overridable in the user config).
- **If Zoho MCP tools are not available in this session**, do not invent ticket fields. Ask the developer to paste the ticket or enable Zoho. Continue local implementation using what they provide.
- This checkout wires **Zoho Sprints only** through `.agents/mcp_config.json` to `.agents/mcp/zoho_sprints/server.py`. **Zoho Desk is not used.** Do not invoke Desk tools, do not add a Desk MCP server, and do not treat Desk ticket numbers as Sprints item ids.
- Bug id ingestion: fetch if tools exist, explain in chat, start analysis. Still write a plan for non-trivial bugs and request approval.
- Feature task id: fetch, explain, then ask whether to start the plan.
- Templates for comments/descriptions stay as: Commit / سبب المشكلة / الحل / خطوات الفحص (bugs) and Commit / الميزة / الشاشات / حالات الاختبار (features).

---

## 7) Skills (read on demand)

- `android-harness` and its `references/` — architecture, Compose, Room, performance, checkout facts
- `kotlin-coroutines-expert`
- `systematic-debugging`
- `compose-inspector`
- `gradle-build-optimizer`
- `git-pr-automator` — commit **message** format only
- Zoho Sprints playbook: `.agents/workflows/zoho-sprints.md` (mutate only on `update zoho`)
