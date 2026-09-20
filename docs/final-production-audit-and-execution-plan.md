# Final Production Audit and Deterministic Remediation Plan

> Baseline: `v1.0.54` at `38f27b21750549d8b0bf0673f0efba0e3e1dcaae`
>
> Audit date: 2026-09-20
>
> Intended executor: Antigravity or another coding agent working on the
> Android Agent Harness repository itself.

## Executor directive

Implement **only M1 through M8**, in order, in one focused pull request. The
requirements and acceptance tests in this document are the implementation
specification. Do not redesign the harness, add a framework, add runtime
dependencies, change the client-project approval model, invoke the Android
application reviewers, mutate a live tracker, publish a release, or implement
anything under **Deferred observations**.

If implementation reveals a direct contradiction in this specification, stop
and report the exact file, line, and contradiction. Do not invent a new product
decision. Ordinary technical details that preserve the behavior specified here
are in scope and do not require a new plan.

## Executive verdict

The harness is functionally strong and already useful on a real, large Android
repository. It is not yet a “freeze it and forget it” foundation because two
fail-closed guarantees have bypasses, release construction is not fully
reproducible, several operations can wait indefinitely, and the public package
page contains broken links and contradictory license text.

Internal audit score: **81/100 (strong, conditional production readiness)**.
This is a source-based engineering assessment, not a commit.show score. The
external commit.show audit was intentionally not run because this repository is
a CLI/scaffold rather than a deployed application and executing its external
`npx` package was unnecessary for this audit.

Production recommendation:

- Safe to continue controlled internal use on the current release.
- Complete M1-M8 before declaring the next release the long-lived public
  baseline.
- Do not remove the approval, evidence, lifecycle, or adaptive-review systems;
  they provide real value and are not the current source of instability.

## Evidence collected

### Repository and release health

- Worktree was clean on `main`; `HEAD`, `origin/main`, and `v1.0.54` pointed to
  the same commit at audit start.
- `python harness_cli.py selftest` passed all 18 suites.
- `python -m compileall -q harness_cli.py agents/scripts` passed.
- `python scripts_dev/validate_release.py` passed.
- `python -m pip check` reported no broken requirements.
- The final `main` CI, tag validation, and PyPI publication workflows for
  `v1.0.54` all succeeded.
- PyPI exposes both wheel and sdist through Trusted Publishing with provenance
  tied to the release commit.
- A tracked-file credential-pattern scan found no non-test secret candidate.
- GitHub secret scanning and push protection are enabled.

### Real-project probe

The probe used `E:\AndroidProjects\Fitness_Android` in read-only mode. It did
not run Gradle, ADB, reviewers, or modify the existing 12-file dirty worktree.

| Operation | Observed result |
|---|---:|
| Diff classifier | PASS, 2.185 s |
| Cold bounded file context | PASS, 2.034 s |
| Repeated bounded file context | PASS, 1.885 s |
| Files discovered and parsed | 2,704 |
| Graph nodes / edges | 3,960 / 14,956 |

The classifier produced `BUSINESS_LOGIC` plus `COMPOSE_UI` with `MEDIUM`
severity for the active campaign changes. The bounded resolver returned the
correct `CampaignDetailsViewModel` identity and a focused context. This is
evidence that Project Intelligence is fast enough to be beneficial rather than
an operational bottleneck on the target project.

### Scalability probe

The deterministic performance test passed on a synthetic repository containing
20,001 manifest files:

- manifest construction: 0.544 s;
- average policy decision: 1.277 ms;
- inventory completeness: exact;
- repeated policy output: deterministic.

Wall-clock values are observations, not fixed pass/fail budgets.

## Confirmed findings

### F1 — High: checksum verification accepts unlisted executable Python files

Evidence:

- `harness_cli.py:_verify_kit_checksums` validates every manifest entry but
  does not compare the manifest inventory with the actual executable payload.
- `agents/scripts/lifecycle.py:_validate_kit` and
  `agents/scripts/repair.py:_verify_kit` repeat the same behavior.
- `harness_cli.py:run_engine_script` and `agents/harness.py:_run` execute a
  Python file from `agents/scripts`. Python places that directory on
  `sys.path`, so an unlisted file such as `agents/scripts/json.py` can shadow a
  standard-library import before the target script performs its own checks.

Impact:

- A locally modified kit can pass the advertised release checksum check while
  still containing an additional import-shadowing payload.
- This does not turn the harness into an OS sandbox, but it is inside the
  harness's claimed kit-integrity boundary and must fail closed.

### F2 — High: Zoho mutations can bypass the mandatory idempotency key

Evidence:

- `agents/mcp/zoho_sprints/_idempotency.py:107-112` directly executes the
  mutation when `operation_id` is absent.
- `agents/mcp/zoho_sprints/server.py:117-122` adds the schema property but does
  not add it to each mutation tool's `required` list.
- The public rules and security documentation state that every Zoho write
  requires a stable operation identity.

Impact:

- A direct MCP caller, a rule-only host, or an integration bug can issue a
  non-idempotent write and duplicate a task, status update, description, or
  comment after an uncertain network result.
- The current behavior contradicts the documented safety contract.

### F3 — High: bootstrap and ADB helper subprocesses have no deadline

Evidence:

- Git provisioning at `harness_cli.py:165-184` and update fetch/checkout at
  `harness_cli.py:313-344` have no timeout and do not disable interactive Git
  credential prompts.
- Screenshot capture and fallback commands at
  `agents/scripts/capture_screen.py:37-65` have no timeout.
- Device enumeration at `agents/scripts/_repo_files.py:270-278` has no timeout.
- GitHub workflow jobs do not declare `timeout-minutes`.

Impact:

- DNS failure, a credential helper, a wedged ADB server, an offline device, or
  a stuck test can leave installation, update, device verification, or CI
  waiting until an external watchdog kills it.
- This is precisely the kind of edge case that makes a developer distrust and
  bypass a harness.

### F4 — Medium: public package metadata and README disagree about the license

Evidence:

- `LICENSE` is MIT.
- `CITATION.cff` declares MIT.
- PyPI detects MIT.
- `README.md` says “Apache License 2.0”.
- The latest package build logs warn that the TOML-table form of
  `project.license` is deprecated and must be migrated before 2027-02-18.

Impact:

- The contradiction creates avoidable legal ambiguity for an open-source user.
- A future setuptools version can turn the deprecation into a release failure.

### F5 — Medium: README navigation is broken on PyPI

Evidence:

- PyPI renders repository-relative targets such as `docs/quickstart.md` and
  `SECURITY.md` under `https://pypi.org/project/android-agent-harness/...`.
- Those targets return HTTP 404.
- PyPI renders the Mermaid source as a plain code block instead of a diagram.

Impact:

- The primary public package page looks incomplete and prevents a new user from
  reaching setup, security, compatibility, and recovery documentation.

### F6 — Medium: important setup and review preparation failures are silent

Evidence:

- `agents/scripts/lifecycle.py:_warm_project_graph` catches every exception and
  returns no status; install/update still print the step as complete and return
  `PASS`.
- `agents/scripts/pre_tool_safety.py:351-378` silently ignores failure while
  writing reviewer-dispatch receipts, then allows the reviewer dispatch.
- The later evidence gate can reject the result, after model calls and developer
  time have already been spent.

Impact:

- Installation may succeed with unexpectedly slow first-use context and no
  explanation.
- A review round can be paid for and then become unusable because its receipt
  was never persisted.

### F7 — Medium: the release build is only partially reproducible

Evidence:

- `.github/workflows/publish-pypi.yml` runs an unpinned
  `python -m pip install --upgrade pip`.
- It pins direct `build` and `twine` versions, but `python -m build` uses build
  isolation and resolves `setuptools>=68` from `pyproject.toml` at release time.
- The wheel lifecycle job already demonstrates a safer pattern: exact backend
  versions plus `--no-build-isolation`.

Impact:

- Identical source tags can produce artifacts with different build-tool
  versions.
- A newly released or compromised build backend can affect publishing without a
  source change.

## Mandatory implementation scope

### M1 — Enforce an exact executable-payload inventory

Files:

- `harness_cli.py`
- `agents/scripts/lifecycle.py`
- `agents/scripts/repair.py`
- `agents/scripts/_public_cli_selftest.py`
- `agents/scripts/_critical_safety_selftest.py`

Required behavior:

1. In all three kit-verification paths, enumerate actual files below `agents/`.
2. Ignore only:
   - `agents/release_checksums.json` itself;
   - any path containing `state`, `cache`, or `__pycache__` as a complete path
     component;
   - files ending in `.pyc` or `.pyo`.
3. Reject symlinks anywhere in the validated installable payload.
4. Require exact set equality between the actual payload and manifest keys.
5. The error must list at most the first ten missing or unexpected relative
   paths and state whether each set is missing or unexpected.
6. Continue validating every listed SHA-256 digest after inventory equality is
   established.
7. Do not import code from the candidate kit to perform this verification.

Regression tests:

- A valid kit passes.
- An extra `agents/scripts/json.py` fails before any engine script executes.
- An extra nested Python file fails.
- A missing manifest entry fails.
- A manifest entry with a missing file fails.
- State/cache/bytecode files remain ignored.
- A symlinked payload file fails on platforms that permit symlinks; skip only
  when the OS genuinely denies symlink creation.
- Bootstrap, lifecycle update, and repair all enforce the same inventory rule.

### M2 — Make Zoho idempotency non-optional

Files:

- `agents/mcp/zoho_sprints/_idempotency.py`
- `agents/mcp/zoho_sprints/server.py`
- `agents/scripts/_zoho_selftest.py`

No documentation wording change is required for M2: `README.md`,
`agents/rules/harness-rules.md`, `docs/compatibility-matrix.md`, and
`docs/tool-support.md` already describe `operation_id` as required. Keep that
wording unchanged.

Required behavior:

1. `execute_once` must raise a clear `RuntimeError` when `operation_id` is
   absent or blank. It must never call the supplied operation in that case.
2. Add `operation_id` to the JSON Schema `required` array for all four mutation
   tools:
   - `zoho_create_task`;
   - `zoho_update_task_status`;
   - `zoho_add_comment`;
   - `zoho_update_task_description`.
3. Keep read-only Zoho tools unchanged.
4. Keep the existing safe-character, length, content-hash, pending-outcome, and
   replay behavior unchanged.
5. Do not perform a live Zoho mutation during testing.

Regression tests:

- Missing and blank `operation_id` both fail and leave a mock operation call
  count at zero.
- Every mutation schema requires `operation_id`.
- Read-only schemas do not require it.
- Existing completed replay, content mismatch, unknown outcome, and terminal
  status tests continue to pass.

### M3 — Bound external processes and report timeouts precisely

Files:

- `harness_cli.py`
- `agents/scripts/capture_screen.py`
- `agents/scripts/_repo_files.py`
- `.github/workflows/ci.yml`
- `.github/workflows/release-check.yml`
- `.github/workflows/publish-pypi.yml`
- `agents/scripts/_public_cli_selftest.py`
- `agents/scripts/_adb_core_selftest.py`
- `agents/scripts/_release_safety_selftest.py`

Required behavior:

1. Git network fetches use a 120-second default timeout.
2. Local Git init/remote/checkout/symbolic-ref operations use a 30-second
   default timeout.
3. Set `GIT_TERMINAL_PROMPT=0` for automated bootstrap/update Git commands while
   preserving the caller's existing environment.
4. `adb devices` uses a 15-second timeout.
5. screenshot capture and pull use a 30-second timeout; remote cleanup uses a
   10-second timeout.
6. Catch `subprocess.TimeoutExpired` separately and emit a sanitized,
   actionable message naming the operation and timeout. Do not print command
   credentials or environment values.
7. Preserve existing fallback behavior: a timed-out direct screencap may try the
   bounded remote-file fallback; no path may wait forever.
8. Add workflow job limits:
   - full selftest: 35 minutes;
   - performance: 10 minutes;
   - wheel lifecycle: 15 minutes;
   - release metadata: 5 minutes;
   - tag release validation: 10 minutes;
   - PyPI build/upload: 20 minutes.
9. Do not add wall-clock performance assertions to functional tests.

Regression tests:

- Mocked Git fetch timeout exits non-zero with remediation text and preserves an
  existing valid kit.
- Mocked ADB enumeration timeout returns no device without traceback.
- Mocked direct screenshot timeout reaches the fallback.
- Mocked fallback timeout deletes a partial local screenshot and returns
  failure.
- Release validation rejects a workflow job missing its required
  `timeout-minutes` value.

### M4 — Correct license metadata and make README portable

Files:

- `README.md`
- `pyproject.toml`
- `scripts_dev/validate_release.py`
- `agents/scripts/_release_safety_selftest.py`
- `docs/assets/architecture-pipeline.svg`

Required behavior:

1. Keep MIT as the project license. Change the README license sentence to MIT.
2. Migrate package metadata to PEP 639-compatible form:
   - `project.license = "MIT"`;
   - `project.license-files = ["LICENSE"]`;
   - change the build-system requirement to `setuptools>=77`.
3. Add these exact entries under `[project.urls]` while retaining the existing
   `Homepage` and `Issues` entries:
   - `Source = "https://github.com/rabee-elkholy/android-agent-harness"`;
   - `Documentation = "https://github.com/rabee-elkholy/android-agent-harness/tree/main/docs"`;
   - `Changelog = "https://github.com/rabee-elkholy/android-agent-harness/blob/main/CHANGELOG.md"`;
   - `Security = "https://github.com/rabee-elkholy/android-agent-harness/blob/main/SECURITY.md"`.
4. Replace every repository-relative README link that PyPI cannot resolve with
   an absolute URL rooted at
   `https://github.com/rabee-elkholy/android-agent-harness/blob/main/`.
   Internal `#anchor` links remain relative.
5. Keep the installation prompt pinned to the exact release tag through the
   existing release-version machinery.
6. Replace the Mermaid-only pipeline with `docs/assets/architecture-pipeline.svg`
   and embed it using exactly
   `https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/main/docs/assets/architecture-pipeline.svg`.
   Change “OS Interceptor” in that SVG to “Host Safety Boundary”; the harness
   does not claim an OS sandbox. Remove the Mermaid fence after the SVG is in
   place.
7. Do not add marketing claims that are not covered by tests or the threat
   model.

Release validation additions:

- README, `LICENSE`, `CITATION.cff`, and `project.license` must all resolve to
  MIT.
- README repository-document links must be absolute `https://github.com/...`
  URLs; local anchors are allowed.
- The README must not contain a Mermaid fence unless it also provides a static
  image fallback that PyPI renders.
- Package metadata validation must complete without the deprecated license-table
  warning.

### M5 — Make lifecycle warm-up and reviewer receipt failures observable

Files:

- `agents/scripts/lifecycle.py`
- `agents/scripts/pre_tool_safety.py`
- lifecycle and hook selftests

Required behavior:

1. `_warm_project_graph` returns structured success/failure information instead
   of swallowing every exception.
2. A graph warm-up failure does **not** roll back an otherwise valid install or
   update. It must:
   - print one `[WARN]` line;
   - return `graph_cache_warmed: false` and a sanitized
     `graph_cache_warning` in the lifecycle result;
   - recommend exactly `python .agents/harness.py doctor --json`. Do not label
     `context refresh` as read-only because it updates local cache files.
3. Success returns `graph_cache_warmed: true` without a warning.
4. Reviewer-dispatch receipt creation is mandatory before allowing dispatch.
   If directory creation, package hashing, or receipt writing fails, emit a deny
   decision with reason code `REVIEW_RECEIPT_WRITE_FAILED` and return before the
   model call is made.
5. Use the existing atomic JSON writer for receipts. Do not leave a partially
   written JSON receipt.
6. Do not change reviewer selection, model budgets, or evidence binding.

Regression tests:

- Failed graph warm-up still returns lifecycle `PASS` plus the explicit warning
  fields.
- Successful warm-up returns `graph_cache_warmed: true`.
- Receipt write failure denies dispatch and does not return an allow decision.
- A successful dispatch still creates a receipt with matching task, run,
  reviewer, package digest, host, and receipt digest.

### M6 — Make the publish build reproducible within the existing toolchain

Files:

- `.github/workflows/publish-pypi.yml`
- `scripts_dev/validate_release.py`
- `agents/scripts/_release_safety_selftest.py`

Required behavior:

1. Remove `python -m pip install --upgrade pip` from the publish workflow.
2. Install exact direct build tools in one command:
   `build==1.6.0`, `twine==7.0.0`, `setuptools==80.9.0`, and `wheel==0.45.1`.
3. Build with `python -m build --no-isolation`.
4. Keep Trusted Publishing, the full-SHA publish action, tag/version alignment,
   CI requirement, tag-validation requirement, and Twine metadata check.
5. Extend release validation to reject:
   - an unpinned pip upgrade in the publish workflow;
   - missing exact versions for the four direct build tools;
   - a publish build that omits `--no-isolation`.
6. Do not add a runtime dependency.

### M7 — Add repository guardrails without inflating the runtime

Code changes:

1. Add explicit top-level `permissions: contents: read` to CI and release-check
   workflows even though the current repository default is read-only.
2. Keep the publish job's minimal explicit permissions unchanged.
3. Keep full-SHA action pinning and extend release validation so a future
   workflow cannot silently remove the explicit read-only permission.
4. Change the PyPI classifier from `Development Status :: 4 - Beta` to
   `Development Status :: 5 - Production/Stable` only after M1-M6 and the full
   acceptance suite pass. If any mandatory item is deferred, retain Beta.

Maintainer-owned GitHub settings after the code PR passes:

- Enable a ruleset or branch protection for `main` that blocks force pushes and
  deletion, requires pull requests, and requires the CI workflow before merge.
- Protect `v*` tags from deletion or update.
- Enable Dependabot security updates. The existing weekly Actions and pip
  version-update configuration should remain.
- Enable automatic deletion of merged head branches.

These GitHub settings are external mutations. The coding agent must report the
exact intended settings and obtain maintainer authorization before changing
them. Their absence must not be hidden by a code-only “PASS”.

### M8 — Remove completed plan artifacts without deleting runtime planning support

Delete exactly these two tracked, completed implementation artifacts:

- `implementation_plan.md`;
- `implementation_plan_vnext.md`.

Update `ROADMAP.md` so its opening archive note no longer points to
`implementation_plan_vnext.md`. Replace the current three-line note with:

```text
> Archive note: pre-v1 completion history below is retained for provenance.
> Current behavior is documented in `docs/architecture.md`, `docs/workflows.md`,
> and `docs/compatibility-matrix.md`.
```

Do **not** delete or rename any of the following; they are active product
features rather than stale plan artifacts:

- `agents/scripts/plan_authority.py`;
- `agents/skills/brainstorming/`;
- references to host-generated `implementation_plan.md` artifacts in templates,
  rules, tests, or changelog history;
- `ROADMAP.md`;
- this audit/remediation document.

Do not perform a broad filename-based cleanup in this pull request. No other
file deletion is authorized by M8. The two named files are historical,
completed repository-local plans; runtime support for plans created inside a
client Android project's host session must remain unchanged.

Regression validation:

- `python -c "from pathlib import Path; assert not Path('implementation_plan.md').exists() and not Path('implementation_plan_vnext.md').exists()"`
  exits zero;
- `rg -n "implementation_plan_vnext\.md" ROADMAP.md README.md` returns no
  output (the remediation report itself is intentionally excluded because it
  records the deleted filename as audit history);
- the hook and vNext selftests that cover host-generated plan artifacts still
  pass.

## Required acceptance sequence

Run in this order after all mandatory edits:

```text
python -m compileall -q harness_cli.py agents/scripts agents/mcp/zoho_sprints
python agents/scripts/_zoho_selftest.py
python agents/scripts/_critical_safety_selftest.py
python agents/scripts/_public_cli_selftest.py
python agents/scripts/_release_safety_selftest.py
python agents/scripts/_performance_selftest.py
python scripts_dev/validate_release.py
python harness_cli.py selftest
```

Then perform packaging in a temporary/owned directory using the same pinned
backend versions and `--no-isolation`. Run `twine check` on both the wheel and
sdist. Do not delete or overwrite user-owned build output.

CI acceptance:

- all configured Python 3.10-3.14 jobs pass;
- full selftest passes on Ubuntu, Windows, and macOS as configured;
- all three wheel lifecycle jobs pass;
- performance and release metadata jobs pass;
- no workflow exceeds its timeout;
- no test command reports zero executed tests when a test gate is required.

Final change-set acceptance:

- runtime code remains Python standard-library only;
- no Android Gradle or ADB gate is run against the harness repository;
- no Android application reviewer is invoked for this harness change;
- no live Zoho mutation occurs;
- no new secret or credential is committed;
- release checksum inventory is regenerated only after the final payload is
  frozen;
- documentation, rules, code, and tests describe the same behavior;
- changes remain unstaged unless the maintainer separately requests Git work;
- no tag, GitHub release, or PyPI publication occurs without an explicit
  maintainer request after CI is green.

## Deferred observations — do not implement in the M1-M8 pull request

These are real maintenance or efficiency concerns, but combining them with the
mandatory hardening would increase regression risk more than value.

### D1 — Large modules and duplicated invariants

The production code is approximately 26,900 lines. Notable modules include
`project_context.py`, `_graph_core.py`, `workflow.py`, `_adb_core.py`,
`lifecycle.py`, and `wizard/questions.py`, each near or above 1,000 lines.
Checksum and version validation are also duplicated across bootstrap,
lifecycle, and repair paths.

Decision: do not perform a broad module split now. After M1-M8, extract one
boundary at a time only when a behavior change already touches it. Preserve the
standalone bootstrap verifier; it must not import untrusted candidate-kit code.

### D2 — Broad exception handling

The non-test runtime contains many broad `except Exception` handlers. Several
are intentional compatibility or fail-closed boundaries, but silent handlers
make diagnostics inconsistent.

Decision: M5 fixes the two user-visible silent failures with the highest cost.
Do not mechanically replace every broad handler. Audit them by subsystem later
and classify each as fail-closed, best-effort-with-warning, or programming
error. Mechanical narrowing would be unsafe.

### D3 — Conservative UI micro classification

Pure Compose literal padding changes correctly use the micro lane. However, a
static local assignment such as `val spacing = 16.dp` is treated as non-visual,
and XML layout changes are never micro. This can route a harmless style edit to
reviewers, assemble, and device verification.

Decision: retain the conservative behavior for now. A safe XML/Compose
presentation parser needs a separately approved specification and a corpus of
real diffs. Do not weaken classification with a larger regex allowlist in the
hardening PR.

### D4 — CI duration

The full suite is repeated for every supported Python on Linux and on canonical
Windows/macOS runtimes. Windows full selftest has taken roughly 14 minutes. The
matrix is expensive, but it recently found a real Windows/WSL shell-selection
bug that narrower CI missed.

Decision: keep the current compatibility coverage. Add job deadlines in M3,
but do not replace full cross-platform testing with smoke tests until at least
one release cycle has stable per-suite timing and platform ownership data.

### D5 — Test reporting and coverage

The custom selftest runner gives deterministic progress and broad scenario
coverage, but it does not currently upload JUnit results or measure line/branch
coverage. Coverage would improve maintenance visibility, not runtime behavior.

Decision: defer. If added later, keep it a pinned development/CI dependency and
do not make the installed harness depend on it.

### D6 — Release cadence

The project has shipped many patch releases in a short period. Fast correction
is positive, but excessive public patch churn increases update fatigue and
makes the “stable baseline” hard to identify.

Decision: after the hardening release, collect non-critical fixes under an
`Unreleased` changelog section and publish only when release criteria are met.
Security, data-loss, and installation-blocking fixes remain immediate-release
exceptions. Do not encode an arbitrary calendar delay in code.

## What should remain unchanged

The following mechanisms are justified by observed value and should not be
removed as “over-engineering”:

- bounded file/symbol Project Intelligence;
- diff-scoped multi-surface classification;
- task-baseline isolation from unrelated dirty developer files;
- single explicit plan approval and direct execution of in-scope follow-ups;
- evidence binding to task, run, snapshot, change set, producer, and schema;
- transactional install/update/uninstall and recovery journals;
- Room, localization, test-attribution, artifact-set, and device-identity
  deterministic gates;
- no-review micro lane for eligible documentation/resource/presentation edits;
- two-reviewer standard lane and five-reviewer critical lane;
- independent reviews only for Android client-project changes selected by
  policy, not for changes to the harness repository itself;
- complete canonical Windows and macOS coverage;
- standard-library-only installed runtime;
- explicit non-claims that the harness is not an OS sandbox or remote
  attestation system.

## Definition of done

The remediation is complete only when:

1. M1-M8 requirements and regression tests are implemented.
2. Every command in the required acceptance sequence passes.
3. CI is green on the final commit across all configured jobs.
4. PyPI-targeted README links are validated and license metadata is consistent.
5. A candidate kit with an extra import-shadowing Python file is rejected.
6. No Zoho mutation can execute without `operation_id`.
7. All listed Git/ADB/workflow operations terminate within their configured
   deadline and return actionable failure output.
8. Install/update surface graph warm-up warnings without rolling back healthy
   installation state.
9. Reviewer dispatch is denied before spending a model call when its receipt
   cannot be persisted.
10. External GitHub settings are either applied with maintainer authorization or
    explicitly reported as the only remaining manual actions.
11. The two completed root implementation-plan artifacts are removed,
    `ROADMAP.md` points only to current documentation, and client-project plan
    generation remains covered by passing tests.
