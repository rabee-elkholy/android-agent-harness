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
  <a href="#domain-skills-workflows--slash-command-packs"><b>Skills &amp; Command Packs</b></a> ·
  <a href="#capability-detected-android-ecosystem-bridges--ast-symbol-surgery"><b>Ecosystem Bridges</b></a> ·
  <a href="#faq"><b>FAQ</b></a>
</p>

</div>

<!-- DRAG_AND_DROP_MP4_VIDEO_ON_THIS_STANDALONE_LINE_IN_GITHUB_WEB_EDITOR -->

---

**Android Agent Harness** upgrades general-purpose AI coding assistants — engineered primary-first for **Google Antigravity**, alongside **Claude Code**, **Codex**, **Cursor**, **GitHub Copilot**, **Windsurf**, and `15` supported AI hosts — into a deterministic, senior-grade Android and KMM/KMP engineering runtime.

Prompt rules alone decay as conversations cross `50k+` tokens: agents start reading entire files blindly, editing out-of-scope modules, skipping Room migrations, swallowing coroutine cancellations, leaving debug logs behind, or claiming `"tests pass"` from stale runs. Android Agent Harness moves architectural discovery, scope enforcement, TDD bug reproduction, specialist code review, physical-device QA, and cryptographic delivery proof into a **zero-dependency Python standard-library engine** under `.agents/`.

> **Design Principle — Stricter proof, not heavier workflow:** Approve one concise plan, keep 100% human authority over Git and external ticket mutations, and receive changes backed by `SHA-256` snapshot-bound compile, test, review, and device evidence.

---

## Why Android Agent Harness?

Host JVM unit tests (`./gradlew testDebugUnitTest`) catch logic assertions inside mocked classes, yet **silently pass** on many of the costliest Android and KMP production defects. Below is what happens on real multi-module repositories (`mustafaunlu/Ecommerce-Compose` & `joreilly/PeopleInSpace`) when the exact same seeded tasks run unassisted vs. governed by `v1.3.5`:

```text
WITHOUT HARNESS (Vanilla AI Session)                   WITH ANDROID AGENT HARNESS v1.3.5
────────────────────────────────────────────────────   ───────────────────────────────────────────────────────────────────
1. @Entity column added at @Database(version = 1)   -> BLOCKED in 22ms  [ROOM_SCHEMA_MIGRATION_MISSING] (0 tokens)
2. import android.util.Log inside KMP commonMain    -> BLOCKED in 18ms  [KMP_COMMON_MAIN_PURITY_VIOLATION] (0 tokens)
3. PendingIntent(ctx, 0, intent, 0) on Android 15   -> BLOCKED in 14ms  [PENDING_INTENT_MISSING_IMMUTABILITY] (0 tokens)
4. Compose A2UI 1.0 uncollected outboundEvents      -> BLOCKED in 15ms  [A2UI_UNCOLLECTED_OUTBOUND_EVENTS] (0 tokens)
5. Arabic RTL banner right=432px > 360px viewport   -> BLOCKED in 14ms  [HORIZONTAL_VIEWPORT_CLIP] (.uitree.json gate)
6. Legacy module with 0 unit tests exits 0          -> BLOCKED at gate  [ZERO_TESTS_EXECUTED] (vacuous green rejected)
7. Temporary debug Log.d / println left in code     -> BLOCKED at gate  [ACTIVE_DEBUG_PROBES_REMAIN] (debug strip)
8. Prompt says "commit and push when done"          -> DENIED at hook   [GIT_MUTATION_HUMAN_AUTHORITY] (PreToolUse)
9. Hilt @Module leaks concrete data source to UI    -> CAUGHT in V2 R1  [HARNESS_REVIEW_RESULT_V2 -> remediated in R2]
10. Idle subagent wakes up 255m later via schedule  -> BLOCKED & REAPED [ZOMBIE_SUBAGENT_SCHEDULE_WAKEUP_GUARD / kill_all]
11. Unattended agy -p script loop risks 403 ban     -> BLOCKED at hook  [AGY_HEADLESS_LOOP_TOS_GUARD] (#199748/#199756)
12. Hydrogen rapid turn burst risks 403 ToS ban     -> PACED at hook    [HYDROGEN_ANTI_BURST_PACER] (#200029/#199971)
```

| Failure Mode in Vanilla AI Sessions | Deterministic Guarantee with Android Agent Harness |
|---|---|
| **Stale verification**: Agent reports `"all tests pass"` from a run executed before its final edit. | Every compile, unit test, V2 review, APK, and device check is bound to `delivery_snapshot_sha256`. Any subsequent byte edit invalidates stale proof automatically. |
| **Unreproduced bug fixes**: Agent guesses at a fix without proving the failure existed. | Applicable `BUG` tasks enforce `CAPTURE_RED_EVIDENCE` (`--capture-red`), requiring a recorded failing test (`red-evidence.json`) before production files unlock. |
| **Scope drift & drive-by refactors**: Agent edits `libs.versions.toml` or rewrites legacy Java/XML unasked. | Per-module architecture resolver preserves local patterns (`MVP`, `MVVM`, `MVI`), and native `PreToolUse` hooks reject unapproved file paths in real time. |
| **Self-approved plans & unwanted Git commits**: Agent rubber-stamps its own plan or runs `git commit` / `push`. | Plan unlocks require a developer-issued approval bound to `plan_sha256` + single-use nonce; `commit`, `branch`, `merge`, `rebase`, and `push` remain strictly human-owned. |
| **Shared Gemini quota exhaustion**: All Gemini models share one `/usage` pool (`Carbon`/`Argon` at `3.00x` vs `Hydrogen`/`Flash` at `1.00x`), while cold subagents cost `~12.4K` startup tokens. | Shared-quota optimal `hydrogen-dynamic` executes `<4`-file slices inline on the warm Lead cache, runs `4+`-file `Worker` slices on `gemini-4-hydrogen-high` (`1.00x`) from Wave 1, caps `T5` reviews at `Hydrogen High` (zero `3x` `Argon` burn), and blocks post-wave re-reads. |
| **Context amnesia across chats**: Every new chat forgets repo conventions and repeats architectural mistakes. | `.agents/project-context/` persists `project-facts.json`, `project-notes.md`, and scoped `developer-instructions.json` across all `7/7` planning, worker, and review surfaces. |

---

## Quick Start

### Chat installation (recommended)

Open your Android or KMM/KMP repository in **Google Antigravity** (or Claude Code) and paste this single pinned bootstrap prompt:

```text
Read https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.3.7/docs/install-or-update-prompt.md and follow all instructions.
```

What happens automatically and non-destructively:
1. **Read-only discovery**: Inspects Gradle modules (`:app`, `:composeApp`, `:shared`, `:core:*`, `:feature:*`), variants, DI frameworks (`Hilt`, `Koin`), Room/SQLDelight schemas, UI toolkits, and locales without touching a single app file.
2. **Language-adaptive interactive preview & sign-off**: Summarizes detected architecture, previews the exact setup plan in the developer's active conversation language, and waits for explicit approval.
3. **Zero-noise isolation**: Stores the immutable release kit outside your repo (`~/.android-harness/kit`), installs only the `.agents/` runtime and selected host adapters, configures `.git/info/exclude` when gitignored mode is selected, and verifies installation health via `doctor --install-check` across all `13` diagnostic dimensions.

### Terminal installation (alternative)

Install globally via `pipx`:

```bash
# 1. Install the standalone CLI (Python 3.10–3.14, zero third-party dependencies)
pipx install android-agent-harness

# 2. Initialize inside your Android or KMP repository (--lang en or --lang ar)
android-harness init --repo /path/to/android-project

# 3. Verify all 13 health & runtime dimensions
android-harness doctor --repo /path/to/android-project --json
```

Or initialize directly from a pinned shallow tag clone with **zero global packages**:

```bash
git clone --depth 1 --branch v1.3.7 --single-branch \
  https://github.com/rabee-elkholy/android-agent-harness.git ~/.android-harness/kit

python ~/.android-harness/kit/harness_cli.py init \
  --repo /path/to/android-project \
  --kit ~/.android-harness/kit
```

Inside any initialized repository, daily commands run through the fast in-process launcher (`~18 ms`):

```bash
python .agents/harness.py doctor --json
```

### Transactional Zero-Clobber Updates, Repair & Clean Uninstall

```bash
# Check release update status (at most once/day background check):
python .agents/harness.py update-info

# Upgrade from the pinned external kit checkout:
python ~/.android-harness/kit/harness_cli.py update --repo /path/to/android-project

# Upgrade directly from a local maintainer checkout:
python /path/to/android-agent-harness/harness_cli.py update \
  --repo /path/to/android-project \
  --kit /path/to/android-agent-harness \
  --no-refresh

# Restore tampered engine files or cleanly uninstall harness-owned files only:
python ~/.android-harness/kit/harness_cli.py repair    --repo /path/to/android-project
python ~/.android-harness/kit/harness_cli.py uninstall --repo /path/to/android-project
```

Updates synchronize `.agents/` in place without breaking open IDE file watchers, preserve `project-notes.md`, `developer-instructions.json`, `harness-verification/` contracts, wizard answers, and task history, refuse mid-flight task clobbering by default (`--preserve-active-task <id> --source-stopped` when intentional), and roll back atomically if interrupted. See [Install & Update Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/install-or-update-prompt.md) and [Restore & Clean Uninstall](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/restore.md).

---

## Measured Performance & Context Efficiency

Every runtime subsystem is implemented in pure Python `3.10–3.14` standard library with content-addressed `blake2b` caching and in-process dispatch. All end-to-end metrics below were measured live against **`mustafaunlu/Ecommerce-Compose`** (`178` files) and **`joreilly/PeopleInSpace`** (`9`-module KMP + `SwiftUI`, `204` files):

| Engineering Dimension | Baseline (`Without Harness` / `v1.3.4`) | Governed by Harness `v1.3.5` | Measured Engineering Gain |
|---|---:|---:|---|
| **Silent Defect Interception** (`18` Seeded Tasks) | `0 / 18` caught (`100%` escaped) | **`18 / 18` caught & delivered (`0%` escaped)** | **`100%` caught** (`14` by `0`-token Python gates in `<200 ms` + `4` by V2 review) |
| **Lead-Chat Discovery Tokens** (`18` Tasks) | `112,097` tokens in Frontier chat | **`~8,640` tokens in Frontier chat** | **`-92.3%` Frontier Lead context** (`90,341` raw tokens isolated in Hydrogen `Scout`) |
| **`plan.md` Artifact Size** (`204`–`1,000+` file repos) | `38,790 B` / `1.84 MB` (`v1.3.4`) | **`5,396 B` / `~5.6 KB`** | **`-86.09%` to `-99.70%` payload bytes** with zero `plan_sha256` hash loss |
| **Read-Only CLI Dispatch** (`harness.py` in-process) | `145.10 ms` subprocess startup | **`18.10 ms` in-process router** | **`8.02x` faster** (`8.59 ms` warm `resolve_next_action` on `1` doc; `13.82 ms` on `500` docs) |
| **Worker Unit-Test Iteration** (`IMPLEMENTING`) | `2x` full `--no-build-cache` pass | **Cached `--tests <Class>` + `cause:` line** | **`2x–10x` faster** feedback without mutating full-suite gate evidence |
| **KMP Test-Target Isolation** (`9`-Module `PeopleInSpace`) | `9 / 9` modules executed (`allprojects`) | **`1 / 9` module (`:common:testAndroidHostTest`)** | **`-88.9%` skipped downstream modules** during `--capture-red` & test authoring |
| **Context Delta Compaction** (`task-context --since`) | `22,774 B` full `SUMMARY` | **`11,439 B` `UNCHANGED` delta** | **`-49.77%` bytes** (`15.18 ms` warm `mixed`, `15.60 ms` `kmp`, `46.35 ms` `+500` files) |
| **Non-Code Note Stripping** (`FILE_FALLBACK` / Reviews) | `40,394 B` / `15,408 B` | **`4,694 B` / `341 B`** | **`-88.38%` / `-97.79%`** non-code PM HTML template bloat stripped automatically |
| **Dual-Mode Lead `Carbon` Quota** (`28` Paired Tasks / `56` Runs) | `364,727` `Carbon` (`3.00x`) tokens (`Normal`) | **`61,218` `Carbon` tokens (`Web-Relay`)** | **`-83.2%` `3.00x` Lead `Carbon` burn** with `100%` parity (`28/28` `DELIVERED` on both modes) |
| **End-to-End Certification** (`Install` + `T1..T10` + `DW-01..35`) | Unverified ad-hoc session edits | **`46 / 46` E2E scenarios `PASSED`** | **`100%` pass rate** + `38 / 38` automated selftest suites (`61` parallel processes) |

Reproducible benchmark suites, task specifications, per-task token ledgers, and raw JSON measurements:
- [Controlled 18-Task A/B Comparison (`Without Harness` vs `With Harness v1.3.5`)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/ab-comparison-v1.3.5.md)
- [Head-to-Head Dual-Mode Benchmark (`Normal Mode` vs `Web-Relay`, `56/56` E2E Runs)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/web-relay-vs-default-v1.3.5.md)
- [Consolidated 18-Task Execution Ledger & Quota Economics (`results-v1.3.5.md`)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/results-v1.3.5.md)
- [Standardized 18-Task A/B Specification Suite (`tasks.md`)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/tasks.md)
- [v1.3.5 Engine, Project-Context & Subagent Benchmarks](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/v1.3.5-engine-and-context-benchmarks.md)
- [End-to-End Certification (`Install + T1..T10`) & `35` Daily Workflow Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/benchmark-status.md)
- [Context Summary Compaction Measurements (JSON)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/implementation/context-summary-measurements.json)

---

## At a Glance: 12 Core Engineering Subsystems

| Subsystem | Engineering Problem Solved | Deterministic Enforcement Mechanism |
|---|---|---|
| **1. Incremental AST & Symbol Graph** | Blind grep loops and token-heavy full-file reads across multi-module repos | Indexes `Kotlin`, `Java`, `XML`, and `Swift` symbols with `blake2b` caching, resolving exact line spans, callers, reuse candidates, and impacted `*Test.kt` files in `~15 ms`. |
| **2. Single-Approval Scope Lock** | Unapproved refactors, silent config edits, and repetitive prompt nagging | One plan approval (`plan_sha256` + single-use nonce) unlocks execution; native `PreToolUse` hooks (`hooks.json`) block unapproved paths and protect `preexisting_dirty` user WIP. |
| **3. Shared-Quota Optimal `Hydrogen` Routing** | Burning `3.00x` `Carbon`/`Argon` quota or paying `~12.4K` cold subagent overhead on tiny 1–3 file edits | `hydrogen-dynamic` (`#1` default) runs `<4`-file slices inline on warm Lead cache (`TRIVIAL_INLINE_LEAD`), starts `4+`-file `Worker` slices directly on `gemini-4-hydrogen-high` (`1.00x`) from Wave 1, and caps `COMPLEX`/`T5_CRITICAL` reviews at `gemini-4-hydrogen-high` (`51` AA Index vs `50` on `Argon`, zero `3x` `Argon` burn). |
| **4. 6-Tier Risk & Epistemic Review V2** | Over-reviewing docs or under-reviewing `Auth` / `Billing` / `Room` diffs | Classifies actual diffs from `T0_TRIVIAL` (`0` reviewers) to `T5_CRITICAL`, dispatching isolated specialists that emit cryptographically bound `HARNESS_REVIEW_RESULT_V2` JSON. |
| **5. Android, KMP & `A2UI 1.0` Gates** | Room crashes, missing `values-ar` keys, `commonMain` leaks, and `A2UI` white-boxes | Zero-token preflight checks for split-file Room migrations, locale string/plural parity, `UI -> DAO` bypasses, Android 15/16 `PendingIntent` flags, `A2UI 1.0` traps, and `commonMain` purity. |
| **6. Persistent Repo Memory** | Repeating module rules and conventions across every new chat session | `.agents/project-context/` merges `project-facts.json`, `project-notes.md`, and scoped `developer-instructions.json` (`--supersedes` & `drift-report`) across all `7/7` surfaces. |
| **7. AST Symbol Surgery & Scaffold** | Corrupting 800-line classes or hand-wiring repetitive multi-module boilerplate | Declaration-level AST editor (`symbol outline/read/replace-body/insert-after`) for `Kotlin`/`Java`/`Swift` with `--expected-sha256` locking, plus architecture-aware `/new-feature` scaffolding. |
| **8. Tracked Debug Probes & Live Inspect** | Accidental `println` / `Log.d` shipping to prod or blind `adb` logcat dumps | `debug add/status/strip` tracks temporary runtime probes (blocking delivery until stripped), paired with `android-inspect`, `logcat_doctor`, and `android-ui <list\|render\|hub>`. |
| **9. Maestro, Roborazzi & Acceptance Contracts** | RTL clipping missed by JVM tests, manual QA repetition, or unverified criteria | **Maestro YAML** physical-device runner/exporter, **Roborazzi** `.uitree.json` viewport gate, `--verification-contract` JUnit method binding (`bind-evidence`), and `device validate-automatically`. |
| **10. Snapshot-Bound EvidenceStore** | Claiming `"tests pass"` from stale runs or vacuous `0`-test legacy modules | Binds `preflight`, `compile`, non-empty `unit_tests`, V2 verdicts, APKs, and `device install-start` to `delivery_snapshot_sha256` and `change_set_sha256`. |
| **11. Multi-Task, WIP Handoff & Context Bridge** | Context degradation in `100k+`-token chats and mid-feature hotfix collisions | Supports up to `3` concurrent disjoint tasks (`task switch`), plan consolidation (`task merge`), WIP commit lineage (`task handoff`), and cross-chat/host rotation (`task bridge` / `continue`). |
| **12. Universal PM MCP, Forensics & Self-Heal** | Unauthorized ticket closures, opaque hook stalls, or interrupted task state | Zero-config governance for `9` PM trackers (`pm authorize` & RTL/LTR `prepare-report`), `task heal` rollback, `diagnose-session`, local `task metrics`, and Zero-PII `report-issue`. |

---

## What daily use looks like

```text
  Developer Prompt ("Fix blank weightGoal bug on STEPS users in CaloriesViewModel")
         │
         ▼
  [1. AST Discovery] ──► graph / task-context (~15 ms) or parallel Hydrogen Scout wave (<1.5k-token digest)
         │
         ▼
  [2. Single Plan]   ──► Concise plan.md + 1 language-adaptive approval card (plan_sha256 + single-use nonce)
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

1. **Anchored Discovery**: Resolves exact callers, tests, and repo-local constraints via `graph` and `task-context` (or parallel `Gemini 4 Hydrogen` `harness-scout-agent` waves on multi-subsystem tasks).
2. **One Concise Plan**: Generates a compact `plan.md` (`~5.4 KB` even on 9-module KMP repos) with impacted existing tests and auto-routed domain skills surfaced upfront.
3. **Explicit Developer Approval**: Waits once for your sign-off (`Approve` / `Request changes` / `Cancel task`) — zero mid-task nagging, with mid-verification developer edits reconciled cleanly via `task change-decision`.
4. **Scoped Execution**: Reproduces bugs first (`--capture-red`), supports tracked temporary runtime probes (`debug add` -> `debug strip`), iterates rapidly with `--tests <Pattern>` on cached Gradle builds, and protects pre-existing uncommitted user files (`preexisting_dirty`).
5. **Risk-Adaptive Gates**: Executes zero-token static/domain gates (`verify-steps`), module-scoped unit tests (rejecting vacuous `0`-test suites), and epistemically isolated V2 specialist reviews matched to the final diff.
6. **Device & Walkthrough Sign-off**: Runs `device install-start`, interactive `e2e start`, `device validate-automatically` replayable journeys, or `maestro run` when UI/device surfaces warrant hardware proof.
7. **Human Git Delivery**: Leaves verified changes cleanly in your working tree under **Human Git Authority** (reopening cleanly via `task resume --reopen` if post-ready tweaks are needed) and closes out once you commit.

### Multi-Phase Tasks, Disjoint Worktrees & Smart Context Bridging

- **Single-Approval Multi-Phase Execution (`p1 -> p2 -> ...`)**: Large cross-module features run phase checkpoints (`checkpoint-phase` + optional `phase-review`) without redundant mid-phase approvals, preserving completed phase proof even across mid-task `workflow.py revise` updates.
- **Up to 3 Concurrent Disjoint Tasks & WIP Lineage**: Keep three independent tasks live in one worktree (`task switch --task-id <id>`), consolidate pre-approval drafts (`task merge --apply`), or freeze urgent hotfix interruptions (`task handoff` -> developer WIP commit -> `task reconcile-handoff`).
- **One-Command Chat & Host Rotation (`task bridge` & `task continue`)**: Transfer active contracts, `interface_delta` signatures, and a fresh Discovery Receipt to a clean chat — or switch AI hosts mid-task (`task continue --host claude --source-stopped`):

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

Android Agent Harness is built primary-first for **Google Antigravity** with `HARD_ENFORCED` native hooks (`.agents/hooks.json`), **all `8` custom subagents** pre-installed under `.agents/agents/<role>/agent.md`, real `SYSTEM` / `SYSTEM_SDK` / `transcript_full.jsonl` verification, and proactive runtime diagnostics:

- **Cryptographically Bound `HARNESS_REVIEW_RESULT_V2`**: Specialist reviewers emit structured JSON tied to `delivery_snapshot_sha256`, `change_set_sha256`, and `package_sha256` (with optional `criterion_results` and developer `--override-reviews` audit trail).
- **Complete `8`-Role Pre-Installed Subagent Roster (`.agents/agents/`)**:
  - **4 V2 Code Reviewers**:
    - `bug-test-reviewer-agent` — Behavioral correctness, boundary conditions, nullability, structured concurrency/cancellation, lifecycle state, and unit-test assertion rigor.
    - `arch-regression-reviewer-agent` — Cross-module blast radius, navigation/deep-link callers, Clean Architecture boundaries, KMP source-set purity, and localization parity.
    - `security-perf-reviewer-agent` — Auth/Billing/Crypto invariants, exported Manifest components, `PendingIntent` mutability, main-thread I/O & ANR hazards, and Compose stability.
    - `spec-compliance-agent` — Requirement-by-requirement verification against the approved plan and acceptance criteria when routed.
  - **2 On-Demand Domain Specialists**:
    - `qa-diagnostics-agent` — Deep crash/ANR stacktrace root-cause triage, flaky-test forensics, and runtime state diagnosis.
    - `android-ui-expert-agent` — Compose/XML layout hierarchy review, RTL/accessibility ergonomics, Material 3 adaptive design, and viewport clipping diagnosis.
  - **2 Quota-Safe Gen-4 Utility Subagents**:
    - `harness-scout-agent` — Pinned read-only AST/graph explorer (`gemini-4-hydrogen-medium` by default) returning `<1,500`-token `file:line` architectural digests.
    - `harness-worker-agent` — Scoped slice & unit-test builder starting directly on `gemini-4-hydrogen-high` from Wave 1 on `4+`-file slices (while `<4`-file `T0–T3` slices run inline on the warm Lead cache via `TRIVIAL_INLINE_LEAD`), governed by `delegate-plan` (`FULL_SLICE`, `CAPTURE_RED_ONLY`, or `TESTS_AND_GATES_ONLY`).
- **`Zero-Hop` Inlined Briefs & Single-Turn Batch Ingestion**: Review packages (`<= 24 KB`), `GraphEngine` blast-radius topologies, and passed deterministic gate proofs are inlined directly inside `brief-<role>.md`. `python .agents/harness.py review complete-all --task <id>` (and `phase-review complete-all`) ingests all parallel verdicts in one turn, guarded by a **Reviewer Call Safety Cap** (default: `20`, per-reviewer budget: `12` calls; adjustable per task via `task review-budget`).
- **Antigravity Platform, Quota & Account-Safety Guards (`v1.3.5`)**:
  - **Zombie Subagent & `255m` Reactive-Wakeup Guard (`#199713`)**: Strips `schedule` permissions from all `.agents/agents/*/agent.md` manifests, blocks `schedule` / `schedules:*` wakeup triggers (`ZOMBIE_SUBAGENT_SCHEDULE_WAKEUP_GUARD`), permits `manage_subagents({"Action": "kill_all"})` across all task states to reap idle subagents immediately after waves/tasks finish, and flags `>= 2h` reactive-wakeup spikes in `doctor` and `diagnose-session`.
  - **Unattended `agy -p` & UI-Injection ToS Anti-Ban Guard (`#199748` / `#199756`)**: Blocks unattended `agy -p` / `--headless` loops and programmatic UI keystroke injection (`AGY_HEADLESS_LOOP_TOS_GUARD`) to protect Google AI Ultra accounts from automated `403 PERMISSION_DENIED` suspension while preserving interactive Skill workflows.
  - **Managed Agent `limit: 0` Zero-Quota, Hydrogen Rollout & Regional `503` Diagnostics (`#199769` / `#199770` & `#198333`)**: Classifies Free/Pro tier `HTTP 429` (`limit: 0`) errors on `gemini-4-argon` / `gemini-4-carbon` (`MANAGED_AGENT_ZERO_QUOTA_429` -> 1-command switch to `hydrogen-dynamic-project`), `Gemini 4 Hydrogen` rollout/entitlement blocks (`HYDROGEN_ROLLOUT_ENTITLEMENT_BLOCK` -> `flash-argon-project` fallback), `Orchestrator` double-planning friction (`ORCHESTRATOR_DOUBLE_PLANNING_HAZARD`), and regional `gemini-3.8-flash` `HTTP 503` backoff stalls (`FLASH_503_CAPACITY_BACKOFF`) in `diagnose-session`.
  - **Hydrogen `403 TOS_VIOLATION` Anti-Burst Pacer, Native Orchestrator Escalation, Turn-3 Cache Shield & Win11 `v2.7.0` Guard (`#200029`, `#199971`, `#200026`, `#200037`)**: `PreToolUse` (`HYDROGEN_ANTI_BURST_PACER`) passes same-turn parallel batches (`<= 200ms`) at `0ms` delay while smoothing `>= 4`-turn sequential `Hydrogen` bursts (`0.8s–1.4s` human cadence) to prevent false-positive `403 TOS_VIOLATION` suspensions; `Native Harness Orchestrator` evaluates completed `Worker` waves at `PostToolUse` via `delivery_snapshot_sha256` (`unit_tests.json`), capping automatic `Hydrogen` thinking at `High` (which ties `xHigh` at `54%` on `Terminal-Bench 4.0` while avoiding `2.76x` token verbosity and `+69%` cost), giving `Hydrogen High` up to **`2` full attempts** from Wave 1 (`High #1` -> `High #2` -> `Carbon`, with instant **1-wave `Fast-Fail`** on `[SCOPE-HINT]` / architectural blockers) and persisting `.agents/state/tasks/<id>/worker-handoff.json` (**`Zero-Scratch Handoff Capsule`**) so `Lead Architect (Carbon)` resumes directly on top of completed files, passing gates, and exact failure diagnostics (`ORCHESTRATOR_FRICTION_LEAD_TAKEOVER`); `PreInvocation` locks Turn-0 subagent prefixes + `<= 2`-turn `Scout` mega-batches (plus optional `safe-cache-project`) against `#200026` `Turn-3 +701 / cache=0` drops; and `doctor` warns against Windows 11 `Smart App Control Error 4551` on `Antigravity IDE v2.7.0` (`#200037`).
  - **Remote Mode Quota-Leak, Frontmatter Pin, File-Watcher & IDE Stability Guards (`#198819`, `#198689`, `#199301`)**: Blocks silent fast-tier -> Frontier billing in Remote Mode (`REMOTE_MODE_FLASH_QUOTA_LEAK_GUARD` across both `Hydrogen` and `Flash`), enforces explicit `.agents/agents/*/agent.md` `model:` pins before omitted-`Model` dispatch (`SUBAGENT_FRONTMATTER_UNPINNED_GUARD`), detects `language_server.log` `WatchVersionControlState` spin-loops / `>= 500 MB` bloat, audits `.vscode/settings.json` `files.watcherExclude`, and flags multi-server Windows `stdio` MCP pipe collisions.

---

## Hybrid Flash Orchestration & Frontier Quota Protection

Version `1.3.5` ships the **Shared-Quota Optimal `Gemini 4 Hydrogen` Engine (`hydrogen-dynamic` / `hydrogen-dynamic-project`)** as the recommended `#1` project-wide routing policy, calibrated to Antigravity's single shared Gemini quota pool (`Carbon` & `Argon` weighted at `3.00x` = `$6/$30` effective vs `Hydrogen` at `1.00x` = `$1.50/$7.50`). It pairs an explicit **`Gemini 4 Carbon (Medium)`** Lead Architect (or `Claude Sonnet/Opus 5.5` separate-pool rotation / `Web-Relay` external offload — never Antigravity's built-in `Orchestrator` dropdown) with warm-cache `<4`-file inline edits (`TRIVIAL_INLINE_LEAD`), Wave-1 `gemini-4-hydrogen-high` `4+`-file `Worker` execution, and zero `3x` `Argon` burn:

| Complexity Band | Automatic Task / Diff Trigger | Routed Execution & Reviewer Models (`hydrogen-dynamic`) | Shared-Pool Quota & Reasoning Profile |
| :--- | :--- | :--- | :--- |
| **Band 0: `SMALL_INLINE`** | `T0` docs or `1–3` planned files (`< 4` files) on `T0–T3` | **Warm-cache inline Lead edit (`TRIVIAL_INLINE_LEAD`)**; `0` cold `Worker` spawn (`gemini-4-hydrogen-medium` reviews if `T2+`) | Skips `~12.4K`-token cold subagent startup overhead in the shared Gemini pool |
| **Band 1: `SIMPLE` (`4+` files)** | Single-module `T1–T2` with `>= 4` planned files | **`gemini-4-hydrogen-high`** `Worker` (from Wave 1) + **`gemini-4-hydrogen-medium`** `Scout` & reviewers | `1.00x` shared-pool weight (`4x` cheaper than `Carbon`/`Argon`); avoids failed `Medium` Worker retries |
| **Band 2: `COMPLEX` (`4+` files)** | `BUG`, `>= 2` modules/phases, `>= 4` files, `T3/T4`, `COROUTINES`/`NETWORK`/`ROOM_SCHEMA`/`PUBLIC_API`, or `Round 2` | **`gemini-4-hydrogen-high`** (`Worker`, `bug-test`, `security-perf`, `DEEP` roles) + **`gemini-4-hydrogen-medium`** (`Scout` + `NORMAL` `arch-regression`) | `1.00x` shared-pool weight; `Hydrogen High` scores `51` vs `Argon` `50` on AA Index |
| **Band 3: `CRITICAL` (`T5`)** | `T5` (`AUTH`, `BILLING`, `CRYPTO`, `SECURITY`, `SENSITIVE_DATA`) or `Round 3+` | **Lead Architect (`Carbon Medium`)** writes production code (`Worker` runs `TESTS_AND_GATES_ONLY` on `gemini-4-hydrogen-high`); **all routed reviewers run `gemini-4-hydrogen-high`** | Zero `3.00x` `Argon` shared-pool penalty while preserving `51`-index reasoning across security/logic & architecture |
Additional enforced subagent guardrails across all waves:
- **Scale-Adaptive Step Budgets**: `harness-scout-agent` capped at **`24` calls/instance** (blocking built-in unpinned `research`/`explore` via `USE_HARNESS_SCOUT_AGENT`); `harness-worker-agent` defaults to **`32` read/search calls** and scales automatically up to **`140` reads** (`slice_files + 16`) on `30–100+` file slices (edits & Gradle uncapped); specialists capped at **`24`**; reviewers default to **`12`** calls and scale automatically up to **`48` calls** on large diffs.
- **Post-Wave Anti-Reread Guard**: Native hooks block bloated `> 220`-line Lead re-reads on `> 350`-line files already digested by subagents and cap post-wave surgical Lead reads at **`<= 3`**. See [Reviewer Model Configuration](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/reviewer-models.md).
- **Interactive Execution Mode Selector (`execution-mode show|set`) & Large-Scale Stateless Web-Relay (`web-pack` / `web-apply`, `1–250` Files)**: Choose **Smart Auto** (`auto-project` / `auto-task` — runs `<12`-file single-module tasks locally in Antigravity and promotes `12+`-file, multi-module, `T5` critical, or `2-Strike` tasks automatically to Gemini Web), **Normal Mode** (`normal-task` / `normal-project`), or **Web-Relay Mode** (`web-task` / `web-project`, cutting **`-83.2%` Lead `Carbon` burn across `28` paired benchmark tasks**). Packs `1–40` files into **one** single `.md` bundle (handling routine `30`-file tasks in 1 pass) and auto-shards `41–250` file refactors in Clean Architecture DAG order (`Batch 1/N` + `"status": "PARTIAL"` continuation + `APPLIED_BATCH_NEXT_READY` auto-copy + multi-batch `staged-web-phases` accumulation); shields binary media/fonts (`.png`/`.webp`/`.ttf`) while indexing module `R.drawable.*`/`R.font.*`/`Res.drawable.*` IDs automatically; allows verified surgical `hunks` on neighbor callers; extracts replies via `JSONDecoder.raw_decode`; keeps read-only `IDLE` chats prompt-free; preserves `plan_sha256` across mid-task `normal <-> web` switches, `task bridge`, and `task switch`; and keeps all-secret scopes and Git `CONFLICT` markers (`<<<<<<<`) safely local.

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
- **KMP Source-Set, Type-Safe Accessors & Xcode Purity**: Indexes `commonMain`, `androidMain`, `iosMain`, `:composeApp`, `:shared`, and `.swift`; resolves Gradle `projects.*` type-safe accessors; blocks `android.*` / JVM leaks in `commonMain`; verifies `expect` / `actual` pairing; skips Apple-only KMP targets cleanly on Linux/Windows; and filters non-Gradle Xcode `SwiftUI` folders from Gradle task resolution.
- **Jetpack Compose `A2UI 1.0` & Android 15/16 Static Gate (`fast_kt_lint.py`)**: Catches uncollected `A2UI` `outboundEvents` (silent white-box bug), `material3-a2ui` vs stable Compose BOM conflicts, `catalogId` mismatches, missing `PendingIntent` immutability flags, swallowed `CancellationException`s, `Fragment` `_binding` leaks, missing `@Preview`s, cleartext `http://` URLs, and `UI -> DAO` bypasses in `< 35 ms` at `0` tokens.
- **Mixed Legacy & Modern Coexistence**: Resolves architecture rules per module (`Java + XML + MVP` beside `Kotlin + Compose + MVI`) without forcing unapproved migrations.

---

## Domain Skills, Workflows & Slash Command Packs

Instead of stuffing static rules into every prompt, `skill_router.py` attaches specialized domain skills on demand based on the active task's classified surfaces:

| Category | Auto-Routed Domain Skills (`.agents/skills/*/SKILL.md`) |
|---|---|
| **Core & Context Efficiency** | `android-harness` (lifecycle kernel) · `efficient-context` (AST graph, `--since` deltas & `symbol` surgery) · `brainstorming` (pre-plan architecture trade-offs) |
| **UI, Compose & Coroutines** | `compose-inspector` (state hoisting, stability & `@Preview` parity) · `android-ui-diagnostics` (`android-ui`, RTL & viewport bounds) · `kotlin-coroutines-expert` (structured concurrency & `Flow` safety) |
| **Security, Build & Quality** | `android-security-billing` (`Keystore`, Play Billing, OAuth & Manifest hardening) · `gradle-build-optimizer` (daemon lock, caching & KMP targets) · `test-driven-development` (`RED -> GREEN` & JUnit assertions) · `systematic-debugging` (`debug` probes & crash root-cause) |
| **Device QA, Git & PM** | `phone-e2e` (live ADB / Maestro hardware walkthroughs) · `git-pr-automator` (Conventional Commits & PR summaries under Human Git Authority) · `pm-tracker` (multi-provider MCP ticket sync & QA handoff reports) |

### 15 Playbook Workflows & 11 Native `/slash` Command Packs
- **Workflow Playbooks (`.agents/workflows/*.md`)**: `new-feature` (backed by `new_feature_scaffold.py` architecture-matched module/class scaffolding), `crash-triage` (`logcat_doctor.py`), `perf-audit` (`perf_guard.py`), `test-quality-audit`, `android-inspection`, `android-ui`, `check-strings`, `commit-msg`, `debug`, `deliver`, `efficient-context`, `phone-e2e`, `pm-tracker`, `preflight`, and `web-relay` (`web-pack` / `web-apply` manual Gemini Web offload).
- **Host Slash Commands (`agents/command-packs/`)**: Automatically rendered into `.claude/commands/*.md` (Claude Code), `.github/prompts/*.prompt.md` (GitHub Copilot), and `.codex/prompts/*.md` (Codex) for one-command `/doctor`, `/preflight`, `/new-feature`, `/debug`, `/crash-triage`, `/perf-audit`, `/test-quality-audit`, `/check-strings`, `/pm-tracker`, `/commit-msg`, and `/deliver` invocation.

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

# Bind a scoped architectural requirement in developer-instructions.json (supports --supersedes <id>):
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
- **Tracked Temporary Diagnostic Probes (`debug`)**: Inject tracked runtime logs during root-cause investigation (`python .agents/harness.py debug <add|status|strip>`); `prepare-verification` fails closed (`assert_clean`) if any temporary probe remains unstripped.
- **Live Android Device Inspection & UI Diagnostics (`android-inspect` & `android-ui`)**: Structured read-only `logcat` crash/ANR extraction, `dumpsys` activity/package/permission inspection, and Compose/XML hierarchy rendering (`android-ui <list|render|hub>`).
- **Maestro Physical-Device Bridge & Exporter (`maestro`)**: Executes `.maestro/*.yaml` against the bound physical device, blocks destructive `clearState` / `uninstallApp` commands unless `--allow-clear-state` is granted, and exports passing `phone_e2e` runs into `.maestro/<task_id>.yaml` regression suites.
- **Roborazzi Headless `.uitree.json` Viewport & RTL Gate (`roborazzi`)**: Audits Compose `.uitree.json` sidecars on the JVM for `HORIZONTAL_VIEWPORT_CLIP` (catching Arabic RTL overflow), `ZERO_DIMENSION_NODE`, and `CLICKABLE_SIBLING_COLLISION`.
- **Verifiable Acceptance Contracts & Auto-Replayable Device Journeys (`journey` & `bind-evidence`)**: Attach `--verification-contract` JSON definitions to bind required criteria to exact passing JUnit cases (`task bind-evidence --case "Class#method"`), inspect `task coverage --json`, and replay bounded (`<=40` steps / `<=120s`) post-install device walkthroughs (`device validate-automatically`) with `secret_env` credential protection. See [Verification Value & Journeys](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/verification-value.md).
- **Diff-Scoped Static Health, Local Telemetry & Zero-PII Forensics (`health`, `task metrics`, `diagnose-session`, `report-issue`)**: Filters Detekt / Android Lint `*.sarif` and Gradle `build-health-report.json` strictly to task-touched files, checks post-E2E `LeakCanary` heap dumps, records opt-in zero-content command timings (`HARNESS_LOCAL_METRICS=1` -> `task metrics --json`), diagnoses hook/token stalls (`diagnose-session`), and prepares consent-first Zero-PII incident bundles (`report-issue`).
- **Universal Zero-Config PM MCP & Self-Healing (`pm` & `task heal`)**: Governs **Zoho Sprints**, **Zoho Projects**, **Jira**, **Linear**, **GitHub Projects**, **ClickUp**, **Asana**, **Monday.com**, and **Trello** with `pm authorize` previews, protected Bug descriptions, 5-section RTL/LTR QA handoff reports (`pm prepare-report`), and 1-command state recovery (`task heal --prepare-fresh-run`).

---

## Supported Hosts & Enforcement Model (`15` AI Coding Hosts)

| AI Coding Host | Installed Adapters & Assets | Scope & Mutation Enforcement | Review Protocol | Final Snapshot Verifier |
|---|---|---|---|---|
| **Google Antigravity** *(Primary Target)* | `GEMINI.md`, `AGENTS.md`, `.agents/hooks.json`, `.agents/agents/*/agent.md` (`8` pre-installed subagents), rules, `13` skills, `14` workflows | **`HARD_ENFORCED`** (`PreToolUse` & `PostToolUse` native hooks) | Trusted transcript `HARNESS_REVIEW_RESULT_V2` | **Yes** (`SHA-256` bound) |
| **Claude Code** | `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json` hooks, `.claude/agents/*`, `.claude/commands/*` (`11` slash packs) | Hook + Rule enforced | Native subagent transcript verification | **Yes** (`SHA-256` bound) |
| **GitHub Copilot & Codex** | `AGENTS.md`, `.github/copilot-instructions.md`, `.github/hooks/*`, `.github/prompts/*`, `CODEX.md`, `.codex/prompts/*` | Bridge Hook / **`RULE_ENFORCED`** + CLI gates | Structured response ingestion | **Yes** (`SHA-256` bound) |
| **Gemini CLI, Cursor, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, Goose & Qwen** | `AGENTS.md` + native host rule adapters (`GEMINI.md`, `.cursor/rules`, `.windsurf/rules`, `.clinerules`, `.roo/rules`, `.amazonq/rules`, `.continue/rules`, `.junie/guidelines.md`, `.kilocode/rules`, `.goosehints`, `QWEN.md`) | **`RULE_ENFORCED`** + downstream CLI gates | Structured response ingestion | **Yes** (`SHA-256` bound) |

See [AI Tool Support Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md) and [Cross-Host Continuation](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/host-continuation.md).

---

## Essential CLI Reference

| Goal | Command |
|---|---|
| **Check installation & 13-dimension health** | `python .agents/harness.py doctor [--install-check] [--json]` |
| **Explore module/feature symbol graph** | `python .agents/harness.py graph --feature <name> --json` |
| **Resolve target file/symbol AST context** | `python .agents/harness.py task-context --file <path> [--since <digest>] --json` |
| **Inspect Hybrid model delegation plan** | `python .agents/harness.py delegate-plan [--task-id <id>] --json` |
| **Check active task deterministic next step** | `python .agents/harness.py task status --task-id <id> --next` |
| **Run full deterministic gate sequence** | `python .agents/harness.py verify-steps --task-id <id> --host antigravity` |
| **Fast single-class TDD test iteration** | `python .agents/harness.py test [--capture-red] [--tests <ClassOrMethod>]` |
| **Surgical AST symbol outline / replacement** | `python .agents/harness.py symbol <outline\|read\|replace-body\|insert-after> ...` |
| **Inject / strip tracked debug probes** | `python .agents/harness.py debug <add\|status\|strip> [--task-id <id>]` |
| **Live Android device & UI diagnostics** | `python .agents/harness.py <android-inspect \| android-ui> ...` |
| **Manage persistent repo notes & rules** | `python .agents/harness.py context <note\|instruct\|drift-report> ...` |
| **Bind acceptance criteria & check metrics** | `python .agents/harness.py task <coverage\|bind-evidence\|metrics> --task-id <id>` |
| **Bridge context or switch host mid-task** | `python .agents/harness.py task <bridge \| continue --host claude --source-stopped>` |
| **View or switch execution mode (`Normal` / `Web`)** | `python .agents/harness.py execution-mode <show \| set --choice auto-project --source conversation --proof-reference "...">` |
| **Optional Gemini Web manual quota relay** | `python .agents/harness.py <web-pack [--dirty] --prompt "..." \| web-apply [--dry-run] --source developer_terminal>` |
| **Ingest parallel V2 reviews in 1 turn** | `python .agents/harness.py <review\|phase-review> complete-all --task <id>` |
| **Run physical-device / Maestro / UI gates** | `python .agents/harness.py <device install-start \| maestro run \| roborazzi verify>` |
| **Self-heal state, forensics & Zero-PII issue** | `python .agents/harness.py <task heal --task-id <id> \| diagnose-session \| report-issue>` |

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
├── harness.py             # Fast ~18 ms in-process CLI router & 33-command dispatcher
├── command-packs/         # 11 /slash prompt templates for Claude Code, Copilot & Codex
├── rules/                 # Canonical English behavioral kernel (<= 36k combined budget)
├── scripts/               # Pure Python 3.10–3.14 stdlib governance, AST graph, gates & doctor
├── skills/                # 13 auto-routed domain skills (Compose, Coroutines, Security, KMP, QA)
├── subagents/             # 8 isolated V2 reviewer, specialist, Scout & Worker templates
├── tool-adapters/         # Managed adapters for 15 AI hosts (Antigravity, Claude, Cursor & more)
└── workflows/             # 15 engineering playbooks (new-feature, crash-triage, perf-audit, E2E)
```

- **Cross-Platform CI Matrix**: Validated across **Ubuntu 24.04**, **Windows Server 2025**, and **macOS 15** on **Python 3.10–3.14**, running `38` deterministic selftest suites (`61` parallel processes via `python harness_cli.py selftest`), wheel packaging lifecycle smoke checks, `270`-file `SHA-256` release checksum verification, and adversarial hook/security tests.
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
<summary><b>4. How does Shared-Quota Optimal Hydrogen routing (hydrogen-dynamic) minimize Antigravity Gemini pool burn?</b></summary>
<br>
Inside Antigravity, all Gemini models share one <code>/usage</code> quota pool where <code>Carbon</code> and <code>Argon</code> draw at a <code>3.00x</code> multiplier (<code>$6/$30</code> effective per 1M tokens) while <code>Gemini 4 Hydrogen</code> draws at <code>1.00x</code> (<code>$1.50/$7.50</code> — <code>4x</code> cheaper per token) and scores <code>51</code> at <code>High</code> vs <code>50</code> on <code>Argon</code>. Under <code>hydrogen-dynamic-project</code>, small <code>1–3</code> file slices run inline on the warm Lead cache (<code>TRIVIAL_INLINE_LEAD</code>) to skip the <code>~12.4K</code>-token cold subagent startup tax, <code>4+</code>-file <code>Worker</code> slices start on <code>gemini-4-hydrogen-high</code> from Wave 1 (eliminating wasted <code>Medium</code> retry waves), and <code>COMPLEX</code> / <code>T5_CRITICAL</code> reviews cap at <code>gemini-4-hydrogen-high</code> with <b>zero <code>3x Argon</code> subagent burn</b> (with <code>Web-Relay</code> and <code>Claude 5.5</code> available to offload tokens outside the Antigravity Gemini pool altogether).
</details>

<details>
<summary><b>5. Can I keep multiple tasks open in the same worktree without committing first?</b></summary>
<br />
Yes — up to <b>three live tasks</b> may share a single worktree simultaneously as long as their planned file sets are disjoint. Switch active tasks with <code>python .agents/harness.py task switch --task-id &lt;id&gt;</code>, combine pre-approval drafts with <code>task merge</code>, and finalize individual developer commits via <code>task reconcile-delivery --task-id &lt;id&gt;</code>.
</details>

<details>
<summary><b>6. What happens if managed files under .agents/ are accidentally edited, or if I want to uninstall cleanly?</b></summary>
<br />
Run <code>python .agents/harness.py doctor</code> to diagnose any drift across all 13 health dimensions, <code>python ~/.android-harness/kit/harness_cli.py repair --repo /path/to/app</code> to restore checksum-verified engine files and subagent manifests, or <code>harness_cli.py uninstall --repo /path/to/app</code> to remove harness-managed files cleanly without touching your application code.
</details>

<details>
<summary><b>7. How do I choose or switch between Normal Mode (Antigravity) and Web-Relay Mode mid-task or across chats?</b></summary>
<br />
When no project-wide mode is saved yet, starting a real coding task in Antigravity prompts once with 5 clear choices led by <code>auto-project</code> (Smart Auto), alongside <code>normal-task</code>, <code>normal-project</code>, <code>web-task</code>, and <code>web-project</code> (while read-only architectural questions in <code>IDLE</code> never interrupt you). You can switch modes at any point — even mid-task — via natural chat instructions (recorded with <code>python .agents/harness.py execution-mode set --choice &lt;choice&gt; --source conversation --proof-reference &quot;...&quot;</code>) or reset to prompt on every new task via <code>--choice ask-every-task</code>. Mid-task switches preserve <code>plan_sha256</code> approval, <code>task bridge</code> carries active mode state into fresh chats, and Git merge conflicts automatically run locally without altering your saved project preference.
</details>

---

## Documentation Hub

- [Quickstart Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/quickstart.md) · [Install or Update Prompt](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/install-or-update-prompt.md) · [Setup Wizard Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/setup-wizard.md)
- [Architecture Reference](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/architecture.md) · [Workflow Guide](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/workflows.md) · [Efficient Task Context](https://github.com/rabee-elkholy/android-agent-harness/blob/main/agents/workflows/efficient-context.md)
- [Reviewer Model Configuration](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/reviewer-models.md) · [Verification Value & Journeys](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/verification-value.md) · [PM MCP Integrations](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/workflows/pm-integrations.md)
- [Compatibility Matrix](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/compatibility-matrix.md) · [AI Tool Support (`15` Hosts)](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/tool-support.md) · [Cross-Host Continuation](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/host-continuation.md)
- [Threat Model](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/threat-model.md) · [Restore & Clean Uninstall](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/restore.md) · [v1.3.5 Benchmarks & A/B Suite](https://github.com/rabee-elkholy/android-agent-harness/blob/main/docs/benchmark/ab-comparison-v1.3.5.md)

---

## License

MIT License. See [LICENSE](https://github.com/rabee-elkholy/android-agent-harness/blob/main/LICENSE).
