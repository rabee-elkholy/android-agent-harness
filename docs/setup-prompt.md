# Setup prompt

The installing agent **executes** this file (usually after the developer pasted [`install-prompt.md`](install-prompt.md) or [`update-prompt.md`](update-prompt.md) in a new chat on the Android app). Do not summarize it. Replacing the example app name alone is **not** a successful install.

---

You are installing a portable **Android AI harness** into THIS checkout. The kit is a clone of `android-harness-kit` (sibling, temp, or a path the developer gave). Copy from that clone’s `agents/` folder.

## Goal

Same **engine** (5-leaf review, live Gradle runner, safety hook). **Different product, machine, and team policy.** A find-replace of the example app name is **not** enough.

## Critical Installation Guardrails (Zero-Tolerance Rules)

1. **Read-Only Kit Source**: The kit directory (`<kit>` / `android-harness-kit`) is strictly **READ-ONLY**. NEVER edit, create, or modify any file in `<kit>`. All file copies, edits, patches, and configurations MUST occur strictly in the target Android repository (`<this-android-root>/.agents`).
2. **Scope Isolation (No Modifying App Source Code)**: Setup is strictly for configuring `.agents/` and AI tool rules. NEVER edit, rewrite, or modify the target application's production source code (e.g. `strings.xml`, `values-ar/strings.xml`, Kotlin files, or Room entities) to force preflight to pass. If preflight detects pre-existing issues in the app's codebase (such as untranslated strings or Room schema discrepancies), report them clearly to the developer in chat as pre-existing findings.
3. **No `schedule` Timers**: NEVER call the `schedule` tool or create background sleep/polling timers during setup. Execute commands synchronously or wait for automatic task completion via Reactive Wakeup.
4. **Mandatory Step 3b Approval**: The installer MUST present the domain references table to the developer via `ask_question` modal in Step 3b and obtain explicit approval before finalizing setup.

Before the wizard questions, tell the developer in their language **as a warning**: this setup needs a **strong model** in this chat, not a fast/cheap one. Install is a structural port. A weak model skips steps and leaves a broken helper. Stay until `Total test failures: 0`. If this chat is a small model, **stop** and start a new chat on a stronger model. Then: setup takes a few minutes (backup, port, selftest).

Answer in the developer's language. Do not commit unless they ask.

If `<repo>/.harness-setup/answers.json` exists and `"i0": true`, **skip section I**. Use those answers. Copy `.harness-setup/SETUP_ANSWERS.md` into the backup folder. Installer argv: `$PY <kit-or-.agents>/scripts/setup_wizard.py flags --repo <this-android-root>`.

Otherwise run `<kit>/agents/scripts/setup_wizard.py` (see [`install-prompt.md`](install-prompt.md)). Print the wizard JSON `model_warning` first, then `auto_blurb`. Ask **only** the objects in `questions` (usually eight: backup, app name, git, phone vs emulator, ask before install, unit tests, which tools, Zoho Sprints). Use each JSON `prompt` **verbatim**. Do **not** invent extra I.* questions. Do **not** invent five-word titles.

**Interview format:** The developer reads the **choice UI**. One form per JSON question. Options in the **same language** as the developer. Wait for required answers. Do not guess which tools they use (I.14), Zoho (I.16), or phone vs emulator (I.4). Do not rewrite `harness-rules.md` until I.0 / I.1 / I.3 / I.4 / I.10 / I.15 / I.14 / I.16 are answered.

Python, module, launcher, APK, architecture, and locales come from disk (`auto` in the wizard JSON). Defaults you must **not** ask: scaffold disabled (I.9), Gemini = merge script grants only if `~/.gemini` exists else skip (I.12 — never write a global Gemini rule during setup), tests only at the end (I.13). The wizard adds I.2 / I.5 / I.6 **only** when Python, module, or launcher is missing or ambiguous.

**Free text only** if they pick “Other” on I.1, I.5, or I.6.

## Detect environment (print in chat)

- OS: `darwin` / Windows / Linux. Do **not** assume Mac. Never copy another PC's paths.
- Tools: Claude Code, Codex, Antigravity/Gemini, Cursor, Copilot, Qwen Code, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, Goose — whatever exists. Do not require Antigravity. Write adapters **only** for the tools they pick in **I.14**.
- **`PY`**: try `python3 --version` then `python --version`. Windows `python3` is often a failing Store stub → use `python`. Ask I.2 only if the wizard JSON includes it (both work, or none work).
- `adb` and `./gradlew` / `gradlew.bat`. On macOS `chmod +x gradlew` if needed.

## 0) Backup FIRST (mandatory)

Do not write/delete `.agents` or user AI config until either a backup exists **or** they chose start-without-backup. If they asked for a backup and copy fails, **stop**.

Ask **I.0** before copying (see section I), unless `.harness-setup/answers.json` already recorded it. If `"backup": false`, **skip file copies** and tell them rollback will not work. Then:

If `"backup"` is true or unset (default): Timestamp `YYYYMMDD-HHMMSS`. Prune any previous backup directories under `.harness-backup/` so that **strictly only 1 backup copy is retained** (avoiding disk bloat while guaranteeing clean rollback). **A)** `<repo>/.harness-backup/<timestamp>/` for `.agents`, `.claude`, `.codex`, `.cursor`, `.github` (copilot/instructions only if present), `.windsurf`, `.roo`, `.amazonq`, `.continue`, `.junie`, `.kilocode`, repo `.gemini`, root `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`/`CODEX.md`/`QWEN.md`/`.cursorrules`/`.clinerules`/`.windsurfrules`/`.goosehints`. **B)** `$HOME/.harness-backups/<repo>-<timestamp>/` for `~/.gemini/config.json` + `rules/`, `~/.claude/settings*.json`, `~/.codex/config.toml` or `json` — no tokens/transcripts. Do **not** write `~/.gemini` during this install when another product on this PC already uses it (I.12). Append `.harness-backup/` to `.gitignore`. Manifest with yes/no per item. Rollback = `docs/rollback-prompt.md` (copied into the backup folder).

## 1) Place the engine

Copy kit `agents/` → `.agents/`. Empty `state/`. `.agents/.gitignore` = `state/` + `scripts/__pycache__/` + `mcp/zoho_sprints/__pycache__/` + `mcp/zoho_sprints/zoho_config.json`. Leave kit `mcp_config.json` empty until **I.16** is applied by `install_zoho_mcp.py`. Never copy a Zoho token file into the repo.

## 2) Discover from disk (do not invent)

Read Gradle, manifests, source:
- **Android Validation**: If no `gradlew`/`gradlew.bat` or no Android Gradle build files: **STOP**. Tell the developer `[ERROR] Target directory is NOT an Android project.`
- **Greenfield / Brand-New Project Support**: If the project is brand new or blank (< 4 source files, unconfigured architecture), do NOT stop! Instead, enter **Greenfield Bootstrap Mode**. The wizard `questions` payload will automatically include the detailed architectural foundation questions (`b_platform`, `b_arch`, `b_di`, `b_nav`, `b_ui`, `b_db`, `b_net`, `b_locales`) so the developer can establish their desired stack from day one.

Print a **proposed facts** table in chat (module, assemble task, APK path, applicationId, launcher, DI, VM base, Room yes/no, theme, source roots, string files). Never assume `:app` or `app-debug.apk`. If `local.properties` missing: tell them Android Studio must write `sdk.dir` — do not invent a path.

Print `model_warning` then `auto_blurb` from the wizard JSON. Then ask **only** the `questions` array (section I). Do not re-ask facts already in `auto`.

## I) Interview — only what the wizard JSON lists

Ask **only** `questions` from `setup_wizard.py questions`. Typically seven forms:

### I.0 Backup? (required)

- **Modal prompt:** Setup will replace the AI helper files in this project. A backup lets you restore them if something goes wrong. Without a backup, the old files cannot be restored.
- **Choices:** `Back up and start` (Recommended) / `Start without a backup` / `Stop setup`

### I.1 App name (required)

- **Modal prompt:** What name should the helper use for this app? I found “<discovered>”. Reviews and AGENTS.md will show that name.
- **Choices:** `Use “<discovered>”` (Recommended) / `Other name (I will type it)`
- **Free text** only if they pick Other.

### I.3 Git (required)

- **Modal prompt:** Who should create git commits? If you are not sure, keep commits in your own hands (you commit from the IDE).
- **Choices:** `I commit myself` (Recommended) / `The agent may commit when I ask in chat`

### I.4 Phone or emulator? (required)

- **Modal prompt:** Will you test this app on a real phone, an emulator (AVD), or both? Pick both unless you never use an emulator. Physical only blocks emulator install and logcat.
- **Choices:** `Phone and emulator both allowed` (Recommended) / `Physical phone only — no emulator`
- **If both allowed:** relax “physical only” in `harness-rules.md`, `pre_tool_safety.py` (do **not** deny `emulator-` serials or `emulator`/`avdmanager`), `run_device.py`, `logcat_doctor.py`, `capture_screen.py`, adapters, and do not add emulator to the Gemini `deny` list. Keep `adb monkey` denied. Rewrite entire `if emulator` blocks (do not leave an empty `if`). Flip selftest `emu` to `allow`.
- **If physical only:** keep the kit’s physical-only denies.

### I.10 Ask before install? (required)

- **Modal prompt:** Before the helper installs the app on the phone or emulator, should it ask you first? Asking avoids installing on the wrong device. Skipping is faster if you trust the serial.
- **Choices:** `Ask me first` (Recommended) / `Install without asking`
- **If ask:** `harness-rules.md` requires one confirmation before `run_device.py` / `adb install` in a session.
- **If without asking:** do not add that confirmation. Keep `adb monkey` denied.

### I.15 Unit tests? (required)

- **Modal prompt:** After the helper finishes code and review, should it run unit tests (checks logic without opening the app)? Pick no if this project has no tests and you will not add them.
- **Choices:** `Yes, run unit tests` (Recommended) / `No, skip unit tests`
- **If yes:** keep a targeted `:<module>:testDebugUnitTest` step after the 5 leaves and before assemble. Use **this** module. Drop leftover payment-test paths unless they exist here. If there is no `src/test` yet, still leave the step — the agent must not invent fake tests.
- **If no:** remove the unit-test step from `harness-rules.md` section 3, `workflows/deliver.md`, and `gradle-build-optimizer`. Do **not** skip the 5-leaf review or assemble. Do not require TDD.

### I.14 Coding tools (required)

- **Modal prompt:** Which programs do you open this project in? Select every one you use. If you use Cursor, you must select Cursor so its rules get written.
- **Choices (multi-select):** `Cursor` / `Claude Code` / `GitHub Copilot` / `Gemini / Antigravity` / `Codex` / `Qwen Code` / `Windsurf` / `Cline` / `Roo` / `Amazon Q` / `Continue` / `Junie` / `Kilo` / `Goose` / `All of them`
- Wait. Do not default to all. Do not default to only the tool running this chat.

### I.16 Zoho Sprints (required)

- **Modal prompt:** use the wizard JSON `prompt` verbatim. Setup will not ask for tokens and will not copy them.
- **Choices:** enable / skip. If a user-level Zoho config already exists on this PC, enable is recommended. Otherwise skip is recommended.
- **If skip:** run `$PY .agents/scripts/install_zoho_mcp.py --repo <this-android-root> --py <I.2> --tools <I.14 ids> --disable` so a leftover `.cursor/mcp.json` Zoho entry is removed. Keep `.agents/mcp_config.json` empty.
- **If enable:** follow the Zoho setup flow below.
- Never write `~/.gemini/config/mcp_config.json`. Never paste tokens in chat.

#### Zoho setup flow (only when I.16 = enable)

1. **Check for existing credentials** on this PC: `~/.android-harness/zoho_sprints.json` or `~/.gemini/antigravity/scratch/zoho_sprints/zoho_config.json`.
2. **If credentials exist:** tell the developer you found them and will reuse them. Skip to step 6.
3. **If no credentials:** ask the developer with `ask_question`:
   - `Set up Zoho credentials now` / `I will set them up later`
4. **If later:** run `$PY .agents/scripts/install_zoho_mcp.py --repo <this-android-root> --py <I.2> --tools <I.14 ids> --enable`. Tell them to fill `~/.android-harness/zoho_sprints.json` with the fields from `config.example.json` when they are ready. Skip to step 7.
5. **If now:** guide the developer through credential setup:
   - Tell them: "You need a Zoho API console self-client. Here are the steps:"
   - **Step A:** Go to https://api-console.zoho.com/ and create a **Self Client**.
   - **Step B:** Generate a grant token with scope: `ZohoSprints.sprints.ALL,ZohoSprints.items.ALL,ZohoSprints.team.READ`
   - **Step C:** Exchange the grant token for a refresh token using the Zoho OAuth endpoint.
   - **Step D:** Ask the developer for these values (one `ask_question` with free text):
     - `client_id`
     - `client_secret`
     - `refresh_token`
     - `team_id` (from their Zoho Sprints URL: `https://sprints.zoho.com/team/<team_id>/...`)
     - `project_id` (from their Zoho Sprints URL: `https://sprints.zoho.com/team/<team_id>/project/<project_id>/...`)
   - Write these to `~/.android-harness/zoho_sprints.json` in the format of `config.example.json`. Never copy this file into the repo.
6. **Wire MCP:** run `$PY .agents/scripts/install_zoho_mcp.py --repo <this-android-root> --py <I.2> --tools <I.14 ids> --enable`.
7. **Fill workflow defaults:** ask the developer:
   - What prefix to use for sprint items (e.g. `"App-I"`, `"PRJ-I"`)?
   - What names should be stripped from ticket titles (their name in English and/or Arabic)?
   - Write these to `.agents/mcp/zoho_sprints/workflow_defaults.json`. Leave `default_user_id`, `fallback_item_type_id`, `fallback_priority_id`, `fallback_sprint_id` empty — the server resolves them at runtime when blank.

### I.2 / I.5 / I.6 — only if they appear in the JSON

Ask them with the JSON `prompt` verbatim (ambiguous Python, several app modules, or several launchers).

### Do not ask (already in `auto` / answers.json)

- **I.6b / I.7 / I.8:** APK path, stack, locales from disk. Use discovered stack. Rewrite architecture skills to match **this** app (do not keep kit placeholder architecture unless it matches disk).
- **I.9:** always disable `new_feature_scaffold.py` `main()`. Keep `VIEWMODEL` / `SCREEN` constants for `_hook_selftest.py`.
- **I.11:** always add `.agents/` to `.gitignore`. Helper rules stay on the machine that ran setup, even on a team. Teammates install their own copy. Do not commit `.agents` during this setup.
- **I.12:** if `~/.gemini` exists, merge script grants only. Never write a global Gemini rule during this setup.
- **I.13:** tests only (selftest + preflight). Do not run `:assembleDebug` at the end unless answers say assemble.

Record all answers in `.harness-backup/<timestamp>/SETUP_ANSWERS.md`.

## 3) Port structurally (use answers)

**Keep:** 5 reviewers; `*_PASS`; no `code-review-guard-agent`; no `LGTM`; `$PY .agents/scripts/run_gradle_task.py`; `$PY .agents/scripts/run_device.py`; do not skip reviews.

Patch **all** product constants (`docs/porting.md`): write `.agents/scripts/_product.py` from `applicationId`, launcher, assemble task, APK path, and source-root Path pieces. Rewrite `harness-rules.md` (I.1 name, I.3 git, I.4 device, I.15 tests). Glob `**/outputs/apk/debug/*.apk` if the filename is unknown. KMP: `androidMain`, not `src/main` after renaming only `"app"`.

Apply **I.7**: rewrite or stub skills so reviewers cannot cite ads/streak/GPS/Room/MVI/Hilt/theme wrappers unless this checkout has them. See **3b** for the full reference-fill protocol. **Always disable** scaffold `main()` (keep `VIEWMODEL`/`SCREEN` constants for `_hook_selftest.py`). `logcat_doctor` / `perf_guard` / `fast_kt_lint` use **this** `applicationId` via `_product.py` and the real source roots. `run_device.py` uses **I.6**. Apply **I.4**: physical-only keeps emulator denies; both-allowed = allow emulator serials — rewrite entire `if emulator` blocks (do not leave an empty `if`). Flip selftest `emu` to `allow` only when I.4 is not physical-only. Apply **I.15** (unit tests yes/no) in `harness-rules.md` / `deliver.md`. `harness-rules.md` uses **I.1–I.8** and git policy **I.3**. Keep the generic Zoho Sprints section; I.16 only wires MCP. **I.8:** one locale → skip AR/EN parity.

### 3b) Dynamic Domain Discovery & Custom Reference Creation (with developer approval)

The kit ships clean foundation references in `.agents/skills/android-harness/references/` (`architecture-mvi.md`, `ui-compose-theme.md`, `performance-anr-optimization.md`, `room-database-migrations.md`, `automated-skills.md`, `daily-scenarios.md`). During install, the installer agent MUST dynamically discover the project's actual core domains and create tailored reference files.

#### 1. Foundation References (Always Port & Fill):
1. **`architecture-mvi.md`**: 
   - **For Established Codebases**: Read Gradle, `libs.versions.toml`, and ViewModels / DI modules to port DI framework, ViewModel base, Navigation, State pattern, and Layer conventions.
   - **For Greenfield / Brand-New Projects**: Write `architecture-mvi.md` directly using the developer's recorded `bootstrap_details` (Platform, Architecture pattern, DI, Navigation, Database, Networking, Locales), establishing the clean architectural foundation for the new project from day one!

2. **`ui-compose-theme.md`**:
   - Detect Compose Multiplatform vs AndroidX Compose.
   - Document the real theme function (`AppTheme` / `MaterialTheme`), typography tokens, and preview patterns (`CompositionLocalProvider(LocalLayoutDirection...)` for KMP, `locale = "ar"` for AndroidX).

3. **`performance-anr-optimization.md`**:
   - Keep generic (UI thread safety, coroutine dispatchers, memory leaks, Compose recomposition stability).

4. **`room-database-migrations.md`**:
   - If `@Database` exists: fill with real `AppDatabase` class name and entities.
   - If no Room: delete this file or keep a minimal note ("No Room database in this project").

#### 2. Dynamic Domain Discovery & Custom Reference Creation:
Scan all module folders (`features/`, `core/`, `domain/`, etc.), packages, and Gradle dependencies to identify the project's actual core domains. For any major domain found in the project, **create a new dedicated reference file** in `.agents/skills/android-harness/references/`:
- **Audio / Media**: (ExoPlayer, Media3, SoundPool, AudioPlayer) -> Create `audio-media-playback.md`
- **Networking & API**: (Ktor client, Retrofit, WebSockets, GraphQL) -> Create `networking-api-contracts.md`
- **Hardware / IoT / Bluetooth**: (BLE, USB, CameraX, NFC, Wi-Fi) -> Create `hardware-bluetooth-camera.md`
- **Ads / Mediation**: (AdMob, AppLovin, UnityAds, UMP) -> Create `ad-mediation-privacy.md`
- **Payments / Billing**: (Google Play Billing, Stripe, RevenueCat) -> Create `payment-gateways-architecture.md`
- **Location / Maps**: (GPS, Google Maps, Mapbox, LocationManager) -> Create `location-maps-services.md`
- **Domain-Specific Engines**: e.g., Education & Alphabet Games, Shopping Cart & Checkout, Chat & Messaging -> Create `<feature-name>-system.md`
- **Local Storage / Caching**: (SQLDelight, KeyValueCache, DataStore) -> Create `local-cache-storage.md`

#### 3. Update `daily-scenarios.md`:
- Register and link to ALL active domain references (foundation + newly discovered).

#### 4. Present Approval Table:
Present a clear summary table to the developer showing:
- Foundation references filled
- Discovered domain references created
Ask for approval via `ask_question` modal before proceeding:
- `Approve the reference files` / `I have changes to make`

## 4) Leftover grep

Must not find the parent-product leftovers listed in `docs/porting.md` (After port). Theme-wrapper name only if they kept it. `HARNESS_REVIEW_PACKAGE` may stay.

Do not write forbidden tokens even in “do not use …” sentences.

## 5) Wire tools

`hooks.json` lives in `.agents/` for Antigravity. Write adapters **only** for the tools from **I.14**. Run:

```
$PY .agents/scripts/install_tool_adapters.py --product <I.1> --py <I.2> --assemble <I.5 assembleDebug task> --device-policy <allow|physical-only from I.4> --git-policy <never|agent-may-commit from I.3> --tools <comma ids from I.14>
```

`--tools` examples: `cursor,gemini` or `claude,copilot` or `all`. Map I.14 labels to ids: `cursor` `claude` `copilot` `gemini` `codex` `qwen` `windsurf` `cline` `roo` `amazonq` `continue` `junie` `kilo` `goose`. `--tools all` if they picked every tool.

`--device-policy allow` if I.4 is both-allowed. `--device-policy physical-only` only if they locked to a physical device. `--git-policy never` unless I.3 allows commits.

That script fills `.agents/tool-adapters/*.template`, always writes `AGENTS.md`, writes the selected tool files, generates `.claude/agents/*.md` only when `claude` is selected, and **deletes** previously managed adapters for tools that were not selected. Details: kit `docs/tool-support.md`.

Then Zoho MCP from **I.16**:

```
$PY .agents/scripts/install_zoho_mcp.py --repo <this-android-root> --py <I.2> --tools <comma ids from I.14> --enable
```

Use `--disable` when I.16 is skip (or `zoho_mcp` is missing on an old answers.json). Do **not** copy token files. Do **not** write `~/.gemini/config/mcp_config.json`.

Follow **I.12** from answers: merge script grants only when `gemini_config` is `merge-allowlist`. Do **not** write a global Gemini rule. Never copy `remoteControlHostname` or tokens. Never set `sdk.dir` in harness files. Do not overwrite `.aider.conf.yml`, Continue user configs, `kilo.jsonc`, or `~/.gemini`.

## 6) Verify

`$PY .agents/scripts/_hook_selftest.py` → `Total test failures: 0`.  
`$PY .agents/scripts/preflight_check.py` → pass.  
Confirm adapter files exist for **I.14** only (always `AGENTS.md`; Cursor `.mdc` starts with `---`; `GEMINI.md` if Gemini was selected). Do not require CLAUDE.md / Copilot / Cline unless those tools were chosen.  
Assemble only if **I.13 = yes**.

## 7) Tell the developer

New session on this folder. Five `*_PASS` before real delivery. Rollback = `docs/rollback-prompt.md`.
