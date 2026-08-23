"""Verify string resource parity and fail on hardcoded user-facing text.

Usage: python .agents/scripts/check_strings.py
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _repo_files import REPO, changed_paths  # noqa: E402

enable_line_buffered_stdio()

try:
    from _product import ANDROID_SRC
    RES_DIR = REPO.joinpath(*ANDROID_SRC) / "res"
except Exception:
    RES_DIR = REPO / "app" / "src" / "main" / "res"

if not RES_DIR.is_dir():
    _candidates = list(REPO.glob("**/src/*/res")) or list(REPO.glob("**/res"))
    if _candidates:
        RES_DIR = _candidates[0]

STR_EN = RES_DIR / "values" / "strings.xml"
STR_AR = RES_DIR / "values-ar" / "strings.xml"

# UI call sites that must not carry a raw user-facing literal.
HARDCODED_KT = [
    re.compile(r'\bText\s*\(\s*(?:text\s*=\s*)?"[^"]{2,}"'),
    re.compile(r'\bText\s*\(\s*(?:text\s*=\s*)?"[^"]*"\s*\+'),
    re.compile(r'\bText\s*\(\s*"""'),
    re.compile(
        r'\b(?:Button|TextButton|OutlinedButton|ElevatedButton|FilledTonalButton)'
        r'\s*\([^;\n]{0,200}(?:text|content)\s*=\s*"[^"]{2,}"'
    ),
    re.compile(r'\b(?:label|placeholder|headline|supportingText)\s*=\s*"[^"]{2,}"'),
    re.compile(
        r'\b(?:setText|setHint|setTitle|setMessage|setSubtitle|setContentDescription|setError)'
        r'\s*\(\s*"[^"]{2,}"'
    ),
    re.compile(r'\bToast\.makeText\s*\([^;\n]*"[^"]{2,}"'),
    re.compile(r'\b(?:showSnackbar|Snackbar\.make)\s*\([^;\n]*"[^"]{2,}"'),
    re.compile(
        r'\b(?:setPositiveButton|setNegativeButton|setNeutralButton)\s*\(\s*"[^"]{2,}"'
    ),
    re.compile(r'\bcontentDescription\s*=\s*"[^"]{2,}"'),
]
HARDCODED_XML_TEXT = re.compile(
    r'(?:android|app):(?:text|hint|contentDescription|title|subtitle)="([^@?/"][^"]+)"',
    re.IGNORECASE,
)
HAS_LETTERS = re.compile(r"[A-Za-z\u0600-\u06FF]")
RESOURCE_OK = re.compile(
    r"\b(?:stringResource|pluralStringResource|getString|getText|getQuantityString|R\.string)\b"
)
SKIP_KT_LINE = re.compile(
    r"@Preview\b|\bLog\.|\bTimber\.|\bprintln\s*\(|\bBuildConfig\b|https?://|\bcontentType\b"
)


def _resource_names(xml_file: Path) -> set[str]:
    if not xml_file.is_file():
        return set()
    names: set[str] = set()
    try:
        root = ET.parse(xml_file).getroot()
    except Exception as exc:
        print(f"Warning: Failed to parse XML {xml_file.name}: {exc}")
        return set()
    for tag in ("string", "plurals", "string-array"):
        for elem in root.findall(tag):
            name = elem.get("name")
            if name:
                names.add(name)
    return names


def check_key_parity() -> tuple[set[str], set[str]]:
    en_keys = _resource_names(STR_EN)
    ar_keys = _resource_names(STR_AR)
    return en_keys - ar_keys, ar_keys - en_keys


def _is_test_path(path: Path) -> bool:
    posix = path.as_posix().lower()
    return "/src/test/" in posix or "/androidtest/" in posix


def check_hardcoded_strings(files: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in files:
        try:
            rel = path.relative_to(REPO).as_posix()
        except ValueError:
            rel = str(path)
        if path.suffix == ".xml" and "/values" in f"/{rel}":
            continue
        if _is_test_path(path):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("<!--") or stripped.startswith("*"):
                continue
            if path.suffix == ".kt":
                if RESOURCE_OK.search(line) or SKIP_KT_LINE.search(line):
                    continue
                if any(pat.search(line) for pat in HARDCODED_KT):
                    findings.append(f"{rel}:{i} -> Hardcoded Kotlin UI text: {stripped[:120]}")
            elif path.suffix == ".xml":
                for match in HARDCODED_XML_TEXT.finditer(line):
                    value = match.group(1)
                    if not HAS_LETTERS.search(value):
                        continue
                    findings.append(f"{rel}:{i} -> Hardcoded XML {match.group(0)[:120]}")
    return findings


def main() -> int:
    print("==================================================")
    print("[Strings] this app Localization & Strings Parity Checker")
    print("==================================================")

    if not STR_AR.is_file():
        print("[OK] Single-locale checkout (no values-ar). Skipping AR/EN key parity.")
        missing_in_ar, missing_in_en = set(), set()
    else:
        missing_in_ar, missing_in_en = check_key_parity()
    errors = 0

    if missing_in_ar:
        print(f"\n[!] Missing in values-ar/strings.xml ({len(missing_in_ar)} keys):")
        for key in sorted(missing_in_ar):
            print(f"   - {key}")
        errors += len(missing_in_ar)
    else:
        print("[OK] All English keys exist in Arabic.")

    if missing_in_en:
        print(f"\n[!] Missing in values/strings.xml ({len(missing_in_en)} keys):")
        for key in sorted(missing_in_en):
            print(f"   - {key}")
        errors += len(missing_in_en)
    else:
        print("[OK] All Arabic keys exist in English.")

    modified = [p for p in changed_paths() if p.suffix in {".kt", ".xml"}]
    hardcoded: list[str] = []
    if modified:
        print(f"\n[*] Checking {len(modified)} modified files for hardcoded strings...")
        hardcoded = check_hardcoded_strings(modified)
        if hardcoded:
            print(f"[!] Hardcoded strings found ({len(hardcoded)}):")
            for item in hardcoded:
                print(f"   - {item}")
            errors += len(hardcoded)
        else:
            print("[OK] No hardcoded strings detected in modified files.")

    print("\n==================================================")
    if errors == 0:
        print("[SUCCESS] String Parity Check Passed Successfully!")
        return 0
    print(f"[FAIL] Found {errors} string issue(s). Synchronize keys and extract hardcoded text.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
