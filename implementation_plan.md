---
ArtifactMetadata:
  UserFacing: true
  RequestFeedback: true
---

# Android Harness Reliability Improvement Plan

## Objective

Resolve the verified reliability gaps in the current `v0.27.23` harness without broad refactoring, new runtime dependencies, weakened safety gates, state-format breakage, or changes to Android application code.

The plan uses incremental, backward-compatible fixes. No implementation phase may begin until the previous phase is green, reviewed, committed by the developer, and explicitly authorized to continue.

## Current Evidence

- Repository state at planning time: clean working tree at `d86581e`.
- Current version: `0.27.23`.
- Thirteen local checks were exercised.
- Ten checks passed.
- `_hook_selftest.py`, `_environment_selftest.py`, and `preflight_check.py` failed.
- The preflight failure is downstream of the hook self-test failure.
- Release version alignment passes for `v0.27.23`, but it does not detect stale pinned URLs or documentation drift.

## Constraints

- Keep the current safety policy that rejects raw `gradlew` outside Antigravity self-healing.
- Keep five mandatory review leaves for production-only diffs and six leaves when test files are included.
- Preserve both existing review verdict spellings, `PASS` and `APPROVED`.
- Preserve existing JSON fields and add fields only when required for compatibility.
- Do not add third-party runtime dependencies.
- Do not add reviewers, services, databases, background workers, or new abstraction layers.
- Do not install, uninstall, clear, or mutate an Android device during this work.
- Keep network-dependent update behavior mocked in automated tests.
- Keep changes phase-local and independently reversible.

## Selected Approach

Use the minimal incremental option:

1. Repair the test oracle before changing production behavior.
2. Fix proven CLI and doctor correctness bugs with focused regression tests.
3. Remove duplicate preflight work through a fingerprinted, fail-closed cache contract.
4. Make release validation catch the documentation and supply-chain drift already observed.

Rejected approaches:

- Rewriting the self-test framework.
- Splitting the harness into packages or services.
- Replacing the current gate state machine.
- Adding a general-purpose test framework solely for these fixes.
- Increasing reviewer count or adding another review stage.

## Phase 1: Restore Deterministic Gate Health

### Scope

1. Update the post-review assemble-barrier tests in `agents/scripts/_hook_selftest.py` to invoke `run_gradle_task.py` instead of raw `gradlew.bat`.
2. Retain explicit tests proving that raw Gradle commands remain denied in Codex and other non-self-healing environments.
3. Make `agents/scripts/_environment_selftest.py` hermetic:
   - Isolate environment variables for every runtime-detection case.
   - Remove ambient `CODEX_*`, `CLAUDE_*`, `CURSOR_*`, and `ANTIGRAVITY_*` contamination where the case does not own them.
   - Use a temporary writable `ANTIGRAVITY_ARTIFACT_DIR` for render tests.
   - Restore the parent environment after each case.
4. Change subprocess assertions that currently raise immediately on failure into aggregated assertions only where this improves diagnostics without hiding a failure.
5. Add the standalone ADB-core and graph self-tests to CI so their regression coverage cannot be skipped.

### Non-regression checks

- Raw `gradlew` remains denied in Codex.
- Antigravity still returns the existing overwrite payload.
- A completed review still unlocks the wrapper-based assemble command.
- Strict evidence mode still rejects missing or mismatched evidence.
- All existing security tests remain unchanged and pass.

### Exit criteria

- `_hook_selftest.py`: exit `0`.
- `_environment_selftest.py`: exit `0` in Codex, standard terminals, and CI.
- `preflight_check.py`: exit `0` on the clean kit repository.
- No production safety rule is relaxed.

## Phase 2: Correct CLI Verification and Update Results

### Scope

1. Correct `android-harness verify` in `harness_cli.py`:
   - Accept verdict records with either `PASS` or `APPROVED`.
   - Require the five canonical leaves for production-only diffs.
   - Require the five canonical leaves plus `test_quality` for test/mock diffs.
   - Recognize existing canonical names and aliases without accepting unknown leaves.
   - Verify the expected pass token for every required leaf.
   - Preserve package-path containment, package hashing, file hashing, and evidence validation.
2. Add round-trip tests using records produced through `record_review.py`, rather than hand-written records only.
3. Add explicit cases for:
   - Five-leaf `PASS`.
   - Five-leaf `APPROVED`.
   - Six-leaf test diff.
   - Missing `TEST_PASS` on a test diff.
   - Unknown or duplicate leaf aliases.
   - Modified and missing reviewed files.
4. Align the stale/incomplete exit code with the documented public contract by returning exit `2`, and lock it with a CLI test.
5. Correct `android-harness update`:
   - Capture the result of `install_or_update.py`.
   - Print success only when the result is zero.
   - Propagate a non-zero result unchanged.
   - Never claim that an app checkout was verified after a failed update.

### Compatibility controls

- Continue accepting old schema versions already supported by the CLI.
- Do not rename verdict fields or leaf keys.
- Do not change successful command output except where it currently reports a false success.
- Keep exit `0` for success and exit `1` for findings/configuration failures.

### Exit criteria

- A verdict generated by `record_review.py --approve-all` verifies successfully.
- A valid six-leaf test verdict verifies successfully.
- A five-leaf test verdict fails clearly.
- A failed update cannot print `SUCCESS` or return zero.
- Existing five-leaf production verdicts remain valid.

## Phase 3: Repair Device Diagnostics and Remove Duplicate Preflight Work

### Scope

1. Fix `HarnessDoctor.check_connected_devices()` to parse `proc.stdout.splitlines()` instead of referencing an undefined variable.
2. Add isolated subprocess tests for:
   - A single physical device.
   - A single emulator.
   - Multiple connected targets.
   - No device.
   - `adb` missing.
   - `adb devices` timeout or non-zero exit.
3. Keep device diagnostics read-only; only `adb devices` may be invoked by these checks.
4. Add the current working-tree fingerprint to the preflight gate artifact as an additive field.
5. Update `review_package.py` to reuse a prior preflight result only when all of the following match:
   - Status is `PASS`.
   - Git HEAD matches.
   - Working-tree fingerprint matches.
   - Required artifact schema fields are present.
6. If any preflight artifact condition is missing, corrupt, stale, or mismatched, run preflight normally and fail closed on errors.
7. Keep a CLI override for an intentional full re-run, used by tests and diagnostics.
8. Change the preflight success text from `ready for assembleDebug` to `ready for review packaging`; review remains mandatory before assemble.

### Side-effect controls

- No cache result may be reused based on Git HEAD alone.
- Documentation-only changes follow the existing fingerprint policy.
- Corrupt or future-schema artifacts never unlock review packaging.
- Cache reuse changes execution time only; it does not change pass/fail criteria.
- Existing artifact readers must ignore the added fingerprint field safely.

### Exit criteria

- Repeated preflight plus review packaging performs the expensive checks once for an unchanged tree.
- Any code or test modification invalidates the cached preflight result.
- Device discovery reports actual connected targets instead of converting the parser error into a warning.
- No device mutation command is introduced.

## Phase 4: Release and Documentation Drift Prevention

### Scope

1. Extend `scripts_dev/pin_prompt_docs.py` to cover every version-pinned file, including `docs/quickstart.md` and any versioned links in `README.md`.
2. Extend `scripts_dev/validate_release.py` to verify:
   - `agents/VERSION`, `pyproject.toml`, the release tag, and `CHANGELOG.md` agree.
   - Every pinned raw prompt URL uses the release version.
   - Prompt checksum headers are current.
   - The documented supported release line in `SECURITY.md` is current.
   - No stale fixed script count remains in release-critical documentation.
3. Update the architecture workflow diagram so preflight appears before review packaging and assemble remains after review.
4. Replace brittle documentation counts such as `34 core scripts` with wording derived from, or linked to, the canonical inventory.
5. Align CLI exit-code documentation with the tested contract.
6. Harden the publish workflow without affecting runtime:
   - Pin the PyPI publish action to an audited commit SHA.
   - Pin `build` and `twine` to reviewed versions.
   - Keep trusted publishing and the current minimal permissions.

### Exit criteria

- Release validation fails when any prompt URL points to an older version.
- Release validation fails on a stale or mismatched checksum.
- No document describes preflight as a post-review gate.
- No current documentation claims that only `v0.14.x` is supported.
- The publish workflow contains no floating action reference.

## Verification Matrix for Every Phase

Run the following checks after each phase, not only at the end:

1. `python agents/scripts/_hook_selftest.py`
2. `python agents/scripts/_security_selftest.py`
3. `python agents/scripts/_env_codes_selftest.py`
4. `python agents/scripts/_round_cap_selftest.py`
5. `python agents/scripts/_final_verdict_selftest.py`
6. `python agents/scripts/_baseline_selftest.py`
7. `python agents/scripts/_risk_and_impact_selftest.py`
8. `python agents/scripts/_adb_core_selftest.py`
9. `python agents/scripts/_apk_freshness_selftest.py`
10. `python agents/scripts/_environment_selftest.py`
11. `python agents/scripts/_graph_selftest.py`
12. `python agents/scripts/preflight_check.py`
13. `python scripts_dev/validate_release.py v<current-version>`
14. `python harness_cli.py version`
15. `python harness_cli.py doctor --json`

CI must run the supported Python matrix on Windows, Linux, and macOS. No phase is complete while any check is red.

Because this work changes test files, every implementation phase requires the five standard review leaves plus `test-quality-reviewer-agent` against the same review package.

## Phase Boundary and Rollback Policy

1. Complete only one phase at a time.
2. Generate one review package after the phase is green.
3. Complete the required six-leaf review for the exact package.
4. Present one phase milestone with test and review evidence.
5. Stop and wait for the developer to commit the phase.
6. Do not open or modify files belonging to the next phase until the developer explicitly authorizes it.
7. If a phase causes an unrelated regression, revert only that phase rather than compensating with additional architecture.

## Final Acceptance Criteria

- All automated checks pass on every supported OS and Python version.
- Preflight and review packaging remain fail-closed.
- Raw Gradle remains prohibited outside the existing Antigravity overwrite path.
- Both five-leaf and test-promoted six-leaf review records verify correctly.
- CLI update failures are propagated accurately.
- Device diagnostics are correct and read-only.
- Unchanged trees do not repeat preflight work.
- Changed trees cannot reuse stale preflight results.
- Release validation detects stale URLs, stale checksums, version drift, and workflow documentation drift.
- No new runtime dependency, Android permission, persistent service, or external network call is added.

