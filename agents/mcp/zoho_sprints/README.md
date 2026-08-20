# Zoho Sprints MCP

Stdio MCP server. Same tools and mutate rules as the original engine (`update zoho`, Arabic templates, `In progress` / `Ready To ReTest`). Playbook: `../../workflows/zoho-sprints.md`.

The kit ships **code + workflow defaults**, not tokens.

Credentials stay on the developer’s machine:

1. Copy `config.example.json` to `~/.android-harness/zoho_sprints.json`
2. Fill `client_id`, `client_secret`, `refresh_token`, `team_id`, `project_id`
3. Never put that file in the app repo or in this kit

`workflow_defaults.json` is assignee / item-prefix / title-strip only. User config overrides those keys. Tokens are never read from it.

Setup (`I.16`) wires `.agents/mcp_config.json` (and Cursor `.cursor/mcp.json` when Cursor was selected) to this `server.py` and sets `ZOHO_SPRINTS_CONFIG` to an **existing** user file if one is already on the PC. It does not copy tokens.

If a config already exists at `~/.gemini/antigravity/scratch/zoho_sprints/zoho_config.json`, setup points at that path and leaves the file untouched.

Zoho Desk is not included.
