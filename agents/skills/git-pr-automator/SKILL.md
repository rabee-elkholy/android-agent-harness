---
name: git-pr-automator
description: Use when the developer asks for a commit message or PR summary. The agent never commits or opens PRs.
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
