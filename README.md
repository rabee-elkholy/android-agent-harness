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
| **Room Migrations** | Modifies `@Entity` without migration -> app crashes on user upgrade. | **Room Guard (`room_guard.py`)**: Hard-blocks un-migrated Kotlin & Java entities. |
| **Localization & RTL** | Hardcodes strings, drops Arabic (`values-ar`), scrambles placeholders. | **Adaptive String Guard (`check_strings.py`)**: Sub-second diff-scoped parity check. |
| **ANR & Main-Thread I/O** | Runs disk/network I/O on `Dispatchers.Main`; leaks sensor listeners. | **Perf & ANR Guardian**: Enforces 60/120 FPS fluidity and lifecycle unregistration. |
| **Review Verification** | Model declares "LGTM!" and assumes its own fix works. | **Cryptographic Barrier**: Assembly (`:assembleDebug`) locked until 6 guardians emit SHA-256 tokens. |
| **Rogue Git Commits** | Runs `git commit` or `git push --force` to hide compilation mistakes. | **OS Interceptor (`pre_tool_safety.py`)**: Hard-denies unauthorized Git and ADB mutations. |
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
```

---

## The 6 Parallel Quality Guardians

Before `:app:assembleDebug` or device deployment, 6 specialized subagents review the immutable snapshot in parallel:

1. **`bug-reviewer-agent`** (`BUG_PASS`): Logic bugs, Kotlin null-safety across Java boundaries, and coroutine cancellation leaks.
2. **`convention-reviewer-agent`** (`CONVENTION_PASS`): Clean Architecture, MVI StateFlow immutability, zero inline FQCNs.
3. **`security-reviewer-agent`** (`SECURITY_PASS`): OWASP Mobile Top 10, unexported components, and credential isolation.
4. **`perf-anr-guardian-agent`** (`PERF_PASS`): ANR elimination, Main-thread I/O prevention, and Compose recomposition fluidity.
5. **`regression-impact-reviewer-agent`** (`REGRESSION_PASS`): Blast radius analysis, caller graph impacts, and API signature changes.
6. **`test-quality-reviewer-agent`** (`TEST_PASS`): **Smart Test Promotion** — automatically promoted on test/mock diffs to verify assertion depth and `runTest` dispatchers.

*On-demand specialists:* `qa-diagnostics-agent` (Logcat crash forensics) & `android-ui-expert-agent` (Compose & RTL layouts).

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
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v0.27.6/docs/install-or-update-prompt.md and follow all its instructions.
```

### Option B: Via Terminal CLI
```bash
pip install android-agent-harness
# or via pipx for an isolated global command:
pipx install android-agent-harness
android-harness init
```

---

## Supported AI Environments (14 Tools, 3 Tiers)

* **Hook-Enforced**: Google Antigravity, Claude Code, GitHub Copilot (deterministic Python OS-level interceptors).
* **Rule-Driven**: Cursor, Windsurf, Cline, Roo Code, Amazon Q, Continue, Junie, Kilo, Goose, Qwen, Codex.
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
