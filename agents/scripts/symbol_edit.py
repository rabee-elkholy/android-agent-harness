"""MIT-compatible, pure-stdlib semantic symbol outline, read, and AST-brace body surgery.

Provides `harness.py symbol <outline|read|replace-body|insert-after>` for Kotlin (.kt),
Java (.java), and Swift (.swift) source files so agents and `harness-worker-agent` can
inspect or replace a single function/type body in large files (>350 lines) without
loading hundreds of surrounding lines into context or failing fragile text matches.

All mutating operations enforce `mutation_guard.file_mutation_allowed` (and
`delegation_policy.worker_write_allowed` when invoked by `harness-worker-agent`),
optimistic `expected_sha256` verification, and code brace-balance validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _vnext_common import ValidationError, atomic_write_bytes, sha256_bytes  # noqa: E402

SUPPORTED_SUFFIXES = frozenset({".kt", ".java", ".swift"})
MAX_SYMBOL_FILE_BYTES = 2_500_000

_ANNOTATIONS = r"(?:@[\w.]+(?:\([^()]*\))?\s+)*"
_KT_MODS = (
    r"(?:(?:public|private|internal|protected|override|open|abstract|final|sealed|data|enum|inner|"
    r"annotation|value|inline|noinline|crossinline|suspend|operator|infix|tailrec|external|const|"
    r"lateinit|expect|actual|companion)\s+)*"
)
_KT_DECL_RE = re.compile(
    r"^\s*" + _ANNOTATIONS + _KT_MODS
    + r"(?P<kind>companion\s+object|class|interface|object|fun|val|var|typealias)\b"
    + r"\s*(?:<[^>]*>\s*)?(?:[\w.<>?, *]+?\.)?(?P<name>`[^`]+`|\w+)?"
)
_JAVA_MODS = r"(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|strictfp)\s+)*"
_JAVA_TYPE_RE = re.compile(
    r"^\s*" + _ANNOTATIONS + _JAVA_MODS + r"(?P<kind>class|interface|enum|record|@interface)\s+(?P<name>\w+)"
)
_JAVA_METHOD_RE = re.compile(
    r"^\s*" + _ANNOTATIONS + r"(?:(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)+"
    r"(?:<[^>]*>\s*)?[\w.<>\[\]?, ]+?\s+(?P<name>\w+)\s*\("
)
_SWIFT_MODS = (
    r"(?:(?:public|private|fileprivate|internal|open|final|override|static|class|mutating|nonmutating|"
    r"convenience|required|lazy|weak|unowned|indirect|nonisolated|isolated|async)\s+)*"
)
_SWIFT_DECL_RE = re.compile(
    r"^\s*" + _ANNOTATIONS + _SWIFT_MODS
    + r"(?P<kind>actor|class|struct|enum|protocol|extension|func|init)\b"
    + r"(?:\s+(?P<name>`[^`]+`|[\w.]+))?"
)


def scrub_comments_and_strings(lines: list[str]) -> list[str]:
    """Blank string literals (including triple-quoted multiline strings) and comments line-by-line."""
    out: list[str] = []
    in_block_comment = 0
    in_triple_string = False

    for raw in lines:
        buf: list[str] = []
        i = 0
        n = len(raw)
        while i < n:
            if in_triple_string:
                end_idx = raw.find('"""', i)
                if end_idx < 0:
                    buf.append(" " * (n - i))
                    i = n
                else:
                    buf.append(" " * (end_idx - i) + '"""')
                    i = end_idx + 3
                    in_triple_string = False
                continue

            if in_block_comment > 0:
                c_open = raw.find("/*", i)
                c_close = raw.find("*/", i)
                if c_close < 0:
                    buf.append(" " * (n - i))
                    i = n
                elif c_open >= 0 and c_open < c_close:
                    buf.append(" " * (c_open + 2 - i))
                    in_block_comment += 1
                    i = c_open + 2
                else:
                    buf.append(" " * (c_close + 2 - i))
                    in_block_comment -= 1
                    i = c_close + 2
                continue

            if raw.startswith("//", i):
                buf.append(" " * (n - i))
                break
            if raw.startswith("/*", i):
                buf.append("  ")
                in_block_comment = 1
                i += 2
                continue
            if raw.startswith('"""', i):
                buf.append('"""')
                in_triple_string = True
                i += 3
                continue
            ch = raw[i]
            if ch in ('"', "'"):
                quote = ch
                buf.append(quote)
                i += 1
                while i < n:
                    c = raw[i]
                    if c == "\\" and i + 1 < n:
                        buf.append("  ")
                        i += 2
                        continue
                    if c == quote:
                        buf.append(quote)
                        i += 1
                        break
                    buf.append(" ")
                    i += 1
                continue
            buf.append(ch)
            i += 1
        out.append("".join(buf))
    return out


def code_brace_delta(lines: list[str]) -> tuple[int, int]:
    """Return (net_brace_delta, min_running_depth) across scrubbed code lines."""
    scrubbed = scrub_comments_and_strings(lines)
    depth = 0
    min_depth = 0
    for ln in scrubbed:
        for ch in ln:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < min_depth:
                    min_depth = depth
    return depth, min_depth


def _match_declaration(line: str, suffix: str) -> tuple[str, str] | None:
    if suffix == ".java":
        m = _JAVA_TYPE_RE.match(line) or _JAVA_METHOD_RE.match(line)
        if not m:
            return None
        kind = " ".join((m.groupdict().get("kind") or "method").split())
        name = (m.groupdict().get("name") or "").strip()
        return (kind, name) if name else None
    if suffix == ".swift":
        m = _SWIFT_DECL_RE.match(line)
        if not m:
            return None
        kind = " ".join((m.groupdict().get("kind") or "").split())
        name = (m.groupdict().get("name") or ("init" if kind == "init" else "")).strip("`")
        return (kind, name) if name else None
    m = _KT_DECL_RE.match(line)
    if not m:
        return None
    kind = " ".join((m.groupdict().get("kind") or "").split())
    name = (m.groupdict().get("name") or "").strip("`")
    if kind == "companion object" and not name:
        name = "Companion"
    return (kind, name) if name else None


def parse_symbols(path: Path) -> list[dict[str, Any]]:
    """Parse declarations with exact 1-based line spans and SHA-256 body fingerprints."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValidationError(f"Unsupported file extension '{suffix}' for symbol surgery; expected {sorted(SUPPORTED_SUFFIXES)}.")
    if not path.is_file():
        raise ValidationError(f"Target source file does not exist: {path}")
    size = path.stat().st_size
    if size > MAX_SYMBOL_FILE_BYTES:
        raise ValidationError(f"Source file exceeds {MAX_SYMBOL_FILE_BYTES} byte safety cap: {path}")

    raw_text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    raw_lines = raw_text.splitlines()
    code_lines = scrub_comments_and_strings(raw_lines)

    entries: list[dict[str, Any]] = []
    open_blocks: list[tuple[dict[str, Any], int]] = []
    type_stack: list[tuple[str, int]] = []
    type_depths: set[int] = {0}
    depth = 0
    parens = 0
    pending: tuple[dict[str, Any], int, str] | None = None

    func_kinds = {"fun", "method", "func", "init"}
    prop_kinds = {"val", "var"}

    for idx, line in enumerate(code_lines, start=1):
        entry: dict[str, Any] | None = None
        stripped = line.strip()
        if stripped and parens == 0:
            matched = _match_declaration(line, suffix)
            if matched:
                kind, name = matched
                is_prop = kind in prop_kinds
                if (not is_prop or depth in type_depths) and (depth in type_depths or kind in func_kinds):
                    # Include contiguous leading annotations/KDoc lines attached directly above declaration
                    decl_start = idx
                    scan = idx - 2
                    while scan >= 0:
                        prev_raw = raw_lines[scan].strip()
                        if prev_raw.startswith("@"):
                            decl_start = scan + 1
                            scan -= 1
                            continue
                        break
                    enclosing = ".".join(t_name for t_name, _ in type_stack)
                    qualified = f"{enclosing}.{name}" if enclosing else name
                    entry = {
                        "name": name,
                        "qualified_name": qualified,
                        "kind": kind,
                        "start_line": decl_start,
                        "declaration_line": idx,
                        "body_open_line": idx,
                        "end_line": idx,
                    }
                    entries.append(entry)

        opens = line.count("{")
        closes = line.count("}")
        parens_after = max(0, parens + line.count("(") - line.count(")"))
        body: tuple[dict[str, Any], int] | None = None

        if entry is not None:
            pending = None
            if opens > closes:
                entry["body_open_line"] = idx
                body = (entry, depth)
            elif parens_after > 0:
                pending = (entry, depth, "paren")
            elif "=" in line and kind in func_kinds | prop_kinds:
                # Single-line or multi-line expression body without braces
                entry["end_line"] = idx
            elif not stripped.endswith(("}", ";")):
                pending = (entry, depth, "brace_next")
        elif pending is not None:
            held, held_depth, mode = pending
            if mode == "paren":
                if parens_after == 0:
                    if opens > closes:
                        held["body_open_line"] = idx
                        body, pending = (held, held_depth), None
                    elif "=" in line:
                        held["end_line"] = idx
                        pending = None
                    elif not stripped.endswith(("}", ";")):
                        pending = (held, held_depth, "brace_next")
                    else:
                        held["end_line"] = idx
                        pending = None
            elif stripped:
                if stripped.startswith("{") or opens > closes:
                    held["body_open_line"] = idx
                    body = (held, held_depth)
                else:
                    held["end_line"] = max(int(held["end_line"]), idx if "=" in line else int(held["declaration_line"]))
                pending = None

        if body is not None:
            open_blocks.append(body)
            b_kind = str(body[0]["kind"])
            if b_kind not in func_kinds and b_kind not in prop_kinds:
                type_depths.add(body[1] + 1)
                type_stack.append((str(body[0]["name"]), body[1]))

        depth = max(0, depth + opens - closes)
        parens = parens_after

        while open_blocks and depth <= open_blocks[-1][1]:
            done, start_depth = open_blocks.pop()
            done["end_line"] = idx
            type_depths.discard(start_depth + 1)
            while type_stack and type_stack[-1][1] >= start_depth:
                type_stack.pop()

    for item in entries:
        s_ln = int(item["start_line"])
        e_ln = int(item["end_line"])
        snippet = "\n".join(raw_lines[s_ln - 1:e_ln])
        digest = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
        item["line_count"] = e_ln - s_ln + 1
        item["body_sha256"] = digest
        item["short_sha256"] = digest[:12]

    return entries


def resolve_symbol(entries: list[dict[str, Any]], symbol_query: str, occurrence: int | None = None) -> dict[str, Any]:
    q = symbol_query.strip().strip("`")
    if not q:
        raise ValidationError("Symbol name cannot be empty.")
    matches = [
        e for e in entries
        if e["qualified_name"] == q or e["name"] == q or e["qualified_name"].endswith("." + q)
    ]
    # Prefer non-property matches if both a property and function/class share a query
    non_props = [e for e in matches if e["kind"] not in {"val", "var"}]
    if len(matches) > 1 and len(non_props) == 1 and occurrence is None:
        return non_props[0]
    if not matches:
        known = ", ".join(e["qualified_name"] for e in entries[:20])
        raise ValidationError(f"Symbol '{q}' not found. Available symbols: {known or '(none)'}")
    if occurrence is not None:
        if occurrence < 1 or occurrence > len(matches):
            raise ValidationError(f"Occurrence {occurrence} out of range (1..{len(matches)}) for symbol '{q}'.")
        return matches[occurrence - 1]
    if len(matches) > 1:
        locs = ", ".join(f"{m['qualified_name']}@L{m['start_line']}-L{m['end_line']} (#{i})" for i, m in enumerate(matches, 1))
        raise ValidationError(
            f"Ambiguous symbol '{q}' matched {len(matches)} declarations ({locs}). "
            "Pass qualified name (Class.method) or --occurrence <1..N>."
        )
    return matches[0]


def _authorize_symbol_write(repo: Path, target_file: Path) -> str:
    try:
        rel = target_file.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise ValidationError(f"Target file '{target_file}' is outside repository '{repo}'.") from exc

    from pre_tool_safety import check_write_safety
    safety = check_write_safety(repo, rel, tool_name="symbol_edit")
    if safety.get("decision") != "ALLOW":
        raise ValidationError(f"PROTECTED_PATH: {safety.get('reason')}")

    from mutation_guard import file_mutation_allowed
    allowed, reason, code = file_mutation_allowed(repo, targets=[rel])
    if not allowed:
        raise ValidationError(f"{code}: {reason}")

    conv = os.environ.get("HARNESS_CONVERSATION_ID", "").strip()
    if conv or os.environ.get("HARNESS_UTILITY_AGENT"):
        try:
            from delegation_policy import WORKER_AGENT, utility_subagent_context, worker_write_allowed
            uctx = utility_subagent_context(repo, conv, bind=False)
            if uctx is not None and str(uctx.get("agent_type") or "") == WORKER_AGENT:
                w_ok, w_reason, w_code = worker_write_allowed(repo, [rel], uctx)
                if not w_ok:
                    raise ValidationError(f"{w_code}: {w_reason}")
        except (ImportError, OSError, ValueError, KeyError):
            pass
    return rel


def _load_replacement_text(args: argparse.Namespace) -> str:
    if getattr(args, "replacement_file", None):
        rf = Path(args.replacement_file).expanduser().resolve()
        if not rf.is_file():
            raise ValidationError(f"Replacement file not found: {rf}")
        raw = rf.read_text(encoding="utf-8")
    elif getattr(args, "stdin", False):
        raw = __import__('_vnext_common').read_utf8_stdin()
    elif getattr(args, "body", None) is not None:
        raw = str(args.body)
    else:
        raise ValidationError("Provide replacement code via --replacement-file <path> or --stdin.")

    normalized = raw.replace("\r\n", "\n").rstrip("\n")
    if not normalized.strip():
        raise ValidationError("Replacement code cannot be empty.")
    net_delta, min_depth = code_brace_delta(normalized.splitlines())
    if net_delta != 0 or min_depth < 0:
        raise ValidationError(
            f"BRACE_IMBALANCE: replacement snippet has unbalanced braces (net_delta={net_delta}, min_depth={min_depth}). "
            "Provide the complete declaration including balanced opening and closing braces."
        )
    return normalized


def cmd_outline(repo: Path, args: argparse.Namespace) -> dict[str, Any]:
    target = (Path(args.file) if Path(args.file).is_absolute() else (repo / args.file)).resolve()
    symbols = parse_symbols(target)
    total_lines = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
    rel = target.relative_to(repo.resolve()).as_posix() if target.is_relative_to(repo.resolve()) else str(target)
    return {
        "status": "OK",
        "file": rel,
        "total_lines": total_lines,
        "symbol_count": len(symbols),
        "symbols": symbols,
    }


def cmd_read(repo: Path, args: argparse.Namespace) -> dict[str, Any]:
    target = (Path(args.file) if Path(args.file).is_absolute() else (repo / args.file)).resolve()
    symbols = parse_symbols(target)
    sym = resolve_symbol(symbols, args.symbol, args.occurrence)
    raw_lines = target.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").splitlines()
    s_ln, e_ln = int(sym["start_line"]), int(sym["end_line"])
    numbered = [f"{ln_no}: {raw_lines[ln_no - 1]}" for ln_no in range(s_ln, e_ln + 1)]
    rel = target.relative_to(repo.resolve()).as_posix() if target.is_relative_to(repo.resolve()) else str(target)
    return {
        "status": "OK",
        "file": rel,
        "symbol": sym,
        "source": "\n".join(raw_lines[s_ln - 1:e_ln]),
        "numbered_source": "\n".join(numbered),
    }


def cmd_replace_body(repo: Path, args: argparse.Namespace) -> dict[str, Any]:
    target = (Path(args.file) if Path(args.file).is_absolute() else (repo / args.file)).resolve()
    rel = _authorize_symbol_write(repo, target)
    replacement = _load_replacement_text(args)
    symbols = parse_symbols(target)
    sym = resolve_symbol(symbols, args.symbol, args.occurrence)

    exp_hash = str(getattr(args, "expected_sha256", "") or "").strip().lower()
    if exp_hash and not str(sym["body_sha256"]).startswith(exp_hash):
        raise ValidationError(
            f"SYMBOL_SHA256_MISMATCH: expected '{exp_hash}', current is '{sym['short_sha256']}' "
            f"on {sym['qualified_name']} (L{sym['start_line']}-L{sym['end_line']}). Re-run `symbol read` first."
        )

    raw_text = target.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    trailing_nl = raw_text.endswith("\n")
    lines = raw_text.splitlines()
    s_ln, e_ln = int(sym["start_line"]), int(sym["end_line"])
    rep_lines = replacement.splitlines()
    updated_lines = lines[:s_ln - 1] + rep_lines + lines[e_ln:]

    whole_delta, whole_min = code_brace_delta(updated_lines)
    if whole_delta != 0 or whole_min < 0:
        raise ValidationError(
            f"FILE_BRACE_IMBALANCE_AFTER_EDIT: whole-file brace check failed (net_delta={whole_delta}, min_depth={whole_min}); edit aborted."
        )

    out_bytes = ("\n".join(updated_lines) + ("\n" if trailing_nl or updated_lines else "")).encode("utf-8")
    atomic_write_bytes(target, out_bytes)
    new_symbols = parse_symbols(target)
    return {
        "status": "UPDATED",
        "file": rel,
        "replaced_symbol": sym["qualified_name"],
        "previous_span": [s_ln, e_ln],
        "new_line_count": len(rep_lines),
        "file_sha256": sha256_bytes(out_bytes)[:12],
        "symbol_count_after": len(new_symbols),
    }


def cmd_insert_after(repo: Path, args: argparse.Namespace) -> dict[str, Any]:
    target = (Path(args.file) if Path(args.file).is_absolute() else (repo / args.file)).resolve()
    rel = _authorize_symbol_write(repo, target)
    addition = _load_replacement_text(args)
    symbols = parse_symbols(target)
    sym = resolve_symbol(symbols, args.symbol, args.occurrence)

    exp_hash = str(getattr(args, "expected_sha256", "") or "").strip().lower()
    if exp_hash and not str(sym["body_sha256"]).startswith(exp_hash):
        raise ValidationError(
            f"SYMBOL_SHA256_MISMATCH: expected '{exp_hash}', current is '{sym['short_sha256']}' on {sym['qualified_name']}."
        )

    raw_text = target.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    trailing_nl = raw_text.endswith("\n")
    lines = raw_text.splitlines()
    e_ln = int(sym["end_line"])
    # Match indentation of anchor symbol's start line if addition is unindented
    anchor_indent = re.match(r"^(\s*)", lines[int(sym["declaration_line"]) - 1]).group(1)
    add_lines = addition.splitlines()
    if anchor_indent and add_lines and not add_lines[0].startswith((" ", "\t")):
        add_lines = [(anchor_indent + ln if ln.strip() else ln) for ln in add_lines]

    updated_lines = lines[:e_ln] + [""] + add_lines + lines[e_ln:]
    whole_delta, whole_min = code_brace_delta(updated_lines)
    if whole_delta != 0 or whole_min < 0:
        raise ValidationError(
            f"FILE_BRACE_IMBALANCE_AFTER_INSERT: whole-file brace check failed (net_delta={whole_delta}, min_depth={whole_min}); insert aborted."
        )

    out_bytes = ("\n".join(updated_lines) + ("\n" if trailing_nl or updated_lines else "")).encode("utf-8")
    atomic_write_bytes(target, out_bytes)
    return {
        "status": "INSERTED",
        "file": rel,
        "after_symbol": sym["qualified_name"],
        "inserted_at_line": e_ln + 2,
        "inserted_lines": len(add_lines),
        "file_sha256": sha256_bytes(out_bytes)[:12],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("outline", "read", "replace-body", "insert-after"))
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("HARNESS_REPO") or Path(__file__).resolve().parents[2]))
    parser.add_argument("--file", required=True, help="Target .kt, .java, or .swift file path")
    parser.add_argument("--symbol", help="Symbol name or Class.method qualified name")
    parser.add_argument("--occurrence", type=int, help="1-based index when overloaded methods share a name")
    parser.add_argument("--expected-sha256", dest="expected_sha256", help="Expected body SHA-256 prefix from `symbol read`")
    parser.add_argument("--replacement-file", dest="replacement_file", help="Path to temporary file containing new declaration+body")
    parser.add_argument("--stdin", action="store_true", help="Read replacement declaration+body from stdin")
    parser.add_argument("--body", "--code", "--replacement", dest="body", help="Inline replacement text for compact bodies")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)

    if args.action != "outline" and not args.symbol:
        parser.error(f"{args.action} requires --symbol <name>")

    repo = args.repo.resolve()
    handlers = {
        "outline": cmd_outline,
        "read": cmd_read,
        "replace-body": cmd_replace_body,
        "insert-after": cmd_insert_after,
    }
    try:
        res = handlers[args.action](repo, args)
        if args.json or args.action in {"replace-body", "insert-after"}:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        elif args.action == "outline":
            print(f"# {res['file']} ({res['total_lines']} lines, {res['symbol_count']} symbols)")
            for s in res["symbols"]:
                print(f"  L{s['start_line']}-L{s['end_line']} [{s['kind']}] {s['qualified_name']} (sha256={s['short_sha256']})")
        else:
            s = res["symbol"]
            print(f"# {res['file']} :: {s['qualified_name']} (L{s['start_line']}-L{s['end_line']}, sha256={s['short_sha256']})")
            print(res["numbered_source"])
        return 0
    except (OSError, ValueError, ValidationError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
