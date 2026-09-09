# Android Agent Harness chat installer
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v1.0.6` — **SHA-256**: `a325cd729734bf861861eab9757ccf19fe5b9cbf869c9e18e30a41fc3377397b` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.
If truncated, STOP. Never bypass hooks or use floating `main`. Speak developer's language; keep files in English.
Run all commands directly; never demand terminal execution. Universally use `ask_question` for all approvals and decisions.

## Phase 1: Read-only discovery
Do not mutate, download, build, install, or remove.

1. Require root `gradlew` or `gradlew.bat`; otherwise STOP.
2. Select one lifecycle:
   - **Clean Install**: no `.agents` and no v1 ownership.
   - **Same-Major Update**: `.harness-setup/ownership-v1.json` has architecture major 1.
   - **Legacy Replacement**: `.agents` exists without v1 ownership.
3. `<kit-dir>` is `%USERPROFILE%\.android-harness\kit` (Windows) or `~/.android-harness/kit`. Reuse only at detached `v1.0.5` with matching version and checksum `files`.

## Phase 2: Kit bootstrap approval
If cache is invalid, show expanded staging, kit, rollback paths and commands:

```text
git clone --depth 1 --branch v1.0.5 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git <staging-dir>
git -C <staging-dir> describe --tags --exact-match
python <staging-dir>/harness_cli.py version --kit <staging-dir>
```

Verified staging atomically replaces `<kit-dir>`; rollback is `<kit-dir>.previous`.

**STOP AND WAIT FOR EXPLICIT KIT BOOTSTRAP APPROVAL.** This permits only displayed cache operations, not app installation/removal. After approval verify tag, version, checksum `files`, symlinks, and path boundaries before importing code; promote with rollback. Never improvise a downloader.

## Phase 3: Authoritative interview
Run once:

```text
python <kit-dir>/agents/scripts/setup_wizard.py questions --repo <app-root>
```

The setup wizard payload is the sole interview authority. Show `auto_blurb`. Ask **only** the questions returned. Respect dependencies/options and `recommended`/`previous`; show one recommendation per single-choice question. Do not repeat discovery.

## Phase 4: Lifecycle approval and execution
Show lifecycle, immutable tag, cache/target paths, adapters, preserved references/defaults, and the one exact expanded command below. State that the CLI snapshots all non-harness app files and rolls back if any changes.

**STOP AND WAIT FOR EXPLICIT DEVELOPER APPROVAL.** Bootstrap approval is not lifecycle approval. Before approval, do not create answers, install, update, or remove anything.

After approval, create `<temp-answers>.json` in the OS temp directory, outside `<app-root>`, then run one path:

```text
Clean Install: python <kit-dir>/harness_cli.py init --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json
Same-Major Update: python <kit-dir>/harness_cli.py update --no-refresh --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json
Legacy Replacement: python <kit-dir>/harness_cli.py init --replace-legacy --repo <app-root> --kit <kit-dir> --answers-json <temp-answers>.json
```

Legacy replacement is one atomic process; never uninstall legacy separately. It preserves project-specific reference Markdown and Zoho `workflow_defaults.json`. The CLI removes temporary answers.

## Phase 5: Verification
Run in foreground without timers:

```text
python <kit-dir>/harness_cli.py doctor --install-check --repo <app-root> --kit <kit-dir> --json
python <kit-dir>/harness_cli.py version --kit <kit-dir>
```

On failure report recovery. On success show version, lifecycle, checks, preserved files, and `0` changed app files; then say: “Android Agent Harness is successfully configured. Open a NEW chat at the project root.”
