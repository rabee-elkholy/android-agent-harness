# Zoho Sprints MCP

Stdio MCP server. Same tools and mutate rules as the original engine (`update zoho`, Arabic templates, `In progress` / `Ready To ReTest`). Playbook: `../../workflows/zoho-sprints.md`.

The kit ships **code + empty workflow defaults**, not tokens.

Credentials stay on the developer's machine:

1. Copy `config.example.json` to `~/.android-harness/zoho_sprints.json`
2. Fill `client_id`, `client_secret`, `refresh_token`, `team_id`, `project_id`
3. Never put that file in the app repo or in this kit

To get Zoho API credentials:

1. Go to https://api-console.zoho.com/ and create a **Self Client**
2. Generate a grant token with scope: `ZohoSprints.sprints.ALL,ZohoSprints.items.ALL,ZohoSprints.team.READ`
3. Exchange the grant token for a refresh token using the Zoho OAuth endpoint
4. Find your `team_id` and `project_id` from your Zoho Sprints URL: `https://sprints.zoho.com/team/<team_id>/project/<project_id>/...`

`workflow_defaults.json` has assignee / item-prefix / title-strip settings. Empty values are resolved at runtime by the server. Fill them during install (I.16) or configure later.

Setup (`I.16`) wires `.agents/mcp_config.json` (and Cursor `.cursor/mcp.json` when Cursor was selected) to this `server.py` and sets `ZOHO_SPRINTS_CONFIG` to an **existing** user file if one is already on the PC. It does not copy tokens.

If a config already exists at `~/.gemini/antigravity/scratch/zoho_sprints/zoho_config.json`, setup points at that path and leaves the file untouched.

Zoho Desk is not included.
