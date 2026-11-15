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
from pathlib import Path

DEFAULT_HEARTBEAT_SEC = 10.0

_open_step_line: bool = False
_active_step_has_sublogs: list[bool] = []
_active_step_lock = threading.Lock()
_last_sublog_time: list[float] = [0.0]


def enable_line_buffered_stdio() -> None:
    os.environ["PYTHONUNBUFFERED"] = "1"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except (OSError, ValueError):
                pass


def _json_output_mode() -> bool:
    if os.environ.get("HARNESS_LIVE_STDERR", "").strip() == "1":
        return True
    argv = sys.argv[1:]
    if "--json" in argv or "--format=json" in argv:
        return True
    for i, arg in enumerate(argv[:-1]):
        if arg == "--format" and argv[i + 1].strip().lower() == "json":
            return True
    return False


def live_print(msg: str, *, err: bool = False, end: str = "\n") -> None:
    global _open_step_line
    stream = sys.stderr if (err or _json_output_mode()) else sys.stdout
    if _open_step_line and not (msg.startswith("[Done]") or msg.startswith("[Fail]")):
        try:
            print("", file=stream, flush=True)
        except (OSError, ValueError):
            pass
        _open_step_line = False
    try:
        print(msg, file=stream, end=end, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        safe_msg = msg.encode(encoding, errors="replace").decode(encoding)
        print(safe_msg, file=stream, end=end, flush=True)
    _open_step_line = (end != "\n")


def sublog(msg: str, *, bullet: str = "*", indent: int = 2) -> None:
    """Print an indented live sub-log entry under the active step_progress."""
    global _active_step_has_sublogs, _last_sublog_time
    with _active_step_lock:
        if _active_step_has_sublogs:
            _active_step_has_sublogs[-1] = True
    _last_sublog_time[0] = time.time()
    spaces = " " * indent
    formatted = f"{spaces}{bullet} {msg}"
    live_print(formatted)


STEP_HEARTBEAT_SEC = 30.0
# run_streaming prints its own heartbeat (naming the last output line); a step around it stays quiet.
_streaming_active = [0]


@contextlib.contextmanager
def step_progress(name: str, step: int | None = None, total: int | None = None, heartbeat_sec: float = STEP_HEARTBEAT_SEC):  # type: ignore[return]
    """Context manager that prints step progress markers with elapsed time, sublogs, and heartbeat."""
    global _active_step_has_sublogs, _last_sublog_time
    clean_name = name.strip()
    m = re.match(r"^\[(\d+/\d+)\]\s*(.*)$", clean_name)
    if m:
        formatted = f"{m.group(2)} [{m.group(1)}]"
    elif step is not None and total is not None:
        formatted = f"{clean_name} [{step}/{total}]"
    else:
        formatted = clean_name

    live_print(f"{formatted} ", end="")
    with _active_step_lock:
        _active_step_has_sublogs.append(False)

    t0 = time.time()
    _last_sublog_time[0] = t0
    stop_heartbeat = threading.Event()

    def _step_heartbeat() -> None:
        if heartbeat_sec <= 0:
            return
        while not stop_heartbeat.wait(1.0):
            now = time.time()
            if _streaming_active[0]:
                _last_sublog_time[0] = now
                continue
            if (now - _last_sublog_time[0]) >= heartbeat_sec:
                _last_sublog_time[0] = now
                elapsed = int(now - t0)
                sublog(f"{formatted.strip()}: still running ({elapsed}s)", bullet="[-]")

    worker = None
    if heartbeat_sec > 0:
        worker = threading.Thread(target=_step_heartbeat, name="step-hb", daemon=True)
        worker.start()

    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        stop_heartbeat.set()
        if worker is not None:
            worker.join()
        elapsed = time.time() - t0
        with _active_step_lock:
            has_sublogs = _active_step_has_sublogs.pop() if _active_step_has_sublogs else False
        prefix = "  " if has_sublogs else ""
        status = "Fail" if failed else "Done"
        live_print(f"{prefix}[{status}] ({elapsed:.1f}s)")


def _is_windows_pid_alive(pid: int) -> bool:
    if pid <= 0 or os.name != "nt":
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return int(exit_code.value) == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _has_explicit_gradle_java_home(prop_file: Path) -> bool:
    if not prop_file.is_file():
        return False
    try:
        for raw_ln in prop_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            ln = raw_ln.strip()
            if not ln or ln.startswith(("#", "!")):
                continue
            if re.match(r"^org\.gradle\.java\.home\s*[:=]\s*\S+", ln):
                return True
    except OSError:
        return False
    return False


def resolve_compatible_windows_daemon_java_home(
    cwd: str | Path | None,
    env: dict[str, str],
    *,
    os_name: str | None = None,
    pid_alive_fn: Callable[[int], bool] | None = None,
) -> str | None:
    """Match `JAVA_HOME` to a live Gradle daemon of the exact project wrapper version on Windows.

    When Android Studio already holds a warm out-of-job daemon (e.g. bundled JBR) and the project does not pin
    `org.gradle.java.home`, aligning `JAVA_HOME` lets `gradlew.bat` attach over localhost TCP to that warm daemon
    instead of spawning a cold disposable daemon inside Antigravity's `KILL_ON_JOB_CLOSE` Job Object.
    """
    eff_os = os_name if os_name is not None else os.name
    if eff_os != "nt":
        return None
    if str(env.get("HARNESS_DISABLE_WINDOWS_DAEMON_JAVA_ALIGN") or "").strip().lower() in {"1", "true", "yes"}:
        return None
    try:
        proj_dir = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        gradle_user_home = Path(
            env.get("GRADLE_USER_HOME") or (Path.home() / ".gradle")
        ).resolve()
        if _has_explicit_gradle_java_home(proj_dir / "gradle.properties") or _has_explicit_gradle_java_home(
            gradle_user_home / "gradle.properties"
        ):
            return None
        wrapper_props = proj_dir / "gradle" / "wrapper" / "gradle-wrapper.properties"
        if not wrapper_props.is_file():
            return None
        w_txt = wrapper_props.read_text(encoding="utf-8", errors="ignore")
        m_ver = re.search(r"gradle-([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-rc-\d+)?)-(?:bin|all)\.zip", w_txt)
        if not m_ver:
            return None
        gradle_ver = m_ver.group(1)
        daemon_dir = gradle_user_home / "daemon" / gradle_ver
        if not daemon_dir.is_dir():
            return None
        check_alive = pid_alive_fn or _is_windows_pid_alive
        now = time.time()
        logs = sorted(
            (p for p in daemon_dir.glob("daemon-*.out.log") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:6]
        live_homes: dict[str, str] = {}
        java_bin_rel = Path("bin") / ("java.exe" if os.name == "nt" or eff_os == "nt" else "java")
        for lg in logs:
            try:
                if (now - lg.stat().st_mtime) > 86400:
                    continue
                m_pid = re.match(r"^daemon-(\d+)\.out\.log$", lg.name)
                if not m_pid or not check_alive(int(m_pid.group(1))):
                    continue
                with lg.open("r", encoding="utf-8", errors="ignore") as fh:
                    head = fh.read(16384)
                m_jh = re.search(r"DaemonContext\[[^\]]*?\bjavaHome=([^,\]\r\n]+)", head)
                if not m_jh:
                    continue
                jh_path = Path(m_jh.group(1).strip())
                if (jh_path / java_bin_rel).is_file() or (jh_path / "bin" / "java").is_file():
                    norm_key = str(jh_path).replace("\\", "/").rstrip("/").lower()
                    live_homes[norm_key] = str(jh_path)
            except OSError:
                continue
        if len(live_homes) == 1:
            return next(iter(live_homes.values()))
    except Exception:
        return None
    return None


def _should_try_windows_gradle_breakaway(argv: Sequence[str], env: dict[str, str], label: str) -> bool:
    """True when launching a daemon-enabled Gradle wrapper on Windows so the daemon survives Job close."""
    if os.name != "nt" or str(label or "").strip().lower() != "gradle":
        return False
    if str(env.get("HARNESS_DISABLE_WINDOWS_DAEMON_BREAKAWAY") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    return not any(str(a).strip() == "--no-daemon" for a in argv)


def _spawn_streaming_process(
    argv: list[str],
    *,
    cwd: str | None,
    env: dict[str, str],
    label: str,
) -> subprocess.Popen[str]:
    eff_env = env
    if (
        str(label or "").strip().lower() == "gradle"
        and not any(str(a).strip() == "--no-daemon" for a in argv)
    ):
        aligned_jh = resolve_compatible_windows_daemon_java_home(cwd, env)
        if aligned_jh:
            eff_env = {**env, "JAVA_HOME": aligned_jh}
    base_kwargs: dict[str, object] = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": eff_env,
        "bufsize": 1,
    }
    if _should_try_windows_gradle_breakaway(argv, eff_env, label):
        breakaway_flags = (
            int(getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000))
            | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
        )
        try:
            return subprocess.Popen(argv, creationflags=breakaway_flags, **base_kwargs)  # type: ignore[arg-type]
        except OSError:
            # Host Job Object disallows breakaway (e.g. WinError 5 Access Denied); fall back transparently.
            pass
    return subprocess.Popen(argv, **base_kwargs)  # type: ignore[arg-type]


def run_streaming(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    heartbeat_sec: float = DEFAULT_HEARTBEAT_SEC,
    should_echo: Callable[[str], bool] | None = None,
    format_echo: Callable[[str], str] | None = None,
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
    merged_env.pop("BASH_ENV", None)
    merged_env.pop("ENV", None)
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
        proc = _spawn_streaming_process(
            list(argv),
            cwd=cwd,
            env=merged_env,
            label=label,
        )
    except Exception as exc:
        live_print(f"[!] Failed to launch {label}: {exc}", err=True)
        return 1, "", []

    worker = threading.Thread(target=heartbeat, name="harness-heartbeat", daemon=True)
    worker.start()
    _streaming_active[0] += 1
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            raw_chunks.append(line)
            clean = line.rstrip("\n\r")
            if echo_fn(clean):
                clean = format_echo(clean) if format_echo else clean
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
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        raise
    finally:
        _streaming_active[0] -= 1
        stop.set()
        if proc.stdout is not None:
            proc.stdout.close()
        worker.join()

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


def shard_tests(tests: list, index: int, count: int) -> list:
    """Contiguous slice `index` of `count` near-equal slices, in load order.

    Contiguous slices keep each test class together, so class fixtures run once per shard, and the
    slices of all shards together are exactly the full list.
    """
    size = -(-len(tests) // count) if count > 0 else len(tests)
    return tests[index * size:(index + 1) * size]


def run_test_shard(path: str, index: int, count: int) -> int:
    """Load a selftest module and run shard `index` of `count`; exit status 0 only when it passes."""
    import importlib.util
    import unittest
    from pathlib import Path

    name = f"selftest_shard_{Path(path).stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    tests: list = []

    def walk(suite) -> None:
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                walk(item)
            else:
                tests.append(item)

    walk(unittest.defaultTestLoader.loadTestsFromModule(module))
    picked = shard_tests(tests, index, count)
    result = unittest.TextTestRunner().run(unittest.TestSuite(picked))
    return 0 if result.wasSuccessful() else 1

