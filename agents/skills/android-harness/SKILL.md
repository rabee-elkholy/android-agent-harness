---
name: android-harness
description: Use when working on this Android app architecture, Compose or XML UI, Room, performance, or daily checkout facts.
---

# Android harness (domain knowledge)

Setup fills product-specific references. Do not cite a stub file as if this app shipped that domain.

## References

- [**Architecture & Patterns**](./references/architecture-guidelines.md): match this checkout's DI, navigation, and ViewModel base.
- [**UI Layout & Theming**](./references/ui-layout-and-theming.md): Compose & XML UI, theme tokens, `@Preview`, strings.
- [**Database & Persistence**](./references/database-and-persistence.md): Room & SQLite migrations, DataStore, schema integrity.
- [**Performance & Optimization**](./references/performance-and-optimization.md): main-thread safety, leaks, Compose jank, WakeLocks.
- [**Test Quality Guidelines**](./references/test-quality-guidelines.md): unit test depth, Coroutine test dispatchers, Turbine streams.
- [**Daily work notes**](./references/daily-scenarios.md): checkout facts after setup.
- [**Automated skills**](./references/automated-skills.md): five-leaf delivery gate.

Zoho Sprints (when enabled): `.agents/workflows/zoho-sprints.md`. Mutate only on `update zoho`.

## Related skills

- [**Kotlin Coroutines Expert**](../kotlin-coroutines-expert/SKILL.md)
- [**Systematic Debugging**](../systematic-debugging/SKILL.md)
- [**Compose Inspector**](../compose-inspector/SKILL.md)
- [**Gradle Build Optimizer**](../gradle-build-optimizer/SKILL.md)
- [**Git PR Automator**](../git-pr-automator/SKILL.md): commit **message** format only
