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
        self.env = mock.patch.dict(os.environ, {"ANDROID_HARNESS_ZOHO_LEDGER": str(self.ledger)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
