"""Environment-vs-code failure classification and the harness exit-code protocol.

Exit codes (documented in harness-rules.md):
  EXIT_OK   = 0   success
  EXIT_FAIL = 1   code failure: the agent's diff is the cause; fix the code.
  EXIT_ENV  = 30  environment or ambiguous failure: HALT immediately, never
                  edit project code, Gradle files, or the manifest to bypass
                  it; report the reason to the developer.

Classification classes (first match wins, priority ENV > AMBIGUOUS > CODE):
  CLASS_ENV        unambiguous environment problem (adb missing, no device,
                   device offline/unauthorized, network dependency fetch)
  CLASS_CODE       unambiguous code/build problem (compiler errors, APK parse
                   failure, version downgrade, runtime crash)
  CLASS_AMBIGUOUS  undecidable locally; policy equals CLASS_ENV: HALT + report,
                   zero code edits.

Every ENV/AMBIGUOUS failure is also persisted atomically to
<REPO>/.agents/state/env_failure.json and printed as an [ENV-FAILURE] marker.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_ENV = 30

CLASS_ENV = "ENV"
CLASS_CODE = "CODE"
CLASS_AMBIGUOUS = "AMBIGUOUS"

_STATE_FILE_NAME = "env_failure.json"

_ADB_ENV_RE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"no devices/emulators found",
        r"no devices found",
        r"adb: no devices",
        r"error: no devices",
        r"device ['\"][^'\"]*['\"] not found",
        r"device not found",
        r"device offline",
        r"device unauthorized",
        r"more than one device",
        r"adb server is out of date",
        r"adb server version",
        r"daemon not running",
        r"daemon failed to start",
        r"cannot connect to daemon",
        r"failed to connect to",
        r"connection refused",
        r"connection reset",
        r"connection timed out",
        r"read timed out",
        r"protocol fault",
        r"install_failed_insufficient_storage",
        r"install_failed_no_matching_abis",
        r"install_failed_cpu_abi_incompatible",
        r"install_failed_already_exists",
        r"install_failed_user_restricted",
        r"install_failed_verification_failure",
        r"install_failed_verification_timeout",
        r"install_failed_cancelled_by_user",
        r"install_failed_media_unavailable",
        r"install_failed_shared_user_incompatible",
        r"install_failed_invalid_install_location",
        r"install_failed_dexopt",
        r"install_failed_container_error",
        r"install_failed_uid_changed",
        r"delete_failed_device_policy_manager",
        r"delete_failed_user_restricted",
        r"unknown package",
        r"not installed for \d+",
    )
]

_ADB_AMBIGUOUS_RE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"install_failed_update_incompatible",
        r"install_failed_package_changed",
        r"install_failed_internal_error",
        r"install_failed_missing_shared_library",
        r"install_failed_older_sdk",
        r"install_failed_newer_sdk",
        r"error type 3",
        r"error: activity class",
        r"does not exist",
        r"permission denial",
        r"security exception",
        r"delete_failed_internal_error",
        r"delete_failed_aborted",
    )
]

_ADB_CODE_RE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"install_parse_failed_",
        r"install_failed_invalid_apk",
        r"install_failed_version_downgrade",
        r"install_failed_conflicting_provider",
        r"install_failed_duplicate_permission",
        r"install_failed_test_only",
        r"error type 2",
    )
]

_GRADLE_NETWORK_FETCH_RE = re.compile(
    r"could not (get|head|put|download) [^'\"]*https?://", re.IGNORECASE
)

_GRADLE_ENV_RE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"failed to download [^'\"]*https?://",
        r"connection timed out",
        r"read timed out",
        r"socket timed out",
        r"connectexception",
        r"connection reset",
        r"connection refused",
        r"unknownhostexception",
        r"no such host is known",
        r"network is unreachable",
        r"broken pipe",
        r"received status code 502 from server",
        r"received status code 503 from server",
        r"received status code 504 from server",
        r"timeout waiting to lock",
        r"another gradle instance",
    )
]

_GRADLE_AMBIGUOUS_RE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"daemon disappeared",
        r"daemon has disappeared",
    )
]

_GRADLE_POSIX_ENV_EXITS = {130, 137, 143}

_DEVICE_GONE_RE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"device ['\"][^'\"]*['\"] not found",
        r"device not found",
        r"device offline",
        r"no devices",
        r"device unauthorized",
    )
]


@dataclass(frozen=True)
class FailureVerdict:
    env_class: str
    reason: str


def _summarize(text: str) -> str:
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        return "command failed (no output)"
    return lines[-1][:200]


def _first_match(re_list: list, text: str) -> bool:
    return any(rx.search(text) for rx in re_list)


def classify_adb_failure(exit_code: int, output: str) -> FailureVerdict:
    text = output or ""
    if _first_match(_ADB_ENV_RE, text):
        return FailureVerdict(CLASS_ENV, _summarize(text))
    if _first_match(_ADB_AMBIGUOUS_RE, text):
        return FailureVerdict(CLASS_AMBIGUOUS, _summarize(text))
    if _first_match(_ADB_CODE_RE, text):
        return FailureVerdict(CLASS_CODE, _summarize(text))
    return FailureVerdict(CLASS_CODE, f"adb command failed (exit {exit_code})")


def classify_gradle_failure(exit_code: int, raw_log: str) -> FailureVerdict:
    text = raw_log or ""
    if _GRADLE_NETWORK_FETCH_RE.search(text) or _first_match(_GRADLE_ENV_RE, text):
        return FailureVerdict(CLASS_ENV, _summarize(text))
    if os.name != "nt" and exit_code in _GRADLE_POSIX_ENV_EXITS:
        return FailureVerdict(
            CLASS_ENV, f"gradle process was killed by signal (exit {exit_code})"
        )
    if _first_match(_GRADLE_AMBIGUOUS_RE, text):
        return FailureVerdict(CLASS_AMBIGUOUS, _summarize(text))
    return FailureVerdict(CLASS_CODE, f"gradle build failed (exit {exit_code})")


def device_gone_reason(output: str) -> str | None:
    text = output or ""
    for rx in _DEVICE_GONE_RE:
        match = rx.search(text)
        if match:
            return match.group(0)
    return None


def adb_on_path() -> bool:
    return shutil.which("adb") is not None


def no_device_verdict() -> FailureVerdict:
    if not adb_on_path():
        return FailureVerdict(
            CLASS_ENV,
            "adb executable not found on PATH; install Android platform-tools or fix PATH",
        )
    return FailureVerdict(
        CLASS_ENV,
        "no Android device detected via adb (connect a device or start an emulator)",
    )


def exit_for(verdict: FailureVerdict) -> int:
    return EXIT_ENV if verdict.env_class in (CLASS_ENV, CLASS_AMBIGUOUS) else EXIT_FAIL


def _default_state_dir() -> Path:
    try:
        from _repo_files import SCRIPTS_DIR

        return SCRIPTS_DIR.parent / "state"
    except Exception:
        return Path(".agents") / "state"


def record_env_failure(
    verdict: FailureVerdict,
    script: str,
    serial: str | None = None,
    state_dir: Path | None = None,
) -> Path | None:
    payload = {
        "schema_version": 1,
        "env_class": verdict.env_class,
        "reason": verdict.reason,
        "script": script,
        "serial": serial,
        "exit_code": EXIT_ENV,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    target_dir = Path(state_dir) if state_dir else _default_state_dir()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / _STATE_FILE_NAME
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, target)
        return target
    except Exception:
        return None


def emit_env_failure(
    verdict: FailureVerdict,
    script: str,
    serial: str | None = None,
    state_dir: Path | None = None,
) -> int:
    note = "" if verdict.env_class == CLASS_ENV else " (ambiguous: treat as environment)"
    print(
        f"[ENV-FAILURE] {verdict.reason} — environment problem{note}. "
        "HALT: do not modify project code, Gradle files, or the manifest to "
        "bypass this; report to the developer.",
        file=sys.stderr,
    )
    record_env_failure(verdict, script, serial=serial, state_dir=state_dir)
    return EXIT_ENV
