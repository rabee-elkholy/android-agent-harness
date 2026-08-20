# Install prompt

Paste **this entire file** as the first message in a **new chat on your Android app** (the app checkout, not the kit). The agent must execute it, not summarize it.

---

You are installing the portable **Android AI harness** into **this** checkout. This folder is the Android product. It is not `android-harness-kit`.

Answer in the developer's language. Do not commit unless they ask. Do not skip the interview. Do not only rename the example app.

## Start now

1. Confirm this repo has `gradlew` or `gradlew.bat`. If not, stop — this is not an Android Gradle checkout.
2. Get the kit (do **not** clone into `app/`, `composeApp/`, or any module source tree):
   - If a clone already exists nearby (sibling `android-harness-kit`, a path the developer gives, or a previous temp clone), use that.
   - Otherwise: `git clone https://github.com/rabee-elkholy/android-harness-kit.git` into a sibling folder or the OS temp directory.
3. Open `<kit>/docs/setup-prompt.md` and **execute that file in full** as if the developer had pasted it. The copy source is `<kit>/agents/` → `<this repo>/.agents`.
4. After setup: tell them to start a **new chat** on this Android folder before real work.

Kit rules that still apply during setup:

- Backup before overwriting `.agents` or tool adapters.
- Structural port (package, regex, Path pieces, APK name, architecture, locales). A find-replace of the example name is not a successful install.
- Write adapters only for the tools they pick (`--tools`). Always write `AGENTS.md`.
- Keep `.agents/mcp_config.json` as `{"mcpServers": {}}`. Do not add MCP servers. Do not overwrite the developer's existing MCP / Continue / Aider / `kilo.jsonc` / `~/.gemini` configs.
- Do not copy `local.properties` `sdk.dir` or `~/.gemini` hostnames from another machine.
- `adb monkey` stays denied. Emulator deny only if they lock the install to a physical device.

Begin: print OS, this repo path, and whether you reused a kit clone or cloned a fresh one. Then run `setup-prompt.md` from its first heading.
