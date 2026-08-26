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

## Phase 5 — Modular Architecture & Enterprise Governance
- [x] Monolith splits: `setup_wizard.py` modularized into `agents/scripts/wizard/` (discovery, i18n, questions)
- [x] Monolith splits: `harness_doctor.py` modularized into `agents/scripts/doctor/` (models, engine)
- [x] Monolith splits: `zoho_sprints/server.py` modularized into `_client.py`, `_dns.py`, and `_formatter.py`
- [x] Reviewer conflict adjudication model & ADR-006 (`docs/adr/006-reviewer-conflict-adjudication.md`)
- [x] Structured findings schema & severity classification (`HARD_BLOCKER` vs `SOFT_FINDING`) in `_hook_state.py` and `pre_tool_safety.py`

## Future

- Signed release artifacts (Sigstore/cosign) for the kit distribution
- Native hook bridges for Windsurf / Cursor / Codex when their hook protocols ship
- Python 3.14 CI coverage extension
- Opt-in telemetry to automate benchmark collection

