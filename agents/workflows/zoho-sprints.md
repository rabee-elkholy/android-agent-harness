---
description: Zoho Sprints ingest, create, and update zoho — same workflow as the original engine.
---

# Zoho Sprints

Follow `.agents/rules/harness-rules.md` section 5. This file is the playbook. **Zoho Desk is not used.**

Credentials stay in the user-level config. Never copy tokens into the repo. Never mutate Zoho unless the developer explicitly says `update zoho` (or an equivalent explicit order).

## Tools

`zoho_list_sprints` · `zoho_list_tasks` · `zoho_get_task_details` · `zoho_create_task` · `zoho_update_task_status` · `zoho_update_task_description` · `zoho_add_comment`

Pass sprint_id + item id (display number or internal id). The server resolves display numbers.

## Ingest (read-only — not `update zoho`)

**Bug id:** fetch details if tools exist, explain in chat, start analysis. Still write `.agents/state/plans/implementation_plan.md` for non-trivial bugs and request approval.

**Feature task id:** fetch, explain, then ask whether to start the plan. Do not implement until they approve.

If MCP tools are missing: do not invent ticket fields. Ask the developer to paste the ticket or enable Zoho. Continue local work with what they provide.

Do **not** change status, description, or comments during ingest.

## Create a task (only when they asked to create one)

This still counts as a mutate. Do it only on an explicit create request (including `update zoho` that says to open a new item).

- Title: the work name only. **No developer name** in the title (the server strips known suffixes).
- Type: `Task` / `Bug` / `Story` as they said. Default `Task`.
- Priority: `Low` / `Medium` / `High` / `None`. Default `Medium`.
- Assignee: the default Sprints user from the MCP workflow (do not pick someone else).
- Optional `parent_item_id` for a sub-item.
- Description: Arabic, no emoji, no engine internals. Use the matching template below if they asked for a full write-up; otherwise a short scope is enough.

## `update zoho` (mutate)

Never `Done` / `Solved`.

| When | Status | What to write |
|---|---|---|
| Work started | `In progress` | Optional short comment. Do not mark verified. |
| Device phases all Pass | `Ready To ReTest` | Full template in the **description**. Short **comment** with the commit hash. |

Prose is **Arabic**. No emoji. Human tone. No hook/selftest/Gradle internals.

Commit hash: `git log -1 --format=%h`. If HEAD has not moved (developer has not committed), ask them to paste the hash. Do not invent one.

### Bug template (description)

```
Commit: <hash>

سبب المشكلة:
<why it broke — producer, not the symptom>

الحل:
<what changed>

خطوات الفحص:
<how to verify on the device>
```

### Feature template (description)

```
Commit: <hash>

الميزة:
<what shipped>

الشاشات:
<screens / entry points>

حالات الاختبار:
<what passed on the device>
```

After every device phase is Pass, remind once in chat that Zoho is not updated until they say `update zoho`. No modal.

## After local delivery (no Zoho yet)

Walkthrough + Conventional Commit message stay as in harness-rules section 4. Zoho waits for the explicit phrase.
