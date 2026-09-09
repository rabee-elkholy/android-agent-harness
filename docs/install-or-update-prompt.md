# Install or update Android Agent Harness

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.0/docs/install-or-update-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v1.0.0` — **SHA-256**: `4f585d435b2745ff63ddd6bcb41c7078df6980149ec8225b6a6fd527516dd6a7` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

---
Before executing anything: verify that the SHA-256 of every byte after the **SHA-256** header line equals the header value. If it does not match, STOP and tell the developer the file was tampered with.

You are operating inside the Android project root checkout (`<app-root>`). Keep all conversational discussion in the developer's preferred language (e.g. Arabic or English) and all repository code artifacts strictly in English.

> **Pre-release Note**: Before `v1.0.0` is published and tagged on GitHub, manual testing uses an immutable exact commit URL (`https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/<EXACT_COMMIT>/docs/install-or-update-prompt.md`). The only authorized kit source is the immutable tag `v1.0.0` (or exact commit) from `https://github.com/rabee-elkholy/android-agent-harness.git`. Never use, clone, pull, or resolve the floating `main` branch.

---

### Phase 1: Read-Only Project Discovery

Perform read-only inspection first. **STRICT RULE**: Do NOT edit files, do NOT run Gradle builds, and do NOT download the kit in this phase.

1. **Gradle Wrapper Verification (Fail-Fast)**:
   Confirm the current directory has a root `gradlew` or `gradlew.bat`. If missing, STOP immediately and explain in the developer's language:
   `[ERROR] Target directory is NOT an Android project (missing gradlew/gradlew.bat).`
2. **Lifecycle State Detection**:
   Inspect existing harness markers in `<app-root>`:
   - **Clean install**: `.harness-setup/ownership-v1.json` does NOT exist and no `.agents` or `.agent` directory exists.
   - **Same-major update**: `.harness-setup/ownership-v1.json` exists and its installed architecture major is `1`.
   - **Legacy replacement**: pre-v1 `.agents` or `.agent` exists without `.harness-setup/ownership-v1.json`. It must be previewed and removed via ownership-safe legacy cleanup, followed by a clean v1 install; never migrate in place.
3. **Android Configuration Discovery**:
   - Inspect `settings.gradle` / `settings.gradle.kts` to identify application modules (e.g. `:app`, `:composeApp`) and library modules.
   - Inspect application module `build.gradle` / `build.gradle.kts` to detect `applicationId`, build variants / flavors, and UI toolkit (Jetpack Compose vs XML views).
   - Inspect `AndroidManifest.xml` to discover launcher activity name.
   - Inspect repository root for existing AI tool adapters (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules`, etc.).

---

### Phase 2: Chat Interview (Setup Questions)

The setup wizard payload is the sole interview authority. Do not invent static questions or assume modules that do not exist.

1. **Prepare Kit for Dynamic Discovery**:
   Use the user-level cache `<kit-dir>` (`~/.android-harness/kit` on Linux/macOS, `%USERPROFILE%\.android-harness\kit` on Windows). If `<kit-dir>` is already prepared at `v1.0.0` with valid checksums, reuse it. Otherwise, fetch and verify into user cache as detailed in Phase 5.
2. **Execute Wizard Discovery**:
   Run the read-only discovery command once into a single JSON object:
   ```bash
   python "<kit-dir>/agents/scripts/setup_wizard.py" questions --repo "<app-root>"
   ```
   Extract `auto_blurb` and the `questions` array. Print `auto_blurb` in chat to summarize discovered facts.
3. **Ask Dynamic Questions**:
   Ask **only** the questions returned in the `questions` array. When asking in chat, use the developer's conversation language, with recommended choices marked **(Recommended)** (the wizard automatically positions previous/detected choices as option 1).

   **Canonical Questions Reference**:
   - `i0`: Install & Backup Confirmation (`yes` [Recommended], `skip`, `no`)
   - `i14`: AI Tool Adapters (`gemini` [Recommended], `claude`, `codex`, `cursor`, `copilot`, `all`)
   - `i1`: Product Name (discovered application name)
   - `i5`: Application Module (only asked if multiple application modules exist; skipped if only one module is detected)
   - `i19`: Build Variant / Flavor (only asked if custom product flavors exist; skipped for standard debug)
   - `i3`: Git Commit Policy (`never` [Recommended] — agent never commits, `agent-may-commit`)
   - `i20`: Project Management & Task Tracker (`zoho_sprints` [Recommended], `github_projects`, `jira_mcp`, `linear_mcp`, `none`)
   - `i18`: Task Tracker Language Policy (only asked when `i20` is not `none`):
     - 1) `en_titles_ar_comments` (English task titles, Arabic descriptions/comments) — **(Recommended)**
     - 2) `all_en` (All English)
     - 3) `all_ar` (All Arabic)
   - `i16`: Zoho Sprints MCP Integration (only asked when `i20` is `zoho_sprints`):
     - 1) `skip` (Skip local token configuration) — **(Recommended)**
     - 2) `enable` (Configure Zoho Sprints MCP)
   - `i15`: Unit Tests Policy (`yes` [Recommended], `no`)
   - `i4`: Device Testing Policy (`allow` [Recommended], `physical-only`, `skip`)

4. **Persist Answers**:
   Write the collected answers to a temporary JSON file `<temp-answers>.json`.

---

### Phase 3: References & Tailored Knowledge Preservation

- **On Updates**: Scan `.agents/skills/android-harness/references/` and list all existing tailored markdown references with clickable `file:///` links. Guarantee they are preserved verbatim.
- **Zoho & MCP Defaults**: Guarantee `.agents/mcp/zoho_sprints/workflow_defaults.json` and user-level credentials are never overwritten or mutated during setup.

---

### Phase 4: Exact Plan & Explicit Approval Gate

Present a comprehensive installation plan in chat detailing:
- **Detected Lifecycle Path**: Clean Install, Same-Major Update, or Legacy Replacement.
- **Kit Source**: Immutable release tag `v1.0.0` (never floating `main`).
- **User-Level Cache**: `~/.android-harness/kit`.
- **Target App Files**: List files to be created (`.agents/`, `.harness-setup/answers.json`, `.harness-setup/ownership-v1.json`, configured adapters).
- **Executable Non-Interference Guarantee**: A cryptographic pre-install snapshot of all Android product files (`src/`, `build.gradle*`, `gradlew*`) will be recorded. A post-install snapshot comparison ensures zero unauthorized file modifications, triggering automated rollback if violated.
- **Exact Shell Commands**: Present all exact commands to be executed.

> [!CAUTION]
> **STOP AND WAIT FOR EXPLICIT DEVELOPER APPROVAL.**
> Pasting this prompt does not constitute authorization. Do NOT clone the kit, do NOT write files, and do NOT alter the repository until the developer explicitly responds with approval (e.g. "Approve").

---

### Phase 5: Verified Kit Bootstrap (After Approval)

Only after explicit approval, prepare the engine kit at user-level cache `<kit-dir>` (`~/.android-harness/kit`):

1. If `<kit-dir>` already exists with valid engine at `v1.0.0` and valid checksums, reuse it.
2. Otherwise, fetch into a temporary staging folder (`<staging-dir>`):
   ```bash
   git clone --depth 1 --branch v1.0.0 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git <staging-dir>
   git -C <staging-dir> describe --tags --exact-match
   ```
3. **Pre-Execution Integrity Verifier**:
   Before importing or running any kit scripts, run a standard library Python check:
   - Verify `agents/VERSION` equals `1.0.0`.
   - Verify every file in `agents/release_checksums.json` matches its SHA-256 hash.
   - Reject symlinks or out-of-boundary paths.
   *(Note: Release checksums verify integrity against corruption and accidental tampering; signed releases remain the cryptographic trust boundary).*
4. **Windows-Safe Atomic Promotion**:
   If `<kit-dir>` already exists, rename `<kit-dir>` to `<kit-dir>.previous`, move `<staging-dir>` to `<kit-dir>`, validate engine, and purge `<kit-dir>.previous`. On failure, restore `<kit-dir>.previous`.

---

### Phase 6: Official Execution

Write the collected answers to a temporary JSON file `<temp-answers>.json`, then execute the official lifecycle path non-interactively:

- **Clean Install**:
  ```bash
  python "<kit-dir>/harness_cli.py" init --repo "<app-root>" --kit "<kit-dir>" --answers-json "<temp-answers>.json"
  ```
- **Same-Major Update**:
  ```bash
  python "<kit-dir>/harness_cli.py" update --repo "<app-root>" --kit "<kit-dir>"
  ```
- **Legacy Replacement** (in approved order):
  ```bash
  python "<kit-dir>/harness_cli.py" uninstall --repo "<app-root>" --legacy
  python "<kit-dir>/harness_cli.py" uninstall --repo "<app-root>" --legacy --apply
  python "<kit-dir>/harness_cli.py" init --repo "<app-root>" --kit "<kit-dir>" --answers-json "<temp-answers>.json"
  ```

*(The CLI automatically removes `<temp-answers>.json` after processing).*

---

### Phase 7: Doctor & Verification

1. Run the diagnostic engine:
   ```bash
   python "<kit-dir>/harness_cli.py" doctor --repo "<app-root>" --kit "<kit-dir>" --json
   ```
2. Report diagnostic status honestly. Confirm that the application non-interference snapshot verified 0 modified app files.
3. Display the installation summary card and advise the developer:
   **"Android Agent Harness is successfully configured. Please open a NEW chat session at the project root to begin daily development."**
