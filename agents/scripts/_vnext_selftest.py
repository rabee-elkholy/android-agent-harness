"""Regression suite for the vNext architecture contracts."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
KIT = SCRIPTS.parents[1]
HARNESS_VERSION = (KIT / "agents" / "VERSION").read_text(encoding="utf-8").strip()
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(KIT))
import harness_cli  # noqa: E402

from _vnext_common import ValidationError, atomic_write_json, canonical_sha256, read_json, sha256_file  # noqa: E402
from artifact_set import build_artifact_set, resolve_artifacts, verify_artifact_set  # noqa: E402
from change_classifier import classify  # noqa: E402
from delivery_manifest import build_manifest  # noqa: E402
from evidence_store import EvidenceStore, StateLock, _pid_alive  # noqa: E402
from final_verifier import verify  # noqa: E402
from install_tool_adapters import sync_hooks_json  # noqa: E402
from lifecycle import OWNERSHIP_RELATIVE, _validate_kit, install, replace_legacy, uninstall, update  # noqa: E402
import lifecycle as lifecycle_module  # noqa: E402
from plan_authority import (  # noqa: E402
    DEFAULT_APP_SURFACES,
    approve,
    begin,
    changed_modules,
    check_material_drift,
    create_plan,
    normalize_expected_surfaces,
    save_plan,
)
from review_policy import PIPELINE_GATE_ORDER, decide, decide_later_round  # noqa: E402
from run_device import adb_result_ok  # noqa: E402
from review_package import build_package  # noqa: E402
from record_review import ingest  # noqa: E402
from skill_router import route  # noqa: E402
from mutation_guard import command_allowed  # noqa: E402
from _repo_files import first_adb_serial  # noqa: E402
from wizard.discovery import discover, discover_android_source_root, discover_di_framework, discover_launchers, discover_module_application_ids  # noqa: E402
from wizard.questions import normalize, questions_payload  # noqa: E402
from room_guard import check_room_working_tree  # noqa: E402
from workflow import begin_task, complete, deliver_task, draft, prepare_verification, record_approval, record_sensitive_approval, state_root, task_dir  # noqa: E402



def run_git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)


def write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Harness Test")
        run_git(self.repo, "config", "user.email", "harness@example.invalid")
        run_git(self.repo, "config", "core.autocrlf", "true")
        write(self.repo / "gradlew", "#!/bin/sh\nexit 0\n")
        os.chmod(self.repo / "gradlew", 0o755)
        write(self.repo / "settings.gradle.kts", 'rootProject.name = "Fixture"\ninclude(":app")\n')
        write(self.repo / "app/build.gradle.kts", 'plugins { id("com.android.application") }\n')
        write(self.repo / "app/src/main/kotlin/A.kt", "internal class A\n")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "fixture")

    def tearDown(self) -> None:
        self.temp.cleanup()


class ChatInstallationDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.version = (KIT / "agents" / "VERSION").read_text(encoding="utf-8").strip()
        self.readme = (KIT / "README.md").read_text(encoding="utf-8")
        self.prompt = (KIT / "docs" / "install-or-update-prompt.md").read_text(encoding="utf-8")

    def test_chat_installation_is_primary_and_terminal_is_alternative(self) -> None:
        chat_heading = "### Chat installation (recommended)"
        terminal_heading = "### Terminal installation (alternative)"
        self.assertIn(chat_heading, self.readme)
        self.assertIn(terminal_heading, self.readme)
        self.assertLess(self.readme.index(chat_heading), self.readme.index(terminal_heading))
        self.assertIn(
            f"android-agent-harness/v{self.version}/docs/install-or-update-prompt.md",
            self.readme,
        )

    def test_chat_prompt_is_pinned_and_self_contained(self) -> None:
        tag = f"v{self.version}"
        self.assertIn(f"--branch {tag} --single-branch", self.prompt)
        self.assertIn("describe --tags --exact-match", self.prompt)
        self.assertIn("recommended", self.prompt)
        self.assertLessEqual(len(self.prompt.encode("utf-8")), 4096)
        self.assertNotIn("android-agent-harness/main/", self.prompt)
        self.assertNotIn("releases/latest", self.prompt)

    def test_chat_prompt_covers_approved_install_and_update_paths(self) -> None:
        for marker in (
            "Clean Install",
            "Same-Major Update",
            "Legacy Replacement",
            "harness_cli.py init --repo",
            "harness_cli.py update --no-refresh --repo",
            "init --replace-legacy",
            "STOP AND WAIT FOR EXPLICIT DEVELOPER APPROVAL",
            "Phase 1: Read-only discovery",
            "Phase 2: Kit bootstrap approval",
            "Phase 4: Lifecycle approval and execution",
            "Phase 5: Verification",
        ):
            self.assertIn(marker, self.prompt)

    def test_single_shot_proceed_and_followup_execution_rules(self) -> None:
        harness_rules = (KIT / "agents" / "rules" / "harness-rules.md").read_text(encoding="utf-8")
        gemini_tpl = (KIT / "agents" / "tool-adapters" / "GEMINI.md.template").read_text(encoding="utf-8")
        agents_tpl = (KIT / "agents" / "tool-adapters" / "AGENTS.md.template").read_text(encoding="utf-8")
        gemini_root = (KIT / "GEMINI.md").read_text(encoding="utf-8")
        agents_root = (KIT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("Single-shot Proceed invariant", harness_rules)
        self.assertIn("Direct follow-up execution", harness_rules)
        self.assertIn("Antigravity Planning Lifecycle", gemini_tpl)
        self.assertIn("Antigravity Planning Lifecycle", gemini_root)
        self.assertIn("never generate redundant plan artifacts or stall for nonexistent UI buttons", agents_tpl)
        self.assertIn("Follow-ups and technical fixes within active scope require immediate execution", agents_root)

    def test_pre_invocation_reminder_anti_stalling_directives(self) -> None:
        reminder_script = (KIT / "agents" / "scripts" / "pre_invocation_reminder.py").read_text(encoding="utf-8")
        self.assertIn("Do not create new plans or ask for Proceed", reminder_script)
        self.assertIn("never stall on new plans or demand 'Proceed'", reminder_script)
        self.assertIn("do not stall on follow-ups", reminder_script)


class ChatInstallationLifecycleTests(RepoCase):
    def test_harness_cli_init_with_answers_json(self) -> None:
        temp_answers = self.repo / "temp_answers.json"
        write(
            temp_answers,
            json.dumps({
                "i0": "yes",
                "i1": "Fixture",
                "i2": sys.executable,
                "i5": ":app",
                "i6": "com.example.fixture.MainActivity",
                "i14": ["codex"],
                "i15": "yes",
                "i20": "none",
            }),
        )
        args = Namespace(
            repo=str(self.repo),
            kit=str(KIT),
            answers_json=str(temp_answers),
            lang="en",
        )
        code = harness_cli.cmd_init(args)
        self.assertEqual(0, code)
        self.assertTrue((self.repo / ".agents").is_dir())
        self.assertTrue((self.repo / ".harness-setup" / "answers.json").is_file())
        self.assertFalse(temp_answers.exists())

    def test_chat_same_major_update_applies_new_answers_without_refresh(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "tools": ["codex"],
            "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        temp_answers = self.repo / "update_answers.json"
        write(temp_answers, json.dumps({"i4": "emulator-only", "i14": ["codex"], "i20": "none"}))
        code = harness_cli.cmd_update(Namespace(
            repo=str(self.repo), kit=str(KIT), force=False, no_refresh=True,
            answers_json=str(temp_answers),
        ))
        self.assertEqual(0, code)
        self.assertFalse(temp_answers.exists())
        answers = json.loads((self.repo / ".harness-setup/answers.json").read_text(encoding="utf-8"))
        self.assertEqual("emulator-only", answers["device_policy"])

    def test_setup_wizard_schema_validation_rejects_unknown_keys_and_symlinks(self) -> None:
        bad_answers = self.repo / "bad_answers.json"
        write(bad_answers, json.dumps({"unknown_key_xyz": "value"}))
        from wizard.schema import validate_raw_answers
        payload = json.loads(bad_answers.read_text(encoding="utf-8"))
        errors = validate_raw_answers(payload)
        self.assertTrue(any("unknown question keys" in e for e in errors))

        link_answers = self.repo / "symlink_answers.json"
        try:
            link_answers.symlink_to(bad_answers)
            from setup_wizard import load_write_payload
            with self.assertRaises(SystemExit) as ctx:
                load_write_payload(link_answers)
            self.assertIn("cannot be a symlink", str(ctx.exception))
        except (OSError, NotImplementedError):
            pass

    def test_temporary_answers_file_is_cleaned_up_on_failure(self) -> None:
        temp_answers = self.repo / "fail_answers.json"
        write(temp_answers, json.dumps({"unknown_key_fail": True}))
        args = Namespace(
            repo=str(self.repo),
            kit=str(KIT),
            answers_json=str(temp_answers),
            lang="en",
        )
        code = harness_cli.cmd_init(args)
        self.assertNotEqual(0, code)
        self.assertFalse(temp_answers.exists())

    def test_pre_execution_checksums_verifier_rejects_tampered_kit(self) -> None:
        temp_kit_dir = tempfile.TemporaryDirectory()
        try:
            kit_copy = Path(temp_kit_dir.name) / "kit"
            shutil.copytree(KIT / "agents", kit_copy / "agents")
            harness_cli._verify_kit_checksums(kit_copy)

            tampered_file = kit_copy / "agents" / "VERSION"
            tampered_file.write_text("0.0.0-tampered", encoding="utf-8")
            with self.assertRaises(SystemExit) as ctx:
                harness_cli._verify_kit_checksums(kit_copy)
            self.assertIn("checksum mismatch", str(ctx.exception))
        finally:
            temp_kit_dir.cleanup()

    def test_windows_kit_transaction_and_recovery(self) -> None:
        target_dir = self.repo / "kit_target"
        target_dir.mkdir()
        previous = target_dir.with_name(f"{target_dir.name}.previous")
        previous.mkdir()
        write(previous / "agents/VERSION", "1.0.0")
        write(previous / "agents/scripts/setup_wizard.py", "# dummy")
        harness_cli._recover_stale_kit(target_dir)
        self.assertTrue(harness_cli._has_engine(target_dir))
        self.assertFalse(previous.exists())

    def test_executable_app_snapshot_fails_if_app_code_modified(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "tools": ["codex"],
            "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        original_install_engine = lifecycle_module._install_engine

        def tampering_install_engine(repo: Path, kit: Path, answers: dict) -> None:
            original_install_engine(repo, kit, answers)
            write(repo / "app/src/main/kotlin/A.kt", "unauthorized modification\n")

        with mock.patch.object(lifecycle_module, "_install_engine", tampering_install_engine):
            with self.assertRaises(ValidationError) as ctx:
                install(self.repo, KIT)
            self.assertIn("outside harness boundary were modified", str(ctx.exception))

    def test_chat_installation_prompt_contract_and_schema_alignment(self) -> None:
        prompt_text = (KIT / "docs" / "install-or-update-prompt.md").read_text(encoding="utf-8")
        self.assertIn("setup wizard payload is the sole interview authority", prompt_text)
        self.assertIn("Ask **only** the questions returned", prompt_text)
        self.assertNotIn("Canonical Questions Reference", prompt_text)
        self.assertIn("recommended", prompt_text)
        self.assertIn("STOP AND WAIT FOR EXPLICIT DEVELOPER APPROVAL", prompt_text)

    def test_chat_installation_has_separate_bootstrap_and_lifecycle_approvals(self) -> None:
        prompt_text = (KIT / "docs" / "install-or-update-prompt.md").read_text(encoding="utf-8")
        bootstrap_gate = prompt_text.index("STOP AND WAIT FOR EXPLICIT KIT BOOTSTRAP APPROVAL")
        clone = prompt_text.index("git clone --depth 1")
        lifecycle_gate = prompt_text.index("STOP AND WAIT FOR EXPLICIT DEVELOPER APPROVAL")
        answers_write = prompt_text.index("create `<temp-answers>.json`")
        self.assertLess(clone, bootstrap_gate)
        self.assertLess(bootstrap_gate, lifecycle_gate)
        self.assertLess(lifecycle_gate, answers_write)
        self.assertIn("not app installation/removal", prompt_text)
        self.assertIn("outside `<app-root>`", prompt_text)

    def test_chat_installation_with_existing_project_agents_md(self) -> None:
        agents_md = self.repo / "AGENTS.md"
        write(agents_md, "# Existing Custom Instructions\n")
        run_git(self.repo, "add", "AGENTS.md")
        run_git(self.repo, "commit", "-qm", "add existing AGENTS.md")

        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "tools": ["codex"],
            "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        res = install(self.repo, KIT)
        self.assertEqual("PASS", res["status"])
        backup_dir = Path(res["backup"])
        self.assertTrue((backup_dir / "AGENTS.md").is_file())

    def test_crlf_lf_checksum_stability_and_paths_with_spaces(self) -> None:
        spaces_repo = self.repo / "sub dir with spaces"
        spaces_repo.mkdir()
        write(spaces_repo / "gradlew", "#!/bin/sh\nexit 0\n")
        write(spaces_repo / "build.gradle.kts", "// gradle\n")
        snapshot = lifecycle_module._snapshot_app_files(spaces_repo)
        self.assertIn("build.gradle.kts", snapshot)


class ManifestTests(RepoCase):
    def test_snapshot_is_stable_when_identical_content_is_committed(self) -> None:
        write(self.repo / "app/src/main/kotlin/A.kt", b"internal class B\r\n")
        before = build_manifest(self.repo)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "same content")
        after = build_manifest(self.repo)
        self.assertEqual(before["delivery_snapshot_sha256"], after["delivery_snapshot_sha256"])
        self.assertNotEqual(before["change_set_sha256"], after["change_set_sha256"])

    def test_line_endings_only_are_not_a_material_change(self) -> None:
        before = build_manifest(self.repo)
        write(self.repo / "app/src/main/kotlin/A.kt", b"internal class A\r\n")
        after = build_manifest(self.repo)
        self.assertEqual([], after["changes"])
        self.assertEqual(before["delivery_snapshot_sha256"], after["delivery_snapshot_sha256"])
        self.assertEqual(before["change_set_sha256"], after["change_set_sha256"])

    def test_change_set_covers_rename_delete_and_untracked(self) -> None:
        write(self.repo / "app/src/main/kotlin/B.kt", "internal class B\n")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "second source")
        write(self.repo / "app/src/main/kotlin/A.kt", b"internal class A\r\n")
        (self.repo / "app/src/main/kotlin/A.kt").rename(self.repo / "app/src/main/kotlin/C.kt")
        (self.repo / "app/src/main/kotlin/B.kt").unlink()
        write(self.repo / "app/src/main/kotlin/D.kt", "internal class D\n")
        changes = build_manifest(self.repo)["changes"]
        paths = {item["path"] for item in changes}
        statuses = {item["status"] for item in changes}
        self.assertTrue({"app/src/main/kotlin/C.kt", "app/src/main/kotlin/B.kt", "app/src/main/kotlin/D.kt"} <= paths)
        self.assertTrue({"R", "D", "A"} <= statuses)

    def test_docs_do_not_stale_delivery_snapshot(self) -> None:
        before = build_manifest(self.repo)
        write(self.repo / "README.md", "documentation only\n")
        after = build_manifest(self.repo)
        self.assertEqual(before["delivery_snapshot_sha256"], after["delivery_snapshot_sha256"])
        self.assertEqual(before["change_set_sha256"], after["change_set_sha256"])

    def test_ignored_external_input_changes_identity_without_leaking_value(self) -> None:
        write(self.repo / ".gitignore", "local.properties\n")
        run_git(self.repo, "add", ".gitignore")
        run_git(self.repo, "commit", "-qm", "ignore local")
        write(self.repo / "local.properties", "sdk.dir=/private/sdk-one\n")
        first = build_manifest(self.repo)
        write(self.repo / "local.properties", "sdk.dir=/private/sdk-two\n")
        second = build_manifest(self.repo)
        self.assertNotEqual(first["external_inputs_sha256"], second["external_inputs_sha256"])
        self.assertNotIn("/private/sdk-two", json.dumps(second))


class DiscoveryTests(RepoCase):
    def test_emulator_only_selects_emulator_when_phone_is_also_connected(self) -> None:
        devices = subprocess.CompletedProcess([], 0, "List of devices attached\nPHONE\tdevice\nemulator-5554\tdevice\n", "")
        physical_probe = subprocess.CompletedProcess([], 0, "0\n", "")
        emulator_probe = subprocess.CompletedProcess([], 0, "1\n", "")
        with mock.patch("_repo_files.subprocess.run", side_effect=[devices, physical_probe, emulator_probe]):
            self.assertEqual("emulator-5554", first_adb_serial(policy="emulator-only"))

    def test_hilt_summary_detection_is_case_insensitive(self) -> None:
        self.assertEqual("hilt", discover_di_framework("Hilt + Room + Jetpack Compose"))

    def test_single_choice_recommendation_is_unique_and_previous_is_separate(self) -> None:
        payload = questions_payload(self.repo, "en", discover(self.repo))
        for question in payload:
            if question.get("allow_multiple"):
                continue
            self.assertEqual(1, sum(bool(o.get("recommended")) for o in question["options"]))
            self.assertFalse(any(bool(o.get("previous")) for o in question["options"]))
        write(self.repo / ".harness-setup/answers.json", json.dumps({"device_policy": "physical-only"}))
        device = next(q for q in questions_payload(self.repo, "en", discover(self.repo)) if q["id"] == "i4")
        self.assertTrue(device["options"][0]["previous"])
        self.assertEqual("physical-only", device["options"][0]["id"])
        self.assertEqual(1, sum(bool(o["recommended"]) for o in device["options"]))

    def test_emulator_only_is_a_real_answer(self) -> None:
        facts = discover(self.repo)
        answers = normalize({"i4": "emulator-only", "i14": ["codex"], "i20": "none"}, facts)
        self.assertEqual("emulator-only", answers["device_policy"])

    def test_each_application_launcher_uses_its_own_package(self) -> None:
        write(self.repo / "app/build.gradle.kts", 'plugins { id("com.android.application") }\nandroid { namespace = "com.one"; defaultConfig { applicationId = "com.one" } }\n')
        write(self.repo / "admin/build.gradle", "plugins { id 'com.android.application' }\nandroid { namespace 'com.two'; defaultConfig { applicationId 'com.two' } }\n")
        manifest = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application><activity android:name=".MainActivity"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>'''
        write(self.repo / "app/src/main/AndroidManifest.xml", manifest)
        write(self.repo / "admin/src/main/AndroidManifest.xml", manifest.replace(".MainActivity", ".AdminActivity"))
        ids = discover_module_application_ids(self.repo)
        self.assertEqual("com.one", ids[":app"])
        self.assertEqual("com.two", ids[":admin"])
        self.assertEqual(
            {"com.one/.MainActivity", "com.two/.AdminActivity"},
            set(discover_launchers(self.repo)),
        )

    def test_kmp_and_root_module_source_roots_are_exact(self) -> None:
        write(self.repo / "composeApp/src/androidMain/kotlin/App.kt", "class App\n")
        self.assertEqual(["composeApp", "src", "androidMain"], discover_android_source_root(self.repo, ":composeApp"))
        write(self.repo / "src/main/java/Root.java", "class Root {}\n")
        self.assertEqual(["src", "main"], discover_android_source_root(self.repo, ":"))


class PolicyTests(RepoCase):
    def test_critical_pattern_cannot_be_downgraded_by_file_location(self) -> None:
        write(self.repo / "app/src/main/kotlin/A.kt", "internal val client = BillingClient.newBuilder(context)\n")
        result = classify(self.repo)
        self.assertIn("BILLING", result["surfaces"])
        self.assertEqual("CRITICAL", result["severity"])

    def test_removed_security_code_remains_critical(self) -> None:
        write(self.repo / "app/src/main/kotlin/A.kt", "internal val verifier: HostnameVerifier? = null\n")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "security fixture")
        write(self.repo / "app/src/main/kotlin/A.kt", "internal class Safe\n")
        result = classify(self.repo)
        self.assertIn("SECURITY", result["surfaces"])
        self.assertEqual("CRITICAL", result["severity"])

    def test_untouched_billing_in_modified_file_does_not_trigger_billing_surface(self) -> None:
        write(
            self.repo / "app/src/main/kotlin/A.kt",
            "class FoodPlanFragment {\n"
            "    val client = BillingClient.newBuilder(context)\n"
            "    fun datePicker() {\n"
            "        val x = 1\n"
            "    }\n"
            "}\n",
        )
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "legacy billing fixture")
        write(
            self.repo / "app/src/main/kotlin/A.kt",
            "class FoodPlanFragment {\n"
            "    val client = BillingClient.newBuilder(context)\n"
            "    fun datePicker() {\n"
            "        val x = 2\n"
            "    }\n"
            "}\n",
        )
        result = classify(self.repo)
        self.assertNotIn("BILLING", result["surfaces"])
        self.assertNotIn("AUTH", result["surfaces"])
        self.assertIn("BUSINESS_LOGIC", result["surfaces"])
        self.assertEqual("MEDIUM", result["severity"])

    def test_added_or_deleted_billing_in_diff_triggers_billing_surface(self) -> None:
        write(
            self.repo / "app/src/main/kotlin/A.kt",
            "class FoodPlanFragment {\n"
            "    fun datePicker() {\n"
            "        val x = 1\n"
            "    }\n"
            "}\n",
        )
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "clean fixture")
        write(
            self.repo / "app/src/main/kotlin/A.kt",
            "class FoodPlanFragment {\n"
            "    val client = BillingClient.newBuilder(context)\n"
            "    fun datePicker() {\n"
            "        val x = 1\n"
            "    }\n"
            "}\n",
        )
        result = classify(self.repo)
        self.assertIn("BILLING", result["surfaces"])
        self.assertEqual("CRITICAL", result["severity"])

    def test_entity_field_change_in_bounded_context_triggers_room_schema(self) -> None:
        write(
            self.repo / "app/src/main/kotlin/User.kt",
            "@Entity\n"
            "data class User(\n"
            "    val id: String,\n"
            "    val age: Int\n"
            ")\n",
        )
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "initial entity")
        write(
            self.repo / "app/src/main/kotlin/User.kt",
            "@Entity\n"
            "data class User(\n"
            "    val id: String,\n"
            "    val age: Long\n"
            ")\n",
        )
        result = classify(self.repo)
        self.assertIn("ROOM_SCHEMA", result["surfaces"])
        self.assertIn(result["severity"], ("HIGH", "CRITICAL"))

    def test_room_cross_file_migration_succeeds(self) -> None:
        write(
            self.repo / "app/src/main/kotlin/AppDatabase.kt",
            "@Database(entities = [User::class], version = 1)\n"
            "abstract class AppDatabase : RoomDatabase()\n",
        )
        write(
            self.repo / "app/src/main/kotlin/User.kt",
            "@Entity\ndata class User(val id: String)\n",
        )
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "initial room db")
        write(
            self.repo / "app/src/main/kotlin/AppDatabase.kt",
            "@Database(entities = [User::class], version = 2)\n"
            "abstract class AppDatabase : RoomDatabase()\n",
        )
        write(
            self.repo / "app/src/main/kotlin/DatabaseModule.kt",
            "val MIGRATION_1_2 = object : Migration(1, 2) {}\n"
            "fun provideDb(context: Context): AppDatabase {\n"
            "    return Room.databaseBuilder(context, AppDatabase::class.java, \"app.db\")\n"
            "        .addMigrations(MIGRATION_1_2)\n"
            "        .build()\n"
            "}\n",
        )
        ok, msg = check_room_working_tree(repo=self.repo)
        self.assertTrue(ok, msg)
        self.assertIn("Room migration gate passed", msg)



    def test_persistence_routes_tests_and_android_knowledge(self) -> None:
        write(self.repo / "app/src/main/kotlin/A.kt", "internal val settingsDataStore = context.dataStore\n")
        classification = classify(self.repo)
        self.assertIn("PERSISTENCE", classification["surfaces"])
        policy = decide(classification, KIT / "agents" / "skills")
        self.assertIn("unit_tests", policy["gates"])
        self.assertIn("android-harness", {item["id"] for item in policy["skills"]["skills"]})

    def test_micro_localization_uses_no_semantic_reviewers(self) -> None:
        classification = {
            "classification_sha256": "c" * 64,
            "surfaces": ["LOCALIZATION"],
            "severity": "LOW",
            "confidence": "HIGH",
            "changed_files": 1,
        }
        policy = decide(classification, KIT / "agents" / "skills")
        self.assertTrue(policy["micro_eligible"])
        self.assertEqual([], policy["reviewers"])
        self.assertEqual("REVIEW_NOT_REQUIRED_BY_POLICY", policy["review_status"])

    def test_localization_delete_is_not_micro(self) -> None:
        strings = self.repo / "app/src/main/res/values/strings.xml"
        write(strings, '<resources><string name="title">Title</string></resources>\n')
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "strings")
        strings.unlink()
        classification = classify(self.repo)
        policy = decide(classification, KIT / "agents/skills")
        self.assertTrue(classification["has_delete_or_rename"])
        self.assertFalse(policy["micro_eligible"])

    def test_later_round_reruns_only_findings_regression_and_promotions(self) -> None:
        prior_classification = {
            "classification_sha256": "a" * 64, "surfaces": ["COMPOSE_UI"],
            "severity": "MEDIUM", "confidence": "HIGH", "changed_files": 1,
            "changed_lines": 4, "has_delete_or_rename": False,
        }
        previous = decide(prior_classification, KIT / "agents/skills")
        fixed = dict(prior_classification)
        fixed.update({"classification_sha256": "b" * 64, "surfaces": ["COMPOSE_UI", "COROUTINES"]})
        later = decide_later_round(
            fixed, KIT / "agents/skills", previous_policy=previous,
            finding_owners=["bug-reviewer-agent"],
            passed_reviewers=["convention-reviewer-agent", "regression-impact-reviewer-agent"],
            source_snapshot="s" * 64, source_change_set="c" * 64, source_run_id="run-old",
            round_number=2,
        )
        self.assertEqual(
            {"bug-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"},
            set(later["reviewers"]),
        )
        self.assertEqual(["convention-reviewer-agent"], [item["reviewer"] for item in later["carried_reviews"]])

    def test_missing_required_skill_blocks_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = route(Path(tmp), ["COROUTINES"])
        self.assertEqual("BLOCKED", result["status"])

    def test_library_project_never_selects_device_gate(self) -> None:
        write(self.repo / "app/build.gradle.kts", 'plugins { id("com.android.library") }\nandroid { namespace = "com.example.lib" }\n')
        facts = discover(self.repo)
        self.assertEqual("library", facts["project_kind"])
        classification = {
            "classification_sha256": "c" * 64, "surfaces": ["COMPOSE_UI"],
            "severity": "MEDIUM", "confidence": "HIGH", "changed_files": 1,
        }
        policy = decide(classification, KIT / "agents" / "skills", project_kind="library")
        self.assertNotIn("device", policy["gates"])
        self.assertFalse(policy["device_required"])

    def test_custom_combined_variant_drives_assemble_task(self) -> None:
        write(self.repo / "app/build.gradle.kts", '''plugins { id("com.android.application") }
android { namespace = "com.example"; defaultConfig { applicationId = "com.example" }
productFlavors { create("free") { dimension = "tier" }; create("eu") { dimension = "region" } } }
''')
        facts = discover(self.repo)
        answers = normalize({
            "i0": "yes", "i14": ["codex"], "i19": "other", "i19_text": "FreeEuStaging",
            "i6": "other", "i6_text": "com.example/.MainActivity", "i20": "none",
        }, facts)
        self.assertEqual(":app:assembleFreeEuStaging", answers["assemble"])
        self.assertEqual("FreeEuStaging", answers["build_variant"])


class AuthorityAndEvidenceTests(RepoCase):
    def test_live_pid_probe_is_non_destructive(self) -> None:
        self.assertTrue(_pid_alive(os.getpid()))

    def test_approval_is_bound_and_single_use(self) -> None:
        plan = create_plan(self.repo, task_id="task-one", requested_outcome="Change A", expected_surfaces=["BUSINESS_LOGIC"])
        plan = approve(plan, source="conversation", proof_reference="message-1", enforcement_tier="RULE_ENFORCED")
        plan = begin(self.repo, plan)
        with self.assertRaises(ValidationError):
            begin(self.repo, plan)
        self.assertEqual([], check_material_drift(plan, ["BUSINESS_LOGIC"]))
        self.assertEqual(["surface:BILLING"], check_material_drift(plan, ["BUSINESS_LOGIC", "BILLING"]))

    def test_surface_aliases_normalization(self) -> None:
        self.assertEqual(
            ["BUSINESS_LOGIC", "COMPOSE_UI", "RESOURCE_UI", "XML_UI"],
            normalize_expected_surfaces(["code", "ui"]),
        )
        self.assertEqual(["LOCALIZATION"], normalize_expected_surfaces(["strings"]))
        self.assertEqual(["PERSISTENCE", "ROOM_SCHEMA"], normalize_expected_surfaces(["db"]))
        self.assertEqual(["MANIFEST_PERMISSION"], normalize_expected_surfaces(["permissions"]))
        self.assertEqual([], normalize_expected_surfaces(None))
        self.assertEqual([], normalize_expected_surfaces([]))

    def test_material_drift_with_surface_aliases(self) -> None:
        plan = create_plan(self.repo, task_id="task-alias", requested_outcome="Change A", expected_surfaces=["code", "ui"])
        self.assertEqual([], check_material_drift(plan, ["BUSINESS_LOGIC", "COMPOSE_UI"]))
        self.assertEqual(["surface:BILLING"], check_material_drift(plan, ["BUSINESS_LOGIC", "BILLING"]))

    def test_clean_repo_draft_defaults_to_app_surfaces_without_drift(self) -> None:
        import argparse
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id="clean-draft",
            outcome="Add feature",
            expected_surfaces="",
            expected_modules="",
            test_strategy="",
            device_strategy="",
            risks="",
            rollback="",
            external_write=[],
        )
        plan = draft(args)
        self.assertEqual(sorted(DEFAULT_APP_SURFACES), sorted(plan["expected_surfaces"]))
        self.assertEqual([], check_material_drift(plan, ["BUSINESS_LOGIC", "COMPOSE_UI"]))
        self.assertEqual(["surface:BILLING"], check_material_drift(plan, ["BUSINESS_LOGIC", "BILLING"]))
        self.assertEqual(["surface:SECURITY"], check_material_drift(plan, ["BUSINESS_LOGIC", "SECURITY"]))

    def test_pipeline_gates_ordered_by_execution_priority(self) -> None:
        classification = {
            "classification_sha256": "0" * 64,
            "surfaces": ["BUSINESS_LOGIC", "COMPOSE_UI"],
            "severity": "MEDIUM",
            "confidence": "HIGH",
            "changed_files": 2,
        }
        policy = decide(classification, KIT / "agents" / "skills")
        gates = policy["gates"]
        self.assertIn("preflight", gates)
        self.assertIn("unit_tests", gates)
        self.assertIn("device", gates)
        self.assertLess(gates.index("preflight"), gates.index("unit_tests"))
        self.assertLess(gates.index("unit_tests"), gates.index("device"))

    def test_base_change_invalidates_approval_before_begin(self) -> None:
        plan = create_plan(self.repo, task_id="task-two", requested_outcome="Change A", expected_surfaces=["BUSINESS_LOGIC"])
        plan = approve(plan, source="conversation", proof_reference="message-2", enforcement_tier="RULE_ENFORCED")
        write(self.repo / "app/src/main/kotlin/A.kt", "internal class Changed\n")
        with self.assertRaises(ValidationError):
            begin(self.repo, plan)

    def test_conversation_cannot_claim_hard_approval(self) -> None:
        plan = create_plan(self.repo, task_id="trust-one", requested_outcome="Change A", expected_surfaces=["BUSINESS_LOGIC"])
        with self.assertRaises(ValidationError):
            approve(plan, source="conversation", proof_reference="message", enforcement_tier="HARD_ENFORCED")

    def test_unplanned_module_is_material_drift(self) -> None:
        write(self.repo / "feature/build.gradle.kts", 'plugins { id("com.android.library") }\nandroid { namespace = "com.example.feature" }\n')
        write(self.repo / "feature/src/main/kotlin/F.kt", "internal class F\n")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "feature fixture")
        plan = create_plan(
            self.repo, task_id="module-drift", requested_outcome="Change app",
            expected_surfaces=["BUSINESS_LOGIC"], expected_modules=[":app"],
        )
        plan = approve(plan, source="conversation", proof_reference="message", enforcement_tier="RULE_ENFORCED")
        begin(self.repo, plan)
        write(self.repo / "feature/src/main/kotlin/F.kt", "internal class ChangedFeature\n")
        modules = changed_modules(self.repo, build_manifest(self.repo))
        self.assertEqual([":feature"], modules)
        self.assertEqual(["module:feature"], check_material_drift(plan, ["BUSINESS_LOGIC"], modules))

    def test_evidence_is_append_only_redacted_and_integrity_checked(self) -> None:
        store = EvidenceStore(self.repo / "state")
        path = store.write(
            snapshot="a" * 64, run_id="run-one", name="unit_tests", producer="run_tests_gate",
            harness_version="1.0.0", change_set="b" * 64, status="PASS",
            evidence={"executed": 2, "api_token": "secret-value"},
        )
        self.assertNotIn("secret-value", path.read_text(encoding="utf-8"))
        with self.assertRaises(ValidationError):
            store.write(
                snapshot="a" * 64, run_id="run-one", name="unit_tests", producer="run_tests_gate",
                harness_version="1.0.0", change_set="b" * 64, status="PASS", evidence={},
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "FAIL"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValidationError):
            store.read("a" * 64, "run-one", "unit_tests")

    def test_live_lock_is_not_evicted_by_age(self) -> None:
        root = self.repo / "state"
        with StateLock(root):
            with self.assertRaises(ValidationError):
                with StateLock(root, timeout_seconds=0.01):
                    pass

    def test_stale_corrupt_lock_is_recovered(self) -> None:
        root = self.repo / "state"
        root.mkdir(parents=True, exist_ok=True)
        lock = root / ".write.lock"
        write(lock, "not-json")
        old = lock.stat().st_mtime - 60
        os.utime(lock, (old, old))
        with StateLock(root, timeout_seconds=0.1):
            self.assertTrue(lock.exists())
        self.assertFalse(lock.exists())


class ArtifactAndVerifierTests(RepoCase):
    def test_adb_semantic_failure_cannot_pass_on_exit_zero(self) -> None:
        self.assertFalse(adb_result_ok(0, "Error type 3\nActivity class does not exist"))
        self.assertTrue(adb_result_ok(0, "Starting: Intent { cmp=com.example/.MainActivity }"))

    def test_split_apk_set_is_order_independent_and_tamper_evident(self) -> None:
        one = self.repo / "app/build/outputs/apk/debug/base.apk"
        two = self.repo / "app/build/outputs/apk/debug/config.en.apk"
        write(one, b"base")
        write(two, b"split")
        first = build_artifact_set(self.repo, ":app:assembleDebug", [two, one], application_id="com.test")
        second = build_artifact_set(self.repo, ":app:assembleDebug", [one, two], application_id="com.test")
        self.assertEqual(first["artifact_set_sha256"], second["artifact_set_sha256"])
        self.assertEqual([one.resolve(), two.resolve()], verify_artifact_set(self.repo, first))
        write(two, b"tampered")
        with self.assertRaises(Exception):
            verify_artifact_set(self.repo, first)

    def test_output_metadata_resolves_split_set(self) -> None:
        output = self.repo / "app/build/outputs/apk/debug"
        write(output / "base.apk", b"base")
        write(output / "config.xhdpi.apk", b"split")
        write(output / "output-metadata.json", json.dumps({
            "variantName": "Debug",
            "elements": [{"outputFile": "config.xhdpi.apk"}, {"outputFile": "base.apk"}],
        }))
        paths = resolve_artifacts(self.repo, ":app:assembleDebug")
        self.assertEqual(
            [(output / "base.apk").resolve(), (output / "config.xhdpi.apk").resolve()],
            paths,
        )

    def test_read_only_verifier_approves_one_bound_run(self) -> None:
        expected_policy = decide({
            "classification_sha256": "preliminary", "surfaces": ["BUSINESS_LOGIC"],
            "severity": "MEDIUM", "confidence": "HIGH", "changed_files": 1,
        }, KIT / "agents" / "skills")
        plan = create_plan(
            self.repo, task_id="verify-one", requested_outcome="Change logic",
            expected_surfaces=["BUSINESS_LOGIC"], expected_modules=[":app"],
            skills=expected_policy["skills"]["skills"],
        )
        plan = approve(plan, source="conversation", proof_reference="message-3", enforcement_tier="RULE_ENFORCED")
        plan = begin(self.repo, plan)
        write(self.repo / "app/src/main/kotlin/A.kt", "internal class Changed\n")
        manifest = build_manifest(self.repo)
        classification = classify(self.repo)
        policy = decide(classification, KIT / "agents" / "skills")
        self.assertEqual(["BUSINESS_LOGIC"], policy["surfaces"])
        plan["status"] = "VERIFYING"
        directory = self.repo / ".agents/state/tasks/verify-one"
        directory.mkdir(parents=True)
        plan_path, policy_path, manifest_path = directory / "plan.json", directory / "policy.json", directory / "manifest.json"
        save_plan(plan_path, plan)
        atomic_write_json(policy_path, policy)
        atomic_write_json(manifest_path, manifest)
        state = self.repo / ".agents/state"
        store = EvidenceStore(state)
        common = dict(snapshot=manifest["delivery_snapshot_sha256"], run_id="run-verify", harness_version=HARNESS_VERSION, change_set=manifest["change_set_sha256"])
        store.write(**common, name="unit_tests", producer="run_tests_gate", status="PASS", evidence={"executed": 2})
        store.write(**common, name="preflight", producer="preflight_check", status="PASS", evidence={})
        store.write(**common, name="assemble", producer="run_gradle_task", status="PASS", evidence={"artifact_set_sha256": "f" * 64})
        store.write(**common, name="reviews", producer="review_orchestrator", status="PASS", evidence={"reviewers": policy["reviewers"], "is_truncated": False, "blocking_findings": []})
        result = verify(self.repo, plan_path=plan_path, policy_path=policy_path, manifest_path=manifest_path, state_root=state, run_id="run-verify")
        self.assertEqual("APPROVED", result["status"], result)
        tampered_policy = dict(policy)
        tampered_policy["gates"] = [item for item in policy["gates"] if item != "unit_tests"]
        tampered_policy["policy_sha256"] = canonical_sha256({key: value for key, value in tampered_policy.items() if key != "policy_sha256"})
        atomic_write_json(policy_path, tampered_policy)
        tampered_result = verify(self.repo, plan_path=plan_path, policy_path=policy_path, manifest_path=manifest_path, state_root=state, run_id="run-verify")
        self.assertEqual("BLOCKED", tampered_result["status"])
        self.assertIn("deterministic policy", " ".join(tampered_result["blocked_by"]))
        atomic_write_json(policy_path, policy)
        before = {path.relative_to(state).as_posix(): sha256_file(path) for path in state.rglob("*.json")}
        verify(self.repo, plan_path=plan_path, policy_path=policy_path, manifest_path=manifest_path, state_root=state, run_id="run-verify")
        after = {path.relative_to(state).as_posix(): sha256_file(path) for path in state.rglob("*.json")}
        self.assertEqual(before, after)


class LifecycleTests(RepoCase):
    def test_safe_harness_cli_inspection_commands_need_no_active_plan(self) -> None:
        for command in (
            "python C:/kit/harness_cli.py version",
            "python C:/kit/harness_cli.py doctor --repo .",
            "python C:/kit/harness_cli.py --help",
        ):
            self.assertTrue(command_allowed(self.repo, command)[0], command)

    def test_windows_python_path_is_literal_in_hook_commands(self) -> None:
        hooks = self.repo / ".agents/hooks.json"
        write(hooks, json.dumps({"hooks": [{"command": "python agents/scripts/preflight_check.py"}]}))
        python_path = r"C:\Users\Harness User\Python\python.exe"
        logs = sync_hooks_json(self.repo, python_path, dry_run=False)
        payload = json.loads(hooks.read_text(encoding="utf-8"))
        self.assertEqual(
            python_path + " agents/scripts/preflight_check.py",
            payload["hooks"][0]["command"],
        )
        self.assertEqual(
            ["rewrote .agents/hooks.json commands to use the configured python"],
            logs,
        )

    def test_release_checksums_survive_windows_autocrlf_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            checkout = Path(raw) / "kit"
            proc = subprocess.run(
                ["git", "-c", "core.autocrlf=true", "clone", "--quiet", "--no-local", str(KIT), str(checkout)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            attr = subprocess.run(
                ["git", "check-attr", "eol", "--", "agents/.gitignore"],
                cwd=checkout,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, attr.returncode, attr.stderr)
            self.assertEqual("agents/.gitignore: eol: lf", attr.stdout.strip())
            self.assertNotIn(b"\r\n", (checkout / "agents/.gitignore").read_bytes())
            proc_diff = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=str(KIT), capture_output=True, text=True, check=False)
            if proc_diff.returncode == 0:
                for line in proc_diff.stdout.splitlines():
                    rel = line.strip()
                    if rel and (KIT / rel).is_file():
                        dest = checkout / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes((KIT / rel).read_bytes())
            _validate_kit(checkout)
            release = subprocess.run(
                [sys.executable, str(checkout / "scripts_dev/validate_release.py")],
                cwd=checkout,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, release.returncode, release.stdout + release.stderr)

    def _answers(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture",
            "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity",
            "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest",
            "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"],
            "pm_provider": "zoho_sprints",
            "zoho_mcp": "disable",
            "backup": True,
        }))

    def test_install_update_preserve_and_uninstall_restore(self) -> None:
        original = "# User-owned project instructions\n"
        write(self.repo / "AGENTS.md", original)
        self._answers()
        installed = install(self.repo, KIT)
        self.assertEqual("PASS", installed["status"])
        self.assertFalse(any("__pycache__" in item["path"] or item["path"].endswith((".pyc", ".pyo")) for item in installed["ownership"]["entries"]))
        self.assertTrue((self.repo / OWNERSHIP_RELATIVE).is_file())
        reference = self.repo / ".agents/skills/android-harness/references/architecture-guidelines.md"
        write(reference, reference.read_text(encoding="utf-8") + "\nProject-tailored rule.\n")
        updated = update(self.repo, KIT)
        self.assertEqual("PASS", updated["status"])
        self.assertIn("Project-tailored rule.", reference.read_text(encoding="utf-8"))
        preview = uninstall(self.repo)
        self.assertEqual("DRY_RUN", preview["status"])
        removed = uninstall(self.repo, apply=True)
        self.assertEqual("PASS", removed["status"])
        self.assertFalse((self.repo / ".agents").exists())
        self.assertEqual(original, (self.repo / "AGENTS.md").read_text(encoding="utf-8"))

    def test_legacy_install_is_refused(self) -> None:
        self._answers()
        write(self.repo / ".agents/VERSION", "0.27.24\n")
        with self.assertRaises(ValidationError):
            install(self.repo, KIT)

    def test_atomic_legacy_replacement_preserves_project_references(self) -> None:
        self._answers()
        write(self.repo / ".agents/VERSION", "0.27.24\n")
        custom = self.repo / ".agents/skills/android-harness/references/ads-project-policy.md"
        write(custom, "Project-specific ads policy.\n")
        defaults = self.repo / ".agents/mcp/zoho_sprints/workflow_defaults.json"
        write(defaults, '{"project":"fixture"}\n')
        result = replace_legacy(self.repo, KIT)
        self.assertEqual("PASS", result["status"])
        self.assertEqual("Project-specific ads policy.\n", custom.read_text(encoding="utf-8"))
        self.assertEqual('{"project":"fixture"}\n', defaults.read_text(encoding="utf-8"))
        self.assertTrue((self.repo / OWNERSHIP_RELATIVE).is_file())

    def test_emulator_only_is_generated_into_product_policy(self) -> None:
        self._answers()
        answers_path = self.repo / ".harness-setup/answers.json"
        answers = json.loads(answers_path.read_text(encoding="utf-8"))
        answers["device_policy"] = "emulator-only"
        write(answers_path, json.dumps(answers))
        install(self.repo, KIT)
        product = (self.repo / ".agents/scripts/_product.py").read_text(encoding="utf-8")
        self.assertIn("DEVICE_TARGET_POLICY = 'emulator-only'", product)

    def test_unrelated_host_config_is_not_claimed_or_removed(self) -> None:
        self._answers()
        unrelated = self.repo / ".claude/settings.json"
        write(unrelated, '{"userOwned": true}\n')
        result = install(self.repo, KIT)
        owned = {item["path"] for item in result["ownership"]["entries"]}
        self.assertNotIn(".claude/settings.json", owned)
        uninstall(self.repo, apply=True)
        self.assertEqual('{"userOwned": true}\n', unrelated.read_text(encoding="utf-8"))

    def test_install_does_not_hide_unrelated_tool_directory_files(self) -> None:
        self._answers()
        workflow = self.repo / ".github/workflows/user-ci.yml"
        write(workflow, "name: user-ci\n")
        install(self.repo, KIT)
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn(".github/workflows/user-ci.yml", proc.stdout)

    def test_failed_update_rolls_back_old_engine_and_tailoring(self) -> None:
        self._answers()
        install(self.repo, KIT)
        reference = self.repo / ".agents/skills/android-harness/references/architecture-guidelines.md"
        write(reference, reference.read_text(encoding="utf-8") + "\nTailored-before-failure.\n")
        with mock.patch.object(lifecycle_module, "_restore_preserved", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                update(self.repo, KIT)
        self.assertIn("Tailored-before-failure.", reference.read_text(encoding="utf-8"))
        journal = json.loads((self.repo / ".harness-setup/update-journal.json").read_text(encoding="utf-8"))
        self.assertEqual("ROLLED_BACK", journal["status"])

    def test_installed_custom_variant_uses_exact_task(self) -> None:
        self._answers()
        answers_path = self.repo / ".harness-setup/answers.json"
        answers = json.loads(answers_path.read_text(encoding="utf-8"))
        answers.update({
            "assemble": ":app:assembleFreeEuStaging", "build_variant": "FreeEuStaging",
            "flavor": "FreeEuStaging", "flavor_mode": "custom_variant",
        })
        write(answers_path, json.dumps(answers))
        install(self.repo, KIT)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.repo / ".agents/scripts")
        proc = subprocess.run(
            [sys.executable, "-c", "from _variants import resolve_or_raise; print(resolve_or_raise(None)[1])"],
            cwd=self.repo, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual(":app:assembleFreeEuStaging", proc.stdout.strip())

    def test_diagnostic_preflight_needs_no_task_and_writes_no_evidence(self) -> None:
        self._answers()
        install(self.repo, KIT)
        proc = subprocess.run(
            [sys.executable, str(self.repo / ".agents/scripts/preflight_check.py"), "--diagnostic"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn("diagnostic mode", proc.stdout)
        self.assertFalse((self.repo / ".agents/state/results").exists())


class EndToEndWorkflowTests(RepoCase):
    def test_sensitive_final_approval_is_separate_and_snapshot_bound(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "tools": ["codex"],
            "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        task_id = "sensitive-explicit"
        common = {"repo": str(self.repo), "task_id": task_id}
        draft(Namespace(
            **common, outcome="Harden TLS", expected_surfaces="SECURITY,BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Security tests", device_strategy="Policy selected",
            risks="TLS regression", rollback="Restore source", external_write=[],
        ))
        record_approval(Namespace(
            **common, source="conversation", proof_reference="plan-message",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(Namespace(**common))
        write(self.repo / "app/src/main/kotlin/A.kt", "internal val verifier: HostnameVerifier? = null\n")
        current = prepare_verification(Namespace(**common))
        store = EvidenceStore(state_root(self.repo))
        with self.assertRaises(ValidationError):
            store.read(current["delivery_snapshot_sha256"], current["run_id"], "sensitive_approval")
        with self.assertRaises(ValidationError):
            record_sensitive_approval(Namespace(
                **common, source="invalid_source", proof_reference="agent-text",
                enforcement_tier="RULE_ENFORCED",
            ))
        with self.assertRaises(ValidationError):
            record_sensitive_approval(Namespace(
                **common, source="conversation", proof_reference="   ",
                enforcement_tier="RULE_ENFORCED",
            ))
        with self.assertRaises(ValidationError):
            record_sensitive_approval(Namespace(
                **common, source="conversation", proof_reference="agent-text",
                enforcement_tier="HARD_ENFORCED",
            ))
        result = record_sensitive_approval(Namespace(
            **common, source="conversation", proof_reference="chat-confirmation",
            enforcement_tier="RULE_ENFORCED",
        ))
        self.assertEqual("PASS", result["status"])
        record = store.read(current["delivery_snapshot_sha256"], current["run_id"], "sensitive_approval")
        self.assertEqual("conversation", record["evidence"]["approval_source"])

    def test_approved_change_reaches_delivery_only_with_exact_evidence(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest",
            "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"], "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        task_id = "e2e-approved"
        common = {"repo": str(self.repo), "task_id": task_id}
        plan = draft(Namespace(
            **common, outcome="Change business behavior", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore changed source",
        ))
        self.assertEqual("AWAITING_DEVELOPER_APPROVAL", plan["status"])
        approved = record_approval(Namespace(
            **common, source="conversation", proof_reference="test-message",
            enforcement_tier="RULE_ENFORCED",
        ))
        self.assertEqual("APPROVED", approved["status"])
        self.assertEqual("IMPLEMENTING", begin_task(Namespace(**common))["status"])
        write(self.repo / "app/src/main/kotlin/A.kt", "internal class Changed\n")
        current = prepare_verification(Namespace(**common))
        package, _ = build_package(self.repo, task_id)
        directory = self.repo / ".harness-setup/reviewer-fixtures"
        policy = json.loads(Path(current["policy"]).read_text(encoding="utf-8"))
        package_sha = sha256_file(package)
        reports: list[Path] = []
        for reviewer in policy["reviewers"]:
            report = directory / f"{reviewer}.json"
            write(report, json.dumps({
                "schema_version": 1, "reviewer": reviewer, "package_sha256": package_sha,
                "delivery_snapshot_sha256": current["delivery_snapshot_sha256"],
                "change_set_sha256": current["change_set_sha256"], "verdict": "PASS", "findings": [],
            }))
            reports.append(report)
        ingest(self.repo, task_id, reports)
        store = EvidenceStore(state_root(self.repo))
        evidence_common = dict(
            snapshot=current["delivery_snapshot_sha256"], run_id=current["run_id"],
            harness_version=HARNESS_VERSION, change_set=current["change_set_sha256"], status="PASS",
        )
        store.write(**evidence_common, name="unit_tests", producer="run_tests_gate", evidence={"executed": 1})
        store.write(**evidence_common, name="preflight", producer="preflight_check", evidence={})
        store.write(**evidence_common, name="assemble", producer="run_gradle_task", evidence={})
        ready = complete(Namespace(**common))
        self.assertEqual("READY_FOR_DELIVERY", ready["status"])
        self.assertEqual(current["delivery_snapshot_sha256"], ready["ready_delivery_snapshot_sha256"])

    def test_sensitive_approval_via_conversation_passes_verifier(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"], "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        task_id = "sensitive-convo-e2e"
        common = {"repo": str(self.repo), "task_id": task_id}
        draft(Namespace(
            **common, outcome="Harden Security", expected_surfaces="SECURITY,BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore source", external_write=[],
        ))
        record_approval(Namespace(
            **common, source="conversation", proof_reference="chat-approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(Namespace(**common))
        write(self.repo / "app/src/main/kotlin/A.kt", "internal val verifier: HostnameVerifier? = null\n")
        current = prepare_verification(Namespace(**common))
        package, _ = build_package(self.repo, task_id)
        package_sha = sha256_file(package)
        directory = self.repo / ".harness-setup/reviewer-fixtures"
        policy = json.loads(Path(current["policy"]).read_text(encoding="utf-8"))
        reports: list[Path] = []
        for reviewer in policy["reviewers"]:
            report = directory / f"{reviewer}.json"
            write(report, json.dumps({
                "schema_version": 1, "reviewer": reviewer, "package_sha256": package_sha,
                "delivery_snapshot_sha256": current["delivery_snapshot_sha256"],
                "change_set_sha256": current["change_set_sha256"], "verdict": "PASS", "findings": [],
            }))
            reports.append(report)
        ingest(self.repo, task_id, reports)
        store = EvidenceStore(state_root(self.repo))
        evidence_common = dict(
            snapshot=current["delivery_snapshot_sha256"], run_id=current["run_id"],
            harness_version=HARNESS_VERSION, change_set=current["change_set_sha256"], status="PASS",
        )
        store.write(**evidence_common, name="unit_tests", producer="run_tests_gate", evidence={"executed": 1})
        store.write(**evidence_common, name="preflight", producer="preflight_check", evidence={})
        store.write(**evidence_common, name="assemble", producer="run_gradle_task", evidence={})
        record_sensitive_approval(Namespace(
            **common, source="conversation", proof_reference="chat-confirmed",
            enforcement_tier="RULE_ENFORCED",
        ))
        ready = complete(Namespace(**common))
        self.assertEqual("READY_FOR_DELIVERY", ready["status"])
        self.assertEqual(current["delivery_snapshot_sha256"], ready["ready_delivery_snapshot_sha256"])

    def test_record_review_cli_staged_verdicts_e2e(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest",
            "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"], "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        task_id = "e2e-review-cli"
        common = {"repo": str(self.repo), "task_id": task_id}
        draft(Namespace(
            **common, outcome="Test review CLI", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore changed source",
        ))
        record_approval(Namespace(
            **common, source="conversation", proof_reference="test-msg",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(Namespace(**common))
        write(self.repo / "app/src/main/kotlin/A.kt", "internal class ChangedReview\n")
        current = prepare_verification(Namespace(**common))
        package, _ = build_package(self.repo, task_id)
        package_sha = sha256_file(package)
        policy = json.loads(Path(current["policy"]).read_text(encoding="utf-8"))
        reviewers = policy["reviewers"]
        first_rev = reviewers[0]
        proc = subprocess.run(
            [sys.executable, str(self.repo / ".agents/scripts/record_review.py"), "--task", task_id, "--reviewer", first_rev, "--verdict", "PASS", "--evidence-pkg", package_sha[:12]],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("STAGED_REVIEW", proc.stdout)
        proc = subprocess.run(
            [sys.executable, str(self.repo / ".agents/scripts/record_review.py"), "--task", task_id, "--status"],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn(f"STAGED_REVIEWS=1/{len(reviewers)}", proc.stdout)
        for rev in reviewers[1:]:
            proc = subprocess.run(
                [sys.executable, str(self.repo / ".agents/scripts/record_review.py"), "--task", task_id, "--reviewer", rev, "--verdict", "PASS", "--evidence-pkg", package_sha[:12]],
                cwd=self.repo, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("REVIEW_EVIDENCE=", proc.stdout)
        store = EvidenceStore(state_root(self.repo))
        review_record = store.read(current["delivery_snapshot_sha256"], current["run_id"], "reviews")
        self.assertEqual("PASS", review_record["status"])

    def test_review_package_deduplicates_tracked_added_files(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"], "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        task_id = "test-pkg-dedup"
        common = {"repo": str(self.repo), "task_id": task_id}
        draft(Namespace(
            **common, outcome="Test dedup", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore", external_write=[],
        ))
        record_approval(Namespace(
            **common, source="conversation", proof_reference="chat-approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(Namespace(**common))
        new_file = self.repo / "app/src/main/kotlin/NewFeature.kt"
        write(new_file, "package com.fixture\n\nclass NewFeature {\n    fun hello() = 42\n}\n")
        run_git(self.repo, "add", "app/src/main/kotlin/NewFeature.kt")
        prepare_verification(Namespace(**common))
        package_path, _ = build_package(self.repo, task_id)
        pkg_content = package_path.read_text(encoding="utf-8")
        self.assertIn("+++ b/app/src/main/kotlin/NewFeature.kt", pkg_content)
        self.assertNotIn("## NEW FILE app/src/main/kotlin/NewFeature.kt", pkg_content)
        self.assertNotIn("## NEW UNTRACKED FILE app/src/main/kotlin/NewFeature.kt", pkg_content)

    def test_check_strings_deletion_parity_in_diff_scope(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"], "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        base_strings = self.repo / "app/src/main/res/values/strings.xml"
        loc_strings = self.repo / "app/src/main/res/values-ar/strings.xml"
        write(base_strings, '<resources><string name="app_name">App</string><string name="logout">Logout</string></resources>\n')
        write(loc_strings, '<resources><string name="app_name">تطبيق</string><string name="logout">خروج</string></resources>\n')
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "initial strings")
        # Delete 'logout' from base only
        write(base_strings, '<resources><string name="app_name">App</string></resources>\n')
        script = self.repo / ".agents/scripts/check_strings.py"
        proc = subprocess.run([sys.executable, str(script)], cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual(1, proc.returncode, "diff-scoped should catch deleted key missing in base vs ar")
        self.assertIn("logout", proc.stdout)
        # Now delete 'logout' from ar as well
        write(loc_strings, '<resources><string name="app_name">تطبيق</string></resources>\n')
        proc2 = subprocess.run([sys.executable, str(script)], cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual(0, proc2.returncode, proc2.stdout + proc2.stderr)

    def test_workflow_deliver_lifecycle(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"], "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        task_id = "test-deliver-lifecycle"
        common = {"repo": str(self.repo), "task_id": task_id}
        draft(Namespace(
            **common, outcome="Test delivery lifecycle", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore", external_write=[], force=False,
        ))
        record_approval(Namespace(
            **common, source="conversation", proof_reference="chat-approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(Namespace(**common))
        with self.assertRaises(ValidationError):
            deliver_task(Namespace(**common))

        write(self.repo / "app/src/main/kotlin/Deliv.kt", "package com.fixture\nclass Deliv\n")
        current = prepare_verification(Namespace(**common))
        with self.assertRaises(ValidationError):
            deliver_task(Namespace(**common))

        policy = json.loads(Path(current["policy"]).read_text(encoding="utf-8"))
        store = EvidenceStore(state_root(self.repo))
        evidence_common = dict(
            snapshot=current["delivery_snapshot_sha256"], run_id=current["run_id"],
            harness_version=HARNESS_VERSION, change_set=current["change_set_sha256"], status="PASS",
        )
        store.write(**evidence_common, name="unit_tests", producer="run_tests_gate", evidence={"executed": 1})
        store.write(**evidence_common, name="preflight", producer="preflight_check", evidence={})
        store.write(**evidence_common, name="assemble", producer="run_gradle_task", evidence={})
        store.write(**evidence_common, name="reviews", producer="review_orchestrator", evidence={"reviewers": policy.get("reviewers") or [], "is_truncated": False, "blocking_findings": []})
        complete(Namespace(**common))

        res = deliver_task(Namespace(**common))
        self.assertEqual("DELIVERED", res["status"])
        self.assertIn("delivered_at", res)

        active_task = self.repo / ".agents/state/active-task.json"
        self.assertFalse(active_task.exists())

    def test_workflow_draft_collision_barrier_and_auto_delivery(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"], "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        task1 = "task-one"
        common1 = {"repo": str(self.repo), "task_id": task1}
        draft(Namespace(
            **common1, outcome="Task 1", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore", external_write=[], force=False,
        ))
        record_approval(Namespace(
            **common1, source="conversation", proof_reference="chat-approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(Namespace(**common1))

        write(self.repo / "app/src/main/kotlin/DirtyFile.kt", "package com.fixture\nclass DirtyFile\n")

        task_temp = "task-temp"
        common_temp = {"repo": str(self.repo), "task_id": task_temp}
        with self.assertRaises(ValidationError) as ctx1:
            draft(Namespace(
                **common_temp, outcome="Task Temp", expected_surfaces="BUSINESS_LOGIC",
                expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
                risks="", rollback="Restore", external_write=[], force=False,
            ))
        self.assertIn("implementing", str(ctx1.exception).lower())

        current1 = prepare_verification(Namespace(**common1))
        policy1 = json.loads(Path(current1["policy"]).read_text(encoding="utf-8"))
        store = EvidenceStore(state_root(self.repo))
        evidence_common = dict(
            snapshot=current1["delivery_snapshot_sha256"], run_id=current1["run_id"],
            harness_version=HARNESS_VERSION, change_set=current1["change_set_sha256"], status="PASS",
        )
        store.write(**evidence_common, name="unit_tests", producer="run_tests_gate", evidence={"executed": 1})
        store.write(**evidence_common, name="preflight", producer="preflight_check", evidence={})
        store.write(**evidence_common, name="assemble", producer="run_gradle_task", evidence={})
        store.write(**evidence_common, name="reviews", producer="review_orchestrator", evidence={"reviewers": policy1.get("reviewers") or [], "is_truncated": False, "blocking_findings": []})
        complete(Namespace(**common1))

        with self.assertRaises(ValidationError) as ctx2:
            draft(Namespace(
                **common_temp, outcome="Task Temp", expected_surfaces="BUSINESS_LOGIC",
                expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
                risks="", rollback="Restore", external_write=[], force=False,
            ))
        self.assertIn("uncommitted changes", str(ctx2.exception).lower())

        task_forced = draft(Namespace(
            **common_temp, outcome="Task Temp Forced", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore", external_write=[], force=True,
        ))
        self.assertEqual("AWAITING_DEVELOPER_APPROVAL", task_forced["status"])

        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "commit task 1 files")

        task2 = "task-two"
        common2 = {"repo": str(self.repo), "task_id": task2}
        draft(Namespace(
            **common2, outcome="Task 2", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore", external_write=[], force=False,
        ))

        task1_plan = read_json(task_dir(self.repo, task1) / "plan.json")
        self.assertEqual("DELIVERED", task1_plan["status"])

    def test_device_gating_blocks_implementing_and_enforces_prerequisites(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"], "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)
        task_id = "test-device-gate"
        common = {"repo": str(self.repo), "task_id": task_id}
        draft(Namespace(
            **common, outcome="Device test gate", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore", external_write=[], force=False,
        ))
        record_approval(Namespace(
            **common, source="conversation", proof_reference="chat-approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(Namespace(**common))

        allowed, reason = command_allowed(self.repo, "python .agents/scripts/run_device.py install-start")
        self.assertFalse(allowed)
        self.assertIn("device operation", reason.lower())

        proc = subprocess.run(
            [sys.executable, str(self.repo / ".agents/scripts/run_device.py"), "install-start"],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("implementing", (proc.stderr + proc.stdout).lower())

        write(self.repo / "app/src/main/kotlin/DevGate.kt", "package com.fixture\nclass DevGate\n")
        prepare_verification(Namespace(**common))

        proc2 = subprocess.run(
            [sys.executable, str(self.repo / ".agents/scripts/run_device.py"), "install-start"],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(0, proc2.returncode)
        self.assertIn("preflight", (proc2.stderr + proc2.stdout).lower())

    def test_developer_review_override(self) -> None:
        write(self.repo / ".harness-setup/answers.json", json.dumps({
            "product": "Fixture", "application_id": "com.example.fixture",
            "launcher": "com.example.fixture/.MainActivity", "assemble": ":app:assembleDebug",
            "unit_test_task": ":app:testDebugUnitTest", "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["codex"], "pm_provider": "none", "zoho_mcp": "disable", "backup": True,
        }))
        install(self.repo, KIT)

        task_id = "test-override-allowed"
        common = {"repo": str(self.repo), "task_id": task_id}
        draft(Namespace(
            **common, outcome="Logic change", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Unit tests", device_strategy="Policy selected",
            risks="", rollback="Restore", external_write=[], force=False,
        ))
        record_approval(Namespace(
            **common, source="conversation", proof_reference="chat-approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(Namespace(**common))
        write(self.repo / "app/src/main/kotlin/Logic.kt", "package com.fixture\nclass Logic\n")
        current = prepare_verification(Namespace(**common))

        proc = subprocess.run(
            [
                sys.executable, str(self.repo / ".agents/scripts/record_review.py"),
                "--task", task_id,
                "--override-reviews",
                "--proof-reference", "Developer approved override in chat",
                "--source", "conversation",
            ],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr + proc.stdout)
        self.assertIn("DEVELOPER_OVERRIDE", proc.stdout)

        store = EvidenceStore(state_root(self.repo))
        review_record = store.read(current["delivery_snapshot_sha256"], current["run_id"], "reviews")
        self.assertEqual("PASS", review_record["status"])
        self.assertTrue(review_record["evidence"].get("developer_override"))

        evidence_common = dict(
            snapshot=current["delivery_snapshot_sha256"], run_id=current["run_id"],
            harness_version=HARNESS_VERSION, change_set=current["change_set_sha256"], status="PASS",
        )
        store.write(**evidence_common, name="unit_tests", producer="run_tests_gate", evidence={"executed": 1})
        store.write(**evidence_common, name="preflight", producer="preflight_check", evidence={})
        store.write(**evidence_common, name="assemble", producer="run_gradle_task", evidence={})
        ready = complete(Namespace(**common))
        self.assertEqual("READY_FOR_DELIVERY", ready["status"])

        task_id_sec = "test-override-forbidden"
        common_sec = {"repo": str(self.repo), "task_id": task_id_sec}
        draft(Namespace(
            **common_sec, outcome="Security change", expected_surfaces="SECURITY,BUSINESS_LOGIC",
            expected_modules="app", test_strategy="Security tests", device_strategy="Policy selected",
            risks="", rollback="Restore", external_write=[], force=True,
        ))
        record_approval(Namespace(
            **common_sec, source="conversation", proof_reference="chat-approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(Namespace(**common_sec))
        write(self.repo / "app/src/main/kotlin/Sec.kt", "package com.fixture\nimport javax.net.ssl.HostnameVerifier\nclass Sec {\n    val v: HostnameVerifier? = null\n}\n")
        prepare_verification(Namespace(**common_sec))

        proc_sec = subprocess.run(
            [
                sys.executable, str(self.repo / ".agents/scripts/record_review.py"),
                "--task", task_id_sec,
                "--override-reviews",
                "--proof-reference", "Developer approved override in chat",
            ],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(0, proc_sec.returncode)
        self.assertIn("strictly forbidden", (proc_sec.stderr + proc_sec.stdout).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
