# Android Architecture Guidelines & Layering

Setup overwrites this file from the target app (DI, navigation, ViewModel base). Until then, match the files you opened. Do not invent a stack that is not in the repo.

- Zero inline FQCNs. Import at the top. Typealias collisions (`as CoreState`, `as CoreAction`, `as CoreEvent`) when names clash.
- One-shot UI effects: never sticky `MutableLiveData` for navigate/dialog. Use `Channel`/`sendEvent()`, `SharedFlow`, or consume-to-null.
- Persistent errors live in UI state, not in a one-shot event.
- New network/data work follows the layers already used in this checkout (UseCase / Repository / whatever the opened files do).

## Mandatory Architectural KDoc Documentation Standard

Every newly created or refactored architectural layer MUST include clean, standard KDoc (`/** ... */`):
- **Repository Interfaces**: Document data contracts, caching policy, `@param`, and `@return [Result<T>]`.
- **Domain UseCases**: Document business responsibility and execution contract on `operator fun invoke(...)`.
- **ViewModels**: Document exposed `StateFlow` / `LiveData` contracts and one-shot navigation events.
- **DataSources / Remote APIs**: Document network endpoints, payload structures, and error handling.
