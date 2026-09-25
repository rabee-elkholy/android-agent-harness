# Certification benchmark: progress report

Status: **paused** after T3; T4 was stopped mid-run (restarted RED-first attempt, killed at the review stage). Handover to a new session. Protocol: [certification-plan.md](certification-plan.md). Previous round: [results-2026-09-25-round5.md](results-2026-09-25-round5.md).

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
| T4 rounding bug | stopped | First attempt fixed code before RED; router refused completion with `RED_EVIDENCE_MISSING` (D10 fix works); developer cancelled; restarted RED-first | - |
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

## Unresolved problems and recommended fixes

Fix these after the run, each with a failing regression test first and the complete selftest before push. Keep Antigravity's hook stdout, Review Protocol V2, `GEMINI.md`, `agents/hooks.json` and reviewer agents unchanged.

### C-D2 (high): multi-line commands denied with a misleading reason
- Where: `agents/scripts/mutation_guard.py` `_split_segments` splits on `\n` outside quotes, so `\`+newline continuations become separate "commands"; the first unknown segment triggers "not allowed while plan status is ..." or "No active task found".
- Fix: in `_split_segments`, treat backslash-newline outside quotes as whitespace (join the lines) before splitting; keep real newlines as separators. Add a test: `workflow.py draft ... \\\n --outcome "x"` is allowed exactly like the one-line form, and `revise` at AWAITING with continuations is allowed.
- Also: when a segment is denied, name the segment in the reason ("segment '--kind FEATURE' is not a command") so agents do not misdiagnose state.

### C-D3 (high): Claude cannot record an unchanged reviewer response
- Where: `pre_tool_safety.py` read-only boundary denies backticks, `|`, `<` anywhere in the command, even inside single quotes; agents may not write files outside the plan; `record_review.py --from-subagent` and `phase_review.py complete --response-file` do not read Claude subagent transcripts.
- Best fix (host-scoped, Antigravity untouched): let `record_review.py --from-subagent <role>=<path>` and `phase-review complete --response-file` accept a Claude subagent transcript (`.../tasks/<agent-id>.output`, JSONL): parse it, take the last assistant text, and ingest it unchanged. The agent then only passes a path, so no quoting problem. Restrict accepted paths to the Claude project transcript directory (`~/.claude/projects/...` or the `tasks/*.output` files of the current session), record the path and its sha256 in the evidence, and still mark independent execution as unverified (V1).
- Secondary: in the command guard, do not treat characters inside single-quoted arguments as shell operators (tokenize with `shlex` and only check unquoted tokens). Add tests for both.
- Update the Claude rules template to name the transcript path as the ingestion method.

### C-D4 (high): partial `revise` drops files and modules
- Where: `workflow.py` `revise` -> `_build_and_save_plan` rebuilds the plan only from given args.
- Fix: in `revise`, default every omitted field (`expected_files`, `expected_modules`, `expected_surfaces`, `test_strategy`, phases, architecture args) to the old plan's value; merge surfaces given by the O4 hint with the old ones. Test: revise with only `--expected-surfaces X` keeps files and modules. Also make the O4 hint print the full revise command (files, modules, surfaces).

### C-D5 (medium): unscoped plans accepted
- Where: `workflow.py` draft validation.
- Fix: for FEATURE/BUG/REFACTOR tasks that are not T0/micro, require at least one `--expected-files` entry (or fail with a message showing the discovered candidate files from the task context/receipt). Alternatively auto-fill `expected_files` from the discovery receipt's resolved paths and show them in `PLAN_SUMMARY`. Keep T0 and context-note actions exempt. Check the Antigravity daily tests that draft without files and adapt them only if the rule is gated to new plans.

### C-D6 (low): raw traceback in `phase-review complete`
- Fix: check `Path(response_file).is_file()` and fail with a usage error naming the expected input.

### Open observations
- D10b: CAPTURE_RED is advisory; in T4 the agent edited production code before RED and never asked the router after approval. Fix option: the write guard denies non-test source edits in a BUG task until RED evidence exists (tests stay writable), gated to BUG tasks with executable RED required.
- C1: `test -f` outside a task is denied; add `test`/`[ -f ]` to the read-only allowlist.
- C2: install prompt Phase 4/5 text describes Antigravity outputs; mention that other hosts get their own adapter files (keep the prompt under 4096 bytes).
- C6: agents re-type `PLAN_SUMMARY`; the Claude rule exists, consider having `approve` print the plan hash the developer approved.

## How to resume the certification run

The run's working copies were in the ephemeral session scratchpad and may be gone. To resume:
1. Provision the kit from commit 68db0bc (or from the commit that fixes the defects above, which starts a new run).
2. Clone Pocket Casts at `30ee012`, copy `local.properties` (`sdk.dir`), keep the Maven Central mirror init script in `~/.gradle/init.d/`.
3. Move `.agents/skills` to `.claude/skills` (replace the `.claude/skills` symlink) and commit, then install with Claude Code as host, tracker none, device verification disabled.
4. Run the tasks in [certification-plan.md](certification-plan.md) with a fresh session each; prompts: task text plus the two developer notes in the plan. Use `claude -p` with `--session-id`, `acceptEdits`, and an allowlist without permission bypass; disallow `git push` and `rm`.
5. Rules: record a problem as FAIL and continue; no fixes during the run.
