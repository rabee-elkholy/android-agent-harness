---
description: Universal PM Tracker (Zoho Projects, Zoho Sprints, Jira, Linear, Monday, ClickUp, Asana, Trello, GitHub) ingest, create, and update workflow.
---

# Universal PM Tracker Playbook (All Providers)

Follow `.agents/rules/harness-rules.md` section 7. This playbook governs **all** external PM MCP servers installed in Antigravity (`zoho-projects_mcp`, `zoho-sprints`, `atlassian-mcp-server` / Jira, `linear`, `monday`, `clickup`, `asana`, `trello`, `github`).

## 1. Zero-Config Discovery & Read-Only Ingest

Run `python .agents/harness.py pm status` to inspect all installed PM MCP servers and their categorized tools (`read_tools`, `create_tools`, `update_status_tools`, `update_description_tools`, `comment_tools`).

- **Read/Search/Inspect tools are always allowed immediately** without approval.
- **Bug id / Issue id:** fetch details from the active PM MCP, explain in chat, analyze, then draft the normal task plan with `workflow.py` and request approval.
- **Feature / Task id:** fetch details, explain in chat, then ask whether to start the plan. Do not implement until the developer approves.
- Never change status, description, or comments during ingest.

## 2. Mandatory Preview & Approval Before Any PM Write

Never create, update, comment, transition, or delete any item on any PM MCP without **first showing the exact preview to the developer and obtaining their explicit approval**:

1. **Present the Preview in Chat**:
   - Target Provider & Item ID / Title
   - Target Action (`Create Task`, `Update Description`, `Add Bug QA Comment`, `Update Status`)
   - Exact Status Transition (e.g. `In progress` or `Ready To ReTest` / `In Review`)
   - Exact formatted Description or Comment body (prepared via `python .agents/harness.py pm prepare-report ...`)
2. **Wait for Explicit Approval**:
   - When the developer replies (`حدث التاسك` / `update pm` / `update zoho` / `update jira` / `update linear` / `حدث زوهو`), record the 30-minute write grant:
     `python .agents/harness.py pm authorize --proof-reference "<developer's message>"`
   - Never revise the code task plan (`workflow.py revise`) just to update the PM tracker.

## 3. Universal PM Safety & Quality Rules (All Providers)

| Rule | Requirement Across Every PM MCP |
|---|---|
| **Bug / Issue Description Preservation** | For **Bug / Defect / Issue** items, **NEVER modify or overwrite the Bug's Description** (preserves QA's original bug report and reproduction steps). Always post the QA delivery report as a **Comment** (`ZohoProjects_add_issue_comments`, `addCommentToJiraIssue`, `zoho_add_comment`, etc.). |
| **Task / Story Delivery** | For **Task / Story / Feature** items, write the full 5-section QA delivery report in the **Description** and post a short **Comment** with `Commit: <short-hash>`. |
| **Terminal Status Protection** | Never set `Done`, `Closed`, `Solved`, `Completed`, or `Resolved` automatically — always transition to `Ready To ReTest` / `In Review` / `Ready for Testing`, **unless** the developer explicitly ordered closing the task (`close task` / `اقفل التاسك`). |
| **Zero Code / File / Class Leak** | Never include raw source file names (`.kt`, `.java`, `.xml`, `.kts`, `.gradle`), class/architecture identifiers (`*ViewModel`, `*Fragment`, `*Activity`, `*Repository`, `*UseCase`, `*Composable`), or internal code jargon. Write for **QA / Testers & Product Stakeholders** in functional user-facing terms. |
| **5-Section RTL HTML Standard (when required by `project-notes.md` or HTML trackers)** | Use `<div dir="rtl" style="font-family: inherit; line-height: 1.6; text-align: right;">` with `<h3>` headings (`1. سبب المشكلة والهدف من المهمة`, `2. التعديلات الوظيفية والسلوكية للتطبيق` + Unit Tests PASS + Commit hash, `3. نطاق التأثير وفحص الآثار الجانبية`, `4. سيناريوهات الفحص اليدوي وفريق الجودة` in a 4-column `<table>`, `5. معايير القبول`). Never hardcode dark colors (`#2c3e50`, `#000000`); use `inherit` and `rgba(128,128,128,0.15)` for Dark/Light Mode compatibility. |

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

### 1. Bug Template (Comment — Do NOT modify Bug Description)

> [!IMPORTANT]
> For **Bug** items, ALWAYS post the full delivery report as a **Comment**. **NEVER modify or overwrite the Bug's Description**, preserving the original QA bug report, environment details, and reproduction steps intact.

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

> [!NOTE]
> For **Story / Feature / Sub-task** items, write/update this template in the **Description**, and post a short comment with `Commit: <hash>`.

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

> [!NOTE]
> For **Task / Improvement** items, write/update this template in the **Description**, and post a short comment with `Commit: <hash>`.

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
