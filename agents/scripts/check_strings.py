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
from _repo_files import REPO, changed_paths, repo_glob  # noqa: E402

enable_line_buffered_stdio()

try:
    from _product import ANDROID_SRC, SUPPORTED_LOCALES
except Exception:
    ANDROID_SRC = ("app", "src", "main")
    SUPPORTED_LOCALES = ["en", "ar"]

from _modules import discover_res_dirs  # noqa: E402

primary_res = REPO.joinpath(*ANDROID_SRC) / "res"
RES_DIRS: list[Path] = discover_res_dirs(REPO, primary_res=primary_res)

PLACEHOLDER_RE = re.compile(
    r"(?<!\d)%(?:(\d+)\$)?([+\-# 0,(<]*\d*(?:\.\d+)?[tT]?[sSdDfFgGxXbBcCeEoaAn%])(?(1)|(?![a-zA-Z0-9]))|\{([a-zA-Z0-9_]+)\}"
)

# UI call sites that must not carry a raw user-facing literal.
_COMPOSE_ANIM_CALL_RE = re.compile(
    r"\b(?:"
    r"animate(?:Float|Dp|Color|Int|Offset|Size|Rect|IntOffset|IntSize|Value)AsState"
    r"|rememberInfiniteTransition|updateTransition|rememberTransition|createChildTransition"
    r"|AnimatedContent|Crossfade"
    r"|animate(?:Float|Dp|Color|Int|Offset|Size|Rect|IntOffset|IntSize|Value)"
    r")\s*(?:<[^>\n]*>\s*)?\("
)
_LABEL_LIT_RE = re.compile(r'\blabel\s*=\s*"')
_OTHER_KT_UI_ATTR_RE = re.compile(
    r'\b(?:text|placeholder|headline|supportingText|contentDescription)\s*=\s*"[^"]{2,}"'
)


def _is_compose_animation_label_line(lines: list[str], line_idx_0: int, clean_line: str) -> bool:
    """Return True when `label = "..."` belongs solely to a Compose animation API (tooling inspector tag)."""
    if not _LABEL_LIT_RE.search(clean_line) or _OTHER_KT_UI_ATTR_RE.search(clean_line):
        return False
    # If another UI call pattern also matched on this line (e.g. `Text(...)`), do not exempt it.
    if any(
        pat.search(clean_line)
        for idx, pat in enumerate(HARDCODED_KT)
        if idx != 3
    ):
        return False
    if _COMPOSE_ANIM_CALL_RE.search(clean_line):
        return True
    # Walk backward from just before `label =` to find the immediately enclosing call header `funcName(`.
    before_label = clean_line[:clean_line.find("label")]
    balance = 0
    for idx in range(line_idx_0, max(-1, line_idx_0 - 25), -1):
        seg = before_label if idx == line_idx_0 else _KT_STRING_LIT_RE.sub('""', _cut_line_comment(lines[idx]))
        # Strip string literals in current line prefix too.
        if idx == line_idx_0:
            seg = _KT_STRING_LIT_RE.sub('""', seg)
        for pos in range(len(seg) - 1, -1, -1):
            ch = seg[pos]
            if ch == ")":
                balance += 1
            elif ch == "(":
                balance -= 1
                if balance < 0:
                    prefix_text = seg[:pos + 1]
                    if idx > 0 and not re.search(r"[A-Za-z0-9_>]\s*\($", prefix_text):
                        # Multi-line signature like `animateFloatAsState\n(`: include previous line.
                        prefix_text = _cut_line_comment(lines[idx - 1]) + " " + prefix_text
                    return bool(_COMPOSE_ANIM_CALL_RE.search(prefix_text))
    return False
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
RTL_LOCALE_PREFIXES = ("ar", "fa", "he", "iw", "ur")
RTL_XML_DIRECTIONAL_ATTR = re.compile(
    r"\bandroid:(?:layout_margin(?:Left|Right)|padding(?:Left|Right)|drawable(?:Left|Right)|layout_alignParent(?:Left|Right)|layout_to(?:Left|Right)Of)\s*="
)
RTL_DIRECTIONAL_DRAWABLE_STEM = re.compile(
    r"(?:^|_)(?:arrow|back|chevron|forward|next|prev)(?:_|$)",
    re.IGNORECASE,
)
_KT_TEMPLATE_EXPR_RE = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*")
_KT_STRING_LIT_RE = re.compile(r'"((?:\\.|[^"\\])*)"')


def _kt_line_has_translatable_literal(clean_line: str) -> bool:
    """True when at least one string literal still contains alphabetic/Arabic prose after stripping `$var` / `${expr}` / `%d`."""
    if '"""' in clean_line:
        return True
    lits = [m.group(1) for m in _KT_STRING_LIT_RE.finditer(clean_line)]
    if not lits:
        return False
    for lit in lits:
        if len(lit) < 2:
            continue
        without_interp = _KT_TEMPLATE_EXPR_RE.sub("", lit)
        without_fmt = PLACEHOLDER_RE.sub("", without_interp)
        if HAS_LETTERS.search(without_fmt):
            return True
    return False
RESOURCE_CALL = re.compile(
    r"\b(?:stringResource|pluralStringResource|getString|getText|getQuantityString)\s*\([^)]*\)"
)
RESOURCE_OK = re.compile(
    r"\b(?:stringResource|pluralStringResource|getString|getText|getQuantityString|(?:R|Res)\.string)\b"
)
SKIP_KT_LINE = re.compile(
    r"@Preview\b|\bLog\.|\bTimber\.|\bprintln\s*\(|\bBuildConfig\b|https?://|\bcontentType\b"
)


ARABIC_REQUIRED_PLURAL_QUANTITIES = ("zero", "one", "two", "few", "many", "other")


def _extract_placeholders(text: str) -> list[str]:
    if not text:
        return []
    placeholders = []
    for m in PLACEHOLDER_RE.finditer(text):
        if m.group(2) in ("%", "n"):
            continue
        placeholders.append(m.group(0))
    return sorted(placeholders)


def _has_multiple_non_positional_specifiers(text: str) -> bool:
    """True when >=2 unnumbered printf specifiers (e.g. `%s ... %d` without `1$`/`2$`) would fail AAPT2 compilation."""
    if not text:
        return False
    unnumbered = 0
    for m in PLACEHOLDER_RE.finditer(text):
        pos_idx, conv, brace_tok = m.group(1), m.group(2), m.group(3)
        if brace_tok or not conv or conv in ("%", "n"):
            continue
        if not pos_idx:
            unnumbered += 1
            if unnumbered >= 2:
                return True
    return False


NON_LOCALE_QUALIFIERS = {
    "night", "notnight", "land", "port", "square", "round", "notround", "long", "notlong",
    "ldr", "ldrtl", "ldltr", "ldpi", "hdpi", "mdpi", "xhdpi", "xxhdpi", "xxxhdpi", "nodpi",
    "tvdpi", "anydpi", "small", "normal", "large", "xlarge",
    "car", "watch", "desk", "television", "appliance", "vrheadset",
    "widecg", "nowidecg", "highdr", "lowdr",
    "finger", "notouch", "stylus", "keysexposed", "keyshidden", "keyssoft",
    "nokeys", "qwerty", "12key", "navexposed", "navhidden", "nonav", "dpad", "trackball", "wheel",
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
    # Only primary locale directories participate in full parity. Android
    # qualifier overlays such as values-ar-v35 are partial by design.
    return bool(re.fullmatch(r"(?:b\+[a-z0-9]+(?:\+[a-z0-9]+)*|[a-z]{2,3}(?:-r[a-z]{2})?)", tag_lower))


class ResourceMap(dict):
    """Dict keyed by `(tag, name)` that also supports `name in res` and `res[name]` lookup for callers."""

    def __contains__(self, key: object) -> bool:
        if super().__contains__(key):
            return True
        if isinstance(key, str):
            return any(isinstance(k, tuple) and len(k) == 2 and k[1] == key for k in super().keys())
        return False

    def __getitem__(self, key: object) -> dict:
        if super().__contains__(key):
            return super().__getitem__(key)
        if isinstance(key, str):
            for k, val in super().items():
                if isinstance(k, tuple) and len(k) == 2 and k[1] == key:
                    return val
        raise KeyError(key)


def _format_res_key(key: tuple[str, str] | str) -> str:
    if isinstance(key, tuple) and len(key) == 2:
        tag, name = key
        return name if tag == "string" else f"{name} (<{tag}>)"
    return str(key)


def _parse_resources(xml_file: Path) -> tuple[ResourceMap, list[str]]:
    """Parse resources keyed by `(tag, name)`, returning (resource_map, duplicate/parse errors)."""
    if not xml_file.is_file():
        return ResourceMap(), []
    res = ResourceMap()
    duplicates: list[str] = []
    # Android keeps separate namespaces per resource type (R.string.x vs R.plurals.x).
    seen_names: set[tuple[str, str]] = set()

    try:
        root = ET.parse(xml_file).getroot()
    except Exception as exc:
        return ResourceMap(), [f"XML_PARSE_ERROR: {xml_file}: {exc}"]

    for tag in ("string", "plurals", "string-array"):
        for elem in root.findall(tag):
            name = elem.get("name")
            if not name:
                continue
            if (tag, name) in seen_names:
                try:
                    rel_p = xml_file.relative_to(REPO).as_posix()
                except ValueError:
                    rel_p = str(xml_file)
                duplicates.append(f"Duplicate <{tag} name=\"{name}\"> in {rel_p}")
            seen_names.add((tag, name))

            if elem.get("translatable") == "false":
                continue
            tools_ignore = elem.get("{http://schemas.android.com/tools}ignore") or elem.get("tools:ignore") or elem.get("ignore") or ""
            if "MissingTranslation" in tools_ignore or elem.get("l10n-todo") == "true":
                continue
            if tag == "string":
                text = "".join(elem.itertext()).strip()
                is_unformatted = elem.get("formatted") == "false"
                placeholders = [] if is_unformatted else _extract_placeholders(text)
                if not is_unformatted and "MultipleSubstitutions" not in tools_ignore and _has_multiple_non_positional_specifiers(text):
                    try:
                        rel_p = xml_file.relative_to(REPO).as_posix()
                    except ValueError:
                        rel_p = str(xml_file)
                    duplicates.append(
                        f"NON_POSITIONAL_FORMAT_SPECIFIERS: <string name=\"{name}\"> in {rel_p} uses multiple unnumbered "
                        "format specifiers (use positional `%1$s`, `%2$d` or set `formatted=\"false\"`)"
                    )
                res[(tag, name)] = {"tag": tag, "name": name, "text": text, "placeholders": placeholders}
            elif tag == "plurals":
                items = []
                quantities: dict[str, list[str]] = {}
                placeholders = []
                for it in elem.findall("item"):
                    it_txt = "".join(it.itertext()).strip()
                    items.append(it_txt)
                    it_phs = _extract_placeholders(it_txt)
                    placeholders.extend(it_phs)
                    q_attr = (it.get("quantity") or "").strip()
                    if q_attr:
                        quantities[q_attr] = it_phs
                    if "MultipleSubstitutions" not in tools_ignore and _has_multiple_non_positional_specifiers(it_txt):
                        try:
                            rel_p = xml_file.relative_to(REPO).as_posix()
                        except ValueError:
                            rel_p = str(xml_file)
                        duplicates.append(
                            f"NON_POSITIONAL_FORMAT_SPECIFIERS: <plurals name=\"{name}\"> item[{q_attr or '?'}] in {rel_p} "
                            "uses multiple unnumbered format specifiers (use positional `%1$d`, `%2$s`)"
                        )
                res[(tag, name)] = {
                    "tag": tag,
                    "name": name,
                    "items": items,
                    "quantities": quantities,
                    "placeholders": sorted(set(placeholders)),
                }
            elif tag == "string-array":
                items = [("".join(it.itertext()).strip()) for it in elem.findall("item")]
                item_placeholders = [_extract_placeholders(it) for it in items]
                all_placeholders = []
                for phs in item_placeholders:
                    all_placeholders.extend(phs)
                res[(tag, name)] = {
                    "tag": tag,
                    "name": name,
                    "items": items,
                    "placeholders": sorted(set(all_placeholders)),
                    "item_placeholders": item_placeholders,
                }
    return res, duplicates


def _resource_names(xml_text: str) -> set[str]:
    """Every string/plurals/string-array name in the XML, exempt or not."""
    return {name for _tag, name in _resource_keys(xml_text)}


def _resource_keys(xml_text: str) -> set[tuple[str, str]]:
    """Every `(tag, name)` pair in the XML, exempt or not."""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return set()
    return {
        (tag, str(elem.get("name")))
        for tag in ("string", "plurals", "string-array")
        for elem in root.findall(tag)
        if elem.get("name")
    }


def _head_resource_names(repo: Path, rel: str) -> set[tuple[str, str]] | None:
    """Resource `(tag, name)` keys in the committed version of a file; None when not in Git."""
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=str(repo), capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    return _resource_keys(proc.stdout) if proc.returncode == 0 else None


def discover_locale_pairs(res_dirs: list[Path] | None = None, repo: Path | None = None) -> list[tuple[Path, Path, str]]:
    """Find all (base_values_xml, localized_values_xml, locale_tag) pairs for strings, plurals, and arrays."""
    r = repo or REPO
    dirs = res_dirs if res_dirs is not None else RES_DIRS
    pairs: list[tuple[Path, Path, str]] = []
    deleted_locales_by_res: dict[Path, set[str]] = {}
    for p in changed_paths(include_deleted=True, repo=r):
        if p.suffix == ".xml" and "/values-" in p.as_posix():
            tag = p.parent.name[len("values-") :]
            if _is_language_locale_tag(tag):
                deleted_locales_by_res.setdefault(p.parent.parent, set()).add(tag)

    for res_dir in dirs:
        base_dir = res_dir / "values"

        if not base_dir.is_dir():
            continue
        base_files = [
            f for f in base_dir.glob("*.xml")
            if f.is_file() and (f.name.startswith(("strings", "plurals", "arrays")) or f.name in ("strings.xml", "plurals.xml", "arrays.xml"))
        ]
        if not base_files and (base_dir / "strings.xml").is_file():
            base_files = [base_dir / "strings.xml"]

        val_dirs: dict[str, Path] = {}
        for val_dir in sorted(res_dir.glob("values-*")):
            if not val_dir.is_dir():
                continue
            tag = val_dir.name[len("values-") :]
            if _is_language_locale_tag(tag):
                val_dirs[tag] = val_dir

        for tag in deleted_locales_by_res.get(res_dir, set()):
            val_dirs.setdefault(tag, res_dir / f"values-{tag}")

        for base_file in sorted(base_files):
            for tag, val_dir in sorted(val_dirs.items()):
                loc_file = val_dir / base_file.name
                pairs.append((base_file, loc_file, tag))
    return pairs




def _is_test_path(path: Path) -> bool:
    from _modules import is_kmp_or_android_test_path

    return is_kmp_or_android_test_path(path.as_posix())


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
    """Returns mapping from file path to set of 1-based modified line numbers (or None if untracked/new) via 1 batched git diff."""
    from fast_kt_lint import get_modified_lines_map
    return get_modified_lines_map(repo, files, cached=cached)


def _extract_keys_from_xml_lines(lines: list[str]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    text = "\n".join(lines)
    for m in re.finditer(r'<(string|plurals|string-array)\b[^>]*?\bname\s*=\s*["\']([^"\']+)["\']', text, re.DOTALL):
        keys.add((m.group(1), m.group(2)))
    return keys


def _extract_touched_keys_from_xml(content: str, modified_lines: set[int]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not content or not modified_lines:
        return keys

    elem_re = re.compile(
        r'<(string|plurals|string-array)\b([^>]*?)(?:/>|>(.*?)</\1>)',
        re.DOTALL
    )
    name_re = re.compile(r'\bname\s*=\s*["\']([^"\']+)["\']')

    line_starts = [0]
    for idx, ch in enumerate(content):
        if ch == '\n':
            line_starts.append(idx + 1)

    import bisect
    def char_to_line(char_idx: int) -> int:
        return bisect.bisect_right(line_starts, char_idx)

    for m in elem_re.finditer(content):
        tag_name = m.group(1)
        attrs = m.group(2)
        nm = name_re.search(attrs)
        if not nm:
            continue
        key_name = nm.group(1)
        start_line = char_to_line(m.start())
        end_line = char_to_line(m.end())
        if any(start_line <= l_num <= end_line for l_num in modified_lines):
            keys.add((tag_name, key_name))

    return keys


def get_touched_string_keys(repo: Path) -> tuple[dict[Path, set[str]], bool]:
    """Returns (map of base_strings_path -> set of touched keys, any_string_file_changed)."""
    from _repo_files import active_task_scope
    touched_by_base: dict[Path, set[str]] = {}
    any_changed = False

    scoped_paths, _baseline_dir = active_task_scope(repo, include_deleted=True)
    candidate_paths = scoped_paths if scoped_paths is not None else changed_paths(include_deleted=True, repo=repo)
    for changed in candidate_paths:


        if changed.suffix != ".xml":
            continue
        if "/values" not in changed.as_posix():
            continue
        if not (changed.name.startswith(("strings", "plurals", "arrays")) or changed.name in ("strings.xml", "plurals.xml", "arrays.xml")):
            continue

        res_dir = changed.parent.parent
        base_file = res_dir / "values" / changed.name
        if not base_file.exists() and not changed.exists():
            continue

        any_changed = True
        if base_file not in touched_by_base:
            touched_by_base[base_file] = set()

        try:
            rel = changed.relative_to(repo).as_posix()
        except ValueError:
            rel = str(changed)

        proc = subprocess.run(
            ["git", "diff", "-U0", "--ignore-cr-at-eol", "HEAD", "--", rel],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode == 0 and not proc.stdout.strip():
            tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel], cwd=repo, capture_output=True, check=False)
            if tracked.returncode == 0:
                continue
        if proc.returncode != 0 or not proc.stdout.strip():
            if changed.exists():
                # Untracked / new file -> consider all keys touched
                data, _ = _parse_resources(changed)
                touched_by_base[base_file].update(data.keys())
            else:
                proc_head = subprocess.run(
                    ["git", "show", f"HEAD:{rel}"],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if proc_head.returncode == 0:
                    keys = _extract_keys_from_xml_lines(proc_head.stdout.splitlines())
                    touched_by_base[base_file].update(keys)
        else:
            diff_lines = [
                line[1:] for line in proc.stdout.splitlines()
                if (line.startswith("+") or line.startswith("-"))
                and not (line.startswith("+++") or line.startswith("---"))
            ]
            keys = _extract_keys_from_xml_lines(diff_lines)

            # Map modified line numbers to enclosing parent tag (for plurals/arrays/multiline strings)
            hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
            new_lines: set[int] = set()
            old_lines: set[int] = set()
            for line in proc.stdout.splitlines():
                m = hunk_re.match(line)
                if m:
                    old_start = int(m.group(1))
                    old_count = int(m.group(2)) if m.group(2) is not None else 1
                    new_start = int(m.group(3))
                    new_count = int(m.group(4)) if m.group(4) is not None else 1
                    for l in range(new_start, new_start + new_count):
                        new_lines.add(l)
                    for l in range(old_start, old_start + old_count):
                        old_lines.add(l)

            if changed.exists() and new_lines:
                try:
                    content = changed.read_text(encoding="utf-8", errors="replace")
                    keys.update(_extract_touched_keys_from_xml(content, new_lines))
                except (OSError, ValueError):
                    pass
            if old_lines:
                proc_head = subprocess.run(
                    ["git", "show", f"HEAD:{rel}"],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if proc_head.returncode == 0:
                    keys.update(_extract_touched_keys_from_xml(proc_head.stdout, old_lines))

            touched_by_base[base_file].update(keys)

    return touched_by_base, any_changed


def check_hardcoded_strings(
    files: list[Path],
    lines_map: dict[Path, set[int] | None] | None = None,
    repo_root: Path | None = None,
) -> list[str]:
    base_repo = repo_root or REPO
    findings: list[str] = []
    for path in files:
        try:
            rel = path.relative_to(base_repo).as_posix()
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
        content_lines = content.splitlines()

        for i, line in enumerate(content_lines, 1):
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
                is_hardcoded = any(pat.search(clean_line) for pat in HARDCODED_KT) and _kt_line_has_translatable_literal(clean_line)
                if is_hardcoded and _is_compose_animation_label_line(content_lines, i - 1, clean_line):
                    is_hardcoded = False
                if not is_hardcoded and i > 1:
                    prev_stripped = _cut_line_comment(content_lines[i - 2]).strip()
                    if re.search(r'\b(?:Text|Button|TextButton|OutlinedButton|ElevatedButton)\s*\(\s*$', prev_stripped):
                        if re.search(r'^\s*(?:text\s*=\s*)?"[^"]{2,}"', clean_line) and _kt_line_has_translatable_literal(clean_line):
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


def _locale_dir_is_rtl(dir_name: str) -> bool:
    lower = dir_name.lower()
    if not lower.startswith("values-"):
        return False
    qual = lower[len("values-"):]
    if qual.startswith("b+"):
        lang = qual[2:].split("+", 1)[0].split("-", 1)[0]
    else:
        lang = qual.split("-", 1)[0]
    return lang in RTL_LOCALE_PREFIXES


def _repo_supports_rtl(
    repo_root: Path,
    res_dirs: list[Path],
    pairs: list[tuple],
) -> bool:
    for pair in pairs:
        if len(pair) >= 2 and isinstance(pair[1], Path) and _locale_dir_is_rtl(pair[1].parent.name):
            return True
    for rdir in res_dirs:
        if not rdir.is_dir():
            continue
        try:
            for child in rdir.iterdir():
                if child.is_dir() and _locale_dir_is_rtl(child.name):
                    return True
        except OSError:
            continue
    prod_file = repo_root / ".agents" / "scripts" / "_product.py"
    if prod_file.is_file():
        try:
            prod_txt = prod_file.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"SUPPORTED_LOCALES\s*=\s*\[([^\]]*)\]", prod_txt)
            if m:
                for tok in re.findall(r"""['"]([A-Za-z0-9_+-]+)['"]""", m.group(1)):
                    lang = tok.lower().replace("_", "-").split("-", 1)[0]
                    if lang in RTL_LOCALE_PREFIXES:
                        return True
        except OSError:
            pass
    return False


def check_rtl_xml_issues(
    files: list[Path],
    lines_map: dict[Path, set[int] | None] | None = None,
    repo_root: Path | None = None,
) -> list[str]:
    """Diff-scoped `<1ms` RTL XML layout & directional vector drawable check."""
    base_repo = repo_root or REPO
    findings: list[str] = []
    for path in files:
        if path.suffix.lower() != ".xml" or _is_test_path(path):
            continue
        try:
            rel = path.relative_to(base_repo).as_posix()
        except ValueError:
            rel = path.as_posix()
        parent_name = path.parent.name.lower()
        is_layout = parent_name == "layout" or (
            parent_name.startswith("layout-")
            and "ldltr" not in parent_name
            and "ldrtl" not in parent_name
        )
        is_drawable = parent_name == "drawable" or (
            parent_name.startswith("drawable-")
            and "ldltr" not in parent_name
            and "ldrtl" not in parent_name
            and not any(f"-{rtl}" in parent_name for rtl in RTL_LOCALE_PREFIXES)
        )
        if not is_layout and not is_drawable:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r'tools:ignore\s*=\s*"[^"]*(?:RtlHardcoded|RtlSymmetry|AutoMirrored)', content):
            continue
        modified_lines = lines_map.get(path) if lines_map else None
        lines = content.splitlines()
        if is_layout:
            for i, line in enumerate(lines, 1):
                if modified_lines is not None and i not in modified_lines:
                    continue
                stripped = line.strip()
                if stripped.startswith("<!--"):
                    continue
                m_attr = RTL_XML_DIRECTIONAL_ATTR.search(line)
                if m_attr:
                    attr_tok = m_attr.group(0).rstrip("=").strip()
                    findings.append(
                        f"{rel}:{i} -> Hardcoded LTR/RTL XML attribute `{attr_tok}` (use Start/End equivalent for RTL mirroring)"
                    )
        elif is_drawable and RTL_DIRECTIONAL_DRAWABLE_STEM.search(path.stem):
            if "<vector" in content and not re.search(r'\bandroid:autoMirrored\s*=\s*"true"', content):
                vec_lines = {idx for idx, ln in enumerate(lines, 1) if "<vector" in ln or "xmlns:android" in ln}
                if modified_lines is None or (modified_lines and (vec_lines & modified_lines or len(modified_lines) >= len(lines) - 1)):
                    vec_line_no = min(vec_lines) if vec_lines else 1
                    findings.append(
                        f'{rel}:{vec_line_no} -> Directional vector drawable `{path.name}` is missing `android:autoMirrored="true"` for RTL locales'
                    )
    return findings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check Android string resource parity and hardcoded UI literals.")
    p.add_argument("--all", action="store_true", help="Check global string parity across entire repository.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, repo: Path | None = None) -> int:
    r = repo or REPO
    args = parse_args(argv)
    print("==================================================")
    mode_str = "Full Repository Scan" if args.all else "Diff-Scoped (Modified Keys Only)"
    print(f"[Strings] Adaptive Localization & Placeholder Guard ({mode_str})")
    print("==================================================")

    res_dirs = RES_DIRS
    if repo:
        prim = r.joinpath(*ANDROID_SRC) / "res"
        res_dirs = discover_res_dirs(r, primary_res=prim)

    pairs = discover_locale_pairs(res_dirs=res_dirs, repo=r)
    errors = 0
    from _repo_files import active_task_scope, diff_modified_lines_against_baseline
    scoped_paths, baseline_dir = (None, None) if args.all else active_task_scope(r)
    modified = scoped_paths if scoped_paths is not None else changed_paths(repo=r)
    parsed: dict[Path, tuple[dict, list[str]]] = {}
    reported: set[Path] = set()

    def resources(path: Path) -> tuple[dict, list[str]]:
        if path not in parsed:
            parsed[path] = _parse_resources(path)
        return parsed[path]

    def report_resource_errors(path: Path) -> int:
        if path in reported:
            return 0
        reported.add(path)
        _values, failures = resources(path)
        if failures:
            print(f"\n[!] Resource errors in {path} ({len(failures)}):")
            for failure in failures:
                print(f"   - {failure}")
        return len(failures)

    # Syntax/duplicate failures must not disappear because no translation pair
    # exists or a malformed XML edit yielded no parseable changed resource key.
    resource_files = {path for path in modified if path.suffix == ".xml" and path.parent.name.startswith("values")}
    if args.all:
        resource_files.update(path for root in res_dirs for path in root.glob("values*/*.xml") if path.is_file())
    for path in sorted(resource_files):
        errors += report_resource_errors(path)

    if not pairs:
        print("[OK] Single-locale checkout (no locale variants). Skipping translation parity.")
    else:
        touched_by_base, any_string_changed = get_touched_string_keys(r)

        for base_file, loc_file, tag in pairs:
            try:
                base_rel = base_file.relative_to(r).as_posix()
                loc_rel = loc_file.relative_to(r).as_posix()
            except ValueError:
                base_rel = str(base_file)
                loc_rel = str(loc_file)


            touched_keys = touched_by_base.get(base_file, set())

            # In diff-scoped mode, if no string files changed for this base file, skip parity check cleanly.
            if not args.all and not touched_keys:
                print(f"[OK] No string modifications in {base_rel}. Global translation parity skipped (diff-scoped).")
                continue

            base_data, _base_errors = resources(base_file)
            loc_data, _locale_errors = resources(loc_file)
            errors += report_resource_errors(base_file)
            errors += report_resource_errors(loc_file)

            base_keys = set(base_data.keys())
            loc_keys = set(loc_data.keys())

            if args.all:
                keys_to_check = base_keys | loc_keys
            else:
                keys_to_check = touched_keys

            # A base key exempt from translation (translatable="false", MissingTranslation, l10n-todo)
            # is not "missing in base" because a locale still translates it (N5).
            base_exempt = _resource_keys(base_file.read_text(encoding="utf-8", errors="replace")) - base_keys if base_file.is_file() else set()
            missing_in_loc = [k for k in keys_to_check if k in base_keys and k not in loc_keys]
            missing_in_base = [k for k in keys_to_check if k in loc_keys and k not in base_keys and k not in base_exempt]
            if not args.all and missing_in_loc:
                # Editing a key never creates a gap in a locale that already lacked it at HEAD;
                # that is pre-existing debt, not this change's (N6). New keys stay strict.
                head_base = _head_resource_names(r, base_rel)
                head_loc = _head_resource_names(r, loc_rel)
                if head_base is not None and head_loc is not None:
                    missing_in_loc = [k for k in missing_in_loc if not (k in head_base and k not in head_loc)]

            if missing_in_loc:
                not_found_note = " (file does not exist)" if not loc_file.is_file() else ""
                print(f"\n[!] Missing in {loc_rel}{not_found_note} ({len(missing_in_loc)} modified key(s) vs {base_rel}):")

                for key in sorted(missing_in_loc):
                    print(f"   - {_format_res_key(key)}")
                print(
                    "   Add the translation. A string that must not be translated takes translatable=\"false\" or "
                    "tools:ignore=\"MissingTranslation\"; one an external translation service will fill takes l10n-todo=\"true\"."
                )
                errors += len(missing_in_loc)
            else:
                scope_note = f"{len(keys_to_check)} modified key(s)" if not args.all else "all keys"
                print(f"[OK] Parity verified: {scope_note} in {base_rel} exist in {loc_rel}.")

            if missing_in_base:
                print(f"\n[!] Missing in {base_rel} ({len(missing_in_base)} modified key(s) from {loc_rel}):")
                for key in sorted(missing_in_base):
                    print(f"   - {_format_res_key(key)}")
                errors += len(missing_in_base)

            # Placeholder matching for relevant keys
            placeholder_mismatches = []
            common_keys = (base_keys & loc_keys) if args.all else (touched_keys & base_keys & loc_keys)
            for key_tup in sorted(common_keys):
                base_info = base_data[key_tup]
                loc_info = loc_data[key_tup]
                key = _format_res_key(key_tup)
                tag = base_info.get("tag")
                if tag == "string-array":
                    base_item_phs = base_info.get("item_placeholders", [])
                    loc_item_phs = loc_info.get("item_placeholders", [])
                    if len(base_item_phs) != len(loc_item_phs):
                        placeholder_mismatches.append(
                            f"   - key '{key}': item count mismatch ({len(base_item_phs)} in base vs {len(loc_item_phs)} in {loc_rel})"
                        )
                    else:
                        for idx, (b_phs, l_phs) in enumerate(zip(base_item_phs, loc_item_phs)):
                            if b_phs != l_phs:
                                placeholder_mismatches.append(
                                    f"   - key '{key}' item[{idx}]: base has {b_phs}, {loc_rel} has {l_phs}"
                                )
                elif tag == "plurals":
                    base_ph = base_info.get("placeholders", [])
                    base_quants: dict[str, list[str]] = base_info.get("quantities") or {}
                    loc_quants: dict[str, list[str]] = loc_info.get("quantities") or {}
                    loc_lang = loc_file.parent.name[len("values-"):].lower()
                    if loc_lang.startswith("b+"):
                        loc_lang = loc_lang[2:].split("+", 1)[0].split("-", 1)[0]
                    else:
                        loc_lang = loc_lang.split("-", 1)[0]
                    if "other" not in loc_quants:
                        placeholder_mismatches.append(
                            f"   - key '{key}': <plurals> in {loc_rel} is missing mandatory quantity=\"other\" item"
                        )
                    elif loc_lang == "ar":
                        missing_q = [q for q in ARABIC_REQUIRED_PLURAL_QUANTITIES if q not in loc_quants]
                        if missing_q:
                            placeholder_mismatches.append(
                                f"   - key '{key}': Arabic <plurals> in {loc_rel} is missing required CLDR quantity item(s): {', '.join(missing_q)}"
                            )
                    # Idiomatic Arabic `zero`/`one`/`two` (and base quantities that omit placeholders) may omit `%d`
                    # while `other`/`few`/`many` must preserve all placeholders declared in the base plural.
                    base_ph_set = set(base_ph)
                    for q_name, q_phs in sorted(loc_quants.items()):
                        q_unique = sorted(set(q_phs))
                        if loc_lang == "ar" and q_name in {"zero", "one", "two"}:
                            unexpected_phs = [p for p in q_unique if p not in base_ph_set]
                            if unexpected_phs:
                                placeholder_mismatches.append(
                                    f"   - key '{key}' quantity=\"{q_name}\": unexpected placeholder(s) {unexpected_phs} vs base {base_ph} in {loc_rel}"
                                )
                        else:
                            expected_q_phs = sorted(set(base_quants[q_name])) if q_name in base_quants else base_ph
                            if q_unique != expected_q_phs and q_unique != base_ph:
                                placeholder_mismatches.append(
                                    f"   - key '{key}' quantity=\"{q_name}\": base has {expected_q_phs}, {loc_rel} has {q_unique}"
                                )
                else:
                    base_ph = base_info.get("placeholders", [])
                    loc_ph = loc_info.get("placeholders", [])
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

    modified_src = [p for p in modified if p.suffix in {".kt", ".xml"}]
    hardcoded: list[str] = []
    if modified_src:
        print(f"\n[*] Checking {len(modified_src)} modified file(s) for hardcoded UI strings...")
        lines_map = None if args.all else _get_modified_lines_map(modified_src, r)
        if lines_map is not None and baseline_dir is not None:
            for p in modified_src:
                try:
                    rel = p.resolve().relative_to(r.resolve()).as_posix()
                except ValueError:
                    continue
                b_file = baseline_dir / rel
                if b_file.is_file() and p.is_file():
                    lines_map[p] = diff_modified_lines_against_baseline(b_file, p)
        hardcoded = check_hardcoded_strings(modified_src, lines_map=lines_map, repo_root=r)
        if hardcoded:
            print(f"[!] Hardcoded strings found in modified lines ({len(hardcoded)}):")
            for item in hardcoded:
                print(f"   - {item}")
            errors += len(hardcoded)
        else:
            print("[OK] No hardcoded strings detected in modified lines.")

        if _repo_supports_rtl(r, res_dirs, pairs):
            rtl_issues = check_rtl_xml_issues(modified_src, lines_map=lines_map, repo_root=r)
            if rtl_issues:
                print(f"[!] RTL XML layout/drawable issues in modified lines ({len(rtl_issues)}):")
                for item in rtl_issues:
                    print(f"   - {item}")
                errors += len(rtl_issues)
            else:
                print("[OK] No RTL XML layout/drawable issues detected in modified lines.")

    print("\n==================================================")
    if errors == 0:
        print("[SUCCESS] String Parity & Placeholder Check Passed Successfully! (0 errors)")
        return 0
    print(f"[FAIL] Found {errors} string issue(s). Synchronize keys, match placeholders, and extract hardcoded text.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
