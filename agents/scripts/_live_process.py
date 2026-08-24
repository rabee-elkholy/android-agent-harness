"""Stream long-running commands so Antigravity task logs stay live.

Python and Gradle both buffer when stdout is a pipe (not a TTY). Without
line-buffering, flush, and a heartbeat, assemble/test/install look empty
for minutes even while the process is working.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence

DEFAULT_HEARTBEAT_SEC = 10.0


def enable_line_buffered_stdio() -> None:
    os.environ["PYTHONUNBUFFERED"] = "1"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                pass


def live_print(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(msg, file=stream, flush=True)


def run_streaming(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    heartbeat_sec: float = DEFAULT_HEARTBEAT_SEC,
    should_echo: Callable[[str], bool] | None = None,
    label: str = "command",
    echo: bool = True,
) -> tuple[int, str, list[str]]:
    """Run argv, echo selected lines immediately, heartbeat while stdout is quiet.

    Returns (returncode, raw_log, echoed_lines).
    """
    enable_line_buffered_stdio()
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    merged_env["PYTHONUNBUFFERED"] = "1"
    merged_env["PYTHONIOENCODING"] = "utf-8"

    echo_fn = should_echo or (lambda line: bool(line.strip()))
    stop = threading.Event()
    start = time.time()
    last = {"text": "", "t": start, "beat": 0.0}
    lock = threading.Lock()
    echoed: list[str] = []
    raw_chunks: list[str] = []
    idle_hint = f"waiting for {label} output"

    def heartbeat() -> None:
        if heartbeat_sec <= 0:
            return
        while not stop.wait(1.0):
            now = time.time()
            with lock:
                quiet = now - last["t"]
                since_beat = now - last["beat"]
                last_text = last["text"] or idle_hint
            if quiet >= heartbeat_sec and since_beat >= heartbeat_sec:
                with lock:
                    last["beat"] = now
                elapsed = int(now - start)
                live_print(f"[*] still running ({elapsed}s) — {last_text}")

    try:
        proc = subprocess.Popen(
            list(argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged_env,
            bufsize=1,
        )
    except Exception as exc:
        live_print(f"[!] Failed to launch {label}: {exc}", err=True)
        return 1, "", []

    worker = threading.Thread(target=heartbeat, name="harness-heartbeat", daemon=True)
    worker.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            raw_chunks.append(line)
            clean = line.rstrip("\n\r")
            if echo_fn(clean):
                with lock:
                    last["text"] = clean.strip()[:180]
                    last["t"] = time.time()
                    echoed.append(clean)
                if echo:
                    live_print(clean)
        proc.wait()
    except BaseException:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
        except Exception:
            pass
        raise
    finally:
        stop.set()

    code = proc.returncode if proc.returncode is not None else 1
    return code, "".join(raw_chunks), echoed
