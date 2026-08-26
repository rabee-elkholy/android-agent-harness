# Roadmap

## Phase 1 — Supply-chain integrity
- [x] Pin-to-tag CLI provisioning, never floats to `main` (v0.9.0)
- [x] Threat-model table in SECURITY.md mapping attack classes to proving tests (v0.10.0)
- [x] One-click prompt URLs pinned to an immutable release tag with tamper-evident checksum headers
- [x] Dedicated threat model (`docs/threat-model.md`) covering prompt injection, config tampering, traversal, exfiltration, and MCP poisoning
- [x] SECURITY.md and threat-model cross-linking without duplication
- [x] Engine hardening: adb exfiltration verbs device-bound, `cmd package clear|uninstall` denied
- [x] GitHub Actions pinned to immutable commit SHAs

## Phase 2 — Machine-verifiable evidence
- [x] `verdict.json` schema with task id, git SHA, per-file hashes, leaves, findings, and timestamps
- [x] Review gate emits the verdict artifact alongside the text evidence footer convention
- [x] `android-harness verify` subcommand validating artifacts against actual repo state
- [x] `explain` reads the installed checkout's audit log

## Phase 3 — Contributor onboarding & truth-in-docs
- [x] README restructured under 150 lines with zero-loss relocation into `docs/`
- [x] Tool -> template -> enforcement-tier mapping table
- [x] macOS CI coverage
- [x] Architecture decision records (`docs/adr/`)
- [x] Contributor recipes: reviewer / policy rule / tool adapter (`docs/recipes/`)
- [x] Compatibility matrix (`docs/compatibility-matrix.md`)
- [x] Issue template YAML repair

## Phase 4 — Proof scaffold
- [x] Committed golden Android fixture projects regenerated from the fixture generator
- [x] Benchmark task list, metrics collector, and results template (`docs/benchmark/`)
- [x] Demo-media placeholder section with recording shot list (`docs/media/`)

## Future

- Split monolith modules (`_hook_selftest.py`, `setup_wizard.py`, `harness_doctor.py`, `agents/mcp/zoho_sprints/server.py`) — TODO markers in place at each split point
- Formal conflict-resolution workflow for reviewer disagreements (adjudication rules, escalation criteria)
- Signed release artifacts (Sigstore/cosign) for the kit distribution
- Per-leaf structured findings (JSON) in reviewer replies instead of transcript parsing
- Native hook bridges for Windsurf / Cursor / Codex when their hook protocols ship
- Python 3.14 CI coverage extension
- Opt-in telemetry to automate benchmark collection
