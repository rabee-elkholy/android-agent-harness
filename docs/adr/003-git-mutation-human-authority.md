# ADR-003: Git mutation is human authority

## Context

Agents were observed committing incomplete work to cover mistakes, pushing
dirty state, and rewriting branches. Repository history must stay auditable
and human-owned.

## Decision

All git mutation verbs (`commit`, `push`, `reset`, `merge`, `rebase`,
`stash`, `checkout`, `switch`, `worktree`, `clone`, `fetch`, `pull`, `add`,
`branch`) are denied by the safety engine, including chained segments,
subshell wrappers, executable paths, config-option wrapping, and homoglyph
laundering. Adapters instruct agents to draft Conventional Commit messages
only; the developer commits from their IDE. Setup question I.3 may opt into
agent commits on explicit request. The staged pre-commit gate blocks
regressions but never blocks a human: the documented escape is
`git commit --no-verify`.

## Consequences

Repository history stays human-owned and auditable. Cost: an agent cannot
complete a delivery loop fully autonomously, and the documented bypass means
the gate is a quality fence rather than a security boundary against a
malicious human.
