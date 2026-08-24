---
description: Zoho Sprints ingest, create, and update zoho — same workflow as the original engine.
---

# Zoho Sprints

Follow `.agents/rules/harness-rules.md` section 5. This file is the playbook. **Zoho Desk is not used.** If `workflow_defaults.json` has empty values, the server resolves defaults at runtime. Fill them during install (I.16) or leave them for the developer to configure later.

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
- Description: Resolved per `ZOHO_LANGUAGE` in `_product.py`, no emoji, no engine internals. Use the matching template below if they asked for a full write-up; otherwise a short scope is enough.

## `update zoho` (mutate)

Never `Done` / `Solved`.

| When | Status | What to write |
|---|---|---|
| Work started | `In progress` | Optional short comment. Do not mark verified. |
| Device phases all Pass | `Ready To ReTest` | Full template in the **description**. Short **comment** with the commit hash. |

### Audience & Tone Policy
- **Primary Audience**: **QA / Testers & Product Stakeholders**.
- **STRICTLY FORBIDDEN**: Low-level code internals (e.g. no XML layout file names like `fragment_*.xml`, no Kotlin source files, no XML attribute names like `clipToPadding`, no framework class names, and no arbitrary `dp`/`px` numbers). Explain everything in functional, user-facing behavior.
- **Mandatory Commit Hash**: The first line MUST always be `Commit: <hash>` (retrieved via `git log -1 --format=%h`). If HEAD has not moved (developer has not committed), ask them to paste the hash. Do not invent one.

---

### Language Mapping Table (Per `ZOHO_LANGUAGE` in `_product.py`)

Language is resolved from `_product.py` (configured in setup wizard I.18):
- `en_titles_ar_comments` (Default): English task titles, Arabic descriptions & comments.
- `all_en`: English task titles, English descriptions & comments.
- `all_ar`: Arabic task titles, Arabic descriptions & comments.

| Section | English Header (`all_en`) | Arabic Header (`en_titles_ar_comments` / `all_ar`) |
|---|---|---|
| First Line | `Commit: <hash>` | `Commit: <hash>` |
| 1. Root Cause / Objective | `Root Cause:` (bugs) / `Objective:` (tasks/features) | `سبب المشكلة:` / `الهدف من المهمة:` |
| 2. Solution / Implementation | `Solution:` / `What Changed:` | `الحل المطبق:` / `ما تم تنفيذه:` |
| 3. Blast Radius / Scope | `Impact Area (Blast Radius):` | `نطاق التأثير (Impact Area):` |
| 4. Verification Scenarios | `Test Cases & Verification Steps:` | `خطوات الفحص وحالات الاختبار (Test Cases):` |

---

### 1. Bug Template (Description)

**English Structure (`all_en`):**
```
Commit: <hash>

Root Cause:
<Functional explanation of why the defect occurred from a user-experience perspective, with zero internal code jargon>

Solution:
<Functional summary of what changed and how the UI/feature now behaves correctly>

Impact Area (Blast Radius):
- <List screens, related flows, or shared components that QA must verify for regression>

Test Cases & Verification Steps:
1. <Positive / happy path verification step>
2. <Negative, edge cases, different account tiers, or various screen sizes>
```

**Arabic Equivalent (`en_titles_ar_comments` / `all_ar`):**
```
Commit: <hash>

سبب المشكلة:
<شرح وظيفي لسبب المشكلة من منظور تجربة المستخدم دون ذكر أكواد داخلية>

الحل المطبق:
<ما تم تعديله وتصحيحه في سلوك الواجهة والتطبيق>

نطاق التأثير (Impact Area):
- <الشاشات أو الميزات المرتبطة التي قد تتأثر ويجب فحصها للتأكد من عدم حدوث Regression>

خطوات الفحص وحالات الاختبار (Test Cases):
1. <السيناريو الأساسي / الحالة الإيجابية>
2. <السيناريو العكسي أو الحالات الحدية / أنواع الحسابات المختلفة أو أحجام الشاشات>
```

---

### 2. Feature / Story Template (Description)

**English Structure (`all_en`):**
```
Commit: <hash>

Feature & Objective:
<Description of the new feature and its functional purpose for the user>

Implementation & Entry Points:
<Target screens, navigation entry points, and new user flows>

Impact Area (Blast Radius):
- <Connected screens or shared components affected by this new feature>

Test Cases & Verification Steps:
1. <Happy path end-to-end user flow>
2. <Edge cases, network error states, and permission variants>
```

**Arabic Equivalent (`en_titles_ar_comments` / `all_ar`):**
```
Commit: <hash>

الميزة والهدف منها:
<وصف الميزة المضافة والهدف الوظيفي منها للمستخدم>

ما تم تنفيذه:
<الشاشات ومداخل الميزة وسلوكها الجديد>

نطاق التأثير (Impact Area):
- <الشاشات أو التدفقات المرتبطة بالميزة الجديدة>

خطوات الفحص وحالات الاختبار (Test Cases):
1. <خطوات فحص مسار الاستخدام الرئيسي (Happy Path)>
2. <خطوات فحص الحالات الاستثنائية والـ Edge Cases>
```

---

### 3. Task / Improvement Template (Description)

**English Structure (`all_en`):**
```
Commit: <hash>

Objective:
<Purpose of the improvement or refactoring task from a product/performance standpoint>

What Changed:
<Functional and noticeable changes in app behavior or performance>

Impact Area (Blast Radius):
- <Modules or screens requiring smoke/regression testing>

Test Cases & Verification Steps:
1. <Verification steps to ensure the improvement works as expected>
```

**Arabic Equivalent (`en_titles_ar_comments` / `all_ar`):**
```
Commit: <hash>

الهدف من التعديل:
<شرح التحسين أو التعديل المطلوب والغرض منه>

ما تم تنفيذه:
<ملخص التعديلات الوظيفية الظاهرة للمستخدم أو المؤثرة على الأداء>

نطاق التأثير (Impact Area):
- <الأماكن والميزات التي يجب فحصها للتأكد من سلامة النظام>

خطوات الفحص وحالات الاختبار (Test Cases):
1. <سيناريوهات التحقق والتأكد من عمل التحسين>
```

After every device phase is Pass, remind once in chat that Zoho is not updated until they say `update zoho`. No modal.

## After local delivery (no Zoho yet)

Walkthrough + Conventional Commit message stay as in harness-rules section 4. Zoho waits for the explicit phrase.
