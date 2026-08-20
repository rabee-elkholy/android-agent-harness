# Tool support

One engine. Many entry files. Setup writes adapters **only for the tools the developer selects** (`--tools`). Re-run the installer with a new list to add another tool later.

Canonical rules: `.agents/rules/harness-rules.md`.  
Installer: `$PY .agents/scripts/install_tool_adapters.py`.

`AGENTS.md` is always written. `.claude/agents/*.md` is generated only when `claude` is selected. Previously managed adapters for tools that were **not** selected are deleted (unless `--keep-extra-adapters`).

## What actually runs

| Capability | Where it lives | Who enforces it |
|---|---|---|
| Review protocol, git, device, architecture | `.agents/rules/harness-rules.md` | Every tool, via adapters |
| Live Gradle + heartbeat | `.agents/scripts/run_gradle_task.py` | Same Python on every tool |
| Device install/launch | `.agents/scripts/run_device.py` | Same Python on every tool |
| Assemble barrier (5 `*_PASS`) | `.agents/hooks.json` + `pre_tool_safety.py` | **Antigravity only** (automatic). Others: follow `AGENTS.md` |
| Reviewer prompts | `.agents/subagents/*.json` | Claude Code also gets `.claude/agents/*.md` |

Do **not** copy `~/.gemini` hostnames, tokens, or `local.properties` `sdk.dir`.

Do **not** overwrite `.aider.conf.yml`, Continue user config, MCP configs, `kilo.jsonc`, or `~/.qwen`. This installer only writes the harness-owned paths below.

## Adapter matrix

| Tool | Files written at the Android repo root | Enforcement |
|---|---|---|
| **Any agent that reads `AGENTS.md`** (Codex, Cursor, Copilot, Windsurf, Aider, Zed, Amp, Devin, Factory, Jules, Warp, Roo, VS Code, OpenCode) | `AGENTS.md` | Prompt |
| **Claude Code** | `CLAUDE.md` (`@AGENTS.md` first line) + `.claude/agents/*.md` | Prompt + named agents |
| **Gemini CLI / Antigravity** | `GEMINI.md` + `.agents/hooks.json` | Prompt; **hook barrier in Antigravity** |
| **OpenAI Codex CLI** | `AGENTS.md` + `CODEX.md` | Prompt |
| **Qwen Code** | `QWEN.md` (`@AGENTS.md` first line) + `AGENTS.md` | Prompt |
| **Cursor** | `AGENTS.md` + `.cursor/rules/android-harness.mdc` (`alwaysApply: true`) | Prompt |
| **GitHub Copilot / VS Code** | `.github/copilot-instructions.md` + `.github/instructions/android-harness.instructions.md` | Prompt |
| **Windsurf** | `.windsurf/rules/android-harness.md` (`trigger: always_on`) + `.windsurfrules` | Prompt |
| **Cline** | `.clinerules` | Prompt |
| **Roo Code** | `.roo/rules/android-harness.md` | Prompt |
| **Amazon Q Developer** | `.amazonq/rules/android-harness.md` | Prompt |
| **Continue** | `.continue/rules/android-harness.md` | Prompt |
| **JetBrains Junie** | `.junie/guidelines.md` | Prompt |
| **Kilo Code** | `.kilocode/rules/android-harness.md` | Prompt |
| **Goose** | `.goosehints` + `AGENTS.md` | Prompt |

Aider, Zed, Amp, Devin, Factory, Jules, Warp, and OpenCode pick up `AGENTS.md` with no extra file. Do not add `.cursorrules` (Cursor legacy; `.mdc` is the current file). Do not add `CONVENTIONS.md` (Aider can already read `AGENTS.md`; that filename often belongs to humans).

## Adding a tool later

Re-run the installer with the **new** `--tools` list (include tools you still use, plus the one you are adding). Example: you had Cursor + Gemini; later you add Claude Code:

```
{{PY}} .agents/scripts/install_tool_adapters.py --product <name> --py <python|python3> --assemble :<module>:assembleDebug --device-policy allow|physical-only --git-policy never|agent-may-commit --tools cursor,gemini,claude
```

`--tools all` writes every row in the matrix. `--keep-extra-adapters` writes the selected files without deleting the others.

Also re-run after changing Python command, assemble task, device policy, or git policy.

## Tools without subagent spawn

If the product cannot launch `bug-reviewer-agent` as a child, `AGENTS.md` still requires the five leaves: open each JSON under `.agents/subagents/`, follow `system_prompt` against the same `RASHAQA_REVIEW_PACKAGE`, sequential is allowed. Assemble only after `BUG_PASS` `CONVENTION_PASS` `SECURITY_PASS` `PERF_PASS` `REGRESSION_PASS`.
