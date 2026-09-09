# Android Agent Harness Next Architecture Implementation Plan

Status: IMPLEMENTED LOCALLY — RELEASE ACCEPTANCE PENDING EXTERNAL MATRIX

## 1. Objective

Rebuild the harness around evidence-driven, risk-adaptive Android development so that cheaper and faster AI models can deliver higher-quality changes without imposing a heavy universal workflow.

The new system must:

- require explicit developer approval for every implementation plan before any project mutation;
- use deterministic evidence as the delivery authority;
- invoke only the tests, reviewers, builds, and device checks justified by the final change;
- remain conservative when a material classification is uncertain;
- work efficiently across the supported Android project matrix;
- avoid modifying application code, Gradle configuration, Git history, or host configuration during installation;
- use Python standard library, Git, Gradle Wrapper, and ADB only;
- add no daemon, database, server, background service, or mandatory runtime dependency.

## 2. Clean-Break Product Decision

The first installation of this architecture is a clean replacement for the legacy harness. Once the new architecture is installed, later compatible releases support safe in-place updates.

Decisions:

- Do not migrate legacy state, fingerprints, review ledgers, approvals, or gate artifacts.
- Do not implement dual-read or dual-write evidence schemas.
- Do not preserve legacy synthetic review commands.
- Do not preserve the current fixed five-reviewer workflow as a compatibility mode.
- Replace the legacy `install_or_update` behavior with explicit `install`, `update`, and safe `uninstall` lifecycles owned by the new architecture.
- Refuse installation over an existing harness checkout unless it has first been safely uninstalled.
- Document the release as requiring a clean reinstall.
- Support updates only from a previously installed new-architecture version with a valid ownership manifest.
- Preserve source-level features only when they remain valuable under the new architecture.

This deliberately removes migration complexity and prevents legacy evidence from being mistaken for new trusted evidence.

## 3. Supported Project Boundary

The phrase "any Android project" means any project inside the validated support matrix below. Unsupported shapes must fail clearly during discovery instead of installing a partially configured harness.

Supported:

- Gradle-based Android repositories with a Gradle Wrapper;
- Kotlin DSL and Groovy DSL;
- Kotlin, Java, or mixed source;
- single-module and multi-module repositories;
- one or multiple Android application modules;
- Android library-only repositories, with APK/device gates automatically unavailable;
- Jetpack Compose, XML Views, and hybrid UI;
- Android and Kotlin Multiplatform repositories with Android targets;
- feature modules and dynamic-feature modules;
- product flavors, multiple flavor dimensions, and custom build types;
- convention plugins, `buildSrc`, included builds, and version catalogs;
- Room and non-Room projects;
- localized, default-locale-only, and non-localized projects;
- Hilt, Dagger, Koin, manual dependency injection, or no DI framework;
- repositories with no unit tests or with known legacy test debt;
- Windows, macOS, and Linux;
- physical devices over USB or Wireless ADB, plus optional emulators by project policy;
- normal Git checkouts and Git worktree checkouts.

Explicitly unsupported in the first clean release:

- Bazel-, Buck-, or custom non-Gradle Android builds;
- automatic Wireless ADB pairing;
- Play Console publishing or release signing automation;
- remote approval servers;
- a claim of complete Kotlin semantic analysis;
- non-Git delivery evidence.

Discovery must report unsupported conditions without changing the client repository.

## 4. Non-Negotiable Developer Authority

### 4.1 Task lifecycle

Every mutating task follows:

```text
INTAKE
-> DISCOVERY
-> PLAN_DRAFTED
-> AWAITING_DEVELOPER_APPROVAL
-> IMPLEMENTING
-> VERIFYING
-> READY_FOR_DELIVERY or BLOCKED
-> DELIVERED
```

`RELEASING` is an optional later state entered only by an explicit release request.

### 4.2 Universal plan approval

- Analysis, explanation, diagnosis, and read-only review do not require a plan approval.
- Any file write, edit, deletion, external mutation, build installation, tracker mutation, Git mutation, or publication requires an approved plan.
- Micro changes still require a short plan and explicit approval.
- The plan depth adapts to task size; approval does not disappear.
- One approval authorizes the complete stated plan. Phase-by-phase approval is not required unless scope changes materially.
- Drafting or presenting a plan never starts implementation automatically; silence, continuation, or an unrelated reply is not approval.

### 4.3 Plan artifact

The plan artifact records:

- `plan_id`;
- `plan_sha256`;
- a unique non-reusable task/run identity;
- the approved base snapshot and Git worktree/branch identity;
- requested outcome;
- expected change surfaces;
- intended components/modules;
- expected files as advisory scope, not a brittle exact allowlist;
- test strategy;
- device strategy;
- known risks and rollback approach;
- status and approval provenance.

Mutation tools remain blocked while the plan is pending. A changed plan hash invalidates its approval.
An approval is single-task and cannot be replayed for another run, branch, worktree, or base snapshot. Cancellation revokes it. A material external change after approval returns the task to discovery and, when it changes scope or risk, requires a revised plan approval.

### 4.4 Reapproval triggers

Stop and request approval for a revised plan when implementation introduces:

- a new product behavior;
- a materially different technical approach;
- an unplanned module or architecture layer;
- a public API or contract change;
- Room schema work not present in the approved plan;
- Billing, authentication, security, cryptography, or sensitive-data work not present in the approved plan;
- an unplanned Manifest, permission, signing, or build-system change;
- a destructive operation;
- an external write or publication;
- materially broader blast radius.

Do not request reapproval for formatting, local renames, tests within the approved behavior, compile fixes, or reviewer fixes that remain inside the approved scope.

### 4.5 Approval trust

- Use a host-native user response proof when the host exposes one that the agent cannot synthesize.
- Otherwise record conversational approval as `RULE_ENFORCED`, without claiming cryptographic human separation.
- Require developer-terminal confirmation for sensitive final delivery when no host-bound proof exists.
- Never let an ordinary agent command manufacture `APPROVED_BY_DEVELOPER`.

### 4.6 Enforcement capability tiers

Do not claim identical enforcement across AI hosts with different interception capabilities. Discovery assigns and displays one tier:

- `HARD_ENFORCED`: host-native hooks or an equivalent boundary can deterministically intercept covered mutations;
- `RULE_ENFORCED`: the compact kernel and workflow rules apply, but the host cannot technically prevent every bypass;
- `UNSUPPORTED`: the minimum safe workflow cannot be established.

Sensitive delivery is unavailable in `UNSUPPORTED` mode. Documentation and final reports must state the active tier and its exact limitations. Adapters may not market rule-only compliance as an OS-level or cryptographic sandbox.

## 5. Canonical Delivery Manifest

Create one immutable manifest per candidate delivery.

### 5.1 Two distinct identities

The manifest contains two hashes with non-overlapping meanings:

1. `delivery_snapshot_sha256`
   - identity of the final delivery-relevant Android tree;
   - based on normalized path plus final content hash;
   - stable when the same content is committed;
   - unaffected by documentation-only changes.

2. `change_set_sha256`
   - identity of the reviewed change relative to the task base;
   - includes status, current path, old path for rename, and content hash;
   - covers added, modified, deleted, renamed, unmerged, and untracked files.

The delivery snapshot binds executable evidence. The change-set hash binds review coverage and diff-scoped checks.

### 5.2 Delivery-relevant files

Include, where present:

- Kotlin, Java, Groovy, and Kotlin scripts;
- all Android resource types and resource XML;
- Android manifests and navigation resources;
- Gradle settings, build files, properties that affect builds, version catalogs, and convention-plugin sources;
- ProGuard/R8 and consumer rules;
- Room schema JSON;
- AIDL, C/C++, JNI, and supported native build files;
- assets and raw resources included in application artifacts;
- application configuration proven to affect the build or runtime.

Exclude:

- documentation;
- IDE metadata;
- build outputs;
- logs and reports;
- harness state, caches, plans, and generated review packages;
- local secrets and machine-specific SDK paths.

### 5.3 Performance implementation

- Use `git ls-files -s -z` blob identities for unchanged tracked files.
- Hash only dirty and untracked delivery-relevant content from disk.
- Represent deletion with a tombstone.
- Normalize separators without lowercasing case-sensitive paths.
- Reuse the manifest across every gate; do not rescan independently.
- Never trust `mtime` as evidence identity.

## 6. Evidence Store and Schema

Store artifacts under:

```text
.agents/state/runs/<delivery_snapshot_sha256>/<run_id>/
```

Required properties:

- append-only run directories;
- atomic temporary write followed by replace;
- no global "latest result wins" authority;
- an optional latest pointer used only for display;
- artifact name, schema, producer, harness version, snapshot, change set, timestamps, status, and structured evidence;
- no raw secrets, complete environment dumps, or unredacted commands.

Core artifacts:

- plan and approval;
- delivery manifest;
- policy decision;
- unit-test result;
- preflight result;
- reviewer reports;
- assemble result;
- installable artifact-set identity;
- device installation result;
- device verification result;
- sensitive-delivery approval when required;
- final verdict.

Evidence files are local by default. Writers must use bounded paths, reject traversal through symlinks, redact secrets and likely personal data from commands/logs, and apply configurable retention without deleting active or referenced runs. Wall-clock timestamps are descriptive only; identity and freshness come from hashes and run relationships.

### 6.1 External build inputs

The canonical snapshot cannot silently claim reproducibility when the Android build consumes inputs outside normal Git delivery files. Discovery records a redacted external-input manifest for relevant items such as ignored build configuration, local AAR/JAR inputs, generated sources, SDK/JDK/Gradle/AGP identities, and service configuration files.

- Hash content when safe; otherwise record presence plus a non-secret identity and mark the limitation.
- Include Gradle Wrapper properties and binaries and all delivery-relevant binary resources.
- A changed required external input stales dependent evidence.
- A required but unidentifiable input produces `ENV_BLOCKED` or an explicit reproducibility limitation, never a false deterministic claim.

## 7. Read-Only Final Verifier

The final verifier must not run gates, mutate state, normalize missing evidence into PASS, or accept agent-authored verdict tokens.

It verifies:

- approved plan hash matches the executed plan;
- current delivery snapshot matches every required artifact;
- review artifacts also match the change set they covered;
- required gates match the stored policy decision;
- artifact producer and schema are valid;
- assemble target and variant match policy;
- installable artifact-set hashes match between assemble and install;
- device verification references the same install and artifact set;
- required reviewer coverage is complete;
- carried review coverage is still valid;
- sensitive final approval exists only when required and matches the final snapshot;
- emergency or unverified paths cannot produce a normal approval.

Final statuses:

- `APPROVED`;
- `BLOCKED`;
- `STALE`;
- `ENV_BLOCKED`;
- `PLAN_APPROVAL_REQUIRED`;
- `USER_DECISION_REQUIRED`;
- `EMERGENCY_UNVERIFIED`.

## 8. Change Surface and Risk Model

Use multi-label surfaces plus severity and confidence.

Example surfaces:

- `DOCS`;
- `LOCALIZATION`;
- `RESOURCE_UI`;
- `COMPOSE_UI`;
- `XML_UI`;
- `BUSINESS_LOGIC`;
- `PUBLIC_API`;
- `NETWORK`;
- `COROUTINES`;
- `PERSISTENCE`;
- `ROOM_SCHEMA`;
- `SENSITIVE_DATA`;
- `AUTH`;
- `BILLING`;
- `SECURITY`;
- `MANIFEST_PERMISSION`;
- `BUILD_CONFIG`;
- `NATIVE_CODE`;
- `DEVICE_API`;
- `TEST_ONLY`;
- `UNKNOWN`.

The result contains:

- surfaces;
- `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` severity;
- confidence;
- deterministic reason codes;
- files and symbols that triggered each surface.

Classification rules:

- deterministic paths and code patterns are primary;
- graph impact may promote surfaces but may not silently remove a deterministic surface;
- file count and changed LOC are secondary guards, not semantic proof;
- only material uncertainty that changes gates prompts the developer;
- uncertainty in an immaterial classification does not interrupt the task;
- the agent cannot manually lower severity or remove a detected surface.

## 9. Adaptive Evidence Policy

Create one central `review_policy.py`. No gate-routing rules may be duplicated in adapters or documentation.

### 9.1 Reviewer routing

| Surface | Required semantic review |
|---|---|
| Docs | None |
| Localization only | None by default; deterministic localization gate |
| Pure business logic | Bug + Regression |
| Compose/XML UI | Bug + Convention + Regression |
| Coroutines, Flow, I/O, lifecycle | Bug + Performance + Regression |
| Room schema | Bug + Regression; Security when sensitive data is affected |
| Manifest/permissions | Security + Convention + Regression |
| Gradle/dependencies | Convention + Security + Regression |
| Billing/Auth/Crypto/Security | Full five-reviewer set |
| Unknown material surface | Developer decision |
| Critical or broadly cross-cutting change | Full five-reviewer set |

Test Quality is added whenever test or mock behavior changes.

### 9.2 Later rounds

Round 2 and 3 require:

- reviewers that reported blocking findings;
- Regression review;
- any reviewer promoted by the fix delta;
- Test Quality if test behavior changed.

Carried evidence must record reviewer, source round, source snapshot, source change set, covered surfaces, and invalidation reason when removed.

### 9.3 Micro changes

Micro eligibility requires all of:

- only low-risk surfaces;
- no deletion or rename;
- no test behavior change;
- no Room, build, Manifest, permission, security, auth, billing, sensitive-data, or public-contract surface;
- bounded files and changed LOC;
- required deterministic gates passing.

The result is `REVIEW_NOT_REQUIRED_BY_POLICY`, never reviewer `PASS` and never an agent-issued waiver.

### 9.4 Review conflict, round, and cost policy

- Limit semantic review to three rounds per candidate delivery.
- After round three, any unresolved blocking finding returns `BLOCKED`; the harness never loops indefinitely.
- Conflicting reviewer findings are preserved and resolved by deterministic evidence where possible; otherwise they require a developer decision rather than majority voting.
- Configure an AI-call and model-cost budget per workflow.
- Do not silently escalate to a more expensive model. Escalation requires a pre-approved project policy or an explicit developer decision.
- Reviewer timeout, quota exhaustion, malformed output, or model unavailability is `ENV_BLOCKED` for a required review, never PASS.

## 10. Testing Policy

- Require plan approval before creating or modifying tests.
- Use Red-Green-Refactor for regressions and deterministic new behavior where a meaningful test seam exists.
- Do not require artificial tests for documentation, resources, mechanical renames, or non-testable configuration-only changes.
- Always run existing relevant tests selected from module and impact evidence.
- New testable business logic without meaningful tests is blocking.
- Legacy code without a practical seam records `TEST_SEAM_MISSING`; policy promotes review and runtime verification, and asks the developer only when delivery risk materially changes.
- Baseline tolerance applies only to the same test identity, failure category, and normalized failure signature.
- Compilation failures, test discovery failures, missing reports, and stale reports cannot be baseline-ignored.
- A successful Gradle exit with zero discovered/executed tests cannot satisfy a required test gate.
- Record selected task, task outcome, executed/skipped/failed counts, report identity, cache/up-to-date state, and retry history.
- Flaky-test retries are bounded and remain visible; a retry pass cannot erase the initial failure.

## 11. Android Deterministic Gates

### 11.1 Localization

- Consume configured/discovered locales rather than hardcoded languages.
- Support strings, plurals, and string arrays across multiple values XML files.
- Detect addition, modification, and deletion-only changes.
- Validate placeholder index, type, and compatible multiplicity.
- Preserve diff-scoped behavior so untouched legacy debt does not block delivery.
- Treat a default-locale-only project as valid.

### 11.2 Room

- Detect affected databases and transitive embedded/entity types.
- Compare the task base with final source.
- Validate the complete old-to-new migration path.
- Recognize manual and auto migrations.
- Locate migration declarations and `addMigrations` wiring across separate source files and DI modules.
- Reject destructive fallback for affected schema changes unless the approved product plan explicitly requires a destructive migration and final sensitive approval is present.
- Return `AMBIGUOUS` instead of PASS when static evidence cannot prove wiring.
- Do nothing in non-Room projects.

### 11.3 Baseline failures

Fingerprint:

```text
test identity + failure category + normalized stable message signature
```

Do not hash complete stack traces. Do not load legacy baseline evidence in the clean replacement.

### 11.4 Build and Manifest risk

- Evaluate sensitive patterns before generic resource classifications.
- Do not classify all `values/*.xml` as trivial strings.
- Treat themes, styles, attrs, resource aliases, network security, provider declarations, exported components, deep links, permissions, and Gradle plugin/dependency changes according to their actual surfaces.

## 12. Build, APK, and Device Chain

### 12.1 Assemble evidence

Record:

- delivery snapshot;
- Gradle task;
- application module;
- flavor and build type;
- resolved application id;
- installable artifact-set members and their SHA-256 values;
- the deterministic artifact-set SHA-256;
- command result and environment classification.

Never select the first globbed APK when multiple candidates exist. Resolve deterministically or ask during setup/discovery.

Treat installable output as an artifact set, not necessarily one file:

- record every base/split APK path and SHA-256 in deterministic order;
- bind install and verification evidence to the complete artifact-set hash;
- use `adb install-multiple` when the resolved variant produces split APKs;
- support dynamic-feature projects for static/build verification, but mark device verification unavailable when no deterministic installable APK set can be produced;
- keep AAB publication, bundletool provisioning, release signing, and Play delivery outside the first-release boundary.

### 12.2 Device evidence

Record separately:

- device selection;
- install;
- launch;
- automated E2E if configured;
- manual developer verification.

`start` alone is not installation evidence. A later start result cannot overwrite an earlier install failure.

Never automatically uninstall an existing package, clear application data, accept a signing mismatch, or force a downgrade. Any destructive device recovery requires a separately stated action in an approved plan and explicit developer confirmation. Record device user/profile and pre-existing package identity when they affect the result.

### 12.3 Device requirement

Require device verification for user-visible UI, navigation, lifecycle, permissions, device APIs, runtime integrations, significant Room migrations, Billing/Auth flows, and crash/ANR fixes.

Do not require it for proven pure logic, internal refactors, docs, or test-only changes unless project policy explicitly promotes it.

### 12.4 Emergency bypass

An explicit emergency install may exist for developer troubleshooting, but it must emit `EMERGENCY_UNVERIFIED` and can never satisfy delivery policy.

### 12.5 Wireless ADB

- Treat USB and Wireless ADB as the same physical-device pipeline.
- Use a shared device classifier with `ro.kernel.qemu` when serial heuristics are insufficient.
- Never own pairing, credentials, Wi-Fi settings, or reconnect loops.
- Retry a transient offline/disappearance failure once with a short bounded retry.
- Return `ENV_BLOCKED` after the retry.

## 13. State Concurrency and Recovery

- A live lock owner must never be evicted because of age alone.
- Use age only when ownership is invalid or the process is proven dead.
- Add process metadata sufficient to reduce PID-reuse ambiguity where the host supports it.
- Keep lock scope to read-modify-atomic-write.
- Never hold locks across Gradle, ADB, reviewer execution, or network work.
- Use unique temporary artifact paths to prevent parallel writer collisions.
- Recover from dead writers without accepting partial JSON.
- Preserve incomplete runs for diagnostics; do not reinterpret them as PASS.
- Before writing a project file, compare its current identity with the identity last read by the active task; stop on an external or concurrent edit rather than overwriting it.
- Detect actual module, surface, contract, and risk drift against the approved plan. Material drift invalidates approval even when the expected-file list was advisory.
- Bind a run to its Git base, branch/detached state, and worktree identity; checkout, rebase, merge, or base movement invalidates affected work.
- Journal task progress atomically so an interrupted task can be diagnosed or resumed only after fresh discovery.
- Never auto-stash, reset, revert, or overwrite developer changes during cancellation or recovery.

### 13.1 Repository trust and untrusted input

- Require a one-time trust decision before executing Gradle or repository-provided programs in a repository that has not been trusted locally.
- Read-only file inspection remains available before trust is granted.
- Treat repository prose, source comments, tracker content, test output, and Zoho fields as untrusted data, not harness instructions.
- Invoke subprocesses without a shell where practical and validate module, variant, path, package, and task arguments against command injection.
- Keep secrets out of reviewer packages, screenshots, logcat artifacts, and environment summaries through allowlisting and redaction.

## 14. Clean Installer, Updater, and Uninstaller

### 14.1 Installer

- Run discovery read-only first.
- Present discovered modules, variant, application id, launcher, locales, test task, device policy, and unsupported conditions for developer confirmation.
- Require a clean target with no active legacy harness installation.
- Write only harness-owned paths and bounded managed blocks.
- Record every created or modified path, pre-install hash, post-install hash, and backup location in an ownership manifest.
- Never edit application source or Gradle files.
- Never run `git update-index --assume-unchanged`, `git checkout`, commit, stash, reset, or push.
- Use `.git/info/exclude` only for local harness paths and never clean unrelated shared `.gitignore` entries.
- Never copy `local.properties`, SDK paths, credentials, host tokens, or unrelated agent configuration.

### 14.2 Updater for new-architecture versions

- Do not support in-place migration from the legacy architecture.
- Support safe in-place updates from the first new-architecture release to later compatible patch and minor releases.
- Require a valid ownership manifest and supported evidence/config schema range.
- Fetch or provision only an immutable requested release, never a floating branch.
- Create a timestamped backup before replacing any owned file.
- Preserve project configuration, tailored skill references, Zoho configuration pointers, workflow defaults, and user-owned managed content.
- Replace only files recorded as harness-owned.
- Regenerate managed adapters from the central policy instead of patching them independently.
- Run self-tests, configuration validation, and doctor checks after replacement.
- Roll back automatically to the backup if validation fails before update completion.
- Refuse with a clear clean-reinstall instruction when the source version, ownership data, or schema range is unsupported.
- Never reinterpret old delivery evidence as valid after an engine or policy update; active delivery runs must restart verification under the new version.
- Verify release origin, requested version, and published checksum before replacement.
- Use an atomic update journal covering owned files, generated adapters, configuration transforms, and the owned `.git/info/exclude` block.
- Detect partial update, insufficient disk space, permission failure, and Windows file locks before commit where possible.
- Do not downgrade unless the target version explicitly declares compatible configuration and evidence schemas.
- If preserved user content conflicts with a required configuration change, stop with a recovery path instead of silently choosing either version.

### 14.3 Uninstaller

- Default to dry-run preview.
- Remove only files still matching recorded harness-owned hashes.
- Remove only managed blocks, never entire mixed-ownership files.
- Preserve user-modified harness files in a timestamped recovery directory.
- Remove only the exact `.git/info/exclude` block owned by the harness.
- Never delete application files based only on filename patterns.
- Produce a final removal report and leave recoverable backups.

### 14.4 Legacy replacement boundary

- Updating from the legacy harness to this architecture is intentionally unsupported.
- The developer removes the legacy installation and installs the first new-architecture release cleanly.
- All later compatible new-architecture releases use the safe updater described above.
- A clean reinstall remains the documented recovery path if the updater itself is damaged.

## 15. Rule and Adapter Simplification

- Keep one concise canonical workflow document.
- Generate adapters from central configuration and policy summaries.
- Do not duplicate reviewer routing, risk rules, or gate matrices in every adapter.
- Replace absolute investigation file caps with evidence-based soft budgets.
- Permit revisiting files when new evidence justifies it.
- Keep graph-first discovery without making a failed graph lookup a blocker.
- Remove mandatory commit stops between approved phases.
- Keep milestone reporting without requiring developer interruption.
- Ask only about product behavior, material uncertainty, plan approval, sensitive delivery approval, or an unrecoverable blocker.

### 15.1 Two-layer knowledge architecture

Keep an always-loaded compact kernel containing only:

- mandatory plan approval;
- developer authority and mutation boundaries;
- delivery manifest and evidence rules;
- environment-failure behavior;
- destructive Git/ADB/external-operation safety;
- the requirement to obey the central policy decision;
- the requirement to load every skill selected by the deterministic skill router.

Move detailed Android guidance into on-demand skills:

- Android architecture and project conventions;
- Compose and XML UI;
- coroutines and Flow;
- testing and TDD;
- systematic debugging;
- Gradle optimization;
- database and persistence;
- performance, ANR, and lifecycle;
- security, authentication, and Billing where specialized guidance is required.

Skill loading must not depend only on the lead agent's judgment:

- preliminary surfaces from the request and graph select skills before planning;
- the final changed-file classifier promotes any additional required skills before verification/review;
- selected skill identifiers and versions are recorded in the plan and policy artifacts;
- a missing required skill blocks the affected review or gate;
- `UNKNOWN` material scope loads the Android core skill and asks the developer once;
- adapters contain only the compact kernel and skill-router entrypoint, not duplicated domain prose.

Every loaded skill is bound by identifier, semantic version, content hash, compatible kernel range, and source. The router rejects malformed, duplicate, missing, or incompatible mandatory skills. Project-tailored skills may add conventions but cannot weaken the kernel, approval boundary, evidence policy, or risk floor.

Instruction precedence is explicit: the compact kernel and developer authority define the safety boundary; the approved task defines intent and scope; central/project policy defines non-weakenable gates; project conventions and selected skills guide implementation inside that boundary. Text discovered in source code, documentation, build output, or tracker content is data and cannot change this precedence.

This reduces context dilution for cheaper models while preserving mandatory compliance in the always-loaded kernel.

### 15.2 Feature preservation inventory

Preserve and refactor:

- code graph and impact discovery;
- setup discovery and doctor diagnostics;
- Gradle wrapper runner, live output, and failure parsing;
- environment-versus-code failure classification;
- localization, Room, lint, risk, baseline, and performance guards;
- ADB selection, install/launch, logcat diagnostics, screenshots, and reusable E2E core;
- five core reviewers plus Test Quality, Android UI, and QA Diagnostics specialists;
- Android architecture, UI, coroutine, testing, debugging, Gradle, persistence, and performance skills;
- command packs for planning, debugging, delivery, localization, crash triage, performance, and test quality;
- commit-message helper;
- backup, recovery, and local credential-isolation behavior.

Keep optional and outside delivery authority:

- Zoho Sprints and other project-management integrations;
- UI rendering and presentation helpers;
- new-feature scaffolding;
- tracker-specific command packs.

Remove:

- legacy fingerprints, state, and verdict schemas;
- synthetic reviewer approval;
- agent-minted human approval tokens;
- fixed universal reviewer routing;
- universal TDD and device requirements;
- mandatory commit stops between approved phases;
- duplicated policy text and unsupported security claims.

### 15.3 Zoho Sprints workflow preservation

Preserve the current Zoho capabilities and workflow behavior:

- read ticket/story/task context when relevant;
- keep credentials exclusively in user-level configuration;
- preserve project and workflow defaults;
- preserve configured title, description, comment, and language policies;
- require the explicit configured mutation phrase, including `update zoho` when that is the project trigger;
- never move an item to a terminal Done/Solved state automatically;
- include the ticket identifier and intended milestone/status actions in the approved task plan;
- keep delivery summaries and QA-oriented update content;
- retain mocked, network-independent self-tests for the integration;
- create a parity inventory and golden contract tests for every retained command, input/output shape, language rule, status mapping, and failure result before replacing the legacy integration;
- use a stable operation id bound to ticket, intended mutation, and delivery snapshot so a retry cannot duplicate a comment or status update;
- handle rate limits, expired credentials, remote concurrent changes, missing/moved tickets, and custom workflow states without guessing;
- keep retries explicit and foreground-only; do not add a background synchronization daemon.

Zoho remains part of the developer workflow but never becomes delivery evidence:

- Zoho availability or synchronization failure cannot turn valid Android evidence into a failed delivery;
- a failed write records `PM_SYNC_PENDING` with a retry instruction;
- successful delivery does not imply Zoho was updated;
- the final response reminds the developer when a relevant Zoho update is still pending;
- explicit Zoho mutation authorization remains separate from Android delivery approval.

The first clean installation may require one-time Zoho project setup when legacy project-local configuration is intentionally not migrated. Existing valid user-level credentials are not deleted by legacy removal. Later compatible new-architecture updates preserve the validated Zoho configuration.

### 15.4 CI and headless behavior

CI is verification-only in the first release:

- it may run deterministic gates and verify an already approved, matching plan/evidence relationship;
- it cannot create developer approval, implement a plan, perform device-destructive recovery, publish, or mutate Zoho;
- missing interactive approval or required device/reviewer capability produces an explicit unavailable or blocked result;
- CI artifacts follow the same snapshot, redaction, retention, and schema rules as local artifacts.

## 16. Implementation Phases

### Phase 0: Freeze specification and build failing regression tests

- Convert the decisions in this plan into testable policy fixtures.
- Add regression tests for every confirmed bypass and stale-evidence scenario.
- Establish performance baselines before changing implementation.
- Produce no release from this phase.

Exit criteria:

- failing tests reproduce snapshot, synthetic review, approval, truncation, lock, APK-chain, deletion, rename, partial-path, and device overwrite defects;
- baseline timing captured on small, normal, and large fixtures.

### Phase 1: Repository model and delivery manifest

- Consolidate changed-file discovery.
- Implement delivery relevance.
- Implement stable delivery snapshot and reviewed change set.
- Add manifest serialization and validation.
- Remove old fingerprint authority.

Exit criteria:

- all manifest regression scenarios pass;
- commit-with-identical-content remains stable;
- documentation-only mutations do not stale delivery evidence;
- Android resource and build mutations do stale evidence.

### Phase 2: Evidence store and final verifier

- Implement run-scoped append-only evidence.
- Define artifact schemas and producer validation.
- Rewrite final verdict as a read-only verifier.
- Add atomic concurrency and crash-recovery tests.

Exit criteria:

- mismatched or missing artifact cannot approve;
- parallel artifact writes cannot lose evidence;
- incomplete writes remain blocked.

### Phase 3: Plan authority and review trust

- Add plan artifact/hash and pending-plan mutation barrier.
- Implement approval provenance accurately per host.
- Replace token-based review recording with structured report ingestion.
- Remove synthetic production approval paths.
- Block partial and truncated coverage.

Exit criteria:

- no mutating workflow starts before plan approval;
- changed plan requires approval again;
- no CLI command can manufacture reviewer or developer PASS;
- restricted reviewer coverage cannot produce full approval.
- approval replay, cancellation, branch/base movement, and material scope drift cannot preserve authorization.

### Phase 4: Android surface classifier and deterministic gates

- Implement surface/severity/confidence classification.
- Complete localization, Room, baseline, resource, Manifest, and risk behavior.
- Add decision prompting only for material uncertainty.

Exit criteria:

- support-matrix fixtures classify correctly;
- critical surfaces cannot be downgraded by generic rules;
- unsupported or ambiguous static analysis never returns a false PASS.

### Phase 5: Adaptive evidence and review policy

- Implement central gate/reviewer routing.
- Implement micro-change policy.
- Implement targeted later rounds and carried provenance.
- Implement conditional testing and device policy.

Exit criteria:

- normal tasks invoke fewer reviewers without missing required surfaces;
- unknown material changes ask once;
- fixes promote newly relevant reviewers;
- carried evidence invalidates correctly.

### Phase 6: Build, APK, and device chain

- Bind assemble, APK, install, launch, automated flow, and manual verification.
- Implement transport-neutral device selection and bounded retry.
- Separate emergency troubleshooting from delivery evidence.

Exit criteria:

- only the assembled APK can satisfy install evidence;
- only the installed APK can satisfy verification evidence;
- USB and Wireless ADB follow the same policy;
- emulator policy cannot be bypassed by serial format;
- split APK sets are hashed, installed, and verified as one immutable artifact identity;
- no device data is cleared and no installed package is removed without separate explicit confirmation.

### Phase 7: Clean installation and update lifecycle

- Implement read-only discovery, fresh installer, ownership manifest, safe new-architecture updater, and safe uninstaller.
- Remove legacy updater and migration code while retaining a clean-reinstall boundary from the legacy system.
- Preserve Zoho pointers, project configuration, tailored skills, and user-owned content across compatible updates.
- Verify zero application-code and Git-history mutation.

Exit criteria:

- install/update/uninstall/reinstall round trips are clean across platforms and path shapes;
- user-modified managed content is preserved;
- reinstallation starts from a clean state;
- partial updates recover safely, release checksums are verified, and unsupported downgrades are refused.

### Phase 8: Rule consolidation, compatibility validation, and release

- Generate concise adapters.
- Update documentation to match real enforcement tiers.
- Run full self-tests and performance suite.
- Validate representative real Android repositories.
- Publish only after every release gate passes.

## 17. Mandatory Regression Matrix

### Snapshot and Git

- same-path content mutation;
- added, deleted, renamed, untracked, and unmerged files;
- rename with content modification;
- documentation-only working change and commit;
- application change committed without content change;
- detached HEAD, shallow clone, worktree checkout, spaces, Unicode, and long Windows paths;
- symlinks and case-sensitive path distinctions;
- large repositories and large change sets.

### Planning and authority

- mutation before plan approval;
- plan modified after approval;
- technical fix inside approved scope;
- material scope expansion;
- forged conversational approval;
- missing host approval capability;
- sensitive final delivery approval and stale approval;
- replayed approval, cancelled task, changed base branch, rebase/checkout, concurrent developer edit, and material plan drift.

### Evidence and concurrency

- stale unit tests, preflight, review, build, install, and verification;
- mismatched snapshot/change set;
- corrupted, partial, duplicate, and unknown-schema artifacts;
- concurrent reviewers and gate writers;
- dead and live lock owners;
- PID reuse fallback;
- process interruption during atomic replace;
- ignored/external build input change, generated source change, symlink traversal attempt, secret redaction, and retention with an active referenced run.

### Android shapes

- Kotlin Compose single module;
- Groovy XML/Java application;
- hybrid Compose/XML;
- multi-module and dynamic feature;
- multiple application modules;
- KMP Android target;
- flavored application with multiple dimensions;
- convention plugins and included builds;
- library-only repository;
- no unit tests;
- no Room;
- Room migrations declared/wired in separate files;
- default locale only;
- multiple locales and split resource files;
- native/AIDL/ProGuard changes.

### Review policy

- micro eligible and every disqualifier;
- surface combinations;
- low-risk file containing a critical pattern;
- unknown material classification and single prompt behavior;
- full critical review;
- targeted second round;
- new surface promotion;
- carried coverage invalidation;
- test-quality promotion;
- conflicting reviewers, three-round cap, model timeout/quota failure, and unauthorized expensive-model escalation.

### Build and device

- multiple APK outputs;
- application-id suffix;
- stale APK with preserved or manipulated mtime;
- assemble/install hash mismatch;
- start without install;
- manual verification against another install;
- emergency force path;
- zero, one, and multiple devices;
- USB physical, Wireless physical, emulator, unauthorized, offline, disconnected, and reconnect-once cases;
- device serials containing colons that are not emulators;
- base plus split APK installation and artifact-set mismatch;
- signing mismatch, downgrade request, existing app data, alternate Android user/work profile, and attempted automatic uninstall/clear-data.

### Installer safety

- existing harness detected;
- dirty application repository;
- mixed-ownership AGENTS file;
- edited harness-owned file during uninstall;
- missing ownership manifest;
- interrupted install/uninstall;
- compatible patch/minor update and unsupported-version refusal;
- updater validation failure and automatic rollback;
- active evidence invalidation after an engine/policy update;
- preservation of tailored skills, project settings, and Zoho configuration pointers;
- `.git/info/exclude` containing unrelated user rules;
- client files with names resembling old harness scratch files;
- no network, no SDK, missing wrapper, and unsupported build system;
- tampered release checksum, interrupted update journal, disk-full state, permissions/file-lock failure, incompatible config merge, and unsupported downgrade.

### Skills, trust, CI, and Zoho

- missing, malformed, duplicate, modified, and kernel-incompatible skills;
- a project skill attempting to weaken approval or delivery rules;
- prompt-injection text in repository files, build output, and Zoho content;
- untrusted repository before its first Gradle execution;
- CI attempting to synthesize approval or perform an external mutation;
- Zoho retry without duplicate comment/status mutation;
- expired credentials, rate limiting, remote state conflict, unknown custom status, and first-install reconfiguration;
- golden parity coverage for all retained legacy Zoho behaviors.

## 18. Performance Budgets

Measure and enforce, excluding Gradle/ADB/AI latency:

- surface classification: target <= 300 ms for a normal change;
- manifest generation: reference target <= 1.25 seconds for 20,000 tracked files and 200 changed files;
- large manifest generation: target <= 2 seconds for 100,000 tracked files under the benchmark fixture;
- policy evaluation and final verification: target <= 150 ms each;
- no delivery-relevant file hashed more than once per manifest;
- no duplicate Git status, graph, or resource scan inside one verification run;
- bounded state size with explicit retention cleanup that never deletes active runs;
- zero additional Gradle invocations caused only by internal harness layering.

AI call targets:

- micro deterministic change: zero semantic reviewer calls;
- normal logic change: two or three reviewers;
- UI/runtime change: only surface-relevant reviewers;
- critical or broad change: full review set;
- later rounds: finding owners plus Regression and deterministic promotions.

These are targets, not marketing claims, until benchmark results are published.

Performance budgets are release-regression criteria measured on documented fixtures and reference environments. They do not fail a client task merely because its machine, antivirus, filesystem, or repository is slower; runtime tasks use bounded timeouts and report the measured cause.

## 19. Release Acceptance

Do not call the clean replacement production-ready until all are true:

- every mandatory regression scenario passes;
- CI passes on Windows, macOS, and Linux for supported Python versions;
- package build and metadata validation pass;
- clean install/update/uninstall/reinstall passes on all three operating systems;
- representative Compose, XML/Java, multi-module/flavored, and KMP projects pass;
- at least one real multi-module production Android project completes standard and sensitive task simulations;
- snapshot and policy performance stay inside budgets with no statistically material regression;
- no synthetic review or developer approval path exists;
- no evidence mismatch can produce `APPROVED`;
- no installer/uninstaller test mutates application code or Git history;
- host enforcement tiers are accurately detected and no rule-only host is advertised as hard-enforced;
- approval replay, concurrent edits, prompt injection, or malformed skills cannot bypass the kernel;
- external build inputs and split APK sets cannot silently escape snapshot identity;
- Zoho parity and idempotent retry contract tests pass;
- verification-only CI cannot synthesize approval or external mutations;
- documentation states enforcement and trust limitations accurately;
- local use demonstrates lower reviewer calls and lower developer interruption without reduced critical-task coverage.

## 20. Expected Outcome

The completed system should provide:

- mandatory developer approval before every implementation;
- fewer AI calls for normal work;
- no artificial TDD or universal device requirement;
- stronger Android-specific deterministic validation;
- exact tested/reviewed/built/installed snapshot integrity;
- full review and final human control for actual sensitive risk;
- clean installation into supported Android projects without application changes;
- safe failure for unsupported or ambiguous project shapes;
- a smaller, clearer rule surface that cheaper models can follow reliably.

Implementation was explicitly approved in the originating developer conversation.
The local candidate is complete; CI operating-system coverage, representative real
Android repositories, and physical-device validation remain release-acceptance
work and are not represented as locally proven.

## 21. Local Implementation Record

Implemented in the v1 candidate:

- approval-first task authority with agent-denied approval/cancellation commands;
- a separate final-snapshot approval for sensitive delivery;
- canonical delivery/change/external-input identities and append-only evidence;
- deterministic surface, skill, gate, reviewer, and device policy;
- narrowed later review rounds, carried-review validation, round caps, and model-call budgets;
- exact Gradle task, variant, application-id, root-module, KMP source-set, and split-APK handling;
- device-safe install/launch evidence without automatic uninstall, data clear,
  network changes, logcat clearing, or permission grants;
- transactional clean install, compatible update, rollback, dry-run uninstall,
  exact Git-local exclusions, and Zoho idempotency;
- diagnostic preflight that validates a fresh install without requiring a task
  approval or writing delivery evidence;
- offline regression suites and a declared three-OS/Python 3.10–3.13 CI matrix;
- a three-OS built-wheel lifecycle job covering clean install, doctor, compatible
  update, uninstall preview/apply, project-file preservation, and reinstall.

Local evidence does not substitute for the still-pending external release matrix:
hosted Windows/macOS CI, representative production Android builds, and a physical
device run must be green before changing the package classifier from Beta or
publishing/tagging v1.0.0.
