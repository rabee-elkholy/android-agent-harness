"""Contracts for disjoint tasks sharing one developer-owned working tree."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from _vnext_common import ValidationError, atomic_write_json, read_json
from _worktree_handoff_selftest import run_git, setup_ownership, write_file
from delivery_manifest import build_task_manifest
from evidence_store import EvidenceStore
from mutation_guard import file_mutation_allowed
import workflow


class TaskIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Isolation Test")
        run_git(self.repo, "config", "user.email", "test@example.invalid")
        setup_ownership(self.repo)
        write_file(self.repo / ".agents/VERSION", (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8"))
        (self.repo / "app").mkdir()
        write_file(self.repo / ".gitignore", ".agents/\n.harness-setup/\n")
        for name in ("A.md", "B.md", "C.md"):
            write_file(self.repo / name, "original\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-qm", "Initial fixture")

    def draft(self, task, files):
        return workflow.draft(workflow.build_parser().parse_args([
            "draft", "--repo", str(self.repo), "--task-id", task,
            "--outcome", "Update documentation", "--expected-files", files,
            "--expected-surfaces", "DOCS",
        ]))

    def approve(self, task):
        return workflow.record_approval(argparse.Namespace(
            repo=str(self.repo), task_id=task, source="conversation",
            proof_reference="Approved fixture", enforcement_tier="RULE_ENFORCED",
        ))

    def ready(self, task):
        """Exercise the public docs-only verifier with a bound preflight fixture."""
        current = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task, force=False))
        EvidenceStore(workflow.state_root(self.repo)).write(
            snapshot=current["delivery_snapshot_sha256"], run_id=current["run_id"],
            name="preflight", producer="preflight_check", harness_version=current["harness_version"],
            change_set=current["change_set_sha256"], status="PASS", evidence={},
        )
        return workflow.complete(argparse.Namespace(repo=str(self.repo), task_id=task))

    def test_draft_approve_switch_and_isolated_delta(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        write_file(self.repo / "A.md", "alpha changes\n")
        self.draft("beta", "B.md")
        self.approve("beta")
        write_file(self.repo / "B.md", "beta changes\n")
        for task, file in (("alpha", "A.md"), ("beta", "B.md")):
            result = workflow.recover_active(argparse.Namespace(repo=str(self.repo), task_id=task))
            self.assertEqual(task, result["task_id"])
            self.assertEqual(task, workflow.status(argparse.Namespace(repo=str(self.repo), task_id=""))["task_id"])
            self.assertEqual([file], [c["path"] for c in build_task_manifest(self.repo, task)["task_changes"]])
        allowed, _, _ = file_mutation_allowed(self.repo, ["B.md"])
        self.assertTrue(allowed)
        allowed, _, _ = file_mutation_allowed(self.repo, ["A.md"])
        self.assertFalse(allowed)

    def test_overlapping_draft_keeps_existing_focus_and_plan(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        with self.assertRaisesRegex(ValidationError, "ACTIVE_TASK_CONFLICT"):
            self.draft("beta", "A.md")
        self.assertFalse((workflow.task_dir(self.repo, "beta") / "plan.json").exists())
        self.assertEqual("alpha", read_json(workflow.state_root(self.repo) / "active-task.json")["task_id"])

    def test_missing_focus_requires_explicit_task(self):
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        (workflow.state_root(self.repo) / "active-task.json").unlink()
        with self.assertRaisesRegex(ValidationError, "AMBIGUOUS"):
            workflow.status(argparse.Namespace(repo=str(self.repo), task_id=""))

    def test_pending_approval_tolerates_only_sibling_edits(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        self.draft("beta", "B.md")
        write_file(self.repo / "A.md", "concurrent alpha edit\n")
        self.approve("beta")

    def test_pending_approval_rejects_own_edits(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        self.draft("beta", "B.md")
        write_file(self.repo / "B.md", "unapproved beta edit\n")
        with self.assertRaises(ValidationError):
            self.approve("beta")

    def test_three_tasks_allowed_fourth_blocked_until_cancellation(self):
        for task, file in (("alpha", "A.md"), ("beta", "B.md"), ("gamma", "C.md")):
            self.draft(task, file)
            self.approve(task)
        with self.assertRaisesRegex(ValidationError, "LIVE_TASK_LIMIT_REACHED"):
            self.draft("delta", "D.md")
        self.assertEqual("gamma", read_json(workflow.state_root(self.repo) / "active-task.json")["task_id"])
        workflow.cancel(argparse.Namespace(repo=str(self.repo), task_id="beta"))
        self.draft("delta", "D.md")

    def test_partial_delivery_and_verified_sibling_lineage(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        write_file(self.repo / "A.md", "alpha change\n")
        alpha = self.ready("alpha")
        self.draft("beta", "B.md")
        self.approve("beta")
        write_file(self.repo / "B.md", "beta change\n")
        action = workflow.resolve_next_action(self.repo, "alpha", alpha)
        self.assertEqual("DEVELOPER_GIT_COMMIT_REQUIRED", action["code"])
        run_git(self.repo, "add", "A.md")
        run_git(self.repo, "commit", "-qm", "Deliver alpha only")
        delivered, status = workflow.reconcile_delivery(self.repo, "alpha")
        self.assertEqual("DELIVERED", status)
        self.assertEqual("IMPLEMENTING", read_json(workflow.task_dir(self.repo, "beta") / "plan.json")["status"])
        self.assertIn("B.md", run_git(self.repo, "status", "--short"))
        current = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="beta", force=False))
        frozen = read_json(Path(current["manifest"]))
        self.assertEqual(["B.md"], [c["path"] for c in frozen["task_changes"]])

    def test_sibling_edit_invalidates_frozen_verification(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        self.draft("beta", "B.md")
        self.approve("beta")
        write_file(self.repo / "B.md", "beta change\n")
        workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="beta", force=False))
        write_file(self.repo / "A.md", "alpha changed during verification\n")
        self.assertFalse(workflow.verification_freshness(self.repo, "beta")["fresh"])

    def test_declared_sibling_files_do_not_authorize_unverified_commit(self):
        from task_git_lineage import is_valid_task_lineage
        self.draft("alpha", "A.md")
        self.approve("alpha")
        self.draft("beta", "B.md")
        self.approve("beta")
        write_file(self.repo / "B.md", "unverified change\n")
        run_git(self.repo, "add", "B.md")
        run_git(self.repo, "commit", "-qm", "Unverified sibling commit")
        self.assertFalse(is_valid_task_lineage(self.repo, "alpha", run_git(self.repo, "rev-parse", "HEAD"))[0])

    def test_pending_task_can_begin_after_verified_sibling_commit(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        write_file(self.repo / "A.md", "alpha change\n")
        self.ready("alpha")
        self.draft("beta", "B.md")
        run_git(self.repo, "add", "A.md")
        run_git(self.repo, "commit", "-qm", "Deliver alpha")
        workflow.reconcile_delivery(self.repo, "alpha")
        self.assertEqual("IMPLEMENTING", self.approve("beta")["status"])

    def test_three_ready_tasks_deliver_independently_in_reverse_order(self):
        for task, file in (("alpha", "A.md"), ("beta", "B.md"), ("gamma", "C.md")):
            self.draft(task, file)
            self.approve(task)
            write_file(self.repo / file, task + " change\n")
            self.ready(task)
        with self.assertRaisesRegex(ValidationError, "LIVE_TASK_LIMIT_REACHED"):
            self.draft("delta", "D.md")
        for task, file in (("gamma", "C.md"), ("beta", "B.md"), ("alpha", "A.md")):
            run_git(self.repo, "add", file)
            run_git(self.repo, "commit", "-qm", "Deliver " + task)
            self.assertEqual("DELIVERED", workflow.reconcile_delivery(self.repo, task)[1])

    def test_overlapping_revision_preserves_approval_and_focus(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        self.draft("beta", "B.md")
        beta = self.approve("beta")
        with self.assertRaisesRegex(ValidationError, "ACTIVE_TASK_CONFLICT"):
            workflow.revise(workflow.build_parser().parse_args([
                "revise", "--repo", str(self.repo), "--task-id", "beta", "--expected-files", "A.md,B.md",
            ]))
        self.assertEqual(beta, read_json(workflow.task_dir(self.repo, "beta") / "plan.json"))
        self.assertEqual("beta", read_json(workflow.state_root(self.repo) / "active-task.json")["task_id"])

    def test_verified_sibling_path_with_different_committed_content_is_rejected(self):
        from task_git_lineage import is_valid_task_lineage
        self.draft("alpha", "A.md")
        self.approve("alpha")
        self.draft("beta", "B.md")
        self.approve("beta")
        write_file(self.repo / "B.md", "verified beta\n")
        self.ready("beta")
        write_file(self.repo / "B.md", "unverified beta\n")
        run_git(self.repo, "add", "B.md")
        run_git(self.repo, "commit", "-qm", "Different beta content")
        self.assertFalse(is_valid_task_lineage(self.repo, "alpha", run_git(self.repo, "rev-parse", "HEAD"))[0])

    def test_concurrent_drafts_cannot_exceed_three_slots(self):
        candidates = (("alpha", "A.md"), ("beta", "B.md"), ("gamma", "C.md"), ("delta", "D.md"))
        processes = [subprocess.Popen([
            sys.executable, str(Path(workflow.__file__).resolve()), "draft", "--repo", str(self.repo),
            "--task-id", task, "--outcome", "Update documentation", "--expected-surfaces", "DOCS",
            "--expected-files", file, "--json",
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for task, file in candidates]
        outputs = [process.communicate(timeout=60) for process in processes]
        admitted = {task for (task, _), process in zip(candidates, processes) if process.returncode == 0}
        self.assertGreaterEqual(len(admitted), 1, outputs)
        self.assertLessEqual(len(admitted), 3, outputs)
        self.assertEqual(admitted, {task for task, _, _ in workflow.live_task_plans(self.repo)})
        rejected = [i for i, process in enumerate(processes) if process.returncode != 0]
        for index in rejected:
            response = b"".join(outputs[index])
            allowed = [b"state lock is owned by a live process"]
            if len(admitted) == 3:
                allowed.append(b"LIVE_TASK_LIMIT_REACHED")
            self.assertTrue(any(reason in response for reason in allowed), response)
        # The bounded state lock may reject several contenders under parallel-suite load.
        # After all writers exit, make one fresh attempt per rejected request: fill any
        # remaining slots, then require the real admission limit without a retry loop.
        from delivery_manifest import TaskConflictError
        for index in rejected:
            if len(admitted) < 3:
                self.draft(*candidates[index])
                admitted.add(candidates[index][0])
            else:
                with self.assertRaises(TaskConflictError) as caught:
                    self.draft(*candidates[index])
                self.assertEqual("LIVE_TASK_LIMIT_REACHED", caught.exception.details["code"])
        self.assertEqual(admitted, {task for task, _, _ in workflow.live_task_plans(self.repo)})
        self.assertEqual(3, len(workflow.live_task_plans(self.repo)))

    def test_public_switch_preserves_pending_status(self):
        pending = self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        self.assertEqual(0, workflow.main(["switch", "--repo", str(self.repo), "--task-id", "alpha", "--json"]))
        self.assertEqual(pending, read_json(workflow.task_dir(self.repo, "alpha") / "plan.json"))
        self.assertFalse(file_mutation_allowed(self.repo, ["A.md"])[0])

    def test_cross_task_rename_is_rejected_from_both_deltas(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        self.draft("beta", "renamed.md")
        self.approve("beta")
        run_git(self.repo, "mv", "A.md", "renamed.md")
        for task in ("alpha", "beta"):
            with self.assertRaisesRegex(ValidationError, "ACTIVE_TASK_CONFLICT"):
                build_task_manifest(self.repo, task)

    def test_own_rename_and_sibling_deletion_deliver_separately(self):
        self.draft("alpha", "A.md,renamed.md")
        self.approve("alpha")
        self.draft("beta", "B.md")
        self.approve("beta")
        run_git(self.repo, "mv", "A.md", "renamed.md")
        self.ready("alpha")
        (self.repo / "B.md").unlink()
        self.ready("beta")
        run_git(self.repo, "add", "B.md")
        run_git(self.repo, "commit", "-qm", "Delete beta file", "--only", "--", "B.md")
        self.assertEqual("DELIVERED", workflow.reconcile_delivery(self.repo, "beta")[1])
        run_git(self.repo, "commit", "-qm", "Rename alpha file")
        self.assertEqual("DELIVERED", workflow.reconcile_delivery(self.repo, "alpha")[1])

    def test_external_build_input_drift_routes_to_executable_resume(self):
        write_file(self.repo / ".git/info/exclude", "local.properties\n")
        write_file(self.repo / "local.properties", "sdk.dir=/initial/sdk\n")
        self.draft("alpha", "A.md")
        self.approve("alpha")
        write_file(self.repo / "A.md", "alpha change\n")
        ready = self.ready("alpha")
        write_file(self.repo / "local.properties", "sdk.dir=/different/sdk\n")
        self.assertEqual("DELIVERY_STALE_AFTER_COMMIT", workflow.resolve_next_action(self.repo, "alpha", ready)["code"])
        resumed = workflow.resume(argparse.Namespace(repo=str(self.repo), task_id="alpha", reopen=False))
        self.assertEqual("IMPLEMENTING", resumed["status"])

    def test_sibling_lifecycle_preserves_pending_cancel_request(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        marker = workflow.state_root(self.repo) / "cancel-requested.json"
        request = {"task_id": "alpha", "requested_at": 1}
        atomic_write_json(marker, request)
        self.draft("beta", "B.md")
        self.approve("beta")
        workflow.cancel(argparse.Namespace(repo=str(self.repo), task_id="beta"))
        self.assertEqual(request, read_json(marker))
        workflow.cancel(argparse.Namespace(repo=str(self.repo), task_id="alpha"))
        self.assertFalse(marker.exists())

    def test_overlap_json_offers_choices_without_changing_tasks(self):
        alpha = self.draft("alpha", "A.md")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = workflow.main(["draft", "--repo", str(self.repo), "--task-id", "beta",
                                  "--outcome", "Another change", "--expected-files", "A.md", "--json"])
        self.assertEqual(1, code)
        result = json.loads(output.getvalue())
        self.assertEqual("RESOLVE_TASK_CONFLICT", result["next_action"]["code"])
        self.assertEqual("DEVELOPER_ACTION", result["next_action"]["kind"])
        self.assertEqual("", result["next_action"]["command"])
        conflict = result["conflict"]
        self.assertEqual(["alpha"], [task["task_id"] for task in conflict["tasks"]])
        self.assertEqual(["a.md"], [Path(file).name.casefold() for file in conflict["conflicting_files"]])
        self.assertEqual({"work_in_order", "change_scope", "merge_plans", "cancel_task", "separate_worktree"},
                         {option["id"] for option in conflict["options"]})
        self.assertEqual(1, sum(bool(option.get("recommended")) for option in conflict["options"]))
        for option in conflict["options"]:
            if option["kind"] == "DEVELOPER_ACTION":
                self.assertEqual("", option["command"])
        self.assertEqual(alpha, read_json(workflow.task_dir(self.repo, "alpha") / "plan.json"))
        self.assertFalse((workflow.task_dir(self.repo, "beta") / "plan.json").exists())

    def test_limit_options_offer_delivery_cancellation_or_worktree(self):
        from delivery_manifest import TaskConflictError
        for task, file in (("alpha", "A.md"), ("beta", "B.md"), ("gamma", "C.md")):
            self.draft(task, file)
        with self.assertRaises(TaskConflictError) as caught:
            self.draft("delta", "D.md")
        details = caught.exception.details
        self.assertEqual(3, len(details["tasks"]))
        self.assertEqual({"finish_task", "merge_plans", "cancel_task", "separate_worktree"},
                         {option["id"] for option in details["options"]})

    def test_mutation_conflict_explains_choices(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        self.draft("beta", "B.md")
        self.approve("beta")
        allowed, reason, _ = file_mutation_allowed(self.repo, ["A.md"])
        self.assertFalse(allowed)
        self.assertIn("Available choices:", reason)
        self.assertIn("Choose separate files", reason)
        self.assertIn("local files stay in place", reason)

    def merge(self, ids=("alpha", "beta"), *, apply=False, preview="", target="combined"):
        from task_merge import merge_plans
        return merge_plans(argparse.Namespace(repo=str(self.repo), task_id=target, from_task_id=list(ids),
                                             apply=apply, expect_preview=preview, source="conversation",
                                             proof_reference="Combine these plans" if apply else ""))

    def test_merge_preview_is_stable_and_preserves_all_source_state(self):
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        root = workflow.state_root(self.repo)
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        preview = self.merge()
        self.assertEqual("MERGE_PREVIEW", preview["status"])
        self.assertEqual(preview["merge_preview_sha256"], self.merge()["merge_preview_sha256"])
        self.assertEqual(["A.md", "B.md"], preview["plan"]["expected_files"])
        self.assertEqual(["t1-work", "t2-work"], [p["id"] for p in preview["plan"]["phases"]])
        self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_merge_apply_keeps_history_and_requires_one_fresh_approval(self):
        from plan_authority import validate_plan_hash
        alpha = self.draft("alpha", "A.md")
        beta = self.draft("beta", "B.md")
        preview = self.merge()
        merged = self.merge(apply=True, preview=preview["merge_preview_sha256"])
        self.assertEqual("AWAITING_DEVELOPER_APPROVAL", merged["status"])
        self.assertIsNone(merged["approval"])
        self.assertIsNone(merged["execution_nonce"])
        self.assertTrue(validate_plan_hash(merged)[0])
        for old in (alpha, beta):
            directory = workflow.task_dir(self.repo, old["task_id"])
            source = read_json(directory / "plan.json")
            self.assertEqual("CANCELLED", source["status"])
            self.assertEqual("combined", source["merge"]["merged_into"])
            self.assertEqual(old, read_json(directory / "plan-history" / f"{old['plan_sha256']}.json"))
        self.assertEqual("combined", read_json(workflow.state_root(self.repo) / "active-task.json")["task_id"])
        self.assertFalse(file_mutation_allowed(self.repo, ["A.md"])[0])
        self.assertEqual("IMPLEMENTING", self.approve("combined")["status"])
        self.assertTrue(file_mutation_allowed(self.repo, ["A.md"])[0])
        self.assertEqual("", run_git(self.repo, "status", "--porcelain"))

    def test_merge_three_plans_frees_slots_and_preserves_third_party_edits(self):
        for task, file in (("alpha", "A.md"), ("beta", "B.md"), ("gamma", "C.md")):
            self.draft(task, file)
        preview = self.merge(("alpha", "beta", "gamma"))
        self.merge(("alpha", "beta", "gamma"), apply=True, preview=preview["merge_preview_sha256"])
        self.draft("delta", "D.md")
        self.draft("epsilon", "E.md")
        self.assertEqual(3, len(workflow.live_task_plans(self.repo)))

    def test_merge_rejects_started_revised_and_spent_tasks(self):
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        self.approve("alpha")
        with self.assertRaisesRegex(ValidationError, "TASK_MERGE_INELIGIBLE"):
            self.merge()
        workflow.revise(workflow.build_parser().parse_args([
            "revise", "--repo", str(self.repo), "--task-id", "alpha", "--outcome", "Expanded documentation goals",
        ]))
        with self.assertRaisesRegex(ValidationError, "history"):
            self.merge()

    def test_merge_rejects_source_edits_and_stale_preview(self):
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        preview = self.merge()
        write_file(self.repo / "A.md", "Changed before approval\n")
        with self.assertRaisesRegex(ValidationError, "TASK_MERGE_BASELINE_CHANGED"):
            self.merge(apply=True, preview=preview["merge_preview_sha256"])
        self.assertEqual("Changed before approval\n", (self.repo / "A.md").read_text())
        write_file(self.repo / "A.md", "original\n")
        workflow.revise(workflow.build_parser().parse_args([
            "revise", "--repo", str(self.repo), "--task-id", "beta", "--outcome", "Revised beta goals",
        ]))
        with self.assertRaisesRegex(ValidationError, "TASK_MERGE_PREVIEW_STALE"):
            self.merge(apply=True, preview=preview["merge_preview_sha256"])

    def test_merge_requires_explicit_preview_bound_choice(self):
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        with self.assertRaisesRegex(ValidationError, "TASK_MERGE_DECISION_REQUIRED"):
            self.merge(apply=True)
        from pre_tool_safety import _developer_authority_violation
        self.assertEqual("merge", _developer_authority_violation("python .agents/harness.py task merge --task-id combined --from-task-id alpha --from-task-id beta --apply"))
        self.assertEqual("", _developer_authority_violation("python .agents/harness.py task merge --task-id combined --from-task-id alpha --from-task-id beta"))

    def test_interrupted_merge_blocks_writes_and_recovers_without_losing_sources(self):
        import task_merge
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        preview = self.merge()["merge_preview_sha256"]
        real_save = task_merge.save_plan
        calls = []
        def interrupted(path, plan):
            if path.parent.name in {"alpha", "beta"}:
                calls.append(path.parent.name)
                if len(calls) == 2:
                    raise OSError("Simulated publication interruption")
            return real_save(path, plan)
        with mock.patch.object(task_merge, "save_plan", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "interruption"):
                self.merge(apply=True, preview=preview)
        with self.assertRaisesRegex(ValidationError, "TASK_MERGE_RECOVERY_REQUIRED"):
            workflow.live_task_plans(self.repo)
        recovered = self.merge(apply=True, preview=preview)
        self.assertEqual("AWAITING_DEVELOPER_APPROVAL", recovered["status"])
        self.assertEqual(["combined"], [tid for tid, _, _ in workflow.live_task_plans(self.repo)])

    def test_interrupted_merge_staging_can_retry_the_same_preview(self):
        import task_merge
        sources = [self.draft("alpha", "A.md"), self.draft("beta", "B.md")]
        preview = self.merge()["merge_preview_sha256"]
        root = workflow.state_root(self.repo)
        def interrupted(source, destination):
            destination.mkdir(parents=True)
            (destination / "incomplete.tmp").write_text("Unpublished preparation", encoding="utf-8")
            raise OSError("Simulated staging interruption")
        with mock.patch.object(task_merge.shutil, "copytree", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "staging interruption"):
                self.merge(apply=True, preview=preview)
        self.assertFalse((root / "task-merge-pending.json").exists())
        self.assertEqual(sources, [read_json(workflow.task_dir(self.repo, p["task_id"]) / "plan.json") for p in sources])
        self.assertEqual(2, len(workflow.live_task_plans(self.repo)))
        merged = self.merge(apply=True, preview=preview)
        self.assertEqual("AWAITING_DEVELOPER_APPROVAL", merged["status"])
        self.assertFalse((workflow.task_dir(self.repo, "combined") / "incomplete.tmp").exists())
        self.assertEqual(["combined"], [tid for tid, _, _ in workflow.live_task_plans(self.repo)])

    def test_conflict_merge_option_explains_eligibility(self):
        from delivery_manifest import TaskConflictError
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        with self.assertRaises(TaskConflictError) as caught:
            workflow.revise(workflow.build_parser().parse_args([
                "revise", "--repo", str(self.repo), "--task-id", "beta", "--expected-files", "A.md",
            ]))
        option = next(o for o in caught.exception.details["options"] if o["id"] == "merge_plans")
        self.assertTrue(option["available"])
        self.assertIn("task merge", option["command"])
        self.assertNotIn("--apply", option["command"])
        self.approve("alpha")
        with self.assertRaises(TaskConflictError) as caught:
            self.draft("gamma", "A.md")
        option = next(o for o in caught.exception.details["options"] if o["id"] == "merge_plans")
        self.assertFalse(option["available"])
        self.assertIn("IMPLEMENTING", option["description"])

    def test_merge_preserves_unmerged_running_sibling_and_its_dirty_files(self):
        self.draft("gamma", "C.md")
        self.approve("gamma")
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        write_file(self.repo / "C.md", "Ongoing gamma work\n")
        gamma = read_json(workflow.task_dir(self.repo, "gamma") / "plan.json")
        preview = self.merge()["merge_preview_sha256"]
        self.merge(apply=True, preview=preview)
        self.assertEqual(gamma, read_json(workflow.task_dir(self.repo, "gamma") / "plan.json"))
        self.assertEqual("Ongoing gamma work\n", (self.repo / "C.md").read_text())
        self.approve("combined")
        write_file(self.repo / "A.md", "Combined first phase\n")
        self.assertEqual(["A.md"], [c["path"] for c in build_task_manifest(self.repo, "combined")["task_changes"]])

    def test_merge_preserves_tracker_link_and_rejects_different_links(self):
        from plan_authority import plan_payload
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        def link(task, item):
            path = workflow.task_dir(self.repo, task) / "plan.json"
            plan = read_json(path)
            plan["zoho_link"] = {"item_id": item, "sprint_id": "sprint", "item_type": "Task"}
            plan["plan_sha256"] = workflow.canonical_sha256(plan_payload(plan))
            atomic_write_json(path, plan)
        link("alpha", "item-a")
        preview = self.merge()
        self.assertEqual("item-a", preview["plan"]["zoho_link"]["item_id"])
        link("beta", "item-b")
        with self.assertRaisesRegex(ValidationError, "TASK_MERGE_INCOMPATIBLE.*zoho_link"):
            self.merge()
        self.assertFalse(workflow.task_dir(self.repo, "combined").exists())

    def test_merge_cli_returns_valid_json_and_pending_approval_material(self):
        self.draft("alpha", "A.md")
        self.draft("beta", "B.md")
        command = ["merge", "--repo", str(self.repo), "--task-id", "combined", "--from-task-id", "alpha", "--from-task-id", "beta", "--json"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, workflow.main(command))
        preview = json.loads(output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, workflow.main([*command, "--apply", "--expect-preview", preview["merge_preview_sha256"],
                                               "--source", "conversation", "--proof-reference", "Merge these two plans"]))
        result = json.loads(output.getvalue())
        self.assertEqual("AWAITING_DEVELOPER_APPROVAL", result["status"])
        self.assertIn("approval_material", result)
        self.assertIn("PLAN_DOCUMENT_URI=", result["approval_material"])
        self.assertIn("Source plans (execution order)", (workflow.task_dir(self.repo, "combined") / "plan.md").read_text(encoding="utf-8"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, workflow.main(command))
        self.assertEqual("TASK_MERGE_INPUT", json.loads(output.getvalue())["next_action"]["code"])

    def test_merge_code_plans_with_same_architecture_and_different_files(self):
        for name in ("Alpha", "Beta"):
            write_file(self.repo / f"app/src/main/java/sample/{name}.kt", f"package sample\nclass {name}\n")
        run_git(self.repo, "add", "app")
        run_git(self.repo, "commit", "-qm", "Add code fixture")
        for name in ("Alpha", "Beta"):
            workflow.draft(workflow.build_parser().parse_args([
                "draft", "--repo", str(self.repo), "--task-id", name.lower(), "--outcome", f"Update {name} behavior",
                "--expected-files", f"app/src/main/java/sample/{name}.kt", "--expected-surfaces", "BUSINESS_LOGIC",
            ]))
        preview = self.merge()
        self.assertEqual("app/src/main/java/sample", preview["plan"]["architecture_contract"]["target_scope"])
        beta_path = workflow.task_dir(self.repo, "beta") / "plan.json"
        beta = read_json(beta_path)
        changed = json.loads(json.dumps(beta))
        changed["architecture_contract"]["target_dimensions"] = {"ui_toolkit": "incompatible"}
        from plan_authority import plan_payload
        changed["plan_sha256"] = workflow.canonical_sha256(plan_payload(changed))
        atomic_write_json(beta_path, changed)
        with self.assertRaisesRegex(ValidationError, "TASK_MERGE_INCOMPATIBLE.*architecture"):
            self.merge()
        self.assertFalse(workflow.task_dir(self.repo, "combined").exists())
        atomic_write_json(beta_path, beta)
        merged = self.merge(apply=True, preview=preview["merge_preview_sha256"])
        self.assertEqual("AWAITING_DEVELOPER_APPROVAL", merged["status"])
        self.assertIn("BUSINESS_LOGIC", merged["expected_surfaces"])


if __name__ == "__main__":
    unittest.main()
