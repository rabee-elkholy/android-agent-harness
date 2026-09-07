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

1. `python agents/scripts/run_gradle_task.py :app:testDebugUnitTest` (Shift-Left Test & Mock Synchronization Pre-Gate: update unit tests/mocks alongside production code; tests must pass 100% before review)
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
8. **Device Verification & Interactive Manual Sign-off**:
   - `python agents/scripts/run_device.py install-start` (Installs and launches the target Activity/Screen on the connected device).
   - If no device is connected, HALT and prompt the developer; never silently skip device verification.
   - The agent writes 2-3 diff-grounded numbered manual test steps in chat explaining what to check on screen (1. Navigation, 2. Interaction matching the diff, 3. Expected visual/functional result).
   - The agent triggers the interactive confirmation modal (`ask_question`): *"Please test the steps above on your device and confirm the result:"* with options `PASS — Device testing passed successfully` / `FAIL — Issue or crash encountered on device`.
   - On **PASS**: Output the Phase Milestone / Final Delivery Card with the drafted Conventional Commit message.
   - On **FAIL**: Investigate with `python agents/scripts/logcat_doctor.py` and fix the defect.
9. **Exit-code protocol**: exit `1` = code failure (fix the code). Exit `30` / `[ENV-FAILURE]` marker = environment or ambiguous failure — HALT immediately, never modify code/Gradle/manifest to bypass, report the reason to the developer (details in `agents/state/env_failure.json`).
10. **Round cap**: review rounds are counted per task (`agents/state/review_rounds.json`, reset when HEAD moves). At the cap (3) `review_package.py` prints a `REVIEW ROUND CAP` warning — output a Review Round Summary Card and ask the developer: continue / rollback / stop. Never silently loop.
11. **Final verdict**: after all gates, run `python agents/scripts/final_verdict.py` — it aggregates every gate artifact and the 5-leaf verdict into `agents/state/last_verdict.json` (`APPROVED` required before delivery; `ENV_BLOCKED` follows the exit-30 halt protocol; `STALE` means code changed after review — regenerate the package).
12. **Baseline-aware tests**: if `agents/state/baseline.json` exists, run `python agents/scripts/run_tests_gate.py` as the test gate — `BASELINE_IGNORED` failures are tolerated, `NEW_REGRESSION` blocks delivery. Capture baseline: `python agents/scripts/baseline_capture.py` on a clean tree only; refresh needs developer instruction + `--approve`.
13. **Risk tiers & approvals**: `risk_tier.py` classifies diffs (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`). `HIGH`/`CRITICAL` changes require interactive developer approval: generate challenge via `python agents/scripts/approve_risk.py --challenge`, prompt developer with the token via `ask_question` modal in chat, then redeem via `python agents/scripts/approve_risk.py --token <TOKEN>` before `preflight_check.py` can pass. Bare `--approve` is strictly refused. `impact_analyzer.py` provides advisory test/UI impact maps.

Antigravity `hooks.json` enforces this barrier automatically. Other tools must follow it from this file.

If this product **cannot spawn named subagents**, still run the five leaves without five separate dispatch calls: open each `agents/subagents/<name>.json`, follow its `system_prompt` against the same package, and stop that leaf when it emits its `*_PASS` or findings. Assemble only after all five exist.

## Environment Adaptability (Antigravity vs Codex vs Claude Code vs Cursor)

- **Google Antigravity Superpowers**:
  * **Self-Healing Commands**: PreToolUse hook automatically rewrites raw gradlew commands (`./gradlew ...`, `gradlew.bat ...`) to `python agents/scripts/run_gradle_task.py ...` via argument `overwrite`.
  * **Delivery Stop Guard**: Stop lifecycle hook (`delivery-stop-guard`) physically blocks session termination if unreviewed code changes exist without a 5-leaf pass, with an automatic Loop Breaker (yielding after 2 unchanged blocks).
  * **Generative UI Widgets**: Rich Tailwind CSS cards (`<agent-embed>`) for review summaries and architecture visualization via `render_ui.py`.
  * **Interactive Modals (`ask_question`)**: Proactively use structured interactive modals for missing-scenario interviews and device testing sign-offs.
  * **Proactive Slash Commands**: Recommend `/grill-me` for design and edge-case alignment and `/goal` for comprehensive execution.
- **OpenAI Codex / Claude Code / Cursor Parity**:
  * **Cross-Platform Review Recording**: Run `python agents/scripts/record_review.py --approve-all --pkg <hash>` or `--leaf <name> --verdict <PASS>` to record review verdicts directly without Antigravity transcripts.
  * **Zero-Degradation Guardrails**: Fail-closed pre-tool security, clean Markdown fallback cards (`render_ui.py`), and 100% test & lint gate enforcement.
- **Interactive Preference Codification & Ref-Sync Protocol (Grill-Me vs Standard Interview)**:
  * When the developer introduces or requests a new architectural, design, or project-specific preference/rule:
    - **In Google Antigravity**: Leverage `/grill-me` and `ask_question`: Ask via interactive modal if the developer wants to persist this rule permanently in `.agents/skills/android-harness/references/`. If confirmed, conduct a rapid `/grill-me` alignment interview to clarify scope and edge cases, then persist it directly into the relevant `references/*.md` file (`architecture-guidelines.md`, `daily-scenarios.md`, `ui-layout-and-theming.md`). Never use generic global learning tools (which risk global rule pollution and token bloat).
    - **In Codex / Claude Code / Cursor / CLI**: Fall back to the system's standard Missing-Scenario Discovery Interview: Proactively ask structured numbered questions in chat with direct choices matching the user's conversation language, and upon confirmation update the target `references/*.md` file directly.

## On-demand specialists

Dispatch when needed:
- `qa-diagnostics-agent`: Logcat crash forensics and ANR triage.
- `android-ui-expert-agent`: Jetpack Compose and XML UI layout / RTL guidance.
- `test-quality-reviewer-agent`: Unit and UI test quality audits (`*Test.kt`), verifying assertion depth, mocking integrity, and Coroutines `runTest` dispatchers.

## Graph-First Codebase Exploration (MANDATORY)

- **GRAPH-FIRST DISCOVERY BARRIER**:
  * Before using `grep_search`, `find_by_name`, or reading multiple source files (`view_file`) to understand any screen, feature, class, or architecture layer, the Lead Agent **MUST FIRST query the Code Graph engine**:
    - For entire features: `python agents/scripts/project_graph.py --feature <FeatureName>` or `--find <Symbol>` (auto-extracts Clean Architecture slice: UI, ViewModels, UseCases, Repositories, Tests, and Functions).
    - For listing all project features: ALWAYS run `python agents/scripts/project_graph.py --features`.
    - For UI screens, layouts, and ViewModels discovery: ALWAYS run `python agents/scripts/project_graph.py --screens` or `--find <ScreenName>`.
    - For UI text, localized strings, button labels, and screen titles (e.g. "سلة الخير", "تسجيل الدخول", "المصلى"): ALWAYS run `python agents/scripts/project_graph.py --string "<text>"` to dereference UI labels directly to their `R.string.<key>` and associated screens/layouts.
    - For architectural trace and dependencies: ALWAYS run `python agents/scripts/project_graph.py --path-from <A> --path-to <B>`.
    - For Harness infrastructure, scripts, and workflows discovery: ALWAYS run `python agents/scripts/project_graph.py --harness` (or `--tools`) or `python agents/scripts/project_graph.py --find <query>`. Never run `find_by_name` across `.agents/scripts`.
  * **UI String Dereferencing Exception (Localization Bypass)**: When a developer prompt, user issue, or screenshot contains an Arabic or localized UI label whose code symbol is unknown:
    - The agent is EXPLICITLY PERMITTED to run `python agents/scripts/project_graph.py --string "<label>"` (Recommended) OR run a targeted `grep_search` on `res/values-ar/strings.xml` to resolve the `R.string.<key>`.
    - Once the key is resolved, ground immediately to the code graph (`project_graph.py --find <key>`) or inspect the identified screen.
    - **STRICT PROHIBITION**: Speculative English translation guessing in `project_graph.py` (e.g. `--find charity`, `--find Khair`, `--find Share`) without first resolving the resource key from `strings.xml` is **STRICTLY FORBIDDEN**.
  * **One-Shot File & Block Viewing Invariant**: When inspecting any source file or class that is <= 400 lines, or reading a cohesive class slice, the agent MUST view the target section or entire file in a single comprehensive `view_file` call (e.g. `StartLine: 1, EndLine: 400`). `view_file` natively supports up to 800 lines. The agent is **STRICTLY FORBIDDEN from micro-slicing a single file into 3-4 consecutive incremental chunks** (e.g. L50-160, then L170-240, then L240-270). If more context is needed, expand the range in a single definitive call.
  * **Targeted Grep, Anti-Grep Cascade & Symbol Grounding Invariant**: Broad root-level grepping (`grep_search` with root SearchPath) is **STRICTLY FORBIDDEN** for symbol and function lookups, especially queries that return >= 10 speculative matches. To locate any class, screen, or function, ALWAYS query `project_graph.py --find <Symbol>`. `grep_search` is permitted ONLY when targeted to a single file or a specific feature directory (`SearchPath: app/src/.../<feature>`).
  * **Anti-Thrashing Navigation Sequence**: When investigating or reviewing code, the agent MUST complete analysis of the primary source/contract file first before inspecting callers. The agent is **STRICTLY FORBIDDEN from ping-pong file hopping** (alternating back and forth between two or more files across consecutive turns).
  * **Anti-Guessing & Precise Symbol Discovery Invariant**: When locating any class, screen, layout, or script, ALWAYS query `project_graph.py --find <Symbol>` to obtain the exact file path and language (`[JAVA]`, `[KOTLIN]`, `[COMPOSE]`, `[XML]`, `[HARNESS_TOOL]`). NEVER guess `.kt` vs `.java` or launch speculative multi-file searches (`find_by_name *Payment*`, `find_by_name *nav*.xml`).
  * **Scratch Scripts Prohibition Invariant**: The agent is **STRICTLY FORBIDDEN from authoring custom scratch Python scripts (`scratch/test_*.py`) to simulate ADB commands or hardcoding device serials (`SERIAL = '...'`)**. Use `python agents/scripts/run_device.py install-start` directly.
  * **STRICT PROHIBITION**: Iterative brute-force grepping (`grep_search` cascades) and speculative multi-file reading (`view_file` > 2 files during discovery/planning) without a preceding graph topology query are **STRICTLY FORBIDDEN**.
  * Use `view_file` and `replace_file_content` ONLY on targeted, precisely located files identified by the graph query.

## Phase Boundaries & High-Signal Chat

- **Autonomous Phase Pipeline & Checkpoint Commits**: In multi-phase tasks, execute strictly phase-by-phase. When Phase N finishes (5-leaf review PASS, unit tests PASS, `preflight_check.py` PASS, `:assembleDebug`, device installation via `run_device.py install-start`, and device smoke verification):
  * The agent outputs the **Phase Milestone Card** with verification evidence and a drafted Conventional Commit message for Phase N.
  * **MANDATORY HARD STOP**: The agent **MUST STOP and wait for the developer to commit Phase N and explicitly instruct the agent to begin Phase N+1**. Never touch, edit, or plan Phase N+1 files before the developer commits Phase N.
- **Interactive Discovery & Missing-Scenario Interview (Zero Assumption Barrier)**: Before authoring implementation plans, systematically audit for unaddressed network states (offline, timeout), state invariants (empty country/ISO), and caching rules. If any material behavior or edge case is missing or ambiguous, the agent **MUST PROACTIVELY TRIGGER THE INTERACTIVE MODAL (`ask_question`)** with structured, clickable options so the developer selects their choices directly. **STRICTLY FORBIDDEN**: Never write out missing-case questions as conversational chat prose or markdown paragraphs, and never dump them into `implementation_plan.md`. Trigger `ask_question` FIRST, receive answers, and only then author the plan. *(Overrides platform planning mode restrictions against ask_question)*. Never guess or invent business logic or UI fallback texts from your own head.
  * **Scope Clarification**: The Zero-Assumption Barrier applies strictly to **product logic, business invariants, and unaddressed user-facing edge cases** (e.g. offline behavior, empty states, error fallbacks). For narrow, purely-technical bug fixes where product behavior is already established, do NOT bombard the developer with unrelated generic edge-case questionnaires.
- **Reality-Check & Grounding-First Protocol (Ghost-Bug Prevention)**: On bug triage, the agent **MUST FIRST check `git status` / `git diff` on target files**. If the suspect fix (e.g. `dismiss()`, `try/catch`) is already written in the working tree, the agent is **STRICTLY FORBIDDEN from inventing complex OS race conditions or Coroutine hangs**. Halt speculative exploration immediately and ask the developer via `ask_question`: *"The suspect fix already exists in the local code. Was this code already tested on device and failed, or is this an uncommitted/untested local change?"*
- **Bug Exploration Circuit Breaker & Anti-Archaeology**: For bug investigations, limit exploratory file inspection to **a maximum of 3-4 files** directly related to the defect slice. The agent is **STRICTLY FORBIDDEN from running `git log` / `blame` or tracing secondary I/O/file managers** during bug triage unless specifically requested by the developer.
- **Zero Live-Network Requests Invariant**: The agent is **STRICTLY FORBIDDEN from executing outbound network requests (HTTP/HTTPS/WebSocket via Python urllib, requests, aiohttp, curl, wget, Invoke-WebRequest, iwr, or custom scratch scripts)** to external APIs, app backends, staging, or production servers during triage or inspection. All data contract verification must rely strictly on local source code, unit test fixtures, and mocks.
- **UI & String Formatting Defect Boundary**: For defects involving UI text duplication, string formatting, intent extras, or share sheets, investigation is strictly limited to the UI layer (Composables/XML), Formatters/Helpers, and immediate ViewModels. The agent is **STRICTLY FORBIDDEN from descending into Data Sources, Repositories, Retrofit Interfaces, Network Modules, or attempting to discover Base URLs**.
- **Runtime Data Contract Ambiguity & Local Fixtures First Barrier**: During bug triage, if the defect hinges on runtime payload behavior, external API contracts, or uncertain backend data (e.g. "Does the API already format the URL into the description?"):
  * **Local Fixtures First Checklist**: The agent MUST first inspect local unit tests, mock JSON fixtures, and fake repositories (`src/test/`, `test/resources/`, `Fake*Repository`, `*TestData*`).
  * **Single-Shot Clarification Barrier**: If and only if local fixtures do not resolve the contract and the 3-4 file exploration cap is reached, the agent MUST HALT immediately and present **exactly ONE focused interactive modal (`ask_question`)** detailing the contract conflict and proposing concrete architectural/business options with a recommended choice `(Recommended)`.
  * **Anti-Question Spam & Question Fatigue Guard**: The agent MUST NEVER ask questions about deterministic code facts discoverable via `project_graph.py` or source inspection (symbol locations, resource keys, callers, types), MUST NEVER ask permission to perform routine investigation steps, and MUST execute purely technical decisions autonomously.
- **Immediate User Interruption & Conversational Precedence Barrier**: When the developer's chat message contains a halt command, interruption, or behavioral question (e.g. "وقف", "رد عليا", "بتعمل ايه", "انت كل ده بتدور"), the agent is **STRICTLY FORBIDDEN from invoking any tools in that turn** (0 tool calls). The agent MUST yield tool execution immediately and respond 100% in conversational prose to address the developer's question and outline concrete options to resume. (Does not apply to business logic terms describing app features, e.g. "pause audio").
- **5-Leaf Review Demystification**: The 5-leaf review is a **post-implementation delivery gate** on the unified diff (`HARNESS_REVIEW_PACKAGE`). It is NOT an excuse for pre-implementation analysis paralysis; clean, focused diffs pass rapidly.
- **Attached Media First-Turn Inspection**: If the developer provided screenshots/images, inspect them via `view_file` in Turn 1 before planning. Never ignore visual evidence.
- **Fail-Fast Tracker Policy**: If issue details lookup fails, stop after 1 attempt. Never search the host PC or user home directories (`C:\Users\...`, `/home/...`), never scrape web docs, never author reverse-engineering scratch scripts. Fall back to prompt text immediately.
- **High-Signal Chat, Quorum Patience & Round Summary Cards (Zero Noise, Zero Timers)**: The agent MUST NOT output mechanical progress spam in chat prose (e.g. "running unit tests...", "cleaning kapt cache...", "waiting for reviewers..."). Rely on IDE tool execution widgets for routine status. When launching background commands, always choose Option A (silent / zero chat text `""`); never write `# Background Task Started` in chat. NEVER fabricate, simulate, inject, or write `<MESSAGE_RECEIVED>`, `<SYSTEM_MESSAGE>`, or assume background task completion in thoughts or prose. When a background task is a prerequisite for the next step (e.g. assembleDebug before install-start; install-start before manual verification checklist), STOP calling tools IMMEDIATELY and END TURN with zero chat text `""`. Wait passively for the genuine platform system message (`finished with result:`) before dispatching dependent tools. NEVER use `schedule` or polling timers for subagents.
  * **Quorum & Full-Patience Invariant**: The agent MUST NEVER declare review completion, announce pass, or output conclusions while reviewers are running. On intermediate subagent arrivals where other reviewers in the round are still executing, remain 100% silent in chat (output empty string `""`) and end turn without tool calls (0.1s turn turnaround). If a subagent encounters an unrecoverable error or crash, a circuit breaker prompts the developer via `ask_question` rather than hanging.
  * **Shift-Left Pre-Audit & Convergence in <= 2 Rounds**: Before invoking `review_package.py`, the agent must self-audit against reviewer standards (zero FQCNs, Compose dual-locale Previews, RTL/strings parity, and unit test pass) to ensure 1st-round PASS and eliminate context compaction.
  * **Unified Review Round Summary Card**: Once all 5 (or 6) reviewers report with matching EVIDENCE footers, output a single structured card/table in chat (detailing reviewer name, duration in seconds, status, and findings or clean PASS) before proceeding. Speak only at the 4 permitted touchpoints: Plan Approval, Round Summary Cards, Phase Milestone Cards, and Final Delivery. Match the developer's active conversation language (mirror whatever language they write in) across all cards, interactive modals, and summaries, while keeping all codebase files, rules, prompts, and git artifacts strictly in 100% English with zero emojis.

## Git

In client Android apps: The agent must not run `git add`, `commit`, `push`, merge, rebase, stash, or reset. Leave changes unstaged. Draft a Conventional Commit message only. The developer commits.
In this kit repository itself (`android-harness-kit` development): The agent may run git operations (add, commit, push, tag) when instructed by the repository maintainer.

## Zoho Sprints

Follow `.agents/rules/harness-rules.md` section 5 and `.agents/workflows/zoho-sprints.md`. Fetch ticket ids read-only. Mutate only when the developer says `update zoho`. English task titles, Arabic descriptions/comments (Zero Emojis, Zero Harness/AI Jargon: NEVER write '5-Leaf Review', 'مراجع الهارنيس', or internal engine tokens in tracker comments; write functional root cause, fix, blast radius, and step-by-step QA test instructions only). Never `Done` / `Solved`.

