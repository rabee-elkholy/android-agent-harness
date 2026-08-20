# Daily work notes

Follow `.agents/rules/harness-rules.md`. Setup fills checkout facts from Gradle/manifests into `_product.py` and this file.

## Checkout facts (this file only)

- Product, `applicationId`, launcher, assemble task, and debug APK: `.agents/scripts/_product.py`
- Source roots: classic `app/src/main` or KMP `androidMain` — use what exists on disk
- Locales: the `values` / `values-*` folders that exist

## Where to read the rest

- Architecture: `architecture-mvi.md`
- Compose / theme: `ui-compose-theme.md`
- Room: `room-database-migrations.md` (only if this checkout has `@Database`)
- Performance: `performance-anr-optimization.md`
- Ads / streak / GPS / sensors / payments: only if those files describe **this** checkout (kit stubs are not rules)
