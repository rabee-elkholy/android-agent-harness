"""Stream long-running commands so Antigravity task logs stay live.

Python and Gradle both buffer when stdout is a pipe (not a TTY). Without
line-buffering, flush, and a heartbeat, assemble/test/install look empty
for minutes even while the process is working.
"""
from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence

DEFAULT_HEARTBEAT_SEC = 10.0

_open_step_line: bool = False


def enable_line_buffered_stdio() -> None:
    os.environ["PYTHONUNBUFFERED"] = "1"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                pass


def live_print(msg: str, *, err: bool = False, end: str = "\n") -> None:
    global _open_step_line
    stream = sys.stderr if err else sys.stdout
    if _open_step_line and not (msg.startswith("[Done]") or msg.startswith("[Fail]")):
        try:
            print("", file=stream, flush=True)
        except Exception:
            pass
        _open_step_line = False
    try:
        print(msg, file=stream, end=end, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        safe_msg = msg.encode(encoding, errors="replace").decode(encoding)
        print(safe_msg, file=stream, end=end, flush=True)
    _open_step_line = (end != "\n")


@contextlib.contextmanager
def step_progress(name: str, step: int | None = None, total: int | None = None):  # type: ignore[return]
    """Context manager that prints step progress markers with elapsed time."""
    clean_name = name.strip()
    m = re.match(r"^\[(\d+/\d+)\]\s*(.*)$", clean_name)
    if m:
        formatted = f"{m.group(2)} [{m.group(1)}]"
    elif step is not None and total is not None:
        formatted = f"{clean_name} [{step}/{total}]"
    else:
        formatted = clean_name

    live_print(f"{formatted} ", end="")
    t0 = time.time()
    try:
        yield
        elapsed = time.time() - t0
        live_print(f"[Done] ({elapsed:.1f}s)")
    except Exception:
        elapsed = time.time() - t0
        live_print(f"[Fail] ({elapsed:.1f}s)")
        raise


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
            if proc.stdout:
                try:
                    proc.stdout.close()
                except Exception:
                    pass
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


def enable_subtask_test_runner() -> None:
    """Configures unittest to report every test as an indented, formatted subtask."""
    import unittest
    import unittest.runner

    class SubtaskTestResult(unittest.TextTestResult):
        def __init__(self, stream, descriptions, verbosity):
            super().__init__(stream, descriptions, verbosity)
            self.dots = False
            self.showAll = False
            self.test_idx = 0
            self.total = 0
            self._t0 = 0.0

        def startTest(self, test):
            super().startTest(test)
            self.test_idx += 1
            self._t0 = time.time()
            name = test.id().split(".")[-1]
            tot_str = f"/{self.total}" if self.total else ""
            line = f"  {name} [{self.test_idx}{tot_str}] "
            try:
                self.stream.write(line)
            except UnicodeEncodeError:
                enc = getattr(self.stream, "encoding", None) or "ascii"
                self.stream.write(line.encode(enc, errors="replace").decode(enc))
            self.stream.flush()

        def _finish_subtask(self, status: str, el: float) -> None:
            line = f"[{status}] ({el:.1f}s)\n"
            try:
                self.stream.write(line)
            except UnicodeEncodeError:
                enc = getattr(self.stream, "encoding", None) or "ascii"
                self.stream.write(line.encode(enc, errors="replace").decode(enc))
            self.stream.flush()

        def addSuccess(self, test):
            super().addSuccess(test)
            el = time.time() - self._t0
            self._finish_subtask("Done", el)

        def addFailure(self, test, err):
            super().addFailure(test, err)
            el = time.time() - self._t0
            self._finish_subtask("Fail", el)

        def addError(self, test, err):
            super().addError(test, err)
            el = time.time() - self._t0
            self._finish_subtask("Fail", el)

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            el = time.time() - self._t0
            self._finish_subtask("Skip", el)


    class SubtaskTestRunner(unittest.TextTestRunner):
        resultclass = SubtaskTestResult

        def __init__(self, *args, **kwargs):
            kwargs["buffer"] = True
            super().__init__(*args, **kwargs)

        def _makeResult(self):
            res = super()._makeResult()
            res.buffer = True
            return res

        def run(self, test):
            self.buffer = True
            result = self._makeResult()
            result.total = test.countTestCases()
            test(result)
            result.printErrors()
            return result

    unittest.TextTestRunner = SubtaskTestRunner
    unittest.runner.TextTestRunner = SubtaskTestRunner


