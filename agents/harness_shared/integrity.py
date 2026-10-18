"""Bundled pre-execution verifier for selected kit payloads.

This module never imports code from the kit being verified.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re


class KitIntegrityError(ValueError):
    """The selected kit cannot establish an exact immutable payload."""


def verify_kit(kit: Path) -> dict[str, str]:
    checksum_file = kit / "agents/release_checksums.json"
    if not checksum_file.is_file() or checksum_file.is_symlink():
        raise KitIntegrityError(f"Kit release checksums manifest missing or symlink: {checksum_file}")
    try:
        manifest = json.loads(checksum_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KitIntegrityError(f"Kit release checksums manifest corrupt: {exc}") from exc
    if not isinstance(manifest, dict):
        raise KitIntegrityError("Kit release checksums manifest has an unsupported schema")
    if manifest.get("algorithm", "sha256") != "sha256":
        raise KitIntegrityError("Kit release checksums algorithm must be sha256")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise KitIntegrityError("Kit release checksums manifest files inventory is empty or malformed")
    for rel, digest in files.items():
        if (not isinstance(rel, str) or not rel.startswith("agents/") or "\\" in rel
                or PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).drive
                or ".." in PurePosixPath(rel).parts):
            raise KitIntegrityError(f"Suspicious path in release checksums: {rel}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise KitIntegrityError(f"Invalid release checksum for {rel}")
    missing_core = {"agents/VERSION", "agents/scripts/lifecycle.py"} - files.keys()
    if missing_core:
        raise KitIntegrityError(f"Kit release checksums manifest missing core files: {', '.join(sorted(missing_core))}")
    agents_dir = kit / "agents"
    if not agents_dir.is_dir() or agents_dir.is_symlink():
        raise KitIntegrityError(f"Kit agents directory missing or symlink: {agents_dir}")
    actual_files = set()
    for path in sorted(agents_dir.rglob("*")):
        if path.is_symlink():
            raise KitIntegrityError(f"Symlink rejected in kit payload: {path.relative_to(kit).as_posix()}")
        relative = path.relative_to(agents_dir)
        if (not path.is_file() or relative.as_posix() == "release_checksums.json"
                or {"state", "cache", "__pycache__"}.intersection(relative.parts)
                or path.suffix.lower() in {".pyc", ".pyo"}):
            continue
        actual_files.add(path.relative_to(kit).as_posix())
    if actual_files != set(files):
        missing = sorted(set(files) - actual_files)
        unexpected = sorted(actual_files - set(files))
        details = []
        if missing:
            details.append(f"missing ({len(missing)}): {', '.join(missing[:10])}")
        if unexpected:
            details.append(f"unexpected ({len(unexpected)}): {', '.join(unexpected[:10])}")
        raise KitIntegrityError(f"Kit release checksums inventory mismatch: {'; '.join(details)}")
    try:
        for rel, expected in files.items():
            target = kit / rel
            if not target.is_file() or target.is_symlink():
                raise KitIntegrityError(f"Missing or symlinked kit file: {rel}")
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise KitIntegrityError(f"Kit release checksum mismatch for {rel}")
    except OSError as exc:
        raise KitIntegrityError(f"Kit payload is unreadable: {exc}") from exc
    return files
