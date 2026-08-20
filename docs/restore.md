# Restore (manual)

Use this if the new harness is not what you wanted. **Do not delete** `.harness-backup` or `$HOME/.harness-backups`.

## Fastest path

Paste [`rollback-prompt.md`](rollback-prompt.md) into the same agent (any tool that can edit this checkout).

## Manual steps

1. Read `.harness-backup/<timestamp>/MANIFEST.md`
2. `.agents`: restore `project-agents`, or delete `.agents` if it did not exist before setup
3. Same idea for `.claude` / `.codex` / `.cursor` / `.github` / `.windsurf` / `.roo` / `.amazonq` / `.continue` / `.junie` / `.kilocode` from the backup folders
4. Restore root files from `project-root-files/` (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CODEX.md`, `QWEN.md`, `.clinerules`, `.windsurfrules`, `.goosehints`, …)
5. Restore user settings from the path in the manifest:
   - `~/.gemini/config/` if Antigravity existed
   - `~/.claude/settings.json` and `settings.local.json` if Claude existed
   - `~/.codex/config.toml` if Codex existed
6. Open a **new session** in the same tool

Do not restore `local.properties` or the SDK — those belong to this machine.
