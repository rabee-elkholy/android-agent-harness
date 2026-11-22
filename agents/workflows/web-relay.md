---
description: Optional stateless Manual Web-Relay Mode (`web-pack` / `web-apply`) for offloading heavy planning/coding (including 30–100+ file refactors and UI screenshot tasks) to any external AI chat while keeping 100% local safety, Gradle, ADB, and default Antigravity mode untouched.
---

# Optional Manual Web-Relay Workflow (`web-pack` -> External AI Chat -> `web-apply`)

**Execution Mode Integration (`normal-*` vs `web-*`)**: Ordinary tasks run locally in Antigravity by default without prompting. When a heavy task (`10+` files, `80+ KB` code mass, `2+` phases, substantial multi-module scope, or non-trivial `T5` scope) warrants external Web-Relay and no project lock is set, run `python .agents/harness.py execution-mode show --files <csv> [--surfaces <csv>] [--phases <N>] --json` BEFORE `task draft` (or on `SELECT_EXECUTION_MODE_REQUIRED`) and ask the developer via `ask_question` stating the approximate quota savings (`~60%-85%`) with 3 choices (`normal-task`, `web-task`, `normal-project`), recorded via `python .agents/harness.py execution-mode set --choice <normal-task|web-task|normal-project|web-project|ask-every-task> --source conversation --proof-reference "<words>"`. Single-task overrides (`normal-task` / `web-task`) apply to one task without altering any saved project lock, and `CONFLICT` tasks always resolve locally while preserving `web-project`.

## When to use `Mode 2: Manual Web-Relay`

Use when `execution-mode` is set to `web-task` / `web-project`, when the developer asks to pack context for an external AI chat (e.g., `30–100+` file refactors, heavy multi-module features, `T5` sensitive reviews, UI design screenshot tasks, or quota-saving runs), or when applying a returned `HARNESS_WEB_MERGE_V1` merge block.

## Step 1: Build the Scoped Context Pack (`web-pack`)

```bash
# Cold-start (from IDLE — auto-discovers AST scope, open Git dirty edits, neighbor signatures & R.drawable/R.font IDs)
python .agents/harness.py web-pack --prompt "<goal or bug description>" [--feature <FeatureOrSymbol>] [--file <paths...>] [--dirty]

# Active-task pack (packs up to 40 editable files in 1 pack; auto-shards 41–250 files in DAG order)
python .agents/harness.py web-pack --task-id <id> --prompt "<optional refinement>"

# Expand existing pack with additional files or adjust batching for large refactors
python .agents/harness.py web-pack --task-id <id> --add-files <paths...>
python .agents/harness.py web-pack --task-id <id> --batch-size 40
python .agents/harness.py web-pack --task-id <id> --all-in-one

# Retry delta packs (send compact JUnit / Gradle / preflight failure diagnostics to the SAME external chat)
python .agents/harness.py web-pack --task-id <id> --retry
python .agents/harness.py web-pack --task-id <id> --retry-failure
```

What `web-pack` guarantees automatically:
- **Single-File `.md` Bundle (`30–40` Files Standard) + Auto-Sharded `41–250` File DAG Batches**: Routine `1–40` file tasks pack into **one** `.md` file under `~/Downloads/Harness-Web-Relay/`. Massive `41–250` file refactors sort automatically in Clean Architecture DAG order (`core`/`domain` -> `data` -> `app`/`UI` -> `res` -> `tests`) and shard into `40`-file batches (`Batch 1/N`) with the upcoming batch schedule embedded in Section `4A`. Bundles `<= 45 KB` copy straight as UTF-8 text to Clipboard; larger bundles copy the `.md` file handle (`Set-Clipboard -Path`).
- **Binary Asset Shield & Automatic `R.drawable` / `R.font` / KMP `Res.drawable` Inventory**: Binary media/font files (`.png`, `.webp`, `.jpg`, `.ttf`, `\x00` bytes) are excluded from UTF-8 code blocks (`binary_assets` metadata instead), while existing module `R.drawable.*`, `R.font.*`, and KMP `Res.drawable.*` IDs are indexed automatically in Section 2 so the external AI model reuses real project assets or emits `<vector>` XML `CREATE` operations without hallucinating missing resource IDs.
- **Zero-Secret Vault Redaction**: Blocks `.env`, `keystore`, `.jks`, `local.properties`, `google-services.json`, `GoogleService-Info.plist`, and `*secret*`/`*credentials*`, and replaces inline tokens (`AIza...`, `Bearer ...`, `sk-...`, `api_key=...`) with `__HARNESS_REDACTED_SECRET_N__` stored locally under `.agents/state/web-relay/packs/<pack_id>.json`.
- **AST Neighbor Signatures**: Includes public signatures of direct callers/callees (`READ_ONLY_NEIGHBOR_SIGNATURES`), `project-facts.json`, code-relevant `project-notes.md`, active `developer-instructions.json`, and any failing local gate diagnostics.


> **Zero-Rewrite `web-apply` Rule**: Always run `python .agents/harness.py web-apply --source conversation --proof-reference "<words>"` **FIRST with NO `--file` flag** — it automatically discovers the merge payload from Clipboard, `~/Downloads`, or `.agents/state/web-relay/inbox/`. NEVER re-emit the merge JSON via shell redirection or external paths; ONLY if raw JSON was pasted in chat and `web-apply` reports no file in Clipboard/Downloads, write it once via `write_file` to `.agents/state/web-relay/inbox/merge.json` and re-run `web-apply`.

## Step 2: Developer Interaction in External AI Chat

1. **For a new task**, open a **NEW** external AI chat (ChatGPT, Claude, Gemini, etc.), press `Ctrl+V` to attach/paste the Context Pack (plus attach 1–5 relevant Figma/UI screenshots if implementing a visual mockup — avoid 40+ bulk image dumps in a single session), and send. *(Only stay in the **SAME** chat when continuing a `--retry`, `PARTIAL`, `NEED_FILES`, or `Batch 2+` pack of the same task.)*
2. Copy the `HARNESS_WEB_MERGE_V1` JSON block from the reply (or save it to `~/Downloads`).

## Step 3: Verify & Apply Locally (`web-apply`)

When the developer says in chat to apply the Web-Relay reply (e.g. `"apply"` / `"merge"`), execute with explicit conversation proof:

```bash
# Optional read-only preview (line stats, 3-way merge check & static lint warnings; 0 files modified):
python .agents/harness.py web-apply --dry-run

# Apply verified changes:
python .agents/harness.py web-apply --source conversation --proof-reference "<developer words>"
```

(Or the developer can run `python .agents/harness.py web-apply --source developer_terminal` directly in a terminal.)

What `web-apply` enforces before and during writes:
- **Resilient `JSONDecoder.raw_decode` Extraction & Single-Use Binding**: Safely extracts `HARNESS_WEB_MERGE_V1` even when string values contain inner ```` ```kotlin ```` markdown fences, trailing commas, or surrounding prose, and verifies `pack_id`, `repo_fingerprint`, active `task_id`, and `applied == False` (`PACK_ALREADY_APPLIED` blocks stale replays).
- **`NEED_FILES`, `"status": "PARTIAL"`, & Multi-Batch Auto-Advance (`APPLIED_BATCH_NEXT_READY`)**: `"status": "NEED_FILES"` builds an expanded pack immediately; `"status": "PARTIAL"` applies the first chunk of a large batch while keeping `pack_id` open for the continuation reply; and on multi-batch `41–250` file tasks, completing Batch `k/N` automatically builds and copies Batch `(k+1)/N` to Clipboard (`APPLIED_BATCH_NEXT_READY`).
- **Surgical Neighbor `hunks` + Anti-Truncation & Brace Balance**: Supports exact `SEARCH/REPLACE` `hunks` (including `"replace_all": true`), `MODIFY`, `CREATE`, `DELETE`, and `RENAME`; allows verified surgical `hunks` on unscoped non-secret repo files (such as `READ_ONLY_NEIGHBOR_SIGNATURES` callers) while blocking blind full-file `"content"` overwrites (`UNSCOPED_EXISTING_FILE_OVERWRITE_BLOCKED`), lazy placeholders, `> 65%` unrequested line wipes, and unbalanced `{}` braces.
- **3-Way Git Merge, Accumulated Multi-Phase Staging & Auto `BUG` `RED -> GREEN`**: Runs `git merge-file -p` on concurrent local edits, restores `__HARNESS_REDACTED_SECRET_N__` from the local vault, preserves `CRLF`/`LF` endings, accumulates future-phase (`p2..pN`) edits across batches under `.agents/state/tasks/<id>/staged-web-phases/<phase>.json` (applied via `web-apply --staged-phase`), and captures `RED` test evidence automatically before writing `BUG` fixes.
- **Zero-Token Static Gate & `Zero Re-Read` Receipt**: Runs `fast_kt_lint.py` + `check_strings.py` immediately and writes `web-relay-receipt.json` (`WEB_RELAY_APPLIED_VERIFY`) once all batches complete so Antigravity proceeds straight to `task prepare-verification` without re-reading applied files.
