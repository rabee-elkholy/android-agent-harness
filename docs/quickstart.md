# Quickstart

## Requirements

- Python 3.10 or newer;
- Git checkout;
- root Gradle Wrapper in the **Native Android** or **KMM / KMP (Kotlin Multiplatform Mobile)** project (`:app`, `:composeApp`, `:androidApp`, `:shared`);
- JDK/Android SDK only when selected build gates need them;
- ADB device only when the adaptive policy selects device verification.

## Chat installation (recommended)

Open the Android project root in **Google Antigravity** (`antigravity` is selected automatically by default during setup) and paste:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.5.11/docs/install-or-update-prompt.md and follow all instructions.
```

The agent interviews you in chat, preserves references, shows an explicit plan, provisions the pinned kit into `~/.android-harness/kit` (or `%USERPROFILE%\.android-harness\kit` on Windows), and runs Doctor verification (`doctor --install-check`).

Key configuration defaults for Google Antigravity:
- **AI Host**: Select `Google Antigravity` (`antigravity`).
- **Clean Install Only**: This architecture version supports deterministic clean installations.
- **Reviewer Call Safety Cap**: Recommended clean-install value = `20` (acts as a safety ceiling, not a target).
- **Installed Custom Subagents**: Four dedicated specialist reviewer agents (`bug-test-reviewer-agent`, `security-perf-reviewer-agent`, `arch-regression-reviewer-agent`, `spec-compliance-agent`), two on-demand domain specialists (`qa-diagnostics-agent`, `android-ui-expert-agent`), and one quota-saving read-only exploration scout (`harness-scout-agent`) are automatically generated under `.agents/agents/<role>/agent.md`.
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

1. **Discovery & Plan**: Ask the AI to analyze first. It explores using bounded Task Context, drafts a plan (evaluating Zero-Decision readiness, codebase reuse candidates, path grounding, and multi-phase module DAG ordering via `task plan-check`), and waits for explicit developer approval before any file modification.
2. **Approval**: Approve the plan in chat (reply with an approval such as "approve", in any language). Single intake approval covers all phases in a multi-phase task without pauses.
3. **Warm-Cache Inline Lead Implementation**: The agent follows `python .agents/harness.py delegate-plan --json` — implementing approved production & unit-test files directly inline on the warm Lead cache (`INLINE_LEAD_DIRECT`, or via `Web-Relay` when Web mode is active) with concise English KDoc (`/** ... */`) on newly created classes/interfaces and added public contracts, then advancing through `checkpoint-phase --advance-all-ready` / single-pass `verify-steps`. Unapproved file mutations outside scope are blocked by `.agents/hooks.json`.
4. **Prepare Verification**: Once changes are ready, the agent runs:
   ```bash
   python .agents/harness.py task prepare-verification --repo . --task-id <id> --host antigravity
   ```
5. **Parallel Reviewers**: Routed specialist subagents run concurrently via Antigravity `invoke_subagent` following Review Protocol V2. Structured results are ingested and finalized in one turn via `review complete-all --task <id>` (or individually via `review complete` and `review finalize`).
6. **Assemble & Device**: After reviews pass cleanly, the agent builds the debug APK (`assemble`) and deploys to a physical device (`device install-start`). Startup checks verify the installed APK and foreground app/user; an optional `--expect-resource-id` asserts a known visible element. The walkthrough remains required. See [verification hardening](verification-hardening.md).
7. **Delivery**: When the lifecycle state is unclear, `python .agents/harness.py task status --repo . --task-id <id> --next` prints the authoritative next action. The agent never performs automatic git commits or pushes.
8. **Self-Healing, Living Context Drift, PM Sync & Incident Consent**: If task state becomes stale after an edit, `python .agents/harness.py task heal --task-id <id> --prepare-fresh-run` restores the nearest valid checkpoint. Use `python .agents/harness.py context drift-report` to check `project-notes.md` and `developer-instructions.json` for stale file or module references after refactors. External PM MCP updates (`zoho-projects_mcp`, Jira, Linear, etc.) require showing a preview and recording `python .agents/harness.py pm authorize --proof-reference "<phrase>"`. Unexpected harness exceptions save organized Zero-PII reports under `.agents/state/incidents/` and ask via `ask_question` before submitting to GitHub.

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

Before execution, two or three pending plans can become one task: preview with `python .agents/harness.py task merge --task-id combined --from-task-id task-a --from-task-id task-b --json`. After the developer chooses the preview, apply with the same ids plus `--apply --expect-preview <merge_preview_sha256> --source conversation --proof-reference "<merge choice>"`. Source history stays readable; the new plan needs one fresh approval. Started tasks and conflicting architecture/acceptance/tracker contracts cannot be combined automatically. [Merge details](../README.md#faq).

Disjoint tasks may share a worktree without committing previous work. Builds and APKs still include every local task, and frozen verification becomes stale if any task changes. For overlapping files or independent builds, use the separate-worktree flow below.

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

## Execution Modes (Local Default & Threshold-Prompted `Web-Relay`)

Ordinary tasks (`<10` files, `<80 KB` non-test code mass, single-phase, and single-module or compact 2-module `<6` files / `<48 KB`) run locally in Antigravity by default without interrupting you. When a heavy task (`10+` files, `80+ KB`, `2+` phases, substantial multi-module, or `4+`-file / `32+ KB` `T5` scope) warrants offloading code generation to an **external AI chat (`Web-Relay`)**, Antigravity prompts once with estimated quota savings (`~60%–85%`) and 3 choices (`normal-task`, `web-task`, or `normal-project` to lock local execution and stop asking):

```bash
# 1. Optional: lock local execution project-wide (or web-project / ask-every-task to reset)
python .agents/harness.py execution-mode set --choice normal-project --source conversation --proof-reference "Always run locally"

# 2. Pack modified/staged/untracked Android Studio files (or --feature <Name>) into 1 secret-scrubbed .md bundle
#    (Then open a NEW external AI chat, attach or paste via Ctrl+V, and send)
python .agents/harness.py web-pack --dirty --prompt "Complete refactor and unit tests"

# 3. Preview the external AI's HARNESS_WEB_MERGE_V1 reply with zero disk writes, then apply
python .agents/harness.py web-apply --dry-run
python .agents/harness.py web-apply --source developer_terminal --proof-reference "Apply web merge"
```

### Core Invariants
- **At most three disjoint live tasks per worktree**: Reserve explicit files for each task; pending and ready tasks count. Use `python .agents/harness.py task switch --task-id <id>` to select focus. A fourth task is blocked until one is delivered or cancelled.
- **Model never executes Git mutations**: Git operations are strictly developer-owned.
- **Lineage enforcement**: Validated handoff checkpoints and verified disjoint sibling commits are accepted; unrelated or mixed unverified commits remain lineage violations.
- **Final review required**: Even when all phase reviews pass cleanly, final integration review remains required.
