---
trigger: model_decision
description: "Apply when resolving Git merge conflicts, reconciling concurrent Android Studio developer edits or commits, healing stale task state, or continuing tasks across hosts."
---
<!-- managed-by: android-agent-harness -->

# Merge Conflicts, IDE Edit Reconciliation & Recovery

Keep `.agents/rules/harness-rules.md` authoritative.

## 1. Merge Conflict Resolution (`--kind CONFLICT` / `FIX_CONFLICT` / `MERGE`)
- Draft conflict tasks with `--kind CONFLICT` and `--expected-files <paths>`.
- Never silently drop callbacks, state fields, UI elements, imports, permissions, or error handling from either `HEAD` or the incoming branch.
- On semantic or behavioral incompatibility between branches, ask the developer via `ask_question` before choosing one side.
- Run `python .agents/harness.py compile` immediately after resolving conflict markers before preparing verification.

## 2. Concurrent Android Studio Edits, Reformatting & Git Lineage
- When the router reports `FILE_SCOPE_DECISION_REQUIRED`, `VERIFICATION_STALE`, `DELIVERY_STALE_AFTER_COMMIT`, or `TASK_HEAD_LINEAGE_RECONCILIATION_REQUIRED`, ask the developer via `ask_question` whether they made those changes in Android Studio or Git.
- If confirmed, record via `python .agents/harness.py task change-decision --repo . --task-id <id> --mode accept-edits --file <path> --reason "Developer edit/reformat in Android Studio" --apply --source conversation --proof-reference "<developer answer>"` (`--reconcile-lineage` for developer Git commits/merges, or `--mode extend-scope` for same-outcome support files).
- During `VERIFYING` or `READY_FOR_DELIVERY`, run `change-decision` preview first, then apply with `--apply --expect-preview <sha256>`.
- For wedged or interrupted task state, run `python .agents/harness.py task heal --task-id <id> --prepare-fresh-run`.

## 3. Host Continuation & Disjoint Tasks
- Up to 3 tasks with disjoint file scopes may coexist in one worktree (`python .agents/harness.py task switch --task-id <id>`; commit separately, then `task reconcile-delivery --task-id <id>`).
- Unstarted pending plans can be consolidated via `python .agents/harness.py task merge --task-id <new-id> --from-task-id <a> --from-task-id <b>` (preview then `--apply --expect-preview <sha256>`).
- When continuing a task on Antigravity after stopping a former host, run `python .agents/harness.py task continue --task-id <id> --host antigravity --source-stopped` (with `--expect-session` when supplied by the router).
