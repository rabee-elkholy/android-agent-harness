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
