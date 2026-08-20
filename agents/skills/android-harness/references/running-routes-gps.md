# Running, GPS Location Tracking & Virtual Tracks Architecture

Authoritative guide for GPS location tracking, running workouts, real-time pace/speed calculations, polylines, and Virtual Tracks in Rashaqa Android.

---

## 1. Foreground Location Service (`RunTrackingService`)
- **Android 14/15/16 Foreground Types**:
  - Must declare `android:foregroundServiceType="location"` (and `"health"` / `"dataSync"`) in `AndroidManifest.xml`.
  - On API 34+, permissions `ACCESS_FINE_LOCATION` and `FOREGROUND_SERVICE_LOCATION` must be granted before calling `ServiceCompat.startForeground()`.
- **FusedLocationProviderClient Setup**:
  - Request priority: `Priority.PRIORITY_HIGH_ACCURACY`.
  - Dynamic intervals: ~2–5 seconds during active running, throttled during pause.
- **Location Drift & Jitter Filtering**:
  - Discard location points with poor accuracy (e.g. `location.accuracy > 25m`).
  - Filter out impossible speed jumps (e.g. `speed > 45 km/h` on foot) caused by GPS multipath reflections.

---

## 2. Metrics & Calculations
- **Distance**:
  - Calculate cumulative Euclidean / Haversine distance using `location.distanceTo(previousLocation)`.
- **Speed & Pace**:
  - **Speed**: In KM/H (`speedMps * 3.6f`). Maintain rolling averages (10s window) for stable UI display.
  - **Pace**: In Minutes/KM (`(1000f / speedMps) / 60f`). Handle divide-by-zero when paused or stationary.
- **Calories Burned**:
  - Calculated dynamically from user weight, pace, duration, and METs (Metabolic Equivalent of Task).
- **Audio Coach & Voice Cues**:
  - Use `AudioManager.requestAudioFocus()` before voice announcements (e.g. "Distance: 1 kilometer, Pace: 5:30").
  - Release audio focus immediately after audio playback completes.

---

## 3. Route Polyline & Virtual Tracks
- **Points Storage**:
  - Store GPS coordinates as `List<LatLng>` / `Point(lat, lng, timestamp, speed, altitude)`.
  - Downsample or encode polyline (`PolyUtil.encode`) before sending to backend API to prevent payload bloat.
- **Virtual Tracks (`virtualTracks` / `virtualTrackReview`)**:
  - Compares live runner location with pre-recorded track waypoints.
  - Calculate distance-to-track and checkpoint completion percentages.
- **Google Maps Integration**:
  - Support both `SupportMapFragment` (XML) and `maps-compose` (`com.google.maps.android:maps-compose`).
  - Update `Polyline` incrementally without re-instantiating the entire polyline object.

---

## 4. Lifecycle & Crash Recovery
- **Process Death Protection**:
  - Continuously write active session snapshots to Room / cache so if the OS kills the process during a marathon, the session can be recovered on relaunch.
- **Clean Session Termination**:
  - When stopping a workout: save workout to Room DB, trigger sync worker, remove location callbacks, stop foreground service, and release wake locks.

---

## 5. Review Guard Rules for Running & GPS
- ❌ **NEVER remove location permissions checks** before starting `RunTrackingService`.
- ❌ **NEVER block location callback thread** with synchronous disk writes or network calls.
- ❌ **NEVER perform heavy polyline calculations on the UI thread**.
