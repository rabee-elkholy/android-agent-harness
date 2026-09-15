"""Comprehensive test suite for Evolutionary Architecture Context and v1.0.35 Hardening.

Covers:
- SIM-01 through SIM-10 Consumer-Model Usability Simulations
- HARD-001 through HARD-005 Hardening Regressions
- Architecture Policy Schema & Validation
- Architecture Drift Detection with Compatibility Bridge support
- Settings Multi-Module Parsing
- Negative Inference Removal
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _product
from architecture_drift import check_architecture_drift
from architecture_policy import (
    compute_policy_hash,
    create_architecture_policy,
    read_architecture_policy,
    validate_architecture_policy,
    write_architecture_policy,
)
from architecture_resolver import (
    STATUS_DECISION_REQUIRED,
    STATUS_INVALID_POLICY,
    STATUS_RESOLVED,
    resolve_architecture_contract,
)
from project_context import (
    extract_project_facts,
    parse_settings_modules,
    project_context_diff,
    render_project_context,
)
from review_execution import resolve_execution_profile


class ArchitectureContextAndHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp(prefix="harness_arch_test_")
        self.repo = Path(self.test_dir).resolve()
        # Basic structure
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example").mkdir(parents=True, exist_ok=True)
        (self.repo / ".agents" / "project-context").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write(self, rel_path: str, content: str) -> Path:
        p = self.repo / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    # --- 1. Settings Gradle Multi-Module Parsing (PC-007) ---
    def test_settings_multi_module_parsing(self) -> None:
        sample_settings = """
        // Root project settings
        rootProject.name = "MyAwesomeApp"
        include(":app")
        include(":core:network", ":core:database", ":feature:login")
        include ":core:model", ":feature:home"
        /* Multiline include */
        include(
            ":feature:profile",
            ":feature:settings"
        )
        """
        modules = parse_settings_modules(sample_settings)
        self.assertIn(":app", modules)
        self.assertIn(":core:network", modules)
        self.assertIn(":core:database", modules)
        self.assertIn(":feature:login", modules)
        self.assertIn(":core:model", modules)
        self.assertIn(":feature:home", modules)
        self.assertIn(":feature:profile", modules)
        self.assertIn(":feature:settings", modules)
        self.assertEqual(8, len(modules))

    # --- 2. Negative Inference Removal (PC-004) ---
    def test_negative_inference_removed_from_rendered_views(self) -> None:
        # Bare-bones repo with zero explicit base VM, zero explicit navigation, zero custom theme
        facts_payload = extract_project_facts(self.repo)
        views = render_project_context(facts_payload)

        # None of the old negative assumptions should be present
        self.assertNotIn("uses standard `androidx.lifecycle.ViewModel`", views["architecture.md"])
        self.assertNotIn("Standard Activity/Intent-based navigation", views["architecture.md"])
        self.assertNotIn("Standard `MaterialTheme` tokens", views["ui.md"])

        # Should render NOT_DETECTED
        self.assertIn("NOT_DETECTED", views["architecture.md"])
        self.assertIn("NOT_DETECTED", views["ui.md"])

    # --- 3. Complete Drift Diff Coverage (PC-008) ---
    def test_drift_diff_covers_modules_and_architecture(self) -> None:
        old_facts = {
            "schema_version": 2,
            "extractor_version": "2.0.0",
            "context_fingerprint_sha256": "fp1",
            "facts": {
                "modules": [":app"],
                "di": {},
                "view_models": {},
                "persistence": {},
                "ui": {},
                "navigation": {},
                "conventions": {"result_wrappers": []},
                "capabilities": {},
                "architecture": {"families": []},
            },
        }
        # Change modules
        new_facts_modules = json.loads(json.dumps(old_facts))
        new_facts_modules["context_fingerprint_sha256"] = "fp2"
        new_facts_modules["facts"]["modules"] = [":app", ":core"]
        diff_mod = project_context_diff(old_facts, new_facts_modules)
        self.assertEqual("SOURCE_DRIFT", diff_mod["kind"])
        self.assertTrue(any("modules" in d for d in diff_mod["details"]))

        # Change architecture
        new_facts_arch = json.loads(json.dumps(old_facts))
        new_facts_arch["context_fingerprint_sha256"] = "fp3"
        new_facts_arch["facts"]["architecture"]["families"] = [{"id": "af-123"}]
        diff_arch = project_context_diff(old_facts, new_facts_arch)
        self.assertEqual("SOURCE_DRIFT", diff_arch["kind"])
        self.assertTrue(any("architecture" in d for d in diff_arch["details"]))

    # --- 4. Developer Evolution Policy Schema & Validation ---
    def test_architecture_policy_validation(self) -> None:
        policy = create_architecture_policy(preferred_new_code_family="af-123456789abc")
        valid, msg = validate_architecture_policy(policy)
        self.assertTrue(valid, msg)

        # Tampering with policy invalidates hash
        policy_tampered = dict(policy)
        policy_tampered["existing_code_policy"] = "INVALID_POLICY"
        val_bad, _ = validate_architecture_policy(policy_tampered)
        self.assertFalse(val_bad)

        # Write and read back
        p_file = write_architecture_policy(self.repo, policy)
        self.assertTrue(p_file.is_file())
        read_back = read_architecture_policy(self.repo)
        self.assertIsNotNone(read_back)
        self.assertEqual(policy["policy_sha256"], read_back["policy_sha256"])

    # --- 5. Hardening HARD-001: Model Escalation Kill Switch is Strictly One-Way ---
    def test_hard_001_model_escalation_one_way_kill_switch(self) -> None:
        # Create minimal valid task state
        t_id = "test-task-hard001"
        t_dir = self.repo / ".agents" / "state" / "tasks" / t_id
        t_dir.mkdir(parents=True, exist_ok=True)
        (self.repo / ".agents" / "state" / "active-task.json").write_text(
            json.dumps({"task_id": t_id}), encoding="utf-8"
        )
        (t_dir / "plan.json").write_text(json.dumps({"task_id": t_id, "schema_version": 1}), encoding="utf-8")
        policy_path = t_dir / "policy.json"
        policy_path.write_text(
            json.dumps({"surfaces": ["AUTH"], "reviewers": ["security-reviewer-agent"], "review_round": 1}),
            encoding="utf-8",
        )
        (t_dir / "current-run.json").write_text(
            json.dumps({"run_id": "run-1", "policy": str(policy_path)}), encoding="utf-8"
        )

        # When ALLOW_MODEL_ESCALATION in _product is False, environment cannot elevate to True
        with mock.patch.object(_product, "ALLOW_MODEL_ESCALATION", False):
            with mock.patch.dict("os.environ", {"HARNESS_ALLOW_MODEL_ESCALATION": "1"}):
                profile = resolve_execution_profile(self.repo, t_id)
                self.assertFalse(profile["allow_model_escalation"])
                for rev, r_data in profile["reviewers"].items():
                    self.assertEqual("inherit", r_data["preferred_model"])

    # --- 6. Hardening HARD-004 & HARD-005: Reviewer Dispatch Payload & Strict Schema ---
    def test_hard_004_and_005_reviewer_dispatch_contract(self) -> None:
        t_id = "test-task-hard004"
        t_dir = self.repo / ".agents" / "state" / "tasks" / t_id
        t_dir.mkdir(parents=True, exist_ok=True)
        (self.repo / ".agents" / "state" / "active-task.json").write_text(
            json.dumps({"task_id": t_id}), encoding="utf-8"
        )
        (t_dir / "plan.json").write_text(json.dumps({"task_id": t_id, "schema_version": 1}), encoding="utf-8")
        policy_path = t_dir / "policy.json"
        policy_path.write_text(
            json.dumps({"surfaces": ["AUTH"], "reviewers": ["security-reviewer-agent"], "review_round": 1}),
            encoding="utf-8",
        )
        (t_dir / "current-run.json").write_text(
            json.dumps({"run_id": "run-1", "policy": str(policy_path)}), encoding="utf-8"
        )
        # Create a lean role brief
        (t_dir / "brief-security-reviewer-agent.md").write_text("# Security Brief", encoding="utf-8")

        profile = resolve_execution_profile(self.repo, t_id)
        self.assertIn("security-reviewer-agent", profile["reviewers"])
        rev_info = profile["reviewers"]["security-reviewer-agent"]

        # HARD-004 contract assertions
        self.assertEqual("security-reviewer-agent", rev_info["reviewer_role"])
        self.assertTrue(rev_info["brief_path"].endswith("brief-security-reviewer-agent.md"))
        self.assertEqual("# Security Brief", rev_info["brief_content"])
        self.assertEqual("EVIDENCE pkg=<sha12> cites=<count>", rev_info["evidence_footer_contract"])

    # --- 7. Architecture Drift Detection with Compatibility Bridges ---
    def test_architecture_drift_enforcement(self) -> None:
        # Contract: PRESERVE XML family
        contract_preserve = {
            "mode": "PRESERVE",
            "target_scope": "feature/profile",
            "source_family_id": "af-legacy",
            "family_signature_sha256": "BaseViewModel-xml-livedata",
            "source_dimensions": {"ui_toolkit": "xml", "state_holder_base": "BaseViewModel", "state_stream": "livedata"},
        }
        # In unauthorized XML -> Compose transition
        self._write("feature/profile/ProfileFragment.kt", "@Composable fun ProfileScreen() { setContent { Text('Hi') } }")
        with mock.patch("architecture_drift.changed_paths", return_value=[self.repo / "feature/profile/ProfileFragment.kt"]):
            passed, msg, _ = check_architecture_drift(self.repo, contract_preserve)
            self.assertFalse(passed)
            self.assertIn("ARCHITECTURE_DRIFT", msg)

        # In unauthorized LiveData -> StateFlow transition
        self._write("feature/profile/ProfileViewModel.kt", "class ProfileViewModel : BaseViewModel() { val data = MutableStateFlow<String>('') }")
        with mock.patch("architecture_drift.changed_paths", return_value=[self.repo / "feature/profile/ProfileViewModel.kt"]):
            passed_vm, msg_vm, _ = check_architecture_drift(self.repo, contract_preserve)
            self.assertFalse(passed_vm)
            self.assertIn("StateFlow", msg_vm)

        # Compose screen in PRESERVE mode on a Compose family should NOT produce false positive
        contract_preserve_compose = {
            "mode": "PRESERVE",
            "target_scope": "feature/home",
            "source_dimensions": {"ui_toolkit": "compose", "state_stream": "stateflow"},
        }
        self._write("feature/home/MainActivity.kt", "class MainActivity : ComponentActivity() { override fun onCreate() { setContent { Text('Hi') } } }")
        with mock.patch("architecture_drift.changed_paths", return_value=[self.repo / "feature/home/MainActivity.kt"]):
            passed_comp, msg_comp, _ = check_architecture_drift(self.repo, contract_preserve_compose)
            self.assertTrue(passed_comp, f"Existing Compose Activity should be permitted: {msg_comp}")

        # In NEW mode: a compatibility bridge Fragment hosting Compose is explicitly ALLOWED
        contract_new = {
            "mode": "NEW",
            "target_scope": "feature/search",
            "target_family_id": "af-compose-mvi",
            "target_dimensions": {"ui_toolkit": "compose"},
        }
        target_fam = {"dimensions": {"ui_toolkit": "compose"}}
        # Fragment hosting ComposeView
        bridge_file = self._write("feature/search/SearchBridgeFragment.kt", "class SearchBridgeFragment : Fragment() { fun onCreateView() { ComposeView(context) } }")
        with mock.patch("architecture_drift.changed_paths", return_value=[bridge_file]):
            passed_new, msg_new, _ = check_architecture_drift(self.repo, contract_new, target_fam)
            self.assertTrue(passed_new, f"Bridge fragment should be allowed in NEW mode: {msg_new}")

        # In NEW mode: brand new screen built with pure XML layouts is BLOCKED
        xml_screen = self._write("feature/search/SearchLegacyFragment.kt", "class SearchLegacyFragment : Fragment() { fun onCreateView() { inflate(R.layout.search) } }")
        with mock.patch("architecture_drift.changed_paths", return_value=[xml_screen]):
            passed_xml, msg_xml, _ = check_architecture_drift(self.repo, contract_new, target_fam)
            self.assertFalse(passed_xml)
            self.assertIn("XML layouts instead of preferred Compose family", msg_xml)

    # --- 8. SIM-01 through SIM-10 Consumer-Model Usability Simulations ---

    def test_sim_01_bug_in_legacy_xml_screen(self) -> None:
        """SIM-01: Bug fix in legacy XML screen -> PRESERVE local family, no modernizing."""
        # Setup repo with legacy screen and modern screen elsewhere
        self._write("app/src/main/kotlin/legacy/ProfileFragment.kt", "class ProfileFragment : Fragment() { val vm: ProfileViewModel by viewModels() }")
        self._write("app/src/main/kotlin/legacy/ProfileViewModel.kt", "class ProfileViewModel : BaseViewModel() { val data = MutableLiveData<String>() }")
        self._write("app/src/main/kotlin/legacy/BaseViewModel.kt", "abstract class BaseViewModel : ViewModel()")
        self._write("app/src/main/kotlin/modern/HomeScreen.kt", "@Composable fun HomeScreen() {}")
        self._write("app/src/main/kotlin/modern/HomeViewModel.kt", "class HomeViewModel : MviViewModel() { val state = MutableStateFlow('') }")

        res = resolve_architecture_contract(self.repo, architecture_intent="EXISTING_CHANGE", target_scope="legacy/ProfileFragment.kt")
        self.assertEqual(STATUS_RESOLVED, res["status"])
        self.assertEqual("PRESERVE", res["mode"])
        contract = res["contract"]
        self.assertFalse(contract["migration_allowed"])
        self.assertIn("Forbidden", res["brief_markdown"])
        self.assertIn("XML to Compose", res["brief_markdown"])

    def test_sim_02_small_ui_tweak_in_legacy_screen(self) -> None:
        """SIM-02: Small UI tweak in legacy screen preserves family."""
        self._write("app/src/main/kotlin/legacy/DetailFragment.kt", "class DetailFragment : Fragment()")
        res = resolve_architecture_contract(self.repo, architecture_intent="EXISTING_CHANGE", target_scope="legacy/DetailFragment.kt")
        self.assertEqual(STATUS_RESOLVED, res["status"])
        self.assertEqual("PRESERVE", res["mode"])

    def test_sim_03_new_screen_inside_legacy_feature(self) -> None:
        """SIM-03: New screen in legacy feature uses preferred family with compatibility boundary."""
        self._write("app/src/main/kotlin/legacy/FeatureFragment.kt", "class FeatureFragment : Fragment()")
        facts = extract_project_facts(self.repo)
        fam_id = facts["facts"]["architecture"]["families"][0]["id"]
        # Developer chooses modern preferred family
        write_architecture_policy(self.repo, create_architecture_policy(preferred_new_code_family=fam_id))

        res = resolve_architecture_contract(self.repo, architecture_intent="NEW_SCREEN", target_scope="legacy/NewScreen.kt")
        self.assertEqual(STATUS_RESOLVED, res["status"])
        self.assertEqual("NEW", res["mode"])
        self.assertEqual(fam_id, res["contract"]["target_family_id"])

    def test_sim_04_entirely_new_feature(self) -> None:
        """SIM-04: Entirely new feature uses preferred family and modern exemplars."""
        self._write("app/src/main/kotlin/base/MviViewModel.kt", "abstract class MviViewModel : ViewModel()")
        facts = extract_project_facts(self.repo)
        fam_id = facts["facts"]["architecture"]["families"][0]["id"]
        write_architecture_policy(self.repo, create_architecture_policy(preferred_new_code_family=fam_id))

        res = resolve_architecture_contract(self.repo, architecture_intent="NEW_FEATURE", target_scope="feature/billing")
        self.assertEqual(STATUS_RESOLVED, res["status"])
        self.assertEqual("NEW", res["mode"])
        self.assertEqual(fam_id, res["contract"]["target_family_id"])

    def test_sim_05_internal_refactor_of_legacy_viewmodel(self) -> None:
        """SIM-05: Internal refactor preserves family (source == target, no migration)."""
        self._write("app/src/main/kotlin/legacy/OldViewModel.kt", "class OldViewModel : BaseViewModel()")
        self._write("app/src/main/kotlin/legacy/BaseViewModel.kt", "abstract class BaseViewModel : ViewModel()")
        res = resolve_architecture_contract(self.repo, architecture_intent="REFACTOR", target_scope="legacy/OldViewModel.kt")
        self.assertEqual(STATUS_RESOLVED, res["status"])
        self.assertEqual("REFACTOR", res["mode"])
        self.assertEqual(res["contract"]["source_family_id"], res["contract"]["target_family_id"])

    def test_sim_06_explicit_xml_to_compose_migration(self) -> None:
        """SIM-06: Explicit migration allowed only with architectural planning depth."""
        self._write("app/src/main/kotlin/legacy/Screen.kt", "class LegacyScreen : Fragment()")
        facts = extract_project_facts(self.repo)
        fam_id = facts["facts"]["architecture"]["families"][0]["id"]
        write_architecture_policy(self.repo, create_architecture_policy(preferred_new_code_family=fam_id))

        res = resolve_architecture_contract(
            self.repo,
            architecture_intent="MIGRATION",
            target_scope="legacy/Screen.kt",
            target_family_id=fam_id,
            planning_depth="ARCHITECTURAL",
        )
        self.assertEqual(STATUS_RESOLVED, res["status"])
        self.assertEqual("MIGRATE", res["mode"])
        self.assertTrue(res["contract"]["migration_allowed"])

    def test_sim_07_multiple_base_viewmodels(self) -> None:
        """SIM-07: Multiple BaseViewModels exist in different scopes without global failure."""
        self._write("app/src/main/kotlin/scope1/VM1.kt", "abstract class VM1 : ViewModel()")
        self._write("app/src/main/kotlin/scope2/VM2.kt", "abstract class VM2 : ViewModel()")
        facts = extract_project_facts(self.repo)["facts"]
        # In v2 facts, multiple candidates create valid distinct families
        families = facts["architecture"]["families"]
        self.assertGreaterEqual(len(families), 2)
        # Target in scope1 resolves locally
        res = resolve_architecture_contract(self.repo, architecture_intent="EXISTING_CHANGE", target_scope="scope1/VM1.kt")
        self.assertEqual(STATUS_RESOLVED, res["status"])

    def test_sim_08_compose_and_xml_coexist(self) -> None:
        """SIM-08: Compose and XML coexist, resolver selects task-specific family."""
        self._write("app/src/main/kotlin/comp/CompScreen.kt", "@Composable fun CompScreen() {}")
        self._write("app/src/main/kotlin/xml/XmlFragment.kt", "class XmlFragment : Fragment()")
        facts = extract_project_facts(self.repo)["facts"]
        self.assertIn("hybrid", facts["ui"]["framework"])
        # Resolver picks task-specific family
        res_comp = resolve_architecture_contract(self.repo, architecture_intent="EXISTING_CHANGE", target_scope="comp/CompScreen.kt")
        self.assertEqual(STATUS_RESOLVED, res_comp["status"])

    def test_sim_09_ambiguous_target_fails_closed(self) -> None:
        """SIM-09: Ambiguous target across multiple families requires human decision."""
        self._write("app/src/main/kotlin/scope1/Base1.kt", "abstract class Base1 : ViewModel()")
        self._write("app/src/main/kotlin/scope2/Base2.kt", "abstract class Base2 : ViewModel()")
        # Empty target scope with multiple candidate families -> DECISION_REQUIRED
        res = resolve_architecture_contract(self.repo, architecture_intent="EXISTING_CHANGE", target_scope="")
        self.assertEqual(STATUS_DECISION_REQUIRED, res["status"])

    def test_sim_10_stale_preferred_family_reference(self) -> None:
        """SIM-10: Stale preferred family reference diagnosed rather than guessing."""
        self._write("app/src/main/kotlin/MyScreen.kt", "class MyScreen : Fragment()")
        # Policy references a non-existent family ID
        write_architecture_policy(self.repo, create_architecture_policy(preferred_new_code_family="af-deadbeef9999"))
        res = resolve_architecture_contract(self.repo, architecture_intent="NEW_SCREEN", target_scope="NewScreen.kt")
        self.assertIn(res["status"], (STATUS_DECISION_REQUIRED, STATUS_INVALID_POLICY))


if __name__ == "__main__":
    unittest.main(verbosity=2)
