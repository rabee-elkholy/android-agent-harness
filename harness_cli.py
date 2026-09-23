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
    android-harness repair [--repo PATH] [--kit PATH] [--force] [--json]
    android-harness preflight [--repo PATH] [--kit PATH]
    android-harness test [ARGS...] [--repo PATH] [--kit PATH]
    android-harness assemble [TASK...] [--repo PATH] [--kit PATH]
    android-harness review [ARGS...] [--repo PATH] [--kit PATH]
    android-harness device [COMMAND...] [--repo PATH] [--kit PATH]
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
    dest = KIT_DIR
    clean_v = str(version).strip().lstrip("v")
    if clean_v.lower() == "latest":
        branch_arg = ""
        checkout_ref = "HEAD"
    else:
        branch_arg = f"--branch v{clean_v} "
        checkout_ref = f"v{clean_v}"
    return (
        "Remediate manually:\n"
        f'    git clone --depth 1 {branch_arg}--single-branch {KIT_REPO_URL} "{dest}"\n'
        f'    git -C "{dest}" checkout --detach {checkout_ref}\n'
        f'then rerun with --kit "{dest}".'
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
    if not isinstance(manifest, dict):
        raise SystemExit("[ERROR] Kit release checksums manifest has an unsupported schema")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SystemExit("[ERROR] Kit release checksums manifest files inventory is empty or malformed")
    core_files = {"agents/VERSION", "agents/scripts/lifecycle.py"}
    missing_core = core_files - set(files)
    if missing_core:
        raise SystemExit(f"[ERROR] Kit release checksums manifest missing core files: {', '.join(sorted(missing_core))}")

    agents_dir = kit / "agents"
    if not agents_dir.is_dir() or agents_dir.is_symlink():
        raise SystemExit(f"[ERROR] Kit agents directory missing or symlink: {agents_dir}")
    actual_files: set[str] = set()
    ignored_parts = {"state", "cache", "__pycache__"}
    for p in sorted(agents_dir.rglob("*")):
        if p.is_symlink():
            rel_sym = p.relative_to(kit).as_posix()
            raise SystemExit(f"[ERROR] Symlink rejected in kit payload: {rel_sym}")
        if not p.is_file():
            continue
        rel_from_agents = p.relative_to(agents_dir)
        if rel_from_agents.as_posix() == "release_checksums.json":
            continue
        if ignored_parts.intersection(rel_from_agents.parts):
            continue
        if p.suffix.lower() in {".pyc", ".pyo"}:
            continue
        actual_files.add(p.relative_to(kit).as_posix())

    manifest_keys = set(files.keys())
    if actual_files != manifest_keys:
        missing = sorted(manifest_keys - actual_files)
        unexpected = sorted(actual_files - manifest_keys)
        details = []
        if missing:
            details.append(f"missing ({len(missing)}): {', '.join(missing[:10])}")
        if unexpected:
            details.append(f"unexpected ({len(unexpected)}): {', '.join(unexpected[:10])}")
        raise SystemExit(f"[ERROR] Kit release checksums inventory mismatch: {'; '.join(details)}")

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
    git_env = os.environ.copy()
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    steps = [
        (["git", "init", "-q"], True, 30, "git init"),
        (["git", "remote", "add", "origin", url], True, 30, "git remote add"),
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
            120,
            "git fetch",
        ),
        (["git", "checkout", "-q", "--detach", tag], True, 30, "git checkout"),
    ]
    try:
        for step, use_cwd, timeout_sec, op_name in steps:
            try:
                proc = subprocess.run(
                    step,
                    check=False,
                    cwd=str(staging) if use_cwd else None,
                    timeout=timeout_sec,
                    env=git_env,
                )
                if proc.returncode != 0:
                    raise SystemExit(
                        f"[ERROR] Could not provision kit at tag {tag}. {_manual_remediation(version)}"
                    )
            except subprocess.TimeoutExpired:
                raise SystemExit(
                    f"[ERROR] Operation '{op_name}' timed out after {timeout_sec}s while provisioning tag {tag}. "
                    + _manual_remediation(version)
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


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _assert_kit_outside_repo(repo: Path, kit: Path) -> None:
    repo_r = repo.resolve()
    kit_r = kit.resolve()
    if kit_r == repo_r or _is_within(kit_r, repo_r):
        raise SystemExit(
            "[ERROR] Harness kit checkout must live outside the Android project. "
            f"Target app: {repo_r}. "
            f"Kit: {kit_r}. "
            f"Use {KIT_DIR}."
        )


def _find_nested_kit_checkouts(repo: Path) -> list[Path]:
    found: list[Path] = []
    try:
        for child in repo.iterdir():
            if (
                child.is_dir()
                and (child / ".git").exists()
                and (child / "harness_cli.py").is_file()
                and (child / "agents" / "VERSION").is_file()
                and (child / "agents" / "scripts" / "lifecycle.py").is_file()
            ):
                found.append(child.resolve())
    except (OSError, PermissionError):
        pass
    return sorted(found)


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
        kit = resolve_kit(explicit)
    except SystemExit:
        pass
    else:
        _verify_kit_checksums(kit)
        return kit
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
    git_env = os.environ.copy()
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    try:
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
            timeout=120,
            env=git_env,
        )
    except subprocess.TimeoutExpired:
        current = _read_version_file(kit)
        print(
            f"[!] Operation 'git fetch' timed out after 120s; keeping existing pinned checkout v{current}. "
            "Nothing floated to main."
        )
        return

    try:
        checkout = subprocess.run(
            ["git", "-C", str(kit), "checkout", "-q", "--detach", tag],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=git_env,
        )
    except subprocess.TimeoutExpired:
        current = _read_version_file(kit)
        raise SystemExit(
            f"[ERROR] Operation 'git checkout' timed out after 30s while pinning {tag}; "
            f"checkout state is uncertain (previous version: v{current}). "
            + _manual_remediation(want)
        )
        return

    if fetch.returncode != 0 or checkout.returncode != 0:
        current = _read_version_file(kit)
        try:
            detached = subprocess.run(
                ["git", "-C", str(kit), "symbolic-ref", "-q", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                env=git_env,
            )
        except subprocess.TimeoutExpired:
            raise SystemExit(
                "[ERROR] Operation 'git symbolic-ref' timed out after 30s while checking "
                f"the failed {tag} refresh. " + _manual_remediation(current)
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
        [sys.executable, "-u", str(target), *args],
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
    nested = _find_nested_kit_checkouts(repo)
    if nested:
        raise SystemExit(
            "[ERROR] Full Android Agent Harness checkout found inside target project: "
            + ", ".join(map(str, nested))
            + ". Remove/move it outside the app repository and rerun clean setup."
        )
    if getattr(args, "kit", None):
        _assert_kit_outside_repo(repo, Path(args.kit).expanduser().resolve())
    kit = ensure_kit(args.kit)
    _assert_kit_outside_repo(repo, kit)
    version = (kit / "agents" / "VERSION").read_text(encoding="utf-8").strip()
    print("==================================================")
    print(f"[Android Agent Harness] v{version}")
    print(f"  target app : {repo}")
    print(f"  engine kit : {kit}")
    print("==================================================")
    answers_arg = getattr(args, "answers_json", None)
    answers_source: Path | None = None
    if answers_arg:
        p = Path(answers_arg).absolute()
        if p.is_symlink() or not p.is_file():
            raise SystemExit(f"[ERROR] --answers-json path is missing or a symlink: {answers_arg}")
        answers_source = p

    if answers_arg:
        wizard_args = ["write", "--repo", str(repo), "--answers-json", str(answers_source)]
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
    lifecycle_action = "replace-legacy" if getattr(args, "replace_legacy", False) else "install"
    port_code = run_engine_script(
        kit,
        "lifecycle.py",
        [lifecycle_action, "--repo", str(repo), "--kit", str(kit)],
    )
    if port_code != 0:
        print("[!] Engine port reported failures; review doctor output above.")
        return port_code
    print()
    print("[SUCCESS] Android Agent Harness installed; run doctor for local validation.")
    print(f"[VERIFY] Run anytime: android-harness doctor --repo \"{repo}\"")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    no_refresh = bool(getattr(args, "no_refresh", False))
    kit = resolve_kit(args.kit) if no_refresh else ensure_kit(args.kit)
    current = _read_version_file(kit)
    if no_refresh:
        _verify_kit_checksums(kit)
        latest = current
    else:
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
    if not no_refresh:
        if _semver_tuple(latest) > _semver_tuple(current):
            refresh_kit(kit, latest)
        else:
            # No upgrade (or offline): re-assert the pin on the current release tag.
            refresh_kit(kit, current)
    new_version = _read_version_file(kit)
    print(f"[i] Local kit engine now at: v{new_version}")
    if args.repo:
        repo = find_repo(args.repo)
        nested = _find_nested_kit_checkouts(repo)
        if nested:
            raise SystemExit(
                "[ERROR] Full Android Agent Harness checkout found inside target project: "
                + ", ".join(map(str, nested))
                + ". Remove/move it outside the app repository and rerun clean setup."
            )
        _assert_kit_outside_repo(repo, kit)
        answers = repo / ".harness-setup" / "answers.json"
        if answers.is_file():
            try:
                ans_data = json.loads(answers.read_text(encoding="utf-8"))
                if isinstance(ans_data, dict) and ans_data.get("schema") not in (None, 2):
                    print(
                        "[FAIL] Existing setup answers use an unsupported schema.\n"
                        "Clean setup required. Remove/reset .harness-setup and rerun installer."
                    )
                    return 1
            except Exception:
                pass
        answers_arg = getattr(args, "answers_json", None)
        temp_answers = Path(answers_arg).absolute() if answers_arg else None
        old_answers = answers.read_bytes() if answers.is_file() else None
        sys.path.insert(0, str(_script_root(kit)))
        from lifecycle import require_update_idle
        try:
            require_update_idle(repo)
        except RuntimeError as exc:
            print(f"[FAIL] {exc}")
            return 1
        completed = False
        try:
            if temp_answers:
                if temp_answers.is_symlink() or not temp_answers.is_file():
                    raise SystemExit(f"[ERROR] --answers-json path is missing or a symlink: {answers_arg}")
                wizard_code = run_engine_script(
                    kit, "setup_wizard.py",
                    ["write", "--repo", str(repo), "--answers-json", str(temp_answers)],
                )
                if wizard_code != 0:
                    return wizard_code
            if answers.is_file():
                print("[*] Applying a compatible vNext engine update to the app checkout...")
                port_code = run_engine_script(
                    kit, "lifecycle.py", ["update", "--repo", str(repo), "--kit", str(kit)],
                )
                if port_code != 0:
                    print(f"[FAIL] App checkout update failed with exit code {port_code}; success was not recorded.")
                    return port_code
                completed = True
                print("[SUCCESS] App checkout updated and verified.")
                return 0
        finally:
            if temp_answers and not completed:
                if old_answers is None:
                    answers.unlink(missing_ok=True)
                else:
                    answers.write_bytes(old_answers)
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
    forwarded = list(task_args)
    if repo_value is None and forwarded:
        action = forwarded[0]
        forwarded = [action, "--repo", str(repo), *forwarded[1:]]
    if installed.is_file():
        return subprocess.run([sys.executable, str(installed), *forwarded], cwd=str(repo), check=False).returncode
    return run_engine_script(kit, "workflow.py", forwarded)


def cmd_context(args: argparse.Namespace) -> int:
    kit = ensure_kit(args.kit)
    repo = find_repo(args.repo) if args.repo else Path.cwd().resolve()
    cli_args = [args.subaction, "--repo", str(repo)]
    if getattr(args, "json", False):
        cli_args.append("--json")
    if args.subaction == "preview" and getattr(args, "full", False):
        cli_args.append("--full")
    if args.subaction == "note":
        text = getattr(args, "note", None) or getattr(args, "note_text", None)
        if text:
            cli_args.append(text)
        if getattr(args, "section", None):
            cli_args.extend(["--section", args.section])
    if args.subaction == "instruct":
        text = getattr(args, "instruction", None) or getattr(args, "note_text", None)
        if text:
            cli_args.append(text)
        if getattr(args, "scope", None):
            cli_args.extend(["--scope", args.scope])
        if getattr(args, "source", None):
            cli_args.extend(["--source", args.source])
        if getattr(args, "proof_reference", None):
            cli_args.extend(["--proof-reference", args.proof_reference])
        if getattr(args, "strength", None):
            cli_args.extend(["--strength", args.strength])
        if getattr(args, "applies_to", None):
            cli_args.extend(["--applies-to", args.applies_to])
        if getattr(args, "supersedes", None):
            cli_args.extend(["--supersedes", args.supersedes])
    return run_engine_script(kit, "generate_project_context.py", cli_args, capture=getattr(args, "json", False))


def cmd_task_context(args: argparse.Namespace) -> int:
    """Resolve a bounded, read-only architectural slice for a file or symbol."""
    kit = ensure_kit(args.kit)
    repo = find_repo(args.repo) if args.repo else Path.cwd().resolve()
    cli_args = ["--repo", str(repo)]
    if args.file:
        cli_args.extend(["--file", args.file])
    if args.symbol:
        cli_args.extend(["--symbol", args.symbol])
    if args.module:
        cli_args.extend(["--module", args.module])
    if args.source_set:
        cli_args.extend(["--source-set", args.source_set])
    cli_args.extend(["--limit", str(args.limit)])
    if args.json:
        cli_args.append("--json")
    return run_engine_script(kit, "task_context.py", cli_args, capture=args.json)


def cmd_graph(args: argparse.Namespace) -> int:
    """Query the Universal Android Code & Architecture Graph."""
    kit = ensure_kit(args.kit)
    cli_args = []
    if getattr(args, "repo", None):
        cli_args.extend(["--repo", str(args.repo)])
    if getattr(args, "feature", None):
        cli_args.extend(["--feature", args.feature])
    if getattr(args, "find", None):
        cli_args.extend(["--find", args.find])
    if getattr(args, "module", None):
        cli_args.extend(["--module", args.module])
    if getattr(args, "screen", None):
        cli_args.extend(["--screen", args.screen])
    if getattr(args, "depth", None) is not None:
        cli_args.extend(["--depth", str(args.depth)])
    if getattr(args, "limit", None) is not None:
        cli_args.extend(["--limit", str(args.limit)])
    if getattr(args, "arch", False):
        cli_args.append("--arch")
    if getattr(args, "modules", False):
        cli_args.append("--modules")
    if getattr(args, "screens", False):
        cli_args.append("--screens")
    if getattr(args, "features", False):
        cli_args.append("--features")
    if getattr(args, "sync", False):
        cli_args.append("--sync")
    if getattr(args, "stats", False):
        cli_args.append("--stats")
    if getattr(args, "json", False):
        cli_args.append("--json")
    if getattr(args, "format", None) and not getattr(args, "json", False):
        cli_args.extend(["--format", args.format])
    raw_extra = getattr(args, "graph_args", []) or []
    if raw_extra:
        cli_args.extend(raw_extra)
    return run_engine_script(kit, "project_graph.py", cli_args, capture=getattr(args, "json", False))


def cmd_doctor(args: argparse.Namespace) -> int:
    kit = ensure_kit(args.kit)
    repo = find_repo(args.repo) if args.repo else Path.cwd().resolve()
    cli_args = ["--repo", str(repo)]
    if args.json:
        cli_args.append("--json")
    if args.device:
        cli_args.append("--device")
    if getattr(args, "install_check", False):
        cli_args.append("--install-check")
    env_marker = os.environ.get("_IN_HOOK_SELFTEST")
    if env_marker != "1":
        os.environ["_IN_HOOK_SELFTEST"] = "0"
    installed_doctor = repo / ".agents" / "scripts" / "harness_doctor.py"
    installed_version_file = repo / ".agents" / "VERSION"
    if installed_doctor.is_file() and installed_version_file.is_file():
        installed_version = installed_version_file.read_text(encoding="utf-8").strip()
        kit_version = _read_version_file(kit)
        if _semver_tuple(installed_version)[0] != _semver_tuple(kit_version)[0]:
            raise SystemExit(
                f"[ERROR] Installed engine v{installed_version} is incompatible with kit v{kit_version}; "
                "update or repair the target checkout before running doctor."
            )
        doctor_env = os.environ.copy()
        doctor_env["HARNESS_REPO"] = str(repo)
        proc = subprocess.run(
            [sys.executable, "-u", str(installed_doctor), *cli_args],
            check=False,
            capture_output=args.json,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=doctor_env,
            cwd=str(repo),
        )
        if args.json and proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        code = proc.returncode
    else:
        code = run_engine_script(kit, "harness_doctor.py", cli_args, capture=args.json)
    if os.environ.get("_IN_HOOK_SELFTEST") == "0":
        os.environ.pop("_IN_HOOK_SELFTEST", None)
    return code


def cmd_repair(args: argparse.Namespace) -> int:
    repo = find_repo(args.repo) if args.repo else Path.cwd().resolve()
    if getattr(args, "kit", None):
        _assert_kit_outside_repo(repo, Path(args.kit).expanduser().resolve())
    kit = ensure_kit(args.kit)
    _assert_kit_outside_repo(repo, kit)
    nested = _find_nested_kit_checkouts(repo)
    if nested:
        raise SystemExit(
            "[ERROR] Full Android Agent Harness checkout found inside target project: "
            + ", ".join(map(str, nested))
            + ". Remove/move it outside the app repository and rerun clean setup."
        )
    cli_args = ["--repo", str(repo), "--kit", str(kit)]
    if getattr(args, "force", False):
        cli_args.append("--force")
    if getattr(args, "json", False):
        cli_args.append("--json")
    return run_engine_script(kit, "repair.py", cli_args, capture=getattr(args, "json", False))


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
        task_id = getattr(args, "task_id", None) or getattr(args, "task", None)
        forward_args = ["--task-id", task_id] if task_id else []
        if client_script.is_file():
            proc = subprocess.run(
                [sys.executable, str(client_script), *forward_args],
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return proc.returncode
        env = os.environ.copy()
        env["HARNESS_REPO"] = str(repo)
        return run_engine_script(kit, "preflight_check.py", forward_args, env=env)
    finally:
        os.chdir(prev_cwd)


def _dispatch_pipeline_script(args: argparse.Namespace, script_name: str, forward_args: list[str]) -> int:
    kit = ensure_kit(getattr(args, "kit", None))
    repo = find_repo(getattr(args, "repo", None)) if getattr(args, "repo", None) else Path.cwd().resolve()
    installed = repo / ".agents" / "scripts" / script_name
    prev_cwd = Path.cwd()
    os.chdir(repo)
    try:
        if installed.is_file():
            return subprocess.run([sys.executable, str(installed), *forward_args], cwd=str(repo), check=False).returncode
        env = os.environ.copy()
        env["HARNESS_REPO"] = str(repo)
        return run_engine_script(kit, script_name, forward_args, env=env)
    finally:
        os.chdir(prev_cwd)


def cmd_test(args: argparse.Namespace) -> int:
    """Run test gates (unit/instrumented) via run_tests_gate.py."""
    forward = list(args.test_args)
    if forward and forward[0] == "--":
        forward = forward[1:]
    return _dispatch_pipeline_script(args, "run_tests_gate.py", forward)


def cmd_assemble(args: argparse.Namespace) -> int:
    """Run Gradle assemble task via run_gradle_task.py."""
    forward = list(args.gradle_args)
    if forward and forward[0] == "--":
        forward = forward[1:]
    if not forward:
        kit = ensure_kit(getattr(args, "kit", None))
        repo = find_repo(getattr(args, "repo", None)) if getattr(args, "repo", None) else Path.cwd().resolve()
        sys.path.insert(0, str(_script_root(kit)))
        from _variants import resolve_assemble_task
        task_str = resolve_assemble_task(repo)
        forward = [task_str]
    return _dispatch_pipeline_script(args, "run_gradle_task.py", forward)


def cmd_review(args: argparse.Namespace) -> int:
    """Record reviewer verdicts, complete reviewer execution, or build/profile review packages."""
    forward = list(args.review_args)
    if forward and forward[0] == "--":
        forward = forward[1:]
    if not forward:
        return _dispatch_pipeline_script(args, "record_review.py", forward)
    sub = forward[0]
    if sub == "package":
        return _dispatch_pipeline_script(args, "review_package.py", forward[1:])
    if sub == "profile":
        return _dispatch_pipeline_script(args, "review_execution.py", forward[1:])
    if sub in ("complete", "finalize", "dispatch", "status"):
        return _dispatch_pipeline_script(args, "review_orchestrator.py", forward)
    if sub == "ingest":
        return _dispatch_pipeline_script(args, "record_review.py", forward[1:])
    return _dispatch_pipeline_script(args, "record_review.py", forward)


def cmd_commands(args: argparse.Namespace) -> int:
    """Output machine-readable catalog of public harness commands."""
    kit = ensure_kit(getattr(args, "kit", None))
    sys.path.insert(0, str(_script_root(kit)))
    from _public_commands import get_public_commands
    cmds = get_public_commands()
    print(json.dumps(cmds, indent=2, ensure_ascii=False))
    return 0


def cmd_device(args: argparse.Namespace) -> int:
    """Deploy or test on device via run_device.py."""
    forward = list(args.device_args)
    if forward and forward[0] == "--":
        forward = forward[1:]
    if not forward:
        forward = ["install-start"]
    return _dispatch_pipeline_script(args, "run_device.py", forward)


def cmd_phase_review(args: argparse.Namespace) -> int:
    """Build, complete, or finalize scoped phase reviews via phase_review.py."""
    forward = list(args.phase_review_args)
    if forward and forward[0] == "--":
        forward = forward[1:]
    return _dispatch_pipeline_script(args, "phase_review.py", forward)


FULL_SELFTEST_SUITES = (
    "_vnext_selftest.py",
    "_hook_selftest.py",
    "_security_selftest.py",
    "_zoho_selftest.py",
    "_baseline_selftest.py",
    "_graph_selftest.py",
    "_adb_core_selftest.py",
    "_env_codes_selftest.py",
    "_performance_selftest.py",
    "_android_scenarios_selftest.py",
    "_release_safety_selftest.py",
    "_critical_safety_selftest.py",
    "_architecture_selftest.py",
    "_daily_workflow_selftest.py",
    "_stabilization_v41_selftest.py",
    "_stabilization_v42_selftest.py",
    "_public_cli_selftest.py",
    "_project_intelligence_selftest.py",
    "_graph_discovery_selftest.py",
    "_antigravity_stability_selftest.py",
    "_phase_review_v2_selftest.py",
    "_worktree_handoff_selftest.py",
)

QUICK_SELFTEST_SUITES = (
    "_hook_selftest.py",
    "_security_selftest.py",
    "_critical_safety_selftest.py",
    "_daily_workflow_selftest.py",
    "_public_cli_selftest.py",
    "_graph_discovery_selftest.py",
    "_antigravity_stability_selftest.py",
)

assert set(QUICK_SELFTEST_SUITES) < set(FULL_SELFTEST_SUITES)


def cmd_selftest(args: argparse.Namespace) -> int:
    kit = ensure_kit(args.kit)
    prev_cwd = Path.cwd()
    os.chdir(kit)
    # Import step_progress from the kit's _live_process module
    import importlib.util as _ilu
    _lp_path = _script_root(kit) / "_live_process.py"
    _lp_spec = _ilu.spec_from_file_location("_live_process", str(_lp_path))
    _lp_mod = _ilu.module_from_spec(_lp_spec)  # type: ignore[arg-type]
    _lp_spec.loader.exec_module(_lp_mod)  # type: ignore[union-attr]
    _step = _lp_mod.step_progress
    _live = _lp_mod.live_print
    try:
        scripts = QUICK_SELFTEST_SUITES if getattr(args, "quick", False) else FULL_SELFTEST_SUITES
        mode = "QUICK" if getattr(args, "quick", False) else "FULL"
        _live(f"selftest mode: {mode}")
        total = len(scripts)
        timings: list[tuple[str, float]] = []
        for idx, script in enumerate(scripts, 1):
            label = script.replace("_selftest.py", "").lstrip("_")
            _live(f"selftest: {label} [{idx}/{total}]")
            t0 = time.time()
            target = _script_root(kit) / script
            runner_code = (
                "import sys, os;"
                "sys.path.insert(0, r'" + str(_script_root(kit)) + "');"
                "from _live_process import enable_subtask_test_runner;"
                "enable_subtask_test_runner();"
                "import runpy; runpy.run_path(r'" + str(target) + "', run_name='__main__')"
            )
            proc = subprocess.run(
                [sys.executable, "-c", runner_code],
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            code = proc.returncode
            elapsed = time.time() - t0
            timings.append((label, elapsed))
            if code != 0:
                _live(f"selftest: {label} [{idx}/{total}] [Fail] ({elapsed:.1f}s)")
                return code
            _live(f"selftest: {label} [{idx}/{total}] [Done] ({elapsed:.1f}s)")
        _live(f"\n✅ All {total} selftest suites passed.")
        timings.sort(key=lambda x: x[1], reverse=True)
        _live("Slowest suites:")
        for rank, (t_label, t_el) in enumerate(timings[:5], 1):
            _live(f"{rank}. {t_label} {t_el:.1f}s")
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
    task_id = getattr(args, "task", "") or getattr(args, "task_id", "")
    if not task_id:
        sys.path.insert(0, str(_script_root(kit)))
        try:
            from mutation_guard import active_plan
            plan = active_plan(repo)
            task_id = str(plan.get("task_id") or "")
        except Exception:
            pass
    if not task_id:
        print("[FAIL] No active task found in repository; pass --task-id <id>", file=sys.stderr)
        return 1
    client_workflow = repo / ".agents" / "scripts" / "workflow.py"
    if client_workflow.is_file():
        proc = subprocess.run(
            [sys.executable, str(client_workflow), "verify", "--repo", str(repo), "--task-id", task_id],
            cwd=str(repo), check=False,
        )
        return proc.returncode
    return run_engine_script(kit, "workflow.py", ["verify", "--repo", str(repo), "--task-id", task_id])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="android-harness",
        description="Android Agent Harness Kit control CLI (zero dependencies).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", aliases=["setup"], help="Run the setup wizard against an Android checkout.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--lang", choices=("en", "ar"), default=None, help="Wizard language.")
    sp.add_argument("--kit", help="Kit checkout to use (default: auto-discover or clone).")
    sp.add_argument("--answers-json", help="Path to validated answers JSON for non-interactive setup.")
    sp.add_argument("--replace-legacy", action="store_true", help="Atomically replace a pre-v1 .agents installation.")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("update", help="Refresh the local kit engine and print upgrade steps.")
    sp.add_argument("--repo", help="Android checkout that consumes the engine.")
    sp.add_argument("--kit", help="Kit checkout to refresh (default: auto-discover or clone).")
    sp.add_argument("--force", action="store_true", help="Force remote release check.")
    sp.add_argument("--no-refresh", action="store_true", help="Use the already verified pinned kit without network refresh.")
    sp.add_argument("--answers-json", help="Optional new wizard answers collected by chat.")
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
    sp.add_argument("--install-check", action="store_true", help="Fast post-install structural validation.")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("repair", help="Deterministic restore of managed harness files from pinned kit.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.add_argument("--force", action="store_true", help="Force repair even if an active task exists.")
    sp.add_argument("--json", action="store_true", help="Output machine-readable JSON report.")
    sp.set_defaults(func=cmd_repair)

    sp = sub.add_parser("preflight", help="String parity + Room gate + fast Kotlin lint.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--task-id", "--task", dest="task_id", default="", help="Task ID for preflight validation.")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.set_defaults(func=cmd_preflight)

    sp = sub.add_parser("test", help="Run test gates (unit/instrumented) via run_tests_gate.py.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.add_argument("test_args", nargs=argparse.REMAINDER, help="Arguments passed to run_tests_gate.py")
    sp.set_defaults(func=cmd_test)

    sp = sub.add_parser("assemble", help="Run Gradle assemble via run_gradle_task.py.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.add_argument("gradle_args", nargs=argparse.REMAINDER, help="Gradle task arguments (resolved dynamically from project configuration if omitted)")
    sp.set_defaults(func=cmd_assemble)

    sp = sub.add_parser("review", help="Record reviewer results via record_review.py.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.add_argument("review_args", nargs=argparse.REMAINDER, help="Arguments passed to record_review.py")
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser("device", help="Deploy or inspect device via run_device.py.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.add_argument("device_args", nargs=argparse.REMAINDER, help="Device arguments (default: install-start)")
    sp.set_defaults(func=cmd_device)

    sp = sub.add_parser("phase-review", help="Build, complete, or finalize scoped phase delta reviews.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout providing the engine.")
    sp.add_argument("phase_review_args", nargs=argparse.REMAINDER, help="Arguments passed to phase_review.py")
    sp.set_defaults(func=cmd_phase_review)

    sp = sub.add_parser("context", help="Inspect, preview, refresh, or add notes/instructions to derived project context.")
    sp.add_argument("subaction", choices=("preview", "generate", "status", "refresh", "note", "instruct"), help="Context action.")
    sp.add_argument("note_text", nargs="?", default="", help="Note or instruction text.")
    sp.add_argument("--note", default="", help="Note text to append.")
    sp.add_argument("--instruction", default="", help="Instruction text.")
    sp.add_argument("--scope", default="GLOBAL", help="Instruction scope (e.g. module::payments, package:com.example, global).")
    sp.add_argument("--source", choices=("conversation", "developer_terminal", "host_native"), default=None, help="Explicit developer authority source.")
    sp.add_argument("--proof-reference", default="", help="Message or command reference proving developer direction.")
    sp.add_argument("--strength", choices=("REQUIREMENT", "PREFERENCE"), default="REQUIREMENT")
    sp.add_argument("--applies-to", default="ANY", help="Applicable task intents (ANY, PRESERVE, NEW, REFACTOR, MIGRATION).")
    sp.add_argument("--supersedes", default=None, help="Prior instruction ID to supersede.")
    sp.add_argument("--section", default="Domain Conventions & Context", help="Section header in project-notes.md.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout to use (default: auto-discover or clone).")
    sp.add_argument("--json", action="store_true", help="Format output as JSON.")
    sp.add_argument("--full", action="store_true", help="For context preview, print the complete diagnostic payload.")
    sp.set_defaults(func=cmd_context)

    sp = sub.add_parser("task-context", help="Resolve bounded read-only context for one file or symbol.")
    target = sp.add_mutually_exclusive_group(required=True)
    target.add_argument("--file", help="Repository-relative or absolute source file path.")
    target.add_argument("--symbol", help="Short symbol name or fully qualified name.")
    sp.add_argument("--module", help="Optional module qualifier for ambiguous symbols.")
    sp.add_argument("--source-set", help="Optional source-set qualifier for ambiguous symbols.")
    sp.add_argument("--limit", type=int, default=20, help="Maximum related items to return (1-100).")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout to use (default: auto-discover or clone).")
    sp.add_argument("--json", action="store_true", help="Format output as JSON.")
    sp.set_defaults(func=cmd_task_context)

    sp = sub.add_parser("graph", help="Query the Universal Android Code & Architecture Graph.")
    sp.add_argument("--feature", help="Analyze and display architecture slice for a feature.")
    sp.add_argument("--find", help="Find symbol, screen, or class with dependencies.")
    sp.add_argument("--module", help="Focus graph on a specific Gradle module.")
    sp.add_argument("--screen", help="Focus graph on a specific screen or composable.")
    sp.add_argument("--depth", type=int, default=2, help="Traversal depth around focus node.")
    sp.add_argument("--limit", type=int, default=80, help="Maximum nodes rendered (0 disables cap).")
    sp.add_argument("--arch", action="store_true", help="Display Clean Architecture layers graph.")
    sp.add_argument("--modules", action="store_true", help="Display Gradle module dependency graph.")
    sp.add_argument("--screens", action="store_true", help="List UI screens/layouts.")
    sp.add_argument("--features", action="store_true", help="List all detected feature modules.")
    sp.add_argument("--sync", action="store_true", help="Force full cache resynchronization.")
    sp.add_argument("--stats", action="store_true", help="Display graph cache statistics.")
    sp.add_argument("--format", choices=("compact", "mermaid", "dot", "json"), default=None, help="Output format.")
    sp.add_argument("--json", action="store_true", help="Format output as JSON.")
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument("--kit", help="Kit checkout to use (default: auto-discover or clone).")
    sp.add_argument("graph_args", nargs=argparse.REMAINDER, help="Additional arguments passed to project_graph.py")
    sp.set_defaults(func=cmd_graph)

    sp = sub.add_parser("selftest", help="Run the kit hook selftest suite in the kit checkout.")
    sp.add_argument("--kit", help="Kit checkout (default: auto-discover).")
    sp.add_argument(
        "--quick",
        action="store_true",
        help="Run high-value developer-loop selftest subset.",
    )
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
    sp.add_argument("--task", "--task-id", dest="task", default="", help="Approved task id to verify (defaults to active task).")
    sp.add_argument("--kit", help="Kit checkout (default: auto-discover).")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser(
        "commands",
        help="Print machine-readable catalog of public harness commands as JSON.",
    )
    sp.add_argument("--json", action="store_true", default=True, help="Output format as JSON (default: true).")
    sp.add_argument("--kit", help="Kit checkout (default: auto-discover).")
    sp.set_defaults(func=cmd_commands)

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
