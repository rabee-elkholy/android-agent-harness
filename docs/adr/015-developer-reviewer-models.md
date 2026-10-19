# ADR-015: Developer-owned native reviewer model choices

Status: Accepted (explicit maintainer approval)

The previous blanket inheritance contract prevented a developer from choosing
different supported reviewer models. Preserve inheritance for existing installs,
but accept a project policy, a task-local replacement (`--scope task`), and a
single-run choice (`--scope run`). The policy has one default and optional
canonical-role overrides; it never selects reviewers.

Freeze resolved selections in phase and final review packages. When a developer
selects a reviewer model right before the first dispatch of an undispatched run,
the harness refreshes the undispatched run metadata and briefs and syncs
`.agents/agents/<role>/agent.md` frontmatter before any reviewer is launched.

Claude Code documents `inherit`, `sonnet`, `opus`, and `haiku` in its
[native subagent model contract](https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields).
Antigravity `invoke_subagent` tool arguments stay strictly limited to
`Prompt`, `Role`, `TypeName`, and `Workspace` (`INHERIT_PARENT_BY_OMISSION` on tool args);
instead, Antigravity custom reviewer agents resolve their model from the `model:`
field in `.agents/agents/<role>/agent.md` YAML frontmatter, supporting `inherit`,
`flash-dynamic` (dynamic `medium`/`high` thinking level by reviewer criticality),
`hybrid-smart` (Flash Dynamic for standard reviewers + Chat model `Inherit` for
critical specialists), and explicit `gemini-3.8-flash-*` / `gemini-3.8-pro-*` slugs.

The recovery contract publishes model changes under the repository state lock,
with a durable incomplete-update marker checked before dispatch. Refresh the
undispatched package and briefs together using the phase owner's canonical paths.
Preserve the run identity and all spent budgets. Dispatched evidence is immutable;
an identical repeated decision is idempotent. Shared native agent settings cannot
change during an unbound launch from another task.

Frontmatter is configuration, not actual-model evidence. Explicit Antigravity
choices require the matching native executor model and observed generation model
family from that execution's read-only database. Unknown native schemas fail
closed for explicit choices. Existing inheritance remains unobserved when the
host cannot report metadata. Native user cancellation requires a recorded
developer resume decision for the same execution; it never authorizes a new call.
