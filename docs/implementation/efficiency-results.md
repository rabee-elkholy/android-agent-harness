# Efficiency results

Local Linux/Python 3.12 synthetic fixtures; 25 paired warm iterations, alternating checkout order.
Native content caches are warmed explicitly. Bytes use the CLI JSON formatter (ASCII escaping, indentation and final newline).
Comparison is full native context against explicit unchanged presentation; the unsafe legacy repo-global notes omission is not assumed.

| Scenario | Facts reads before/after | Full baseline / unchanged candidate bytes | Median ms before/after | p95 ms before/after |
| --- | --- | --- | --- | --- |
| mixed | 2/1 | 21076/12087 | 22.75/22.88 | 27.10/32.16 |
| kmp | 2/1 | 21079/12090 | 22.74/22.04 | 27.39/24.78 |
| large | 2/1 | 21094/12105 | 115.75/117.45 | 128.36/135.33 |

Unchanged output is about 43% smaller than baseline full output and about 48% smaller than candidate full output.
Candidate full output is about 11% larger because it includes architecture advice. New chats always receive complete context.
One primary mixed-fixture p95 increased by >10%; a complete independent repeat gave 30.37/28.37 ms baseline/candidate instead. The variation was not consistent; no general speedup is claimed.
Replication medians: mixed 24.50/24.85 ms, KMP 23.19/22.84 ms, large 114.67/114.74 ms. Raw summaries for both runs are in efficiency-results.json.
Cold-query single samples are recorded separately in JSON and are not percentile estimates or process startup timings.
The KMP fixture adds platform files; it does not certify iOS compilation or complete expect/actual impact.
Existing verification benchmark: unchanged COMPLETE_TASK routing; median change -1.78% small fixture and +0.31% 500-doc fixture. These are noise-scale changes.
Review path lookup is one node-index pass plus path lookups instead of a graph scan per changed path. A deterministic regression test bounds node accesses on 500 nodes / 50 changed paths.
No persistent result cache or gate/reviewer skipping was added. No real Gradle/device/reviewer execution or model token savings were measured.

Validation: all 34 canonical suites passed (57 processes), including eight focused efficiency contracts; Python compilation, release metadata/checksums, wheel/sdist packaging and metadata passed.
These measurements were collected before publication. Release CI is tracked separately for the exact release commit; native Antigravity/Studio smoke testing was not performed.

Reproduce: `python scripts_dev/benchmark_efficiency.py --baseline <clean-baseline-checkout> --output <json-file>`; `python scripts_dev/benchmark_verification_value.py --output <json-file>`.
