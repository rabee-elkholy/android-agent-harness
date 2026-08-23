# Changelog

All notable changes to the **Android Harness Kit** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.1] - 2026-08-23

### 🚀 Added
- **Community Contribution Guidelines**: Added clear open-source contribution workflow, branch conventions, and testing requirements in `README.md`.
- **Single-Backup Retention & 1-Click Rollback**: Enforced single-backup pruning on upgrades with automatic rollback guarantee via `docs/rollback-prompt.md`.
- **Frontier Reasoning Model Lineup**: Updated model recommendations to latest verified flagship reasoning models (Claude Opus/Sonnet 4.6/5, Gemini 3.1 Pro/3.7 Flash, GPT-5.6 Sol/o3, DeepSeek-V4/R1).
- **Documentation Refinement**: Streamlined README with clean engineering typography, flat-square badges, and polished workflow diagrams.

---

## [0.2.0] - 2026-08-23

### 🚀 Added
- **Interactive Start-of-Session Update Notifier**: Automatic, non-blocking check at the beginning of each new chat session alerting the developer when a newer kit version is available.
- **Snooze & In-Chat Changelog Viewing**: Full support for viewing markdown release notes directly in chat (`--show-changes`), snoozing update notifications for 24 hours (`--snooze 1`), or launching seamless upgrades.
- **Greenfield Bootstrap Mode**: Interactive architectural questionnaire for blank Android/KMP projects to establish Platform, Architecture, DI, Navigation, UI, Database, Networking, and Locales from Day 1.

---

## [0.1.0] - 2026-08-23

### 🚀 Added
- **Five-Leaf Review Delivery Gate**: Mandatory, parallel 5-reviewer subagents (`BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`) before any assemble or release.
- **Dynamic Domain Discovery**: Automatically inspects project dependencies and codebase during installation to create tailored domain reference files (Audio/Media, BLE, Education/Games, Billing, etc.).
- **Live Gradle Task Runner (`run_gradle_task.py`)**: Real-time task logging with a 10-second heartbeat to prevent silent builds.
- **Multi-IDE & AI Assistant Support**: Automatic adapter generation for 14+ tools including Cursor, Google Antigravity, Claude Code, GitHub Copilot, Codex, Qwen Code, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, and Goose.
- **Fail-Fast Project Validation**: Immediately verifies `gradlew`/`gradlew.bat` and halts non-Android directories with helpful guidance.
- **Zoho Sprints MCP Integration**: Project management integration that reads PC-level credentials without leaking or committing tokens to the repository.

### 🛡️ Security & Quality
- **Reactive Wakeup Enforcement**: Forbids `schedule` timer polling loops after subagent dispatch, relying on Antigravity's automatic reactive wakeup.
- **Strict Git Mutation Guard**: Hard safety hooks preventing agents from creating unauthorized commits, pushes, or worktrees unless explicitly directed.
- **Device & Package Safety**: Strict denial of `adb monkey` and unauthorized `pm clear` commands, with safe `run_device.py uninstall` support.
