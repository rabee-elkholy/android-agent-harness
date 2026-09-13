<!-- managed-by: android-harness-kit -->
# android-harness-kit — Gemini CLI / Antigravity

Follow `AGENTS.md` and `agents/rules/harness-rules.md`. That file wins.

- Python: `python`
- Assemble: `python agents/scripts/run_gradle_task.py :app:assembleDebug`
- Device: Physical device or emulator. Resolve the serial with `adb devices`. Prefer a physical device when both are connected. Never hardcode a serial.
- In client Android apps: The agent must not run `git add`, `commit`, `push`, merge, rebase, stash, or reset. Leave changes unstaged. Draft a Conventional Commit message only. The developer commits. In this kit repository itself (`android-harness-kit` development): The agent may run git operations when instructed by the maintainer.
- Independent Reviews: Reviewer roles selected by policy MUST be executed via subagents. The lead agent is strictly forbidden from self-certifying reviews using `record_review.py --verdict PASS` on HIGH/CRITICAL or sensitive changes; evaluations must come from actual reviewer runs.
- Antigravity Planning Lifecycle: The interactive Proceed button appears ONLY on initial task plan approval. Subsequent updates show only Review. Never tell the developer to click 'Proceed' on follow-ups or bug fixes during active tasks; execute, compile, and deploy directly.
- Mobile Verification Walkthrough: After every device installation (`run_device.py install-start`), the agent MUST output a complete, numbered mobile verification walkthrough (Navigation path, Preconditions, User actions, Expected results, Edge cases) in chat BEFORE invoking `ask_question` for developer sign-off. The agent must NEVER invoke `ask_question` with just 'Did it pass' without detailing how to navigate to and test the specific modified feature.

Antigravity loads `agents/hooks.json` in this repo. Gemini CLI does not; still honor the five-leaf review before assemble. No `code-review-guard-agent`. No `LGTM`.
