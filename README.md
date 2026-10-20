# Android Agent Harness

> **Stricter proof, not heavier daily workflow.**

Android Agent Harness is an approval-first engineering layer for AI coding tools working on real Android codebases.

It gives agents bounded project context, records the approved architecture and scope, checks the resulting changes, and requires the test, build, review, or device evidence selected by policy.

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

## Failure modes it checks

The mechanisms below check these failure modes within the configured host and verification boundaries. Native interception depends on the host; downstream verification applies to commands run through the harness.

| Without the harness | With the harness |
|---|---|
| The agent reports "tests pass" from a run that predates its last edit. | Test, review, assemble and device evidence is bound to a frozen delivery snapshot. Any later edit makes it stale, and delivery fails closed. |
| A bug is "fixed" without ever being reproduced. | Applicable BUG tasks require a new failing-test reproduction before the fix. Presentational changes and explicitly supported manual, device, or log reproductions follow the reproduction policy; a pre-existing failure alone does not establish RED. |
| Tests that were already broken block the task or get blamed on the change. | Installation and task-start captures can identify pre-existing failures. Recognized unrelated debt is reported separately; unmatched failures and suspected flaky results still block verification. |
| The agent edits files the developer never agreed to. | The plan pins expected files and surfaces. On Antigravity, installed native hooks can deny supported out-of-scope tool writes. Verification checks scope drift on every supported host. |
| The agent approves its own plan, cancels its own task, or commits. | Approval must cite the developer's words in chat. Cancel, commit, merge, rebase and push stay with the developer. |
| A risky change gets the same light review as a string fix. | A 6-tier risk model routes reviewers and gates from the final diff: none for trivial changes, specialists for Room, security or device surfaces. |
| A large change is reviewed only once, at the end. | Multi-phase tasks checkpoint each phase; substantial or risky phases get a scoped delta review before the next begins. |
| The developer asks for a change after verification and the workflow wedges. | `task resume --reopen` sends a verified task back to implementation under the same approval, and it is re-verified. |
| A new chat forgets the team's conventions. | Project notes and scoped developer instructions live in the repo. Applicable instructions are selected during planning; this does not provide memory to the chat provider. |

---

## What the harness adds

The harness adds six engineering capabilities around your AI coding assistant:

- **Persistent project knowledge**: Generated project facts plus human project notes and scoped developer instructions give future task sessions durable repo-local context without depending on one chat history.
- **Project-aware discovery**: Bounded AST slicing via Task Context, symbol dependency mapping via Project Graph, source-set awareness, and automatic detection of local architecture families in mixed codebases.
- **Approval-first execution**: Plan-before-mutation flow, plan hashes and approval receipts, with scope drift checks. Conversation-based approval is rule-enforced; a hash binds the recorded plan but does not authenticate the human who approved it.
- **Adaptive Android verification**: Canonical 6-tier risk classification matching blast radius to verification requirements, including specialized checks for Room schemas, localized string parity, coroutine dispatchers, and device APIs.
- **Evidence-bound delivery**: Tests, reviews, assemble, and device verification are cryptographically bound to the final frozen delivery snapshot. Stale or partial evidence fails closed.
- **Recovery and developer control**: Environment and installation diagnostics (`doctor`), restoration from a checksum-verified pinned kit (`repair`), transactional updates with rollback, and developer authority over Git operations.

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
- **Proportional review**: Routine `< 400`-line feature phases and the final phase before `prepare-verification` use fast deterministic checkpoints only (`preflight`, Room guards, localized string parity, fast ktlint, and targeted unit tests); substantial intermediate deltas (`>= 400` changed lines), elevated risks (`T3_SUBSYSTEM` through `T5_CRITICAL`), critical surfaces, or explicitly opted-in phases trigger 1–2 policy-routed specialists.
- **Final integration review**: Intermediate phase reviews do not replace the final integration review across the completed task.

### Continuing across AI hosts

An approved task can continue in another supported AI host using the same checkout.
Stop the former executor, then let the receiving agent run `task continue --host
<actual-host> --source-stopped`. The task keeps its approval and progress; interrupted
review runs are archived and restarted through the receiving host's real protocol,
while valid deterministic proof is retained with its original provenance. See
[cross-host continuation](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/host-continuation.md) for commands and enforcement limits.

### Urgent Task Interruption & Worktree Handoff

For overlapping files or independent builds, use a separate worktree. When an urgent hotfix or bug interrupts an in-progress task (Task A):
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
- **At most three live tasks per worktree**: Each task reserves explicit, disjoint files and keeps its own approval, baseline, reviews, and evidence. Pending approval and READY_FOR_DELIVERY tasks count toward the limit. Deliver or cancel a task before opening a fourth.
- **Lineage preservation**: An accepted WIP commit does not cancel or pause Task A; it preserves Task A's lineage receipt chain.
- **Developer Git authority**: Installed client-project policy reserves commit, worktree, branch, merge, rebase, and push decisions for the developer. Technical interception depends on host capabilities.
- **Bound commit lineage**: Validated WIP checkpoints and commits matching verified files of a disjoint sibling task are accepted. Unrelated commits and commits that mix unverified files remain lineage violations.
- **Arbitrary merges blocked**: Arbitrary external merge/rebase into an active Task A worktree remains blocked; finish or hand off first.
- **Chat independence**: Returning to Task A uses persisted harness state on disk (`task status --next`), never chat memory.

---

## Quick Start

### Chat installation (recommended)

Open your Android project in your AI coding agent (Claude Code, Codex, Gemini CLI / Antigravity, Cursor, Windsurf, Roo Code, or Copilot) and provide this bootstrap prompt:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.1.39/docs/install-or-update-prompt.md and follow all instructions.
```

The installer runs non-destructively: it inspects project Gradle modules, asks a few essential setup questions, presents an installation plan, installs the managed engine under `.agents/`, and runs environment diagnostics. The full harness kit source checkout lives outside the target application (`~/.android-harness/kit`), while your Android project receives only the managed harness runtime payload under `.agents/`.

### Terminal installation (alternative)

Install the CLI globally with `pipx`:

```bash
# Install the CLI in an isolated environment
pipx install android-agent-harness

# Initialize harness in your Android repository root
android-harness init --repo /path/to/android-project

# Inspect environment and installation health
android-harness doctor --repo /path/to/android-project --json
```

Or run directly from a pinned source clone without global installation:

```bash
git clone --depth 1 --branch v1.1.39 --single-branch \
  https://github.com/rabee-elkholy/android-agent-harness.git ~/.android-harness/kit

python ~/.android-harness/kit/harness_cli.py init \
  --repo /path/to/android-project \
  --kit ~/.android-harness/kit
```

In an installed repository, daily commands use the local launcher:

```bash
python .agents/harness.py doctor --json
```

### Updating

At the start of a conversation, an installed harness tells the agent (at most once a day, checking for new releases every six hours) when a newer release exists. Ask the agent to update and it runs `python .agents/harness.py update-info`, which prints the exact prompt and command for this installation. To update, finish or cancel the active task, then paste the same prompt with the new version in a new chat, or run:

```bash
python ~/.android-harness/kit/harness_cli.py update --repo /path/to/android-project
```

The update is transactional and rolls back on failure. It keeps task history and state, setup answers, project notes and developer instructions. The default update refuses while tasks are active and lists locally edited managed files. An explicit stopped-source update can preserve one active task; multiple live tasks still block that path. An explicit discard-local-edits option keeps a backup before replacing eligible managed edits. If an update is interrupted (the process is killed), `.agents/VERSION` keeps the previous release and `doctor` reports it; running the update again rolls the interrupted one back, including `GEMINI.md`/`AGENTS.md`/`CLAUDE.md`, and applies it from the start.

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

- **Room database & schemas**: Source-based checks for version changes, numeric migration paths, Kotlin/Java embedded types, risky schema changes, and unconditional destructive fallback. These heuristics do not replace Room schema export validation or migration tests.
- **Compose, XML & resources**: String parity across locales (`values/`, `values-ar/`, etc.), plural/placeholder validation, ViewBinding lifecycle leak checks, and Compose UI state handling.
- **Coroutines, ANR & threading**: Pattern-based checks for selected blocking calls, coroutine scope risks, and exception-handling patterns. Static checks cannot establish freedom from ANRs or concurrency bugs.
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

For design, migration, compatibility and security decisions the agent asks the developer before drafting the plan. After approval it follows the Harness router, the authority for next actions and completion, until the task ends. Every plan also gets a readable, generated `plan.md` linked from the approval question.

- **Review Protocol V2**: Specialist reviewers return structured, machine-verifiable JSON (`HARNESS_REVIEW_RESULT_V2`) rather than fragile text tokens. Findings are typed, prioritized, and cryptographically bound to the frozen delivery snapshot, change set, and review package digest.
- **Dedicated Custom Reviewer Subagents**: Seven core specialist reviewers are installed directly as Antigravity custom agents under `.agents/agents/<reviewer>/agent.md` (`bug-reviewer-agent`, `security-reviewer-agent`, `perf-anr-guardian-agent`, `convention-reviewer-agent`, `regression-impact-reviewer-agent`, `test-quality-reviewer-agent`, `spec-compliance-agent`).
- **Developer-selected reviewer models & per-reviewer model visibility**: Inheritance remains the default. On Google Antigravity, the router prompts once before first dispatch (`SELECT_REVIEW_MODEL`: `flash-dynamic-task`, `flash-dynamic-once`, `inherit-task`, `inherit-once`, `hybrid-smart-task`) or accepts explicit model/thinking choices (`gemini-3.8-flash-*`, `gemini-4-argon-*`, `gemini-3.1-pro-*`), syncs `.agents/agents/<role>/agent.md` frontmatter, and verifies native SQLite execution metadata (`NATIVE_METADATA_OBSERVED`). Claude Code supports native model aliases (`sonnet`, `opus`, `haiku`) or per-role choices. Every router action, status report, and chat update displays each reviewer alongside its active model (`<role> [<model>]`). See [reviewer model configuration](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/reviewer-models.md).
- **Parallel Routed Reviews**: Central policy selects the required reviewer roster. Antigravity dispatch commands prepare concurrent `invoke_subagent` calls when the host supports them; protocol and environment blockers remain explicit.
- **Reviewer Call Safety Cap**: Maximum safety ceiling on total reviewer model calls (recommended: 20).
- **Same-Conversation Protocol Recovery**: Malformed initial reviewer responses trigger exact `send_message` corrections within the same conversation ID, preventing runaway subagent spawns.
- **PostToolUse Launch Reconciliation**: Subagent invocation errors are trapped by native `PostToolUse` hooks, transitioning pending reviewers to `ENV_BLOCKED` and returning actionable diagnostic guidance.
- **Mutation Interception**: Installed `.agents/hooks.json` commands check supported tool writes (`multi_replace_file_content`, `replace_file_content`, `write_to_file`) against approved scope and phases. This is a host hook boundary, not an operating-system sandbox.

---

## Supported hosts / enforcement model

| Host | Adapter | Mutation Interception | Review proof | Downstream verifier |
|---|---|---|---|---|
| **Google Antigravity** | `agents/hooks.json`, custom agents (`.agents/agents/`), rules, skills | Native hooks (`HARD_ENFORCED`) | Trusted transcript Review V2 | Yes |
| **Claude Code** | `.claude/settings.json`, rules | Installed pre-tool hooks where available | V1 response ingestion; independence not natively verified | Yes |
| **Codex** | Root `AGENTS.md`, `.codex/` instructions | Rule/sandbox dependent | V1 response ingestion; independence not natively verified | Yes |
| **Cursor** | `.cursorrules` / `.cursor/rules` | `RULE_ENFORCED` | V1 response ingestion | Yes |
| **Windsurf** | `.windsurfrules` | `RULE_ENFORCED` | V1 response ingestion | Yes |
| **GitHub Copilot** | `.github/copilot-instructions.md`, installed pre-tool hook adapter | Hook-backed where supported and detected; otherwise rule-enforced | V1 response ingestion | Yes |
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

The Python runtime engine uses the standard library. Git, a compatible JDK/Android SDK, the project Gradle Wrapper, ADB for device workflows, and the selected AI host are separate external requirements. Wheel building and publishing use development dependencies.

---

## Testing / CI

- **Configured runners**: Ubuntu 24.04, Windows Server 2025, and Intel macOS 15.
- **Configured Python coverage**: Full suite on Linux/Python 3.12; quick suite on Linux/Python 3.10, 3.11, 3.13, and 3.14, and on Windows/macOS with Python 3.12. Wheel lifecycle checks run on all three operating systems.
- **Validation**: Full deterministic selftest suite (`python harness_cli.py selftest`), syntax compilation across all scripts (`python -m compileall`), wheel packaging and lifecycle tests, security/adversarial boundary validation, and multi-phase Android workflow scenario tests.

Pushes and pull requests targeting `main` trigger the configured [GitHub Actions jobs](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml). This is a selected compatibility matrix, not every OS/Python combination. A configured job is not evidence of a pass: consult results for the exact commit. Release policy requires successful validation and CI before tagging.

---

## Recorded client validation

Historical client runs and their evidence are documented in [benchmark status](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/benchmark-status.md) and its linked reports. That record includes passed, failed, incomplete, and pending scenarios. Results apply to the frozen versions and environments named in each report; they do not certify every scenario on the current release.

The deterministic selftests exercise simulated Android projects and workflow contracts. They do not replace real-device testing or end-to-end validation on your own application.

## Maturity / roadmap

Antigravity is the primary host. Other hosts use their detected hook or rule enforcement plus downstream verification. Evaluate the current commit's CI results, supported boundaries, and client validation before relying on it for a particular project.

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
3. **Deterministic Selftests**: Run `python harness_cli.py selftest` and `python -m compileall -q harness_cli.py agents/scripts` to verify all tests pass cleanly. Suites run in parallel (`--jobs N`, default up to 4; the largest suites are split into shards; `--jobs 1` streams output). On Windows, pointing `HARNESS_SELFTEST_TMP` at a folder excluded from antivirus scanning shortens the run considerably.

For security reports, refer to [SECURITY.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/SECURITY.md).

---

## FAQ

**1. Does this replace Android Studio?**
No. Android Studio remains the primary IDE for Android development, debugging, and profiling. The harness is an engineering control layer for AI coding tools working within the repository.

**2. Does this make the AI autonomous?**
No. The harness is approval-first. All task scopes and risk classifications require explicit developer approval before modifications begin, and delivery requires verified evidence.

**3. Can it work with mixed Java/Kotlin/XML/Compose codebases?**
Yes. It derives local architectural evidence per module and source set and checks changes against the approved architecture. Ambiguous or unsupported patterns can require developer clarification.

**4. Does every task run many reviewers?**
No. The 6-tier risk model dynamically assigns verification: trivial edits (T0) and low-risk changes (T1) skip reviewer subagents entirely. Specialized reviewers run only when justified by the final classified blast radius.

**5. Does every task require a device?**
No. Device deployment and mobile verification are required only for tiers and changes involving device-facing surfaces (such as T4/T5 with Room, permissions, or system services) or when explicitly requested.

**6. Can I use Codex / Gemini / Claude / Copilot?**
Yes. Native tool adapters and instruction templates are provided for Claude Code, Gemini CLI / Antigravity, GitHub Copilot, Cursor, Windsurf, Roo Code, and others.

**7. Does the harness commit/push code?**
Installed client-project workflows leave Git mutations to the developer and normally leave edits unstaged. Maintenance of this harness repository may use Git or publish only when its maintainer explicitly authorizes those actions.

**8. What happens if the harness itself is corrupted?**
The harness includes deterministic health diagnostics (`doctor`) and self-healing repair (`repair`) that can restore managed engine files from the pinned kit without touching your application source code.

**9. Will a new chat remember my project rules?**
Future sessions can load repo-local context. Project notes (`project-notes.md`) and scoped developer instructions (`developer-instructions.json`) persist inside the repository. When a new chat begins, Task Context and Discovery automatically carry applicable instructions into task planning. The chat provider itself does not need to remember previous conversations. Current source evidence remains the highest authority.

**10. Can I keep several local tasks without worktrees or committing the previous task first?**
Yes. Up to **three live tasks** may share one worktree when their explicitly planned files do not overlap. Pending approvals, implementation, verification, blocked tasks, and READY_FOR_DELIVERY tasks all count. A fourth task is refused until one is delivered or cancelled; switching focus does not free a slot.

Start each task with its own `--task-id` and `--expected-files`. A ready task may remain uncommitted while you work on another disjoint task. Switch focus before editing or running commands that use the active task:

```bash
python .agents/harness.py task switch --task-id task-b
python .agents/harness.py task status --task-id task-b --next --brief
```

Explicit `--task-id` selects the task for commands that accept it. `task switch` preserves the task's status and approval; a pending plan still requires approval, and a verifying task still needs `task resume` before edits. Without an active pointer, several live tasks require explicit selection. Revisions cannot reserve another live task's files.

When tasks conflict, the harness names the affected tasks and files and offers understandable choices: finish the existing task first, agree separate file scopes, explicitly cancel an unwanted task while keeping its edits, or use a developer-created worktree. Even edits to different lines of the same file overlap. The three-task limit instead offers delivery, cancellation, or another worktree. `--json` includes structured options and a `RESOLVE_TASK_CONFLICT` next action so the host can present these choices in your language. No resolution runs automatically.

**Combine plans before starting:** The conflict choices also offer **Combine plans before implementation**, with an eligibility explanation. You can consolidate two or three plans awaiting their first approval into a new task. Preview their combined goals, files, execution phases, tests and newly evaluated review policy:

```bash
python .agents/harness.py task merge --task-id combined --from-task-id task-a --from-task-id task-b --json
```

Repeat `--from-task-id` in the desired execution order, adding a third source if needed. The preview changes no task state or project files. After you explicitly select the merge, the agent applies that exact preview:

```bash
python .agents/harness.py task merge --task-id combined --from-task-id task-a --from-task-id task-b --apply --expect-preview <merge_preview_sha256> --source conversation --proof-reference "<your merge choice>"
```

The source tasks become CANCELLED with their original plans and a `merged_into` reference retained. The new task awaits **one fresh implementation approval**; selecting a merge grants no permission to edit application files. Changed plans or inputs require a fresh preview. No approval, execution evidence, or spending transfers. Started tasks remain separate, even if revised back to pending approval. Conflicting architecture, acceptance or Zoho links require a reviewed consolidated plan rather than silently dropping an obligation. If the conflicting request has no saved task yet, the host offers to include its complete goals in a revision of the existing pending plan. Interrupted application blocks project writes and can be recovered by repeating the recorded apply command. This feature consolidates plans; file changes and Git branches are unaffected.

When a task is ready, commit only its verified files yourself, then run:

```bash
python .agents/harness.py task reconcile-delivery --task-id task-b
```

Only that task becomes DELIVERED. Other tasks keep their local changes and accept the verified sibling commit in their lineage. Unrelated commits, overlapping edits, and changed verified content still block delivery.

**Shared build limitation:** Gradle, unit tests, assembly, and the APK use the entire working tree, including unfinished sibling changes. Keep parked work compilable. Editing any task during another task's frozen verification makes that run stale; rerun verification against the actual tree. Use separate developer-created worktrees when you need overlapping files or independent builds. The existing `task handoff` / `task reconcile-handoff` WIP checkpoint flow remains available.

**11. Does every phase run AI reviewers?**
No. Deterministic checks (Room schema guards, string parity, fast ktlint, and targeted unit tests) remain primary. Routine feature phases (`< 400` changed lines) and the final phase of a multi-phase plan (which is immediately followed by `prepare-verification`) skip redundant AI subagent phase reviews. Scoped phase delta review runs only on intermediate phases when the delta is substantial (`>= 400` changed lines), elevates canonical risk (`T3_SUBSYSTEM` through `T5_CRITICAL`), touches critical surfaces, or explicitly enables `scoped_phase_review_enabled`. Even then, only 1–2 policy-routed specialists review the phase delta. Final integration review across the completed task remains authoritative.

---

## License

MIT License. See [LICENSE](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE).

- [Optional acceptance evidence, reusable journeys, and local metrics](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/verification-value.md)
- [Quickstart Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/quickstart.md)
- [Architecture Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/architecture.md)
- [Workflow Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/workflows.md)
- [Compatibility Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
- [AI Tool Support](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md)
- [Setup Wizard Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/setup-wizard.md)
- [Threat Model](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/threat-model.md)
- [Restore & Recovery](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/restore.md)
