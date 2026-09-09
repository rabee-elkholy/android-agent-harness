"""Generate deterministic checksums for installable harness payload files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents"
OUTPUT = AGENTS / "release_checksums.json"


def included(path: Path) -> bool:
    rel = path.relative_to(AGENTS)
    return (
        path.is_file()
        and rel.as_posix() != "release_checksums.json"
        and "state" not in rel.parts
        and "cache" not in rel.parts
        and "__pycache__" not in rel.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


def normalize_and_read(path: Path) -> bytes:
    data = path.read_bytes()
    if b"\r\n" in data:
        data = data.replace(b"\r\n", b"\n")
        path.write_bytes(data)
    return data


def main() -> int:
    files = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(normalize_and_read(path)).hexdigest()
        for path in sorted(AGENTS.rglob("*")) if included(path)
    }
    payload = {"schema_version": 1, "algorithm": "sha256", "files": files}
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
