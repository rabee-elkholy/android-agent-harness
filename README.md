# Android Agent Harness

Portable quality engine for Android work. Same scripts and five-leaf review in **Claude Code**, **Codex**, **Cursor**, **GitHub Copilot**, **Gemini / Antigravity**, **Qwen Code**, **Windsurf**, **Cline**, **Roo**, **Amazon Q**, **Continue**, **Junie**, **Kilo**, **Goose**, and any tool that reads `AGENTS.md`.

The kit is not an Android app. It is the delivery gate used on a production Android product: rules, reviewer prompts, and Python runners you install into an existing checkout. It does **not** ship an SDK, Gradle caches, secrets, or another developer’s machine paths.

## Why it is strong

This is not a style-guide snippet. After a full install, the agent cannot treat “looks good” as done.

- **Five-leaf gate:** `BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS` before assemble. No `LGTM`. No retired `code-review-guard-agent`.
- **Live Gradle:** `run_gradle_task.py` streams the task log with a 10s heartbeat. The agent does not wait on a silent `gradlew`.
- **Device path:** `run_device.py` install/launch. `adb monkey` is always denied.
- **Hard block where the tool allows it:** Antigravity `hooks.json` can refuse assemble until the five leaves finish. Other tools get the same protocol in markdown.
- **Your product, not a placeholder:** setup fills `_product.py`, module, APK, launcher, and architecture so reviewers cite *this* app.

The strength shows up **after** setup finishes (selftest `0` failures + adapters for the tools you picked). A half install is a weak install.

## What you get

- Five-leaf delivery review (`BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`)
- Live Gradle runner with a task log and 10s heartbeat
- Device install/launch helper (`run_device.py`)
- Safety hook in Antigravity; the same protocol in markdown for every other tool
- One installer that writes adapters **only for the tools the developer selects** (re-run `--tools` to add another later)
- Setup fills package, module, theme, and architecture from this app (`_product.py` + skills)

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

## Prerequisites & Target Project Types

> [!TIP]
> **Supports Both Established Codebases & Brand-New (Greenfield) Projects**
> - **Existing / Established Codebases**: The installer automatically inspects and discovers your DI, ViewModels, Navigation, Compose theme, and domain patterns from disk.
> - **Brand-New / Greenfield Projects**: The installer guides you through the interactive **Greenfield Bootstrap Questionnaire** (Platform, MVI/MVVM, Koin/Hilt, Voyager/ComposeNav, Room/SQLDelight, Ktor/Retrofit) to establish strict architectural rules and blueprints from day one!

> [!CAUTION]
> **Non-Android Projects Are Strictly Rejected**
> The harness requires a Gradle-based Android or Kotlin Multiplatform (KMP) project with `gradlew` / `gradlew.bat`. If the Gradle wrapper or Android build configurations are missing, installation immediately stops.

### System Requirements:
- Python 3.10+ (`python3` on macOS/Linux; on Windows use `python` if `python3` is a Store stub)
- Android Studio `local.properties` (`sdk.dir`) on the target machine
- Gradle wrapper in the project root (`gradlew` / `gradlew.bat`)
- `adb` on `PATH` or from the SDK `platform-tools`

---

## 🚀 Installation (Step-by-Step)

Installation is **not** a simple file copy. It is an automated structural port that tailors the 5-reviewer governance engine to your app's exact architecture and tech stack.

### Step 1: Open a New Chat in Your Android Project
Open your IDE or terminal AI assistant (Cursor, Antigravity, Claude Code, etc.) in your **Android app's root folder** (⚠️ **never** run setup inside `android-harness-kit` itself).

### Step 2: Use a Strong AI Model
Use a strong reasoning model (e.g. Gemini 2.5/3.0 Pro, Claude 3.7 Sonnet, GPT-4o) for the installation chat. Fast/cheap models tend to skip architectural porting steps and leave a broken setup.

### Step 3: Paste the Install Prompt
Copy the entire contents of [`docs/install-prompt.md`](docs/install-prompt.md) and paste it as your first message in the chat:
```markdown
[Paste the full contents of docs/install-prompt.md here]
```

### Step 4: Answer the Setup Wizard Questions
The agent will run the interactive setup wizard (`setup_wizard.py`) or present the questions in chat:
1. **Backup**: Create a timestamped backup before touching `.agents/` (Recommended).
2. **App Name**: Confirm the detected application name.
3. **Git Policy**: Decide whether you commit manually in the IDE (Recommended) or allow the agent to commit on request.
4. **Testing Target**: Physical device only, or both physical device and emulator.
5. **Install Confirmation**: Ask before `adb install` or install unattended.
6. **Unit Tests**: Keep or skip unit-test verification gates.
7. **AI Tools**: Select which tools you use (Cursor, Antigravity, Claude Code, Copilot, Windsurf, etc.) to generate matching adapter files (`AGENTS.md`, `.cursorrules`, `CLAUDE.md`, etc.).
8. **Zoho Sprints (Optional)**: Enable or skip Zoho Sprints project management integration (MCP credentials stay securely on your PC and are never copied into the repository).

### Step 5: Automatic Porting & Verification
The agent will:
- Clone the harness kit to a sibling/temp location.
- Copy engine scripts and subagents to `.agents/`.
- Discover your app's package, modules, launcher activity, Compose theme, DI, and domain logic.
- Dynamically create tailored reference files for detected domains (audio, education, billing, etc.).
- Run selftest (`_hook_selftest.py`) until `Total test failures: 0`.

### Step 6: Start Real Work in a Fresh Chat Session
Once setup completes, **open a brand new chat session** in your Android project. All subsequent coding tasks will automatically be governed by the parallel 5-reviewer quality gate!

---

## 🔄 Updating an Existing Installation

When new features or fixes are committed to this repository, existing installations can be updated seamlessly without losing custom settings:

1. Open a **new chat** in your Android project.
2. Copy and paste the entire contents of [`docs/update-prompt.md`](docs/update-prompt.md).
3. The agent will back up, pull the latest harness kit, re-port the engine using your saved answers, restore your custom skills, and verify with selftest.

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
- Kit `agents/mcp_config.json` stays `mcpServers: {}`; install may wire Zoho Sprints to a **user-level** config path
- Do not copy `local.properties` or `~/.gemini` hostnames from another PC
- The agent must not commit unless you ask

## Releases

There were none at first because install is **clone `main` + paste the install prompt**, not a downloadable app zip. Tags start at **v0.1.0**.

GitHub Releases are snapshots of this repo (source archive only — no extra zip). Day-to-day install and update still follow `main` unless you pin a tag (`git clone --branch v0.1.0 …`).
