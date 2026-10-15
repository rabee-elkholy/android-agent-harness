# Continue a task across AI hosts

An approved task belongs to its repository/worktree, not to one chat provider.
Use the same checkout when moving between Codex, Antigravity, or another supported
host. Stop the former chat's execution before the receiving chat takes over.
No commit, branch switch, new task, or repeat plan approval is required merely
because the executor changed. Scope changes still follow normal revision rules.

In the receiving chat, the agent runs:

```text
python .agents/harness.py task status --task-id <task-id> --next --host <actual-host>
python .agents/harness.py task continue --task-id <task-id> --host <actual-host> --source-stopped
```

Use the exact `--expect-session` value when the router supplies it. This rejects a
takeover based on an old observation. Repeating continuation on the same host and
session is idempotent. For example, replace `<actual-host>` with `codex` or
`antigravity`; never declare the preferred host instead of the host executing the
command. Codex's process-local thread identity is detected automatically. Native
hook adapters identify their hook host; other launchers can declare `HARNESS_HOST`.
When no current host is available, the active continuation or project preference
is only a routing fallback, not independently verified host identity.

The returned brief links the original plan, notes and developer instructions and
reports current phase, completed phases, recorded review spending, pending finding
owners, and the canonical next action. It is regenerated from repository state;
it does not infer decisions from an old provider conversation.

## Review and evidence behavior

- Implementation retains the approved plan, nonce, phase progress and application
  files. A stale repository/branch or unaccepted commit lineage blocks takeover.
- A changed verification snapshot permits ownership transfer but never proof
  reuse. Keep the old run unchanged and follow the router to resume implementation
  and verify the changed inputs normally.
- A completed phase retains its original review provenance. A completed final
  review keeps its verification run and deterministic/device evidence. Changing
  host does not turn rule-enforced or unverified review into trusted native proof.
- An open phase review on another host is archived under `review-history/` and
  recreated from its still-fresh checkpoint. Its tests and compile are not rerun.
- An unfinished final review gets a new run bound to the same snapshot and policy.
  Valid deterministic PASS records are reused with explicit references to their
  original attempt hashes. Original records remain authoritative and are retained
  during evidence pruning. Missing, changed, corrupt, failed or incompatible proof
  cannot become PASS through transfer. Reviews and sensitive approvals are never
  copied into a new run.
- Recorded findings remain blockers. Reviewer spending and protocol retry limits
  remain in force; interrupted recorded final dispatches are charged before the
  replacement round. A transfer cannot silently increase the spending budget.
- A crashed transfer blocks mutations and offers the same continuation command for
  recovery. Canonical pointers are restored before retry; incomplete new review
  artifacts remain available for diagnosis.

Ownership is `RULE_ENFORCED`. Native mutation hooks reject a former executor, and
the installed launcher serializes mutating commands against takeover. Hosts without
native mutation interception rely on their instructions and downstream checks;
these receipts are not an OS lock over all editors or cryptographic host identity.
Keep only one chat writing. Git worktree changes and transfers to another checkout
remain separate developer-owned operations.

Installed clients need a harness version containing this command. Updating this
source checkout alone does not migrate an already installed client or repair its
active review run. Never patch an installed engine or edit its evidence by hand.

## Temporarily reserve execution for an update

Stop the active executor first. For an approved live task, the maintainer may
explicitly update the installed engine without cancelling or completing the task:

```text
python "<kit-dir>/harness_cli.py" update --repo "<app-root>" --kit "<kit-dir>" --preserve-active-task <task-id> --source-stopped
```

The updater checks the exact active task, approval and repository lineage, refuses
live state/execution/review locks, and holds an update reservation. Native mutation
hooks and the installed launcher reject task mutations while the reservation is
held. Hosts with rule-only interception still require the executor to be stopped.
The original task state and evidence must survive byte-for-byte; setup answers and
context refresh cannot be changed in this mode. A mismatch rolls the update back.

Successful completion releases the reservation without changing the task status,
approval, review policy or evidence provenance. A crash keeps the update journal
pending; repeat the same update command to recover before continuing. Keep the
pre-update backup. Ordinary updates still refuse live tasks without this explicit
option. After updating, query task status and use the normal continuation command
if changing hosts. See [ADR-010](adr/010-active-task-preserving-update.md).

Verification runs freeze the installed engine version. After a preserving engine
update, a run created under the previous version routes to `VERIFICATION_STALE`.
Use `task resume`, then `task prepare-verification` on the same task. The new run
must execute its required gates with the current engine; the old immutable proof,
approval, reviewer-call consumption and round decisions remain intact. Later-round
review coverage follows the central policy and existing provenance checks. An
update itself never certifies old proof or grants another review round. Legacy
runs without a version use the completed preserving-update journal to detect
that their verification predates the replacement. Preflight and device commands
refuse that stale engine identity before executing checks or deployment.
