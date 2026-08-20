# Jetpack Compose & Theme Standards for Rashaqa

## 1. Jetpack Compose Default
- ALL new UI screens are built with **Jetpack Compose** (unless explicitly directed otherwise).
- Each Compose screen is hosted inside `BaseComposeFragment` (`com.madarsoft.core.common.bases.BaseComposeFragment`).
- Navigation: Activity/Fragment host containers + Intents / Navigation Component (no Compose Navigation).

## 2. Theme System & Localization
- Main Theme: `MyAppTheme` (`com.madarsoft.core.ui.themes.AppThemeCompose.kt`).
- Parameters:
  - `useDarkTheme: Boolean = false`: Light / Dark color scheme.
  - `withScaffoldPadding: Boolean = true`: Controls Scaffold insets. Set `withScaffoldPadding = false` for full-screen / full-bleed layouts (like custom headers, image backgrounds, or edge-to-edge screens).
- Auto-detects system locale and applies typography:
  - **Arabic**: `Noto Naskh Arabic UI` (`Font(R.font.noto_naskh_arabic_ui_*)`)
  - **English**: `Roboto` (`Font(R.font.roboto_*)`)
- Shapes (`ComposeShapes.kt`): `AppShapes`.
- Rules: ALWAYS use `MaterialTheme.typography.*` tokens.

## 3. Previews
- Every independent Composable (screens, cards, buttons, headers) MUST have dedicated `@Preview` functions.
- Dual-Locale Previews: Include Arabic RTL (`@Preview(locale = "ar")`) and English LTR (`@Preview(locale = "en")`), plus Loading, Empty, and Error state previews.
- Wrap all previews in `MyAppTheme(withScaffoldPadding = false) { ... }` or `MyAppTheme { ... }`.

## 4. Image Loading
- Use **Coil 2** `coil.compose.AsyncImage` like existing screens. The app also depends on Coil 3; do not mix Coil 3 APIs into new UI unless migrating that screen.

## 5. String Resources
- ALL user-facing text MUST reside in `strings.xml` (`values/strings.xml` and `values-ar/strings.xml`).
- Hardcoded strings in Composables or ViewModels are strictly prohibited.
