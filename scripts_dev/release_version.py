"""Unified, one-command release automation for android-agent-harness.

Automates version bumping, prompt URL pinning, cryptographic checksum recalculation,
changelog extraction, selftest verification, Git tagging, and GitHub Release publication.

Usage:
    python scripts_dev/release_version.py 0.14.22
    python scripts_dev/release_version.py --patch
    python scripts_dev/release_version.py --minor
    python scripts_dev/release_version.py 0.14.22 --dry-run
    python scripts_dev/release_version.py 0.14.22 --no-push
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts_dev"))

try:
    from pin_prompt_docs import fill_checksums, pin_urls
except ImportError:
    pin_urls = None
    fill_checksums = None

try:
    from generate_release_checksums import main as generate_checksums
except ImportError:
    generate_checksums = None

try:
    from validate_release import validate_release
except ImportError:
    validate_release = None


def read_current_version() -> str:
    return (ROOT / "agents" / "VERSION").read_text(encoding="utf-8").strip()


def parse_semver(ver_str: str) -> tuple[int, int, int]:
    clean = ver_str.strip().lstrip("v")
    parts = [int(p) for p in clean.split(".") if p.isdigit()]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def bump_semver(current: str, part: str) -> str:
    major, minor, patch = parse_semver(current)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unknown semver bump part: {part}")


def update_version_files(new_version: str) -> list[str]:
    logs = []
    today = datetime.date.today().isoformat()

    # 1. agents/VERSION
    ver_file = ROOT / "agents" / "VERSION"
    ver_file.write_text(f"{new_version}\n", encoding="utf-8", newline="\n")
    logs.append(f"Updated agents/VERSION -> {new_version}")

    # 2. pyproject.toml
    pyproject_file = ROOT / "pyproject.toml"
    if pyproject_file.is_file():
        text = pyproject_file.read_text(encoding="utf-8")
        updated = re.sub(r'version\s*=\s*"[^"]+"', f'version = "{new_version}"', text)
        pyproject_file.write_text(updated, encoding="utf-8", newline="\n")
        logs.append(f"Updated pyproject.toml -> version = \"{new_version}\"")

    # 3. CITATION.cff
    citation_file = ROOT / "CITATION.cff"
    if citation_file.is_file():
        text = citation_file.read_text(encoding="utf-8")
        text = re.sub(r'version:\s*\S+', f'version: {new_version}', text)
        text = re.sub(r'date-released:\s*\S+', f'date-released: {today}', text)
        citation_file.write_text(text, encoding="utf-8", newline="\n")
        logs.append(f"Updated CITATION.cff -> version: {new_version}, date-released: {today}")

    # 4. agents/scripts/_hook_selftest.py
    selftest_file = ROOT / "agents" / "scripts" / "_hook_selftest.py"
    if selftest_file.is_file():
        text = selftest_file.read_text(encoding="utf-8")
        updated = re.sub(
            r'get_current_version\(\)\s*==\s*"[^"]+"',
            f'get_current_version() == "{new_version}"',
            text,
        )
        selftest_file.write_text(updated, encoding="utf-8", newline="\n")
        logs.append(f"Updated _hook_selftest.py assertion -> {new_version}")

    return logs


def extract_changelog_notes(version: str) -> tuple[str, str]:
    """Extracts headline and notes body for the given version from CHANGELOG.md."""
    changelog_file = ROOT / "CHANGELOG.md"
    if not changelog_file.is_file():
        return f"Release v{version}", f"Release notes for v{version}."

    text = changelog_file.read_text(encoding="utf-8")
    pattern = rf"## \[{re.escape(version)}\](?:[^\n]*)\n+(.*?)(?=\n## \[|\n---|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return f"Release v{version}", f"Release notes for v{version}."

    section = match.group(1).strip()
    headline_match = re.search(r"###\s+(.+)", section)
    title = headline_match.group(1).strip() if headline_match else f"Release v{version}"

    # Append full changelog link if compare is possible
    all_versions = re.findall(r"## \[(\d+\.\d+\.\d+)\]", text)
    full_notes = section
    if len(all_versions) >= 2 and all_versions[0] == version:
        prev_version = all_versions[1]
        full_notes += (
            f"\n\n**Full Changelog**: "
            f"https://github.com/rabee-elkholy/android-agent-harness/compare/v{prev_version}...v{version}"
        )

    return f"v{version}: {title}", full_notes


def run_cmd(cmd: list[str], *, check: bool = True, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def tag_exists_locally(tag_name: str) -> bool:
    res = subprocess.run(["git", "tag", "-l", tag_name], cwd=ROOT, capture_output=True, text=True, check=False)
    return bool(res.returncode == 0 and tag_name in res.stdout.split())


def tag_remote_status(tag_name: str) -> str:
    """Return 'PRESENT', 'ABSENT', or 'UNKNOWN'."""
    try:
        res = subprocess.run(
            ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag_name}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if res.returncode == 0:
            return "PRESENT" if res.stdout.strip() else "ABSENT"
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def github_release_status(tag_name: str) -> str:
    """Return 'PRESENT', 'ABSENT', or 'UNKNOWN'."""
    if not shutil.which("gh"):
        return "UNKNOWN"
    try:
        res = subprocess.run(
            ["gh", "release", "view", tag_name],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if res.returncode == 0:
            return "PRESENT"
        stderr = (res.stderr or "").lower()
        if "release not found" in stderr or "not found" in stderr or "404" in stderr:
            return "ABSENT"
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def tag_exists_remotely(tag_name: str) -> bool:
    return tag_remote_status(tag_name) == "PRESENT"


def github_release_exists(tag_name: str) -> bool:
    return github_release_status(tag_name) == "PRESENT"



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unified one-command release automation for android-agent-harness."
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="Explicit version (e.g. 0.14.22). Mutually exclusive with --patch/--minor.",
    )
    parser.add_argument("--patch", action="store_true", help="Auto-bump patch version.")
    parser.add_argument("--minor", action="store_true", help="Auto-bump minor version.")
    parser.add_argument("--major", action="store_true", help="Auto-bump major version.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the release process without committing, tagging, or publishing.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit and tag locally, but skip git push and GitHub release publication.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip executing _hook_selftest.py.",
    )
    parser.add_argument(
        "--allow-tag-overwrite",
        action="store_true",
        help="Emergency recovery flag: allow overwriting existing git tag/release.",
    )
    args = parser.parse_args(argv)

    current_version = read_current_version()

    # Determine target version
    if args.patch:
        target_version = bump_semver(current_version, "patch")
    elif args.minor:
        target_version = bump_semver(current_version, "minor")
    elif args.major:
        target_version = bump_semver(current_version, "major")
    elif args.version:
        target_version = args.version.strip().lstrip("v")
    else:
        parser.error("Specify a version (e.g. 0.14.22) or use --patch / --minor.")

    if not re.fullmatch(r"\d+\.\d+\.\d+", target_version):
        print(f"[ERROR] Version must be semver X.Y.Z format, got '{target_version}'.")
        return 1

    tag_name = f"v{target_version}"
    if not args.allow_tag_overwrite:
        if tag_exists_locally(tag_name):
            print(f"[ERROR] Tag '{tag_name}' already exists locally. Release tags are immutable. Increment the patch version.")
            return 1
        if not args.dry_run and not args.no_push:
            remote_tag_state = tag_remote_status(tag_name)
            if remote_tag_state == "PRESENT":
                print(f"[ERROR] Tag '{tag_name}' already exists on remote origin. Release tags are immutable. Increment the patch version.")
                return 1
            elif remote_tag_state == "UNKNOWN":
                print(f"[ERROR] Could not reliably verify remote tag status for '{tag_name}' on origin. Preflight check failed closed.")
                return 1

            gh_release_state = github_release_status(tag_name)
            if gh_release_state == "PRESENT":
                print(f"[ERROR] GitHub release '{tag_name}' already exists. Published releases are immutable. Increment the patch version.")
                return 1
            elif gh_release_state == "UNKNOWN":
                print(f"[ERROR] Could not reliably verify GitHub release status for '{tag_name}'. Preflight check failed closed.")
                return 1
    else:
        gh_release_state = github_release_status(tag_name)
        if gh_release_state == "PRESENT":
            print(f"[ERROR] Cannot overwrite published GitHub release '{tag_name}'. Release tags are immutable once published.")
            return 1

    print(f"[*] Release target: v{target_version} (current: v{current_version})")
    if args.dry_run:
        print("[i] Running in DRY-RUN mode (no git mutations or remote changes).")

    # Step 1: Check CHANGELOG.md for the target version
    changelog_path = ROOT / "CHANGELOG.md"
    if changelog_path.is_file():
        changelog_content = changelog_path.read_text(encoding="utf-8")
        if f"## [{target_version}]" not in changelog_content:
            print(
                f"[!] Warning: '## [{target_version}]' not found in CHANGELOG.md. "
                "Please add release notes before releasing."
            )
            if not args.dry_run:
                return 1

    # Step 2: Version bumping
    print("\n[1/5] Updating version files...")
    if not args.dry_run:
        for log_line in update_version_files(target_version):
            print(f"  + {log_line}")
    else:
        print(f"  [dry-run] Would update agents/VERSION, pyproject.toml, CITATION.cff, _hook_selftest.py to {target_version}")

    # Step 3: URL Pinning & Cryptographic Hashes
    print("\n[2/5] Pinning prompt URLs & computing SHA-256 tamper-evident hashes...")
    if not args.dry_run:
        if pin_urls and fill_checksums:
            pin_logs = pin_urls(target_version)
            checksum_logs = fill_checksums(target_version)
            for line in pin_logs + checksum_logs:
                print(f"  + {line}")
        if generate_checksums:
            generate_checksums()
            print("  + Generated agents/release_checksums.json")
    else:
        print(f"  [dry-run] Would pin URLs to v{target_version} and compute prompt hashes.")

    # Step 4: Run Tests
    if not args.skip_tests:
        print("\n[3/5] Running hook selftest suite...")
        selftest_cmd = [sys.executable, str(ROOT / "agents" / "scripts" / "_hook_selftest.py")]
        env = dict(os.environ)
        env["_IN_HOOK_SELFTEST"] = "1"
        res = subprocess.run(selftest_cmd, cwd=ROOT, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"[FAIL] Selftest failed with return code {res.returncode}:")
            print(res.stdout[-1500:])
            print(res.stderr[-1500:])
            return 1
        print("  [SUCCESS] All hook self-tests passed (0 failures).")

    if validate_release and not args.dry_run:
        print("  + Running validate_release suite...")
        val_errors = validate_release(ROOT, target_version)
        if val_errors:
            print("[FAIL] Release validation failed:")
            for err in val_errors:
                print(f"  - {err}")
            return 1
        print("  [SUCCESS] Release validation passed.")

        # Verify PyPI build & metadata
        try:
            import build as _
            import twine as _
            print("  + Verifying distribution packaging build and twine check...")
            res_build = subprocess.run([sys.executable, "-m", "build"], cwd=ROOT, capture_output=True, text=True)
            if res_build.returncode != 0:
                print(f"[FAIL] Package build failed:\n{res_build.stderr}")
                return 1
            res_twine = subprocess.run([sys.executable, "-m", "twine", "check", "dist/*"], cwd=ROOT, capture_output=True, text=True)
            if res_twine.returncode != 0 or "FAILED" in res_twine.stdout:
                print(f"[FAIL] Twine check failed:\n{res_twine.stdout}\n{res_twine.stderr}")
                return 1
            print("  [SUCCESS] Distribution package builds cleanly and passes twine check.")
        except ImportError:
            print("  [i] 'build' or 'twine' not installed; skipping local packaging verification.")
        finally:
            for d in ["dist", "build", "android_agent_harness.egg-info"]:
                shutil.rmtree(ROOT / d, ignore_errors=True)
    else:
        print("\n[3/5] Skipping tests (--skip-tests).")

    # Step 5: Git & GitHub Release
    title, notes = extract_changelog_notes(target_version)
    print(f"\n[4/5] Extracted release notes ({len(notes)} chars):")
    print(f"  Title: {title}")

    if args.dry_run:
        print("\n[5/5] [dry-run] Release preparation complete. Would commit, tag, push, and create GitHub release.")
        return 0

    print("\n[5/5] Committing, tagging, and publishing release...")
    stage_paths = [
        ".gitignore",
        ".github/",
        "agents/",
        "AGENTS.md",
        "GEMINI.md",
        "pyproject.toml",
        "CITATION.cff",
        "CHANGELOG.md",
        "README.md",
        "harness_cli.py",
        "docs/",
        "scripts_dev/",
    ]
    run_cmd(["git", "add", *stage_paths])

    commit_msg = f"release: v{target_version}"
    res_commit = run_cmd(["git", "commit", "-m", commit_msg], check=False)
    combined_commit_out = (res_commit.stdout or "") + "\n" + (res_commit.stderr or "")
    if res_commit.returncode == 0:
        print(f"  + Created commit: {commit_msg}")
    elif "nothing to commit" in combined_commit_out.lower() or "working tree clean" in combined_commit_out.lower():
        print("  + Working tree already clean, no new commit needed.")
    else:
        print(f"[FAIL] Git commit failed with code {res_commit.returncode}:\n{combined_commit_out.strip()}")
        return 1

    tag_name = f"v{target_version}"
    tag_cmd = ["git", "tag", "-f", tag_name] if args.allow_tag_overwrite else ["git", "tag", tag_name]
    res_tag = run_cmd(tag_cmd)
    print(f"  + Tagged: {tag_name}")

    if args.no_push:
        print(f"\n[OK] Release {tag_name} prepared locally (--no-push).")
        return 0

    print("  + Pushing commit and tag to GitHub...")
    run_cmd(["git", "push", "origin", "main"])
    push_tag_cmd = ["git", "push", "origin", tag_name, "-f"] if args.allow_tag_overwrite else ["git", "push", "origin", tag_name]
    run_cmd(push_tag_cmd)
    print(f"  [SUCCESS] Pushed {tag_name} to origin.")

    # Create/update GitHub Release via gh CLI if installed
    if shutil.which("gh"):
        print("  + Publishing GitHub Release via gh CLI...")
        if not args.allow_tag_overwrite and github_release_exists(tag_name):
            print(f"[FAIL] GitHub Release '{tag_name}' already exists. Release versions are immutable. Increment the patch version.")
            return 1

        gh_proc = subprocess.run(
            [
                "gh",
                "release",
                "create",
                tag_name,
                "--title",
                title,
                "--notes",
                notes,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if gh_proc.returncode != 0 and "already exists" in gh_proc.stderr:
            if not args.allow_tag_overwrite:
                print(f"[FAIL] GitHub Release '{tag_name}' already exists. Release versions are immutable. Increment the patch version.")
                return 1
            gh_proc = subprocess.run(
                [
                    "gh",
                    "release",
                    "edit",
                    tag_name,
                    "--title",
                    title,
                    "--notes",
                    notes,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        if gh_proc.returncode == 0:
            print(f"  [SUCCESS] GitHub Release published: https://github.com/rabee-elkholy/android-agent-harness/releases/tag/{tag_name}")
        else:
            print(f"  [!] gh release warning: {gh_proc.stderr.strip()}")
    else:
        print("  [!] gh CLI not found on PATH. Release tag pushed, publish release notes via GitHub web UI.")


    print(f"\n==================================================")
    print(f"[SUCCESS] Release v{target_version} completed successfully!")
    print(f"==================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
