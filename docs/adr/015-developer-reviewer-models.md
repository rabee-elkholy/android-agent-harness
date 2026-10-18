# ADR-015: Developer-owned native reviewer model choices

Status: Accepted (explicit maintainer approval)

The previous blanket inheritance contract prevented a developer from choosing
different supported reviewer models. Preserve inheritance for existing installs,
but accept a project policy and complete task-local replacement. The policy has
one default and optional canonical-role overrides; it never selects reviewers.
Setup choices apply unless an explicit project decision exists; task decisions
take precedence. Changes require a developer source and proof reference.

Freeze resolved selections in phase and final review packages. Existing runs,
receipts, findings, budgets and historical evidence do not change with config.
Unsupported native controls fail before a review run is published. Never retry
with inheritance after an explicit native selection fails.

Claude Code documents `inherit`, `sonnet`, `opus`, and `haiku` in its
[native subagent model contract](https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields).
The execution profile supplies `model` only for explicit Claude selection.
This is a documented alias catalog, not a probe of account entitlements or a
cross-provider runner. Antigravity's current invoke_subagent schema lacks model
controls and stays inherit-only. Other adapters also stay inherit-only.

Requested models and host-reported model IDs are distinct. Only the unchanged
native Claude transcript supplies observed IDs; response-body claims are ignored.
An explicit selection requires matching family metadata. Transcript location and
hash checks do not prove independent Claude execution, which remains unverified.
All existing stronger proof requirements and developer override limits remain.
