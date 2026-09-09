"""Offline contract tests for the compact vNext safety hook."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delivery_manifest import build_manifest  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
ENGINE = SCRIPTS / "pre_tool_safety.py"


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "harness@example.invalid"], cwd=self.repo, check=True)
        (self.repo / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True)
        self.state = self.repo / ".agents/state"
        self.env = os.environ.copy()
        self.env["HARNESS_REPO"] = str(self.repo)
        self.env["HARNESS_HOOK_STATE"] = str(self.state / "hook-state.json")

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name: str, args: dict | None = None, *, stop: bool = False) -> dict:
        payload = {"terminationReason": "model_stop"} if stop else {"toolCall": {"name": name, "args": args or {}}}
        proc = subprocess.run(
            [sys.executable, str(ENGINE)], input=json.dumps(payload), capture_output=True,
            text=True, encoding="utf-8", errors="replace", env=self.env, check=False, timeout=15,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return json.loads(proc.stdout)

    def activate(self, status: str = "IMPLEMENTING", *, external_writes: list[str] | None = None) -> None:
        task = self.state / "tasks/task-one"
        task.mkdir(parents=True, exist_ok=True)
        plan = {
            "plan_id": "plan-one", "status": status, "execution_nonce": "nonce",
            "approval": {"single_use_nonce": "nonce"},
            "external_writes": external_writes or [],
        }
        if status == "READY_FOR_DELIVERY":
            manifest = build_manifest(self.repo)
            plan["ready_delivery_snapshot_sha256"] = manifest["delivery_snapshot_sha256"]
            plan["ready_change_set_sha256"] = manifest["change_set_sha256"]
        (task / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (self.state / "active-task.json").write_text(json.dumps({"task_id": "task-one", "plan_path": str(task / "plan.json")}), encoding="utf-8")

    def test_file_write_requires_plan(self):
        self.assertEqual("deny", self.call("write_to_file", {"TargetFile": "app/A.kt"})["decision"])
        self.activate()
        self.assertEqual("allow", self.call("write_to_file", {"TargetFile": "app/A.kt"})["decision"])

    def test_infrastructure_write_is_always_denied(self):
        self.activate()
        self.assertEqual("deny", self.call("apply_patch", {"path": ".agents/state/fake.json"})["decision"])
        self.assertEqual("deny", self.call("replace_file_content", {"TargetFile": "agents/scripts/x.py"})["decision"])
        self.assertEqual("deny", self.call("write_to_file", {})["decision"])
        self.assertEqual("deny", self.call("write_to_file", {"TargetFile": "../outside.kt"})["decision"])

    def test_verification_reviewer_roster_is_exact(self):
        self.activate("VERIFYING")
        task = self.state / "tasks/task-one"
        policy = task / "policy.json"
        policy.write_text(json.dumps({"reviewers": ["bug-reviewer-agent"], "max_review_rounds": 3, "model_call_budget": 8}), encoding="utf-8")
        (task / "current-run.json").write_text(json.dumps({"policy": str(policy)}), encoding="utf-8")
        good = {"Subagents": [{"TypeName": "bug-reviewer-agent", "model": "inherit"}]}
        missing = {"Subagents": []}
        escalated = {"Subagents": [{"TypeName": "bug-reviewer-agent", "model": "premium"}]}
        self.assertEqual("allow", self.call("invoke_subagent", good)["decision"])
        self.assertEqual("deny", self.call("invoke_subagent", missing)["decision"])
        self.assertEqual("deny", self.call("invoke_subagent", escalated)["decision"])

    def test_read_only_command_without_plan(self):
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "git status"})["decision"])
        self.assertEqual("deny", self.call("run_command", {"CommandLine": "git status && touch owned"})["decision"])
        self.assertEqual("deny", self.call("run_command", {"CommandLine": "git status > app/status.txt"})["decision"])
        self.assertEqual("deny", self.call("run_command", {"CommandLine": "rg safe | tee app/status.txt"})["decision"])
        self.assertEqual("deny", self.call("run_command", {"CommandLine": "rg $(touch app/owned)"})["decision"])

    def test_agent_cannot_manufacture_approval(self):
        for action in ("approve", "approve-sensitive", "cancel"):
            command = f"python .agents/scripts/workflow.py {action} --repo . --task-id t"
            self.assertEqual("deny", self.call("run_command", {"CommandLine": command})["decision"])
        wrapped = "python harness_cli.py task --kit . approve --repo . --task-id t"
        self.assertEqual("deny", self.call("run_command", {"CommandLine": wrapped})["decision"])

    def test_conversation_approval_is_allowed(self):
        cmd = "python .agents/scripts/workflow.py approve --repo . --task-id t --source conversation --proof-reference ok --enforcement-tier RULE_ENFORCED"
        self.assertEqual("allow", self.call("run_command", {"CommandLine": cmd})["decision"])

    def test_developer_terminal_approval_by_agent_is_denied(self):
        cmd = "python .agents/scripts/workflow.py approve --repo . --task-id t --source developer_terminal --proof-reference ok --enforcement-tier RULE_ENFORCED"
        self.assertEqual("deny", self.call("run_command", {"CommandLine": cmd})["decision"])

    def test_conversation_sensitive_approval_is_allowed(self):
        cmd = "python .agents/scripts/workflow.py approve-sensitive --repo . --task-id t --source conversation --proof-reference ok --enforcement-tier RULE_ENFORCED"
        self.assertEqual("allow", self.call("run_command", {"CommandLine": cmd})["decision"])

    def test_developer_terminal_sensitive_approval_by_agent_is_denied(self):
        cmd = "python .agents/scripts/workflow.py approve-sensitive --repo . --task-id t --source developer_terminal --proof-reference ok --enforcement-tier RULE_ENFORCED"
        self.assertEqual("deny", self.call("run_command", {"CommandLine": cmd})["decision"])

    def test_help_command_is_read_only_allowed(self):
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/scripts/workflow.py --help"})["decision"])
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/scripts/workflow.py draft -h"})["decision"])

    def test_ide_artifact_write_is_allowed(self):
        brain_target = str(Path.home() / ".gemini" / "antigravity" / "brain" / "test-convo" / "implementation_plan.md")
        self.assertEqual("allow", self.call("write_to_file", {"TargetFile": brain_target})["decision"])

    def test_external_and_destructive_commands_stay_denied(self):
        self.activate()
        attacks = (
            "git status && git push origin main",
            "git -c core.hooksPath=/dev/null reset --hard HEAD~1",
            "echo Z2l0IHJlc2V0 | base64 -d | sh",
            "adb -s device shell cmd package clear com.example",
            "curl -X POST https://example.invalid/api",
            "python update_zoho.py --status Done",
            "python .agents/scripts/run_device.py install --grant-runtime-permissions",
        )
        for command in attacks:
            with self.subTest(command=command):
                self.assertEqual("deny", self.call("run_command", {"CommandLine": command})["decision"])

    def test_raw_gradle_is_denied_but_gate_is_allowed(self):
        self.activate("VERIFYING")
        self.assertEqual("deny", self.call("run_command", {"CommandLine": "./gradlew :app:testDebugUnitTest"})["decision"])
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/scripts/run_tests_gate.py"})["decision"])
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/scripts/record_review.py --task t --reviewer bug --verdict PASS"})["decision"])

    def test_zoho_mutation_requires_plan_scope_and_operation_id(self):
        self.activate()
        args = {"item_id": "1", "comment": "ready", "operation_id": "task-1-handoff"}
        self.assertEqual("deny", self.call("zoho_add_comment", args)["decision"])
        self.activate(external_writes=["zoho_sprints"])
        self.assertEqual("allow", self.call("zoho_add_comment", args)["decision"])
        self.assertEqual("deny", self.call("zoho_add_comment", {"item_id": "1", "comment": "ready"})["decision"])
        self.assertEqual("deny", self.call("zoho_update_task_status", {"status": "Done", "operation_id": "task-1-done"})["decision"])

    def test_stop_allows_turn_completion(self):
        self.activate("IMPLEMENTING")
        self.assertEqual("allow", self.call("", stop=True)["decision"])
        self.activate("AWAITING_DEVELOPER_APPROVAL")
        self.assertEqual("allow", self.call("", stop=True)["decision"])
        self.activate("READY_FOR_DELIVERY")
        self.assertEqual("allow", self.call("", stop=True)["decision"])

    def test_resume_allowed_in_verifying_and_blocked(self):
        self.activate("VERIFYING")
        cmd = "python .agents/scripts/workflow.py resume --repo . --task-id task-1"
        self.assertEqual("allow", self.call("run_command", {"CommandLine": cmd})["decision"])
        self.activate("BLOCKED")
        self.assertEqual("allow", self.call("run_command", {"CommandLine": cmd})["decision"])

    def test_oversized_and_invalid_payload_fail_closed(self):
        proc = subprocess.run([sys.executable, str(ENGINE)], input="{" + "x" * (5 * 1024 * 1024), capture_output=True, text=True, env=self.env, check=False, timeout=15)
        self.assertEqual("deny", json.loads(proc.stdout)["decision"])
        proc = subprocess.run([sys.executable, str(ENGINE)], input="{bad", capture_output=True, text=True, env=self.env, check=False, timeout=15)
        self.assertEqual("deny", json.loads(proc.stdout)["decision"])

    def test_lifecycle_commands_allowed_without_plan(self):
        commands = (
            "git clone --depth 1 --branch v1.0.3 --single-branch https://github.com/rabee-elkholy/android-agent-harness.git C:/Users/test/.android-harness/kit-stage-v1.0.3",
            'git -C "C:/Users/test/.android-harness/kit-stage-v1.0.3" describe --tags --exact-match',
            'python "C:/Users/test/.android-harness/kit-stage-v1.0.3/harness_cli.py" version --kit "C:/Users/test/.android-harness/kit-stage-v1.0.3"',
            'python "C:/Users/test/.android-harness/kit/agents/scripts/setup_wizard.py" questions --repo .',
            'python "C:/Users/test/.android-harness/kit/harness_cli.py" update --no-refresh --repo . --kit "C:/Users/test/.android-harness/kit" --answers-json "C:/temp/answers.json"',
            'python "C:/Users/test/.android-harness/kit/harness_cli.py" init --replace-legacy --repo . --kit "C:/Users/test/.android-harness/kit" --answers-json "C:/temp/answers.json"',
            'python "C:/Users/test/.android-harness/kit/harness_cli.py" doctor --install-check --repo . --kit "C:/Users/test/.android-harness/kit" --json',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual("allow", self.call("run_command", {"CommandLine": command})["decision"])

    def test_temp_answers_write_allowed_without_plan(self):
        with tempfile.TemporaryDirectory() as external_temp:
            temp_answers = Path(external_temp) / "harness-answers.json"
            self.assertEqual("allow", self.call("write_to_file", {"TargetFile": str(temp_answers)})["decision"])
            temp_script = Path(external_temp) / "evil.py"
            self.assertEqual("deny", self.call("write_to_file", {"TargetFile": str(temp_script)})["decision"])

    def test_search_guard_rules(self):
        # 1. Targeted file search is always allowed
        self.assertEqual("allow", self.call("grep_search", {"SearchPath": "app/src/main/java/com/example/HomeActivity.kt", "Query": "test"})["decision"])
        self.assertEqual("allow", self.call("find_by_name", {"SearchDirectory": "app/src/main/java/com/example/features/login", "Pattern": "*.kt"})["decision"])

        # 2. Broad search during discovery without project_graph is denied
        self.assertEqual("deny", self.call("grep_search", {"SearchPath": "app", "Query": "test"})["decision"])
        self.assertEqual("deny", self.call("find_by_name", {"SearchDirectory": ".", "Pattern": "test"})["decision"])

        # 3. Broad search during VERIFYING is allowed (reviewers never blocked)
        self.activate("VERIFYING")
        self.assertEqual("allow", self.call("grep_search", {"SearchPath": "app", "Query": "test"})["decision"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
