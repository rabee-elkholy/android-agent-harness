# Jira via Upstream MCP Server — Registration Playbook

Jira integration is **configuration, not code**: the harness ships no Jira
client. Register Atlassian's official upstream MCP server, keep credentials in
the user-level config exactly like Zoho Sprints (rules section 5), and reuse
the same QA-centric handoff policy.

## 1. Prerequisites

- An Atlassian cloud site with API access.
- The official Atlassian Remote MCP Server endpoint for your site
  (`https://api.atlassian.com/mcp` style URL from Atlassian's docs), or a
  self-hosted Jira MCP gateway approved by your organization.
- Never paste tokens into this repository. User-level files only:
  `~/.android-harness/jira.json` (same pattern as
  `~/.android-harness/zoho_sprints.json`).

## 2. Register the server

Merge into `.agents/mcp_config.json` (project level) or your client's global
MCP settings. Example shape:

```json
{
  "mcpServers": {
    "jira": {
      "command": "npx",
      "args": ["-y", "@atlassian/mcp-bridge"],
      "env": { "JIRA_CONFIG": "~/.android-harness/jira.json" }
    }
  }
}
```

Follow the current official Atlassian MCP documentation for the exact command,
arguments, and OAuth flow; they evolve independently of this kit. The invariant
is: **credentials referenced by path or host auth flow, never inline values.**

## 3. Status map enforced by the kit policy engine

Kit canonical status is set by `agents/scripts/pm_policy.py`. Jira labels:

| Kit canonical | Jira label | Notes |
|---|---|---|
| `in_progress` | `In Progress` | Set when work starts |
| `ready_to_retest` | `Ready for Testing` | Set after all device phases Pass |

Denied Jira statuses (never set, never declared in a handoff): `Done`,
`Resolved`, `Closed`.

## 4. Mutation trigger phrase

Mutations happen only on the explicit chat phrase **`update jira`** (the
provider-generic form of the historical `update zoho`). Ingest stays read-only.

## 5. Handoff contract

Identical to rules section 5 and `.agents/workflows/zoho-sprints.md`:

- First line MUST be `Commit: <hash>`.
- Mandatory sections: Root Cause/Objective, Solution/What Changed,
  Impact Area (Blast Radius), Test Cases & Verification Steps
  (language per `_product.py ZOHO_LANGUAGE`).
- QA-centric tone: no code internals, no emoji.
- Validate offline before posting: `validate_handoff(text, lang_mode, "jira")`
  from `agents/scripts/pm_policy.py`.

## 6. Credential isolation checklist

- Secrets live only in `~/.android-harness/jira.json`.
- `harness_doctor.py` Dimension 11 fails if any `<provider>.json` secret file
  appears inside the repository.
- If MCP tools are unavailable in a session, do not invent ticket fields; ask
  the developer to paste the ticket (same rule as Zoho).
