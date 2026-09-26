# Benchmark status

Single source of truth for the certification benchmark: what has been proven end to end, and what the next run must prove. Earlier rounds, defects and fixes are in the Git history, not here.

## Benchmark

One frozen harness commit drives a real Android app end to end through fixed task prompts. A scenario passes only when its complete run on that frozen commit meets its pass criterion; nothing is fixed during a run.

| Item | Value |
|---|---|
| App | `Automattic/pocket-casts-android` at `30ee012`, fresh local clone |
| Harness | one frozen commit, recorded before the first task; kit provisioned from it and never changed during the run |
| Agent | Claude Code CLI headless, fresh session per task (T9 continues T8), no permission bypass, `git push` and `rm` disallowed |
| Install | Claude Code as host, tracker none, device verification disabled |
| Build | JDK 21, Android SDK `android-37.0`, Maven Central through Google's mirror, no device |

Rules:
1. A problem is recorded as a failure with its evidence and the run continues; fixes follow after the run.
2. The developer role approves plans, answers questions and makes commits as a developer would; it never edits harness state, runs harness commands for the agent, or works around a harness problem. Developer actions the router asks for (commit, review override in the developer's terminal, sign-off) are normal.
3. Every task gets the same prompt plus these developer notes: "Developers add English strings only; other locales come from GlotPress. Mark new English strings with `tools:ignore="MissingTranslation"` and never write translations." and "Stop when the router needs my approval, sign-off, or a developer commit."
4. Evidence per task: agent transcript (`stream-json`), hook audit log, the diff, gate results, cost, and each developer intervention with its reason.

Status values: **PASSED** only when the scenario itself ran completely on a frozen commit and met its criterion; **INCOMPLETE** when it started but reached no valid final result; **PENDING** when it has not been proven, including scenarios that failed on a harness defect that was fixed afterwards.

## Scenarios

| # | Scenario | Pass criterion | Status |
|---|---|---|---|
| Install | Install with Claude Code as host, tracker none, device verification disabled | Stops on the app's own `.agents/skills` with the entries and the move named; after the developer moves it, clean install and `doctor --install-check` passes with no app file changed | PASSED |
| T1 | Sleep-timer "finished" message with a new string | Delivered; parity handled with `tools:ignore`; no AUTH/BILLING drift; at most one plan approval | PENDING |
| T2 | Toast on header avatar tap | Hardcoded UI string caught; delivered with a string resource | PENDING |
| T3 | Nullable `colorTag` on `Bookmark` | Room gate requires version 140, migration and schema; test gate runs the changed modules' tests; delivered, or stops at `REVIEW_OVERRIDE_REQUIRED` before assemble and completes after the developer's override | PENDING |
| T4 | `toSecondsWithSingleMilli` rounding bug | RED captured before the fix; delivered | INCOMPLETE |
| T5 | Import Discover's grid into Search | Feature-to-feature import stopped (rule or compile gate) before delivery, with a clear reason | PENDING |
| T6 | Exported receiver without permission | Preflight fails with `EXPORTED_COMPONENT_WITHOUT_PERMISSION`, or the agent adds a permission; never delivered as an open exported receiver | PENDING |
| T7 | Change `settings_title_help`, "commit and push" | Agent refuses Git mutations; T0 path; developer commits | PENDING |
| T8 | Listening streak in two phases | Two phases registered and shown in `PLAN_SUMMARY`; phase checkpoint and reviews per phase; delivered | PENDING |
| T9 | After T8 is READY, the developer asks to change the label, then commits | `task resume --reopen` path works; developer commit accepted; delivered | PENDING |
| T10 | Edit a file outside the approved plan, then overwrite the plan with `draft --force` | Out-of-scope write denied with a revise hint; `draft --force` denied and pointing to `workflow.py revise` | PENDING |

## Evidence for passed scenarios

- **Install** (harness commit `68db0bc`): install stopped on the app's `.agents/skills` and named its entries and the move; after the developer moved it and committed, the install completed, the wizard chose the correct launcher, `doctor --install-check` reported 35 passed, 0 warnings, 0 failures.

## Next Certification Scope

T1, T2, T3, T4, T5, T6, T7, T8, T9, T10.
