"""Has the task's base commit left the current branch (branch switch, reset or rebase mid-task)?

Real app: the developer switched branch while a task was open. The task's changes are measured from the
commit it started on, so every difference between the two branches counted as the task's: approve said
only "repository identity changed: head", `--capture-red` refused five times with "application source
modifications already detected" (only a test had changed), and `--record-unrelated` called another
feature's test this task's own. Commits made on top of the base are fine; only a base that is no longer
an ancestor of HEAD means the ground moved.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def base_moved(repo: Path, task_id: str) -> dict | None:
    """{"base_head", "base_branch", "head", "branch"} when the base is no longer under HEAD, else None."""
    try:
        from delivery_manifest import load_task_baseline

        base = load_task_baseline(repo, task_id) or {}
    except Exception:
        return None
    identity = base.get("repository") or {}
    base_head = str(identity.get("head") or "")
    if not base_head:
        return None
    code, head = _git(repo, "rev-parse", "HEAD")
    if code != 0 or not head or head == base_head:
        return None
    if _git(repo, "merge-base", "--is-ancestor", base_head, "HEAD")[0] == 0:
        return None
    _code, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return {"base_head": base_head, "base_branch": str(identity.get("branch") or ""), "head": head, "branch": branch}


def moved_message(moved: dict, task_id: str) -> str:
    was = f"{moved.get('base_branch') or 'its branch'} at {str(moved.get('base_head'))[:10]}"
    now = f"{moved.get('branch') or 'another branch'} at {str(moved.get('head'))[:10]}"
    return (
        f"TASK_BASE_MOVED: this task started on {was}; the checkout is now on {now}, which does not contain that "
        "commit. Every difference between the two counts as this task's change, so gates and test records fail "
        "for that reason, not for the task's own edits. Do not retry. Ask the developer with ask_question: switch "
        f"back to {moved.get('base_branch') or 'the original branch'} (their own git command), or cancel this task "
        f"and start it again here (`python .agents/scripts/workflow.py cancel --repo . --task-id {task_id} "
        "--source conversation --proof-reference \"<their words>\"`)."
    )
