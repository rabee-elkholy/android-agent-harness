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
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.1.1/docs/install-or-update-prompt.md and follow all instructions.
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
2. **Approval**: Approve the plan in chat (reply "ابدأ" or "approve"). Single intake approval covers all phases in a multi-phase task without pauses.
3. **Implementation**: The agent applies only approved changes. Unapproved file mutations outside scope are blocked by `.agents/hooks.json`.
4. **Prepare Verification**: Once changes are ready, the agent runs:
   ```bash
   python .agents/harness.py task prepare-verification --repo . --task-id <id> --host antigravity
   ```
5. **Parallel Reviewers**: Routed specialist subagents run concurrently via Antigravity `invoke_subagent` following Review Protocol V2. Structured results are recorded via `review complete` and aggregated via `review finalize`.
6. **Assemble & Device**: After reviews pass cleanly, the agent builds the debug APK (`assemble`) and deploys to a physical device (`device install-start`).
7. **Delivery**: When the lifecycle state is unclear, `python .agents/harness.py task status --repo . --task-id <id> --next` prints the authoritative next action. The agent never performs automatic git commits or pushes.

## Canonical Large-Task & Phased Execution

For multi-phase tasks, the workflow executes sequentially and autonomously:
```text
one task approval
→ phase implementation
→ deterministic checkpoint
→ scoped phase delta review when selected
→ next phase
→ final integration review
→ assemble/device
→ developer signoff
→ final verify
→ developer Git commit
→ deliver
```

## Urgent Task Interruption & Worktree Handoff

When an urgent bug or hotfix interrupts an active in-progress task (Task A):
```text
Task A
→ task handoff (python .agents/harness.py task handoff --task-id <id>)
→ developer WIP commit (developer creates Git commit for checkpoint)
→ reconcile handoff (python .agents/harness.py task reconcile-handoff --task-id <id>)
→ developer creates separate worktree (git worktree add ../repo-task-b HEAD)
→ Task B in new chat/worktree
→ return to Task A worktree/chat
→ task status --next (python .agents/harness.py task status --task-id <id> --next)
```

### Core Invariants
- **One live task per worktree**: Each worktree maintains isolated task state.
- **Model never executes Git mutations**: Git operations are strictly developer-owned.
- **Lineage enforcement**: Mid-task Git commits must follow the handoff protocol; raw unregistered commits remain lineage violations.
- **Final review required**: Even when all phase reviews pass cleanly, final integration review remains required.
