# Android Agent Harness chat installer
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v1.1.6`

---
Never bypass hooks. Keep files in English. Run commands directly; use `ask_question` for approvals.

## Phase 1: Read-only discovery
Pick the mode; never delete project files.
- INSTALL: no `.agents` and no `.harness-setup`. An app-owned `.agents`: STOP, the developer moves it first.
- UPDATE: `.harness-setup/ownership-v1.json` exists. Installed version is `.agents/VERSION`; if it is not older than `<version>`, STOP (up to date).
Require a root Gradle Wrapper.

Active task check: If `.agents/state/active-task.json` points to a task that is not DELIVERED or CANCELLED, STOP. Tell the developer to finish it, or cancel it in their own terminal: `python .agents/scripts/workflow.py cancel --repo . --task-id <id>`. Do not resume or search.

Path and Location Rules:
`<cache-root>` is `%USERPROFILE%\.android-harness` or `~/.android-harness`.
`<version>` is the Kit version shown in the header above.
`<kit-dir>` is `<cache-root>\kit` or `<cache-root>/kit` at detached `v1.1.6`.
`<staging-dir>` is `<cache-root>\kit-stage-<version>-<nonce>` or `<cache-root>/kit-stage-<version>-<nonce>`.
`<kit-dir>` and `<staging-dir>` MUST NOT be inside `<app-root>`; both stay external to the app repository.
Never run a clone command without an explicit destination.
Never clone to `<app-root>/android-agent-harness`, `<app-root>/kit`, or `<app-root>/kit-stage-*`.

## Phase 2: Kit bootstrap approval
STOP if `<kit-dir>` or `<staging-dir>` is equal to or inside `<app-root>`.
`git clone --depth 1 --branch v1.1.6 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git <staging-dir>`
Verify: `git -C <staging-dir> describe --tags --exact-match`
Verify version: `python <staging-dir>/harness_cli.py version --kit <staging-dir>`
Staging replaces `<kit-dir>`; rollback is `<kit-dir>.previous`.
**STOP AND WAIT FOR EXPLICIT KIT BOOTSTRAP APPROVAL.** Permits cache operations only, not app installation/removal.

## Phase 3: Authoritative interview (INSTALL only)
UPDATE keeps the saved answers; skip to Phase 4.
Run: `python <kit-dir>/agents/scripts/setup_wizard.py questions --repo <app-root>`
The setup wizard payload is the sole interview authority. Ask **only** the questions returned; respect `recommended` (1 per question); answers use each option's `id`. Context preview: `python <kit-dir>/harness_cli.py context preview --repo <app-root>`.
- AI host: default **Google Antigravity** (`antigravity`). No model questions; reviewers inherit the model.
- Reviewer Call Safety Cap: the recommended `20`.
If a question contains `conditional_text_input` and the selected option equals `when_option`, ask exactly that nested prompt and save it under `answer_key`.

## Phase 4: Lifecycle approval and execution
**STOP AND WAIT FOR EXPLICIT DEVELOPER APPROVAL.**
INSTALL: create `<temp-answers>.json` outside `<app-root>`, then run:
`python <kit-dir>/harness_cli.py init --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json`
It backs up the app, installs `.agents/` and each selected host's files: Antigravity `.agents/hooks.json`, `.agents/agents/<reviewer>/agent.md`, `GEMINI.md`; Claude Code `CLAUDE.md`, `.claude/agents/`, `.claude/settings.json` hook.
UPDATE: `python <kit-dir>/harness_cli.py update --repo <app-root> --kit <kit-dir> --no-refresh`
It keeps state, tasks, answers, notes and developer instructions, and rolls back on failure. If it names user-modified managed files, show them and STOP; never delete or overwrite them.

## Phase 5: Verification
Run: `python <kit-dir>/harness_cli.py doctor --install-check --repo <app-root> --kit <kit-dir> --json`
Doctor validates the harness and each selected host's adapter (Antigravity: hooks, 7 reviewers in `.agents/agents/`, Review Protocol V2).
On success show 0 changed app files and the installed version, and say: “Android Agent Harness is ready. Open a NEW chat at the project root.”
END OF PROMPT (5 phases).
