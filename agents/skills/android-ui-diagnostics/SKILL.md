---
name: android-ui-diagnostics
description: Compose preview discovery/rendering and Device Hub inspection via the official Android CLI plugin (`android-ui` and `android-inspect`). Use for Compose UI visual loops or Studio symbol/docs checks.
version: 1.0.0
kernel-major: 1
---

# Android UI & Studio Diagnostics Skill

Follow `.agents/workflows/android-ui.md` for bounded Compose preview listing/rendering (`python .agents/harness.py android-ui capabilities/list/render/hub`) and `.agents/workflows/android-inspection.md` for live Android Studio symbol/docs lookups (`android-inspect`). Advisory diagnostics never substitute for required build, unit-test, review, or device evidence.

## Roborazzi Headless `.uitree.json` Bounds Verification
- When `io.github.takahirom.roborazzi` is configured (`python .agents/harness.py roborazzi capabilities --json`), run `python .agents/harness.py roborazzi verify` (or `roborazzi inspect-tree`) to verify deterministic `[left, top, right, bottom]` UI bounds, horizontal/RTL viewport clipping, zero-size controls, and sibling overlap on the JVM before building an APK.
