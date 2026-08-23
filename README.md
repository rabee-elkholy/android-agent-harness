<div align="center">

# Android Agent Harness

**Architecture governance, quality delivery gate, and safety harness for Android & Kotlin Multiplatform.**

[![Release](https://img.shields.io/github/v/release/rabee-elkholy/android-harness-kit?color=2ea44f&style=flat-square)](https://github.com/rabee-elkholy/android-harness-kit/releases)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20KMP-3DDC84?style=flat-square&logo=android&logoColor=white)](https://android.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Quality Gate](https://img.shields.io/badge/Quality%20Gate-5--Leaf%20Pass-success?style=flat-square)](https://github.com/rabee-elkholy/android-harness-kit)
[![AI Tools](https://img.shields.io/badge/AI%20Tools-14%20Supported-purple?style=flat-square)](docs/tool-support.md)

<p align="center">
  <a href="#overview">Overview</a> •
  <a href="#architecture-workflow">Workflow</a> •
  <a href="#key-capabilities">Key Capabilities</a> •
  <a href="#supported-ai-tools">Supported Tools</a> •
  <a href="#installation">Installation</a> •
  <a href="#contributing">Contributing</a> •
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

</div>

## Overview

**Android Agent Harness** is a production delivery gate and architecture governance engine for Android and Kotlin Multiplatform (KMP) development. It installs rules, specialized reviewer subagents, and Python safety runners into your codebase.

Once installed, coding assistants cannot declare tasks complete with a casual "LGTM". Every code modification must pass a parallel **Five-Leaf Review Gate**, preflight sanity checks, real-time Gradle execution, and physical device verification before delivery.

---

## Architecture Workflow

```mermaid
flowchart TD
    Start([Task / Prompt]) --> Plan[Planning Guard: implementation_plan.md]
    Plan --> Approval{Developer Approval}
    Approval -- Approved --> Code[Code Implementation]
    Approval -- Revisions --> Plan
    Code --> ReviewGate[Five-Leaf Parallel Review Gate - MANDATORY]
    
    subgraph ReviewGate [Reviewer Subagents]
        R1[Bug Reviewer]
        R2[Convention Reviewer]
        R3[Security Reviewer]
        R4[Perf & ANR Guardian]
        R5[Regression Impact]
    end
    
    ReviewGate --> Verdict{All 5 Leaves PASS?}
    Verdict -- Fix Findings --> Code
    Verdict -- All PASS --> Preflight[Preflight: Lint + DB Migrations + String Parity]
    Preflight --> TestCheck{Unit Tests Enabled? <br/><i>(Configurable)</i>}
    TestCheck -- Enabled --> UnitTests[Unit Tests: testDebugUnitTest]
    UnitTests -- Tests Fail --> Code
    UnitTests -- Tests PASS --> Gradle[Live Gradle Runner: assembleDebug]
    TestCheck -- Skipped --> Gradle
    Gradle --> Device[Device Install & Verification]
    Device --> ZohoCheck{Zoho Sprints Connected? <br/><i>(Optional)</i>}
    ZohoCheck -- Enabled --> Zoho[Zoho Sprints: Status & Comment Sync]
    ZohoCheck -- Skipped / None --> Finish([Verified Delivery & Commit])
    Zoho --> Finish
```

---

## Core vs. Optional Features

| Category | Feature | Status | Description |
| :--- | :--- | :--- | :--- |
| **Core** | **Five-Leaf Review Gate** | **Mandatory** | Parallel review by 5 subagents (`BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`). Never bypassed. |
| **Core** | **Planning Guard** | **Mandatory** | Multi-file features and new screens require `implementation_plan.md` approval before coding. |
| **Core** | **Preflight Verification** | **Mandatory** | Runs fast Kotlin lint, Room database migration checks, and string parity before building. |
| **Core** | **Live Gradle Streaming** | **Mandatory** | `run_gradle_task.py` executes tasks with a 10s heartbeat to avoid silent background hangs. |
| **Core** | **Safety Hooks & Git Guard** | **Mandatory** | Hard blocks on `git commit`, `adb monkey`, and destructive package operations. |
| **Configurable** | **Unit Tests Gate (`I.15`)** | *Optional* | Enabled by default; runs `testDebugUnitTest`. Can be skipped if the project does not have test suites. |
| **Configurable** | **Zoho Sprints Sync (`I.16`)** | *Optional* | Project management MCP integration to sync task statuses (`Ready To ReTest`) and comments. |
| **Configurable** | **Device Target Policy (`I.4`)** | *Configurable* | Choose between locking strictly to **Physical Device Only** or allowing **Physical + Emulator**. |
| **Configurable** | **Git Commit Policy (`I.3`)** | *Configurable* | **Manual IDE commit** (recommended) or allow the agent to commit upon explicit chat request. |
| **Configurable** | **Bilingual Parity (`I.8`)** | *Configurable* | Enforces dual **Arabic (RTL) + English (LTR)** string parity and previews, or single locale. |
| **Configurable** | **AI Tool Adapters (`I.14`)** | *Configurable* | Select only the tools you use (Cursor, Antigravity, Claude Code, Copilot, Windsurf, etc.). |

---

## Supported AI Tools

The installer generates native adapter files for your chosen toolchain:

| AI Assistant / IDE | Generated Adapter | Integration Level |
| :--- | :--- | :--- |
| **Google Antigravity** | `agents/rules/`, `agents/hooks.json` | Hook blocking, subagent definitions, ephemeral reminders |
| **Cursor** | `.cursorrules` | Architectural rules, review protocol, terminal execution gates |
| **Claude Code** | `CLAUDE.md` | Slash command protocols, terminal safety guards |
| **GitHub Copilot** | `.github/copilot-instructions.md` | Workspace instructions, domain conventions |
| **OpenAI Codex CLI** | `AGENTS.md` | Universal agent instructions, execution policies |
| **Windsurf** | `.windsurfrules` | Cascade AI rules and architectural constraints |
| **Cline & Roo Code** | `.clinerules`, `.roomodes` | System prompts, mode definitions, tool permissions |
| **Amazon Q / Continue / Junie / Kilo / Goose** | Tool-specific rule files | Full rule compliance across 14+ supported environments |

---

## Project Modes

> [!NOTE]
> **Established Codebases**: The installer inspects `libs.versions.toml`, Gradle build files, ViewModels, and Compose UI to port your existing stack (MVI/MVVM, Koin/Hilt, Voyager/Compose Navigation, Room, etc.).
> 
> **Brand-New / Blank Projects**: The installer launches an interactive questionnaire to define your target platform (Native vs KMP), architecture, DI, navigation, UI toolkit, database, networking, and localization from day one.

---

## Installation

Installation is an automated structural port that tailors the 5-reviewer governance engine to your app's exact package and architecture.

### Step 1: Open Chat in Target Android Root
Open your IDE or terminal assistant in your **Android project root directory** (do not run setup inside `android-harness-kit`).

### Step 2: Select a Reasoning Model
Use a strong reasoning model for the setup chat (fast/lightweight models without deep reasoning tend to skip structural porting steps):
- **Anthropic**: `Claude Opus 4.6 / 5 (Thinking)` / `Claude Sonnet 4.6 / 5 (Thinking)`
- **Google**: `Gemini 3.1 Pro (Deep Think)` / `Gemini 3.7 Flash`
- **OpenAI**: `GPT-5.6 Sol` / `OpenAI o3` / `gpt-oss-120b`
- **DeepSeek**: `DeepSeek-V4 (Thinking)` / `DeepSeek-R1`

### Step 3: Paste the Install Prompt
Open [`docs/install-prompt.md`](docs/install-prompt.md), copy its entire contents, and paste it as your first message in the chat.

The AI assistant will automatically:
1. Verify that your project is a valid Android or Kotlin Multiplatform (KMP) repository.
2. Clone or locate the harness kit.
3. Guide you through the interactive setup questionnaire.
4. Structurally port the architecture rules, domain skills, and the 5 reviewer subagents to your app.
5. Generate native configuration adapters for your selected AI tools and run self-tests until `Total test failures: 0`.

### Step 4: Answer the Setup Wizard Questions
During installation, the wizard will ask you to confirm:
1. **Backup**: Create a timestamped backup before modifying `.agents/` *(Recommended)*.
2. **App Name**: Application identifier and display name.
3. **Git Policy**: Manual commits in IDE *(Recommended)* vs agent commits on request.
4. **Testing Target**: Physical device only vs physical + emulator.
5. **Install Confirmation**: Require confirmation before `adb install`.
6. **Unit Tests**: Retain or bypass unit-test verification gates.
7. **AI Tools**: Select which tools you use to generate matching adapter files.
8. **Zoho Sprints**: Optional project management integration.
9. *(If Greenfield Project)*: Complete the 8-question architecture foundation questionnaire.

---

## Repository Structure

```
android-harness-kit/
├── README.md                ← Project documentation
├── CHANGELOG.md             ← Version release history
├── LICENSE                  ← MIT License
├── docs/
│   ├── install-prompt.md    ← Setup instructions for new installs
│   ├── update-prompt.md     ← Upgrade instructions for existing installs
│   ├── setup-prompt.md      ← Installer agent execution protocol
│   ├── rollback-prompt.md   ← Uninstallation and restore instructions
│   └── tool-support.md      ← Supported tool specifications
├── agents/                  ← Deployed to <your-app>/.agents
│   ├── rules/               ← Core harness rules & five-leaf review guidelines
│   ├── scripts/             ← Python runners (setup_wizard, run_gradle_task, preflight, etc.)
│   ├── skills/              ← Android skills (Compose theme, MVI, ANR, Room, etc.)
│   ├── subagents/           ← Specialized reviewer subagent definitions
│   └── tool-adapters/       ← Template adapters for Cursor, Claude, Antigravity, etc.
└── templates/               ← Optional runtime and tool templates
```

## Contributing

Contributions from the Android and Kotlin Multiplatform development community are welcome!

Whether you want to:
- Add support or adapters for new AI coding tools and IDEs
- Improve prompt heuristics and domain guidelines for the reviewer subagents
- Enhance test coverage, safety guards, or Python automation runners
- Report edge-case bugs or suggest architectural improvements

### Getting Started:
1. **Fork the Repository** and create your branch from `main`:
   ```bash
   git checkout -b feature/your-improvement
   ```
2. **Make Your Changes** and verify all safety checks and selftests pass:
   ```bash
   python agents/scripts/_hook_selftest.py
   python agents/scripts/preflight_check.py
   ```
3. **Commit Your Changes** with clear, conventional commit messages (`feat: ...`, `fix: ...`, `docs: ...`).
4. **Open a Pull Request** explaining the motivation and detailed summary of changes.

For major architectural proposals, please open an **Issue** or start a **Discussion** first to align on design.

---

## License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

---

<div align="center">

[Back to Top](#android-agent-harness)

</div>
