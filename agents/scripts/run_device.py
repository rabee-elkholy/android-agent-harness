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
from _live_process import enable_line_buffered_stdio, live_print, run_streaming, step_progress, sublog  # noqa: E402
from _product import (  # noqa: E402
    ALLOW_EMULATOR,
    APPLICATION_ID,
    ASSEMBLE_TASK,
    LAUNCHER,
    PRODUCT_NAME,
)
try:
    from _product import DEVICE_TARGET_POLICY  # type: ignore[attr-defined]  # noqa: E402
except ImportError:  # Backward compatibility with pre-v1.0.2 installations.
    DEVICE_TARGET_POLICY = "allow" if ALLOW_EMULATOR else "physical-only"
from _repo_files import REPO, adb_serial_is_emulator, first_adb_serial, matching_adb_serials  # noqa: E402
from _variants import apk_relative, resolve_or_raise  # noqa: E402
from artifact_set import build_artifact_set, verify_artifact_set  # noqa: E402
from delivery_manifest import build_manifest  # noqa: E402
from _vnext_common import HarnessError, sha256_bytes  # noqa: E402
from _verification_recipes import VERIFICATION_RECIPES, get_verification_recipes  # noqa: E402

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
    policy = str(DEVICE_TARGET_POLICY or ("allow" if ALLOW_EMULATOR else "physical-only"))
    if explicit:
        serial = explicit
    else:
        matches = matching_adb_serials(policy=policy)
        if not matches:
            verdict = no_device_verdict()
            record_device("require-serial", "ENV", EXIT_ENV, None, verdict.env_class, verdict.reason)
            emit_env_failure(verdict, "run_device.py")
            sys.exit(EXIT_ENV)
        if len(matches) > 1:
            verdict = FailureVerdict(
                CLASS_ENV,
                f"Multiple matching target devices detected ({', '.join(matches)}). Specify device explicitly via --serial <serial>.",
            )
            record_device("require-serial", "ENV", EXIT_ENV, None, verdict.env_class, verdict.reason)
            emit_env_failure(verdict, "run_device.py")
            sys.exit(EXIT_ENV)
        serial = matches[0]
    is_emulator = adb_serial_is_emulator(serial)
    if policy == "physical-only" and is_emulator:
        verdict = FailureVerdict(
            CLASS_ENV,
            "Emulator targeting is forbidden by project policy. Connect a physical device.",
        )
        record_device("require-serial", "ENV", EXIT_ENV, serial, verdict.env_class, verdict.reason)
        emit_env_failure(verdict, "run_device.py", serial=serial)
        sys.exit(EXIT_ENV)
    if policy == "emulator-only" and not is_emulator:
        verdict = FailureVerdict(CLASS_ENV, "Physical-device targeting is forbidden by project policy. Start an emulator.")
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


def resolve_target_user(serial: str, requested: str | None) -> str:
    value = str(requested) if requested is not None else "current"
    if value == "current":
        try:
            result = subprocess.run(
                ["adb", "-s", serial, "shell", "am", "get-current-user"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=10.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HarnessError("cannot resolve the current Android user") from exc
        if result.returncode != 0:
            raise HarnessError("cannot resolve the current Android user")
        value = result.stdout.strip()
    if not value.isascii() or not value.isdecimal():
        raise HarnessError("target user must resolve to one numeric Android user id")
    return str(int(value))


def _read_harness_version(repo: Path) -> str:
    for candidate in (
        repo / ".agents" / "VERSION",
        repo / "agents" / "VERSION",
        Path(__file__).resolve().parent.parent / "VERSION",
    ):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return "1.0.0"


def _gate_passed(state_root: Path, current_run: dict, gate_name: str) -> bool:
    snapshot = str(current_run.get("delivery_snapshot_sha256") or "")
    run_id = str(current_run.get("run_id") or "")
    change_set = str(current_run.get("change_set_sha256") or "")
    if not change_set and current_run.get("manifest"):
        try:
            from _vnext_common import read_json
            manifest_p = Path(str(current_run["manifest"]))
            if manifest_p.is_file():
                change_set = str(read_json(manifest_p).get("change_set_sha256") or "")
        except Exception:
            pass
    if snapshot and run_id and change_set:
        try:
            from evidence_store import EvidenceStore
            from final_verifier import _validate_artifact
            store = EvidenceStore(state_root)
            harness_version = _read_harness_version(REPO)
            record, error = _validate_artifact(store, snapshot, change_set, run_id, gate_name, harness_version)
            if error is None:
                return True
            res_path = state_root / "results" / f"{gate_name}.json"
            if res_path.is_file():
                from _vnext_common import read_json
                res_data = read_json(res_path)
                if (
                    res_data.get("delivery_snapshot_sha256") == snapshot
                    and res_data.get("change_set_sha256") == change_set
                    and str(res_data.get("status") or "").upper() == "PASS"
                ):
                    producer_defaults = {
                        "assemble": "run_gradle_task",
                        "preflight": "preflight_check",
                        "localization": "check_strings",
                        "room": "room_guard",
                        "unit_tests": "run_tests_gate",
                        "device_install": "run_device",
                        "device_launch": "run_device",
                    }
                    producer = str(res_data.get("producer") or producer_defaults.get(gate_name) or gate_name).replace(".py", "").replace("-", "_")
                    store.write(
                        snapshot=snapshot,
                        run_id=run_id,
                        name=gate_name,
                        producer=producer,
                        harness_version=str(res_data.get("harness_version") or harness_version),
                        change_set=change_set,
                        status="PASS",
                        exit_code=int(res_data.get("exit_code") or 0),
                        detail=str(res_data.get("detail") or "bridged on-the-fly from results cache"),
                    )
                    record, err2 = _validate_artifact(store, snapshot, change_set, run_id, gate_name, harness_version)
                    return err2 is None
            return False
        except Exception:
            return False
    return False


def _handle_status(args: argparse.Namespace) -> int:
    policy = str(DEVICE_TARGET_POLICY or ("allow" if ALLOW_EMULATOR else "physical-only"))
    all_devices = matching_adb_serials(policy="allow")
    policy_devices = matching_adb_serials(policy=policy)
    live_print(f"[*] Target policy: {policy}")
    if not all_devices:
        live_print("[-] No connected Android devices or emulators detected via adb.")
        return 0
    live_print(f"[+] Detected devices ({len(all_devices)}):")
    for s in all_devices:
        kind = "emulator" if adb_serial_is_emulator(s) else "physical"
        eligible = "eligible" if s in policy_devices else "ineligible (policy)"
        live_print(f"    - {s} ({kind}, {eligible})")
    if policy_devices:
        live_print(f"[*] Default resolved target: {policy_devices[0]}")
    else:
        live_print(f"[!] No devices match current policy ({policy})")
    return 0


def _check_device_prerequisites(args: argparse.Namespace) -> int | None:
    if getattr(args, "force", False) or args.action in ("uninstall", "signoff", "status"):
        return None
    try:
        from mutation_guard import active_plan
        from _vnext_common import read_json
        active = active_plan(REPO)
    except Exception:
        return None
    status = str(active.get("status") or "")
    if status == "IMPLEMENTING":
        live_print(
            "[FAIL] Device operation is blocked during IMPLEMENTING. Transition to verification via 'python .agents/scripts/workflow.py prepare-verification' first.",
            err=True,
        )
        return EXIT_ENV
    if status == "VERIFYING" and args.action in ("install", "start", "install-start"):
        task_id = str(active.get("task_id") or "")
        state = REPO / ".agents/state" if (REPO / ".agents").is_dir() else REPO / "agents/state"
        current_path = state / "tasks" / task_id / "current-run.json"
        if not current_path.is_file():
            live_print(
                "[FAIL] Verification run is not initialized. Run 'python .agents/scripts/workflow.py prepare-verification' first.",
                err=True,
            )
            return EXIT_ENV
        try:
            from _vnext_common import read_json
            current_run = read_json(current_path)
            current_task_id = str(current_run.get("task_id") or "")
            if not current_task_id or current_task_id != task_id:
                live_print(
                    f"[FAIL] Verification run task mismatch: active task expects '{task_id}', but current-run is '{current_task_id}'.",
                    err=True,
                )
                return EXIT_ENV
            snapshot = str(current_run.get("delivery_snapshot_sha256") or "")
            if not snapshot:
                live_print(
                    "[FAIL] Verification run is missing delivery_snapshot_sha256.",
                    err=True,
                )
                return EXIT_ENV
            from delivery_manifest import build_manifest
            current_snapshot = str(build_manifest(REPO).get("delivery_snapshot_sha256") or "")
            if not current_snapshot or current_snapshot != snapshot:
                live_print(
                    f"[FAIL] Stale delivery snapshot in current-run ({snapshot} != active {current_snapshot}).",
                    err=True,
                )
                return EXIT_ENV
            run_id = str(current_run.get("run_id") or "")
            expected_run_id = str(active.get("verification_run_id") or "")
            if not run_id or (expected_run_id and run_id != expected_run_id):
                live_print(
                    f"[FAIL] Verification run mismatch: active task expects run '{expected_run_id}', but current-run is '{run_id}'.",
                    err=True,
                )
                return EXIT_ENV
            policy_path = Path(str(current_run.get("policy") or ""))
            if not policy_path.is_file():
                live_print(
                    f"[FAIL] Verification policy artifact is missing: {policy_path}.",
                    err=True,
                )
                return EXIT_ENV
            policy = read_json(policy_path)
            manifest_path = Path(str(current_run.get("manifest") or ""))
            recorded_manifest = read_json(manifest_path) if manifest_path.is_file() else {}
            task_changes = recorded_manifest.get("task_changes") if "task_changes" in recorded_manifest else None
            from final_verifier import validate_policy_artifact
            expected_policy, policy_error, _ = validate_policy_artifact(
                REPO, active, policy, state, policy_path, task_changes=task_changes
            )
            if policy_error:
                live_print(f"[FAIL] Invalid verification policy: {policy_error}.", err=True)
                return EXIT_ENV
            required_gates = set(expected_policy.get("gates") or [])
            if not required_gates:
                live_print("[FAIL] Verification policy defines no required gates.", err=True)
                return EXIT_ENV
            if "preflight" in required_gates and not _gate_passed(state, current_run, "preflight"):
                live_print("[FAIL] Pipeline order violation: preflight_check must pass before device deployment.", err=True)
                return EXIT_ENV
            if "unit_tests" in required_gates and not _gate_passed(state, current_run, "unit_tests"):
                live_print("[FAIL] Pipeline order violation: run_tests_gate must pass before device deployment.", err=True)
                return EXIT_ENV
            reviewers = list(expected_policy.get("reviewers") or [])
            if reviewers:
                try:
                    from evidence_store import EvidenceStore
                    from final_verifier import _validate_artifact
                    store = EvidenceStore(state)
                    harness_version = _read_harness_version(REPO)
                    change_set = str(current_run.get("change_set_sha256") or "")
                    rev_record, rev_error = _validate_artifact(store, snapshot, change_set, run_id, "reviews", harness_version)
                    if rev_error is not None:
                        live_print(f"[FAIL] Pipeline order violation: required reviews must pass before device deployment ({rev_error}).", err=True)
                        return EXIT_ENV
                    rev_ev = rev_record.get("evidence") or {}
                    if not rev_ev.get("developer_override"):
                        covered = set(rev_ev.get("reviewers") or [])
                        if not set(reviewers) <= covered:
                            live_print("[FAIL] Pipeline order violation: required reviewer coverage is incomplete before device deployment.", err=True)
                            return EXIT_ENV
                        if rev_ev.get("blocking_findings"):
                            live_print("[FAIL] Pipeline order violation: reviews contain unresolved blocking findings before device deployment.", err=True)
                            return EXIT_ENV
                except Exception as exc:
                    live_print(f"[FAIL] Pipeline order violation: required reviews check failed: {exc}", err=True)
                    return EXIT_ENV
        except Exception as exc:
            live_print(f"[FAIL] Failed to verify device prerequisites: {exc}", err=True)
            return EXIT_ENV
    return None


def _handle_signoff(args: argparse.Namespace) -> int:
    import os
    from mutation_guard import active_plan
    from _vnext_common import read_json, canonical_sha256, ValidationError
    from workflow import assert_active_run_fresh
    task_id = args.task_id
    if not task_id:
        try:
            active = active_plan(REPO)
            task_id = str(active.get("task_id") or "")
        except Exception:
            task_id = ""
    if not task_id:
        live_print("[FAIL] --task-id is required for device sign-off.", err=True)
        return 1

    # Invariant: human device sign-off must not be self-certified by the implementation agent
    verdict = str(args.verdict or "PASS").upper()
    source = getattr(args, "source", None) or os.environ.get("HARNESS_AUTHORITY_SOURCE")
    if verdict == "PASS":
        if not source or source not in ("developer_terminal", "host_native", "conversation"):
            live_print(
                "[FAIL] Device sign-off with verdict PASS requires explicit developer authority via "
                "--source developer_terminal or host-native approval.",
                err=True,
            )
            return 1
        if source == "conversation" and not getattr(args, "approval_token", None):
            live_print("[FAIL] Conversation device signoff requires a trusted host approval token.", err=True)
            return 1

    proof_ref = str(args.proof_reference or "").strip()
    if not proof_ref:
        live_print("[FAIL] --proof-reference is required for device sign-off.", err=True)
        return 1

    state = REPO / ".agents/state" if (REPO / ".agents").is_dir() else REPO / "agents/state"
    try:
        current_run = assert_active_run_fresh(REPO, task_id)
    except Exception as exc:
        live_print(f"[FAIL] Active run freshness check failed for device sign-off: {exc}", err=True)
        return 1

    snapshot = str(current_run.get("delivery_snapshot_sha256") or "")
    run_id = str(current_run.get("run_id") or "")
    change_set = str(current_run.get("change_set_sha256") or "")
    plan_path = state / "tasks" / task_id / "plan.json"
    plan = read_json(plan_path) if plan_path.is_file() else {}

    from evidence_store import EvidenceStore
    store = EvidenceStore(state)
    harness_version = _read_harness_version(REPO)

    # Artifact chain validation: device_install evidence must exist for this run
    install_sha = ""
    install_ev = {}
    try:
        rec_inst = store.read(snapshot, run_id, "device_install")
        install_ev = rec_inst.get("evidence") or {}
        install_sha = str(install_ev.get("artifact_set_sha256") or "")
    except Exception:
        pass

    if verdict == "PASS" and not install_sha:
        live_print(f"[FAIL] Device sign-off requires prior successful device_install evidence for run {run_id[:12]}.", err=True)
        return 1

    assemble_sha = ""
    try:
        rec_asm = store.read(snapshot, run_id, "assemble")
        assemble_ev = rec_asm.get("evidence") or {}
        assemble_sha = str(assemble_ev.get("artifact_set_sha256") or (assemble_ev.get("artifact_set") or {}).get("artifact_set_sha256") or "")
    except Exception:
        pass

    if assemble_sha and install_sha and assemble_sha != install_sha:
        live_print(
            f"[FAIL] Device sign-off artifact set mismatch: assemble ({assemble_sha[:12]}) != device_install ({install_sha[:12]}).",
            err=True,
        )
        return 1

    final_art_sha = install_sha or assemble_sha
    store.write(
        snapshot=snapshot,
        run_id=run_id,
        name="device_signoff",
        producer="developer_approval",
        harness_version=harness_version,
        change_set=change_set,
        status=verdict,
        evidence={
            "task_id": task_id,
            "plan_sha256": plan.get("plan_sha256") or "",
            "run_id": run_id,
            "delivery_snapshot_sha256": snapshot,
            "change_set_sha256": change_set,
            "artifact_set_sha256": final_art_sha,
            "approval_source": source or "developer_terminal",
            "enforcement_tier": "HARD_ENFORCED" if source == "host_native" else "RULE_ENFORCED",
            "proof_reference": proof_ref,
            "proof_reference_sha256": canonical_sha256(proof_ref),
            "verdict": verdict,
            "target_user": str(install_ev.get("target_user") or install_ev.get("user") or getattr(args, "user", None) or "0"),
            "serial_sha256": str(install_ev.get("serial_sha256") or install_ev.get("serial_hash") or ""),
            "serial_hash": str(install_ev.get("serial_sha256") or install_ev.get("serial_hash") or ""),
            "application_id": str(install_ev.get("application_id") or APPLICATION_ID),
            "signer": os.environ.get("USERNAME") or os.environ.get("USER") or "developer",
        },
    )
    live_print(f"[SUCCESS] Device sign-off recorded: verdict={verdict} for task {task_id} (run {run_id[:12]})")
    return 0 if verdict == "PASS" else 1


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description=f"Live adb install/start for {PRODUCT_NAME}")
    parser.add_argument("action", choices=["install", "start", "install-start", "uninstall", "signoff", "status"])
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
    parser.add_argument("--task-id", default=None, help="Task ID for signoff")
    parser.add_argument("--proof-reference", default=None, help="Proof reference / reason for signoff")
    parser.add_argument("--verdict", choices=["PASS", "FAIL"], default="PASS", help="Signoff verdict")
    parser.add_argument("--source", choices=["developer_terminal", "host_native", "conversation"], default=None, help="Authority source for signoff")
    parser.add_argument("--approval-token", default=None, help="Trusted approval token from developer prompt")
    args = parser.parse_args()

    prereq_err = _check_device_prerequisites(args)
    if prereq_err is not None:
        return prereq_err

    if args.action == "status":
        return _handle_status(args)

    if args.action == "signoff":
        return _handle_signoff(args)

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
    if args.action in ("install", "install-start", "start"):
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
    try:
        target_user = resolve_target_user(serial, args.user)
    except HarnessError as exc:
        record_device(args.action, "ENV", EXIT_ENV, serial, "ENV", str(exc))
        live_print(f"[FAIL] {exc}", err=True)
        return EXIT_ENV
    target_activity = ""
    if args.action in ("start", "install-start"):
        target_activity = args.activity
        if target_activity == DEFAULT_ACTIVITY and "/" in target_activity:
            original_package, activity_class = target_activity.split("/", 1)
            if activity_class.startswith("."):
                activity_class = original_package + activity_class
            target_activity = actual_application_id + "/" + activity_class
        elif "/" not in target_activity:
            activity_class = target_activity if target_activity.startswith(".") or "." in target_activity else "." + target_activity
            target_activity = actual_application_id + "/" + activity_class
        if target_activity.split("/", 1)[0] != actual_application_id:
            record_device("start", "FAIL", 1, serial, "CODE", "activity package differs from assembled application id")
            return 1
    preexisting_package: bool | None = None
    if args.action in ("install", "install-start"):
        probe_args = ["adb", "-s", serial, "shell", "pm", "path"]
        probe_args.extend(["--user", target_user])
        probe_args.append(actual_application_id)
        try:
            probe = subprocess.run(
                probe_args, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False, timeout=10.0,
            )
            preexisting_package = probe.returncode == 0 and "package:" in (probe.stdout or "")
        except (OSError, subprocess.TimeoutExpired):
            preexisting_package = None
    if args.action == "start":
        prior_install = read_gate_result("device_install") or {}
        expected = {
            "status": "PASS", "artifact_set_sha256": artifact_set_sha,
            "application_id": actual_application_id, "target_user": target_user,
            "serial_sha256": sha256_bytes(serial.encode("utf-8")),
            **{field: assemble_record.get(field) for field in ("delivery_snapshot_sha256", "change_set_sha256", "external_inputs_sha256")},
        }
        if not artifact_set_sha or any(not value or prior_install.get(field) != value for field, value in expected.items()):
            live_print("[FAIL] Start requires passing install evidence for the same artifact, device, user, application and snapshot.", err=True)
            record_device("start", "FAIL", 1, serial, "CODE", "install identity mismatch")
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
        install_cmd.extend(["--user", target_user])
        install_cmd.extend(str(apk) for apk in apk_paths)
        with step_progress("Installing APK on device"):
            sublog(f"Target device: {serial}, user: {target_user}")
            sublog(f"Installing {len(apk_paths)} APK(s)...")
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
        live_print(f"[*] Launching target Activity: {target_activity}")
        with step_progress(f"Launching activity: {target_activity}"):
            sublog(f"Sending am start to device {serial}...")
            code, log = run_adb(
                serial,
                ["shell", "am", "start", "--user", target_user, "-n", target_activity],
                "am start",
            )
        if not adb_result_ok(code, log):
            code = code or 1
            verdict = classify_adb_failure(code, log)
            live_print(f"[!] am start failed (exit {code})", err=True)
            record_device("start", "ENV" if verdict.env_class != "CODE" else "FAIL", exit_for(verdict), serial, verdict.env_class, verdict.reason, artifact_set_sha=artifact_set_sha, install_reference=artifact_set_sha, application_id=actual_application_id, target_user=target_user)
            emit_env_failure(verdict, "run_device.py", serial=serial)
            return exit_for(verdict)
        record_device("start", "EMERGENCY_UNVERIFIED" if args.force else "PASS", 0, serial, artifact_set_sha=artifact_set_sha, install_reference=artifact_set_sha, application_id=actual_application_id, target_user=target_user)
        live_print(f"[+] Launched {target_activity}")
        try:
            state = REPO / ".agents/state" if (REPO / ".agents").is_dir() else REPO / "agents/state"
            from mutation_guard import active_plan
            from _vnext_common import read_json
            active = active_plan(REPO)
            task_id = str(active.get("task_id") or "")
            current_path = state / "tasks" / task_id / "current-run.json"
            if current_path.is_file():
                current_run = read_json(current_path)
                recipes = current_run.get("verification_recipes") or []
                if not recipes:
                    policy_path = Path(str(current_run.get("policy") or ""))
                    if policy_path.is_file():
                        policy = read_json(policy_path)
                        recipes = get_verification_recipes(policy.get("surfaces") or [])
                if not recipes:
                    recipes = get_verification_recipes([], fallback=True)
                if recipes:
                    live_print("\n" + "=" * 60)
                    live_print("[MANDATORY MOBILE TEST WALKTHROUGH REQUIRED IN CHAT]")
                    live_print("The agent MUST now output a custom, numbered walkthrough in chat:")
                    live_print(f"  1. Navigation Path: Path from {target_activity} to the modified feature/screen")
                    live_print("  2. Preconditions: Required login state, flags, or test data")
                    live_print("  3. User Actions: Concrete taps, inputs, and screens to interact with")
                    live_print("  4. Expected Results: What the user should see and experience on screen")
                    live_print("  5. Edge Cases: Rotation, cancellations, back navigation")
                    live_print("-" * 60)
                    live_print("Surface verification recipes:")
                    for recipe in recipes:
                        live_print(f"  [{recipe['surface']}]:")
                        for idx, step in enumerate(recipe["steps"], 1):
                            live_print(f"    - {step}")
                    live_print("=" * 60)
                    live_print("[!] CRITICAL: DO NOT simply ask 'Did it pass' without first explaining the 5 test steps above in chat!\n")
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
