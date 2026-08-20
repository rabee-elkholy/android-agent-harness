# Rollback prompt

Paste **this entire file** to the agent if you want the previous system restored.

---

You are rolling back the Android AI harness install on THIS checkout. The developer may use **any** coding agent (Claude Code, Codex, Antigravity, Cursor, Copilot, Qwen, Windsurf, Cline, Kilo, Goose, …) on **macOS**, **Windows**, or **Linux**.

Backups: `<repo>/.harness-backup/` and `$HOME/.harness-backups/` (or `$HOME/.gemini/harness-backups/`) as recorded in `MANIFEST.md`.

## Rules

- Do **not** delete backup folders.
- Do **not** restore `local.properties`, Android SDK, or Gradle caches.
- Do **not** commit unless asked.
- Answer in the developer's language.
- After restore, they must start a **new** chat session in the same tool.

## Steps

1. Open the newest `.harness-backup/*/MANIFEST.md` unless they name a timestamp. Print the path.
2. Follow the manifest exactly.
3. Project restore:
   - `.agents` from `project-agents`, or delete `.agents` if it did not exist
   - `.claude` / `.codex` / `.cursor` / `.github` / `.windsurf` / `.roo` / `.amazonq` / `.continue` / `.junie` / `.kilocode` the same way if those backup folders exist
   - overwrite repo-root files from `project-root-files/` (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CODEX.md`, `QWEN.md`, `.clinerules`, `.windsurfrules`, `.goosehints`, …)
4. User-config restore from `geminiBackupPath` / user backup path in the manifest only for files that existed before:
   - `~/.gemini/config/config.json` and `rules/`
   - `~/.claude/settings.json` and `settings.local.json`
   - `~/.codex/config.toml` (or json)
   - If a file did **not** exist before: delete only what this kit added. Never wipe `~/.claude` or `~/.gemini` entirely.
5. Confirm restored paths in chat.

If no backup exists, stop. Do not invent files.
