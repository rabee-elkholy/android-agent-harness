"""Multi-module and KMP source-set discovery shared by lints, audits, classifiers, and the doctor."""
from __future__ import annotations

import os
import re
from pathlib import Path

SKIP_PARTS = {
    ".git", "build", ".gradle", ".idea", ".agents", ".harness-backup", ".harness-setup",
    "node_modules", "__pycache__", "Pods", "DerivedData", ".kotlin",
}

_SRC_MARKERS = ("java", "kotlin")
_SOURCE_SET_DIRS = (
    "main",
    "androidMain",
    "commonMain",
    "iosMain",
    "iosArm64Main",
    "iosSimulatorArm64Main",
    "iosX64Main",
    "appleMain",
    "nativeMain",
    "mobileMain",
    "jvmMain",
    "desktopMain",
    "jvmAndAndroidMain",
    "jsMain",
    "wasmJsMain",
)

# Canonical Gradle test source sets (Android + KMP: test, androidTest, testFixtures, sharedTest,
# instrumentationTest, commonTest, iosTest, iosSimulatorArm64Test, androidUnitTest, androidHostTest, etc.)
TEST_SOURCE_SET_RE = re.compile(
    r"^(?:(?:test|androidtest|testfixtures|sharedtest|instrumentationtest)(?:[a-z0-9_]*)"
    r"|[a-z0-9_]*(?:unittest|instrumentedtest|hosttest)"
    r"|(?:common|jvm|android|desktop|ios|iosarm64|iossimulatorarm64|iosx64|js|wasmjs|native|apple|macos|linux|mingw)test)$",
    re.IGNORECASE,
)


def is_test_source_set_name(source_set: str) -> bool:
    """Return True when a Gradle source-set directory name under src/<sourceSet> is a test source set."""
    clean = str(source_set or "").strip()
    if not clean:
        return False
    return bool(TEST_SOURCE_SET_RE.match(clean))


def is_kmp_or_android_test_path(rel_path: str) -> bool:
    """Return True when a relative file path sits inside a test source set or has a standard test filename."""
    norm = str(rel_path or "").replace("\\", "/").strip("/")
    if not norm:
        return False
    lower = norm.lower()
    parts = lower.split("/")
    if "src" in parts:
        for idx, part in enumerate(parts):
            if part == "src" and idx + 1 < len(parts):
                if is_test_source_set_name(parts[idx + 1]):
                    return True
    else:
        for part in parts[:-1]:
            if part in {
                "test", "tests", "androidtest", "testfixtures", "sharedtest",
                "instrumentationtest", "commontest", "iostest", "androidunittest",
                "androidhosttest", "iosapptests", "iosappuitests", "uitests",
            }:
                return True
            if lower.endswith(".swift") and part.endswith(("tests", "uitests")):
                return True
    if lower.endswith(("test.kt", "test.java", "tests.kt", "tests.java", "test.swift", "tests.swift")):
        return True
    return False


def strip_gradle_comments_preserving_strings(text: str) -> str:
    """Strip // and /* */ comments from Gradle script text while keeping string literals intact."""
    return re.sub(
        r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|//[^\n]*|/\*.*?\*/''',
        lambda m: m.group(1) or " ",
        text or "",
        flags=re.S,
    )


_KMP_PLUGIN_RE = re.compile(
    r"""(?:id\s*\(\s*["'](?:org\.jetbrains\.kotlin\.multiplatform|com\.android\.kotlin\.multiplatform\.library)["']\s*\)"""
    r"""|id\s+["'](?:org\.jetbrains\.kotlin\.multiplatform|com\.android\.kotlin\.multiplatform\.library)["']"""
    r"""|kotlin\s*\(\s*["']multiplatform["']\s*\)"""
    r"""|apply\s+plugin\s*:\s*["'](?:org\.jetbrains\.kotlin\.multiplatform|kotlin-multiplatform|com\.android\.kotlin\.multiplatform\.library)["'])"""
)

_AGP_KMP_LIB_PLUGIN_RE = re.compile(
    r"""(?:id\s*(?:\(\s*)?["']com\.android\.kotlin\.multiplatform\.library["']"""
    r"""|apply\s+plugin\s*:\s*["']com\.android\.kotlin\.multiplatform\.library["']"""
    r"""|\bandroidLibrary\s*\{)"""
)


def detect_kmp_build_script(build_text: str, resolved_text: str | None = None) -> dict[str, bool]:
    """Inspect a Gradle build script for applied KMP plugins and Android target styles.

    Ignores comments and `apply false` declarations so root plugin declarations never
    misclassify a Native Android module as KMP.
    """
    raw = resolved_text if resolved_text is not None else build_text
    clean = strip_gradle_comments_preserving_strings(raw)
    active_lines = [
        line for line in clean.splitlines()
        if not re.search(r"\bapply\s*\(\s*false\s*\)|\bapply\s+false\b", line)
    ]
    active_text = "\n".join(active_lines)
    has_kmp_plugin = bool(_KMP_PLUGIN_RE.search(active_text))
    has_agp_kmp_lib = bool(_AGP_KMP_LIB_PLUGIN_RE.search(active_text))
    has_android_target = bool(
        re.search(r"\bandroidTarget\s*\(|\bandroid\s*\(", active_text)
        or re.search(r"com\.android\.(?:application|library)", active_text)
    )
    has_ios_target = bool(
        re.search(r"\bios(?:X64|Arm64|SimulatorArm64)\s*\(|\bios\s*\(", active_text)
    )
    has_jvm_target = bool(re.search(r"\bjvm\s*\(", active_text))
    return {
        "has_kmp_plugin": has_kmp_plugin,
        "has_agp_kmp_library": has_agp_kmp_lib,
        "has_android_target": has_android_target or has_agp_kmp_lib,
        "has_ios_target": has_ios_target,
        "has_jvm_target": has_jvm_target,
    }


def _is_skipped(path: Path) -> bool:
    return bool(set(path.parts) & SKIP_PARTS)


def discover_source_roots(repo: Path) -> list[Path]:
    """All module source roots shaped like <module>/src/{main,androidMain,commonMain,iosMain,...}/{java,kotlin}.

    Uses a single pruned os.walk covering nested modules (:core:data) and KMP source sets without descending
    into package directories under src/ or build/output trees.
    """
    roots: dict[str, Path] = {}
    for root, dirs, _ in os.walk(repo, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
        if "src" in dirs:
            src_root = Path(root) / "src"
            for src_dir in _SOURCE_SET_DIRS:
                ss_path = src_root / src_dir
                if ss_path.is_dir():
                    for marker in _SRC_MARKERS:
                        candidate = ss_path / marker
                        if candidate.is_dir() and not _is_skipped(candidate):
                            roots[str(candidate)] = candidate
            dirs.remove("src")
    return [roots[k] for k in sorted(roots)]


def discover_res_dirs(repo: Path, primary_res: Path | None = None) -> list[Path]:
    """Discover all module res/ and composeResources/ directories without walking build/ or package trees."""
    res_dirs: list[Path] = []
    seen: set[Path] = set()
    if primary_res is not None and primary_res.is_dir():
        res_dirs.append(primary_res)
        seen.add(primary_res)
    for root, dirs, _ in os.walk(repo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_PARTS)
        root_path = Path(root)
        for top_res in ("res", "composeResources"):
            if top_res in dirs:
                cr = root_path / top_res
                if cr.is_dir() and cr not in seen and not _is_skipped(cr):
                    res_dirs.append(cr)
                    seen.add(cr)
                dirs.remove(top_res)
        if "src" in dirs:
            src_root = root_path / "src"
            try:
                source_sets = sorted(p for p in src_root.iterdir() if p.is_dir() and p.name not in SKIP_PARTS)
            except OSError:
                source_sets = []
            for ss in source_sets:
                for res_name in ("res", "composeResources"):
                    cand = ss / res_name
                    if cand.is_dir() and cand not in seen and not _is_skipped(cand):
                        res_dirs.append(cand)
                        seen.add(cand)
            dirs.remove("src")
    if not res_dirs and primary_res is not None:
        return [primary_res]
    return res_dirs


def module_name_of(source_root: Path, repo: Path) -> str:
    try:
        rel = source_root.relative_to(repo).as_posix()
    except ValueError:
        return ":unknown"
    module_path = rel.split("/src/")[0]
    if not module_path or module_path == ".":
        return ":app"
    return ":" + module_path.replace("/", ":")


_KMP_MODIFIER_GROUP = (
    r"(?:(?:public|internal|protected|private|suspend|inline|infix|operator|tailrec|external|open|abstract|final|sealed|data|value|enum|annotation|fun)\s+)*"
)

_KMP_ANNOT_GROUP = r"(?:@[A-Za-z0-9_.:]+\s*(?:\((?:[^()]|\([^()]*\))*\))?\s*)*"
_KMP_NESTED_TYPE_ARGS = r"(?:<(?:[^<>]|<(?:[^<>]|<[^<>]*>)*>)*>)"

_EXPECT_DECL_RE = re.compile(
    rf"(?m)^[ \t]*{_KMP_ANNOT_GROUP}{_KMP_MODIFIER_GROUP}expect\s+{_KMP_MODIFIER_GROUP}"
    rf"(class|interface|object|fun|val|var)\s+(?:{_KMP_NESTED_TYPE_ARGS}\s+)?"
    rf"(?:([A-Za-z0-9_.]+)(?:\s*{_KMP_NESTED_TYPE_ARGS})?\??\.)?([A-Za-z0-9_]+)\b"
)

_ACTUAL_DECL_RE = re.compile(
    rf"(?m)^[ \t]*{_KMP_ANNOT_GROUP}{_KMP_MODIFIER_GROUP}actual\s+{_KMP_MODIFIER_GROUP}"
    rf"(class|interface|object|typealias|fun|val|var)\s+(?:{_KMP_NESTED_TYPE_ARGS}\s+)?"
    rf"(?:([A-Za-z0-9_.]+)(?:\s*{_KMP_NESTED_TYPE_ARGS})?\??\.)?([A-Za-z0-9_]+)\b"
)

_KMP_ANDROID_JVM_PKG_GROUP = (
    r"(?:android\.(?:content|view|os|util|app|widget|graphics|database|net|provider|webkit|hardware|media|telephony|bluetooth|location|nfc|security|service|text|transition|animation|accessibilityservice)"
    r"|dalvik\.[A-Za-z0-9_]+"
    r"|java\.(?:io|net|sql|awt|nio|rmi|beans|lang\.reflect|util\.concurrent)"
    r"|javax\.swing)\.[A-Za-z0-9_.*]+"
)
_KMP_IOS_NATIVE_PKG_GROUP = (
    r"(?:platform\.(?:UIKit|Foundation|darwin|posix|CoreFoundation|CoreGraphics|QuartzCore|Security|StoreKit|AVFoundation|CoreLocation|CoreBluetooth|UserNotifications|WebKit|MapKit|Metal)"
    r"|kotlinx\.cinterop)\.[A-Za-z0-9_.*]+"
)

_KMP_FORBIDDEN_ANDROID_JVM_IMPORT_RE = re.compile(
    rf"(?m)^[ \t]*import[ \t]+({_KMP_ANDROID_JVM_PKG_GROUP})"
)

_KMP_FORBIDDEN_IOS_NATIVE_IMPORT_RE = re.compile(
    rf"(?m)^[ \t]*import[ \t]+({_KMP_IOS_NATIVE_PKG_GROUP})"
)

_KMP_FORBIDDEN_COMMON_IMPORT_RE = re.compile(
    rf"(?m)^[ \t]*import[ \t]+({_KMP_ANDROID_JVM_PKG_GROUP}|{_KMP_IOS_NATIVE_PKG_GROUP})"
)

_IOS_SOURCE_SETS = (
    "iosMain", "appleMain", "nativeMain", "iosArm64Main", "iosSimulatorArm64Main", "iosX64Main",
)
_ANDROID_JVM_SOURCE_SETS = (
    "androidMain", "jvmMain", "desktopMain", "jvmAndAndroidMain",
)


def _source_set_of_rel(norm_rel: str) -> str:
    parts = f"/{norm_rel}".split("/src/")
    if len(parts) < 2:
        return ""
    return parts[1].split("/", 1)[0]


def check_kmp_common_main_purity(repo: Path, changed_rel_paths: list[str] | None = None) -> tuple[bool, list[str]]:
    """Deterministically verify KMP source-set platform purity across commonMain, androidMain, and iosMain."""
    repo = repo.resolve()
    target_files: list[tuple[Path, str]] = []
    allowed_sets = {"commonMain", *_IOS_SOURCE_SETS, *_ANDROID_JVM_SOURCE_SETS}
    if changed_rel_paths is not None:
        for rel in changed_rel_paths:
            norm = str(rel or "").replace("\\", "/").strip("/")
            if not norm.endswith(".kt"):
                continue
            ss = _source_set_of_rel(norm)
            if ss in allowed_sets:
                fpath = repo / norm
                if fpath.is_file() and not _is_skipped(fpath):
                    target_files.append((fpath, ss))
    else:
        for mod_dir in _discover_kmp_common_modules(repo):
            for ss in sorted(allowed_sets):
                ss_dir = mod_dir / "src" / ss
                if ss_dir.is_dir():
                    for kt_file in sorted(ss_dir.rglob("*.kt")):
                        if not _is_skipped(kt_file):
                            target_files.append((kt_file, ss))

    violations: list[str] = []
    for kt_file, ss in target_files:
        try:
            raw = kt_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        clean = strip_gradle_comments_preserving_strings(raw)
        try:
            rel_posix = kt_file.relative_to(repo).as_posix()
        except ValueError:
            rel_posix = kt_file.name
        if ss == "commonMain":
            for match in _KMP_FORBIDDEN_COMMON_IMPORT_RE.finditer(clean):
                violations.append(
                    f"{rel_posix} imports forbidden platform API '{match.group(1)}' inside commonMain"
                )
        elif ss in _IOS_SOURCE_SETS:
            for match in _KMP_FORBIDDEN_ANDROID_JVM_IMPORT_RE.finditer(clean):
                violations.append(
                    f"{rel_posix} imports forbidden Android/JVM API '{match.group(1)}' inside {ss}"
                )
        elif ss in _ANDROID_JVM_SOURCE_SETS:
            for match in _KMP_FORBIDDEN_IOS_NATIVE_IMPORT_RE.finditer(clean):
                violations.append(
                    f"{rel_posix} imports forbidden iOS/Native API '{match.group(1)}' inside {ss}"
                )
    return len(violations) == 0, violations


def _parse_fun_arity(text: str, pos: int) -> int | None:
    """Parse top-level parameter count from `( ... )` immediately following a Kotlin `fun` name."""
    n = len(text)
    idx = pos
    while idx < n and text[idx] in " \t\r\n":
        idx += 1
    if idx < n and text[idx] == "<":
        # Skip trailing type arguments if any before `(`
        t_depth = 1
        idx += 1
        while idx < n and t_depth > 0:
            if text[idx] == "<":
                t_depth += 1
            elif text[idx] == ">":
                t_depth -= 1
            idx += 1
        while idx < n and text[idx] in " \t\r\n":
            idx += 1
    if idx >= n or text[idx] != "(":
        return None
    idx += 1
    paren_depth = 1
    angle_depth = 0
    bracket_depth = 0
    brace_depth = 0
    quote_char = ""
    segments: list[str] = []
    current: list[str] = []
    while idx < n and paren_depth > 0:
        ch = text[idx]
        if quote_char:
            current.append(ch)
            if ch == "\\" and idx + 1 < n:
                idx += 1
                current.append(text[idx])
            elif ch == quote_char:
                quote_char = ""
            idx += 1
            continue
        if ch in ('"', "'"):
            quote_char = ch
            current.append(ch)
        elif ch == "(":
            paren_depth += 1
            current.append(ch)
        elif ch == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break
            current.append(ch)
        elif ch == "<":
            angle_depth += 1
            current.append(ch)
        elif ch == ">" and (idx == 0 or text[idx - 1] != "-"):
            angle_depth = max(0, angle_depth - 1)
            current.append(ch)
        elif ch == "[":
            bracket_depth += 1
            current.append(ch)
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
            current.append(ch)
        elif ch == "{":
            brace_depth += 1
            current.append(ch)
        elif ch == "}":
            brace_depth = max(0, brace_depth - 1)
            current.append(ch)
        elif ch == "," and paren_depth == 1 and angle_depth == 0 and bracket_depth == 0 and brace_depth == 0:
            segments.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        idx += 1
    if paren_depth != 0:
        return None
    tail = "".join(current).strip()
    if tail:
        segments.append(tail)
    return len([seg for seg in segments if seg])


def _normalize_decl_kind(raw_kind: str) -> str:
    if raw_kind in ("class", "interface", "object"):
        return "type"
    return raw_kind


def _extract_kmp_declarations(source_dir: Path, pattern: re.Pattern[str]) -> set[str]:
    names: set[str] = set()
    for name, _ in _extract_kmp_declaration_signatures(source_dir, pattern).items():
        names.add(name)
    return names


def _extract_kmp_declaration_signatures(
    source_dir: Path, pattern: re.Pattern[str]
) -> dict[str, set[tuple[str, str, int | None]]]:
    """Return mapping of symbol_name -> set of (kind_group, receiver_base, fun_arity)."""
    decls: dict[str, set[tuple[str, str, int | None]]] = {}
    if not source_dir.is_dir():
        return decls
    for kt_file in sorted(source_dir.rglob("*.kt")):
        if _is_skipped(kt_file):
            continue
        try:
            raw = kt_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        clean = strip_gradle_comments_preserving_strings(raw)
        for match in pattern.finditer(clean):
            raw_kind = match.group(1)
            raw_recv = match.group(2) or ""
            sym_name = match.group(3)
            kind_group = _normalize_decl_kind(raw_kind)
            recv_base = raw_recv.rsplit(".", 1)[-1] if raw_recv else ""
            arity = _parse_fun_arity(clean, match.end()) if raw_kind == "fun" else None
            decls.setdefault(sym_name, set()).add((kind_group, recv_base, arity))
    return decls


def _format_sig(sym: str, sig: tuple[str, str, int | None]) -> str:
    kind_group, recv_base, arity = sig
    target = f"{recv_base}.{sym}" if recv_base else sym
    if kind_group == "fun" and arity is not None:
        return f"fun {target}/{arity}"
    return f"{kind_group} {target}"


def _signature_matches(
    exp_sig: tuple[str, str, int | None],
    act_sigs: set[tuple[str, str, int | None]],
) -> bool:
    exp_kind, exp_recv, exp_arity = exp_sig
    for act_kind, act_recv, act_arity in act_sigs:
        kind_ok = (exp_kind == act_kind) or (exp_kind == "type" and act_kind == "typealias")
        if not kind_ok:
            continue
        if act_kind == "typealias":
            return True
        if exp_recv != act_recv:
            continue
        if exp_kind == "fun" and exp_arity is not None and act_arity is not None and exp_arity != act_arity:
            continue
        return True
    return False


def _discover_kmp_common_modules(repo: Path) -> list[Path]:
    """Discover module directories containing src/commonMain without walking inside src/ or skipped folders."""
    modules: list[Path] = []
    for root, dirs, _ in os.walk(repo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_PARTS)
        if "src" in dirs:
            root_path = Path(root)
            if (root_path / "src" / "commonMain").is_dir():
                modules.append(root_path)
            dirs.remove("src")
    return modules


def has_kmp_common_main(repo: Path) -> bool:
    """Fast O(1)/bounded check for any non-skipped src/commonMain directory in repo."""
    for quick in ("src/commonMain", "composeApp/src/commonMain", "shared/src/commonMain"):
        if (repo / quick).is_dir():
            return True
    for root, dirs, _ in os.walk(repo, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
        if "src" in dirs:
            if (Path(root) / "src" / "commonMain").is_dir():
                return True
            dirs.remove("src")
    return False


def check_kmp_expect_actual_pairs(repo: Path, changed_rel_paths: list[str] | None = None) -> tuple[bool, str]:
    """Deterministically verify expect/actual pairing and signature compatibility in modified KMP modules.

    Only inspects KMP modules that have both `src/commonMain` and at least one mobile
    platform source set (`src/androidMain`, `src/iosMain`, `src/appleMain`, etc.) and were touched by
    the current change set (or all KMP modules when changed_rel_paths is None).
    Native Android modules without `src/commonMain` are skipped with zero overhead.
    """
    repo = repo.resolve()
    candidate_module_dirs: set[Path] = set()
    if changed_rel_paths is not None:
        for rel in changed_rel_paths:
            norm = str(rel or "").replace("\\", "/").strip("/")
            if not norm.endswith(".kt"):
                continue
            if norm.startswith("src/"):
                mod_dir = repo
            elif "/src/" in norm:
                mod_prefix = norm.split("/src/", 1)[0]
                mod_dir = repo / mod_prefix if mod_prefix and mod_prefix != "." else repo
            else:
                continue
            if (mod_dir / "src" / "commonMain").is_dir():
                candidate_module_dirs.add(mod_dir)
    else:
        for mod_dir in _discover_kmp_common_modules(repo):
            candidate_module_dirs.add(mod_dir)

    if not candidate_module_dirs:
        return True, "no KMP commonMain changes require expect/actual check"

    missing_reports: list[str] = []
    checked_modules = 0
    for mod_dir in sorted(candidate_module_dirs):
        common_main = mod_dir / "src" / "commonMain"
        expect_decls = _extract_kmp_declaration_signatures(common_main, _EXPECT_DECL_RE)
        if not expect_decls:
            continue
        checked_modules += 1
        try:
            rel_mod = mod_dir.relative_to(repo).as_posix()
            mod_label = ":" + rel_mod.replace("/", ":") if rel_mod and rel_mod != "." else ":"
        except ValueError:
            mod_label = mod_dir.name

        def _verify_platform_target(target_label: str, platform_dirs: list[Path]) -> None:
            actual_decls: dict[str, set[tuple[str, str, int | None]]] = {}
            for p_dir in platform_dirs:
                for sym, sigs in _extract_kmp_declaration_signatures(p_dir, _ACTUAL_DECL_RE).items():
                    actual_decls.setdefault(sym, set()).update(sigs)
            for sym in sorted(expect_decls):
                if sym not in actual_decls:
                    missing_reports.append(f"{mod_label} expect '{sym}' is missing actual in {target_label}")
                    continue
                act_sigs = actual_decls[sym]
                for exp_sig in sorted(expect_decls[sym], key=lambda s: (s[0], s[1], -1 if s[2] is None else s[2])):
                    if not _signature_matches(exp_sig, act_sigs):
                        exp_str = _format_sig(sym, exp_sig)
                        act_str = ", ".join(_format_sig(sym, a) for a in sorted(act_sigs, key=lambda s: (s[0], s[1], -1 if s[2] is None else s[2])))
                        missing_reports.append(
                            f"{mod_label} expect '{sym}' has incompatible actual in {target_label} (expected {exp_str}, found {act_str})"
                        )

        # Check Android platform source sets if present in this module
        android_dirs = [
            mod_dir / "src" / d
            for d in ("androidMain", "jvmAndAndroidMain", "mobileMain")
            if (mod_dir / "src" / d).is_dir()
        ]
        if android_dirs:
            _verify_platform_target("androidMain", android_dirs)

        # Check iOS/Apple platform source sets if present in this module
        ios_dirs = [
            mod_dir / "src" / d
            for d in ("iosMain", "appleMain", "nativeMain", "mobileMain", "iosArm64Main", "iosSimulatorArm64Main", "iosX64Main")
            if (mod_dir / "src" / d).is_dir()
        ]
        if any((mod_dir / "src" / d).is_dir() for d in ("iosMain", "appleMain", "nativeMain", "iosArm64Main", "iosSimulatorArm64Main", "iosX64Main")):
            _verify_platform_target("iosMain", ios_dirs)

    if missing_reports:
        return False, "KMP_EXPECT_ACTUAL_MISMATCH: " + "; ".join(missing_reports)
    return True, f"KMP expect/actual pairing verified ({checked_modules} module(s) with expect declarations)"



