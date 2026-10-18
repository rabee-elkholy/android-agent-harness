"""Pure checkout containment and nested-kit discovery helpers."""
from __future__ import annotations

from pathlib import Path


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def assert_kit_outside_repo(repo: Path, kit: Path) -> None:
    if is_within(kit, repo):
        raise ValueError(f"Harness kit checkout must live outside target Android repository: {kit.resolve()} inside {repo.resolve()}")


def find_nested_kit_checkouts(repo: Path) -> list[Path]:
    found: list[Path] = []
    try:
        for child in repo.iterdir():
            if (child.is_dir() and (child / ".git").exists()
                    and (child / "harness_cli.py").is_file()
                    and (child / "agents/VERSION").is_file()
                    and (child / "agents/scripts/lifecycle.py").is_file()):
                found.append(child.resolve())
    except OSError:
        # Advisory discovery only; target containment is enforced separately.
        return sorted(found)
    return sorted(found)
