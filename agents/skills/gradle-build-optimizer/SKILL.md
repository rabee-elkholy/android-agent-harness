---
name: gradle-build-optimizer
description: Use when Gradle builds hang, lock on Windows, or a targeted :app assemble/test is enough instead of a full rebuild.
---

# Gradle Build Optimizer

## Daemon reuse
- Use the **repo-root** wrapper (`gradlew.bat` / `./gradlew`). Do not use `app/gradlew`.
- Do not start a second wrapper if a Rashaqa Gradle daemon is already running.
- Prefer `python3 .agents/scripts/run_gradle_task.py :app:assembleDebug` / `:app:testDebugUnitTest --tests` when only `:app` changed (`python` on Windows is fine). Do not run raw `gradlew` / `gradlew.bat` from the agent — the wrapper picks the OS script, streams executing tasks, and a 10s heartbeat. An empty task log means the process never started, not "still compiling silently".
- Device install/launch: `python .agents/scripts/run_device.py install-start` (live adb output).
- Raise the command wait high enough for a real compile (minutes, not 10 seconds). Success is the log line `BUILD SUCCESSFUL` on **that same command**. A timeout/early return is not success and is not a reason to start a second assemble. If the log shows `BUILD FAILED`, fix then start one new assemble. Do not install a leftover APK.
- Daily builds are **debug**. Do not assemble `staging` or `release` unless asked (those minify and need keystore properties).

## Windows file locks
- If assemble fails with `AccessDeniedException` or kapt tmp delete errors, tell the developer.
- Use `./gradlew --stop` only with explicit developer agreement (it is not project-local).

## Worktrees
- This project does not use Git worktrees for AI subagents. Do not copy `local.properties` into a worktree or spawn `Workspace="share"`.

## Dependencies
- Check transitive conflicts before adding libraries.
- Avoid duplicating deps across `:app`, `:base`, `:gdpr`, `:fat-burner`.
