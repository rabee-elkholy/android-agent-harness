<div align="center">

# Android Agent Harness

**Deterministic Quality Gate, Five-Leaf Parallel Review, and Execution Safety Interceptor for AI-Assisted Android & Kotlin Multiplatform Development.**

[![CI Build](https://img.shields.io/github/actions/workflow/status/rabee-elkholy/android-harness-kit/ci.yml?branch=main&style=flat-square&label=CI%20Build)](https://github.com/rabee-elkholy/android-harness-kit/actions/workflows/ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/rabee-elkholy/android-harness-kit?color=2ea44f&style=flat-square&label=Release)](https://github.com/rabee-elkholy/android-harness-kit/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20KMP-3DDC84?style=flat-square)](https://android.com)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square)](https://python.org)
[![Quality Gate](https://img.shields.io/badge/Quality%20Gate-5--Leaf%20Pass-success?style=flat-square)](docs/architecture.md)
[![AI Tools](https://img.shields.io/badge/AI%20Tools-14%20IDs%20%7C%2011%20Templates-8A2BE2?style=flat-square)](docs/tool-support.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](CONTRIBUTING.md)

</div>

---

## The Core Problem: Why AI Coding Agents Break Android Apps

AI coding assistants (Cursor, Claude Code, Copilot, Antigravity, Windsurf) have become exceptionally capable at writing isolated Kotlin snippets. However, in real-world Android projects, they routinely cause **silent production failures, architectural degradation, and data loss**:

1. **The "Self-Deluding" Agent & Fake Success**: Models self-report success based on superficial text completion. They declare a feature "implemented and verified" without compiling the Gradle module, leaving subtle nullability bugs at Java/Kotlin boundaries, unhandled Coroutine exceptions, or broken navigation graphs.
2. **Main-Thread ANRs & Memory Leaks**: Agents frequently perform disk I/O, Room database access, or JSON parsing on `Dispatchers.Main`, introduce runaway recomposition loops in Jetpack Compose, or forget to unregister sensors/listeners in `DisposableEffect.onDispose`, draining battery life and causing Application Not Responding (ANR) crashes.
3. **Database Schema Corruption & Crash on Launch**: When modifying `@Entity` data classes, models often neglect Room `AutoMigration` specs or export schema updates. The project compiles successfully, but crashes immediately upon runtime launch with `IllegalStateException: Room cannot verify the data integrity`.
4. **Destructive Git & Device Mutations**: Under context pressure, agents hallucinate destructive shell commands -- attempting `git commit`, `git push --force`, `git reset --hard`, or executing `adb shell pm clear` and `adb monkey`, wiping uncommitted developer work and deleting local application databases.
5. **The Prompt-Only Illusion**: System prompts like *"Please review your code"* or *"Do not commit"* reliably fail as conversation context grows. **Soft prompt instructions cannot enforce hard engineering boundaries.**

---

## The Solution: Deterministic Gates Outside the Model

The **Android Agent Harness** places deterministic, machine-enforced barriers **outside the model's brain**:

```
[ Developer Prompt / IDE Chat ]
              |
              v
[ Pre-Tool Safety Interceptor ] --> Blocks destructive Git mutations, bare ADB, pm clear
              |
              v
[ Implementation / Coding ]
              |
              v
[ Five-Leaf Review Barrier ] -----> 5 Specialized subagents run in parallel (Bug, Conv, Sec, Perf, Reg)
              |                     Must produce cryptographic SHA-256 evidence footers + verdict.json
              v
[ Preflight Quality Gate ] -------> Fast Kotlin lint (<5s), Room migration check, Bilingual string parity
              |
              v
[ Gradle Build & Live Device ] ---> APK Assembly & device install only unlocked after FULL PASS
```

* **Zero Git Authority**: The agent is physically barred from executing `git commit` or `git push`. History remains strictly under human developer control.
* **Cryptographic Delivery Barrier**: Gradle assembly and device deployment stay locked until 5 independent reviewer subagents evaluate the exact working tree diff and emit valid cryptographic evidence footers (`EVIDENCE pkg=<sha256_12>`).
* **Universal Pre-Commit Quality Gate**: Fast (<5s) staged-file validation ensuring zero hardcoded UI strings, valid Room migrations, and clean Kotlin imports before any commit can land in history.

---

## Comparison: Development With vs Without Harness

| Failure Mode | Without Android Harness | With Android Agent Harness |
| :--- | :--- | :--- |
| **Verification Integrity** | Casual self-reported "LGTM". Agent declares success without compiling. | **Mandatory Review Gate**: Locked out of `:assembleDebug` until all 5 specialized subagents sign off with cryptographic proof. |
| **UI Freezes & ANRs** | Blocking I/O or heavy operations placed on `Dispatchers.Main`. | **ANR Guardian**: Static heuristics intercept main-thread disk/network I/O, canvas bottlenecks, and recomposition loops. |
| **Database Migrations** | Modifying `@Entity` without migrations causes launch crashes. | **Room Guard**: Validates entity hash schemas, migration paths, and test coverage before allowing builds. |
| **Localization & RTL** | Adding English strings without Arabic translations breaks bilingual UI. | **Bilingual String Parity**: Automated validation enforces 1-to-1 key parity and Compose dual-locale previews. |
| **Git Safety** | AI commits incomplete code, overwrites branches, or pushes dirty state. | **Hard Interception**: Zero autonomous Git mutations allowed. All commit attempts are blocked by Python hooks. |
| **Device Integrity** | AI runs `pm clear` or `adb monkey`, wiping test databases. | **Device Guard**: Intercepts destructive device commands and binds ADB commands to explicit device serials. |

---

## Lifecycle Operations: Install, Maintain, Update & Rollback

The harness provides two frictionless paths for every lifecycle operation: **CLI-First** (for terminal workflows) and **One-Click Prompts** (for direct IDE AI chat).

### 1. Installation & Setup

Set up deterministic governance in any Android or Kotlin Multiplatform repository in under a minute:

#### Path A: Via CLI (Recommended)
```bash
cd /path/to/your/android-project
pipx install git+https://github.com/rabee-elkholy/android-harness-kit.git
android-harness init
```

#### Path B: Via AI Chat (One-Click Prompt)
Open a **new strong-model chat** at your Android repository root and paste:
```
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/install-prompt.md
```

The interactive wizard automatically discovers your Gradle modules, launcher activities, build flavors, and project architecture (MVI/MVVM/Clean + Koin/Hilt + Room + Compose).

---

### 2. Maintenance & Health Diagnostics (Doctor)

Verify the integrity of your installed harness, subagent fingerprints, SDK paths, and file locks at any time:

```bash
# Terminal execution
android-harness doctor

# Or execute via IDE Chat prompt:
# https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/diagnostic-prompt.md
```

The **12-Dimension Harness Doctor** runs 30 automated checks covering:
* Host Python environment & Android SDK discovery
* Subagent template fingerprints & prompt integrity
* Git repository status & local hook exclusions
* Preflight linters (Strings, Room, Fast Kotlin lint)
* Project tracker configuration & credential isolation (zero secrets in repo)

---

### 3. Upgrading to New Releases (Update)

Upgrade your harness installation to the latest stable release with pin-to-tag supply-chain safety and zero configuration drift:

```bash
# Terminal execution
android-harness update

# Or execute via IDE Chat prompt:
# https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/update-prompt.md
```

* Upgrades preserve all existing project settings, tailored domain references, and tracker credentials.
* Automatically creates an isolated snapshot in `.harness-backup/<timestamp>/` before updating.

---

### 4. Emergency Instant Rollback

If you ever need to restore your repository configuration to an exact previous state:

```bash
# Terminal execution
android-harness rollback

# Or execute via IDE Chat prompt:
# https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/rollback-prompt.md
```

---

## The Five-Leaf Review Gate

Before any APK assembly or device execution, the Lead Agent dispatches **5 specialized review subagents in parallel in a single invocation** against a hashed diff of the working tree (`HARNESS_REVIEW_PACKAGE`):

| Specialized Subagent | Pass Token | Review Focus & Quality Invariant |
| :--- | :--- | :--- |
| **`bug-reviewer-agent`** | `BUG_PASS` | Logic correctness, Kotlin null-safety, Coroutine exception handling, network resiliency. |
| **`convention-reviewer-agent`** | `CONVENTION_PASS` | Unidirectional Data Flow, Clean Architecture/MVI, zero inline FQCNs, Compose accessibility (48dp touch targets). |
| **`security-reviewer-agent`** | `SECURITY_PASS` | Exported components, deep link validation, secret leakage in logs, hardcoded tokens. |
| **`perf-anr-guardian-agent`** | `PERF_PASS` | Main-thread disk/network I/O, recomposition loops, sensor/listener lifecycle disposal. |
| **`regression-impact-reviewer-agent`** | `REGRESSION_PASS` | Blast radius analysis, caller graph verification, data model contract changes. |

Every review round produces a machine-readable verdict record at `.agents/state/verdicts/verdict-<pkg12>.json`. Validate any verdict record using:
```bash
android-harness verify
```

---

## Multi-IDE AI Tool Support

The harness provides 3 tiers of enforcement across 14 AI coding environments:

| Enforcement Tier | Protection Mechanisms | Supported AI Tools |
| :--- | :--- | :--- |
| **Hook-Enforced** | Deterministic Python pre-tool interceptors, native IDE hook bridges, universal pre-commit gate. | Antigravity, Claude Code, GitHub Copilot (with repository hooks). |
| **Rule-Driven** | Managed IDE configuration rules (`.cursor/rules/`, `.windsurf/`, `.roo/`), slash command packs. | Cursor, Windsurf, Cline, Roo Code, Amazon Q, Continue, Junie, Kilo, Goose, Qwen, Codex. |
| **Prompt-Only** | Standardized `AGENTS.md` repository manifest. | Aider, Zed, Devin, Amp, Factory, Jules, Warp, OpenCode. |

---

## One-Click Prompt Library

Pinned lifecycle prompts with cryptographic tamper-evident headers:

| Operation | Prompt URL (Pinned to v0.12.0) | Purpose |
| :--- | :--- | :--- |
| **Install** | [`docs/install-prompt.md`](https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/install-prompt.md) | Full guided installation, module discovery, and adapter generation. |
| **Update** | [`docs/update-prompt.md`](https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/update-prompt.md) | In-place version upgrade preserving project preferences. |
| **Doctor** | [`docs/diagnostic-prompt.md`](https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/diagnostic-prompt.md) | 12-dimension comprehensive system health diagnostics. |
| **Rollback** | [`docs/rollback-prompt.md`](https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/rollback-prompt.md) | Instant restoration from timestamped backups. |

---

## Documentation & Architecture Deep-Dives

* **[Architecture Guide](docs/architecture.md)**: 7-stage delivery lifecycle, safety interceptor mechanics, and preflight pipeline.
* **[Quickstart & CLI Reference](docs/quickstart.md)**: Complete CLI command matrix and environment setup.
* **[Tool Support Matrix](docs/tool-support.md)**: Adapter templates, slash command packs, and configuration changing.
* **[Threat Model & Security](docs/threat-model.md)**: Detailed analysis of 7 threat vectors and mitigation layers.
* **[Architecture Decision Records (ADRs)](docs/adr/)**: Formal ADRs (001-006) covering review gates, human git authority, and conflict adjudication.
* **[Contributor Recipes](docs/recipes/)**: Step-by-step guides for adding reviewers, policy rules, and tool adapters.
* **[Project Tracker Governance](docs/workflows/pm-integrations.md)**: Zoho Sprints, Jira, Linear, and GitHub Projects integrations.

---

## Contributing & Community

* **Report Bugs**: [GitHub Issue Tracker](https://github.com/rabee-elkholy/android-harness-kit/issues)
* **Contributions**: Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
* **Security Advisories**: See [SECURITY.md](SECURITY.md)

---

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
