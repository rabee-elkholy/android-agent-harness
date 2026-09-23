"""Selftest suite for Developer WIP Checkpoint & Urgent Worktree Handoff.

Covers:
- Section 29 Test Matrix (HANDOFF_001 through HANDOFF_024)
- Sections 12-18 of ANTIGRAVITY_FINAL_WORKFLOW_STABILITY_REPAIR_SPEC
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _vnext_common import (
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    git_text,
    read_json,
    utc_now,
)
from delivery_manifest import build_manifest, build_task_diff, build_task_manifest
from plan_authority import save_plan
import workflow
from workflow import (
    begin_task,
    checkpoint_phase,
    draft,
    prepare_verification,
    record_approval,
    resolve_next_action,
    state_root,
    task_dir,
)

try:
    import task_git_lineage
    from task_git_lineage import (
        create_pending_handoff,
        is_valid_task_lineage,
        reconcile_handoff,
    )
except ImportError:
    task_git_lineage = None


def run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr or proc.stdout}")
    return proc.stdout.strip()


def write_file(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def setup_ownership(repo: Path) -> None:
    manifest = {
        "schema_version": 1,
        "architecture_major": 1,
        "harness_version": "1.0.60",
        "installed_at": utc_now(),
        "install_backup": None,
        "latest_backup": None,
        "managed_exclude_block": {"begin": "# BEGIN", "end": "# END"},
        "entries": [],
    }
    manifest["ownership_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "ownership_sha256"})
    atomic_write_json(repo / ".agents" / "ownership.json", manifest)
    write_file(repo / ".harness-setup" / "answers.json", json.dumps({"confirm_installation": True, "target_branch": "main"}))


class WorktreeHandoffSelftest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="handoff_test_")
        self.repo = Path(self.temp.name).resolve()
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Handoff Test")
        run_git(self.repo, "config", "user.email", "handoff@example.invalid")
        setup_ownership(self.repo)

        # Initial commit
        write_file(self.repo / ".gitignore", ".agents/\n")
        write_file(self.repo / "settings.gradle.kts", "rootProject.name = 'sample'\ninclude(':app')\n")
        write_file(self.repo / "app" / "build.gradle.kts", "plugins { kotlin('jvm') }\n")
        write_file(self.repo / "README.md", "# Base Repo\n")
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "App.kt", "package com.example\nclass App\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "chore: initial commit")
        run_git(self.repo, "checkout", "-B", "main")

    def tearDown(self) -> None:
        try:
            self.temp.cleanup()
        except Exception:
            pass

    def _create_task(
        self,
        repo: Path | None = None,
        kind: str = "FEATURE",
        outcome: str = "Add feature",
        expected_files: list[str] | None = None,
    ) -> str:
        import uuid
        target_repo = repo or self.repo
        t_id = f"task-{uuid.uuid4().hex[:6]}"
        files = expected_files if expected_files is not None else [
            "app/src/main/java/com/example/Feature.kt",
            "app/src/main/java/com/example/Feature2.kt",
        ]
        d = draft(argparse.Namespace(
            repo=str(target_repo),
            task_id=t_id,
            outcome=outcome,
            kind=kind,
            prompt=outcome,
            task_file=None,
            expected_files=",".join(files),
        ))
        t_id = d["task_id"]
        record_approval(argparse.Namespace(
            repo=str(target_repo),
            task_id=t_id,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(target_repo), task_id=t_id))
        return t_id

    def test_HANDOFF_001_implementing_task_can_prepare_handoff_snapshot(self) -> None:
        """HANDOFF_001: IMPLEMENTING task can prepare a handoff snapshot."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        res = create_pending_handoff(self.repo, t_id)
        self.assertEqual("DEVELOPER_WIP_COMMIT_REQUIRED", res["code"])
        self.assertEqual("DEVELOPER_ACTION", res["kind"])
        self.assertEqual("", res["command"])

        pending_f = task_dir(self.repo, t_id) / "pending-handoff.json"
        self.assertTrue(pending_f.is_file())

    def test_HANDOFF_002_verifying_task_must_resume_before_handoff(self) -> None:
        """HANDOFF_002: VERIFYING task must resume before handoff."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=t_id, host="antigravity"))
        res = create_pending_handoff(self.repo, t_id)
        self.assertEqual("RESUME_IMPLEMENTATION", res["code"])

    def test_HANDOFF_003_ready_task_uses_final_commit_flow_not_wip_handoff(self) -> None:
        """HANDOFF_003: READY task uses final commit flow, not WIP handoff."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=t_id, host="antigravity"))
        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        plan["status"] = "READY_FOR_DELIVERY"
        save_plan(task_dir(self.repo, t_id) / "plan.json", plan)

        res = create_pending_handoff(self.repo, t_id)
        self.assertEqual("DEVELOPER_GIT_COMMIT_REQUIRED", res["code"])

    def test_HANDOFF_004_model_cannot_execute_git_commit(self) -> None:
        """HANDOFF_004: model cannot execute Git commit."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        res = create_pending_handoff(self.repo, t_id)
        self.assertEqual("", res.get("command", ""))
        self.assertEqual("DEVELOPER_ACTION", res["kind"])

    def test_HANDOFF_005_pending_handoff_records_parent_head_snapshot_task_delta(self) -> None:
        """HANDOFF_005: pending handoff records parent HEAD/snapshot/task delta."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        pending = read_json(task_dir(self.repo, t_id) / "pending-handoff.json")
        self.assertIn("parent_head", pending)
        self.assertIn("task_base_head", pending)
        self.assertIn("delivery_snapshot_sha256", pending)
        self.assertIn("task_change_set_sha256", pending)
        self.assertIn("expected_files", pending)

    def test_HANDOFF_006_valid_developer_wip_commit_reconciles_successfully(self) -> None:
        """HANDOFF_006: valid developer WIP commit reconciles successfully."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)

        # Developer commits the WIP changes
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")

        res = reconcile_handoff(self.repo, t_id)
        self.assertEqual("WORKTREE_SWITCH_READY", res["status"])
        receipt_f = task_dir(self.repo, t_id) / "git-checkpoints" / f"{res['checkpoint_head']}.json"
        self.assertTrue(receipt_f.is_file())
        self.assertFalse((task_dir(self.repo, t_id) / "pending-handoff.json").exists())

    def test_HANDOFF_007_accepted_checkpoint_does_not_invalidate_plan_approval(self) -> None:
        """HANDOFF_007: accepted checkpoint does not invalidate plan approval."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)

        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        self.assertEqual("IMPLEMENTING", plan["status"])
        self.assertEqual("RULE_ENFORCED", plan["approval"]["enforcement_tier"])

    def test_HANDOFF_008_accepted_checkpoint_head_is_allowed_by_prepare_verification(self) -> None:
        """HANDOFF_008: accepted checkpoint HEAD is allowed by prepare-verification."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)

        # Make another in-scope edit and verify prepare_verification succeeds
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature2.kt", "package com.example\nclass Feature2\n")
        res = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=t_id, host="antigravity"))
        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        self.assertEqual("VERIFYING", plan["status"])

    def test_HANDOFF_009_unknown_head_change_remains_blocked(self) -> None:
        """HANDOFF_009: unknown HEAD change remains blocked."""
        t_id = self._create_task()
        # Direct commit without handoff
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Rogue.kt", "package com.example\nclass Rogue\n")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "rogue commit")

        with self.assertRaises(ValidationError) as ctx:
            prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=t_id, host="antigravity"))
        self.assertIn("lineage", str(ctx.exception).lower())

    def test_HANDOFF_010_non_descendant_head_remains_blocked(self) -> None:
        """HANDOFF_010: non-descendant HEAD remains blocked."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        run_git(self.repo, "checkout", "-b", "other-branch")
        write_file(self.repo / "Other.kt", "class Other\n")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "divergent commit")

        with self.assertRaises(ValidationError) as ctx:
            reconcile_handoff(self.repo, t_id)
        self.assertTrue(
            "lineage" in str(ctx.exception).lower() or "descendant" in str(ctx.exception).lower() or "pending" in str(ctx.exception).lower()
        )

    def test_HANDOFF_011_rebase_merge_without_reconciliation_remains_blocked(self) -> None:
        """HANDOFF_011: rebase/merge without reconciliation remains blocked."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        run_git(self.repo, "checkout", "-b", "side")
        write_file(self.repo / "Side.kt", "class Side\n")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "side commit")
        run_git(self.repo, "checkout", "main")
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)

        # Merge side into main
        run_git(self.repo, "merge", "side", "--no-ff", "-m", "merge side")
        with self.assertRaises(ValidationError) as ctx:
            reconcile_handoff(self.repo, t_id)
        self.assertIn("lineage", str(ctx.exception).lower())

    def test_HANDOFF_012_commit_hook_content_mutation_is_rejected(self) -> None:
        """HANDOFF_012: commit hook content mutation is rejected."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)

        # Simulate hook mutating file during commit
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass FeatureHookModified\n")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: commit with hook change")

        with self.assertRaises(ValidationError) as ctx:
            reconcile_handoff(self.repo, t_id)
        self.assertIn("changed", str(ctx.exception).lower())

    def test_HANDOFF_013_full_task_manifest_still_includes_code_committed_in_wip_checkpoint(self) -> None:
        """HANDOFF_013: full task manifest still includes code committed in WIP checkpoint."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)

        # Working tree is clean now!
        man = build_task_manifest(self.repo, task_base_head=run_git(self.repo, "rev-parse", "HEAD~1"))
        changed_paths = [c.get("path") for c in man.get("task_changes", [])]
        self.assertTrue(any("Feature.kt" in p for p in changed_paths if p))

    def test_HANDOFF_014_final_task_diff_still_includes_committed_wip_code(self) -> None:
        """HANDOFF_014: final task diff still includes committed WIP code."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)

        # Working tree is clean, but task diff against task_base_head must still contain Feature.kt!
        base_head = run_git(self.repo, "rev-parse", "HEAD~1")
        man = build_task_manifest(self.repo, task_base_head=base_head)
        diff = build_task_diff(self.repo, t_id, man)
        self.assertIn("Feature.kt", diff)

    def test_HANDOFF_015_phase_delta_still_includes_relevant_committed_code(self) -> None:
        """HANDOFF_015: phase delta still includes relevant committed code."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        from phase_review import _compute_phase_diff
        t_id = self._create_task()
        base_head = run_git(self.repo, "rev-parse", "HEAD")
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)

        diff = _compute_phase_diff(self.repo, ["app/src/main/java/com/example/Feature.kt"], base_ref=base_head)
        self.assertIn("Feature.kt", diff)

    def test_HANDOFF_016_pre_existing_unrelated_dirty_baseline_remains_excluded(self) -> None:
        """HANDOFF_016: pre-existing unrelated dirty baseline remains excluded."""
        # Start task with pre-existing dirty file
        write_file(self.repo / "dirty.txt", "unrelated dirty\n")
        base_man = build_manifest(self.repo)

        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        man = build_task_manifest(self.repo, baseline=base_man, expected_files=["app/src/main/java/com/example/Feature.kt"])
        paths = [c.get("path") for c in man.get("task_changes", [])]
        self.assertTrue(any("Feature.kt" in p for p in paths if p))
        self.assertFalse(any("dirty.txt" in p for p in paths if p))

    def test_HANDOFF_017_unprovable_overlapping_dirty_baseline_fails_closed(self) -> None:
        """HANDOFF_017: unprovable overlapping dirty baseline fails closed."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        # Pre-existing secret dirty file
        write_file(self.repo / "secret.env", "KEY=123\n")
        t_id = self._create_task()
        # Modifying secret file as part of task is unsafe for WIP handoff
        write_file(self.repo / "secret.env", "KEY=456\n")

        with self.assertRaises(ValidationError) as ctx:
            create_pending_handoff(self.repo, t_id)
        self.assertIn("dirty", str(ctx.exception).lower())

    def test_HANDOFF_018_original_worktree_keeps_task_a_live(self) -> None:
        """HANDOFF_018: original worktree keeps Task A live."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)

        active = read_json(state_root(self.repo) / "active-task.json")
        self.assertEqual(t_id, active.get("task_id"))

    def test_HANDOFF_019_second_worktree_can_initialize_independent_task_b_state(self) -> None:
        """HANDOFF_019: second worktree can initialize independent Task B state."""
        t_id_a = self._create_task(outcome="Task A")
        # Setup second worktree
        worktree_b = Path(tempfile.mkdtemp(prefix="worktree_b_")).resolve()
        try:
            run_git(self.repo, "worktree", "add", str(worktree_b), "HEAD")
            setup_ownership(worktree_b)
            t_id_b = self._create_task(repo=worktree_b, outcome="Task B")
            self.assertNotEqual(t_id_a, t_id_b)
            self.assertTrue((task_dir(worktree_b, t_id_b) / "plan.json").is_file())
        finally:
            try:
                run_git(self.repo, "worktree", "remove", "--force", str(worktree_b))
            except Exception:
                pass
            shutil.rmtree(str(worktree_b), ignore_errors=True)

    def test_HANDOFF_020_task_b_active_state_does_not_alter_task_a_active_state(self) -> None:
        """HANDOFF_020: Task B active state does not alter Task A active state."""
        t_id_a = self._create_task(outcome="Task A")
        worktree_b = Path(tempfile.mkdtemp(prefix="worktree_b_")).resolve()
        try:
            run_git(self.repo, "worktree", "add", str(worktree_b), "HEAD")
            setup_ownership(worktree_b)
            t_id_b = self._create_task(repo=worktree_b, outcome="Task B")

            active_a = read_json(state_root(self.repo) / "active-task.json")
            active_b = read_json(state_root(worktree_b) / "active-task.json")
            self.assertEqual(t_id_a, active_a.get("task_id"))
            self.assertEqual(t_id_b, active_b.get("task_id"))
        finally:
            try:
                run_git(self.repo, "worktree", "remove", "--force", str(worktree_b))
            except Exception:
                pass
            shutil.rmtree(str(worktree_b), ignore_errors=True)

    def test_HANDOFF_021_returning_to_original_worktree_returns_task_a_next_action(self) -> None:
        """HANDOFF_021: returning to original worktree returns Task A next action."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)

        act = resolve_next_action(self.repo, t_id)
        self.assertIn("code", act)
        self.assertEqual("IMPLEMENT_APPROVED_SCOPE", act["code"])

    def test_HANDOFF_022_no_repeat_approval_after_safe_return(self) -> None:
        """HANDOFF_022: no repeat approval after safe return."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)

        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        self.assertEqual("IMPLEMENTING", plan["status"])
        self.assertNotIn("APPROVAL_REQUIRED", [resolve_next_action(self.repo, t_id)["code"]])

    def test_HANDOFF_023_arbitrary_urgent_branch_merge_returns_lineage_reconciliation_required(self) -> None:
        """HANDOFF_023: arbitrary urgent branch merge into Task A returns lineage reconciliation required."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        run_git(self.repo, "checkout", "-b", "urgent")
        write_file(self.repo / "Urgent.kt", "class Urgent\n")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "urgent commit")
        run_git(self.repo, "checkout", "main")
        run_git(self.repo, "merge", "urgent", "--no-ff", "-m", "merge urgent")

        valid, reason = is_valid_task_lineage(self.repo, t_id, run_git(self.repo, "rev-parse", "HEAD"))
        self.assertFalse(valid)
        self.assertIn("lineage", reason.lower())

    def test_HANDOFF_024_handoff_receipts_have_integrity_hashes_and_identity_validation(self) -> None:
        """HANDOFF_024: handoff receipts have integrity hashes and identity validation."""
        if task_git_lineage is None:
            self.fail("task_git_lineage module not yet implemented")
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        res = reconcile_handoff(self.repo, t_id)

        r_path = task_dir(self.repo, t_id) / "git-checkpoints" / f"{res['checkpoint_head']}.json"
        self.assertTrue(r_path.is_file())
        receipt = read_json(r_path)
        self.assertIn("receipt_sha256", receipt)
        self.assertIn("plan_sha256", receipt)
        self.assertIn("parent_head", receipt)
        self.assertIn("checkpoint_head", receipt)
        self.assertIn("task_base_head", receipt)

    def test_HANDOFF_IDENTITY_001_committed_and_dirty_identities_consistent(self) -> None:
        """HANDOFF_IDENTITY_001: moving same content from dirty tree to accepted commit uses consistent git:<oid> identity format."""
        t_id = self._create_task()
        target_path = self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt"
        write_file(target_path, "package com.example\nclass Feature\n")
        
        m_dirty = build_task_manifest(self.repo, t_id)
        dirty_change = next(c for c in m_dirty["task_changes"] if c["path"] == "app/src/main/java/com/example/Feature.kt")
        self.assertTrue(dirty_change["content_identity"].startswith("git:"))
        
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)
        
        m_committed = build_task_manifest(self.repo, t_id)
        comm_change = next(c for c in m_committed["task_changes"] if c["path"] == "app/src/main/java/com/example/Feature.kt")
        self.assertTrue(comm_change["content_identity"].startswith("git:"))
        self.assertEqual(dirty_change["content_identity"], comm_change["content_identity"])

    def test_HANDOFF_DIRTY_BASE_001_dirty_text_plus_task_edit_plus_checkpoint_remains_in_final_manifest(self) -> None:
        """HANDOFF_DIRTY_BASE_001: pre-existing dirty tracked text file + task edit + checkpoint remains in final manifest."""
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "App.kt", "package com.example\n// dirty before task\nclass App\n")
        t_id = self._create_task(expected_files=["app/src/main/java/com/example/App.kt"])
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "App.kt", "package com.example\n// dirty before task\n// task A edit\nclass App\n")
        
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)
        
        m = build_task_manifest(self.repo, t_id)
        app_changes = [c for c in m["task_changes"] if c["path"] == "app/src/main/java/com/example/App.kt"]
        self.assertEqual(1, len(app_changes))

    def test_HANDOFF_DIRTY_BASE_002_final_diff_shows_baseline_to_task_delta_only(self) -> None:
        """HANDOFF_DIRTY_BASE_002: final diff shows baseline->task delta only (pre-task dirty delta excluded)."""
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "App.kt", "package com.example\n// PRE_TASK_DIRTY_CONTENT\nclass App\n")
        t_id = self._create_task(expected_files=["app/src/main/java/com/example/App.kt"])
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "App.kt", "package com.example\n// PRE_TASK_DIRTY_CONTENT\n// TASK_A_EDIT_CONTENT\nclass App\n")
        
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)
        
        m = build_task_manifest(self.repo, t_id)
        diff = build_task_diff(self.repo, m, task_id=t_id)
        self.assertIn("TASK_A_EDIT_CONTENT", diff)
        self.assertNotIn("+// PRE_TASK_DIRTY_CONTENT", diff)

    def test_HANDOFF_DIRTY_BASE_003_unprovable_binary_overlap_fails_closed(self) -> None:
        """HANDOFF_DIRTY_BASE_003: unprovable binary overlap fails closed."""
        write_file(self.repo / "app" / "sample.bin", b"\x00\x01\x02")
        run_git(self.repo, "add", "app/sample.bin")
        run_git(self.repo, "commit", "-m", "chore: add binary")
        write_file(self.repo / "app" / "sample.bin", b"\x00\x01\x02\x03_dirty")
        
        t_id = self._create_task(expected_files=["app/sample.bin"])
        write_file(self.repo / "app" / "sample.bin", b"\x00\x01\x02\x03_task_a")
        
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)
        
        with self.assertRaises(ValidationError) as ctx:
            build_task_manifest(self.repo, t_id)
        self.assertIn("HANDOFF_DIRTY_BASE_UNPROVABLE_BINARY", str(ctx.exception))

    def test_HANDOFF_DIRTY_BASE_004_secret_overlap_fails_closed(self) -> None:
        """HANDOFF_DIRTY_BASE_004: secret overlap fails closed."""
        write_file(self.repo / "app" / "credentials.txt", "API_KEY=dirty_before_task\n")
        run_git(self.repo, "add", "app/credentials.txt")
        run_git(self.repo, "commit", "-m", "chore: add creds")
        write_file(self.repo / "app" / "credentials.txt", "API_KEY=dirty_modified\n")
        
        t_id = self._create_task(expected_files=["app/credentials.txt"])
        write_file(self.repo / "app" / "credentials.txt", "API_KEY=dirty_modified_by_task\n")
        
        with self.assertRaises(ValidationError) as ctx:
            create_pending_handoff(self.repo, t_id)
        self.assertIn("HANDOFF_COMMIT_UNSAFE_DIRTY_BASELINE", str(ctx.exception))

    def test_HANDOFF_DIRTY_BASE_005_unrelated_pre_existing_dirty_path_stays_excluded(self) -> None:
        """HANDOFF_DIRTY_BASE_005: unrelated pre-existing dirty path stays excluded."""
        write_file(self.repo / "unrelated.txt", "unrelated dirty\n")
        
        t_id = self._create_task(expected_files=["app/src/main/java/com/example/Feature.kt"])
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "class Feature\n")
        
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", "app/src/main/java/com/example/Feature.kt")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        reconcile_handoff(self.repo, t_id)
        
        m = build_task_manifest(self.repo, t_id)
        paths = [c["path"] for c in m["task_changes"]]
        self.assertIn("app/src/main/java/com/example/Feature.kt", paths)
        self.assertNotIn("unrelated.txt", paths)

    def test_LINEAGE_RECEIPT_001_valid_receipt_chain_accepted(self) -> None:
        """LINEAGE_RECEIPT_001: valid receipt chain accepted."""
        from task_git_lineage import validate_checkpoint_receipt
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "class Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        res = reconcile_handoff(self.repo, t_id)
        head = res["checkpoint_head"]
        r_path = task_dir(self.repo, t_id) / "git-checkpoints" / f"{head}.json"
        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        base_head = plan.get("task_base_head")
        
        ok, err, receipt = validate_checkpoint_receipt(self.repo, t_id, base_head, r_path, set())
        self.assertTrue(ok, err)
        self.assertIsNotNone(receipt)

    def test_LINEAGE_RECEIPT_002_plan_only_head_rejected(self) -> None:
        """LINEAGE_RECEIPT_002: plan-only head with missing receipt file rejected."""
        from task_git_lineage import is_valid_task_lineage
        t_id = self._create_task()
        plan_f = task_dir(self.repo, t_id) / "plan.json"
        plan = read_json(plan_f)
        fake_head = "a" * 40
        plan["accepted_checkpoint_heads"] = [fake_head]
        save_plan(plan_f, plan)
        
        valid, reason = is_valid_task_lineage(self.repo, t_id, fake_head)
        self.assertFalse(valid)
        self.assertTrue("lineage" in reason.lower() or "receipt" in reason.lower())

    def test_LINEAGE_RECEIPT_003_wrong_task_rejected(self) -> None:
        """LINEAGE_RECEIPT_003: wrong task ID in receipt rejected."""
        from task_git_lineage import validate_checkpoint_receipt
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "class Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        res = reconcile_handoff(self.repo, t_id)
        head = res["checkpoint_head"]
        r_path = task_dir(self.repo, t_id) / "git-checkpoints" / f"{head}.json"
        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        base_head = plan.get("task_base_head")
        
        ok, err, _ = validate_checkpoint_receipt(self.repo, "other-task", base_head, r_path, set())
        self.assertFalse(ok)
        self.assertIn("task_id", err)

    def test_LINEAGE_RECEIPT_004_wrong_base_rejected(self) -> None:
        """LINEAGE_RECEIPT_004: wrong base HEAD in receipt rejected."""
        from task_git_lineage import validate_checkpoint_receipt
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "class Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        res = reconcile_handoff(self.repo, t_id)
        head = res["checkpoint_head"]
        r_path = task_dir(self.repo, t_id) / "git-checkpoints" / f"{head}.json"
        
        ok, err, _ = validate_checkpoint_receipt(self.repo, t_id, "b" * 40, r_path, set())
        self.assertFalse(ok)
        self.assertIn("task_base_head", err)

    def test_LINEAGE_RECEIPT_005_filename_head_mismatch_rejected(self) -> None:
        """LINEAGE_RECEIPT_005: filename and checkpoint_head mismatch rejected."""
        from task_git_lineage import validate_checkpoint_receipt
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "class Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        res = reconcile_handoff(self.repo, t_id)
        head = res["checkpoint_head"]
        r_path = task_dir(self.repo, t_id) / "git-checkpoints" / f"{head}.json"
        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        base_head = plan.get("task_base_head")
        
        mismatch_path = task_dir(self.repo, t_id) / "git-checkpoints" / f"{'c'*40}.json"
        r_path.rename(mismatch_path)
        
        ok, err, _ = validate_checkpoint_receipt(self.repo, t_id, base_head, mismatch_path, set())
        self.assertFalse(ok)
        self.assertIn("mismatch", err)

    def test_LINEAGE_RECEIPT_006_broken_parent_chain_rejected(self) -> None:
        """LINEAGE_RECEIPT_006: broken parent chain rejected."""
        from task_git_lineage import compute_receipt_sha, validate_checkpoint_receipt
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "class Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        res = reconcile_handoff(self.repo, t_id)
        head = res["checkpoint_head"]
        r_path = task_dir(self.repo, t_id) / "git-checkpoints" / f"{head}.json"
        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        base_head = plan.get("task_base_head")
        
        receipt = read_json(r_path)
        receipt["parent_head"] = "d" * 40
        receipt["receipt_sha256"] = compute_receipt_sha(receipt)
        atomic_write_json(r_path, receipt)
        
        ok, err, _ = validate_checkpoint_receipt(self.repo, t_id, base_head, r_path, set())
        self.assertFalse(ok)
        self.assertIn("parent_head", err)

    def test_LINEAGE_RECEIPT_007_bad_integrity_rejected(self) -> None:
        """LINEAGE_RECEIPT_007: bad receipt integrity hash rejected."""
        from task_git_lineage import validate_checkpoint_receipt
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "class Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint")
        res = reconcile_handoff(self.repo, t_id)
        head = res["checkpoint_head"]
        r_path = task_dir(self.repo, t_id) / "git-checkpoints" / f"{head}.json"
        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        base_head = plan.get("task_base_head")
        
        receipt = read_json(r_path)
        receipt["tampered"] = True
        atomic_write_json(r_path, receipt)
        
        ok, err, _ = validate_checkpoint_receipt(self.repo, t_id, base_head, r_path, set())
        self.assertFalse(ok)
        self.assertIn("checksum", err)

    def test_LINEAGE_RECEIPT_008_valid_second_checkpoint_accepted(self) -> None:
        """LINEAGE_RECEIPT_008: valid second checkpoint receipt accepted in chain."""
        from task_git_lineage import validate_checkpoint_receipt
        t_id = self._create_task()
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "class Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint 1")
        res1 = reconcile_handoff(self.repo, t_id)
        head1 = res1["checkpoint_head"]
        
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature2.kt", "class Feature2\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint 2")
        res2 = reconcile_handoff(self.repo, t_id)
        head2 = res2["checkpoint_head"]
        
        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        base_head = plan.get("task_base_head")
        r_path2 = task_dir(self.repo, t_id) / "git-checkpoints" / f"{head2}.json"
        
        ok, err, _ = validate_checkpoint_receipt(self.repo, t_id, base_head, r_path2, {head1})
        self.assertTrue(ok, err)

    def test_HANDOFF_ATTRIBUTION_E2E_001(self) -> None:
        """HANDOFF_ATTRIBUTION_E2E_001: complete worktree dirty baseline handoff E2E."""
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "App.kt", "package com.example\n// dirty before task\nclass App\n")
        
        t_id = self._create_task(expected_files=[
            "app/src/main/java/com/example/App.kt",
            "app/src/main/java/com/example/Feature.kt",
        ])
        
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "App.kt", "package com.example\n// dirty before task\n// task edit\nclass App\n")
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        
        h_res = create_pending_handoff(self.repo, t_id)
        self.assertEqual("DEVELOPER_WIP_COMMIT_REQUIRED", h_res["code"])
        
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint 1")
        
        rec_res = reconcile_handoff(self.repo, t_id)
        self.assertEqual("WORKTREE_SWITCH_READY", rec_res["status"])
        
        status_out = run_git(self.repo, "status", "--porcelain")
        self.assertEqual("", status_out)
        
        m = build_task_manifest(self.repo, t_id)
        task_paths = {c["path"] for c in m["task_changes"]}
        
        self.assertIn("app/src/main/java/com/example/App.kt", task_paths)
        self.assertIn("app/src/main/java/com/example/Feature.kt", task_paths)
        
        diff = build_task_diff(self.repo, m, task_id=t_id)
        self.assertIn("task edit", diff)
        self.assertNotIn("+// dirty before task", diff)
        
        res_prep = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=t_id, host="antigravity"))
        self.assertIn("run_id", res_prep)
        self.assertEqual("VERIFYING", read_json(task_dir(self.repo, t_id) / "plan.json").get("status"))

    def test_HANDOFF_SECOND_CHECKPOINT_001(self) -> None:
        """HANDOFF_SECOND_CHECKPOINT_001: two sequential handoffs retain full final delta."""
        t_id = self._create_task(expected_files=[
            "app/src/main/java/com/example/Feature.kt",
            "app/src/main/java/com/example/Feature2.kt",
        ])
        
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature.kt", "package com.example\nclass Feature\n")
        create_pending_handoff(self.repo, t_id)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint 1")
        reconcile_handoff(self.repo, t_id)
        
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Feature2.kt", "package com.example\nclass Feature2\n")
        
        h2 = create_pending_handoff(self.repo, t_id)
        self.assertEqual("DEVELOPER_WIP_COMMIT_REQUIRED", h2["code"])
        
        pending = read_json(task_dir(self.repo, t_id) / "pending-handoff.json")
        self.assertIn("full_task_change_set_sha256", pending)
        self.assertIn("checkpoint_delta_sha256", pending)
        self.assertIn("full_task_paths", pending)
        self.assertIn("checkpoint_paths", pending)
        self.assertIn("app/src/main/java/com/example/Feature.kt", pending["full_task_paths"])
        self.assertIn("app/src/main/java/com/example/Feature2.kt", pending["full_task_paths"])
        self.assertIn("app/src/main/java/com/example/Feature2.kt", pending["checkpoint_paths"])
        
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-m", "wip: checkpoint 2")
        rec2 = reconcile_handoff(self.repo, t_id)
        self.assertEqual("WORKTREE_SWITCH_READY", rec2["status"])
        
        plan = read_json(task_dir(self.repo, t_id) / "plan.json")
        self.assertEqual(2, len(plan.get("accepted_checkpoint_heads", [])))
        
        m = build_task_manifest(self.repo, t_id)
        diff = build_task_diff(self.repo, m, task_id=t_id)
        self.assertIn("Feature", diff)
        self.assertIn("Feature2", diff)


if __name__ == "__main__":
    unittest.main()
