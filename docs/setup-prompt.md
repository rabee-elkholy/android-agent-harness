# Setup prompt

The installing agent **executes** this file (usually after the developer pasted [`install-prompt.md`](install-prompt.md) or [`update-prompt.md`](update-prompt.md) in a new chat on the Android app). Do not summarize it. Replacing the example app name alone is **not** a successful install.

---

You are installing a portable **Android AI harness** into THIS checkout. The kit is a clone of `android-harness-kit` (sibling, temp, or a path the developer gave). Copy from that clone’s `agents/` folder.

## Goal

Same **engine** (5-leaf review, live Gradle runner, safety hook). **Different product, machine, and team policy.** A find-replace of the example app name is **not** enough.

Before the three wizard questions, tell the developer in their language: setup takes a few minutes (backup, port, selftest). They should stay in this chat until `Total test failures: 0`. Stopping early is a weak install.

Answer in the developer's language. Do not commit unless they ask.

If `<repo>/.harness-setup/answers.json` exists and `"i0": true`, **skip section I**. Use those answers. Copy `.harness-setup/SETUP_ANSWERS.md` into the backup folder. Installer argv: `$PY <kit-or-.agents>/scripts/setup_wizard.py flags --repo <this-android-root>`.

Otherwise run `<kit>/agents/scripts/setup_wizard.py` (see [`install-prompt.md`](install-prompt.md)). Print the wizard JSON `auto_blurb` in chat. Ask **only** the objects in `questions` (usually three: backup, git, which tools). Use each JSON `prompt` **verbatim**. Do **not** invent extra I.1–I.13 questions. Do **not** invent five-word titles.

**Interview format:** The developer reads the **choice UI**. One form per JSON question. Options in the **same language** as the developer. Wait for required answers. Do not guess which tools they use (I.14). Do not rewrite `harness-rules.md` until I.0 / I.3 / I.14 are answered.

Product name, Python, module, launcher, APK, architecture, and locales come from disk (`auto` in the wizard JSON). Defaults you must **not** ask: emulator allowed (I.4), scaffold disabled (I.9), confirm before adb install (I.10), `.agents` gitignored (I.11), Gemini = merge script grants only if `~/.gemini` exists else skip (I.12 — never write a global Gemini rule during setup), tests only at the end (I.13). The wizard adds I.2 / I.5 / I.6 **only** when Python, module, or launcher is missing or ambiguous.

**Free text only** if they pick “Other” on I.5 or I.6.

## Detect environment (print in chat)

- OS: `darwin` / Windows / Linux. Do **not** assume Mac. Never copy another PC's paths.
- Tools: Claude Code, Codex, Antigravity/Gemini, Cursor, Copilot, Qwen Code, Windsurf, Cline, Roo, Amazon Q, Continue, Junie, Kilo, Goose — whatever exists. Do not require Antigravity. Write adapters **only** for the tools they pick in **I.14**.
- **`PY`**: try `python3 --version` then `python --version`. Windows `python3` is often a failing Store stub → use `python`. Ask I.2 only if the wizard JSON includes it (both work, or none work).
- `adb` and `./gradlew` / `gradlew.bat`. On macOS `chmod +x gradlew` if needed.

## 0) Backup FIRST (mandatory)

Do not write/delete `.agents` or user AI config until either a backup exists **or** they chose start-without-backup. If they asked for a backup and copy fails, **stop**.

Ask **I.0** before copying (see section I), unless `.harness-setup/answers.json` already recorded it. If `"backup": false`, **skip file copies** and tell them rollback will not work. Then:

If `"backup"` is true or unset (default): Timestamp `YYYYMMDD-HHMMSS`. **A)** `<repo>/.harness-backup/<timestamp>/` for `.agents`, `.claude`, `.codex`, `.cursor`, `.github` (copilot/instructions only if present), `.windsurf`, `.roo`, `.amazonq`, `.continue`, `.junie`, `.kilocode`, repo `.gemini`, root `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`/`CODEX.md`/`QWEN.md`/`.cursorrules`/`.clinerules`/`.windsurfrules`/`.goosehints`. **B)** `$HOME/.harness-backups/<repo>-<timestamp>/` for `~/.gemini/config.json` + `rules/`, `~/.claude/settings*.json`, `~/.codex/config.toml` or `json` — no tokens/transcripts. Do **not** write `~/.gemini` during this install when another product on this PC already uses it (I.12). Append `.harness-backup/` to `.gitignore`. Manifest with yes/no per item. Rollback = `docs/rollback-prompt.md` (copied into the backup folder).

## 1) Place the engine

Copy kit `agents/` → `.agents/`. Empty `state/`. `.agents/.gitignore` = `state/` + `scripts/__pycache__/`. Keep `.agents/mcp_config.json` as `{"mcpServers": {}}`. Do **not** add MCP servers or portal integrations.

## 2) Discover from disk (do not invent)

Read Gradle, manifests, source. Print a **proposed facts** table in chat (module, assemble task, APK path, applicationId, launcher, DI, VM base, Room yes/no, theme, source roots, string files). Never assume `:app` or `app-debug.apk`. If `local.properties` missing: tell them Android Studio must write `sdk.dir` — do not invent a path. If no `gradlew`: **stop**.

Print `auto_blurb` from the wizard JSON. Then ask **only** the `questions` array (section I). Do not re-ask facts already in `auto`.

## I) Interview — only what the wizard JSON lists

Ask **only** `questions` from `setup_wizard.py questions`. Typically three forms:

### I.0 Backup? (required)

- **Modal prompt:** Setup will replace the AI helper files in this project. A backup lets you restore them if something goes wrong. Without a backup, the old files cannot be restored.
- **Choices:** `Back up and start` (Recommended) / `Start without a backup` / `Stop setup`

### I.3 Git (required)

- **Modal prompt:** Who should create git commits? If you are not sure, keep commits in your own hands (you commit from the IDE).
- **Choices:** `I commit myself` (Recommended) / `The agent may commit when I ask in chat`

### I.14 Coding tools (required)

- **Modal prompt:** Which programs do you open this project in? Select every one you use. If you use Cursor, you must select Cursor so its rules get written.
- **Choices (multi-select):** `Cursor` / `Claude Code` / `GitHub Copilot` / `Gemini / Antigravity` / `Codex` / `Qwen Code` / `Windsurf` / `Cline` / `Roo` / `Amazon Q` / `Continue` / `Junie` / `Kilo` / `Goose` / `All of them`
- Wait. Do not default to all. Do not default to only the tool running this chat.

### I.2 / I.5 / I.6 — only if they appear in the JSON

Ask them with the JSON `prompt` verbatim (ambiguous Python, several app modules, or several launchers).

### Do not ask (already in `auto` / answers.json)

- **I.1 / I.6b / I.7 / I.8:** product, APK path, stack, locales from disk. Use discovered stack (do **not** keep kit leftover architecture rules unless they later change answers).
- **I.4:** emulator **allowed**. Relax “physical only” in `harness-rules.md`, `pre_tool_safety.py` (do **not** deny `emulator-` serials or `emulator`/`avdmanager`), `run_device.py`, `logcat_doctor.py`, `capture_screen.py`, adapters, and do not add emulator to the Gemini `deny` list. Keep `adb monkey` denied. Physical-only only if answers.json later says so.
- **I.9:** always disable `new_feature_scaffold.py` `main()`. Keep `VIEWMODEL` / `SCREEN` constants for `_hook_selftest.py`.
- **I.10:** confirm before adb install.
- **I.11:** add `.agents` to `.gitignore`. Do not commit unless they later say “commit”.
- **I.12:** if `~/.gemini` exists, merge script grants only. Never write a global Gemini rule during this setup.
- **I.13:** tests only (selftest + preflight). Do not run `:assembleDebug` at the end unless answers say assemble.

Record all answers in `.harness-backup/<timestamp>/SETUP_ANSWERS.md`.

## 3) Port structurally (use answers)

**Keep:** 5 reviewers; `*_PASS`; no `code-review-guard-agent`; no `LGTM`; `$PY .agents/scripts/run_gradle_task.py`; `$PY .agents/scripts/run_device.py`; do not skip reviews.

Patch **all** leftover forms (`docs/porting.md`): plain names, **regex** `com\.madarsoft`, **paths** `REPO / "app"`, quoted Path pieces `"madarsoft"` / `"fitness"`, `:app:assembleDebug`, launcher activity, APK existence check in `run_gradle_task.py` (glob `**/outputs/apk/debug/*.apk` if the filename is unknown). Also rename leftover `app-debug.apk` **filename** after `"app"` was already replaced.

Apply **I.7**: rewrite or stub skills so reviewers cannot cite the example product’s ads/streak/GPS/Room/MVI/Hilt/theme wrapper unless they opted in. **Always disable** scaffold `main()` (keep `VIEWMODEL`/`SCREEN` constants for `_hook_selftest.py`). `logcat_doctor` / `perf_guard` / `fast_kt_lint` use **this** `applicationId` and the real source roots (KMP: `androidMain`, not `src/main` after renaming `"app"`). `run_device.py` uses **I.6**. Apply **I.4** (optional): physical-only keeps emulator denies; skip/either/emulator = allow emulator serials — rewrite entire `if emulator` blocks (do not leave an empty `if`). Flip selftest `emu` to `allow`. `harness-rules.md` uses **I.1–I.8** and git policy **I.3**. There is **no** ticket portal in this kit. **I.8:** one locale → skip AR/EN parity.

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

Follow **I.12** from answers: merge script grants only when `gemini_config` is `merge-allowlist`. Do **not** write a global Gemini rule. Never copy `remoteControlHostname` or tokens. Never set `sdk.dir` in harness files. Do not overwrite `.aider.conf.yml`, Continue/MCP user configs, `kilo.jsonc`, or `~/.gemini`.

## 6) Verify

`$PY .agents/scripts/_hook_selftest.py` → `Total test failures: 0`.  
`$PY .agents/scripts/preflight_check.py` → pass.  
Confirm adapter files exist for **I.14** only (always `AGENTS.md`; Cursor `.mdc` starts with `---`; `GEMINI.md` if Gemini was selected). Do not require CLAUDE.md / Copilot / Cline unless those tools were chosen.  
Assemble only if **I.13 = yes**.

## 7) Tell the developer

New session on this folder. Five `*_PASS` before real delivery. Rollback = `docs/rollback-prompt.md`.
