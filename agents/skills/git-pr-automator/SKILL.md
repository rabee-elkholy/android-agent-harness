---
name: git-pr-automator
description: Use when preparing a conventional commit message, pull request summary, or release change notes for developer review.
---

# Git notes (developer-owned)

The AI agent works **locally** and leaves changes unstaged.
The developer commits from their IDE. The agent must not `git add`, commit, push, or open a PR. Draft the message only.

## Conventional Commits (when the developer commits)
- `feat(scope):`
- `fix(scope):`
- `refactor(scope):`
- `test(scope):`
- `perf(scope):`

If asked to draft a commit/PR summary only, suggest:
- Title
- What changed (bullets)
- Modules (`:app`, `:base`, …)
- How it was verified (tests / device Pass)

## Worktrees
Do not create or use Git worktrees. Subagents inherit the opened checkout.
