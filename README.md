# Android Agent Harness

<div align="center">

[![Release](https://img.shields.io/github/v/release/rabee-elkholy/android-agent-harness?color=blue&label=release)](https://github.com/rabee-elkholy/android-agent-harness/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/rabee-elkholy/android-agent-harness.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero%20(stdlib%20only)-success.svg)](#zero-dependency-standard-library-runtime)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](#supported-environments)
[![Tests](https://img.shields.io/badge/tests-154%20deterministic%20passed-brightgreen.svg)](#verification--selftest)

**Deterministic local governance, proportional verification, and zero-compromise safety for AI-assisted Android development.**

*Autonomous AI speed with deterministic human authority — the zero-dependency, tamper-evident quality harness for Android engineering.*

[Guarantees](#core-guarantees) •
[Why This Exists](#why-this-exists-the-problem-with-raw-ai-agents) •
[Architecture](#architecture--how-it-works) •
[Quickstart](#quickstart) •
[Workflows](#task-lifecycle--workflows) •
[Supported AI Hosts](#supported-ai-hosts--enforcement-tiers) •
[CLI Reference](#cli-reference)

</div>

---

## Core Guarantees

1. **Deterministic Human Authority**: AI agents are strictly restricted to *read-only* discovery and planning. Implementation cannot begin without explicit developer approval recorded in `plan.json`.
2. **Zero Autonomous Git Mutations**: In client Android applications, the agent **never** stages, commits, resets, or pushes code. All modifications remain unstaged for the developer to inspect and commit.
3. **Deterministic Multi-Label Surface Classification**: Inspects Git diffs across 15+ Android-specific surfaces (`ROOM_SCHEMA`, `COMPOSE_UI`, `XML_UI`, `NAVIGATION`, `BILLING`, `AUTH`, `CRYPTO`, `BUILD_CONFIG`, `MANIFEST_PERMISSION`, etc.). Unclassified delivery-relevant changes are tagged `UNKNOWN` to prevent masking.
4. **Proportional Adaptive Review & Token Protection**: Eliminates runaway LLM costs. Micro-changes (simple docs, localized strings) bypass semantic reviewers. High and critical changes trigger up to five specialist reviewer agents within a strict caller budget.
5. **Cryptographically Bound Evidence Store**: Build results, test executions, and reviews produce append-only, tamper-evident evidence bound to the exact `delivery_snapshot_sha256`, repository identity, run ID, and Git branch.
6. **Unified APK Artifact-Set Integrity**: Multi-APK and split-APK builds are verified as a single cohesive artifact set. The exact hash is enforced across assemble, install, and device launch.
7. **Attributed Test Execution**: Separates newly introduced regressions from pre-existing baseline test failures, preventing false-positive gate failures.
8. **Zero Dependencies**: 100% Python standard-library (`pathlib`, `json`, `hashlib`, `subprocess`, `argparse`). No `pip install`, no third-party supply chain risks, and seamless operation across Windows, macOS, and Linux.

---

## Why This Exists: The Problem with Raw AI Agents

AI coding assistants (Claude Code, Gemini CLI, Cursor, Windsurf, Roo Code) are powerful, but when let loose on production Android codebases, they present recurring failure modes:

| Failure Mode in Raw AI Agents | How Android Agent Harness Solves It |
| :--- | :--- |
| **Silent Database Corruption**<br>Agents modify Room entity fields without declaring migrations or testing schema compatibility. | **Deterministic Room Guard** recursively parses `@Database`, entities, and `@Embedded` classes across files, blocking delivery unless valid migration paths are proven. |
| **Masked Regressions via Mixed Diffs**<br>An agent touches a critical class and a doc file simultaneously, tricking naive classifiers into treating the change as low-risk. | **Full-Coverage Classifier** inspects every delivery-relevant file. Any unclassified file is tagged `UNKNOWN`, forcing human decision rather than auto-approval. |
| **Runaway Token Costs**<br>Dispatching 5+ reviewer agents on a trivial one-line string update wastes millions of tokens. | **Adaptive Policy Matrix** dynamically selects reviewers based on actual change severity (Micro, Low, Medium, High, Critical). |
| **Git History Destruction**<br>Agents perform unexpected `git reset`, create untracked commits, or rebase active branches. | **Host Enforcement Hooks** block autonomous `git add`, `git commit`, `git push`, and `git reset` commands in client applications. |
| **Stale / Cross-Run Evidence Forgery**<br>An agent re-uses previous test output or verifies code on branch A that was built on branch B. | **Immutable Evidence Store** ties all evidence to repository identity, snapshot SHA-256, active branch, and single-use nonces. |
| **Device & Emulator Inconsistencies**<br>Agents install an APK to one device/user and launch on another, or launch outdated builds. | **Device Chain Verifier** ensures exact matching of artifact SHA-256, device serial SHA-256, and numeric Android user ID. |

---

## Architecture & How It Works

The harness operates as a deterministic finite state machine governing the interaction between the developer and the AI agent.

```mermaid
stateDiagram-v2
    [*] --> AWAITING_DEVELOPER_APPROVAL: workflow.py draft
    AWAITING_DEVELOPER_APPROVAL --> IMPLEMENTING: workflow.py approve + begin
    IMPLEMENTING --> VERIFYING: workflow.py prepare-verification
    VERIFYING --> BLOCKED: Findings or Test Failure
    BLOCKED --> IMPLEMENTING: workflow.py resume (same scope)
    VERIFYING --> READY_FOR_DELIVERY: workflow.py verify + complete
    READY_FOR_DELIVERY --> [*]: Developer commits & merges
```

### 1. Planning Phase (Read-Only)
The agent analyzes the codebase and generates an implementation plan (`plan.json`). The plan specifies the exact expected surfaces, modules, risks, and rollback steps. No file-writing tools or mutation scripts are authorized during this phase.

### 2. Approval & Transition
The developer reviews the plan. Once approved (`workflow.py approve`), a single-use cryptographic nonce is generated. `workflow.py begin` consumes the nonce and unlocks implementation authority.

### 3. Change Classification & Policy Selection
Upon completing code changes, `change_classifier.py` computes the Git diff and categorizes modifications across 15+ specialized Android surfaces:

- **Critical**: `BILLING`, `AUTH`, `SECURITY`, `SENSITIVE_DATA`, `CRYPTO`
- **High**: `ROOM_SCHEMA`, `MANIFEST_PERMISSION`, `BUILD_CONFIG`, `PUBLIC_API`, `NATIVE_CODE`
- **Medium**: `COMPOSE_UI`, `XML_UI`, `NAVIGATION`, `DEVICE_API`, `BUSINESS_LOGIC`, `NETWORK`, `COROUTINES`, `PERSISTENCE`
- **Low / Micro**: `DOCS`, `LOCALIZATION`, `RESOURCE_UI`, `TEST_ONLY`

`review_policy.py` derives the exact required verification gates and reviewer agents. If an unknown file is encountered, the policy fails closed to `USER_DECISION_REQUIRED`.

### 4. Specialist Reviewer Squad
When required by policy, isolated specialist subagents are dispatched:
- **`bug-reviewer-agent`**: Logic errors, edge cases, nullability, and lifecycle pitfalls.
- **`security-reviewer-agent`**: Data leakage, exported components, auth flaws, and cryptographic misuse.
- **`perf-anr-guardian-agent`**: Main-thread blocking, coroutine dispatchers, memory leaks, and recomposition loops.
- **`regression-impact-reviewer-agent`**: Behavioral regressions and API contract breakage.
- **`test-quality-reviewer-agent`**: Meaningful assertions, test independence, and mutation coverage.
- **`convention-reviewer-agent`**: Android & Kotlin clean architecture idioms.

### 5. Final Read-Only Verification
`final_verifier.py` recalculates the active delivery snapshot, repository identity, and Git branch. It independently verifies that all required evidence records are present, valid, untampered, and passing. The verifier is strictly read-only: it can confirm or reject delivery, but cannot write success state itself.

---

## Quickstart

### Prerequisites
- Python 3.10 or newer (standard library only).
- Android project managed by Git with a root Gradle Wrapper (`gradlew` or `gradlew.bat`).
- Android SDK and JDK (only when build or test gates are executed).

### Chat installation (recommended)
Open your Android project in your AI coding agent (Antigravity, Gemini CLI, Claude Code, Cursor, Windsurf, or Roo Code), and paste:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.19/docs/install-or-update-prompt.md and follow all instructions.
```

The agent will:
1. Discover your project structure in read-only mode.
2. Ask interactive configuration questions in chat.
3. Present a non-interference installation plan.
4. Wait for your approval, then provision the pinned kit into `~/.android-harness/kit`.
5. Run `doctor` to confirm that zero project source files were altered.

### Terminal installation (alternative)
Run directly from your command line:

```bash
# Clone the pinned harness release
git clone --depth 1 --branch v1.0.19 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git ~/.android-harness/kit

# Initialize inside your Android project
python ~/.android-harness/kit/harness_cli.py init --repo /path/to/android-project --kit ~/.android-harness/kit

# Verify configuration and environment health
python ~/.android-harness/kit/harness_cli.py doctor --repo /path/to/android-project
```

The installer configures `.agents` in your project and registers `.git/info/exclude` so that harness state never pollutes your repository's Git tracking.

---

## Task Lifecycle & Workflows

A standard task follows an explicit workflow:

```bash
# 1. Draft a task plan (Read-Only)
python .agents/scripts/workflow.py draft --repo . --task-id TASK-101 \
  --outcome "Implement user biometric authentication" \
  --expected-surfaces AUTH,CRYPTO,UI \
  --expected-modules :app

# 2. Developer approves the plan
python .agents/scripts/workflow.py approve --repo . --task-id TASK-101 \
  --source conversation --proof-reference MSG-4892 --enforcement-tier RULE_ENFORCED

# 3. Consume approval nonce and begin implementation
python .agents/scripts/workflow.py begin --repo . --task-id TASK-101

# ... AI agent implements code changes ...

# 4. Prepare verification (freezes delivery snapshot and policy)
python .agents/scripts/workflow.py prepare-verification --repo . --task-id TASK-101

# 5. For sensitive surfaces (auth/crypto/billing), developer confirms final snapshot
python .agents/scripts/workflow.py approve-sensitive --repo . --task-id TASK-101 \
  --source conversation --proof-reference CONFIRM-8391 --enforcement-tier RULE_ENFORCED

# 6. Execute gates and reviewers dictated by current-run.json
# e.g., run assemble, unit tests, room schema checks, or specialist reviews

# 7. Final read-only verification
python .agents/scripts/workflow.py verify --repo . --task-id TASK-101

# 8. Mark ready for delivery
python .agents/scripts/workflow.py complete --repo . --task-id TASK-101
```

Once marked `READY_FOR_DELIVERY`, the developer reviews the unstaged changes using standard Git tools (`git diff`, `git status`) and commits the work.

---

## Supported AI Hosts & Enforcement Tiers

The harness is host-agnostic and adapts to the security model of your coding environment:

| AI Host | Integration Mechanism | Enforcement Level | Protection Capabilities |
| :--- | :--- | :---: | :--- |
| **Google Antigravity / Gemini CLI** | Native `agents/hooks.json` | **Hard Enforced** | Pre-command execution interceptor blocks unauthorized commands, raw Gradle/ADB, and Git mutations. |
| **Claude Code** | Custom Tool Hooks & Settings | **Hard Enforced** | Native pre-tool execution hooks intercept file modifications and bash commands before execution. |
| **GitHub Copilot** | `.github/prompts` & PreToolUse bridge | **Hard Enforced** (where hook supported) | Native prompt command packs with pre-tool mutation guards. |
| **OpenAI Codex** | `AGENTS.md`, `CODEX.md`, `.codex/prompts` | **Rule Enforced** | Native slash-command prompt packs and instruction-enforced boundaries blocking unauthorized mutations and raw Gradle. |
| **Cursor & Windsurf** | System Rules (`.cursorrules` / `.windsurfrules`) | **Rule Enforced** | Behavioral policy constraints prevent unauthorized mutations; verified at final delivery gate. |
| **Roo Code / Cline** | Custom Modes & Instructions | **Rule Enforced** | Constrained persona workflows with policy gate enforcement. |
| **Terminal / CI** | Native Python CLI | **Deterministic** | Full deterministic command-line validation and policy verification. |

---

## CLI Reference

`harness_cli.py` manages the harness engine lifecycle across target repositories:

```bash
# Initialize harness into an Android project
python harness_cli.py init --repo /path/to/project --kit /path/to/kit

# Atomically upgrade an existing project to a newer kit version
python harness_cli.py update --repo /path/to/project --kit /path/to/new-kit

# Run diagnostic health check
python harness_cli.py doctor --repo /path/to/project --json

# Dry-run harness uninstallation
python harness_cli.py uninstall --repo /path/to/project

# Apply clean uninstallation (restores pre-install files safely)
python harness_cli.py uninstall --repo /path/to/project --apply

# Run the complete deterministic selftest suite
python harness_cli.py selftest --kit .
```

---

## Project Philosophy

> **Stricter proof, not heavier workflow.**
>
> Real Android production value > complexity + token cost + workflow friction + regression risk.
>
> **Stability first.**

- **No Vanity Metrics**: We do not assign arbitrary scores or bloat workflows with bureaucratic checkpoints.
- **Fail-Closed Safety**: If a device serial cannot be confirmed, a migration path cannot be verified, or an unknown surface is touched, the system halts and asks the developer.
- **Respect the Repository**: Your application code and Git tree belong to you. The harness never commits without permission and never touches files outside its designated boundaries.

---

## Verification & Selftest

Every commit and release is validated by a 154-test deterministic suite running on pure Python standard library:

```bash
# Run full deterministic test suite
python harness_cli.py selftest

# Run critical safety selftest suite
python agents/scripts/_critical_safety_selftest.py

# Validate release checksums and metadata
python scripts_dev/validate_release.py
```

---

## Contributing & Community

Contributions that preserve the stability-first principles, zero-dependency runtime, and deterministic verification model are welcome.

1. Review [Architecture Guidelines](docs/architecture.md) and [Threat Model](docs/threat-model.md).
2. Ensure runtime code remains **Python standard-library only**.
3. Verify that all 154 tests pass via `python harness_cli.py selftest`.
4. Open a pull request with clear rationale and regression coverage.

---

## License

This project is licensed under the [MIT License](LICENSE).
Copyright © 2026 Rabee Elkholy.
