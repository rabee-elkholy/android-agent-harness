# Acceptance evidence, reusable journeys, and local metrics

These features are optional. Existing tasks and installations retain their established behavior. They use the same router, risk policy, approval hash, and append-only evidence store as the rest of the harness.

## Acceptance criteria

Keep reusable definitions in project-owned JSON, for example `harness-verification/refresh.json`. The installer does not own this directory; updates and uninstall preserve it. The approved plan embeds the definition, so editing a reusable file does not silently change a live task. Apply a changed definition through the existing plan revision and approval flow.

```json
{
  "schema_version": 1,
  "criteria": [
    {"id": "refresh", "expected": "Refresh shows updated data", "method": "test", "required": true},
    {"id": "rotation", "expected": "Rotation does not repeat the request", "method": "manual", "required": true}
  ],
  "journeys": []
}
```

Include it when drafting a task:

```text
python .agents/harness.py task draft --task-id refresh --outcome "Fix refresh behavior" --expected-files <approved-files> --verification-contract harness-verification/refresh.json
```

The approval material lists criteria, verification methods, and selected journey effects. Required criteria become obligations only for this approved task. Advisory criteria display gaps without blocking completion. Omitted criteria retain the legacy path. Revisions retain the contract unless a replacement definition is explicitly supplied.

After the normal gates run, inspect and associate relevant evidence:

```text
python .agents/harness.py task coverage --task-id refresh --json
python .agents/harness.py task bind-evidence --task-id refresh --criterion refresh --artifact unit_tests --case "com.example.RefreshTest#showsUpdatedData"
```

The exact case must have a fresh successful outcome. Skipped cases, baseline failures, a passing module alone, and a case with the same short method name in a different class cannot satisfy the requirement. The gate collects exact-case outcomes only for opted-in tasks. It does not force a rerun by default. If Gradle reused old reports and current-case proof is missing, explicitly rerun only the selected gate/task with `test --task <task> --rerun-tests`; the flag uses Gradle's `--rerun-tasks` for that invocation.

For a manual criterion, show its expected behavior and get the developer's explicit result. Record the existing sign-off with `--criterion-id rotation` (repeat for every criterion the developer actually checked), then bind the criterion to `device_signoff`. A general sign-off cannot silently cover all criteria. Existing device-disabled installations cannot approve required manual or journey criteria until their device policy is intentionally changed.

A review criterion requires an independent reviewer report with an explicit `criterion_results` mapping. V2 reviewer output supports this optional mapping, using PASS, FAIL, or NEEDS_CONTEXT. The review package includes the approved criteria. A lead-authored report or a provider without verifiable independent, criterion-specific results cannot satisfy it; choose a test/manual method before approval when appropriate. Existing review protocol requirements are unchanged.

Coverage validates evidence identity and association, not the meaning of the assertions. Existing test-quality and completeness review still judges relevance. Reassociation is necessary after a newer evidence attempt; edits, a new run, or changed approved definitions invalidate earlier proof.

## Reusable journeys

Use a JSON journey definition and embed it in the contract's `journeys` array. Every selected journey must run successfully, except when an approved complete-walkthrough choice explicitly substitutes manual verification as described below. Criterion associations additionally follow required/advisory status.

```json
{
  "schema_version": 1,
  "id": "refresh-flow",
  "version": 1,
  "purpose": "Refresh exposes updated content",
  "criteria": ["refresh-ui"],
  "module": ":app",
  "variant": "Debug",
  "application_id": "com.example.app",
  "prerequisites": "Open the refresh screen using a test account; refreshed content is available",
  "effects": ["ui_interaction"],
  "steps": [
    {"action": "tap", "selector": {"resource_id": "com.example.app:id/refresh"}, "timeout": 5},
    {"action": "assert_present", "selector": {"content_desc": "Updated content"}, "timeout": 10}
  ]
}
```

Define `refresh-ui` as a journey-method criterion in the same contract. Journey modules and variants must match the approved task and installed project. Validate a file without a device, inspect the selected definitions, and explicitly replay:

```text
python .agents/harness.py journey validate --file harness-verification/refresh-journey.json --json
python .agents/harness.py journey list --task-id refresh --json
python .agents/harness.py journey run --task-id refresh --id refresh-flow --serial <installed-device-serial> --json
python .agents/harness.py task bind-evidence --task-id refresh --criterion refresh-ui --artifact journey-refresh-flow
```

Resolve the serial of the device already used by harness installation. Confirm stated prerequisites before replay. Do not automatically replay all saved journeys or retry failures until one passes.

Supported actions: tap, back, input, wait_present, assert_present, and assert_absent. A selector has exactly one resource_id, content_desc, or exact text. Ambiguity fails; coordinates and arbitrary shell commands are unsupported. Input uses a local uppercase `secret_env` reference, accepts a limited ASCII character set, and requires an already-focused field. Input values are not copied to evidence. Opaque Compose UI without exposed selectors requires manual verification.

The initial runner supports the primary Android user only, caps journeys at 40 steps and 120 seconds, and requires at least one observable assertion. It checks device/foreground identity and installed APK checksums against the verified artifact set. APKs must be readable via `sha256sum`; unsupported device capabilities report an environment limitation rather than success. No screenshots are captured by this version.

The normal review/build/install proof must be valid before replay. The runner does not install, uninstall, clear data, grant permissions, purchase, or authorize external account writes. A permitted tap does not independently authorize a business side effect: selected journeys must use safe screens and test accounts within approved scope. Partial journeys retain the established human sign-off requirement.

### Choose manual or automatic validation after install

When the selected journeys cover the complete mobile walkthrough with observable assertions, add `"device_validation": "manual_or_automatic"` to the contract before task approval. The approval material states that automatic PASS replaces manual repetition. All journeys must share one application/module/variant, with at most 40 combined steps and a combined 120-second budget. A required human-only criterion makes this mode invalid. Do not mark a partial replay or subjective visual/usability check as a complete automatic walkthrough.

After `device install-start` succeeds, present the approved walkthrough in chat with the existing manual PASS/FAIL responses and **Run Automatically**. There is no harness-installation wizard question or persistent project-wide automatic setting. Never preselect or execute automation without the developer's answer.

The agent executes the selected option, using the developer's answer as its proof reference:

```text
python .agents/harness.py device validate-automatically --task-id refresh --serial <installed-device-serial> --source conversation --proof-reference "Run Automatically"
```

This runs the complete approved set and binds its criterion evidence automatically. A complete PASS supplies device validation without creating `device_signoff` or asking for manual repetition. FAIL blocks completion for diagnosis. ENV reports the limitation and offers manual validation; it is never converted to PASS or retried automatically.

Manual sign-off and complete automatic execution share a bounded execution lock. A concurrent mode change fails cleanly instead of overwriting an in-flight selection. Interruptions leave blocked evidence, and malformed source attempts block delivery rather than being interpreted as success.

For the manual alternative, the agent records `device signoff --verdict PASS` with one `--criterion-id` per journey criterion the displayed walkthrough covers, plus the existing authority/proof arguments. Those explicit associations are recorded automatically; no replay is required. A new automatic attempt supersedes previous success before any device effect, and stale source attempts invalidate the automatic result. Final approval of sensitive changes remains developer-owned and separate from automatic validation.

Consecutive `assert_present` steps may share one screen observation. Each assertion retains its own result and identity check; an unmatched selector resumes its normal bounded polling and discards the remaining observations. Taps, input, back, waits, and negative assertions always request fresh observations. In particular, tap targets are read again even after a successful assertion. Device identity uses one bounded ADB shell probe for the current Android user and foreground activity, and still rejects disconnected devices, other users, and other foreground applications. This reduces device round trips without changing the approved journey or allowing earlier-run evidence to satisfy it.

## Local metrics

Set `HARNESS_LOCAL_METRICS=1` in the agent process environment to collect compact timings for repository-local launcher operations. Collection is disabled otherwise. No installation question, network request, daemon, or host transcript reader is added.

```text
python .agents/harness.py task metrics --task-id refresh --json
```

The report shows observed command durations, attempt counts, nonzero exits, and available task review rounds/blockers. It distinguishes summed operation time from the union of observed intervals, so overlapping commands are not presented as elapsed wall time. Explicit host reasoning, reviewer execution outside launcher commands, developer working time, token usage, costs, and unrecorded interventions remain UNAVAILABLE.

Collection caps history at 512 events per task and records no command arguments, source content, input values, or raw output. Corrupt or partial diagnostic events are counted, not treated as evidence. Diagnostic write failure never changes a valid command outcome. Reports are on demand and cannot change gates or reviewer selection. Authoritative run evidence is never rotated to fit a metrics quota.

## Validation limits

Kit validation uses deterministic fixtures and fake transports only. Real Android/device certification requires a separate approved client checkout. Local suite success does not imply cross-platform CI or device certification, and no release is published by these features.
