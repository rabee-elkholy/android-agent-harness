# Performance, Threading & Optimization Guidelines

Peak performance, 60/120 FPS rendering, zero ANRs, and low battery consumption are the bar. Apply the rules below to **this** checkout. Do not assume sensors, GPS, or ads exist unless the code does.

---

## 1. Main Thread Protection & ANR Prevention

### Strict Threading Rules
- **Dispatchers.Main / UI Thread**: ONLY for UI updates, state emission, and lightweight view bindings.
- **Dispatchers.IO**: For disk I/O, Room database reads/writes, SharedPreferences/DataStore, Retrofit network requests, and file streaming.
- **Dispatchers.Default**: For CPU-intensive work (parsing, crypto, list transforms). Not for UI updates.

### Prohibited Patterns on Main Thread
1. **Never use `runBlocking`** in ViewModels, Activities, Fragments, Services, or BroadcastReceivers.
2. **Never call synchronous blocking methods** (`Future.get()`, `CountDownLatch.await()`, `Thread.sleep()`, `Process.waitFor()`) on the Main thread.
3. **Never execute Room queries synchronously** on Main thread (`allowMainThreadQueries()` is forbidden).
4. **Never perform large bitmap manipulation or decode** on the Main thread.

---

## 2. Sensors & background work (only if this checkout uses them)

### Sensor event loops
- `SensorEventListener.onSensorChanged()` is invoked on the registered thread (often Main or sensor thread).
- Keep `onSensorChanged()` execution under **1 millisecond**.
- Do NOT perform database writes or heavy math inside `onSensorChanged()`. Buffer events and process on `Dispatchers.Default` / `Dispatchers.IO`.
- Prefer `SENSOR_DELAY_NORMAL` for long-running listeners unless the opened code already uses a tighter rate.

### WakeLock Management
- Always use a timeout with `acquire()`:
  ```kotlin
  wakeLock.acquire(10 * 60 * 1000L) // 10 minutes max timeout
  ```
- Always release WakeLocks in a `finally` block or lifecycle teardown:
  ```kotlin
  try {
      // Background sync or tracking step
  } finally {
      if (wakeLock.isHeld) {
          wakeLock.release()
      }
  }
  ```

---

## 3. Location (only if this checkout tracks it)

- Throttle updates with realistic time/distance filters.
- Do not hold unbounded `Location` lists in memory; downsample before persist or draw.

---

## 4. Jetpack Compose Recomposition & Jank Optimization

### State Stability & Immutability
- Always annotate state data classes with `@Immutable` or `@Stable` from `androidx.compose.runtime`:
  ```kotlin
  @Immutable
  data class FeatureState(
      val items: List<ItemModel> = emptyList()
  )
  ```
- Use `ImmutableList` (from `kotlinx.collections.immutable`) or wrap `List<T>` to guarantee Compose compiler skips unnecessary recompositions.

### Allocations & Computations in Composables
- **Never allocate objects inside `@Composable` functions without `remember`**:
  ```kotlin
  // BAD: Creates new DateFormatter on every single frame recomposition
  val formatter = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())

  // GOOD:
  val formatter = remember { SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()) }
  ```
- **Use `derivedStateOf` for high-frequency state reads**:
  ```kotlin
  val showScrollToTop by remember {
      derivedStateOf { listState.firstVisibleItemIndex > 5 }
  }
  ```
- **Always provide `key` in `LazyColumn` / `LazyRow`**:
  ```kotlin
  items(items = state.tips, key = { it.id }) { item ->
      MotivationTipCard(item)
  }
  ```

---

## 5. Memory Leaks & Lifecycle Safety

### Fragment ViewBinding
- In XML Fragments, null out ViewBinding references in `onDestroyView()`:
  ```kotlin
  private var _binding: FragmentExampleBinding? = null
  private val binding get() = _binding!!

  override fun onDestroyView() {
      super.onDestroyView()
      _binding = null
  }
  ```

### Static & Long-Lived Context References
- Never hold strong references to `Activity` or `View` in singletons, companion objects, or static variables.
- Pass `ApplicationContext` to background singletons and repositories.

### Coroutines Scoping
- Bounded scopes only: `viewModelScope` in ViewModels, `viewLifecycleOwner.lifecycleScope` in Fragments.
- In Fragments, collect UI flows using `viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED)`.

---

## 6. Room Database & Indexing Optimization

- Add indices to foreign keys and columns frequently used in `WHERE`, `ORDER BY`, or `JOIN` queries (e.g. `date`, `day`, `timestamp`, `userId`):
  ```kotlin
  @Entity(tableName = "steps_table", indices = [Index(value = ["date"], unique = true)])
  data class StepsEntity(...)
  ```
- Use `@Transaction` for batch insertions or multi-step operations to minimize disk sync overhead.
- Use pagination (`PagingSource` / `Paging 3`) for large lists (e.g. historical workout logs, comments).
