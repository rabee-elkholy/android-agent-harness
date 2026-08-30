# Changelog

All notable changes to the **Android Harness Kit** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.14.15] - 2026-08-30

### Unified Install & Update Prompt File Consolidation
- **Unified Setup & Upgrade Architecture (`docs/install-or-update-prompt.md`)**: Consolidated installation and update workflows by renaming `docs/install-prompt.md` to `docs/install-or-update-prompt.md` and removing `docs/update-prompt.md`, retaining the original structural port and setup steps while clarifying its dual capability for fresh installations and project upgrades.
- **Synchronized Roster & Documentation Links**: Updated `README.md`, `docs/quickstart.md`, `docs/tool-support.md`, `docs/diagnostic-prompt.md`, `docs/setup-prompt.md`, `docs/sync.md`, `check_kit_update.py`, `pre_invocation_reminder.py`, `harness_cli.py`, and `scripts_dev/pin_prompt_docs.py`.

## [0.14.14] - 2026-08-30

### Autonomous Phase Pipeline, Review Round Cards & Zero-Timer Invariant
- **Continuous Autonomous Phase Pipeline (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**: Enhanced `autonomous_e2e` device verification mode so that upon passing `run_e2e_smoke.py` ([SUCCESS]), the Lead Agent outputs the Phase Milestone Card with verification evidence and proceeds immediately and autonomously to Phase N+1 without blocking the developer with interactive modals. Interactive `ask_question` modals are reserved exclusively for `manual_only` mode (with explicit numbered checklists) or upon test failures/crashes.
- **Transparent Review Round Summary Cards (`harness-rules.md`, `AGENTS.md`, `deliver.md`)**: Mandated outputting concise Review Round Summary Cards in chat whenever a review round finishes with non-PASS findings, detailing the exact findings and corrective fixes before re-dispatching the next round, eliminating developer loop anxiety.
- **Strict Zero-Timer & No-Sleep Invariant (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**: Strictly banned invoking `schedule`, running shell `sleep` commands, or polling `manage_task` in a loop while waiting for subagents, relying 100% on the system's reactive wakeup.

## [0.14.13] - 2026-08-30

### Foundation Reference Indexing & Automated Upgrade Pruning
- **Complete Foundation Indexing (`daily-scenarios.md`)**: Indexed all 7 universal foundation reference guides (`architecture-guidelines.md`, `ui-layout-and-theming.md`, `database-and-persistence.md`, `performance-and-optimization.md`, `test-quality-guidelines.md`, `automated-skills.md`, `daily-scenarios.md`) to guarantee 100% zero-warning diagnostics across all installations and updates.
- **Enhanced Update Engine (`update-prompt.md`)**: Enforced automatic pruning of legacy reference file names during upgrade while strictly preserving tailored project domain references and developer configurations.

## [0.14.12] - 2026-08-30

### Universal Generic Architecture References
- **Universal Reference Naming (`agents/skills/android-harness/references/`, `doctor/models.py`)**: Renamed foundation references to universal names to represent general Android development across modern and legacy codebases:
  * `architecture-mvi.md` -> `architecture-guidelines.md` (covers MVI, MVVM, MVP, Clean Architecture, Unidirectional Data Flow, Layer Separation)
  * `ui-compose-theme.md` -> `ui-layout-and-theming.md` (covers Jetpack Compose, XML Views, ViewBinding, Material 3/2 Theming, RTL/Arabic, Previews)
  * `room-database-migrations.md` -> `database-and-persistence.md` (covers Room, SQLite, Migrations, DataStore, EncryptedSharedPreferences)
  * `performance-anr-optimization.md` -> `performance-and-optimization.md` (covers ANR, Threading/Dispatchers, Memory Leaks, Battery, Sensors, Compose Jank)
- **Synchronized Roster & Documentation**: Updated `SKILL.md`, `daily-scenarios.md`, `perf-audit.md`, `perf-anr-guardian-agent.json` (fingerprint `v5`), `setup-prompt.md`, `update-prompt.md`, and `porting.md`.

## [0.14.11] - 2026-08-30

### Shift-Left Test Pre-Gate & Lead Agent Review First-Pass Optimization
- **Mandatory Shift-Left Test & Compilation Pre-Gate (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**: Mandated executing `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest` before generating review packages whenever Kotlin/Java code or tests are touched, catching constructor/signature mismatches and assertion errors in seconds before subagent dispatch.
- **Expanded Fast Kotlin Linter (`fast_kt_lint.py`)**: Added instant static checks for `TEST_RUNBLOCKING` (`runBlocking` inside `*Test.kt`), `UNIMPLEMENTED_STUB` (`TODO()` or `throw NotImplementedError()`), and `UNCHECKED_DOUBLE_BANG` (`!!` operators in production code).
- **Embedded Pre-Dispatch Quality Checklist (`pre_invocation_reminder.py`)**: Integrated an immediate 4-point verification checklist into agent context prompts to guarantee high first-pass review clearance rates.

## [0.14.10] - 2026-08-30

### Product Module Isolation in Doctor & Lifecycle Cross-Compatibility
- **`_product.py` Dynamic Module Isolation (`doctor/engine.py`)**: Isolated target app configuration loading in `_check_install_consistency` via `importlib.util.spec_from_file_location`, eliminating `sys.path` collision between raw kit templates and installed client checkouts.
- **Discovered Application IDs Exposure (`wizard/discovery.py`)**: Added `application_ids` array to `discover()` facts dictionary, ensuring complete metadata transparency during Greenfield and established project setup.
- **Lifecycle Cross-Compatibility Verification**: Completed and validated exhaustive empirical test matrix across Installation, Update, and Doctor lifecycles with 0 failures.

## [0.14.9] - 2026-08-30

### Automatic Local Git Privacy (.git/info/exclude) & Clean .gitignore Restoration
- **Automated Local Exclusion Architecture (`_repo_files.py`, `ensure_local_git_privacy`)**: Centralized local Git exclusion management via `ensure_local_git_privacy()`, ensuring all 27 harness directories, manifests, and transient patterns are automatically registered in `.git/info/exclude` across setup, update, preflight, and doctor runs.
- **Zero Shared `.gitignore` Pollution (`wizard/questions.py`, `doctor/engine.py`)**: Automatically removes all harness-related lines from the shared `.gitignore` file, keeping client repositories 100% clean with zero Git diff in Android Studio commit windows.
- **Automatic Scratch Script Pruning**: Automatically detects and purges stray helper scripts (`fix_product.py`, `script_step3b*.py`, `update_worker.py`) to prevent untracked file clutter in Android Studio.

## [0.14.8] - 2026-08-30

### Mandatory Autonomous E2E Enforcement, Silent Review Wait & run_device Bugfix
- **`run_device.py` APK Resolution Fix (`agents/scripts/run_device.py`)**: Fixed `TypeError` bug caused by redundant `apk = Path(args.apk)` assignment when running without explicit `--apk`, ensuring zero-argument `python .agents/scripts/run_device.py install-start` runs flawlessly.
- **Mandatory Autonomous E2E Execution (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**: Removed "optional" qualifier from Phase verification rules; strictly mandated `python .agents/scripts/run_e2e_smoke.py` execution immediately following APK installation when `DEVICE_VERIFICATION_MODE` is `autonomous_e2e`.
- **Silent Intermediate Review Wait Protocol (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**: Explicitly prohibited conversational countdown spam on intermediate subagent wakeups, requiring the Lead Agent to remain 100% silent and present the consolidated review table only after all verdicts arrive in context.

## [0.14.7] - 2026-08-30

### Hierarchy-Aware Gitignore Deduplication, CLI Ergonomics & Windows UTF-8 Resilience
- **Hierarchy-Aware `.gitignore` Deduplication (`wizard/questions.py`)**: Completely eliminated redundant subfolder entries (`.agents/state/`, `.agents/cache/`, `.agents/__pycache__/`) when parent `.agents/` is ignored, and automatically prunes legacy redundant entries from existing repositories to eliminate Git diff noise.
- **Windows Console Unicode Resilience (`_live_process.py`, `harness_cli.py`, `setup_wizard.py`)**: Reconfigured standard I/O to UTF-8 with replacement across CLI entrypoints, preventing `UnicodeEncodeError` crashes on Windows consoles with Arabic text and special symbols.
- **CLI Argument Ergonomics (`install_zoho_mcp.py`, `install_tool_adapters.py`)**: Allowed `install_zoho_mcp.py` to default `--repo` to current working directory (`Path.cwd()`), and made `--git-gate` parsing resilient to explicit `yes`/`no`/`true`/`false` values.

## [0.14.6] - 2026-08-30

### Autonomous E2E Smoke Testing Engine & Wizard Setup Integration
- **Autonomous E2E Smoke Testing Engine (`agents/scripts/run_e2e_smoke.py`)**: Built a zero-dependency (Python stdlib + native ADB) autonomous UI testing engine that inspects device UI hierarchy, asserts component visibility and scroll responsiveness across Compose & XML Views, catches runtime Logcat crashes, and captures timestamped verification screenshots.
- **Physical Device First & High-Precision Gestures**: Fully compatible with real physical Android devices (and emulators) across Android 5.0 through Android 15 with strict safety containment (aborts immediately if foreground package leaves target app).
- **Setup Wizard Question `I.22` (`wizard/questions.py`, `wizard/i18n.py`)**: Added user-selectable Device Verification Mode during project initialization (`autonomous_e2e` recommended default vs `manual_only`).
- **Doctor Diagnostic Engine Updates (`doctor/engine.py`, `doctor/models.py`)**: Expanded core script inventory to 35 audited scripts and added Dimension 4 device verification mode reporting.

## [0.14.5] - 2026-08-30

### Interactive Device Verification & Chat UX Signal Maximization
- **Explicit Manual Device Smoke Testing Steps (`harness-rules.md`, `AGENTS.md`)**: Mandated that upon completing APK installation on the connected physical device, the Lead Agent must provide explicit, numbered verification steps in the Phase Milestone Card detailing exact screens to open, interactions to perform, and expected behaviors to verify.
- **Interactive Phase Sign-Off Modal (`ask_question`)**: Required the Lead Agent to prompt the developer via an interactive choice modal (`(Recommended) PASS` / `FAIL`) to confirm device verification before unlocking Phase N+1.
- **Chat Noise Elimination**: Strictly prohibited mechanical progress messages ("running tests...", "waiting for subagents...", "installing apk...") ensuring completely silent execution during background tool runs.

## [0.14.4] - 2026-08-30

### Repository Alignment, Security Hardening & Managed Block Preservation
- **Repository Naming Alignment**: Completely unified repository identity to `android-harness-kit` across Git remotes, PyPI packaging, CLI endpoints, and documentation.
- **Path Traversal & Boundary Containment (`harness_cli.py`)**: Hardened `cmd_verify` with strict path traversal containment checks for `package.path` and all reviewed diff files, preventing escapes outside repository root or temporary directories.
- **Strict Reviewer Roster Validation**: Enforced strict canonical name and status validation for all 5 leaf reviewers in `verdict.json` verification.
- **Non-Destructive Managed Block Preservation (`install_tool_adapters.py`)**: Enhanced adapter file generation to cleanly preserve existing user-defined custom rules and instructions in `CLAUDE.md`, `AGENTS.md`, and `.cursorrules` using bounded `<!-- BEGIN ANDROID-HARNESS MANAGED BLOCK -->` markers.
- **Security Policy Modernization (`SECURITY.md`)**: Updated supported versions table to actively cover `0.14.x` through `0.10.x` with clear demarcation of AI developer safety vs mobile runtime application security boundaries.

---

**Included in 0.14.3 (2026-08-29):**

### Documentation & Developer Experience Priority
- **Primary AI Chat Prompt Workflow (`README.md`, `quickstart.md`)**: Restructured all lifecycle operations (Installation, Diagnostics & Health, Upgrades & Updates, and Emergency Rollback) to feature the one-click AI Chat Prompt URL as the primary, recommended method for maximum developer convenience and automated domain discovery.

---

**Included in 0.14.2 (2026-08-29):**

### Zero Git Pollution & Team Working Tree Protection
- **Comprehensive Local Exclusion (`install_tool_adapters.py`, `wizard/questions.py`)**: Automatically configured `.git/info/exclude` across all project setups and updates to strictly isolate all AI manifests, adapter rule files, and transient harness state (`.agents/`, `AGENTS.md`, `GEMINI.md`, `CLAUDE.md`, `CODEX.md`, `QWEN.md`, `.cursor/`, `.cursorrules`, `.windsurf/`, `.windsurfrules`, `.claude/`, `.clinerules`, `.amazonq/`, `.continue/`, `.junie/`, `.kilocode/`, `.roo/`, `.goosehints`, `*.diff`, `*.patch`, `*.secret`).
- **Clean Android Studio Working Tree**: Ensured that zero harness or AI rule files appear as modified or untracked in Android Studio Git, preventing any unintended commits or merge friction on shared team repositories.
- **Index Protection**: Applied automatic `git update-index --assume-unchanged` guards on adapter files to keep working trees permanently pristine.

---

**Included in 0.14.1 (2026-08-29):**

### Mandatory Phase Sign-Off Hard Barrier & Atomic Delivery
- **Unbreakable Phase Boundary Barrier (`harness-rules.md`, `AGENTS.md`)**: Mandated that the Lead Agent is strictly forbidden from creating, modifying, or planning any files for Phase N+1 until Phase N completes its full verification lifecycle (5-leaf review, unit tests, assembleDebug, device smoke test) and receives explicit developer sign-off in chat.
- **Universal Device Smoke Testing**: Mandated live physical device smoke testing across all phases (including pure Data/Repository refactoring) to verify application startup and existing screen stability before advancing.

### High-Signal Communication Policy & Zero Chat Noise
- **Chat Noise Elimination (`harness-rules.md`)**: Strictly prohibited mechanical progress messages (e.g. "reading file...", "running tests...", "waiting for reviews...") in chat.
- **Actionable Chat Invariants**: Restricted agent chat output exclusively to 4 high-value moments: plan approval, critical engineering tradeoffs, standardized Phase Milestone Cards, and final delivery with Conventional Commit.

### Shift-Left Coroutines & Test Quality Standards
- **Mandatory `runTest` Invariant (`test-quality-reviewer-agent.json`, `harness-rules.md`)**: Strictly banned `runBlocking` inside `*Test.kt` unit test suites, enforcing `runTest`, `StandardTestDispatcher`, Turbine for Flow assertion, and dual-branch (success + error) assertions from the very first draft.

---

**Included in 0.14.0 (2026-08-29):**

### Universal Adaptive Discovery & Architecture Flexibility
- **Adaptive Stack Introspection (`wizard/discovery.py`)**: Added automatic detection for DI frameworks (Hilt, Koin, Dagger, Manual/None), UI frameworks (Jetpack Compose, XML Views, Hybrid), Supported Locales (`res/values-*`), and Project Structure (Single-module, Multi-module, KMP).
- **Product Model Architecture Constants (`_product.py`)**: Added `DI_FRAMEWORK`, `UI_FRAMEWORK`, `SUPPORTED_LOCALES`, and `PROJECT_STRUCTURE` to product facts and answer normalization in `wizard/questions.py`.
- **Dynamic Heuristic Linting (`fast_kt_lint.py`)**: Made `@AndroidEntryPoint` enforcement conditionally active only when `DI_FRAMEWORK == "hilt"`, eliminating false alarms on Koin/Dagger projects. Dynamicized `@Preview` requirements based on active project locales.

### Deep Localization & Format Placeholder Guard
- **Deep Format Placeholder Matching (`check_strings.py`)**: Added positional and named placeholder validation (`%1$s`, `%2$d`, `%s`, `{name}`) across base and translated strings to prevent runtime StringFormat crashes.
- **Dynamic Multi-Locale Scan (`check_strings.py`)**: Added automatic discovery and parity auditing across all `values-*` resource folders with graceful bypass for single-locale projects.

### Offline Bundled Packaging & Standardized Exit Codes
- **Offline Wheel Distribution (`pyproject.toml`)**: Configured `package_data` mappings to include all agent templates, scripts, rules, and workflows inside the wheel.
- **Local Kit Resolution (`harness_cli.py`)**: Updated `resolve_kit()` to prioritize local bundled engine paths, eliminating runtime Git cloning requirements and enabling 100% offline installation.
- **Standardized POSIX Exit Codes (`harness_cli.py`)**: Implemented standardized CLI return codes (`0=PASS`, `1=FINDINGS`, `2=CONFIG_ERROR`, `3=INFRA_ERROR`, `4=INCOMPLETE_OR_STALE`).

### Structured Review Schema v2 & Monorepo Scaling
- **Verdict Schema v2 (`review_package.py`, `_hook_state.py`)**: Added `reviewed_files`, `skipped_files`, and `is_truncated` fields to review package metadata, warning developers if working tree changes exceed file limits in large monorepos.

---

**Included in 0.13.3 (2026-08-26):**

### Fix: Review Package Digest Alignment & Infinite Review Barrier Resolution
- **Canonical Whole-File SHA-256 Digest (`review_package.py`)**: Aligned the printed `HARNESS_PACKAGE_SHA256_12` with the whole-file SHA-256 hash computed by the engine at dispatch time. Previously, `review_package.py` printed the pre-digest (bytes before `PACKAGE_SHA256` marker), causing `EVIDENCE` footers cited by reviewers to mismatch the engine's expected package hash and preventing the review barrier from clearing.
- **Subagent Evidence Fallback Correction**: Corrected the misleading fallback sentence in all 8 subagent system prompts. Reviewers are explicitly instructed to use the value printed by `review_package.py` and never derive it from the package header.
- **Fingerprint Bump (`v2` / `v4` / `v3`)**: Updated subagent template fingerprints across all 8 subagents and `doctor/models.py`.

---

**Included in 0.13.2 (2026-08-26):**

### Fix: Neutralize Kit Placeholders in the Security Selftest
- **Neutral Placeholder in `_security_selftest.py`**: Replaced the `com.example.app` test literal in the `adb_cmd_package_clear_denied` case with the neutral `com.selftest.app` token (assertion semantics unchanged). Previously, every fresh install/update of v0.13.x failed the installed-checkout placeholder scan and required a manual patch of the shipped security selftest.
- **Always-On Placeholder Guard (`_hook_selftest.py`)**: The `kit placeholder grep agents/` scan now runs in the raw kit as well as installed checkouts, so a new `com.example` literal in any shipped file (other than the deliberate `_product.py` port canary and the self-exempt hook selftest) fails kit CI immediately instead of surfacing later on developer machines.

---

**Included in 0.13.1 (2026-08-26):**

### Atomic Milestone Enforcement & Mandatory PM Prompting
- **Strict Prohibition of Standalone Review Phases (`harness-rules.md`)**: Formally prohibited creating deferred "Review Phases" at the end of multi-phase plans. Mandated that every phase is an atomic lifecycle ending with its own test gate, 5-leaf review gate, build, device verification, and commit checkpoint before proceeding to the next phase.
- **Mandatory Proactive PM Chat Prompt**: Mandated that the Lead Agent proactively includes the Zoho Sprints User Story and Sub-tasks proposal directly in the chat message accompanying plan generation.
- **Explicit Device Sign-off Barrier**: Clarified that physical device verification (or unit test suite pass for pure Data/Domain layers) is the mandatory human sign-off barrier before presenting any conventional commit.

---

**Included in 0.13.0 (2026-08-26):**

### Superpowers Skills Integration
- **`brainstorming` Skill (`agents/skills/brainstorming/SKILL.md`)**: Structured 4-phase requirements probing, 2–3 architectural alternatives evaluation with trade-offs & blast radius, pre-screening of Android invariants, and spec locking before plan generation.
- **`test-driven-development` Skill (`agents/skills/test-driven-development/SKILL.md`)**: Strict **RED-GREEN-REFACTOR** protocol. Enforces writing failing unit tests in `src/test/`, empirical failure verification via Gradle test task, minimal implementation, green verification, and refactoring with Shift-Left quality invariants.
- **Complete 8-Skills Catalog**: Formalized catalog documenting `android-harness`, `brainstorming`, `test-driven-development`, `systematic-debugging`, `compose-inspector`, `kotlin-coroutines-expert`, `gradle-build-optimizer`, and `git-pr-automator`.

### Pre-Review Test Quality Gate (Stage 0.5)
- **Dedicated Test Gate (`agents/rules/harness-rules.md`)**: Automatically triggers `test-quality-reviewer-agent` independently whenever `*Test.kt` or `src/test/` files are present in the package diff.
- **Strict Quality Invariants**: Enforces assertion depth ($\ge 2$ asserts per test), Coroutines `StandardTestDispatcher` control with `advanceUntilIdle()`, pure Fakes and isolated Mock behaviors with `@After` teardown, and zero placeholder/empty stubs before advancing to the 5-leaf gate.

### Milestone Delivery & Standardized Progress Tracking
- **Phase-by-Phase Delivery Strategy**: Mandates presenting Strategy 1 (Iterative Phase-by-Phase) vs Strategy 2 (All-in-One) to the developer during plan drafting.
- **Standardized Milestone Status Format**: Clean, professional progress tracking in chat displaying active phase, target files, consolidated review verdicts, and completion summary without conversational noise.

### Silent Review Wait & UX Noise Elimination
- **Silent Review Wait Protocol (`harness-rules.md`)**: Lead Agent remains 100% silent in chat on intermediate subagent wakeups, letting the IDE's native visual cards display live progress spinners and checkmarks cleanly. Consolidated summary is printed only after all 5 verdicts are in context.

### Proactive Project Tracker Integration
- **Proactive Story & Task Breakdown**: Proactively prompts developer upon multi-phase plan approval to generate a User Story on Zoho Sprints / GitHub Projects with sub-tasks for each phase and track progress automatically.

---

**Included in 0.12.0 (2026-08-26):**

### Modular Architecture: Monolith Splitting
- **Zoho Sprints MCP Modularization (`agents/mcp/zoho_sprints/`)**: Extracted direct UDP DNS queries into `_dns.py`, HTML sanitization and markdown formatting into `_formatter.py`, and the full API client & OAuth token management into `_client.py`. `server.py` is now a slim JSON-RPC dispatch layer while preserving 100% backward-compatible tool symbols.
- **Harness Doctor Diagnostic Engine (`agents/scripts/doctor/`)**: Created dedicated `doctor` package with `models.py` (dataclasses, diagnostic manifests) and `engine.py` (the 12-dimension check suite). `harness_doctor.py` retains CLI entrypoint and full legacy symbol exports.
- **Setup Wizard Modularization (`agents/scripts/wizard/`)**: Created modular `wizard` package with `i18n.py` (bilingual English/Arabic translations, tool constants), `discovery.py` (Gradle modules, launchers, architectures, flavors), and `questions.py` (payload models, answer normalization, defaults prefill). `setup_wizard.py` maintains CLI dispatch.

### Reviewer Conflict Adjudication & Structured Findings (ADR-006)
- **Architecture Decision Record (`docs/adr/006-reviewer-conflict-adjudication.md`)**: Formally defined the two-tier finding severity hierarchy (`HARD_BLOCKER` vs `SOFT_FINDING`) and human authority overrides.
- **Severity Classification (`agents/scripts/_hook_state.py`)**: Added `SEVERITY_HARD_BLOCKER` and `SEVERITY_SOFT_FINDING` constants, `parse_structured_finding()`, and `adjudicate_review_findings()`.
- **Verdict Integration (`agents/scripts/pre_tool_safety.py`)**: `verdict.json` artifacts now record structured adjudication results under `record["adjudication"]`.

### Dynamic Developer Mirroring & Streamlined Wizard
- **Streamlined Setup Wizard (`wizard/questions.py`, `wizard/i18n.py`)**: Removed static chat language question (I.17) to reduce wizard friction. Retained tracker language question (I.18) with clean English descriptions supporting bilingual teams (`en_titles_ar_comments`).
- **Dynamic Language Policy (`agents/rules/harness-rules.md`)**: Configured dynamic language mirroring across developer chat (reply in Arabic when addressed in Arabic, in English when addressed in English) while enforcing strict English across code, symbols, and Git commit messages.

---

**Included in 0.11.0 (2026-08-26):**

### README Restructured: Truth-In-Docs Without Information Loss
- **README Condensed (`README.md`)**: Rewritten from 598 lines / 36 KB to 103 lines, keeping the hero + badges, the Before/After problem table verbatim, a new "Why this exists" narrative (agents self-report success without verification; deterministic gates must sit outside the model), a <=5-command quickstart, an Enforcement Levels table promoted from `docs/tool-support.md`, a five-leaf summary with evidence-footer semantics, pinned lifecycle-prompt URLs, and full doc/community footer links.
- **Relocated Detail (zero loss)**: 7-stage workflow mermaid, per-leaf reviewer focus/catches, expanded safety-interceptor detail (git protection, pre-commit gate, Claude Code/Copilot bridges, anti-polling, ephemeral state machine), preflight trio internals, Gradle runner bullets, device runner, and doctor commands moved to `docs/architecture.md`; CLI reference table and install modes A/B moved to `docs/quickstart.md`; wizard I.0-I.21 parameter table moved to new `docs/setup-wizard.md`; slash-command pack table and per-assistant integration features moved to `docs/tool-support.md`; Zoho sequence diagram and flagship feature bullets moved to `docs/workflows/pm-integrations.md`; CI matrix note added to `CONTRIBUTING.md`.
- **Honest Tool Badge**: The "14 Supported" badge now reads "14 IDs | 11 Templates" and links to the enforcement mapping.
- **Tool -> Template -> Enforcement Mapping (`docs/tool-support.md`)**: New explicit table mapping each of the 14 wizard tool ids to its adapter template file(s), the files written at the app root, and its enforcement tier (hook-enforced / rule-driven / prompt-only), including the eight AGENTS.md-only agents.
- **macOS CI Coverage (`.github/workflows/ci.yml`, `.github/workflows/release-check.yml`)**: `macos-latest` added to the CI test matrix and the release-validation job now runs as a three-OS matrix, matching the engine's cross-platform shell handling.
- **Roadmap (`ROADMAP.md`)**: New roadmap tracking the four delivered audit phases and future items (monolith splits, reviewer-conflict adjudication, signed artifacts).
- **Architecture Decision Records (`docs/adr/`)**: Five ADRs grounded in the shipped code: 001 five-leaf review gate as the only delivery barrier, 002 hooks-first enforcement with prompt-level fallback, 003 git mutation is human authority, 004 ephemeral per-conversation review state machine, 005 physical device over emulator — each with Context/Decision/Consequences.
- **Contributor Recipes (`docs/recipes/`)**: Three complete guides grounded in the real registration points: `add-a-reviewer.md` (subagent JSON + doctor roster + engine roster + selftest), `add-a-policy-rule.md` (vocabulary -> engine -> grants parity -> adversarial tests), and `add-a-tool-adapter.md` (template + installer registry + wizard ids + optional hook bridge) — each with concrete steps, file touchpoints, and an acceptance check command.
- **Compatibility Matrix (`docs/compatibility-matrix.md`)**: OS x Python x AI-tool support grid with enforcement tiers, universal pre-commit gate coverage, engine integration transports, and CI verification scope.
- **Fixed: GitHub Issue Templates (`.github/ISSUE_TEMPLATE/`)**: `bug_report.yml` contained mixed YAML indentation that made the file unparseable (GitHub would reject the bug form); it is rewritten with consistent indentation, and `feature_request.yml` regains its sixth dropdown option ("Project Tracker / PM Integration") that a stray indent had silently merged into the fifth. A deterministic stdlib selftest probe now guards issue-template YAML shape against regressions.
- **Deferred-Split Markers (`_hook_selftest.py`, `setup_wizard.py`, `harness_doctor.py`, `agents/mcp/zoho_sprints/server.py`)**: TODO markers added at the four oversized modules documenting the intended split points; restructuring itself is explicitly deferred (see ROADMAP.md).

### Golden Fixtures Committed
- **In-Repo Fixture Projects (`tests/fixtures/golden/`)**: All four generator profiles (classic, multimodule, flavors, kmp) committed as byte-stable golden trees with a provenance README; a selftest probe regenerates each profile into temp and asserts byte equality, so generator drift fails CI.
- **TTL Probe Hardening (`_hook_selftest.py`)**: The barrier-TTL test now dispatches a real review round before backdating `pending_since`, so it no longer depends on an empty working tree (uncommitted Kotlin files would otherwise correctly trip the tree-cleanliness gate).
- **Fixed: Golden-Fixture EOL Stability (`.gitattributes`, `_hook_selftest.py`)**: `core.autocrlf` smudge rewrote the committed fixture trees to CRLF, faking generator drift. Golden fixtures are now excluded from EOL normalization via `.gitattributes`, and the drift probe compares EOL-normalized bytes so it is robust to any git config.

### Demo Media Placeholder
- **Recording Guide (`docs/media/README.md`)**: Placeholder section backing the README demo table, with an exact four-shot list (install wizard, five-leaf dispatch with evidence footers and verify, blocked commit plus pre-commit gate, doctor report), export commands, and hygiene rules (<=30s, 1200px, no secrets).

### Benchmark Scaffold
- **Standardized Task List (`docs/benchmark/tasks.md`)**: Twelve benchmark tasks, each mapped to the harness gate with a determinate outcome (parity, Room, previews, network resiliency, blast radius, sensors, security, git authority, module boundaries).
- **Metrics Collector (`scripts_dev/benchmark/metrics.py`)**: Stdlib-only, zero-network collector rendering per-task markdown tables from a run directory (events.jsonl, harness audit_log.jsonl denies as unsafe-action blocks, manual interventions.json, tokens.jsonl) covering retries, unsafe-action blocks, build/test failures, human interventions, token counts, and wall time.
- **Results Template (`docs/benchmark/results-template.md`)**: Ready-to-fill agent-alone vs agent+harness comparison table with cost estimate and protocol notes.

### Machine-Verifiable Evidence: verdict.json Artifact
- **Structured Verdict Schema (`agents/scripts/_hook_state.py`, `review_package.py`)**: New `verdicts/verdict-<pkg12>.json` artifact per review round (schema_version 1: task_id, git_sha, package path+sha256, tree fingerprint, per-file SHA-256 map, dispatched/completed timestamps, per-leaf tokens+evidence, findings, PASS/PENDING/EXPIRED verdict). `review_package.py` emits the PENDING record at package generation and a `FILES_SHA256=` header line (capped at 200 files) so every review package carries per-file hashes.
- **Barrier-Clear Emission (`agents/scripts/pre_tool_safety.py`)**: The review barrier now completes the verdict artifact alongside the existing text evidence footer convention (additive only): PASS on evidence-verified clear, EXPIRED on TTL expiry, FAIL on evidence-shortfall denials — with per-leaf tokens, evidence validity, and findings captured best-effort. A safety decision can never be altered by the emission.
- **`android-harness verify` (`harness_cli.py`)**: New subcommand validating a `verdict-*.json` artifact against actual repo state: recomputes the package digest, re-hashes every recorded changed file against the working tree, checks the 5 evidenced leaves, flags a stale commit (exit codes: 0 PASS, 1 FAIL, 2 STALE). Optional `--rerun-checks` re-runs the installed engine's fast lint and string checks.
- **Fixed: `explain` Now Reads the Installed Checkout's Audit Log (`harness_cli.py`)**: `android-harness explain` previously always read the kit checkout's own log, never the installed app's decisions. It now resolves the audit path with explicit priority (`--repo` > `HARNESS_HOOK_STATE` > cwd `.agents`/`agents` discovery > kit fallback) and gains a `--repo` option; end users can finally inspect their own safety-hook decision history.
- **Regression Coverage (`_hook_selftest.py`)**: New probe asserts the PENDING artifact, its schema, package digest, and the FILES_SHA256 header; a second probe asserts the artifact reaches `verdict: PASS` with all 5 evidenced leaves after the barrier clears.

### Safety Engine Hardening: adb Exfiltration Verbs & cmd-package Wipe Denials
- **Device-Bound Exfil Verbs (`policy_vocab.py`)**: `root`, `remount`, `backup`, `reboot`, and `sync` added to `DEVICE_BOUND_ADB` — bare invocations now deny exactly like every other device-bound verb and require `-d`/`-s <serial>`.
- **cmd-package Wipe Denial (`pre_tool_safety.py`)**: `adb shell cmd package clear|uninstall <pkg>` now denies identically to `pm clear`/`pm uninstall`, closing the data-wipe laundering path; `cmd package list` remains allowed.
- **Regression Coverage (`_hook_selftest.py`, `_security_selftest.py`, `SECURITY.md`)**: Seven new hook cases (deny/allow matrix) and three adversarial security assertions; SECURITY.md threat table gained the two new attack-class rows.

### Threat Model Documentation
- **Dedicated Threat Model (`docs/threat-model.md`)**: New threat model covering prompt injection via repo instructions, `.agents/` config tampering, symlink/path-traversal attacks, secret exfiltration (logcat/env/MCP wiring), MCP tool poisoning, adb data-wipe/privilege bypasses, and floating kit provisioning — each mapped to its deterministic mitigation layer and enforcement code, with accepted residual risks called out explicitly.
- **Cross-Linked Security Docs (`SECURITY.md`, `docs/threat-model.md`)**: SECURITY.md gains an "Agent-Behavior Threat Model" pointer section; the threat model links back to the SECURITY.md reporting policy. No duplication between the two files.

### Supply-Chain Integrity: Pinned One-Click Prompt URLs & Checksum Headers
- **Immutable Prompt Pinning (`README.md`, `docs/`, `harness_cli.py`)**: All 29 raw one-click lifecycle prompt URLs moved from the floating `main` branch to the immutable `v0.10.8` release tag; the CLI now builds prompt URLs from the resolved kit version via `_prompt_url()` instead of hardcoded `main` constants.
- **Tamper-Evident Fetched Docs (`docs/install-prompt.md`, `docs/update-prompt.md`, `docs/diagnostic-prompt.md`, `docs/rollback-prompt.md`)**: Each raw-fetched prompt carries a Kit version + SHA-256 header covering every byte after the header line, plus an explicit verify-first instruction (mismatch = stop and report tampering).
- **Release Re-Pinning Tool (`scripts_dev/pin_prompt_docs.py`, `CONTRIBUTING.md`)**: New stdlib-only, idempotent tool that re-pins prompt URLs to a release tag and refreshes the fetched-doc checksums; documented as the Pinned Prompt Release Procedure (step 5 of Release Governance).
- **Pinned GitHub Actions (`.github/workflows/`)**: `actions/checkout` and `actions/setup-python` pinned to immutable commit SHAs (`v4.4.0` / `v5.6.0` respectively) in both CI workflows, removing the mutable-tag supply-chain surface.

---

**Included in 0.10.0 (2026-08-25):**

### Enforcement Parity, Red Team & Patch Consolidations (0.10.1 - 0.10.8)
- **Tracked Hook Isolation & Local Exclusions (0.10.6, 0.10.8)**: Added automatic `git update-index --assume-unchanged .githooks/pre-commit` and local exclusion in `.git/info/exclude` to ensure zero team friction and clean working trees.
- **Porting Determinism & Established Codebase Support (0.10.5, 0.10.7)**: Hardened execution sequence, eliminated redundant update modals, and upgraded the Five-Leaf Review Gate to seamlessly handle legacy (XML/MVVM) and modern (Compose/MVI/KMP) architectures.
- **Installed Checkout Selftest Hardening (0.10.3, 0.10.4)**: Neutralized kit-shipped placeholders and added installed-checkout degradation paths so tests pass anywhere.
- **Wizard Pre-Fill & Doctor Drift Remediation (0.10.1, 0.10.2)**: Enabled wizard answer pre-fill (`setup_wizard.py ask`), doctor install consistency remediation, and synchronized packaging metadata.
- **Adversarial Security Suite (`agents/scripts/_security_selftest.py`)**: Standalone red-team suite with 26 deterministic assertions covering git mutations, path traversal, stdin fuzzing, and secret leakage.
- **GitHub Copilot Enforcement Bridge (`agents/scripts/copilot_pre_tool_safety.py`)**: Enforces repository-level `preToolUse` hooks with support for camelCase and snake_case payloads.
- **Git Gate Default ON + Wizard I.21**: Staged pre-commit quality gate is installed by default with `--no-git-gate` opt-out.
- **Fixture Generator Promotion (`scripts_dev/fixtures/make_android_fixture.py`)**: Reusable stdlib fixture generator with 4 profiles (classic, multimodule, flavors, kmp).
- **Threat Model Documentation (`SECURITY.md`)**: Comprehensive mitigation mapping across all 7 threat classes.

---

**Included in 0.9.0 (2026-08-25):**

### Trust & Supply Chain: Pin-to-Tag Provisioning, Single Deny Vocabulary, Audit Log, Evidence-Backed Verdicts
- **Pin-to-Tag Kit Provisioning (`harness_cli.py`)**: The CLI no longer clones or floats to `main`. `ensure_kit` resolves the requested release (HARNESS_KIT_REF or the latest GitHub release tag), provisions a fresh checkout pinned to exactly `v<version>` via tag fetch + detached checkout, and asserts the checked-out `agents/VERSION` equals the requested version, failing closed with remediation commands on any mismatch. `refresh_kit` re-pins existing clones to an exact tag, keeps a pinned checkout when a tag is unreachable, and refuses to continue if the clone somehow sits on a named branch. `update` resolves the latest release tag from engine check data and never upgrades to a floating ref. `--kit` local-checkout override behavior unchanged.
- **Single Deny Vocabulary (`agents/scripts/policy_vocab.py`)**: Canonical frozensets for GIT_MUTATIONS, DEVICE_BOUND_ADB verbs, named EMULATOR_PATTERNS, DENIED_PM_OPS, FORBIDDEN_TOOLS, SHELL_INDIRECTION_PATTERNS, a homoglyph CONFUSABLES_MAP, and the static REASON_CODES table. `pre_tool_safety.py` now imports these (behavior identical); selftest proves the shipped `config.grants.example.json` allow/deny entries never contradict the vocabulary.
- **Append-Only Audit Log + `android-harness explain` (`pre_tool_safety.py`, `harness_cli.py`)**: Every `deny()`/`allow()` decision appends a sanitized JSONL record to `agents/state/audit_log.jsonl` — `{ts, decision, tool, reason_code, reason_short, cmd_sha256_12, conv_hint}` — never raw commands or secrets. The file caps at the last 1000 records (atomic rewrite under the state lock). New `android-harness explain [--last N]` subcommand prints recent decisions with human-readable labels from REASON_CODES.
- **Formal Review Package v2 (`review_package.py`, `_hook_state.py`)**: Packages now carry a structured header (`TASK_ID` from `$HARNESS_TASK_ID`/`--task`, `GIT_SHA`, `TREE_FINGERPRINT`, `GENERATED_AT`, `PACKAGE_SHA256` computed post-write over all preceding bytes) and print `HARNESS_PACKAGE_SHA256_12=` for the orchestrator. The review ledger records `git_sha`. Pre-v2 packages remain valid with a single stderr WARN line during this migration window.
- **Evidence-Backed Verdicts (`pre_tool_safety.py`, all 8 subagent templates, both review prompts)**: A leaf verdict only clears the delivery barrier when the reply carries `EVIDENCE pkg=<sha256_12> cites=<n>` matching the dispatched package (n file:line citations, or `cites=0` for a clean pass). Tokens without a footer — or footers with a wrong/missing pkg hash — are treated as not-yet-replied with an explanatory message. Gated behind `HARNESS_EVIDENCE_MODE=strict|legacy` (default strict; legacy preserves the token-only behavior for one migration window). Selftests cover forged tokens, wrong hashes, correct footers, and legacy parity.
- **Adversarial Fail-Closed Inputs (`pre_tool_safety.py`)**: NFKC + confusables normalization closes homoglyph/zero-width `git` variants, whitespace-collapsed mutation tokens, and `git -c k=v <mutation>` laundering; encoded/piped shell indirection (`| sh`, `sh -c`, base64 decode chains) is denied outright; hook stdin is capped at 5 MB. Core script inventory expanded from 31 to 32 (`policy_vocab.py`).

---

**Included in 0.8.0 (2026-08-26):**

### P1 Final Item: PM Abstraction Layer & Multi-Provider Adapters (Zoho, GitHub, Jira, Linear)
- **Provider-Agnostic Policy Engine (`agents/scripts/pm_policy.py`)**: New deterministic, offline registry generalizing rules section 5 to four trackers: `zoho_sprints`, `github_projects`, `jira`, `linear`. Per-provider status maps from kit canonical states (`in_progress`, `ready_to_retest` — e.g. Ready To ReTest becomes Jira "Ready for Testing", Linear/GitHub "In Review"), denied Done-class labels per provider, mutation trigger phrases (`update zoho` stays valid for Zoho; `update <provider>` otherwise), and bilingual handoff validation: `validate_handoff(text, lang_mode, provider)` enforces the `Commit: <hash>` first line, all mandatory sections via the documented EN/AR header mapping table per `ZOHO_LANGUAGE`, and rejects forbidden provider-Done status declarations. Unknown statuses/providers/language modes fail closed with actionable messages. Zero network I/O.
- **GitHub Projects Adapter (`agents/scripts/pm_github.py`)**: Stdlib subprocess wrapper around the official `gh` CLI (`issue list/view/comment/edit`, `gh project item-edit` where available). Every call is timeout-bounded and fail-closed (missing binary, non-zero exit, timeout, unparsable output). Authentication stays entirely with gh host auth — tokens are never read or printed. Status changes honor the policy map; Done-class transitions are refused before any gh invocation. Selftested exclusively via mocked `subprocess.run` (zero network).
- **External-MCP Trackers as Configuration (`agents/pm/mcp_registration.jira.md`, `.linear.md`)**: Copy-paste registration playbooks for the official upstream Jira/Linear MCP servers using the identical credential-isolation pattern as Zoho (user-level `~/.android-harness/<provider>.json`, never in repo), plus per-provider status-map tables and trigger phrases.
- **Setup Wizard I.20 "Which project tracker?"**: New question with options `zoho_sprints` / `github_projects` / `jira_mcp` / `linear_mcp` / `none`, recorded as `pm_provider` in answers and `PM_PROVIDER` in `_product.py`. Post-install guidance prints conditionally: gh CLI check command for GitHub, registration doc path for Jira/Linear. Absent field keeps today's Zoho-centric behavior byte-for-byte.
- **Doctor Upgrades (`harness_doctor.py`)**: Dimension 11 renamed to Project Tracker & PM Security; reports the active `PM_PROVIDER`, its trigger phrase, and user-level config presence. Credential isolation scan now covers `<provider>.json` patterns for every tracker. Core script inventory expanded from 29 to 31 audited scripts (`pm_policy.py`, `pm_github.py`).
- **Selftest Expansion**: New regression groups for the provider/status/trigger matrix, adversarial handoff validation (missing commit line, each missing section, denied statuses, unknown statuses), mocked-gh adapter fail-closed behavior, wizard I.20 conditional wiring with unknown-tracker guard, and the doctor PM provider line; semver assertions synced to 0.8.0.

---

**Folded minor release 0.7.0 (2026-08-24):**

### P1 Domain Depth: Build Flavors (Variants) & Multi-Module Governance
- **Build Flavor Support (`_variants.py`, `run_gradle_task.py --flavor`, `run_device.py --flavor`, setup I.19)**: Full product-flavor lifecycle. The wizard discovers flavors from Groovy/KTS `productFlavors` blocks and asks which variant is the daily test target; runners resolve assemble tasks (`:app:assemble{Flavor}Debug`) and flavor APK paths automatically, with unknown-flavor rejection. Backward compatible: empty flavor = classic single-variant behavior. Debug-only discipline enforced by construction.
- **Multi-Module Governance (`_modules.py`, `fast_kt_lint.py`, `perf_guard.py`)**: Source-root discovery across every module (`*/src/main/{java,kotlin}` including KMP `androidMain`). `fast_kt_lint --all` and `perf_guard --all` now scan all modules instead of only `app/src/main`. New deterministic architecture gate `FEATURE_CROSS_IMPORT`: a feature module importing another feature is flagged at lint time — shared logic must route through `:core`/`:common`.
- **Doctor Upgrades (`harness_doctor.py`)**: Dimension 2 reports discovered module source roots (`:app`, `:core:data`, ...); install-consistency cross-check now validates daily-flavor parity between `answers.json` and `_product.py ACTIVE_FLAVOR` plus per-flavor task resolution.
- **Core Script Inventory**: Expanded from 27 to 29 audited scripts (`_variants.py`, `_modules.py`). Selftest adds 4 regression groups (resolver matrix, wizard discovery + I.19 wiring incl. unknown-flavor guard, multi-root discovery, boundary-lint matrix).

---

**Included in 0.6.0:**

### Standalone CLI Dispatcher, 11 Native Slash Command Packs, Pre-Commit Quality Gate & Claude Code PreToolUse Bridge
- **Zero-Dependency CLI Dispatcher (`harness_cli.py`, `pyproject.toml`)**: Introduced the standalone `android-harness` command-line executable (`pipx install git+https://github.com/rabee-elkholy/android-harness-kit.git`, or run in place via `python harness_cli.py`). Features 6 core subcommands (`init`, `update`, `doctor`, `preflight`, `selftest`, `version`), automatic engine discovery, and remote fallback kit provisioning.
- **11 Native Slash Command Packs (`agents/command-packs/`, `install_tool_adapters.py`)**: Added standardized, tool-native prompt templates automatically installed into `.claude/commands/` (Claude Code `/deliver`, `/debug`, `/doctor`, etc.), `.github/prompts/*.prompt.md` (GitHub Copilot), and `.codex/prompts/` (OpenAI Codex) with automated managed-marker pruning.
- **Deterministic Staged Pre-Commit Quality Gate (`agents/scripts/pre_commit_gate.py`, `--git-gate`)**: Implemented an ultra-fast (<5s), stdlib-only Git hook scanning staged changes for bilingual string parity, Room entity migrations, and fast Kotlin lint issues prior to commit. Installed via `--git-gate` setting `git config core.hooksPath .githooks`.
- **Claude Code PreToolUse Safety Bridge (`agents/scripts/cc_pre_tool_safety.py`, `--cc-hooks`)**: Ported the deterministic runtime safety hook to Claude Code sessions via the `PreToolUse` hook protocol in `.claude/settings.json`, enforcing zero-tolerance Git mutations and ADB restrictions outside Antigravity.
- **Parser Adversarial Immunity & Cross-Tool Review Ledger (v0.5.7)**: Added comment truncation and triple-quoted string support in `check_strings.py`, review ledger verification (`state/review_ledger.json`) across non-Antigravity IDEs, barrier TTL expiry unblocks, and install-consistency audit in `harness_doctor.py`.
- **Core Script Inventory Expansion (`harness_doctor.py`, `_hook_selftest.py`)**: Expanded the audited core script manifest from 25 to 27 scripts in Dimension 2, with new selftests covering CLI dispatch, command packs, pre-commit gate, and Claude Code PreToolUse bridge.

---

**Included in 0.5.6:**

### Forensic Audit Hardening: Chained Git Mutation Interception & Diagnostic Inventory Parity
- **Chained Git Mutation Bypass Fix (`pre_tool_safety.py`)**: The git mutation scanner now splits commands on shell chaining operators (`&&`, `||`, `;`, `|`, newlines) and scans every segment independently. Previously, a leading inspection command could mask a chained mutation (e.g. `git status && git push origin main` or `git log --oneline; git reset --hard HEAD~1`) because the first regex match consumed the remainder of the command line. Pure inspection chains (e.g. `git status && git diff HEAD --stat`) remain allowed.
- **Core Script Inventory Completeness (`harness_doctor.py`)**: Added `new_feature_scaffold.py` to the Dimension 2 core script manifest. The doctor now audits all 25 shipped Python scripts instead of 24, closing an inventory blind spot.
- **Kotlin Source Domain Discovery (`harness_doctor.py`)**: `_detect_project_domains()` now scans Kotlin source files (bounded at 500 files, skipping `build`/`.git`/cache directories) in addition to Gradle build scripts, `libs.versions.toml`, and `AndroidManifest.xml`. This matches the documented v0.5.4 behavior and detects signatures that only appear in `.kt` code (e.g. `SensorManager`, `SoundPool`, `MediaPlayer`).
- **Documentation Veracity Sweep**: Corrected README adapter matrix drift (Cursor `.cursor/rules/android-harness.mdc` instead of legacy `.cursorrules`; Roo `.roo/rules/android-harness.md` instead of `.roomodes`), fixed the `run_device.py` example to include the required `install-start` action argument, aligned the I.4 device policy default with the actual wizard recommendation (`Physical + Emulator`), clarified I.16 Zoho as optional, added `test-quality-guidelines.md` to the foundation references enumeration in `docs/setup-prompt.md`, and updated "24 core scripts" references to 25 across README, architecture guide, and diagnostic prompt.

---

**Folded patch release 0.5.4 (2026-08-24):**

**Included in 0.5.5:**

### Scope Isolation Hardening & Application Localization Advisory
- **Scope Isolation Protection (`harness_doctor.py` Dimension 10)**: Refactored Preflight Pipeline inspection to classify pre-existing application string parity discrepancies as informational advisories (`[WARN]`) rather than fatal harness infrastructure failures (`[FAIL]`).
- **Real-Time Progressive Console Streaming (`harness_doctor.py`)**: Implemented progressive line-by-line output streaming with immediate `flush=True` for all 12 diagnostic dimensions. Eliminates stdout buffer delays and prevents tasks from appearing silent/frozen during background execution.

---

### Deep Domain References Integration & Architectural Coverage Guard
- **Deep Domain Discovery & Audit (`harness_doctor.py`)**: Enhanced the 12-Dimension Diagnostic Doctor with automated project domain discovery. Scans Gradle dependencies, `libs.versions.toml`, `AndroidManifest.xml`, and Kotlin source files to detect active architectural domains (Networking, Payments/Billing, Ads/Monetization, Location/Maps, Hardware/Sensors, Audio/Media, Local Storage).
- **Tailored Domain Reference Coverage Validation**: Verifies that every active project domain has a dedicated, tailored reference guide in `.agents/skills/android-harness/references/` (e.g. `networking-api-contracts.md`, `payment-gateways-architecture.md`, `ad-mediation-privacy.md`, `fitness-tracking-sensors.md`). Issues actionable recommendations if uncovered domains are detected.
- **Reference Indexing & Linkage Verification**: Audits `daily-scenarios.md` to guarantee that 100% of foundation and tailored domain reference files are actively indexed and linked, preventing orphan references and enabling AI subagents to cite exact project conventions during daily tasks.
- **Reference File Integrity Check**: Validates that all foundation references exist and contain valid, non-corrupted architectural guidance.

---

**Included in 0.5.0:**

### Automated Post-Setup Diagnostics, `.gitignore` Hygiene & Git Working Tree Guard
- **Automated Post-Setup & Post-Update Diagnostics**: Standardized `harness_doctor.py` as an automatic verification stage executed across `docs/setup-prompt.md`, `docs/install-prompt.md`, and `docs/update-prompt.md` to validate full 12-dimension health immediately after harness provisioning.
- **Deep `.gitignore` Security & State Inspection (`harness_doctor.py`)**: Added dedicated `.gitignore` inspection auditing root and harness-level `.gitignore` files to guarantee that transient state (`state/`, `.agents/state/`), Python cache (`__pycache__`, `*.pyc`), backup archives (`.harness-backup/`), and sensitive Zoho tokens (`zoho_config.json`) are completely excluded from source control.
- **Git Working Tree Status & Commit Reminders**: Added automated `git status` inspection to `harness_doctor.py` detecting uncommitted or untracked changes, accompanied by an explicit actionable advisory banner instructing developers to create a Git commit following harness setup or updates.

### QA-Centric Zoho Handoff & Native Artifact Interactive Plan Review
- **QA-Centric Zoho Communication Policy (`harness-rules.md`, `zoho-sprints.md`)**: Standardized all task descriptions and comments across Zoho Sprints for QA / testers and product stakeholders. Strictly prohibited raw code dumps, internal XML layout files, Kotlin source references, and framework-level attributes (e.g. `clipToPadding`, `paddingBottom` dp values), enforcing functional, user-facing descriptions.
- **Mandatory Commit Hash & Impact Scope**: Enforced mandatory `Commit: <hash>` on the first line and an explicit `Impact Area (Blast Radius)` section across all Zoho item types (Bugs, Features/Stories, Tasks/Improvements) to guide regression testing.
- **Dynamic Dual-Language Workflow (`zoho-sprints.md`)**: Refactored the Zoho Sprints workflow playbook into standard English documentation with a comprehensive `Language Mapping Table` resolving English and Arabic section headers dynamically per `ZOHO_LANGUAGE` (`en_titles_ar_comments`, `all_en`, `all_ar`) in `_product.py`.
- **Native Artifact Planning & Interactive "Proceed" Review**: Replaced redundant `ask_question` plan approval modals with Antigravity native interactive `implementation_plan.md` artifacts (`RequestFeedback: true`), providing a direct UI **Proceed** action and reserving `ask_question` strictly for design tradeoffs and sequential manual device verification phases (`deliver.md`, `pre_invocation_reminder.py`, `android-harness-global.md.template`).

### Installed Checkout Selftest Alignment & Dynamic Product Identity
- **Installed Checkout Selftest Adaptation (`_hook_selftest.py`)**: Enhanced the selftest suite to dynamically detect installed target Android checkouts (`.harness-setup/answers.json` or `.agents/` root). When running inside an installed client app, the suite verifies the client's `.agents/` hierarchy instead of requiring raw kit-only files (`CHANGELOG.md`, kit root `docs/`, `agents/` folder), guaranteeing zero false-positive selftest failures after installation or update.
- **Dynamic Product Name in Ephemeral Failure Notices (`ensure_hook_selftest.py`)**: Dynamically resolves the active application's `PRODUCT_NAME` from `_product.py` when generating ephemeral hook messages upon harness modifications.
- **Cross-Platform UTF-8 & Windows CP1252 Resilience**: Standardized UTF-8 encoding across setup wizard subprocess runners, preventing character encoding exceptions when processing Arabic titles and non-ASCII typography on Windows consoles.

**Included in 0.4.0:**

### Consolidated Milestone (0.2.0 - 0.4.0): Foundation Era
- **0.4.0**: AST parser robustness, Room graph migrations with BFS path validation, Groovy/KMP discovery, git octal-escape decoding, configurable device policy, Zoho MCP network hardening.
- **0.3.0**: Shift-left quality invariants, expanded reviewer pillars (network resiliency, accessibility, battery/sensor), test-quality-reviewer-agent, atomic state locking, CI matrix, community health files.
- **0.2.0**: Initial public foundation - multi-IDE adapters, five-leaf review gate, domain discovery, live Gradle runner, Zoho Sprints MCP, greenfield bootstrap, device safety.

---

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
