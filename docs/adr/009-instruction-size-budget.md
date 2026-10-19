# ADR-009: Local instruction growth budget

Status: Accepted by the maintainer on 2026-10-13.

## Context

Commit `aeab304` (v1.0.52, 2026-09-19) introduced a 12,000-character
regression limit after reducing the kernel plus Codex adapter from 32,519 to
11,371 characters. Its changelog explains the reduction of always-loaded
instructions, but the repository contains no benchmark or documented derivation
establishing 12,000 as an optimal or necessary threshold.

## Decision

Use a maintainer-selected ceiling of 32,000 Unicode characters, counting
`agents/rules/harness-rules.md` plus `agents/tool-adapters/AGENTS.md.template`.
This is a local regression budget for instruction growth. It is not a token
count, host context-window limit, performance guarantee, or empirical optimum.
It does not measure the complete prompt supplied by any host.

For Antigravity, count `agents/tool-adapters/GEMINI.md.template` separately with
a ceiling of 40,000 Unicode characters. Commit `1b95e9c` introduced its former
23,000-character check without a documented benchmark or threshold derivation.
On 2026-10-15 and 2026-10-19 the maintainer authorized justified increases to
preserve full instruction clarity and ample headroom for useful instruction changes
(such as per-reviewer active model reporting in chat). It remains a deliberately
chosen maintenance budget, not an Antigravity restriction or a measured
performance optimum.

Keep useful instructions explicit. Load detailed domain guidance through routed
skills, and review duplication and clarity before expanding always-loaded text.
Do not pad instructions to fill the budget or remove meaningful requirements
merely to make the size check pass. Future changes to the ceiling should document
their rationale; claims about model performance require actual measurements.

## Consequences

The deterministic size check remains a maintenance signal. The higher ceiling
does not change approval, routing, runtime enforcement, or evidence gates.
