"""Offline golden, policy, idempotency, and universal external PM MCP selftests."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _idempotency import _ledger_lock, execute_once  # noqa: E402
from _vnext_common import atomic_write_json, canonical_sha256, read_json  # noqa: E402
from plan_authority import plan_payload, save_plan  # noqa: E402
import workflow  # noqa: E402
import zoho_sync  # noqa: E402
from zoho_sync import resolve_new_item_type  # noqa: E402


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


class MockExternalPmServer:
    """In-memory mock external PM MCP adapter used for offline deterministic selftests."""

    TOOLS = [
        {"name": "zoho_list_sprints", "inputSchema": {"type": "object", "required": []}},
        {"name": "zoho_list_tasks", "inputSchema": {"type": "object", "required": []}},
        {"name": "zoho_get_task_details", "inputSchema": {"type": "object", "required": ["item_id"]}},
        {"name": "zoho_create_task", "inputSchema": {"type": "object", "required": ["name", "operation_id"]}},
        {"name": "zoho_update_task_status", "inputSchema": {"type": "object", "required": ["item_id", "status", "operation_id"]}},
        {"name": "zoho_add_comment", "inputSchema": {"type": "object", "required": ["item_id", "comment", "operation_id"]}},
        {"name": "zoho_update_task_description", "inputSchema": {"type": "object", "required": ["item_id", "description", "operation_id"]}},
    ]

    def get_api(self):
        return FakeAPI()

    def handle_call_tool(self, name: str, arguments: dict):
        api = self.get_api()
        if name == "zoho_update_task_status":
            status = str(arguments.get("status") or "").strip()
            if status.lower() in ("done", "solved", "closed", "completed"):
                raise RuntimeError(f"Setting terminal status '{status}' is forbidden")
            res = execute_once(
                name,
                arguments,
                lambda: api.update_item_status(arguments.get("sprint_id") or "sprint-1", str(arguments.get("item_id")), status),
            )
            return {"content": [{"type": "text", "text": json.dumps(res)}]}
        if name == "zoho_add_comment":
            res = execute_once(
                name,
                arguments,
                lambda: api.add_comment(arguments.get("sprint_id") or "sprint-1", str(arguments.get("item_id")), str(arguments.get("comment") or "")),
            )
            return {"content": [{"type": "text", "text": json.dumps(res)}]}
        if name == "zoho_update_task_description":
            res = execute_once(
                name,
                arguments,
                lambda: api.update_item_description(arguments.get("sprint_id") or "sprint-1", str(arguments.get("item_id")), str(arguments.get("description") or "")),
            )
            return {"content": [{"type": "text", "text": json.dumps(res)}]}
        raise RuntimeError(f"Unsupported mock tool: {name}")


server = MockExternalPmServer()


class PmIdempotencyAndAdapterTests(unittest.TestCase):
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

    def test_bundled_zoho_mcp_is_removed_from_kit(self):
        kit_root = HERE.parent.parent
        self.assertFalse((kit_root / "agents" / "mcp" / "zoho_sprints").exists(), "Bundled zoho_sprints MCP directory must be removed")
        self.assertFalse((HERE / "install_zoho_mcp.py").exists(), "install_zoho_mcp.py must be removed")

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
        with self.assertRaisesRegex(RuntimeError, "operation_id is required"):
            execute_once("status", {"item_id": "1", "status": "In progress"}, lambda: calls.append(1) or {"status": "ok"})
        self.assertEqual(0, len(calls))

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


class PmPolicyTests(unittest.TestCase):
    """Deterministic PM integration policy tests."""

    def setUp(self) -> None:
        sys.path.insert(0, str(HERE))
        from integrations.zoho_sprints.policy import ZohoPolicyResolver
        from integrations.zoho_sprints.integration import ZohoSprintsIntegration
        from integrations.base import validate_external_write
        self.resolver = ZohoPolicyResolver
        self.integ = ZohoSprintsIntegration()
        self.validate_write = validate_external_write

    def test_ZOHO_001_and_002_bug_delivery_report_in_comment_description_preserved(self) -> None:
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
        self.assertIn("harness.py zoho authorize", reason)
        self.assertIn("Do not revise the task plan", reason)

    def test_ZOHO_009_language_template_obeys_configured_language(self) -> None:
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


class PmLifecycleTests(unittest.TestCase):
    """Comprehensive PM lifecycle, Universal PM MCP discovery, incident reporter, and self-healing tests."""

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
            "execution_nonce": "nonce-1",
            "approval": {"single_use_nonce": "nonce-1"},
            "external_writes": ["zoho_sprints"],
        }
        default_plan.update(plan_data)
        if "plan_sha256" not in plan_data:
            comp_hash = canonical_sha256(plan_payload(default_plan))
            default_plan["plan_sha256"] = comp_hash
            if "approval" in default_plan and isinstance(default_plan["approval"], dict):
                default_plan["approval"]["plan_sha256"] = comp_hash
        atomic_write_json(plan_path, default_plan)
        return tdir

    def test_ZOHO_LIFE_001_linked_approved_task_routes_sync_zoho_start(self):
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

        plan["status"] = "DELIVERED"
        atomic_write_json(tdir / "plan.json", plan)
        action_deliv = workflow.resolve_next_action(self.repo, tid, plan)
        self.assertEqual("TASK_DELIVERED", action_deliv.get("code"))

        rc = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)

    def test_ZOHO_LIFE_003_linked_but_unapproved_scope_denied(self):
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

    def test_ZOHO_LIFE_005b_report_takes_plain_items_and_missing_report_names_the_command(self):
        import contextlib
        import io
        tid = "T-ZOHO-005B"
        self._create_task(tid, {
            "status": "DELIVERED",
            "task_kind": "BUG",
            "zoho_link": {"item_id": "1055", "sprint_id": "sprint-1", "item_type": "Bug"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "abc123456789",
        })
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)
        self.assertIn(f"zoho prepare-report --task-id {tid} --objective", err.getvalue())
        self.assertIn('--impact "<impact area>" --tests "<test case>"', err.getvalue())

        rc = zoho_sync.main([
            "prepare-report", "--repo", str(self.repo), "--task-id", tid,
            "--objective", "Fix login null crash", "--changes", "Added null safety check",
            "--impact", "LoginScreen", "--impact", "Session restore", "--tests", "testLoginNull",
        ])
        self.assertEqual(0, rc)
        report = read_json(workflow.task_dir(self.repo, tid) / "zoho-delivery-report.json")
        self.assertIn("Session restore", json.dumps(report, ensure_ascii=False))

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = zoho_sync.main(["prepare-report", "--repo", str(self.repo), "--task-id", tid,
                                 "--objective", "x", "--changes", "y", "--impact", "A"])
        self.assertEqual(1, rc)
        self.assertIn('give 1 to 30 --tests items, e.g. --tests "<first>"', err.getvalue())

    def test_ZOHO_LIFE_006_bug_report_to_comment(self):
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
        tid = "T-ZOHO-012"
        self._create_task(tid, {
            "status": "DELIVERED",
            "zoho_link": {"item_id": "1012", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "",
        })
        rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)

        tdir = workflow.task_dir(self.repo, tid)
        plan = read_json(tdir / "plan.json")
        plan["status"] = "IMPLEMENTING"
        plan["delivery_commit_sha"] = "commit12345"
        atomic_write_json(tdir / "plan.json", plan)
        rc2 = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc2)

    def test_ZOHO_LIFE_013_stable_operation_ids(self):
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
        op_id = "T-ZOHO-015.zoho.start.unknown"
        with self.assertRaises(OSError):
            execute_once("status", {"item_id": "1015", "status": "In progress", "operation_id": op_id}, lambda: (_ for _ in ()).throw(OSError("Network timeout")))
        with self.assertRaisesRegex(RuntimeError, "outcome is unknown"):
            execute_once("status", {"item_id": "1015", "status": "In progress", "operation_id": op_id}, lambda: {"status": "success"})

    def test_ZOHO_LIFE_016_denied_mutation_cannot_emit_bypass_script(self):
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
        self.assertIn("harness.py zoho authorize", output)
        self.assertNotIn("curl", output.lower())
        self.assertNotIn("python -c", output)
        self.assertNotIn("requests.", output)

    def test_ZOHO_LIFE_016b_update_zoho_grants_writes_without_a_plan_revision(self):
        import io
        import zoho_grant
        from integrations.base import validate_external_write
        from integrations.zoho_sprints.integration import ZohoSprintsIntegration
        integ = ZohoSprintsIntegration()
        tid = "T-ZOHO-016B"
        self._create_task(tid, {
            "status": "READY_FOR_DELIVERY",
            "execution_nonce": "n1",
            "approval": {"single_use_nonce": "n1"},
            "zoho_link": {"item_id": "873", "item_type": "Task"},
            "external_writes": [],
        })
        plan = {"status": "READY_FOR_DELIVERY", "execution_nonce": "n1", "approval": {"single_use_nonce": "n1"}, "external_writes": []}
        write = {"status": "In progress", "operation_id": "op-873"}
        self.assertFalse(validate_external_write(integ, "zoho_update_task_status", write, plan)[0])

        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            self.assertEqual(1, zoho_sync.main(["authorize", "--repo", str(self.repo), "--proof-reference", "ok go"]))
        self.assertIn("update zoho", err.getvalue())
        self.assertIsNone(zoho_grant.active_grant(self.repo))
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(0, zoho_sync.main(["authorize", "--repo", str(self.repo), "--proof-reference", "Update Zoho"]))
        self.assertIn("ZOHO_WRITE_GRANTED", out.getvalue())
        self.assertTrue(zoho_grant.is_update_zoho("حدث زوهو بتعديلات"))
        self.assertTrue(zoho_grant.is_update_zoho("تحديث زوهو"))
        self.assertFalse(zoho_grant.is_update_zoho("شوف زوهو"), "looking at Zoho is not an order to write")
        self.assertFalse(zoho_grant.is_update_zoho("حدث الكود"), "updating the code is not a Zoho write")
        grant = zoho_grant.active_grant(self.repo)
        self.assertIsNotNone(grant)
        self.assertEqual((True, ""), validate_external_write(integ, "zoho_update_task_status", write, plan, grant=grant))
        self.assertFalse(validate_external_write(integ, "zoho_update_task_status", {"status": "Done", "operation_id": "op"}, plan, grant=grant)[0])
        self.assertFalse(validate_external_write(integ, "zoho_update_task_status", {"status": "In progress"}, plan, grant=grant)[0])
        from mutation_guard import command_allowed
        self.assertTrue(command_allowed(self.repo, 'python .agents/harness.py zoho authorize --proof-reference "update zoho"')[0])
        path = zoho_grant._state(self.repo) / zoho_grant.GRANT_FILE
        data = json.loads(path.read_text(encoding="utf-8"))
        data["expires_epoch"] = data["granted_epoch"] - 1
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNone(zoho_grant.active_grant(self.repo))

    def test_ZOHO_LIFE_017_language_mapping_preserved(self):
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
        tid = "T-ZOHO-018"
        self._create_task(tid, {
            "status": "IMPLEMENTING",
            "zoho_link": {"item_id": "1018", "sprint_id": "sprint-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
        })
        import contextlib
        import io
        out = io.StringIO()
        with mock.patch.object(server, "handle_call_tool", side_effect=OSError("DNS failure")), contextlib.redirect_stdout(out):
            rc = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc)
        tdir = workflow.task_dir(self.repo, tid)
        sync_res = read_json(tdir / "zoho-start-sync.json")
        self.assertEqual("ENV", sync_res.get("status"))
        self.assertNotEqual("PASS", sync_res.get("status"))
        printed = json.loads(out.getvalue())
        self.assertIn("Tell the developer now that Zoho item 1018 was not moved to In progress: DNS failure", printed["next"])
        self.assertIn("Do not call Zoho MCP tools directly", printed["next"])

    def test_ZOHO_LIFE_019_delivered_local_state_remains_delivered_during_tracker_outage(self):
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

    def test_ZOHO_start_outside_implementing_denied(self):
        tid = "T-ZOHO-NON-IMPL"
        self._create_task(tid, {
            "status": "VERIFYING",
            "zoho_link": {"item_id": "9991", "sprint_id": "s-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
        })
        import io
        stderr_buf = io.StringIO()
        with mock.patch("sys.stderr", stderr_buf):
            rc = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)
        self.assertIn("TASK_NOT_IMPLEMENTING", stderr_buf.getvalue())

    def test_ZOHO_corrupt_execution_nonce_denied(self):
        tid = "T-ZOHO-BAD-NONCE"
        self._create_task(tid, {
            "status": "IMPLEMENTING",
            "zoho_link": {"item_id": "9992", "sprint_id": "s-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
            "execution_nonce": "corrupted-nonce",
            "approval": {"single_use_nonce": "original-nonce"},
        })
        import io
        stderr_buf = io.StringIO()
        with mock.patch("sys.stderr", stderr_buf):
            rc = zoho_sync.main(["start", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)
        self.assertIn("EXECUTION_NONCE_MISMATCH", stderr_buf.getvalue())

    def test_ZOHO_stale_report_plan_denied(self):
        tid = "T-ZOHO-STALE-REPORT"
        tdir = self._create_task(tid, {
            "status": "DELIVERED",
            "zoho_link": {"item_id": "9993", "sprint_id": "s-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "abcdef1234567890",
        })
        rep = {
            "schema_version": 1,
            "task_id": tid,
            "plan_sha256": "stale-plan-hash-12345",
            "objective_or_root_cause": "obj",
            "solution_or_changes": "changes",
            "impact_area": ["app"],
            "test_cases": ["test1"],
        }
        rep["report_sha256"] = canonical_sha256(rep)
        atomic_write_json(tdir / "zoho-delivery-report.json", rep)

        import io
        stderr_buf = io.StringIO()
        with mock.patch("sys.stderr", stderr_buf):
            rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)
        self.assertIn("DELIVERY_REPORT_PLAN_MISMATCH", stderr_buf.getvalue())

    def test_ZOHO_tampered_report_hash_denied(self):
        tid = "T-ZOHO-TAMPERED-REPORT"
        tdir = self._create_task(tid, {
            "status": "DELIVERED",
            "zoho_link": {"item_id": "9994", "sprint_id": "s-1", "item_type": "Task"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": "abcdef1234567890",
        })
        plan = read_json(tdir / "plan.json")
        rep = {
            "schema_version": 1,
            "task_id": tid,
            "plan_sha256": plan["plan_sha256"],
            "objective_or_root_cause": "obj",
            "solution_or_changes": "changes",
            "impact_area": ["app"],
            "test_cases": ["test1"],
            "report_sha256": "fake-tampered-hash",
        }
        atomic_write_json(tdir / "zoho-delivery-report.json", rep)

        import io
        stderr_buf = io.StringIO()
        with mock.patch("sys.stderr", stderr_buf):
            rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(1, rc)
        self.assertIn("DELIVERY_REPORT_TAMPERED", stderr_buf.getvalue())

    def test_ZOHO_delivery_actions_match_policy_resolver_and_sha12_op_ids(self):
        tid = "T-ZOHO-POLICY-MATCH"
        full_commit = "abcdef1234567890fedcba"
        tdir = self._create_task(tid, {
            "status": "DELIVERED",
            "zoho_link": {"item_id": "9995", "sprint_id": "s-1", "item_type": "Bug"},
            "external_writes": ["zoho_sprints"],
            "delivery_commit_sha": full_commit,
        })
        plan = read_json(tdir / "plan.json")

        rep = {
            "schema_version": 1,
            "task_id": tid,
            "plan_sha256": plan["plan_sha256"],
            "objective_or_root_cause": "Fix crash on login",
            "solution_or_changes": "Handle null pointer in auth token",
            "impact_area": ["app:login"],
            "test_cases": ["LoginTest"],
        }
        rep["report_sha256"] = canonical_sha256(rep)
        atomic_write_json(tdir / "zoho-delivery-report.json", rep)

        called_tools = []
        def fake_call_tool(name, args):
            called_tools.append((name, args))
            return {"status": "success"}

        with mock.patch.object(server, "handle_call_tool", side_effect=fake_call_tool):
            rc = zoho_sync.main(["delivery", "--repo", str(self.repo), "--task-id", tid])
        self.assertEqual(0, rc)

        tool_names = [t[0] for t in called_tools]
        self.assertIn("zoho_add_comment", tool_names)
        self.assertIn("zoho_update_task_status", tool_names)
        self.assertNotIn("zoho_update_task_description", tool_names)

        expected_sha12 = full_commit[:12]
        for name, args in called_tools:
            op_id = args.get("operation_id", "")
            self.assertTrue(op_id.endswith(expected_sha12), f"Operation ID {op_id} must end with sha12 {expected_sha12}")

        comment_call = next(args for name, args in called_tools if name == "zoho_add_comment")
        comment_text = comment_call.get("comment", "")
        self.assertIn(full_commit[:7], comment_text)

    def test_ZOHO_new_item_type_resolver(self):
        self.assertEqual("Bug", resolve_new_item_type("BUG"))
        self.assertEqual("Story", resolve_new_item_type("FEATURE"))
        self.assertEqual("Task", resolve_new_item_type("REFACTOR"))
        self.assertEqual("Task", resolve_new_item_type("OTHER"))
        self.assertEqual("Bug", resolve_new_item_type("FEATURE", explicit_type="Bug"))

    def test_ZOHO_project_notes_authorize_and_mutation_validation(self):
        notes_p = self.repo / ".agents" / "project-context" / "project-notes.md"
        notes_p.parent.mkdir(parents=True, exist_ok=True)
        notes_p.write_text(
            "# Project Notes\n\n"
            "## 1. Zoho Sprints Task & Bug Description Standard (Mandatory)\n"
            "- **No Code or File Artifacts**: Do NOT include raw code blocks, Kotlin/Java snippets, XML, file paths, or class/function names.\n"
            "- **Dark/Light Mode Safe Styling**: Never hardcode dark text colors (such as `#2c3e50` or `#000000`).\n"
            "- **Required 5-Section Structure**:\n"
            "  1. `🎯 الهدف من التاسك` (Objective)\n"
            "  2. `🔍 المشكلة أو السياق الحالي` (Problem / Current Context)\n"
            "  3. `🛠️ الحل والتعديلات المنفذة` (Solution & Implemented Changes)\n"
            "  4. `📱 النتيجة المتوقعة وتجربة المستخدم` (Expected Result & UX Impact)\n"
            "  5. `✅ خطوات التحقق والاختبار (QA Checklist)`\n"
            "```html\n<div dir=\"rtl\"></div>\n```\n",
            encoding="utf-8",
        )
        import io
        stdout_buf = io.StringIO()
        with mock.patch("sys.stdout", stdout_buf):
            rc = zoho_sync.main(["authorize", "--repo", str(self.repo), "--proof", "حدث زوهو"])
        self.assertEqual(0, rc)
        self.assertIn("MANDATORY ZOHO RULES FROM .agents/project-context/project-notes.md:", stdout_buf.getvalue())
        self.assertIn("No Code or File Artifacts", stdout_buf.getvalue())

        from integrations.zoho_sprints.integration import ZohoSprintsIntegration
        from integrations.universal_pm import UniversalPmIntegration
        integ = ZohoSprintsIntegration()
        upm = UniversalPmIntegration()
        plan = {
            "status": "READY_FOR_DELIVERY",
            "repo_root": str(self.repo),
            "execution_nonce": "nonce-notes",
            "approval": {"single_use_nonce": "nonce-notes"},
            "external_writes": ["zoho_sprints", "zoho_projects"],
        }

        ok_plain, reason_plain = integ.validate_mutation(
            "zoho_create_task",
            {"name": "Task", "description": "تم فصل منطق البانرات بالكامل", "operation_id": "op-1"},
            plan,
        )
        self.assertFalse(ok_plain)
        self.assertIn("ZOHO_PROJECT_NOTES_VIOLATION", reason_plain)

        # UniversalPmIntegration also enforces project-notes.md 5-section Arabic HTML & No-Code-Leak rules!
        ok_upm_plain, reason_upm_plain = upm.validate_mutation(
            "call_mcp_tool",
            {
                "ServerName": "zoho-projects_mcp",
                "ToolName": "ZohoProjects_create_a_task",
                "Arguments": {"name": "Task", "description": "تم فصل منطق البانرات بالكامل"},
            },
            plan,
        )
        self.assertFalse(ok_upm_plain)
        self.assertIn("ZOHO_PROJECT_NOTES_VIOLATION", reason_upm_plain)

        bad_html = (
            '<div dir="rtl">'
            '🎯 الهدف من التاسك 🔍 المشكلة أو السياق الحالي 🛠️ الحل والتعديلات المنفذة '
            '📱 النتيجة المتوقعة وتجربة المستخدم ✅ خطوات التحقق والاختبار '
            'تم تعديل CampaignBannerItem و HomeScreen.kt'
            '</div>'
        )
        ok_leak, reason_leak = integ.validate_mutation(
            "zoho_create_task",
            {"name": "Task", "description": bad_html, "operation_id": "op-2"},
            plan,
        )
        self.assertFalse(ok_leak)
        self.assertIn("ZOHO_PROJECT_NOTES_VIOLATION", reason_leak)

        good_html = (
            '<div dir="rtl">'
            '<h3>🎯 الهدف من التاسك</h3><p>فصل منطق البانرات الترويجية</p>'
            '<h3>🔍 المشكلة أو السياق الحالي</h3><p>اعتماد البانر على حالة الاشتراك</p>'
            '<h3>🛠️ الحل والتعديلات المنفذة</h3><p>فصل منطق العرض والتوجيه للويب</p>'
            '<h3>📱 النتيجة المتوقعة وتجربة المستخدم</h3><p>عرض البانرات وتوجيه المستخدم بسلاسة</p>'
            '<h3>✅ خطوات التحقق والاختبار (QA Checklist)</h3><p>التحقق من ظهور البانر</p>'
            '</div>'
        )
        ok_good, reason_good = integ.validate_mutation(
            "zoho_create_task",
            {"name": "Task", "description": good_html, "operation_id": "op-3"},
            plan,
        )
        self.assertTrue(ok_good, reason_good)

    def test_universal_pm_discovery_and_guardrails(self):
        from pm_discovery import discover_installed_pm_mcps
        from integrations.universal_pm import UniversalPmIntegration
        from zoho_grant import active_pm_grant, is_explicit_close_order, is_update_pm, record_pm_grant

        self.assertTrue(is_update_pm("update pm"))
        self.assertTrue(is_update_pm("حدث التاسك على زوهو"))
        self.assertTrue(is_update_pm("update jira"))
        self.assertFalse(is_update_pm("please update all dependencies"), "Wildcard provider='all' must not match 'update all'")
        self.assertTrue(is_explicit_close_order("update pm and close task"))
        self.assertTrue(is_explicit_close_order("حدث التاسك واقفل التاسك"))
        self.assertFalse(is_explicit_close_order("حدث التاسك"))

        # Verify installation-chosen TRACKER_LANGUAGE in _product.py is respected across all PM providers
        from pm_discovery import resolve_configured_pm_language
        from integrations.zoho_sprints.policy import ZohoPolicyResolver
        prod_file = self.repo / ".agents" / "scripts" / "_product.py"
        prod_file.parent.mkdir(parents=True, exist_ok=True)
        prod_file.write_text('TRACKER_LANGUAGE = "all_en"\nZOHO_LANGUAGE = "all_en"\n', encoding="utf-8")
        self.assertEqual("all_en", resolve_configured_pm_language(self.repo))
        html_en = ZohoPolicyResolver.render_template(
            "TASK_DESCRIPTION", "all_en", "abc1234", "Improve performance", "Optimized caching", ["Home"], ["Verify cold start"], use_html_template=True
        )
        self.assertIn('<div dir="ltr"', html_en)
        self.assertIn("<h3>1. Root Cause &amp; Objective</h3>", html_en)
        prod_file.write_text('TRACKER_LANGUAGE = "en_titles_ar_comments"\nZOHO_LANGUAGE = "en_titles_ar_comments"\n', encoding="utf-8")
        self.assertEqual("en_titles_ar_comments", resolve_configured_pm_language(self.repo))

        mcp_root = self.repo / "fake_ag_mcp"
        zp_dir = mcp_root / "zoho-projects_mcp"
        zp_dir.mkdir(parents=True, exist_ok=True)
        (zp_dir / "ZohoProjects_get_tasks_by_project.json").write_text('{"name": "ZohoProjects_get_tasks_by_project"}', encoding="utf-8")
        (zp_dir / "ZohoProjects_update_issue.json").write_text('{"name": "ZohoProjects_update_issue"}', encoding="utf-8")
        jira_dir = mcp_root / "atlassian-mcp-server"
        jira_dir.mkdir(parents=True, exist_ok=True)
        (jira_dir / "getJiraIssue.json").write_text('{"name": "getJiraIssue"}', encoding="utf-8")
        (jira_dir / "editJiraIssue.json").write_text('{"name": "editJiraIssue"}', encoding="utf-8")

        discovered = discover_installed_pm_mcps(self.repo, extra_mcp_roots=[mcp_root])
        providers = {item["provider_id"]: item for item in discovered}
        self.assertIn("zoho_projects", providers)
        self.assertIn("jira", providers)
        self.assertIn("ZohoProjects_get_tasks_by_project", providers["zoho_projects"]["tools"]["read_tools"])
        self.assertIn("ZohoProjects_update_issue", providers["zoho_projects"]["tools"]["write_tools"])

        upm = UniversalPmIntegration()
        self.assertTrue(upm.owns_tool("ZohoProjects_get_tasks_by_project"))
        self.assertTrue(upm.owns_tool("ZohoProjects_update_issue"))
        self.assertTrue(upm.owns_tool("call_mcp_tool", {"ServerName": "zoho-projects_mcp", "ToolName": "ZohoProjects_update_a_task"}))
        self.assertTrue(upm.is_read_only("ZohoProjects_get_tasks_by_project"))
        self.assertTrue(upm.is_read_only("call_mcp_tool", {"ServerName": "atlassian-mcp-server", "ToolName": "getJiraIssue"}))
        self.assertFalse(upm.is_read_only("call_mcp_tool", {"ServerName": "zoho-projects_mcp", "ToolName": "ZohoProjects_update_issue"}))

        plan = {
            "status": "READY_FOR_DELIVERY",
            "repo_root": str(self.repo),
            "execution_nonce": "n-upm",
            "approval": {"single_use_nonce": "n-upm"},
            "external_writes": ["zoho_projects"],
        }

        ok_bug_desc, reason_bug_desc = upm.validate_mutation(
            "call_mcp_tool",
            {
                "ServerName": "zoho-projects_mcp",
                "ToolName": "ZohoProjects_update_issue",
                "Arguments": {"issue_id": "123", "description": "overwritten"},
            },
            plan,
        )
        self.assertFalse(ok_bug_desc)
        self.assertIn("Editing a Bug/Issue description is strictly prohibited", reason_bug_desc)

        record_pm_grant(self.repo, "conversation", "حدث التاسك")
        ok_closed, reason_closed = upm.validate_mutation(
            "call_mcp_tool",
            {
                "ServerName": "zoho-projects_mcp",
                "ToolName": "ZohoProjects_update_a_task",
                "Arguments": {"task_id": "123", "status": "Closed"},
            },
            plan,
        )
        self.assertFalse(ok_closed)
        self.assertIn("Terminal tracker states", reason_closed)

        import pre_tool_safety
        import io
        hook_out = io.StringIO()
        (self.repo / ".agents" / "state" / "zoho-write-grant.json").unlink(missing_ok=True)
        unapproved_plan = {
            "status": "READY_FOR_DELIVERY",
            "repo_root": str(self.repo),
            "execution_nonce": "n-upm",
            "approval": {"single_use_nonce": "n-upm"},
            "external_writes": [],
        }
        with mock.patch.object(pre_tool_safety, "REPO", self.repo), \
             mock.patch.object(pre_tool_safety, "active_plan", return_value=unapproved_plan), \
             mock.patch("sys.stdout", hook_out):
            pre_tool_safety._handle_mcp_tool(
                "call_mcp_tool",
                {
                    "ServerName": "zoho-projects_mcp",
                    "ToolName": "ZohoProjects_update_a_task",
                    "Arguments": {"task_id": "123", "name": "Updated Task"},
                },
            )
        hook_res = json.loads(hook_out.getvalue())
        self.assertEqual("deny", hook_res["decision"])
        self.assertIn("PM_PREVIEW_AND_APPROVAL_REQUIRED", hook_res["reason"])
        self.assertIn("present the exact preview of the tracker changes", hook_res["reason"])

        record_pm_grant(self.repo, "conversation", "حدث التاسك واقفل التاسك", allow_close=True)
        self.assertTrue(active_pm_grant(self.repo).get("allow_close"))
        ok_closed_explicit, reason_closed_explicit = upm.validate_mutation(
            "call_mcp_tool",
            {
                "ServerName": "zoho-projects_mcp",
                "ToolName": "ZohoProjects_update_a_task",
                "Arguments": {"task_id": "123", "status": "Closed"},
            },
            plan,
        )
        self.assertTrue(ok_closed_explicit, reason_closed_explicit)

    def test_incident_reporter_and_self_healing_snapshots(self):
        from incident_reporter import list_incidents, record_incident
        from self_heal import heal_task_state, load_stable_snapshot, save_stable_snapshot

        inc1 = record_incident(
            self.repo,
            code="HARNESS_CONTRADICTION",
            title="Test contradiction",
            command=f"python {self.repo}/harness.py task complete",
            error_message=f"Failed at {self.repo}/app/src/main/Login.kt",
            task_id="t-heal",
            task_status="VERIFYING",
            auto_submit=False,
        )
        self.assertEqual("RECORDED", inc1["status"])
        inc_dup = record_incident(
            self.repo,
            code="HARNESS_CONTRADICTION",
            title="Test contradiction",
            command=f"python {self.repo}/harness.py task complete",
            error_message=f"Failed at {self.repo}/app/src/main/Login.kt",
            task_id="t-heal",
            task_status="VERIFYING",
            auto_submit=False,
        )
        self.assertEqual("DUPLICATE", inc_dup["status"])
        incidents = list_incidents(self.repo)
        self.assertEqual(1, len(incidents))
        self.assertIn("<REPO_ROOT>", incidents[0]["command"])
        self.assertNotIn(str(self.repo).replace("\\", "/"), incidents[0]["command"])

        tid = "t-heal"
        tdir = self.repo / ".agents" / "state" / "tasks" / tid
        tdir.mkdir(parents=True, exist_ok=True)
        plan = {
            "task_id": tid,
            "status": "READY_FOR_DELIVERY",
            "requested_outcome": "Fix login",
            "expected_files": ["app/src/main/Login.kt"],
            "expected_surfaces": ["BUSINESS_LOGIC"],
            "approval": {"single_use_nonce": "nonce-heal", "approval_source": "conversation"},
            "execution_nonce": "nonce-heal",
            "review_rounds": 1,
            "review_calls_used": 3,
            "ready_run_id": "run-old",
            "ready_delivery_snapshot_sha256": "deadbeef",
        }
        plan["plan_sha256"] = canonical_sha256(plan_payload(plan))
        plan["approval"]["plan_sha256"] = plan["plan_sha256"]
        save_plan(tdir / "plan.json", plan)
        save_stable_snapshot(self.repo, tid, "ready_for_delivery", plan=plan)
        snap = load_stable_snapshot(self.repo, tid, "ready_for_delivery")
        self.assertIsNotNone(snap)

        heal_res = heal_task_state(self.repo, task_id=tid, reason="pre_commit_edit", prepare_fresh_run=False)
        self.assertEqual("HEALED", heal_res["status"])
        self.assertEqual("IMPLEMENTING", heal_res["to_status"])
        self.assertEqual(3, heal_res["preserved_review_calls_used"])
        healed_plan = read_json(tdir / "plan.json")
        self.assertEqual("IMPLEMENTING", healed_plan["status"])
        self.assertEqual(3, healed_plan["review_calls_used"])


class ReviewRegressionTests(unittest.TestCase):
    def test_incident_export_excludes_free_text_in_all_submission_paths(self):
        import incident_reporter as ir
        from urllib.parse import unquote_plus
        from types import SimpleNamespace
        secret = "customer@example.test +201012345678 PrivateCustomerName"
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            incident = ir.record_incident(repo, code=secret, command=secret,
                message=secret, extra={secret: secret}, heal_action=secret,
                task_state=secret, traceback_text="ValueError: " + secret, auto_submit=False)
            incident.update(host=secret, os=secret, incident_id=secret, created_at=secret,
                            issue_url="https://example.test/?private=" + secret)
            self.assertNotIn("customer@example.test", ir.format_issue_markdown(incident))
            self.assertNotIn("PrivateCustomerName", unquote_plus(ir.build_github_issue_url(incident)))
            preview = ir.submit_incident_to_github(repo, incident, dry_run=True)
            self.assertNotIn("PrivateCustomerName", json.dumps(preview))
            with mock.patch.object(ir.shutil, "which", return_value="gh"), mock.patch.object(
                ir.subprocess, "run", side_effect=[SimpleNamespace(returncode=0, stdout="[]"),
                SimpleNamespace(returncode=0, stdout="https://github.com/example/issues/1")]) as run:
                ir.submit_incident_to_github(repo, incident)
            self.assertNotIn("PrivateCustomerName", str(run.call_args_list))

    def test_snapshot_rejects_wrong_identity_schema_and_plan_hash(self):
        from self_heal import heal_task_state, load_stable_snapshot, save_stable_snapshot
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); tdir = repo / ".agents/state/tasks/task-a"
            plan = {"task_id": "task-a", "status": "CANCELLED", "requested_outcome": "test"}
            plan["plan_sha256"] = canonical_sha256(plan_payload(plan))
            save_plan(tdir / "plan.json", plan)
            self.assertIsNotNone(save_stable_snapshot(repo, "task-a", "cancelled"))
            good = load_stable_snapshot(repo, "task-a")
            self.assertIsNotNone(good)
            for mutate in (lambda x: x.update(task_id="task-b"),
                           lambda x: x["plan"].update(task_id="task-b"),
                           lambda x: x.update(schema_version=99),
                           lambda x: x["plan"].update(requested_outcome="different")):
                bad = json.loads(json.dumps(good)); mutate(bad)
                atomic_write_json(tdir / "snapshots/stable-latest.json", bad)
                (tdir / "plan.json").write_text("{broken", encoding="utf-8")
                self.assertIsNone(load_stable_snapshot(repo, "task-a"))
                self.assertEqual("UNRECOVERABLE", heal_task_state(repo, "task-a")["status"])
                self.assertEqual("{broken", (tdir / "plan.json").read_text())
            self.assertIsNone(load_stable_snapshot(repo, "task-a", "../../../escape"))
            atomic_write_json(tdir / "snapshots/stable-latest.json", good)
            with mock.patch("incident_reporter.record_incident"):
                self.assertEqual("HEALED", heal_task_state(repo, "task-a")["status"])
            self.assertEqual("task-a", read_json(tdir / "plan.json")["task_id"])

    def test_snapshot_requires_bound_approval_and_run_identity(self):
        from self_heal import save_stable_snapshot, load_stable_snapshot
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = {"task_id": "task", "status": "IMPLEMENTING", "requested_outcome": "test",
                    "execution_nonce": "nonce", "approval": {"single_use_nonce": "nonce"}}
            plan["plan_sha256"] = canonical_sha256(plan_payload(plan))
            self.assertIsNone(save_stable_snapshot(repo, "task", "implementing", plan=plan))
            plan["approval"]["plan_sha256"] = plan["plan_sha256"]
            self.assertIsNotNone(save_stable_snapshot(repo, "task", "implementing", plan=plan))
            self.assertIsNone(save_stable_snapshot(repo, "task", "implementing", plan=plan,
                                                  current_run={"task_id": "other"}))
            self.assertIsNotNone(load_stable_snapshot(repo, "task"))
            plan["execution_nonce"] = "wrong"
            self.assertIsNone(save_stable_snapshot(repo, "task", "implementing", plan=plan))

    def test_legacy_incident_url_is_rebuilt_on_load(self):
        import incident_reporter as ir
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents").mkdir()
            incident = ir.record_incident(repo, code="MANUAL_REPORT", command="test", auto_submit=False)
            incident["issue_url"] = "https://github.com/issues/new?body=private-customer"
            incident["message"] = "private-customer"
            atomic_write_json(repo / ".agents/state/incidents" / (incident["incident_id"] + ".json"), incident)
            for identifier in (None, incident["incident_id"]):
                self.assertNotIn("private-customer", ir.load_incident(repo, identifier)["issue_url"])

    def test_pm_nested_named_terminal_states_and_provider_issue_names(self):
        from integrations.universal_pm import UniversalPmIntegration
        pm = UniversalPmIntegration()
        for container in ({"status_name": "Done"}, {"transition_name": "Closed"},
                          {"status": {"name": "Done"}}, {"state": {"name": "Closed"}},
                          {"fields": {"state": "Resolved"}}, {"fields": {"transition": {"name": "Done"}}}):
            with self.subTest(container=container):
                self.assertFalse(pm.validate_pm_mutation("jira", "update_issue", container, {}, {})[0])
                self.assertTrue(pm.validate_pm_mutation("jira", "update_issue", container, {}, {"allow_close": True})[0])
        for tool in ("editJiraIssue", "jira_update_issue", "linear_update_issue"):
            self.assertFalse(pm.validate_pm_mutation("jira", tool, {"fields": {"description": ""}}, {}, {})[0])
        self.assertTrue(pm.validate_pm_mutation("jira", "create_issue", {"description": ""}, {}, {})[0])

    def test_pm_rejects_opaque_status_ids_and_empty_description(self):
        from integrations.universal_pm import UniversalPmIntegration
        pm = UniversalPmIntegration()
        for args in ({"transition": {"id": "31"}}, {"transition": {"id": "31", "name": "In Progress"}},
                     {"status_id": "31"}, {"stateId": "abc-123"}, {"status": 31},
                     {"fields": {"status": {"id": "31"}}}):
            with self.subTest(args=args):
                self.assertFalse(pm.validate_pm_mutation("jira", "transition_issue", args, {}, {"allow_close": False})[0])
                self.assertTrue(pm.validate_pm_mutation("jira", "transition_issue", args, {}, {"allow_close": True})[0])
        for value in ("", None, {}, []):
            for args in ({"description": value}, {"fields": {"description": value}}):
                self.assertFalse(pm.validate_pm_mutation("jira", "update_issue", args, {}, {"allow_close": True})[0])
        self.assertTrue(pm.validate_pm_mutation("jira", "add_comment", {"body": "test"}, {}, {})[0])
        self.assertTrue(pm.validate_pm_mutation("jira", "update_issue", {"status": "In Progress"}, {}, {})[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
