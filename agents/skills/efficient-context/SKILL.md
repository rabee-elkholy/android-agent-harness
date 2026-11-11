---
name: efficient-context
description: Bounded graph-backed context resolution (`task-context --since`, batch targets) and Smart Context Bridge (`task bridge --save`) for zero-bloat Antigravity sessions.
version: 1.0.0
kernel-major: 1
---

# Efficient Context & Smart Bridge Skill

Follow `.agents/workflows/efficient-context.md` and `.agents/rules/pm-and-context-bridge.md`. Batch up to 8 targets in one `task-context` call, pass `--since <context_digest>` only within confirmed live turns, and execute `task bridge --save` / `task bridge` on the developer's behalf without printing raw CLI bridge commands in chat.

## Hybrid Quota-Safe Delegation (Option 4)
- Keep the primary chat on `Gemini 4 Carbon (Medium)` and rotate to `Claude Sonnet 5.5 / Opus 5.5` when the `/usage` Gemini weekly bar reaches ~50%.
- Delegate multi-file codebase discovery before `task draft` to `harness-scout-agent` (`gemini-3.8-flash-medium`).
- During `IMPLEMENTING`, check `python .agents/harness.py delegate-plan --json` and dispatch a single `harness-worker-agent` (`Workspace='inherit'`) with a Decision-Complete Brief for `T0-T3` non-sensitive slices and Gradle compile/test loops; retain `T4/T5` sensitive production edits (`AUTH`, `BILLING`, `SECURITY`, `CRYPTO`) on the Lead Architect.
- For large Kotlin/Java/Swift files (`>350` lines), use `python .agents/harness.py symbol outline --file <path>` and `symbol read --file <path> --symbol <Class.method>` (or `symbol replace-body` / `symbol insert-after` with `--expected-sha256`) to edit single declarations without loading 800+ surrounding lines.
- When the developer asks why a chat stalled or burned tokens, run `python .agents/harness.py diagnose-session --json` (add `--export-bundle` only if they request a Zero-PII diagnostic file).
