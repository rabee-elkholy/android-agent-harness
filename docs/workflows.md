# Workflows

All workflows use the central lifecycle in `.agents/scripts/workflow.py`.

| Workflow | Purpose | Key property |
|---|---|---|
| `deliver` | Implement an approved change | Runs only policy-selected gates and reviewers |
| `debug` | Reproduce and fix a defect | Hypothesis-first and test-backed |
| `new-feature` | Add product behavior | Resolves material choices before plan approval |
| `preflight` | Fast static checks | Localization/Room/lint run only when relevant |
| `perf-audit` | Inspect performance risk | Evidence-driven; device profiling is optional unless policy requires it |
| `test-quality-audit` | Inspect test value | Does not replace execution evidence |
| `zoho-sprints` | Read or explicitly update tickets | Writes only after `update zoho` |

## Standard sequence

1. Inspect and analyze without mutation.
2. Draft a bounded plan with expected surfaces and skills.
3. Wait for explicit developer approval.
4. Consume approval and implement.
5. Freeze the delivery manifest and adaptive policy.
6. Run only selected gates and reviewers.
7. For sensitive surfaces, the developer separately approves the frozen final
   snapshot interactively in chat (via `ask_question`), from their terminal, or via host-native control.
8. Read-only final verification.
9. Mark the unchanged snapshot ready and hand it off.

A blocking finding returns the task to `BLOCKED`. `resume` reopens implementation under the same approved scope; a material scope change requires a new approval. Three failed review rounds require developer direction.
The AI hook denies `approve` and `approve-sensitive` without `--source conversation`, and denies `cancel`; those
developer-authority transitions must come from explicit developer approval.

## Verification recovery

| Situation | Action |
|---|---|
| A selected gate is rerun on the same frozen run | Its new immutable attempt becomes authoritative. Resolve any failure before delivery; an earlier PASS does not override it. |
| A gate reports authoritative evidence discovery/write failure | Stop verification, resolve the state/filesystem failure, and rerun the gate. Do not treat diagnostic output or an earlier PASS as proof of this execution. |
| `prepare-verification` fails while publishing run artifacts | After resolving the filesystem error, retry preparation while the task remains `IMPLEMENTING`. Previous completed review evidence is retained through the persisted plan's run identity. |
| A task's declared baseline is missing or corrupt | Restore the original task state from a trusted backup. Do not recreate the baseline from the current tree or delete state to bypass the error. |
| Delivery inputs or recorded file modes change after verification | Resume implementation, then prepare fresh verification under the approved scope. |

The agent handles routine retries and harness commands. The developer intervenes only for filesystem/access decisions, unrecoverable task state, material scope changes, or other explicit authority boundaries.

## Approved resource file scope

Both `prepare-verification` and final verification enforce the approved file scope
against the task delta. Renames require authority for the deleted source and the
destination; revise hints include both paths. A copy does not require write authority
for its unchanged source. An empty task delta does not include unrelated baseline edits.

When a plan declares `expected_files`, resource surfaces (`RESOURCE_UI`, `XML_UI`,
`LOCALIZATION`) do not authorize additional files. The same check runs before file
mutation and during `prepare-verification`. Explicitly approved new files can be
created without another approval; additional resources, modules, or source sets
outside the declared scope require `revise` and approval of the new plan hash.
Repository-relative Windows separators are normalized for comparison. Existing
surface/module-scoped plans with no explicit file list and declared companion-test
behavior retain their existing semantics; no directory/glob syntax is introduced.

## Reviewer dispatch visibility

`task status --next --json` exposes canonical dispatch data at `next_action.inputs`.
Plain status emits it once as `NEXT_ACTION_INPUTS=<JSON>` for final/phase dispatch
only. Use the returned roster. For final dispatch, pass `reviewer_prompts[role]` as
`invoke_subagent.Prompt`: a one-line pointer naming the current brief's path and the
first 16 hex characters of its content hash; the reviewer reads the brief itself, and
the hook refuses a stale or other-role pointer. The exact brief content (`brief_content`)
is still accepted. Phase inputs provide current brief paths, which the host must read
and pass in full; a bare path is not a valid Prompt. V1 fallback is unchanged. This is CLI visibility, not a new dispatch mechanism. WAIT and protocol
retry actions never authorize redispatch; trusted completion and same-model
inheritance remain governed by the existing host contract.

## Gradle progress and daemon investigation

The Gradle runner uses one quiet-output heartbeat, owned by `run_streaming`; its
outer step marker has no separate timer. Step cleanup stops and joins its heartbeat
on success, failure, and interruption before emitting the completion marker. Stream
cleanup also joins its worker before returning. Raw logs, exit-code classification,
and authoritative gate publication retain their existing contracts.

The runner adds `--console=plain` when needed and preserves explicit daemon options
and the inherited Gradle/JDK/JVM/user-home environment. The reviewed callers do not
inject `--no-daemon`. No harness cause of O15 daemon non-reuse was established, and
no daemon setting was changed. Command-construction tests are not proof of real
reuse. Investigating a client report still requires that client's wrapper version,
command/environment, project and user Gradle properties, selected Java/JVM criteria,
and daemon logs. Gradle's [daemon compatibility documentation](https://docs.gradle.org/current/userguide/gradle_daemon.html)
and [build environment precedence](https://docs.gradle.org/current/userguide/build_environment.html)
explain why incompatible JVM settings or explicit disabling can prevent reuse.

## Optional verification value

New tasks can select an approved JSON verification contract for criterion-specific acceptance evidence and reusable UI journeys. Definitions remain project-owned outside `.agents`; installation, update, and uninstall do not manage them. Existing tasks are unchanged. Local operation timings are enabled only through `HARNESS_LOCAL_METRICS=1`, with reports generated on demand. These features add no setup question or external service. See [verification-value.md](verification-value.md) for schema examples, prerequisite gates, and commands.
