"""Shared, zero-dependency primitives for the vNext harness core."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SECRET_KEY = re.compile(r"(?i)(token|secret|password|passwd|authorization|api[_-]?key|private[_-]?key)")
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?im)([\"']?\b(?:token|secret|password|passwd|api[_-]?key|authorization|private[_-]?key|"
        r"storepassword|keypassword)\b[\"']?\s*[:=]\s*)(?:[\"'][^\r\n\"']*[\"']|[^\s,;#]+)"
    ),
    re.compile(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"(?i)(https?://[^\s/:@]+:)[^\s/@]+(@)"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class HarnessError(RuntimeError):
    """Base class for deterministic harness failures."""


class ValidationError(HarnessError):
    """Raised when an artifact or path violates a declared contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def validate_id(value: str, label: str = "identifier") -> str:
    candidate = str(value or "").strip()
    if not SAFE_ID.fullmatch(candidate):
        raise ValidationError(f"invalid {label}: {candidate!r}")
    return candidate


def bounded_path(root: Path, relative: str | Path, *, reject_symlink_parents: bool = True) -> Path:
    root_resolved = root.resolve()
    raw = Path(relative)
    if raw.is_absolute():
        raise ValidationError(f"absolute path is not allowed: {relative}")
    candidate = root_resolved / raw
    if reject_symlink_parents:
        current = root_resolved
        for part in raw.parts[:-1]:
            if part in ("", "."):
                continue
            if part == "..":
                raise ValidationError(f"path traversal is not allowed: {relative}")
            current = current / part
            if current.is_symlink():
                raise ValidationError(f"symlink parent is not allowed: {relative}")
    resolved_parent = candidate.parent.resolve()
    if resolved_parent != root_resolved and root_resolved not in resolved_parent.parents:
        raise ValidationError(f"path escapes root: {relative}")
    return candidate


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON artifact must be an object: {path}")
    return value


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            input=input_bytes,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise HarnessError(f"cannot execute Git: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise HarnessError(f"git {' '.join(args)} failed: {detail[:500]}")
    return proc.stdout or b""


def git_text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode("utf-8", errors="replace").strip()


def _norm_path_str(p: Path) -> str:
    resolved = str(p.resolve())
    return os.path.normcase(resolved) if os.name == "nt" else resolved


def repository_identity(repo: Path) -> dict[str, str]:
    identity_lines = git_text(repo, "rev-parse", "--show-toplevel", "--git-common-dir", "HEAD").splitlines()
    if len(identity_lines) != 3:
        raise HarnessError("cannot resolve repository identity")
    root = Path(identity_lines[0]).resolve()
    common = Path(identity_lines[1])
    if not common.is_absolute():
        common = (root / common).resolve()
    head = identity_lines[2]
    try:
        proc = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=str(root), capture_output=True, text=True, check=False,
        )
        branch = proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "DETACHED"
    except OSError as exc:
        raise HarnessError(f"cannot execute Git: {exc}") from exc
    return {
        "root_sha256": sha256_bytes(_norm_path_str(root).encode("utf-8")),
        "git_common_dir_sha256": sha256_bytes(_norm_path_str(common).encode("utf-8")),
        "head": head,
        "branch": branch,
    }
def redact(value: Any) -> Any:
    """Recursively redact secret-shaped keys without serializing raw values."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SECRET_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    """Redact secret-shaped values while retaining useful diff structure.

    Review packages contain free-form source diffs, so dictionary-key
    redaction alone is insufficient.  The replacement callback preserves a
    detected assignment key (and URL username) while removing only the secret
    value.  This keeps line numbers and surrounding build context reviewable.
    """
    result = str(value)
    for pattern in SECRET_VALUE_PATTERNS:
        def replace(match: re.Match[str]) -> str:
            if match.lastindex == 1:
                return f"{match.group(1)}[REDACTED]"
            if match.lastindex == 2:
                return f"{match.group(1)}[REDACTED]{match.group(2)}"
            return "[REDACTED]"
        result = pattern.sub(replace, result)
    return result


def _reject_cross_platform_absolute_path(raw_path: str) -> None:
    raw = str(raw_path or "").strip()
    if not raw:
        raise ValidationError("empty path is invalid")

    normalized = raw.replace("\\", "/")
    lower = raw.lower()

    win = PureWindowsPath(raw)
    posix = PurePosixPath(normalized)

    # Windows drive absolute and drive-relative paths.
    if win.drive:
        raise ValidationError(f"foreign/drive path is not allowed: {raw_path}")

    # POSIX absolute.
    if posix.is_absolute():
        raise ValidationError(f"absolute path is not allowed: {raw_path}")

    # UNC.
    if raw.startswith("\\\\") or normalized.startswith("//"):
        raise ValidationError(f"UNC/network path is not allowed: {raw_path}")

    # Windows extended/device namespace.
    if lower.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        raise ValidationError(f"Windows device path is not allowed: {raw_path}")


def validate_repo_path_containment(repo: Path, raw_path: str | Path) -> str:
    if not raw_path:
        raise ValidationError("empty path is invalid")

    raw_str = str(raw_path).strip()
    if not raw_str:
        raise ValidationError("empty path is invalid")

    _reject_cross_platform_absolute_path(raw_str)

    normalized = raw_str.replace("\\", "/")
    normalized_parts = PurePosixPath(normalized).parts

    if ".." in normalized_parts:
        raise ValidationError(f"path traversal forbidden: {raw_path}")

    repo_resolved = Path(os.path.realpath(str(repo))).resolve()
    relative_host_path = Path(*normalized_parts)
    target = Path(
        os.path.realpath(str(repo_resolved / relative_host_path))
    ).resolve()

    try:
        rel = target.relative_to(repo_resolved)
    except ValueError:
        raise ValidationError(f"path escapes repository: {raw_path}")

    rel_posix = rel.as_posix()
    if rel_posix == "." or not rel_posix:
        raise ValidationError(
            f"path cannot point to repository root: {raw_path}"
        )
    return rel_posix


def state_root(repo: Path) -> Path:
    override = os.environ.get("HARNESS_STATE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    installed = repo / ".agents" / "state"
    return installed if (repo / ".agents").is_dir() else repo / "agents" / "state"


def active_review_package_path(repo: Path, current_run: dict[str, Any], root: Path | None = None) -> Path:
    run_id = str(current_run.get("run_id") or "").strip()
    snapshot = str(current_run.get("delivery_snapshot_sha256") or "").strip()
    if not snapshot and current_run.get("manifest"):
        try:
            m = read_json(Path(current_run["manifest"]))
            snapshot = str(m.get("delivery_snapshot_sha256") or "").strip()
        except Exception:
            pass
    base = root if root is not None else state_root(repo)
    canonical = base / "runs" / snapshot / run_id / "review-package.md"
    if not canonical.is_file() and current_run.get("review_package"):
        candidate = Path(str(current_run["review_package"]))
        if candidate.is_file():
            return candidate
    return canonical
