# Quickstart

## Requirements

- Python 3.10 or newer;
- Git checkout;
- root Gradle Wrapper in the Android/KMP project;
- JDK/Android SDK only when selected build gates need them;
- ADB device only when the adaptive policy selects device verification.

## Chat installation (recommended)

Open the Android project root in your coding agent (select **Google Antigravity** during setup) and paste:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.60/docs/install-or-update-prompt.md and follow all instructions.
```

The agent interviews you in chat, preserves references, shows an explicit plan, provisions the pinned kit into `~/.android-harness/kit` (or `%USERPROFILE%\.android-harness\kit` on Windows), and runs Doctor verification (`doctor --install-check`).

Key configuration defaults for Google Antigravity:
- **AI Host**: Select `Google Antigravity` (`antigravity`).
- **Clean Install Only**: This architecture version supports deterministic clean installations.
- **Reviewer Call Safety Cap**: Recommended clean-install value = `20` (acts as a safety ceiling, not a target).
- **Installed Reviewer Subagents**: Seven dedicated custom reviewer agents are automatically generated under `.agents/agents/<reviewer>/agent.md`.
- **Model & Reasoning**: Inherited by omission from the parent agent; no manual model or reasoning configuration required.

## Terminal installation (alternative)

POSIX:
```bash
python ~/.android-harness/kit/harness_cli.py init --repo /path/to/app --kit ~/.android-harness/kit
python ~/.android-harness/kit/harness_cli.py doctor --install-check --repo /path/to/app --kit ~/.android-harness/kit --json
```

Windows:
```powershell
python "%USERPROFILE%\.android-harness\kit\harness_cli.py" init --repo C:\path\to\app --kit "%USERPROFILE%\.android-harness\kit"
python "%USERPROFILE%\.android-harness\kit\harness_cli.py" doctor --install-check --repo C:\path\to\app --kit "%USERPROFILE%\.android-harness\kit" --json
```

The setup wizard can be rerun before installation. Clean install is the supported onboarding path.

## Daily use (Antigravity-First)

1. **Discovery & Plan**: Ask the AI to analyze first. It explores using bounded Task Context, drafts a plan, and waits for explicit developer approval before any file modification.
2. **Approval**: Approve the plan in chat (reply "ابدأ" or "approve").
3. **Implementation**: The agent applies only approved changes. Unapproved file mutations outside scope are blocked by `.agents/hooks.json`.
4. **Prepare Verification**: Once changes are ready, the agent runs:
   ```bash
   python .agents/harness.py task prepare-verification --repo . --task-id <id> --host antigravity
   ```
5. **Parallel Reviewers**: Routed specialist subagents run concurrently via Antigravity `invoke_subagent` following Review Protocol V2. Structured results are recorded via `review complete` and aggregated via `review finalize`.
6. **Assemble & Device**: After reviews pass cleanly, the agent builds the debug APK (`assemble`) and deploys to a physical device (`device install-start`).
7. **Delivery**: When the lifecycle state is unclear, `python .agents/harness.py task status --repo . --task-id <id> --next` prints the authoritative next action. The agent never performs automatic git commits or pushes.
