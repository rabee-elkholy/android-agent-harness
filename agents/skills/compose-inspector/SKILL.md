---
name: compose-inspector
description: Use when inspecting or building Jetpack Compose UI for recomposition safety, stability (@Immutable/@Stable), RTL/LTR, remember/derivedStateOf, and Lazy list keys.
version: 1.1.0
kernel-major: 1
---

# Compose Inspector & Layout Verifier

## 1. Composition & Performance Safety Checks
- **Stability**: Diagnose a recomposition problem with runtime observations or compiler reports before changing stability. `List`, `Set`, and `Map` are not proof of immutability. `@Immutable` and `@Stable` are compiler contracts, not transformations: use them only when all reachable values satisfy the immutability contract, or mutable public state notifies Compose and satisfies the stability contract. Check mutation through aliases and element types; prefer a correctly modeled type over an annotation that hides instability. See the [official stability guidance](https://developer.android.com/develop/ui/compose/performance/stability/fix).
- **Calculations**: Verify `remember` is used for expensive object allocations or formatting inside composables.
- **Fast-Changing State**: Use `derivedStateOf` when the derived result changes less often than its inputs (for example, a scroll threshold). It adds overhead and does not help when the UI needs every input update.
- **Lazy Lists**: Every `LazyColumn` / `LazyRow` must specify explicit `key` lambdas using unique, stable IDs (e.g., `key = { it.id }`).
- **State Hoisting**: Pass only immutable State and lambda callbacks down to leaf composables. Never pass `ViewModel` instances into reusable child components.

---

## 2. Layout & Localization Verification
- **RTL / LTR**: Strictly use directional modifiers: `Modifier.padding(start = ..., end = ...)` instead of `left`/`right`.
- **Theme & Design Tokens**: All colors and text styles must consume this app's theme tokens — `MaterialTheme.colorScheme` / `MaterialTheme.typography`. `colorResource(R.color…)` is allowed when matching existing XML colors. Never use raw hex colors or hardcoded fonts.
- **String Resources**: Put user-facing text in the owning module's resource source set. Follow the project's configured locales, qualifiers, fallback rules, and translation conventions; do not invent an Arabic locale or assume an application module.
- **Previews**: Add focused previews for changed states where the existing tooling supports them, using the project's theme. Cover supported locales and relevant layout directions; Arabic RTL and English LTR are examples only. A preview is not runtime or device verification, and unsupported previews must not trigger build-system changes outside the approved scope.
