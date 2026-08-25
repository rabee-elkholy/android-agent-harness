# Changelog

All notable changes to the **Android Harness Kit** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-08-26

### P1 Final Item: PM Abstraction Layer & Multi-Provider Adapters (Zoho, GitHub, Jira, Linear)
- **Provider-Agnostic Policy Engine (`agents/scripts/pm_policy.py`)**: New deterministic, offline registry generalizing rules section 5 to four trackers: `zoho_sprints`, `github_projects`, `jira`, `linear`. Per-provider status maps from kit canonical states (`in_progress`, `ready_to_retest` — e.g. Ready To ReTest becomes Jira "Ready for Testing", Linear/GitHub "In Review"), denied Done-class labels per provider, mutation trigger phrases (`update zoho` stays valid for Zoho; `update <provider>` otherwise), and bilingual handoff validation: `validate_handoff(text, lang_mode, provider)` enforces the `Commit: <hash>` first line, all mandatory sections via the documented EN/AR header mapping table per `ZOHO_LANGUAGE`, and rejects forbidden provider-Done status declarations. Unknown statuses/providers/language modes fail closed with actionable messages. Zero network I/O.
- **GitHub Projects Adapter (`agents/scripts/pm_github.py`)**: Stdlib subprocess wrapper around the official `gh` CLI (`issue list/view/comment/edit`, `gh project item-edit` where available). Every call is timeout-bounded and fail-closed (missing binary, non-zero exit, timeout, unparsable output). Authentication stays entirely with gh host auth — tokens are never read or printed. Status changes honor the policy map; Done-class transitions are refused before any gh invocation. Selftested exclusively via mocked `subprocess.run` (zero network).
- **External-MCP Trackers as Configuration (`agents/pm/mcp_registration.jira.md`, `.linear.md`)**: Copy-paste registration playbooks for the official upstream Jira/Linear MCP servers using the identical credential-isolation pattern as Zoho (user-level `~/.android-harness/<provider>.json`, never in repo), plus per-provider status-map tables and trigger phrases.
- **Setup Wizard I.20 "Which project tracker?"**: New question with options `zoho_sprints` / `github_projects` / `jira_mcp` / `linear_mcp` / `none`, recorded as `pm_provider` in answers and `PM_PROVIDER` in `_product.py`. Post-install guidance prints conditionally: gh CLI check command for GitHub, registration doc path for Jira/Linear. Absent field keeps today's Zoho-centric behavior byte-for-byte.
- **Doctor Upgrades (`harness_doctor.py`)**: Dimension 11 renamed to Project Tracker & PM Security; reports the active `PM_PROVIDER`, its trigger phrase, and user-level config presence. Credential isolation scan now covers `<provider>.json` patterns for every tracker. Core script inventory expanded from 29 to 31 audited scripts (`pm_policy.py`, `pm_github.py`).
- **Selftest Expansion**: New regression groups for the provider/status/trigger matrix, adversarial handoff validation (missing commit line, each missing section, denied statuses, unknown statuses), mocked-gh adapter fail-closed behavior, wizard I.20 conditional wiring with unknown-tracker guard, and the doctor PM provider line; semver assertions synced to 0.8.0.

---

## [0.7.0] - 2026-08-24

### P1 Domain Depth: Build Flavors (Variants) & Multi-Module Governance
- **Build Flavor Support (`_variants.py`, `run_gradle_task.py --flavor`, `run_device.py --flavor`, setup I.19)**: Full product-flavor lifecycle. The wizard discovers flavors from Groovy/KTS `productFlavors` blocks and asks which variant is the daily test target; runners resolve assemble tasks (`:app:assemble{Flavor}Debug`) and flavor APK paths automatically, with unknown-flavor rejection. Backward compatible: empty flavor = classic single-variant behavior. Debug-only discipline enforced by construction.
- **Multi-Module Governance (`_modules.py`, `fast_kt_lint.py`, `perf_guard.py`)**: Source-root discovery across every module (`*/src/main/{java,kotlin}` including KMP `androidMain`). `fast_kt_lint --all` and `perf_guard --all` now scan all modules instead of only `app/src/main`. New deterministic architecture gate `FEATURE_CROSS_IMPORT`: a feature module importing another feature is flagged at lint time — shared logic must route through `:core`/`:common`.
- **Doctor Upgrades (`harness_doctor.py`)**: Dimension 2 reports discovered module source roots (`:app`, `:core:data`, ...); install-consistency cross-check now validates daily-flavor parity between `answers.json` and `_product.py ACTIVE_FLAVOR` plus per-flavor task resolution.
- **Core Script Inventory**: Expanded from 27 to 29 audited scripts (`_variants.py`, `_modules.py`). Selftest adds 4 regression groups (resolver matrix, wizard discovery + I.19 wiring incl. unknown-flavor guard, multi-root discovery, boundary-lint matrix).

---

## [0.6.0] - 2026-08-24

### Standalone CLI Dispatcher, 11 Native Slash Command Packs, Pre-Commit Quality Gate & Claude Code PreToolUse Bridge
- **Zero-Dependency CLI Dispatcher (`harness_cli.py`, `pyproject.toml`)**: Introduced the standalone `android-harness` command-line executable (`pipx install git+https://github.com/rabee-elkholy/android-harness-kit.git`, or run in place via `python harness_cli.py`). Features 6 core subcommands (`init`, `update`, `doctor`, `preflight`, `selftest`, `version`), automatic engine discovery, and remote fallback kit provisioning.
- **11 Native Slash Command Packs (`agents/command-packs/`, `install_tool_adapters.py`)**: Added standardized, tool-native prompt templates automatically installed into `.claude/commands/` (Claude Code `/deliver`, `/debug`, `/doctor`, etc.), `.github/prompts/*.prompt.md` (GitHub Copilot), and `.codex/prompts/` (OpenAI Codex) with automated managed-marker pruning.
- **Deterministic Staged Pre-Commit Quality Gate (`agents/scripts/pre_commit_gate.py`, `--git-gate`)**: Implemented an ultra-fast (<5s), stdlib-only Git hook scanning staged changes for bilingual string parity, Room entity migrations, and fast Kotlin lint issues prior to commit. Installed via `--git-gate` setting `git config core.hooksPath .githooks`.
- **Claude Code PreToolUse Safety Bridge (`agents/scripts/cc_pre_tool_safety.py`, `--cc-hooks`)**: Ported the deterministic runtime safety hook to Claude Code sessions via the `PreToolUse` hook protocol in `.claude/settings.json`, enforcing zero-tolerance Git mutations and ADB restrictions outside Antigravity.
- **Core Script Inventory Expansion (`harness_doctor.py`, `_hook_selftest.py`)**: Expanded the audited core script manifest from 25 to 27 scripts in Dimension 2, with new selftests covering CLI dispatch, command packs, pre-commit gate, and Claude Code PreToolUse bridge.

---

## [0.5.7] - 2026-08-24

### Architectural Resilience Release: Parser Immunity, Cross-Tool Review Ledger, Barrier TTL & Install-Consistency Audit
- **Parser Adversarial Immunity (`check_strings.py`)**: The hardcoded-string scanner now truncates trailing `//` comments (string-literal aware) and skips Kotlin triple-quoted string blocks across lines, eliminating false positives from decoy `Text("...")` samples in comments/KDoc/multiline documentation strings while still flagging real code after a trailing comment.
- **Cross-Tool Review Ledger (`_hook_state.py`, `review_package.py`, `run_gradle_task.py`)**: `review_package.py` now records a review ledger (`state/review_ledger.json`) containing the package hash plus a fingerprint of the protected code tree at generation time. `run_gradle_task.py` prints a deterministic `REVIEW ADVISORY` when Kotlin/XML code changed after the last package was generated — giving Cursor/Claude/Copilot sessions (where Antigravity hooks do not run) a script-level, tool-agnostic staleness signal instead of prompt-only compliance.
- **Barrier TTL Expiry (`pre_tool_safety.py`)**: A pending 5-leaf review round now auto-expires after `HARNESS_BARRIER_TTL` seconds (default 6h) instead of wedging forever if the platform transcript format changes or subagents never reply. Format drift degrades to a time-based unblock with an explicit re-review reminder rather than a permanent assemble lockout.
- **Install-Consistency Dimension (`harness_doctor.py`)**: In installed checkouts (`.harness-setup/answers.json` present), the doctor cross-checks recorded answers against reality: device policy vs `_product.py ALLOW_EMULATOR`, assemble task parity, and presence/managed-marker of every selected tool adapter plus root `AGENTS.md`. A weak-model install that skipped steps now fails diagnostics with exact remediation commands instead of silently drifting.
- **Selftest Expansion**: New regression cases for triple-string/trailing-comment immunity, ledger recording + staleness comparator, and barrier TTL expiry; version assertions synced to 0.5.7.

---

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

### Consolidated Milestone (0.2.0 - 0.4.0): Foundation Era
- **0.4.0**: AST parser robustness, Room graph migrations with BFS path validation, Groovy/KMP discovery, git octal-escape decoding, configurable device policy, Zoho MCP network hardening.
- **0.3.0**: Shift-left quality invariants, expanded reviewer pillars (network resiliency, accessibility, battery/sensor), test-quality-reviewer-agent, atomic state locking, CI matrix, community health files.
- **0.2.0**: Initial public foundation - multi-IDE adapters, five-leaf review gate, domain discovery, live Gradle runner, Zoho Sprints MCP, greenfield bootstrap, device safety.
