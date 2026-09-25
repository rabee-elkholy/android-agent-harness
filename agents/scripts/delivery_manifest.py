"""Build the canonical delivery snapshot and reviewed change-set identities."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import (  # noqa: E402
    HarnessError,
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    git,
    git_text,
    repository_identity,
    sha256_bytes,
    utc_now,
)


SCHEMA_VERSION = 1
ROOT_EXCLUDED = {".git", ".agents", ".harness-setup", ".harness-backup", ".harness-backups"}
NESTED_EXCLUDED = {".gradle", ".idea", "build", "out", "node_modules", "__pycache__"}
SOURCE_SUFFIXES = {
    ".kt", ".java", ".kts", ".gradle", ".groovy", ".toml", ".xml", ".json",
    ".aidl", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".pro", ".rules",
    ".properties", ".jar", ".aar", ".so", ".bin", ".png", ".jpg", ".jpeg", ".webp",
    ".gif", ".svg", ".ttf", ".otf", ".wav", ".mp3", ".ogg", ".mp4",
    ".md", ".rst", ".adoc",
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
SECRET_PATH_MARKERS = (".env", "keystore", "jks", "secret", "token", "credentials", "local.properties")


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
    if lowered.startswith(("agents/state/", "agents/cache/", "audit/")):
        return False
    name = lowered.rpartition("/")[2]
    if name in ROOT_BUILD_FILES or name in ("baseline-prof.txt", "startup-prof.txt"):
        return True
    if first == "docs" and name.endswith(".txt"):
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
            if status == "M" and xy == ".M" and oid == index_entries.get(rel):
                continue
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
                    k_clean = key.strip()
                    keys.append(k_clean)
                    val_clean = re.sub(r"/+", "/", value.strip().replace("\\:", ":").replace("\\", "/"))
                    normalized_lines.append(f"{k_clean}={val_clean}")
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
        # JVM option notices ("Picked up JAVA_TOOL_OPTIONS: ...") carry environment noise such as
        # proxy ports; the version line is the toolchain identity.
        java_lines = [
            line for line in (java_proc.stderr or java_proc.stdout or "").splitlines()
            if line.strip() and not line.startswith("Picked up ")
        ]
        java_version = (java_lines[0] if java_lines else "unavailable")[:200]
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


def load_task_baseline(repo: Path, task_id: str | None = None) -> dict | None:
    root = repo.resolve()
    tid = task_id
    if not tid:
        for state_dir in (root / ".agents" / "state", root / "agents" / "state"):
            active_file = state_dir / "active-task.json"
            if active_file.is_file():
                try:
                    data = json.loads(active_file.read_text(encoding="utf-8"))
                    tid = data.get("task_id")
                    if tid:
                        break
                except Exception:
                    pass
    if not tid:
        return None
    for state_dir in (root / ".agents" / "state", root / "agents" / "state"):
        baseline_file = state_dir / "tasks" / tid / "task-baseline.json"
        if baseline_file.is_file():
            try:
                return json.loads(baseline_file.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


import difflib


def _is_tracked_in_head(repo: Path, rel: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{rel}"],
            cwd=str(repo),
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def build_task_diff(
    repo: Path,
    task_id_or_manifest: str | dict | None = None,
    task_manifest: dict | None = None,
    *,
    task_id: str | None = None,
) -> str:
    """Build unified diff for changes introduced by this task, isolating pre-existing dirty baseline."""
    root = repo.resolve()
    if isinstance(task_id_or_manifest, dict):
        manifest = task_id_or_manifest
        resolved_task_id = task_id or (task_manifest if isinstance(task_manifest, str) else None)
    else:
        manifest = task_manifest if task_manifest is not None else {}
        resolved_task_id = task_id or (task_id_or_manifest if isinstance(task_id_or_manifest, str) else None)

    task_changes = manifest.get("task_changes")
    if task_changes is None or manifest.get("task_delta_mode") == "LEGACY_FULL_WORKTREE":
        raw_changes = manifest.get("changes") or []
        paths = sorted({str(c.get("path") or "") for c in raw_changes if c.get("path")} | {str(c.get("old_path") or "") for c in raw_changes if c.get("old_path")})
        secret_markers = (".env", "keystore", "jks", "secret", "token", "credentials", "local.properties")
        safe_paths = [p for p in paths if not any(m in p.lower() for m in secret_markers)]
        if not safe_paths:
            return ""
        chunks: list[str] = []
        for offset in range(0, len(safe_paths), 100):
            proc = subprocess.run(
                ["git", "diff", "--no-ext-diff", "--full-index", "--find-renames", "--unified=10", "HEAD", "--", *safe_paths[offset:offset+100]],
                cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            chunks.append(proc.stdout or "")
        return "".join(chunks)

    baseline_files_dir: Path | None = None
    task_base_head: str | None = manifest.get("task_base_head")
    if resolved_task_id:
        for candidate_state in (root / ".agents" / "state", root / "agents" / "state"):
            c_dir = candidate_state / "tasks" / resolved_task_id / "baseline-files"
            if c_dir.is_dir():
                baseline_files_dir = c_dir
            plan_file = candidate_state / "tasks" / resolved_task_id / "plan.json"
            if plan_file.is_file() and not task_base_head:
                try:
                    pdata = json.loads(plan_file.read_text(encoding="utf-8"))
                    task_base_head = pdata.get("task_base_head") or pdata.get("repository", {}).get("head")
                except Exception:
                    pass

    secret_markers = (".env", "keystore", "jks", "secret", "token", "credentials", "local.properties")
    diff_chunks: list[str] = []

    sorted_changes = sorted(task_changes, key=lambda c: (c.get("path") or "", c.get("old_path") or "", c.get("status") or ""))
    for item in sorted_changes:
        rel = item.get("path") or ""
        if not rel:
            continue
        rel_norm = rel.replace("\\", "/")
        if any(m in rel_norm.lower() for m in secret_markers):
            continue

        status = item.get("status")
        base_copy = (baseline_files_dir / rel) if baseline_files_dir else None
        target_path = root / rel

        if status == "BASELINE_DIRTY_REMOVED":
            if base_copy and base_copy.is_file():
                base_lines = base_copy.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                try:
                    head_bytes = git(root, "show", f"HEAD:{rel}")
                    head_lines = head_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
                except Exception:
                    head_lines = []
                chunk = "".join(difflib.unified_diff(base_lines, head_lines, fromfile=f"a/{rel} (baseline-dirty)", tofile=f"b/{rel} (reverted-to-head)"))
                if chunk:
                    diff_chunks.append(chunk)
            continue

        if base_copy and base_copy.is_file() and target_path.is_file():
            base_lines = base_copy.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            cur_lines = target_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            chunk = "".join(difflib.unified_diff(base_lines, cur_lines, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
            if chunk:
                diff_chunks.append(chunk)
        elif status == "A" and not _is_tracked_in_head(root, rel):
            if target_path.is_file():
                cur_lines = target_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                chunk = "".join(difflib.unified_diff([], cur_lines, fromfile="/dev/null", tofile=f"b/{rel}"))
                if chunk:
                    diff_chunks.append(chunk)
        else:
            base_ref = task_base_head or "HEAD"
            proc = subprocess.run(
                ["git", "diff", "--no-ext-diff", "--full-index", "--find-renames", "--unified=10", base_ref, "--", rel],
                cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            if proc.stdout:
                diff_chunks.append(proc.stdout)

    return "".join(diff_chunks)


def build_task_manifest(
    repo: Path,
    baseline: dict | list | str | None = None,
    expected_files: list[str] | set[str] | None = None,
    task_base_head: str | None = None,
) -> dict:
    manifest = build_manifest(repo)
    task_id: str | None = None
    if isinstance(baseline, str):
        task_id = baseline
        baseline = load_task_baseline(repo, task_id)
        if task_id:
            for state_dir in (repo.resolve() / ".agents" / "state", repo.resolve() / "agents" / "state"):
                plan_file = state_dir / "tasks" / task_id / "plan.json"
                if plan_file.is_file():
                    try:
                        pdata = json.loads(plan_file.read_text(encoding="utf-8"))
                        if task_base_head is None:
                            task_base_head = pdata.get("task_base_head") or pdata.get("repository", {}).get("head")
                        if expected_files is None:
                            expected_files = pdata.get("expected_files")
                        break
                    except Exception:
                        pass

    if task_base_head is None and isinstance(baseline, dict):
        task_base_head = baseline.get("task_base_head")

    committed_task_changes: list[dict] = []
    if task_base_head:
        try:
            current_head = git_text(repo, "rev-parse", "HEAD")
            if current_head != task_base_head:
                proc = subprocess.run(
                    ["git", "diff", "--name-status", task_base_head, current_head],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode == 0:
                    for line in proc.stdout.splitlines():
                        if not line.strip():
                            continue
                        parts = line.split("\t")
                        stat = parts[0][0]
                        p = parts[-1]
                        old_p = parts[1] if len(parts) > 2 else None
                        if is_delivery_relevant(p):
                            target_p = repo / p
                            if target_p.is_file():
                                raw_oid = git(repo, "hash-object", "--path", p, "--stdin", input_bytes=target_p.read_bytes()).decode("utf-8").strip()
                                oid = f"git:{raw_oid}"
                            else:
                                try:
                                    base_blob = git_text(repo, "rev-parse", f"{task_base_head}:{p}").strip()
                                    oid = f"tombstone:git:{base_blob}"
                                except Exception:
                                    oid = "tombstone:git:unknown"
                            committed_task_changes.append({
                                "status": stat,
                                "path": _normal_rel(p),
                                "old_path": _normal_rel(old_p) if old_p else None,
                                "content_identity": oid,
                            })
        except Exception:
            pass

    if baseline is None:
        all_changes = list(manifest.get("changes") or [])
        cur_paths = {_normal_rel(c.get("path") or "") for c in all_changes if c.get("path")}
        for comm in committed_task_changes:
            if comm.get("path") not in cur_paths:
                all_changes.append(comm)
                cur_paths.add(comm.get("path"))
        all_changes.sort(key=lambda item: (item.get("path") or "", item.get("old_path") or "", item.get("status") or ""))
        change_identities = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in all_changes]
        manifest["task_changes"] = all_changes
        manifest["task_change_set_sha256"] = canonical_sha256(change_identities)
        manifest["task_delta_mode"] = "TASK_COMMITTED_OR_WORKTREE" if task_base_head else "LEGACY_FULL_WORKTREE"
        if task_base_head:
            manifest["task_base_head"] = task_base_head
        return manifest

    if isinstance(baseline, dict):
        base_changes = baseline.get("changes") or []
    elif isinstance(baseline, list):
        base_changes = list(baseline)
    else:
        base_changes = []

    base_map: dict[str, dict] = {}
    for entry in base_changes:
        if isinstance(entry, dict):
            p = entry.get("path")
            base_entry = entry
        elif hasattr(entry, "path"):
            p = entry.path
            base_entry = asdict(entry) if hasattr(entry, "__dataclass_fields__") else vars(entry)
        else:
            p = str(entry)
            base_entry = {"path": p, "status": "M", "content_identity": ""}
        if p:
            base_map[_normal_rel(p)] = base_entry
            base_map[p] = base_entry

    task_changes: list[dict] = []
    current_changes = manifest.get("changes") or []
    current_paths: set[str] = set()

    for cur in current_changes:
        if cur.get("status") == "U":
            raise HarnessError(f"Conflicted path in working tree: {cur.get('path')}")
        path = cur.get("path")
        norm_path = _normal_rel(path) if path else ""
        if norm_path:
            current_paths.add(norm_path)
        if path:
            current_paths.add(path)

        if path not in base_map and norm_path not in base_map:
            task_changes.append(cur)
        else:
            base_entry = base_map.get(norm_path) or base_map.get(path)
            # Changed if identity, status, or old_path differ
            if base_entry:
                if (cur.get("content_identity") != base_entry.get("content_identity") or
                    cur.get("status") != base_entry.get("status") or
                    cur.get("old_path") != base_entry.get("old_path")):
                    task_changes.append(cur)

    # Add committed task changes not present in working tree changes
    for comm in committed_task_changes:
        p = comm.get("path")
        norm_p = _normal_rel(p) if p else ""
        if not norm_p:
            continue
        if norm_p not in current_paths and p not in current_paths:
            if norm_p in base_map or p in base_map:
                base_entry = base_map.get(norm_p) or base_map.get(p) or {}
                # Check for sensitive/secret marker
                if any(m in norm_p.lower() for m in SECRET_PATH_MARKERS):
                    raise ValidationError("HANDOFF_COMMIT_UNSAFE_DIRTY_BASELINE: pre-existing dirty sensitive file overlaps intended commit")
                target_p = repo / norm_p
                if target_p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".jar", ".aar", ".so", ".bin", ".gif"):
                    raise ValidationError(f"HANDOFF_DIRTY_BASE_UNPROVABLE_BINARY: cannot safely attribute binary file '{norm_p}' overlapping dirty baseline")
                # Compare committed content to baseline content
                if comm.get("content_identity") != base_entry.get("content_identity"):
                    task_changes.append(comm)
                current_paths.add(norm_p)
                if p:
                    current_paths.add(p)
            else:
                task_changes.append(comm)
                current_paths.add(norm_p)
                if p:
                    current_paths.add(p)

    # Detect disappeared dirty files (pre-existing dirty changes reverted or removed)
    for base_entry in base_changes:
        if isinstance(base_entry, dict):
            b_path = base_entry.get("path")
            b_old = base_entry.get("old_path")
        elif hasattr(base_entry, "path"):
            b_path = base_entry.path
            b_old = getattr(base_entry, "old_path", None)
        else:
            b_path = str(base_entry)
            b_old = None
        b_norm = _normal_rel(b_path) if b_path else ""
        if b_norm and b_norm not in current_paths and b_path not in current_paths:
            task_changes.append({
                "path": b_path,
                "status": "BASELINE_DIRTY_REMOVED",
                "old_path": b_old,
                "content_identity": "git:head_or_reverted",
            })

    task_changes.sort(key=lambda item: (item.get("path") or "", item.get("old_path") or "", item.get("status") or ""))
    change_identities = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in task_changes]
    manifest["task_changes"] = task_changes
    manifest["baseline_dirty_removed"] = [
        c.get("path", "") for c in task_changes if isinstance(c, dict) and c.get("status") == "BASELINE_DIRTY_REMOVED"
    ]
    manifest["task_change_set_sha256"] = canonical_sha256(change_identities)
    manifest["task_delta_mode"] = "TASK_ISOLATED"
    if task_base_head:
        manifest["task_base_head"] = task_base_head
    return manifest


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
