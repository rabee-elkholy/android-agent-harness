"""Publish an explicit release commit after its successful main CI run.

Runs only in the repository's trusted workflow_run context. A release commit's
first line must be exactly 'release: v<agents/VERSION>'. No tag is overwritten.
GitHub's workflow token suppresses ordinary downstream events, so explicitly
dispatch the existing validation and trusted PyPI workflows at the release tag.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

from release_version import extract_changelog_notes, publish_release, wait_for_workflow
from validate_release import validate_release

ROOT = Path(__file__).resolve().parents[1]


def command(*args: str, allow_missing: bool = False):
    result = subprocess.run(list(args), cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        if allow_missing and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def api(repository: str, path: str, *, allow_missing: bool = False):
    output = command("gh", "api", f"repos/{repository}/{path}", allow_missing=allow_missing)
    return json.loads(output) if output is not None else None


def publish(repository: str, sha: str, ci_run: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not re.fullmatch(r"[0-9a-f]{40}", sha) or not ci_run.isdigit():
        raise RuntimeError("invalid release repository, commit or CI run identity")
    if command("git", "rev-parse", "HEAD").strip() != sha:
        raise RuntimeError("checkout does not match the validated commit")
    version = (ROOT / "agents/VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise RuntimeError("invalid release version")
    tag = "v" + version
    title = command("git", "log", "-1", "--format=%s").strip()
    if title != "release: " + tag:
        print("No explicit release commit; publication skipped.")
        return False
    run = api(repository, "actions/runs/" + ci_run)
    if any(run.get(key) != value for key, value in {
        "head_sha": sha, "head_branch": "main", "event": "push", "status": "completed", "conclusion": "success",
        "path": ".github/workflows/ci.yml",
    }.items()):
        raise RuntimeError("release requires successful canonical main CI for the exact commit")
    if api(repository, "git/ref/heads/main")["object"]["sha"] != sha:
        raise RuntimeError("main advanced after CI; publication stopped")
    errors = validate_release(ROOT, version)
    if errors:
        raise RuntimeError("release validation failed: " + "; ".join(errors))
    existing_tag = api(repository, "git/ref/tags/" + tag, allow_missing=True)
    existing_release = api(repository, "releases/tags/" + tag, allow_missing=True)
    if existing_tag and existing_tag.get("object", {}).get("sha") != sha:
        raise RuntimeError("release tag already points elsewhere; never overwrite it")
    if existing_release:
        if not existing_tag or existing_release.get("draft"):
            raise RuntimeError("unexpected existing release state; inspect before retrying")
        print(f"{tag} is already published; no duplicate publication.")
        return False
    if not existing_tag:
        command("gh", "api", f"repos/{repository}/git/refs", "-f", "ref=refs/tags/" + tag, "-f", "sha=" + sha)
    command("gh", "workflow", "run", "release-check.yml", "--ref", tag)
    if not wait_for_workflow("release-check.yml", sha, branch=tag, accept_dispatch=True):
        raise RuntimeError("release tag validation must pass before publication")
    if api(repository, "git/ref/tags/" + tag)["object"]["sha"] != sha:
        raise RuntimeError("release tag changed during validation")
    release_title, notes = extract_changelog_notes(version)
    if not publish_release(tag, release_title, notes):
        raise RuntimeError("GitHub release creation failed; inspect the existing tag before retrying")
    command("gh", "workflow", "run", "publish-pypi.yml", "--ref", tag)
    print(f"Published {tag} at {sha}; dispatched the trusted PyPI workflow.")
    return True


def main() -> int:
    try:
        publish(os.environ.get("GH_REPO", ""), os.environ.get("RELEASE_COMMIT", ""), os.environ.get("RELEASE_CI_RUN", ""))
        return 0
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
