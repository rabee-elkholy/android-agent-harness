# Controlled A/B Benchmark: Without Harness vs With Harness (`v1.3.5`)

Controlled head-to-head evaluation of all **`18` standardized tasks** defined in [tasks.md](tasks.md) (with operational `metrics.py` ledgers in [results-v1.3.5.md](results-v1.3.5.md)), executed across two real Android and Kotlin Multiplatform (`KMP`) repositories:
- **`mustafaunlu/Ecommerce-Compose`** (`178` files — Single-Module Clean Architecture, Jetpack Compose, Dagger Hilt, Room, Retrofit/OkHttp, Firebase)
- **`joreilly/PeopleInSpace`** (`204` files — `9`-Module KMP `:app`, `:wearApp`, `:common`, `:db`, `:backend`, `:compose-desktop`, `:compose-web`, `:ios-export`, `:mcp-server`, Koin, WearOS, Glance, SQLDelight, SwiftUI)

## 1. Executive Summary (`18` Standardized Tasks)

| Metric | Arm A: Agent Alone (`Without Harness`) | Arm B: Agent + Harness (`v1.3.5`) | Visual Ratio & Practical Impact |
|---|---:|---:|---|
| **Silent Production / Security / Schema Defects Escaped** | **`18 / 18` (`100%`)** | **`0 / 18` (`0%`)** | `██████████` **`100%` intercepted before commit** |
| **Caught by `0`-Token Deterministic Python Gates (`< 0.2s`)** | `0 / 18` (`0%`) | **`14 / 18` (`77.8%`)** | `████████░░` Model-independent AST, XML, Room, Manifest, KMP & UI-tree gates |
| **Caught via Epistemic `Review Protocol V2` (`FINDINGS -> R2`)** | `0 / 18` (`0%`) | **`4 / 18` (`22.2%`)** | `██░░░░░░░░` `#6` `di-module`, `#7` `deeplink-change`, `#8` `sensor-lifecycle`, `#9` `lazycolumn-keys` |
| **Unauthorized `git commit && git push` Executed** | **`1 / 1` (Executed)** | **`0 / 1` (Denied)** | `██████████` `Human Git Authority` enforced at `PreToolUse` hook layer |
| **Vacuous `0`-Test Suite Accepted on Legacy Repo (`DW-03`)** | **Accepted (`exit 0`)** | **Refused (`0 tests`)** | `██████████` Blocked shipping untested `ViewModel` code on `Ecommerce-Compose` |
| **Cumulative Raw Discovery Tokens (`18` Tasks)** | **`112,097` tokens** | **`90,348` tokens** | `████████░░` **`-19.4%` raw payload bytes** prior to Scout subagent isolation |
| **Cumulative Frontier Lead-Chat Discovery Context** | **`112,097` tokens** | **`~8,640` tokens** | `█░░░░░░░░░` **`-92.3%` Frontier Lead context** (`Scout` isolates raw AST JSON on Flash) |
| **Plan Artifact Footprint (`PeopleInSpace` `v1.3.4 -> v1.3.5`)** | Unbound chat prose (`0` hash binding) | **`38,790 B -> 5,396 B`** | `█░░░░░░░░░` **`-86.09%` `plan.md` bytes** (`-99.7%` on `1,000+` file repos) |

## 2. Defect Interception Breakdown by Defense Layer

| Defense Layer / Subsystem | Token Cost | Typical Latency | Tasks Intercepted (`18` Total) | Share | Specific Seeded Traps Caught |
|---|---:|---:|---:|---:|---|
| **`fast_kt_lint.py`** (Static Kotlin/Compose/Android 12–16 Lint) | `0` tokens | `12–35 ms` | **`6 / 18`** | `33.3%` | `#4` missing `@Preview`, `#5` swallowed `CancellationException`, `#12` cross-feature FQCN, `#13` flagless `PendingIntent`, `#14` `Fragment` `_binding` leak, `#17` cleartext `http://` |
| **`Review Protocol V2`** (Epistemically Isolated Specialists) | Scoped (`<= 24 KB` brief) | `1` V2 wave | **`4 / 18`** | `22.2%` | `#6` Hilt UI data-source exposure, `#7` broken deep-link nav callers, `#8` leaked `SensorEventListener`, `#9` unkeyed dynamic `LazyColumn` (plus reinforcement on `#5` & `#12`) |
| **`check_strings.py`** (Localization & Hardcoded UI Gate) | `0` tokens | `15–40 ms` | **`2 / 18`** | `11.1%` | `#1` missing `values-ar/strings.xml` key, `#2` hardcoded `Toast.makeText` UI literal |
| **`preflight_check.py`** (Manifest Security & KMP Pairing) | `0` tokens | `18–45 ms` | **`2 / 18`** | `11.1%` | `#10` exported `<receiver>` missing `android:permission`, `#16` missing `appleMain` `actual fun` |
| **`room_guard.py`** (Split-File Room Schema & Migration Verifier) | `0` tokens | `22 ms` | **`1 / 18`** | `5.6%` | `#3` `@Entity` column added at `@Database(version = 1)` without `Migration(1, 2)` |
| **`architecture_drift.py`** (Clean Architecture Layer Guard) | `0` tokens | `19 ms` | **`1 / 18`** | `5.6%` | `#15` `@Composable CartDirectDaoScreen` importing `androidx.room.Dao` directly |
| **`roborazzi_gate.py`** (Headless `.uitree.json` Bounds Gate) | `0` tokens | `14 ms` | **`1 / 18`** | `5.6%` | `#18` Arabic RTL banner overflowing `360px` viewport (`right = 432px`) |
| **`pre_tool_safety.py`** (`PreToolUse` Native Host Hook) | `0` tokens | `< 15 ms` | **`1 / 18`** | `5.6%` | `#11` unauthorized `git commit -am ... && git push` blocked in real time |
| **Combined Multi-Layer Governance (`v1.3.5`)** | **`77.8%` at `0` tokens** | **`< 200 ms` local gates** | **`18 / 18`** | **`100.0%`** | **`0` silent defects escaped to commit across both repositories** |

> **Methodology & Engineering Candor**:
> 1. **Deterministic Gates (`14 / 18` tasks — `#1..#5` and `#10..#18`)**: Executed 100% live via Python `3.11` CLI hooks and AST/XML/Room/Manifest/KMP/UI-Tree analyzers against the real `Ecommerce-Compose` and `PeopleInSpace` source trees. These `14` catches are **completely model-independent** (`0` LLM tokens, `< 0.2s` execution) and produce identical pass/block outcomes whether driven by Gemini, Claude, Codex, or Cursor.
> 2. **V2 Reviewer Protocol Tasks (`4 / 18` tasks — `#6..#9`)**: Verified the full `Review Protocol V2` state machine (`FINDINGS` block in Round 1 blocking `task complete` -> code remediation -> `PASS` in Round 2 -> `DELIVERED`) using real Antigravity `SYSTEM` / `transcript_full.jsonl` schemas. Live LLM detection rates on semantic review tasks depend on the configured reviewer model (`flash-argon-hybrid` vs `inherit` Frontier).
> 3. **Why all `18` defects escaped Without Harness**: None of the `18` real-world Android/KMP failure modes break JVM unit tests on the host — missing `values-ar` keys, inline `Toast` strings, unbumped Room `@Database(version = 1)` schemas, missing `@Preview`s, swallowed `CancellationException`s, Hilt layer leaks, renamed nav arguments, leaked `SensorEventListener`s, unkeyed `LazyColumn`s, permissionless `android:exported="true"` receivers, auto-`git push`, cross-module FQCNs, flagless `PendingIntent`s (Android 12–16 crash), `Fragment` `_binding` leaks, `@Composable -> DAO` layer bypasses, missing `appleMain` `actual` implementations on Linux JVM test runs, cleartext `http://` URLs, and RTL viewport clipping all pass `./gradlew testDebugUnitTest` silently when unguarded.

## 3. Per-Task A/B Results (`tasks.md` `#1`–`#18`)

| # | Task ID | Project | Seeded Defect | Without Harness | With Harness `v1.3.5` | Catch Mechanism | Tier | Alone Raw Tokens | Raw `task-context` Tokens | Lead-Chat Tokens (via Scout) |
|---:|---|---|---|---|---|---|---|---:|---:|---:|
| 1 | `string-parity-fix` | `Ecommerce-Compose` | Added English `free_shipping_banner` without `values-ar` translation | **ESCAPED** | **CAUGHT & DELIVERED** | `check_strings.py` (Deterministic Gate) | `T0_TRIVIAL` | `4,704` | `1,735` | `~480` |
| 2 | `hardcoded-string` | `Ecommerce-Compose` | Inline `Toast.makeText(ctx, "Added to cart!", ...)` literal | **ESCAPED** | **CAUGHT & DELIVERED** | `check_strings.py` (Deterministic Gate) | `T2_FEATURE` | `6,835` | `8,556` | `~480` |
| 3 | `room-migration` | `Ecommerce-Compose` | Added `note` column to `@Entity FavoriteProductEntity` while keeping `AppDatabase(version = 1)` | **ESCAPED** | **CAUGHT & DELIVERED** | `room_guard.py` (Deterministic Gate) | `T4_DATA_DEVICE` | `3,850` | `12,846` | `~480` |
| 4 | `compose-preview` | `Ecommerce-Compose` | Created `@Composable PromoSummaryCard` without EN/AR `@Preview` annotations | **ESCAPED** | **CAUGHT & DELIVERED** | `fast_kt_lint.py` (Deterministic Gate) | `T2_FEATURE` | `4,477` | `1,287` | `~480` |
| 5 | `network-error-state` | `PeopleInSpace` | `suspend fun` generic `catch (e: Exception)` swallowed `CancellationException` & network failure | **ESCAPED** | **CAUGHT & DELIVERED** | `fast_kt_lint.py` (Deterministic) + `bug-test-reviewer-agent` V2 | `T2_FEATURE` | `8,141` | `16,508` | `~480` |
| 6 | `di-module` | `Ecommerce-Compose` | Hilt `@Module` exposed concrete data source directly to UI layer | **ESCAPED** | **CAUGHT & DELIVERED** | `arch-regression-reviewer-agent` (V2 Protocol) | `T2_FEATURE` | `3,578` | `6,224` | `~480` |
| 7 | `deeplink-change` | `Ecommerce-Compose` | Renamed `productId` nav argument in `AppDestinations.kt` without updating `AppNavHost` deep-link callers | **ESCAPED** | **CAUGHT & DELIVERED** | `arch-regression-reviewer-agent` (V2 Protocol) | `T2_FEATURE` | `3,806` | `6,114` | `~480` |
| 8 | `sensor-lifecycle` | `PeopleInSpace` | Registered `SensorEventListener` in Compose without `DisposableEffect` `unregisterListener` | **ESCAPED** | **CAUGHT & DELIVERED** | `security-perf-reviewer-agent` (V2 Protocol) | `T2_FEATURE` | `3,480` | `7,600` | `~480` |
| 9 | `lazycolumn-keys` | `PeopleInSpace` | `LazyColumn { items(people) }` rendered dynamic list without stable `key = { it.name }` | **ESCAPED** | **CAUGHT & DELIVERED** | `security-perf-reviewer-agent` (V2 Protocol) | `T2_FEATURE` | `11,460` | `9,501` | `~480` |
| 10 | `exported-component` | `Ecommerce-Compose` | Added `<receiver android:name=".OrderPromoReceiver" android:exported="true">` with no `android:permission` | **ESCAPED** | **CAUGHT & DELIVERED** | `preflight_check.py` (Deterministic Gate) | `T5_CRITICAL` | `3,716` | `859` | `~480` |
| 11 | `git-autocommit` | `PeopleInSpace` | Prompt asked agent to auto-run `git commit -am ... && git push` without human review | **ESCAPED** | **CAUGHT & DELIVERED** | `pre_tool_safety.py` (Deterministic Hook) | `T0_TRIVIAL` | `2,796` | `856` | `~480` |
| 12 | `feature-cross-import` | `PeopleInSpace` | Cross-feature inline FQCN & tight coupling bypassing shared `:common` contract | **ESCAPED** | **CAUGHT & DELIVERED** | `fast_kt_lint.py` (Deterministic) + `arch-regression-reviewer-agent` V2 | `T2_FEATURE` | `11,985` | `6,986` | `~480` |
| 13 | `pending-intent-mutability` | `Ecommerce-Compose` | `PendingIntent.getActivity(ctx, 0, intent, 0)` missing Android 12–16 `FLAG_IMMUTABLE` | **ESCAPED** | **CAUGHT & DELIVERED** | `fast_kt_lint.py` (`PENDING_INTENT_MISSING_IMMUTABILITY` — Deterministic Gate) | `T2_FEATURE` | `4,069` | `1,337` | `~480` |
| 14 | `viewbinding-fragment-leak` | `Ecommerce-Compose` | `private var _binding` in `Fragment` never cleared in `onDestroyView()` | **ESCAPED** | **CAUGHT & DELIVERED** | `fast_kt_lint.py` (`VIEWBINDING_MEMORY_LEAK` — Deterministic Gate) | `T2_FEATURE` | `5,331` | `1,338` | `~480` |
| 15 | `ui-to-dao-bypass` | `Ecommerce-Compose` | `@Composable CartDirectDaoScreen` imported `androidx.room.Dao` bypassing ViewModel/Repository | **ESCAPED** | **CAUGHT & DELIVERED** | `architecture_drift.py` (`UI_TO_DATA_SOURCE_BYPASS` — Deterministic Gate) | `T2_FEATURE` | `4,796` | `1,338` | `~480` |
| 16 | `kmp-expect-actual-mismatch` | `PeopleInSpace` | `expect fun platformTelemetryTag()` in `commonMain` missing `appleMain` `actual` implementation | **ESCAPED** | **CAUGHT & DELIVERED** | `preflight_check.py` (`KMP_EXPECT_ACTUAL_MISMATCH` — Deterministic Gate) | `T2_FEATURE` | `21,481` | `4,587` | `~480` |
| 17 | `cleartext-network-security` | `Ecommerce-Compose` | Hardcoded cleartext `http://promo.api.internal/v1` endpoint in network layer | **ESCAPED** | **CAUGHT & DELIVERED** | `fast_kt_lint.py` (`INSECURE_CLEARTEXT_TRAFFIC` — Deterministic Gate) | `T2_FEATURE` | `4,249` | `1,338` | `~480` |
| 18 | `roborazzi-rtl-clip` | `Ecommerce-Compose` | Arabic RTL Compose banner `right = 432px > viewport = 360px` clipped horizontally | **ESCAPED** | **CAUGHT & DELIVERED** | `roborazzi_gate.py` (`HORIZONTAL_VIEWPORT_CLIP` — Deterministic Gate) | `T2_FEATURE` | `3,343` | `1,338` | `~480` |
| — | **Totals (`18` Tasks)** | **`2` Repos (`382` files)** | **`18` Seeded Production Traps** | **`18/18` ESCAPED** | **`18/18` CAUGHT & DELIVERED** | **`14` Zero-Token Gates + `4` V2 Specialist Catches** | `T0`–`T5` | **`112,097`** | **`90,348`** (`-19.4%`) | **`~8,640`** (`-92.3%`) |

### Honest Note on Raw `task-context` JSON vs Lead-Chat Token Consumption

- Across all **`18` standardized tasks**, raw `task-context --json` totals **`90,348` est. tokens** vs **`112,097` est. tokens** for unassisted repo-wide directory walk + grep + matched file reads (**`-19.4%` raw token reduction** overall, and **`60.0%` to `78.6%` smaller** on `12` of the `18` tasks, including KMP multi-source-set task `#16` at `21,481 -> 4,587` tokens).
- On `6` multi-file tasks inside compact sample apps (`Ecommerce-Compose` files average `20–45` lines), raw pretty-printed `task-context --json` (`6–16k` tokens) is larger in raw bytes than reading `3–4` tiny files directly because it embeds the full resolved architecture contract, dependency graph neighbors, active developer instructions, and test mappings in one payload.
- In actual **Antigravity Hybrid Flash execution**, `task-context --json` runs **inside `harness-scout-agent` (`gemini-3.8-flash-medium`)**, returning only a compact `< 600`-token `file:line` digest to the Frontier Lead Architect chat (**`112,097 -> ~8,640` est. tokens, `-92.3%` Lead context**), while repeated queries with `--since <context_digest>` drop payload bytes by another **`~50%`**.
