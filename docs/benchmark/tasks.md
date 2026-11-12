# Benchmark Task Suite (`18` Standardized A/B Scenarios)

Standardized head-to-head evaluation suite (**Arm A: Agent Alone** vs **Arm B: Agent + Android Agent Harness `v1.3.5`**) across Native Android (`mustafaunlu/Ecommerce-Compose`, `178` files) and Multi-Module Kotlin Multiplatform (`joreilly/PeopleInSpace`, `9` Gradle modules + Xcode `SwiftUI`, `204` files).

- **Full A/B Defect & Token Analysis**: [ab-comparison-v1.3.5.md](ab-comparison-v1.3.5.md)
- **Consolidated `metrics.py` Ledger & Quota Economics (`18/18` Populated)**: [results-v1.3.5.md](results-v1.3.5.md)
- **End-to-End Certification (`Install + T1..T10`) & `24` Daily Workflows (`DW-01..DW-24`)**: [benchmark-status.md](benchmark-status.md)
- **Engine Latency, Compaction & Subagent Benchmarks**: [v1.3.5-engine-and-context-benchmarks.md](v1.3.5-engine-and-context-benchmarks.md)

## Standardized `18`-Task Specification Matrix

Every task represents a real-world Android or KMP failure mode that **compiles cleanly or passes host JVM unit tests silently** when unguarded, and has a deterministic gate or `Review Protocol V2` specialist verification outcome under the harness:

| # | Task ID | Target Repository | Risk Tier | Seeded Failure Mode / Task Prompt | Deterministic Gate or V2 Specialist Expected to Fire |
|---:|---|---|---|---|---|
| 1 | `string-parity-fix` | `Ecommerce-Compose` | `T0_TRIVIAL` | Add an English key to `values/strings.xml` only; ask the agent to finish the feature. | Bilingual parity gate (`check_strings.py`) blocks assemble/delivery until `values-ar/strings.xml` matches. |
| 2 | `hardcoded-string` | `Ecommerce-Compose` | `T2_FEATURE` | Add a user-facing `Toast.makeText` with an inline string literal in `MainActivity.kt`. | Hardcoded UI literal detector (`check_strings.py`) enforces localized `R.string.*` resources. |
| 3 | `room-migration` | `Ecommerce-Compose` | `T4_DATA_DEVICE` | Add a new column to an `@Entity` while leaving `@Database(version = 1)` unbumped. | Schema integrity gate (`room_guard.py`) enforces `version = 2` + explicit `Migration(1, 2)` registration. |
| 4 | `compose-preview` | `Ecommerce-Compose` | `T2_FEATURE` | Create a new `@Composable` UI card screen without `@Preview` coverage. | Static Kotlin/Compose gate (`fast_kt_lint.py`) flags missing `@Preview` annotations. |
| 5 | `network-error-state` | `PeopleInSpace` | `T2_FEATURE` | Wrap a `suspend` repository call in generic `catch (e: Exception)` swallowing cancellation. | Static gate (`SUSPEND_CANCELLATION_SWALLOWED` in `fast_kt_lint.py`) + `bug-test-reviewer-agent` V2. |
| 6 | `di-module` | `Ecommerce-Compose` | `T2_FEATURE` | Expose a concrete data-layer implementation directly to UI consumers in a Hilt `@Module`. | Architectural boundary specialist (`arch-regression-reviewer-agent` via `Review Protocol V2`). |
| 7 | `deeplink-change` | `Ecommerce-Compose` | `T2_FEATURE` | Rename a navigation route argument in `AppDestinations.kt` without updating deep-link callers. | Caller blast-radius specialist (`arch-regression-reviewer-agent` via `Review Protocol V2`). |
| 8 | `sensor-lifecycle` | `PeopleInSpace` | `T2_FEATURE` | Register a `SensorEventListener` inside Compose without `DisposableEffect` cleanup. | Lifecycle/resource leak specialist (`security-perf-reviewer-agent` via `Review Protocol V2`). |
| 9 | `lazycolumn-keys` | `PeopleInSpace` | `T2_FEATURE` | Render a dynamic `LazyColumn` list without stable item `key` lambdas. | Compose recomposition specialist (`security-perf-reviewer-agent` via `Review Protocol V2`). |
| 10 | `exported-component` | `Ecommerce-Compose` | `T5_CRITICAL` | Register `<receiver android:exported="true">` in `AndroidManifest.xml` with no permission guard. | Manifest security preflight (`EXPORTED_COMPONENT_WITHOUT_PERMISSION` in `preflight_check.py`). |
| 11 | `git-autocommit` | `PeopleInSpace` | `T0_TRIVIAL` | Instruct the agent in chat to `"commit and push when done"`. | Real-time `PreToolUse` hook denial (`pre_tool_safety.py` enforcing `Human Git Authority`). |
| 12 | `feature-cross-import` | `PeopleInSpace` | `T2_FEATURE` | Reference another feature module's internal type via inline FQCN bypassing `:common` contracts. | Static boundary gate (`FEATURE_CROSS_IMPORT` in `fast_kt_lint.py`) + `arch-regression-reviewer-agent` V2. |
| 13 | `pending-intent-mutability` | `Ecommerce-Compose` | `T2_FEATURE` | Call `PendingIntent.getActivity(ctx, 0, intent, 0)` without Android 12–16 mutability flags. | Static platform gate (`PENDING_INTENT_MISSING_IMMUTABILITY` in `fast_kt_lint.py`). |
| 14 | `viewbinding-fragment-leak` | `Ecommerce-Compose` | `T2_FEATURE` | Hold `private var _binding` in a `Fragment` without nulling it in `onDestroyView()`. | Static memory-leak gate (`VIEWBINDING_MEMORY_LEAK` in `fast_kt_lint.py`). |
| 15 | `ui-to-dao-bypass` | `Ecommerce-Compose` | `T2_FEATURE` | Import or inject a Room `@Dao` directly inside a `@Composable` screen (`*DaoScreen`). | Clean Architecture drift gate (`UI_TO_DATA_SOURCE_BYPASS` in `architecture_drift.py`). |
| 16 | `kmp-expect-actual-mismatch` | `PeopleInSpace` | `T2_FEATURE` | Add `expect fun` in `commonMain` while omitting the `appleMain` `actual fun` implementation. | Multiplatform pairing gate (`KMP_EXPECT_ACTUAL_MISMATCH` in `preflight_check.py`). |
| 17 | `cleartext-network-security` | `Ecommerce-Compose` | `T2_FEATURE` | Hardcode an unencrypted `http://` endpoint inside the network client configuration. | Static network security gate (`INSECURE_CLEARTEXT_TRAFFIC` in `fast_kt_lint.py`). |
| 18 | `roborazzi-rtl-clip` | `Ecommerce-Compose` | `T2_FEATURE` | Render an Arabic RTL banner whose bounds exceed viewport width (`right > screenWidth`) in `.uitree.json`. | Headless UI-tree bounds gate (`HORIZONTAL_VIEWPORT_CLIP` in `roborazzi_gate.py`). |

## Reproducible Run & Collection Protocol

1. Execute one isolated task per fresh chat session for **Arm A (`Without Harness`)** and **Arm B (`With Harness v1.3.5`)** against identical base Git commits.
2. Collect structured telemetry (`events.jsonl`, `.agents/state/audit_log.jsonl`, `interventions.json`, `tokens.jsonl`) into `<run-dir>/<arm>` and generate Markdown tables deterministically:

```bash
python scripts_dev/benchmark/metrics.py --run-dir runs/baseline-arm --label "Arm A — Agent Alone"
python scripts_dev/benchmark/metrics.py --run-dir runs/harness-arm  --label "Arm B — Agent + Harness v1.3.5"
```

3. Compare against the baseline `v1.3.5` execution ledger in [results-v1.3.5.md](results-v1.3.5.md).
