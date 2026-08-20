# Setup prompt

The installing agent **executes** this file (usually after the developer pasted [`install-prompt.md`](install-prompt.md) in a new chat on the Android app). Do not summarize it. Replacing the example app name alone is **not** a successful install.

---

You are installing a portable **Android AI harness** into THIS checkout. The kit is a clone of `android-harness-kit` (sibling, temp, or a path the developer gave). Copy from that clone’s `agents/` folder.

## Goal

Same **engine** (5-leaf review, live Gradle runner, safety hook). **Different product, machine, and team policy.** A find-replace of the example app name is **not** enough.

Answer in the developer's language. Do not commit unless they ask.

**Interview format (mandatory):** After backup + file discovery, run section **I**. For every question: (1) in chat, **why** you need it and **what they gain**, (2) then a **choice list** (`ask_question` if the product has it; otherwise numbered options in chat). Options in the **same language** as the developer.

Use **choices whenever the answer is a known set** (yes/no, discovered module A vs B, python vs python3). Put the discovered/default value first and mark it `(Recommended)` **only** when it is an engineering default (e.g. no unattended install) — never on “did the last test pass”. Physical vs emulator is **optional during install** (I.4).

**Free text only** when the agent cannot know the value from the repo or the machine (section **I-text**). Do not ask them to type a module name if you already found `:composeApp` — offer it as a choice. If they pick “Other”, **then** wait for one line of text.

Do not guess team policy. Wait for required choices before rewriting `harness-rules.md`.

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

Explain why + benefit in chat, then **choices**. Required = wait. Optional: if they ignore, apply the first option (the default) and record that in `SETUP_ANSWERS.md`.

You may **batch** independent choices in one `ask_question` (several questions) so they are not clicking many times — still keep why/benefit in chat above the form.

### I.0 Backup and install? (required)

- **Why:** Setup overwrites `.agents` and may merge AI tool settings.
- **Benefit:** A backup + rollback prompt restores the old system.
- **Choices:** `Yes, back up and start` / `No, stop`

### I.1 Product name (required)

- **Why:** Prompts must name *this* app, not the example product.
- **Benefit:** Reviewers follow this product.
- **Choices:** `Use “<discovered rootProject.name or folder>”` / `Other name (I will type it in chat)`
- **Free text** only if they pick the second.

### I.2 Python command (required)

- **Why:** Scripts run as `$PY .agents/scripts/...`.
- **Benefit:** Lint/assemble do not hit a fake Windows `python3` Store alias.
- **Choices:** only interpreters you **already verified** (e.g. `python` / `python3`). If only one works, one option + `Stop — install Python 3.10+`.

### I.3 Git (required)

- **Why:** Default kit blocks agent `git add`/`commit`/`push`.
- **Benefit:** No surprise commits, or the agent commits if they want that.
- **Choices:** `Agent never touches git (developer commits)` (Recommended) / `Agent may commit`

### I.4 Device (optional during install)

- **Why:** Serials, `run_device.py`, and whether the hook denies `emulator` / `emulator-*`.
- **Benefit:** They can lock to a physical phone, allow an AVD, or skip and decide later.
- **Do not block setup** waiting on this. If they skip or pick “either”, continue install.
- **Choices:** `Physical device only` / `Allow emulator` / `Skip — both allowed for now`
- **If skipped or third choice:** treat as emulator allowed. Relax “physical only” in `harness-rules.md`, `pre_tool_safety.py` (do **not** deny `emulator-` serials or `emulator`/`avdmanager` unless they picked physical-only), `run_device.py`, `logcat_doctor.py`, `capture_screen.py`, adapters, and do not add emulator to the Gemini `deny` list. Keep `adb monkey` denied either way.
- **If physical only:** keep the kit’s physical-only denies.

### I.5 Android application module (required)

- **Why:** Assemble/install must use the real module.
- **Benefit:** The APK they install is the one that just built.
- **Choices:** one option per `com.android.application` / `androidApplication` module you found (e.g. `:composeApp`, `:app`). If several, list all. Add `Other module (I will type it)` only if discovery is incomplete.

### I.6 Launcher activity (required)

- **Why:** `run_device.py` start component.
- **Benefit:** Install launches the real MAIN/LAUNCHER screen.
- **Choices:** each MAIN/LAUNCHER you found (`com.pkg/.MainActivity`). Add `Other activity (I will type it)` only if none or several ambiguous.

### I.6b Debug APK path (required)

- **Why:** Assemble summary + install path.
- **Benefit:** Not the example `app-debug.apk`.
- **Choices:** `Use discovered path: <path>` / `Glob **/outputs/apk/debug/*.apk` / `Other path (I will type it)`

### I.7 Architecture to enforce (required)

- **Why:** Reviewers cite skills; example MVI/Hilt/Room/ads will false-fail Koin/KMP/`BaseViewModel`.
- **Benefit:** Reviews match how they write code.
- **Choices:** `Use discovered stack: <one-line stack>` (Recommended) / `Keep the kit’s MVI/Hilt/Room rules`

### I.8 Locales (required if you found resource folders)

- **Why:** `check_strings.py` pairs locales.
- **Benefit:** No missing keys across locales.
- **Choices:** `Use discovered folders: <e.g. values + values-ar>` / `Other locales (I will type them)`

### I.9 Scaffold (optional)

- **Why:** Scaffold still has example-product paths until retargeted.
- **Benefit:** disable = no junk packages; retarget = faster new screens later.
- **Choices:** `Disable it now` (Recommended if layout ≠ `app/src/main/java`) / `Retarget it to this project now`

### I.10 Unattended install (optional)

- **Why:** Overwrites the app on a device.
- **Benefit:** confirm = safer; allowlist = faster loop.
- **Choices:** `Confirm before adb install` (Recommended) / `Allow run_device.py without confirm`

### I.11 `.agents` in git (optional)

- **Why:** Some teams keep the harness local; others commit it.
- **Benefit:** git = shared with clones; gitignore = machine-only.
- **Choices:** `Add to .gitignore (local)` / `We will commit it later without state/`
  Do not commit in this setup unless they later say “commit”.

### I.12 Antigravity config (only if `~/.gemini` exists)

- **Why:** `config.json` is machine-global.
- **Benefit:** allowlist-only is safe when another app on the same PC already uses Gemini.
- **Choices:** `Merge script allowlist only` (Recommended) / `This is the only Antigravity project — write a global rule`

### I.13 Assemble now? (optional)

- **Why:** Proves their wrapper/SDK with the live runner.
- **Benefit:** they see heartbeats; cost = compile time.
- **Choices:** `Tests only (selftest + preflight)` (Recommended) / `Yes, run :assembleDebug at the end`

### I.14 Coding agents (required)

- **Why:** Each product loads a different entry file. Writing every adapter clutters the checkout with tools they do not use.
- **Benefit:** Only those files appear at the repo root. Re-run the installer with a new `--tools` list to add one later.
- **Choices (multi-select):** `Cursor` / `Claude Code` / `GitHub Copilot` / `Gemini / Antigravity` / `Codex` / `Qwen Code` / `Windsurf` / `Cline` / `Roo` / `Amazon Q` / `Continue` / `Junie` / `Kilo` / `Goose` / `All of them`
- Wait for this answer (`allow_multiple` if the product supports it). Do not default to all.

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
