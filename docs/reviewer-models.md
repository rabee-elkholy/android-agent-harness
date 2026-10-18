# Reviewer model configuration

Inheritance is the default and existing installations need no migration.
Model choices do not alter the policy-selected reviewer roster, risk, budgets,
or the requirement for independent review proof.

| Host | Supported choices | Enforcement |
|---|---|---|
| Claude Code | `inherit`, `sonnet`, `opus`, `haiku` | Rule-enforced native Agent/Task model argument; account access is host-dependent |
| Antigravity | `inherit` | Omit `model` and `Model`; current native schema has no override |
| Other adapters | `inherit` | Host-managed; inheritance is not independently verified |

These are documented native aliases, not a live account model inventory. An
unavailable model must stop the review; the lead must never silently substitute
another model. External providers, arbitrary IDs and API keys are not supported.

During Claude-only setup, choose a common alias or `custom` for a complete policy:

```json
{"schema_version":1,"default":"sonnet","overrides":{"security-reviewer-agent":"opus"}}
```

After setup, inspect support and record a developer-requested project choice:

```bash
python .agents/harness.py review models show --host claude
python .agents/harness.py review models set --host claude --default sonnet --reviewer security-reviewer-agent=opus --source conversation --proof-reference "Use Sonnet for reviewers and Opus for security"
```

Add `--task-id <id>` for a task-local replacement before final verification.
Each `set` replaces the complete policy: omitted overrides are cleared. Reset to
inheritance with `--default inherit` and no `--reviewer`. Sources are
`conversation` (the developer's explicit instruction) or `developer_terminal`.
Agents must not invent permission, edit state/config files, or select models
from environment variables. The global `android-harness review models` command
uses the same implementation (add `--repo <project>`).

Precedence: task decision, project decision, setup answer, inheritance.
Project and task decisions are stored in harness state, outside managed release
files. Every new phase/final run freezes its resolved selections in its package.
Changing the project default affects future runs only. To change a final run,
resume implementation and prepare a new run through the normal lifecycle; no
previous evidence is rewritten and previous reviewer calls remain spent.

The router's execution profile is authoritative for dispatch. On Claude, pass
each role's `native_arguments` to its native Agent/Task call and use its exact
brief. On inheritance, omit the model argument. Do not use the lead model name
as a substitute for inheritance. Launching a reviewer needs no extra approval.

Ingest the unchanged Claude transcript using the existing final/phase review
commands. Explicit model choices require native assistant-message model metadata
matching the requested family; missing or different metadata blocks ingestion.
The evidence records requested and host-reported models separately. A reviewer's
own statement about its model is ignored. Claude transcript metadata remains
unverified host-reported evidence and does not upgrade independent execution
proof or bypass sensitive-change restrictions.
