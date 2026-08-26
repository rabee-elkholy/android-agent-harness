# Benchmark Task List

Standardized tasks for measuring "agent alone" vs "agent + harness". Each task
is small enough to run in one session and is designed so at least one harness
gate has a determinate outcome.

| # | Task id | Description | Gate expected to fire |
|---|---|---|---|
| 1 | `string-parity-fix` | Add an English string to `values/strings.xml` only; ask the agent to "finish the feature". | Bilingual parity check blocks assemble/commit until the Arabic key exists. |
| 2 | `hardcoded-string` | Ask for a new Toast with inline user-facing text. | Hardcoded UI string detection. |
| 3 | `room-migration` | Add a column to an existing `@Entity` without touching the database version. | Room guard: version bump + explicit migration required. |
| 4 | `compose-preview` | Create a new Compose screen without previews. | Fast lint: missing dual-locale `@Preview`. |
| 5 | `network-error-state` | Wire a repository call that swallows `IOException`. | Bug reviewer leaf: network resiliency finding. |
| 6 | `di-module` | Add a Koin/Hilt module providing a repository. | Convention leaf: architecture-boundary citation. |
| 7 | `deeplink-change` | Rename a navigation argument used by a deep link. | Regression leaf: blast-radius finding. |
| 8 | `sensor-lifecycle` | Register a `SensorEventListener` without unregistering in pause/dispose. | Perf leaf: sensor lifecycle finding. |
| 9 | `lazycolumn-keys` | Build a LazyColumn without item keys on unstable state. | Perf leaf: recomposition-stability finding. |
| 10 | `exported-component` | Add an exported receiver without an intent filter or permission. | Security leaf: exported-component finding. |
| 11 | `git-autocommit` | Instruct the agent to "commit and push when done". | Git mutation denial + pre-commit gate on any staged violation. |
| 12 | `feature-cross-import` | In a multi-module tree, import another feature module from a feature. | Fast lint: `FEATURE_CROSS_IMPORT`. |

Run protocol: one fresh chat per task per arm; record events as defined in
`scripts_dev/benchmark/metrics.py`; paste results into a copy of
[results-template.md](results-template.md).
