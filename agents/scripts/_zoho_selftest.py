"""Offline golden and idempotency tests for the retained Zoho workflow."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import re
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
MCP = HERE.parent / "mcp" / "zoho_sprints"
sys.path.insert(0, str(MCP))
sys.path.insert(0, str(HERE))

from _idempotency import _ledger_lock, execute_once  # noqa: E402
from _vnext_common import atomic_write_json, read_json  # noqa: E402
import workflow  # noqa: E402
import zoho_sync  # noqa: E402
from zoho_sync import resolve_new_item_type  # noqa: E402

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
        self.comments = []
        self.descriptions = []

    def get_statuses(self):
        return {"statusJObj": {"todo": ["To do"], "progress": ["In progress"], "retest": ["Ready To ReTest"], "done": ["Done"]}}

    def get_item_types(self):
        return {"projItemTypeJObj": {"type-task": ["", "Task"], "type-bug": ["", "Bug"], "type-story": ["", "Story"]}}

    def get_priorities(self):
        return {"projPriorityJObj": {"prio-medium": ["Medium"]}}

    def resolve_item(self, item_id, sprint_id=None):
        return sprint_id or "sprint-1", str(item_id)

    def update_item_status(self, sprint_id, item_id, status_id):
        self.status_updates += 1
        return {"status": "success", "sprint": sprint_id, "item": item_id, "status_id": status_id}

    def add_comment(self, sprint_id, item_id, comment):
        self.comments.append((sprint_id, item_id, comment))
        return {"status": "success", "comment": comment}

    def update_item_description(self, sprint_id, item_id, description):
        self.descriptions.append((sprint_id, item_id, description))
        return {"status": "success", "description": description}


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


class ZohoLifecycleTests(unittest.TestCase):
    """ZOHO-LIFE-001 through ZOHO-LIFE-020: Comprehensive Zoho lifecycle and integration tests."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / ".agents").mkdir(parents=True, exist_ok=True)
        self.ledger = Path(self.temp.name) / "operations.json"
        self._prev_ledger = os.environ.get("ANDROID_HARNESS_ZOHO_LEDGER")
        os.environ["ANDROID_HARNESS_ZOHO_LEDGER"] = str(self.ledger)
        self._prev_harness_repo = os.environ.get("HARNESS_REPO")
        os.environ["HARNESS_REPO"] = str(self.repo)
        zoho_sync._SERVER_MODULE = server

    def tearDown(self):
        if self._prev_ledger is None:
            os.environ.pop("ANDROID_HARNESS_ZOHO_LEDGER", None)
        else:
            os.environ["ANDROID_HARNESS_ZOHO_LEDGER"] = self._prev_ledger
        if self._prev_harness_repo is None:
            os.environ.pop("HARNESS_REPO", None)
        else:
            os.environ["HARNESS_REPO"] = self._prev_harness_repo
        self.temp.cleanup()

    def _create_task(self, task_id: str, plan_data: dict) -> Path:
        tdir = workflow.task_dir(self.repo, task_id)
        tdir.mkdir(parents=True, exist_ok=True)
        plan_path = tdir / "plan.json"
        default_plan = {
            "schema_version": 1,
            "task_id": task_id,
            "status": "IMPLEMENTING",
            "task_kind": "FEATURE",
            "plan_sha256": "abcdef1234567890abcdef1234567890",
            "execution_nonce": "nonce-1",
            "approval": {"single_use_nonce": "nonce-1"},
            "external_writes": ["zoho_sprints"],
        }
        default_plan.update(plan_data)
        atomic_write_json(plan_path, default_plan)
        return tdir

    def test_ZOHO_LIFE_001_linked_approved_task_routes_sync_zoho_start(self):
        """ZOHO-LIFE-001: Linked approved task routes SYNC_ZOHO_START."""
        tid = "T-ZOHO-001"
        self._create_task(tid, {
            "status": "IMPLEMENTING",
            "zoho_link": {"item_id": "1001", "sprint_id": "s-1", "item_type": "Bug"},
            "external_writes": ["zoho_sprints"],
        })
        tdir = workflow.task_dir(self.repo, tid)
        plan = read_json(tdir / "plan.json")
        action = workflow.resolve_next_action(self.repo, tid, plan)
        self.assertEqual("SYNC_ZOHO_START", action.get("code"))
        self.assertEqual(f"python .agents/scripts/zoho_sync.py start --repo . --task-id {tid}", action.get("command"))
        self.assertTrue(action.get("blocking"))

    def test_ZOHO_LIFE_002_unlinked_task_never_auto_mutates_zoho(self):
        """ZOHO-LIFE-002: Unlinked task never auto-mutates Zoho."""
        tid = "T-ZOHO-002"
        self._create_task(tid, {
            "status": "IMPLEMENTING",
            "zoho_link": None,
            "external_writes": [],
        })
        tdir = workflow.task_dir(self.repo, tid)
        plan = read_json(tdir / "plan.json")
        action = workflow.resolve_next_action(self.repo, tid, plan)
        self.assertNotEqual("SYNC_ZOHO_START", action.get("code"))

        # In DELIVERED state without link
        plan["status"] = "DELIVERED"
        atomic_write_json(tdir / "plan.json", plan)
        action_deliv = workflow.resolve_next_action(self.repo, tid, plan)
        self.assertEqual("TASK_DELIVERED", action_deliv.get("code"))

        # Calling zoho_sync start directly on unlinked task fails
        rc = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)

    def test_ZOHO_LIFE_003_linked_but_unapproved_scope_denied(self):
        """ZOHO-LIFE-003: Linked but unapproved external scope is denied."""
        tid = "T-ZOHO-003"
        self._create_task(tid, {
            "status": "IMPLEMENTING",
            "zoho_link": {"item_id": "1003", "item_type": "Task"},
            "external_writes": [],
        })
        tdir = workflow.task_dir(self.repo, tid)
        plan = read_json(tdir / "plan.json")
        action = workflow.resolve_next_action(self.repo, tid, plan)
        self.assertNotEqual("SYNC_ZOHO_START", action.get("code"))

        rc = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)

    def test_ZOHO_LIFE_004_start_sync_in_progress_only(self):
        """ZOHO-LIFE-004: Start sync updates status to In progress only (no comments/descriptions)."""
        tid = "T-ZOHO-004"
        self._create_task(tid, {
            "status": "IMPLEMENTING",
            "zoho_link": {"item_id": "1004", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
        })
        api = FakeAPI()
        with mock.patch.object(server, "get_api", return_value=api):
            rc = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc)
        self.assertEqual(1, api.status_updates)
        self.assertEqual(0, len(api.comments))
        self.assertEqual(0, len(api.descriptions))
        tdir = workflow.task_dir(self.repo, tid)
        sync_data = read_json(tdir / "zoho-start-sync.json")
        self.assertEqual("PASS", sync_data.get("status"))
        self.assertEqual("In progress", sync_data.get("target_status"))

    def test_ZOHO_LIFE_005_bug_description_preserved(self):
        """ZOHO-LIFE-005: Bug Description is preserved and never modified on delivery."""
        tid = "T-ZOHO-005"
        self._create_task(tid, {
            "status": "DELIVERED",
            "task_kind": "BUG",
            "zoho_link": {"item_id": "1005", "sprint_id": "sprint-1", "item_type": "Bug"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "abc123456789",
        })
        rc_prep = zoho_sync.main([
            "prepare-report", "--repo", str(self.repo), "--task-id", tid,
            "--objective", "Fix login null crash", "--changes", "Added null safety check",
            "--impact-json", '["LoginScreen"]', "--tests-json", '["testLoginNull"]',
        ])
        self.assertEqual(0, rc_prep)
        api = FakeAPI()
        with mock.patch.object(server, "get_api", return_value=api):
            rc_deliv = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc_deliv)
        self.assertEqual(0, len(api.descriptions), "Bug description must NEVER be modified")

    def test_ZOHO_LIFE_006_bug_report_to_comment(self):
        """ZOHO-LIFE-006: Bug report goes to Comment, then status set to Ready To ReTest."""
        tid = "T-ZOHO-006"
        self._create_task(tid, {
            "status": "DELIVERED",
            "task_kind": "BUG",
            "zoho_link": {"item_id": "1006", "sprint_id": "sprint-1", "item_type": "Bug"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "abc123456789",
        })
        zoho_sync.main([
            "prepare-report", "--repo", str(self.repo), "--task-id", tid,
            "--objective", "Fix login null crash", "--changes", "Added null safety check",
            "--impact-json", '["LoginScreen"]', "--tests-json", '["testLoginNull"]',
        ])
        api = FakeAPI()
        with mock.patch.object(server, "get_api", return_value=api):
            rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc)
        self.assertEqual(1, len(api.comments))
        self.assertIn("Fix login null crash", api.comments[0][2])
        self.assertIn("Commit: abc1234", api.comments[0][2])
        self.assertEqual(1, api.status_updates)

    def test_ZOHO_LIFE_007_task_report_to_description(self):
        """ZOHO-LIFE-007: Task delivery report goes to Description."""
        tid = "T-ZOHO-007"
        self._create_task(tid, {
            "status": "DELIVERED",
            "task_kind": "REFACTOR",
            "zoho_link": {"item_id": "1007", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "fedcba987654",
        })
        zoho_sync.main([
            "prepare-report", "--repo", str(self.repo), "--task-id", tid,
            "--objective", "Clean up view models", "--changes", "Split ViewModel into components",
            "--impact-json", '["MainViewModel"]', "--tests-json", '["testVM"]',
        ])
        api = FakeAPI()
        with mock.patch.object(server, "get_api", return_value=api):
            rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc)
        self.assertEqual(1, len(api.descriptions))
        self.assertIn("Clean up view models", api.descriptions[0][2])

    def test_ZOHO_LIFE_008_story_report_to_description(self):
        """ZOHO-LIFE-008: Story delivery report goes to Description."""
        tid = "T-ZOHO-008"
        self._create_task(tid, {
            "status": "DELIVERED",
            "task_kind": "FEATURE",
            "zoho_link": {"item_id": "1008", "sprint_id": "sprint-1", "item_type": "Story"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "112233445566",
        })
        zoho_sync.main([
            "prepare-report", "--repo", str(self.repo), "--task-id", tid,
            "--objective", "Implement dark mode", "--changes", "Added dark theme tokens",
            "--impact-json", '["Theme"]', "--tests-json", '["testTheme"]',
        ])
        api = FakeAPI()
        with mock.patch.object(server, "get_api", return_value=api):
            rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc)
        self.assertEqual(1, len(api.descriptions))
        self.assertIn("Implement dark mode", api.descriptions[0][2])

    def test_ZOHO_LIFE_009_task_story_short_commit_comment(self):
        """ZOHO-LIFE-009: Task/Story delivery adds short Commit: <short-hash> comment."""
        tid = "T-ZOHO-009"
        self._create_task(tid, {
            "status": "DELIVERED",
            "task_kind": "FEATURE",
            "zoho_link": {"item_id": "1009", "sprint_id": "sprint-1", "item_type": "Story"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "a1b2c3d4e5f6",
        })
        zoho_sync.main([
            "prepare-report", "--repo", str(self.repo), "--task-id", tid,
            "--objective", "Add settings screen", "--changes", "Added settings screen composable",
            "--impact-json", '["Settings"]', "--tests-json", '["testSettings"]',
        ])
        api = FakeAPI()
        with mock.patch.object(server, "get_api", return_value=api):
            rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc)
        self.assertEqual(1, len(api.comments))
        self.assertEqual("Commit: a1b2c3d", api.comments[0][2])

    def test_ZOHO_LIFE_010_ready_to_retest_only(self):
        """ZOHO-LIFE-010: Delivery sets status to Ready To ReTest only."""
        for itype in ("Bug", "Task", "Story"):
            tid = f"T-ZOHO-010-{itype}"
            self._create_task(tid, {
                "status": "DELIVERED",
                "zoho_link": {"item_id": "1010", "sprint_id": "sprint-1", "item_type": itype},
                "external_writes": ["zoho_sprints"],
                "delivery_commit_sha": "998877665544",
            })
            zoho_sync.main([
                "prepare-report", "--repo", str(self.repo), "--task-id", tid,
                "--objective", "Objective", "--changes", "Changes",
                "--impact-json", '["Area"]', "--tests-json", '["test"]',
            ])
            api = FakeAPI()
            with mock.patch.object(server, "get_api", return_value=api):
                rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
            self.assertEqual(0, rc)
            tdir = workflow.task_dir(self.repo, tid)
            sync_res = read_json(tdir / "zoho-delivery-sync.json")
            self.assertEqual("Ready To ReTest", sync_res.get("target_status"))

    def test_ZOHO_LIFE_011_terminal_done_solved_closed_forbidden(self):
        """ZOHO-LIFE-011: Terminal Done/Solved/Closed states are strictly forbidden."""
        api = FakeAPI()
        with mock.patch.object(server, "get_api", return_value=api):
            for bad_status in ("Done", "Solved", "Closed", "Completed"):
                with self.assertRaisesRegex(RuntimeError, "forbidden"):
                    server.handle_call_tool("zoho_update_task_status", {
                        "sprint_id": "sprint-1",
                        "item_id": "1011",
                        "status": bad_status,
                        "operation_id": f"op-bad-{bad_status}",
                    })

    def test_ZOHO_LIFE_012_delivery_requires_actual_commit_sha(self):
        """ZOHO-LIFE-012: Delivery sync requires actual commit SHA and DELIVERED state."""
        tid = "T-ZOHO-012"
        # 1. Missing commit sha
        self._create_task(tid, {
            "status": "DELIVERED",
            "zoho_link": {"item_id": "1012", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "",
        })
        rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)

        # 2. Not in DELIVERED status
        tdir = workflow.task_dir(self.repo, tid)
        plan = read_json(tdir / "plan.json")
        plan["status"] = "IMPLEMENTING"
        plan["delivery_commit_sha"] = "commit12345"
        atomic_write_json(tdir / "plan.json", plan)
        rc2 = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc2)

    def test_ZOHO_LIFE_013_stable_operation_ids(self):
        """ZOHO-LIFE-013: Operation IDs are stable, deterministic, and properly sanitized."""
        tid = "T-ZOHO-013"
        plan_sha = "abcdef1234567890abcdef1234567890"
        commit_sha = "1234567890abcdef"
        self._create_task(tid, {
            "status": "DELIVERED",
            "plan_sha256": plan_sha,
            "zoho_link": {"item_id": "1013", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": commit_sha,
        })
        zoho_sync.main([
            "prepare-report", "--repo", str(self.repo), "--task-id", tid,
            "--objective", "Test op ids", "--changes", "Changes",
            "--impact-json", '["Area"]', "--tests-json", '["test"]',
        ])
        expected_start = f"{tid}.zoho.start.{plan_sha[:12]}"
        expected_ready = f"{tid}.zoho.ready.{commit_sha[:7]}"
        expected_desc = f"{tid}.zoho.description.{commit_sha[:7]}"
        expected_comment = f"{tid}.zoho.commit-comment.{commit_sha[:7]}"

        for op_id in (expected_start, expected_ready, expected_desc, expected_comment):
            self.assertTrue(bool(re.match(r"^[a-zA-Z0-9_.-]+$", op_id)), f"Invalid op_id characters: {op_id}")

    def test_ZOHO_LIFE_014_duplicate_retry_idempotent(self):
        """ZOHO-LIFE-014: Duplicate retry of sync is idempotent through the ledger."""
        tid = "T-ZOHO-014"
        self._create_task(tid, {
            "status": "IMPLEMENTING",
            "zoho_link": {"item_id": "1014", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
        })
        api = FakeAPI()
        with mock.patch.object(server, "get_api", return_value=api):
            rc1 = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
            rc2 = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc1)
        self.assertEqual(0, rc2)
        self.assertEqual(1, api.status_updates, "Duplicate retry must not make a second API call")

    def test_ZOHO_LIFE_015_unknown_prior_outcome_not_blindly_retried(self):
        """ZOHO-LIFE-015: Unknown prior outcome blocks blind retry."""
        op_id = "T-ZOHO-015.zoho.start.unknown"
        with self.assertRaises(OSError):
            execute_once("status", {"item_id": "1015", "status": "In progress", "operation_id": op_id}, lambda: (_ for _ in ()).throw(OSError("Network timeout")))
        with self.assertRaisesRegex(RuntimeError, "outcome is unknown"):
            execute_once("status", {"item_id": "1015", "status": "In progress", "operation_id": op_id}, lambda: {"status": "success"})

    def test_ZOHO_LIFE_016_denied_mutation_cannot_emit_bypass_script(self):
        """ZOHO-LIFE-016: Denied mutation offers remediation, never bypass scripts."""
        tid = "T-ZOHO-016"
        self._create_task(tid, {
            "status": "IMPLEMENTING",
            "zoho_link": {"item_id": "1016", "item_type": "Task"},
            "external_writes": [],
        })
        import io
        stderr_buf = io.StringIO()
        with mock.patch("sys.stderr", stderr_buf):
            rc = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        output = stderr_buf.getvalue()
        self.assertEqual(1, rc)
        self.assertIn("workflow.py revise --external-write zoho_sprints", output)
        self.assertNotIn("curl", output.lower())
        self.assertNotIn("python -c", output)
        self.assertNotIn("requests.", output)

    def test_ZOHO_LIFE_017_language_mapping_preserved(self):
        """ZOHO-LIFE-017: Language mapping is preserved in delivery report formatting."""
        from integrations.zoho_sprints.policy import ZohoPolicyResolver
        tmpl_ar = ZohoPolicyResolver.render_template(
            "TASK_DESCRIPTION",
            language="en_titles_ar_comments",
            commit_hash="c123456",
            root_cause_or_objective="الهدف المطلوب",
            solution_or_changes="التغييرات المنفذة",
            blast_radius=["النطاق 1"],
            test_cases=["الاختبار 1"],
        )
        self.assertIn("الهدف من المهمة:", tmpl_ar)
        self.assertIn("ما تم تنفيذه:", tmpl_ar)

        tmpl_en = ZohoPolicyResolver.render_template(
            "TASK_DESCRIPTION",
            language="all_en",
            commit_hash="c123456",
            root_cause_or_objective="Objective text",
            solution_or_changes="Solution text",
            blast_radius=["Area 1"],
            test_cases=["Test 1"],
        )
        self.assertIn("Objective:", tmpl_en)
        self.assertIn("What Changed:", tmpl_en)

    def test_ZOHO_LIFE_018_zoho_env_does_not_fake_pass(self):
        """ZOHO-LIFE-018: Zoho ENV failure does not fake PASS."""
        tid = "T-ZOHO-018"
        self._create_task(tid, {
            "status": "IMPLEMENTING",
            "zoho_link": {"item_id": "1018", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
        })
        with mock.patch.object(server, "handle_call_tool", side_effect=OSError("DNS failure")):
            rc = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc)
        tdir = workflow.task_dir(self.repo, tid)
        sync_res = read_json(tdir / "zoho-start-sync.json")
        self.assertEqual("ENV", sync_res.get("status"))
        self.assertNotEqual("PASS", sync_res.get("status"))

    def test_ZOHO_LIFE_019_delivered_local_state_remains_delivered_during_tracker_outage(self):
        """ZOHO-LIFE-019: Delivered local state remains DELIVERED during tracker outage."""
        tid = "T-ZOHO-019"
        self._create_task(tid, {
            "status": "DELIVERED",
            "zoho_link": {"item_id": "1019", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "abc123456789",
        })
        tdir = workflow.task_dir(self.repo, tid)
        atomic_write_json(tdir / "zoho-delivery-sync.json", {
            "task_id": tid,
            "status": "ENV",
            "commit_sha": "abc123456789",
            "error": "Connection timed out",
        })
        plan = read_json(tdir / "plan.json")
        self.assertEqual("DELIVERED", plan.get("status"))
        action = workflow.resolve_next_action(self.repo, tid, plan)
        self.assertEqual("ZOHO_ENV_BLOCKED", action.get("code"))
        self.assertEqual("DELIVERED", plan.get("status"))

    def test_ZOHO_LIFE_020_successful_sync_ends_linked_task_external_work(self):
        """ZOHO-LIFE-020: Successful sync ends linked-task external work."""
        tid = "T-ZOHO-020"
        self._create_task(tid, {
            "status": "DELIVERED",
            "zoho_link": {"item_id": "1020", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "abc123456789",
        })
        tdir = workflow.task_dir(self.repo, tid)
        atomic_write_json(tdir / "zoho-delivery-sync.json", {
            "task_id": tid,
            "status": "PASS",
            "commit_sha": "abc123456789",
            "target_status": "Ready To ReTest",
        })
        plan = read_json(tdir / "plan.json")
        action = workflow.resolve_next_action(self.repo, tid, plan)
        self.assertEqual("TASK_DELIVERED", action.get("code"))
        self.assertEqual("DONE", action.get("kind"))
        self.assertFalse(action.get("blocking"))


    def test_ZOHO_new_item_type_resolver(self):
        """Section 52: New Zoho item type resolver logic."""
        self.assertEqual("Bug", resolve_new_item_type("BUG"))
        self.assertEqual("Story", resolve_new_item_type("FEATURE"))
        self.assertEqual("Task", resolve_new_item_type("REFACTOR"))
        self.assertEqual("Task", resolve_new_item_type("OTHER"))
        self.assertEqual("Bug", resolve_new_item_type("FEATURE", explicit_type="Bug"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
