"""Android Agent Harness CLI: bootstrap, doctor, preflight, and selftest dispatch.

Zero runtime dependencies. The CLI is a thin dispatcher: the engine always lives
in a kit checkout (agents/scripts). `android-harness init` reuses an existing
kit clone or fetches one into ~/.android-harness/kit.

The kit is provisioned PINNED to an exact release tag (never main). The tag is
resolved from HARNESS_KIT_REF when set, otherwise from the latest GitHub release;
after checkout the provisioned agents/VERSION is asserted against the requested
version and any mismatch fails closed with remediation instructions.

Usage:
    android-harness init  [--repo PATH] [--lang en|ar] [--kit PATH]
    android-harness update [--repo PATH] [--kit PATH]
    android-harness explain [--last N] [--repo PATH] [--kit PATH]
    android-harness verify --task TASK_ID [--repo PATH] [--kit PATH]
    android-harness doctor [--repo PATH] [--json] [--device] [--kit PATH]
    android-harness preflight [--repo PATH] [--kit PATH]
    android-harness selftest [--kit PATH]
    android-harness version [--kit PATH]

Exit codes (documented contract):
    0  PASS / nothing wrong
    1  findings, failures, or configuration errors
    2  configuration error
    30 environment-blocked verification
    130 interrupted (Ctrl-C)

Or without installing:
    python harness_cli.py <command> [options]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

KIT_REPO_URL = "https://github.com/rabee-elkholy/android-agent-harness.git"
RELEASES_API_URL = "https://api.github.com/repos/rabee-elkholy/android-agent-harness/releases/latest"
KIT_DIR = Path.home() / ".android-harness" / "kit"


def _prompt_url(version: str, doc: str) -> str:
    """Immutable release-tag URL for a one-click lifecycle prompt doc."""
    return (
        "https://raw.githubusercontent.com/rabee-elkholy/android-agent-harness/"
        f"v{str(version).strip().lstrip('v')}/docs/{doc}"
    )


def _manual_remediation(version: str) -> str:
    return (
        "Remediate manually:\n"
        f"    git clone {KIT_REPO_URL}\n"
        f"    git -C android-agent-harness checkout v{version}\n"
        "then rerun with --kit <path>."
    )


def _read_version_file(kit: Path) -> str:
    return (kit / "agents" / "VERSION").read_text(encoding="utf-8").strip()


def _semver_tuple(version: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for chunk in version.lstrip("v").strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _latest_release_tag(timeout: float = 3.0) -> str | None:
    req = urllib.request.Request(
        RELEASES_API_URL,
        headers={"User-Agent": "AndroidHarnessKit-CLI"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                tag = str(json.loads(resp.read().decode("utf-8")).get("tag_name") or "").strip()
                return tag.lstrip("v") or None
    except Exception:
        return None
    return None


def _verify_kit_checksums(kit: Path) -> None:
    """Pre-execution release checksum verifier.

    Verifies every file in agents/release_checksums.json using standard library Python
    before importing or executing any kit scripts. Rejects symlinks and path traversal.
    """
    checksum_file = kit / "agents" / "release_checksums.json"
    if not checksum_file.is_file() or checksum_file.is_symlink():
        raise SystemExit(f"[ERROR] Kit release checksums manifest missing or symlink: {checksum_file}")
    try:
        manifest = json.loads(checksum_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"[ERROR] Kit release checksums manifest corrupt: {exc}")
    files = manifest.get("files") or {}
    for rel, expected in files.items():
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise SystemExit(f"[ERROR] Suspicious path in release checksums: {rel}")
        target = kit / rel_path
        if not target.is_file() or target.is_symlink():
            raise SystemExit(f"[ERROR] Missing or symlinked kit file: {rel}")
        h = hashlib.sha256()
        with open(target, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != expected:
            raise SystemExit(f"[ERROR] Kit release checksum mismatch for {rel}")


def _recover_stale_kit(dest: Path) -> None:
    """Recover from interrupted promotions or remove stale backup kits."""
    previous = dest.with_name(f"{dest.name}.previous")
    if dest.is_dir() and _has_engine(dest):
        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
    elif previous.is_dir() and not dest.exists():
        try:
            os.replace(previous, dest)
        except OSError:
            pass
    elif previous.is_dir() and dest.is_dir() and not _has_engine(dest):
        shutil.rmtree(dest, ignore_errors=True)
        try:
            os.replace(previous, dest)
        except OSError:
            pass


def _provision_pinned(url: str, dest: Path, version: str) -> None:
    """Fresh checkout of exactly tag v<version> via staging and Windows-safe atomic transaction."""
    _recover_stale_kit(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.parent / f"staging_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True, exist_ok=True)
    tag = f"v{version}"
    steps = [
        (["git", "init", "-q"], True),
        (["git", "remote", "add", "origin", url], True),
        (
            [
                "git",
                "fetch",
                "--depth",
                "1",
                "--force",
                "origin",
                f"refs/tags/{tag}:refs/tags/{tag}",
            ],
            True,
        ),
        (["git", "checkout", "-q", "--detach", tag], True),
    ]
    try:
        for step, use_cwd in steps:
            proc = subprocess.run(step, check=False, cwd=str(staging) if use_cwd else None)
            if proc.returncode != 0:
                raise SystemExit(
                    f"[ERROR] Could not provision kit at tag {tag}. {_manual_remediation(version)}"
                )
        if not _has_engine(staging):
            raise SystemExit(
                f"[ERROR] Kit checkout at v{version} has no harness engine. {_manual_remediation(version)}"
            )
        found = _read_version_file(staging)
        if found != version:
            raise SystemExit(
                f"[ERROR] Pinned kit checkout reports v{found} but v{version} was requested. "
                + _manual_remediation(version)
            )
        _verify_kit_checksums(staging)

        # Windows-safe atomic replacement transaction:
        # kit -> kit.previous, staging -> kit, validate, clean kit.previous
        previous = dest.with_name(f"{dest.name}.previous")
        has_prev = False
        if dest.exists():
            if previous.exists():
                shutil.rmtree(previous, ignore_errors=True)
            try:
                os.replace(dest, previous)
                has_prev = True
            except OSError:
                time.sleep(0.1)
                os.replace(dest, previous)
                has_prev = True
        try:
            os.replace(staging, dest)
            if not _has_engine(dest) or _read_version_file(dest) != version:
                raise RuntimeError("Engine validation failed after kit promotion")
            if has_prev and previous.exists():
                shutil.rmtree(previous, ignore_errors=True)
        except Exception as exc:
            shutil.rmtree(dest, ignore_errors=True)
            if has_prev and previous.exists():
                try:
                    os.replace(previous, dest)
                except OSError:
                    pass
            raise SystemExit(f"[ERROR] Failed promoting staged kit to {dest}: {exc}")
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _script_root(kit: Path) -> Path:
    return kit / "agents" / "scripts"


def _has_engine(kit: Path) -> bool:
    return (_script_root(kit) / "setup_wizard.py").is_file() and (kit / "agents" / "VERSION").is_file()


EXIT_PASS = 0
EXIT_FINDINGS = 1
EXIT_CONFIG_ERROR = 2
EXIT_INFRA_ERROR = 3
EXIT_INCOMPLETE_OR_STALE = 2


def resolve_kit(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    env = os.environ.get("HARNESS_KIT", "").strip()
    if env:
        candidates.append(Path(env).expanduser().resolve())
    candidates.append(Path(__file__).resolve().parent)
    candidates.append(Path.cwd().resolve())
    candidates.append(KIT_DIR)
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents[:2]]:
        candidates.append(parent / "android-agent-harness")
    for cand in candidates:
        if _has_engine(cand):
            return cand
    raise SystemExit(
        "[ERROR] No Android Agent Harness engine found. "
        "Pass --kit /path/to/android-agent-harness, set HARNESS_KIT, run from the kit "
        f"checkout, or let init clone it into {KIT_DIR}."
    )


def ensure_kit(explicit: str | None) -> Path:
    try:
        return resolve_kit(explicit)
    except SystemExit:
        pass
    if explicit:
        raise SystemExit(f"[ERROR] --kit path has no harness engine: {explicit}")
    requested = os.environ.get("HARNESS_KIT_REF", "").strip().lstrip("v") or _latest_release_tag()
    if not requested:
        raise SystemExit(
            "[ERROR] Could not resolve a release tag to pin (offline?). "
            "The kit is never provisioned from a floating branch. "
            + _manual_remediation("latest")
        )
    print(f"[*] Provisioning Android Agent Harness at pinned tag v{requested} into {KIT_DIR} ...")
    _provision_pinned(KIT_REPO_URL, KIT_DIR, requested)
    if not _has_engine(KIT_DIR):
        shutil.rmtree(KIT_DIR, ignore_errors=True)
        raise SystemExit(
            f"[ERROR] Kit checkout at v{requested} has no harness engine. {_manual_remediation(requested)}"
        )
    found = _read_version_file(KIT_DIR)
    if found != requested:
        raise SystemExit(
            f"[ERROR] Pinned kit checkout reports v{found} but v{requested} was requested. "
            "Refusing to continue on a mismatched provision. " + _manual_remediation(requested)
        )
    return KIT_DIR


def refresh_kit(kit: Path, target_version: str | None = None) -> None:
    """Re-pin an existing kit clone to an exact release tag. Never floats to main."""
    if not (kit / ".git").is_dir():
        print(f"[i] Kit at {kit} is not a git checkout; skipping pin.")
        return
    want = (target_version or "").strip().lstrip("v") or _read_version_file(kit)
    tag = f"v{want}"
    print(f"[*] Pinning kit at {kit} to {tag} ...")
    fetch = subprocess.run(
        [
            "git",
            "-C",
            str(kit),
            "fetch",
            "--depth",
            "1",
            "--force",
            "origin",
            f"refs/tags/{tag}:refs/tags/{tag}",
        ],
        check=False,
    )
    checkout = subprocess.run(
        ["git", "-C", str(kit), "checkout", "-q", "--detach", tag],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if fetch.returncode != 0 or checkout.returncode != 0:
        current = _read_version_file(kit)
        detached = subprocess.run(
            ["git", "-C", str(kit), "symbolic-ref", "-q", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if detached.returncode == 0:
            # The checkout sits on a named branch (e.g. a manual drift to main):
            # refuse to continue — the kit must never float.
            raise SystemExit(
                f"[ERROR] Kit at {kit} is on a branch, not a pinned tag; refusing to float. "
                + _manual_remediation(current)
            )
        print(
            f"[!] Could not re-fetch/checkout {tag}; keeping existing pinned checkout v{current}. "
            "Nothing floated to main."
        )
        return
    found = _read_version_file(kit)
    if found != want:
        raise SystemExit(
            f"[ERROR] After pinning, kit reports v{found} but {tag} was requested. "
            "Refusing to continue. " + _manual_remediation(want)
        )
    print(f"[OK] Kit pinned at {tag}")


def find_repo(explicit: str | None) -> Path:
    repo = Path(explicit).expanduser().resolve() if explicit else Path.cwd().resolve()
    if not ((repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()):
        raise SystemExit(
            f"[ERROR] {repo} is NOT an Android project (missing gradlew/gradlew.bat). "
            "Pass --repo pointing to the Android/KMP checkout."
        )
    return repo


def run_engine_script(
    kit: Path, script: str, args: list[str], *, capture: bool = False, env: dict | None = None
) -> int:
    target = _script_root(kit) / script
    if not target.is_file():
        raise SystemExit(f"[ERROR] Engine script missing: {target}")
    proc = subprocess.run(
        [sys.executable, str(target), *args],
        check=False,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if capture and proc.stdout:
        sys.stdout.write(proc.stdout)
    if not capture and proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def cmd_init(args: argparse.Namespace) -> int:
    repo = find_repo(args.repo)
    kit = ensure_kit(args.kit)
    version = (kit / "agents" / "VERSION").read_text(encoding="utf-8").strip()
    print("==================================================")
    print(f"[Android Agent Harness] v{version}")
    print(f"  target app : {repo}")
    print(f"  engine kit : {kit}")
    print("==================================================")
    answers_arg = getattr(args, "answers_json", None)
    temp_to_clean: Path | None = None
    if answers_arg:
        p = Path(answers_arg).resolve()
        if p.is_symlink() or not p.is_file():
            raise SystemExit(f"[ERROR] --answers-json path is missing or a symlink: {answers_arg}")
        temp_to_clean = p

    try:
        if answers_arg:
            wizard_args = ["write", "--repo", str(repo), "--answers-json", str(temp_to_clean)]
            if args.lang:
                wizard_args.extend(["--lang", args.lang])
            code = run_engine_script(kit, "setup_wizard.py", wizard_args)
        else:
            lang_args = ["--lang", args.lang] if args.lang else []
            code = run_engine_script(
                kit,
                "setup_wizard.py",
                ["--repo", str(repo), *lang_args],
            )
        if code != 0:
            print("[!] Setup wizard did not complete; nothing was installed.")
            return code
        answers = repo / ".harness-setup" / "answers.json"
        if not answers.is_file():
            print("[!] answers.json missing after wizard; rerun init.")
            return 1
        print("[*] Installing the vNext engine into the target app...")
        port_code = run_engine_script(
            kit,
            "lifecycle.py",
            ["install", "--repo", str(repo), "--kit", str(kit)],
        )
        if port_code != 0:
            print("[!] Engine port reported failures; review doctor output above.")
            return port_code
        print()
        print("[SUCCESS] Android Agent Harness installed; run doctor for local validation.")
        print(f"[VERIFY] Run anytime: android-harness doctor --repo \"{repo}\"")
        return 0
    finally:
        if temp_to_clean and temp_to_clean.is_file():
            try:
                temp_to_clean.unlink(missing_ok=True)
            except OSError:
                pass


def cmd_update(args: argparse.Namespace) -> int:
    kit = ensure_kit(args.kit)
    current = _read_version_file(kit)
    sys.path.insert(0, str(_script_root(kit)))
    try:
        from check_kit_update import check_for_update

        info = check_for_update(force=args.force)
        latest = info.get("latest") or current
    except Exception as exc:
        latest = current
        print(f"[i] Update check skipped ({exc}).")
    print(f"[i] Installed kit engine: v{current} | latest release: v{latest}")
    if args.repo:
        repo = find_repo(args.repo)
        print(f"[*] Target app checkout: {repo}")
    if _semver_tuple(latest) > _semver_tuple(current):
        refresh_kit(kit, latest)
    else:
        # No upgrade (or offline): re-assert the pin on the current release tag.
        refresh_kit(kit, current)
    new_version = _read_version_file(kit)
    print(f"[i] Local kit engine now at: v{new_version}")
    if args.repo:
        repo = find_repo(args.repo)
        answers = repo / ".harness-setup" / "answers.json"
        if answers.is_file():
            print("[*] Applying a compatible vNext engine update to the app checkout...")
            port_code = run_engine_script(
                kit,
                "lifecycle.py",
                ["update", "--repo", str(repo), "--kit", str(kit)],
            )
            if port_code != 0:
                print(
                    f"[FAIL] App checkout update failed with exit code {port_code}; "
                    "success was not recorded."
                )
                return port_code
            print("[SUCCESS] App checkout updated and verified.")
            return 0
    print("[NEXT] Port the new engine into your app checkout:")
    print(f"       paste {_prompt_url(new_version, 'install-or-update-prompt.md')}")
    print("       in a NEW strong-model chat opened at the Android project root.")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    kit = resolve_kit(args.kit)
    repo = find_repo(args.repo) if args.repo else find_repo(None)
    command = ["uninstall", "--repo", str(repo)]
    if args.apply:
        command.append("--apply")
    if args.legacy:
        command.append("--legacy")
    return run_engine_script(kit, "lifecycle.py", command)


def cmd_task(args: argparse.Namespace) -> int:
    kit = resolve_kit(args.kit)
    task_args = list(args.task_args)
    if task_args and task_args[0] == "--":
        task_args = task_args[1:]
    repo_value = None
    for index, value in enumerate(task_args):
        if value == "--repo" and index + 1 < len(task_args):
            repo_value = task_args[index + 1]
            break
    repo = Path(repo_value).expanduser().resolve() if repo_value else Path.cwd().resolve()
    installed = repo / ".agents" / "scripts" / "workflow.py"
    if installed.is_file():
        return subprocess.run([sys.executable, str(installed), *task_args], cwd=str(repo), check=False).returncode
    return run_engine_script(kit, "workflow.py", task_args)


def cmd_doctor(args: argparse.Namespace) -> int:
    kit = ensure_kit(args.kit)
    repo = find_repo(args.repo) if args.repo else Path.cwd().resolve()
    cli_args = ["--repo", str(repo)]
    if args.json:
        cli_args.append("--json")
    if args.device:
        cli_args.append("--device")
    env_marker = os.environ.get("_IN_HOOK_SELFTEST")
    if env_marker != "1":
        os.environ["_IN_HOOK_SELFTEST"] = "0"
    code = run_engine_script(kit, "harness_doctor.py", cli_args, capture=args.json)
    if os.environ.get("_IN_HOOK_SELFTEST") == "0":
        os.environ.pop("_IN_HOOK_SELFTEST", None)
    return code


def cmd_preflight(args: argparse.Namespace) -> int:
    """Run the preflight gate against the client checkout.

    Prefer the checkout's own `.agents/scripts/preflight_check.py` (its REPO
    resolves correctly by location). Only when the checkout has no installed
    harness, run the kit's script with HARNESS_REPO pointing at the checkout.
    With no --repo, a kit checkout cwd runs the kit's own preflight (self-check).
    """
    kit = ensure_kit(args.kit)
    if args.repo:
        repo = find_repo(args.repo)
    else:
        cwd = Path.cwd().resolve()
        is_android = (cwd / "gradlew").is_file() or (cwd / "gradlew.bat").is_file()
        is_kit = (cwd / "agents" / "VERSION").is_file() and not (cwd / ".agents").is_dir()
        if not (is_android or is_kit):
            raise SystemExit(
                f"[ERROR] {cwd} is NOT an Android project (missing gradlew/gradlew.bat) "
                "and not a kit checkout. Pass --repo pointing to the Android/KMP checkout."
            )
        repo = cwd
    client_script = repo / ".agents" / "scripts" / "preflight_check.py"
    prev_cwd = Path.cwd()
    os.chdir(repo)
    try:
        if client_script.is_file():
            proc = subprocess.run(
                [sys.executable, str(client_script)],
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return proc.returncode
        env = os.environ.copy()
        env["HARNESS_REPO"] = str(repo)
        return run_engine_script(kit, "preflight_check.py", [], env=env)
    finally:
        os.chdir(prev_cwd)


def cmd_selftest(args: argparse.Namespace) -> int:
    kit = ensure_kit(args.kit)
    prev_cwd = Path.cwd()
    os.chdir(kit)
    try:
        scripts = (
            "_vnext_selftest.py", "_hook_selftest.py", "_security_selftest.py",
            "_zoho_selftest.py", "_baseline_selftest.py", "_graph_selftest.py",
            "_adb_core_selftest.py", "_env_codes_selftest.py", "_performance_selftest.py",
        )
        for script in scripts:
            code = run_engine_script(kit, script, [])
            if code != 0:
                return code
        return 0
    finally:
        os.chdir(prev_cwd)


def cmd_version(args: argparse.Namespace) -> int:
    kit = resolve_kit(args.kit)
    print(_read_version_file(kit))
    return 0


def _resolve_audit_path(repo: Path | None, kit: Path) -> Path:
    """Audit log of the checkout whose hooks actually ran.

    Priority: an explicit --repo checkout, then the HARNESS_HOOK_STATE
    override, then cwd discovery, then the kit's own state dir.
    """
    if repo is not None:
        for rel in (".agents/state/audit_log.jsonl", "agents/state/audit_log.jsonl"):
            candidate = (repo / rel).resolve()
            if candidate.is_file():
                return candidate
    override = os.environ.get("HARNESS_HOOK_STATE", "").strip()
    if override:
        return Path(override).with_name("audit_log.jsonl")
    for rel in (".agents/state/audit_log.jsonl", "agents/state/audit_log.jsonl"):
        candidate = (Path.cwd() / rel).resolve()
        if candidate.is_file():
            return candidate
    return _script_root(kit).parent / "state" / "audit_log.jsonl"


def cmd_explain(args: argparse.Namespace) -> int:
    kit = resolve_kit(args.kit)
    repo = Path(args.repo).expanduser().resolve() if getattr(args, "repo", None) else None
    audit_path = _resolve_audit_path(repo, kit)
    if not audit_path.is_file():
        print(f"[i] No audit log yet at {audit_path}")
        return 0
    records: list[dict] = []
    with open(audit_path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
    last_n = max(1, args.last)
    for rec in records[-last_n:]:
        code = str(rec.get("reason_code") or "")
        label = code or "UNSPECIFIED"
        ts = rec.get("ts") or 0
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts))) if ts else "?"
        decision = str(rec.get("decision") or "?").upper()
        tool = str(rec.get("tool") or "-")
        short = str(rec.get("reason_short") or "").replace("\n", " ")
        cmd_hash = str(rec.get("cmd_sha256_12") or "-")
        conv = str(rec.get("conv_hint") or "-")
        print(f"{stamp}  {decision:<5} {tool:<16} {cmd_hash}  [{code}] {label}")
        print(f"            conv={conv} :: {short}")
    print(f"[i] showed {min(last_n, len(records))} of {len(records)} record(s) from {audit_path}")
    return 0



def cmd_verify(args: argparse.Namespace) -> int:
    """Run the read-only vNext final verifier for one active task."""
    kit = resolve_kit(args.kit)
    repo = find_repo(args.repo) if args.repo else find_repo(None)
    client_workflow = repo / ".agents" / "scripts" / "workflow.py"
    if client_workflow.is_file():
        proc = subprocess.run(
            [sys.executable, str(client_workflow), "verify", "--repo", str(repo), "--task-id", args.task],
            cwd=str(repo), check=False,
        )
        return proc.returncode
    return run_engine_script(kit, "workflow.py", ["verify", "--repo", str(repo), "--task-id", args.task])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="android-harness",
        description="Android Agent Harness Kit control CLI (zero dependencies).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="Run the setup wizard against an Android checkout.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--lang", choices=("en", "ar"), default=None, help="Wizard language.")
    sp.add_argument("--kit", help="Kit checkout to use (default: auto-discover or clone).")
    sp.add_argument("--answers-json", help="Path to validated answers JSON for non-interactive setup.")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("update", help="Refresh the local kit engine and print upgrade steps.")
    sp.add_argument("--repo", help="Android checkout that consumes the engine.")
    sp.add_argument("--kit", help="Kit checkout to refresh (default: auto-discover or clone).")
    sp.add_argument("--force", action="store_true", help="Force remote release check.")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("uninstall", help="Preview or apply an ownership-safe harness removal.")
    sp.add_argument("--repo", help="Android checkout containing the harness (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout providing the lifecycle engine.")
    sp.add_argument("--apply", action="store_true", help="Apply the previewed removal.")
    sp.add_argument("--legacy", action="store_true", help="Remove a legacy installation after backing it up.")
    sp.set_defaults(func=cmd_uninstall)

    sp = sub.add_parser("task", help="Run the vNext plan/approval/verification lifecycle.")
    sp.add_argument("--kit", help="Kit checkout providing the workflow engine.")
    sp.add_argument("task_args", nargs=argparse.REMAINDER, help="Arguments passed to workflow.py")
    sp.set_defaults(func=cmd_task)

    sp = sub.add_parser("doctor", help="12-dimension diagnostic for an Android checkout.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--json", action="store_true", help="Machine-readable JSON report.")
    sp.add_argument("--device", action="store_true", help="Include ADB device diagnostics.")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("preflight", help="String parity + Room gate + fast Kotlin lint.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.set_defaults(func=cmd_preflight)

    sp = sub.add_parser("selftest", help="Run the kit hook selftest suite in the kit checkout.")
    sp.add_argument("--kit", help="Kit checkout (default: auto-discover).")
    sp.set_defaults(func=cmd_selftest)

    sp = sub.add_parser("version", help="Print the active kit engine version.")
    sp.add_argument("--kit", help="Kit checkout (default: auto-discover).")
    sp.set_defaults(func=cmd_version)

    sp = sub.add_parser(
        "explain",
        help="Print recent safety-hook decisions from the append-only audit log.",
    )
    sp.add_argument("--last", type=int, default=20, metavar="N", help="How many records to show.")
    sp.add_argument(
        "--repo",
        help="Checkout whose audit log to read (default: cwd, falling back to the kit's own log).",
    )
    sp.add_argument("--kit", help="Kit checkout (default: auto-discover).")
    sp.set_defaults(func=cmd_explain)

    sp = sub.add_parser(
        "verify",
        help="Run the read-only final verifier for an active vNext task.",
    )
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--task", required=True, help="Approved task id to verify.")
    sp.add_argument("--kit", help="Kit checkout (default: auto-discover).")
    sp.set_defaults(func=cmd_verify)

    return p


def main(argv: list[str] | None = None) -> int:
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\n[!] Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
