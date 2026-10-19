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
