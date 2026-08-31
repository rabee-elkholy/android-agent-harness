# System Audit Report — Conflicts, Edge Cases & Arabic Inventory

> Scope: `android-harness-kit` (this repository). Report only — no fixes were applied as part of this audit.
> Date: 2026-08-31 · Generated from a full-source scan excluding `agents/state/` (ephemeral) and `__pycache__/`.

---

## 1. Arabic Language Inventory

### 1.1 Files containing actual Arabic text (Unicode)

| File | Lines | Content | Classification |
|---|---|---|---|
| `agents/rules/harness-rules.md` | 96 | Arabic translation of the proactive Zoho Story chat question | Kit prose — remove |
| `agents/rules/harness-rules.md` | 241 | Example `"ابدأ المرحلة اللي بعدها"` in the phase barrier | Kit prose — remove |
| `agents/rules/harness-rules.md` | 296–299, 310 | Mandatory Zoho section headers in Arabic (`سبب المشكلة`/`الحل`/`نطاق التأثير`/`خطوات الفحص`) | **Zoho — keep** |
| `agents/scripts/wizard/i18n.py` | 58–75 (`TOOL_LABELS["ar"]`, incl. `كلهم`) | Tool names in Arabic | Kit prose — remove |
| `agents/scripts/wizard/i18n.py` | 280–472 (full `T["ar"]` table) | ~30 wizard questions in Egyptian colloquial Arabic | Kit prose — remove except `i18*` tracker-language keys |
| `agents/scripts/wizard/questions.py` | 359, 362 | `(موصى به)` Recommended-prefix logic | Kit prose — remove |
| `agents/scripts/wizard/questions.py` | 461 | Accepts `"كلهم"` as shortcut for "all" | Kit prose — remove |
| `agents/scripts/pm_policy.py` | 79–82, 88, 93, 98 | Arabic handoff headers for the Zoho validator | **Zoho — keep** |
| `agents/scripts/pre_invocation_reminder.py` | 23 | Arabic labels in the update modal (`عرض التغييرات`/`ذكرني غداً`/`تحديث الآن`) | Kit prose — remove |
| `agents/scripts/pre_tool_safety.py` | 860 | Arabic keyword `"مراجع"` in the `schedule` deny list | Kit prose — remove |
| `agents/scripts/_hook_selftest.py` | 2044–2045 | `VALID_AR_BUG` Arabic fixture for the Zoho validator | **Zoho (test) — keep** |
| `agents/scripts/_hook_selftest.py` | 2232–2247 | Arabic UI-hierarchy XML (`الفعاليات`/`ماراثون الجري`) for the E2E parser test | App-convention (test) — keep |
| `agents/workflows/zoho-sprints.md` | 64–67, 95–106, 135–146, 174–184 | Header mapping table + Arabic Bug/Feature/Task templates | **Zoho — keep** |
| `docs/setup-prompt.md` | 224, 226 | Arabic question/options of the architecture-references approval modal | Kit prose — remove |

### 1.2 "Arabic" mentions in English (policy text, not Arabic Unicode)

- **Chat language policy (generalize):** `harness-rules.md:30,343` · `AGENTS.md:50` · `agents/tool-adapters/AGENTS.md.template:49` · `agents/scripts/pre_invocation_reminder.py:48` · `docs/diagnostic-prompt.md:13`
- **Zoho policy (keep):** `agents/scripts/_product.py:19-20` · `harness-rules.md:31,301-304` · `AGENTS.md:59` · `AGENTS.md.template:57` · `pre_invocation_reminder.py:65` · `docs/setup-wizard.md:21` · `docs/workflows.md:145` · `docs/architecture.md:257` · `docs/workflows/pm-integrations.md:34,74-75` · `agents/pm/mcp_registration.jira.md:63-65` & `linear.md:63-65` · `docs/setup-prompt.md:29,68,121-124,174`
- **Client-app locale conventions (keep):** `agents/scripts/fast_kt_lint.py:24,46,262` · `check_strings.py:22` · `new_feature_scaffold.py:205,227,238,249` · `harness-rules.md:140,163,177` · `docs/workflows.md:95,113` · `docs/architecture.md:219` · `docs/quickstart.md:155` · `docs/tool-support.md:99` · `docs/benchmark/tasks.md:9` · `agents/command-packs/check-strings.md.template:2` · `run_e2e_smoke.py:162` · `_hook_selftest.py:882,927`
- **`--lang en|ar` flag itself:** `setup_wizard.py:5,9,128` · `harness_cli.py:13,290,621` · `doctor/engine.py:383` · `docs/quickstart.md:130` · `docs/tool-support.md:148,155` · `docs/install-or-update-prompt.md:34-37`
- **Historical record (never touched):** `CHANGELOG.md:304,391,460`

**Quality note:** the wizard's Arabic tables are written in Egyptian colloquial register (`هركّب ملفات مساعد التطوير`) while `harness-rules.md:96` and `docs/setup-prompt.md:224` use Modern Standard Arabic — an internal register inconsistency.

---

## 2. Command-Line Conflicts

### 2.1 Two CLIs with identical command names, different semantics
- The real, shipped CLI is `android-harness` → `harness_cli.py` (registered at `pyproject.toml:31-35`).
- A legacy `dg`/`droidguard` CLI survives **as bytecode only** under `src/droidguard/**/__pycache__` (`.py` sources deleted; the whole `src/` tree is untracked by git). Its commands — `init --force`, `doctor --check-tools`, `preflight --silent`, `verify --hash`, `explain --limit`, `deliver/status/sync/rollback` — share names with the new CLI but have different flags and meanings. A client with old muscle memory silently gets different behavior.

### 2.2 Inconsistent exit codes
- `harness_cli.py:131-135` defines a 0–4 scheme (`EXIT_INCOMPLETE_OR_STALE=4`) that is **never referenced anywhere**.
- `verify` returns **2** for STALE (`:599-604`) and 1 elsewhere; config errors `SystemExit` → 1; `KeyboardInterrupt` → 130.
- `_hook_selftest.py:2610` exits with the **failure count** as the code (can be 7); `gradle_error_parser.py:84` has the same problem.
- `check_kit_update.py:216` always exits 0 even when an update is available.
- `run_device.py:105,116` passes raw adb exit codes through.

### 2.3 Most surprising behavior: `preflight` checks the kit, not the client app
`android-harness preflight --repo <app>` (`harness_cli.py:357-365`) runs the **kit's** `preflight_check.py`, which derives `REPO` from its own location (`_repo_files.py:7-8` → `SCRIPTS_DIR.parent.parent` = kit root). Result: it lints the kit tree and performs git mutations on the kit instead of the client app, while `python <app>/.agents/scripts/preflight_check.py` checks the app. Same command name, two different targets.

### 2.4 Silent no-ops
- `update --repo X`: the flag is printed but never used (`harness_cli.py:324-326`) — does not update the app's `.agents`.
- `update` on a pip-installed kit (no `.git`): "skipping pin", exit 0 (`:193-195`).
- `update` offline: "Nothing floated to main", exit 0 (`:238-241`).
- `explain` with no audit log: `[i] No audit log yet`, exit 0 (`:409-411`).
- `doctor`/`preflight` without `--repo` run from `Path.cwd()` (`:342,359`) — late, confusing failure instead of an early clear message.

### 2.5 Destructive operations without confirmation
- `update` force-checks out the kit to a release tag (`harness_cli.py:196-220`) with no dirty-worktree guard — dangerous when a maintainer runs it inside the kit repo.
- `_provision_pinned` removes `~/.android-harness/kit` before re-cloning (`:93-95`).
- `run_device.py uninstall` uninstalls the app with no confirmation (`:82-89`).
- `ensure_local_git_privacy` (`_repo_files.py:134-248`) rewrites `.gitignore` and `.git/info/exclude` as a side effect of running "checks".

### 2.6 Error-like output and inconsistent markers
- Six distinct success markers (`[+] [OK] [SUCCESS] [PASS] [i] [*]`) and four failure markers (`[ERROR] [FAIL] [!] [STALE]`) across scripts with no shared convention; `[!]` is used for warnings in one place and hard errors in another.
- `run_gradle_task.py:118-121`: `[+] BUILD SUCCESSFUL in done` when duration parsing fails.
- `cmd_init` addresses an AI agent, not a human: "[NEXT] ... paste <url> in a NEW strong-model chat" (`:304-307`).

### 2.7 CLI vs scripts duality
- The delivery gate in `AGENTS.md` is 100% script-first (`python .agents/scripts/...`) while README/`docs/quickstart.md` market the CLI as the primary interface — and the two do not fully agree (see §2.3).
- Inside the kit repo itself, every `AGENTS.md` command fails as written because the folder is `agents/` (no dot) and `.agents` does not exist here.
- The selftest hard-codes the canonical subcommand set (`_hook_selftest.py:2499-2500`) — adding a command breaks the suite.

---

## 3. Rules / Docs / Enforcement Contradictions

| # | Contradiction | Details |
|---|---|---|
| 1 | **5 vs 6 leaves** | Engine enforces 5 (`pre_tool_safety.py:137-145,412`); `README.md:116-126`, `docs/workflows.md:18,41`, `docs/architecture.md:25-32`, `docs/setup-prompt.md:290` ("Six `*_PASS` required"), and the SVG assets claim 6 mandatory. `TEST_PASS` is only a Stage 0.5 pre-gate, not a delivery leaf |
| 2 | **Sequential vs parallel** | `AGENTS.md:36`, `AGENTS.md.template:22,35`, `docs/tool-support.md:171`: "Sequential is fine"; `harness-rules.md:210` forbids five separate invokes and `pre_tool_safety.py:330-338` machine-denies them |
| 3 | **Gate sequence differs** | `AGENTS.md:32` mandates `run_e2e_smoke.py` always; `harness-rules.md:252-265` mandates it only in Mode A; AGENTS.md omits Stage 0/0.5 and the `HARNESS_PACKAGE_SHA256_12` evidence protocol |
| 4 | **Wizard answers not honored** | I.3 "agent may commit" (`wizard/questions.py:74-78`) writes permissive AGENTS.md text, but `pre_tool_safety.py:798-809` denies all git in client repos — the option is inert. I.4 "emulator allowed" is the default yet the shipped hook denies all `emulator`/`avdmanager` (`pre_tool_safety.py:812-834`) unless the installer rewrites it. I.10 "Ask me first" is stored (`questions.py:630,668`) and consumed by nothing |
| 5 | **Device verification modes: 3 vs 2** | `harness-rules.md:229,252,257,264` define `autonomous_e2e`/`interactive_device`/`disabled`; the wizard and `_product.py:31-32` know only two; no runner reads the value at all |
| 6 | **Zoho hardcoded in AGENTS.md** | `AGENTS.md:59` and `template:57` always say "`update zoho`. English task titles, Arabic descriptions/comments." regardless of I.18/I.20 — clients who chose GitHub/Jira/Linear get the wrong phrase and policy |
| 7 | **"Prefer physical device" not implemented** | `AGENTS.md:13` promises it; `_repo_files.py:72-89` returns the first `adb devices` line with no physical-first logic |
| 8 | **Update modal has a broken reference** | `pre_invocation_reminder.py:26` and `check_kit_update.py:175,212` instruct "execute docs/install-or-update-prompt.md" — `docs/` is never installed into client repos |
| 9 | **Doc drift** | Gate order differs (`agents/workflows/debug.md:19` vs `harness-rules.md:197-199`); "Realm" offered in `docs/quickstart.md:153` is not a wizard option; Zoho MCP server exposes `Done`/`Solved` (`agents/mcp/zoho_sprints/server.py:81`) despite the ban |
| 10 | **Duplicated gates** | `fast_kt_lint` runs twice per delivery (standalone + inside `preflight_check.py:40-47`); a third lint surface exists in `pre_commit_gate.py:65-82`; the dual-locale preview rule lives in 3 places with different scopes (`fast_kt_lint.py:261-282` vs `convention-reviewer-agent.json` scope 4 vs `harness-rules.md:140`) |

---

## 4. Edge Cases

| # | Case | Impact |
|---|---|---|
| 1 | **Spaces in the project path** | `pre_tool_safety.py:135`: `HARNESS_REVIEW_PACKAGE=(\S+)` truncates at the first whitespace → review dispatch fails ("package file does not exist") even though `review_package.py` printed a valid path |
| 2 | **KMP project without `:app`** | `AGENTS.md.template:19` hardcodes `:app:testDebugUnitTest`; `pre_invocation_reminder.py:50,63` hardcode `:app:` — every KMP client gets wrong commands in files that are always written |
| 3 | **No git repo / zero commits** | `changed_paths()` silently returns empty (`_repo_files.py:25-51`) → all gates pass trivially ("[OK] No Kotlin files to lint", header-only review package, no Room baseline); doctor only warns (`doctor/engine.py:88`) |
| 4 | **Python 3.9** | `pre_tool_safety.py:162` uses `Path \| None` without a future import → the hook itself crashes at import |
| 5 | **Windows/macOS python** | `agents/hooks.json:10,22,32` hardcode `python` (macOS often only has `python3`) and are never rewritten from the I.2 answer; `run_gradle_task.py:93` invokes `bash gradlew` on non-Windows |
| 6 | **Client files deleted** | `_repo_files.py:224-236` deletes `script_step*.py`/`fix_product.py`/`update_worker.py` from the client repo root on every preflight/doctor run; also runs `git update-index --assume-unchanged` (`:239-246`) and `git checkout -- .gitignore` (`:220`) |
| 7 | **Review barrier expiry** | `pre_tool_safety.py:599-609`: a pending round is cleared after 6 hours (`EXPIRED`) even if reviews never completed |
| 8 | **Review budget cap** | `MAX_REVIEWS=20` per conversation (`_hook_state.py:13`) — a long session is denied further reviews with no clear explanation |
| 9 | **Non-1080p screens** | `run_e2e_smoke.py:389-395` hardcodes swipe coordinates (y=1400/600, x=540) — off-screen on small/landscape devices, yet the scroll step still reports PASS (`:521-522`) |
| 10 | **Deny-list false positives** | Any `schedule` prompt containing "review/مراجع" is denied (`pre_tool_safety.py:856-868`) — "مراجع" is a substring of "مراجعة", so innocent Arabic reminders are rejected; any command containing "gradle/assemble/testdebug/run_device.py" hits the review barrier, including `cat gradle.properties` (`:742-745`); the standalone token "monkey" is denied (`policy_vocab.py:64`) |
| 11 | **Parent-product leftover** | `_hook_selftest.py:183` hardcodes `--product Rashaqa` in a shipped test — violates the kit's own porting rule (`docs/porting.md:41-43`) |
| 12 | **Adapter pruning** | Re-running `install_tool_adapters.py` with a smaller `--tools` list deletes previously managed adapters (`:405-442`) |
| 13 | **`--flavor` grammar split** | `run_gradle_task.py:177-183` hand-parses a positional `--flavor`; `run_device.py:61-64` uses real argparse — same concept, two grammars |
| 14 | **Contradictory reminder** | `pre_invocation_reminder.py` always injects "Physical device only. Never commit." (`:63`) even when the client chose emulator-allowed and agent-may-commit |

---

## 5. Priority Matrix & Proposed Fix Batches

| Priority | Item | Client impact |
|---|---|---|
| Critical | `preflight` checks the kit tree (§2.3) | A core command checks the wrong thing |
| Critical | Spaces in paths break review dispatch (§4.1) | Common Windows path layout breaks |
| Critical | Client files deleted (§4.6) | Data loss |
| Critical | 5-vs-6 leaves (§3.1) + sequential/parallel (§3.2) | Confusion and unexplained denials |
| High | Hardcoded `:app:` and Zoho in AGENTS.md (§4.2, §3.6) | Wrong commands for every KMP client |
| High | Inert wizard answers I.3/I.4/I.10 (§3.4) | Configuration that looks active but is not |
| High | Update modal broken `docs/` reference + hardcoded Arabic labels (§3.8) | Unrunnable instruction |
| Medium | Exit codes & output markers (§2.2, §2.6) | Automation on top of the scripts breaks |
| Medium | Legacy bytecode CLI (§2.1), CLI/scripts duality (§2.7) | Documentation confusion |
| Medium | Edge cases 4.3–4.14 (no-git, TTL, review cap, E2E coordinates, false positives) | Silent degradation |
| Low | Doc drift (§3.9) | Cleanup |

---

## 6. Resolution Status (v0.15.0)

| Item | Status |
|---|---|
| §2.3 preflight checks the kit tree | **FIXED** — `cmd_preflight` prefers the checkout's own `.agents/scripts/preflight_check.py`; otherwise runs the kit script with `HARNESS_REPO` override |
| §4.1 spaces in paths | **FIXED** — `PACKAGE_RE` captures the full line (`[^\r\n]+`) with quote stripping |
| §4.6 client files deleted | **FIXED** — stray cleanup is setup-time only (`clean_strays=True` from the wizard) and content-gated |
| §3.1 5 vs 6 leaves | **FIXED** — README, workflows, architecture, setup-prompt, SVGs aligned to 5; `TEST_PASS` documented as Stage 0.5 pre-gate |
| §3.2 sequential vs parallel | **FIXED** — AGENTS.md + template + tool-support reworded to the single-dispatch rule |
| §4.2 hardcoded `:app:` / Zoho in AGENTS.md | **FIXED** — `{{UNIT_TEST}}` (auto-derived), `{{PM_TRIGGER}}`, `{{PM_LANG_NOTE}}`; reminder renders tasks from `_product.py` |
| §3.4 inert wizard answers | **FIXED** — `GIT_POLICY`/`ALLOW_EMULATOR`/`INSTALL_CONFIRM` added to `_product.py`, honored by the hook and reminder |
| §3.8 update modal broken `docs/` reference | **FIXED** — raw prompt URL per version in reminder + `check_kit_update.py` |
| §2.2 exit codes | **FIXED** — selftest & gradle_error_parser exit 0/1; `verify` contract documented (0/1/2) |
| §2.1 legacy bytecode CLI | **FIXED** — `src/` tree and stale `__pycache__` removed |
| §2.7 CLI/scripts duality | **FIXED** — kit `AGENTS.md` uses `agents/scripts` paths; quickstart documents equivalence |
| §4.3 no-git silent pass | **FIXED** — `review_package.py` fails loudly when the checkout has no git HEAD |
| §4.7 barrier TTL silent clear | **FIXED** — `latest_expired_note()` surfaces EXPIRED rounds in the reminder |
| §4.8 review cap confusion | **FIXED** — cap message explains the per-conversation limit and remediation |
| §4.9 E2E fixed coordinates | **FIXED** — screen-relative swipes from `wm size`; WARN (never PASS) when size is unknown |
| §4.10 deny false positives | **FIXED** — schedule keywords narrowed; run_command triggers are precise; monkey requires adb context |
| §4.11 Rashaqa leftover | **FIXED** — neutral `SampleApp` in selftest |
| §4.12 adapter pruning | **FIXED** — explicit prune summary + `--keep-extra-adapters` hint |
| §4.13 `--flavor` grammar | **FIXED** — `--flavor=X` accepted alongside positional |
| §4.14 contradictory reminder | **FIXED** — device/git/install lines render from `_product.py` |
| §4.5 hooks.json hardcoded python | **FIXED** — installer rewrites `.agents/hooks.json` with the configured PY |
| §3.5 device modes 3 vs 2 | **FIXED** — wizard I.22 now offers `autonomous_e2e` / `manual_only` / `disabled` |
| §3.9 doc drift | **FIXED** — debug.md gate order, quickstart DB options, MCP status enum, setup-wizard I.22 row |
| §4.4 Python 3.9 crash | **DOCUMENTED** — `pyproject.toml` requires >=3.10; the wizard blocks older Pythons |
| §2.4/2.5 update no-ops & destructive pinning | **DOCUMENTED** — behavior printed explicitly; kit-dev git bypass is intentional |
| §2.6 output markers | **DOCUMENTED** — per-surface conventions kept; scripts standardize on `[OK]`/`[FAIL]`/`[!]` |
