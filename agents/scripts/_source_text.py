"""Mask or strip Java/Kotlin/Swift comments and literals while preserving exact source offsets."""
from __future__ import annotations

_EXPR_CONT_PREFIXES = (".", "?.", "?:", "&&", "||")


def _scan_source(text: str, *, mask_strings: bool) -> str:
    """Single-pass lexer for comments and string/char/raw literals with `${...}` nesting."""
    out = list(text)
    n = len(text)
    i = 0
    mode = "CODE"
    comment_depth = 0
    interp_stack: list[tuple[str, int]] = []

    def _blank(start: int, end: int) -> None:
        for k in range(start, end):
            if out[k] not in "\r\n":
                out[k] = " "

    while i < n:
        ch = text[i]
        if mode == "LINE_COMMENT":
            if ch == "\n":
                mode = "CODE"
                i += 1
            else:
                if ch != "\r":
                    out[i] = " "
                i += 1
        elif mode == "BLOCK_COMMENT":
            if text.startswith("/*", i):
                _blank(i, i + 2)
                comment_depth += 1
                i += 2
            elif text.startswith("*/", i):
                _blank(i, i + 2)
                comment_depth -= 1
                i += 2
                if comment_depth <= 0:
                    comment_depth = 0
                    mode = "CODE"
            else:
                if ch not in "\r\n":
                    out[i] = " "
                i += 1
        elif mode == "RAW_STRING":
            if text.startswith("${", i):
                if mask_strings:
                    _blank(i, i + 2)
                interp_stack.append(("RAW_STRING", 1))
                mode = "CODE"
                i += 2
            elif text.startswith('"""', i):
                end_q = i + 3
                while end_q < n and text[end_q] == '"':
                    end_q += 1
                if mask_strings:
                    _blank(i, end_q)
                i = end_q
                mode = "CODE"
            else:
                if mask_strings and ch not in "\r\n":
                    out[i] = " "
                i += 1
        elif mode == "STRING":
            if ch == "\\":
                end_esc = min(n, i + 2)
                if mask_strings:
                    _blank(i, end_esc)
                i = end_esc
            elif text.startswith("${", i):
                if mask_strings:
                    _blank(i, i + 2)
                interp_stack.append(("STRING", 1))
                mode = "CODE"
                i += 2
            elif ch == '"':
                if mask_strings:
                    out[i] = " "
                i += 1
                mode = "CODE"
            elif ch == "\n":
                i += 1
                mode = "CODE"
            else:
                if mask_strings and ch != "\r":
                    out[i] = " "
                i += 1
        elif mode == "CHAR":
            if ch == "\\":
                end_esc = min(n, i + 2)
                if mask_strings:
                    _blank(i, end_esc)
                i = end_esc
            elif ch == "'":
                if mask_strings:
                    out[i] = " "
                i += 1
                mode = "CODE"
            elif ch == "\n":
                i += 1
                mode = "CODE"
            else:
                if mask_strings and ch != "\r":
                    out[i] = " "
                i += 1
        else:  # CODE
            if text.startswith("//", i):
                _blank(i, i + 2)
                mode = "LINE_COMMENT"
                i += 2
            elif text.startswith("/*", i):
                _blank(i, i + 2)
                comment_depth = 1
                mode = "BLOCK_COMMENT"
                i += 2
            elif text.startswith('"""', i):
                if mask_strings:
                    _blank(i, i + 3)
                mode = "RAW_STRING"
                i += 3
            elif ch == '"':
                if mask_strings:
                    out[i] = " "
                mode = "STRING"
                i += 1
            elif ch == "'":
                if mask_strings:
                    out[i] = " "
                mode = "CHAR"
                i += 1
            elif ch == "{":
                if interp_stack:
                    ret_mode, depth = interp_stack[-1]
                    interp_stack[-1] = (ret_mode, depth + 1)
                i += 1
            elif ch == "}":
                if interp_stack:
                    ret_mode, depth = interp_stack[-1]
                    if depth <= 1:
                        interp_stack.pop()
                        if mask_strings:
                            out[i] = " "
                        mode = ret_mode
                    else:
                        interp_stack[-1] = (ret_mode, depth - 1)
                i += 1
            else:
                i += 1
    return "".join(out)


def mask_comments_and_strings(text: str) -> str:
    """Mask comments and string/char/raw literals to spaces while preserving `\\r`/`\\n` and `${...}` code expressions."""
    return _scan_source(text, mask_strings=True)


def strip_kotlin_comments_preserving_strings(text: str) -> str:
    """Blank `//` and nested `/* ... */` comments while keeping string and raw-string literals intact."""
    return _scan_source(text, mask_strings=False)


def scan_top_level_assignment(line: str, start_parens: int = 0) -> tuple[bool, bool]:
    """Return `(has_top_level_eq, ends_with_top_level_eq)` outside `(...)` parameter lists on a masked code line."""
    p_depth = max(0, start_parens)
    n = len(line)
    for idx, ch in enumerate(line):
        if ch == "(":
            p_depth += 1
        elif ch == ")":
            p_depth = max(0, p_depth - 1)
        elif ch == "=" and p_depth == 0:
            prev_ch = line[idx - 1] if idx > 0 else ""
            next_ch = line[idx + 1] if idx + 1 < n else ""
            if prev_ch in ("=", "!", "<", ">") or next_ch in ("=", ">"):
                continue
            trailing = line[idx + 1 :].strip()
            return True, (trailing == "")
    return False, False


def is_expr_continuation_line(stripped: str) -> bool:
    """Return True when a masked code line starts with a chained expression continuation operator."""
    return bool(stripped) and stripped.startswith(_EXPR_CONT_PREFIXES)
