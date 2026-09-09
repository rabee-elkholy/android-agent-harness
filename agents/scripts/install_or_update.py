"""Removed legacy lifecycle entry point.

The vNext architecture deliberately separates clean installation from compatible
updates. Use lifecycle.py directly or the android-harness CLI.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle import OWNERSHIP_RELATIVE, install, update  # noqa: E402
from _vnext_common import HarnessError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--kit", required=True)
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        if (repo / OWNERSHIP_RELATIVE).is_file():
            result = update(repo, Path(args.kit))
        elif (repo / ".agents").exists():
            print(
                "[FAIL] Legacy in-place migration is unsupported. Run the safe legacy "
                "uninstall preview, remove the old harness, then perform a clean install.",
                file=sys.stderr,
            )
            return 1
        else:
            result = install(repo, Path(args.kit))
    except (HarnessError, OSError, RuntimeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"[{result['status']}] {result['action']} v{result.get('version', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
