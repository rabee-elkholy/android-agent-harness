<div align="center">

<img src="https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/main/docs/assets/logo.png" alt="Android Agent Harness Logo" width="132" height="132" />

<h1>Android Agent Harness</h1>

<p><b>Approval-first, cryptographically verified engineering governance for AI coding agents on Native Android &amp; Kotlin Multiplatform (KMM / KMP).</b></p>

[![CI](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/rabee-elkholy/android-agent-harness/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/rabee-elkholy/android-agent-harness?label=release&color=22A858)](https://github.com/rabee-elkholy/android-agent-harness/releases)
[![PyPI](https://img.shields.io/pypi/v/android-agent-harness?color=1A73E8)](https://pypi.org/project/android-agent-harness/)
[![Targets](https://img.shields.io/badge/Android%20%7C%20KMM%20%2F%20KMP-Kotlin%20%7C%20Java%20%7C%20Compose%20%7C%20Swift-7F52FF)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
[![Python](https://img.shields.io/badge/Python-3.10%E2%80%933.14%20%7C%20Zero%20Deps-2563EB)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
[![Platforms](https://img.shields.io/badge/Linux%20%7C%20macOS%20%7C%20Windows-supported-10B981)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md)
[![License: MIT](https://img.shields.io/github/license/rabee-elkholy/android-agent-harness)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE)
[![XERJ Corpus Hub contributor](https://hub.xerj.org/contributors/rabee-elkholy/badge.svg)](https://hub.xerj.org/contributors/rabee-elkholy)

<p>
  <a href="#quick-start"><b>Quick Start</b></a> ·
  <a href="#why-android-agent-harness"><b>Why Harness?</b></a> ·
  <a href="#measured-performance--context-efficiency"><b>System Proof &amp; Benchmarks</b></a> ·
  <a href="#what-daily-use-looks-like"><b>Daily Workflow</b></a> ·
  <a href="#antigravity-first-architecture--review-protocol-v2"><b>Antigravity &amp; Review V2</b></a> ·
  <a href="#hybrid-flash-orchestration--frontier-quota-protection"><b>Hybrid Model Routing</b></a> ·
  <a href="#capability-detected-android-ecosystem-bridges--ast-symbol-surgery"><b>Ecosystem Bridges</b></a> ·
  <a href="#faq"><b>FAQ</b></a>
</p>

<a href="https://github.com/rabee-elkholy/android-agent-harness/raw/main/docs/assets/explainer.mp4" title="Click to open full 15-second HD explainer video with audio (MP4)">
  <img src="https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/main/docs/assets/explainer.gif" alt="Android Agent Harness — 15-Second Visual Architecture Walkthrough" width="840" />
</a>
<br />
<sub><b>15-Second Architecture Walkthrough</b> — Click animation to play the <a href="https://github.com/rabee-elkholy/android-agent-harness/raw/main/docs/assets/explainer.mp4">full 720p MP4 with audio</a></sub>

</div>

---

**Android Agent Harness** upgrades general-purpose AI coding assistants — engineered primary-first for **Google Antigravity**, alongside **Claude Code**, **Codex**, **Cursor**, and `AGENTS.md` hosts — into a deterministic, senior-grade Android and KMM/KMP engineering runtime.

Prompt rules alone decay as conversations cross `50k+` tokens: agents start reading entire files blindly, editing out-of-scope modules, skipping Room migrations, swallowing coroutine cancellations, or claiming `"tests pass"` from stale runs. Android Agent Harness moves discovery, scope enforcement, TDD bug reproduction, specialist code review, physical-device QA, and cryptographic delivery proof into a **zero-dependency Python standard-library engine** under `.agents/`.

> **Design Principle — Stricter proof, not heavier workflow:** Approve one concise plan, keep 100% human authority over Git and external ticket mutations, and receive changes backed by `SHA-256` snapshot-bound compile, test, review, and device evidence.

---

## Why Android Agent Harness?

Host JVM unit tests (`./gradlew testDebugUnitTest`) catch logic assertions inside mocked classes, yet **silently pass** on some of the costliest Android and KMP production defects. Below is what happens on real multi-module repositories (`mustafaunlu/Ecommerce-Compose` & `joreilly/PeopleInSpace`) when the exact same `18` seeded tasks run unassisted vs. governed by `v1.3.5`:

```text
WITHOUT HARNESS (Vanilla AI Session)                   WITH ANDROID AGENT HARNESS v1.3.5
────────────────────────────────────────────────────   ───────────────────────────────────────────────────────────────────
1. @Entity column added at @Database(version = 1)   -> BLOCKED in 22ms  [ROOM_SCHEMA_MIGRATION_MISSING] (0 tokens)
2. import android.util.Log inside KMP commonMain    -> BLOCKED in 18ms  [KMP_COMMON_MAIN_PURITY_VIOLATION] (0 tokens)
3. PendingIntent(ctx, 0, intent, 0) on Android 15   -> BLOCKED in 14ms  [PENDING_INTENT_MISSING_IMMUTABILITY] (0 tokens)
4. Compose A2UI 1.0 uncollected outboundEvents      -> BLOCKED in 15ms  [A2UI_UNCOLLECTED_OUTBOUND_EVENTS] (0 tokens)
5. Arabic RTL banner right=432px > 360px viewport   -> BLOCKED in 14ms  [HORIZONTAL_VIEWPORT_CLIP] (.uitree.json gate)
6. Legacy module with 0 unit tests exits 0          -> BLOCKED at gate  [ZERO_TESTS_EXECUTED] (vacuous green rejected)
7. Prompt says "commit and push when done"          -> DENIED at hook   [GIT_MUTATION_HUMAN_AUTHORITY] (PreToolUse)
8. Hilt @Module leaks concrete data source to UI    -> CAUGHT in V2 R1  [HARNESS_REVIEW_RESULT_V2 -> remediated in R2]
9. Idle subagent wakes up 255m later via schedule   -> BLOCKED & REAPED [ZOMBIE_SUBAGENT_SCHEDULE_WAKEUP_GUARD / kill_all]
10. Unattended agy -p script loop risks 403 ban     -> BLOCKED at hook  [AGY_HEADLESS_LOOP_TOS_GUARD] (#199748/#199756)
```

| Failure Mode in Vanilla AI Sessions | Deterministic Guarantee with Android Agent Harness |
|---|---|
| **Stale verification**: Agent reports `"all tests pass"` from a run executed before its final edit. | Every compile, unit test, V2 review, APK, and device check is bound to `delivery_snapshot_sha256`. Any subsequent byte edit invalidates stale proof automatically. |
| **Unreproduced bug fixes**: Agent guesses at a fix without proving the failure existed. | Applicable `BUG` tasks enforce `CAPTURE_RED_EVIDENCE` (`--capture-red`), requiring a recorded failing test (`red-evidence.json`) before production files unlock. |
| **Scope drift & drive-by refactors**: Agent edits `libs.versions.toml` or rewrites legacy Java/XML unasked. | Per-module architecture resolver preserves local patterns (`MVP`, `MVVM`, `MVI`), and native `PreToolUse` hooks reject unapproved file paths in real time. |
| **Self-approved plans & unwanted Git commits**: Agent rubber-stamps its own plan or runs `git commit` / `push`. | Plan unlocks require a developer-issued approval bound to `plan_sha256` + single-use nonce; `commit`, `branch`, `merge`, `rebase`, and `push` remain strictly human-owned. |
| **Frontier quota exhaustion**: Primary model sweeps dozens of files or spawns unbounded explore subagents. | Complexity-adaptive `flash-argon-hybrid` isolates discovery on `gemini-3.8-flash-medium` (`<=24` calls), caps `COMPLEX`/`CRITICAL` reviews at `gemini-4-argon-low`, and blocks post-wave full-file re-reads. |
| **Context amnesia across chats**: Every new chat forgets repo conventions and repeats architectural mistakes. | `.agents/project-context/` persists `project-facts.json`, `project-notes.md`, and scoped `developer-instructions.json` across all `7/7` planning, worker, and review surfaces. |

---

## Quick Start

### Chat installation (recommended)

Open your Android or KMM/KMP repository in **Google Antigravity** (or Claude Code) and paste this single pinned bootstrap prompt:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.3.5/docs/install-or-update-prompt.md and follow all instructions.
```

What happens automatically and non-destructively:
1. **Read-only discovery**: Inspects Gradle modules (`:app`, `:composeApp`, `:shared`, `:core:*`, `:feature:*`), variants, DI frameworks (`Hilt`, `Koin`), Room/SQLDelight schemas, UI toolkits, and locales without touching a single app file.
2. **Interactive preview & sign-off**: Summarizes detected architecture, previews the exact setup plan, and waits for your explicit approval.
3. **Zero-noise isolation**: Stores the immutable release kit outside your repo (`~/.android-harness/kit`), installs only the `.agents/` runtime, configures `.git/info/exclude` when gitignored mode is selected, and runs `doctor --install-check` (`40/40` checks).

### Terminal installation (alternative)

Install globally via `pipx`:

```bash
# 1. Install the standalone CLI (Python 3.10–3.14, zero third-party dependencies)
pipx install android-agent-harness

# 2. Initialize inside your Android or KMP repository
android-harness init --repo /path/to/android-project

# 3. Verify all health & runtime dimensions
android-harness doctor --repo /path/to/android-project --json
```

Or initialize directly from a pinned shallow tag clone with **zero global packages**:

```bash
git clone --depth 1 --branch v1.3.5 --single-branch \
  https://github.com/rabee-elkholy/android-agent-harness.git ~/.android-harness/kit

python ~/.android-harness/kit/harness_cli.py init \
  --repo /path/to/android-project \
  --kit ~/.android-harness/kit
```

Inside any initialized repository, daily commands run through the fast in-process launcher (`~18 ms`):

```bash
python .agents/harness.py doctor --json
```

### Transactional Zero-Clobber Updates

```bash
# Upgrade from the pinned external kit checkout:
python ~/.android-harness/kit/harness_cli.py update --repo /path/to/android-project

# Or upgrade directly from a local maintainer checkout:
python /path/to/android-agent-harness/harness_cli.py update \
  --repo /path/to/android-project \
  --kit /path/to/android-agent-harness \
  --no-refresh
```

Updates synchronize `.agents/` in place without breaking open IDE file watchers, preserve `project-notes.md`, `developer-instructions.json`, wizard answers, and task history, refuse mid-flight task clobbering by default, and roll back atomically if interrupted. See [Install & Update Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/install-or-update-prompt.md).

---

## Measured Performance & Context Efficiency

Every runtime subsystem is implemented in pure Python `3.10–3.14` standard library with content-addressed `blake2b` caching and in-process dispatch. No synthetic benchmarks: all end-to-end numbers below were measured against **`mustafaunlu/Ecommerce-Compose`** (`178` files) and **`joreilly/PeopleInSpace`** (`9`-module KMP + `SwiftUI`, `204` files):

| Engineering Dimension | Baseline (`Without Harness` / `v1.3.4`) | Governed by Harness `v1.3.5` | Visual Comparison & Measured Delta |
|---|---|---|---|
| **Silent Defect Interception** (`18` Seeded Tasks) | `0 / 18` caught (`18/18` escaped) | **`18 / 18` caught & delivered (`0` escaped)** | `██████████` **`100%` caught** (`14` at `0` tokens + `4` via V2 review) |
| **Lead-Chat Discovery Tokens** (`18` Tasks) | `112,097` tokens in Frontier chat | **`~8,640` tokens in Frontier chat** | `█░░░░░░░░░` **`-92.3%` Lead context** (`90,348` isolated in Flash `Scout`) |
| **`plan.md` Artifact Size** (`204`–`1,000+` file repos) | `38,790 B` / `1.84 MB` (`v1.3.4`) | **`5,396 B` / `~5.6 KB`** | `█░░░░░░░░░` **`-86.09%` to `-99.70%` bytes** (`0` hash loss) |
| **Read-Only CLI Dispatch** (`harness.py` in-process) | `145.10 ms` subprocess startup | **`18.10 ms` in-process router** | `█░░░░░░░░░` **`8.02x` faster** (`8.57 ms` warm `resolve_next_action`) |
| **KMP Test-Target Isolation** (`9`-Module `PeopleInSpace`) | `9 / 9` modules executed (`allprojects`) | **`1 / 9` module (`:common:testAndroidHostTest`)** | `█░░░░░░░░░` **`-88.9%` skipped downstream modules** on test-only edits |
| **Context Delta Compaction** (`task-context --since`) | `22,774 B` full `SUMMARY` | **`11,439 B` `UNCHANGED` delta** | `█████░░░░░` **`-49.77%` bytes** (`14.75 ms` warm `mixed`, `14.98 ms` `kmp`) |
| **Non-Code Note Stripping** (`FILE_FALLBACK` / Reviews) | `40,394 B` / `15,408 B` | **`4,694 B` / `341 B`** | `█░░░░░░░░░` **`-88.38%` / `-97.79%`** PM template bloat removed |
| **End-to-End Certification** (`Install` + `T1..T10` + `DW-01..24`) | Unverified ad-hoc session edits | **`35 / 35` E2E scenarios `PASSED`** | `██████████` **`100%` pass rate** + `36/36` selftest suites (`59` procs) |

Reproducible benchmark suites, per-task token ledgers, and raw JSON measurements:
- [Controlled 18-Task A/B Comparison (`Without Harness` vs `With Harness v1.3.5`)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/ab-comparison-v1.3.5.md)
- [Consolidated 18-Task Execution Ledger & Quota Economics (`results-v1.3.5.md`)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/results-v1.3.5.md)
- [v1.3.5 Engine, Project-Context & Subagent Benchmarks](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/v1.3.5-engine-and-context-benchmarks.md)
- [End-to-End Certification (`Install + T1..T10`) & `24` Daily Workflow Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/benchmark-status.md)
- [Context Summary Compaction Measurements (JSON)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/implementation/context-summary-measurements.json)

---

## At a Glance: 10 Core Engineering Subsystems

| Subsystem | Engineering Problem Solved | Deterministic Enforcement Mechanism |
|---|---|---|
| **1. Incremental AST & Symbol Graph** | Blind grep loops and token-heavy full-file reads across multi-module repos | Indexes `Kotlin`, `Java`, `XML`, and `Swift` symbols with `blake2b` caching, resolving exact line spans, callers, reuse candidates, and companion `*Test.kt` files in `~15 ms`. |
| **2. Single-Approval Scope Lock** | Unapproved refactors, silent config edits, and constant prompt nagging | One plan approval (`plan_sha256` + single-use nonce) unlocks execution; native `PreToolUse` hooks (`hooks.json`) block unapproved paths immediately. |
| **3. Complexity-Adaptive Hybrid Routing** | Burning weekly Frontier quota on routine single-module edits and file scans | `flash-argon-hybrid` runs `SIMPLE` slices `100%` on `gemini-3.8-flash-medium`, routes `COMPLEX` worker/deep reviews to `gemini-4-argon-low`, and enforces a hard ceiling at `Argon Low`. |
| **4. 6-Tier Risk & Epistemic Review V2** | Over-reviewing docs or under-reviewing `Auth` / `Billing` / `Room` diffs | Classifies actual diffs from `T0_TRIVIAL` (`0` reviewers) to `T5_CRITICAL`, dispatching isolated specialists that emit cryptographically bound `HARNESS_REVIEW_RESULT_V2` JSON. |
| **5. Android, KMP & `A2UI 1.0` Gates** | Room crashes, missing `values-ar` keys, `commonMain` leaks, and `A2UI` white-boxes | Zero-token preflight checks for split-file Room migrations, locale string/plural parity, `UI -> DAO` bypasses, Android 15/16 `PendingIntent` flags, `A2UI 1.0` traps, and `commonMain` purity. |
| **6. Persistent Repo Memory** | Repeating module rules and conventions across every new chat session | `.agents/project-context/` merges `project-facts.json`, `project-notes.md`, and scoped `developer-instructions.json` across all `7/7` discovery, planning, worker, and review surfaces. |
| **7. AST Symbol Surgery & UI Bridges** | Corrupting 600-line classes, RTL viewport clipping, and noisy legacy lint | Declaration-level AST editor (`symbol replace-body`), **Maestro YAML** runner/exporter, **Roborazzi** headless `.uitree.json` bounds gate, and diff-scoped **SARIF / BuildHealth / LeakCanary** gates. |
| **8. Snapshot-Bound EvidenceStore** | Claiming `"tests pass"` from stale runs prior to a last-minute tweak | Binds `preflight`, `compile`, `unit_tests`, V2 verdicts, APKs, and `device install-start` to `delivery_snapshot_sha256` and `change_set_sha256`. |
| **9. Multi-Task & Context Bridging** | Context degradation in `100k+`-token chats and mid-task hotfix collisions | Supports up to `3` concurrent disjoint tasks (`task switch`), WIP freeze (`task handoff`), and 1-command cross-chat/cross-host continuation (`task bridge` / `task continue`). |
| **10. Universal PM MCP & Self-Healing** | Accidental ticket closures, overwritten Bug specs, or interrupted runs | Zero-config governance for Zoho, Jira, Linear, GitHub, ClickUp, Asana, Monday, and Trello (`pm authorize`), plus `task heal` state recovery and Zero-PII forensics. |

---

## What daily use looks like

```text
  Developer Prompt ("Fix blank weightGoal bug on STEPS users in CaloriesViewModel")
         │
         ▼
  [1. AST Discovery] ──► graph / task-context (~15 ms) or parallel Flash Scout wave (<1.5k-token digest)
         │
         ▼
  [2. Single Plan]   ──► Concise plan.md + 1 interactive approval card (plan_sha256 + single-use nonce)
         │
         ▼
  [3. Scoped Build]  ──► PreToolUse scope lock ─► BUG --capture-red ─► surgical edit ─► --tests <Class>
         │
         ▼
  [4. Risk Gates]    ──► 0-token preflight (Room / Strings / KMP / A2UI / Lint) + parallel V2 Specialists
         │
         ▼
  [5. Sign-Off]      ──► Snapshot-bound EvidenceStore + optional Phone/Maestro QA ─► Human Git Commit
```

You write natural engineering requests; the deterministic state router (`python .agents/harness.py task status --task-id <id> --next`) drives every phase behind the scenes:

1. **Anchored Discovery**: Resolves exact callers, tests, and repo-local constraints via `graph` and `task-context` (or parallel Flash `harness-scout-agent` waves on multi-subsystem tasks).
2. **One Concise Plan**: Generates a compact `plan.md` (`~5.4 KB` even on 9-module KMP repos) with impacted existing tests surfaced upfront.
3. **Explicit Developer Approval**: Waits once for your sign-off (`Approve` / `Request changes` / `Cancel task`) — zero mid-task nagging.
4. **Scoped Execution**: Reproduces bugs first (`--capture-red`), iterates rapidly with single-class `--tests <Pattern>` on cached Gradle builds, and blocks unapproved file edits via `PreToolUse`.
5. **Risk-Adaptive Gates**: Executes zero-token static/domain gates, module-scoped unit tests (rejecting vacuous `0`-test runs), and epistemically isolated V2 specialist reviews matched to the final diff.
6. **Device & Walkthrough Sign-off**: Runs `device install-start`, replayable `journey` contracts, or `maestro run` when UI/device surfaces warrant hardware proof.
7. **Human Git Delivery**: Leaves verified changes cleanly in your working tree under **Human Git Authority** and closes out once you commit.

### Multi-Phase Tasks, Disjoint Worktrees & Smart Context Bridging

- **Single-Approval Multi-Phase Execution (`p1 -> p2 -> ...`)**: Large cross-module features run phase checkpoints (`preflight`, Room guards, string parity, fast lint, targeted unit tests) without redundant mid-phase approvals, preserving completed phase proof even across mid-task `workflow.py revise` updates.
- **Up to 3 Concurrent Disjoint Tasks**: Keep three independent tasks live in one worktree (`task switch --task-id <id>`), consolidate drafts safely (`task merge`), or freeze urgent hotfix interruptions (`task handoff` -> developer WIP commit -> `task reconcile-handoff`).
- **One-Command Chat & Host Rotation (`task bridge`)**: Transfer active contracts, `interface_delta` signatures, and a fresh Discovery Receipt to a clean chat — or switch AI hosts mid-task (`task continue --host claude --source-stopped`):

```bash
# Save follow-up or mid-task state in the current chat:
python .agents/harness.py task bridge --save \
  --next-outcome "Wire CaloriesSettingsScreen state into HomeMviScreen" \
  --summary "Completed CaloriesViewModel maintenance equation; preserve UiState contract"

# Restore immediately in a fresh chat with zero re-discovery overhead:
python .agents/harness.py task bridge
```

---

## Antigravity-First Architecture & Review Protocol V2

Android Agent Harness is built primary-first for **Google Antigravity** with `HARD_ENFORCED` native hooks (`.agents/hooks.json`), 8 role-accurate subagent definitions under `.agents/agents/<role>/agent.md`, real `SYSTEM` / `SYSTEM_SDK` / `transcript_full.jsonl` verification, and proactive runtime diagnostics:

- **Cryptographically Bound `HARNESS_REVIEW_RESULT_V2`**: Specialist reviewers emit structured JSON tied to `delivery_snapshot_sha256`, `change_set_sha256`, and `package_sha256` — eliminating prose hallucinations and stale sign-offs.
- **Epistemically Isolated Specialist Roster (`.agents/agents/`)**:
  - `bug-test-reviewer-agent` — Behavioral correctness, boundary conditions, nullability, structured concurrency/cancellation, lifecycle state, and unit-test assertion rigor.
  - `arch-regression-reviewer-agent` — Cross-module blast radius, navigation/deep-link callers, Clean Architecture boundaries, KMP source-set purity, and localization parity.
  - `security-perf-reviewer-agent` — Auth/Billing/Crypto invariants, exported Manifest components, `PendingIntent` mutability, main-thread I/O & ANR hazards, and Compose recomposition stability.
  - `spec-compliance-agent` — Line-by-line requirement verification against approved acceptance criteria when routed.
- **`Zero-Hop` Inlined Briefs & Single-Turn Batch Ingestion**: Review packages (`<= 24 KB`), `GraphEngine` blast-radius topologies, and passed deterministic gate proofs are inlined directly inside `brief-<role>.md`. `python .agents/harness.py review complete-all --task <id>` verifies and records all parallel verdicts in one call, guarded by a **Reviewer Call Safety Cap** (default: `20`, per-reviewer budget: `12` tool calls).
- **Antigravity Platform, Quota & Account-Safety Guards (`v1.3.5`)**:
  - **Zombie Subagent & `255m` Reactive-Wakeup Guard (`#199713`)**: Strips `schedule` permissions from all `.agents/agents/*/agent.md` manifests, blocks `schedule` / `schedules:*` wakeup triggers (`ZOMBIE_SUBAGENT_SCHEDULE_WAKEUP_GUARD`), explicitly permits `manage_subagents({"Action": "kill_all"})` across all task states to reap idle subagents immediately after waves/tasks finish, and flags `>= 2h` reactive-wakeup spikes in `doctor` and `diagnose-session`.
  - **Unattended `agy -p` & UI-Injection ToS Anti-Ban Guard (`#199748` / `#199756`)**: Blocks unattended `agy -p` / `--headless` loops and programmatic UI keystroke injection (`AGY_HEADLESS_LOOP_TOS_GUARD`) to protect Google AI Ultra accounts from automated `403 PERMISSION_DENIED` suspension while preserving interactive Skill workflows.
  - **Managed Agent `limit: 0` Zero-Quota & Regional Flash `503` Diagnostics (`#199769` / `#199770` & `#198333`)**: Classifies Free/Pro tier `HTTP 429` (`limit: 0`) errors on `gemini-4-argon` / `gemini-4-carbon` (`MANAGED_AGENT_ZERO_QUOTA_429`) with 1-command Pure Flash fallback guidance, and pinpoints silent regional `gemini-3.8-flash` `HTTP 503` backoff stalls (`FLASH_503_CAPACITY_BACKOFF`) in `diagnose-session`.
  - **Remote Mode Quota-Leak & IDE Stability Guards (`#198819`, `#198689`, `#199301`)**: Blocks silent `Model="flash"` -> `Argon` billing in Remote Mode (`REMOTE_MODE_FLASH_QUOTA_LEAK_GUARD`), detects `language_server.log` `WatchVersionControlState` spin-loops / `>= 500 MB` bloat, and flags multi-server Windows `stdio` MCP pipe collisions.

---

## Hybrid Flash Orchestration & Frontier Quota Protection

Version `1.3.5` introduces the **Complexity-Adaptive `Flash + Argon Low` Hybrid Engine (`flash-argon-hybrid`)** as the recommended project-wide routing policy (`flash-argon-project`), protecting weekly Frontier model quotas with a **strict hard ceiling at `gemini-4-argon-low`** (never auto-escalating subagents to `argon-medium` or `argon-high`):

| Complexity Band | Automatic Task / Diff Trigger | Routed Subagent Models | Quota & Reasoning Profile |
|---|---|---|---|
| **Band 0: `TRIVIAL`** | `T0` docs, comments, non-runtime prose | **`0` subagents** (inline Lead edit + preflight) | Instant completion; zero subagent overhead |
| **Band 1: `SIMPLE`** | Single-module `T1–T2`, `<= 3` non-test files, `<= 90` changed lines | **`100%` `gemini-3.8-flash-medium`** across `Scout`, `Worker`, and routed reviewers | **`0` `Gemini 4` subagent calls** on routine UI/resource/helper work |
| **Band 2: `COMPLEX`** | `BUG`, `>= 2` modules/phases, `>= 4` files or `> 90` lines, `T3/T4`, `COROUTINES`/`NETWORK`/`ROOM_SCHEMA`/`PUBLIC_API`, or `Round 2` | **`gemini-4-argon-low`** (`Worker` `FULL_SLICE`, `bug-test`, `security-perf`, `DEEP` roles) + **`gemini-3.8-flash-medium`** (`Scout` + `NORMAL` `arch-regression`) | Concentrates `Argon Low` strictly on deep logic, concurrency, and security-perf |
| **Band 3: `CRITICAL`** | `T5` (`AUTH`, `BILLING`, `CRYPTO`, `SECURITY`, `SENSITIVE_DATA`) or `Round 3+` | **Lead Architect** writes production code (`Worker` runs `TESTS_AND_GATES_ONLY` on `Flash Medium`); all reviewers cap at **`gemini-4-argon-low`** | Maximum human-visible Lead authority + `Argon Low` multi-specialist audit |

Additional enforced subagent guardrails across all waves:
- **Hard Step Budgets**: `harness-scout-agent` capped at **`24` calls/instance** (blocking built-in unpinned `research`/`explore` via `USE_HARNESS_SCOUT_AGENT`); `harness-worker-agent` capped at **`32` read/search calls** while leaving edits and Gradle `compile`/`test` uncapped.
- **Post-Wave Anti-Reread Guard**: Native hooks block bloated `> 220`-line Lead re-reads on `> 350`-line files already digested by subagents and cap post-wave surgical Lead reads at **`<= 3`**. See [Reviewer Model Configuration](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/reviewer-models.md).

---

## Adaptive 6-Tier Risk Model & Android / KMP Protection

| Tier | Classification | Representative Surfaces | Enforced Verification Profile |
|---|---|---|---|
| **T0** | `TRIVIAL` | Markdown docs, code comments, non-runtime text | Fast structural / preflight check — zero AI reviewers, instant delivery |
| **T1** | `LOW_RISK` | `strings.xml`, colors, dimens, static XML resources | Bilingual/multi-locale string & plural parity + bounded compile verification |
| **T2** | `FEATURE` | `ViewModel`, `UseCase`, `Flow`/`suspend`, Compose/XML UI, `DataStore` | Module unit tests + targeted V2 specialist review + APK assemble |
| **T3** | `SUBSYSTEM` | Multi-module contracts, Hilt/Koin DI graphs, Retrofit/Ktor networking | Cross-module architecture boundary review + transitive consumer compile/test gates |
| **T4** | `DATA_DEVICE` | Room / SQLDelight schemas & migrations, `ForegroundService`, Camera, Sensors | Split-file Room migration verifier + specialist V2 review + physical-device / Maestro proof |
| **T5** | `CRITICAL` | `Auth`, `Billing`, `Crypto`, `Keystore`, permissions, sensitive user data | Full specialist V2 roster + Lead-authored implementation + explicit sensitive sign-off |

### Native Android, Jetpack Compose `A2UI 1.0` & Kotlin Multiplatform (`KMM / KMP`) Guards
- **KMP Source-Set & Xcode Purity**: Indexes `commonMain`, `androidMain`, `iosMain`, `:composeApp`, `:shared`, and `.swift`; blocks `android.*` / JVM leaks in `commonMain`; verifies `expect` / `actual` pairing; skips Apple-only KMP targets cleanly on Linux/Windows hosts; and filters non-Gradle Xcode `SwiftUI` folders from Gradle task resolution.
- **Jetpack Compose `A2UI 1.0` & Android 15/16 Static Gate (`fast_kt_lint.py`)**: Catches uncollected `A2UI` `outboundEvents` (silent white-box bug), `material3-a2ui` vs stable Compose BOM conflicts, `catalogId` mismatches, missing `PendingIntent` immutability flags, swallowed `CancellationException`s, `Fragment` `_binding` leaks, and `UI -> DAO` bypasses in `< 35 ms` at `0` tokens.
- **Mixed Legacy & Modern Coexistence**: Resolves architecture rules per module (`Java + XML + MVP` beside `Kotlin + Compose + MVI`) without forcing unapproved migrations.

---

## Persistent Project Knowledge (`.agents/project-context/`)

```text
1. Live Source Code & AST Graph   (Highest authority — current working tree & build topology)
             ↓
2. Generated Project Facts        (.agents/project-context/project-facts.json + architecture/ui/persistence/conventions.md)
             ↓
3. Team Notes & Scoped Rules      (project-notes.md + cryptographically bound developer-instructions.json across 7/7 surfaces)
             ↓
4. Baseline Android Guidance      (Lowest authority — never overrides repository evidence)
```

```bash
# Persist an idempotent domain rule in .agents/project-context/project-notes.md:
python .agents/harness.py context note \
  --section "Domain Conventions & Context" \
  "Never subtract 500 kcal when weightGoal is empty on STEPS users; default to maintenance calories."

# Bind a scoped architectural requirement in developer-instructions.json:
python .agents/harness.py context instruct \
  "Preserve the callback bridge in payments; do not migrate to Flow unless explicitly requested." \
  --scope "MODULE::payments" \
  --strength REQUIREMENT \
  --source conversation \
  --proof-reference "Keep payments callback bridge"

# Audit notes, instructions, and facts against live paths/modules for stale drift:
python .agents/harness.py context drift-report --json
```

---

## Capability-Detected Android Ecosystem Bridges & AST Symbol Surgery

Unconfigured tools add **`0 ms`** runtime overhead; detected project capabilities activate snapshot-bound verification automatically:

- **Pure-Stdlib AST Symbol Surgery (`Kotlin`, `Java`, `Swift`)**: Outline, read, and replace individual declarations inside `800`-line files (`python .agents/harness.py symbol <outline|read|replace-body|insert-after>`) with `--expected-sha256` optimistic locking and whole-file brace-balance verification.
- **Maestro Physical-Device Runner & Exporter (`maestro`)**: Executes `.maestro/*.yaml` against the bound physical device, blocks destructive `clearState` / `uninstallApp` commands unless `--allow-clear-state` is granted, and exports interactive `phone_e2e` runs into `.maestro/<task_id>.yaml` regression suites.
- **Roborazzi Headless `.uitree.json` Viewport & RTL Gate (`roborazzi`)**: Audits Compose `.uitree.json` trees on the JVM for `HORIZONTAL_VIEWPORT_CLIP` (catching Arabic RTL overflow), `ZERO_DIMENSION_NODE`, and `CLICKABLE_SIBLING_COLLISION`.
- **Diff-Scoped Static Health & Zero-PII Forensics (`health` & `diagnose-session`)**: Scopes Detekt / Android Lint `*.sarif` and Gradle `build-health-report.json` strictly to task-touched files, checks `LeakCanary` debug heap dumps, and exports Zero-PII session forensic bundles.
- **Universal Zero-Config PM MCP & Self-Healing (`pm` & `task heal`)**: Governs Zoho Sprints/Projects, Jira, Linear, GitHub, ClickUp, Asana, Monday, and Trello with `pm authorize` previews, protected Bug descriptions, RTL/LTR QA handoff reports (`pm prepare-report`), and 1-command state recovery (`task heal --prepare-fresh-run`).

---

## Supported Hosts & Enforcement Model

| AI Coding Host | Installed Adapters & Assets | Scope & Mutation Enforcement | Review Protocol | Final Snapshot Verifier |
|---|---|---|---|---|
| **Google Antigravity** *(Primary Target)* | `GEMINI.md`, `AGENTS.md`, `.agents/hooks.json`, `.agents/agents/*/agent.md` (`8` pre-installed subagents: `4` V2 reviewers, `2` specialists, `Scout` & `Worker`), rules, skills | **`HARD_ENFORCED`** (`PreToolUse` & `PostToolUse` native hooks) | Trusted transcript `HARNESS_REVIEW_RESULT_V2` | **Yes** (`SHA-256` bound) |
| **Claude Code** | `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json` hooks, `.claude/agents/` subagents | Hook + Rule enforced | Native subagent transcript verification | **Yes** (`SHA-256` bound) |
| **Cursor / Codex / Windsurf / Copilot / `AGENTS.md` Hosts** | `AGENTS.md` + host rule adapters (`.cursor/rules`, `CODEX.md`, `.windsurf/rules`, `.github/copilot-instructions.md`) | **`RULE_ENFORCED`** + downstream CLI gates | Structured response ingestion | **Yes** (`SHA-256` bound) |

See [AI Tool Support Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md) and [Cross-Host Continuation](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/host-continuation.md).

---

## Essential CLI Reference

| Goal | Command |
|---|---|
| **Check installation & runtime health** | `python .agents/harness.py doctor [--install-check] [--json]` |
| **Explore module/feature symbol graph** | `python .agents/harness.py graph --feature <name> --json` |
| **Resolve target file/symbol AST context** | `python .agents/harness.py task-context --file <path> [--since <digest>] --json` |
| **Inspect Hybrid model delegation plan** | `python .agents/harness.py delegate-plan [--task-id <id>] --json` |
| **Check active task deterministic next step** | `python .agents/harness.py task status --task-id <id> --next` |
| **Fast single-class TDD test iteration** | `python .agents/harness.py test [--capture-red] [--tests <ClassOrMethod>]` |
| **Surgical AST symbol outline / replacement** | `python .agents/harness.py symbol <outline\|read\|replace-body\|insert-after> ...` |
| **Manage persistent repo notes & rules** | `python .agents/harness.py context <note\|instruct\|drift-report> ...` |
| **Bridge context to a clean chat** | `python .agents/harness.py task bridge [--save \| --bridge-id <id> \| --snooze]` |
| **Ingest parallel V2 reviews in 1 turn** | `python .agents/harness.py review complete-all --task <id>` |
| **Run physical-device / Maestro / UI gates** | `python .agents/harness.py <device install-start \| maestro run \| roborazzi verify>` |
| **Self-heal task state / session forensics** | `python .agents/harness.py <task heal --task-id <id> \| diagnose-session --json>` |

---

## Clear Boundaries: What It Is & What It Isn't

| Best Fit For | Not Intended To Be |
|---|---|
| Production Android & KMM/KMP teams shipping daily with AI agents | A replacement for Android Studio, Gradle, or physical-device QA |
| Multi-module, mixed legacy/modern codebases (`Java` + `Kotlin`, `XML` + `Compose`, `Swift`) | An autonomous `"no-human-in-the-loop"` auto-committer (`GIT_POLICY = never`) |
| Apps with `Room`, `Auth`, `Billing`, permissions, `ForegroundService`, or RTL localization | An OS kernel sandbox (hooks enforce boundaries at the AI host tool layer) |
| Engineers who want high-speed AI execution **without** surrendering architectural rigor | Necessary for 50-line throwaway prototypes or one-off snippets |

---

## Repository Architecture & CI Validation

```text
agents/
├── harness.py             # Fast ~18 ms in-process CLI router & command dispatcher
├── rules/                 # Canonical English behavioral kernel (<= 36k combined budget)
├── scripts/               # Pure Python 3.10–3.14 stdlib governance, AST graph, gates & doctor
├── skills/                # On-demand domain skills (efficient-context, phone-e2e, UI diagnostics)
├── subagents/             # Epistemically isolated V2 reviewer, specialist, Scout & Worker templates
├── tool-adapters/         # Managed templates for Antigravity, Claude Code, Cursor, Codex & more
└── workflows/             # Multi-phase, phone-e2e, Android inspection & PM tracker playbooks
```

- **Cross-Platform CI Matrix**: Validated across **Ubuntu 24.04**, **Windows Server 2025**, and **macOS 15** on **Python 3.10–3.14**, running `36` deterministic selftest suites (`59` parallel processes via `python harness_cli.py selftest`), wheel packaging lifecycle smoke checks, `265`-file `SHA-256` release checksum verification, and adversarial hook/security tests.
- **Contributing**: Runtime code uses **Python standard library only** (`0` third-party runtime dependencies) and preserves all approval, nonce, and snapshot-binding invariants. See [CONTRIBUTING.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/CONTRIBUTING.md) and [SECURITY.md](https://github.com/rabee-elkholy/android-agent-harness/blob/main/SECURITY.md).

---

## FAQ

<details>
<summary><b>1. Does this make the AI agent fully autonomous or allow it to run git commit / push?</b></summary>
<br />
No. Android Agent Harness is strictly <b>approval-first</b> and enforces <b>Human Git Authority</b>. The agent must obtain explicit developer approval on the plan before mutating source files, and client installations leave <code>git commit</code>, <code>branch</code>, <code>merge</code>, <code>rebase</code>, and <code>push</code> exclusively to the developer.
</details>

<details>
<summary><b>2. Does every task spawn multiple AI reviewers or require a connected phone?</b></summary>
<br />
No. The 6-tier risk engine routes verification from the classified final diff: <code>T0</code> docs and <code>T1</code> resource tweaks skip AI reviewer subagents completely, isolated <code>&lt;=25</code>-line private Kotlin edits consolidate to a single logic/test reviewer, and physical-device verification runs only when device/UI/Room surfaces warrant it (or when requested).
</details>

<details>
<summary><b>3. Does it work with KMM / KMP (Kotlin Multiplatform) and mixed legacy Java + XML projects?</b></summary>
<br />
Yes. It indexes <code>Kotlin</code>, <code>Java</code>, <code>XML</code>, and iOS <code>Swift</code> across <code>commonMain</code>, <code>androidMain</code>, <code>iosMain</code>, <code>:shared</code>, and <code>:composeApp</code>, enforces <code>commonMain</code> platform purity and <code>expect</code>/<code>actual</code> pairing, skips Apple-only KMP targets cleanly on Linux/Windows hosts, and preserves local module architectures (<code>MVP</code>, <code>MVVM</code>, <code>MVI</code>) without forcing migrations.
</details>

<details>
<summary><b>4. How does Complexity-Adaptive Hybrid routing (flash-argon-hybrid) protect weekly Frontier quotas?</b></summary>
<br />
Routine single-module <code>T1–T2</code> tasks (<code>&lt;=3</code> files, <code>&lt;=90</code> lines) execute <b>100% on <code>gemini-3.8-flash-medium</code></b> (zero <code>Gemini 4</code> subagent calls). Complex multi-module, <code>BUG</code>, coroutine, or Room tasks selectively upgrade <code>Worker</code> and deep logic/security reviewers to <b><code>gemini-4-argon-low</code></b> while keeping <code>Scout</code> and structural boundary checks on <code>Flash Medium</code>, with a strict hard ceiling at <code>gemini-4-argon-low</code> (never burning <code>Argon Medium</code> or <code>High</code>).
</details>

<details>
<summary><b>5. Can I keep multiple tasks open in the same worktree without committing first?</b></summary>
<br />
Yes — up to <b>three live tasks</b> may share a single worktree simultaneously as long as their planned file sets are disjoint. Switch active tasks with <code>python .agents/harness.py task switch --task-id &lt;id&gt;</code>, combine pre-approval drafts with <code>task merge</code>, and finalize individual developer commits via <code>task reconcile-delivery --task-id &lt;id&gt;</code>.
</details>

<details>
<summary><b>6. What happens if managed files under .agents/ are accidentally edited or corrupted?</b></summary>
<br />
Run <code>python .agents/harness.py doctor</code> to diagnose any drift, and <code>python ~/.android-harness/kit/harness_cli.py repair --repo /path/to/app</code> to restore checksum-verified engine files and role-accurate subagent definitions without touching your application source code or project notes.
</details>

---

## Documentation Hub

- [Quickstart Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/quickstart.md) · [Install or Update Prompt](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/install-or-update-prompt.md) · [Setup Wizard Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/setup-wizard.md)
- [Architecture Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/architecture.md) · [Workflow Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/workflows.md) · [Efficient Task Context](https://github.com/rabee-elkholy/android-agent-harness/blob/main/agents/workflows/efficient-context.md)
- [Reviewer Model Configuration](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/reviewer-models.md) · [Verification Value & Metrics](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/verification-value.md) · [PM MCP Integrations](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/workflows/pm-integrations.md)
- [Compatibility Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md) · [AI Tool Support](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md) · [Cross-Host Continuation](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/host-continuation.md)
- [Threat Model](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/threat-model.md) · [Restore & Recovery](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/restore.md) · [v1.3.5 Benchmarks & A/B Suite](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/ab-comparison-v1.3.5.md)

---

## License

MIT License. See [LICENSE](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE).
