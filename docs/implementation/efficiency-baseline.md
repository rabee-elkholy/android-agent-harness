# Efficiency baseline

Baseline: v1.1.59, 2701c2c61cd4960247c561f78de36b0ee9896d5f, clean isolated checkout.
Older dirty Graphify checkout was preserved. No commits or publication authorized.
Existing project-intelligence focused suite passed before changes (31 tests).

Observed duplication: a two-target context batch loaded project facts twice, and
review topology compared every changed path against every graph node. Existing
notes compaction used a repo-global marker that could hide notes in a new chat.
Existing metrics were opt-in and command-only; architecture contracts and native
incremental graph/discovery already existed. Preserve those sources of authority.

Protected boundaries: plan approval, six-tier gate/reviewer policy, review identity,
source freshness, device authority, Git ownership. No host adapter hook schema or
model selection changes are needed. No installed third-party dependencies added.
