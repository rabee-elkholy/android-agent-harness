# Automated Multi-Agent Architecture

Canonical protocol: `.agents/rules/harness-rules.md`. This file does not add policy.

## Delivery gate (mandatory)

One `invoke_subagent` call, five leaves, same `HARNESS_REVIEW_PACKAGE`:

- `bug-reviewer-agent`
- `convention-reviewer-agent`
- `security-reviewer-agent`
- `perf-anr-guardian-agent`
- `regression-impact-reviewer-agent`

Verdicts: `BUG_PASS` / `CONVENTION_PASS` / `SECURITY_PASS` / `PERF_PASS` / `REGRESSION_PASS`.

`code-review-guard-agent` is retired as the delivery gate. `LGTM` is not a delivery verdict.

## On-demand

- `qa-diagnostics-agent` — device forensics
- `android-ui-expert-agent` — Compose + XML (alias: `compose-ui-expert-agent`)
- `test-quality-reviewer-agent` — unit & UI test quality verification (alias: `test-reviewer-agent`)

All subagents: `Workspace="inherit"`, `model="inherit"`, write tools off.

Identical package content is rejected on re-review; regenerate after fixes.
