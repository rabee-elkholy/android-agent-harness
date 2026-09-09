# Workflows

All workflows use the central lifecycle in `.agents/scripts/workflow.py`.

| Workflow | Purpose | Key property |
|---|---|---|
| `deliver` | Implement an approved change | Runs only policy-selected gates and reviewers |
| `debug` | Reproduce and fix a defect | Hypothesis-first and test-backed |
| `new-feature` | Add product behavior | Resolves material choices before plan approval |
| `preflight` | Fast static checks | Localization/Room/lint run only when relevant |
| `perf-audit` | Inspect performance risk | Evidence-driven; device profiling is optional unless policy requires it |
| `test-quality-audit` | Inspect test value | Does not replace execution evidence |
| `zoho-sprints` | Read or explicitly update tickets | Writes only after `update zoho` |

## Standard sequence

1. Inspect and analyze without mutation.
2. Draft a bounded plan with expected surfaces and skills.
3. Wait for explicit developer approval.
4. Consume approval and implement.
5. Freeze the delivery manifest and adaptive policy.
6. Run only selected gates and reviewers.
7. For sensitive surfaces, the developer separately approves the frozen final
   snapshot from their terminal or a non-synthesizable host-native control.
8. Read-only final verification.
9. Mark the unchanged snapshot ready and hand it off.

A blocking finding returns the task to `BLOCKED`. `resume` reopens implementation under the same approved scope; a material scope change requires a new approval. Three failed review rounds require developer direction.
The AI hook denies `approve`, `approve-sensitive`, and `cancel`; those
developer-authority transitions must come from outside the agent tool stream.
