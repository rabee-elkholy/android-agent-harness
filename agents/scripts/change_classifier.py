"""Deterministic multi-label Android change-surface classifier."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print, step_progress, sublog  # noqa: E402
from _repo_files import ChangedFile, changed_files  # noqa: E402
from _vnext_common import canonical_sha256  # noqa: E402
from delivery_manifest import is_delivery_relevant  # noqa: E402


SCHEMA_VERSION = 1
SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
CRITICAL_SURFACES = {"BILLING", "AUTH", "SECURITY", "SENSITIVE_DATA", "CRYPTO"}
HIGH_SURFACES = {"ROOM_SCHEMA", "MANIFEST_PERMISSION", "BUILD_CONFIG", "PUBLIC_API", "NATIVE_CODE", "HARNESS_CONFIG"}
DEVICE_SURFACES = {"COMPOSE_UI", "XML_UI", "NAVIGATION", "DEVICE_API"}

PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("BILLING", re.compile(r"(?i)billingclient|purchase|subscription|productdetails|com\.android\.billingclient"), "BILLING_PATTERN"),
    ("AUTH", re.compile(r"(?i)oauth|authentication|authorization|login|sign.?in|jwt|androidx\.biometric|com\.google\.android\.gms\.auth"), "AUTH_PATTERN"),
    ("CRYPTO", re.compile(r"(?i)cipher|keystore|secretkey|encrypt|decrypt|messageDigest|javax\.crypto|java\.security\.(?:KeyStore|MessageDigest)"), "CRYPTO_PATTERN"),
    ("SENSITIVE_DATA", re.compile(r"(?i)access.?token|refresh.?token|password|biometric|health.?data|location|androidx\.security\.crypto"), "SENSITIVE_PATTERN"),
    ("COROUTINES", re.compile(r"\b(suspend|CoroutineScope|Dispatchers\.|Flow<|StateFlow|SharedFlow|launch\s*\{|async\s*\{)"), "COROUTINE_PATTERN"),
    ("ROOM_SCHEMA", re.compile(r"@(Database|Entity|Embedded|Relation)|AutoMigration|Migration\s*\("), "ROOM_PATTERN"),
    ("PERSISTENCE", re.compile(r"(?i)datastore|sqldelight|sqlite(database|openhelper)?|realm(configuration)?"), "PERSISTENCE_PATTERN"),
    ("NETWORK", re.compile(r"(?i)retrofit|okhttp|ktor|httpclient|@GET\b|@POST\b|websocket"), "NETWORK_PATTERN"),
    ("SECURITY", re.compile(r"(?i)networksecurityconfig|certificatepinner|trustmanager|hostnameverifier|x509certificate|androidx\.security|Class\.forName\s*\(\s*[\"']?(?:[^\"']*\.)?(?:billingclient|biometric|auth|crypto|security)"), "SECURITY_PATTERN"),
    ("DEVICE_API", re.compile(r"(?i)bluetooth|sensor|locationmanager|camera|notificationmanager|foregroundservice"), "DEVICE_API_PATTERN"),
)

VIEW_UI_RE = re.compile(
    r"\b("
    r"(?:androidx\.fragment\.app\.)?Fragment\b|"
    r"(?:DialogFragment|BottomSheetDialogFragment|ListFragment)\b|"
    r"(?:AppCompatActivity|ComponentActivity|FragmentActivity|android\.app\.Activity)\b|"
    r"(?:RecyclerView\.(?:Adapter|ViewHolder)|ListAdapter|BaseAdapter|ArrayAdapter|PagerAdapter)\b|"
    r"(?:onCreateViewHolder|onBindViewHolder|getItemCount)\b|"
    r"(?:ViewBinding|DataBindingUtil|LayoutInflater)\b|"
    r"(?:findViewById|setOnClickListener|setContentView)\b|"
    r":\s*(?:Fragment|AppCompatActivity|ComponentActivity|RecyclerView\.Adapter|ListAdapter)\b"
    r")"
)

BUSINESS_TRIGGERS_RE = re.compile(
    r"\b(?:suspend|CoroutineScope|Dispatchers\.|launch\s*\{|async\s*\{|withContext)\b|"
    r"\b(?:emit\s*\(|\.update\s*\{|\.value\s*=|setState\s*\(|sendAction|sendEvent|_state\.)|"
    r"\b(?:viewmodel|repository|usecase|service|interactor|datasource|dao|api)\.|\.invoke\s*\(|"
    r"\b(?:if|when)\s*\(.*?\b(?:state\.|is|has|can|should|status|type|count|total|amount|user|auth|token|perm)\b|"
    r"\b(?:UiState|UiAction|UiEffect|Event|Action|Intent)\b|"
    r"\b(?:validate|validator|sanitize|calculate|compute)\b|"
    r"\b(?:retrofit|okhttp|ktor|httpclient|datastore|sqldelight|sqlite|realm)\b|"
    r"\b(?:billingclient|purchase|subscription|productdetails)\b|"
    r"\b(?:oauth|authentication|authorization|login|sign.?in|jwt|biometric)\b|"
    r"\b(?:cipher|keystore|secretkey|encrypt|decrypt|access.?token|refresh.?token|password)\b|"
    r"\b(?:NavHost|NavController|findNavController|rememberNavController|navigate\(|popBackStack\()",
    re.IGNORECASE,
)


def is_ui_only_kotlin(diff_text: str, context_text: str, full_text: str, rel: str) -> bool:
    """Deterministically identifies Kotlin edits that alter only UI presentational details.

    UI-only Kotlin edits must:
    1. Enclose in a UI declaration (@Composable, @Preview, or View/Recycler presentation method).
    2. Not alter business/domain/state triggers in the changed hunk.
    3. Not introduce or modify non-UI class/interface declarations.
    """
    lower_rel = rel.lower()
    non_ui_path_markers = (
        "viewmodel", "repository", "usecase", "interactor", "datasource",
        "/domain/", "/data/", "/model/", "/network/", "/database/", "/db/"
    )
    if any(m in lower_rel for m in non_ui_path_markers):
        return False

    ctx_check = context_text if context_text.strip() else full_text
    has_ui_context = bool(
        re.search(r"@(?:Composable|Preview)\b", ctx_check)
        or VIEW_UI_RE.search(ctx_check)
        or re.search(r"\b(?:onCreateViewHolder|onBindViewHolder|getItemCount)\b", ctx_check)
    )
    if not has_ui_context:
        return False

    if not diff_text.strip():
        return False

    if BUSINESS_TRIGGERS_RE.search(diff_text):
        return False

    for line in diff_text.splitlines():
        clean_l = line.strip().lstrip("+-").strip()
        if re.match(r"^(?:(?:open|abstract|final|sealed|data|value|enum)\s+)*(?:class|interface|object)\b", clean_l):
            if not re.search(r"@Preview|PreviewParameter", clean_l):
                return False

    return True


VISUAL_COMPOSE_KEYWORDS_RE = re.compile(
    r"\b(?:padding|margin|spacer|dp|sp|width|height|size|fillmaxwidth|fillmaxheight|fillmaxsize|"
    r"arrangement|alignment|color|brush|shape|roundedcornershape|fontsize|fontweight|fontfamily|"
    r"preview|previewparameter|clip|border|alpha|elevation)\b",
    re.IGNORECASE,
)
NON_VISUAL_COMPOSE_TRIGGERS_RE = re.compile(
    r"\b(?:if|when|remember|mutablestateof|collectasstate|by\s+|var\s+|onclick|onvaluechange|"
    r"val\s+[a-zA-Z0-9_]+\s*=|navhost|navcontroller|navigate|launch|coroutine)\b|"
    r"\b(?:viewmodel|repository|usecase|service)\.",
    re.IGNORECASE,
)


def _is_visual_only_compose(diff_text: str) -> bool:
    if not diff_text:
        return False
    modified_lines = [
        line[1:].strip() for line in diff_text.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    code_text = " \n ".join(modified_lines)
    if not code_text.strip():
        return False
    if NON_VISUAL_COMPOSE_TRIGGERS_RE.search(code_text):
        return False
    return bool(VISUAL_COMPOSE_KEYWORDS_RE.search(code_text))


def _add(result: dict, surface: str, path: str, reason: str) -> None:
    result.setdefault(surface, {"files": set(), "reasons": set()})
    result[surface]["files"].add(path)
    result[surface]["reasons"].add(reason)


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _head_text(repo: Path, relative: str) -> str:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{relative}"], cwd=str(repo), capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    return proc.stdout if proc.returncode == 0 and len(proc.stdout) <= 2 * 1024 * 1024 else ""


def _room_schema_types(repo: Path) -> set[str]:
    types: set[str] = set()
    try:
        from room_guard import iter_database_files, parse_database_source
        for db_path in iter_database_files(repo):
            try:
                text = db_path.read_text(encoding="utf-8", errors="replace")
                decl = parse_database_source(text, db_path.relative_to(repo).as_posix(), repo)
                types.update(decl.entity_names)
            except Exception:
                continue
    except Exception:
        pass
    return types


SENSITIVE_DEPENDENCY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("BILLING", re.compile(r"(?i)billing|purchase|subscription|entitlement")),
    ("AUTH", re.compile(r"OAuth|Oauth|Authentication|Authorization|Auth(?:$|[A-Z_])|Login|SignIn|Signin|Credential|Biometric")),
    ("CRYPTO", re.compile(r"(?i)cipher|keystore|secretkey|encrypt|decrypt|crypto")),
    ("SENSITIVE_DATA", re.compile(r"(?i)access.?token|refresh.?token|password|health.?data")),
    ("SECURITY", re.compile(r"(?i)certificatepinner|trustmanager|hostnameverifier|security")),
)

FRAMEWORK_EXCLUDED_TYPES = frozenset({
    "String", "Int", "Long", "Float", "Double", "Boolean", "Byte", "Short", "Char",
    "List", "Set", "Map", "MutableList", "MutableSet", "MutableMap", "ArrayList", "HashMap",
    "Unit", "Any", "Nothing", "Throwable", "Exception", "Error", "Result",
    "Modifier", "Composable", "Context", "View", "ViewGroup", "Activity", "Fragment",
    "ComponentActivity", "AppCompatActivity", "ViewModel", "AndroidViewModel", "SavedStateHandle",
    "CoroutineScope", "Dispatchers", "Flow", "StateFlow", "SharedFlow",
})

UNIVERSAL_HUB_NAMES = frozenset({
    "Application", "App", "BaseActivity", "MainActivity", "AppModule",
    "ApplicationComponent", "SingletonComponent", "ActivityComponent",
})


def _is_universal_hub(rel: str, class_name: str) -> bool:
    if class_name in UNIVERSAL_HUB_NAMES:
        return True
    lower = rel.lower()
    if any(h in lower for h in ("/di/", "di/module", "applicationcomponent", "singletoncomponent")):
        return True
    return False


def _extract_direct_dependency_types(text: str) -> set[str]:
    """Extract direct dependency types: constructor params, fields, supertypes, and imports."""
    types = set()
    if not text:
        return types
    # 1. Imports
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            import_target = stripped[7:].rstrip(";").strip()
            parts = import_target.split(".")
            if parts:
                leaf = parts[-1]
                if leaf and leaf[0].isupper() and leaf not in FRAMEWORK_EXCLUDED_TYPES:
                    types.add(leaf)
    # 2. Constructor parameters: val/var name: Type
    for match in re.finditer(r"\b(?:val|var)\s+[a-zA-Z0-9_]+\s*:\s*([A-Za-z0-9_]+)", text):
        t = match.group(1)
        if t not in FRAMEWORK_EXCLUDED_TYPES:
            types.add(t)
    # 3. Supertypes / interfaces: class/interface/object ... : Super1, Super2
    for match in re.finditer(r"\b(?:class|interface|object)\s+[a-zA-Z0-9_]+(?:\s*<[^>]*>)?\s*(?:\([^)]*\))?\s*:\s*([A-Za-z0-9_,\s<>]+)\s*(?:\{|;|$)", text):
        raw_supers = match.group(1)
        for s in raw_supers.split(","):
            s_clean = s.strip().split("<")[0].split("(")[0].strip()
            if s_clean and s_clean not in FRAMEWORK_EXCLUDED_TYPES:
                types.add(s_clean)
    # 4. Injected or private properties: private val foo: Type
    for match in re.finditer(r"\b(?:private|protected|public|internal)?\s*(?:val|var)\s+[a-zA-Z0-9_]+\s*:\s*([A-Za-z0-9_]+)", text):
        t = match.group(1)
        if t not in FRAMEWORK_EXCLUDED_TYPES:
            types.add(t)
    return types


_TYPE_SURFACE_CACHE: dict[tuple[Path, str], str | None] = {}


def _resolve_type_surface(root: Path, type_name: str) -> tuple[str, str] | None:
    """Check if a dependency type maps to a sensitive surface directly or via target source file (1 hop)."""
    # Direct match on type name
    for surface, pattern in SENSITIVE_DEPENDENCY_PATTERNS:
        if pattern.search(type_name):
            return surface, type_name

    # Check cache
    cache_key = (root, type_name)
    if cache_key in _TYPE_SURFACE_CACHE:
        cached = _TYPE_SURFACE_CACHE[cache_key]
        return (cached, type_name) if cached else None

    # Search for target file in repository (1 hop)
    try:
        matches = []
        for ext in (".kt", ".java"):
            for candidate in (root / "app" / "src").glob(f"**/{type_name}{ext}"):
                matches.append(candidate)
                if len(matches) >= 1:
                    break
            if not matches:
                for candidate in root.glob(f"**/{type_name}{ext}"):
                    if ".git" not in str(candidate) and "build" not in str(candidate):
                        matches.append(candidate)
                        if len(matches) >= 1:
                            break
            if matches:
                break

        if matches:
            target_path = matches[0]
            target_text = _read_text(target_path)
            for surface, pattern, _reason in PATTERNS:
                if surface in CRITICAL_SURFACES:
                    if pattern.search(target_text):
                        _TYPE_SURFACE_CACHE[cache_key] = surface
                        return surface, f"{type_name} -> {surface}"
    except Exception:
        pass

    _TYPE_SURFACE_CACHE[cache_key] = None
    return None


def _propagate_sensitive_dependencies(root: Path, rel: str, full_text: str, found: dict) -> None:
    class_name = Path(rel).stem
    if _is_universal_hub(rel, class_name):
        return

    deps = _extract_direct_dependency_types(full_text)
    for dep in sorted(deps):
        resolved = _resolve_type_surface(root, dep)
        if resolved:
            surface, dep_info = resolved
            _add(found, surface, rel, f"{surface}_DEPENDENCY_PROPAGATION: {dep_info}")


HUNK_LINE_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
DECL_RE = re.compile(
    r"\b(?:class|interface|object|enum\s+class|fun|suspend\s+fun)\s+([A-Za-z0-9_]+)|"
    r"\b(?:public|protected|private|static|final|synchronized|\s)*\s*(?:void|[A-Za-z0-9_<>\[\]]+)\s+([A-Za-z0-9_]+)\s*\([^)]*\)\s*(?:throws\s+[A-Za-z0-9_,\s]+)?\s*\{?"
)
CLASS_DECL_RE = re.compile(r"\b(?:class|interface|object)\s+([A-Za-z0-9_]+)")
FUN_DECL_RE = re.compile(r"\b(?:fun|suspend\s+fun)\s+([A-Za-z0-9_]+)")


def _strip_code_line(line: str, in_block: bool, in_triple: str | None = None) -> tuple[str, bool, str | None]:
    res = []
    i = 0
    n = len(line)
    while i < n:
        if in_block:
            end = line.find("*/", i)
            if end != -1:
                in_block = False
                i = end + 2
            else:
                break
        elif in_triple:
            end = line.find(in_triple, i)
            if end != -1:
                q_len = len(in_triple)
                in_triple = None
                i = end + q_len
            else:
                break
        elif line[i:i+2] == "/*":
            in_block = True
            i += 2
        elif line[i:i+2] == "//":
            break
        elif line[i:i+3] in ('"""', "'''"):
            q3 = line[i:i+3]
            end = line.find(q3, i + 3)
            if end != -1:
                i = end + 3
            else:
                in_triple = q3
                break
        elif line[i] in ('"', "'"):
            q = line[i]
            i += 1
            while i < n:
                if line[i] == q and (i == 0 or line[i-1] != '\\'):
                    i += 1
                    break
                i += 1
        else:
            res.append(line[i])
            i += 1
    return "".join(res), in_block, in_triple


def _enclosing_structural_context(text: str, modified_line_numbers: list[int]) -> str:
    """Extract enclosing declaration (function or class) and leading annotations for modified lines."""
    if not text or not modified_line_numbers:
        return ""
    lines = text.splitlines()
    scopes_by_line: dict[int, list[str]] = {}
    scope_stack: list[tuple[str, int]] = []
    current_brace_depth = 0
    current_paren_depth = 0
    in_block = False
    in_triple = None
    pending_header: list[str] = []
    active_param_header: str = ""
    param_header_depth: int = 0

    for idx, line in enumerate(lines, 1):
        clean, in_block, in_triple = _strip_code_line(line, in_block, in_triple)
        stripped = line.strip()
        if stripped.startswith("@"):
            pending_header.append(line)
        elif DECL_RE.search(clean):
            annos = []
            for h_line in reversed(pending_header):
                if h_line.strip().startswith("@"):
                    annos.insert(0, h_line)
                else:
                    break
            pending_header = annos + [line]

        for char in clean:
            if char == "(":
                if not active_param_header and any(DECL_RE.search(l) for l in pending_header):
                    active_param_header = "\n".join(pending_header)
                    param_header_depth = current_paren_depth
                current_paren_depth += 1
            elif char == ")":
                current_paren_depth = max(0, current_paren_depth - 1)
                if active_param_header and current_paren_depth <= param_header_depth:
                    active_param_header = ""
            elif char == "{":
                if pending_header:
                    last = pending_header[-1]
                    idx_brace = last.find("{")
                    if idx_brace != -1:
                        trimmed_last = last[:idx_brace + 1].rstrip()
                        h_lines = pending_header[:-1] + ([trimmed_last] if trimmed_last else [])
                    else:
                        h_lines = pending_header
                    header_str = "\n".join(h_lines)
                else:
                    header_str = ""
                scope_stack.append((header_str, current_brace_depth))
                pending_header = []
                active_param_header = ""
                current_brace_depth += 1
            elif char == "}":
                current_brace_depth = max(0, current_brace_depth - 1)
                while scope_stack and scope_stack[-1][1] >= current_brace_depth:
                    scope_stack.pop()

        if not clean.strip() or ("{" in clean and not pending_header):
            pass
        elif not any(DECL_RE.search(l) for l in pending_header):
            if not stripped.startswith("@"):
                pending_header = []

        active_headers = [h for h, _ in scope_stack if h]
        if active_param_header:
            active_headers.append(active_param_header)
        scopes_by_line[idx] = active_headers

    emitted: list[str] = []
    seen: set[str] = set()
    for l_num in modified_line_numbers:
        for header in scopes_by_line.get(l_num, []):
            if header not in seen:
                seen.add(header)
                emitted.append(header)
    return "\n".join(emitted)


def _enclosing_xml_context(text: str, modified_line_numbers: list[int]) -> str:
    """Extract enclosing XML element tag and attributes for modified lines."""
    if not text or not modified_line_numbers:
        return ""
    lines = text.splitlines()
    total = len(lines)
    elements: list[str] = []
    seen: set[str] = set()
    for l_num in modified_line_numbers:
        idx = min(max(0, l_num - 1), total - 1)
        tag_start = None
        for cur in range(idx, max(0, idx - 40) - 1, -1):
            line_str = lines[cur].strip()
            m = re.search(r"<([A-Za-z0-9_-]+)", line_str)
            if m and not line_str.startswith("<!--") and not line_str.startswith("<?"):
                tag_start = cur
                break
        if tag_start is not None:
            tag_lines = []
            for cur in range(tag_start, min(total, tag_start + 15)):
                tag_lines.append(lines[cur])
                if ">" in lines[cur]:
                    break
            element_snippet = "\n".join(tag_lines)
            if element_snippet not in seen:
                seen.add(element_snippet)
                elements.append(element_snippet)
    return "\n".join(elements)


def _diff_content(repo: Path, changed: ChangedFile) -> tuple[str, str]:
    """Return added/removed diff text and bounded enclosing structural context."""
    if changed.is_untracked:
        content = _read_text(changed.path) if changed.exists else ""
        return content, ""
    before_rel = changed.old_rel_posix or changed.rel_posix
    if not changed.exists or changed.status == "D":
        return _head_text(repo, before_rel), ""

    diff_cmd = ["git", "diff", "-U0", "--no-ext-diff", "--find-renames", "HEAD", "--", changed.rel_posix]
    if changed.old_rel_posix and changed.old_rel_posix != changed.rel_posix:
        diff_cmd.append(changed.old_rel_posix)
    proc = subprocess.run(
        diff_cmd, cwd=str(repo), capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode != 0:
        text = _read_text(changed.path) if changed.exists else ""
        return text + "\n" + _head_text(repo, before_rel), ""

    lines: list[str] = []
    line_nums: list[int] = []
    for line in proc.stdout.splitlines():
        if line.startswith("@@"):
            m = HUNK_LINE_RE.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                line_nums.extend(range(start, start + max(1, count)))
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            lines.append(line[1:])
    diff_text = "\n".join(lines)
    context_text = ""
    if changed.exists and line_nums:
        suffix = Path(changed.rel_posix.lower()).suffix
        if suffix in (".kt", ".java"):
            context_text = _enclosing_structural_context(_read_text(changed.path), line_nums)
        elif suffix == ".xml":
            context_text = _enclosing_xml_context(_read_text(changed.path), line_nums)
    return diff_text, context_text



def _changed_line_count(repo: Path, changes: list) -> int:
    """Return a conservative diff-size bound without trusting file mtimes."""
    total = 0
    relevant_paths = {c.rel_posix for c in changes} | {c.old_rel_posix for c in changes if c.old_rel_posix}
    proc = subprocess.run(
        ["git", "diff", "--numstat", "HEAD", "--"], cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode == 0:
        for line in (proc.stdout or "").splitlines():
            fields = line.split("\t", 2)
            if len(fields) < 3:
                continue
            path_in_diff = fields[2]
            if "=>" not in path_in_diff and not is_delivery_relevant(path_in_diff):
                continue
            if path_in_diff not in relevant_paths:
                continue
            if fields[0] == "-" or fields[1] == "-":
                total += 100_000
            else:
                try:
                    total += int(fields[0]) + int(fields[1])
                except ValueError:
                    total += 100_000
    for changed in changes:
        if not changed.is_untracked or not changed.exists or not is_delivery_relevant(changed.rel_posix):
            continue
        try:
            data = changed.path.read_bytes()
            total += data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        except OSError:
            total += 100_000
    return total


def classify(repo: Path, task_id: str | None = None, task_changes: list | None = None) -> dict:
    root = repo.resolve()
    found: dict[str, dict[str, set[str]]] = {}
    all_changes = changed_files(root, include_untracked=True)

    if task_changes is None and task_id:
        try:
            from delivery_manifest import load_task_baseline
            baseline = load_task_baseline(root, task_id)
            if baseline and "task_changes" in baseline:
                task_changes = baseline.get("task_changes")
        except Exception:
            pass

    if task_changes is not None:
        def _extract_cls_path(c: Any) -> str:
            if isinstance(c, dict):
                return str(c.get("path") or "")
            if hasattr(c, "rel_posix"):
                return str(c.rel_posix or "")
            return str(c or "")

        task_paths = {_extract_cls_path(c) for c in task_changes if _extract_cls_path(c)}
        changes = [c for c in all_changes if c.rel_posix in task_paths or (c.old_rel_posix and c.old_rel_posix in task_paths)]
    else:
        changes = all_changes

    if changes:
        sublog(f"Evaluating surface patterns across {len(changes)} changed file(s)...")

    has_source_files = any(c.rel_posix.lower().endswith((".kt", ".java")) for c in changes)
    room_types = _room_schema_types(root) if has_source_files else set()
    for changed in changes:
        rel = changed.rel_posix
        if not is_delivery_relevant(rel) and not (changed.old_rel_posix and is_delivery_relevant(changed.old_rel_posix)):
            continue
        lower = rel.lower()
        suffix = Path(lower).suffix
        diff_text, context_text = _diff_content(root, changed)
        before_rel = changed.old_rel_posix or rel
        full_text = (_read_text(changed.path) if changed.exists else "") + "\n" + _head_text(root, before_rel)
        test_path = "/test/" in f"/{lower}" or "/androidtest/" in f"/{lower}" or lower.endswith(("test.kt", "test.java"))
        if Path(lower).name in ("agents.md", "gemini.md", "claude.md", "copilot-instructions.md", "continue-android-harness.md", "codex.md", "qwen.md", "github-instructions.md") or ".cursorrules" in lower or ".windsurfrules" in lower or ".github/workflows" in lower:
            _add(found, "HARNESS_CONFIG", rel, "HARNESS_INSTRUCTION_SURFACE")
        elif suffix in (".md", ".txt", ".rst"):
            _add(found, "DOCS", rel, "DOCUMENTATION_PATH")
        if "/res/values" in f"/{lower}" and suffix == ".xml":
            if Path(lower).name in ("strings.xml", "plurals.xml", "arrays.xml"):
                _add(found, "LOCALIZATION", rel, "LOCALIZED_RESOURCE")
            else:
                _add(found, "RESOURCE_UI", rel, "VALUES_RESOURCE")
        if "/res/layout" in f"/{lower}" and suffix == ".xml":
            _add(found, "XML_UI", rel, "LAYOUT_RESOURCE")
        if "/res/navigation" in f"/{lower}" and suffix == ".xml":
            _add(found, "NAVIGATION", rel, "NAVIGATION_GRAPH")
        if "/res/" in f"/{lower}" and suffix not in (".md", ".txt"):
            _add(found, "RESOURCE_UI", rel, "ANDROID_RESOURCE")
        if suffix in (".kt", ".kts") and ("@composable" in full_text.lower() or "androidx.compose" in full_text.lower()):
            if _is_visual_only_compose(diff_text):
                _add(found, "COMPOSE_UI", rel, "COMPOSE_VISUAL_ONLY")
            else:
                _add(found, "COMPOSE_UI", rel, "COMPOSE_PATTERN")
        if suffix in (".kt", ".java") and not test_path and VIEW_UI_RE.search(full_text):
            _add(found, "XML_UI", rel, "VIEW_UI_COMPONENT")
        if suffix in (".kt", ".java") and not test_path and re.search(r"\b(NavHost|NavController|findNavController|rememberNavController)\b|navGraphBuilder|popUpTo\(", diff_text):
            _add(found, "NAVIGATION", rel, "NAVIGATION_CALL")
        if suffix in (".kt", ".java") and not test_path:
            if is_ui_only_kotlin(diff_text, context_text, full_text, rel):
                pass
            else:
                _add(found, "BUSINESS_LOGIC", rel, "SOURCE_CHANGE")
        if suffix in (".kt", ".java") and not test_path and room_types:
            try:
                from room_guard import declared_type_names
                types_in_file = {Path(rel).stem} | declared_type_names(full_text)
                if types_in_file & room_types:
                    _add(found, "ROOM_SCHEMA", rel, "ROOM_ENTITY_OR_EMBEDDED_TYPE")
            except Exception:
                pass
        if suffix in (".gradle", ".kts", ".toml", ".properties") or Path(lower).name in ("gradlew", "gradlew.bat"):
            _add(found, "BUILD_CONFIG", rel, "BUILD_FILE")
        if "androidmanifest.xml" in lower:
            manifest_has_perm = bool(
                re.search(r"uses-permission|android\.permission\.|android:exported|provider|intent-filter", diff_text, re.I)
                or re.search(r"<(?:uses-permission|permission|permission-tree|permission-group|provider|intent-filter)\b", context_text, re.I)
            )
            manifest_has_comp = bool(
                re.search(r"\b(?:service|receiver|uses-feature)\b", diff_text, re.I)
                or re.search(r"<(?:service|receiver|uses-feature)\b", context_text, re.I)
            )
            if manifest_has_perm:
                _add(found, "MANIFEST_PERMISSION", rel, "MANIFEST_PERMISSION_CHANGE")
            if manifest_has_comp:
                _add(found, "DEVICE_API", rel, "MANIFEST_COMPONENT_CHANGE")
                _add(found, "BUILD_CONFIG", rel, "MANIFEST_CHANGE")
            if not manifest_has_perm and not manifest_has_comp:
                _add(found, "BUILD_CONFIG", rel, "MANIFEST_CHANGE")
        if suffix in (".aidl", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".so"):
            _add(found, "NATIVE_CODE", rel, "NATIVE_OR_AIDL_CHANGE")
        if test_path:
            _add(found, "TEST_ONLY", rel, "TEST_CHANGE")
        if not test_path:
            has_explicit_public = bool(re.search(r"\b(public|protected)\s+(class|interface|object|fun|static|abstract)\b", diff_text))
            has_implicit_public = False
            if suffix in (".kt", ".kts"):
                for line in diff_text.splitlines():
                    stripped = line.strip()
                    code_part = stripped[1:].strip() if stripped.startswith(("+", "-")) else stripped
                    if re.match(r"^(?:(?:open|abstract|final|sealed|data|value|enum)\s+)*(?:class|interface|object|fun)\s+[A-Za-z0-9_]+", code_part):
                        if not re.match(r"^(?:private|internal)\b", code_part):
                            has_implicit_public = True
                            break

            is_library = False
            try:
                from _product import PROJECT_KIND
                is_library = (str(PROJECT_KIND or "").lower() == "library")
            except Exception:
                pass

            if has_explicit_public:
                _add(found, "PUBLIC_API", rel, "PUBLIC_DECLARATION")
            elif is_library and has_implicit_public:
                _add(found, "PUBLIC_API", rel, "IMPLICIT_PUBLIC_LIBRARY_API")
        if "network_security_config" in lower and suffix == ".xml":
            _add(found, "SECURITY", rel, "NETWORK_SECURITY_CONFIG")
        if Path(lower).name in ("consumer-rules.pro", "proguard-rules.pro"):
            _add(found, "BUILD_CONFIG", rel, "PROGUARD_RULES")
        if Path(lower).name in ("baseline-prof.txt", "startup-prof.txt"):
            _add(found, "BUILD_CONFIG", rel, "BASELINE_PROFILE")
        for surface, pattern, reason in PATTERNS:

            if not test_path:
                if pattern.search(diff_text):
                    _add(found, surface, rel, reason)
                elif context_text and pattern.search(context_text):
                    _add(found, surface, rel, f"{reason}_CONTEXT")

        if suffix in (".kt", ".java") and not test_path:
            _propagate_sensitive_dependencies(root, rel, full_text, found)

    non_docs = set(found) - {"DOCS", "TEST_ONLY"}
    relevant_changes = [item for item in changes if is_delivery_relevant(item.rel_posix) or (item.old_rel_posix and is_delivery_relevant(item.old_rel_posix))]
    classified_files = {path for info in found.values() for path in info.get("files", ())}
    for item in relevant_changes:
        rel = item.rel_posix
        old_rel = item.old_rel_posix
        if rel not in classified_files and (not old_rel or old_rel not in classified_files):
            _add(found, "UNKNOWN", rel, "UNCLASSIFIED_CHANGE")

    surfaces = sorted(found)
    if set(surfaces) & CRITICAL_SURFACES:
        severity = "CRITICAL"
    elif set(surfaces) & HIGH_SURFACES:
        severity = "HIGH"
    elif set(surfaces) & (DEVICE_SURFACES | {"BUSINESS_LOGIC", "NETWORK", "COROUTINES", "PERSISTENCE"}):
        severity = "MEDIUM"
    else:
        severity = "LOW"
    confidence = "LOW" if "UNKNOWN" in surfaces else "HIGH"
    if confidence == "HIGH":
        for surface in surfaces:
            if surface in CRITICAL_SURFACES:
                info = found.get(surface, {})
                reasons = info.get("reasons", set())
                if reasons and all("DEPENDENCY_PROPAGATION" in str(r) for r in reasons):
                    confidence = "MEDIUM"
                    break
    details = {
        surface: {
            "files": sorted(info["files"]),
            "reasons": sorted(info["reasons"]),
        }
        for surface, info in sorted(found.items())
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "surfaces": surfaces,
        "severity": severity,
        "confidence": confidence,
        "details": details,
        "changed_files": len(relevant_changes),
        "changed_lines": _changed_line_count(root, relevant_changes),
        "has_delete_or_rename": any(item.status in {"D", "R"} for item in relevant_changes),
    }
    result["classification_sha256"] = canonical_sha256(result)
    return result


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task-id", default=None, help="Task ID for baseline-scoped classification")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.json:
        result = classify(Path(args.repo), task_id=args.task_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        with step_progress("Classifying changes & surfaces"):
            result = classify(Path(args.repo), task_id=args.task_id)
        print(f"SURFACES={','.join(result['surfaces']) or 'NONE'}")
        print(f"SEVERITY={result['severity']}")
        print(f"CONFIDENCE={result['confidence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
