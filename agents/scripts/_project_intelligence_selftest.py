"""Deterministic acceptance tests for advisory Project Intelligence and Task Context."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import project_context  # noqa: E402
from _graph_core import GraphEngine  # noqa: E402
from generate_project_context import summarize_preview  # noqa: E402
from project_context import (  # noqa: E402
    ContextSourceChangedDuringExtraction,
    extract_consistent_project_context,
    extract_project_facts,
    validate_advisory_knowledge,
    write_project_context,
)
from task_context import resolve_task_context  # noqa: E402


class ProjectIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="project_intelligence_")
        self.repo = Path(self.temp.name)
        self.write("settings.gradle.kts", 'include(":app", ":feature:profile")\n')
        self.write("app/build.gradle.kts", 'plugins { id("com.android.application") }\n')
        self.write("feature/profile/build.gradle.kts", 'plugins { id("com.android.library") }\n')

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def mixed_project(self) -> None:
        self.write(
            "feature/profile/src/main/java/com/example/profile/ProfileContract.java",
            "package com.example.profile; interface ProfileContract { interface View {} }",
        )
        self.write(
            "feature/profile/src/main/java/com/example/profile/ProfilePresenter.java",
            "package com.example.profile; class ProfilePresenter { ProfileContract.View view; void load(Callback callback) {} }",
        )
        self.write(
            "feature/profile/src/main/java/com/example/profile/ProfileFragment.java",
            "package com.example.profile; class ProfileFragment extends Fragment { Object binding; ComposeView composeView; }",
        )
        self.write(
            "app/src/main/kotlin/com/example/home/HomeScreen.kt",
            "package com.example.home\n@Composable fun HomeScreen() {}\nclass HomeViewModel : ViewModel() { val state: StateFlow<UiState>; fun onAction() {} }",
        )

    def test_advisory_profiles_include_java_mvp_and_mixed_ui(self) -> None:
        self.mixed_project()
        payload = extract_project_facts(self.repo)
        valid, reason = validate_advisory_knowledge(payload)
        self.assertTrue(valid, reason)
        profiles = payload["advisory_knowledge"]["local_profiles"]
        profile = next(item for item in profiles if item["logical_scope"] == "com.example.profile")
        self.assertIn("java", profile["languages"])
        self.assertEqual("presenter_contract", profile["presentation_pattern"])
        self.assertEqual(["XML_HOSTS_COMPOSE"], profile["interop"])
        self.assertEqual(["xml", "compose"], profile["ui_toolkits"])

    def test_default_preview_is_bounded_and_omits_profile_bodies(self) -> None:
        self.mixed_project()
        payload = extract_project_facts(self.repo)
        summary = summarize_preview(payload)
        self.assertNotIn("facts", summary)
        self.assertNotIn("advisory_knowledge", summary)
        self.assertLessEqual(len(summary["summary"]["representative_families"]), 8)
        self.assertTrue(summary["full_payload_available"])

    def test_authoritative_family_ids_do_not_depend_on_advisory_block(self) -> None:
        self.mixed_project()
        payload = extract_project_facts(self.repo)
        family_ids = [item["id"] for item in payload["facts"]["architecture"]["families"]]
        without_advisory = dict(payload)
        without_advisory.pop("advisory_knowledge")
        self.assertEqual(payload["context_fingerprint_sha256"], project_context.project_context_fingerprint(without_advisory))
        self.assertEqual(family_ids, [item["id"] for item in without_advisory["facts"]["architecture"]["families"]])

    def test_old_schema_v2_without_advisory_is_compatible(self) -> None:
        payload = {"schema_version": 2, "facts": {"architecture": {"families": []}}}
        self.assertEqual((False, "MISSING"), validate_advisory_knowledge(payload))

    def test_duplicate_fqn_is_ambiguous_but_qualified_identity_resolves(self) -> None:
        source = "package com.example.shared\nclass SharedPresenter {}\n"
        self.write("app/src/main/kotlin/com/example/shared/SharedPresenter.kt", source)
        self.write("feature/profile/src/debug/kotlin/com/example/shared/SharedPresenter.kt", source)
        result = resolve_task_context(self.repo, symbol="com.example.shared.SharedPresenter")
        self.assertEqual("AMBIGUOUS", result["status"])
        self.assertEqual(2, len(result["candidates"]))
        qualified = resolve_task_context(
            self.repo,
            symbol="com.example.shared.SharedPresenter",
            module=":feature:profile",
            source_set="debug",
        )
        self.assertEqual("RESOLVED", qualified["status"])
        self.assertEqual("debug", qualified["target"]["source_set"])

    def test_exact_path_wins_and_resolution_does_not_persist_graph_cache(self) -> None:
        path = self.write("app/src/main/kotlin/com/example/ExactTarget.kt", "package com.example\nclass ExactTarget {}")
        cache = self.repo / ".agents/cache/project_graph.json"
        result = resolve_task_context(self.repo, file=str(path))
        self.assertEqual("RESOLVED", result["status"])
        self.assertEqual("app/src/main/kotlin/com/example/ExactTarget.kt", result["target"]["path"])
        self.assertFalse(cache.exists())

    def test_external_path_and_symlink_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="outside_target_") as outside:
            external = Path(outside) / "External.kt"
            external.write_text("class External", encoding="utf-8")
            result = resolve_task_context(self.repo, file=str(external))
            self.assertEqual("INVALID_TARGET_PATH", result["status"])
            link = self.repo / "External.kt"
            try:
                link.symlink_to(external)
            except OSError:
                self.skipTest("Symlink creation is unavailable on this host")
            linked = resolve_task_context(self.repo, file=str(link))
            self.assertEqual("INVALID_TARGET_PATH", linked["status"])

    def test_stale_advisory_falls_back_to_live_context(self) -> None:
        path = self.write("app/src/main/kotlin/com/example/StateVm.kt", "package com.example\nclass StateVm : ViewModel()")
        payload = extract_project_facts(self.repo)
        write_project_context(self.repo, payload)
        path.write_text("package com.example\nclass StateVm : ViewModel() { val state: StateFlow<Int> }", encoding="utf-8")
        result = resolve_task_context(self.repo, symbol="StateVm")
        self.assertEqual("ADVISORY_STALE_FALLBACK_USED", result["status"])
        self.assertEqual([], result["local_profiles"])

    def test_consistent_extraction_retries_once(self) -> None:
        stable = project_context.compute_source_fingerprint(self.repo)
        changed = dict(stable)
        changed["source_fingerprint_sha256"] = "f" * 64
        sequence = [stable, changed, stable, stable]
        with mock.patch.object(project_context, "compute_source_fingerprint", side_effect=sequence):
            payload = extract_consistent_project_context(self.repo)
        self.assertEqual(stable["source_fingerprint_sha256"], payload["source_fingerprint_sha256"])

    def test_repeated_concurrent_change_commits_nothing(self) -> None:
        stable = project_context.compute_source_fingerprint(self.repo)
        changed_a = dict(stable)
        changed_a["source_fingerprint_sha256"] = "a" * 64
        changed_b = dict(stable)
        changed_b["source_fingerprint_sha256"] = "b" * 64
        with mock.patch.object(project_context, "compute_source_fingerprint", side_effect=[stable, changed_a, stable, changed_b]):
            with self.assertRaisesRegex(ContextSourceChangedDuringExtraction, "CONTEXT_SOURCE_CHANGED_DURING_EXTRACTION"):
                extract_consistent_project_context(self.repo)
        self.assertFalse((self.repo / ".agents/project-context/project-facts.json").exists())

    def test_graph_persistent_default_remains_available(self) -> None:
        self.write("app/src/main/kotlin/com/example/Cached.kt", "package com.example\nclass Cached {}")
        engine = GraphEngine(self.repo)
        engine.sync()
        self.assertTrue(engine.cache_file.is_file())

    def test_warm_resolution_processes_less_than_quarter_of_full_fixture(self) -> None:
        for index in range(24):
            self.write(
                f"app/src/main/kotlin/com/example/fixture/Fixture{index}.kt",
                f"package com.example.fixture\nclass Fixture{index} {{}}",
            )
        cold = GraphEngine(self.repo).sync(force_full=True, persist=True)
        warm = resolve_task_context(self.repo, symbol="Fixture0")["graph_sync"]
        self.assertGreaterEqual(cold["files_parsed"], 24)
        self.assertLess(warm["files_parsed"], cold["files_parsed"] * 0.25)

        unrelated = self.repo / "app/src/main/kotlin/com/example/fixture/Fixture23.kt"
        unrelated.write_text("package com.example.fixture\nclass Fixture23 { val changed = true }", encoding="utf-8")
        after_unrelated = resolve_task_context(self.repo, symbol="Fixture0")["graph_sync"]
        self.assertLess(after_unrelated["files_parsed"], cold["files_parsed"] * 0.25)
        self.assertEqual(1, after_unrelated["files_parsed"])

    def test_large_java_sources_do_not_trigger_regex_backtracking(self) -> None:
        methods = "\n".join(
            f"    public static final java.util.List<String> method{index}(String value) {{ return null; }}"
            for index in range(500)
        )
        path = self.write(
            "app/src/main/java/com/example/LargeLegacy.java",
            f"package com.example;\npublic class LargeLegacy {{\n{methods}\n}}\n",
        )
        result = resolve_task_context(self.repo, file=str(path))
        self.assertEqual("RESOLVED", result["status"])
        self.assertIn("LargeLegacy", result["target"]["symbols"])

    def test_failed_snapshot_commit_restores_previous_views_and_facts(self) -> None:
        self.write("app/src/main/kotlin/com/example/Before.kt", "package com.example\nclass Before {}")
        before = extract_project_facts(self.repo)
        context_dir = write_project_context(self.repo, before)
        tracked = ["architecture.md", "ui.md", "persistence.md", "conventions.md", "project-facts.json"]
        original = {name: (context_dir / name).read_bytes() for name in tracked}
        self.write("app/src/main/kotlin/com/example/After.kt", "package com.example\nclass After {}")
        after = extract_project_facts(self.repo)
        real_replace = project_context.os.replace

        def fail_on_facts(source, target):
            if Path(target).name == "project-facts.json":
                raise OSError("injected commit failure")
            return real_replace(source, target)

        with mock.patch.object(project_context.os, "replace", side_effect=fail_on_facts):
            with self.assertRaisesRegex(OSError, "injected commit failure"):
                write_project_context(self.repo, after)
        self.assertEqual(original, {name: (context_dir / name).read_bytes() for name in tracked})


if __name__ == "__main__":
    unittest.main(verbosity=2)
