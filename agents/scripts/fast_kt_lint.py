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
from _repo_files import REPO, changed_paths  # noqa: E402

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
    r"@Preview\b[\s\S]{0,500}?(?:locale\s*=\s*\"ar\"|LayoutDirection\.Rtl|ArabicPreview|\bArPreview\b|//\s*locale\s*=\s*\"ar\")"
)
PREVIEW_EN = re.compile(
    r"@Preview\b[\s\S]{0,500}?(?:locale\s*=\s*\"en\"|LayoutDirection\.Ltr|EnglishPreview|\bEnPreview\b|//\s*locale\s*=\s*\"en\")"
)
PREVIEW_SURFACE_SUFFIXES = (
    "Screen.kt",
    "Card.kt",
    "Dialog.kt",
    "BottomSheet.kt",
    "Sheet.kt",
    "Banner.kt",
)

FEATURE_CROSS_IMPORT_PATTERN = re.compile(
    r"^\s*import\s+([a-zA-Z0-9_.]*\.(?:features|feature)\.([A-Za-z0-9_]+))(\.|$)"
)


def _current_feature_segment(path: Path) -> str | None:
    parts = [p.lower() for p in path.parts]
    for i, part in enumerate(parts):
        if part in ("features", "feature") and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _in_string_or_comment(line: str, index: int) -> bool:
    """True when index sits inside a // comment or a double-quoted string."""
    in_string = False
    escaped = False
    i = 0
    while i < index and i < len(line):
        ch = line[i]
        if not in_string and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return True
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
    return in_string


def is_preview_surface(filename: str) -> bool:
    return filename.endswith(PREVIEW_SURFACE_SUFFIXES)


def requires_state_previews(filename: str) -> bool:
    return filename.endswith("Screen.kt")


def get_modified_lines_map(repo: Path, files: list[Path], cached: bool = False) -> dict[Path, set[int] | None]:
    """Return map of file -> set of 1-indexed added/modified line numbers from git diff HEAD.
    
    If a file is untracked or git diff fails (e.g. no git HEAD), returns None for that file
    (indicating that all lines in that file should be linted).
    """
    res: dict[Path, set[int] | None] = {}
    hunk_re = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")

    for f in files:
        try:
            rel = f.relative_to(repo).as_posix()
        except ValueError:
            rel = str(f)

        cmd = ["git", "diff", "-U0"]
        if cached:
            cmd.append("--cached")
        cmd.extend(["HEAD", "--", rel])

        proc = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            if cached:
                # Fallback for fresh repos before initial commit
                proc = subprocess.run(
                    ["git", "diff", "-U0", "--cached", "--", rel],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            if proc.returncode != 0 or not proc.stdout.strip():
                # Untracked file, brand new file, or git diff returned nothing
                res[f] = None
                continue

        modified_lines: set[int] = set()
        for line in proc.stdout.splitlines():
            m = hunk_re.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                for l_num in range(start, start + count):
                    modified_lines.add(l_num)
        res[f] = modified_lines
    return res


def lint_file(file_path: Path, modified_lines: set[int] | None = None) -> list[dict]:
    issues = []
    posix = file_path.as_posix().lower()
    is_test = "/src/test/" in posix or "/androidtest/" in posix

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
    except Exception as e:
        return [{"file": str(file_path), "line": 1, "type": "IO_ERROR", "msg": str(e)}]

    has_fragment_activity_in_diff = False
    has_android_entry_point = False
    has_compose_function_in_diff = False
    has_compose_imports = any("androidx.compose" in l for l in lines[:60])
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

        if not is_test and RUNBLOCKING_PATTERN.search(trimmed):
            m_rb = RUNBLOCKING_PATTERN.search(trimmed)
            if not _in_string_or_comment(line, m_rb.start()):
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "RUNBLOCKING_ANR",
                    "msg": "runBlocking found in production code. Use viewModelScope.launch or coroutineScope to avoid ANRs.",
                })

        if is_test and RUNBLOCKING_PATTERN.search(trimmed):
            m_trb = RUNBLOCKING_PATTERN.search(trimmed)
            if not _in_string_or_comment(line, m_trb.start()):
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "TEST_RUNBLOCKING",
                    "msg": "runBlocking found in test file. Use runTest { ... } with StandardTestDispatcher / advanceUntilIdle() for robust coroutine testing.",
                })

        if not is_test and UNIMPLEMENTED_STUB_PATTERN.search(trimmed):
            m_stub = UNIMPLEMENTED_STUB_PATTERN.search(trimmed)
            if not _in_string_or_comment(line, m_stub.start()):
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "UNIMPLEMENTED_STUB",
                    "msg": f"Unimplemented stub found in production code: '{trimmed}'. Provide complete implementation.",
                })

        if not is_test and DOUBLE_BANG_PATTERN.search(trimmed):
            m_db = DOUBLE_BANG_PATTERN.search(trimmed)
            if not _in_string_or_comment(line, m_db.start()):
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

        current_feature = _current_feature_segment(file_path)
        if current_feature:
            m = FEATURE_CROSS_IMPORT_PATTERN.match(trimmed)
            if m and m.group(2).lower() != current_feature:
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "FEATURE_CROSS_IMPORT",
                    "msg": (
                        f"Feature module '{current_feature}' imports another feature "
                        f"('{m.group(2)}'). Route shared logic through a :core/:common "
                        "module instead of feature-to-feature imports."
                    ),
                })

        if STATE_CLASS_PATTERN.search(trimmed) and (has_compose_imports or has_compose_function_in_diff):
            lookback_idx = idx - 2
            annotations = []
            while lookback_idx >= 0 and lines[lookback_idx].strip().startswith("@"):
                annotations.append(lines[lookback_idx].strip())
                lookback_idx -= 1
            ann_block = " ".join(annotations)
            if "@Immutable" not in ann_block and "@Stable" not in ann_block:
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

    if has_compose_function_in_diff and is_preview_surface(file_path.name):
        is_dual_locale = "ar" in SUPPORTED_LOCALES and "en" in SUPPORTED_LOCALES
        extra = " plus Loading/Empty/Error." if requires_state_previews(file_path.name) else "."
        if is_dual_locale:
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
        skip = {".git", "build", ".gradle", ".agents", ".harness-backup", ".harness-setup", "__pycache__"}
        target_files = [
            p
            for root in roots
            for p in root.rglob("*.kt")
            if not any(x in p.parts for x in skip)
        ]
        modified_lines_map = {p: None for p in target_files}
    else:
        target_files = [p for p in changed_paths() if p.suffix == ".kt"]
        modified_lines_map = get_modified_lines_map(REPO, target_files)

    if not target_files:
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
        print("[OK] No Kotlin files to lint in the working tree (including untracked).")
        return 0

    mode_label = "all files" if args.all else "modified lines in changed files"
    print(f"[*] Fast Kotlin Lint: Scanning {len(target_files)} Kotlin file(s) ({mode_label})...")
    all_issues = []
    for path in target_files:
        all_issues.extend(lint_file(path, modified_lines=modified_lines_map.get(path)))

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
