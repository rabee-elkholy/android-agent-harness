"""Mask or strip Java/Kotlin/Swift comments and literals while preserving exact source offsets."""
from __future__ import annotations

_EXPR_CONT_PREFIXES = (".", "?.", "?:", "&&", "||")


def _scan_source(
    text: str,
    *,
    mask_strings: bool,
    nested_comments: bool = True,
    allow_raw_strings: bool = True,
    allow_dollar_interp: bool = True,
    line_open_states: list[bool] | None = None,
) -> str:
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
        if ch == "\n" and line_open_states is not None:
            line_open_states.append(mode == "RAW_STRING" or bool(interp_stack))
        if mode == "LINE_COMMENT":
            if ch == "\n":
                mode = "CODE"
                i += 1
            else:
                if ch != "\r":
                    out[i] = " "
                i += 1
        elif mode == "BLOCK_COMMENT":
            if nested_comments and text.startswith("/*", i):
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
            if allow_dollar_interp and text.startswith("${", i):
                if mask_strings:
                    _blank(i, i + 2)
                interp_stack.append(("RAW_STRING", 1))
                mode = "CODE"
                i += 2
            elif not allow_dollar_interp and ch == "\\" and i + 1 < n:
                end_esc = min(n, i + 2)
                if mask_strings:
                    _blank(i, end_esc)
                i = end_esc
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
            elif allow_dollar_interp and text.startswith("${", i):
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
            elif allow_raw_strings and text.startswith('"""', i):
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
    if line_open_states is not None:
        line_open_states.append(mode == "RAW_STRING" or bool(interp_stack))
    return "".join(out)


def _uses_dollar_interp(rel_path: str) -> bool:
    low = str(rel_path or "").lower()
    return (not low) or low.endswith((".kt", ".kts", ".groovy", ".gradle"))


def mask_comments_and_strings(text: str, *, rel_path: str = "") -> str:
    """Mask comments and string/char/raw literals to spaces while preserving `\\r`/`\\n` and `${...}` code expressions."""
    is_java = str(rel_path or "").lower().endswith(".java")
    return _scan_source(
        text,
        mask_strings=True,
        nested_comments=not is_java,
        allow_dollar_interp=_uses_dollar_interp(rel_path),
    )


def mask_comments_and_strings_with_state(text: str, *, rel_path: str = "") -> tuple[list[str], list[bool]]:
    """Return `(masked_lines, raw_literal_open_at_eol)` for exact multi-line triple-quoted symbol spans."""
    if not text:
        return ([], [])
    is_java = str(rel_path or "").lower().endswith(".java")
    open_states: list[bool] = []
    masked = _scan_source(
        text,
        mask_strings=True,
        nested_comments=not is_java,
        allow_dollar_interp=_uses_dollar_interp(rel_path),
        line_open_states=open_states,
    )
    lines = masked.split("\n")
    if len(open_states) < len(lines):
        open_states.extend([False] * (len(lines) - len(open_states)))
    return (lines, open_states[: len(lines)])


def strip_kotlin_comments_preserving_strings(text: str) -> str:
    """Blank `//` and nested `/* ... */` comments while keeping string and raw-string literals intact."""
    return _scan_source(text, mask_strings=False)


def strip_comments_for_path(text: str, rel_path: str = "") -> str:
    """Blank `//` and `/* ... */` comments with language-accurate nesting and raw-string handling."""
    low = str(rel_path or "").lower()
    supports_nested = low.endswith((".kt", ".kts", ".swift"))
    allow_raw = low.endswith((".kt", ".kts", ".java", ".swift", ".groovy", ".gradle"))
    return _scan_source(
        text,
        mask_strings=False,
        nested_comments=supports_nested,
        allow_raw_strings=allow_raw,
        allow_dollar_interp=_uses_dollar_interp(rel_path),
    )


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
