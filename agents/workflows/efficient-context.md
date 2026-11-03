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
