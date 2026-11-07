# ADR 024: Opt-In Lean Review Profile & Installed Client Payload Slimming

- **Status:** Accepted
- **Date:** 2026-11-07
- **Deciders:** Rabee Elkholy, Architecture Engineering

## Context

1. **Reviewer Latency & Cost on Bounded Low/Medium Tasks:**
   By default (`REVIEW_PROFILE = "standard"`), `T1_LOW_RISK` (non-micro) and `T2_FEATURE` tasks route both `bug-test-reviewer-agent` and `arch-regression-reviewer-agent`. On solo or small-team projects with tight token budgets, running two specialist subagents on every single-module bounded feature doubles reviewer token cost and latency, even when no architectural, multi-module, persistence, or security surfaces are touched.
   Similarly, small low-risk single-module code edits (`<= 2` files, `<= 40` lines) that include unit test verification previously always escalated to `T2_FEATURE` instead of qualifying for the fast `MICRO` lane.

2. **Installed Client `.agents/scripts/` Payload Bloat:**
   The kit repository contains 30+ internal test suites (`_*_selftest.py`, totaling ~1.6 MB) used by CI and `harness_cli.py selftest`. Only `_hook_selftest.py` is invoked inside client repositories by `ensure_hook_selftest.py` and `harness_doctor.py`. Copying all 30+ selftest suites into every client project's `.agents/scripts/` directory slowed down `install`, `update`, and syntax compilation checks without adding runtime value to the client checkout.

## Decision

1. **Opt-In `REVIEW_PROFILE = "lean"` (Default `"standard"`):**
   - `_product.py` and `_installer_config.py` define `REVIEW_PROFILE = "standard"` by default (overridable via `answers.json` `"review_profile": "lean"` or `HARNESS_REVIEW_PROFILE=lean`).
   - When `REVIEW_PROFILE == "lean"`:
     - **Single-Reviewer Consolidation for Bounded `T1`/`T2`:** When a task is in `T1_LOW_RISK` or `T2_FEATURE`, single-module (`changed_modules_count <= 1`), non-architectural (`planning_depth != "ARCHITECTURAL"` and `architecture_intent not in ("MIGRATION", "NEW_SUBSYSTEM")`), and touches no critical, permission, build, native, device, or persistence surfaces, `arch-regression-reviewer-agent` is consolidated into `bug-test-reviewer-agent` (recording `"LEAN_PROFILE_CONSOLIDATED"` in the policy explanation).
     - **Bounded Micro-Lane Eligibility:** `_micro_eligible()` permits small (`<= 2` files, `<= 40` lines), single-module, low/medium-severity edits restricted to `{"DOCS", "LOCALIZATION", "RESOURCE_UI", "COMPOSE_UI", "XML_UI", "BUSINESS_LOGIC"}` to qualify for the `MICRO` lane (while still requiring unit tests and assemble gates via `TEST_SURFACES`).
   - High-risk tiers (`T3_SUBSYSTEM`, `T4_DATA_DEVICE`, `T5_CRITICAL`) and security/auth/billing surfaces remain completely unchanged under both `"standard"` and `"lean"`.

2. **Exclude Non-Hook `_*_selftest.py` from Installed Client Checkouts:**
   - The kit's `agents/release_checksums.json` continues to verify every file in `agents/` for kit integrity and CI suites.
   - During `lifecycle._install_engine()` and `repair.repair_repository()`, `_*_selftest.py` files except `_hook_selftest.py` are excluded from the client `.agents/scripts/` copy.
   - `HarnessDoctor._released_scripts()` and `CORE_SCRIPTS` check only client-shipped runtime scripts (plus `_hook_selftest.py`).

## Consequences

- **Zero Breaking Changes:** Default `REVIEW_PROFILE = "standard"` preserves 100% of existing routing and micro-lane behavior.
- **50% Reviewer Token Savings on Opt-In:** Projects enabling `REVIEW_PROFILE = "lean"` cut reviewer subagent calls in half on bounded single-module `T1`/`T2` tasks and fast-track tiny (`<= 2` files, `<= 40` lines) tested fixes.
- **~1.6 MB Lighter Client Installs:** Client `.agents/scripts/` directories contain only production scripts and `_hook_selftest.py`, speeding up `install`, `update`, and bytecode compilation.
