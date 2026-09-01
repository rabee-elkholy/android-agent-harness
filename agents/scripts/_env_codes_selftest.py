"""Self-test for _env_codes.py classification. Stdlib only, no device, no network."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from _env_codes import (  # noqa: E402
    CLASS_AMBIGUOUS,
    CLASS_CODE,
    CLASS_ENV,
    EXIT_ENV,
    EXIT_FAIL,
    FailureVerdict,
    classify_adb_failure,
    classify_gradle_failure,
    device_gone_reason,
    emit_env_failure,
    exit_for,
    no_device_verdict,
    record_env_failure,
)

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"[PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label}")


def expect_class(actual: FailureVerdict, expected: str, label: str) -> None:
    check(actual.env_class == expected, f"{label} -> {actual.env_class} ({actual.reason[:80]})")


def test_adb_environment() -> None:
    for output in [
        "error: no devices/emulators found",
        "adb: no devices found",
        "adb: error: device 'RF8M1234567' not found",
        "error: device offline",
        "error: device unauthorized",
        "adb: more than one device/emulator",
        "adb server is out of date.  killing...",
        "cannot connect to daemon at tcp:5037: Connection refused",
        "Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]",
        "Failure [INSTALL_FAILED_NO_MATCHING_ABIS]",
        "Failure [INSTALL_FAILED_CPU_ABI_INCOMPATIBLE]",
        "Failure [INSTALL_FAILED_USER_RESTRICTED]",
        "Failure [INSTALL_FAILED_VERIFICATION_FAILURE]",
        "Failure [DELETE_FAILED_DEVICE_POLICY_MANAGER]",
        "Failure [DELETE_FAILED_USER_RESTRICTED]",
        "Failure [not installed for 0]",
        "adb: error: failed to connect to 192.168.1.20:5555: Connection timed out",
    ]:
        expect_class(classify_adb_failure(1, output), CLASS_ENV, f"ENV adb: {output[:60]}")


def test_adb_ambiguous() -> None:
    for output in [
        "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]",
        "Failure [INSTALL_FAILED_PACKAGE_CHANGED]",
        "Failure [INSTALL_FAILED_INTERNAL_ERROR]",
        "Failure [INSTALL_FAILED_MISSING_SHARED_LIBRARY]",
        "Failure [INSTALL_FAILED_OLDER_SDK]",
        "Error type 3",
        "Error: Activity class {com.acme.customer.MainActivity} does not exist.",
        "java.lang.SecurityException: Permission Denial: starting Intent",
        "Failure [DELETE_FAILED_ABORTED]",
    ]:
        expect_class(classify_adb_failure(1, output), CLASS_AMBIGUOUS, f"AMB adb: {output[:60]}")


def test_adb_code() -> None:
    for output in [
        "Failure [INSTALL_FAILED_VERSION_DOWNGRADE]",
        "Failure [INSTALL_PARSE_FAILED_NO_CERTIFICATES]",
        "Failure [INSTALL_FAILED_INVALID_APK]",
        "Failure [INSTALL_FAILED_CONFLICTING_PROVIDER]",
        "Failure [INSTALL_FAILED_DUPLICATE_PERMISSION]",
        "Failure [INSTALL_FAILED_TEST_ONLY]",
        "Error type 2",
    ]:
        expect_class(classify_adb_failure(1, output), CLASS_CODE, f"CODE adb: {output[:60]}")
    expect_class(
        classify_adb_failure(1, "adb: failed to install app-debug.apk: some random reason"),
        CLASS_CODE,
        "CODE adb: unknown reason defaults to code",
    )


def test_priority_env_wins() -> None:
    mixed = (
        "Failure [INSTALL_FAILED_ALREADY_EXISTS]\n"
        "Caused by: INSTALL_FAILED_UPDATE_INCOMPATIBLE"
    )
    expect_class(classify_adb_failure(1, mixed), CLASS_ENV, "priority: ENV beats AMBIGUOUS")


def test_gradle_environment() -> None:
    for output in [
        "Could not GET 'https://dl.google.com/dl/android/maven2/a.pom'. > Connection timed out",
        "Caused by: java.net.UnknownHostException: repo.maven.apache.org",
        "Caused by: java.net.ConnectException: Connection refused",
        "What went wrong: Could not resolve all files ... > Read timed out",
        "Received status code 502 from server: Bad Gateway",
        "Timeout waiting to lock buildscript class cache",
        "Gradle could not start your build: another Gradle instance is running",
    ]:
        expect_class(classify_gradle_failure(1, output), CLASS_ENV, f"ENV gradle: {output[:60]}")
    check(
        classify_gradle_failure(1, "Could not get unknown property 'extra' for task ':app'").env_class
        == CLASS_CODE,
        "gradle unknown-property is CODE (not network)",
    )


def test_gradle_ambiguous() -> None:
    expect_class(
        classify_gradle_failure(1, "The Gradle daemon disappeared unexpectedly"),
        CLASS_AMBIGUOUS,
        "AMB gradle: daemon disappeared",
    )


def test_gradle_code() -> None:
    for output in [
        "e: file:///app/src/main/x.kt:10:5 Unresolved reference: foo",
        "BUILD FAILED in 2s",
        "Could not resolve all dependencies for configuration ':app:debugRuntimeClasspath'.",
    ]:
        expect_class(classify_gradle_failure(1, output), CLASS_CODE, f"CODE gradle: {output[:60]}")


def test_gradle_posix_signal_codes() -> None:
    if os.name == "nt":
        print("[SKIP] posix signal exit codes (windows)")
        return
    expect_class(classify_gradle_failure(137, "BUILD FAILED"), CLASS_ENV, "gradle exit 137 is ENV")


def test_exit_for_mapping() -> None:
    check(exit_for(FailureVerdict(CLASS_ENV, "x")) == EXIT_ENV, "exit_for ENV -> 30")
    check(exit_for(FailureVerdict(CLASS_AMBIGUOUS, "x")) == EXIT_ENV, "exit_for AMBIGUOUS -> 30")
    check(exit_for(FailureVerdict(CLASS_CODE, "x")) == EXIT_FAIL, "exit_for CODE -> 1")


def test_device_gone_detector() -> None:
    check(device_gone_reason("error: device offline") == "device offline", "detect device offline")
    check("not found" in (device_gone_reason("adb: error: device 'x' not found") or ""), "detect device 'x' not found")
    check(device_gone_reason("Success") is None, "no false positive on clean output")
    check(device_gone_reason("") is None, "no false positive on empty output")


def test_no_device_verdict() -> None:
    verdict = no_device_verdict()
    check(verdict.env_class == CLASS_ENV, "no_device_verdict is ENV")
    check(bool(verdict.reason), "no_device_verdict has a reason")


def test_record_env_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        verdict = FailureVerdict(CLASS_ENV, "test reason")
        target = record_env_failure(verdict, "selftest.py", serial="SER123", state_dir=state_dir)
        check(target is not None and target.is_file(), "env_failure.json written")
        data = json.loads(target.read_text(encoding="utf-8"))
        check(data.get("schema_version") == 1, "schema_version present")
        check(data.get("env_class") == CLASS_ENV, "env_class recorded")
        check(data.get("reason") == "test reason", "reason recorded")
        check(data.get("script") == "selftest.py", "script recorded")
        check(data.get("serial") == "SER123", "serial recorded")
        check(data.get("exit_code") == EXIT_ENV, "exit_code recorded")
        check(bool(data.get("timestamp")), "timestamp recorded")
        target.write_text("{corrupted", encoding="utf-8")
        target2 = record_env_failure(
            FailureVerdict(CLASS_AMBIGUOUS, "rewrite"), "selftest.py", state_dir=state_dir
        )
        check(target2 is not None, "corrupted file is safely overwritten")
        data2 = json.loads(target2.read_text(encoding="utf-8"))
        check(data2.get("env_class") == CLASS_AMBIGUOUS, "overwrite persisted")


def test_emit_env_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        verdict = FailureVerdict(CLASS_AMBIGUOUS, "ambiguous test")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = emit_env_failure(verdict, "selftest.py", state_dir=state_dir)
        check(code == EXIT_ENV, "emit returns 30")
        check("[ENV-FAILURE]" in err.getvalue(), "stderr carries [ENV-FAILURE] marker")
        check((state_dir / "env_failure.json").is_file(), "state file written by emit")


def main() -> int:
    test_adb_environment()
    test_adb_ambiguous()
    test_adb_code()
    test_priority_env_wins()
    test_gradle_environment()
    test_gradle_ambiguous()
    test_gradle_code()
    test_gradle_posix_signal_codes()
    test_exit_for_mapping()
    test_device_gone_detector()
    test_no_device_verdict()
    test_record_env_failure()
    test_emit_env_failure()
    if FAILURES:
        print(f"\n[FAIL] {len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("\n[SUCCESS] ENV CODES SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
