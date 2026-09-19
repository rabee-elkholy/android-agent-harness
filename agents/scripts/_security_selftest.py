"""Adversarial, offline security checks for vNext boundaries and bridges."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
ENGINE = SCRIPTS / "pre_tool_safety.py"
CLAUDE = SCRIPTS / "cc_pre_tool_safety.py"
COPILOT = SCRIPTS / "copilot_pre_tool_safety.py"


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init", "-q"], cwd=self.repo, check=True)
        version_file = SCRIPTS.parent / "VERSION"
        version_str = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.32"
        (self.repo / "agents").mkdir(parents=True, exist_ok=True)
        (self.repo / "agents" / "VERSION").write_text(f"{version_str}\n", encoding="utf-8")
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

    def test_review_text_redaction_covers_android_assignment_and_token_forms(self):
        from _vnext_common import redact_text

        raw = (
            'storePassword="release-secret"\n'
            "api_key = 'AIzaSyD12345678901234567890123456789012'\n"
            '"password": "json-secret-value"\n'
            "endpoint=https://build-user:build-pass@example.invalid/path\n"
            "github_pat_11AA22BB33CC44DD55EE66FF77GG88HH99II00JJ\n"
            "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----\n"
        )
        redacted = redact_text(raw)
        for secret in ("release-secret", "AIzaSy", "json-secret-value", "build-pass", "github_pat_", "private-material"):
            self.assertNotIn(secret, redacted)
        self.assertIn("storePassword=[REDACTED]", redacted)
        self.assertIn("https://build-user:[REDACTED]@example.invalid", redacted)

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


    def test_generic_shell_mutation_bypass_denied(self):
        # SEC-CMD-001: Model attempts to run unapproved executables during IMPLEMENTING
        for cmd in ("node mutate.js", "bash -c 'rm -rf *'", "powershell Remove-Item file.txt", "perl script.pl", "sed -i 's/a/b/' file.kt"):
            with self.subTest(command=cmd):
                self.assertEqual("deny", self.engine(cmd)["decision"])

    def test_generic_mcp_unrecognized_tool_fails_closed(self):
        # SEC-MCP-001: Unrecognized MCP tool must fail closed as write mutation
        proc = subprocess.run(
            [sys.executable, str(ENGINE)],
            input=json.dumps({"toolCall": {"name": "call_mcp_tool", "args": {"ServerName": "custom-server", "ToolName": "delete_entry", "Arguments": {}}}}),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        res = json.loads(proc.stdout)
        self.assertEqual("deny", res["decision"])

    def test_recover_stale_active_task_protection(self):
        # AUTH-RECOVER-001: Healthy active task cannot be wiped by recover_stale
        sys.path.insert(0, str(SCRIPTS))
        from workflow import recover_stale
        import argparse
        from _vnext_common import ValidationError
        args = argparse.Namespace(repo=str(self.repo))
        with self.assertRaises(ValidationError) as ctx:
            recover_stale(args)
        self.assertIn("cannot auto-recover healthy active task", str(ctx.exception).lower())

    def test_review_override_forbidden_on_sensitive_surfaces(self):
        # SENS-REV-001: Sensitive surfaces strictly prohibit review override
        task_id = "t"
        plan_file = self.repo / f"agents/state/tasks/{task_id}/plan.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["expected_surfaces"] = ["AUTH", "BUSINESS_LOGIC"]
        plan["status"] = "VERIFYING"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        policy = {"reviewers": ["security", "correctness"], "surfaces": ["AUTH", "BUSINESS_LOGIC"]}
        policy_file = self.repo / f"agents/state/tasks/{task_id}/policy.json"
        policy_file.write_text(json.dumps(policy), encoding="utf-8")
        from delivery_manifest import build_manifest
        manifest = build_manifest(self.repo)
        current_file = self.repo / f"agents/state/tasks/{task_id}/current-run.json"
        current_file.write_text(json.dumps({
            "task_id": task_id,
            "policy": str(policy_file),
            "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
            "change_set_sha256": manifest["change_set_sha256"],
            "external_inputs_sha256": manifest["external_inputs_sha256"],
            "run_id": "r1",
        }), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "record_review.py"), "--repo", str(self.repo), "--task", task_id, "--override-reviews", "--source", "developer_terminal", "--proof-reference", "bypassed"],
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("strictly forbidden on sensitive surfaces", proc.stderr.lower())

    def test_kotlin_implicit_public_scoped_to_library(self):
        # KOTLIN-API-001: Implicit public declarations in Kotlin do not trigger PUBLIC_API in application projects
        sys.path.insert(0, str(SCRIPTS))
        import change_classifier
        from unittest import mock

        src = self.repo / "app/src/main/kotlin/com/example/MyService.kt"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("package com.example\n\nclass MyService {\n    fun doWork(): Int = 42\n}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)

        # In application project: no PUBLIC_API
        import _product
        with mock.patch.object(_product, "PROJECT_KIND", "application"):
            res_app = change_classifier.classify(self.repo)
            self.assertNotIn("PUBLIC_API", res_app["surfaces"])

        # In library project: triggers PUBLIC_API
        with mock.patch.object(_product, "PROJECT_KIND", "library"):
            res_lib = change_classifier.classify(self.repo)
            self.assertIn("PUBLIC_API", res_lib["surfaces"])

    def test_review_execution_profile_and_antigravity_routing(self):
        # ROUTE-001: Reviewer capability and model routing resolution
        sys.path.insert(0, str(SCRIPTS))
        from review_execution import resolve_execution_profile
        from unittest import mock
        import _product

        task_id = "t"
        plan_file = self.repo / f"agents/state/tasks/{task_id}/plan.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["status"] = "VERIFYING"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        policy = {"reviewers": ["security-reviewer-agent", "convention-reviewer-agent"], "surfaces": ["AUTH"]}
        policy_file = self.repo / "policy.json"
        policy_file.write_text(json.dumps(policy), encoding="utf-8")
        current_file = self.repo / f"agents/state/tasks/{task_id}/current-run.json"
        current_file.write_text(json.dumps({"task_id": task_id, "policy": str(policy_file), "delivery_snapshot_sha256": "snap", "run_id": "r1", "change_set_sha256": "cs"}), encoding="utf-8")

        # When ALLOW_MODEL_ESCALATION is False (default)
        with mock.patch.object(_product, "ALLOW_MODEL_ESCALATION", False):
            prof_default = resolve_execution_profile(self.repo, task_id, host="antigravity")
            self.assertEqual("inherit", prof_default["reviewers"]["security-reviewer-agent"]["preferred_model"])
            self.assertEqual("inherit", prof_default["reviewers"]["convention-reviewer-agent"]["preferred_model"])

        # When ALLOW_MODEL_ESCALATION is True: security-reviewer on AUTH escalates to pro when trusted route configured
        with mock.patch.object(_product, "ALLOW_MODEL_ESCALATION", True):
            with mock.patch("review_execution.load_host_model_routes", return_value={"STRONG": "pro"}):
                prof_escalated = resolve_execution_profile(self.repo, task_id, host="antigravity")
                self.assertEqual("pro", prof_escalated["reviewers"]["security-reviewer-agent"]["preferred_model"])
                self.assertEqual("inherit", prof_escalated["reviewers"]["convention-reviewer-agent"]["preferred_model"])

    def test_DELIVERY_CLEAN_001(self):
        """DELIVERY-CLEAN-001: normal workflow deliver with dirty verified task files -> DENY"""
        from workflow import deliver_task
        from _vnext_common import ValidationError
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init", "-q"], cwd=self.repo, check=True)
        task_id = "t"
        plan_file = self.repo / f"agents/state/tasks/{task_id}/plan.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["status"] = "READY_FOR_DELIVERY"
        plan["ready_delivery_snapshot_sha256"] = "clean_snap"
        plan["expected_files"] = ["app/src/main/Dirty.kt"]
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        dirty = self.repo / "app/src/main/Dirty.kt"
        dirty.parent.mkdir(parents=True, exist_ok=True)
        dirty.write_text("// uncommitted", encoding="utf-8")

        with self.assertRaises(ValidationError) as ctx:
            deliver_task(self.repo, task_id, require_clean_tree=True)
        self.assertIn("with dirty working tree", str(ctx.exception))

    def test_HEAD_LINEAGE_001(self):
        """HEAD-LINEAGE-001: HEAD changes after begin and before prepare-verification -> BLOCK"""
        from workflow import prepare_verification
        from _vnext_common import ValidationError
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init", "-q"], cwd=self.repo, check=True)
        task_id = "t"
        plan_file = self.repo / f"agents/state/tasks/{task_id}/plan.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["status"] = "IMPLEMENTING"
        plan["repository"] = {"head": "0123456789abcdef0123456789abcdef01234567", "branch": "main"}
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        class DummyArgs:
            task_id = "t"
            force = False

        with self.assertRaises(ValidationError) as ctx:
            prepare_verification(self.repo, DummyArgs())
        self.assertIn("lineage mismatch", str(ctx.exception))

    def test_DRIFT_EARLY_001(self):
        """DRIFT-EARLY-001: material surface/module drift -> no new verification run"""
        from workflow import prepare_verification
        from _vnext_common import ValidationError, git_text
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init", "-q"], cwd=self.repo, check=True)
        head = git_text(self.repo, "rev-parse", "HEAD")
        branch = git_text(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        task_id = "t"
        plan_file = self.repo / f"agents/state/tasks/{task_id}/plan.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["status"] = "IMPLEMENTING"
        plan["surfaces"] = ["DOCS"]
        plan["expected_surfaces"] = ["DOCS"]
        plan["modules"] = [":app"]
        plan["expected_modules"] = [":app"]
        plan["repository"] = {"head": head, "branch": branch}
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        auth_file = self.repo / "app/src/main/Auth.kt"
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth_file.write_text("class AuthManager { val token: String = \"\" }", encoding="utf-8")

        class DummyArgs:
            task_id = "t"
            force = False

        with self.assertRaises(ValidationError) as ctx:
            prepare_verification(self.repo, DummyArgs())
        self.assertIn("PLAN_APPROVAL_REQUIRED: material drift detected", str(ctx.exception))
        current_p = self.repo / f"agents/state/tasks/{task_id}/current-run.json"
        self.assertFalse(current_p.exists())

    def test_REVIEW_FRESH_001(self):
        """REVIEW-FRESH-001: repo changes after package freeze -> package generation/ingestion STALE"""
        from workflow import assert_active_run_fresh
        from _vnext_common import ValidationError
        task_id = "t"
        plan_file = self.repo / f"agents/state/tasks/{task_id}/plan.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["status"] = "VERIFYING"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        current_file = self.repo / f"agents/state/tasks/{task_id}/current-run.json"
        current_file.write_text(json.dumps({
            "task_id": task_id,
            "status": "VERIFYING",
            "run_id": "r1",
            "delivery_snapshot_sha256": "old_snapshot",
            "change_set_sha256": "old_cs",
            "external_inputs_sha256": "old_ext",
            "manifest": str(self.repo / "agents/state/manifest.json"),
            "policy": str(self.repo / "policy.json"),
        }), encoding="utf-8")

        with self.assertRaises(ValidationError) as ctx:
            assert_active_run_fresh(self.repo, task_id)
        self.assertIn("stale", str(ctx.exception).lower())

    def test_OVERRIDE_SENSITIVE_001(self):
        """OVERRIDE-SENSITIVE-001: all paths reject sensitive semantic-review override"""
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification, state_root
        from final_verifier import verify
        from evidence_store import EvidenceStore

        task_id = "t-override-sens"
        auth_file = self.repo / "app/src/main/kotlin/com/example/Auth.kt"
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth_file.write_text("package com.example\nclass AuthenticationManager { val token = \"\" }\n", encoding="utf-8")

        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Add auth storage",
            kind="FEATURE",
            expected_surfaces="AUTH,BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        prep_res = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        plan_file = state_root(self.repo) / "tasks" / task_id / "plan.json"

        store = EvidenceStore(state_root(self.repo))
        version_file = SCRIPTS.parent / "VERSION"
        harness_version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"
        store.write(
            snapshot=prep_res["delivery_snapshot_sha256"],
            run_id=prep_res["run_id"],
            name="reviews",
            producer="developer_approval",
            harness_version=harness_version,
            change_set=prep_res["change_set_sha256"],
            status="PASS",
            evidence={
                "developer_override": True,
                "source": "developer_terminal",
                "proof_reference_sha256": "p" * 64,
            },
        )

        res = verify(
            self.repo,
            plan_path=plan_file,
            policy_path=Path(prep_res["policy"]),
            manifest_path=Path(prep_res["manifest"]),
            state_root=state_root(self.repo),
            run_id=prep_res["run_id"],
        )
        self.assertEqual("BLOCKED", res["status"])
        self.assertTrue(any("forbidden for sensitive changes" in r for r in res.get("blocked_by", [])))

    def test_SPEC_001(self):
        """SPEC-001: architectural task routes a real installed spec reviewer"""
        from review_policy import decide
        spec_subagent_path = SCRIPTS.parent / "subagents" / "spec-compliance-agent.json"
        self.assertTrue(spec_subagent_path.is_file(), "spec-compliance-agent.json must exist")
        subagent_data = json.loads(spec_subagent_path.read_text(encoding="utf-8"))
        self.assertEqual("spec-compliance-agent", subagent_data.get("name"))

        skills_root = SCRIPTS.parent / "skills"
        cls_arch = {"surfaces": ["BUSINESS_LOGIC"], "severity": "HIGH", "changed_files": 4, "planning_depth": "ARCHITECTURAL"}
        policy = decide(cls_arch, skills_root)
        self.assertIn("spec-compliance-agent", policy["reviewers"])

    def test_SPEC_002(self):
        """SPEC-002: clean spec reviewer response parses as PASS"""
        from record_review import parse_verdict
        report = parse_verdict(
            "spec-compliance-agent",
            "SPEC_PASS\nEVIDENCE pkg=abcdef123456 cites=0"
        )
        self.assertEqual("PASS", report.get("verdict"))

    def test_MODEL_ROUND_001(self):
        """MODEL-ROUND-001: round 2 finding owner can deterministically promote capability"""
        from review_policy import reviewer_capability_for, CAPABILITY_STRONG
        cap, reas = reviewer_capability_for("bug-reviewer-agent", ["BUSINESS_LOGIC"], severity="HIGH", round_number=2, is_finding_owner=True)
        self.assertEqual(CAPABILITY_STRONG, cap)
        self.assertEqual("HIGH", reas)

    def test_MODEL_ROUND_002(self):
        """MODEL-ROUND-002: non-empty carried_reviews (dicts) cannot crash model resolver"""
        from review_policy import review_execution_requirements
        policy = {
            "surfaces": ["BUSINESS_LOGIC"],
            "severity": "HIGH",
            "reviewers": ["bug-reviewer-agent"],
            "carried_reviews": [{"reviewer": "convention-reviewer-agent", "source_snapshot": "abc"}],
            "later_round_source": {"finding_owners": ["bug-reviewer-agent"]},
            "review_round": 2,
        }
        reqs = review_execution_requirements(policy)
        self.assertIn("bug-reviewer-agent", reqs["reviewers"])

    def test_MODEL_ROUND_003(self):
        """MODEL-ROUND-003: round 3 core judgment reviewer requests STRONG"""
        from review_policy import reviewer_capability_for, CAPABILITY_STRONG
        for r in ("bug-reviewer-agent", "security-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"):
            cap, reas = reviewer_capability_for(r, ["BUSINESS_LOGIC"], severity="MEDIUM", round_number=3)
            self.assertEqual(CAPABILITY_STRONG, cap, f"{r} must be STRONG in round 3")
            self.assertEqual("HIGH", reas)

    def test_MODEL_PORTABILITY_001(self):
        """MODEL-PORTABILITY-001: unknown host -> inherit"""
        from review_execution import resolve_execution_profile
        task_id = "t"
        plan_file = self.repo / f"agents/state/tasks/{task_id}/plan.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["status"] = "VERIFYING"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        policy_file = self.repo / "policy.json"
        policy_file.write_text(json.dumps({"reviewers": ["security-reviewer-agent"], "surfaces": ["AUTH"]}), encoding="utf-8")
        current_file = self.repo / f"agents/state/tasks/{task_id}/current-run.json"
        current_file.write_text(json.dumps({"task_id": task_id, "policy": str(policy_file), "delivery_snapshot_sha256": "snap", "run_id": "r1", "change_set_sha256": "cs"}), encoding="utf-8")

        prof = resolve_execution_profile(self.repo, task_id, host="unknown_platform_host")
        self.assertEqual("inherit", prof["reviewers"]["security-reviewer-agent"]["preferred_model"])

    def test_MODEL_PORTABILITY_002(self):
        """MODEL-PORTABILITY-002: missing local route -> inherit"""
        from review_execution import resolve_execution_profile
        task_id = "t"
        plan_file = self.repo / f"agents/state/tasks/{task_id}/plan.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["status"] = "VERIFYING"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        policy_file = self.repo / "policy.json"
        policy_file.write_text(json.dumps({"reviewers": ["security-reviewer-agent"], "surfaces": ["AUTH"]}), encoding="utf-8")
        current_file = self.repo / f"agents/state/tasks/{task_id}/current-run.json"
        current_file.write_text(json.dumps({"task_id": task_id, "policy": str(policy_file), "delivery_snapshot_sha256": "snap", "run_id": "r1", "change_set_sha256": "cs"}), encoding="utf-8")

        env_routes = json.dumps({"antigravity": {"STANDARD": "inherit"}})
        with mock.patch.dict(os.environ, {"HARNESS_MODEL_ROUTES": env_routes}):
            prof = resolve_execution_profile(self.repo, task_id, host="antigravity")
            self.assertEqual("inherit", prof["reviewers"]["security-reviewer-agent"]["preferred_model"])

    def test_MODEL_AUTH_001(self):
        """MODEL-AUTH-001: main agent cannot invent arbitrary explicit model"""
        task_id = "t"
        plan_file = self.repo / f"agents/state/tasks/{task_id}/plan.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["status"] = "VERIFYING"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        policy_file = self.repo / "policy.json"
        policy_file.write_text(json.dumps({"reviewers": ["bug-reviewer-agent"], "surfaces": ["BUSINESS_LOGIC"]}), encoding="utf-8")
        current_file = self.repo / f"agents/state/tasks/{task_id}/current-run.json"
        current_file.write_text(json.dumps({"task_id": task_id, "policy": str(policy_file), "delivery_snapshot_sha256": "snap", "run_id": "r1", "change_set_sha256": "cs"}), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(ENGINE)],
            input=json.dumps({"toolCall": {"name": "invoke_subagent", "args": {"Subagents": [{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "review", "Model": "unapproved-mega-model"}]}}}),
            capture_output=True, text=True, env=self.env, check=False, timeout=15,
        )
        data = json.loads(proc.stdout)
        self.assertEqual("deny", data["decision"])
        self.assertIn("Reviewer model escalation", data["reason"])

    def test_MODEL_HASH_001(self):
        """MODEL-HASH-001: changing exact host model route does not change authoritative policy hash"""
        from review_policy import decide
        skills_root = SCRIPTS.parent / "skills"
        cls = {"surfaces": ["AUTH", "SECURITY"], "severity": "HIGH", "changed_files": 2}
        p1 = decide(cls, skills_root)
        with mock.patch.dict(os.environ, {"HARNESS_MODEL_ROUTES": json.dumps({"antigravity": {"STRONG": "other-model"}})}):
            p2 = decide(cls, skills_root)
        self.assertEqual(p1["policy_sha256"], p2["policy_sha256"])

    def test_BRIEF_001(self):
        """BRIEF-001: reviewer dispatch receives lean brief and immutable package reference"""
        from review_package import generate_task_brief
        pkg_dir = self.repo / "test_pkg_dir"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        meta = {"run_id": "run-99", "package_sha256": "abcdef1234567890abcdef"}
        plan = {"outcome": "Implement secure auth storage", "kind": "FEATURE"}
        policy = {"surfaces": ["AUTH", "SECURITY"]}
        changes = [{"path": "app/src/main/Auth.kt"}]

        brief_path = generate_task_brief(self.repo, "t1", "security-reviewer-agent", pkg_dir, meta, plan, policy, changes)
        self.assertTrue(brief_path.is_file())
        text = brief_path.read_text(encoding="utf-8")
        self.assertIn("LEAN TASK BRIEF: Security Specialist", text)
        self.assertIn("abcdef123456", text)
        self.assertIn("Auth.kt", text)
        self.assertIn("review-package.md", text)

    def test_REDGREEN_001(self):
        """REDGREEN-001: applicable BUG cannot claim enforced RED->GREEN without bound RED evidence"""
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification, state_root
        from final_verifier import verify

        task_id = "t-redgreen"
        fix_file = self.repo / "app/src/main/kotlin/com/example/Fix.kt"
        fix_file.parent.mkdir(parents=True, exist_ok=True)
        fix_file.write_text("package com.example\nfun bugFix() = true\n", encoding="utf-8")

        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Fix NPE in profile",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        prep_res = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        plan_file = state_root(self.repo) / "tasks" / task_id / "plan.json"

        res = verify(
            self.repo,
            plan_path=plan_file,
            policy_path=Path(prep_res["policy"]),
            manifest_path=Path(prep_res["manifest"]),
            state_root=state_root(self.repo),
            run_id=prep_res["run_id"],
        )
        self.assertEqual("BLOCKED", res["status"])
        self.assertTrue(any("requires bound RED" in r for r in res.get("blocked_by", [])))

    def test_DEVICE_SIGNOFF_001(self):
        """DEVICE-SIGNOFF-001: device-required task cannot complete without current-run developer PASS"""
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification, state_root
        from final_verifier import verify

        task_id = "t-device-signoff"
        ui_file = self.repo / "app/src/main/kotlin/com/example/Ui.kt"
        ui_file.parent.mkdir(parents=True, exist_ok=True)
        ui_file.write_text("package com.example\nimport androidx.compose.runtime.Composable\n@Composable fun MainView() {}\n", encoding="utf-8")

        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Add compose UI screen",
            kind="FEATURE",
            expected_surfaces="COMPOSE_UI,BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit",
            device_strategy="physical-only",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        prep_res = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        plan_file = state_root(self.repo) / "tasks" / task_id / "plan.json"

        res = verify(
            self.repo,
            plan_path=plan_file,
            policy_path=Path(prep_res["policy"]),
            manifest_path=Path(prep_res["manifest"]),
            state_root=state_root(self.repo),
            run_id=prep_res["run_id"],
        )
        self.assertEqual("BLOCKED", res["status"])
        self.assertTrue(any("device verification sign-off is required" in r for r in res.get("blocked_by", [])))

    def test_DEVICE_SIGNOFF_002(self):
        """DEVICE-SIGNOFF-002: post-signoff source/artifact change invalidates old PASS"""
        from evidence_store import EvidenceStore
        from final_verifier import _validate_artifact

        state = self.repo / "agents/state"
        store = EvidenceStore(state)
        old_snapshot = "s1" * 32
        old_cs = "c1" * 32
        run_id = "r1"

        store.write(
            snapshot=old_snapshot, run_id=run_id, name="device_signoff", producer="developer_approval",
            harness_version="1.0.0", change_set=old_cs, status="PASS",
            evidence={"proof_reference": "tested", "proof_reference_sha256": "p" * 64}
        )

        new_cs = "c2" * 32
        rec, err = _validate_artifact(store, old_snapshot, new_cs, run_id, "device_signoff", "1.0.0")
        self.assertIsNotNone(err)
        self.assertIn("change-set mismatch", err)

    def test_ORDER_001(self):
        """ORDER-001: missing reviewer evidence blocks run_device.py install/start"""
        from run_device import _check_device_prerequisites
        import argparse

        task_id = "t"
        state = self.repo / "agents/state"
        task_d = state / "tasks" / task_id
        task_d.mkdir(parents=True, exist_ok=True)

        plan = {
            "task_id": task_id, "status": "VERIFYING", "verification_run_id": "r1",
            "surfaces": ["COMPOSE_UI"], "modules": [":app"], "plan_sha256": "p" * 64,
        }
        (task_d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

        from _vnext_common import canonical_sha256
        policy = {
            "schema_version": 1, "surfaces": ["COMPOSE_UI"], "severity": "MEDIUM",
            "status": "PASS", "reviewers": ["bug-reviewer-agent"],
            "gates": ["preflight", "device"], "device_required": True,
            "project_kind": "application", "classification_sha256": "cls",
        }
        policy["policy_sha256"] = canonical_sha256(policy)
        policy_path = task_d / "policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")

        (task_d / "current-run.json").write_text(json.dumps({
            "task_id": task_id, "policy": str(policy_path),
            "delivery_snapshot_sha256": "snap", "run_id": "r1", "change_set_sha256": "cs",
        }), encoding="utf-8")

        args = argparse.Namespace(action="install", force=False)
        with mock.patch("run_device.REPO", self.repo):
            code = _check_device_prerequisites(args)
            self.assertIsNotNone(code)
            self.assertNotEqual(0, code)

    def test_REVIEW_RERUN_001(self):
        """REVIEW-RERUN-001: post-review production-code fix invalidates prior required reviewer PASS coverage"""
        from review_policy import decide, decide_later_round
        skills_root = SCRIPTS.parent / "skills"
        prior_cls = {"surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"], "severity": "MEDIUM", "changed_files": 2, "changed_lines": 10}
        previous = decide(prior_cls, skills_root)

        fixed_cls = {"surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"], "severity": "MEDIUM", "changed_files": 2, "changed_lines": 15}
        later = decide_later_round(
            fixed_cls, skills_root, previous_policy=previous,
            finding_owners=["bug-reviewer-agent"],
            passed_reviewers=["convention-reviewer-agent", "regression-impact-reviewer-agent"],
            source_snapshot="s1" * 32, source_change_set="cs1" * 32,
            current_change_set="cs2" * 32, source_run_id="r1", round_number=2,
        )
        self.assertEqual([], later["carried_reviews"])
        self.assertEqual(set(previous["reviewers"]), set(later["reviewers"]))

    def test_AUTH_SIGNOFF_001_model_call_denied(self):
        """AUTH-SIGNOFF-001: lead agent cannot invoke device signoff directly through model tool call"""
        from pre_tool_safety import DANGEROUS
        signoff_rule = next((pattern for code, pattern in DANGEROUS if code == "signoff_authority"), None)
        self.assertIsNotNone(signoff_rule)
        self.assertTrue(signoff_rule.search("python .agents/scripts/run_device.py signoff --task-id T1 --proof-reference ok --verdict PASS"))
        self.assertTrue(signoff_rule.search("python run_device.py signoff --task-id T1"))

    def test_AUTH_SIGNOFF_002_freeform_proof_without_authority_denied(self):
        """AUTH-SIGNOFF-002: free-form proof reference without developer_terminal authority returns failure"""
        from run_device import _handle_signoff
        args = argparse.Namespace(
            action="signoff", task_id="T-SIGNOFF-FAIL", proof_reference="looks great to me",
            verdict="PASS", source=None, approval_token=None,
        )
        with mock.patch("run_device.REPO", self.repo):
            code = _handle_signoff(args)
            self.assertEqual(1, code)

    def test_AUTH_DELIVER_001_dirty_override_denied(self):
        """AUTH-DELIVER-001: model dirty-tree delivery override is denied by hook and requires developer_terminal"""
        from pre_tool_safety import DANGEROUS
        override_rule = next((pattern for code, pattern in DANGEROUS if code == "dirty_tree_delivery_override"), None)
        self.assertIsNotNone(override_rule)
        self.assertTrue(override_rule.search("python .agents/scripts/workflow.py deliver --repo . --task-id T1 --allow-dirty-tree"))
        self.assertTrue(override_rule.search("python .agents/scripts/workflow.py deliver --repo . --task-id T1 --developer-allow-dirty-tree"))

        from workflow import deliver_task, ValidationError
        args = argparse.Namespace(repo=str(self.repo), task_id="T1", allow_dirty_tree=True, source=None)
        with self.assertRaises(ValidationError) as ctx:
            deliver_task(args)
        self.assertIn("Dirty-tree delivery override requires explicit developer terminal authority", str(ctx.exception))

    def test_MODEL_KILL_001_global_kill_switch_forces_inherit(self):
        """MODEL-KILL-001: when ALLOW_MODEL_ESCALATION=False, every reviewer unconditionally resolves to inherit"""
        from review_execution import resolve_execution_profile
        task_id = "T-KILL-SWITCH"
        task_d = self.repo / f"agents/state/tasks/{task_id}"
        task_d.mkdir(parents=True, exist_ok=True)
        (task_d / "plan.json").write_text(json.dumps({
            "task_id": task_id, "status": "VERIFYING", "review_rounds": 0, "planning_depth": "BOUNDED",
        }), encoding="utf-8")
        policy_p = task_d / "policy.json"
        policy_p.write_text(json.dumps({
            "surfaces": ["AUTH", "SECURITY"], "severity": "HIGH",
            "reviewers": ["security-reviewer-agent", "bug-reviewer-agent"],
        }), encoding="utf-8")
        (task_d / "current-run.json").write_text(json.dumps({
            "task_id": task_id, "run_id": "r-kill", "policy": str(policy_p),
            "delivery_snapshot_sha256": "snap1", "change_set_sha256": "cs1",
        }), encoding="utf-8")

        with mock.patch("review_execution.load_host_model_routes", return_value={"STRONG": "pro", "STANDARD": "flash"}):
            with mock.patch.dict("os.environ", {"HARNESS_ALLOW_MODEL_ESCALATION": "0"}):
                prof = resolve_execution_profile(self.repo, task_id, host="antigravity")
                self.assertFalse(prof["allow_model_escalation"])
                for rev, info in prof["reviewers"].items():
                    self.assertEqual("inherit", info["preferred_model"], f"{rev} must inherit when kill switch active")
                    self.assertEqual("INHERIT_FALLBACK", info["resolution"])

    def test_MODEL_NAME_001_core_requires_no_provider_literals(self):
        """MODEL-NAME-001: core review_execution requires no hardcoded provider/model literals"""
        from review_execution import load_host_model_routes
        routes = load_host_model_routes("unknown_or_empty_host")
        self.assertEqual({}, routes)
        # Even for antigravity without local config, core default is empty
        ag_routes = load_host_model_routes("antigravity")
        # In absence of ~/.android-harness/model_routes.json, returns empty
        if not (Path.home() / ".android-harness" / "model_routes.json").is_file():
            self.assertEqual({}, ag_routes)

    def test_MODEL_CONFIG_001_model_cannot_write_route_config(self):
        """MODEL-CONFIG-001: model file tools cannot write to user-level harness config or model routes"""
        from pre_tool_safety import _safe_target
        user_routes = str(Path.home() / ".android-harness" / "model_routes.json")
        allowed, reason, _ = _safe_target(user_routes)
        self.assertFalse(allowed)
        self.assertIn("developer-owned and immutable", reason)

    def test_SPEC_PROD_001_architectural_reaches_spec_reviewer(self):
        """SPEC-PROD-001: architectural task reaches spec reviewer through normal lifecycle and planning_depth"""
        from plan_authority import create_plan
        from review_policy import decide
        plan = create_plan(
            self.repo, task_id="T-ARCH-SPEC", requested_outcome="Complete modular migration",
            expected_surfaces=["BUSINESS_LOGIC", "NAVIGATION"], planning_depth="ARCHITECTURAL",
        )
        self.assertEqual("ARCHITECTURAL", plan.get("planning_depth"))
        self.assertIn("planning_depth", plan)

        policy = decide(
            {"surfaces": ["BUSINESS_LOGIC", "NAVIGATION"], "severity": "HIGH", "changed_files": 10, "changed_lines": 300},
            SCRIPTS.parent / "skills",
            plan={"planning_depth": "ARCHITECTURAL"},
        )
        self.assertIn("spec-compliance-agent", policy["reviewers"])

    def test_BRIEF_SCHEMA_001_uses_authoritative_plan_fields(self):
        """BRIEF-SCHEMA-001: generate_task_brief uses requested_outcome, task_kind, and expected_modules"""
        from review_package import generate_task_brief
        pkg_dir = self.repo / "agents/state/pkg_test"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        plan = {
            "requested_outcome": "Strictly implement user login flow",
            "task_kind": "BUG",
            "expected_modules": [":app", ":feature:auth"],
            "expected_surfaces": ["AUTH", "BUSINESS_LOGIC"],
        }
        policy = {"surfaces": ["AUTH", "BUSINESS_LOGIC"]}
        metadata = {"package_sha256": "1234567890abcdef" * 4, "run_id": "r1"}
        brief_p = generate_task_brief(
            self.repo, "T-BRIEF", "bug-reviewer-agent", pkg_dir,
            metadata, plan, policy, [{"path": "app/Login.kt"}],
        )
        content = brief_p.read_text(encoding="utf-8")
        self.assertIn("Strictly implement user login flow", content)
        self.assertIn("**Task Kind**: BUG", content)
        self.assertIn(":feature:auth", content)

    def test_FRESH_EXT_001_external_input_drift_blocks(self):
        """FRESH-EXT-001: external-input drift triggers STALE before review"""
        from workflow import assert_active_run_fresh, ValidationError
        task_id = "T-FRESH-EXT"
        task_d = self.repo / f"agents/state/tasks/{task_id}"
        task_d.mkdir(parents=True, exist_ok=True)
        (task_d / "plan.json").write_text(json.dumps({"task_id": task_id, "status": "VERIFYING"}), encoding="utf-8")
        from delivery_manifest import build_manifest
        m = build_manifest(self.repo)
        (task_d / "current-run.json").write_text(json.dumps({
            "task_id": task_id, "run_id": "r1",
            "delivery_snapshot_sha256": m["delivery_snapshot_sha256"],
            "change_set_sha256": m["change_set_sha256"],
            "external_inputs_sha256": "drifted_external_input_hash",
        }), encoding="utf-8")
        with self.assertRaises(ValidationError) as ctx:
            assert_active_run_fresh(self.repo, task_id)
        self.assertIn("STALE: repository external_inputs_sha256 modified", str(ctx.exception))

    def test_REDGREEN_ID_001_defect_binding(self):
        """REDGREEN-ID-001: failing test in RED that is resolved in GREEN passes, while unresolved fails"""
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification, state_root, _load_plan, load_task_baseline
        from _vnext_common import canonical_sha256, utc_now
        from final_verifier import verify_task
        from evidence_store import EvidenceStore

        version_file = SCRIPTS.parent / "VERSION"
        version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"
        store = EvidenceStore(state_root(self.repo))

        test_file = self.repo / "app/src/test/kotlin/com/example/LoginTest.kt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("package com.example\nclass LoginTest {}\n", encoding="utf-8")

        # Case A: Resolved in GREEN -> PASS
        task_id_a = "t-rg-a"
        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id_a,
            outcome="Fix login defect A",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id_a,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id_a))
        prep_a = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id_a))

        task_a_dir = state_root(self.repo) / "tasks" / task_id_a
        base_a = load_task_baseline(self.repo, task_id_a)
        plan_a = _load_plan(self.repo, task_id_a)
        red_a = {
            "schema_version": 3,
            "task_id": task_id_a,
            "plan_sha256": plan_a["plan_sha256"],
            "captured_at": utc_now(),
            "producer": "run_tests_gate",
            "pre_fix_delivery_snapshot_sha256": "pre_fix_snap_a",
            "pre_fix_change_set_sha256": "pre_fix_cs_a",
            "pre_fix_task_change_set_sha256": "pre_fix_cs_a",
            "baseline_sha256": base_a.get("baseline_sha256", ""),
            "reproduction_kind": "FAILING_TEST",
            "gradle_task": ":app:testDebugUnitTest",
            "failed_tests": [{"test_id": "com.example.LoginTest.testBadPassword", "failure_fingerprint": "fp1"}],
        }
        red_a["red_sha256"] = canonical_sha256({k: v for k, v in red_a.items() if k != "red_sha256"})
        (task_a_dir / "red-evidence.json").write_text(json.dumps(red_a), encoding="utf-8")

        store.write(
            snapshot=prep_a["delivery_snapshot_sha256"],
            run_id=prep_a["run_id"],
            name="unit_tests",
            producer="run_tests_gate",
            harness_version=version,
            change_set=prep_a["change_set_sha256"],
            status="PASS",
            evidence={"executed": 5, "failed": 0, "new_regressions": [], "executed_tests": ["com.example.LoginTest.testBadPassword"]},
        )
        res_a = verify_task(self.repo, task_id_a)
        red_check_a = next((c for c in res_a["checks"] if c["name"] == "red_evidence"), None)
        self.assertIsNotNone(red_check_a)
        self.assertEqual("PASS", red_check_a["status"])

        # Case B: Still failing in GREEN (in new_regressions) -> FAIL
        task_id_b = "t-rg-b"
        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id_b,
            outcome="Fix login defect B",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id_b,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id_b))
        prep_b = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id_b))

        task_b_dir = state_root(self.repo) / "tasks" / task_id_b
        base_b = load_task_baseline(self.repo, task_id_b)
        plan_b = _load_plan(self.repo, task_id_b)
        red_b = {
            "schema_version": 3,
            "task_id": task_id_b,
            "plan_sha256": plan_b["plan_sha256"],
            "captured_at": utc_now(),
            "producer": "run_tests_gate",
            "pre_fix_delivery_snapshot_sha256": "pre_fix_snap_b",
            "pre_fix_change_set_sha256": "pre_fix_cs_b",
            "pre_fix_task_change_set_sha256": "pre_fix_cs_b",
            "baseline_sha256": base_b.get("baseline_sha256", ""),
            "reproduction_kind": "FAILING_TEST",
            "gradle_task": ":app:testDebugUnitTest",
            "failed_tests": [{"test_id": "com.example.LoginTest.testBadPassword", "failure_fingerprint": "fp1"}],
        }
        red_b["red_sha256"] = canonical_sha256({k: v for k, v in red_b.items() if k != "red_sha256"})
        (task_b_dir / "red-evidence.json").write_text(json.dumps(red_b), encoding="utf-8")

        store.write(
            snapshot=prep_b["delivery_snapshot_sha256"],
            run_id=prep_b["run_id"],
            name="unit_tests",
            producer="run_tests_gate",
            harness_version=version,
            change_set=prep_b["change_set_sha256"],
            status="PASS",
            evidence={"executed": 5, "failed": 1, "new_regressions": ["com.example.LoginTest.testBadPassword"]},
        )
        res_b = verify_task(self.repo, task_id_b)
        red_check_b = next((c for c in res_b["checks"] if c["name"] == "red_evidence"), None)
        self.assertIsNotNone(red_check_b)
        self.assertEqual("FAIL", red_check_b["status"])
        self.assertIn("RED defect(s) still failing in GREEN verification", red_check_b["detail"])

    def test_DEVICE_CHAIN_001_artifact_set_mismatch_fails(self):
        """DEVICE-CHAIN-001: final_verifier rejects signoff if artifact_set_sha256 differs from device_install"""
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification, state_root
        from final_verifier import verify_task
        from evidence_store import EvidenceStore

        task_id = "t-dev-chain"
        ui_file = self.repo / "app/src/main/kotlin/com/example/UI.kt"
        ui_file.parent.mkdir(parents=True, exist_ok=True)
        ui_file.write_text("package com.example\nimport androidx.compose.runtime.Composable\n@Composable fun MainView() {}\n", encoding="utf-8")

        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Add UI component",
            kind="FEATURE",
            expected_surfaces="COMPOSE_UI,BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="launch",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        prep_res = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))

        store = EvidenceStore(state_root(self.repo))
        version_file = SCRIPTS.parent / "VERSION"
        version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"

        snap = prep_res["delivery_snapshot_sha256"]
        cs = prep_res["change_set_sha256"]
        run_id = prep_res["run_id"]

        store.write(
            snapshot=snap, run_id=run_id, name="device_install", producer="run_device",
            harness_version=version, change_set=cs, status="PASS",
            evidence={"artifact_set_sha256": "artifact_hash_A"},
        )
        store.write(
            snapshot=snap, run_id=run_id, name="device_launch", producer="run_device",
            harness_version=version, change_set=cs, status="PASS",
            evidence={"artifact_set_sha256": "artifact_hash_A"},
        )
        # Signoff recorded for a different artifact hash B
        store.write(
            snapshot=snap, run_id=run_id, name="device_signoff", producer="developer_approval",
            harness_version=version, change_set=cs, status="PASS",
            evidence={
                "artifact_set_sha256": "artifact_hash_B_mismatch",
                "proof_reference": "ok", "proof_reference_sha256": "proof",
                "approval_source": "developer_terminal",
            },
        )
        res = verify_task(self.repo, task_id)
        signoff_chk = next((c for c in res["checks"] if c["name"] == "device_signoff"), None)
        self.assertIsNotNone(signoff_chk)
        self.assertEqual("FAIL", signoff_chk["status"])
        self.assertIn("device sign-off artifact mismatch", signoff_chk["detail"])

    def test_PLAN_LEGACY_001_dual_validation(self):
        """PLAN-LEGACY-001: active legacy plan without planning_depth passes dual hash validation"""
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification, state_root
        from final_verifier import verify_task
        from plan_authority import legacy_plan_payload, validate_plan_hash
        from _vnext_common import canonical_sha256, read_json

        task_id = "t-plan-legacy"
        legacy_file = self.repo / "app/src/main/kotlin/com/example/Legacy.kt"
        legacy_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_file.write_text("package com.example\nclass Legacy {}\n", encoding="utf-8")

        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Legacy task outcome",
            kind="FEATURE",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        plan_path = state_root(self.repo) / "tasks" / task_id / "plan.json"
        plan = read_json(plan_path)
        # Strip planning_depth to simulate a pre-v1.0.31 plan
        plan.pop("planning_depth", None)
        legacy_hash = canonical_sha256(legacy_plan_payload(plan))
        plan["plan_sha256"] = legacy_hash
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        valid, computed_hash = validate_plan_hash(plan)
        self.assertTrue(valid)
        self.assertEqual(legacy_hash, computed_hash)

        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            source="conversation",
            proof_reference="approved legacy",
            enforcement_tier="RULE_ENFORCED",
        ))
        # Ensure approval recorded the legacy hash
        plan = read_json(plan_path)
        self.assertEqual(legacy_hash, plan["approval"]["plan_sha256"])
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        prep_res = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        res = verify_task(self.repo, task_id)
        # Verify plan hash check did not fail
        self.assertNotIn("plan or approval hash mismatch", res.get("blocked_by") or [])

    def test_BRIEF_RESOLVER_001_path_binding(self):
        """BRIEF-RESOLVER-001: review_execution resolves brief-<rev>.md from state/runs/<snap>/<run>/"""
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification
        from review_package import build_package
        from review_execution import resolve_execution_profile

        task_id = "t-brief-resolve"
        code_file = self.repo / "app/src/main/kotlin/com/example/BriefTest.kt"
        code_file.parent.mkdir(parents=True, exist_ok=True)
        code_file.write_text("package com.example\nclass BriefTest {}\n", encoding="utf-8")

        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Brief path binding test",
            kind="FEATURE",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))

        pkg_path, metadata = build_package(self.repo, task_id)
        self.assertTrue(pkg_path.is_file())

        exec_meta = resolve_execution_profile(self.repo, task_id, host="antigravity")
        self.assertTrue(exec_meta["package_dir"])
        for rev_name, r_info in exec_meta["reviewers"].items():
            self.assertTrue(r_info["brief_path"], f"brief_path empty for {rev_name}")
            self.assertTrue(Path(r_info["brief_path"]).is_file(), f"brief file does not exist: {r_info['brief_path']}")
            self.assertIn(f"brief-{rev_name}.md", r_info["brief_path"])

    def test_SIGNOFF_PROVENANCE_001_tier_and_identity(self):
        """SIGNOFF-PROVENANCE-001: device signoff validates tier consistency and target identity matching"""
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification, state_root
        from final_verifier import verify_task
        from evidence_store import EvidenceStore

        task_id = "t-signoff-prov"
        ui_file = self.repo / "app/src/main/kotlin/com/example/ProvUI.kt"
        ui_file.parent.mkdir(parents=True, exist_ok=True)
        ui_file.write_text("package com.example\nimport androidx.compose.runtime.Composable\n@Composable fun ProvView() {}\n", encoding="utf-8")

        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Device identity test",
            kind="FEATURE",
            expected_surfaces="COMPOSE_UI,BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="launch",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        prep_res = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))

        store = EvidenceStore(state_root(self.repo))
        version_file = SCRIPTS.parent / "VERSION"
        version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"
        snap = prep_res["delivery_snapshot_sha256"]
        cs = prep_res["change_set_sha256"]
        run_id = prep_res["run_id"]

        store.write(
            snapshot=snap, run_id=run_id, name="device_install", producer="run_device",
            harness_version=version, change_set=cs, status="PASS",
            evidence={"artifact_set_sha256": "art1", "target_user": "0", "serial_sha256": "ser1"},
        )
        store.write(
            snapshot=snap, run_id=run_id, name="device_launch", producer="run_device",
            harness_version=version, change_set=cs, status="PASS",
            evidence={"artifact_set_sha256": "art1", "target_user": "0", "serial_sha256": "ser1", "install_reference": "art1"},
        )

        # Case A: signoff overclaims HARD_ENFORCED with developer_terminal -> FAIL
        store.write(
            snapshot=snap, run_id=run_id, name="device_signoff", producer="developer_approval",
            harness_version=version, change_set=cs, status="PASS",
            evidence={
                "artifact_set_sha256": "art1",
                "proof_reference": "signed off", "proof_reference_sha256": "p",
                "approval_source": "developer_terminal",
                "enforcement_tier": "HARD_ENFORCED",
                "target_user": "0", "serial_sha256": "ser1",
            },
        )
        res = verify_task(self.repo, task_id)
        chk = next((c for c in res["checks"] if c["name"] == "device_signoff"), None)
        self.assertIsNotNone(chk)
        self.assertEqual("FAIL", chk["status"])
        self.assertIn("enforcement tier overclaims its source", chk["detail"])

    def test_REDGREEN_EXEC_001_executed_test_required(self):
        """REDGREEN-EXEC-001: RED defect must be executed in GREEN run, not just absent from regressions"""
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification, state_root, _load_plan, load_task_baseline
        from _vnext_common import canonical_sha256, utc_now
        from final_verifier import verify_task
        from evidence_store import EvidenceStore

        version_file = SCRIPTS.parent / "VERSION"
        version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"
        store = EvidenceStore(state_root(self.repo))

        test_file = self.repo / "app/src/test/kotlin/com/example/AuthTest.kt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("package com.example\nclass AuthTest {}\n", encoding="utf-8")

        # Task 1: GREEN ran only OtherTest (RED target NOT executed) -> FAIL
        task_id_1 = "t-rg-exec-fail"
        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id_1,
            outcome="Fix defect 1",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id_1,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id_1))
        prep_1 = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id_1))

        base_1 = load_task_baseline(self.repo, task_id_1)
        plan_1 = _load_plan(self.repo, task_id_1)
        red_1 = {
            "schema_version": 3,
            "task_id": task_id_1,
            "plan_sha256": plan_1["plan_sha256"],
            "captured_at": utc_now(),
            "producer": "run_tests_gate",
            "pre_fix_delivery_snapshot_sha256": "pre_fix_snap_1",
            "pre_fix_change_set_sha256": "pre_fix_cs_1",
            "pre_fix_task_change_set_sha256": "pre_fix_cs_1",
            "baseline_sha256": base_1.get("baseline_sha256", ""),
            "reproduction_kind": "FAILING_TEST",
            "gradle_task": ":app:testDebugUnitTest",
            "failed_tests": [{"test_id": "com.example.AuthTest.testTokenExpiry", "failure_fingerprint": "fp1"}],
        }
        red_1["red_sha256"] = canonical_sha256({k: v for k, v in red_1.items() if k != "red_sha256"})
        (state_root(self.repo) / "tasks" / task_id_1 / "red-evidence.json").write_text(json.dumps(red_1), encoding="utf-8")

        # GREEN run ran unrelated test only
        store.write(
            snapshot=prep_1["delivery_snapshot_sha256"],
            run_id=prep_1["run_id"],
            name="unit_tests",
            producer="run_tests_gate",
            harness_version=version,
            change_set=prep_1["change_set_sha256"],
            status="PASS",
            evidence={"executed": 1, "failed": 0, "new_regressions": [], "executed_tests": ["com.example.OtherTest.testUnrelated"]},
        )
        res1 = verify_task(self.repo, task_id_1)
        chk1 = next((c for c in res1["checks"] if c["name"] == "red_evidence"), None)
        self.assertIsNotNone(chk1)
        self.assertEqual("FAIL", chk1["status"])
        self.assertIn("not executed in GREEN verification run", chk1["detail"])

        # Task 2: GREEN ran AuthTest.testTokenExpiry -> PASS
        task_id_2 = "t-rg-exec-pass"
        draft(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id_2,
            outcome="Fix defect 2",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id_2,
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id_2))
        prep_2 = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id_2))

        base_2 = load_task_baseline(self.repo, task_id_2)
        plan_2 = _load_plan(self.repo, task_id_2)
        red_2 = {
            "schema_version": 3,
            "task_id": task_id_2,
            "plan_sha256": plan_2["plan_sha256"],
            "captured_at": utc_now(),
            "producer": "run_tests_gate",
            "pre_fix_delivery_snapshot_sha256": "pre_fix_snap_2",
            "pre_fix_change_set_sha256": "pre_fix_cs_2",
            "pre_fix_task_change_set_sha256": "pre_fix_cs_2",
            "baseline_sha256": base_2.get("baseline_sha256", ""),
            "reproduction_kind": "FAILING_TEST",
            "gradle_task": ":app:testDebugUnitTest",
            "failed_tests": [{"test_id": "com.example.AuthTest.testTokenExpiry", "failure_fingerprint": "fp2"}],
        }
        red_2["red_sha256"] = canonical_sha256({k: v for k, v in red_2.items() if k != "red_sha256"})
        (state_root(self.repo) / "tasks" / task_id_2 / "red-evidence.json").write_text(json.dumps(red_2), encoding="utf-8")

        store.write(
            snapshot=prep_2["delivery_snapshot_sha256"],
            run_id=prep_2["run_id"],
            name="unit_tests",
            producer="run_tests_gate",
            harness_version=version,
            change_set=prep_2["change_set_sha256"],
            status="PASS",
            evidence={"executed": 1, "failed": 0, "new_regressions": [], "executed_tests": ["com.example.AuthTest.testTokenExpiry"]},
        )
        res2 = verify_task(self.repo, task_id_2)
        chk2 = next((c for c in res2["checks"] if c["name"] == "red_evidence"), None)
        self.assertIsNotNone(chk2)
        self.assertEqual("PASS", chk2["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
