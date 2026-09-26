# Tool support

The harness has one engine and thin host adapters. The canonical rules are
`.agents/rules/harness-rules.md`; adaptive decisions come only from
`.agents/scripts/review_policy.py`.

## Capability matrix

| Host | Installed entry points | Effective enforcement |
|---|---|---|
| **Google Antigravity** | `GEMINI.md`, `agents/hooks.json`, `.agents/agents/` | `HARD_ENFORCED`: Primary production host; native hooks intercept tool write mutations (`write_to_file`, `replace_file_content`, `multi_replace_file_content`) and invoke_subagent pre/post calls; Review Protocol V2 with 7 custom reviewer subagents |
| Claude Code | `CLAUDE.md`, `.claude/settings.json`, commands, named agents, `PreToolUse` bridge | `HARD_ENFORCED` for covered mutations where the installed hook runs; conversational approval remains `RULE_ENFORCED` |
| GitHub Copilot | instructions, prompts, optional `preToolUse` bridge | `RULE_ENFORCED`: Rule guidance + downstream verification gate |
| Gemini CLI | `GEMINI.md` | `RULE_ENFORCED`: Downstream verification gate (legacy compatibility path) |
| Codex | `AGENTS.md`, `CODEX.md`, prompt commands | `RULE_ENFORCED` |
| Cursor | always-on `.mdc` rule and MCP path-only merge | `RULE_ENFORCED` |
| Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, Goose, Qwen | Host-specific rule pointer | `RULE_ENFORCED` |
| Other `AGENTS.md` readers | `AGENTS.md` | Prompt/rule enforcement only |

`HARD_ENFORCED` describes only mutation classes actually intercepted by a
host-native hook. It never means an OS sandbox or cryptographic proof of who
typed an approval. Doctor reports approval trust and mutation interception
separately.

## Generated files

Setup writes adapters only for selected tools and records every managed path in
`.harness-setup/ownership-v1.json`. It does not overwrite unrelated host
configuration. Existing managed files are backed up; uninstall previews its
exact targets and restores pre-install content when applied.

Zoho setup may merge the `zoho-sprints` command and user-config path into the
project's supported MCP files. Tokens stay in the user profile and are never
copied to the repository or review evidence.

## Commands

```bash
python harness_cli.py init --repo /path/to/project
python harness_cli.py setup --repo /path/to/project
python harness_cli.py task draft --repo /path/to/project --task-id feature-1 --outcome "..." --expected-surfaces BUSINESS_LOGIC --expected-modules :app
python harness_cli.py task approve --repo /path/to/project --task-id feature-1 --source conversation --proof-reference <host-message-id> --enforcement-tier RULE_ENFORCED
python harness_cli.py task begin --repo /path/to/project --task-id feature-1
python harness_cli.py doctor --repo /path/to/project --json
python harness_cli.py task-context --repo /path/to/project --file app/src/main/kotlin/com/example/ProfileScreen.kt --json
python harness_cli.py task-context --repo /path/to/project --symbol ProfileViewModel --module :feature:profile --source-set main --json
python harness_cli.py context refresh --repo /path/to/project
python harness_cli.py context preview --repo /path/to/project --json
python harness_cli.py context preview --repo /path/to/project --json --full
python harness_cli.py task status --repo /path/to/project --task-id feature-1 --next
python harness_cli.py repair --repo /path/to/project --kit /path/to/pinned/kit
python harness_cli.py update --repo /path/to/project
python harness_cli.py uninstall --repo /path/to/project
python harness_cli.py uninstall --repo /path/to/project --apply
```

`task-context` is a trusted read-only inspection command. It performs a live,
bounded resolution without writing the persistent graph cache or project
context. Only a target that independently resolves or is genuinely ambiguous
can satisfy the initial discovery anchor; missing and invalid targets do not
unlock broad repository search.

For an approved plan that includes tracker mutation, add
`--external-write zoho_sprints` while drafting. Every Zoho write also requires
a stable `operation_id`; terminal states such as Done remain developer-owned.

## Review behavior

The final change classification selects the smallest valid reviewer set from the adaptive 6-tier risk policy. Eligible micro-changes use `REVIEW_NOT_REQUIRED_BY_POLICY`. Normal business logic, UI, coroutine, network, persistence, and build changes select their relevant specialist roles. Critical security, billing, authentication, cryptography, or sensitive-data changes select all applicable specialist roles.

On **Google Antigravity**:
- Seven custom reviewer subagents are provisioned under `.agents/agents/<reviewer>/agent.md`.
- Routed reviewers execute concurrently in parallel via `invoke_subagent`.
- Reviewer subagents inherit the parent agent's model by omission (no model override).
- Review Protocol V2 enforces structured JSON output (`HARNESS_REVIEW_RESULT_V2`). Clean reviews report `findings: []` and `verdict: "PASS"`.
- Initial malformed replies receive an exact `send_message` protocol retry within the same subagent execution without launching a new dispatch.
- Review results are ingested from trusted conversation transcripts via `review complete` and aggregated via `review finalize`.
- Total reviewer calls are bounded by the **Reviewer Call Safety Cap** (recommended: 20). Maximum 3 review rounds per delivery.

On **Claude Code, Codex, and other hosts without a trusted transcript adapter**, the final run freezes Review Protocol V1. Pass the active host to `task status --next --host <host>` and `prepare-verification --host <host>`. On Claude Code, record each reviewer's reply from its subagent transcript with `record_review.py --from-subagent <role>=<transcript-path>` (the transcript path or agent id Claude Code reported); other hosts record the unchanged final reviewer response with `record_review.py --response <role>=<path>`. The evidence identifies independent execution as unverified. For scoped phase reviews, build the package with `phase-review package --host <host>`, launch the exact roster with the generated briefs, then run `phase-review dispatch --host <host> --reviewer <role>` once for each launched reviewer in the same command. Ingest unchanged responses with `phase-review complete --host <host> --response-file <path>`; on Claude Code `<path>` is the reviewer's subagent transcript. These hosts retain deterministic policy, immutable packages, gates, and the final verifier, but the receipt is host-reported rather than trusted execution proof.

Limits on these hosts, because the final verifier requires proven independent review execution for some changes:

| Change | What completes it on a V1 host |
|---|---|
| LOW or MEDIUM severity, no sensitive surface | Recorded reviews are enough |
| HIGH or CRITICAL severity, no sensitive surface | After the reviews pass, the router returns `REVIEW_OVERRIDE_REQUIRED`: the developer runs `record_review.py --override-reviews --source developer_terminal --proof-reference "<reason>"` in their own terminal. The agent cannot run it; the hook denies it |
| AUTH, BILLING, SECURITY, SENSITIVE_DATA or CRYPTO surface | Not deliverable. The router returns `SENSITIVE_REVIEW_PROOF_UNAVAILABLE`: run the review on Antigravity, or cancel and split the sensitive part into its own task |

On every host, a component the task newly exports without a permission fails preflight with `EXPORTED_COMPONENT_WITHOUT_PERMISSION`. If public access is intended, the developer accepts it in their own terminal with `exported_component_guard.py --accept <android:name> --source developer_terminal --proof-reference "<reason>"`; the hook denies that command to the agent, and `tools:ignore` on the element does not waive the check.

## Changing setup answers

Edit or regenerate `.harness-setup/answers.json`, then run a compatible update.
The updater refuses modified managed engine files, preserves documented
project-tailored references and Zoho defaults, stages the replacement, and
rolls back on failure. A pre-v1 installation must be uninstalled and installed
cleanly; it is never migrated in place.

Pinned operator prompts are in `docs/install-or-update-prompt.md`,
`docs/diagnostic-prompt.md`, and `docs/rollback-prompt.md`.
