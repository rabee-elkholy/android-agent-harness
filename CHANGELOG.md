# Changelog

All notable changes to the **Android Harness Kit** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.6] - 2026-08-24

### Forensic Audit Hardening: Chained Git Mutation Interception & Diagnostic Inventory Parity
- **Chained Git Mutation Bypass Fix (`pre_tool_safety.py`)**: The git mutation scanner now splits commands on shell chaining operators (`&&`, `||`, `;`, `|`, newlines) and scans every segment independently. Previously, a leading inspection command could mask a chained mutation (e.g. `git status && git push origin main` or `git log --oneline; git reset --hard HEAD~1`) because the first regex match consumed the remainder of the command line. Pure inspection chains (e.g. `git status && git diff HEAD --stat`) remain allowed.
- **Core Script Inventory Completeness (`harness_doctor.py`)**: Added `new_feature_scaffold.py` to the Dimension 2 core script manifest. The doctor now audits all 25 shipped Python scripts instead of 24, closing an inventory blind spot.
- **Kotlin Source Domain Discovery (`harness_doctor.py`)**: `_detect_project_domains()` now scans Kotlin source files (bounded at 500 files, skipping `build`/`.git`/cache directories) in addition to Gradle build scripts, `libs.versions.toml`, and `AndroidManifest.xml`. This matches the documented v0.5.4 behavior and detects signatures that only appear in `.kt` code (e.g. `SensorManager`, `SoundPool`, `MediaPlayer`).
- **Documentation Veracity Sweep**: Corrected README adapter matrix drift (Cursor `.cursor/rules/android-harness.mdc` instead of legacy `.cursorrules`; Roo `.roo/rules/android-harness.md` instead of `.roomodes`), fixed the `run_device.py` example to include the required `install-start` action argument, aligned the I.4 device policy default with the actual wizard recommendation (`Physical + Emulator`), clarified I.16 Zoho as optional, added `test-quality-guidelines.md` to the foundation references enumeration in `docs/setup-prompt.md`, and updated "24 core scripts" references to 25 across README, architecture guide, and diagnostic prompt.

---

## [0.5.5] - 2026-08-24

### Scope Isolation Hardening & Application Localization Advisory
- **Scope Isolation Protection (`harness_doctor.py` Dimension 10)**: Refactored Preflight Pipeline inspection to classify pre-existing application string parity discrepancies as informational advisories (`[WARN]`) rather than fatal harness infrastructure failures (`[FAIL]`).
- **Real-Time Progressive Console Streaming (`harness_doctor.py`)**: Implemented progressive line-by-line output streaming with immediate `flush=True` for all 12 diagnostic dimensions. Eliminates stdout buffer delays and prevents tasks from appearing silent/frozen during background execution.

---

## [0.5.4] - 2026-08-24

### Deep Domain References Integration & Architectural Coverage Guard
- **Deep Domain Discovery & Audit (`harness_doctor.py`)**: Enhanced the 12-Dimension Diagnostic Doctor with automated project domain discovery. Scans Gradle dependencies, `libs.versions.toml`, `AndroidManifest.xml`, and Kotlin source files to detect active architectural domains (Networking, Payments/Billing, Ads/Monetization, Location/Maps, Hardware/Sensors, Audio/Media, Local Storage).
- **Tailored Domain Reference Coverage Validation**: Verifies that every active project domain has a dedicated, tailored reference guide in `.agents/skills/android-harness/references/` (e.g. `networking-api-contracts.md`, `payment-gateways-architecture.md`, `ad-mediation-privacy.md`, `fitness-tracking-sensors.md`). Issues actionable recommendations if uncovered domains are detected.
- **Reference Indexing & Linkage Verification**: Audits `daily-scenarios.md` to guarantee that 100% of foundation and tailored domain reference files are actively indexed and linked, preventing orphan references and enabling AI subagents to cite exact project conventions during daily tasks.
- **Reference File Integrity Check**: Validates that all foundation references exist and contain valid, non-corrupted architectural guidance.

---

## [0.5.3] - 2026-08-24

### Automated Post-Setup Diagnostics, `.gitignore` Hygiene & Git Working Tree Guard
- **Automated Post-Setup & Post-Update Diagnostics**: Standardized `harness_doctor.py` as an automatic verification stage executed across `docs/setup-prompt.md`, `docs/install-prompt.md`, and `docs/update-prompt.md` to validate full 12-dimension health immediately after harness provisioning.
- **Deep `.gitignore` Security & State Inspection (`harness_doctor.py`)**: Added dedicated `.gitignore` inspection auditing root and harness-level `.gitignore` files to guarantee that transient state (`state/`, `.agents/state/`), Python cache (`__pycache__`, `*.pyc`), backup archives (`.harness-backup/`), and sensitive Zoho tokens (`zoho_config.json`) are completely excluded from source control.
- **Git Working Tree Status & Commit Reminders**: Added automated `git status` inspection to `harness_doctor.py` detecting uncommitted or untracked changes, accompanied by an explicit actionable advisory banner instructing developers to create a Git commit following harness setup or updates.

---

## [0.5.2] - 2026-08-24

### QA-Centric Zoho Handoff & Native Artifact Interactive Plan Review
- **QA-Centric Zoho Communication Policy (`harness-rules.md`, `zoho-sprints.md`)**: Standardized all task descriptions and comments across Zoho Sprints for QA / testers and product stakeholders. Strictly prohibited raw code dumps, internal XML layout files, Kotlin source references, and framework-level attributes (e.g. `clipToPadding`, `paddingBottom` dp values), enforcing functional, user-facing descriptions.
- **Mandatory Commit Hash & Impact Scope**: Enforced mandatory `Commit: <hash>` on the first line and an explicit `Impact Area (Blast Radius)` section across all Zoho item types (Bugs, Features/Stories, Tasks/Improvements) to guide regression testing.
- **Dynamic Dual-Language Workflow (`zoho-sprints.md`)**: Refactored the Zoho Sprints workflow playbook into standard English documentation with a comprehensive `Language Mapping Table` resolving English and Arabic section headers dynamically per `ZOHO_LANGUAGE` (`en_titles_ar_comments`, `all_en`, `all_ar`) in `_product.py`.
- **Native Artifact Planning & Interactive "Proceed" Review**: Replaced redundant `ask_question` plan approval modals with Antigravity native interactive `implementation_plan.md` artifacts (`RequestFeedback: true`), providing a direct UI **Proceed** action and reserving `ask_question` strictly for design tradeoffs and sequential manual device verification phases (`deliver.md`, `pre_invocation_reminder.py`, `android-harness-global.md.template`).

---

## [0.5.1] - 2026-08-24

### Installed Checkout Selftest Alignment & Dynamic Product Identity
- **Installed Checkout Selftest Adaptation (`_hook_selftest.py`)**: Enhanced the selftest suite to dynamically detect installed target Android checkouts (`.harness-setup/answers.json` or `.agents/` root). When running inside an installed client app, the suite verifies the client's `.agents/` hierarchy instead of requiring raw kit-only files (`CHANGELOG.md`, kit root `docs/`, `agents/` folder), guaranteeing zero false-positive selftest failures after installation or update.
- **Dynamic Product Name in Ephemeral Failure Notices (`ensure_hook_selftest.py`)**: Dynamically resolves the active application's `PRODUCT_NAME` from `_product.py` when generating ephemeral hook messages upon harness modifications.
- **Cross-Platform UTF-8 & Windows CP1252 Resilience**: Standardized UTF-8 encoding across setup wizard subprocess runners, preventing character encoding exceptions when processing Arabic titles and non-ASCII typography on Windows consoles.

---

## [0.5.0] - 2026-08-24

### 12-Dimension Harness Doctor & Interactive System Diagnostics
- **12-Dimension System Doctor Engine (`harness_doctor.py`)**: Introduced an automated, exhaustive diagnostic CLI runner that inspects 12 core operational layers:
  1. Environment & Host Runtime (Python >= 3.10, OS platform, Gradle wrapper, Android SDK path, Git status).
  2. File Structure & Version Alignment (`.agents/VERSION`, `harness-rules.md`, 24 core scripts, `hooks.json`).
  3. Complete Subagent Roster (all 8 subagents with active security fingerprint validation).
  4. Product Identity & Configuration (`_product.py`, package prefix, application ID, source root, assemble task).
  5. Template Leakage Check (verifying zero un-replaced `{{...}}` template placeholders in `.agents/`).
  6. Skills & Workflow Playbooks (verifying all 10 workflow playbooks and 7 domain architectural references).
  7. Multi-IDE Tool Adapters (verifying `AGENTS.md` and tool-specific configuration parity).
  8. Safety Hooks & Atomic State Locking (cross-platform atomic `state_lock()` and selftest validation).
  9. Live Process Streaming & Heartbeat (verifying line-buffered standard I/O and process tree cleanup).
  10. Preflight Verification Pipeline (verifying string parity, Room migration graph, and fast Kotlin lint).
  11. Zoho Sprints MCP Security Boundaries (verifying zero token leakage in repository).
  12. Connected Devices & ADB Hardware Diagnostics (querying physical devices, emulators, and Android API levels).
- **Interactive AI Assistant Diagnostic Prompt (`docs/diagnostic-prompt.md`)**: Added an interactive, dual-language (Arabic/English) copy-paste diagnostic prompt for developers to audit system health in a new chat across any supported AI assistant.
- **Workflow & Doctor Integration**: Integrated `harness_doctor.py` into `docs/quickstart.md`, `docs/update-prompt.md`, `README.md`, and `_hook_selftest.py`.

---

## [0.4.0] - 2026-08-24

### AST Parser Robustness, Room Graph Migrations & Network Socket Hardening
- **AST Parser Robustness & Multiline UI Strings**: Modernized `check_strings.py` to detect multiline Compose `Text(...)` parameters, handle parameter reordering, and strip `RESOURCE_CALL` before evaluation to prevent string concatenation bypasses.
- **Deep Room Schema Invariants & Migration Graph Analysis**: Extended `room_guard.py` with recursive `@Embedded` data class discovery across all entity hierarchies, native Room 2.4+ `AutoMigration(from, to)` annotation parsing, and BFS graph traversal (`is_migration_path_covered`) to validate transitive migration paths (e.g. 1 -> 2 -> 3).
- **Kotlin AST & Architecture Hygiene**: Whitelisted standard Android SDK symbols (`Build.VERSION.SDK_INT`, `UUID`, `@androidx.annotation.*`, `@file:OptIn`), excluded `abstract class` from `@AndroidEntryPoint` check to prevent Hilt compiler crashes, and dynamically scanned lookback annotations for Compose `@Immutable` state classes.
- **Heterogeneous Android & Groovy Gradle Discovery**: Added support for Groovy `applicationId` and `namespace` declarations without equals signs in `setup_wizard.py` and KMP `composeResources` fallback directory resolution.
- **Git Path Octal C-Escape Decoding**: Implemented `_unquote_git_path()` in `_repo_files.py` using `latin1` -> `unicode_escape` -> `utf-8` decoding, ensuring paths with spaces and Arabic characters are never dropped from git diff and safety gates.
- **Configurable Device Policy in Runners**: Replaced hardcoded emulator denials with project-configured `ALLOW_EMULATOR` in `run_device.py`, `logcat_doctor.py`, and `capture_screen.py`.
- **Network & Socket Resilience in Zoho MCP**: Enclosed UDP socket creation in `try...finally` cleanup to eliminate socket file descriptor leaks on DNS timeouts, enforced explicit 30.0s HTTP timeouts across all `urllib.request.urlopen` requests, added 3-attempt exponential backoff retry on HTTP 429 and 502/503/504 errors, and added validated OAuth token refresh error handling.

---

## [0.3.0] - 2026-08-24

### Shift-Left Proactive Quality, Reviewer Expansion & Test Quality Specialist
- **Shift-Left Proactive Quality Architecture**: Introduced Pre-Implementation Quality Invariants across `harness-rules.md` and `pre_invocation_reminder.py`, instructing coding agents to proactively satisfy review pillars prior to code execution for first-pass review approval.
- **Expanded Core Reviewer Pillars**:
  - `bug-reviewer-agent`: Added Network & I/O Resiliency checks (`IOException`, `SocketTimeoutException`, `UnknownHostException` in coroutines, error UI state exposure, exponential backoff).
  - `convention-reviewer-agent`: Added Accessibility standards (mandatory `contentDescription` on non-decorative images/icons, minimum 48dp touch target size) and KMP portability rules (zero `android.*` framework imports in `commonMain`).
  - `perf-anr-guardian-agent`: Added Battery & Sensor Life checks (`SensorEventListener` unregistration in `onPause()`/`DisposableEffect.onDispose`, Android 14+ foreground service type declarations, WorkManager charging constraints).
- **Dedicated Test Quality Specialist (`test-quality-reviewer-agent`)**: Introduced on-demand reviewer (`HARNESS_TEST_FINGERPRINT=quality-first-test-review-v1`) for unit and UI test files (`*Test.kt`), checking assertion depth, mocking integrity, and Coroutines `runTest` dispatchers.
- **Security & Concurrency Hardening**: Implemented atomic cross-platform file locking (`state_lock()`) preventing multi-agent state race conditions, child process lifecycle management preventing orphaned Gradle worker/AAPT2 daemon locks (`BaseException` process reaping), secure CI/CD environment variable parameterization (CWE-94 prevention), and escaped command normalization in safety hooks.
- **Model Selection Matrix by Assistant**: Added comprehensive **Recommended Models by Assistant (Setup vs Daily)** comparative matrix in `docs/tool-support.md` and `docs/quickstart.md` across 10 supported AI assistants and IDEs.
- **Automated CI/CD Pipeline**: Multi-OS GitHub Actions matrix testing Linux and Windows across Python 3.10, 3.11, 3.12, and 3.13 (`.github/workflows/ci.yml`).
- **Open-Source Community Health**: Added `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1), `SECURITY.md`, and interactive GitHub Issue Forms.

---

## [0.2.0] - 2026-08-23

### Multi-IDE Tool Adapters, Five-Leaf AI Quality Engine & Foundation
- **Multi-IDE & AI Assistant Support**: Automatic adapter generation for 14+ tools including Cursor, Google Antigravity, Claude Code, GitHub Copilot, Codex, Qwen Code, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, and Goose.
- **Five-Leaf Review Delivery Gate**: Mandatory, parallel 5-reviewer subagents (`BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`) before any assemble or release.
- **Dynamic Domain Discovery**: Automatically inspects project dependencies and codebase during installation to create tailored domain reference files (Audio/Media, BLE, Education/Games, Billing, etc.).
- **Live Gradle Task Runner (`run_gradle_task.py`)**: Real-time task logging with a 10-second heartbeat to prevent silent build timeouts.
- **Zoho Sprints MCP Integration**: Bidirectional task synchronization reading bug attachments, creating hierarchical subtasks, and posting Arabic/English QA handoff comments with exact Git commit hashes.
- **Interactive Update Notifier (`check_kit_update.py`)**: Automatic start-of-session update checker with 24-hour cache TTL and non-blocking timeout.
- **Greenfield Bootstrap Mode**: Interactive architectural questionnaire for blank Android and Kotlin Multiplatform projects.
- **Device & Package Safety**: Strict denial of `adb monkey` and unauthorized `pm clear` commands, with safe `run_device.py uninstall` support.

