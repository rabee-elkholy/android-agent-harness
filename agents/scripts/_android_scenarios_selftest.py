"""30-Scenario Android Regression Matrix Suite.

Tests harness behavior across 30 real-world Android development scenarios:
  - Scenarios 01–04: UI & Logic (ViewModel, Compose, XML View, Resource UI)
  - Scenarios 05–07: Localization (New string, Deleted string, Missing locale)
  - Scenarios 08–10: Room & DB (Entity change, Deleted entity, Migration)
  - Scenarios 11–12: Sensitive Context (Billing callback, Auth in long function)
  - Scenarios 13–17: Architecture & Build (Coroutines, Network, Manifest, Gradle deps, ProGuard)
  - Scenarios 18–20: Filesystem & Generated Code (Generated error, New file, Rename/move)
  - Scenarios 21–24: Verification & Baseline (Known baseline, Different baseline failure, ADB offline, Stale gate)
  - Scenarios 25–28: Workflow & Authority (Pure logic no-device, Concurrent edits, Scope drift, Follow-up)
  - Scenarios 29–30: Reviews & Release (Reviewer env failure, Release version reuse)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
KIT = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(KIT))

from _env_codes import EXIT_ENV, classify_adb_failure
from _repo_files import ChangedFile
from _vnext_common import ValidationError, canonical_sha256, read_json, sha256_file
from baseline_capture import fingerprint, normalize_failure_message
from change_classifier import _enclosing_structural_context, classify
from delivery_manifest import build_manifest, is_delivery_relevant
from final_verifier import _validate_artifact
from plan_authority import check_material_drift, create_plan, normalize_expected_surfaces
from pre_tool_safety import DANGEROUS
from review_policy import decide, decide_later_round


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class AndroidScenariosSelftest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name).resolve()
        _run_git(self.repo, "init", "-q")
        _run_git(self.repo, "config", "user.name", "Scenario Test")
        _run_git(self.repo, "config", "user.email", "scenario@example.invalid")
        _run_git(self.repo, "config", "core.autocrlf", "true")

        # Basic Android fixture structure
        _write_file(self.repo / "gradlew", "#!/bin/sh\nexit 0\n")
        os.chmod(self.repo / "gradlew", 0o755)
        _write_file(self.repo / "settings.gradle.kts", 'rootProject.name = "ScenarioApp"\ninclude(":app")\n')
        _write_file(self.repo / "app/build.gradle.kts", 'plugins { id("com.android.application") }\n')
        _write_file(
            self.repo / "app/src/main/AndroidManifest.xml",
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '    <application android:label="ScenarioApp">\n'
            '        <activity android:name=".MainActivity" android:exported="true">\n'
            '            <intent-filter>\n'
            '                <action android:name="android.intent.action.MAIN" />\n'
            '                <category android:name="android.intent.category.LAUNCHER" />\n'
            '            </intent-filter>\n'
            '        </activity>\n'
            '    </application>\n'
            '</manifest>\n',
        )
        _write_file(
            self.repo / "app/src/main/kotlin/com/example/MainActivity.kt",
            "package com.example\n\nclass MainActivity\n",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "initial commit")

        self.skills_root = KIT / "agents" / "skills"
        (self.repo / ".agents" / "state").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- Scenario 01: Tiny ViewModel Business Logic Regression ---
    def test_scenario_01_viewmodel_business_logic_regression(self) -> None:
        vm_file = self.repo / "app/src/main/kotlin/com/example/UserViewModel.kt"
        _write_file(
            vm_file,
            "package com.example\n\nclass UserViewModel {\n    fun isValid(age: Int): Boolean = age >= 18\n}\n",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "add viewmodel")

        # Mutate condition only
        _write_file(
            vm_file,
            "package com.example\n\nclass UserViewModel {\n    fun isValid(age: Int): Boolean = age > 18\n}\n",
        )

        classification = classify(self.repo)
        self.assertIn("BUSINESS_LOGIC", classification["surfaces"])
        self.assertNotIn("COMPOSE_UI", classification["surfaces"])
        self.assertNotIn("ROOM_SCHEMA", classification["surfaces"])

        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertIn("bug-reviewer-agent", policy["reviewers"])
        self.assertIn("regression-impact-reviewer-agent", policy["reviewers"])
        # Must not require physical device for pure logic
        self.assertFalse(policy["device_required"])
        self.assertNotIn("device", policy["gates"])
        self.assertIn("unit_tests", policy["gates"])

    # --- Scenario 02: Compose UI State Change ---
    def test_scenario_02_compose_ui_state_change(self) -> None:
        compose_file = self.repo / "app/src/main/kotlin/com/example/UserScreen.kt"
        _write_file(
            compose_file,
            "package com.example\nimport androidx.compose.runtime.Composable\n"
            "@Composable\nfun UserScreen(name: String) {\n    val color = if (name.isEmpty()) 0 else 1\n}\n",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "add compose screen")

        # Mutate inside screen without touching the @Composable annotation line
        _write_file(
            compose_file,
            "package com.example\nimport androidx.compose.runtime.Composable\n"
            "@Composable\nfun UserScreen(name: String) {\n    val color = if (name.isEmpty()) 2 else 1\n}\n",
        )

        classification = classify(self.repo)
        self.assertIn("COMPOSE_UI", classification["surfaces"])

        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertTrue(policy["device_required"])
        self.assertIn("device", policy["gates"])

    # --- Scenario 03: XML View Screen Change ---
    def test_scenario_03_xml_view_screen_change(self) -> None:
        layout_file = self.repo / "app/src/main/res/layout/activity_detail.xml"
        _write_file(
            layout_file,
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"\n'
            '    android:layout_width="match_parent"\n'
            '    android:layout_height="match_parent">\n'
            '    <TextView android:id="@+id/title" android:layout_width="wrap_content" android:layout_height="wrap_content" />\n'
            '</LinearLayout>\n',
        )

        classification = classify(self.repo)
        self.assertIn("XML_UI", classification["surfaces"])
        self.assertNotIn("COMPOSE_UI", classification["surfaces"])

        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertTrue(policy["device_required"])
        self.assertIn("device", policy["gates"])

    # --- Scenario 04: Resource-Only UI Change ---
    def test_scenario_04_resource_only_ui_change(self) -> None:
        drawable_file = self.repo / "app/src/main/res/drawable/ic_status.xml"
        _write_file(
            drawable_file,
            '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
            '    android:width="24dp" android:height="24dp" android:viewportWidth="24" android:viewportHeight="24">\n'
            '    <path android:fillColor="#FF000000" android:pathData="M12,2L2,22h20L12,2z" />\n'
            '</vector>\n',
        )

        classification = classify(self.repo)
        self.assertEqual(["RESOURCE_UI"], classification["surfaces"])

        policy = decide(classification, self.skills_root, project_kind="application")
        # Micro-eligible resource-only change skips semantic reviewer roster
        self.assertTrue(policy["micro_eligible"])
        self.assertEqual([], policy["reviewers"])
        self.assertNotIn("unit_tests", policy["gates"])

    # --- Scenario 05: New Localized String ---
    def test_scenario_05_new_localized_string(self) -> None:
        base_xml = self.repo / "app/src/main/res/values/strings.xml"
        ar_xml = self.repo / "app/src/main/res/values-ar/strings.xml"
        _write_file(base_xml, '<resources><string name="welcome">Welcome %s</string></resources>\n')
        _write_file(ar_xml, '<resources><string name="welcome">أهلا %s</string></resources>\n')

        classification = classify(self.repo)
        self.assertIn("LOCALIZATION", classification["surfaces"])

        script = SCRIPTS / "check_strings.py"
        env = {**os.environ, "HARNESS_REPO": str(self.repo)}
        res = subprocess.run([sys.executable, str(script)], cwd=str(self.repo), capture_output=True, text=True, env=env, check=False)
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)

    # --- Scenario 06: Deleted Translation Key ---
    def test_scenario_06_deleted_translation_key_diff_scope(self) -> None:
        base_xml = self.repo / "app/src/main/res/values/strings.xml"
        ar_xml = self.repo / "app/src/main/res/values-ar/strings.xml"
        _write_file(base_xml, '<resources><string name="app_name">App</string><string name="farewell">Bye</string></resources>\n')
        _write_file(ar_xml, '<resources><string name="app_name">تطبيق</string><string name="farewell">وداعا</string></resources>\n')
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "add strings")

        # Delete from base only
        _write_file(base_xml, '<resources><string name="app_name">App</string></resources>\n')

        script = SCRIPTS / "check_strings.py"
        env = {**os.environ, "HARNESS_REPO": str(self.repo)}
        res = subprocess.run([sys.executable, str(script)], cwd=str(self.repo), capture_output=True, text=True, env=env, check=False)
        self.assertNotEqual(0, res.returncode, "diff-scoped should detect asymmetric key deletion")
        self.assertIn("farewell", res.stdout + res.stderr)

    # --- Scenario 07: Missing Whole Locale Resource File ---
    def test_scenario_07_missing_whole_locale_file(self) -> None:
        base_strings = self.repo / "app/src/main/res/values/strings.xml"
        ar_strings = self.repo / "app/src/main/res/values-ar/strings.xml"
        _write_file(base_strings, '<resources><string name="app_name">App</string></resources>\n')
        _write_file(ar_strings, '<resources><string name="app_name">تطبيق</string></resources>\n')
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "initial strings")

        base_plurals = self.repo / "app/src/main/res/values/plurals.xml"
        # Only base plural added, no localized plurals file
        _write_file(
            base_plurals,
            '<resources>\n'
            '    <plurals name="items">\n'
            '        <item quantity="one">%d item</item>\n'
            '        <item quantity="other">%d items</item>\n'
            '    </plurals>\n'
            '</resources>\n',
        )

        classification = classify(self.repo)
        self.assertIn("LOCALIZATION", classification["surfaces"])

        script = SCRIPTS / "check_strings.py"
        env = {**os.environ, "HARNESS_REPO": str(self.repo)}
        res = subprocess.run([sys.executable, str(script)], cwd=str(self.repo), capture_output=True, text=True, env=env, check=False)
        self.assertNotEqual(0, res.returncode, "check_strings should fail on missing localized plural resource")
        self.assertIn("items", res.stdout + res.stderr)

    # --- Scenario 08: Room Entity Field Type Change ---
    def test_scenario_08_room_entity_field_type_change(self) -> None:
        entity_file = self.repo / "app/src/main/kotlin/com/example/UserEntity.kt"
        _write_file(
            entity_file,
            "package com.example\nimport androidx.room.Entity\nimport androidx.room.PrimaryKey\n\n"
            "@Entity(tableName = \"users\")\n"
            "data class UserEntity(\n"
            "    @PrimaryKey val id: Long,\n"
            "    val score: Int\n"
            ")\n",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "add entity")

        # Change Int to Long without modifying @Entity annotation
        _write_file(
            entity_file,
            "package com.example\nimport androidx.room.Entity\nimport androidx.room.PrimaryKey\n\n"
            "@Entity(tableName = \"users\")\n"
            "data class UserEntity(\n"
            "    @PrimaryKey val id: Long,\n"
            "    val score: Long\n"
            ")\n",
        )

        classification = classify(self.repo)
        self.assertIn("ROOM_SCHEMA", classification["surfaces"])
        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertIn("room", policy["gates"])

    # --- Scenario 09: Deleted Room Entity ---
    def test_scenario_09_deleted_room_entity(self) -> None:
        entity_file = self.repo / "app/src/main/kotlin/com/example/OldEntity.kt"
        _write_file(
            entity_file,
            "package com.example\nimport androidx.room.Entity\n@Entity\nclass OldEntity\n",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "add old entity")

        # Delete entity via git rm
        _run_git(self.repo, "rm", "app/src/main/kotlin/com/example/OldEntity.kt")

        classification = classify(self.repo)
        # Deletion-aware classifier reads old HEAD text and catches ROOM_SCHEMA
        self.assertIn("ROOM_SCHEMA", classification["surfaces"])

    # --- Scenario 10: Cross-File Room Migration Registration ---
    def test_scenario_10_cross_file_room_migration(self) -> None:
        db_file = self.repo / "app/src/main/kotlin/com/example/AppDatabase.kt"
        _write_file(
            db_file,
            "package com.example\nimport androidx.room.Database\nimport androidx.room.RoomDatabase\n\n"
            "@Database(entities = [], version = 2)\n"
            "abstract class AppDatabase : RoomDatabase()\n",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "add db")

        # Mutate database version to create an uncommitted Room diff without migration
        _write_file(
            db_file,
            "package com.example\nimport androidx.room.Database\nimport androidx.room.RoomDatabase\n\n"
            "@Database(entities = [], version = 3)\n"
            "abstract class AppDatabase : RoomDatabase()\n",
        )

        classification = classify(self.repo)
        self.assertIn("ROOM_SCHEMA", classification["surfaces"])

        # Execute room_guard.py to verify it catches missing migration path 2 -> 3
        script = SCRIPTS / "room_guard.py"
        env = {**os.environ, "HARNESS_REPO": str(self.repo)}
        res_missing = subprocess.run([sys.executable, str(script)], cwd=str(self.repo), capture_output=True, text=True, env=env, check=False)
        self.assertNotEqual(0, res_missing.returncode, "room_guard should reject database version bump without migration")

        # Add valid migration and builder registration across files
        mig_file = self.repo / "app/src/main/kotlin/com/example/Migrations.kt"
        _write_file(
            mig_file,
            "package com.example\nimport androidx.room.migration.Migration\n"
            "val MIGRATION_2_3 = object : Migration(2, 3) {}\n",
        )
        _write_file(
            db_file,
            "package com.example\nimport androidx.room.Database\nimport androidx.room.RoomDatabase\nimport androidx.room.Room\n\n"
            "@Database(entities = [], version = 3)\n"
            "abstract class AppDatabase : RoomDatabase() {\n"
            "    fun build(ctx: android.content.Context) = Room.databaseBuilder(ctx, AppDatabase::class.java, \"app.db\")\n"
            "        .addMigrations(MIGRATION_2_3)\n"
            "        .build()\n"
            "}\n",
        )
        res_valid = subprocess.run([sys.executable, str(script)], cwd=str(self.repo), capture_output=True, text=True, env=env, check=False)
        self.assertEqual(0, res_valid.returncode, res_valid.stdout + res_valid.stderr)

    # --- Scenario 11: Billing Callback Logic Edit Without Billing Keyword in Diff ---
    def test_scenario_11_billing_callback_logic_edit(self) -> None:
        billing_file = self.repo / "app/src/main/kotlin/com/example/BillingHandler.kt"
        _write_file(
            billing_file,
            "package com.example\nimport com.android.billingclient.api.BillingClient\n\n"
            "class BillingHandler {\n"
            "    fun onPurchasesUpdated(status: Int) {\n"
            "        if (status == 0) {\n"
            "            processSuccess()\n"
            "        }\n"
            "    }\n"
            "    private fun processSuccess() {}\n"
            "}\n",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "add billing")

        # Edit only the conditional inside onPurchasesUpdated (no billing keyword in diff line)
        _write_file(
            billing_file,
            "package com.example\nimport com.android.billingclient.api.BillingClient\n\n"
            "class BillingHandler {\n"
            "    fun onPurchasesUpdated(status: Int) {\n"
            "        if (status == 1) {\n"
            "            processSuccess()\n"
            "        }\n"
            "    }\n"
            "    private fun processSuccess() {}\n"
            "}\n",
        )

        classification = classify(self.repo)
        self.assertIn("BILLING", classification["surfaces"])
        self.assertEqual("CRITICAL", classification["severity"])

    # --- Scenario 12: Auth Logic Edit in Long Function ---
    def test_scenario_12_auth_logic_edit_in_long_function(self) -> None:
        auth_file = self.repo / "app/src/main/kotlin/com/example/AuthManager.kt"
        filler = "\n".join(f"        val dummy{i} = {i}" for i in range(40))
        _write_file(
            auth_file,
            "package com.example\n\n"
            "class AuthManager {\n"
            "    fun performAuthentication(token: String): Boolean {\n"
            f"{filler}\n"
            "        return token.isNotEmpty()\n"
            "    }\n"
            "}\n",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "add auth")

        # Modify the line far down in performAuthentication
        _write_file(
            auth_file,
            "package com.example\n\n"
            "class AuthManager {\n"
            "    fun performAuthentication(token: String): Boolean {\n"
            f"{filler}\n"
            "        return token.length > 5\n"
            "    }\n"
            "}\n",
        )

        classification = classify(self.repo)
        self.assertIn("AUTH", classification["surfaces"])
        self.assertEqual("CRITICAL", classification["severity"])

    # --- Scenario 13: Coroutine Dispatcher/Lifecycle Change ---
    def test_scenario_13_coroutine_dispatcher_change(self) -> None:
        repo_file = self.repo / "app/src/main/kotlin/com/example/DataRepo.kt"
        _write_file(
            repo_file,
            "package com.example\nimport kotlinx.coroutines.Dispatchers\nimport kotlinx.coroutines.withContext\n\n"
            "class DataRepo {\n"
            "    suspend fun load() = withContext(Dispatchers.IO) { 42 }\n"
            "}\n",
        )

        classification = classify(self.repo)
        self.assertIn("COROUTINES", classification["surfaces"])
        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertIn("perf-anr-guardian-agent", policy["reviewers"])
        self.assertFalse(policy["device_required"])

    # --- Scenario 14: Network API Contract Change ---
    def test_scenario_14_network_api_contract_change(self) -> None:
        api_file = self.repo / "app/src/main/kotlin/com/example/ApiService.kt"
        _write_file(
            api_file,
            "package com.example\nimport retrofit2.http.GET\n\n"
            "interface ApiService {\n"
            '    @GET("v1/profile")\n'
            "    suspend fun getProfile(): String\n"
            "}\n",
        )

        classification = classify(self.repo)
        self.assertIn("NETWORK", classification["surfaces"])
        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertIn("security-reviewer-agent", policy["reviewers"])

    # --- Scenario 15: Manifest Permission / Exported Component Change ---
    def test_scenario_15_manifest_permission_change(self) -> None:
        manifest_file = self.repo / "app/src/main/AndroidManifest.xml"
        _write_file(
            manifest_file,
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '    <uses-permission android:name="android.permission.CAMERA" />\n'
            '    <application android:label="ScenarioApp">\n'
            '        <activity android:name=".MainActivity" android:exported="true" />\n'
            '    </application>\n'
            '</manifest>\n',
        )

        classification = classify(self.repo)
        self.assertIn("MANIFEST_PERMISSION", classification["surfaces"])
        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertTrue(policy["device_required"])

    def test_scenario_15b_manifest_service_component_floors(self) -> None:
        manifest_file = self.repo / "app/src/main/AndroidManifest.xml"
        _write_file(
            manifest_file,
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '    <application android:label="ScenarioApp">\n'
            '        <activity android:name=".MainActivity" android:exported="true">\n'
            '            <intent-filter>\n'
            '                <action android:name="android.intent.action.MAIN" />\n'
            '                <category android:name="android.intent.category.LAUNCHER" />\n'
            '            </intent-filter>\n'
            '        </activity>\n'
            '        <service android:name=".BackgroundSyncService" />\n'
            '    </application>\n'
            '</manifest>\n',
        )

        classification = classify(self.repo)
        # service/receiver maps to DEVICE_API + BUILD_CONFIG, not MANIFEST_PERMISSION
        self.assertIn("DEVICE_API", classification["surfaces"])
        self.assertIn("BUILD_CONFIG", classification["surfaces"])
        self.assertNotIn("MANIFEST_PERMISSION", classification["surfaces"])
        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertTrue(policy["device_required"])

    # --- Scenario 16: Gradle Dependency Change ---
    def test_scenario_16_gradle_dependency_change(self) -> None:
        gradle_file = self.repo / "app/build.gradle.kts"
        _write_file(
            gradle_file,
            'plugins { id("com.android.application") }\n'
            'dependencies { implementation("com.squareup.okhttp3:okhttp:4.12.0") }\n',
        )

        classification = classify(self.repo)
        self.assertIn("BUILD_CONFIG", classification["surfaces"])
        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertIn("assemble", policy["gates"])
        self.assertFalse(policy["device_required"])

    # --- Scenario 17: ProGuard / R8 Rule Change ---
    def test_scenario_17_proguard_rule_change(self) -> None:
        proguard_file = self.repo / "proguard-rules.pro"
        _write_file(proguard_file, "-keep class com.example.models.** { *; }\n")

        classification = classify(self.repo)
        self.assertIn("BUILD_CONFIG", classification["surfaces"])
        self.assertNotEqual("CRITICAL", classification["severity"])

    # --- Scenario 18: Generated KSP Error / Delivery Exclusion ---
    def test_scenario_18_generated_ksp_output_excluded(self) -> None:
        gen_path = "app/build/generated/ksp/debug/kotlin/com/example/UserDao_Impl.kt"
        _write_file(self.repo / gen_path, "package com.example\nclass UserDao_Impl\n")

        # Delivery manifest must ignore build/generated files
        self.assertFalse(is_delivery_relevant(gen_path))
        manifest = build_manifest(self.repo)
        manifest_paths = [c["path"] for c in manifest.get("changes") or []]
        self.assertNotIn(gen_path, manifest_paths)

    # --- Scenario 19: New Untracked Kotlin Source File ---
    def test_scenario_19_new_untracked_kotlin_file(self) -> None:
        new_source = "app/src/main/kotlin/com/example/FreshClass.kt"
        _write_file(self.repo / new_source, "package com.example\nclass FreshClass\n")

        self.assertTrue(is_delivery_relevant(new_source))
        manifest = build_manifest(self.repo)
        untracked = [c for c in manifest.get("changes") or [] if c["path"] == new_source]
        self.assertEqual(1, len(untracked))
        self.assertEqual("A", untracked[0]["status"])

        classification = classify(self.repo)
        self.assertIn("BUSINESS_LOGIC", classification["surfaces"])

    # --- Scenario 20: File Rename / Move ---
    def test_scenario_20_file_rename_move_identity(self) -> None:
        old_path = "app/src/main/kotlin/com/example/MainActivity.kt"
        new_path = "app/src/main/kotlin/com/example/RenamedActivity.kt"
        _run_git(self.repo, "mv", old_path, new_path)

        manifest = build_manifest(self.repo)
        renamed = [c for c in manifest.get("changes") or [] if c["path"] == new_path]
        self.assertEqual(1, len(renamed))
        self.assertEqual("R", renamed[0]["status"])
        self.assertEqual(old_path, renamed[0]["old_path"])
        self.assertEqual(new_path, renamed[0]["path"])
        self.assertFalse(renamed[0]["path"].startswith("R100"))

        from _repo_files import changed_files
        changes = changed_files(self.repo)
        rf = next(c for c in changes if c.status == "R")
        self.assertEqual(new_path, rf.rel_posix)
        self.assertEqual(old_path, rf.old_rel_posix)
        self.assertFalse(rf.rel_posix.startswith("R100"))

        classification = classify(self.repo)
        self.assertTrue(classification["has_delete_or_rename"])

    # --- Scenario 21: Existing Failing-Test Baseline ---
    def test_scenario_21_existing_baseline_test_tolerated(self) -> None:
        raw_fail = "Failure at /workspace/app/src/Test.kt:42 at 2026-09-11 12:00:00: expected true"
        norm = normalize_failure_message(raw_fail)
        # Normalization strips path, line number and timestamp
        self.assertNotIn("42", norm)
        self.assertNotIn("2026-09-11", norm)
        self.assertIn("<PATH>", norm)
        self.assertIn("<TIMESTAMP>", norm)

    # --- Scenario 22: Same Baseline Test Fails Differently ---
    def test_scenario_22_same_baseline_test_fails_differently(self) -> None:
        fp1 = fingerprint("com.example.TestA#testFlow", "AssertionError", "expected 1 got 2")
        fp2 = fingerprint("com.example.TestA#testFlow", "NullPointerException", "object was null")
        self.assertNotEqual(fp1, fp2, "Different exception type/message must yield different fingerprints")

    # --- Scenario 23: Wireless ADB Offline ---
    def test_scenario_23_wireless_adb_offline_verdict(self) -> None:
        err = "adb: error: failed to connect to 192.168.1.100:5555: Connection timed out"
        verdict = classify_adb_failure(1, err)
        self.assertEqual("ENV", verdict.env_class)
        self.assertEqual(EXIT_ENV, 30)

    # --- Scenario 24: Stale Mutable Gate PASS Block ---
    def test_scenario_24_stale_mutable_gate_pass_blocked(self) -> None:
        from evidence_store import EvidenceStore
        store = EvidenceStore(self.repo / ".agents/state")
        # Trying to validate artifact without matching change-set sha fails closed
        rec, err = _validate_artifact(store, "snap123", "expected_change_set", "run1", "unit_tests", "1.0.12")
        self.assertIsNone(rec)
        self.assertIsNotNone(err)

    # --- Scenario 25: Pure Logic Task With No Device Requirement ---
    def test_scenario_25_pure_logic_no_device_requirement(self) -> None:
        logic_file = self.repo / "app/src/main/kotlin/com/example/Calculator.kt"
        _write_file(logic_file, "package com.example\nclass Calculator { fun add(a: Int, b: Int) = a + b }\n")

        classification = classify(self.repo)
        self.assertEqual(["BUSINESS_LOGIC"], classification["surfaces"])
        policy = decide(classification, self.skills_root, project_kind="application")
        self.assertFalse(policy["device_required"])

    # --- Scenario 26: Concurrent Developer Edit Safety ---
    def test_scenario_26_concurrent_developer_edit_no_destructive_git(self) -> None:
        # Harness safety boundaries must explicitly deny destructive git commands
        forbidden = ["git reset --hard", "git checkout .", "git stash drop", "git clean -fd"]
        for cmd in forbidden:
            denied = any(pattern.search(cmd) for _, pattern in DANGEROUS)
            self.assertTrue(denied, f"Command '{cmd}' must be blocked by safety boundary")

    # --- Scenario 27: Material Scope Expansion Mid-Task ---
    def test_scenario_27_material_scope_expansion_drift(self) -> None:
        plan = {
            "expected_surfaces": ["BUSINESS_LOGIC"],
            "expected_modules": [":app"],
        }
        # Classified surfaces expanded to include BILLING
        classification = {
            "surfaces": ["BUSINESS_LOGIC", "BILLING"],
            "details": {
                "BILLING": {"files": ["app/src/main/kotlin/Billing.kt"], "reasons": ["BILLING_PATTERN"]}
            },
        }
        drift = check_material_drift(plan, classification["surfaces"], [":app"])
        self.assertIn("surface:BILLING", drift)

    # --- Scenario 28: Minor Follow-Up Inside Approved Scope ---
    def test_scenario_28_minor_follow_up_inside_approved_scope(self) -> None:
        plan = {
            "expected_surfaces": ["BUSINESS_LOGIC"],
            "expected_modules": [":app"],
        }
        # Classified surfaces remain inside approved scope
        classification = {
            "surfaces": ["BUSINESS_LOGIC"],
            "details": {
                "BUSINESS_LOGIC": {"files": ["app/src/main/kotlin/UserViewModel.kt"], "reasons": ["SOURCE_CHANGE"]}
            },
        }
        drift = check_material_drift(plan, classification["surfaces"], [":app"])
        self.assertEqual([], drift)

    # --- Scenario 29: Reviewer Environment / Quota Failure ---
    def test_scenario_29_reviewer_env_failure_blocks_delivery(self) -> None:
        from evidence_store import EvidenceStore
        store = EvidenceStore(self.repo / ".agents/state")
        # If record is marked ENV, validation fails with ENV block message
        store.write(
            snapshot="snap123",
            run_id="run1",
            name="unit_tests",
            producer="run_tests_gate",
            harness_version="1.0.12",
            change_set="cs123",
            status="ENV",
            evidence={},
        )
        rec, err = _validate_artifact(store, "snap123", "cs123", "run1", "unit_tests", "1.0.12")
        self.assertIsNone(rec)
        self.assertIn("blocked by the environment", str(err))

    # --- Scenario 30: Existing Release Version Reuse Attempt ---
    def test_scenario_30_existing_release_version_reuse(self) -> None:
        # Check that version file exists and can be validated against semver contract
        version_file = KIT / "agents" / "VERSION"
        self.assertTrue(version_file.is_file())
        version = version_file.read_text(encoding="utf-8").strip()
        parts = version.split(".")
        self.assertEqual(3, len(parts), "Version must follow semver X.Y.Z")
        for part in parts:
            self.assertTrue(part.isdigit(), "Each semver part must be digits")

    # --- Phase 2C: Systematic Debugging Evidence Recorded Outside plan.json ---
    def test_scenario_phase2c_debug_evidence_recorded_outside_plan(self) -> None:
        import argparse
        from workflow import draft, record_approval, begin_task, record_debug_evidence
        from mutation_guard import command_allowed

        # 1. Draft a task with --kind BUG
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id="TASK-BUG-1",
            outcome="Fix crash on profile button click",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app",
            test_strategy="unit tests",
            device_strategy="manual",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        )
        plan = draft(args)
        self.assertEqual("BUG", plan.get("task_kind"))
        routed_skills = [s.get("id") for s in plan.get("skills") or []]
        self.assertIn("systematic-debugging", routed_skills)
        initial_plan_sha = plan.get("plan_sha256")
        self.assertTrue(initial_plan_sha)

        # 2. Approve and begin
        app_args = argparse.Namespace(
            repo=str(self.repo),
            task_id="TASK-BUG-1",
            source="conversation",
            proof_reference="approved by developer",
            enforcement_tier="RULE_ENFORCED",
        )
        approved_plan = record_approval(app_args)
        self.assertEqual("APPROVED", approved_plan.get("status"))

        begin_args = argparse.Namespace(
            repo=str(self.repo),
            task_id="TASK-BUG-1",
        )
        begun_plan = begin_task(begin_args)
        self.assertEqual("IMPLEMENTING", begun_plan.get("status"))

        # 3. Verify mutation_guard allows workflow.py debug-evidence command
        cmd = "python .agents/scripts/workflow.py debug-evidence --repo . --task-id TASK-BUG-1 --kind reproduction --reference test_failure"
        allowed, reason = command_allowed(self.repo, cmd)
        self.assertTrue(allowed, f"debug-evidence should be allowed: {reason}")

        # 4. Record debug evidence
        ev_args = argparse.Namespace(
            repo=str(self.repo),
            task_id="TASK-BUG-1",
            kind="reproduction",
            reference="NullPointerException at UserProfile.kt:42",
            hypothesis="Profile data null when user not cached",
            risk="Cache miss returns default empty state",
        )
        res = record_debug_evidence(ev_args)
        self.assertEqual(1, len(res.get("entries", [])))
        self.assertEqual("reproduction", res["entries"][0]["kind"])

        # Record a second evidence
        ev_args2 = argparse.Namespace(
            repo=str(self.repo),
            task_id="TASK-BUG-1",
            kind="logcat",
            reference="logcat -d | grep NPE",
            hypothesis="Confirmed NPE trace",
            risk="",
        )
        res2 = record_debug_evidence(ev_args2)
        self.assertEqual(2, len(res2.get("entries", [])))

        # 5. Check debug-evidence.json file exists
        ev_file = self.repo / ".agents" / "state" / "tasks" / "TASK-BUG-1" / "debug-evidence.json"
        self.assertTrue(ev_file.is_file())
        saved_ev = read_json(ev_file)
        self.assertEqual(2, len(saved_ev.get("entries", [])))

        # 6. Verify plan.json is unchanged and plan_sha256 is strictly preserved
        plan_file = self.repo / ".agents" / "state" / "tasks" / "TASK-BUG-1" / "plan.json"
        current_plan = read_json(plan_file)
        self.assertEqual(initial_plan_sha, current_plan.get("plan_sha256"))
        self.assertNotIn("entries", current_plan)
        self.assertNotIn("debug_evidence", current_plan)

    # --- Phase 3: Verification Recipes as Deterministic Manual Guidance ---
    def test_scenario_phase3_verification_recipes(self) -> None:
        import argparse
        from _verification_recipes import VERIFICATION_RECIPES, get_verification_recipes
        from workflow import draft, record_approval, begin_task, prepare_verification

        # 1. Test deterministic recipes helper
        compose_recipes = get_verification_recipes(["COMPOSE_UI"])
        self.assertEqual(1, len(compose_recipes))
        self.assertEqual("COMPOSE_UI", compose_recipes[0]["surface"])
        self.assertEqual(5, len(compose_recipes[0]["steps"]))

        multi_recipes = get_verification_recipes(["ROOM_SCHEMA", "MANIFEST_PERMISSION", "NAVIGATION"])
        surfaces = [r["surface"] for r in multi_recipes]
        self.assertIn("ROOM_SCHEMA", surfaces)
        self.assertIn("MANIFEST_PERMISSION", surfaces)
        self.assertIn("NAVIGATION", surfaces)

        # Pure logic receives NO device recipe
        logic_recipes = get_verification_recipes(["BUSINESS_LOGIC"])
        self.assertEqual([], logic_recipes)

        # 2. Integration with prepare_verification
        compose_file = self.repo / "app/src/main/kotlin/com/example/MyScreen.kt"
        _write_file(compose_file, "package com.example\nimport androidx.compose.runtime.Composable\n@Composable fun MyScreen() {}\n")

        args = argparse.Namespace(
            repo=str(self.repo),
            task_id="TASK-RECIPE-1",
            outcome="Add Compose screen",
            kind="FEATURE",
            expected_surfaces="COMPOSE_UI,BUSINESS_LOGIC",
            expected_modules=":app",
            test_strategy="unit tests",
            device_strategy="manual",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        )
        draft(args)
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id="TASK-RECIPE-1",
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id="TASK-RECIPE-1"))

        prep_res = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="TASK-RECIPE-1"))
        self.assertIn("verification_recipes", prep_res)
        prep_surfaces = [r["surface"] for r in prep_res["verification_recipes"]]
        self.assertIn("COMPOSE_UI", prep_surfaces)

        # Confirm written current-run.json contains verification_recipes
        current_run_file = self.repo / ".agents" / "state" / "tasks" / "TASK-RECIPE-1" / "current-run.json"
        self.assertTrue(current_run_file.is_file())
        saved_run = read_json(current_run_file)
        self.assertIn("verification_recipes", saved_run)

    # --- Phase 2C: End-to-End BUG Task Final Verification ---
    def test_scenario_phase2c_e2e_bug_final_verification(self) -> None:
        import argparse
        from workflow import draft, record_approval, begin_task, prepare_verification
        from final_verifier import verify

        fix_file = self.repo / "app/src/main/kotlin/com/example/Fix.kt"
        _write_file(fix_file, "package com.example\nfun bugFix() = true\n")

        args = argparse.Namespace(
            repo=str(self.repo),
            task_id="TASK-BUG-E2E",
            outcome="Fix NPE in profile",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        )
        draft(args)
        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id="TASK-BUG-E2E",
            source="conversation",
            proof_reference="approved",
            enforcement_tier="RULE_ENFORCED",
        ))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id="TASK-BUG-E2E"))
        prep_res = prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="TASK-BUG-E2E"))
        self.assertIn("run_id", prep_res)
        plan_file = self.repo / ".agents" / "state" / "tasks" / "TASK-BUG-E2E" / "plan.json"
        saved_plan = read_json(plan_file)
        self.assertEqual("VERIFYING", saved_plan["status"])

        ver_res = verify(
            self.repo,
            plan_path=plan_file,
            policy_path=Path(prep_res["policy"]),
            manifest_path=Path(prep_res["manifest"]),
            state_root=self.repo / ".agents" / "state",
            run_id=prep_res["run_id"],
        )
        self.assertNotIn("policy artifact does not match deterministic policy evaluation", ver_res.get("blocked_by", []))

    # --- Scenario: Multiple Matching Physical Devices Disambiguation ---
    def test_scenario_multiple_matching_physical_devices(self) -> None:
        from unittest import mock
        from _repo_files import matching_adb_serials
        from run_device import require_serial

        devices = subprocess.CompletedProcess([], 0, "List of devices attached\nPHONE_A\tdevice\nPHONE_B\tdevice\n", "")
        probe_a = subprocess.CompletedProcess([], 0, "0\n", "")
        probe_b = subprocess.CompletedProcess([], 0, "0\n", "")

        with mock.patch("_repo_files.subprocess.run", side_effect=[devices, probe_a, probe_b]):
            matches = matching_adb_serials(policy="physical-only")
            self.assertEqual(["PHONE_A", "PHONE_B"], matches)

        with mock.patch("run_device.matching_adb_serials", return_value=["PHONE_A", "PHONE_B"]):
            with self.assertRaises(SystemExit) as cm:
                require_serial(None)
            self.assertEqual(EXIT_ENV, cm.exception.code)

        with mock.patch("run_device.adb_serial_is_emulator", return_value=False):
            with mock.patch("run_device.DEVICE_TARGET_POLICY", "physical-only"):
                self.assertEqual("PHONE_B", require_serial("PHONE_B"))


if __name__ == "__main__":
    unittest.main()
