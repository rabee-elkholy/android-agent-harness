"""Repo-relative git/adb helpers shared by harness scripts."""
from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO = SCRIPTS_DIR.parent.parent

_CODE_SUFFIXES = {".kt", ".java", ".kts"}


def _unquote_git_path(raw: str) -> str:
    """Decode C-style quoted and octal-escaped Git porcelain path."""
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        inner = raw[1:-1]
        try:
            return inner.encode("latin1").decode("unicode_escape").encode("latin1").decode("utf-8")
        except Exception:
            return inner
    return raw


def changed_paths(*, include_untracked: bool = True) -> list[Path]:
    """Working-tree files vs HEAD: staged, unstaged, and untracked."""
    proc = subprocess.run(
        ["git", "status", "--porcelain", "-u", "--untracked-files=all"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    seen: dict[str, Path] = {}
    for line in (proc.stdout or "").splitlines():
        if len(line) < 4:
            continue
        xy = line[:2]
        path_str = line[3:].strip()
        if " -> " in path_str:
            path_str = path_str.split(" -> ", 1)[1].strip()
        path_str = _unquote_git_path(path_str)
        if not include_untracked and xy == "??":
            continue
        path = REPO / path_str
        if path.is_file():
            key = path_str.replace("\\", "/")
            seen[key] = path
    return list(seen.values())


def has_non_doc_code_changes() -> bool:
    """True when the working tree has Kotlin/Java/Gradle or non-string XML edits."""
    for path in changed_paths():
        try:
            rel = path.relative_to(REPO).as_posix()
        except ValueError:
            rel = str(path).replace("\\", "/")
        suffix = path.suffix.lower()
        if suffix in _CODE_SUFFIXES:
            return True
        if suffix == ".xml":
            lower_name = path.name.lower()
            if lower_name in ("strings.xml", "plurals.xml") or "/values" in f"/{rel}":
                continue
            return True
    return False


def first_adb_serial(*, allow_emulator: bool = True) -> str | None:
    try:
        proc = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return None
    for line in (proc.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            if allow_emulator or not parts[0].startswith("emulator-"):
                return parts[0]
    return None


def first_physical_adb_serial() -> str | None:
    return first_adb_serial(allow_emulator=False)

