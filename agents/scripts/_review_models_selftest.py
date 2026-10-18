"""Reviewer-model policy, native dispatch and evidence boundary contracts."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, atomic_write_json, read_json, task_dir
import review_models as models

ROLE = "bug-reviewer-agent"
SECURITY = "security-reviewer-agent"
SCRIPT = Path(models.__file__)


class ReviewerModelsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        (self.repo / ".agents").mkdir()

    def policy(self, default="sonnet", **overrides):
        return {"schema_version": 1, "default": default, "overrides": overrides}

    def record(self, policy, task=None, **kwargs):
        return models.set_policy(self.repo, policy, task_id=task, host=kwargs.get("host", "claude"),
                                 source=kwargs.get("source", "conversation"), proof_reference=kwargs.get("proof", "Developer requested this model"))

    def run_meta(self, default="sonnet"):
        self.record(self.policy(default))
        return {"review_host": "claude", "review_models": models.freeze_models(self.repo, "task", "claude", [ROLE])}

    def transcript(self, actual="claude-sonnet-4-6", body="I am Opus"):
        directory = self.repo / "claude-config" / "projects" / "project" / "session" / "subagents"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "agent-abc123.jsonl"
        message = {"id": "msg_1", "content": [{"type": "text", "text": body}]}
        if actual is not None:
            message["model"] = actual
        path.write_text(json.dumps({"type": "assistant", "message": message}) + "\n", encoding="utf-8")
        return path

    def identity(self, path):
        from review_sources import read_claude_subagent_transcript
        return read_claude_subagent_transcript(path)[1]

    def test_legacy_runs_ignore_new_project_configuration(self):
        self.record(self.policy("opus"))
        self.assertEqual({}, models.frozen_models({"review_host": "claude"}))
        self.assertEqual("inherit", models.model_evidence({"review_host": "claude"}, ROLE)["requested_model"])

    def test_default_has_no_native_override(self):
        frozen = models.freeze_models(self.repo, "task", "antigravity", [ROLE])
        self.assertEqual({}, frozen["reviewers"][ROLE]["native_arguments"])
        self.assertIsNone(frozen["reviewers"][ROLE]["actual_model"])

    def test_project_and_role_choices(self):
        self.record(self.policy(**{SECURITY: "opus"}))
        frozen = models.freeze_models(self.repo, "task", "claude", [ROLE, SECURITY])
        self.assertEqual({"model": "sonnet"}, frozen["reviewers"][ROLE]["native_arguments"])
        self.assertEqual({"model": "opus"}, frozen["reviewers"][SECURITY]["native_arguments"])

    def test_task_replaces_project_and_setup(self):
        atomic_write_json(self.repo / ".harness-setup/answers.json", {"review_model_policy": self.policy("haiku")})
        self.assertEqual("setup", models.load_policy(self.repo)[1])
        self.record(self.policy("opus"))
        atomic_write_json(task_dir(self.repo, "task") / "plan.json", {"status": "IMPLEMENTING"})
        self.record(self.policy("inherit"), "task")
        self.assertEqual(self.policy("inherit"), models.load_policy(self.repo, "task")[0])
        self.assertEqual("opus", models.load_policy(self.repo)[0]["default"])

    def test_existing_run_is_immutable_when_project_changes(self):
        run = self.run_meta()
        self.record(self.policy("haiku"))
        self.assertEqual("sonnet", models.frozen_models(run)[ROLE]["requested_model"])
        self.assertEqual("haiku", models.freeze_models(self.repo, "task", "claude", [ROLE])["reviewers"][ROLE]["requested_model"])

    def test_host_transfer_preserves_choice_and_rejects_unsupported_target(self):
        run = self.run_meta()
        self.record(self.policy("haiku"))
        transferred = models.transfer_models(run, "claude", [ROLE])
        self.assertEqual("sonnet", transferred["reviewers"][ROLE]["requested_model"])
        with self.assertRaisesRegex(ValidationError, "UNSUPPORTED"):
            models.transfer_models(run, "antigravity", [ROLE])
        inherited = models.transfer_models({"review_host": "claude"}, "antigravity", [ROLE])
        self.assertEqual({}, inherited["reviewers"][ROLE]["native_arguments"])

    def test_mutation_boundary_requires_explicit_developer_choice_before_task(self):
        from mutation_guard import command_allowed
        command = 'python .agents/harness.py review models set --host claude --default opus'
        self.assertFalse(command_allowed(self.repo, command)[0])
        allowed = command + ' --source conversation --proof-reference "Use Opus for reviewers"'
        self.assertTrue(command_allowed(self.repo, allowed)[0])
        self.assertTrue(command_allowed(self.repo, 'python .agents/harness.py review models show --host claude')[0])
        # Feed the actual native hook shape, ensuring no extra task approval is required.
        env = {**os.environ, "HARNESS_REPO": str(self.repo), "HARNESS_HOOK_STATE": str(self.repo / "hook-state.json")}
        for supplied, decision in ((command, "deny"), (allowed, "allow")):
            result = subprocess.run([sys.executable, str(SCRIPT.with_name("pre_tool_safety.py"))],
                                    input=json.dumps({"toolName": "run_command", "toolArgs": {"CommandLine": supplied}}),
                                    text=True, capture_output=True, env=env)
            self.assertEqual(decision, json.loads(result.stdout)["decision"], result.stdout + result.stderr)

    def test_final_proof_requires_frozen_model_evidence(self):
        run = self.run_meta()
        with self.assertRaisesRegex(ValidationError, "UNVERIFIED"):
            models.validate_model_evidence(run, ROLE, None)
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.repo / "claude-config")}):
            evidence = models.model_evidence(run, ROLE, self.identity(self.transcript()))
        models.validate_model_evidence(run, ROLE, evidence)
        evidence["settings_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValidationError, "UNVERIFIED"):
            models.validate_model_evidence(run, ROLE, evidence)

    def test_authority_and_task_state(self):
        for source, proof in ((None, "chosen"), ("conversation", ""), ("agent", "chosen")):
            with self.subTest(source=source), self.assertRaises(ValidationError):
                self.record(self.policy(), source=source, proof=proof)
        atomic_write_json(task_dir(self.repo, "task") / "plan.json", {"status": "VERIFYING"})
        with self.assertRaises(ValidationError):
            self.record(self.policy(), "task")

    def test_unsupported_explicit_choice_never_falls_back_or_writes(self):
        for host in ("antigravity", "codex", "generic"):
            with self.subTest(host=host), self.assertRaisesRegex(ValidationError, "REVIEW_MODEL_UNSUPPORTED"):
                self.record(self.policy(), host=host)
        self.assertFalse((self.repo / ".agents/state/review-models.json").exists())

    def test_malformed_unknown_and_provider_models_rejected(self):
        for value in (None, [], {}, self.policy("gpt-6"), self.policy(**{"security": "opus"}),
                      {**self.policy(), "schema_version": True}, {**self.policy(), "extra": True},
                      self.policy(**{ROLE: ["opus"]})):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                models.validate_policy(value)

    def test_corrupt_records_and_frozen_settings_fail_closed(self):
        self.record(self.policy())
        path = self.repo / ".agents/state/review-models.json"
        record = read_json(path)
        record["policy"]["default"] = "opus"
        atomic_write_json(path, record)
        with self.assertRaisesRegex(ValidationError, "checksum"):
            models.load_policy(self.repo)
        run = self.run_meta()
        run["review_models"]["reviewers"][ROLE]["requested_model"] = "opus"
        with self.assertRaisesRegex(ValidationError, "checksum"):
            models.frozen_models(run)

    def test_explicit_selection_requires_native_transcript_metadata(self):
        run = self.run_meta()
        with self.assertRaisesRegex(ValidationError, "UNVERIFIED"):
            models.model_evidence(run, ROLE, {"host_reported_model": "claude-sonnet-4-6"})
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.repo / "claude-config")}):
            path = self.transcript(None, "I used sonnet")
            with self.assertRaisesRegex(ValidationError, "UNVERIFIED"):
                models.model_evidence(run, ROLE, self.identity(path))

    def test_native_matching_model_recorded_separately_from_requested(self):
        run = self.run_meta()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.repo / "claude-config")}):
            path = self.transcript()
            evidence = models.model_evidence(run, ROLE, self.identity(path))
        self.assertEqual("sonnet", evidence["requested_model"])
        self.assertEqual("claude-sonnet-4-6", evidence["actual_model"])
        self.assertEqual("HOST_REPORTED_UNVERIFIED", evidence["actual_model_status"])

    def test_model_mismatch_and_changed_transcript_rejected(self):
        run = self.run_meta()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.repo / "claude-config")}):
            path = self.transcript("claude-opus-4-6")
            with self.assertRaisesRegex(ValidationError, "MISMATCH"):
                models.model_evidence(run, ROLE, self.identity(path))
            path = self.transcript()
            identity = self.identity(path)
            path.write_text(path.read_text() + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "changed"):
                models.model_evidence(run, ROLE, identity)

    def test_public_command_roundtrip_and_dispatch_map(self):
        from harness_shared.commands import review_command
        self.assertEqual(("review_models.py", ["show"]), review_command(["models", "show"]))
        args = [sys.executable, str(SCRIPT), "set", "--repo", str(self.repo), "--host", "claude", "--default", "haiku",
                "--source", "conversation", "--proof-reference", "Use Haiku for reviews"]
        result = subprocess.run(args, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        result = subprocess.run([sys.executable, str(SCRIPT), "show", "--repo", str(self.repo), "--host", "claude"], text=True, capture_output=True)
        self.assertEqual("haiku", json.loads(result.stdout)["policy"]["default"])
        self.assertEqual("HOST_ACCOUNT_DEPENDENT", json.loads(result.stdout)["capability"]["availability"])

    def test_setup_schema_and_host_validation(self):
        from wizard.schema import validate_raw_answers, setup_model_policy
        from wizard.questions import normalize
        self.assertEqual([], validate_raw_answers({"review_model_policy": self.policy()}))
        self.assertTrue(validate_raw_answers({"review_model_policy": "inherit_only"}))
        self.assertEqual(self.policy(), setup_model_policy({"review_model_policy": "sonnet"}))
        raw = {"i0": "yes", "i1": "Test", "i2": sys.executable, "i5": ":app", "i6": "com.example.MainActivity", "i14": ["claude"], "i20": "none", "review_model_policy": "sonnet"}
        facts = {"repo": ".", "project_name": "Test", "modules": [":app"], "gradle": "gradlew", "python": sys.executable, "launcher": "com.example.MainActivity", "application_id": "com.example"}
        self.assertEqual("sonnet", normalize(raw, facts)["review_model_policy"]["default"])
        raw["i14"] = ["antigravity"]
        with self.assertRaisesRegex(ValidationError, "UNSUPPORTED"):
            normalize(raw, facts)

    def test_final_profile_uses_frozen_selection_and_same_roster(self):
        from review_execution import resolve_execution_profile
        run = self.run_meta()
        directory = task_dir(self.repo, "task")
        atomic_write_json(directory / "plan.json", {})
        atomic_write_json(directory / "policy.json", {"reviewers": [ROLE], "risk_tier": "T2_FEATURE", "severity": "MEDIUM"})
        run.update({"run_id": "run-models", "policy": str(directory / "policy.json")})
        atomic_write_json(directory / "current-run.json", run)
        profile = resolve_execution_profile(self.repo, "task", "claude")
        self.assertEqual({ROLE}, set(profile["reviewers"]))
        self.assertEqual({"model": "sonnet"}, profile["reviewers"][ROLE]["native_arguments"])
        self.assertEqual("DEVELOPER_SELECTED_NATIVE", profile["model_policy"])
        with self.assertRaisesRegex(ValidationError, "host"):
            resolve_execution_profile(self.repo, "task", "antigravity")

    def test_public_lifecycle_freezes_settings_before_run_publication(self):
        # Real draft/approve/prepare path, not a fabricated current-run.
        from _task_isolation_selftest import TaskIsolationTests
        import workflow
        fixture = TaskIsolationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.draft("models", "A.md")
        fixture.approve("models")
        (fixture.repo / "A.md").write_text("changed documentation\n", encoding="utf-8")
        models.set_policy(fixture.repo, self.policy(), task_id=None, host="claude", source="conversation", proof_reference="Use Sonnet")
        args = argparse.Namespace(repo=str(fixture.repo), task_id="models", host="antigravity", force=False)
        with self.assertRaisesRegex(ValidationError, "UNSUPPORTED"):
            workflow.prepare_verification(args)
        self.assertEqual("IMPLEMENTING", read_json(task_dir(fixture.repo, "models") / "plan.json")["status"])
        self.assertFalse((task_dir(fixture.repo, "models") / "current-run.json").exists())
        args.host = "claude"
        run = workflow.prepare_verification(args)
        self.assertEqual("sonnet", run["review_models"]["policy"]["default"])
        self.assertEqual("VERIFYING", read_json(task_dir(fixture.repo, "models") / "plan.json")["status"])

    def test_phase_router_dispatch_completion_and_freeze(self):
        from _phase_review_v2_selftest import PhaseReviewV2Selftest
        from phase_review import record_phase_dispatch_batch, complete_phase_review
        import workflow
        fixture = PhaseReviewV2Selftest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        models.set_policy(fixture.repo, self.policy(), task_id=None, host="claude", source="conversation", proof_reference="Use Sonnet")
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "claude", "CLAUDE_CONFIG_DIR": str(self.repo / "claude-config")}):
            task, reviewers, _, run = fixture._setup_dispatch_state()
            self.assertTrue(reviewers)
            action = workflow.resolve_next_action(fixture.repo, task)
            for role in reviewers:
                self.assertEqual({"model": "sonnet"}, action["review_execution_profile"]["reviewers"][role]["native_arguments"])
            models.set_policy(fixture.repo, self.policy("haiku"), task_id=None, host="claude", source="conversation", proof_reference="Use Haiku for future runs")
            action = workflow.resolve_next_action(fixture.repo, task)
            self.assertEqual("sonnet", action["review_execution_profile"]["reviewers"][reviewers[0]]["requested_model"])
            record_phase_dispatch_batch(fixture.repo, task, "p1", reviewers, host="claude")
            role = reviewers[0]
            response = '```json\n' + json.dumps({"schema_version": 2, "task_id": task, "run_id": run["phase_review_run_id"],
                       "reviewer": role, "review_package_sha256": run["package_sha256"], "verdict": "PASS", "findings": []}) + '\n```'
            with self.assertRaisesRegex(ValidationError, "UNVERIFIED"):
                complete_phase_review(fixture.repo, task, "p1", role, "execution-1", host="claude", raw_response=response)
            identity = self.identity(self.transcript(body=response))
            result = complete_phase_review(fixture.repo, task, "p1", role, "execution-1", host="claude", raw_response=response, response_source=identity)
            self.assertEqual("PASS", result["verdict"])


if __name__ == "__main__":
    unittest.main()
