"""Fast Gradle / kotlinc / KSP / Dagger-Hilt / AAPT2 / Manifest Error Parser for Android & KMP apps.
Extracts clean, actionable file:line diagnostics from Gradle stdout/stderr.

Usage:
  python .agents/scripts/gradle_error_parser.py --log <path_to_log_or_stdin>
"""
from __future__ import annotations

import bisect
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (OSError, ValueError):
        pass

_FILE_URI_PREFIX = r"(?:file:///(?=[a-zA-Z]:)|file://)?"

# 1. KSP / Room processor diagnostics (evaluated before generic kotlinc so SQL continuation lines fold cleanly)
KSP_ERROR_RE = re.compile(
    r"^(?:e:\s*)?\[ksp\]\s*" + _FILE_URI_PREFIX + r"(.+?\.(?:kt|java)):\s*(\d+)(?::(\d+))?(?:\s*:\s*|\s+)(.+)$",
    re.MULTILINE,
)

# 2. Kotlin compiler (`kotlinc` / Compose compiler) diagnostics (Kotlin 1.x `:line:col: msg`, `(line, col): msg`, and K2 `file:///...:line:col msg`)
KOTLIN_ERROR_RE = re.compile(
    r"^e:\s+(?!\[ksp\])(?:\[[a-zA-Z0-9_-]+\]\s+)?" + _FILE_URI_PREFIX
    + r"(.+?\.(?:kt|kts)):\s*(?:\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*:\s*|(\d+)(?::(\d+))?(?:\s*:\s*|\s+))(.+)$",
    re.MULTILINE,
)

# 3. Java compiler (`javac`) diagnostics (excluding Dagger/Hilt multi-line header handled separately)
JAVAC_ERROR_RE = re.compile(
    r"^(?:\[ERROR\]\s*)?([a-zA-Z]:[\\/][^\r\n:]+|\/[^\r\n:]+?\.java|[^\r\n:*]+?\.java):(\d+):\s*error:\s*(?!\[Dagger/)(.+)$",
    re.MULTILINE,
)

# 4. Dagger / Hilt binding, scope, and cycle diagnostics
DAGGER_HILT_RE = re.compile(
    r"^(?:(?:\[ERROR\]\s*)?(?:(?P<file>[a-zA-Z]:[\\/][^\r\n:]+|\/[^\r\n:]+?\.(?:java|kt)|[^\r\n:*]+?\.(?:java|kt)):(?P<line>\d+):\s*)?error:\s*)?"
    r"\[(?P<tag>Dagger/[A-Za-z0-9_]+|Hilt)\]\s*(?P<msg>.+)$",
    re.MULTILINE,
)

# 5. AAPT2 XML resource linking & compilation errors
AAPT2_PREFIXED_RE = re.compile(
    r"^(?:ERROR:\s*|e:\s*)?" + _FILE_URI_PREFIX + r"([a-zA-Z]:[\\/][^\r\n:]+?\.xml|[^\r\n:*]+?\.xml):(\d+)(?::(\d+))?:\s*AAPT:\s*error:\s*(.+)$",
    re.MULTILINE,
)
AAPT2_PLAIN_XML_RE = re.compile(
    r"^[ \t]*(?:ERROR:\s*)?([a-zA-Z]:[\\/][^\r\n:]+?\.xml|[^\r\n:*]+?\/res\/[^\r\n:]+?\.xml):(\d+)(?::(\d+))?:\s*error:\s*(.+)$",
    re.MULTILINE,
)

# 6. AndroidManifest Merger conflicts
MANIFEST_FILE_ERROR_RE = re.compile(
    r"^" + _FILE_URI_PREFIX + r"([a-zA-Z]:[\\/][^\r\n:]*AndroidManifest\.xml|[^\r\n:*]*AndroidManifest\.xml):(\d+)(?::(\d+)(?:-\d+)?)?\s+Error:\s*$",
    re.MULTILINE,
)
MANIFEST_INLINE_RE = re.compile(
    r"^Manifest merger failed\s*:\s*(.+)$",
    re.MULTILINE,
)

# 7. Gradle script / convention-plugin `* Where:` + `* What went wrong:` fallback (runs on LF-normalized log)
GRADLE_WHERE_WHAT_RE = re.compile(
    r"^\* Where:\s*\n(?:Build file|Settings file|Script)\s+'([^']+)'(?:\s+line:\s*(\d+))?\s*\n\s*\n\* What went wrong:\s*\n([^\n]+(?:\n[ \t>+]+[^\n]+){0,3})",
    re.MULTILINE,
)


def _fold_ksp_continuation(lines: list[str], start_idx: int, base_msg: str) -> str:
    parts = [base_msg.strip()]
    idx = start_idx + 1
    while idx < len(lines) and len(parts) < 4:
        nxt = lines[idx].rstrip()
        stripped = nxt.strip()
        if not stripped:
            break
        if (
            nxt.startswith(("  ", "\t"))
            or stripped.startswith(("[SQLITE_", "Expected:", "Found:", "Columns:", "Near "))
        ) and not stripped.startswith(("> Task ", "e: ", "w: ", "[ksp]", "FAILURE:", "* What went wrong:")):
            parts.append(stripped)
            idx += 1
            continue
        break
    return " — ".join(parts)


def _fold_dagger_injection_site(lines: list[str], start_idx: int, tag: str, headline: str) -> str:
    msg = f"[{tag}] {headline.strip()}"
    injected_target = ""
    idx = start_idx + 1
    limit = min(len(lines), start_idx + 18)
    while idx < limit:
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith(("> Task ", "FAILURE:", "* What went wrong:", "error: [Dagger/", "[Dagger/")):
            break
        m_site = re.search(r"(?:\[[^\]]+\]\s*)?([a-zA-Z0-9_.]+\.[A-Z][a-zA-Z0-9_]*(?:\([^)]*\)|\.[a-zA-Z0-9_]+))", stripped)
        if m_site and " is injected at" not in stripped and " is requested at" not in stripped:
            cand = m_site.group(1).strip()
            if not cand.endswith(("HiltComponents", "SingletonC", "ViewModelC", "ActivityRetainedC")):
                injected_target = cand
                break
        idx += 1
    if injected_target and injected_target not in msg:
        return f"{msg} (injected at {injected_target})"
    return msg


def parse_compiler_errors(raw_log: str) -> list[dict]:
    if not raw_log:
        return []
    normalized = raw_log.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    line_offsets: list[int] = []
    pos = 0
    for ln in lines:
        line_offsets.append(pos)
        pos += len(ln) + 1

    def _line_index_at(char_offset: int) -> int:
        return max(0, bisect.bisect_right(line_offsets, char_offset) - 1)

    errors: list[dict] = []
    seen: set[tuple[str, int, str]] = set()

    def _add(err_type: str, filepath: str, line_no: int, col_no: int | None, message: str) -> None:
        fp = filepath.strip()
        msg = re.sub(r"\s+", " ", message.strip())
        if not fp or not msg:
            return
        key = (fp, line_no, msg)
        if key in seen:
            return
        seen.add(key)
        errors.append({
            "type": err_type,
            "file": fp,
            "line": line_no,
            "column": col_no,
            "message": msg,
        })

    # 1. KSP / Room
    for match in KSP_ERROR_RE.finditer(normalized):
        filepath, line_s, col_s, msg = match.groups()
        l_idx = _line_index_at(match.start())
        full_msg = _fold_ksp_continuation(lines, l_idx, msg)
        _add("KSP", filepath, int(line_s), int(col_s) if col_s else None, full_msg)

    # 2. Kotlin
    for match in KOTLIN_ERROR_RE.finditer(normalized):
        filepath, p_line, p_col, c_line, c_col, msg = match.groups()
        line_s = p_line or c_line
        col_s = p_col or c_col
        _add("Kotlin", filepath, int(line_s), int(col_s) if col_s else None, msg)

    # 3. Dagger / Hilt
    for match in DAGGER_HILT_RE.finditer(normalized):
        filepath = match.group("file") or "DI/HiltGraph"
        line_s = match.group("line")
        tag = match.group("tag")
        headline = match.group("msg")
        l_idx = _line_index_at(match.start())
        full_msg = _fold_dagger_injection_site(lines, l_idx, tag, headline)
        _add("Dagger/Hilt", filepath, int(line_s) if line_s else 1, None, full_msg)

    # 4. Java
    for match in JAVAC_ERROR_RE.finditer(normalized):
        filepath, line_s, msg = match.groups()
        _add("Java", filepath, int(line_s), None, msg)

    # 5. AAPT2 XML resource compilation & linking
    aapt_spans: set[tuple[str, int]] = set()
    for match in AAPT2_PREFIXED_RE.finditer(normalized):
        filepath, line_s, col_s, msg = match.groups()
        aapt_spans.add((filepath.strip(), int(line_s)))
        _add("AAPT2", filepath, int(line_s), int(col_s) if col_s else None, msg)
    for match in AAPT2_PLAIN_XML_RE.finditer(normalized):
        filepath, line_s, col_s, msg = match.groups()
        if (filepath.strip(), int(line_s)) not in aapt_spans:
            _add("AAPT2", filepath, int(line_s), int(col_s) if col_s else None, msg)

    # 6. AndroidManifest Merger
    manifest_matched = False
    for match in MANIFEST_FILE_ERROR_RE.finditer(normalized):
        filepath, line_s, col_s = match.groups()
        l_idx = _line_index_at(match.start())
        detail_parts: list[str] = []
        for nxt in lines[l_idx + 1 : l_idx + 5]:
            s_nxt = nxt.strip()
            if not s_nxt or s_nxt.startswith(("> Task ", "FAILURE:", "* What went wrong:", "See http")):
                break
            detail_parts.append(s_nxt)
        if detail_parts:
            manifest_matched = True
            _add("Manifest", filepath, int(line_s), int(col_s) if col_s else None, " ".join(detail_parts))
    if not manifest_matched:
        for match in MANIFEST_INLINE_RE.finditer(normalized):
            _add("Manifest", "AndroidManifest.xml", 1, None, match.group(1))

    # 7. Gradle script / convention-plugin failure fallback when no file-level compiler error matched
    if not errors:
        for match in GRADLE_WHERE_WHAT_RE.finditer(normalized):
            filepath, line_s, what_body = match.groups()
            cleaned_what = " — ".join(
                ln.strip().lstrip("> ").strip()
                for ln in what_body.splitlines()
                if ln.strip() and not ln.strip().startswith("Execution failed for task ")
            )
            if not cleaned_what:
                cleaned_what = what_body.splitlines()[0].strip()
            _add("Gradle", filepath, int(line_s) if line_s else 1, None, cleaned_what)

    return errors


def format_errors(errors: list[dict]) -> str:
    if not errors:
        return "[OK] No compiler errors detected in build log."

    lines = [f"[ERROR] Found {len(errors)} compilation error(s):"]
    for i, err in enumerate(errors, 1):
        col_str = f":{err['column']}" if err["column"] else ""
        lines.append(f"  {i}. [{err['type']}] {err['file']}:{err['line']}{col_str}")
        lines.append(f"     ↳ {err['message']}")
    return "\n".join(lines)


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--log":
        log_path = Path(sys.argv[2])
        if not log_path.is_file():
            print(f"Log file not found: {log_path}", file=sys.stderr)
            sys.exit(1)
        raw_log = log_path.read_text(encoding="utf-8", errors="replace")
    else:
        raw_log = __import__("_vnext_common").read_utf8_stdin()

    errors = parse_compiler_errors(raw_log)
    print(format_errors(errors))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
