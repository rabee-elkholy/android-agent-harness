"""Android Harness Kit CLI: bootstrap, doctor, preflight, and selftest dispatch.

Zero runtime dependencies. The CLI is a thin dispatcher: the engine always lives
in a kit checkout (agents/scripts). `android-harness init` reuses an existing
kit clone or fetches one into ~/.android-harness/kit.

Usage:
    android-harness init  [--repo PATH] [--lang en|ar] [--kit PATH]
    android-harness update [--repo PATH] [--kit PATH]
    android-harness doctor [--repo PATH] [--json] [--device] [--kit PATH]
    android-harness preflight [--repo PATH] [--kit PATH]
    android-harness selftest [--kit PATH]
    android-harness version [--kit PATH]

Or without installing:
    python harness_cli.py <command> [options]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

KIT_REPO_URL = "https://github.com/rabee-elkholy/android-harness-kit.git"
KIT_DIR = Path.home() / ".android-harness" / "kit"
INSTALL_PROMPT_URL = (
    "https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/install-prompt.md"
)
UPDATE_PROMPT_URL = (
    "https://raw.githubusercontent.com/rabee-elkholy/android-harness-kit/main/docs/update-prompt.md"
)


def _script_root(kit: Path) -> Path:
    return kit / "agents" / "scripts"


def _has_engine(kit: Path) -> bool:
    return (_script_root(kit) / "setup_wizard.py").is_file() and (kit / "agents" / "VERSION").is_file()


def resolve_kit(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    env = os.environ.get("HARNESS_KIT", "").strip()
    if env:
        candidates.append(Path(env).expanduser().resolve())
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
    print(f"[*] Cloning Android Harness Kit into {KIT_DIR} ...")
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", KIT_REPO_URL, str(KIT_DIR)],
        check=False,
    )
    if proc.returncode != 0 or not _has_engine(KIT_DIR):
        raise SystemExit(
            "[ERROR] Kit clone failed. Clone manually:\n"
            f"    git clone {KIT_REPO_URL}\n"
            "then rerun with --kit <path>."
        )
    return KIT_DIR


def refresh_kit(kit: Path) -> None:
    if not (kit / ".git").is_dir():
        print(f"[i] Kit at {kit} is not a git checkout; skipping pull.")
        return
    print(f"[*] Updating kit clone at {kit} (main) ...")
    subprocess.run(["git", "-C", str(kit), "fetch", "origin", "main"], check=False)
    subprocess.run(["git", "-C", str(kit), "pull", "--ff-only", "origin", "main"], check=False)


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
    print(f"       paste {INSTALL_PROMPT_URL}")
    print("       in a NEW strong-model chat opened at the Android project root.")
    print(f"[VERIFY] afterwards: android-harness doctor --repo \"{repo}\"")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    kit = ensure_kit(args.kit)
    current = (kit / "agents" / "VERSION").read_text(encoding="utf-8").strip()
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
    refresh_kit(kit)
    new_version = (kit / "agents" / "VERSION").read_text(encoding="utf-8").strip()
    print(f"[i] Local kit engine now at: v{new_version}")
    print("[NEXT] Port the new engine into your app checkout:")
    print(f"       paste {UPDATE_PROMPT_URL}")
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
    print((kit / "agents" / "VERSION").read_text(encoding="utf-8").strip())
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

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\n[!] Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
