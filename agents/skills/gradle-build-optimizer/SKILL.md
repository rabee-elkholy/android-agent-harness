---
name: gradle-build-optimizer
description: Use when Gradle builds hang, lock on Windows, or targeted module and variant tasks can replace a full rebuild.
version: 1.1.0
kernel-major: 1
---

# Gradle Build Optimizer

## Daemon reuse
- Use the **repo-root** wrapper (`gradlew.bat` / `./gradlew`). Do not use `app/gradlew`.
- Do not start a second wrapper if a Gradle daemon for this checkout is already running.
- Resolve the affected modules, source sets, variants, and exact test/assemble tasks from project configuration and discovery. Run those tasks through `python .agents/scripts/run_gradle_task.py`; do not copy an example application task into a library, flavored, or KMP project. Do not run raw `gradlew` / `gradlew.bat` from the agent — the wrapper picks the OS script, streams executing tasks, and a 10s heartbeat. An empty task log means the process never started, not "still compiling silently".
- Device install/launch: `python .agents/scripts/run_device.py install-start` (live adb output).
- Raise the command wait high enough for a real compile (minutes, not 10 seconds). Success is the log line `BUILD SUCCESSFUL` on **that same command**. A timeout/early return is not success and is not a reason to start a second assemble. If the log shows `BUILD FAILED`, fix then start one new assemble. Do not install a leftover APK.
- Use the approved configured variant. Do not substitute debug for a release/minification-specific failure. Inspect the project's actual minification and signing configuration; variant names alone do not establish either. Missing signing credentials are an environment limitation, not permission to alter signing or bypass verification.

## Windows file locks
- If assemble fails with `AccessDeniedException` or kapt tmp delete errors, tell the developer.
- Use `./gradlew --stop` only with explicit developer agreement (it is not project-local).

## Worktrees
- This project does not use Git worktrees for AI subagents. Do not copy `local.properties` into a worktree or spawn `Workspace="share"`.

## Dependencies
- Check transitive conflicts before adding libraries.
- Check dependency ownership in the discovered module graph; avoid redundant declarations while preserving dependencies required by each module's public API.
