# Install prompt

---

You are installing the portable **Android AI harness** into **this** checkout. This folder is the Android product. It is not `android-harness-kit`.

Answer in the developer's language. Do not commit unless they ask. Do not only rename the example app.

Tell the developer **first**, in their language, as a warning they must read: this setup needs a **strong model** in this chat, not a fast/cheap one. Install is a structural port (package, module, APK, architecture, leftover grep, selftest). A weak model skips steps, shortens questions, and leaves a broken helper. They should stay until selftest `Total test failures: 0`. If they say this chat is a small model, **stop** and tell them to open a new chat on a stronger model, then paste this file again.

Then tell them: a few short questions (backup, app name, who commits, phone vs emulator, ask before install, unit tests, which AI tools, Zoho Sprints), then backup, port, and selftest. Stopping early yields a weak harness.

## Start now

1. **Target Project Verification (Fail-Fast)**:
   - **Android Project Check**: Confirm this repo has `gradlew` or `gradlew.bat` AND Android Gradle build files (`build.gradle` / `build.gradle.kts`). If not, **STOP IMMEDIATELY** and tell the developer in their language:
     `[ERROR] Target directory is NOT an Android project. Android Harness Kit requires a Gradle-based Android or Kotlin Multiplatform project.`
   - **Semi-Complete / Non-Blank Codebase Check**: Confirm this repo contains an existing, active codebase with real Kotlin/Java files, ViewModels, and UI (not an empty starter template). If the project is blank with no existing architecture/screens, **STOP IMMEDIATELY** and tell the developer in their language:
     `[ERROR] Android Harness Kit requires an existing, active/semi-complete codebase with established architecture, ViewModels, and UI to discover and govern. Please create your foundational app structure and initial screen first, then install the harness.`
2. Get the kit (do **not** clone into `app/`, `composeApp/`, or any module source tree):
   - If a clone already exists nearby (sibling `android-harness-kit`, a path the developer gives, or a previous temp clone), use that. `git pull` on `main` if they want the latest.
   - Otherwise: `git clone https://github.com/rabee-elkholy/android-harness-kit.git` into a sibling folder or the OS temp directory.
3. **Answers first (do not invent short questions).** `--lang ar` if the developer writes Arabic, else `--lang en`.
   - Preferred: they run this in **their** terminal, then tell you when it finishes:
     `$PY <kit>/agents/scripts/setup_wizard.py --repo <this-android-root> --lang <ar|en>`
   - If they want you to ask in chat: `$PY <kit>/agents/scripts/setup_wizard.py questions --repo <this-android-root> --lang <ar|en>`. Print `model_warning` in chat first (developer language), then `auto_blurb`. Then `ask_question` using each JSON `questions[].prompt` **verbatim**. Ask **only** that list (usually i0, i1, i3, i4, i10, i15, i14, i16). Do not invent extra questions. Then write a JSON file of ids → values and `$PY <kit>/agents/scripts/setup_wizard.py write --repo <this-android-root> --answers-json <that-file>`.
   - Stop if I.0 is no / wizard exit 1. Do not copy `.agents`.
4. When `<this-repo>/.harness-setup/answers.json` exists with `"i0": true`, open `<kit>/docs/setup-prompt.md` and execute it from **0) Backup** onward. If `"backup": false`, skip copying backups and say rollback will not work. Skip section **I** (answers are already recorded). Copy `.harness-setup/SETUP_ANSWERS.md` into the new backup folder when a backup was made. Installer flags: `$PY <kit>/agents/scripts/setup_wizard.py flags --repo <this-android-root>`. Copy source: `<kit>/agents/` → `<this repo>/.agents`.
5. After setup: tell them to start a **new chat** on this Android folder before real work.

Kit rules that still apply during setup:

- Backup before overwriting `.agents` or tool adapters.
- Structural port (package, regex, Path pieces, APK name, architecture, locales). A find-replace of the example name is not a successful install.
- Write adapters only for the tools in answers.json (`--tools`). Always write `AGENTS.md`.
- Kit `agents/mcp_config.json` stays empty. After copy, run `install_zoho_mcp.py` from I.16. **Never copy** a Zoho token file, `zoho_config.json`, or OAuth values into the repo. If I.16 is enable, point `ZOHO_SPRINTS_CONFIG` at an existing user-level file when one is already on this PC. Do not overwrite the developer's other MCP / Continue / Aider / `kilo.jsonc` / `~/.gemini` configs.
- Do not copy `local.properties` `sdk.dir` or `~/.gemini` hostnames from another machine.
- `adb monkey` stays denied. Emulator deny only if they lock the install to a physical device.

Begin: print the strong-model warning in the developer's language. Then print OS, this repo path, and whether you reused a kit clone or cloned a fresh one. Then step 3 (wizard).
