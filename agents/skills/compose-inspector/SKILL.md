---
name: compose-inspector
description: Use when inspecting or building Jetpack Compose UI for recomposition safety, stability (@Immutable/@Stable), RTL/LTR, remember/derivedStateOf, and Lazy list keys.
---

# Compose Inspector & Layout Verifier

## 1. Composition & Performance Safety Checks
- **Stability**: Ensure UI state data classes containing Collections (`List`, `Set`, `Map`) are annotated with `@Immutable` or `@Stable` to prevent unnecessary recompositions.
- **Calculations**: Verify `remember` is used for expensive object allocations or formatting inside composables.
- **Fast-Changing State**: Use `derivedStateOf` when reading rapidly changing states (e.g., `lazyListState.firstVisibleItemIndex`, scroll offset, real-time pedometer counters) to avoid recomposing the parent scope on every tick.
- **Lazy Lists**: Every `LazyColumn` / `LazyRow` must specify explicit `key` lambdas using unique, stable IDs (e.g., `key = { it.id }`).
- **State Hoisting**: Pass only immutable State and lambda callbacks down to leaf composables. Never pass `ViewModel` instances into reusable child components.

---

## 2. Layout & Localization Verification
- **RTL / LTR**: Strictly use directional modifiers: `Modifier.padding(start = ..., end = ...)` instead of `left`/`right`.
- **Theme & Design Tokens**: All colors and text styles must consume this app's theme tokens — `MaterialTheme.colorScheme` / `MaterialTheme.typography`. `colorResource(R.color…)` is allowed when matching existing XML colors. Never use raw hex colors or hardcoded fonts.
- **String Resources**: Extract all text to `values/strings.xml` and `values-ar/strings.xml`.
- **Previews**: Every independent UI component and screen state (Loading, Empty, Success, Error) must have a `@Preview` function wrapped in this app's theme (or `MaterialTheme`), including Arabic RTL (`locale = "ar"` or `CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl)`) and English LTR (`locale = "en"` or `LayoutDirection.Ltr`).
