"""Synchronous Gradle runner for this Android app with a live task log.

Streams executing tasks and a 10s heartbeat. Suppresses UP-TO-DATE noise and
Kotlin `w:` deprecation floods. Full raw log is kept for failure parsing.
"""
from __future__ import annotations

import argparse
import json
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
from _live_process import enable_line_buffered_stdio, live_print, run_streaming, step_progress  # noqa: E402
from _variants import resolve_or_raise  # noqa: E402
from gradle_error_parser import format_errors, parse_compiler_errors  # noqa: E402
from artifact_set import build_artifact_set, resolve_artifacts  # noqa: E402

_env_repo = os.environ.get("HARNESS_REPO", "").strip()


def _resolve_repo_root() -> Path:
    if _env_repo:
        return Path(_env_repo).resolve()
    cwd = Path.cwd().resolve()
    if (
        (cwd / "gradlew").is_file()
        or (cwd / "gradlew.bat").is_file()
        or (cwd / "settings.gradle.kts").is_file()
        or (cwd / "settings.gradle").is_file()
    ):
        return cwd
    return Path(__file__).resolve().parent.parent.parent


REPO_ROOT = _resolve_repo_root()

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


def gradle_wrapper(repo: Path | None = None) -> Path:
    """Repo wrapper for Windows (`gradlew.bat`) and macOS/Linux (`./gradlew`)."""
    root = Path(repo).resolve() if repo else REPO_ROOT
    unix = root / "gradlew"
    win = root / "gradlew.bat"
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
    raise FileNotFoundError(f"No Gradle wrapper in {root} (expected gradlew or gradlew.bat)")


def unix_wrapper_cmd(wrapper: Path, gradle_args: list[str]) -> list[str]:
    """Run the unix gradlew through bash, falling back to sh, then direct exec."""
    if os.name == "nt" and wrapper.is_file():
        try:
            b = wrapper.read_bytes()
            if b"\r\n" in b:
                wrapper.write_bytes(b.replace(b"\r\n", b"\n"))
        except Exception:
            pass
    target = "./gradlew" if wrapper.name == "gradlew" else str(wrapper)
    for shell in ("bash", "sh"):
        if shutil.which(shell):
            return [shell, target, *gradle_args]
    return [str(wrapper), *gradle_args]



def test_failure_only(task: str, raw_log: str) -> bool:
    """Attribute a nonzero exit to one test task, never to another build failure."""
    failures = re.findall(r"Execution failed for task ['\"]([^'\"]+)['\"]", raw_log)
    failed_tasks = re.findall(r"(?m)^> Task (\S+) FAILED\s*$", raw_log)
    sections = re.findall(r"(?ms)^\* What went wrong:\s*\n(.*?)(?=^\* |\Z)", raw_log)
    if len(sections) != 1 or re.search(r"Build completed with (?:[2-9]|\d{2,}) failures", raw_log):
        return False
    details = [line.strip() for line in sections[0].splitlines() if line.strip()]
    if len(details) != 2 or not details[0].startswith("Execution failed for task ") or not details[1].startswith("> There were failing tests"):
        return False
    expected = ":" + task.strip(":")
    return (
        bool(failures) and all(":" + item.strip(":") == expected for item in failures + failed_tasks)
        and "There were failing tests" in raw_log
        and not parse_compiler_errors(raw_log)
    )


def validate_reviewer_precondition_before_assemble(
    repo: Path,
    state_dir: Path,
) -> tuple[bool, str]:
    """Validate that required specialist reviews have passed before assembleDebug.

    Fail-closed: Returns (False, reason) if evidence is missing, malformed, stale,
    contains unresolved blocking findings, or required coverage is incomplete.
    Returns (True, reason) only if reviews are not required or all required reviews passed.
    """
    active_p = state_dir / "active-task.json"
    if not active_p.is_file():
        return False, "NO_ACTIVE_TASK: an approved active task is required for assemble"

    try:
        active_task_data = json.loads(active_p.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"active-task.json is unreadable or malformed: {exc}"

    tid = str(active_task_data.get("task_id") or "").strip()
    if not tid:
        return False, "NO_ACTIVE_TASK: active task identity is missing"

    plan_p = state_dir / "tasks" / tid / "plan.json"
    if not plan_p.is_file():
        return False, f"Task {tid} plan.json missing"

    try:
        plan_data = json.loads(plan_p.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"Task {tid} plan.json is unreadable or malformed: {exc}"

    status = str(plan_data.get("status") or "").upper()
    if status == "IMPLEMENTING":
        return True, "DIAGNOSTIC_ASSEMBLE_DURING_IMPLEMENTATION"
    if status != "VERIFYING":
        return False, f"Active task status {status or 'UNKNOWN'} does not authorize assemble"

    current_run_p = state_dir / "tasks" / tid / "current-run.json"
    if not current_run_p.is_file():
        return False, f"Task {tid} is VERIFYING but current-run.json is missing"

    try:
        current_run = json.loads(current_run_p.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"Task {tid} current-run.json is unreadable or malformed: {exc}"

    policy_raw = str(current_run.get("policy") or "")
    if not policy_raw:
        return False, f"Task {tid} current-run.json missing policy reference"

    policy_p = Path(policy_raw)
    if not policy_p.is_file():
        if (state_dir / policy_p).is_file():
            policy_p = state_dir / policy_p
        elif (repo / policy_p).is_file():
            policy_p = repo / policy_p

    if not policy_p.is_file():
        return False, f"Policy file not found: {policy_p}"

    try:
        pol_data = json.loads(policy_p.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"Policy file is unreadable or malformed: {exc}"

    required_revs = list(pol_data.get("reviewers") or [])
    if not required_revs:
        return True, "Policy requires no reviewers"

    snap = str(current_run.get("snapshot") or current_run.get("delivery_snapshot_sha256") or "")
    r_id = str(current_run.get("run_id") or "")
    change_set = str(current_run.get("change_set_sha256") or "")
    if not snap or not r_id:
        return False, "current-run missing snapshot or run_id"

    try:
        from evidence_store import EvidenceStore
        store = EvidenceStore(state_dir)
        rev_entry = store.read(snap, r_id, "reviews")
    except Exception as exc:
        return False, f"Required reviews evidence missing, stale, or invalid: {exc}"

    if rev_entry.get("change_set_sha256") and change_set and rev_entry.get("change_set_sha256") != change_set:
        return False, "reviews evidence change-set mismatch"

    if str(rev_entry.get("status") or "").upper() != "PASS":
        return False, f"reviews evidence status is {rev_entry.get('status')}, expected PASS"

    rev_ev = rev_entry.get("evidence") or {}
    if not isinstance(rev_ev, dict):
        return False, "reviews evidence payload is malformed"

    if rev_ev.get("developer_override"):
        return True, "developer override present in reviews evidence"

    covered = set(rev_ev.get("reviewers") or [])
    missing_revs = set(required_revs) - covered
    if missing_revs:
        return False, f"Incomplete reviewer coverage: missing {sorted(missing_revs)}"

    if rev_ev.get("blocking_findings"):
        return False, f"Reviews contain unresolved blocking findings: {rev_ev.get('blocking_findings')}"

    return True, "All required reviewers passed"


def run_gradle(task_args: list[str], *, outcome: dict | None = None, cwd: Path | str | None = None) -> int:
    enable_line_buffered_stdio()
    if outcome is not None:
        outcome.clear()
        outcome["test_failure_only"] = False
    gradle_args = with_plain_console(task_args)
    task_label = task_args[0] if task_args else "gradle"
    artifact_name = gate_artifact_name(task_label)
    run_root = Path(cwd).resolve() if cwd else REPO_ROOT

    def record(status: str, exit_code: int, env_class: str = "", detail: str = "", **extra) -> None:
        write_gate_result(artifact_name, {
            "schema_version": 1,
            "task": task_label,
            "status": status,
            "exit_code": exit_code,
            "env_class": env_class,
            "git_sha": current_head_sha(),
            "detail": detail,
            **extra,
        })

    if any("assemble" in arg.lower() for arg in task_args):
        state_dir = run_root / ".agents" / "state"
        try:
            allowed, reason = validate_reviewer_precondition_before_assemble(run_root, state_dir)
            if not allowed:
                msg = f"Pipeline order violation: required specialist reviewers must pass before running assembleDebug ({reason})."
                live_print(f"[FAIL] {msg}", err=True)
                record("FAIL", 1, "CODE", msg)
                return 1
        except Exception as exc:
            msg = f"Reviewer precondition validation failed closed: {type(exc).__name__}: {exc}"
            live_print(f"[FAIL] {msg}", err=True)
            record("FAIL", 1, "CODE", msg)
            return 1

    try:
        wrapper = gradle_wrapper(run_root)
    except FileNotFoundError as exc:
        live_print(f"[!] {exc}", err=True)
        verdict = FailureVerdict(CLASS_ENV, str(exc))
        record("ENV", EXIT_ENV, verdict.env_class, verdict.reason)
        emit_env_failure(verdict, "run_gradle_task.py")
        return EXIT_ENV
    if wrapper.name == "gradlew":
        if os.name == "nt" and not shutil.which("bash") and not shutil.which("sh"):
            msg = "gradlew.bat is missing on Windows and neither bash nor sh was found in PATH to execute gradlew. Please restore gradlew.bat or install Git Bash."
            live_print(f"[!] {msg}", err=True)
            verdict = FailureVerdict(CLASS_ENV, msg)
            record("ENV", EXIT_ENV, verdict.env_class, verdict.reason)
            emit_env_failure(verdict, "run_gradle_task.py")
            return EXIT_ENV
        gradle_cmd = unix_wrapper_cmd(wrapper, gradle_args)
    else:
        gradle_cmd = [str(wrapper), *gradle_args]
    live_print(f"[*] Executing: {wrapper.name} {' '.join(gradle_args)}")
    started = time.time()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    with step_progress(f"Gradle: {task_label}"):
        code, raw_log, echoed = run_streaming(
            gradle_cmd,
            cwd=str(run_root),
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
        if outcome is not None:
            outcome["test_failure_only"] = test_failure_only(task_label, raw_log)

    if code == 0:
        artifact_set = None
        artifact_error = ""
        try:
            from _product import PROJECT_KIND
        except ImportError:
            PROJECT_KIND = "application"
        if PROJECT_KIND == "application" and any("assemble" in arg.lower() for arg in task_args):
            try:
                from _product import APPLICATION_ID
                from _variants import apk_relative

                paths = resolve_artifacts(run_root, task_label, apk_relative())
                artifact_set = build_artifact_set(
                    run_root,
                    task_label,
                    paths,
                    application_id=str(APPLICATION_ID or ""),
                )
            except Exception as exc:
                artifact_error = str(exc)
        if artifact_error:
            record("FAIL", 1, "CODE", artifact_error)
            live_print(f"[!] BUILD OUTPUT AMBIGUOUS: {artifact_error}", err=True)
            return 1
        record("PASS", 0, artifact_set=artifact_set)
        hint = _duration_hint(raw_log)
        if hint == "done":
            hint = f"{time.time() - started:.1f}s"
        live_print(f"[+] BUILD SUCCESSFUL in {hint}")
        for item in echoed:
            lower = item.lower()
            if "BUILD SUCCESSFUL" in item or "tests completed" in lower or " passed" in lower:
                live_print(f"    {item}")
        if artifact_set:
            live_print(f"[+] Installable artifact set: {artifact_set['artifact_set_sha256'][:12]}")
            for member in artifact_set["members"]:
                live_print(f"    {member['path']} ({int(member['size']) / (1024 * 1024):.1f} MB)")
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
    sys.exit(run_gradle(task_args, cwd=_resolve_repo_root()))


if __name__ == "__main__":
    main()
