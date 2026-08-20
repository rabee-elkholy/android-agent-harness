---
trigger: always_on
---

# Rashaqa Android — Quality-First Multi-Agent Delivery Rules

Single source of truth for AI work in this checkout. Skills are domain knowledge. Workflows are short pointers back here. If a workflow, skill, or reminder disagrees with this file, this file wins.

Developer (Rabee) works **locally** in Android Studio on this checkout. The agent never uses Git worktrees, never commits, and never opens PRs.

Main chat model: **Gemini Flash 3.7**. Every subagent must use `model="inherit"`. Never pin `flash`/`pro` to a different SKU.

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
- **Colors**: Use `MyAppTheme` tokens. Prefer `MaterialTheme.colorScheme` / `MaterialTheme.typography`. `colorResource(R.color…)` is allowed when matching existing XML colors. No raw hex and no hardcoded fonts.
- **Context**: Subagents may read callers, contracts, entities, and lifecycle hosts.

---

## Always

- Work only in the opened `Fitness_Android` checkout. Subagents: `Workspace="inherit"`. Never `share` / worktree / new branch.
- Leave changes **unstaged**. No `git add`, commit, push, merge, rebase, stash, reset, or PR — not even if the developer says "commit it". Draft the Conventional Commit message only. Rabee commits in Android Studio.
- Physical device only. Never create or use an emulator or AVD. Resolve the serial with `adb devices` and pick a non-`emulator-` device. Do not hardcode a serial.
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
- Smallest change that matches **the files you opened**. Most of the app is Fragment + XML + ViewBinding. Do not convert an XML screen to Compose to fix a bug.
- Domain references (do not restate them here): ads/UMP, running/GPS, streak acknowledge, Room migrations, sensors/services, payments.
- Non-trivial work needs `.agents/state/plans/implementation_plan.md` and developer approval via `ask_question`.
- Large work (>3–4 files, or core types like `HomeActivity` / `HomeViewModel` / `RunTrackingService`): split into milestones (data → domain → state → UI). One milestone per increment. No 10-file big-bang turns.
- Bugs: 2–3 explicit hypotheses, trace data flow, fix the producer.
- TDD when it protects real logic. No placeholder tests.

### New production code

- New UI: Jetpack Compose in `BaseComposeFragment`.
- Any new or modified Compose UI: dual-locale `@Preview` in `MyAppTheme` — Arabic RTL (`locale = "ar"`) and English LTR (`locale = "en"`). **Screens** also need Loading, Empty, and Error. Cards, dialogs, sheets, and banners need the two locales; they do not need the three state previews.
- New ViewModels: `MVIViewModel<S, E, A>` (not `BaseViewModel`). Data via UseCase → `ResultStates<T>`.
- Zero inline FQCNs. Import at the top. Typealias collisions (`as CoreState`, `as CoreAction`, `as CoreEvent`).
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

1. `python .agents/scripts/review_package.py` (optional paths). Use the printed `RASHAQA_REVIEW_PACKAGE=`.
2. Dispatch **all 5** in **exactly one** `invoke_subagent` with `Subagents: [...]`. Same package path in every Prompt. `Workspace="inherit"`. Write tools off.
3. Stop calling tools. Do not poll `transcript.jsonl`. Do not run lint/tests/assemble while they run.
4. Collect verdicts. BLOCKER/MAJOR → fix at the producer → regenerate the package → dispatch the same 5 again. Identical package content is rejected; the diff must change.
5. Advance only when all five returned `BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`.

Never fire five separate `invoke_subagent` calls. That burns the round counter and is denied.

Optional sixth slot in the same invoke: `qa-diagnostics-agent` **or** `android-ui-expert-agent`, not both.

---

## 3) Lint, Tests, Build, Install, Launch

Only after the 5 leaves have finished (PASS, not still running):

1. `python .agents/scripts/fast_kt_lint.py` — dual-locale `@Preview` is required on Compose `*Screen.kt`, `*Card.kt`, `*Dialog.kt`, `*BottomSheet.kt`, `*Sheet.kt`, and `*Banner.kt`. Screens also need Loading/Empty/Error.
2. Targeted tests: `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest --tests "..."`. Payment tests: `app/src/test/.../payment/`.
3. `python .agents/scripts/run_gradle_task.py :app:assembleDebug`. Wait for `BUILD SUCCESSFUL` from **this** command. Daily work is **debug**. Do not install a leftover APK. Do **not** run raw `gradlew.bat` from the agent — the Python runner streams executing tasks and a 10s heartbeat so the task log is not empty during compile.
4. `adb devices` — physical serial only.
5. `python .agents/scripts/run_device.py install-start` (live adb install + launch). Equivalent: `adb -s <DEVICE_ID> install -r -d app/build/outputs/apk/debug/app-debug.apk` then `adb -s <DEVICE_ID> shell am start -n com.madarsoft.fitness/.features.splash.SplashActivity`.

Helpers: `python .agents/scripts/capture_screen.py` and `python .agents/scripts/logcat_doctor.py` (optional `--device <serial>`). Both reject emulators.

---

## 4) Manual Device Verification & Sign-off

- Short phases: Happy path, then edge/offline, then RTL/orientation, then lifecycle/re-entry. **One phase per `ask_question`.**
- On Fail: ask for symptoms in chat (not a modal). Do not guess. For crashes, offer `qa-diagnostics-agent` + `logcat_doctor.py`. Then fix producer, re-run gates, re-install, re-present the **same** phase.
- After **every** phase is Pass:
  1. Write `.agents/state/plans/walkthrough.md`
  2. Final Task Summary in chat: what / why / files / gates (`*_PASS` + `BUILD SUCCESSFUL`)
  3. Conventional Commit message for Android Studio
  4. Never present the commit message before every phase is Pass.

---

## Skills (read on demand)

- `android-harness` and its `references/` — MVI, ads, streak, GPS, sensors, Room, payments, Compose, scenarios
- `kotlin-coroutines-expert`
- `systematic-debugging`
- `compose-inspector`
- `gradle-build-optimizer`
- `git-pr-automator` — commit **message** format only
