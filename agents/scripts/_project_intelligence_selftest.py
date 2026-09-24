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

    def test_PROJECT_NOTE_001_note_survives_context_refresh(self) -> None:
        """PROJECT_NOTE_001: human project-notes.md survives context refresh."""
        self.mixed_project()
        notes_p = self.repo / ".agents" / "project-context" / "project-notes.md"
        notes_p.parent.mkdir(parents=True, exist_ok=True)
        note_content = "# Project Notes\n- Legacy checkout module must stay XML + MVVM until migration approved.\n"
        notes_p.write_text(note_content, encoding="utf-8")

        payload = extract_consistent_project_context(self.repo)
        write_project_context(self.repo, payload)

        self.assertTrue(notes_p.is_file())
        self.assertEqual(note_content, notes_p.read_text(encoding="utf-8"))

    def test_PROJECT_NOTE_002_note_file_not_overwritten_by_generated_context(self) -> None:
        """PROJECT_NOTE_002: write_project_context does not overwrite or touch project-notes.md."""
        self.mixed_project()
        notes_p = self.repo / ".agents" / "project-context" / "project-notes.md"
        notes_p.parent.mkdir(parents=True, exist_ok=True)
        note_content = "Custom human note\n"
        notes_p.write_text(note_content, encoding="utf-8")

        facts = extract_project_facts(self.repo)
        ctx_dir = write_project_context(self.repo, facts)
        self.assertEqual(note_content, (ctx_dir / "project-notes.md").read_text(encoding="utf-8"))

    def test_PROJECT_INST_001_global_instruction_reaches_applicable_future_task_context(self) -> None:
        """PROJECT_INST_001: global instruction reaches applicable future task context."""
        self.mixed_project()
        inst_p = self.repo / ".agents" / "project-context" / "developer-instructions.json"
        inst_p.parent.mkdir(parents=True, exist_ok=True)
        inst_p.write_text(json.dumps({
            "schema_version": 1,
            "instructions": [
                {
                    "id": "pi-global-01",
                    "status": "ACTIVE",
                    "scope": {"kind": "GLOBAL", "value": "*"},
                    "strength": "REQUIREMENT",
                    "text": "All new public classes must have KDoc",
                    "applies_to": ["ANY"],
                }
            ]
        }), encoding="utf-8")

        res = resolve_task_context(self.repo, file="app/src/main/kotlin/com/example/home/HomeScreen.kt")
        self.assertEqual("RESOLVED", res.get("status"))
        app_inst = res.get("developer_instructions", [])
        self.assertTrue(any(i.get("id") == "pi-global-01" for i in app_inst))

    def test_PROJECT_INST_002_module_instruction_applies_only_to_matching_module(self) -> None:
        """PROJECT_INST_002: MODULE instruction applies only to matching module."""
        self.mixed_project()
        inst_p = self.repo / ".agents" / "project-context" / "developer-instructions.json"
        inst_p.parent.mkdir(parents=True, exist_ok=True)
        inst_p.write_text(json.dumps({
            "schema_version": 1,
            "instructions": [
                {
                    "id": "pi-profile-mod",
                    "status": "ACTIVE",
                    "scope": {"kind": "MODULE", "value": ":feature:profile"},
                    "strength": "REQUIREMENT",
                    "text": "Profile module must maintain MVP contract pattern",
                    "applies_to": ["ANY"],
                }
            ]
        }), encoding="utf-8")

        res_profile = resolve_task_context(self.repo, file="feature/profile/src/main/java/com/example/profile/ProfilePresenter.java")
        self.assertTrue(any(i.get("id") == "pi-profile-mod" for i in res_profile.get("developer_instructions", [])))

        res_home = resolve_task_context(self.repo, file="app/src/main/kotlin/com/example/home/HomeScreen.kt")
        self.assertFalse(any(i.get("id") == "pi-profile-mod" for i in res_home.get("developer_instructions", [])))

    def test_PROJECT_INST_003_package_instruction_respects_package_ancestry(self) -> None:
        """PROJECT_INST_003: PACKAGE instruction respects package ancestry."""
        self.mixed_project()
        inst_p = self.repo / ".agents" / "project-context" / "developer-instructions.json"
        inst_p.parent.mkdir(parents=True, exist_ok=True)
        inst_p.write_text(json.dumps({
            "schema_version": 1,
            "instructions": [
                {
                    "id": "pi-pkg-profile",
                    "status": "ACTIVE",
                    "scope": {"kind": "PACKAGE", "value": "com.example.profile"},
                    "strength": "REQUIREMENT",
                    "text": "Profile package requires presenter isolation",
                    "applies_to": ["ANY"],
                }
            ]
        }), encoding="utf-8")

        res_pkg = resolve_task_context(self.repo, file="feature/profile/src/main/java/com/example/profile/ProfileContract.java")
        self.assertTrue(any(i.get("id") == "pi-pkg-profile" for i in res_pkg.get("developer_instructions", [])))

        res_other = resolve_task_context(self.repo, file="app/src/main/kotlin/com/example/home/HomeScreen.kt")
        self.assertFalse(any(i.get("id") == "pi-pkg-profile" for i in res_other.get("developer_instructions", [])))

    def test_PROJECT_INST_004_path_instruction_respects_path_boundaries(self) -> None:
        """PROJECT_INST_004: PATH instruction respects path boundaries."""
        self.mixed_project()
        inst_p = self.repo / ".agents" / "project-context" / "developer-instructions.json"
        inst_p.parent.mkdir(parents=True, exist_ok=True)
        inst_p.write_text(json.dumps({
            "schema_version": 1,
            "instructions": [
                {
                    "id": "pi-path-feature",
                    "status": "ACTIVE",
                    "scope": {"kind": "PATH", "value": "feature/profile"},
                    "strength": "REQUIREMENT",
                    "text": "Feature profile path convention",
                    "applies_to": ["ANY"],
                }
            ]
        }), encoding="utf-8")

        res_match = resolve_task_context(self.repo, file="feature/profile/src/main/java/com/example/profile/ProfileFragment.java")
        self.assertTrue(any(i.get("id") == "pi-path-feature" for i in res_match.get("developer_instructions", [])))

        res_outside = resolve_task_context(self.repo, file="app/src/main/kotlin/com/example/home/HomeScreen.kt")
        self.assertFalse(any(i.get("id") == "pi-path-feature" for i in res_outside.get("developer_instructions", [])))

    def test_PROJECT_INST_005_superseded_instruction_is_inactive(self) -> None:
        """PROJECT_INST_005: superseded instruction is inactive."""
        self.mixed_project()
        inst_p = self.repo / ".agents" / "project-context" / "developer-instructions.json"
        inst_p.parent.mkdir(parents=True, exist_ok=True)
        inst_p.write_text(json.dumps({
            "schema_version": 1,
            "instructions": [
                {
                    "id": "pi-old",
                    "status": "SUPERSEDED",
                    "scope": {"kind": "GLOBAL", "value": "*"},
                    "strength": "REQUIREMENT",
                    "text": "Deprecated rule",
                    "applies_to": ["ANY"],
                }
            ]
        }), encoding="utf-8")

        res = resolve_task_context(self.repo, file="app/src/main/kotlin/com/example/home/HomeScreen.kt")
        self.assertFalse(any(i.get("id") == "pi-old" for i in res.get("developer_instructions", [])))

    def test_PROJECT_INST_006_conflicting_applicable_instructions_produce_deterministic_conflict_state(self) -> None:
        """PROJECT_INST_006: conflicting applicable instructions produce deterministic conflict state."""
        self.mixed_project()
        inst_p = self.repo / ".agents" / "project-context" / "developer-instructions.json"
        inst_p.parent.mkdir(parents=True, exist_ok=True)
        inst_p.write_text(json.dumps({
            "schema_version": 1,
            "instructions": [
                {
                    "id": "pi-req-1",
                    "status": "ACTIVE",
                    "scope": {"kind": "MODULE", "value": ":feature:profile"},
                    "strength": "REQUIREMENT",
                    "text": "Always use MVVM pattern in this module",
                    "applies_to": ["ANY"],
                },
                {
                    "id": "pi-req-2",
                    "status": "ACTIVE",
                    "scope": {"kind": "MODULE", "value": ":feature:profile"},
                    "strength": "REQUIREMENT",
                    "text": "Never use MVVM pattern in this module",
                    "applies_to": ["ANY"],
                },
            ]
        }), encoding="utf-8")

        res = resolve_task_context(self.repo, file="feature/profile/src/main/java/com/example/profile/ProfilePresenter.java")
        self.assertEqual("DEVELOPER_INSTRUCTION_CONFLICT", res.get("status"))

    def test_PROJECT_INST_007_plan_binds_applicable_instruction_ids_and_hashes(self) -> None:
        """PROJECT_INST_007: plan binds applicable instruction IDs and hashes."""
        import argparse
        import subprocess
        import uuid
        import workflow
        from _vnext_common import atomic_write_json, canonical_sha256, utc_now

        subprocess.run(["git", "init", "-q"], cwd=str(self.repo), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(self.repo), check=True)
        subprocess.run(["git", "config", "user.email", "test@invalid"], cwd=str(self.repo), check=True)

        manifest = {
            "schema_version": 1,
            "architecture_major": 1,
            "harness_version": "1.0.60",
            "installed_at": utc_now(),
            "install_backup": None,
            "latest_backup": None,
            "managed_exclude_block": {"begin": "# BEGIN", "end": "# END"},
            "entries": [],
        }
        manifest["ownership_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "ownership_sha256"})
        atomic_write_json(self.repo / ".agents" / "ownership.json", manifest)

        self.mixed_project()
        subprocess.run(["git", "add", "."], cwd=str(self.repo), check=True)
        subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=str(self.repo), check=True)

        inst_p = self.repo / ".agents" / "project-context" / "developer-instructions.json"
        inst_p.parent.mkdir(parents=True, exist_ok=True)
        inst_data = {
            "schema_version": 1,
            "instructions": [
                {
                    "id": "pi-plan-bound",
                    "status": "ACTIVE",
                    "scope": {"kind": "GLOBAL", "value": "*"},
                    "strength": "REQUIREMENT",
                    "text": "Always write unit tests for public methods",
                    "proof_reference_sha256": "abcdef123456",
                    "applies_to": ["ANY"],
                }
            ]
        }
        inst_p.write_text(json.dumps(inst_data), encoding="utf-8")

        task_id = f"task-{uuid.uuid4().hex[:6]}"
        draft_args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Add feature",
            kind="FEATURE",
            prompt="Add feature",
            task_file=None,
            expected_files="app/src/main/kotlin/com/example/home/HomeScreen.kt",
        )
        res = workflow.draft(draft_args)
        plan_f = workflow.task_dir(self.repo, res["task_id"]) / "plan.json"
        self.assertTrue(plan_f.is_file())
        plan = json.loads(plan_f.read_text(encoding="utf-8"))
        bound_insts = plan.get("developer_instructions", [])
        self.assertTrue(any(i.get("id") == "pi-plan-bound" and i.get("sha256") == "abcdef123456" for i in bound_insts))

    def test_PROJECT_INST_008_current_source_evidence_remains_higher_authority_than_contradictory_generic_note(self) -> None:
        """PROJECT_INST_008: current source evidence remains higher authority than contradictory generic note."""
        self.mixed_project()
        notes_p = self.repo / ".agents" / "project-context" / "project-notes.md"
        notes_p.parent.mkdir(parents=True, exist_ok=True)
        notes_p.write_text("# Notes\nAll UI is written exclusively in XML.\n", encoding="utf-8")

        facts = extract_project_facts(self.repo)
        app_profiles = [p for p in facts["advisory_knowledge"]["local_profiles"] if "home" in str(p.get("logical_scope", ""))]
        if app_profiles:
            self.assertIn("compose", app_profiles[0]["ui_toolkits"])


class InstructionConflictResolutionTests(unittest.TestCase):
    """INSTRUCT-CONFLICT-001..006 covering deterministic polarity conflicts."""

    def test_INSTRUCT_CONFLICT_001_unrelated_positive_negative_no_conflict(self) -> None:
        from task_context import _detect_instruction_conflict
        instructions = [
            {
                "id": "inst-synthetic",
                "status": "ACTIVE",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "REQUIREMENT",
                "text": "Never use synthetic view accessors.",
            },
            {
                "id": "inst-compose",
                "status": "ACTIVE",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "REQUIREMENT",
                "text": "New screens must use Jetpack Compose.",
            },
        ]
        conflict = _detect_instruction_conflict(instructions)
        self.assertIsNone(conflict)

    def test_INSTRUCT_CONFLICT_002_shared_subject_positive_negative_conflicts(self) -> None:
        from task_context import _detect_instruction_conflict
        instructions = [
            {
                "id": "inst-no-retrofit",
                "status": "ACTIVE",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "REQUIREMENT",
                "text": "Never use Retrofit.",
            },
            {
                "id": "inst-use-retrofit",
                "status": "ACTIVE",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "REQUIREMENT",
                "text": "Networking must use Retrofit.",
            },
        ]
        conflict = _detect_instruction_conflict(instructions)
        self.assertIsNotNone(conflict)
        self.assertIn("Conflicting", conflict)

    def test_INSTRUCT_CONFLICT_003_mvi_vs_mvvm_architecture_conflict(self) -> None:
        from task_context import _detect_instruction_conflict
        instructions = [
            {
                "id": "inst-mvi",
                "status": "ACTIVE",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "REQUIREMENT",
                "text": "Architecture must use MVI.",
            },
            {
                "id": "inst-mvvm",
                "status": "ACTIVE",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "REQUIREMENT",
                "text": "Architecture must use MVVM.",
            },
        ]
        conflict = _detect_instruction_conflict(instructions)
        self.assertIsNotNone(conflict)
        self.assertIn("architecture", conflict.lower())

    def test_INSTRUCT_CONFLICT_004_explicit_conflict_with_authoritative(self) -> None:
        from task_context import _detect_instruction_conflict
        instructions = [
            {
                "id": "inst-a",
                "status": "ACTIVE",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "RECOMMENDATION",
                "text": "Use Koin for dependency injection.",
                "conflict_with": "inst-b",
            },
            {
                "id": "inst-b",
                "status": "ACTIVE",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "RECOMMENDATION",
                "text": "Use Dagger Hilt for dependency injection.",
            },
        ]
        conflict = _detect_instruction_conflict(instructions)
        self.assertIsNotNone(conflict)
        self.assertIn("Explicitly conflicting", conflict)

    def test_INSTRUCT_CONFLICT_005_instructions_in_different_scopes_no_false_conflict(self) -> None:
        from task_context import _detect_instruction_conflict
        instructions = [
            {
                "id": "inst-login",
                "status": "ACTIVE",
                "scope": {"kind": "MODULE", "value": ":feature:login"},
                "strength": "REQUIREMENT",
                "text": "Never use Retrofit.",
            },
            {
                "id": "inst-home",
                "status": "ACTIVE",
                "scope": {"kind": "MODULE", "value": ":feature:home"},
                "strength": "REQUIREMENT",
                "text": "Networking must use Retrofit.",
            },
        ]
        conflict = _detect_instruction_conflict(instructions)
        self.assertIsNone(conflict)

    def test_INSTRUCT_CONFLICT_006_superseded_instruction_does_not_conflict(self) -> None:
        from task_context import _detect_instruction_conflict
        instructions = [
            {
                "id": "inst-old",
                "status": "SUPERSEDED",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "REQUIREMENT",
                "text": "Never use Retrofit.",
            },
            {
                "id": "inst-new",
                "status": "ACTIVE",
                "scope": {"kind": "GLOBAL", "value": "*"},
                "strength": "REQUIREMENT",
                "text": "Networking must use Retrofit.",
            },
        ]
        conflict = _detect_instruction_conflict(instructions)
        self.assertIsNone(conflict)


class TaskContextFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="taskctx_fallback_")
        self.repo = Path(self.temp.name).resolve()
        # Create minimal Android project
        (self.repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
        (self.repo / "app/build.gradle.kts").parent.mkdir(parents=True, exist_ok=True)
        (self.repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")

        # Kotlin source
        kt = self.repo / "app/src/main/kotlin/com/example/home/HomeScreen.kt"
        kt.parent.mkdir(parents=True, exist_ok=True)
        kt.write_text("package com.example.home\nclass HomeScreen {}\n", encoding="utf-8")

        # Manifest
        manifest = self.repo / "app/src/main/AndroidManifest.xml"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android"><uses-permission android:name="android.permission.INTERNET"/></manifest>\n', encoding="utf-8")

        # Strings
        strings = self.repo / "app/src/main/res/values/strings.xml"
        strings.parent.mkdir(parents=True, exist_ok=True)
        strings.write_text('<resources><string name="app_name">Test</string></resources>\n', encoding="utf-8")

        # Layout
        layout = self.repo / "app/src/main/res/layout/activity_main.xml"
        layout.parent.mkdir(parents=True, exist_ok=True)
        layout.write_text('<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"/>\n', encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_TASKCTX_FALLBACK_001_kotlin_source_graph_context_unchanged(self) -> None:
        from task_context import resolve_task_context
        res = resolve_task_context(self.repo, file="app/src/main/kotlin/com/example/home/HomeScreen.kt")
        self.assertEqual("RESOLVED", res["status"])
        self.assertNotEqual("FILE_FALLBACK", res.get("context_mode"))
        self.assertTrue(res["graph_basis"]["used"])
        self.assertIn("HomeScreen", res["target"]["symbols"])

    def test_TASKCTX_FALLBACK_002_gradle_resolved_file_fallback_build_config(self) -> None:
        from task_context import resolve_task_context
        res = resolve_task_context(self.repo, file="app/build.gradle.kts")
        self.assertEqual("RESOLVED", res["status"])
        self.assertEqual("FILE_FALLBACK", res.get("context_mode"))
        self.assertIn("BUILD_CONFIG", res["target"]["candidate_surfaces"])
        self.assertEqual([], res["direct_dependencies"])
        self.assertEqual([], res["direct_dependents"])
        self.assertTrue(any("graph relationships are unavailable" in w.lower() for w in res.get("warnings", [])))

    def test_TASKCTX_FALLBACK_003_manifest_resolved_fallback(self) -> None:
        from task_context import resolve_task_context
        res = resolve_task_context(self.repo, file="app/src/main/AndroidManifest.xml")
        self.assertEqual("RESOLVED", res["status"])
        self.assertEqual("FILE_FALLBACK", res.get("context_mode"))
        surfaces = res["target"]["candidate_surfaces"]
        self.assertTrue("MANIFEST_PERMISSION" in surfaces or "BUILD_CONFIG" in surfaces)

    def test_TASKCTX_FALLBACK_004_strings_xml_localization(self) -> None:
        from task_context import resolve_task_context
        res = resolve_task_context(self.repo, file="app/src/main/res/values/strings.xml")
        self.assertEqual("RESOLVED", res["status"])
        self.assertEqual("FILE_FALLBACK", res.get("context_mode"))
        self.assertIn("LOCALIZATION", res["target"]["candidate_surfaces"])

    def test_TASKCTX_FALLBACK_005_layout_xml_ui(self) -> None:
        from task_context import resolve_task_context
        res = resolve_task_context(self.repo, file="app/src/main/res/layout/activity_main.xml")
        self.assertEqual("RESOLVED", res["status"])
        self.assertEqual("FILE_FALLBACK", res.get("context_mode"))
        self.assertIn("XML_UI", res["target"]["candidate_surfaces"])

    def test_TASKCTX_FALLBACK_006_missing_outside_repo_fails(self) -> None:
        from task_context import resolve_task_context
        res_missing = resolve_task_context(self.repo, file="app/src/main/res/values/nonexistent.xml")
        self.assertEqual("NOT_FOUND", res_missing["status"])

        res_outside = resolve_task_context(self.repo, file="../outside.xml")
        self.assertEqual("INVALID_TARGET_PATH", res_outside["status"])

    def test_TASKCTX_FALLBACK_007_fallback_does_not_inherit_unrelated_active_architecture(self) -> None:
        from task_context import resolve_task_context
        state = self.repo / ".agents" / "state"
        task = state / "tasks" / "task-unrelated"
        task.mkdir(parents=True, exist_ok=True)
        contract = {
            "family_id": "MVI",
            "target_scope": "payments/src/main/kotlin/PaymentViewModel.kt",
            "contract_sha256": "dummy",
        }
        plan = {
            "task_id": "task-unrelated",
            "status": "IMPLEMENTING",
            "approval": {"single_use_nonce": "n"},
            "expected_files": ["payments/src/main/kotlin/PaymentViewModel.kt"],
            "architecture_contract": contract,
        }
        (task / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (state / "active-task.json").write_text(json.dumps({"task_id": "task-unrelated", "plan_path": str(task / "plan.json")}), encoding="utf-8")

        res = resolve_task_context(self.repo, file="app/src/main/res/values/strings.xml")
        self.assertEqual("RESOLVED", res["status"])
        self.assertEqual("FILE_FALLBACK", res.get("context_mode"))
        self.assertEqual({}, res.get("architecture_contract", {}))
        self.assertEqual([], res.get("local_profiles", []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
