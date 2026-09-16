"""Project-derived architectural context engine and fact extraction library.

Zero-dependency standard library Python engine providing deterministic, evidence-backed
extraction of Android and KMP project architecture (DI, BaseViewModel, Navigation,
Persistence, Theming, Capabilities, Architecture Families). Renders reproducible
markdown views and computes normalized architectural fingerprints.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
EXTRACTOR_VERSION = "2.0.0"

SKIP_PARTS = {
    ".git", ".gradle", "build", ".harness-backup", ".harness-recovery",
    "node_modules", "__pycache__", ".idea", ".agents", "dist", "out",
}

TEST_AND_SAMPLE_PARTS = {
    "test", "androidtest", "testfixtures", "sharedtest", "instrumentationtest",
    "sample", "samples", "demo", "fixtures",
}

TECHNICAL_CAPABILITIES: dict[str, dict[str, tuple[str, ...]]] = {
    "networking": {
        "signatures": ("retrofit", "retrofit2", "io.ktor", "ktor-client", "okhttp3", "com.apollographql"),
    },
    "location": {
        "signatures": ("play-services-location", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "com.mapbox"),
    },
    "maps": {
        "signatures": ("play-services-maps", "com.google.android.gms.maps", "com.mapbox.maps"),
    },
    "sensors": {
        "signatures": ("SensorEventListener", "SensorManager", "TYPE_STEP_COUNTER", "TYPE_ACCELEROMETER", "TYPE_HEART_RATE"),
    },
    "health_connect": {
        "signatures": ("androidx.health.connect", "HealthConnectClient", "health-connect-client"),
    },
    "billing": {
        "signatures": ("com.android.billingclient", "billing-ktx", "com.stripe", "revenuecat"),
    },
    "audio": {
        "signatures": ("androidx.media3", "exoplayer", "SoundPool", "MediaPlayer"),
    },
    "camera": {
        "signatures": ("androidx.camera", "camera-camera2", "camera-lifecycle", "camera-view"),
    },
    "bluetooth": {
        "signatures": ("android.bluetooth", "BluetoothAdapter", "BluetoothDevice", "BluetoothGatt", "BLUETOOTH_CONNECT"),
    },
}


def _skip_path(path: Path, repo: Path) -> bool:
    try:
        rel = path.relative_to(repo)
        parts = set(rel.parts)
    except ValueError:
        return True
    return bool(parts & SKIP_PARTS)


def classify_source_path(rel_path: str) -> str:
    """Classifies a relative path into source categories:

    MAIN_SOURCE, TEST_SOURCE, SAMPLE_SOURCE, BUILD_CONFIG, MANIFEST.
    """
    norm = rel_path.replace("\\", "/").lower()
    parts = set(norm.split("/"))
    # Match Gradle test source sets: src/test/, src/testDebug/, src/androidTest/, src/androidTestDebug/, etc.
    if (
        parts & {"test", "testfixtures", "sharedtest", "androidtest", "instrumentationtest"}
        or re.search(r"/src/(?:test|androidtest|testfixtures|sharedtest|instrumentationtest)[^/]*/", f"/{norm}")
    ):
        return "TEST_SOURCE"
    if parts & {"sample", "samples", "demo", "fixtures"} or re.search(r"/(?:sample|samples|demo|fixtures)(?:/|$)", f"/{norm}"):
        return "SAMPLE_SOURCE"
    if norm.endswith("build.gradle") or norm.endswith("build.gradle.kts") or norm.endswith("libs.versions.toml") or norm.endswith("settings.gradle") or norm.endswith("settings.gradle.kts"):
        return "BUILD_CONFIG"
    if norm.endswith("androidmanifest.xml"):
        return "MANIFEST"
    return "MAIN_SOURCE"


def resolve_feature_scope(rel_path: str) -> str:
    """Deterministically resolves a feature/locality scope prefix from a relative file path.

    Precedence:
    1. Known module + explicit feature path (/feature/<name>/, /features/<name>/)
    2. Package/path locality under ui/<feature>, presentation/<feature>
    3. Screen / ViewModel sibling directory (parent directory)
    4. Module-level fallback
    """
    norm = rel_path.replace("\\", "/").strip("/")
    if not norm:
        return ""
    parts = norm.split("/")
    # 1. Feature module: feature/<name> or features/<name>
    if len(parts) >= 2 and parts[0].lower() in ("feature", "features"):
        return f"{parts[0]}/{parts[1]}"
    for i, part in enumerate(parts[:-1]):
        if part.lower() in ("feature", "features") and i + 1 < len(parts):
            return "/".join(parts[: i + 2])
    # 2. Package/path locality under ui/<feature> or presentation/<feature>
    for i, part in enumerate(parts[:-1]):
        if part.lower() in ("ui", "presentation") and i + 1 < len(parts) - 1:
            return "/".join(parts[: i + 2])
        elif part.lower() in ("ui", "presentation") and i > 0:
            return "/".join(parts[:i])
    # 3. Screen / ViewModel sibling directory (parent directory)
    if len(parts) > 1:
        return "/".join(parts[:-1])
    # 4. Module fallback
    return parts[0]


def parse_settings_modules(settings_text: str) -> list[str]:
    """Deterministically extracts module paths from settings.gradle / settings.gradle.kts.

    Supports:
      include(":app")
      include(":app", ":core", ":feature:home")
      include ":app", ":core"
      multiline include statements
    """
    clean_text = re.sub(r'//.*', '', settings_text)
    clean_text = re.sub(r'/\*.*?\*/', '', clean_text, flags=re.DOTALL)
    modules: list[str] = []
    for stmt in re.finditer(r'include\s*\(?([^;)\n]+(?:\n\s*[^;)\n]+)*)\)?', clean_text):
        block = stmt.group(1)
        for m in re.finditer(r'["\'](:[A-Za-z0-9_:\-\.]+)["\']', block):
            modules.append(m.group(1))
    return sorted(set(modules))


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rel_path(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.name


def _strip_comments_and_strings(text: str) -> str:
    """Strip //, /* */, and string literals from Kotlin code."""
    res: list[str] = []
    i = 0
    n = len(text)
    in_block = False
    in_triple = None
    while i < n:
        if in_block:
            end = text.find("*/", i)
            if end != -1:
                in_block = False
                i = end + 2
            else:
                break
        elif in_triple:
            end = text.find(in_triple, i)
            if end != -1:
                q_len = len(in_triple)
                in_triple = None
                i = end + q_len
            else:
                break
        elif text[i:i+2] == "/*":
            in_block = True
            i += 2
        elif text[i:i+2] == "//":
            end = text.find("\n", i)
            if end != -1:
                i = end
            else:
                break
        elif text[i:i+3] in ('"""', "'''"):
            in_triple = text[i:i+3]
            i += 3
        elif text[i] in ('"', "'"):
            q = text[i]
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == q:
                    i += 1
                    break
                if text[i] == "\n":
                    break
                i += 1
        else:
            res.append(text[i])
            i += 1
    return "".join(res)


def scan_viewmodel_declarations(text: str) -> list[tuple[str, str]]:
    """Deterministically scan for ViewModel class declarations and their base classes.
    Handles annotations, constructor injection, multiline declarations, generic classes/bases,
    and balanced parentheses.
    Returns list of (class_name, base_class_name).
    """
    clean = _strip_comments_and_strings(text)
    results: list[tuple[str, str]] = []
    class_iter = re.finditer(r"\bclass\s+([A-Za-z0-9_]+)", clean)
    for m in class_iter:
        cls_name = m.group(1)
        idx = m.end()
        n = len(clean)

        # Skip generic parameters on class: class Foo<T : Bar>
        while idx < n and clean[idx].isspace():
            idx += 1
        if idx < n and clean[idx] == '<':
            depth = 0
            while idx < n:
                if clean[idx] == '<':
                    depth += 1
                elif clean[idx] == '>':
                    depth -= 1
                    if depth == 0:
                        idx += 1
                        break
                idx += 1

        # Skip annotations, visibility modifiers, constructor keyword, and primary constructor parameters (...)
        while idx < n:
            while idx < n and clean[idx].isspace():
                idx += 1
            if idx >= n:
                break
            if clean[idx] == '@':
                idx += 1
                while idx < n and (clean[idx].isalnum() or clean[idx] in "._"):
                    idx += 1
                while idx < n and clean[idx].isspace():
                    idx += 1
                if idx < n and clean[idx] == '(':
                    p_depth = 0
                    while idx < n:
                        if clean[idx] == '(':
                            p_depth += 1
                        elif clean[idx] == ')':
                            p_depth -= 1
                            if p_depth == 0:
                                idx += 1
                                break
                        idx += 1
                continue
            if clean[idx:idx+11] == "constructor":
                idx += 11
                continue
            word_match = re.match(r"(?:internal|public|private|protected|actual|expect|open|sealed)\b", clean[idx:])
            if word_match:
                idx += len(word_match.group(0))
                continue
            if clean[idx] == '(':
                p_depth = 0
                while idx < n:
                    if clean[idx] == '(':
                        p_depth += 1
                    elif clean[idx] == ')':
                        p_depth -= 1
                        if p_depth == 0:
                            idx += 1
                            break
                    idx += 1
                continue
            break

        # Check for colon ':'
        while idx < n and clean[idx].isspace():
            idx += 1
        if idx < n and clean[idx] == ':':
            idx += 1
            while idx < n and clean[idx].isspace():
                idx += 1
            base_match = re.match(r"([A-Za-z0-9_.]+)", clean[idx:])
            if base_match:
                full_base = base_match.group(1)
                base_name = full_base.split(".")[-1]
                if cls_name.endswith("ViewModel") or base_name.endswith("ViewModel") or base_name == "ViewModel":
                    results.append((cls_name, base_name))
            elif cls_name.endswith("ViewModel"):
                results.append((cls_name, "ViewModel"))
        elif cls_name.endswith("ViewModel"):
            results.append((cls_name, "ViewModel"))
    return results


def resolve_feature_scope(rel_path: str) -> str:
    norm = rel_path.replace("\\", "/").strip("/")
    parts = norm.split("/")
    if not parts:
        return ""
    if len(parts) >= 2 and parts[0] in ("feature", "features"):
        return f"{parts[0]}/{parts[1]}"
    for i in range(len(parts) - 2):
        if parts[i] in ("feature", "features"):
            return "/".join(parts[:i+2])
    parent_dir = "/".join(parts[:-1]) if len(parts) > 1 else parts[0]
    parent_parts = parent_dir.split("/")
    for idx, p in enumerate(parent_parts):
        if p.lower() in ("ui", "presentation", "screens", "screen", "view", "views") and idx > 0:
            if idx + 1 < len(parent_parts):
                return "/".join(parent_parts[:idx+2])
            else:
                return "/".join(parent_parts[:idx])
    if len(parts) > 1:
        return "/".join(parts[:-1])
    return parts[0]


def extract_project_facts(repo: Path, *, in_memory_graph: bool = True, cache_dir: Path | None = None) -> dict:
    """Deterministically extracts architectural facts from repo with zero PII and zero secrets."""
    repo = repo.resolve()

    modules: list[str] = []
    for s_name in ("settings.gradle.kts", "settings.gradle"):
        s_path = repo / s_name
        if s_path.is_file():
            modules.extend(parse_settings_modules(_safe_read(s_path)))

    build_texts: dict[str, str] = {}
    for build_file in repo.glob("**/build.gradle*"):
        if not _skip_path(build_file, repo):
            rel = _rel_path(build_file, repo)
            build_texts[rel] = _safe_read(build_file)

    toml_text = ""
    toml_path = repo / "gradle" / "libs.versions.toml"
    if toml_path.is_file():
        toml_text = _safe_read(toml_path)

    corpus_gradle = "\n".join(build_texts.values()) + "\n" + toml_text

    # --- 1. DI Framework Detection (multi-framework aware) ---
    di_frameworks: list[str] = []
    di_evidence: list[dict] = []
    di_modules: list[dict] = []

    has_hilt = "dagger.hilt" in corpus_gradle or "hilt-android" in corpus_gradle or "com.google.dagger.hilt.android" in corpus_gradle
    has_koin = "org.koin" in corpus_gradle or "koin-android" in corpus_gradle
    has_anvil = "com.squareup.anvil" in corpus_gradle

    if has_hilt:
        di_frameworks.append("hilt")
        di_evidence.append({"type": "build_file", "evidence": "dagger.hilt / hilt-android dependency declared", "confidence": "HIGH"})
    if has_koin:
        di_frameworks.append("koin")
        di_evidence.append({"type": "build_file", "evidence": "koin-android dependency declared", "confidence": "HIGH"})
    if has_anvil:
        di_frameworks.append("anvil")
        di_evidence.append({"type": "build_file", "evidence": "anvil dependency declared", "confidence": "HIGH"})

    if len(di_frameworks) == 1:
        di_framework = di_frameworks[0]
    elif len(di_frameworks) > 1:
        di_framework = "multiple"
    else:
        di_framework = "unknown"

    # --- 2. Codebase Scan for Bases, Theme, and Modules ---
    vm_candidates: list[dict] = []
    room_databases: list[dict] = []
    room_daos: list[dict] = []
    datastore_preferences: list[dict] = []
    compose_themes: list[dict] = []
    result_wrappers: list[dict] = []
    nav_elements: list[dict] = []

    all_kt_files: list[tuple[str, Path, str]] = []
    for p in repo.rglob("*.kt"):
        if _skip_path(p, repo) or ".agents" in p.parts:
            continue
        rel = _rel_path(p, repo)
        kind = classify_source_path(rel)
        all_kt_files.append((rel, p, kind))
    all_kt_files.sort(key=lambda item: item[0])

    manifest_files: list[Path] = []
    for m in repo.glob("**/AndroidManifest.xml"):
        if not _skip_path(m, repo):
            rel = _rel_path(m, repo)
            if classify_source_path(rel) == "MANIFEST":
                manifest_files.append(m)

    # Capability scanning per-file (streaming, no 2000-char truncation, production only)
    matched_sigs_by_cap: dict[str, set[str]] = {cap: set() for cap in TECHNICAL_CAPABILITIES}

    def _scan_text_for_caps(text: str) -> None:
        if not text:
            return
        text_lower = text.lower()
        for cap_name, config in TECHNICAL_CAPABILITIES.items():
            for sig in config["signatures"]:
                if sig.lower() in text_lower:
                    matched_sigs_by_cap[cap_name].add(sig)

    _scan_text_for_caps(corpus_gradle)
    for m_path in manifest_files:
        _scan_text_for_caps(_safe_read(m_path))

    # Detailed production symbols
    discovered_screens: list[dict] = []
    discovered_viewmodels: list[dict] = []

    for rel, p, kind in all_kt_files:
        txt = _safe_read(p)
        if not txt:
            continue

        # Capabilities: scan full production text
        if kind == "MAIN_SOURCE":
            _scan_text_for_caps(txt)

        # Exclude tests/samples from production architecture facts
        if kind in ("TEST_SOURCE", "SAMPLE_SOURCE"):
            continue

        # DI Modules
        if ("hilt" in di_frameworks or di_framework == "hilt") and "@Module" in txt and ("@InstallIn" in txt or "@Provides" in txt or "@Binds" in txt):
            m_cls = re.search(r"(?:abstract\s+)?(?:class|object|interface)\s+([A-Za-z0-9_]+)", txt)
            if m_cls:
                di_modules.append({"name": m_cls.group(1), "path": rel, "framework": "hilt"})
        if ("koin" in di_frameworks or di_framework == "koin") and re.search(r"module\s*\{", txt):
            m_koin = re.search(r"val\s+([A-Za-z0-9_]+Module)\s*=", txt)
            if m_koin:
                di_modules.append({"name": m_koin.group(1), "path": rel, "framework": "koin"})

        # ViewModel Candidates
        m_vms = re.finditer(r"(?:abstract|open)\s+class\s+([A-Za-z0-9_]+)(<[^>]+>)?\s*:\s*(?:androidx\.lifecycle\.)?ViewModel\s*\([^)]*\)", txt)
        for m_vm in m_vms:
            cls_name = m_vm.group(1)
            generics = (m_vm.group(2) or "").strip()
            pkg_m = re.search(r"package\s+([a-zA-Z0-9_.]+)", txt)
            pkg = pkg_m.group(1) if pkg_m else ""
            vm_candidates.append({
                "symbol": cls_name,
                "package": pkg,
                "generics": generics,
                "path": rel,
            })

        # Concrete ViewModel detection for family resolution
        vm_decls = scan_viewmodel_declarations(txt)
        for vm_name, vm_base in vm_decls:
            has_stateflow = "StateFlow" in txt or "MutableStateFlow" in txt
            has_livedata = "LiveData" in txt or "MutableLiveData" in txt
            has_rx = any(rx in txt for rx in ("Observable<", "BehaviorSubject", "Flowable", "Single<"))
            has_flow = "Flow<" in txt or "SharedFlow" in txt

            state_stream = (
                "stateflow" if has_stateflow
                else "livedata" if has_livedata
                else "rxjava" if has_rx
                else "flow" if has_flow
                else "unknown"
            )

            # Unidirectional flow signals
            action_match = re.search(r"sealed\s+(?:class|interface)\s+([A-Za-z0-9_]*(?:Action|Intent|UiAction|UiIntent|Event|UiEvent))\b", txt)
            effect_match = re.search(r"sealed\s+(?:class|interface)\s+([A-Za-z0-9_]*(?:Effect|Event|UiEffect|UiEvent|SideEffect))\b", txt)
            has_action_handler = bool(re.search(r"fun\s+(?:onAction|handleAction|processIntent|dispatch|sendAction|onIntent|onEvent|handleEvent|processEvent)\s*\(", txt))

            # If contract not declared in same file, check companion contract files in the same directory
            if not action_match and p.parent.is_dir():
                try:
                    for sibling in p.parent.glob("*.kt"):
                        if sibling != p and any(k in sibling.stem.lower() for k in ("contract", "action", "intent", "event", "state")):
                            sib_txt = _safe_read(sibling)
                            if not action_match:
                                action_match = re.search(r"sealed\s+(?:class|interface)\s+([A-Za-z0-9_]*(?:Action|Intent|UiAction|UiIntent|Event|UiEvent))\b", sib_txt)
                            if not effect_match:
                                effect_match = re.search(r"sealed\s+(?:class|interface)\s+([A-Za-z0-9_]*(?:Effect|Event|UiEffect|UiEvent|SideEffect))\b", sib_txt)
                except Exception:
                    pass

            if has_stateflow and (action_match or has_action_handler):
                presentation_flow = "unidirectional"
                input_contract = action_match.group(1) if action_match else "UiAction"
                effect_contract = effect_match.group(1) if effect_match else "none"
            else:
                presentation_flow = "unknown"
                input_contract = "unknown"
                effect_contract = "unknown"

            # Domain boundary
            domain_boundary = "usecase" if ("UseCase" in txt or "Interactor" in txt) else "repository" if "Repository" in txt else "unknown"
            data_boundary = "repository" if "Repository" in txt else "datasource" if "DataSource" in txt else "dao" if "Dao" in txt else "unknown"
            di_type = "hilt" if ("@HiltViewModel" in txt or "@Inject" in txt) else "koin" if "viewModel(" in txt else (di_frameworks[0] if di_frameworks else "unknown")

            discovered_viewmodels.append({
                "name": vm_name,
                "base": vm_base,
                "path": rel,
                "state_stream": state_stream,
                "presentation_flow": presentation_flow,
                "input_contract": input_contract,
                "effect_contract": effect_contract,
                "domain_boundary": domain_boundary,
                "data_boundary": data_boundary,
                "di": di_type,
            })

        # Screen detection
        is_screen = False
        screen_name = ""
        screen_host = "unknown"
        ui_toolkit = "unknown"

        # Composable screen
        comp_match = re.search(r"@Composable\s+fun\s+([A-Za-z0-9_]+Screen|[A-Za-z0-9_]+Content)\s*\(", txt)
        if comp_match or (rel.endswith("Screen.kt") and "@Composable" in txt):
            is_screen = True
            screen_name = comp_match.group(1) if comp_match else p.stem
            screen_host = "composable"
            ui_toolkit = "compose"
        elif re.search(r"class\s+([A-Za-z0-9_]+)\s*:\s*(?:Fragment|BaseFragment)\b", txt):
            frag_match = re.search(r"class\s+([A-Za-z0-9_]+)\s*:\s*(?:Fragment|BaseFragment)\b", txt)
            is_screen = True
            screen_name = frag_match.group(1) if frag_match else p.stem
            screen_host = "fragment"
            ui_toolkit = "compose" if ("ComposeView" in txt or "setContent" in txt) else "xml"
        elif re.search(r"class\s+([A-Za-z0-9_]+)\s*:\s*(?:ComponentActivity|AppCompatActivity|Activity)\b", txt):
            act_match = re.search(r"class\s+([A-Za-z0-9_]+)\s*:\s*(?:ComponentActivity|AppCompatActivity|Activity)\b", txt)
            is_screen = True
            screen_name = act_match.group(1) if act_match else p.stem
            screen_host = "activity"
            ui_toolkit = "compose" if "setContent" in txt else "xml"

        if is_screen:
            # Check for navigation inside screen
            nav_type = (
                "compose_navigation" if ("NavHost" in txt or "rememberNavController" in txt or "composable<" in txt)
                else "xml_navigation" if "findNavController" in txt
                else "voyager" if "Voyager" in txt
                else "unknown"
            )
            discovered_screens.append({
                "name": screen_name,
                "path": rel,
                "screen_host": screen_host,
                "ui_toolkit": ui_toolkit,
                "nav_type": nav_type,
                "text": txt,
            })

        # Room Database
        if "@Database" in txt and "RoomDatabase" in txt:
            m_db = re.search(r"(?:abstract\s+)?class\s+([A-Za-z0-9_]+)\s*:\s*(?:androidx\.room\.)?RoomDatabase\s*\(\s*\)", txt)
            m_ver = re.search(r"@Database\s*\([^)]*version\s*=\s*(\d+)", txt)
            m_ent = re.search(r"@Database\s*\([^)]*entities\s*=\s*\[([^\]]+)\]", txt)
            db_name = m_db.group(1) if m_db else p.stem
            version = int(m_ver.group(1)) if m_ver else 1
            entities = [e.strip().replace("::class", "") for e in m_ent.group(1).split(",") if e.strip()] if m_ent else []
            room_databases.append({
                "symbol": db_name,
                "version": version,
                "entities_count": len(entities),
                "entities": sorted(entities),
                "path": rel,
            })

        # Room DAOs
        if "@Dao" in txt:
            m_dao = re.search(r"interface\s+([A-Za-z0-9_]+)", txt)
            if m_dao:
                room_daos.append({"symbol": m_dao.group(1), "path": rel})

        # DataStore Preferences
        if "preferencesDataStore" in txt or "DataStore<Preferences>" in txt:
            datastore_preferences.append({"file": rel})

        # Compose Theme
        m_theme = re.finditer(r"@Composable\s+fun\s+([A-Za-z0-9_]+Theme)\s*\(", txt)
        for th in m_theme:
            compose_themes.append({"symbol": th.group(1), "path": rel})

        # Result / Resource Wrappers
        m_res = re.search(r"sealed\s+(?:class|interface)\s+(Result|Resource|NetworkResult|ApiResponse|UiState)(<[^>]+>)?", txt)
        if m_res:
            result_wrappers.append({"symbol": m_res.group(1), "path": rel})

        # Navigation
        if "NavHost" in txt or "rememberNavController" in txt or "composable<" in txt or "NavGraphBuilder" in txt:
            nav_elements.append({"type": "compose_nav", "path": rel})
        elif "Voyager" in txt or "Navigator(" in txt:
            nav_elements.append({"type": "voyager", "path": rel})

    # XML Navigation graphs
    for nav_xml in repo.glob("**/res/navigation/*.xml"):
        if not _skip_path(nav_xml, repo):
            rel_xml = _rel_path(nav_xml, repo)
            if classify_source_path(rel_xml) == "MAIN_SOURCE":
                nav_elements.append({"type": "xml_nav_graph", "path": rel_xml})

    # UI Framework classification (legacy summary)
    has_compose = "androidx.compose" in corpus_gradle or bool(compose_themes) or any(s.get("ui_toolkit") == "compose" for s in discovered_screens)
    has_xml_views = any(s.get("ui_toolkit") == "xml" for s in discovered_screens) or any(
        not _skip_path(xml_p, repo) and classify_source_path(_rel_path(xml_p, repo)) == "MAIN_SOURCE"
        for xml_p in repo.glob("**/res/layout/*.xml")
    )
    if has_compose and has_xml_views:
        ui_framework = "hybrid"
    elif has_compose:
        ui_framework = "compose"
    elif has_xml_views:
        ui_framework = "xml"
    else:
        ui_framework = "unknown"

    # Resolve ViewModel Primary Base (legacy summary)
    primary_vm = None
    vm_resolution = "NONE"
    if len(vm_candidates) == 1:
        primary_vm = vm_candidates[0]
        vm_resolution = "RESOLVED"
    elif len(vm_candidates) > 1:
        primary_vm = None
        vm_resolution = "UNRESOLVED"

    # Complete Capabilities dictionary
    capabilities: dict[str, dict] = {}
    for cap_name, matched_set in matched_sigs_by_cap.items():
        if matched_set:
            capabilities[cap_name] = {
                "detected": True,
                "confidence": "HIGH",
                "evidence_signatures": sorted(matched_set),
            }
        else:
            capabilities[cap_name] = {
                "detected": False,
                "confidence": "LOW",
                "evidence_signatures": [],
            }

    # --- 3. Architecture Families Extraction ---
    families_by_sig: dict[str, dict[str, Any]] = {}

    # Synthesize families from discovered pairs or standalone bases
    if discovered_screens:
        for sc in discovered_screens:
            sc_scope = resolve_feature_scope(sc["path"])
            sc_stem = re.sub(r"(Screen|Fragment|Activity|Content)$", "", sc["name"])
            matching_vm = None
            ambiguous = False

            # Tier 1: exact normalized stem match (Screen stem == ViewModel stem)
            if sc_stem:
                t1 = [
                    v for v in discovered_viewmodels
                    if re.sub(r"(ViewModel|VM)$", "", v["name"]).lower() == sc_stem.lower()
                ]
                if len(t1) == 1:
                    matching_vm = t1[0]
                elif len(t1) > 1:
                    scoped = [v for v in t1 if resolve_feature_scope(v["path"]) == sc_scope]
                    if len(scoped) == 1:
                        matching_vm = scoped[0]
                    else:
                        ambiguous = True

            # Tier 2: same local feature scope + compatible name
            if not matching_vm and not ambiguous and sc_stem:
                t2 = [
                    v for v in discovered_viewmodels
                    if resolve_feature_scope(v["path"]) == sc_scope
                    and (
                        sc_stem.lower() in re.sub(r"(ViewModel|VM)$", "", v["name"]).lower()
                        or re.sub(r"(ViewModel|VM)$", "", v["name"]).lower() in sc_stem.lower()
                    )
                ]
                if len(t2) == 1:
                    matching_vm = t2[0]
                elif len(t2) > 1:
                    ambiguous = True

            # Tier 3: graph reference / source text association
            if not matching_vm and not ambiguous:
                sc_text = sc.get("text", "")
                if sc_text:
                    t3 = [v for v in discovered_viewmodels if v["name"] in sc_text]
                    if len(t3) == 1:
                        matching_vm = t3[0]
                    elif len(t3) > 1:
                        scoped = [v for v in t3 if resolve_feature_scope(v["path"]) == sc_scope]
                        if len(scoped) == 1:
                            matching_vm = scoped[0]
                        else:
                            ambiguous = True

            # Tier 4: one and only one candidate in local scope
            if not matching_vm and not ambiguous:
                local_vms = [v for v in discovered_viewmodels if resolve_feature_scope(v["path"]) == sc_scope]
                if len(local_vms) == 1:
                    matching_vm = local_vms[0]
                elif len(local_vms) > 1:
                    ambiguous = True

            dims = {
                "ui_toolkit": sc["ui_toolkit"],
                "screen_host": sc["screen_host"],
                "state_holder_base": matching_vm["base"] if matching_vm else "unknown",
                "state_stream": matching_vm["state_stream"] if matching_vm else "unknown",
                "presentation_flow": matching_vm["presentation_flow"] if matching_vm else "unknown",
                "input_contract": matching_vm["input_contract"] if matching_vm else "unknown",
                "effect_contract": matching_vm["effect_contract"] if matching_vm else "unknown",
                "domain_boundary": matching_vm["domain_boundary"] if matching_vm else "unknown",
                "data_boundary": matching_vm["data_boundary"] if matching_vm else "unknown",
                "di": matching_vm["di"] if matching_vm else (di_frameworks[0] if di_frameworks else "unknown"),
                "navigation": sc["nav_type"] if sc["nav_type"] != "unknown" else ("compose_navigation" if sc["ui_toolkit"] == "compose" else "xml_navigation" if nav_elements else "unknown"),
            }
            core_dims = {
                "ui_toolkit": sc["ui_toolkit"],
                "screen_host": sc["screen_host"],
                "state_holder_base": dims["state_holder_base"],
                "state_stream": dims["state_stream"],
                "presentation_flow": dims["presentation_flow"],
                "di": dims["di"],
            }
            sig_str = _canonical_json(core_dims)
            sig_hash = _sha256_text(sig_str)
            fid = f"af-{sig_hash[:12]}"
            initial_confidence = "HIGH" if matching_vm else ("LOW/AMBIGUOUS" if ambiguous else "MEDIUM")
            if fid not in families_by_sig:
                label_parts = [core_dims["ui_toolkit"]]
                if core_dims["screen_host"] != "unknown":
                    label_parts.append(core_dims["screen_host"])
                if core_dims["state_holder_base"] != "unknown":
                    label_parts.append(core_dims["state_holder_base"].lower())
                if core_dims["state_stream"] != "unknown":
                    label_parts.append(core_dims["state_stream"])
                if core_dims["di"] != "unknown":
                    label_parts.append(core_dims["di"])
                label = "-".join(label_parts) or "android-standard"
                families_by_sig[fid] = {
                    "id": fid,
                    "signature_sha256": sig_hash,
                    "label": label,
                    "dimensions": dims,
                    "confidence": initial_confidence,
                    "scopes": set(),
                    "exemplars": set(),
                    "evidence": [],
                }
            fam = families_by_sig[fid]
            # Coalesce richer dimensions into existing family
            if fam["dimensions"].get("navigation") == "unknown" and dims["navigation"] != "unknown":
                fam["dimensions"]["navigation"] = dims["navigation"]
            if fam["dimensions"].get("input_contract") == "unknown" and dims["input_contract"] != "unknown":
                fam["dimensions"]["input_contract"] = dims["input_contract"]
            if fam["dimensions"].get("effect_contract") == "unknown" and dims["effect_contract"] != "unknown":
                fam["dimensions"]["effect_contract"] = dims["effect_contract"]
            if matching_vm and fam["confidence"] != "LOW/AMBIGUOUS":
                fam["confidence"] = "HIGH"
            elif ambiguous:
                fam["confidence"] = "LOW/AMBIGUOUS"
            fam["scopes"].add(sc_scope)
            fam["exemplars"].add(sc["path"])
            if matching_vm:
                fam["exemplars"].add(matching_vm["path"])
    elif vm_candidates or has_compose or has_xml_views:
        # Synthesize from candidates or framework presence
        candidates_to_use = vm_candidates if vm_candidates else [{"symbol": "ViewModel", "path": ""}]
        for cand in candidates_to_use:
            cand_name = cand["symbol"]
            cand_scope = resolve_feature_scope(cand["path"]) if cand.get("path") else ""
            is_mvi = "mvi" in cand_name.lower() or "state" in cand_name.lower()
            u_toolkit = "compose" if has_compose else "xml" if has_xml_views else "unknown"
            s_host = "composable" if u_toolkit == "compose" else "fragment" if u_toolkit == "xml" else "unknown"
            s_stream = "stateflow" if is_mvi else "livedata" if u_toolkit == "xml" else "unknown"
            p_flow = "unidirectional" if (is_mvi and s_stream == "stateflow") else "unknown"
            dims = {
                "ui_toolkit": u_toolkit,
                "screen_host": s_host,
                "state_holder_base": cand_name,
                "state_stream": s_stream,
                "presentation_flow": p_flow,
                "input_contract": "UiAction" if is_mvi else "unknown",
                "effect_contract": "UiEvent" if is_mvi else "unknown",
                "domain_boundary": "usecase" if is_mvi else "repository",
                "data_boundary": "repository",
                "di": di_frameworks[0] if di_frameworks else "unknown",
                "navigation": "compose_navigation" if u_toolkit == "compose" else "xml_navigation" if nav_elements else "unknown",
            }
            core_dims = {
                "ui_toolkit": u_toolkit,
                "screen_host": s_host,
                "state_holder_base": cand_name,
                "state_stream": s_stream,
                "presentation_flow": p_flow,
                "di": dims["di"],
            }
            sig_str = _canonical_json(core_dims)
            sig_hash = _sha256_text(sig_str)
            fid = f"af-{sig_hash[:12]}"
            if fid not in families_by_sig:
                label_parts = [u_toolkit]
                if s_host != "unknown":
                    label_parts.append(s_host)
                label_parts.append(cand_name.lower())
                if s_stream != "unknown":
                    label_parts.append(s_stream)
                if dims["di"] != "unknown":
                    label_parts.append(dims["di"])
                label = "-".join(label_parts)
                families_by_sig[fid] = {
                    "id": fid,
                    "signature_sha256": sig_hash,
                    "label": label,
                    "dimensions": dims,
                    "confidence": "HIGH" if cand.get("path") else "MEDIUM",
                    "scopes": set(),
                    "exemplars": set(),
                    "evidence": [],
                }
            fam = families_by_sig[fid]
            if cand_scope:
                fam["scopes"].add(cand_scope)
            if cand.get("path"):
                fam["exemplars"].add(cand["path"])

    final_families: list[dict[str, Any]] = []
    scope_assignments: list[dict[str, Any]] = []

    for fid in sorted(families_by_sig.keys()):
        raw_fam = families_by_sig[fid]
        sorted_exemplars = sorted(raw_fam["exemplars"])[:5]  # Cap at 5 exemplars
        sorted_scopes = sorted(raw_fam["scopes"])
        fam_entry = {
            "id": raw_fam["id"],
            "signature_sha256": raw_fam["signature_sha256"],
            "label": raw_fam["label"],
            "dimensions": raw_fam["dimensions"],
            "confidence": raw_fam["confidence"],
            "scopes": sorted_scopes,
            "exemplars": sorted_exemplars,
            "evidence": sorted(raw_fam["evidence"]),
        }
        final_families.append(fam_entry)
        for sc in sorted_scopes:
            scope_assignments.append({"scope": sc, "family_id": raw_fam["id"]})

    facts = {
        "modules": sorted(set(modules)),
        "di": {
            "framework": di_framework,
            "frameworks": sorted(di_frameworks),
            "evidence": di_evidence,
            "modules": sorted(di_modules, key=lambda m: (m.get("name", ""), m.get("path", ""))),
        },
        "view_models": {
            "resolution": vm_resolution,
            "primary": primary_vm,
            "candidates": sorted(vm_candidates, key=lambda c: (c.get("symbol", ""), c.get("path", ""))),
        },
        "persistence": {
            "room_databases": sorted(room_databases, key=lambda d: (d.get("symbol", ""), d.get("path", ""))),
            "room_daos": sorted(room_daos, key=lambda d: (d.get("symbol", ""), d.get("path", ""))),
            "datastore_preferences": sorted(datastore_preferences, key=lambda d: d.get("file", "")),
        },
        "ui": {
            "framework": ui_framework,
            "themes": sorted(compose_themes, key=lambda t: (t.get("symbol", ""), t.get("path", ""))),
        },
        "navigation": {
            "elements": sorted(nav_elements, key=lambda n: (n.get("type", ""), n.get("path", ""))),
        },
        "conventions": {
            "result_wrappers": sorted(result_wrappers, key=lambda r: (r.get("symbol", ""), r.get("path", ""))),
        },
        "capabilities": capabilities,
        "architecture": {
            "technologies": {
                "ui_framework": ui_framework,
                "di_frameworks": sorted(di_frameworks),
                "has_compose": has_compose,
                "has_xml_views": has_xml_views,
            },
            "families": final_families,
            "scope_assignments": sorted(scope_assignments, key=lambda s: (s.get("scope", ""), s.get("family_id", ""))),
        },
    }

    normalized = normalize_project_facts(facts)
    fingerprint = project_context_fingerprint(normalized)

    return {
        "schema_version": SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "context_fingerprint_sha256": fingerprint,
        "facts": normalized,
    }


def normalize_project_facts(facts: dict) -> dict:
    """Sorts and normalizes facts structure to guarantee deterministic hashing."""
    if not isinstance(facts, dict):
        return facts
    norm: dict = {}
    for k in sorted(facts.keys()):
        v = facts[k]
        if isinstance(v, dict):
            norm[k] = normalize_project_facts(v)
        elif isinstance(v, list):
            norm_list = []
            for item in v:
                norm_list.append(normalize_project_facts(item) if isinstance(item, dict) else item)
            try:
                norm[k] = sorted(norm_list, key=lambda x: _canonical_json(x))
            except TypeError:
                norm[k] = norm_list
        else:
            norm[k] = v
    return norm


def project_context_fingerprint(facts: dict) -> str:
    """Calculates canonical SHA-256 over normalized facts, strictly ignoring timestamps."""
    content = facts.get("facts") if "facts" in facts else facts
    canonical = _canonical_json(normalize_project_facts(content))
    return _sha256_text(canonical)


def render_project_context(facts_payload: dict) -> dict[str, str]:
    """Deterministically renders markdown documents from project facts."""
    facts = facts_payload.get("facts") or facts_payload

    # 1. architecture.md
    di = facts.get("di") or {}
    vm = facts.get("view_models") or {}
    nav = facts.get("navigation") or {}
    conv = facts.get("conventions") or {}
    arch = facts.get("architecture") or {}

    arch_lines = [
        "# Project Architecture & Component Contracts",
        "",
        "> Generated by Android Agent Harness from deterministic project static analysis.",
        "> Update via `android-harness context refresh` if architecture evolves.",
        "",
        "## 1. Dependency Injection",
        f"- **Framework**: `{di.get('framework', 'unknown').upper()}`",
    ]
    if di.get("frameworks"):
        arch_lines.append(f"- **Detected Frameworks**: `{', '.join(di['frameworks'])}`")
    if di.get("modules"):
        arch_lines.append("- **Discovered Modules**:")
        for mod in di["modules"]:
            arch_lines.append(f"  - `{mod['name']}` in [`{mod['path']}`](file:///{mod['path']})")
    else:
        arch_lines.append("- No explicit DI modules indexed in root scan.")

    arch_lines.extend([
        "",
        "## 2. ViewModel & State Management",
        f"- **Resolution Status**: `{vm.get('resolution', 'NONE')}`",
    ])
    primary = vm.get("primary")
    if primary:
        generics_str = f" `{primary['generics']}`" if primary.get("generics") else ""
        arch_lines.append(f"- **Primary Base**: `{primary['symbol']}`{generics_str} in [`{primary['path']}`](file:///{primary['path']})")
    elif vm.get("candidates"):
        arch_lines.append("- **Candidates (Unresolved Primary)**:")
        for cand in vm["candidates"]:
            arch_lines.append(f"  - `{cand['symbol']}` in [`{cand['path']}`](file:///{cand['path']})")
    else:
        arch_lines.append("- No custom BaseViewModel detected (NOT_DETECTED).")

    # Families rendering (v2)
    families = arch.get("families") or []
    if families:
        arch_lines.extend([
            "",
            "## 3. Discovered Architecture Families",
        ])
        for fam in families:
            arch_lines.append(f"### Family `{fam['id']}` ({fam.get('label', 'unnamed')})")
            arch_lines.append(f"- **Confidence**: `{fam.get('confidence', 'UNKNOWN')}`")
            dims = fam.get("dimensions") or {}
            arch_lines.append(f"- **UI Toolkit**: `{dims.get('ui_toolkit')}` | **Host**: `{dims.get('screen_host')}`")
            arch_lines.append(f"- **State Holder Base**: `{dims.get('state_holder_base')}` | **Stream**: `{dims.get('state_stream')}`")
            arch_lines.append(f"- **Presentation Flow**: `{dims.get('presentation_flow')}`")
            if fam.get("exemplars"):
                arch_lines.append("- **Exemplars**:")
                for ex in fam["exemplars"]:
                    arch_lines.append(f"  - [`{ex}`](file:///{ex})")

    arch_lines.extend([
        "",
        "## 4. Navigation System",
    ])
    nav_elements = nav.get("elements") or []
    if nav_elements:
        for elem in nav_elements:
            arch_lines.append(f"- `{elem['type']}` in [`{elem['path']}`](file:///{elem['path']})")
    else:
        arch_lines.append("- No explicit navigation library detected (NOT_DETECTED).")

    if conv.get("result_wrappers"):
        arch_lines.extend([
            "",
            "## 5. Result & State Wrappers",
        ])
        for rw in conv["result_wrappers"]:
            arch_lines.append(f"- `{rw['symbol']}` in [`{rw['path']}`](file:///{rw['path']})")

    # 2. ui.md
    ui = facts.get("ui") or {}
    framework = ui.get("framework", "unknown")
    if framework == "unknown":
        ui_paradigm_str = "UNKNOWN / no UI framework evidence detected"
    else:
        ui_paradigm_str = f"`{framework.upper()}`"
    ui_lines = [
        "# Project UI, Theming & Layout Guidelines",
        "",
        "> Generated by Android Agent Harness from deterministic project static analysis.",
        "",
        f"- **UI Paradigm**: {ui_paradigm_str}",
    ]
    themes = ui.get("themes") or []
    if themes:
        ui_lines.append("- **Detected Themes**:")
        for th in themes:
            ui_lines.append(f"  - `{th['symbol']}` in [`{th['path']}`](file:///{th['path']})")
    else:
        ui_lines.append("- No explicit custom theme detected (NOT_DETECTED).")

    # 3. persistence.md
    pers = facts.get("persistence") or {}
    pers_lines = [
        "# Project Persistence & Storage Architecture",
        "",
        "> Generated by Android Agent Harness from deterministic project static analysis.",
        "",
        "## Room Databases",
    ]
    dbs = pers.get("room_databases") or []
    if dbs:
        for db in dbs:
            pers_lines.append(f"- **Database**: `{db['symbol']}` (Version `{db['version']}`, Entities: `{db['entities_count']}`)")
            pers_lines.append(f"  - File: [`{db['path']}`](file:///{db['path']})")
            if db.get("entities"):
                pers_lines.append(f"  - Entities: {', '.join(db['entities'])}")
    else:
        pers_lines.append("- No Room `@Database` classes detected (NOT_DETECTED).")

    daos = pers.get("room_daos") or []
    if daos:
        pers_lines.extend(["", "## Discovered DAOs"])
        for dao in daos:
            pers_lines.append(f"- `{dao['symbol']}` in [`{dao['path']}`](file:///{dao['path']})")

    ds = pers.get("datastore_preferences") or []
    if ds:
        pers_lines.extend(["", "## DataStore Preferences"])
        for pref in ds:
            pers_lines.append(f"- File: [`{pref['file']}`](file:///{pref['file']})")

    # 4. conventions.md
    conv_lines = [
        "# Project Engineering Conventions & Capabilities",
        "",
        "> Generated by Android Agent Harness from deterministic project static analysis.",
        "",
        "## Technical Capabilities",
    ]
    caps = facts.get("capabilities") or {}
    for cap_name in sorted(caps.keys()):
        cap_data = caps[cap_name]
        status_str = "DETECTED" if cap_data.get("detected") else "NOT DETECTED"
        sigs = cap_data.get("evidence_signatures") or []
        sig_str = f" (Evidence: `{', '.join(sigs)}`)" if sigs else ""
        conv_lines.append(f"- **{cap_name.replace('_', ' ').title()}**: `{status_str}`{sig_str}")

    return {
        "architecture.md": "\n".join(arch_lines) + "\n",
        "ui.md": "\n".join(ui_lines) + "\n",
        "persistence.md": "\n".join(pers_lines) + "\n",
        "conventions.md": "\n".join(conv_lines) + "\n",
    }


def project_context_diff(old_facts_payload: dict, new_facts_payload: dict) -> dict:
    """Computes deterministic diff between two project facts snapshots (PC-008)."""
    old_fp = old_facts_payload.get("context_fingerprint_sha256") or ""
    new_fp = new_facts_payload.get("context_fingerprint_sha256") or ""
    old_ext = old_facts_payload.get("extractor_version") or "1.0.0"
    new_ext = new_facts_payload.get("extractor_version") or EXTRACTOR_VERSION

    diff: dict[str, Any] = {
        "old_fingerprint": old_fp,
        "new_fingerprint": new_fp,
        "old_extractor": old_ext,
        "new_extractor": new_ext,
        "changed_sections": [],
    }

    if old_fp == new_fp:
        return {"kind": "NO_CHANGE", "has_drift": False, "details": []}

    if old_ext != new_ext and old_fp != new_fp:
        return {
            "kind": "EXTRACTOR_CHANGE",
            "has_drift": True,
            "details": [f"Extractor version changed from {old_ext} to {new_ext}"],
        }

    drifts = []
    old_f = old_facts_payload.get("facts") or {}
    new_f = new_facts_payload.get("facts") or {}

    # Comprehensive section coverage (PC-008)
    for section in ("modules", "di", "view_models", "persistence", "ui", "navigation", "conventions", "capabilities", "architecture"):
        if _canonical_json(old_f.get(section)) != _canonical_json(new_f.get(section)):
            drifts.append(f"Architectural drift in '{section}'")

    return {
        "kind": "SOURCE_DRIFT" if drifts else "RENDER_ONLY_CHANGE",
        "has_drift": bool(drifts),
        "details": drifts if drifts else ["Structural representation changed without source drift"],
    }


def project_context_status(repo: Path) -> dict:
    """Checks the status and freshness of project-context without modifying disk."""
    facts_file = repo / ".agents" / "project-context" / "project-facts.json"
    if not facts_file.is_file():
        return {"status": "MISSING", "message": "project-facts.json is missing; run context generate or init"}

    try:
        current_on_disk = json.loads(facts_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "CORRUPTED", "message": f"project-facts.json cannot be parsed: {exc}"}

    disk_fp = current_on_disk.get("context_fingerprint_sha256") or ""
    fresh_payload = extract_project_facts(repo, in_memory_graph=True)
    fresh_fp = fresh_payload.get("context_fingerprint_sha256") or ""

    diff = project_context_diff(current_on_disk, fresh_payload)
    if disk_fp == fresh_fp:
        return {
            "status": "CURRENT",
            "fingerprint": disk_fp,
            "message": "Project context is up-to-date with codebase architecture.",
            "diff": diff,
        }
    return {
        "status": "STALE",
        "fingerprint": disk_fp,
        "fresh_fingerprint": fresh_fp,
        "message": "Project context is stale; run 'android-harness context refresh'.",
        "diff": diff,
    }


def write_project_context(repo: Path, facts_payload: dict, rendered_views: dict[str, str] | None = None) -> Path:
    """Atomically writes project-facts.json and rendered markdown documents into .agents/project-context.

    Uses a temporary staging directory on the same filesystem, replaces rendered markdown views
    first, and replaces project-facts.json last as the authoritative commit point.
    Preserves project-notes.md and architecture-policy.json across refresh.
    """
    context_dir = repo / ".agents" / "project-context"
    context_dir.mkdir(parents=True, exist_ok=True)

    if rendered_views is None:
        rendered_views = render_project_context(facts_payload)

    stage_dir = context_dir / f".staging_{uuid.uuid4().hex}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Write views to staging
        for name, content in rendered_views.items():
            stage_file = stage_dir / name
            stage_file.write_text(content, encoding="utf-8")

        # 2. Write facts to staging
        if "source_fingerprint" not in facts_payload:
            facts_payload["source_fingerprint"] = compute_context_fingerprint(repo)
        facts_file_stage = stage_dir / "project-facts.json"
        facts_content = json.dumps(facts_payload, ensure_ascii=False, indent=2) + "\n"
        facts_file_stage.write_text(facts_content, encoding="utf-8")

        # 3. Validate staged files are present and non-empty
        required_views = ("architecture.md", "ui.md", "persistence.md", "conventions.md")
        for v in required_views:
            sf = stage_dir / v
            if not sf.is_file() or sf.stat().st_size == 0:
                raise IOError(f"Staging failed for view: {v}")
        if not facts_file_stage.is_file() or facts_file_stage.stat().st_size == 0:
            raise IOError("Staging failed for project-facts.json")

        # 4. Atomically replace markdown views first
        for name in rendered_views.keys():
            os.replace(stage_dir / name, context_dir / name)

        # 5. Atomically replace project-facts.json LAST (the authoritative commit point)
        os.replace(facts_file_stage, context_dir / "project-facts.json")

        # 6. Create initial project-notes.md only if it does not already exist (NEVER overwrite)
        notes_file = context_dir / "project-notes.md"
        if not notes_file.exists():
            notes_content = [
                "# Human-Authored Project Architectural Notes",
                "",
                "> This file is owned and maintained by the project engineering team.",
                "> When instructed by the developer, AI agents may append or update project notes and conventions here.",
                "",
                "## Domain Conventions & Context",
                "- Add specific team idioms, legacy constraints, or non-obvious architecture requirements here.",
                "",
            ]
            notes_file.write_text("\n".join(notes_content), encoding="utf-8")

    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)

    return context_dir


def compute_context_fingerprint(repo: Path) -> str:
    """Computes a fast, lightweight structural fingerprint across build and config files."""
    items: list[tuple[str, int, int]] = []
    patterns = (
        "settings.gradle*",
        "build.gradle*",
        "gradle/libs.versions.toml",
        "*/build.gradle*",
        "**/build.gradle*",
        "**/AndroidManifest.xml",
    )
    seen: set[str] = set()
    for pattern in patterns:
        for p in repo.glob(pattern):
            if not p.is_file():
                continue
            try:
                rel = p.resolve().relative_to(repo.resolve()).as_posix()
            except ValueError:
                continue
            if rel.startswith((".git/", ".agents/", ".gradle/", "build/")):
                continue
            if rel in seen:
                continue
            seen.add(rel)
            try:
                st = p.stat()
                items.append((rel, st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))))
            except OSError:
                pass
    items.sort()
    import hashlib
    raw = ";".join(f"{rel}:{sz}:{mt}" for rel, sz, mt in items)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_context_fresh(repo: Path) -> bool:
    """Cheap check to verify whether project-facts.json is still fresh without re-extracting."""
    facts_file = repo / ".agents" / "project-context" / "project-facts.json"
    if not facts_file.is_file():
        return False
    try:
        from _vnext_common import read_json
        facts = read_json(facts_file)
        stored_fp = facts.get("source_fingerprint")
        if not stored_fp:
            return False
        curr_fp = compute_context_fingerprint(repo)
        return stored_fp == curr_fp
    except Exception:
        return False
