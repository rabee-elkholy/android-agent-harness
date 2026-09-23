# Android Agent Harness chat installer
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v1.0.61`

---
Never bypass hooks. Keep files in English. Run commands directly; use `ask_question` for approvals.

## Phase 1: Read-only discovery
This v1.0.60 onboarding performs CLEAN INSTALL only.

Require:
- root Gradle Wrapper
- no active Harness task
- no existing managed `.agents`
- no incompatible `.harness-setup`

If an existing Harness installation is detected:
STOP.

Tell the developer to remove/uninstall the old Harness first, then rerun the clean installer. Do not auto-delete project files.

Active task check: If `.agents/state/active-task.json` exists with an active task, STOP immediately. Tell developer:
"An active task `<id>` is currently recorded. Please finish or cancel it before updating: `python .agents/scripts/workflow.py cancel --repo . --task-id <id>`". Do NOT search the repository or try to resume the active task.

Path and Location Rules:
`<cache-root>` is `%USERPROFILE%\.android-harness` or `~/.android-harness`.
`<version>` is `v1.0.60`.
`<kit-dir>` is `<cache-root>\kit` or `<cache-root>/kit` at detached `v1.0.61`.
`<staging-dir>` is `<cache-root>\kit-stage-<version>-<nonce>` or `<cache-root>/kit-stage-<version>-<nonce>`.
`<kit-dir>` and `<staging-dir>` MUST NOT be inside `<app-root>`. Both must be strictly external to the app repository.
Never run a clone command without an explicit destination.
Never clone to `<app-root>/android-agent-harness`, `<app-root>/kit`, or `<app-root>/kit-stage-*`.

## Phase 2: Kit bootstrap approval
Read-only path check before clone: Resolve `<app-root>`, `<kit-dir>`, and `<staging-dir>`.
STOP if `<kit-dir>` or `<staging-dir>` is equal to or contained by `<app-root>`.
Command with explicit external destination:
`git clone --depth 1 --branch v1.0.61 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git <staging-dir>`
Verify: `git -C <staging-dir> describe --tags --exact-match`
Verify version: `python <staging-dir>/harness_cli.py version --kit <staging-dir>`
Staging replaces `<kit-dir>`; rollback is `<kit-dir>.previous`.
**STOP AND WAIT FOR EXPLICIT KIT BOOTSTRAP APPROVAL.** Permits cache operations only, not app installation/removal.

## Phase 3: Authoritative interview
Run: `python <kit-dir>/agents/scripts/setup_wizard.py questions --repo <app-root>`
The setup wizard payload is the sole interview authority. Ask **only** the questions returned; respect `recommended` (1 per question). Context preview: `python <kit-dir>/harness_cli.py context preview --repo <app-root>`.
- For AI host: select **Google Antigravity** (`antigravity`).
- No model selection or escalation questions are asked; reviewer model is inherited by omission.
- For Reviewer Call Safety Cap: select recommended default of `20`.
If a question contains `conditional_text_input`, and the selected option equals `when_option`, ask exactly that nested prompt and save the value under `answer_key`. Do not invent any other follow-up questions.

## Phase 4: Lifecycle approval and execution
**STOP AND WAIT FOR EXPLICIT DEVELOPER APPROVAL.**
create `<temp-answers>.json` outside `<app-root>`, then run:
`python <kit-dir>/harness_cli.py init --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json`
The installer takes a pre-install application backup, installs `.agents/hooks.json`, writes Antigravity reviewer agent definitions to `.agents/agents/<reviewer>/agent.md`, and generates `GEMINI.md`.

## Phase 5: Verification
Run: `python <kit-dir>/harness_cli.py doctor --install-check --repo <app-root> --kit <kit-dir> --json`
Doctor validates `.agents/hooks.json`, all 7 custom reviewer agents in `.agents/agents/`, Review Protocol V2, and runtime root paths.
Optionally verify kit version: `python <kit-dir>/harness_cli.py version --kit <kit-dir>`
On success show 0 changed app files and say: “Android Agent Harness is successfully configured. Open a NEW chat at the project root.”
