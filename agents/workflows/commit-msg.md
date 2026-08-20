---
description: Draft a Conventional Commit message for Android Studio. The agent never commits.
---

# Generate Conventional Commit Message

Follow `.agents/rules/harness-rules.md`. Never `git add` / commit / push.

## Steps

1. Inspect with `git status --short --branch` and `git diff HEAD --stat` only.
2. After every device phase is Pass, present:

```
<type>(<module/feature>): <concise imperative summary>

- What changed:
  * Detail 1
  * Detail 2
- Modules affected: :app, :base...
- Verification: Physical device tested / Unit tests passed
```

3. Ready to paste into Android Studio. Do not run git commit.
