---
name: efficient-context
description: Bounded graph-backed context resolution (`task-context --since`, batch targets) and Smart Context Bridge (`task bridge --save`) for zero-bloat Antigravity sessions.
version: 1.1.0
kernel-major: 1
---

# Efficient Context & Smart Bridge Skill

Follow `.agents/workflows/efficient-context.md` and `.agents/rules/pm-and-context-bridge.md`. Batch up to 8 targets in one `task-context` call, pass `--since <context_digest>` only within confirmed live turns, and execute `task bridge --save` / `task bridge` on the developer's behalf without printing raw CLI bridge commands in chat.

## Hybrid Quota-Safe Delegation & Anti-Reread Contract (Option 4)
- Keep the primary chat on `Gemini 4 Carbon (Medium)` and rotate to `Claude Sonnet 5.5 / Opus 5.5` when the `/usage` Gemini weekly bar reaches ~50%.
- **Parallel Hydrogen Scouts (`harness-scout-agent`)**: Delegate multi-file codebase discovery (pre-plan or mid-task) to `harness-scout-agent` (`gemini-4-hydrogen-medium` by default, omitting `Model` in `invoke_subagent` so `agent.md` frontmatter applies; never built-in `research` or `explore`). When investigating `3+` distinct subsystems or screens, split into `2–3` parallel `harness-scout-agent` entries in a single `invoke_subagent` call (`<= 24` tool calls per scout, `4–8` parallel `view_file` reads per turn).
- **Warm-Cache Inline Edits (`<4` Files) & `Hydrogen High` Worker (`4+` Files + `worker-handoff.json`)**: During `IMPLEMENTING`, check `python .agents/harness.py delegate-plan --json`: execute `1–3` file non-sensitive `T0-T3` slices inline on the warm Lead session (`TRIVIAL_INLINE_LEAD`), and dispatch a single `harness-worker-agent` (`Workspace='inherit'`, starting on `gemini-4-hydrogen-high` from Wave 1; automatic `Hydrogen` capped at `high`) with a Decision-Complete Brief for `4+`-file slices (including `previous_wave_handoff.corrective_wave_brief_hint` on corrective `Hydrogen High` waves). On `ORCHESTRATOR_FRICTION_LEAD_TAKEOVER` (after 2 `Hydrogen High` failures or 1-wave `Fast-Fail` architectural/empty-wave blocker), read `.agents/state/tasks/<id>/worker-handoff.json` + `git diff`, patch `lead_owned_files` surgically on top of existing Worker progress without starting from scratch, and delegate `TESTS_AND_GATES_ONLY` to `harness-worker-agent`; retain `T4/T5` sensitive production edits (`AUTH`, `BILLING`, `SECURITY`, `CRYPTO`) on the Lead Architect (`Gemini 4 Carbon Medium`).
- **Zero Post-Subagent Re-Read Across All Waves**: Once ANY `harness-scout-agent`, `harness-worker-agent`, specialist, or reviewer wave returns, synthesize its file:line digest directly (or run `git diff` once after a worker slice, or `review complete-all` / `phase-review complete-all` after reviewers) without re-running `graph` or re-reading analyzed source files (hard cap: `<= 3` surgical `<= 200`-line gap checks per wave).
- **Surgical Symbol Tools on Large Files (`>350` lines)**: Use `python .agents/harness.py symbol outline --file <path>` and `symbol read --file <path> --symbol <Class.method>` (or `symbol replace-body` / `symbol insert-after` with `--expected-sha256`) to inspect/edit single declarations without loading 800+ surrounding lines.
- When the developer asks why a chat stalled or burned tokens, run `python .agents/harness.py diagnose-session --json` (add `--export-bundle` only if they request a Zero-PII diagnostic file).
