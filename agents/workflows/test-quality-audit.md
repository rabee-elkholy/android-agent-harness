---
description: Static audit of unit and UI test suites (*Test.kt) using test-quality-reviewer-agent.
---

# Test Quality Audit Workflow (`/test-quality-audit`)

Follow `.agents/rules/harness-rules.md`. Solo test quality audit does not replace delivery review.

## Steps

1. Identify modified or newly added test files (`*Test.kt`).
2. Invoke `test-quality-reviewer-agent` with the target test files.
3. Verify assertion depth, `runTest` Coroutines dispatchers, and mocking integrity.
4. If this audit is part of shipping a code change, still run the full 5-leaf gate.
5. Reference: `.agents/skills/android-harness/references/test-quality-guidelines.md`
