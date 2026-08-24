# Changelog

All notable changes to the **Android Harness Kit** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] - 2026-08-24

### Shift-Left Proactive Quality, Reviewer Expansion & Test Quality Specialist
- **Shift-Left Proactive Quality Architecture**: Introduced Pre-Implementation Quality Invariants across `harness-rules.md` and `pre_invocation_reminder.py`, instructing coding agents to proactively satisfy review pillars prior to code execution for first-pass review approval.
- **Expanded Core Reviewer Pillars**:
  - `bug-reviewer-agent`: Added Network & I/O Resiliency checks (`IOException`, `SocketTimeoutException`, `UnknownHostException` in coroutines, error UI state exposure, exponential backoff).
  - `convention-reviewer-agent`: Added Accessibility standards (mandatory `contentDescription` on non-decorative images/icons, minimum 48dp touch target size) and KMP portability rules (zero `android.*` framework imports in `commonMain`).
  - `perf-anr-guardian-agent`: Added Battery & Sensor Life checks (`SensorEventListener` unregistration in `onPause()`/`DisposableEffect.onDispose`, Android 14+ foreground service type declarations, WorkManager charging constraints).
- **Dedicated Test Quality Specialist (`test-quality-reviewer-agent`)**: Introduced on-demand reviewer (`HARNESS_TEST_FINGERPRINT=quality-first-test-review-v1`) for unit and UI test files (`*Test.kt`), checking assertion depth, mocking integrity, and Coroutines `runTest` dispatchers.
- **Model Selection Matrix by Assistant**: Added comprehensive **Recommended Models by Assistant (Setup vs Daily)** comparative matrix in `docs/tool-support.md` and `docs/quickstart.md` across 10 supported AI assistants and IDEs.
- **Automated CI/CD Pipeline**: Multi-OS GitHub Actions matrix testing Linux and Windows across Python 3.10, 3.11, 3.12, and 3.13 (`.github/workflows/ci.yml`).
- **Open-Source Community Health**: Added `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1), `SECURITY.md`, and interactive GitHub Issue Forms.

---

## [0.2.0] - 2026-08-23

### Multi-IDE Tool Adapters, Interactive Notifier & Zoho Integration
- **Multi-IDE & AI Assistant Support**: Automatic adapter generation for 14+ tools including Cursor, Google Antigravity, Claude Code, GitHub Copilot, Codex, Qwen Code, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, and Goose.
- **Interactive Update Notifier (`check_kit_update.py`)**: Automatic start-of-session update checker with 24-hour cache TTL, non-blocking 2.5s network timeout, and `--snooze 1` support.
- **Greenfield Bootstrap Mode**: Interactive architectural questionnaire for blank Android and Kotlin Multiplatform projects.
- **Background Process & Safety Discipline**: Anti-polling guardrails preventing infinite subagent status loops (`>2` polls blocked) and atomic temporary-file state replacements (`_hook_state.py`).
- **Granular Language Separation (I.17 & I.18)**: Strict English for engineering artifacts and subagent findings alongside Arabic/English localization controls for Zoho Sprints.
- **Git Mutation Guard Hardening**: Advanced command inspection intercepting git mutations across wrapper subshells (`powershell`, `cmd`, `bash`), absolute paths, and chained command sequences.

---

## [0.1.0] - 2026-08-23

### Five-Leaf AI Quality Engine & Delivery Gate
- **Five-Leaf Review Delivery Gate**: Mandatory, parallel 5-reviewer subagents (`BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`) before any assemble or release.
- **Dynamic Domain Discovery**: Automatically inspects project dependencies and codebase during installation to create tailored domain reference files (Audio/Media, BLE, Education/Games, Billing, etc.).
- **Live Gradle Task Runner (`run_gradle_task.py`)**: Real-time task logging with a 10-second heartbeat to prevent silent build timeouts.
- **Zoho Sprints MCP Integration**: Bidirectional task synchronization reading bug attachments, creating hierarchical subtasks, and posting Arabic/English QA handoff comments with exact Git commit hashes.
- **Device & Package Safety**: Strict denial of `adb monkey` and unauthorized `pm clear` commands, with safe `run_device.py uninstall` support.
