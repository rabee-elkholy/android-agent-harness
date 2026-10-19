# Reviewer model configuration

Inheritance is the default and existing installations need no migration.
Model choices do not alter the policy-selected reviewer roster, risk, budgets,
or the requirement for independent review proof.

| Host | Supported choices | Enforcement |
|---|---|---|
| Claude Code | `inherit`, `sonnet`, `opus`, `haiku` | Rule-enforced native Agent/Task model argument; account access is host-dependent |
| Antigravity | `inherit`, `flash-dynamic`, `hybrid-smart`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-high`, `gemini-3.8-pro-medium`, `gemini-3.8-pro-high` (or `<model>@<low|medium|high>`) | Synced into `.agents/agents/<role>/agent.md` YAML frontmatter (`model:`); `invoke_subagent` never sends `model`/`Model` |
| Other adapters | `inherit` | Host-managed; inheritance is not independently verified |

## Antigravity pre-review interactive choices (`SELECT_REVIEW_MODEL`)

When a task or phase review on Antigravity reaches `DISPATCH_REVIEWERS` / `DISPATCH_PHASE_REVIEWERS` with no explicit model bound (`source == "default"`), the router emits `before_first_dispatch` (`code = "SELECT_REVIEW_MODEL"`) with 5 developer choices:

1. `flash-dynamic-task` (`--default flash-dynamic --scope task`): Gemini 3.8 Flash with dynamic thinking (`high` for `security-reviewer-agent`, `bug-reviewer-agent`, `perf-anr-guardian-agent`, or `DEEP`/`MAX` effort; `medium` for standard reviewers) for the whole task.
2. `flash-dynamic-once` (`--default flash-dynamic --scope run`): Gemini 3.8 Flash with dynamic thinking for this review run only (`review-models-run.json`).
3. `inherit-task` (`--default inherit --scope task`): Chat conversation model (`Inherit`) for the whole task.
4. `inherit-once` (`--default inherit --scope run`): Chat conversation model (`Inherit`) for this review run only.
5. `hybrid-smart-task` (`--default hybrid-smart --scope task`): Smart Hybrid — Flash Dynamic for standard reviewers (`convention`, `test-quality`, `spec-compliance`, `regression-impact`) and Chat model (`Inherit`) for critical reviewers (`bug`, `perf-anr-guardian`, `security`) for the whole task.

The plan displays the current model setting and its source. Approving the plan
does not answer the model question. Keep an unanswered question pending when the
developer sends an unrelated message. Newly prepared Antigravity runs require a
recorded choice before dispatch; existing frozen runs retain their recorded policy.

You can also pass `--choice <id>` directly:

```bash
python .agents/harness.py review models set --host antigravity --task-id <id> --choice hybrid-smart-task --source conversation --proof-reference "Developer chose hybrid-smart-task"
```

Or configure per-reviewer overrides and thinking levels explicitly:

```bash
python .agents/harness.py review models set --host antigravity --task-id <id> --default flash@medium --reviewer security-reviewer-agent=pro@high --scope task --source conversation --proof-reference "Use Flash Medium by default and Pro High for security"
```

## Claude Code configuration

During Claude-only setup, choose a common alias or `custom` for a complete policy:

```json
{"schema_version":1,"default":"sonnet","overrides":{"security-reviewer-agent":"opus"}}
```

After setup, inspect support and record a developer-requested project choice:

```bash
python .agents/harness.py review models show --host claude
python .agents/harness.py review models set --host claude --default sonnet --reviewer security-reviewer-agent=opus --source conversation --proof-reference "Use Sonnet for reviewers and Opus for security"
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

Reviewer `run_command` is restricted by the native hook to bounded `graph` and
`task-context` queries. It permits no shell chaining, builds, tests, lifecycle
commands, application writes or reviewer orchestration. Discovery expansion
changes read scope only; it never expands approved implementation scope.
