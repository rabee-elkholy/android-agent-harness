<div align="center">

# Android Agent Harness

**Architecture governance, five-leaf parallel review gate, and execution safety harness for Android & Kotlin Multiplatform.**

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

## Why this exists

Coding agents self-report success without verification. They declare a task
finished on vibes, compile nothing, and commit whatever compiles. The harness
puts deterministic gates **outside the model**: a five-leaf review barrier
with evidence footers, a deny-engine that blocks git mutations and unsafe
device commands in every supported tool, a staged pre-commit quality gate
that fires regardless of which agent wrote the code, and a 12-dimension
doctor that proves the installation itself is healthy. The agent cannot
approve itself; the machine checks it.

## The problem we solve

| Without Android Harness | With Android Agent Harness |
| :--- | :--- |
| **Casual "LGTM"**: AI writes code and declares completion without compiling or verifying. | **Mandatory Review Gate**: AI is locked out of assembly until 5 specialized subagents sign off with matching evidence footers (`BUG_PASS`, `CONVENTION_PASS`, `SECURITY_PASS`, `PERF_PASS`, `REGRESSION_PASS`). |
| **Silent Regressions**: Modifying one ViewModel or UI component breaks dependent flows. | **Regression Blast Radius**: Maps every caller, navigation route, and data model to verify impact. |
| **Missing Translations & Broken RTL**: Adding a string in English without adding Arabic or vice versa. | **Bilingual String Parity**: Automated validation enforcing 1-to-1 string parity and Jetpack Compose `@Preview` tags. |
| **UI Freezes & ANRs**: Heavy operations placed on Dispatchers.Main or unnecessary recompositions. | **ANR Guardian**: Static heuristics flag main-thread disk/network I/O, heavy canvas draws, and recomposition loops. |
| **Database Crashes**: Altering `@Entity` schemas without writing Room migrations causes runtime crashes. | **Room Guard**: Validates database schema versions, migration objects, and test coverage before building. |
| **Accidental Git Mutations**: AI commits incomplete code, overwrites branches, or pushes dirty state. | **Git Mutation Guard**: Hard interception blocks all autonomous `git commit` and `git push` commands. |

## Quickstart

```bash
cd your-android-project
pipx install git+https://github.com/rabee-elkholy/android-harness-kit.git
android-harness init          # setup wizard -> answers recorded
```

Then paste the install prompt in a **new strong-model chat** opened at the
Android project root:
`https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.11.0/docs/install-prompt.md`

No pipx? Run in place from any kit clone: `python harness_cli.py --help`.
More CLI: `update` (pin-to-tag upgrade), `preflight` (strings+Room+lint),
`selftest`, `verify` (validate a review verdict.json), `explain --last N`
(safety-hook decision audit), `doctor --device` (12-dimension health audit).
Full CLI reference, install modes A/B, and the one-click prompt library:
[Quickstart Guide](docs/quickstart.md).

## Enforcement levels

| Enforcement | Mechanisms | Applies to |
| :--- | :--- | :--- |
| **Hook-enforced** | Antigravity `PreToolUse` engine; Claude Code `PreToolUse` bridge; Copilot `preToolUse` bridge; universal `.githooks/pre-commit` gate | Antigravity, Claude Code, Copilot (optional hook), every tool's commits |
| **Rule-driven** | Managed adapter files (`.cursor/rules/`, `.windsurf/`, `.roo/`, ...) + command packs + slash commands | Cursor, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, Goose, Qwen, Codex |
| **Prompt-only** | `AGENTS.md` at repo root | Any AGENTS.md reader (Aider, Zed, Amp, Devin, Factory, Jules, Warp, OpenCode, VS Code) |

Full tool-to-template-to-tier mapping: [Tool Support](docs/tool-support.md). Compatibility grid: [Compatibility Matrix](docs/compatibility-matrix.md).

## The five-leaf review gate

Before any build, the agent dispatches 5 reviewers in ONE call against the
same `HARNESS_REVIEW_PACKAGE` (a hashed diff of the working tree). Each leaf
must reply with its PASS token AND the evidence footer
`EVIDENCE pkg=<sha256_12> cites=<n>` matching the package hash - otherwise the
barrier stays up. Machine-verifiable artifact:
`state/verdicts/verdict-*.json`, checked by `android-harness verify`.

| Leaf | Token | Focus |
| :--- | :--- | :--- |
| bug-reviewer-agent | `BUG_PASS` | Logic, null-safety, coroutines, network recovery |
| convention-reviewer-agent | `CONVENTION_PASS` | Architecture, MVI/Clean, accessibility, KMP purity |
| security-reviewer-agent | `SECURITY_PASS` | Component security, secrets, permissions |
| perf-anr-guardian-agent | `PERF_PASS` | Main-thread safety, sensors, WakeLocks, recomposition |
| regression-impact-reviewer-agent | `REGRESSION_PASS` | Blast radius, callers, models, deep links |

On-demand specialists: `qa-diagnostics-agent` (logcat/ANR forensics),
`android-ui-expert-agent` (Compose/XML/RTL), `test-quality-reviewer-agent`
(test suite audits). Full protocol, the 7-stage workflow, the preflight trio
(strings/Room/lint), the 12-dimension doctor, safety hooks, live Gradle
runner, device runner, and PM integrations:
[Architecture Guide](docs/architecture.md).

## Safety highlights

- **Strict Git Mutation Protection**: `git commit/push/reset` (incl. subshell, `git.exe`, chained, homoglyph variants) hard-denied; developers own history.
- **Deterministic Pre-Commit Gate**: stdlib-only `.githooks/pre-commit` (strings + lint + Room) on staged files, <5s, default ON (`--no-git-gate` to opt out).
- **Device safety**: `adb monkey` and `pm clear` denied; device-bound adb requires `-d`/`-s <serial>`; emulator blocked when the project is physical-only.
- **Anti-polling + ephemeral state machine**: busy polling denied; review rounds tracked per conversation (package hashes, re-dispatch lock, TTL expiry).
- **Threat model**: [docs/threat-model.md](docs/threat-model.md). Reporting: [SECURITY.md](SECURITY.md).

## Lifecycle prompts (one click)

Paste into a **new chat** on your Android project root with a strong
reasoning model. Each fetched doc carries a version + SHA-256 header -
verify it before executing.

| Operation | Prompt URL (pinned to v0.11.0) |
| :--- | :--- |
| **Install** | `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.11.0/docs/install-prompt.md` |
| **Update** | `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.11.0/docs/update-prompt.md` |
| **Doctor** | `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.11.0/docs/diagnostic-prompt.md` |
| **Rollback** | `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.11.0/docs/rollback-prompt.md` |

## Demo

*Placeholder: recording guide and shot list in [docs/media/README.md](docs/media/README.md).*

| Shot | Link |
| :--- | :--- |
| 1. Install wizard end-to-end | [GIF slot](docs/media/install.gif) |
| 2. Five-leaf dispatch + evidence footers | [GIF slot](docs/media/review.gif) |
| 3. Blocked git commit + pre-commit gate | [GIF slot](docs/media/safety.gif) |
| 4. 12-dimension doctor report | [GIF slot](docs/media/doctor.gif) |

## Contributing & community

- [Contributing Guide](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [SECURITY.md](SECURITY.md) · [ROADMAP.md](ROADMAP.md) · [docs/](docs/)
- Docs: [Quickstart](docs/quickstart.md) · [Architecture](docs/architecture.md) · [Tool Support](docs/tool-support.md) · [Compatibility](docs/compatibility-matrix.md) · [Threat Model](docs/threat-model.md) · [Setup Wizard Reference](docs/setup-wizard.md) · [ADR](docs/adr/) · [Recipes](docs/recipes/) · [Benchmarks](docs/benchmark/) · [PM Integrations](docs/workflows/pm-integrations.md)
- Report bugs via [Bug Report Form](.github/ISSUE_TEMPLATE/bug_report.yml); propose features via [Feature Request Form](.github/ISSUE_TEMPLATE/feature_request.yml); discuss on [GitHub Discussions](https://github.com/rabee-elkholy/android-harness-kit/discussions).

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE).
