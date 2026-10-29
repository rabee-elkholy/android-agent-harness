"""Optional Antigravity Android CLI diagnostics; never delivery evidence.

Preview compilation shares the Gradle execution lock. Device Hub only opens the
physical device bound to fresh install/launch evidence. No APK installation,
emulator startup, permission grants, or task transitions occur here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

from _vnext_common import ValidationError, atomic_write_json, canonical_sha256, read_json, state_root
from evidence_store import StateLock
from build_execution import build_lock

MAX_OUTPUT = 6000
FQN = re.compile(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+", re.ASCII)


def invoke(executable: str, args: list[str], repo: Path, timeout: int = 120, *, detach: bool = False) -> tuple[int, str]:
    # Disk-backed capture bounds Python memory even with very noisy build tools.
    # No shell interpolation; public inputs are separately allowlisted.
    if os.name == "nt" and Path(executable).suffix.lower() in {".bat", ".cmd"}:
        if any(re.search(r'[&|<>^%!\r\n"]', value) for value in [executable, *args]):
            raise ValidationError("Unsafe batch launcher path/argument; use an Android CLI path without shell metacharacters.")
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    if detach:
        process = subprocess.Popen([executable, *args], cwd=repo, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **options)
        try:
            return process.wait(timeout=timeout), ""
        except subprocess.TimeoutExpired:
            return 0, ""  # still running: the hub window/server is up
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen([executable, *args], cwd=repo, stdout=output,
                                   stderr=subprocess.STDOUT, **options)
        try:
            code = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # Kill the launched process tree before releasing the build lock.
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.kill()
            process.wait(timeout=15)
            raise
        output.seek(0, 2)
        size = output.tell()
        output.seek(max(0, size - MAX_OUTPUT))
        text = output.read(MAX_OUTPUT).decode("utf-8", errors="replace")
    return code, text


def executable_path(repo: Path) -> str:
    found = shutil.which("android")
    if not found:
        raise ValidationError("ENV_BLOCKED: Android CLI is unavailable; use existing harness checks.")
    path = Path(found).resolve()
    if path.is_relative_to(repo.resolve()):
        raise ValidationError("Refusing a repository-local Android CLI executable.")
    return str(path)


def capabilities(repo: Path, executable: str) -> dict:
    stat = Path(executable).stat()
    identity = canonical_sha256([executable, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])
    path = state_root(repo) / "cache/android-ui-capabilities.json"
    try:
        cached = read_json(path)
        if (isinstance(cached, dict) and cached.get("identity") == identity
                and 0 <= time.time() - cached.get("at", 0) < 600 and cached.get("schema_version") == 1
                and isinstance(cached.get("version"), str) and isinstance(cached.get("features"), dict)
                and all(type(cached["features"].get(key)) is bool for key in ("list", "render", "hub"))):
            return cached
    except (OSError, ValueError, ValidationError, TypeError):
        pass
    code, version = invoke(executable, ["--version"], repo, 20)
    if code:
        raise ValidationError("ENV_BLOCKED: Android CLI version probe failed.")
    features = {}
    for action, args, required in (
        ("list", ["preview", "list", "--help"], ["--format"]),
        ("render", ["preview", "render", "--help"], ["--fqn", "--output", "--component-tree", "--no-image", "--daemon"]),
        ("hub", ["device", "hub", "--help"], ["--device"]),
    ):
        status, help_text = invoke(executable, args, repo, 20)
        features[action] = status == 0 and all(flag in help_text for flag in required)
    result = {"schema_version": 1, "identity": identity, "at": time.time(),
              "version": version.strip()[:200], "features": features}
    atomic_write_json(path, result)
    return result


def authorize(repo: Path, action: str) -> dict:
    from review_sources import resolve_review_host
    from mutation_guard import active_plan
    from host_continuation import assert_execution_session
    from plan_authority import require_mutation
    if resolve_review_host(repo) != "antigravity":
        raise ValidationError("UNSUPPORTED: android-ui is an Antigravity adapter; existing host gates remain available.")
    if action == "capabilities":
        return {}
    plan = active_plan(repo)
    assert_execution_session(repo, plan.get("task_id"))
    if plan.get("status") == "IMPLEMENTING" and action in {"list", "render"}:
        require_mutation(plan)
    elif plan.get("status") == "VERIFYING":
        from workflow import assert_active_run_fresh
        assert_active_run_fresh(repo, plan["task_id"])
    else:
        raise ValidationError("Preview requires IMPLEMENTING/VERIFYING; Device Hub requires VERIFYING.")
    return plan


def preview_reference(repo: Path, explicit: str | None) -> tuple[str, str]:
    from _variants import resolve_assemble_task
    task = resolve_assemble_task(repo)
    # Deliberately accept only a local module. No arbitrary build arguments,
    # external workspaces, scripts, or guessed CLI variant switches.
    if ":assemble" not in task:
        raise ValidationError("Cannot resolve an application preview target from the configured assemble task.")
    reference = explicit or task.rsplit(":assemble", 1)[0] or ":"
    if not re.fullmatch(r":(?:[A-Za-z_][A-Za-z0-9_-]*(?::[A-Za-z_][A-Za-z0-9_-]*)*)?", reference):
        raise ValidationError("Preview reference must be an exact local Gradle module, e.g. :mobile.")
    return reference, task


def prune_diagnostics(root: Path, keep: int = 12) -> None:
    """Remove only this adapter's UUID directories, under a verified local root."""
    resolved = root.resolve()
    if root.is_symlink():
        raise ValidationError("Diagnostic root must not be a symlink.")
    directories = sorted((p for p in root.iterdir() if re.fullmatch(r"[0-9a-f]{32}", p.name)
                          and p.is_dir() and not p.is_symlink()), key=lambda p: p.stat().st_mtime, reverse=True)
    for directory in directories[keep:]:
        target = directory.resolve()
        if target.parent != resolved:
            raise ValidationError("Diagnostic cleanup target escaped its root.")
        # Absolute containment is checked immediately before recursive deletion.
        shutil.rmtree(target)
    for cache in root.glob("*.json"):
        if re.fullmatch(r"[0-9a-f]{64}\.json", cache.name) and not cache.is_symlink():
            try:
                directory = Path(read_json(cache)["directory"])
                if directory.resolve().parent == resolved and not directory.exists():
                    cache.unlink()
            except (OSError, ValueError, ValidationError, KeyError, TypeError):
                pass


def input_identity(repo: Path, plan: dict, caps: dict, selection: dict) -> str:
    from delivery_manifest import build_manifest
    manifest = build_manifest(repo)
    return canonical_sha256({
        "repo": str(repo.resolve()), "task": plan.get("task_id"), "plan": plan.get("plan_sha256"),
        "snapshot": manifest["delivery_snapshot_sha256"],
        "changes": manifest["change_set_sha256"], "external": manifest["external_inputs_sha256"],
        "cli": [caps["identity"], caps["version"]], "selection": selection,
        "environment": {key: os.environ.get(key, "") for key in
                        ("JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_USER_HOME", "GRADLE_USER_HOME",
                         "JAVA_TOOL_OPTIONS", "GRADLE_OPTS", "PATH")},
    })


def output_files(directory: Path) -> list[dict]:
    files = []
    total = 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValidationError("Preview output escaped its diagnostic directory.")
        if not path.is_file() or path.suffix.lower() not in {".png", ".json"} or path.name == "receipt.json":
            continue
        total += path.stat().st_size
        if len(files) >= 128 or path.stat().st_size > 32 * 1024 * 1024 or total > 128 * 1024 * 1024:
            raise ValidationError("Preview outputs exceed the diagnostic budget; narrow the selected previews.")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        files.append({"path": str(path.resolve()), "sha256": digest.hexdigest(), "bytes": path.stat().st_size})
    return files


def preview(repo: Path, args, executable: str, caps: dict, plan: dict) -> dict:
    reference, configured_task = preview_reference(repo, args.reference)
    fqns = sorted(set(args.fqn))
    if args.action == "render" and (not 1 <= len(fqns) <= 16 or any(not FQN.fullmatch(f) for f in fqns)):
        raise ValidationError("Render requires 1..16 exact preview FQNs obtained from preview list.")
    selection = {"action": args.action, "reference": reference, "fqns": fqns,
                 "image": args.image, "daemon": not args.no_daemon, "configured_assemble": configured_task}
    with build_lock(repo):
        plan = authorize(repo, args.action)
        identity = input_identity(repo, plan, caps, selection)
        root = state_root(repo) / "diagnostics/android-ui"
        if not root.resolve().is_relative_to(state_root(repo).resolve()) or root.is_symlink():
            raise ValidationError("Diagnostic directory escaped the harness state root.")
        root.mkdir(parents=True, exist_ok=True)
        prune_diagnostics(root, keep=11)
        cache = root / (identity + ".json")
        # Advisory reuse is short-lived and must revalidate every output byte.
        if not args.refresh:
            try:
                previous = read_json(cache)
                directory = Path(previous["directory"])
                if (directory.resolve().parent == root.resolve() and not directory.is_symlink()
                        and previous.get("identity") == identity and previous.get("status") == "DIAGNOSTIC_OK"
                        and 0 <= time.time() - previous["at"] < 600
                        and previous["files"] == output_files(directory)):
                    return {**previous, "reused": True}
            except (OSError, ValueError, ValidationError, KeyError, TypeError):
                pass
        directory = root / uuid.uuid4().hex
        directory.mkdir(parents=True)
        command = ["preview", args.action, reference]
        if args.action == "render":
            command += ["--component-tree", "--output=" + str(directory)]
            if not args.image:
                command.append("--no-image")
            if not args.no_daemon:
                command.append("--daemon")
            command += ["--fqn=" + f for f in fqns]
        started = time.monotonic()
        code, output = invoke(executable, command, repo, 300)
        from _vnext_common import redact
        (directory / "tool-output.txt").write_text(redact(output), encoding="utf-8")
        if code:
            raise ValidationError("PREVIEW_TOOL_FAILED: inspect the bounded local diagnostic log; no test verdict was recorded. " + str(directory))
        if identity != input_identity(repo, plan, caps, selection):
            raise ValidationError("STALE: project inputs changed during preview; output cannot be reused.")
        files = output_files(directory)
        if args.action == "render" and (not files or (args.image and not any(f["path"].endswith(".png") for f in files))
                                      or not any(f["path"].endswith(".json") for f in files)):
            raise ValidationError("PREVIEW_TOOL_FAILED: requested preview outputs are missing.")
        result = {"schema_version": 1, "status": "DIAGNOSTIC_OK", "delivery_evidence": False,
                  "identity": identity, "at": time.time(), "directory": str(directory), "files": files,
                  "selection": selection, "seconds": round(time.monotonic() - started, 3), "reused": False,
                  "variant_note": "CLI preview target resolution is diagnostic; only harness assemble proves the configured APK variant."}
        if args.action == "list":
            result["previews"] = [line.strip() for line in output.splitlines() if FQN.fullmatch(line.strip())][:64]
            result["list_may_be_truncated"] = len(output.encode("utf-8")) >= MAX_OUTPUT
        atomic_write_json(directory / "receipt.json", result)
        atomic_write_json(cache, result)
        return result


def bound_phone(repo: Path, plan: dict, explicit: str | None) -> str:
    from workflow import assert_active_run_fresh
    from final_verifier import _validate_artifact
    from evidence_store import EvidenceStore
    from _repo_files import matching_adb_serials
    from run_gradle_task import validate_reviewer_precondition_before_assemble
    current = assert_active_run_fresh(repo, plan["task_id"])
    root = state_root(repo)
    allowed, reason = validate_reviewer_precondition_before_assemble(repo, root)
    if not allowed:
        raise ValidationError("Device Hub review prerequisites: " + reason)
    version = (root.parent / "VERSION").read_text(encoding="utf-8").strip()
    records = []
    for name in ("device_install", "device_launch"):
        record, error = _validate_artifact(EvidenceStore(root), current["delivery_snapshot_sha256"],
                                           current["change_set_sha256"], current["run_id"], name, version)
        if error:
            raise ValidationError("Device Hub requires fresh install/start: " + error)
        records.append(record["evidence"])
    for key in ("artifact_set_sha256", "serial_sha256", "target_user"):
        if not records[0].get(key) or records[0][key] != records[1].get(key):
            raise ValidationError("Device Hub install/launch binding mismatch: " + key)
    phones = matching_adb_serials(policy="physical-only")
    matches = [phone for phone in phones if hashlib.sha256(phone.encode()).hexdigest() == records[1]["serial_sha256"]]
    if len(matches) != 1 or (explicit is not None and explicit != matches[0]):
        raise ValidationError("The verified physical phone is unavailable or --serial selects a different phone. No automatic fallback.")
    return matches[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capabilities", "list", "render", "hub"))
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("HARNESS_REPO") or Path(__file__).resolve().parents[2]))
    parser.add_argument("--reference")
    parser.add_argument("--fqn", action="append", default=[])
    parser.add_argument("--image", action="store_true")
    parser.add_argument("--no-daemon", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--serial")
    parser.add_argument("--json", action="store_true", help="Structured output (also the default).")
    args = parser.parse_args(argv)
    if args.action not in {"list", "render"} and (args.reference or args.fqn or args.image or args.no_daemon or args.refresh):
        parser.error("Preview selection/options require list or render.")
    if args.action != "hub" and args.serial:
        parser.error("--serial requires hub.")
    if args.action == "list" and (args.fqn or args.image or args.no_daemon):
        parser.error("--fqn, --image and --no-daemon require render.")
    repo = args.repo.resolve()
    try:
        plan = authorize(repo, args.action)
        executable = executable_path(repo)
        caps = capabilities(repo, executable)
        if args.action == "capabilities":
            result = caps
        elif not caps["features"].get(args.action):
            raise ValidationError("UNSUPPORTED: this Android CLI lacks the required options. Use existing harness verification; no automatic update.")
        elif args.action in {"list", "render"}:
            result = preview(repo, args, executable, caps, plan)
        else:
            with StateLock(state_root(repo) / "device-validation-execution", timeout_seconds=0):
                plan = authorize(repo, args.action)
                serial = bound_phone(repo, plan, args.serial)
                # `android device hub` keeps serving its window; waiting for it to exit hung for 60 s and
                # reported a failure while the mirror was actually open. Detach and check it started.
                code, _ = invoke(executable, ["device", "hub", "--device=" + serial], repo, 8, detach=True)
                if code:
                    raise ValidationError("ENV_BLOCKED: Device Hub failed to open; use the physical phone directly.")
                result = {"status": "OPEN_REQUESTED", "delivery_evidence": False,
                          "pill": "[Android Device Hub](sidecar://android-cli-plugin/device-hub/)",
                          "note": "Reuse this window. Opening is not a test PASS; complete the routed walkthrough or e2e session."}
        if "files" in result:
            result = {**result, "file_count": len(result["files"]), "files": result["files"][:8],
                      "receipt": str(Path(result["directory"]) / "receipt.json")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, subprocess.TimeoutExpired, ValidationError) as exc:
        print(json.dumps({"status": "BLOCKED", "delivery_evidence": False, "reason": str(exc)}, ensure_ascii=False))
        return 30


if __name__ == "__main__":
    raise SystemExit(main())
