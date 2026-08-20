# Tool adapters

Canonical templates live in **`agents/tool-adapters/`** so they copy with the engine into `<app>/.agents/tool-adapters/`.

Setup runs:

```
$PY .agents/scripts/install_tool_adapters.py --product … --py … --assemble … --device-policy … --git-policy … --tools cursor,gemini
```

`--tools` is required (`all` or a comma-separated list of ids). That writes `AGENTS.md` plus only the selected adapters. See [`docs/tool-support.md`](../../docs/tool-support.md).
