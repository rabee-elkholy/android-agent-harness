# Android Agent Harness — Project Constitution

> **Repository-maintenance constitution**
>
> This file governs development of the **Android Agent Harness repository itself**.
> It is not the installed client-project runtime kernel.
>
> Product identity: **Stricter proof, not heavier workflow.**

---

## 1. Purpose

Android Agent Harness is an approval-first engineering control layer for AI-assisted Android development.

It exists to make important engineering guarantees live **outside model memory and prompt obedience** where practical:

- bounded, project-aware discovery;
- explicit plan authority before mutation;
- deterministic scope/risk classification;
- proportional tests and Android-specific gates;
- independent specialist review where policy requires it;
- immutable, snapshot-bound evidence;
- developer-owned Git/device/release decisions;
- durable repo-local project knowledge.

The project must increase trust **without turning normal development into a heavyweight ceremony**.

When choosing between two designs of similar safety and correctness, prefer the one with:

1. fewer states;
2. fewer duplicate sources of truth;
3. less host-specific branching in the core;
4. less developer interruption;
5. more deterministic proof.

---

## 2. Authority

The developer remains the ultimate authority.

This constitution is a protection against accidental architectural drift, not a veto over the maintainer.

### 2.1 Conflict procedure

If a requested change conflicts with a protected invariant in this file, the AI maintainer MUST NOT:

- silently implement the conflicting behavior;
- silently reinterpret the request;
- weaken the invariant only to make a test pass.

Instead it must surface:

```text
CONSTITUTION_CONFLICT
Invariant: <exact invariant>
Requested change: <what conflicts>
Impact: <what safety/architecture property would change>
Safe alternative: <closest compatible option, if one exists>
```

Then request **explicit informed confirmation** before changing the architecture.

If the developer explicitly confirms the architectural override:

- the developer's decision wins;
- update this Constitution and/or the relevant ADR in the same change;
- update deterministic tests to encode the new contract;
- update public documentation if behavior is user-visible;
- do not leave code, tests, and architecture documentation contradictory.

Ordinary bug fixes, implementation details, refactors that preserve these invariants, and already-approved in-scope work do **not** require an extra confirmation.

---

## 3. Protected Product Invariants

### 3.1 Approval-first

- Analysis and read-only discovery do not require task approval.
- Repository/client-project mutation requires an approved task plan.
- Silence is never approval.
- One explicit initial approval covers the approved task and its declared semantic phases.
- Normal phase progression never asks for approval again.
- In-scope bug fixes after review findings resume implementation under the same approved scope.
- Material scope expansion requires revised approval.

Do not add repeated approval gates merely to feel safer.

### 3.2 Human Git Authority

For installed client projects, the model does not autonomously mutate Git history or branch/worktree state.

Protected developer-owned operations include:

- add/stage;
- commit/amend;
- push;
- tag/release;
- merge;
- rebase;
- stash;
- reset;
- checkout/switch;
- worktree add/remove.

The harness may inspect Git, generate commit guidance, request a developer commit, freeze handoff state, and validate resulting lineage.

Development of this harness repository itself may use Git actions only when the maintainer explicitly authorizes them for that maintenance task. Never change the product's client-project Git policy merely because repository maintenance was explicitly authorized.

### 3.3 Router is completion authority

Model confidence is not task completion.

```text
MODEL SAYS "DONE" != TASK IS DONE
```

The canonical task router/state must establish terminal completion.

Agents must continue to resolve the canonical next action until one of:

- terminal DONE/DELIVERED state;
- a real `DEVELOPER_ACTION`;
- a deterministic ENV/PROTOCOL/STALE blocker that requires intervention.

Known failing commands, fake WAIT states, and orphan substates are architecture defects.

### 3.4 Six-tier policy is the routing authority

The 6-tier risk system and central review policy are the sole runtime authority for:

- risk tier;
- deterministic gates;
- reviewer roster;
- device requirement;
- skill routing.

Do not create a second hidden reviewer router or independent risk vocabulary in phase code, host adapters, or prompts.

Canonical tiers:

```text
T0_TRIVIAL
T1_LOW_RISK
T2_FEATURE
T3_SUBSYSTEM
T4_DATA_DEVICE
T5_CRITICAL
```

### 3.5 Evidence is snapshot-bound

Verification evidence must be tied to the actual task/run/change identity.

Stale, malformed, incomplete, mismatched, or wrong-run evidence cannot approve delivery.

Important identities include:

- task/plan identity;
- repository/worktree identity;
- delivery snapshot;
- task change set;
- review package;
- artifact set;
- device/install/launch evidence;
- accepted Git checkpoint lineage.

Do not convert evidence failures into warnings merely to keep the workflow moving.

### 3.6 Antigravity-first, not Antigravity-hardcoded

Google Antigravity is the **primary production host** and may receive the strongest native integration.

The core workflow must still preserve **portable correctness** on supported non-Antigravity hosts.

Rules:

- Antigravity-specific transcript paths, hook schemas, slash commands, custom-agent semantics, and V2 host behavior must stay behind host capability boundaries.
- Generic lifecycle code must not hardcode `antigravity`.
- Non-Antigravity hosts must never pretend to possess trusted Antigravity transcript proof.
- Enforcement strength must be reported honestly (`HARD_ENFORCED`, `RULE_ENFORCED`, or `UNSUPPORTED`).
- Stronger Antigravity enforcement must not make Claude/Codex/generic paths logically impossible.

Host parity is not required. **Correctness and truthful degradation are required.**

### 3.7 Reviewer model inheritance on Antigravity

For Antigravity Review Protocol V2:

```text
model_policy = INHERIT_PARENT_BY_OMISSION
```

Do not pass:

- `model`;
- `Model`;
- `"inherit"` as a fake model value;
- guessed reasoning fields.

Reasoning escalation is allowed only through a trusted host-native capability whose real supported argument/schema was detected.

Do not create a cross-provider model-routing subsystem.

### 3.8 Review proof cannot be self-certified

For Review V2 and scoped Phase Review V2:

- the lead implementation agent cannot manufacture reviewer PASS;
- reviewer dispatch must be recorded before trusted completion;
- reviewer identity, package identity, run identity, and execution identity must bind;
- protocol correction stays in the same reviewer execution when possible;
- environment failure is not PASS;
- stale review result is not PASS.

### 3.9 One live task per worktree

- One live harness task per Git worktree.
- Urgent parallel work uses a separate developer-created worktree.
- A validated WIP checkpoint may extend Task A's accepted lineage without cancelling Task A.
- Arbitrary unregistered commits, merges, or rebases into a live task remain lineage violations.
- Returning to Task A resumes from persisted harness state, not chat memory.

### 3.10 Semantic phases, not mechanical chunking

Large tasks may use coherent phases.

- Phases are semantic engineering boundaries.
- A line-count threshold can trigger review, but must not mechanically split architecture.
- Small/trivial phases may skip AI review.
- Substantial/risk-sensitive phases may receive 1–2 policy-derived reviewers.
- Final integration review remains authoritative.

### 3.11 Persistent project knowledge is repo-local

For installed Android projects, persistent engineering knowledge is stored in repository-local harness context.

Truth hierarchy:

```text
Current source evidence
    ↓
Generated project facts
    ↓
Explicit developer notes / scoped developer instructions
    ↓
Generic Android guidance
```

Never claim the chat provider itself remembers previous conversations.

A developer note or instruction cannot silently overwrite contradictory deterministic source truth.

### 3.12 Runtime stays dependency-light

Installed runtime Python must remain standard-library-only unless the maintainer explicitly approves changing this architectural constraint.

Development/test tooling may use separate tooling only when it does not become an installed runtime dependency.

### 3.13 Installed engine is not client task source

During normal Android application work:

- `.agents/**` is managed engine/state, not application implementation scope;
- unexpected harness failure is reported/diagnosed, not silently patched by the client-task agent;
- source-app bugs must not be “fixed” by weakening harness gates.

---

## 4. Design Principles

### 4.1 Prefer one source of truth

Examples:

- one risk/reviewer policy;
- one strict V2 structured-result parser;
- one host capability resolver;
- one task lineage validator;
- one phase ledger loader/validator;
- one public command contract.

If two modules independently answer the same policy question, treat that as design debt.

### 4.2 Fail closed at proof boundaries, degrade gracefully at convenience boundaries

Fail closed for:

- approval identity;
- scope;
- reviewer proof;
- stale verification;
- evidence binding;
- sensitive changes;
- lineage;
- destructive operations.

Best-effort/warning is acceptable for non-authoritative convenience such as optional advisory graph enrichment, provided correctness does not depend on it.

### 4.3 Do not add a state machine for a prompting convenience

Host-native accelerators such as Antigravity `/goal` and `/grill-me` must not become kernel states.

Correctness must remain identical without them.

### 4.4 No fake host capabilities

Never invent:

- transcript readers;
- reasoning arguments;
- approval tokens;
- hook enforcement;
- conversation IDs;
- model inheritance controls.

A capability exists only when the host integration can prove it.

### 4.5 Keep developer ceremony proportional

Do not require:

- repeated Proceed/approval at each phase;
- reviewer launch approvals;
- terminal commands from the developer when the model can safely run a harness command;
- manual bookkeeping already derivable from state.

Human interaction is reserved for real authority/decision boundaries.

---

## 5. Test-Driven Maintenance Contract

Tests are part of the architecture.

### 5.1 Bug fixes

When a deterministic seam exists:

1. reproduce the bug;
2. add the smallest meaningful RED regression test;
3. implement the minimal fix;
4. make the test GREEN;
5. run neighboring focused suites;
6. run the canonical suite.

Do not add a test that only checks an implementation detail if the user-visible contract can be tested.

### 5.2 New behavior

New behavior must arrive with contract tests in the same change.

For state-machine/router changes, tests must exercise the real public path, not only direct private-function calls.

For host hooks, tests should feed actual hook-shaped payloads.

For review proof, tests should not bypass dispatch/transcript requirements by directly writing PASS state unless the test is explicitly testing a private pure helper.

### 5.3 Stale tests

If a test encodes an obsolete contract after an intentional architecture change:

- update the test;
- do not weaken correct production behavior to satisfy it;
- record why the old expectation is obsolete.

Conversely, never label a failing test “stale” merely because fixing production code is inconvenient.

### 5.4 Mandatory validation before claiming repository work complete

At minimum:

```bash
python harness_cli.py selftest
python -m compileall -q harness_cli.py agents/scripts
python scripts_dev/validate_release.py
```

Then inspect GitHub Actions for the exact final commit across supported OS/Python jobs.

A required pending, cancelled, or failing job is not “all green”.

### 5.5 CI matrix protection

Do not narrow Windows/macOS/Python coverage merely to make CI faster unless explicitly approved as an architecture/quality decision.

Cross-platform behavior is a product property.

---

## 6. Change Discipline

Before changing a protected subsystem, identify:

- current source of truth;
- invariant being changed/preserved;
- affected tests;
- affected host adapters;
- migration/backward-compat implications;
- docs/ADR implications.

Protected subsystems include:

- approval/plan authority;
- mutation guard;
- review policy;
- Review Protocol V2;
- phase review;
- evidence store;
- verification freshness;
- Git/task lineage;
- installer/update/repair;
- host enforcement;
- device sign-off;
- persistent project knowledge.

For changes inside these areas, prefer surgical edits over framework creation.

---

## 7. Host Strategy

### 7.1 Google Antigravity

Primary production host.

Use native capabilities where proven:

- tool hooks;
- custom specialist agents;
- exact Review V2 dispatch;
- trusted transcript-backed completion;
- reactive completion;
- same-model inheritance by omission;
- `/grill-me` and `/goal` as optional workflow accelerators.

### 7.2 Claude Code

Supported with the strongest real hook/rule integration the current adapter can prove.

Do not describe Antigravity-only trusted transcript semantics as Claude behavior.

### 7.3 Codex

Use root `AGENTS.md` and supported instruction mechanisms for persistent repository guidance.

Deterministic harness gates remain authoritative even when mutation interception is rule-enforced rather than native-hard-enforced.

### 7.4 Other hosts

Prefer truthful reduced enforcement over fake parity.

---

## 8. Antigravity Native Accelerators

These improve behavior but are not correctness dependencies.

### `/grill-me`

Recommended before planning when material ambiguity exists, especially:

- new subsystem;
- architecture choice;
- migration;
- cross-module behavior;
- sensitive business behavior;
- substantial error/backward-compat decisions.

Do not use it for every tiny bug.

Resolved interview decisions should feed the task plan. Do not ask the same material question again unless new evidence reopens it.

A durable rule is recorded as Project Note/Developer Instruction only when the developer clearly states or approves it as durable.

### `/goal`

Recommended after task-plan approval for non-trivial Antigravity work.

Meaning:

```text
/goal = execution persistence
Harness router = execution/completion authority
```

The agent continues the router loop until terminal completion or a real human/blocker boundary.

`/goal` never:

- grants approval;
- overrides scope;
- bypasses device sign-off;
- performs developer-owned Git;
- bypasses review;
- changes reviewer model selection;
- turns ENV_BLOCKED into success.

The harness must remain fully correct when `/goal` is not used.

---

## 9. Documentation Truth

Public docs must match runtime behavior.

If code and README disagree, do not solve it by guessing which one is intended.

Determine the current approved architecture, repair the inconsistency, and add a regression/doc assertion when practical.

Avoid stale claims such as:

- obsolete reviewer counts;
- outdated file paths;
- host capabilities that no longer exist;
- “all green” when CI is not green;
- “cross-chat memory” phrased as provider memory.

---

## 10. Release Guard

Do not tag, release, or publish merely because code compiles.

Release requires:

- canonical deterministic suites green;
- cross-platform CI green;
- release metadata/checksum validation green;
- no known P0/P1 blocker in the candidate;
- explicit maintainer publication decision.

Never rewrite an existing release tag.

---

## 11. Maintainer Completion Standard

Repository maintenance is complete only when:

- requested behavior is implemented;
- protected invariants still hold;
- focused RED/GREEN tests pass;
- canonical selftest passes;
- compileall passes;
- release validation passes;
- exact-head CI is green;
- docs/host adapters agree;
- no known reachable router state is orphaned;
- no known proof boundary fails open.

Do not claim “no possible edge cases”.

The correct statement is that all identified and tested risk classes are covered, with remaining limitations stated explicitly.

---

## 12. Fast Checklist for Any AI Maintainer

Before editing:

```text
[ ] Read this Constitution.
[ ] Read AGENTS.md.
[ ] Inspect relevant ADR/current architecture.
[ ] Identify source of truth.
[ ] Check whether request conflicts with a protected invariant.
[ ] If conflict: show CONSTITUTION_CONFLICT and obtain explicit informed confirmation.
```

Before finishing:

```text
[ ] New/changed behavior has regression tests.
[ ] No production weakening for stale tests.
[ ] No duplicate policy/state authority introduced.
[ ] Non-Antigravity path still degrades truthfully.
[ ] python harness_cli.py selftest passes.
[ ] compileall passes.
[ ] release validation passes.
[ ] Exact-head CI passes.
[ ] Docs and code agree.
```

**Protect the identity: stricter proof, not heavier workflow.**
