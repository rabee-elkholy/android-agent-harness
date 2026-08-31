"""Scaffold a production-grade MVI feature for this Android app.

Usage: python .agents/scripts/new_feature_scaffold.py <feature_name> [--dest <path>]
Example: python .agents/scripts/new_feature_scaffold.py dailyMotivation
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _product import APPLICATION_ID, ANDROID_SRC  # noqa: E402
from _repo_files import REPO  # noqa: E402

enable_line_buffered_stdio()

def _default_features_dir() -> Path:
    kotlin_root = REPO.joinpath(*ANDROID_SRC, "kotlin")
    src_lang = "kotlin" if kotlin_root.is_dir() else "java"
    return REPO.joinpath(*ANDROID_SRC, src_lang, *APPLICATION_ID.split("."), "features")


FEATURES_DIR = _default_features_dir()
RES_DIR = REPO.joinpath(*ANDROID_SRC, "res")


def split_words(text: str) -> list[str]:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s)
    return [w for w in s.split() if w]


def to_pascal_case(text: str) -> str:
    return "".join(w.capitalize() for w in split_words(text))


def to_camel_case(text: str) -> str:
    words = split_words(text)
    if not words:
        return ""
    return words[0].lower() + "".join(w.capitalize() for w in words[1:])


def to_snake_case(text: str) -> str:
    return "_".join(w.lower() for w in split_words(text))


def assert_inside_repo(path: Path) -> Path:
    resolved = path.resolve()
    repo_resolved = REPO.resolve()
    if resolved != repo_resolved and repo_resolved not in resolved.parents:
        raise SystemExit(f"dest must be inside the repo: {repo_resolved}")
    return resolved


def fill(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, value in mapping.items():
        out = out.replace(key, value)
    return out


CONTRACT = """package __PACKAGE__

import androidx.compose.runtime.Immutable
import com.yourapp.core.common.bases.Action as CoreAction
import com.yourapp.core.common.bases.Event as CoreEvent
import com.yourapp.core.common.bases.State as CoreState

class __PASCAL__Contract {

    @Immutable
    data class State(
        val isLoading: Boolean = false,
        val isEmpty: Boolean = false,
        val errorMessage: String? = null,
        val isSuccess: Boolean = false
    ) : CoreState

    sealed interface Action : CoreAction {
        data object OnRefresh : Action
        data class OnItemClicked(val id: String) : Action
        data object OnBackClicked : Action
    }

    sealed interface Event : CoreEvent {
        data object NavigateBack : Event
    }
}
"""

VIEWMODEL = """package __PACKAGE__

import androidx.lifecycle.viewModelScope
import com.yourapp.core.common.bases.MVIViewModel
import com.yourapp.core.common.utils.applicationExceptionHandler
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class __PASCAL__ViewModel @Inject constructor(
    // Inject UseCases returning ResultStates here before review.
) : MVIViewModel<__PASCAL__Contract.State, __PASCAL__Contract.Event, __PASCAL__Contract.Action>() {

    override fun initialState(): __PASCAL__Contract.State = __PASCAL__Contract.State()

    override fun onAction(action: __PASCAL__Contract.Action) {
        when (action) {
            is __PASCAL__Contract.Action.OnRefresh -> loadData()
            is __PASCAL__Contract.Action.OnItemClicked -> handleItemClick(action.id)
            is __PASCAL__Contract.Action.OnBackClicked -> {
                viewModelScope.launch(applicationExceptionHandler) {
                    sendEvent(__PASCAL__Contract.Event.NavigateBack)
                }
            }
        }
    }

    private fun loadData() {
        setState { copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch(applicationExceptionHandler) {
            // Collect UseCase ResultStates.Success / Error / Loading. Do not swallow errors.
            setState { copy(isLoading = false) }
        }
    }

    private fun handleItemClick(id: String) {
        if (id.isBlank()) return
        // Map id to a domain action / navigation event. Do not hardcode user-facing text.
    }
}
"""

SCREEN = """package __PACKAGE__.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import __PACKAGE__.__PASCAL__Contract
import com.yourapp.core.ui.themes.MyAppTheme
import com.yourapp.app.R

@Composable
fun __PASCAL__Screen(
    state: __PASCAL__Contract.State,
    onAction: (__PASCAL__Contract.Action) -> Unit,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
    ) {
        when {
            state.isLoading -> {
                CircularProgressIndicator(modifier = Modifier.align(Alignment.Center))
            }
            state.errorMessage != null -> {
                Text(
                    text = state.errorMessage,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.align(Alignment.Center)
                )
            }
            state.isEmpty -> {
                Text(
                    text = stringResource(id = R.string.__SNAKE___empty),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onBackground,
                    modifier = Modifier.align(Alignment.Center)
                )
            }
            else -> {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 16.dp)
                ) {
                    Text(
                        text = stringResource(id = R.string.__SNAKE___title),
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onBackground
                    )
                }
            }
        }
    }
}

@Preview(name = "Arabic RTL - Content", locale = "ar", showBackground = true)
@Composable
private fun __PASCAL__ScreenArabicPreview() {
    MyAppTheme {
        __PASCAL__Screen(
            state = __PASCAL__Contract.State(isLoading = false, isSuccess = true),
            onAction = {}
        )
    }
}

@Preview(name = "English LTR - Content", locale = "en", showBackground = true)
@Composable
private fun __PASCAL__ScreenEnglishPreview() {
    MyAppTheme {
        __PASCAL__Screen(
            state = __PASCAL__Contract.State(isLoading = false, isSuccess = true),
            onAction = {}
        )
    }
}

@Preview(name = "Loading State", locale = "ar", showBackground = true)
@Composable
private fun __PASCAL__ScreenLoadingPreview() {
    MyAppTheme {
        __PASCAL__Screen(
            state = __PASCAL__Contract.State(isLoading = true),
            onAction = {}
        )
    }
}

@Preview(name = "Empty State", locale = "ar", showBackground = true)
@Composable
private fun __PASCAL__ScreenEmptyPreview() {
    MyAppTheme {
        __PASCAL__Screen(
            state = __PASCAL__Contract.State(isLoading = false, isEmpty = true),
            onAction = {}
        )
    }
}

@Preview(name = "Error State", locale = "ar", showBackground = true)
@Composable
private fun __PASCAL__ScreenErrorPreview() {
    MyAppTheme {
        __PASCAL__Screen(
            state = __PASCAL__Contract.State(isLoading = false, errorMessage = "preview"),
            onAction = {}
        )
    }
}
"""

FRAGMENT = """package __PACKAGE__

import android.os.Bundle
import android.view.View
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.fragment.app.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.yourapp.core.common.bases.BaseComposeFragment
import __PACKAGE__.ui.__PASCAL__Screen
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch

@AndroidEntryPoint
class __PASCAL__Fragment : BaseComposeFragment() {

    private val viewModel: __PASCAL__ViewModel by viewModels()

    override val uxcamScreenTag: String = "__PASCAL__"

    override fun trackOpenScreen() {
        // Screen open tracking
    }

    @Composable
    override fun ComposeContent() {
        val state by viewModel.state.collectAsStateWithLifecycle()
        __PASCAL__Screen(
            state = state,
            onAction = viewModel::onAction
        )
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        observeEvents()
    }

    private fun observeEvents() {
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.event.collect { event ->
                    when (event) {
                        is __PASCAL__Contract.Event.NavigateBack -> {
                            requireActivity().onBackPressedDispatcher.onBackPressed()
                        }
                    }
                }
            }
        }
    }
}
"""


def append_string_key(file_path: Path, name: str, value: str) -> None:
    if not file_path.is_file():
        return
    content = file_path.read_text(encoding="utf-8")
    if f'name="{name}"' in content or "</resources>" not in content:
        return
    entry = f'    <string name="{name}">{value}</string>\n'
    file_path.write_text(content.replace("</resources>", f"{entry}</resources>"), encoding="utf-8")


def scaffold_feature(feature_name: str, target_dir: Path | None = None) -> Path:
    camel = to_camel_case(feature_name)
    pascal = to_pascal_case(feature_name)
    snake = to_snake_case(feature_name)
    dest = assert_inside_repo(target_dir if target_dir else (FEATURES_DIR / camel))
    ui_dir = dest / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)

    mapping = {
        "__PACKAGE__": f"{APPLICATION_ID}.features.{camel}",
        "__PASCAL__": pascal,
        "__SNAKE__": snake,
    }

    (dest / f"{pascal}Contract.kt").write_text(fill(CONTRACT, mapping), encoding="utf-8")
    (dest / f"{pascal}ViewModel.kt").write_text(fill(VIEWMODEL, mapping), encoding="utf-8")
    (ui_dir / f"{pascal}Screen.kt").write_text(fill(SCREEN, mapping), encoding="utf-8")
    (dest / f"{pascal}Fragment.kt").write_text(fill(FRAGMENT, mapping), encoding="utf-8")

    append_string_key(RES_DIR / "values" / "strings.xml", f"{snake}_title", pascal)
    append_string_key(RES_DIR / "values-ar" / "strings.xml", f"{snake}_title", "Coming soon")
    append_string_key(RES_DIR / "values" / "strings.xml", f"{snake}_empty", "Nothing to show yet")
    append_string_key(RES_DIR / "values-ar" / "strings.xml", f"{snake}_empty", "Nothing to show yet")

    print(f"Scaffolded {pascal} feature at: {dest}")
    print("Next: wire UseCase + navigation, then run the 5-leaf review. Do not leave this scaffold as production behavior.")
    return dest


def main() -> None:
    print(
        "new_feature_scaffold.py is disabled. Templates exist only so selftest can "
        "read VIEWMODEL/SCREEN. Do not generate files from this script. Write new "
        "screens in this app's real packages."
    )
    raise SystemExit(0)


if __name__ == "__main__":
    main()
