<!-- managed-by: android-agent-harness -->
# Android Agent Harness repository instructions (Gemini CLI / Antigravity)

Before modifying this repository, read:

1. `PROJECT_CONSTITUTION.md`
2. `AGENTS.md`
3. Relevant ADR and current architecture documents

This checkout is the `android-agent-harness` kit itself, not a client Android application:

- Use `python harness_cli.py selftest` for the complete deterministic suite;
- Use `python -m compileall -q harness_cli.py agents/scripts` for syntax validation;
- Do not run Android Gradle or ADB gates against this repository;
- Client Android project adapter instructions live in `agents/tool-adapters/GEMINI.md.template` (never mix client `.agents/harness.py` app workflows into kit repository maintenance);
- Never poll background tasks or subagents in a loop (Zero-Polling invariant).

Do not duplicate `PROJECT_CONSTITUTION.md` or `AGENTS.md` rules here.
