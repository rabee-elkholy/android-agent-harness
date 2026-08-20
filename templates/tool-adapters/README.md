# Tool adapters

Canonical templates live in **`agents/tool-adapters/`** so they copy with the engine into `<app>/.agents/tool-adapters/`.

Setup runs:

```
$PY .agents/scripts/install_tool_adapters.py --product … --py … --assemble … --device-policy … --git-policy …
```

That writes `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CODEX.md`, `QWEN.md`, Copilot/Cursor/Windsurf/Cline/Roo/Amazon Q/Continue/Junie/Kilo/Goose adapters, and `.claude/agents/*.md`. See [`docs/tool-support.md`](../../docs/tool-support.md).
