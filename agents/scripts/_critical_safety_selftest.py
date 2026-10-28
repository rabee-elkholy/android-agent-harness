"""Critical safety regressions using temporary repositories and simulated tools."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import shutil
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
    def test_review_round_extension_requires_a_current_valid_round_decision(self):
        from review_budget import effective_review_budget, effective_review_round_limit
        from _vnext_common import atomic_write_json, canonical_sha256
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            path = repo / ".agents/state/tasks/task/review-budget.json"
            plan = {"task_id": "task", "plan_sha256": "plan", "repository": {"branch": "main"}}
            legacy = {"schema_version": 1, "task_id": "task", "plan_sha256": "plan",
                "repository": plan["repository"], "limit": 70, "source": "conversation",
                "enforcement_tier": "RULE_ENFORCED", "proof_reference_sha256": "a" * 64}
            def save(record):
                record = dict(record)
                record["decision_sha256"] = canonical_sha256(record)
                atomic_write_json(path, record)
            save(legacy)
            self.assertEqual(70, effective_review_budget(repo, plan))
            self.assertEqual(3, effective_review_round_limit(repo, plan))
            save({**legacy, "round_limit": 100})
            self.assertEqual(3, effective_review_round_limit(repo, plan), "Schema-1 call approval never grants rounds")
            approved = {**legacy, "schema_version": 2, "round_limit": 4}
            save(approved)
            self.assertEqual(4, effective_review_round_limit(repo, plan))
            self.assertEqual(3, effective_review_round_limit(repo, {**plan, "plan_sha256": "revised"}))
            for value in (True, 0, 101, "4"):
                save({**approved, "round_limit": value})
                with self.subTest(value=value), self.assertRaises(ValidationError):
                    effective_review_round_limit(repo, plan)

    def test_engine_inspection_is_exact_bounded_and_read_only(self):
        import harness_doctor
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            scripts = repo / ".agents/scripts"
            scripts.mkdir(parents=True)
            source = scripts / "engine.py"
            source.write_text("\n".join(f"# line {index}" for index in range(300)), encoding="utf-8")
            before = source.read_bytes()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = harness_doctor.main(["--repo", str(repo), "--inspect-file", "scripts/engine.py",
                    "--inspection-reason", "unexpected_failure", "--reference", "documented command failed",
                    "--inspect-start-line", "20", "--inspect-lines", "2"])
            self.assertEqual(0, code)
            data = json.loads(output.getvalue())
            self.assertEqual(["20: # line 19", "21: # line 20"], data["lines"])
            self.assertEqual(before, source.read_bytes())
            self.assertFalse((repo / ".agents/state").exists())
            for path in ("../outside.py", "scripts", "scripts/*.py"):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    harness_doctor.main(["--repo", str(repo), "--inspect-file", path,
                        "--inspection-reason", "developer_request", "--reference", "inspect exact source"])
            base = ["--repo", str(repo), "--inspect-file", "scripts/engine.py"]
            for extra in ([], ["--inspection-reason", "developer_request"],
                          ["--inspection-reason", "unexpected_failure", "--reference", " "]):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    harness_doctor.main(base + extra)
            reason = ["--inspection-reason", "developer_request", "--reference", "exact source inspection"]
            for extra in (["--inspect-lines", "201"], ["--inspect-lines", "0"],
                          ["--inspect-start-line", "0"], ["--inspect-start-line", "301"]):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    harness_doctor.main(base + reason + extra)

    def test_scope_denial_hints_do_not_rescan_the_plan_for_file_only_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "Source.kt").write_text("class Source")
            classify = mock.Mock(return_value={"surfaces": ["BUSINESS_LOGIC"]})
            plan = {"task_id": "task", "expected_files": ["Source.kt"], "expected_modules": [":app"]}
            hint = mutation_guard._all_missing_surfaces_hint(
                repo, plan, "pack/build.gradle", ["file:pack/build.gradle", "module::pack"],
                classify, mock.Mock(return_value=[]))
            classify.assert_not_called()
            self.assertIn("pack/build.gradle", hint)

    def test_surface_denial_hints_batch_classification_and_preserve_sensitive_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            files = [f"Source{index}.kt" for index in range(40)]
            for name in files:
                (repo / name).write_text("class Source")
            plan = {"task_id": "task", "expected_files": files, "expected_surfaces": ["BUSINESS_LOGIC"]}
            classifier = mock.Mock(return_value={"surfaces": ["AUTH", "COMPOSE_UI"]})
            def drift(_plan, surfaces):
                return ["surface:" + surface for surface in surfaces if surface not in plan["expected_surfaces"]]
            with mock.patch.object(mutation_guard, "_is_tracked", side_effect=lambda _root, path: path in files[:20]):
                hint = mutation_guard._all_missing_surfaces_hint(
                    repo, plan, "Other.kt", ["surface:XML_UI"], classifier, drift)
            self.assertLessEqual(classifier.call_count, 2)
            self.assertIn("AUTH", hint)
            self.assertIn("COMPOSE_UI", hint)
            self.assertIn("XML_UI", hint)

    def test_windows_unix_wrapper_prefers_git_shell_over_wsl_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git = root / "Git" / "cmd" / "git.exe"
            git_bash = root / "Git" / "bin" / "bash.exe"
            wrapper = root / "repo" / "gradlew"
            for path in (git, git_bash, wrapper):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"#!/bin/sh\nexit 0\n")

            def which(name: str):
                return {
                    "git": str(git),
                    "bash": r"C:\Users\runneradmin\AppData\Local\Microsoft\WindowsApps\bash.exe",
                    "sh": None,
                }.get(name)

            with mock.patch.object(run_gradle_task.sys, "platform", "win32"), \
                 mock.patch.object(run_gradle_task.shutil, "which", side_effect=which):
                command = run_gradle_task.unix_wrapper_cmd(wrapper, [":app:compileDebugKotlin"])
            self.assertEqual(str(git_bash), command[0])
            self.assertEqual("./gradlew", command[1])

    def test_gradle_failure_attribution_rejects_other_failed_tasks(self):
        task = ":app:testDebugUnitTest"
        log = f"> Task {task} FAILED\n* What went wrong:\nExecution failed for task '{task}'.\n> There were failing tests. See the report at: fixture\n\n* Try:\nRun with --info\n"
        self.assertTrue(run_gradle_task.test_failure_only(task, log))
        self.assertFalse(run_gradle_task.test_failure_only(task, log + "\nExecution failed for task ':app:compileKotlin'.\n"))
        self.assertFalse(run_gradle_task.test_failure_only(task, log + "> Task :other:testDebugUnitTest FAILED\n"))
        self.assertFalse(run_gradle_task.test_failure_only(task, "BUILD FAILED"))
        self.assertFalse(run_gradle_task.test_failure_only(task, log + "\n* What went wrong:\nFailed to notify build listener.\n> Release output verification failed\n* Try:\n"))
        self.assertFalse(run_gradle_task.test_failure_only(task, "FAILURE: Build completed with 2 failures.\n" + log))

    def test_gradle_9_test_failure_without_try_section_is_attributed(self):
        # Round 5: Gradle 9.7 prints no '* Try:' after a test failure, so the section ran to the end
        # of the log and --capture-red could never record RED evidence.
        task = ":modules:services:utils:testDebugUnitTest"
        log = (
            f"> Task {task} FAILED\n\nFAILURE: Build failed with an exception.\n\n* What went wrong:\n"
            f"Execution failed for task '{task}'.\n"
            "> There were failing tests. See the report at: file:///repo/build/reports/tests/index.html\n\n"
            "BUILD FAILED in 5s\n62 actionable tasks: 1 executed, 61 up-to-date\nConfiguration cache entry reused.\n"
        )
        self.assertTrue(run_gradle_task.test_failure_only(task, log))
        self.assertFalse(run_gradle_task.test_failure_only(":app:testDebugUnitTest", log))

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

    def test_red_evidence_survives_a_revision_of_the_plan_it_was_captured_under(self):
        # Real app: a BUG task captured RED under plan r2, the developer re-approved r3 to add the missing
        # half, and `complete` refused forever ("RED defect evidence is bound to a different plan hash");
        # the agent then offered to edit the evidence file.
        from plan_authority import plan_payload
        from _vnext_common import canonical_sha256

        def plan(n: int, supersedes: str | None, approved: bool, task: str = "t1") -> dict:
            record = {"task_id": task, "task_kind": "BUG", "requested_outcome": f"fix r{n}", "expected_files": [f"A{n}.kt"]}
            if supersedes:
                record["supersedes_plan_sha256"] = supersedes
            record["plan_sha256"] = canonical_sha256(plan_payload(record))
            if approved:
                record["approval"] = {"plan_sha256": record["plan_sha256"]}
            return record

        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory)
            (task_dir / "plan-history").mkdir()
            draft = plan(1, None, False)
            r2 = plan(2, draft["plan_sha256"], True)
            r3 = plan(3, r2["plan_sha256"], True)
            for archived in (draft, r2):
                (task_dir / "plan-history" / f"{archived['plan_sha256']}.json").write_text(json.dumps(archived), encoding="utf-8")
            accepted = final_verifier.red_plan_hashes(task_dir, r3, r3["plan_sha256"])
            self.assertEqual({r3["plan_sha256"], r2["plan_sha256"]}, accepted, "an unapproved draft never binds RED")
            # A history file rewritten after archiving breaks the chain instead of extending it.
            forged = dict(r2, requested_outcome="something else")
            (task_dir / "plan-history" / f"{r2['plan_sha256']}.json").write_text(json.dumps(forged), encoding="utf-8")
            self.assertEqual({r3["plan_sha256"]}, final_verifier.red_plan_hashes(task_dir, r3, r3["plan_sha256"]))
            # Another task's plan is never an ancestor.
            other = plan(2, None, True, task="t2")
            (task_dir / "plan-history" / f"{other['plan_sha256']}.json").write_text(json.dumps(other), encoding="utf-8")
            r3_other = plan(3, other["plan_sha256"], True)
            self.assertEqual({r3_other["plan_sha256"]}, final_verifier.red_plan_hashes(task_dir, r3_other, r3_other["plan_sha256"]))

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
                "git grep -O mutate.sh needle", "git grep -nOmutate.sh needle",
                "git grep --open-files-in-pager=mutate.sh needle",
                "Set-Content app.kt x", "Get-Content app.kt | Set-Content b.kt", "Get-ChildItem $(Remove-Item app.kt)",
                "python .agents/harness.py graph --find X --out graph.json",
            ):
                self.assertFalse(mutation_guard.command_allowed(repo, command)[0], command)
            for command in (
                "git status && git diff --stat", "rg -n needle app.kt", "python .agents/scripts/workflow.py --help",
                'git grep -n "calculateDaysRemaining"', "git blame -L 1,20 app.kt",
                "Get-ChildItem -Path app\\src\\main", "Get-Content app\\build.gradle", "Select-String -Path app.kt -Pattern needle",
                "python .agents/harness.py graph --find MVIViewModel --json",
            ):
                self.assertTrue(mutation_guard.command_allowed(repo, command)[0], command)

    def test_quoted_separator_does_not_split_a_command(self):
        # Round 4: a developer reason containing ';' split a routed device command in two.
        with mock.patch.object(mutation_guard, "active_plan", return_value={"status": "VERIFYING"}):
            quoted = ('python .agents/harness.py device skip-validation --task-id t --source conversation '
                      '--proof-reference "not reachable from navigation; build and tests cover it"')
            self.assertTrue(mutation_guard.command_allowed(Path('.'), quoted)[0])
            self.assertTrue(mutation_guard.command_allowed(Path('.'), quoted.replace('"', "'"))[0])
            for command in (
                'python .agents/harness.py device skip-validation --proof-reference "x"; python mutate.py',
                'python .agents/harness.py device skip-validation --proof-reference "x" && python mutate.py',
                'python .agents/harness.py device skip-validation --proof-reference "unterminated; python mutate.py',
            ):
                self.assertFalse(mutation_guard.command_allowed(Path('.'), command)[0], command)

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

    def test_changed_modules_scope_targets_every_changed_module(self):
        # Round 5 (D8): a change in two modules fell back to :app tests and the changed test never ran.
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            changed = [repo / "modules/a/src/main/A.kt", repo / "modules/b/src/test/BTest.kt"]
            import _product
            import _repo_files
            with mock.patch.object(_repo_files, "changed_paths", return_value=changed), mock.patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"):
                with mock.patch.object(_product, "UNIT_TEST_SCOPE", "legacy", create=True):
                    self.assertEqual([":app:testDebugUnitTest"], run_tests_gate.resolve_target_tasks(repo, None))
                with mock.patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True):
                    self.assertEqual([":modules:a:testDebugUnitTest", ":modules:b:testDebugUnitTest"], run_tests_gate.resolve_target_tasks(repo, None))
                    self.assertEqual([":x:test"], run_tests_gate.resolve_target_tasks(repo, ":x:test"))
                with mock.patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), mock.patch.object(_repo_files, "changed_paths", return_value=[*changed, repo / "app/src/main/M.kt"]):
                    self.assertEqual([":app:testDebugUnitTest", ":modules:a:testDebugUnitTest", ":modules:b:testDebugUnitTest"], run_tests_gate.resolve_target_tasks(repo, None))

    def test_multi_module_run_executes_each_module_and_blocks_new_failure(self):
        passing = '<testsuite tests="1" failures="0"><testcase classname="A" name="a"/></testsuite>'
        failing = '<testsuite tests="1" failures="1"><testcase classname="B" name="b"><failure message="new"/></testcase></testsuite>'
        tasks = [":modules:a:testDebugUnitTest", ":modules:b:testDebugUnitTest"]
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ran: list[str] = []

            def gradle(args, **kwargs):
                ran.extend(args)
                module = args[0].split(":")[2]
                folder = repo / "modules" / module / "build/test-results/testDebugUnitTest"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "r.xml").write_text(passing if module == "a" else failing)
                if module == "b":
                    kwargs["outcome"].update(test_failure_only=True)
                    return 1
                return 0
            written: dict = {}
            with mock.patch.object(run_tests_gate, "REPO", repo), mock.patch.object(run_tests_gate, "resolve_target_tasks", return_value=tasks), \
                    mock.patch.object(run_tests_gate, "load_baseline", return_value={"unit_tests": []}), \
                    mock.patch.object(run_tests_gate, "write_gate_result", side_effect=lambda name, data: written.update(data)), \
                    mock.patch.object(run_tests_gate, "current_head_sha", return_value=""), mock.patch.object(run_gradle_task, "run_gradle", side_effect=gradle):
                code = run_tests_gate.main([])
            self.assertEqual(tasks, ran)
            self.assertNotEqual(0, code)
            self.assertEqual(["B#b"], written.get("new_regressions"))
            self.assertEqual(2, written.get("executed"))

    def test_repo_glob_matches_path_glob_without_entering_git(self):
        # Recursive Path.glob over the repository walked `.git`, where background object packing can
        # remove directories mid-walk (FileNotFoundError on Python 3.10). repo_glob returns what
        # Path.glob returns for the working tree and never lists `.git`.
        from _repo_files import repo_glob
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            for rel in ("AndroidManifest.xml", "app/src/main/AndroidManifest.xml", "lib/src/debug/AndroidManifest.xml",
                        ".git/modules/x/AndroidManifest.xml", "app/src/main/res/values/strings.xml",
                        "app/build/test-results/testDebugUnitTest/TEST-a.xml"):
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text("x", encoding="utf-8")
            for pattern in ("**/AndroidManifest.xml", "**/src/*/res", "**/build/test-results/**/TEST-*.xml", "**/res/values*"):
                with self.subTest(pattern=pattern):
                    expected = [p for p in repo.glob(pattern) if ".git" not in p.relative_to(repo).parts]
                    # Path.glob's order differs between Python versions; the set of results is the contract.
                    self.assertEqual(sorted(expected), sorted(repo_glob(repo, pattern)))
            real_scandir = os.scandir

            def no_git(path="."):
                if ".git" in Path(str(path)).parts:
                    raise FileNotFoundError(2, "vanished", str(path))
                return real_scandir(path)

            with mock.patch("os.scandir", side_effect=no_git):
                self.assertEqual(3, len(list(repo_glob(repo, "**/AndroidManifest.xml"))))

    def test_doctor_repository_scan_survives_git_objects_vanishing(self):
        # CI (Python 3.10): git packed objects in the background while Doctor's credential scan globbed
        # the whole repository, `.git` included; Path.glob raised FileNotFoundError and repair failed.
        from doctor.engine import HarnessDoctor
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".git/objects/97").mkdir(parents=True)
            (repo / ".git/objects/97/zoho_config.json").write_text("{}", encoding="utf-8")
            (repo / "app/src/vanishing").mkdir(parents=True)
            (repo / "app/zoho_config.json").write_text("{}", encoding="utf-8")
            real_scandir = os.scandir

            def flaky_scandir(path="."):
                if str(path).endswith("vanishing"):
                    raise FileNotFoundError(2, "No such file or directory", str(path))
                return real_scandir(path)

            doctor = HarnessDoctor(repo, run_selftest=False)
            with mock.patch("os.scandir", side_effect=flaky_scandir):
                found = sorted(p.relative_to(repo).as_posix() for p in doctor._repo_files(("zoho_config.json",)))
                doctor.check_zoho_mcp()
            self.assertEqual(["app/zoho_config.json"], found)
            isolation = next(r for r in doctor.results if r.name == "Credential Isolation")
            self.assertEqual("FAIL", isolation.status)
            self.assertIn(str(repo / "app" / "zoho_config.json"), isolation.message)
            self.assertNotIn(".git", isolation.message)

    def test_E1_doctor_checks_every_script_of_the_release_inventory(self):
        # Doctor checked a hand-kept list of 58 scripts and reported "All core scripts verified" while
        # phase_review.py, exported_component_guard.py and others could be missing. The release
        # checksum inventory is the single list of shipped scripts.
        from doctor.engine import HarnessDoctor
        from doctor.models import CORE_SCRIPTS
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            agents = repo / ".agents"
            (agents / "rules").mkdir(parents=True)
            (agents / "rules" / "harness-rules.md").write_text("rules\n", encoding="utf-8")
            (agents / "VERSION").write_text("1.1.1\n", encoding="utf-8")
            (agents / "scripts" / "doctor").mkdir(parents=True)
            for name in CORE_SCRIPTS:
                (agents / "scripts" / name).write_text("", encoding="utf-8")
            (agents / "scripts" / "doctor" / "engine.py").write_text("", encoding="utf-8")
            inventory = {name: "0" * 64 for name in (
                *(f"agents/scripts/{n}" for n in CORE_SCRIPTS), "agents/scripts/doctor/engine.py", "agents/scripts/phase_review.py",
            )}
            (agents / "release_checksums.json").write_text(json.dumps({"schema_version": 1, "algorithm": "sha256", "files": inventory}), encoding="utf-8")
            doctor = HarnessDoctor(repo, run_selftest=False)
            doctor.check_file_structure()
            result = next(r for r in doctor.results if r.name == "Core Scripts")
            self.assertEqual("FAIL", result.status, result.message)
            self.assertIn("phase_review.py", result.message)
            (agents / "scripts" / "phase_review.py").write_text("", encoding="utf-8")
            doctor = HarnessDoctor(repo, run_selftest=False)
            doctor.check_file_structure()
            result = next(r for r in doctor.results if r.name == "Core Scripts")
            self.assertEqual("PASS", result.status, result.message)
            self.assertIn(f"All {len(inventory)} ", result.message)

    def test_device_step_when_verification_is_disabled_says_so(self):
        # Round 5 (O3): with device verification disabled, install-start failed as an environment
        # problem and told the agent to halt instead of saying there is no device step.
        import _product
        out = io.StringIO()
        with mock.patch.object(_product, "DEVICE_VERIFICATION_MODE", "disabled", create=True), \
                mock.patch.object(sys, "argv", ["run_device.py", "install-start"]), \
                mock.patch.object(run_device, "require_serial", side_effect=AssertionError("no device lookup expected")), \
                contextlib.redirect_stdout(out):
            self.assertEqual(0, run_device.main())
        self.assertIn("Device verification is disabled", out.getvalue())
        self.assertIn("task status --next", out.getvalue())

    def test_install_explains_app_owned_agents_directory(self):
        # Round 5 (D2): an app keeping .agents/skills got "already contains a harness", which was wrong
        # and gave no migration step.
        fixture = fixtures.LifecycleTests()
        fixture.setUp()
        try:
            fixture._answers()
            (fixture.repo / ".agents/skills/app-skill").mkdir(parents=True)
            with self.assertRaisesRegex(ValidationError, r"did not install \(entries: skills/\).*git mv \.agents/skills"):
                lifecycle.install(fixture.repo, fixtures.KIT)
            self.assertFalse((fixture.repo / ".agents/scripts").exists())
            self.assertTrue((fixture.repo / ".agents/skills/app-skill").is_dir())
        finally:
            fixture.tearDown()

    def test_update_accepts_a_product_config_rendered_from_the_answers(self):
        # Real app: the developer raised the reviewer budget in answers.json and _product.py together;
        # update then refused "user-modified managed files require clean recovery: _product.py".
        fixture = fixtures.LifecycleTests()
        fixture.setUp()
        try:
            fixture._answers()
            lifecycle.install(fixture.repo, fixtures.KIT)
            answers_path = fixture.repo / ".harness-setup/answers.json"
            product = fixture.repo / ".agents/scripts/_product.py"
            original = product.read_text(encoding="utf-8")
            self.assertIn("MODEL_CALL_BUDGET = 20\n", original)
            # Changed here only: a hand edit the answers do not produce is still a conflict.
            product.write_text(original.replace("MODEL_CALL_BUDGET = 20\n", "MODEL_CALL_BUDGET = 30\n"), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, r"user-modified managed files require clean recovery.*_product\.py"):
                lifecycle.update(fixture.repo, fixtures.KIT)
            # Other code in the file is a conflict even when every value matches.
            product.write_text(original + "import os\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, r"_product\.py"):
                lifecycle.update(fixture.repo, fixtures.KIT)
            # Changed in both, as the setup question would: the update proceeds and keeps the value.
            answers = json.loads(answers_path.read_text(encoding="utf-8"))
            answers["model_call_budget"] = 30
            answers_path.write_text(json.dumps(answers), encoding="utf-8")
            product.write_text(original.replace("MODEL_CALL_BUDGET = 20\n", "MODEL_CALL_BUDGET = 30\n"), encoding="utf-8")
            lifecycle.update(fixture.repo, fixtures.KIT)
            self.assertIn("MODEL_CALL_BUDGET = 30\n", product.read_text(encoding="utf-8"))
            # The new ownership record matches the regenerated file, so the next update is clean.
            lifecycle.update(fixture.repo, fixtures.KIT)
        finally:
            fixture.tearDown()

    @staticmethod
    def _managed_integrity(repo: Path):
        from doctor.engine import HarnessDoctor

        doctor = HarnessDoctor(repo, run_selftest=False)
        doctor.check_file_structure()
        return [r for r in doctor.results if r.name == "Managed File Integrity"]

    def test_doctor_recovery_commands_use_the_external_kit_from_an_app_root(self):
        from _vnext_common import canonical_sha256

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "Android Project"
            managed = repo / ".agents/scripts/phase_review.py"
            managed.parent.mkdir(parents=True)
            managed.write_bytes(b"# local edit\n")
            ownership = {
                "architecture_major": 1,
                "entries": [{
                    "path": ".agents/scripts/phase_review.py",
                    "post_install_sha256": sha256_bytes(b"# release copy\n"),
                }],
            }
            ownership["ownership_sha256"] = canonical_sha256(ownership)
            setup = repo / ".harness-setup"
            setup.mkdir()
            (setup / "ownership-v1.json").write_text(json.dumps(ownership), encoding="utf-8")

            integrity = self._managed_integrity(repo)
            self.assertEqual(["WARN"], [r.status for r in integrity])
            instructions = next(d for d in integrity[0].details if "--discard-local-edits" in d)
            refusal = lifecycle._conflict_refusal_message([".agents/scripts/phase_review.py"], discard_requested=False)
            commands = [instructions[instructions.index("python "):]]
            commands.extend(part for part in refusal.split("'") if part.startswith("python "))
            self.assertEqual(3, len(commands))
            for command in commands:
                with self.subTest(command=command):
                    rendered = command.replace("<kit-dir>", str(fixtures.KIT)).replace("<app-root>", str(repo))
                    argv = shlex.split(rendered)
                    launcher = Path(argv[1])
                    self.assertTrue(launcher.is_absolute(), "recovery must not resolve its launcher against the app root")
                    self.assertTrue(launcher.is_file(), "the suggested launcher must exist in the external kit")
                    self.assertEqual(fixtures.KIT / "harness_cli.py", launcher)
                    self.assertEqual(str(repo), argv[argv.index("--repo") + 1])
                    self.assertEqual(str(fixtures.KIT), argv[argv.index("--kit") + 1])
                    if argv[2] == "update":
                        self.assertIn("--discard-local-edits", argv)

    def test_update_discard_local_edits_restores_engine_files_and_keeps_backup(self):
        # Real app (Rashaqa): hand edits to phase_review.py and _product.py blocked the update, and the only
        # offered recovery was uninstall + init; doctor had passed because it never compared hashes.
        fixture = fixtures.LifecycleTests()
        fixture.setUp()
        try:
            fixture._answers()
            lifecycle.install(fixture.repo, fixtures.KIT)
            self.assertEqual(["PASS"], [r.status for r in self._managed_integrity(fixture.repo)])
            engine = fixture.repo / ".agents/scripts/phase_review.py"
            product = fixture.repo / ".agents/scripts/_product.py"
            engine_release = engine.read_bytes()
            product_release = product.read_text(encoding="utf-8")
            engine.write_bytes(engine_release + b"\nDEFAULT_SAFETY_CAP = 30\n")
            product.write_text(product_release.replace("MODEL_CALL_BUDGET = 20\n", "MODEL_CALL_BUDGET = 30\n"), encoding="utf-8")
            engine_edited = engine.read_bytes()
            product_edited = product.read_bytes()

            # Doctor now warns before any update is attempted.
            integrity = self._managed_integrity(fixture.repo)
            self.assertEqual(["WARN"], [r.status for r in integrity])
            self.assertIn("2 managed file(s)", integrity[0].message)
            self.assertIn(".agents/scripts/phase_review.py", integrity[0].details)
            self.assertIn(".agents/scripts/_product.py", integrity[0].details)
            self.assertTrue(any("--discard-local-edits" in d for d in integrity[0].details))

            # Without the flag: refused exactly as before, nothing touched, every recovery path named.
            with self.assertRaises(ValidationError) as refused:
                lifecycle.update(fixture.repo, fixtures.KIT)
            message = str(refused.exception)
            first_line = message.splitlines()[0]
            self.assertIn("user-modified managed files require clean recovery", first_line)
            self.assertIn(".agents/scripts/phase_review.py", first_line)
            self.assertIn(".agents/scripts/_product.py", first_line)
            self.assertIn("--discard-local-edits", message)
            self.assertIn("model_call_budget", message)
            self.assertIn("uninstall --apply", message)
            self.assertNotIn("never discarded automatically", message)
            self.assertEqual(engine_edited, engine.read_bytes())
            self.assertEqual(product_edited, product.read_bytes())

            # With the flag: release copies installed, edited copies kept in the pre-update backup.
            result = lifecycle.update(fixture.repo, fixtures.KIT, discard_local_edits=True)
            self.assertEqual("PASS", result["status"])
            self.assertEqual(
                {".agents/scripts/phase_review.py", ".agents/scripts/_product.py"},
                set(result["discarded_local_edits"]),
            )
            self.assertEqual((fixtures.KIT / "agents/scripts/phase_review.py").read_bytes(), engine.read_bytes())
            self.assertIn("MODEL_CALL_BUDGET = 20\n", product.read_text(encoding="utf-8"))
            backup = Path(result["backup"])
            self.assertEqual(engine_edited, (backup / ".agents/scripts/phase_review.py").read_bytes())
            self.assertEqual(product_edited, (backup / ".agents/scripts/_product.py").read_bytes())
            self.assertEqual(["PASS"], [r.status for r in self._managed_integrity(fixture.repo)])

            # The next update is clean and reports nothing discarded.
            again = lifecycle.update(fixture.repo, fixtures.KIT)
            self.assertNotIn("discarded_local_edits", again)
        finally:
            fixture.tearDown()

    def test_update_discard_local_edits_never_overwrites_files_outside_agents(self):
        fixture = fixtures.LifecycleTests()
        fixture.setUp()
        try:
            fixture._answers()
            installed = lifecycle.install(fixture.repo, fixtures.KIT)
            outside = sorted(
                entry["path"] for entry in installed["ownership"]["entries"]
                if not entry["path"].startswith(".agents/") and entry.get("post_install_sha256")
            )
            self.assertTrue(outside, "fixture install must manage at least one adapter outside .agents/")
            adapter = fixture.repo / outside[0]
            engine = fixture.repo / ".agents/scripts/phase_review.py"
            adapter.write_text(adapter.read_text(encoding="utf-8") + "\nApp-owned note.\n", encoding="utf-8")
            engine.write_bytes(engine.read_bytes() + b"\n# local edit\n")
            adapter_edited = adapter.read_bytes()
            engine_edited = engine.read_bytes()

            integrity = self._managed_integrity(fixture.repo)
            self.assertEqual(["WARN"], [r.status for r in integrity])
            self.assertTrue(any("outside .agents/" in d for d in integrity[0].details))

            with self.assertRaises(ValidationError) as refused:
                lifecycle.update(fixture.repo, fixtures.KIT, discard_local_edits=True)
            message = str(refused.exception)
            self.assertIn(outside[0], message.splitlines()[0])
            self.assertIn("never discarded automatically", message)
            # The flag was already given, so it is not offered again.
            self.assertNotIn("rerun the same update command with --discard-local-edits", message)
            # Refusal happens before any change: both edits survive byte for byte.
            self.assertEqual(adapter_edited, adapter.read_bytes())
            self.assertEqual(engine_edited, engine.read_bytes())
        finally:
            fixture.tearDown()

    def test_doctor_managed_file_integrity_is_skipped_without_ownership_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents" / "rules").mkdir(parents=True)
            (repo / ".agents" / "rules" / "harness-rules.md").write_text("rules\n", encoding="utf-8")
            (repo / ".agents" / "VERSION").write_text("1.1.1\n", encoding="utf-8")
            self.assertEqual([], self._managed_integrity(repo))
            # A tampered manifest is reported, never raised out of doctor.
            (repo / ".harness-setup").mkdir()
            (repo / ".harness-setup" / "ownership-v1.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
            integrity = self._managed_integrity(repo)
            self.assertEqual(["WARN"], [r.status for r in integrity])
            self.assertIn("integrity mismatch", integrity[0].message)

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
            startup = stack.enter_context(mock.patch.object(run_device, 'check_startup',
                return_value={'schema_version': 1, 'status': 'PASS', 'detail': 'Foreground verified'}))
            adb = stack.enter_context(mock.patch.object(run_device, "run_adb", return_value=(0, "Success")))
            stack.enter_context(mock.patch.object(sys, "argv", ["run_device.py", "start", "--user", "10"]))
            self.assertEqual(0, run_device.main())
            self.assertIn("com.example.debug/com.example.MainActivity", adb.call_args.args[1])
            self.assertEqual(["--user", "10"], adb.call_args.args[1][3:5])
            self.assertEqual("com.example.debug", record.call_args.kwargs["application_id"])
            self.assertEqual(('device', 'com.example.debug', '10', artifact), startup.call_args.args[:4])
            self.assertEqual('PASS', record.call_args.kwargs['startup_probe']['status'])
            startup.return_value = {'schema_version': 1, 'status': 'FAIL', 'detail': 'Expected element missing'}
            self.assertEqual(1, run_device.main())
            self.assertEqual('FAIL', record.call_args.args[1])
            startup.return_value = {'schema_version': 1, 'status': 'PASS', 'detail': 'Foreground verified'}
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
            # Real app: a newer build on the phone; the developer may choose to install over it (adb -d).
            with mock.patch.object(sys, "argv", ["run_device.py", "install-start", "--allow-downgrade"]), mock.patch.object(run_device, "DEFAULT_ACTIVITY", "com.example/.MainActivity"), mock.patch.object(run_device.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="10\n")):
                adb.reset_mock()
                self.assertEqual(0, run_device.main())
                install_cmd = [call.args[1] for call in adb.call_args_list][0]
                self.assertEqual(["install", "-r", "-d", "--user", "10"], install_cmd[:5])
            # Real app: if _product.py was overwritten with the raw kit template (com.example.app/.MainActivity),
            # run_device resolves the real launcher activity from .harness-setup/answers.json or AndroidManifest.xml
            # instead of launching com.madarsoft.fitness/com.example.app.MainActivity.
            answers_dir = root / ".harness-setup"
            answers_dir.mkdir(parents=True, exist_ok=True)
            (answers_dir / "answers.json").write_text(
                json.dumps({"launcher": "com.example/.features.splash.SplashActivity"}),
                encoding="utf-8",
            )
            with mock.patch.object(sys, "argv", ["run_device.py", "install-start"]), mock.patch.object(run_device, "DEFAULT_ACTIVITY", "com.example.app/.MainActivity"), mock.patch.object(run_device.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="10\n")):
                adb.reset_mock()
                self.assertEqual(0, run_device.main())
                commands = [call.args[1] for call in adb.call_args_list]
                self.assertEqual(
                    ["shell", "am", "start", "--user", "10", "-n", "com.example.debug/com.example.features.splash.SplashActivity"],
                    commands[1],
                )

    def test_unclassified_delivery_file_not_masked_by_docs(self):
        fixture = fixtures.RepoCase()
        fixture.setUp()
        try:
            root = fixture.repo
            fixtures.write(root / "docs/notes.md", "Documentation notes\n")
            fixtures.run_git(root, "add", ".")
            fixtures.run_git(root, "commit", "-qm", "baseline doc")

            # 1. Modifying documentation and an unclassified delivery config.json
            fixtures.write(root / "docs/notes.md", "Updated notes\n")
            fixtures.write(root / "app/config.json", '{"theme": "dark"}\n')
            result = change_classifier.classify(root)
            self.assertIn("DOCS", result["surfaces"])
            self.assertIn("UNKNOWN", result["surfaces"])
            self.assertEqual("LOW", result["confidence"])

            # 2. Positive neighboring case: modifying only documentation stays pure DOCS
            (root / "app/config.json").unlink()
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

    def test_exact_executable_payload_inventory_enforced_across_verifiers(self):
        cli = fixtures.harness_cli
        from repair import _verify_kit
        current_version = (fixtures.KIT / "agents" / "VERSION").read_text(encoding="utf-8").strip()

        with tempfile.TemporaryDirectory() as directory:
            kit = Path(directory)
            shutil.copytree(fixtures.KIT / "agents", kit / "agents")

            # 1. Valid kit passes all 3 verifiers
            self.assertEqual(0, cli._verify_kit_checksums(kit) or 0)
            valid_root, ver = lifecycle._validate_kit(kit)
            self.assertEqual(kit.resolve(), valid_root)
            repaired_files = _verify_kit(kit, current_version)
            self.assertTrue(len(repaired_files) > 0)

            # 2. Extra agents/scripts/json.py fails before any engine script executes
            extra_file = kit / "agents" / "scripts" / "json.py"
            extra_file.write_text("# shadow stdlib\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as ctx:
                cli._verify_kit_checksums(kit)
            self.assertIn("unexpected", str(ctx.exception).lower())
            with self.assertRaisesRegex(ValidationError, "unexpected"):
                lifecycle._validate_kit(kit)
            with self.assertRaisesRegex(ValidationError, "unexpected"):
                _verify_kit(kit, current_version)
            extra_file.unlink()

            # 3. Extra nested Python file fails
            nested_file = kit / "agents" / "scripts" / "nested_extra.py"
            nested_file.write_text("# nested\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                cli._verify_kit_checksums(kit)
            with self.assertRaises(ValidationError):
                lifecycle._validate_kit(kit)
            with self.assertRaises(ValidationError):
                _verify_kit(kit, current_version)
            nested_file.unlink()

            # 4. State/cache/bytecode files remain ignored
            (kit / "agents" / "state").mkdir(parents=True, exist_ok=True)
            (kit / "agents" / "state" / "temp.txt").write_text("state\n")
            (kit / "agents" / "scripts" / "__pycache__").mkdir(parents=True, exist_ok=True)
            (kit / "agents" / "scripts" / "__pycache__" / "foo.cpython-312.pyc").write_bytes(b"byte")
            (kit / "agents" / "scripts" / "temp.pyc").write_bytes(b"byte")
            # Must still pass!
            self.assertEqual(0, cli._verify_kit_checksums(kit) or 0)
            lifecycle._validate_kit(kit)
            _verify_kit(kit, current_version)

            # 5. Missing manifest entry (file exists on disk, removed from manifest)
            manifest_path = kit / "agents" / "release_checksums.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            removed_key = "agents/command-packs/debug.md.template"
            del manifest["files"][removed_key]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(SystemExit) as ctx:
                cli._verify_kit_checksums(kit)
            self.assertIn("unexpected", str(ctx.exception).lower())
            with self.assertRaisesRegex(ValidationError, "unexpected"):
                lifecycle._validate_kit(kit)
            with self.assertRaisesRegex(ValidationError, "unexpected"):
                _verify_kit(kit, current_version)

            # 6. Manifest entry with a missing file (entry in manifest, deleted from disk)
            shutil.copyfile(fixtures.KIT / "agents" / "release_checksums.json", manifest_path)
            deleted_file = kit / "agents" / "command-packs" / "debug.md.template"
            deleted_file.unlink()
            with self.assertRaises(SystemExit) as ctx:
                cli._verify_kit_checksums(kit)
            self.assertIn("missing", str(ctx.exception).lower())
            with self.assertRaisesRegex(ValidationError, "missing"):
                lifecycle._validate_kit(kit)
            with self.assertRaisesRegex(ValidationError, "missing"):
                _verify_kit(kit, current_version)
            shutil.copyfile(fixtures.KIT / "agents" / "command-packs" / "debug.md.template", deleted_file)

            # 7. Symlinked payload file fails on platforms that permit symlinks
            symlink_candidate = kit / "agents" / "scripts" / "symlink_test.py"
            try:
                symlink_candidate.symlink_to(kit / "agents" / "VERSION")
            except OSError:
                pass
            else:
                try:
                    with self.assertRaises(SystemExit):
                        cli._verify_kit_checksums(kit)
                    with self.assertRaises(ValidationError):
                        lifecycle._validate_kit(kit)
                    with self.assertRaises(ValidationError):
                        _verify_kit(kit, current_version)
                finally:
                    symlink_candidate.unlink(missing_ok=True)

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


class RetryEvidenceTests(unittest.TestCase):
    def test_clean_rerun_in_same_run_cannot_erase_diagnostic_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            store = evidence_store.EvidenceStore(Path(directory))
            common = dict(snapshot='a' * 64, run_id='run', name='unit_tests', producer='run_tests_gate',
                          harness_version='v', change_set='c')
            store.write(**common, status='FAIL', evidence={'attempts': [{'new_regressions': ['A#a']}]})
            store.write(**common, status='PASS', evidence={'executed': 1})
            record, error = final_verifier._validate_artifact(store, 'a' * 64, 'c', 'run', 'unit_tests', 'v')
            self.assertIsNotNone(error)
            store.reuse(snapshot='a' * 64, source_run_id='run', run_id='reuse-run', name='unit_tests')
            self.assertIsNotNone(final_verifier._validate_artifact(store, 'a' * 64, 'c', 'reuse-run', 'unit_tests', 'v')[1])
            store.write(**{**common, 'run_id': 'new-run'}, status='PASS', evidence={'executed': 1})
            self.assertIsNone(final_verifier._validate_artifact(store, 'a' * 64, 'c', 'new-run', 'unit_tests', 'v')[1])

    def exercise(self, retry='pass', identities=None):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            repo = Path(directory)
            folder = repo / 'app/build/test-results/testDebugUnitTest'
            folder.mkdir(parents=True)
            report = folder / 'TEST-A.xml'
            if retry == 'initial-stale':
                report.write_text('<testsuite tests="1" failures="1"><testcase classname="A" name="a"><failure/></testcase></testsuite>', encoding='utf-8')
            calls, records = [], []
            def gradle(args, outcome):
                calls.append(args)
                if retry == 'initial-stale':
                    return 0
                if len(calls) == 2 and retry == 'env':
                    return 30
                if len(calls) == 2 and retry == 'stale':
                    return 0
                failed = (len(calls) == 1 and retry != 'initial-pass') or retry == 'fail'
                report.write_text('<testsuite tests="1" failures="' + str(int(failed)) + '">'
                    '<testcase classname="A" name="a">' + ('<failure message="private failure"/>' if failed else '')
                    + '</testcase></testsuite>', encoding='utf-8')
                stat = report.stat()
                os.utime(report, ns=(stat.st_atime_ns, stat.st_mtime_ns + len(calls) * 10000000))
                outcome['test_failure_only'] = failed
                return int(failed)
            stack.enter_context(mock.patch.object(run_tests_gate, 'REPO', repo))
            stack.enter_context(mock.patch.object(run_tests_gate, 'execution_identity', create=True,
                side_effect=identities if identities else None, return_value={'delivery_snapshot_sha256': 'a' * 64,
                'change_set_sha256': 'b' * 64, 'external_inputs_sha256': 'c' * 64}))
            stack.enter_context(mock.patch.object(run_tests_gate, 'load_baseline', return_value={'unit_tests': []}))
            stack.enter_context(mock.patch.object(run_tests_gate, 'current_head_sha', return_value=''))
            stack.enter_context(mock.patch.object(run_tests_gate, 'write_gate_result', side_effect=lambda name, data: records.append(data.copy())))
            stack.enter_context(mock.patch.object(run_gradle_task, 'run_gradle', side_effect=gradle))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = run_tests_gate.main([':app:testDebugUnitTest'])
            if retry == 'pass' and identities is None:
                self.assertIn('SUSPECTED_FLAKY', sys.stderr.getvalue())
            return code, calls, records

    def test_failure_then_pass_is_suspected_flaky_and_still_blocks(self):
        code, calls, records = self.exercise()
        self.assertNotEqual(0, code)
        self.assertEqual(2, len(calls))
        self.assertIn('--rerun-tasks', calls[1])
        self.assertEqual('FAIL', records[0]['status'])
        self.assertEqual(['A#a'], records[-1]['suspected_flaky'])
        self.assertEqual(2, len(records[-1]['attempts']))
        self.assertNotIn('private failure', json.dumps(records))

    def test_green_run_passes_only_when_inputs_stay_unchanged(self):
        code, calls, records = self.exercise('initial-pass')
        self.assertEqual(0, code)
        self.assertEqual(1, len(calls))
        code, calls, records = self.exercise('initial-pass', [{'delivery_snapshot_sha256': 'a'}, {'delivery_snapshot_sha256': 'b'}])
        self.assertNotEqual(0, code)
        self.assertEqual(1, len(calls))
        self.assertIn('changed', records[-1]['detail'])

    def test_success_with_old_failed_xml_does_not_trigger_a_diagnostic_retry(self):
        code, calls, records = self.exercise('initial-stale')
        self.assertNotEqual(0, code)
        self.assertEqual(1, len(calls))

    def test_persistent_failure_retries_only_once(self):
        code, calls, records = self.exercise('fail')
        self.assertNotEqual(0, code)
        self.assertEqual(2, len(calls))
        self.assertEqual(['A#a'], records[-1]['new_regressions'])
        self.assertEqual([], records[-1]['suspected_flaky'])

    def test_stale_retry_does_not_prove_recovery(self):
        code, calls, records = self.exercise('stale')
        self.assertNotEqual(0, code)
        self.assertEqual(2, len(calls))
        self.assertEqual([], records[-1]['suspected_flaky'])
        self.assertEqual(['A#a'], records[-1]['new_regressions'])

    def test_environment_retry_preserves_first_failure(self):
        code, calls, records = self.exercise('env')
        self.assertEqual(30, code)
        self.assertEqual('ENV', records[-1]['status'])
        self.assertEqual(['A#a'], records[-1]['attempts'][0]['new_regressions'])

    def test_source_change_blocks_retry(self):
        code, calls, records = self.exercise(identities=[{'delivery_snapshot_sha256': 'a'}, {'delivery_snapshot_sha256': 'b'}])
        self.assertNotEqual(0, code)
        self.assertEqual(1, len(calls))
        self.assertIn('changed', records[-1]['detail'])


class StartupEvidenceTests(unittest.TestCase):
    def test_malformed_or_excessively_deep_ui_cannot_create_screen_proof(self):
        from _adb_core import parse_ui_hierarchy
        for xml in (
            '<unexpected><node package="com.example" resource-id="com.example:id/home" bounds="[0,0][100,100]"/></unexpected>',
            '<hierarchy>' + '<node>' * 1500 + '</node>' * 1500 + '</hierarchy>',
            '<hierarchy><node text="' + 'x' * (2 * 1024 * 1024) + '"/></hierarchy>',
        ):
            self.assertEqual([], parse_ui_hierarchy(xml))

    def transport(self, xml=None, probe=None):
        from journey_runner import AdbTransport
        transport = AdbTransport('device', 'com.example', ['a' * 64])
        transport.verify_installed_artifact = mock.Mock()
        def call(args, timeout=3):
            if args[:2] == ['shell', 'am get-current-user && dumpsys activity activities']:
                return probe or '0\ntopResumedActivity u0 com.example/.Main'
            if args[0] == 'exec-out':
                return xml if xml is not None else '<hierarchy><node package="com.example" resource-id="com.example:id/home" bounds="[0,0][100,100]" enabled="true"/></hierarchy>'
            return '35'
        transport.call = call
        return transport

    def test_startup_expected_element_requires_actual_matching_ui(self):
        transport = self.transport()
        result = run_device.probe_startup(transport, 'com.example:id/home', 1)
        self.assertEqual('PASS', result['status'])
        self.assertEqual('PASS', result['screen_assertion'])
        self.assertGreaterEqual(transport.verify_installed_artifact.call_count, 2)
        result = run_device.probe_startup(self.transport(), 'com.example:id/missing', 0.1)
        self.assertEqual('FAIL', result['status'])

    def test_startup_does_not_accept_another_package_or_invisible_element(self):
        for xml in (
            '<hierarchy><node package="com.other" resource-id="com.example:id/home" bounds="[0,0][100,100]"/></hierarchy>',
            '<hierarchy><node package="com.example" resource-id="com.example:id/home" bounds="[0,0][0,0]"/></hierarchy>',
        ):
            self.assertEqual('FAIL', run_device.probe_startup(self.transport(xml), 'com.example:id/home', 0.1)['status'])

    def test_startup_missing_hierarchy_is_limited_without_visual_claim(self):
        result = run_device.probe_startup(self.transport('not XML private user text'), None, 1)
        self.assertEqual('PASS', result['status'])
        self.assertEqual('UNAVAILABLE', result['hierarchy'])
        self.assertEqual('NOT_REQUESTED', result['screen_assertion'])
        self.assertNotIn('private user text', json.dumps(result))
        self.assertEqual('ENV', run_device.probe_startup(self.transport('bad'), 'com.example:id/home', 1)['status'])

    def test_startup_foreground_and_installed_apk_must_match(self):
        transport = self.transport(probe='0\ntopResumedActivity u0 com.other/.Main')
        self.assertNotEqual('PASS', run_device.probe_startup(transport, None, 0.1)['status'])
        transport = self.transport()
        transport.verify_installed_artifact.side_effect = OSError('private installed path')
        result = run_device.probe_startup(transport, None, 1)
        self.assertEqual('ENV', result['status'])
        self.assertNotIn('private installed path', json.dumps(result))

    def test_installed_apk_change_after_hierarchy_cannot_pass(self):
        transport = self.transport()
        transport.verify_installed_artifact.side_effect = [None, OSError('APK replaced')]
        self.assertEqual('ENV', run_device.probe_startup(transport, 'com.example:id/home', 1)['status'])

    def test_startup_supports_work_profile_but_never_switches_selected_user(self):
        from journey_runner import AdbTransport
        transport = AdbTransport('device', 'com.example', ['a' * 64], target_user='10')
        commands = []
        def call(args, timeout=3):
            commands.append(args)
            if args[:3] == ['shell', 'pm', 'path']:
                return 'package:/data/app/example/base.apk'
            if args[:2] == ['shell', 'sha256sum']:
                return 'a' * 64 + '  /data/app/example/base.apk'
            if args[0] == 'exec-out':
                return '<hierarchy><node package="com.example" resource-id="com.example:id/home" bounds="[0,0][100,100]"/></hierarchy>'
            if args[:2] == ['shell', 'am get-current-user && dumpsys activity activities']:
                return '0\ntopResumedActivity u10 com.example/.Main'
            return '35'
        transport.call = call
        self.assertEqual('PASS', run_device.probe_startup(transport, 'com.example:id/home', 1)['status'])
        self.assertIn(['shell', 'pm', 'path', '--user', '10', 'com.example'], commands)
        transport.call = lambda *args: '0\ntopResumedActivity u0 com.example/.Main'
        self.assertNotEqual('PASS', run_device.probe_startup(transport, None, 0.1)['status'])

    def test_startup_disconnect_after_dump_cannot_pass(self):
        transport = self.transport()
        original = transport.check_identity
        transport.check_identity = mock.Mock(side_effect=[original(), OSError('device lost')])
        self.assertEqual('ENV', run_device.probe_startup(transport, None, 1)['status'])

    def test_final_verifier_rejects_failed_startup_even_if_outer_record_says_pass(self):
        record = {'change_set_sha256': 'c', 'producer': 'run_device', 'schema_version': 1,
                  'harness_version': 'v', 'status': 'PASS', 'evidence': {'startup_probe': {'schema_version': 1, 'status': 'FAIL'}}}
        store = mock.Mock()
        store.read.return_value = record
        self.assertIsNotNone(final_verifier._validate_artifact(store, 's', 'c', 'r', 'device_launch', 'v')[1])

    def test_final_verifier_accepts_valid_startup_without_requiring_visual_assertion(self):
        store = mock.Mock()
        for selector in (None, 'com.example:id/home'):
            evidence = run_device.probe_startup(self.transport(), selector, 1)
            store.read.return_value = {'change_set_sha256': 'c', 'producer': 'run_device', 'schema_version': 1,
                'harness_version': 'v', 'status': 'PASS', 'evidence': {'startup_probe': evidence}}
            self.assertIsNone(final_verifier._validate_artifact(store, 's', 'c', 'r', 'device_launch', 'v')[1])

    def test_new_evidence_fields_fail_closed_when_malformed_or_contradictory(self):
        store = mock.Mock()
        for name, evidence in (
            ('unit_tests', {'attempts': None}),
            ('unit_tests', {'suspected_flaky': ['A#a']}),
            ('device_launch', {'startup_probe': {'schema_version': True, 'status': 'PASS', 'foreground': 'PASS',
                'installed_artifact': 'PASS', 'hierarchy': 'OBSERVED', 'screen_assertion': 'PASS'}}),
        ):
            store.read.return_value = {'change_set_sha256': 'c', 'producer': 'run_device' if name == 'device_launch' else 'run_tests_gate',
                'schema_version': 1, 'harness_version': 'v', 'status': 'PASS', 'evidence': evidence}
            with self.subTest(name=name, evidence=evidence):
                self.assertIsNotNone(final_verifier._validate_artifact(store, 's', 'c', 'r', name, 'v')[1])


class AntigravityAuditRegressionTests(unittest.TestCase):
    def hook(self, repo, name, args, **environment):
        import subprocess
        script = Path(__file__).with_name("pre_tool_safety.py")
        result = subprocess.run([sys.executable, str(script)],
            input=json.dumps({"toolCall": {"name": name, "args": args}}),
            capture_output=True, text=True, timeout=20,
            env={**os.environ, "HARNESS_REPO": str(repo), "HARNESS_HOOK_HOST": "antigravity",
                 "HARNESS_HOOK_STATE": str(repo / "audit/hook.json"), **environment})
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_antigravity_shell_expressions_and_local_impersonators_are_denied(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            for command in (
                "Get-Content (Set-Content -Path probe.txt -Value changed -PassThru)",
                "Get-Item @(New-Item -Path probe.txt)",
                "Get-ChildItem -Path . -Filter {Set-Content probe.txt changed}",
                "./tools/git status", "./tools/rg pattern .", "./tools/python -m compileall .",
            ):
                with self.subTest(command=command):
                    self.assertEqual("deny", self.hook(repo, "run_command", {"CommandLine": command})["decision"])
            for command in ("git status --short", 'Get-Content "file (copy).txt"', 'rg "fun (foo)" app'):
                with self.subTest(command=command):
                    self.assertEqual("allow", self.hook(repo, "run_command", {"CommandLine": command})["decision"])

    def test_antigravity_native_proof_is_not_an_editable_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            runtime = Path(td) / "runtime"
            for name in ("transcript.jsonl", ".system_generated/logs/transcript.jsonl", "metadata.json", "nested/plan.md"):
                target = runtime / "brain/conversation" / name
                with self.subTest(name=name):
                    self.assertEqual("deny", self.hook(repo, "write_to_file", {"TargetFile": str(target)},
                        ANTIGRAVITY_APP_DATA=str(runtime))["decision"])
            self.assertEqual("allow", self.hook(repo, "write_to_file",
                {"TargetFile": str(runtime / "brain/conversation/implementation_plan.md")},
                ANTIGRAVITY_APP_DATA=str(runtime))["decision"])

    def test_antigravity_empty_disabled_or_incomplete_hooks_do_not_claim_hard_enforcement(self):
        from _enforcement import detect
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            hooks = root / ".agents/hooks.json"
            hooks.parent.mkdir()
            for body in ("{}", "invalid", '[]', '{"adb-and-git-safety":{"enabled":false}}'):
                hooks.write_text(body, encoding="utf-8")
                self.assertEqual("RULE_ENFORCED", detect(root, ["antigravity"])["by_host"]["antigravity"])

    def test_antigravity_fingerprint_tracks_nested_code_and_reuses_unchanged_file_hashes(self):
        import ensure_hook_selftest as checker
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scripts = root / "scripts"
            (scripts / "nested").mkdir(parents=True)
            source = scripts / "nested/engine.py"
            source.write_text("old", encoding="utf-8")
            with mock.patch.multiple(checker, AGENTS=root, SCRIPTS=scripts, CACHE=root / "state/cache.json"):
                first = checker.harness_fingerprint()
                checker._write_cache(first, True)
                with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unchanged source reread")):
                    self.assertEqual(first, checker.harness_fingerprint())
                source.write_text("new", encoding="utf-8")
                self.assertNotEqual(first, checker.harness_fingerprint())
                source.unlink()
                self.assertNotEqual(first, checker.harness_fingerprint())

    def test_antigravity_identity_scan_does_not_read_tool_history_after_dispatch(self):
        import reviewer_host
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "transcript.jsonl"
            first = {"source": "SYSTEM_SDK", "type": "SYSTEM_MESSAGE", "content": "dispatch"}
            path.write_text(json.dumps(first) + "\n" + "invalid history\n", encoding="utf-8")
            messages = reviewer_host.identity_messages(path)
            self.assertEqual("dispatch", next(messages))
            messages.close()

    def test_antigravity_bound_reviewer_rechecks_identity_without_reading_history_or_relocking(self):
        import reviewer_host as host
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            transcript, brief, ledger = root / "transcript.jsonl", root / "brief.md", root / "ledger.json"
            brief.write_text("exact brief", encoding="utf-8")
            ledger.write_text("{}", encoding="utf-8")
            first = {"source": "SYSTEM_SDK", "type": "SYSTEM_MESSAGE",
                     "content": "sender=parent priority=MESSAGE_PRIORITY_HIGH content=exact brief\n</SYSTEM_MESSAGE>"}
            transcript.write_text(json.dumps(first) + "\n" + '{}\n' * 7 + "unrelated malformed tail\n", encoding="utf-8")
            run = {"review_host": "antigravity", "briefs": {"bug-reviewer-agent": str(brief)}}
            data = {"reviewers": {"bug-reviewer-agent": {"state": "DISPATCHED", "execution_id": "child", "parent_execution_id": "parent"}}}
            with mock.patch.object(host, "resolve_transcript", return_value=transcript), \
                    mock.patch.object(host, "active_reviews", return_value=[(run, ledger)]), \
                    mock.patch.object(host, "_load_ledger", return_value=data), \
                    mock.patch.object(host, "StateLock", side_effect=AssertionError("already bound")):
                self.assertEqual("bug-reviewer-agent", host.reviewer_context(root, "child", bind=True)["role"])
                with self.assertRaises(ValidationError):
                    host.reviewer_context(root, "different-child", bind=True)
                transcript.write_text('{}\n', encoding="utf-8")
                self.assertEqual({"unverified_reviewer": True}, host.reviewer_context(root, "child", bind=True))

    def test_antigravity_reading_guide_preserves_shared_context_and_falls_back(self):
        from review_package import review_reading_guide
        content = "header\n## Git diff\n```diff\ndiff --git a/A.kt b/A.kt\n+x\ndiff --git a/B.kt b/B.kt\n+y\n```\n## Acceptance\nall criteria\n"
        changes = [{"path": "A.kt"}, {"path": "B.kt"}]
        policy = {"surfaces": ["COROUTINES", "BUSINESS_LOGIC"], "explanation": {"classification": {
            "COROUTINES": {"files": ["A.kt"]}, "BUSINESS_LOGIC": {"files": ["B.kt"]}}}}
        guide = review_reading_guide(content, "perf-anr-guardian-agent", policy, changes)
        self.assertEqual(["A.kt"], guide["focus_files"])
        self.assertEqual([[1, 3], [4, 5], [8, 10]], guide["line_ranges"])
        self.assertIsNone(review_reading_guide(content, "bug-reviewer-agent", policy, changes))
        self.assertIsNone(review_reading_guide(content, "perf-anr-guardian-agent", {**policy, "surfaces": ["AUTH"]}, changes))
        self.assertIsNone(review_reading_guide(content, "perf-anr-guardian-agent", policy, changes + [{"path": "missing.kt"}]))
        # Passive surfaces (DOCS, LOCALIZATION, TEST_ONLY) and quoted/untracked paths are supported.
        mixed_content = (
            'header\n## Git diff\n```diff\ndiff --git "a/dir with space/A.kt" "b/dir with space/A.kt"\n+x\n'
            'diff --git a/README.md b/README.md\n+doc\n```\n## NEW UNTRACKED FILE B.kt\nclass B\n'
        )
        mixed_changes = [{"path": "dir with space/A.kt"}, {"path": "README.md"}, {"path": "B.kt"}]
        mixed_policy = {"surfaces": ["COROUTINES", "DOCS", "BUSINESS_LOGIC"], "explanation": {"classification": {
            "COROUTINES": {"files": ["dir with space/A.kt"]},
            "DOCS": {"files": ["README.md"]},
            "BUSINESS_LOGIC": {"files": ["B.kt"]},
        }}}
        mixed_guide = review_reading_guide(mixed_content, "perf-anr-guardian-agent", mixed_policy, mixed_changes)
        self.assertEqual(["dir with space/A.kt"], mixed_guide["focus_files"])

    def test_active_reviews_skips_historical_plans_without_run_or_phase_markers(self):
        import reviewer_host as host
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tasks = root / ".agents/state/tasks"
            for idx in range(5):
                d = tasks / f"old-{idx}"
                d.mkdir(parents=True)
                (d / "plan.json").write_text(json.dumps({"task_id": f"old-{idx}", "status": "DELIVERED"}), encoding="utf-8")
            with mock.patch.object(host, "read_json", wraps=host.read_json) as rj:
                self.assertEqual([], list(host.active_reviews(root)))
                self.assertEqual(0, rj.call_count)

    def test_incremental_type_index_and_cli_notes_deduplication(self):
        import change_classifier as cc
        import task_context as tc
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".agents/cache").mkdir(parents=True)
            src = root / "app/src/main/kotlin/com/example/Item.kt"
            src.parent.mkdir(parents=True)
            src.write_text("package com.example\nclass Item\n", encoding="utf-8")
            idx1 = cc._build_type_file_index(root)
            self.assertIn("Item", idx1)
            self.assertTrue((root / ".agents/cache/source_type_index.json").is_file())
            with mock.patch.object(Path, "read_text", autospec=True, side_effect=Path.read_text) as rt:
                idx2 = cc._build_type_file_index(root)
                self.assertIn("Item", idx2)
                self.assertFalse(any(call.args and call.args[0] == src for call in rt.call_args_list))
            payload = {"project_notes": {"has_custom_notes": True, "sha256": "abc123", "sections": ["Sec1"], "content": "Long notes"}}
            first_out = tc._deduplicate_cli_context_notes(root, payload)
            self.assertEqual("Long notes", first_out["project_notes"].get("content"))
            second_out = tc._deduplicate_cli_context_notes(root, payload)
            self.assertNotIn("content", second_out["project_notes"])
            self.assertTrue(second_out["project_notes"].get("content_omitted"))
            changed_out = tc._deduplicate_cli_context_notes(root, {"project_notes": {**payload["project_notes"], "sha256": "def456"}})
            self.assertEqual("Long notes", changed_out["project_notes"].get("content"))

    def test_phase_review_narrows_unaffected_passing_specialist_on_rerun(self):
        import phase_review as pr
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tdir = root / ".agents/state/tasks/t1"
            hist_dir = tdir / "phases/p1/review-history/phase-p1-11111111"
            hist_dir.mkdir(parents=True)
            weight_p = root / "app/src/main/java/com/example/WeightUseCase.kt"
            auth_p = root / "app/src/main/java/com/example/AuthUseCase.kt"
            weight_p.parent.mkdir(parents=True)
            auth_p.write_text("package com.example\nclass AuthUseCase { fun login() {} }\n", encoding="utf-8")
            weight_p.write_text("package com.example\nclass WeightUseCase { suspend fun save() { kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {} } }\n", encoding="utf-8")
            prev_states = {
                "app/src/main/java/com/example/AuthUseCase.kt": {"exists": True, "sha256": "same-auth"},
                "app/src/main/java/com/example/WeightUseCase.kt": {"exists": True, "sha256": "old-weight"},
            }
            live_states = {
                "app/src/main/java/com/example/AuthUseCase.kt": {"exists": True, "sha256": "same-auth"},
                "app/src/main/java/com/example/WeightUseCase.kt": {"exists": True, "sha256": "new-weight"},
            }
            (hist_dir / "current-phase-run.json").write_text(json.dumps({
                "task_id": "t1",
                "phase_id": "p1",
                "phase_review_run_id": "phase-p1-11111111",
                "package_sha256": "pkg-sha-1",
                "phase_path_states": prev_states,
                "created_at": "2026-10-28T12:00:00Z",
            }), encoding="utf-8")
            (hist_dir / "phase_review_result.json").write_text(json.dumps({
                "schema_version": 2,
                "task_id": "t1",
                "phase_id": "p1",
                "verdict": "FINDINGS",
                "reviewers": {
                    "perf-anr-guardian-agent": {"verdict": "FINDINGS", "findings": [{"id": "perf-001"}]},
                    "security-reviewer-agent": {"verdict": "PASS", "findings": []},
                },
            }), encoding="utf-8")
            rerun, carried = pr._narrow_phase_review_roster(
                root, "t1", "p1", ["perf-anr-guardian-agent", "security-reviewer-agent"], live_states,
            )
            self.assertEqual(["perf-anr-guardian-agent"], rerun)
            self.assertEqual(1, len(carried))
            self.assertEqual("security-reviewer-agent", carried[0]["reviewer"])

    def test_antigravity_unknown_invocation_uses_small_read_only_reminder(self):
        import pre_invocation_reminder as reminder
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO('{}')), mock.patch.object(reminder, "_compact_message", return_value="compact"), \
                mock.patch.object(reminder, "_message", side_effect=AssertionError("full reminder")), \
                mock.patch.object(reminder, "_update_notice", side_effect=AssertionError("network check")), contextlib.redirect_stdout(out):
            reminder.main()
        self.assertEqual("compact", json.loads(out.getvalue())["injectSteps"][0]["ephemeralMessage"])

    def test_antigravity_audit_rotates_by_bytes_and_keeps_latest_record(self):
        import pre_tool_safety as hook
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audit.jsonl"
            with mock.patch.object(hook, "_audit_path", return_value=path), mock.patch.object(hook, "AUDIT_ROTATE_BYTES", 4096):
                for index in range(40):
                    hook._audit("allow", "safe inspection", "view_file", "", reason_code=f"ROW_{index}")
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                self.assertEqual("ROW_39", rows[-1]["reason_code"])
                self.assertLess(path.stat().st_size, 4096)
                with mock.patch.object(Path, "read_text", autospec=True, side_effect=Path.read_text) as read:
                    hook._audit("allow", "safe", "view_file", "")
                self.assertFalse(any(call.args and call.args[0] == path for call in read.call_args_list))


if __name__ == "__main__":
    unittest.main(verbosity=2)
