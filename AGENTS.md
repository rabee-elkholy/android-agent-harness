<!-- managed-by: android-harness-kit -->
# android-harness-kit — agent instructions

**Source of truth:** `agents/rules/harness-rules.md`. If any other file disagrees, that file wins.

This checkout uses a portable Android harness. The same rules apply in Cursor, Claude Code, Codex, Copilot, Gemini, Qwen Code, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, Goose, and any other agent that reads `AGENTS.md`.

## Environment

- Android SDK: this machine only (`local.properties` `sdk.dir`). Never copy another PC’s path.
- Python: `python` for every harness script.
- Gradle: `python agents/scripts/run_gradle_task.py :app:assembleDebug` (picks `gradlew` / `gradlew.bat`). Never call raw `gradlew` from the agent.
- Device: Physical device or emulator. Resolve the serial with `adb devices`. Prefer a physical device when both are connected. Never hardcode a serial.
- Install/launch: `python agents/scripts/run_device.py install-start`

## Delivery gate (do not skip)

After non-trivial implementation:

1. `python agents/scripts/run_gradle_task.py :app:testDebugUnitTest` (Shift-Left Test Pre-Gate: compiler parity and unit tests — permitted before review)
2. `python agents/scripts/fast_kt_lint.py` (Shift-Left Lint Pre-Gate: diff-scoped fast Kotlin lint on modified lines without penalizing untouched legacy code)
3. `python agents/scripts/review_package.py` (strictly validates lint before creating package)
4. Run **all five** reviewers against the same `HARNESS_REVIEW_PACKAGE=` path (prompts in `agents/subagents/*.json`). Dispatch them in **exactly one** parallel invoke when this product can spawn children.
   - `bug-reviewer-agent` → `BUG_PASS`
   - `convention-reviewer-agent` → `CONVENTION_PASS`
   - `security-reviewer-agent` → `SECURITY_PASS`
   - `perf-anr-guardian-agent` → `PERF_PASS`
   - `regression-impact-reviewer-agent` → `REGRESSION_PASS`
5. Do **not** treat a single self-review as the gate. Do not invoke `code-review-guard-agent`. Do not wait for `LGTM`.
6. `python agents/scripts/preflight_check.py` (Mandatory Preflight Gate: must pass with 0 errors before assemble — never assemble if `[FAIL]`)
7. `python agents/scripts/run_gradle_task.py :app:assembleDebug`
8. Live device install & verification: `python agents/scripts/run_device.py install-start` + `python agents/scripts/run_e2e_smoke.py`. If no device is connected, HALT and prompt the developer; never silently skip device verification.
9. **Exit-code protocol**: exit `1` = code failure (fix the code). Exit `30` / `[ENV-FAILURE]` marker = environment or ambiguous failure — HALT immediately, never modify code/Gradle/manifest to bypass, report the reason to the developer (details in `agents/state/env_failure.json`).
10. **Round cap**: review rounds are counted per task (`agents/state/review_rounds.json`, reset when HEAD moves). At the cap (2) `review_package.py` prints a `REVIEW ROUND CAP` warning — output a Review Round Summary Card and ask the developer: continue / rollback / stop. Never silently loop.
11. **Final verdict**: after all gates, run `python agents/scripts/final_verdict.py` — it aggregates every gate artifact and the 5-leaf verdict into `agents/state/last_verdict.json` (`APPROVED` required before delivery; `ENV_BLOCKED` follows the exit-30 halt protocol; `STALE` means code changed after review — regenerate the package).

Antigravity `hooks.json` enforces this barrier automatically. Other tools must follow it from this file.

If this product **cannot spawn named subagents**, still run the five leaves without five separate dispatch calls: open each `agents/subagents/<name>.json`, follow its `system_prompt` against the same package, and stop that leaf when it emits its `*_PASS` or findings. Assemble only after all five exist.

## On-demand specialists

Dispatch when needed:
- `qa-diagnostics-agent`: Logcat crash forensics and ANR triage.
- `android-ui-expert-agent`: Jetpack Compose and XML UI layout / RTL guidance.
- `test-quality-reviewer-agent`: Unit and UI test quality audits (`*Test.kt`), verifying assertion depth, mocking integrity, and Coroutines `runTest` dispatchers.

## Phase Boundaries & High-Signal Chat

- **Autonomous Phase Pipeline & Checkpoint Commits**: In multi-phase tasks, execute strictly phase-by-phase. When Phase N finishes (5-leaf review PASS, unit tests PASS, `preflight_check.py` PASS, `:assembleDebug`, device installation via `run_device.py install-start`, and device smoke verification):
  * The agent outputs the **Phase Milestone Card** with verification evidence and a drafted Conventional Commit message for Phase N.
  * **MANDATORY HARD STOP**: The agent **MUST STOP and wait for the developer to commit Phase N and explicitly instruct the agent to begin Phase N+1**. Never touch, edit, or plan Phase N+1 files before the developer commits Phase N.
- **High-Signal Chat & Round Summary Cards (Zero Noise, Zero Timers)**: The agent MUST NOT output mechanical progress spam in chat prose (e.g. "running unit tests...", "cleaning kapt cache...", "waiting for reviewers..."). Rely on IDE tool execution widgets for routine status. When launching background commands, always choose Option A (silent / zero chat text `""`); never write `# Background Task Started` in chat. NEVER fabricate, simulate, inject, or write `<MESSAGE_RECEIVED>`, `<SYSTEM_MESSAGE>`, or assume background task completion in thoughts or prose. When a background task is a prerequisite for the next step (e.g. assembleDebug before install-start; install-start before run_e2e_smoke), STOP calling tools IMMEDIATELY and END TURN with zero chat text `""`. Wait passively for the genuine platform system message (`finished with result:`) before dispatching dependent tools. NEVER use `schedule` or polling timers for subagents. On intermediate subagent arrivals where other reviewers in the round are still executing, remain 100% silent in chat (output empty string `""`) and end turn without tool calls. When a 5-leaf round finishes with findings, output a concise **Review Round Summary Card** in chat detailing the findings and corrective fixes before launching the next round (rounds must converge in <= 2 rounds). Speak only at the 4 permitted touchpoints: Plan Approval, Round Summary Cards (on findings), Phase Milestone Cards, and Final Delivery. Match the developer's active conversation language (mirror whatever language they write in) across all cards, interactive modals, and summaries.

## Git

In client Android apps: The agent must not run `git add`, `commit`, `push`, merge, rebase, stash, or reset. Leave changes unstaged. Draft a Conventional Commit message only. The developer commits.
In this kit repository itself (`android-harness-kit` development): The agent may run git operations (add, commit, push, tag) when instructed by the repository maintainer.

## Zoho Sprints

Follow `.agents/rules/harness-rules.md` section 5 and `.agents/workflows/zoho-sprints.md`. Fetch ticket ids read-only. Mutate only when the developer says `update zoho`. English task titles, Arabic descriptions/comments. Never `Done` / `Solved`.

