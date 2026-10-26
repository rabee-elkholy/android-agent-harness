---
description: Design and implement an Android feature with explicit plan approval and adaptive quality gates.
---

# New Android feature

1. Inspect the relevant architecture and any supplied media. Resolve material product choices before drafting the plan.
2. Route the approved surfaces to architecture, Compose/XML, coroutines, testing, Gradle, persistence, performance, debugging, or security/billing skills as needed.
3. Present one bounded implementation plan. Do not auto-start it. Begin only after explicit developer approval.
4. Implement with targeted tests and preserve existing project conventions. Stop for reapproval if actual surfaces or modules materially exceed the plan.
5. Follow `deliver.md` for immutable verification, adaptive review, complete APK-set handling, and final readiness.

Write new files using the project's resolved patterns. `new_feature_scaffold.py` is disabled and generates nothing.

## Recovering planning errors

- An in-scope fix or description clarification is not a new plan. Use `task resume` before correcting review findings and `task plan-note --text "<clarification>" --source conversation --proof-reference "<decision>"` for explanatory notes. Notes leave the approved payload, phases, review budgets and frozen evidence unchanged. `PLAN_NOTE_REQUIRED` means no reapproval is needed for a clarification; do not invent material scope. If prose really changes the requirements, use `revise --material-change-reason "<concrete expansion>"` and obtain approval of the revised requirements.

- Use the resolved Task Context's `read_ranges`, direct dependencies/dependents and tests. Query the graph again only for a missing relationship; do not repeat discovery for files already resolved.
- For several known targets, repeat `--file` or `--symbol` in one Task Context call (up to eight, one selector kind). Inspect every result, including missing/ambiguous files. Discover the source/layout/manifest/callers/tests needed to satisfy each requirement before presenting scope; a source filename alone does not establish complete cleanup.
- `draft` and `revise` use stable live architecture facts when the saved context is stale, missing or unusable. They do not persist a context refresh or grant application-write authority. Concurrent source/policy changes block the decision; wait for the writer to stop before retrying. Genuine architecture ambiguity still requires the developer's decision; never change the intent merely to avoid it.
- A metadata-only `revise` retains the previous architecture mode, target scope and family and revalidates them. Explicit architecture changes win; changed files trigger scope inference again. Legacy plans without a contract use normal resolution.
- Explicit surface lists are a floor: declared Android/KMP test paths retain `TEST_ONLY` even before the files exist. For a new UI implementation, declare the chosen toolkit in the plan/surfaces before approval (`COMPOSE_UI` for Compose, `XML_UI` for Views); an `Activity` filename alone cannot prove that choice. Introducing a toolkit later is a genuine change to the declared plan and must still reconcile its required skills.
- For `PHASE_PLAN_REQUIRED`, pass semantic phases directly, for example `--phases "p1:Create onboarding paywall,p2:Migrate callers and validate integration"`. Replace the titles with actual task boundaries. The command normalizes and stores the phases with the plan; no helper file, shell redirection or unapproved project write is necessary. A JSON list with `id`, `title` and optional `expected_files` remains supported for richer definitions.
- Read the complete failure once, fix the named cause, then rerun. A denied mutation is not permission to try another tool or shell form. Preserve the old plan/approval/evidence on a refused revision, and report a reproducible harness defect through Doctor rather than patching the installed engine.
