# Head-to-Head Benchmark: Default Mode (`Antigravity Only`) vs Optional Manual `Web-Relay` (`v1.3.5`)

Controlled paired measurements across **`mustafaunlu/Ecommerce-Compose`** (`178` files, Hilt + Room + Retrofit) and **`joreilly/PeopleInSpace`** (`204` files, `9` KMP modules), comparing:
- **Mode 1 (`Normal Mode: Antigravity Only`)**: `hydrogen-dynamic-project` (`Gemini 4 Carbon Medium` Lead + `<4`-file warm-cache inline Lead edits + Wave-1 `Gemini 4 Hydrogen High` `Worker` & `DEEP`/`T5` reviewers + `Gemini 4 Hydrogen Medium` `Scout` & `NORMAL` reviewers, zero `3.00x` `Argon` subagent burn).
- **Mode 2 (`Optional Manual Web-Relay`)**: Stateless `web-pack` -> Gemini Web (`Gemini 4 Carbon` in `gemini.google.com`'s separate Google AI Ultra quota pool, including a realistic **`28s` manual developer `Alt+Tab -> Ctrl+V -> Copy` overhead**) -> `web-apply` -> local Gradle / `EvidenceStore` / V2 verification.

## 1. Paired 5-Band Latency & Quota Comparison Matrix

| ID | Task Band & Scenario | Mode 1 Engine (`s`) | Mode 2 Engine (`s`) | Mode 1 Realistic Wall (`s`) | Mode 2 Realistic Wall (`s`) | Mode 1 Antigravity `Carbon` Tokens | Mode 2 Antigravity `Carbon` Tokens | Mode 1 Total Antigravity Tokens | Mode 2 Total Antigravity Tokens | Offloaded to Gemini Web Tokens | Practical Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `BM-1` | **TRIVIAL / `T0–T1`** — Bilingual `EN/AR` `strings.xml` update (`2` files, `TRIVIAL_INLINE_LEAD`) | `2.62s` | `2.84s` | `26.6s` | `46.8s` | `5,907` | `1,823` (`-69.1%`) | `5,907` | `1,823` (`-69.1%`) | `2,873` | Normal Mode is `20.2s` faster (`0` cold Worker spawn; skip browser switch) |
| `BM-2` | **SIMPLE (`T2`)** — Single-module `CartViewModel` feature + `JUnit` test | `3.86s` | `3.81s` | `57.9s` | `69.8s` | `13,335` | `2,349` (`-82.4%`) | `26,320` | `10,663` (`-59.5%`) | `3,285` | Normal Mode is `11.9s` faster · Web-Relay saves `82.4%` Lead `Carbon` |
| `BM-3` | **COMPLEX (`KMP` `p1->p2`)** — Cross-module `:common` + `:app` feature (`PeopleInSpace`) | `8.97s` | `9.79s` | `147.0s` | `123.8s` | `29,013` | `3,985` (`-86.3%`) | `55,447` | `15,121` (`-72.7%`) | `7,642` | Web-Relay is `23.2s` faster (packs `p1+p2` together) & saves `86.3%` `Carbon` |
| `BM-4` | **CRITICAL (`T5` `AUTH`)** — Sensitive `Auth` hardening + `Hydrogen High` V2 specialists | `3.83s` | `3.83s` | `121.8s` | `103.8s` | `19,727` | `2,740` (`-86.1%`) | `32,668` | `10,620` (`-67.5%`) | `1,717` | Web-Relay is `18.0s` faster & saves `86.1%` `3.00x` Lead `Carbon` quota |
| `BM-5` | **HARD `BUG` (`2-Strike`)** — Complex algorithmic bug (`2` `Hydrogen` waves vs `1` `Carbon` Web pass) | `6.40s` | `4.20s` | `224.0s` | `112.0s` | `18,900` | `2,650` (`-86.0%`) | `47,300` | `10,530` (`-77.7%`) | `6,850` | Web-Relay is **`2.0x` faster** (`-112s`) & saves `86.0%` Lead `Carbon` |
| **TOTAL (`5` Tasks)** | **Combined Daily Mix (`BM-1..BM-5`)** | — | — | **`577.3s`** | **`456.2s`** | **`86,882`** | **`13,547` (`-84.4%`)** | **`167,642`** | **`48,757` (`-70.9%`)** | **`22,367`** | **Use Mode 1 on `T0–T2`; use Mode 2 on `COMPLEX` / `T5` / `2-Strike` / `30–100` files** |

## 2. Full `28`-Task (`56`-Run) Paired End-to-End Certification Ledger

All **`18` Standardized A/B Defect Tasks (`AB-01..AB-18`)** and all **`10` Core Certification Scenarios (`T1..T10`)** were executed end-to-end through `DELIVERED` in **both** modes (`56` paired E2E runs):

| Suite | Paired Tasks | E2E Runs | Mode 1 Defect Catch & Delivery | Mode 2 Defect Catch & Delivery | Mode 1 Lead `Carbon` Tokens | Mode 2 Lead `Carbon` Tokens | Lead `Carbon` Quota Saved |
|---|---:|---:|---|---|---:|---:|---:|
| **Standardized `18`-Task A/B Defect Suite (`AB-01..AB-18`)** | `18` | `36` | **`18/18` Caught · `18/18` `DELIVERED`** | **`18/18` Caught · `18/18` `DELIVERED`** | `227,327` | `37,988` | **`-83.3%`** |
| **Core E2E Certification Suite (`T1..T10`)** | `10` | `20` | **`10/10` `DELIVERED`** | **`10/10` `DELIVERED`** | `137,400` | `23,230` | **`-83.1%`** |
| **Combined `28`-Task Total** | **`28`** | **`56`** | **`28 / 28` (`100%`)** | **`28 / 28` (`100%`)** | **`364,727`** | **`61,218`** | **`-83.2%`** |

## 3. Large-Scale (`30`-File Daily & `100`-File Refactor) Stress Verification

| Workload Scale | Mode 1 (`Normal Mode` Inside Antigravity) | Mode 2 (`Manual Web-Relay` via `gemini.google.com`) | Verified Outcome |
|---|---|---|---|
| **Standard `30–40` File Feature / Refactor** | `harness-worker-agent` (`gemini-4-hydrogen-high`) scales read budget automatically to `slice_files + 16` (`46–56` reads) with uncapped edits & `--tests <Class>` | Packs all `30–40` editable files + `READ_ONLY_NEIGHBOR_SIGNATURES` + `R.drawable.*`/`R.font.*` inventory into **`1` single `.md` Context Pack**; Gemini Web returns compact `hunks` (`replace_all: true`) + surgical neighbor `hunks` + `<vector>` XML `CREATE` | **`100%` 1-Pass `APPLIED`** (`test_11`, binary `.png`/`.webp`/`.ttf` shielded from UTF-8 blocks) |
| **Massive `41–100+` File Multi-Module Refactor** | Clean Architecture DAG phases (`:core` `p1` -> `:app` `p2`) + scale-adaptive `Worker` cap (`up to 140` reads) & `Reviewer` cap (`up to 48` calls) + `[:250]` conflict scan | Auto-shards `100` files in Clean Architecture DAG order into `40 + 40 + 20` batches (`Batch 1/3 -> 2/3 -> 3/3`), supports `"status": "PARTIAL"` multi-part replies, accumulates `66` `:app` files in `staged-web-phases/p2.json`, and auto-copies each next batch on `web-apply` (`APPLIED_BATCH_NEXT_READY`) | **`100 / 100` Files Updated & Verified** (`test_12`, zero output truncation) |

## 4. Candid Engineering Decision Rule

1. **Keep `Mode 1 (Normal Mode)` for `T0–T2` slices (`1–15` files)**: `<4`-file edits execute inline on the warm Lead cache (`TRIVIAL_INLINE_LEAD`) in `~25s–30s`, and `4–15` file single-module tasks finish cleanly on `gemini-4-hydrogen-high` (`1.00x` pool weight) without manual browser switching.
2. **Use `Mode 2 (Web-Relay)` on `30–100+` file refactors, `COMPLEX` multi-module features (`BM-3`), `T5` sensitive surfaces (`BM-4`), and `2-Strike` bugs (`BM-5`)**: Offloads `100%` of heavy `Carbon` architectural synthesis and multi-file code edits to Gemini Web's separate Ultra pool — saving **`83.2%–86.3%` of Antigravity `3.00x` `Carbon` quota**, beating `2-Strike` retry loops by **`2.0x` on wall-clock speed**, and handling `30`-file single-pack and `100`-file auto-sharded DAG refactors without output truncation.
3. **100% Cross-Chat & Multi-Task Continuity (`DW-31..DW-35`)**: `execution-mode show|set` persists per-task or project-wide preferences with `SHA-256` tamper checks, `task bridge` transfers `staged-web-phases/p2..pN` and batch state cleanly across chats, and `CONFLICT` / all-secret scopes stay safely local.
