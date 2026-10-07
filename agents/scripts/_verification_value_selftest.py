"""Contract tests for optional verification value features (no real device calls)."""
from __future__ import annotations

import copy
import sys
import subprocess
import json
import io
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, canonical_sha256
from evidence_store import EvidenceStore
from verification_contract import validate_contract, coverage_report, bind_evidence
from journey_runner import execute_journey, validate_journey
from task_metrics import record_operation, metrics_report


def contract(method="test", required=True):
    return {"schema_version": 1, "criteria": [
        {"id": "refresh", "expected": "Refresh shows updated data", "method": method,
         "required": required}], "journeys": []}


class VerificationContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvidenceStore(self.root / ".agents/state")
        self.plan = {"task_id": "task", "plan_sha256": "p", "verification_contract": contract()}
        self.current = {"run_id": "run", "delivery_snapshot_sha256": "snapshot", "change_set_sha256": "change"}

    def tearDown(self):
        self.temp.cleanup()

    def write_tests(self, status="PASS", outcomes=None):
        self.store.write(snapshot="snapshot", run_id="run", name="unit_tests", producer="run_tests_gate",
                         harness_version="1", change_set="change", status=status,
                         evidence={"test_outcomes": outcomes or {"Tests.refresh": "PASS"}}, allow_pass_retry=True)

    def test_duplicate_and_unknown_contracts_rejected(self):
        value = contract()
        value["criteria"] *= 2
        with self.assertRaises(ValidationError):
            validate_contract(value)
        value = contract()
        value["schema_version"] = 99
        with self.assertRaises(ValidationError):
            validate_contract(value)

    def test_legacy_disabled_does_not_read_evidence(self):
        with patch.object(self.store, "read", side_effect=AssertionError("unexpected read")):
            report = coverage_report({}, self.current, self.store)
        self.assertEqual([], report["criteria"])
        self.assertEqual([], report["blocking"])

    def test_exact_case_execution_required(self):
        self.write_tests(outcomes={"Other.refresh": "PASS"})
        with self.assertRaises(ValidationError):
            bind_evidence(self.plan, self.current, self.store, "refresh", "unit_tests", "Tests.refresh")

    def test_bound_case_and_latest_failure(self):
        self.write_tests()
        bind_evidence(self.plan, self.current, self.store, "refresh", "unit_tests", "Tests.refresh")
        report = coverage_report(self.plan, self.current, self.store)
        self.assertEqual("VERIFIED", report["criteria"][0]["status"])
        self.write_tests("FAIL")
        report = coverage_report(self.plan, self.current, self.store)
        self.assertTrue(report["blocking"])
        self.assertNotEqual("VERIFIED", report["criteria"][0]["status"])

    def test_changed_contract_invalidates_association(self):
        self.write_tests()
        bind_evidence(self.plan, self.current, self.store, "refresh", "unit_tests", "Tests.refresh")
        self.plan["verification_contract"]["criteria"][0]["expected"] = "A different behavior"
        self.assertEqual("STALE", coverage_report(self.plan, self.current, self.store)["criteria"][0]["status"])

    def test_failed_skipped_and_wrong_producer_cannot_bind(self):
        for outcome in ("FAIL", "SKIPPED"):
            self.write_tests(outcomes={"Tests.refresh": outcome})
            with self.assertRaises(ValidationError):
                bind_evidence(self.plan, self.current, self.store, "refresh", "unit_tests", "Tests.refresh")

    def test_missing_required_blocks_advisory_does_not(self):
        self.assertTrue(coverage_report(self.plan, self.current, self.store)["blocking"])
        self.plan["verification_contract"] = contract(required=False)
        self.assertFalse(coverage_report(self.plan, self.current, self.store)["blocking"])

    def test_optional_payload_is_hash_bound_without_changing_legacy(self):
        from plan_authority import plan_payload
        before = plan_payload({"task_id": "task"})
        self.assertNotIn("verification_contract", before)
        after = plan_payload(self.plan)
        self.assertIn("verification_contract", after)
        value = copy.deepcopy(self.plan)
        value["verification_contract"]["criteria"][0]["required"] = False
        self.assertNotEqual(canonical_sha256(after), canonical_sha256(plan_payload(value)))

    def test_manual_criterion_requires_explicit_identity(self):
        self.plan["verification_contract"] = contract("manual")
        evidence = {"task_id": "task", "plan_sha256": "p", "approval_source": "conversation", "proof_reference_sha256": "proof"}
        def write():
            self.store.write(snapshot="snapshot", run_id="run", name="device_signoff", producer="developer_approval",
                harness_version="1", change_set="change", status="PASS", evidence=evidence, allow_pass_retry=True)
        write()
        with self.assertRaises(ValidationError):
            bind_evidence(self.plan, self.current, self.store, "refresh", "device_signoff")
        evidence["criterion_ids"] = ["refresh"]
        write()
        bind_evidence(self.plan, self.current, self.store, "refresh", "device_signoff")
        self.assertFalse(coverage_report(self.plan, self.current, self.store)["blocking"])

    def test_review_boolean_cannot_replace_ingested_criterion_result(self):
        self.plan["verification_contract"] = contract("review")
        self.store.write(snapshot="snapshot", run_id="run", name="reviews", producer="review_orchestrator",
            harness_version="1", change_set="change", status="PASS", evidence={"reports": [{"reviewer": "bug-reviewer-agent",
                "verdict": "PASS", "independent_execution_verified": True, "criterion_results": {"refresh": "PASS"}}]})
        with self.assertRaises(ValidationError):
            bind_evidence(self.plan, self.current, self.store, "refresh", "reviews", "bug-reviewer-agent")

    def test_review_result_binding_rejects_tampered_aggregate(self):
        from review_orchestrator import save_ledger, result_file, dispatch_receipt_file
        from _vnext_common import atomic_write_json, sha256_file
        self.plan["verification_contract"] = contract("review")
        self.current["review_protocol_version"] = 2
        reviewer = "bug-reviewer-agent"
        directory = self.store.state_root / "tasks/task"
        package = self.store.run_dir("snapshot", "run") / "review-package.md"
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_text("Approved review fixture")
        package_sha = sha256_file(package)
        body = {"verdict": "PASS", "criterion_results": {"refresh": "PASS"}, "review_package_sha256": package_sha}
        digest = canonical_sha256(body)
        save_ledger(directory, "run", {"reviewers": {reviewer: {"state": "INGESTED", "result_sha256": digest, "execution_id_sha256": "execution"}}})
        identity = {"task_id": "task", "run_id": "run", "reviewer": reviewer}
        atomic_write_json(result_file(directory, "run", reviewer), {**identity, "result": body, "result_sha256": digest, "execution_id_sha256": "execution"})
        receipt = {**identity, "delivery_snapshot_sha256": "snapshot", "change_set_sha256": "change", "review_package_sha256": package_sha}
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        atomic_write_json(dispatch_receipt_file(directory, "run", reviewer), receipt)
        report = {"reviewer": reviewer, "verdict": "PASS", "independent_execution_verified": True,
                  "criterion_results": {"refresh": "PASS"}, "result_sha256": digest, "execution_id_sha256": "execution"}
        def write():
            self.store.write(snapshot="snapshot", run_id="run", name="reviews", producer="review_orchestrator",
                harness_version="1", change_set="change", status="PASS", evidence={"review_protocol_version": 2,
                    "package_sha256": package_sha, "reports": [report]}, allow_pass_retry=True)
        write()
        bind_evidence(self.plan, self.current, self.store, "refresh", "reviews", reviewer)
        self.assertFalse(coverage_report(self.plan, self.current, self.store)["blocking"])
        report["result_sha256"] = "tampered"
        write()
        self.assertTrue(coverage_report(self.plan, self.current, self.store)["blocking"])


def journey():
    return {"schema_version": 1, "id": "refresh-flow", "version": 1,
            "purpose": "Verify refresh", "criteria": ["refresh"], "module": ":app", "variant": "Debug",
            "application_id": "com.example", "prerequisites": "Open the refresh screen using a test account",
            "effects": ["ui_interaction"], "steps": [
                {"action": "assert_present", "selector": {"resource_id": "com.example:id/refresh"}, "timeout": 1}]}


class FakeTransport:
    def __init__(self, counts=(1,)):
        self.counts = iter(counts)
        self.actions = []

    def check_identity(self):
        return {"os": "35", "locale": "en-US"}

    def find(self, selector, timeout):
        return [object() for _ in range(next(self.counts, 1))]

    def act(self, action, node, value, timeout):
        self.actions.append(action)


class JourneyContracts(unittest.TestCase):
    def test_valid_assertion_and_ambiguous_selector(self):
        self.assertEqual("PASS", execute_journey(journey(), FakeTransport())["status"])
        result = execute_journey(journey(), FakeTransport((2,)))
        self.assertEqual("FAIL", result["status"])

    def test_invalid_late_step_causes_zero_actions(self):
        value = journey()
        value["steps"].insert(0, {"action": "tap", "selector": {"resource_id": "com.example:id/refresh"}})
        value["steps"].append({"action": "shell", "command": "rm -rf"})
        transport = FakeTransport()
        with self.assertRaises(ValidationError):
            execute_journey(value, transport)
        self.assertEqual([], transport.actions)

    def test_missing_hierarchy_is_environment_failure_not_negative_pass(self):
        value = journey()
        value["steps"][0]["action"] = "assert_absent"
        transport = FakeTransport()
        transport.find = lambda *args: (_ for _ in ()).throw(OSError("hierarchy unavailable"))
        self.assertEqual("ENV", execute_journey(value, transport)["status"])

    def test_identity_rechecks_user_after_initial_probe(self):
        from journey_runner import AdbTransport
        transport = AdbTransport("fixture", "com.example", [])
        transport.observed = {"os": "35", "locale": "en-US"}
        def fake_call(args, timeout=3):
            return "10\ntopResumedActivity u10 com.example/.MainActivity"
        transport.call = fake_call
        with self.assertRaises(OSError):
            transport.check_identity()

    def test_real_adb_hierarchy_trailer_is_accepted_without_accepting_malformed_xml(self):
        from journey_runner import AdbTransport
        from _adb_core import parse_ui_hierarchy
        xml = ('<?xml version="1.0"?><hierarchy rotation="0">'
               '<node resource-id="com.example:id/refresh" text="" content-desc="" '
               'enabled="true" bounds="[0,0][100,100]" /></hierarchy>')
        raw = xml + "UI hierchary dumped to: /dev/tty\n"
        transport = AdbTransport("fixture", "com.example", [])
        transport.check_identity = lambda: {"os": "35", "locale": "en-US"}
        transport.call = lambda *args, **kwargs: raw
        matches = transport.find({"resource_id": "com.example:id/refresh"}, 5)
        self.assertEqual(1, len(matches))
        self.assertEqual("com.example:id/refresh", matches[0].resource_id)
        self.assertEqual([], parse_ui_hierarchy(xml[:-len("</hierarchy>")] +
                                               "UI hierchary dumped to: /dev/tty\n"))
        self.assertEqual([], parse_ui_hierarchy(xml + "<hierarchy><node /></hierarchy>"))
        self.assertEqual([], parse_ui_hierarchy(xml + "unexpected trailing data"))

    def test_foreground_rejects_other_top_activity_and_work_profile(self):
        from journey_runner import AdbTransport
        transport = AdbTransport("fixture", "com.example", [])
        transport.observed = {"os": "35", "locale": "en-US"}
        for focus in ("mResumedActivity u0 com.example/.Main\ntopResumedActivity u0 com.other/.Main",
                      "topResumedActivity u10 com.example/.Main"):
            def fake_call(args, timeout=3):
                return "0\n" + focus
            transport.call = fake_call
            with self.assertRaises(OSError):
                transport.check_identity()
        focus = "topResumedActivity u0 com.example/.Main"
        self.assertEqual("35", transport.check_identity()["os"])

    def test_navigation_checkpoints_reduce_dumps_but_actions_read_fresh_targets(self):
        from journey_runner import AdbTransport
        value = journey()
        value["steps"] = [
            {"action": action, "selector": {"resource_id": "com.example:id/" + target}, "timeout": 5}
            for action, target in (("wait_present", "home"), ("tap", "calories"),
                ("assert_present", "container"), ("assert_present", "home"), ("tap", "home"),
                ("assert_present", "container"), ("assert_present", "calories"))]
        for ambiguous_target in (False, True):
            transport = AdbTransport("fixture", "com.example", [])
            transport.observed = {"os": "35", "locale": "en-US"}
            dumps, actions, probes = [], [], []
            def call(args, timeout=3):
                if args[0] == "shell":
                    probes.append(args)
                    return "0\ntopResumedActivity u0 com.example/.Main"
                dumps.append(len(actions))
                targets = ["home", "calories", "container"]
                # The assertion checkpoint sees Home; the subsequent tap must
                # notice that its target has become ambiguous on this screen.
                if ambiguous_target and len(dumps) == 4:
                    targets.remove("home")
                    # Return two replacements: neither is a uniquely verified tap target.
                    targets += ["home", "home"]
                return '<hierarchy>' + ''.join(
                    '<node resource-id="com.example:id/' + target + '" enabled="true" bounds="[0,0][100,100]" />'
                    for target in targets) + '</hierarchy>'
            transport.call = call
            transport.act = lambda *args: actions.append(args[0])
            result = execute_journey(value, transport)
            self.assertEqual("FAIL" if ambiguous_target else "PASS", result["status"])
            self.assertEqual([0, 0, 1, 1] if ambiguous_target else [0, 0, 1, 1, 2], dumps)
            self.assertEqual(1 if ambiguous_target else 2, len(actions))
            self.assertTrue(all(args == ["shell", "am get-current-user && dumpsys activity activities"] for args in probes))

    def test_checkpoint_missing_selector_discards_remaining_observations(self):
        value = journey()
        value["steps"] *= 2
        transport = FakeTransport()
        observations, finds = [], []
        transport.observe_present = lambda *args: observations.append(True) or [[], [object()]]
        def find(*args):
            finds.append(True)
            return [object()]
        transport.find = find
        self.assertEqual("PASS", execute_journey(value, transport)["status"])
        self.assertEqual(1, len(observations))
        self.assertEqual(2, len(finds))

    def test_batched_identity_fails_closed_for_disconnection_or_malformed_output(self):
        from journey_runner import AdbTransport
        transport = AdbTransport("fixture", "com.example", [])
        for output in ("", "unexpected header\n0\ntopResumedActivity u0 com.example/.Main",
                       "0\n", "0\ntopResumedActivity u0 com.other/.Main"):
            transport.call = lambda *args: output
            with self.assertRaises(OSError):
                transport.check_identity()
        transport.call = lambda *args: (_ for _ in ()).throw(OSError("disconnected"))
        with self.assertRaises(OSError):
            transport.check_identity()

    def test_action_requires_observable_assertion_and_effect(self):
        value = journey()
        value["steps"][0]["action"] = "tap"
        with self.assertRaises(ValidationError):
            validate_journey(value)
        value = journey()
        value["effects"] = []
        value["steps"].insert(0, {"action": "tap", "selector": {"resource_id": "com.example:id/refresh"}})
        with self.assertRaises(ValidationError):
            validate_journey(value)


class MetricsContracts(unittest.TestCase):
    def test_local_metrics_and_failed_write_do_not_raise(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            record_operation(repo, "task", "test", 2.0, 0)
            report = metrics_report(repo, "task")
            self.assertEqual(2.0, report["observed_execution_seconds"])
            self.assertEqual("UNAVAILABLE", report["tokens"])
            with patch("task_metrics.atomic_write_json", side_effect=OSError("disk full")):
                record_operation(repo, "task", "test", 1.0, 0)

    def test_report_missing_history_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            report = metrics_report(Path(temp), "task")
            self.assertEqual("UNAVAILABLE", report["observed_execution_seconds"])


class PublicWorkflowContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        for args in (("init", "-q"), ("config", "user.name", "Verification Fixture"),
                     ("config", "user.email", "fixture@example.invalid"), ("config", "core.autocrlf", "false")):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        (self.repo / ".git/info/exclude").write_text(".agents/\napp/build/\n")
        (self.repo / ".agents/state").mkdir(parents=True)
        (self.repo / ".agents/VERSION").write_text("1.1.19\n")
        (self.repo / "app").mkdir()
        (self.repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n')
        (self.repo / "settings.gradle.kts").write_text('include(":app")\n')
        (self.repo / "README.md").write_text("Original documentation\n")
        (self.repo / "criteria.json").write_text(json.dumps(contract()))
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True, capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, *args):
        import workflow
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = workflow.main([action, "--repo", str(self.repo), "--task-id", "feature", *args])
        self.assertEqual(0, code, (action, args))

    def start(self, opt_in=True, choice=False):
        if choice:
            value = contract("journey")
            value.update(journeys=[journey()], device_validation="manual_or_automatic")
            (self.repo / "criteria.json").write_text(json.dumps(value))
            subprocess.run(["git", "add", "criteria.json"], cwd=self.repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-qm", "complete walkthrough fixture"], cwd=self.repo, check=True, capture_output=True)
        extra = ["--verification-contract", "criteria.json"] if opt_in else []
        if choice:
            extra += ["--expected-modules", ":app"]
        self.call("draft", "--outcome", "Document refresh behavior", "--kind", "FEATURE", "--expected-files", "README.md", *extra)
        self.call("approve", "--source", "conversation", "--proof-reference", "approved fixture", "--enforcement-tier", "RULE_ENFORCED")
        (self.repo / "README.md").write_text("Updated refresh documentation\n")
        self.call("prepare-verification")
        from _vnext_common import read_json
        directory = self.repo / ".agents/state/tasks/feature"
        self.plan = read_json(directory / "plan.json")
        self.current = read_json(directory / "current-run.json")
        self.store = EvidenceStore(self.repo / ".agents/state")
        policy = read_json(Path(self.current["policy"]))
        for gate in policy["gates"]:
            if gate in ("preflight", "unit_tests"):
                self.store.write(snapshot=self.current["delivery_snapshot_sha256"], run_id=self.current["run_id"],
                                 name=gate, producer="preflight_check" if gate == "preflight" else "run_tests_gate",
                                 harness_version="1.1.19", change_set=self.current["change_set_sha256"], status="PASS",
                                 evidence={"executed": 1, "test_outcomes": {"Tests#refresh": "PASS"}})

    def install_choice_fixture(self):
        import hashlib
        from artifact_set import build_artifact_set
        apk = self.repo / "app/build/outputs/apk/debug/app-debug.apk"
        apk.parent.mkdir(parents=True, exist_ok=True)
        apk.write_bytes(b"immutable fixture APK")
        artifact_set = build_artifact_set(self.repo, ":app:assembleDebug", [apk], application_id="com.example")
        digest = artifact_set["artifact_set_sha256"]
        for name in ("assemble", "device_install", "device_launch"):
            self.store.write(snapshot=self.current["delivery_snapshot_sha256"], run_id=self.current["run_id"],
                name=name, producer="run_gradle_task" if name == "assemble" else "run_device",
                harness_version="1.1.19", change_set=self.current["change_set_sha256"], status="PASS",
                evidence={"artifact_set_sha256": digest, "serial_sha256": hashlib.sha256(b"fixture").hexdigest(),
                          "target_user": "0", "application_id": "com.example",
                          "install_reference": digest, "artifact_set": artifact_set}, allow_pass_retry=True)

    def device(self, *args, transport=None):
        import run_device
        from journey_runner import run_device_validation
        def execute(*values):
            return run_device_validation(*values, transport=transport or FakeTransport())
        with patch.object(run_device, "REPO", self.repo), patch("sys.argv", ["run_device.py", *args]), \
                patch("journey_runner.run_device_validation", side_effect=execute), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return run_device.main()

    def test_public_choice_after_install_auto_pass_completes_without_manual_signoff(self):
        self.start(choice=True)
        from workflow import resolve_next_action
        from final_verifier import verify_task
        self.assertNotEqual("DEVICE_SIGNOFF_REQUIRED", resolve_next_action(self.repo, "feature")["code"])
        self.install_choice_fixture()
        action = resolve_next_action(self.repo, "feature")
        self.assertEqual("DEVICE_SIGNOFF_REQUIRED", action["code"])
        self.assertEqual(["PASS", "FAIL", "AUTOMATIC"], action["accepted_responses"])
        self.assertEqual(1, len(action["walkthrough"]))
        self.assertEqual(0, self.device("validate-automatically", "--task-id", "feature", "--serial", "fixture",
                                      "--source", "conversation", "--proof-reference", "Run Automatically"))
        self.assertEqual("APPROVED", verify_task(self.repo, "feature")["status"], verify_task(self.repo, "feature").get("blocked_by"))
        self.assertEqual("COMPLETE_TASK", resolve_next_action(self.repo, "feature")["code"])
        with self.assertRaises(ValidationError):
            self.store.read(self.current["delivery_snapshot_sha256"], self.current["run_id"], "device_signoff")
        self.call("complete")

    def test_public_choice_manual_pass_completes_without_running_journey(self):
        self.start(choice=True)
        self.install_choice_fixture()
        from final_verifier import verify_task
        self.assertEqual(0, self.device("signoff", "--task-id", "feature", "--verdict", "PASS", "--source", "conversation",
                                      "--proof-reference", "I checked refresh manually", "--criterion-id", "refresh"))
        self.assertEqual("APPROVED", verify_task(self.repo, "feature")["status"], verify_task(self.repo, "feature").get("blocked_by"))
        with self.assertRaises(ValidationError):
            self.store.read(self.current["delivery_snapshot_sha256"], self.current["run_id"], "journey-refresh-flow")
        self.call("complete")

    def test_public_auto_environment_offers_manual_fallback_and_auto_failure_blocks(self):
        self.start(choice=True)
        self.install_choice_fixture()
        from workflow import resolve_next_action
        from final_verifier import verify_task
        disconnected = FakeTransport()
        disconnected.check_identity = lambda: (_ for _ in ()).throw(OSError("disconnected"))
        args = ("validate-automatically", "--task-id", "feature", "--serial", "fixture", "--source", "conversation", "--proof-reference", "Run Automatically")
        self.assertEqual(30, self.device(*args, transport=disconnected))
        self.assertEqual("BLOCKED", verify_task(self.repo, "feature")["status"])
        self.assertEqual("DEVICE_SIGNOFF_REQUIRED", resolve_next_action(self.repo, "feature")["code"])
        self.assertEqual(0, self.device("signoff", "--task-id", "feature", "--source", "conversation", "--proof-reference", "Manual fallback passed", "--criterion-id", "refresh"))
        self.assertEqual("APPROVED", verify_task(self.repo, "feature")["status"])
        # A new automatic attempt must supersede the previous manual PASS before effects.
        self.assertEqual(1, self.device(*args, transport=FakeTransport((0,))))
        self.assertEqual("BLOCKED", verify_task(self.repo, "feature")["status"])
        self.assertEqual("RESUME_IMPLEMENTATION", resolve_next_action(self.repo, "feature")["code"])

    def test_auto_requires_selection_and_rejects_changed_source_attempt(self):
        self.start(choice=True)
        self.install_choice_fixture()
        args = ("validate-automatically", "--task-id", "feature", "--serial", "fixture")
        self.assertEqual(1, self.device(*args))
        self.assertEqual(0, self.device(*args, "--source", "conversation", "--proof-reference", "Run Automatically"))
        from final_verifier import verify_task
        self.install_choice_fixture()
        self.assertEqual("BLOCKED", verify_task(self.repo, "feature")["status"])

    def test_interrupted_auto_retry_cannot_reuse_previous_success(self):
        self.start(choice=True)
        self.install_choice_fixture()
        args = ("validate-automatically", "--task-id", "feature", "--serial", "fixture", "--source", "conversation", "--proof-reference", "Run Automatically")
        self.assertEqual(0, self.device(*args))
        interrupted = FakeTransport()
        def stop():
            record = self.store.read(self.current["delivery_snapshot_sha256"], self.current["run_id"], "device_validation_result")
            self.assertEqual("BLOCKED", record["status"])
            raise KeyboardInterrupt("interrupted replay fixture")
        interrupted.check_identity = stop
        with self.assertRaises(KeyboardInterrupt):
            self.device(*args, transport=interrupted)
        from final_verifier import verify_task
        self.assertEqual("BLOCKED", verify_task(self.repo, "feature")["status"])

    def test_manual_signoff_cannot_switch_mode_during_automatic_execution(self):
        self.start(choice=True)
        self.install_choice_fixture()
        transport = FakeTransport()
        attempted = []
        def check_identity():
            if not attempted:
                attempted.append(True)
                code = self.device("signoff", "--task-id", "feature", "--source", "conversation",
                                   "--proof-reference", "Competing manual response", "--criterion-id", "refresh")
                self.assertEqual(1, code, "manual choice must not interleave with an active device replay")
            return {"os": "35", "locale": "en-US"}
        transport.check_identity = check_identity
        self.assertEqual(0, self.device("validate-automatically", "--task-id", "feature", "--serial", "fixture",
                                      "--source", "conversation", "--proof-reference", "Run Automatically", transport=transport))
        from final_verifier import verify_task
        self.assertEqual("APPROVED", verify_task(self.repo, "feature")["status"])
        with self.assertRaises(ValidationError):
            self.store.read(self.current["delivery_snapshot_sha256"], self.current["run_id"], "device_signoff")

    def test_malformed_new_journey_attempt_blocks_delivery_without_traceback(self):
        self.start(choice=True)
        self.install_choice_fixture()
        self.assertEqual(0, self.device("validate-automatically", "--task-id", "feature", "--serial", "fixture",
                                      "--source", "conversation", "--proof-reference", "Run Automatically"))
        snapshot, run_id = self.current["delivery_snapshot_sha256"], self.current["run_id"]
        source = self.store.read(snapshot, run_id, "journey-refresh-flow")
        evidence = copy.deepcopy(source["evidence"])
        evidence["steps"] = ["malformed step"]
        self.store.write(snapshot=snapshot, run_id=run_id, name="journey-refresh-flow", producer="journey_runner",
                         harness_version=source["harness_version"], change_set=self.current["change_set_sha256"],
                         status="PASS", evidence=evidence, allow_pass_retry=True)
        from final_verifier import verify_task
        self.assertEqual("BLOCKED", verify_task(self.repo, "feature")["status"])

    def test_public_missing_coverage_then_bind_complete_and_reopen(self):
        self.start()
        from workflow import resolve_next_action, task_dir
        from final_verifier import verify_task
        self.assertEqual("BLOCKED", verify_task(self.repo, "feature")["status"])
        self.assertEqual("ACCEPTANCE_EVIDENCE_REQUIRED", resolve_next_action(self.repo, "feature")["code"])
        self.call("bind-evidence", "--criterion", "refresh", "--artifact", "unit_tests", "--case", "Tests#refresh")
        self.assertEqual("APPROVED", verify_task(self.repo, "feature")["status"])
        self.call("complete")
        from workflow import acceptance_coverage
        import argparse
        report = acceptance_coverage(argparse.Namespace(repo=str(self.repo), task_id="feature"))
        self.assertEqual("VERIFIED", report["criteria"][0]["status"])
        (self.repo / "README.md").write_text("Edited completed task\n")
        self.assertEqual("STALE", acceptance_coverage(argparse.Namespace(repo=str(self.repo), task_id="feature"))["criteria"][0]["status"])
        self.call("resume", "--reopen")
        (self.repo / "README.md").write_text("Changed again\n")
        self.call("prepare-verification")
        from _vnext_common import read_json
        current = read_json(task_dir(self.repo, "feature") / "current-run.json")
        self.assertTrue(coverage_report(self.plan, current, self.store)["blocking"])

    def test_legacy_task_reaches_completion_without_new_evidence(self):
        self.start(False)
        from final_verifier import verify_task
        self.assertEqual("APPROVED", verify_task(self.repo, "feature")["status"])
        self.call("complete")

    def test_revision_retains_contract_and_requires_fresh_approval(self):
        self.start()
        self.call("resume")
        self.call("revise", "--outcome", "Document refresh and failure behavior")
        from _vnext_common import read_json
        plan = read_json(self.repo / ".agents/state/tasks/feature/plan.json")
        self.assertEqual(contract(), plan["verification_contract"])
        self.assertEqual("AWAITING_DEVELOPER_APPROVAL", plan["status"])

    def test_test_case_parser_excludes_skipped_and_stale(self):
        from run_tests_gate import collect_test_outcomes
        report = self.repo / "app/build/test-results/testDebugUnitTest/TEST-Tests.xml"
        report.parent.mkdir(parents=True)
        report.write_text('<testsuite><testcase classname="Tests" name="refresh"/><testcase classname="Tests" name="skip"><skipped/></testcase><testcase classname="Tests" name="bad"><failure/></testcase></testsuite>')
        with patch("run_tests_gate.report_paths", return_value=[report]):
            self.assertEqual({"Tests#refresh": "PASS", "Tests#skip": "SKIPPED", "Tests#bad": "FAIL"},
                             collect_test_outcomes(self.repo, "testDebugUnitTest"))
            stat = report.stat()
            self.assertEqual({}, collect_test_outcomes(self.repo, "testDebugUnitTest", {report.resolve().as_posix(): (stat.st_mtime_ns, stat.st_size)}))

    def test_device_contract_incompatible_policy_fails_before_approval(self):
        from review_policy import decide
        import _product
        with patch.object(_product, "DEVICE_VERIFICATION_MODE", "disabled", create=True):
            with self.assertRaises(ValidationError):
                decide({"surfaces": ["DOCS"], "severity": "LOW"}, Path(__file__).parents[1] / "skills",
                       project_kind="application", plan={"verification_contract": contract("manual")})

    def test_new_commands_are_parser_valid_and_guarded(self):
        from workflow import build_parser
        from mutation_guard import command_allowed
        for action in ("coverage", "metrics"):
            build_parser().parse_args([action, "--task-id", "feature", "--json"])
        # Only trusted installed scripts are accepted by hooks.
        import shutil
        shutil.copy(Path(__file__).parents[1] / "harness.py", self.repo / ".agents/harness.py")
        self.assertTrue(command_allowed(self.repo, "python .agents/harness.py task coverage --task-id feature --json")[0])
        self.assertFalse(command_allowed(self.repo, "python .agents/harness.py journey run --task-id feature --id flow --serial fixture")[0])


class AdditionalBoundaries(unittest.TestCase):
    def test_complete_walkthrough_choice_rejects_empty_human_only_and_unbounded_contracts(self):
        value = contract()
        value["device_validation"] = "manual_or_automatic"
        with self.assertRaises(ValidationError):
            validate_contract(value)
        value = contract("journey")
        value.update(journeys=[journey()], device_validation="manual_or_automatic")
        validate_contract(value)
        human = copy.deepcopy(value)
        human["criteria"].append({"id": "usability", "expected": "Comfortable to use", "method": "manual", "required": True})
        with self.assertRaises(ValidationError):
            validate_contract(human)
        other = copy.deepcopy(value)
        second = copy.deepcopy(journey())
        second.update(id="other-flow", application_id="com.other")
        other["journeys"].append(second)
        with self.assertRaises(ValidationError):
            validate_contract(other)
        value["device_validation"] = "always_automatic"
        with self.assertRaises(ValidationError):
            validate_contract(value)

    def test_definition_traversal_oversize_and_invalid_types(self):
        from verification_contract import load_definition
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            with self.assertRaises(ValidationError):
                load_definition(repo, "../outside.json")
            (repo / "big.json").write_bytes(b" " * 262145)
            with self.assertRaises(ValidationError):
                load_definition(repo, "big.json")
        for value in (None, [], {}, {"schema_version": True, "criteria": [], "journeys": []}):
            with self.assertRaises(ValidationError):
                validate_contract(value)
        value = journey()
        value["steps"][0]["timeout"] = float("nan")
        with self.assertRaises(ValidationError):
            validate_journey(value)

    @unittest.skipUnless(hasattr(__import__("os"), "mkfifo"), "POSIX named-pipe regression")
    def test_nonregular_definition_never_opens_a_named_pipe(self):
        import os
        from verification_contract import load_definition
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            os.mkfifo(repo / "definition.json")
            # Guard the reader to make the regression deterministic instead of hanging.
            with patch("verification_contract.read_json", side_effect=AssertionError("unbounded pipe read")):
                with self.assertRaises(ValidationError):
                    load_definition(repo, "definition.json")

    def test_failed_assertion_disconnect_and_timeout_do_not_pass(self):
        self.assertEqual("FAIL", execute_journey(journey(), FakeTransport((0,)))["status"])
        for error in (OSError("disconnected"), TimeoutError("deadline")):
            transport = FakeTransport()
            transport.check_identity = lambda: (_ for _ in ()).throw(error)
            self.assertEqual("ENV", execute_journey(journey(), transport)["status"])

    def test_secret_input_is_never_in_result(self):
        value = journey()
        value["steps"].insert(0, {"action": "input", "selector": {"text": "Email"}, "secret_env": "FIXTURE_LOGIN"})
        with patch.dict("os.environ", {"FIXTURE_LOGIN": "private@example.invalid"}):
            result = execute_journey(value, FakeTransport())
        self.assertEqual("PASS", result["status"])
        self.assertNotIn("private@example.invalid", json.dumps(result))
        with patch.dict("os.environ", {"FIXTURE_LOGIN": "$(unsafe)"}):
            self.assertEqual("ENV", execute_journey(value, FakeTransport())["status"])

    def test_metrics_overlap_restart_corruption_and_cap(self):
        from _vnext_common import atomic_write_json
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            directory = repo / ".agents/state/metrics/task"
            for index, (start, end) in enumerate(((1, 4), (2, 5), (8, 10))):
                atomic_write_json(directory / f"{index}.json", {"schema_version": 1, "task_id": "task",
                    "operation": "test", "duration_seconds": end-start, "started_at": start,
                    "ended_at": end, "exit_code": index % 2})
            (directory / "partial.json").write_text('{')
            first = metrics_report(repo, "task")
            self.assertEqual(8, first["observed_execution_seconds"])
            self.assertEqual(6, first["operation_elapsed_union_seconds"])
            self.assertEqual(1, first["invalid_events"])
            self.assertEqual(first, metrics_report(repo, "task"))
            with patch("task_metrics.MAX_EVENTS", 4):
                record_operation(repo, "task", "test", 1, 0)
                self.assertEqual(4, len(list(directory.iterdir())))
                self.assertTrue(metrics_report(repo, "task")["history_capped"])

    def test_metrics_disabled_launcher_does_not_read_or_write(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("installed_fixture_launcher", Path(__file__).parents[1] / "harness.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with patch.dict("os.environ", {"HARNESS_LOCAL_METRICS": "0"}), \
                patch.object(launcher, "_main", return_value=0), \
                patch("mutation_guard.active_plan", side_effect=AssertionError("task read")), \
                patch("task_metrics.record_operation", side_effect=AssertionError("metric write")):
            self.assertEqual(0, launcher.main(["task", "status", "--json"]))

    def test_metrics_enabled_uses_explicit_task_without_history_scan(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("bounded_metric_launcher", Path(__file__).parents[1] / "harness.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with patch.dict("os.environ", {"HARNESS_LOCAL_METRICS": "1"}), \
                patch.object(launcher, "_main", return_value=0), \
                patch.object(launcher, "_print_next_step"), \
                patch("mutation_guard.active_plan", side_effect=AssertionError("historical fallback scan")), \
                patch("task_metrics.record_operation") as record:
            self.assertEqual(0, launcher.main(["task", "complete", "--task-id", "explicit-task", "--json"]))
            self.assertEqual("explicit-task", record.call_args.args[1])
            record.reset_mock()
            self.assertEqual(0, launcher.main(["assemble", "privateNamedGradleTask", "--task-id", "explicit-task", "--json"]))
            self.assertEqual("assemble", record.call_args.args[2])
            self.assertNotIn("privateNamedGradleTask", str(record.call_args))
            record.reset_mock()
            self.assertEqual(0, launcher.main(["task", "status", "--json"]))
            record.assert_not_called()

    def test_journey_requires_matching_artifacts_and_preserves_latest_failure(self):
        from journey_runner import run_selected
        import _product
        import hashlib
        from _vnext_common import atomic_write_json
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            store = EvidenceStore(repo / ".agents/state")
            definition = journey()
            plan = {"task_id": "task", "plan_sha256": "plan", "expected_modules": [":app"],
                    "verification_contract": {"schema_version": 1, "criteria": contract("journey")["criteria"], "journeys": [definition]}}
            current = {"delivery_snapshot_sha256": "snap", "run_id": "run", "change_set_sha256": "change",
                       "policy": str(repo / "policy.json")}
            atomic_write_json(repo / "policy.json", {"device_required": True})
            serial_hash = hashlib.sha256(b"fixture").hexdigest()
            def write(name, digest="apk"):
                evidence = {"artifact_set_sha256": digest, "serial_sha256": serial_hash,
                            "application_id": "com.example", "target_user": "0",
                            "artifact_set": {"artifact_set_sha256": digest, "members": [{"sha256": "member"}]}}
                store.write(snapshot="snap", run_id="run", name=name,
                    producer={"assemble": "run_gradle_task", "device_install": "run_device", "device_launch": "run_device"}[name],
                    harness_version="1", change_set="change", status="PASS", evidence=evidence, allow_pass_retry=True)
            for name in ("assemble", "device_install", "device_launch"):
                write(name)
            # These tests isolate runner boundaries; the canonical suite separately verifies trusted reviewer proof.
            with patch("verification_contract.active_context", return_value=(plan, current, store)), \
                    patch.object(_product, "ACTIVE_VARIANT", "Debug"), \
                    patch.object(_product, "DEVICE_VERIFICATION_MODE", "required"), \
                    patch("run_gradle_task.validate_reviewer_precondition_before_assemble", return_value=(True, "")), \
                    patch("final_verifier.verify_task", return_value={"status": "BLOCKED", "blocked_by": ["device_signoff"]}):
                self.assertEqual("PASS", run_selected(repo, "task", "refresh-flow", "fixture", FakeTransport())["status"])
                interrupted = FakeTransport()
                def interrupt():
                    self.assertEqual("BLOCKED", store.read("snap", "run", "journey-refresh-flow")["status"])
                    raise KeyboardInterrupt("fixture interruption")
                interrupted.check_identity = interrupt
                with self.assertRaises(KeyboardInterrupt):
                    run_selected(repo, "task", "refresh-flow", "fixture", interrupted)
                self.assertEqual("BLOCKED", store.read("snap", "run", "journey-refresh-flow")["status"])
                self.assertEqual("FAIL", run_selected(repo, "task", "refresh-flow", "fixture", FakeTransport((0,)))["status"])
                self.assertEqual("FAIL", store.read("snap", "run", "journey-refresh-flow")["status"])
                with self.assertRaises(ValidationError):
                    run_selected(repo, "task", "refresh-flow", "different", FakeTransport())
                write("device_install", "different-apk")
                transport = FakeTransport()
                with self.assertRaises(ValidationError):
                    run_selected(repo, "task", "refresh-flow", "fixture", transport)
                self.assertEqual([], transport.actions)


if __name__ == "__main__":
    unittest.main()
