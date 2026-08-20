# Setup prompt

The installing agent **executes** this file (usually after the developer pasted [`install-prompt.md`](install-prompt.md) or [`update-prompt.md`](update-prompt.md) in a new chat on the Android app). Do not summarize it. Replacing the example app name alone is **not** a successful install.

---

You are installing a portable **Android AI harness** into THIS checkout. The kit is a clone of `android-harness-kit` (sibling, temp, or a path the developer gave). Copy from that clone’s `agents/` folder.

## Goal

Same **engine** (5-leaf review, live Gradle runner, safety hook). **Different product, machine, and team policy.** A find-replace of the example app name is **not** enough.

Before I.0, tell the developer in their language: setup takes time (wizard questions, backup, structural port, selftest). They should stay in this chat until `Total test failures: 0`. Skipping questions or stopping early is a weak install.

Answer in the developer's language. Do not commit unless they ask.

If `<repo>/.harness-setup/answers.json` exists and `"i0": true`, **skip section I**. Use those answers. Copy `.harness-setup/SETUP_ANSWERS.md` into the backup folder. Installer argv: `$PY <kit-or-.agents>/scripts/setup_wizard.py flags --repo <this-android-root>`.

Otherwise run `<kit>/agents/scripts/setup_wizard.py` (see [`install-prompt.md`](install-prompt.md)). Do **not** invent five-word `ask_question` titles. If you must ask in chat, the prompt text must be the wizard JSON `prompt` field verbatim.

**Interview format (only if the wizard has not written answers.json):** After backup + file discovery, run section **I**. The developer reads the **choice UI**, not your chat. A five-word title (`Backup?`, `Python?`, `Device?`) is a failed question.

For every question:

1. Put **why + what they gain + what goes wrong if they pick the other option** inside the `ask_question` `prompt` itself (translate the **Modal prompt** below). Chat may repeat it; the modal must stand alone.
2. Then the **choice list**. Options in the **same language** as the developer.
3. Wait for required answers. Do not guess team policy. Do not rewrite `harness-rules.md` until required I.* are answered.

Do **not** dump I.0–I.14 into one form. Policy questions are **one form each**: I.0, I.3, I.4, I.7, I.12, I.14. Disk facts may share one form **only** for I.5 + I.6 + I.6b, and each of those three prompts still has its full why/benefit text.

Use **choices** whenever the answer is a known set. Put the discovered/safe default first. Mark `(Recommended)` **only** on a real engineering default (no unattended install, skip device lock during setup). Never on “did the last test pass”. Physical vs emulator is **optional during install** (I.4).

**Free text only** when you cannot know the value (section **I-text**). Do not ask them to type a module name if you already found `:composeApp`. If they pick “Other”, **then** wait for one line of text.

## Detect environment (print in chat)

- OS: `darwin` / Windows / Linux. Do **not** assume Mac. Never copy another PC's paths.
- Tools: Claude Code, Codex, Antigravity/Gemini, Cursor, Copilot, Qwen Code, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, Goose — whatever exists. Do not require Antigravity. Write adapters **only** for the tools they pick in **I.14**.
- **`PY`**: try `python3 --version` then `python --version`. Windows `python3` is often a failing Store stub → use `python`. Confirm with the developer if both work (question I.2).
- `adb` and `./gradlew` / `gradlew.bat`. On macOS `chmod +x gradlew` if needed.

## 0) Backup FIRST (mandatory)

Do not write/delete `.agents` or user AI config until backup exists and paths are printed. If copy fails, **stop**.

Ask **I.0** before copying (see section I). Then:

Timestamp `YYYYMMDD-HHMMSS`. **A)** `<repo>/.harness-backup/<timestamp>/` for `.agents`, `.claude`, `.codex`, `.cursor`, `.github` (copilot/instructions only if present), `.windsurf`, `.roo`, `.amazonq`, `.continue`, `.junie`, `.kilocode`, repo `.gemini`, root `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`/`CODEX.md`/`QWEN.md`/`.cursorrules`/`.clinerules`/`.windsurfrules`/`.goosehints`. **B)** `$HOME/.harness-backups/<repo>-<timestamp>/` for `~/.gemini/config.json` + `rules/`, `~/.claude/settings*.json`, `~/.codex/config.toml` or `json` — no tokens/transcripts. Do **not** write `~/.gemini` during this install when another product on this PC already uses it (I.12). Append `.harness-backup/` to `.gitignore`. Manifest with yes/no per item. Rollback = `docs/rollback-prompt.md` (copied into the backup folder).

## 1) Place the engine

Copy kit `agents/` → `.agents/`. Empty `state/`. `.agents/.gitignore` = `state/` + `scripts/__pycache__/`. Keep `.agents/mcp_config.json` as `{"mcpServers": {}}`. Do **not** add MCP servers or portal integrations.

## 2) Discover from disk (do not invent)

Read Gradle, manifests, source. Print a **proposed facts** table in chat (module, assemble task, APK path, applicationId, launcher, DI, VM base, Room yes/no, theme, source roots, string files). Never assume `:app` or `app-debug.apk`. If `local.properties` missing: tell them Android Studio must write `sdk.dir` — do not invent a path. If no `gradlew`: **stop**.

Then run **section I** using those proposals as defaults they can correct.

## I) Interview — choices first, type only when we cannot know

Explain why + benefit **in the question prompt**, then **choices**. Required = wait. Optional: if they ignore, apply the **first** option and record it in `SETUP_ANSWERS.md`.

### I.0 Backup and install? (required)

- **Modal prompt:** Setup will replace `.agents` in this repo. A backup plus the rollback prompt can restore what is here today. Without a backup, the old harness is gone. Do you want to back up and start?
- **Choices:** `Yes, back up and start` / `No, stop`

### I.1 Product name (required)

- **Modal prompt:** Reviewer prompts and `AGENTS.md` will use this name. If we keep the example product name, reviews talk about the wrong app. Use the name I found, or type another?
- **Choices:** `Use “<discovered rootProject.name or folder>”` / `Other name (I will type it in chat)`
- **Free text** only if they pick the second.

### I.2 Python command (required)

- **Modal prompt:** Every harness script starts with this command. On Windows, `python3` is often a Store stub that does not run. The one I verified actually works. Pick it, or stop so you can install Python 3.10+.
- **Choices:** only interpreters you **already verified** (e.g. `python` / `python3`). If only one works, that option + `Stop — install Python 3.10+`.

### I.3 Git (required)

- **Modal prompt:** The default blocks the agent from `git add` / commit / push so nothing lands on GitHub unless you commit in the IDE. If you want the agent to commit when you ask in chat, pick the second option. Surprise commits are the failure mode of the second choice.
- **Choices:** `Agent never touches git (developer commits)` (Recommended) / `Agent may commit when I explicitly ask`

### I.4 Device (optional during install)

- **Modal prompt:** This chooses whether the harness may use an emulator serial. Pick “both allowed” unless you are sure you will never debug on an AVD. “Physical only” blocks emulator installs and logcat. You can change this later with the update prompt. Skipping is safe.
- **Do not block setup** waiting on this. If they skip or ignore, continue.
- **Choices:** `Skip — both allowed for now` (Recommended) / `Allow emulator` / `Physical device only`
- **If skipped, ignored, first choice, or Allow emulator:** treat as emulator allowed. Relax “physical only” in `harness-rules.md`, `pre_tool_safety.py` (do **not** deny `emulator-` serials or `emulator`/`avdmanager`), `run_device.py`, `logcat_doctor.py`, `capture_screen.py`, adapters, and do not add emulator to the Gemini `deny` list. Keep `adb monkey` denied either way.
- **If physical only:** keep the kit’s physical-only denies.

### I.5 Android application module (required)

- **Modal prompt:** Assemble and install must use the module that actually builds the APK. The wrong module means you install an old or missing APK. I found these application modules.
- **Choices:** one option per `com.android.application` / `androidApplication` module you found (e.g. `:composeApp`, `:app`). If several, list all. Add `Other module (I will type it)` only if discovery is incomplete.

### I.6 Launcher activity (required)

- **Modal prompt:** After install, `run_device.py` starts this activity (`package/.Activity`). The wrong component opens a blank task or a different screen. I found these MAIN/LAUNCHER activities.
- **Choices:** each MAIN/LAUNCHER you found (`com.pkg/.MainActivity`, keep the `/`). Add `Other activity (I will type it)` only if none or several ambiguous.

### I.6b Debug APK path (required)

- **Modal prompt:** The live runner checks that this debug APK exists after assemble. The kit example is `app-debug.apk`; many KMP apps are `composeApp-debug.apk`. A wrong path looks like a failed build.
- **Choices:** `Use discovered path: <path>` / `Glob **/outputs/apk/debug/*.apk` / `Other path (I will type it)`

### I.7 Architecture to enforce (required)

- **Modal prompt:** Reviewers only flag what they can cite. If we keep the kit’s MVI/Hilt/Room/ads rules, they will false-fail a Koin/KMP/`BaseViewModel` app. Using the stack I discovered makes reviews match how you write code.
- **Choices:** `Use discovered stack: <one-line stack>` (Recommended) / `Keep the kit’s MVI/Hilt/Room rules`

### I.8 Locales (required if you found resource folders)

- **Modal prompt:** String checks compare keys across locale folders. If you only have `values/`, we skip AR/EN parity so preflight does not fail on a missing `values-ar`. If you have two folders, we keep the pair so translations do not drift.
- **Choices:** `Use discovered folders: <e.g. values + values-ar>` / `Other locales (I will type them)`

### I.9 Scaffold (optional)

- **Modal prompt:** The new-screen generator still has example-product paths until we retarget it. Disable it so the agent cannot create junk packages. Retarget it if you want faster new screens in *this* tree. Disable is safer when the layout is not `app/src/main/java`.
- **Choices:** `Disable it now` (Recommended if layout ≠ `app/src/main/java`) / `Retarget it to this project now`

### I.10 Unattended install (optional)

- **Modal prompt:** `run_device.py` overwrites the app on the phone. Confirm-before-install avoids a surprise install on the wrong device. Skipping confirm is faster if you trust the allowlist.
- **Choices:** `Confirm before adb install` (Recommended) / `Allow run_device.py without confirm`

### I.11 `.agents` in git (optional)

- **Modal prompt:** Gitignore keeps the harness on this machine only (clones will not get `.agents`). Committing it later shares the engine with the team, still without `state/`. This setup will not commit unless you later say “commit”.
- **Choices:** `Add to .gitignore (local)` / `We will commit it later without state/`
  Do not commit in this setup unless they later say “commit”.

### I.12 Antigravity config (only if `~/.gemini` exists)

- **Modal prompt:** `~/.gemini/config.json` is for the whole PC, not this repo. Another app on this machine may already use it. Merging the script allowlist only leaves that global file alone except for safe grants. A global rule is only for when this is the only Antigravity project on the PC.
- **Choices:** `Merge script allowlist only` (Recommended) / `This is the only Antigravity project — write a global rule`

### I.13 Assemble now? (optional)

- **Modal prompt:** Selftest + preflight prove the harness scripts. A full `:assembleDebug` also proves your SDK/wrapper and shows the 10s heartbeat, but it costs compile time. Tests only is enough to finish setup.
- **Choices:** `Tests only (selftest + preflight)` (Recommended) / `Yes, run :assembleDebug at the end`

### I.14 Coding agents (required)

- **Modal prompt:** Each tool loads a different file (Cursor `.mdc`, `GEMINI.md`, `CLAUDE.md`, Copilot, …). Pick **every** product you actually open this repo in. If you use Cursor but only pick Gemini, Cursor will not get `.cursor/rules`. Extra tools only add files; you can add one later by re-running the installer. Do not pick “all” just to be safe if you want a clean root.
- **Choices (multi-select):** `Cursor` / `Claude Code` / `GitHub Copilot` / `Gemini / Antigravity` / `Codex` / `Qwen Code` / `Windsurf` / `Cline` / `Roo` / `Amazon Q` / `Continue` / `Junie` / `Kilo` / `Goose` / `All of them`
- Wait for this answer (`allow_multiple` if the product supports it). Do not default to all. Do not default to only the tool running this chat.

### I-text — type in chat (only these)

Use a short chat prompt, not fake choices, when you **cannot** know:

1. Custom product name (only if I.1 = other)
2. Custom module / activity / APK / locales (only if they picked “other”)

Record all answers in `.harness-backup/<timestamp>/SETUP_ANSWERS.md`.

## 3) Port structurally (use answers)

**Keep:** 5 reviewers; `*_PASS`; no `code-review-guard-agent`; no `LGTM`; `$PY .agents/scripts/run_gradle_task.py`; `$PY .agents/scripts/run_device.py`; do not skip reviews.

Patch **all** leftover forms (`docs/porting.md`): plain names, **regex** `com\.madarsoft`, **paths** `REPO / "app"`, quoted Path pieces `"madarsoft"` / `"fitness"`, `:app:assembleDebug`, launcher activity, APK existence check in `run_gradle_task.py` (glob `**/outputs/apk/debug/*.apk` if the filename is unknown). Also rename leftover `app-debug.apk` **filename** after `"app"` was already replaced.

Apply **I.7**: rewrite or stub skills so reviewers cannot cite the example product’s ads/streak/GPS/Room/MVI/Hilt/theme wrapper unless they opted in. Retarget or disable scaffold per **I.9** (keep `VIEWMODEL`/`SCREEN` constants for `_hook_selftest.py` if you disable `main()`). `logcat_doctor` / `perf_guard` / `fast_kt_lint` use **this** `applicationId` and the real source roots (KMP: `androidMain`, not `src/main` after renaming `"app"`). `run_device.py` uses **I.6**. Apply **I.4** (optional): physical-only keeps emulator denies; skip/either/emulator = allow emulator serials — rewrite entire `if emulator` blocks (do not leave an empty `if`). Flip selftest `emu` to `allow`. `harness-rules.md` uses **I.1–I.8** and git policy **I.3**. There is **no** ticket portal in this kit. **I.8:** one locale → skip AR/EN parity.

## 4) Leftover grep

Must not find the leftovers listed in `docs/porting.md` (After port). Theme-wrapper name only if they kept it. `RASHAQA_REVIEW_PACKAGE` may stay.

Do not write forbidden tokens even in “do not use …” sentences.

## 5) Wire tools

`hooks.json` lives in `.agents/` for Antigravity. Write adapters **only** for the tools from **I.14**. Run:

```
$PY .agents/scripts/install_tool_adapters.py --product <I.1> --py <I.2> --assemble <I.5 assembleDebug task> --device-policy <allow|physical-only from I.4> --git-policy <never|agent-may-commit from I.3> --tools <comma ids from I.14>
```

`--tools` examples: `cursor,gemini` or `claude,copilot` or `all`. Map I.14 labels to ids: `cursor` `claude` `copilot` `gemini` `codex` `qwen` `windsurf` `cline` `roo` `amazonq` `continue` `junie` `kilo` `goose`. `--tools all` if they picked every tool.

`--device-policy allow` if I.4 was skip / either / emulator. `--device-policy physical-only` only if they locked to a physical device. `--git-policy never` unless I.3 allows commits.

That script fills `.agents/tool-adapters/*.template`, always writes `AGENTS.md`, writes the selected tool files, generates `.claude/agents/*.md` only when `claude` is selected, and **deletes** previously managed adapters for tools that were not selected. Details: kit `docs/tool-support.md`.

Follow **I.12** for Gemini **global** config only. Never copy `remoteControlHostname` or tokens. Never set `sdk.dir` in harness files. Do not overwrite `.aider.conf.yml`, Continue/MCP user configs, `kilo.jsonc`, or `~/.gemini`.

## 6) Verify

`$PY .agents/scripts/_hook_selftest.py` → `Total test failures: 0`.  
`$PY .agents/scripts/preflight_check.py` → pass.  
Confirm adapter files exist for **I.14** only (always `AGENTS.md`; Cursor `.mdc` starts with `---`; `GEMINI.md` if Gemini was selected). Do not require CLAUDE.md / Copilot / Cline unless those tools were chosen.  
Assemble only if **I.13 = yes**.

## 7) Tell the developer

New session on this folder. Five `*_PASS` before real delivery. Rollback = `docs/rollback-prompt.md`.
