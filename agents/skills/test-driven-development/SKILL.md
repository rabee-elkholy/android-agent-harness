---
name: test-driven-development
description: Use when developing business logic, UseCases, Repositories, ViewModels, or reproducing and fixing bugs using strict Red-Green-Refactor cycles. Requires writing and proving a failing test before writing implementation code.
---

# Test-Driven Development (TDD) Skill

## 1. Core Principle: Red-Green-Refactor
Production code is only written in response to a failing test that defines its requirements or reproduces a defect.

---

## 2. Four-Phase TDD Protocol

### Phase 1: RED (Write the Failing Test)
- Author a concise, focused unit test in `src/test/java/.../*Test.kt`.
- Test names must clearly describe the scenario and expected outcome (e.g. `loginViewModel_invalidPassword_emitsValidationError()`).
- Capture both happy paths and boundary/error cases.

### Phase 2: PROVE FAILURE (Empirical Verification)
- Execute the targeted unit test task:
  ```bash
  python .agents/scripts/run_gradle_task.py :app:testDebugUnitTest --tests "com.package.FeatureTest.testName"
  ```
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
1. **Assertion Depth**: Every `@Test` method must have at least $\ge 2$ meaningful assertions (`assertEquals`, `assertTrue`, `assertNull`). Trivial checks (`assertTrue(true)`) are strictly prohibited.
2. **Coroutines & Turbine**: Use `runTest` with `StandardTestDispatcher` or `app.cash.turbine:turbine` for testing Flows and Channels.
3. **Mock Isolation**: Use pure Fakes or explicit `coEvery`/`every` definitions with `relaxed = false` for critical domain assertions. Never leak mock state across tests; reset in `@After`.
4. **Zero Placeholder Tests**: Never commit empty test stubs or `TODO()` test bodies.
