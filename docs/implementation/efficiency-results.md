# Context & Topology Efficiency Results (v1.3.5)

Generated from `scripts_dev/benchmark_efficiency.py` (`25` paired warm samples in alternating order) and `scripts_dev/benchmark_context_output.py` on `mustafaunlu/Ecommerce-Compose` and `joreilly/PeopleInSpace`.

| Scenario | Median (`ms`) | `p95` (`ms`) | `facts_reads` | `SUMMARY` Bytes | `--since` Bytes | `--since` Saving |
|---|---:|---:|---:|---:|---:|---:|
| `mixed` | `14.75` | `15.28` | `1` | `22,774` | `11,439` | `-49.77%` |
| `kmp` | `14.98` | `16.89` | `1` | `22,776` | `11,441` | `-49.77%` |
| `large (+500)` | `45.69` | `52.74` | `1` | `22,786` | `11,451` | `-49.75%` |

Full details: [../benchmark/v1.3.5-engine-and-context-benchmarks.md](../benchmark/v1.3.5-engine-and-context-benchmarks.md) and [../benchmark/ab-comparison-v1.3.5.md](../benchmark/ab-comparison-v1.3.5.md).
