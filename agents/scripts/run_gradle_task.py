"""Synchronous Gradle runner for this Android app with a live task log.

Streams executing tasks and a 10s heartbeat. Suppresses UP-TO-DATE noise and
Kotlin `w:` deprecation floods. Full raw log is kept for failure parsing.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env_codes import (  # noqa: E402
    CLASS_CODE,
    CLASS_ENV,
    EXIT_ENV,
    FailureVerdict,
    classify_gradle_failure,
    emit_env_failure,
)
from _gate_results import (  # noqa: E402
    current_head_sha,
    gate_artifact_name,
    write_gate_result,
)
from _live_process import enable_line_buffered_stdio, live_print, run_streaming  # noqa: E402
from _variants import resolve_or_raise  # noqa: E402
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


def unix_wrapper_cmd(wrapper: Path, gradle_args: list[str]) -> list[str]:
    """Run the unix gradlew through bash, falling back to sh, then direct exec."""
    for shell in ("bash", "sh"):
        if shutil.which(shell):
            return [shell, str(wrapper), *gradle_args]
    return [str(wrapper), *gradle_args]


def run_gradle(task_args: list[str]) -> int:
    enable_line_buffered_stdio()
    try:
        from _hook_state import review_advisory

        advisory = review_advisory()
        if advisory:
            live_print(advisory)
    except Exception:
        pass
    gradle_args = with_plain_console(task_args)
    task_label = task_args[0] if task_args else "gradle"
    artifact_name = gate_artifact_name(task_label)

    def record(status: str, exit_code: int, env_class: str = "", detail: str = "") -> None:
        write_gate_result(artifact_name, {
            "schema_version": 1,
            "task": task_label,
            "status": status,
            "exit_code": exit_code,
            "env_class": env_class,
            "git_sha": current_head_sha(),
            "detail": detail,
        })

    try:
        wrapper = gradle_wrapper()
    except FileNotFoundError as exc:
        live_print(f"[!] {exc}", err=True)
        verdict = FailureVerdict(CLASS_ENV, str(exc))
        record("ENV", EXIT_ENV, verdict.env_class, verdict.reason)
        emit_env_failure(verdict, "run_gradle_task.py")
        return EXIT_ENV
    if os.name != "nt" and wrapper.name == "gradlew":
        gradle_cmd = unix_wrapper_cmd(wrapper, gradle_args)
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

    if code != 0:
        verdict = classify_gradle_failure(code, raw_log)
        if verdict.env_class != CLASS_CODE:
            live_print(f"[!] BUILD FAILED (exit {code}) — environment problem, no code fixes allowed")
            record("ENV", EXIT_ENV, verdict.env_class, verdict.reason)
            emit_env_failure(verdict, "run_gradle_task.py")
            return EXIT_ENV
        record("FAIL", code, verdict.env_class, verdict.reason)

    if code == 0:
        record("PASS", 0)
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
                from _variants import apk_relative

                apk = REPO_ROOT / apk_relative()
            except Exception:
                apk = REPO_ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
            if not apk.is_file():
                candidates = [
                    p
                    for p in REPO_ROOT.glob("**/outputs/apk/**/*.apk")
                    if "debug" in p.as_posix().lower() and not p.name.endswith("-androidTest.apk")
                ]
                apk = sorted(candidates)[0] if candidates else apk
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


def extract_flavor(task_args: list[str]) -> tuple[str | None, list[str]]:
    """Pull a leading --flavor NAME or --flavor=NAME out of the task list."""
    if task_args and task_args[0] == "--flavor":
        if len(task_args) < 2:
            return None, task_args
        return task_args[1], task_args[2:]
    if task_args and task_args[0].startswith("--flavor="):
        return (task_args[0].split("=", 1)[1].strip() or None), task_args[1:]
    return None, task_args


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

    flavor, task_args = extract_flavor(task_args)
    if flavor is None and any(arg == "--flavor" for arg in task_args[:2]):
        live_print("Usage: python run_gradle_task.py --flavor <name> <gradle_tasks...>", err=True)
        sys.exit(1)

    if not task_args:
        live_print("Usage: python run_gradle_task.py [--flavor <name>] <gradle_tasks_and_args>", err=True)
        sys.exit(1)
    try:
        active_flavor, _resolved_task = resolve_or_raise(flavor)
    except SystemExit as exc:
        live_print(str(exc), err=True)
        sys.exit(1)
    if active_flavor:
        live_print(f"[*] Active build variant: {active_flavor} (debug)")
    sys.exit(run_gradle(task_args))


if __name__ == "__main__":
    main()
