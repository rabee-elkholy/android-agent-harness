# Benchmark Results Template

Copy this file to `results-<date>.md` and fill one column pair per arm.
Arms: **agent alone** vs **agent + harness**, same task list
([tasks.md](tasks.md)), one fresh chat per task per arm.

Metrics collector: `python scripts_dev/benchmark/metrics.py --run-dir <dir> --label "<arm>"`

## Results

| Task | Alone retries | Alone blocks | Alone build fails | Alone test fails | Alone interventions | Alone min | Harness retries | Harness blocks | Harness build fails | Harness test fails | Harness interventions | Harness min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| string-parity-fix | | | | | | | | | | | | |
| hardcoded-string | | | | | | | | | | | | |
| room-migration | | | | | | | | | | | | |
| compose-preview | | | | | | | | | | | | |
| network-error-state | | | | | | | | | | | | |
| di-module | | | | | | | | | | | | |
| deeplink-change | | | | | | | | | | | | |
| sensor-lifecycle | | | | | | | | | | | | |
| lazycolumn-keys | | | | | | | | | | | | |
| exported-component | | | | | | | | | | | | |
| git-autocommit | | | | | | | | | | | | |
| feature-cross-import | | | | | | | | | | | | |
| **Totals** | | | | | | | | | | | | |

## Cost estimate

| Arm | Total tokens | Est. cost (model rate x tokens) | Notes |
|---|---|---|---|
| Agent alone | | | |
| Agent + harness | | | |

## Notes

- Model and reasoning tier used per arm:
- Date(s):
- Any deviations from the run protocol:
