# ADR-019: Selective Integration of Elephant-Goldfish Model (EGM) Concepts

## Status

Accepted

## Context

Google's Elephant-Goldfish Model (`google/elephant-goldfish-model`) separates AI-assisted software engineering into two complementary modes:
1. **Elephant (Deep-Context Architecture & Spec Intelligence)**: Probing requirements, challenging flawed premises (anti-sycophancy), discovering existing reusable code before introducing new abstractions, and recording decision rationale alongside rejected alternatives.
2. **Goldfish (Epistemically Isolated Reviewers)**: Evaluating implementation diffs without being anchored or biased by the implementing agent's self-justification, while enforcing YAGNI and codebase reuse.

We evaluated EGM against Android Agent Harness's core guarantees:
- Single state machine (`workflow.py`) and single approval boundary (`plan_sha256`).
- Zero external Python dependencies (100% standard library).
- Native Antigravity host hook and subagent compatibility.
- Fast daily developer loop for native Android, Kotlin Multiplatform (KMP), and iOS companion source sets.

## Decision

We adopt **Option A (Selective Native Integration)** and reject full EGM plugin installation or multi-round spec approval workflows:

1. **Blind Goldfish Epistemic Isolation in Lean Briefs (`review_package.py`, `phase_review.py`)**:
   - The designated plan-completeness owner (`bug-reviewer-agent` or `regression-impact-reviewer-agent`) and `spec-compliance-agent` verify every item of the `Approved Approach`.
   - All other specialist reviewers (`security-reviewer-agent`, `perf-anr-guardian-agent`, `convention-reviewer-agent`, `test-quality-reviewer-agent`) receive an explicit **Goldfish Epistemic Independence** directive instructing them to treat implementer approach descriptions and `FALSE_POSITIVE` finding validations as untrusted hypotheses, judging the diff strictly on runtime behavior, architectural contracts, and code evidence.
   - `finding-validations.json` claims are surfaced in lean briefs scoped to the owning reviewer for adversarial re-verification.

2. **Graph-Grounded Codebase Reuse & Plan Readiness (`_workflow/planning.py`, `plan_document.py`)**:
   - During `task draft` and `task revise`, newly planned `.kt`, `.java`, and `.swift` files are cross-checked against the `GraphEngine` symbol index (`_discover_reuse_candidates`) to surface existing classes, repositories, or helpers with overlapping domain stems (`reuse_candidates`).
   - Advisory readiness diagnostics (`readiness_assessment`) are recorded in `plan.json` and rendered in `plan.md` and `APPROVAL_BRIEF` without altering `plan_payload` or `plan_sha256`.

3. **YAGNI & Reuse Reviewer Rubric (`convention-reviewer-agent.json`)**:
   - `convention-reviewer-agent` enforces Rule 11 (`Codebase Reuse & YAGNI`), flagging redundant helper/manager/wrapper abstractions that duplicate existing graph-discovered components without multi-caller or testability justification.

4. **Deterministic KMP `commonMain` Purity & Clean Layer Boundary Drift (`_modules.py`, `preflight_check.py`, `architecture_drift.py`)**:
   - `check_kmp_common_main_purity` deterministically blocks `android.*`, `java.io.*`, `java.net.*`, `java.sql.*`, `java.awt.*`, `java.nio.*`, and `javax.swing.*` imports inside `src/commonMain` during preflight Step 7 (zero overhead for native Android repos without `src/commonMain`).
   - `check_architecture_drift` detects `UI_TO_DATA_SOURCE_BYPASS` when a UI entry file (`@Composable` screen, `Activity`, `Fragment`) newly imports or injects Room `@Dao`, `SQLiteDatabase`, or `retrofit2.http.*` directly in a layered architecture contract.

5. **Persistent Decision Rationale & Swift Graph Indexing (`generate_project_context.py`, `_graph_core.py`, `task_context.py`)**:
   - `context instruct` supports optional `--rationale` and `--alternatives-rejected` fields persisted in `developer-instructions.json` and surfaced in `task-context` and review packages while keeping instruction IDs (`pi-<sha8>`) unchanged.
   - `GraphEngine` and `task-context` index `.swift` files (`struct`, `class`, `enum`, `protocol`, `actor`, `func`, SwiftUI `View`, and `ObservableObject`/`@Observable` ViewModels) for KMP + iOS (`iosMain` / `iosApp`) navigation.

## Consequences

- Specialist reviewers remain unbiased by implementer prose while plan-completeness checking stays owned by one reviewer.
- Native Android projects experience zero extra ceremony or overhead, while KMP and iOS source sets gain deterministic purity and graph support.
- All Antigravity hooks, subagent contracts, and existing approval hashes remain 100% backward-compatible.
