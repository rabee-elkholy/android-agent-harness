# Android Agent Harness

Portable quality engine for Android work. Same scripts and five-leaf review in **Claude Code**, **Codex**, **Cursor**, **GitHub Copilot**, **Gemini / Antigravity**, **Qwen Code**, **Windsurf**, **Cline**, **Roo**, **Amazon Q**, **Continue**, **Junie**, **Kilo**, **Goose**, and any tool that reads `AGENTS.md`.

The kit is not an Android app. It is rules, reviewer prompts, and Python runners you install into an existing checkout. It does **not** ship an SDK, Gradle caches, secrets, or another developer’s machine paths.

## What you get

- Five-leaf delivery review (`BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`)
- Live Gradle runner with a task log and 10s heartbeat
- Device install/launch helper (`run_device.py`)
- Safety hook in Antigravity; the same protocol in markdown for every other tool
- One installer that writes adapters **only for the tools the developer selects** (re-run `--tools` to add another later)
- Structural port away from the example product identity (package, module, theme, architecture)

## Layout

```
android-harness-kit/
├── README.md
├── .gitignore
├── docs/
│   ├── setup-prompt.md      ← paste this to the agent first
│   ├── rollback-prompt.md
│   ├── restore.md
│   ├── porting.md
│   └── tool-support.md      ← which file each product loads
├── agents/                  ← copy this folder to <your-app>/.agents
│   ├── rules/
│   ├── scripts/
│   ├── skills/
│   ├── subagents/
│   ├── workflows/
│   └── tool-adapters/       ← templates; installer fills them at the app root
└── templates/
    ├── tool-adapters/       ← pointer to agents/tool-adapters
    └── gemini-runtime/      ← optional Antigravity grants example
```

## Requirements

- Python 3.10+ (`python3` on macOS/Linux; on Windows use `python` if `python3` is a Store stub)
- Android Studio `local.properties` (`sdk.dir`) on the target machine
- Repo `gradlew` / `gradlew.bat`
- `adb` on `PATH` or from the SDK `platform-tools`

## Install

1. Clone this repository.
2. Copy `agents/` to the **root of your Android project** and name it `.agents`.
3. Open that Android project in whichever agent you use.
4. Paste **all of** [`docs/setup-prompt.md`](docs/setup-prompt.md) as the first message.

The agent backs up first, discovers your module/package/launcher from disk, then asks setup questions with choices. It must **port** the engine (regex, Path pieces, APK name, architecture). A find-replace of the example app name is not a successful install.

After port, it runs `install_tool_adapters.py --tools <the tools they chose>` and writes only those entry files. Switching to a new IDE later means re-running the installer with that tool added.

Physical vs emulator is **optional during setup**. Skip = both allowed. `adb monkey` stays denied.

## After setup

Start a **new chat** on that Android folder. Non-trivial work still needs all five `*_PASS` tokens before assemble. Rollback: paste [`docs/rollback-prompt.md`](docs/rollback-prompt.md).

## Supported agents

See [`docs/tool-support.md`](docs/tool-support.md) for the full matrix.

| Tool | Entry | Enforcement |
|---|---|---|
| Any `AGENTS.md` reader (Codex, Aider, Zed, Amp, Devin, Factory, Jules, Warp, OpenCode, …) | `AGENTS.md` | Prompt |
| Google Antigravity | `.agents/hooks.json` + `GEMINI.md` | Hook can block assemble until reviews finish |
| Claude Code | `CLAUDE.md` + `.claude/agents/*.md` | Prompt + named agents |
| Qwen Code | `QWEN.md` + `AGENTS.md` | Prompt |
| Cursor | `AGENTS.md` + `.cursor/rules/android-harness.mdc` | Prompt |
| GitHub Copilot | `.github/copilot-instructions.md` | Prompt |
| Windsurf / Cline / Roo / Amazon Q / Continue / Junie / Kilo / Goose | dedicated rule files | Prompt |

Python scripts are the same on every tool. Only Antigravity auto-blocks assemble via `hooks.json`.

## Safety

- No tokens, OAuth clients, or portal IDs in this repo
- Empty `agents/mcp_config.json` (`mcpServers: {}`)
- Do not copy `local.properties` or `~/.gemini` hostnames from another PC
- The agent must not commit unless you ask
