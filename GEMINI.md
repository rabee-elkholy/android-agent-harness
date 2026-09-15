<!-- managed-by: android-harness-kit -->
# android-harness-kit — Gemini CLI / Antigravity

Follow `AGENTS.md` and `agents/rules/harness-rules.md`. That file wins.

- Python: `python`
- Assemble: `python agents/scripts/run_gradle_task.py :app:assembleDebug`
- Harness Execution Boundary: Installed harness engine source under `.agents/scripts/**` is an implementation detail. Execute documented commands directly; do not inspect or recursively read harness Python implementation before execution.
- Device: Physical device or emulator. Resolve the serial with `adb devices`. Prefer a physical device when both are connected. Never hardcode a serial.
- Discovery: MUST start with `python .agents/scripts/project_graph.py --feature <name>` or `--find <Symbol>` (mandatory even with known commits/files). Unanchored grep cascades are forbidden.
- Pre-Planning Clarification: Missing requirements, edge cases, or domain ambiguities MUST be clarified interactively via `ask_question` before drafting the plan; guessing is strictly forbidden.
- Multi-Phase Execution: Multi-phase plans execute sequentially and autonomously. Single intake approval covers all phases; never pause or ask developer between phases.
- Strict Verification Order: The Verification Plan in `implementation_plan.md` MUST use the 6-step headings (1. preflight -> 2. unit tests -> 3. routed reviewers -> 4. device install -> 5. mobile walkthrough -> 6. verify). The agent MUST wait for ALL routed specialist reviewers (subagents) to finish, record their responses via `record_review.py`, and verify ZERO blocking findings BEFORE running `assembleDebug` or starting device installation. Starting assemble or device deployment while any reviewer subagent is still running is strictly forbidden.
- Reviewer Dispatch: 100% autonomous. Launch routed reviewers in parallel via subagents immediately; never pause, ask for permission, or demand 'Proceed'.
- Direct Review Ingestion: Ingest reviewer responses directly with `python .agents/scripts/record_review.py --task <id> --response-text "<name>=<text>"`; do not create intermediate scratch files.
- In client Android apps: The agent must not run `git add`, `commit`, `push`, merge, rebase, stash, or reset. Leave changes unstaged. Draft a Conventional Commit message only. The developer commits. In this kit repository itself (`android-harness-kit` development): The agent may run git operations when instructed by the maintainer.
- Independent Reviews: Reviewer roles selected by policy MUST be executed via subagents. The lead agent is strictly forbidden from self-certifying reviews using `record_review.py --verdict PASS` on HIGH/CRITICAL or sensitive changes; evaluations must come from actual reviewer runs.
- Antigravity Planning Lifecycle: The interactive Proceed button appears ONLY on initial task plan approval. Subsequent updates show only Review. Never tell the developer to click 'Proceed' on follow-ups or bug fixes during active tasks; execute, compile, and deploy directly.
- Mobile Verification Walkthrough & Device Verification: The agent MUST wait for `run_device.py install-start` to finish execution with exit code 0 BEFORE outputting any mobile verification walkthrough or invoking `ask_question`. If `run_device.py` is still running as a background task, wait for completion; never output walkthrough or invoke `ask_question` prematurely. If `run_device.py` fails (e.g. `[ENV-FAILURE] no Android device detected via adb`), report the exact environment blocker to the developer; NEVER hallucinate device serials (such as `emulator-5554`), never claim the app is running when it is not, and NEVER ask the developer to verify a build that was not installed. When installation succeeds, output a complete, numbered mobile verification walkthrough (Navigation path, Preconditions, User actions, Expected results, Edge cases) in chat BEFORE invoking `ask_question` for sign-off. Never invoke `ask_question` with just 'Did it pass' without detailing feature navigation.

Antigravity loads `agents/hooks.json` in this repo. Gemini CLI does not; still honor the five-leaf review before assemble. No `code-review-guard-agent`. No `LGTM`.
