# Test Quality & Assertion Depth Guidelines

This reference defines the quality standards enforced by `test-quality-reviewer-agent` when auditing unit and UI tests (`*Test.kt`).

---

## 1. Core Principles

1. **Assertion Depth**:
   - Every test case must assert observable state, domain outcomes, or emitted events.
   - Avoid vacuous assertions (e.g. `assertNotNull(viewModel)` with zero subsequent state verification, or `assertTrue(true)`).
   - Verify both success and error state transitions (e.g. `State.Loading` -> `State.Success` / `State.Error`).

2. **Fakes over Fragile Mocks**:
   - Prefer in-memory fakes for repositories and data sources over deeply chained `Mockito.when()` or `every {}` stubs.
   - When mocking is necessary, verify strict argument matching and avoid ignoring unexpected invocations.

---

## 2. Kotlin Coroutines & Flow Testing

1. **`runTest` & TestDispatchers**:
   - Always wrap coroutine tests in `runTest` from `kotlinx-coroutines-test`.
   - Inject `StandardTestDispatcher` or `UnconfinedTestDispatcher` into ViewModels, UseCases, and Repositories rather than hardcoding `Dispatchers.IO` or `Dispatchers.Default`.
   - Use `advanceUntilIdle()` or `runCurrent()` to deterministically process pending coroutine queues.

2. **Testing Reactive Streams with Turbine**:
   - Use the `Turbine` library (`flow.test { ... }`) to verify emissions in order:
     ```kotlin
     viewModel.uiState.test {
         assertEquals(DashboardUiState.Loading, awaitItem())
         viewModel.handleIntent(DashboardIntent.Refresh)
         assertEquals(DashboardUiState.Success(expectedData), awaitItem())
         cancelAndIgnoreRemainingEvents()
     }
     ```

---

## 3. Room Database & Repository Testing

1. **In-Memory Database**:
   - Use `Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).allowMainThreadQueries().build()`.
   - Close the database in `@After` / `tearDown()`.

2. **Entity & Migration Verification**:
   - Test DAO CRUD operations, conflict strategies (`OnConflictStrategy.REPLACE`), and transactional integrity.
   - Verify migration steps using `MigrationTestHelper`.

---

## 4. Jetpack Compose UI Testing

1. **Semantics & Test Tags**:
   - Use `composeTestRule.onNodeWithTag("tag_name")` or `onNodeWithText("...")` to verify screen elements.
   - Verify user interaction flows: `performClick()`, `performTextInput()`, and `performScrollTo()`.
