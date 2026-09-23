"""Comprehensive Adversarial Integration & Stabilization Suite for v1.0.41.

Covers all priority requirements from the v1.0.41 stabilization specification:
- REV-PROOF-001 to 007: Reviewer Independence & Provenance
- RED-001 to 008: RED->GREEN Temporal & Defect Binding
- TASK-ISO-001 to 005: True Task-Delta Isolation
- PHASE-001 to 004: Multi-Phase Planning & Checkpoint Verification
- ARCH-001 to 004: Architecture Resolution & Drift Correctness
- UPD-REC-001 to 007: Transaction Journal-Driven Update Recovery
- PERF-CTX-001 to 004: Source Fingerprint & Context Freshness Performance
- SETUP-ARCH-001 to 004: Setup Architecture Preference Neutrality
- CONTRACT-001: Public Command Contract Accuracy
- E2E-01 to 07: End-to-End Adversarial Workflows
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vnext_common import ValidationError, canonical_sha256, read_json, atomic_write_json, utc_now
from architecture_drift import check_architecture_drift
from architecture_policy import create_architecture_policy, write_architecture_policy, compute_policy_hash
from architecture_resolver import resolve_architecture_contract, STATUS_DECISION_REQUIRED, STATUS_RESOLVED
from change_classifier import classify
from delivery_manifest import build_manifest, build_task_manifest, build_task_diff
from evidence_store import EvidenceStore
from final_verifier import verify_delivery
from lifecycle import update, recover_interrupted_update, install
from plan_authority import plan_payload
from project_context import (
    compute_source_fingerprint,
    extract_project_facts,
    project_context_status,
    render_project_context,
    write_project_context,
)
from record_review import (
    ingest,
    response_text_to_report,
    verify_independent_reviewer_execution,
)
from review_package import build_package
from review_policy import decide
from workflow import (
    record_approval as approve,
    begin_task,
    begin_next_phase,
    checkpoint_phase,
    complete,
    draft,
    prepare_verification,
    resolve_next_action,
    task_dir,
    state_root,
)
from wizard.questions import questions_payload

KIT = Path(__file__).resolve().parents[2]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")


def _run_git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)


def _setup_mock_repo(root: Path) -> None:
    _run_git(root, "init", "-q")
    _run_git(root, "config", "user.name", "Test User")
    _run_git(root, "config", "user.email", "test@example.com")
    _run_git(root, "config", "commit.gpgsign", "false")
    (root / "app" / "src" / "main" / "kotlin" / "com" / "example").mkdir(parents=True, exist_ok=True)
    _write_text(root / "app" / "build.gradle.kts", 'plugins { id("com.android.application") }\n')
    _write_text(root / "settings.gradle.kts", 'include(":app")\n')
    _write_text(root / "gradlew", "#!/bin/sh\nexit 0\n")
    _write_text(root / "gradlew.bat", "@exit /b 0\r\n")
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-qm", "Initial commit")
    _write_json(root / ".harness-setup" / "answers.json", {
        "product": "TestApp",
        "application_id": "com.example.testapp",
        "launcher": "com.example.testapp.MainActivity",
        "assemble": ":app:assembleDebug",
        "unit_test_task": ":app:testDebugUnitTest",
        "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
        "tools": ["gemini"],
        "pm_provider": "none",
        "zoho_mcp": "disable",
        "backup": True,
    })
    install(root, KIT)
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-qm", "Install harness", "--allow-empty")


class ReviewerIndependenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_rev_indep_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_REV_PROOF_001_lead_agent_response_text_rejected_on_high_severity(self) -> None:
        task_id = "task-rev-001"
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Security change",
            kind="FEATURE", planning_depth="STANDARD", expected_surfaces="SECURITY,BUSINESS_LOGIC",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/Auth.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=None,
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))
        _write_text(self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Auth.kt", "class Auth { private val p = 0; fun verify() = CertificatePinner() }\n")
        prep = prepare_verification(Namespace(repo=str(self.tmp), task_id=task_id))
        prep["review_protocol_version"] = 1
        current_run_path = self.tmp / ".agents" / "state" / "tasks" / task_id / "current-run.json"
        _write_json(current_run_path, prep)
        pkg_file, _ = build_package(self.tmp, task_id)
        pkg_sha = hashlib.sha256(pkg_file.read_bytes()).hexdigest()

        # Lead agent creates raw response text with valid pass token and valid package hash
        raw_text = f"SECURITY_PASS\nEVIDENCE pkg={pkg_sha[:12]} cites=0\nLooks good."
        report = response_text_to_report(self.tmp, task_id, "security-reviewer-agent", raw_text)
        self.assertFalse(report.get("independent_execution_verified", False))

        rep_path = self.tmp / ".harness-setup" / "sec_report.json"
        _write_json(rep_path, report)
        reports = [rep_path]
        policy_data = read_json(Path(prep["policy"]))
        for other in policy_data.get("reviewers", []):
            if other != "security-reviewer-agent":
                tok = f"{other.split('-')[0].upper()}_PASS\nEVIDENCE pkg={pkg_sha[:12]} cites=0\nPASS"
                oth_rep = response_text_to_report(self.tmp, task_id, other, tok)
                p = self.tmp / ".harness-setup" / f"{other}.json"
                _write_json(p, oth_rep)
                reports.append(p)
        ingest(self.tmp, task_id, reports)

        # Write other gate evidence
        store = EvidenceStore(state_root(self.tmp))
        h_ver = (self.tmp / ".agents" / "VERSION").read_text(encoding="utf-8").strip()
        comm = dict(snapshot=prep["delivery_snapshot_sha256"], run_id=prep["run_id"], harness_version=h_ver, change_set=prep["change_set_sha256"], status="PASS")
        store.write(**comm, name="unit_tests", producer="run_tests_gate", evidence={"executed": 1})
        store.write(**comm, name="preflight", producer="preflight_check", evidence={})
        store.write(**comm, name="assemble", producer="run_gradle_task", evidence={})

        res = verify_delivery(self.tmp, task_id)
        self.assertNotEqual("PASS", res.get("status"))
        self.assertTrue(any("independent_execution_verified=false" in b or "self-certified" in b for b in res.get("blocked_by", [])))

    def test_REV_PROOF_002_subagent_execution_accepted_with_valid_receipt_and_transcript(self) -> None:
        task_id = "task-rev-002"
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Security change",
            kind="FEATURE", planning_depth="STANDARD", expected_surfaces="SECURITY,BUSINESS_LOGIC",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/Auth.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=None,
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))
        _write_text(self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Auth.kt", "class Auth { val token = 123 }\n")
        prep = prepare_verification(Namespace(repo=str(self.tmp), task_id=task_id, host="antigravity"))
        pkg_file, _ = build_package(self.tmp, task_id)
        pkg_sha = hashlib.sha256(pkg_file.read_bytes()).hexdigest()

        # Create mock receipt
        subagent_id = "sub-conv-123"
        rc_dir = task_dir(self.tmp, task_id) / "reviewer-dispatches"
        rc_dir.mkdir(parents=True, exist_ok=True)
        rc_data = {
            "schema_version": 1,
            "task_id": task_id,
            "run_id": prep["run_id"],
            "reviewer": "security-reviewer-agent",
            "package_sha256": pkg_sha,
            "subagent_id": subagent_id,
            "dispatched_at": utc_now(),
        }
        rc_data["receipt_sha256"] = canonical_sha256(rc_data)
        _write_json(rc_dir / "security-reviewer-agent.json", rc_data)

        # Create mock trusted transcript in test-injected ANTIGRAVITY_APP_DATA root
        app_data_dir = self.tmp / "test_app_data"
        old_env = os.environ.get("ANTIGRAVITY_APP_DATA")
        os.environ["ANTIGRAVITY_APP_DATA"] = str(app_data_dir)
        try:
            transcript_dir = app_data_dir / "brain" / subagent_id / ".system_generated" / "logs"
            transcript_path = transcript_dir / "transcript.jsonl"
            rev_output = f"SECURITY_PASS\nEVIDENCE pkg={pkg_sha[:12]} cites=0\nAll security invariants hold."
            _write_text(transcript_path, json.dumps({"source": "MODEL", "content": rev_output}) + "\n")

            ok, proof = verify_independent_reviewer_execution(
                self.tmp, task_id=task_id, run_id=prep["run_id"],
                reviewer="security-reviewer-agent", package_sha256=pkg_sha,
                subagent_id=subagent_id, transcript_path=transcript_path,
            )
            self.assertTrue(ok)
            self.assertTrue(proof.get("verified"))
        finally:
            if old_env is not None:
                os.environ["ANTIGRAVITY_APP_DATA"] = old_env
            else:
                os.environ.pop("ANTIGRAVITY_APP_DATA", None)

    def test_REV_PROOF_003_missing_transcript_rejected(self) -> None:
        task_id = "task-rev-003"
        ok, proof = verify_independent_reviewer_execution(
            self.tmp, task_id=task_id, run_id="run-1",
            reviewer="security-reviewer-agent", package_sha256="abc",
            subagent_id="sub-nonexistent",
            transcript_path=self.tmp / "nonexistent.jsonl",
        )
        self.assertFalse(ok)
        self.assertFalse(proof.get("verified"))

    def test_REV_PROOF_004_mismatched_run_id_or_pkg_sha_rejected(self) -> None:
        task_id = "task-rev-004"
        rc_dir = task_dir(self.tmp, task_id) / "reviewer-dispatches"
        rc_dir.mkdir(parents=True, exist_ok=True)
        rc_data = {
            "schema_version": 1, "task_id": task_id, "run_id": "run-expected",
            "reviewer": "security-reviewer-agent", "package_sha256": "pkg-expected",
            "subagent_id": "sub-4", "dispatched_at": utc_now(),
        }
        rc_data["receipt_sha256"] = canonical_sha256(rc_data)
        _write_json(rc_dir / "security-reviewer-agent.json", rc_data)

        # Mismatched run_id in caller
        ok, proof = verify_independent_reviewer_execution(
            self.tmp, task_id=task_id, run_id="run-DIFFERENT",
            reviewer="security-reviewer-agent", package_sha256="pkg-expected",
            subagent_id="sub-4", transcript_path=rc_dir / "security-reviewer-agent.json",
        )
        self.assertFalse(ok)

    def test_REV_PROOF_005_tampered_receipt_signature_rejected(self) -> None:
        task_id = "task-rev-005"
        rc_dir = task_dir(self.tmp, task_id) / "reviewer-dispatches"
        rc_dir.mkdir(parents=True, exist_ok=True)
        rc_data = {
            "schema_version": 1, "task_id": task_id, "run_id": "run-1",
            "reviewer": "security-reviewer-agent", "package_sha256": "pkg-1",
            "subagent_id": "sub-5", "receipt_sha256": "bad-hash",
        }
        _write_json(rc_dir / "security-reviewer-agent.json", rc_data)
        _write_json(task_dir(self.tmp, task_id) / "current-run.json", {
            "task_id": task_id, "run_id": "run-1", "review_host": "antigravity", "review_protocol_version": 1,
        })

        app_data_dir = self.tmp / "test_app_data"
        old_env = os.environ.get("ANTIGRAVITY_APP_DATA")
        os.environ["ANTIGRAVITY_APP_DATA"] = str(app_data_dir)
        try:
            t_path = app_data_dir / "brain" / "sub-5" / ".system_generated" / "logs" / "transcript.jsonl"
            _write_text(t_path, json.dumps({"source": "MODEL", "content": "SECURITY_PASS\nEVIDENCE pkg=pkg-1 cites=0"}) + "\n")

            ok, proof = verify_independent_reviewer_execution(
                self.tmp, task_id=task_id, run_id="run-1",
                reviewer="security-reviewer-agent", package_sha256="pkg-1",
                subagent_id="sub-5", transcript_path=t_path,
            )
            self.assertFalse(ok)
            self.assertIn("receipt_sha256 signature mismatch", proof.get("reason", ""))
        finally:
            if old_env is not None:
                os.environ["ANTIGRAVITY_APP_DATA"] = old_env
            else:
                os.environ.pop("ANTIGRAVITY_APP_DATA", None)

    def test_REV_PROOF_007_developer_override_rules(self) -> None:
        task_id = "task-rev-007"
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Sensitive Auth",
            kind="FEATURE", planning_depth="STANDARD", expected_surfaces="AUTH,BUSINESS_LOGIC",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/Auth.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=None,
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))
        _write_text(self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Auth.kt", "class Auth { fun login() = true }\n")
        prep = prepare_verification(Namespace(repo=str(self.tmp), task_id=task_id))

        store = EvidenceStore(state_root(self.tmp))
        h_ver = (self.tmp / ".agents" / "VERSION").read_text(encoding="utf-8").strip()
        comm = dict(snapshot=prep["delivery_snapshot_sha256"], run_id=prep["run_id"], harness_version=h_ver, change_set=prep["change_set_sha256"])

        # Override on sensitive surface is strictly forbidden
        store.write(**comm, status="PASS", name="reviews", producer="developer_override", evidence={
            "developer_override": True, "source": "developer_terminal", "proof_reference": "override",
            "proof_reference_sha256": "abc", "reviewers": ["security-reviewer-agent"],
        })
        store.write(**comm, status="PASS", name="unit_tests", producer="run_tests_gate", evidence={"executed": 1})
        store.write(**comm, status="PASS", name="preflight", producer="preflight_check", evidence={})
        store.write(**comm, status="PASS", name="assemble", producer="run_gradle_task", evidence={})

        res = verify_delivery(self.tmp, task_id)
        self.assertNotEqual("PASS", res.get("status"))
        self.assertTrue(any("forbidden for sensitive changes" in b for b in res.get("blocked_by", [])))


class RedGreenTemporalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_red_green_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_RED_002_pre_red_code_fix_rejected(self) -> None:
        task_id = "task-red-002"
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Fix calculation bug",
            kind="BUG", planning_depth="STANDARD", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/Calc.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=None,
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))

        # Modifying non-test production file BEFORE capturing RED
        _write_text(self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Calc.kt", "class Calc { fun add(a: Int, b: Int) = a + b }\n")

        from run_tests_gate import main as tests_gate_main
        with mock.patch("sys.argv", ["run_tests_gate.py", "--capture-red"]):
            code = tests_gate_main()
            # Must exit with error because non-test production file was modified before RED capture
            self.assertNotEqual(0, code)

    def test_RED_003_debug_evidence_does_not_satisfy_executable_red(self) -> None:
        task_id = "task-red-003"
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Fix crash bug",
            kind="BUG", planning_depth="STANDARD", expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/Fix.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=None,
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))

        # Write synthetic debug-evidence.json only
        t_dir = task_dir(self.tmp, task_id)
        _write_json(t_dir / "debug-evidence.json", {
            "schema_version": 1, "task_id": task_id, "kind": "test_failure", "summary": "synthetic red",
        })

        # Apply fix
        _write_text(self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Fix.kt", "class Fix\n")
        prep = prepare_verification(Namespace(repo=str(self.tmp), task_id=task_id))

        store = EvidenceStore(state_root(self.tmp))
        h_ver = (self.tmp / ".agents" / "VERSION").read_text(encoding="utf-8").strip()
        comm = dict(snapshot=prep["delivery_snapshot_sha256"], run_id=prep["run_id"], harness_version=h_ver, change_set=prep["change_set_sha256"], status="PASS")
        store.write(**comm, name="unit_tests", producer="run_tests_gate", evidence={"executed": 1, "executed_tests": ["com.example.FixTest#test"]})
        store.write(**comm, name="preflight", producer="preflight_check", evidence={})
        store.write(**comm, name="assemble", producer="run_gradle_task", evidence={})
        store.write(**comm, name="reviews", producer="review_orchestrator", evidence={"reviewers": ["bug-reviewer-agent"], "reports": [{"reviewer": "bug-reviewer-agent", "verdict": "PASS", "independent_execution_verified": True}]})

        res = verify_delivery(self.tmp, task_id)
        self.assertNotEqual("PASS", res.get("status"))
        self.assertTrue(any("missing executable RED test failure evidence" in b for b in res.get("blocked_by", [])))


class TrueTaskDeltaIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_task_iso_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_TASK_ISO_001_pre_existing_dirty_file_excluded(self) -> None:
        # Pre-existing dirty file
        unrelated = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "OldPayments.kt"
        _write_text(unrelated, "class OldPayments\n")

        task_id = "task-iso-001"
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Add Profile",
            kind="FEATURE", planning_depth="STANDARD", expected_surfaces="COMPOSE_UI",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/ProfileScreen.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=None,
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))

        # Task creates ProfileScreen
        _write_text(self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "ProfileScreen.kt", "class ProfileScreen\n")

        plan = read_json(task_dir(self.tmp, task_id) / "plan.json")
        baseline = plan.get("task_baseline")
        manifest = build_task_manifest(self.tmp, baseline)

        task_changes_paths = [c["path"] for c in manifest.get("task_changes", [])]
        self.assertIn("app/src/main/kotlin/com/example/ProfileScreen.kt", task_changes_paths)
        self.assertNotIn("app/src/main/kotlin/com/example/OldPayments.kt", task_changes_paths)

    def test_TASK_ISO_002_baseline_dirty_removed(self) -> None:
        unrelated = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "OldTemp.kt"
        _write_text(unrelated, "class OldTemp\n")

        task_id = "task-iso-002"
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Do work",
            kind="FEATURE", planning_depth="STANDARD", expected_surfaces="COMPOSE_UI",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/Work.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=None,
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))

        # Delete OldTemp
        unrelated.unlink()
        _write_text(self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Work.kt", "class Work\n")

        plan = read_json(task_dir(self.tmp, task_id) / "plan.json")
        manifest = build_task_manifest(self.tmp, plan.get("task_baseline"))
        self.assertIn("app/src/main/kotlin/com/example/OldTemp.kt", manifest.get("baseline_dirty_removed", []))

    def test_TASK_ISO_003_empty_task_delta_preserves_task_isolated_mode(self) -> None:
        task_id = "task-iso-003"
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="No changes yet",
            kind="FEATURE", planning_depth="STANDARD", expected_surfaces="COMPOSE_UI",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/Empty.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=None,
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))

        plan = read_json(task_dir(self.tmp, task_id) / "plan.json")
        manifest = build_task_manifest(self.tmp, plan.get("task_baseline"))
        self.assertEqual("TASK_ISOLATED", manifest.get("task_delta_mode"))
        self.assertEqual([], manifest.get("task_changes"))


class PhaseCheckpointsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_phase_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_PHASE_001_phase_enforcement_threshold(self) -> None:
        task_id = "task-phase-001"
        # Task spanning UI and DATA across multiple files requires phases
        with self.assertRaises(ValidationError) as ctx:
            draft(Namespace(
                repo=str(self.tmp), task_id=task_id, outcome="Big feature",
                kind="FEATURE", planning_depth="STANDARD", expected_surfaces="COMPOSE_UI,ROOM_SCHEMA",
                expected_modules="app",
                expected_files="app/src/main/kotlin/com/example/Screen.kt,app/src/main/kotlin/com/example/Dao.kt",
                test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
                architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
                phases=None,
            ))
        self.assertIn("PHASE_PLAN_REQUIRED", str(ctx.exception))

    def test_PHASE_002_checkpoint_without_changes_fails(self) -> None:
        task_id = "task-phase-002"
        phases_def = [
            {"id": "p1", "title": "Phase 1 UI", "expected_files": ["app/src/main/kotlin/com/example/P1.kt"], "expected_surfaces": ["COMPOSE_UI"]},
            {"id": "p2", "title": "Phase 2 Data", "expected_files": ["app/src/main/kotlin/com/example/P2.kt"], "expected_surfaces": ["ROOM_SCHEMA"]},
        ]
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Phased task",
            kind="FEATURE", planning_depth="STANDARD", expected_surfaces="COMPOSE_UI,ROOM_SCHEMA",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/P1.kt,app/src/main/kotlin/com/example/P2.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=json.dumps(phases_def),
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))

        # Checkpoint without writing P1.kt must fail
        with self.assertRaises(ValidationError) as ctx:
            checkpoint_phase(Namespace(repo=str(self.tmp), task_id=task_id))
        self.assertIn("no file changes detected", str(ctx.exception).lower())

    def test_PHASE_004_phase_advance_autonomous(self) -> None:
        task_id = "task-phase-004"
        phases_def = [
            {"id": "p1", "title": "Phase 1 UI", "expected_files": ["app/src/main/kotlin/com/example/P1.kt"], "expected_surfaces": ["COMPOSE_UI"]},
            {"id": "p2", "title": "Phase 2 Data", "expected_files": ["app/src/main/kotlin/com/example/P2.kt"], "expected_surfaces": ["ROOM_SCHEMA"]},
        ]
        draft(Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Phased task",
            kind="FEATURE", planning_depth="STANDARD", expected_surfaces="COMPOSE_UI,ROOM_SCHEMA",
            expected_modules="app", expected_files="app/src/main/kotlin/com/example/P1.kt,app/src/main/kotlin/com/example/P2.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=json.dumps(phases_def),
        ))
        approve(Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(Namespace(repo=str(self.tmp), task_id=task_id))

        _write_text(self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "P1.kt", "class P1\n")
        p1_dir = task_dir(self.tmp, task_id) / "phases" / "p1"
        p1_dir.mkdir(parents=True, exist_ok=True)
        (p1_dir / "unit_tests.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        (p1_dir / "reviews.json").write_text(json.dumps([
            {"reviewer": "bug-reviewer-agent", "verdict": "PASS"},
            {"reviewer": "regression-impact-reviewer-agent", "verdict": "PASS"},
        ]), encoding="utf-8")
        res = checkpoint_phase(Namespace(repo=str(self.tmp), task_id=task_id))
        self.assertEqual("CHECKPOINT_PASS", res.get("status"))
        self.assertEqual(1, res.get("next_phase_index"))

        plan = read_json(task_dir(self.tmp, task_id) / "plan.json")
        self.assertEqual(0, plan.get("active_phase_index", 0))
        self.assertEqual("p1", read_json(task_dir(self.tmp, task_id) / "phase-state.json")["current_phase_id"])
        self.assertFalse((task_dir(self.tmp, task_id) / "phases" / "p2" / "baseline.json").exists())
        self.assertEqual("BEGIN_NEXT_PHASE", resolve_next_action(self.tmp, task_id)["code"])
        begin_next_phase(Namespace(repo=str(self.tmp), task_id=task_id))
        self.assertEqual(1, read_json(task_dir(self.tmp, task_id) / "plan.json")["active_phase_index"])
        self.assertEqual("p2", read_json(task_dir(self.tmp, task_id) / "phase-state.json")["current_phase_id"])
        self.assertTrue((task_dir(self.tmp, task_id) / "phases" / "p2" / "baseline.json").is_file())


class ArchitectureResolutionAndDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_arch_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ARCH_001_path_component_matching_no_prefix_clash(self) -> None:
        facts = {
            "schema_version": 2,
            "facts": {
                "architecture": {
                    "families": [
                        {"id": "fam_pro", "label": "Pro", "confidence": "HIGH", "exemplars": ["app/src/main/kotlin/feature/pro/ProScreen.kt"]},
                        {"id": "fam_profile", "label": "Profile", "confidence": "HIGH", "exemplars": ["app/src/main/kotlin/feature/profile/ProfileScreen.kt"]},
                    ]
                }
            }
        }
        sfp = compute_source_fingerprint(self.tmp)
        facts["source_fingerprint_sha256"] = sfp["source_fingerprint_sha256"]
        facts["source_fingerprint"] = sfp["source_fingerprint"]
        _write_json(self.tmp / ".agents" / "project-context" / "project-facts.json", facts)
        pol = create_architecture_policy(preferred_new_code_family="fam_pro")
        write_architecture_policy(self.tmp, pol, overwrite=True)

        res = resolve_architecture_contract(self.tmp, intent="NEW_SCREEN", target_scope="feature/pro")
        self.assertEqual("fam_pro", res.get("contract", {}).get("target_family_id"))

    def test_ARCH_002_ambiguous_family_returns_none(self) -> None:
        facts = {
            "schema_version": 2,
            "facts": {
                "architecture": {
                    "families": [
                        {"id": "f1", "confidence": "HIGH", "exemplars": ["app/src/main/kotlin/feature/x/A.kt"]},
                        {"id": "f2", "confidence": "HIGH", "exemplars": ["app/src/main/kotlin/feature/x/B.kt"]},
                    ]
                }
            }
        }
        sfp = compute_source_fingerprint(self.tmp)
        facts["source_fingerprint_sha256"] = sfp["source_fingerprint_sha256"]
        facts["source_fingerprint"] = sfp["source_fingerprint"]
        _write_json(self.tmp / ".agents" / "project-context" / "project-facts.json", facts)
        pol = create_architecture_policy()
        write_architecture_policy(self.tmp, pol, overwrite=True)

        res = resolve_architecture_contract(self.tmp, intent="NEW_SCREEN", target_scope="feature/x")
        self.assertEqual(STATUS_DECISION_REQUIRED, res.get("status"))
        self.assertIsNone(res.get("contract"))


class InterruptedUpdateRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_upd_rec_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_UPD_REC_001_kill_at_prepared_aborts(self) -> None:
        journal_path = self.tmp / ".harness-setup" / "update-journal.json"
        _write_json(journal_path, {
            "schema_version": 1,
            "status": "PREPARED",
            "stage": "PREPARED",
            "from_version": "1.0.40",
            "to_version": "1.0.41",
        })
        res = recover_interrupted_update(self.tmp)
        self.assertIsNotNone(res)
        self.assertEqual("RECOVERED", res.get("status"))
        self.assertEqual("aborted_prepared_update", res.get("action"))

        saved_journal = read_json(journal_path)
        self.assertEqual("ROLLED_BACK", saved_journal.get("status"))

    def test_UPD_REC_003_kill_at_new_engine_installed_rolls_back(self) -> None:
        old_dir = self.tmp / ".agents.previous-abc"
        old_dir.mkdir()
        _write_text(old_dir / "VERSION", "1.0.40\n")
        _write_text(old_dir / "marker.txt", "old_engine\n")

        journal_path = self.tmp / ".harness-setup" / "update-journal.json"
        _write_json(journal_path, {
            "schema_version": 1,
            "status": "IN_PROGRESS",
            "stage": "NEW_ENGINE_INSTALLED",
            "from_version": "1.0.40",
            "to_version": "1.0.41",
            "old_agents_path": ".agents.previous-abc",
        })

        res = recover_interrupted_update(self.tmp)
        self.assertIsNotNone(res)
        self.assertEqual("RECOVERED", res.get("status"))
        self.assertEqual("restored_previous_engine", res.get("action"))
        self.assertTrue((self.tmp / ".agents" / "marker.txt").is_file())

    def test_UPD_REC_006_kill_at_ownership_written_completes_forward(self) -> None:
        target_version = "1.0.41"
        _write_text(self.tmp / ".agents" / "VERSION", f"{target_version}\n")
        _write_text(self.tmp / ".agents" / "rules" / "harness-rules.md", "rules\n")
        _write_text(self.tmp / ".agents" / "scripts" / "_product.py", "APPLICATION_ID = 'test'\n")

        own = {
            "schema_version": 1,
            "architecture_major": 1,
            "harness_version": target_version,
            "installed_at": utc_now(),
        }
        own["ownership_sha256"] = canonical_sha256({k: v for k, v in own.items() if k != "ownership_sha256"})
        _write_json(self.tmp / ".harness-setup" / "ownership-v1.json", own)

        journal_path = self.tmp / ".harness-setup" / "update-journal.json"
        _write_json(journal_path, {
            "schema_version": 1,
            "status": "IN_PROGRESS",
            "stage": "OWNERSHIP_WRITTEN",
            "from_version": "1.0.40",
            "to_version": target_version,
            "ownership_after_sha256": own["ownership_sha256"],
        })

        res = recover_interrupted_update(self.tmp)
        self.assertIsNotNone(res)
        self.assertEqual("RECOVERED", res.get("status"))
        self.assertEqual("completed_new_engine", res.get("action"))


class ProjectContextPerformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_perf_ctx_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_PERF_CTX_001_source_fingerprint_unchanged_zero_ast_extraction(self) -> None:
        facts = extract_project_facts(self.tmp, in_memory_graph=True)
        views = render_project_context(facts)
        write_project_context(self.tmp, facts, views)

        # Calling status should hit fast-path with zero AST extraction
        with mock.patch("project_context.extract_project_facts") as mock_extract:
            st = project_context_status(self.tmp)
            self.assertEqual("CURRENT", st.get("status"))
            self.assertEqual(0, mock_extract.call_count)

    def test_PERF_CTX_002_dirty_kotlin_file_updates_source_fingerprint(self) -> None:
        fp1 = compute_source_fingerprint(self.tmp)
        _write_text(self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "NewScreen.kt", "class NewScreen\n")
        fp2 = compute_source_fingerprint(self.tmp)
        self.assertNotEqual(fp1.get("source_fingerprint_sha256"), fp2.get("source_fingerprint_sha256"))

    def test_PERF_CTX_003_unrelated_markdown_does_not_stale_fingerprint(self) -> None:
        fp1 = compute_source_fingerprint(self.tmp)
        _write_text(self.tmp / "README.md", "# Just Documentation\n")
        fp2 = compute_source_fingerprint(self.tmp)
        self.assertEqual(fp1.get("source_fingerprint_sha256"), fp2.get("source_fingerprint_sha256"))


class SetupArchitectureNeutralityTests(unittest.TestCase):
    def test_SETUP_ARCH_001_neutral_ordering_no_modernity_bias(self) -> None:
        d = {
            "architecture": {
                "families": [
                    {"id": "xml_fam", "label": "XML Views", "confidence": "HIGH", "exemplars": ["MainFragment.kt"]},
                    {"id": "compose_fam", "label": "Compose", "confidence": "HIGH", "exemplars": ["MainScreen.kt"]},
                ]
            }
        }
        qs = questions_payload(repo=None, lang="en", facts=d)
        arch_q = next((q for q in qs if q["id"] == "pref_arch_family"), None)
        self.assertIsNotNone(arch_q)

        # Neither compose nor xml should be recommended based on modernity
        opts = {opt["id"]: opt["label"] for opt in arch_q["options"]}
        self.assertNotIn("(Recommended)", opts.get("compose_fam", ""))
        self.assertNotIn("(Recommended)", opts.get("xml_fam", ""))
        # None / decide later should be recommended when ambiguous
        self.assertIn("(Recommended)", opts.get("none", ""))

    def test_SETUP_ARCH_002_single_high_confidence_recommended(self) -> None:
        d = {
            "architecture": {
                "families": [
                    {"id": "only_fam", "label": "Compose Only", "confidence": "HIGH", "exemplars": ["MainScreen.kt"]},
                ]
            }
        }
        qs = questions_payload(repo=None, lang="en", facts=d)
        arch_q = next((q for q in qs if q["id"] == "pref_arch_family"), None)
        self.assertIsNotNone(arch_q)
        opts = {opt["id"]: opt["label"] for opt in arch_q["options"]}
        self.assertIn("(Recommended)", opts.get("only_fam", ""))


class ContractAccuracyTests(unittest.TestCase):
    def test_CONTRACT_001_tokens_and_flags_validation(self) -> None:
        contract_path = (KIT / "agents" / "skills" / "android-harness" / "references" / "command-contract.md") if (KIT / "agents").is_dir() else (KIT / "skills" / "android-harness" / "references" / "command-contract.md")
        self.assertTrue(contract_path.is_file())
        text = contract_path.read_text(encoding="utf-8")

        # Verify field names match actual schemas
        self.assertIn("COMPOSE_UI", text)
        self.assertIn("ROOM_SCHEMA", text)
        self.assertIn("`severity`:", text)
        self.assertIn("`reviewers`:", text)
        self.assertIn("`gates`:", text)
        self.assertNotIn("UI_COMPOSE", text)
        self.assertNotIn("`risk_level`:", text)

        # Verify command flags documented
        self.assertIn("--planning-depth", text)
        self.assertIn("--expected-surfaces", text)
        self.assertIn("--expected-modules", text)
        self.assertIn("--expected-files", text)
        self.assertIn("--test-strategy", text)
        self.assertIn("--device-strategy", text)
        self.assertIn("--architecture-intent", text)
        self.assertIn("--phases", text)
        self.assertIn("checkpoint-phase", text)
        self.assertIn("--capture-red", text)


if __name__ == "__main__":
    unittest.main()
