# Android Agent Harness

> **Stricter proof, not heavier daily workflow.**

Android Agent Harness is an approval-first engineering layer for AI coding tools working on real Android codebases.

It gives agents bounded project context, preserves local architecture, verifies what actually changed, runs proportional Android checks, and binds delivery claims to real test/build/device evidence.

The model focuses on engineering. The harness handles workflow state, proof, and safety boundaries.

[![CI](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/rabee-elkholy/android-agent-harness?label=release)](https://github.com/rabee-elkholy/android-agent-harness/releases)
[![PyPI](https://img.shields.io/pypi/v/android-agent-harness)](https://pypi.org/project/android-agent-harness/)
[![Python](https://img.shields.io/badge/Python-3.10%E2%80%933.14-blue)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
[![Platforms](https://img.shields.io/badge/Linux%20%7C%20macOS%20%7C%20Windows-supported-success)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
[![License](https://img.shields.io/github/license/rabee-elkholy/android-agent-harness)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE)

---

## Why it exists

AI coding agents are good at writing code, but production Android work has a second problem: keeping the agent aligned over time.

As context grows, an agent can infer the wrong local architecture, touch more files than intended, modernize legacy code accidentally, report stale tests/builds as current, miss Room/device/platform risks, or lose track of the approved scope.

Prompt rules help guide behavior. Android Agent Harness moves selected guarantees outside model memory and into deterministic tooling.

---

## What the harness adds

The harness adds five deterministic capabilities around your AI coding assistant:

- **Project-aware discovery**: Bounded AST slicing via Task Context, symbol dependency mapping via Project Graph, source-set awareness, and automatic detection of local architecture families in mixed codebases.
- **Approval-first execution**: Strict plan-before-mutation flow, single-use cryptographic approval nonces, immutable scope and plan hashing, and zero silent scope creep.
- **Adaptive Android verification**: Canonical 6-tier risk classification matching blast radius to verification requirements, including specialized checks for Room schemas, localized string parity, coroutine dispatchers, and device APIs.
- **Evidence-bound delivery**: Tests, reviews, assemble, and device verification are cryptographically bound to the final frozen delivery snapshot. Stale or partial evidence fails closed.
- **Recovery and developer control**: 12-dimension environment diagnostic (`doctor`), deterministic engine self-healing (`repair`), transactional updates with rollback, and 100% developer-owned Git authority.

---

## What daily use looks like

Developer:

> Fix the refresh bug in `ProfileViewModel`.

Harness-assisted agent:

1. Resolves the exact target and local project context.
2. Shows one implementation plan.
3. Waits for explicit approval.
4. Applies only the approved change.
5. Follows the next action reported by the harness (`task status --task-id <id> --next`).
6. Runs only the checks required by the final risk policy.
7. Reports the result with bound test/build/device evidence.

The developer sees the plan, approval point, important blockers, and final result — not the internal plumbing.

```text
Request
  ↓
Project Context
  ↓
Plan + Approval
  ↓
Implementation
  ↓
Adaptive Verification
  ↓
Evidence-Bound Result
```

---

## Quick Start

### Chat installation (recommended)

Open your Android project in your AI coding agent (Claude Code, Gemini CLI / Antigravity, Cursor, Windsurf, Roo Code, or Copilot) and provide this bootstrap prompt:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.59/docs/install-or-update-prompt.md and follow all instructions.
```

The installer runs non-destructively: it inspects project Gradle modules, asks a few essential setup questions, presents an installation plan, installs the managed engine under `.agents/`, and runs environment diagnostics.

### Terminal installation (alternative)

Install the CLI globally with `pipx`:

```bash
# Install the CLI in an isolated environment
pipx install android-agent-harness

# Initialize harness in your Android repository root
android-harness init --repo /path/to/android-project

# Run 12-point diagnostic check
android-harness doctor --repo /path/to/android-project --json
```

Or run directly from a pinned source clone without global installation:

```bash
git clone --depth 1 --branch v1.0.59 --single-branch \
  https://github.com/rabee-elkholy/android-agent-harness.git ~/.android-harness/kit

python ~/.android-harness/kit/harness_cli.py init \
  --repo /path/to/android-project \
  --kit ~/.android-harness/kit
```

In an installed repository, daily commands use the local launcher:

```bash
python .agents/harness.py doctor --json
```

For advanced configuration, see [docs/install-or-update-prompt.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/install-or-update-prompt.md) and [docs/tool-support.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md).

---

## Prompt Rules vs Harness

| Capability | Prompt / AGENTS.md only | Android Agent Harness |
|---|---|---|
| Architecture guidance | Model remembers it | Local project evidence |
| Scope control | Instruction | Plan + deterministic drift checks |
| Approval | Conversational convention | Recorded and plan-bound |
| Tests | Model may run/report them | Execution evidence gate |
| Review | Model judgment | Runtime-policy-routed evidence |
| APK/device | Often ad hoc | Artifact/install/launch identity |
| Dirty tree | Model reasons about it | Baseline-aware task isolation |
| Recovery | Manual | Doctor + deterministic Repair |

> Prompt rules remain useful; the harness makes selected parts verifiable outside the model.

---

## 6-Tier Risk Model

The harness inspects the final classified working tree diff and selects an adaptive verification tier:

| Tier | Name | Typical examples | Typical verification |
|---|---|---|---|
| T0 | TRIVIAL | docs / non-runtime | structural / preflight |
| T1 | LOW_RISK | strings, resources, visual-only UI | bounded deterministic checks, compile as needed |
| T2 | FEATURE | ViewModel, UseCase, normal feature behavior | tests + targeted review + assemble |
| T3 | SUBSYSTEM | multi-module, DI, network, architecture integration | stronger integration/architecture verification |
| T4 | DATA_DEVICE | Room, migrations, permissions, location, FGS, device APIs | specialized gates + runtime/device proof as applicable |
| T5 | CRITICAL | Billing, Auth, Security, Crypto, Sensitive Data | highest applicable review/evidence + sensitive approval |

> Exact reviewers, gates, and device requirements are calculated by the current runtime policy from the final classified change set.

---

## Project-aware, not project-assuming

Real Android repositories are rarely uniform.

One codebase may contain Java + XML + MVP, Kotlin + XML + MVVM, Kotlin + Compose + MVI, callbacks next to Flow, and several source sets/modules.

The harness does not assume one global architecture. It resolves the current task against the nearest evidence-backed local context and preserves that local style unless a migration is explicitly approved.

```text
legacy/profile  → Java + XML + MVP
home            → Kotlin + XML + MVVM
tracking        → Kotlin + Compose + MVI
```

---

## Android-specific protection

- **Room database & schemas**: Schema version tracking, migration path continuity, column drop protection, and destructive fallback prevention (`fallbackToDestructiveMigration`).
- **Compose, XML & resources**: String parity across locales (`values/`, `values-ar/`, etc.), plural/placeholder validation, ViewBinding lifecycle leak checks, and Compose UI state handling.
- **Coroutines, ANR & threading**: Detection of blocking I/O calls on `Dispatchers.Main`, unconfined coroutine scopes, and missing exception handlers.
- **Device & platform APIs**: Foreground services, runtime permissions, location, notifications, Bluetooth/camera, and Android user ID (`u0`) continuity.
- **Gradle build variants & multi-module**: Real variant-aware compilation tasks, split APK handling, artifact set identity, and cross-module dependency validation.

---

## Evidence-bound verification

```text
Final Change Set
      ↓
Runtime Policy
      ↓
Tests / Reviews / Assemble / Device
      ↓
Bound Evidence
      ↓
Final Verifier
```

> Evidence is bound to the exact delivery snapshot/change set. Stale, mismatched, incomplete, or invalid evidence cannot approve delivery.

---

## Supported hosts / enforcement model

| Host | Adapter | Mutation Interception | Approval Trust | Notes |
|---|---|---|---|---|
| **Antigravity / Gemini CLI** | `agents/hooks.json`, rules, skills | `HARD_ENFORCED` / `RULE_ENFORCED` | Native hooks + rule gates | Intercepts tool calls directly |
| **Claude Code** | Pre-tool execution hooks (`config.json`), rules | `HARD_ENFORCED` | Native tool hooks | Blocks unapproved writes |
| **Cursor** | `.cursorrules` / `.cursor/rules` | `RULE_ENFORCED` | Rule guidance + verifier | Downstream verification enforcement |
| **Windsurf** | `.windsurfrules` | `RULE_ENFORCED` | Rule guidance + verifier | Downstream verification enforcement |
| **GitHub Copilot** | `.github/copilot-instructions.md` | `RULE_ENFORCED` | Rule guidance + verifier | Downstream verification enforcement |
| **Roo Code / Continue** | Mode instructions, system rules | `RULE_ENFORCED` | Rule guidance + verifier | Downstream verification enforcement |

Host-native hooks can intercept some mutation classes where supported. Other hosts rely on rule enforcement plus deterministic downstream verification. The harness reports the detected enforcement level honestly.

See [docs/tool-support.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md) for full integration details.

---

## What it does not do

- It is not an Android IDE.
- It is not a coding model.
- It does not replace Android Studio or Gradle.
- It does not guarantee bug-free code.
- It does not make every host OS-sandboxed.
- It does not automatically modernize legacy architecture.
- It does not remove developer authority over Git/release decisions.

---

## Who should use it

**Best fit:**
- Production Android teams using AI coding agents regularly
- Mixed/legacy codebases (Java/Kotlin, XML/Compose, multi-module)
- Apps with Room, payments, auth, permissions, foreground services, or device behavior
- Developers who want AI speed without giving up explicit engineering control

**Probably unnecessary for:**
- Throwaway prototypes
- Tiny demo apps
- One-off code generation

---

## Repository architecture

```text
agents/
├── rules/         # Canonical harness rules and behavioral invariants
├── scripts/       # Deterministic Python standard-library engine and verification gates
├── skills/        # AI host skill definitions and reference contracts
├── subagents/     # Independent specialized reviewer agent definitions
├── tool-adapters/ # Host-specific configuration templates (Claude, Gemini, Cursor, etc.)
└── workflows/     # Task lifecycle and multi-phase orchestration workflows
```

Each component is implemented using Python standard-library modules with zero external runtime dependencies.

---

## Testing / CI

- **Platforms**: Linux (Ubuntu 24.04), Windows (Server 2025), macOS (15).
- **Python Matrix**: Python 3.10, 3.11, 3.12, 3.13, and 3.14 (standard library only; zero pip dependencies).
- **Validation**: Full deterministic selftest suite (`python harness_cli.py selftest`), syntax compilation across all scripts (`python -m compileall`), wheel packaging and lifecycle tests, security/adversarial boundary validation, and multi-phase Android workflow scenario tests.

All pull requests and commits run the complete matrix on GitHub Actions.

---

## Maturity / roadmap

Production-oriented and heavily self-tested. Real-world Android burn-in continues across heterogeneous production codebases.

**Roadmap:**
- Real-repo burn-in across diverse Android topologies
- Performance tuning of Task Context AST slicing
- Host integration refinement for emerging AI environments
- Documentation simplification and developer onboarding polish

---

## Contributing

We welcome contributions! Please review [CONTRIBUTING.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/CONTRIBUTING.md) before submitting pull requests.

1. **Standard Library Only**: All runtime engine code must use Python standard library only.
2. **Safety Invariants**: Never weaken approval gates, plan nonces, or evidence binding.
3. **Deterministic Selftests**: Run `python harness_cli.py selftest` and `python -m compileall -q harness_cli.py agents/scripts` to verify all tests pass cleanly.

For security reports, refer to [SECURITY.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/SECURITY.md).

---

## FAQ

**1. Does this replace Android Studio?**
No. Android Studio remains the primary IDE for Android development, debugging, and profiling. The harness is an engineering control layer for AI coding tools working within the repository.

**2. Does this make the AI autonomous?**
No. The harness is approval-first. All task scopes and risk classifications require explicit developer approval before modifications begin, and delivery requires verified evidence.

**3. Can it work with mixed Java/Kotlin/XML/Compose codebases?**
Yes. The harness detects local architectural conventions per module and source set, ensuring agents preserve existing patterns (such as Java + XML) rather than performing unplanned modernizations.

**4. Does every task run many reviewers?**
No. The 6-tier risk model dynamically assigns verification: trivial edits (T0) and low-risk changes (T1) skip reviewer subagents entirely. Specialized reviewers run only when justified by the final classified blast radius.

**5. Does every task require a device?**
No. Device deployment and mobile verification are required only for tiers and changes involving device-facing surfaces (such as T4/T5 with Room, permissions, or system services) or when explicitly requested.

**6. Can I use Codex / Gemini / Claude / Copilot?**
Yes. Native tool adapters and instruction templates are provided for Claude Code, Gemini CLI / Antigravity, GitHub Copilot, Cursor, Windsurf, Roo Code, and others.

**7. Does the harness commit/push code?**
Never. Git commits, branches, pushes, and release decisions remain 100% developer-owned. The harness leaves modifications unstaged in your working tree.

**8. What happens if the harness itself is corrupted?**
The harness includes deterministic health diagnostics (`doctor`) and self-healing repair (`repair`) that can restore managed engine files from the pinned kit without touching your application source code.

---

## License

MIT License. See [LICENSE](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE).

- [Quickstart Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/quickstart.md)
- [Architecture Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/architecture.md)
- [Workflow Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/workflows.md)
- [Compatibility Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
- [AI Tool Support](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md)
- [Setup Wizard Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/setup-wizard.md)
- [Threat Model](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/threat-model.md)
- [Restore & Recovery](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/restore.md)
