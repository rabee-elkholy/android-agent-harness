---
trigger: glob
globs: "**/ui/**/*.kt, **/*Screen.kt, **/*Preview.kt, **/*Theme.kt"
description: Compose UI inspection and focused preview guidance for Android changes.
---
<!-- managed-by: android-agent-harness -->

Keep the always-on harness kernel and central skill/review policy authoritative.
When working on Compose UI, load `.agents/skills/compose-inspector/SKILL.md` if
routed. Use `.agents/workflows/android-inspection.md` for optional live IDE
analysis and `.agents/workflows/android-ui.md` for approved preview compilation.
Inspect representative loading/error/content, RTL/LTR, dark/light and large-font
previews already defined in source. Add missing previews only within approved
scope. A preview or IDE inspection cannot replace builds, device tests or evidence.
Globs are a context-loading convenience, not exhaustive Compose detection.
