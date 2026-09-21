"""Offline golden and idempotency tests for the retained Zoho workflow."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
MCP = HERE.parent / "mcp" / "zoho_sprints"
sys.path.insert(0, str(MCP))

from _idempotency import _ledger_lock, execute_once  # noqa: E402

SPEC = importlib.util.spec_from_file_location("zoho_vnext_server", MCP / "server.py")
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class FakeAPI:
    item_prefix = "SP-"
    fallback_item_type_id = "type-task"
    fallback_priority_id = "prio-medium"

    def __init__(self):
        self.status_updates = 0

    def get_statuses(self):
        return {"statusJObj": {"todo": ["To do"], "progress": ["In progress"], "retest": ["Ready To ReTest"], "done": ["Done"]}}

    def get_item_types(self):
        return {"projItemTypeJObj": {"type-task": ["", "Task"], "type-bug": ["", "Bug"]}}

    def get_priorities(self):
        return {"projPriorityJObj": {"prio-medium": ["Medium"]}}

    def resolve_item(self, item_id, sprint_id=None):
        return sprint_id or "sprint-1", str(item_id)

    def update_item_status(self, sprint_id, item_id, status_id):
        self.status_updates += 1
        return {"status": "success", "sprint": sprint_id, "item": item_id, "status_id": status_id}


class ZohoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.temp.name) / "operations.json"
        self._prev_ledger = os.environ.get("ANDROID_HARNESS_ZOHO_LEDGER")
        os.environ["ANDROID_HARNESS_ZOHO_LEDGER"] = str(self.ledger)

    def tearDown(self):
        if self._prev_ledger is None:
            os.environ.pop("ANDROID_HARNESS_ZOHO_LEDGER", None)
        else:
            os.environ["ANDROID_HARNESS_ZOHO_LEDGER"] = self._prev_ledger
        self.temp.cleanup()

    def test_tool_names_remain_compatible(self):
        self.assertEqual(
            ["zoho_list_sprints", "zoho_list_tasks", "zoho_get_task_details", "zoho_create_task", "zoho_update_task_status", "zoho_add_comment", "zoho_update_task_description"],
            [tool["name"] for tool in server.TOOLS],
        )

    def test_completed_retry_returns_same_result_without_second_write(self):
        calls = []
        arguments = {"item_id": "1", "status": "In progress", "operation_id": "SP-1-start"}
        first = execute_once("status", arguments, lambda: calls.append(1) or {"status": "success"})
        second = execute_once("status", arguments, lambda: calls.append(2) or {"status": "wrong"})
        self.assertEqual({"status": "success"}, first)
        self.assertEqual(first, second)
        self.assertEqual([1], calls)

    def test_same_id_with_different_content_is_refused(self):
        execute_once("comment", {"comment": "one", "operation_id": "SP-1-report"}, lambda: {"status": "success"})
        with self.assertRaises(RuntimeError):
            execute_once("comment", {"comment": "two", "operation_id": "SP-1-report"}, lambda: {})

    def test_unknown_outcome_blocks_blind_retry(self):
        with self.assertRaises(OSError):
            execute_once("comment", {"comment": "one", "operation_id": "SP-2-report"}, lambda: (_ for _ in ()).throw(OSError("timeout")))
        with self.assertRaisesRegex(RuntimeError, "outcome is unknown"):
            execute_once("comment", {"comment": "one", "operation_id": "SP-2-report"}, lambda: {})

    def test_stale_corrupt_lock_is_recovered(self):
        lock = self.ledger.with_suffix(self.ledger.suffix + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("corrupt", encoding="ascii")
        old = lock.stat().st_mtime - 60
        os.utime(lock, (old, old))
        with _ledger_lock(self.ledger):
            self.assertTrue(lock.exists())
        self.assertFalse(lock.exists())

    def test_done_is_rejected_even_if_remote_metadata_exposes_it(self):
        api = FakeAPI()
        with mock.patch.object(server, "get_api", return_value=api):
            with self.assertRaisesRegex(RuntimeError, "forbidden"):
                server.handle_call_tool("zoho_update_task_status", {"sprint_id": "sprint-1", "item_id": "1", "status": "Done", "operation_id": "SP-1-done"})
        self.assertEqual(0, api.status_updates)

    def test_status_write_is_idempotent_through_server(self):
        api = FakeAPI()
        arguments = {"sprint_id": "sprint-1", "item_id": "1", "status": "In progress", "operation_id": "SP-1-start"}
        with mock.patch.object(server, "get_api", return_value=api):
            first = server.handle_call_tool("zoho_update_task_status", arguments)
            second = server.handle_call_tool("zoho_update_task_status", arguments)
        self.assertEqual(json.loads(first["content"][0]["text"]), json.loads(second["content"][0]["text"]))
        self.assertEqual(1, api.status_updates)
        self.assertEqual("success", json.loads(first["content"][0]["text"])["status"])

    def test_missing_or_blank_operation_id_is_strictly_rejected(self):
        calls = []
        # Missing operation_id
        with self.assertRaisesRegex(RuntimeError, "operation_id is required"):
            execute_once("status", {"item_id": "1", "status": "In progress"}, lambda: calls.append(1) or {"status": "ok"})
        self.assertEqual(0, len(calls))

        # Blank operation_id
        with self.assertRaisesRegex(RuntimeError, "operation_id is required"):
            execute_once("status", {"item_id": "1", "status": "In progress", "operation_id": "   "}, lambda: calls.append(1) or {"status": "ok"})
        self.assertEqual(0, len(calls))

    def test_schemas_require_operation_id_for_mutations_only(self):
        mutation_tools = {
            "zoho_create_task",
            "zoho_update_task_status",
            "zoho_add_comment",
            "zoho_update_task_description",
        }
        for tool in server.TOOLS:
            schema = tool.get("inputSchema") or {}
            required = schema.get("required") or []
            if tool["name"] in mutation_tools:
                self.assertIn("operation_id", required, f"{tool['name']} must require operation_id")
            else:
                self.assertNotIn("operation_id", required, f"{tool['name']} should not require operation_id")

class ZohoPolicyTests(unittest.TestCase):
    """ZOHO-001 through ZOHO-009: Deterministic Zoho integration policy tests."""

    def setUp(self) -> None:
        sys.path.insert(0, str(HERE))
        from integrations.zoho_sprints.policy import ZohoPolicyResolver
        from integrations.zoho_sprints.integration import ZohoSprintsIntegration
        from integrations.base import validate_external_write
        self.resolver = ZohoPolicyResolver
        self.integ = ZohoSprintsIntegration()
        self.validate_write = validate_external_write

    def test_ZOHO_001_and_002_bug_delivery_report_in_comment_description_preserved(self) -> None:
        """ZOHO-001 & ZOHO-002: Bug delivery report goes to Comment; Bug description edit rejected."""
        res = self.resolver.resolve(
            item_type="Bug",
            task_state="READY_FOR_DELIVERY",
            delivery_state="GATES_PASSED",
            approved_external_write_scope=["zoho_sprints"],
        )
        self.assertTrue(res["allowed"])
        self.assertEqual("ADD_COMMENT", res["action"])
        self.assertEqual("Ready To ReTest", res["status"])
        self.assertEqual("BUG_COMMENT", res["template"])

        # Attempt to edit Bug description via tool
        plan = {
            "status": "READY_FOR_DELIVERY",
            "execution_nonce": "nonce-bug",
            "approval": {"single_use_nonce": "nonce-bug"},
            "external_writes": ["zoho_sprints"],
        }
        allowed, reason = self.validate_write(
            self.integ,
            "zoho_update_task_description",
            {"item_type": "Bug", "description": "mod", "operation_id": "op-bug-desc"},
            plan,
        )
        self.assertFalse(allowed)
        self.assertIn("Editing Bug description is strictly prohibited", reason)

    def test_ZOHO_003_and_004_task_story_report_in_description_commit_in_comment(self) -> None:
        """ZOHO-003 & ZOHO-004: Task/Story report goes to Description; short commit comment."""
        for itype in ("Task", "Story"):
            with self.subTest(item_type=itype):
                res = self.resolver.resolve(
                    item_type=itype,
                    task_state="READY_FOR_DELIVERY",
                    delivery_state="GATES_PASSED",
                    approved_external_write_scope=["zoho_sprints"],
                )
                self.assertTrue(res["allowed"])
                self.assertEqual("UPDATE_DESCRIPTION", res["action"])
                self.assertEqual("ADD_COMMENT", res["secondary_action"])
                self.assertEqual("Ready To ReTest", res["status"])

    def test_ZOHO_005_plan_approval_in_progress_only_when_external_write_approved(self) -> None:
        """ZOHO-005: Plan approval transitions to In progress only when external write is approved."""
        res_ok = self.resolver.resolve(
            item_type="Task",
            task_state="IMPLEMENTING",
            approved_external_write_scope=["zoho_sprints"],
        )
        self.assertTrue(res_ok["allowed"])
        self.assertEqual("UPDATE_STATUS", res_ok["action"])
        self.assertEqual("In progress", res_ok["status"])

        res_denied = self.resolver.resolve(
            item_type="Task",
            task_state="IMPLEMENTING",
            approved_external_write_scope=[],
        )
        self.assertFalse(res_denied["allowed"])
        self.assertIn("EXTERNAL_WRITE_SCOPE_REQUIRED", res_denied["denied_reason"])

    def test_ZOHO_006_delivery_ready_to_retest_never_done_or_solved(self) -> None:
        """ZOHO-006: Delivery transitions to Ready To ReTest, never Done or Solved."""
        res = self.resolver.resolve(
            item_type="Task",
            task_state="READY_FOR_DELIVERY",
            delivery_state="GATES_PASSED",
            approved_external_write_scope=["zoho_sprints"],
        )
        self.assertEqual("Ready To ReTest", res["status"])

        plan = {
            "status": "READY_FOR_DELIVERY",
            "execution_nonce": "nonce-done",
            "approval": {"single_use_nonce": "nonce-done"},
            "external_writes": ["zoho_sprints"],
        }
        for bad_status in ("Done", "Solved", "Closed", "Completed"):
            with self.subTest(bad_status=bad_status):
                allowed, reason = self.validate_write(
                    self.integ,
                    "zoho_update_task_status",
                    {"status": bad_status, "operation_id": f"op-{bad_status}"},
                    plan,
                )
                self.assertFalse(allowed)
                self.assertIn("Terminal tracker states", reason)

    def test_ZOHO_007_missing_external_scope_fails_closed(self) -> None:
        """ZOHO-007: Missing external write scope fails closed with EXTERNAL_WRITE_SCOPE_REQUIRED."""
        plan_no_scope = {
            "status": "IMPLEMENTING",
            "execution_nonce": "n1",
            "approval": {"single_use_nonce": "n1"},
            "external_writes": [],
        }
        allowed, reason = self.validate_write(
            self.integ,
            "zoho_update_task_status",
            {"status": "In progress", "operation_id": "op-noscope"},
            plan_no_scope,
        )
        self.assertFalse(allowed)
        self.assertIn("EXTERNAL_WRITE_SCOPE_REQUIRED", reason)

    def test_ZOHO_008_denied_external_write_never_generates_bypass_script(self) -> None:
        """ZOHO-008: Denied external write provides remediation advice, not bypass script."""
        plan = {
            "status": "IMPLEMENTING",
            "execution_nonce": "n1",
            "approval": {"single_use_nonce": "n1"},
            "external_writes": [],
        }
        allowed, reason = self.validate_write(
            self.integ,
            "zoho_update_task_status",
            {"status": "In progress", "operation_id": "op-remediate"},
            plan,
        )
        self.assertFalse(allowed)
        self.assertIn("workflow.py revise --external-write zoho_sprints", reason)

    def test_ZOHO_009_language_template_obeys_configured_language(self) -> None:
        """ZOHO-009: Language template formatting obeys configured ZOHO_LANGUAGE."""
        tmpl_ar = self.resolver.render_template(
            "BUG_COMMENT",
            "en_titles_ar_comments",
            "abc1234",
            "سبب الخلل الوظيفي",
            "إصلاح منطق التحقق",
            ["شاشة تسجيل الدخول"],
            ["التحقق من صحة الإدخال"],
        )
        self.assertIn("Commit: abc1234", tmpl_ar)
        self.assertIn("سبب المشكلة:", tmpl_ar)
        self.assertIn("الحل المطبق:", tmpl_ar)
        self.assertIn("نطاق التأثير (Impact Area):", tmpl_ar)

        tmpl_en = self.resolver.render_template(
            "BUG_COMMENT",
            "all_en",
            "abc1234",
            "Functional defect explanation",
            "Validation fix",
            ["Login screen"],
            ["Input validation step"],
        )
        self.assertIn("Commit: abc1234", tmpl_en)
        self.assertIn("Root Cause:", tmpl_en)
        self.assertIn("Solution:", tmpl_en)
        self.assertIn("Impact Area (Blast Radius):", tmpl_en)


if __name__ == "__main__":
    unittest.main(verbosity=2)
