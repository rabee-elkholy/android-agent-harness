<div align="center">

# 🛡️ Android Agent Harness

**Enterprise Architecture Governance, 5-Leaf Review Gate, and Safety Harness for Android & Kotlin Multiplatform.**

[![CI Build](https://img.shields.io/github/actions/workflow/status/rabee-elkholy/android-harness-kit/ci.yml?branch=main&style=flat-square&logo=github-actions&logoColor=white&label=CI)](https://github.com/rabee-elkholy/android-harness-kit/actions/workflows/ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/rabee-elkholy/android-harness-kit?color=2ea44f&style=flat-square&logo=github&logoColor=white)](https://github.com/rabee-elkholy/android-harness-kit/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20KMP-3DDC84?style=flat-square&logo=android&logoColor=white)](https://android.com)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Quality Gate](https://img.shields.io/badge/Quality%20Gate-5--Leaf%20Pass-success?style=flat-square&logo=checkmarx&logoColor=white)](docs/architecture.md)
[![AI Tools](https://img.shields.io/badge/AI%20Tools-14%20Supported-8A2BE2?style=flat-square&logo=openai&logoColor=white)](docs/tool-support.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](CONTRIBUTING.md)

<p align="center">
  <a href="#-overview">Overview</a> •
  <a href="#-quickstart-in-2-minutes">Quickstart</a> •
  <a href="#-architecture-workflow">Workflow</a> •
  <a href="#-the-five-leaf-review-gate">Review Gate</a> •
  <a href="#-supported-ai-tools">Supported Tools</a> •
  <a href="#-documentation">Documentation</a> •
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

</div>

## 🌟 Overview

**Android Agent Harness** transforms AI coding assistants from unconstrained code generators into disciplined, production-grade engineering teammates.

When using tools like **Cursor**, **Google Antigravity**, **Claude Code**, or **GitHub Copilot** on large Android & KMP codebases, AI models often cause silent regressions, introduce unhandled `NullPointerExceptions`, drop Arabic/RTL string translations, or freeze the UI thread with unoptimized recompositions.

**Android Agent Harness** eliminates these risks by installing an automated **Five-Leaf Review Gate**, strict safety hooks, live Gradle execution streams, and Zoho Sprints project sync into your codebase.

---

## ⚡ Quickstart (in 2 Minutes)

Open your AI assistant in your **Android project root directory** and paste:

```markdown
Read and execute the Android Harness Kit installer:
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/install-prompt.md
```

Follow the interactive setup wizard to configure your project. Once verified (`Total test failures: 0`), your repository is fully protected!

👉 *For detailed setup instructions, see the [Quickstart Guide](docs/quickstart.md).*

---

## 🔄 Architecture Workflow

```mermaid
flowchart TD
    Start(["Task / User Request"]) --> Plan["Planning Guard: implementation_plan.md"]
    Plan --> Approval{"Developer Approval"}
    Approval -- Approved --> Code["Code Implementation"]
    Approval -- Revisions --> Plan
    Code --> ReviewGate["Five-Leaf Parallel Review Gate"]
    
    subgraph ReviewGate ["Parallel Reviewer Subagents"]
        R1["🐞 Bug & Null-Safety Reviewer"]
        R2["📐 Architecture & Convention"]
        R3["🔒 Security & Permissions"]
        R4["⚡ Perf & ANR Guardian"]
        R5["🔄 Regression Blast Radius"]
    end
    
    ReviewGate --> Verdict{"All 5 Leaves PASS?"}
    Verdict -- Findings --> Code
    Verdict -- All PASS --> Preflight["Preflight: Fast Lint + Room DB + String Parity"]
    Preflight --> TestCheck{"Unit Tests Enabled?"}
    TestCheck -- Enabled --> UnitTests["Unit Tests: testDebugUnitTest"]
    UnitTests -- Fail --> Code
    UnitTests -- PASS --> Gradle["Live Gradle Runner: assembleDebug"]
    TestCheck -- Skipped --> Gradle
    Gradle --> Device["Device Runner: run_device.py"]
    Device --> ManualSignoff["Manual 4-Phase Verification"]
    ManualSignoff -- Fail --> Code
    ManualSignoff -- All PASS --> ZohoCheck{"Zoho Sprints Connected?"}
    ZohoCheck -- Enabled --> Zoho["Zoho Sprints: Status & Commit Traceability"]
    ZohoCheck -- Skipped --> Finish(["Verified Delivery & Safe Commit"])
    Zoho --> Finish
```

---

## 🍃 The Five-Leaf Review Gate

Every code change must pass parallel sign-off from all 5 specialized reviewer subagents before Gradle assembly is unlocked:

| Leaf Reviewer | Focus Area | What It Catches |
| :--- | :--- | :--- |
| **🐞 Bug Reviewer** | Memory & Logic | `NullPointerExceptions`, unhandled coroutine cancellations, lifecycle leaks |
| **📐 Convention Reviewer** | Architecture | MVI / Clean Architecture violations, mutable state leakage, improper DI |
| **🔒 Security Reviewer** | Security & Privacy | Exported components without permission, SQL injections, cleartext tokens |
| **⚡ Perf & ANR Guardian** | Performance & UI | Main thread disk/network I/O, heavy recompositions, unbounded loops |
| **🔄 Regression Reviewer** | Blast Radius | Broken dependent screens, missing navigation parameters, contract breaks |

---

## 🛠️ Supported AI Tools

The installer automatically generates native rule adapters tailored to your IDE and assistant:

| Assistant / IDE | Generated Adapter | Capabilities |
| :--- | :--- | :--- |
| **Google Antigravity** | `agents/rules/`, `agents/hooks.json` | Subagent dispatch, blocking hooks, ephemeral reminders |
| **Cursor** | `.cursorrules` | Architecture constraints, review protocol, terminal gates |
| **Claude Code** | `CLAUDE.md` | Terminal safety guards, review flow protocols |
| **GitHub Copilot** | `.github/copilot-instructions.md` | Context instructions, domain conventions |
| **OpenAI Codex CLI** | `AGENTS.md` | Universal agent instructions, execution limits |
| **Windsurf** | `.windsurfrules` | Cascade AI constraints, MVI architecture rules |
| **Cline & Roo Code** | `.clinerules`, `.roomodes` | System prompt enforcement, tool permissions |
| **Continue / Junie / Kilo / Goose** | Native Adapter Files | Full rule compliance across 14+ supported environments |

---

## 📚 Documentation

- [**Quickstart Guide**](docs/quickstart.md) — 2-minute setup instructions
- [**Architecture Guide**](docs/architecture.md) — Deep dive into the governance engine
- [**Tool Support Matrix**](docs/tool-support.md) — Full matrix of 14+ supported AI tools
- [**Installation Prompt**](docs/install-prompt.md) — One-prompt installer script
- [**Upgrade Guide**](docs/update-prompt.md) — How to update an existing installation
- [**Rollback Guide**](docs/rollback-prompt.md) — Clean uninstaller and restore script
- [**Contributing Guidelines**](CONTRIBUTING.md) — How to contribute to the kit
- [**Code of Conduct**](CODE_OF_CONDUCT.md) — Community standards
- [**Security Policy**](SECURITY.md) — Vulnerability reporting

---

## 🤝 Contributing

Contributions are welcome! Whether you want to add adapters for new AI tools, improve subagent prompts, or enhance Python runners, please read our [Contributing Guide](CONTRIBUTING.md) before submitting a Pull Request.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

<div align="center">

**Crafted with 💚 for the Android & Kotlin Multiplatform Community.**

[Back to Top ↑](#️-android-agent-harness)

</div>\n