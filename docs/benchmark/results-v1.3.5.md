# Benchmark Execution Results & Quota Economics (`v1.3.5`)

Complete, side-by-side operational scorecard for all **`18` standardized benchmark tasks** ([tasks.md](tasks.md)) executed across **`mustafaunlu/Ecommerce-Compose`** (`178` files) and **`joreilly/PeopleInSpace`** (`9`-module `KMP`, `204` files), collected via `scripts_dev/benchmark/metrics.py`.

## 1. Consolidated `18`-Task Side-by-Side Execution Ledger

| # | Task ID | Alone Retries | Alone Blocks | Alone Build Fails | Alone Test Fails | Alone Interventions | Alone Lead Tokens | Alone Defect Outcome | Harness Retries | Harness Blocks | Harness Build Fails | Harness Test Fails | Harness Interventions | Harness Lead Tokens | Harness CLI Sec | Harness Outcome |
|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `string-parity-fix` | `0` | `0` | `0` | `0` | `0` | `4,704` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.11s` | **`DELIVERED`** |
| 2 | `hardcoded-string` | `0` | `0` | `0` | `0` | `0` | `6,835` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.13s` | **`DELIVERED`** |
| 3 | `room-migration` | `0` | `0` | `0` | `0` | `0` | `3,850` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.15s` | **`DELIVERED`** |
| 4 | `compose-preview` | `0` | `0` | `0` | `0` | `0` | `4,477` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.10s` | **`DELIVERED`** |
| 5 | `network-error-state` | `0` | `0` | `0` | `0` | `0` | `8,141` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.14s` | **`DELIVERED`** |
| 6 | `di-module` | `0` | `0` | `0` | `0` | `0` | `3,578` | `ESCAPED` | `1` | `1` | `0` | `0` | `2` | `480` | `0.12s` | **`DELIVERED`** |
| 7 | `deeplink-change` | `0` | `0` | `0` | `0` | `0` | `3,806` | `ESCAPED` | `1` | `1` | `0` | `0` | `2` | `480` | `0.12s` | **`DELIVERED`** |
| 8 | `sensor-lifecycle` | `0` | `0` | `0` | `0` | `0` | `3,480` | `ESCAPED` | `1` | `1` | `0` | `0` | `2` | `480` | `0.12s` | **`DELIVERED`** |
| 9 | `lazycolumn-keys` | `0` | `0` | `0` | `0` | `0` | `11,460` | `ESCAPED` | `1` | `1` | `0` | `0` | `2` | `480` | `0.13s` | **`DELIVERED`** |
| 10 | `exported-component` | `0` | `0` | `0` | `0` | `0` | `3,716` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.09s` | **`DELIVERED`** |
| 11 | `git-autocommit` | `0` | `0` | `0` | `0` | `0` | `2,796` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.04s` | **`DELIVERED`** |
| 12 | `feature-cross-import` | `0` | `0` | `0` | `0` | `0` | `11,985` | `ESCAPED` | `1` | `2` | `0` | `0` | `2` | `480` | `0.14s` | **`DELIVERED`** |
| 13 | `pending-intent-mutability` | `0` | `0` | `0` | `0` | `0` | `4,069` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.10s` | **`DELIVERED`** |
| 14 | `viewbinding-fragment-leak` | `0` | `0` | `0` | `0` | `0` | `5,331` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.10s` | **`DELIVERED`** |
| 15 | `ui-to-dao-bypass` | `0` | `0` | `0` | `0` | `0` | `4,796` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.11s` | **`DELIVERED`** |
| 16 | `kmp-expect-actual-mismatch` | `0` | `0` | `0` | `0` | `0` | `21,481` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.16s` | **`DELIVERED`** |
| 17 | `cleartext-network-security` | `0` | `0` | `0` | `0` | `0` | `4,249` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.09s` | **`DELIVERED`** |
| 18 | `roborazzi-rtl-clip` | `0` | `0` | `0` | `0` | `0` | `3,343` | `ESCAPED` | `0` | `1` | `0` | `0` | `2` | `480` | `0.19s` | **`DELIVERED`** |
| — | **Totals (`18` Tasks)** | **`0`** | **`0`** | **`0`** | **`0`** | **`0`** | **`112,097`** | **`18/18 ESCAPED`** | **`5`** | **`19`** | **`0`** | **`0`** | **`36`** (`2`/task) | **`~8,640`** | **`2.14s`** | **`18/18 DELIVERED`** |

### Column Interpretation Notes
- **`Alone Blocks = 0` & `Alone Retries = 0`**: Without the harness, all `18` seeded Android/KMP defects compiled cleanly or passed JVM unit tests without triggering any warning, escaping straight to commit (`100%` silent defect escape rate).
- **`Harness Blocks = 19` & `Harness Retries = 5`**: `14` defects were intercepted immediately at `0` LLM tokens by deterministic Python preflight/hook gates (`< 0.2s` each), and `4` semantic/architectural defects (`#6`, `#7`, `#8`, `#9`, plus dual-layer reinforcement on `#12`) triggered `Review Protocol V2` `FINDINGS` in Round `1`, were remediated, and passed Round `2`.
- **`Harness Interventions = 2` per task (`36` total)**: Represents the two deliberate constitutional checkpoints per task — **1 single-shot plan approval** (`plan_sha256` + nonce) prior to source edits and **1 developer `git commit` sign-off** under `Human Git Authority`.

## 2. Discovery Token Footprint & Frontier Quota Economics

| Arm | Lead-Chat Discovery Tokens (`18` Tasks) | Isolated Subagent / CLI Tokens (`Flash Medium`) | Frontier Quota Impact (`Gemini 4 Carbon` / `Argon`) | Architectural Summary |
|---|---:|---:|---|---|
| **Arm A: Agent Alone** (`Without Harness`) | **`112,097` tokens** (`100%` in Frontier Lead chat) | `0` tokens (no subagent isolation) | **High Frontier Quota Burn** — every directory walk, grep sweep, and multi-file read accumulates permanently in the primary Lead context window | Unbounded Lead context growth increases per-turn latency and accelerates weekly Frontier quota exhaustion |
| **Arm B: Agent + Harness `v1.3.5`** (`flash-argon-hybrid`) | **`~8,640` tokens** (`~480`-token `file:line` Scout digest/task) | **`90,348` raw `task-context` tokens** isolated inside `gemini-3.8-flash-medium` `harness-scout-agent` | **`-92.3%` Frontier Lead Discovery Context** — `TRIVIAL`/`SIMPLE` slices consume `0` `Gemini 4` subagent calls; `COMPLEX`/`CRITICAL` cap strictly at `gemini-4-argon-low` | Deterministic Python gates catch `77.8%` (`14/18`) of defects at **`0` tokens**, preserving Frontier reasoning strictly for planning and `T4/T5` code |

## 3. Protocol & Environment Metadata

- **Harness Version & Integrity**: `v1.3.5` (`265` SHA-256 tracked payload files, `36/36` selftest suites / `59` parallel processes `PASS`, `40/40` `doctor --install-check` `PASS`).
- **Model & Routing Policy**: Lead Architect (`Gemini 4 Carbon Medium`) + `flash-argon-hybrid` (`gemini-3.8-flash-medium` for `harness-scout-agent`, `SIMPLE` slices, and `NORMAL` structural review; hard ceiling at `gemini-4-argon-low` for `COMPLEX` Worker slices and `DEEP`/`CRITICAL` specialist reviews).
- **Execution Date**: `2026-11-12`.
- **Protocol Compliance**: Strict 1-task-per-session isolation across `mustafaunlu/Ecommerce-Compose` and `joreilly/PeopleInSpace`. Local CLI/gate timings (`2.14s` cumulative across `18` tasks) measure deterministic Python hook, AST graph, XML/Room/Manifest/KMP/UI-tree preflight, and `EvidenceStore` cryptographic binding overhead on warm cache, excluding external Maven downloads and LLM generation latency.
