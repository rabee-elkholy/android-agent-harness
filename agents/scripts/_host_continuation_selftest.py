"""Cross-host continuation contracts using real task state and public commands."""
from __future__ import annotations

import contextlib
import argparse
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _phase_review_v2_selftest as phase_fixtures
from _phase_review_v2_selftest import write_file
from _vnext_common import ValidationError, atomic_write_json, read_json
from evidence_store import EvidenceStore, StateLock
from review_sources import resolve_review_host
import workflow


class HostContinuationTests(phase_fixtures.PhaseReviewV2Selftest):
    # Reuse fixture helpers, not the inherited test inventory.
    def setUp(self):
        super().setUp()
        self.host_env = mock.patch.dict(os.environ, {"HARNESS_HOST": "", "CODEX_THREAD_ID": ""})
        self.host_env.start()

    def tearDown(self):
        self.host_env.stop()
        super().tearDown()

    def cli(self, task_id, host, *extra):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_HOST": host}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = workflow.main(["continue", "--repo", str(self.repo), "--task-id", task_id,
                                  "--host", host, "--json", *extra])
        return code, json.loads(out.getvalue()) if code == 0 else err.getvalue()

    def simple_task(self):
        return self._create_phased_task([
            {"id": "p1", "name": "First", "expected_files": ["app/src/main/res/values/one.xml"]},
            {"id": "p2", "name": "Second", "expected_files": ["app/src/main/res/values/two.xml"]},
        ])

    @contextlib.contextmanager
    def installed_active_task(self):
        import _vnext_selftest as fixtures
        import lifecycle
        fixture = fixtures.LifecycleTests()
        fixture.setUp()
        previous_repo = self.repo
        try:
            fixture._answers()
            lifecycle.install(fixture.repo, fixtures.KIT)
            self.repo = fixture.repo
            yield self.simple_task(), fixtures.KIT
        finally:
            self.repo = previous_repo
            fixture.tearDown()

    def test_public_update_temporarily_reserves_and_preserves_active_task(self):
        import harness_cli
        import lifecycle
        with self.installed_active_task() as (task_id, kit):
            write_file(self.repo / "app/src/main/res/values/one.xml", "<resources/>\n")
            before = lifecycle._state_snapshot(self.repo)
            source = (self.repo / "app/src/main/res/values/one.xml").read_bytes()
            with mock.patch.dict(os.environ, {"HARNESS_HOST": "codex"}):
                expected_action = workflow.resolve_next_action(self.repo, task_id)["code"]
            with contextlib.redirect_stdout(io.StringIO()):
                code = harness_cli.main(["update", "--repo", str(self.repo), "--kit", str(kit), "--no-refresh",
                                         "--preserve-active-task", task_id, "--source-stopped"])
            self.assertEqual(0, code)
            self.assertEqual(before, lifecycle._state_snapshot(self.repo))
            self.assertEqual(source, (self.repo / "app/src/main/res/values/one.xml").read_bytes())
            self.assertFalse(StateLock(self.repo / ".harness-setup/lifecycle").path.exists())
            journal = read_json(self.repo / ".harness-setup/update-journal.json")
            self.assertEqual(task_id, journal["preserved_active_task"]["task_id"])
            self.assertEqual("COMPLETED", journal["status"])
            with mock.patch.dict(os.environ, {"HARNESS_HOST": "codex"}):
                self.assertEqual(expected_action, workflow.resolve_next_action(self.repo, task_id)["code"])

    def test_active_update_keeps_engine_directories_and_asks_for_reload(self):
        """Real app: after an update an open chat reported its reviewer subagents as not found.

        `.agents/` was moved aside and recreated; the in-place update keeps the directories an open
        IDE session loaded definitions from, and tells the developer to reload before continuing.
        """
        import lifecycle
        with self.installed_active_task() as (task_id, kit):
            watched = [self.repo / ".agents", self.repo / ".agents/subagents", self.repo / ".agents/state"]
            identities = [os.stat(path).st_ino for path in watched]
            stale = self.repo / ".agents/scripts/removed_in_new_release.py"
            stale.write_text("# not shipped any more\n", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                result = lifecycle.update(self.repo, kit, preserve_active_task=task_id, source_stopped=True)
            self.assertEqual("PASS", result["status"])
            self.assertTrue(result["reload_ide_required"])
            self.assertIn("Reload Window", err.getvalue())
            self.assertEqual(identities, [os.stat(path).st_ino for path in watched])
            self.assertFalse(stale.exists(), "files no longer shipped are removed by the in-place update")
            self.assertTrue((self.repo / ".agents/subagents/security-perf-reviewer-agent.json").is_file())
            self.assertEqual([], list(self.repo.glob(".agents.previous-*")))

            with mock.patch.object(lifecycle, "_warm_project_graph", side_effect=OSError("simulated interruption")):
                with self.assertRaises(OSError), contextlib.redirect_stdout(io.StringIO()):
                    lifecycle.update(self.repo, kit, preserve_active_task=task_id, source_stopped=True)
            self.assertEqual(identities, [os.stat(path).st_ino for path in watched])
            self.assertEqual([], list(self.repo.glob(".agents.previous-*")))

    def test_active_update_requires_stopped_source_and_rejects_a_live_writer(self):
        import lifecycle
        with self.installed_active_task() as (task_id, kit):
            for arguments in ({}, {"preserve_active_task": task_id},
                              {"preserve_active_task": "another-task", "source_stopped": True}):
                with self.assertRaises(ValidationError):
                    lifecycle.update(self.repo, kit, **arguments)
            before = lifecycle._state_snapshot(self.repo)
            with StateLock(workflow.task_dir(self.repo, task_id) / "execution", timeout_seconds=0):
                with self.assertRaisesRegex(ValidationError, "live process"):
                    lifecycle.update(self.repo, kit, preserve_active_task=task_id, source_stopped=True)
            self.assertEqual(before, lifecycle._state_snapshot(self.repo))

    def test_failed_active_update_restores_engine_ownership_and_task(self):
        import lifecycle
        with self.installed_active_task() as (task_id, kit):
            before = lifecycle._state_snapshot(self.repo)
            ownership = (self.repo / ".harness-setup/ownership-v1.json").read_bytes()
            engine = (self.repo / ".agents/scripts/workflow.py").read_bytes()
            with mock.patch.object(lifecycle, "_warm_project_graph", side_effect=OSError("simulated interruption")):
                with self.assertRaisesRegex(OSError, "simulated interruption"):
                    lifecycle.update(self.repo, kit, preserve_active_task=task_id, source_stopped=True)
            self.assertEqual(before, lifecycle._state_snapshot(self.repo))
            self.assertEqual(ownership, (self.repo / ".harness-setup/ownership-v1.json").read_bytes())
            self.assertEqual(engine, (self.repo / ".agents/scripts/workflow.py").read_bytes())
            self.assertEqual("ROLLED_BACK", read_json(self.repo / ".harness-setup/update-journal.json")["status"])

    def test_native_write_guard_pauses_for_update_and_releases_afterward(self):
        task_id = self.simple_task()
        payload = {"toolName": "write_to_file", "toolArgs": {
            "TargetFile": str(self.repo / "app/src/main/res/values/one.xml"), "CodeContent": "<resources/>"}}
        with StateLock(self.repo / ".harness-setup/lifecycle", timeout_seconds=0):
            _, result = self._run_pre_tool_safety(payload)
        self.assertEqual("deny", result.get("decision"), result)
        self.assertIn("HARNESS_UPDATE_PAUSED", result.get("reason", ""))
        _, result = self._run_pre_tool_safety(payload)
        self.assertEqual("allow", result.get("decision"), result)

    def test_interrupted_active_update_blocks_execution_until_recovered(self):
        import lifecycle
        from host_continuation import assert_execution_session
        with self.installed_active_task() as (task_id, kit):
            before = lifecycle._state_snapshot(self.repo)
            with mock.patch.object(lifecycle, "_warm_project_graph", side_effect=KeyboardInterrupt("simulated crash")):
                with self.assertRaises(KeyboardInterrupt):
                    lifecycle.update(self.repo, kit, preserve_active_task=task_id, source_stopped=True)
            with self.assertRaisesRegex(ValidationError, "HARNESS_UPDATE_INCOMPLETE"):
                assert_execution_session(self.repo, task_id)
            result = lifecycle.update(self.repo, kit, preserve_active_task=task_id, source_stopped=True)
            self.assertEqual("PASS", result["status"])
            self.assertEqual(before, lifecycle._state_snapshot(self.repo))
            self.assertEqual("COMPLETED", read_json(self.repo / ".harness-setup/update-journal.json")["status"])

    def test_current_codex_session_beats_installed_primary(self):
        write_file(self.repo / ".agents/scripts/_product.py", "PRIMARY_AI_HOST = 'antigravity'\n")
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "actual-codex-thread"}):
            self.assertEqual("codex", resolve_review_host(self.repo))
            self.assertEqual("antigravity", resolve_review_host(self.repo, "antigravity"))

    def test_cancelled_task_status_does_not_request_an_impossible_takeover(self):
        task_id = self.simple_task()
        code, result = self.cli(task_id, "codex")
        self.assertEqual(0, code, result)
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "codex"}), contextlib.redirect_stdout(io.StringIO()):
            code = workflow.main(["cancel", "--repo", str(self.repo), "--task-id", task_id,
                                  "--source", "conversation", "--proof-reference", "Cancel the fixture"])
        self.assertEqual(0, code)
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "antigravity"}), contextlib.redirect_stdout(output):
            code = workflow.main(["status", "--repo", str(self.repo), "--task-id", task_id,
                                  "--host", "antigravity", "--next", "--json"])
        self.assertEqual(0, code)
        self.assertEqual("CANCELLED", json.loads(output.getvalue())["next_action"]["code"])

    def test_invalid_receiving_host_is_a_clean_cli_failure(self):
        task_id = self.simple_task()
        error = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_HOST": ""}), contextlib.redirect_stderr(error):
            code = workflow.main(["continue", "--repo", str(self.repo), "--task-id", task_id,
                                  "--host", "invalid host", "--json"])
        self.assertNotEqual(0, code)
        self.assertIn("invalid review host", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())

    def test_continue_preserves_approval_and_blocks_previous_writer(self):
        task_id = self.simple_task()
        directory = workflow.task_dir(self.repo, task_id)
        original = (directory / "plan.json").read_bytes()
        code, first = self.cli(task_id, "codex")
        self.assertEqual(0, code, first)
        code, second = self.cli(task_id, "antigravity", "--source-stopped", "--expect-session", first["session_id"])
        self.assertEqual(0, code, second)
        self.assertEqual(original, (directory / "plan.json").read_bytes())
        self.assertEqual("antigravity", second["host"])
        self.assertEqual("IMPLEMENT_APPROVED_SCOPE", second["next_action"]["code"])
        from mutation_guard import file_mutation_allowed
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "codex"}):
            allowed, reason, _ = file_mutation_allowed(self.repo)
            self.assertFalse(allowed)
            self.assertIn("HOST_SESSION_MISMATCH", reason)

    def test_continue_is_idempotent_and_rejects_stale_transfer(self):
        task_id = self.simple_task()
        code, first = self.cli(task_id, "codex")
        self.assertEqual(0, code, first)
        code, again = self.cli(task_id, "codex")
        self.assertEqual(first["session_id"], again["session_id"])
        code, denial = self.cli(task_id, "antigravity")
        self.assertNotEqual(0, code)
        self.assertIn("source-stopped", denial)
        code, second = self.cli(task_id, "antigravity", "--source-stopped", "--expect-session", first["session_id"])
        self.assertEqual(0, code, second)
        code, denial = self.cli(task_id, "codex", "--source-stopped", "--expect-session", first["session_id"])
        self.assertNotEqual(0, code)
        self.assertIn("STALE_HOST_SESSION", denial)

    def test_wrong_host_phase_run_restarts_without_repeating_checkpoint(self):
        task_id, reviewers, _, old = self._setup_dispatch_state()
        directory = workflow.task_dir(self.repo, task_id)
        checkpoint = directory / "phases/p1/checkpoint.json"
        checkpoint_bytes = checkpoint.read_bytes()
        plan_bytes = (directory / "plan.json").read_bytes()
        code, result = self.cli(task_id, "codex", "--source-stopped")
        self.assertEqual(0, code, result)
        new = read_json(directory / "phases/p1/review/current-phase-run.json")
        self.assertEqual("codex", new["review_host"])
        self.assertNotEqual(old["phase_review_run_id"], new["phase_review_run_id"])
        self.assertEqual(checkpoint_bytes, checkpoint.read_bytes())
        self.assertEqual(plan_bytes, (directory / "plan.json").read_bytes())
        self.assertTrue((directory / "phases/p1/review-history" / old["phase_review_run_id"] / "ledger.json").is_file())
        self.assertEqual(set(reviewers), set(new["selected_reviewers"]))
        self.assertEqual("DISPATCH_PHASE_REVIEWERS", result["next_action"]["code"])
        self.assertIn("--host codex", result["next_action"]["command"])

    def test_transfer_cannot_hide_phase_findings(self):
        task_id, _, _, _ = self._setup_dispatch_state()
        import phase_review
        directory = workflow.task_dir(self.repo, task_id)
        phase_review.set_phase_substate(directory, "p1", phase_review.PHASE_REVIEW_BLOCKED)
        old = (directory / "phases/p1/review/current-phase-run.json").read_bytes()
        code, result = self.cli(task_id, "codex", "--source-stopped")
        self.assertEqual(0, code, result)
        self.assertEqual(old, (directory / "phases/p1/review/current-phase-run.json").read_bytes())
        self.assertEqual("FIX_PHASE_FINDINGS", result["next_action"]["code"])

    def test_phase_findings_remain_takeoverable_after_the_restart_limit(self):
        task_id, reviewers, _, run = self._setup_dispatch_state()
        directory = workflow.task_dir(self.repo, task_id)
        run["host_restart_count"] = 3
        atomic_write_json(directory / "phases/p1/review/current-phase-run.json", run)
        from phase_review import compute_ledger_sha, load_phase_ledger
        ok, reason, ledger = load_phase_ledger(directory, "p1", expected_run_id=run["phase_review_run_id"])
        self.assertTrue(ok, reason)
        ledger["reviewers"][reviewers[0]].update(
            state="COMPLETED",
            verdict="FINDINGS",
            findings=[{"id": "finding-1", "severity": "HIGH"}],
        )
        ledger["ledger_sha256"] = compute_ledger_sha(ledger)
        atomic_write_json(directory / "phases/p1/review/ledger.json", ledger)
        code, result = self.cli(task_id, "codex", "--source-stopped")
        self.assertEqual(0, code, result)
        self.assertEqual(run, read_json(directory / "phases/p1/review/current-phase-run.json"))
        self.assertEqual("FIX_PHASE_FINDINGS", result["next_action"]["code"])

    def test_transfer_refuses_corrupt_plan_and_live_writer(self):
        task_id = self.simple_task()
        directory = workflow.task_dir(self.repo, task_id)
        with StateLock(directory / "execution", timeout_seconds=0):
            code, denial = self.cli(task_id, "codex")
        self.assertNotEqual(0, code)
        self.assertIn("live process", denial)
        plan = read_json(directory / "plan.json")
        plan["requested_outcome"] = "tampered"
        atomic_write_json(directory / "plan.json", plan)
        code, denial = self.cli(task_id, "codex")
        self.assertNotEqual(0, code)
        self.assertFalse((directory / "host-session.json").exists())

    def test_evidence_reuse_validates_original_and_never_reuses_reviews(self):
        store = EvidenceStore(self.repo / ".agents/state")
        snapshot, changes = "a" * 64, "b" * 64
        original = store.write(snapshot=snapshot, run_id="old", name="unit_tests", producer="run_tests_gate",
                               harness_version="1.1.23", change_set=changes, status="PASS", evidence={"tests": 7})
        source = store.read(snapshot, "old", "unit_tests")
        store.reuse(snapshot=snapshot, source_run_id="old", run_id="new", name="unit_tests", lock=False)
        reused = store.read(snapshot, "new", "unit_tests")
        self.assertEqual(source["artifact_sha256"], reused["reused_from"]["artifact_sha256"])
        self.assertEqual(source["evidence"], reused["evidence"])
        with self.assertRaises(ValidationError):
            store.reuse(snapshot=snapshot, source_run_id="old", run_id="bad", name="reviews", lock=False)
        original.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValidationError):
            store.read(snapshot, "new", "unit_tests")

    def final_task(self):
        task_id = self._create_phased_task([
            {"id": "p1", "name": "First", "expected_files": ["app/src/main/java/com/example/First.kt"]},
            {"id": "p2", "name": "Second", "expected_files": ["app/src/main/java/com/example/Second.kt"]},
        ])
        for phase_id, name in (("p1", "First"), ("p2", "Second")):
            write_file(self.repo / "app/src/main/java/com/example" / (name + ".kt"), "package com.example\nclass " + name + "\n")
            self._pass_phase_tests(task_id, phase_id)
            workflow.checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id=phase_id))
            if phase_id == "p1":
                workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        run = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id, host="codex"))
        self.assertTrue(read_json(Path(run["policy"]))["reviewers"], "exercise a real final-review requirement")
        return task_id, run

    def test_final_review_restart_carries_tests_without_approval_or_budget_reset(self):
        task_id, old = self.final_task()
        directory = workflow.task_dir(self.repo, task_id)
        before = read_json(directory / "plan.json")
        store = EvidenceStore(self.repo / ".agents/state")
        store.write(snapshot=old["delivery_snapshot_sha256"], run_id=old["run_id"], name="unit_tests",
                    producer="run_tests_gate", harness_version="1.1.23", change_set=old["change_set_sha256"],
                    status="PASS", evidence={"tests": 9})
        code, result = self.cli(task_id, "antigravity", "--source-stopped")
        self.assertEqual(0, code, result)
        current = read_json(directory / "current-run.json")
        self.assertNotEqual(old["run_id"], current["run_id"])
        self.assertEqual("antigravity", current["review_host"])
        self.assertEqual(["unit_tests"], result["reused_artifacts"])
        after = read_json(directory / "plan.json")
        self.assertEqual(before["approval"], after["approval"])
        self.assertEqual(before["plan_sha256"], after["plan_sha256"])
        self.assertEqual(before.get("review_rounds", 0), after.get("review_rounds", 0))
        self.assertEqual({"tests": 9}, store.read(current["delivery_snapshot_sha256"], current["run_id"], "unit_tests")["evidence"])

    def test_failed_transfer_restores_review_and_can_be_retried(self):
        task_id, _, _, old = self._setup_dispatch_state()
        directory = workflow.task_dir(self.repo, task_id)
        import host_continuation
        with mock.patch.object(host_continuation, "atomic_write_json", side_effect=lambda path, data:
                               (_ for _ in ()).throw(OSError("simulated session publication failure"))
                               if path.name == "host-session.json" else atomic_write_json(path, data)):
            code, denial = self.cli(task_id, "codex", "--source-stopped")
        self.assertNotEqual(0, code)
        self.assertIn("simulated", denial)
        self.assertEqual(old, read_json(directory / "phases/p1/review/current-phase-run.json"))
        self.assertFalse((directory / "host-session.json").exists())
        code, result = self.cli(task_id, "codex", "--source-stopped")
        self.assertEqual(0, code, result)

    def test_final_transfer_preserves_protocol_attempts_and_charges_interrupted_dispatch(self):
        task_id, old = self.final_task()
        directory = workflow.task_dir(self.repo, task_id)
        from review_orchestrator import init_ledger, load_ledger, save_ledger
        roles = read_json(Path(old["policy"]))["reviewers"]
        ledger = init_ledger(directory, task_id, old["run_id"], old["delivery_snapshot_sha256"],
                             old["change_set_sha256"], "", roles)
        ledger["reviewers"][roles[0]].update(state="PROTOCOL_RETRY_REQUIRED", protocol_attempts=1)
        save_ledger(directory, old["run_id"], ledger)
        before = read_json(directory / "plan.json")
        code, result = self.cli(task_id, "antigravity", "--source-stopped")
        self.assertEqual(0, code, result)
        current = read_json(directory / "current-run.json")
        replacement = load_ledger(directory, current["run_id"])
        self.assertEqual(1, replacement["reviewers"][roles[0]]["protocol_attempts"])
        self.assertEqual("NOT_DISPATCHED", replacement["reviewers"][roles[0]]["state"])
        self.assertEqual(int(before.get("review_calls_used") or 0) + 1,
                         read_json(directory / "plan.json")["review_calls_used"])
        from review_package import build_package
        build_package(self.repo, task_id)
        self.assertEqual(1, load_ledger(directory, current["run_id"])["reviewers"][roles[0]]["protocol_attempts"])

    def test_host_transfer_cannot_reset_exhausted_final_review_protocol(self):
        task_id, old = self.final_task()
        directory = workflow.task_dir(self.repo, task_id)
        from review_orchestrator import init_ledger, save_ledger
        roles = read_json(Path(old["policy"]))["reviewers"]
        ledger = init_ledger(directory, task_id, old["run_id"], old["delivery_snapshot_sha256"],
                             old["change_set_sha256"], "", roles)
        ledger["reviewers"][roles[0]].update(state="FAILED_PROTOCOL", protocol_attempts=2)
        save_ledger(directory, old["run_id"], ledger)
        before = (directory / "plan.json").read_bytes()
        code, denial = self.cli(task_id, "antigravity", "--source-stopped")
        self.assertNotEqual(0, code)
        self.assertIn("REVIEW_PROTOCOL_BLOCKED", denial)
        self.assertEqual(old, read_json(directory / "current-run.json"))
        self.assertEqual(before, (directory / "plan.json").read_bytes())
        self.assertFalse((directory / "host-session.json").exists())

    def test_router_detects_wrong_frozen_host_before_dispatch(self):
        task_id, _, _, _ = self._setup_dispatch_state()
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "codex-thread"}):
            action = workflow.resolve_next_action(self.repo, task_id)
        self.assertEqual("CONTINUE_ON_CURRENT_HOST", action["code"])
        self.assertIn("--host codex", action["command"])

    def test_reused_evidence_sources_survive_pruning(self):
        store = EvidenceStore(self.repo / ".agents/state")
        snapshot = "a" * 64
        store.write(snapshot=snapshot, run_id="old", name="unit_tests", producer="run_tests_gate",
                    harness_version="1.1.23", change_set="b" * 64, status="PASS", evidence={"tests": 7})
        store.reuse(snapshot=snapshot, source_run_id="old", run_id="new", name="unit_tests", lock=False)
        store.prune(keep=0, protected={(snapshot, "new")})
        self.assertEqual("PASS", store.read(snapshot, "new", "unit_tests")["status"])

    def test_reused_pass_is_invalidated_by_a_later_original_failure(self):
        store = EvidenceStore(self.repo / ".agents/state")
        snapshot = "a" * 64
        kwargs = dict(snapshot=snapshot, name="unit_tests", producer="run_tests_gate",
                      harness_version="1.1.23", change_set="b" * 64)
        store.write(**kwargs, run_id="old", status="PASS", evidence={"tests": 7})
        store.reuse(snapshot=snapshot, source_run_id="old", run_id="new", name="unit_tests", lock=False)
        store.write(**kwargs, run_id="old", status="FAIL", evidence={"tests": 1}, allow_pass_retry=True)
        with self.assertRaises(ValidationError):
            store.read(snapshot, "new", "unit_tests")

    def test_stale_snapshot_can_change_executor_without_reusing_proof(self):
        task_id, old = self.final_task()
        directory = workflow.task_dir(self.repo, task_id)
        original = (directory / "current-run.json").read_bytes()
        write_file(self.repo / "app/src/main/java/com/example/First.kt", "package com.example\nclass Changed\n")
        code, result = self.cli(task_id, "antigravity", "--source-stopped")
        self.assertEqual(0, code, result)
        self.assertEqual([], result["reused_artifacts"])
        self.assertEqual([], result["restarted_reviews"])
        self.assertEqual("VERIFICATION_STALE", result["next_action"]["code"])
        self.assertEqual(original, (directory / "current-run.json").read_bytes())
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "antigravity"}), contextlib.redirect_stdout(io.StringIO()):
            code = workflow.main(["resume", "--repo", str(self.repo), "--task-id", task_id])
        self.assertEqual(0, code)
        self.assertEqual("IMPLEMENTING", read_json(directory / "plan.json")["status"])

    def test_engine_update_cannot_restart_host_reviews_or_reuse_old_gates(self):
        task_id, old = self.final_task()
        directory = workflow.task_dir(self.repo, task_id)
        original = (directory / "current-run.json").read_bytes()
        plan = (directory / "plan.json").read_bytes()
        write_file(self.repo / ".agents/VERSION", "9.9.9\n")
        code, result = self.cli(task_id, "antigravity", "--source-stopped")
        self.assertEqual(0, code, result)
        self.assertEqual([], result["reused_artifacts"])
        self.assertEqual([], result["restarted_reviews"])
        self.assertEqual("VERIFICATION_STALE", result["next_action"]["code"])
        self.assertIn("HARNESS_VERSION_CHANGED", result["next_action"]["reason"])
        self.assertEqual(original, (directory / "current-run.json").read_bytes())
        self.assertEqual(plan, (directory / "plan.json").read_bytes())

    def test_wrong_run_snapshot_cannot_transfer_foreign_gate_evidence(self):
        task_id, run = self.final_task()
        directory = workflow.task_dir(self.repo, task_id)
        run["delivery_snapshot_sha256"] = "f" * 64
        atomic_write_json(directory / "current-run.json", run)
        code, denial = self.cli(task_id, "antigravity", "--source-stopped")
        self.assertNotEqual(0, code)
        self.assertIn("verification run and manifest identity mismatch", denial)
        self.assertFalse((directory / "host-session.json").exists())

    def test_registered_partial_final_findings_survive_transfer(self):
        task_id, run = self.final_task()
        directory = workflow.task_dir(self.repo, task_id)
        from review_package import build_package
        from _vnext_common import sha256_file
        import record_review
        role = read_json(Path(run["policy"]))["reviewers"][0]
        # Use the public ingestion path; this response is explicitly unverified,
        # and its findings must block even before full-round aggregation.
        package, _ = build_package(self.repo, task_id)
        response = directory / "reviewer-response.txt"
        response.write_text('```json\n' + json.dumps({
            "schema_version": 2, "task_id": task_id, "run_id": run["run_id"], "reviewer": role,
            "review_package_sha256": sha256_file(package), "verdict": "FINDINGS",
            "findings": [{"id": "bug-1", "severity": "HIGH", "title": "Invalid calculation",
                          "message": "Incorrect result", "file": "app/src/main/java/com/example/First.kt",
                          "line_start": 2, "line_end": 2, "evidence": "Missing bound", "recommended_fix": "Add bound"}],
        }) + '\n```', encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = record_review.main(["--repo", str(self.repo), "--task", task_id, "--response", role + "=" + str(response)])
        self.assertEqual(0, code)
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "antigravity"}):
            action = workflow.resolve_next_action(self.repo, task_id)
        self.assertEqual("CONTINUE_ON_CURRENT_HOST", action["code"])
        code, result = self.cli(task_id, "antigravity", "--source-stopped")
        self.assertEqual(0, code, result)
        self.assertEqual(run, read_json(directory / "current-run.json"))
        self.assertEqual("BLOCKED", read_json(directory / "plan.json")["status"])
        self.assertIn(role, result["brief"]["blocked_reviewers"])
        self.assertEqual("RESUME_IMPLEMENTATION", result["next_action"]["code"])

    def test_new_codex_chat_is_a_new_executor_on_the_same_host(self):
        task_id = self.simple_task()
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "first-thread"}):
            code, first = self.cli(task_id, "codex")
        self.assertEqual(0, code, first)
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "second-thread"}):
            action = workflow.resolve_next_action(self.repo, task_id)
            self.assertEqual("CONTINUE_ON_CURRENT_HOST", action["code"])
            code, second = self.cli(task_id, "codex", "--source-stopped", "--expect-session", first["session_id"])
        self.assertEqual(0, code, second)
        from host_continuation import assert_execution_session
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "first-thread"}):
            with self.assertRaises(ValidationError):
                assert_execution_session(self.repo, task_id)

    def test_interrupted_commit_recovers_from_the_routed_command(self):
        task_id, _, _, _ = self._setup_dispatch_state()
        import host_continuation
        save = host_continuation._save_transition
        def interrupt(directory, data):
            if data["status"] == "COMPLETED":
                raise KeyboardInterrupt("simulated process interruption")
            save(directory, data)
        with mock.patch.object(host_continuation, "_save_transition", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.cli(task_id, "codex", "--source-stopped")
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "codex"}):
            action = workflow.resolve_next_action(self.repo, task_id)
        self.assertEqual("CONTINUE_ON_CURRENT_HOST", action["code"])
        self.assertNotIn("--expect-session", action["command"])
        code, result = self.cli(task_id, "codex", "--source-stopped")
        self.assertEqual(0, code, result)

    def test_source_native_hook_rejects_file_writes_after_takeover(self):
        task_id = self.simple_task()
        code, _ = self.cli(task_id, "codex")
        self.assertEqual(0, code)
        code, result = self._run_pre_tool_safety({"toolName": "write_to_file", "toolArgs": {
            "TargetFile": str(self.repo / "app/src/main/res/values/one.xml"), "CodeContent": "<resources/>"}})
        self.assertEqual("deny", result.get("decision"), result)
        self.assertIn("HOST_SESSION_MISMATCH", result.get("reason", ""))

    def test_plain_continue_returns_the_brief_and_canonical_next_action(self):
        task_id = self.simple_task()
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_HOST": "codex"}), contextlib.redirect_stdout(output):
            code = workflow.main(["continue", "--repo", str(self.repo), "--task-id", task_id, "--host", "codex"])
        self.assertEqual(0, code)
        self.assertIn("RESUME_BRIEF=", output.getvalue())
        self.assertIn("NEXT_ACTION=IMPLEMENT_APPROVED_SCOPE", output.getvalue())

    def test_unknown_current_host_keeps_the_frozen_review_host(self):
        task_id, _, _, _ = self._setup_dispatch_state()
        write_file(self.repo / ".agents/scripts/_product.py", "PRIMARY_AI_HOST = 'codex'\n")
        action = workflow.resolve_next_action(self.repo, task_id)
        self.assertEqual("DISPATCH_PHASE_REVIEWERS", action["code"])
        self.assertEqual("INHERIT_PARENT_BY_OMISSION", action["review_execution_profile"]["model_policy"])

    def test_task_bridge_follow_up_after_deliver_mints_fresh_discovery_receipt(self):
        import time
        import discovery_receipt
        task_id = self.simple_task()
        directory = workflow.task_dir(self.repo, task_id)
        plan = read_json(directory / "plan.json")
        plan["status"] = "DELIVERED"
        plan["delivered_at"] = "2026-11-09T20:00:00+00:00"
        plan["expected_files"] = ["app/src/main/java/com/example/App.kt"]
        workflow.save_plan(directory / "plan.json", plan)
        (self.repo / ".agents/state/active-task.json").unlink(missing_ok=True)
        discovery_receipt.clear_latest_discovery_receipt(self.repo)

        save_out = io.StringIO()
        with contextlib.redirect_stdout(save_out):
            code = workflow.main([
                "bridge", "--save", "--repo", str(self.repo),
                "--next-outcome", "Add input validation to App",
                "--summary", "Delivered initial App screen",
                "--json",
            ])
        self.assertEqual(0, code)
        saved = json.loads(save_out.getvalue())
        self.assertEqual("BRIDGE_SAVED", saved["status"])
        self.assertEqual("FOLLOW_UP_TASK", saved["mode"])
        self.assertEqual(task_id, saved["task_snapshot"]["task_id"])
        self.assertIn("app/src/main/java/com/example/App.kt", saved["discovery_seed"]["resolved_paths"])

        # Simulate a new conversation starting after the bridge was saved
        prev_not_before = discovery_receipt.RECEIPT_NOT_BEFORE
        try:
            discovery_receipt.RECEIPT_NOT_BEFORE = time.time() - 0.01
            load_out = io.StringIO()
            with contextlib.redirect_stdout(load_out):
                code = workflow.main(["bridge", "--repo", str(self.repo), "--json"])
            self.assertEqual(0, code)
            loaded = json.loads(load_out.getvalue())
            self.assertEqual("BRIDGE_LOADED", loaded["status"])
            self.assertEqual("FOLLOW_UP_TASK", loaded["mode"])
            self.assertEqual("Add input validation to App", loaded["next_outcome"])
            self.assertEqual("DRAFT_BRIDGED_FOLLOWUP_TASK", loaded["next_action"]["code"])
            fresh_rec = discovery_receipt.load_latest_discovery_receipt(self.repo)
            self.assertIsNotNone(fresh_rec)
            self.assertEqual("task_bridge", fresh_rec["mode"])
            self.assertIn("app/src/main/java/com/example/App.kt", fresh_rec["resolved_paths"])

            draft_out = io.StringIO()
            with contextlib.redirect_stdout(draft_out), contextlib.redirect_stderr(io.StringIO()):
                d_code = workflow.main([
                    "draft", "--repo", str(self.repo),
                    "--task-id", "followup-validation",
                    "--outcome", "Add input validation to App",
                    "--expected-files", "app/src/main/java/com/example/App.kt",
                    "--approach", "Validate App inputs before submission",
                    "--json",
                ])
            self.assertEqual(0, d_code)
            drafted = read_json(workflow.task_dir(self.repo, "followup-validation") / "plan.json")
            self.assertEqual("task_bridge", (drafted.get("discovery_provenance") or {}).get("discovery_mode"))
        finally:
            discovery_receipt.RECEIPT_NOT_BEFORE = prev_not_before

    def test_task_bridge_mid_task_handoff_transfers_session_and_is_idempotent(self):
        from mutation_guard import command_allowed
        task_id = self.simple_task()
        code, _ = self.cli(task_id, "claude")
        self.assertEqual(0, code)

        save_out = io.StringIO()
        with contextlib.redirect_stdout(save_out):
            s_code = workflow.main([
                "bridge", "--save", "--repo", str(self.repo),
                "--task-id", task_id,
                "--summary", "Mid-task checkpoint on First.kt",
                "--json",
            ])
        self.assertEqual(0, s_code)
        saved = json.loads(save_out.getvalue())
        self.assertEqual("MID_TASK_HANDOFF", saved["mode"])

        with mock.patch.dict(os.environ, {"HARNESS_HOST": "codex", "CODEX_THREAD_ID": "new-thread-99"}):
            allowed, reason = command_allowed(self.repo, "python .agents/harness.py task bridge")
            self.assertTrue(allowed, reason)
            load_out = io.StringIO()
            with contextlib.redirect_stdout(load_out):
                l_code = workflow.main(["bridge", "--repo", str(self.repo), "--host", "codex", "--json"])
            self.assertEqual(0, l_code)
            loaded = json.loads(load_out.getvalue())
            self.assertEqual("BRIDGE_CONTINUED", loaded["status"])
            self.assertEqual("codex", loaded["host"])
            self.assertEqual("IMPLEMENT_APPROVED_SCOPE", loaded["next_action"]["code"])

            # Second load in the same chat is idempotent
            load_out_2 = io.StringIO()
            with contextlib.redirect_stdout(load_out_2):
                l_code_2 = workflow.main(["bridge", "--repo", str(self.repo), "--host", "codex", "--json"])
            self.assertEqual(0, l_code_2)
            loaded_2 = json.loads(load_out_2.getvalue())
            self.assertEqual("BRIDGE_CONTINUED", loaded_2["status"])

    def test_smart_context_rotation_advisory_and_snooze(self):
        task_id = self.simple_task()
        directory = workflow.task_dir(self.repo, task_id)
        plan = read_json(directory / "plan.json")
        plan["status"] = "DELIVERED"
        workflow.save_plan(directory / "plan.json", plan)

        with mock.patch.dict(os.environ, {"HARNESS_CONVERSATION_STEPS": "150"}):
            act = workflow.resolve_next_action(self.repo, task_id, plan)
            self.assertEqual("TASK_DELIVERED", act["code"])
            self.assertIn("context_rotation", act)
            self.assertEqual("FOLLOW_UP_TASK", act["context_rotation"]["mode"])

            # Snooze for 100 steps (until 250)
            snooze_out = io.StringIO()
            with contextlib.redirect_stdout(snooze_out):
                self.assertEqual(0, workflow.main(["bridge", "--snooze", "--snooze-steps", "100", "--repo", str(self.repo), "--json"]))
            act_snoozed = workflow.resolve_next_action(self.repo, task_id, plan)
            self.assertNotIn("context_rotation", act_snoozed)

        with mock.patch.dict(os.environ, {"HARNESS_CONVERSATION_STEPS": "260"}):
            act_after = workflow.resolve_next_action(self.repo, task_id, plan)
            self.assertIn("context_rotation", act_after)

    def test_pre_tool_safety_records_active_conversation_turns(self):
        conv_id = "11111111-2222-3333-4444-555555555555"
        for _ in range(2):
            code, res = self._run_pre_tool_safety({
                "conversationId": conv_id,
                "toolName": "view_file",
                "toolArgs": {"AbsolutePath": str(self.repo / "app/src/main/java/com/example/First.kt")},
            })
            self.assertEqual(0, code, res)
        conv_file = self.repo / ".agents/state/active-conversation.json"
        self.assertTrue(conv_file.is_file())
        data = read_json(conv_file)
        self.assertEqual(conv_id, data["conversation_id"])
        self.assertEqual(2, data["hook_calls"])

    def test_task_bridge_edge_cases_integrity_repo_mismatch_and_transcript_tail(self):
        from task_bridge import _inspect_transcript_tail

        # 1. Missing bridge fails closed
        err_out = io.StringIO()
        with contextlib.redirect_stdout(err_out):
            self.assertEqual(1, workflow.main(["bridge", "--repo", str(self.repo), "--json"]))
        self.assertIn("TASK_BRIDGE_NOT_FOUND", err_out.getvalue())

        # 2. Save bridge and inspect --status
        task_id = self.simple_task()
        save_out = io.StringIO()
        with contextlib.redirect_stdout(save_out):
            self.assertEqual(0, workflow.main(["bridge", "--save", "--repo", str(self.repo), "--task-id", task_id, "--json"]))

        status_out = io.StringIO()
        with contextlib.redirect_stdout(status_out):
            self.assertEqual(0, workflow.main(["bridge", "--status", "--repo", str(self.repo), "--json"]))
        st = json.loads(status_out.getvalue())
        self.assertEqual("READY", st["status"])
        self.assertIsNotNone(st["saved_bridge"])
        self.assertEqual(task_id, st["saved_bridge"]["task_id"])

        # 3. Tampered bridge fails closed
        b_path = self.repo / ".agents/state/task-bridge.json"
        b_data = read_json(b_path)
        Tampered = dict(b_data, next_outcome="tampered without updating sha")
        atomic_write_json(b_path, Tampered)
        tamper_out = io.StringIO()
        with contextlib.redirect_stdout(tamper_out):
            self.assertEqual(1, workflow.main(["bridge", "--repo", str(self.repo), "--json"]))
        self.assertIn("TASK_BRIDGE_INTEGRITY_ERROR", tamper_out.getvalue())

        # 4. Repo root mismatch fails closed even with recalculated sha
        from _vnext_common import canonical_sha256
        from task_bridge import _bridge_canonical_fields
        mismatch = dict(b_data)
        mismatch["repository"] = dict(b_data["repository"], root_sha256="0" * 64)
        mismatch["bridge_sha256"] = canonical_sha256(_bridge_canonical_fields(mismatch))
        atomic_write_json(b_path, mismatch)
        mismatch_out = io.StringIO()
        with contextlib.redirect_stdout(mismatch_out):
            self.assertEqual(1, workflow.main(["bridge", "--repo", str(self.repo), "--json"]))
        self.assertIn("TASK_BRIDGE_REPO_MISMATCH", mismatch_out.getvalue())

        # 5. Transcript tail inspection extracts step_index and token usage
        fake_transcript = self.repo / "transcript.jsonl"
        fake_transcript.write_text(
            json.dumps({"step_index": 42, "type": "USER_INPUT"}) + "\n"
            + json.dumps({"step_index": 185, "type": "PLANNER_RESPONSE", "usage": {"input_tokens": 92000, "cache_read_tokens": 4500}}) + "\n",
            encoding="utf-8",
        )
        t_metrics = _inspect_transcript_tail(fake_transcript)
        self.assertEqual(185, t_metrics["steps"])
        self.assertEqual(96500, t_metrics["tokens"])

    def test_task_bridge_interface_delta_intent_aware_reminder_and_clear(self):
        import pre_invocation_reminder
        from task_bridge import pending_bridge_reminder

        app_kt = self.repo / "app/src/main/java/com/example/App.kt"
        write_file(
            app_kt,
            "package com.example\n\n"
            "// Comment should be ignored\n"
            "data class LoginUiState(val email: String = \"\", val isLoading: Boolean = false)\n\n"
            "class LoginViewModel {\n"
            "    suspend fun submitCredentials(email: String, pass: String): Boolean {\n"
            "        return true\n"
            "    }\n"
            "}\n",
        )
        task_id = self.simple_task()
        directory = workflow.task_dir(self.repo, task_id)
        plan = read_json(directory / "plan.json")
        plan["status"] = "DELIVERED"
        plan["delivered_at"] = "2026-11-10T08:00:00+00:00"
        plan["expected_files"] = ["app/src/main/java/com/example/App.kt"]
        workflow.save_plan(directory / "plan.json", plan)
        (self.repo / ".agents/state/active-task.json").unlink(missing_ok=True)

        # 1. Save bridge and verify interface_delta + handoff_card + optional_notice
        save_out = io.StringIO()
        with contextlib.redirect_stdout(save_out):
            self.assertEqual(0, workflow.main([
                "bridge", "--save", "--repo", str(self.repo),
                "--next-outcome", "Add forgot password flow",
                "--json",
            ]))
        saved = json.loads(save_out.getvalue())
        self.assertIn("optional_notice", saved)
        self.assertIn("handoff_card", saved)
        self.assertIn("BRIDGE_HANDOFF_CARD_BEGIN", saved["handoff_card"])
        self.assertEqual("python .agents/harness.py task bridge --clear", saved["clear_command"])
        idelta = saved["task_snapshot"].get("interface_delta") or []
        self.assertEqual(1, len(idelta))
        self.assertEqual("app/src/main/java/com/example/App.kt", idelta[0]["path"])
        decls_joined = "\n".join(idelta[0]["declarations"])
        self.assertIn("data class LoginUiState", decls_joined)
        self.assertIn("class LoginViewModel", decls_joined)
        self.assertIn("suspend fun submitCredentials", decls_joined)

        # 2. PreInvocation reminder surfaces intent-conditional non-forced notice while unconsumed
        rem = pending_bridge_reminder(self.repo)
        self.assertIn("OPTIONAL & INTENT-CONDITIONAL", rem)
        self.assertIn("DIFFERENT or UNRELATED topic", rem)
        self.assertIn("Add forgot password flow", rem)
        with mock.patch.object(pre_invocation_reminder, "REPO", self.repo):
            compact = pre_invocation_reminder._compact_message()
        self.assertTrue(compact.startswith("Android Harness: Idle (no active task)."))
        self.assertIn("Pending Task Bridge", compact)

        # 3. Unrelated read-only tool call in the new chat does NOT consume or delete task-bridge.json
        b_path = self.repo / ".agents/state/task-bridge.json"
        self.assertTrue(b_path.is_file())
        self.assertEqual(0, int(read_json(b_path).get("consumed_count") or 0))
        code, res = self._run_pre_tool_safety({
            "conversationId": "22222222-3333-4444-5555-666666666666",
            "toolName": "view_file",
            "toolArgs": {"AbsolutePath": str(app_kt)},
        })
        self.assertEqual(0, code, res)
        self.assertTrue(b_path.is_file())
        self.assertEqual(0, int(read_json(b_path).get("consumed_count") or 0))

        # 4. Loading the bridge marks it consumed (consumed_count == 1) and stops repeating the reminder
        load_out = io.StringIO()
        with contextlib.redirect_stdout(load_out):
            self.assertEqual(0, workflow.main(["bridge", "--repo", str(self.repo), "--json"]))
        loaded = json.loads(load_out.getvalue())
        self.assertEqual(1, len((loaded.get("previous_task") or {}).get("interface_delta") or []))
        self.assertEqual(1, int(read_json(b_path).get("consumed_count") or 0))
        self.assertEqual("", pending_bridge_reminder(self.repo))

        # 5. Save again, then test explicit --clear (and idempotency when already cleared)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, workflow.main(["bridge", "--save", "--repo", str(self.repo), "--task-id", task_id, "--next-outcome", "Second follow-up", "--json"]))
        self.assertTrue(b_path.is_file())
        self.assertNotEqual("", pending_bridge_reminder(self.repo))

        clear_out = io.StringIO()
        with contextlib.redirect_stdout(clear_out):
            self.assertEqual(0, workflow.main(["bridge", "--clear", "--repo", str(self.repo), "--json"]))
        cleared = json.loads(clear_out.getvalue())
        self.assertEqual("BRIDGE_CLEARED", cleared["status"])
        self.assertTrue(cleared["archived_in_history"])
        self.assertFalse(b_path.is_file())
        self.assertEqual("", pending_bridge_reminder(self.repo))

        # Second --clear is idempotent
        clear_out_2 = io.StringIO()
        with contextlib.redirect_stdout(clear_out_2):
            self.assertEqual(0, workflow.main(["bridge", "--clear", "--repo", str(self.repo), "--json"]))
        cleared_2 = json.loads(clear_out_2.getvalue())
        self.assertEqual("BRIDGE_CLEARED", cleared_2["status"])
        self.assertEqual("", cleared_2["bridge_id"])

    def test_multi_bridge_queue_disambiguation_and_selective_consumption(self):
        from task_bridge import pending_bridge_reminder

        task_a = self.simple_task()
        dir_a = workflow.task_dir(self.repo, task_a)
        plan_a = read_json(dir_a / "plan.json")
        plan_a["status"] = "DELIVERED"
        plan_a["delivered_at"] = "2026-11-10T08:10:00+00:00"
        workflow.save_plan(dir_a / "plan.json", plan_a)
        (self.repo / ".agents/state/active-task.json").unlink(missing_ok=True)

        # Save bridge 1 (follow-up A) and bridge 2 (follow-up B)
        out_1 = io.StringIO()
        with contextlib.redirect_stdout(out_1):
            self.assertEqual(0, workflow.main([
                "bridge", "--save", "--repo", str(self.repo),
                "--task-id", task_a,
                "--next-outcome", "Add biometric login",
                "--json",
            ]))
        b1 = json.loads(out_1.getvalue())

        out_2 = io.StringIO()
        with contextlib.redirect_stdout(out_2):
            self.assertEqual(0, workflow.main([
                "bridge", "--save", "--repo", str(self.repo),
                "--task-id", task_a,
                "--next-outcome", "Add dark mode toggle",
                "--json",
            ]))
        b2 = json.loads(out_2.getvalue())
        self.assertEqual(2, b2["pending_bridges_count"])
        self.assertNotEqual(b1["bridge_id"], b2["bridge_id"])

        # Reminder lists both waiting bridges
        rem = pending_bridge_reminder(self.repo)
        self.assertIn("2 waiting", rem)
        self.assertIn(b1["bridge_id"], rem)
        self.assertIn(b2["bridge_id"], rem)

        # Calling `task bridge` without --bridge-id returns MULTIPLE_BRIDGES_PENDING + SELECT_PENDING_BRIDGE
        ambig_out = io.StringIO()
        with contextlib.redirect_stdout(ambig_out):
            self.assertEqual(0, workflow.main(["bridge", "--repo", str(self.repo), "--json"]))
        ambig = json.loads(ambig_out.getvalue())
        self.assertEqual("MULTIPLE_BRIDGES_PENDING", ambig["status"])
        self.assertEqual(2, ambig["pending_bridges_count"])
        self.assertEqual("SELECT_PENDING_BRIDGE", ambig["next_action"]["code"])
        self.assertEqual("ask_question", ambig["next_action"]["tool"])

        # Calling `task bridge --task-id <same>` when 2 follow-up bridges share that task_id ALSO disambiguates
        ambig_tid_out = io.StringIO()
        with contextlib.redirect_stdout(ambig_tid_out):
            self.assertEqual(0, workflow.main(["bridge", "--repo", str(self.repo), "--task-id", task_a, "--json"]))
        ambig_tid = json.loads(ambig_tid_out.getvalue())
        self.assertEqual("MULTIPLE_BRIDGES_PENDING", ambig_tid["status"])
        self.assertEqual(2, ambig_tid["pending_bridges_count"])

        # Load bridge 1 specifically via --bridge-id -> consumes only b1, leaving b2 pending
        load_b1_out = io.StringIO()
        with contextlib.redirect_stdout(load_b1_out):
            self.assertEqual(0, workflow.main([
                "bridge", "--repo", str(self.repo),
                "--bridge-id", b1["bridge_id"],
                "--json",
            ]))
        loaded_b1 = json.loads(load_b1_out.getvalue())
        self.assertEqual("BRIDGE_LOADED", loaded_b1["status"])
        self.assertEqual("Add biometric login", loaded_b1["next_outcome"])

        # Now only 1 unconsumed bridge (b2) remains, so plain `task bridge` loads b2 directly without ambiguity!
        rem_after = pending_bridge_reminder(self.repo)
        self.assertIn(b2["bridge_id"], rem_after)
        self.assertNotIn("2 waiting", rem_after)

        load_b2_out = io.StringIO()
        with contextlib.redirect_stdout(load_b2_out):
            self.assertEqual(0, workflow.main(["bridge", "--repo", str(self.repo), "--json"]))
        loaded_b2 = json.loads(load_b2_out.getvalue())
        self.assertEqual("BRIDGE_LOADED", loaded_b2["status"])
        self.assertEqual("Add dark mode toggle", loaded_b2["next_outcome"])
        self.assertEqual("", pending_bridge_reminder(self.repo))


# Avoid running the parent suite again when this focused suite is discovered.
for _name in dir(phase_fixtures.PhaseReviewV2Selftest):
    if _name.startswith("test_") and _name not in HostContinuationTests.__dict__:
        setattr(HostContinuationTests, _name, None)

if __name__ == "__main__":
    unittest.main(verbosity=2)
