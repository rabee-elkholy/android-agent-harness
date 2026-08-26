"""Validate release tag alignment against agents/VERSION, pyproject.toml, and CHANGELOG.md."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    ref_name = os.environ.get("REF_NAME", "")
    if not ref_name and len(sys.argv) > 1:
        ref_name = sys.argv[1]

    tag = ref_name.lstrip("v")
    repo_root = Path(__file__).resolve().parent.parent

    ver = (repo_root / "agents" / "VERSION").read_text(encoding="utf-8").strip()
    if tag:
        assert ver == tag, f"agents/VERSION ({ver}) does not match tag ({tag})"

    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{ver}"' in pyproject, f"pyproject.toml version does not match agents/VERSION ({ver})"

    changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"[{ver}]" in changelog, f"Version {ver} not found in CHANGELOG.md"

    print(f"Release version {ver} is valid and aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
