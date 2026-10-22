"""Fast Kotlin pre-build sanity for this Android app.

Usage:
  python .agents/scripts/fast_kt_lint.py
  python .agents/scripts/fast_kt_lint.py --all
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _product import PACKAGE_PREFIX  # noqa: E402
from _repo_files import REPO, changed_paths, repo_glob  # noqa: E402

try:
    from _product import DI_FRAMEWORK, SUPPORTED_LOCALES, UI_FRAMEWORK
except Exception:
    DI_FRAMEWORK = "hilt"
    SUPPORTED_LOCALES = ["en", "ar"]
    UI_FRAMEWORK = "compose"


enable_line_buffered_stdio()

FQCN_PATTERN = re.compile(
    rf"\b(androidx\.[a-zA-Z0-9_.]+|{re.escape(PACKAGE_PREFIX)}\.[a-zA-Z0-9_.]+|android\.(view|widget|graphics|os|content)\.[a-zA-Z0-9_.]+|java\.util\.[a-zA-Z0-9_.]+)\b"
)
FQCN_WHITELIST = re.compile(
    r"^(?:android\.os\.Build(?:\.VERSION(?:\.SDK_INT|_CODES)?)?|java\.util\.(?:UUID|Locale|Date|Objects)|androidx\.annotation\.\w+|androidx\.compose\.\w+\.Experimental\w+)$"
)

WILDCARD_IMPORT_PATTERN = re.compile(r"^import\s+[a-zA-Z0-9_.]+\.\*")
STATE_CLASS_PATTERN = re.compile(r"data\s+class\s+[A-Za-z0-9_]*State\b")
RUNBLOCKING_PATTERN = re.compile(r"\brunBlocking\s*(\(|{)")
UNIMPLEMENTED_STUB_PATTERN = re.compile(r"\b(TODO\s*\(|throw\s+NotImplementedError\s*\()")
DOUBLE_BANG_PATTERN = re.compile(r"[a-zA-Z0-9_\)\]]\s*!!")
DIAGNOSTIC_PROBE_PATTERN = re.compile(r"(?:\[HARNESS-PROBE\]|\bHARNESS_PROBE\b)")
CLASS_ENTRY_PATTERN = re.compile(
    r"^(?:(?:public|internal|open)\s+)?class\s+\w+[^{]*:\s*(?:BaseComposeFragment|BaseFragment|Fragment|AppCompatActivity|ComponentActivity|FragmentActivity|DialogFragment|BottomSheetDialogFragment)\b"
)
PREVIEW_AR = re.compile(
    r"(?:@Preview\b[\s\S]{0,500}?(?:locale\s*=\s*\"ar\"|LayoutDirection\.Rtl|ArabicPreview|\bArPreview\b|//\s*locale\s*=\s*\"ar\")|@(?:DualLocale|Arabic|Rtl|MultiLocale)Previews?\b)"
)
PREVIEW_EN = re.compile(
    r"(?:@Preview\b[\s\S]{0,500}?(?:locale\s*=\s*\"en\"|LayoutDirection\.Ltr|EnglishPreview|\bEnPreview\b|//\s*locale\s*=\s*\"en\")|@(?:DualLocale|English|Ltr|MultiLocale|PreviewLightDark)Previews?\b)"
)
PREVIEW_SURFACE_SUFFIXES = (
    "Screen.kt",
    "Card.kt",
    "Dialog.kt",
    "BottomSheet.kt",
    "Sheet.kt",
    "Banner.kt",
)

BIDI_TROJAN_PATTERN = re.compile(r"[\u202A-\u202E\u2066-\u2069\u200B]")
SECRET_PATTERNS = (
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b")),
    ("OpenAI/Anthropic Key", re.compile(r"\b(?:sk-[a-zA-Z0-9]{20,}|sk-proj-[a-zA-Z0-9_-]{20,}|sk-ant-[a-zA-Z0-9_-]{20,})\b")),
    ("Stripe Secret Key", re.compile(r"\b(?:sk|rk)_live_[0-9a-zA-Z]{24,}\b")),
    ("GitHub Personal Access Token", re.compile(r"\bghp_[0-9a-zA-Z]{36}\b")),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private Key", re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----")),
)
CLEARTEXT_URL_PATTERN = re.compile(r'"http://([^"/]+)(?:/[^"]*)?"')
CLEARTEXT_WHITELIST_HOSTS = {
    "localhost", "127.0.0.1", "10.0.2.2",
    "schemas.android.com", "schemas.xmlsoap.org", "w3.org", "www.w3.org",
}


def _in_string_or_comment(line: str, index: int) -> bool:
    """True when index sits inside a // comment, /* ... */ block comment, or double-quoted string."""
    in_string = False
    in_block = False
    escaped = False
    i = 0
    while i < index and i < len(line):
        ch = line[i]
        if in_block:
            if ch == "*" and i + 1 < len(line) and line[i + 1] == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if not in_string and ch == "/" and i + 1 < len(line):
            if line[i + 1] == "/":
                return True
            if line[i + 1] == "*":
                in_block = True
                i += 2
                continue
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        i += 1
    return in_string or in_block


def is_preview_surface(filename: str, text: str = "") -> bool:
    if filename.endswith(PREVIEW_SURFACE_SUFFIXES):
        return True
    if text:
        if re.search(r"\b(?:Scaffold|ModalNavigationDrawer)\s*\(", text) and "@Composable" in text:
            return True
        if re.search(r"@(?:Destination|Route)\b", text):
            return True
    return False


def requires_state_previews(filename: str) -> bool:
    return filename.endswith("Screen.kt")


def is_stateful_container_only(text: str) -> bool:
    funcs = list(
        re.finditer(
            r"@Composable(?:\s+@[A-Za-z0-9_.]+(?:\([^)]*\))?)*\s*(?:(?:inline|private|public|internal|actual)\s+)*fun\s+(?:<[^>]+>\s*)?(\w+)\s*\((.*?)\)",
            text,
            re.DOTALL,
        )
    )
    if not funcs:
        return False
    for m in funcs:
        fn_name = m.group(1)
        params = m.group(2).lower()
        if "viewmodel" not in params and "hiltviewmodel" not in params and "screenmodel" not in params:
            return False
        if fn_name.endswith(("Content", "Stateless", "Preview", "Item", "Row", "Card", "Header", "Footer")):
            return False
    return True


def get_modified_lines_map(repo: Path, files: list[Path], cached: bool = False) -> dict[Path, set[int] | None]:
    """Select changed lines with one batched diff and one NUL-safe inventory.

    None means lint every line. Failed/ambiguous Git output never suppresses lint.
    Numstat supplies literal filenames in patch order, including tabs/newlines,
    so quoted patch headers need no platform-dependent filename decoding.
    """
    result: dict[Path, set[int] | None] = {path: None for path in files}
    if not files:
        return result
    root = repo.resolve()
    by_relative: dict[str, list[Path]] = {}
    for path in files:
        try:
            absolute = path if path.is_absolute() else root / path
            relative = absolute.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        by_relative.setdefault(relative, []).append(path)
    if not by_relative:
        return result

    base = ["git", "--literal-pathspecs", "diff", "--no-ext-diff", "--no-textconv",
            "--no-color", "--no-renames", "--numstat", "-z", "--patch", "-U0", "--ignore-cr-at-eol"]
    if cached:
        base.append("--cached")
    # Avoid Windows command-line limits on very large tasks. Extra diff paths
    # are filtered in memory; the process count remains independent of file count.
    paths = list(by_relative)
    if sum(len(path.encode("utf-16-le")) // 2 + 3 for path in paths) > 20000:
        paths = []
    def run(arguments: list[str]):
        return subprocess.run(arguments, cwd=repo, capture_output=True, check=False)

    try:
        proc = run([*base, "HEAD", "--", *paths])
        if proc.returncode != 0 and cached:
            proc = run([*base, "--", *paths])
        if proc.returncode != 0:
            return result
        inventory = run(["git", "ls-files", "--cached", "-z"])
    except OSError:
        return result
    if inventory.returncode != 0:
        return result
    tracked = {os.fsdecode(name) for name in inventory.stdout.split(b"\0") if name}
    for relative, originals in by_relative.items():
        if relative in tracked:
            for path in originals:
                result[path] = set()
    if not proc.stdout.strip(b"\0"):
        return result
    stats, separator, patch = proc.stdout.partition(b"\0\0")
    entries = [entry.split(b"\t", 2) for entry in stats.split(b"\0") if entry]
    sections = re.split(rb"(?m)^diff --git ", patch)[1:]
    if not separator or len(entries) != len(sections) or any(len(entry) != 3 for entry in entries):
        return {path: None for path in files}
    hunk_re = re.compile(rb"(?m)^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")
    for entry, section in zip(entries, sections):
        relative = os.fsdecode(entry[2])
        if relative not in by_relative:
            continue
        if entry[0] == b"-" or entry[1] == b"-":
            for path in by_relative[relative]:
                result[path] = None
            continue
        modified: set[int] = set()
        for match in hunk_re.finditer(section):
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) is not None else 1
            modified.update(range(start, start + count))
        for path in by_relative[relative]:
            result[path] = set(modified)
    return result


def lint_file(file_path: Path, modified_lines: set[int] | None = None) -> list[dict]:
    from _modules import is_kmp_or_android_test_path

    issues = []
    posix = file_path.as_posix()
    is_test = is_kmp_or_android_test_path(posix)

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
    except Exception as e:
        return [{"file": str(file_path), "line": 1, "type": "IO_ERROR", "msg": str(e)}]

    has_fragment_activity_in_diff = False
    has_android_entry_point = False
    has_compose_function_in_diff = False
    has_compose_imports = any("androidx.compose" in l or "org.jetbrains.compose" in l for l in lines[:60])
    in_block_comment = False
    in_triple_string = False

    for idx, line in enumerate(lines, 1):
        trimmed = line.strip()

        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
            continue

        if trimmed.startswith("/*"):
            if "*/" not in trimmed[2:]:
                in_block_comment = True
            continue

        if in_triple_string:
            if '"""' in line:
                in_triple_string = False
            continue

        if '"""' in trimmed:
            count = trimmed.count('"""')
            if count % 2 != 0:
                in_triple_string = True

        # Track full-file markers
        if "@AndroidEntryPoint" in trimmed:
            has_android_entry_point = True

        # Track if new fragment/activity class or compose function was modified/added
        is_line_modified = modified_lines is None or idx in modified_lines

        if CLASS_ENTRY_PATTERN.search(trimmed) and not trimmed.startswith("abstract class"):
            if is_line_modified:
                has_fragment_activity_in_diff = True

        if "@Composable" in trimmed:
            if is_line_modified:
                has_compose_function_in_diff = True

        # Line-level checks apply ONLY to added/modified lines in diff-scoped mode
        if not is_line_modified:
            continue

        if BIDI_TROJAN_PATTERN.search(line):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "TROJAN_SOURCE_BIDI",
                "msg": f"Invisible Bidi control / Trojan Source character detected in code: '{trimmed}'. Invisible directional formatting characters are prohibited (CVE-2021-42574).",
            })

        if not is_test:
            for sec_name, sec_re in SECRET_PATTERNS:
                if sec_re.search(line):
                    issues.append({
                        "file": str(file_path),
                        "line": idx,
                        "type": "HARDCODED_SECRET",
                        "msg": f"Hardcoded credential detected ({sec_name}). Store credentials in local.properties or secure build configuration.",
                    })
                    break

            for m_url in CLEARTEXT_URL_PATTERN.finditer(line):
                host = m_url.group(1).lower().split(":")[0]
                if host not in CLEARTEXT_WHITELIST_HOSTS and not any(host.endswith("." + wh) for wh in CLEARTEXT_WHITELIST_HOSTS):
                    issues.append({
                        "file": str(file_path),
                        "line": idx,
                        "type": "INSECURE_CLEARTEXT_TRAFFIC",
                        "msg": f"Insecure cleartext HTTP URL detected: '{m_url.group(0)}'. Use HTTPS to prevent MITM attacks or configure network_security_config.xml.",
                    })
                    break

        if WILDCARD_IMPORT_PATTERN.match(trimmed):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "WILDCARD_IMPORT",
                "msg": f"Wildcard import forbidden: '{trimmed}'. Use explicit imports.",
            })

        if not (
            trimmed.startswith("import ")
            or trimmed.startswith("package ")
            or trimmed.startswith("//")
            or trimmed.startswith("/*")
            or trimmed.startswith("*")
            or trimmed.startswith("@file:OptIn")
            or trimmed.startswith("@OptIn")
        ):
            for match in FQCN_PATTERN.finditer(line):
                val = match.group(0)
                if FQCN_WHITELIST.match(val):
                    continue
                if _in_string_or_comment(line, match.start()):
                    continue
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "INLINE_FQCN",
                    "msg": f"Inline FQCN forbidden: '{trimmed}'. Add import at top with typealiases for collisions.",
                })
                break

        if not is_test and any(not _in_string_or_comment(line, m_rb.start()) for m_rb in RUNBLOCKING_PATTERN.finditer(line)):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "RUNBLOCKING_ANR",
                "msg": "runBlocking found in production code. Use viewModelScope.launch or coroutineScope to avoid ANRs.",
            })

        if is_test and any(not _in_string_or_comment(line, m_trb.start()) for m_trb in RUNBLOCKING_PATTERN.finditer(line)):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "TEST_RUNBLOCKING",
                "msg": "runBlocking found in test file. Use runTest { ... } with StandardTestDispatcher / advanceUntilIdle() for robust coroutine testing.",
            })

        if not is_test and any(not _in_string_or_comment(line, m_stub.start()) for m_stub in UNIMPLEMENTED_STUB_PATTERN.finditer(line)):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "UNIMPLEMENTED_STUB",
                "msg": f"Unimplemented stub found in production code: '{trimmed}'. Provide complete implementation.",
            })

        if not is_test and any(not _in_string_or_comment(line, m_db.start()) for m_db in DOUBLE_BANG_PATTERN.finditer(line)):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "UNCHECKED_DOUBLE_BANG",
                "msg": f"Unchecked double-bang (!!) found in production code: '{trimmed}'. Replace with safe call (?.) or checkNotNull()/requireNotNull() with clear message.",
            })

        if DIAGNOSTIC_PROBE_PATTERN.search(trimmed):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "STRAY_DIAGNOSTIC_PROBE",
                "msg": f"Stray diagnostic probe detected: '{trimmed}'. Remove temporary probes before review/delivery.",
            })

        if STATE_CLASS_PATTERN.search(trimmed) and (has_compose_imports or has_compose_function_in_diff):
            has_ann = "@Immutable" in trimmed or "@Stable" in trimmed
            if not has_ann:
                lookback_idx = idx - 2
                annotations = []
                while lookback_idx >= 0:
                    prev_line = lines[lookback_idx].strip()
                    if prev_line.startswith("@"):
                        annotations.append(prev_line)
                        lookback_idx -= 1
                    elif not prev_line or prev_line.startswith("//") or prev_line.startswith("/*") or prev_line.startswith("*"):
                        lookback_idx -= 1
                    else:
                        break
                ann_block = " ".join(annotations)
                has_ann = "@Immutable" in ann_block or "@Stable" in ann_block

            if not has_ann:
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "MISSING_IMMUTABLE",
                    "msg": f"MVI State class '{trimmed}' is missing @Immutable or @Stable for Compose stability.",
                })

    uses_hilt = DI_FRAMEWORK.lower() == "hilt" or "@Inject" in text or "hiltViewModel" in text or "hiltNavGraphViewModels" in text
    if uses_hilt and has_fragment_activity_in_diff and not has_android_entry_point and not is_test:
        issues.append({
            "file": str(file_path),
            "line": 1,
            "type": "MISSING_HILT_ENTRY_POINT",
            "msg": "Fragment / Activity class is missing '@AndroidEntryPoint' for Hilt dependency injection.",
        })

    posix_lower = f"/{posix.lower()}"
    is_ios_source_set = bool(re.search(r"/src/ios[^/]*/", posix_lower))
    is_common_main = "/src/commonmain/" in posix_lower
    has_non_expect_composable = bool(
        re.search(
            r"@Composable(?:\s+@[A-Za-z0-9_.]+(?:\([^)]*\))?)*\s+(?!(?:(?:public|internal|private|protected|inline)\s+)*expect\b)(?:(?:public|internal|private|protected|inline|actual|open|override)\s+)*fun\b",
            text,
        )
    )
    if (
        not is_test
        and not is_ios_source_set
        and has_compose_function_in_diff
        and has_non_expect_composable
        and is_preview_surface(file_path.name, text)
    ):
        if not is_stateful_container_only(text):
            has_rtl = any(loc in {"ar", "he", "fa", "ur", "iw"} for loc in SUPPORTED_LOCALES)
            has_ltr = any(loc not in {"ar", "he", "fa", "ur", "iw"} for loc in SUPPORTED_LOCALES)
            needs_bidirectional = has_rtl and has_ltr and not is_common_main
            extra = " plus Loading/Empty/Error." if requires_state_previews(file_path.name) else "."
            if needs_bidirectional:
                if not PREVIEW_AR.search(text) or not PREVIEW_EN.search(text):
                    issues.append({
                        "file": str(file_path),
                        "line": 1,
                        "type": "MISSING_COMPOSE_PREVIEW",
                        "msg": (
                            f"'{file_path.name}' needs dual-locale @Preview "
                            f"(locale=\"ar\" and locale=\"en\"){extra}"
                        ),
                    })
            else:
                if not PREVIEW_EN.search(text) and "@Preview" not in text:
                    issues.append({
                        "file": str(file_path),
                        "line": 1,
                        "type": "MISSING_COMPOSE_PREVIEW",
                        "msg": f"'{file_path.name}' needs @Preview composable function{extra}",
                    })

    is_fragment = bool(re.search(r"class\s+\w+[^{]*:\s*(?:BaseFragment|Fragment|DialogFragment|BottomSheetDialogFragment)\b", text))
    if is_fragment and not is_test:
        binding_decl = re.search(r"private\s+var\s+(_binding\w*)\s*:\s*[A-Za-z0-9_]+Binding\?\s*=\s*null", text)
        if binding_decl:
            var_name = binding_decl.group(1)
            ondestroy_match = re.search(r"override\s+fun\s+onDestroyView\s*\([^)]*\)\s*\{([^}]*)\}", text, re.DOTALL)
            nullified = ondestroy_match and (f"{var_name} = null" in ondestroy_match.group(1) or f"{var_name}=null" in ondestroy_match.group(1))
            if not nullified:
                issues.append({
                    "file": str(file_path),
                    "line": 1,
                    "type": "VIEWBINDING_MEMORY_LEAK",
                    "msg": f"Fragment ViewBinding memory leak: '{var_name}' is declared but not set to null in onDestroyView(). Set '{var_name} = null' in onDestroyView() to prevent retaining the View hierarchy.",
                })

    return issues


def lint_java_file(file_path: Path, modified_lines: set[int] | None = None) -> list[dict]:
    """Inline FQCNs in Java (the only rule here that applies to Java).

    Real app: an inline FQCN in PaymentActivity.java passed preflight (Kotlin only) and was found by
    the convention reviewer, which cost a blocked review round, a resume and a second full review.
    """
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return [{"file": str(file_path), "line": 1, "type": "IO_ERROR", "msg": str(e)}]
    issues: list[dict] = []
    # Java has no import alias: when the simple name is already imported from another package, or is the
    # file's own class, the qualified name is the only way to write it.
    imported: dict[str, str] = {}
    for line in lines:
        found = re.match(r"\s*import\s+(?!static\b)([\w.]+)\s*;", line)
        if found:
            imported[found.group(1).rsplit(".", 1)[-1]] = found.group(1)
    declared = set(re.findall(r"\b(?:class|interface|enum|record)\s+(\w+)", "\n".join(lines)))

    def unavoidable(qualified: str) -> bool:
        parts = qualified.split(".")
        type_at = next((i for i, part in enumerate(parts) if part[:1].isupper()), None)
        if type_at is None:
            return False
        simple, owner = parts[type_at], ".".join(parts[: type_at + 1])
        return simple in declared or (simple in imported and imported[simple] != owner)

    in_block_comment = False
    for idx, line in enumerate(lines, 1):
        trimmed = line.strip()
        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
            continue
        if trimmed.startswith("/*"):
            if "*/" not in trimmed[2:]:
                in_block_comment = True
            continue
        if modified_lines is not None and idx not in modified_lines:
            continue
        if trimmed.startswith(("import ", "package ", "//", "*", "@")):
            continue
        for match in FQCN_PATTERN.finditer(line):
            val = match.group(0)
            if FQCN_WHITELIST.match(val) or _in_string_or_comment(line, match.start()) or unavoidable(val):
                continue
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "INLINE_FQCN",
                "msg": f"Inline FQCN forbidden: '{trimmed}'. Add an import at the top.",
            })
            break
    return issues


def lint_build_script(file_path: Path) -> list[dict[str, Any]]:
    issues = []
    try:
        txt = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return issues
    for idx, line in enumerate(txt.splitlines(), start=1):
        if (".delete()" in line or "delete(" in line) and any(p in line for p in ("src/", "res/", "layout", "values")):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "UNAUTHORIZED_BUILD_SCRIPT_MUTATION",
                "msg": f"Unauthorized file deletion in Gradle build script at line {idx}: '{line.strip()}'. Do not use Gradle tasks to delete project assets or bypass verification.",
            })
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast Kotlin lint for this app")
    parser.add_argument("--all", action="store_true", help="Scan all Kotlin files under app/src/main")
    args = parser.parse_args()

    if args.all:
        try:
            from _modules import discover_source_roots

            roots = discover_source_roots(REPO)
        except Exception:
            roots = []
        if not roots:
            try:
                from _product import ANDROID_SRC

                roots = [REPO.joinpath(*ANDROID_SRC)]
            except Exception:
                roots = [REPO / "app" / "src" / "main"]
            if not roots[0].is_dir():
                roots = [REPO]
        from _modules import SKIP_PARTS
        skip = set(SKIP_PARTS)
        target_files = [
            p
            for root in roots
            for p in repo_glob(root, "**/*.kt")
            if not any(x in p.parts for x in skip)
        ]
        modified_lines_map = {p: None for p in target_files}
        java_files = [
            p for root in roots for p in repo_glob(root, "**/*.java") if not any(x in p.parts for x in skip)
        ]
        java_lines_map = {p: None for p in java_files}
        changed = changed_paths()
    else:
        changed = changed_paths()
        target_files = [p for p in changed if p.suffix == ".kt"]
        modified_lines_map = get_modified_lines_map(REPO, target_files)
        java_files = [p for p in changed if p.suffix == ".java"]
        java_lines_map = get_modified_lines_map(REPO, java_files) if java_files else {}

    build_files = [p for p in changed if p.name in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")]

    if not target_files and not build_files and not java_files:
        git_head_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if git_head_proc.returncode != 0:
            print(
                "[WARN] No git HEAD in this checkout (no commits?). "
                "Changed-file lint cannot verify the tree; run --all for a full scan.",
                file=sys.stderr,
            )
        print("[OK] No Kotlin or build files to lint in the working tree (including untracked).")
        return 0

    mode_label = "all files" if args.all else "modified lines in changed files"
    if target_files:
        print(f"[*] Fast Kotlin Lint: Scanning {len(target_files)} Kotlin file(s) ({mode_label})...")
    all_issues = []
    for path in target_files:
        all_issues.extend(lint_file(path, modified_lines=modified_lines_map.get(path)))
    for path in java_files:
        all_issues.extend(lint_java_file(path, modified_lines=java_lines_map.get(path)))
    for bf in build_files:
        all_issues.extend(lint_build_script(bf))

    if not all_issues:
        print("[SUCCESS] Fast Kotlin Lint passed! 0 syntax/architectural violations detected.")
        return 0

    print(f"\nFound {len(all_issues)} lint issue(s):")
    for i, iss in enumerate(all_issues, 1):
        rel_path = os.path.relpath(iss["file"], REPO)
        print(f"  {i}. [{iss['type']}] {rel_path}:{iss['line']}")
        print(f"     -> {iss['msg']}")

    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
