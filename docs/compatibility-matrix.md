# Compatibility Matrix

## Operating systems

| OS | Support | Notes |
| :--- | :--- | :--- |
| Windows 10/11 | Supported (CI) | `python` preferred over the Store `python3` stub; `gradlew.bat`; path separators normalized in the engine |
| macOS | Supported (CI) | `python3`; `chmod +x gradlew` where needed |
| Linux (Ubuntu/Debian) | Supported (CI) | `python3`; POSIX hooks |

## Python

| Version | Status |
| :--- | :--- |
| 3.10 / 3.11 / 3.12 / 3.13 | Tested in CI on all three operating systems |
| 3.14+ | Untested - not blocked, but no CI coverage |

## AI tool enforcement tiers

Full per-tool template mapping: [Tool Support](tool-support.md#tool--template--enforcement-mapping).

| Tool | Entry files | Enforcement tier |
| :--- | :--- | :--- |
| Google Antigravity | `agents/hooks.json`, `GEMINI.md` | Hook-enforced (PreToolUse engine + PreInvocation reminder/selftest) |
| Claude Code | `CLAUDE.md`, `.claude/agents/*`, `.claude/commands/*`, `.claude/settings.json` | Hook-enforced (PreToolUse bridge, `--cc-hooks`) |
| GitHub Copilot / VS Code | `.github/copilot-instructions.md`, `.github/prompts/*`, `.github/hooks/*` | Hook-enforced (preToolUse bridge, `--copilot-hooks`) + rule-driven |
| Cursor | `.cursor/rules/android-harness.mdc` | Rule-driven |
| OpenAI Codex CLI | `AGENTS.md`, `CODEX.md`, `.codex/prompts/*` | Rule-driven + native prompt commands |
| Windsurf | `.windsurf/rules/android-harness.md`, `.windsurfrules` | Rule-driven |
| Cline / Roo Code | `.clinerules`, `.roo/rules/android-harness.md` | Rule-driven |
| Amazon Q / Continue / Junie / Kilo Code / Goose / Qwen Code | `.amazonq/`, `.continue/`, `.junie/`, `.kilocode/`, `.goosehints`, `QWEN.md` | Rule-driven |
| Aider, Zed, Amp, Devin, Factory, Jules, Warp, OpenCode | `AGENTS.md` | Prompt-only |

## Universal (all tools)

The staged pre-commit quality gate (`.githooks/pre-commit`, default ON,
`--no-git-gate` opt-out) fires for commits made by ANY agent or human,
independent of which assistant produced the change.

## Engine integrations

| Component | Transport | Notes |
| :--- | :--- | :--- |
| Zoho Sprints MCP | stdio JSON-RPC, kit-owned server | Credentials stay user-level (`~/.android-harness/zoho_sprints.json`), never in the repo |
| GitHub Projects | `gh` CLI adapter (`pm_github.py`) | Auth owned by `gh` itself; harness never reads tokens |
| Jira / Linear | upstream MCP registration playbooks (`agents/pm/mcp_registration.*.md`) | Developer-registered servers with user-level credentials |

## Verification

`_hook_selftest.py`, `_security_selftest.py`, and `preflight_check.py` run on
ubuntu/windows/macos x Python 3.10-3.13 in CI. The release-validation
workflow additionally re-runs on every pushed tag across all three OSes.
