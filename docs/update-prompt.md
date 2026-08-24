# Update prompt

Paste **this entire file** as the first message in a **new chat on your Android app** (already has `.agents` from a previous install). The agent must execute it, not summarize it.

---

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
3. Get the **latest** kit (do **not** clone into `app/`, `composeApp/`, or any module source tree):
   - If a clone already exists nearby: `git fetch` and `git pull` on `main` in that clone. Print the new commit.
   - Else: `git clone https://github.com/rabee-elkholy/android-harness-kit.git` into a sibling folder or the OS temp directory.
   - Do **not** reuse a stale clone without pulling.
4. If `.harness-setup/answers.json` exists, print it. Ask **U.1** with a full prompt: keep these answers, or run `setup_wizard.py` again to change some. Do not use a two-word title.
5. If they change answers, run `<kit>/agents/scripts/setup_wizard.py --repo <this-android-root> --lang <ar|en>` (or `questions` + print `auto_blurb` + verbatim `ask_question` prompts for **only** the JSON `questions` list + `write`). Copy the new `.harness-setup/SETUP_ANSWERS.md` into the backup folder.
6. Note extra paths under current `.agents/` that the kit `agents/` folder does **not** ship (custom skills they added). Those must be restored from backup after the copy.
7. Copy `<kit>/agents/` → `<this repo>/.agents/`. Empty `state/`. Then run `install_zoho_mcp.py` from recorded I.16 (`--enable` or `--disable`). Never copy a Zoho token file. Do not overwrite the developer's Continue / Aider / `kilo.jsonc` / `~/.gemini` configs.
8. Restore extra non-kit paths from the backup into `.agents/` (custom skills only). Do **not** restore old kit files on top of the new copy.
9. Open `<kit>/docs/setup-prompt.md` and run **from “3) Port structurally” through verify** using the recorded answers. Discover from disk again (module/package may have changed). Leftover grep must pass. Run `install_tool_adapters.py` with the recorded `--tools` (and `--product`, `--py`, `--assemble`, `--device-policy`, `--git-policy`).
10. `$PY .agents/scripts/_hook_selftest.py` → `Total test failures: 0`. Then `$PY .agents/scripts/preflight_check.py` and `$PY .agents/scripts/harness_doctor.py`.
11. Tell them to start a **new chat** on this Android folder. System diagnostics = `docs/diagnostic-prompt.md`, Rollback = `docs/rollback-prompt.md`.

Do not copy `local.properties` `sdk.dir` or `~/.gemini` hostnames. `adb monkey` stays denied. Emulator deny only if I.4 is physical-only.

Begin: print OS, this repo path, whether `.agents` exists, and then U.0.
