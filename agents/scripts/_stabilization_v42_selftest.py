"""Targeted regression selftest suite for Android Agent Harness v1.0.42 stabilization.

Covers the 8 surgical fixes specified in the v1.0.42 patch spec:
- RED42-001..005 (Canonical Executable RED Only)
- REV42-001..005 (Authentic Host Reviewer Transcripts)
- CONTRACT42-001 (Command Contract Parity)
- PHASE42-001..006 (Real Phase Checkpoints)
- ARCH42-001..005 (Architecture Confidence & Authority)
- PERF42-001..004 (Dirty Source Fingerprint Content Identity)
- UPDATE42-001..004 (Update Recovery Ownership Integrity)
- SETUP42-001..004 (Neutral Setup Question Recommendations)
- PREFLIGHT42-001..004 (Task-Scoped Preflight & Room Gate)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from _vnext_common import ValidationError, canonical_sha256, utc_now, read_json, atomic_write_json
from workflow import (
    draft,
    record_approval,
    begin_task,
    prepare_verification,
    record_debug_evidence,
    task_dir,
    state_root,
    load_task_baseline,
    _load_plan,
)
from final_verifier import verify_task
from evidence_store import EvidenceStore


def _setup_mock_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)

    app_kt = root / "app" / "src" / "main" / "kotlin" / "com" / "example"
    app_kt.mkdir(parents=True, exist_ok=True)
    (app_kt / "MainActivity.kt").write_text("package com.example\nclass MainActivity\n", encoding="utf-8")

    test_kt = root / "app" / "src" / "test" / "kotlin" / "com" / "example"
    test_kt.mkdir(parents=True, exist_ok=True)
    (test_kt / "OrderTest.kt").write_text("package com.example\nclass OrderTest\n", encoding="utf-8")

    (root / "build.gradle").write_text("// top-level\n", encoding="utf-8")
    (root / "settings.gradle").write_text("include ':app'\n", encoding="utf-8")
    (root / "gradlew.bat").write_text("@echo off\n", encoding="utf-8")
    unix_wrapper = root / "gradlew"
    unix_wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    unix_wrapper.chmod(unix_wrapper.stat().st_mode | 0o111)

    version_file = SCRIPTS.parent / "VERSION"
    v_str = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.42"
    agents_dir = root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "VERSION").write_text(f"{v_str}\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=root, check=True)


class RedAuthorityV42Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_red42_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_RED42_001_debug_evidence_creates_no_red_file(self) -> None:
        """RED42-001: workflow.py debug-evidence --kind test_failure writes debug-evidence.json but NO red-evidence.json."""
        task_id = "TASK-RED-001"
        draft(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            outcome="Fix defect",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        res = record_debug_evidence(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            kind="test_failure",
            reference="com.example.OrderTest#testFailure",
            hypothesis="division by zero",
            risk="none",
        ))
        t_dir = task_dir(self.tmp, task_id)
        self.assertTrue((t_dir / "debug-evidence.json").is_file(), "debug-evidence.json must exist")
        self.assertFalse((t_dir / "red-evidence.json").is_file(), "red-evidence.json must NOT exist")
        dbg_data = read_json(t_dir / "debug-evidence.json")
        self.assertFalse(dbg_data["entries"][0].get("satisfies_executable_red", True))

    def test_RED42_002_schema_2_red_rejected_on_modern_task(self) -> None:
        """RED42-002: Schema 2 RED on modern v1.0.41+ task fails executable RED verification."""
        task_id = "TASK-RED-002"
        draft(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            outcome="Fix defect 2",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            expected_files="app/src/main/kotlin/com/example/Fix.kt",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        t_dir = task_dir(self.tmp, task_id)
        schema2_red = {
            "schema_version": 2,
            "status": "RED_CAPTURED",
            "task_id": task_id,
            "test_id": "com.example.OrderTest#testFailure",
            "hypothesis": "hyp",
            "snapshot_sha256": "snap123",
            "captured_at": utc_now(),
        }
        atomic_write_json(t_dir / "red-evidence.json", schema2_red)

        (self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Fix.kt").write_text("package com.example\nclass Fix\n", encoding="utf-8")
        prep = prepare_verification(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        store = EvidenceStore(state_root(self.tmp))
        store.write(
            snapshot=prep["delivery_snapshot_sha256"],
            run_id=prep["run_id"],
            name="unit_tests",
            producer="run_tests_gate",
            harness_version="1.0.42",
            change_set=prep["change_set_sha256"],
            status="PASS",
            evidence={"executed": 1, "failed": 0, "new_regressions": [], "executed_tests": ["com.example.OrderTest#testFailure"]},
        )
        res = verify_task(self.tmp, task_id)
        red_chk = next((c for c in res["checks"] if c["name"] == "red_evidence"), None)
        self.assertIsNotNone(red_chk)
        self.assertEqual("FAIL", red_chk["status"])
        self.assertIn("missing executable RED test failure evidence", red_chk["detail"])

    def test_RED42_003_schema_3_wrong_producer_fails(self) -> None:
        """RED42-003: Schema 3 RED with producer != run_tests_gate fails verification."""
        task_id = "TASK-RED-003"
        draft(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            outcome="Fix defect 3",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            expected_files="app/src/main/kotlin/com/example/Fix.kt",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        t_dir = task_dir(self.tmp, task_id)
        base = load_task_baseline(self.tmp, task_id)
        plan = _load_plan(self.tmp, task_id)

        red3 = {
            "schema_version": 3,
            "task_id": task_id,
            "plan_sha256": plan["plan_sha256"],
            "captured_at": utc_now(),
            "producer": "untrusted_agent",
            "pre_fix_delivery_snapshot_sha256": "snap_prefix",
            "pre_fix_change_set_sha256": "cs_prefix",
            "pre_fix_task_change_set_sha256": "cs_prefix",
            "baseline_sha256": base.get("baseline_sha256", ""),
            "reproduction_kind": "FAILING_TEST",
            "gradle_task": ":app:testDebugUnitTest",
            "failed_tests": [{"test_id": "com.example.OrderTest#testFailure", "failure_fingerprint": "fp"}],
        }
        red3["red_sha256"] = canonical_sha256({k: v for k, v in red3.items() if k != "red_sha256"})
        atomic_write_json(t_dir / "red-evidence.json", red3)

        (self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Fix.kt").write_text("package com.example\nclass Fix\n", encoding="utf-8")
        prep = prepare_verification(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        store = EvidenceStore(state_root(self.tmp))
        store.write(
            snapshot=prep["delivery_snapshot_sha256"],
            run_id=prep["run_id"],
            name="unit_tests",
            producer="run_tests_gate",
            harness_version="1.0.42",
            change_set=prep["change_set_sha256"],
            status="PASS",
            evidence={"executed": 1, "failed": 0, "new_regressions": [], "executed_tests": ["com.example.OrderTest#testFailure"]},
        )
        res = verify_task(self.tmp, task_id)
        red_chk = next((c for c in res["checks"] if c["name"] == "red_evidence"), None)
        self.assertIsNotNone(red_chk)
        self.assertEqual("FAIL", red_chk["status"])

    def test_RED42_004_canonical_schema_3_accepted(self) -> None:
        """RED42-004: Valid schema 3 RED with producer=run_tests_gate passes verification."""
        task_id = "TASK-RED-004"
        draft(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            outcome="Fix defect 4",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            expected_files="app/src/main/kotlin/com/example/Fix.kt",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        t_dir = task_dir(self.tmp, task_id)
        base = load_task_baseline(self.tmp, task_id)
        plan = _load_plan(self.tmp, task_id)

        red3 = {
            "schema_version": 3,
            "task_id": task_id,
            "plan_sha256": plan["plan_sha256"],
            "captured_at": utc_now(),
            "producer": "run_tests_gate",
            "pre_fix_delivery_snapshot_sha256": "pre_snap",
            "pre_fix_change_set_sha256": "pre_cs",
            "pre_fix_task_change_set_sha256": "pre_cs",
            "baseline_sha256": base.get("baseline_sha256", ""),
            "reproduction_kind": "FAILING_TEST",
            "gradle_task": ":app:testDebugUnitTest",
            "failed_tests": [{"test_id": "com.example.OrderTest#testFailure", "failure_fingerprint": "fp"}],
        }
        red3["red_sha256"] = canonical_sha256({k: v for k, v in red3.items() if k != "red_sha256"})
        atomic_write_json(t_dir / "red-evidence.json", red3)

        (self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Fix.kt").write_text("package com.example\nclass Fix\n", encoding="utf-8")
        prep = prepare_verification(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        store = EvidenceStore(state_root(self.tmp))
        store.write(
            snapshot=prep["delivery_snapshot_sha256"],
            run_id=prep["run_id"],
            name="unit_tests",
            producer="run_tests_gate",
            harness_version="1.0.42",
            change_set=prep["change_set_sha256"],
            status="PASS",
            evidence={"executed": 1, "failed": 0, "new_regressions": [], "executed_tests": ["com.example.OrderTest#testFailure"]},
        )
        res = verify_task(self.tmp, task_id)
        red_chk = next((c for c in res["checks"] if c["name"] == "red_evidence"), None)
        self.assertIsNotNone(red_chk)
        self.assertEqual("PASS", red_chk["status"])

    def test_RED42_005_debug_test_failure_without_canonical_red_fails(self) -> None:
        """RED42-005: Debug test_failure + GREEN unit test but no canonical RED fails verification."""
        task_id = "TASK-RED-005"
        draft(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            outcome="Fix defect 5",
            kind="BUG",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":",
            expected_files="app/src/main/kotlin/com/example/Fix.kt",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        record_debug_evidence(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            kind="test_failure",
            reference="com.example.OrderTest#testCalculateTotal",
            hypothesis="Division by zero on empty cart",
            risk="None",
        ))

        (self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Fix.kt").write_text("package com.example\nclass Fix\n", encoding="utf-8")
        prep = prepare_verification(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        store = EvidenceStore(state_root(self.tmp))
        store.write(
            snapshot=prep["delivery_snapshot_sha256"],
            run_id=prep["run_id"],
            name="unit_tests",
            producer="run_tests_gate",
            harness_version="1.0.42",
            change_set=prep["change_set_sha256"],
            status="PASS",
            evidence={"executed": 1, "failed": 0, "new_regressions": [], "executed_tests": ["com.example.OrderTest#testCalculateTotal"]},
        )
        res = verify_task(self.tmp, task_id)
        red_chk = next((c for c in res["checks"] if c["name"] == "red_evidence"), None)
        self.assertIsNotNone(red_chk)
        self.assertEqual("FAIL", red_chk["status"])
        self.assertIn("missing executable RED test failure evidence", red_chk["detail"])


class ReviewerProofV42Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_rev42_")).resolve()
        _setup_mock_repo(self.tmp)
        self.app_data = self.tmp / "test_app_data"
        self.old_app_data = os.environ.get("ANTIGRAVITY_APP_DATA")
        os.environ["ANTIGRAVITY_APP_DATA"] = str(self.app_data)

    def tearDown(self) -> None:
        if self.old_app_data is not None:
            os.environ["ANTIGRAVITY_APP_DATA"] = self.old_app_data
        else:
            os.environ.pop("ANTIGRAVITY_APP_DATA", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_receipt(self, task_id: str, run_id: str, reviewer: str, pkg_sha: str, subagent_id: str = "") -> Path:
        rc_dir = task_dir(self.tmp, task_id) / "reviewer-dispatches"
        rc_dir.mkdir(parents=True, exist_ok=True)
        rc_data = {
            "schema_version": 1,
            "task_id": task_id,
            "run_id": run_id,
            "reviewer": reviewer,
            "subagent_id": subagent_id,
            "review_package_sha256": pkg_sha,
            "dispatched_at": utc_now(),
            "host": "antigravity",
        }
        rc_data["receipt_sha256"] = canonical_sha256({k: v for k, v in rc_data.items() if k != "receipt_sha256"})
        rc_path = rc_dir / f"{reviewer}.json"
        atomic_write_json(rc_path, rc_data)
        return rc_path

    def test_REV42_001_arbitrary_temp_jsonl_rejected(self) -> None:
        """REV42-001: Valid receipt + arbitrary temp JSONL is rejected (returns False)."""
        from record_review import verify_independent_reviewer_execution
        task_id = "TASK-REV-001"
        run_id = "run-001"
        pkg_sha = "a" * 64
        self._create_receipt(task_id, run_id, "security-reviewer-agent", pkg_sha)

        # Arbitrary temp file
        temp_dir = self.tmp / "arbitrary_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        fake_transcript = temp_dir / "fake.jsonl"
        fake_transcript.write_text(json.dumps({"content": "SECURITY_PASS"}) + "\n", encoding="utf-8")

        ok, proof = verify_independent_reviewer_execution(
            self.tmp,
            task_id=task_id,
            run_id=run_id,
            reviewer="security-reviewer-agent",
            package_sha256=pkg_sha,
            subagent_id="conv-123",
            transcript_path=fake_transcript,
        )
        self.assertFalse(ok)
        self.assertFalse(proof.get("verified"))

    def test_REV42_002_canonical_trusted_transcript_accepted(self) -> None:
        """REV42-002: Valid receipt + canonical trusted Antigravity transcript passes (returns True)."""
        from record_review import verify_independent_reviewer_execution
        task_id = "TASK-REV-002"
        run_id = "run-002"
        pkg_sha = "b" * 64
        sub_id = "conv-trusted-456"
        self._create_receipt(task_id, run_id, "security-reviewer-agent", pkg_sha, subagent_id=sub_id)

        # Place transcript in canonical test-injected brain root
        t_dir = self.app_data / "brain" / sub_id / ".system_generated" / "logs"
        t_dir.mkdir(parents=True, exist_ok=True)
        t_file = t_dir / "transcript.jsonl"
        t_file.write_text(json.dumps({"content": "SECURITY_PASS"}) + "\n", encoding="utf-8")

        ok, proof = verify_independent_reviewer_execution(
            self.tmp,
            task_id=task_id,
            run_id=run_id,
            reviewer="security-reviewer-agent",
            package_sha256=pkg_sha,
            subagent_id=sub_id,
        )
        self.assertTrue(ok)
        self.assertTrue(proof.get("verified"))
        self.assertEqual("ANTIGRAVITY_SUBAGENT_TRANSCRIPT", proof.get("proof_kind"))

    def test_REV42_003_path_traversal_fake_conversation_path_rejected(self) -> None:
        """REV42-003: Path traversal / fake conversation path rejected."""
        from record_review import verify_independent_reviewer_execution
        task_id = "TASK-REV-003"
        run_id = "run-003"
        pkg_sha = "c" * 64
        self._create_receipt(task_id, run_id, "security-reviewer-agent", pkg_sha)

        ok, proof = verify_independent_reviewer_execution(
            self.tmp,
            task_id=task_id,
            run_id=run_id,
            reviewer="security-reviewer-agent",
            package_sha256=pkg_sha,
            subagent_id="../../escaped/path",
        )
        self.assertFalse(ok)
        self.assertFalse(proof.get("verified"))

    def test_REV42_004_transcript_id_mismatch_rejected(self) -> None:
        """REV42-004: Transcript ID mismatch between receipt and call rejected."""
        from record_review import verify_independent_reviewer_execution
        task_id = "TASK-REV-004"
        run_id = "run-004"
        pkg_sha = "d" * 64
        self._create_receipt(task_id, run_id, "security-reviewer-agent", pkg_sha, subagent_id="bound-sub-1")

        # Caller provides different subagent_id
        ok, proof = verify_independent_reviewer_execution(
            self.tmp,
            task_id=task_id,
            run_id=run_id,
            reviewer="security-reviewer-agent",
            package_sha256=pkg_sha,
            subagent_id="other-sub-2",
        )
        self.assertFalse(ok)
        self.assertFalse(proof.get("verified"))

    def test_REV42_005_high_task_imported_with_response_path_unverified_blocks(self) -> None:
        """REV42-005: HIGH severity task imported with normal --response path has independent_execution_verified=false and blocks delivery."""
        import record_review
        task_id = "TASK-REV-005"
        draft(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            outcome="Sensitive auth change",
            kind="FEATURE",
            expected_surfaces="AUTH,BUSINESS_LOGIC",
            expected_modules=":",
            expected_files="app/src/main/kotlin/com/example/Auth.kt",
            test_strategy="unit tests",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        (self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Auth.kt").write_text("package com.example\nclass Auth {\n    fun login(token: String): Boolean = true\n}\n", encoding="utf-8")
        prep = prepare_verification(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        import review_package
        _, pkg = review_package.build_package(self.tmp, task_id)
        pkg_sha = pkg["package_sha256"][:12]

        resp_file = self.tmp / "resp.txt"
        resp_file.write_text(f"VERDICT: PASS\nEVIDENCE pkg={pkg_sha} cites=0\nAll good.\n", encoding="utf-8")

        # Import via --response without valid subagent conversation id for all required reviewers
        for r in ["bug-reviewer-agent", "convention-reviewer-agent", "security-reviewer-agent", "perf-anr-guardian-agent", "regression-impact-reviewer-agent"]:
            ret = record_review.main([
                "--repo", str(self.tmp),
                "--task", task_id,
                "--response", f"{r}={resp_file}",
            ])
            self.assertEqual(0, ret)

        store = EvidenceStore(state_root(self.tmp))
        store.write(
            snapshot=prep["delivery_snapshot_sha256"],
            run_id=prep["run_id"],
            name="unit_tests",
            producer="run_tests_gate",
            harness_version="1.0.42",
            change_set=prep["change_set_sha256"],
            status="PASS",
            evidence={"executed": 1, "failed": 0, "new_regressions": []},
        )
        res = verify_task(self.tmp, task_id)
        # Should be BLOCKED because independent_execution_verified is false on sensitive/HIGH change
        self.assertEqual("BLOCKED", res.get("status"))
        rev_chk = next((c for c in res["checks"] if c["name"] == "reviews"), None)
        self.assertIsNotNone(rev_chk)
        self.assertEqual("FAIL", rev_chk["status"])
        self.assertIn("lacks verified independent execution proof", rev_chk["detail"])


class ContractV42Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_contract42_"))
        (self.tmp / ".agents").mkdir(parents=True)
        (self.tmp / ".agents" / "VERSION").write_text("1.0.42\n", encoding="utf-8")
        (self.tmp / ".git").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_CONTRACT42_001_real_parser_and_remediation(self) -> None:
        """CONTRACT42-001: CLI accepts BOUNDED/ARCHITECTURAL, rejects STANDARD, parses --external-write zoho_sprints, and parses remediation cmd."""
        import shlex
        from unittest import mock
        import workflow
        from workflow import build_parser, build_remediation_command

        parser = build_parser()

        # 1. Canonical BOUNDED draft command parses cleanly
        args = parser.parse_args([
            "draft",
            "--repo", str(self.tmp),
            "--task-id", "TASK-CONTRACT-01",
            "--outcome", "Test outcome",
            "--kind", "FEATURE",
            "--planning-depth", "BOUNDED",
            "--external-write", "zoho_sprints",
        ])
        self.assertEqual("BOUNDED", args.planning_depth)
        self.assertEqual(["zoho_sprints"], args.external_write)

        # 2. ARCHITECTURAL parses cleanly
        args_arch = parser.parse_args([
            "draft",
            "--repo", str(self.tmp),
            "--task-id", "TASK-CONTRACT-02",
            "--outcome", "Arch outcome",
            "--kind", "REFACTOR",
            "--planning-depth", "ARCHITECTURAL",
        ])
        self.assertEqual("ARCHITECTURAL", args_arch.planning_depth)

        # 3. STANDARD is rejected by argparse
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr"):
                parser.parse_args([
                    "draft",
                    "--repo", str(self.tmp),
                    "--task-id", "TASK-CONTRACT-03",
                    "--outcome", "Invalid outcome",
                    "--planning-depth", "STANDARD",
                ])

        # 4. Canonical remediation command generated by build_remediation_command parses via real parser
        plan = {
            "requested_outcome": "Add login feature",
            "task_kind": "FEATURE",
            "planning_depth": "BOUNDED",
            "expected_surfaces": ["AUTH"],
            "expected_modules": [":app"],
            "expected_files": ["app/src/main/kotlin/com/example/Auth.kt"],
            "architecture_contract": {"mode": "NEW", "target_scope": "login", "target_family_id": "MVI_ORBIT"},
            "phases": [{"id": 1, "description": "Phase 1"}],
        }
        policy = {"surfaces": ["AUTH", "BUSINESS_LOGIC"]}
        manifest = {"task_changes": [{"path": "app/src/main/kotlin/com/example/Auth.kt"}]}

        remediation_cmd = build_remediation_command(self.tmp, "TASK-CONTRACT-04", plan, policy, manifest)
        self.assertIn("--planning-depth BOUNDED", remediation_cmd)

        tokens = shlex.split(remediation_cmd.replace("\\\n", " "))
        cmd_args = tokens[tokens.index("draft"):]
        parsed_remediation = parser.parse_args(cmd_args)
        self.assertEqual("TASK-CONTRACT-04", parsed_remediation.task_id)
        self.assertEqual("BOUNDED", parsed_remediation.planning_depth)
        self.assertEqual("NEW_SCREEN", parsed_remediation.architecture_intent)

        # 5. Verify command-contract.md contains BOUNDED and no SHALLOW
        contract_doc = (Path(__file__).resolve().parent.parent / "skills" / "android-harness" / "references" / "command-contract.md").read_text(encoding="utf-8")
        self.assertIn("--planning-depth <BOUNDED|ARCHITECTURAL>", contract_doc)
        self.assertNotIn("<SHALLOW|STANDARD|DEEP>", contract_doc)
        self.assertIn("--external-write zoho_sprints", contract_doc)
        self.assertNotIn('"<comma-separated external paths>"', contract_doc)


class PhaseV42Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_phase42_"))
        _setup_mock_repo(self.tmp)
        (self.tmp / ".agents").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".agents" / "VERSION").write_text("1.0.42\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_PHASE42_001_nested_module_resolution(self) -> None:
        """PHASE42-001: Nested module path resolves to :feature:subscription, not :feature."""
        from workflow import resolve_phase_modules
        manifest = {
            "task_changes": [
                {"path": "feature/subscription/src/main/kotlin/com/example/Sub.kt"}
            ]
        }
        mods = resolve_phase_modules(self.tmp, manifest)
        self.assertEqual([":feature:subscription"], mods)
        self.assertNotIn(":feature", mods)

    def test_PHASE42_002_policy_required_test_failure_blocks_phase(self) -> None:
        """PHASE42-002: Policy-required test fails -> phase does not advance."""
        from workflow import draft, record_approval, begin_task, checkpoint_phase
        task_id = "TASK-PHASE-002"
        phases_def = [
            {"id": "p1", "title": "Phase 1 Logic", "expected_files": ["app/src/main/kotlin/com/example/Logic.kt"]},
        ]
        draft(argparse.Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Phased task",
            kind="FEATURE", planning_depth="BOUNDED", expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app", expected_files="app/src/main/kotlin/com/example/Logic.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=json.dumps(phases_def), force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        logic_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Logic.kt"
        logic_file.parent.mkdir(parents=True, exist_ok=True)
        logic_file.write_text("package com.example\nclass Logic\n", encoding="utf-8")

        p1_dir = task_dir(self.tmp, task_id) / "phases" / "p1"
        p1_dir.mkdir(parents=True, exist_ok=True)
        # Write failing test evidence
        (p1_dir / "unit_tests.json").write_text(json.dumps({"status": "FAIL", "detail": "1 test failed"}), encoding="utf-8")

        with self.assertRaises(ValidationError) as ctx:
            checkpoint_phase(argparse.Namespace(repo=str(self.tmp), task_id=task_id))
        self.assertIn("unit tests failed", str(ctx.exception).lower())

    def test_PHASE42_003_policy_requires_reviewer_missing_evidence_blocks(self) -> None:
        """PHASE42-003: Policy requires reviewer but no reviewer evidence -> phase does not advance."""
        from workflow import draft, record_approval, begin_task, checkpoint_phase
        task_id = "TASK-PHASE-003"
        phases_def = [
            {"id": "p1", "title": "Phase 1 Logic", "expected_files": ["app/src/main/kotlin/com/example/Logic.kt"]},
        ]
        draft(argparse.Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Phased task",
            kind="FEATURE", planning_depth="BOUNDED", expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app", expected_files="app/src/main/kotlin/com/example/Logic.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=json.dumps(phases_def), force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        logic_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Logic.kt"
        logic_file.parent.mkdir(parents=True, exist_ok=True)
        logic_file.write_text("package com.example\nclass Logic\n", encoding="utf-8")

        p1_dir = task_dir(self.tmp, task_id) / "phases" / "p1"
        p1_dir.mkdir(parents=True, exist_ok=True)
        # Passing test evidence, but NO review evidence
        (p1_dir / "unit_tests.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

        with self.assertRaises(ValidationError) as ctx:
            checkpoint_phase(argparse.Namespace(repo=str(self.tmp), task_id=task_id))
        self.assertIn("requires review from", str(ctx.exception).lower())

    def test_PHASE42_004_blocking_phase_finding_blocks_advance(self) -> None:
        """PHASE42-004: Blocking phase finding -> phase does not advance."""
        from workflow import draft, record_approval, begin_task, checkpoint_phase
        task_id = "TASK-PHASE-004"
        phases_def = [
            {"id": "p1", "title": "Phase 1 Logic", "expected_files": ["app/src/main/kotlin/com/example/Logic.kt"]},
        ]
        draft(argparse.Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Phased task",
            kind="FEATURE", planning_depth="BOUNDED", expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app", expected_files="app/src/main/kotlin/com/example/Logic.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=json.dumps(phases_def), force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        logic_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Logic.kt"
        logic_file.parent.mkdir(parents=True, exist_ok=True)
        logic_file.write_text("package com.example\nclass Logic\n", encoding="utf-8")

        p1_dir = task_dir(self.tmp, task_id) / "phases" / "p1"
        p1_dir.mkdir(parents=True, exist_ok=True)
        (p1_dir / "unit_tests.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        # Review has blocking findings
        (p1_dir / "reviews.json").write_text(json.dumps([
            {"reviewer": "bug-reviewer-agent", "verdict": "FINDINGS", "blocking_findings": True},
            {"reviewer": "regression-impact-reviewer-agent", "verdict": "PASS"},
        ]), encoding="utf-8")

        with self.assertRaises(ValidationError) as ctx:
            checkpoint_phase(argparse.Namespace(repo=str(self.tmp), task_id=task_id))
        self.assertIn("blocking findings", str(ctx.exception).lower())

    def test_PHASE42_005_pure_resource_phase_no_tests_or_reviewer_required(self) -> None:
        """PHASE42-005: Pure resource phase, no tests/reviewer required -> tests/review = NOT_REQUIRED; checkpoint may pass."""
        from workflow import draft, record_approval, begin_task, checkpoint_phase
        task_id = "TASK-PHASE-005"
        phases_def = [
            {"id": "p1", "title": "Phase 1 Strings", "expected_files": ["app/src/main/res/values/strings.xml"]},
        ]
        draft(argparse.Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Strings only",
            kind="FEATURE", planning_depth="BOUNDED", expected_surfaces="LOCALIZATION",
            expected_modules=":app", expected_files="app/src/main/res/values/strings.xml",
            test_strategy="NONE", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=json.dumps(phases_def), force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        res_file = self.tmp / "app" / "src" / "main" / "res" / "values" / "strings.xml"
        res_file.parent.mkdir(parents=True, exist_ok=True)
        res_file.write_text("<resources><string name=\"app_name\">Test</string></resources>\n", encoding="utf-8")

        res = checkpoint_phase(argparse.Namespace(repo=str(self.tmp), task_id=task_id))
        self.assertEqual("CHECKPOINT_PASS", res.get("status"))
        self.assertEqual("NOT_REQUIRED", res.get("tests", {}).get("status"))
        self.assertEqual("NOT_REQUIRED", res.get("review", {}).get("status"))

    def test_PHASE42_006_unexpected_compile_exception_fails(self) -> None:
        """PHASE42-006: Unexpected compile exception -> FAIL, never silent PASS."""
        from unittest import mock
        from workflow import draft, record_approval, begin_task, checkpoint_phase
        task_id = "TASK-PHASE-006"
        phases_def = [
            {"id": "p1", "title": "Phase 1 Logic", "expected_files": ["app/src/main/kotlin/com/example/Logic.kt"]},
        ]
        draft(argparse.Namespace(
            repo=str(self.tmp), task_id=task_id, outcome="Phased task",
            kind="FEATURE", planning_depth="BOUNDED", expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app", expected_files="app/src/main/kotlin/com/example/Logic.kt",
            test_strategy="UNIT_ONLY", device_strategy="NONE", risks="", rollback="none", external_write=[],
            architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family="",
            phases=json.dumps(phases_def), force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        logic_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "Logic.kt"
        logic_file.parent.mkdir(parents=True, exist_ok=True)
        logic_file.write_text("package com.example\nclass Logic\n", encoding="utf-8")

        import run_gradle_task
        with mock.patch.object(run_gradle_task, "run_gradle", side_effect=RuntimeError("Gradle crashed with unexpected OOM")):
            with self.assertRaises(ValidationError) as ctx:
                checkpoint_phase(argparse.Namespace(repo=str(self.tmp), task_id=task_id))
            self.assertIn("compile exception", str(ctx.exception).lower())

class ArchitectureV42Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_arch42_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ARCH42_001_low_confidence_family_in_preserve_reflects_low_confidence(self) -> None:
        """ARCH42-001: LOW-confidence matched family in PRESERVE -> contract confidence LOW."""
        from architecture_resolver import resolve_architecture_contract, STATUS_RESOLVED
        from project_context import compute_source_fingerprint
        facts = {
            "schema_version": 2,
            "facts": {
                "architecture": {
                    "families": [
                        {
                            "id": "fam_legacy",
                            "label": "Legacy Views",
                            "confidence": "LOW",
                            "exemplars": ["app/src/main/kotlin/com/example/LegacyFragment.kt"],
                            "dimensions": {"ui_toolkit": "XML_VIEWS", "navigation": "FRAGMENTS"},
                        }
                    ]
                }
            }
        }
        sfp = compute_source_fingerprint(self.tmp)
        facts["source_fingerprint_sha256"] = sfp["source_fingerprint_sha256"]
        facts["source_fingerprint"] = sfp["source_fingerprint"]
        ctx_dir = self.tmp / ".agents" / "project-context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / "project-facts.json").write_text(json.dumps(facts), encoding="utf-8")

        res = resolve_architecture_contract(
            self.tmp,
            architecture_intent="EXISTING_CHANGE",
            target_scope="app/src/main/kotlin/com/example/LegacyFragment.kt",
        )
        self.assertEqual(STATUS_RESOLVED, res.get("status"))
        contract = res.get("contract") or {}
        self.assertEqual("LOW", contract.get("resolution_confidence"))

    def test_ARCH42_002_new_with_surrounding_family_no_target_or_pref_returns_decision_required(self) -> None:
        """ARCH42-002: NEW + surrounding family but no explicit target/preference -> DECISION_REQUIRED."""
        from architecture_resolver import resolve_architecture_contract, STATUS_DECISION_REQUIRED
        from project_context import compute_source_fingerprint
        from architecture_policy import create_architecture_policy, write_architecture_policy
        facts = {
            "schema_version": 2,
            "facts": {
                "architecture": {
                    "families": [
                        {
                            "id": "fam_compose",
                            "label": "Compose MVI",
                            "confidence": "HIGH",
                            "exemplars": ["app/src/main/kotlin/feature/home/HomeScreen.kt"],
                            "dimensions": {"ui_toolkit": "COMPOSE", "navigation": "COMPOSE_DESTINATIONS"},
                        }
                    ]
                }
            }
        }
        sfp = compute_source_fingerprint(self.tmp)
        facts["source_fingerprint_sha256"] = sfp["source_fingerprint_sha256"]
        facts["source_fingerprint"] = sfp["source_fingerprint"]
        ctx_dir = self.tmp / ".agents" / "project-context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / "project-facts.json").write_text(json.dumps(facts), encoding="utf-8")

        pol = create_architecture_policy()
        write_architecture_policy(self.tmp, pol, overwrite=True)

        res = resolve_architecture_contract(
            self.tmp,
            architecture_intent="NEW_SCREEN",
            target_scope="app/src/main/kotlin/feature/home/DetailScreen.kt",
        )
        self.assertEqual(STATUS_DECISION_REQUIRED, res.get("status"))
        self.assertIsNone(res.get("contract"))

    def test_ARCH42_003_new_with_saved_preference_uses_preferred_family(self) -> None:
        """ARCH42-003: NEW + saved preference -> target = preferred."""
        from architecture_resolver import resolve_architecture_contract, STATUS_RESOLVED
        from project_context import compute_source_fingerprint
        from architecture_policy import create_architecture_policy, write_architecture_policy
        facts = {
            "schema_version": 2,
            "facts": {
                "architecture": {
                    "families": [
                        {
                            "id": "fam_compose",
                            "label": "Compose MVI",
                            "confidence": "HIGH",
                            "exemplars": ["app/src/main/kotlin/feature/home/HomeScreen.kt"],
                            "dimensions": {"ui_toolkit": "COMPOSE", "navigation": "COMPOSE_DESTINATIONS"},
                        },
                        {
                            "id": "fam_legacy",
                            "label": "Legacy Views",
                            "confidence": "HIGH",
                            "exemplars": ["app/src/main/kotlin/legacy/OldFragment.kt"],
                            "dimensions": {"ui_toolkit": "XML_VIEWS", "navigation": "FRAGMENTS"},
                        },
                    ]
                }
            }
        }
        sfp = compute_source_fingerprint(self.tmp)
        facts["source_fingerprint_sha256"] = sfp["source_fingerprint_sha256"]
        facts["source_fingerprint"] = sfp["source_fingerprint"]
        ctx_dir = self.tmp / ".agents" / "project-context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / "project-facts.json").write_text(json.dumps(facts), encoding="utf-8")

        pol = create_architecture_policy(preferred_new_code_family="fam_compose")
        write_architecture_policy(self.tmp, pol, overwrite=True)

        res = resolve_architecture_contract(
            self.tmp,
            architecture_intent="NEW_SCREEN",
            target_scope="app/src/main/kotlin/feature/new/NewScreen.kt",
        )
        self.assertEqual(STATUS_RESOLVED, res.get("status"))
        contract = res.get("contract") or {}
        self.assertEqual("fam_compose", contract.get("target_family_id"))

    def test_ARCH42_004_new_with_explicit_target(self) -> None:
        """ARCH42-004: NEW + explicit target -> target = explicit."""
        from architecture_resolver import resolve_architecture_contract, STATUS_RESOLVED
        from project_context import compute_source_fingerprint
        facts = {
            "schema_version": 2,
            "facts": {
                "architecture": {
                    "families": [
                        {
                            "id": "fam_compose",
                            "label": "Compose MVI",
                            "confidence": "HIGH",
                            "exemplars": ["app/src/main/kotlin/feature/home/HomeScreen.kt"],
                            "dimensions": {"ui_toolkit": "COMPOSE", "navigation": "COMPOSE_DESTINATIONS"},
                        },
                        {
                            "id": "fam_legacy",
                            "label": "Legacy Views",
                            "confidence": "HIGH",
                            "exemplars": ["app/src/main/kotlin/legacy/OldFragment.kt"],
                            "dimensions": {"ui_toolkit": "XML_VIEWS", "navigation": "FRAGMENTS"},
                        },
                    ]
                }
            }
        }
        sfp = compute_source_fingerprint(self.tmp)
        facts["source_fingerprint_sha256"] = sfp["source_fingerprint_sha256"]
        facts["source_fingerprint"] = sfp["source_fingerprint"]
        ctx_dir = self.tmp / ".agents" / "project-context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / "project-facts.json").write_text(json.dumps(facts), encoding="utf-8")

        res = resolve_architecture_contract(
            self.tmp,
            architecture_intent="NEW_SCREEN",
            target_scope="app/src/main/kotlin/feature/new/NewScreen.kt",
            target_family_id="fam_legacy",
        )
        self.assertEqual(STATUS_RESOLVED, res.get("status"))
        contract = res.get("contract") or {}
        self.assertEqual("fam_legacy", contract.get("target_family_id"))

    def test_ARCH42_005_legacy_surrounding_family_with_preferred_modern_family(self) -> None:
        """ARCH42-005: Legacy surrounding family + preferred modern family -> target preferred; surrounding family only becomes compatibility boundary."""
        from architecture_resolver import resolve_architecture_contract, STATUS_RESOLVED
        from project_context import compute_source_fingerprint
        from architecture_policy import create_architecture_policy, write_architecture_policy
        facts = {
            "schema_version": 2,
            "facts": {
                "architecture": {
                    "families": [
                        {
                            "id": "fam_compose",
                            "label": "Compose MVI",
                            "confidence": "HIGH",
                            "exemplars": ["app/src/main/kotlin/feature/home/HomeScreen.kt"],
                            "dimensions": {"ui_toolkit": "COMPOSE", "navigation": "COMPOSE_DESTINATIONS"},
                        },
                        {
                            "id": "fam_legacy",
                            "label": "Legacy Views",
                            "confidence": "HIGH",
                            "exemplars": ["app/src/main/kotlin/legacy/OldFragment.kt"],
                            "dimensions": {"ui_toolkit": "XML_VIEWS", "navigation": "FRAGMENTS"},
                        },
                    ]
                }
            }
        }
        sfp = compute_source_fingerprint(self.tmp)
        facts["source_fingerprint_sha256"] = sfp["source_fingerprint_sha256"]
        facts["source_fingerprint"] = sfp["source_fingerprint"]
        ctx_dir = self.tmp / ".agents" / "project-context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / "project-facts.json").write_text(json.dumps(facts), encoding="utf-8")

        pol = create_architecture_policy(preferred_new_code_family="fam_compose")
        write_architecture_policy(self.tmp, pol, overwrite=True)

        res = resolve_architecture_contract(
            self.tmp,
            architecture_intent="NEW_SCREEN",
            target_scope="app/src/main/kotlin/legacy/OldFragment.kt",
        )
        self.assertEqual(STATUS_RESOLVED, res.get("status"))
        contract = res.get("contract") or {}
        self.assertEqual("fam_compose", contract.get("target_family_id"))
        boundaries = contract.get("compatibility_boundaries", [])
        self.assertTrue(len(boundaries) > 0)

class FingerprintV42Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_perf42_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_PERF42_001_modify_same_dirty_kotlin_file_twice_changes_fingerprint(self) -> None:
        """PERF42-001: Modify same dirty Kotlin file twice without commit -> fingerprint changes."""
        from project_context import compute_source_fingerprint
        kt_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "MainActivity.kt"
        kt_file.write_text("package com.example\n// version A\nclass MainActivity\n", encoding="utf-8")
        fp1 = compute_source_fingerprint(self.tmp)

        kt_file.write_text("package com.example\n// version B\nclass MainActivity\n", encoding="utf-8")
        fp2 = compute_source_fingerprint(self.tmp)

        self.assertNotEqual(fp1["source_fingerprint_sha256"], fp2["source_fingerprint_sha256"])

    def test_PERF42_002_markdown_only_change_fingerprint_unchanged(self) -> None:
        """PERF42-002: Markdown-only change -> fingerprint unchanged."""
        from project_context import compute_source_fingerprint
        fp1 = compute_source_fingerprint(self.tmp)

        md_file = self.tmp / "README.md"
        md_file.write_text("# Documentation\nUnrelated markdown change.\n", encoding="utf-8")
        fp2 = compute_source_fingerprint(self.tmp)

        self.assertEqual(fp1["source_fingerprint_sha256"], fp2["source_fingerprint_sha256"])

    def test_PERF42_003_delete_relevant_kotlin_file_changes_fingerprint(self) -> None:
        """PERF42-003: Delete relevant Kotlin file -> fingerprint changes."""
        from project_context import compute_source_fingerprint
        fp1 = compute_source_fingerprint(self.tmp)

        kt_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "MainActivity.kt"
        kt_file.unlink()
        fp2 = compute_source_fingerprint(self.tmp)

        self.assertNotEqual(fp1["source_fingerprint_sha256"], fp2["source_fingerprint_sha256"])

    def test_PERF42_004_repeated_unchanged_status_calls_consistent(self) -> None:
        """PERF42-004: Repeated unchanged status calls must be deterministic and not trigger full re-extraction."""
        from project_context import compute_source_fingerprint, is_context_fresh, extract_project_facts, write_project_context
        facts = extract_project_facts(self.tmp)
        write_project_context(self.tmp, facts)

        self.assertTrue(is_context_fresh(self.tmp))
        fp1 = compute_source_fingerprint(self.tmp)
        fp2 = compute_source_fingerprint(self.tmp)
        self.assertEqual(fp1["source_fingerprint_sha256"], fp2["source_fingerprint_sha256"])

class UpdateRecoveryV42Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_update42_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _setup_interrupted_scenario(self, target_version: str = "1.0.42") -> Path:
        old_dir = self.tmp / ".agents.previous-v41"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "VERSION").write_text("1.0.41\n", encoding="utf-8")
        (old_dir / "marker.txt").write_text("old_engine\n", encoding="utf-8")

        agents_dir = self.tmp / ".agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "VERSION").write_text(f"{target_version}\n", encoding="utf-8")
        (agents_dir / "rules").mkdir(parents=True, exist_ok=True)
        (agents_dir / "rules" / "harness-rules.md").write_text("# Rules\n", encoding="utf-8")
        (agents_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (agents_dir / "scripts" / "_product.py").write_text("APPLICATION_ID = 'test'\n", encoding="utf-8")

        return old_dir

    def test_UPDATE42_001_invalid_ownership_hash_rolls_back(self) -> None:
        """UPDATE42-001: Correct target version + invalid ownership hash -> rollback."""
        from lifecycle import recover_interrupted_update, OWNERSHIP_RELATIVE
        old_dir = self._setup_interrupted_scenario()
        target_version = "1.0.42"

        own = {
            "schema_version": 1,
            "architecture_major": 1,
            "harness_version": target_version,
            "installed_at": utc_now(),
            "ownership_sha256": "tampered-bad-hash",
        }
        setup_dir = self.tmp / ".harness-setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp / OWNERSHIP_RELATIVE).write_text(json.dumps(own), encoding="utf-8")

        journal = {
            "schema_version": 1,
            "status": "IN_PROGRESS",
            "stage": "OWNERSHIP_WRITTEN",
            "from_version": "1.0.41",
            "to_version": target_version,
            "old_agents_path": ".agents.previous-v41",
            "ownership_after_sha256": "tampered-bad-hash",
        }
        (setup_dir / "update-journal.json").write_text(json.dumps(journal), encoding="utf-8")

        res = recover_interrupted_update(self.tmp)
        self.assertIsNotNone(res)
        self.assertEqual("RECOVERED", res.get("status"))
        self.assertEqual("restored_previous_engine", res.get("action"))
        self.assertTrue((self.tmp / ".agents" / "marker.txt").is_file())

    def test_UPDATE42_002_journal_ownership_sha_mismatch_rolls_back(self) -> None:
        """UPDATE42-002: Valid ownership hash + journal ownership SHA mismatch -> rollback."""
        from lifecycle import recover_interrupted_update, OWNERSHIP_RELATIVE
        old_dir = self._setup_interrupted_scenario()
        target_version = "1.0.42"

        own = {
            "schema_version": 1,
            "architecture_major": 1,
            "harness_version": target_version,
            "installed_at": utc_now(),
        }
        own["ownership_sha256"] = canonical_sha256({k: v for k, v in own.items() if k != "ownership_sha256"})
        setup_dir = self.tmp / ".harness-setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp / OWNERSHIP_RELATIVE).write_text(json.dumps(own), encoding="utf-8")

        journal = {
            "schema_version": 1,
            "status": "IN_PROGRESS",
            "stage": "OWNERSHIP_WRITTEN",
            "from_version": "1.0.41",
            "to_version": target_version,
            "old_agents_path": ".agents.previous-v41",
            "ownership_after_sha256": "different-hash-expected-by-journal",
        }
        (setup_dir / "update-journal.json").write_text(json.dumps(journal), encoding="utf-8")

        res = recover_interrupted_update(self.tmp)
        self.assertIsNotNone(res)
        self.assertEqual("RECOVERED", res.get("status"))
        self.assertEqual("restored_previous_engine", res.get("action"))
        self.assertTrue((self.tmp / ".agents" / "marker.txt").is_file())

    def test_UPDATE42_003_fully_valid_ownership_completes_forward(self) -> None:
        """UPDATE42-003: Fully valid ownership + target engine -> forward completion."""
        from lifecycle import recover_interrupted_update, OWNERSHIP_RELATIVE
        old_dir = self._setup_interrupted_scenario()
        target_version = "1.0.42"

        own = {
            "schema_version": 1,
            "architecture_major": 1,
            "harness_version": target_version,
            "installed_at": utc_now(),
        }
        own["ownership_sha256"] = canonical_sha256({k: v for k, v in own.items() if k != "ownership_sha256"})
        setup_dir = self.tmp / ".harness-setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp / OWNERSHIP_RELATIVE).write_text(json.dumps(own), encoding="utf-8")

        journal = {
            "schema_version": 1,
            "status": "IN_PROGRESS",
            "stage": "OWNERSHIP_WRITTEN",
            "from_version": "1.0.41",
            "to_version": target_version,
            "old_agents_path": ".agents.previous-v41",
            "ownership_after_sha256": own["ownership_sha256"],
        }
        (setup_dir / "update-journal.json").write_text(json.dumps(journal), encoding="utf-8")

        res = recover_interrupted_update(self.tmp)
        self.assertIsNotNone(res)
        self.assertEqual("RECOVERED", res.get("status"))
        self.assertEqual("completed_new_engine", res.get("action"))
        self.assertEqual(target_version, (self.tmp / ".agents" / "VERSION").read_text(encoding="utf-8").strip())

    def test_UPDATE42_004_incomplete_agents_dir_rolls_back(self) -> None:
        """UPDATE42-004: Valid ownership but incomplete .agents -> rollback."""
        from lifecycle import recover_interrupted_update, OWNERSHIP_RELATIVE
        old_dir = self._setup_interrupted_scenario()
        target_version = "1.0.42"

        # Missing rules/harness-rules.md
        (self.tmp / ".agents" / "rules" / "harness-rules.md").unlink()

        own = {
            "schema_version": 1,
            "architecture_major": 1,
            "harness_version": target_version,
            "installed_at": utc_now(),
        }
        own["ownership_sha256"] = canonical_sha256({k: v for k, v in own.items() if k != "ownership_sha256"})
        setup_dir = self.tmp / ".harness-setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp / OWNERSHIP_RELATIVE).write_text(json.dumps(own), encoding="utf-8")

        journal = {
            "schema_version": 1,
            "status": "IN_PROGRESS",
            "stage": "OWNERSHIP_WRITTEN",
            "from_version": "1.0.41",
            "to_version": target_version,
            "old_agents_path": ".agents.previous-v41",
            "ownership_after_sha256": own["ownership_sha256"],
        }
        (setup_dir / "update-journal.json").write_text(json.dumps(journal), encoding="utf-8")

        res = recover_interrupted_update(self.tmp)
        self.assertIsNotNone(res)
        self.assertEqual("RECOVERED", res.get("status"))
        self.assertEqual("restored_previous_engine", res.get("action"))
        self.assertTrue((self.tmp / ".agents" / "marker.txt").is_file())

class SetupNeutralityV42Tests(unittest.TestCase):
    def test_SETUP42_001_two_low_families_more_exemplars_neither_recommended(self) -> None:
        """SETUP42-001: Two LOW/MEDIUM families, one with more exemplars -> neither recommended; None recommended."""
        from wizard.questions import questions_payload
        families = [
            {"id": "fam_a", "label": "Fam A", "confidence": "LOW", "exemplars": ["A1.kt", "A2.kt", "A3.kt"]},
            {"id": "fam_b", "label": "Fam B", "confidence": "LOW", "exemplars": ["B1.kt"]},
        ]
        qs = questions_payload(None, "en", facts={"families": families})
        arch_q = next((q for q in qs if q.get("id") == "pref_arch_family"), None)
        self.assertIsNotNone(arch_q)
        opts = arch_q["options"]

        opt_a = next(o for o in opts if o["id"] == "fam_a")
        opt_b = next(o for o in opts if o["id"] == "fam_b")
        opt_none = next(o for o in opts if o["id"] == "none")

        self.assertNotIn("(Recommended)", opt_a["label"])
        self.assertNotIn("(Recommended)", opt_b["label"])
        self.assertIn("(Recommended)", opt_none["label"])

    def test_SETUP42_002_single_high_confidence_family_recommended(self) -> None:
        """SETUP42-002: Exactly one HIGH family -> that family may be recommended."""
        from wizard.questions import questions_payload
        families = [
            {"id": "fam_high", "label": "Fam High", "confidence": "HIGH", "exemplars": ["High.kt"]},
            {"id": "fam_low", "label": "Fam Low", "confidence": "LOW", "exemplars": ["Low.kt"]},
        ]
        qs = questions_payload(None, "en", facts={"families": families})
        arch_q = next((q for q in qs if q.get("id") == "pref_arch_family"), None)
        self.assertIsNotNone(arch_q)
        opts = arch_q["options"]

        opt_high = next(o for o in opts if o["id"] == "fam_high")
        opt_none = next(o for o in opts if o["id"] == "none")

        self.assertIn("(Recommended)", opt_high["label"])
        self.assertNotIn("(Recommended)", opt_none["label"])

    def test_SETUP42_003_two_high_confidence_families_none_recommended(self) -> None:
        """SETUP42-003: Two HIGH families -> no family recommended; None recommended."""
        from wizard.questions import questions_payload
        families = [
            {"id": "fam_high1", "label": "Fam High 1", "confidence": "HIGH", "exemplars": ["H1.kt"]},
            {"id": "fam_high2", "label": "Fam High 2", "confidence": "HIGH", "exemplars": ["H2.kt"]},
        ]
        qs = questions_payload(None, "en", facts={"families": families})
        arch_q = next((q for q in qs if q.get("id") == "pref_arch_family"), None)
        self.assertIsNotNone(arch_q)
        opts = arch_q["options"]

        opt_h1 = next(o for o in opts if o["id"] == "fam_high1")
        opt_h2 = next(o for o in opts if o["id"] == "fam_high2")
        opt_none = next(o for o in opts if o["id"] == "none")

        self.assertNotIn("(Recommended)", opt_h1["label"])
        self.assertNotIn("(Recommended)", opt_h2["label"])
        self.assertIn("(Recommended)", opt_none["label"])

    def test_SETUP42_004_saved_preference_shows_current_default_no_competing_recommendation(self) -> None:
        """SETUP42-004: Saved preference -> Current default; no competing auto recommendation."""
        from wizard.questions import questions_payload
        families = [
            {"id": "fam_saved", "label": "Fam Saved", "confidence": "HIGH", "exemplars": ["S.kt"]},
            {"id": "fam_other", "label": "Fam Other", "confidence": "HIGH", "exemplars": ["O.kt"]},
        ]
        facts = {"families": families, "preferred_new_code_family": "fam_saved"}
        qs = questions_payload(None, "en", facts=facts)
        arch_q = next((q for q in qs if q.get("id") == "pref_arch_family"), None)
        self.assertIsNotNone(arch_q)
        opts = arch_q["options"]

        opt_saved = next(o for o in opts if o["id"] == "fam_saved")
        opt_other = next(o for o in opts if o["id"] == "fam_other")
        opt_none = next(o for o in opts if o["id"] == "none")

        self.assertIn("(Current default)", opt_saved["label"])
        self.assertNotIn("(Recommended)", opt_saved["label"])
        self.assertNotIn("(Recommended)", opt_other["label"])
        self.assertNotIn("(Recommended)", opt_none["label"])


class PreflightScopeV42Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="test_preflight42_")).resolve()
        _setup_mock_repo(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_PREFLIGHT42_001_unrelated_dirty_room_does_not_block_compose_task(self) -> None:
        """PREFLIGHT42-001: Pre-existing unrelated dirty Room migration + current Compose task -> Room does not block task."""
        # Pre-existing broken Room file exists outside task scope (before task begins)
        room_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "BrokenDatabase.kt"
        room_file.write_text(
            "package com.example\n"
            "@Database(entities = [User::class], version = 2)\n"
            "abstract class BrokenDatabase : RoomDatabase() {\n"
            "    fun build(ctx: Context) = Room.databaseBuilder(ctx, BrokenDatabase::class.java, \"db\").fallbackToDestructiveMigration().build()\n"
            "}\n"
            "data class User(val id: Int)\n",
            encoding="utf-8",
        )

        task_id = "TASK-PRE-001"
        draft(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            outcome="Compose Screen",
            kind="FEATURE",
            expected_surfaces="COMPOSE_UI",
            expected_modules=":app",
            expected_files="app/src/main/kotlin/com/example/MyScreen.kt",
            test_strategy="none",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        # Task file modified inside task scope
        screen_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "MyScreen.kt"
        screen_file.write_text("package com.example\n// Compose Screen\nclass MyScreen\n", encoding="utf-8")

        from workflow import load_task_baseline, build_task_manifest
        from change_classifier import classify
        from room_guard import check_room_working_tree

        base = load_task_baseline(self.tmp, task_id)
        manifest = build_task_manifest(self.tmp, base)
        task_changes = manifest.get("task_changes", [])
        task_paths = [tc["path"] if isinstance(tc, dict) else str(tc) for tc in task_changes]

        self.assertIn("app/src/main/kotlin/com/example/MyScreen.kt", task_paths)
        self.assertNotIn("app/src/main/kotlin/com/example/BrokenDatabase.kt", task_paths)

        # Room check scoped to task paths passes because task paths do not touch Room
        db_ok, db_msg = check_room_working_tree(paths=task_paths, repo=self.tmp)
        self.assertTrue(db_ok)

    def test_PREFLIGHT42_002_current_task_modifying_room_triggers_room_guard(self) -> None:
        """PREFLIGHT42-002: Current task modifies Room Entity/DAO/schema -> Room guard runs."""
        # Setup initial Room database in HEAD
        db_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "AppDatabase.kt"
        db_file.write_text(
            "package com.example\n"
            "@Database(entities = [User::class], version = 1)\n"
            "abstract class AppDatabase : RoomDatabase()\n"
            "data class User(val id: Int)\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=self.tmp, check=True)
        subprocess.run(["git", "commit", "-m", "add db v1", "-q"], cwd=self.tmp, check=True)

        task_id = "TASK-PRE-002"
        draft(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            outcome="Room Schema Migration",
            kind="FEATURE",
            expected_surfaces="ROOM_SCHEMA",
            expected_modules=":app",
            expected_files="app/src/main/kotlin/com/example/AppDatabase.kt",
            test_strategy="none",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        # Task introduces destructive migration
        db_file.write_text(
            "package com.example\n"
            "@Database(entities = [User::class], version = 2)\n"
            "abstract class AppDatabase : RoomDatabase() {\n"
            "    fun build(ctx: Context) = Room.databaseBuilder(ctx, AppDatabase::class.java, \"db\").fallbackToDestructiveMigration().build()\n"
            "}\n"
            "data class User(val id: Int)\n",
            encoding="utf-8",
        )

        from workflow import load_task_baseline, build_task_manifest
        from room_guard import check_room_working_tree

        base = load_task_baseline(self.tmp, task_id)
        manifest = build_task_manifest(self.tmp, base)
        task_changes = manifest.get("task_changes", [])
        task_paths = [tc["path"] if isinstance(tc, dict) else str(tc) for tc in task_changes]

        db_ok, db_msg = check_room_working_tree(paths=task_paths, repo=self.tmp)
        self.assertFalse(db_ok)
        self.assertIn("fallbackToDestructiveMigration", db_msg)

    def test_PREFLIGHT42_003_legacy_task_without_baseline_runs_working_tree_fallback(self) -> None:
        """PREFLIGHT42-003: Legacy task without baseline -> legacy working tree fallback retained."""
        from room_guard import check_room_working_tree
        # Setup initial Room database in HEAD
        db_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "AppDatabase.kt"
        db_file.write_text(
            "package com.example\n"
            "@Database(entities = [User::class], version = 1)\n"
            "abstract class AppDatabase : RoomDatabase()\n"
            "data class User(val id: Int)\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=self.tmp, check=True)
        subprocess.run(["git", "commit", "-m", "add db v1", "-q"], cwd=self.tmp, check=True)

        # Modify to destructive migration
        db_file.write_text(
            "package com.example\n"
            "@Database(entities = [User::class], version = 2)\n"
            "abstract class AppDatabase : RoomDatabase() {\n"
            "    fun build(ctx: Context) = Room.databaseBuilder(ctx, AppDatabase::class.java, \"db\").fallbackToDestructiveMigration().build()\n"
            "}\n"
            "data class User(val id: Int)\n",
            encoding="utf-8",
        )
        db_ok, db_msg = check_room_working_tree(paths=None, repo=self.tmp)
        self.assertFalse(db_ok)
        self.assertIn("fallbackToDestructiveMigration", db_msg)

    def test_PREFLIGHT42_004_unrelated_dirty_business_logic_does_not_elevate_resource_task(self) -> None:
        """PREFLIGHT42-004: Unrelated dirty BUSINESS_LOGIC + current RESOURCE_UI task -> classification reflects RESOURCE_UI."""
        # Pre-existing unrelated dirty business logic before task begins
        biz_file = self.tmp / "app" / "src" / "main" / "kotlin" / "com" / "example" / "PaymentLogic.kt"
        biz_file.write_text("package com.example\nclass PaymentLogic { fun pay() = true }\n", encoding="utf-8")

        task_id = "TASK-PRE-004"
        draft(argparse.Namespace(
            repo=str(self.tmp),
            task_id=task_id,
            outcome="Update String",
            kind="FEATURE",
            expected_surfaces="RESOURCE_UI",
            expected_modules=":app",
            expected_files="app/src/main/res/values/strings.xml",
            test_strategy="none",
            device_strategy="none",
            risks="",
            rollback="",
            external_write=[],
            force=True,
        ))
        record_approval(argparse.Namespace(repo=str(self.tmp), task_id=task_id, source="conversation", proof_reference="ok", enforcement_tier="RULE_ENFORCED"))
        begin_task(argparse.Namespace(repo=str(self.tmp), task_id=task_id))

        # Current task modifies strings.xml
        res_file = self.tmp / "app" / "src" / "main" / "res" / "values" / "strings.xml"
        res_file.parent.mkdir(parents=True, exist_ok=True)
        res_file.write_text("<resources><string name=\"test\">Val</string></resources>\n", encoding="utf-8")

        from workflow import load_task_baseline, build_task_manifest
        from change_classifier import classify

        base = load_task_baseline(self.tmp, task_id)
        manifest = build_task_manifest(self.tmp, base)
        task_changes = manifest.get("task_changes", [])

        classification = classify(self.tmp, task_changes=task_changes)
        surfaces = classification.get("surfaces", [])
        self.assertIn("RESOURCE_UI", surfaces)
        self.assertNotIn("BUSINESS_LOGIC", surfaces)


if __name__ == "__main__":
    unittest.main(verbosity=2)

