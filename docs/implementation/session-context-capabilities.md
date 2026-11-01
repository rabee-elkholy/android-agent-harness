# Session-aware context presentation: capability investigation

Investigated: 2026-11-01. Decision: **automatic reuse UNSUPPORTED by the current
harness adapters; retain full output unless an explicit baseline is supplied**.
This is the Phase A unsupported branch of the approved session-context plan.
It is not a claim that every possible future Antigravity API is unsupported.

## Baseline and environment

GitHub `refs/heads/main`, checked read-only with `git ls-remote`, was
`2701c2c61cd4960247c561f78de36b0ee9896d5f` (v1.1.59), matching this checkout's
base. At investigation time the local efficiency changes were uncommitted prerequisites.
No Antigravity CLI executable (`agy` or `antigravity`) or native runtime storage
was found in this environment. Native delivery/retention tests were NOT RUN.
No installed Antigravity version can therefore be certified here. The official
changelog inspected lists v2.28.2 dated October 29, 2026; this is documentation
context, not an installed-version attestation.

## Official sources inspected

Retrieved the following public documentation on 2026-11-01:

- [Hooks](https://antigravity.google/docs/hooks/), especially common fields,
  SessionStart, PreToolUse, PostToolUse and PreInvocation.
- [Context command](https://antigravity.google/docs/cli/commands/context/),
  especially Manage context growth and checkpoint summaries.
- [Conversations](https://antigravity.google/docs/cli/conversations/).
- [SDK lifecycle](https://antigravity.google/docs/sdk/lifecycle/).
- [SDK tools](https://antigravity.google/docs/sdk/tools/).
- [Changelog](https://antigravity.google/docs/changelog/).

The hooks reference says PostToolUse "Fires after a tool completes" and its
output "Returns an empty JSON object {}". Its listed inputs include toolCall,
stepIdx and error plus common metadata. It does not describe a final delivered
response acknowledgement or an overwriteResult field. The PreToolUse `overwrite`
field modifies tool arguments; it does not replace a completed result.

The context reference says: "Antigravity automatically compacts older turns into
checkpoint summaries". A summary may omit exactly the fields our presentation
would omit. The published PreInvocation fields invocationNum and initialNumSteps
do not enumerate retained response identities or define a retention epoch.

## Capability matrix

| Required guarantee | Documented evidence | Current adapter evidence | Decision |
| --- | --- | --- | --- |
| Recipient execution identity | Common conversationId, transcriptPath; SessionStart | Trusted subagent transcript resolution exists; current parent CLI metadata transport not established | Partial; insufficient alone |
| Final response/call correlation | PostToolUse toolCall, stepIdx, optional error | No verified mapping for async final output and model delivery | Unverified |
| Supported presentation interception | PreToolUse argument overwrite; PostToolUse returns {} | Existing safety hooks and reviewer reconciliation, no verified result replacement | No supported automatic path established |
| Complete successful delivery to recipient | Tool completion event | No attestation that the entire full response reached model input, including truncation/failure cases | Unverified |
| Baseline still in current input | Context panel shows checkpoint summaries | No supported per-response retention/invalidation interface detected | Unverified |
| Safe invalidation after fork/prune/resume | Conversation/context docs describe lifecycle operations | No complete observed hook ordering/retention fixtures | Unverified |
| Safety-hook precedence for a new presentation hook | Hooks lifecycle docs | Existing safety behavior proven by existing suites; no new hook installed | Not changed |

Confidence: high in the quoted documentation contracts and inspected adapter
limitations; no native execution evidence. Absence from inspected documentation
does not prove host-wide impossibility. Supporting automatic reuse requires new
documented AND observed guarantees, rather than a guessed field or version check.

## Retained outcome

The maintainer requested removal of the optional capability field, Doctor
message and diagnostic-specific test. That runtime diagnostic has been removed;
this research is retained for future reference.

The installed workflow still requires full context after summarization, pruning
or uncertain resume. Existing explicit `--since` and `--full` contracts remain.
No automatic flag, persistent baseline store, observer hooks, mode configuration
or dormant automatic implementation was introduced.

## Validation and deferred phases

The existing explicit-baseline and changed-source regression coverage remains,
including a repeated public CLI request returning FULL despite a claimed
same-session environment value. The diagnostic-specific test was removed along
with the diagnostic; the efficiency suite now contains eight tests.

Automatic cache/concurrency tests, eligible-repeat performance measurements and
native rollout are **DEFERRED: capability prerequisites not established**.
There is no automatic candidate to benchmark, no claimed speed/byte improvement
from this change, and no observation/auto setting to activate. Deterministic
validation cannot substitute for native retention/delivery qualification.

Reopen Phase B only when a supported integration provides all three: trusted
recipient identity, confirmed complete delivery, and proof of ongoing baseline
availability (or reliable invalidation before reuse). Reuse existing presentation
digests after current discovery. Confirm reviewer isolation and context reset
behavior through native fixtures before enabling any automatic policy.

At investigation time these changes were local and CI had not run. Publication
validation is tracked separately by the release pipeline; this document does not
claim native Antigravity qualification.
