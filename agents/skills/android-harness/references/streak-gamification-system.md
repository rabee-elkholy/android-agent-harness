# Streak System & Gamification Engine Architecture

Authoritative guide for the daily Streak system, gamification milestones, and achievement event bus in Rashaqa Android.

---

## 1. Centralized Event Bus (`StreakEventManager`)
- **Architecture**:
  - `StreakEventManager` is a singleton event bus managing all achievement and streak UI events (`StreakEffect` subclasses).
  - Single source of truth: `StateFlow<StreakEventState>` (with `asLiveData()` for legacy Java/XML interop).
- **The 3-Step Lifecycle (CRITICAL)**:
  1. **Posting (Enqueue)**: When an activity completes (e.g. logging water, reaching step target, completing a run), enqueue the corresponding effect:
     ```kotlin
     StreakEventManager.enqueue(WaterFirstCupTodayEffect(cups = count))
     ```
  2. **Observing (UI)**: Central UI observers (in `MainActivity`, `SplashActivity`, or Compose host) collect the `state` flow.
  3. **Acknowledging (Consume)**: After the dialog or animation finishes displaying, the UI **MUST** call:
     ```kotlin
     streakEffect.acknowledge()
     ```
     This consumes the event from state, preventing infinite popup loops on screen re-entry.

---

## 2. Streak Categories & Triggers
- **Daily App Open**: `DailyStreakNormalEffect`, `DailyStreakWeeklyMilestoneEffect`, `DailyStreakLastDayFrozenEffect`.
- **Activity & Fitness**:
  - Steps: `DailyStepsTargetReachedEffect`.
  - Running: `RunningSessionTargetReachedEffect`.
  - Training: `CompletePlanTrainingEffect`, `Complete7MinTrainingEffect`.
- **Wellness & Tracking**:
  - Water: `WaterFirstCupTodayEffect`, `WaterLastCupTodayEffect`, `WaterLastCupAfterShortBreakEffect`.
  - Nutrition: `FoodFirstMealTodayEffect`, `FoodLastMealTodayEffect`.
  - Weight: `WeightGoalReachedEffect`, `WeightPositiveUpdateEffect`, `WeightNegativeUpdateEffect`.
- **Challenges & Social**:
  - `ChallengeJoinedEffect`, `ChallengeArchive50PercentEffect`, `ChallengeCompleteEffect`.

---

## 3. Persistence & App Lifecycle
- **Unshown Streaks**:
  - If a streak event occurs while the app is in the background or between navigation destinations, `StreakEventManager` serializes unshown streaks to `SharedPreferences` (`restoreUnshownStreaks()`).
  - Never drop pending streak rewards on process lifecycle changes.
- **Date & Timezone Calculations**:
  - Always base daily streak boundaries on `dateMilliseconds` with local calendar day calculation to prevent timezone jumping bugs.

---

## 4. Sound & Animation Sync
- `StreakSoundManager`: plays celebration sound effects (`streak_winner`, milestones).
- Animations: Lottie animations / Confetti (`com.github.jinatonic.confetti`).
- Ensure animation dismiss callbacks trigger `acknowledge()` reliably even if the user taps outside or presses Back.

---

## 5. Review Guard Rules for Streak System
- ❌ **NEVER trigger a streak event without an `acknowledge()` call in the UI layer**.
- ❌ **NEVER mutate `StreakEventState` directly from outside `StreakEventManager`**.
- ❌ **NEVER block the UI thread during streak state deserialization**.
