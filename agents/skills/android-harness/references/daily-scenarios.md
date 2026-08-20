# Daily Work Notes for Rashaqa

Follow `.agents/rules/harness-rules.md` for workflow. Domain details live in the sibling reference files — do not copy them here.

## Checkout facts (this file only)

- Package: `com.madarsoft.fitness`. Launcher: `SplashActivity`.
- Gradle modules: `:app`, `:base`, `:gdpr`, `:fat-burner`.
- Chat UI lives **inside** `:app` (`data.chat` / features). Do not add a `:chat` module (leftover `chat/build` may exist on disk).
- `resourceConfigurations` is `ar` + `en` only.
- Keep `:base` free of feature UI. No circular module deps.
- Daily APK: `app/build/outputs/apk/debug/app-debug.apk`.
- New Retrofit APIs go in central `NetWorkModule`. Bottom-up: Model → service → Repository → UseCase → ViewModel → UI. Existing payment/steps code may skip UseCase; do not invent a layer while fixing those.

## Where to read the rest

- Ads / UMP: `ad-mediation-privacy.md`
- Streak acknowledge: `streak-gamification-system.md`
- GPS / `RunTrackingService`: `running-routes-gps.md`
- Pedometer / FGS: `steps-sensors-services.md`
- Room: `room-database-migrations.md`
- Payments: `payment-gateways-architecture.md`
- Compose / theme: `ui-compose-theme.md`
- MVI layout: `architecture-mvi.md`
- Performance: `performance-anr-optimization.md` + `kotlin-coroutines-expert` + `compose-inspector`
- Gradle locks: `gradle-build-optimizer`
