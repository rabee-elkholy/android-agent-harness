# Certification report: targeted re-run on harness 2609344

Round date: 2026-09-26/27. Scope: T3 → T8 → T9 → T10. These are the scenarios [certification-report-v1.1.2.md](certification-report-v1.1.2.md) left unproven, re-run after the N1–N8/N10 fixes. The conditions match that round: cloud container, the same Pocket Casts clone and prompts, `claude-sonnet-5` at medium effort for every turn, headless Claude Code, and no fixes during the run.

| Item | Value |
|---|---|
| Harness | `2609344`, frozen for the round (CI 12/12 green before the first scenario) |
| App baseline | `22a75e510` = Pocket Casts `30ee012` + the developer's skills move + harness `2609344` installed with round 1's answers; `doctor --install-check` 35 PASS, 0 WARN, 0 FAIL; unit-test baseline 0 pre-existing failures |
| Model / effort | `claude-sonnet-5` / medium (verified per turn from the transcripts) |

## Results

| # | Result | Cost | Wall time | Turns | Developer interventions |
|---|---|---|---|---|---|
| T3 | **FAILED** | $2.56 | 11 m 27 s | 4 | 2 approvals; the review override run in the developer terminal (failed) |
| T8 | **FAILED** | $20.04 | 48 m 6 s | 10 | design answers, 9 approvals, 2 environment notes |
| T9 | **NOT RUN** (PENDING) | $0 | 0 | 0 | none (T8 never reached READY) |
| T10 | **INCOMPLETE** | $0.34 | 1 m 36 s | 3 | approval with the out-of-scope request, one insistence |
| **Total** | 0 of 4 passed | **$22.94** | **61 m 9 s** | 17 | |

- **T3.** The Room gate (version 140, migration, schema) and the changed-module test gate passed. A single-phase checkpoint passed, both reviewers passed and were recorded, and the router stopped at `REVIEW_OVERRIDE_REQUIRED` before assemble, as the criterion expects. The developer's `record_review.py --override-reviews --source developer_terminal` then failed with `append-only artifact already exists: reviews.json` (N11), and the task cannot complete.
- **T8.** All nine phase files were in the plan scope. Both phases were checkpointed, phase-reviewed and finalized, and the resource-only `localization` module no longer blocked a checkpoint. Preflight, unit tests, `:app:assembleDebug` and four final reviewers passed; a real HIGH race condition was found and fixed on the way. The router then returned `COMPLETE_TASK`, but `complete` refused: `PLAN_APPROVAL_REQUIRED: mandatory skill selection drifted from the approved plan: compose-inspector` (N12). Each revision after a finalized phase reset phase progress (N13), leaving a stale next-phase baseline (N14). That produced nine approvals, six of them caused by harness state.
- **T9.** Not run: it needs T8 at READY.
- **T10.** The one-line edit to an existing string passed parity and reached READY_FOR_DELIVERY. The agent refused the out-of-scope edit and `draft --force` itself, so the harness denials were not reached, the same outcome as round 1.

## Did the N-fixes remove the round-1 causes?

| Round-1 cause | Fix | Seen in this round |
|---|---|---|
| T3: out-of-order phase checkpoint, then a stale loop (N1) | active-phase check; empty later phase | Held: T8's early p2 checkpoint was refused with "active phase is p1". T3 used one phase; no stale loop |
| T3/T6: Claude transcripts refused for HIGH changes (N8) | record as unverified | Held: T3 reached `REVIEW_OVERRIDE_REQUIRED`. Exposed N11 in the next step |
| T8: phase files missing from the scope (N2) | phase files become the plan files | Held for files; modules and surfaces still come from the task context |
| T8: zero-test failure for resource-only module (N3) | skip resource-only modules without tests | Held |
| T8: revise drops a reviewed phase (N4) | check proof against the old plan | **Partly**: it holds when the next phase has no edits; with edits the proof still reads stale (N13) |
| T10: parity on pre-existing gaps and exempt keys (N5, N6) | HEAD-aware parity, exempt keys | Held: T10's in-scope change reached READY |
| T3/T5: quoted `|`, `>` denied (N10) | double-quoted text is text on Claude | Held: no such denial in this round |

## New harness issues (not fixed; frozen run)

| # | Scenario | Issue |
|---|---|---|
| N11 | T3 | `--override-reviews` writes the append-only `reviews` artifact that already exists once reviews are recorded, so the developer override always fails after `REVIEW_OVERRIDE_REQUIRED` |
| N12 | T8 | Verification selects skills (`compose-inspector` for COMPOSE_UI) that the approved plan does not list; `complete` refuses with `PLAN_APPROVAL_REQUIRED` while the router says `COMPLETE_TASK` |
| N13 | T8 | Revising after a finalized phase resets progress when a later phase has edits: freshness re-derives the finalized phase's delta from the live tree (`phase delta SHA-256 changed`) |
| N14 | T8 | After that reset, the stale next-phase `baseline.json` makes `begin-next-phase` fail (`next phase baseline differs from the current delivery snapshot`) |
| N2 residual | T8 | With `--phases`, `Modules:` and `Surfaces:` still come from the task context (one module; AUTH and BILLING from `PlaybackManager`) |

Environment during the run:
- An account usage limit interrupted T8. The developer resumed with "continue".
- In headless mode a background checkpoint stopped when the turn ended. The developer asked for a foreground run.

## Evidence

[evidence/cert-2026-09-27-2609344.tar.xz](evidence/cert-2026-09-27-2609344.tar.xz) holds, per scenario, the transcripts, prompts, hook audit lines, the final diff and router output, task state and `RESULT.md`, plus the install log, doctor output and environment notes.
