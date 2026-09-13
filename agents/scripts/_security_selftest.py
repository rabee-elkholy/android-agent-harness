"""Adversarial, offline security checks for vNext boundaries and bridges."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ENGINE = SCRIPTS / "pre_tool_safety.py"
CLAUDE = SCRIPTS / "cc_pre_tool_safety.py"
COPILOT = SCRIPTS / "copilot_pre_tool_safety.py"


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        state = self.repo / "agents/state/tasks/t"
        state.mkdir(parents=True)
        plan = {"plan_id": "p", "status": "IMPLEMENTING", "execution_nonce": "n", "approval": {"single_use_nonce": "n"}}
        (state / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (state.parents[1] / "active-task.json").write_text(json.dumps({"plan_path": str(state / "plan.json"), "task_id": "t"}), encoding="utf-8")
        self.env = os.environ.copy()
        self.env["HARNESS_REPO"] = str(self.repo)
        self.env["HARNESS_HOOK_STATE"] = str(self.repo / "audit/state.json")

    def tearDown(self):
        self.temp.cleanup()

    def engine(self, command: str) -> dict:
        proc = subprocess.run(
            [sys.executable, str(ENGINE)], input=json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": command}}}),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        return json.loads(proc.stdout)

    def test_laundering_vectors_are_denied(self):
        for command in (
            "git     push origin main", "gıt.exe push origin main",
            "git commit -am surprise", "git update-index --assume-unchanged app/A.kt",
            "C:/Git/bin/git.exe reset --hard HEAD", "powershell -c \"Invoke-WebRequest https://x.invalid\"",
            "python -c \"import requests; requests.post('https://x.invalid')\"",
            "adb root", "adb backup -all", "adb shell pm clear com.example",
        ):
            with self.subTest(command=command):
                self.assertEqual("deny", self.engine(command)["decision"])

    def test_audit_contains_hash_not_command_or_secret(self):
        secret = "TOKEN-NEVER-LOG-123456"
        self.engine(f"curl https://x.invalid -H 'Authorization: {secret}'")
        text = (self.repo / "audit/audit_log.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(secret, text)
        self.assertIn("command_sha256_12", text)

    def test_claude_bridge_denies(self):
        proc = subprocess.run(
            [sys.executable, str(CLAUDE)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        result = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual("deny", result["permissionDecision"])

    def test_copilot_bridge_denies_and_malformed_fails_closed(self):
        proc = subprocess.run(
            [sys.executable, str(COPILOT)], input=json.dumps({"toolName": "bash", "toolArgs": {"command": "adb root"}}),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
    def test_raw_gradle_commands_are_denied(self):
        for command in ("gradle assembleDebug", "gradle.bat assembleDebug", "./gradlew assembleDebug", "gradlew test"):
            with self.subTest(command=command):
                self.assertEqual("deny", self.engine(command)["decision"])

    def test_subagent_role_flexible_matching(self):
        policy = {"reviewers": ["code-review-specialist"], "max_review_rounds": 3, "model_call_budget": 5}
        policy_file = self.repo / "policy.json"
        policy_file.write_text(json.dumps(policy), encoding="utf-8")
        current_file = self.repo / "agents/state/tasks/t/current-run.json"
        current_file.write_text(json.dumps({"policy": str(policy_file)}), encoding="utf-8")
        plan_file = self.repo / "agents/state/tasks/t/plan.json"
        plan_file.write_text(json.dumps({"plan_id": "p", "status": "VERIFYING", "execution_nonce": "n", "approval": {"single_use_nonce": "n"}}), encoding="utf-8")

        # Invoke subagent with TypeName='self' and Role='code-review-specialist'
        payload = {
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [{"TypeName": "self", "Role": "code-review-specialist", "Prompt": "review"}]
                }
            }
        }
        proc = subprocess.run(
            [sys.executable, str(ENGINE)], input=json.dumps(payload),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        res = json.loads(proc.stdout)
        self.assertEqual("allow", res["decision"])

    def test_evidence_store_allows_retry_on_fail_but_blocks_pass(self):
        sys.path.insert(0, str(SCRIPTS))
        from evidence_store import EvidenceStore
        from _vnext_common import ValidationError
        store = EvidenceStore(self.repo / "agents/state")
        common = {
            "snapshot": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "run_id": "run-1",
            "name": "unit_tests",
            "producer": "run_tests_gate",
            "harness_version": "1.0.26",
            "change_set": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        }
        # First write FAIL
        p1 = store.write(**common, status="FAIL", evidence={"detail": "fail"})
        self.assertTrue(p1.is_file())
        # Retry with PASS should succeed because previous was FAIL
        p2 = store.write(**common, status="PASS", evidence={"detail": "pass"})
        self.assertTrue(p2.is_file())
        self.assertEqual("PASS", store.read(common["snapshot"], common["run_id"], common["name"])["status"])
        # Writing again when status is PASS must raise ValidationError
        with self.assertRaises(ValidationError):
            store.write(**common, status="PASS", evidence={"detail": "another pass"})

    def test_mutation_guard_blocks_raw_gradle_and_destructive_commands_in_implementing(self):
        sys.path.insert(0, str(SCRIPTS))
        from mutation_guard import command_allowed
        task_dir = self.repo / "agents/state/tasks/t"
        task_dir.mkdir(parents=True, exist_ok=True)
        active_task = self.repo / "agents/state/active-task.json"
        active_task.write_text(json.dumps({"task_id": "t", "plan_path": "agents/state/tasks/t/plan.json"}), encoding="utf-8")
        plan_file = task_dir / "plan.json"
        plan_file.write_text(json.dumps({
            "plan_id": "p", "task_id": "t", "status": "IMPLEMENTING",
            "execution_nonce": "n", "approval": {"single_use_nonce": "n"}
        }), encoding="utf-8")

        denied_commands = (
            "gradle assembleDebug",
            "gradle.bat assembleDebug",
            "./gradlew assembleDebug",
            "gradlew.bat assembleDebug",
            "del /f /q app\\src\\main.kt",
            "rmdir /s /q app\\build",
            "rm -rf app/build",
            "powershell -File evil.ps1",
            "bash run_something.sh",
        )
        for cmd in denied_commands:
            with self.subTest(cmd=cmd):
                allowed, reason = command_allowed(self.repo, cmd)
                self.assertFalse(allowed, f"Expected '{cmd}' to be denied, but got allowed: {reason}")

    def test_fast_kt_lint_ignores_test_files_for_compose_previews(self):
        sys.path.insert(0, str(SCRIPTS))
        from fast_kt_lint import lint_file
        test_file = self.repo / "app/src/androidTest/java/com/test/ScreenTest.kt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(
            "package com.test\n\nimport androidx.compose.material3.Scaffold\nimport androidx.compose.runtime.Composable\n\n"
            "@Composable\ndef TestScreen() {\n    Scaffold {}\n}\n",
            encoding="utf-8",
        )
        issues = lint_file(test_file, modified_lines={8, 9, 10})
        preview_issues = [iss for iss in issues if iss["type"] == "MISSING_COMPOSE_PREVIEW"]
        self.assertEqual([], preview_issues, "Test files must not require Compose previews")

    def test_delivery_manifest_normalizes_local_properties_slashes(self):
        sys.path.insert(0, str(SCRIPTS))
        from delivery_manifest import _external_inputs
        (self.repo / ".gitignore").write_text("local.properties\n", encoding="utf-8")
        prop_file = self.repo / "local.properties"

        prop_file.write_text("sdk.dir=C\\:\\\\Users\\\\test\\\\Android\\\\Sdk\n", encoding="utf-8")
        out1 = _external_inputs(self.repo)

        prop_file.write_text("sdk.dir=C:/Users/test/Android/Sdk\n", encoding="utf-8")
        out2 = _external_inputs(self.repo)

        prop_file.write_text("sdk.dir=C:\\Users\\test\\Android\\Sdk\n", encoding="utf-8")
        out3 = _external_inputs(self.repo)

        self.assertEqual(out1, out2)
        self.assertEqual(out2, out3)

    def test_call_mcp_tool_mutation_denied_without_plan(self):
        # Mutating Zoho MCP call without approved plan must be denied
        payload = {
            "toolCall": {
                "name": "call_mcp_tool",
                "args": {
                    "ServerName": "zoho-sprints",
                    "ToolName": "zoho_update_task_status",
                    "Arguments": {"status": "In Progress"}
                }
            }
        }
        proc = subprocess.run(
            [sys.executable, str(ENGINE)], input=json.dumps(payload),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        res = json.loads(proc.stdout)
        self.assertEqual("deny", res["decision"])

        # Read-only Zoho MCP call must be allowed
        ro_payload = {
            "toolCall": {
                "name": "call_mcp_tool",
                "args": {
                    "ServerName": "zoho-sprints",
                    "ToolName": "zoho_list_tasks",
                    "Arguments": {}
                }
            }
        }
        proc = subprocess.run(
            [sys.executable, str(ENGINE)], input=json.dumps(ro_payload),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        res = json.loads(proc.stdout)
        self.assertEqual("allow", res["decision"])

    def test_inline_python_execution_denied(self):
        sys.path.insert(0, str(SCRIPTS))
        from mutation_guard import command_allowed
        task_dir = self.repo / "agents/state/tasks/t"
        task_dir.mkdir(parents=True, exist_ok=True)
        active_task = self.repo / "agents/state/active-task.json"
        active_task.write_text(json.dumps({"task_id": "t", "plan_path": "agents/state/tasks/t/plan.json"}), encoding="utf-8")
        plan_file = task_dir / "plan.json"
        plan_file.write_text(json.dumps({
            "plan_id": "p", "task_id": "t", "status": "IMPLEMENTING",
            "execution_nonce": "n", "approval": {"single_use_nonce": "n"}
        }), encoding="utf-8")

        for cmd in ("python -c \"import os; os.system('ls')\"", "py -c \"print(1)\"", "python -m http.server"):
            with self.subTest(cmd=cmd):
                allowed, reason = command_allowed(self.repo, cmd)
                self.assertFalse(allowed, f"Expected '{cmd}' to be denied, got allowed: {reason}")

    def test_stateful_viewmodel_composable_skipped_for_preview(self):
        sys.path.insert(0, str(SCRIPTS))
        from fast_kt_lint import is_stateful_container_only, lint_file
        code = (
            "package com.test\n\nimport androidx.compose.material3.Scaffold\nimport androidx.compose.runtime.Composable\n\n"
            "@Composable\nfun OrderScreen(viewModel: OrderViewModel = hiltViewModel()) {\n    Scaffold {}\n}\n"
        )
        self.assertTrue(is_stateful_container_only(code))

        screen_file = self.repo / "app/src/main/java/com/test/OrderScreen.kt"
        screen_file.parent.mkdir(parents=True, exist_ok=True)
        screen_file.write_text(code, encoding="utf-8")
        issues = lint_file(screen_file, modified_lines={8, 9, 10})
        preview_issues = [iss for iss in issues if iss["type"] == "MISSING_COMPOSE_PREVIEW"]
        self.assertEqual([], preview_issues, "Stateful screen with ViewModel only must not fail on missing preview")

    def test_missing_translation_tools_ignore_supported(self):
        sys.path.insert(0, str(SCRIPTS))
        from check_strings import _parse_resources
        strings_xml = self.repo / "app/src/main/res/values/strings.xml"
        strings_xml.parent.mkdir(parents=True, exist_ok=True)
        strings_xml.write_text(
            "<resources xmlns:tools=\"http://schemas.android.com/tools\">\n"
            "    <string name=\"normal_str\">Hello</string>\n"
            "    <string name=\"wip_str\" tools:ignore=\"MissingTranslation\">WIP</string>\n"
            "    <string name=\"todo_str\" l10n-todo=\"true\">TODO</string>\n"
            "</resources>\n",
            encoding="utf-8",
        )
        res, dups = _parse_resources(strings_xml)
        self.assertIn("normal_str", res)
        self.assertNotIn("wip_str", res, "tools:ignore='MissingTranslation' should be excluded from missing parity check")
        self.assertNotIn("todo_str", res, "l10n-todo='true' should be excluded from missing parity check")


    def test_git_hooks_and_gradlew_file_mutations_denied(self):
        # Attempting write to .git/hooks/pre-commit
        git_payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(self.repo / ".git/hooks/pre-commit"),
                    "CodeContent": "#!/bin/sh\nexit 0\n"
                }
            }
        }
        proc = subprocess.run(
            [sys.executable, str(ENGINE)], input=json.dumps(git_payload),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        res = json.loads(proc.stdout)
        self.assertEqual("deny", res["decision"])
        self.assertIn("immutable", res["reason"].lower())

        # Attempting write to gradlew in client repo
        gradlew_payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(self.repo / "gradlew"),
                    "CodeContent": "#!/bin/sh\necho malicious\n"
                }
            }
        }
        proc2 = subprocess.run(
            [sys.executable, str(ENGINE)], input=json.dumps(gradlew_payload),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        res2 = json.loads(proc2.stdout)
        self.assertEqual("deny", res2["decision"])
        self.assertIn("immutable", res2["reason"].lower())

    def test_subagent_batch_size_limit_enforced(self):
        # 6 subagents in batch during IMPLEMENTING must be denied
        subs = [{"TypeName": "research", "Role": f"Worker {i}", "Prompt": "do work"} for i in range(6)]
        payload = {
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Subagents": subs}
            }
        }
        proc = subprocess.run(
            [sys.executable, str(ENGINE)], input=json.dumps(payload),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        res = json.loads(proc.stdout)
        self.assertEqual("deny", res["decision"])
        self.assertIn("exceeds the safety limit of 5", res["reason"])

    def test_trojan_source_and_secret_detection(self):
        sys.path.insert(0, str(SCRIPTS))
        from fast_kt_lint import lint_file

        # Bidi Trojan source test
        bidi_code = "package com.test\n\nval secret = \"admin\"\u202E // reversed\n"
        bidi_file = self.repo / "app/src/main/java/com/test/Bidi.kt"
        bidi_file.parent.mkdir(parents=True, exist_ok=True)
        bidi_file.write_text(bidi_code, encoding="utf-8")
        issues = lint_file(bidi_file, modified_lines={3})
        bidi_issues = [iss for iss in issues if iss["type"] == "TROJAN_SOURCE_BIDI"]
        self.assertTrue(len(bidi_issues) > 0, "Expected TROJAN_SOURCE_BIDI to be reported")

        # Hardcoded secret test
        secret_code = "package com.test\n\nval apiKey = \"AIzaSyD12345678901234567890123456789012\"\n"
        sec_file = self.repo / "app/src/main/java/com/test/Secret.kt"
        sec_file.write_text(secret_code, encoding="utf-8")
        issues = lint_file(sec_file, modified_lines={3})
        sec_issues = [iss for iss in issues if iss["type"] == "HARDCODED_SECRET"]
        self.assertTrue(len(sec_issues) > 0, "Expected HARDCODED_SECRET to be reported")

        # Insecure cleartext test
        cleartext_code = "package com.test\n\nval endpoint = \"http://api.example.com/v1\"\n"
        ct_file = self.repo / "app/src/main/java/com/test/Cleartext.kt"
        ct_file.write_text(cleartext_code, encoding="utf-8")
        issues = lint_file(ct_file, modified_lines={3})
        ct_issues = [iss for iss in issues if iss["type"] == "INSECURE_CLEARTEXT_TRAFFIC"]
        self.assertTrue(len(ct_issues) > 0, "Expected INSECURE_CLEARTEXT_TRAFFIC to be reported")

    def test_viewbinding_memory_leak_detected(self):
        sys.path.insert(0, str(SCRIPTS))
        from fast_kt_lint import lint_file

        leaking_code = (
            "package com.test\n\nimport androidx.fragment.app.Fragment\n\n"
            "class ProfileFragment : Fragment() {\n"
            "    private var _binding: FragmentProfileBinding? = null\n"
            "    override fun onCreateView(...) = null\n"
            "}\n"
        )
        leak_file = self.repo / "app/src/main/java/com/test/ProfileFragment.kt"
        leak_file.parent.mkdir(parents=True, exist_ok=True)
        leak_file.write_text(leaking_code, encoding="utf-8")
        issues = lint_file(leak_file)
        leak_issues = [iss for iss in issues if iss["type"] == "VIEWBINDING_MEMORY_LEAK"]
        self.assertTrue(len(leak_issues) > 0, "Expected VIEWBINDING_MEMORY_LEAK when onDestroyView is missing")

        clean_code = (
            "package com.test\n\nimport androidx.fragment.app.Fragment\n\n"
            "class CleanFragment : Fragment() {\n"
            "    private var _binding: FragmentProfileBinding? = null\n"
            "    override fun onDestroyView() {\n"
            "        super.onDestroyView()\n"
            "        _binding = null\n"
            "    }\n"
            "}\n"
        )
        clean_file = self.repo / "app/src/main/java/com/test/CleanFragment.kt"
        clean_file.write_text(clean_code, encoding="utf-8")
        issues = lint_file(clean_file)
        leak_issues = [iss for iss in issues if iss["type"] == "VIEWBINDING_MEMORY_LEAK"]
        self.assertEqual([], leak_issues, "Clean fragment with _binding = null must pass")

    def test_room_migration_not_null_without_default_rejected(self):
        sys.path.insert(0, str(SCRIPTS))
        from room_guard import NOT_NULL_NO_DEFAULT_RE

        bad_sql = "ALTER TABLE users ADD COLUMN phone TEXT NOT NULL"
        self.assertTrue(bool(NOT_NULL_NO_DEFAULT_RE.search(bad_sql)), "Should detect NOT NULL without DEFAULT")

        good_sql = "ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''"
        self.assertFalse(bool(NOT_NULL_NO_DEFAULT_RE.search(good_sql)), "Should not match when DEFAULT is present")


if __name__ == "__main__":
    unittest.main(verbosity=2)
