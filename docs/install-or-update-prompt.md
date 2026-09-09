# Install or update Android Agent Harness

> **Raw Prompt URL**: `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/v1.0.0/docs/install-or-update-prompt.md`
> **Kit Repository**: `https://github.com/rabee-elkholy/android-agent-harness.git`
> **Kit version**: `v1.0.0` — **SHA-256**: `0238164e5071178d2e5b98415375ece7ce5016e90ea82ed9cf7361b73554ad57` (SHA-256 of every byte after this line; verify first — mismatch = STOP)

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

### Phase 2: Approved Kit Bootstrap & Chat Interview

The setup wizard payload is the sole interview authority. Do not invent static questions or assume modules that do not exist.

1. **Inspect the Kit Cache Read-Only**:
   Use `<kit-dir>` (`~/.android-harness/kit` on Linux/macOS, `%USERPROFILE%\.android-harness\kit` on Windows). Without importing or executing kit code, verify with Python standard-library operations that the cache is a regular, boundary-safe checkout of `v1.0.0`, `agents/VERSION` is `1.0.0`, and every entry in `agents/release_checksums.json` matches. If it is valid, reuse it.
2. **Bootstrap Approval Gate (Only If the Cache Is Missing or Invalid)**:
   Present the exact clone, verification, staging, promotion, replacement, and rollback commands before running them. State every user-cache path that may be created, replaced, or removed.

   > [!CAUTION]
   > **STOP AND WAIT FOR EXPLICIT KIT BOOTSTRAP APPROVAL.**
   > Do not download, clone, create, replace, rename, or remove any kit-cache file before the developer explicitly approves this bootstrap plan. This approval authorizes only the stated user-cache bootstrap; it does not authorize installing, updating, or removing anything in `<app-root>`.

   After bootstrap approval, fetch into a temporary staging folder (`<staging-dir>`):
   ```bash
   git clone --depth 1 --branch v1.0.0 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git <staging-dir>
   git -C <staging-dir> describe --tags --exact-match
   ```
   Before importing or running kit scripts, use a standard-library-only verifier to confirm `agents/VERSION`, every checksum, and the absence of symlinks or out-of-boundary paths. If verification fails, remove only `<staging-dir>` and STOP. If it passes, promote it atomically: rename an existing `<kit-dir>` to `<kit-dir>.previous`, move `<staging-dir>` to `<kit-dir>`, revalidate, then remove `<kit-dir>.previous`. Restore `<kit-dir>.previous` if promotion or revalidation fails.
3. **Execute Wizard Discovery**:
   Run the read-only discovery command once into a single JSON object:
   ```bash
   python "<kit-dir>/agents/scripts/setup_wizard.py" questions --repo "<app-root>"
   ```
   Extract `auto_blurb` and the `questions` array. Print `auto_blurb` in chat to summarize discovered facts.
4. **Ask Dynamic Questions**:
   Ask **only** the questions returned in the `questions` array. When asking in chat, use the developer's conversation language, with recommended choices marked **(Recommended)** (the wizard automatically positions previous/detected choices as option 1).
   Respect each returned question's `required`, `allow_multiple`, `options`, and `depends_on` fields exactly. Do not use a separately maintained question list or offer an option that is absent from the payload.
5. **Hold Answers In Memory**:
   Keep the collected answers in memory. Do not write `<temp-answers>.json` or any other file yet.

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
> Pasting this prompt and approving the kit bootstrap do not authorize an app-root mutation. Do not write the answers file, install, update, remove, or alter `<app-root>` until the developer explicitly approves this exact lifecycle plan (e.g. "Approve clean install").

---

### Phase 5: Post-Approval Preparation

Only after the explicit lifecycle approval from Phase 4:

1. Revalidate the already prepared `<kit-dir>` without modifying it. If its tag, version, boundary checks, or checksums changed since the interview, STOP and request a new bootstrap plan and approval.
2. Create `<temp-answers>.json` in the operating system's temporary directory, outside `<app-root>`, using the exact in-memory answers collected from the wizard payload.
3. Record the pre-install application snapshot immediately before the approved lifecycle command.

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
