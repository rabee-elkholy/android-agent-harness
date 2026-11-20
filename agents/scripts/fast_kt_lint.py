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
    rf"\b("
    rf"androidx\.[a-zA-Z0-9_.]+|"
    rf"{re.escape(PACKAGE_PREFIX)}\.[a-zA-Z0-9_.]+|"
    rf"android\.(?:view|widget|graphics|os|content)\.[a-zA-Z0-9_.]+|"
    rf"kotlinx\.coroutines\.(?:[a-z0-9_]+\.)*[A-Z][a-zA-Z0-9_.]*|"
    rf"java\.(?:util|io|time|net|math)\.(?:[a-z0-9_]+\.)*[A-Z][a-zA-Z0-9_.]*"
    rf")\b"
)
FQCN_WHITELIST = re.compile(
    r"^(?:"
    r"android\.os\.Build(?:\.VERSION(?:\.SDK_INT|_CODES)?)?|"
    r"java\.util\.(?:UUID|Locale|Date|Objects)|"
    r"androidx\.annotation\.\w+|"
    r"androidx\.compose\.\w+\.Experimental\w+|"
    r"kotlinx\.coroutines\.(?:\w*Experimental\w*|FlowPreview|DelicateCoroutinesApi|InternalCoroutinesApi|ObsoleteCoroutinesApi)"
    r")$"
)

WILDCARD_IMPORT_PATTERN = re.compile(r"^import\s+[a-zA-Z0-9_.]+\.\*")
STATE_CLASS_PATTERN = re.compile(r"data\s+class\s+[A-Za-z0-9_]*State\b")
RUNBLOCKING_PATTERN = re.compile(r"\brunBlocking\s*(\(|{)")
UNIMPLEMENTED_STUB_PATTERN = re.compile(r"\b(TODO\s*\(|throw\s+NotImplementedError\s*\()")
DOUBLE_BANG_PATTERN = re.compile(r"[a-zA-Z0-9_\)\]]\s*!!")
DIAGNOSTIC_PROBE_PATTERN = re.compile(r"(?:\[HARNESS-PROBE\]|\bHARNESS_PROBE\b)")
DEAD_CODE_WORKAROUND_PATTERN = re.compile(
    r"(?:\bif\s*\(\s*(?:true|false)\s*\)|\|\|\s*false\b|&&\s*true\b|\brun\s*\{\s*run\s*\{|\b(?:private\s+)?fun\s+(?:unusedHelper|_vmKeep|_signInKeep)\s*\()"
)
PENDING_INTENT_FACTORY_PATTERN = re.compile(
    r"\bPendingIntent\s*\.\s*get(?:Activity|Activities|Service|Broadcast|ForegroundService)\s*\("
)
PENDING_INTENT_IMMUTABILITY_FLAG_RE = re.compile(
    r"\b(?:FLAG_IMMUTABLE|FLAG_MUTABLE)\b"
)
SUSPEND_FUN_DECL_RE = re.compile(
    r"\bsuspend\s+(?:(?:private|internal|public|protected|override|inline|operator|infix|tailrec|actual)\s+)*fun\b"
)
GENERIC_CATCH_DECL_RE = re.compile(
    r"\bcatch\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?:kotlin\.|java\.lang\.)?(?:Exception|Throwable)\s*\)\s*\{"
)


def _strip_kotlin_comments_preserve_lines(text: str) -> str:
    """Mask comments and string/raw-string literals (including `${...}` nested quotes and nested `/* */`) preserving exact newlines."""
    from _source_text import mask_comments_and_strings
    return mask_comments_and_strings(text)


def _extract_balanced_brace_body(clean_text: str, open_brace_index: int) -> tuple[str, int] | None:
    """Given index right at '{', return (body_inside_braces, close_brace_index) or None if unbalanced."""
    if open_brace_index < 0 or open_brace_index >= len(clean_text) or clean_text[open_brace_index] != "{":
        return None
    depth = 1
    pos = open_brace_index + 1
    n = len(clean_text)
    while pos < n and depth > 0:
        ch = clean_text[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        pos += 1
    if depth != 0:
        return None
    return clean_text[open_brace_index + 1:pos - 1], pos - 1


def _find_suspend_cancellation_swallows(clean_text: str, modified_lines: set[int] | None) -> list[tuple[int, str]]:
    """Detect catch(e: Exception|Throwable) inside suspend fun bodies that swallow CancellationException."""
    findings: list[tuple[int, str]] = []
    line_starts = [0]
    for idx, ch in enumerate(clean_text):
        if ch == "\n":
            line_starts.append(idx + 1)

    def offset_to_line(offset: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if line_starts[mid] <= offset:
                lo = mid + 1
            else:
                hi = mid - 1
        return hi + 1

    suspend_ranges: list[tuple[int, int]] = []
    for m_sus in SUSPEND_FUN_DECL_RE.finditer(clean_text):
        # Locate opening '{' of this suspend function header (before any top-level ';' or unbalanced brace)
        pos = m_sus.end()
        paren_depth = 0
        open_brace = -1
        while pos < len(clean_text):
            ch = clean_text[pos]
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
            elif paren_depth == 0 and ch == "{":
                open_brace = pos
                break
            elif paren_depth == 0 and ch == "=":
                # Single-expression suspend fun `suspend fun foo() = try { ... } catch (e: Exception) { ... }`
                expr_start = pos + 1
                epos = expr_start
                b_depth = 0
                p_depth = 0
                k_depth = 0
                while epos < len(clean_text):
                    ech = clean_text[epos]
                    if ech == "{":
                        b_depth += 1
                    elif ech == "}":
                        if b_depth == 0:
                            break
                        b_depth -= 1
                    elif ech == "(":
                        p_depth += 1
                    elif ech == ")":
                        p_depth = max(0, p_depth - 1)
                    elif ech == "[":
                        k_depth += 1
                    elif ech == "]":
                        k_depth = max(0, k_depth - 1)
                    elif b_depth == 0 and p_depth == 0 and k_depth == 0 and ech == "\n":
                        rest = clean_text[epos + 1 :].lstrip(" \t\r\n")
                        if not rest.startswith((".", "?.", "?:", "catch", "finally", "else", "+", "-", "&&", "||", "{")):
                            break
                    epos += 1
                if epos > expr_start:
                    suspend_ranges.append((expr_start, epos))
                break
            pos += 1
        if open_brace != -1:
            extracted = _extract_balanced_brace_body(clean_text, open_brace)
            if extracted is not None:
                _, close_brace = extracted
                suspend_ranges.append((open_brace, close_brace))

    if not suspend_ranges:
        return findings

    for m_catch in GENERIC_CATCH_DECL_RE.finditer(clean_text):
        catch_start = m_catch.start()
        if not any(r_start <= catch_start <= r_end for r_start, r_end in suspend_ranges):
            continue
        catch_line = offset_to_line(catch_start)
        open_brace = m_catch.end() - 1
        extracted = _extract_balanced_brace_body(clean_text, open_brace)
        if extracted is None:
            continue
        catch_body, close_brace = extracted
        catch_end_line = offset_to_line(close_brace)
        if modified_lines is not None:
            if not any(ln in modified_lines for ln in range(catch_line, catch_end_line + 1)):
                continue
        caught_var = m_catch.group(1)
        preceding_window = clean_text[max(0, catch_start - 320) : catch_start]
        has_sibling_cancel_catch = bool(
            re.search(
                r"\bcatch\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*(?:[A-Za-z0-9_.]+\.)?CancellationException\s*\)\s*\{[^{}]*\bthrow\b[^{}]*\}\s*$",
                preceding_window,
                re.DOTALL,
            )
        )
        rethrows_cancellation = has_sibling_cancel_catch or bool(
            re.search(r"\bCancellationException\b|\bensureActive\s*\(|\byield\s*\(", catch_body)
            or re.search(rf"\bthrow\s+{re.escape(caught_var)}\b", catch_body)
        )
        if not rethrows_cancellation:
            findings.append((catch_line, caught_var))
    return findings
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


def _strip_kotlin_comments_keep_templates(text: str) -> str:
    """Strip // and /* */ comments while preserving exact newlines and $ident / ${...} string templates."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n:
                if text[i] == "*" and i + 1 < n and text[i + 1] == "/":
                    out.append("  ")
                    i += 2
                    break
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue
        if text.startswith('"""', i):
            out.append('"""')
            i += 3
            while i < n:
                if text.startswith('"""', i):
                    out.append('"""')
                    i += 3
                    break
                if text[i] == "$" and i + 1 < n and text[i + 1] == "{":
                    out.append("${")
                    i += 2
                    b_depth = 1
                    while i < n and b_depth > 0:
                        if text[i] == "{":
                            b_depth += 1
                        elif text[i] == "}":
                            b_depth -= 1
                        out.append(text[i])
                        i += 1
                    continue
                if text[i] == "$" and i + 1 < n and (text[i + 1].isalpha() or text[i + 1] == "_"):
                    out.append("$")
                    i += 1
                    while i < n and (text[i].isalnum() or text[i] == "_"):
                        out.append(text[i])
                        i += 1
                    continue
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue
        if ch == '"':
            out.append('"')
            i += 1
            while i < n and text[i] != "\n":
                if text[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                if text[i] == '"':
                    out.append('"')
                    i += 1
                    break
                if text[i] == "$" and i + 1 < n and text[i + 1] == "{":
                    out.append("${")
                    i += 2
                    b_depth = 1
                    while i < n and b_depth > 0 and text[i] != "\n":
                        if text[i] == "{":
                            b_depth += 1
                        elif text[i] == "}":
                            b_depth -= 1
                        out.append(text[i])
                        i += 1
                    continue
                if text[i] == "$" and i + 1 < n and (text[i + 1].isalpha() or text[i + 1] == "_"):
                    out.append("$")
                    i += 1
                    while i < n and (text[i].isalnum() or text[i] == "_"):
                        out.append(text[i])
                        i += 1
                    continue
                out.append(" ")
                i += 1
            continue
        if ch == "'":
            out.append("'")
            i += 1
            while i < n and text[i] != "\n":
                if text[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                if text[i] == "'":
                    out.append("'")
                    i += 1
                    break
                out.append(" ")
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


_UNUSED_SKIP_ANNOTATIONS_RE = re.compile(
    r"@(?:Preview|DualLocalePreviews|MultiLocalePreviews|PreviewLightDark|BindingAdapter|Subscribe|JavascriptInterface|Keep|Provides|Binds|IntoSet|IntoMap|Test|Before|After|BeforeEach|AfterEach|ParameterizedTest)\b"
)
_SUPPRESS_UNUSED_RE = re.compile(
    r'@Suppress\s*\([^)]*(?:UNUSED_PARAMETER|UnusedPrivateMember|UnusedPrivateClass|"unused")',
    re.IGNORECASE,
)
_PRIVATE_FUN_DECL_RE = re.compile(
    r"(?<!\boperator\s)\bprivate\s+(?:(?:suspend|inline|tailrec|infix)\s+)*fun\s+"
    r"(?:<[^>]+>\s*)?(?:[A-Za-z0-9_.<>?]+\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
_PRIVATE_TYPE_DECL_RE = re.compile(
    r"(?<!\bcompanion\s)\bprivate\s+(?:(?:data|sealed|enum|value|inner|abstract|open)\s+)*"
    r"(class|object|interface)\s+([A-Za-z_][A-Za-z0-9_]*)\b"
)


def _split_top_level_commas(segment: str, base_offset: int) -> list[tuple[int, str]]:
    items: list[tuple[int, str]] = []
    cur_start = 0
    p_d = a_d = k_d = b_d = 0
    for idx, ch in enumerate(segment):
        if ch == "(":
            p_d += 1
        elif ch == ")":
            p_d = max(0, p_d - 1)
        elif ch == "<":
            a_d += 1
        elif ch == ">":
            a_d = max(0, a_d - 1)
        elif ch == "[":
            k_d += 1
        elif ch == "]":
            k_d = max(0, k_d - 1)
        elif ch == "{":
            b_d += 1
        elif ch == "}":
            b_d = max(0, b_d - 1)
        elif ch == "," and p_d == 0 and a_d == 0 and k_d == 0 and b_d == 0:
            items.append((base_offset + cur_start, segment[cur_start:idx]))
            cur_start = idx + 1
    if cur_start < len(segment):
        items.append((base_offset + cur_start, segment[cur_start:]))
    return items


def _split_top_level_equals(param_chunk: str) -> tuple[str, str]:
    p_d = a_d = k_d = b_d = 0
    for idx, ch in enumerate(param_chunk):
        if ch == "(":
            p_d += 1
        elif ch == ")":
            p_d = max(0, p_d - 1)
        elif ch == "<":
            a_d += 1
        elif ch == ">":
            a_d = max(0, a_d - 1)
        elif ch == "[":
            k_d += 1
        elif ch == "]":
            k_d = max(0, k_d - 1)
        elif ch == "{":
            b_d += 1
        elif ch == "}":
            b_d = max(0, b_d - 1)
        elif ch == "=" and p_d == 0 and a_d == 0 and k_d == 0 and b_d == 0:
            if idx + 1 < len(param_chunk) and param_chunk[idx + 1] == "=":
                continue
            if idx > 0 and param_chunk[idx - 1] in ("!", "=", "<", ">"):
                continue
            return param_chunk[:idx], param_chunk[idx + 1:]
    return param_chunk, ""


def _find_unused_intra_file_code(
    file_path: Path,
    raw_text: str,
    modified_lines: set[int] | None,
    *,
    is_test: bool = False,
) -> list[dict]:
    """Detect unused function parameters, unused private functions, and unused private classes/objects."""
    issues: list[dict] = []
    tmpl_text = _strip_kotlin_comments_keep_templates(raw_text)
    raw_lines = raw_text.splitlines()
    line_starts = [0]
    for idx, ch in enumerate(tmpl_text):
        if ch == "\n":
            line_starts.append(idx + 1)

    def offset_to_line(offset: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if line_starts[mid] <= offset:
                lo = mid + 1
            else:
                hi = mid - 1
        return hi + 1

    def in_scope(ln: int) -> bool:
        return modified_lines is None or ln in modified_lines

    def header_annotations(decl_line_1: int) -> str:
        start_0 = max(0, decl_line_1 - 12)
        collected: list[str] = [raw_lines[decl_line_1 - 1]] if 1 <= decl_line_1 <= len(raw_lines) else []
        i = decl_line_1 - 2
        while i >= start_0:
            s = raw_lines[i].strip()
            if not s:
                i -= 1
                continue
            if s.endswith(("}", "{", ";")) and not s.startswith("@"):
                break
            collected.append(s)
            i -= 1
        return "\n".join(reversed(collected))

    # 1. Unused parameters on non-override, non-abstract functions (production files)
    if not is_test:
        for m_fun in re.finditer(r"\bfun\b", tmpl_text):
            fun_pos = m_fun.start()
            fun_line = offset_to_line(fun_pos)
            stmt_prefix_start = max(line_starts[fun_line - 1], fun_pos - 160)
            stmt_prefix = tmpl_text[stmt_prefix_start:fun_pos]
            last_sep = max(stmt_prefix.rfind(";"), stmt_prefix.rfind("{"), stmt_prefix.rfind("}"))
            if last_sep != -1:
                stmt_prefix = stmt_prefix[last_sep + 1:]
            if re.search(r"\b(?:override|abstract|external|expect)\b", stmt_prefix):
                continue

            # Advance past optional `<...>` type params, receiver type, and function name to `(`
            pos = m_fun.end()
            n = len(tmpl_text)
            while pos < n and tmpl_text[pos].isspace():
                pos += 1
            if pos < n and tmpl_text[pos] == "<":
                a_d = 1
                pos += 1
                while pos < n and a_d > 0:
                    if tmpl_text[pos] == "<":
                        a_d += 1
                    elif tmpl_text[pos] == ">":
                        a_d -= 1
                    pos += 1
            sig_before_paren_start = pos
            angle_d = 0
            open_paren = -1
            while pos < n:
                ch = tmpl_text[pos]
                if ch == "<":
                    angle_d += 1
                elif ch == ">":
                    angle_d = max(0, angle_d - 1)
                elif angle_d == 0 and ch == "(":
                    open_paren = pos
                    break
                elif angle_d == 0 and ch in ("{", "=", ";", "\n"):
                    break
                pos += 1
            if open_paren == -1:
                continue
            name_chunk = tmpl_text[sig_before_paren_start:open_paren].strip()
            m_fn_ident = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", name_chunk)
            if not m_fn_ident:
                continue
            fn_name = m_fn_ident.group(1)
            if fn_name.endswith(("Preview", "Previews")):
                continue
            ann_ctx = header_annotations(fun_line)
            if _UNUSED_SKIP_ANNOTATIONS_RE.search(ann_ctx) or _SUPPRESS_UNUSED_RE.search(ann_ctx):
                continue

            # Extract balanced parameter list `(...)`
            p_d = 1
            p_pos = open_paren + 1
            while p_pos < n and p_d > 0:
                if tmpl_text[p_pos] == "(":
                    p_d += 1
                elif tmpl_text[p_pos] == ")":
                    p_d -= 1
                p_pos += 1
            if p_d != 0:
                continue
            close_paren = p_pos - 1
            params_inner = tmpl_text[open_paren + 1:close_paren]
            if not params_inner.strip():
                continue

            # Locate function body (`{ ... }` or `= expr`); skip interface/abstract methods with no body
            scan = close_paren + 1
            s_paren = s_angle = s_brack = 0
            body_region = ""
            while scan < n:
                sch = tmpl_text[scan]
                if sch == "(":
                    s_paren += 1
                elif sch == ")":
                    if s_paren == 0:
                        break
                    s_paren -= 1
                elif sch == "<":
                    s_angle += 1
                elif sch == ">":
                    s_angle = max(0, s_angle - 1)
                elif sch == "[":
                    s_brack += 1
                elif sch == "]":
                    s_brack = max(0, s_brack - 1)
                elif s_paren == 0 and s_angle == 0 and s_brack == 0:
                    if sch == "{":
                        extracted = _extract_balanced_brace_body(tmpl_text, scan)
                        if extracted is not None:
                            inner_b, close_b = extracted
                            if inner_b.strip():
                                body_region = tmpl_text[close_paren + 1:close_b + 1]
                        break
                    if sch == "=" and (scan + 1 >= n or tmpl_text[scan + 1] != "="):
                        epos = scan + 1
                        eb = ep = ek = 0
                        while epos < n:
                            ech = tmpl_text[epos]
                            if ech == "{":
                                eb += 1
                            elif ech == "}":
                                if eb == 0:
                                    break
                                eb -= 1
                            elif ech == "(":
                                ep += 1
                            elif ech == ")":
                                if ep == 0:
                                    break
                                ep -= 1
                            elif ech == "[":
                                ek += 1
                            elif ech == "]":
                                ek = max(0, ek - 1)
                            elif eb == 0 and ep == 0 and ek == 0 and ech == "\n":
                                rest_ln = tmpl_text[epos + 1:].lstrip(" \t\r\n")
                                if not rest_ln.startswith((".", "?.", "?:", "else", "+", "-", "&&", "||", "{")):
                                    break
                            epos += 1
                        body_region = tmpl_text[close_paren + 1:epos]
                        break
                    if sch in (";", "}"):
                        break
                    if sch == "\n":
                        nxt = tmpl_text[scan + 1:].lstrip(" \t\r")
                        if re.match(r"^(?:@(?:[A-Za-z0-9_.]+)|(?:public|internal|private|protected|override|suspend|fun|val|var|class|interface|object|enum|sealed|data)\b|\})", nxt):
                            break
                scan += 1

            if not body_region or UNIMPLEMENTED_STUB_PATTERN.search(body_region):
                continue

            raw_segments = _split_top_level_commas(params_inner, open_paren + 1)
            parsed_params: list[tuple[str, int, str]] = []
            for seg_off, seg_txt in raw_segments:
                if not seg_txt.strip():
                    continue
                decl_part, def_part = _split_top_level_equals(seg_txt)
                cleaned_decl = re.sub(r"@[A-Za-z0-9_.]+(?:\([^)]*\))?", " ", decl_part)
                cleaned_decl = re.sub(r"\b(?:vararg|noinline|crossinline)\b", " ", cleaned_decl)
                if re.search(r"\b(?:val|var)\b", cleaned_decl):
                    continue
                m_p = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", cleaned_decl)
                if not m_p:
                    continue
                p_name = m_p.group(1)
                ident_rel = decl_part.find(p_name)
                p_line = offset_to_line(seg_off + max(0, ident_rel))
                parsed_params.append((p_name, p_line, def_part))

            for idx_p, (p_name, p_line, _) in enumerate(parsed_params):
                if p_name.startswith("_"):
                    continue
                if not (in_scope(p_line) or in_scope(fun_line)):
                    continue
                other_defaults = "\n".join(dp_txt for j, (_, _, dp_txt) in enumerate(parsed_params) if j != idx_p and dp_txt)
                haystack = body_region + "\n" + other_defaults
                if not re.search(rf"(?:\b{re.escape(p_name)}\b|`{re.escape(p_name)}`)", haystack):
                    issues.append({
                        "file": str(file_path),
                        "line": p_line,
                        "type": "UNUSED_PARAMETER",
                        "msg": (
                            f"Unused parameter '{p_name}' in 'fun {fn_name}(...)'. "
                            "Wire it into the implementation, prefix with '_' if required by a callback signature, or remove dead parameter."
                        ),
                    })

    # 2. Unused private functions (file-scoped)
    for m_pf in _PRIVATE_FUN_DECL_RE.finditer(tmpl_text):
        fn_name = m_pf.group(1)
        decl_line = offset_to_line(m_pf.start(1))
        if not in_scope(decl_line):
            continue
        if fn_name.endswith(("Preview", "Previews")) or fn_name in {
            "readResolve", "writeReplace", "writeObject", "readObject",
            "unusedHelper", "_vmKeep", "_signInKeep",
        }:
            continue
        stmt_pre = tmpl_text[max(0, m_pf.start() - 40):m_pf.start()]
        if re.search(r"\boperator\b", stmt_pre):
            continue
        ann_ctx = header_annotations(decl_line)
        if _UNUSED_SKIP_ANNOTATIONS_RE.search(ann_ctx) or _SUPPRESS_UNUSED_RE.search(ann_ctx):
            continue
        rest_file = tmpl_text[:m_pf.start(1)] + " " + tmpl_text[m_pf.end(1):]
        if not re.search(rf"(?:\b{re.escape(fn_name)}\b|`{re.escape(fn_name)}`)", rest_file):
            issues.append({
                "file": str(file_path),
                "line": decl_line,
                "type": "UNUSED_PRIVATE_FUNCTION",
                "msg": f"Unused private function 'private fun {fn_name}(...)' is never called in {file_path.name}. Wire it in or remove dead code.",
            })

    # 3. Unused private classes / objects / interfaces (file-scoped)
    for m_pc in _PRIVATE_TYPE_DECL_RE.finditer(tmpl_text):
        kind_kw, cls_name = m_pc.group(1), m_pc.group(2)
        decl_line = offset_to_line(m_pc.start(2))
        if not in_scope(decl_line):
            continue
        ann_ctx = header_annotations(decl_line)
        if "@Keep" in ann_ctx or _SUPPRESS_UNUSED_RE.search(ann_ctx):
            continue
        excl_start = m_pc.start()
        excl_end = m_pc.end(2)
        brace_probe = m_pc.end(2)
        p_d = 0
        while brace_probe < len(tmpl_text):
            c_ch = tmpl_text[brace_probe]
            if c_ch == "(":
                p_d += 1
            elif c_ch == ")":
                p_d = max(0, p_d - 1)
            elif p_d == 0 and c_ch == "{":
                extracted_cls = _extract_balanced_brace_body(tmpl_text, brace_probe)
                if extracted_cls is not None:
                    _, close_c = extracted_cls
                    excl_end = close_c + 1
                break
            elif p_d == 0 and c_ch in (";", "\n"):
                nxt_c = tmpl_text[brace_probe + 1:].lstrip(" \t\r")
                if not nxt_c.startswith((":", "{", "where")):
                    break
            brace_probe += 1
        rest_file = tmpl_text[:excl_start] + " " + tmpl_text[excl_end:]
        if not re.search(rf"(?:\b{re.escape(cls_name)}\b|`{re.escape(cls_name)}`)", rest_file):
            issues.append({
                "file": str(file_path),
                "line": decl_line,
                "type": "UNUSED_PRIVATE_CLASS",
                "msg": f"Unused private {kind_kw} '{cls_name}' is never referenced in {file_path.name}. Wire it in or remove dead code.",
            })

    return issues


def _in_string_or_comment(line: str, index: int) -> bool:
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

    _clean_kt = _strip_kotlin_comments_preserve_lines(text)
    kt_imported: dict[str, str] = {}
    for _imp_line in lines:
        _m_imp = re.match(r"\s*import\s+([A-Za-z0-9_.]+)\s*$", _imp_line)
        if _m_imp and not _m_imp.group(1).endswith(".*"):
            _full_imp = _m_imp.group(1)
            kt_imported[_full_imp.rsplit(".", 1)[-1]] = _full_imp
    kt_declared = set(re.findall(r"\b(?:class|interface|object|typealias)\s+([A-Za-z_][A-Za-z0-9_]*)", _clean_kt))

    def _unavoidable_kt_fqcn(qualified: str, full_line: str, match_end: int) -> bool:
        if qualified.startswith(("dagger.Lazy", "android.R.", "android.Manifest.")):
            return True
        tail = full_line[match_end:].lstrip()
        if tail.startswith("::class") and any(
            tok in qualified for tok in ("Experimental", "Preview", "Delicate", "Internal", "Obsolete")
        ):
            return True
        parts = qualified.split(".")
        type_at = next((i for i, part in enumerate(parts) if part[:1].isupper()), None)
        if type_at is None:
            return False
        simple, owner = parts[type_at], ".".join(parts[: type_at + 1])
        return simple in kt_declared or (simple in kt_imported and kt_imported[simple] != owner)

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
                if FQCN_WHITELIST.match(val) or _unavoidable_kt_fqcn(val, line, match.end()):
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

        if not is_test and any(not _in_string_or_comment(line, m_dc.start()) for m_dc in DEAD_CODE_WORKAROUND_PATTERN.finditer(line)):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "DEAD_CODE_WORKAROUND",
                "msg": f"Dead-code edit workaround detected in production code: '{trimmed}'. Cleanly edit or delete the target code block instead of leaving tautological branches or dummy functions.",
            })

        if not is_test:
            for m_pi in PENDING_INTENT_FACTORY_PATTERN.finditer(line):
                if _in_string_or_comment(line, m_pi.start()):
                    continue
                # Extract balanced call argument window across up to 10 lines
                call_window_lines = [line[m_pi.start():]]
                paren_balance = 0
                found_close = False
                for w_idx in range(idx - 1, min(len(lines), idx + 10)):
                    seg = lines[w_idx][m_pi.start():] if w_idx == idx - 1 else lines[w_idx]
                    if w_idx > idx - 1:
                        call_window_lines.append(seg)
                    for c_pos, ch in enumerate(seg):
                        abs_pos = (m_pi.start() + c_pos) if w_idx == idx - 1 else c_pos
                        if _in_string_or_comment(lines[w_idx], abs_pos):
                            continue
                        if ch == "(":
                            paren_balance += 1
                        elif ch == ")":
                            paren_balance -= 1
                            if paren_balance <= 0:
                                found_close = True
                                break
                    if found_close:
                        break
                call_window = "\n".join(call_window_lines)
                if found_close and not PENDING_INTENT_IMMUTABILITY_FLAG_RE.search(call_window):
                    issues.append({
                        "file": str(file_path),
                        "line": idx,
                        "type": "PENDING_INTENT_MISSING_IMMUTABILITY",
                        "msg": "PendingIntent created without explicit FLAG_IMMUTABLE or FLAG_MUTABLE (crashes on Android 12+ API 31+ and risks implicit Intent hijacking). Prefer PendingIntent.FLAG_IMMUTABLE.",
                    })
                    break

        if STATE_CLASS_PATTERN.search(trimmed) and (has_compose_imports or has_compose_function_in_diff):
            has_ann = "@Immutable" in trimmed or "@Stable" in trimmed
            if not has_ann:
                lookback_idx = idx - 2
                annotations = []
                in_kdoc = False
                while lookback_idx >= 0:
                    prev_line = lines[lookback_idx].strip()
                    if in_kdoc:
                        if "/*" in prev_line:
                            in_kdoc = False
                        lookback_idx -= 1
                        continue
                    if prev_line.endswith("*/") and not prev_line.startswith("/*"):
                        in_kdoc = True
                        lookback_idx -= 1
                        continue
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

    uses_hilt = bool(
        re.search(
            r"@Inject\b|\bhiltViewModel\b|\bhiltNavGraphViewModels\b|\bby\s+(?:activityViewModels|viewModels)\b|\bdagger\.hilt\b",
            text,
        )
    )
    if uses_hilt and has_fragment_activity_in_diff and not has_android_entry_point and not is_test:
        issues.append({
            "file": str(file_path),
            "line": 1,
            "type": "MISSING_HILT_ENTRY_POINT",
            "msg": "Fragment / Activity class is missing '@AndroidEntryPoint' for Hilt dependency injection.",
        })

    posix_lower = f"/{posix.lower()}"
    is_ios_source_set = bool(re.search(r"/src/(?:ios|apple|native)[^/]*/", posix_lower))
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
            preview_search_text = text
            stem = file_path.stem
            preview_dirs = [file_path.parent]
            if is_common_main:
                android_parallel = Path(
                    re.sub(r"/src/commonMain(?=/|$)", "/src/androidMain", file_path.parent.as_posix(), flags=re.IGNORECASE)
                )
                if android_parallel != file_path.parent and android_parallel.is_dir():
                    preview_dirs.append(android_parallel)
            for p_dir in preview_dirs:
                for cand_name in (f"{stem}Preview.kt", f"{stem}Previews.kt", "Previews.kt"):
                    sibling = p_dir / cand_name
                    if sibling != file_path and sibling.is_file():
                        try:
                            sib_text = sibling.read_text(encoding="utf-8", errors="replace")
                            if stem in sib_text or cand_name.startswith(stem):
                                preview_search_text = f"{preview_search_text}\n{sib_text}"
                        except (OSError, ValueError):
                            pass
            has_rtl = any(loc in {"ar", "he", "fa", "ur", "iw"} for loc in SUPPORTED_LOCALES)
            has_ltr = any(loc not in {"ar", "he", "fa", "ur", "iw"} for loc in SUPPORTED_LOCALES)
            needs_bidirectional = has_rtl and has_ltr and not is_common_main
            extra = " plus Loading/Empty/Error." if requires_state_previews(file_path.name) else "."
            if needs_bidirectional:
                if not PREVIEW_AR.search(preview_search_text) or not PREVIEW_EN.search(preview_search_text):
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
                if not PREVIEW_EN.search(preview_search_text) and "@Preview" not in preview_search_text:
                    issues.append({
                        "file": str(file_path),
                        "line": 1,
                        "type": "MISSING_COMPOSE_PREVIEW",
                        "msg": f"'{file_path.name}' needs @Preview composable function{extra}",
                    })

    if not is_test:
        line_preserved_clean = _strip_kotlin_comments_preserve_lines(text)
        for catch_line, caught_var in _find_suspend_cancellation_swallows(line_preserved_clean, modified_lines):
            issues.append({
                "file": str(file_path),
                "line": catch_line,
                "type": "SUSPEND_CANCELLATION_SWALLOWED",
                "msg": f"Generic catch({caught_var}: Exception/Throwable) inside suspend function swallows structured concurrency cancellation. Add 'if ({caught_var} is CancellationException) throw {caught_var}' (or currentCoroutineContext().ensureActive()) before handling.",
            })

    clean_fragment_text = re.sub(
        r'("""[\s\S]*?"""|"(?:\\.|[^"\\\r\n])*"|\'(?:\\.|[^\'\\\r\n])*\'|//[^\r\n]*|/\*[\s\S]*?\*/)',
        lambda m: '""' if m.group(0).startswith(('"', "'")) else "",
        text,
    )
    is_fragment = bool(re.search(r"class\s+\w+[^{]*:\s*(?:BaseFragment|Fragment|DialogFragment|BottomSheetDialogFragment)\b", clean_fragment_text))
    if is_fragment and not is_test:
        binding_decl = re.search(r"private\s+var\s+(_binding\w*)\s*:\s*[A-Za-z0-9_]+Binding\?\s*=\s*null", clean_fragment_text)
        if binding_decl:
            var_name = binding_decl.group(1)
            ondestroy_header = re.search(r"override\s+fun\s+onDestroyView\s*\([^)]*\)\s*\{", clean_fragment_text)
            ondestroy_body = ""
            if ondestroy_header:
                depth = 1
                pos = ondestroy_header.end()
                while pos < len(clean_fragment_text) and depth > 0:
                    ch = clean_fragment_text[pos]
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                    pos += 1
                ondestroy_body = clean_fragment_text[ondestroy_header.end():pos - 1] if depth == 0 else clean_fragment_text[ondestroy_header.end():]
            nullified = bool(ondestroy_body) and bool(re.search(rf"\b{re.escape(var_name)}\s*=\s*null\b", ondestroy_body))
            if not nullified:
                issues.append({
                    "file": str(file_path),
                    "line": 1,
                    "type": "VIEWBINDING_MEMORY_LEAK",
                    "msg": f"Fragment ViewBinding memory leak: '{var_name}' is declared but not set to null in onDestroyView(). Set '{var_name} = null' in onDestroyView() to prevent retaining the View hierarchy.",
                })

    issues.extend(
        _lint_a2ui_kotlin_traps(
            file_path,
            text,
            _strip_kotlin_comments_preserve_lines(text),
            lines,
            modified_lines,
            is_test=is_test,
            is_common_main=is_common_main,
        )
    )
    issues.extend(_find_unused_intra_file_code(file_path, text, modified_lines, is_test=is_test))
    return issues

A2UI_IMPORT_OR_SYMBOL_RE = re.compile(
    r"\b(?:androidx\.a2ui|androidx\.compose\.material3\.a2ui|A2uiMessageProcessor|A2uiSurface|BasicCatalog|processInput)\b"
)
A2UI_PROCESS_INPUT_CALL_RE = re.compile(r"\bprocessInput\s*\(")
A2UI_OUTBOUND_EVENTS_RE = re.compile(r"\boutboundEvents\b")
A2UI_BASIC_CATALOG_URI_V1 = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"
A2UI_CATALOG_DECL_RE = re.compile(
    r'\bCatalog\s*\(\s*(?:id\s*=\s*|catalogId\s*=\s*)?"([^"]*)"'
)
A2UI_CREATE_SURFACE_CATALOG_KT_RE = re.compile(
    r'\bcreateSurface\b[\s\S]{0,240}?\bcatalogId\s*=\s*"([^"]*)"'
)
A2UI_CREATE_SURFACE_CATALOG_JSON_RE = re.compile(
    r'"createSurface"\s*:\s*\{[\s\S]{0,300}?"catalogId"\s*:\s*"([^"]*)"'
)


def _lint_a2ui_kotlin_traps(
    file_path: Path,
    text: str,
    clean_text: str,
    lines: list[str],
    modified_lines: set[int] | None,
    *,
    is_test: bool,
    is_common_main: bool,
) -> list[dict]:
    """Detect the 3 real-world Jetpack Compose A2UI 1.0 traps (+ KMP commonMain Android-only AAR leak)."""
    issues: list[dict] = []
    if is_test or not A2UI_IMPORT_OR_SYMBOL_RE.search(text):
        return issues

    def _line_in_scope(ln: int) -> bool:
        return modified_lines is None or ln in modified_lines

    # KMP commonMain guard: official androidx.a2ui / material3-a2ui artifacts are Android-only AARs
    if is_common_main:
        for idx, line in enumerate(lines, 1):
            if _line_in_scope(idx) and re.search(r"^\s*import\s+androidx\.(?:a2ui|compose\.material3\.a2ui)\b", line):
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "A2UI_ANDROID_ONLY_IN_COMMON_MAIN",
                    "msg": (
                        "Official 'androidx.a2ui' / 'material3-a2ui' publishes Android-only AARs without klib/iOS targets. "
                        "Keep agent logic in commonMain and move A2UI Compose rendering to androidMain (or use a KMP bridge)."
                    ),
                })
                break

    # Trap 1: Silent White Box — `processInput(...)` swallows `A2uiException` into `outboundEvents`
    has_process_input = False
    process_input_line = 1
    for idx, clean_line in enumerate(clean_text.splitlines(), 1):
        if A2UI_PROCESS_INPUT_CALL_RE.search(clean_line) and _line_in_scope(idx):
            has_process_input = True
            process_input_line = idx
            break
    if has_process_input and ("androidx.a2ui" in text or "A2uiMessageProcessor" in text):
        combined_scope_text = text
        try:
            for sib in file_path.parent.glob("*.kt"):
                if sib != file_path and sib.is_file():
                    combined_scope_text += "\n" + sib.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        if not A2UI_OUTBOUND_EVENTS_RE.search(combined_scope_text):
            issues.append({
                "file": str(file_path),
                "line": process_input_line,
                "type": "A2UI_UNCOLLECTED_OUTBOUND_EVENTS",
                "msg": (
                    "A2UI silent white-screen hazard: 'processInput(...)' swallows A2uiException and emits errors "
                    "only on 'outboundEvents'. Collect or expose 'processor.outboundEvents' so malformed agent JSON "
                    "is handled visibly instead of rendering a blank white box."
                ),
            })

    # Trap 3: Literal `catalogId` mismatch — `createSurface.catalogId` must match registered Catalog ID verbatim
    registered_ids: set[str] = {m.group(1) for m in A2UI_CATALOG_DECL_RE.finditer(text) if m.group(1)}
    if re.search(r"\bBasicCatalog\b", text):
        registered_ids.add(A2UI_BASIC_CATALOG_URI_V1)
    try:
        for sib in file_path.parent.glob("*.kt"):
            if sib != file_path and sib.is_file():
                sib_txt = sib.read_text(encoding="utf-8", errors="replace")
                registered_ids.update(m.group(1) for m in A2UI_CATALOG_DECL_RE.finditer(sib_txt) if m.group(1))
                if re.search(r"\bBasicCatalog\b", sib_txt):
                    registered_ids.add(A2UI_BASIC_CATALOG_URI_V1)
    except OSError:
        pass

    surface_matches = list(A2UI_CREATE_SURFACE_CATALOG_KT_RE.finditer(text)) + list(
        A2UI_CREATE_SURFACE_CATALOG_JSON_RE.finditer(text)
    )
    for m_surf in surface_matches:
        surf_cid = m_surf.group(1)
        line_no = text.count("\n", 0, m_surf.start()) + 1
        if not _line_in_scope(line_no):
            continue
        if not surf_cid or surf_cid != surf_cid.strip():
            issues.append({
                "file": str(file_path),
                "line": line_no,
                "type": "A2UI_CATALOG_ID_MISMATCH",
                "msg": f"A2UI createSurface has blank or whitespace-padded catalogId '{surf_cid}'; surface will silently fail to render.",
            })
        elif registered_ids and surf_cid not in registered_ids:
            issues.append({
                "file": str(file_path),
                "line": line_no,
                "type": "A2UI_CATALOG_ID_MISMATCH",
                "msg": (
                    f"A2UI silent blank-surface hazard: createSurface catalogId '{surf_cid}' does not match "
                    f"registered catalog ID(s) {sorted(registered_ids)} verbatim (A2UI drops mismatched surfaces without throwing)."
                ),
            })

    return issues


SWIFT_STUB_PATTERN = re.compile(
    r'\bfatalError\s*\(\s*"(?:TODO|Not\s+implemented|unimplemented|FIXME)[^"]*"\s*\)',
    re.IGNORECASE,
)


def lint_swift_file(file_path: Path, modified_lines: set[int] | None = None) -> list[dict]:
    """Fast preflight security and hygiene checks for KMM iOS Swift files."""
    from _modules import is_kmp_or_android_test_path

    issues: list[dict] = []
    posix = file_path.as_posix()
    is_test = is_kmp_or_android_test_path(posix)
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return [{"file": str(file_path), "line": 1, "type": "IO_ERROR", "msg": str(e)}]

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
            if trimmed.count('"""') % 2 != 0:
                in_triple_string = True
            continue
        if modified_lines is not None and idx not in modified_lines:
            continue

        if BIDI_TROJAN_PATTERN.search(line):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "TROJAN_SOURCE_BIDI",
                "msg": f"Invisible Bidi control / Trojan Source character detected in code: '{trimmed}'. Invisible directional formatting characters are prohibited (CVE-2021-42574).",
            })

        if trimmed.startswith("//"):
            if DIAGNOSTIC_PROBE_PATTERN.search(trimmed):
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "STRAY_DIAGNOSTIC_PROBE",
                    "msg": f"Stray diagnostic probe detected: '{trimmed}'. Remove temporary probes before review/delivery.",
                })
            continue

        # Strip trailing `// ...` comment outside string literals so commented-out URLs or TODO notes are not flagged
        code_only_chars: list[str] = []
        in_str = False
        ci = 0
        while ci < len(line):
            ch = line[ci]
            if in_str:
                code_only_chars.append(ch)
                if ch == "\\" and ci + 1 < len(line):
                    ci += 1
                    code_only_chars.append(line[ci])
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                    code_only_chars.append(ch)
                elif line[ci:ci + 2] == "//":
                    break
                else:
                    code_only_chars.append(ch)
            ci += 1
        code_line = "".join(code_only_chars)

        if not is_test:
            for sec_name, sec_re in SECRET_PATTERNS:
                if sec_re.search(code_line):
                    issues.append({
                        "file": str(file_path),
                        "line": idx,
                        "type": "HARDCODED_SECRET",
                        "msg": f"Hardcoded credential detected ({sec_name}). Store credentials in secure build configuration or Keychain.",
                    })
                    break

            for m_url in CLEARTEXT_URL_PATTERN.finditer(code_line):
                host = m_url.group(1).lower().split(":")[0]
                if host not in CLEARTEXT_WHITELIST_HOSTS and not any(host.endswith("." + wh) for wh in CLEARTEXT_WHITELIST_HOSTS):
                    issues.append({
                        "file": str(file_path),
                        "line": idx,
                        "type": "INSECURE_CLEARTEXT_TRAFFIC",
                        "msg": f"Insecure cleartext HTTP URL detected: '{m_url.group(0)}'. Use HTTPS to prevent MITM attacks.",
                    })
                    break

            if SWIFT_STUB_PATTERN.search(code_line):
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "UNIMPLEMENTED_STUB",
                    "msg": f"Unimplemented stub found in production Swift code: '{trimmed}'. Provide complete implementation.",
                })

        if DIAGNOSTIC_PROBE_PATTERN.search(trimmed):
            issues.append({
                "file": str(file_path),
                "line": idx,
                "type": "STRAY_DIAGNOSTIC_PROBE",
                "msg": f"Stray diagnostic probe detected: '{trimmed}'. Remove temporary probes before review/delivery.",
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


_STABLE_COMPOSE_BOM_RE = re.compile(
    r'(?:compose-bom|composeBom)\s*[:=]\s*"?(?:androidx\.compose:compose-bom:)?(202[3-5]\.[0-9]{2}\.[0-9]{2}|2026\.0[1-8]\.[0-9]{2})"?',
    re.IGNORECASE,
)
_OLD_COMPOSE_VER_RE = re.compile(
    r'(?:compose(?:Ui|Runtime|Foundation)?|androidx\.compose\.[a-z0-9_.]+)\s*[:=]\s*"?(1\.(?:[0-9]|1[0-2])\.[0-9]+(?:-[a-z0-9.]+)?)"?',
    re.IGNORECASE,
)
_OLD_MATERIAL3_VER_RE = re.compile(
    r'(?:material3|androidx\.compose\.material3:material3)\s*[:=]\s*"?(1\.[0-4]\.[0-9]+(?:-[a-z0-9.]+)?)"?',
    re.IGNORECASE,
)
_ALPHA_COMPOSE_OVERRIDE_RE = re.compile(r"1\.(?:1[3-9]|[2-9][0-9])\.[0-9]+|1\.5\.0-alpha2[89]|1\.[5-9]\.[0-9]+")


def lint_build_script(file_path: Path) -> list[dict]:
    issues: list[dict] = []
    try:
        txt = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return issues
    lines = txt.splitlines()
    is_toml = file_path.name.endswith(".toml")
    if not is_toml:
        for idx, line in enumerate(lines, start=1):
            if (".delete()" in line or "delete(" in line) and any(p in line for p in ("src/", "res/", "layout", "values")):
                issues.append({
                    "file": str(file_path),
                    "line": idx,
                    "type": "UNAUTHORIZED_BUILD_SCRIPT_MUTATION",
                    "msg": f"Unauthorized file deletion in Gradle build script at line {idx}: '{line.strip()}'. Do not use Gradle tasks to delete project assets or bypass verification.",
                })

    # Trap 2: `material3-a2ui:1.0.0-alpha*` POM conflict with stable Compose BOM (<=1.12.x / Material3 <=1.4.x)
    a2ui_m3_line = next(
        (idx for idx, line in enumerate(lines, start=1) if "material3-a2ui" in line and not line.lstrip().startswith(("#", "//"))),
        0,
    )
    if a2ui_m3_line:
        combined_versions_text = txt
        toml_cand = REPO / "gradle" / "libs.versions.toml"
        if toml_cand != file_path and toml_cand.is_file():
            try:
                combined_versions_text += "\n" + toml_cand.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        has_old_bom_or_compose = bool(
            _STABLE_COMPOSE_BOM_RE.search(combined_versions_text)
            or _OLD_COMPOSE_VER_RE.search(combined_versions_text)
            or _OLD_MATERIAL3_VER_RE.search(combined_versions_text)
        )
        has_alpha_alignment = bool(_ALPHA_COMPOSE_OVERRIDE_RE.search(txt))
        if has_old_bom_or_compose and not has_alpha_alignment:
            issues.append({
                "file": str(file_path),
                "line": a2ui_m3_line,
                "type": "A2UI_COMPOSE_BOM_CONFLICT",
                "msg": (
                    "A2UI Compose BOM conflict: 'material3-a2ui:1.0.0-alpha*' requires androidx.compose 1.13.0-alpha03+ "
                    "and strictly constrains material3 to [1.5.0-alpha28], which fails resolution against stable Compose BOM (<=1.12.x). "
                    "Pin compatible Compose 1.13.0-alpha / Material3 1.5.0-alpha versions or isolate A2UI in a dedicated module."
                ),
            })

    # KMP commonMain build-script guard for Android-only `androidx.a2ui` / `material3-a2ui`
    if not is_toml and ("commonMain" in txt) and ("androidx.a2ui" in txt or "material3-a2ui" in txt):
        for m_cm in re.finditer(r"commonMain\s*(?:\.dependencies)?\s*\{", txt):
            extracted = _extract_balanced_brace_body(txt, m_cm.end() - 1)
            if extracted and ("androidx.a2ui" in extracted[0] or "material3-a2ui" in extracted[0]):
                cm_line = txt.count("\n", 0, m_cm.start()) + 1
                issues.append({
                    "file": str(file_path),
                    "line": cm_line,
                    "type": "A2UI_ANDROID_ONLY_IN_COMMON_MAIN",
                    "msg": (
                        "Official 'androidx.a2ui' / 'material3-a2ui' artifacts are Android-only AARs and cannot resolve in KMP commonMain. "
                        "Move them to androidMain.dependencies."
                    ),
                })
                break

    return issues


_ARCH_KDOC_STEM_RE = re.compile(
    r"(?:Repo|Repository|RepositoryImpl|UseCase|Interactor|ViewModel|DataSource|ApiService|Service|Screen|Router|Manager)$",
    re.IGNORECASE,
)
_ARCH_KDOC_PATH_RE = re.compile(
    r"/(?:repository|repositories|usecase|usecases|domain|viewmodel|viewmodels|datasource|remote)/",
    re.IGNORECASE,
)
_KDOC_CLASS_DECL_RE = re.compile(
    r"^\s*(?:@[A-Za-z0-9_.]+(?:\([^)]*\))?\s+)*"
    r"(?!(?:[^({\n]*\b(?:private|protected|companion)\b))"
    r"(?:(?:public|internal|open|abstract|sealed|data|value|actual|expect)\s+)*"
    r"(class|interface)\s+([A-Za-z_][A-Za-z0-9_]*)\b"
)
_KDOC_FUN_DECL_RE = re.compile(
    r"^\s*(?:@[A-Za-z0-9_.]+(?:\([^)]*\))?\s+)*"
    r"(?!(?:[^({\n]*\b(?:private|protected|override)\b))"
    r"(?:(?:public|internal|open|abstract|suspend|operator|inline|actual|expect)\s+)*"
    r"fun\s+(?:<[^>]+>\s*)?(?:[A-Za-z0-9_.<>?]+\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\("
)


def _is_architectural_kdoc_surface(file_path: Path) -> bool:
    from _modules import is_kmp_or_android_test_path

    posix = file_path.as_posix()
    if is_kmp_or_android_test_path(posix):
        return False
    stem = file_path.stem
    if stem.endswith(("Preview", "Previews", "Module", "Modules")):
        return False
    return bool(_ARCH_KDOC_STEM_RE.search(stem) or _ARCH_KDOC_PATH_RE.search(posix))


def _has_preceding_kdoc_or_preview(lines: list[str], decl_line_idx_0: int) -> tuple[bool, bool]:
    """Return `(has_kdoc, is_preview)` by walking upward above `decl_line_idx_0` past annotations."""
    i = decl_line_idx_0 - 1
    blank_budget = 1
    in_kdoc_block = False
    is_preview = "@Preview" in lines[decl_line_idx_0] or "Preview" in lines[decl_line_idx_0]
    paren_depth = 0
    while i >= 0:
        s = lines[i].strip()
        if in_kdoc_block:
            if "/**" in s:
                return True, is_preview
            if s.startswith("/*") and not s.startswith("/**"):
                in_kdoc_block = False
            i -= 1
            continue
        if not s:
            if blank_budget > 0:
                blank_budget -= 1
                i -= 1
                continue
            break
        if s.startswith("/**") and s.endswith("*/"):
            return True, is_preview
        if s.endswith("*/") and not s.startswith("/*"):
            in_kdoc_block = True
            i -= 1
            continue
        if s.startswith("//"):
            i -= 1
            continue
        if s.startswith("@"):
            if "Preview" in s:
                is_preview = True
            i -= 1
            continue
        # Handle multi-line annotation arguments directly above declaration (e.g. `@OptIn(\n Foo::class\n)`)
        if (s.endswith(")") and s.count(")") > s.count("(")) or paren_depth > 0:
            paren_depth += s.count(")") - s.count("(")
            if "Preview" in s:
                is_preview = True
            i -= 1
            if paren_depth <= 0:
                paren_depth = 0
            continue
        break
    return False, is_preview


def find_missing_architectural_kdoc(
    file_path: Path,
    text: str,
    modified_lines: set[int] | None,
) -> list[dict]:
    """Find newly added public/internal classes, interfaces, and contract functions missing `/** ... */` KDoc."""
    if not _is_architectural_kdoc_surface(file_path):
        return []
    if modified_lines is not None and len(modified_lines) == 0:
        return []

    from _source_text import mask_comments_and_strings

    raw_lines = text.splitlines()
    clean_lines = _strip_kotlin_comments_preserve_lines(text).splitlines()
    structural_lines = mask_comments_and_strings(text).splitlines()
    advisories: list[dict] = []
    brace_depth = 0
    paren_depth = 0

    for idx_0, c_line in enumerate(clean_lines):
        s_line = structural_lines[idx_0] if idx_0 < len(structural_lines) else c_line
        ln_1 = idx_0 + 1
        in_mod = modified_lines is None or ln_1 in modified_lines
        # Only check top-level declarations (brace_depth == 0) or direct class/interface members (brace_depth == 1)
        if in_mod and paren_depth == 0 and brace_depth in (0, 1):
            m_cls = _KDOC_CLASS_DECL_RE.match(c_line)
            if m_cls and brace_depth == 0:
                kind_kw, sym_name = m_cls.group(1), m_cls.group(2)
                if not sym_name.endswith(("UiState", "State", "Event", "Effect", "Action")):
                    has_kdoc, is_prev = _has_preceding_kdoc_or_preview(raw_lines, idx_0)
                    if not has_kdoc and not is_prev:
                        advisories.append({
                            "file": str(file_path),
                            "line": ln_1,
                            "type": "MISSING_ARCHITECTURAL_KDOC",
                            "msg": (
                                f"Newly added public/internal {kind_kw} '{sym_name}' has no KDoc (/** ... */). "
                                "Add concise English KDoc documenting its architectural responsibility and contract."
                            ),
                        })
            else:
                m_fun = _KDOC_FUN_DECL_RE.match(c_line)
                if m_fun:
                    fn_name = m_fun.group(1)
                    if not fn_name.endswith(("Preview", "Previews")):
                        has_kdoc, is_prev = _has_preceding_kdoc_or_preview(raw_lines, idx_0)
                        if not has_kdoc and not is_prev:
                            advisories.append({
                                "file": str(file_path),
                                "line": ln_1,
                                "type": "MISSING_ARCHITECTURAL_KDOC",
                                "msg": (
                                    f"Newly added public/internal contract 'fun {fn_name}(...)' has no KDoc (/** ... */). "
                                    "Add concise English KDoc documenting responsibility, @param, and @return."
                                ),
                            })
        brace_depth += s_line.count("{") - s_line.count("}")
        if brace_depth < 0:
            brace_depth = 0
        paren_depth += s_line.count("(") - s_line.count(")")
        if paren_depth < 0:
            paren_depth = 0
    return advisories


_FRAMEWORK_ENTRY_ANNOTATIONS_RE = re.compile(
    r"@(?:Preview|DualLocalePreviews|MultiLocalePreviews|PreviewLightDark|HiltAndroidApp|AndroidEntryPoint|"
    r"HiltViewModel|Module|InstallIn|EntryPoint|Provides|Binds|IntoSet|IntoMap|Inject|Entity|Dao|Database|"
    r"TypeConverter|Query|Insert|Update|Delete|Upsert|GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|HTTP|"
    r"Serializable|Parcelize|Keep|BindingAdapter|JavascriptInterface|Subscribe|WorkerThread)\b"
)
_FRAMEWORK_ENTRY_SUFFIXES = (
    "Activity", "Fragment", "Service", "Receiver", "Provider", "Application",
    "Worker", "ViewModel", "Module", "Modules", "Preview", "Previews", "Initializer",
)
_PUB_TYPE_DECL_RE = re.compile(
    r"^\s*(?:@[A-Za-z0-9_.]+(?:\([^)]*\))?\s+)*"
    r"(?!(?:[^({\n]*\b(?:private|protected|companion)\b))"
    r"(?:(?:public|internal|open|abstract|sealed|data|enum|value|actual|expect)\s+)*"
    r"(class|interface|object)\s+([A-Za-z_][A-Za-z0-9_]*)\b"
)
_PUB_FUN_DECL_RE = re.compile(
    r"^\s*(?:@[A-Za-z0-9_.]+(?:\([^)]*\))?\s+)*"
    r"(?!(?:[^({\n]*\b(?:private|protected|override|abstract|operator|external|expect)\b))"
    r"(?:(?:public|internal|open|suspend|inline|tailrec|infix|actual)\s+)*"
    r"fun\s+(?:<[^>]+>\s*)?(?:[A-Za-z0-9_.<>?]+\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
_IDENT_TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")


def find_unreferenced_new_declarations(
    repo: Path,
    target_files: list[Path],
    modified_lines_map: dict[Path, set[int] | None],
) -> list[dict]:
    """Detect newly added non-private classes/objects/functions that have 0 references across the entire repository."""
    from _modules import SKIP_PARTS, is_kmp_or_android_test_path

    candidates: list[dict] = []
    file_texts: dict[Path, str] = {}

    for path in target_files:
        posix = path.as_posix()
        if is_kmp_or_android_test_path(posix):
            continue
        mod_set = modified_lines_map.get(path)
        if mod_set is not None and len(mod_set) == 0:
            continue
        try:
            raw_txt = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_texts[path] = raw_txt
        from _source_text import mask_comments_and_strings
        raw_lines = raw_txt.splitlines()
        tmpl_lines = _strip_kotlin_comments_keep_templates(raw_txt).splitlines()
        struct_lines = mask_comments_and_strings(raw_txt).splitlines()
        brace_depth = 0
        paren_depth = 0
        for idx_0, c_line in enumerate(tmpl_lines):
            s_line = struct_lines[idx_0] if idx_0 < len(struct_lines) else c_line
            ln_1 = idx_0 + 1
            in_mod = mod_set is None or ln_1 in mod_set
            if in_mod and paren_depth == 0 and brace_depth in (0, 1):
                ann_win = "\n".join(raw_lines[max(0, idx_0 - 8):idx_0 + 1])
                if not (_FRAMEWORK_ENTRY_ANNOTATIONS_RE.search(ann_win) or _SUPPRESS_UNUSED_RE.search(ann_win)):
                    m_t = _PUB_TYPE_DECL_RE.match(c_line)
                    if m_t and brace_depth == 0:
                        kind_kw, sym = m_t.group(1), m_t.group(2)
                        if len(sym) >= 3 and not sym.endswith(_FRAMEWORK_ENTRY_SUFFIXES):
                            candidates.append({"file": path, "line": ln_1, "kind": kind_kw, "name": sym})
                    else:
                        m_f = _PUB_FUN_DECL_RE.match(c_line)
                        if m_f:
                            fn = m_f.group(1)
                            if (
                                len(fn) >= 3
                                and not fn.endswith(("Preview", "Previews"))
                                and fn not in {
                                    "main", "invoke", "equals", "hashCode", "toString", "copy",
                                    "describeContents", "writeToParcel", "createFromParcel", "newArray",
                                }
                            ):
                                candidates.append({"file": path, "line": ln_1, "kind": "fun", "name": fn})
            brace_depth += s_line.count("{") - s_line.count("}")
            if brace_depth < 0:
                brace_depth = 0
            paren_depth += s_line.count("(") - s_line.count(")")
            if paren_depth < 0:
                paren_depth = 0

    if not candidates:
        return []

    from _source_text import mask_comments_and_strings
    cand_names = {c["name"] for c in candidates}
    skip = set(SKIP_PARTS)
    all_source_files: list[Path] = []
    for ext in ("*.kt", "*.java", "*.xml", "*.swift"):
        for p in repo_glob(repo, f"**/{ext}"):
            if not any(part in p.parts for part in skip) and p.is_file():
                all_source_files.append(p)
    if len(all_source_files) < 2:
        return []

    seen_elsewhere: set[str] = set()
    cand_files = {c["file"].resolve() for c in candidates}
    cand_file_tokens: dict[Path, set[str]] = {}
    for sp in all_source_files:
        sp_res = sp.resolve()
        try:
            stxt = sp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if sp.suffix == ".kt":
            stxt = _strip_kotlin_comments_keep_templates(stxt)
        elif sp.suffix == ".swift":
            stxt = mask_comments_and_strings(stxt)
        matched_here = cand_names & set(_IDENT_TOKEN_RE.findall(stxt))
        if sp_res in cand_files:
            cand_file_tokens[sp_res] = matched_here
            continue
        if matched_here:
            seen_elsewhere.update(matched_here)

    findings: list[dict] = []
    for cand in candidates:
        sym = cand["name"]
        c_path: Path = cand["file"]
        c_res = c_path.resolve()
        if sym in seen_elsewhere or any(sym in toks for f_res, toks in cand_file_tokens.items() if f_res != c_res):
            continue
        raw_c = file_texts.get(c_path, "")
        tmpl_c_lines = _strip_kotlin_comments_keep_templates(raw_c).splitlines()
        decl_idx_0 = cand["line"] - 1
        if 0 <= decl_idx_0 < len(tmpl_c_lines):
            # Replace only the declaration occurrence on `decl_idx_0`
            tmpl_c_lines[decl_idx_0] = re.sub(rf"\b{re.escape(sym)}\b", " ", tmpl_c_lines[decl_idx_0], count=1)
        rest_same_file = "\n".join(tmpl_c_lines)
        if re.search(rf"(?:\b{re.escape(sym)}\b|`{re.escape(sym)}`)", rest_same_file):
            continue
        findings.append({
            "file": str(c_path),
            "line": cand["line"],
            "symbol": sym,
            "kind": cand["kind"],
            "type": "UNUSED_DECLARATION",
            "msg": (
                f"Newly added {cand['kind']} '{sym}' has 0 callers/references across the entire project. "
                "Wire it into its caller/test or remove dead code."
            ),
        })
    return findings


def main(argv: list[str] | None = None, *, repo_override: Path | None = None) -> int:
    global REPO
    _saved_repo = REPO
    if repo_override is not None:
        REPO = repo_override.resolve()
    try:
        return _main_impl(argv)
    finally:
        REPO = _saved_repo


def _main_impl(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fast Kotlin lint for this app")
    parser.add_argument("--all", action="store_true", help="Scan all Kotlin files under app/src/main")
    parser.add_argument("--strict-kdoc", action="store_true", help="Treat missing architectural KDoc on newly added contracts as blocking lint errors")
    parser.add_argument("--strict-unused", action="store_true", help="Treat unreferenced newly added public/internal classes and functions as blocking lint errors")
    parser.add_argument("files", nargs="*", help="Optional explicit file path(s) to scan")
    args = parser.parse_args(argv)

    if args.files:
        cwd_root = Path.cwd().resolve()
        explicit_paths: list[Path] = []
        for raw_f in args.files:
            cand = Path(raw_f)
            if cand.is_absolute():
                resolved_p = cand.resolve()
            elif (cwd_root / cand).is_file():
                resolved_p = (cwd_root / cand).resolve()
            else:
                resolved_p = (REPO / cand).resolve()
            if resolved_p.is_file() and resolved_p not in explicit_paths:
                explicit_paths.append(resolved_p)
        eff_repo = REPO
        if explicit_paths:
            probe_f = explicit_paths[0]
            if (cwd_root / ".git").exists() and probe_f.is_relative_to(cwd_root):
                eff_repo = cwd_root
            else:
                for anc in probe_f.parents:
                    if (anc / ".git").exists():
                        eff_repo = anc
                        break
        changed = explicit_paths
        target_files = [p for p in changed if p.suffix == ".kt"]
        java_files = [p for p in changed if p.suffix == ".java"]
        swift_files = [p for p in changed if p.suffix == ".swift"]
        if args.all:
            modified_lines_map = {p: None for p in target_files}
            java_lines_map = {p: None for p in java_files}
            swift_lines_map = {p: None for p in swift_files}
        else:
            from _repo_files import active_task_scope, diff_modified_lines_against_baseline
            _, baseline_dir = active_task_scope(eff_repo)
            modified_lines_map = get_modified_lines_map(eff_repo, target_files) if (eff_repo / ".git").exists() else {p: None for p in target_files}
            java_lines_map = get_modified_lines_map(eff_repo, java_files) if (java_files and (eff_repo / ".git").exists()) else {p: None for p in java_files}
            swift_lines_map = get_modified_lines_map(eff_repo, swift_files) if (swift_files and (eff_repo / ".git").exists()) else {p: None for p in swift_files}
            if baseline_dir is not None:
                for p in target_files:
                    try:
                        rel = p.resolve().relative_to(eff_repo.resolve()).as_posix()
                    except ValueError:
                        continue
                    b_file = baseline_dir / rel
                    if b_file.is_file() and p.is_file():
                        modified_lines_map[p] = diff_modified_lines_against_baseline(b_file, p)
    elif args.all:
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
        swift_roots = list(roots)
        for ios_dir in ("iosApp", "ios", "appleApp"):
            cand = REPO / ios_dir
            if cand.is_dir() and cand not in swift_roots:
                swift_roots.append(cand)
        swift_files = [
            p for root in swift_roots for p in repo_glob(root, "**/*.swift") if not any(x in p.parts for x in skip)
        ]
        swift_lines_map = {p: None for p in swift_files}
        changed = changed_paths()
    else:
        from _repo_files import active_task_scope, diff_modified_lines_against_baseline
        scoped_paths, baseline_dir = active_task_scope(REPO)
        changed = scoped_paths if scoped_paths is not None else changed_paths()
        target_files = [p for p in changed if p.suffix == ".kt"]
        modified_lines_map = get_modified_lines_map(REPO, target_files)
        java_files = [p for p in changed if p.suffix == ".java"]
        java_lines_map = get_modified_lines_map(REPO, java_files) if java_files else {}
        swift_files = [p for p in changed if p.suffix == ".swift"]
        swift_lines_map = get_modified_lines_map(REPO, swift_files) if swift_files else {}
        if baseline_dir is not None:
            for p in target_files:
                try:
                    rel = p.resolve().relative_to(REPO.resolve()).as_posix()
                except ValueError:
                    continue
                b_file = baseline_dir / rel
                if b_file.is_file() and p.is_file():
                    modified_lines_map[p] = diff_modified_lines_against_baseline(b_file, p)
            for p in java_files:
                try:
                    rel = p.resolve().relative_to(REPO.resolve()).as_posix()
                except ValueError:
                    continue
                b_file = baseline_dir / rel
                if b_file.is_file() and p.is_file():
                    java_lines_map[p] = diff_modified_lines_against_baseline(b_file, p)
            for p in swift_files:
                try:
                    rel = p.resolve().relative_to(REPO.resolve()).as_posix()
                except ValueError:
                    continue
                b_file = baseline_dir / rel
                if b_file.is_file() and p.is_file():
                    swift_lines_map[p] = diff_modified_lines_against_baseline(b_file, p)

    build_files = [
        p for p in changed
        if p.name in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "libs.versions.toml")
        or p.name.endswith(".versions.toml")
    ]

    if not target_files and not build_files and not java_files and not swift_files:
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
    if swift_files:
        print(f"[*] Fast Swift Lint: Scanning {len(swift_files)} Swift file(s) ({mode_label})...")
    all_issues = []
    kdoc_advisories = []
    unused_advisories = []
    strict_kdoc = bool(args.strict_kdoc or os.environ.get("HARNESS_STRICT_KDOC") == "1")
    strict_unused = bool(args.strict_unused or os.environ.get("HARNESS_STRICT_UNUSED") == "1")
    for path in target_files:
        mod_set = modified_lines_map.get(path)
        all_issues.extend(lint_file(path, modified_lines=mod_set))
        if strict_kdoc or (mod_set is not None and len(mod_set) > 0):
            try:
                kt_raw = path.read_text(encoding="utf-8", errors="replace")
                found_kdoc = find_missing_architectural_kdoc(path, kt_raw, mod_set)
                if strict_kdoc:
                    all_issues.extend(found_kdoc)
                else:
                    kdoc_advisories.extend(found_kdoc)
            except OSError:
                pass
    if target_files and not args.all:
        eff_scan_repo = eff_repo if args.files else REPO
        found_unused_decls = find_unreferenced_new_declarations(eff_scan_repo, target_files, modified_lines_map)
        if strict_unused:
            all_issues.extend(found_unused_decls)
        else:
            unused_advisories.extend(found_unused_decls)
    for path in java_files:
        all_issues.extend(lint_java_file(path, modified_lines=java_lines_map.get(path)))
    for path in swift_files:
        all_issues.extend(lint_swift_file(path, modified_lines=swift_lines_map.get(path)))
    for bf in build_files:
        all_issues.extend(lint_build_script(bf))

    def _safe_rel(raw_path: str) -> str:
        try:
            return os.path.relpath(raw_path, REPO)
        except ValueError:
            return str(raw_path)

    for adv in kdoc_advisories[:20]:
        rel_adv = _safe_rel(adv["file"]).replace("\\", "/")
        print(f"[KDOC-ADVISORY] {rel_adv}:{adv['line']} -> {adv['msg']}")
    for u_adv in unused_advisories[:20]:
        rel_u = _safe_rel(u_adv["file"]).replace("\\", "/")
        print(f"[UNUSED-ADVISORY] {rel_u}:{u_adv['line']} -> {u_adv['msg']}")

    if not all_issues:
        print("[SUCCESS] Fast Kotlin Lint passed! 0 syntax/architectural violations detected.")
        return 0

    print(f"\nFound {len(all_issues)} lint issue(s):")
    for i, iss in enumerate(all_issues, 1):
        rel_path = _safe_rel(iss["file"])
        print(f"  {i}. [{iss['type']}] {rel_path}:{iss['line']}")
        print(f"     -> {iss['msg']}")

    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
