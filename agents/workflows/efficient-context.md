# Efficient task context

Start each conversation/reviewer execution with a self-contained request:
`python .agents/harness.py task-context --file <actual-path> --json`.
Batch related known targets with repeated --file/--symbol (up to eight).

The default JSON presentation is SUMMARY and is self-contained: batch results
use shared_context_refs[field] indexes into shared_context[field] in the same
response. Read each referenced value as part of that target, including all scoped
instructions, architecture contracts and project notes. Different values are never
merged. Warnings, discovery receipts, scope restrictions, expansion requirements,
read ranges and target outlines remain intact.

Only advisory target node details and neighbor/test lists are shortened: at most
eight entries per list, with omitted_details counts and an explicit --full retrieval
instruction. Omitted entries are not absent dependencies or proof of test coverage.
Use the same query with --full whenever the missing detail is needed; --full returns
the original expanded structure. Failed/partial batches retain expanded output.
There is no hard output cap that could discard mandatory safety information.

The response includes a context_digest. For the same query in the same visible
conversation, pass `--since <that-digest>` to compact unchanged bulky context.
Use `--full` to force full output, including all advisory details. A mismatched baseline returns full current
context. Never copy a digest from an unrelated task/chat or infer that a repo
marker means this model already read the notes. The developer need not manage IDs.
After summarization, pruning or an uncertain resume, request full context again;
a response stored in a transcript is not proof it remains in the current input.

An unchanged digest does not prove previously omitted details were read.
Compaction runs after native discovery. Current scope, receipts, warnings,
instructions, expansion requirements and architecture restrictions remain visible.
It is presentation only, not permission, cached PASS or a reason to skip checks.
Architecture context is graph-derived advice; heuristic edges and candidate tests
are not a complete impact analysis. Omitted counts require normal expansion.

Use the existing verify-steps runner for consecutive router-selected deterministic
checks; use its returned next action without an unnecessary extra status query.
It still stops for reviews, failure, stale inputs and human/device decisions.

Optional local metrics use HARNESS_LOCAL_METRICS=1. Query the existing task metrics
command. Child-operation durations are separate from command totals, and numeric
counters describe harness work/output, not actual model reads or token use.
Feature-off performs no measurement reads/writes; collection never controls gates.

## Smart Context Rotation & Task-to-Task Bridge (`task bridge`)

When a conversation grows large (`CONTEXT_ROTATION_RECOMMENDED` at post-task delivery,
phase checkpoints, or pre-verification) or when the developer wants to start a related
follow-up task in a clean chat without re-explaining the previous task:

1. **Save the bridge in the current chat**:
   `python .agents/harness.py task bridge --save [--task-id <id>] [--next-outcome "<follow-up request>"] [--summary "<key decisions & files>"]`
   - For a completed/delivered task (`FOLLOW_UP_TASK`), this captures the completed task's
     outcome, approach, architecture contract, modified files, compact declaration signatures
     (`interface_delta`), and plan notes, plus a copy-ready `BRIDGE_HANDOFF_CARD`.
   - For an active in-progress task (`MID_TASK_HANDOFF`), this captures the live task state
     and marks the source session stopped for seamless continuation.
2. **Load the bridge in the new chat (100% optional & intent-conditional)**:
   `python .agents/harness.py task bridge`
   - Mints a fresh conversation-local Discovery Receipt (`st_mtime >= RECEIPT_NOT_BEFORE`)
     and refreshes `.agents/cache/last-task-context.json` so bounded searches and
     `task draft` work immediately with zero re-discovery overhead.
   - **Non-forced continuation & Multi-Bridge Queue**: `pre_invocation_reminder.py` surfaces an
     intent-conditional notice in the new chat. If multiple unconsumed bridges exist in
     `.agents/state/task-bridges.json`, `task bridge` returns `MULTIPLE_BRIDGES_PENDING`
     (`SELECT_PENDING_BRIDGE`) so the developer can choose via `ask_question` (`--bridge-id <id>`),
     consuming only the selected bridge and keeping the others queued. If the developer opens the
     new chat for a **different or unrelated topic**, address their actual request directly without
     running or consuming `task bridge` (leaving saved bridges untouched in the background, or run
     `python .agents/harness.py task bridge --clear [--bridge-id <id> | --all]` if they ask to discard).
   - If the developer chooses to stay in the current chat instead of rotating, suppress
     repeated advisories with `python .agents/harness.py task bridge --snooze`.
