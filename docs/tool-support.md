# Tool support

One engine. Many entry files. Setup writes adapters **only for the tools the developer selects** (`--tools`). Re-run the installer with a new list to add another tool later.

Canonical rules: `.agents/rules/harness-rules.md`.  
Installer: `$PY .agents/scripts/install_tool_adapters.py`.

`AGENTS.md` is always written. `.claude/agents/*.md` is generated only when `claude` is selected. Previously managed adapters for tools that were **not** selected are deleted (unless `--keep-extra-adapters`).

## What actually runs

| Capability | Where it lives | Who enforces it |
|---|---|---|
| Review protocol, git, device, architecture | `.agents/rules/harness-rules.md` | Every tool, via adapters |
| Live Gradle + heartbeat + staleness advisory | `.agents/scripts/run_gradle_task.py` | Same Python on every tool |
| Device install/launch | `.agents/scripts/run_device.py` | Same Python on every tool |
| Assemble barrier (5 `*_PASS` + matching evidence) | `.agents/hooks.json` + `pre_tool_safety.py` | **Antigravity** (runtime hook), **Claude Code** (`PreToolUse` bridge), and **GitHub Copilot** when `--copilot-hooks` is installed. Others: follow `AGENTS.md` |
| Staged Pre-Commit Quality Gate | `.agents/scripts/pre_commit_gate.py` (`.githooks/`) | Universal across all tools via Git |
| 11 Native Slash Command Packs | `.claude/commands/`, `.github/prompts/`, `.codex/prompts/` | Claude Code, GitHub Copilot, OpenAI Codex |
| Reviewer & Specialist prompts | `.agents/subagents/*.json` | Claude Code also gets `.claude/agents/*.md` |

Do **not** copy `~/.gemini` hostnames, tokens, or `local.properties` `sdk.dir`.

Do **not** overwrite `.aider.conf.yml`, Continue user config, unrelated MCP configs, `kilo.jsonc`, or `~/.qwen`. Zoho Sprints is the exception: `install_zoho_mcp.py` may merge `zoho-sprints` into this checkout’s `.agents/mcp_config.json` and `.cursor/mcp.json` (command + config **path** only, never tokens). It does not write `~/.gemini`.

## Adapter matrix

| Tool | Files written at the Android repo root | Enforcement |
|---|---|---|
| **Any agent that reads `AGENTS.md`** (Codex, Cursor, Copilot, Windsurf, Aider, Zed, Amp, Devin, Factory, Jules, Warp, Roo, VS Code, OpenCode) | `AGENTS.md` | Prompt |
| **Claude Code** | `CLAUDE.md` (`@AGENTS.md`), `.claude/agents/*.md`, `.claude/commands/*.md`, `.claude/settings.json` | Prompt + named agents + PreToolUse bridge |
| **Google Antigravity** | `GEMINI.md` + `.agents/hooks.json` | Prompt; **hook barrier in Antigravity** |
| **OpenAI Codex CLI** | `AGENTS.md` + `CODEX.md` + `.codex/prompts/*.md` | Prompt + native prompt commands |
| **GitHub Copilot / VS Code** | `.github/copilot-instructions.md` + `.github/prompts/*.prompt.md`; optional `.github/hooks/*.json` | Prompt + native prompt files; optional native `preToolUse` bridge |
| **Windsurf** | `.windsurf/rules/android-harness.md` (`trigger: always_on`) + `.windsurfrules` | Prompt |
| **Cline** | `.clinerules` | Prompt |
| **Roo Code** | `.roo/rules/android-harness.md` | Prompt |
| **Amazon Q Developer** | `.amazonq/rules/android-harness.md` | Prompt |
| **Continue** | `.continue/rules/android-harness.md` | Prompt |
| **JetBrains Junie** | `.junie/guidelines.md` | Prompt |
| **Kilo Code** | `.kilocode/rules/android-harness.md` | Prompt |
| **Goose** | `.goosehints` + `AGENTS.md` | Prompt |

Aider, Zed, Amp, Devin, Factory, Jules, Warp, and OpenCode pick up `AGENTS.md` with no extra file. Do not add `.cursorrules` (Cursor legacy; `.mdc` is the current file). Do not add `CONVENTIONS.md` (Aider can already read `AGENTS.md`; that filename often belongs to humans).

---

## Recommended Models by Assistant (Setup vs Daily)

| Assistant / IDE | Recommended for Setup & Porting (Tier-1 Reasoning) | Recommended for Daily Work (Coding & 5-Leaf Review) |
| :--- | :--- | :--- |
| **Google Antigravity** | `Gemini 3.1 Pro (Deep Think)` | `Gemini 3.7 Flash (Thinking)` |
| **Cursor** | `Claude Opus 5` / `GPT-5.6 Sol` / `Claude 3.7 Sonnet (Thinking)` | `Composer 2.5` / `Claude Sonnet 5` / `Grok 4.6` |
| **Claude Code** | `Claude Opus 5 (Adaptive Thinking)` / `Claude 3.7 Sonnet (Thinking)` | `Claude Sonnet 5` |
| **GitHub Copilot** | `Claude 3.7 Sonnet (Thinking)` / `GPT-5.6 Sol` | `Claude Sonnet 5` / `GPT-5 mini` |
| **OpenAI Codex CLI** | `GPT-5.6 Sol` / `OpenAI o3` | `GPT-5.5` / `gpt-oss-120b` |
| **Windsurf (Codeium)** | `Claude 3.7 Sonnet (Thinking)` / `Claude Sonnet 5` | `Cascade Base` / `Claude 3.7 Sonnet` |
| **Cline & Roo Code** | `Claude Opus 5` / `DeepSeek-V4 Pro` / `DeepSeek-R1` | `Gemini 3.7 Flash Thinking` / `DeepSeek-V4 Flash` |
| **Continue / Kilo / Goose** | `DeepSeek-R1` / `Claude 3.7 Sonnet` | `Qwen 2.5 Coder 32B` (Local) / `Claude Sonnet 5` |
| **Amazon Q Developer** | `Amazon Q Developer Pro Engine` | `Amazon Q Developer Default` |
| **JetBrains Junie** | `Junie Core Engine` | `Junie Core Engine` |

## Adding a tool later

Re-run the installer with the **new** `--tools` list (include tools you still use, plus the one you are adding). Example: you had Cursor + Gemini; later you add Claude Code:

```
{{PY}} .agents/scripts/install_tool_adapters.py --product <name> --py <python|python3> --assemble :<module>:assembleDebug --device-policy allow|physical-only --git-policy never|agent-may-commit --tools cursor,gemini,claude
```

`--tools all` writes every row in the matrix. `--keep-extra-adapters` writes the selected files without deleting the others.

The staged git gate is installed by default. Use `--no-git-gate` only when the
project has an intentionally managed replacement hook. Add `--copilot-hooks`
when Copilot is selected and its native `preToolUse` enforcement is desired.

Also re-run after changing Python command, assemble task, device policy, or git policy.

## Changing setup answers after install

Setup answers are recorded in `.harness-setup/answers.json` (human-readable summary:
`.harness-setup/SETUP_ANSWERS.md`). To change them later:

1. **Re-run the wizard (recommended)**:

   ```
   {{PY}} .agents/scripts/setup_wizard.py ask --repo . --lang en|ar
   ```

   Previous answers are pre-filled: each question shows `(current)` next to the
   recorded choice. Press **Enter** to keep it, type a new number to change it.

2. **Non-interactive (via chat)**: run
   `{{PY}} .agents/scripts/setup_wizard.py questions --repo . --lang en|ar`,
   answer only the JSON questions, then
   `{{PY}} .agents/scripts/setup_wizard.py write --repo . --answers-json <file>`.

3. **Manual edit**: edit `.harness-setup/answers.json` directly, then re-run
   `install_tool_adapters.py` for the values that feed adapters (`--py`,
   `--assemble`, `--device-policy`, `--git-policy`, `--tools`) and update the
   matching `_product.py` fields (`ALLOW_EMULATOR`, `ASSEMBLE_TASK`,
   `ACTIVE_FLAVOR`, `PM_PROVIDER`).

After any change, verify with `{{PY}} .agents/scripts/harness_doctor.py`. The
**Install Consistency** dimension fails with a remediation hint whenever
answers drift from `_product.py` or the adapters on disk.

## Tools without subagent spawn

If the product cannot launch `bug-reviewer-agent` as a child, `AGENTS.md` still requires the five leaves: open each JSON under `.agents/subagents/`, follow `system_prompt` against the same `HARNESS_REVIEW_PACKAGE`, sequential is allowed. Assemble only after `BUG_PASS` `CONVENTION_PASS` `SECURITY_PASS` `PERF_PASS` `REGRESSION_PASS`, each accompanied by the evidence footer `EVIDENCE pkg=<HARNESS_PACKAGE_SHA256_12> cites=<n>` (strict evidence mode).

---

## One-Click Lifecycle Prompt URLs

For any supported AI assistant, use the following raw GitHub URLs:
- **Install**: `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.10.8/docs/install-prompt.md`
- **Update**: `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.10.8/docs/update-prompt.md`
- **Diagnostic Doctor**: `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.10.8/docs/diagnostic-prompt.md`
- **Rollback**: `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.10.8/docs/rollback-prompt.md`
