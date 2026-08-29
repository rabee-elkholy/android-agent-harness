<!-- managed-by: android-harness-kit -->
# android-harness-kit — Gemini CLI / Antigravity

Follow `AGENTS.md` and `.agents/rules/harness-rules.md`. That file wins.

- Python: `python`
- Assemble: `python .agents/scripts/run_gradle_task.py :app:assembleDebug`
- Device: Physical device or emulator. Resolve the serial with `adb devices`. Prefer a physical device when both are connected. Never hardcode a serial.
- The agent must not run `git add`, `commit`, `push`, merge, rebase, stash, or reset. Leave changes unstaged. Draft a Conventional Commit message only. The developer commits.

Antigravity loads `.agents/hooks.json` in this repo. Gemini CLI does not; still honor the five-leaf review before assemble. No `code-review-guard-agent`. No `LGTM`.
