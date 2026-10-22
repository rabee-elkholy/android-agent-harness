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
            self.assertTrue((self.repo / ".agents/subagents/perf-anr-guardian-agent.json").is_file())
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


# Avoid running the parent suite again when this focused suite is discovered.
for _name in dir(phase_fixtures.PhaseReviewV2Selftest):
    if _name.startswith("test_") and _name not in HostContinuationTests.__dict__:
        setattr(HostContinuationTests, _name, None)

if __name__ == "__main__":
    unittest.main(verbosity=2)
