# Reviewer model configuration

Inheritance is the default and existing installations need no migration.
Model choices do not alter the policy-selected reviewer roster, risk, budgets,
or the requirement for independent review proof.

| Host | Supported choices | Enforcement |
|---|---|---|
| **Google Antigravity** (Primary Runtime) | `inherit`, `hydrogen-argon-hybrid`, `hydrogen-dynamic`, `hydrogen-risk-hybrid`, `flash-argon-hybrid`, `risk-hybrid`, `flash-dynamic`, `argon-dynamic`, `hybrid-smart`, `gemini-4-hydrogen-low`, `gemini-4-hydrogen-medium`, `gemini-4-hydrogen-high`, `gemini-4-hydrogen-xhigh` (`extra`), `gemini-4-argon-low`, `gemini-4-argon-medium`, `gemini-4-argon-high`, `carbon-dynamic`, `gemini-4-carbon-low`, `gemini-4-carbon-medium`, `gemini-4-carbon-high`, `gemini-3.8-flash-fast`, `gemini-3.8-flash-low`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-high`, `gemini-3.1-pro-low`, `gemini-3.1-pro-high` (or `<model>@<fast\|low\|medium\|high\|xhigh\|extra\|hybrid\|dynamic>`) | Synced into `.agents/agents/<role>/agent.md` YAML frontmatter (`model:`); `invoke_subagent` omits `Model` for `hydrogen`/`argon`/`carbon`/`inherit` (passing `Model="flash"` only for legacy `gemini-3.8-flash-*`); native SQLite metadata verified |
| Legacy / Compatibility Adapters (Claude Code, etc.) | `inherit` (`sonnet`, `opus`, `haiku` on Claude Code) | Host-managed or rule-enforced native Agent/Task model argument |

## Antigravity pre-review interactive choices (`SELECT_REVIEW_MODEL`)

When a task or phase review on Antigravity reaches `DISPATCH_REVIEWERS` / `DISPATCH_PHASE_REVIEWERS` with no explicit model bound (`source == "default"`), the router emits `before_first_dispatch` (`code = "SELECT_REVIEW_MODEL"`) with 5 streamlined developer choices (while keeping `-once`, `flash-argon-*`, `risk-hybrid-*`, `flash-dynamic-*`, and `hybrid-smart-*` aliases available via `--choice`):

1. `hydrogen-argon-project` (`--default hydrogen-argon-hybrid --scope project` / `--preset hydrogen-argon-hybrid`): **Complexity-Adaptive `Gemini 4 Hydrogen + Argon Low` Hybrid for Entire Project (Recommended #1)** — pairs an explicit `Gemini 4 Carbon (Medium)` Lead Architect with `Gemini 4 Hydrogen` workhorses and a strict `Gemini 4 Argon (Low)` `T5` security ceiling:
   - **Band 0 (`TRIVIAL` — `T0` / micro strings / docs)**: `0` subagents (inline Lead edit + deterministic preflight).
   - **Band 1 (`SIMPLE` — single-module `T1–T2` UI/ViewModel/Resource feature, `<= 3` non-test files, `<= 90` lines)**: **100% `gemini-4-hydrogen-medium`** across `Scout`, `Worker`, and **all** routed reviewers (`0` `Argon` / `Carbon` subagent quota used; `2.5x` faster than `3.8 Flash` with `5x` lower fabricated claims).
   - **Band 2 (`COMPLEX` — `BUG` root-cause tasks, multi-module `>= 2`, multi-phase `>= 2`, `>= 4` non-test files or `> 90` lines, `T3/T4`, or `COROUTINES` / `NETWORK` / `ROOM_SCHEMA` / `PUBLIC_API` / `DEVICE_API` / `Round 2`)**: **Precision `Hydrogen High + Medium` Split** — upgrades `harness-worker-agent` (`FULL_SLICE`), `bug-test-reviewer-agent`, `security-perf-reviewer-agent`, and any `DEEP`-effort specialist to **`gemini-4-hydrogen-high`** (`0` `Argon` / `Carbon` subagent quota!), while keeping `harness-scout-agent` and `NORMAL` structural reviewers (`arch-regression-reviewer-agent`) on **`gemini-4-hydrogen-medium`**.
   - **Band 3 (`CRITICAL` — `T5` `AUTH` / `BILLING` / `CRYPTO` / `SECURITY` / `SENSITIVE_DATA`, `CRITICAL` severity, or `Round 3+`)**: Lead Architect (`Gemini 4 Carbon Medium`) writes core production files directly (`Worker` runs `TESTS_AND_GATES_ONLY` on `gemini-4-hydrogen-medium`), escalating critical security/logic specialists (`security-perf-reviewer-agent`, `bug-test-reviewer-agent`, and `MAX`-effort Round 3+ roles) to **`gemini-4-argon-medium`** (`thinking_level="medium"`, Google's recommended code default + `4%` AA-Omniscience hallucination floor, avoiding `argon-low` hard-task quality drops and `argon-high` token bloat) while keeping structural/UI/spec reviewers on **`gemini-4-hydrogen-high`** (`0` Argon quota waste).
2. `hydrogen-argon-task` (`--default hydrogen-argon-hybrid --scope task`): Same Complexity-Adaptive `Hydrogen + Argon Low` Hybrid scoped to the current task only.
3. `hydrogen-dynamic-project` (`--default hydrogen-dynamic --scope project`): **100% Pure `Gemini 4 Hydrogen`** across the project (`medium` on `SIMPLE`, capped at `high` across `COMPLEX` logic/security and `CRITICAL` `T5` — matching `xhigh`'s `54%` `Terminal-Bench 4.0` score without `2.76x` token verbosity) — ideal for Free/Plus accounts or zero-Frontier-quota weeks.
4. `hydrogen-risk-project` (`--default hydrogen-risk-hybrid --scope project`): Risk-Adaptive Hydrogen + Chat Hybrid across the project (`gemini-4-hydrogen-medium` on `NORMAL` `T1–T3` reviews; main chat model `Inherit` automatically on `DEEP`/`MAX` `T4/T5` reviews).
5. `inherit-task` (`--default inherit --scope task`): Current chat model (`Inherit`) for all reviewers on the current task.

> **Rollout Fallback (`flash-argon-project` / `flash-project`)**: Existing `flash-argon-hybrid` (`flash-argon-project`, `flash-argon-task`) and `flash-dynamic` (`flash-project`, `flash-dynamic-task`) presets remain 100% supported for accounts or regions awaiting `Gemini 4 Hydrogen` rollout, and all in-flight tasks with frozen `flash-argon-hybrid` SHA-256 digests continue seamlessly without migration errors.

The plan displays the current model setting and its source, and every router dispatch, wait, status, and completion output includes `reviewer_models` and formats each specialist as `<role> [<model>]` in both CLI output and chat updates. Approving the plan
does not answer the model question. Keep an unanswered question pending when the
developer sends an unrelated message. Newly prepared Antigravity runs require a
recorded choice before dispatch; existing frozen runs retain their recorded policy.

You can also pass `--choice <id>` directly:

```bash
python .agents/harness.py review models set --host antigravity --choice hydrogen-argon-project --source conversation --proof-reference "Developer chose hydrogen-argon-project"
```

Or configure per-reviewer overrides and thinking levels (`low`, `medium`, `high`, `xhigh`/`extra`) explicitly:

```bash
python .agents/harness.py review models set --host antigravity --task-id <id> --default hydrogen@medium --reviewer security-perf-reviewer-agent=argon@low --scope task --source conversation --proof-reference "Use Hydrogen Medium by default and Argon Low for security"
```

## Claude Code configuration

During Claude-only setup, choose a common alias or `custom` for a complete policy:

```json
{"schema_version":1,"default":"sonnet","overrides":{"security-perf-reviewer-agent":"opus"}}
```

After setup, inspect support and record a developer-requested project choice:

```bash
python .agents/harness.py review models show --host claude
python .agents/harness.py review models set --host claude --default sonnet --reviewer security-perf-reviewer-agent=opus --source conversation --proof-reference "Use Sonnet for reviewers and Opus for security"
```

Precedence: run-scoped decision (`--scope run`, bound to current `run_id`), task decision (`--scope task`), project decision, setup answer, inheritance.

## Interrupted updates and concurrent tasks

A model change refreshes an undispatched phase or final run, its package and all
briefs under the repository state lock. It preserves the run identity, review
budget, checkpoint and reviewer roster. Phase paths come from the phase-review
owner. A durable `review-model-update.json` marker blocks dispatch if publication
is interrupted. Repeat the same authorized command to complete it; do not edit
state or reset counters. Repeating an already applied choice after dispatch
returns the existing decision without rewriting evidence.

Only selected reviewer files are synchronized. Another task cannot overwrite a
reviewer's native model while its launch is pending execution binding. Once the
host has identified the execution, later configuration changes cannot alter its
recorded model proof. CLI output uses UTF-8, including under Windows legacy
codepages; advisory next-step output does not change a completed command's exit code.

## Model proof and reviewer lifecycle

`requested_model` is the developer's policy; `resolved_model` and frontmatter are
configuration. They are not an observed model. For explicit Antigravity selection,
the harness reads the execution's native database in read-only mode, recording
`host_configured_model`, `host_reported_models`, `actual_model` and a metadata
digest (stripping optional `models/` prefixes and validating all four `Hydrogen`
thinking levels including `xhigh`/`extra` while rejecting cross-family quota leaks).
Missing or unsupported native metadata blocks explicit selection as
`REVIEW_MODEL_UNVERIFIED`. Legacy inheritance can remain honestly `UNOBSERVED`.
Reviewer prose cannot supply native model proof.
Review ingestion accepts an actual assistant reply; system briefs, example PASS
templates and tool output cannot become a reviewer verdict.

Reviewer executions are bound from canonical host messages matching the current
brief. Native cancellation routes to `REVIEWER_CANCELLED`, separate from launch
failure, tool rejection and a completed verdict. After an explicit developer
resume request, record it with:

```bash
python .agents/harness.py review resume --task-id <id> --phase-id <phase> --reviewer <role> --source conversation --proof-reference "Continue the cancelled reviewer"
```

Omit `--phase-id` for final review. Follow the routed `send_message` to the same
execution. This spends no extra call and grants no PASS. Finished native replies
route to the normal completion command for validation and ingestion.

## Carbon Primary + Hydrogen & Argon Utility/Reviewer Subagents (Google AI Ultra)

- **Primary Chat Model**: Select explicit **`Gemini 4 Carbon (Medium)`** (do **not** select Antigravity's built-in `Orchestrator` mode over the harness, because `Orchestrator` injects its own internal `Carbon <-> Hydrogen` planning/handoff loop that collides with deterministic `PreToolUse` gates).
- **Separate Quota Pool Rotation**: Switch the main Antigravity chat selector to `Claude Sonnet 5.5 (Thinking)` or `Claude Opus 5.5 (Thinking)` when `/usage` shows the Gemini weekly bar near `50%`. `.agents/agents/harness-scout-agent/agent.md` stays pinned to `gemini-4-hydrogen-medium` on every task, while `.agents/agents/harness-worker-agent/agent.md` runs on `gemini-4-hydrogen-medium` on `SIMPLE` tasks and automatically steps up to `gemini-4-hydrogen-high` on `COMPLEX` `FULL_SLICE` tasks (`0` `Argon` / `Carbon` worker quota burn!).
- **Risk-Gated Delegation**: Inspect `python .agents/harness.py delegate-plan --json` to verify whether the current task slice uses `DELEGATE_WORKER_SLICE`, `CAPTURE_RED_ONLY`, `TESTS_AND_GATES_ONLY`, or `TRIVIAL_INLINE_LEAD`.
