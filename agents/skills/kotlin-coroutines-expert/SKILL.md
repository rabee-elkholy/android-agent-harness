---
name: kotlin-coroutines-expert
description: "Expert patterns for Kotlin Coroutines and Flow, covering structured concurrency, error handling, and testing in Rashaqa Android."
---

# Kotlin Coroutines Expert

## Overview
Authoritative guide for asynchronous programming, reactive data streams, and cancellation/exception safety in Rashaqa Android.

---

## 1. Structured Concurrency
- Always launch coroutines within a defined `CoroutineScope` (e.g., `viewModelScope` with `applicationExceptionHandler`).
- Use `coroutineScope` or `supervisorScope` to group concurrent tasks.
- **Never use `GlobalScope`** (causes memory leaks and uncontrollable lifetimes).

```kotlin
suspend fun loadDashboardData(): DashboardData = supervisorScope {
    val userDeferred = async { userRepo.getUser() }
    val stepsDeferred = async { stepsRepo.getTodaySteps() }
    
    DashboardData(
        user = userDeferred.await(),
        steps = stepsDeferred.await()
    )
}
```

---

## 2. Exception & Cancellation Safety
- Top-level scopes should use `CoroutineExceptionHandler`.
- Never swallow `CancellationException` — if caught, rethrow it to allow proper cancellation propagation.
- For network calls, catch specific domain exceptions (`IOException`, `HttpException`) instead of a generic empty `catch (e: Exception)`.

---

## 3. Reactive Streams (Flow & StateFlow)
- Expose read-only `StateFlow<T>` or `SharedFlow<T>` from ViewModels; keep `MutableStateFlow` private.
- For One-Shot UI events (navigation, toast, dialog), use `Channel<Event>` with `receiveAsFlow()` or `SharedFlow<Event>(replay = 0)`. **Never use sticky MutableLiveData**.
- Use `flowOn(Dispatchers.IO)` for heavy data transformations before collecting on the Main thread.

---

## 4. Testing Coroutines
- Use `runTest` from `kotlinx-coroutines-test`.
- Inject `TestDispatcher` (e.g. `StandardTestDispatcher` or `UnconfinedTestDispatcher`) into ViewModels/UseCases instead of hardcoding `Dispatchers.IO`.
