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


def _with_audit_reason(out: dict, env: dict, engine: Path) -> dict:
    """Hook stdout carries only decision/reason; the reason code is in the audit log."""
    state = env.get("HARNESS_HOOK_STATE")
    audit = Path(state).with_name("audit_log.jsonl") if state else Path(engine).resolve().parent.parent / "state" / "audit_log.jsonl"
    lines = audit.read_text(encoding="utf-8").splitlines() if audit.is_file() else []
    if not lines:
        return out
    record = json.loads(lines[-1])
    enriched = {**out, "reason_code": record.get("reason_code")}
    if record.get("mcp_fingerprint"):
        enriched["mcp_fingerprint"] = record["mcp_fingerprint"]
    return enriched


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "harness@example.invalid"], cwd=self.repo, check=True)
        (self.repo / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
        source = self.repo / "app/src/main/kotlin/com/example/MainActivity.kt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("package com.example\nclass MainActivity {}\n", encoding="utf-8")
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
        return _with_audit_reason(json.loads(proc.stdout), self.env, ENGINE)

    def activate(
        self,
        status: str = "IMPLEMENTING",
        *,
        external_writes: list[str] | None = None,
        expected_files: list[str] | None = None,
        expected_surfaces: list[str] | None = None,
        expected_modules: list[str] | None = None,
        test_strategy: str | None = None,
    ) -> None:
        task = self.state / "tasks/task-one"
        task.mkdir(parents=True, exist_ok=True)
        plan = {
            "plan_id": "plan-one", "status": status, "execution_nonce": "nonce",
            "approval": {"single_use_nonce": "nonce"},
            "external_writes": external_writes or [],
        }
        if expected_files is not None:
            plan["expected_files"] = expected_files
        if expected_surfaces is not None:
            plan["expected_surfaces"] = expected_surfaces
        if expected_modules is not None:
            plan["expected_modules"] = expected_modules
        if test_strategy is not None:
            plan["test_strategy"] = test_strategy
        if status == "READY_FOR_DELIVERY":
            manifest = build_manifest(self.repo)
            plan["ready_delivery_snapshot_sha256"] = manifest["delivery_snapshot_sha256"]
            plan["ready_change_set_sha256"] = manifest["change_set_sha256"]
        (task / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (self.state / "active-task.json").write_text(json.dumps({"task_id": "task-one", "plan_path": str(task / "plan.json")}), encoding="utf-8")

    def prepare_reviewer_run(self, task: Path, policy: Path, *, create_package: bool = True) -> Path:
        run_id = "run-one"
        snapshot = "a" * 64
        manifest = task / "manifest.json"
        manifest.write_text(json.dumps({"delivery_snapshot_sha256": snapshot, "change_set_sha256": snapshot}), encoding="utf-8")
        (task / "current-run.json").write_text(
            json.dumps({"policy": str(policy), "run_id": run_id, "manifest": str(manifest)}),
            encoding="utf-8",
        )
        package = self.state / "runs" / snapshot / run_id / "review-package.md"
        if create_package:
            package.parent.mkdir(parents=True, exist_ok=True)
            package.write_text("# Bound review package\n", encoding="utf-8")
        return package

    def test_hook_stdout_matches_antigravity_result_schema(self):
        """Antigravity unmarshals hook stdout with protojson: only decision and reason are known fields."""
        payloads = [
            {"toolCall": {"name": "run_command", "args": {"CommandLine": "git status"}}},
            {"toolCall": {"name": "run_command", "args": {"CommandLine": "git commit -m x"}}},
            {"toolCall": {"name": "write_to_file", "args": {"TargetFile": "app/A.kt"}}},
            {"toolCall": {"name": "call_mcp_tool", "args": {"ServerName": "x", "ToolName": "create_item"}}},
            {"terminationReason": "model_stop"},
        ]
        for payload in payloads:
            proc = subprocess.run(
                [sys.executable, str(ENGINE)], input=json.dumps(payload), capture_output=True,
                text=True, encoding="utf-8", errors="replace", env=self.env, check=False, timeout=15,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual({"decision", "reason"}, set(out), payload)
        # The machine-readable reason code is still recorded, in the audit log.
        audit = [json.loads(line) for line in (self.state / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(record.get("reason_code") for record in audit))

    def test_developer_authority_is_decided_by_subcommand_not_free_text(self):
        """Task text mentioning cancel/approve is ordinary; only the real subcommand and --source matter."""
        allowed = [
            'python .agents/harness.py task draft --task-id t9 --outcome "Fix cancel button crash" --kind BUG',
            'python .agents/harness.py task draft --task-id t9 --outcome "Approve button does nothing" --kind BUG',
            'python .agents/scripts/workflow.py approve --repo . --task-id t --source conversation '
            '--proof-reference "approve plan for task t" --enforcement-tier RULE_ENFORCED',
            'python .agents/harness.py task approve --task-id t --source=conversation --proof-reference "ok, approve it"',
            "python .agents/scripts/workflow.py cancel --help",
            "python .agents/harness.py task approve -h",
        ]
        denied = [
            "python .agents/scripts/workflow.py cancel --repo . --task-id t",
            "python .agents/harness.py task cancel --task-id t",
            "python .agents/harness.py task --json cancel --task-id t",
            'python .agents/scripts/workflow.py approve --task-id t --source developer_terminal --proof-reference "x --source conversation"',
            "python .agents/harness.py task approve --task-id t --proof-reference ok",
            "python .agents/harness.py task approve-sensitive --task-id t --source host_native --proof-reference ok",
            "git status; python .agents/scripts/workflow.py cancel --task-id t",
        ]
        for command in allowed:
            res = self.call("run_command", {"CommandLine": command})
            self.assertNotEqual("DEVELOPER_AUTHORITY", res.get("reason_code"), command)
        for command in denied:
            res = self.call("run_command", {"CommandLine": command})
            self.assertEqual("deny", res["decision"], command)
            self.assertEqual("DEVELOPER_AUTHORITY", res.get("reason_code"), command)

    def test_draft_force_denial_points_to_revise(self):
        """Round 4: an agent fixing a pending plan tried draft --force; the denial must name the real path."""
        res = self.call("run_command", {"CommandLine": 'python .agents/scripts/workflow.py draft --repo . --task-id t --outcome "x" --force'})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("DRAFT_FORCE", res.get("reason_code"))
        self.assertIn("workflow.py revise", res["reason"])

    def test_router_resume_for_stale_ready_delivery_is_allowed(self):
        """The router routes a stale READY task to `task resume`; the hook must not block its own advice."""
        self.activate(status="READY_FOR_DELIVERY")
        res = self.call("run_command", {"CommandLine": "python .agents/harness.py task resume --task-id task-one"})
        self.assertEqual("allow", res["decision"], res.get("reason"))
        # READY still refuses unrelated mutation.
        res = self.call("run_command", {"CommandLine": "python .agents/harness.py test"})
        self.assertEqual("deny", res["decision"])

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

    def test_generated_code_write_is_denied_while_source_is_allowed(self):
        self.activate()
        # Ephemeral build generated paths are denied
        res = self.call("write_to_file", {"TargetFile": "app/build/generated/ksp/debug/kotlin/UserDao_Impl.kt"})
        self.assertEqual("deny", res["decision"])
        self.assertIn("diagnostic evidence only", res["reason"])

        res2 = self.call("replace_file_content", {"TargetFile": "build/intermediates/dummy.txt"})
        self.assertEqual("deny", res2["decision"])

        # Checked-in source files (even if containing 'generated') are allowed
        res3 = self.call("write_to_file", {"TargetFile": "app/src/main/generated/User.kt"})
        self.assertEqual("allow", res3["decision"])

    def test_MUTATION_SCOPE_001_approved_strings_xml_allowed(self):
        self.activate(
            expected_files=["app/src/main/res/values/strings.xml"],
            expected_surfaces=["LOCALIZATION"],
            expected_modules=[":app"],
        )
        res = self.call("write_to_file", {"TargetFile": "app/src/main/res/values/strings.xml"})
        self.assertEqual("allow", res["decision"])
        self.assertEqual("FILE_MUTATION_ALLOWED", res.get("reason_code"))

    def test_MUTATION_SCOPE_002_unrelated_mainactivity_denied(self):
        self.activate(
            expected_files=["app/src/main/res/values/strings.xml"],
            expected_surfaces=["LOCALIZATION"],
            expected_modules=[":app"],
        )
        res = self.call("write_to_file", {"TargetFile": "app/src/main/kotlin/com/example/MainActivity.kt"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("SCOPE_EXPANSION_REQUIRES_REVISED_APPROVAL", res.get("reason_code"))

    def test_MUTATION_SCOPE_002b_strings_plan_does_not_admit_layout_ui(self):
        # Behavioural XML UI is a device surface; a strings-only approval must not cover it.
        self.activate(
            expected_files=["app/src/main/res/values/strings.xml"],
            expected_surfaces=["LOCALIZATION"],
            expected_modules=[":app"],
        )
        res = self.call("write_to_file", {"TargetFile": "app/src/main/res/layout/activity_main.xml"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("SCOPE_EXPANSION_REQUIRES_REVISED_APPROVAL", res.get("reason_code"))

        from plan_authority import check_material_drift
        plan = {
            "expected_files": ["app/src/main/res/values/strings.xml"],
            "expected_surfaces": ["LOCALIZATION"],
            "expected_modules": [":app"],
        }
        self.assertIn(
            "surface:XML_UI",
            check_material_drift(plan, ["RESOURCE_UI", "XML_UI"], [":app"], actual_files=["app/src/main/res/layout/activity_main.xml"]),
        )
        self.assertEqual(
            [],
            check_material_drift(plan, ["LOCALIZATION", "RESOURCE_UI"], [":app"], actual_files=["app/src/main/res/values/strings.xml"]),
        )

    def test_MUTATION_SCOPE_002c_module_inference_uses_plan_modules(self):
        # A plan scoped to the root module must not have app/ targets rewritten to :app.
        self.activate(
            expected_files=["app/src/main/res/values/strings.xml"],
            expected_surfaces=["LOCALIZATION"],
            expected_modules=[":"],
        )
        res = self.call("write_to_file", {"TargetFile": "app/src/main/res/values/strings.xml"})
        self.assertEqual("allow", res["decision"], res.get("reason"))

    def test_MUTATION_SCOPE_003_test_companion_allowed_when_test_strategy_permits(self):
        self.activate(
            expected_files=["app/src/main/kotlin/com/example/Feature.kt"],
            expected_surfaces=["BUSINESS_LOGIC"],
            expected_modules=[":app"],
            test_strategy="ADD_UNIT_TESTS",
        )
        res = self.call("write_to_file", {"TargetFile": "app/src/test/kotlin/com/example/FeatureTest.kt"})
        self.assertEqual("allow", res["decision"])
        self.assertEqual("FILE_MUTATION_ALLOWED", res.get("reason_code"))

    def test_MUTATION_SCOPE_004_protected_path_denial_unchanged(self):
        self.activate(
            expected_files=["app/src/main/kotlin/com/example/Feature.kt"],
            expected_surfaces=["BUSINESS_LOGIC"],
            expected_modules=[":app"],
        )
        res = self.call("write_to_file", {"TargetFile": ".agents/state/config.json"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("PROTECTED_PATH", res.get("reason_code"))

    def test_MUTATION_SCOPE_005_pre_approval_write_denied(self):
        self.activate(
            status="AWAITING_DEVELOPER_APPROVAL",
            expected_files=["app/src/main/kotlin/com/example/Feature.kt"],
            expected_surfaces=["BUSINESS_LOGIC"],
            expected_modules=[":app"],
        )
        res = self.call("write_to_file", {"TargetFile": "app/src/main/kotlin/com/example/Feature.kt"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("FILE_MUTATION_GUARD", res.get("reason_code"))

    def test_MUTATION_SCOPE_006_new_module_or_sensitive_surface_denied(self):
        self.activate(
            expected_files=["app/src/main/kotlin/com/example/Feature.kt"],
            expected_surfaces=["BUSINESS_LOGIC"],
            expected_modules=[":app"],
        )
        res_mod = self.call("write_to_file", {"TargetFile": "feature/src/main/kotlin/com/example/Other.kt"})
        self.assertEqual("deny", res_mod["decision"])
        self.assertEqual("SCOPE_EXPANSION_REQUIRES_REVISED_APPROVAL", res_mod.get("reason_code"))

    def test_MUTATION_SCOPE_007_revised_approval_allows_expanded_target(self):
        self.activate(
            expected_files=["app/src/main/res/values/strings.xml"],
            expected_surfaces=["LOCALIZATION"],
            expected_modules=[":app"],
        )
        res_before = self.call("write_to_file", {"TargetFile": "app/src/main/kotlin/com/example/MainActivity.kt"})
        self.assertEqual("deny", res_before["decision"])
        self.assertEqual("SCOPE_EXPANSION_REQUIRES_REVISED_APPROVAL", res_before.get("reason_code"))

        self.activate(
            expected_files=["app/src/main/res/values/strings.xml", "app/src/main/kotlin/com/example/MainActivity.kt"],
            expected_surfaces=["LOCALIZATION", "BUSINESS_LOGIC"],
            expected_modules=[":app"],
        )
        res_after = self.call("write_to_file", {"TargetFile": "app/src/main/kotlin/com/example/MainActivity.kt"})
        self.assertEqual("allow", res_after["decision"])
        self.assertEqual("FILE_MUTATION_ALLOWED", res_after.get("reason_code"))

    def test_verification_reviewer_roster_is_exact(self):
        self.activate("VERIFYING")
        task = self.state / "tasks/task-one"
        policy = task / "policy.json"
        policy.write_text(json.dumps({"reviewers": ["bug-reviewer-agent"], "max_review_rounds": 3, "model_call_budget": 8}), encoding="utf-8")
        self.prepare_reviewer_run(task, policy)
        good = {"Subagents": [{"TypeName": "bug-reviewer-agent"}]}
        missing = {"Subagents": []}
        escalated = {"Subagents": [{"TypeName": "bug-reviewer-agent", "model": "premium"}]}
        self.assertEqual("allow", self.call("invoke_subagent", good)["decision"])
        receipt_file = task / "reviewer-dispatches" / "bug-reviewer-agent.json"
        self.assertTrue(receipt_file.is_file())
        receipt_data = json.loads(receipt_file.read_text(encoding="utf-8"))
        self.assertEqual("task-one", receipt_data["task_id"])
        self.assertEqual("run-one", receipt_data["run_id"])
        self.assertEqual("bug-reviewer-agent", receipt_data["reviewer"])
        self.assertEqual("antigravity", receipt_data["host"])
        self.assertRegex(receipt_data["review_package_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(receipt_data["receipt_sha256"])
        self.assertEqual("deny", self.call("invoke_subagent", missing)["decision"])
        self.assertEqual("deny", self.call("invoke_subagent", escalated)["decision"])

    def test_reviewer_receipt_write_failure_denies_dispatch(self):
        self.activate("VERIFYING")
        task = self.state / "tasks/task-one"
        policy = task / "policy.json"
        policy.write_text(json.dumps({"reviewers": ["bug-reviewer-agent"], "max_review_rounds": 3, "model_call_budget": 8}), encoding="utf-8")
        self.prepare_reviewer_run(task, policy)
        receipts_dir = task / "reviewer-dispatches"
        receipts_dir.write_text("not a directory", encoding="utf-8")
        good = {"Subagents": [{"TypeName": "bug-reviewer-agent"}]}
        res = self.call("invoke_subagent", good)
        self.assertEqual("deny", res["decision"])
        self.assertIn("REVIEW_RECEIPT_WRITE_FAILED", res["reason"])

    def test_missing_review_package_denies_dispatch_before_model_call(self):
        self.activate("VERIFYING")
        task = self.state / "tasks/task-one"
        policy = task / "policy.json"
        policy.write_text(json.dumps({"reviewers": ["bug-reviewer-agent"], "max_review_rounds": 3, "model_call_budget": 8}), encoding="utf-8")
        self.prepare_reviewer_run(task, policy, create_package=False)
        good = {"Subagents": [{"TypeName": "bug-reviewer-agent"}]}
        res = self.call("invoke_subagent", good)
        self.assertEqual("deny", res["decision"])
        self.assertIn("REVIEW_RECEIPT_WRITE_FAILED", res["reason"])
        self.assertFalse((task / "reviewer-dispatches").exists())

    def test_invalid_review_run_identity_denies_dispatch(self):
        self.activate("VERIFYING")
        task = self.state / "tasks/task-one"
        policy = task / "policy.json"
        policy.write_text(json.dumps({"reviewers": ["bug-reviewer-agent"], "max_review_rounds": 3, "model_call_budget": 8}), encoding="utf-8")
        self.prepare_reviewer_run(task, policy)
        current_path = task / "current-run.json"
        current = json.loads(current_path.read_text(encoding="utf-8"))
        current["run_id"] = "../escape"
        current_path.write_text(json.dumps(current), encoding="utf-8")
        good = {"Subagents": [{"TypeName": "bug-reviewer-agent"}]}
        res = self.call("invoke_subagent", good)
        self.assertEqual("deny", res["decision"])
        self.assertIn("REVIEW_RECEIPT_WRITE_FAILED", res["reason"])

    def test_read_only_command_without_plan(self):
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "git status"})["decision"])
        self.assertEqual("deny", self.call("run_command", {"CommandLine": "git status && touch owned"})["decision"])
        self.assertEqual("deny", self.call("run_command", {"CommandLine": "git status > app/status.txt"})["decision"])
        self.assertEqual("deny", self.call("run_command", {"CommandLine": "rg safe | tee app/status.txt"})["decision"])
        self.assertEqual("deny", self.call("run_command", {"CommandLine": "rg $(touch app/owned)"})["decision"])

    def test_task_context_is_bounded_read_only_discovery(self):
        targeted = "python .agents/scripts/task_context.py --repo . --file app/src/main/kotlin/com/example/MainActivity.kt --json"
        result = self.call("run_command", {"CommandLine": targeted})
        self.assertEqual("allow", result["decision"])
        self.assertIn("targeted task_context executed", result["reason"])
        harness_targeted = "python .agents/harness.py task-context --file app/src/main/kotlin/com/example/MainActivity.kt --json"
        h_result = self.call("run_command", {"CommandLine": harness_targeted})
        self.assertEqual("allow", h_result["decision"])
        self.assertIn("targeted task_context executed", h_result["reason"])
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/harness.py doctor --json"})["decision"])
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/harness.py version"})["decision"])
        self.assertEqual(
            "deny",
            self.call("run_command", {"CommandLine": "python .agents/scripts/task_context.py --repo . --json"})["decision"],
        )
        self.assertEqual(
            "deny",
            self.call("run_command", {"CommandLine": "python .agents/scripts/task_context.py --repo . --file A.kt --out result.json"})["decision"],
        )

    def test_targeted_task_context_satisfies_discovery_anchor(self):
        targeted = "python .agents/scripts/task_context.py --repo . --symbol MainActivity --json"
        self.assertEqual("allow", self.call("run_command", {"CommandLine": targeted})["decision"])
        self.assertEqual("allow", self.call("grep_search", {"SearchPath": "app", "Query": "MainActivity"})["decision"])

    def test_failed_task_context_does_not_satisfy_discovery_anchor(self):
        invalid = "python .agents/scripts/task_context.py --repo . --file app/src/main/Missing.kt --json"
        result = self.call("run_command", {"CommandLine": invalid})
        self.assertEqual("allow", result["decision"])
        self.assertNotIn("targeted task_context executed", result["reason"])
        self.assertEqual("deny", self.call("grep_search", {"SearchPath": "app", "Query": "anything"})["decision"])

    def test_agent_cannot_manufacture_approval(self):
        for action in ("approve", "approve-sensitive", "cancel"):
            command = f"python .agents/scripts/workflow.py {action} --repo . --task-id t"
            self.assertEqual("deny", self.call("run_command", {"CommandLine": command})["decision"])
            harness_cmd = f"python .agents/harness.py task {action} --task-id t"
            self.assertEqual("deny", self.call("run_command", {"CommandLine": harness_cmd})["decision"])
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
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/harness.py preflight"})["decision"])
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/harness.py test"})["decision"])
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/harness.py assemble :app:assembleDebug"})["decision"])
        self.assertEqual("allow", self.call("run_command", {"CommandLine": "python .agents/harness.py verify --task-id t"})["decision"])

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
            command = command.replace("C:/Users/test", Path.home().as_posix())
            with self.subTest(command=command):
                self.assertEqual("allow", self.call("run_command", {"CommandLine": command})["decision"])

    def test_temp_answers_write_allowed_without_plan(self):
        with tempfile.TemporaryDirectory() as external_temp:
            temp_answers = Path(external_temp) / "harness-answers.json"
            self.assertEqual("allow", self.call("write_to_file", {"TargetFile": str(temp_answers)})["decision"])
            temp_script = Path(external_temp) / "evil.py"
            self.assertEqual("deny", self.call("write_to_file", {"TargetFile": str(temp_script)})["decision"])

    def test_search_guard_rules(self):
        # 1. Targeted search before discovery anchor is denied
        self.assertEqual("deny", self.call("grep_search", {"SearchPath": "app/src/main/java/com/example/HomeActivity.kt", "Query": "test"})["decision"])
        self.assertEqual("deny", self.call("find_by_name", {"SearchDirectory": "app/src/main/java/com/example/features/login", "Pattern": "*.kt"})["decision"])

        # 2. Targeted search inside discovered scope is allowed
        from discovery_receipt import create_discovery_receipt, save_discovery_receipt
        target_file = self.repo / "app/src/main/java/com/example/HomeActivity.kt"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("package com.example\nclass HomeActivity\n", encoding="utf-8")
        receipt = create_discovery_receipt(
            mode="TARGETED_GRAPH_CONTEXT",
            query_kind="file",
            query_value="app/src/main/java/com/example/HomeActivity.kt",
            graph_fingerprint="fp1",
            resolved_modules=[":app"],
            resolved_paths=["app/src/main/java/com/example/HomeActivity.kt"],
            resolved_symbols=["HomeActivity"],
            allowed_search_roots=["app/src/main/java/com/example"],
        )
        save_discovery_receipt(self.repo, receipt)
        self.assertEqual("allow", self.call("grep_search", {"SearchPath": "app/src/main/java/com/example/HomeActivity.kt", "Query": "test"})["decision"])

        # 3. Broad search outside discovery scope is denied
        self.assertEqual("deny", self.call("grep_search", {"SearchPath": "app", "Query": "test"})["decision"])
        self.assertEqual("deny", self.call("find_by_name", {"SearchDirectory": ".", "Pattern": "test"})["decision"])

        # 4. In VERIFYING, search is bounded to review scope
        self.activate("VERIFYING")
        task = self.state / "tasks/task-one"
        (task / "current-run.json").write_text(json.dumps({
            "run_id": "run-one",
            "review_scope": {
                "changed_files": ["app/src/main/java/com/example/HomeActivity.kt"],
                "allowed_roots": ["app/src/main/java/com/example"],
                "direct_callers": [],
                "max_graph_hops": 2,
            }
        }), encoding="utf-8")
        self.assertEqual("allow", self.call("grep_search", {"SearchPath": "app/src/main/java/com/example/HomeActivity.kt", "Query": "test"})["decision"])
        res_denied = self.call("grep_search", {"SearchPath": "app", "Query": "test"})
        self.assertEqual("deny", res_denied["decision"])
        self.assertEqual("REVIEW_SCOPE_EXPANSION_REQUIRED", res_denied.get("reason_code"))

    def test_P0_03_explicit_model_argument_denied_and_omission_allowed(self):
        self.activate("VERIFYING")
        task = self.state / "tasks/task-one"
        policy = task / "policy.json"
        policy.write_text(json.dumps({"reviewers": ["bug-reviewer-agent"], "max_review_rounds": 3, "model_call_budget": 8}), encoding="utf-8")
        self.prepare_reviewer_run(task, policy)
        # 1. explicit model="inherit" must be denied under Antigravity-first omission rule
        res1 = self.call("invoke_subagent", {"Subagents": [{"TypeName": "bug-reviewer-agent", "Role": "Bug Reviewer", "Prompt": "review", "model": "inherit"}]})
        self.assertEqual("deny", res1["decision"])
        self.assertEqual("REVIEWER_MODEL_OVERRIDE_FORBIDDEN", res1.get("reason_code"))
        # 2. explicit Model="inherit" must be denied
        res2 = self.call("invoke_subagent", {"Subagents": [{"TypeName": "bug-reviewer-agent", "Role": "Bug Reviewer", "Prompt": "review", "Model": "inherit"}]})
        self.assertEqual("deny", res2["decision"])
        self.assertEqual("REVIEWER_MODEL_OVERRIDE_FORBIDDEN", res2.get("reason_code"))
        # 3. other model must be denied
        res3 = self.call("invoke_subagent", {"Subagents": [{"TypeName": "bug-reviewer-agent", "Role": "Bug Reviewer", "Prompt": "review", "model": "flash"}]})
        self.assertEqual("deny", res3["decision"])
        self.assertEqual("REVIEWER_MODEL_OVERRIDE_FORBIDDEN", res3.get("reason_code"))
        # 4. dispatch WITHOUT model key must be allowed
        res4 = self.call("invoke_subagent", {"Subagents": [{"TypeName": "bug-reviewer-agent", "Role": "Bug Reviewer", "Prompt": "review"}]})
        self.assertEqual("allow", res4["decision"])

    def test_P0_05_multi_replace_file_content_unapproved_denied(self):
        res = self.call("multi_replace_file_content", {
            "TargetFile": "app/src/main/kotlin/com/example/MainActivity.kt",
            "Replacements": [{"TargetContent": "class MainActivity", "ReplacementContent": "class MainActivity2"}],
        })
        self.assertEqual("deny", res["decision"])

    def test_P0_05_multi_replace_file_content_approved_scope(self):
        self.activate("IMPLEMENTING")
        res1 = self.call("multi_replace_file_content", {
            "TargetFile": "app/src/main/kotlin/com/example/MainActivity.kt",
            "Replacements": [{"TargetContent": "class MainActivity", "ReplacementContent": "class MainActivity2"}],
        })
        self.assertEqual("allow", res1["decision"])

        # Protected targets denied
        res2 = self.call("multi_replace_file_content", {
            "TargetFile": ".agents/scripts/workflow.py",
            "Replacements": [{"TargetContent": "x", "ReplacementContent": "y"}],
        })
        self.assertEqual("deny", res2["decision"])

    def test_P0_05_list_dir_intercepted(self):
        res = self.call("list_dir", {"DirectoryPath": "app"})
        self.assertIn("decision", res)

    def test_P0_07_post_tool_reconcile_failed_invoke_sets_env_blocked(self):
        post_script = SCRIPTS / "post_tool_reconcile.py"
        self.assertTrue(post_script.is_file(), "post_tool_reconcile.py must exist")
        self.activate("VERIFYING")
        task = self.state / "tasks/task-one"
        policy = task / "policy.json"
        policy.write_text(json.dumps({"reviewers": ["bug-reviewer-agent"], "max_review_rounds": 3, "model_call_budget": 8}), encoding="utf-8")
        self.prepare_reviewer_run(task, policy)
        current_run = json.loads((task / "current-run.json").read_text(encoding="utf-8"))
        current_run["review_protocol_version"] = 2
        current_run["review_host"] = "antigravity"
        (task / "current-run.json").write_text(json.dumps(current_run), encoding="utf-8")
        # First record dispatch in ledger
        from review_orchestrator import record_dispatch, load_ledger, REVIEW_ENV_BLOCKED
        record_dispatch(self.repo, "task-one", "bug-reviewer-agent")
        # Run post_tool_reconcile with error
        hook_payload = {
            "toolCall": {"name": "invoke_subagent", "args": {"Subagents": [{"TypeName": "bug-reviewer-agent"}]}},
            "error": "Failed to launch subagent: timeout",
        }
        proc = subprocess.run(
            [sys.executable, str(post_script)],
            input=json.dumps(hook_payload),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        current = json.loads((task / "current-run.json").read_text(encoding="utf-8"))
        ledger = load_ledger(task, current["run_id"])
        self.assertEqual(REVIEW_ENV_BLOCKED, ledger["reviewers"]["bug-reviewer-agent"]["state"])
        self.assertIn("timeout", ledger["reviewers"]["bug-reviewer-agent"]["last_error"])

    def test_P1_06_tool_vocabulary_invariants(self):
        try:
            from policy_vocab import ANTIGRAVITY_TOOLS
        except ImportError:
            from antigravity_tools import ANTIGRAVITY_TOOLS
        hooks_path = Path(__file__).resolve().parent.parent / "hooks.json"
        hooks_json = json.loads(hooks_path.read_text(encoding="utf-8"))
        pre_tools = set()
        for feature in hooks_json.values():
            if isinstance(feature, dict):
                for hook in feature.get("PreToolUse", []):
                    for tool in hook.get("matcher", "").split("|"):
                        pre_tools.add(tool.strip())
        self.assertIn("multi_replace_file_content", pre_tools)
        self.assertIn("list_dir", pre_tools)
        post_tools = set()
        for feature in hooks_json.values():
            if isinstance(feature, dict):
                for hook in feature.get("PostToolUse", []):
                    for tool in hook.get("matcher", "").split("|"):
                        post_tools.add(tool.strip())
        self.assertIn("invoke_subagent", post_tools)
        for req in ("run_command", "write_to_file", "replace_file_content", "multi_replace_file_content", "invoke_subagent", "list_dir"):
            self.assertIn(req, ANTIGRAVITY_TOOLS)



class GenericMCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Harness Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "harness@example.invalid"], cwd=self.repo, check=True)
        (self.repo / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
        source = self.repo / "app/src/main/kotlin/com/example/MainActivity.kt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("package com.example\nclass MainActivity {}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True)
        self.state = self.repo / ".agents/state"
        self.env = os.environ.copy()
        self.env["HARNESS_REPO"] = str(self.repo)
        self.env["HARNESS_HOOK_STATE"] = str(self.state / "hook-state.json")

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name: str, args: dict | None = None) -> dict:
        payload = {"toolCall": {"name": name, "args": args or {}}}
        proc = subprocess.run(
            [sys.executable, str(ENGINE)], input=json.dumps(payload), capture_output=True,
            text=True, encoding="utf-8", errors="replace", env=self.env, check=False, timeout=15,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return _with_audit_reason(json.loads(proc.stdout), self.env, ENGINE)

    def activate(self, status: str = "IMPLEMENTING", *, external_writes: list[str] | None = None, nonce: str = "nonce") -> None:
        task = self.state / "tasks/task-mcp"
        task.mkdir(parents=True, exist_ok=True)
        plan = {
            "task_id": "task-mcp",
            "plan_id": "plan-mcp",
            "status": status,
            "execution_nonce": nonce,
            "approval": {"single_use_nonce": nonce},
            "external_writes": external_writes or [],
            "plan_sha256": "abcdef1234567890abcdef1234567890",
        }
        (task / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (self.state / "active-task.json").write_text(json.dumps({"task_id": "task-mcp", "plan_path": str(task / "plan.json")}), encoding="utf-8")

    def test_MCP_001_generic_read_allowed(self):
        """MCP-001: Generic MCP read tools are allowed without external-write scope."""
        self.activate(external_writes=[])
        res1 = self.call("call_mcp_tool", {"ServerName": "figma", "ToolName": "get_file"})
        self.assertEqual("allow", res1["decision"])
        res2 = self.call("call_mcp_tool", {"ServerName": "firebase", "ToolName": "list_projects"})
        self.assertEqual("allow", res2["decision"])
        res3 = self.call("call_mcp_tool", {"ServerName": "notion", "ToolName": "search_pages"})
        self.assertEqual("allow", res3["decision"])

    def test_MCP_002_write_without_scope_denied(self):
        """MCP-002: Mutation without approved external-write scope is denied."""
        self.activate(external_writes=[])
        res = self.call("call_mcp_tool", {"ServerName": "figma", "ToolName": "create_component"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("EXTERNAL_WRITE_SCOPE_REQUIRED", res.get("reason_code"))
        self.assertIn("--external-write mcp:figma", res.get("reason", ""))

    def test_MCP_003_figma_write_with_mcp_figma_allowed(self):
        """MCP-003: Figma write is allowed when mcp:figma is in approved external_writes."""
        self.activate(external_writes=["mcp:figma"])
        res = self.call("call_mcp_tool", {"ServerName": "figma", "ToolName": "create_component"})
        self.assertEqual("allow", res["decision"])

    def test_MCP_004_figma_scope_does_not_authorize_firebase(self):
        """MCP-004: mcp:figma scope does not authorize firebase mutations."""
        self.activate(external_writes=["mcp:figma"])
        res = self.call("call_mcp_tool", {"ServerName": "firebase", "ToolName": "create_app"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("EXTERNAL_WRITE_SCOPE_REQUIRED", res.get("reason_code"))
        self.assertIn("--external-write mcp:firebase", res.get("reason", ""))

    def test_MCP_005_firebase_deploy_with_mcp_firebase_denied(self):
        """MCP-005: High-impact mutation (firebase deploy) with only mcp:firebase is denied."""
        self.activate(external_writes=["mcp:firebase"])
        res = self.call("call_mcp_tool", {"ServerName": "firebase", "ToolName": "firebase_deploy"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("EXTERNAL_HIGH_IMPACT_SCOPE_REQUIRED", res.get("reason_code"))
        self.assertIn("--external-write mcp:firebase:high-impact", res.get("reason", ""))

    def test_MCP_006_firebase_deploy_with_high_impact_scope_allowed(self):
        """MCP-006: High-impact mutation is allowed when mcp:firebase:high-impact is approved."""
        self.activate(external_writes=["mcp:firebase:high-impact"])
        res = self.call("call_mcp_tool", {"ServerName": "firebase", "ToolName": "firebase_deploy"})
        self.assertEqual("allow", res["decision"])

    def test_MCP_007_unknown_tool_denied(self):
        """MCP-007: Tools that cannot be safely classified fail closed."""
        self.activate(external_writes=["mcp:figma", "mcp:figma:high-impact"])
        res = self.call("call_mcp_tool", {"ServerName": "figma", "ToolName": "arbitrary_custom_action"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("UNKNOWN_MCP_TOOL", res.get("reason_code"))

    def test_MCP_008_read_like_prefix_containing_mutation_keyword_is_not_treated_read_only(self):
        """MCP-008: Read prefix with mutation keyword (e.g. get_or_create_user) is treated as write."""
        self.activate(external_writes=[])
        res = self.call("call_mcp_tool", {"ServerName": "backend", "ToolName": "get_or_create_user"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("EXTERNAL_WRITE_SCOPE_REQUIRED", res.get("reason_code"))

    def test_MCP_009_write_like_tool_cannot_disguise_itself_with_get(self):
        """MCP-009: High-impact tool prefixed with get (e.g. get_and_delete_account) is high-impact."""
        self.activate(external_writes=["mcp:auth"])
        res = self.call("call_mcp_tool", {"ServerName": "auth", "ToolName": "get_and_delete_account"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("EXTERNAL_HIGH_IMPACT_SCOPE_REQUIRED", res.get("reason_code"))

    def test_MCP_010_old_revised_invalidated_approval_cannot_mutate(self):
        """MCP-010: Plan with invalidated approval nonce cannot execute mutations."""
        task = self.state / "tasks/task-mcp"
        task.mkdir(parents=True, exist_ok=True)
        plan = {
            "task_id": "task-mcp",
            "status": "IMPLEMENTING",
            "execution_nonce": "nonce-new",
            "approval": {"single_use_nonce": "nonce-old"},
            "external_writes": ["mcp:figma"],
            "plan_sha256": "abcdef1234567890abcdef1234567890",
        }
        (task / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (self.state / "active-task.json").write_text(json.dumps({"task_id": "task-mcp", "plan_path": str(task / "plan.json")}), encoding="utf-8")
        res = self.call("call_mcp_tool", {"ServerName": "figma", "ToolName": "create_frame"})
        self.assertEqual("deny", res["decision"])
        self.assertEqual("PLAN_NOT_APPROVED", res.get("reason_code"))

    def test_MCP_011_generic_call_receives_no_injected_operation_id(self):
        """MCP-011: Generic MCP tools do not receive an injected operation_id."""
        self.activate(external_writes=["mcp:figma"])
        tool_args = {"name": "Frame 1", "width": 100}
        res = self.call("call_mcp_tool", {"ServerName": "figma", "ToolName": "create_frame", "Arguments": tool_args})
        self.assertEqual("allow", res["decision"])
        self.assertNotIn("operation_id", tool_args)

    def test_MCP_012_local_audit_fingerprint_created(self):
        """MCP-012: Local audit fingerprint is created and recorded for generic mutations."""
        self.activate(external_writes=["mcp:figma"])
        res = self.call("call_mcp_tool", {
            "ServerName": "figma",
            "ToolName": "create_frame",
            "Arguments": {"name": "Header", "secret_key": "my-token"},
        })
        self.assertEqual("allow", res["decision"])
        fp = res.get("mcp_fingerprint")
        self.assertTrue(bool(fp), "Audit fingerprint must be returned")
        audit_file = self.state / "audit_log.jsonl"
        self.assertTrue(audit_file.is_file())
        lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        matched = [rec for rec in lines if rec.get("mcp_fingerprint") == fp]
        self.assertEqual(1, len(matched))

    def test_MCP_013_zoho_still_uses_specialized_integration(self):
        """MCP-013: Zoho calls resolve to specialized integration requiring operation_id and policy."""
        # 1. Generic scope does not authorize specialized Zoho integration
        self.activate(external_writes=["mcp:zoho-sprints"])
        res1 = self.call("call_mcp_tool", {
            "ServerName": "zoho-sprints",
            "ToolName": "zoho_update_task_status",
            "Arguments": {"item_id": "1", "status": "In progress", "operation_id": "op-1"},
        })
        self.assertEqual("deny", res1["decision"])
        self.assertIn("zoho_sprints", res1.get("reason", ""))

        # 2. Specialized scope approved, but missing operation_id is rejected by specialized integration
        self.activate(external_writes=["zoho_sprints"])
        res2 = self.call("call_mcp_tool", {
            "ServerName": "zoho-sprints",
            "ToolName": "zoho_update_task_status",
            "Arguments": {"item_id": "1", "status": "In progress"},
        })
        self.assertEqual("deny", res2["decision"])
        self.assertIn("require a stable operation_id", res2.get("reason", ""))

    def test_MCP_014_model_cannot_self_add_mcp_scope_after_approval(self):
        """MCP-014: Direct modification of plan.json by file tools is blocked."""
        self.activate(external_writes=[])
        plan_path = self.state / "tasks/task-mcp/plan.json"
        res = self.call("replace_file_content", {
            "TargetFile": str(plan_path),
            "Instruction": "add scope",
            "Description": "hack",
            "TargetContent": '"external_writes": []',
            "ReplacementContent": '"external_writes": ["mcp:firebase:high-impact"]',
            "StartLine": 1,
            "EndLine": 10,
            "AllowMultiple": False,
        })
        self.assertEqual("deny", res["decision"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
