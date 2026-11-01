---
trigger: glob
globs: "**/commonMain/**/*.kt, **/androidMain/**/*.kt, **/iosMain/**/*.kt, **/commonTest/**/*.kt"
description: Source-set and platform boundary guidance for Kotlin Multiplatform changes.
---
<!-- managed-by: android-agent-harness -->

Resolve the exact module and source set with task-context before editing. Preserve
commonMain purity and inspect expect/actual or platform implementations when
changing a shared contract. Existing architecture checks and central policy remain
authoritative. Use `.agents/workflows/android-inspection.md` for optional symbol
lookups only when the running IDE has the relevant project/source set indexed;
absence of results is not proof of no platform impact. Never migrate the build
plugin, assume Android-only coverage or suppress iOS requirements implicitly.
