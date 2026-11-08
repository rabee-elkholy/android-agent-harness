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
        policy = {"model_call_budget": 30, "reviewers": ["bug-test-reviewer-agent"]}
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

    def test_blind_goldfish_brief_isolation_and_reuse_candidates(self):
        import review_package
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            task_id = "goldfish-task"
            tdir = repo / ".agents/state/tasks" / task_id
            tdir.mkdir(parents=True)
            pkg_dir = tdir / "review-packages/RUN_1"
            pkg_dir.mkdir(parents=True)
            plan = {
                "task_id": task_id,
                "plan_sha256": "plan123",
                "outcome": "Validate checkout payment state",
                "approach": "Add validation helper and update ViewModel",
                "expected_files": ["app/src/main/kotlin/com/example/CheckoutViewModel.kt"],
                "non_goals": ["No UI redesign"],
                "reuse_candidates": [
                    {
                        "planned_file": "app/src/main/kotlin/com/example/PaymentValidator.kt",
                        "symbol": "PaymentValidator",
                        "existing_file": "core/src/main/kotlin/com/example/core/PaymentValidator.kt",
                        "kind": "CLASS",
                    }
                ],
            }
            (tdir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            validations = {
                "task_id": task_id,
                "plan_sha256": "plan123",
                "validations": [
                    {"finding_id": "F-BUG-1", "reviewer": "bug-test-reviewer-agent", "status": "FALSE_POSITIVE", "reason": "Guarded by null check"},
                    {"finding_id": "F-SEC-1", "reviewer": "security-perf-reviewer-agent", "status": "FALSE_POSITIVE", "reason": "Internal token only"},
                ],
            }
            (tdir / "finding-validations.json").write_text(json.dumps(validations), encoding="utf-8")
            routed = ["bug-test-reviewer-agent", "security-perf-reviewer-agent", "arch-regression-reviewer-agent", "spec-compliance-agent"]
            policy = {"reviewers": routed, "surfaces": ["STATE_ARCH"]}
            metadata = {
                "run_id": "RUN_1",
                "delivery_snapshot_sha256": "snap123",
                "change_set_sha256": "cs123",
                "package_sha256": "pkg1234567890",
            }
            changes = [{"path": "app/src/main/kotlin/com/example/CheckoutViewModel.kt", "status": "M"}]
            bug_brief = review_package.generate_task_brief(repo, task_id, "bug-test-reviewer-agent", pkg_dir, metadata, plan, policy, changes).read_text(encoding="utf-8")
            sec_brief = review_package.generate_task_brief(repo, task_id, "security-perf-reviewer-agent", pkg_dir, metadata, plan, policy, changes).read_text(encoding="utf-8")
            conv_brief = review_package.generate_task_brief(repo, task_id, "arch-regression-reviewer-agent", pkg_dir, metadata, plan, policy, changes).read_text(encoding="utf-8")
            spec_brief = review_package.generate_task_brief(repo, task_id, "spec-compliance-agent", pkg_dir, metadata, plan, policy, changes).read_text(encoding="utf-8")

            self.assertIn("**Approved Approach**:", bug_brief)
            self.assertIn("**Approved Approach**:", sec_brief)
            self.assertNotIn("Goldfish Epistemic Independence", bug_brief)
            self.assertIn("Goldfish Epistemic Independence (Blind Specialist Evaluation)", sec_brief)
            self.assertIn("Goldfish Epistemic Independence (Blind Specialist Evaluation)", conv_brief)
            self.assertIn("Graph-Discovered Existing Reuse Candidates", conv_brief)
            self.assertIn("Graph-Discovered Existing Reuse Candidates", spec_brief)
            self.assertNotIn("Graph-Discovered Existing Reuse Candidates", sec_brief)
            self.assertIn("F-SEC-1", sec_brief)
            self.assertNotIn("F-BUG-1", sec_brief)
            self.assertIn("F-SEC-1", bug_brief)

    def test_plan_readiness_and_reuse_discovery_without_changing_plan_hash(self):
        from _graph_core import GraphEngine
        from _workflow.planning import _discover_reuse_candidates, _evaluate_plan_readiness
        from workflow import approval_brief, plan_payload
        from plan_document import render_plan_document
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            existing = repo / "core/src/main/kotlin/com/example/core/PaymentValidator.kt"
            existing.parent.mkdir(parents=True)
            existing.write_text("package com.example.core\nclass PaymentValidator {\n    fun validate(): Boolean = true\n}\n", encoding="utf-8")
            engine = GraphEngine(repo)
            engine.sync()

            expected = ["app/src/main/kotlin/com/example/PaymentValidator.kt"]
            candidates = _discover_reuse_candidates(repo, expected)
            self.assertTrue(any(c["symbol"] == "PaymentValidator" for c in candidates))

            base_plan = {
                "schema_version": 2,
                "task_id": "t-readiness",
                "task_kind": "FEATURE",
                "requested_outcome": "Add payment validation",
                "approach": "",
                "expected_files": expected,
                "expected_surfaces": ["STATE_ARCH"],
                "risks": [],
                "constraints": [],
            }
            payload_before = plan_payload(dict(base_plan))
            policy = {"risk_tier": "T3_HIGH", "gates": ["preflight", "unit_tests"], "reviewers": ["bug-test-reviewer-agent"]}
            enriched_plan = dict(base_plan)
            enriched_plan["reuse_candidates"] = candidates
            enriched_plan["readiness_assessment"] = _evaluate_plan_readiness(enriched_plan, policy)
            self.assertEqual(payload_before, plan_payload(enriched_plan))
            self.assertEqual("ADVISORY_GAPS", enriched_plan["readiness_assessment"]["status"])
            doc = render_plan_document(repo, enriched_plan, policy=policy)
            self.assertIn("## Existing codebase reuse candidates", doc)
            self.assertIn("## Architecture & spec readiness advisories", doc)
            self.assertIn("Reuse candidates:", approval_brief(enriched_plan))

    def test_kmp_common_main_purity_gate(self):
        from _modules import check_kmp_common_main_purity
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            common_file = repo / "shared/src/commonMain/kotlin/com/example/shared/SharedLogic.kt"
            common_file.parent.mkdir(parents=True)
            common_file.write_text(
                "package com.example.shared\n// import android.os.Bundle\nimport kotlinx.coroutines.flow.Flow\nclass SharedLogic\n",
                encoding="utf-8",
            )
            ok, msg = check_kmp_common_main_purity(repo, ["shared/src/commonMain/kotlin/com/example/shared/SharedLogic.kt"])
            self.assertTrue(ok, msg)

            common_file.write_text(
                "package com.example.shared\nimport android.content.Context\nclass SharedLogic\n",
                encoding="utf-8",
            )
            ok2, violations = check_kmp_common_main_purity(repo, ["shared/src/commonMain/kotlin/com/example/shared/SharedLogic.kt"])
            self.assertFalse(ok2)
            self.assertTrue(any("android.content.Context" in v for v in violations))

    def test_clean_layer_ui_to_data_source_bypass_detection(self):
        import architecture_drift
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            ui_rel = "app/src/main/kotlin/com/example/ui/CheckoutScreen.kt"
            ui_file = repo / ui_rel
            ui_file.parent.mkdir(parents=True)
            ui_content = (
                "package com.example.ui\nimport androidx.compose.runtime.Composable\nimport androidx.room.Dao\n@Composable\nfun CheckoutScreen() {}\n"
            )
            ui_file.write_text(ui_content, encoding="utf-8")
            contract = {
                "mode": "PRESERVE",
                "source_family_id": "COMPOSE_MVVM_UDF",
                "source_dimensions": {
                    "ui_toolkit": "compose",
                    "state_holder_base": "ViewModel",
                    "state_stream": "StateFlow",
                },
            }
            with patch("architecture_drift._baseline_reader", return_value=lambda rel: ""):
                ok, reason, violations = architecture_drift.check_architecture_drift(repo, contract, task_id="t-layer", task_changes=[ui_rel])
                self.assertFalse(ok)
                self.assertIn("UI_TO_DATA_SOURCE_BYPASS", reason)
                self.assertTrue(any("UI_TO_DATA_SOURCE_BYPASS" in v for v in violations))

            with patch("architecture_drift._baseline_reader", return_value=lambda rel: ui_content):
                ok_base, _, _ = architecture_drift.check_architecture_drift(repo, contract, task_id="t-layer", task_changes=[ui_rel])
                self.assertTrue(ok_base)

    def test_developer_instruction_rationale_and_alternatives_rejected(self):
        import generate_project_context
        import task_context
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            (repo / "app").mkdir()
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            target = repo / "app/src/main/kotlin/com/example/CheckoutViewModel.kt"
            target.parent.mkdir(parents=True)
            target.write_text("package com.example\nclass CheckoutViewModel {\n    fun submit() {}\n}\n", encoding="utf-8")

            rc = generate_project_context.main([
                "instruct",
                "Preserve callback bridge in Checkout",
                "--repo", str(repo),
                "--scope", "GLOBAL",
                "--source", "conversation",
                "--proof-reference", "keep callback bridge",
                "--strength", "REQUIREMENT",
                "--rationale", "Legacy payment SDK requires main-thread callback registration",
                "--alternatives-rejected", "CallbackFlow wrapper rejected due to SDK re-entrancy bug",
                "--json",
            ])
            self.assertEqual(0, rc)

            resolved = task_context.resolve_task_context(repo, file="app/src/main/kotlin/com/example/CheckoutViewModel.kt")
            self.assertEqual("RESOLVED", resolved["status"])
            insts = resolved["developer_instructions"]
            self.assertEqual(1, len(insts))
            self.assertEqual("Legacy payment SDK requires main-thread callback registration", insts[0]["rationale"])
            self.assertEqual("CallbackFlow wrapper rejected due to SDK re-entrancy bug", insts[0]["alternatives_rejected"])

    def test_swift_graph_and_task_context_resolution(self):
        from _graph_core import GraphEngine
        import task_context
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "settings.gradle.kts").write_text('include(":shared")\n', encoding="utf-8")
            swift_rel = "iosApp/iosApp/CheckoutViewModel.swift"
            swift_file = repo / swift_rel
            swift_file.parent.mkdir(parents=True)
            swift_file.write_text(
                "import SwiftUI\n@MainActor\nfinal class CheckoutViewModel: ObservableObject {\n    func pay() {}\n}\nstruct CheckoutView: View {\n    var body: some View { EmptyView() }\n}\n",
                encoding="utf-8",
            )
            engine = GraphEngine(repo)
            engine.sync()
            res = engine.find_symbol("CheckoutViewModel")
            vm_matches = [m for m in res["matches"] if m["name"] == "CheckoutViewModel"]
            self.assertEqual(1, len(vm_matches))
            self.assertEqual(swift_rel, vm_matches[0]["file_path"])
            self.assertEqual("VIEW_MODEL", vm_matches[0]["kind"])

            resolved = task_context.resolve_task_context(repo, file=swift_rel)
            self.assertEqual("RESOLVED", resolved["status"])
            self.assertEqual(swift_rel, resolved["target"]["path"])

    def test_kmp_cross_source_set_purity_and_expect_actual_signatures(self):
        from _modules import check_kmp_common_main_purity, check_kmp_expect_actual_pairs
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            # 1. Cross-source-set purity: platform.* in commonMain, android.* in iosMain, platform.* in androidMain
            common_f = repo / "shared/src/commonMain/kotlin/Common.kt"
            ios_f = repo / "shared/src/iosMain/kotlin/Ios.kt"
            android_f = repo / "shared/src/androidMain/kotlin/Android.kt"
            for f in (common_f, ios_f, android_f):
                f.parent.mkdir(parents=True, exist_ok=True)

            common_f.write_text("package shared\nimport platform.UIKit.UIDevice\n", encoding="utf-8")
            ios_f.write_text("package shared\nimport android.os.Bundle\n", encoding="utf-8")
            android_f.write_text("package shared\nimport kotlinx.cinterop.ExperimentalForeignApi\n", encoding="utf-8")

            ok, violations = check_kmp_common_main_purity(
                repo,
                [
                    "shared/src/commonMain/kotlin/Common.kt",
                    "shared/src/iosMain/kotlin/Ios.kt",
                    "shared/src/androidMain/kotlin/Android.kt",
                ],
            )
            self.assertFalse(ok)
            self.assertEqual(3, len(violations), violations)

            # Valid platform imports in their respective source sets
            common_f.write_text(
                "package shared\nexpect class PlatformUUID\nexpect fun formatPrice(amount: Double, currency: String): String\n",
                encoding="utf-8",
            )
            ios_f.write_text(
                "package shared\nimport platform.Foundation.NSUUID\nactual typealias PlatformUUID = NSUUID\n"
                "actual fun formatPrice(amount: Double): String = \"$amount\"\n",
                encoding="utf-8",
            )
            android_f.write_text(
                "package shared\nimport java.util.UUID\nactual typealias PlatformUUID = UUID\n"
                "actual fun formatPrice(amount: Double, currency: String): String = \"$amount $currency\"\n",
                encoding="utf-8",
            )
            ok_pure, pure_violations = check_kmp_common_main_purity(
                repo,
                [
                    "shared/src/commonMain/kotlin/Common.kt",
                    "shared/src/iosMain/kotlin/Ios.kt",
                    "shared/src/androidMain/kotlin/Android.kt",
                ],
            )
            self.assertTrue(ok_pure, pure_violations)

            # 2. Expect/Actual arity mismatch on iosMain (1 param vs 2 params)
            ok_ea, msg_ea = check_kmp_expect_actual_pairs(repo, ["shared/src/commonMain/kotlin/Common.kt"])
            self.assertFalse(ok_ea)
            self.assertIn("expected fun formatPrice/2, found fun formatPrice/1", msg_ea)

            # Fix iosMain via appleMain intermediate hierarchy + matching arity + nested generics & quoted default param comma
            common_f.write_text(
                "package shared\nexpect class PlatformUUID\n"
                'expect fun formatPrice(amount: Double, currency: String = ", "): String\n'
                '@Deprecated("old", ReplaceWith("sortedCustom()"))\n'
                "expect fun <T : Comparable<T>> List<T>.sortedCustom(): List<T>\n"
                "expect fun Map<String, List<Int>>.flattenValues(): List<Int>\n",
                encoding="utf-8",
            )
            android_f.write_text(
                "package shared\nimport java.util.UUID\nactual typealias PlatformUUID = UUID\n"
                'actual fun formatPrice(amount: Double, currency: String): String = "$amount $currency"\n'
                "actual fun <T : Comparable<T>> List<T>.sortedCustom(): List<T> = this.sorted()\n"
                "actual fun Map<String, List<Int>>.flattenValues(): List<Int> = values.flatten()\n",
                encoding="utf-8",
            )
            ios_f.unlink()
            apple_f = repo / "shared/src/appleMain/kotlin/Apple.kt"
            apple_f.parent.mkdir(parents=True, exist_ok=True)
            apple_f.write_text(
                "package shared\nimport platform.Foundation.NSUUID\nactual typealias PlatformUUID = NSUUID\n"
                'actual fun formatPrice(amount: Double, currency: String): String = "$amount $currency"\n'
                "actual fun <T : Comparable<T>> List<T>.sortedCustom(): List<T> = this.sorted()\n"
                "actual fun Map<String, List<Int>>.flattenValues(): List<Int> = values.flatten()\n",
                encoding="utf-8",
            )
            ok_ea2, msg_ea2 = check_kmp_expect_actual_pairs(repo, ["shared/src/commonMain/kotlin/Common.kt"])
            self.assertTrue(ok_ea2, msg_ea2)

    def test_kmp_sqldelight_graphql_swift_classification_and_swift_lint(self):
        import change_classifier
        import fast_kt_lint
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            sq_rel = "shared/src/commonMain/sqldelight/com/example/User.sq"
            sqm_rel = "shared/src/commonMain/sqldelight/migrations/1.sqm"
            gql_rel = "shared/src/commonMain/graphql/GetUser.graphql"
            swift_rel = "iosApp/iosApp/PaywallView.swift"
            swift_clean_rel = "iosApp/iosApp/CleanCommentView.swift"
            swift_test_rel = "iosApp/iosAppTests/PaywallTests.swift"
            for rel, content in (
                (sq_rel, "CREATE TABLE userEntity (id INTEGER NOT NULL PRIMARY KEY, name TEXT NOT NULL);\n"),
                (sqm_rel, "ALTER TABLE userEntity ADD COLUMN email TEXT;\n"),
                (gql_rel, "query GetUser($id: ID!) { user(id: $id) { id name } }\n"),
                (
                    swift_rel,
                    'import SwiftUI\nimport StoreKit\nstruct PaywallView: View {\n'
                    '    let apiUrl = "http://insecure.example.com/pay"\n'
                    '    var body: some View { Text("Pay") }\n'
                    '    func buy() { fatalError("TODO: implement StoreKit purchase") }\n'
                    '}\n',
                ),
                (
                    swift_clean_rel,
                    'import SwiftUI\nstruct CleanCommentView: View {\n'
                    '    let secureUrl = "https://api.example.com" // legacy: "http://old.example.com" fatalError("TODO")\n'
                    '    var body: some View { Text("OK") }\n'
                    '}\n',
                ),
                (
                    swift_test_rel,
                    'import XCTest\nfinal class PaywallTests: XCTestCase {\n'
                    '    func testUrl() { let u = "http://insecure.example.com/test" }\n'
                    '}\n',
                ),
            ):
                p = repo / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")

            res = change_classifier.classify(
                repo,
                task_changes=[{"path": sq_rel}, {"path": sqm_rel}, {"path": gql_rel}, {"path": swift_rel}],
                candidate_paths=[sq_rel, sqm_rel, gql_rel, swift_rel],
                progress=False,
            )
            surfaces = set(res.get("surfaces") or [])
            self.assertIn("PERSISTENCE", surfaces)
            self.assertIn("ROOM_SCHEMA", surfaces)
            self.assertIn("NETWORK", surfaces)
            self.assertIn("COMPOSE_UI", surfaces)
            self.assertIn("BILLING", surfaces)

            issues = fast_kt_lint.lint_swift_file(repo / swift_rel)
            issue_types = {iss["type"] for iss in issues}
            self.assertIn("INSECURE_CLEARTEXT_TRAFFIC", issue_types)
            self.assertIn("UNIMPLEMENTED_STUB", issue_types)

            clean_issues = fast_kt_lint.lint_swift_file(repo / swift_clean_rel)
            self.assertEqual([], clean_issues)

            test_issues = fast_kt_lint.lint_swift_file(repo / swift_test_rel)
            self.assertEqual([], test_issues)

    def test_macos_ios_compile_test_and_simulator_commands(self):
        import _variants
        import mutation_guard
        import run_device
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "settings.gradle.kts").write_text('include(":composeApp", ":shared")\n', encoding="utf-8")
            (repo / "shared/src/commonMain/kotlin").mkdir(parents=True)
            (repo / "shared/src/iosMain/kotlin").mkdir(parents=True)
            (repo / "shared/build.gradle.kts").write_text(
                'plugins { kotlin("multiplatform") }\nkotlin { iosArm64(); iosSimulatorArm64() }\n',
                encoding="utf-8",
            )
            (repo / "iosApp/iosApp.xcodeproj").mkdir(parents=True)

            # 1. iOS compile task resolution
            task_str, _note = _variants.resolve_ios_compile_task(repo)
            self.assertTrue(task_str.startswith(":shared:compileKotlinIos"), task_str)

            # 2. Aggregate KMP allTests XML report discovery
            xml_report = repo / "shared/build/test-results/iosSimulatorArm64Test/TEST-SharedIosTest.xml"
            xml_report.parent.mkdir(parents=True)
            xml_report.write_text(
                '<testsuite tests="2" failures="0" skipped="0"><testcase classname="SharedIosTest" name="testOne"/></testsuite>',
                encoding="utf-8",
            )
            self.assertEqual([xml_report], run_tests_gate.report_paths(repo, ":shared:allTests"))
            self.assertEqual(2, run_tests_gate.collect_test_summary(repo, ":shared:allTests")["executed"])

            # 3. Xcode project discovery
            flag, xc_path, scheme = run_device._discover_ios_xcode_project(repo)
            self.assertEqual("-project", flag)
            self.assertEqual("iosApp", scheme)
            self.assertIsNotNone(xc_path)

            # 4. Mutation guard allowlisting for macOS Xcode / Simulator commands & Swift production code
            self.assertTrue(mutation_guard._is_production_code("iosApp/iosApp/ContentView.swift"))
            self.assertFalse(mutation_guard._is_production_code("iosApp/iosAppTests/ContentViewTests.swift"))
            for ro_cmd in (
                "xcrun simctl list devices available -j",
                "xcodebuild -version",
                "xcodebuild -list -project iosApp/iosApp.xcodeproj",
                "xcodebuild -showdestinations -project iosApp/iosApp.xcodeproj -scheme iosApp",
                "swift --version",
                "python .agents/harness.py device ios-status",
                "python .agents/harness.py compile --ios",
            ):
                allowed, reason = mutation_guard.command_allowed(repo, ro_cmd)
                self.assertTrue(allowed, f"{ro_cmd}: {reason}")

    def test_egm_expanded_reuse_path_grounding_and_phase_dag(self):
        from _graph_core import GraphEngine
        from _workflow.planning import (
            _check_phase_module_dag,
            _discover_reuse_candidates,
            _evaluate_plan_readiness,
        )
        import workflow
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "settings.gradle.kts").write_text('include(":app", ":core:network")\n', encoding="utf-8")
            (repo / "app").mkdir(parents=True)
            (repo / "app/build.gradle.kts").write_text(
                'plugins { id("com.android.application") }\ndependencies { implementation(project(":core:network")) }\n',
                encoding="utf-8",
            )
            (repo / "core/network").mkdir(parents=True)
            (repo / "core/network/build.gradle.kts").write_text('plugins { id("com.android.library") }\n', encoding="utf-8")

            calc_file = repo / "core/network/src/main/kotlin/com/example/core/PriceCalculator.kt"
            calc_file.parent.mkdir(parents=True, exist_ok=True)
            calc_file.write_text("package com.example.core\nclass PriceCalculator {\n    fun calculate(): Int = 42\n}\n", encoding="utf-8")

            fmt_file = repo / "core/network/src/main/kotlin/com/example/core/CurrencyFormatter.kt"
            fmt_file.write_text("package com.example.core\nclass CurrencyFormatter {\n    fun format(): String = \"\"\n}\n", encoding="utf-8")

            engine = GraphEngine(repo)
            engine.sync()

            expected = [
                "app/src/main/kotlin/com/example/PriceCalculator.kt",
                "app/src/main/kotlin/com/example/AmountFormatter.kt",
            ]
            candidates = _discover_reuse_candidates(repo, expected)
            exact_matches = [c for c in candidates if c.get("exact_symbol_match")]
            role_matches = [c for c in candidates if not c.get("exact_symbol_match")]
            self.assertEqual(1, len(exact_matches))
            self.assertEqual("PriceCalculator", exact_matches[0]["symbol"])
            self.assertTrue(any(c["symbol"] == "CurrencyFormatter" for c in role_matches))

            # Inverted multi-phase module DAG order (:app in p1 before :core:network in p2)
            inverted_phases = [
                {"id": "p1", "title": "Update UI", "expected_files": ["app/src/main/kotlin/com/example/PriceCalculator.kt"]},
                {"id": "p2", "title": "Update Core", "expected_files": ["core/network/src/main/kotlin/com/example/core/PriceCalculator.kt"]},
            ]
            dag_warnings = _check_phase_module_dag(repo, inverted_phases)
            self.assertEqual(1, len(dag_warnings))
            self.assertIn("modifies downstream module ':app' before later phase 'p2'", dag_warnings[0])

            # Correct upstream-first phase order (:core:network in p1 before :app in p2)
            valid_phases = [
                {"id": "p1", "title": "Update Core", "expected_files": ["core/network/src/main/kotlin/com/example/core/PriceCalculator.kt"]},
                {"id": "p2", "title": "Update UI", "expected_files": ["app/src/main/kotlin/com/example/PriceCalculator.kt"]},
            ]
            self.assertEqual([], _check_phase_module_dag(repo, valid_phases))

            plan = {
                "schema_version": 2,
                "task_id": "t-egm-plan",
                "task_kind": "FEATURE",
                "planning_depth": "ARCHITECTURAL",
                "requested_outcome": "Refactor pricing and currency formatting",
                "approach": "Consolidate pricing calculation",
                "expected_files": expected,
                "expected_surfaces": ["BUSINESS_LOGIC", "ROOM_SCHEMA"],
                "risks": [],
                "constraints": [],
                "phases": inverted_phases,
                "reuse_candidates": candidates,
            }
            policy = {"risk_tier": "T3_HIGH", "gates": ["preflight", "unit_tests"], "reviewers": ["bug-test-reviewer-agent"]}
            readiness = _evaluate_plan_readiness(plan, policy, repo=repo)
            self.assertEqual("ADVISORY_GAPS", readiness["status"])
            self.assertEqual(1, len(readiness["path_grounding_warnings"]))
            self.assertIn("PATH_GROUNDING_WARNING", readiness["path_grounding_warnings"][0])
            self.assertEqual(1, len(readiness["phase_dag_warnings"]))
            self.assertTrue(any("PHASE_MODULE_DAG_ORDER" in adv for adv in readiness["advisories"]))
            self.assertTrue(any("ROOM_SCHEMA" in adv for adv in readiness["advisories"]))

            # Test workflow.py plan-check CLI
            tdir = repo / ".agents/state/tasks/t-egm-plan"
            tdir.mkdir(parents=True, exist_ok=True)
            plan["readiness_assessment"] = readiness
            (tdir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parent / "workflow.py"), "plan-check", "--repo", str(repo), "--task-id", "t-egm-plan", "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            check_out = json.loads(proc.stdout)
            self.assertEqual("ADVISORY_GAPS", check_out["readiness_status"])
            self.assertEqual("T3_HIGH", check_out["risk_tier"])
            self.assertEqual(1, len(check_out["path_grounding_warnings"]))
            self.assertEqual(1, len(check_out["phase_dag_warnings"]))

            # Multi-file starvation edge case: 5 existing *Formatter classes should not starve
            # exact_symbol_match detection on the 2nd planned file (PriceCalculator.kt).
            for idx in range(5):
                extra_fmt = repo / f"core/network/src/main/kotlin/com/example/core/Extra{idx}Formatter.kt"
                extra_fmt.write_text(f"package com.example.core\nclass Extra{idx}Formatter\n", encoding="utf-8")
            engine.sync()
            ordered_expected = [
                "app/src/main/kotlin/com/example/AmountFormatter.kt",
                "app/src/main/kotlin/com/example/PriceCalculator.kt",
            ]
            multi_cands = _discover_reuse_candidates(repo, ordered_expected)
            self.assertTrue(
                any(c.get("exact_symbol_match") and c.get("symbol") == "PriceCalculator" for c in multi_cands),
                f"Expected exact_symbol_match for PriceCalculator in {multi_cands}",
            )

    def test_egm_living_context_drift_and_self_healing_suggestions(self):
        from _graph_core import GraphEngine
        from project_context import check_living_context_drift
        import generate_project_context
        import mutation_guard
        from doctor.engine import HarnessDoctor
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "settings.gradle.kts").write_text('include(":app", ":core:network")\n', encoding="utf-8")
            (repo / "app").mkdir(parents=True)
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            (repo / "core/network").mkdir(parents=True)
            (repo / "core/network/build.gradle.kts").write_text('plugins { id("com.android.library") }\n', encoding="utf-8")

            moved_file = repo / "core/network/src/main/kotlin/com/example/ApiClient.kt"
            moved_file.parent.mkdir(parents=True, exist_ok=True)
            moved_file.write_text("package com.example\nclass ApiClient\n", encoding="utf-8")
            manifest_file = repo / "app/src/main/AndroidManifest.xml"
            manifest_file.parent.mkdir(parents=True, exist_ok=True)
            manifest_file.write_text("<manifest/>\n", encoding="utf-8")

            engine = GraphEngine(repo)
            engine.sync()

            ctx_dir = repo / ".agents/project-context"
            ctx_dir.mkdir(parents=True, exist_ok=True)
            (ctx_dir / "project-notes.md").write_text(
                "# Project Notes\n\n## Domain Conventions & Context\n"
                "- Old client lived at `app/src/main/kotlin/com/example/ApiClient.kt` inside `:legacy:sync`.\n"
                "- Active client is `core/network/src/main/kotlin/com/example/ApiClient.kt`.\n"
                "- Build debug APK with `:app:assembleDebug` or `:core:network:testDebugUnitTest`.\n"
                "- External docs: https://github.com/example/repo/blob/main/docs/architecture.md and `src/main/AndroidManifest.xml`.\n",
                encoding="utf-8",
            )
            (ctx_dir / "developer-instructions.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "instructions": [
                        {
                            "id": "inst-stale-1",
                            "status": "ACTIVE",
                            "scope": "module::legacy:sync",
                            "text": "Keep retry interceptor in app/src/main/kotlin/com/example/ApiClient.kt (see https://github.com/org/repo/blob/main/README.md)",
                        }
                    ],
                }),
                encoding="utf-8",
            )

            drift = check_living_context_drift(repo)
            self.assertEqual("DRIFT_DETECTED", drift["status"])
            self.assertEqual(2, drift["stale_notes_count"], f"Unexpected stale notes: {drift['stale_notes']}")
            self.assertEqual(2, drift["stale_instructions_count"], f"Unexpected stale instructions: {drift['stale_instructions']}")
            file_note = next(n for n in drift["stale_notes"] if n["kind"] == "STALE_NOTE_FILE_REF")
            self.assertEqual("core/network/src/main/kotlin/com/example/ApiClient.kt", file_note["suggested_replacement"])

            # Verify CLI drift-report --json
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parent / "generate_project_context.py"), "drift-report", "--repo", str(repo), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            cli_data = json.loads(proc.stdout)
            self.assertEqual("DRIFT_DETECTED", cli_data["status"])

            # Verify Doctor surfaces Living Context Drift warning
            generate_project_context.main(["generate", "--repo", str(repo)])
            doc = HarnessDoctor(repo, run_selftest=False)
            doc.is_raw_kit = False
            doc.check_project_context()
            drift_chk = next(r for r in doc.results if r.name == "Living Context Drift")
            self.assertEqual("WARN", drift_chk.status)

            # Verify mutation_guard allows read-only plan-check, drift-report, and context note without an active task
            kit_root = Path(__file__).resolve().parents[2]
            for cmd in (
                "python .agents/harness.py task plan-check --json",
                "python .agents/harness.py context drift-report --json",
                'python .agents/harness.py context note "Test note"',
            ):
                allowed, reason = mutation_guard.command_allowed(kit_root, cmd)
                self.assertTrue(allowed, f"{cmd} should be allowed: {reason}")

    def test_pass2_edge_cases_finding_routing_arch_drift_and_kmp_lint(self):
        import argparse
        import _modules
        import architecture_drift
        import fast_kt_lint
        import review_package
        import workflow

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)

            # 1. Gradle triple-quoted string comment stripping
            raw_gradle = 'val url = """https://example.com//not-a-comment""" // trailing comment\n'
            stripped_gradle = _modules.strip_gradle_comments_preserving_strings(raw_gradle)
            self.assertIn('"""https://example.com//not-a-comment"""', stripped_gradle)
            self.assertNotIn("trailing comment", stripped_gradle)

            # 2. Specialist reviewer routing from short finding IDs & auto-resolved reviewer in record-finding-validation
            tdir = repo / ".agents/state/tasks/t-pass2"
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / "plan.json").write_text(json.dumps({"task_id": "t-pass2", "expected_files": []}), encoding="utf-8")
            (tdir / "reviews-security-privacy-reviewer-agent.json").write_text(
                json.dumps({
                    "reviewer": "security-privacy-reviewer-agent",
                    "findings": [{"id": "F-CUSTOM-99", "severity": "HIGH", "summary": "Custom finding"}],
                }),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                repo=str(repo),
                task_id="t-pass2",
                finding_id="F-CUSTOM-99",
                status="CONFIRMED",
                reason="Resolved in commit",
                evidence_reference="commit:abc1234",
            )
            res = workflow.record_finding_validation(args)
            self.assertEqual("t-pass2", res.get("task_id"))
            val_payload = json.loads((tdir / "finding-validations.json").read_text(encoding="utf-8"))
            self.assertEqual("security-privacy-reviewer-agent", val_payload["validations"][0].get("reviewer"))

            # Short prefix routing without explicit reviewer field
            (tdir / "finding-validations.json").write_text(
                json.dumps({
                    "task_id": "t-pass2",
                    "validations": [
                        {
                            "finding_id": "F-SEC-1",
                            "status": "FALSE_POSITIVE",
                            "reason": "Encrypted token storage",
                        }
                    ],
                }),
                encoding="utf-8",
            )
            sec_lines = review_package._scoped_finding_validation_lines(repo, "t-pass2", "security-perf-reviewer-agent")
            self.assertEqual(2, len(sec_lines))
            self.assertTrue(any("F-SEC-1" in line for line in sec_lines))
            ui_lines = review_package._scoped_finding_validation_lines(repo, "t-pass2", "compose-ui-reviewer-agent")
            self.assertEqual([], ui_lines)

            # 3. Architecture drift ignores commented-out DAO imports and SearchQueries UI state properties
            ui_file = repo / "feature/search/src/commonMain/kotlin/com/example/search/SearchViewModel.kt"
            ui_file.parent.mkdir(parents=True, exist_ok=True)
            ui_file.write_text(
                "package com.example.search\n"
                "// import com.example.data.local.dao.UserDao\n"
                "/* import app.cash.sqldelight.db.SqlDriver */\n"
                "class SearchViewModel(\n"
                "    private val searchQueries: SearchQueries,\n"
                ") {\n"
                "    val recentQueries: List<String> = emptyList()\n"
                "}\n",
                encoding="utf-8",
            )
            drift_findings = architecture_drift._detect_ui_data_source_bypass(
                "feature/search/src/commonMain/kotlin/com/example/search/SearchViewModel.kt",
                ui_file.read_text(encoding="utf-8"),
            )
            self.assertIsNone(drift_findings, f"Unexpected drift findings: {drift_findings}")

            # 4. KMP @Preview discovery in parallel src/androidMain/... for a commonMain screen
            common_screen = repo / "shared/src/commonMain/kotlin/com/example/ui/ProfileScreen.kt"
            common_screen.parent.mkdir(parents=True, exist_ok=True)
            common_screen.write_text(
                "package com.example.ui\n"
                "import androidx.compose.runtime.Composable\n"
                "@Composable\n"
                "fun ProfileScreen() {\n"
                "    val a = 1\n"
                "    val b = 2\n"
                "    val c = 3\n"
                "    val d = 4\n"
                "}\n",
                encoding="utf-8",
            )
            android_preview = repo / "shared/src/androidMain/kotlin/com/example/ui/ProfileScreenPreview.kt"
            android_preview.parent.mkdir(parents=True, exist_ok=True)
            android_preview.write_text(
                "package com.example.ui\n"
                "import androidx.compose.ui.tooling.preview.Preview\n"
                "@Preview\n"
                "fun ProfileScreenPreview() {}\n",
                encoding="utf-8",
            )
            kt_violations = fast_kt_lint.lint_file(common_screen)
            self.assertFalse(
                any(v.rule == "MISSING_PREVIEW" for v in kt_violations),
                f"Expected no MISSING_PREVIEW when androidMain preview exists, got {kt_violations}",
            )

            # 5. Swift triple-quoted string ignores http:// cleartext warning
            swift_file = repo / "iosApp/iosApp/DocSample.swift"
            swift_file.parent.mkdir(parents=True, exist_ok=True)
            swift_file.write_text(
                "import Foundation\n"
                'let sampleDoc = """\n'
                "Example legacy endpoint: http://legacy.example.com/api\n"
                '"""\n',
                encoding="utf-8",
            )
            swift_violations = fast_kt_lint.lint_swift_file(swift_file)
            self.assertFalse(
                any(v.rule == "CLEARTEXT_HTTP" for v in swift_violations),
                f"Expected no CLEARTEXT_HTTP inside Swift triple-quoted string, got {swift_violations}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)


