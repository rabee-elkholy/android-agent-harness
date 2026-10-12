"""Unit tests for delivery_equivalence.py module."""
import shutil
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from delivery_equivalence import (
    classify_file_equivalence,
    evaluate_post_ready_changes,
)


class DeliveryEquivalenceTests(unittest.TestCase):
    def test_identical_bytes(self):
        content = b"package com.example\n\nclass Foo\n"
        is_benign, classification, _ = classify_file_equivalence(content, content, "Foo.kt")
        self.assertTrue(is_benign)
        self.assertEqual("IDENTICAL", classification)

    def test_line_endings_only(self):
        c1 = b"package com.example\r\n\r\nclass Foo\r\n"
        c2 = b"package com.example\n\nclass Foo\n"
        is_benign, classification, _ = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertTrue(is_benign)
        self.assertEqual("LINE_ENDINGS_ONLY", classification)

    def test_kotlin_import_reorder_accepted(self):
        c1 = b"""package com.example

import java.util.Locale
import kotlinx.coroutines.Dispatchers
import javax.inject.Inject

class Foo {
    fun bar() = Locale.ENGLISH
}
"""
        # IDE reorders alphabetically: javax, java, kotlinx
        c2 = b"""package com.example

import java.util.Locale
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers

class Foo {
    fun bar() = Locale.ENGLISH
}
"""
        is_benign, classification, detail = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertTrue(is_benign)
        self.assertEqual("IMPORT_REORDER", classification)
        self.assertIn("3 imports preserved", detail)

    def test_java_import_reorder_accepted(self):
        c1 = b"""package com.example;

import java.util.List;
import java.util.ArrayList;
import java.util.Collections;

public class Bar {
    private List<String> list = new ArrayList<>();
}
"""
        c2 = b"""package com.example;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class Bar {
    private List<String> list = new ArrayList<>();
}
"""
        is_benign, classification, _ = classify_file_equivalence(c1, c2, "Bar.java")
        self.assertTrue(is_benign)
        self.assertEqual("IMPORT_REORDER", classification)

    def test_import_added_rejected(self):
        c1 = b"""package com.example

import java.util.Locale

class Foo
"""
        c2 = b"""package com.example

import java.util.Locale
import java.util.Date

class Foo
"""
        is_benign, classification, detail = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertFalse(is_benign)
        self.assertEqual("IMPORTS_MODIFIED", classification)
        self.assertIn("added", detail)

    def test_import_removed_rejected(self):
        c1 = b"""package com.example

import java.util.Locale
import java.util.Date

class Foo
"""
        c2 = b"""package com.example

import java.util.Locale

class Foo
"""
        is_benign, classification, detail = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertFalse(is_benign)
        self.assertEqual("IMPORTS_MODIFIED", classification)
        self.assertIn("removed", detail)

    def test_code_body_modified_rejected(self):
        c1 = b"""package com.example

import java.util.Locale

class Foo {
    fun calc() = 1
}
"""
        c2 = b"""package com.example

import java.util.Locale

class Foo {
    fun calc() = 2
}
"""
        is_benign, classification, _ = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertFalse(is_benign)
        self.assertEqual("BODY_MODIFIED", classification)

    def test_code_body_comment_added_rejected(self):
        c1 = b"""package com.example

import java.util.Locale

class Foo
"""
        c2 = b"""package com.example

import java.util.Locale

// added comment
class Foo
"""
        is_benign, classification, _ = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertFalse(is_benign)
        self.assertEqual("BODY_MODIFIED", classification)

    def test_multiline_raw_string_whitespace_change_rejected(self):
        c1 = b'''package com.example

val msg = """
hello    
world
"""
'''
        # Trailing spaces after 'hello' stripped
        c2 = b'''package com.example

val msg = """
hello
world
"""
'''
        is_benign, classification, _ = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertFalse(is_benign)
        self.assertEqual("BODY_MODIFIED", classification)

    def test_trailing_whitespace_on_safe_suffix_accepted(self):
        c1 = b"val x = 1   \nval y = 2\n"
        c2 = b"val x = 1\nval y = 2\n\n"
        is_benign, classification, _ = classify_file_equivalence(c1, c2, "build.gradle.kts")
        self.assertTrue(is_benign)
        self.assertEqual("TRAILING_WHITESPACE_OR_EOF_NEWLINE", classification)

    def test_xml_whitespace_modification_rejected(self):
        c1 = b"<resources>\n    <string name=\"app_name\">App   </string>\n</resources>\n"
        c2 = b"<resources>\n    <string name=\"app_name\">App</string>\n</resources>\n"
        is_benign, classification, _ = classify_file_equivalence(c1, c2, "strings.xml")
        self.assertFalse(is_benign)
        self.assertEqual("CONTENT_MODIFIED", classification)

    def test_snapshot_verified_files_and_evaluate(self):
        # A real frozen manifest is required; fake Git OIDs cannot certify delivery.
        from _daily_workflow_selftest import GitDeliveryTests, write_file
        from delivery_manifest import build_manifest
        fixture = GitDeliveryTests("test_GIT_DELIVERY_003_developer_commit_with_identical_content_returns_deliver")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        plan, directory = fixture._setup_ready_task("test-task-eq", content="package com.example\n\nimport b.B\nimport a.A\n\nclass Foo\n")
        rel = plan["expected_files"][0]
        write_file(fixture.repo / rel, "package com.example\n\nimport a.A\nimport b.B\n\nclass Foo\n")
        result = evaluate_post_ready_changes(fixture.repo, plan["task_id"], plan, build_manifest(fixture.repo))
        self.assertTrue(result["is_benign"])
        self.assertEqual("IMPORT_REORDER", result["normalized_files"][0]["classification"])
        write_file(fixture.repo / rel, "package com.example\n\nimport a.A\nimport b.B\n\nclass Foo { val x = 1 }\n")
        result = evaluate_post_ready_changes(fixture.repo, plan["task_id"], plan, build_manifest(fixture.repo))
        self.assertFalse(result["is_benign"])
        self.assertIn("BODY_MODIFIED", result["reason"])
        stored = directory / "verified-files" / plan["ready_run_id"] / rel
        stored.write_bytes(b"tampered")
        result = evaluate_post_ready_changes(fixture.repo, plan["task_id"], plan, build_manifest(fixture.repo))
        self.assertFalse(result["is_benign"])
        self.assertIn("VERIFIED_FILE_INTEGRITY_MISMATCH", result["reason"])

    def test_change_classifier_line_endings_robustness(self):
        import subprocess
        tmp_dir = tempfile.mkdtemp(prefix="test_diff_eol_")
        try:
            repo = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), capture_output=True, check=True)
            subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=str(repo), capture_output=True, check=True)

            kt_dir = repo / "app/src/main/java/com/example"
            kt_dir.mkdir(parents=True)
            kt_file = kt_dir / "SampleFragment.kt"

            # Create file with CRLF line endings, referencing BillingClient in an unedited method
            initial_content = (
                "package com.example\r\n\r\n"
                "import com.android.billingclient.api.BillingClient\r\n\r\n"
                "class SampleFragment {\r\n"
                "    fun uneditedBillingMethod() {\r\n"
                "        val client: BillingClient? = null\r\n"
                "    }\r\n"
                "    fun targetMethod() {\r\n"
                "        val count = 1\r\n"
                "    }\r\n"
                "}\r\n"
            )
            kt_file.write_bytes(initial_content.encode("utf-8"))
            subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=str(repo), capture_output=True, check=True)

            # Now edit ONLY targetMethod, and save the file with LF line endings
            modified_content = (
                "package com.example\n\n"
                "import com.android.billingclient.api.BillingClient\n\n"
                "class SampleFragment {\n"
                "    fun uneditedBillingMethod() {\n"
                "        val client: BillingClient? = null\n"
                "    }\n"
                "    fun targetMethod() {\n"
                "        val count = 2\n"
                "    }\n"
                "}\n"
            )
            kt_file.write_bytes(modified_content.encode("utf-8"))

            from change_classifier import classify, _changed_line_count, changed_files
            changes = changed_files(repo)
            count = _changed_line_count(repo, changes)
            # With --ignore-cr-at-eol, only 2 lines changed (+1 / -1), NOT the entire file (12 lines)
            self.assertLessEqual(count, 3)

            # And classify on the diff should NOT see BillingClient in the modified diff!
            res = classify(repo, progress=False)
            self.assertNotIn("BILLING", res.get("surfaces", []))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_approval_brief_includes_sensitive_advisory(self):
        from workflow import approval_brief
        plan = {
            "requested_outcome": "Fix button color",
            "expected_files": ["app/src/main/java/com/example/SampleFragment.kt"],
            "expected_surfaces": ["RESOURCE_UI"],
        }
        brief_plain = approval_brief(plan)
        self.assertNotIn("Pre-existing sensitive code:", brief_plain)

        advisory = "SENSITIVE_PLANNED_FILES=BILLING: app/src/main/java/com/example/SampleFragment.kt. These planned files already contain that code."
        brief_with_advisory = approval_brief(plan, sensitive_advisory=advisory)
        self.assertIn("- Pre-existing sensitive code: BILLING: app/src/main/java/com/example/SampleFragment.kt (add to plan only if your change touches it)", brief_with_advisory)


class DeliverySafetyRegressionTests(unittest.TestCase):
    """Exercise the post-ready public delivery seam with isolated ready-state fixtures."""

    def test_import_like_raw_string_and_commented_import_are_not_equivalent(self):
        pairs = [
            (b'package example\nval text = """\nimport b.B\nimport a.A\n"""\n',
             b'package example\nval text = """\nimport a.A\nimport b.B\n"""\n'),
            (b'package example\nimport a.A\n/*\nimport b.B\n*/\nimport c.C\nclass Foo(val x: B)\n',
             b'package example\nimport a.A\nimport b.B\nimport c.C\nclass Foo(val x: B)\n'),
        ]
        for before, after in pairs:
            with self.subTest(before=before):
                self.assertFalse(classify_file_equivalence(before, after, "Foo.kt")[0])

    def test_data_and_multiline_literals_preserve_bytes(self):
        pairs = [
            ("settings.properties", b"name=User  \n", b"name=User\n"),
            ("program.py", b"text = '''\nhello  \n'''\n", b"text = '''\nhello\n'''\n"),
            ("assets/image.dat", b"\x89PNG\r\n\x1a\n", b"\x89PNG\n\x1a\n"),
            ("strings.xml", b"<string>\r\nvalue\r\n</string>", b"<string>\nvalue\n</string>"),
            ("app/src/main/assets/policy.kt", b"name=User  \n", b"name=User\n"),
            ("module/src/test/resources/Fixture.java", b"value\r\n", b"value\n"),
        ]
        for path, before, after in pairs:
            with self.subTest(path=path):
                self.assertFalse(classify_file_equivalence(before, after, path)[0])

    def test_supported_import_prefix_preserves_comments_aliases_and_multiplicity(self):
        before = b"/* License */\npackage example\n\nimport b.B as Bee\nimport a.A\n\n/** Documentation */\nclass Foo\n"
        after = b"/* License */\npackage example\n\nimport a.A\nimport b.B as Bee\n\n/** Documentation */\nclass Foo\n"
        self.assertEqual((True, "IMPORT_REORDER"), classify_file_equivalence(before, after, "Foo.kt")[:2])
        for changed in (after.replace(b"Documentation", b"Different documentation"),
                        after.replace(b"import a.A\n", b"import a.A\nimport a.A\n"),
                        after.replace(b"import a.A", b"import a.*")):
            self.assertFalse(classify_file_equivalence(before, changed, "Foo.kt")[0])

    def test_capture_is_bound_to_frozen_tree_and_cannot_recertify_new_content(self):
        from _daily_workflow_selftest import write_file
        from _vnext_common import ValidationError
        from delivery_equivalence import snapshot_verified_files
        fixture, plan, directory = self._fixture("safe-capture")
        # Retrying the same capture is idempotent; it never overwrites sealed files.
        snapshot_verified_files(fixture.repo, plan["task_id"], plan, plan["ready_run_id"])
        original = (directory / "verified-files" / plan["ready_run_id"] / plan["expected_files"][0]).read_bytes()
        write_file(fixture.repo / plan["expected_files"][0], "package com.example\nclass MainActivity { fun auth() = false }\n")
        with self.assertRaises(ValidationError):
            snapshot_verified_files(fixture.repo, plan["task_id"], plan, plan["ready_run_id"])
        self.assertEqual(original, (directory / "verified-files" / plan["ready_run_id"] / plan["expected_files"][0]).read_bytes())

    def _fixture(self, task_id):
        from _daily_workflow_selftest import GitDeliveryTests
        fixture = GitDeliveryTests("test_GIT_DELIVERY_003_developer_commit_with_identical_content_returns_deliver")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        plan, directory = fixture._setup_ready_task(task_id)
        return fixture, plan, directory

    def test_missing_cache_never_captures_post_ready_auth_edit(self):
        from _daily_workflow_selftest import run_git, write_file
        from workflow import resolve_next_action, deliver_task
        from _vnext_common import ValidationError
        fixture, plan, directory = self._fixture("safe-missing-cache")
        for path in (directory / "verified-files").rglob("verified-files-manifest.json"):
            path.unlink()
        rel = plan["expected_files"][0]
        write_file(fixture.repo / rel, "package com.example\nclass MainActivity { fun auth() = false }\n")
        self.assertEqual("DELIVERY_STALE_AFTER_COMMIT", resolve_next_action(fixture.repo, plan["task_id"], plan)["code"])
        self.assertFalse(list((directory / "verified-files").rglob("verified-files-manifest.json")))
        run_git(fixture.repo, "add", rel)
        run_git(fixture.repo, "commit", "-qm", "Fixture auth edit")
        self.assertEqual("DELIVERY_STALE_AFTER_COMMIT", resolve_next_action(fixture.repo, plan["task_id"], plan)["code"])
        with self.assertRaises(ValidationError):
            deliver_task(fixture.repo, plan["task_id"])

    def test_cache_identity_and_required_hash_fail_closed(self):
        from _daily_workflow_selftest import run_git, write_file
        from _vnext_common import read_json, atomic_write_json
        from workflow import resolve_next_action, deliver_task
        from _vnext_common import ValidationError
        fixture, plan, directory = self._fixture("safe-cache-identity")
        rel = plan["expected_files"][0]
        target = fixture.repo / rel
        write_file(target, target.read_text() + "\n")
        run_git(fixture.repo, "add", rel)
        run_git(fixture.repo, "commit", "-qm", "Fixture EOF newline")
        cache = next((directory / "verified-files").rglob("verified-files-manifest.json"))
        original = read_json(cache)
        for field, value in (("task_id", "other-task"), ("run_id", "other-run"), ("schema_version", 999)):
            data = dict(original, **{field: value})
            atomic_write_json(cache, data)
            with self.subTest(field=field):
                self.assertEqual("DELIVERY_STALE_AFTER_COMMIT", resolve_next_action(fixture.repo, plan["task_id"], plan)["code"])
                with self.assertRaises(ValidationError):
                    deliver_task(fixture.repo, plan["task_id"])
        data = read_json(cache)
        data.update(original)
        data["files"][rel].pop("sha256")
        atomic_write_json(cache, data)
        from delivery_manifest import build_manifest
        self.assertFalse(evaluate_post_ready_changes(fixture.repo, plan["task_id"], plan, build_manifest(fixture.repo))["is_benign"])

    def test_git_mode_change_is_not_benign(self):
        import os
        from _daily_workflow_selftest import run_git
        from workflow import resolve_next_action, deliver_task
        from _vnext_common import git_text, ValidationError
        fixture, plan, _directory = self._fixture("safe-file-mode")
        rel = plan["expected_files"][0]
        if os.name != "nt":
            # Match the committed mode on hosts that track filesystem execute bits.
            target = fixture.repo / rel
            target.chmod(target.stat().st_mode | 0o111)
        run_git(fixture.repo, "add", rel)
        run_git(fixture.repo, "update-index", "--chmod=+x", rel)
        run_git(fixture.repo, "commit", "-qm", "Fixture mode change")
        self.assertEqual("", git_text(fixture.repo, "status", "--porcelain", "--", rel))
        self.assertEqual("DELIVERY_STALE_AFTER_COMMIT", resolve_next_action(fixture.repo, plan["task_id"], plan)["code"])
        with self.assertRaises(ValidationError):
            deliver_task(fixture.repo, plan["task_id"])

    def test_git_symlink_stored_as_text_cannot_normalize_its_target(self):
        from _daily_workflow_selftest import GitDeliveryTests, run_git, write_file
        from _vnext_common import git_text, ValidationError
        from workflow import resolve_next_action, deliver_task
        fixture = GitDeliveryTests("test_GIT_DELIVERY_003_developer_commit_with_identical_content_returns_deliver")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        run_git(fixture.repo, "config", "core.symlinks", "false")
        rel = "app/src/main/kotlin/com/example/MainActivity.kt"
        write_file(fixture.repo / rel, b"Target.kt")
        oid = git_text(fixture.repo, "hash-object", "-w", "--stdin", input_bytes=b"Target.kt")
        run_git(fixture.repo, "update-index", "--cacheinfo", "120000", oid, rel)
        run_git(fixture.repo, "commit", "-qm", "Fixture Git symlink stored as text")
        plan, _directory = fixture._setup_ready_task("safe-symlink-text", content="Target.kt")
        self.assertEqual("DELIVER", resolve_next_action(fixture.repo, plan["task_id"], plan)["code"])
        # This is a different link target, even though the host exposes a text file.
        write_file(fixture.repo / rel, b"Target.kt ")
        run_git(fixture.repo, "add", rel)
        run_git(fixture.repo, "commit", "-qm", "Fixture changed symlink target")
        self.assertEqual("DELIVERY_STALE_AFTER_COMMIT", resolve_next_action(fixture.repo, plan["task_id"], plan)["code"])
        with self.assertRaises(ValidationError):
            deliver_task(fixture.repo, plan["task_id"])

    def test_baseline_diff_preserves_eof_and_unicode_line_separators(self):
        from _daily_workflow_selftest import write_file
        from delivery_manifest import build_task_diff
        from phase_review import _compute_phase_diff
        fixture, plan, directory = self._fixture("safe-baseline-diff")
        rel = plan["expected_files"][0]
        write_file(directory / "baseline-files" / rel, b"class Foo")
        write_file(fixture.repo / rel, b"class Foo\n")
        diff = build_task_diff(fixture.repo, plan["task_id"], {"task_changes": [{"path": rel, "status": "M"}]})
        self.assertTrue(diff, "EOF newline changes must remain visible to reviewers")
        new_rel = "app/src/main/kotlin/New.kt"
        write_file(fixture.repo / new_rel, 'val text = "a\u2028b"\n')
        self.assertIn("\u2028", _compute_phase_diff(fixture.repo, [new_rel]))
        self.assertIn("\u2028", build_task_diff(fixture.repo, plan["task_id"], {"task_changes": [{"path": new_rel, "status": "A"}]}))

    def test_diff_preserves_literal_whitespace_and_eol_only_selects_no_lines(self):
        from _daily_workflow_selftest import run_git, write_file
        from fast_kt_lint import get_modified_lines_map, lint_file
        from check_strings import _get_modified_lines_map
        from delivery_manifest import build_manifest, build_task_diff
        from change_classifier import changed_files, _diff_content
        from phase_review import _compute_phase_diff
        from review_package import _git_diff
        fixture, _plan, _directory = self._fixture("safe-diff")
        rel = "app/src/main/kotlin/com/example/features/results/Results.kt"
        target = fixture.repo / rel
        run_git(fixture.repo, "config", "core.autocrlf", "false")
        content = b'package example\r\nimport example.features.billing.StreakEventManager\r\nval text = """\r\nhello  \r\n"""\r\n'
        write_file(target, content)
        run_git(fixture.repo, "add", rel)
        run_git(fixture.repo, "commit", "-qm", "Fixture raw string")
        write_file(target, content.replace(b"\r\n", b"\n"))
        self.assertEqual(set(), get_modified_lines_map(fixture.repo, [target])[target])
        self.assertEqual(set(), _get_modified_lines_map([target], fixture.repo)[target])
        self.assertFalse(lint_file(target, set()))
        write_file(target, content.replace(b"hello  ", b"hello"))
        changed = next(item for item in changed_files(fixture.repo) if item.rel_posix == rel)
        self.assertIn("hello", _diff_content(fixture.repo, changed)[0])
        for diff in (_git_diff(fixture.repo, [rel]), _compute_phase_diff(fixture.repo, [rel]), build_task_diff(fixture.repo, build_manifest(fixture.repo))):
            self.assertIn("-hello  ", diff)
            self.assertIn("+hello", diff)


if __name__ == "__main__":
    unittest.main()
