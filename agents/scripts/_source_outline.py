"""Line numbers for Kotlin and Java declarations and references.

task-context hands these to the agent so it opens the lines that matter instead of
whole files. The scan is lexical (no parser): string literals and comments are
blanked before braces are counted, and anything it cannot place is left out rather
than guessed. An outline is a reading aid, never evidence.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

MAX_OUTLINE = 150
MAX_REFERENCE_LINES = 12
_MAX_FILE_BYTES = 1_500_000

_MODIFIERS = (
    r"(?:(?:public|private|internal|protected|override|open|abstract|final|sealed|data|enum|inner|annotation|"
    r"value|inline|noinline|suspend|operator|infix|tailrec|external|const|lateinit|expect|actual|static|"
    r"synchronized|default|native|transient|volatile|strictfp)\s+)*"
)
_ANNOTATIONS = r"(?:@[\w.]+(?:\([^()]*\))?\s+)*"
_KOTLIN_DECL = re.compile(
    r"^\s*" + _ANNOTATIONS + _MODIFIERS
    + r"(?P<kind>companion\s+object|class|interface|object|fun|val|var|typealias)\b"
    + r"\s*(?:<[^>]*>\s*)?(?:[\w.<>?, ]+?\.)?(?P<name>`[^`]+`|\w+)?"
)
_JAVA_TYPE = re.compile(r"^\s*" + _ANNOTATIONS + _MODIFIERS + r"(?P<kind>class|interface|enum|record|@interface)\s+(?P<name>\w+)")
_JAVA_METHOD = re.compile(
    r"^\s*" + _ANNOTATIONS + r"(?:(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)+"
    r"(?:<[^>]*>\s*)?[\w.<>\[\]?, ]+?\s+(?P<name>\w+)\s*\("
)
_STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def _read(path: Path) -> list[str] | None:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None


def _code_lines(lines: list[str]) -> list[str]:
    """Blank string literals and comments so braces and names in them are not counted."""
    out: list[str] = []
    in_block = False
    for raw in lines:
        line = raw
        if in_block:
            end = line.find("*/")
            if end < 0:
                out.append("")
                continue
            line = " " * (end + 2) + line[end + 2:]
            in_block = False
        line = _STRING.sub(lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', line)
        while True:
            start = line.find("/*")
            if start < 0:
                break
            end = line.find("*/", start + 2)
            if end < 0:
                line = line[:start]
                in_block = True
                break
            line = line[:start] + " " * (end + 2 - start) + line[end + 2:]
        comment = line.find("//")
        if comment >= 0:
            line = line[:comment]
        out.append(line)
    return out


def outline(path: Path) -> list[dict[str, Any]]:
    """Declarations with 1-based start and end lines, members of nested types included.

    Properties are listed only at file or type level, so locals inside functions do not
    crowd the outline. ``end_line`` equals ``line`` for single-line or expression bodies.
    """
    lines = _read(path)
    if lines is None:
        return []
    java = path.suffix.lower() == ".java"
    code = _code_lines(lines)
    entries: list[dict[str, Any]] = []
    open_blocks: list[tuple[dict[str, Any], int]] = []
    # Brace depth of each enclosing block, and whether that block is a type body.
    type_depths: set[int] = {0}
    depth = 0
    parens = 0  # open "(" across lines: constructor parameters and call arguments are not declarations
    # A declaration whose body brace comes on a later line: after a multi-line signature
    # ("paren") or alone on the next line ("brace_next").
    pending: tuple[dict[str, Any], int, str] | None = None
    for index, line in enumerate(code, start=1):
        entry = None
        stripped = line.strip()
        if stripped and parens == 0:
            match = (_JAVA_TYPE.match(line) or _JAVA_METHOD.match(line)) if java else _KOTLIN_DECL.match(line)
            if match:
                kind = " ".join((match.groupdict().get("kind") or "method").split())
                name = (match.group("name") or "").strip("`")
                if kind == "companion object" and not name:
                    name = "Companion"
                is_property = kind in ("val", "var")
                if name and (not is_property or depth in type_depths) and (depth in type_depths or kind in ("fun", "method")):
                    entry = {"line": index, "end_line": index, "kind": kind, "name": name}
                    if depth == 0:
                        entry["top_level"] = True
                    entries.append(entry)
        opens, closes = line.count("{"), line.count("}")
        parens_after = max(0, parens + line.count("(") - line.count(")"))
        body: tuple[dict[str, Any], int] | None = None
        if entry is not None:
            pending = None
            if opens > closes:
                body = (entry, depth)
            elif parens_after > 0:
                pending = (entry, depth, "paren")
            elif "=" not in line and not stripped.endswith(("}", ";")):
                pending = (entry, depth, "brace_next")
        elif pending is not None:
            held, held_depth, mode = pending
            if mode == "paren":
                if parens_after == 0:
                    if opens > closes:
                        body, pending = (held, held_depth), None
                    elif "=" not in line and not stripped.endswith(("}", ";")):
                        pending = (held, held_depth, "brace_next")
                    else:
                        pending = None
            elif stripped:
                if stripped.startswith("{"):
                    body = (held, held_depth)
                pending = None
        if body is not None:
            open_blocks.append(body)
            if body[0]["kind"] not in ("fun", "method", "val", "var"):
                type_depths.add(body[1] + 1)
        depth = max(0, depth + opens - closes)
        parens = parens_after
        while open_blocks and depth <= open_blocks[-1][1]:
            done, start_depth = open_blocks.pop()
            done["end_line"] = index
            type_depths.discard(start_depth + 1)
    if len(entries) <= MAX_OUTLINE:
        return entries
    # A large file: types and functions first, properties only in the room that is left.
    ranked = sorted(entries, key=lambda e: (e["kind"] in ("val", "var"), e["line"]))[:MAX_OUTLINE]
    return sorted(ranked, key=lambda e: e["line"])


def declaration_line(path: Path, name: str) -> int:
    for entry in outline(path):
        if entry["name"] == name and entry["kind"] not in ("val", "var"):
            return int(entry["line"])
    return 0


def reference_lines(path: Path, names: list[str] | set[str]) -> list[int]:
    """Lines outside imports and comments that mention any of ``names`` as a whole word."""
    wanted = sorted({str(n) for n in names if n and len(str(n)) > 2})
    lines = _read(path)
    if not wanted or lines is None:
        return []
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in wanted) + r")\b")
    hits: list[int] = []
    for index, line in enumerate(_code_lines(lines), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("import ", "package ")):
            continue
        if pattern.search(line):
            hits.append(index)
            if len(hits) >= MAX_REFERENCE_LINES:
                break
    return hits


def as_ranges(numbers: list[int]) -> str:
    """[3, 4, 5, 9] -> "L3-L5, L9"."""
    parts: list[str] = []
    run: list[int] = []
    for number in sorted(set(numbers)):
        if run and number == run[-1] + 1:
            run.append(number)
            continue
        if run:
            parts.append(f"L{run[0]}" if len(run) == 1 else f"L{run[0]}-L{run[-1]}")
        run = [number]
    if run:
        parts.append(f"L{run[0]}" if len(run) == 1 else f"L{run[0]}-L{run[-1]}")
    return ", ".join(parts)


def line_count(path: Path) -> int:
    lines = _read(path)
    return len(lines) if lines is not None else 0
