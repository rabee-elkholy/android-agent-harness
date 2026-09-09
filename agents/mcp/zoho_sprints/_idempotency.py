"""Crash-safe idempotency ledger for explicit Zoho mutations."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable


def ledger_path() -> Path:
    override = os.environ.get("ANDROID_HARNESS_ZOHO_LEDGER", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".android-harness" / "zoho_operations.json"


def operation_hash(tool: str, arguments: dict) -> str:
    payload = {"tool": tool, "arguments": {k: v for k, v in arguments.items() if k != "operation_id"}}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".zoho-ops-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _read(path: Path) -> dict:
    if not path.is_file():
        return {"schema_version": 1, "operations": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Zoho idempotency ledger is unreadable; refusing mutation") from exc
    if not isinstance(data, dict) or not isinstance(data.get("operations"), dict):
        raise RuntimeError("Zoho idempotency ledger has an invalid schema; refusing mutation")
    return data


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return pid > 0
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


@contextmanager
def _ledger_lock(path: Path):
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 10.0
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(str(os.getpid()))
                handle.flush()
                os.fsync(handle.fileno())
            break
        except FileExistsError:
            try:
                owner = int(lock.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                # The creator may have opened the lock but not flushed its PID
                # yet. Preserve a fresh lock, but recover a corrupt stale one.
                try:
                    fresh = (time.time() - lock.stat().st_mtime) < 2.0
                except OSError:
                    fresh = False
                if not fresh:
                    lock.unlink(missing_ok=True)
                    continue
                owner = os.getpid()
            if not _pid_alive(owner):
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError("Zoho idempotency ledger is busy; retry later")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            if int(lock.read_text(encoding="ascii").strip()) == os.getpid():
                lock.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def execute_once(tool: str, arguments: dict, operation: Callable[[], dict]) -> dict:
    operation_id = str(arguments.get("operation_id") or "").strip()
    if not operation_id:
        # Backward-compatible interface. The vNext workflow always supplies an
        # operation id; legacy direct callers retain their previous behavior.
        return operation()
    if len(operation_id) > 128 or not all(char.isalnum() or char in "-_." for char in operation_id):
        raise RuntimeError("operation_id must be 1-128 safe identifier characters")
    path = ledger_path()
    digest = operation_hash(tool, arguments)
    with _ledger_lock(path):
        data = _read(path)
        existing = data["operations"].get(operation_id)
        if existing:
            if existing.get("operation_sha256") != digest:
                raise RuntimeError("operation_id was already used for different Zoho content")
            if existing.get("status") == "COMPLETED":
                return existing.get("result") or {}
            raise RuntimeError("previous Zoho mutation outcome is unknown; inspect the item before retrying")
        data["operations"][operation_id] = {
            "tool": tool, "operation_sha256": digest, "status": "PENDING", "started_at_epoch": int(time.time()),
        }
        _write(path, data)
        # Keep the lock over the network mutation. This serializes writes and
        # prevents two processes from issuing the same request concurrently.
        result = operation()
        data = _read(path)
        record = data["operations"].get(operation_id) or {}
        if record.get("operation_sha256") != digest:
            raise RuntimeError("Zoho idempotency ledger changed during mutation")
        record.update({"status": "COMPLETED", "result": result, "completed_at_epoch": int(time.time())})
        data["operations"][operation_id] = record
        completed = [(key, value) for key, value in data["operations"].items() if value.get("status") == "COMPLETED"]
        if len(completed) > 500:
            for key, _ in sorted(completed, key=lambda item: item[1].get("completed_at_epoch", 0))[:-500]:
                data["operations"].pop(key, None)
        _write(path, data)
        return result
