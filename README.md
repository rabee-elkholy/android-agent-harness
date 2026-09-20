<div align="center">

# Android Agent Harness

### A production control plane for AI-assisted Android development

Turn a general-purpose coding agent into a predictable Android contributor with explicit developer approval, Android-aware policy, bounded project context, and evidence-backed delivery.

[![CI](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/rabee-elkholy/android-agent-harness?label=release)](https://github.com/rabee-elkholy/android-agent-harness/releases)
[![PyPI](https://img.shields.io/pypi/v/android-agent-harness)](https://pypi.org/project/android-agent-harness/)
[![Python](https://img.shields.io/badge/Python-3.10%E2%80%933.14-blue)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
[![Platforms](https://img.shields.io/badge/Linux%20%7C%20macOS%20%7C%20Windows-supported-success)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
[![License](https://img.shields.io/github/license/rabee-elkholy/android-agent-harness)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE)

[Why it exists](#why-it-exists) · [How it works](#how-it-works) · [Install](#install) · [Daily workflow](#daily-workflow) · [Safety model](#safety-model) · [Documentation](#documentation)

</div>

---

Android Agent Harness is a repository-local workflow and verification system for teams that use AI agents on real Android codebases. It does not replace Android Studio, Gradle, ADB, Git, CI, or your model. It coordinates them so the agent receives relevant context, follows an approved scope, runs proportionate checks, and cannot label work ready without evidence from the current change set.

It is designed for existing Kotlin, Java, Compose, XML, multi-module, library, dynamic-feature, and Android/KMP projects. Runtime code uses only the Python standard library.

## Why it exists

Raw coding agents are useful, but Android delivery has failure modes that a prompt alone cannot reliably control:

| Without the harness | With the harness |
|---|---|
| The agent edits before the developer agrees on scope | A task plan is recorded and explicit approval unlocks implementation |
| A large repository is dumped into model context | Project Intelligence resolves a bounded file-, symbol-, or feature-level slice |
| A mixed diff is treated as one generic change | Android surfaces such as Room, Compose, navigation, auth, billing, and permissions are classified independently |
| Every task pays for the same expensive review process | Risk lanes select only the deterministic gates and specialist reviews the change needs |
| “Tests passed” can refer to stale or unrelated output | Evidence is bound to the repository, branch, run, change set, and delivery snapshot |
| An old or different APK is installed | Assemble, install, and launch share one verified APK artifact-set identity |
| Room or resource mistakes reach runtime | Dedicated deterministic guards inspect migrations, localized resources, and Android-specific hazards |
| The agent mutates Git history or external trackers unexpectedly | Client-project Git writes remain developer-owned; tracker writes require explicit, scoped authorization |

The goal is not more ceremony. The goal is to spend model time and developer attention only where they materially reduce risk.

## What you get

- **Approval-first execution** — discovery is read-only; implementation starts only after the developer approves a concrete outcome, scope, and verification plan.
- **Android-aware change classification** — detects multiple simultaneous surfaces instead of collapsing a diff to its least risky file.
- **Bounded Project Intelligence** — resolves the smallest useful live context for a file or symbol, handles ambiguous identities safely, and keeps default previews compact.
- **Adaptive verification** — micro, standard, and critical changes receive different gates. Presentation-only UI work is not forced through the same path as auth, billing, crypto, or Room schema changes.
- **Deterministic Android guards** — localization parity, Room migration safety, test attribution, performance hazards, environment classification, Gradle diagnostics, and device identity checks.
- **Evidence-backed delivery** — gate output and reviews must match the frozen final tree. Stale, partial, malformed, or mismatched evidence fails closed.
- **Safe lifecycle operations** — install, update, repair, rollback, and uninstall are transactional and preserve project-owned hooks, configuration, source, and task evidence.
- **Model-agnostic operation** — works with supported hosts and lets teams map abstract `STANDARD` and `STRONG` review capabilities to the models they choose.
- **Local, dependency-light runtime** — installed project commands run from `.agents/harness.py` with no third-party Python runtime packages.

## How it works

![Android Agent Harness Architecture Pipeline](https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/main/docs/assets/architecture-pipeline.svg)

The workflow is a persisted state machine:

```text
INTAKE -> DISCOVERY -> PLAN_DRAFTED -> AWAITING_DEVELOPER_APPROVAL
       -> IMPLEMENTING -> VERIFYING -> READY_FOR_DELIVERY -> DELIVERED
                                    \-> BLOCKED -> IMPLEMENTING
```

The harness separates three concerns:

1. **Understanding the project** — discovers modules, variants, source sets, architecture signals, symbols, and relevant dependencies without forcing an architecture rewrite.
2. **Controlling the task** — binds approval, scope, risk, selected skills, and allowed operations to one task lifecycle.
3. **Proving the result** — records deterministic gate and review evidence against one immutable delivery snapshot.

## Install

### Requirements

- Python 3.10–3.14;
- a Git checkout with a root Gradle Wrapper;
- JDK and Android SDK when selected build gates require them;
- ADB only when the task requires device verification.

### Chat installation (recommended)

Open the Android project root in your coding agent and paste this exact pinned prompt:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.56/docs/install-or-update-prompt.md and follow all instructions.
```

The installer discovers the project in read-only mode, asks only the configuration questions it needs, shows the installation plan, waits for approval, installs the pinned kit, and runs Doctor. Application source is not modified during setup.

### Terminal installation (alternative)

```bash
# Install the CLI in an isolated environment.
pipx install android-agent-harness

# Configure an Android project.
android-harness setup --repo /path/to/android-project

# Verify the installation and environment.
android-harness doctor --repo /path/to/android-project --json
```

To use a source checkout instead:

```bash
git clone --depth 1 --branch v1.0.56 --single-branch \
  https://github.com/rabee-elkholy/android-agent-harness.git ~/.android-harness/kit

python ~/.android-harness/kit/harness_cli.py setup \
  --repo /path/to/android-project \
  --kit ~/.android-harness/kit
```

After setup, normal work uses the repository-local launcher, so the global kit path is not required for daily commands:

```bash
python .agents/harness.py doctor --json
python .agents/harness.py task-context --file app/src/main/kotlin/com/acme/ProfileScreen.kt --json
python .agents/harness.py task status --task-id profile-edit --next
```

See the [Quickstart](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/quickstart.md) and [Setup Wizard reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/setup-wizard.md) for update, repair, rollback, uninstall, and non-interactive options.

## Daily workflow

The developer can describe work naturally. A typical request is:

> Add retry handling to profile loading, preserve the existing architecture, add regression coverage, and verify the affected screen.

The agent should then:

1. resolve bounded context for the affected file, symbol, or feature;
2. inspect the relevant application code and existing conventions;
3. present the proposed outcome, files/surfaces, risks, tests, and device needs;
4. wait for one explicit approval;
5. implement the approved work without changing unrelated architecture;
6. freeze the final change set and run the policy-selected gates and reviewers;
7. perform assemble/device/UI verification only when the policy requires it;
8. report the result and leave application changes unstaged for developer review.

For a bug with a meaningful deterministic seam, the workflow records a real failing result before the fix and a passing result afterward. For a documentation or mechanical change, it avoids pretending that an empty or irrelevant test run adds confidence.

### Common commands

| Goal | Command |
|---|---|
| Diagnose installation | `python .agents/harness.py doctor --json` |
| Resolve context for a file | `python .agents/harness.py task-context --file <path> --json` |
| Resolve context for a symbol | `python .agents/harness.py task-context --symbol <name> --json` |
| Ask for the safe next action | `python .agents/harness.py task status --task-id <id> --next` |
| Run deterministic preflight | `python .agents/harness.py preflight` |
| Run selected unit tests | `python .agents/harness.py test` |
| Assemble a configured target | `python .agents/harness.py assemble <task>` |
| Install and start verified APKs | `python .agents/harness.py device install-start` |
| Verify the frozen result | `python .agents/harness.py verify --task-id <id>` |

The project includes command packs for supported hosts, but the repository-local CLI is the canonical contract.

## Android-aware verification

The central policy routes checks from the actual diff. Examples:

| Detected surface | Typical deterministic protection |
|---|---|
| Room entity or database schema | version and migration path inspection; destructive fallback detection; migration tests when configured |
| Localized resources | key, plural, and placeholder parity; introduced hardcoded UI text checks |
| Compose/XML presentation | resource and UI classification; proportionate visual verification |
| Coroutines or blocking work | main-thread/blocking hazard checks plus targeted tests/review |
| Auth, crypto, billing, sensitive data | stronger risk lane, security review, and final snapshot approval |
| Gradle, manifest, module topology | exact module/variant discovery and build-policy checks |
| APK/device work | artifact-set, device serial, Android user, install, and launch continuity |

### Example: Room schema change

If an agent adds a field to a Room entity, the harness can classify the change as `ROOM_SCHEMA`, discover the owning database, require an explicit migration path, run configured migration tests, route the data-focused review lane, and bind the final assemble/device evidence to the same frozen tree. A changed entity cannot be disguised as a low-risk documentation change by placing both in one diff.

## Safety model

The harness is deliberately precise about what it can and cannot enforce.

| Tier | Meaning |
|---|---|
| `HARD_ENFORCED` | A supported host-native hook intercepts the stated mutation class before execution |
| `RULE_ENFORCED` | Instructions and deterministic delivery gates apply, but the host does not provide complete pre-execution interception |
| `UNSUPPORTED` | The minimum safe workflow is unavailable for that host or capability |

Important boundaries:

- This is not an OS sandbox. A process with arbitrary local access can bypass repository files.
- Cryptographic hashes make evidence tampering and staleness detectable; they do not make the host machine trusted.
- The harness never claims that configuring a CI matrix proves it passed. Hosted CI results are separate evidence.
- It does not silently modernize architecture, replace DI, migrate XML to Compose, or rewrite persistence choices.
- It does not automatically pair wireless ADB, clear app data, uninstall an app, downgrade builds, make purchases, or grant every permission.
- It does not commit, push, reset, or stage client application work for the developer.
- Zoho Sprints behavior is preserved, but live tracker mutation requires explicit `update zoho` authorization and idempotent operation identity.

For the complete boundary and threat analysis, read [Security](https://github.com/rabee-elkholy/android-agent-harness/blob/main/SECURITY.md), [Threat Model](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/threat-model.md), and [Compatibility Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md).

## Supported project and host shapes

The validated project boundary includes:

- Kotlin, Java, and mixed projects;
- Jetpack Compose, XML Views, and hybrid UI;
- application, library-only, multi-module, dynamic-feature, and Android/KMP targets;
- Kotlin or Groovy Gradle DSL;
- discovered flavors and custom build types;
- existing tests, no-test repositories, and explicitly recorded baseline debt;
- normal Git checkouts and worktrees;
- Linux, macOS, and Windows hosts.

Host adapters are available for Claude Code, GitHub Copilot, Cursor, Windsurf, Roo Code, Gemini CLI, and Antigravity. Enforcement strength depends on the capabilities of each host; see [Tool Support](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md) for the current matrix.

## Lifecycle and non-interference

Harness lifecycle operations are designed not to take ownership of the Android project:

- managed files live under `.agents/` plus documented host adapters;
- local state is excluded through `.git/info/exclude` rather than changing the application’s tracked ignore policy;
- project-owned hooks and Git configuration are preserved byte-for-byte;
- same-major updates are transactional and fail closed on conflicting managed-file edits;
- repair restores immutable engine files from the pinned checksum inventory;
- uninstall starts as a dry run and preserves modified harness material in recovery when applied;
- interrupted lifecycle operations use journals for deterministic recovery.

```bash
android-harness update --repo /path/to/android-project --kit /path/to/new-kit
android-harness repair --repo /path/to/android-project --kit /path/to/pinned-kit
android-harness uninstall --repo /path/to/android-project
android-harness uninstall --repo /path/to/android-project --apply
```

## Verification and release quality

This repository verifies the harness itself; it does not run Android Gradle or ADB against the harness source tree.

```bash
# Complete deterministic suite.
python harness_cli.py selftest

# Syntax validation.
python -m compileall -q harness_cli.py agents/scripts agents/mcp/zoho_sprints

# Release metadata, prompt pins, checksums, and package contract.
python scripts_dev/validate_release.py
```

CI runs the complete selftest suite across every supported Python version on Linux and on the canonical Python runtime for Windows and macOS. Wheel install/update/uninstall lifecycles run separately on all three operating systems, alongside performance regression and release-metadata checks. Release tags receive a second cross-platform validation before trusted PyPI publication.

## Documentation

| Document | Use it for |
|---|---|
| [Quickstart](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/quickstart.md) | installation and first successful run |
| [Architecture](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/architecture.md) | components, state, policy, and evidence design |
| [Workflows](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/workflows.md) | the full task and delivery lifecycle |
| [Compatibility Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md) | supported projects, runtimes, and enforcement boundaries |
| [Tool Support](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md) | AI-host adapters and capability tiers |
| [Setup Wizard](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/setup-wizard.md) | configuration questions and generated policy |
| [Threat Model](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/threat-model.md) | trust assumptions, attacks, and residual risks |
| [Restore and Recovery](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/restore.md) | damaged installation recovery and verification |
| [Contributing](https://github.com/rabee-elkholy/android-agent-harness/blob/main/CONTRIBUTING.md) | development, tests, and release rules |
| [Changelog](https://github.com/rabee-elkholy/android-agent-harness/blob/main/CHANGELOG.md) | release history and migration notes |

## What this project is not

- not an AI model, model proxy, or provider lock-in layer;
- not a replacement for Gradle, Android Studio, Git, CI, or human code review;
- not a generic autonomous-agent swarm framework;
- not a promise that every host offers hard pre-execution enforcement;
- not a reason to run every expensive gate for every trivial edit.

## Contributing

Issues and focused pull requests are welcome. Please read [CONTRIBUTING.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/CONTRIBUTING.md), preserve the standard-library-only runtime, add deterministic regression coverage for behavior changes, and run the complete selftest before opening a pull request.

Security issues should follow the private reporting process in [SECURITY.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/SECURITY.md).

## License

MIT License. See [LICENSE](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE).
