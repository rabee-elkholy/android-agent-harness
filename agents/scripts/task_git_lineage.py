"""Task Git Lineage and Worktree Handoff Management.

Implements Sections 12-18 and Section 29 of ANTIGRAVITY_FINAL_WORKFLOW_STABILITY_REPAIR_SPEC.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from _vnext_common import (
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    git,
    git_text,
    read_json,
    utc_now,
)
from delivery_manifest import (
    build_manifest,
    build_task_manifest,
    load_task_baseline,
)
from plan_authority import save_plan
from workflow import state_root, task_dir

SECRET_PATH_MARKERS = (".env", "keystore", "jks", "secret", "token", "credentials", "local.properties")


def checkpoints_dir(task_directory: Path) -> Path:
    return task_directory / "git-checkpoints"


def pending_handoff_file(task_directory: Path) -> Path:
    return task_directory / "pending-handoff.json"


def compute_receipt_sha(receipt: dict[str, Any]) -> str:
    clean = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    return canonical_sha256(clean)


def is_valid_task_lineage(repo: Path, task_id: str, current_head: str) -> tuple[bool, str]:
    tdir = task_dir(repo, task_id)
    plan_f = tdir / "plan.json"
    if not plan_f.is_file():
        return False, f"plan not found for task '{task_id}'"
    plan = read_json(plan_f)

    base_head = plan.get("task_base_head") or plan.get("repository", {}).get("head", "")
    if not base_head:
        return False, "task base head not defined in plan"

    if current_head == base_head:
        return True, "head matches immutable task base head"

    # Inspect checkpoint receipts
    cdir = checkpoints_dir(tdir)
    accepted_heads: set[str] = set()
    if cdir.is_dir():
        for r_file in cdir.glob("*.json"):
            try:
                receipt = read_json(r_file)
                if receipt.get("receipt_sha256") == compute_receipt_sha(receipt):
                    accepted_heads.add(receipt.get("checkpoint_head", ""))
            except Exception:
                continue

    plan_accepted = set(plan.get("accepted_checkpoint_heads") or [])
    if plan.get("accepted_checkpoint_head"):
        plan_accepted.add(plan["accepted_checkpoint_head"])

    valid_heads = accepted_heads | plan_accepted
    if current_head not in valid_heads:
        return False, f"HEAD/branch lineage mismatch: commit {current_head[:8]} is not in accepted checkpoints"

    # Verify current_head is a git descendant of base_head
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_head, current_head],
        cwd=str(repo),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return False, f"lineage check failed: {current_head[:8]} is not a descendant of task base {base_head[:8]}"

    # Check for unauthorized merge commits
    merges_proc = subprocess.run(
        ["git", "rev-list", "--merges", f"{base_head}..{current_head}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if merges_proc.returncode == 0 and merges_proc.stdout.strip():
        return False, "TASK_HEAD_LINEAGE_RECONCILIATION_REQUIRED: merge commit detected in task lineage"

    return True, "valid accepted checkpoint descendant"


def create_pending_handoff(repo: Path, task_id: str) -> dict[str, Any]:
    tdir = task_dir(repo, task_id)
    plan_f = tdir / "plan.json"
    if not plan_f.is_file():
        raise ValidationError(f"task plan not found for '{task_id}'")
    plan = read_json(plan_f)
    status = plan.get("status")

    if status == "VERIFYING":
        return {
            "code": "RESUME_IMPLEMENTATION",
            "kind": "HOST_ACTION",
            "command": "",
            "blocking": True,
            "reason": "Task is in VERIFYING state. Must resume to IMPLEMENTING before creating a handoff.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {},
        }

    if status == "READY_FOR_DELIVERY":
        return {
            "code": "DEVELOPER_GIT_COMMIT_REQUIRED",
            "kind": "DEVELOPER_ACTION",
            "command": "",
            "blocking": True,
            "reason": "Task is READY_FOR_DELIVERY. Use final Git delivery commit flow instead of handoff.",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {},
        }

    if status != "IMPLEMENTING":
        raise ValidationError(f"cannot prepare handoff for task '{task_id}' with status '{status}'")

    # Section 16.3: Unsafe dirty baseline detection
    baseline_files_dir = tdir / "baseline-files"
    if baseline_files_dir.is_dir():
        for b_file in baseline_files_dir.rglob("*"):
            if b_file.is_file():
                rel = b_file.relative_to(baseline_files_dir).as_posix().lower()
                if any(m in rel for m in SECRET_PATH_MARKERS):
                    cur_target = repo / rel
                    if cur_target.is_file():
                        base_bytes = b_file.read_bytes()
                        cur_bytes = cur_target.read_bytes()
                        if base_bytes != cur_bytes:
                            raise ValidationError(
                                "HANDOFF_COMMIT_UNSAFE_DIRTY_BASELINE: pre-existing dirty sensitive file overlaps intended commit"
                            )

    task_base = load_task_baseline(repo, task_id)
    if task_base:
        all_base_entries = list(task_base.get("changes") or []) + list(task_base.get("sensitive_changes") or [])
        for b_entry in all_base_entries:
            rel = str(b_entry.get("path") or "").replace("\\", "/")
            if any(m in rel.lower() for m in SECRET_PATH_MARKERS):
                cur_target = repo / rel
                cur_oid = ""
                if cur_target.is_file():
                    cur_oid = "git:" + git(repo, "hash-object", "--path", rel, "--stdin", input_bytes=cur_target.read_bytes()).decode("utf-8").strip()
                if cur_oid != b_entry.get("content_identity"):
                    raise ValidationError(
                        "HANDOFF_COMMIT_UNSAFE_DIRTY_BASELINE: pre-existing dirty sensitive file overlaps intended commit"
                    )

    # Check for unmerged conflicts
    proc_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc_status.returncode == 0:
        for line in proc_status.stdout.splitlines():
            if line.startswith("U ") or line.startswith("AA") or line.startswith("UU") or line.startswith("DD"):
                raise ValidationError(f"Conflicted path in working tree: {line}")

    # Build manifest
    manifest = build_task_manifest(repo)
    task_changes = manifest.get("task_changes") or manifest.get("changes") or []
    expected_files = sorted({c.get("path") for c in task_changes if c.get("path")})

    current_head = git_text(repo, "rev-parse", "HEAD")
    task_base_head = plan.get("task_base_head") or plan.get("repository", {}).get("head") or current_head
    if not plan.get("task_base_head"):
        plan["task_base_head"] = task_base_head
        save_plan(plan_f, plan)

    pending_data = {
        "schema_version": 1,
        "task_id": task_id,
        "plan_sha256": plan.get("plan_sha256"),
        "task_base_head": task_base_head,
        "parent_head": current_head,
        "delivery_snapshot_sha256": manifest.get("delivery_snapshot_sha256"),
        "task_change_set_sha256": manifest.get("task_change_set_sha256"),
        "expected_files": expected_files,
        "created_at": utc_now(),
    }
    pending_f = pending_handoff_file(tdir)
    atomic_write_json(pending_f, pending_data)

    suggested_commit = f"wip({plan.get('kind', 'feature').lower()}): checkpoint for {task_id}"
    return {
        "code": "DEVELOPER_WIP_COMMIT_REQUIRED",
        "kind": "DEVELOPER_ACTION",
        "command": "",
        "blocking": True,
        "reason": (
            "Task checkpoint snapshot frozen. Developer action required: create a Git commit "
            "for this WIP checkpoint, then reconcile the handoff."
        ),
        "inputs": {
            "repo": ".",
            "task_id": task_id,
            "parent_head": current_head,
            "expected_files": expected_files,
            "suggested_commit": suggested_commit,
        },
        "expected": {},
    }


def reconcile_handoff(repo: Path, task_id: str) -> dict[str, Any]:
    tdir = task_dir(repo, task_id)
    pending_f = pending_handoff_file(tdir)
    if not pending_f.is_file():
        raise ValidationError(f"no pending handoff found for task '{task_id}'")

    pending = read_json(pending_f)
    parent_head = pending.get("parent_head")
    current_head = git_text(repo, "rev-parse", "HEAD")

    if current_head == parent_head:
        raise ValidationError(f"no developer commit detected; HEAD unchanged from parent_head '{parent_head[:8]}'")

    # Check that current_head is a descendant of parent_head
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", parent_head, current_head],
        cwd=str(repo),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ValidationError(
            f"lineage check failed: current HEAD '{current_head[:8]}' is not a descendant of parent_head '{parent_head[:8]}'"
        )

    # Check for unauthorized merge commits
    merges_proc = subprocess.run(
        ["git", "rev-list", "--merges", f"{parent_head}..{current_head}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if merges_proc.returncode == 0 and merges_proc.stdout.strip():
        raise ValidationError("TASK_HEAD_LINEAGE_RECONCILIATION_REQUIRED: merge commit detected during handoff")

    # Section 15.1: Task files must be clean
    manifest = build_manifest(repo)
    expected_files = set(pending.get("expected_files") or [])
    live_changes = manifest.get("changes") or []
    dirty_task_files = [c.get("path") for c in live_changes if c.get("path") in expected_files]
    if dirty_task_files:
        raise ValidationError(f"task files still dirty after commit: {', '.join(dirty_task_files)}")

    # Section 15.2: Commit hook content mutation detection
    live_snapshot = manifest.get("delivery_snapshot_sha256")
    expected_snapshot = pending.get("delivery_snapshot_sha256")
    if live_snapshot != expected_snapshot:
        raise ValidationError(
            f"HANDOFF_COMMIT_CONTENT_CHANGED: delivery snapshot mismatch (expected {expected_snapshot[:8]}, got {live_snapshot[:8]}). "
            "A commit hook or external process modified file contents during commit."
        )

    # Write accepted checkpoint receipt
    cdir = checkpoints_dir(tdir)
    cdir.mkdir(parents=True, exist_ok=True)
    receipt_data = {
        "schema_version": 1,
        "task_id": task_id,
        "plan_sha256": pending.get("plan_sha256"),
        "task_base_head": pending.get("task_base_head"),
        "parent_head": parent_head,
        "checkpoint_head": current_head,
        "delivery_snapshot_sha256": live_snapshot,
        "task_change_set_sha256": pending.get("task_change_set_sha256"),
        "expected_files": pending.get("expected_files"),
        "created_at": utc_now(),
    }
    receipt_data["receipt_sha256"] = compute_receipt_sha(receipt_data)
    receipt_path = cdir / f"{current_head}.json"
    atomic_write_json(receipt_path, receipt_data)

    # Update plan
    plan_f = tdir / "plan.json"
    plan = read_json(plan_f)
    plan["accepted_checkpoint_head"] = current_head
    accepted_heads = list(plan.get("accepted_checkpoint_heads") or [])
    if current_head not in accepted_heads:
        accepted_heads.append(current_head)
    plan["accepted_checkpoint_heads"] = accepted_heads
    save_plan(plan_f, plan)

    # Clear pending handoff
    pending_f.unlink()

    return {
        "status": "WORKTREE_SWITCH_READY",
        "task_id": task_id,
        "checkpoint_head": current_head,
        "receipt_path": str(receipt_path),
    }
