# Update prompt

Paste **this entire file** as the first message in a **new chat on your Android app** (already has `.agents` from a previous install). The agent must execute it, not summarize it.

---

You are **updating** the portable Android AI harness in **this** checkout. This folder is the Android product. It is not `android-harness-kit`.

Answer in the developer's language. Do not commit unless they ask.

Tell the developer **first**, in their language: this update needs a **strong reasoning model** in this chat (such as `Claude Sonnet 4.6 (Thinking)` / `Claude Opus 4.6`, `Gemini 3.1 Pro`, `GPT-OSS 120B`), not a fast/lightweight one without deep reasoning. Re-port is structural. A weak model copies files and skips leftover grep. Stay until selftest `Total test failures: 0`. If this chat is a small model, **stop** and start a new chat on a stronger model, then paste this file again.

This is not a first install. Do **not** treat it as a blank product. Reuse recorded setup answers. Re-port the new engine. Do not only copy files and stop.

## Start now

1. Confirm this repo has `gradlew` or `gradlew.bat` **and** `.agents/`. If `.agents/` is missing, stop and tell them to paste `docs/install-prompt.md` instead.
2. Ask **U.0** with choices: `Back up and update` / `Stop`. Wait. If Stop, do nothing.
3. Backup first (same layout as setup): timestamp `YYYYMMDD-HHMMSS`. Copy current `.agents` and harness-owned adapters into `<repo>/.harness-backup/<timestamp>/`. Print the path. If backup fails, **stop**. Copy `<kit>/docs/rollback-prompt.md` into that backup folder when the kit is available.
4. Get the **latest** kit (do **not** clone into `app/`, `composeApp/`, or any module source tree):
   - If a clone already exists nearby: `git fetch` and `git pull` on `main` in that clone. Print the new commit.
   - Else: `git clone https://github.com/rabee-elkholy/android-harness-kit.git` into a sibling folder or the OS temp directory.
   - Do **not** reuse a stale clone without pulling.
5. If `.harness-setup/answers.json` exists, print it. Ask **U.1** with a full prompt: keep these answers, or run `setup_wizard.py` again to change some. Do not use a two-word title.
6. If they change answers, run `<kit>/agents/scripts/setup_wizard.py --repo <this-android-root> --lang <ar|en>` (or `questions` + print `auto_blurb` + verbatim `ask_question` prompts for **only** the JSON `questions` list + `write`). Copy the new `.harness-setup/SETUP_ANSWERS.md` into the backup folder.
7. Note extra paths under current `.agents/` that the kit `agents/` folder does **not** ship (custom skills they added). Those must be restored from backup after the copy.
8. Copy `<kit>/agents/` → `<this repo>/.agents/`. Empty `state/`. Then run `install_zoho_mcp.py` from recorded I.16 (`--enable` or `--disable`). Never copy a Zoho token file. Do not overwrite the developer's Continue / Aider / `kilo.jsonc` / `~/.gemini` configs.
9. Restore extra non-kit paths from the backup into `.agents/` (custom skills only). Do **not** restore old kit files on top of the new copy.
10. Open `<kit>/docs/setup-prompt.md` and run **from “3) Port structurally” through verify** using the recorded answers. Discover from disk again (module/package may have changed). Leftover grep must pass. Run `install_tool_adapters.py` with the recorded `--tools` (and `--product`, `--py`, `--assemble`, `--device-policy`, `--git-policy`).
11. `$PY .agents/scripts/_hook_selftest.py` → `Total test failures: 0`. Then `$PY .agents/scripts/preflight_check.py`.
12. Tell them to start a **new chat** on this Android folder. Rollback = `docs/rollback-prompt.md`.

Do not copy `local.properties` `sdk.dir` or `~/.gemini` hostnames. `adb monkey` stays denied. Emulator deny only if I.4 is physical-only.

Begin: print OS, this repo path, whether `.agents` exists, and then U.0.
