"""Bounded Android diagnostics, isolated from final verification evidence."""
from argparse import Namespace
from decimal import Decimal
import re
import subprocess
import time

from _vnext_common import (HarnessError, ValidationError, atomic_write_json, canonical_sha256,
                           read_json, redact_text, sha256_bytes, sha256_file, state_root, task_dir, utc_now)
from evidence_store import EvidenceStore, StateLock


def adb(serial, *args, timeout=20):
    try:
        result = subprocess.run(["adb", "-s", serial, *args], capture_output=True, encoding="utf8",
                                errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationError(f"READ_FAILED: {exc}") from exc
    if result.returncode:
        raise ValidationError(f"READ_FAILED: {redact_text(result.stderr or result.stdout)[:500]}")
    return result.stdout.strip()


def arm(serial, user, package, attempt):
    clock = adb(serial, "shell", "date", "+%s.%N")
    if not re.fullmatch(r"\d+\.\d{1,9}", clock):
        second = adb(serial, "shell", "date", "+%s")
        if not second.isdecimal():
            raise ValidationError("READ_FAILED: invalid device clock")
        time.sleep(1)
        clock = str(int(second) + 1) + ".000"
    return {"serial_hash": sha256_bytes(serial.encode()), "package": package, "user": user,
            "attempt": attempt, "start_epoch": clock}


def read_window(serial, start):
    common = ["logcat", "-d", "-b", "main,system,crash", "-v", "threadtime", "-v", "epoch"]
    if start:
        try:
            return adb(serial, *common, "-T", start), False
        except ValidationError as exc:
            if not re.search(r"unknown option|invalid option|unrecognized option", str(exc), re.I):
                raise
    return adb(serial, *common, "-t", "5000"), bool(start)


def summarize(raw, package, start, ids, show_all, limit, pattern, current_pids=()):
    """Attribute crash blocks per process; expire ownership at each PID start."""
    pids = set(current_pids)
    blocks = {}
    crashes = []
    logs = []
    for line in raw.splitlines():
        match = re.match(r"\s*(\d+\.\d+)\s+(\d+)\s+\d+\s+[VDIWEFA]\s+([^:]+):\s?(.*)", line)
        if not match or start and Decimal(match[1]) < Decimal(start):
            continue
        _, pid, tag, msg = match.groups()
        launched = re.search(r"\bStart proc (\d+):([^/\s]+)", msg)
        if launched:
            pids.discard(launched[1])
            blocks.pop(launched[1], None)
            if launched[2].split(":")[0] == package:
                pids.add(launched[1])
        if tag.strip() == "AndroidRuntime":
            if "FATAL EXCEPTION" in msg:
                blocks[pid] = [msg]
            elif pid in blocks:
                blocks[pid].append(msg)
                proc = re.search(r"\bProcess:\s*([^,\s]+)", msg)
                if proc and proc[1].split(":")[0] == package:
                    pids.add(pid)
                    crashes.append(blocks[pid])
                elif proc:
                    blocks.pop(pid, None)
        if re.search(r"\bANR in " + re.escape(package) + r"(?=[:\s(]|$)", msg) or pid in pids and "Fatal signal" in msg:
            crashes.append([msg])
        owned = any("#" + ident in msg for ident in ids)
        if (owned or show_all and pid in pids) and (not pattern or pattern.lower() in msg.lower()):
            if logs and logs[-1][0] == msg:
                logs[-1][1] += 1
            else:
                logs.append([msg, 1])
    fatal = [line for group in crashes for line in group]
    if len(fatal) > 60:
        fatal = (fatal[:15] + [line for line in fatal[15:-30] if "Caused by:" in line][:15] + fatal[-30:])
    rows = fatal[:limit]
    remaining = limit - len(rows)
    if remaining > 0:
        for line, count in logs[-remaining:]:
            rows.append(line + (f" (x{count})" if count > 1 else ""))
    return [redact_text(line)[:1500] for line in rows]


def verified_reference(repo, plan, serial_hash, user):
    try:
        run = read_json(task_dir(repo, plan["task_id"]) / "current-run.json")
        store = EvidenceStore(state_root(repo))
        args = (run["delivery_snapshot_sha256"], run["run_id"])
        installed = store.read(*args, "device_install")
        built = store.read(*args, "assemble")
        proof = installed["evidence"]
        artifact = built["evidence"]["artifact_set"]
        if (installed["status"] == built["status"] == "PASS" and proof["serial_sha256"] == serial_hash
                and proof["target_user"] == user and proof["application_id"] == artifact["application_id"]
                and proof["artifact_set_sha256"] == artifact["artifact_set_sha256"]):
            return artifact
    except (HarnessError, KeyError, OSError, ValueError):
        pass
    return {}


def identity(serial, user, package, artifact):
    from journey_runner import AdbTransport
    if not artifact or not artifact.get("members") or artifact.get("application_id") != package:
        return "unknown"
    try:
        transport = AdbTransport(serial, package, [m["sha256"] for m in artifact["members"]], target_user=user)
        transport.verify_installed_artifact()
        return "confirmed"
    except (HarnessError, OSError, subprocess.TimeoutExpired) as exc:
        return "different" if "differs from approved artifact" in str(exc) else "unknown"


def build_key(repo, task, package, entries):
    from delivery_manifest import build_manifest
    snap = build_manifest(repo)
    return canonical_sha256([snap["delivery_snapshot_sha256"], snap["external_inputs_sha256"], task,
                             package, [(e["id"], sha256_file(repo / e["path"])) for e in entries if e["state"] == "APPLIED"]])


def minifier_warning(repo, task):
    module = repo.joinpath(*task.strip(":").split(":")[:-1])
    config = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in module.glob("build.gradle*"))
    if not re.search(r"(?:minifyEnabled|isMinifyEnabled)\s*(?:=\s*)?true", config):
        return None
    rules = [*module.glob("*.pro"), *repo.glob("*.pro")]
    if any(re.search(r"-assumenosideeffects\s+class\s+android\.util\.Log\b",
                     path.read_text(encoding="utf-8", errors="replace")) for path in rules):
        return "R8 rules may remove android.util.Log calls. Use a non-minified diagnostic variant."
    return None


def install(repo, serial, user, package, book, previous, args, directory):
    from _variants import resolve_assemble_task
    from artifact_set import verify_artifact_set
    from run_gradle_task import diagnostic_assemble
    task = resolve_assemble_task(repo)
    key = build_key(repo, task, package, book["entries"])
    artifact = previous.get("artifact_set", {})
    paths = []
    if key == previous.get("build_key"):
        try:
            paths = verify_artifact_set(repo, artifact)
        except (HarnessError, OSError):
            pass
    warning = minifier_warning(repo, task)
    if warning:
        import sys
        print(warning, file=sys.stderr)
    if not paths:
        artifact = diagnostic_assemble(repo, task)
        if build_key(repo, task, package, book["entries"]) != key:
            raise ValidationError("Sources changed during diagnostic build; retry")
        paths = verify_artifact_set(repo, artifact)
    package = artifact["application_id"]
    device_hash = sha256_bytes(serial.encode())
    reused = (previous.get("serial_hash") == device_hash and previous.get("user") == user
              and identity(serial, user, package, artifact) == "confirmed")
    if not reused:
        flags = ["install-multiple" if len(paths) > 1 else "install", "-r", "--user", user]
        if args.allow_downgrade:
            flags.append("-d")
        try:
            result = adb(serial, *flags, *map(str, paths), timeout=120)
        except ValidationError as exc:
            if "VERSION_DOWNGRADE" in str(exc):
                raise ValidationError("Device contains a newer build. Keep it or obtain developer approval for --allow-downgrade.") from exc
            raise
        if "Success" not in result or "Failure" in result:
            raise ValidationError(f"Diagnostic install failed: {redact_text(result)}")
    receipt = {"warning": warning, "artifact_set": artifact, "build_key": key, "serial_hash": device_hash, "user": user,
               "install_skipped": reused}
    atomic_write_json(directory / "install.json", receipt)
    return receipt


def device_action(repo, plan, args):
    from _product import APPLICATION_ID, DEVICE_TARGET_POLICY
    from _repo_files import matching_adb_serials
    from debug_instrumentation import ledger, ledger_path, reconcile
    from run_device import resolve_target_user
    choices = matching_adb_serials(policy=DEVICE_TARGET_POLICY)
    serial = args.device or (choices[0] if len(choices) == 1 else None)
    if serial not in choices:
        raise ValidationError("Select one connected policy-compatible device using --device")
    user = resolve_target_user(serial, None)
    serial_hash = sha256_bytes(serial.encode())
    if not plan:
        if args.action != "logs":
            raise ValidationError("An active task is required")
        raw, _ = read_window(serial, None)
        limit = args.max_lines or (400 if args.all else 150)
        if not 1 <= limit <= 5000:
            raise ValidationError("Expected --max-lines between 1 and 5000")
        return {"lines": summarize(raw, APPLICATION_ID, None, [], args.all, limit, args.grep)}
    if plan.get("status") not in {"IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"} and args.action != "logs":
        raise ValidationError("Debug device action requires an active implementation or verification task")
    directory = ledger_path(repo, plan).parent
    with StateLock(directory):
        book = ledger(repo, plan)
        reconcile(repo, book)
        if book["entries"]:
            atomic_write_json(ledger_path(repo, plan), book)
        lost = [e["path"] for e in book["entries"] if e["state"] == "LOST"]
        previous = read_json(directory / "install.json") if (directory / "install.json").exists() else {}
        attempt = book["attempts"][-1]["id"] if book["attempts"] else "observation"
        if args.action == "install" and lost:
            raise ValidationError(f"LOST: strip or re-add diagnostics for {lost}")
        if args.action == "install":
            previous = install(repo, serial, user, APPLICATION_ID, book, previous, args, directory)
        artifact = previous.get("artifact_set", {})
        if plan.get("status") in {"VERIFYING", "READY_FOR_DELIVERY"}:
            artifact = verified_reference(repo, plan, serial_hash, user)
        package = artifact.get("application_id") or APPLICATION_ID
        if args.action in {"arm", "install"}:
            session = arm(serial, user, package, attempt)
            atomic_write_json(directory / "session.json", session)
            if args.action == "install":
                # Resolve against the actual installed variant and selected user.
                output = adb(serial, "shell", "cmd", "package", "resolve-activity", "--brief", "--user", user,
                             "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", package)
                component = output.splitlines()[-1] if output else ""
                if not component.startswith(package + "/") or not re.fullmatch(r"[\w.$/]+", component):
                    raise ValidationError("No launcher activity resolved for diagnostic package")
                result = adb(serial, "shell", "am", "start", "--user", user, "-n", component)
                if "Error" in result:
                    raise ValidationError(redact_text(result))
            return {**session, "lost_sources": lost, **({"install_skipped": previous["install_skipped"]} if args.action == "install" else {})}
        session_path = directory / "session.json"
        session = read_json(session_path) if session_path.exists() else {}
        if session and (session["serial_hash"], session["user"], session["package"], session["attempt"]) != (
                serial_hash, user, package, attempt):
            raise ValidationError("Diagnostic session changed; run debug arm on the current device/build")
        if book["entries"] and not session:
            raise ValidationError("Run debug arm before reproducing this attempt")
        start = session.get("start_epoch")
        raw, fallback = read_window(serial, start)
        ids = [e["id"] for e in book["entries"] if e["state"] == "APPLIED"]
        limit = args.max_lines or (400 if args.all else 150)
        if not 1 <= limit <= 5000:
            raise ValidationError("Expected --max-lines between 1 and 5000")
        # pidof can exit 1 when the process has crashed; the log still supplies
        # its historical process identity.
        try:
            current_pids = adb(serial, "shell", "pidof", package).split()
        except ValidationError:
            current_pids = []
        lines = summarize(raw, package, start, ids, args.all, limit, args.grep, current_pids)
        result = {"attempt": attempt, "start_epoch": start, "serial_hash": serial_hash, "package": package,
                  "identity": identity(serial, user, package, artifact), "fallback": fallback,
                  "lost_sources": lost, "lines": lines, "matched": bool(lines)}
        if not lines:
            result["message"] = f"No matching events for {attempt} on {package} since {start or 'recent device logs'}."
        from workflow import record_debug_evidence
        import json
        record_debug_evidence(Namespace(repo=str(repo), task_id=plan["task_id"], kind="logcat",
                                        reference=json.dumps({**result, "lines": lines[:40], "sha256": canonical_sha256(lines)})))
        if book["attempts"]:
            book["attempts"][-1]["read_at"] = utc_now()
            atomic_write_json(ledger_path(repo, plan), book)
        return result
