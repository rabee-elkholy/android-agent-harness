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


def _iter_watched() -> list[Path]:
    files: list[Path] = []
    files.extend(sorted(SCRIPTS.glob("*.py")))
    files.extend(sorted((AGENTS / "subagents").glob("*.json")))
    for extra in (AGENTS / "hooks.json",):
        if extra.is_file():
            files.append(extra)
    return [p for p in files if p.is_file()]


def harness_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in _iter_watched():
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
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
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(
        json.dumps({"fingerprint": fingerprint, "ok": ok}, indent=2),
        encoding="utf-8",
    )


def cache_is_fresh(fingerprint: str) -> bool:
    cache = _read_cache()
    return cache.get("fingerprint") == fingerprint and cache.get("ok") is True


def run_selftest(echo: bool = False) -> tuple[bool, str]:
    env = os.environ.copy()
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


def main() -> int:
    enable_line_buffered_stdio()
    raw = _read_stdin_safe()
    as_hook = _is_hook_payload(raw)

    fingerprint = harness_fingerprint()
    if cache_is_fresh(fingerprint):
        if as_hook:
            print("{}", flush=True)
        else:
            print("[OK] Hook selftest cache is fresh.", flush=True)
        return 0

    ok, output = run_selftest(echo=(not as_hook))
    _write_cache(fingerprint, ok)

    if as_hook:
        if ok:
            print("{}", flush=True)
            return 0
        try:
            import _product
            prod_name = getattr(_product, "PRODUCT_NAME", getattr(_product, "PRODUCT", "App"))
        except Exception:
            prod_name = "App"
        print(
            json.dumps(
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
            ),
            flush=True,
        )
        return 0

    if ok:
        print("[SUCCESS] Hook selftest passed; cache updated.", flush=True)
        return 0
    print("[FAIL] Hook selftest failed.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
