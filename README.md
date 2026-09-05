<div align="center">

# android-agent-harness

### Deterministic Android Engineering for the AI Era
**Turn Any AI Assistant into an Uncompromising Senior Android Engineering Team.**

[![CI Build](https://img.shields.io/github/actions/workflow/status/rabee-elkholy/android-agent-harness/ci.yml?branch=main&style=flat-square&label=CI%20Build)](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml)
[![PyPI Version](https://img.shields.io/pypi/v/android-agent-harness?color=blue&style=flat-square&label=PyPI)](https://pypi.org/project/android-agent-harness/)
[![Latest Release](https://img.shields.io/github/v/release/rabee-elkholy/android-agent-harness?color=2ea44f&style=flat-square&label=Release)](https://github.com/rabee-elkholy/android-agent-harness/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20KMP-3DDC84?style=flat-square)](https://android.com)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square)](https://python.org)
[![Quality Gate](https://img.shields.io/badge/Quality%20Gate-6--Leaf%20Pass-success?style=flat-square)](docs/architecture.md)
[![AI Tools](https://img.shields.io/badge/AI%20Tools-14%20IDs%20%7C%2011%20Templates-8A2BE2?style=flat-square)](docs/tool-support.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](CONTRIBUTING.md)

<br/><br/>
<img src="docs/assets/banner.svg" alt="android-agent-harness: Deterministic Android Engineering for the AI Era" width="100%" />

</div>

---

## Why the Harness? Prompts are Polite Requests. The Harness is an OS-Level Cage.

Prompts, `.cursorrules`, and `SKILL.md` files decay as conversation context expands. AI coding assistants eventually hallucinate success, break Room migrations, ignore RTL layouts, and push unreviewed code.

The **Android Agent Harness** enforces deterministic, cryptographic, and OS-level execution barriers outside the model brain:

| Android Failure Mode | Bare AI Assistant | Android Agent Harness |
| :--- | :--- | :--- |
| **Code Discovery** | Speculative 50-file grepping; reads random source files; burns 100k tokens. | **Universal Code Graph (`project_graph.py`)**: Instant Clean Architecture slices in <100ms. |
| **Room Migrations** | Modifies `@Entity` without migration -> app crashes on user upgrade. | **Room Guard (`room_guard.py`)**: Hard-blocks un-migrated Kotlin & Java entities. |
| **Localization & RTL** | Hardcodes strings, drops Arabic (`values-ar`), scrambles placeholders. | **Adaptive String Guard (`check_strings.py`)**: Sub-second diff-scoped parity check. |
| **ANR & Main-Thread I/O** | Runs disk/network I/O on `Dispatchers.Main`; leaks sensor listeners. | **Perf & ANR Guardian**: Enforces 60/120 FPS fluidity and lifecycle unregistration. |
| **Review Verification** | Model declares "LGTM!" and assumes its own fix works. | **Cryptographic Barrier**: Assembly (`:assembleDebug`) locked until 6 guardians emit SHA-256 tokens. |
| **Rogue Git Commits** | Runs `git commit` or `git push --force` to hide compilation mistakes. | **OS Interceptor (`pre_tool_safety.py`)**: Hard-denies unauthorized Git and ADB mutations. |
| **Host Scrapes & Loops** | Scans developer home directories (`C:\Users\...`) when third-party tools fail. | **Host Sandbox Guard**: Intercepts host filesystem traversals; enforces fail-fast tracker exit. |
| **Legacy Codebases** | Linters output 4,000 legacy errors, stalling delivery. | **Zero Legacy Penalty**: Diff-scoped AST lint (`fast_kt_lint.py`) inspects modified lines in <1s. |

---

### The Cage in Action: Real-Time Interceptions

```text
[MODEL ATTEMPTS] > git push --force origin main
[HARNESS CAGE]   [DENIED] Autonomous git push is strictly blocked. Human developer authority is absolute.

[MODEL ATTEMPTS] > python agents/scripts/run_gradle_task.py :app:assembleDebug
[HARNESS CAGE]   [LOCKED] Cryptographic Review Barrier active. Missing pass tokens: [BUG_PASS, PERF_PASS].

[PREFLIGHT GATE] python agents/scripts/room_guard.py
[HARNESS CAGE]   [FAIL] Room database AppDatabase.kt version was NOT incremented. Destructive fallback banned.

[MODEL ATTEMPTS] > Get-ChildItem -Path "C:\Users\..." -Recurse
[HARNESS CAGE]   [DENIED] Host user directory traversal is strictly blocked. Confine discovery to repository.
```

---

## Universal Code Graph Engine: Graph-First Discovery vs. Brute-Force Grepping

Traditional AI coding tools explore large Android codebases blindly: they launch speculative `grep_search` cascades, guess whether a class is written in Kotlin (`.kt`) or Java (`.java`), read irrelevant files, and exhaust context windows before writing a single line of code.

The **Android Agent Harness** solves this with an integrated, pre-warmed **Universal Code Graph Engine (`project_graph.py`)**:

```text
                                  [Universal Code Graph]
                                             |
      +------------------------------+-------+----------------------+------------------------------+
      |                              |                              |                              |
      v                              v                              v                              v
  UI Layer                     ViewModel Layer                Domain Layer                   Data Layer
[Composables / XML] --deps--> [StateFlow / MVI] --deps--> [UseCases / Interactors] --deps--> [Repositories / Room]
```

### Why the Graph Transforms Agentic Coding:
* **Pre-Warmed & Instant**: Parses thousands of files (Kotlin, Java, XML, Gradle) during setup into an optimized topological cache (`.agents/cache/project_graph.json`).
* **Clean Architecture Slices**: Extract the complete end-to-end stack for any feature in a single CLI call:
  ```bash
  python .agents/scripts/project_graph.py --feature Payment
  # Automatically returns: PaymentScreen -> PaymentViewModel -> ProcessPaymentUseCase -> PaymentRepository -> PaymentDao
  ```
* **Architectural Trace & Dependency Paths**: Find the exact dependency path between two distant components:
  ```bash
  python .agents/scripts/project_graph.py --path-from HomeScreen --path-to UserPreferencesDataStore
  ```
* **UI Screen & Layout Mapping**: Discover all Composables, XML Activities, and their associated ViewModels instantly:
  ```bash
  python .agents/scripts/project_graph.py --screens
  ```
* **Precise Symbol Resolution**: Locate exact file paths, languages (`[COMPOSE]`, `[KOTLIN]`, `[JAVA]`, `[XML]`), and incoming/outgoing edges without guessing:
  ```bash
  python .agents/scripts/project_graph.py --find ProfileRepository
  ```
* **80%+ Token Savings**: Eliminates exploratory reading loops, cutting discovery phase token consumption by over 80%.

---

## The 6 Parallel Quality Guardians

Before `:app:assembleDebug` or device deployment, 6 specialized subagents review the immutable snapshot in parallel:

```text
                            +---> [bug-reviewer-agent]              ---> BUG_PASS
                            +---> [convention-reviewer-agent]       ---> CONVENTION_PASS
[Review Package (SHA-256)] -+---> [security-reviewer-agent]         ---> SECURITY_PASS
                            +---> [perf-anr-guardian-agent]         ---> PERF_PASS
                            +---> [regression-impact-reviewer-agent] ---> REGRESSION_PASS
                            +---> [test-quality-reviewer-agent]     ---> TEST_PASS (Smart Test Promotion)
```

1. **`bug-reviewer-agent`** (`BUG_PASS`): Logic bugs, Kotlin null-safety across Java boundaries, and coroutine cancellation leaks.
2. **`convention-reviewer-agent`** (`CONVENTION_PASS`): Clean Architecture, MVI StateFlow immutability, zero inline FQCNs.
3. **`security-reviewer-agent`** (`SECURITY_PASS`): OWASP Mobile Top 10, unexported components, and credential isolation.
4. **`perf-anr-guardian-agent`** (`PERF_PASS`): ANR elimination, Main-thread I/O prevention, and Compose recomposition fluidity.
5. **`regression-impact-reviewer-agent`** (`REGRESSION_PASS`): Blast radius analysis, caller graph impacts, and API signature changes.
6. **`test-quality-reviewer-agent`** (`TEST_PASS`): **Smart Test Promotion** — automatically promoted on test/mock diffs to verify assertion depth and `runTest` dispatchers.

*On-demand specialists:* `qa-diagnostics-agent` (Logcat crash forensics) & `android-ui-expert-agent` (Compose & RTL layouts).

---

## The Zero-Assumption Barrier & Interactive Discovery

AI assistants frequently jump into implementation based on flawed assumptions about business logic or edge cases. The harness enforces a strict **Zero-Assumption Protocol**:

1. **Mandatory Missing-Scenario Audit**: After graph discovery and before proposing an implementation plan, the agent must systematically audit for unmentioned edge cases:
   - **Network States**: Offline behavior, timeout policies, friendly error message mappings.
   - **State Invariants**: Missing/empty identifiers (e.g. empty country/ISO codes, unauthenticated sessions).
   - **Data Lifecycles**: Cache TTL, cache invalidation triggers, and empty list states.
2. **Proactive Developer Interviewing**: If any scenario is underspecified, the agent **MUST** interview the developer using interactive choice modals (`ask_question`). Guessing business logic from scratch is strictly forbidden.
3. **Attached Media First-Turn Inspection**: Whenever the developer provides a screenshot or video recording, the agent inspects it via `view_file` in the very first turn to correlate on-screen visual bugs directly with the code.

---

## Physical Device Verification & Interactive Sign-off

Software that compiles is not necessarily software that works on mobile. The harness:
1. Resolves connected physical devices via ADB (prioritizing physical devices over emulators).
2. Builds and installs via `run_device.py install-start`, launching the target Activity directly.
3. Generates **2 to 3 diff-grounded manual test steps** and triggers an interactive confirmation modal (`ask_question`):
   `PASS -- Device testing passed successfully` vs `FAIL -- Issue or crash encountered`.

---

## Quickstart in 60 Seconds

### Option A: Via AI Chat Prompt (Recommended)
Open a new chat session in your AI assistant (Antigravity, Claude Code, Cursor, Copilot, Windsurf) at your project root and paste:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/main/docs/install-or-update-prompt.md and follow all its instructions.
```

### Option B: Via Terminal CLI
```bash
pip install android-agent-harness
# or via pipx for an isolated global command:
pipx install android-agent-harness
android-harness init
```

---

---

## Environment Adaptability: Native Superpowers with Zero-Degradation Parity

The harness automatically detects the host assistant environment at runtime (`_environment.py`) and seamlessly leverages platform-specific superpowers while preserving 100% verification rigor across portable CLI assistants:

| Capability | Google Antigravity | OpenAI Codex / Claude Code / Cursor |
| :--- | :--- | :--- |
| **Command Execution** | **Self-Healing Rewrite**: PreToolUse hook automatically rewrites `./gradlew ...` to `run_gradle_task.py` via `overwrite`. | **Fail-Closed Guidance**: Intercepts raw gradlew and outputs portable script replacement. |
| **Delivery Barrier** | **Physical Stop Hook**: `delivery-stop-guard` intercepts termination if unreviewed code exists; includes diff-aware loop breaker. | **Cross-Platform Bridge (`record_review.py`)**: Direct verdict artifact generation with strict gate parity. |
| **Review Summaries** | **Generative UI Widgets**: Inline `<agent-embed>` Tailwind CSS cards with collapsible review accordions (`render_ui.py`). | **High-Signal Markdown**: Clean ASCII tables with zero emojis and sub-second rendering. |
| **Missing Scenarios** | **Interactive Modals (`ask_question`)**: Clickable radio options for edge-case alignment and device sign-off. | **Structured Chat Handshakes**: Structured prompts with explicit choices matching user conversation language. |
| **Design Alignment** | **Proactive Slash Commands**: Recommends `/grill-me` for design alignment and `/goal` for tasks. | **Standard Interactive Prompts**: Direct step-by-step TDD interviews. |

---

## Supported AI Environments (14 Tools, 3 Tiers)

* **Hook-Enforced & Adaptive**: Google Antigravity (PreToolUse self-healing overwrite, Stop lifecycle hook, Generative UI), Claude Code, GitHub Copilot.
* **Rule-Driven with Parity Bridge**: OpenAI Codex, Cursor, Windsurf, Cline, Roo Code, Amazon Q, Continue, Junie, Kilo, Goose, Qwen (`record_review.py` 100% parity).
* **Prompt-Only**: Aider, Zed, Devin, Amp, Factory, Jules, Warp, OpenCode (`AGENTS.md` standard).

---

## Documentation & Deep-Dives

* **[Architecture Guide](docs/architecture.md)**: 7-stage delivery lifecycle, safety interceptor mechanics, and preflight pipeline.
* **[Developer Workflows](docs/workflows.md)**: 10 structured engineering playbooks (TDD, forensic triage, ANR audit, preflight).
* **[Quickstart & CLI](docs/quickstart.md)**: Complete CLI command matrix and environment setup.
* **[Threat Model & Security](docs/threat-model.md)**: Analysis of 7 threat vectors and mitigation layers.
* **[Architecture Decision Records (ADRs)](docs/adr/)**: Formal ADRs (001-006) covering review gates, human git authority, and conflict adjudication.

---

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
