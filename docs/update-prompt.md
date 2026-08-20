# Update prompt

Paste **this entire file** as the first message in a **new chat on your Android app** (already has `.agents` from a previous install). The agent must execute it, not summarize it.

---

You are **updating** the portable Android AI harness in **this** checkout. This folder is the Android product. It is not `android-harness-kit`.

Answer in the developer's language. Do not commit unless they ask.

This is not a first install. Do **not** treat it as a blank product. Reuse recorded setup answers. Re-port the new engine. Do not only copy files and stop.

## Start now

1. Confirm this repo has `gradlew` or `gradlew.bat` **and** `.agents/`. If `.agents/` is missing, stop and tell them to paste `docs/install-prompt.md` instead.
2. Ask **U.0** with choices: `Back up and update` / `Stop`. Wait. If Stop, do nothing.
3. Backup first (same layout as setup): timestamp `YYYYMMDD-HHMMSS`. Copy current `.agents` and harness-owned adapters into `<repo>/.harness-backup/<timestamp>/`. Print the path. If backup fails, **stop**. Copy `<kit>/docs/rollback-prompt.md` into that backup folder when the kit is available.
4. Get the **latest** kit (do **not** clone into `app/`, `composeApp/`, or any module source tree):
   - If a clone already exists nearby: `git fetch` and `git pull` on `main` in that clone. Print the new commit.
   - Else: `git clone https://github.com/rabee-elkholy/android-harness-kit.git` into a sibling folder or the OS temp directory.
   - Do **not** reuse a stale clone without pulling.
5. Read the newest `.harness-backup/*/SETUP_ANSWERS.md` (or the one from the backup you just made if it stored answers). Print the recorded I.1–I.14 in chat.
6. Ask **U.1** with choices: `Keep these answers and update` / `I will change some answers`. If they change some, interview **only** the items they name (same I.* choices as setup). Record a new `SETUP_ANSWERS.md` in the new backup folder.
7. Note extra paths under current `.agents/` that the kit `agents/` folder does **not** ship (custom skills they added). Those must be restored from backup after the copy.
8. Copy `<kit>/agents/` → `<this repo>/.agents/`. Empty `state/`. Keep `.agents/mcp_config.json` as `{"mcpServers": {}}`. Do not add MCP servers. Do not overwrite the developer's MCP / Continue / Aider / `kilo.jsonc` / `~/.gemini` configs.
9. Restore extra non-kit paths from the backup into `.agents/` (custom skills only). Do **not** restore old kit files on top of the new copy.
10. Open `<kit>/docs/setup-prompt.md` and run **from “3) Port structurally” through verify** using the recorded answers. Discover from disk again (module/package may have changed). Leftover grep must pass. Run `install_tool_adapters.py` with the recorded `--tools` (and `--product`, `--py`, `--assemble`, `--device-policy`, `--git-policy`).
11. `$PY .agents/scripts/_hook_selftest.py` → `Total test failures: 0`. Then `$PY .agents/scripts/preflight_check.py`.
12. Tell them to start a **new chat** on this Android folder. Rollback = `docs/rollback-prompt.md`.

Do not copy `local.properties` `sdk.dir` or `~/.gemini` hostnames. `adb monkey` stays denied. Emulator deny only if I.4 is physical-only.

Begin: print OS, this repo path, whether `.agents` exists, and then U.0.
