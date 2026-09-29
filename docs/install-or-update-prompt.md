# Android Agent Harness chat installer
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v1.1.8`

Never bypass hooks. Keep files in English. Run commands directly; use `ask_question` for approvals. Short on purpose: the kit prints Phases 3-5.

## Phase 1: Read-only discovery
Pick the mode; never delete project files.
- INSTALL: no `.agents` and no `.harness-setup`. An app-owned `.agents`: STOP, the developer moves it first.
- UPDATE: `.harness-setup/ownership-v1.json` exists. If `.agents/VERSION` is not older than `<version>` (this header), STOP (up to date).
Require a root Gradle Wrapper. If `.agents/state/active-task.json` names a task not DELIVERED or CANCELLED, STOP: the developer finishes or cancels it in their own terminal.

## Phase 2: Kit bootstrap approval
`<cache-root>` is `~/.android-harness`; `<kit-dir>` is `<cache-root>/kit` at detached `v1.1.8`; `<staging-dir>` is `<cache-root>/kit-stage-<version>-<nonce>`. Both MUST NOT be inside `<app-root>`; both stay external to the app repository. Never run a clone command without an explicit destination. Never clone to `<app-root>/android-agent-harness` or `<app-root>/kit`.
**STOP AND WAIT FOR EXPLICIT KIT BOOTSTRAP APPROVAL.** Permits cache operations only, not app installation/removal. Then run:
1. `git clone --depth 1 --branch v1.1.8 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git <staging-dir>`
2. `python <staging-dir>/harness_cli.py kit-promote --staging <staging-dir>` (checks `describe --tags --exact-match`, keeps the old kit as `<kit-dir>.previous`)
3. `python <kit-dir>/harness_cli.py chat-steps --repo <app-root>`: follow the Phases 3-5 it prints.
END OF PAGE (Phases 1-2).
