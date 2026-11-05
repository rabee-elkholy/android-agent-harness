"""Exercise diagnostic source edits and cross-task delivery isolation."""
import json
import os
import sys
from unittest.mock import patch
import subprocess
import tempfile
import unittest
from pathlib import Path

from debug_instrumentation import add, strip, assert_clean
from _vnext_common import ValidationError


class DebugIsolation(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.file = self.repo / "App.kt"
        self.original = b"fun run() {\r\n    submit()\r\n}\r\n"
        self.file.write_bytes(self.original)
        self.plan = {"task_id": "task-a"}
        self.other = {"task_id": "task-b"}

    def test_shared_tree_and_idempotent_strip(self):
        add(self.repo, self.plan, "App.kt", "submit()", True, None, "submit", [], "restore")
        with self.assertRaisesRegex(ValidationError, "task-a.*App.kt"):
            assert_clean(self.repo, self.other)
        edited = self.file.read_bytes().replace(b"submit()", b"submit(1)")
        self.file.write_bytes(edited)
        strip(self.repo, self.plan)
        strip(self.repo, self.plan)
        self.assertEqual(self.original.replace(b"submit()", b"submit(1)"), self.file.read_bytes())
        assert_clean(self.repo, self.other)

    def test_public_add_recovery_and_strip(self):
        task = self.repo / ".agents/state/tasks/task-a"
        task.mkdir(parents=True)
        plan = dict(self.plan, status="IMPLEMENTING", execution_nonce="n",
                    approval={"single_use_nonce": "n"}, plan_id="approved")
        (task / "plan.json").write_text(json.dumps(plan))
        cli = Path(__file__).resolve().parent / "debug_instrumentation.py"
        def command(*args):
            return subprocess.run([sys.executable, str(cli), *args], cwd=self.repo, capture_output=True,
                                  text=True, env={**os.environ, "HARNESS_REPO": str(self.repo)})
        proc = command("add", "--file", "App.kt", "--before", "submit()", "--label", "state")
        self.assertEqual(0, proc.returncode, proc.stderr)
        dest = task / "debug/ledger.json"
        book = json.loads(dest.read_text())
        book["entries"][0]["state"] = "PENDING"
        dest.write_text(json.dumps(book))
        self.assertIn("APPLIED", command("status").stdout)
        proc = command("strip")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual(self.original, self.file.read_bytes())

    def test_manual_marker_and_conflicting_strip(self):
        add(self.repo, self.plan, "App.kt", "submit()", True, None, "state", [], "")
        data = self.file.read_bytes().replace(b" state", b" altered")
        self.file.write_bytes(data)
        self.assertEqual(["App.kt"], strip(self.repo, self.plan))
        self.assertEqual(data, self.file.read_bytes())
        self.file.write_bytes(self.original)
        self.assertEqual([], strip(self.repo, self.plan))
        self.file.write_bytes(self.original + b"// HARNESS-DEBUG manual")
        with self.assertRaisesRegex(ValidationError, "Remove manual marker"):
            assert_clean(self.repo, self.other)

    def test_intervening_editor_write(self):
        from debug_instrumentation import replace_current
        actual = self.original.replace(b"submit()", b"submit(1)")
        self.file.write_bytes(actual)
        with self.assertRaisesRegex(ValidationError, "Source changed"):
            replace_current(self.file, self.original, b"overwrite")
        self.assertEqual(actual, self.file.read_bytes())

    def test_log_window_and_package_attribution(self):
        from debug_device import summarize, read_window
        raw = "\n".join([
            "100.010  5  5 E AndroidRuntime: FATAL EXCEPTION: old",
            "100.011  5  5 E AndroidRuntime: Process: com.test.app, PID: 5",
            "101.003  3  3 E AndroidRuntime: FATAL EXCEPTION: unrelated",
            "101.004  3  3 E AndroidRuntime: Process: com.test.bad, PID: 3",
            "101.005  9  9 E AndroidRuntime: FATAL EXCEPTION: new",
            "101.006  9  9 E AndroidRuntime: Process: com.test.app:remote, PID: 9",
            "101.007  9  9 E AndroidRuntime: Caused by: expected",
            "101.008  9  9 D HarnessDbg: #entry state",
            "101.009  9  9 D HarnessDbg: #entry state",
        ])
        for fallback in [False, True]:
            replies = [ValidationError("unknown option -T"), raw] if fallback else [raw]
            with patch("debug_device.adb", side_effect=replies) as mock:
                text, limited = read_window("serial", "101.000")
            self.assertEqual(limited, fallback)
            self.assertEqual(mock.call_args_list[0].args[-1], "101.000")
            lines = summarize(text, "com.test.app", "101.000", ["entry"], False, 150, None)
            self.assertEqual(lines, ["FATAL EXCEPTION: new", "Process: com.test.app:remote, PID: 9",
                                     "Caused by: expected", "#entry state (x2)"])

    def test_unsafe_values_and_expression_end(self):
        from debug_source import make_insertion
        for value in ("count=queue.remove()", "k=foo[0]", "k=counter++"):
            with self.assertRaises(ValidationError):
                make_insertion(self.original, self.file, "submit()", True, None, "label", [value], "id")
        for code, anchor in [
            ("fun f() {\n    if (\n        ready\n    )\n    submit()\n}\n", "submit()"),
            ("fun f() {\n    when (x) {\n        1 -> submit()\n    }\n}", "1 -> submit()"),
            ("class X {\n    val x = 1\n}", "val x = 1"),
            ("fun f() {\n    /* test\n    submit()\n    */\n}", "submit()"),
        ]:
            with self.subTest(code=code), self.assertRaises(ValidationError):
                make_insertion(code.encode(), self.file, anchor, True, None, "label", [], "id")
        with self.assertRaises(ValidationError):
            make_insertion(self.original, self.file, "submit()", False, None, "label", [], "id")

    def test_apk_identity_and_cache(self):
        from argparse import Namespace
        from debug_device import install
        from artifact_set import build_artifact_set
        task = ":app:assembleDebug"
        paths = [self.repo / name for name in ("base.apk", "split.apk")]
        for p in paths:
            p.write_bytes(p.name.encode())
        artifact = build_artifact_set(self.repo, task, paths, application_id="com.test.app")
        directory = self.repo / "receipt"
        previous = {}
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch("_variants.resolve_assemble_task", return_value=task))
            build = stack.enter_context(patch("run_gradle_task.diagnostic_assemble", return_value=artifact))
            stack.enter_context(patch("debug_device.build_key", side_effect=["first","first","first","second","second","second"]))
            identity = stack.enter_context(patch("debug_device.identity", return_value="confirmed"))
            adb = stack.enter_context(patch("debug_device.adb", return_value="Success"))
            def run():
                return install(self.repo, "serial", "0", "com.test.app", {"entries":[]}, previous,
                               Namespace(allow_downgrade=False), directory)
            previous = run()
            self.assertIn("install-multiple", adb.call_args.args)
            previous = run()
            self.assertTrue(previous["install_skipped"])
            previous = run()
            self.assertEqual(2, build.call_count)
            identity.return_value = "different"
            previous = run()
            self.assertFalse(previous["install_skipped"])
            self.assertEqual(2, build.call_count)
            self.assertEqual(2, adb.call_count)

    def test_verified_reference_must_match_run_device_and_user(self):
        from debug_device import verified_reference
        task = self.repo / ".agents/state/tasks/task-a"
        task.mkdir(parents=True)
        (task / "current-run.json").write_text(json.dumps({"delivery_snapshot_sha256":"snap", "run_id":"run"}))
        # The verifier reads the install and assemble from one immutable run.
        artifact = {"artifact_set_sha256":"digest", "application_id":"com.test", "members":[{"sha256":"apk"}]}
        proof = {"serial_sha256":"serial", "target_user":"10", "application_id":"com.test","artifact_set_sha256":"digest"}
        def read(snapshot, run, name):
            self.assertEqual(("snap","run"), (snapshot, run))
            return {"status":"PASS", "evidence":proof if name == "device_install" else {"artifact_set":artifact}}
        with patch("debug_device.EvidenceStore.read", side_effect=read):
            self.assertEqual(artifact, verified_reference(self.repo,self.plan,"serial","10"))
            self.assertEqual({}, verified_reference(self.repo,self.plan,"serial","0"))
            proof["artifact_set_sha256"] = "wrong"
            self.assertEqual({}, verified_reference(self.repo,self.plan,"serial","10"))

    def test_unbraced_control(self):
        data = b"fun run() {\n    if (ready)\n        submit()\n}\n"
        self.file.write_bytes(data)
        with self.assertRaises(ValidationError):
            add(self.repo, self.plan, "App.kt", "submit()", True, None, "submit", [], "")
        self.assertEqual(data, self.file.read_bytes())


if __name__ == "__main__":
    unittest.main()
