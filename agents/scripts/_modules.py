"""Multi-module discovery shared by lints, audits, and the doctor."""
from __future__ import annotations

from pathlib import Path

SKIP_PARTS = {".git", "build", ".gradle", ".idea", ".agents", ".harness-backup", ".harness-setup", "node_modules", "__pycache__"}

_SRC_MARKERS = ("java", "kotlin")


def _is_skipped(path: Path) -> bool:
    return bool(set(path.parts) & SKIP_PARTS)


def discover_source_roots(repo: Path) -> list[Path]:
    """All module source roots shaped like <module>/src/{main,androidMain}/{java,kotlin}.

    Recursive globs cover nested modules (:core:data) and KMP androidMain.
    """
    roots: dict[str, Path] = {}
    for src_dir in ("main", "androidMain"):
        for marker in _SRC_MARKERS:
            for candidate in repo.glob(f"**/src/{src_dir}/{marker}"):
                if candidate.is_dir() and not _is_skipped(candidate):
                    roots[str(candidate)] = candidate
    return [roots[k] for k in sorted(roots)]


def module_name_of(source_root: Path, repo: Path) -> str:
    try:
        rel = source_root.relative_to(repo).as_posix()
    except ValueError:
        return ":unknown"
    module_path = rel.split("/src/")[0]
    if not module_path or module_path == ".":
        return ":app"
    return ":" + module_path.replace("/", ":")
