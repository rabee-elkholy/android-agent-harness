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
    ver_file.write_text(f"{new_version}\n", encoding="utf-8")
    logs.append(f"Updated agents/VERSION -> {new_version}")

    # 2. pyproject.toml
    pyproject_file = ROOT / "pyproject.toml"
    if pyproject_file.is_file():
        text = pyproject_file.read_text(encoding="utf-8")
        updated = re.sub(r'version\s*=\s*"[^"]+"', f'version = "{new_version}"', text)
        pyproject_file.write_text(updated, encoding="utf-8")
        logs.append(f"Updated pyproject.toml -> version = \"{new_version}\"")

    # 3. CITATION.cff
    citation_file = ROOT / "CITATION.cff"
    if citation_file.is_file():
        text = citation_file.read_text(encoding="utf-8")
        text = re.sub(r'version:\s*\S+', f'version: {new_version}', text)
        text = re.sub(r'date-released:\s*\S+', f'date-released: {today}', text)
        citation_file.write_text(text, encoding="utf-8")
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
        selftest_file.write_text(updated, encoding="utf-8")
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
    if not args.dry_run and pin_urls and fill_checksums:
        pin_logs = pin_urls(target_version)
        checksum_logs = fill_checksums(target_version)
        for line in pin_logs + checksum_logs:
            print(f"  + {line}")
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
        "agents/VERSION",
        "pyproject.toml",
        "CITATION.cff",
        "CHANGELOG.md",
        "agents/scripts/_hook_selftest.py",
        "README.md",
        "docs/",
        "scripts_dev/",
    ]
    run_cmd(["git", "add", *stage_paths])

    commit_msg = f"release: v{target_version}"
    res_commit = run_cmd(["git", "commit", "-m", commit_msg], check=False)
    if res_commit.returncode == 0:
        print(f"  + Created commit: {commit_msg}")
    else:
        print(f"  + Working tree already clean or commit skipped ({res_commit.stderr.strip()})")

    tag_name = f"v{target_version}"
    res_tag = run_cmd(["git", "tag", "-f", tag_name])
    print(f"  + Tagged: {tag_name}")

    if args.no_push:
        print(f"\n[OK] Release {tag_name} prepared locally (--no-push).")
        return 0

    print("  + Pushing commit and tag to GitHub...")
    run_cmd(["git", "push", "origin", "main"])
    run_cmd(["git", "push", "origin", tag_name, "-f"])
    print(f"  [SUCCESS] Pushed {tag_name} to origin.")

    # Create/update GitHub Release via gh CLI if installed
    if shutil.which("gh"):
        print("  + Publishing GitHub Release via gh CLI...")
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
