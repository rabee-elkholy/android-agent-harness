<div align="center">

# Android Agent Harness

### A deterministic engineering control plane for AI-assisted Android development

Turn general-purpose coding agents into disciplined, predictable Android contributors with approval-gated workflows, Android-aware surface classification, AST-bounded context, and cryptographic evidence verification.

[![CI](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/rabee-elkholy/android-agent-harness?label=release)](https://github.com/rabee-elkholy/android-agent-harness/releases)
[![PyPI](https://img.shields.io/pypi/v/android-agent-harness)](https://pypi.org/project/android-agent-harness/)
[![Python](https://img.shields.io/badge/Python-3.10%E2%80%933.14-blue)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
[![Platforms](https://img.shields.io/badge/Linux%20%7C%20macOS%20%7C%20Windows-supported-success)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
[![License](https://img.shields.io/github/license/rabee-elkholy/android-agent-harness)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE)

[Why It Exists](#why-it-exists) · [Core Architecture](#core-architecture) · [Installation](#install) · [Canonical Lifecycle](#daily-workflow) · [Adaptive Risk Lanes](#5-tier-adaptive-risk-lanes) · [Deterministic Guards](#deterministic-android-guards) · [Documentation](#documentation)

</div>

---

## Overview

**Android Agent Harness** is a repository-local governance and verification control plane designed specifically for real-world Android codebases.

General-purpose coding agents (such as Claude Code, GitHub Copilot, Cursor, Windsurf, Roo Code, and Gemini CLI / Antigravity) excel at code generation but lack systemic understanding of Android platform constraints: Gradle variant matrices, Room schema migrations, localized XML string parity, multi-module dependency graphs, main-thread blocking hazards, and device deployment continuity. Left unguided, agents introduce runtime crashes, trigger unanchored grep cascades across large trees, or claim tests passed based on stale terminal logs.

The harness does not replace Android Studio, Gradle, ADB, Git, CI, or your AI model. Instead, it coordinates them through an immutable state machine:

- **Zero Python dependencies**: The entire runtime relies exclusively on the Python standard library (Python 3.10–3.14).
- **Approval-first execution**: Repository discovery is strictly read-only; implementation requires explicit developer sign-off on scope, risks, and verification criteria.
- **Strict cryptographic evidence binding**: Assemble, test, and device results are cryptographically bound to the final frozen change set. Stale or partial evidence fails closed.
- **Respects project ownership**: Git checkouts, commit history, and existing git hooks remain 100% developer-owned. Client application code is never auto-committed or staged by the harness.

---

## Why it exists

Raw coding agents frequently suffer from platform-specific failure modes when working on Android repositories. The harness provides deterministic boundaries for each:

| Failure Mode Without Harness | Deterministic Protection With Harness |
|:---|:---|
| **Eager, Unapproved Edits**<br>Agents start rewriting code before the developer agrees on scope or architectural boundaries. | **Explicit Approval Gate**<br>Discovery is read-only. A single-use cryptographic approval nonce is required before any source file can be modified. |
| **Context Window Saturation**<br>Dumping the whole repository or running broad grep sweeps wastes tokens and hallucinates dependencies. | **Bounded Project Intelligence**<br>Resolves the exact AST slice, symbol graph, or feature dependency sub-graph needed for the task (`task-context`, `project_graph.py`). |
| **Generic Diff Evaluation**<br>A mixed diff containing Room entities, XML strings, and Compose UI is treated as one generic code change. | **Multi-Surface Classification**<br>Simultaneously classifies Room schemas, localized resources, Compose state, Coroutine dispatchers, and Gradle builds independently. |
| **One-Size-Fits-All Verification**<br>Trivial documentation edits pay the cost of full Gradle builds, while sensitive changes skip critical checks. | **5-Tier Adaptive Risk Lanes**<br>Routes tasks dynamically: Tier 0 (Nano, <2s) skips builds, while Tier 4 (Critical Core) mandates Room migration gates and device verification. |
| **Hallucinated or Stale Verification**<br>Agents claim "build succeeded" or "tests passed" by referencing stale logs or unrelated runs. | **Cryptographic Evidence Fingerprints**<br>Evidence is hashed (`pkg=<sha12> cites=<n>`) and bound to the exact immutable snapshot of the working tree. |
| **Wrong APK Deployed to Device**<br>Builds generate multiple APKs (splits, variants); agents install older or mismatched binaries. | **Verified Artifact Set Identity**<br>Assemble, install, launch, and UI verification share one deterministic artifact fingerprint and device user identity. |
| **Silent Runtime Regressions**<br>Room migrations missing destructive fallback protection, or strings missing from `values-ar/strings.xml`. | **Deterministic Preflight Guards**<br>Fast, deterministic checks (<2s) catch broken migrations, missing translation keys, and formatting regressions before Gradle runs. |
| **Destructive Git & Tracker Mutations**<br>Agents rebase, reset unstaged work, or spam external project trackers. | **Developer Ownership & Safe Trackers**<br>Client git operations are developer-owned; issue tracker updates require explicit authorization and idempotency tokens. |

---

## Core Architecture

The harness coordinates discovery, execution control, and verification proof:

![Android Agent Harness Architecture Pipeline](https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/main/docs/assets/architecture-pipeline.svg)

### Lifecycle State Machine

Every task is governed by an immutable state machine persisted in `.agents/task-state/`:

```text
[INTAKE] ──► [DISCOVERY] ──► [PLAN_DRAFTED] ──► [AWAITING_DEVELOPER_APPROVAL]
                                                         │ (Developer Approves)
                                                         ▼
                                                  [IMPLEMENTING] ◄────────┐
                                                         │                │
                                                         ▼                │ (Resume on Fixes)
                                                   [VERIFYING] ───────────┘
                                                    │        │
                                   (Checks Pass)    │        │ (Findings / Blockers)
                                                    ▼        ▼
                                       [READY_FOR_DELIVERY] [BLOCKED]
                                                    │
                                                    ▼
                                               [DELIVERED]
```

1. **Discovery & Scoping**: Explores project topology, build variants, source sets, and symbols without modifying any application files.
2. **Task Planning & Single Approval**: Establishes target outcomes, predicted surfaces, and required verification tiers. The developer approves once via chat or terminal.
3. **Implementation**: Code modifications are confined strictly to the approved scope. Material architectural drift or unplanned module edits fail closed.
4. **Verification & Proof**: Final code is frozen. Preflight checks, unit tests, specialist reviewer subagents, Gradle assemble, and device deployment run in strict topological order.

---

## Install

### Requirements

- **Python**: 3.10 to 3.14 (standard library only; no virtual environment or external packages required).
- **Project**: Git checkout of an Android project with a root Gradle Wrapper (`gradlew` / `gradlew.bat`).
- **Build Tools**: JDK and Android SDK configured for your project.
- **Device (Optional)**: Connected physical device or running Android emulator (only needed if task triggers device verification).

### Chat installation (recommended)

Open your Android project in your AI coding agent (Claude Code, GitHub Copilot, Cursor, Windsurf, Roo Code, or Gemini CLI / Antigravity) and paste this exact pinned bootstrap prompt into the chat:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.58/docs/install-or-update-prompt.md and follow all instructions.
```

The installer runs non-destructively:
1. Discovers existing Gradle modules, build variants, and architectural conventions.
2. Interactively asks only necessary configuration questions (e.g., target build variant, device policy).
3. Presents a clear installation plan and awaits developer approval.
4. Installs the immutable engine under `.agents/` and configures host adapter files.
5. Runs the 12-point Doctor diagnosis to verify full environment readiness.

### Terminal installation (alternative)

You can install the harness CLI globally using `pipx`:

```bash
# Install the CLI in an isolated environment
pipx install android-agent-harness

# Run interactive setup in your Android repository root
android-harness setup --repo /path/to/android-project

# Verify system health across all 12 diagnostic dimensions
android-harness doctor --repo /path/to/android-project --json
```

Or run directly from a pinned source clone without global installation:

```bash
git clone --depth 1 --branch v1.0.58 --single-branch \
  https://github.com/rabee-elkholy/android-agent-harness.git ~/.android-harness/kit

python ~/.android-harness/kit/harness_cli.py setup \
  --repo /path/to/android-project \
  --kit ~/.android-harness/kit
```

After installation, daily work uses the repository-local launcher:

```bash
python .agents/harness.py doctor --json
```

---

## Daily workflow

Developers interact naturally with their coding agent. For example:

> *"Add retry handling to profile image loading, preserve our existing MVI architecture, add unit test coverage, and verify the screen on emulator."*

The harness orchestrates the agent's work through the 15-step sequential lifecycle:

### Canonical Sequential Lifecycle

| Step | Stage | Canonical Command | Purpose & Parameter Contract |
|:---:|:---|:---|:---|
| **1** | **Discovery** | `python .agents/harness.py task-context --file <path> --json` | AST-bounded symbol and dependency slice (or `--symbol <name>`). |
| **1b** | **Graph Discovery** | `python .agents/scripts/project_graph.py --feature <name>` | Feature-level dependency graph and component topology. |
| **2** | **Draft Plan** | `python .agents/scripts/workflow.py draft --repo . --task-id <id> --outcome "<outcome>" --kind <AUTO\|BUG\|FEATURE\|REFACTOR>` | Creates formal task plan. Required: `--task-id`, `--outcome`. |
| **3** | **Approve Task** | `python .agents/scripts/workflow.py approve --repo . --task-id <id> --source conversation --proof-reference "<phrase>" --enforcement-tier RULE_ENFORCED` | Records single developer approval. Generates single-use execution nonce. |
| **4** | **Begin Task** | `python .agents/scripts/workflow.py begin --repo . --task-id <id>` | Transitions task to `IMPLEMENTING` state. Consumes approval nonce. |
| **5** | **Diagnostic Build** | `python .agents/scripts/run_gradle_task.py :app:assembleDebug` | *(Optional)* Diagnostic compilation checkpoint during implementation. |
| **6** | **Prepare Verification** | `python .agents/scripts/workflow.py prepare-verification --repo . --task-id <id>` | Freezes final working tree diff, resolves risk lane, transitions to `VERIFYING`. |
| **7** | **Preflight Gate** | `python .agents/scripts/preflight_check.py` | Fast (<2s) deterministic checks: Room schemas, localized strings, ktlint. |
| **8** | **Unit Tests Gate** | `python .agents/scripts/run_tests_gate.py` | Executes targeted unit tests required by policy; verifies zero regressions. |
| **9** | **Review Package** | `python .agents/scripts/review_package.py --task-id <id>` | Generates immutable markdown review package with surface diffs and metrics. |
| **10** | **Record Review** | `python .agents/scripts/record_review.py --task <id> --from-subagent <role>=<convId>` | Auto-harvests review evidence from independent subagent transcripts. |
| **10b** | **Validate Finding** | `python .agents/scripts/workflow.py validate-finding --repo . --task-id <id> --finding-id <id> --status <FALSE_POSITIVE\|CONFIRMED> --reason "<text>"` | Formally adjudicates reviewer findings with technical rationale. |
| **10c** | **Resume Task** | `python .agents/scripts/workflow.py resume --repo . --task-id <id>` | Transitions back to `IMPLEMENTING` if code fixes or re-work are required. |
| **11** | **Assemble Debug** | `python .agents/scripts/run_gradle_task.py :app:assembleDebug` | Builds target APK *(executed only AFTER reviewers pass or REVIEWERS=NONE)*. |
| **12** | **Device Deploy** | `python .agents/scripts/run_device.py install-start` | Deploys verified APK set and launches main component on device/emulator. |
| **12b** | **Screen Capture** | `python .agents/scripts/capture_screen.py --output-name <name>` | Captures device verification screenshot as visual proof. |
| **13** | **Final Verify** | `python .agents/scripts/workflow.py verify --repo . --task-id <id>` | Read-only delivery audit; validates all gates and cryptographic signatures. |
| **14** | **Complete Task** | `python .agents/scripts/workflow.py complete --repo . --task-id <id>` | Transitions task to `READY_FOR_DELIVERY`. Developer reviews diff. |
| **15** | **Deliver Task** | `python .agents/scripts/workflow.py deliver --repo . --task-id <id>` | Finalizes delivery state after developer completes git commit. |
| **—** | **Context Note** | `python harness_cli.py context note "<note>"` | Records durable project conventions into `.agents/project-context/`. |

---

## 5-Tier Adaptive Risk Lanes

Tasks are not evaluated uniformly. The harness inspects the actual working tree diff and dynamically selects an adaptive risk lane based on blast radius:

| Tier | Risk Lane | Scope Triggers | Reviewers Required | Verification Gates |
|:---:|:---|:---|:---:|:---|
| **Tier 0** | `NANO` | Strings, icons, drawables, documentation | **None** | Fast preflight only (<2s). Assemble and device deployment skipped. |
| **Tier 1** | `VISUAL_ANALYTICS` | UI styling, analytics constants, Compose clicks ($\le 8$ files in 1 module) | **None** | Fast assemble permitted; device deployment skipped. |
| **Tier 2** | `FEATURE_LOGIC` | ViewModels, UseCases, standard domain logic | **1 Reviewer**<br>(`bug-reviewer-agent`) | Preflight + unit tests gate + Gradle assemble. |
| **Tier 3** | `SUBSYSTEM_ARCH` | Multi-module diffs, Hilt DI bindings, network API contracts | **2 Reviewers**<br>(`bug-reviewer-agent`, `regression-impact-reviewer-agent`) | Preflight + unit tests + architecture drift check + Gradle assemble. |
| **Tier 4** | `CRITICAL_CORE` | Room schemas, DB migrations, Auth, Billing, Crypto, Security | **Full Five-Leaf Review**<br>(5 independent subagent specialists) | Mandatory Room migration gate + assemble + device deploy & sign-off walkthrough. |

### Cryptographic Review Evidence & Finding Adjudication

Specialist reviewers execute independently as subagents and attach cryptographically bound evidence footers:
`EVIDENCE pkg=<sha12> cites=<n>`

- **Clean Reviews**: Reviews with zero citations (`cites=0`) automatically evaluate to `PASS`.
- **Finding Adjudication**: When a reviewer reports a false positive or intentional design decision, the lead agent adjudicates it using `workflow.py validate-finding --status FALSE_POSITIVE --reason "<rationale>"`.
- **Audit Trails**: The technical justification is permanently embedded into `review-package.md` under `## LEAD AGENT FINDING VALIDATIONS`, allowing re-reviews to verify the decision without manual bypasses.

---

## Deterministic Android Guards

The harness includes specialized deterministic guards that catch domain-specific regressions in milliseconds before Gradle compilation:

| Android Surface | Deterministic Protection |
|:---|:---|
| **Room Database & Schemas** | Checks version increments and migration path continuity. Flags missing migration classes, unhandled column drops, and illegal destructive fallbacks (`fallbackToDestructiveMigration`). |
| **Localized Resources (`strings.xml`)** | Enforces key, plural, and placeholder parity across all locale directories (`values/`, `values-ar/`, `values-es/`). Detects introduced hardcoded UI strings. |
| **Compose & XML Presentation** | Classifies Composable functions, Activity/Fragment lifecycle scopes, and ViewBinding references. Detects leaked ViewBinding properties in Fragments. |
| **Threading & Dispatchers** | Scans for blocking I/O calls on the main dispatcher (`Dispatchers.Main`), unconfined coroutine scopes, and missing exception handlers. |
| **Sensitive & Auth Logic** | Automatically elevates modifications involving tokens, credentials, encryption, or payment SDKs to Tier 4 verification. |
| **Device & APK Continuity** | Verifies split APK sets, ABI compatibility, device connectivity states, Android user IDs (`u0`), and package identities to prevent deploying stale artifacts. |

---

## Safety Model & Boundaries

The harness enforces rigorous boundaries to keep the developer in complete control:

```text
┌──────────────────────────────────────────────────────────────┐
│                    DEVELOPER BOUNDARY                        │
│  • Git commits, pushes, branches, merges, and rebases        │
│  • Application architecture & third-party dependency choices │
│  • Production release signing & secret management            │
├──────────────────────────────────────────────────────────────┤
│                     HARNESS CONTROL PLANE                    │
│  • Read-only project discovery & AST slicing                 │
│  • Approval nonce enforcement & state machine validation     │
│  • Deterministic preflight gates (<2s)                       │
│  • Autonomous reviewer subagent routing                      │
│  • Gradle gate execution & APK artifact fingerprinting       │
│  • Device deployment & interactive mobile walkthrough        │
├──────────────────────────────────────────────────────────────┤
│                      HOST ENVIRONMENT                        │
│  • Standard Library Python 3.10–3.14 (Zero pip dependencies) │
│  • Gradle Wrapper, Android SDK, ADB daemon                   │
└──────────────────────────────────────────────────────────────┘
```

### Safety Principles

- **No OS Sandbox**: The harness does not sandbox host processes. A process with shell access can modify local files; cryptographic checksums ensure any tampering with harness engine code is immediately detected.
- **No Git Tampering**: The harness will never commit, push, reset, stash, or rebase client project code. All changes remain unstaged in the developer's working tree.
- **No Silent Modernization**: The harness never silently rewrites project architecture, migrates XML to Compose, or swaps dependency injection frameworks without explicit developer instructions.
- **No Dangerous Device Operations**: Does not clear application data, uninstall applications, downgrade versions, or automatically authorize billable actions on connected devices.

For detailed security analyses, consult [SECURITY.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/SECURITY.md), [Threat Model](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/threat-model.md), and [Compatibility Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md).

---

## Supported Environments & AI Hosts

### Android Project Compatibility

- **Languages**: Kotlin, Java, and mixed codebases.
- **UI Frameworks**: Jetpack Compose, XML Views, and hybrid UI.
- **Project Topologies**: Single-module apps, multi-module apps, library projects, dynamic-feature modules, and Android/KMP targets.
- **Build Systems**: Gradle with Kotlin DSL (`build.gradle.kts`) or Groovy DSL (`build.gradle`), Gradle Version Catalogs (`libs.versions.toml`).
- **Operating Systems**: Linux, macOS, and Windows (native PowerShell and CMD support).

### AI Host Adapters

The harness provides native adapter configurations for all major AI coding environments:

| AI Host | Integration Mechanism | Enforcement Tier |
|:---|:---|:---:|
| **Antigravity / Gemini CLI** | Native tool hooks (`agents/hooks.json`), rules, and skills | `HARD_ENFORCED` / `RULE_ENFORCED` |
| **Claude Code** | Pre-tool execution hooks (`config.json`), subagents, custom rules | `HARD_ENFORCED` |
| **GitHub Copilot** | Custom agent configuration, workspace rules | `RULE_ENFORCED` |
| **Cursor** | Workspace rules (`.cursorrules`), terminal wrappers | `RULE_ENFORCED` |
| **Windsurf** | Cascade instructions (`.windsurfrules`), workflow recipes | `RULE_ENFORCED` |
| **Roo Code** | Custom modes, tool permission wrappers | `RULE_ENFORCED` |

See [Tool Support](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md) for full adapter configuration details.

---

## Quality & Self-Testing

This repository tests its own engine through an extensive deterministic selftest suite covering 18 test domains and 500+ unit, integration, and scenario assertions:

```bash
# Run the complete deterministic selftest suite
python harness_cli.py selftest

# Run syntax compilation validation across all scripts
python -m compileall -q harness_cli.py agents/scripts agents/mcp/zoho_sprints

# Validate release metadata, prompt pins, checksums, and package invariants
python scripts_dev/validate_release.py
```

### Continuous Integration (CI)

Every commit and pull request is validated by GitHub Actions across:
- **Python Matrix**: 3.10, 3.11, 3.12, 3.13, and 3.14.
- **Platforms**: Ubuntu 24.04, Windows Server 2025, and macOS 15.
- **Checks**: Full deterministic selftest, performance regression benchmarks, wheel lifecycle tests (install, update, uninstall), and tamper-detection validation.

---

## Documentation

Comprehensive guides and architectural references are available in the repository:

| Document | Description |
|:---|:---|
| [Quickstart Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/quickstart.md) | Step-by-step setup and running your first governed task. |
| [Architecture Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/architecture.md) | Deep dive into the state machine, project graph, and evidence subsystem. |
| [Workflow Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/workflows.md) | Complete guide to the 15-step task and delivery lifecycle. |
| [Compatibility Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md) | Supported project structures, Gradle versions, and OS platforms. |
| [AI Tool Support](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md) | Host adapter setup for Claude Code, Gemini CLI, Cursor, and Copilot. |
| [Setup Wizard Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/setup-wizard.md) | Interactive setup questions, flags, and non-interactive JSON schemas. |
| [Threat Model](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/threat-model.md) | Security analysis, trust boundaries, and mitigated vulnerability classes. |
| [Restore & Recovery](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/restore.md) | Safe recovery, repair, and rollback procedures. |
| [Contributing Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/CONTRIBUTING.md) | Guidelines for contributing code, tests, and documentation. |
| [Changelog](https://github.com/rabee-elkholy/android-agent-harness/blob/main/CHANGELOG.md) | Detailed version history, fixes, and migration notices. |

---

## What this project is not

To set clear engineering expectations:
- **Not an AI Model or Proxy**: We do not sell or wrap LLM APIs. The harness sits in your repository and works with whichever AI model or coding assistant you use.
- **Not a Framework Replacement**: It does not replace Android Studio, Gradle, Kotlin compiler, or Jetpack libraries.
- **Not an Autonomous Swarm Gimmick**: It does not spin up uncontrolled agent loops. Every task has an explicit scope, bounded context, and human-in-the-loop approval.
- **Not a Reason to Run Heavy Builds Blindly**: It actively avoids running slow Gradle builds or device deployments for micro edits and documentation changes.

---

## Contributing

We welcome contributions! Please review [CONTRIBUTING.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/CONTRIBUTING.md) before submitting pull requests.

Key contributor rules:
1. **Standard Library Only**: All runtime engine code must strictly use the Python standard library.
2. **Deterministic Coverage**: Any behavioral change or bug fix must include deterministic regression tests in `agents/scripts/_*_selftest.py`.
3. **Full Suite Green**: Run `python harness_cli.py selftest` and `python scripts_dev/validate_release.py` before submitting.

For vulnerability disclosures, please follow the coordinated process detailed in [SECURITY.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/SECURITY.md).

---

## License

MIT License. See [LICENSE](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE).
