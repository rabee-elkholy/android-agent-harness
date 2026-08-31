"""Deterministic pre-commit quality gate over STAGED files only.

Runs string parity, fast Kotlin lint, and the Room working-tree gate against
what is actually being committed. Fast (<5s), stdlib-only, and cross-tool: it
guards the developer's commit regardless of which AI assistant produced the code.
It never blocks on review-round policy — the developer owns commits; this gate
owns static correctness.

Usage:
  python .agents/scripts/pre_commit_gate.py          # from repo root or anywhere
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _repo_files import REPO, _unquote_git_path  # noqa: E402
from check_strings import check_hardcoded_strings  # noqa: E402
from fast_kt_lint import lint_file, get_modified_lines_map  # noqa: E402
from room_guard import check_room_working_tree  # noqa: E402

CODE_SUFFIXES = {".kt", ".java", ".kts", ".cpp", ".c", ".h", ".hpp", ".aidl", ".pro"}


def staged_paths() -> list[Path]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return []
    paths: list[Path] = []
    for line in (proc.stdout or "").splitlines():
        rel = _unquote_git_path(line.strip())
        if not rel:
            continue
        path = REPO / rel.replace("/", os.sep) if os.name == "nt" else REPO / rel
        if path.is_file():
            paths.append(path)
    return paths


def main() -> int:
    enable_line_buffered_stdio()
    paths = staged_paths()
    if not paths:
        live_print("[OK] Nothing staged for the quality gate.")
        return 0

    kt = [p for p in paths if p.suffix.lower() in CODE_SUFFIXES]
    xml = [p for p in paths if p.suffix.lower() == ".xml"]

    failures: list[str] = []

    if kt or xml:
        live_print(f"[git-gate] Scanning {len(kt)} Kotlin/Java and {len(xml)} XML staged file(s)...")
        lines_map = get_modified_lines_map(REPO, kt + xml, cached=True)
        for item in check_hardcoded_strings(kt + xml, lines_map=lines_map):
            failures.append(f"[STRINGS] {item}")
        for path in kt:
            mod_lines = lines_map.get(path)
            for iss in lint_file(path, modified_lines=mod_lines):
                if iss.get("type") == "IO_ERROR":
                    continue
                try:
                    rel = path.relative_to(REPO).as_posix()
                except ValueError:
                    rel = str(path)
                failures.append(f"[LINT] {rel}:{iss['line']} {iss['type']} -> {iss['msg']}")

    db_ok, db_msg = check_room_working_tree()
    live_print(f"[{'OK' if db_ok else 'FAIL'}] Room migration gate: {db_msg[:300]}")
    if not db_ok:
        failures.append(f"[ROOM] {db_msg}")

    try:
        from _hook_state import review_advisory

        advisory = review_advisory()
        if advisory:
            live_print(advisory)
    except Exception:
        pass

    if failures:
        live_print(f"\n[FAIL] Pre-commit gate blocked the commit: {len(failures)} issue(s)")
        for item in failures[:60]:
            live_print(f"  - {item}")
        if len(failures) > 60:
            live_print(f"  ... and {len(failures) - 60} more")
        live_print("Fix the findings, restage, and commit again. To bypass an emergency:")
        live_print("  git commit --no-verify   (use sparingly and explain in the message)")
        return 1

    live_print("[SUCCESS] Pre-commit gate passed: strings, fast lint, and Room clean on staged changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
