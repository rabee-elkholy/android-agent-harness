"""Hermetic release and upgrade regression tests; no remote mutations."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT / "scripts_dev"))
sys.path.insert(0, str(KIT / "agents/scripts"))
import release_version as release
import validate_release as validation
import _vnext_selftest as fixtures
import lifecycle


class ReleaseSafetyTests(unittest.TestCase):
    def test_version_bump_preserves_citation_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "agents").mkdir()
            (root / "CITATION.cff").write_text('cff-version: 1.2.0\nversion: 1.0.17\n', encoding="utf-8")
            with mock.patch.object(release, "ROOT", root):
                release.update_version_files("1.0.18")
            self.assertEqual('cff-version: 1.2.0\nversion: 1.0.18\n', (root / "CITATION.cff").read_text())

    def test_release_rejects_incomplete_inventory_and_invalid_citation(self):
        original = Path.read_text
        version = (KIT / "agents/VERSION").read_text().strip()
        for filename, replacement, expected in (
            ("release_checksums.json", '{"schema_version":1,"algorithm":"sha256","files":{}}', "inventory"),
            ("CITATION.cff", f'cff-version: {version}\nversion: {version}\n', "cff-version"),
        ):
            with self.subTest(filename=filename):
                def read(path, *args, **kwargs):
                    return replacement if path.name == filename else original(path, *args, **kwargs)
                with mock.patch.object(Path, "read_text", read):
                    errors = validation.validate_release(KIT, version)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_incomplete_findings_cannot_approve_delivery(self):
        original = fixtures.ingest
        def malformed(repo, task, reports):
            for path in reports:
                report = json.loads(path.read_text(encoding="utf-8"))
                report.update(verdict="FINDINGS", findings=[])
                path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(fixtures.ValidationError, "FINDINGS.*non-empty"):
                original(repo, task, reports)
            # A valid neighboring PASS still permits the complete lifecycle.
            for path in reports:
                report = json.loads(path.read_text(encoding="utf-8"))
                report["verdict"] = "PASS"
                path.write_text(json.dumps(report), encoding="utf-8")
            return original(repo, task, reports)
        stream = io.StringIO()
        with mock.patch.object(fixtures, "ingest", malformed):
            result = unittest.TextTestRunner(stream=stream).run(unittest.TestSuite([
                fixtures.EndToEndWorkflowTests("test_approved_change_reaches_delivery_only_with_exact_evidence")
            ]))
        self.assertTrue(result.wasSuccessful(), stream.getvalue())

    def test_upgrade_updates_defaults_preserves_tailoring_and_reports_conflict(self):
        fixture = fixtures.LifecycleTests()
        fixture.setUp()
        try:
            fixture._answers()
            lifecycle.install(fixture.repo, KIT)
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                shutil.copytree(KIT / "agents", target / "agents", ignore=shutil.ignore_patterns("__pycache__", "state", "cache"))
                rel = Path("skills/android-harness/references/performance-and-optimization.md")
                tailored_rel = Path("skills/android-harness/references/test-quality-guidelines.md")
                (target / "agents" / rel).write_text("Updated default guidance.\n", encoding="utf-8")
                (target / "agents" / tailored_rel).write_text("Updated test default.\n", encoding="utf-8")
                custom = fixture.repo / ".agents" / tailored_rel
                custom.write_text("Project-specific test guidance.\n", encoding="utf-8")
                import hashlib
                inventory = json.loads((target / "agents/release_checksums.json").read_text())
                for changed in (rel, tailored_rel):
                    inventory["files"]["agents/" + changed.as_posix()] = hashlib.sha256((target / "agents" / changed).read_bytes()).hexdigest()
                (target / "agents/release_checksums.json").write_text(json.dumps(inventory), encoding="utf-8")
                result = lifecycle.update(fixture.repo, target)
                self.assertEqual("Updated default guidance.\n", (fixture.repo / ".agents" / rel).read_text())
                self.assertEqual("Project-specific test guidance.\n", custom.read_text())
                self.assertIn(".agents/" + tailored_rel.as_posix(), result["preserved_reference_conflicts"])
                # Repeating an update must not silently hide the unresolved conflict.
                repeated = lifecycle.update(fixture.repo, target)
                self.assertIn(".agents/" + tailored_rel.as_posix(), repeated["preserved_reference_conflicts"])
        finally:
            fixture.tearDown()

    def test_workflow_gate_binds_sha_and_rejects_failure_or_absence(self):
        sha = "a" * 40
        base = dict(headSha=sha, status="completed", conclusion="success", databaseId=1)
        for runs, allowed in (([base], True), ([], False),
                              ([dict(base, headSha="b" * 40)], False),
                              ([dict(base, conclusion="failure")], False)):
            with self.subTest(runs=runs), mock.patch.object(release, "run_cmd", return_value=subprocess.CompletedProcess([], 0, json.dumps(runs), "")):
                self.assertEqual(allowed, release.wait_for_workflow("ci.yml", sha, timeout=0))

    def test_packaging_uses_owned_workspace_and_preserves_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("dist", "build", "android_agent_harness.egg-info"):
                (root / name).mkdir()
                (root / name / "sentinel").write_text("keep")
            (root / "pyproject.toml").write_text("[build-system]\n")
            def command(args, **kwargs):
                self.assertNotEqual(root, Path(kwargs["cwd"]))
                if args[2] == "build":
                    output = Path(kwargs["cwd"]) / "dist"
                    output.mkdir()
                    (output / "fixture.whl").write_bytes(b"fixture")
                return subprocess.CompletedProcess(args, 0, "", "")
            with mock.patch.object(release, "ROOT", root), mock.patch.object(release, "run_cmd", side_effect=command):
                self.assertTrue(release.verify_packaging())
            for name in ("dist", "build", "android_agent_harness.egg-info"):
                self.assertEqual("keep", (root / name / "sentinel").read_text())

    def test_publication_failure_is_failure_and_notes_are_a_file(self):
        def command(args, **kwargs):
            self.assertIn("--verify-tag", args)
            notes = Path(args[args.index("--notes-file") + 1])
            self.assertEqual("Line one\n`literal` $text\n", notes.read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(args, 1, "", "HTTP 500")
        with mock.patch.object(release, "run_cmd", side_effect=command):
            self.assertFalse(release.publish_release("v1.0.18", "Title", "Line one\n`literal` $text\n"))

    def test_release_main_never_tags_failed_ci_or_publishes_failed_validation(self):
        from contextlib import ExitStack
        for decisions, expect_tag in (([False], False), ([True, False], True), ([True, True], True)):
            with self.subTest(decisions=decisions), ExitStack() as stack:
                for name, value in (("tag_exists_locally", False), ("tag_remote_status", "ABSENT"),
                                    ("github_release_status", "ABSENT"), ("update_version_files", []),
                                    ("pin_urls", []), ("fill_checksums", []), ("generate_checksums", 0),
                                    ("validate_release", []), ("verify_packaging", True)):
                    stack.enter_context(mock.patch.object(release, name, return_value=value))
                stack.enter_context(mock.patch.object(release.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "OK", "")))
                command = stack.enter_context(mock.patch.object(release, "run_cmd", return_value=subprocess.CompletedProcess([], 0, "a" * 40, "")))
                gate = stack.enter_context(mock.patch.object(release, "wait_for_workflow", side_effect=decisions))
                publish = stack.enter_context(mock.patch.object(release, "publish_release", return_value=False))
                self.assertEqual(1, release.main(["1.0.18"]))
                commands = [call.args[0] for call in command.call_args_list]
                self.assertEqual(expect_tag, any(args[:2] == ["git", "tag"] for args in commands))
                self.assertEqual(len(decisions) == 2 and decisions[-1], publish.called)
                self.assertEqual("ci.yml", gate.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
