# Tool adapters

These templates are rendered into the **application repository** by `install_tool_adapters.py` (`{{PRODUCT}}`, `{{PY}}`, `{{ASSEMBLE}}`, `{{UNIT_TEST}}`, `{{DEVICE_POLICY}}`, `{{GIT_POLICY}}`, `{{PM_TRIGGER}}`, `{{PM_LANG_NOTE}}`).

| File written at app root | Purpose |
|---|---|
| `GEMINI.md` | **Google Antigravity** (Official Primary Target — paired with `.agents/hooks.json` and `.agents/agents/*/agent.md`) |
| `AGENTS.md` | Universal standard `AGENTS.md` CLI fallback |
| `.agents/agents/*/agent.md` | Native Antigravity subagent definitions (`bug-test-reviewer-agent`, `security-perf-reviewer-agent`, `arch-regression-reviewer-agent`, `spec-compliance-agent`, `qa-diagnostics-agent`, `android-ui-expert-agent`, `harness-scout-agent`) |

Canonical rules remain `.agents/rules/harness-rules.md`. Optional global Antigravity configuration examples live in `gemini-runtime/` alongside these canonical adapter templates.
