---
name: android-harness
description: Use when working on Rashaqa Android architecture, MVI screens, Legacy XML, Compose theme, Streak/Gamification, Running/GPS Tracks, Ads/GDPR, Sensors/Services, Room DB migrations, Coroutines, or daily scenarios.
---

# Rashaqa Android Harness (Domain Knowledge Reference)

Comprehensive domain reference guides for the Rashaqa Fitness Android enterprise architecture.

---

## 📚 Domain Knowledge References

- [**Architecture & MVI Standards**](./references/architecture-mvi.md): `MVIViewModel`, Clean Architecture boundaries, `ResultStates`, Hilt DI, One-Shot UI Effects Rule.
- [**Ad Mediation & GDPR Privacy**](./references/ad-mediation-privacy.md): Google AdMob, Mediation networks, Google UMP 3.2.0, `:gdpr` module, Main-thread safety.
- [**Streak System & Gamification Engine**](./references/streak-gamification-system.md): `StreakEventManager`, `StreakEffect.acknowledge()` lifecycle, daily milestones, sound & confetti animations.
- [**Running, GPS Location & Virtual Tracks**](./references/running-routes-gps.md): `RunTrackingService`, FusedLocationProviderClient, Pace/Speed formulas, Polylines, Virtual Tracks.
- [**Pedometer Sensors & Background Services**](./references/steps-sensors-services.md): 24/7 background step counting, Android 14/15/16 foreground service types, battery optimizations, Health Connect.
- [**Room Database & Migrations**](./references/room-database-migrations.md): Zero Data Loss protocol, explicit Room migrations, EncryptedSharedPreferences.
- [**Payment Gateways Architecture**](./references/payment-gateways-architecture.md): Google Play Billing 8.3, RevenueCat 10.16, Fawry Pay, purchase acknowledgment.
- [**Performance & ANR Optimization**](./references/performance-anr-optimization.md): Main-thread safety, ANR prevention, 24/7 Sensor loops, WakeLocks, Compose recomposition stability.
- [**Jetpack Compose & Theme**](./references/ui-compose-theme.md): `MyAppTheme`, typography, colors, `@Preview`, Coil, `strings.xml`.
- [**Daily Work Scenarios & Protocols**](./references/daily-scenarios.md): Checkout-only facts (modules, no `:chat`, NetWorkModule). Domain rules stay in the files above.
- [**Automated Skills & Multi-Agents**](./references/automated-skills.md): Delivery gate is five parallel leaves (`bug-reviewer-agent`, `convention-reviewer-agent`, `security-reviewer-agent`, `perf-anr-guardian-agent`, `regression-impact-reviewer-agent`). On-demand: `qa-diagnostics-agent`, `android-ui-expert-agent`.

## Related Skills

- [**Kotlin Coroutines Expert**](../kotlin-coroutines-expert/SKILL.md): Structured concurrency, Flow streams, exception handling, and coroutine testing.
- [**Systematic Debugging**](../systematic-debugging/SKILL.md): Hypothesis-driven debugging for bugs and crashes.
- [**Compose Inspector**](../compose-inspector/SKILL.md): Recomposition safety, RTL/LTR, `@Immutable`, `remember`/`derivedStateOf`.
- [**Gradle Build Optimizer**](../gradle-build-optimizer/SKILL.md): Daemon reuse, dependency safety, Windows locks.
- [**Git PR Automator**](../git-pr-automator/SKILL.md): Conventional Commits, PR summaries for developer.
