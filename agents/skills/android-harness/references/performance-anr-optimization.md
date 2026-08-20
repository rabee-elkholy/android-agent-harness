# Performance & ANR Optimization Reference Guide for Rashaqa

Rashaqa is a high-demand fitness application featuring continuous 24/7 step tracking, GPS route tracing, realtime sensor processing, Jetpack Compose UI trees, and heavy ad mediation. Peak performance, 60/120 FPS rendering, zero ANRs, and low battery consumption are vital.

---

## 1. Main Thread Protection & ANR Prevention

### Strict Threading Rules
- **Dispatchers.Main / UI Thread**: ONLY for UI updates, state emission, and lightweight view bindings.
- **Dispatchers.IO**: For disk I/O, Room database reads/writes, SharedPreferences/DataStore, Retrofit network requests, and file streaming.
- **Dispatchers.Default**: For CPU-intensive tasks: GPS distance & pace formulas, Polyline simplification, JSON serialization/deserialization, cryptographic operations, and step count filtering algorithms.

### Prohibited Patterns on Main Thread
1. **Never use `runBlocking`** in ViewModels, Activities, Fragments, Services, or BroadcastReceivers.
2. **Never call synchronous blocking methods** (`Future.get()`, `CountDownLatch.await()`, `Thread.sleep()`, `Process.waitFor()`) on the Main thread.
3. **Never execute Room queries synchronously** on Main thread (`allowMainThreadQueries()` is forbidden).
4. **Never perform large bitmap manipulation or decode** on the Main thread.

---

## 2. 24/7 Sensor Processing & Background Services

### Pedometer & Sensor Event Loops
- `SensorEventListener.onSensorChanged()` is invoked on the registered thread (often Main or sensor thread).
- **Rule**: Keep `onSensorChanged()` execution under **1 millisecond**.
- Do NOT perform database writes or calculations inside `onSensorChanged()`. Buffer raw sensor events and dispatch processing asynchronously via Coroutines to `Dispatchers.Default` / `Dispatchers.IO`.
- Use appropriate sampling rates: `SensorManager.SENSOR_DELAY_NORMAL` (200,000 µs) for background pedometer tracking to conserve battery.

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

## 3. GPS Running & Route Tracking Performance

### `RunTrackingService` Best Practices
- **Location Throttling**: Configure location updates with realistic distance and time filters (e.g. `interval = 3000ms`, `minDistance = 2.0m`).
- **Polyline Downsampling**: Downsample high-frequency GPS coordinate lists before persisting to Room or rendering on Google Maps to prevent memory bloat and UI freezing.
- **Memory Footprint**: Do not hold millions of raw `Location` objects in memory during marathon tracking; stream aggregations to disk.

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
