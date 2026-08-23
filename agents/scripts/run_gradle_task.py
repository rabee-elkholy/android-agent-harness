"""Synchronous Gradle runner for this Android app with a live task log.

Streams executing tasks and a 10s heartbeat. Suppresses UP-TO-DATE noise and
Kotlin `w:` deprecation floods. Full raw log is kept for failure parsing.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print, run_streaming  # noqa: E402
from gradle_error_parser import format_errors, parse_compiler_errors  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SUPPRESSED_PATTERNS = [
    re.compile(r"^> Task :.*UP-TO-DATE"),
    re.compile(r"^> Task :.*NO-SOURCE"),
    re.compile(r"^> Task :.*SKIPPED"),
    re.compile(r"^Configuration on demand is an incubating feature"),
    re.compile(r"^Reusing configuration cache"),
    re.compile(r"^Calculating task graph"),
    re.compile(r"^Configure project :.*WARNING: Using flatDir"),
    re.compile(r"^Note: Some input files use or override a deprecated API"),
    re.compile(r"^Note: Recompile with -Xlint"),
    re.compile(r"^Note: Some input files use unchecked"),
]
KOTLIN_WARNING = re.compile(r"^w:\s")


def is_boilerplate(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    return any(p.search(s) for p in SUPPRESSED_PATTERNS)


def should_echo_gradle(line: str) -> bool:
    s = line.strip()
    if not s or is_boilerplate(s):
        return False
    if KOTLIN_WARNING.match(s):
        return False
    return True


def with_plain_console(task_args: list[str]) -> list[str]:
    if any(arg == "--console" or arg.startswith("--console=") for arg in task_args):
        return task_args
    return ["--console=plain", *task_args]


def gradle_wrapper() -> Path:
    """Repo-root wrapper for Windows (`gradlew.bat`) and macOS/Linux (`./gradlew`)."""
    unix = REPO_ROOT / "gradlew"
    win = REPO_ROOT / "gradlew.bat"
    if os.name == "nt":
        if win.is_file():
            return win
        if unix.is_file():
            return unix
    else:
        if unix.is_file():
            return unix
        if win.is_file():
            return win
    raise FileNotFoundError(f"No Gradle wrapper in {REPO_ROOT} (expected gradlew or gradlew.bat)")


def run_gradle(task_args: list[str]) -> int:
    enable_line_buffered_stdio()
    gradle_args = with_plain_console(task_args)
    try:
        wrapper = gradle_wrapper()
    except FileNotFoundError as exc:
        live_print(f"[!] {exc}", err=True)
        return 1
    if os.name != "nt" and wrapper.name == "gradlew":
        gradle_cmd = ["bash", str(wrapper), *gradle_args]
    else:
        gradle_cmd = [str(wrapper), *gradle_args]
    live_print(f"[*] Executing: {wrapper.name} {' '.join(gradle_args)}")
    started = time.time()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    code, raw_log, echoed = run_streaming(
        gradle_cmd,
        cwd=str(REPO_ROOT),
        env=env,
        heartbeat_sec=10.0,
        should_echo=should_echo_gradle,
        label="gradle",
    )

    important_lines = list(echoed)
    for line in raw_log.splitlines():
        if "BUILD FAILED" in line or line.strip().startswith("e: ") or " FAILED" in line:
            if line not in important_lines:
                important_lines.append(line)

    if code == 0:
        hint = _duration_hint(raw_log)
        if hint == "done":
            hint = f"{time.time() - started:.1f}s"
        live_print(f"[+] BUILD SUCCESSFUL in {hint}")
        for item in echoed:
            lower = item.lower()
            if "BUILD SUCCESSFUL" in item or "tests completed" in lower or " passed" in lower:
                live_print(f"    {item}")
        if any("assemble" in arg.lower() for arg in task_args):
            try:
                from _product import APK_RELATIVE
                apk = REPO_ROOT / APK_RELATIVE
            except Exception:
                apk = REPO_ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
            if not apk.is_file():
                found = sorted(REPO_ROOT.glob("**/outputs/apk/debug/*.apk"))
                apk = found[0] if found else apk
            if apk.is_file():
                size_mb = apk.stat().st_size / (1024 * 1024)
                rel = apk.relative_to(REPO_ROOT).as_posix()
                live_print(f"[+] Output APK: {rel} ({size_mb:.1f} MB)")
        return 0

    live_print(f"[!] BUILD FAILED (exit {code})")
    parsed = parse_compiler_errors(raw_log)
    if parsed:
        live_print(format_errors(parsed))
    else:
        live_print("--- Isolated Error Output ---")
        for item in important_lines[-80:]:
            live_print(f"  {item}")
    return code


def _duration_hint(raw_log: str) -> str:
    for line in reversed(raw_log.splitlines()):
        if "BUILD SUCCESSFUL" in line and " in " in line:
            return line.split(" in ", 1)[-1].strip()
    return "done"


def main() -> None:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Live Gradle runner for this app")
    parser.add_argument(
        "gradle_args",
        nargs=argparse.REMAINDER,
        help="Gradle task arguments (e.g. :app:assembleDebug)",
    )
    args = parser.parse_args()
    task_args = list(args.gradle_args)
    if task_args and task_args[0] == "--":
        task_args = task_args[1:]
    if not task_args:
        live_print("Usage: python run_gradle_task.py <gradle_tasks_and_args>", err=True)
        sys.exit(1)
    sys.exit(run_gradle(task_args))


if __name__ == "__main__":
    main()
