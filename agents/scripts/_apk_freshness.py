"""APK Freshness & Stale Build Barrier for Android Harness.

Validates that an APK artifact is strictly newer than all modified source files,
resources, and build configs in the repository, and that the latest assemble
gate result is valid and matches the current Git commit.
"""
from __future__ import annotations

import dataclasses
import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gate_results import current_head_sha, gate_artifact_name, read_gate_result  # noqa: E402
from _repo_files import REPO, changed_paths  # noqa: E402
from _variants import assemble_task  # noqa: E402

# File extensions that affect the compiled APK
APP_SOURCE_EXTENSIONS = {
    ".kt",
    ".java",
    ".kts",
    ".gradle",
    ".xml",
    ".json",
    ".properties",
    ".pro",
    ".toml",
    ".cpp",
    ".c",
    ".cc",
    ".cxx",
    ".h",
    ".hpp",
    ".aidl",
    ".proto",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".svg",
    ".ttf",
    ".otf",
}

# Directories and paths ignored during staleness evaluation
EXCLUDED_DIR_PARTS = {
    ".git",
    ".agents",
    "agents",
    "build",
    ".gradle",
    ".idea",
    ".harness-backup",
    ".harness-setup",
    ".cxx",
}


@dataclasses.dataclass
class FreshnessVerdict:
    is_fresh: bool
    status: str  # "FRESH", "STALE_SOURCE", "STALE_COMMIT", "MISSING_APK", "FAILED_BUILD"
    reason: str
    stale_file: str | None = None
    apk_mtime: float | None = None
    source_mtime: float | None = None
    time_diff_sec: float | None = None

    @property
    def time_diff_display(self) -> str:
        if self.time_diff_sec is None:
            return ""
        diff = abs(self.time_diff_sec)
        if diff < 60:
            return f"{diff:.1f}s"
        if diff < 3600:
            return f"{diff / 60:.1f}m"
        return f"{diff / 3600:.1f}h"


def _is_relevant_app_file(path: Path, repo: Path) -> bool:
    """Return True if modifying this file necessitates rebuilding the APK."""
    try:
        rel_parts = path.resolve().relative_to(repo.resolve()).parts
    except Exception:
        rel_parts = path.parts

    # Exclude non-app directories
    for part in rel_parts:
        if part in EXCLUDED_DIR_PARTS:
            return False

    # Exclude top-level markdown or non-code files
    if len(rel_parts) == 1 and path.suffix.lower() in (".md", ".txt"):
        return False
    if "docs" in rel_parts and path.suffix.lower() == ".md":
        return False

    suffix = path.suffix.lower()
    if suffix in APP_SOURCE_EXTENSIONS:
        return True

    name = path.name.lower()
    if name in ("androidmanifest.xml", "gradle.properties", "local.properties", "libs.versions.toml"):
        return True

    return False


def check_apk_freshness(
    apk: Path,
    repo: Path | None = None,
    flavor: str | None = None,
    *,
    timestamp_margin_sec: float = 0.5,
) -> FreshnessVerdict:
    """Evaluate whether the specified APK is fresh relative to working tree and git state.

    Args:
        apk: Absolute or repo-relative path to the target APK.
        repo: Base repository directory (defaults to REPO).
        flavor: Optional build flavor string.
        timestamp_margin_sec: Tolerance window (seconds) to account for filesystem timestamp jitter.

    Returns:
        FreshnessVerdict indicating freshness, status code, and detailed diagnosis.
    """
    repo = Path(repo) if repo else REPO
    apk_p = Path(apk)
    apk_path = (repo / apk_p) if not apk_p.is_absolute() else apk_p

    # 1. Existence check
    if not apk_path.is_file():
        task = assemble_task(flavor)
        return FreshnessVerdict(
            is_fresh=False,
            status="MISSING_APK",
            reason=f"APK not found at {apk_path.as_posix()}. Assemble debug first: python .agents/scripts/run_gradle_task.py {task}",
            apk_mtime=None,
        )

    try:
        apk_mtime = apk_path.stat().st_mtime
    except Exception as exc:
        return FreshnessVerdict(
            is_fresh=False,
            status="MISSING_APK",
            reason=f"Unable to read APK stats for {apk_path.as_posix()}: {exc}",
        )

    # 2. Check Git working tree changes (staged, unstaged, untracked)
    newest_file: Path | None = None
    newest_mtime = 0.0

    try:
        modified_paths = changed_paths()
    except Exception:
        modified_paths = []

    for path in modified_paths:
        if not path.is_file():
            continue
        if not _is_relevant_app_file(path, repo):
            continue
        try:
            mtime = path.stat().st_mtime
            if mtime > (apk_mtime + timestamp_margin_sec):
                if mtime > newest_mtime:
                    newest_mtime = mtime
                    newest_file = path
        except Exception:
            continue

    if newest_file is not None:
        try:
            rel_name = newest_file.relative_to(repo).as_posix()
        except Exception:
            rel_name = str(newest_file)
        diff_sec = newest_mtime - apk_mtime
        task = assemble_task(flavor)
        apk_time_str = datetime.datetime.fromtimestamp(apk_mtime).strftime("%Y-%m-%d %H:%M:%S")
        file_time_str = datetime.datetime.fromtimestamp(newest_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return FreshnessVerdict(
            is_fresh=False,
            status="STALE_SOURCE",
            reason=(
                f"Source file '{rel_name}' was modified at {file_time_str}, which is "
                f"{diff_sec:.1f}s newer than the APK built at {apk_time_str}. "
                f"You MUST run: python .agents/scripts/run_gradle_task.py {task}"
            ),
            stale_file=rel_name,
            apk_mtime=apk_mtime,
            source_mtime=newest_mtime,
            time_diff_sec=diff_sec,
        )

    # 3. Check assemble gate result artifact
    task_name = assemble_task(flavor)
    artifact_name = gate_artifact_name(task_name)
    gate_result = read_gate_result(artifact_name)

    if gate_result:
        status = str(gate_result.get("status") or "").upper()
        if status != "PASS":
            return FreshnessVerdict(
                is_fresh=False,
                status="FAILED_BUILD",
                reason=f"Last assemble gate for '{task_name}' did not PASS (recorded status: {status}). Rebuild required.",
                apk_mtime=apk_mtime,
            )

        gate_sha = str(gate_result.get("git_sha") or "")
        head_sha = current_head_sha()
        # If working tree has no uncommitted code changes, but HEAD commit moved past the assemble gate commit
        if gate_sha and head_sha and (gate_sha != head_sha) and not modified_paths:
            return FreshnessVerdict(
                is_fresh=False,
                status="STALE_COMMIT",
                reason=(
                    f"APK was built on git commit {gate_sha[:8]}, but current HEAD is {head_sha[:8]}. "
                    f"Rebuild required: python .agents/scripts/run_gradle_task.py {task_name}"
                ),
                apk_mtime=apk_mtime,
            )

    return FreshnessVerdict(
        is_fresh=True,
        status="FRESH",
        reason="APK is fresh and up to date with all repository source files and build state.",
        apk_mtime=apk_mtime,
    )


def format_freshness_error(verdict: FreshnessVerdict, apk_path: Path, flavor: str | None = None) -> str:
    """Format a prominent, structured error banner when an APK is stale or missing."""
    task = assemble_task(flavor)
    apk_display = apk_path.as_posix()
    lines = [
        "======================================================================",
        " [ERROR] STALE APK DETECTED — BUILD FRESHNESS BARRIER",
        "======================================================================",
        f" Target APK:       {apk_display}",
        f" Detection Status: {verdict.status}",
    ]
    if verdict.apk_mtime:
        apk_dt = datetime.datetime.fromtimestamp(verdict.apk_mtime).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f" APK Timestamp:    {apk_dt}")
    if verdict.stale_file and verdict.source_mtime:
        src_dt = datetime.datetime.fromtimestamp(verdict.source_mtime).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f" Modified Source:  {verdict.stale_file}")
        lines.append(f" Source Timestamp: {src_dt} (+{verdict.time_diff_display} newer)")
    lines.extend([
        f" Reason:           {verdict.reason}",
        "----------------------------------------------------------------------",
        f" Action Required:  python .agents/scripts/run_gradle_task.py {task}",
        "======================================================================",
    ])
    return "\n".join(lines)
