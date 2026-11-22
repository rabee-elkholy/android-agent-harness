---
trigger: model_decision
description: "Apply when syncing or mutating project management trackers (Zoho Sprints, Zoho Projects, Jira, Linear, GitHub, ClickUp, Asana, Trello) or saving/loading Smart Context Bridges (`task bridge`)."
---
<!-- managed-by: android-agent-harness -->

# External PM Trackers & Smart Context Bridge

Keep `.agents/rules/harness-rules.md` authoritative.

## 1. Universal PM MCP & Zoho Sprints Safety
- Discover configured PM MCP servers via `python .agents/harness.py pm discover --json`.
- **Zero-Pagination Item Lookup (`pm find-item`)**: When `ZohoSprints_GetItems` or any PM tool saves a large JSON dump to `.system_generated/steps/*/output.txt`, NEVER paginate `output.txt` via `read_file` `ByteOffset` (blocked by `LARGE_STEP_OUTPUT_PAGINATION_BLOCKED`). Extract matching items in `<20ms` via `python .agents/harness.py pm find-item --item <I1454|1454> --file "<output.txt>" --json`. On Zoho Sprints (`zoho-sprints_mcp`), check ALL active sprints (`sprintType == 2`) before Backlog, and filter by item number via `query_params={"itemsearchby": "{\"itemNo\":\"1454\"}"}` (NEVER `searchby="itemNo"`, which fails with Zoho error `7600`).
- Before any PM MCP mutation, preview the exact target item ID, fields, status, and comment to the developer and record explicit developer confirmation via `python .agents/harness.py pm authorize --source conversation --proof-reference "<developer confirmation>"` (add `--allow-close` only when closing a terminal state is explicitly confirmed).
- Original Bug/Issue descriptions are protected: never overwrite or blank them.
- Terminal tracker states (`Done`, `Closed`, `Solved`) are developer-owned and never set automatically without explicit `--allow-close` developer authorization.
- Generate 5-section QA reports with zero code-identifier leakage via `python .agents/harness.py pm prepare-report`. For `ZohoSprints_UpdateItem`, pass the returned whitespace-minified `zoho_query_param_html` (`<= 1,050` chars) in `query_params.description` so URL-encoded Arabic never triggers `HTTP 414 Request-URI Too Large` (`ZohoSprints_AddItemComment` sends `body.name` in the POST body without URI limits).
- For linked Zoho Sprints tasks, Zoho writes require explicit developer confirmation (`python .agents/harness.py pm authorize --source conversation --proof-reference "<developer confirmation>"`, or the legacy `zoho authorize` alias), `zoho start-sync --task-id <id>` after plan approval, and `zoho delivery-sync --task-id <id>` after developer commit (becoming `PM_SYNC_PENDING` on network failure).

## 2. Smart Context Rotation & Multi-Bridge Queue (`task bridge`)
- Never display raw `python .agents/harness.py task bridge ...` CLI commands in chat or `ask_question` for the developer to run manually, and NEVER append repetitive `Note:` bridge reminders before or between `run_command` calls during implementation or verification.
- Mention `CONTEXT_ROTATION_RECOMMENDED` AT MOST ONCE at final task delivery (or as an optional choice on the Commit/Delivery `ask_question` card). When the developer asks to save, snooze, or discard a bridge, execute `python .agents/harness.py task bridge --save [--task-id <id>] [--next-outcome "<follow-up>"] [--summary "<decisions>"]` (or `--snooze` / `--clear`) yourself.
- In a new chat when continuing bridged work, run `python .agents/harness.py task bridge` (if `MULTIPLE_BRIDGES_PENDING` / `SELECT_PENDING_BRIDGE` is returned, ask via `ask_question` and pass `--bridge-id <bridge_id>`).
