# Update prompt

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/update-prompt.md`  
> **Kit Repository**: `https://github.com/rabee-elkholy/android-harness-kit.git`
> **Kit version**: `v0.12.0` — **SHA-256**: `b88f617273cea07ee7d2a6f47ef13dd8858d96064918da5f50bb73f3507bf063` (SHA-256 of every byte after this line; verify first — mismatch = STOP)
Paste **this entire file** as the first message in a **new chat on your Android app** (already has `.agents` from a previous install). The agent must execute it, not summarize it.

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

You are **updating** the portable Android AI harness in **this** checkout. This folder is the Android product. It is not `android-harness-kit`.

Answer in the developer's language. Do not commit unless they ask.

Tell the developer **first**, in their language: this update needs a **strong reasoning model** in this chat (such as Anthropic `Claude Opus 5 / 3.7 Sonnet (Thinking)`, Google `Gemini 3.1 Pro (Deep Think)`, OpenAI `GPT-5.6 Sol / o3`, or DeepSeek `DeepSeek-V4 Pro / R1`), not a fast/lightweight one without deep reasoning. Re-port is structural. A weak model copies files and skips leftover grep. Stay until selftest `Total test failures: 0`. If this chat is a small model, **stop** and start a new chat on a stronger model, then paste this file again.

This is not a first install. Do **not** treat it as a blank product. Reuse recorded setup answers. Re-port the new engine. Do not only copy files and stop.

## Start now

1. Confirm this repo has `gradlew` or `gradlew.bat` **and** `.agents/`. If `.agents/` is missing, stop and tell them to paste `docs/install-prompt.md` instead.
2. **Single-Backup Retention**:
   - **Prune Old Backups**: Inspect `<repo>/.harness-backup/`. If any older backup folders exist, remove them first so that **strictly only ONE backup copy** (the immediate previous version) is retained, avoiding disk bloat.
   - **Create Backup**: Timestamp `YYYYMMDD-HHMMSS`. Copy current `.agents` and harness-owned adapters into `<repo>/.harness-backup/<timestamp>/`. Print the backup path in chat.
   - If backup fails, **STOP IMMEDIATELY**.
   - Copy `<kit>/docs/rollback-prompt.md` into that backup folder. Tell the developer: *"A rollback backup was saved. If you do not like this update at any point, simply paste `docs/rollback-prompt.md` in a new chat to restore your previous version."*
3. **Get the Latest Kit (Remote & Local Support)**:
   - Preferred: run `android-harness update --repo <this-android-root>`. It resolves the latest release tag, fetches that exact tag, checks it out detached, and verifies `agents/VERSION`; it never pulls `main`.
   - For a manual update, fetch tags, choose the requested release tag, check it out detached, and verify `agents/VERSION` equals the tag version:
     ```bash
     git -C <kit> fetch origin --tags --prune
     git -C <kit> checkout --detach v<requested-version>
     ```
   - Do **not** copy from a named branch or a stale unverified clone. Do **not** clone into `app/`, `composeApp/`, or any module source tree.
4. If `.harness-setup/answers.json` exists, print it. Ask **U.1** with a full prompt: keep these answers, or run `setup_wizard.py` again to change some. Do not use a two-word title.
5. If they change answers, run `<kit>/agents/scripts/setup_wizard.py --repo <this-android-root> --lang <ar|en>` (or `questions` + print `auto_blurb` + verbatim `ask_question` prompts for **only** the JSON `questions` list + `write`). Copy the new `.harness-setup/SETUP_ANSWERS.md` into the backup folder.
6. **Identify Custom Files to Preserve**: Note extra paths under current `.agents/` that the kit `agents/` folder does **not** ship (custom skills and tailored domain references in `skills/android-harness/references/`).
7. **Copy New Engine & Restore State**:
   - Copy `<kit>/agents/` → `<this repo>/.agents/`.
   - Empty `.agents/state/` and ensure `.gitkeep` exists.
   - Restore extra non-kit paths and custom domain reference files from the backup into `.agents/` (do **not** restore old kit scripts over new ones).
   - Run `install_zoho_mcp.py` from recorded I.16 (`--enable` or `--disable`). Never copy a Zoho token file.
8. **Port Product Constants & Adapters (Strict Order — DO NOT run selftest yet)**:
   - **Immediately write `.agents/scripts/_product.py`** using recorded facts from `answers.json` or backup (product name, applicationId, launcher, assemble task, device policy, PM_PROVIDER).
   - **Port foundation references** (`architecture-mvi.md`, `ui-compose-theme.md`, `room-database-migrations.md`, `daily-scenarios.md`) using recorded project facts. (Note: DO NOT ask the developer to re-approve domain references via `ask_question` during an update; they were approved during initial install).
   - **Run tool adapters**: `$PY .agents/scripts/install_tool_adapters.py --product <I.1> --py <I.2> --assemble <I.5> --device-policy <I.4> --git-policy <I.3> --tools <I.14> <git_gate_flag>`. This automatically registers `.githooks/` into `.git/info/exclude` to keep local hooks strictly machine-local.
9. **Verify & Diagnostics (Run in order)**:
   - `$PY .agents/scripts/_hook_selftest.py` → must report `Total test failures: 0`.
   - `$PY .agents/scripts/preflight_check.py` → application checks.
   - `$PY .agents/scripts/harness_doctor.py` → run once and wait for completion without launching duplicate background tasks. Must report 0 critical failures.
10. **Tell the developer**:
    - Inform them that `.githooks/` is automatically excluded in `.git/info/exclude` to protect team repositories from local git hook churn.
    - If `harness_doctor.py` reported uncommitted changes, advise the developer in their language to review and commit their updated harness files (`.agents/`, `AGENTS.md`):
      ```bash
      git add .
      git commit -m "chore: update android harness kit"
      ```
    - Tell them to start a **new chat** on this Android folder before starting daily work.
    - System diagnostics = `python .agents/scripts/harness_doctor.py` (or execute `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/diagnostic-prompt.md`), Rollback = `.harness-backup/<timestamp>/rollback-prompt.md` (or `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/rollback-prompt.md`).

Do not copy `local.properties` `sdk.dir` or `~/.gemini` hostnames. `adb monkey` stays denied. Emulator deny only if I.4 is physical-only.

Begin: print OS, this repo path, whether `.agents` exists, and then U.0.
