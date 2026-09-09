"""Physical-device install/launch with a live adb task log.

Usage:
  python .agents/scripts/run_device.py install
  python .agents/scripts/run_device.py start
  python .agents/scripts/run_device.py install-start
  python .agents/scripts/run_device.py uninstall
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env_codes import (  # noqa: E402
    CLASS_ENV,
    EXIT_ENV,
    FailureVerdict,
    classify_adb_failure,
    emit_env_failure,
    exit_for,
    no_device_verdict,
)
from _gate_results import current_head_sha, gate_artifact_name, read_gate_result, write_gate_result  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print, run_streaming  # noqa: E402
from _product import (  # noqa: E402
    ALLOW_EMULATOR,
    APPLICATION_ID,
    ASSEMBLE_TASK,
    LAUNCHER,
    PRODUCT_NAME,
)
from _repo_files import REPO, first_adb_serial  # noqa: E402
from _variants import apk_relative, resolve_or_raise  # noqa: E402
from artifact_set import build_artifact_set, verify_artifact_set  # noqa: E402
from delivery_manifest import build_manifest  # noqa: E402
from _vnext_common import HarnessError, sha256_bytes  # noqa: E402

DEFAULT_ACTIVITY = LAUNCHER
ADB_ERROR_MARKERS = (
    "error type", "activity class", "does not exist", "securityexception",
    "exception occurred", "failure [",
)


def adb_result_ok(code: int, log: str) -> bool:
    lowered = str(log or "").lower()
    return code == 0 and not any(marker in lowered for marker in ADB_ERROR_MARKERS)


def record_device(
    action: str,
    status: str,
    exit_code: int,
    serial: str | None,
    env_class: str = "",
    detail: str = "",
    artifact_set_sha: str = "",
    install_reference: str = "",
    application_id: str = "",
    target_user: str = "",
    preexisting_package: bool | None = None,
) -> None:
    payload = {
        "schema_version": 2,
        "action": action,
        "status": status,
        "exit_code": exit_code,
        "env_class": env_class,
        "serial_sha256": sha256_bytes(serial.encode("utf-8")) if serial else None,
        "git_sha": current_head_sha(),
        "detail": detail,
    }
    if artifact_set_sha:
        payload["artifact_set_sha256"] = artifact_set_sha
    if install_reference:
        payload["install_reference"] = install_reference
    if application_id:
        payload["application_id"] = application_id
    if target_user:
        payload["target_user"] = target_user
    if preexisting_package is not None:
        payload["preexisting_package"] = preexisting_package
    name = "device_install" if action == "install" else "device_launch" if action == "start" else "device"
    write_gate_result(name, payload)
    write_gate_result("device", payload)


def require_serial(explicit: str | None) -> str:
    allow_emu = bool(ALLOW_EMULATOR)
    serial = explicit or first_adb_serial(allow_emulator=allow_emu)
    if not serial:
        verdict = no_device_verdict()
        record_device("require-serial", "ENV", EXIT_ENV, serial, verdict.env_class, verdict.reason)
        emit_env_failure(verdict, "run_device.py")
        sys.exit(EXIT_ENV)
    is_emulator = serial.startswith("emulator-") or serial.startswith("localhost:") or serial.startswith("127.0.0.1:")
    if not is_emulator:
        try:
            probe = subprocess.run(
                ["adb", "-s", serial, "shell", "getprop", "ro.kernel.qemu"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=5,
            )
            is_emulator = probe.returncode == 0 and (probe.stdout or "").strip() == "1"
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not allow_emu and is_emulator:
        verdict = FailureVerdict(
            CLASS_ENV,
            "Emulator targeting is forbidden by project policy. Connect a physical device.",
        )
        record_device("require-serial", "ENV", EXIT_ENV, serial, verdict.env_class, verdict.reason)
        emit_env_failure(verdict, "run_device.py", serial=serial)
        sys.exit(EXIT_ENV)
    return serial



def run_adb(serial: str, adb_args: list[str], label: str) -> tuple[int, str]:
    live_print(f"[*] adb -s {serial} {' '.join(adb_args)}")
    code, log, _ = run_streaming(
        ["adb", "-s", serial, *adb_args],
        cwd=str(REPO),
        heartbeat_sec=10.0,
        should_echo=lambda line: bool(line.strip()),
        label=label,
    )
    return code, log


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description=f"Live adb install/start for {PRODUCT_NAME}")
    parser.add_argument("action", choices=["install", "start", "install-start", "uninstall"])
    parser.add_argument("-s", "--serial", default=None, help="Physical device serial")
    parser.add_argument(
        "--flavor",
        default=None,
        help="Build flavor for APK resolution (default: ACTIVE_FLAVOR in _product.py).",
    )
    parser.add_argument("--apk", action="append", default=None, help="APK path; repeat for split APK sets")
    parser.add_argument("--activity", default=DEFAULT_ACTIVITY, help="Launch activity")
    parser.add_argument("--package", default=APPLICATION_ID, help="Package name to uninstall")
    parser.add_argument("--user", default=None, help="Target user ID for multi-user / work profile devices (e.g. 0)")
    parser.add_argument("--force", action="store_true", help="Bypass APK freshness check (emergency manual use only)")
    parser.add_argument("--grant-runtime-permissions", action="store_true", help="Explicitly grant requested runtime permissions during install")
    parser.add_argument("--confirm-destructive", action="store_true", help="Required for uninstall")
    args = parser.parse_args()

    try:
        active_flavor, _task = resolve_or_raise(args.flavor)
    except SystemExit as exc:
        live_print(str(exc), err=True)
        return 1

    variant_note = f" (variant: {active_flavor})" if active_flavor else ""
    serial = require_serial(args.serial)
    live_print(f"[*] Physical device{variant_note}: {serial}")

    if args.action == "uninstall":
        if not args.confirm_destructive:
            live_print("[FAIL] Uninstall requires --confirm-destructive and explicit developer authorization.", err=True)
            return 1
        live_print(f"[*] Uninstalling {args.package} from {serial}")
        code, log = run_adb(serial, ["uninstall", args.package], "adb uninstall")
        if not adb_result_ok(code, log):
            code = code or 1
            verdict = classify_adb_failure(code, log)
            live_print(f"[!] adb uninstall failed (exit {code})", err=True)
            record_device(args.action, "ENV" if verdict.env_class != "CODE" else "FAIL", exit_for(verdict), serial, verdict.env_class, verdict.reason)
            emit_env_failure(verdict, "run_device.py", serial=serial)
            return exit_for(verdict)
        record_device(args.action, "PASS", 0, serial)
        live_print(f"[+] Uninstall finished for {args.package}")
        return 0

    artifact_set = None
    apk_paths: list[Path] = []
    if args.action in ("install", "install-start"):
        try:
            assemble_record = read_gate_result(gate_artifact_name(_task)) or {}
            recorded = assemble_record.get("artifact_set")
            if args.force and args.apk:
                apk_paths = [Path(item).resolve() if Path(item).is_absolute() else (REPO / item).resolve() for item in args.apk]
                artifact_set = build_artifact_set(REPO, _task, apk_paths, application_id=APPLICATION_ID)
            elif args.force:
                if isinstance(recorded, dict):
                    artifact_set = recorded
                    apk_paths = verify_artifact_set(REPO, recorded)
                else:
                    fallback = REPO / apk_relative()
                    artifact_set = build_artifact_set(REPO, _task, [fallback], application_id=APPLICATION_ID)
                    apk_paths = [fallback]
            else:
                if assemble_record.get("status") != "PASS" or not isinstance(recorded, dict):
                    raise HarnessError(f"passing assemble evidence is missing for {_task}")
                apk_paths = verify_artifact_set(REPO, recorded)
                artifact_set = recorded
                if args.apk:
                    requested_paths = [Path(item).resolve() if Path(item).is_absolute() else (REPO / item).resolve() for item in args.apk]
                    requested = build_artifact_set(REPO, _task, requested_paths, application_id=str(recorded.get("application_id") or APPLICATION_ID))
                    if requested["artifact_set_sha256"] != recorded.get("artifact_set_sha256"):
                        raise HarnessError("explicit APK paths do not match the active assemble artifact set")
                current_manifest = build_manifest(REPO)
                for field in ("delivery_snapshot_sha256", "change_set_sha256", "external_inputs_sha256"):
                    if assemble_record.get(field) != current_manifest.get(field):
                        raise HarnessError(f"assemble evidence is stale: {field}")
        except HarnessError as exc:
            verdict = FailureVerdict(CLASS_ENV, str(exc))
            record_device("install", "ENV", EXIT_ENV, serial, verdict.env_class, verdict.reason)
            emit_env_failure(verdict, "run_device.py", serial=serial)
            return EXIT_ENV
    artifact_set_sha = str((artifact_set or {}).get("artifact_set_sha256") or "")
    actual_application_id = str((artifact_set or {}).get("application_id") or APPLICATION_ID)
    target_user = str(args.user) if args.user is not None else "current"
    preexisting_package: bool | None = None
    if args.action in ("install", "install-start"):
        probe_args = ["adb", "-s", serial, "shell", "pm", "path"]
        if args.user is not None:
            probe_args.extend(["--user", str(args.user)])
        probe_args.append(actual_application_id)
        try:
            probe = subprocess.run(
                probe_args, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False, timeout=10.0,
            )
            preexisting_package = probe.returncode == 0 and "package:" in (probe.stdout or "")
        except (OSError, subprocess.TimeoutExpired):
            preexisting_package = None
    if args.action == "start" and not artifact_set_sha:
        prior_install = read_gate_result("device_install") or {}
        prior_hash = str(prior_install.get("artifact_set_sha256") or "")
        assemble_record = read_gate_result(gate_artifact_name(_task)) or {}
        recorded = assemble_record.get("artifact_set")
        try:
            if isinstance(recorded, dict):
                verify_artifact_set(REPO, recorded)
                artifact_set = recorded
                artifact_set_sha = str(recorded.get("artifact_set_sha256") or "")
        except HarnessError:
            artifact_set_sha = ""
        if not artifact_set_sha or artifact_set_sha != prior_hash:
            live_print("[FAIL] Start requires install evidence for the active artifact set.", err=True)
            record_device("start", "FAIL", 1, serial, "CODE", "missing install evidence")
            return 1

    if args.action in ("install", "install-start"):
        if not apk_paths or any(not apk.is_file() for apk in apk_paths):
            live_print("[ERROR] One or more APK artifacts are missing.", err=True)
            live_print(f"Assemble debug first: python .agents/scripts/run_gradle_task.py {ASSEMBLE_TASK}", err=True)
            verdict = FailureVerdict(
                CLASS_ENV,
                "APK artifact set is incomplete (pipeline order: assemble before install)",
            )
            record_device("install", "ENV", EXIT_ENV, serial, verdict.env_class, verdict.reason, artifact_set_sha=artifact_set_sha, application_id=actual_application_id, target_user=target_user, preexisting_package=preexisting_package)
            emit_env_failure(verdict, "run_device.py", serial=serial)
            return EXIT_ENV
        total_mb = sum(apk.stat().st_size for apk in apk_paths) / (1024 * 1024)
        live_print(f"[*] Installing {len(apk_paths)} APK artifact(s) ({total_mb:.1f} MB)")
        install_cmd = ["install-multiple" if len(apk_paths) > 1 else "install", "-r"]
        if args.grant_runtime_permissions:
            install_cmd.append("-g")
        if args.user is not None:
            install_cmd.extend(["--user", str(args.user)])
        install_cmd.extend(str(apk) for apk in apk_paths)
        code, log = run_adb(serial, install_cmd, "adb install")
        if not adb_result_ok(code, log):
            code = code or 1
            verdict = classify_adb_failure(code, log)
            live_print(f"[!] adb install failed (exit {code})", err=True)
            record_device("install", "ENV" if verdict.env_class != "CODE" else "FAIL", exit_for(verdict), serial, verdict.env_class, verdict.reason, artifact_set_sha=artifact_set_sha, application_id=actual_application_id, target_user=target_user, preexisting_package=preexisting_package)
            emit_env_failure(verdict, "run_device.py", serial=serial)
            return exit_for(verdict)
        install_status = "EMERGENCY_UNVERIFIED" if args.force else "PASS"
        detail = "runtime permissions granted by explicit flag" if args.grant_runtime_permissions else ""
        record_device("install", install_status, 0, serial, detail=detail, artifact_set_sha=artifact_set_sha, application_id=actual_application_id, target_user=target_user, preexisting_package=preexisting_package)
        live_print("[+] Install finished")

    if args.action in ("start", "install-start"):
        target_activity = args.activity
        if target_activity == DEFAULT_ACTIVITY and "/" in target_activity:
            target_activity = actual_application_id + "/" + target_activity.split("/", 1)[1]
        if "/" not in target_activity:
            target_activity = (
                f"{actual_application_id}/{target_activity if target_activity.startswith('.') else '.' + target_activity}"
            )
        live_print(f"[*] Launching target Activity: {target_activity}")
        code, log = run_adb(
            serial,
            ["shell", "am", "start", "-n", target_activity],
            "am start",
        )
        if not adb_result_ok(code, log):
            code = code or 1
            verdict = classify_adb_failure(code, log)
            live_print(f"[!] am start failed (exit {code})", err=True)
            record_device("start", "ENV" if verdict.env_class != "CODE" else "FAIL", exit_for(verdict), serial, verdict.env_class, verdict.reason, artifact_set_sha=artifact_set_sha, install_reference=artifact_set_sha, application_id=actual_application_id, target_user=target_user)
            emit_env_failure(verdict, "run_device.py", serial=serial)
            return exit_for(verdict)
        record_device("start", "PASS", 0, serial, artifact_set_sha=artifact_set_sha, install_reference=artifact_set_sha, application_id=actual_application_id, target_user=target_user)
        live_print(f"[+] Launched {target_activity}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
