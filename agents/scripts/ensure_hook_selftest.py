"""Run hook selftest when harness files change. Cached by content hash.

CLI:  python .agents/scripts/ensure_hook_selftest.py
Hook: PreInvocation — stdout is JSON only.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _live_process import enable_line_buffered_stdio, run_streaming  # type: ignore
except ImportError:
    def enable_line_buffered_stdio() -> None:
        pass
    def run_streaming(argv, cwd=None, env=None, label="cmd", echo=True):  # type: ignore
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, check=False)
        return proc.returncode, proc.stdout + proc.stderr, []

AGENTS = Path(__file__).resolve().parent.parent
SCRIPTS = AGENTS / "scripts"
SELFTEST = SCRIPTS / "_hook_selftest.py"
CACHE = AGENTS / "state" / "hook_selftest.json"
_fingerprint_files: dict = {}


def _iter_watched() -> list[Path]:
    files: list[Path] = []
    files.extend(sorted(SCRIPTS.rglob("*.py")))
    files.extend(sorted((AGENTS / "harness_shared").rglob("*.py")))
    files.extend(sorted((AGENTS / "subagents").glob("*.json")))
    for extra in (AGENTS / "hooks.json", AGENTS / "harness.py"):
        if extra.is_file():
            files.append(extra)
    return [p for p in files if p.is_file()]


def harness_fingerprint() -> str:
    # This is an advisory selftest scheduling cache, never verification proof.
    # Include ctime/inode to detect replacement and same-size restored-mtime edits.
    global _fingerprint_files
    previous = _read_cache().get("files") or {}
    if not isinstance(previous, dict):
        previous = {}
    current = {}
    digest = hashlib.sha256()
    for path in _iter_watched():
        stat = path.stat()
        signature = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino]
        key = path.as_posix()
        cached = previous.get(key) or {}
        content_hash = cached.get("sha256") if isinstance(cached, dict) and cached.get("signature") == signature else None
        if not isinstance(content_hash, str) or len(content_hash) != 64 or any(c not in "0123456789abcdef" for c in content_hash):
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        current[key] = {"signature": signature, "sha256": content_hash}
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\0")
    _fingerprint_files = current
    return digest.hexdigest()


def _read_cache() -> dict:
    try:
        if not CACHE.is_file():
            return {}
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(fingerprint: str, ok: bool) -> None:
    from _vnext_common import atomic_write_json
    atomic_write_json(CACHE, {"fingerprint": fingerprint, "ok": ok, "files": _fingerprint_files})


def cache_is_fresh(fingerprint: str) -> bool:
    cache = _read_cache()
    return cache.get("fingerprint") == fingerprint and cache.get("ok") is True


def run_selftest(echo: bool = False) -> tuple[bool, str]:
    if os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") == "1":
        return True, "already running inside selftest"
    env = os.environ.copy()
    env["HARNESS_HOOK_SELFTEST_ACTIVE"] = "1"
    env.pop("HARNESS_HOOK_STATE", None)
    env.pop("HARNESS_TRANSCRIPT_ROOT", None)
    code, raw_log, _ = run_streaming(
        [sys.executable, str(SELFTEST)],
        cwd=str(AGENTS.parent),
        env=env,
        label="hook-selftest",
        echo=echo,
    )
    return code == 0, raw_log


def _is_hook_payload(raw: str) -> bool:
    if not raw.strip():
        return False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return any(
        key in payload
        for key in ("conversationId", "conversation_id", "invocationNum", "toolCall")
    )


def _read_stdin_safe(timeout_sec: float = 0.1) -> str:
    """Read stdin safely without hanging indefinitely when run as a background task.

    - If explicit CLI flags (--cli, -c) are given, returns empty string (CLI mode).
    - If explicit --hook flag is given, reads stdin synchronously.
    - If stdin is a TTY, returns empty string immediately (interactive terminal CLI).
    - If stdin is a pipe, reads in a worker thread with a brief timeout so background
      pipes with open stdin descriptors never block execution.
    """
    if "--cli" in sys.argv or "-c" in sys.argv:
        return ""
    if "--hook" in sys.argv:
        return sys.stdin.read()
    if sys.stdin.isatty():
        return ""

    buf: list[str] = []

    def _reader() -> None:
        try:
            buf.append(sys.stdin.read())
        except Exception:
            pass

    t = threading.Thread(target=_reader, name="harness-stdin-reader", daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    return buf[0] if buf else ""


def _running_lock_path() -> Path:
    return CACHE.with_name("hook_selftest.running.json")


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _is_background_running(max_age_sec: float = 300.0) -> bool:
    import time
    lock_file = _running_lock_path()
    try:
        if not lock_file.is_file():
            return False
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False
        started = float(data.get("started_at") or 0.0)
        if time.time() - started > max_age_sec:
            return False
        pid = int(data.get("pid") or 0)
        return _is_pid_alive(pid)
    except Exception:
        return False


def _write_running_lock(pid: int, fingerprint: str) -> None:
    import time
    from _vnext_common import atomic_write_json
    try:
        atomic_write_json(_running_lock_path(), {"pid": pid, "fingerprint": fingerprint, "started_at": time.time()})
    except Exception:
        pass


def _clear_running_lock() -> None:
    try:
        _running_lock_path().unlink(missing_ok=True)
    except Exception:
        pass


def _spawn_background_selftest(fingerprint: str) -> bool:
    if _is_background_running():
        return False
    env = os.environ.copy()
    env.pop("HARNESS_HOOK_STATE", None)
    env.pop("HARNESS_TRANSCRIPT_ROOT", None)
    kwargs: dict = {
        "cwd": str(AGENTS.parent),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--cli", "--background-worker"],
            **kwargs,
        )
        _write_running_lock(proc.pid, fingerprint)
        return True
    except Exception:
        return False


def seed_cache_for_agents(agents_dir: Path, *, ok: bool = True) -> None:
    """Seed hook_selftest.json for an installed .agents directory after verified install/update."""
    global AGENTS, SCRIPTS, SELFTEST, CACHE
    prev = (AGENTS, SCRIPTS, SELFTEST, CACHE)
    try:
        AGENTS = agents_dir.resolve()
        SCRIPTS = AGENTS / "scripts"
        SELFTEST = SCRIPTS / "_hook_selftest.py"
        CACHE = AGENTS / "state" / "hook_selftest.json"
        fp = harness_fingerprint()
        _write_cache(fp, ok)
    finally:
        AGENTS, SCRIPTS, SELFTEST, CACHE = prev


def _failure_hook_response() -> str:
    try:
        import _product
        prod_name = getattr(_product, "PRODUCT_NAME", getattr(_product, "PRODUCT", "App"))
    except Exception:
        prod_name = "App"
    return json.dumps(
        {
            "injectSteps": [
                {
                    "ephemeralMessage": (
                        f"{prod_name} hook selftest FAILED after a harness change. "
                        "Do not assemble. Run `python .agents/scripts/_hook_selftest.py` "
                        "and fix the failures before delivery."
                    )
                }
            ]
        }
    )


def main() -> int:
    enable_line_buffered_stdio()
    if os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") == "1":
        print("[OK] Hook selftest already running (recursion guard).", flush=True)
        return 0
    raw = _read_stdin_safe()
    as_hook = _is_hook_payload(raw)

    fingerprint = harness_fingerprint()
    if cache_is_fresh(fingerprint):
        if as_hook:
            print("{}", flush=True)
        else:
            print("[OK] Hook selftest cache is fresh.", flush=True)
        return 0

    if as_hook:
        cache = _read_cache()
        if cache.get("ok") is False:
            if cache.get("fingerprint") != fingerprint:
                _spawn_background_selftest(fingerprint)
            print(_failure_hook_response(), flush=True)
            return 0
        if os.environ.get("HARNESS_HOOK_SELFTEST_SYNC") == "1":
            ok, _ = run_selftest(echo=False)
            _write_cache(fingerprint, ok)
            print("{}" if ok else _failure_hook_response(), flush=True)
            return 0
        _spawn_background_selftest(fingerprint)
        print("{}", flush=True)
        return 0

    _write_running_lock(os.getpid(), fingerprint)
    try:
        ok, output = run_selftest(echo=True)
        _write_cache(fingerprint, ok)
    finally:
        _clear_running_lock()

    if ok:
        print("[SUCCESS] Hook selftest passed; cache updated.", flush=True)
        return 0
    print("[FAIL] Hook selftest failed.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
