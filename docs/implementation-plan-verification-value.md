# Implementation plan: acceptance evidence, reusable journeys, and local task metrics

Status: implementation authorized by the maintainer's "Start" instruction on 2026-10-07. Publication and Git mutations remain separately authorized.

Approved amendment on 2026-10-07: after successful app installation and launch, an approved complete executable walkthrough offers the existing manual PASS/FAIL responses plus Run Automatically. The developer selects one method; complete automatic PASS replaces manual repetition. The maintainer explicitly approved this replacement after discussion of the previous duplicate manual requirement. See ADR 009 for eligibility, evidence integrity, manual fallback, and unchanged sensitive approval.

## Outcome and scope

Deliver three capabilities without replacing existing lifecycle, risk policy, review proof, or evidence authority:

1. Show which approved acceptance criteria have valid, relevant verification evidence.
2. Save and explicitly replay bounded Android verification journeys against the current installed artifact.
3. Explain task time, retries, and developer interventions through an on-demand local report.

The stability prerequisite is a fresh certification of existing public lifecycle paths. Historical failed benchmark scenarios are evidence gaps, not proof that the current checkout retains their original defects.

Excluded: Jev or other model providers, automatic Git operations, live tracker writes, cloud telemetry, a dashboard/web server, automatic test suppression, release publication, and an unrestricted device automation language.

## Architecture decisions

- Keep Python runtime standard-library-only. Reuse `EvidenceStore` and its append-only attempt validation.
- Keep the existing router and six-tier review policy as the only lifecycle and verification authorities. Add policy fields only where necessary; do not introduce a second gate router.
- Treat generated reports as read-only views. They cannot create PASS, change approval, or repair authoritative evidence.
- Preserve old plans, approvals, setup answers, evidence records, and active tasks. Never retroactively rewrite an approved payload or its hash.
- Optional features remain off for old installations. Updating does not enable features or amend active task scope silently.
- Device replay is subordinate to current device policy and review-before-assemble/install ordering. Partial replay retains human sign-off. The approved complete-walkthrough choice can replace manual sign-off with a separately recorded developer-selected automatic PASS, never with agent confidence or an environment failure.
- Diagnostics may fail gracefully. Required evidence persistence, integrity, and freshness failures remain blocking.
- New public commands and file paths below are proposed contracts, not existing functionality. Final naming must agree across the launcher, command catalog, adapters, and documentation.

## Phase 0: establish stability and performance baselines

Inspect lifecycle, evidence, installer/update, and device contracts; record focused seams and affected tests before edits.

Run the existing deterministic suite, syntax validation, and release validation. Record failures without silently attributing them to this proposal. Exercise fixtures for draft, approval, phases, revise, review corrections, verification, reopen, handoff, and delivery.

Use the benchmark status document to define a fresh frozen-commit certification run, especially T3, T8, T9, and T10. Real Android certification belongs in a separate client checkout with existing developer/device authorization; do not run Gradle or ADB against the harness kit. If certification is unavailable, record the unverified paths and keep broad enablement blocked.

Capture representative small and large fixture workloads for task status, task context, prepare-verification, final verification, and setup/update. Measure enabled and disabled paths on the same machine with repeated alternating runs. Separate cold and warm measurements.

Exit: known baseline failures classified, protected paths represented in regression tests, and reproducible performance fixtures recorded. Existing defects receive the smallest RED/GREEN repair within this scope when they obstruct these integrations; unrelated product changes require separate scope.

## Phase 1: shared compatibility and evidence contracts

- Define independent versioned schemas for criteria, journeys, and metrics. Bound input sizes and collection counts in named constants with boundary tests.
- Extend plan validation only with optional versioned fields. Legacy plan hashing uses the unchanged legacy payload; new fields join approval hashing only for new or explicitly revised plans that opt in.
- Reuse existing atomic writes and locks. Never append to authoritative evidence with a custom unlocked writer.
- Pin approved semantic inputs: criterion definitions, selected journey definitions and hashes, and permitted device actions. A definition change invalidates its prior results; a material contract change follows existing revise authority.
- Store reusable definitions as project-owned configuration outside immutable managed engine source. Resolve the exact path through current installer ownership, delivery manifest, and scope rules before implementation. Include definitions in appropriate identity bindings and preserve them on update/uninstall.
- Keep generated reports and operational metrics outside delivery inputs. Audit new files for accidental manifest churn.
- Add setup choices only through the canonical wizard schema, normalization, generated configuration, and chat installer contract. Avoid new questions where a safe default or explicit task option suffices.

Exit: old/new fixtures pass, active-task upgrades preserve identities, interrupted writes recover, and no new lifecycle state exists.

## Phase 2: approved criteria mapped to evidence

### Data and public behavior

Each criterion has a stable ID, observable expected behavior, verification method, and approved required/advisory status. Keep scope proportional: trivial tasks need no forced matrix; feature tasks use a small set of meaningful criteria derived from the request and shown with the plan.

Proposed public contracts:

- `task coverage --task-id <id> [--json]`: read-only coverage view.
- `task bind-evidence`: validated association of a criterion with a specific existing evidence record and, where applicable, exact test case or structured reviewer finding.

Reuse existing gate producers to expose executed test-case identities and outcomes. Prefer bounded summaries generated when a gate runs; do not repeatedly parse every XML report during status queries.

Coverage statuses: VERIFIED, FAILED, MISSING, STALE, NEEDS_HUMAN, and NOT_APPLICABLE. NOT_APPLICABLE requires a reason and authority appropriate to the approved criterion; it cannot bypass an existing required gate.

### Proof rules

- Test coverage requires the named test to have executed successfully in the bound current run. A successful module gate alone cannot establish that a particular requirement was tested.
- An association is a claim about relevance, not semantic proof. Relevant tests and assertions remain subject to existing test-quality/completeness review. Do not advertise machine-verified semantic coverage.
- Reviewer coverage requires trusted existing reviewer execution and an explicit criterion reference. Lead-authored text cannot manufacture reviewer approval.
- Manual coverage requires an existing authorized developer receipt explicitly identifying the checked criteria. A blanket sign-off must not silently certify every criterion.
- Evidence binds task, approved criterion definition, run, snapshot, change set, producer, and the latest valid attempt. Wrong-run, corrupt, stale, or superseded PASS is rejected.
- Missing required coverage blocks only tasks that explicitly approved the new coverage contract. Advisory or legacy tasks retain existing behavior and display gaps without acquiring retroactive gates.
- Coverage adds no tests or reviewers independently of central policy. An explicitly approved test requirement must be represented by central policy; incompatible device-disabled requirements must be resolved before approval.

Exit: one missing required criterion prevents completion of an opted-in task; irrelevant, stale, or forged references cannot pass; legacy tasks complete unchanged; coverage reports remain bounded and read-only.

## Phase 3: reusable device verification journeys

### Definition and authorization

A journey has an ID/version, purpose, mapped criterion IDs, module/variant applicability, prerequisites, explicit permitted effects, bounded steps, and observable assertions. Use strict JSON initially; avoid adding YAML parsing or arbitrary expression execution.

Start with navigate, tap, input via secret references, bounded wait, and positive/negative UI assertions. Prefer resource IDs and content descriptions; permit locale-aware text only when necessary. Ambiguous selectors fail with an actionable reason. Coordinate replay is excluded from the initial reliable path.

Definitions can be drafted from existing walkthroughs but remain unexecuted/unverified until reviewed and run. Reuse the current `_adb_core.py` selectively behind a small adapter, after auditing command construction, selector behavior, and timeouts. Its presence does not establish public replay readiness.

Proposed contracts: `journey validate`, `journey list`, and `journey run --id <id> --task-id <id>`. A task approves selected journeys and their effects once. Do not request approval per step.

No purchases, external account mutations, data clearing, uninstall, or uncontrolled shell execution in the initial action set. Merely labeling a journey a test does not authorize its side effects. Never modify app source to add test hooks without approved application scope.

### Execution and evidence

- Validate the entire definition before the first device action.
- Require verified APK/install/launch identity and the existing selected device policy. Recheck device identity and disconnection during execution.
- Bind results to definition hash, app artifact set, variant, device identity, relevant OS/locale, criterion IDs, and current run/snapshot.
- Record per-step outcomes and overall PASS/FAIL/ENV/STALE. Unsupported selectors, missing UI exposure, and interrupted execution cannot become PASS.
- Wait on conditions with deadlines; bound polling and total execution. Do not repeatedly rerun failed journeys until one happens to pass.
- Start replay only when explicitly selected for the task, after required reviews and installation. Do not add it to every status or verification query.
- Store bounded sanitized diagnostics. Screenshots are opt-in and captured selectively; avoid secrets and private user content. Retention never removes evidence of a live task.
- Keep manual walkthrough and sign-off available on every host. Unsupported automation degrades truthfully to manual requirements; do not silently mark replay complete.

Exit: deterministic fixtures cover success, wrong artifact, ambiguous/missing selector, false assertion, device loss, timeout, interruption, and changed definition. Separate authorized client certification demonstrates a reusable journey end to end; kit validation uses fake device transports only.

## Phase 4: local task metrics and on-demand reports

Proposed contract: `task metrics --task-id <id> [--json]`. Reuse workflow receipts, evidence attempts, and existing benchmark metric vocabulary before adding new events.

Report observed execution durations, review rounds, repeated gate attempts, explicit developer interventions, and classified blocker reasons. Distinguish active execution from waiting; task wall time is not developer working time. Concurrent reviewer durations must not be summed as elapsed time.

- Use monotonic duration within a process and UTC event timestamps for correlation. Preserve gaps and unknown attribution rather than guessing across restarts.
- Report token use or cost only when trusted host usage exposes it. Missing data is UNAVAILABLE, never zero or an estimate presented as measured fact.
- Add compact events only at meaningful operation boundaries. No network traffic, background process, periodic full-tree scan, or per-token logging.
- Metrics writes are best-effort diagnostics and cannot abort a valid lifecycle operation. Keep metrics failures separate from required evidence failures.
- Bound events and report input; cap or rotate only diagnostic history. Never prune live authoritative evidence to meet a metric quota.
- Reuse benchmark parsing/rendering logic through a runtime-safe standard-library module if needed; installed runtime must not import `scripts_dev`.
- Keep reports local and generated on demand. No automatic optimization, reviewer reduction, or gate skipping based on metrics.

Exit: metrics match fixture timelines, handle overlap/restarts and partial files, expose unavailable fields, contain no secrets, and leave delivery outcomes unchanged even when diagnostic writes fail.

## Phase 5: integration, compatibility, and rollout

Implement in this order: baseline and contracts; diagnostic metrics; criteria reporting; explicitly approved required coverage; validated manual journey definitions; explicit automated replay. This order provides measurements before introducing new proof consumers.

Test the complete public path: approved feature -> implementation -> gate results -> criteria binding -> review -> assemble/install -> selected journey/manual receipt -> final verification -> reopen after a source edit. Old evidence must become stale; the router must issue an actionable next operation and reach terminal completion after fresh verification.

Also cover phases, partial criterion fulfillment, revised criteria, handoff lineage, interrupted update, uninstall ownership, legacy approvals, malformed schemas, path traversal, oversized inputs, and concurrent result publication. Compare outcomes with optional features disabled.

Update public command catalog, launch dispatch, rules, prompts, host adapters, installer/update docs, and relevant ADRs together. Preserve Zoho behavior; no live mutation without `update zoho`.

Rollout defaults: metrics local and on demand; structured coverage opt-in for new tasks; replay off unless selected. Do not silently promote experimental contracts to mandatory behavior for existing users.

## Performance acceptance

No promise of zero overhead: additional checks do real work. Enforce bounded work and measure incremental overhead.

Deterministic requirements:

- Feature-off task status performs zero new metrics/journey scans and no network or device calls.
- Ordinary status never runs a journey, rebuilds coverage history, or scans all historical tasks.
- Coverage reads only current criteria and referenced current-run summaries; work scales with bounded input rather than repository history.
- Metrics collection adds constant bounded work at operation boundaries; report generation reads only the selected bounded task history.
- No new full-repository source scan; reuse existing graph, manifest, and test indexes.

Proposed measured budget: feature-off warm median regression <= 5%; enabled bookkeeping <= 5% of a representative task's execution time, excluding explicitly selected device replay. Establish absolute budgets from Phase 0 to handle tiny commands where percentage noise dominates. Compare repeated runs and p95; investigate sustained regressions before rollout. Wall-clock thresholds are controlled benchmark acceptance, not brittle unit-test assertions.

## Validation and completion

For each behavior: smallest meaningful RED regression, GREEN implementation, neighboring focused checks, then canonical validation:

```text
python harness_cli.py selftest
python -m compileall -q harness_cli.py agents/scripts
python scripts_dev/validate_release.py
```

Run fixture-based kit checks without Gradle/ADB. Perform real device/build certification only in a separate authorized Android application checkout. An unavailable device is a stated certification gap, not a simulated success.

Required completion artifacts: regression tests, compatible schemas, current documentation/ADRs, measured overhead report, updated frozen-commit certification results, and no identified reachable router dead-end or proof bypass.

Exact-final-commit cross-platform CI must pass before claiming full release readiness. Commit/push/tag/publication require explicit maintainer Git/release authorization; absent authorization, leave changes unstaged and report local validation separately from CI.

## Recovery

Disable optional configuration to return new tasks to the established behavior. Do not disable required coverage or journeys inside an already approved task to evade failed verification; use existing authorized revision semantics. Preserve old evidence and do not rewrite approvals. Transactional update rollback remains the engine recovery path.

## Approval boundary

One explicit approval covers implementation of the full scope above and in-scope repairs, without phase-by-phase stops. Real external effects, application changes outside certification scope, Git operations, and release publication remain separately authorized boundaries. Material expansion requires a revised plan.
