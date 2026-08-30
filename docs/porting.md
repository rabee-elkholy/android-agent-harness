# Porting tokens

Naive replace of a display name is not enough. After copy, **fill product constants** and rewrite architecture from **this** checkout.

The kit ships generic defaults in `agents/scripts/_product.py` (`com.example.app`, `.MainActivity`, `:app:assembleDebug`). Setup overwrites them from Gradle/manifests. Do **not** copy a parent product's company, package, or launcher into a stranger app.

## Fill from disk

| Kit default | Replace with |
|---|---|
| `PRODUCT_NAME` in `_product.py` and `harness-rules.md` title | I.1 product name |
| `APPLICATION_ID` / `PACKAGE_PREFIX` | Real `applicationId` (keep regex escapes in logcat/lint) |
| `LAUNCHER` | Real launcher (`applicationId/.MainActivity`, etc.) |
| `ASSEMBLE_TASK` / `UNIT_TEST_TASK` | `:<androidApplicationModule>:assembleDebug` / `testDebugUnitTest` |
| `APK_RELATIVE` | Real debug APK, **including** the `run_gradle_task.py` existence check. Glob `**/outputs/apk/debug/*.apk` if the filename is unknown. |
| `ANDROID_SRC` path pieces | Real source root. Replacing only `"app"` is not enough: KMP Android res is often `composeApp/src/androidMain`, not `composeApp/src/main`. |
| Theme wrapper in subagent JSON / `compose-inspector` | Real theme token, or `MaterialTheme` if none |
| DI / ViewModel base in `architecture-guidelines.md` | Real bases (Koin + `BaseViewModel`, Hilt + MVI, …) or delete invented rules |
| Sender personal name | This team's developer name (who commits). Never copy portal ids or tokens. |

`HARNESS_REVIEW_PACKAGE` and `HARNESS_*_FINGERPRINT` stay. Rename everywhere if you rebrand those env tokens.

## Install traps

- **I.4 allow emulator:** Set `ALLOW_EMULATOR = True` (or `False` for physical device only) in `_product.py`. Device runners (`run_device.py`, `logcat_doctor.py`, `capture_screen.py`) automatically consume this centralized policy. Keep `adb monkey` denied.
- **I.8 one locale:** if there is no second `values-*` folder, skip key parity in `check_strings.py` or preflight fails. Point `RES_DIR` at the real `res` root.
- **I.9 scaffold:** do not ask. `main()` stays disabled. `_hook_selftest.py` still imports `new_feature_scaffold.VIEWMODEL` and `.SCREEN` (needs `locale = "ar"` / `"en"` and `isEmpty = true`). Keep those constants.
- **Leftover grep:** do not write forbidden parent-product tokens even in “do not use …” sentences inside `.agents`.
- **I.12:** if another product on this PC already uses `~/.gemini/config.json`, skip global writes.
- **I.16 Zoho Sprints:** run `install_zoho_mcp.py --enable` or `--disable` from answers. Never copy `zoho_config.json`, refresh tokens, or client secrets into the repo. Point `ZOHO_SPRINTS_CONFIG` at an existing user-level file when one is already on this PC. Do not write `~/.gemini/config/mcp_config.json`.
- **Tool adapters:** do not hand-edit one `AGENTS.md` and skip the rest. Run `install_tool_adapters.py --tools <selected ids>`. Do not copy `remoteControlHostname`, tokens, or `sdk.dir`. Do not overwrite `.aider.conf.yml` or `~/.gemini`.

## Do not weaken

- 5-leaf review + `*_PASS`
- `pre_tool_safety.py` barrier (except package/activity strings)
- live `run_gradle_task.py` / `_live_process.py`
- `adb monkey` deny always. Emulator deny **only** if setup I.4 = physical only
- `code-review-guard-agent` retired / no `LGTM`

## After port, grep `.agents` must not find

After port, grep `.agents` for any leftover references to the project the kit was originally extracted from. The install selftest (`_hook_selftest.py`) checks for kit placeholder leftovers automatically (`com.example.app`, `com.example`, `this Android app`). Setup adds project-specific needles during install.

Theme-wrapper name only if they kept it. `HARNESS_REVIEW_PACKAGE` may stay.
