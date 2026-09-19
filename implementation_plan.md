---
ArtifactMetadata:
  UserFacing: true
  RequestFeedback: true
---

# Safe Project Intelligence — Implementation Plan

## Objective

Add deterministic local Project Intelligence to Android Agent Harness so an agent can resolve the smallest accurate context for a concrete Android task across mixed Java/Kotlin, XML/Compose, MVP/MVVM/MVI-like, multi-module, flavored, and KMP projects.

The intelligence remains advisory. It must not change developer authority, approval behavior, architecture contracts, verification rules, Git authority, or application code automatically.

This repository is the Harness kit itself. Development and verification of this plan use Python tooling only:

- no Harness workflow state;
- no Android specialist reviewers;
- no Gradle or ADB;
- no device walkthrough;
- no external writes;
- no Git mutation during implementation and verification; the maintainer later
  explicitly authorized commit, push, version publication, README updates, and
  CI confirmation after every local release gate passes.

## Decisions Locked Before Implementation

1. Keep `project-facts.json` at schema version 2.
2. Add only an optional top-level `advisory_knowledge` block.
3. Keep existing architecture-family signatures and IDs byte-for-byte stable.
4. Keep old scalar fields such as `ui_toolkit`; add richer advisory arrays rather than replacing scalar semantics.
5. Reuse `project_context.py`, `architecture_resolver.py`, `_graph_core.py`, and `GraphEngine`.
6. Do not create a second graph, context root, architecture policy, or resolver.
7. Persistent context refresh stays explicit, full, staged, and facts-last.
8. Ordinary Task Context resolution does not persist source, context, workflow, or graph-cache changes.
9. Local conventions remain guidance even at high confidence.
10. No automatic architecture migration or modernization is allowed.

## Selected Design

```text
authoritative project facts + approved task contract
                         ↓ authority
optional advisory local profiles
                         ↓ acceleration
incremental in-memory graph
                         ↓ candidate discovery
targeted live source verification
                         ↓
bounded Task Context result
```

The graph and advisory snapshot generate candidates. Current source verification decides whether a candidate is still usable. An approved task contract always outranks Task Context.

## Stable Data Contracts

### Advisory knowledge

```json
{
  "schema_version": 2,
  "extractor_version": "2.1.x",
  "facts": {},
  "advisory_knowledge": {
    "schema_version": 1,
    "local_profiles": [],
    "convention_profiles": [],
    "generated_from": {},
    "knowledge_fingerprint_sha256": "..."
  }
}
```

The advisory fingerprint is canonical SHA-256 over normalized advisory content excluding the fingerprint field itself. It is independent of the authoritative architecture fingerprint and every family-ID signature.

### Local profile identity

Each profile is identified by:

```text
module + source_set + logical/package scope + normalized repository paths
```

Profiles are clustered at the nearest stable package or feature scope. A cluster is split when its UI toolkit or presentation relationship differs. Profiles are not created per class. Evidence and exemplars are capped and sorted deterministically.

### Confidence

- `UNKNOWN`: no reliable relationship evidence.
- `LOW`: one independent structural signal.
- `MEDIUM`: at least two compatible evidence items.
- `HIGH`: at least three compatible items, including a verified relationship such as presenter↔view contract, screen↔state holder, inheritance, import, or confirmed graph edge.
- `CONFLICTED`: evidence disagrees; never choose a winner silently.

A filename alone cannot classify MVP, MVVM, or MVI. One occurrence cannot become a project convention.

### Task Context result

Task Context uses its own schema and resolver version. Stable statuses:

- `RESOLVED`
- `AMBIGUOUS`
- `NOT_FOUND`
- `INVALID_TARGET_PATH`
- `ADVISORY_STALE_FALLBACK_USED`
- `CONTEXT_CONFLICT_WITH_APPROVED_CONTRACT`
- `GRAPH_FALLBACK_USED`

Default output is bounded to:

- one resolved target;
- direct dependencies and dependents only;
- directly relevant tests;
- at most three compatible profiles;
- at most five exemplars per profile;
- at most five evidence items per inferred field.

An optional limit may reduce these caps but cannot exceed a fixed safety maximum.

## Resolution Invariants

### Identity precedence

```text
exact repository path
→ unique exact FQN
→ exact module + source set + symbol
→ unique short symbol
→ AMBIGUOUS or NOT_FOUND
```

FQN is not assumed globally unique. Multiple modules or source sets may contain the same package and declaration. The graph must retain all candidates; no API may silently return the first duplicate.

Source-set identity covers `main`, build types, flavors, combined variants, `test`, `androidTest`, `commonMain`, `androidMain`, and other discoverable Gradle-style `src/<name>` roots. Unknown layouts remain explicit rather than being folded into `main`.

### Read-only graph mode

Add an explicit non-persisting mode such as `GraphEngine.sync(persist=False)`. Existing graph commands retain persistent caching by default. Task Context always uses the non-persisting mode.

### Live verification

Before returning target-local relationships, verify:

- resolved path remains inside the repository;
- the file exists and is supported;
- the expected declaration still exists;
- evidence hashes still match;
- graph relationships agree with current imports/declarations where the decision matters.

Stale evidence invalidates only its local profile. It must not trigger automatic full persistent refresh.

### Path and symlink containment

Every file target is resolved before indexing. Reject:

- `..` traversal escaping the repository;
- absolute external paths;
- symlinks resolving outside the repository;
- broken links;
- directories;
- unsupported file types.

An internal symlink is usable only when its resolved target remains inside the repository and current repository policy permits it.

### Approved contracts

Only a hash-valid approved contract belonging to the active task may be consulted. Draft, cancelled, stale, foreign-task, or corrupted contracts are ignored or reported. A conflict returns `CONTEXT_CONFLICT_WITH_APPROVED_CONTRACT`; Task Context never edits a plan or contract.

## Persistent Snapshot Consistency

Generation and refresh follow:

```text
fingerprint A
→ extract facts and advisory knowledge
→ fingerprint B
→ if A != B, discard and retry once
→ stage views and facts using the accepted fingerprint
→ optional final pre-commit fingerprint check
→ replace views
→ replace project-facts.json last as the authoritative commit point
```

If the repository changes again, return `CONTEXT_SOURCE_CHANGED_DURING_EXTRACTION`, clean staging, and commit nothing.

`write_project_context()` must use the fingerprint belonging to the extracted payload. It must not recompute a newer fingerprint and attach it to older facts. An edit after the final check may make the snapshot immediately stale, but the stored fingerprint must still truthfully identify the extracted state.

## Implementation Phases

### Phase 1 — Compatibility Baseline and Resolver Safety

Primary files:

- `agents/scripts/architecture_resolver.py`
- `agents/scripts/_architecture_selftest.py`

Work:

1. Freeze golden family IDs and schema-v2 behavior before implementation.
2. Add failing regressions for ambiguous `PRESERVE` and `REFACTOR` when a preferred new-code family exists.
3. Remove preferred-new-family fallback from existing-code modes.
4. Return `ARCHITECTURE_DECISION_REQUIRED` when the local source family cannot be resolved confidently.
5. Preserve explicit target-family and unique-local-family behavior.
6. Prove `NEW_SCREEN`/`NEW_FEATURE` still use preferred-new-code policy and `MIGRATION` remains explicit.

Exit criteria:

- ambiguous existing-code work never modernizes implicitly;
- all existing family IDs remain unchanged;
- existing architecture-policy files remain valid.

### Phase 2 — Concurrent Snapshot Protection

Primary files:

- `agents/scripts/project_context.py`
- `agents/scripts/generate_project_context.py`
- focused context/lifecycle selftests

Work:

1. Separate accepted extraction fingerprints from write-time behavior.
2. Add pre/post fingerprint comparison and one bounded retry.
3. Abort without commit after repeated instability.
4. Preserve notes, architecture policy, overrides, and rendered-view semantics.
5. Add fault injection around extraction, staging, and commit boundaries.
6. Ensure temporary staging is cleaned after every outcome.

Exit criteria:

- old facts can never receive a newer fingerprint;
- every aborted refresh leaves the previous snapshot authoritative and complete.

### Phase 3 — Advisory Architecture and Convention Profiles

Primary files:

- `agents/scripts/project_context.py`
- new `agents/scripts/_project_intelligence_selftest.py`

Work:

1. Add the optional versioned advisory block.
2. Detect module, source set, package/logical scope, language, UI toolkits, XML-hosts-Compose interop, presentation relationships, state/async models, and DI signals.
3. Add conservative Java MVP-like inference using presenter, contract, view interface, and relationship evidence together.
4. Build scoped convention profiles using explicit confidence/conflict rules.
5. Store repository-relative paths and hashes only.
6. Exclude source contents, secrets, absolute user paths, generated output, and build output.
7. Keep existing rendered Markdown semantics unchanged.

Exit criteria:

- Java/XML/MVP-like, Kotlin/XML/MVVM, and Kotlin/Compose/MVI-like areas coexist without global flattening;
- mixed UI is represented without changing existing scalar enforcement;
- same-family scopes do not leak conventions into each other.

### Phase 4 — Duplicate-Safe Graph and Task Context

Primary files:

- `agents/scripts/_graph_core.py`
- new `agents/scripts/task_context.py`
- graph and Project Intelligence selftests

Work:

1. Introduce multi-candidate FQN and symbol indexes where Task Context needs them.
2. Preserve current graph command output and cache compatibility.
3. Add non-persisting incremental sync.
4. Implement exact resolution precedence and source-set identity.
5. Perform targeted live verification and stale-profile fallback.
6. Return direct neighborhood, directly relevant tests, conventions, and interop boundaries within fixed limits.
7. Compare against a valid active approved contract without mutation.
8. Produce deterministic JSON ordering and stable error codes.

Exit criteria:

- duplicate symbols/FQNs never resolve arbitrarily;
- rename, move, delete, and corrupt-cache cases cannot return stale targets;
- unrelated edits do not cause persistent full refresh.

### Phase 5 — Safety, Doctor, CLI, and Documentation

Primary files:

- `agents/scripts/mutation_guard.py`
- `agents/scripts/pre_tool_safety.py`
- `agents/scripts/doctor/engine.py`
- `harness_cli.py`
- safety, hook, daily-workflow, and public-CLI selftests
- `README.md`, `docs/architecture.md`, `docs/tool-support.md`

Work:

1. Register Task Context as a trusted inspection command with an exact argument allowlist.
2. Count only a successful targeted `RESOLVED` or `AMBIGUOUS` result as anchored discovery.
3. Preserve unknown-script, shell-laundering, path, and Graph-first barriers.
4. Add public CLI help and examples without a second implementation path.
5. Add Doctor `PASS/WARN` checks for parseability, version, fingerprint, relative paths, bounded evidence, and suspicious secret material.
6. Treat missing advisory knowledge on an old compatible installation as non-fatal.
7. Preserve installer ordering and avoid a context↔warm-cache dependency cycle.

Exit criteria:

- Task Context performs no persistent write in ordinary use;
- failed or invalid calls do not unlock broad discovery;
- unknown Python scripts remain blocked.

### Phase 6 — Hardening, Performance, and Release Integrity

Primary files:

- Project Intelligence, graph, performance, lifecycle, and compatibility selftests
- `agents/release_checksums.json` only after the final file set is frozen

Work:

1. Complete the edge-case matrix below.
2. Add a deterministic large mixed-project fixture.
3. Measure full extraction, warm unchanged resolution, relevant edit, unrelated edit, and forced refresh.
4. Use deterministic work counters as the release assertion: warm unchanged resolution and unrelated-edit resolution must process less than 25% of the files processed by full extraction on the fixture.
5. Record wall-clock medians for visibility, but do not make cross-platform release success depend on a flaky timing threshold.
6. Run the complete selftest, compileall, diff check, and release validation.
7. Refresh checksums last, then perform the separately authorized release only
   after local release validation and CI pass.

Exit criteria:

- all deterministic compatibility, lifecycle, safety, and performance assertions pass;
- implementation itself performs no Git mutation; the separately authorized
  release occurs only after the completed plan is green.

## Mandatory Edge-Case Matrix

### Compatibility

- Old schema-v2 snapshot without advisory knowledge.
- Unknown future advisory version.
- Malformed advisory block and fingerprint mismatch.
- Family IDs before/after on every golden fixture.
- Existing preferred-family policy, notes, overrides, and rendered files unchanged.
- Fresh install, update preserve, update refresh, interrupted update, and rollback.

### Architecture and conventions

- Java/XML/MVP-like.
- Kotlin/XML/MVVM.
- Kotlin/Compose/MVI-like.
- All three in one repository.
- XML Fragment hosting Compose.
- Java UI calling Kotlin data code.
- LiveData/Flow bridge.
- Legacy and modern siblings in one feature.
- Weak, repeated, contradictory, and deleted evidence.
- Same architecture family with different local conventions.

### Identity and source sets

- Same short symbol in two modules.
- Same FQN in two modules.
- Same symbol/FQN in `main` and `debug`.
- `commonMain`/`androidMain` expect/actual pair.
- Flavor and combined-variant source sets.
- Exact path, unique FQN, qualified identity, unique short name, ambiguous name, missing target, and unsupported target.

### Graph and freshness

- No cache, valid cache, corrupt cache, future cache schema, and incomplete cache.
- Rename, move, delete, and declaration change without filename change.
- Relevant edit, unrelated edit, timestamp-only change, and content change with preserved timestamp where feasible.
- Missing graph edge with a relationship confirmed directly in source.
- Task Context cannot persist cache; normal project graph still can.

### Concurrency and commit safety

- One mid-extraction change followed by stable retry.
- Two changes returning `CONTEXT_SOURCE_CHANGED_DURING_EXTRACTION`.
- Change during staging.
- Failure before views, between view replacements, and before facts commit.
- Previous snapshot remains authoritative on every aborted path.

### Contracts and safety

- Valid active approved contract.
- Conflict with approved contract.
- Draft, cancelled, stale, hash-corrupt, and foreign-task contracts.
- Traversal, absolute external path, external symlink, broken symlink, internal safe symlink, directory target, and Windows path canonicalization.
- Unknown Python script remains denied.
- Failed Task Context does not satisfy Graph-first discovery.

## Verification Strategy

After every phase:

1. Confirm only phase-owned files changed and preserve concurrent developer edits.
2. Run syntax validation for touched Python modules.
3. Run the smallest relevant selftest set.
4. Run `git diff --check`.
5. Continue only when the phase is green.

Final verification:

```powershell
python -m compileall -q harness_cli.py agents/scripts
python harness_cli.py selftest
git diff --check
python scripts_dev/validate_release.py <current-version>
```

Use the available Python executable when `python` is not on PATH. Do not run Android Gradle, assemble, ADB, device, or Android specialist reviewer flows against this repository.

## Acceptance Criteria

- Schema v2 remains compatible without forced refresh.
- Existing family IDs and preferred-family policies remain stable.
- Ambiguous existing-code work never falls back to preferred-new-code architecture.
- Advisory knowledge is deterministic, bounded, repository-relative, secret-free, and non-authoritative.
- Mixed languages, UI systems, presentation styles, modules, flavors, variants, and KMP source sets are resolved locally.
- Duplicate symbols and FQNs never select a first match silently.
- Persistent refresh is consistency-checked, explicit, full, and facts-last.
- Ordinary Task Context performs no persistent write.
- Stale/corrupt advisory or graph data falls back safely to targeted live evidence.
- Approved contracts remain authoritative and immutable from Task Context.
- Safety integration is narrow and does not weaken unknown-script or Graph-first controls.
- Warm narrow resolution demonstrates materially less deterministic work than full extraction.
- Complete Harness selftest, compileall, release validation, and diff check pass.

## Deliberately Deferred

- Automatic migration or modernization.
- Java architecture drift enforcement.
- Hard convention enforcement.
- LLM-generated project memory or architecture detection.
- Persistent partial snapshot mutation.
- Background watchers or automatic refresh.
- Transitive whole-graph context expansion.
- Changes to Android specialist reviewer prompts or routing.

## Rollback

Stop at the first failing phase boundary. Preserve developer files, notes, and policies. Revert only the phase-owned Project Intelligence changes through explicit patches. Never use `git reset`, `git checkout --`, stash, hidden commits, or automatic rollback. The previously committed context remains authoritative until a complete replacement commits successfully.
