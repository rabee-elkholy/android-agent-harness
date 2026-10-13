# ADR-009: Local instruction growth budget

Status: Accepted by the maintainer on 2026-10-13.

## Context

Commit `aeab304` (v1.0.52, 2026-09-19) introduced a 12,000-character
regression limit after reducing the kernel plus Codex adapter from 32,519 to
11,371 characters. Its changelog explains the reduction of always-loaded
instructions, but the repository contains no benchmark or documented derivation
establishing 12,000 as an optimal or necessary threshold.

## Decision

Use a maintainer-selected ceiling of 20,000 Unicode characters, counting
`agents/rules/harness-rules.md` plus `agents/tool-adapters/AGENTS.md.template`.
This is a local regression budget for instruction growth. It is not a token
count, host context-window limit, performance guarantee, or empirical optimum.
It does not measure the complete prompt supplied by any host.

Keep useful instructions explicit. Load detailed domain guidance through routed
skills, and review duplication and clarity before expanding always-loaded text.
Do not pad instructions to fill the budget or remove meaningful requirements
merely to make the size check pass. Future changes to the ceiling should document
their rationale; claims about model performance require actual measurements.

## Consequences

The deterministic size check remains a maintenance signal. The higher ceiling
does not change approval, routing, runtime enforcement, or evidence gates.
