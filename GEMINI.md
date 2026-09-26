<!-- managed-by: android-harness-kit -->
# android-harness-kit — Gemini CLI / Antigravity

Before changing this repository, read `PROJECT_CONSTITUTION.md`, then follow `AGENTS.md` and `agents/rules/harness-rules.md`.

- Python: `python`
- Assemble: `python .agents/harness.py assemble`
- Harness Execution Boundary: Installed harness engine source under `.agents/scripts/**` is an implementation detail. Execute documented commands directly; do not inspect or recursively read harness Python implementation before execution.
- Device: Physical device or emulator. Automatically resolved by `run_device.py`. Prefer a physical device when both are connected. Never hardcode a serial.
- Discovery: Graph-backed. Exact code target -> `python .agents/harness.py task-context --file <path> --json` or `--symbol <name>`. Feature/unknown target or cross-module refactor -> `python .agents/harness.py graph --feature <name> --json` (or `--find <symbol>`) first, then Task Context on resolved target. Search is never the initial code discovery anchor; after discovery, search only within discovered scope; expand scope via Graph, not grep cascades.
- Consultation & Edge Case Discussion Before Planning: If the user's prompt includes an engineering inquiry, trade-off question, architectural validation, asks to study/research missing scenarios or surface edge cases before starting (e.g. "ادرس الموضوع كويس", "دور ع edge cases قبل ما تبدأ", "find missing scenarios/edge cases before starting"), or asks for confirmation before starting (e.g. "أكد عليا", "is this logic sound or best-practice?", "should we do A or B?"), the agent MUST fully discuss, analyze, and present the findings directly in plain chat BEFORE invoking `workflow.py draft` or drafting `implementation_plan.md`. When asked to surface edge cases or examine missing scenarios, the agent MUST present and discuss a comprehensive breakdown of all identified edge cases directly in chat first, and await developer alignment before drafting any implementation plan. Never swallow consultation questions or edge-case discovery into an immediate plan artifact. Only after the developer confirms the direction or says to proceed (e.g. "ابدأ", "اكتب الخطة"), begin the discovery and planning workflow.
- Pre-Planning Clarification: Missing requirements, edge cases, or domain ambiguities MUST be clarified interactively via `ask_question` or discussed in plain chat before drafting the plan; guessing or silently assuming missing scenarios is strictly forbidden.
- Plan Approval Clarity: On initial plan drafting, explain to the developer: "Review the plan above; click Proceed, or reply 'ابدأ' / 'موافق' in chat to approve." If the developer replies with approval in chat, proceed immediately; never wait for a nonexistent button.
- Multi-Phase Execution: Multi-phase plans execute sequentially and autonomously. Single intake approval covers all phases; never pause or ask developer between phases.
- Strict Verification Order: The Verification Plan in `implementation_plan.md` MUST use the 6-step headings (1. preflight -> 2. unit tests -> 3. routed reviewers -> 4. device install -> 5. mobile walkthrough -> 6. verify). The agent MUST wait for ALL routed specialist reviewers (subagents) to finish, record their responses, and verify ZERO blocking findings BEFORE running `assemble` or starting device installation. Starting assemble or device deployment while any reviewer subagent is still running is strictly forbidden.
- Reviewer Dispatch: 100% autonomous. Launch routed reviewers in parallel via subagents immediately; never pause, ask for permission, or demand 'Proceed'.
- Review Protocol V2: On reactive reviewer completion, record trusted reviewer results with `python .agents/harness.py review complete --task <id> --reviewer <role> --execution-id <convId>`. Once all routed reviewers complete, finalize aggregate review evidence with `python .agents/harness.py review finalize --task <id>`. Clean reviews with findings: [] are recognized as PASS. Intermediate scratch files are forbidden.
- Use `/grill-me` before planning when material design or compatibility questions remain. Carry resolved answers into the plan without repeating them.
- After approval, `/goal` may sustain non-trivial work. The Harness router remains completion authority and all gates and developer decisions still apply.
- Zero-Polling Invariant: Never poll background tasks or subagents in a loop using `manage_task(Action='status')`, `manage_subagents(Action='list')`, or `schedule`. Yield execution and wait for reactive wakeup messages from the system. Polling loops waste tokens, trigger safety blocks, and stall execution.
- Harness Immutability & Diagnostic Protocol: The harness engine under `.agents/**` is immutable developer infrastructure. If any harness command or verification gate crashes with a Python traceback or system error, the agent is STRICTLY FORBIDDEN from attempting to edit or patch files in `.agents/**` using host tools, PowerShell, Python `-c`, or shell commands. Instead, stop immediately, report the exact traceback and root cause to the developer, and await instructions.
- Task Resumption: If a task becomes BLOCKED or fixes are needed during verification, run `python .agents/scripts/workflow.py resume --repo . --task-id <id>` to return to implementation.
- In client Android apps: The agent must not run `git add`, `commit`, `push`, merge, rebase, stash, or reset. Leave changes unstaged. Draft a Conventional Commit message only. The developer commits. In this kit repository itself (`android-harness-kit` development): The agent may run git operations when instructed by the maintainer.
- Independent Reviews: Reviewer roles selected by policy MUST be executed via subagents. The lead agent is strictly forbidden from self-certifying reviews using `record_review.py --verdict PASS` on HIGH/CRITICAL or sensitive changes; evaluations must come from actual reviewer runs.
- Antigravity Planning Lifecycle: The interactive Proceed button appears ONLY on initial task plan approval. Subsequent updates show only Review. Never tell the developer to click 'Proceed' on follow-ups or bug fixes during active tasks; execute, compile, and deploy directly. When the developer approves in chat (e.g. replies 'ابدأ' or 'موافق'), the agent MUST immediately record approval via `python .agents/scripts/workflow.py approve --repo . --task-id <id> --source conversation --proof-reference "<phrase>" --enforcement-tier RULE_ENFORCED` (which atomically transitions directly to `IMPLEMENTING`); NEVER instruct the developer to run PowerShell commands manually.
- 6-Tier Dynamic Risk Model: Review policy (`review_policy.py`) evaluates changes into 6 risk tiers (`T0_TRIVIAL` through `T5_CRITICAL`) and is the sole runtime authority for risk tier, required gates, reviewer roster, and device requirements. Execute exactly the policy-resolved roster; when reviewers are omitted by policy, do not dispatch subagents.
- Next-Action Command Router: After every lifecycle transition or verification step, query `python .agents/harness.py task status --task-id <id> --next` (or `workflow.py status`) for the authoritative next action instead of memorizing long sequential stages.
- Mobile Verification Walkthrough & Device Verification: The agent MUST wait for `run_device.py install-start` to finish execution with exit code 0 BEFORE outputting any mobile verification walkthrough or invoking `ask_question`. If `run_device.py` is still running as a background task, wait for completion; never output walkthrough or invoke `ask_question` prematurely. If `run_device.py` fails (e.g. `[ENV-FAILURE] no Android device detected via adb`), report the exact environment blocker to the developer; NEVER hallucinate device serials (such as `emulator-5554`), never claim the app is running when it is not, and NEVER ask the developer to verify a build that was not installed. If the developer chooses to skip device verification, record honest skip evidence with `python .agents/harness.py device skip-validation --task-id <id> --source conversation --proof-reference "<phrase>"` (recording `status: "SKIPPED"`, never synthetic PASS). When installation succeeds, output a complete, numbered mobile verification walkthrough (Navigation path, Preconditions, User actions, Expected results, Edge cases) in chat BEFORE invoking `ask_question` for sign-off. Once developer replies with explicit PASS, record device sign-off via `python .agents/harness.py device signoff --task-id <id> --verdict PASS --source conversation --proof-reference "<phrase>"`. Never run signoff before developer replies.
- Linked Zoho Sprints Integration: When a task plan includes an approved `zoho_link`, sync task start with `python .agents/harness.py zoho start-sync --task-id <id>` after approval, and sync delivery status/report with `python .agents/harness.py zoho delivery-sync --task-id <id>` after developer git commit.
- Context Management Actions: Updating project context, recording architectural conventions, or adding domain notes (e.g. "add this note to project context", "note that Home screen uses MVI") is an administrative context action, NOT an Android code delivery task. Do NOT run change_classifier, review_policy, unit tests, or Gradle assemble. Directly record the note using `python harness_cli.py context note "<note>"`.
- Review Host Binding:
  - In Antigravity, prepare verification with:
    `python .agents/scripts/workflow.py prepare-verification --repo . --task-id <id> --host antigravity`
  - Never claim Review Protocol V2 unless `current-run.json` says `review_protocol_version = 2`.
- Exact Reviewer Dispatch Procedure (Antigravity):
  1. Run `python .agents/harness.py task status --task-id <id> --next` (or `workflow.py status`).
  2. If code == DISPATCH_REVIEWERS:
     - use exactly the returned reviewer set;
     - one invoke_subagent call;
     - for each reviewer:
         TypeName = exact reviewer role
         Role = exact reviewer role
         Prompt = exact current reviewer brief
         Workspace = inherit (or omit if host default is used consistently)
     - do not send model/Model (INHERIT_PARENT_BY_OMISSION);
     - do not invent reasoning fields.
  3. Yield; do not poll.
  4. On reactive completion, run `python .agents/harness.py review complete --task <id> --reviewer <role> --execution-id <convId>`.
  5. On RETRY_REVIEW_PROTOCOL, execute the exact router-provided send_message.
  6. On REVIEW_ENV_BLOCKED / REVIEW_PROFILE_BLOCKED / REVIEW_PROTOCOL_BLOCKED, stop reviewer flow and report blocker.
  7. After all completed, run `python .agents/harness.py review finalize --task <id>`.
  No legacy PASS token. No EVIDENCE footer. No self-certification.
- Exact Scoped Phase Review V2 Procedure (Antigravity):
  1. On `BUILD_PHASE_REVIEW_PACKAGE`: run `python .agents/harness.py phase-review package --task-id <id> --phase-id <phase>`.
  2. On `DISPATCH_PHASE_REVIEWERS`:
     - use exactly the returned reviewer set;
     - one `invoke_subagent` call;
     - for each reviewer:
         TypeName = exact reviewer role
         Role = exact reviewer role
         Prompt = exact current phase brief
         Workspace = inherit (or omit if host default is used consistently)
     - do not send model/Model (INHERIT_PARENT_BY_OMISSION);
     - do not invent reasoning fields.
  3. Yield; do not poll.
  4. On reactive reviewer completion, run `python .agents/harness.py phase-review complete --task-id <id> --phase-id <phase> --reviewer <role> --execution-id <convId>`.
  5. On `RETRY_PHASE_REVIEW_PROTOCOL`, execute the exact router-provided `send_message`.
  6. On `PHASE_REVIEW_ENV_BLOCKED` / `PHASE_REVIEW_PROTOCOL_BLOCKED` / `PHASE_REVIEW_LEDGER_BLOCKED`, stop reviewer flow and report blocker.
  7. After all phase reviewers completed, run `python .agents/harness.py phase-review finalize --task-id <id> --phase-id <phase>`.
  8. Advance to next phase via `python .agents/harness.py task begin-next-phase --task-id <id>` (no second approval needed).

## Canonical Command Catalog & 4-Phase Lifecycle (PLAN → BUILD → VERIFY → SHIP)

Follow the simplified 4-phase lifecycle driven by `python .agents/harness.py task status --task-id <id> --next`:

| Phase | Step | Canonical Command | Description & Parameter Rules |
| :--- | :--- | :--- | :--- |
| **PLAN** | 1. Discovery | `python .agents/harness.py task-context --file <path> --json` | Bounded AST slice for target file/symbol |
| **PLAN** | 1b. Graph | `python .agents/harness.py graph --feature <name> --json` | AST/symbol feature graph analysis |
| **PLAN** | 2. Draft | `python .agents/scripts/workflow.py draft --repo . --task-id <id> --outcome "<outcome>" --kind <AUTO\|BUG\|FEATURE\|REFACTOR> --expected-files <paths>` | Create task plan; `--expected-files` is required except for T0 resource/string/doc-only plans |
| **PLAN** | 3. Approve | `python .agents/scripts/workflow.py approve --repo . --task-id <id> --source conversation --proof-reference "<phrase>" --enforcement-tier RULE_ENFORCED` | Record approval & atomically transition to IMPLEMENTING |
| **BUILD** | 4. (Compat) Begin | `python .agents/scripts/workflow.py begin --repo . --task-id <id>` | Idempotent begin compatibility command |
| **BUILD** | 4b. Zoho Start Sync | `python .agents/harness.py zoho start-sync --task-id <id>` | Sync In progress status to linked Zoho item (when plan has approved zoho_link) |
| **BUILD** | 4c. Task Handoff | `python .agents/harness.py task handoff --task-id <id>` | Freeze WIP checkpoint for safe worktree switch |
| **BUILD** | 4d. Reconcile Handoff | `python .agents/harness.py task reconcile-handoff --task-id <id>` | Validate developer WIP commit and update lineage |
| **BUILD** | 4e. Phase Package | `python .agents/harness.py phase-review package --task-id <id> --phase-id <phase>` | Build immutable phase review package markdown and lean briefs |
| **BUILD** | 4f. Phase Review Complete | `python .agents/harness.py phase-review complete --task-id <id> --phase-id <phase> --reviewer <role> --execution-id <convId>` | Record trusted specialist phase review completion |
| **BUILD** | 4g. Phase Review Finalize | `python .agents/harness.py phase-review finalize --task-id <id> --phase-id <phase>` | Finalize phase review evidence and substate |
| **BUILD** | 5. Diagnostic Build | `python .agents/harness.py assemble` | Optional diagnostic build during implementation |
| **VERIFY** | 6. Prepare | `python .agents/scripts/workflow.py prepare-verification --repo . --task-id <id> --host antigravity` | Freeze review package & transition to VERIFYING |
| **VERIFY** | 7. Preflight | `python .agents/harness.py preflight` | Deterministic preflight: strings, Room, architecture |
| **VERIFY** | 8. Unit Tests | `python .agents/harness.py test` | Run unit tests gate (when required by policy) |
| **VERIFY** | 9. Package | `python .agents/harness.py review package` | Generate immutable review package markdown |
| **VERIFY** | 10. Reviews | `python .agents/harness.py review complete --task <id> --reviewer <role> --execution-id <convId>` | Record trusted specialist reviewer completion |
| **VERIFY** | 10b. Validate Finding| `python .agents/scripts/workflow.py validate-finding --repo . --task-id <id> --finding-id <id> --status <FALSE_POSITIVE\|CONFIRMED> --reason "<text>"` | Validate reviewer finding |
| **VERIFY** | 10c. Resume | `python .agents/harness.py task resume --task-id <id>` | Resume to IMPLEMENTING if fixes needed |
| **VERIFY** | 10d. Finalize Reviews | `python .agents/harness.py review finalize --task <id>` | Finalize aggregate review evidence once all routed reviewers complete |
| **VERIFY** | 11. Assemble | `python .agents/harness.py assemble` | Build debug APK (after reviews pass) |
| **VERIFY** | 12. Device Deploy / Skip | `python .agents/harness.py device install-start` (or `device skip-validation --source conversation --proof-reference "<phrase>"`) | Install & launch on device (when required), or record explicit developer skip |
| **VERIFY** | 12b. Screen Capture | `python .agents/scripts/capture_screen.py --output-name <name>` | Optional screenshot verification proof |
| **VERIFY** | 12c. Device Signoff | `python .agents/harness.py device signoff --task-id <id> --verdict PASS --source conversation --proof-reference "<phrase>"` | Record explicit developer device verification sign-off |
| **SHIP** | 13. Final Verify | `python .agents/harness.py verify --task-id <id>` | Read-only delivery verification check |
| **SHIP** | 14. Complete | `python .agents/scripts/workflow.py complete --repo . --task-id <id>` | Seal task to READY_FOR_DELIVERY (SHIP_PENDING) |
| **SHIP** | 15. Reconcile / Deliver | `python .agents/scripts/workflow.py reconcile-delivery --repo . --task-id <id>` | Finalize to DELIVERED after developer git commit |
| **SHIP** | 15b. Zoho Delivery Sync | `python .agents/harness.py zoho delivery-sync --task-id <id>` | Sync delivery report & resolution to linked Zoho item (when plan has zoho_link) |
| - | Context Note | `python harness_cli.py context note "<note>"` | Record architectural convention/note |
| - | Context Instruct | `python .agents/harness.py context instruct "<instruction>" --scope "<scope>" --source conversation --proof-reference "<phrase>" --strength REQUIREMENT` | Add scoped developer instruction to developer-instructions.json |

## Canonical Large-Task & Phased Execution Flow

```text
one task approval
→ phase implementation
→ deterministic checkpoint
→ scoped phase delta review when selected
→ next phase
→ final integration review
→ assemble/device
→ developer signoff
→ final verify
→ developer Git commit
→ deliver
```

## Urgent Interruption & Worktree Handoff Flow

```text
Task A
→ task handoff (python .agents/harness.py task handoff --task-id <id>)
→ developer WIP commit (developer creates Git commit for checkpoint)
→ reconcile handoff (python .agents/harness.py task reconcile-handoff --task-id <id>)
→ developer creates separate worktree (git worktree add ../repo-task-b HEAD)
→ Task B in new chat/worktree
→ return to Task A worktree/chat
→ task status --next (python .agents/harness.py task status --task-id <id> --next)
```

### Core Invariants:
- **One live task per worktree**: each worktree maintains isolated task state; never run multiple concurrent tasks in the same worktree.
- **Model never executes Git mutations**: Git add, commit, tag, push, checkout, merge, and worktree operations are strictly developer-owned.
- **Lineage enforcement**: a raw unregistered mid-task commit is a lineage violation; only a validated handoff checkpoint commit with accepted lineage receipt is allowed.
- **Final review required**: aggregate final integration review remains required even when all intermediate phase reviews pass.

Antigravity loads `agents/hooks.json` in this repo. Gemini CLI does not; still execute the policy-resolved reviewer roster before assemble. No `code-review-guard-agent`. No `LGTM`.
