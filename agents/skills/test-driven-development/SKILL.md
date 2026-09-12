---
name: test-driven-development
description: Use when developing business logic, UseCases, Repositories, ViewModels, or reproducing and fixing bugs using strict Red-Green-Refactor cycles. Requires writing and proving a failing test before writing implementation code.
version: 1.1.0
kernel-major: 1
---

# Test-Driven Development (TDD) Skill

## 1. Core Principle: Red-Green-Refactor
Production code is only written in response to a failing test that defines its requirements or reproduces a defect with a meaningful seam. For untestable UI/platform configs or when empirical reproduction is genuinely bounded (`EVIDENCE_LIMITED`), document evidence and risk boundaries rather than fabricating artificial test stubs.

---

## 2. Four-Phase TDD Protocol

### Phase 1: RED (Write the Failing Test)
- Author a concise, focused test in the owning module's existing test source set, using its configured runner.
- Test names must clearly describe the scenario and expected outcome (e.g. `loginViewModel_invalidPassword_emitsValidationError()`).
- Capture both happy paths and boundary/error cases.

### Phase 2: PROVE FAILURE (Empirical Verification)
- Resolve the exact module/variant test task from project configuration, then execute it through `python .agents/scripts/run_gradle_task.py`. Use a test filter only if that task supports it; do not assume `:app`, debug, or a JVM source set.
- Verify that the test fails **for the expected assertion reason** (not due to a compilation failure or configuration error).

### Phase 3: GREEN (Minimal Implementation)
- Write the minimal amount of production code required to make the failing test pass.
- Re-run the targeted test to verify `BUILD SUCCESSFUL` and test pass.

### Phase 4: REFACTOR & HARDEN
- Improve code readability, remove duplication, and extract reusable helpers.
- Ensure strict adherence to Shift-Left Quality Invariants:
  1. Single-source `StateFlow` unidirectional data flow.
  2. Zero inline FQCNs.
  3. Zero synchronous I/O on `Dispatchers.Main`.
  4. Proper Coroutine cancellation and dispatcher handling (`StandardTestDispatcher` with `advanceUntilIdle()`).

---

## 3. Test Quality Invariants (Mandatory for Pre-Review Gate)
1. **Assertion Quality**: Assert on observable state, return values, or side-effects with meaningful assertions (`assertEquals`, `assertTrue`, `assertNull`). Trivial tautologies (`assertTrue(true)`) are strictly prohibited.
2. **Coroutines & Turbine**: Use `runTest` with `StandardTestDispatcher` or `app.cash.turbine:turbine` for testing Flows and Channels.
3. **Mock Isolation**: Use pure Fakes or explicit `coEvery`/`every` definitions with `relaxed = false` for critical domain assertions. Never leak mock state across tests; reset in `@After`.
4. **Zero Placeholder Tests**: Never commit empty test stubs or `TODO()` test bodies.
5. **Test the Break**: State which plausible defect the test catches. Derive expected outcomes independently from the requirement or a reviewed fixture, never by calling or copying the implementation under test. Assert behavior rather than source-text fragments unless text itself is the public contract.
6. **Positive Neighbor**: Pair a rejection regression with a nearby valid case when a guard could otherwise reject everything. Check the intended rejection reason so an import, setup, or unrelated validation failure cannot make the test pass. Do not impose an assertion-count quota.
