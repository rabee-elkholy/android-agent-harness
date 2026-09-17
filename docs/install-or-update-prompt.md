# Android Agent Harness chat installer
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v1.0.42` — **SHA-256**: `ebb74b505c3c2e050e9c8bb32cdb85daca9ec98b2244ea28a8df31833b966df4` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with. If truncated, STOP. Never bypass hooks. Keep files in English. Run commands directly; use `ask_question` for approvals.

## Phase 1: Read-only discovery
Do not mutate, download, build, install, or remove.
1. Require root `gradlew` or `gradlew.bat`; otherwise STOP.
2. Select one lifecycle:
   - **Clean Install**: no `.agents` and no v1 ownership.
   - **Same-Major Update**: `.harness-setup/ownership-v1.json` has architecture major 1.
   - **Legacy Replacement**: `.agents` exists without v1 ownership.
3. `<kit-dir>` is `%USERPROFILE%\.android-harness\kit` (Windows) or `~/.android-harness/kit`. Reuse only at detached `v1.0.42` with matching version and checksum `files`.

## Phase 2: Kit bootstrap approval
If cache is invalid, show staging, kit, rollback paths and commands:
```text
git clone --depth 1 --branch v1.0.42 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git <staging-dir>
git -C <staging-dir> describe --tags --exact-match
python <staging-dir>/harness_cli.py version --kit <staging-dir>
```
Staging atomically replaces `<kit-dir>`; rollback is `<kit-dir>.previous`.
**STOP AND WAIT FOR EXPLICIT KIT BOOTSTRAP APPROVAL.** Permits cache operations only, not app installation/removal. Verify tag, version, checksum `files`; promote with rollback.

## Phase 3: Authoritative interview
Run: `python <kit-dir>/agents/scripts/setup_wizard.py questions --repo <app-root>`
The setup wizard payload is the sole interview authority. Ask **only** the questions returned. Respect options and `recommended`/`previous` (1 per question).

## Phase 3.5: Read-only project context preview
Run in read-only mode (zero mutations to repo or graph cache):
`python <kit-dir>/harness_cli.py context preview --repo <app-root>`
Show discovered DI, ViewModel base, Room, UI, capabilities, architecture families, legacy overrides.
Confirm via `ask_question`: "Do you confirm the discovered project architecture context?"
- `(Recommended) Confirm discovered project context`
- `Flag incorrect detection / review before continuing`
Model must not auto-mutate facts/notes; developer refines answers or edits `project-notes.md` post-install. Confirms context only; no repo mutation.

## Phase 4: Lifecycle approval and execution
Show lifecycle, tag, paths, preserved files, command below. CLI snapshots files and rolls back on change.
**STOP AND WAIT FOR EXPLICIT DEVELOPER APPROVAL.** Bootstrap and context confirmation are not lifecycle approval. Before approval, do not mutate anything.
After approval, create `<temp-answers>.json` outside `<app-root>`, then run one path:
```text
Clean Install: python <kit-dir>/harness_cli.py init --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json
Same-Major Update: python <kit-dir>/harness_cli.py update --no-refresh --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json
Legacy Replacement: python <kit-dir>/harness_cli.py init --replace-legacy --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json
```
Legacy replacement is atomic; keeps `project-notes.md`, migrates legacy customizations to `legacy-overrides/`, retains Zoho `workflow_defaults.json`.

## Phase 5: Verification
Run in foreground without timers:
```text
python <kit-dir>/harness_cli.py doctor --install-check --repo <app-root> --kit <kit-dir> --json
python <kit-dir>/harness_cli.py version --kit <kit-dir>
```
On failure report recovery. On success show version, lifecycle, checks, and `0` changed app files; then say: “Android Agent Harness is successfully configured. Open a NEW chat at the project root.”
