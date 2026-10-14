"""Behavioral contracts for policy explanations, diagnostic metrics, and test impact."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _product
import _repo_files
import change_classifier
import review_policy
import run_tests_gate
from task_metrics import metrics_report, record_operation


class WorkflowInsightTests(unittest.TestCase):
    def test_review_forecast_discloses_shared_setup_limit_without_changing_authority(self):
        from review_budget import forecast_review_calls, effective_review_budget
        from plan_document import render_plan_document
        from workflow import approval_brief, plan_summary
        plan = {"task_id": "task", "task_kind": "FEATURE", "phases": [{"id": f"p{i}"} for i in range(6)]}
        policy = {"model_call_budget": 20, "reviewers": [f"reviewer-{i}" for i in range(7)]}
        before = json.dumps(plan, sort_keys=True)
        forecast = forecast_review_calls(plan, policy)
        self.assertEqual(before, json.dumps(plan, sort_keys=True))
        self.assertEqual(20, forecast["configured_limit"])
        self.assertEqual(12, forecast["phase_calls_estimate"])
        self.assertEqual(7, forecast["final_calls_estimate"])
        self.assertEqual(7, forecast["correction_reserve"])
        self.assertEqual(26, forecast["estimated_total_with_reserve"])
        self.assertEqual("HEADROOM_LIMITED", forecast["status"])
        with patch.object(_product, "MODEL_CALL_BUDGET", 12, create=True):
            self.assertEqual(12, forecast_review_calls(plan, {**policy, "model_call_budget": 12})["configured_limit"])
            self.assertEqual(12, effective_review_budget(None, plan))
        plan["review_budget_forecast"] = forecast
        self.assertEqual(20, effective_review_budget(None, plan, policy))
        for text in (render_plan_document(Path.cwd(), plan, policy=policy), approval_brief(plan), plan_summary(plan)):
            self.assertIn("20", text)
            self.assertIn("26", text)
            self.assertIn("shared", text.lower())

    def test_review_forecast_keeps_documentation_and_disabled_phase_reviews_cheap(self):
        from review_budget import forecast_review_calls
        plan = {"phases": [{"id": "p1", "expected_files": ["docs/guide.md"]}, {"id": "p2"}]}
        policy = {"model_call_budget": 30, "reviewers": ["bug-reviewer-agent"]}
        self.assertEqual(2, forecast_review_calls(plan, policy)["phase_calls_estimate"])
        plan["scoped_phase_review_enabled"] = False
        self.assertEqual(0, forecast_review_calls(plan, policy)["phase_calls_estimate"])
        self.assertEqual("WITHIN_LIMIT", forecast_review_calls(plan, policy)["status"])

    def test_metrics_distinguish_environment_failures_and_repeated_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            record_operation(repo, "task", "test", 2, 30)
            record_operation(repo, "task", "test", 3, 1)
            record_operation(repo, "task", "test", 1, 0)
            record_operation(repo, "task", "task-approve", 1, 0)
            report = metrics_report(repo, "task")
            self.assertEqual(1, report["environment_failures"])
            self.assertEqual(1, report["other_failed_commands"])
            self.assertEqual(2, report["repeated_command_executions"])
            self.assertEqual({"task-approve": 1}, report["successful_decision_commands"])
            self.assertEqual("UNAVAILABLE", report["developer_work_seconds"])

    def test_policy_explains_each_selected_gate_and_reviewer(self):
        classification = {"surfaces": ["BILLING"], "severity": "CRITICAL", "confidence": "HIGH",
                          "details": {"BILLING": {"files": ["Billing.kt"], "reasons": ["BILLING_PATTERN"]}}}
        policy = review_policy.decide(classification, Path(__file__).resolve().parents[1] / "skills")
        explanation = policy["explanation"]
        self.assertEqual(set(policy["gates"]), set(explanation["gates"]))
        self.assertEqual(set(policy["reviewers"]), set(explanation["reviewers"]))
        self.assertIn("CRITICAL_SURFACE", explanation["risk_tier"])
        self.assertIn("BILLING", explanation["gates"]["unit_tests"])
        self.assertEqual(classification["details"], explanation["classification"])

    def test_micro_policy_does_not_explain_reviewers_that_will_not_run(self):
        policy = review_policy.decide({"surfaces": ["DOCS"], "severity": "LOW", "changed_files": 1,
                                       "changed_lines": 1}, Path(__file__).resolve().parents[1] / "skills")
        self.assertEqual([], policy["reviewers"])
        self.assertEqual({}, policy["explanation"]["reviewers"])

    def test_classifier_preserves_per_file_reason_association(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "README.md").write_text("Documentation\n")
            result = change_classifier.classify(repo, progress=False)
            signals = result["details"]["DOCS"]["signals"]
            self.assertTrue(signals)
            self.assertEqual({"README.md"}, {item["path"] for item in signals})
            self.assertEqual(set(result["details"]["DOCS"]["reasons"]), {item["reason"] for item in signals})

    def test_finding_metrics_are_plan_bound_and_do_not_expose_content(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            record_operation(repo, "task", "test", 1, 0)
            state = repo / ".agents/state/tasks/task"
            state.mkdir(parents=True)
            (state / "plan.json").write_text(json.dumps({"task_id": "task", "plan_sha256": "current"}))
            findings = {"task_id": "task", "plan_sha256": "current", "validations": [
                {"finding_id": "private-id", "status": "CONFIRMED", "reason": "private-source"},
                {"finding_id": "private-id", "status": "FALSE_POSITIVE", "reason": "private-source"}]}
            path = state / "finding-validations.json"
            path.write_text(json.dumps(findings))
            before = {p: p.read_bytes() for p in repo.rglob("*.json")}
            report = metrics_report(repo, "task")
            self.assertEqual({"FALSE_POSITIVE": 1}, report["reported_finding_verdicts"])
            self.assertNotIn("private", json.dumps(report))
            self.assertEqual(before, {p: p.read_bytes() for p in repo.rglob("*.json")})
            findings["plan_sha256"] = "stale"
            path.write_text(json.dumps(findings))
            self.assertEqual("UNAVAILABLE", metrics_report(repo, "task")["reported_finding_verdicts"])

    def test_missing_and_corrupt_metrics_do_not_invent_success(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.assertEqual("UNAVAILABLE", metrics_report(repo, "task")["environment_failures"])
            record_operation(repo, "task", "test", 1, 0)
            path = next((repo / ".agents/state/metrics/task").glob("*.json"))
            event = json.loads(path.read_text())
            event["exit_code"] = "0"
            path.write_text(json.dumps(event))
            report = metrics_report(repo, "task")
            self.assertEqual(1, report["invalid_events"])
            self.assertEqual("UNAVAILABLE", report["other_failed_commands"])

    def _project(self, root):
        (root / "settings.gradle.kts").write_text('include(":app", ":feature", ":base", ":unrelated")\n')
        for name, dependencies in (("app", 'implementation(project(":feature"))'),
                                   ("feature", 'api(project(":base"))'), ("base", ""), ("unrelated", "")):
            directory = root / name
            directory.mkdir()
            (directory / "build.gradle.kts").write_text('plugins { id("com.android.library") }\ndependencies { ' + dependencies + ' }\n')

    def test_changed_library_selects_transitive_consumers(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self._project(repo)
            with patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), \
                    patch("baseline_capture._unit_test_task", return_value=":app:testDemoDebugUnitTest"), \
                    patch.object(_repo_files, "changed_paths", return_value=[repo / "base/src/main/Base.kt"]):
                self.assertEqual([":app:testDemoDebugUnitTest", ":base:testDemoDebugUnitTest", ":feature:testDemoDebugUnitTest"],
                                 run_tests_gate.resolve_target_tasks(repo, None))
                self.assertEqual([":base:testCustomUnitTest"], run_tests_gate.resolve_target_tasks(repo, ":base:testCustomUnitTest"))

    def test_build_configuration_selects_all_declared_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self._project(repo)
            with patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), \
                    patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"), \
                    patch.object(_repo_files, "changed_paths", return_value=[repo / "gradle/libs.versions.toml"]):
                self.assertEqual([f":{m}:testDebugUnitTest" for m in ("app", "base", "feature", "unrelated")],
                                 run_tests_gate.resolve_target_tasks(repo, None))

    def test_jvm_dependency_uses_jvm_test_task(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self._project(repo)
            (repo / "base/build.gradle.kts").write_text('plugins { kotlin("jvm") }\n')
            with patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), \
                    patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"), \
                    patch.object(_repo_files, "changed_paths", return_value=[repo / "base/src/main/Base.kt"]):
                self.assertIn(":base:test", run_tests_gate.resolve_target_tasks(repo, None))

    def test_named_dependencies_cycles_and_remapped_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self._project(repo)
            (repo / "feature/build.gradle.kts").write_text('dependencies { demoImplementation(project(path = ":base")) }')
            (repo / "base/build.gradle.kts").write_text('dependencies { api(projects.feature) }')
            (repo / "base").rename(repo / "shared")
            with (repo / "settings.gradle.kts").open("a") as handle:
                handle.write('project(":base").projectDir = file("shared")\n')
            with patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), \
                    patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"), \
                    patch.object(_repo_files, "changed_paths", return_value=[repo / "shared/src/main/Base.kt"]):
                tasks = run_tests_gate.resolve_target_tasks(repo, None)
                self.assertEqual([f":{m}:testDebugUnitTest" for m in ("app", "base", "feature", "unrelated")], tasks)
            report = repo / "shared/build/test-results/testDebugUnitTest/TEST-base.xml"
            report.parent.mkdir(parents=True)
            report.write_text('<testsuite tests="1" failures="1"><testcase classname="Base" name="broken"><failure/></testcase></testsuite>')
            self.assertEqual([report], run_tests_gate.report_paths(repo, ":base:testDebugUnitTest"))
            self.assertEqual(1, run_tests_gate.collect_test_summary(repo, ":base:testDebugUnitTest")["failed"])

    def test_non_app_project_does_not_invent_app_task(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "settings.gradle.kts").write_text('include(":mobile", ":core")')
            for name in ("mobile", "core"):
                (repo / name).mkdir()
                (repo / name / "build.gradle.kts").write_text('plugins { kotlin("jvm") }')
            with patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), \
                    patch("baseline_capture._unit_test_task", return_value=":mobile:test"), \
                    patch.object(_repo_files, "changed_paths", return_value=[repo / "gradle.properties"]):
                self.assertEqual([":core:test", ":mobile:test"], run_tests_gate.resolve_target_tasks(repo, None))

    def test_asset_packs_do_not_receive_invented_unit_test_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self._project(repo)
            with (repo / "settings.gradle.kts").open("a") as handle:
                handle.write('include(":foods_db_pack")\n')
            pack = repo / "foods_db_pack"
            pack.mkdir()
            (repo / "gradle").mkdir()
            (repo / "gradle/libs.versions.toml").write_text(
                '[plugins]\nasset-pack = { id = "com.android.asset-pack", version = "8.14" }\n')
            builds = [
                'plugins { id "com.android.asset-pack" }\n',
                'plugins { id("com.android.asset-pack") }\n',
                "apply plugin: 'com.android.asset-pack'\n",
                'plugins { alias(libs.plugins.asset.pack) }\n',
            ]
            for build in builds:
                with self.subTest(build=build):
                    (pack / "build.gradle").write_text(build)
                    with patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), \
                            patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"), \
                            patch.object(_repo_files, "changed_paths", return_value=[repo / "gradle.properties"]):
                        self.assertEqual([f":{m}:testDebugUnitTest" for m in ("app", "base", "feature", "unrelated")],
                                         run_tests_gate.resolve_target_tasks(repo, None))
                        self.assertEqual([":foods_db_pack:customCheck"],
                                         run_tests_gate.resolve_target_tasks(repo, ":foods_db_pack:customCheck"))

    def test_asset_pack_mentions_do_not_suppress_unknown_or_real_test_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self._project(repo)
            for build in [
                '// plugins { id("com.android.asset-pack") }\nplugins { kotlin("jvm") }',
                'plugins { id("com.android.asset-pack") apply false; id("com.example.convention") }',
                'plugins { id("com.android.asset-pack"); id("java-library") }',
                'plugins { id("com.android.asset-pack"); alias(libs.plugins.unknown) }',
                'plugins { id("com.android.asset-pack"); id(customTestPlugin) }',
                'plugins { id("com.android.asset-pack") }\napply(\nfrom = "custom-tests.gradle.kts"\n)',
            ]:
                with self.subTest(build=build):
                    (repo / "base/build.gradle.kts").write_text(build)
                    with patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), \
                            patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"), \
                            patch.object(_repo_files, "changed_paths", return_value=[repo / "gradle.properties"]):
                        self.assertTrue(any(task.startswith(":base:") for task in run_tests_gate.resolve_target_tasks(repo, None)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
