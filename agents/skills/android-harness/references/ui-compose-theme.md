# Jetpack Compose & theme

Setup fills theme class names from this checkout. Until then, use `MaterialTheme` tokens.

- New UI: Jetpack Compose unless the surrounding screen is XML and the developer did not ask to convert it.
- Colors and type: `MaterialTheme.colorScheme` / `MaterialTheme.typography`. `colorResource(R.color…)` is allowed when matching existing XML colors. No raw hex and no hardcoded fonts.
- Dual-locale `@Preview`: Arabic RTL (`locale = "ar"` for AndroidX, or `CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl)` for KMP/Compose Multiplatform) and English LTR (`locale = "en"` or `LayoutDirection.Ltr`). Screens also need Loading, Empty, and Error.
- User-facing text in string resources, not hardcoded in Composables or ViewModels.
- Image loading: match the library already in the module (Coil or other).
