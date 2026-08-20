# Architecture & MVI Standards for Rashaqa

Rashaqa is a **hybrid** production app: most screens are Fragment + XML + ViewBinding. Newer screens are Compose + MVI. Match the surrounding pattern. Do not rewrite XML/payment to Compose/MVI unless the developer asks.

## 1. MVI Pattern (new screens only)
Base class: `com.madarsoft.core.common.bases.MVIViewModel<S : State, E : Event, A : Action>`

Effects go through `Channel` via `sendEvent()`. State via `setState {}` / `StateFlow`.

### Feature package layout (new Compose features)
```
features/featureName/
├── FeatureContract.kt      // State / Action / Event (not UiState naming)
├── FeatureViewModel.kt     // @HiltViewModel, extends MVIViewModel
├── FeatureFragment.kt      // BaseComposeFragment host, @AndroidEntryPoint
└── ui/
    └── FeatureScreen.kt
```
Reference: `features/home/homeFragment/` (`HomeContract.kt`, `HomeViewModel.kt`, `ui/HomeMviScreen.kt`) hosted in `BaseComposeFragment`.

## 2. ViewModel rules
- **New screens:** `MVIViewModel<S, E, A>`.
- **Existing screens:** keep the current parent (`ViewModel`, rarely others). Smallest fix.
- **Do not extend** `BaseViewModel` (god-object in `core.common.bases`; payment/steps logic lives there historically). Payment UI uses `PaymentViewModel : ViewModel` + `LiveData`, not MVI.
- **Do not use** `StateViewModel` for new work (sticky `LiveData` effects; consume-to-null exists as `onEffectConsumed()`).
- **One-shot UI effects:** never sticky `MutableLiveData` for launch/navigate/dialog. Use `sendEvent()`, `SharedFlow`, or consume-to-null (`value = null` after observe). This is the Google Pay re-entry class of bug.
- Coroutines: `viewModelScope` + `applicationExceptionHandler`.

## 3. Domain layer (new operations)
- New data loads from a ViewModel should go through a UseCase returning `ResultStates<T>` (`Success`, `Error`, `Loading`) in `com.madarsoft.fitness.domain.common` (declared in `Result.kt`).
- Existing payment/steps code often calls repositories from the ViewModel. Do not invent a UseCase layer while fixing those unless the change needs it.
- Domain should stay free of Android UI types when adding new UseCases.

## 4. UI error handling
- Persistent errors live in `UiState`. Do not use one-shot events for a lasting error screen.

## 5. Dependency injection
- Hilt: `@HiltAndroidApp` on `MyApplication`, `@HiltViewModel`, `@Inject constructor`.
- New Retrofit APIs: add to central `NetWorkModule` (`com.madarsoft.core.networks.NetWorkModule`). No per-feature network modules.

## 6. Clean Imports & No Inline FQCNs (Strict Clean Code Standard)
- **Zero Inline Fully Qualified Class Names**: Never write `com.madarsoft.core.common.bases.State` in class bodies or interface inheritance signatures.
- **Type Aliasing on Shadowed Names**: When declaring inner contract types (`State`, `Event`, `Action`), import base marker interfaces using clean typealiases:
  ```kotlin
  import com.madarsoft.core.common.bases.Action as CoreAction
  import com.madarsoft.core.common.bases.Event as CoreEvent
  import com.madarsoft.core.common.bases.State as CoreState

  class FeatureContract {
      @Immutable
      data class State(...) : CoreState

      sealed interface Action : CoreAction { ... }

      sealed interface Event : CoreEvent { ... }
  }
  ```
