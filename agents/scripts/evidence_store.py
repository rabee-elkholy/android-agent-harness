"""Append-only, snapshot-scoped evidence storage with bounded locking and redaction."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from contextlib import AbstractContextManager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import (  # noqa: E402
    ValidationError,
    atomic_write_json,
    bounded_path,
    canonical_sha256,
    read_json,
    redact,
    utc_now,
    validate_id,
)


SCHEMA_VERSION = 1
VALID_STATUSES = {
    "PASS", "FAIL", "ENV", "BLOCKED", "STALE", "PENDING", "SKIPPED",
    "REVIEW_NOT_REQUIRED_BY_POLICY", "USER_DECISION_REQUIRED", "EMERGENCY_UNVERIFIED",
}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_marker(pid: int) -> str:
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        parts = proc_stat.read_text(encoding="utf-8", errors="replace").split()
        return parts[21] if len(parts) > 21 else ""
    except OSError:
        return ""


class StateLock(AbstractContextManager):
    """Short-lived lock that never evicts a demonstrably live owner by age."""

    def __init__(self, state_root: Path, timeout_seconds: float = 5.0):
        self.path = state_root / ".write.lock"
        self.timeout_seconds = timeout_seconds
        self.acquired = False

    def _owner_live(self) -> bool:
        try:
            owner = read_json(self.path)
            pid = int(owner.get("pid") or 0)
            marker = str(owner.get("process_marker") or "")
            if not _pid_alive(pid):
                return False
            current = _process_marker(pid)
            return not (marker and current and marker != current)
        except (ValidationError, ValueError, TypeError):
            # A just-created lock can be observed before its JSON payload has
            # been flushed. Treat recent unreadable locks as owned instead of
            # racing to unlink another writer's lock.
            try:
                return (time.time() - self.path.stat().st_mtime) < max(2.0, self.timeout_seconds)
            except OSError:
                return False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            payload = {
                "pid": os.getpid(),
                "process_marker": _process_marker(os.getpid()),
                "created_at": utc_now(),
                "nonce": uuid.uuid4().hex,
            }
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                self.acquired = True
                return self
            except FileExistsError:
                if not self._owner_live():
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise ValidationError("state lock is owned by a live process")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb):
        if self.acquired:
            try:
                owner = read_json(self.path)
                if int(owner.get("pid") or 0) == os.getpid():
                    self.path.unlink(missing_ok=True)
            except (ValidationError, OSError, ValueError, TypeError):
                pass
        self.acquired = False
        return False


class EvidenceStore:
    def __init__(self, state_root: Path):
        self.state_root = state_root.resolve()
        self.runs_root = self.state_root / "runs"

    def run_dir(self, snapshot: str, run_id: str) -> Path:
        snapshot = validate_id(snapshot, "delivery snapshot")
        run_id = validate_id(run_id, "run id")
        return bounded_path(self.runs_root, Path(snapshot) / run_id)

    def write(
        self,
        *,
        snapshot: str,
        run_id: str,
        name: str,
        producer: str,
        harness_version: str,
        change_set: str,
        status: str,
        evidence: dict,
    ) -> Path:
        name = validate_id(name, "artifact name")
        producer = validate_id(producer, "producer")
        status = str(status).upper()
        if status not in VALID_STATUSES:
            raise ValidationError(f"invalid artifact status: {status}")
        run_dir = self.run_dir(snapshot, run_id)
        target = bounded_path(run_dir, f"{name}.json")
        record = {
            "schema_version": SCHEMA_VERSION,
            "artifact": name,
            "producer": producer,
            "harness_version": str(harness_version),
            "delivery_snapshot_sha256": snapshot,
            "change_set_sha256": str(change_set),
            "run_id": run_id,
            "created_at": utc_now(),
            "status": status,
            "evidence": redact(evidence),
        }
        record["artifact_sha256"] = canonical_sha256(record)
        with StateLock(self.state_root):
            if target.exists():
                raise ValidationError(f"append-only artifact already exists: {target.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=str(target.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(record, handle, ensure_ascii=False, indent=2, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, target)
            finally:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
        return target

    def read(self, snapshot: str, run_id: str, name: str) -> dict:
        name = validate_id(name, "artifact name")
        record = read_json(bounded_path(self.run_dir(snapshot, run_id), f"{name}.json"))
        stored = str(record.pop("artifact_sha256", ""))
        actual = canonical_sha256(record)
        record["artifact_sha256"] = stored
        if not stored or stored != actual:
            raise ValidationError(f"artifact integrity mismatch: {name}")
        if record.get("delivery_snapshot_sha256") != snapshot or record.get("run_id") != run_id:
            raise ValidationError(f"artifact identity mismatch: {name}")
        return record

    def prune(self, *, keep: int = 50, protected: set[tuple[str, str]] | None = None) -> list[Path]:
        """Remove only complete, unprotected old run directories."""
        protected = protected or set()
        run_dirs = [path for snap in self.runs_root.glob("*") if snap.is_dir() for path in snap.glob("*") if path.is_dir()]
        run_dirs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        removed: list[Path] = []
        for run_dir in run_dirs[max(0, keep):]:
            key = (run_dir.parent.name, run_dir.name)
            if key in protected or (run_dir / ".active").exists():
                continue
            for child in sorted(run_dir.rglob("*"), reverse=True):
                if child.is_symlink() or child.is_file():
                    child.unlink(missing_ok=True)
                elif child.is_dir():
                    child.rmdir()
            run_dir.rmdir()
            removed.append(run_dir)
        return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    record = EvidenceStore(Path(args.state_root)).read(args.snapshot, args.run_id, args.name)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
