# ADR 009: optional acceptance evidence, journeys, and local metrics

Status: accepted for implementation on 2026-10-07.

## Decision

Add an optional `verification_contract` field only to opted-in approved plans. Bind its schema-v1 criteria and embedded journeys through the existing approval payload. Legacy hashes remain unchanged. Existing central policy derives all added test/device/reviewer prerequisites, and the existing final verifier consumes evidence associations. No new task state or independent risk router is introduced.

Use the existing append-only EvidenceStore for criterion associations and replay results. Associations pin the approved contract and the exact source attempt. They prove provenance, not semantic completeness. Manual proof names explicitly checked criteria. Review proof requires independently verified, criterion-specific results.

Journeys are project-owned JSON definitions embedded at approval, outside managed engine source. A bounded runner validates every step before effects and requires verified install/artifact identity. Device execution is explicit; no new background service or general shell language exists.

Maintainer-approved amendment on 2026-10-07: a contract may declare `device_validation: "manual_or_automatic"` only when its journeys define the complete walkthrough, share one application, fit a combined 40-step/120-second budget, and have no required human-only criterion. Immediately after verified installation and launch, retain the existing manual PASS/FAIL question and add Run Automatically. Explicit selection executes all approved journeys and records a separate authoritative automatic result. Complete automatic PASS replaces manual repetition, with criterion associations recorded automatically. Manual PASS explicitly identifies all checked journey criteria and requires no replay. ENV offers manual fallback; actual FAIL requires diagnosis. Sensitive snapshot approval remains a separate developer decision. Legacy tasks and partial replays retain their established sign-off contract.

Local metrics are optional diagnostics outside delivery authority. Enable collection through the process environment; emit only compact operation-boundary records. Fail gracefully on diagnostic writes, expose unavailable measurements honestly, and never use timings to suppress required checks.

## Consequences

Old installations and active tasks are not migrated or silently enabled. Required coverage can add work only when explicitly approved. Exact-case proof may need an explicit selected-task rerun when existing Gradle reports are stale; no blanket rerun is added to the default path. Device replay needs stable UI selectors and verified APK checksum access; unsupported environments retain manual verification and cannot fabricate replay PASS.

Full release readiness still requires deterministic validation, exact-final-commit cross-platform CI, and relevant client certification. Git and publication remain maintainer-owned.
