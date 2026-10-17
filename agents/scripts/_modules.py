"""Multi-module and KMP source-set discovery shared by lints, audits, classifiers, and the doctor."""
from __future__ import annotations

import re
from pathlib import Path

SKIP_PARTS = {".git", "build", ".gradle", ".idea", ".agents", ".harness-backup", ".harness-setup", "node_modules", "__pycache__"}

_SRC_MARKERS = ("java", "kotlin")
_SOURCE_SET_DIRS = (
    "main",
    "androidMain",
    "commonMain",
    "iosMain",
    "iosArm64Main",
    "iosSimulatorArm64Main",
    "iosX64Main",
)

# Canonical Gradle test source sets (Android + KMP: test, androidTest, testFixtures, sharedTest,
# instrumentationTest, commonTest, iosTest, iosSimulatorArm64Test, androidUnitTest, androidHostTest, etc.)
TEST_SOURCE_SET_RE = re.compile(
    r"^(?:(?:test|androidtest|testfixtures|sharedtest|instrumentationtest)(?:[a-z0-9_]*)"
    r"|[a-z0-9_]*(?:unittest|instrumentedtest|hosttest)"
    r"|(?:common|jvm|android|ios|iosarm64|iossimulatorarm64|iosx64|js|wasmjs|native|apple|macos|linux|mingw)test)$",
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
            if part in {"test", "tests", "androidtest", "testfixtures", "sharedtest", "instrumentationtest", "commontest", "iostest", "androidunittest", "androidhosttest"}:
                return True
    if lower.endswith(("test.kt", "test.java", "tests.kt", "tests.java")):
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

    Recursive globs cover nested modules (:core:data) and KMP source sets.
    """
    roots: dict[str, Path] = {}
    for src_dir in _SOURCE_SET_DIRS:
        for marker in _SRC_MARKERS:
            for candidate in repo.glob(f"**/src/{src_dir}/{marker}"):
                if candidate.is_dir() and not _is_skipped(candidate):
                    roots[str(candidate)] = candidate
    return [roots[k] for k in sorted(roots)]


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

_EXPECT_DECL_RE = re.compile(
    rf"(?m)^[ \t]*(?:@[A-Za-z0-9_.]+\s*(?:\([^)]*\))?\s*)*{_KMP_MODIFIER_GROUP}expect\s+{_KMP_MODIFIER_GROUP}"
    r"(class|interface|object|fun|val|var)\s+(?:<[^>]+>\s*)?(?:[A-Za-z0-9_.]+(?:\s*<[^>;{}=]*>)?\??\.)?([A-Za-z0-9_]+)\b"
)

_ACTUAL_DECL_RE = re.compile(
    rf"(?m)^[ \t]*(?:@[A-Za-z0-9_.]+\s*(?:\([^)]*\))?\s*)*{_KMP_MODIFIER_GROUP}actual\s+{_KMP_MODIFIER_GROUP}"
    r"(class|interface|object|typealias|fun|val|var)\s+(?:<[^>]+>\s*)?(?:[A-Za-z0-9_.]+(?:\s*<[^>;{}=]*>)?\??\.)?([A-Za-z0-9_]+)\b"
)


def _extract_kmp_declarations(source_dir: Path, pattern: re.Pattern[str]) -> set[str]:
    names: set[str] = set()
    if not source_dir.is_dir():
        return names
    for kt_file in sorted(source_dir.rglob("*.kt")):
        if _is_skipped(kt_file):
            continue
        try:
            raw = kt_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        clean = strip_gradle_comments_preserving_strings(raw)
        for match in pattern.finditer(clean):
            names.add(match.group(2))
    return names


def check_kmp_expect_actual_pairs(repo: Path, changed_rel_paths: list[str] | None = None) -> tuple[bool, str]:
    """Deterministically verify expect/actual pairing in modified KMP modules.

    Only inspects KMP modules that have both `src/commonMain` and at least one mobile
    platform source set (`src/androidMain`, `src/iosMain`, etc.) and were touched by
    the current change set (or all KMP modules when changed_rel_paths is None).
    Native Android modules without `src/commonMain` are skipped with zero overhead.
    """
    repo = repo.resolve()
    candidate_module_dirs: set[Path] = set()
    if changed_rel_paths is not None:
        for rel in changed_rel_paths:
            norm = str(rel or "").replace("\\", "/").strip("/")
            if "/src/" in norm and norm.endswith(".kt"):
                mod_prefix = norm.split("/src/", 1)[0]
                mod_dir = repo / mod_prefix if mod_prefix and mod_prefix != "." else repo
                if (mod_dir / "src" / "commonMain").is_dir():
                    candidate_module_dirs.add(mod_dir)
    else:
        for common_dir in repo.glob("**/src/commonMain"):
            if common_dir.is_dir() and not _is_skipped(common_dir):
                candidate_module_dirs.add(common_dir.parent.parent)

    if not candidate_module_dirs:
        return True, "no KMP commonMain changes require expect/actual check"

    missing_reports: list[str] = []
    checked_modules = 0
    for mod_dir in sorted(candidate_module_dirs):
        common_main = mod_dir / "src" / "commonMain"
        expect_names = _extract_kmp_declarations(common_main, _EXPECT_DECL_RE)
        if not expect_names:
            continue
        checked_modules += 1
        try:
            rel_mod = mod_dir.relative_to(repo).as_posix()
            mod_label = ":" + rel_mod.replace("/", ":") if rel_mod and rel_mod != "." else ":"
        except ValueError:
            mod_label = mod_dir.name

        # Check Android platform source sets if present in this module
        android_dirs = [
            mod_dir / "src" / d
            for d in ("androidMain", "jvmAndAndroidMain", "mobileMain")
            if (mod_dir / "src" / d).is_dir()
        ]
        if (mod_dir / "src" / "androidMain").is_dir():
            android_actuals: set[str] = set()
            for android_d in android_dirs:
                android_actuals |= _extract_kmp_declarations(android_d, _ACTUAL_DECL_RE)
            missing_android = sorted(expect_names - android_actuals)
            for sym in missing_android:
                missing_reports.append(f"{mod_label} expect '{sym}' is missing actual in androidMain")

        # Check iOS platform source sets if present in this module
        ios_dirs = [
            mod_dir / "src" / d
            for d in ("iosMain", "appleMain", "nativeMain", "mobileMain", "iosArm64Main", "iosSimulatorArm64Main", "iosX64Main")
            if (mod_dir / "src" / d).is_dir()
        ]
        if any((mod_dir / "src" / d).is_dir() for d in ("iosMain", "iosArm64Main", "iosSimulatorArm64Main", "iosX64Main")):
            ios_actuals: set[str] = set()
            for ios_d in ios_dirs:
                ios_actuals |= _extract_kmp_declarations(ios_d, _ACTUAL_DECL_RE)
            missing_ios = sorted(expect_names - ios_actuals)
            for sym in missing_ios:
                missing_reports.append(f"{mod_label} expect '{sym}' is missing actual in iosMain")

    if missing_reports:
        return False, "KMP_EXPECT_ACTUAL_MISMATCH: " + "; ".join(missing_reports)
    return True, f"KMP expect/actual pairing verified ({checked_modules} module(s) with expect declarations)"


