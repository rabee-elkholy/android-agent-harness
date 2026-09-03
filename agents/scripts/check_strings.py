"""Verify string resource parity and fail on hardcoded user-facing text.

Diff-scoped by default: only enforces translation parity on newly added/modified
string keys in git working tree, and scans modified lines for hardcoded text.
Legacy untouched keys are ignored so legacy repositories are never blocked.

Usage:
  python .agents/scripts/check_strings.py
  python .agents/scripts/check_strings.py --all
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _repo_files import REPO, changed_paths  # noqa: E402

enable_line_buffered_stdio()

try:
    from _product import ANDROID_SRC, SUPPORTED_LOCALES
except Exception:
    ANDROID_SRC = ("app", "src", "main")
    SUPPORTED_LOCALES = ["en", "ar"]

RES_DIRS: list[Path] = []
primary_res = REPO.joinpath(*ANDROID_SRC) / "res"
if primary_res.is_dir():
    RES_DIRS.append(primary_res)
for candidate in list(REPO.glob("**/src/*/res")) + list(REPO.glob("**/composeResources")):
    if candidate.is_dir() and candidate not in RES_DIRS and "/build/" not in candidate.as_posix():
        RES_DIRS.append(candidate)

if not RES_DIRS:
    RES_DIRS = [primary_res]

PLACEHOLDER_RE = re.compile(
    r"(?<!\d)%(?:(\d+)\$)?([+\-# 0,(<]*\d*(?:\.\d+)?[tT]?[sSdDfFgGxXbBcCeEoaAn%])(?![a-zA-Z0-9])|\{([a-zA-Z0-9_]+)\}"
)

# UI call sites that must not carry a raw user-facing literal.
HARDCODED_KT = [
    re.compile(r'\bText\s*\([^;\n]{0,200}(?:text\s*=\s*)?"[^"]{2,}"'),
    re.compile(r'\bText\s*\([^;\n]{0,200}"[^"]*"\s*\+'),
    re.compile(r'\bText\s*\(\s*"""'),
    re.compile(r'\b(?:text|label|placeholder|headline|supportingText|contentDescription)\s*=\s*"[^"]{2,}"'),
    re.compile(
        r'\b(?:Button|TextButton|OutlinedButton|ElevatedButton|FilledTonalButton)'
        r'\s*\([^;\n]{0,200}(?:text|content)\s*=\s*"[^"]{2,}"'
    ),
    re.compile(
        r'\b(?:setText|setHint|setTitle|setMessage|setSubtitle|setContentDescription|setError)'
        r'\s*\(\s*"[^"]{2,}"'
    ),
    re.compile(r'\bToast\.makeText\s*\([^;\n]*"[^"]{2,}"'),
    re.compile(r'\b(?:showSnackbar|Snackbar\.make)\s*\([^;\n]*"[^"]{2,}"'),
    re.compile(
        r'\b(?:setPositiveButton|setNegativeButton|setNeutralButton)\s*\(\s*"[^"]{2,}"'
    ),
]
HARDCODED_XML_TEXT = re.compile(
    r'(?:android|app):(?:text|hint|contentDescription|title|subtitle)="([^@?/"][^"]+)"',
    re.IGNORECASE,
)
HAS_LETTERS = re.compile(r"[A-Za-z\u0600-\u06FF]")
RESOURCE_CALL = re.compile(
    r"\b(?:stringResource|pluralStringResource|getString|getText|getQuantityString)\s*\([^)]*\)"
)
RESOURCE_OK = re.compile(
    r"\b(?:stringResource|pluralStringResource|getString|getText|getQuantityString|R\.string)\b"
)
SKIP_KT_LINE = re.compile(
    r"@Preview\b|\bLog\.|\bTimber\.|\bprintln\s*\(|\bBuildConfig\b|https?://|\bcontentType\b"
)


def _extract_placeholders(text: str) -> list[str]:
    if not text:
        return []
    placeholders = []
    for m in PLACEHOLDER_RE.finditer(text):
        placeholders.append(m.group(0))
    return sorted(placeholders)


NON_LOCALE_QUALIFIERS = {
    "night", "notnight", "land", "port", "square", "round", "long", "notlong",
    "ldr", "ldrtl", "ldltr", "hdpi", "mdpi", "xhdpi", "xxhdpi", "xxxhdpi", "nodpi",
    "tvdpi", "anydpi", "small", "normal", "large", "xlarge",
}
NON_LOCALE_PATTERNS = [
    re.compile(r"^v\d+$"),
    re.compile(r"^sw\d+dp$"),
    re.compile(r"^w\d+dp$"),
    re.compile(r"^h\d+dp$"),
    re.compile(r"^(?:mcc|mnc)\d+$"),
]


def _is_language_locale_tag(tag: str) -> bool:
    tag_lower = tag.lower().strip()
    if tag_lower in NON_LOCALE_QUALIFIERS:
        return False
    if any(pat.match(tag_lower) for pat in NON_LOCALE_PATTERNS):
        return False
    return bool(re.match(r"^(?:b\+[a-zA-Z0-9+]+|[a-z]{2,3}(?:-r?[a-zA-Z0-9]+)?)$", tag_lower))


def _parse_resources(xml_file: Path) -> tuple[dict[str, dict], list[str]]:
    """Parse XML strings/plurals/arrays, returning (resource_dict, duplicate_key_errors)."""
    if not xml_file.is_file():
        return {}, []
    res: dict[str, dict] = {}
    duplicates: list[str] = []
    seen_names: set[str] = set()

    try:
        root = ET.parse(xml_file).getroot()
    except Exception as exc:
        print(f"Warning: Failed to parse XML {xml_file.name}: {exc}")
        return {}, []

    for tag in ("string", "plurals", "string-array"):
        for elem in root.findall(tag):
            name = elem.get("name")
            if not name:
                continue
            if name in seen_names:
                try:
                    rel_p = xml_file.relative_to(REPO).as_posix()
                except ValueError:
                    rel_p = str(xml_file)
                duplicates.append(f"Duplicate <{tag} name=\"{name}\"> in {rel_p}")
            seen_names.add(name)

            if elem.get("translatable") == "false":
                continue
            if tag == "string":
                text = "".join(elem.itertext()).strip()
                placeholders = [] if elem.get("formatted") == "false" else _extract_placeholders(text)
                res[name] = {"tag": tag, "text": text, "placeholders": placeholders}
            elif tag == "plurals":
                items = [("".join(it.itertext()).strip()) for it in elem.findall("item")]
                placeholders = []
                for it in items:
                    placeholders.extend(_extract_placeholders(it))
            elif tag == "string-array":
                items = [("".join(it.itertext()).strip()) for it in elem.findall("item")]
                placeholders = []
                for it in items:
                    placeholders.extend(_extract_placeholders(it))
                res[name] = {"tag": tag, "items": items, "placeholders": sorted(set(placeholders))}
    return res, duplicates


def discover_locale_pairs() -> list[tuple[Path, Path, str]]:
    """Find all (base_values_strings, localized_values_strings, locale_tag) pairs."""
    pairs: list[tuple[Path, Path, str]] = []
    for res_dir in RES_DIRS:
        base_file = res_dir / "values" / "strings.xml"
        if not base_file.is_file():
            continue
        for val_dir in sorted(res_dir.glob("values-*")):
            if not val_dir.is_dir():
                continue
            loc_strings = val_dir / "strings.xml"
            if loc_strings.is_file():
                tag = val_dir.name[len("values-") :]
                if _is_language_locale_tag(tag):
                    pairs.append((base_file, loc_strings, tag))
    return pairs


def _is_test_path(path: Path) -> bool:
    posix = path.as_posix().lower()
    return "/src/test/" in posix or "/androidtest/" in posix


def _cut_line_comment(line: str) -> str:
    """Truncate a Kotlin line at a // comment that sits outside string literals."""
    in_string = False
    escaped = False
    i = 0
    while i < len(line):
        ch = line[i]
        if not in_string and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return line[:i]
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
    return line


def _get_modified_lines_map(files: list[Path], repo: Path, cached: bool = False) -> dict[Path, set[int] | None]:
    """Returns mapping from file path to set of 1-based modified line numbers (or None if untracked/new)."""
    res: dict[Path, set[int] | None] = {}
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
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


def _extract_keys_from_xml_lines(lines: list[str]) -> set[str]:
    keys = set()
    key_pattern = re.compile(r'<(?:string|plurals|string-array)\s+[^>]*name="([^"]+)"')
    for line in lines:
        for match in key_pattern.finditer(line):
            keys.add(match.group(1))
    return keys


def get_touched_string_keys(repo: Path) -> tuple[dict[Path, set[str]], bool]:
    """Returns (map of base_strings_path -> set of touched keys, any_string_file_changed)."""
    touched_by_base: dict[Path, set[str]] = {}
    any_changed = False

    for changed in changed_paths():
        if changed.name != "strings.xml":
            continue
        if "/values" not in changed.as_posix():
            continue

        # Find the matching base strings.xml (in values/strings.xml)
        res_dir = changed.parent.parent
        base_file = res_dir / "values" / "strings.xml"
        if not base_file.exists():
            continue

        any_changed = True
        if base_file not in touched_by_base:
            touched_by_base[base_file] = set()

        try:
            rel = changed.relative_to(repo).as_posix()
        except ValueError:
            rel = str(changed)

        proc = subprocess.run(
            ["git", "diff", "-U0", "HEAD", "--", rel],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            # Untracked / new file -> consider all keys touched
            data, _ = _parse_resources(changed)
            touched_by_base[base_file].update(data.keys())
        else:
            added_lines = [
                line[1:] for line in proc.stdout.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
            keys = _extract_keys_from_xml_lines(added_lines)
            touched_by_base[base_file].update(keys)

    return touched_by_base, any_changed


def check_hardcoded_strings(files: list[Path], lines_map: dict[Path, set[int] | None] | None = None) -> list[str]:
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

        modified_lines = lines_map.get(path) if lines_map else None
        in_triple_string = False

        for i, line in enumerate(content.splitlines(), 1):
            if modified_lines is not None and i not in modified_lines:
                continue

            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("<!--") or stripped.startswith("*"):
                continue
            if path.suffix == ".kt":
                if in_triple_string:
                    if line.count('"""') % 2 == 1:
                        in_triple_string = False
                    continue
                code_line = _cut_line_comment(line)
                if code_line.count('"""') % 2 == 1:
                    in_triple_string = True
                    continue
                if SKIP_KT_LINE.search(code_line):
                    continue
                clean_line = RESOURCE_CALL.sub('""', code_line)
                is_hardcoded = any(pat.search(clean_line) for pat in HARDCODED_KT)
                if not is_hardcoded and i > 1:
                    prev_stripped = _cut_line_comment(content.splitlines()[i - 2]).strip()
                    if re.search(r'\b(?:Text|Button|TextButton|OutlinedButton|ElevatedButton)\s*\(\s*$', prev_stripped):
                        if re.search(r'^\s*(?:text\s*=\s*)?"[^"]{2,}"', clean_line):
                            is_hardcoded = True
                if is_hardcoded:
                    findings.append(f"{rel}:{i} -> Hardcoded Kotlin UI text: {stripped[:120]}")
            elif path.suffix == ".xml":
                for match in HARDCODED_XML_TEXT.finditer(line):
                    value = match.group(1)
                    if not HAS_LETTERS.search(value):
                        continue
                    findings.append(f"{rel}:{i} -> Hardcoded XML {match.group(0)[:120]}")
    return findings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check Android string resource parity and hardcoded UI literals.")
    p.add_argument("--all", action="store_true", help="Check global string parity across entire repository.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print("==================================================")
    mode_str = "Full Repository Scan" if args.all else "Diff-Scoped (Modified Keys Only)"
    print(f"[Strings] Adaptive Localization & Placeholder Guard ({mode_str})")
    print("==================================================")

    pairs = discover_locale_pairs()
    errors = 0

    if not pairs:
        print("[OK] Single-locale checkout (no locale variants). Skipping translation parity.")
    else:
        touched_by_base, any_string_changed = get_touched_string_keys(REPO)

        for base_file, loc_file, tag in pairs:
            try:
                base_rel = base_file.relative_to(REPO).as_posix()
                loc_rel = loc_file.relative_to(REPO).as_posix()
            except ValueError:
                base_rel = str(base_file)
                loc_rel = str(loc_file)

            touched_keys = touched_by_base.get(base_file, set())

            # In diff-scoped mode, if no string files changed for this base file, skip parity check cleanly.
            if not args.all and not touched_keys:
                print(f"[OK] No string modifications in {base_rel}. Global translation parity skipped (diff-scoped).")
                continue

            base_data, base_dups = _parse_resources(base_file)
            loc_data, loc_dups = _parse_resources(loc_file)

            if base_dups:
                print(f"\n[!] Duplicate keys in {base_rel} ({len(base_dups)}):")
                for d in base_dups:
                    print(f"   - {d}")
                errors += len(base_dups)

            if loc_dups:
                print(f"\n[!] Duplicate keys in {loc_rel} ({len(loc_dups)}):")
                for d in loc_dups:
                    print(f"   - {d}")
                errors += len(loc_dups)

            base_keys = set(base_data.keys())
            loc_keys = set(loc_data.keys())

            if args.all:
                keys_to_check = base_keys | loc_keys
            else:
                keys_to_check = touched_keys

            missing_in_loc = [k for k in keys_to_check if k in base_keys and k not in loc_keys]
            missing_in_base = [k for k in keys_to_check if k in loc_keys and k not in base_keys]

            if missing_in_loc:
                print(f"\n[!] Missing in {loc_rel} ({len(missing_in_loc)} modified key(s) vs {base_rel}):")
                for key in sorted(missing_in_loc):
                    print(f"   - {key}")
                errors += len(missing_in_loc)
            else:
                scope_note = f"{len(keys_to_check)} modified key(s)" if not args.all else "all keys"
                print(f"[OK] Parity verified: {scope_note} in {base_rel} exist in {loc_rel}.")

            if missing_in_base:
                print(f"\n[!] Missing in {base_rel} ({len(missing_in_base)} modified key(s) from {loc_rel}):")
                for key in sorted(missing_in_base):
                    print(f"   - {key}")
                errors += len(missing_in_base)

            # Placeholder matching for relevant keys
            placeholder_mismatches = []
            common_keys = (base_keys & loc_keys) if args.all else (touched_keys & base_keys & loc_keys)
            for key in sorted(common_keys):
                base_ph = base_data[key].get("placeholders", [])
                loc_ph = loc_data[key].get("placeholders", [])
                if base_ph != loc_ph:
                    placeholder_mismatches.append(
                        f"   - key '{key}': base has {base_ph}, {loc_rel} has {loc_ph}"
                    )

            if placeholder_mismatches:
                print(f"\n[!] Placeholder format mismatches in {loc_rel} ({len(placeholder_mismatches)}):")
                for item in placeholder_mismatches:
                    print(item)
                errors += len(placeholder_mismatches)
            elif common_keys:
                print(f"[OK] Placeholders matched across {len(common_keys)} key(s) in {loc_rel}.")

    modified_src = [p for p in changed_paths() if p.suffix in {".kt", ".xml"}]
    hardcoded: list[str] = []
    if modified_src:
        print(f"\n[*] Checking {len(modified_src)} modified file(s) for hardcoded UI strings...")
        lines_map = None if args.all else _get_modified_lines_map(modified_src, REPO)
        hardcoded = check_hardcoded_strings(modified_src, lines_map=lines_map)
        if hardcoded:
            print(f"[!] Hardcoded strings found in modified lines ({len(hardcoded)}):")
            for item in hardcoded:
                print(f"   - {item}")
            errors += len(hardcoded)
        else:
            print("[OK] No hardcoded strings detected in modified lines.")

    print("\n==================================================")
    if errors == 0:
        print("[SUCCESS] String Parity & Placeholder Check Passed Successfully! (0 errors)")
        return 0
    print(f"[FAIL] Found {errors} string issue(s). Synchronize keys, match placeholders, and extract hardcoded text.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
