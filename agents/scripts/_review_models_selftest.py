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

ROLE = "bug-test-reviewer-agent"
SECURITY = "security-perf-reviewer-agent"
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

    def phase_fixture(self):
        from _phase_review_v2_selftest import PhaseReviewV2Selftest
        from install_tool_adapters import generate_antigravity_agents
        import shutil
        fixture = PhaseReviewV2Selftest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        (fixture.repo / ".agents/state/review-models.json").unlink(missing_ok=True)
        shutil.copytree(Path(__file__).resolve().parents[1] / "subagents", fixture.repo / ".agents/subagents")
        generate_antigravity_agents(fixture.repo, dry_run=False)
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "antigravity"}):
            task, roster, briefs, run = fixture._setup_dispatch_state(select_model=False)
        return fixture, task, roster, run

    def test_existing_phase_choice_refreshes_package_and_briefs_without_spending(self):
        from phase_review import phase_run_file, phase_ledger_file
        fixture, task, roster, before = self.phase_fixture()
        result = models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                                  host="antigravity", source="conversation", proof_reference="Flash for this task")
        after = read_json(phase_run_file(task_dir(fixture.repo, task), "p1"))
        self.assertEqual(before["phase_review_run_id"], after["phase_review_run_id"])
        self.assertEqual("flash-dynamic", after["review_models"]["policy"]["default"])
        self.assertNotEqual(before["package_sha256"], after["package_sha256"])
        self.assertIn(after["review_models"]["sha256"], Path(after["package_path"]).read_text(encoding="utf-8"))
        for role in roster:
            self.assertIn(after["package_sha256"], Path(after["briefs"][role]).read_text(encoding="utf-8"))
        self.assertEqual(0, read_json(task_dir(fixture.repo, task) / "plan.json").get("review_calls_used", 0))
        ledger = read_json(phase_ledger_file(task_dir(fixture.repo, task), "p1"))
        self.assertTrue(all(r["state"] == "NOT_DISPATCHED" for r in ledger["reviewers"].values()))
        self.assertIn("refreshed_run", result)

    def test_phase_once_choice_binds_to_real_run_and_expires(self):
        fixture, task, roster, run = self.phase_fixture()
        record = models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task, scope="run",
                                   host="antigravity", source="conversation", proof_reference="Flash once")
        self.assertEqual(run["phase_review_run_id"], record["bound_run_id"])
        self.assertEqual("run", models.load_policy(fixture.repo, task)[1])
        self.assertEqual("default", models.freeze_models(fixture.repo, task, "antigravity", roster, run_id="future-run")["source"])

    def test_phase_dispatched_choice_cannot_rewrite_evidence(self):
        from phase_review import record_phase_dispatch_batch, phase_run_file
        fixture, task, roster, run = self.phase_fixture()
        models.set_policy(fixture.repo, self.policy("inherit"), task_id=task,
                          host="antigravity", source="conversation", proof_reference="Use chat model")
        record_phase_dispatch_batch(fixture.repo, task, "p1", roster, host="antigravity")
        path = phase_run_file(task_dir(fixture.repo, task), "p1")
        before = path.read_bytes()
        with self.assertRaisesRegex(ValidationError, "dispatched"):
            models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                              host="antigravity", source="conversation", proof_reference="Change active run")
        self.assertEqual(before, path.read_bytes())

    def test_interrupted_model_update_blocks_dispatch_and_same_choice_repairs(self):
        from phase_review import record_phase_dispatch_batch, phase_run_file
        fixture, task, roster, run = self.phase_fixture()
        with mock.patch.object(models, "_refresh_undispatched_runs", side_effect=OSError("interrupted publication")):
            with self.assertRaises(OSError):
                models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                                  host="antigravity", source="conversation", proof_reference="Use Flash")
        with self.assertRaisesRegex(ValidationError, "INCOMPLETE"):
            record_phase_dispatch_batch(fixture.repo, task, "p1", roster, host="antigravity")
        models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                          host="antigravity", source="conversation", proof_reference="Use Flash")
        after = read_json(phase_run_file(task_dir(fixture.repo, task), "p1"))
        self.assertEqual("flash-dynamic", after["review_models"]["policy"]["default"])
        record_phase_dispatch_batch(fixture.repo, task, "p1", roster, host="antigravity")

    def test_frontmatter_is_not_actual_model_proof(self):
        run = {"review_host": "antigravity", "review_models": models._resolve_policy(self.policy("flash-dynamic"), "task", "antigravity", [ROLE])}
        with self.assertRaisesRegex(ValidationError, "UNVERIFIED"):
            models.model_evidence(run, ROLE, {"repo": str(self.repo), "host_reported_model": "gemini-3.8-flash-high"})

    def test_review_brief_and_tool_output_cannot_be_a_reviewer_response(self):
        from record_review import _extract_transcript_response
        path = self.repo / "transcript.jsonl"
        for source, kind in [("SYSTEM_SDK", "SYSTEM_MESSAGE"), ("MODEL", "GENERIC")]:
            path.write_text(json.dumps({"source": source, "type": kind, "content": '```json\n{"verdict":"PASS"}\n```'}) + '\n', encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "model response"):
                _extract_transcript_response(path)
        # A native transcript must identify an assistant response explicitly;
        # legacy source-only tool output cannot acquire trusted V2 provenance.
        root = self.repo / "antigravity"
        path = root / "brain/reviewer-123/.system_generated/logs/transcript.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"source": "MODEL", "content": '```json\n{"verdict":"PASS"}\n```'}) + '\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root)}):
            with self.assertRaisesRegex(ValidationError, "model response"):
                _extract_transcript_response(path)

    def test_protocol_retry_cancellation_can_resume_same_execution(self):
        from reviewer_host import reviewer_context, authorize_resume
        from phase_review import complete_phase_review
        fixture, task, roster, run, root, role = self.reviewer_host_fixture()
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root), "HARNESS_HOST": "antigravity"}):
            reviewer_context(fixture.repo, "reviewer-123", bind=True)
            result = complete_phase_review(fixture.repo, task, "p1", role, "reviewer-123", host="antigravity", raw_response="malformed reviewer reply")
            self.assertEqual("PROTOCOL_RETRY_REQUIRED", result["status"])
            result = authorize_resume(fixture.repo, task, role, "p1", "conversation", "Resume the cancelled correction")
            self.assertEqual("reviewer-123", result["execution_id"])

    def antigravity_identity(self, configured="gemini-3.8-flash-high", observed="gemini-3.8-flash-n", cid="reviewer-123"):
        import sqlite3
        def varint(n):
            data = bytearray()
            while n >= 128:
                data.append((n & 127) | 128)
                n >>= 7
            return bytes(data + bytes([n]))
        def field(number, data):
            return varint(number * 8 + 2) + varint(len(data)) + data
        root = self.repo / "antigravity"
        transcript = root / "brain" / cid / ".system_generated/logs/transcript.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text('{}\n', encoding="utf-8")
        database = root / "conversations" / f"{cid}.db"
        database.parent.mkdir(exist_ok=True)
        from contextlib import closing
        with closing(sqlite3.connect(database)) as connection:
            connection.execute('CREATE TABLE executor_metadata (idx INTEGER, data BLOB)')
            connection.execute('CREATE TABLE gen_metadata (idx INTEGER, data BLOB)')
            connection.execute('INSERT INTO executor_metadata VALUES (0, ?)', (field(10, field(1, field(28, configured.encode()))),))
            connection.execute('INSERT INTO gen_metadata VALUES (0, ?)', (field(1, field(19, observed.encode())),))
            connection.commit()
        return root, {"transcript_path": str(transcript)}

    def test_antigravity_native_model_metadata_is_distinct_from_configuration(self):
        run = {"review_host": "antigravity", "review_models": models._resolve_policy(self.policy("flash-dynamic"), "task", "antigravity", [ROLE], efforts_by_role={ROLE: "DEEP"})}
        root, identity = self.antigravity_identity()
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root)}):
            evidence = models.model_evidence(run, ROLE, identity)
        self.assertEqual("gemini-3.8-flash-n", evidence["actual_model"])
        self.assertEqual("gemini-3.8-flash-high", evidence["host_configured_model"])
        self.assertEqual("NATIVE_METADATA_OBSERVED", evidence["actual_model_status"])
        models.validate_model_evidence(run, ROLE, evidence)
        with self.assertRaisesRegex(ValidationError, "UNVERIFIED"):
            models.validate_model_evidence(run, ROLE, {**evidence, "host_configured_model": "gemini-3.8-pro-high"})

    def test_antigravity_wrong_native_model_blocks_acceptance(self):
        run = {"review_host": "antigravity", "review_models": models._resolve_policy(self.policy("flash-dynamic"), "task", "antigravity", [ROLE], efforts_by_role={ROLE: "DEEP"})}
        root, identity = self.antigravity_identity(observed="gemini-3.8-pro-n")
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root)}):
            with self.assertRaisesRegex(ValidationError, "MISMATCH"):
                models.model_evidence(run, ROLE, identity)

    def test_phase_default_model_requires_a_separate_explicit_choice(self):
        from phase_review import record_phase_dispatch_batch
        fixture, task, roster, run = self.phase_fixture()
        with self.assertRaisesRegex(ValidationError, "SELECT_REVIEW_MODEL"):
            record_phase_dispatch_batch(fixture.repo, task, "p1", roster, host="antigravity")
        self.assertEqual(0, read_json(task_dir(fixture.repo, task) / "plan.json").get("review_calls_used", 0))

    def test_arabic_choice_output_survives_windows_legacy_encoding(self):
        proof = "Use Flash for this task: \u0641\u0644\u0627\u0634"
        proc = subprocess.run([sys.executable, str(SCRIPT), "set", "--repo", str(self.repo), "--host", "antigravity",
                               "--default", "flash-dynamic", "--source", "conversation", "--proof-reference", proof],
                              capture_output=True, env={**os.environ, "PYTHONIOENCODING": "cp1252"})
        self.assertEqual(0, proc.returncode, proc.stderr.decode("utf-8"))
        self.assertEqual(proof, json.loads(proc.stdout.decode("utf-8"))["proof_reference"])

    def test_repeated_choice_keeps_run_package_and_call_count(self):
        from phase_review import phase_run_file, phase_ledger_file
        fixture, task, roster, run = self.phase_fixture()
        for index in range(2):
            models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                              host="antigravity", source="conversation", proof_reference="Flash")
            current = read_json(phase_run_file(task_dir(fixture.repo, task), "p1"))
            digest = current["package_sha256"]
            if index == 0:
                first_digest = digest
            else:
                self.assertEqual(first_digest, digest)
        self.assertEqual(run["phase_review_run_id"], current["phase_review_run_id"])
        self.assertTrue(all(e["state"] == "NOT_DISPATCHED" for e in read_json(phase_ledger_file(task_dir(fixture.repo, task), "p1"))["reviewers"].values()))

    def test_same_choice_after_dispatch_is_idempotent(self):
        from phase_review import record_phase_dispatch_batch, phase_run_file
        fixture, task, roster, run = self.phase_fixture()
        models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                          host="antigravity", source="conversation", proof_reference="Flash")
        record_phase_dispatch_batch(fixture.repo, task, "p1", roster, host="antigravity")
        path = phase_run_file(task_dir(fixture.repo, task), "p1")
        before = path.read_bytes()
        result = models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                                   host="antigravity", source="conversation", proof_reference="Flash")
        self.assertTrue(result["already_applied"])
        self.assertEqual(before, path.read_bytes())

    def test_interruption_after_package_write_is_repairable_without_new_run(self):
        import phase_review
        fixture, task, roster, run = self.phase_fixture()
        path = phase_review.phase_run_file(task_dir(fixture.repo, task), "p1")
        original = phase_review.atomic_write_json
        def interrupted(target, data):
            if target == path:
                raise OSError("interrupted after package and briefs")
            return original(target, data)
        with mock.patch.object(phase_review, "atomic_write_json", side_effect=interrupted):
            with self.assertRaises(OSError):
                models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                                  host="antigravity", source="conversation", proof_reference="Flash")
        models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                          host="antigravity", source="conversation", proof_reference="Flash")
        repaired = read_json(path)
        self.assertEqual(run["phase_review_run_id"], repaired["phase_review_run_id"])
        self.assertTrue(phase_review.phase_review_freshness(fixture.repo, task, "p1", repaired)[0])

    def reviewer_host_fixture(self):
        from phase_review import record_phase_dispatch_batch
        fixture, task, roster, run = self.phase_fixture()
        models.set_policy(fixture.repo, self.policy("inherit"), task_id=task,
                          host="antigravity", source="conversation", proof_reference="Use chat model")
        from phase_review import phase_run_file
        run = read_json(phase_run_file(task_dir(fixture.repo, task), "p1"))
        record_phase_dispatch_batch(fixture.repo, task, "p1", roster, host="antigravity")
        root, identity = self.antigravity_identity()
        role = "bug-test-reviewer-agent" if "bug-test-reviewer-agent" in roster else roster[0]
        prompt = Path(run["briefs"][role]).read_text(encoding="utf-8").strip()
        content = '<SYSTEM_MESSAGE>\n[Message] timestamp=2026-10-19T09:02:22Z sender=parent-123 priority=MESSAGE_PRIORITY_HIGH content=' + prompt + '\n</SYSTEM_MESSAGE>'
        Path(identity["transcript_path"]).write_text(json.dumps({"source": "SYSTEM_SDK", "type": "SYSTEM_MESSAGE", "content": content}) + '\n', encoding="utf-8")
        parent = root / "brain/parent-123/.system_generated/logs/transcript.jsonl"
        parent.parent.mkdir(parents=True)
        parent.write_text(json.dumps({"source": "SYSTEM_SDK", "type": "SYSTEM_MESSAGE", "content": '[Message] timestamp=2026-10-19T09:03:01Z sender=system priority=MESSAGE_PRIORITY_LOW content=Subagent "reviewer-123" has been explicitly canceled by the user and will be idle until you send a message to it directly.'}) + '\n', encoding="utf-8")
        return fixture, task, roster, run, root, role

    def test_native_cancellation_routes_to_decision_and_resumes_same_execution(self):
        import workflow
        from reviewer_host import reviewer_context, authorize_resume
        fixture, task, roster, run, root, role = self.reviewer_host_fixture()
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root), "HARNESS_HOST": "antigravity"}):
            context = reviewer_context(fixture.repo, "reviewer-123", bind=True)
            self.assertEqual(role, context["role"])
            action = workflow.resolve_next_action(fixture.repo, task)
            self.assertEqual("REVIEWER_CANCELLED", action["code"])
            _, denied = fixture._run_pre_tool_safety({"toolName": "send_message", "toolArgs": {"Recipient": "reviewer-123", "Message": "Continue"}})
            self.assertEqual("deny", denied["decision"])
            used = read_json(task_dir(fixture.repo, task) / "plan.json")["review_calls_used"]
            with self.assertRaisesRegex(ValidationError, "explicit"):
                authorize_resume(fixture.repo, task, role, "p1", "conversation", "")
            proc = subprocess.run([sys.executable, str(Path(__file__).with_name("review_orchestrator.py")), "resume", "--repo", str(fixture.repo),
                                   "--task-id", task, "--phase-id", "p1", "--reviewer", role,
                                   "--source", "conversation", "--proof-reference", "Continue the cancelled reviewers"], capture_output=True, text=True)
            self.assertEqual(0, proc.returncode, proc.stderr)
            action = workflow.resolve_next_action(fixture.repo, task)
            self.assertEqual("RESUME_REVIEWER", action["code"])
            self.assertEqual("reviewer-123", action["recipient"])
            _, allowed = fixture._run_pre_tool_safety({"toolName": "send_message", "toolArgs": {"Recipient": action["recipient"], "Message": action["message"]}})
            self.assertEqual("allow", allowed["decision"])
            self.assertEqual("WAIT_FOR_PHASE_REVIEWERS", workflow.resolve_next_action(fixture.repo, task)["code"])
            self.assertEqual(used, read_json(task_dir(fixture.repo, task) / "plan.json")["review_calls_used"])
            fixture._run_post_tool_reconcile({"toolCall": {"name": "send_message", "args": {"Recipient": "reviewer-123"}}, "error": "Host unavailable"})
            self.assertEqual("REVIEWER_RESUME_ENV_BLOCKED", workflow.resolve_next_action(fixture.repo, task)["code"])
            authorize_resume(fixture.repo, task, role, "p1", "conversation", "Continue the cancelled reviewers")
            self.assertEqual("RESUME_REVIEWER", workflow.resolve_next_action(fixture.repo, task)["code"])

    def test_successful_launch_binds_and_finished_reply_routes_to_ingestion(self):
        from phase_review import phase_ledger_file, complete_phase_review
        import workflow
        fixture, task, roster, run, root, role = self.reviewer_host_fixture()
        parent = root / "brain/parent-123/.system_generated/logs/transcript.jsonl"
        parent.write_text('', encoding="utf-8")
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root), "HARNESS_HOST": "antigravity"}):
            fixture._run_post_tool_reconcile({"toolCall": {"name": "invoke_subagent"}, "toolResult": {"conversationId": "reviewer-123"}})
            ledger = read_json(phase_ledger_file(task_dir(fixture.repo, task), "p1"))
            self.assertEqual("reviewer-123", ledger["reviewers"][role]["execution_id"])
            result = {"schema_version": 2, "task_id": task, "run_id": run["phase_review_run_id"], "reviewer": role,
                      "review_package_sha256": run["package_sha256"], "verdict": "PASS", "findings": []}
            transcript = root / "brain/reviewer-123/.system_generated/logs/transcript.jsonl"
            with transcript.open('a', encoding="utf-8") as handle:
                handle.write(json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE", "content": '```json\n' + json.dumps(result) + '\n```'}) + '\n')
            self.assertEqual("COMPLETE_REVIEWER", workflow.resolve_next_action(fixture.repo, task)["code"])
            response = complete_phase_review(fixture.repo, task, "p1", role, "reviewer-123", host="antigravity")
            self.assertEqual("PASS", response["verdict"])

    def test_reviewer_shell_is_bounded_and_bound_to_native_execution(self):
        fixture, task, roster, run, root, role = self.reviewer_host_fixture()
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root), "HARNESS_HOST": "antigravity"}):
            for command, expected in [
                ("python .agents/harness.py task-context --file app/src/main/java/com/example/Auth.kt --json", "allow"),
                ("python .agents/harness.py task resume --task-id " + task, "deny"),
                ("python .agents/harness.py graph --find Auth --json; git status", "deny"),
                ("python -c print(1)", "deny"),
                ("python .agents/harness.py graph --find Auth --out escape.json", "deny"),
            ]:
                _, result = fixture._run_pre_tool_safety({"conversationId": "reviewer-123", "toolName": "run_command", "toolArgs": {"CommandLine": command}})
                self.assertEqual(expected, result.get("decision"), result)
            _, result = fixture._run_pre_tool_safety({"conversationId": "reviewer-123", "toolName": "write_to_file", "toolArgs": {"TargetFile": str(fixture.repo / "app/src/main/java/com/example/Auth.kt"), "CodeContent": "changed"}})
            self.assertEqual("deny", result.get("decision"))
            _, result = fixture._run_pre_tool_safety({"conversationId": "unbound-reviewer", "toolName": "run_command", "toolArgs": {
                "CommandLine": "python .agents/harness.py task resume --task-id " + task}})
            self.assertEqual("deny", result.get("decision"))
            _, result = fixture._run_pre_tool_safety({"conversationId": "reviewer-123", "toolName": "run_command", "toolArgs": {
                "CommandLine": "python .agents/harness.py graph --find Auth --json", "Cwd": str(self.repo)}})
            self.assertEqual("deny", result.get("decision"))

    def test_pending_sibling_launch_keeps_its_native_model(self):
        from phase_review import record_phase_dispatch_batch
        fixture, task, roster, run = self.phase_fixture()
        models.set_policy(fixture.repo, self.policy("flash-dynamic"), task_id=task,
                          host="antigravity", source="conversation", proof_reference="Flash")
        record_phase_dispatch_batch(fixture.repo, task, "p1", roster, host="antigravity")
        role = "bug-test-reviewer-agent" if "bug-test-reviewer-agent" in roster else roster[0]
        before = (fixture.repo / ".agents/agents" / role / "agent.md").read_bytes()
        with self.assertRaisesRegex(ValidationError, "LAUNCH_PENDING"):
            models.freeze_models(fixture.repo, "sibling", "antigravity", roster, run_id="sibling-run")
        self.assertEqual(before, (fixture.repo / ".agents/agents" / role / "agent.md").read_bytes())

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



    def test_antigravity_five_choices_and_dynamic_thinking_resolution(self):
        from install_tool_adapters import generate_antigravity_agents
        import shutil
        shutil.copytree(Path(__file__).resolve().parents[1] / "subagents", self.repo / ".agents" / "subagents", dirs_exist_ok=True)
        generate_antigravity_agents(self.repo, dry_run=False)
        conv = "arch-regression-reviewer-agent"
        roster = [conv, ROLE, SECURITY]
        prompt = models.build_antigravity_model_prompt(self.repo, "task-ag", roster, run_id="run-1")
        self.assertEqual("SELECT_REVIEW_MODEL", prompt["code"])
        choice_ids = [c["id"] for c in prompt["choices"]]
        self.assertEqual(
            ["hydrogen-dynamic-project", "hydrogen-dynamic-task", "safe-cache-project", "hydrogen-risk-project", "inherit-task"],
            choice_ids,
        )

        # 1. flash-dynamic-task on standard NORMAL task: medium for convention & bug, medium for unescalated security (high when DEEP/MAX)
        atomic_write_json(task_dir(self.repo, "task-ag") / "plan.json", {"status": "IMPLEMENTING"})
        args_set = [
            sys.executable, str(SCRIPT), "set", "--repo", str(self.repo), "--host", "antigravity",
            "--task-id", "task-ag", "--choice", "flash-dynamic-task",
            "--source", "conversation", "--proof-reference", "Use flash dynamic for task",
        ]
        res = subprocess.run(args_set, text=True, capture_output=True)
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        frozen = models.freeze_models(
            self.repo, "task-ag", "antigravity", roster, run_id="run-1",
            policy_data={"surfaces": ["BUSINESS_LOGIC", "COROUTINES"], "severity": "HIGH"},
        )
        self.assertEqual("gemini-3.8-flash-medium", frozen["reviewers"][conv]["resolved_model"])
        self.assertEqual("medium", frozen["reviewers"][conv]["thinking_level"])
        self.assertEqual("gemini-3.8-flash-medium", frozen["reviewers"][ROLE]["resolved_model"])
        self.assertEqual("medium", frozen["reviewers"][ROLE]["thinking_level"])
        self.assertEqual("gemini-3.8-flash-high", frozen["reviewers"][SECURITY]["resolved_model"])
        self.assertEqual({}, frozen["reviewers"][SECURITY]["native_arguments"])

        # Check frontmatter synced on disk
        sec_md = (self.repo / ".agents" / "agents" / SECURITY / "agent.md").read_text(encoding="utf-8")
        conv_md = (self.repo / ".agents" / "agents" / conv / "agent.md").read_text(encoding="utf-8")
        self.assertIn('model: "gemini-3.8-flash-high"', sec_md)
        self.assertIn('model: "gemini-3.8-flash-medium"', conv_md)

        # Verify model_evidence and validate_model_evidence on Antigravity
        run_doc = {"review_host": "antigravity", "review_models": frozen}
        root, identity = self.antigravity_identity()
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root)}):
            ev = models.model_evidence(run_doc, SECURITY, identity)
        self.assertEqual("NATIVE_METADATA_OBSERVED", ev["actual_model_status"])
        self.assertEqual("gemini-3.8-flash-n", ev["actual_model"])
        models.validate_model_evidence(run_doc, SECURITY, ev)

        # 2. hybrid-smart-task: Flash medium for standard (convention), Inherit for critical (bug, security)
        args_hybrid = [
            sys.executable, str(SCRIPT), "set", "--repo", str(self.repo), "--host", "antigravity",
            "--task-id", "task-ag", "--choice", "hybrid-smart-task",
            "--source", "conversation", "--proof-reference", "Use hybrid smart for task",
        ]
        res_h = subprocess.run(args_hybrid, text=True, capture_output=True)
        self.assertEqual(0, res_h.returncode, res_h.stdout + res_h.stderr)
        frozen_h = models.freeze_models(self.repo, "task-ag", "antigravity", roster, run_id="run-2")
        self.assertEqual("gemini-3.8-flash-medium", frozen_h["reviewers"][conv]["resolved_model"])
        self.assertEqual("DEVELOPER_SELECTED_NATIVE", frozen_h["reviewers"][conv]["model_policy"])
        self.assertEqual("inherit", frozen_h["reviewers"][ROLE]["requested_model"])
        self.assertEqual("INHERIT_PARENT_BY_OMISSION", frozen_h["reviewers"][ROLE]["model_policy"])
        self.assertIsNone(frozen_h["reviewers"][ROLE].get("agent_frontmatter_model"))
        self.assertEqual("inherit", frozen_h["reviewers"][SECURITY]["requested_model"])
        sec_md_after = (self.repo / ".agents" / "agents" / SECURITY / "agent.md").read_text(encoding="utf-8")
        conv_md_after = (self.repo / ".agents" / "agents" / conv / "agent.md").read_text(encoding="utf-8")
        self.assertNotIn("model:", sec_md_after)
        self.assertIn('model: "gemini-3.8-flash-medium"', conv_md_after)

    def test_antigravity_run_scope_expires_on_next_run_and_refreshes_undispatched_run(self):
        from install_tool_adapters import generate_antigravity_agents
        import shutil
        shutil.copytree(Path(__file__).resolve().parents[1] / "subagents", self.repo / ".agents" / "subagents", dirs_exist_ok=True)
        generate_antigravity_agents(self.repo, dry_run=False)
        tdir = task_dir(self.repo, "task-once")
        atomic_write_json(tdir / "plan.json", {"task_id": "task-once", "status": "VERIFYING"})
        policy_path = tdir / "policy-run-1.json"
        atomic_write_json(policy_path, {"reviewers": [ROLE], "risk_tier": "T2_FEATURE", "severity": "MEDIUM"})
        initial_models = models.freeze_models(self.repo, "task-once", "antigravity", [ROLE], run_id="run-1")
        self.assertEqual("default", initial_models["source"])
        atomic_write_json(tdir / "current-run.json", {
            "task_id": "task-once",
            "run_id": "run-1",
            "review_host": "antigravity",
            "review_protocol_version": 2,
            "policy": str(policy_path),
            "delivery_snapshot_sha256": "a" * 64,
            "change_set_sha256": "b" * 64,
            "review_models": initial_models,
        })

        # Setting flash-dynamic-once while VERIFYING before any reviewer is dispatched succeeds and refreshes current-run.json
        models.set_policy(
            self.repo,
            models.choice_to_policy("flash-dynamic-once")[0],
            task_id="task-once",
            host="antigravity",
            source="conversation",
            proof_reference="Flash once for this run",
            scope="run",
        )
        updated_current = read_json(tdir / "current-run.json")
        self.assertEqual("run", updated_current["review_models"]["source"])
        self.assertEqual("gemini-3.8-flash-medium", updated_current["review_models"]["reviewers"][ROLE]["resolved_model"])

        # Next run (run-2) does not match bound_run_id="run-1", so it reverts to default inherit!
        next_run_models = models.freeze_models(self.repo, "task-once", "antigravity", [ROLE], run_id="run-2")
        self.assertEqual("default", next_run_models["source"])
        self.assertEqual("inherit", next_run_models["reviewers"][ROLE]["requested_model"])

    def test_define_subagent_and_unbound_phase_dispatch_replay_allowed(self):
        from phase_review import phase_run_file, phase_ledger_file
        fixture, task, roster, _ = self.phase_fixture()
        models.set_policy(
            fixture.repo, self.policy("inherit"), task_id=task,
            host="antigravity", source="conversation", proof_reference="Use chat model",
        )
        run = read_json(phase_run_file(task_dir(fixture.repo, task), "p1"))
        briefs = {r: Path(run["briefs"][r]).read_text(encoding="utf-8") for r in roster}

        # 1. define_subagent is allowed during DISPATCH_PHASE_REVIEWERS
        _, def_res = fixture._run_pre_tool_safety({
            "toolName": "define_subagent",
            "toolArgs": {"name": roster[0], "description": "Reviewer", "system_prompt": "Review"},
        })
        self.assertEqual("allow", def_res.get("decision"), def_res)

        # 2. Initial invoke_subagent succeeds in pre-tool hook (records DISPATCHED with execution_id=None)
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r]} for r in roster]
        _, disp1 = fixture._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("allow", disp1.get("decision"), disp1)
        calls_after_first = read_json(task_dir(fixture.repo, task) / "plan.json").get("review_calls_used", 0)
        self.assertEqual(len(roster), calls_after_first)

        # 3. If host rejected invoke_subagent before creating any subagent (execution_id is still None),
        #    define_subagent and exact cohort replay are allowed without charging extra calls!
        _, def_res2 = fixture._run_pre_tool_safety({
            "toolName": "define_subagent",
            "toolArgs": {"name": roster[0], "description": "Reviewer", "system_prompt": "Review"},
        })
        self.assertEqual("allow", def_res2.get("decision"), def_res2)

        _, disp2 = fixture._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("allow", disp2.get("decision"), disp2)
        calls_after_replay = read_json(task_dir(fixture.repo, task) / "plan.json").get("review_calls_used", 0)
        self.assertEqual(calls_after_first, calls_after_replay)

        # 4. Once an execution_id is bound on any reviewer, further invoke_subagent calls are denied
        ledger_path = phase_ledger_file(task_dir(fixture.repo, task), "p1")
        ledger = read_json(ledger_path)
        ledger["reviewers"][roster[0]]["execution_id"] = "bound-conv-1"
        from phase_review import compute_ledger_sha
        ledger["ledger_sha256"] = compute_ledger_sha(ledger)
        atomic_write_json(ledger_path, ledger)

        _, disp3 = fixture._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", disp3.get("decision"), disp3)

    def test_reviewer_models_displayed_in_router_and_phase_review_outputs(self):
        from workflow import resolve_next_action
        from phase_review import phase_run_file
        fixture, task, roster, _ = self.phase_fixture()
        models.set_policy(
            fixture.repo, self.policy("flash-dynamic"), task_id=task,
            host="antigravity", source="conversation", proof_reference="Flash for task",
        )
        run = read_json(phase_run_file(task_dir(fixture.repo, task), "p1"))
        rm_map = models.reviewer_model_map(run, roster)
        self.assertTrue(all(rm_map[r].startswith("gemini-3.8-flash-") for r in roster))
        formatted = models.format_reviewers_with_models(run, roster)
        for r in roster:
            self.assertIn(f"{r} [{rm_map[r]}]", formatted)
        plan = read_json(task_dir(fixture.repo, task) / "plan.json")
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "antigravity"}):
            action = resolve_next_action(fixture.repo, task, plan)
        self.assertEqual("DISPATCH_PHASE_REVIEWERS", action["code"])
        self.assertEqual(rm_map, action["inputs"]["reviewer_models"])
        for r in roster:
            self.assertIn(f"{r} [{rm_map[r]}]", action["reason"])

    def test_antigravity_flash_enforced_in_invoke_subagent_and_batch_complete(self):
        from phase_review import phase_run_file, phase_ledger_file, main as phase_main
        import workflow
        fixture, task, roster, _ = self.phase_fixture()
        models.set_policy(
            fixture.repo, self.policy("flash-dynamic"), task_id=task,
            host="antigravity", source="conversation", proof_reference="Flash for task",
        )
        run = read_json(phase_run_file(task_dir(fixture.repo, task), "p1"))
        briefs = {r: Path(run["briefs"][r]).read_text(encoding="utf-8") for r in roster}

        # Omitting Model="flash" when flash-dynamic is active is denied by pre_tool_safety
        subagents_no_model = [{"TypeName": r, "Role": r, "Prompt": briefs[r]} for r in roster]
        _, denied = fixture._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents_no_model}})
        self.assertEqual("deny", denied.get("decision"), denied)
        self.assertIn("REVIEWER_MODEL_MISMATCH", str(denied.get("reason") or ""), denied)

        # Supplying Model="flash" is allowed
        subagents_flash = [{"TypeName": r, "Role": r, "Prompt": briefs[r], "Model": "flash"} for r in roster]
        _, allowed = fixture._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents_flash}})
        self.assertEqual("allow", allowed.get("decision"), allowed)

        # Verify batch COMPLETE_REVIEWER when multiple reviewers finish
        ledger_path = phase_ledger_file(task_dir(fixture.repo, task), "p1")
        ledger = read_json(ledger_path)
        root = None
        for idx, r in enumerate(roster):
            exec_id = f"rev-batch-{idx}"
            ledger["reviewers"][r]["execution_id"] = exec_id
            root, identity = self.antigravity_identity(
                configured="gemini-3.8-flash-tiered",
                observed="gemini-3.8-flash-n",
                cid=exec_id,
            )
            t_file = Path(identity["transcript_path"])
            res_body = {
                "schema_version": 2, "task_id": task, "run_id": run["phase_review_run_id"],
                "reviewer": r, "review_package_sha256": run["package_sha256"],
                "verdict": "PASS", "findings": [],
            }
            step = {
                "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                "content": "```json\n" + json.dumps(res_body) + "\n```",
            }
            t_file.write_text(json.dumps(step) + "\n", encoding="utf-8")
        from phase_review import compute_ledger_sha
        ledger["ledger_sha256"] = compute_ledger_sha(ledger)
        atomic_write_json(ledger_path, ledger)

        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root), "HARNESS_HOST": "antigravity"}):
            action = workflow.resolve_next_action(fixture.repo, task)
            self.assertEqual("COMPLETE_REVIEWER", action["code"])
            for idx, r in enumerate(roster):
                self.assertIn(f"--reviewer {r} --execution-id rev-batch-{idx}", action["command"])
            batch_args = ["complete", "--repo", str(fixture.repo), "--task-id", task, "--phase-id", "p1"]
            for idx, r in enumerate(roster):
                batch_args.extend(["--reviewer", r, "--execution-id", f"rev-batch-{idx}"])
            rc = phase_main(batch_args)
            self.assertEqual(0, rc)
            updated_ledger = read_json(ledger_path)
            for r in roster:
                self.assertEqual("COMPLETED", updated_ledger["reviewers"][r]["state"])

    def test_adapter_regeneration_and_dispatch_keep_antigravity_agent_files_stable(self):
        from install_tool_adapters import generate_antigravity_agents
        from phase_review import phase_run_file
        fixture, task, roster, _ = self.phase_fixture()
        models.set_policy(
            fixture.repo, self.policy("flash-dynamic"), task_id=task,
            host="antigravity", source="conversation", proof_reference="Flash for task",
        )
        run = read_json(phase_run_file(task_dir(fixture.repo, task), "p1"))
        agent_md = fixture.repo / ".agents" / "agents" / "bug-test-reviewer-agent" / "agent.md"
        expected_bytes = agent_md.read_bytes()
        self.assertIn(b'model: "gemini-3.8-flash-high"', expected_bytes)

        # Adapter regeneration during active-task update preserves active task/run model frontmatter
        generate_antigravity_agents(fixture.repo, dry_run=False)
        self.assertEqual(expected_bytes, agent_md.read_bytes())

        # PreToolUse dispatch does not rewrite agent.md when frontmatter already matches
        updated = models.sync_antigravity_agent_models(
            fixture.repo, {r: models.frozen_models(run)[r] for r in roster}
        )
        self.assertEqual([], updated)





    def test_flash_argon_hybrid_adaptive_complexity_bands_and_mixed_dispatch_guard(self):
        from install_tool_adapters import generate_antigravity_agents
        from phase_review import phase_run_file
        import shutil

        shutil.copytree(Path(__file__).resolve().parents[1] / "subagents", self.repo / ".agents" / "subagents", dirs_exist_ok=True)
        generate_antigravity_agents(self.repo, dry_run=False)
        conv = "arch-regression-reviewer-agent"
        roster = [conv, ROLE, SECURITY]

        # Set project-wide flash-argon-project choice (argon@hybrid shorthand also normalizes cleanly)
        self.assertEqual("flash-argon-hybrid", models.normalize_model_token("argon@hybrid"))
        rec = models.set_policy(
            self.repo,
            models.choice_to_policy("flash-argon-project")[0],
            task_id=None,
            host="antigravity",
            source="conversation",
            proof_reference="Enable adaptive Flash + Argon Low hybrid project-wide",
            scope="project",
        )
        self.assertEqual("flash-argon-hybrid", rec["policy"]["default"])

        # Band 1: SIMPLE single-module UI/ViewModel feature -> 100% Pure Flash Medium (0 Argon calls!)
        simple_plan = {
            "task_id": "t-simple",
            "status": "VERIFYING",
            "task_kind": "FEATURE",
            "planning_depth": "BOUNDED",
            "expected_modules": [":app"],
            "expected_files": [
                "app/src/main/java/com/example/CatalogScreen.kt",
                "app/src/main/java/com/example/CatalogViewModel.kt",
                "app/src/test/java/com/example/CatalogViewModelTest.kt",
            ],
            "expected_surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"],
        }
        simple_pol = {
            "risk_tier": "T2_FEATURE",
            "severity": "MEDIUM",
            "surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"],
            "changed_lines": 42,
        }
        self.assertEqual("SIMPLE", models.compute_task_complexity_tier(self.repo, "t-simple", policy_data=simple_pol, plan=simple_plan))
        frozen_simple = models.freeze_models(
            self.repo, "t-simple", "antigravity", roster, run_id="run-s1",
            policy_data=simple_pol, plan=simple_plan,
        )
        self.assertEqual("SIMPLE", frozen_simple["complexity_tier"])
        for r in roster:
            self.assertEqual("gemini-3.8-flash-medium", frozen_simple["reviewers"][r]["resolved_model"], r)
            self.assertEqual("medium", frozen_simple["reviewers"][r]["thinking_level"], r)
        models.frozen_models({"review_host": "antigravity", "review_models": frozen_simple})

        # Band 2a: COMPLEX (COROUTINES + NETWORK, >90 lines) -> Argon Low for bug/security-perf, Flash Medium for NORMAL arch-regression!
        complex_plan = {
            "task_id": "t-complex",
            "status": "VERIFYING",
            "task_kind": "FEATURE",
            "planning_depth": "BOUNDED",
            "expected_modules": [":app", ":core:network"],
            "expected_files": [
                "app/src/main/java/com/example/SyncRepository.kt",
                "core/network/src/main/java/com/example/SyncApi.kt",
            ],
            "expected_surfaces": ["COROUTINES", "NETWORK"],
        }
        complex_pol = {
            "risk_tier": "T3_SUBSYSTEM",
            "severity": "HIGH",
            "surfaces": ["COROUTINES", "NETWORK"],
            "changed_lines": 120,
        }
        self.assertEqual("COMPLEX", models.compute_task_complexity_tier(self.repo, "t-complex", policy_data=complex_pol, plan=complex_plan))
        frozen_complex = models.freeze_models(
            self.repo, "t-complex", "antigravity", roster, run_id="run-c1",
            policy_data=complex_pol, plan=complex_plan,
        )
        self.assertEqual("COMPLEX", frozen_complex["complexity_tier"])
        self.assertEqual("gemini-4-argon-low", frozen_complex["reviewers"][ROLE]["resolved_model"])
        self.assertEqual("low", frozen_complex["reviewers"][ROLE]["thinking_level"])
        self.assertEqual("gemini-4-argon-low", frozen_complex["reviewers"][SECURITY]["resolved_model"])
        self.assertEqual("gemini-3.8-flash-medium", frozen_complex["reviewers"][conv]["resolved_model"])
        models.frozen_models({"review_host": "antigravity", "review_models": frozen_complex})
        hint = models.antigravity_dispatch_model_hint(frozen_complex, roster)
        self.assertIn("pass Model='flash' for [arch-regression-reviewer-agent]", hint)
        self.assertIn("omit Model for [bug-test-reviewer-agent, security-perf-reviewer-agent]", hint)

        # Band 2b: COMPLEX with ROOM_SCHEMA -> arch-regression has DEEP effort so it ALSO steps up to Argon Low!
        room_pol = {
            "risk_tier": "T4_DATA_DEVICE",
            "severity": "HIGH",
            "surfaces": ["ROOM_SCHEMA", "BUSINESS_LOGIC"],
            "changed_lines": 65,
        }
        frozen_room = models.freeze_models(
            self.repo, "t-room", "antigravity", roster, run_id="run-c2",
            policy_data=room_pol, plan=complex_plan,
        )
        for r in roster:
            self.assertEqual("gemini-4-argon-low", frozen_room["reviewers"][r]["resolved_model"], r)

        # Band 3: CRITICAL (AUTH + BILLING, T5_CRITICAL) -> Strict hard ceiling at Argon Low (`gemini-4-argon-low`) for ALL reviewers!
        crit_pol = {
            "risk_tier": "T5_CRITICAL",
            "severity": "CRITICAL",
            "surfaces": ["AUTH", "BILLING"],
            "changed_lines": 50,
            "review_round": 3,
        }
        self.assertEqual("CRITICAL", models.compute_task_complexity_tier(self.repo, "t-crit", policy_data=crit_pol, plan=simple_plan))
        frozen_crit = models.freeze_models(
            self.repo, "t-crit", "antigravity", roster, run_id="run-crit",
            policy_data=crit_pol, plan=simple_plan,
        )
        for r in roster:
            self.assertEqual("gemini-4-argon-low", frozen_crit["reviewers"][r]["resolved_model"], r)
            self.assertEqual("low", frozen_crit["reviewers"][r]["thinking_level"], r)
        models.frozen_models({"review_host": "antigravity", "review_models": frozen_crit})

        # Verify mixed Flash + Argon Low wave in PreToolUse hook on phase review!
        fixture, task, p_roster, _ = self.phase_fixture()
        p_plan = read_json(task_dir(fixture.repo, task) / "plan.json")
        p_plan["task_kind"] = "BUG"
        p_plan["expected_modules"] = [":app", ":core"]
        atomic_write_json(task_dir(fixture.repo, task) / "plan.json", p_plan)
        models.set_policy(
            fixture.repo,
            models.resolve_preset_policy("flash-argon-hybrid"),
            task_id=task,
            host="antigravity",
            source="conversation",
            proof_reference="Adaptive Flash + Argon Low",
        )
        p_run = read_json(phase_run_file(task_dir(fixture.repo, task), "p1"))
        p_briefs = {r: Path(p_run["briefs"][r]).read_text(encoding="utf-8") for r in p_roster}
        mixed_subs = []
        for r in p_roster:
            rm = p_run["review_models"]["reviewers"][r]["resolved_model"]
            entry = {"TypeName": r, "Role": r, "Prompt": p_briefs[r]}
            if "flash" in rm:
                entry["Model"] = "flash"
            mixed_subs.append(entry)
        _, ok_mixed = fixture._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": mixed_subs}})
        self.assertEqual("allow", ok_mixed.get("decision"), ok_mixed)


    def test_hydrogen_argon_hybrid_pure_hydrogen_and_all_edge_cases(self):
        """Exhaustively verify Carbon Lead + Hydrogen/Argon subagent routing and all 14 edge cases."""
        import delegation_policy as dp
        import antigravity_runtime as ar
        from install_tool_adapters import generate_antigravity_agents
        from lifecycle import _antigravity_agent_matches_policy
        from doctor.engine import HarnessDoctor
        from phase_review import phase_run_file
        import repair as repair_mod
        import shutil

        shutil.copytree(Path(__file__).resolve().parents[1] / "subagents", self.repo / ".agents" / "subagents", dirs_exist_ok=True)
        generate_antigravity_agents(self.repo, dry_run=False)

        conv = "arch-regression-reviewer-agent"
        roster = [conv, ROLE, SECURITY]
        efforts_norm = {r: "NORMAL" for r in roster}

        # Edge Case 1: Shorthand & Extra/xHigh normalization + --mode CLI flag compatibility
        self.assertEqual("hydrogen-argon-hybrid", models.normalize_model_token("hydrogen@hybrid"))
        self.assertEqual("hydrogen-argon-hybrid", models.normalize_model_token("hydrogen-argon"))
        self.assertEqual("hydrogen-dynamic", models.normalize_model_token("hydrogen@dynamic"))
        self.assertEqual("hydrogen-risk-hybrid", models.normalize_model_token("hydrogen@risk"))
        self.assertEqual("gemini-4-hydrogen-xhigh", models.normalize_model_token("hydrogen@extra"))
        self.assertEqual("gemini-4-hydrogen-xhigh", models.normalize_model_token("gemini-4-hydrogen-extra"))
        self.assertEqual(("gemini-4-hydrogen-xhigh", "xhigh"), models.resolve_antigravity_model("hydrogen@xhigh", ROLE, "MAX"))
        self.assertEqual(("gemini-4-hydrogen-high", "high"), models.resolve_antigravity_model("gemini-4-hydrogen", ROLE, "NORMAL"))

        res_cli = subprocess.run(
            [
                sys.executable, str(SCRIPT), "set", "--repo", str(self.repo), "--host", "antigravity",
                "--mode", "hydrogen-argon-project", "--source", "conversation", "--proof-reference", "Use Hydrogen+Argon project-wide",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, res_cli.returncode, res_cli.stdout + res_cli.stderr)

        # Edge Case 2: Band 1 SIMPLE -> Scout & reviewers on gemini-4-hydrogen-medium; Worker starts on gemini-4-hydrogen-high from Wave 1
        t_simple = "task-hy-simple"
        plan_s = {
            "task_id": t_simple,
            "status": "IMPLEMENTING",
            "task_kind": "FEATURE",
            "risk_tier": "T2_MODERATE",
            "expected_surfaces": ["COMPOSE_UI"],
            "expected_modules": [":app"],
            "expected_files": [
                "app/src/main/java/com/example/HomeScreen.kt",
                "app/src/main/java/com/example/HomeViewModel.kt",
                "app/src/test/java/com/example/HomeViewModelTest.kt",
            ],
        }
        atomic_write_json(task_dir(self.repo, t_simple) / "plan.json", plan_s)
        self.assertEqual("gemini-4-hydrogen-medium", dp.resolve_utility_scout_model(self.repo, t_simple, plan=plan_s))
        w_simple, tier_s = dp.resolve_utility_worker_model(self.repo, t_simple, plan=plan_s, worker_mode="FULL_SLICE")
        self.assertEqual(("gemini-4-hydrogen-high", "SIMPLE"), (w_simple, tier_s))
        frozen_s = models.freeze_models(
            self.repo, t_simple, "antigravity", roster, run_id="r-hy-s",
            policy_data={"surfaces": ["COMPOSE_UI"], "severity": "MEDIUM", "risk_tier": "T2_MODERATE", "reviewer_efforts": efforts_norm},
            plan=plan_s,
        )
        for r in roster:
            self.assertEqual("gemini-4-hydrogen-medium", frozen_s["reviewers"][r]["resolved_model"])
            self.assertEqual("medium", frozen_s["reviewers"][r]["thinking_level"])
        models.frozen_models({"review_host": "antigravity", "review_models": frozen_s})

        # Edge Case 3: Band 2 COMPLEX -> Worker & bug-test/security-perf upgrade to gemini-4-hydrogen-high (0 Argon burn!); Scout & arch stay medium
        t_complex = "task-hy-complex"
        plan_c = {
            "task_id": t_complex,
            "status": "IMPLEMENTING",
            "task_kind": "BUG",
            "risk_tier": "T3_SUBSYSTEM",
            "expected_surfaces": ["COROUTINES", "NETWORK"],
            "expected_modules": [":app", ":core:network"],
            "expected_files": [
                "app/src/main/java/com/example/SyncWorker.kt",
                "core/network/src/main/java/com/example/ApiClient.kt",
                "app/src/test/java/com/example/SyncWorkerTest.kt",
            ],
        }
        atomic_write_json(task_dir(self.repo, t_complex) / "plan.json", plan_c)
        self.assertEqual("gemini-4-hydrogen-medium", dp.resolve_utility_scout_model(self.repo, t_complex, plan=plan_c))
        w_complex, tier_c = dp.resolve_utility_worker_model(self.repo, t_complex, plan=plan_c, worker_mode="FULL_SLICE")
        self.assertEqual(("gemini-4-hydrogen-high", "COMPLEX"), (w_complex, tier_c))
        w_red, _ = dp.resolve_utility_worker_model(self.repo, t_complex, plan=plan_c, worker_mode="CAPTURE_RED_ONLY")
        self.assertEqual("gemini-4-hydrogen-high", w_red)
        frozen_c = models.freeze_models(
            self.repo, t_complex, "antigravity", roster, run_id="r-hy-c",
            policy_data={"surfaces": ["COROUTINES", "NETWORK"], "severity": "HIGH", "risk_tier": "T3_SUBSYSTEM", "reviewer_efforts": efforts_norm},
            plan=plan_c,
        )
        self.assertEqual("gemini-4-hydrogen-high", frozen_c["reviewers"][ROLE]["resolved_model"])
        self.assertEqual("gemini-4-hydrogen-high", frozen_c["reviewers"][SECURITY]["resolved_model"])
        self.assertEqual("gemini-4-hydrogen-medium", frozen_c["reviewers"][conv]["resolved_model"])
        models.frozen_models({"review_host": "antigravity", "review_models": frozen_c})

        # Edge Case 4: Band 3 CRITICAL (T5 AUTH/BILLING) -> Strict hard ceiling at gemini-4-argon-low; Worker runs TESTS_AND_GATES_ONLY on medium
        t_crit = "task-hy-crit"
        plan_crit = {
            "task_id": t_crit,
            "status": "IMPLEMENTING",
            "task_kind": "FEATURE",
            "risk_tier": "T5_CRITICAL",
            "expected_surfaces": ["AUTH", "BILLING", "CRYPTO"],
            "expected_modules": [":app"],
            "expected_files": ["app/src/main/java/com/example/BillingCrypto.kt"],
        }
        atomic_write_json(task_dir(self.repo, t_crit) / "plan.json", plan_crit)
        dec_crit = dp.evaluate_delegation_policy(self.repo, t_crit, plan=plan_crit)
        self.assertEqual("SENSITIVE_LEAD_CORE_WORKER_TESTS", dec_crit["strategy"])
        self.assertEqual("gemini-4-hydrogen-high", dec_crit["worker_model"])
        frozen_crit = models.freeze_models(
            self.repo, t_crit, "antigravity", roster, run_id="r-hy-crit",
            policy_data={
                "surfaces": ["AUTH", "BILLING", "CRYPTO"],
                "severity": "CRITICAL",
                "risk_tier": "T5_CRITICAL",
                "reviewer_efforts": {SECURITY: "MAX", ROLE: "DEEP", conv: "NORMAL"},
            },
            plan=plan_crit,
        )
        self.assertEqual("gemini-4-hydrogen-high", frozen_crit["reviewers"][SECURITY]["resolved_model"])
        self.assertEqual("high", frozen_crit["reviewers"][SECURITY]["thinking_level"])
        self.assertEqual("gemini-4-hydrogen-high", frozen_crit["reviewers"][ROLE]["resolved_model"])
        self.assertEqual("high", frozen_crit["reviewers"][ROLE]["thinking_level"])
        self.assertEqual("gemini-4-hydrogen-high", frozen_crit["reviewers"][conv]["resolved_model"])
        self.assertEqual("high", frozen_crit["reviewers"][conv]["thinking_level"])
        models.frozen_models({"review_host": "antigravity", "review_models": frozen_crit})

        # Edge Case 5: Pure Hydrogen (`hydrogen-dynamic`) escalates SIMPLE(medium) -> COMPLEX/CRITICAL capped at `high` (zero automatic `xhigh`)
        models.set_policy(
            self.repo, models.resolve_preset_policy("hydrogen-dynamic"),
            task_id=None, host="antigravity", source="conversation", proof_reference="Pure Hydrogen", scope="project",
        )
        frozen_pure_crit = models.freeze_models(
            self.repo, t_crit, "antigravity", roster, run_id="r-pure-crit",
            policy_data={"surfaces": ["AUTH"], "severity": "CRITICAL", "risk_tier": "T5_CRITICAL", "reviewer_efforts": {r: "MAX" for r in roster}},
            plan=plan_crit,
        )
        for r in roster:
            self.assertEqual("gemini-4-hydrogen-high", frozen_pure_crit["reviewers"][r]["resolved_model"])
            self.assertEqual("high", frozen_pure_crit["reviewers"][r]["thinking_level"])

        # Edge Case 6: Native SQLite Protobuf Verification (`models/` prefix, `-n`, `-extra`, `-tiered`, `gemini-4-flash` alias, and Carbon leak rejection!)
        run_pure = {"review_host": "antigravity", "review_models": frozen_pure_crit}
        ag_root, id_ok = self.antigravity_identity(
            configured="models/gemini-4-hydrogen-high",
            observed="models/gemini-4-hydrogen-n",
            cid="hy-high-ok",
        )
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(ag_root)}):
            ev_ok = models.model_evidence(run_pure, SECURITY, id_ok)
            self.assertEqual("gemini-4-hydrogen-n", ev_ok["actual_model"])
            models.validate_model_evidence(run_pure, SECURITY, ev_ok)

            # Explicit manual `hydrogen@xhigh` override still validates `-extra` SQLite metadata cleanly
            models.set_policy(
                self.repo, {"schema_version": 1, "default": "gemini-4-hydrogen-xhigh", "overrides": {}},
                task_id=None, host="antigravity", source="conversation", proof_reference="Manual xhigh", scope="project",
            )
            frozen_manual_xh = models.freeze_models(
                self.repo, t_crit, "antigravity", roster, run_id="r-manual-xhigh",
                policy_data={"surfaces": ["AUTH"], "severity": "CRITICAL", "risk_tier": "T5_CRITICAL"},
                plan=plan_crit,
            )
            _, id_xh = self.antigravity_identity(
                configured="models/gemini-4-hydrogen-extra",
                observed="models/gemini-4-hydrogen-n",
                cid="hy-xhigh-ok",
            )
            ev_xh = models.model_evidence({"review_host": "antigravity", "review_models": frozen_manual_xh}, SECURITY, id_xh)
            models.validate_model_evidence({"review_host": "antigravity", "review_models": frozen_manual_xh}, SECURITY, ev_xh)

            _, id_alias = self.antigravity_identity(
                configured="gemini-4-hydrogen",
                observed="gemini-4-flash-001",
                cid="hy-alias-ok",
            )
            ev_alias = models.model_evidence(run_pure, ROLE, id_alias)
            models.validate_model_evidence(run_pure, ROLE, ev_alias)

            for leaked_model, cid_bad in (("gemini-4-carbon-medium", "hy-leak-carbon"), ("gemini-3.8-flash-n", "hy-leak-38")):
                _, id_bad = self.antigravity_identity(configured=leaked_model, observed=leaked_model, cid=cid_bad)
                with self.assertRaisesRegex(ValidationError, "REVIEW_MODEL_MISMATCH"):
                    models.model_evidence(run_pure, SECURITY, id_bad)

        # Edge Case 7: Hook enforcement on Hydrogen reviewers & utility agents (Model override forbidden + Remote Mode #198819 guard!)
        models.set_policy(
            self.repo, models.resolve_preset_policy("hydrogen-argon-hybrid"),
            task_id=None, host="antigravity", source="conversation", proof_reference="Back to Hydrogen+Argon", scope="project",
        )
        ok_u_bad, msg_u_bad, code_u_bad = dp.validate_utility_dispatch(
            self.repo, plan_c, [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Prompt": "Scan", "Model": "flash"}]
        )
        self.assertFalse(ok_u_bad)
        self.assertEqual("UTILITY_MODEL_QUOTA_GUARD", code_u_bad)
        self.assertIn("omit `Model`", msg_u_bad)
        ok_u_good, _, _ = dp.validate_utility_dispatch(
            self.repo, plan_c, [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Prompt": "Scan repo architecture"}]
        )
        self.assertTrue(ok_u_good)
        self.assertIn('model: "gemini-4-hydrogen-medium"', (self.repo / ".agents/agents/harness-scout-agent/agent.md").read_text(encoding="utf-8"))

        fixture, p_task, p_roster, _ = self.phase_fixture()
        p_plan = read_json(task_dir(fixture.repo, p_task) / "plan.json")
        p_plan["task_kind"] = "BUG"
        p_plan["expected_modules"] = [":app", ":core"]
        atomic_write_json(task_dir(fixture.repo, p_task) / "plan.json", p_plan)
        # Auth.kt in phase_fixture is CRITICAL -> hydrogen-argon-hybrid uses Argon Medium; hydrogen-dynamic caps at gemini-4-hydrogen-high
        models.set_policy(
            fixture.repo,
            models.resolve_preset_policy("hydrogen-dynamic"),
            task_id=p_task,
            host="antigravity",
            source="conversation",
            proof_reference="Pure Hydrogen on Phase Review",
        )
        p_run = read_json(phase_run_file(task_dir(fixture.repo, p_task), "p1"))
        for r in p_roster:
            self.assertTrue(p_run["review_models"]["reviewers"][r]["resolved_model"].startswith("gemini-4-hydrogen-"))
        p_briefs = {r: Path(p_run["briefs"][r]).read_text(encoding="utf-8") for r in p_roster}
        # Passing Model='flash' on Hydrogen reviewer -> REVIEWER_MODEL_OVERRIDE_FORBIDDEN
        _, out_ov = fixture._run_pre_tool_safety({
            "toolName": "invoke_subagent",
            "toolArgs": {"Subagents": [{"TypeName": r, "Role": r, "Prompt": p_briefs[r], "Model": "flash"} for r in p_roster]},
        })
        self.assertIn("REVIEWER_MODEL_OVERRIDE_FORBIDDEN", json.dumps(out_ov))
        # Remote Mode (#198819) -> REMOTE_MODE_FLASH_QUOTA_LEAK_GUARD even when Model is omitted on Hydrogen!
        old_rem = os.environ.get("ANTIGRAVITY_REMOTE_AGENT")
        os.environ["ANTIGRAVITY_REMOTE_AGENT"] = "1"
        try:
            _, out_rem = fixture._run_pre_tool_safety({
                "toolName": "invoke_subagent",
                "toolArgs": {"Subagents": [{"TypeName": r, "Role": r, "Prompt": p_briefs[r]} for r in p_roster]},
            })
            self.assertIn("REMOTE_MODE_FLASH_QUOTA_LEAK_GUARD", json.dumps(out_rem))
        finally:
            if old_rem is None:
                os.environ.pop("ANTIGRAVITY_REMOTE_AGENT", None)
            else:
                os.environ["ANTIGRAVITY_REMOTE_AGENT"] = old_rem

        # Local Mode with omitted Model -> ALLOWED
        _, out_loc = fixture._run_pre_tool_safety({
            "toolName": "invoke_subagent",
            "toolArgs": {"Subagents": [{"TypeName": r, "Role": r, "Prompt": p_briefs[r]} for r in p_roster]},
        })
        self.assertEqual("allow", out_loc.get("decision"), out_loc)

        # Edge Case 8: Doctor, Lifecycle ownership, Repair preservation, and Legacy `flash-*` fallback sync!
        dp.sync_utility_worker_model(self.repo, "gemini-4-hydrogen-high")
        self.assertTrue(_antigravity_agent_matches_policy(self.repo, ".agents/agents/harness-worker-agent/agent.md"))
        self.assertTrue(_antigravity_agent_matches_policy(self.repo, ".agents/agents/harness-scout-agent/agent.md"))
        doc = HarnessDoctor(self.repo, run_selftest=False)
        doc.check_antigravity_installation()
        rev_chk = next(r for r in doc.results if r.name == "Custom Reviewer Agents")
        self.assertEqual("PASS", rev_chk.status, rev_chk.message)

        models.set_policy(
            self.repo, models.choice_to_policy("flash-project")[0],
            task_id=None, host="antigravity", source="conversation", proof_reference="Fallback to Flash", scope="project",
        )
        self.assertIn('model: "gemini-3.8-flash-medium"', (self.repo / ".agents/agents/harness-scout-agent/agent.md").read_text(encoding="utf-8"))
        self.assertIn('model: "gemini-3.8-flash-medium"', (self.repo / ".agents/agents/harness-worker-agent/agent.md").read_text(encoding="utf-8"))
        repair_mod.main(["--repo", str(self.repo)])
        self.assertIn('model: "gemini-3.8-flash-medium"', (self.repo / ".agents/agents/harness-scout-agent/agent.md").read_text(encoding="utf-8"))

        # Edge Case 9: Platform hazard classifiers (Hydrogen rollout block, Orchestrator double-planning, Zero-quota 429)
        h_roll = ar.classify_antigravity_quota_or_capacity_error("PERMISSION_DENIED: model gemini-4-hydrogen is not available on your plan")
        self.assertEqual("HYDROGEN_ROLLOUT_ENTITLEMENT_BLOCK", h_roll["code"])
        self.assertIn("flash-argon-project", h_roll["remedy"])
        h_orch = ar.classify_antigravity_quota_or_capacity_error("Error: Effort isn't adjustable for Orchestrator")
        self.assertEqual("ORCHESTRATOR_DOUBLE_PLANNING_HAZARD", h_orch["code"])
        h_zero = ar.classify_antigravity_quota_or_capacity_error("HTTP 429 RESOURCE_EXHAUSTED gemini-4-argon: limit: 0 requests per day")
        self.assertEqual("MANAGED_AGENT_ZERO_QUOTA_429", h_zero["code"])
        self.assertIn("hydrogen-dynamic-project", h_zero["remedy"])


class TestCarbonCwdAndSandboxHardening(unittest.TestCase):
    """Edge-case regression tests for CRIT-1, CRIT-3, and CRIT-5."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        (self.repo / ".agents").mkdir()

    def test_gemini_4_carbon_models_and_pro_dispatch_contract(self):
        from install_tool_adapters import generate_antigravity_agents
        import shutil

        shutil.copytree(Path(__file__).resolve().parents[1] / "subagents", self.repo / ".agents" / "subagents")
        generate_antigravity_agents(self.repo, dry_run=False)

        pol = {
            "schema_version": 1,
            "default": models.normalize_model_token("carbon@dynamic"),
            "overrides": {SECURITY: models.normalize_model_token("pro@high")},
        }
        rec = models.set_policy(
            self.repo, pol, task_id=None, host="antigravity",
            source="conversation", proof_reference="Use Carbon dynamic and Pro high for security",
        )
        self.assertEqual("carbon-dynamic", rec["policy"]["default"])
        self.assertEqual("gemini-3.1-pro-high", rec["policy"]["overrides"][SECURITY])

        frozen = models.freeze_models(
            self.repo, "t-carbon", "antigravity",
            [ROLE, SECURITY, "arch-regression-reviewer-agent"],
            policy_data={"reviewer_efforts": {ROLE: "DEEP", SECURITY: "DEEP", "arch-regression-reviewer-agent": "NORMAL"}},
        )
        self.assertEqual("gemini-4-carbon-high", frozen["reviewers"][ROLE]["resolved_model"])
        self.assertEqual("gemini-4-carbon-medium", frozen["reviewers"]["arch-regression-reviewer-agent"]["resolved_model"])
        self.assertEqual("gemini-3.1-pro-high", frozen["reviewers"][SECURITY]["resolved_model"])

        gemini_tpl = (Path(__file__).resolve().parents[1] / "tool-adapters" / "GEMINI.md.template").read_text(encoding="utf-8")
        self.assertIn('Model = "pro"', gemini_tpl)
        self.assertIn("carbon", gemini_tpl)

    def test_native_model_metadata_readonly_wal_sandbox_fallback(self):
        import sqlite3
        from antigravity_runtime import native_model_metadata

        root = self.repo / "ag_data"
        conv_dir = root / "conversations"
        brain_dir = root / "brain" / "exec-ro-1" / ".system_generated" / "logs"
        conv_dir.mkdir(parents=True)
        brain_dir.mkdir(parents=True)
        transcript = brain_dir / "transcript.jsonl"
        transcript.write_text('{"source":"MODEL","type":"PLANNER_RESPONSE","content":"ok"}\n', encoding="utf-8")

        def pb_len(field_num: int, payload: bytes) -> bytes:
            tag = (field_num << 3) | 2
            out = bytearray()
            v = tag
            while v >= 128:
                out.append((v & 127) | 128)
                v >>= 7
            out.append(v)
            ln = len(payload)
            while ln >= 128:
                out.append((ln & 127) | 128)
                ln >>= 7
            out.append(ln)
            out.extend(payload)
            return bytes(out)

        cfg_blob = pb_len(10, pb_len(1, pb_len(28, b"gemini-4-carbon-high")))
        gen_blob = pb_len(1, pb_len(19, b"gemini-4-carbon-preview"))
        db_path = conv_dir / "exec-ro-1.db"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE executor_metadata (idx INTEGER, data BLOB)")
            conn.execute("CREATE TABLE gen_metadata (idx INTEGER, data BLOB)")
            conn.execute("INSERT INTO executor_metadata VALUES (0, ?)", (cfg_blob,))
            conn.execute("INSERT INTO gen_metadata VALUES (0, ?)", (gen_blob,))
            conn.commit()
        finally:
            conn.close()

        # Make conversations directory read-only (simulating Terminal Sandbox blocking -shm creation)
        conv_dir.chmod(0o555)
        try:
            with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root)}):
                meta = native_model_metadata(transcript)
                self.assertEqual("gemini-4-carbon-high", meta.get("host_configured_model"))
                self.assertEqual(["gemini-4-carbon-preview"], meta.get("host_reported_models"))

                frozen = models._resolve_policy(
                    {"schema_version": 1, "default": "carbon-dynamic", "overrides": {}},
                    "task", "antigravity", [ROLE], efforts_by_role={ROLE: "DEEP"},
                )
                run_doc = {"review_host": "antigravity", "review_models": frozen}
                ev = models.model_evidence(run_doc, ROLE, {"transcript_path": str(transcript)})
                self.assertEqual("NATIVE_METADATA_OBSERVED", ev["actual_model_status"])
                models.validate_model_evidence(run_doc, ROLE, ev)
        finally:
            conv_dir.chmod(0o755)

    def test_post_tool_reconcile_works_from_dot_agents_cwd_and_without_tool_result(self):
        from phase_review import phase_ledger_file
        import shutil

        # Copy post_tool_reconcile + sibling scripts into a client-shaped .agents/scripts layout
        fixture = ReviewerModelsTests("test_legacy_runs_ignore_new_project_configuration")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        inner_fixture, task, roster, run, root, role = fixture.reviewer_host_fixture()

        # Simulate Antigravity invoking PostToolUse with cwd=<repo>/.agents and NO HARNESS_REPO env
        client_agents = inner_fixture.repo / ".agents"
        client_scripts = client_agents / "scripts"
        if not (client_scripts / "post_tool_reconcile.py").is_file():
            shutil.copytree(Path(__file__).resolve().parent, client_scripts, dirs_exist_ok=True)
        client_shared = client_agents / "harness_shared"
        if not client_shared.is_dir():
            shutil.copytree(Path(__file__).resolve().parents[1] / "harness_shared", client_shared, dirs_exist_ok=True)

        parent_tx = root / "brain/parent-999/.system_generated/logs/transcript.jsonl"
        parent_tx.parent.mkdir(parents=True, exist_ok=True)
        parent_tx.write_text("", encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if k != "HARNESS_REPO"}
        env["ANTIGRAVITY_APP_DATA"] = str(root)
        env["HARNESS_HOST"] = "antigravity"

        # 1. Bind execution_id via transcriptPath sibling brain scan when toolResult is omitted!
        payload_bind = {
            "toolCall": {"name": "invoke_subagent", "args": {"Subagents": [{"Role": role, "TypeName": role}]}},
            "conversationId": "parent-999",
            "transcriptPath": str(parent_tx),
        }
        proc = subprocess.run(
            [sys.executable, "scripts/post_tool_reconcile.py"],
            input=json.dumps(payload_bind),
            cwd=str(client_agents),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        ledger = read_json(phase_ledger_file(task_dir(inner_fixture.repo, task), "p1"))
        self.assertEqual("reviewer-123", ledger["reviewers"][role]["execution_id"])



if __name__ == "__main__":
    unittest.main()
