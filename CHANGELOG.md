# Changelog

All notable changes to the **Android Harness Kit** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.10.8] - 2026-08-25

### Git Working Tree Cleanliness: Automatic `--assume-unchanged` for Tracked Hooks
- **Tracked Hook Isolation (`install_tool_adapters.py`, `setup_wizard.py`)**: When the pre-commit quality gate is installed or updated on repositories that previously had tracked hook files, the kit now automatically executes `git update-index --assume-unchanged .githooks/pre-commit`.
- **Zero Dirty Changes**: Guarantees that local hook overwrites never show up as uncommitted changes (`M .githooks/pre-commit`) in developer Git status or IDE change lists, even if `.githooks/` was committed to the repository history by team members in the past.

---

## [0.10.7] - 2026-08-25

### Update & Setup Determinism: Strict Execution Order & Modal Hardening
- **Strict Porting Sequence (`docs/update-prompt.md`, `docs/setup-prompt.md`)**: Enforced a strict execution order (copy engine -> populate `_product.py` and tool adapters -> run selftest/doctor). Prevents premature hook selftest failures caused by unported placeholder constants.
- **Update Modal Elimination (`docs/setup-prompt.md`, `docs/update-prompt.md`)**: Scoped domain references approval modals (`ask_question`) strictly to first-time installations, completely eliminating redundant modal interruptions during update workflows where references are already preserved from backup.
- **Single Diagnostic Execution**: Hardened instructions to prevent duplicate background task spawning during diagnostics.
- **Local Hooks Privacy Note**: Clarified that `.githooks/` is automatically excluded in `.git/info/exclude` to preserve clean shared team working trees.

---

## [0.10.6] - 2026-08-25

### Team Cleanliness: Automatic `.git/info/exclude` for `.githooks/`
- **Automatic Local Git Exclusion (`install_tool_adapters.py`, `setup_wizard.py`)**: When the staged pre-commit quality gate is installed or configured, `.githooks/` is now automatically registered in `.git/info/exclude`.
- **Zero Team Friction**: Pre-commit hooks remain active and protective locally on the individual developer's machine without polluting the shared git working tree, forcing unwanted team commits, or modifying shared `.gitignore` files.

---

## [0.10.5] - 2026-08-25

### Established & Modern Codebase Reviewer Enhancement (Five-Leaf Review Gate)
- **Established & Legacy Codebase Adaptive Reviewers (`agents/subagents/`)**: Upgraded the Five-Leaf Review Gate prompts (`bug-reviewer-agent`, `perf-anr-guardian-agent`, `convention-reviewer-agent`, `security-reviewer-agent`, `regression-impact-reviewer-agent`) to seamlessly handle both established/legacy codebases (XML Views, ViewBinding, MVVM, Java platform types, multi-module) and modern architectures (Jetpack Compose, MVI, KMP).
- **Sharpened Quality Invariants**: Added explicit checks for Java/Kotlin nullability boundaries, `viewLifecycleOwner` vs `this` in Fragment LiveData observation, atomic `StateFlow.update { }`, `onDestroyView()` ViewBinding nulling, unhandled Coroutine crashes, deep links/intent exports, and multi-module core contract blast radius.
- **Architectural Rules Alignment (`harness-rules.md`)**: Aligned shift-left quality invariants to explicitly respect the target project's established architecture without forcing unadopted patterns.

---

## [0.10.4] - 2026-08-25
 
### Fix: Neutralize Kit-Shipped Placeholders in Installed-Mode Selftest
- **Neutralized kit-shipped example tokens**: Replaced `com.example` needles across kit-shipped files that legitimately contained illustrative code (`harness_doctor.py` fallback defaults, `new_feature_scaffold.py` dead template imports, `convention-reviewer-agent.json` example inline FQCN prompt illustration, and `harness-rules.md` example adb start command) with neutral `""` sentinels or generic `<APPLICATION_ID>` / `com.yourapp` tokens.
- **Installed needle scan integrity**: The `kit placeholder grep agents/` check in `_hook_selftest.py` now runs strictly against the entire installed `.agents/` tree without false positives on fresh installs, while continuing to catch real unported placeholders.

---

## [0.10.3] - 2026-08-25

### Fix: Selftest No Longer Crashes in Installed Checkouts
- **Installed-checkout awareness (`_hook_selftest.py`)**: Three probe groups introduced in v0.9.x/v0.10.x assumed the kit-root layout and crashed with `FileNotFoundError` / `ModuleNotFoundError` when run from an installed app checkout (which receives only `agents/`): (1) the grants-example consistency probe resolving `templates/gemini-runtime/`, (2) the `harness_cli.py` explain subprocess plus the pin-to-tag provisioning group importing `harness_cli`, and (3) the `scripts_dev/make_android_fixture` import. Each group now degrades to an explicit `OK (skipped - installed checkout)` line, matching the skip pattern the dispatcher test already used.
- **Fixture fallback for installs**: When `scripts_dev/` is absent, equivalent minimal fixture builders are defined inline so the flavor-discovery, multi-module, pre-fill, and doctor-remediation engine tests keep running everywhere instead of being skipped.
- **Robust git HEAD (`review_package.py`)**: `GIT_SHA` / ledger `git_sha` now accept only a valid 40-hex commit hash; outside a git repository they record an empty value instead of git's error text, keeping package headers and ledger comparisons sane in non-git contexts.
- **Verified in the reported failure scenario**: a simulation copying only `agents/` into a clean directory now completes with `Total test failures: 0`, zero tracebacks, and explicit skip lines.

---

## [0.10.2] - 2026-08-25

### Maintenance & Documentation Consistency
- Synchronized package metadata with `agents/VERSION` (`pyproject.toml` had drifted to 0.6.0) and added release-CI validation plus a selftest gate so the drift cannot recur.
- Removed stale runtime grants for the intentionally disabled feature scaffold and unused imports without removing public helper contracts.
- Aligned install/update/setup prompts, README, issue forms, and rollback documentation with tagged provisioning (never floating to main), current wizard questions (I.17-I.21), Copilot preToolUse hooks, and the default-on git gate.

---

## [0.10.1] - 2026-08-25

### Setup Answers Change Flow: Wizard Pre-Fill, Doctor Remediation & Documentation
- **Wizard Answer Pre-Fill (`setup_wizard.py`)**: Re-running the wizard (`setup_wizard.py ask`) now pre-fills the previously recorded answers — `existing_defaults()` maps `.harness-setup/answers.json` onto the question ids and each question shows `(current)` next to the recorded choice; Enter keeps it, typing a new number changes only that answer. Multi-select tool questions restore the stored `tools` list. EN/AR `defaults_note` announces the behavior.
- **Doctor Drift Remediation (`harness_doctor.py`)**: The Install Consistency dimension appends a remediation line pointing at the wizard whenever answers drift from `_product.py`/adapters, closing the "detected but unexplained" gap.
- **Dedicated Documentation (`docs/tool-support.md`)**: New "Changing setup answers after install" section covering the wizard (recommended), the non-interactive questions/write flow, and manual edits, with a doctor verification step. Documentation veracity sweep: CLI subcommand list now includes `explain` and pin-to-tag provisioning (`docs/architecture.md`), git gate documented as default-ON with `--no-git-gate` opt-out (README, `docs/architecture.md`), and the evidence footer requirement noted for manual reviews (`docs/tool-support.md`).
- **Selftests**: New regression groups `wizard answer pre-fill defaults` and `doctor drift remediation points to wizard`. Changelog consolidated (0.4.0 folded into the 0.5.0 entry) to hold the milestone cap.

---

## [0.10.0] - 2026-08-25

### Enforcement Parity & Red Team: Adversarial Security Suite, Copilot Hook Bridge, Fixture Generator, Threat Model
- **Adversarial Security Suite (`agents/scripts/_security_selftest.py`)**: New standalone red-team suite (23 deterministic, zero-network assertion lines) wired into `_hook_selftest.py` and CI. Covers chained/spaced/config-wrapped/base64-wrapped git mutations, homoglyph and full-path `git.exe` variants, review-package traversal (URL-encoded `%2e%2e`, `..\..\`, symlink escape), oversized hook stdin, malformed Claude Code bridge fuzz, malformed Copilot bridge fuzz, forged EVIDENCE footers, and secret leakage through the Zoho MCP install path. Every case must deny or fail closed.
- **GitHub Copilot Enforcement Bridge (`agents/scripts/copilot_pre_tool_safety.py`, `install_tool_adapters.py --copilot-hooks`)**: GitHub Copilot now enforces repository-level `preToolUse` hooks (`.github/hooks/*.json`, allow/deny decision JSON, fail-closed on crash). The bridge reuses the engine-subprocess pattern from `cc_pre_tool_safety.py`, accepting both the documented camelCase and the VS Code compatible snake_case payloads, and is registered under `.github/hooks/android-harness-pre-tool-use.json` with a bash|powershell matcher. `copilot-instructions.md.template` documents the hook and a best-effort fallback for hook-less checkouts.
- **Git Gate Default ON + Wizard I.21 (`install_tool_adapters.py`, `setup_wizard.py`)**: The staged pre-commit quality gate is now installed by default; `--no-git-gate` opts out. The setup wizard gains confirmation question I.21 ("Pre-commit git gate?") in EN/AR, recorded as `git_gate` in answers, printed in the answers summary, and emitted as `--git-gate`/`--no-git-gate` by `flags_from_answers`. Absent answers keep the new default (on).
- **Fixture Generator Promotion (`scripts_dev/fixtures/make_android_fixture.py`)**: The ad-hoc temp-project builders from the selftests are promoted into one reusable stdlib-only generator with `--profile classic|multimodule|flavors|kmp` that prints the fixture root. The heaviest selftest blocks (wizard flavor discovery, multi-module root discovery) now consume it — behavior-neutral, all existing assertions unchanged.
- **Threat Model Documentation (`SECURITY.md`)**: New "Threat Model & Mitigations" table mapping every attack class above to the exact test name that proves the mitigation; supported-versions rows now span 0.6–0.10. Core script inventory expanded from 32 to 34 (`_security_selftest.py`, `copilot_pre_tool_safety.py`).

---

## [0.9.0] - 2026-08-25

### Trust & Supply Chain: Pin-to-Tag Provisioning, Single Deny Vocabulary, Audit Log, Evidence-Backed Verdicts
- **Pin-to-Tag Kit Provisioning (`harness_cli.py`)**: The CLI no longer clones or floats to `main`. `ensure_kit` resolves the requested release (HARNESS_KIT_REF or the latest GitHub release tag), provisions a fresh checkout pinned to exactly `v<version>` via tag fetch + detached checkout, and asserts the checked-out `agents/VERSION` equals the requested version, failing closed with remediation commands on any mismatch. `refresh_kit` re-pins existing clones to an exact tag, keeps a pinned checkout when a tag is unreachable, and refuses to continue if the clone somehow sits on a named branch. `update` resolves the latest release tag from engine check data and never upgrades to a floating ref. `--kit` local-checkout override behavior unchanged.
- **Single Deny Vocabulary (`agents/scripts/policy_vocab.py`)**: Canonical frozensets for GIT_MUTATIONS, DEVICE_BOUND_ADB verbs, named EMULATOR_PATTERNS, DENIED_PM_OPS, FORBIDDEN_TOOLS, SHELL_INDIRECTION_PATTERNS, a homoglyph CONFUSABLES_MAP, and the static REASON_CODES table. `pre_tool_safety.py` now imports these (behavior identical); selftest proves the shipped `config.grants.example.json` allow/deny entries never contradict the vocabulary.
- **Append-Only Audit Log + `android-harness explain` (`pre_tool_safety.py`, `harness_cli.py`)**: Every `deny()`/`allow()` decision appends a sanitized JSONL record to `agents/state/audit_log.jsonl` — `{ts, decision, tool, reason_code, reason_short, cmd_sha256_12, conv_hint}` — never raw commands or secrets. The file caps at the last 1000 records (atomic rewrite under the state lock). New `android-harness explain [--last N]` subcommand prints recent decisions with human-readable labels from REASON_CODES.
- **Formal Review Package v2 (`review_package.py`, `_hook_state.py`)**: Packages now carry a structured header (`TASK_ID` from `$HARNESS_TASK_ID`/`--task`, `GIT_SHA`, `TREE_FINGERPRINT`, `GENERATED_AT`, `PACKAGE_SHA256` computed post-write over all preceding bytes) and print `HARNESS_PACKAGE_SHA256_12=` for the orchestrator. The review ledger records `git_sha`. Pre-v2 packages remain valid with a single stderr WARN line during this migration window.
- **Evidence-Backed Verdicts (`pre_tool_safety.py`, all 8 subagent templates, both review prompts)**: A leaf verdict only clears the delivery barrier when the reply carries `EVIDENCE pkg=<sha256_12> cites=<n>` matching the dispatched package (n file:line citations, or `cites=0` for a clean pass). Tokens without a footer — or footers with a wrong/missing pkg hash — are treated as not-yet-replied with an explanatory message. Gated behind `HARNESS_EVIDENCE_MODE=strict|legacy` (default strict; legacy preserves the token-only behavior for one migration window). Selftests cover forged tokens, wrong hashes, correct footers, and legacy parity.
- **Adversarial Fail-Closed Inputs (`pre_tool_safety.py`)**: NFKC + confusables normalization closes homoglyph/zero-width `git` variants, whitespace-collapsed mutation tokens, and `git -c k=v <mutation>` laundering; encoded/piped shell indirection (`| sh`, `sh -c`, base64 decode chains) is denied outright; hook stdin is capped at 5 MB. Core script inventory expanded from 31 to 32 (`policy_vocab.py`).

---

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
