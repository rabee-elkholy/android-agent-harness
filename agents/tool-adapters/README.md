# Tool adapters

These files are copied into the **application repo** (not into `.agents`) so popular coding agents pick up the same harness without extra setup.

`install_tool_adapters.py` fills `{{PRODUCT}}`, `{{PY}}`, `{{ASSEMBLE}}`, `{{DEVICE_POLICY}}`, and `{{GIT_POLICY}}`.

The installer writes **only** the tools passed in `--tools` (plus `AGENTS.md`). Re-run with a new list to add a tool. It does **not** overwrite `.aider.conf.yml`, Continue user config, `kilo.jsonc`, or `~/.gemini`. Zoho Sprints MCP is a separate script (`install_zoho_mcp.py`) and never copies tokens.

Rows below are written only when that tool is selected (`--tools all` writes every row).

| File written at app root | Tools that typically load it |
|---|---|
| `AGENTS.md` | Codex, Cursor, Copilot, Windsurf, Aider, Zed, Amp, Devin, Factory, Jules, Warp, Junie, VS Code, Roo, OpenCode, Qwen Code |
| `CLAUDE.md` | Claude Code (`@AGENTS.md` on the first line) |
| `GEMINI.md` | Gemini CLI / some Antigravity layouts |
| `CODEX.md` | Extra pointer for Codex-family CLIs |
| `QWEN.md` | Qwen Code (`@AGENTS.md` on the first line) |
| `.cursor/rules/android-harness.mdc` | Cursor (alwaysApply) |
| `.github/copilot-instructions.md` | GitHub Copilot |
| `.github/instructions/android-harness.instructions.md` | Copilot path-scoped instructions |
| `.windsurf/rules/android-harness.md` | Windsurf Cascade (always_on) |
| `.windsurfrules` | Older Windsurf / Cascade root file |
| `.clinerules` | Cline |
| `.roo/rules/android-harness.md` | Roo Code |
| `.amazonq/rules/android-harness.md` | Amazon Q Developer |
| `.continue/rules/android-harness.md` | Continue (project rules only) |
| `.junie/guidelines.md` | JetBrains Junie |
| `.kilocode/rules/android-harness.md` | Kilo Code |
| `.goosehints` | Block Goose |
| `.claude/agents/*.md` | Claude Code custom agents (from `.agents/subagents/*.json`) |

Canonical rules remain `.agents/rules/harness-rules.md`.
