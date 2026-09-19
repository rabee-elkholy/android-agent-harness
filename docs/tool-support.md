# Tool support

The harness has one engine and thin host adapters. The canonical rules are
`.agents/rules/harness-rules.md`; adaptive decisions come only from
`.agents/scripts/review_policy.py`.

## Capability matrix

| Host | Installed entry points | Effective enforcement |
|---|---|---|
| Claude Code | `CLAUDE.md`, commands, named agents, `PreToolUse` bridge | Mutation hook where supported; conversational approval remains `RULE_ENFORCED` |
| GitHub Copilot | instructions, prompts, optional `preToolUse` bridge | Mutation hook where supported; conversational approval remains `RULE_ENFORCED` |
| Google Antigravity/Gemini | `GEMINI.md`, harness hook config | Host hook when the advertised protocol is available; otherwise rules |
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

The final change classification selects the smallest valid reviewer set.
Eligible documentation/localization/resource micro changes use
`REVIEW_NOT_REQUIRED_BY_POLICY`. Normal business logic, UI, coroutine,
network, persistence, native, and build changes select their relevant roles.
Room schema changes use the focused `DATA` lane (Room gate, tests, correctness,
and regression review) rather than automatically selecting all five roles.
Critical security, billing, authentication, cryptography, or sensitive-data
changes select all five specialist roles. Test changes add Test Quality.

If a host cannot launch named children, run each reviewer prompt selected in
the immutable policy against the same review package and ingest the structured
reports. Missing, extra, malformed, stale, or truncated coverage cannot pass.
The maximum is three rounds per candidate delivery.

## Changing setup answers

Edit or regenerate `.harness-setup/answers.json`, then run a compatible update.
The updater refuses modified managed engine files, preserves documented
project-tailored references and Zoho defaults, stages the replacement, and
rolls back on failure. A pre-v1 installation must be uninstalled and installed
cleanly; it is never migrated in place.

Pinned operator prompts are in `docs/install-or-update-prompt.md`,
`docs/diagnostic-prompt.md`, and `docs/rollback-prompt.md`.
