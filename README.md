<div align="center">

# Android Agent Harness

**Deterministic Quality Gate, Five-Leaf Parallel Cryptographic Review, and Execution Safety Interceptor for AI-Assisted Android & Kotlin Multiplatform Development.**

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

## The Hard Reality: Why AI Coding Agents Break Android Apps

AI coding assistants (Cursor, Claude Code, Copilot, Antigravity, Windsurf, Devin) are exceptional at generating isolated Kotlin snippets. However, when unleashed on production Android codebases, they introduce **critical silent bugs, performance regressions, and destructive actions**:

1. **The "Self-Deluding" Agent & Fake Success**:
   * Models declare tasks "completed and verified" based purely on generating code. They do not compile the Gradle module, leaving fatal nullability mismatches across Java/Kotlin boundaries, unhandled Coroutine exceptions in background jobs, and broken Jetpack Compose navigation routes.
2. **Main-Thread ANRs & Silent Memory Leaks**:
   * Models routinely execute Room database transactions, disk I/O, or JSON parsing on `Dispatchers.Main`. In Jetpack Compose, they trigger unstable recomposition loops or fail to clean up listeners and sensors in `DisposableEffect.onDispose`, resulting in battery drain and Application Not Responding (ANR) dialogs.
3. **Database Schema Corruption & Launch Crashes**:
   * When modifying `@Entity` classes, AI models frequently forget Room `AutoMigration` specs or export schema updates. The project compiles without warning, but crashes immediately upon launch on user devices with `IllegalStateException: Room cannot verify the data integrity`.
4. **Destructive Git & Device Actions**:
   * Under context window pressure, agents hallucinate destructive shell commands -- executing `git commit`, `git push --force`, `git reset --hard`, or running `adb shell pm clear` and `adb monkey`, wiping uncommitted developer work and deleting local application test databases.
5. **The Prompt-Only Illusion**:
   * Prompt rules like *"Please review carefully"* or *"Do not commit"* reliably fail as conversation context expands. **Soft system prompts cannot enforce hard engineering boundaries.**

---

## The 7-Layer Defense Architecture

The **Android Agent Harness** places deterministic, machine-enforced barriers **outside the model's brain**:

```
+-------------------------------------------------------------------------+
|                      Developer Prompt / IDE Chat                        |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 1. PRE-TOOL SAFETY INTERCEPTOR (Python Hook Engine)                     |
|    - Hard-denies git commit, push, reset (Zero Git Authority)           |
|    - Intercepts bare ADB, pm clear, adb monkey, homoglyphs, base64      |
|    - Anti-polling rate limits & ephemeral conversation state tracking   |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 2. FIVE-LEAF PARALLEL CRYPTOGRAPHIC REVIEW GATE                         |
|    - Locks :assembleDebug and device execution                          |
|    - Dispatches 5 specialized subagents in ONE call on hashed diff      |
|    - Validates cryptographic SHA-256 evidence footers (EVIDENCE pkg=...) |
|    - Emits machine-readable verdict.json & resolves ADR-006 conflicts   |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 3. SPECIALIZED ANDROID PREFLIGHT TRIO (<5s Fast Checks)                 |
|    - Bilingual String Parity: 1-to-1 sync between values/ & values-ar/  |
|    - Room Database Guard: Validates entity hashes & AutoMigrations      |
|    - Fast Kotlin Lint: 48dp touch targets, contentDescription, previews |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 4. UNIVERSAL PRE-COMMIT QUALITY GATE (.githooks/pre-commit)             |
|    - Runs on staged files before any human commit lands in history      |
|    - Isolated locally via .git/info/exclude and --assume-unchanged      |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 5. GRADLE BUILD & LIVE PROCESS STREAMING                                |
|    - APK Assembly unlocked only after full evidence verification        |
|    - Live 10-second heartbeat progress streaming to IDE chat            |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 6. PHYSICAL DEVICE RUNNER & FORENSICS                                   |
|    - Serial-bound ADB installation (-d / -s <serial>)                   |
|    - Real-time Logcat ANR & crash forensics on actual hardware          |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 7. ENTERPRISE PROJECT TRACKER GOVERNANCE                                |
|    - Modular Zoho Sprints, GitHub Projects, Jira, Linear integrations   |
|    - Zero secret leakage in repo (credentials stored in ~/.android-*)   |
|    - Gated behind explicit trigger phrases (e.g. 'update zoho')         |
+-------------------------------------------------------------------------+
```

---

## Side-by-Side Comparison

| Failure Mode / Capability | Without Android Harness | With Android Agent Harness |
| :--- | :--- | :--- |
| **Verification Integrity** | Casual self-reported "LGTM". Agent declares success without compiling. | **Mandatory 5-Leaf Review Gate**: Assembly is physically blocked until 5 specialized subagents sign off with cryptographic proof. |
| **UI Freezes & ANRs** | Blocking I/O or Room access executed on `Dispatchers.Main`. | **ANR Guardian**: Static heuristics intercept main-thread I/O, canvas bottlenecks, and runaway recomposition loops. |
| **Database Migrations** | Modifying `@Entity` without migrations causes runtime launch crashes. | **Room Guard**: Validates entity hash schemas, migration paths, and test coverage before allowing builds. |
| **Bilingual Localization & RTL** | Adding English strings without Arabic translations breaks RTL layouts. | **Bilingual String Parity**: Automated validation enforces 1-to-1 key parity and Compose dual-locale previews. |
| **Git Safety & History** | AI commits incomplete code, overwrites branches, or pushes dirty state. | **Zero Git Authority**: Hard Python interception blocks all autonomous Git mutations. Commits stay strictly human. |
| **Pre-Commit Cleanliness** | Hardcoded strings and lint errors slip into Git history. | **Deterministic Git Gate**: Staged pre-commit hook runs in <5s and blocks dirty commits before they land. |
| **Device Protection** | AI runs `pm clear` or `adb monkey`, wiping device databases. | **Device Guard**: Hard-denies destructive device commands; binds all execution to physical device serials. |
| **Supply Chain Safety** | Tooling clones mutable `main` branches with potential drifts. | **Pin-to-Tag Provisioning**: Provisions immutable, tag-pinned releases with SHA-256 tamper-evident verification. |

---

## Complete Lifecycle Operations (CLI & AI Chat Prompts)

Every lifecycle operation provides two frictionless execution paths: **CLI-First** (for terminal workflows) and **One-Click Prompts** (for direct IDE AI chat).

### 1. Installation & Greenfield/Existing Project Setup

Set up deterministic governance in any Android or Kotlin Multiplatform repository in under 60 seconds:

#### Path A: Via CLI (Terminal)
```bash
cd /path/to/your/android-project
pipx install git+https://github.com/rabee-elkholy/android-harness-kit.git
android-harness init
```

#### Path B: Via AI Chat (One-Click Prompt)
Open a **new strong-model chat** at your Android repository root and paste:
```markdown
Run the Android Harness Kit Installer:
https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/install-prompt.md
```

The interactive wizard automatically analyzes your project and discovers:
* Gradle application modules, launcher activities, and package names.
* Product Flavors & Build Variants (e.g. `devDebug`, `stagingRelease`, `prodRelease`).
* Architecture stack (MVI / MVVM / Clean Architecture + Koin / Hilt + Room + Jetpack Compose / XML).

---

### What Happens After Installation: Seamless Architectural Adaptation

Once installed, the harness becomes a **native, non-invasive guardian** that seamlessly integrates into your existing codebase:

1. **Adapts to YOUR Architecture (No Forced Rewrites)**:
   * The harness does not impose foreign paradigms or demand code refactoring.
   * **Established / Legacy Codebases**: If your project uses XML Views, ViewBinding, ViewModel + LiveData, and Java interop, the reviewers adapt to enforce `viewLifecycleOwner` Fragment observation, ViewBinding nulling in `onDestroyView()`, and Java/Kotlin nullability boundaries.
   * **Modern / Reactive Codebases**: If your project uses Jetpack Compose, MVI, StateFlow, or Kotlin Multiplatform (KMP), the reviewers enforce Unidirectional Data Flow, atomic `StateFlow.update { }`, 48dp touch targets, and Compose recomposition stability.
   * **Architectural Boundaries**: Agents are strictly barred from violating module boundaries or injecting UI dependencies into Domain/Data layers.

2. **The Invisible Daily Workflow (Silent Guardianship in Action)**:
   * **Step 1: Normal Prompting**: You interact with your AI coding assistant (Cursor, Claude, Copilot, Antigravity) exactly as usual.
   * **Step 2: Transparent Safety Interception**: If the AI attempts destructive shell commands (`git commit`, `git reset --hard`, `pm clear`, `adb monkey`), the harness intercepts the execution in Python, preserves your workspace, and redirects the model safely.
   * **Step 3: Parallel Review Barrier**: When the AI attempts to build (`:assembleDebug`) or run on a device, the harness triggers the **Five-Leaf Review Gate** against the working diff. Once all 5 subagents verify the code with matching SHA-256 evidence footers, APK assembly unlocks automatically.
   * **Step 4: Human-Owned Commits**: You retain full control over your Git history. When you commit from your IDE, the staged pre-commit gate validates string parity and Room schemas in **<5 seconds**.

3. **Zero Team Pollution (Seamless Team Coexistence)**:
   * Local safety hooks and configurations are automatically registered in `.git/info/exclude` and marked with `git update-index --assume-unchanged`.
   * Your team members can work on the same shared repository without experiencing Git merge conflicts or unwanted configuration commits.

---

### 2. Maintenance & Health Diagnostics (12-Dimension Doctor)

Verify the complete health of your harness installation, SDK paths, and configuration at any time:

```bash
# Terminal execution
android-harness doctor

# Or execute via IDE Chat prompt:
# https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/diagnostic-prompt.md
```

The **12-Dimension Harness Doctor** runs 30 automated checks across:
1. **Host Environment**: Python 3.10+ runtime, OS platform, and path isolation.
2. **Android SDK & Toolchain**: `adb`, `JAVA_HOME`, and Gradle wrapper execution.
3. **Subagent Prompt Integrity**: Verifies SHA-256 fingerprints of all 8 reviewer subagents.
4. **Git Hygiene & Cleanliness**: Local hook exclusions (`.git/info/exclude`) and working tree status.
5. **Template Consistency**: Ensures zero unreplaced `{{...}}` placeholders in configs.
6. **Domain References**: Tailored architectural rules and guidelines.
7. **AI Tool Adapters**: Status of configuration files across selected IDEs.
8. **Concurrency Locks**: Ephemeral review state machine locks and TTL hygiene.
9. **Core Safety Selftests**: Verifies passing status of all deterministic security hooks.
10. **Preflight Linters**: String parity, Room migration check, and Fast Kotlin lint.
11. **Project Tracker Security**: Credential isolation and trigger-phrase wiring.
12. **Build Flavors**: Active variant selection and multi-module boundary guards.

---

### 3. Upgrading to New Releases (Update)

Upgrade your harness installation to the latest stable release with pin-to-tag supply-chain safety and zero configuration drift:

```bash
# Terminal execution
android-harness update

# Or execute via IDE Chat prompt:
# https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.12.0/docs/update-prompt.md
```

* Preserves all tailored project preferences, custom domain references, and tracker credentials.
* Automatically creates an isolated snapshot in `.harness-backup/<timestamp>/` before performing the update.

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

## The Five-Leaf Review Gate & Subagents Roster

Before any APK assembly or device execution, the Lead Agent dispatches **5 specialized review subagents in parallel in a single invocation** against a hashed diff of the working tree (`HARNESS_REVIEW_PACKAGE`):

| Specialized Subagent | Pass Token | Review Focus & Quality Invariants |
| :--- | :--- | :--- |
| **`bug-reviewer-agent`** | `BUG_PASS` | Logic correctness, Kotlin null-safety across Java/Kotlin boundaries, Coroutine exception handling, network resiliency, and state preservation across configuration changes. |
| **`convention-reviewer-agent`** | `CONVENTION_PASS` | Unidirectional Data Flow (UDF), Clean Architecture / MVI, zero inline FQCNs, Compose accessibility standards (touch targets >= 48dp, contentDescription). |
| **`security-reviewer-agent`** | `SECURITY_PASS` | Exported components security, deep link intent validation, secret leakage in Logcat, hardcoded tokens, and least-privilege runtime permissions. |
| **`perf-anr-guardian-agent`** | `PERF_PASS` | Intercepts main-thread disk/network I/O, canvas drawing bottlenecks, recomposition loops in Compose, and uncleaned sensor/listener leaks in `DisposableEffect`. |
| **`regression-impact-reviewer-agent`** | `REGRESSION_PASS` | Blast radius analysis, caller graph verification, deep link route integrity, and data model contract stability. |

### On-Demand Specialists (Task-Specific Delegation)
* **`qa-diagnostics-agent`**: Deep Logcat forensics, ANR stack trace parsing, memory leak analysis, and test device inspection.
* **`android-ui-expert-agent`**: Jetpack Compose and XML layout optimization, RTL alignment, accessibility styling, and multi-screen responsiveness.
* **`test-quality-reviewer-agent`**: Audits unit and UI test suites for assertions validity, coroutine test dispatchers, and mock isolation.

Every review round produces a machine-readable verdict record at `.agents/state/verdicts/verdict-<pkg12>.json`. Validate any verdict record using:
```bash
android-harness verify
```

---

## Multi-IDE AI Tool Support (14 Tools, 3 Tiers)

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

## Documentation & Deep-Dives

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
