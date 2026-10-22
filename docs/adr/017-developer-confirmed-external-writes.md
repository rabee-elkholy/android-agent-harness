# ADR-017: Developer-confirmed external writes

## Context

In a client app the developer asked the agent to upload an RTL formatting file to
Google Drive. The hook refused it with "command is not allowed while plan status
is AWAITING_DEVELOPER_APPROVAL": every external write was tied to the Android
code plan. An upload the developer asked for has nothing to do with that plan, so
the refusal protected nothing and blocked the request. The Google Workspace skills
(`gdrive`, `gdocs`, `gsheets`, `gslides`, `gcalendar`) are shell CLIs with
`readonly` and `mutate` namespaces, not MCP tools.

## Decision

External writes are confirmed by the developer through the host's own permission
prompt. They no longer depend on the code plan's state
(`integrations/external_write_policy.py`):

- reads (`readonly`, MCP `get_/list_/search_`) are allowed;
- ordinary writes (upload, create, rename, comment, local download/export
  destinations, CLI login) return `ask`;
- high-impact writes (delete, trash, share, permission changes, moves, publish,
  send, clear, opaque batch operations, unknown mutate subcommands, and
  unclassifiable MCP tools) return `force_ask`, which prompts on every call;
- writes whose arguments name a credential or signing file (`.env*`, keystores,
  `local.properties`, `key.properties`, `google-services.json`, private keys,
  service-account JSON) are denied;
- a Workspace CLI call is recognized only as a single command with no chaining,
  pipes, redirection or substitution;
- unknown shell network tools (curl, rclone, scp) are not recognized and stay
  denied by the command guard;
- an approved plan scope (`--external-write mcp:<server>[:high-impact]`) still
  authorizes the matching MCP call silently;
- Zoho keeps its `update zoho` grant and operation-id rules.

## Host capability

Antigravity accepts `ask` and `force_ask` natively. The Claude Code bridge maps
both to Claude's `ask`. The Copilot bridge maps them to `deny`, because it only
supports allow/deny. A bridge may never turn a prompt into a silent allow.
Unknown engine decisions are denied.

## Compatibility

Calls that were previously allowed are still allowed. Calls that were previously
denied only because no plan covered them now raise a prompt instead. The audit
log records the same reason codes (`EXTERNAL_WRITE_SCOPE_REQUIRED`,
`PLAN_NOT_APPROVED`, `UNKNOWN_MCP_TOOL`) together with the new decision.
