# Android Agent Harness

Portable quality engine for Android work. Same scripts and five-leaf review in **Claude Code**, **Codex**, **Cursor**, **GitHub Copilot**, **Gemini / Antigravity**, **Qwen Code**, **Windsurf**, **Cline**, **Roo**, **Amazon Q**, **Continue**, **Junie**, **Kilo**, **Goose**, and any tool that reads `AGENTS.md`.

The kit is not an Android app. It is the delivery gate used on a production Android product: rules, reviewer prompts, and Python runners you install into an existing checkout. It does **not** ship an SDK, Gradle caches, secrets, or another developer’s machine paths.

## Why it is strong

This is not a style-guide snippet. After a full install, the agent cannot treat “looks good” as done.

- **Five-leaf gate:** `BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS` before assemble. No `LGTM`. No retired `code-review-guard-agent`.
- **Live Gradle:** `run_gradle_task.py` streams the task log with a 10s heartbeat. The agent does not wait on a silent `gradlew`.
- **Device path:** `run_device.py` install/launch. `adb monkey` is always denied.
- **Hard block where the tool allows it:** Antigravity `hooks.json` can refuse assemble until the five leaves finish. Other tools get the same protocol in markdown.
- **Your product, not the example:** setup ports package, module, APK, launcher, and architecture so reviewers cite *this* app (Koin/KMP vs MVI/Hilt), not leftover names.

The strength shows up **after** setup finishes (selftest `0` failures + adapters for the tools you picked). A half install is a weak install.

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
│   ├── update-prompt.md     ← paste this to pull a newer kit into an existing install
│   ├── setup-prompt.md      ← the agent runs this after it clones the kit
│   ├── rollback-prompt.md
│   ├── restore.md
│   ├── porting.md
│   ├── sync.md              ← kit ↔ parent product without overwriting .agents
│   └── tool-support.md      ← which file each product loads
├── agents/                  ← copy this folder to <your-app>/.agents
│   ├── rules/
│   ├── scripts/             ← includes setup_wizard.py (few questions; rest from disk)
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

Install is **not** a file copy. Use a **strong model** for the install chat (not a fast/cheap one). A weak model skips the structural port and leaves a broken helper. Plan for **time**: a few wizard questions (backup, app name, git, phone vs emulator, ask before install, unit tests, which tools — the rest is read from Gradle/manifests), backup, clone (or reuse) the kit, a structural port, leftover grep, then selftest and preflight. On a first machine that can mean **tens of minutes**. If you close the chat early or accept a rename of the example app, you do **not** get the engine above.

Stay in that chat until the agent prints selftest `Total test failures: 0` and tells you to open a **new** session. Prefer answering the wizard in a **terminal**. The agent then ports; it must not invent extra interview questions.

Open a **new chat** on your **Android app** (not this kit). Paste **all of** [`docs/install-prompt.md`](docs/install-prompt.md).

The agent clones this repository if needed, runs `agents/scripts/setup_wizard.py` (usually seven questions), copies `agents/` to `.agents`, then **ports** the engine (regex, Path pieces, APK name, architecture). A find-replace of the example app name is not a successful install.

After port, it runs `install_tool_adapters.py` with the flags printed by `setup_wizard.py flags`. Switching to a new IDE later means re-running the installer with that tool added.

Phone vs emulator is a setup question (both allowed is first). `adb monkey` stays denied.

If you already have this kit on disk, you can still paste the same prompt — the agent will reuse the clone (pull `main` if you want the latest).

The pasteable first message is the full file [`docs/install-prompt.md`](docs/install-prompt.md) (not a short summary).


## After setup

Start a **new chat** on that Android folder. Non-trivial work still needs all five `*_PASS` tokens before assemble. Rollback: paste [`docs/rollback-prompt.md`](docs/rollback-prompt.md).

## Update

When this GitHub repo gets a new commit, people who already installed do **not** get it automatically. `.agents` is a copy.

Open a **new chat** on the **Android app** and paste **all of** [`docs/update-prompt.md`](docs/update-prompt.md).

The agent backs up, `git pull`s the kit, recopies `agents/` → `.agents`, re-ports from `.harness-setup/answers.json` (or `SETUP_ANSWERS.md`), and re-runs `install_tool_adapters.py` from `setup_wizard.py flags`. Custom skills they added (not shipped by the kit) are restored from the backup. Then a new chat.

Do **not** use install/update prompts on the parent product that this kit was extracted from. File-level sync: [`docs/sync.md`](docs/sync.md).

The pasteable update message is [`docs/update-prompt.md`](docs/update-prompt.md).

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

## Releases

There were none at first because install is **clone `main` + paste the install prompt**, not a downloadable app zip. Tags start at **v0.1.0**.

GitHub Releases are snapshots of this repo (source archive only — no extra zip). Day-to-day install and update still follow `main` unless you pin a tag (`git clone --branch v0.1.0 …`).
