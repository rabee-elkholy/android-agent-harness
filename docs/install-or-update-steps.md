# Android Agent Harness chat installer: Phases 3-5

Printed by `python <kit-dir>/harness_cli.py chat-steps --repo <app-root>` after Phase 2 of `install-or-update-prompt.md`, with this installation's paths filled in. Keep following it exactly.

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
END OF STEPS (Phases 3-5).
