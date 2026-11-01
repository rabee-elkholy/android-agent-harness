# ADR-023: Automatic context reuse requires delivery and retention proof

Status: capability investigation completed; automatic integration unsupported.

Conversation identity and a saved transcript do not prove that a full context
response remains available to the next model invocation. Antigravity documents
automatic checkpoint summarization. The current adapters do not establish complete
response delivery and ongoing retained-input availability. PostToolUse documents
tool completion and an empty output object, not result replacement or delivery
acknowledgement.

Keep the ADR-022 explicit presentation contract. Default requests return full
current context. Only an explicitly supplied matching digest requests compaction;
callers must start full after summarization, pruning or uncertain resume.

Retain this investigation as documentation only. The optional capability field
and Doctor diagnostic were removed at the maintainer's request because they
provided no daily benefit without automatic integration. Do not add a cache,
configuration mode or hooks based on unestablished host semantics.

See [capability investigation](../implementation/session-context-capabilities.md)
for official sources, the decision matrix and native qualification limitations.
Future host support requires documented and observed recipient, delivery and
retention guarantees. No kernel gates, risk/review policy or task state change.
