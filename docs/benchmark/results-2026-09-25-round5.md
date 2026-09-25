# Round 5 results: Claude Code on Pocket Casts

Date: 2026-09-25. Plan: [round5-plan.md](round5-plan.md). Raw log: [round5-findings-log.md](round5-findings-log.md).

## Setup

| Item | Value |
|---|---|
| App | `Automattic/pocket-casts-android` at `30ee012`: Kotlin only, 47 Gradle modules, Compose and XML, Hilt, Room (database version 139), version-catalog plugin aliases |
| Harness | `v1.1.0`, then this branch's fixes applied through `harness_cli.py update` between tasks |
| Agent under test | Claude Code CLI headless, `claude-sonnet-5`, no permission bypass, `git push` and `rm` disallowed |
| Developer role | Orchestrating session: approvals, scope decisions, commits |
| Environment | Cloud container; Maven Central reached through Google's mirror (HTTP 429 otherwise); no device |

## Outcome

| Task | Result | Agent cost |
|---|---|---|
| Install (Claude Code adapter) | Clean install, `doctor --install-check` 35/0/0; after moving the app's own `.agents/skills` (D2) | $2.45 |
| T1 copy change (Toast string) | DELIVERED after 5 attempts; 4 were cancelled to apply harness fixes | $11.49 |
| T2 avatar Toast | DELIVERED; hardcoded-string gate and two review rounds | $5.26 |
| T3 Room column | Room gate and reviews worked; stopped at completion (D13), then stale (D14); not delivered | $10.53 |
| T4 to T10 | Not run in this round | - |

Total agent spend: $29.73.

## Where the harness added value

- Pre-planning: the agent found that the requested message already existed in three code paths and asked for scope before planning.
- Hooks on Claude Code: raw Gradle, pipes, work outside a task and a Claude claim of `--host antigravity` were denied.
- Hardcoded-string gate caught inline Toast text; the agent refused to evade it.
- Room gate refused an entity change without version bump or migration.
- Reviews found real defects the implementing agent missed:
  - T1: the updated test stub asserted nothing, so a wrong string key would pass.
  - T2: a nested clickable swallowed the header click; the fix then produced two TalkBack targets with the same label.
  - T3: the new migration was missing from the test helper's list, and no dedicated migration test existed.
- Fail-closed gates: the test gate refused to attribute an environment failure; the agent refused to self-certify review proof.

## Harness defects

| Id | Severity | Defect | Status |
|---|---|---|---|
| D3 | critical | The hook required `--host antigravity` for `prepare-verification` on every host, so no Claude Code task could reach verification, while a Claude claim of the Antigravity host was allowed | fixed |
| D9 | critical | Claude runs are review protocol V1 (footer required) but installed reviewers must end with a V2 JSON block, so no Claude review could be recorded | fixed |
| D6 | critical | Module discovery matched literal plugin ids only; with `alias(libs.plugins.android.library)` it found 0 of 47 modules | fixed |
| D4 | high | `<string>` and `<plurals>` sharing a name were reported as duplicates; preflight failed on the untouched baseline (90 errors) | fixed |
| D5 | high | Drift remediation printed the root module as an empty entry; revise dropped it and the same drift repeated forever | fixed |
| D8 | high | A change touching two modules fell back to `:app` tests; the gate passed while the changed test never ran | open (needs per-module baselines) |
| D10 | high | A BUG task without RED reached COMPLETE_TASK in the router while the verifier refused | fixed (router) |
| D11 | high | Editing an existing file in a scope shared by six architecture families was refused, with no working remediation | fixed |
| D12 | high | A `String` property resolved to `extensions/String.kt` (MessageDigest) and classified the change CRYPTO / T5 | fixed |
| D13 | high | On hosts without trusted transcripts, HIGH changes complete only through a developer-terminal review override and sensitive changes cannot be delivered; not documented or routed | open (design/docs) |
| D14 | high | The java toolchain identity included `Picked up JAVA_TOOL_OPTIONS` with a proxy port; a reconnect made a finished verification stale | fixed |
| D1 | medium | The wizard recommended an `androidTest` activity as launcher and listed disabled aliases | fixed |
| D2 | high | Install refuses any existing `.agents` directory; the harness owns `.agents` wholesale, so repos using `.agents/skills` cannot install | open (design) |
| D7 | low | `--expected-surfaces` accepted file paths; plans then drifted and needed a second approval | fixed (validation, modules of planned files declared) |

Other observations: the install prompt hardcodes Antigravity (F1); the Claude sandbox cannot write the kit cache (F2); Gradle gates exceed Claude's 2-minute default command timeout (F9); plan-time reviewer routing is unstable until the diff-based reclassification (O1); parity requires every locale unless `tools:ignore` is used, and setup never asks about an external translation service (O2).

## Discovery hardening (from an external review of v1.1.0)

| Point | Result |
|---|---|
| Targeted anchors granted whole-module search roots | Fixed: only a module query grants a module root; GRAPH-008B/C test the computed-roots path |
| `latest-discovery.json` outlived its graph and task | Fixed: freshness compares a graph-fingerprint sidecar; deliver and cancel clear the latest receipt |
| Reminder wording looser than enforcement | Fixed |
| Router heuristics (`:feature:home` as multi-module, substring resource checks) | Fixed |
| `view_file` unrestricted | Not changed: read-only; recommend allowing user-supplied and discovered paths and flagging repeated out-of-scope reads |

## Antigravity stability

Every fix keeps Antigravity's behaviour unless the change is a correctness fix that also applies to it (D4, D5, D6, D11, D12, D14, discovery scope). Hook stdout, Review Protocol V2 and the Antigravity adapters were not changed. Each fix landed only after the complete selftest passed, including the Antigravity suites. Two attempted changes were reverted because they changed established behaviour: a `prepare-verification` RED guard (121 existing tests) and widening declared surfaces from file paths (3 router tests).

## Recommendations

1. Per-module unit-test baselines, then target every changed module in the test gate (D8).
2. Document and route the V1-host limits for HIGH and sensitive changes (D13).
3. Decide ownership of `.agents` for repos that already use `.agents/skills` (D2).
4. Add a Claude Code install prompt path and tell agents to pass long command timeouts for gates (F1, F9).
5. Run T4 to T10 and the "agent alone" arm on the same app before claiming Claude Code support.
