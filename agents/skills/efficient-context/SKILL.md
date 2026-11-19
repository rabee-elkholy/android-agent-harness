---
name: efficient-context
description: Bounded graph-backed context resolution (`task-context --since`, batch targets) and Smart Context Bridge (`task bridge --save`) for zero-bloat Antigravity sessions.
version: 1.1.0
kernel-major: 1
disable-slash-command: true
---

# Efficient Context & Smart Bridge Skill

Follow `.agents/workflows/efficient-context.md` and `.agents/rules/pm-and-context-bridge.md`. Batch up to 8 targets in one `task-context` call, pass `--since <context_digest>` only within confirmed live turns, and execute `task bridge --save` / `task bridge` on the developer's behalf without printing raw CLI bridge commands in chat.

## Hybrid Quota-Safe Delegation & Anti-Reread Contract (Option 4)
- Keep the primary chat on `Gemini 4 Carbon (Medium)` or `Gemini 4 Neon (High)` and rotate to `Claude Sonnet 5.5 / Opus 5.5` when the `/usage` Gemini weekly bar reaches ~50%.
- **Parallel Hydrogen Scouts (`harness-scout-agent`)**: Delegate multi-file codebase discovery (pre-plan or mid-task) to `harness-scout-agent` passing `Model="flash"` unconditionally (routes natively in Antigravity to `gemini-4-hydrogen-tiered-high` `1x` regardless of the main-chat model; omit `Model` only if explicit `inherit` is configured, never built-in `research` or `explore`). When investigating `3+` distinct subsystems or screens, split into `2–3` parallel `harness-scout-agent` entries in a single `invoke_subagent` call (`<= 24` tool calls per scout, `4–8` parallel `view_file` reads per turn).
- **Warm-Cache Inline Lead Execution (`INLINE_LEAD_DIRECT`)**: During `IMPLEMENTING`, check `python .agents/harness.py delegate-plan --json` and implement approved production & unit-test files directly inline on the warm Lead session (or via `web-pack`/`web-apply` when Web execution mode is active), writing concise English KDoc (`/** ... */`) on newly created classes/interfaces and added public/internal `Repository`/`UseCase`/`ViewModel`/`DataSource`/`@Composable` contracts, then advance via `checkpoint-phase --advance-all-ready` or single-pass `verify-steps`.
- **Zero Post-Subagent Re-Read Across All Waves**: Once ANY `harness-scout-agent`, specialist, or reviewer wave returns, synthesize its file:line digest directly (or run `review complete-all` / `phase-review complete-all` after reviewers) without re-running `graph` or re-reading analyzed source files (hard cap: `<= 3` surgical `<= 200`-line gap checks per wave).
- **Surgical Symbol Tools on Large Files (`>350` lines)**: Use `python .agents/harness.py symbol outline --file <path>` and `symbol read --file <path> --symbol <Class.method>` (or `symbol replace-body` / `symbol insert-after` with `--expected-sha256`) to inspect/edit single declarations without loading 800+ surrounding lines.
- When the developer asks why a chat stalled or burned tokens, run `python .agents/harness.py diagnose-session --json` (add `--export-bundle` only if they request a Zero-PII diagnostic file).
