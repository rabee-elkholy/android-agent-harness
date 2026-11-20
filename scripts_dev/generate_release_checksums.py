"""Generate or verify deterministic checksums for installable harness payload files."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
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


TEXT_EXTENSIONS = {
    ".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".xml",
    ".sh", ".bat", ".ps1", ".cff", ".gradle", ".kts", ".properties",
}


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def normalize_and_read(path: Path) -> bytes:
    data = path.read_bytes()
    if is_text_file(path) and b"\r\n" in data:
        rel = path.relative_to(ROOT).as_posix()
        raise SystemExit(f"[FAIL] {rel} contains Windows CRLF line endings. Normalize text files to LF before generating checksums.")
    return data


def compute_payload() -> dict[str, object]:
    files = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(normalize_and_read(path)).hexdigest()
        for path in sorted(AGENTS.rglob("*")) if included(path)
    }
    return {"schema_version": 1, "algorithm": "sha256", "files": files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify agents/release_checksums.json without modifying disk")
    args = parser.parse_args(argv)

    payload = compute_payload()
    files = payload["files"]
    assert isinstance(files, dict)

    if args.check:
        if not OUTPUT.is_file():
            print(f"[FAIL] {OUTPUT.relative_to(ROOT)} is missing.", file=sys.stderr)
            return 1
        try:
            existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[FAIL] Could not parse {OUTPUT.relative_to(ROOT)}: {exc}", file=sys.stderr)
            return 1
        if existing != payload:
            print(f"[FAIL] {OUTPUT.relative_to(ROOT)} is out of sync with agents/ payload.", file=sys.stderr)
            return 1
        print(f"[OK] {OUTPUT.relative_to(ROOT)} matches all {len(files)} files.")
        return 0

    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
