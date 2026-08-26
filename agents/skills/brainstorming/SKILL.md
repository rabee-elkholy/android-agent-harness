---
name: brainstorming
description: Use before planning non-trivial features, new screens, or major refactors to explore architectural trade-offs, compare 2-3 design options, assess complexity/risks, and gather requirements before writing an implementation plan.
---

# Brainstorming & Architecture Exploration Skill

## 1. Purpose & Trigger
Activate this skill before committing to an implementation plan whenever the task involves:
- Adding a new feature, screen, or system integration.
- Major refactoring of existing presentation, domain, or data layers.
- Architectural design decisions with multiple viable technical paths.

---

## 2. Four-Phase Brainstorming Methodology

### Phase 1: Requirements & Constraints Probing
1. Identify underspecified requirements, hidden assumptions, and edge cases.
2. Probe data persistence needs (Room, DataStore, SharedPreferences), network error handling, offline support, and lifecycle boundaries.
3. Determine backward compatibility constraints with existing models and shared contracts.

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
- Lock the agreed technical specification before authoring the `implementation_plan.md` artifact.
