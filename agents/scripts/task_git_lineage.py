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


def validate_checkpoint_receipt(
    repo: Path,
    task_id: str,
    base_head: str,
    receipt_path: Path,
    known_valid_heads: set[str],
) -> tuple[bool, str, dict[str, Any] | None]:
    if not receipt_path.is_file():
        return False, f"receipt file not found: {receipt_path}", None
    try:
        receipt = read_json(receipt_path)
    except Exception as exc:
        return False, f"corrupt receipt json: {exc}", None

    if not isinstance(receipt, dict):
        return False, "receipt is not a dict", None

    head = str(receipt.get("checkpoint_head") or "").strip()
    if not head or receipt_path.stem != head:
        return False, f"receipt filename '{receipt_path.name}' mismatch: does not match checkpoint_head '{head}'", None

    if receipt.get("task_id") != task_id:
        return False, f"receipt task_id '{receipt.get('task_id')}' mismatch: expected '{task_id}'", None

    if receipt.get("task_base_head") != base_head:
        return False, f"receipt task_base_head '{receipt.get('task_base_head')}' mismatch: expected '{base_head}'", None

    if receipt.get("receipt_sha256") != compute_receipt_sha(receipt):
        return False, f"receipt checksum invalid for '{head[:8]}'", None

    parent_head = str(receipt.get("parent_head") or "").strip()
    if not parent_head:
        return False, "receipt missing parent_head", None

    if parent_head != base_head and parent_head not in known_valid_heads:
        return False, f"parent_head '{parent_head[:8]}' is not base_head or a previously validated checkpoint", None

    # Check that head is a descendant of parent_head
    proc_anc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", parent_head, head],
        cwd=str(repo),
        capture_output=True,
        check=False,
    )
    if proc_anc.returncode != 0:
        return False, f"checkpoint '{head[:8]}' is not a descendant of parent '{parent_head[:8]}'", None

    tdir = task_dir(repo, task_id)
    plan_f = tdir / "plan.json"
    if not plan_f.is_file():
        return False, "checkpoint task plan is missing", None
    try:
        plan = read_json(plan_f)
        approved_shas = {plan.get("plan_sha256")}
        for sp in plan.get("superseded_plans", []):
            if isinstance(sp, dict) and sp.get("plan_sha256"):
                approved_shas.add(sp.get("plan_sha256"))
        rec_plan_sha = receipt.get("plan_sha256")
        if not rec_plan_sha or rec_plan_sha not in approved_shas:
            return False, f"receipt plan_sha256 '{str(rec_plan_sha)[:8]}' not in approved plan chain", None
    except Exception as exc:
        return False, f"cannot validate checkpoint against plan: {exc}", None

    # Supported one-commit transition
    proc_cnt = subprocess.run(
        ["git", "rev-list", "--count", f"{parent_head}..{head}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc_cnt.returncode != 0:
        return False, f"cannot inspect commit count between '{parent_head[:8]}' and '{head[:8]}'", None
    if int(proc_cnt.stdout.strip() or 0) != 1:
        return False, f"checkpoint '{head[:8]}' is not a single-commit transition from parent '{parent_head[:8]}'", None

    # No merge parent
    proc_merges = subprocess.run(
        ["git", "rev-list", "--merges", f"{parent_head}..{head}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc_merges.returncode != 0 or proc_merges.stdout.strip():
        return False, f"merge commit detected in checkpoint '{head[:8]}'", None

    return True, "", receipt


def resolve_valid_checkpoint_heads(repo: Path, task_id: str, base_head: str) -> set[str]:
    tdir = task_dir(repo, task_id)
    cdir = checkpoints_dir(tdir)
    if not cdir.is_dir():
        return set()

    receipt_files = list(cdir.glob("*.json"))
    valid_heads: set[str] = set()

    changed = True
    while changed:
        changed = False
        for rf in receipt_files:
            if rf.stem in valid_heads:
                continue
            ok, _, rec = validate_checkpoint_receipt(repo, task_id, base_head, rf, valid_heads)
            if ok and rec:
                valid_heads.add(rec["checkpoint_head"])
                changed = True

    return valid_heads


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

    valid_heads = resolve_valid_checkpoint_heads(repo, task_id, base_head)
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


def accept_requested_delivery_commit(repo: Path, task_id: str, plan: dict[str, Any]) -> str | None:
    """Accept the developer commit that DEVELOPER_GIT_COMMIT_REQUIRED asked for.

    When a READY task goes stale and resumes, HEAD may hold exactly one new commit
    containing only the files verified in the frozen run. That commit is the
    requested delivery commit, not a foreign lineage change, so it is recorded as an
    accepted checkpoint (same receipt schema as a WIP handoff). Anything else - more
    commits, merges, or files outside the verified change set - is left unaccepted.
    """
    tdir = task_dir(repo, task_id)
    base_head = plan.get("task_base_head") or (plan.get("repository") or {}).get("head", "")
    current_head = git_text(repo, "rev-parse", "HEAD")
    if not base_head or current_head == base_head:
        return None
    valid_heads = resolve_valid_checkpoint_heads(repo, task_id, base_head)
    if current_head in valid_heads:
        return None
    accepted = str(plan.get("accepted_checkpoint_head") or "")
    parent_head = accepted if accepted in valid_heads else base_head

    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)

    if _git("merge-base", "--is-ancestor", parent_head, current_head).returncode != 0:
        return None
    merges = _git("rev-list", "--merges", f"{parent_head}..{current_head}")
    count = _git("rev-list", "--count", f"{parent_head}..{current_head}")
    if merges.returncode != 0 or merges.stdout.strip() or count.returncode != 0 or count.stdout.strip() != "1":
        return None

    current_run = tdir / "current-run.json"
    if not current_run.is_file():
        return None
    run_manifest = Path(str(read_json(current_run).get("manifest") or ""))
    if not run_manifest.is_file():
        return None
    frozen = read_json(run_manifest)
    changes = frozen.get("task_changes") if "task_changes" in frozen else frozen.get("changes") or []
    verified_paths = {str(c.get("path") or "").replace("\\", "/") for c in changes if isinstance(c, dict) and c.get("path")}
    committed = _git("diff", "--name-only", parent_head, current_head)
    committed_paths = {line.strip().replace("\\", "/") for line in committed.stdout.splitlines() if line.strip()}
    if committed.returncode != 0 or not committed_paths or not committed_paths <= verified_paths:
        return None

    receipt_data = {
        "schema_version": 2,
        "kind": "REQUESTED_DELIVERY_COMMIT",
        "task_id": task_id,
        "plan_sha256": plan.get("plan_sha256"),
        "task_base_head": base_head,
        "parent_head": parent_head,
        "checkpoint_head": current_head,
        "checkpoint_paths": sorted(committed_paths),
        "created_at": utc_now(),
    }
    receipt_data["receipt_sha256"] = compute_receipt_sha(receipt_data)
    cdir = checkpoints_dir(tdir)
    cdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cdir / f"{current_head}.json", receipt_data)
    plan["accepted_checkpoint_head"] = current_head
    heads = list(plan.get("accepted_checkpoint_heads") or [])
    if current_head not in heads:
        heads.append(current_head)
    plan["accepted_checkpoint_heads"] = heads
    return current_head


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
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py task resume --task-id {task_id}",
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

    current_head = git_text(repo, "rev-parse", "HEAD")
    task_base_head = plan.get("task_base_head") or plan.get("repository", {}).get("head") or current_head
    if not plan.get("task_base_head"):
        plan["task_base_head"] = task_base_head
        save_plan(plan_f, plan)

    # The original baseline attributes all generations of Task A. The checkpoint
    # parent baseline attributes only work since the last accepted WIP commit.
    if not isinstance(task_base, dict):
        raise ValidationError("HANDOFF_TASK_BASELINE_MISSING: immutable task baseline is required")
    expected_scope = plan.get("expected_files")
    full_manifest = build_task_manifest(
        repo, task_base, expected_files=expected_scope, task_base_head=task_base_head,
    )
    full_changes = full_manifest.get("task_changes") or full_manifest.get("changes") or []
    dirty_at_start = {
        str(entry.get("path") or "").replace("\\", "/")
        for entry in task_base.get("changes") or [] if isinstance(entry, dict)
    }
    binary_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".jar", ".aar", ".so", ".bin", ".gif"}
    for change in full_changes:
        path = str(change.get("path") or "").replace("\\", "/")
        if path in dirty_at_start and Path(path).suffix.lower() in binary_suffixes:
            raise ValidationError(
                f"HANDOFF_DIRTY_BASE_UNPROVABLE_BINARY: cannot safely attribute binary file '{path}' overlapping dirty baseline"
            )
    full_task_paths = sorted({c.get("path") for c in full_changes if c.get("path")})
    full_task_change_set_sha256 = full_manifest.get("task_change_set_sha256")
    delivery_snapshot_sha256 = full_manifest.get("delivery_snapshot_sha256")

    curr_manifest = build_manifest(repo)
    checkpoint_base = task_base
    accepted_head = plan.get("accepted_checkpoint_head")
    if accepted_head:
        receipt_file = checkpoints_dir(tdir) / f"{accepted_head}.json"
        valid_heads = resolve_valid_checkpoint_heads(repo, task_id, task_base_head)
        if accepted_head != current_head or accepted_head not in valid_heads:
            raise ValidationError("HANDOFF_CHECKPOINT_LINEAGE_INVALID: current HEAD is not the accepted checkpoint")
        ok, reason, receipt = validate_checkpoint_receipt(
            repo, task_id, task_base_head, receipt_file, valid_heads,
        )
        if not ok or not receipt or not isinstance(receipt.get("checkpoint_baseline_changes"), list):
            raise ValidationError(f"HANDOFF_CHECKPOINT_BASELINE_INVALID: {reason or 'accepted checkpoint baseline missing'}")
        checkpoint_base = {"changes": receipt["checkpoint_baseline_changes"], "task_base_head": current_head}
    checkpoint_manifest = build_task_manifest(
        repo, checkpoint_base, expected_files=expected_scope, task_base_head=current_head,
    )
    curr_changes = checkpoint_manifest.get("task_changes") or []
    checkpoint_paths = sorted({c.get("path") for c in curr_changes if c.get("path")})
    checkpoint_delta_sha256 = checkpoint_manifest.get("task_change_set_sha256")

    # Lightweight deterministic safety check before returning DEVELOPER_WIP_COMMIT_REQUIRED
    try:
        from fast_kt_lint import lint_file
        kt_issues = []
        for c in curr_changes:
            rel_p = c.get("path", "") if isinstance(c, dict) else str(c or "")
            p = repo / rel_p
            if p.suffix == ".kt" and p.is_file():
                kt_issues.extend(lint_file(p))
        if kt_issues:
            raise ValidationError(f"handoff Kotlin lint failed: {len(kt_issues)} issue(s) detected")
    except ValidationError:
        raise
    except Exception as exc:
        return {
            "code": "HANDOFF_ENV_BLOCKED",
            "kind": "DEVELOPER_ACTION",
            "command": "",
            "blocking": True,
            "reason": f"Environment blocked handoff safety preflight check: {exc}",
            "inputs": {"repo": ".", "task_id": task_id},
            "expected": {},
        }

    if curr_changes:
        try:
            from workflow import check_phase_compile, resolve_phase_modules
            modules = resolve_phase_modules(repo, checkpoint_manifest)
            if modules:
                compile_ok, compile_detail = check_phase_compile(repo, modules, phase_changes=curr_changes)
                if not compile_ok:
                    return {
                        "code": "HANDOFF_ENV_BLOCKED",
                        "kind": "DEVELOPER_ACTION",
                        "command": "",
                        "blocking": True,
                        "reason": f"Targeted handoff compile did not pass: {compile_detail}",
                        "inputs": {"repo": ".", "task_id": task_id, "modules": modules},
                        "expected": {},
                    }
        except Exception as exc:
            return {
                "code": "HANDOFF_ENV_BLOCKED",
                "kind": "DEVELOPER_ACTION",
                "command": "",
                "blocking": True,
                "reason": f"Environment blocked targeted handoff compile: {exc}",
                "inputs": {"repo": ".", "task_id": task_id},
                "expected": {},
            }

    pending_data = {
        "schema_version": 2,
        "task_id": task_id,
        "plan_sha256": plan.get("plan_sha256"),
        "task_base_head": task_base_head,
        "parent_head": current_head,
        "full_task_change_set_sha256": full_task_change_set_sha256,
        "full_task_paths": full_task_paths,
        "delivery_snapshot_sha256": delivery_snapshot_sha256,
        "checkpoint_delta_sha256": checkpoint_delta_sha256,
        "checkpoint_paths": checkpoint_paths,
        "expected_files": full_task_paths,
        "task_change_set_sha256": full_task_change_set_sha256,
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
            "expected_files": full_task_paths,
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
        raise ValidationError("TASK_HEAD_LINEAGE_RECONCILIATION_REQUIRED: merge commit detected during handoff lineage check")

    # Section 25: Check for exactly one commit
    count_proc = subprocess.run(
        ["git", "rev-list", "--count", f"{parent_head}..{current_head}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if count_proc.returncode != 0:
        raise ValidationError(f"cannot inspect lineage commit count between '{parent_head[:8]}' and '{current_head[:8]}'")
    commit_count = int(count_proc.stdout.strip() or "0")
    if commit_count != 1:
        raise ValidationError(
            f"HANDOFF_COMMIT_COUNT_MISMATCH: lineage check failed: expected exactly 1 developer checkpoint commit between {parent_head[:8]} and {current_head[:8]}, found {commit_count}"
        )

    committed_paths_proc = subprocess.run(
        ["git", "diff", "--name-only", "-z", parent_head, current_head],
        cwd=str(repo), capture_output=True, check=False,
    )
    if committed_paths_proc.returncode != 0:
        raise ValidationError("HANDOFF_COMMIT_SCOPE_UNVERIFIABLE: cannot inspect checkpoint commit paths")
    committed_paths = {
        path.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for path in committed_paths_proc.stdout.split(b"\0") if path
    }
    checkpoint_paths = set(pending.get("checkpoint_paths") or [])
    unexpected_paths = sorted(committed_paths - checkpoint_paths)
    if unexpected_paths:
        raise ValidationError(
            "HANDOFF_COMMIT_SCOPE_MISMATCH: checkpoint commit includes paths outside the task delta: "
            + ", ".join(unexpected_paths)
        )

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
        "schema_version": 2,
        "task_id": task_id,
        "plan_sha256": pending.get("plan_sha256"),
        "task_base_head": pending.get("task_base_head"),
        "parent_head": parent_head,
        "checkpoint_head": current_head,
        "delivery_snapshot_sha256": live_snapshot,
        "full_task_change_set_sha256": pending.get("full_task_change_set_sha256"),
        "full_task_paths": pending.get("full_task_paths"),
        "checkpoint_delta_sha256": pending.get("checkpoint_delta_sha256"),
        "checkpoint_paths": pending.get("checkpoint_paths"),
        "checkpoint_baseline_changes": manifest.get("changes") or [],
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
