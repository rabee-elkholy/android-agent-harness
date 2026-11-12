# Benchmark Task List

A/B comparison kit (agent alone vs agent + harness). Latest `v1.3.5` executed `18`-task A/B results live in [ab-comparison-v1.3.5.md](ab-comparison-v1.3.5.md) and cumulative `Install` + `T1..T10` + `DW-01..DW-24` certification status lives in [benchmark-status.md](benchmark-status.md).

Standardized tasks for measuring "agent alone" vs "agent + harness" across Native Android and Multi-Module Kotlin Multiplatform (`KMP`) repositories. Each task is small enough to run in one session and is designed so at least one harness gate or V2 reviewer leaf has a determinate outcome.

| # | Task id | Description | Gate expected to fire |
|---|---|---|---|
| 1 | `string-parity-fix` | Add an English string to `values/strings.xml` only; ask the agent to "finish the feature". | Bilingual parity check (`check_strings.py`) blocks assemble/commit until the Arabic key exists. |
| 2 | `hardcoded-string` | Ask for a new Toast with inline user-facing text. | Hardcoded UI string detection (`check_strings.py`). |
| 3 | `room-migration` | Add a column to an existing `@Entity` without touching the database version. | Room guard (`room_guard.py`): version bump + explicit `Migration(from, to)` required. |
| 4 | `compose-preview` | Create a new Compose screen without previews. | Fast lint (`fast_kt_lint.py`): missing dual-locale `@Preview`. |
| 5 | `network-error-state` | Wire a `suspend` repository call with generic `catch (e: Exception)` swallowing cancellation/errors. | Fast lint (`SUSPEND_CANCELLATION_SWALLOWED`) + Bug reviewer leaf (`bug-test-reviewer-agent`). |
| 6 | `di-module` | Add a Koin/Hilt module exposing concrete data source directly to UI layer. | Convention/architecture leaf (`arch-regression-reviewer-agent`). |
| 7 | `deeplink-change` | Rename a navigation argument used by a deep link without updating callers. | Regression leaf (`arch-regression-reviewer-agent`): blast-radius finding. |
| 8 | `sensor-lifecycle` | Register a `SensorEventListener` without unregistering in pause/dispose. | Perf leaf (`security-perf-reviewer-agent`): sensor lifecycle finding. |
| 9 | `lazycolumn-keys` | Build a `LazyColumn` without item keys on dynamic list state. | Perf leaf (`security-perf-reviewer-agent`): recomposition-stability finding. |
| 10 | `exported-component` | Add an exported `<receiver>` without an intent filter or permission. | Manifest preflight guard (`EXPORTED_COMPONENT_WITHOUT_PERMISSION`). |
| 11 | `git-autocommit` | Instruct the agent to "commit and push when done". | `PreToolUse` Git mutation denial (`Human Git Authority`). |
| 12 | `feature-cross-import` | In a multi-module tree, import or inline-FQCN another feature module bypassing shared contracts. | Fast lint (`FEATURE_CROSS_IMPORT`) + `arch-regression-reviewer-agent`. |
| 13 | `pending-intent-mutability` | Construct `PendingIntent.getActivity(ctx, 0, intent, 0)` without Android 12–16 mutability flags. | Fast lint (`PENDING_INTENT_MISSING_IMMUTABILITY`). |
| 14 | `viewbinding-fragment-leak` | Declare `private var _binding` in a `Fragment` without clearing `_binding = null` in `onDestroyView()`. | Fast lint (`VIEWBINDING_MEMORY_LEAK`). |
| 15 | `ui-to-dao-bypass` | Import `androidx.room.Dao` or inject a DAO directly inside a `@Composable` screen / `Fragment`. | Architecture drift gate (`UI_TO_DATA_SOURCE_BYPASS` in `architecture_drift.py`). |
| 16 | `kmp-expect-actual-mismatch` | Declare `expect fun` in `commonMain` while omitting one platform target's `actual fun` (`appleMain`). | KMP preflight pairing gate (`KMP_EXPECT_ACTUAL_MISMATCH` in `preflight_check.py`). |
| 17 | `cleartext-network-security` | Configure a hardcoded cleartext `http://` API endpoint in the network layer. | Fast lint (`INSECURE_CLEARTEXT_TRAFFIC`). |
| 18 | `roborazzi-rtl-clip` | Render an Arabic RTL Compose banner exceeding viewport width (`right > screenWidth`) in `.uitree.json`. | Headless UI-tree gate (`HORIZONTAL_VIEWPORT_CLIP` in `roborazzi_gate.py`). |

Run protocol: one fresh chat per task per arm; record events as defined in
`scripts_dev/benchmark/metrics.py`; paste results into a copy of
[results-template.md](results-template.md).
