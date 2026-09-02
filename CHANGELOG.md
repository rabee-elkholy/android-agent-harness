# Changelog

All notable changes to the **Android Agent Harness** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.27.4] - 2026-09-02

### Complete E2E/Maestro Machinery Purge & Interactive Manual Checklist Mode
- **Complete E2E/Maestro Engine Purge (`_maestro_core.py`, `run_e2e_qa.py`, `run_e2e_smoke.py`, `qa-e2e-planner-agent`)**:
  - Permanently purged all automated E2E and Maestro scripts, runners, planners, workflows, and selftests from the harness kit.
- **Streamlined Interactive Manual Checklist Mode (`AGENTS.md`, `harness-rules.md`, `deliver.md`, `_product.py`)**:
  - Enforced developer-in-the-loop interactive verification as the default and standard mode: compile `:app:assembleDebug`, install via `run_device.py install-start`, present 2-3 simple human test steps in chat, trigger interactive confirmation modal (`ask_question`), and immediately deliver the Conventional Commit on PASS.
- **Anti-Forgery Safety Interceptor (`pre_tool_safety.py`)**:
  - Hardened pre-tool safety hook to deny any direct edits or file creation inside `.agents/state/` and `.agents/scripts/`, preventing unauthorized tampering with gates or review ledgers.
- **Universal Code Graph & Selftest Alignment**:
  - Updated codebase graph engine, wizards, and selftest suites to pass 100% cleanly with zero warnings and zero failures.

## [0.27.3] - 2026-09-02

### Application ID Resolution, PM Tracker Jargon Elimination & Local Privacy
- **Application ID & Launcher Package Discovery (`install_or_update.py`)**:
  - Enhanced `generate_product_py()` to dynamically discover `application_id` via `wizard.discovery` and fallback to the package prefix of the resolved launcher activity, preventing incorrect `com.<product>.app` defaults in client checkouts.
- **Zero Emojis & Zero Internal AI Jargon Governance (`AGENTS.md`, `harness-rules.md`, `pre_invocation_reminder.py`)**:
  - Mandated strictly human and QA-centric PM tracker comments (Zoho Sprints, Jira, Linear, GitHub Projects), prohibiting emojis and internal AI tokens (`5-Leaf Review`, `مراجع الهارنيس`, `Maestro Suite (1/1 Flows Passed)`).
  - Enforced structured, sequential testing steps for QA verification.
- **Local Privacy for Temporary Setup JSON Files (`install_or_update.py`)**:
  - Automatically added temporary setup dump and input files to local `.git/info/exclude` to guarantee zero working-tree pollution.

## [0.27.2] - 2026-09-02

### Anti-Dummy Maestro Gate, APK Freshness Parity & Final Verdict Hardening
- **Anti-Dummy Maestro Gate & Assertion Floor (`_maestro_core.py`, `run_e2e_qa.py`, `_maestro_selftest.py`)**:
  - Enforced a meaningful assertion and interaction floor (`assertVisible`, `assertNotVisible`, `assertTrue`, `tapOn`, `inputText`, `doubleTapOn`, `longPressOn`, `openLink`, `scrollUntilVisible`) in `validate_maestro_flow()`.
  - Added pre-execution validation in `run_e2e_qa.py`, immediately rejecting hollow or dummy test flows containing only `launchApp`/`scroll`.
  - Added automated unit test in `_maestro_selftest.py` ensuring dummy flows fail linting and execution.
- **APK Freshness & Unpacking Signature Parity (`_apk_freshness.py`, `run_e2e_qa.py`, `run_e2e_smoke.py`)**:
  - Converted input APK paths to `Path` objects before checking `is_absolute()`, preventing string attribute errors.
  - Updated `run_e2e_qa.py` and `run_e2e_smoke.py` to check `fresh_verdict.is_fresh` directly rather than attempting tuple unpacking.
- **Final Verdict Status & Leaf Token Extraction (`final_verdict.py`, `_final_verdict_selftest.py`)**:
  - Accepted `("APPROVED", "PASS")` as valid success states in review outcome evaluation.
  - Enhanced `_pick_leaf` to extract `token` from dictionary leaf objects containing cryptographic review evidence.
- **Application ID & Namespace Fallback Discovery (`wizard/discovery.py`)**:
  - Added `AndroidManifest.xml` package attribute fallback to ensure real package name is always discovered even when missing from Gradle DSL blocks.

## [0.27.0] - 2026-09-02

### Maestro E2E Engine Integration, Harness Code Graph Indexing & Automated CLI Setup
- **Harness Infrastructure Code Graph Indexing (`_graph_core.py`, `project_graph.py`)**:
  - Indexed all Harness scripts, workflows, and subagents into the universal Code Graph with entity types `[HARNESS_TOOL]`, `[WORKFLOW_PLAYBOOK]`, and `[SUBAGENT_ROSTER]`.
  - Added `project_graph.py --harness` and `--tools` CLI options to render an instant, comprehensive topology directory of all tools, workflows, and subagents.
  - Enhanced `--find <query>` to seamlessly search across both Android application classes and Harness tools/workflows with metadata-aware description and flag matching.
- **Anti-Guessing Barrier & Explicit Language Tagging (`_graph_core.py`, `project_graph.py`, `AGENTS.md`, `harness-rules.md`)**:
  - Symbol searches now explicitly output language tags (`[JAVA_CLASS]`, `[KOTLIN_CLASS]`, `[COMPOSE_SCREEN]`, `[XML_LAYOUT]`, `[HARNESS_TOOL]`) alongside full relative paths and module metadata.
  - Mandated Graph-First symbol discovery before opening files, eliminating guessing cascades (`.kt` vs `.java`) and speculative multi-file searches (`find_by_name *Payment*`, `find_by_name *nav*.xml`).
  - Strictly prohibited authoring custom ADB scratch Python scripts (`scratch/test_*.py`) and hardcoded device serials, enforcing declarative Maestro YAML flows in `.agents/e2e_cases/`.
- **Permanent Windows User PATH Persistence (`_maestro_core.py`)**:
  - Added `_persist_maestro_to_path()` in `_maestro_core.py` to permanently register `%USERPROFILE%\.maestro\bin` in the Windows User Environment Registry upon installation.

### Maestro E2E Engine Integration, Automated CLI Setup & Native Multi-Flow QA
- **Maestro E2E Engine Core (`_maestro_core.py`, `run_e2e_qa.py`, `run_e2e_smoke.py`)**:
  - Replaced legacy python-only ADB execution engine with Maestro (`maestro test`), providing sub-second UI hierarchy inspection, native Jetpack Compose semantics, and resilient test execution.
  - Implemented cross-platform native Python zip-based installer (`install_maestro_cli()`), downloading and installing Maestro CLI with zero external dependencies.
  - Added JUnit XML report parser, automatic failure screenshot capture, and logcat crash buffer forensics integrated into Phase Milestone Cards and `final_verdict.py`.
- **Native Multi-Flow Test Authoring (`qa-e2e-planner-agent.json`, `run_e2e_qa.py`)**:
  - Updated `qa-e2e-planner-agent` to author native Maestro YAML flows per case (`TC01_positive_flow.yaml`, `TC02_negative_flow.yaml`, `TC03_edge_flow.yaml`) in `.agents/e2e_cases/<task>/`.
  - Added `--generate-cases` scaffold generator and `--lint` offline flow validator.
- **Smart Setup & Automated Maestro Installation (`setup_wizard.py`, `install_or_update.py`)**:
  - Interactive setup wizard detects missing Maestro CLI when `autonomous_e2e` is selected, requests developer approval, and installs it automatically during setup.
  - `install_or_update.py` verifies and provisions Maestro CLI during harness install/update.
- **Strict Preflight Verification (`preflight_check.py`, `_maestro_selftest.py`)**:
  - Added Maestro CLI version check in preflight gate, issuing clean `[ENV-FAILURE]` (exit code 30) with installation guidance if missing.
  - Added `_maestro_selftest.py` unit test suite covering validation, scaffolding, JUnit parsing, and installation.

## [0.26.0] - 2026-09-02

### Universal Hub Defense, Comment & Keyword Filtering, and Zero-Noise Graph Slices
- **Universal Hub Defense & Star-Topology Blast-Radius Protection (`_graph_core.py`, `project_graph.py`)**:
  - Implemented `is_hub_or_base_symbol()` to dynamically identify framework roots (`Activity`, `Fragment`, `ViewModel`, `Context`, `Application`, `R`), generic base types (`Base*`, `*Base`, `Abstract*`), and high-fan-in symbols across any Android project.
  - Automatically restricts subgraph traversal to direct outgoing dependencies (`direction="outgoing"`), eliminating reverse hub expansion that previously caused thousands of unrelated application classes to flood feature queries.
- **Universal Static Code Parser Hygiene & Comment Stripping (`_graph_core.py`)**:
  - Added `strip_comments_and_strings()` to eliminate single-line comments, multi-line blocks, and string literals before running symbol extraction regexes.
  - Implemented language-standard `KOTLIN_RESERVED_DECLARATIONS` filter, completely preventing phantom declarations (`companion`, `val`, `var`, `for`, `is`, `the`) from polluting the code graph.
- **Multi-Module & Directory-Scoped Feature Boundary Extraction (`_graph_core.py`)**:
  - Enhanced `extract_feature_graph()` to match standard Android feature modules (`:feature:<name>`, `:features:<name>`), packages (`*.feature.<name>.*`), and directory structures (`/features/<name>/`, `/feature/<name>/`) across any project architecture.
- **Expanded Self-Test Suite (`_graph_selftest.py`)**:
  - Added Test 7 validating comment stripping, keyword filtering, and hub explosion defense with 30-screen star topology fixtures (38/38 assertions passed, 0 failures).

## [0.25.8] - 2026-09-02

### Feature-Level Architecture Slices, Multi-Node Disambiguation & Discovery Invariant
- **Feature-Level Architecture Slices (`project_graph.py --feature <name>`, `_graph_core.py`)**:
  - Added dedicated `--feature <NAME>` CLI command and `DependencyGraph.extract_feature_graph()` engine method.
  - Automatically isolates and extracts all components belonging to a feature package/module across Clean Architecture layers (UI Screens & Layouts with `[COMPOSE]` vs `[XML]` tags, ViewModels & State Holders, Domain UseCases & Contracts, Data Repositories & Sources, and Unit/UI Tests) in a single high-signal call.
- **Multi-Node Disambiguation & Subgraph Aggregation (`project_graph.py --find`, `_graph_core.py`)**:
  - Enhanced `--find <SYMBOL>` with `DependencyGraph.find_nodes()` to locate all matching nodes across IDs, names, declarations, and file paths.
  - When querying broad keywords (e.g. `event`, `post`, `food`), the engine now automatically aggregates all matching feature nodes and extracts their unified connected subgraph, eliminating top-level symbol collisions with generic utility classes.
- **Clean Architecture Slice Summarizer (`DependencyGraph.to_slice_summary()`)**:
  - Outputs a structured, token-efficient Clean Architecture breakdown of any selected feature or subgraph directly in console/chat, eliminating the need to speculatively read multi-thousand-line source files.
- **Graph Query Refinement & Exploration Invariant (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`)**:
  - Enforced a strict Graph Query Refinement Invariant: when initial graph queries match broad utilities, agents must refine queries with discovered symbol names or use `--feature` rather than falling back to directory listing cascades or reading raw source files.
- **Self-Test Suite Expansion (`_graph_selftest.py`)**:
  - Added Test 6 validating multi-node matching, feature subgraph extraction, internal dependency retention, and Clean Architecture layer summary formatting (30 assertions passed, 0 failures).

### Zero-Git-Pollution Clean Completion, Code Graph Pre-Warming & Graph-First Barrier
- **Zero-Git-Pollution Clean Completion (`docs/install-or-update-prompt.md`)**:
  - Removed outdated configuration commit instructions from the update completion card, clarifying that harness files are automatically excluded locally via `.git/info/exclude` without requiring working-tree commits.
- **Zero Cold-Start Code Graph Pre-Warming (`install_or_update.py`, `docs/install-or-update-prompt.md`)**:
  - Automatically parses the entire codebase, builds the dependency DAG, and caches `.agents/cache/project_graph.json` directly during harness installation and update, ensuring the graph is 100% warmed up and ready on the very first chat.
- **Graph-First Codebase Exploration Barrier (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`)**:
  - Mandated querying the Code Graph engine (`project_graph.py --find` / `--screens` / `--path-from/--path-to`) as the mandatory first-line discovery barrier before performing wide greps or multiple file views, preventing token waste and brute-force search cascades.
- **Automated Version Diff Changelog Highlights (`install_or_update.py`, `docs/install-or-update-prompt.md`)**:
  - Automatically extracts key feature highlights between the previous installed version and the new version directly from `CHANGELOG.md` for interactive update summaries.
- **Strict Locale Qualification Filtering (`wizard/discovery.py`, `_hook_selftest.py`)**:
  - Filtered out non-language Android resource qualifiers (`night`, `sw*dp`, `w*dp`, `h*dp`, `hdpi`, `v31`, `land`) from `SUPPORTED_LOCALES` in `_product.py`, preserving only true ISO language tags (`['en', 'ar']`).
- **Multi-Package Permission Grants (`_adb_core.py`, `_adb_core_selftest.py`)**:
  - Enhanced `grant_common_permissions()` to grant permissions across both `APPLICATION_ID` and launcher package prefix candidates when package IDs diverge.
- **Deep Hilt Injection Entry Point Auditing (`fast_kt_lint.py`)**:
  - Enhanced `@AndroidEntryPoint` lint check to trigger when `@Inject` or `hiltViewModel()` is present in diffs even if project-level DI is unspecified.
- **Zero-Friction Setup Wizard (`wizard/questions.py`, `wizard/discovery.py`)**:
  - Automatically discovers project identity from `settings.gradle(.kts)` `rootProject.name` or repository directory name with zero interactive prompt friction.

## [0.25.2] - 2026-09-02

### Universal Code Graph Engine, Resilient UI Hierarchy & Shift-Left Test Synchronization
- **Universal Code Graph & Topology Engine (`_graph_core.py`, `project_graph.py`, `_graph_selftest.py`)**:
  - Built zero-dependency Pure Python graph engine supporting Gradle multi-module DAGs (Groovy & Kotlin DSL, type-safe accessors), universal components (Java & Kotlin, XML layouts & Navigation, Compose screens), and Clean Architecture layer classification (UI -> ViewModel/Presenter -> UseCase -> Repository -> DataSource -> Tests).
  - Added cycle-safe BFS shortest path finding and isolated subgraph extraction with depth limits (`--depth N`), paired path validation (`--path-from` / `--path-to`), and token-efficient `compact` serialization saving up to 80% context.
  - Implemented incremental SHA-256 caching (`cache/project_graph.json`, sub-50ms) and heuristic self-healing for moved/renamed files with `[HEALED]` auto-repairs.
- **OEM-Resilient UI Hierarchy Dumps & Multi-Tier Foreground Resolution (`_adb_core.py`, `_adb_core_selftest.py`)**:
  - Enhanced `dump_hierarchy()` to validate true root `<hierarchy` XML tags, automatically falling back to `_dump_via_file()` when OEM ROMs (Oppo, Realme, Xiaomi, Samsung) return non-empty informational text messages on `exec-out /dev/tty`.
  - Implemented multi-tier foreground resolution across Android 12, 13, 14, 15: Tier 1 (`dumpsys window` with `u0` user ID and modern window token matching) and Tier 2 (`dumpsys activity activities` with `mResumedActivity` / `topResumedActivity`).
- **Harness Engine Mutation Protection in Client Apps (`pre_tool_safety.py`, `_security_selftest.py`)**:
  - Added safety guard denying AI agents from making ad-hoc modifications to `.agents/scripts/` files in client app checkouts.
- **Shift-Left Test & Mock Synchronization Pre-Gate (`harness-rules.md`, `AGENTS.md`)**:
  - Enforced mandatory unit test and mock synchronization alongside production code changes to guarantee first-pass review approvals and eliminate review round flapping.
  - Registered core scripts in `CORE_SCRIPTS` manifest verified across all 12 diagnostic dimensions of `harness_doctor.py`.

## [0.24.0] - 2026-09-01

### Advanced E2E Gestures, Component State Assertions, Offline Simulation & Live Task Streaming
- **Horizontal Gestures & Directional Scrolling (`_adb_core.py`, `run_e2e_qa.py`, `_adb_core_selftest.py`)**:
  - Added native support for `swipeLeft`, `swipeRight`, `scrollLeft`, and `scrollRight` gestures in `DeviceSession` and `FlowExecutor`.
  - Added horizontal directional scrolling to `scrollUntilVisible` (`direction: left` / `direction: right`) for navigating Jetpack Compose `LazyRow`, `ViewPager2`, and horizontal carousels.
- **Component State Assertions (`_adb_core.py`, `find_nodes()`)**:
  - Added `assertChecked` and `assertSelected` actions validating boolean state for Switch toggles, Checkboxes, RadioButtons, and Navigation Tabs.
  - Added `checked` and `selected` filter parameters to `find_nodes()` for UI hierarchy queries.
- **Offline Mode Simulation & Automatic Teardown Restoration (`_adb_core.py`)**:
  - Added `setNetwork: offline/online` and alias `network` toggling Wi-Fi and Mobile Data via ADB shell commands.
  - Enforced guaranteed network restoration via `FlowExecutor` `finally` block to prevent test devices from remaining offline on failure.
- **Pre-E2E Confirmation Ordering Before Test-Case Planning (`e2e-qa.md`, `harness-rules.md`, `deliver.md`)**:
  - Reordered the E2E verification lifecycle: developers are prompted via `ask_question` ("Start E2E round?" / "Skip E2E") before any test-case planning, scaffold generation, or `qa-e2e-planner-agent` invocation, eliminating wasted tokens and execution time on skipped test runs.
- **Background Task Live Streaming & Non-blocking IO Fix (`ensure_hook_selftest.py`)**:
  - Integrated `run_streaming()` with `echo=True` and `flush=True`, eliminating the "Empty log" display in IDE background task outputs.
  - Added `_read_stdin_safe()` with thread-isolated non-blocking read and explicit `--cli` / `--hook` flags.

## [0.23.0] - 2026-09-01

### Senior-QA Test-Case E2E Engine, Pre-E2E Interactive Confirmation & Shared ADB Core
- **Pre-E2E Interactive Confirmation Gate (`E2E_CONFIRM`, `pre_invocation_reminder.py`, `harness-rules.md`, `deliver.md`, `e2e-qa.md`, `AGENTS.md`)**:
  - Introduced `E2E_CONFIRM = "confirm"` policy in `_product.py` and `install_or_update.py`.
  - Mandated that the Lead Agent MUST ask the developer via `ask_question` in their active conversation language ("Start E2E round?" / "Skip E2E") before executing any E2E suite (`run_e2e_qa.py` or `run_e2e_smoke.py`).
  - Strict honesty invariant: on developer skip, device verification is explicitly marked `skipped by developer` in the Phase Milestone Card and delivery reports; never claimed as passed.
- **Shared ADB core (`_adb_core.py`)**: extracted the UI hierarchy model and matching (substring + exact + ambiguity detection), string/locale resolution, a strict declarative flow parser with action validation, and a `DeviceSession` providing polling synchronization, single-call `uiautomator dump`, pid/process-scoped crash detection with a cleared baseline, verified taps, clipboard/ADBKeyboard text input (Arabic + ASCII), and physical-device-first serial selection.
- **`run_e2e_qa.py`**: test-case-aware Senior QA runner with a positive/negative/edge case schema, per-case isolation (`relaunch`/`stop`/`none`), per-case verdicts with failure evidence, JSON/markdown reports, offline `--lint` validation, and a diff-grounded `--generate-cases` scaffold.
- **`qa-e2e-planner-agent`** + `e2e-qa.md` workflow: derive diff-grounded test cases from each plan phase.
- **`run_e2e_smoke.py`** refactored onto the shared core (no behavior regressions) and the APK freshness barrier now applies to every mode.

### Correctness & reliability fixes
- Eliminated cross-app and stale-buffer crash false positives; fixed `assertNotVisible` substring collisions via exact matching; taps now verify the foreground app; fixed full-qualified component launch; unknown flow actions fail validation instead of passing silently.

## [0.22.0] - 2026-09-01

### Interactive In-Chat Risk Tier Approvals, Codified 4-Scenario QA Engine & Convergence Polish
- **Interactive In-Chat Risk Tier Governance (`approve_risk.py`, `risk_tier.py`, `AGENTS.md`)**:
  - Added `--approve` flag support to `approve_risk.py` enabling seamless interactive modal approval via `ask_question` directly in chat, strictly eliminating non-interactive terminal execution blockers.
  - Refined risk classification: normal `AndroidManifest.xml` activity/service additions now classify as standard `MEDIUM` application changes, reserving `HIGH` tier strictly for sensitive permissions (`<uses-permission>`) and exported flags (`android:exported`).
- **Codified 4-Scenario Autonomous Senior QA E2E Testing (`run_e2e_smoke.py`, `AGENTS.md`, `harness-rules.md`)**:
  - Formally codified and mandated 4 explicit E2E execution scenarios across all agent guidelines:
    - **Scenario A (New Features & User Journeys)**: Declarative Maestro-compatible YAML flows (`.agents/e2e_flows/<feature>.yaml`).
    - **Scenario B (UI Bugfixes & Screen Refactors)**: Diff-aware auto-discovery launching modified Activities directly (`am start -n`) with assertions and scroll tests.
    - **Scenario C (Deep Links & Navigation Routing)**: URI resolution testing via `--target-deeplink <uri>`.
    - **Scenario D (Pure Data / Domain / Room / Worker Logic)**: Runtime boot verification confirming DI (Hilt), Room DB migrations, and background workers operate without Logcat crashes or ANRs.
  - Enabled diff-aware auto-discovery by default in `run_e2e_smoke.py` when no explicit flow or target is specified.
- **Review Round Cap & High-Signal Chat Polish (`_hook_state.py`, `pre_invocation_reminder.py`, `AGENTS.md`)**:
  - Increased default review round cap to 3 for natural convergence.
  - Mandated outputting a Review Round Summary Card on clean full PASS rounds.
  - Standardized background waiting status messages to plain text English status lines matching user language dynamically, completely eliminating internal task IDs (`task-1004`) and robotic meta-phrases.
  - Fixed `tree_code_fingerprint(repo=None)` signature and hardened `_hook_selftest.py` stdout banner parsing.

## [0.21.0] - 2026-09-01

### Autonomous Senior QA Engine, Declarative Maestro Flows & In-App UI Language Fingerprinting
- **Declarative Maestro-Compatible E2E Flow Engine (`run_e2e_smoke.py`)**:
  - Implemented a zero-dependency, pure-Python declarative flow parser supporting Maestro-compatible YAML and JSON formats (`.agents/e2e_flows/*.yaml`).
  - Supports comprehensive interactive actions: `launchApp`, `tapOn`, `inputText`, `eraseText`, `hideKeyboard`, `scroll`, `scrollUntilVisible`, `back`, `assertVisible`, `assertNotVisible`, `takeScreenshot`, and `wait`.
  - Built-in hybrid runner: automatically delegates to `maestro` CLI if installed on the host system PATH, or executes natively via ADB UI Automator with zero external pip dependencies.
  - Added CLI flags: `--flow <path>`, `--flow-text "<inline>"`, and `--force-native`.
- **In-App UI Language Fingerprinting & Dynamic String Resolution (`run_e2e_smoke.py`)**:
  - Automatically indexes all string resource dictionaries across `res/values*/strings.xml` per locale (`values`, `values-ar`, `values-fr`, etc.).
  - Fingerprints visible on-screen strings against dictionary keys to detect the active in-app locale dynamically, operating independently of the device's system language.
  - Resolves test target string keys (`stringKey: "..."`) dynamically to active in-app locale values at runtime.
- **Diagnostic Probing Sandbox & Zero-Leakage Barrier (`fast_kt_lint.py`, `harness-rules.md`, `AGENTS.md`)**:
  - Introduces lightweight temporary diagnostic probing logs tagged with `// [HARNESS-PROBE]` for bug investigation without triggering 6-reviewer rounds.
  - Enforces a zero-leakage lint barrier via `STRAY_DIAGNOSTIC_PROBE` in `fast_kt_lint.py`, strictly rejecting unstripped probes with `exit 1` before review package generation or final assemble.
- **Deep Failure Forensics Package (`run_e2e_smoke.py`)**:
  - Captures instant failure screenshots, dumps UI hierarchy XML to `.agents/state/e2e/failed_hierarchy.xml`, and extracts the last 50 Logcat lines to `.agents/state/e2e/failed_logcat.txt`.
  - Classifies E2E failures into structured categories: `ASSERTION_FAILED`, `RUNTIME_CRASH`, `TIMEOUT_UNRESPONSIVE`, or `ENV_FAILURE`.
- **Rule Alignment & Comprehensive Self-Test Suite (`_hook_selftest.py`, `AGENTS.md`, `harness-rules.md`)**:
  - Updated delivery gate items 16 & 17 and added unit test coverage for YAML flow parsing, in-app locale fingerprinting, and probe rejection.

**Included in 0.20.1 (2026-09-01):**

### Zoho Sprints Lifecycle Governance, QA Report Separation & Silent In-Progress Transitions
- **Strict Bug vs Story/Task Report Separation (`zoho-sprints.md`, `harness-rules.md`)**:
  - Strictly mandates that for **Bug** items, QA handoff reports (`Commit: <hash>`, root cause, solution, impact area, test cases) are posted exclusively as **Comments**. Modifying the Bug Description is strictly forbidden to preserve the QA team's original reproduction steps and environment reports intact.
  - For **Task / Story / Sub-task / Improvement** items, the handoff report is written directly to the **Description** as the permanent architecture and feature reference, accompanied by a short commit hash comment.
- **Silent `In progress` Task Start Transition (`zoho-sprints.md`, `harness-rules.md`)**:
  - Automatically and silently updates ticket status to `In progress` upon implementation plan approval without posting redundant comments, maintaining zero-noise communication.
- **Local Multi-Phase Feature Lifecycle Protocol (`harness-rules.md`, `zoho-sprints.md`)**:
  - Establishes local phase management inside `implementation_plan.md` for multi-phase tasks, updating the main parent task on Zoho Sprints upon full delivery without cluttering the project tracker with micro sub-tasks.
- **Handoff Git Commit Verification Guardrail**:
  - Enforces verifying a clean working tree and actual commit hash via `git log -1` before generating delivery reports, preventing placeholder or uncommitted hash submissions.

## [0.20.0] - 2026-09-01

### Smart Test-Aware Review Promotion & Integrity Barrier
- **Automatic 6th Reviewer Promotion on Test Diffs (`review_package.py`, `pre_tool_safety.py`, `_hook_state.py`)**:
  - Automatically detects modified or newly added test files (`*Test.kt`, `*Tests.kt`, `src/test/`, `src/androidTest/`, `src/sharedTest/`) during review package generation.
  - Adds `CONTAINS_TESTS=true`, `TEST_FILES_COUNT=<n>`, and `REQUIRED_LEAVES=6` to package headers and review state.
  - Automatically promotes `test-quality-reviewer-agent` to a mandatory 6th reviewer in the parallel review batch whenever test files are touched.
  - Pre-tool safety hook strictly denies 5-leaf review invocations on test-bearing packages, requiring all 6 leaves in exactly one parallel `invoke_subagent` call to prevent agents from weakening assertions or adding shallow mocks undetected.
- **Strict Multi-Layer Delivery Barrier for Test Quality (`pre_tool_safety.py`, `final_verdict.py`, `_hook_selftest.py`)**:
  - Requires all 6 PASS tokens (`BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`, `TEST_PASS`) with valid matching `EVIDENCE pkg=<sha256_12>` footers before unlocking `:app:assembleDebug`.
  - Blocks final delivery (`final_verdict.py`) with status `BLOCKED` and explicit `blocked_by: ["test_quality"]` if `test-quality-reviewer-agent` verdict is missing on test diffs.
- **Rule & Reminder Alignment (`AGENTS.md`, `harness-rules.md`, `pre_invocation_reminder.py`)**:
  - Synchronized harness instructions and pre-invocation reminder prompt across all IDE adapters to reflect the Smart Test-Aware Review Promotion invariant.

**Included in 0.19.0 (2026-09-01):**

### APK Freshness & Stale Build Barrier, Interactive Reference Review Links & Zero-Noise Background Protocols
- **APK Freshness & Stale Build Barrier (`_apk_freshness.py`, `_apk_freshness_selftest.py`, `run_device.py`)**:
  - Built a dedicated, high-speed (<15ms) build freshness verifier checking APK creation timestamps (`mtime`) against all modified source and resource files (`.kt`, `.java`, `.xml`, `AndroidManifest.xml`, `.gradle*`, `.pro`, etc.) in the working tree.
  - Automatically rejects installation attempts (`run_device.py install-start`) when the target APK is older than repository changes, exiting immediately with `exit 1` and a structured diagnostic banner requiring `:app:assembleDebug`.
  - Verifies that Gradle assemble gate results (`_gate_results.py`) match the current `git_sha` and passed with status `PASS`.
- **Interactive Tailored Reference Reviews with Clickable IDE Links (`docs/setup-prompt.md`, `docs/install-or-update-prompt.md`)**:
  - Mandated formatting all discovered project domain reference files as clickable markdown links (`[filename.md](file:///<path>)`) within the `ask_question` approval modal during update and setup sessions.
  - Explicitly informs developers in their active conversation language that they can click and review each reference guide directly in their IDE before confirming.
- **Zero-Noise Chat & Background Task Silence Hardening (`docs/install-or-update-prompt.md`, `harness-rules.md`, `AGENTS.md`)**:
  - Reinforced strict zero-noise chat invariants during long-running background tasks (e.g. Gradle compilation), requiring the agent to output empty string `""` and rely purely on native platform reactive notifications.

**Included in 0.18.0 (2026-09-01):**

### Governance Suite: Exit-Code Protocol, Review Round Cap, Structured Final Verdict, Baseline Test Gate, Risk Tiers & Impact Analysis
- **Exit-Code Protocol & Environment Failure Classification (`_env_codes.py`, `_env_codes_selftest.py`)**:
  - Introduced standard exit code `30` (`EXIT_ENV`) for environment, network, and ambiguous ADB/Gradle failures, separating them from code failures (`exit 1`).
  - Added deterministic regex and exit code classification (`CLASS_ENV`, `CLASS_CODE`, `CLASS_AMBIGUOUS`) across `run_device.py`, `run_e2e_smoke.py`, `run_gradle_task.py`, and `run_tests_gate.py`.
  - Halts the agent immediately with `[ENV-FAILURE]` marker upon environment issues and atomically writes `.agents/state/env_failure.json`, strictly prohibiting the agent from modifying project code, Gradle files, or the manifest to bypass environment failures.
- **Per-Task Review Round Cap & Anti-Loop Warning (`_hook_state.py`, `review_package.py`, `_round_cap_selftest.py`)**:
  - Implemented an isolated, per-task review round ledger tracking review iterations per task ID and resetting upon `HEAD SHA` movement.
  - Generates a prominent `REVIEW ROUND CAP` warning when reaching the cap (2 rounds), instructing the agent to output a Review Round Summary Card and prompt the developer (continue / rollback / stop) rather than looping silently.
- **Machine-Readable Unified Final Verdict Aggregation (`final_verdict.py`, `_gate_results.py`, `_final_verdict_selftest.py`)**:
  - Unified gate result artifact emission across all delivery gates into `.agents/state/results/<gate>.json`.
  - Created `final_verdict.py` aggregating unit tests, preflight, assemble, device, E2E smoke, and 5-leaf parallel review results into an atomic, machine-readable `.agents/state/last_verdict.json` with status values (`APPROVED`, `BLOCKED`, `ENV_BLOCKED`, `STALE`, `EXPIRED`).
  - Enforces tree fingerprint consistency, diff SHA-256 computation, and older-HEAD artifact invalidation.
- **Known-Failures Debt Registry & Baseline-Aware Test Gate (`baseline_capture.py`, `run_tests_gate.py`, `_baseline_selftest.py`)**:
  - Created `baseline_capture.py` to record pre-existing unit test debt into `.agents/state/baseline.json` with SHA-256 test fingerprinting, enforced clean-tree capture invariants, and required `--approve` flag for refreshing.
  - Implemented `run_tests_gate.py` to parse JUnit XML reports and classify test failures into `BASELINE_IGNORED` (tolerated pre-existing debt) vs `NEW_REGRESSION` (blocks delivery with `exit 1`).
- **Risk-Tiered Approval Gates & Human Intervention Barrier (`risk_tier.py`, `approve_risk.py`, `_risk_and_impact_selftest.py`)**:
  - Implemented four-tier diff risk classification (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) with file-level floor invariants for sensitive surfaces (billing, purchases, security/crypto, proguard rules, Room database migrations, AndroidManifest permissions).
  - Built `approve_risk.py` as an interactive-only human approval barrier requiring developer confirmation via TTY and refusing AI agent automated execution (`stdin=DEVNULL`).
  - Added Step 4 to `preflight_check.py` to verify risk approvals and prevent assembling unapproved `HIGH`/`CRITICAL` changes.
  - Embedded `RISK_TIER=` classification into the review package header for all 5 reviewers.
- **Change Impact Analysis & Dependency Graph (`impact_analyzer.py`)**:
  - Built an AST/regex-based Kotlin/Java dependency indexer calculating direct and transitive (depth 2) dependencies, mapping modified symbols to impacted unit tests and UI surfaces for focused verification.

**Included in 0.17.0 (2026-08-31):**

### One-Command Deterministic Harness Engine & Diff-Scoped Quality Guards
- **Anti-Hallucination Invariant & Background Task Protocol (0.17.2)**:
  - Explicitly prohibited fabricating, injecting, or simulating fake `<MESSAGE_RECEIVED>` completion tags in agent thoughts or chat prose.
  - Required the agent to stop calling tools and end turn silently with empty string `""` on prerequisite background tasks to allow genuine reactive wakeup.
  - Enhanced component launching and multi-package foreground detection in `run_e2e_smoke.py`.
- **Diff-Scoped Pre-Commit Gate & String Parity Guard (0.17.1)**:
  - Refactored `pre_commit_gate.py` and `check_strings.py` to be 100% diff-scoped on modified lines, completely ignoring untouched legacy code and untranslated pre-existing strings.
  - Extended the safety hook review barrier to `preflight_check.py`.
- **One-Command Deterministic Harness Engine (`install_or_update.py`)**:
  - Built standalone, zero-dependency Python engine that executes complete harness installation and updates atomically in under 3 seconds with automated timestamped backup and reference preservation.

### One-Command Deterministic Harness Engine, Upstream Bug Fixes & Instant Porting Pipeline
- **One-Command Deterministic Harness Engine (`install_or_update.py`)**: Built a dedicated, standalone, zero-dependency Python engine that executes complete harness installation and updates atomically in under 3 seconds:
  - Automated timestamped backup with single-copy pruning in `<repo>/.harness-backup/` and `$HOME/.harness-backups/`.
  - 100% automatic preservation of existing custom tailored domain references (`.agents/skills/android-harness/references/*.md`).
  - Atomic `.agents/` replacement, transient `state/` cleanup, and `.gitignore` configuration.
  - Automatic generation of `_product.py` from `answers.json`.
  - Automated configuration of multi-IDE adapters (`AGENTS.md`, `GEMINI.md`, `.cursorrules`, etc.) and Zoho MCP / tracker wiring.
  - Automatic registration of all private harness paths in `<repo>/.git/info/exclude`.
  - Automated verification running `_hook_selftest.py` and `harness_doctor.py` reporting 0 failures.
- **Upstream Dynamic Emulator Verification (`_hook_selftest.py`)**: Replaced hardcoded `"allow"` expectation in `emu` test case with dynamic `ALLOW_EMULATOR` resolution (`"allow" if ALLOW_EMULATOR else "deny"`), preventing false failures on `physical-only` checkouts.
- **Template Leak False-Positive Resolution (`_hook_selftest.py`, `harness_doctor.py`)**: Broken up string literals for `"{{UNIT_TEST}}"` and `"{{PM_TRIGGER}}"` in selftest code, ensuring Dimension 5 (Template Leak Check) in `harness_doctor.py` passes cleanly with 0 false positives.
- **Unified CLI & Wizard Integration (`setup_wizard.py`, `harness_cli.py`)**: Added `apply` subcommand to `setup_wizard.py` and wired `android-harness init` and `android-harness update` to use `install_or_update.py` directly.
- **Streamlined Setup & Update Prompts (`docs/setup-prompt.md`, `docs/install-or-update-prompt.md`)**: Replaced 300 lines of manual multi-turn porting steps with a single direct invocation of `install_or_update.py`.

**Included in 0.16.0 (2026-08-31):**

### Diff-Scoped Fast KT Lint, Pre-Gate Deadlock Fix, Hard Review Package Gate & Precision Strings
- **Diff-Scoped Fast Kotlin Lint (`fast_kt_lint.py`, `_hook_selftest.py`)**: Added `get_modified_lines_map` parsing `git diff -U0 HEAD` to apply line-level coding invariants (`!!`, inline FQCNs, `runBlocking`, `TODO` stubs, wildcard imports) strictly to modified/added lines in the working tree diff without penalizing untouched legacy code in the same files.
- **Pre-Gate Deadlock Resolution (`pre_tool_safety.py`)**: Disentangled unit tests from full assemble/device deployment in `handle_run_command`, explicitly unblocking `:app:testDebugUnitTest` (and unit test tasks) as a pre-review test gate while keeping `:app:assembleDebug`, bundle, and device installation strictly blocked until 5-leaf review PASS.
- **Hard Deterministic Lint Pre-Gate in Review Package Generator (`review_package.py`)**: `review_package.py` now automatically executes `fast_kt_lint.py` before building diff packages and aborts with `Exit Code 1` on violations, preventing invalid packages and wasted review tokens.
- **Adaptive Strings Guard & Duplicate Resource Key Detector (`check_strings.py`)**:
  - Refactored `PLACEHOLDER_RE` with lookaround guards to eliminate false-positive placeholder matches on literal percentage phrases (e.g. `40% extra`, `55 % Discount`, `20%, drastically`, `% From`).
  - Added duplicate resource key detection across `<string>`, `<plurals>`, and `<string-array>` in `_parse_resources`, catching duplicate insertions before Gradle AAPT2 merger crashes during assemble.
- **Delivery Rules & Governance Synchronized (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**: Documented the diff-scoped linting contract and unblocked unit-testing flow across all agent instructions.

**Included in 0.15.0 (2026-08-31):**

### System Audit Report, Product-Policy Safety Hooks & Client-Facing Parameterization
- **Kit Prose De-Arabized — Language Mirrors the Developer (`wizard/i18n.py`, `wizard/questions.py`, `harness-rules.md`, `AGENTS.md`, docs)**: Removed the wizard's Arabic table (I.18 tracker-language keys kept), Arabic update-modal labels, and the Arabic `schedule` deny keyword. Chat-language policy generalized to mirror whatever language the developer writes in. SHA-256 headers re-pinned for the edited prompt docs.
- **System Audit Report (`docs/conflicts-and-edgecases-report.md`)**: New report documenting CLI conflicts (preflight target, exit codes, output markers), rules/enforcement contradictions (5-vs-6 leaves, sequential wording), 14 edge cases, and the full Arabic inventory with a priority matrix and resolution status.
- **`preflight` CLI Checks the Client Checkout (`harness_cli.py`, `_repo_files.py`)**: `cmd_preflight` prefers the checkout's own `.agents/scripts/preflight_check.py`; falls back to the kit script with a new `HARNESS_REPO` env override. Kit-dir runs remain self-checks.
- **Product-Policy-Driven Safety Hooks (`_product.py`, `pre_tool_safety.py`)**: Added `GIT_POLICY` and `INSTALL_CONFIRM`; the hook now honors `ALLOW_EMULATOR` (I.4) and `agent-may-commit` (I.3, `git add`/`commit` only — push/merge/rebase/reset stay denied). Wizard I.22 gained a `disabled` option.
- **AGENTS.md & Reminder Parameterization (`install_tool_adapters.py`, `AGENTS.md.template`, `pre_invocation_reminder.py`)**: `{{UNIT_TEST}}` auto-derived from `--assemble`; `{{PM_TRIGGER}}`/`{{PM_LANG_NOTE}}` written from I.20/I.18; `.agents/hooks.json` rewritten with the configured python; reminder renders device/git/install policy lines from `_product.py`.
- **Robustness Fixes**: review-package paths with spaces (`PACKAGE_RE` full-line capture); fail-loud when the checkout has no git HEAD (`review_package.py`, `fast_kt_lint.py`, `room_guard.py`); barrier-TTL expiry surfaced via `latest_expired_note()`; screen-relative E2E swipes from `wm size` with WARN (never PASS) when unavailable; deny false positives narrowed (schedule keywords, run-command triggers, adb-context monkey); normalized exit codes (selftest, gradle_error_parser, documented `verify` contract); setup-only content-gated stray cleanup; `--flavor=X` grammar; `bash`→`sh`→direct gradlew fallback; MCP statuses aligned with policy; neutral product name in selftest; legacy `src/` bytecode tree removed; `docs/` upgrade references point at raw prompt URLs.
- **Docs Aligned**: 5-leaf wording everywhere (README, workflows, architecture, SVGs, setup-prompt), single-dispatch review rule, `debug.md` gate order, quickstart DB options, setup-wizard I.22 row, porting guide updated for the new `_product.py` policy fields.

**Included in 0.14.23 (2026-08-31):**

### Shift-Left Fast KT Lint Pre-Gate, Strict Device Verification Halt & Update Reference Preservation
- **Shift-Left Fast Kotlin Lint Pre-Gate (`harness-rules.md`, `AGENTS.md`, `deliver.md`, `pre_invocation_reminder.py`)**: Re-sequenced the delivery pipeline to run `fast_kt_lint.py` alongside `testDebugUnitTest` *before* generating the review package, eliminating review invalidation from post-approval lint fixes (e.g. double-bang `!!` or `TODO` cleanup).
- **Strict Device Verification & No-Device Halt Policy (`harness-rules.md`, `deliver.md`, `pre_invocation_reminder.py`)**: Codified a hard invariant prohibiting the agent from silently skipping device installation (`run_device.py install-start`) or smoke testing (`run_e2e_smoke.py`) when no device/emulator is connected; mandates halting and prompting the developer.
- **Preflight Gate Invariant (`harness-rules.md`, `deliver.md`, `pre_invocation_reminder.py`)**: Enforced that `preflight_check.py` MUST exit with code 0 (`[SUCCESS]`); strictly prohibited proceeding to `:app:assembleDebug` or delivery on `[FAIL]`.
- **Zero-Noise Background Commands Protocol (`harness-rules.md`, `pre_invocation_reminder.py`, `AGENTS.md`)**: Mandated choosing Option A (proceed silently with zero chat text `""`) when launching asynchronous background tasks, strictly forbidding `# Background Task Started` chat spam and relying 100% on IDE tool execution badges.
- **Wizard Previous Answers Recommendation (`wizard/questions.py`, `install-or-update-prompt.md`)**: Upgraded `questions_payload` with `_reorder_with_previous_answers` to automatically pre-fill previous configuration choices from `.harness-setup/answers.json` as the recommended first option (`Index 0`) with `(Recommended) ` / `(موصى به) `.
- **Tailored References Preservation on Update (`docs/setup-prompt.md`, `docs/install-or-update-prompt.md`)**: Mandated that update sessions restore and keep all existing tailored project references (`.agents/skills/android-harness/references/`) AS-IS without injecting generic references, with an interactive confirmation modal (`ask_question`).

---

**Included in 0.14.22 (2026-08-31):**

### Unified Release Automation, High-Signal Zero-Noise UI & Phase Checkpoint Commits
- **One-Command Release Engine (`scripts_dev/release_version.py`)**: Built a fully automated release engine that handles version bumping, cryptographic prompt hashing, docs synchronization, selftest verification, Git tagging, and GitHub Release publication with a single command (`--patch`, `--minor`, `--dry-run`).
- **High-Signal Chat & Zero-Noise UI Governance (`harness-rules.md`, `pre_invocation_reminder.py`, `AGENTS.md`)**: Formalized Section 6 strictly distinguishing collapsible IDE tool badges from permanent chat prose. Codified the Silent Intermediate Review Wait Protocol (`""` empty response during in-flight reviewer wakeups) and prohibited mechanical progress spam in chat.
- **Phase Checkpoint Commits & Mandatory Hard Stop (`harness-rules.md`, `deliver.md`, `AGENTS.md`)**: Enforced phase-by-phase checkpoint commits. When Phase N passes all gates, the Lead Agent outputs the Phase Milestone Card with a drafted commit message and HALTS immediately, awaiting explicit developer commit and instruction before touching Phase N+1 files.
- **Shift-Left Phase Preflight Gate (`harness-rules.md`, `deliver.md`)**: Integrated `preflight_check.py` into every phase boundary before milestone handoff, eliminating commit-time blocking on lint annotations, hardcoded strings, or Room schema issues.
- **Dynamic Conversation Language Parity (`harness-rules.md`, `pre_invocation_reminder.py`, `AGENTS.md`)**: Mandated matching the developer's conversation language (Arabic/English) across all cards (Review Round, Phase Milestone, Final Delivery) and interactive `ask_question` modals.

**Included in 0.14.21 (2026-08-31):**

### Comprehensive Edge Case Hardening Across Harness Engines & Review Gates (0.14.21)
- **Multi-Module & Cross-Feature Import Flexibility (`fast_kt_lint.py`)**: Expanded cross-feature import regex to detect both singular `.feature.` and plural `.features.` package structures.
- **Flavor & Case-Insensitive Linux APK Discovery (`run_gradle_task.py`)**: Upgraded APK search to be case-insensitive across subdirectories, ensuring reliable APK resolution for all product flavors on Linux/macOS filesystems.
- **Multi-Class Room Entity & Embedded Resolution (`room_guard.py`)**: Added class declaration scanning fallback to discover `@Entity` and `@Embedded` types declared in shared model files.
- **ADB Auto-Grant Permissions & Work Profile Support (`run_device.py`)**: Added `-g` flag to auto-grant runtime permissions on debug builds and added `--user` support for multi-user/work profile test devices.
- **Scalable Review Package Cap (`review_package.py`)**: Increased default file cap from 200 to 500 files with configurable `HARNESS_MAX_REVIEW_FILES` for large-scale refactorings.
- **Kotlin Script (.kts) & KSP Compiler Error Parsing (`gradle_error_parser.py`)**: Supported `.kts` build errors and `[ksp]` prefix tags in compiler diagnostics.
- **Custom Launcher Activity Auto-Discovery (`wizard/discovery.py`)**: Enabled detection of launcher activities with custom class names from XML manifests.
- **Universal MVI State Class Immutability Guard (`perf_guard.py`)**: Broadened `@Immutable` / `@Stable` static check to cover all `*State` and `*UiState` models.
- **Native C++ / NDK Crash Forensics (`logcat_doctor.py`)**: Added SIGSEGV and native crash patterns (`Fatal signal`, `DEBUG: ***`) to Logcat triage.
- **Whitespace-Flexible ADB Devices Parsing (`doctor/engine.py`)**: Improved device listing parser to handle spaces flexibly.
- **Staged Quoted Path Decoding (`pre_commit_gate.py`)**: Integrated `_unquote_git_path` for staged files containing spaces or quotes.
- **Kotlin-First Source Directory Scaffolding (`new_feature_scaffold.py`)**: Auto-detects `src/main/kotlin` vs `src/main/java` source roots.
- **Process Stream Cleanup on Windows (`_live_process.py`)**: Guaranteed stdout pipe handle closure upon cancellation.
- **Resource Qualifier Filtering & Formatted Attribute (`check_strings.py`)**: Excluded non-locale qualifiers (`values-night`, `values-sw600dp`) from 100% translation parity and honored `formatted="false"`.
- **Legacy Screencap Fallback (`capture_screen.py`)**: Added fallback screencap via `/data/local/tmp` for older devices.
- **Offline CLI Update Caching (`check_kit_update.py`)**: Cached transient network failures to eliminate command delays when offline.
- **NDK, AIDL & Proguard Review Coverage (`_repo_files.py`, `_hook_state.py`, `pre_commit_gate.py`)**: Expanded code suffixes to include `.cpp`, `.c`, `.h`, `.hpp`, `.aidl`, and `.pro` across review gates.

**Included in 0.14.18, 0.14.17, 0.14.16 & 0.14.15 (2026-08-30):**

### Diff-Aware Targeted E2E Smoke Testing, Base ViewModel Discovery & Architectural KDoc (0.14.18)
- **Diff-Aware Target Auto-Discovery (`agents/scripts/run_e2e_smoke.py`)**: Enhanced autonomous E2E engine with `--auto-diff` inspection, automatically detecting modified Activity components, Fragment/Compose screens, and newly added string resources from git working tree diff.
- **Direct Component & Deep-Link Launching**: Added targeted launch capabilities (`--target-activity`, `--target-deeplink`) enabling direct Activity invocation via ADB component intents (`am start -n`) alongside automated UI Automator navigation.
- **Deep Logcat Crash & ANR Forensics**: Upgraded runtime error interception to capture, extract, and demangle 15-line stack traces for `FATAL EXCEPTION`, `AndroidRuntime`, `ANR`, `Room` schema integrity violations, and unchecked nullability failures.
- **Architectural Base Classes Discovery (`wizard/discovery.py`)**: Built `discover_architectural_bases()` to automatically scan and extract standardized Base ViewModel classes (e.g. `MVIViewModel<S : State, E : Event, A : Action>`, `BaseViewModel`), Domain Result wrappers (`Result<T>`, `Resource<T>`), and Base Activities/Fragments from client repositories.
- **Mandatory Base ViewModel Inheritance Invariant (`harness-rules.md`, `convention-reviewer-agent.json`)**: Added Invariant 9 and Scope Item 10 strictly prohibiting ad-hoc reinvented `_uiState = MutableStateFlow` boilerplate when a standardized Base ViewModel exists in the project.
- **Mandatory Architectural KDoc Invariant (`harness-rules.md`, `architecture-guidelines.md`)**: Added Invariant 8 to Shift-Left Quality Invariants strictly mandating standard, meaningful KDoc (`/** ... */`) documenting purpose, `@param`, `@return`, and `@throws` on all newly created or refactored Repository interfaces, Domain UseCases, ViewModel exposed contracts, and DataSource methods.

### Zero Git Pollution Hardening & Legacy Advisory Elimination (0.14.17)
- **Zero Git Pollution Hardening (`harness_doctor.py`, `doctor/engine.py`, `setup-prompt.md`, `_repo_files.py`)**: Completely removed legacy `chore: setup android harness` git commit advisories from diagnostic reports and setup documentation. All harness manifests (`.agents/`), adapters, and transient states are 100% locally private via `.git/info/exclude`, requiring zero git commits by developers.
- **Temporary Wizard & Scratch File Isolation (`_repo_files.py`)**: Added `*.wizard_questions.json`, `.wizard_questions.json`, `*.tmp`, `*.json.tmp`, and `scratch_*.py` to `HARNESS_LOCAL_EXCLUSIONS`, ensuring temporary question payloads and scripts never appear in Android Studio unversioned files.
- **Reference Indexing Synchronization (`daily-scenarios.md`)**: Fully synchronized foundation and tailored domain reference indexing across all setups and updates, ensuring 100% zero-warning diagnostics across client Android applications.

### Official Slogan, 6-Leaf Review Gate, Workflows Guide & Prompt Consolidation
- **Official Identity & Tagline (0.14.16)**: Adopted official slogan *"Deterministic Android Engineering for the AI Era"* with tagline *"Turn Any AI Assistant into an Uncompromising Senior Android Engineering Team."* across `README.md`, `docs/architecture.md`, `docs/quickstart.md`, and `pyproject.toml`.
- **6-Leaf Review Gate & 8-Specialist Roster (0.14.16)**: Clarified documentation topology to explicitly reflect all 6 parallel Quality Guardians and 2 on-demand specialists.
- **Comprehensive Developer Workflows Playbook (0.14.16)**: Created dedicated engineering playbooks guide covering all 10 core Android development workflows.

### Unified Install & Update Prompt File Consolidation
- **Unified Setup & Upgrade Architecture (`docs/install-or-update-prompt.md`)**: Consolidated installation and update workflows by renaming `docs/install-prompt.md` to `docs/install-or-update-prompt.md` and removing `docs/update-prompt.md`, retaining the original structural port and setup steps while clarifying its dual capability for fresh installations and project upgrades.
- **Synchronized Roster & Documentation Links**: Updated `README.md`, `docs/quickstart.md`, `docs/tool-support.md`, `docs/diagnostic-prompt.md`, `docs/setup-prompt.md`, `docs/sync.md`, `check_kit_update.py`, `pre_invocation_reminder.py`, `harness_cli.py`, and `scripts_dev/pin_prompt_docs.py`.
- **Autonomous Phase Pipeline & Zero-Timer Invariant (0.14.14)**: Enhanced `autonomous_e2e` device verification mode so that upon passing `run_e2e_smoke.py`, the Lead Agent outputs the Phase Milestone Card and proceeds autonomously to Phase N+1 without blocking modals. Strictly banned `schedule`, shell `sleep`, or `manage_task` busy loops.
- **Foundation Reference Indexing (0.14.13)**: Indexed all 7 universal foundation reference guides to guarantee 100% zero-warning diagnostics across all installations and updates.

---

**Included in 0.14.12 (2026-08-30):**

### Universal Generic Architecture References
- **Universal Reference Naming (`agents/skills/android-harness/references/`, `doctor/models.py`)**: Renamed foundation references to universal names to represent general Android development across modern and legacy codebases:
  * `architecture-mvi.md` -> `architecture-guidelines.md` (covers MVI, MVVM, MVP, Clean Architecture, Unidirectional Data Flow, Layer Separation)
  * `ui-compose-theme.md` -> `ui-layout-and-theming.md` (covers Jetpack Compose, XML Views, ViewBinding, Material 3/2 Theming, RTL/Arabic, Previews)
  * `room-database-migrations.md` -> `database-and-persistence.md` (covers Room, SQLite, Migrations, DataStore, EncryptedSharedPreferences)
  * `performance-anr-optimization.md` -> `performance-and-optimization.md` (covers ANR, Threading/Dispatchers, Memory Leaks, Battery, Sensors, Compose Jank)
- **Synchronized Roster & Documentation**: Updated `SKILL.md`, `daily-scenarios.md`, `perf-audit.md`, `perf-anr-guardian-agent.json` (fingerprint `v5`), `setup-prompt.md`, `update-prompt.md`, and `porting.md`.

---

**Included in 0.14.11 (2026-08-30):**

### Shift-Left Test Pre-Gate & Lead Agent Review First-Pass Optimization
- **Mandatory Shift-Left Test & Compilation Pre-Gate (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**: Mandated executing `python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest` before generating review packages whenever Kotlin/Java code or tests are touched, catching constructor/signature mismatches and assertion errors in seconds before subagent dispatch.
- **Expanded Fast Kotlin Linter (`fast_kt_lint.py`)**: Added instant static checks for `TEST_RUNBLOCKING` (`runBlocking` inside `*Test.kt`), `UNIMPLEMENTED_STUB` (`TODO()` or `throw NotImplementedError()`), and `UNCHECKED_DOUBLE_BANG` (`!!` operators in production code).
- **Embedded Pre-Dispatch Quality Checklist (`pre_invocation_reminder.py`)**: Integrated an immediate 4-point verification checklist into agent context prompts to guarantee high first-pass review clearance rates.

---

**Included in 0.14.10 (2026-08-30):**

### Product Module Isolation in Doctor & Lifecycle Cross-Compatibility
- **`_product.py` Dynamic Module Isolation (`doctor/engine.py`)**: Isolated target app configuration loading in `_check_install_consistency` via `importlib.util.spec_from_file_location`, eliminating `sys.path` collision between raw kit templates and installed client checkouts.
- **Discovered Application IDs Exposure (`wizard/discovery.py`)**: Added `application_ids` array to `discover()` facts dictionary, ensuring complete metadata transparency during Greenfield and established project setup.
- **Lifecycle Cross-Compatibility Verification**: Completed and validated exhaustive empirical test matrix across Installation, Update, and Doctor lifecycles with 0 failures.

---

**Included in 0.14.9 (2026-08-30):**

### Automatic Local Git Privacy (.git/info/exclude) & Clean .gitignore Restoration
- **Automated Local Exclusion Architecture (`_repo_files.py`, `ensure_local_git_privacy`)**: Centralized local Git exclusion management via `ensure_local_git_privacy()`, ensuring all 27 harness directories, manifests, and transient patterns are automatically registered in `.git/info/exclude` across setup, update, preflight, and doctor runs.
- **Zero Shared `.gitignore` Pollution (`wizard/questions.py`, `doctor/engine.py`)**: Automatically removes all harness-related lines from the shared `.gitignore` file, keeping client repositories 100% clean with zero Git diff in Android Studio commit windows.
- **Automatic Scratch Script Pruning**: Automatically detects and purges stray helper scripts (`fix_product.py`, `script_step3b*.py`, `update_worker.py`) to prevent untracked file clutter in Android Studio.

---

**Included in 0.14.8 (2026-08-30):**

### Mandatory Autonomous E2E Enforcement, Silent Review Wait & run_device Bugfix
- **`run_device.py` APK Resolution Fix (`agents/scripts/run_device.py`)**: Fixed `TypeError` bug caused by redundant `apk = Path(args.apk)` assignment when running without explicit `--apk`, ensuring zero-argument `python .agents/scripts/run_device.py install-start` runs flawlessly.
- **Mandatory Autonomous E2E Execution (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**: Removed "optional" qualifier from Phase verification rules; strictly mandated `python .agents/scripts/run_e2e_smoke.py` execution immediately following APK installation when `DEVICE_VERIFICATION_MODE` is `autonomous_e2e`.
- **Silent Intermediate Review Wait Protocol (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**: Explicitly prohibited conversational countdown spam on intermediate subagent wakeups, requiring the Lead Agent to remain 100% silent and present the consolidated review table only after all verdicts arrive in context.

---

**Included in 0.14.7 (2026-08-30):**

### Hierarchy-Aware Gitignore Deduplication, CLI Ergonomics & Windows UTF-8 Resilience
- **Hierarchy-Aware `.gitignore` Deduplication (`wizard/questions.py`)**: Completely eliminated redundant subfolder entries (`.agents/state/`, `.agents/cache/`, `.agents/__pycache__/`) when parent `.agents/` is ignored, and automatically prunes legacy redundant entries from existing repositories to eliminate Git diff noise.
- **Windows Console Unicode Resilience (`_live_process.py`, `harness_cli.py`, `setup_wizard.py`)**: Reconfigured standard I/O to UTF-8 with replacement across CLI entrypoints, preventing `UnicodeEncodeError` crashes on Windows consoles with Arabic text and special symbols.
- **CLI Argument Ergonomics (`install_zoho_mcp.py`, `install_tool_adapters.py`)**: Allowed `install_zoho_mcp.py` to default `--repo` to current working directory (`Path.cwd()`), and made `--git-gate` parsing resilient to explicit `yes`/`no`/`true`/`false` values.

---

**Included in 0.14.6 (2026-08-30):**

### Autonomous E2E Smoke Testing Engine & Wizard Setup Integration
- **Autonomous E2E Smoke Testing Engine (`agents/scripts/run_e2e_smoke.py`)**: Built a zero-dependency (Python stdlib + native ADB) autonomous UI testing engine that inspects device UI hierarchy, asserts component visibility and scroll responsiveness across Compose & XML Views, catches runtime Logcat crashes, and captures timestamped verification screenshots.
- **Physical Device First & High-Precision Gestures**: Fully compatible with real physical Android devices (and emulators) across Android 5.0 through Android 15 with strict safety containment (aborts immediately if foreground package leaves target app).
- **Setup Wizard Question `I.22` (`wizard/questions.py`, `wizard/i18n.py`)**: Added user-selectable Device Verification Mode during project initialization (`autonomous_e2e` recommended default vs `manual_only`).
- **Doctor Diagnostic Engine Updates (`doctor/engine.py`, `doctor/models.py`)**: Expanded core script inventory to 35 audited scripts and added Dimension 4 device verification mode reporting.

---

**Included in 0.14.5 (2026-08-30):**

### Interactive Device Verification & Chat UX Signal Maximization
- **Explicit Manual Device Smoke Testing Steps (`harness-rules.md`, `AGENTS.md`)**: Mandated that upon completing APK installation on the connected physical device, the Lead Agent must provide explicit, numbered verification steps in the Phase Milestone Card detailing exact screens to open, interactions to perform, and expected behaviors to verify.
- **Interactive Phase Sign-Off Modal (`ask_question`)**: Required the Lead Agent to prompt the developer via an interactive choice modal (`(Recommended) PASS` / `FAIL`) to confirm device verification before unlocking Phase N+1.
- **Chat Noise Elimination**: Strictly prohibited mechanical progress messages ("running tests...", "waiting for subagents...", "installing apk...") ensuring completely silent execution during background tool runs.

---

**Included in 0.14.4 (2026-08-30):**

### Repository Alignment, Security Hardening & Managed Block Preservation
- **Repository Naming Alignment**: Completely unified repository identity to `android-agent-harness` across Git remotes, PyPI packaging, CLI endpoints, and documentation.
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
- **Zero-Dependency CLI Dispatcher (`harness_cli.py`, `pyproject.toml`)**: Introduced the standalone `android-harness` command-line executable (`pipx install git+https://github.com/rabee-elkholy/android-agent-harness.git`, or run in place via `python harness_cli.py`). Features 6 core subcommands (`init`, `update`, `doctor`, `preflight`, `selftest`, `version`), automatic engine discovery, and remote fallback kit provisioning.
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
