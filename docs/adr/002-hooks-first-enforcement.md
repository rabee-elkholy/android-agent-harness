# ADR-002: Hooks-first enforcement with prompt-level fallback

## Context

Antigravity provides runtime PreToolUse hooks (`agents/hooks.json`). Other
tools have heterogeneous capabilities: Claude Code has a PreToolUse protocol,
GitHub Copilot has repository-level preToolUse hooks, and the remaining tools
read instruction files only. A single enforcement story would either overstate
or underuse each tool.

## Decision

Enforcement is tiered and honest:

1. **Hook-enforced**: the same stdlib deny engine (`pre_tool_safety.py` driven
   by `policy_vocab.py`) runs inside Antigravity, Claude Code
   (`cc_pre_tool_safety.py`, `--cc-hooks`), and GitHub Copilot
   (`copilot_pre_tool_safety.py`, `--copilot-hooks`), plus the universal
   `.githooks/pre-commit` quality gate for every tool's commits.
2. **Rule-driven**: managed adapter files and native command/slash packs for
   Cursor, Codex, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo,
   Goose, and Qwen.
3. **Prompt-only**: `AGENTS.md` at the repo root for every other reader
   (Aider, Zed, Amp, Devin, Factory, Jules, Warp, OpenCode).

The single deny vocabulary is kept in parity with the Antigravity grants
example by a deterministic selftest assertion.

## Consequences

One engine, honest per-tool guarantees, and a compatibility matrix that says
exactly what each tier enforces. Cost: three bridge payload adapters to
maintain and fuzz-test, and prompt-tier compliance depends on instruction
following rather than interception.
