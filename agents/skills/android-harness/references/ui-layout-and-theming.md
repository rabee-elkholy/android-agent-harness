# UI Layout, Compose, XML & Theming Guidelines

Setup fills theme class names from this checkout. Until then, use `MaterialTheme` tokens.

- New UI: Jetpack Compose unless the surrounding screen is XML and the developer did not ask to convert it.
- Colors and type: `MaterialTheme.colorScheme` / `MaterialTheme.typography`. `colorResource(R.color…)` is allowed when matching existing XML colors. No raw hex and no hardcoded fonts.
- Follow [Compose Inspector](../../compose-inspector/SKILL.md) for focused previews of changed states, configured locales, and relevant layout directions where preview tooling is supported. Arabic RTL and English LTR are examples, not mandatory project locales. Keep resource changes in the owning module and existing source sets.
- User-facing text in string resources, not hardcoded in Composables or ViewModels.
- Image loading: match the library already in the module (Coil or other).
