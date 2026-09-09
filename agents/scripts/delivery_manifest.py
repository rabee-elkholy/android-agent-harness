"""Build the canonical delivery snapshot and reviewed change-set identities."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import (  # noqa: E402
    HarnessError,
    atomic_write_json,
    canonical_sha256,
    git,
    git_text,
    repository_identity,
    sha256_bytes,
    utc_now,
)


SCHEMA_VERSION = 1
ROOT_EXCLUDED = {".git", ".agents", ".harness-setup", ".harness-backup", ".harness-backups", "docs"}
NESTED_EXCLUDED = {".gradle", ".idea", "build", "out", "node_modules", "__pycache__"}
SOURCE_SUFFIXES = {
    ".kt", ".java", ".kts", ".gradle", ".groovy", ".toml", ".xml", ".json",
    ".aidl", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".pro", ".rules",
    ".properties", ".jar", ".aar", ".so", ".png", ".jpg", ".jpeg", ".webp",
    ".gif", ".svg", ".ttf", ".otf", ".wav", ".mp3", ".ogg", ".mp4",
}
SOURCE_SUFFIX_TUPLE = tuple(sorted(SOURCE_SUFFIXES))
ROOT_BUILD_FILES = {
    "gradlew", "gradlew.bat", "settings.gradle", "settings.gradle.kts",
    "build.gradle", "build.gradle.kts", "gradle.properties",
}
EXTERNAL_CANDIDATES = {
    "local.properties",
    "google-services.json",
    "app/google-services.json",
}


@dataclass(frozen=True)
class ChangeEntry:
    status: str
    path: str
    old_path: str | None
    content_identity: str


def _normal_rel(raw: str) -> str:
    normalized = raw.replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def is_delivery_relevant(relative: str) -> bool:
    rel = _normal_rel(relative)
    lowered = rel.lower()
    first = lowered.partition("/")[0]
    framed = f"/{lowered.strip('/')}/"
    if first in ROOT_EXCLUDED or any(f"/{part}/" in framed for part in NESTED_EXCLUDED):
        return False
    name = lowered.rpartition("/")[2]
    if name in ROOT_BUILD_FILES:
        return True
    if lowered.endswith(("gradle-wrapper.jar", "gradle-wrapper.properties")):
        return True
    if "/src/" in f"/{lowered}" and any(
        marker in f"/{lowered}/" for marker in ("/res/", "/assets/", "/resources/", "/jnilibs/", "/cpp/")
    ):
        return True
    if name.endswith(SOURCE_SUFFIX_TUPLE):
        return True
    return False


def _object_format(repo: Path) -> str:
    try:
        value = git_text(repo, "rev-parse", "--show-object-format")
    except HarnessError:
        return "sha1"
    return value if value in ("sha1", "sha256") else "sha1"


def _working_tree_oid(repo: Path, relative: str, path: Path, algorithm: str) -> str:
    """Return the Git identity after attributes and clean filters are applied."""
    oid = git(
        repo,
        "hash-object",
        "--path",
        _normal_rel(relative),
        "--stdin",
        input_bytes=_path_bytes(path),
    ).decode("ascii", errors="strict").strip()
    if len(oid) != hashlib.new(algorithm).digest_size * 2 or any(char not in "0123456789abcdef" for char in oid):
        raise HarnessError(f"Git returned an invalid object identity for {relative}")
    return oid


def _path_bytes(path: Path) -> bytes:
    if path.is_symlink():
        return os.readlink(path).encode("utf-8", errors="surrogateescape")
    return path.read_bytes()


def _index_and_untracked(repo: Path) -> tuple[dict[str, str], set[str]]:
    index: dict[str, str] = {}
    untracked: set[str] = set()
    raw = git(repo, "ls-files", "-s", "--others", "--exclude-standard", "-z")
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        meta, sep, raw_path = entry.partition(b"\t")
        if not sep:
            untracked.add(_normal_rel(entry.decode("utf-8", errors="surrogateescape")))
            continue
        parts = meta.split()
        if len(parts) < 3 or parts[2] != b"0":
            continue
        index[_normal_rel(raw_path.decode("utf-8", errors="surrogateescape"))] = parts[1].decode("ascii")
    return index, untracked


def _porcelain_changes(
    repo: Path,
    algorithm: str,
    content_cache: dict[str, str],
    index_entries: dict[str, str],
) -> list[ChangeEntry]:
    raw = git(repo, "status", "--porcelain=v2", "-z", "-u", "--untracked-files=all")
    chunks = raw.split(b"\0")
    entries: list[ChangeEntry] = []
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        index += 1
        if not chunk:
            continue
        line = chunk.decode("utf-8", errors="surrogateescape")
        status = ""
        rel = ""
        old_rel: str | None = None
        if line.startswith("1 "):
            parts = line.split(" ", 8)
            if len(parts) < 9:
                continue
            xy, rel = parts[1], parts[8]
            status = "D" if "D" in xy else "A" if "A" in xy else "T" if "T" in xy else "M"
        elif line.startswith("2 "):
            parts = line.split(" ", 9)
            if len(parts) < 10:
                continue
            xy, rel = parts[1], parts[9]
            old_rel = chunks[index].decode("utf-8", errors="surrogateescape") if index < len(chunks) else None
            index += 1
            status = "C" if "C" in xy else "R"
        elif line.startswith("u "):
            parts = line.split(" ", 10)
            if len(parts) < 11:
                continue
            rel = parts[10]
            status = "U"
        elif line.startswith("? "):
            rel = line[2:]
            status = "A"
        else:
            continue
        rel = _normal_rel(rel)
        old_rel = _normal_rel(old_rel) if old_rel else None
        if not (is_delivery_relevant(rel) or (old_rel and is_delivery_relevant(old_rel))):
            continue
        path = repo / rel
        if status == "D" or (not path.exists() and not path.is_symlink()):
            base_oid = index_entries.get(rel, "unknown")
            identity = f"tombstone:git:{base_oid}"
        else:
            oid = _working_tree_oid(repo, rel, path, algorithm)
            content_cache[rel] = oid
            identity = f"git:{oid}"
        entries.append(ChangeEntry(status=status, path=rel, old_path=old_rel, content_identity=identity))
    # Git does not always report an unstaged filesystem rename as a rename. Pair
    # a deleted index blob with an added working-tree blob deterministically so
    # the canonical change set still models the operation accurately.
    deletes: dict[str, list[ChangeEntry]] = {}
    additions: dict[str, list[ChangeEntry]] = {}
    for entry in entries:
        if entry.status == "D" and entry.content_identity.startswith("tombstone:"):
            deletes.setdefault(entry.content_identity.removeprefix("tombstone:"), []).append(entry)
        elif entry.status == "A":
            additions.setdefault(entry.content_identity, []).append(entry)
    consumed: set[ChangeEntry] = set()
    replacements: list[ChangeEntry] = []
    for identity in sorted(set(deletes) & set(additions)):
        old_items = sorted(deletes[identity], key=lambda item: item.path)
        new_items = sorted(additions[identity], key=lambda item: item.path)
        for old, new in zip(old_items, new_items):
            consumed.update((old, new))
            replacements.append(ChangeEntry(status="R", path=new.path, old_path=old.path, content_identity=new.content_identity))
    entries = [entry for entry in entries if entry not in consumed] + replacements
    return sorted(entries, key=lambda item: (item.path, item.old_path or "", item.status))


def _delivery_files(
    repo: Path,
    changes: list[ChangeEntry],
    algorithm: str,
    content_cache: dict[str, str],
    index: dict[str, str],
    untracked: set[str],
) -> list[dict[str, str]]:
    changed_paths = {entry.path for entry in changes}
    candidates = set(index) | untracked
    result: list[dict[str, str]] = []
    for rel in sorted(candidates):
        if not is_delivery_relevant(rel):
            continue
        if rel in changed_paths or rel in untracked:
            path = repo / rel
            if not path.exists() and not path.is_symlink():
                continue
            identity = content_cache.get(rel) or _working_tree_oid(repo, rel, path, algorithm)
            source = "working_tree"
        else:
            identity = index.get(rel)
            source = "git_index"
        if not identity:
            raise HarnessError(f"cannot identify delivery file: {rel}")
        result.append({"path": rel, "content_identity": f"git:{identity}", "source": source})
    return result


def _external_inputs(repo: Path) -> list[dict[str, str | int | bool]]:
    result: list[dict[str, str | int | bool]] = []
    ignored_relevant = {
        _normal_rel(item.decode("utf-8", errors="surrogateescape"))
        for item in git(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").split(b"\0")
        if item and is_delivery_relevant(_normal_rel(item.decode("utf-8", errors="surrogateescape")))
    }
    for rel in sorted(EXTERNAL_CANDIDATES | ignored_relevant):
        path = repo / rel
        if not path.is_file():
            continue
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--", rel], cwd=str(repo), check=False
        ).returncode == 0
        if not ignored:
            continue
        if path.name == "local.properties":
            keys: list[str] = []
            normalized_lines: list[str] = []
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key, value = stripped.split("=", 1)
                    keys.append(key.strip())
                    normalized_lines.append(f"{key.strip()}={value.strip()}")
            result.append({
                "path": rel,
                "ignored": True,
                "identity": sha256_bytes("\n".join(sorted(normalized_lines)).encode()),
                "redacted": True,
                "keys": ",".join(sorted(keys)),
            })
        else:
            result.append({"path": rel, "ignored": True, "identity": sha256_bytes(path.read_bytes()), "redacted": False})
    versions = _toolchain_versions()
    result.append({"path": "<toolchain>", "ignored": False, "identity": canonical_sha256(versions), "redacted": False})
    return result


@lru_cache(maxsize=1)
def _toolchain_versions() -> dict[str, str]:
    try:
        java_proc = subprocess.run(["java", "-version"], capture_output=True, text=True, check=False)
        java_version = (java_proc.stderr or java_proc.stdout or "unavailable").splitlines()[0][:200]
    except OSError:
        java_version = "unavailable"
    try:
        git_proc = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False)
        git_version = (git_proc.stdout or git_proc.stderr or "unavailable").strip()[:200]
    except OSError:
        git_version = "unavailable"
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "git": git_version,
        "java": java_version,
    }


def build_manifest(repo: Path) -> dict:
    root = repo.resolve()
    algorithm = _object_format(root)
    content_cache: dict[str, str] = {}
    index, untracked = _index_and_untracked(root)
    changes = _porcelain_changes(root, algorithm, content_cache, index)
    files = _delivery_files(root, changes, algorithm, content_cache, index, untracked)
    file_identity = [{"path": item["path"], "content_identity": item["content_identity"]} for item in files]
    change_identity = [asdict(item) for item in changes]
    external = _external_inputs(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "repository": repository_identity(root),
        "object_format": algorithm,
        "delivery_snapshot_sha256": canonical_sha256(file_identity),
        "change_set_sha256": canonical_sha256(change_identity),
        "external_inputs_sha256": canonical_sha256(external),
        "files": files,
        "changes": change_identity,
        "external_inputs": external,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Git repository root")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    args = parser.parse_args()
    try:
        manifest = build_manifest(Path(args.repo))
        if args.output:
            atomic_write_json(Path(args.output), manifest)
        if args.json:
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        else:
            print(f"DELIVERY_SNAPSHOT_SHA256={manifest['delivery_snapshot_sha256']}")
            print(f"CHANGE_SET_SHA256={manifest['change_set_sha256']}")
            print(f"DELIVERY_FILES={len(manifest['files'])}")
            print(f"CHANGED_DELIVERY_FILES={len(manifest['changes'])}")
        return 0
    except HarnessError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
