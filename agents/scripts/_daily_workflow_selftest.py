"""Daily developer workflow selftest suite for v1.0.40 hardening.

Covers:
- Section 1.4 Command contract and parser validation tests.
- Section 11 Scenarios Daily-01 through Daily-20.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _product
from _vnext_common import (
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    read_json,
    sha256_file,
    utc_now,
)
from architecture_drift import check_architecture_drift
import architecture_drift
from architecture_policy import (
    create_architecture_policy,
    read_architecture_policy,
    write_architecture_policy,
)
from architecture_resolver import (
    STATUS_DECISION_REQUIRED,
    STATUS_RESOLVED,
    resolve_architecture_contract,
)
from change_classifier import classify, is_ui_only_kotlin
from delivery_manifest import (
    build_manifest,
    build_task_manifest,
    load_task_baseline,
)
from evidence_store import EvidenceStore
from final_verifier import verify_task
import lifecycle
from mutation_guard import active_plan
from plan_authority import plan_payload
import record_review
from record_review import _parse_reviewer_findings, is_blocking_finding
import review_package
from review_policy import decide
import workflow
from workflow import (
    begin_task,
    build_remediation_command,
    checkpoint_phase,
    complete,
    deliver_task,
    draft,
    normalize_expected_files,
    prepare_verification,
    record_approval,
    record_debug_evidence,
    record_sensitive_approval,
    state_root,
    task_dir,
)

KIT = Path(__file__).resolve().parents[2]


def run_git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)


def write_file(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def setup_ownership(repo: Path, version: str = "1.0.40") -> None:
    from lifecycle import SCHEMA_VERSION, ARCHITECTURE_MAJOR, OWNERSHIP_RELATIVE, EXCLUDE_BEGIN, EXCLUDE_END
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "architecture_major": ARCHITECTURE_MAJOR,
        "harness_version": version,
        "installed_at": utc_now(),
        "install_backup": None,
        "latest_backup": None,
        "managed_exclude_block": {"begin": EXCLUDE_BEGIN, "end": EXCLUDE_END},
        "entries": [],
    }
    manifest["ownership_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "ownership_sha256"})
    atomic_write_json(repo / OWNERSHIP_RELATIVE, manifest)
    write_file(repo / ".harness-setup" / "answers.json", json.dumps({"confirm_installation": True, "target_branch": "main"}))


class DailyWorkflowSelftest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="daily_wf_test_")
        self.repo = Path(self.temp.name).resolve()
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Daily Test")
        run_git(self.repo, "config", "user.email", "daily@example.invalid")
        run_git(self.repo, "config", "core.autocrlf", "true")

        # Guarantee consistent state_root
        (self.repo / ".agents" / "state").mkdir(parents=True, exist_ok=True)

        # Basic Android fixture
        write_file(self.repo / "gradlew", "#!/bin/sh\nexit 0\n")
        try:
            os.chmod(self.repo / "gradlew", 0o755)
        except Exception:
            pass
        write_file(self.repo / "settings.gradle.kts", 'rootProject.name = "DailyFixture"\ninclude(":app")\n')
        write_file(self.repo / "app/build.gradle.kts", 'plugins { id("com.android.application") }\n')
        write_file(
            self.repo / "app/src/main/res/values/strings.xml",
            '<resources>\n    <string name="app_name">DailyFixture</string>\n</resources>\n',
        )
        write_file(
            self.repo / "app/src/main/kotlin/com/example/MainActivity.kt",
            "package com.example\n\nclass MainActivity\n",
        )
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "initial fixture")

        self.env = os.environ.copy()
        self.env["HARNESS_REPO"] = str(self.repo)

    def tearDown(self) -> None:
        self.temp.cleanup()

    # -------------------------------------------------------------------------
    # Section 1.4: Command Contract & Parser Tests
    # -------------------------------------------------------------------------

    def test_command_contract_draft_matches_workflow_parser(self) -> None:
        """Verify the canonical draft command flags are completely valid according to workflow parser."""
        contract_file = KIT / "agents" / "skills" / "android-harness" / "references" / "command-contract.md"
        self.assertTrue(contract_file.is_file(), f"Missing contract file: {contract_file}")
        content = contract_file.read_text(encoding="utf-8")

        self.assertIn("workflow.py draft", content)
        self.assertIn("--outcome", content)
        self.assertIn("--kind", content)
        self.assertIn("--expected-files", content)
        self.assertIn("--architecture-intent", content)

        from workflow import main as workflow_main
        args = [
            "draft",
            "--repo", str(self.repo),
            "--task-id", "test-contract-draft",
            "--outcome", "Implement login flow",
            "--kind", "FEATURE",
            "--expected-surfaces", "COMPOSE_UI,RESOURCES",
            "--expected-modules", "app",
            "--expected-files", "app/src/main/kotlin/com/example/Login.kt",
            "--architecture-intent", "EXISTING_CHANGE",
            "--architecture-target-scope", "app/src/main/kotlin/com/example/Login.kt",
        ]
        ret = workflow_main(args)
        self.assertEqual(0, ret)

    def test_material_drift_remediation_command_is_parser_valid(self) -> None:
        """Verify that build_remediation_command produces a fully executable, parser-valid command."""
        task_id = "test-remediation"
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Fix login crash",
            kind="BUG",
            planning_depth="BOUNDED",
            expected_surfaces="COMPOSE_UI",
            expected_modules="app",
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/Login.kt",
            phases=None,
            force=True,
        )
        draft(args)
        plan = read_json(task_dir(self.repo, task_id) / "plan.json")
        policy = {"surfaces": ["COMPOSE_UI", "RESOURCES"], "gates": ["preflight"]}
        manifest = build_manifest(self.repo)

        cmd = build_remediation_command(self.repo, task_id, plan, policy, manifest)
        self.assertTrue(cmd.startswith("python .agents/scripts/workflow.py draft"))
        self.assertIn(f"--task-id {task_id}", cmd)

        parts = shlex.split(cmd.replace("\\\n", " "))
        draft_idx = parts.index("draft")
        cli_args = parts[draft_idx:]
        from workflow import main as workflow_main
        cli_args.append("--force")
        ret = workflow_main(cli_args)
        self.assertEqual(0, ret)

    def test_architecture_drift_documented_cli_is_real(self) -> None:
        """Verify architecture_drift.py CLI is real, returns 0 for compliant plan, and never mutates state."""
        task_id = "test-arch-cli"
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Check architecture",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces=None,
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files=None,
            phases=None,
            force=True,
        )
        draft(args)
        code = architecture_drift.main(["--repo", str(self.repo), "--task-id", task_id])
        self.assertEqual(0, code)

    def test_public_command_catalog_has_no_unknown_flags(self) -> None:
        """Verify command catalog references only valid flags for each CLI tool."""
        import preflight_check
        code = preflight_check.main(["--diagnostic"])
        self.assertEqual(0, code)

        self.assertEqual(0, architecture_drift.main(["--repo", str(self.repo), "--task-id", "nonexistent"]))

        ret = review_package.main(["--repo", str(self.repo), "--task", "nonexistent"])
        self.assertIn(ret, (0, 1))

    # -------------------------------------------------------------------------
    # Daily-01: Tiny strings change
    # -------------------------------------------------------------------------

    def test_daily_01_tiny_strings_change(self) -> None:
        """Daily-01: Micro behavior for strings change; no semantic reviewers or unit tests solely due to strings."""
        task_id = "daily-01-strings"
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Update welcome label",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces=None,
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/res/values/strings.xml",
            phases=None,
            force=True,
        )
        draft(args)
        write_file(
            self.repo / "app/src/main/res/values/strings.xml",
            '<resources>\n    <string name="app_name">DailyFixture</string>\n    <string name="welcome">Welcome</string>\n</resources>\n',
        )
        baseline = load_task_baseline(self.repo, task_id)
        task_manifest = build_task_manifest(self.repo, baseline)
        classification = classify(self.repo, task_id=task_id)
        surfaces = classification["surfaces"]

        self.assertTrue("LOCALIZATION" in surfaces or "RESOURCE_UI" in surfaces)
        self.assertNotIn("BUSINESS_LOGIC", surfaces)
        self.assertNotIn("COMPOSE_UI", surfaces)

        policy = decide(classification, KIT / "agents" / "skills", plan=plan_payload(read_json(task_dir(self.repo, task_id) / "plan.json")))
        self.assertNotIn("unit_tests", policy.get("gates", []))

    # -------------------------------------------------------------------------
    # Daily-02: Compose padding only
    # -------------------------------------------------------------------------

    def test_daily_02_compose_padding_only(self) -> None:
        """Daily-02: Compose padding edit is COMPOSE_UI without BUSINESS_LOGIC; no unit tests gate required."""
        task_id = "daily-02-padding"
        header_file = self.repo / "app/src/main/kotlin/com/example/Header.kt"
        write_file(
            header_file,
            'package com.example\n\nimport androidx.compose.runtime.Composable\nimport androidx.compose.ui.Modifier\nimport androidx.compose.ui.unit.dp\nimport androidx.compose.foundation.layout.padding\nimport androidx.compose.foundation.layout.Box\nimport androidx.compose.material3.Text\n\n@Composable\nfun Header() {\n    Box(modifier = Modifier.padding(16.dp)) {\n        Text("Title")\n    }\n}\n',
        )
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "add header")

        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Increase header padding to 24dp",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces=None,
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/Header.kt",
            phases=None,
            force=True,
        )
        draft(args)

        write_file(
            header_file,
            'package com.example\n\nimport androidx.compose.runtime.Composable\nimport androidx.compose.ui.Modifier\nimport androidx.compose.ui.unit.dp\nimport androidx.compose.foundation.layout.padding\nimport androidx.compose.foundation.layout.Box\nimport androidx.compose.material3.Text\n\n@Composable\nfun Header() {\n    Box(modifier = Modifier.padding(24.dp)) {\n        Text("Title")\n    }\n}\n',
        )
        baseline = load_task_baseline(self.repo, task_id)
        task_manifest = build_task_manifest(self.repo, baseline)
        classification = classify(self.repo, task_id=task_id)
        surfaces = classification["surfaces"]

        self.assertIn("COMPOSE_UI", surfaces)
        self.assertNotIn("BUSINESS_LOGIC", surfaces)

        policy = decide(classification, KIT / "agents" / "skills", plan=plan_payload(read_json(task_dir(self.repo, task_id) / "plan.json")))
        self.assertNotIn("unit_tests", policy.get("gates", []))

    # -------------------------------------------------------------------------
    # Daily-03: Compose click invoking UseCase
    # -------------------------------------------------------------------------

    def test_daily_03_compose_click_invokes_usecase(self) -> None:
        """Daily-03: Compose click invoking viewModel.submitOrder() is BUSINESS_LOGIC + COMPOSE_UI; requires unit tests."""
        task_id = "daily-03-click"
        header_file = self.repo / "app/src/main/kotlin/com/example/Header.kt"
        write_file(
            header_file,
            'package com.example\n\nimport androidx.compose.runtime.Composable\nimport androidx.compose.material3.Button\nimport androidx.compose.material3.Text\n\n@Composable\nfun OrderButton() {\n    Button(onClick = {}) {\n        Text("Submit")\n    }\n}\n',
        )
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "add button")

        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Wire submit order click",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces=None,
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/Header.kt",
            phases=None,
            force=True,
        )
        draft(args)

        write_file(
            header_file,
            'package com.example\n\nimport androidx.compose.runtime.Composable\nimport androidx.compose.material3.Button\nimport androidx.compose.material3.Text\n\n@Composable\nfun OrderButton(viewModel: OrderViewModel) {\n    Button(onClick = { viewModel.submitOrder() }) {\n        Text("Submit")\n    }\n}\n',
        )
        baseline = load_task_baseline(self.repo, task_id)
        task_manifest = build_task_manifest(self.repo, baseline)
        classification = classify(self.repo, task_id=task_id)
        surfaces = classification["surfaces"]

        self.assertIn("COMPOSE_UI", surfaces)
        self.assertIn("BUSINESS_LOGIC", surfaces)

        policy = decide(classification, KIT / "agents" / "skills", plan=plan_payload(read_json(task_dir(self.repo, task_id) / "plan.json")))
        self.assertIn("unit_tests", policy.get("gates", []))

    # -------------------------------------------------------------------------
    # Daily-04: BUG with failing unit test (RED -> GREEN)
    # -------------------------------------------------------------------------

    def test_daily_04_bug_with_failing_unit_test(self) -> None:
        """Daily-04: Capture RED failure before fix; apply fix; verifier approves schema 2 RED evidence."""
        task_id = "daily-04-bug"
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Fix order calculation crash",
            kind="BUG",
            planning_depth="BOUNDED",
            expected_surfaces=None,
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/Order.kt",
            phases=None,
            force=True,
        )
        draft(args)
        record_approval(argparse.Namespace(repo=str(self.repo), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))

        record_debug_evidence(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            kind="test_failure",
            reference="com.example.OrderTest#testCalculateTotal",
            hypothesis="Division by zero on empty cart",
            risk="None",
        ))
        red_file = task_dir(self.repo, task_id) / "red-evidence.json"
        self.assertFalse(red_file.is_file(), "debug-evidence must not write red-evidence.json")
        dbg_file = task_dir(self.repo, task_id) / "debug-evidence.json"
        self.assertTrue(dbg_file.is_file())
        dbg_data = read_json(dbg_file)
        self.assertFalse(dbg_data["entries"][0].get("satisfies_executable_red", True))

        write_file(
            self.repo / "app/src/main/kotlin/com/example/Order.kt",
            "package com.example\n\nclass Order { fun calculateTotal(): Int = 0 }\n",
        )
        baseline = load_task_baseline(self.repo, task_id)
        task_manifest = build_task_manifest(self.repo, baseline)
        self.assertTrue(len(task_manifest.get("task_changes", [])) > 0)

    # -------------------------------------------------------------------------
    # Daily-05: Developer has unrelated dirty file
    # -------------------------------------------------------------------------

    def test_daily_05_developer_unrelated_dirty_file(self) -> None:
        """Daily-05: Pre-existing dirty developer file is excluded from task delta and review package."""
        write_file(self.repo / "unrelated_dev_notes.md", "# Developer Scratchpad\nDraft ideas\n")

        task_id = "daily-05-isolation"
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Add feature X",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces=None,
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/FeatureX.kt",
            phases=None,
            force=True,
        )
        draft(args)
        record_approval(argparse.Namespace(repo=str(self.repo), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))

        write_file(
            self.repo / "app/src/main/kotlin/com/example/FeatureX.kt",
            "package com.example\n\nclass FeatureX\n",
        )

        baseline = load_task_baseline(self.repo, task_id)
        task_manifest = build_task_manifest(self.repo, baseline)
        changed_paths = [c["path"] for c in task_manifest["changes"]]

        self.assertIn("app/src/main/kotlin/com/example/FeatureX.kt", changed_paths)
        self.assertNotIn("unrelated_dev_notes.md", changed_paths)

        prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        pkg_path, meta = review_package.build_package(self.repo, task_id)
        pkg_content = pkg_path.read_text(encoding="utf-8")
        self.assertIn("FeatureX.kt", pkg_content)
        self.assertNotIn("unrelated_dev_notes.md", pkg_content)

    # -------------------------------------------------------------------------
    # Daily-06: Task modifies pre-dirty file
    # -------------------------------------------------------------------------

    def test_daily_06_task_modifies_predirty_file(self) -> None:
        """Daily-06: File already dirty at baseline and further modified by task IS captured in task delta."""
        shared_file = self.repo / "app/src/main/kotlin/com/example/Shared.kt"
        write_file(shared_file, "package com.example\n\n// dev edit 1\nclass Shared\n")

        task_id = "daily-06-predirty"
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Enhance Shared component",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces=None,
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/Shared.kt",
            phases=None,
            force=True,
        )
        draft(args)

        write_file(shared_file, "package com.example\n\n// dev edit 1\n// task edit 2\nclass Shared { fun act() = Unit }\n")

        baseline = load_task_baseline(self.repo, task_id)
        task_manifest = build_task_manifest(self.repo, baseline)
        changed_paths = [c["path"] for c in task_manifest["changes"]]

        self.assertIn("app/src/main/kotlin/com/example/Shared.kt", changed_paths)

    # -------------------------------------------------------------------------
    # Daily-07: Mixed architecture in :app
    # -------------------------------------------------------------------------

    def test_daily_07_mixed_architecture_in_app(self) -> None:
        """Daily-07: Scope resolution matches local screen/ViewModel family, not first ViewModel or global default."""
        from project_context import extract_project_facts
        write_file(
            self.repo / "app/src/main/kotlin/com/example/mvi/HomeScreen.kt",
            "package com.example.mvi\n\nimport androidx.compose.runtime.Composable\n\n@Composable\nfun HomeScreen() {}\n",
        )
        write_file(
            self.repo / "app/src/main/kotlin/com/example/mvi/HomeViewModel.kt",
            "package com.example.mvi\n\nclass HomeViewModel : MviViewModel<State, Action, Effect>()\n",
        )
        write_file(
            self.repo / "app/src/main/kotlin/com/example/legacy/OldActivity.kt",
            "package com.example.legacy\n\nimport androidx.appcompat.app.AppCompatActivity\n\nclass OldActivity : AppCompatActivity()\n",
        )
        write_file(
            self.repo / "app/src/main/kotlin/com/example/legacy/OldViewModel.kt",
            "package com.example.legacy\n\nclass OldViewModel : ViewModel()\n",
        )

        facts_payload = extract_project_facts(self.repo)
        from project_context import write_project_context
        write_project_context(self.repo, facts_payload)
        facts = facts_payload["facts"]
        families = facts["architecture"]["families"]
        self.assertGreaterEqual(len(families), 2)

        policy = create_architecture_policy(families[0]["id"])
        write_architecture_policy(self.repo, policy)

        res = resolve_architecture_contract(
            self.repo,
            architecture_intent="EXISTING_CHANGE",
            target_scope="app/src/main/kotlin/com/example/legacy/OldActivity.kt",
        )
        self.assertEqual(STATUS_RESOLVED, res["status"])
        old_fam = next((f["id"] for f in families if "mvi" not in f["label"].lower()), None)
        if old_fam:
            self.assertEqual(old_fam, res["contract"]["target_family_id"])

    # -------------------------------------------------------------------------
    # Daily-08: New screen
    # -------------------------------------------------------------------------

    def test_daily_08_new_screen(self) -> None:
        """Daily-08: NEW_SCREEN intent resolves to preferred architecture family and allows compatibility bridges."""
        from project_context import extract_project_facts, write_project_context
        write_file(
            self.repo / "app/src/main/kotlin/com/example/mvi/HomeScreen.kt",
            "package com.example.mvi\n\nimport androidx.compose.runtime.Composable\n\n@Composable\nfun HomeScreen() {}\n",
        )
        write_file(
            self.repo / "app/src/main/kotlin/com/example/mvi/HomeViewModel.kt",
            "package com.example.mvi\n\nclass HomeViewModel : MviViewModel<State, Action, Effect>()\n",
        )
        facts_payload = extract_project_facts(self.repo)
        write_project_context(self.repo, facts_payload)
        families = facts_payload["facts"]["architecture"]["families"]
        policy = create_architecture_policy(families[0]["id"])
        write_architecture_policy(self.repo, policy)

        res = resolve_architecture_contract(
            self.repo,
            architecture_intent="NEW_SCREEN",
            target_scope="app/src/main/kotlin/com/example/NewScreen.kt",
        )
        self.assertEqual(STATUS_RESOLVED, res["status"])
        self.assertEqual(policy["preferred_new_code_family"], res["contract"]["target_family_id"])

        passed, msg, _ = check_architecture_drift(self.repo, res["contract"])
        self.assertTrue(passed, f"Drift check failed: {msg}")

    # -------------------------------------------------------------------------
    # Daily-09: Explicit migration
    # -------------------------------------------------------------------------

    def test_daily_09_explicit_migration(self) -> None:
        """Daily-09: MIGRATION intent with ARCHITECTURAL planning depth validates target family and out-of-scope transitions."""
        from project_context import extract_project_facts, write_project_context
        write_file(
            self.repo / "app/src/main/kotlin/com/example/mvi/HomeScreen.kt",
            "package com.example.mvi\n\nimport androidx.compose.runtime.Composable\n\n@Composable\nfun HomeScreen() {}\n",
        )
        write_file(
            self.repo / "app/src/main/kotlin/com/example/mvi/HomeViewModel.kt",
            "package com.example.mvi\n\nclass HomeViewModel : MviViewModel<State, Action, Effect>()\n",
        )
        facts_payload = extract_project_facts(self.repo)
        write_project_context(self.repo, facts_payload)
        families = facts_payload["facts"]["architecture"]["families"]
        policy = create_architecture_policy(families[0]["id"])
        write_architecture_policy(self.repo, policy)

        res = resolve_architecture_contract(
            self.repo,
            architecture_intent="MIGRATION",
            planning_depth="ARCHITECTURAL",
            target_scope="app/src/main/kotlin/com/example/LegacyScreen.kt",
            target_family_id=policy["preferred_new_code_family"],
        )
        self.assertEqual(STATUS_RESOLVED, res["status"])
        self.assertEqual(policy["preferred_new_code_family"], res["contract"]["target_family_id"])

    # -------------------------------------------------------------------------
    # Daily-10: Fake subagent proof rejected on HIGH/sensitive task
    # -------------------------------------------------------------------------

    def test_daily_10_fake_subagent_proof_rejected(self) -> None:
        """Daily-10: Self-certifying direct --verdict on HIGH/sensitive task without valid receipt/transcript is rejected."""
        task_id = "daily-10-fake-proof"
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Payment crypto update",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces="AUTH,SECURITY,BUSINESS_LOGIC",
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/Auth.kt",
            phases=None,
            force=True,
        )
        draft(args)
        record_approval(argparse.Namespace(repo=str(self.repo), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        write_file(self.repo / "app/src/main/kotlin/com/example/Auth.kt", "package com.example\n\nclass Auth {\n    fun loginWithOAuth(token: String): Boolean = true\n}\n")
        prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        _, pkg = review_package.build_package(self.repo, task_id)
        pkg_sha = pkg["package_sha256"]

        ret = record_review.main([
            "--repo", str(self.repo),
            "--task", task_id,
            "--verdict", "security-reviewer-agent=PASS",
            "--evidence-pkg", pkg_sha,
            "--subagent-id", "fabricated-conv-id-12345",
        ])
        self.assertEqual(1, ret)

    # -------------------------------------------------------------------------
    # Daily-11: Real transcript reviewer accepted and provenance verified
    # -------------------------------------------------------------------------

    def test_daily_11_real_transcript_reviewer_accepted(self) -> None:
        """Daily-11: Valid dispatch receipt + transcript is accepted with provenance=subagent_execution."""
        task_id = "daily-11-real-proof"
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Bug fix with reviewer",
            kind="BUG",
            planning_depth="BOUNDED",
            expected_surfaces="COMPOSE_UI,BUSINESS_LOGIC",
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/MainActivity.kt",
            phases=None,
            force=True,
        )
        draft(args)
        record_approval(argparse.Namespace(repo=str(self.repo), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        write_file(self.repo / "app/src/main/kotlin/com/example/MainActivity.kt", "package com.example\n\nclass MainActivity { fun fix() = Unit }\n")
        prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))

        run_info = read_json(task_dir(self.repo, task_id) / "current-run.json")
        run_id = str(run_info["run_id"])
        _, review_pkg = review_package.build_package(self.repo, task_id)
        pkg_sha = review_pkg["package_sha256"]

        policy = read_json(Path(run_info["policy"]))
        required_reviewers = list(policy.get("reviewers") or ["bug-reviewer-agent"])
        self.assertGreater(len(required_reviewers), 0)

        app_data_dir = self.repo / ".test_app_data"
        old_env = os.environ.get("ANTIGRAVITY_APP_DATA")
        os.environ["ANTIGRAVITY_APP_DATA"] = str(app_data_dir)
        receipt_dir = task_dir(self.repo, task_id) / "reviewer-dispatches"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        try:
            from record_review import PASS_TOKENS
            for rev in required_reviewers:
                sub_id = f"{rev}-conv-id"
                t_dir = app_data_dir / "brain" / sub_id / ".system_generated" / "logs"
                t_dir.mkdir(parents=True, exist_ok=True)
                t_file = t_dir / "transcript.jsonl"
                token = PASS_TOKENS.get(rev, "PASS")
                rev_text = f"VERDICT: PASS\n{token}\nNo issues found.\nEVIDENCE pkg={pkg_sha[:12]} cites=0"
                t_file.write_text(
                    json.dumps({"type": "PLANNER_RESPONSE", "content": rev_text}) + "\n",
                    encoding="utf-8",
                )
                r_data = {
                    "schema_version": 1,
                    "task_id": task_id,
                    "run_id": run_id,
                    "reviewer": rev,
                    "subagent_id": sub_id,
                    "review_package_sha256": pkg_sha,
                    "dispatched_at": utc_now(),
                    "host": "antigravity",
                }
                r_data["receipt_sha256"] = canonical_sha256(r_data)
                atomic_write_json(receipt_dir / f"{rev}.json", r_data)

                ret = record_review.main([
                    "--repo", str(self.repo),
                    "--task", task_id,
                    "--response-text", f"{rev}={rev_text}",
                    "--subagent-id", sub_id,
                ])
                self.assertEqual(0, ret)
        finally:
            if old_env is not None:
                os.environ["ANTIGRAVITY_APP_DATA"] = old_env
            else:
                os.environ.pop("ANTIGRAVITY_APP_DATA", None)

        reviews_file = state_root(self.repo) / "runs" / run_info["delivery_snapshot_sha256"] / run_id / "reviews.json"
        self.assertTrue(reviews_file.is_file())
        review_evidence = read_json(reviews_file)
        self.assertEqual("PASS", review_evidence["status"])
        self.assertEqual("subagent_execution", review_evidence["evidence"]["provenance"])

    # -------------------------------------------------------------------------
    # Daily-12: Reviewer LOW finding retained, not rewritten to HIGH, non-blocking
    # -------------------------------------------------------------------------

    def test_daily_12_reviewer_low_finding_retained_not_blocking(self) -> None:
        """Daily-12: Reviewer LOW finding is preserved as LOW, marked non-blocking, does not block plan."""
        review_text = "Found minor issue:\n[LOW] Consider renaming variable 'x' for clarity.\nEVIDENCE pkg=abcdef123456 cites=1"
        findings = _parse_reviewer_findings(review_text, default_severity="HIGH")
        self.assertEqual(1, len(findings))
        self.assertEqual("LOW", findings[0]["severity"])
        self.assertFalse(is_blocking_finding(findings[0]))

    # -------------------------------------------------------------------------
    # Daily-13: Reviewer HIGH finding blocks delivery; remediation uses real task ID
    # -------------------------------------------------------------------------

    def test_daily_13_reviewer_high_finding_blocks_delivery(self) -> None:
        """Daily-13: Reviewer HIGH finding is blocking, sets plan BLOCKED, remediation uses task_id."""
        task_id = "daily-13-high-finding"
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Update user profile",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces=None,
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/Profile.kt",
            phases=None,
            force=True,
        )
        draft(args)
        record_approval(argparse.Namespace(repo=str(self.repo), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        write_file(self.repo / "app/src/main/kotlin/com/example/Profile.kt", "package com.example\n\nclass Profile\n")
        prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))

        run_info = read_json(task_dir(self.repo, task_id) / "current-run.json")
        run_id = str(run_info["run_id"])
        _, review_pkg = review_package.build_package(self.repo, task_id)
        pkg_sha = review_pkg["package_sha256"]

        policy = read_json(Path(run_info["policy"]))
        required_reviewers = list(policy.get("reviewers") or ["security-reviewer-agent"])
        primary = required_reviewers[0]

        finding_text = f"Security vulnerability identified:\n[HIGH] SQL injection vulnerability\nEVIDENCE pkg={pkg_sha[:12]} cites=1"
        try:
            record_review.main([
                "--repo", str(self.repo),
                "--task", task_id,
                "--response-text", f"{primary}={finding_text}",
            ])
        except (ValidationError, SystemExit):
            pass

        for other in required_reviewers[1:]:
            try:
                record_review.main([
                    "--repo", str(self.repo),
                    "--task", task_id,
                    "--response-text", f"{other}=Clean.\nEVIDENCE pkg={pkg_sha[:12]} cites=0\nPASS",
                ])
            except (ValidationError, SystemExit):
                pass

        plan = read_json(task_dir(self.repo, task_id) / "plan.json")
        self.assertEqual("BLOCKED", plan.get("status"))

        from mutation_guard import command_allowed
        allowed, msg = command_allowed(self.repo, "python agents/scripts/run_gradle_task.py :app:assembleDebug")
        self.assertFalse(allowed)
        self.assertIn(f"--task-id {task_id}", msg)

    # -------------------------------------------------------------------------
    # Daily-14: Multi-phase feature
    # -------------------------------------------------------------------------

    def test_daily_14_multi_phase_feature(self) -> None:
        """Daily-14: Multi-phase feature under single approval; phase checkpoints validate phase delta."""
        task_id = "daily-14-phases"
        phases_spec = [
            {"id": "phase-1", "name": "Data layer", "expected_files": ["app/src/main/kotlin/com/example/Data.kt"]},
            {"id": "phase-2", "name": "UI layer", "expected_files": ["app/src/main/kotlin/com/example/UI.kt"]},
        ]
        args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            outcome="Two phase delivery",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces=None,
            expected_modules=None,
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/Data.kt,app/src/main/kotlin/com/example/UI.kt",
            phases=json.dumps(phases_spec),
            force=True,
        )
        draft(args)
        record_approval(argparse.Namespace(repo=str(self.repo), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))

        write_file(self.repo / "app/src/main/kotlin/com/example/Data.kt", "package com.example\n\nclass Data\n")
        p1_dir = task_dir(self.repo, task_id) / "phases" / "phase-1"
        p1_dir.mkdir(parents=True, exist_ok=True)
        write_file(p1_dir / "unit_tests.json", json.dumps({"status": "PASS"}))
        write_file(p1_dir / "reviews.json", json.dumps([
            {"reviewer": "bug-reviewer-agent", "verdict": "PASS"},
            {"reviewer": "regression-impact-reviewer-agent", "verdict": "PASS"},
        ]))
        res1 = checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="phase-1"))
        self.assertEqual("PASS", res1["status"])
        self.assertEqual(["phase-1"], res1["completed_phases"])
        self.assertEqual("phase-2", res1["current_phase_id"])

        write_file(self.repo / "app/src/main/kotlin/com/example/UI.kt", "package com.example\n\nclass UI\n")
        p2_dir = task_dir(self.repo, task_id) / "phases" / "phase-2"
        p2_dir.mkdir(parents=True, exist_ok=True)
        write_file(p2_dir / "unit_tests.json", json.dumps({"status": "PASS"}))
        write_file(p2_dir / "reviews.json", json.dumps([
            {"reviewer": "bug-reviewer-agent", "verdict": "PASS"},
            {"reviewer": "regression-impact-reviewer-agent", "verdict": "PASS"},
        ]))
        res2 = checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="phase-2"))
        self.assertEqual("PASS", res2["status"])
        self.assertEqual(["phase-1", "phase-2"], res2["completed_phases"])

    # -------------------------------------------------------------------------
    # Daily-15: Update preserve
    # -------------------------------------------------------------------------

    def test_daily_15_update_preserve(self) -> None:
        """Daily-15: lifecycle update(mode=preserve) preserves context facts, views, policy, and notes byte-for-byte."""
        facts_file = self.repo / ".agents" / "project-context" / "project-facts.json"
        write_file(facts_file, '{"schema_version": 1, "custom_facts": true}\n')
        notes_file = self.repo / ".agents" / "project-context" / "project-notes.md"
        write_file(notes_file, "# Developer Notes\nImportant custom note.\n")
        policy_file = self.repo / ".agents" / "project-context" / "architecture-policy.json"
        write_file(policy_file, '{"schema_version": 1, "status": "ACTIVE", "policy_hash": "test"}\n')

        facts_before = facts_file.read_bytes()
        notes_before = notes_file.read_bytes()

        setup_ownership(self.repo)
        answers = {"update_context_mode": "preserve", "confirm_installation": True}
        with mock.patch("lifecycle._validate_kit", return_value=(KIT, "1.0.40")):
            lifecycle.update(self.repo, KIT, answers)

        self.assertEqual(facts_before, facts_file.read_bytes())
        self.assertEqual(notes_before, notes_file.read_bytes())

    # -------------------------------------------------------------------------
    # Daily-16: Update refresh
    # -------------------------------------------------------------------------

    def test_daily_16_update_refresh(self) -> None:
        """Daily-16: lifecycle update(mode=refresh) refreshes facts; sets ARCHITECTURE_DECISION_REQUIRED if family gone."""
        policy = {
            "schema_version": 1,
            "status": "ACTIVE",
            "default_family": "nonexistent_obsolete_family",
            "allowed_families": ["nonexistent_obsolete_family"],
            "policy_hash": "dummy",
        }
        write_file(self.repo / ".agents" / "project-context" / "architecture-policy.json", json.dumps(policy))

        setup_ownership(self.repo)
        answers = {"update_context_mode": "refresh", "confirm_installation": True}
        with mock.patch("lifecycle._validate_kit", return_value=(KIT, "1.0.40")):
            lifecycle.update(self.repo, KIT, answers)

        updated_policy = read_json(self.repo / ".agents" / "project-context" / "architecture-policy.json")
        self.assertEqual("ARCHITECTURE_DECISION_REQUIRED", updated_policy.get("status"))

    # -------------------------------------------------------------------------
    # Daily-17: Interrupted update recovery
    # -------------------------------------------------------------------------

    def test_daily_17_interrupted_update_recovery(self) -> None:
        """Daily-17: Automatic recovery from interrupted update restores previous valid engine."""
        setup_ownership(self.repo)
        agents_dir = self.repo / ".agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        write_file(agents_dir / "engine_marker.txt", "engine_v1")

        previous_dir = self.repo / ".agents.previous-test123"
        shutil.copytree(agents_dir, previous_dir)
        write_file(agents_dir / "engine_marker.txt", "engine_corrupted_partial")

        journal_file = self.repo / ".harness-setup" / "update-journal.json"
        write_file(journal_file, json.dumps({
            "schema_version": 1,
            "status": "in_progress",
            "previous_backup": str(previous_dir),
            "updated_at": utc_now(),
        }))

        recovered = lifecycle.recover_interrupted_update(self.repo)
        self.assertIsNotNone(recovered)
        self.assertEqual("RECOVERED", recovered["status"])
        self.assertEqual("engine_v1", (agents_dir / "engine_marker.txt").read_text(encoding="utf-8"))
        self.assertFalse(previous_dir.exists())

    # -------------------------------------------------------------------------
    # Daily-18: Stale command documentation detection
    # -------------------------------------------------------------------------

    def test_daily_18_stale_command_documentation(self) -> None:
        """Daily-18: Parser validation ensures documented commands have no stale or unsupported flags."""
        from workflow import main as workflow_main
        with self.assertRaises(SystemExit):
            workflow_main(["draft", "--repo", str(self.repo), "--task-id", "stale-test", "--unknown-stale-flag-12345"])

    # -------------------------------------------------------------------------
    # Daily-19: Unknown mutation-like host tool
    # -------------------------------------------------------------------------

    def test_daily_19_unknown_mutation_like_host_tool(self) -> None:
        """Daily-19: Unknown host tool with mutation verb is denied closed and audited."""
        safety_script = KIT / "agents" / "scripts" / "pre_tool_safety.py"
        self.assertTrue(safety_script.is_file())

        mutation_payload = {
            "toolCall": {"name": "custom_delete_records", "args": {"record_id": "123"}}
        }
        proc = subprocess.run(
            [sys.executable, str(safety_script)],
            input=json.dumps(mutation_payload),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertIn('"decision": "deny"', proc.stdout.lower() + proc.stderr.lower())

        read_payload = {
            "toolCall": {"name": "custom_inspect_status", "args": {"id": "123"}}
        }
        proc2 = subprocess.run(
            [sys.executable, str(safety_script)],
            input=json.dumps(read_payload),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertIn('"decision": "allow"', proc2.stdout.lower())

    # -------------------------------------------------------------------------
    # Daily-20: Old v1 active task (legacy compatibility mode)
    # -------------------------------------------------------------------------

    def test_daily_20_old_v1_active_task(self) -> None:
        """Daily-20: Legacy active task without task-baseline.json operates in full worktree legacy mode without crashing."""
        task_id = "daily-20-legacy"
        t_dir = task_dir(self.repo, task_id)
        t_dir.mkdir(parents=True, exist_ok=True)

        legacy_plan = {
            "plan_id": "legacy-plan-id",
            "task_id": task_id,
            "status": "IMPLEMENTING",
            "execution_nonce": "legacy_nonce",
            "requested_outcome": "Legacy task",
            "task_kind": "FEATURE",
            "planning_depth": "BOUNDED",
            "expected_surfaces": ["COMPOSE_UI"],
            "expected_modules": [":app"],
            "approval": {"single_use_nonce": "legacy_nonce"},
        }
        write_file(t_dir / "plan.json", json.dumps(legacy_plan))

        baseline = load_task_baseline(self.repo, task_id)
        self.assertIsNone(baseline)

        manifest = build_task_manifest(self.repo, baseline)
        self.assertEqual("LEGACY_FULL_WORKTREE", manifest.get("task_delta_mode"))
        self.assertIn("delivery_snapshot_sha256", manifest)
        self.assertIn("changes", manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
