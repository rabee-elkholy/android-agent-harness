---
trigger: glob
globs: "**/*.gradle.kts, **/*.gradle, **/gradle.properties, **/libs.versions.toml"
description: Scoped Gradle and dependency configuration guidance.
---
<!-- managed-by: android-agent-harness -->

Load `.agents/skills/gradle-build-optimizer/SKILL.md` when selected by policy.
Resolve project module/variant and run builds through the harness wrappers.
Preserve dependency versions and the project's build system unless migration is
approved. Read the wrapper's bounded error summary first; the complete log path
is printed in its result. Use `.agents/workflows/android-inspection.md` to verify
API/tool guidance against official documentation. Never upload source, credentials
or private build logs as a documentation query. Required gates remain unchanged.
