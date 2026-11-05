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

class Foo(val d: Date)
"""
        c2 = b"""package com.example

import java.util.Locale

class Foo(val d: Date)
"""
        is_benign, classification, detail = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertFalse(is_benign)
        self.assertEqual("IMPORTS_MODIFIED", classification)
        self.assertIn("removed", detail)

    def test_unused_import_removed_accepted(self):
        c1 = b"""package com.example

import java.util.Locale
import java.util.Date

class Foo {
    fun bar() = Locale.ENGLISH
}
"""
        c2 = b"""package com.example

import java.util.Locale

class Foo {
    fun bar() = Locale.ENGLISH
}
"""
        is_benign, classification, detail = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertTrue(is_benign)
        self.assertEqual("UNUSED_IMPORT_REMOVED", classification)
        self.assertIn("1 removed", detail)

    def test_token_preserving_reformat_accepted(self):
        c1 = b"""package com.example

class Foo {
    fun calc(a: Int, b: Int): Int {
        return a + b
    }
}
"""
        c2 = b"""package com.example

class Foo {
    fun calc(
        a: Int,
        b: Int
    ): Int {
        return a + b
    }
}
"""
        is_benign, classification, _ = classify_file_equivalence(c1, c2, "Foo.kt")
        self.assertTrue(is_benign)
        self.assertEqual("TRAILING_WHITESPACE_OR_FORMATTING", classification)

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

    def test_merge_conflict_task_kind_end_to_end_lifecycle_and_two_parent_delivery(self):
        import argparse
        import subprocess
        from _daily_workflow_selftest import GitDeliveryTests, run_git, write_file
        from _vnext_common import ValidationError, read_json, atomic_write_json
        from delivery_manifest import build_manifest, build_task_manifest, load_task_baseline, unmerged_paths
        from workflow import (
            draft,
            record_approval,
            prepare_verification,
            resolve_next_action,
            deliver_task,
            pre_existing_changes_line,
            _should_record_task_start,
        )

        fixture = GitDeliveryTests("test_GIT_DELIVERY_003_developer_commit_with_identical_content_returns_deliver")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        repo = fixture.repo

        rel_conflict = "app/src/main/kotlin/com/example/MainActivity.kt"
        rel_auto = "app/src/main/kotlin/com/example/AutoMerged.kt"
        write_file(repo / rel_conflict, "package com.example\nclass MainActivity {\n    fun step() = 0\n}\n")
        write_file(repo / rel_auto, "package com.example\nclass AutoMerged {\n    fun base() = 1\n}\n")
        run_git(repo, "add", rel_conflict, rel_auto)
        run_git(repo, "commit", "-qm", "Base before branches diverge")

        # Create incoming branch that modifies both MainActivity.kt and AutoMerged.kt
        run_git(repo, "checkout", "-qb", "features/incoming-solve")
        write_file(
            repo / rel_conflict,
            "package com.example\nclass MainActivity {\n    fun step() = 2\n    fun onIncomingAction() = true\n}\n",
        )
        write_file(
            repo / rel_auto,
            "package com.example\nclass AutoMerged {\n    fun base() = 1\n    fun incomingHelper() = 42\n}\n",
        )
        run_git(repo, "add", rel_conflict, rel_auto)
        run_git(repo, "commit", "-qm", "Incoming branch changes")

        # Return to main branch and make conflicting edit to MainActivity.kt
        run_git(repo, "checkout", "-q", "-")
        write_file(
            repo / rel_conflict,
            "package com.example\nclass MainActivity {\n    fun step() = 1\n    fun onHeadOnboarding() = true\n}\n",
        )
        run_git(repo, "add", rel_conflict)
        run_git(repo, "commit", "-qm", "HEAD onboarding changes")

        # Start git merge that leaves MainActivity.kt in UU conflict and AutoMerged.kt cleanly staged
        merge_proc = subprocess.run(
            ["git", "merge", "--no-commit", "features/incoming-solve"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, merge_proc.returncode, "git merge should report conflict on MainActivity.kt")
        self.assertEqual([rel_conflict], unmerged_paths(repo))

        # Draft with --kind FIX_CONFLICT and without --expected-files (auto-populated from unmerged_paths)
        draft_args = argparse.Namespace(
            repo=str(repo),
            task_id="fix-merge-conflict",
            outcome="Resolve merge conflict between features/incoming-solve and HEAD",
            kind="FIX_CONFLICT",
            planning_depth="BOUNDED",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app",
            expected_files=None,
            test_strategy="Policy-selected relevant tests",
            device_strategy="1. Open MainActivity -> onboarding and incoming actions work",
            approach="Combine onHeadOnboarding and onIncomingAction in MainActivity without dropping either branch",
            risks="Dropping callbacks from either branch",
            rollback="git merge --abort",
            external_write=[],
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            phases=None,
            verification_contract=None,
        )
        plan = draft(draft_args)
        self.assertEqual("CONFLICT", plan["task_kind"])
        self.assertEqual([rel_conflict], plan["expected_files"])
        base = load_task_baseline(repo, "fix-merge-conflict")
        self.assertTrue(base["git_merge_state"]["merge_in_progress"])
        self.assertEqual([rel_conflict], base["git_merge_state"]["unmerged_paths"])
        self.assertIn("MERGE_BASELINE=1 unmerged conflict file(s)", pre_existing_changes_line(repo, plan))

        # Approve task
        approve_args = argparse.Namespace(
            repo=str(repo),
            task_id="fix-merge-conflict",
            source="conversation",
            proof_reference="approve conflict resolution plan",
            enforcement_tier="RULE_ENFORCED",
            plan_hash=plan["plan_sha256"][:12],
        )
        plan = record_approval(approve_args)
        self.assertEqual("IMPLEMENTING", plan["status"])
        self.assertFalse(_should_record_task_start(repo, "fix-merge-conflict", plan))
        next_act = resolve_next_action(repo, "fix-merge-conflict", plan)
        self.assertNotIn("before_first_edit", next_act)

        # Attempting prepare_verification while conflict markers remain MUST fail closed
        prep_args = argparse.Namespace(
            repo=str(repo),
            task_id="fix-merge-conflict",
            host="antigravity",
        )
        with self.assertRaises(ValidationError) as ctx:
            prepare_verification(prep_args)
        self.assertIn("UNRESOLVED_MERGE_CONFLICT", str(ctx.exception))

        # Resolve conflict in working tree WITHOUT running git add (index remains UU)
        resolved_code = (
            "package com.example\n"
            "class MainActivity {\n"
            "    fun step() = 2\n"
            "    fun onHeadOnboarding() = true\n"
            "    fun onIncomingAction() = true\n"
            "}\n"
        )
        write_file(repo / rel_conflict, resolved_code)
        self.assertEqual([rel_conflict], unmerged_paths(repo), "Index is still UU because agent cannot run git add")

        # Task manifest attributes ONLY MainActivity.kt (not AutoMerged.kt) to task_changes
        t_man = build_task_manifest(repo, base, expected_files=plan["expected_files"])
        self.assertEqual([rel_conflict], [c["path"] for c in t_man["task_changes"]])
        pre_commit_snapshot = t_man["delivery_snapshot_sha256"]

        # Prepare verification succeeds now that conflict markers are resolved
        run_info = prepare_verification(prep_args)
        self.assertEqual(pre_commit_snapshot, run_info["delivery_snapshot_sha256"])

        # Seal task to READY_FOR_DELIVERY (simulate verified ready state as in _setup_ready_task)
        from delivery_equivalence import snapshot_verified_files
        tdir = repo / ".agents" / "state" / "tasks" / "fix-merge-conflict"
        plan = read_json(tdir / "plan.json")
        plan["status"] = "READY_FOR_DELIVERY"
        plan["ready_run_id"] = run_info["run_id"]
        plan["ready_delivery_snapshot_sha256"] = run_info["delivery_snapshot_sha256"]
        plan["ready_change_set_sha256"] = run_info["change_set_sha256"]
        atomic_write_json(tdir / "plan.json", plan)
        snapshot_verified_files(repo, "fix-merge-conflict", plan, run_info["run_id"])

        # Developer stages resolved conflict and commits the 2-parent merge commit
        run_git(repo, "add", rel_conflict)
        run_git(repo, "commit", "-qm", "fix(merge): resolve MainActivity conflict")

        # Post-commit delivery_snapshot_sha256 matches pre-commit ready_delivery_snapshot_sha256
        post_commit_manifest = build_manifest(repo)
        self.assertEqual(pre_commit_snapshot, post_commit_manifest["delivery_snapshot_sha256"])

        # Router routes to DELIVER and deliver_task accepts the 2-parent merge commit
        self.assertEqual("DELIVER", resolve_next_action(repo, "fix-merge-conflict", read_json(tdir / "plan.json"))["code"])
        delivered = deliver_task(repo, "fix-merge-conflict", require_clean_tree=True)
        self.assertEqual("DELIVERED", delivered["status"])

    def test_conflict_task_drafted_before_git_merge_backfills_merge_baseline(self):
        """CONFLICT task drafted and approved BEFORE developer runs `git merge` auto-backfills merge baseline."""
        import argparse
        import subprocess
        from _daily_workflow_selftest import GitDeliveryTests, run_git, write_file
        from delivery_manifest import build_task_manifest, load_task_baseline
        from workflow import draft, prepare_verification, record_approval

        fixture = GitDeliveryTests("test_GIT_DELIVERY_003_developer_commit_with_identical_content_returns_deliver")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        repo = fixture.repo

        rel_conflict = "app/src/main/kotlin/com/example/MainActivity.kt"
        rel_auto = "app/src/main/kotlin/com/example/AutoMerged.kt"
        write_file(repo / rel_conflict, "package com.example\nclass MainActivity {\n    fun step() = 1\n}\n")
        write_file(repo / rel_auto, "package com.example\nclass AutoMerged {\n    fun clean() = 1\n}\n")
        run_git(repo, "add", rel_conflict, rel_auto)
        run_git(repo, "commit", "-qm", "merge base")

        run_git(repo, "checkout", "-qb", "features/deferred-branch")
        write_file(repo / rel_conflict, "package com.example\nclass MainActivity {\n    fun step() = 2\n    fun fromFeature() = true\n}\n")
        write_file(repo / rel_auto, "package com.example\nclass AutoMerged {\n    fun clean() = 2\n}\n")
        run_git(repo, "add", rel_conflict, rel_auto)
        run_git(repo, "commit", "-qm", "incoming branch changes")

        run_git(repo, "checkout", "-q", "-")
        write_file(repo / rel_conflict, "package com.example\nclass MainActivity {\n    fun step() = 1\n    fun fromMain() = true\n}\n")
        run_git(repo, "add", rel_conflict)
        run_git(repo, "commit", "-qm", "main branch changes")

        # 1. Draft and approve CONFLICT task BEFORE `git merge` is executed (clean tree)
        draft_args = argparse.Namespace(
            repo=str(repo),
            task_id="deferred-merge",
            outcome="Merge features/deferred-branch into main",
            kind="MERGE",
            planning_depth="BOUNDED",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app",
            expected_files=rel_conflict,
            test_strategy="Policy-selected relevant tests",
            device_strategy="1. Open MainActivity -> verify both methods",
            approach="Run git merge and resolve MainActivity conflict",
            risks="Conflict resolution",
            rollback="git merge --abort",
            external_write=[],
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            phases=None,
            verification_contract=None,
        )
        plan = draft(draft_args)
        approve_args = argparse.Namespace(
            repo=str(repo),
            task_id="deferred-merge",
            source="conversation",
            proof_reference="approve merge plan",
            enforcement_tier="RULE_ENFORCED",
            plan_hash=plan["plan_sha256"][:12],
        )
        plan = record_approval(approve_args)
        self.assertEqual("IMPLEMENTING", plan["status"])

        # 2. Now developer runs `git merge --no-commit features/deferred-branch` in terminal
        merge_proc = subprocess.run(
            ["git", "merge", "--no-commit", "features/deferred-branch"],
            cwd=str(repo), capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(0, merge_proc.returncode)

        # 3. load_task_baseline transparently backfills the merge baseline (AutoMerged.kt + U MainActivity.kt)
        base = load_task_baseline(repo, "deferred-merge")
        self.assertTrue(base["git_merge_state"]["merge_in_progress"])
        base_paths = {c["path"]: c["status"] for c in base["changes"]}
        self.assertEqual("U", base_paths.get(rel_conflict))
        self.assertEqual("M", base_paths.get(rel_auto))

        # 4. Agent resolves MainActivity.kt conflict without touching AutoMerged.kt
        write_file(
            repo / rel_conflict,
            "package com.example\nclass MainActivity {\n    fun step() = 2\n    fun fromMain() = true\n    fun fromFeature() = true\n}\n",
        )
        t_man = build_task_manifest(repo, "deferred-merge")
        self.assertEqual([rel_conflict], [c["path"] for c in t_man["task_changes"]])
        run_info = prepare_verification(argparse.Namespace(repo=str(repo), task_id="deferred-merge", host="antigravity"))
        self.assertTrue(run_info.get("run_id"))


class MergeBoundaryRegressionTests(unittest.TestCase):
    def test_non_git_conflicts_keep_normal_verification(self):
        from workflow import normalize_task_kind
        from review_policy import decide
        for outcome in ("Resolve sync conflict between offline records", "Fix conflict in account data", "Implement conflict resolution"):
            with self.subTest(outcome=outcome):
                kind = normalize_task_kind("AUTO", text_to_scan=outcome)
                self.assertNotEqual("CONFLICT", kind)
                policy = decide({"surfaces": ["AUTH"], "severity": "CRITICAL"},
                                Path(__file__).resolve().parents[1] / "skills", task_kind=kind)
                self.assertTrue(policy["reviewers"])
                self.assertIn("unit_tests", policy["gates"])

    def test_explicit_merge_kind_and_git_evidence_still_classify(self):
        from unittest.mock import patch
        from _workflow.engine import normalize_task_kind
        for kind in ("CONFLICT", "FIX_CONFLICT", "MERGE"):
            self.assertEqual("CONFLICT", normalize_task_kind(kind))
        with patch("_workflow.engine.unmerged_paths", return_value=["Main.kt"]):
            self.assertEqual("CONFLICT", normalize_task_kind("AUTO", Path.cwd()))

    def test_loading_other_task_does_not_backfill_merge(self):
        from unittest.mock import patch
        import delivery_manifest as manifest
        from _vnext_common import atomic_write_json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / ".agents/state/tasks/feature"
            directory.mkdir(parents=True)
            baseline_path = directory / "task-baseline.json"
            plan_path = directory / "plan.json"
            atomic_write_json(baseline_path, {"task_id": "feature", "changes": []})
            atomic_write_json(plan_path, {"task_kind": "FEATURE", "expected_files": ["feature.kt"]})
            before = (baseline_path.read_bytes(), plan_path.read_bytes())
            with patch.object(manifest, "git_merge_in_progress", return_value={
                "merge_in_progress": True, "merge_head": "a" * 40, "unmerged_paths": ["other.kt"],
            }), patch.object(manifest, "build_manifest", return_value={"changes": [
                {"path": "other.kt", "status": "U", "content_identity": "git:original"},
            ]}), patch.object(manifest, "_index_and_untracked", return_value=({}, {}, set())):
                manifest.load_task_baseline(root, "feature")
            self.assertEqual(before, (baseline_path.read_bytes(), plan_path.read_bytes()))

    def test_conflict_contract_preserves_required_gates(self):
        from unittest.mock import patch
        import review_policy
        for method in ("test", "manual", "review"):
            with self.subTest(method=method), patch.object(review_policy, "_configured_device_verification_mode", return_value="required"):
                contract = {"schema_version": 1, "criteria": [{"id": "required-check", "expected": "Preserve behavior",
                            "method": method, "required": True}], "journeys": []}
                policy = review_policy.decide({"surfaces": ["BUSINESS_LOGIC"], "severity": "MEDIUM"},
                    Path(__file__).resolve().parents[1] / "skills", task_kind="CONFLICT",
                    plan={"task_kind": "CONFLICT", "verification_contract": contract})
                if method == "test":
                    self.assertIn("unit_tests", policy["gates"])
                elif method == "manual":
                    self.assertTrue(policy["device_required"])
                    self.assertTrue({"device", "assemble"} <= set(policy["gates"]))
                else:
                    self.assertEqual(["bug-test-reviewer-agent"], policy["reviewers"])
                    self.assertEqual("REQUIRED", policy["review_status"])
                    self.assertIsNone(policy["explanation"]["review_exemption"])

    def test_unreceipted_merge_is_not_valid_lineage(self):
        import subprocess
        from _vnext_common import atomic_write_json
        from task_git_lineage import is_valid_task_lineage, compute_receipt_sha, validate_checkpoint_receipt
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            git("config", "user.name", "Harness Test")
            git("config", "user.email", "harness@example.invalid")
            (root / "base.txt").write_text("base", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "Base")
            base = git("rev-parse", "HEAD")
            branch = git("branch", "--show-current")
            git("checkout", "-qb", "unrelated")
            (root / "outside.txt").write_text("unrelated", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "Unrelated")
            incoming = git("rev-parse", "HEAD")
            git("checkout", "-q", branch)
            git("merge", "--no-ff", "-m", "Unrequested merge", "unrelated")
            directory = root / ".agents/state/tasks/merge-task"
            atomic_write_json(directory / "plan.json", {"task_id": "merge-task", "task_kind": "CONFLICT",
                "task_base_head": base, "expected_files": ["base.txt"], "plan_sha256": "approved-plan"})
            head = git("rev-parse", "HEAD")
            valid, _ = is_valid_task_lineage(root, "merge-task", head)
            self.assertFalse(valid)
            receipt = {"kind": "REQUESTED_DELIVERY_COMMIT", "merge_delivery": True,
                "task_id": "merge-task", "task_base_head": base, "parent_head": base,
                "checkpoint_head": head, "plan_sha256": "approved-plan"}
            receipt["receipt_sha256"] = compute_receipt_sha(receipt)
            receipt_path = directory / "git-checkpoints" / (head + ".json")
            atomic_write_json(receipt_path, receipt)
            for recorded, expected in ((base, False), (incoming, True)):
                atomic_write_json(directory / "task-baseline.json", {"task_id": "merge-task", "changes": [],
                    "git_merge_state": {"merge_in_progress": True, "merge_head": recorded}})
                self.assertEqual(expected, validate_checkpoint_receipt(root, "merge-task", base, receipt_path, set())[0])
            # Even a receipt must not authorize an extra (octopus) parent.
            extra = git("commit-tree", head + "^{tree}", "-p", base, "-m", "Extra parent")
            octopus = git("commit-tree", head + "^{tree}", "-p", base, "-p", incoming, "-p", extra, "-m", "Octopus")
            receipt["checkpoint_head"] = octopus
            receipt["receipt_sha256"] = compute_receipt_sha(receipt)
            octopus_path = receipt_path.with_name(octopus + ".json")
            atomic_write_json(octopus_path, receipt)
            self.assertFalse(validate_checkpoint_receipt(root, "merge-task", base, octopus_path, set())[0])

    def test_raw_string_and_backtick_test_name_allow_unused_import_removal_only(self):
        before = (
            b"package com.example\n\n"
            b"import com.example.auth.LoginResponse\n"
            b"import org.junit.Test\n\n"
            b"class FoodPlanViewModelTest {\n"
            b"    @Test\n"
            b"    fun `trainingDays object contract syncs across LoginResponse and cache`() {\n"
            b'        val fixture = """\n'
            b'            {"training_days": "3_days"}\n'
            b'        """.trimIndent()\n'
            b"    }\n"
            b"}\n"
        )
        after = (
            b"package com.example\n\n"
            b"import org.junit.Test\n\n"
            b"class FoodPlanViewModelTest {\n"
            b"    @Test\n"
            b"    fun `trainingDays object contract syncs across LoginResponse and cache`() {\n"
            b'        val fixture = """\n'
            b'            {"training_days": "3_days"}\n'
            b'        """.trimIndent()\n'
            b"    }\n"
            b"}\n"
        )
        self.assertEqual(
            (True, "UNUSED_IMPORT_REMOVED"),
            classify_file_equivalence(before, after, "app/src/test/java/com/example/FoodPlanViewModelTest.kt")[:2],
        )
        # Any whitespace or content edit inside the raw string must still fail closed.
        modified_raw = after.replace(b'{"training_days": "3_days"}', b'{"training_days":  "3_days"}')
        self.assertEqual(
            (False, "BODY_MODIFIED"),
            classify_file_equivalence(before, modified_raw, "app/src/test/java/com/example/FoodPlanViewModelTest.kt")[:2],
        )

    def test_external_user_doc_allows_desktop_when_home_has_global_agents_dir(self):
        from unittest.mock import patch
        import pre_tool_safety
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "Users" / "dev"
            (fake_home / ".agents").mkdir(parents=True)
            desktop_doc = fake_home / "Desktop" / "notes.md"
            desktop_doc.parent.mkdir(parents=True)
            desktop_doc.write_text("# Notes\n", encoding="utf-8")
            nested_repo_doc = fake_home / "Desktop" / "nested_repo" / "notes.md"
            (nested_repo_doc.parent / ".git").mkdir(parents=True)
            nested_repo_doc.write_text("# Repo Notes\n", encoding="utf-8")
            with patch.object(Path, "home", return_value=fake_home):
                self.assertTrue(pre_tool_safety._is_external_user_doc(desktop_doc, desktop_doc.resolve()))
                self.assertFalse(pre_tool_safety._is_external_user_doc(nested_repo_doc, nested_repo_doc.resolve()))


if __name__ == "__main__":
    unittest.main()
