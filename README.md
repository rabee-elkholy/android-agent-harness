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

## What it actually stops

Every row below is a failure mode we have watched AI agents hit on a real Android codebase, and the concrete mechanism that now stops it.

| Without the harness | With the harness |
|---|---|
| The agent reports "tests pass" from a run that predates its last edit. | Test, review, assemble and device evidence is bound to a frozen delivery snapshot. Any later edit makes it stale, and delivery fails closed. |
| A bug is "fixed" without ever being reproduced. | Bug tasks require a captured RED: a new test that fails before the fix, recorded as evidence. Tests that were already failing are never accepted as the reproduction. |
| Tests that were already broken block the task or get blamed on the change. | A test baseline is captured at install. Only new failures block; known debt is reported separately. |
| The agent edits files the developer never agreed to. | The plan pins expected files and surfaces. On Antigravity, native hooks deny out-of-scope writes before they happen; on every host, drift is re-checked at verification. |
| The agent approves its own plan, cancels its own task, or commits. | Approval must cite the developer's words in chat. Cancel, commit, merge, rebase and push stay with the developer. |
| A risky change gets the same light review as a string fix. | A 6-tier risk model routes reviewers and gates from the final diff: none for trivial changes, specialists for Room, security or device surfaces. |
| A large change is reviewed only once, at the end. | Multi-phase tasks checkpoint each phase; substantial or risky phases get a scoped delta review before the next begins. |
| The developer asks for a change after verification and the workflow wedges. | `task resume --reopen` sends a verified task back to implementation under the same approval, and it is re-verified. |
| A new chat forgets the team's conventions. | Project notes and scoped developer instructions live in the repo and are pinned into every matching plan. |

---

## What the harness adds

The harness adds six engineering capabilities around your AI coding assistant:

- **Persistent project knowledge**: Generated project facts plus human project notes and scoped developer instructions give future task sessions durable repo-local context without depending on one chat history.
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

### Large-Task & Multi-Phase Flow

> Large tasks can be split into coherent phases. When a phase is substantial or risk-sensitive, reviewers inspect the immutable delta for that phase instead of seeing the whole large change for the first time at the end. Final verification still performs an integration-focused review across the completed task.

Complex tasks execute through sequential phases under a single initial approval:
```text
one task approval
→ phase implementation
→ deterministic checkpoint
→ scoped phase delta review (when selected)
→ next phase
→ final integration review
→ assemble/device
→ developer signoff
→ final verify
→ developer Git commit
→ deliver
```

- **Semantic boundaries**: Phases represent coherent engineering steps, not mechanical 200-line splits.
- **Proportional review**: Small or trivial phases skip AI review; substantial deltas (e.g. >= 180 changed lines) or elevated risks trigger 1–2 policy-routed specialists.
- **Final integration review**: Intermediate phase reviews do not replace the final integration review across the completed task.

### Urgent Task Interruption & Worktree Handoff

When an urgent hotfix or bug interrupts an in-progress task (Task A):
```text
Task A
→ task handoff (freeze WIP snapshot)
→ developer WIP commit
→ reconcile handoff (lineage receipt verified)
→ developer creates separate worktree (git worktree add ../repo-task-b HEAD)
→ Task B in new chat / worktree
→ return to Task A worktree / chat
→ task status --next
```

**Key Invariants & Boundaries:**
- **One live task per worktree**: Each worktree maintains isolated task state. Never run multiple concurrent tasks in the same worktree.
- **Lineage preservation**: An accepted WIP commit does not cancel or pause Task A; it preserves Task A's lineage receipt chain.
- **Model never executes Git mutations**: Git commit, worktree, branch, merge, and rebase operations are strictly 100% developer-owned.
- **Raw commits blocked**: Random unregistered commits in Task A remain lineage violations; only a validated handoff checkpoint commit with accepted lineage receipt is allowed.
- **Arbitrary merges blocked**: Arbitrary external merge/rebase into an active Task A worktree remains blocked; finish or hand off first.
- **Chat independence**: Returning to Task A uses persisted harness state on disk (`task status --next`), never chat memory.

---

## Quick Start

### Chat installation (recommended)

Open your Android project in your AI coding agent (Claude Code, Codex, Gemini CLI / Antigravity, Cursor, Windsurf, Roo Code, or Copilot) and provide this bootstrap prompt:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.1.1/docs/install-or-update-prompt.md and follow all instructions.
```

The installer runs non-destructively: it inspects project Gradle modules, asks a few essential setup questions, presents an installation plan, installs the managed engine under `.agents/`, and runs environment diagnostics. The full harness kit source checkout lives outside the target application (`~/.android-harness/kit`), while your Android project receives only the managed harness runtime payload under `.agents/`.

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
git clone --depth 1 --branch v1.1.1 --single-branch \
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
| Cross-chat project conventions | Repeated manually / prompt-dependent | Repo-local Project Notes + scoped Developer Instructions |
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

## Persistent Project Knowledge

> **The project remembers, even when the chat doesn’t.**
>
> Android Agent Harness keeps durable engineering context inside the repository instead of relying on one chat session or one model’s memory.

Persistent project knowledge is structured across three distinct layers:

### 1. Generated Project Facts
Machine-derived local architecture, Gradle modules, source sets, UI frameworks (Compose, XML, ViewBinding), persistence patterns (Room, SQLite, DataStore), conventions, and symbol dependency graphs. These live in `.agents/project-context/` (`project-facts.json`, `architecture.md`, `ui.md`, `persistence.md`, `conventions.md`) and are refreshed deterministically from source code.

### 2. Human Project Notes
For durable domain knowledge, team conventions, and non-obvious engineering decisions that cannot be inferred from code alone.

```text
Developer:
"Never inject or call Retrofit APIs directly from ViewModels. Always route through Repository interfaces, map DTOs to domain models, and expose state via StateFlow."
```

Command:
```bash
python .agents/harness.py context note \
  "Never inject or call Retrofit APIs directly from ViewModels. Always route through Repository interfaces, map DTOs to domain models, and expose state via StateFlow."
```

- Stored in `.agents/project-context/project-notes.md`.
- Preserved across context refreshes.
- Informs future task discovery and planning. Applicable scoped Developer Instructions are pinned into the plan and review package.
- Clarifies developer intent; cannot overrule contradictory source code facts.

### 3. Scoped Developer Instructions
For explicit engineering rules intended to apply to future matching tasks based on module, package, path, or feature scope.

```text
Developer:
"Whenever we touch payments, preserve the existing callback bridge. Do not migrate it to Flow unless I explicitly ask."
```

Command:
```bash
python .agents/harness.py context instruct \
  "Preserve the existing callback bridge. Do not migrate it to Flow unless explicitly requested." \
  --scope "MODULE::payments" \
  --source conversation \
  --proof-reference "<developer phrase>" \
  --strength REQUIREMENT
```

Supported scopes: `GLOBAL`, `MODULE`, `SOURCE_SET`, `PACKAGE`, `FEATURE`, `ARCH_FAMILY`, `PATH`.

### Truth Hierarchy

When resolving context for task planning and review, the harness applies a strict hierarchy of authority:

```text
Current source evidence
    ↓
Generated project facts
    ↓
Developer notes / scoped instructions
    ↓
Generic Android guidance
```

Current source code evidence is always the highest truth. Project notes and scoped instructions explain developer intent and constraints. Generic model advice or external best-practices never override local codebase evidence.

### Cross-Chat Example

```text
Monday — Chat A
Developer: "Never use destructive Room migration in this app."
→ record as project instruction

Two weeks later — Chat B
Developer: "Add a field to UserEntity."
→ Task Context resolves the applicable persistence instruction
→ plan includes the existing migration constraint
→ agent does not depend on remembering Chat A
```

The harness rehydrates and matches repo-local context; the chat provider itself is not claimed to remember.

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

## Antigravity-First Architecture & Review Protocol V2

The harness is engineered primary-first for **Google Antigravity**:

For materially ambiguous work, Antigravity's `/grill-me` can clarify design decisions before plan drafting. After approval, `/goal` can sustain execution while the Harness router remains the authority for next actions and completion.

- **Review Protocol V2**: Specialist reviewers return structured, machine-verifiable JSON (`HARNESS_REVIEW_RESULT_V2`) rather than fragile text tokens. Findings are typed, prioritized, and cryptographically bound to the frozen delivery snapshot, change set, and review package digest.
- **Dedicated Custom Reviewer Subagents**: Seven core specialist reviewers are installed directly as Antigravity custom agents under `.agents/agents/<reviewer>/agent.md` (`bug-reviewer-agent`, `security-reviewer-agent`, `perf-anr-guardian-agent`, `convention-reviewer-agent`, `regression-impact-reviewer-agent`, `test-quality-reviewer-agent`, `spec-compliance-agent`).
- **Reviewer Model Inheritance by Omission**: Reviewer subagents inherit the authoritative model of the lead agent by omission. No model escalation or manual model routing parameters are passed.
- **Parallel Routed Reviews**: Dynamic review policies resolve the minimal required reviewer roster. All routed reviewers are dispatched concurrently via Antigravity `invoke_subagent` without intermediate prompt stops.
- **Reviewer Call Safety Cap**: Maximum safety ceiling on total reviewer model calls (recommended: 20).
- **Same-Conversation Protocol Recovery**: Malformed initial reviewer responses trigger exact `send_message` corrections within the same conversation ID, preventing runaway subagent spawns.
- **PostToolUse Launch Reconciliation**: Subagent invocation errors are trapped by native `PostToolUse` hooks, transitioning pending reviewers to `ENV_BLOCKED` and returning actionable diagnostic guidance.
- **Hard Mutation Interception**: `.agents/hooks.json` intercepts tool write calls (`multi_replace_file_content`, `replace_file_content`, `write_to_file`) to ensure changes stay strictly within approved scope and phases.

---

## Supported hosts / enforcement model

| Host | Adapter | Mutation Interception | Review proof | Downstream verifier |
|---|---|---|---|---|
| **Google Antigravity** | `agents/hooks.json`, custom agents (`.agents/agents/`), rules, skills | Native hooks (`HARD_ENFORCED`) | Trusted transcript Review V2 | Yes |
| **Claude Code** | `.claude/settings.json`, rules | Installed pre-tool hooks where available | V1 response ingestion; independence not natively verified | Yes |
| **Codex** | Root `AGENTS.md`, `.codex/` instructions | Rule/sandbox dependent | V1 response ingestion; independence not natively verified | Yes |
| **Cursor** | `.cursorrules` / `.cursor/rules` | `RULE_ENFORCED` | V1 response ingestion | Yes |
| **Windsurf** | `.windsurfrules` | `RULE_ENFORCED` | V1 response ingestion | Yes |
| **GitHub Copilot** | `.github/copilot-instructions.md` | `RULE_ENFORCED` | V1 response ingestion | Yes |
| **Gemini CLI** | Rules, instructions | `RULE_ENFORCED` | V1 response ingestion | Yes |
| **Roo Code / Continue** | Mode instructions, system rules | `RULE_ENFORCED` | V1 response ingestion | Yes |

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
- It is not a general-purpose cross-project/cloud chat-memory system; persistent project knowledge is repo-local harness context.
- It does not automatically merge/rebase concurrent worktrees or infer ownership of arbitrary external commits.

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

## Field-tested

Version 1.1.0 is the first release line declared stable. Before it shipped, the harness drove Google Antigravity through four end-to-end rounds on a disposable copy of a production Android app (Kotlin and Java, XML and Compose, MVVM and MVI, Hilt, Room, Arabic and English resources), with a human in the developer role approving plans, reviewing diffs and making every commit.

Those rounds covered ordinary daily work: date-logic bugs reproduced with failing tests, copy fixes across locales, ViewModel validation, a two-phase feature with scoped phase review, a new screen following the project's preferred architecture, developer-requested changes after verification, and harness updates between tasks. Every defect found in a round was fixed with a failing regression test first, and all of them are covered by the deterministic selftest suite that runs on every commit.

## Maturity / roadmap

Stable for daily use on Google Antigravity, where enforcement is hook-backed. Other hosts are supported with rule-level enforcement plus the same downstream verification. Real-world burn-in continues across more Android codebases.

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

**9. Will a new chat remember my project rules?**
Yes, through repo-local context. Project notes (`project-notes.md`) and scoped developer instructions (`developer-instructions.json`) persist inside the repository. When a new chat begins, Task Context and Discovery automatically carry applicable instructions into task planning. The chat provider itself does not need to remember previous conversations. Current source evidence remains the highest authority.

**10. Can I interrupt a large task for an urgent fix?**
Yes. Run `python .agents/harness.py task handoff --task-id <id>` to freeze a safe WIP checkpoint, create one developer WIP commit, and validate it with `python .agents/harness.py task reconcile-handoff --task-id <id>`. Then create a separate Git worktree for the urgent fix (Task B). When finished, return to Task A's worktree and resume via `python .agents/harness.py task status --next`. Never run two live tasks in the same worktree.

**11. Does every phase run AI reviewers?**
No. Deterministic checks (Room schema guards, string parity, fast ktlint, and targeted unit tests) remain primary. Scoped phase delta review runs only when the phase delta is substantial (e.g. >= 180 changed lines), elevates canonical risk (such as `T4_DATA_DEVICE` or `T5_CRITICAL`), touches critical surfaces, or is explicitly requested. Even then, only 1–2 policy-routed specialists review the phase delta. Final integration review across the completed task remains authoritative.

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
