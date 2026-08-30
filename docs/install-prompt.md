# Install prompt

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/v0.14.6/docs/install-prompt.md`  
> **Kit Repository**: `https://github.com/rabee-elkholy/android-harness-kit.git`
> **Kit version**: `v0.14.6` — **SHA-256**: `f6a43344a915e9c5389b9970e9ddb6b3484eb007845fe88fa5bf47165fd91321` (SHA-256 of every byte after this line; verify first — mismatch = STOP)
---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

You are installing the portable **Android AI harness** into **this** checkout. This folder is the Android product. It is not `android-harness-kit`.

Answer in the developer's language. Do not commit unless they ask. Do not only rename the example app.

Tell the developer **first**, in their language, as a warning they must read: this setup needs a **strong reasoning model** in this chat (such as Anthropic `Claude Opus 5 / 3.7 Sonnet (Thinking)`, Google `Gemini 3.1 Pro (Deep Think)`, OpenAI `GPT-5.6 Sol / o3`, or DeepSeek `DeepSeek-V4 Pro / R1`), not a fast/lightweight one without deep reasoning. Install is a structural port (package, module, APK, architecture, leftover grep, selftest). A weak model skips steps, shortens questions, and leaves a broken helper. They should stay until selftest `Total test failures: 0`. If they say this chat is a small model, **stop** and tell them to open a new chat on a stronger model, then paste this file again.

Then tell them: the wizard asks only the questions it returns (backup, app name, git policy, device policy, install confirmation, unit tests, tools, Zoho, language, tracker, and git gate; conditional Python/module/launcher/flavor/bootstrap questions may also appear), then backup, port, and selftest. Stopping early yields a weak harness.

## Start now

1. **Target Project Verification (Fail-Fast)**:
   - **Android Project Check**: Confirm this repo has `gradlew` or `gradlew.bat` AND Android Gradle build files (`build.gradle` / `build.gradle.kts`). If not, **STOP IMMEDIATELY** and tell the developer in their language:
     `[ERROR] Target directory is NOT an Android project. Android Harness Kit requires a Gradle-based Android or Kotlin Multiplatform project.`
   - **Greenfield / Established Codebase Support**:
     - If this is an **established codebase**, the wizard will automatically discover your architecture, DI, ViewModels, and UI from disk.
     - If this is a **brand-new / blank project**, the wizard will automatically guide you through the **Greenfield Bootstrap Questionnaire** (Platform, MVI/MVVM, Koin/Hilt, Voyager/ComposeNav, Room/SQLDelight, Ktor/Retrofit) to establish the architectural blueprint and governance rules from day one.
2. **Get the Kit (Remote & Local Support)**:
    - Preferred: run `android-harness init --repo <this-android-root>`. The CLI resolves a release tag, provisions the kit at detached `v<version>`, and verifies that `agents/VERSION` matches the tag. It never provisions from `main`.
    - For a manual kit clone, fetch and check out an exact release tag before copying anything:
      ```bash
      git clone --no-checkout https://github.com/rabee-elkholy/android-harness-kit.git
      git -C android-harness-kit fetch origin --tags --prune
      git -C android-harness-kit checkout --detach v<requested-version>
      ```
      Verify `android-harness-kit/agents/VERSION` equals `<requested-version>`. Do **not** clone into `app/`, `composeApp/`, or any module source tree, and do **not** pull `main`.
3. **Answers first (do not invent short questions).** `--lang ar` if the developer writes Arabic, else `--lang en`.
   - Preferred: they run this in **their** terminal, then tell you when it finishes:
     `$PY <kit>/agents/scripts/setup_wizard.py --repo <this-android-root> --lang <ar|en>`
    - If they want you to ask in chat: `$PY <kit>/agents/scripts/setup_wizard.py questions --repo <this-android-root> --lang <ar|en>`. Print `model_warning` in chat first (developer language), then `auto_blurb`. Then `ask_question` using each JSON `questions[].prompt` **verbatim**. Ask **only** that list; the JSON payload is the sole interview authority. Then write a JSON file of ids → values and `$PY <kit>/agents/scripts/setup_wizard.py write --repo <this-android-root> --answers-json <that-file>`.
   - Stop if I.0 is no / wizard exit 1. Do not copy `.agents`.
4. When `<this-repo>/.harness-setup/answers.json` exists with `"i0": true`, open `<kit>/docs/setup-prompt.md` and execute it from **0) Backup** onward. If `"backup": false`, skip copying backups and say rollback will not work. Skip section **I** (answers are already recorded). Copy `.harness-setup/SETUP_ANSWERS.md` into the new backup folder when a backup was made. Installer flags: `$PY <kit>/agents/scripts/setup_wizard.py flags --repo <this-android-root>`. Copy source: `<kit>/agents/` → `<this repo>/.agents`.
5. After setup: run `$PY .agents/scripts/harness_doctor.py` for automated 12-dimension verification. If uncommitted changes exist, instruct the developer in their language to commit their changes. Then tell them to start a **new chat** on this Android folder before real work.

Kit rules that still apply during setup:

- **Strict Read-Only Kit Source**: Never modify or write files in `<kit>` (`android-harness-kit`). Port and configure strictly into `<this repo>/.agents`.
- **Scope Isolation**: Setup configures `.agents/` only. Never edit app production files (`strings.xml`, Kotlin files) during install. Report pre-existing preflight issues in chat.
- **No `schedule` Timers**: Never call `schedule` or create background sleep timers during install. Run commands synchronously or await reactive completion.
- **Mandatory Step 3b Approval**: Must present the domain references table to the developer via `ask_question` and obtain approval.
- Backup before overwriting `.agents` or tool adapters.
- Structural port (package, regex, Path pieces, APK name, architecture, locales). A find-replace of the example name is not a successful install.
- Write adapters only for the tools in answers.json (`--tools`). Always write `AGENTS.md`.
- Kit `agents/mcp_config.json` stays empty. After copy, run `install_zoho_mcp.py` from I.16. **Never copy** a Zoho token file, `zoho_config.json`, or OAuth values into the repo. If I.16 is enable, point `ZOHO_SPRINTS_CONFIG` at an existing user-level file when one is already on this PC. Do not overwrite the developer's other MCP / Continue / Aider / `kilo.jsonc` / `~/.gemini` configs.
- Do not copy `local.properties` `sdk.dir` or `~/.gemini` hostnames from another machine.
- `adb monkey` stays denied. Emulator deny only if they lock the install to a physical device.

Begin: print the strong-model warning in the developer's language. Then print OS, this repo path, and whether you reused a kit clone or cloned a fresh one. Then step 3 (wizard).
