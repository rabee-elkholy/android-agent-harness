# Porting tokens

Naive replace of the example app name is not enough. After copy, port **structurally**. Replacing `com.madarsoft.fitness` does **not** update regex (`com\.madarsoft`) or Path pieces (`"madarsoft"`).

The engine ships with example-product leftovers from a production Android app. Setup must map them to **this** checkout.

## Identity map

| Source leftover | Replace with |
|---|---|
| Example product name (and its Arabic leftover) | This product name |
| Example repo folder name | This repo folder name |
| `com.madarsoft.fitness` | `applicationId` |
| `com.madarsoft.core` | Real shared package, or delete those rules |
| `com.madarsoft.` | Company/package prefix |
| `com\.madarsoft\.fitness` / `com\.madarsoft\.` | Same IDs, still escaped (logcat/lint/selftest) |
| `.features.splash.SplashActivity` | Real launcher (`/.MainActivity`, etc.) |
| Example theme wrapper | Real theme **or delete the rule** if none |
| `MVIViewModel` / `BaseComposeFragment` / Hilt | Real bases (e.g. `BaseViewModel` + Koin) or delete |
| `:app:assembleDebug` | `:<androidApplicationModule>:assembleDebug` |
| `app/build/outputs/apk/debug/app-debug.apk` | Real debug APK, **including** the `run_gradle_task.py` existence check |
| `app-debug.apk` after `REPO / "app"` was already renamed | Path pieces become `composeApp/.../app-debug.apk`. Rename the filename too. |
| Theme wrapper in subagent JSON / `compose-inspector` | Real theme token, or `MaterialTheme` if none |
| `REPO / "app" / "src" / "main"` | Real source root. Replacing only `"app"` is not enough: KMP Android res is often `composeApp/src/androidMain`, not `composeApp/src/main`. |
| `"madarsoft"` / `"fitness"` as **separate** Path args | `REPO / "com" / "madarsoft" / "fitness"` survives a replace of `com/madarsoft/fitness`. Replace each quoted piece. |
| Sender personal name | This team's developer name (who commits). Never copy portal ids or tokens. |
| `RASHAQA_REVIEW_PACKAGE` | Keep the name **or** rename everywhere |

## Install traps

- **I.4 allow emulator:** rewrite the **whole** `if serial.startswith("emulator-")` / `re.search(...emulator` blocks (condition + body) in `pre_tool_safety.py`, `run_device.py`, `capture_screen.py`, `logcat_doctor.py`. Deleting only `deny()` / `sys.exit` leaves a **SyntaxError**. Change `_hook_selftest.py` case `emu` from `deny` to `allow`. Keep `adb monkey` denied.
- **I.8 one locale:** if there is no second `values-*` folder, skip key parity in `check_strings.py` or preflight fails. Point `RES_DIR` at the real `res` root.
- **I.9 disable scaffold:** `_hook_selftest.py` still imports `new_feature_scaffold.VIEWMODEL` and `.SCREEN` (needs `locale = "ar"` / `"en"` and `isEmpty = true`). Keep those constants without leftover identity tokens, or selftest crashes. `main()` may still exit disabled.
- **Leftover grep:** do not write forbidden tokens even in “do not use …” sentences.
- **I.12:** if another product on this PC already uses `~/.gemini/config.json`, skip global writes.
- **Tool adapters:** do not hand-edit one `AGENTS.md` and skip the rest. Run `install_tool_adapters.py` so Cursor/Copilot/Cline/Qwen/Kilo/Goose/… stay in sync. Do not copy `remoteControlHostname`, tokens, or `sdk.dir`. Do not overwrite `.aider.conf.yml` or `~/.gemini`.

## Do not weaken

- 5-leaf review + `*_PASS`
- `pre_tool_safety.py` barrier (except package/activity strings)
- live `run_gradle_task.py` / `_live_process.py`
- `adb monkey` deny always. Emulator deny **only** if setup I.4 = physical only
- `code-review-guard-agent` retired / no `LGTM`

## After port, grep must not find

`madarsoft`, `Rashaqa`, `Fitness_Android`, `SplashActivity`, `com\\.madarsoft`, `app-debug.apk` (unless that is truly the APK name), `:app:assembleDebug` (unless the module is `:app`). Also grep the example product's original non-English display name (paired with Rashaqa in the source app).
