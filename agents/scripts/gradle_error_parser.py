"""Fast Gradle / kotlinc Compiler Error Parser for this Android app.
Extracts clean, actionable file:line compiler errors from Gradle stdout/stderr.

Usage:
  python .agents/scripts/gradle_error_parser.py --log <path_to_log_or_stdin>
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

KOTLIN_ERROR_RE = re.compile(
    r"^e:\s+(?:file:///?)?(.+?\.kt):\s*(?:\()?\s*(\d+)(?:[,\s:]+(\d+)\)?)?\s*:\s*(.+)$",
    re.MULTILINE,
)
JAVAC_ERROR_RE = re.compile(
    r"^(?:\[ERROR\]\s*)?([a-zA-Z]:[\\/][^\r\n:]+|\/[^\r\n:]+?\.java):(\d+):\s*error:\s*(.+)$",
    re.MULTILINE,
)


def parse_compiler_errors(raw_log: str) -> list[dict]:
    errors = []
    seen = set()

    for match in KOTLIN_ERROR_RE.finditer(raw_log):
        filepath, line, col, msg = match.groups()
        key = (filepath.strip(), int(line), msg.strip())
        if key not in seen:
            seen.add(key)
            errors.append({
                "type": "Kotlin",
                "file": filepath.strip(),
                "line": int(line),
                "column": int(col) if col else None,
                "message": msg.strip(),
            })

    for match in JAVAC_ERROR_RE.finditer(raw_log):
        filepath, line, msg = match.groups()
        key = (filepath.strip(), int(line), msg.strip())
        if key not in seen:
            seen.add(key)
            errors.append({
                "type": "Java",
                "file": filepath.strip(),
                "line": int(line),
                "column": None,
                "message": msg.strip(),
            })

    return errors


def format_errors(errors: list[dict]) -> str:
    if not errors:
        return "[OK] No compiler errors detected in build log."
    
    lines = [f"[ERROR] Found {len(errors)} compilation error(s):"]
    for i, err in enumerate(errors, 1):
        col_str = f":{err['column']}" if err['column'] else ""
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
        raw_log = sys.stdin.read()

    errors = parse_compiler_errors(raw_log)
    print(format_errors(errors))
    sys.exit(len(errors))


if __name__ == "__main__":
    main()
