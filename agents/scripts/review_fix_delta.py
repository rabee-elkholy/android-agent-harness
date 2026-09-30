"""Files changed since a reviewed run, and the reviewers those files alone route.

`prepare-verification` uses it to narrow a later review round, and the final verifier recomputes it
from the same saved manifests, so a stored policy is never trusted on its own word.
"""
from __future__ import annotations

from pathlib import Path


def _entries(manifest: dict) -> dict[str, tuple]:
    changes = manifest.get("task_changes") if "task_changes" in manifest else manifest.get("changes")
    return {
        str(item.get("path")): (item.get("content_identity"), item.get("status"), item.get("git_mode"))
        for item in changes or [] if isinstance(item, dict) and item.get("path")
    }


def compute_fix_delta(
    repo: Path,
    task_directory: Path,
    previous_run_id: str,
    current_manifest: dict,
    plan: dict,
    skills_root: Path,
    project_kind: str,
) -> dict | None:
    """{"files": [...], "reviewers": [...]}, or None when the delta cannot be judged (everyone reruns)."""
    try:
        from _vnext_common import read_json, validate_id
        from change_classifier import classify
        from review_policy import decide

        validate_id(previous_run_id, "run_id")
        previous = read_json(Path(task_directory) / f"manifest-{previous_run_id}.json")
        before, after = _entries(previous), _entries(current_manifest)
        if not before or not after:
            return None
        files = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
        if not files:
            return {"files": [], "reviewers": []}
        present = [{"path": path} for path in files if path in after]
        if not present:
            # Only deletions since the review: the regression reviewer covers what they break.
            return {"files": files, "reviewers": ["regression-impact-reviewer-agent"]}
        delta_class = classify(repo, task_changes=present, candidate_paths=[item["path"] for item in present], progress=False)
        if not delta_class.get("surfaces"):
            return None
        # The delta's own classification (surfaces, size, severity), never mixed with the whole change's.
        routed = decide(delta_class, skills_root, project_kind=project_kind,
                        task_kind=str(plan.get("task_kind") or "FEATURE"), plan=plan)
        reviewers = set(routed.get("reviewers") or [])
        if any(path not in after for path in files):
            reviewers.add("regression-impact-reviewer-agent")
        return {"files": files, "reviewers": sorted(reviewers)}
    except Exception:
        return None
