# Pedometer Sensor & Foreground Services Architecture

Critical domain guide for 24/7 background step counting, sensors, and foreground services in Rashaqa Android.

---

## 1. Pedometer Sensor Pipeline
- **Sensor Types**:
  - `Sensor.TYPE_STEP_COUNTER`: Cumulative steps since last device reboot (hardware-managed, power-efficient). Preferred for daily totals.
  - `Sensor.TYPE_STEP_DETECTOR`: Generates an event per individual step.
- **Boot & Reset Handling**:
  - Always handle device reboot resets: when sensor count drops below previous offset, recalculate daily baseline.
- **Sensor Batching**:
  - Use `SensorManager.registerListener(..., maxReportLatencyUs)` to batch events and prevent CPU wakeups when screen is off.

---

## 2. Foreground Services & Android 14/15/16 Guidelines
- **Service Types**:
  - Must declare explicit `android:foregroundServiceType="health"` and/or `"dataSync"` / `"location"` in `AndroidManifest.xml`.
  - On Android 14+ (API 34+), permissions `FOREGROUND_SERVICE_HEALTH` and `FOREGROUND_SERVICE_DATA_SYNC` must be granted before calling `startForeground()`.
- **Notification Requirement**:
  - Foreground service notification must be persistent (`setOngoing(true)`), show updated step count, and use a dedicated `NotificationChannel` via `NotificationChannelManager`.
- **Battery Optimization**:
  - Instruct the user to disable OEM battery killing (`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`) via `BatteryOptimizationActivity`.

---

## 3. Health Connect & Google Fit Sync
- **Health Connect (`androidx.health.connect:connect-client:1.1.0`)**:
  - Check availability via `HealthConnectClient.getSdkStatus()`.
  - Always verify runtime permissions (`PermissionController.createRequestPermissionResultContract()`) before reading or writing `StepsRecord`, `WeightRecord`, `TotalCaloriesBurnedRecord`.
  - Use atomic batch insertions and avoid duplicate syncing by tracking record UUIDs.

---

## 4. Safety Guardrails for AI
- ❌ **NEVER** kill, clear data (`pm clear`), or unregister the sensor listener in background services during refactoring.
- ❌ **NEVER** perform database writes or heavy step calculation loops directly inside `onSensorChanged()` on the Main thread. Dispatch to `Dispatchers.Default` / `Dispatchers.IO`.
