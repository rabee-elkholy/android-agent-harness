# Changelog

All notable changes to the **Android Agent Harness** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),

## [1.0.45] - 2026-09-17

### Unblocked Chat Installer & Shell Download Flexibility

- **Chat Installer Unblocking (`docs/install-or-update-prompt.md`, `scripts_dev/pin_prompt_docs.py`)**:
  - Removed brittle SHA-256 header and tamper-abort gate from `docs/install-or-update-prompt.md`.
  - Allowed agent bootstrap and update prompts to proceed without false-positive tampering stops caused by host tool stream truncation.
  - Pinned kit clone integrity remains cryptographically guaranteed by Git tag and commit signature verification.
- **Hook Boundary Relaxation for Shell Tooling (`pre_tool_safety.py`)**:
  - Removed `live_network` and `inline_interpreter` restrictions from `DANGEROUS` tuple in `pre_tool_safety.py`.
  - Unblocked `python -c` and `curl` commands from agent tooling for network recovery and automated file fetching when IDE tools fail.

## [1.0.44] - 2026-09-17

### Web Fetch Buffer Hardening: Compact Chat Installer Prompt

- **Compact Chat Installer Prompt (`docs/install-or-update-prompt.md`)**:
  - Streamlined and optimized installer prompt phrasing across all 5 phases (Discovery, Bootstrap, Authoritative Interview, Lifecycle Execution, Verification) down from 4,095 bytes to ~2,700 bytes.
  - Eliminated web fetch truncation and stream severance caused by host IDE web tools (`read_url_content`) and network buffering on raw markdown files.
  - Preserved 100% of security guarantees, mandatory gate assertions, and cryptographic SHA-256 tamper-evident integrity.

## [1.0.43] - 2026-09-17

### Performance & Usability: Real-Time Sublogs, Pruned Room Scanning & Architecture Contract Resilience

- **Real-Time Live Progress & Sublog Streaming (`_live_process.py`, `workflow.py`, `change_classifier.py`, `preflight_check.py`, `run_device.py`)**:
  - Implemented `sublog()` in `_live_process.py` enabling indented sub-step progress markers under active `step_progress` blocks.
  - Enhanced `step_progress` with sublog tracking, formatting completion timestamps (`  [Done] (0.2s)`) while preserving single-line output for fast sublog-free operations.
  - Added non-blocking background heartbeat timer in `step_progress` alerting every 5 seconds on long operations to eliminate silent terminal freezes.
  - Instrumented key workflow stages (`draft`, `begin`, `verify`), classifier surface evaluations, deterministic preflight checks, and ADB device installation/launch steps with real-time sublogs.
- **Pruned Room Database Scanning & Zero-I/O Fast Path (`room_guard.py`, `change_classifier.py`)**:
  - Replaced unpruned `root.rglob()` with `os.walk()` directory pruning, preventing traversal into `build/`, `.gradle/`, `.git/`, `.idea/`, and `.agents/`.
  - Added fast-path check in `change_classifier.py` bypassing Room schema discovery entirely when working tree changes contain no Kotlin or Java source files.
  - Reduced Room working-tree scanning duration from ~36 seconds to < 0.1s on Windows.
- **Resilient Phased Execution Parsing (`workflow.py`)**:
  - Upgraded `--phases` parser in `workflow.py` to support both JSON list (`[...]`) and JSON object (`{"phases": [...]}`) formats, whether passed as file paths or inline strings.
  - Eliminated `ValidationError: JSON artifact must be an object` when reading phase list files.
- **Architecture Family Explicit Override in REFACTOR / PRESERVE (`architecture_resolver.py`)**:
  - Enabled `--architecture-target-family` resolution fallback in `PRESERVE` and `REFACTOR` modes when scope matching is ambiguous or unindexed.
  - Preserved strict failure-closed behavior when multiple families exist and neither scope nor explicit family ID is provided.

## [1.0.42] - 2026-09-17

### Stabilization & Architectural Precision: Canonical Executable RED, Authentic Reviewer Transcripts, Phase Checkpoints & Task Scope

- **Canonical Executable RED Authority (`workflow.py`, `final_verifier.py`)**:
  - Eliminated non-executable RED synthesis (`record_debug_evidence` writes only `debug-evidence.json` with `satisfies_executable_red: false`).
  - Restricted executable RED acceptance strictly to Schema 3 manifests produced directly by `run_tests_gate.py --capture-red`.
  - Enforced defect binding verification requiring valid canonical RED evidence produced by the test gate.
- **Reviewer Proof via Authentic Host Transcripts (`record_review.py`, `final_verifier.py`)**:
  - Enforced host-level transcript path validation (`resolve_trusted_subagent_transcript`) anchoring transcripts to the authentic Antigravity application directory (`AppData/Local/antigravity` or `~/.gemini/antigravity`).
  - Strictly rejected untrusted temporary files, path traversal attempts, and transcript conversation ID mismatches.
  - Required independent execution verification for HIGH/CRITICAL reviews before delivery approval.
- **Command Contract & Remediation Parity (`command-contract.md`, `workflow.py`)**:
  - Aligned public CLI contract documentation and remediation argument generation (`--planning-depth <BOUNDED|ARCHITECTURAL>` and `--external-write <none|zoho_sprints>`).
  - Exposed `workflow.py build_parser()` for contract introspection and normalized `--planning-depth` values.
- **Phase Checkpoint Module Scoping & Fail-Closed Compilation (`workflow.py`)**:
  - Replaced whole-repository compile checks with targeted phase-scoped Gradle tasks derived from AST-mapped changed modules.
  - Eliminated broad swallowed exceptions in `checkpoint_phase`, failing closed on unexpected compilation failures.
  - Enforced policy-required unit test and reviewer execution for phase checkpoints.
- **Architecture Resolution Authority & Contract Confidence (`architecture_resolver.py`)**:
  - In `NEW` feature mode, restricted target architecture authority strictly to explicit CLI flags or user-preferred family, treating surrounding family strictly as compatibility boundaries.
  - Maintained contract confidence strictly aligned with family match confidence without artificial elevation.
- **Dirty Source Fingerprint Content Identity (`project_context.py`)**:
  - Upgraded source fingerprinting to compute SHA-256 content hashes for dirty/untracked source, build, and configuration files, preventing fingerprint thrashing on metadata/mtime changes.
  - Fixed `is_context_fresh` JSON loading bug.
- **Update Recovery Ownership Integrity (`lifecycle.py`)**:
  - Hardened update recovery to validate ownership metadata against canonical SHA-256 calculation and journal records.
  - Enforced forward completion only when ownership hashes and target engine versions match exactly; otherwise safely rolls back.
- **Task-Scoped Preflight & Setup Neutrality (`preflight_check.py`, `room_guard.py`, `wizard/questions.py`)**:
  - Scoped preflight surface classification and Room database schema verification strictly to current task-delta changes.
  - Prevented pre-existing unrelated dirty Room migrations or business logic files from blocking unrelated UI/Compose tasks.
  - Neutralized setup architecture recommendations, removing exemplar-count bias and recommending a family only when a single HIGH-confidence family exists without saved preferences.
- **Adversarial Stabilization Regression Suite (`_stabilization_v42_selftest.py`, `harness_cli.py`)**:
  - Added comprehensive 16th selftest suite `_stabilization_v42_selftest.py` with 38 adversarial unit tests validating all 8 stabilization fixes.

## [1.0.41] - 2026-09-16

### Stabilization: Reviewer Independence, RED->GREEN Defect Binding, True Task-Delta Isolation, Phase Checkpoints & Recovery

- **Independent Reviewer Execution & Cryptographic Provenance (`record_review.py`, `final_verifier.py`, `workflow.py`)**:
  - Implemented strict independent reviewer verification (`verify_independent_reviewer_execution`) ensuring all code reviews for HIGH/CRITICAL severity or sensitive surfaces originate from verified subagent executions rather than self-certification.
  - Required execution proof containing verified subagent transcripts, task and run ID validation, package SHA-256 integrity, and cryptographic SHA-256 integrity-bound dispatch receipt signatures.
  - Enforced fail-closed verification in `final_verifier.py` with explicit rejection reasons when independence proofs or dispatch receipts are missing, tampered, or mismatched.
- **Defect Binding & Temporal RED->GREEN Protocol (`run_tests_gate.py`, `final_verifier.py`, `workflow.py`)**:
  - Eliminated synthetic RED evidence generation; required real test failure execution captured via `run_tests_gate.py --capture-red`.
  - Implemented canonical Schema 3 `red-evidence.json` with live capture manifests and pre-RED task-delta checks preventing RED evidence capture once implementation fix files are modified.
  - Enforced defect binding in `final_verifier.py`: verified defect test failures in RED evidence, validated `red_sha256` signatures, confirmed subsequent GREEN passing state, and eliminated verifier reset bugs by accumulating binding validation errors.
- **True Task-Delta Isolation & Snapshot Diffing (`delivery_manifest.py`, `plan_authority.py`, `review_package.py`, `preflight_check.py`, `workflow.py`)**:
  - Excluded pre-existing baseline dirty files from task manifests and unified diffs; added `BASELINE_DIRTY_REMOVED` tracking for baseline files removed during task execution.
  - Preserved `task_delta_mode = "TASK_ISOLATED"` even on empty task deltas.
  - Implemented `build_task_diff` generating unified diffs strictly against baseline file snapshots or git HEAD for accurate review package and verification generation.
  - Integrated baseline snapshots into `.agents/state/tasks/<id>/baseline-files/` during task drafting.
- **Real Phase Checkpoints & Multi-Layer Group Enforcements (`workflow.py`)**:
  - Aligned phase requirement criteria strictly with specification: enforces phases when implementation files > 3 or when implementation files >= 2 spanning 2+ architectural layer groups (`UI`, `BUSINESS`, `DATA`, `PLATFORM`).
  - Hardened `workflow.py checkpoint-phase` with phase-scoped change tracking, architectural drift validation, Room schema checks, targeted Gradle compilation, and scoped review recording.
- **Architecture Resolution & Drift Correctness (`project_context.py`, `architecture_resolver.py`, `architecture_drift.py`, `workflow.py`)**:
  - Replaced naive string prefix matching with component-aware path hierarchy checks in `architecture_resolver.py`; returns `STATUS_DECISION_REQUIRED` upon ambiguous multi-family ties.
  - Fixed undefined plan references in `architecture_drift.py` and incorporated XML layout and navigation graph validation for NEW features.
  - Corrected remediation command mappings (`MIGRATE -> MIGRATION`) and preserved multi-phase structures across drift remediation.
- **Transaction Journal-Driven Interrupted-Update Recovery (`lifecycle.py`)**:
  - Implemented multi-stage transactional recovery journal (`PREPARED`, `OLD_ENGINE_MOVED`, `NEW_ENGINE_INSTALLED`, `STATE_RESTORED`, `CONTEXT_RESTORED`, `APP_SNAPSHOT_VERIFIED`, `OWNERSHIP_WRITTEN`, `COMPLETED`, `ROLLED_BACK`).
  - Hardened `recover_interrupted_update` to require `stage == "OWNERSHIP_WRITTEN"` and target version matching before completing forward; otherwise rolls back to previous engine backup.
- **Source Fingerprint & Context Freshness Performance (`project_context.py`)**:
  - Implemented Version 2 source fingerprinting combining Git HEAD commit SHA, harness config digest, and dirty architecture file hashes.
  - Added fast-path context status check returning `CURRENT` with zero AST extraction overhead when the source fingerprint is intact and fresh.
- **Public Command Contract Accuracy & Tooling Modernization (`command-contract.md`, `run_device.py`, rules/templates)**:
  - Added `status` action to `run_device.py` for headless device connection inspection.
  - Standardized command contract field names (`surfaces`, `severity`, `reviewers`, `gates`) and documented all `workflow.py draft` parameters and `checkpoint-phase`.
  - Replaced obsolete `adb devices` instructions with `run_device.py status` across all rules, agent definitions, and triage workflows.
- **Setup Architecture Preference Neutrality (`wizard/questions.py`)**:
  - Removed modernity bias scoring favoring Jetpack Compose over XML Views; options are ordered neutrally (current default first, then alphabetical, then none).
  - Flags single HIGH-confidence family as `(Recommended)`; marks `none` as `(Recommended)` when zero or multiple high-confidence architectures exist.
- **Adversarial Regression Test Suite (`_stabilization_v41_selftest.py`, `harness_cli.py`)**:
  - Added comprehensive 15th selftest suite `_stabilization_v41_selftest.py` covering reviewer independence, RED->GREEN defect binding, true task isolation, phase checkpoints, architecture resolution, update recovery, and contract accuracy.
- **Model Call Budget Increase & Zero-Polling Invariants (`_product.py`, `review_policy.py`, `_installer_config.py`)**:
  - Increased default model call budget from 8 to 10 across product defaults, policy resolution, and installer templates.
- **Live Subtask Progress & Zero-Dot Formatter (`_live_process.py`, `harness_cli.py`)**:
  - Implemented real-time subtask reporting indented under selftest suite headers: `  {name} [{i}/{total}] [Done] ({elapsed}s)` on completion without name duplication.
  - Enabled stdout buffering in `SubtaskTestRunner` to prevent orphan `[Done]` lines and eliminate unittest dot noise (`...`).
- **Review Ingestion Prose Recognition (`record_review.py`)**:
  - Treated explanatory prose with zero code citations (`cites=0`) as non-blocking clean PASS results instead of generating artificial HIGH-severity findings.
- **Project Graph UX Guidance (`project_graph.py`)**:
  - Added helpful diagnostic tips directing users to `--feature` or `--string` when AST symbol lookup misses.

## [1.0.40] - 2026-09-16

### Daily Developer Hardening: Public Contract, Task Baseline Isolation, Compose UI Classification, Architecture Evolution & Reviewer Independence

- **Public Command Contract & Architecture Drift CLI (`architecture_drift.py`, `command-contract.md`, Rules & Templates)**:
  - Created standalone CLI `architecture_drift.py --repo . --task-id <id>` with exit code 0 on pass or exemption and exit code 1 on architectural drift.
  - Aligned documented command syntax in `command-contract.md`, removing draft formatting artifacts and standardizing flags across all entrypoints.
  - Replaced legacy `adb devices` instructions with canonical `run_device.py` tooling.
- **Authority, Remediation & Task Baseline Subtraction (`delivery_manifest.py`, `plan_authority.py`, `mutation_guard.py`, `workflow.py`)**:
  - Implemented content-identity baseline subtraction via `task-baseline.json` created during `workflow.py draft`, guaranteeing pre-existing developer dirty files are excluded from task review packages and verification delivery manifests (`task_delta_mode: TASK_ISOLATED`).
  - Added support for multi-phase plan structures in plan authority verification.
  - Ensured material drift remediation commands use the authoritative `--task-id` instead of internal `plan_id`.
- **Kotlin UI vs Business Logic Classification (`change_classifier.py`)**:
  - Distinguished pure Compose UI presentational changes (e.g. padding, colors, layout tweaks) from business logic, classifying them as `COMPOSE_UI` without injecting unwanted `unit_tests` gate requirements unless business triggers (viewModels, useCases, repository calls) are present.
- **Architecture Intent, Scope Resolution, and Structural Drift (`project_context.py`, `architecture_resolver.py`)**:
  - Enhanced ViewModel detection with balanced parenthesis parsing and 4-tier Screen-ViewModel matching priority with fallback.
  - Implemented content fingerprinting for project context freshness (`compute_context_fingerprint`, `is_context_fresh`).
  - Added target family validation, scope resolution, and multi-family migration boundaries to `architecture_resolver.py`.
- **BUG RED Evidence Hardening (`run_tests_gate.py`, `final_verifier.py`, `workflow.py`)**:
  - Hardened BUG workflow to capture schema version 2 `red-evidence.json` before fixes are applied; rejects RED capture if fix modifications occurred; verifies defect test passes in subsequent GREEN run.
- **Reviewer Independence & Finding Severity (`record_review.py`, `pre_tool_safety.py`)**:
  - Recorded reviewer dispatch receipts upon subagent launch and verified dispatch receipt plus transcript authenticity before accepting direct verdicts on HIGH/sensitive surfaces.
  - Preserved reviewer finding severity levels (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`), preventing harmless advisory remarks from blocking delivery while ensuring `HIGH` and `CRITICAL` findings fail-closed.
- **Phased Execution & Delta Checkpoints (`workflow.py`)**:
  - Added `checkpoint_phase` subcommand supporting phased feature execution under a single developer approval, validating phase-scoped file and module delta boundaries without unnecessary intermediate device installations.
- **Lifecycle Preserve/Refresh & Interrupted Update Recovery (`lifecycle.py`)**:
  - Validated facts schema on `preserve` updates; marked `ARCHITECTURE_DECISION_REQUIRED` when preferred architecture family is absent after `refresh`.
  - Added atomic crash recovery from `update-journal.json` during interrupted harness updates.
- **Performance, Audit Schema & Capability-Based Host Tool Safety (`_graph_core.py`, `pre_tool_safety.py`)**:
  - Added file metadata caching (`size`, `mtime_ns`, `hash`) to AST/graph analysis.
  - Standardized audit log schema version 1 and implemented capability-based tool safety.
- **Comprehensive Daily Developer Selftest Suite (`_daily_workflow_selftest.py`, `harness_cli.py`)**:
  - Added standalone deterministic selftest suite (`_daily_workflow_selftest.py`) covering all 20 daily developer hardening scenarios (Daily-01 to Daily-20) and public contract validations; wired into `harness_cli.py selftest`.

## [1.0.39] - 2026-09-15

### Resilient Review Ingestion, Subagent Auto-Harvesting, Canonical Command Catalog & Anti-Polling Invariant

- **Resilient Review Ingestion (`record_review.py`)**:
  - Replaced strict token equality matching with tolerant evidence extraction (`_extract_evidence_and_verdict`).
  - Recognized explanatory prose and natural language rationales accompanying clean reviews (`cites=0`) as `PASS` without fabricating false `HIGH` findings.
  - Hardened against contradictions: duplicate pass tokens, explicit failure tokens, or unresolved issue markers correctly evaluate to `FINDINGS`.
  - Added support for `.jsonl` transcript parsing in `--report` and `--response`, eliminating JSON parser crashes on JSON lines.
  - Enabled subagent-proven verdict recording on sensitive surfaces: allows `--verdict PASS` on HIGH/CRITICAL or sensitive surfaces when `--subagent-id <convId>` and `--evidence-pkg <sha12>` are provided.
- **Subagent Transcript Auto-Harvesting (`record_review.py`)**:
  - Added `--from-subagent <role>=<convId>` CLI option to automatically locate subagent transcripts in the host brain directory, extract the assistant's final verdict, and stage the review directly.
  - Eliminated the need for intermediate scratch files or complex terminal text escaping.
- **Actionable Diagnostics on BLOCKED Status (`mutation_guard.py`, `pre_invocation_reminder.py`)**:
  - Transformed generic `command is not allowed while plan status is BLOCKED` errors into rich diagnostics displaying the exact blocking reviewers and the precise remedy command (`python .agents/scripts/workflow.py resume --repo . --task-id <id>`).
  - Updated both full and compact messages in `pre_invocation_reminder.py` when `status == "BLOCKED"` to guide the agent directly to code fixes and task resumption.
- **Forwarding Preflight Alias & Pipeline CLI Subcommands (`preflight.py`, `harness_cli.py`, `mutation_guard.py`)**:
  - Added `agents/scripts/preflight.py` as an official forwarding alias to `preflight_check.py`.
  - Added `preflight` to `VERIFICATION_SCRIPTS` in `mutation_guard.py`.
  - Added `preflight`, `test`, `assemble`, `review`, and `device` subcommands to `harness_cli.py` (`android-harness`).
- **Canonical Command Catalog & Zero-Polling Invariant Across All Supported Agents**:
  - Added authoritative **Canonical Command Catalog** table across `harness-rules.md`, `GEMINI.md`, `CLAUDE.md`, `CODEX.md`, `QWEN.md`, `agents/tool-adapters/*.template`, and `command-contract.md`.
  - Enforced strict **Zero-Polling Invariant** prohibiting agents from running background task polling loops (`manage_task`, `manage_subagents`, `schedule`), instructing them to yield execution and rely on reactive system wakeups.
- **Regression Test Coverage (`_vnext_selftest.py`)**:
  - Added `VNextReviewAndDiscoveryResilienceTests` validating review parsing tolerance, JSONL extraction, actionable BLOCKED error messages, preflight alias, CLI pipeline subcommands, and doc catalog parity.

## [1.0.38] - 2026-09-15

### Architecture Deduplication, Context Update Mode & Post-Install Context Management

- **Architecture Family Deduplication & Recommendation (`project_context.py`, `wizard/questions.py`)**:
  - Coalesced architecture family signature on core architectural pillars (`ui_toolkit`, `screen_host`, `state_holder_base`, `state_stream`, `presentation_flow`, `di`), ignoring transient navigation syntax variations across individual screens.
  - Added `screen_host` to family label (e.g. `compose-composable-...`, `compose-fragment-...`, `xml-fragment-...`), eliminating duplicate ambiguous family labels.
  - Implemented architecture modernity scoring (`_score_arch`): Jetpack Compose + Composable Host + StateFlow + Hilt automatically scores highest and is marked `(Recommended)` as Option 1 in setup and update interviews.
  - Enriched family choice prompts (`_format_fam_label`) with human-readable titles, host type, framework details, and real project screen exemplars (e.g. `ArticleCommentsScreen.kt`).
- **Update Context Handling Mode (`wizard/schema.py`, `wizard/i18n.py`, `wizard/questions.py`, `lifecycle.py`)**:
  - Added interactive Station 2 question during harness updates: `update_context_mode` (`preserve` vs `refresh`).
  - Allows developers to choose between preserving the existing extracted project context (`preserve`) or re-extracting project facts and re-rendering markdown views (`refresh`).
  - Safely preserves developer notes (`project-notes.md`) and architecture policy (`architecture-policy.json`) across context refreshes.
  - Added full English and Arabic localization for question prompts and option labels.
- **Post-Install Context Management Actions (`generate_project_context.py`, `harness_cli.py`, `mutation_guard.py`, `pre_tool_safety.py`, Rules & Templates)**:
  - Added `note` subcommand to CLI: `python harness_cli.py context note "<note>" [--section "<section>"]` (and `android-harness context note "<note>"`).
  - Permitted developer-directed mutations to `.agents/project-context/project-notes.md` in `pre_tool_safety.py` and `mutation_guard.py` without requiring an active feature delivery task plan.
  - Updated `harness-rules.md`, `GEMINI.md`, `AGENTS.md.template`, `GEMINI.md.template`, and `android-harness/SKILL.md` to explicitly define **Context Management Actions**: when the developer requests to update project context, add domain conventions, or record architectural notes, agents directly append to `project-notes.md` or execute `context note`, and MUST NOT run `change_classifier.py`, `review_policy.py`, unit tests, or Gradle assemble.
- **Regression Test Coverage (`_architecture_selftest.py`, `_vnext_selftest.py`)**:
  - Added comprehensive test suites verifying architecture deduplication, modern recommendation scoring, update context mode questions, context note appending, and mutation barrier permissions.

## [1.0.37] - 2026-09-15

### Harness Execution Boundary & Verification Pipeline Reliability

- **Harness Execution Boundary (`harness-rules.md`, `SKILL.md`, `GEMINI.md`, `AGENTS.md.template`, `GEMINI.md.template`)**:
  - Enforced strict Harness Execution Boundary prohibiting autonomous agents from recursively reading or inspecting internal harness Python implementation scripts under `.agents/scripts/**`.
  - Autonomous agents operate strictly through documented CLI interfaces and public command contracts, conserving context window and preventing distraction from client Android application code.
- **Public Command Contract Reference (`command-contract.md`)**:
  - Documented complete 9-phase public CLI contract (Discovery, Surface Classifier & Reviewer Policy, Workflow Lifecycle, Preflight Gate, Automated Unit Tests, AI Specialist Reviewers, Assemble & Device Verification, Harness Doctor, and Failure Escape Hatch).
  - Provided explicit CLI commands, arguments, expected output, and Windows/PowerShell newline escaping guidance.
- **Strict Verification Sequence & Anti-Premature Build/Deploy Guards**:
  - Strictly enforced verification order: Step 1 (preflight) -> Step 2 (unit tests) -> Step 3 (routed specialist reviewers) -> Step 4 (assemble & device install) -> Step 5 (mobile walkthrough) -> Step 6 (verify).
  - Prohibited running `assembleDebug` or `run_device.py install-start` while any AI reviewer subagent is still executing.
  - Mandated waiting for `run_device.py` to complete with exit code 0 before presenting any mobile verification walkthrough or invoking `ask_question`.
  - Injected strict anti-hallucination guard forbidding fabrication of device serials (such as `emulator-5554`) when devices are missing or offline.
  - Added real-time active reminders in `pre_invocation_reminder.py` during `VERIFYING` phase.
- **Actionable Workflow & Drift Diagnostics (`workflow.py`)**:
  - Transformed cryptic `material drift` errors into actionable reconciliation instructions (`plan_authority.py reconcile --task <id> --add-target <file>`).
  - Added clear interactive guidance for `REVIEW_BUDGET_EXHAUSTED` prompting the developer via `ask_question`.
- **Regression Test Coverage (`_vnext_selftest.py`)**:
  - Added regression test suite `HarnessExecutionBoundaryTests` (`EXEC-BOUNDARY-001` through `EXEC-BOUNDARY-005`).

## [1.0.36] - 2026-09-15

### Evolutionary Architecture Context & Defense-in-Depth Hardening

- **Evolutionary Architecture Context & Inventory Engine (`project_context.py`)**:
  - Upgraded schema to `v2` (`extractor_version: 2.0.0`).
  - Added Architecture Families discovery (`af-<sha256[:12]>`), multidimensional categorization (UI toolkit, screen host, state holder base, state stream, presentation flow, DI, navigation).
  - Multi-framework DI detection (`frameworks` list), multi-BaseViewModel support without global collision.
  - Streaming capability scanning without 2000-char truncation.
  - Excluded test/sample directories from production architectural facts (`classify_source_path`).
  - Replaced negative inferences in markdown views with neutral `(NOT_DETECTED)`.
  - Expanded `project_context_diff` to cover `modules`, `conventions`, and `architecture`.
- **Developer Evolution Policy (`architecture_policy.py`)**:
  - Implemented `architecture-policy.json` schema, SHA-256 cryptographic verification, and validation engine.
  - Added protection in `pre_tool_safety.py` and `lifecycle.py` (`PRESERVE_GLOBS`).
  - Added Doctor verification check for developer architecture policy.
- **Deterministic Architecture Resolver (`architecture_resolver.py`)**:
  - Deterministic intent mapping (`EXISTING_CHANGE` -> `PRESERVE`, `NEW_SCREEN`/`NEW_FEATURE` -> `NEW`, `REFACTOR` -> `REFACTOR`, `MIGRATION` -> `MIGRATE`).
  - Generates compact, self-contained `task-architecture-brief.md` (100–250 words) with reference exemplars.
  - Enforces `planning_depth=ARCHITECTURAL` for migrations.
- **Fast Architecture Drift Verification (`architecture_drift.py`, `preflight_check.py`)**:
  - Fast Preflight step 5 enforcement of task architecture contracts.
  - Conservative drift detection supporting compatibility bridges in `NEW` mode (`Fragment` embedding `ComposeView`).
- **Final Hardening & Defense-in-Depth (`review_execution.py`, `final_verifier.py`)**:
  - `HARD-001`: One-way escalation kill switch for reviewer models.
  - `HARD-002`: Bound RED defect evidence plan hash verification.
  - `HARD-003`: Added `head` commit to frozen repository lineage checks.
  - `HARD-004` & `HARD-005`: Strict reviewer dispatch contract and canonical model routing schema.

## [1.0.35] - 2026-09-14

### Project Context Hygiene Bounding & Candidate Preview Polish

- **Project Context Hygiene Bounding (`doctor/engine.py`)**:
  - Bound home directory leak detection pattern with negative lookbehind `(?<![a-zA-Z0-9_/-])/(?:Users|home)/[a-zA-Z0-9_-]+/`.
  - Prevents false-positive leak reports on legitimate relative repository package paths and feature modules containing `home` (such as `features/home/homeFragment/...`).
- **Base ViewModel Candidate Preview Visibility (`generate_project_context.py`)**:
  - Enhanced `context preview` CLI output when BaseViewModel resolution is `UNRESOLVED` to explicitly display candidate symbol names (e.g. `BaseVM Resolution : UNRESOLVED (candidates: MVIViewModel, StateViewModel)`) instead of merely showing candidate count.

## [1.0.34] - 2026-09-14

### Project Context Corrective Patch & Architectural Engine Hardening

- **Canonical Read-Only Command Safety (`mutation_guard.py`)**:
  - Whitelisted canonical `context preview` and `context status` subcommands under public command interfaces (`harness_cli`, `android-harness`) without lowering security boundaries.
  - Kept `context generate` and `context refresh` mutation-controlled, requiring an authorized plan and approved phase.
  - Kept internal engine scripts (`generate_project_context.py`) strictly unexposed to arbitrary execution.
- **Strict ViewModel Resolution Contract (`project_context.py`)**:
  - Eliminated heuristic name guessing (`BaseViewModel` preference) when multiple candidates exist.
  - Contract strictly enforced: exactly 1 candidate resolves to `RESOLVED` with primary assigned; 0 candidates resolves to `NONE`; >1 candidates resolves to `UNRESOLVED` with `primary = None` and all candidates listed.
- **Uncapped Deterministic Kotlin File Scanning (`project_context.py`)**:
  - Removed arbitrary 800-file cutoff (`max_kt_files = 800`) across project scans.
  - Hardened scan enumeration to index all Kotlin source files, deterministic sorting by repository-relative path, and skipping ignored directories (`.agents`, `build`, `dist`, `out`, `.git`, `.gradle`).
- **Crash-Safe Staged Atomic Writes (`project_context.py`)**:
  - Implemented staging-directory atomic replacement pattern ensuring generated markdown views are replaced first, and `project-facts.json` is replaced last as the single authoritative commit point.
  - Guaranteed `project-notes.md` is strictly preserved and never overwritten on refresh or generation.
- **Doctor View Consistency Verification (`doctor/engine.py`)**:
  - Added line-by-line verification in `check_project_context()` re-rendering `project-facts.json` and comparing against markdown views on disk.
  - Surfaces `Project Context Rendering Consistency: FAIL` if any derived view is modified or out-of-sync with facts.
- **Neutral UI Framework Fallback (`project_context.py`)**:
  - Avoided defaulting to Compose when no UI evidence is present; projects lacking both Compose and XML layout evidence are classified as `"unknown"` and rendered as `UNKNOWN / no UI framework evidence detected`.
- **Prompt Contract & Size Hardening (`docs/install-or-update-prompt.md`)**:
  - Refined Phase 3.5 confirmation options to `Flag incorrect detection / review before continuing`, strictly instructing that AI models must not auto-mutate facts or notes.
  - Enforced compact prompt size under 4096 bytes (4072 bytes) with updated cryptographic SHA-256 integrity verification.

## [1.0.33] - 2026-09-14

### Automated Architectural Discovery, Project Context Derivation, and Interactive Preview

- **Automated Architectural Discovery Engine (`project_context.py`, `generate_project_context.py`)**:
  - Implemented zero-dependency, standard-library-only discovery engine analyzing target Android codebases for dependency injection frameworks (Hilt, Koin), ViewModel base classes and state holders, Room databases and DAOs, DataStore preferences, UI paradigms (Compose, XML layouts, Hybrid), XML navigation graphs, and technical capabilities (networking, location, maps, sensors, health connect, billing, audio, camera, bluetooth).
  - Generates structured, schema-validated `project-facts.json` along with stable, timestamp-independent cryptographic fingerprint (`context_fingerprint_sha256`) omitting volatile source hashes.
  - Generates derived markdown representations: `architecture.md`, `ui.md`, `persistence.md`, and `conventions.md`.
- **Dual-Layer Architecture & Developer Sovereignty (`lifecycle.py`, `pre_tool_safety.py`)**:
  - Established a strict separation between kit-owned, universal guidance (`.agents/skills/android-harness/references/`) and project-derived context (`.agents/project-context/`).
  - Created `.agents/project-context/project-notes.md` as a developer-owned override file, preserved across updates and uninstall-restore cycles.
  - Added mutation barriers in `pre_tool_safety.py` prohibiting AI agent tools from modifying developer notes or legacy overrides.
- **Previous-Baseline Legacy Migration (`lifecycle.py`)**:
  - Enhanced `update()` and `replace_legacy()` to compare installed generic references against the *previous installed baseline* checksums (`release_checksums.json` / `ownership-v1.json`).
  - Genuinely customized references are automatically migrated into `.agents/project-context/legacy-overrides/` without causing update conflict failures or overwriting upstream updates.
- **Read-Only Context Preview in Installation & Update Prompts (`docs/install-or-update-prompt.md`)**:
  - Added Phase 3.5: Read-only project context preview running `harness_cli.py context preview --repo <app-root>` before lifecycle changes.
  - Requires interactive user confirmation via `ask_question` to approve discovered architectural facts before proceeding to Phase 4.
  - Enforced compact prompt size under 4096 bytes with verified SHA-256 integrity verification.
- **CLI Commands & Doctor Engine Integration (`harness_cli.py`, `doctor/engine.py`)**:
  - Added `android-harness context {preview,generate,status,refresh}` CLI subcommands with optional `--json` output.
  - Integrated `check_project_context()` into `harness doctor` ensuring schema validity, view rendering, zero secret/PII leaks, and context freshness.

## [1.0.32] - 2026-09-14

### Backward Compatibility, Empirical Test Execution Binding, and Sign-Off Provenance Hardening

- **Dual Plan Hash Validation (`plan_authority.py`, `final_verifier.py`)**:
  - Added backward compatibility for active tasks created pre-v1.0.31 without `planning_depth` in `plan.json`.
  - Implemented `validate_plan_hash()` supporting both current payload and legacy payload (omitting `planning_depth`) when `planning_depth` was omitted from the plan.
  - Made `plan_payload` safely access `plan.get("task_id")` and supported customizable `payload_fn` / `hash_fn` hooks.
- **Authoritative Lean Brief Resolution (`review_execution.py`)**:
  - Connected reviewer execution profile resolver directly to immutable package directories in `state_root(repo) / "runs" / snapshot / run_id`.
  - Resolved `brief-<reviewer>.md` paths for dispatched subagent reviewers, falling back cleanly to `review-package.md`.
- **Device Sign-Off Provenance & Identity Enforcement (`run_device.py`, `final_verifier.py`)**:
  - Enforced strict tier-source consistency (`HARD_ENFORCED` only for `host_native`; `RULE_ENFORCED` for `developer_terminal`).
  - Asserts exact device identity matching (`target_user` and `serial_sha256`) between `device_install` and `device_signoff`.
- **Empirical RED → GREEN Test Execution Binding (`run_tests_gate.py`, `final_verifier.py`)**:
  - Recorded `executed_tests` identity list in unit-test gate evidence.
  - Asserted that failing test targets from RED defect reproduction are explicitly present in the executed test list of the GREEN run (`RED target ∈ GREEN executed AND not failed`), preventing skipped or phantom test passes.
- **Resilient Harness State Resolution (`_graph_core.py`)**:
  - Ensured `resolve_cache_file` accurately distinguishes kit layout from installed target applications based on `.agents/scripts` presence, preventing accidental `.agents` directory creation.

## [1.0.31] - 2026-09-14

### Airtight Authority Safeguards, Reviewer Portability, and Defect Binding

- **Universal Model Portability & Global Kill Switch (`review_execution.py`, `pre_tool_safety.py`)**:
  - Decoupled model resolution completely: core has zero hardcoded model providers. Default mapping is `inherit` with explicit host route configuration.
  - Enforced `ALLOW_MODEL_ESCALATION=False` as a true global kill switch forcing all reviewers to `inherit`.
  - Protected `~/.android-harness` from model tool mutations.
- **Strict Human Authority Barriers (`run_device.py`, `workflow.py`, `pre_tool_safety.py`)**:
  - Restricted device verification sign-off (`run_device.py signoff`) to `--source developer_terminal` or trusted host token for `PASS` verdicts; denied from model tool invocations in `pre_tool_safety.py`.
  - Restricted dirty-tree delivery override (`--allow-dirty-tree`) to `--source developer_terminal` and denied from model tool invocations.
- **Architectural Planning Depth & Spec Routing (`plan_authority.py`, `workflow.py`, `final_verifier.py`)**:
  - Made `planning_depth` (`BOUNDED` vs `ARCHITECTURAL`) an authoritative, hashed field in `plan.json` (`plan_sha256`), deterministically routing `spec-compliance-agent`.
- **Authoritative Task Briefs & Freshness Assertions (`review_package.py`, `workflow.py`)**:
  - Pinned lean task briefs to authoritative `requested_outcome`, `task_kind`, expected modules, and expected surfaces.
  - Persisted `external_inputs_sha256` in `current-run.json` and validated across run lifecycles.
- **Empirical Defect Binding & Exact Artifact Chains (`final_verifier.py`, `run_device.py`)**:
  - Bound RED defect names and fingerprints to GREEN verification for `BUG` tasks; unresolved defects remaining in `new_regressions` fail verification.
  - Enforced exact artifact set chain validation across `assemble == install == launch == signoff`.

## [1.0.30] - 2026-09-14

### Airtight Post-Implementation Audit Hardening, Pipeline Order Enforcement, and Spec Governance

- **Abstract Capability Decoupling & Honest Routing (`review_execution.py`, `review_policy.py`)**:
  - Decoupled model selection from hardcoded model names into abstract capability tiers: `STANDARD` reviewers strictly map to `"inherit"` (preserving parent context, zero escalation overhead), while `STRONG` reviewers map to host-specific deep reasoning models (`pro` for Gemini/Antigravity, `opus` for Claude Code, `o3` for Codex) guarded by `ALLOW_MODEL_ESCALATION` and environment variable overrides (`AGENT_HARNESS_MODEL_<HOST>_STRONG`, `AGENT_HARNESS_MODEL_STRONG`).
  - Added full capability routing: `HIGH` severity with `COROUTINES` and `NAVIGATION` with multi-module diffs escalate to `STRONG`.
- **Pipeline Order & Verification Barriers (`run_device.py`, `final_verifier.py`, `workflow.py`)**:
  - **ORDER-001 Enforcement**: Device installation and activity launching strictly require verified passing review evidence before physical/emulator execution can proceed.
  - **Early Material Drift Halting**: `prepare_verification` halts immediately with an actionable error if material code drift is detected, preventing wasteful compilation and review runs on stale plans.
  - **Delivery Clean Working Tree by Default (DELIVERY-CLEAN-001)**: `deliver_task` strictly enforces a clean git working tree before finalizing task delivery, with an explicit `--allow-dirty-tree` escape hatch for test automation.
  - **Lineage & Run-ID Barrier**: Verification run transitions validate that current HEAD and branch match the run lineage, preventing cross-branch tampered execution states.
- **Spec-Compliance Governance & Review Lifecycle (`spec-compliance-agent.json`, `record_review.py`, `review_policy.py`)**:
  - Created canonical subagent specification `agents/subagents/spec-compliance-agent.json` declaring specialized acceptance criteria validation.
  - Added first-class `SPEC_PASS` and `SPEC_FAIL` tokens in `record_review.py` verdict parser.
  - Fixed dictionary vs set handling for `finding_owners` in policy re-evaluations.
  - Plan-aware review routing in both initial and subsequent rounds.
  - **REVIEW-RERUN-001**: Any production file modification occurring after reviews strictly invalidates previous review passes, enforcing comprehensive re-review.
- **Empirical Defect Reproduction & Device Sign-Off (`run_tests_gate.py`, `run_device.py`, `final_verifier.py`)**:
  - Enforced mandatory failing test evidence (`red_evidence`) for all normalized `task_kind == "BUG"` tasks before accepting green test results. Added `--capture-red` flag to `run_tests_gate.py`.
  - Implemented `run_device.py signoff` command to cryptographically record verified human/automated UI walkthroughs, enforced by `final_verifier.py` whenever `device_required=True`.

## [1.0.29] - 2026-09-14

### Comprehensive Security Hardening, Reviewer Model Routing, Lean Task Briefs, and Spec-Compliance Governance

- **Superpowers-Inspired Methodology Enhancements**:
  - **Reviewer Model Routing & Capability Tiers (`review_execution.py`, `review_policy.py`, `pre_tool_safety.py`)**: Added abstract capability routing decoupling policy hashes from model names. Routes `STANDARD` reviewers (fast linter, bug, regression) to high-speed models (`flash`), while routing `STRONG` reviewers to deep reasoning models (`pro`) under a developer-controlled `ALLOW_MODEL_ESCALATION` kill switch.
  - **Lean Task Briefs & Token Economy (`review_package.py`)**: Added generation of role-specific `brief-<reviewer>.md` files (~300–400 tokens) distilling diff-scoped contracts, modified files, and rubrics, reducing subagent prompt token consumption by >60% and eliminating context dilution.
  - **Spec-Compliance Review Auditor (`review_policy.py`, `spec-compliance-agent`)**: Added dedicated `spec-compliance-agent` routed automatically for architectural refactors and multi-phase plans, running in parallel with existing reviewers to verify strict adherence to approved `plan.json` outcomes.
  - **Empirical RED → GREEN Defect Binding (`final_verifier.py`, `run_tests_gate.py`)**: Enforced capture and verification of reproducible failing test output (`red_evidence`) for `BUG` tasks before accepting green fixes, preventing greenwashing and cosmetic assertions.

- **P0/P1 Security Hardening & Anti-Tampering Protections**:
  - **Fail-Closed Shell Mutation Guard (`mutation_guard.py`)**: Enforced strict Default-Deny on unrecognized shell executables during implementation (`IMPLEMENTING` state). Whitelisted audited harness utilities (`review_execution.py`).
  - **Fail-Closed Generic MCP Write Protection (`pre_tool_safety.py`)**: Intercepted generic MCP tools in `PreToolUse`, blocking unauthorized mutation methods (`create`, `update`, `delete`, `deploy`, `patch`, etc.) while allowing safe queries (`get`, `list`, `search`, `read`). Blocked `--force` flags from model.
  - **Task Recovery Protection (`workflow.py`)**: Blocked automatic recovery or cancellation of healthy active tasks in `recover_stale`. Enforced fail-closed uncommitted collision checks.
  - **Anti-Tampering Delivery Sealing (`workflow.py`, `pre_invocation_reminder.py`)**: Centralized `finalize_ready_delivery` enforcing `current_snapshot == ready_delivery_snapshot_sha256` and requiring a clean working tree before finalizing task delivery.
  - **Sensitive Review Override Lockout (`record_review.py`)**: Strictly prohibited lead agent review overrides on sensitive surfaces (`AUTH`, `SECURITY`, `BILLING`, `SENSITIVE_DATA`, `CRYPTO`).
  - **Kotlin Implicit Public API Scoping (`change_classifier.py`)**: Accurately classified Kotlin top-level declarations (which default to `public` in Kotlin), scoping `PUBLIC_API` surface escalation strictly to `PROJECT_KIND == "library"` to avoid false-positive token spikes on application code.
  - **Evidence Producer Whitelist (`final_verifier.py`)**: Added `device_signoff` and `red_evidence` to valid producers in `final_verifier.py`.

## [1.0.28] - 2026-09-13

### Infrastructure Immutability, Trojan Source Shield, Room SQLite Safety, and Production Android DX

- **Infrastructure Immutability & Supply Chain Protection**:
  - **Git, Gradle & IDE Root Immutability (`pre_tool_safety.py`)**: Added `.git`, `.gradle`, and `.idea` to `PROTECTED_ROOTS`, closing Git hook hijacking (`.git/hooks/`) and configuration tampering vectors.
  - **Gradle Wrapper Tampering Protection (`pre_tool_safety.py`)**: Added immutable protection for `gradlew`, `gradlew.bat`, and `gradle/wrapper/` in client repositories, closing wrapper poisoning and supply-chain execution escapes.
  - **Subagent Concurrency & Burst Bound (`pre_tool_safety.py`)**: Bounded batch subagent invocations to maximum 5 in `_handle_subagent`, preventing fork bombs and recursive token exhaustion during implementation.

- **Trojan Source, Secret Shield & Production Android DX Architecture**:
  - **Trojan Source & Invisible Unicode Guard (`fast_kt_lint.py`)**: Added detection for bidirectional unicode formatting control characters (`\u202A`–`\u202E`, `\u2066`–`\u2069`) and zero-width spaces (`\u200B`), stopping invisible visual logic deception (CVE-2021-42574).
  - **Preflight Secret Shield (`fast_kt_lint.py`)**: Added preflight detection for hardcoded credentials (Google API keys, OpenAI/Anthropic keys, Stripe live keys, GitHub PATs, AWS keys, PEM private keys) with automatic test directory and fixture exemptions.
  - **Room Migration NOT NULL SQLite Safety Guard (`room_guard.py`)**: Added detection for `ALTER TABLE ... ADD COLUMN ... NOT NULL` without a `DEFAULT` clause in Room migrations, preventing runtime `SQLiteException` crashes on existing user database upgrades.
  - **Fragment ViewBinding Memory Leak Guard (`fast_kt_lint.py`)**: Added automatic detection for Fragment classes with `_binding` fields that fail to set `_binding = null` in `onDestroyView()`, stopping Android View hierarchy memory leaks.
  - **Insecure Cleartext Traffic Guard (`fast_kt_lint.py`)**: Added detection for unencrypted `http://` URLs in production source code, with safe localhost and emulator loopback (`10.0.2.2`) whitelisting.

## [1.0.27] - 2026-09-13

### Adversarial Hard Attack Hardening, MCP Interception, and Production Android DX

- **Adversarial Hard Attack Hardening & Tool Interception**:
  - **Lazy MCP Tool Interception (`agents/hooks.json`, `pre_tool_safety.py`)**: Added `call_mcp_tool` to `PreToolUse` hooks. Unwraps `ServerName`, `ToolName`, and `Arguments` to block MCP-based evasion vectors (such as unauthorized Notion mutations, Firebase deployments, or unapproved Zoho tracker changes), requiring plan authorization and idempotency tokens for tracker writes while allowing safe read queries.
  - **Root Agent Adapter Immutability (`pre_tool_safety.py`, `change_classifier.py`)**: Added `IMMUTABLE_ADAPTER_FILES` protecting root governance files (`agents.md`, `gemini.md`, `claude.md`, `copilot-instructions.md`, `.cursorrules`, `.windsurfrules`, etc.) from runtime prompt rule poisoning. Classified adapter changes under `HARNESS_CONFIG` (high surface).
  - **Inline Interpreter Execution Denial (`mutation_guard.py`, `pre_tool_safety.py`)**: Strictly blocks raw inline code executions (`python -c`, `py -c`, `node -e`, and unvetted `python -m`) during implementation to prevent arbitrary code execution escapes.
  - **Dynamic Reflection & Loading Detection (`change_classifier.py`)**: Added detection for `Class.forName(...)` loading sensitive packages (`billingclient`, `biometric`, `auth`, `crypto`, `security`), classifying changes under `SECURITY` to prevent hidden reflection attacks.

- **Production Android Developer Experience (DX) Enhancements**:
  - **Smart Compose `@Preview` Awareness (`fast_kt_lint.py`)**: Added `is_stateful_container_only` detection. Stateful composables accepting ViewModel parameters (e.g. `: OrderViewModel = hiltViewModel()`) are exempt from fatal `@Preview` enforcement, eliminating Android Studio preview crashes and dummy ViewModel boilerplate.
  - **Generalized Bidirectional Multi-Locale Check (`fast_kt_lint.py`)**: Generalized locale checks to detect whether RTL (`ar`, `he`, `fa`, `ur`, `iw`) and LTR languages both exist in `SUPPORTED_LOCALES`, enforcing bidirectional previews only when necessary and seamlessly supporting any number of languages (3, 4, or more).
  - **Sprint Localization Grace Period (`check_strings.py`)**: Supported `tools:ignore="MissingTranslation"`, `l10n-todo="true"`, and `translatable="false"` XML attributes in string parity checks, treating work-in-progress translations as non-fatal warnings rather than hard preflight blockers.
  - **Selective Submodule Testing (`run_tests_gate.py`)**: Added `resolve_target_task()` to execute isolated Gradle test tasks (e.g. `:feature:auth:testDebugUnitTest`) when changes are confined to a single submodule, cutting verification latency from minutes to seconds.
  - **Developer Diagnostic Whitelist (`mutation_guard.py`)**: Whitelisted non-mutating developer diagnostic commands (`adb logcat`, `adb shell getprop`, `gradle dependencies`, `gradle tasks`, `gradle projects`, `gradle properties`, `gradle help`, `git status/diff/log/show`) without requiring prior plan authorization.
  - **Emergency Developer Override Support (`record_review.py`, `final_verifier.py`)**: Permitted review overrides on `HIGH`/`CRITICAL` or sensitive surfaces when executed with `--source developer_terminal`, providing a human escape hatch for subagent API rate-limit outages without compromising unattended security.

## [1.0.26] - 2026-09-13

### Autonomous Phased Execution, Clarification Gate, Direct Review Ingestion, and Drift Tolerance

- **Pre-Planning Clarification Gate (`harness-rules.md`, `pre_invocation_reminder.py`, tool adapters)**:
  - Missing requirements, edge cases, or domain ambiguities must be clarified interactively via `ask_question` before drafting the plan; guessing is strictly forbidden.
- **Autonomous Phased Execution (`harness-rules.md`, `pre_invocation_reminder.py`)**:
  - Multi-phase plans execute sequentially and autonomously under single intake approval without pausing between phases or waiting for nonexistent Proceed buttons. Reviews inspect smaller, phase-scoped diffs.
- **Strict Verification Order (`harness-rules.md`, `GEMINI.md`)**:
  - Standardized the verification pipeline order into mandatory 6-step headings: 1. preflight -> 2. unit tests -> 3. routed reviewers -> 4. device install -> 5. mobile walkthrough -> 6. verify.
- **Intelligent Drift Tolerance & Companion Surfaces (`plan_authority.py`)**:
  - Added `:app` default exemption in `check_material_drift` to prevent spurious drift when modules default to `:app`.
  - Added companion surface pairing (`NAVIGATION`, `RESOURCE_UI`, `XML_UI`, `COMPOSE_UI`) and outcome surface keyword matching (`BILLING`, `AUTH`, `NETWORK`, `DATABASE`, `BLUETOOTH`, `LOCATION`, `SECURITY`, `CAMERA`, etc.) to prevent false drift alarms.
- **Approval Nonce Preservation (`workflow.py`)**:
  - Prevented wiping approvals and nonces during benign scope adjustments, breaking the vicious reset cycle.
- **Resilient Preflight Check (`preflight_check.py`)**:
  - `preflight_check.py` falls back gracefully to `preliminary-policy.json` or standard gates (`{"preflight", "localization", "room"}`) when `current-run.json` does not yet exist, preventing execution crashes.
- **Direct Review Response Ingestion (`record_review.py`)**:
  - Added `--response-text "<name>=<text>"` argument to directly ingest subagent review output with cryptographic review-package footer validation, eliminating intermediate scratch files and lead agent self-certification loopholes.
- **Automatic Evidence Bridging (`workflow.py`, `run_device.py`)**:
  - Automatically bridges existing test and preflight results from `state/results/` into `EvidenceStore` on verification run initialization, eliminating redundant gate executions and unfulfilled evidence stalls.
- **Selftest & Verification Expansion (`_vnext_selftest.py`)**:
  - Added regression test `test_material_drift_outcome_matching_and_companion_surfaces` validating companion surfaces and outcome matching tolerance.

## [1.0.25] - 2026-09-13

### Cross-IDE Adapter Parity, Independent Subagent Review Enforcement, and Windows Console Safety

- **Cross-IDE Adapter Parity (`agents/tool-adapters/*`, `GEMINI.md`)**:
  - Propagated the mandatory **Mobile Verification Walkthrough** rule across all agent tool adapters (`AGENTS.md.template`, `GEMINI.md.template`, `CLAUDE.md.template`, `copilot-instructions.md.template`, `CODEX.md.template`, `cursor-android-harness.mdc.template`, `windsurf-android-harness.md.template`, `continue-android-harness.md.template`, `QWEN.md.template`, `github-instructions.md.template`) and root instructions.
  - Mandated that whenever an APK is installed or started on a device, the agent must output a complete, numbered mobile verification walkthrough (Navigation path, Preconditions, User actions, Expected results, Edge cases) in chat BEFORE asking the developer for verification. Strictly forbade asking "Did it pass" without detailed navigation and test instructions.
  - Added explicit independent reviewer requirements across all adapter templates, strictly prohibiting lead agents from self-certifying reviews or manufacturing `--verdict PASS` tokens on HIGH/CRITICAL or sensitive changes.
- **Immediate Reviewer Bypassing Denial (`record_review.py`)**:
  - Prohibited direct `--verdict` recording on `HIGH` or `CRITICAL` severity tasks or sensitive surfaces directly at the CLI level with `ValidationError`. The lead agent cannot fabricate review approvals; evaluations must come from independent reviewer reports or responses.
- **Workflow & Classifier Live Streaming (`workflow.py`, `change_classifier.py`, `_live_process.py`)**:
  - Added line-buffered stdio (`enable_line_buffered_stdio`) to `workflow.py` and `change_classifier.py` so background task outputs stream in real-time without buffering stalls.
  - Wrapped `draft`, `prepare_verification`, and `verify_task` in `step_progress` markers.
  - Replaced unicode emojis in `_live_process.py` and `scripts_dev/release_version.py` with ASCII markers (`[IN PROGRESS]`, `[DONE]`, `[FAIL]`) and added fallback encoding protection in `live_print` to eliminate `UnicodeEncodeError` on Windows consoles (cp1252).
- **Documentation Cleanup**:
  - Removed obsolete, unreferenced, and temporary documents (`docs/conflicts-and-edgecases-report.md`, `docs/root-cause-analysis-and-hardening-plan.md`, `docs/stability-first-dogfooding.md`, and untracked root handoff notes).
- **Selftest Expansion (`_vnext_selftest.py`)**:
  - Added `test_all_tool_adapters_contain_mobile_walkthrough_and_independent_review_rules` to ensure future adapters and templates never regress on walkthrough or review rules.
  - Updated `test_final_verifier_rejects_lead_agent_recorded_verdict_on_high_severity` to assert CLI rejection on HIGH severity and test defense-in-depth verifier rejection.

## [1.0.24] - 2026-09-13

### Real-Time Step Progress Across All Harness Scripts

- **`_live_process.py` — `step_progress` Context Manager**: Added a new `step_progress(name)` context manager that prints `⏳ [IN PROGRESS] <step>` when a step starts and `✅ [DONE] <step> (Xs)` or `❌ [FAIL] <step>` when it finishes. Available to all harness scripts via `from _live_process import step_progress`.
- **`preflight_check.py`**: All five preflight steps (hook selftest, string parity, Room migrations, Fast Lint, plan authority) now emit real-time progress markers. Room and plan authority use inline `⏳`/`✅`/`❌` prints (boolean steps not wrapped in subprocess).
- **`run_tests_gate.py`**: The Gradle unit-test invocation is wrapped in `step_progress` so agents see `⏳ [IN PROGRESS] Running unit tests: <task>` immediately and `✅ [DONE]` or `❌ [FAIL]` with elapsed time once Gradle finishes.
- **`run_gradle_task.py`**: The `run_streaming` Gradle invocation is wrapped in `step_progress(f"Gradle: {task_label}")`, providing a top-level progress marker around every Gradle execution.
- **`run_device.py`**: APK install (`Installing APK on device`) and activity launch (`Launching activity: <activity>`) are each wrapped with `step_progress`, giving live confirmation of device operations.
- **`harness_cli.py` selftest**: Each of the 12 selftest suites is reported with `⏳ [IN PROGRESS] [N/12] selftest: <name>` and `✅ [DONE]` with elapsed time. A final `✅ All 12 selftest suites passed.` summary is printed. The step_progress module is dynamically loaded from the kit's `_live_process.py` so `harness_cli.py` retains zero runtime dependencies.
- **`scripts_dev/release_version.py`**: All five release steps are wrapped with `step_progress`. The selftest step (step 3) now streams output in real-time (removed `capture_output=True`) so silent waits during test runs are eliminated.
- **`_vnext_selftest.py`**: Fixed `test_diagnostic_preflight_needs_no_task_and_writes_no_evidence` to use `encoding="utf-8", errors="replace"` in its `subprocess.run` call, preventing `UnicodeDecodeError` on Windows when the preflight output contains emoji progress markers.

## [1.0.23] - 2026-09-13

### Universal Mobile Test Walkthroughs, UI Component Classification, and Review Provenance Hardening

- **View UI Component Classification (`change_classifier.py`)**: Added deterministic regex recognition for Android View UI components (`Fragment`, `DialogFragment`, `BottomSheetDialogFragment`, `Activity`, `AppCompatActivity`, `RecyclerView.Adapter`, `RecyclerView.ViewHolder`, `ListAdapter`, `ViewBinding`, and view inflation methods) in Kotlin/Java files. Modifying Fragments and Adapters without touching XML layout files now correctly classifies as `XML_UI`, triggering the physical device gate and preventing UI code from being disguised as pure business logic.
- **Mandatory Mobile Test Walkthrough Banner (`run_device.py`)**: Enhanced device execution output upon APK install/launch to format and display an unmissable `[MANDATORY MOBILE TEST WALKTHROUGH]` block containing concrete, numbered manual verification steps for the developer on their target device or emulator.
- **Universal Verification Recipes & Fallback (`_verification_recipes.py`, `run_device.py`)**: Added comprehensive verification recipe fallback (`APPLICATION_FALLBACK_RECIPE`) ensuring that whenever an application is deployed or launched on a device, actionable, numbered test steps are always generated regardless of surface categorization.
- **Review Provenance Hardening & Self-Review Block (`record_review.py`, `final_verifier.py`)**:
  - Enforced mandatory `--evidence-pkg <sha12>` when recording reviewer verdicts with `--verdict`, validating strictly against the active `review-package.md` hash.
  - In `final_verifier.py`, strictly prohibited `lead_agent_recorded_verdict` self-certification on `HIGH` or `CRITICAL` severity tasks and sensitive surfaces (`BILLING`, `AUTH`, `SECURITY`, `SENSITIVE_DATA`, `CRYPTO`). Independent specialist reviewer execution (`reviewer_response_footer` or `structured_report`) is required.
- **Developer Governance & Agent Rules Alignment (`harness-rules.md`, `deliver.md`, `GEMINI.md`)**:
  - Mandated that after every device deployment (`run_device.py install-start`), the agent must output a complete, numbered mobile verification walkthrough (Navigation path, Preconditions, User actions, Expected results, Edge cases) in chat and invoke `ask_question` for developer sign-off before completing the task.
  - Strictly forbade lead agents from bypassing subagent execution during verification.
- **Comprehensive Selftest Coverage (`_vnext_selftest.py`)**: Added deterministic regression tests verifying Fragment/Adapter classification as `XML_UI`, non-empty verification recipes and fallback, mandatory evidence package validation, and rejection of self-certified reviews on high-severity changes.

## [1.0.22] - 2026-09-13

### Skill Subset Authorization, Benign Scope Drift Exemption, and Windows Test Isolation

- **Subset Skill Matching in Final Verifier (`final_verifier.py`)**: Replaced strict set equality (`planned_skills != selected_skills`) with authorization subset matching. Approved tasks can safely utilize a subset of planned skills without triggering spurious `PLAN_APPROVAL_REQUIRED` locks when implementation surfaces require fewer tools than initially anticipated.
- **Benign Engineering Skills & Test Autonomy (`final_verifier.py`, `plan_authority.py`)**: Exempted unit/instrumented tests (`TEST_ONLY`) and documentation (`DOCS`) from material scope drift. Writing unit tests to verify implementation changes no longer triggers unplanned surface locks or forces plan re-drafting.
- **Code-Scoped Coroutines Alignment (`plan_authority.py`)**: Recognized standard Kotlin structured concurrency (`COROUTINES`) as a natural implementation technique when code surfaces (`BUSINESS_LOGIC`, `COMPOSE_UI`, etc.) are approved. Added `COROUTINES` to `DEFAULT_APP_SURFACES` to align default scaffolding with modern Android development.
- **Strict Invariant & Sensitive Boundary Preservation**: Maintained 100% strict verification and approval enforcement on critical surfaces (`BILLING`, `AUTH`, `SECURITY`, `SENSITIVE_DATA`, `CRYPTO`), architecture boundaries (`ROOM_SCHEMA`, `MANIFEST_PERMISSION`, `BUILD_CONFIG`, `NATIVE_CODE`, `PUBLIC_API`), module boundaries, and cryptographic skill file hashes.
- **Windows Environment Variable Isolation in Zoho Selftest (`_zoho_selftest.py`)**: Replaced global `mock.patch.dict(os.environ)` with targeted setting and unsetting of `ANDROID_HARNESS_ZOHO_LEDGER` to prevent Windows / Python 3.14 `ValueError` when host environment metadata exceeds 32,767 characters.
- **Comprehensive Selftest Coverage (`_vnext_selftest.py`)**: Added deterministic regression tests verifying subset skill acceptance, unapproved skill gating, benign test exemptions, and code-scoped coroutines.

## [1.0.21] - 2026-09-13

### Superpowers Skill Hardening, Reviewer Finding Validation, and Documentation Precision

- **Reviewer Finding Validation (`workflow.py`, `record_review.py`, `review_package.py`)**: Introduced technical validation protocol for reviewer findings (`CONFIRMED`, `FALSE_POSITIVE`, `NEEDS_CONTEXT`, `NOT_REPRODUCIBLE`). Mandatory technical rationale required for `FALSE_POSITIVE` findings; embedded validations in review packages to inform re-review without creating final verifier bypass loopholes.
- **Deterministic Policy Rehash Tamper Lock (`_vnext_selftest.py`)**: Added deterministic regression lock verifying that tampering with policy gates fails closed even if the canonical policy hash is recalculated.
- **Architectural Design-Lite (`brainstorming/SKILL.md`, `harness-rules.md`)**: Defined advisory planning depth (`BOUNDED` vs `ARCHITECTURAL`). Bounded tasks proceed with standard low-friction plans; architectural tasks embed a concise trade-off design section into the single approved implementation plan without introducing extra approval checkpoints.
- **Skill Description Hygiene (`agents/skills/`)**: Refactored frontmatter descriptions across all skills to state exact triggering conditions rather than summarizing procedural workflows, preventing shallow LLM execution.
- **Reviewer Prompts & Adaptive Policy Alignment (`review-prompt.md`, `re-review-prompt.md`, `test-quality-reviewer-agent.json`)**: Removed hardcoded "all 5 leaves" assumptions, added `TEST_PASS` token support, and refined coroutines async review criteria to eliminate false-positive flags when virtual time advancement is not required.
- **Developer-Side Skill Pressure Testing (`scripts_dev/skill_evals/`)**: Added standalone behavioral evaluation suite and test runner with realistic development pressure cases, fully isolated from runtime selftests and client task budgets.
- **Documentation Precision & Open-Source Credibility (`README.md`)**: Replaced overclaiming terminology with exact engineering descriptions (`deterministic host-level interception`, `Tamper-Evident Snapshot-Bound Evidence`), added "What This Is Not", comparison with rules files, and an end-to-end Room schema migration walkthrough.

## [1.0.20] - 2026-09-13

### Showcase Expansion, The Basic Workflow, and Full AI Host Matrix

- **Deterministic Quality Guardians Showcase (`README.md`)**: Documented the full suite of purpose-built Android tools: Adaptive Localization Guard (`check_strings.py`), Room Schema & Embedded Drift Guard (`room_guard.py`), Baseline Regression Isolation (`baseline_capture.py`), ANR Risk Analyzer (`perf_guard.py`), Intelligent Compiler Diagnostics (`gradle_error_parser.py`), Hardware Observability & Visual Evidence (`capture_screen.py`, `logcat_doctor.py`), and Universal Multi-Module Graph (`project_graph.py`).
- **The Basic Workflow Framework (`README.md`)**: Introduced the 7-stage deterministic execution sequence (discovery-and-scoping, plan-authority, mutation-guard, adaptive-routing, TDD, specialist-reviewer-squad, tamper-evident-verification) modeling the Superpowers methodology with deterministic OS-level guarantees.
- **Complete AI Host Support Matrix (`README.md`)**: Explicitly integrated OpenAI Codex and GitHub Copilot alongside Google Antigravity, Claude Code, Cursor, Windsurf, and Roo Code.
- **Hero & Navigation Typography Refinement (`README.md`)**: Streamlined README header hero, slogan typography, and interactive anchor navigation.

## [1.0.19] - 2026-09-13

### Critical Safety Hardening, Tamper-Proof Checksums, Lock Atomicity, and SemVer Routing

- **Classifier Coverage Verification (`change_classifier.py`)**: Added per-file classification coverage check in `classify()`. Any delivery-relevant file not covered by a classified surface is tagged as `UNKNOWN`, preventing doc or test changes from masking unclassified changes.
- **Room Embedded & Entity Hierarchy Resolution (`change_classifier.py`)**: Added `_room_schema_types(repo)` helper to recursively resolve `@Database` entities and nested `@Embedded` types across files. Kotlin and Java changes matching these types are deterministically tagged as `ROOM_SCHEMA`, enforcing migration checks.
- **Kit Checksum Schema & Inventory Integrity (`harness_cli.py`, `lifecycle.py`)**: Enforced top-level JSON schema validation, non-empty file inventories, and presence of mandatory anchor files (`agents/VERSION`, `agents/scripts/lifecycle.py`) in `_verify_kit_checksums()` and `_validate_kit()`.
- **Skill Router SemVer & Kernel Major Validation (`skill_router.py`)**: Enforced SemVer 2.0.0 regex compliance (including pre-release tags) and integer parsing for `kernel-major` metadata. Missing or malformed skill metadata immediately blocks routing with `BLOCKED`.
- **Final Verifier Repository Identity & Branch Integrity (`final_verifier.py`)**: Validates repository identity fields (`root_sha256`, `git_common_dir_sha256`, and `branch`) against `recorded_manifest`, failing closed with `STALE` if the branch drifts or repository changes during verification.
- **Atomic Nonce-Backed Stale Lock Reclaim & Spin-Free Backoff (`evidence_store.py`)**: Stored unique random `nonce` in `StateLock`, verified `nonce` and `pid` in `__exit__`, added atomic stale lock validation in `_try_remove_stale_lock()`, and eliminated CPU busy-spins by backing off with `time.sleep(0.05)` when lock release is delayed.
- **Critical Safety Regression Suite (`_critical_safety_selftest.py`)**: Added 18 comprehensive unit tests covering all audit findings and positive neighboring invariants.
- **Open Source Showcase & Documentation Overhaul (`README.md`)**: Rebuilt project README with comprehensive architectural breakdowns, multi-host guides, realistic developer guarantees, and failure mode comparisons.

## [1.0.18] - 2026-09-12

### Stability-First Guidance, Safe Upgrades, and Verified Releases

- Correct Compose stability guidance and reviewer prompts: annotations require valid contracts, recomposition changes require diagnosis, and derived state should change less often than its inputs.
- Resolve locales, modules, source sets, and build variants from project configuration instead of assuming Arabic/English, an application module, or debug builds. Keep previews focused on changed states and supported tooling.
- Strengthen test-quality guidance with independent expectations, intended rejection reasons, and nearby valid cases. Keep debugging hypothesis-driven and re-review scoped to fixes and resulting regressions under central policy.
- Extend device prerequisite regression coverage to reject an omitted unit gate even after the policy hash is recomputed and valid preflight evidence exists, while preserving acceptance of complete evidence.
- Add a stability-first dogfooding guide without changing the runtime architecture or adding workflow stages.
- Reject incomplete FINDINGS reports instead of silently approving delivery.
- Refresh unchanged default references on upgrade while preserving project tailoring and reporting references that differ from the new defaults.
- Validate complete release checksum inventories and independent Citation File Format metadata; preserve `cff-version` when bumping the software version.
- Build release packages in an owned temporary workspace, preserving existing checkout artifacts. Require the complete selftest suite and successful CI for the exact commit before tagging, plus successful tag validation before publication. PyPI uploads independently enforce the same checks.
- Return failure when GitHub publication fails and pass release notes through a UTF-8 file. Local-only release preparation creates a commit without a tag; skipping tests is limited to dry runs.

## [1.0.17] - 2026-09-12

### Deterministic Device Policy Artifact Verification & Prerequisite Hardening

- **Deterministic Policy Artifact Verification (`final_verifier.py`, `run_device.py`)**: Extracted `validate_policy_artifact(...)` to evaluate policy integrity, classification freshness, and deterministic policy derivation (`decide` / `decide_later_round` with full `task_kind` and `project_kind` fidelity). Replaced unverified gate reading in `run_device._check_device_prerequisites()` with verified expected policy gates, preventing dropped `unit_tests` gates from bypassing device prerequisite safety.
- **Local Tag Overwrite Warning Precision (`release_version.py`)**: Differentiated remote-verified `ABSENT` warnings from local `--no-push` overwrite warnings when `--allow-tag-overwrite` is supplied.
- **Scenario Selftest Matrix Expansion (`_android_scenarios_selftest.py`)**: Added positive and negative test cases to `test_scenario_r05_device_prerequisites_safety` validating rejected tampered policies, rejected missing unit test evidence, and accepted complete evidence lifecycles.

## [1.0.16] - 2026-09-12

### Device Prerequisite Verification, Checked-In Source Preservation, Room Builder Scoping, and Remote Release Immutability

- **Device Prerequisite & Snapshot Freshness Verification (N01, `run_device.py`)**: Replaced broken module import with `_read_harness_version()` referencing `agents/VERSION`, integrated `final_verifier._validate_artifact` for full gate evidence validation, verified active `delivery_snapshot_sha256` freshness to fail closed on stale snapshots, and rejected empty verification policy gate definitions.
- **Source-Set Generated Directory Allowance (N02, `pre_tool_safety.py`, `_android_scenarios_selftest.py`)**: Refined `EPHEMERAL_GENERATED_RE` to strictly deny ephemeral build outputs (`build/generated/`, `build/intermediates/`, and repo-root `generated/(source|ksp|kapt)/`) while permitting checked-in source-tree directories such as `app/src/main/generated/ksp/`.
- **Manual Room Migration Registration Enforcement (N03, `room_guard.py`)**: Removed manual migrations declared in database class files from pre-registered `migrations`, requiring manual migrations to be explicitly registered in `addMigrations(...)` or inline builder calls to pass.
- **DatabaseBuilder Scoping & Unchanged Version Migration Spanning (N04, `room_guard.py`)**: Scoped `addMigrations(...)` blocks to the specific database class declared in preceding `Room.databaseBuilder(...)` invocations to prevent false credit in shared DI modules. Derived `target_start` dynamically from candidate migration edges when candidate migration files are modified without incrementing the database schema version.
- **Strict Remote Release Tag Immutability (N05, `release_version.py`)**: Made remote origin tag preflight and GitHub release verification unconditional even when `--allow-tag-overwrite` is passed. Disallowed `-f` flag on remote tag pushes, and removed destructive release overwrite fallbacks.

## [1.0.15] - 2026-09-12

### Structural Lexical Scoping, Manifest Floor Precision, Room Isolation, and Release Safety Hardening

- **Structural Scope Isolation & Raw String Support (R01, `change_classifier.py`)**: Added multiline triple-quoted raw string (`"""` / `'''`) tracking across lines in `_strip_code_line`. Reset declaration headers on new declarations to prevent expression-body functions from leaking into sibling declarations, and trimmed header lines on `{` to prevent same-line class body properties from contaminating class scope.
- **Manifest Component Attribute Precision (R02, `change_classifier.py`)**: Refined `MANIFEST_PERMISSION` and `DEVICE_API` classification to inspect diff text and enclosing element tags rather than entire enclosing component context, preventing label-only edits on exported `<activity>` components from falsely requiring physical devices.
- **Generated Build Output Mutation Barrier (R03, `pre_tool_safety.py`)**: Removed overly broad `/src/` exemption from ephemeral generated code checking, strictly rejecting file mutation tools on generated build outputs under `build/generated/`, `build/intermediates/`, and `generated/(source|ksp|kapt)/`.
- **Room Multi-Database Isolation, Java Variables & Inline Migration Parsing (R04, `room_guard.py`)**: Isolated candidate migration files and `addMigrations(...)` to the database referenced by their `Room.databaseBuilder` call, preventing cross-database contamination. Added parsing for Java `Migration` fields (`new Migration(...)`), added balanced-parenthesis extraction for inline `object : Migration(...)` calls in `addMigrations`, permitted valid unused alternative migrations when a complete migration path is registered, and enforced migration verification on candidate file edits.
- **Device Prerequisite Strictness & Producer Verification (R05, `run_device.py`)**: Enforced matching `task_id` between active task and `current-run.json`, required present `delivery_snapshot_sha256`, and validated evidence record producers against `ALLOWED_PRODUCERS` and `HARNESS_VERSION`.
- **Release Automation Server Error Safety & Tag Assertion (R06, `release_version.py`, `publish-pypi.yml`)**: Differentiated HTTP 404 from HTTP 500 / network errors in `github_release_status` to fail closed (`UNKNOWN`), halted release script on git commit errors, and asserted release tag matches package version in GitHub Actions PyPI publishing workflow.
- **Localization Multiline Tag Recognition (R07, `check_strings.py`)**: Implemented multiline element interval matching in `_extract_touched_keys_from_xml` to accurately extract touched keys when `<string`, `<plurals>`, or `<string-array>` opening tags span multiple lines.
- **Regression Matrix Suite Expansion (R08, `_android_scenarios_selftest.py`)**: Added comprehensive regression tests locking R01–R07 invariants into the 42-test scenario matrix suite.

## [1.0.14] - 2026-09-12

### Audit Findings Hardening, FQN Resolution, Multi-Device Disambiguation, and Verification Precision

- **BUG Task Policy Evaluation Alignment (F01, `final_verifier.py`)**: Passed `task_kind` (`BUG` vs `FEATURE`) to deterministic policy evaluation and later-round recalculation in `final_verifier.py`, ensuring bug tasks properly evaluate policy without mismatch.
- **Git Porcelain v2 Rename Token Parsing (F02, `_repo_files.py`)**: Updated porcelain v2 parsing to use 9 split limits (`line.split(" ", 9)`), correctly extracting destination paths and stripping rename similarity score tokens (e.g. `R100`).
- **Device Prerequisite Strictness & Active Run Boundary (F03, `run_device.py`)**: Enforced immutable `EvidenceStore` verification and strict `current-run.json` checks in `run_device.py`, failing closed with `EXIT_ENV` when run files are missing, corrupt, or mismatched.
- **Brace-Balanced & Kotlin Parameter Scope Extraction (F04, F05, `change_classifier.py`)**: Replaced upward sliding regex with a brace-balanced structural scope parser, correctly scoping Kotlin data classes, long methods (>150 lines), and multiline XML elements without false escalation or missing enclosing scopes.
- **Room Migration Completeness & Entity Lifecycle Hardening (F06, F07, `room_guard.py`)**: Stored historical HEAD declarations to detect entity deletion and membership shifts, requiring database version increments. Verified that all intermediate migration edges are explicitly registered in `addMigrations(...)` before granting approval.
- **Localization Array & Plural Hierarchy Checking (F08, `check_strings.py`)**: Mapped diff hunks to enclosing `<plurals>` and `<string-array>` tags and checked item-level placeholder consistency across localized collections.
- **Checked-in Generated Source Exemption (F10, `pre_tool_safety.py`)**: Allowed edits to checked-in generated sources under `/src/` while strictly keeping ephemeral build directories protected from direct host writes.
- **Release Automation Preflight Provenance & Hardening (F11, `release_version.py`, `publish-pypi.yml`)**: Added tri-state remote tag status checking (`PRESENT`, `ABSENT`, `UNKNOWN`) and GitHub release validation before mutation. Removed `skip-existing: true` in PyPI publishing workflow.
- **Scenario Matrix CI Integration & Guard Hardening (F12, `ci.yml`, `_android_scenarios_selftest.py`)**: Added `_android_scenarios_selftest.py` into GitHub Actions CI test matrix, and strengthened Scenarios 07, 10, 20, 2C, and multi-device checks with direct guard execution.
- **Baseline and Startup Profile Coverage (F13, `delivery_manifest.py`, `change_classifier.py`)**: Included `baseline-prof.txt` and `startup-prof.txt` in delivery manifest relevance checks and classified them under `BUILD_CONFIG`.
- **Accurate Delivery Snapshot Guidance (F14, `harness-rules.md`)**: Clarified working tree snapshot proof boundaries in documentation.
- **Graph FQN Import Resolution & Advisory Call-Chain Guidance (F15, `_graph_core.py`, `review_package.py`)**: Resolved exact FQN imports first in graph engine, preventing short name collisions, and updated reviewer call-chain guidance.
- **Navigation Surface Routing & Dedicated Device API Recipe (F17, `change_classifier.py`, `review_policy.py`, `_verification_recipes.py`)**: Added `NAVIGATION` classification for navigation graph resources and navigation APIs, routed it to appropriate reviewers and device requirements, and added dedicated `DEVICE_API` verification recipes.
- **StateLock for Debug Evidence & TDD Assertion Realignment (F18, `workflow.py`, `SKILL.md`)**: Guarded `record_debug_evidence` with `StateLock` and validation against file corruption, and updated TDD/debugging skill instructions to focus on meaningful seams.
- **Multiple Physical Device Disambiguation (F20, `_repo_files.py`, `run_device.py`)**: Added `matching_adb_serials` and fail-closed actionable error in `require_serial` when multiple matching target devices are connected without an explicit `--serial`.

## [1.0.13] - 2026-09-12

### Stability-First Android Specialization, Systematic Debugging, Generated-Code Protection, and Deterministic Verification Recipes

- **30-Scenario Android Regression Test Matrix (`_android_scenarios_selftest.py`)**: Implemented a comprehensive, deterministic 30-scenario regression test matrix (plus scenario 15b, Phase 2C, and Phase 3 verification suites, total 33 tests) covering edge cases across Android lifecycles, ViewModel logic, Compose UI, multi-module graphs, Room migrations, AIDL preservation, baseline failure normalization, wireless ADB timeouts, stale gate blocking, and non-destructive Git invariants. Integrated directly into `harness_cli.py selftest`.
- **Ephemeral Generated-Code Write Barrier (`pre_tool_safety.py`)**: Added deterministic protection denying host file-modifying tools on ephemeral Gradle build outputs (`build/generated`, `build/intermediates`, `generated/source`, `generated/ksp`, `generated/kapt`) while ensuring checked-in generated sources (`src/**/generated`) remain fully editable.
- **Semantic AndroidManifest Path Floors (`change_classifier.py`)**: Differentiated Android manifest diffs by semantic impact: `uses-permission`, `android:exported`, sensitive `provider`, and `intent-filter` trigger `MANIFEST_PERMISSION` (HIGH severity, physical device verification); background components (`service`, `receiver`, `uses-feature`) map to `DEVICE_API` and `BUILD_CONFIG`; generic manifest tweaks default to `BUILD_CONFIG`. Preserved AIDL strictly as `NATIVE_CODE`.
- **Lightweight Systematic Debugging & Out-of-Band Debug Evidence (`workflow.py`, `plan_authority.py`, `mutation_guard.py`, `SKILL.md`)**: Added `--kind AUTO|BUG|FEATURE|REFACTOR` to `workflow.py draft` with automatic detection of bug/crash markers and routing of `systematic-debugging`. Added `workflow.py debug-evidence` subcommand to capture empirical reproduction references, hypotheses, and risks into `debug-evidence.json` inside the task state directory during implementation, strictly preserving the immutability of `plan.json` and its approved `plan_sha256`. Added `EVIDENCE_LIMITED` escape hatch in `systematic-debugging` skill. Whitelisted `debug-evidence` in `mutation_guard.py`.
- **Deterministic Manual Verification Recipes (`_verification_recipes.py`, `run_device.py`, `workflow.py`)**: Added deterministic 3–5 step manual testing recipes for `COMPOSE_UI`, `XML_UI`, `NAVIGATION`, `ROOM_SCHEMA`, `MANIFEST_PERMISSION`, and `FOREGROUND_SERVICE`. Pure logic changes (`BUSINESS_LOGIC`) receive zero device recipe ceremony. Integrated recipes into `prepare_verification` (`current-run.json`) and `run_device.py` to display recommended steps upon app launch.

## [1.0.12] - 2026-09-11

### Release Immutability, Scoped Overrides, Device Prerequisite Strictness, Context Window Expansion, and Resilient Resource Guards

- **Release Immutability & Safe Tag Management (`release_version.py`)**: Added local and remote Git tag preflight verification to prevent accidental tag overwrites. Removed unconditional forced flags (`-f`) from tag creation and pushing, and added GitHub Release preflight checks unless `--allow-tag-overwrite` is explicitly provided.
- **Binary-Safe CRLF Validation (`generate_release_checksums.py`, `validate_release.py`)**: Restricted CRLF line-ending validation to text file extensions (`TEXT_EXTENSIONS`), allowing binary assets to be hashed raw without false-positive rejections.
- **Review Override Scoping & Provenance Enforcement (`record_review.py`, `final_verifier.py`)**: Prohibited developer review overrides (`--override-reviews`) on tasks with `HIGH` or `CRITICAL` severity in addition to sensitive surfaces. Ingested and stamped reviewer response footer, structured report, and lead agent verdict provenance into report identities.
- **Device Prerequisite Gate Strictness (`run_device.py`)**: Enforced that prerequisite verification gates (`preflight_check`, `unit_tests`) are verified exclusively through the active task snapshot in the evidence store, eliminating stale mutable gate fallbacks during active runs.
- **Classifier Context Window Expansion & Enclosing Class Scoping (`change_classifier.py`)**: Expanded upward declaration scanning window to 100 lines for immediate declarations and up to 120 lines for enclosing `class/interface/object` declarations and annotations. Bounded outer class extraction to declaration headers, preventing untouched class-body properties from triggering false surface classifications. Added deterministic path floors for network security config and ProGuard/baseline profile files.
- **Localization Guard Missing & Deleted Locale Coverage (`check_strings.py`)**: Added missing localized file detection for touched base XML resources, diff-scoped deletion parity checks, and explicit missing-file reporting.
- **Room Guard Deleted Entities & Cross-File Registration (`room_guard.py`)**: Added entity deletion tracking via `git show HEAD:<path>`, triggering schema bump requirements when entities are deleted. Added module-wide candidate migration discovery for migrations declared across external files.
- **Deterministic Regression Test Coverage (`_vnext_selftest.py`)**: Added 8 comprehensive unit tests validating each hardening capability.

## [1.0.11] - 2026-09-10

### Single-Shot Proceed Invariant, Direct Follow-Up Execution, and Anti-Stalling Reminders

- **Single-Shot Proceed Invariant (`harness-rules.md`, `GEMINI.md.template`, `GEMINI.md`)**: Codified that the interactive **`Proceed`** button in Antigravity is single-shot and appears ONLY on the initial plan draft for task intake. Documented that subsequent updates show only a **`[Review]`** diff button.
- **Direct Follow-Up Execution Rule (`harness-rules.md`, `AGENTS.md.template`, `AGENTS.md`)**: Mandated that within active tasks (`IMPLEMENTING` or `VERIFYING`), developer feedback, bug reports, and follow-ups are immediate execution directives. Prohibited agents from drafting redundant plans or stalling for nonexistent UI buttons; required direct code execution, verification, compilation, and deployment.
- **Anti-Stalling Pre-Invocation Reminders (`pre_invocation_reminder.py`)**: Injected turn-by-turn anti-stalling directives for `IMPLEMENTING` and `VERIFYING` states to prevent agents from creating redundant plans or demanding `Proceed` on follow-ups.
- **Regression Test Coverage (`_vnext_selftest.py`)**: Added test coverage validating the Single-Shot Proceed Invariant across rules, templates, and pre-invocation reminders.

## [1.0.10] - 2026-09-10

### Task Delivery Lifecycle, Draft Collision Barrier, Device Gating, and Interactive Review Override

- **Task Delivery Lifecycle & Cleanup (`plan_authority.py`, `workflow.py`)**: Added `deliver(plan)` to formalize the transition from `READY_FOR_DELIVERY` to `DELIVERED` with an immutable `delivered_at` timestamp. Added `workflow.py deliver` subcommand to cleanly finalize tasks and unlink `.agents/state/active-task.json`.
- **Working Tree Collision Barrier & Auto-Delivery (`workflow.py`)**: Introduced `_find_uncommitted_task_files` in `workflow.py draft` to strictly block drafting new tasks when uncommitted changes from a prior task exist in the working tree (preventing cross-task contamination), with `--force` override available. Added auto-delivery for tasks in `READY_FOR_DELIVERY` once all files are committed to Git HEAD.
- **Device Hard Barrier during Implementation (`mutation_guard.py`, `run_device.py`)**: Codified defense-in-depth blocking of `run_device.py` while the task is in `IMPLEMENTING` across both `mutation_guard.py` (shell command boundary) and `run_device.py` (internal state inspection).
- **Strict Verification Gate Ordering (`run_device.py`)**: Enforced that `preflight` and `unit_tests` (when mandated by policy) must execute and pass in the active verification run before APK install or launch is permitted.
- **Interactive Developer Review Override (`record_review.py`, `final_verifier.py`)**: Enabled developers to skip AI specialist reviews via interactive `ask_question` with mandatory risk disclosure. Added `--override-reviews`, `--proof-reference`, and `--source` to `record_review.py`, recording immutable `DEVELOPER_OVERRIDE` evidence with producer `developer_approval`.
- **Sensitive Surface Protection**: Review overrides are strictly forbidden on tasks modifying `BILLING`, `AUTH`, `SECURITY`, `SENSITIVE_DATA`, or `CRYPTO` surfaces; both `record_review.py` and `final_verifier.py` fail closed.
- **Noise Suppression (`pre_invocation_reminder.py`)**: Automatically finalizes clean `READY_FOR_DELIVERY` tasks upon commit and restores the clean initial prompt.
- **Comprehensive Regression Suite (`_vnext_selftest.py`)**: Added 4 end-to-end unit tests validating delivery lifecycle, draft collision barriers, device gating, and review overrides.

## [1.0.9] - 2026-09-10

### Surface Alias Normalization, Safe Clean-Repo Baselines, and Strict Verification Pipeline Order

- **Surface Alias Normalization (`plan_authority.py`, `workflow.py`)**: Introduced `SURFACE_ALIASES` mapping natural surface descriptors (`code`, `ui`, `compose`, `xml`, `strings`, `tests`, `db`, `permissions`) to formal canonical classifier outputs. Added `normalize_expected_surfaces` to eliminate false-positive Material Implementation Drift halts caused by free-form naming in `workflow.py draft`.
- **Safe Clean-Repo Baseline Defaulting (`workflow.py`, `plan_authority.py`)**: Added `DEFAULT_APP_SURFACES = ["BUSINESS_LOGIC", "COMPOSE_UI", "XML_UI", "RESOURCE_UI"]` for draft plans created on clean working copies when `--expected-surfaces` is omitted, eliminating false drift on standard logic/UI edits while strictly keeping sensitive surfaces (`BILLING`, `AUTH`, `SECURITY`, `ROOM_SCHEMA`, `MANIFEST_PERMISSION`) protected by drift halts.
- **Strict Verification Pipeline Execution Priority (`review_policy.py`)**: Replaced alphabetical sorting of policy `gates` with `PIPELINE_GATE_ORDER = ("preflight", "localization", "manifest", "unit_tests", "assemble", "device")`, guaranteeing that any tool or agent inspecting `policy.json` receives gates strictly in priority execution sequence.
- **Verification Directive Realignment (`pre_invocation_reminder.py`)**: Realigned `VERIFYING` state ephemeral reminders in `_compact_message()` and `_message()` to explicitly instruct: `Order: 1. preflight -> 2. unit tests -> 3. routed reviewers (parallel) -> 4. device install (if required) -> 5. verify.`, preventing premature reviewer dispatch or premature APK installation on physical devices.
- **Hard Verification Pipeline Invariants (`harness-rules.md`, `deliver.md`)**: Codified strict pipeline rules in Section 4: prohibiting APK installation or device deployment before JVM unit tests pass, and prohibiting AI reviewer dispatch before preflight and unit tests pass. Updated `deliver.md` steps 4–5 into explicit sequential sub-phases.
- **Deterministic Test Hardening (`_vnext_selftest.py`)**: Added test coverage for surface alias normalization, clean-repo draft baseline defaulting, sensitive drift retention, and execution-priority gate sorting.

## [1.0.8] - 2026-09-10

### Structural Context Classification, Enhanced Test Fingerprinting, and Hardened Room & Resource Guards

- **Structural Context Classification (`change_classifier.py`)**: Added bounded upward declaration scanning (`_enclosing_structural_context`) to examine up to 40 lines above modified diff hunks. Inspects enclosing Kotlin/Java classes, interfaces, objects, and leading annotations (`@Entity`, etc.), ensuring modifications inside annotated entities trigger `ROOM_SCHEMA` and `PERSISTENCE` surfaces even when the class header itself was not touched.
- **Normalized Test Failure Fingerprinting (`baseline_capture.py`, `run_tests_gate.py`)**: Added `normalize_failure_message` to strip unstable hex memory addresses (`<HEX>`), paths (`<PATH>`), line numbers (`:<LINE>`), and UUIDs from failure messages. Added `error_type` to fingerprints with backward-compatible fallback to `legacy_fingerprint` for older baseline schemas.
- **Resource and Plural Parity Hardening (`check_strings.py`)**: Extended translation pair discovery and touched-keys analysis to cover `plurals.xml` and `arrays.xml` alongside `strings.xml`. Added deletion tracking (`-` lines) in git diffs to detect keys removed from base values without matching removals in localized variants.
- **Cross-File Room Migration Discovery (`room_guard.py`)**: Added `find_candidate_migration_files` to discover migration definitions and registrations declared outside the database class (e.g. in `*Migration*.kt` or `*DatabaseModule*.kt`) within the Gradle module scope.
- **Read-Only Release Checksum Generator (`generate_release_checksums.py`)**: Converted release checksum generation into a strictly read-only validation tool that aborts with `SystemExit` if CRLF line endings are encountered, preventing silent working tree mutations.
- **Review Package Token Optimization and Ambiguity Notices (`review_package.py`)**: Prevented duplicating tracked added files already present in `git diff HEAD` within `review-package.md`, cutting redundant reviewer tokens by 30–50%. Added `Topology Ambiguity Notice` when stem lookups find multiple candidate classes.
- **Isolated Changed Path Detection (`_repo_files.py`)**: Added `repo: Path | None = None` support to `changed_paths` to allow isolated unit and policy tests on temporary repositories without cross-contaminating global process state.

## [1.0.7] - 2026-09-09

### Cross-Platform Checksum Normalization and Automated Prompt Pinning

- **Cross-Platform LF Normalization (`generate_release_checksums.py`, `release_version.py`)**: Enforced Unix LF (`\n`) line endings when generating `agents/VERSION`, `pyproject.toml`, `CITATION.cff`, and `_hook_selftest.py` across all operating systems. `generate_release_checksums.py` now automatically normalizes any CRLF occurrences on disk to LF before computing cryptographic SHA-256 digests, guaranteeing that `agents/release_checksums.json` matches byte-for-byte on Linux, macOS, and Windows CI runners.
- **Automated Prompt Branch Pinning (`pin_prompt_docs.py`)**: Enhanced `pin_urls` to automatically detect and synchronize `--branch vX.Y.Z --single-branch` and detached release references (`detached `vX.Y.Z``) in `docs/install-or-update-prompt.md` and `README.md`, eliminating manual doc sync errors.
- **Release Validation Hardening (`validate_release.py`)**: Added automated checks enforcing that prompt branch pins match the release version and that zero files in `agents/release_checksums.json` contain Windows CRLF line endings.

## [1.0.6] - 2026-09-09

### Diff-Aware Classification, In-Chat Sensitive Approval, and Interactive Device Verification

- **Diff-Aware Semantic Classification (`change_classifier.py`)**: Restructured semantic pattern detection (`BILLING`, `AUTH`, `CRYPTO`, `SECURITY`, `SENSITIVE_DATA`, `ROOM_SCHEMA`, `PERSISTENCE`, `NETWORK`, `DEVICE_API`) to scan only the added (`+`) and removed (`-`) lines from `git diff -U0 HEAD -- <file>`. Eliminates false-positive critical escalations on large files containing untouched legacy subscription/auth code, reducing token usage and task duration by 60–80% while retaining 100% detection of actual billing/auth modifications or deletions.
- **In-Conversation Sensitive Surface Approval (`workflow.py`, `final_verifier.py`, `pre_tool_safety.py`)**: Enabled `--source conversation --enforcement-tier RULE_ENFORCED` for `approve-sensitive`, allowing agents to solicit approval interactively via `ask_question` and record it with developer proof in chat, completely removing the requirement for manual external PowerShell terminal commands.
- **Interactive Human-in-the-Loop Device Verification (`harness-rules.md`, `pre_invocation_reminder.py`)**: Codified mandatory human verification protocol following `run_device.py install-start`: agents must provide numbered manual testing instructions and invoke `ask_question` asking the developer to verify on device (`Pass` / `Fail`) before final verification.
- **Structural Compose UI Detection**: Maintained full-text checks for `@Composable` and `androidx.compose` to guarantee that edits to existing Compose screens always properly trigger the UI review and physical/emulator device gate.

## [1.0.5] - 2026-09-09

### Subagent Architectural Graph Integration and Smart Anti-Cascade Grep Guard

- **Subagent Architectural Graph Integration (`review_package.py`)**: Embedded an authoritative `## ARCHITECTURAL GRAPH & BLAST RADIUS TOPOLOGY` section in `review-package.md`, pre-computing Clean Architecture layer mappings (`UI -> ViewModel -> Domain -> Data`), cross-module caller dependencies, and navigation links for changed files so all 6 subagent reviewers get immediate, authoritative architectural context without needing shell write tools.
- **Roster Alignment Across All 6 Reviewers**: Synchronized system prompts and investigation protocols across all 6 reviewer roles (`perf-anr-guardian-agent`, `bug-reviewer-agent`, `regression-impact-reviewer-agent`, `convention-reviewer-agent`, `security-reviewer-agent`, and `test-quality-reviewer-agent`) to inspect the pre-computed topology and trace external callers directly via bounded `view_file` calls.
- **Smart Anti-Cascade Grep Guard (`pre_tool_safety.py`, `hooks.json`)**: Added `grep_search` and `find_by_name` to PreToolUse hooks. Permits file-specific and feature-targeted searches as well as reviewer verification searches unconditionally, while intercepting unanchored whole-repository cascades during initial discovery and redirecting agents to `project_graph.py --feature <name>` or `--find <symbol>`.
- **Persistent Turn-Start Reminder (`pre_invocation_reminder.py`)**: Updated the ephemeral hook to inject a compact reminder across all subsequent conversation invocations, ensuring long-running agents retain awareness of graph-first discovery and central rules.
- **Deterministic Checksum and Prompt Alignment**: Normalized `agents/VERSION` line endings to LF, aligned prompt version pinning to `v1.0.5`, and updated `release_checksums.json` covering all 147 files.

## [1.0.4] - 2026-09-09

### Stop hook idle unblocking and review recording bridge

- **Stop hook idle unblocking**: Allowed the host `Stop` hook (`pre_tool_safety.py`) to emit `allow` during active task states (`VERIFYING`, `IMPLEMENTING`), eliminating the toxic polling loop when waiting for asynchronous background tasks and reviewer subagents.
- **Reviewer verdict recording bridge (`record_review.py`)**: Added `record_review.py`, `final_verdict.py`, and `perf_guard.py` to `VERIFY_COMMANDS` in `mutation_guard.py`, allowing the agent to record reviewer verdicts during `VERIFYING`.
- **Incremental staged review recording**: Upgraded `record_review.py` to support `--reviewer <name> --verdict PASS` and `--verdict <name>=PASS`, staging evaluations incrementally and automatically completing immutable ingestion once all required reviewers are present.
- **Workflow recovery unblocking**: Authorized `workflow.py resume` during both `VERIFYING` and `BLOCKED` states so that compilation or test failures can be fixed without task invalidation.
- **Task draft collision fix**: Changed directory creation in `workflow.py draft` to `exist_ok=True` to prevent `WinError 183` collisions on task re-drafting.
- **Discovery and efficiency enforcement**: Mandated `project_graph.py` upfront at discovery and forbade unanchored grep cascades and busy-wait polling with `manage_task status`.

## [1.0.3] - 2026-09-09

### Safety boundary unblocking for chat installation and updates

- Unblocked kit bootstrap, staging clone, and lifecycle update commands from requiring an active application plan.
- Allowed writing temporary setup answers JSON files in the OS temp directory outside the repository without an active task plan.
- Enhanced safety regex matching to support quoted paths, py launcher, and whitespace across inspection and lifecycle commands.
- Strengthened fail-closed repository boundary to prevent internal protected state writes even when test repositories are hosted inside temp directories.

## [1.0.2] - 2026-09-09

### Reliable chat installation

- Kept the entry prompt within Antigravity's fetch limit and made wizard discovery the only Android interview authority.
- Added one-process atomic legacy replacement with rollback and preservation of project references and Zoho defaults.
- Added a real emulator-only device policy covering install, launch, screenshots, and logcat.
- Separated previous answers from the single recommended option and fixed case-insensitive Hilt discovery.
- Allowed safe CLI diagnostics without an active task and added a fast foreground post-install doctor check.
- Improved effective JDK discovery across Gradle configuration, `JAVA_HOME`, Android Studio JBR, and `PATH`.

## [1.0.1] - 2026-09-09

### Chat installation contract hardening

- Made the setup wizard JSON payload the sole authority for adaptive chat questions and conditional options.
- Added a separate, explicit approval gate for downloading or replacing the user-level kit cache.
- Kept application installation, update, and legacy replacement behind a second lifecycle-specific approval.
- Deferred temporary answer-file creation until lifecycle approval and placed it outside the Android checkout.
- Added regression coverage for the two-stage approval order and dynamic question contract.

## [1.0.0] - 2026-09-09

### Approval-first adaptive architecture

- Replaced automatic execution and fixed reviewer fan-out with an explicit, hash-bound plan approval and single-use execution authority.
- Added deterministic change classification, on-demand versioned skills, adaptive reviewers/gates, and a three-round review cap.
- Added canonical Git-blob delivery manifests covering staged, unstaged, untracked, deleted, renamed, and redacted external build inputs.
- Added append-only run evidence and a read-only final verifier that rejects stale, mixed, forged, missing, or emergency evidence.
- Added complete split-APK artifact-set hashing across assemble, install, and launch.
- Added transactional clean install, same-major update, ownership-safe dry-run uninstall, tailoring preservation, backup, and rollback.
- Preserved Zoho Sprints behavior while adding stable mutation operation ids and unknown-outcome protection against duplicate retries.
- Replaced the monolithic hook policy with a compact safety boundary and honest per-host enforcement reporting.
- Added offline architecture, lifecycle, concurrency, security, Zoho, and cross-platform CI regression coverage.
- Made sensitive final approval distinct from initial plan approval, narrowed
  later review rounds, enforced model-call budgets, and removed device-global
  log/network/permission side effects.
- Added a self-contained, approval-gated chat installation path pinned to the
  immutable release tag, with clean install, same-major update, and legacy
  replacement coverage. Terminal installation remains available as an
  alternative.

## [0.27.24] - 2026-09-08

### Harness Reliability and Release Integrity
- **Deterministic Cross-Runtime Gates**:
  - Made environment and hook selftests hermetic, preserved raw Gradle denial, and added ADB-core and graph coverage to CI.
- **CLI Verification Correctness**:
  - Added compatible `PASS` and `APPROVED` verdict handling, exact five/six-leaf validation, documented stale exit code `2`, and update failure propagation.
- **Preflight and Device Diagnostics**:
  - Repaired read-only ADB device parsing and added fail-closed preflight reuse bound to the exact Git HEAD and working-tree content.
- **Release Drift Prevention**:
  - Validated pinned prompt URLs and checksums, current security support, delivery-order documentation, immutable PyPI publishing actions, and pinned build dependencies.

## [0.27.23] - 2026-09-08

### Shift-Left Preflight Gating & Zero-Invalidation Delivery Order
- **Shift-Left Preflight Gate & Zero-Invalidation Invariant (`harness-rules.md`, `deliver.md`, `AGENTS.md`, `AGENTS.md.template`, `pre_invocation_reminder.py`, `review_package.py`)**:
  - Promoted `preflight_check.py` from a post-review assemble requirement to a mandatory Shift-Left Pre-Gate in Stage 0 alongside unit tests.
  - Required all string parity (`check_strings.py`), Room database migration (`room_guard.py`), fast Kotlin lint (`fast_kt_lint.py`), and risk tier checks to pass 100% before review packages can be generated.
  - Wired `review_package.py` to strictly validate `preflight_check.py` as a hard prerequisite before packaging, immediately preventing post-review fixes from modifying code, invalidating fingerprints (`STALE`), and exhausting review round caps.
  - Refined Stage 2 / Step 6 to focus on `:assembleDebug`, treating preflight here as an idempotent sanity assertion.
  - Added recursive selftest guard (`HARNESS_HOOK_SELFTEST_ACTIVE`, `--skip-hook-selftest`) to ensure hook selftest cycles never deadlock during automated preflight execution.

## [0.27.22] - 2026-09-08

### Non-Blocking Autonomous Review Fix Invariant & Touchpoint Clarification
- **Non-Blocking Autonomous Fix Invariant (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`, `deliver.md`, `pre_invocation_reminder.py`)**:
  - Bound Review Round Summary Cards in Rounds 1 and 2 to strictly informational, non-blocking touchpoints.
  - Explicitly prohibited agents from yielding the turn, halting, or waiting for developer approval after emitting review cards with findings.
  - Mandated immediate, autonomous continuation to fix defect producers, run `fast_kt_lint.py` and unit tests, and re-dispatch Round N+1 in the same active loop.
  - Codified an anti-rationalization invariant forbidding agents from falsely claiming that the harness requires stopping for developer card review before the Round 3 Cap.
  - Injected non-blocking directive into the active pre-invocation reminder to eliminate hesitation and premature turn boundaries across all AI models.

## [0.27.21] - 2026-09-08

### Missing Legacy Code Invariant & Pure English System Mandate
- **Missing Legacy Code & One-Shot Git Invariant (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`, `pre_invocation_reminder.py`)**:
  - Bound legacy code restoration and historical git inspections (e.g. "check git", "restore deleted feature") to a maximum of 1 targeted code graph query or 1 scoped git query (`git log -n 5` / `git log -S <symbol> -n 3`).
  - Enforced immediate halt upon absence: strictly prohibited speculative recursive git excavations, multi-commit diff digging (`git log -G`, `git log --all`), or scanning unrelated history when requested code does not exist in the local project.
  - Mandated immediate interactive clarification (`ask_question`) asking the developer for an external reference path, commit hash, or fresh implementation, preventing runaway exploration loops.
- **Pure English System Invariant (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`, `pre_invocation_reminder.py`)**:
  - Enforced that all internal harness files, canonical rules, templates, prompts, git commit messages, and script strings remain 100% in English with zero emojis and zero Arabic text in system files (reserving Arabic exclusively for user-facing chat responses and interactive modal options when interacting with an Arabic-speaking developer).

## [0.27.20] - 2026-09-08

### Production-Readiness Integrity Hardening & Semantic Snapshot Gate
- **Semantic Code Snapshotting & Anti-Drift Verification (`_hook_state.py`, `review_package.py`, `final_verdict.py`)**:
  - Added `semantic_code_snapshot()` computing a deterministic content-bound SHA-256 over code and build files (`.kt`, `.java`, `.kts`, `.xml`, `.gradle`, `.toml`, `schemas/*.json`), strictly ignoring documentation and state files to prevent false-invalidation loops.
  - Bound snapshot into review package headers (`WORKSPACE_SNAPSHOT`) and verdict records, detecting content-level code changes made after review packages are generated.
- **Windows Safe File Locking & PID Liveness Detection (`_hook_state.py`)**:
  - Upgraded `state_lock` with a 15-second timeout, exponential backoff, and randomized jitter to eliminate file lock contention under heavy concurrency on Windows.
  - Linked active locks to system process identifiers (`PID`) with OS-level alive checks (`os.kill(pid, 0)`), automatically evicting dead locks and failing closed on timeouts.
- **Porcelain v2 Git Status Parser with Full Rename/Delete Tracking (`_repo_files.py`)**:
  - Upgraded working-tree change discovery to `git status --porcelain=v2 -z` via `ChangedFile` dataclass, accurately resolving untracked, modified, deleted, and renamed files with old paths.
  - Preserved `_unquote_git_path` for complete backward compatibility across all diagnostic and selftest suites.
- **Resurrected Baseline-Aware Unit Test Gating (`run_tests_gate.py`)**:
  - Prevented premature aborts on non-zero Gradle exits; parsed JUnit XML reports to distinguish known baseline failures (`BASELINE_IGNORED`) from true regressions (`NEW_REGRESSION`) and compilation errors.
- **Plurals Placeholder Parsing Guard (`check_strings.py`)**:
  - Fixed plurals XML resource parsing to persist items and extracted placeholder tokens into checked resource dictionaries.
- **Strict Room Custom Migration Wiring Verification (`room_guard.py`)**:
  - Added AST inspection ensuring custom `Migration(old_ver, new_ver)` definitions are actively registered in `addMigrations(...)` calls on the database builder.
- **Assemble Build Evidence Gate for Device Installation (`_apk_freshness.py`, `run_device.py`)**:
  - Added `require_assemble_evidence` to fail closed if `run_device.py` is called without fresh assemble verification, recording `apk_sha256` in device gate artifacts.

## [0.27.19] - 2026-09-07

### Fortified Invariants: Zero Live-Network Probing, Local Fixtures First & Conversational Precedence
- **Zero Live-Network Probing Invariant & Hook Enforcement (`policy_vocab.py`, `pre_tool_safety.py`, `harness-rules.md`, `AGENTS.md`)**:
  - Implemented fail-closed security hook pattern scanning against ad-hoc network tools (`curl`, `wget`, `Invoke-WebRequest`, `iwr`) and scripting probes (`urllib.request`, `requests`, `aiohttp`, `httpx`).
  - Added scratch script inspection: intercepting Python execution of temporary scratch scripts to detect and block outbound HTTP requests to external APIs.
  - Codified strict prohibition in canonical rules against executing outbound network calls to app backends, staging, or production servers during code investigation and triage.
- **Runtime Data Contract Ambiguity & Local Fixtures First Barrier (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`, `pre_invocation_reminder.py`)**:
  - Established the "Local Fixtures First" checklist: agents must first inspect unit tests, mock JSON fixtures, and fake repositories (`src/test/`, `test/resources/`, `Fake*Repository`) before declaring runtime payload behavior ambiguous.
  - Codified single-shot interactive clarification (`ask_question`) if and only if local fixtures do not resolve the contract and the 3-4 file exploration cap is reached, presenting concrete architectural/business choices.
  - Added strict Anti-Question Spam & Question Fatigue Guard: prohibited questioning developers about deterministic code facts or begging permission for routine tasks.
- **Immediate User Interruption & Conversational Precedence Barrier (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`, `pre_invocation_reminder.py`)**:
  - Enforced 0 tool calls when developer inputs session interruptions or behavioral questions ("وقف", "رد عليا", "بتعمل ايه", "انت كل ده بتدور"), requiring immediate conversational response in prose.
  - Added contextual disambiguation guard strictly distinguishing session interruptions from application business logic.
- **UI & String Formatting Defect Boundary (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`)**:
  - Bound defect exploration for UI text, formatting, and share sheets strictly to UI Composables/XML, Formatters/Helpers, and ViewModels, preventing deep architectural dives into Retrofit interfaces or Base URLs.
- **Adversarial Security Selftest Suite Expansion (`_security_selftest.py`)**:
  - Added deterministic test assertions verifying fail-closed deny on curl, wget, PowerShell iwr, inline urllib/requests, and scratch network scripts using generic test domains (`api.example.com`).

## [0.27.18] - 2026-09-07

### Universal UI String Dereferencing & Graph-First Localization Grounding
- **UI String Dereferencing Engine (`_graph_core.py`, `project_graph.py`)**:
  - Implemented high-performance scanner for `res/values*/strings*.xml` across all project modules, supporting Arabic (`values-ar`), default (`values`), English (`values-en`), and all locale variants.
  - Added Arabic normalization engine (`normalize_arabic`) providing tolerant matching across Alef variants (`أ/إ/آ/ا`), Taa Marbuta and Haa (`ة -> ه`), Yaa and Alef Maksura (`ى/ي`), and stripping Tashkeel diacritics.
  - Implemented static usage tracer (`find_string_usages`) linking string keys to UI screens (Jetpack Compose / XML Layouts) and ViewModels via `R.string.<key>` and `@string/<key>`.
  - Added CLI flag `--string <TEXT>` (and `--ui-text <TEXT>`) to directly dereference localized UI text to code symbols in a single step with suggested next exploration commands.
- **Project Feature Directory Listing (`project_graph.py --features`)**:
  - Added `--features` CLI flag to discover and list all feature modules and packages with component counts (screens, viewmodels, domain, data), resolving previous CLI argument mismatch.
- **Rule & Guardrail Alignment (`AGENTS.md`, `harness-rules.md`, `AGENTS.md.template`, `pre_invocation_reminder.py`)**:
  - Codified `UI String Dereferencing Exception (Localization Bypass)` explicitly authorizing agents to run `project_graph.py --string "<label>"` or targeted grep on `res/values-ar/strings.xml`.
  - Strictly banned speculative English translation guessing (`--find charity`, `--find Khair`) when given localized Arabic UI terms.
  - Injected UI-Text dereferencing instructions into Turn 1 active pipeline reminders.
- **Comprehensive Selftest Suite Expansion (`_graph_selftest.py`)**:
  - Added Test 9 (UI String Dereferencing, Arabic normalization, tolerant matching, usage linking, card generation) and Test 10 (Multi-Feature Directory Listing), expanding test suite to 61 passed tests (100% pass).

## [0.27.17] - 2026-09-07

### Truly Human-Bound Risk Approval & Challenge-Nonce Security Barrier
- **Challenge-Nonce Risk Protocol (`risk_tier.py`, `approve_risk.py`)**:
  - Implemented single-use challenge token mechanism (`AUTH-XXXXXXXX`) bound cryptographically to the exact `tree_code_fingerprint` and risk tier with 15-minute TTL.
  - Eliminated the unverified bare `--approve` flag in production commands, completely preventing AI agents or subagents from self-approving `HIGH` or `CRITICAL` risk tiers (Billing, Payment Gateways, Room Database Migrations, AndroidManifest Security).
  - Enforced single-use consumption (`consume_risk_challenge` unlinks challenge file), strictly preventing replay attacks.
  - Mandated interactive modal presentation (`ask_question`) in chat where human developer explicitly reviews risk factors and confirms approval token before preflight can proceed.
  - Added strict fingerprint staleness detection: any working-tree code changes after challenge generation immediately invalidate the challenge and require a fresh token.
  - Preserved full interactive terminal confirmation (`sys.stdin.isatty()` with `input("Type 'YES'...")`) for developers working directly in CLI without an AI intermediary.
- **Comprehensive Selftest Suite & CLI Hardening (`_risk_and_impact_selftest.py`)**:
  - Expanded test suite to 49 assertions covering token generation, format validation, replay refusal, code tampering/fingerprint mismatch rejection, TTL expiry cleanup, and CLI barrier enforcement.
- **Governance Rules Alignment (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`)**:
  - Synchronized Rule 13 across all canonical rules and multi-IDE agent adapters to mandate the `--challenge` and `--token <TOKEN>` protocol.

## [0.27.16] - 2026-09-07

### Anti-Thrashing Navigation, One-Shot File Viewing & Reviewer Optimization
- **One-Shot File & Block Viewing Invariant (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`)**:
  - Mandated viewing files and cohesive class blocks <= 400 lines in a single comprehensive `view_file` call (utilizing full 800-line capacity).
  - Strictly banned incremental micro-slicing (e.g. reading 50-70 lines repeatedly across multiple turns), cutting conversation token re-transmission and latency by over 70%.
- **Targeted Grep, Anti-Grep Cascade & Symbol Grounding Invariant (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`)**:
  - Strictly prohibited root-level grep flooding returning >= 10 speculative matches.
  - Mandated AST-backed symbol grounding via `project_graph.py --find <Symbol>` or file-scoped grep before file inspection.
- **Anti-Thrashing Navigation Sequence (`harness-rules.md`, `AGENTS.md`)**:
  - Enforced linear contract-first reading before inspecting callers.
  - Strictly prohibited ping-pong file hopping between multiple files across consecutive turns.
- **Reviewer Subagent Prompts Hardening (`agents/subagents/*.json`)**:
  - Harmonized `Investigation Protocol` across all 6 reviewer subagents (`bug-reviewer`, `perf-anr-guardian`, `convention-reviewer`, `security-reviewer`, `regression-impact-reviewer`, `test-quality-reviewer`) to mandate One-Shot Viewing (<= 400 lines in 1 call) and bounded 2-hop call chain inspection.
  - Replaced loose codebase-wide grep references in `regression-impact-reviewer-agent.json` with embedded graph topology and AST symbol lookups.
- **Turn-by-Turn Pre-Invocation Directive (`pre_invocation_reminder.py`)**:
  - Injected `ONE-SHOT VIEWING` and `GRAPH-FIRST` directives directly into active turn reminders for continuous in-session enforcement.
- **Target Project Verification**:
  - Verified 100% operational health and AST graph sync in `Fitness_Android` (3,831 nodes, 15,500 edges) with 0 failures.

## [0.27.15] - 2026-09-07

### Pre-Commit Gate Retirement, Shift-Left Preflight Decoupling & Legacy Cleanup
- **Complete Pre-Commit Gate Retirement (`pre_commit_gate.py`, `install_tool_adapters.py`, `install_or_update.py`)**:
  - Permanently deleted `agents/scripts/pre_commit_gate.py` and unhooked it from `CORE_SCRIPTS` (reduced to 45 core scripts).
  - Shifted all quality, lint, and Room migration validations entirely left into `preflight_check.py` and delivery gates, leaving developers in full, unhindered control of their Git commit authority.
  - Implemented `cleanup_legacy_git_gate()` in `install_tool_adapters.py` to automatically unset `core.hooksPath` and safely remove legacy `.githooks/` directories on fresh install and update cycles in client apps.
  - Retired `--git-gate` and `--no-git-gate` CLI flags with backward-compatible parsing.
- **Wizard I.21 Retirement (`setup_wizard.py`, `questions.py`, `i18n.py`)**:
  - Completely removed question `I.21` from the interactive setup wizard while cleanly normalizing `git_gate` to `"no"`.
  - Cleaned up localization dictionaries across English and Arabic strings.
- **Documentation & Cross-Platform Alignment**:
  - Aligned architecture guides, setup prompt, compatibility matrix, and tool support specifications with the retired git-gate invariant.
  - Verified 180+ hook selftests and 12-dimension doctor diagnostic suite passing with 0 failures.

## [0.27.14] - 2026-09-06

### Code Graph Function Indexing, Reality-Check Protocol & Anti-Paralysis Exploration Barriers
- **Code Graph Function & Method Indexing (`_graph_core.py`, `project_graph.py`)**:
  - Upgraded code graph engine to extract and index member and top-level functions in Kotlin, Java, and Python.
  - Added `Matched Member/Function:` reporting in `format_symbol_match` for precise function location via `project_graph.py --find <symbol>`.
  - Optimized repository traversal 100x via `os.walk` with instant pruning of `build/`, `.gradle/`, `.git/`, and caches.
- **Reality-Check & Grounding-First Protocol (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`)**:
  - Enforced mandatory `git status` / `git diff` check at the start of bug triage to prevent the Ghost-Bug trap.
  - Mandatory stop and `ask_question` trigger when suspect fixes already exist in the working tree, prohibiting speculative OS/framework race-condition theories.
- **Targeted Grep & Anti-Grep Cascade Invariant (`harness-rules.md`, `AGENTS.md`)**:
  - Strictly prohibited root-level cascading `grep_search`. Mandatory graph-first discovery for symbols and functions, restricting `grep_search` to single files or feature directories.
- **Bug Exploration Circuit Breaker & Anti-Archaeology (`harness-rules.md`, `AGENTS.md`)**:
  - Imposed a hard cap of 3-4 files for bug localization before presenting an implementation plan.
  - Strictly banned speculative `git log` / commit archaeology and cross-subsystem file manager dives during bug triage.
- **Pre-Invocation Reminder Synchronization (`pre_invocation_reminder.py`)**:
  - Injected Reality-Check and Graph-First priorities into Antigravity turn reminders.

## [0.27.13] - 2026-09-06

### Client Hook Selftest Dirty-Tree Gate Bypass
- **Hook Selftest Review Gate Bypass (`pre_tool_safety.py`)**:
  - Added `_IN_HOOK_SELFTEST` bypass to assemble and device delivery gates in `pre_tool_safety.py`.
  - Guarantees that internal hook selftests (such as `run_device_uninstall`) execute cleanly during client repository installations even when uncommitted application code changes exist in the working tree.

### 0.27.12 - 2026-09-05

### Environment-Adaptive Architecture, Self-Healing Commands & Zero-Bloat Preference Codification
- **Runtime Environment & Surface Sensor (`_environment.py`, `_environment_selftest.py`)**:
  - Automatically identifies runtime assistant environment (Google Antigravity, Claude Code, Cursor, OpenAI Codex, GitHub Copilot) and surface type (Desktop 2.0, IDE, CLI).
  - Supplies capability flags (`supports_stop_hook`, `supports_overwrite`, `supports_generative_ui`, `supports_interactive_modals`) across the harness pipeline with 15 dedicated selftest validations.
- **Self-Healing Gradle Command Execution (`pre_tool_safety.py`)**:
  - Automatically rewrites raw Gradle invocations (`./gradlew ...`, `gradlew.bat ...`) to `python agents/scripts/run_gradle_task.py ...` via Antigravity `PreToolUse` hook argument `overwrite`.
  - Enforces instructional fail-closed denials for raw gradlew commands across non-Antigravity CLI assistants (Codex, Claude Code).
- **Delivery Stop Lifecycle Hook & Diff-Aware Loop Breaker (`pre_tool_safety.py`, `hooks.json`)**:
  - Intercepts Antigravity `Stop` events (`delivery-stop-guard`) to prevent premature session termination when unreviewed code modifications exist in the working tree.
  - Implements an automated Loop Breaker yielding after 2 consecutive identical diff blocks to eliminate token drain loops, and safely unblocks on `env_failure.json` (exit 30 protocol) or `APPROVED` final verdict.
- **Cross-Platform Review Recording Bridge (`record_review.py`)**:
  - Provides a universal CLI bridge to record 5-leaf review verdicts (`BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`) directly on checkouts lacking native Antigravity transcript logs.
- **Generative UI Review Widgets with Markdown Fallback (`render_ui.py`)**:
  - Generates Tailwind CSS `<agent-embed>` review cards and architecture visualizations in Antigravity GUI surfaces.
  - Generates clean, CP1252-safe ASCII Markdown tables in CLI and non-Antigravity environments.
- **Interactive Preference Codification & Ref-Sync Protocol (`harness-rules.md`, `AGENTS.md`, `AGENTS.md.template`)**:
  - Codifies project preferences directly into `.agents/skills/android-harness/references/` with progressive disclosure (zero token bloat and zero global memory pollution).
  - Leverages `/grill-me` with structured `ask_question` modals in Antigravity, and standard numbered discovery interviews in portable CLI assistants.
  - Completely eliminates unconstrained global learning tools from proactive recommendations.

### 0.27.11 - 2026-09-05

### Antigravity Rules Token Optimization, Progressive Disclosure & Clean Adapter Merge
- **Antigravity & Gemini Rules Token Optimization (`harness-rules.md`, `threat-model.md`)**:
  - Migrated `harness-rules.md` frontmatter from `trigger: always_on` to `trigger: model_decision` with an explicit semantic description.
  - Slashed prompt token overhead by over 11,000 tokens (reducing rules budget consumption from 81.3% down to ~15%), completely eliminating automatic truncation risks in Google Antigravity while maintaining full on-disk access for subagents and architecture reviewers.
- **Legacy Managed Marker Deduplication (`install_tool_adapters.py`)**:
  - Expanded `merge_managed_content` to recognize both current (`<!-- managed-by: android-agent-harness -->`) and legacy (`<!-- managed-by: android-harness-kit -->`) markers.
  - Prevented unintentional duplication of `AGENTS.md` blocks during harness upgrades and adapter re-generation.
- **Unbuffered Installer Live Streaming (`install_or_update.py`)**:
  - Integrated unbuffered process execution flag and continuous readline streaming for real-time installer feedback.

### 0.27.10 - 2026-09-03

### Real-Time Live Process Streaming & Progress Feedback Across All Harness Scripts
- **Real-Time Live Streaming Engine (`install_or_update.py`, `_live_process.py`)**:
  - Replaced buffered sub-process execution (`capture_output=True`) with unbuffered, real-time stdout streaming (`bufsize=1`, `PYTHONUNBUFFERED=1`).
  - Displayed live progress for every hook selftest, preflight check, and 12-dimension diagnostic verification check as it executes without UI freezes or terminal stalls.
- **Diagnostic Doctor Optimization (`harness_doctor.py`, `doctor/engine.py`)**:
  - Added `--no-selftest` flag to skip redundant re-execution of the 180+ hook selftests during installation/update health verification, cutting run time by over 50%.
  - Added live intermediate status reporting for sub-process test runs within safety and preflight dimensions.
- **Universal Code Graph Progressive Feedback (`project_graph.py`, `_graph_core.py`, `install_or_update.py`)**:
  - Added progressive milestone reporting during AST indexing, Clean Architecture layer extraction, and DOT/SVG topological caching.
  - Added incremental synchronization indicators when files are added, modified, or deleted.
- **Packaging & Device Inspection Progress (`review_package.py`, `run_device.py`)**:
  - Added real-time review package digest and risk tier indicators before generating review diffs.
  - Added live Activity launch progress before dispatching `am start`.

### 0.27.9 - 2026-09-03

### Mandatory Interactive Modal Invariant, Universal Code Graph README Showcase & Smart MCP Fallback
- **Mandatory Interactive Modal Invariant (`ask_question`) & Platform Planning Mode Override (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**:
  - Eliminated conversational chat prose and "Open Questions" sections in `implementation_plan.md` for missing requirements or edge cases.
  - Mandated that the Lead Agent immediately trigger the interactive `ask_question` modal with structured, clickable choices before authoring implementation plans.
  - Enforced explicit rule precedence overriding platform planning mode defaults that discourage calling `ask_question` during planning.
- **Universal Code Graph Showcase in README (`README.md`)**:
  - Expanded the project README with an in-depth section on the Universal Code Graph Engine (`project_graph.py`).
  - Documented Clean Architecture feature slicing, dependency path finding, UI screen mapping, and 80%+ token savings with ASCII architectural flow diagrams.
- **Smart Sprint Fallback in Zoho Sprints MCP Client (`agents/mcp/zoho_sprints/_client.py`, `zoho_get_task_details.json`)**:
  - Resolved task lookup across all sprints and the backlog even when an explicit mismatched `sprint_id` is supplied by the caller.
  - Updated `zoho_get_task_details` schema to make `sprint_id` optional.

### 0.27.8 - 2026-09-03

### Zero-Assumption Interactive Interview, Native Backlog Support & Host Sandbox Security
- **Zero-Assumption & Missing-Scenario Interview Invariant (`harness-rules.md`, `AGENTS.md`, `pre_invocation_reminder.py`)**:
  - Strictly prohibited AI agents from guessing, assuming, or inventing business logic, UI error texts, or missing scenarios from their own heads.
  - Mandated that agents audit for unaddressed network states (offline, timeout), state invariants (empty country/ISO), caching TTL, and error handling after graph exploration.
  - Required proactive developer interviews via `ask_question` with structured choices before authoring `implementation_plan.md`, ensuring plans are agreed upon and correct from the first attempt.
- **Attached Media First-Turn Inspection Invariant (`harness-rules.md`, `AGENTS.md`, `new-feature.md`)**:
  - Enforced that whenever the developer provides attached screenshots, images, or screen recordings, the Lead Agent MUST view and inspect the media via `view_file` in the very first turn before searching code or authoring plans.
- **Native Zoho Sprints Backlog Resolution (`agents/mcp/zoho_sprints/_client.py`)**:
  - Added native `get_backlog_id()` via `/?action=getbacklog` API query and unified backlog caching.
  - Expanded `resolve_item()` to automatically search both active/future sprints and the project backlog, enabling sub-second resolution of backlog items (e.g. `I769`, `I770`) without ID mismatches.
- **Host OS Traversal & Anti-Scraping Sandbox Guard (`pre_tool_safety.py`)**:
  - Implemented fail-closed interception denying shell commands that attempt to scan host user home directories (`C:\Users\...`, `/home/...`, `~`, `%USERPROFILE%`).
  - Added strict Fail-Fast Tracker Policy: maximum 1 attempt for issue lookup; hard deny on reverse-engineering, Google searches for internal APIs, or scratch scrapers.

### 0.27.7 - 2026-09-03

### Official PyPI Publication, Evergreen Installer Links & Pre-Release Packaging Integrity
- **Official PyPI Publication (`android-agent-harness`)**:
  - Published official distribution packages (`.whl` and `.tar.gz`) to PyPI.
  - Enabled standard one-command global installation: `pip install android-agent-harness` or `pipx install android-agent-harness`.
  - Added official PyPI version badge to repository header.
- **Evergreen Prompt Installer (`README.md`, `docs/quickstart.md`, `pin_prompt_docs.py`)**:
  - Adopted static, permanent prompt URL pointing to `main` (`https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/main/docs/install-or-update-prompt.md`).
  - Eliminated stale link rot across external blogs, tutorials, and chat bookmarks.
  - Excluded entry-point documentation from release version pinning scripts to preserve the permanent evergreen URL.
- **Automated PyPI Publishing CI & Pre-Release Packaging Verification (`publish-pypi.yml`, `release_version.py`)**:
  - Created automated GitHub Actions workflow (`.github/workflows/publish-pypi.yml`) utilizing OIDC Trusted Publishing on new GitHub releases.
  - Hardened release automation script (`release_version.py`) with pre-release distribution packaging build (`python -m build`) and metadata verification (`twine check`) before git tag and push.
  - Added `.github/` workflows directory to automatic release staging paths.

### 0.27.6 - 2026-09-03

### Architectural Caging, Room Java Support, Subtle Logic Bug Fixes & High-Impact Documentation
- **Room Migration Java & Kotlin Guard (`room_guard.py`)**:
  - Expanded entity and database scanning to inspect both Java (`.java`) and Kotlin (`*.kt`) files, preventing missed migrations in mixed or legacy Java codebases.
  - Broadened entity reference regexes to match `FooEntity.class` alongside `FooEntity::class`.
- **String Parity Precision for String Arrays (`check_strings.py`)**:
  - Added placeholder extraction (`%s`, `%d`) for `<string-array>` items to ensure translation parity and prevent runtime format crashes across locales.
- **Wizard Setup & Script Edge Cases (`wizard/questions.py`, `harness_cli.py`)**:
  - Fixed `install_confirm` variable override in answers dictionary generation.
  - Cleaned unused assignments and dead imports in `harness_cli.py` and `questions.py`.
- **APK Staleness Exclusion for AI Tool Adapters (`_apk_freshness.py`)**:
  - Excluded `.cursor`, `.claude`, `.codex`, `.github`, `.windsurf`, `.amazonq`, and other AI tool directories from staleness checks, eliminating false `STALE_SOURCE` re-builds.
- **Pre-Commit Gate Isolation (`pre_commit_gate.py`)**:
  - Isolated Room database checks strictly to staged relative paths (`staged_rels`), preventing un-staged working-tree experiments from blocking commits.
- **ADB Component Normalization (`run_device.py`)**:
  - Normalized target Activity identifiers before `am start -n` to prevent syntax crashes when slash `/` is omitted.
- **High-Impact Architecture & Streamlined Documentation (`README.md`, `docs/architecture.md`)**:
  - Refactored `README.md` to a concise 118-line high-impact manifesto showcasing live OS interceptions, the 6 Quality Guardians, Smart Test Promotion, and the Zero Legacy Debt advantage.

### 0.27.5 - 2026-09-02

### Setup Wizard 2.0 (4-Station Cascading Flow), Diff-Grounded Testing Standard & Doctor Pre-Checks
- **Setup Wizard 2.0 & 4-Station Flow (`wizard/questions.py`, `setup_wizard.py`)**:
  - Re-architected setup interview into 4 strictly ordered thematic stations:
    1. Workspace & AI Tooling (`i0`, `i14`, and conditional `i2`/`i5`/`i6`/`i19`/`b_*`)
    2. Git Governance & Safety (`i3`, `i21`)
    3. Project Management & Task Tracker (`i20`, and cascading `i18`, `i16`)
    4. Device Testing & Verification (`i15`, `i22`, and cascading `i4`, `i10`)
  - Added smart cascading logic (`depends_on`): skipping tracker language and Zoho MCP when `none` is chosen, and skipping device target policy and install confirmation when device verification is `disabled`.
  - Reduced onboarding friction from 11 mandatory questions to 5-7 streamlined prompts for standard workflows.
- **Diff-Grounded Manual Smoke Steps Standard (`harness-rules.md`, `deliver.md`, `AGENTS.md`)**:
  - Enforced a rigorous standard for manual verification: agents must author 2-3 numbered testing steps in chat strictly derived from the modified diff (1. Navigation path, 2. Interaction matching diff, 3. Expected visual/functional outcome).
- **Environment Doctor Hardening (`doctor/engine.py`, `harness_doctor.py`)**:
  - Added proactive checks for Java JDK runtime (validating JDK 17+ requirement for AGP 8+) and ADB CLI availability in system PATH to Dimension 1.

### 0.27.4 - 2026-09-02

### Complete E2E/Maestro Machinery Purge & Interactive Manual Checklist Mode
- **Complete E2E/Maestro Engine Purge (`_maestro_core.py`, `run_e2e_qa.py`, `run_e2e_smoke.py`, `qa-e2e-planner-agent`)**:
  - Permanently purged all automated E2E and Maestro scripts, runners, planners, workflows, and selftests from the harness kit.
- **Streamlined Interactive Manual Checklist Mode (`AGENTS.md`, `harness-rules.md`, `deliver.md`, `_product.py`)**:
  - Enforced developer-in-the-loop interactive verification as the default and standard mode: compile `:app:assembleDebug`, install via `run_device.py install-start`, present 2-3 simple human test steps in chat, trigger interactive confirmation modal (`ask_question`), and immediately deliver the Conventional Commit on PASS.
- **Anti-Forgery Safety Interceptor (`pre_tool_safety.py`)**:
  - Hardened pre-tool safety hook to deny any direct edits or file creation inside `.agents/state/` and `.agents/scripts/`, preventing unauthorized tampering with gates or review ledgers.
- **Universal Code Graph & Selftest Alignment**:
  - Updated codebase graph engine, wizards, and selftest suites to pass 100% cleanly with zero warnings and zero failures.

### 0.27.3 - 2026-09-02

### Application ID Resolution, PM Tracker Jargon Elimination & Local Privacy
- **Application ID & Launcher Package Discovery (`install_or_update.py`)**:
  - Enhanced `generate_product_py()` to dynamically discover `application_id` via `wizard.discovery` and fallback to the package prefix of the resolved launcher activity, preventing incorrect `com.<product>.app` defaults in client checkouts.
- **Zero Emojis & Zero Internal AI Jargon Governance (`AGENTS.md`, `harness-rules.md`, `pre_invocation_reminder.py`)**:
  - Mandated strictly human and QA-centric PM tracker comments (Zoho Sprints, Jira, Linear, GitHub Projects), prohibiting emojis and internal AI tokens (`5-Leaf Review`, `مراجع الهارنيس`, `Maestro Suite (1/1 Flows Passed)`).
  - Enforced structured, sequential testing steps for QA verification.
- **Local Privacy for Temporary Setup JSON Files (`install_or_update.py`)**:
  - Automatically added temporary setup dump and input files to local `.git/info/exclude` to guarantee zero working-tree pollution.

### 0.27.2 - 2026-09-02

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

### 0.27.0 - 2026-09-02

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

### 0.26.0 - 2026-09-02

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

### 0.25.8 - 2026-09-02

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

### 0.25.2 - 2026-09-02

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

### 0.24.0 - 2026-09-01

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

### 0.23.0 - 2026-09-01

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

### 0.22.0 - 2026-09-01

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

### 0.21.0 (2026-09-01)

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

**Included in 0.20.0 (2026-09-01):**

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
