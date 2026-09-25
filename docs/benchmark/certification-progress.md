# Certification benchmark: progress report

Status: **in progress** (T4 running). Protocol: [certification-plan.md](certification-plan.md). Previous round: [results-2026-09-25-round5.md](results-2026-09-25-round5.md).

## Part 1: done before the run (closing round 5 issues)

Every item has a regression test. The complete selftest (22/22) and `validate_release.py` passed before push. Hook stdout, Review Protocol V2, `GEMINI.md`, `agents/hooks.json` and the Antigravity reviewer agents are unchanged.

| Id | Fix | Commit |
|---|---|---|
| D13 | V1 hosts: router returns `REVIEW_OVERRIDE_REQUIRED` (HIGH/CRITICAL) or `SENSITIVE_REVIEW_PROOF_UNAVAILABLE` (sensitive surfaces) before assemble; limits in `docs/tool-support.md` | f4b230d |
| D8 | New installs (`UNIT_TEST_SCOPE = "changed_modules"`) run each changed module's tests, one Gradle run per module; existing installs unchanged | 5f6cd22 |
| D2, F1, F9, O2, O3 | App-owned `.agents` refusal lists entries and the move; install prompt host not fixed to Antigravity; Claude rules (verbatim plan summary, foreground Gradle with max timeout, never run the review override); parity message names `translatable`/`tools:ignore`/`l10n-todo`; `run_device` says when device verification is disabled | 7311a84 |
| O4, O5 | Drift denial names every missing surface of the planned files; preflight fails on a newly exported receiver/service/provider without a permission unless `tools:ignore` records the decision | 8e291b2 |
| O6, discovery | `draft`/`revise` print `PLAN_SUMMARY`; a discovery receipt from before the conversation grants no scope; out-of-scope `view_file` code reads audited as `READ_OUTSIDE_SCOPE` | 8ca0056 |
| Protocol | Certification protocol | 68db0bc |

Frozen harness commit for the run: **68db0bc**, kit at `~/.android-harness/kit-cert`.

## Part 2: certification run so far

Setup: clean local clone of Pocket Casts at `30ee012`, Claude Code headless (`claude-sonnet-5`), fresh session per task, no fixes during the run.

| Task | Result | Notes | Cost |
|---|---|---|---|
| Install | PASS | Stopped on the app's `.agents/skills` and named the entries (D2 works); developer moved them to `.claude/skills` (it was a symlink) and committed; wizard picked the right launcher (D1); doctor 35/0/0; `UNIT_TEST_SCOPE = changed_modules` | $1.90 |
| T1 sleep-timer string | FAIL | Scope asked first. Unscoped first draft (C-D5), C-D2, reviews found the test stub gap again, then stopped at review ingestion (C-D3) | ~$6.8 |
| T2 avatar toast | FAIL (delivered) | Regression reviewer caught a real Automotive break before delivery; O4 hint worked; but C-D4 lost plan scope and reviews recorded only after the agent edited them (C-D3). Developer commit, delivered | ~$5.3 |
| T3 Room column | FAIL | Version 140, migration and `140.json` done in phase 1 (Room gate not exercised); blocked at phase review (C-D3); C-D2, C-D5, C-D6 | ~$4.4 |
| T4 rounding bug | running | First attempt fixed code before RED; router refused completion with `RED_EVIDENCE_MISSING` (D10 fix works); developer cancelled; restarted RED-first | - |
| T5 to T10 | not started | | |

## New defects found (recorded, not fixed during the run)

| Id | Severity | Defect |
|---|---|---|
| C-D2 | high | A command written with backslash line continuations is denied, with a misleading reason ("not allowed while plan status is AWAITING_DEVELOPER_APPROVAL", or "No active task found"); the same command on one line is allowed. Agents conclude that `revise` is impossible and ask for a developer cancel. (C-D1 was the same defect.) |
| C-D3 | high | Claude Code cannot record an unchanged reviewer response. `--response-text` is denied for any backtick, `|` or `<`, even in single quotes; files outside the repo, in `.agents/state`, or outside the plan cannot be written; a Claude subagent transcript (JSONL) is not accepted. Same for `phase-review complete --response-file`. Agents either stop or edit the responses. |
| C-D4 | high | `revise` with only `--expected-surfaces` drops the plan's files and modules, which disables the write-scope guard; the O4 hint suggests exactly that partial command |
| C-D5 | medium | 4 of 4 first drafts registered no files, modules or surfaces; the harness accepts an unscoped plan for a task with known targets |
| C-D6 | low | `phase-review complete --response-file <text>` raises a raw `FileNotFoundError` traceback |

Observations: the hook denies a read-only `test -f` outside a task (C1); the install prompt's Phase 4/5 text describes Antigravity outputs (C2); an agent re-typed the plan summary instead of showing it verbatim (C6); CAPTURE_RED is still advisory and the agent did not ask the router after approval (D10b).

## Verified working in the run

D1, D2 (message), D8 config, D10 (router), O2 hint, O4 hint, O6 plan summary (it is how the developer noticed unscoped plans), D15 edit interception, Git authority (no agent commits), fabricated review JSON rejected for package-hash mismatch.

## Remaining

1. Finish T4 (RED capture, gates, reviews, delivery).
2. Run T5 (feature-to-feature import), T6 (exported receiver, O5 gate), T7 (commit and push), T8 (two phases), T9 (change after READY, then commit), T10 (out-of-scope edit and `draft --force`).
3. Write the certification report with per-task verdicts, costs and the defect list.
4. After the run, fix C-D2, C-D3, C-D4, C-D5, C-D6 (each with a regression test and the complete selftest), keeping Antigravity unchanged.
5. Later: release (version bump, PR to `main`, CI, tag) once the fixes are validated.
