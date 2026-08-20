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
│   ├── install-prompt.md    ← paste this in a new chat on the Android app
│   ├── setup-prompt.md      ← the agent runs this after it clones the kit
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

Open a **new chat** on your **Android app** (not this kit). Paste the prompt below (same text as [`docs/install-prompt.md`](docs/install-prompt.md)).

The agent clones this repository if needed, copies `agents/` to `.agents`, then interviews you (product, Python, git, device, which coding tools). It must **port** the engine (regex, Path pieces, APK name, architecture). A find-replace of the example app name is not a successful install.

After port, it runs `install_tool_adapters.py --tools <the tools they chose>` and writes only those entry files. Switching to a new IDE later means re-running the installer with that tool added.

Physical vs emulator is **optional during setup**. Skip = both allowed. `adb monkey` stays denied.

If you already have this kit on disk, you can still paste the same prompt — the agent will reuse the clone.

```
You are installing the portable Android AI harness into this checkout. This folder is the Android product. It is not android-harness-kit.

Answer in the developer's language. Do not commit unless they ask. Do not skip the interview. Do not only rename the example app.

Start now:

1. Confirm this repo has gradlew or gradlew.bat. If not, stop — this is not an Android Gradle checkout.
2. Get the kit (do not clone into app/, composeApp/, or any module source tree):
   - If a clone already exists nearby (sibling android-harness-kit, a path the developer gives, or a previous temp clone), use that.
   - Otherwise: git clone https://github.com/rabee-elkholy/android-harness-kit.git into a sibling folder or the OS temp directory.
3. Open <kit>/docs/setup-prompt.md and execute that file in full as if the developer had pasted it. The copy source is <kit>/agents/ → <this repo>/.agents.
4. After setup: tell them to start a new chat on this Android folder before real work.

Kit rules that still apply during setup:

- Backup before overwriting .agents or tool adapters.
- Structural port (package, regex, Path pieces, APK name, architecture, locales). A find-replace of the example name is not a successful install.
- Write adapters only for the tools they pick (--tools). Always write AGENTS.md.
- Keep .agents/mcp_config.json as {"mcpServers": {}}. Do not add MCP servers. Do not overwrite the developer's existing MCP / Continue / Aider / kilo.jsonc / ~/.gemini configs.
- Do not copy local.properties sdk.dir or ~/.gemini hostnames from another machine.
- adb monkey stays denied. Emulator deny only if they lock the install to a physical device.

Begin: print OS, this repo path, and whether you reused a kit clone or cloned a fresh one. Then run setup-prompt.md from its first heading.
```


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
