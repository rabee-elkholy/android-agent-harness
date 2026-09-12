"""Critical safety regressions using temporary repositories and simulated tools."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _vnext_selftest as fixtures
import change_classifier
import evidence_store
import final_verifier
import lifecycle
import mutation_guard
import record_review
import review_policy
import room_guard
import run_device
import run_gradle_task
import run_tests_gate
import skill_router
from _vnext_common import HarnessError, ValidationError, read_json, sha256_bytes


class CriticalSafetyTests(unittest.TestCase):
    def test_gradle_failure_attribution_rejects_other_failed_tasks(self):
        task = ":app:testDebugUnitTest"
        log = f"> Task {task} FAILED\n* What went wrong:\nExecution failed for task '{task}'.\n> There were failing tests. See the report at: fixture\n\n* Try:\nRun with --info\n"
        self.assertTrue(run_gradle_task.test_failure_only(task, log))
        self.assertFalse(run_gradle_task.test_failure_only(task, log + "\nExecution failed for task ':app:compileKotlin'.\n"))
        self.assertFalse(run_gradle_task.test_failure_only(task, log + "> Task :other:testDebugUnitTest FAILED\n"))
        self.assertFalse(run_gradle_task.test_failure_only(task, "BUILD FAILED"))
        self.assertFalse(run_gradle_task.test_failure_only(task, log + "\n* What went wrong:\nFailed to notify build listener.\n> Release output verification failed\n* Try:\n"))
        self.assertFalse(run_gradle_task.test_failure_only(task, "FAILURE: Build completed with 2 failures.\n" + log))

    def test_caller_answers_survive_failure_and_update_rollback(self):
        from argparse import Namespace
        cli = fixtures.harness_cli
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            answers = root / ".harness-setup/answers.json"
            answers.parent.mkdir()
            original = b'{"product":"Original"}\n'
            answers.write_bytes(original)
            stack.enter_context(mock.patch.object(cli, "find_repo", return_value=root))
            stack.enter_context(mock.patch.object(cli, "ensure_kit", return_value=fixtures.KIT))
            stack.enter_context(mock.patch.object(cli, "resolve_kit", return_value=fixtures.KIT))
            stack.enter_context(mock.patch.object(cli, "_verify_kit_checksums"))
            runner = stack.enter_context(mock.patch.object(cli, "run_engine_script", return_value=1))
            args = Namespace(repo=str(root), kit=str(fixtures.KIT), answers_json=str(answers), lang="en", no_refresh=True, force=False)
            self.assertEqual(1, cli.cmd_init(args))
            self.assertEqual(original, answers.read_bytes())
            for error in (False, True):
                def run(_kit, script, _args):
                    if script == "setup_wizard.py":
                        answers.write_bytes(b'{"product":"Changed"}\n')
                        return 0
                    if error:
                        raise OSError("simulated engine failure")
                    return 1
                runner.side_effect = run
                if error:
                    with self.assertRaises(OSError):
                        cli.cmd_update(args)
                else:
                    self.assertEqual(1, cli.cmd_update(args))
                self.assertEqual(original, answers.read_bytes())

    def test_final_verifier_rejects_mixed_device_evidence(self):
        digest = "a" * 64
        artifact = {"artifact_set_sha256": digest, "application_id": "com.example.debug"}
        assembled = {"status": "PASS", "evidence": {"artifact_set": artifact}}
        evidence = dict(artifact_set_sha256=digest, application_id="com.example.debug", serial_sha256="b" * 64, target_user="10", install_reference=digest)
        install = {"status": "PASS", "evidence": dict(evidence)}
        launch = {"status": "PASS", "evidence": dict(evidence)}
        self.assertEqual([], final_verifier.device_chain_errors(assembled, install, launch))
        for key in ("serial_sha256", "application_id", "target_user", "install_reference", "artifact_set_sha256"):
            launch["evidence"][key] = "other"
            self.assertTrue(final_verifier.device_chain_errors(assembled, install, launch), key)
            launch["evidence"][key] = evidence[key]

    def test_current_android_user_is_resolved_once_to_numeric_identity(self):
        import subprocess
        with mock.patch.object(run_device.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="10\n")) as adb:
            self.assertEqual("10", run_device.resolve_target_user("device", None))
            self.assertEqual("0", run_device.resolve_target_user("device", "0"))
            self.assertEqual(1, adb.call_count)
            for value in ("all", "-1", "garbage"):
                with self.assertRaises(HarnessError):
                    run_device.resolve_target_user("device", value)
    def test_exemptions_cannot_authorize_other_commands_or_writing_options(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for prefix in (
                "python .agents/scripts/workflow.py status",
                "python .agents/scripts/workflow.py begin --task-id t",
                f'python "{fixtures.KIT.as_posix()}/harness_cli.py" version',
            ):
                self.assertTrue(mutation_guard.command_allowed(repo, prefix)[0], prefix)
                for separator in ("; ", " && ", " || ", "\n", " & "):
                    command = prefix + separator + "python mutate.py"
                    self.assertFalse(mutation_guard.command_allowed(repo, command)[0], command)
            for command in (
                'python mutate.py "workflow.py status"',
                "python fake_workflow.py status", "python innocent.py --help",
                "workflow status", "harness_cli doctor",
                "python .agents/scripts/../../workflow.py status",
                "python /untrusted/agents/scripts/workflow.py status",
                "sed -i s/a/b/ app.kt", "sed 'w output.txt' app.kt",
                "git diff --output=out.txt", "git log --output out.txt",
                "git symbolic-ref HEAD refs/heads/other", "rg --pre mutate.py needle",
            ):
                self.assertFalse(mutation_guard.command_allowed(repo, command)[0], command)
            for command in ("git status && git diff --stat", "rg -n needle app.kt", "python .agents/scripts/workflow.py --help"):
                self.assertTrue(mutation_guard.command_allowed(repo, command)[0], command)

    def test_verification_and_resume_exemptions_are_segment_scoped(self):
        with mock.patch.object(mutation_guard, "active_plan", return_value={"status": "VERIFYING"}):
            for command in ("python .agents/scripts/run_tests_gate.py", "python .agents/scripts/workflow.py resume"):
                self.assertTrue(mutation_guard.command_allowed(Path('.'), command)[0])
                self.assertFalse(mutation_guard.command_allowed(Path('.'), command + "; python mutate.py")[0])
            self.assertFalse(mutation_guard.command_allowed(Path('.'), 'python mutate.py "run_tests_gate.py"')[0])
            self.assertFalse(mutation_guard.command_allowed(Path('.'), "run_tests_gate arbitrary")[0])

    def test_raw_review_contradiction_never_becomes_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "runs/s/run/review-package.md"
            package.parent.mkdir(parents=True)
            package.write_text("fixture", encoding="utf-8")
            response = root / "response.txt"
            current = {"manifest": str(root / "manifest.json"), "run_id": "run"}
            manifest = {"delivery_snapshot_sha256": "s", "change_set_sha256": "c"}
            (root / "current-run.json").write_text(json.dumps(current))
            (root / "manifest.json").write_text(json.dumps(manifest))
            footer = "EVIDENCE pkg=" + record_review.sha256_file(package)[:12]
            with mock.patch.object(record_review, "task_dir", return_value=root), mock.patch.object(record_review, "state_root", return_value=root):
                for body in ("MAJOR: unresolved data loss.\nBUG_PASS", "BUG_PASS\nBUG_PASS", "unresolved issue\nBUG_PASS"):
                    response.write_text(body + "\n" + footer + " cites=0")
                    try:
                        report = record_review.response_to_report(root, "t", "bug-reviewer-agent", response)
                    except ValidationError:
                        continue
                    self.assertNotEqual("PASS", report["verdict"])
                response.write_text("\n\nBUG_PASS\n" + footer + " cites=0\n")
                self.assertEqual("PASS", record_review.response_to_report(root, "t", "bug-reviewer-agent", response)["verdict"])

    def test_failed_gradle_needs_fresh_failures_from_the_test_task(self):
        xml = '<testsuite tests="1" failures="1"><testcase classname="A" name="a"><failure message="known"/></testcase></testsuite>'
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            folder = repo / "app/build/test-results/testDebugUnitTest"
            folder.mkdir(parents=True)
            old = folder / "old.xml"
            old.write_text(xml)
            baseline = {"unit_tests": run_tests_gate.collect_task_failures(repo, ":app:testDebugUnitTest")}
            for fresh_failure, only_test_failure in ((False, True), (True, False), (True, True)):
                with self.subTest(fresh_failure=fresh_failure, only_test_failure=only_test_failure):
                    def gradle(_args, **kwargs):
                        target = old if fresh_failure else folder / "pass.xml"
                        target.write_text(xml + "\n" if fresh_failure else '<testsuite tests="1" failures="0"><testcase name="b"/></testsuite>')
                        stat = target.stat()
                        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10000000))
                        if kwargs.get("outcome") is not None:
                            kwargs["outcome"].update(test_failure_only=only_test_failure)
                        return 1
                    with mock.patch.object(run_tests_gate, "REPO", repo), mock.patch.object(run_tests_gate, "load_baseline", return_value=baseline), mock.patch.object(run_tests_gate, "write_gate_result"), mock.patch.object(run_tests_gate, "current_head_sha", return_value=""), mock.patch.object(run_gradle_task, "run_gradle", side_effect=gradle):
                        code = run_tests_gate.main([":app:testDebugUnitTest"])
                    self.assertEqual(0 if fresh_failure and only_test_failure else 1, code)

    def test_update_preserves_history_and_rejects_active_task(self):
        fixture = fixtures.LifecycleTests()
        fixture.setUp()
        try:
            fixture._answers()
            lifecycle.install(fixture.repo, fixtures.KIT)
            state = fixture.repo / ".agents/state"
            history = state / "runs/old/evidence.json"
            history.parent.mkdir(parents=True)
            history.write_bytes(b'{"history":true}\n')
            active = state / "active-task.json"
            active.write_text('{"task_id":"active"}')
            with self.assertRaisesRegex(ValidationError, "active"):
                lifecycle.update(fixture.repo, fixtures.KIT)
            self.assertTrue(active.is_file())
            self.assertEqual(b'{"history":true}\n', history.read_bytes())
            plan_path = state / "tasks/active/plan.json"
            plan_path.parent.mkdir(parents=True)
            active.write_text(json.dumps({"task_id": "active", "plan_path": str(plan_path)}))
            for terminal in ("CANCELLED", "DELIVERED"):
                plan_path.write_text(json.dumps({"task_id": "active", "status": terminal}))
                before = {p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()}
                lifecycle.update(fixture.repo, fixtures.KIT)
                self.assertEqual(before, {p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()})
            active.unlink()
            lifecycle.update(fixture.repo, fixtures.KIT)
            self.assertEqual(b'{"history":true}\n', history.read_bytes())
        finally:
            fixture.tearDown()

    def test_update_idle_guard_fails_closed_for_uncertain_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / ".agents/state"
            state.mkdir(parents=True)
            pointer = state / "active-task.json"
            plan = state / "plan.json"
            for status in ("IMPLEMENTING", "VERIFYING", "BLOCKED", "AWAITING_DEVELOPER_APPROVAL", "UNKNOWN"):
                pointer.write_text(json.dumps({"task_id": "t", "plan_path": str(plan)}))
                plan.write_text(json.dumps({"task_id": "t", "status": status}))
                with self.assertRaises(ValidationError):
                    lifecycle.require_update_idle(root)
            for reference, content in ((str(plan), '{bad'), (str(plan), '{"task_id":"other","status":"CANCELLED"}'), (str(root / "outside.json"), '{"task_id":"t","status":"CANCELLED"}')):
                pointer.write_text(json.dumps({"task_id": "t", "plan_path": reference}))
                Path(reference).write_text(content)
                with self.assertRaises(ValidationError):
                    lifecycle.require_update_idle(root)
            pointer.write_text(json.dumps({"task_id": "t", "plan_path": str(state / "missing.json")}))
            with self.assertRaises(ValidationError):
                lifecycle.require_update_idle(root)

    def test_removed_historical_migration_is_rejected(self):
        fixture = fixtures.RepoCase()
        fixture.setUp()
        try:
            root = fixture.repo
            db = root / "app/src/main/kotlin/AppDatabase.kt"
            provider = db.with_name("DatabaseModule.kt")
            fixtures.write(db, '@Database(entities = [], version = 2)\nabstract class AppDatabase : RoomDatabase()\n')
            builder = 'Room.databaseBuilder(context, AppDatabase::class.java, "app.db")'
            original = 'val upgrade = object : Migration(1, 2) {}\nfun db() = ' + builder + '.addMigrations(upgrade).build()\n'
            fixtures.write(provider, original)
            fixtures.run_git(root, "add", ".")
            fixtures.run_git(root, "commit", "-qm", "Historical migration fixture")
            fixtures.write(provider, 'fun db() = ' + builder + '.build()\n')
            self.assertFalse(room_guard.check_room_working_tree(repo=root)[0])
            fixtures.write(provider, original + "// Safe comment\n")
            self.assertTrue(room_guard.check_room_working_tree(repo=root)[0])
            provider.unlink()
            self.assertFalse(room_guard.check_room_working_tree(repo=root)[0])
        finally:
            fixture.tearDown()

    def test_device_launch_uses_exact_install_identity(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            apk = root / "app.apk"
            apk.write_bytes(b"apk")
            artifact = {"artifact_set_sha256": "a" * 64, "application_id": "com.example.debug"}
            manifest = {key: key for key in ("delivery_snapshot_sha256", "change_set_sha256", "external_inputs_sha256")}
            install = dict(manifest, status="PASS", artifact_set_sha256=artifact["artifact_set_sha256"], application_id=artifact["application_id"], target_user="10", serial_sha256=sha256_bytes(b"device"))
            assemble = dict(manifest, status="PASS", artifact_set=artifact)
            stack.enter_context(mock.patch.object(run_device, "REPO", root))
            stack.enter_context(mock.patch.object(run_device, "_check_device_prerequisites", return_value=None))
            stack.enter_context(mock.patch.object(run_device, "require_serial", return_value="device"))
            stack.enter_context(mock.patch.object(run_device, "resolve_or_raise", return_value=(None, ":app:assembleDebug")))
            stack.enter_context(mock.patch.object(run_device, "verify_artifact_set", return_value=[apk]))
            stack.enter_context(mock.patch.object(run_device, "build_manifest", return_value=manifest))
            stack.enter_context(mock.patch.object(run_device, "DEFAULT_ACTIVITY", "com.example/com.example.MainActivity"))
            stack.enter_context(mock.patch.object(run_device, "APPLICATION_ID", "com.example"))
            stack.enter_context(mock.patch.object(run_device, "read_gate_result", side_effect=lambda name: install if name == "device_install" else assemble))
            record = stack.enter_context(mock.patch.object(run_device, "record_device"))
            adb = stack.enter_context(mock.patch.object(run_device, "run_adb", return_value=(0, "Success")))
            stack.enter_context(mock.patch.object(sys, "argv", ["run_device.py", "start", "--user", "10"]))
            self.assertEqual(0, run_device.main())
            self.assertIn("com.example.debug/com.example.MainActivity", adb.call_args.args[1])
            self.assertEqual(["--user", "10"], adb.call_args.args[1][3:5])
            self.assertEqual("com.example.debug", record.call_args.kwargs["application_id"])
            for key, bad in (("status", "EMERGENCY_UNVERIFIED"), ("serial_sha256", "other"), ("target_user", "0"), ("application_id", "com.other"), ("change_set_sha256", "stale")):
                saved = install[key]
                install[key] = bad
                adb.reset_mock()
                self.assertNotEqual(0, run_device.main(), key)
                adb.assert_not_called()
                install[key] = saved
            # Combined installation pins the current profile once and uses the
            # original activity class even when the application id has a suffix.
            import subprocess
            with mock.patch.object(sys, "argv", ["run_device.py", "install-start"]), mock.patch.object(run_device, "DEFAULT_ACTIVITY", "com.example/.MainActivity"), mock.patch.object(run_device.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="10\n")) as probe:
                adb.reset_mock()
                self.assertEqual(0, run_device.main())
                commands = [call.args[1] for call in adb.call_args_list]
                self.assertEqual("install", commands[0][0])
                self.assertEqual(["--user", "10"], commands[0][2:4])
                self.assertEqual(["shell", "am", "start", "--user", "10", "-n", "com.example.debug/com.example.MainActivity"], commands[1])
                self.assertEqual(1, sum("get-current-user" in call.args[0] for call in probe.call_args_list))

    def test_unclassified_delivery_file_not_masked_by_docs(self):
        fixture = fixtures.RepoCase()
        fixture.setUp()
        try:
            root = fixture.repo
            fixtures.write(root / "app/src/main/assets/notes.md", "Documentation notes\n")
            fixtures.run_git(root, "add", ".")
            fixtures.run_git(root, "commit", "-qm", "baseline doc")

            # 1. Modifying notes.md and an unclassified delivery config.json
            fixtures.write(root / "app/src/main/assets/notes.md", "Updated notes\n")
            fixtures.write(root / "app/src/main/assets/config.json", '{"theme": "dark"}\n')
            result = change_classifier.classify(root)
            self.assertIn("DOCS", result["surfaces"])
            self.assertIn("UNKNOWN", result["surfaces"])
            self.assertEqual("LOW", result["confidence"])

            # 2. Positive neighboring case: modifying only notes.md stays pure DOCS
            (root / "app/src/main/assets/config.json").unlink()
            clean_result = change_classifier.classify(root)
            self.assertEqual(["DOCS"], clean_result["surfaces"])
            self.assertEqual("HIGH", clean_result["confidence"])
        finally:
            fixture.tearDown()

    def test_embedded_room_type_triggers_room_schema_and_gate(self):
        fixture = fixtures.RepoCase()
        fixture.setUp()
        try:
            root = fixture.repo
            fixtures.write(root / "app/src/main/kotlin/AppDatabase.kt",
                "@Database(entities = [User::class], version = 1)\n"
                "abstract class AppDatabase : RoomDatabase()\n")
            fixtures.write(root / "app/src/main/kotlin/User.kt",
                "@Entity\n"
                "data class User(\n"
                "    val id: String,\n"
                "    @Embedded val address: Address\n"
                ")\n")
            fixtures.write(root / "app/src/main/kotlin/Address.kt",
                "data class Address(\n"
                "    val street: String,\n"
                "    val city: String\n"
                ")\n")
            fixtures.write(root / "app/src/main/kotlin/Unrelated.kt",
                "data class Unrelated(val count: Int)\n")
            fixtures.run_git(root, "add", ".")
            fixtures.run_git(root, "commit", "-qm", "baseline schema")

            # 1. Modifying embedded type Address.kt triggers ROOM_SCHEMA
            fixtures.write(root / "app/src/main/kotlin/Address.kt",
                "data class Address(\n"
                "    val street: String,\n"
                "    val city: String,\n"
                "    val postcode: String\n"
                ")\n")
            result = change_classifier.classify(root)
            self.assertIn("ROOM_SCHEMA", result["surfaces"])
            policy = review_policy.decide(result, fixtures.KIT / "agents/skills")
            self.assertIn("room", policy["gates"])

            # 2. Positive neighboring case: modifying Unrelated.kt does not trigger ROOM_SCHEMA
            fixtures.write(root / "app/src/main/kotlin/Address.kt",
                "data class Address(\n"
                "    val street: String,\n"
                "    val city: String\n"
                ")\n")
            fixtures.write(root / "app/src/main/kotlin/Unrelated.kt",
                "data class Unrelated(val count: Int, val name: String)\n")
            unrelated_result = change_classifier.classify(root)
            self.assertNotIn("ROOM_SCHEMA", unrelated_result["surfaces"])
            unrelated_policy = review_policy.decide(unrelated_result, fixtures.KIT / "agents/skills")
            self.assertNotIn("room", unrelated_policy["gates"])
        finally:
            fixture.tearDown()

    def test_runtime_integrity_rejects_empty_inventory_and_missing_checksums(self):
        cli = fixtures.harness_cli
        with tempfile.TemporaryDirectory() as directory:
            kit = Path(directory)
            agents = kit / "agents"
            agents.mkdir(parents=True)
            checksum_path = agents / "release_checksums.json"

            # 1. CLI verifier rejects empty files dict
            checksum_path.write_text('{"schema_version": 1, "algorithm": "sha256", "files": {}}', encoding="utf-8")
            with self.assertRaises(SystemExit):
                cli._verify_kit_checksums(kit)

            # 2. CLI verifier rejects missing core files
            checksum_path.write_text('{"schema_version": 1, "algorithm": "sha256", "files": {"agents/dummy": "aaa"}}', encoding="utf-8")
            with self.assertRaises(SystemExit):
                cli._verify_kit_checksums(kit)

            # 3. Lifecycle verifier rejects missing release_checksums.json
            checksum_path.unlink()
            (agents / "scripts").mkdir()
            (agents / "scripts/lifecycle.py").write_text("# lifecycle\n")
            (agents / "VERSION").write_text("1.0.18\n")
            with self.assertRaisesRegex(ValidationError, "missing or symlink"):
                lifecycle._validate_kit(kit)

            # 4. Lifecycle verifier rejects empty files inventory
            checksum_path.write_text('{"schema_version": 1, "algorithm": "sha256", "files": {}}', encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "empty or malformed"):
                lifecycle._validate_kit(kit)

            # 5. Positive neighboring case: valid kit passes both verifiers
            self.assertEqual(0, cli._verify_kit_checksums(fixtures.KIT) or 0)
            valid_root, ver = lifecycle._validate_kit(fixtures.KIT)
            self.assertEqual(fixtures.KIT.resolve(), valid_root)

    def test_malformed_skill_metadata_blocks_routing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "test-driven-development"
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"

            # 1. Invalid version format
            skill_file.write_text("---\nversion: invalid\nkernel-major: 1\n---\n")
            res = skill_router.route(root, ["TEST_ONLY"])
            self.assertEqual("BLOCKED", res["status"])
            self.assertTrue(any("invalid version" in e for e in res["errors"]))

            # 2. Invalid kernel-major
            skill_file.write_text("---\nversion: 1.0.0\nkernel-major: nonsense\n---\n")
            res = skill_router.route(root, ["TEST_ONLY"])
            self.assertEqual("BLOCKED", res["status"])
            self.assertTrue(any("invalid kernel-major" in e for e in res["errors"]))

            # 3. Missing version
            skill_file.write_text("---\nkernel-major: 1\n---\n")
            res = skill_router.route(root, ["TEST_ONLY"])
            self.assertEqual("BLOCKED", res["status"])
            self.assertTrue(any("missing required 'version'" in e for e in res["errors"]))

            # 4. Positive neighboring case: valid frontmatter passes
            skill_file.write_text("---\nversion: 1.0.0\nkernel-major: 1\n---\n")
            res = skill_router.route(root, ["TEST_ONLY"])
            self.assertEqual("PASS", res["status"])
            self.assertEqual([], res["errors"])

            # 5. Positive neighboring case: semver pre-release passes
            skill_file.write_text("---\nversion: 1.2.0-rc.1\nkernel-major: 1\n---\n")
            res = skill_router.route(root, ["TEST_ONLY"])
            self.assertEqual("PASS", res["status"])
            self.assertEqual([], res["errors"])

    def test_branch_switch_invalidates_final_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            plan = repo / "plan.json"
            policy = repo / "policy.json"
            manifest = repo / "manifest.json"
            state = repo / "state"
            state.mkdir()

            rec_manifest = {
                "delivery_snapshot_sha256": "h",
                "change_set_sha256": "h",
                "external_inputs_sha256": "h",
                "files": [],
                "changes": [],
                "external_inputs": [],
                "repository": {
                    "root_sha256": "r1",
                    "git_common_dir_sha256": "c1",
                    "head": "h1",
                    "branch": "feature/branch",
                },
            }
            manifest.write_text(json.dumps(rec_manifest))

            cur_manifest = dict(rec_manifest)
            cur_manifest["repository"] = dict(rec_manifest["repository"], branch="main")

            plan_data = {
                "plan_sha256": "p", "execution_nonce": "n", "status": "VERIFYING",
                "approval": {"plan_sha256": "p", "single_use_nonce": "n", "source": "conversation", "enforcement_tier": "RULE_ENFORCED", "proof_reference_sha256": "0" * 64}
            }
            def read_mock(path):
                if path == manifest:
                    return rec_manifest
                if path == plan:
                    return plan_data
                return {}

            with mock.patch.object(final_verifier, "read_json", side_effect=read_mock), \
                 mock.patch.object(final_verifier, "canonical_sha256", side_effect=lambda v: "h" if isinstance(v, list) else "p"), \
                 mock.patch.object(final_verifier, "plan_payload", return_value={}), \
                 mock.patch.object(final_verifier, "build_manifest", return_value=cur_manifest):
                res = final_verifier.verify(repo, plan_path=plan, policy_path=policy, manifest_path=manifest, state_root=state, run_id="r")
                self.assertEqual("STALE", res["status"])
                self.assertTrue(any("branch" in reason for reason in res["blocked_by"]))

    def test_stale_lock_recovery_cannot_delete_replacement_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = evidence_store.StateLock(root)
            lock.path.parent.mkdir(parents=True, exist_ok=True)

            stale_payload = {"pid": 999999, "process_marker": "dead", "nonce": "stale-nonce", "created_at": "now"}
            live_payload = {"pid": os.getpid(), "process_marker": evidence_store._process_marker(os.getpid()), "nonce": "live-nonce", "created_at": "now"}

            # Simulate another process replacing the stale lock with live lock
            lock.path.write_text(json.dumps(live_payload))

            # Writer A attempting stale recovery for 'stale-nonce' must NOT unlink the live lock
            removed = lock._try_remove_stale_lock(stale_payload)
            self.assertFalse(removed)
            self.assertTrue(lock.path.exists())
            self.assertEqual("live-nonce", read_json(lock.path)["nonce"])

            # Releasing with mismatched nonce must not unlink the live lock
            lock.acquired = True
            lock.nonce = "other-nonce"
            lock.__exit__(None, None, None)
            self.assertTrue(lock.path.exists())

            # Stale recovery for matching stale payload unlinks cleanly
            lock.path.write_text(json.dumps(stale_payload))
            self.assertTrue(lock._try_remove_stale_lock(stale_payload))
            self.assertFalse(lock.path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
