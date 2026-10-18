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
    read_json,
    state_root,
    sha256_bytes,
    utc_now,
    validate_id,
)


SCHEMA_VERSION = 1
ROOT_EXCLUDED = {".git", ".agents", ".harness-setup", ".harness-backup", ".harness-backups"}
NESTED_EXCLUDED = {".gradle", ".idea", "build", "out", "node_modules", "__pycache__"}
SOURCE_SUFFIXES = {
    ".kt", ".java", ".kts", ".gradle", ".groovy", ".toml", ".xml", ".json",
    ".aidl", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".m", ".mm", ".swift", ".def",
    ".pro", ".rules", ".proto", ".sq", ".sqm", ".sql", ".graphql", ".graphqls", ".gql",
    ".yaml", ".yml", ".sh", ".py", ".ps1", ".bat", ".cmd", ".bzl",
    ".bazel", ".mk", ".bp", ".cmake", ".rs", ".s", ".asm", ".lockfile",
    ".properties", ".plist", ".entitlements", ".xcprivacy", ".xcconfig", ".pbxproj", ".xcscheme",
    ".jar", ".aar", ".so", ".bin", ".png", ".jpg", ".jpeg", ".webp",
    ".gif", ".svg", ".ttf", ".otf", ".wav", ".mp3", ".ogg", ".mp4",
    ".md", ".rst", ".adoc",
}
SOURCE_SUFFIX_TUPLE = tuple(sorted(SOURCE_SUFFIXES))
ROOT_BUILD_FILES = {
    "gradlew", "gradlew.bat", "settings.gradle", "settings.gradle.kts",
    "build.gradle", "build.gradle.kts", "gradle.properties", "gradle.lockfile",
    "cmakelists.txt", "android.mk", "android.bp", "build", "build.bazel",
    "workspace", "workspace.bazel", "module.bazel",
    "podfile", "podfile.lock", "package.resolved",
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
    git_mode: str
    worktree_git_mode: str | None = None


def _normal_rel(raw: str) -> str:
    normalized = raw.replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def is_delivery_relevant(relative: str) -> bool:
    rel = _normal_rel(relative)
    lowered = rel.lower()
    parts = [part for part in lowered.strip("/").split("/") if part]
    first = parts[0] if parts else ""
    if first in ROOT_EXCLUDED or any(part in NESTED_EXCLUDED for part in parts[:-1]):
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
        marker in f"/{lowered}/" for marker in ("/res/", "/composeresources/", "/assets/", "/resources/", "/jnilibs/", "/cpp/")
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


def _working_tree_mode(path: Path, *, trust_executable_bit: bool = True) -> str:
    if path.is_symlink():
        return "120000"
    try:
        return "100755" if trust_executable_bit and path.stat().st_mode & 0o111 else "100644"
    except OSError:
        return "000000"


def _index_and_untracked(repo: Path) -> tuple[dict[str, str], dict[str, str], set[str]]:
    index: dict[str, str] = {}
    modes: dict[str, str] = {}
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
        rel = _normal_rel(raw_path.decode("utf-8", errors="surrogateescape"))
        modes[rel] = parts[0].decode("ascii")
        index[rel] = parts[1].decode("ascii")
    return index, modes, untracked


def _porcelain_changes(
    repo: Path,
    algorithm: str,
    content_cache: dict[str, str],
    index_entries: dict[str, str],
    index_modes: dict[str, str],
) -> list[ChangeEntry]:
    raw = git(repo, "status", "--porcelain=v2", "-z", "-u", "--untracked-files=all")
    chunks = raw.split(b"\0")
    entries: list[ChangeEntry] = []
    pending: list[tuple] = []
    trust_executable_bit: bool | None = None
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
        head_mode = "000000"
        index_mode = "000000"
        worktree_mode = "000000"
        xy = ".."
        divergent_mode = None
        if line.startswith("1 "):
            parts = line.split(" ", 8)
            if len(parts) < 9:
                continue
            xy, rel = parts[1], parts[8]
            head_mode, index_mode, worktree_mode = parts[3], parts[4], parts[5]
            status = "D" if "D" in xy else "A" if "A" in xy else "T" if "T" in xy else "M"
        elif line.startswith("2 "):
            parts = line.split(" ", 9)
            if len(parts) < 10:
                continue
            xy, rel = parts[1], parts[9]
            head_mode, index_mode, worktree_mode = parts[3], parts[4], parts[5]
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
        pending.append((status, rel, old_rel, head_mode, index_mode, worktree_mode, xy))

    # Hash ordinary changed files in one read-only Git invocation. Preserve clean
    # filters/EOL attributes and the existing per-file/symlink fallback.
    candidates = sorted({rel for status, rel, *_ in pending if status != "D"
                         and (repo / rel).is_file() and not (repo / rel).is_symlink()
                         and not any(ord(char) < 32 and char not in "\t\r\n" for char in rel)})
    if len(candidates) > 1:
        try:
            data = ("\n".join(json.dumps(rel, ensure_ascii=False) for rel in candidates) + "\n").encode("utf-8", errors="surrogateescape")
            hashes = git(repo, "hash-object", "--stdin-paths", input_bytes=data).decode("ascii").splitlines()
            width = hashlib.new(algorithm).digest_size * 2
            if len(hashes) == len(candidates) and all(len(oid) == width and all(c in "0123456789abcdef" for c in oid) for oid in hashes):
                content_cache.update(zip(candidates, hashes))
        except (HarnessError, UnicodeError, OSError):
            pass

    for status, rel, old_rel, head_mode, index_mode, worktree_mode, xy in pending:
        divergent_mode = None
        path = repo / rel
        if status == "D" or (not path.exists() and not path.is_symlink()):
            base_oid = index_entries.get(rel, "unknown")
            identity = f"tombstone:git:{base_oid}"
            git_mode = head_mode if head_mode != "000000" else index_modes.get(rel, "000000")
        else:
            oid = content_cache.get(rel) or _working_tree_oid(repo, rel, path, algorithm)
            if xy[:1] != "." and index_mode != "000000":
                git_mode = index_mode
            elif worktree_mode != "000000":
                git_mode = worktree_mode
            else:
                if trust_executable_bit is None:
                    trust_executable_bit = git_text(repo, "config", "--bool", "--default", "true", "--get", "core.filemode") != "false"
                git_mode = _working_tree_mode(path, trust_executable_bit=trust_executable_bit)
            if worktree_mode != "000000" and worktree_mode != git_mode:
                # Bind both staged intent and the actual tree used by gates.
                # Git's reported mode honors core.filemode=false on Windows.
                divergent_mode = worktree_mode
            if (
                status == "M"
                and xy == ".M"
                and oid == index_entries.get(rel)
                and git_mode == index_modes.get(rel)
            ):
                continue
            content_cache[rel] = oid
            identity = f"git:{oid}"
        entries.append(ChangeEntry(
            status=status,
            path=rel,
            old_path=old_rel,
            content_identity=identity,
            git_mode=git_mode,
            worktree_git_mode=divergent_mode,
        ))
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
            replacements.append(ChangeEntry(
                status="R",
                path=new.path,
                old_path=old.path,
                content_identity=new.content_identity,
                git_mode=new.git_mode,
                worktree_git_mode=new.worktree_git_mode,
            ))
    entries = [entry for entry in entries if entry not in consumed] + replacements
    return sorted(entries, key=lambda item: (item.path, item.old_path or "", item.status))


def _delivery_files(
    repo: Path,
    changes: list[ChangeEntry],
    algorithm: str,
    content_cache: dict[str, str],
    index: dict[str, str],
    index_modes: dict[str, str],
    untracked: set[str],
) -> list[dict[str, str]]:
    changed_paths = {entry.path: entry for entry in changes}
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
            git_mode = changed_paths[rel].git_mode if rel in changed_paths else _working_tree_mode(path)
            source = "working_tree"
        else:
            identity = index.get(rel)
            git_mode = index_modes.get(rel, "000000")
            source = "git_index"
        if not identity:
            raise HarnessError(f"cannot identify delivery file: {rel}")
        result.append({
            "path": rel,
            "content_identity": f"git:{identity}",
            "git_mode": git_mode,
            "source": source,
        })
        if rel in changed_paths and changed_paths[rel].worktree_git_mode:
            result[-1]["worktree_git_mode"] = changed_paths[rel].worktree_git_mode
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
    index, index_modes, untracked = _index_and_untracked(root)
    changes = _porcelain_changes(root, algorithm, content_cache, index, index_modes)
    files = _delivery_files(root, changes, algorithm, content_cache, index, index_modes, untracked)
    file_identity = [
        {
            "path": item["path"],
            "content_identity": item["content_identity"],
            "git_mode": item["git_mode"],
            **({"worktree_git_mode": item["worktree_git_mode"]} if "worktree_git_mode" in item else {}),
        }
        for item in files
    ]
    change_identity = [
        {key: value for key, value in asdict(item).items() if key != "worktree_git_mode" or value is not None}
        for item in changes
    ]
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
    validate_id(tid, "task id")
    for state_dir in (root / ".agents" / "state", root / "agents" / "state"):
        baseline_file = state_dir / "tasks" / tid / "task-baseline.json"
        try:
            baseline = read_json(baseline_file)
        except ValidationError as exc:
            if not isinstance(exc.__cause__, FileNotFoundError):
                raise ValidationError(f"task baseline unavailable: {baseline_file}") from exc
            plan_file = baseline_file.with_name("plan.json")
            if plan_file.exists():
                plan = read_json(plan_file)
                if "task_baseline" in plan:
                    raise ValidationError(f"task baseline missing: {baseline_file}; restore the original task state") from exc
            continue
        if not isinstance(baseline.get("changes"), list) or baseline.get("task_id", tid) != tid:
            raise ValidationError(f"invalid task baseline: {baseline_file}")
        if baseline.get("baseline_sha256"):
            identity = {key: baseline.get(key) for key in (
                "schema_version", "task_id", "repository", "base_delivery_snapshot_sha256", "base_change_set_sha256", "changes",
            )}
            if canonical_sha256(identity) != baseline["baseline_sha256"]:
                raise ValidationError(f"task baseline integrity mismatch: {baseline_file}")
        return baseline
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
                ["git", "diff", "--no-ext-diff", "--full-index", "--find-renames", "--ignore-cr-at-eol", "--unified=10", "HEAD", "--", *safe_paths[offset:offset+100]],
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
                    head_lines = head_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").splitlines(keepends=True)
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
            pathspec = [rel]
            old_rel = item.get("old_path")
            if old_rel and old_rel != rel:
                pathspec.append(old_rel)
            proc = subprocess.run(
                ["git", "diff", "--no-ext-diff", "--full-index", "--find-renames", "--ignore-cr-at-eol", "--unified=10", base_ref, "--", *pathspec],
                cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            if proc.stdout:
                diff_chunks.append(proc.stdout)

    return "".join(diff_chunks)


LIVE_TASK_STATUSES = frozenset({
    "AWAITING_DEVELOPER_APPROVAL",
    "APPROVED",
    "IMPLEMENTING",
    "VERIFYING",
    "BLOCKED",
    "READY_FOR_DELIVERY",
})
MAX_LIVE_TASKS = 3


class TaskConflictError(ValidationError):
    """A blocked operation with reviewable choices, never an automatic resolution."""

    def __init__(self, code: str, reason: str, task_id: str, tasks: list[dict], files: list[str] | None = None, *, repo: Path | None = None):
        options = []
        if code != "LIVE_TASK_LIMIT_REACHED":
            if tasks:
                options.append({"id": "work_in_order", "label": "Finish the task using these files first",
                                "description": "Switch to that task and follow its next step, then return here.",
                                "recommended": True, "kind": "HARNESS_COMMAND",
                                "command": f"python .agents/harness.py task status --task-id {tasks[0]['task_id']} --next --brief"})
            options.append({"id": "change_scope", "label": "Choose separate files",
                            "description": "Agree which task owns each file, then revise the affected plans and obtain approval. Different lines in one file still overlap.",
                            "recommended": not bool(tasks), "kind": "DEVELOPER_ACTION", "command": ""})
        else:
            options.append({"id": "finish_task", "label": "Finish one open task",
                            "description": "Choose a task below and follow task status --next through delivery to free a slot.",
                            "recommended": True, "kind": "DEVELOPER_ACTION", "command": ""})
        if repo is not None:
            from task_merge import conflict_merge_option
            options.append(conflict_merge_option(repo, task_id, tasks, limit=code == "LIVE_TASK_LIMIT_REACHED"))
        options.extend([
            {"id": "cancel_task", "label": "Cancel a task you no longer need",
             "description": "Only on your explicit choice, use workflow.py cancel for the selected task. Its local files stay in place; cancellation does not discard edits.",
             "kind": "DEVELOPER_ACTION", "command": ""},
            {"id": "separate_worktree", "label": "Use a separate worktree",
             "description": "Create a separate worktree yourself for independent work on the same files, then review conflicts when integrating it.",
             "kind": "DEVELOPER_ACTION", "command": ""},
        ])
        self.details = {"code": code, "task_id": task_id, "reason": reason,
                        "conflicting_files": files or [], "tasks": tasks, "options": options}
        roster = "\n".join(f"- {task['task_id']} ({task['status']}): {' '.join(str(task.get('outcome') or '').split())[:160]}"
                           for task in tasks)
        choices = "\n".join(f"{index}. {option['label']}{' (recommended)' if option.get('recommended') else ''}{' (unavailable)' if option.get('available') is False else ''}: {option['description']}"
                            + (f"\n   Next step: {option['command']}" if option.get("command") else "")
                            for index, option in enumerate(options, 1))
        super().__init__(f"{code}: {reason}" + (f"\nAffected tasks:\n{roster}" if roster else "") + f"\nAvailable choices:\n{choices}")


def _iter_state_dirs(repo: Path) -> list[Path]:
    directory = state_root(repo.resolve())
    return [directory] if directory.is_dir() else []


def _load_task_plan_dict(repo: Path, task_id: str) -> dict | None:
    for sdir in _iter_state_dirs(repo):
        pfile = sdir / "tasks" / task_id / "plan.json"
        if pfile.is_file():
            try:
                data = json.loads(pfile.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception as exc:
                raise ValidationError(f"TASK_STATE_INVALID: cannot load task '{task_id}'") from exc
    return None


def task_owned_files(repo: Path, task_id: str, plan: dict | None = None) -> set[str]:
    """Return normalized repo-relative paths declared or verified as owned by task_id."""
    if plan is None and task_id:
        plan = _load_task_plan_dict(repo, task_id)
    if not isinstance(plan, dict):
        return set()
    owned: set[str] = set()
    for f in plan.get("expected_files") or []:
        if str(f).strip():
            owned.add(_normal_rel(str(f).strip()))
    for phase in plan.get("phases") or []:
        if isinstance(phase, dict):
            for f in phase.get("expected_files") or []:
                if str(f).strip():
                    owned.add(_normal_rel(str(f).strip()))
    for sdir in _iter_state_dirs(repo):
        tdir = sdir / "tasks" / task_id
        if not tdir.is_dir():
            continue
        manifest_candidates: list[Path] = []
        ready_run = str(plan.get("ready_run_id") or "").strip()
        if ready_run:
            validate_id(ready_run, "run id")
            manifest_candidates.append(tdir / f"manifest-{ready_run}.json")
        for mfile in manifest_candidates:
            if mfile.is_file():
                try:
                    mdata = json.loads(mfile.read_text(encoding="utf-8"))
                    if any(mdata.get(field) != plan.get(plan_field) for field, plan_field in (
                        ("delivery_snapshot_sha256", "ready_delivery_snapshot_sha256"),
                        ("change_set_sha256", "ready_change_set_sha256"),
                    )):
                        raise ValidationError("ready task manifest binding mismatch")
                    tchanges = mdata.get("task_changes") if "task_changes" in mdata else []
                    for item in tchanges or []:
                        if isinstance(item, dict) and item.get("status") != "BASELINE_DIRTY_REMOVED":
                            for key in ("path", "old_path"):
                                val = str(item.get(key) or "").strip()
                                if val:
                                    owned.add(_normal_rel(val))
                except Exception as exc:
                    raise ValidationError(f"TASK_STATE_INVALID: invalid ready manifest for '{task_id}'") from exc
    return {p for p in owned if p}


def live_task_plans(repo: Path) -> list[tuple[str, dict, Path]]:
    """One state root and one roster for lifecycle, guards and diff isolation."""
    result = []
    for sdir in _iter_state_dirs(repo):
        if (sdir / "task-merge-pending.json").exists():
            raise ValidationError("TASK_MERGE_RECOVERY_REQUIRED: repeat the recorded task merge --apply command to finish the interrupted consolidation; project writes remain blocked.")
        directory = sdir / "tasks"
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*/plan.json")):
            plan = read_json(path)
            if plan.get("status") in LIVE_TASK_STATUSES:
                if plan.get("task_id") != path.parent.name:
                    raise ValidationError("TASK_STATE_INVALID: task directory identity mismatch")
                result.append((path.parent.name, plan, path))
    return result


def assert_disjoint_task_scope(repo: Path, task_id: str, plan: dict, *, exclude_task_ids: tuple[str, ...] = ()) -> None:
    """Concurrent tasks reserve explicit files; broad/unknown scopes fail closed."""
    others = [(tid, other) for tid, other, _ in live_task_plans(repo) if tid != task_id and tid not in exclude_task_ids]
    task_choices = [{"task_id": tid, "status": other.get("status"), "outcome": other.get("requested_outcome", ""),
                     "status_command": f"python .agents/harness.py task status --task-id {tid} --next --brief"}
                    for tid, other in others]
    if len(others) >= MAX_LIVE_TASKS:
        raise TaskConflictError("LIVE_TASK_LIMIT_REACHED", f"All {MAX_LIVE_TASKS} live-task slots are occupied. Switching focus does not free a slot.", task_id, task_choices, repo=repo)
    if not others:
        return
    from _vnext_common import validate_repo_path_containment
    from plan_authority import validate_plan_hash

    def scope(tid: str, data: dict) -> set[str]:
        paths = task_owned_files(repo, tid, data)
        if not paths:
            raise TaskConflictError("ACTIVE_TASK_CONFLICT", f"Task '{tid}' needs explicit expected files for shared-worktree execution.", task_id, task_choices, repo=repo)
        normalized = set()
        for rel in paths:
            if any(c in rel for c in "*?[") or (repo / rel).is_dir():
                raise TaskConflictError("ACTIVE_TASK_CONFLICT", f"Task '{tid}' has a broad file scope: {rel}", task_id, task_choices, [rel], repo=repo)
            clean = validate_repo_path_containment(repo, rel)
            normalized.add(os.path.normcase(clean).replace("\\", "/"))
        return normalized

    own = scope(task_id, plan)
    for tid, other in others:
        theirs = scope(tid, other)
        overlap = sorted(a for a in own for b in theirs if a == b or a.startswith(b + "/") or b.startswith(a + "/"))
        if overlap:
            raise TaskConflictError("ACTIVE_TASK_CONFLICT", f"Tasks '{task_id}' and '{tid}' need the same files: {', '.join(overlap)}.",
                                    task_id, [item for item in task_choices if item["task_id"] == tid], overlap, repo=repo)
        if not validate_plan_hash(other)[0]:
            raise ValidationError(f"TASK_STATE_INVALID: plan hash mismatch for '{tid}'")


def disjoint_sibling_file_sets(
    repo: Path,
    task_id: str | None,
    plan: dict | None = None,
    expected_files: list[str] | set[str] | None = None,
) -> tuple[set[str], set[str]]:
    """Return (live_sibling_files, committed_sibling_files) for strictly disjoint sibling tasks."""
    if not task_id:
        return set(), set()
    own_plan = plan if isinstance(plan, dict) else _load_task_plan_dict(repo, task_id)
    own_expected: set[str] = set()
    if expected_files:
        for f in expected_files:
            if str(f).strip():
                own_expected.add(_normal_rel(str(f).strip()))
    if own_plan:
        own_expected |= task_owned_files(repo, task_id, own_plan)
    if not own_expected:
        return set(), set()

    own_created = str((own_plan or {}).get("created_at") or "")
    own_base_head = str(
        (own_plan or {}).get("task_base_head")
        or ((own_plan or {}).get("repository") or {}).get("head")
        or ""
    )

    live_sibling_files: set[str] = set()
    committed_sibling_files: set[str] = set()
    seen_tasks: set[str] = set()

    for sdir in _iter_state_dirs(repo):
        tasks_dir = sdir / "tasks"
        if not tasks_dir.is_dir():
            continue
        for sub in sorted(tasks_dir.iterdir()):
            if not sub.is_dir() or sub.name == task_id or sub.name in seen_tasks:
                continue
            pfile = sub / "plan.json"
            if not pfile.is_file():
                continue
            seen_tasks.add(sub.name)
            try:
                other_plan = json.loads(pfile.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValidationError(f"TASK_STATE_INVALID: cannot load sibling '{sub.name}'") from exc
            if not isinstance(other_plan, dict):
                continue
            other_status = str(other_plan.get("status") or "").upper()
            if other_status == "CANCELLED":
                continue
            other_files = task_owned_files(repo, sub.name, other_plan)
            if not other_files or (other_files & own_expected):
                continue
            from plan_authority import validate_plan_hash
            if not validate_plan_hash(other_plan)[0]:
                raise ValidationError(f"TASK_STATE_INVALID: sibling plan hash mismatch for '{sub.name}'")
            if other_status in LIVE_TASK_STATUSES:
                live_sibling_files.update(other_files)
            if other_status == "READY_FOR_DELIVERY":
                committed_sibling_files.update(other_files)
            elif other_status == "DELIVERED":
                other_delivered_at = str(other_plan.get("delivered_at") or other_plan.get("ready_at") or "")
                other_base_head = str(
                    other_plan.get("task_base_head")
                    or (other_plan.get("repository") or {}).get("head")
                    or ""
                )
                if (
                    not own_created
                    or (other_delivered_at and other_delivered_at >= own_created)
                    or (own_base_head and other_base_head == own_base_head)
                ):
                    committed_sibling_files.update(other_files)

    return live_sibling_files, committed_sibling_files


def is_disjoint_sibling_change(change: dict, sibling_files: set[str]) -> bool:
    """Exclude a sibling change only when both ends stay inside its scope."""
    paths = {_normal_rel(str(change[key])) for key in ("path", "old_path") if change.get(key)}
    if paths & sibling_files:
        if not paths <= sibling_files:
            raise TaskConflictError("ACTIVE_TASK_CONFLICT", "A rename crosses task file ownership.", "", [], sorted(paths))
        return True
    return False


def build_task_manifest(
    repo: Path,
    baseline: dict | list | str | None = None,
    expected_files: list[str] | set[str] | None = None,
    task_base_head: str | None = None,
    *,
    live_manifest: dict | None = None,
) -> dict:
    manifest = dict(live_manifest) if live_manifest is not None else build_manifest(repo)
    task_id: str | None = None
    pdata: dict | None = None
    plan_defaults = False
    if isinstance(baseline, str):
        task_id = baseline
        baseline = load_task_baseline(repo, task_id)
        plan_defaults = True
    elif isinstance(baseline, dict) and baseline.get("task_id"):
        task_id = str(baseline.get("task_id") or "").strip() or None

    if task_id:
        pdata = _load_task_plan_dict(repo, task_id)
        if plan_defaults and isinstance(pdata, dict):
            if task_base_head is None:
                task_base_head = pdata.get("task_base_head") or (pdata.get("repository") or {}).get("head")
            if expected_files is None:
                expected_files = pdata.get("expected_files")

    if task_base_head is None and isinstance(baseline, dict):
        task_base_head = baseline.get("task_base_head") or (baseline.get("repository") or {}).get("head")

    live_sibling_files, committed_sibling_files = disjoint_sibling_file_sets(
        repo, task_id, plan=pdata, expected_files=expected_files
    )
    all_sibling_files = live_sibling_files | committed_sibling_files

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
                        if is_delivery_relevant(p) or (old_p and is_delivery_relevant(old_p)):
                            target_p = repo / p
                            if target_p.is_file() or target_p.is_symlink():
                                raw_oid = git(repo, "hash-object", "--path", p, "--stdin", input_bytes=_path_bytes(target_p)).decode("utf-8").strip()
                                oid = f"git:{raw_oid}"
                                tree_entry = git_text(repo, "ls-tree", current_head, "--", p).split()
                                git_mode = tree_entry[0] if tree_entry else _working_tree_mode(target_p)
                            else:
                                try:
                                    base_path = old_p or p
                                    base_blob = git_text(repo, "rev-parse", f"{task_base_head}:{base_path}").strip()
                                    oid = f"tombstone:git:{base_blob}"
                                except Exception:
                                    oid = "tombstone:git:unknown"
                                try:
                                    tree_entry = git_text(repo, "ls-tree", task_base_head, "--", old_p or p).split()
                                    git_mode = tree_entry[0] if tree_entry else "000000"
                                except Exception:
                                    git_mode = "000000"
                            committed_task_changes.append({
                                "status": stat,
                                "path": _normal_rel(p),
                                "old_path": _normal_rel(old_p) if old_p else None,
                                "content_identity": oid,
                                "git_mode": git_mode,
                            })
        except Exception:
            pass

    if baseline is None:
        all_changes = [
            c for c in (manifest.get("changes") or [])
            if not is_disjoint_sibling_change(c, live_sibling_files)
        ]
        cur_paths = {_normal_rel(c.get("path") or "") for c in all_changes if c.get("path")}
        for comm in committed_task_changes:
            cpath = _normal_rel(comm.get("path") or "")
            if cpath and not is_disjoint_sibling_change(comm, committed_sibling_files) and cpath not in cur_paths:
                all_changes.append(comm)
                cur_paths.add(cpath)
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
        if is_disjoint_sibling_change(cur, live_sibling_files):
            continue

        if path not in base_map and norm_path not in base_map:
            task_changes.append(cur)
        else:
            base_entry = base_map.get(norm_path) or base_map.get(path)
            # Changed if identity, status, or old_path differ
            if base_entry:
                if (cur.get("content_identity") != base_entry.get("content_identity") or
                    cur.get("status") != base_entry.get("status") or
                    cur.get("old_path") != base_entry.get("old_path") or
                    ("git_mode" in base_entry and cur.get("git_mode") != base_entry.get("git_mode")) or
                    cur.get("worktree_git_mode") != base_entry.get("worktree_git_mode")):
                    task_changes.append(cur)

    # Add committed task changes not present in working tree changes
    for comm in committed_task_changes:
        p = comm.get("path")
        norm_p = _normal_rel(p) if p else ""
        if not norm_p:
            continue
        if is_disjoint_sibling_change(comm, committed_sibling_files):
            current_paths.add(norm_p)
            if p:
                current_paths.add(p)
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
        if b_norm in all_sibling_files:
            continue
        if b_norm and b_norm not in current_paths and b_path not in current_paths:
            task_changes.append({
                "path": b_path,
                "status": "BASELINE_DIRTY_REMOVED",
                "old_path": b_old,
                "content_identity": "git:head_or_reverted",
                "git_mode": base_entry.get("git_mode", "000000") if isinstance(base_entry, dict) else "000000",
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
