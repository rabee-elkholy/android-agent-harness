---
name: android-harness
description: Use when working on this Android app architecture, Compose or XML UI, Room, performance, or daily checkout facts.
version: 1.0.0
kernel-major: 1
---

# Android harness (domain knowledge)

Deterministic architecture facts are derived during setup into `.agents/project-context/`.

## Authoritative Truth Resolution Hierarchy
1. **Current source evidence**, when inspected directly in checkout files.
2. **Generated project facts**: `.agents/project-context/project-facts.json` and rendered views (`architecture.md`, `ui.md`, `persistence.md`, `conventions.md`).
3. **Developer notes**: `.agents/project-context/project-notes.md` (domain intent & unresolved conventions). Developer notes clarify ambiguities or override generic assumptions, but may NOT contradict deterministic source facts.
4. **Generic Android guidelines**: Kit-owned reference rules below.

## Harness Execution Boundary
During normal Android application tasks, installed harness engine source under `.agents/scripts/**` is an implementation detail. Do not inspect or recursively read harness Python implementation before executing a documented harness command. Use the documented public command contract and its output directly.

Harness source inspection is allowed only when:
1. a documented harness command fails unexpectedly;
2. its output violates the documented contract;
3. Doctor reports harness corruption/inconsistency;
4. the developer explicitly asks to inspect, debug, or modify the harness itself.

Application source inspection remains unaffected. For documented commands, see [Public Command Contract](./references/command-contract.md).

## Task Guidance & Routing
- **Harness Public Command Contract**: [Command Contract & Operations](./references/command-contract.md).
- **Context Management Actions**: Updating project context, recording architectural conventions, or adding domain notes is an administrative action, not an Android code task. Do NOT run change_classifier, review_policy, or assemble. Record notes directly using `python .agents/harness.py context note "<note>"`.
- **Active Architecture Contract**: If the active task contains an architecture contract, read `task-architecture-brief.md` in the task directory after project graph discovery and before editing source:
  - **PRESERVE / REFACTOR**: follow local family; no implicit modernization.
  - **NEW**: follow preferred new-code family; surrounding legacy code is only a compatibility boundary.
  - **MIGRATE**: perform only the approved source -> target transition inside approved scope.
- **Architecture / DI / ViewModel**: Read `../../project-context/architecture.md`, then [Architecture & Patterns](./references/architecture-guidelines.md).
- **UI / Layout / Theming**: Read `../../project-context/ui.md`, then [UI Layout & Theming](./references/ui-layout-and-theming.md).
- **Database / Persistence**: Read `../../project-context/persistence.md`, then [Database & Persistence](./references/database-and-persistence.md).
- **Conventions & Capabilities**: Read `../../project-context/conventions.md`.
- **Performance & Optimization**: [Performance & Optimization](./references/performance-and-optimization.md).
- **Test Quality Guidelines**: [Test Quality Guidelines](./references/test-quality-guidelines.md).
- **Daily work notes**: [Daily work notes](./references/daily-scenarios.md).
- **Automated skills**: [Automated skills](./references/automated-skills.md).

Zoho Sprints (when enabled): `.agents/workflows/zoho-sprints.md`. Mutate only on `update zoho`.

## Related skills

- [**Kotlin Coroutines Expert**](../kotlin-coroutines-expert/SKILL.md)
- [**Systematic Debugging**](../systematic-debugging/SKILL.md)
- [**Compose Inspector**](../compose-inspector/SKILL.md)
- [**Gradle Build Optimizer**](../gradle-build-optimizer/SKILL.md)
- [**Git PR Automator**](../git-pr-automator/SKILL.md): commit **message** format only
