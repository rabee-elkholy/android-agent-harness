"""Android Harness Kit CLI: bootstrap, doctor, preflight, and selftest dispatch.

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
    android-harness verify [--repo PATH] [--verdict PATH] [--rerun-checks] [--kit PATH]
    android-harness doctor [--repo PATH] [--json] [--device] [--kit PATH]
    android-harness preflight [--repo PATH] [--kit PATH]
    android-harness selftest [--kit PATH]
    android-harness version [--kit PATH]

Or without installing:
    python harness_cli.py <command> [options]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

KIT_REPO_URL = "https://github.com/rabee-elkholy/android-harness-kit.git"
RELEASES_API_URL = "https://api.github.com/repos/rabee-elkholy/android-harness-kit/releases/latest"
KIT_DIR = Path.home() / ".android-harness" / "kit"


def _prompt_url(version: str, doc: str) -> str:
    """Immutable release-tag URL for a one-click lifecycle prompt doc."""
    return (
        "https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/"
        f"v{str(version).strip().lstrip('v')}/docs/{doc}"
    )


def _manual_remediation(version: str) -> str:
    return (
        "Remediate manually:\n"
        f"    git clone {KIT_REPO_URL}\n"
        f"    git -C android-harness-kit checkout v{version}\n"
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


def _provision_pinned(url: str, dest: Path, version: str) -> None:
    """Fresh checkout of exactly tag v<version>. No main, no float."""
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
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
    for step, use_cwd in steps:
        proc = subprocess.run(step, check=False, cwd=str(dest) if use_cwd else None)
        if proc.returncode != 0:
            shutil.rmtree(dest, ignore_errors=True)
            raise SystemExit(
                f"[ERROR] Could not provision kit at tag {tag}. {_manual_remediation(version)}"
            )


def _script_root(kit: Path) -> Path:
    return kit / "agents" / "scripts"


def _has_engine(kit: Path) -> bool:
    return (_script_root(kit) / "setup_wizard.py").is_file() and (kit / "agents" / "VERSION").is_file()


EXIT_PASS = 0
EXIT_FINDINGS = 1
EXIT_CONFIG_ERROR = 2
EXIT_INFRA_ERROR = 3
EXIT_INCOMPLETE_OR_STALE = 4


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
        candidates.append(parent / "android-harness-kit")
    for cand in candidates:
        if _has_engine(cand):
            return cand
    raise SystemExit(
        "[ERROR] No Android Harness Kit engine found. "
        "Pass --kit /path/to/android-harness-kit, set HARNESS_KIT, run from the kit "
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
    print(f"[*] Provisioning Android Harness Kit at pinned tag v{requested} into {KIT_DIR} ...")
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


def run_engine_script(kit: Path, script: str, args: list[str], *, capture: bool = False) -> int:
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
    print(f"[Android Harness Kit] v{version}")
    print(f"  target app : {repo}")
    print(f"  engine kit : {kit}")
    print("==================================================")
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
    print()
    print("[NEXT] Answers recorded. Finish the structural port with your AI agent:")
    print(f"       paste {_prompt_url(version, 'install-prompt.md')}")
    print("       in a NEW strong-model chat opened at the Android project root.")
    print(f"[VERIFY] afterwards: android-harness doctor --repo \"{repo}\"")
    return 0


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
    print("[NEXT] Port the new engine into your app checkout:")
    print(f"       paste {_prompt_url(new_version, 'update-prompt.md')}")
    print("       in a NEW strong-model chat opened at the Android project root.")
    return 0


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
    kit = ensure_kit(args.kit)
    repo = find_repo(args.repo) if args.repo else Path.cwd().resolve()
    prev_cwd = Path.cwd()
    os.chdir(repo)
    try:
        return run_engine_script(kit, "preflight_check.py", [])
    finally:
        os.chdir(prev_cwd)


def cmd_selftest(args: argparse.Namespace) -> int:
    kit = ensure_kit(args.kit)
    prev_cwd = Path.cwd()
    os.chdir(kit)
    try:
        return run_engine_script(kit, "_hook_selftest.py", [])
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
    sys.path.insert(0, str(_script_root(kit)))
    try:
        from policy_vocab import REASON_CODES
    except Exception:
        REASON_CODES = {}

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
        label = REASON_CODES.get(code, code or "UNSPECIFIED")
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
    kit = ensure_kit(args.kit)
    repo = find_repo(args.repo) if args.repo else Path.cwd().resolve()
    if args.verdict:
        verdict_path = Path(args.verdict).expanduser().resolve()
    else:
        candidates: list[Path] = []
        for rel in (".agents/state/verdicts", "agents/state/verdicts"):
            vdir = repo / rel
            if vdir.is_dir():
                candidates.extend(sorted(vdir.glob("verdict-*.json")))
        if not candidates:
            raise SystemExit(
                "[ERROR] No verdict artifacts found under the repo state dirs. "
                "Run `python .agents/scripts/review_package.py` and complete a "
                "5-leaf review round first."
            )
        verdict_path = candidates[-1]
    try:
        record = json.loads(verdict_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"[ERROR] Cannot read verdict {verdict_path}: {exc}")
    if not isinstance(record, dict) or record.get("schema_version") not in (1, 2):
        raise SystemExit("[FAIL] verdict artifact missing or unsupported schema_version (expected 1 or 2).")
    print(f"[*] Verifying {verdict_path.name} against {repo}")

    problems: list[str] = []

    if record.get("verdict") != "PASS":
        problems.append(f"verdict is {record.get('verdict')!r}, expected PASS")

    package = record.get("package") or {}
    raw_pkg_path = str(package.get("path") or "").strip()
    pkg_sha = str(package.get("sha256") or "")
    if raw_pkg_path:
        pkg_path = Path(raw_pkg_path).resolve()
        repo_res = repo.resolve()
        temp_res = Path(tempfile.gettempdir()).resolve()
        is_safe_pkg = (
            repo_res in pkg_path.parents
            or pkg_path == repo_res
            or temp_res in pkg_path.parents
        )
        if not is_safe_pkg:
            problems.append(f"review package path escapes allowed directories: {raw_pkg_path}")
        elif pkg_path.is_file() and pkg_sha:
            digest = hashlib.sha256(pkg_path.read_bytes()).hexdigest()
            if digest != pkg_sha:
                problems.append(f"review package content changed since the round: {pkg_path.name}")
        elif not pkg_path.is_file():
            problems.append(f"review package file missing: {pkg_path}")
    else:
        problems.append("review package path missing in verdict")

    files = record.get("files") or {}
    missing: list[str] = []
    changed: list[str] = []
    escaped: list[str] = []
    repo_res = repo.resolve()
    for rel, want in sorted(files.items()):
        fpath = (repo / str(rel).replace("/", os.sep)).resolve()
        if repo_res not in fpath.parents and fpath != repo_res:
            escaped.append(str(rel))
            continue
        if not fpath.is_file():
            missing.append(str(rel))
            continue
        digest = hashlib.sha256(fpath.read_bytes()).hexdigest()
        if digest != want:
            changed.append(str(rel))
    for rel in escaped:
        problems.append(f"reviewed file path escapes repository root: {rel}")
    for rel in missing[:10]:
        problems.append(f"file from the reviewed diff is missing in this checkout: {rel}")
    if len(missing) > 10:
        problems.append(f"... and {len(missing) - 10} more missing files")
    for rel in changed[:10]:
        problems.append(f"file changed since the verified round: {rel}")
    if len(changed) > 10:
        problems.append(f"... and {len(changed) - 10} more changed files")

    CANONICAL_LEAVES = {
        "bug",
        "convention",
        "conv",
        "security",
        "perf",
        "regression",
        "bug-reviewer-agent",
        "convention-reviewer-agent",
        "security-reviewer-agent",
        "perf-anr-guardian-agent",
        "regression-impact-reviewer-agent",
    }
    leaves = record.get("leaves") or {}
    if record.get("verdict") == "PASS":
        if len(leaves) != 5:
            problems.append(f"{len(leaves)}/5 leaf verdicts recorded")
        else:
            unknown_leaves = set(leaves.keys()) - CANONICAL_LEAVES
            if unknown_leaves:
                problems.append(f"unknown leaf names in verdict: {sorted(unknown_leaves)}")

    stale = False
    git_sha = str(record.get("git_sha") or "")
    if git_sha:
        proc_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        head = (proc_head.stdout or "").strip()
        if re.fullmatch(r"[0-9a-f]{40}", head) and head != git_sha:
            stale = True
            print(f"[!] STALE: verdict generated at {git_sha[:12]} but HEAD is {head[:12]}.")

    if args.rerun_checks:
        engine_scripts = repo / ".agents" / "scripts"
        if not engine_scripts.is_dir():
            print("[i] --rerun-checks skipped: this checkout has no installed .agents engine.")
        else:
            checks_ok = True
            for script in ("fast_kt_lint.py", "check_strings.py"):
                target = engine_scripts / script
                if not target.is_file():
                    continue
                proc_chk = subprocess.run(
                    [sys.executable, str(target)],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if proc_chk.returncode != 0:
                    checks_ok = False
                    tail = "\n".join((proc_chk.stdout or "").strip().splitlines()[-8:])
                    print(f"[FAIL] {script}:")
                    print(tail)
            if not checks_ok:
                problems.append("re-run checks failed")

    if problems:
        print(f"\n[FAIL] verify failed with {len(problems)} problem(s):")
        for item in problems:
            print(f"  - {item}")
        return 1
    if stale:
        print(
            "\n[STALE] Package and file hashes match the recorded verdict, but it was "
            "generated at a different commit than the current HEAD."
        )
        return 2
    print(
        "\n[PASS] Verdict artifact verified: package hash, changed-file hashes, and "
        "5 evidenced leaves all match this checkout."
    )
    return 0


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
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("update", help="Refresh the local kit engine and print upgrade steps.")
    sp.add_argument("--repo", help="Android checkout that consumes the engine.")
    sp.add_argument("--kit", help="Kit checkout to refresh (default: auto-discover or clone).")
    sp.add_argument("--force", action="store_true", help="Force remote release check.")
    sp.set_defaults(func=cmd_update)

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
        help="Verify a review verdict.json artifact against actual repo state.",
    )
    sp.add_argument("--repo", help="Android/KMP project root (default: cwd).")
    sp.add_argument(
        "--verdict",
        help="Path to a verdict-*.json file (default: newest under the repo state dir).",
    )
    sp.add_argument(
        "--rerun-checks",
        action="store_true",
        help="Additionally re-run fast_kt_lint.py and check_strings.py (requires an installed .agents engine).",
    )
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
