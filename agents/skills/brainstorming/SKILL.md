---
name: brainstorming
description: Use when planning architectural tasks, multi-module restructuring, new system integrations, or exploring trade-offs between design options.
---

# Brainstorming & Architecture Exploration Skill

## 1. Purpose & Planning Depth
Planning depth is advisory and categorizes tasks into two levels:
- **BOUNDED (Default)**: Normal bug fixes, targeted UI tweaks, single-screen features, small repository methods, or isolated Room migrations. These tasks skip architectural design ceremony and proceed directly to the standard implementation plan.
- **ARCHITECTURAL**: Multi-module restructuring, public API redesigns, persistence or networking layer swaps, major authentication redesigns, or app-wide state pattern migrations.

For `ARCHITECTURAL` tasks, activate this skill to work out a concise **Design-Lite** and carry the selected approach into the plan: `workflow.py draft --approach "..." --risks "..."`. The harness renders it in the approval summary and in the generated `plan.md`.

> [!IMPORTANT]
> **Single Approval Invariant**: The Design-Lite exploration does NOT create an extra approval round. The one plan approval (bound to the plan hash, which covers `--approach`) authorizes both the chosen design approach and the implementation plan.

---

## 2. Design-Lite Structure (ARCHITECTURAL Tasks)
When preparing an architectural plan, settle these points (the selected approach goes into `--approach`, trade-off risks into `--risks`):
1. **Goal & Constraints**: What must change and what non-negotiable boundaries exist.
2. **Current Architecture**: The existing pattern, module topology, or contract.
3. **Option A (Minimal / Evolutionary)**: Smallest blast radius, builds on existing code structure.
4. **Option B (Idiomatic Target Architecture)**: Clean separation of concerns, target patterns.
5. **Trade-offs**: Pros/cons, blast radius, migration complexity, token/build impact.
6. **Selected Approach & Rationale**: Why this approach was chosen.

---

## 3. Four-Phase Brainstorming Methodology

### Phase 1: Requirements, Reuse & Anti-Sycophancy Probing
1. **Challenge Flawed Premises (Anti-Sycophancy)**: Never blindly validate a proposed design if it violates Android/KMP lifecycle guarantees, introduces race conditions, bypasses ViewModel/Repository boundaries, or adds speculative abstractions. Point out the concrete technical flaw and propose a sound alternative before drafting.
2. **Graph-Backed Codebase Reuse First**: Query the project graph (`graph --find` / `task-context`) before proposing any new Manager, Helper, UseCase, Repository, or UI component. Reuse or extend existing classes whenever possible.
3. **YAGNI & Complexity Justification**: Every newly proposed abstraction layer, wrapper interface, or state channel must justify its existence with a concrete multi-caller, platform-boundary (`expect`/`actual`), or unit-testability requirement.
4. **Underspecified Requirements & Edge Cases**: Probe data persistence needs (Room, DataStore, SharedPreferences), network error handling, offline support, process death restoration, and backward compatibility constraints.

### Phase 2: Design Space & Trade-off Evaluation
Formulate and evaluate **2–3 distinct technical approaches**:
- **Option A (Minimal / Incremental)**: Smallest blast radius, fits existing code structure directly, minimal refactoring.
- **Option B (Idiomatic MVI / Clean Architecture)**: Single-source StateFlow, isolated UseCase, clean domain entities, full separation of concerns.
- **Option C (Future-Proof / Reactive)**: Event-driven channels, decoupled abstractions, high scalability.

For each option, evaluate:
- **Pros & Cons**.
- **Blast Radius & Risk**: Which existing screens/features are touched?
- **Implementation Effort**: Number of files and estimated complexity.

### Phase 3: Android Platform Invariants Pre-Screening
Before proposing an approach, verify that it adheres to strict platform invariants:
- **Threading & ANR**: Zero synchronous disk or database I/O on `Dispatchers.Main`.
- **Database Migrations**: Incremental schema changes for `@Entity` / `@Database`.
- **Compose Stability**: `@Immutable` / `@Stable` state models, Lazy list keys, directional RTL padding.
- **Localization**: Dual-locale Arabic (RTL) and English (LTR) string parity.

### Phase 4: Developer Alignment & Spec Locking
- Present trade-offs concisely to the developer in chat or via `ask_question` when user preferences are needed.
- Lock the agreed technical specification before running `workflow.py draft`.
