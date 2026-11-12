# Reviewer model configuration

Inheritance is the default and existing installations need no migration.
Model choices do not alter the policy-selected reviewer roster, risk, budgets,
or the requirement for independent review proof.

| Host | Supported choices | Enforcement |
|---|---|---|
| **Google Antigravity** (Primary Runtime) | `inherit`, `flash-argon-hybrid`, `risk-hybrid`, `flash-dynamic`, `argon-dynamic`, `hybrid-smart`, `gemini-3.8-flash-fast`, `gemini-3.8-flash-low`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-high`, `gemini-4-argon-low`, `gemini-4-argon-medium`, `gemini-4-argon-high`, `carbon-dynamic`, `gemini-4-carbon-low`, `gemini-4-carbon-medium`, `gemini-4-carbon-high`, `gemini-3.1-pro-low`, `gemini-3.1-pro-high` (or `<model>@<fast\|low\|medium\|high\|hybrid>`) | Synced into `.agents/agents/<role>/agent.md` YAML frontmatter (`model:`); `invoke_subagent` passes `Model="flash"` for Flash reviewers and omits `Model` for `argon`/`carbon`/`inherit`; native SQLite metadata verified |
| Legacy / Compatibility Adapters (Claude Code, etc.) | `inherit` (`sonnet`, `opus`, `haiku` on Claude Code) | Host-managed or rule-enforced native Agent/Task model argument |

## Antigravity pre-review interactive choices (`SELECT_REVIEW_MODEL`)

When a task or phase review on Antigravity reaches `DISPATCH_REVIEWERS` / `DISPATCH_PHASE_REVIEWERS` with no explicit model bound (`source == "default"`), the router emits `before_first_dispatch` (`code = "SELECT_REVIEW_MODEL"`) with 5 streamlined developer choices (while keeping `-once`, `risk-hybrid-task`, and `hybrid-smart` aliases available via `--choice`):

1. `flash-argon-project` (`--default flash-argon-hybrid --scope project` / `--preset flash-argon-hybrid`): **Complexity-Adaptive `Flash + Argon Low` Hybrid for Entire Project (Recommended #1)** — persists across the repository so future tasks never re-prompt, adapting subagent models deterministically to each task's real complexity:
   - **Band 0 (`TRIVIAL` — `T0` / micro strings / docs)**: `0` subagents (inline Lead edit + deterministic preflight).
   - **Band 1 (`SIMPLE` — single-module `T1–T2` UI/ViewModel/Resource feature, `<= 3` non-test files, `<= 90` lines)**: **100% Pure Flash (`gemini-3.8-flash-medium`)** across `Scout`, `Worker`, and **all** routed reviewers (`0` `Gemini 4` quota used).
   - **Band 2 (`COMPLEX` — `BUG` root-cause tasks, multi-module `>= 2`, multi-phase `>= 2`, `>= 4` non-test files or `> 90` lines, `T3/T4`, or `COROUTINES` / `NETWORK` / `ROOM_SCHEMA` / `PUBLIC_API` / `DEVICE_API` / `Round 2`)**: **Precision `Argon Low + Flash` Split** — upgrades `harness-worker-agent` (`FULL_SLICE`), `bug-test-reviewer-agent`, `security-perf-reviewer-agent`, and any `DEEP`-effort specialist to **`gemini-4-argon-low`**, while keeping `harness-scout-agent` and `NORMAL` structural reviewers (`arch-regression-reviewer-agent`) on **`gemini-3.8-flash-medium`**.
   - **Band 3 (`CRITICAL` — `T5` `AUTH` / `BILLING` / `CRYPTO` / `SECURITY` / `SENSITIVE_DATA`, `CRITICAL` severity, or `Round 3+`)**: Lead Architect writes core production files directly (`Worker` runs `TESTS_AND_GATES_ONLY` on `gemini-3.8-flash-medium`), capping all routed specialists strictly at **`gemini-4-argon-low`** (`thinking_level="low"` — never escalating to `argon-medium` or `high`).
2. `flash-argon-task` (`--default flash-argon-hybrid --scope task`): Same Complexity-Adaptive `Flash + Argon Low` Hybrid scoped to the current task only.
3. `risk-hybrid-project` (`--default risk-hybrid --scope project`): Risk-Adaptive Chat Hybrid across the project (`gemini-3.8-flash-medium` on `NORMAL` `T1–T3` reviews; main chat model `Inherit` on `DEEP`/`MAX` `T4/T5` reviews).
4. `flash-dynamic-task` (`--default flash-dynamic --scope task`): Pure Gemini 3.8 Flash (`medium` for `NORMAL` effort; `high` on `DEEP`/`MAX` effort) for the current task.
5. `inherit-task` (`--default inherit --scope task`): Current chat model (`Inherit`) for all reviewers on the current task.

The plan displays the current model setting and its source, and every router dispatch, wait, status, and completion output includes `reviewer_models` and formats each specialist as `<role> [<model>]` in both CLI output and chat updates. Approving the plan
does not answer the model question. Keep an unanswered question pending when the
developer sends an unrelated message. Newly prepared Antigravity runs require a
recorded choice before dispatch; existing frozen runs retain their recorded policy.

You can also pass `--choice <id>` directly:

```bash
python .agents/harness.py review models set --host antigravity --task-id <id> --choice hybrid-smart-task --source conversation --proof-reference "Developer chose hybrid-smart-task"
```

Or configure per-reviewer overrides and thinking levels explicitly:

```bash
python .agents/harness.py review models set --host antigravity --task-id <id> --default flash@medium --reviewer security-perf-reviewer-agent=pro@high --scope task --source conversation --proof-reference "Use Flash Medium by default and Pro High for security"
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
digest. Runtime IDs may omit thinking levels: the native executor field must
match the selected thinking slug and all observed runtime IDs must match its
model family. Missing or unsupported native metadata blocks explicit selection
as `REVIEW_MODEL_UNVERIFIED`. Legacy inheritance can remain honestly `UNOBSERVED`.
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
If the host rejects the resume message, `REVIEWER_RESUME_ENV_BLOCKED` preserves the
error. After resolving it, repeating the same authorized resume command recovers
the same execution without another reviewer call.

Generated Antigravity reviewer frontmatter (`.agents/agents/<role>/agent.md`) restricts
tools to pure fast file/search reads (`view_file`, `grep_search`, `find_by_name`) and
inlines compact canonical review packages (`<= 24 KB`) directly inside each reviewer brief
with pre-verified deterministic gate summaries (`preflight`, `unit_tests`, `localization`, `room`).
As defense-in-depth, if a host ever dispatches `run_command` from a bound reviewer session,
the native hook restricts it to bounded read-only `graph` and `task-context` queries.

## Hybrid Lead + Flash Utility Subagents & Quota Rotation (Google AI Ultra)

- **Primary Chat Model**: `Gemini 4 Carbon (Medium)` (sweet-spot accuracy & lowest hallucination rate; avoid `Low` on multi-step engineering).
- **Separate Quota Pool Rotation**: Switch the main Antigravity chat selector to `Claude Sonnet 5.5 (Thinking)` or `Claude Opus 5.5 (Thinking)` when `/usage` shows the Gemini weekly bar near `50%`. `.agents/agents/harness-scout-agent/agent.md` stays pinned to `gemini-3.8-flash-medium` on every task, while `.agents/agents/harness-worker-agent/agent.md` runs on `gemini-3.8-flash-medium` by default and automatically steps up to `gemini-4-argon-low` on `COMPLEX` `FULL_SLICE` tasks when `flash-argon-hybrid` is active.
- **Risk-Gated Delegation**: Inspect `python .agents/harness.py delegate-plan --json` to verify whether the current task slice uses `DELEGATE_WORKER_SLICE`, `CAPTURE_RED_ONLY`, `TESTS_AND_GATES_ONLY`, or `TRIVIAL_INLINE_LEAD`.
