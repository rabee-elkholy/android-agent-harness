# Install or Update prompt

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v0.27.0/docs/install-or-update-prompt.md`  
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v0.27.0` — **SHA-256**: `8c93a673a652021912342f8dbc53cd60a8a0cd5bea67cc61724a0a76acb290ad` (SHA-256 of every byte after this line; verify first — mismatch = STOP)
---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value (Python: `import hashlib, urllib.request; data = urllib.request.urlopen('<Raw Prompt URL>').read(); payload = b''.join(data.splitlines(keepends=True)[5:]); assert hashlib.sha256(payload).hexdigest() == '<SHA-256>'`). If it does not match, STOP and tell the developer the file was tampered with.

You are installing or updating the portable **Android AI harness** into **this** checkout. This folder is the Android product. It is not `android-agent-harness`.

Answer in the developer's language. Do not commit unless they ask. Do not only rename the example app.

Tell the developer **first**, in their language, as a warning they must read: this setup needs a **strong reasoning model** in this chat (such as Anthropic `Claude Opus 5 / 3.7 Sonnet (Thinking)`, Google `Gemini 3.1 Pro (Deep Think)`, OpenAI `GPT-5.6 Sol / o3`, or DeepSeek `DeepSeek-V4 Pro / R1`), not a fast/lightweight one without deep reasoning. Install is a structural port (package, module, APK, architecture, leftover grep, selftest). A weak model skips steps, shortens questions, and leaves a broken helper. They should stay until selftest `Total test failures: 0`. If they say this chat is a small model, **stop** and tell them to open a new chat on a stronger model, then paste this file again.

Then tell them: the wizard asks only the questions it returns (backup, app name, git policy, device policy, install confirmation, unit tests, tools, Zoho, language, tracker, and git gate; conditional Python/module/launcher/flavor/bootstrap questions may also appear), then backup, port, and selftest. Stopping early yields a weak harness.

## Start now

1. **Target Project Verification (Fail-Fast)**:
   - **Android Project Check**: Confirm this repo has `gradlew` or `gradlew.bat` AND Android Gradle build files (`build.gradle` / `build.gradle.kts`). If not, **STOP IMMEDIATELY** and tell the developer in their language:
     `[ERROR] Target directory is NOT an Android project. Android Agent Harness requires a Gradle-based Android or Kotlin Multiplatform project.`
   - **Greenfield / Established Codebase Support**:
     - If this is an **established codebase**, the wizard will automatically discover your architecture, DI, ViewModels, and UI from disk.
     - If this is a **brand-new / blank project**, the wizard will automatically guide you through the **Greenfield Bootstrap Questionnaire** (Platform, MVI/MVVM, Koin/Hilt, Voyager/ComposeNav, Room/SQLDelight, Ktor/Retrofit) to establish the architectural blueprint and governance rules from day one.
2. **Get the Kit (Remote & Local Support)**:
    - Preferred: run `android-harness init --repo <this-android-root>`. The CLI resolves a release tag, provisions the kit at detached `v<version>`, and verifies that `agents/VERSION` matches the tag. It never provisions from `main`.
    - For a manual kit clone, fetch and check out an exact release tag before copying anything (clean and reset first so checkout never aborts):
      ```bash
      git -C android-agent-harness reset --hard HEAD 2>/dev/null || git clone --no-checkout https://github.com/rabee-elkholy/android-agent-harness.git
      git -C android-agent-harness clean -fd
      git -C android-agent-harness fetch origin --tags --prune
      git -C android-agent-harness checkout --detach v<requested-version>
      ```
      Verify `android-agent-harness/agents/VERSION` equals `<requested-version>`. Do **not** clone into `app/`, `composeApp/`, or any module source tree, and do **not** pull `main`.
3. **Answers first (do not invent short questions).** The wizard is English-first; when asking in chat, pose each question in the developer's language.
   - Preferred: they run this in **their** terminal, then tell you when it finishes:
     `$PY <kit>/agents/scripts/setup_wizard.py --repo <this-android-root>`
    - If they want you to ask in chat: run `$PY <kit>/agents/scripts/setup_wizard.py questions --repo <this-android-root>` **ONCE** into a single JSON object. Extract `model_warning`, `auto_blurb`, and the `questions` array directly from that single object. **DO NOT** run `setup_wizard.py questions` multiple times.
      *(Note: When updating or re-running on an existing project, the wizard automatically reads previous answers from `.harness-setup/answers.json` and marks each previous choice as `(Recommended)` at index 0).*
      Print `model_warning` in chat first (developer language), then `auto_blurb`. Then `ask_question` using each JSON `questions[].prompt` **verbatim**. Ask **only** that list; the JSON payload is the sole interview authority. Then write a JSON file of ids → values and `$PY <kit>/agents/scripts/setup_wizard.py write --repo <this-android-root> --answers-json <that-file>`.
   - Stop if I.0 is no / wizard exit 1. Do not copy `.agents`.
4. When `<this-repo>/.harness-setup/answers.json` exists with `"i0": true`, execute the deterministic engine in one command:
   `$PY <kit>/agents/scripts/install_or_update.py --repo <this-android-root> --kit <kit>`
   This single atomic command automatically creates the backup, preserves tailored reference files (.agents/skills/android-harness/references/*.md), places .agents/, generates _product.py, wires tool adapters, pre-warms and caches the universal Code Graph (.agents/cache/project_graph.json), configures PM tracking, updates .git/info/exclude, and runs selftest/doctor verification with 0 failures in under 3 seconds.
   - **Tailored References Preservation**: On update sessions, existing tailored reference files (`.agents/skills/android-harness/references/*.md`) are preserved AS-IS without adding new ones. The installer MUST list them with clickable links (`[filename.md](file:///<path>)`) in the `ask_question` modal and inform the developer in their language that they can click and review each file before confirming.
5. **Final Completion Card (No Redundant Tasks)**:
   - Because `install_or_update.py` ALREADY runs 12-dimension doctor verification and hook selftests internally, do **NOT** launch redundant separate `harness_doctor.py` or `preflight_check.py` background tasks after it succeeds.
   - Output the **Harness Updated Successfully** completion card immediately, including the **Update Summary** table and a concise **What's New in v<version> (Highlights since v<previous-version>)** bulleted list extracted from the installer output.
   - Tell them to start a **new chat** on this Android folder before starting daily work.

Kit rules that still apply during setup:

- **Strict Read-Only Kit Source**: Never modify or write files in `<kit>` (`android-agent-harness`). Port and configure strictly into `<this repo>/.agents`.
- **Scope Isolation**: Setup configures `.agents/` only. Never edit app production files (`strings.xml`, Kotlin files) during install. Report pre-existing preflight issues in chat.
- **Zero-Noise Chat & Strict Anti-Polling Protocol**:
  - Always run terminal/python commands with `WaitMsBeforeAsync: 30000` (or 60000) so commands complete synchronously without backgrounding.
  - **STRICT PROHIBITION**: NEVER call `manage_task(Action='status')` in a loop.
  - If a command is sent to the background as a task, the agent MUST STOP CALLING TOOLS IMMEDIATELY and END TURN with zero chat text `""` (do not print `# Background Task Started` or any progress message in chat). Wait passively for the genuine platform system message (`finished with result:`) before dispatching dependent tools.
  - NEVER call `schedule` or create sleep timers.
- **Mandatory Step 3b Approval & Reference Preservation**: On update sessions, restore all existing tailored reference files (.agents/skills/android-harness/references/) AS-IS without adding new ones, and ask the developer via `ask_question` to approve keeping them (with clickable `file:///` links for IDE review). On first-time installs, discover domains, create custom references, and obtain approval.
- **Previous Answers Recommendation**: When updating or re-running setup on an existing project, previous answers must be presented as `(Recommended)` at index 0.
- Backup before overwriting `.agents` or tool adapters.
- Structural port (package, regex, Path pieces, APK name, architecture, locales). A find-replace of the example name is not a successful install.
- Write adapters only for the tools in answers.json (`--tools`). Always write `AGENTS.md`.
- Kit `agents/mcp_config.json` stays empty. After copy, run `install_zoho_mcp.py` from I.16. **Never copy** a Zoho token file, `zoho_config.json`, or OAuth values into the repo. If I.16 is enable, point `ZOHO_SPRINTS_CONFIG` at an existing user-level file when one is already on this PC. Do not overwrite the developer's other MCP / Continue / Aider / `kilo.jsonc` / `~/.gemini` configs.
- Do not copy `local.properties` `sdk.dir` or `~/.gemini` hostnames from another machine.
- `adb monkey` stays denied. Emulator deny only if they lock the install to a physical device.

Begin: print the strong-model warning in the developer's language. Then print OS, this repo path, and whether you reused a kit clone or cloned a fresh one. Then step 3 (wizard).
