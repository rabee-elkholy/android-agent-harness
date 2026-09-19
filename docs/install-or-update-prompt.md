# Android Agent Harness chat installer
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v1.0.50`

---
Never bypass hooks. Keep files in English. Run commands directly; use `ask_question` for approvals.

## Phase 1: Read-only discovery
Require root `gradlew`/`gradlew.bat`; else STOP.
Active task check: If `.agents/state/active-task.json` exists with an active task, STOP immediately. Tell developer:
"An active task `<id>` is currently recorded. Please finish or cancel it before updating: `python .agents/scripts/workflow.py cancel --repo . --task-id <id>`". Do NOT search the repository or try to resume the active task.
Select:
- **Clean Install**: no `.agents`
- **Same-Major Update**: `.harness-setup/ownership-v1.json` major 1
- **Legacy Replacement**: `.agents` exists without v1 ownership
`<kit-dir>` is `%USERPROFILE%\.android-harness\kit` or `~/.android-harness/kit` at detached `v1.0.50`.

## Phase 2: Kit bootstrap approval
`git clone --depth 1 --branch v1.0.50 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git <staging-dir>`
Verify: `git -C <staging-dir> describe --tags --exact-match && python <staging-dir>/harness_cli.py version --kit <staging-dir>`
Staging replaces `<kit-dir>`; rollback is `<kit-dir>.previous`.
**STOP AND WAIT FOR EXPLICIT KIT BOOTSTRAP APPROVAL.** Permits cache operations only, not app installation/removal.

## Phase 3: Authoritative interview
Run: `python <kit-dir>/agents/scripts/setup_wizard.py questions --repo <app-root>`
The setup wizard payload is the sole interview authority. Ask **only** the questions returned; respect `recommended` (1 per question). Context preview: `python <kit-dir>/harness_cli.py context preview --repo <app-root>`.

## Phase 4: Lifecycle approval and execution
**STOP AND WAIT FOR EXPLICIT DEVELOPER APPROVAL.**
create `<temp-answers>.json` outside `<app-root>`, then run:
- Clean Install: `python <kit-dir>/harness_cli.py init --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json`
- Same-Major Update: `python <kit-dir>/harness_cli.py update --no-refresh --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json`
- Legacy Replacement: `python <kit-dir>/harness_cli.py init --replace-legacy --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json`

## Phase 5: Verification
`python <kit-dir>/harness_cli.py doctor --install-check --repo <app-root> --kit <kit-dir> --json && python <kit-dir>/harness_cli.py version --kit <kit-dir>`
On success show 0 changed app files and say: “Android Agent Harness is successfully configured. Open a NEW chat at the project root.”
