"""Public contracts for incremental task change decisions."""
import argparse
import json
import unittest
from pathlib import Path
from unittest import mock

import workflow
import _task_isolation_selftest as fixtures
from _vnext_common import ValidationError, read_json
from mutation_guard import file_mutation_allowed
from plan_authority import validate_plan_hash


class ChangeDecisionTests(unittest.TestCase):
    setUp = fixtures.TaskIsolationTests.setUp
    draft = fixtures.TaskIsolationTests.draft
    approve = fixtures.TaskIsolationTests.approve
    ready = fixtures.TaskIsolationTests.ready

    def command(self, *extra):
        args = workflow.build_parser().parse_args([
            "change-decision", "--repo", str(self.repo), "--task-id", getattr(self, "task_identity", "alpha"), *extra,
        ])
        return args.handler(args)

    def start(self):
        self.draft("alpha", "A.md")
        self.approve("alpha")
        (self.repo / "A.md").write_text("task edit\n", encoding="utf-8")

    def test_same_goal_file_keeps_approval_and_allows_verification(self):
        self.start()
        original = read_json(workflow.task_dir(self.repo, "alpha") / "plan.json")
        preview = self.command("--mode", "extend-scope", "--file", "B.md", "--reason", "Supporting documentation for the approved outcome")
        self.command("--mode", "extend-scope", "--file", "B.md", "--reason", "Supporting documentation for the approved outcome",
                     "--apply", "--expect-preview", preview["preview_sha256"], "--source", "approved-plan")
        plan = read_json(workflow.task_dir(self.repo, "alpha") / "plan.json")
        self.assertEqual(original["approval"], plan["approval"])
        self.assertEqual(original["plan_sha256"], plan["plan_sha256"])
        self.assertTrue(validate_plan_hash(plan)[0])
        self.assertTrue(file_mutation_allowed(self.repo, ["B.md"])[0])
        (self.repo / "B.md").write_text("supporting edit\n", encoding="utf-8")
        current = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="alpha", force=False))
        self.assertTrue(current["run_id"])

    def test_preview_race_and_missing_consent_do_not_mutate(self):
        self.start()
        self.ready("alpha")
        (self.repo / "A.md").write_text("personal edit\n", encoding="utf-8")
        preview = self.command("--mode", "accept-edits", "--file", "A.md", "--reason", "Intentional wording")
        with self.assertRaises(ValidationError):
            self.command("--mode", "accept-edits", "--file", "A.md", "--reason", "Intentional wording",
                         "--apply", "--expect-preview", preview["preview_sha256"])
        (self.repo / "A.md").write_text("another edit\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "STALE"):
            self.command("--mode", "accept-edits", "--file", "A.md", "--reason", "Intentional wording",
                         "--apply", "--expect-preview", preview["preview_sha256"], "--source", "conversation", "--proof-reference", "My edit; skip its review")
        self.assertEqual("READY_FOR_DELIVERY", read_json(workflow.task_dir(self.repo, "alpha") / "plan.json")["status"])

    def test_personal_outside_file_is_not_agent_write_authority(self):
        self.start()
        self.ready("alpha")
        (self.repo / "B.md").write_text("my independent wording\n", encoding="utf-8")
        options = ["--mode", "review-edits", "--file", "B.md", "--reason", "Personal documentation change"]
        preview = self.command(*options)
        self.command(*options, "--apply", "--expect-preview", preview["preview_sha256"],
                     "--source", "conversation", "--proof-reference", "Review my edit")
        self.assertFalse(file_mutation_allowed(self.repo, ["B.md"])[0])
        self.ready("alpha")
        (self.repo / "B.md").write_text("a different personal edit\n", encoding="utf-8")
        workflow.resume(argparse.Namespace(repo=str(self.repo), task_id="alpha"))
        with self.assertRaisesRegex(ValidationError, "FILE_SCOPE_DECISION_REQUIRED"):
            workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="alpha", force=False))

    def test_scope_receipt_is_idempotent_and_reserves_sibling_files(self):
        self.start()
        options = ["--mode", "extend-scope", "--file", "B.md", "--reason", "Same documentation goal"]
        preview = self.command(*options)
        apply = [*options, "--apply", "--expect-preview", preview["preview_sha256"], "--source", "approved-plan"]
        self.command(*apply)
        self.assertTrue(self.command(*apply)["already_applied"])
        with self.assertRaisesRegex(ValidationError, "ACTIVE_TASK_CONFLICT"):
            self.draft("beta", "B.md")

    def test_material_surface_and_protected_paths_cannot_use_file_exception(self):
        self.start()
        for path in ("../escape.md", ".agents/state/plan.json", "*.md", ".git/config"):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                self.command("--mode", "extend-scope", "--file", path, "--reason", "Not authorized")
        target = "app/src/main/kotlin/Auth.kt"
        (self.repo / target).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / target).write_text("class Auth { fun login(password: String) = password }", encoding="utf-8")
        options = ["--mode", "extend-scope", "--file", target, "--reason", "Unplanned sensitive behavior"]
        preview = self.command(*options)
        self.assertTrue(preview["material_drift"])
        with self.assertRaisesRegex(ValidationError, "PLAN_APPROVAL_REQUIRED"):
            self.command(*options, "--apply", "--expect-preview", preview["preview_sha256"], "--source", "approved-plan")

    def test_accepted_delta_retains_real_reviews_and_later_edit_invalidates_it(self):
        import _daily_workflow_selftest as daily
        from review_orchestrator import record_dispatch_batch, complete_review
        from review_policy import FIVE_REVIEWERS
        from final_verifier import validate_policy_artifact
        fixture = daily.ReviewOrchestrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        self.repo = fixture.repo
        content = 'package com.example\nclass MainActivity { fun caption() = "Start" }\n'
        current, run_id, package, directory = fixture._setup_v2_task("alpha", sorted(FIVE_REVIEWERS), content=content)
        record_dispatch_batch(self.repo, "alpha", sorted(FIVE_REVIEWERS))
        for index, reviewer in enumerate(sorted(FIVE_REVIEWERS)):
            execution = f"accepted-change-review-{index}"
            fixture._create_mock_transcript(execution, json.dumps({"schema_version": 2, "task_id": "alpha", "run_id": run_id,
                "reviewer": reviewer, "review_package_sha256": package, "verdict": "PASS", "findings": []}))
            complete_review(self.repo, "alpha", reviewer, execution)
        old_plan = read_json(directory / "plan.json")
        old_run = (directory / "current-run.json").read_bytes()
        target = "app/src/main/kotlin/com/example/MainActivity.kt"
        (self.repo / target).write_text(content.replace("Start", "Continue"), encoding="utf-8")
        options = ["--mode", "accept-edits", "--file", target, "--reason", "Developer-owned caption"]
        preview = self.command(*options)
        self.command(*options, "--apply", "--expect-preview", preview["preview_sha256"],
                     "--source", "conversation", "--proof-reference", "My caption edit is intentional; no additional review")
        self.assertEqual(old_run, (directory / "current-run.json").read_bytes())
        plan = read_json(directory / "plan.json")
        for key in ("approval", "plan_sha256", "review_calls_used", "review_rounds"):
            self.assertEqual(old_plan[key], plan[key])
        fresh = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="alpha", host="antigravity"))
        policy = read_json(Path(fresh["policy"]))
        self.assertEqual([], policy["reviewers"])
        self.assertTrue(policy["carried_reviews"])
        self.assertEqual([target], policy["fix_delta"]["developer_accepted_files"])
        manifest = read_json(Path(fresh["manifest"]))
        _, error, status = validate_policy_artifact(self.repo, read_json(directory / "plan.json"), policy,
            workflow.state_root(self.repo), Path(fresh["policy"]), current_change_set=manifest["change_set_sha256"],
            task_changes=manifest["task_changes"])
        self.assertEqual("PASS", status, error)
        # A second edit must not inherit consent or restart the plan.
        workflow.resume(argparse.Namespace(repo=str(self.repo), task_id="alpha"))
        (self.repo / target).write_text(content.replace("Start", "New behavior"), encoding="utf-8")
        again = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="alpha", host="antigravity"))
        later = read_json(Path(again["policy"]))
        self.assertTrue(later["reviewers"])
        self.assertFalse(later.get("fix_delta", {}).get("developer_accepted_files"))

    def test_final_phase_history_survives_exact_decision_and_integration_corrections(self):
        import _phase_review_v2_selftest as phase_tests
        fixture = phase_tests.PhaseReviewV2Selftest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        self.repo = fixture.repo
        target = "app/src/main/res/values/one.xml"
        task = fixture._create_phased_task([{"id": "p1", "name": "Text", "expected_files": [target]}])
        self.task_identity = task
        source = self.repo / target
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<resources/>\n", encoding="utf-8")
        workflow.checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task, phase_id="p1"))
        original = (workflow.task_dir(self.repo, task) / "phase-state.json").read_bytes()
        workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task, host="generic"))
        source.write_text("<resources><string name='late'>Intentional</string></resources>\n", encoding="utf-8")
        options = ["--mode", "review-edits", "--file", target, "--reason", "Personal final wording"]
        preview = self.command(*options)
        self.command(*options, "--apply", "--expect-preview", preview["preview_sha256"], "--source", "conversation", "--proof-reference", "Review my wording")
        self.assertEqual("PREPARE_VERIFICATION", workflow.resolve_next_action(self.repo, task)["code"])
        workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task, host="generic"))
        self.assertEqual(original, (workflow.task_dir(self.repo, task) / "phase-state.json").read_bytes())
        workflow.resume(argparse.Namespace(repo=str(self.repo), task_id=task))
        source.write_text("<resources><string name='late'>Corrected during integration</string></resources>\n", encoding="utf-8")
        self.assertEqual("PREPARE_VERIFICATION", workflow.resolve_next_action(self.repo, task)["code"])
        workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task, host="generic"))
        self.assertEqual("RUN_PREFLIGHT", workflow.resolve_next_action(self.repo, task, host="generic")["code"])

    def test_native_hook_allows_decision_command_during_stale_verification(self):
        import _hook_selftest as hooks
        fixture = hooks.HookTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        for status in ("IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"):
            fixture.activate(status=status)
            result = fixture.call("run_command", {"CommandLine": 'python .agents/harness.py task change-decision --task-id task-one --mode review-edits --file app/src/main/kotlin/com/example/MainActivity.kt --reason "Personal edit"'})
            self.assertEqual("allow", result["decision"], result)
        base = 'python .agents/harness.py task change-decision --task-id task-one --mode accept-edits --file app/src/main/kotlin/com/example/MainActivity.kt --reason "Personal edit" --apply --expect-preview abc'
        self.assertEqual("deny", fixture.call("run_command", {"CommandLine": base + ' --source developer_terminal --proof-reference "Mine"'})["decision"])
        self.assertEqual("deny", fixture.call("run_command", {"CommandLine": base + ' --source approved-plan'})["decision"])
        self.assertEqual("allow", fixture.call("run_command", {"CommandLine": base + ' --source conversation --proof-reference "Mine; skip review"'})["decision"])

    def test_two_unlisted_xml_files_do_not_discard_completed_specialists(self):
        import _daily_workflow_selftest as daily
        from review_orchestrator import record_dispatch_batch, complete_review
        from review_policy import FIVE_REVIEWERS
        fixture = daily.ReviewOrchestrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        self.repo = fixture.repo
        paths = ["app/src/main/res/layout/joining_groups_target_card.xml", "app/src/main/res/layout/health_condition_item2.xml"]
        for path in paths:
            daily.write_file(self.repo / path, '<TextView xmlns:android="http://schemas.android.com/apk/res/android" android:text="Before"/>\n')
        daily.run_git(self.repo, "add", "app/src/main/res/layout")
        daily.run_git(self.repo, "commit", "-qm", "XML fixture")
        draft_impl = daily.draft
        def draft_with_xml_scope(args):
            args.expected_surfaces = "BUSINESS_LOGIC,XML_UI,COMPOSE_UI,BILLING"
            return draft_impl(args)
        roles = sorted(set(FIVE_REVIEWERS) | {"test-quality-reviewer-agent"})
        with mock.patch.object(daily, "draft", side_effect=draft_with_xml_scope):
            current, run_id, package, directory = fixture._setup_v2_task("alpha", roles, content='package com.example\nclass MainActivity { fun caption() = "Start" }\n')
        record_dispatch_batch(self.repo, "alpha", roles)
        for index, role in enumerate(roles):
            execution = f"xml-source-{index}"
            fixture._create_mock_transcript(execution, json.dumps({"schema_version": 2, "task_id": "alpha", "run_id": run_id,
                "reviewer": role, "review_package_sha256": package, "verdict": "PASS", "findings": []}))
            complete_review(self.repo, "alpha", role, execution)
        old_plan = read_json(directory / "plan.json")
        for path in paths:
            daily.write_file(self.repo / path, '<TextView xmlns:android="http://schemas.android.com/apk/res/android" android:text="After"/>\n')
        workflow.resume(argparse.Namespace(repo=str(self.repo), task_id="alpha"))
        with self.assertRaisesRegex(ValidationError, "FILE_SCOPE_DECISION_REQUIRED"):
            workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="alpha", host="antigravity"))
        options = ["--mode", "extend-scope", "--reason", "Supporting layouts for the same onboarding outcome"]
        for path in paths:
            options += ["--file", path]
        preview = self.command(*options)
        self.command(*options, "--apply", "--expect-preview", preview["preview_sha256"], "--source", "approved-plan")
        fresh = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="alpha", host="antigravity"))
        policy = read_json(Path(fresh["policy"]))
        self.assertEqual(run_id, policy["later_round_source"]["run_id"])
        self.assertLess(len(policy["reviewers"]), len(roles))
        self.assertNotIn("security-reviewer-agent", policy["reviewers"])
        self.assertEqual(old_plan["plan_sha256"], read_json(directory / "plan.json")["plan_sha256"])


if __name__ == "__main__":
    unittest.main()
