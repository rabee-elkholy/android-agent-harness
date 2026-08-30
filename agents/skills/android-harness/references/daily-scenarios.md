# Daily work notes

Follow `.agents/rules/harness-rules.md`. Setup fills checkout facts from Gradle/manifests into `_product.py` and this file.

## Checkout facts (this file only)

- Product, `applicationId`, launcher, assemble task, and debug APK: `.agents/scripts/_product.py`
- Source roots: classic `app/src/main` or KMP `androidMain` — use what exists on disk
- Locales: the `values` / `values-*` folders that exist

## Where to read the rest

- Architecture: `architecture-guidelines.md`
- UI / Layout / Theming: `ui-layout-and-theming.md`
- Database / Persistence: `database-and-persistence.md` (only if this checkout has local DB/storage)
- Performance / Optimization: `performance-and-optimization.md`
- Test Quality: `test-quality-guidelines.md`
- Automated Skills: `automated-skills.md`
- Specialized domains: custom references created during setup (e.g. audio, education, media) if present in this checkout.
