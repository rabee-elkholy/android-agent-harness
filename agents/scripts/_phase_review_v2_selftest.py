"""Selftest suite for Scoped Phase Delta Review V2.

Covers:
- Section 25 Test Matrix (PHASE_V2_001 through PHASE_V2_017)
- Section 26 STALE_PHASE_001
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _vnext_common import (
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    read_json,
    utc_now,
)
from delivery_manifest import load_task_baseline
from plan_authority import save_plan
import workflow
from workflow import (
    begin_task,
    checkpoint_phase,
    draft,
    record_approval,
    resolve_next_action,
    state_root,
    task_dir,
)

try:
    import phase_review
    from phase_review import (
        PHASE_IMPLEMENTING,
        PHASE_CHECKS_PASSED,
        PHASE_REVIEW_PACKAGE_REQUIRED,
        PHASE_REVIEWING,
        PHASE_REVIEW_BLOCKED,
        PHASE_COMPLETE,
        REVIEW_NOT_DISPATCHED,
        REVIEW_DISPATCHED,
        REVIEW_COMPLETED,
        REVIEW_ENV_BLOCKED,
        REVIEW_PROTOCOL_RETRY_REQUIRED,
        REVIEW_FAILED_PROTOCOL,
        is_phase_review_needed,
        build_phase_package,
        complete_phase_review,
        finalize_phase_review,
        format_phase_provenance_section,
        load_phase_ledger,
        phase_run_file,
        phase_review_dir,
        record_phase_dispatch_batch,
        compute_phase_diff_stats,
    )
except ImportError:
    phase_review = None


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


def setup_ownership(repo: Path) -> None:
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
    atomic_write_json(repo / ".agents" / "ownership.json", manifest)
    write_file(repo / ".harness-setup" / "answers.json", json.dumps({"confirm_installation": True, "target_branch": "main"}))


class PhaseReviewV2Selftest(unittest.TestCase):
    def setUp(self) -> None:
        if phase_review is None:
            self.fail("phase_review module not yet implemented")
        self.temp = tempfile.TemporaryDirectory(prefix="phase_v2_test_")
        self.repo = Path(self.temp.name).resolve()
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Phase Test")
        run_git(self.repo, "config", "user.email", "phase@example.invalid")
        run_git(self.repo, "config", "core.autocrlf", "true")

        setup_ownership(self.repo)
        write_file(self.repo / "settings.gradle.kts", "rootProject.name = 'sample'\ninclude(':app')\n")
        write_file(self.repo / "app" / "build.gradle.kts", "plugins { kotlin('jvm') }\n")
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "App.kt", "package com.example\nclass App\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "chore: baseline commit", "-q")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_phased_task(self, phases: list[dict], kind: str = "FEATURE", scoped_phase_review: bool | None = None, expected_modules: str | None = None) -> str:
        import uuid
        task_id = f"phase-{uuid.uuid4().hex[:6]}"
        draft_args = argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            prompt="Phased feature implementation",
            outcome="Implement phased feature",
            kind=kind,
            phases=phases,
            scoped_phase_review_enabled=scoped_phase_review,
            expected_modules=expected_modules,
        )
        task_id = draft(draft_args)["task_id"]

        record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            source="conversation",
            proof_reference="approve phased task",
            enforcement_tier="RULE_ENFORCED",
        ))
        return task_id

    def _pass_phase_tests(self, task_id: str, phase_id: str) -> None:
        p_dir = task_dir(self.repo, task_id) / "phases" / phase_id
        p_dir.mkdir(parents=True, exist_ok=True)
        write_file(p_dir / "unit_tests.json", json.dumps({"status": "PASS"}))

    def test_PHASE_V2_001_small_routine_phase_deterministic_checkpoint_only(self) -> None:
        """PHASE_V2_001: small/routine phase uses deterministic checkpoint only."""
        phases = [
            {"id": "p1", "name": "Phase 1 - Minor UI text", "description": "Update minor button text", "expected_files": ["app/src/main/res/values/strings.xml"]},
            {"id": "p2", "name": "Phase 2 - Minor UI styling", "description": "Update minor style", "expected_files": ["app/src/main/res/values/styles.xml"]},
        ]
        task_id = self._create_phased_task(phases, kind="FEATURE")
        write_file(self.repo / "app" / "src" / "main" / "res" / "values" / "strings.xml", "<resources><string name='hello'>Hello</string></resources>")

        res = checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        self.assertEqual("CHECKPOINT_PASS", res["status"])
        self.assertEqual("NOT_REQUIRED", res["review"]["status"])
        pstate = read_json(task_dir(self.repo, task_id) / "phase-state.json")
        self.assertIn("p1", pstate.get("completed_phases", []))

    def test_PHASE_V2_002_large_task_phase_selects_narrow_reviewer_roster(self) -> None:
        """PHASE_V2_002: large task phase selects narrow reviewer roster (1-2 reviewers max)."""
        phases = [
            {"id": "p1", "name": "Auth Storage Phase", "description": "Implement TokenStorage with cryptographic tokens", "expected_files": ["app/src/main/java/com/example/AuthTokenManager.kt"]},
            {"id": "p2", "name": "UI Phase", "description": "Implement Login Screen", "expected_files": ["app/src/main/java/com/example/LoginScreen.kt"]},
        ]
        task_id = self._create_phased_task(phases, kind="FEATURE", scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "AuthTokenManager.kt", "package com.example\nclass AuthTokenManager {\n  fun saveToken(token: String) {}\n}\n")

        plan = read_json(task_dir(self.repo, task_id) / "plan.json")
        policy = {"surfaces": ["AUTH", "SECURITY"], "reviewers": ["bug-reviewer-agent", "security-reviewer-agent", "convention-reviewer-agent", "regression-impact-reviewer-agent"]}
        needed, reviewers = is_phase_review_needed(self.repo, task_id, plan, phases[0], [{"path": "app/src/main/java/com/example/AuthTokenManager.kt"}], policy)
        self.assertTrue(needed)
        self.assertLessEqual(len(reviewers), 2)
        self.assertIn("security-reviewer-agent", reviewers)
        self.assertNotIn("convention-reviewer-agent", reviewers)

    def test_PHASE_V2_003_phase_package_contains_only_phase_delta_plus_bounded_context(self) -> None:
        """PHASE_V2_003: phase package contains only phase delta plus bounded context."""
        phases = [
            {"id": "p1", "name": "Auth Phase", "description": "Implement TokenStorage", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "UI Phase", "description": "Implement UI", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))

        pkg_path, meta = build_phase_package(self.repo, task_id, "p1")
        self.assertTrue(pkg_path.is_file())
        content = pkg_path.read_text(encoding="utf-8")
        self.assertIn("Auth.kt", content)
        self.assertNotIn("UI.kt", content)

    def test_PHASE_V2_004_phase_package_identity_immutable(self) -> None:
        """PHASE_V2_004: phase package identity immutable."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))

        pkg_path, meta = build_phase_package(self.repo, task_id, "p1")
        self.assertIn("package_sha256", meta)
        # Attempting to rebuild while package exists raises ValidationError
        with self.assertRaises(ValidationError):
            build_phase_package(self.repo, task_id, "p1")

    def test_PHASE_V2_005_phase_reviewer_exact_binding_enforced(self) -> None:
        """PHASE_V2_005: phase reviewer exact Role/TypeName/Prompt enforced."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        build_phase_package(self.repo, task_id, "p1")

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("DISPATCH_PHASE_REVIEWERS", act["code"])
        self.assertIn("briefs", act)
        for rev in act["reviewers"]:
            self.assertIn(rev, act["briefs"])

    def test_PHASE_V2_006_same_model_omission_preserved(self) -> None:
        """PHASE_V2_006: same-model omission preserved (no model or Model passed)."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        build_phase_package(self.repo, task_id, "p1")

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("DISPATCH_PHASE_REVIEWERS", act["code"])
        exec_profile = act.get("review_execution_profile") or {}
        self.assertNotIn("model", exec_profile)
        self.assertNotIn("Model", exec_profile)
        self.assertNotIn("required_model", exec_profile)

    def test_PHASE_V2_007_phase_pass_advances_phase(self) -> None:
        """PHASE_V2_007: phase PASS advances phase."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        pkg_path, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])

        # Mock reviewer completion with PASS
        for rev in meta["selected_reviewers"]:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=rev,
                execution_id="conv-123",
                verdict="PASS",
                findings=[],
                package_sha256=meta["package_sha256"],
            )
        fin = finalize_phase_review(self.repo, task_id, "p1")
        self.assertEqual("PASS", fin["verdict"])

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("BEGIN_NEXT_PHASE", act["code"])
        self.assertEqual("p1", read_json(task_dir(self.repo, task_id) / "phase-state.json")["current_phase_id"])
        self.assertFalse((task_dir(self.repo, task_id) / "phases" / "p2" / "baseline.json").exists())
        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        self.assertEqual("p2", read_json(task_dir(self.repo, task_id) / "phase-state.json")["current_phase_id"])
        self.assertTrue((task_dir(self.repo, task_id) / "phases" / "p2" / "baseline.json").is_file())

    def test_PHASE_V2_008_phase_findings_keep_same_phase_active(self) -> None:
        """PHASE_V2_008: phase findings keep same phase active."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        pkg_path, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])

        for rev in meta["selected_reviewers"]:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=rev,
                execution_id=f"conv-{rev}",
                verdict="FINDINGS" if rev == meta["selected_reviewers"][0] else "PASS",
                findings=[{"id": "AUTH-01", "severity": "HIGH", "message": "Insecure key"}] if rev == meta["selected_reviewers"][0] else [],
                package_sha256=meta["package_sha256"],
            )
        fin = finalize_phase_review(self.repo, task_id, "p1")
        self.assertEqual("FINDINGS", fin["verdict"])

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("FIX_PHASE_FINDINGS", act["code"])

    def test_PHASE_V2_009_fixing_findings_invalidates_old_phase_review_run_only(self) -> None:
        """PHASE_V2_009: fixing findings invalidates old phase review run only."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        pkg_path, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])

        for rev in meta["selected_reviewers"]:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=rev,
                execution_id=f"conv-{rev}",
                verdict="FINDINGS" if rev == meta["selected_reviewers"][0] else "PASS",
                findings=[{"id": "AUTH-01", "severity": "HIGH", "message": "Insecure key"}] if rev == meta["selected_reviewers"][0] else [],
                package_sha256=meta["package_sha256"],
            )
        finalize_phase_review(self.repo, task_id, "p1")

        # Now fix the file and re-checkpoint
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass AuthFixed\n")
        self._pass_phase_tests(task_id, "p1")
        res = checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        self.assertEqual("CHECKPOINT_PASS", res["status"])

        # Check that old phase review run was invalidated
        pdir = task_dir(self.repo, task_id) / "phases" / "p1" / "review"
        self.assertFalse((pdir / "current-phase-run.json").exists())

    def test_PHASE_V2_010_no_new_developer_approval_on_in_scope_phase_fix(self) -> None:
        """PHASE_V2_010: no new developer approval on in-scope phase fix."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])
        for rev in meta["selected_reviewers"]:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=rev,
                execution_id=f"conv-{rev}",
                verdict="FINDINGS" if rev == meta["selected_reviewers"][0] else "PASS",
                findings=[{"id": "AUTH-01", "severity": "HIGH", "message": "Insecure key"}] if rev == meta["selected_reviewers"][0] else [],
                package_sha256=meta["package_sha256"],
            )
        finalize_phase_review(self.repo, task_id, "p1")

        # Plan status stays IMPLEMENTING
        plan = read_json(task_dir(self.repo, task_id) / "plan.json")
        self.assertEqual("IMPLEMENTING", plan["status"])

    def test_PHASE_V2_011_material_scope_drift_still_requires_plan_revision(self) -> None:
        """PHASE_V2_011: material scope drift still requires plan revision/approval."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        # Touch unexpected file outside scope
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "SecretUnauthorized.kt", "class SecretUnauthorized")
        with self.assertRaises(ValidationError) as ctx:
            checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        self.assertIn("modified file outside expected_files", str(ctx.exception))

    def test_PHASE_V2_012_phase_calls_count_toward_global_safety_cap(self) -> None:
        """PHASE_V2_012: phase calls count toward global safety cap."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        plan_f = task_dir(self.repo, task_id) / "plan.json"
        plan = read_json(plan_f)
        # Set max calls = 3, calls used = 2. With 1 phase reviewer and reserved final min = 2, total = 2+1+2 = 5 > 3
        plan["review_calls_used"] = 2
        plan["max_review_calls"] = 3
        save_plan(plan_f, plan)

        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        build_phase_package(self.repo, task_id, "p1")

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("REVIEWER_CALL_SAFETY_CAP_REACHED", act["code"])

    def test_PHASE_V2_013_protocol_retry_no_new_call(self) -> None:
        """PHASE_V2_013: protocol retry on a generic host does not increment review_calls_used."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])

        rev = meta["selected_reviewers"][0]
        # Simulate invalid review format requiring protocol retry
        res = complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=rev,
            execution_id="conv-123",
            raw_response="not json",
            package_sha256=meta["package_sha256"],
        )
        self.assertEqual("PROTOCOL_RETRY_REQUIRED", res["status"])

        plan = read_json(task_dir(self.repo, task_id) / "plan.json")
        used_calls = plan.get("review_calls_used", 0)

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("RETRY_PHASE_REVIEW_RESPONSE", act["code"])
        self.assertIn("phase-review complete", act.get("command", ""))

        plan_after = read_json(task_dir(self.repo, task_id) / "plan.json")
        self.assertEqual(used_calls, plan_after.get("review_calls_used", 0))

    def test_PHASE_V2_014_final_integration_review_still_runs(self) -> None:
        """PHASE_V2_014: final integration review still runs after all phases pass."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])
        for rev in meta["selected_reviewers"]:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=rev,
                execution_id="conv-123",
                verdict="PASS",
                findings=[],
                package_sha256=meta["package_sha256"],
            )
        finalize_phase_review(self.repo, task_id, "p1")

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("BEGIN_NEXT_PHASE", act["code"])

        from workflow import begin_next_phase
        begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "UI.kt", "package com.example\nclass UI\n")
        self._pass_phase_tests(task_id, "p2")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p2"))

        act2 = resolve_next_action(self.repo, task_id)
        if act2["code"] == "BUILD_PHASE_REVIEW_PACKAGE":
            _, meta2 = build_phase_package(self.repo, task_id, "p2")
            record_phase_dispatch_batch(self.repo, task_id, "p2", meta2["selected_reviewers"])
            for rev in meta2["selected_reviewers"]:
                complete_phase_review(
                    repo=self.repo,
                    task_id=task_id,
                    phase_id="p2",
                    reviewer=rev,
                    execution_id="conv-p2",
                    verdict="PASS",
                    findings=[],
                    package_sha256=meta2["package_sha256"],
                )
            finalize_phase_review(self.repo, task_id, "p2")
            act2 = resolve_next_action(self.repo, task_id)
        self.assertEqual("PREPARE_VERIFICATION", act2["code"])

    def test_PHASE_V2_015_final_package_contains_phase_provenance_hashes(self) -> None:
        """PHASE_V2_015: final package contains phase provenance hashes."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])
        for rev in meta["selected_reviewers"]:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=rev,
                execution_id="conv-123",
                verdict="PASS",
                findings=[],
                package_sha256=meta["package_sha256"],
            )
        finalize_phase_review(self.repo, task_id, "p1")

        provenance_md = format_phase_provenance_section(self.repo, task_id)
        self.assertIn("PHASE REVIEW PROVENANCE", provenance_md)
        self.assertIn("p1", provenance_md)
        self.assertIn(meta["package_sha256"][:12], provenance_md)

    def test_PHASE_V2_016_old_reviews_json_phase_evidence_cannot_satisfy_new_phase_gate(self) -> None:
        """PHASE_V2_016: old reviews.json phase evidence cannot satisfy new phase V2 gate."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        # Place legacy reviews.json in phase dir
        p1_dir = task_dir(self.repo, task_id) / "phases" / "p1"
        write_file(p1_dir / "reviews.json", json.dumps({"status": "PASS", "reviews": []}))

        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        pstate = read_json(task_dir(self.repo, task_id) / "phase-state.json")
        # Legacy reviews.json did NOT mark phase complete in V2
        self.assertNotIn("p1", pstate.get("completed_phases", []))

    def test_PHASE_V2_017_no_legacy_phase_review_function_remains_authoritative(self) -> None:
        """PHASE_V2_017: check_phase_reviews does not exist in workflow module."""
        self.assertFalse(hasattr(workflow, "check_phase_reviews"))

    def test_STALE_PHASE_001_phase_baseline_change_while_phase_reviewer_running_blocks_ingestion(self) -> None:
        """STALE_PHASE_001: phase baseline change while phase reviewer running blocks ingestion."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")

        # Mutate the file while reviewer was running
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass AuthModified\n")

        rev = meta["selected_reviewers"][0]
        with self.assertRaises(ValidationError) as ctx:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=rev,
                execution_id="conv-123",
                verdict="PASS",
                findings=[],
                package_sha256=meta["package_sha256"],
            )
        self.assertIn("stale", str(ctx.exception).lower())

    def test_STALE_PHASE_002_deleted_path_recreated_during_review(self) -> None:
        old_file = self.repo / "app" / "src" / "main" / "res" / "values" / "obsolete.xml"
        write_file(old_file, "<resources><string name='old'>Old</string></resources>\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "add obsolete resource", "-q")
        phases = [
            {"id": "p1", "name": "Remove obsolete resource", "expected_files": ["app/src/main/res/values/obsolete.xml"]},
            {"id": "p2", "name": "Update UI", "expected_files": ["app/src/main/res/values/new.xml"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        old_file.unlink()
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])
        write_file(old_file, "<resources><string name='old'>Returned</string></resources>\n")
        with self.assertRaisesRegex(ValidationError, "PHASE_REVIEW_STALE"):
            complete_phase_review(
                repo=self.repo, task_id=task_id, phase_id="p1",
                reviewer=meta["selected_reviewers"][0], execution_id="conv-stale-deletion",
                verdict="PASS", findings=[], package_sha256=meta["package_sha256"],
            )

    def test_STALE_PHASE_003_renamed_source_recreated_during_review(self) -> None:
        old_file = self.repo / "app" / "src" / "main" / "res" / "values" / "old.xml"
        new_file = old_file.with_name("new.xml")
        write_file(old_file, "<resources><string name='old'>Old</string></resources>\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "add old resource", "-q")
        phases = [
            {"id": "p1", "name": "Rename resource", "expected_files": ["app/src/main/res/values/old.xml", "app/src/main/res/values/new.xml"]},
            {"id": "p2", "name": "Update UI", "expected_files": ["app/src/main/res/values/ui.xml"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        old_file.rename(new_file)
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])
        write_file(old_file, "<resources><string name='old'>Returned</string></resources>\n")
        with self.assertRaisesRegex(ValidationError, "PHASE_REVIEW_STALE"):
            complete_phase_review(
                repo=self.repo, task_id=task_id, phase_id="p1",
                reviewer=meta["selected_reviewers"][0], execution_id="conv-stale-rename",
                verdict="PASS", findings=[], package_sha256=meta["package_sha256"],
            )

    def test_PHASE_STATE_001_review_required_checkpoint_persists_review_package_required(self) -> None:
        """PHASE_STATE_001: review-required checkpoint persists REVIEW_PACKAGE_REQUIRED."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        res = checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        self.assertEqual("CHECKPOINT_PASS", res["status"])
        self.assertEqual("REVIEW_PACKAGE_REQUIRED", res["review"]["status"])

        pstate = read_json(task_dir(self.repo, task_id) / "phase-state.json")
        self.assertNotIn("p1", pstate.get("completed_phases", []))
        self.assertEqual(PHASE_REVIEW_PACKAGE_REQUIRED, phase_review.get_phase_substate(pstate, "p1"))
        self.assertEqual(PHASE_REVIEW_PACKAGE_REQUIRED, pstate.get("phase_substates", {}).get("p1", {}).get("substate"))

    def test_PHASE_STATE_002_immediately_after_checkpoint_status_next_is_build_phase_package(self) -> None:
        """PHASE_STATE_002: immediately after checkpoint, status --next == BUILD_PHASE_REVIEW_PACKAGE without any direct Python mutation."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("BUILD_PHASE_REVIEW_PACKAGE", act["code"])
        self.assertEqual("HARNESS_COMMAND", act["kind"])
        self.assertIn("phase-review package", act["command"])

    def test_PHASE_STATE_003_deterministic_only_checkpoint_remains_complete(self) -> None:
        """PHASE_STATE_003: deterministic-only checkpoint remains COMPLETE."""
        phases = [
            {"id": "p1", "name": "Phase 1 - Minor UI text", "description": "Update minor button text", "expected_files": ["app/src/main/res/values/strings.xml"]},
            {"id": "p2", "name": "Phase 2 - Minor UI styling", "description": "Update minor style", "expected_files": ["app/src/main/res/values/styles.xml"]},
        ]
        task_id = self._create_phased_task(phases, kind="FEATURE")
        write_file(self.repo / "app" / "src" / "main" / "res" / "values" / "strings.xml", "<resources><string name='hello'>Hello</string></resources>")
        res = checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        self.assertEqual("CHECKPOINT_PASS", res["status"])

        pstate = read_json(task_dir(self.repo, task_id) / "phase-state.json")
        self.assertIn("p1", pstate.get("completed_phases", []))
        self.assertEqual(PHASE_COMPLETE, phase_review.get_phase_substate(pstate, "p1"))
        self.assertEqual("p1", pstate["current_phase_id"])
        self.assertIn("p1", pstate["phase_checkpoints"])
        self.assertIn("updated_at", pstate["phase_substates"]["p1"])
        self.assertFalse((task_dir(self.repo, task_id) / "phases" / "p2" / "baseline.json").exists())
        self.assertEqual(0, read_json(task_dir(self.repo, task_id) / "plan.json").get("active_phase_index", 0))

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("BEGIN_NEXT_PHASE", act["code"])

        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        advanced = read_json(task_dir(self.repo, task_id) / "phase-state.json")
        self.assertEqual("p2", advanced["current_phase_id"])
        self.assertEqual(PHASE_IMPLEMENTING, phase_review.get_phase_substate(advanced, "p2"))
        self.assertTrue((task_dir(self.repo, task_id) / "phases" / "p2" / "baseline.json").is_file())
        self.assertEqual(1, read_json(task_dir(self.repo, task_id) / "plan.json")["active_phase_index"])

    def test_PHASE_TRANSITION_005_plan_commit_is_last_and_retryable(self) -> None:
        phases = [
            {"id": "p1", "name": "Text", "expected_files": ["app/src/main/res/values/one.xml"]},
            {"id": "p2", "name": "Style", "expected_files": ["app/src/main/res/values/two.xml"]},
        ]
        task_id = self._create_phased_task(phases)
        write_file(self.repo / "app/src/main/res/values/one.xml", "<resources/>\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        directory = task_dir(self.repo, task_id)
        baseline_file = directory / "phases" / "p2" / "baseline.json"
        plan_file = directory / "plan.json"
        state_file = directory / "phase-state.json"

        def interrupt_before_plan_commit(path: Path, plan: dict) -> None:
            self.assertEqual(plan_file, path)
            self.assertTrue(baseline_file.is_file())
            self.assertEqual("p2", read_json(state_file)["current_phase_id"])
            self.assertEqual(0, read_json(plan_file).get("active_phase_index", 0))
            raise OSError("simulated interruption before plan commit")

        with mock.patch.object(workflow, "save_plan", side_effect=interrupt_before_plan_commit):
            with self.assertRaisesRegex(OSError, "simulated interruption"):
                workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        baseline_sha = read_json(baseline_file)["baseline_sha256"]
        self.assertEqual("BEGIN_NEXT_PHASE", resolve_next_action(self.repo, task_id)["code"])
        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        self.assertEqual(baseline_sha, read_json(baseline_file)["baseline_sha256"])
        self.assertEqual(1, read_json(plan_file)["active_phase_index"])
        self.assertEqual("p2", read_json(state_file)["current_phase_id"])

    def test_PHASE_TRANSITION_006_state_write_failure_keeps_plan_on_old_phase(self) -> None:
        phases = [
            {"id": "p1", "name": "Text", "expected_files": ["app/src/main/res/values/one.xml"]},
            {"id": "p2", "name": "Style", "expected_files": ["app/src/main/res/values/two.xml"]},
        ]
        task_id = self._create_phased_task(phases)
        write_file(self.repo / "app/src/main/res/values/one.xml", "<resources/>\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        directory = task_dir(self.repo, task_id)
        plan_file = directory / "plan.json"
        state_file = directory / "phase-state.json"
        original_write = workflow.atomic_write_json

        def interrupt_state_write(path: Path, payload: dict) -> None:
            if path == state_file:
                raise OSError("simulated state write failure")
            original_write(path, payload)

        with mock.patch.object(workflow, "atomic_write_json", side_effect=interrupt_state_write):
            with self.assertRaisesRegex(OSError, "simulated state write failure"):
                workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        self.assertEqual(0, read_json(plan_file).get("active_phase_index", 0))
        self.assertEqual("BEGIN_NEXT_PHASE", resolve_next_action(self.repo, task_id)["code"])
        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        self.assertEqual(1, read_json(plan_file)["active_phase_index"])
        self.assertEqual("p2", read_json(state_file)["current_phase_id"])

    def test_PHASE_TRANSITION_007_stale_checkpoint_cannot_become_next_baseline(self) -> None:
        phases = [
            {"id": "p1", "name": "Text", "expected_files": ["app/src/main/res/values/one.xml"]},
            {"id": "p2", "name": "Style", "expected_files": ["app/src/main/res/values/two.xml"]},
        ]
        task_id = self._create_phased_task(phases)
        source = self.repo / "app/src/main/res/values/one.xml"
        write_file(source, "<resources/>\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        write_file(source, "<resources><string name='late'>late edit</string></resources>\n")
        with self.assertRaisesRegex(ValidationError, "phase checkpoint is stale"):
            workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        directory = task_dir(self.repo, task_id)
        self.assertEqual(0, read_json(directory / "plan.json").get("active_phase_index", 0))
        self.assertFalse((directory / "phases" / "p2" / "baseline.json").exists())
        self.assertEqual("CHECKPOINT_PHASE", resolve_next_action(self.repo, task_id)["code"])
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        self.assertEqual(1, read_json(directory / "plan.json")["active_phase_index"])

    def test_PHASE_TRANSITION_008_stale_final_phase_routes_to_recheckpoint(self) -> None:
        phases = [{"id": "p1", "name": "Text", "expected_files": ["app/src/main/res/values/one.xml"]}]
        task_id = self._create_phased_task(phases)
        source = self.repo / "app/src/main/res/values/one.xml"
        write_file(source, "<resources/>\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        self.assertEqual("PREPARE_VERIFICATION", resolve_next_action(self.repo, task_id)["code"])
        write_file(source, "<resources><string name='late'>late edit</string></resources>\n")
        self.assertEqual("CHECKPOINT_PHASE", resolve_next_action(self.repo, task_id)["code"])
        with mock.patch.object(workflow, "check_material_drift", return_value={}):
            with self.assertRaisesRegex(ValidationError, "phase checkpoint is stale"):
                workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id, host="generic"))

    def test_PHASE_TRANSITION_009_fresh_final_phase_can_prepare_verification(self) -> None:
        phases = [{"id": "p1", "name": "Text", "expected_files": ["app/src/main/res/values/one.xml"]}]
        task_id = self._create_phased_task(phases)
        write_file(self.repo / "app/src/main/res/values/one.xml", "<resources/>\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        with mock.patch.object(workflow, "check_material_drift", return_value={}):
            current = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id, host="generic"))
        self.assertEqual("generic", current["review_host"])
        self.assertEqual("VERIFYING", read_json(task_dir(self.repo, task_id) / "plan.json")["status"])

    def test_PHASE_TRANSITION_010_completed_review_can_be_recheckpointed(self) -> None:
        phases = [
            {"id": "p1", "name": "Auth", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "UI", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        source = self.repo / "app/src/main/java/com/example/Auth.kt"
        write_file(source, "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, first = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", first["selected_reviewers"])
        for reviewer in first["selected_reviewers"]:
            complete_phase_review(
                self.repo, task_id, "p1", reviewer, f"first-{reviewer}",
                verdict="PASS", findings=[], package_sha256=first["package_sha256"],
            )
        finalize_phase_review(self.repo, task_id, "p1")

        write_file(source, "package com.example\nclass AuthFixed\n")
        self.assertEqual("CHECKPOINT_PHASE", resolve_next_action(self.repo, task_id)["code"])
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        review_dir = phase_review_dir(task_dir(self.repo, task_id), "p1")
        archived = review_dir.parent / "review-history" / first["phase_review_run_id"]
        self.assertTrue((archived / "current-phase-run.json").is_file())
        self.assertTrue((archived / "results" / f"{first['selected_reviewers'][0]}.json").is_file())

        _, second = build_phase_package(self.repo, task_id, "p1")
        self.assertNotEqual(first["phase_review_run_id"], second["phase_review_run_id"])
        record_phase_dispatch_batch(self.repo, task_id, "p1", second["selected_reviewers"])
        for reviewer in second["selected_reviewers"]:
            complete_phase_review(
                self.repo, task_id, "p1", reviewer, f"second-{reviewer}",
                verdict="PASS", findings=[], package_sha256=second["package_sha256"],
            )
        finalize_phase_review(self.repo, task_id, "p1")
        self.assertEqual("BEGIN_NEXT_PHASE", resolve_next_action(self.repo, task_id)["code"])

    def test_HOST_PHASE_001_completed_phases_route_to_configured_host(self) -> None:
        phases = [
            {"id": "p1", "name": "Text", "expected_files": ["app/src/main/res/values/one.xml"]},
            {"id": "p2", "name": "Style", "expected_files": ["app/src/main/res/values/two.xml"]},
        ]
        task_id = self._create_phased_task(phases, expected_modules="app,:")
        write_file(self.repo / "app/src/main/res/values/one.xml", "<resources/>\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        write_file(self.repo / "app/src/main/res/values/two.xml", "<resources/>\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p2"))
        product_file = self.repo / ".agents" / "scripts" / "_product.py"
        for host in ("antigravity", "claude", "codex", "generic"):
            with self.subTest(host=host), mock.patch.dict(os.environ, {"HARNESS_HOST": ""}):
                write_file(product_file, f"PRIMARY_AI_HOST = {host!r}\n")
                action = resolve_next_action(self.repo, task_id)
                self.assertEqual("PREPARE_VERIFICATION", action["code"])
                self.assertIn(f"--host {host}", action["command"])

    def test_HOST_PHASE_002_phase_response_ingestion_freezes_nontrusted_host(self) -> None:
        product_file = self.repo / ".agents" / "scripts" / "_product.py"
        write_file(product_file, "PRIMARY_AI_HOST = 'codex'\n")
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        reviewer = reviewers[0]
        self.assertEqual("codex", meta["review_host"])
        self.assertEqual(1, meta["review_protocol_version"])
        self.assertEqual("HOST_MANAGED_UNVERIFIED", resolve_next_action(self.repo, task_id)["review_execution_profile"]["model_policy"])
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        with self.assertRaisesRegex(ValidationError, "HOST_REVIEW_RESPONSE_REQUIRED"):
            complete_phase_review(self.repo, task_id, "p1", reviewer, "codex-review-1")
        with self.assertRaisesRegex(ValidationError, "host cannot change mid-run"):
            complete_phase_review(self.repo, task_id, "p1", reviewer, "codex-review-1", host="antigravity")
        response = json.dumps({
            "schema_version": 2,
            "task_id": task_id,
            "run_id": meta["phase_review_run_id"],
            "reviewer": reviewer,
            "review_package_sha256": meta["package_sha256"],
            "verdict": "PASS",
            "findings": [],
        })
        self.assertEqual("PASS", complete_phase_review(
            self.repo, task_id, "p1", reviewer, "codex-review-1", raw_response=response,
        )["verdict"])
        result = read_json(phase_review_dir(task_dir(self.repo, task_id), "p1") / "results" / f"{reviewer}.json")
        self.assertEqual("reviewer_response_text_unverified", result["provenance"])
        self.assertFalse(result["independent_execution_verified"])

    def test_HOST_PHASE_003_claude_multiphase_freezes_v1_final_run(self) -> None:
        product_file = self.repo / ".agents" / "scripts" / "_product.py"
        write_file(product_file, "PRIMARY_AI_HOST = 'claude'\n")
        phases = [
            {"id": "p1", "name": "First", "expected_files": ["app/src/main/res/values/one.xml"]},
            {"id": "p2", "name": "Second", "expected_files": ["app/src/main/res/values/two.xml"]},
        ]
        task_id = self._create_phased_task(phases, expected_modules="app,:")
        write_file(self.repo / "app/src/main/res/values/one.xml", "<resources/>\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        write_file(self.repo / "app/src/main/res/values/two.xml", "<resources/>\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p2"))
        self.assertEqual("PREPARE_VERIFICATION", resolve_next_action(self.repo, task_id)["code"])
        current = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        self.assertEqual("claude", current["review_host"])
        self.assertEqual(1, current["review_protocol_version"])

    def test_HOST_PHASE_004_nontrusted_cli_uses_response_file(self) -> None:
        write_file(self.repo / ".agents" / "scripts" / "_product.py", "PRIMARY_AI_HOST = 'claude'\n")
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        reviewer = reviewers[0]
        response = json.dumps({
            "schema_version": 2, "task_id": task_id, "run_id": meta["phase_review_run_id"],
            "reviewer": reviewer, "review_package_sha256": meta["package_sha256"],
            "verdict": "PASS", "findings": [],
        })
        response_file = self.repo / "reviewer-response.txt"
        write_file(response_file, response)
        with mock.patch("builtins.print"):
            exit_code = phase_review.main([
                "complete", "--repo", str(self.repo), "--task-id", task_id,
                "--phase-id", "p1", "--reviewer", reviewer,
                "--execution-id", "claude-review-1", "--response-file", str(response_file),
            ])
        self.assertEqual(0, exit_code)
        result_file = phase_review_dir(task_dir(self.repo, task_id), "p1") / "results" / f"{reviewer}.json"
        self.assertEqual("reviewer_response_text_unverified", read_json(result_file)["provenance"])

    def test_C_D3_response_file_accepts_claude_subagent_transcript(self) -> None:
        # Certification C-D3: a Claude reviewer reply could not be handed over unchanged. The
        # subagent transcript path is read directly; its path and sha256 are recorded, unverified.
        import hashlib
        write_file(self.repo / ".agents" / "scripts" / "_product.py", "PRIMARY_AI_HOST = 'claude'\n")
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        reviewer = reviewers[0]
        block = json.dumps({
            "schema_version": 2, "task_id": task_id, "run_id": meta["phase_review_run_id"],
            "reviewer": reviewer, "review_package_sha256": meta["package_sha256"],
            "verdict": "PASS", "findings": [],
        })
        claude_home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, claude_home, True)
        transcript = claude_home / "projects/-app/s1/subagents/agent-r1.jsonl"
        lines = [
            {"type": "user", "message": {"role": "user", "content": "Review phase p1."}},
            {"type": "assistant", "message": {"id": "m9", "role": "assistant", "content": [
                {"type": "text", "text": "Checked `x` | y < z.\n```json\n" + block + "\n```"}]}},
        ]
        write_file(transcript, "".join(json.dumps(line) + "\n" for line in lines))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(claude_home)}), mock.patch("builtins.print"):
            exit_code = phase_review.main([
                "complete", "--repo", str(self.repo), "--task-id", task_id, "--phase-id", "p1",
                "--reviewer", reviewer, "--execution-id", "agent-r1", "--response-file", str(transcript),
            ])
        self.assertEqual(0, exit_code)
        result = read_json(phase_review_dir(task_dir(self.repo, task_id), "p1") / "results" / f"{reviewer}.json")
        self.assertEqual("PASS", result["result"]["verdict"])
        self.assertFalse(result["independent_execution_verified"])
        self.assertEqual(str(transcript.resolve()), result["response_source"]["transcript_path"])
        self.assertEqual(hashlib.sha256(transcript.read_bytes()).hexdigest(), result["response_source"]["transcript_sha256"])

    def test_C_D6_response_file_that_is_not_a_file_is_a_usage_error(self) -> None:
        import contextlib
        import io
        write_file(self.repo / ".agents" / "scripts" / "_product.py", "PRIMARY_AI_HOST = 'claude'\n")
        task_id, reviewers, _, _ = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = phase_review.main([
                "complete", "--repo", str(self.repo), "--task-id", task_id, "--phase-id", "p1",
                "--reviewer", reviewers[0], "--execution-id", "r1", "--response-file", "PASS no findings",
            ])
        self.assertEqual(1, code)
        self.assertIn("--response-file must be the path of a file", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_AUDIT_005_nontrusted_dispatch_has_public_cli(self) -> None:
        write_file(self.repo / ".agents" / "scripts" / "_product.py", "PRIMARY_AI_HOST = 'codex'\n")
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        public_cli = [sys.executable, str(Path(__file__).resolve().parents[2] / "harness_cli.py")]
        status_result = subprocess.run(
            [*public_cli, "task", "status", "--repo", str(self.repo), "--task-id", task_id, "--next", "--host", "codex"],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, status_result.returncode, status_result.stderr)
        self.assertIn("NEXT_ACTION=DISPATCH_PHASE_REVIEWERS", status_result.stdout)
        self.assertIn("phase-review dispatch", status_result.stdout)
        dispatch_result = subprocess.run(
            [*public_cli, "phase-review", "dispatch", "--repo", str(self.repo), "--task-id", task_id,
             "--phase-id", "p1", "--host", "codex",
             *(argument for reviewer in reviewers for argument in ("--reviewer", reviewer))],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, dispatch_result.returncode, dispatch_result.stderr)
        self.assertIn("INDEPENDENT_EXECUTION_VERIFIED=false", dispatch_result.stdout)
        ok, _, ledger = load_phase_ledger(task_dir(self.repo, task_id), "p1", expected_run_id=meta["phase_review_run_id"])
        self.assertTrue(ok)
        self.assertTrue(all(entry["state"] == REVIEW_DISPATCHED for entry in ledger["reviewers"].values()))

    def test_AUDIT_005b_trusted_dispatch_rejects_manual_receipt(self) -> None:
        # The refusal is a clean CLI failure with guidance, not a traceback (seen live on Antigravity).
        import contextlib
        import io
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = phase_review.main([
                "dispatch", "--repo", str(self.repo), "--task-id", task_id,
                "--phase-id", "p1", "--host", "antigravity",
                *(argument for reviewer in reviewers for argument in ("--reviewer", reviewer)),
            ])
        self.assertEqual(1, code)
        self.assertIn("[FAIL]", err.getvalue())
        self.assertIn("invoke_subagent", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        ok, _, ledger = load_phase_ledger(task_dir(self.repo, task_id), "p1", expected_run_id=meta["phase_review_run_id"])
        self.assertTrue(ok)
        self.assertFalse(any(entry["state"] == REVIEW_DISPATCHED for entry in ledger["reviewers"].values()))

    def test_AUDIT_001b_public_checkpoint_rejects_unchanged_dirty_expected_file(self) -> None:
        asset = self.repo / "app/src/main/assets/preexisting.txt"
        write_file(asset, "developer work before task\n")
        task_id = self._create_phased_task([
            {"id": "p1", "name": "Update asset", "expected_files": ["app/src/main/assets/preexisting.txt"]},
            {"id": "p2", "name": "Follow-up", "expected_files": ["docs/next.md"]},
        ])
        command = [
            sys.executable, str(Path(__file__).resolve().parents[2] / "harness_cli.py"),
            "task", "checkpoint-phase", "--repo", str(self.repo), "--task-id", task_id, "--phase-id", "p1",
        ]
        unchanged = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertNotEqual(0, unchanged.returncode)
        self.assertIn("no file changes detected", unchanged.stderr)
        write_file(asset, "developer work before task\napproved task addition\n")
        changed = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual(0, changed.returncode, changed.stderr)

    def test_AUDIT_006_revision_after_complete_phase_preserves_approved_work(self) -> None:
        phases = [
            {"id": "p1", "name": "Asset phase", "expected_files": ["app/src/main/assets/note.txt"]},
            {"id": "p2", "name": "UI phase", "expected_files": ["app/src/main/res/layout/old.xml"]},
        ]
        task_id = self._create_phased_task(phases)
        write_file(self.repo / "app/src/main/assets/note.txt", "approved work\n")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
        revised_phases = [phases[0], {"id": "p2", "name": "UI phase", "expected_files": ["app/src/main/res/layout/new.xml"]}]
        public_cli = [sys.executable, str(Path(__file__).resolve().parents[2] / "harness_cli.py")]
        revised = subprocess.run(
            [*public_cli, "task", "revise", "--repo", str(self.repo), "--task-id", task_id,
             "--outcome", "Implement revised UI phase", "--kind", "FEATURE", "--planning-depth", "BOUNDED",
             "--phases", json.dumps(revised_phases),
             "--expected-files", "app/src/main/assets/note.txt,app/src/main/res/layout/new.xml",
             "--expected-modules", ":app"],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, revised.returncode, revised.stderr)
        revision = read_json(task_dir(self.repo, task_id) / "plan.json")
        self.assertEqual("AWAITING_DEVELOPER_APPROVAL", revision["status"])
        self.assertEqual(1, revision["active_phase_index"])
        approval = subprocess.run(
            [*public_cli, "task", "approve", "--repo", str(self.repo), "--task-id", task_id,
             "--source", "conversation", "--proof-reference", "approve revised UI scope",
             "--enforcement-tier", "RULE_ENFORCED"],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, approval.returncode, approval.stderr)
        approved = read_json(task_dir(self.repo, task_id) / "plan.json")
        self.assertEqual("IMPLEMENTING", approved["status"])
        phase_state = read_json(task_dir(self.repo, task_id) / "phase-state.json")
        self.assertEqual(["p1"], phase_state["completed_phases"])
        self.assertEqual("p2", phase_state["current_phase_id"])
        next_action = resolve_next_action(self.repo, task_id)
        self.assertEqual("IMPLEMENT_APPROVED_SCOPE", next_action["code"])
        write_file(self.repo / "app/src/main/res/layout/new.xml", "<FrameLayout/>\n")
        next_action = resolve_next_action(self.repo, task_id)
        self.assertEqual("CHECKPOINT_PHASE", next_action["code"])
        self.assertIn('--phase-id "p2"', next_action["command"])

    def test_AUDIT_011_docs_only_phase_checkpoints_without_gradle(self) -> None:
        task_id = self._create_phased_task([
            {"id": "p1", "name": "Documentation", "expected_files": ["docs/usage.md"]},
            {"id": "p2", "name": "Follow-up", "expected_files": ["docs/next.md"]},
        ])
        write_file(self.repo / "docs/usage.md", "# Usage\n")
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[2] / "harness_cli.py"), "task", "checkpoint-phase",
             "--repo", str(self.repo), "--task-id", task_id, "--phase-id", "p1"],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        checkpoint = read_json(task_dir(self.repo, task_id) / "phases" / "p1" / "checkpoint.json")
        self.assertEqual("CHECKPOINT_PASS", checkpoint["status"])
        self.assertEqual("NOT_REQUIRED", checkpoint["compile"]["status"])

    def test_AUDIT_013_public_docs_plan_in_mixed_architecture_project(self) -> None:
        """A docs-only task must not demand an Android architecture family."""
        write_file(self.repo / "app/src/main/java/legacy/LegacyScreen.kt", "class LegacyScreen : Fragment()\n")
        write_file(self.repo / "app/src/main/java/modern/CompScreen.kt", "@Composable fun CompScreen() {}\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-qm", "mixed architecture baseline")
        phases = [
            {"id": "p1", "name": "Documentation", "expected_files": ["docs/guide.md"]},
            {"id": "p2", "name": "Follow-up", "expected_files": ["docs/next.md"]},
        ]
        command = [
            sys.executable, str(Path(__file__).resolve().parents[2] / "harness_cli.py"),
            "task", "draft", "--repo", str(self.repo), "--task-id", "audit-013",
            "--outcome", "Document onboarding", "--kind", "FEATURE",
            "--expected-files", "docs/guide.md,docs/next.md", "--phases", json.dumps(phases),
        ]
        for paths in (
            "docs/guide.md,app/src/main/java/unknown/Thing.kt",
            "app/src/main/assets/runtime.txt",
        ):
            guarded = subprocess.run(
                [*command[:], "--expected-files", paths],
                cwd=self.repo, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(0, guarded.returncode)
            self.assertIn("ARCHITECTURE_DECISION_REQUIRED", guarded.stderr)
        code_phase = [*phases, {"id": "p3", "name": "Code", "expected_files": ["app/src/main/java/unknown/Thing.kt"]}]
        guarded = subprocess.run(
            [*command, "--phases", json.dumps(code_phase)],
            cwd=self.repo, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(0, guarded.returncode)
        self.assertIn("ARCHITECTURE_DECISION_REQUIRED", guarded.stderr)
        drafted = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual(0, drafted.returncode, drafted.stderr)
        plan = read_json(task_dir(self.repo, "audit-013") / "plan.json")
        self.assertFalse(plan.get("architecture_contract"))

    def test_AUDIT_003b_public_checkpoint_allows_existing_lint_debt_only(self) -> None:
        source = self.repo / "app/src/main/java/com/example/App.kt"
        write_file(source, "package com.example\nimport java.util.*\nclass App\n")
        run_git(self.repo, "add", "app/src/main/java/com/example/App.kt")
        run_git(self.repo, "commit", "-qm", "legacy lint debt")
        task_id = self._create_phased_task([
            {"id": "p1", "name": "Safe Kotlin edit", "expected_files": ["app/src/main/java/com/example/App.kt"]},
            {"id": "p2", "name": "Follow-up", "expected_files": ["docs/next.md"]},
        ])
        self._pass_phase_tests(task_id, "p1")
        command = [
            sys.executable, str(Path(__file__).resolve().parents[2] / "harness_cli.py"),
            "task", "checkpoint-phase", "--repo", str(self.repo), "--task-id", task_id, "--phase-id", "p1",
        ]
        write_file(source, "package com.example\nimport java.util.*\nimport kotlin.collections.*\nclass App\n// task edit\n")
        new_debt = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertNotEqual(0, new_debt.returncode)
        self.assertIn("Kotlin lint failed", new_debt.stderr)
        write_file(source, "package com.example\nimport java.util.*\nclass App\n// task edit\n")
        old_debt = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual(0, old_debt.returncode, old_debt.stderr)

    def test_PHASE_BUDGET_001_critical_plan_reserves_final_policy_roster(self) -> None:
        plan = {
            "task_kind": "FEATURE", "expected_surfaces": ["AUTH", "SECURITY"],
            "phases": [{"expected_surfaces": ["TEST_ONLY"]}],
            "model_call_budget": 6, "review_calls_used": 0,
        }
        reserve = phase_review.derive_final_review_reserve(self.repo, plan, {"surfaces": ["AUTH"], "severity": "CRITICAL"})
        self.assertEqual("T5_CRITICAL", reserve["risk_tier"])
        self.assertIn("test-quality-reviewer-agent", reserve["reviewers"])
        self.assertGreaterEqual(reserve["reserved_calls"], 6)
        allowed, reason = phase_review.check_phase_safety_cap(plan, 1, reserve)
        self.assertFalse(allowed)
        self.assertIn("reserved_final", reason)

    def test_PHASE_DISPATCH_001_replay_requires_exact_cohort_and_receipts(self) -> None:
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        plan_file = task_dir(self.repo, task_id) / "plan.json"
        used = read_json(plan_file)["review_calls_used"]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        self.assertEqual(used, read_json(plan_file)["review_calls_used"])
        with self.assertRaisesRegex(ValidationError, "dispatch batch mismatch"):
            record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers[:1])
        receipt_file = phase_review_dir(task_dir(self.repo, task_id), "p1") / "dispatch" / meta["phase_review_run_id"] / f"{reviewers[0]}.json"
        receipt = read_json(receipt_file)
        receipt["host"] = "tampered"
        atomic_write_json(receipt_file, receipt)
        with self.assertRaisesRegex(ValidationError, "receipt mismatch"):
            record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)

    def test_PHASE_DISPATCH_002_partial_receipt_blocks_retry(self) -> None:
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        tdir = task_dir(self.repo, task_id)
        receipt_file = phase_review_dir(tdir, "p1") / "dispatch" / meta["phase_review_run_id"] / f"{reviewers[0]}.json"
        receipt_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(receipt_file, {"host": "unproven-partial-dispatch"})
        used_before = read_json(tdir / "plan.json").get("review_calls_used", 0)
        with self.assertRaisesRegex(ValidationError, "partial dispatch receipt"):
            record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        self.assertEqual(used_before, read_json(tdir / "plan.json").get("review_calls_used", 0))
        ok, err, ledger = load_phase_ledger(tdir, "p1", expected_run_id=meta["phase_review_run_id"])
        self.assertTrue(ok, err)
        self.assertTrue(all(ledger["reviewers"][r]["state"] == REVIEW_NOT_DISPATCHED for r in reviewers))

    def _completed_dispatch_for_finalization(self) -> tuple[str, list[str], dict[str, Any]]:
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        for reviewer in reviewers:
            complete_phase_review(
                repo=self.repo, task_id=task_id, phase_id="p1", reviewer=reviewer,
                execution_id=f"conv-{reviewer}", verdict="PASS", findings=[],
                package_sha256=meta["package_sha256"],
            )
        return task_id, reviewers, meta

    def test_PHASE_FINALIZE_001_stale_change_blocks_pass(self) -> None:
        task_id, _, _ = self._completed_dispatch_for_finalization()
        write_file(self.repo / "app/src/main/java/com/example/Auth.kt", "package com.example\nclass AuthChanged\n")
        with self.assertRaisesRegex(ValidationError, "PHASE_REVIEW_STALE"):
            finalize_phase_review(self.repo, task_id, "p1")

    def test_PHASE_FINALIZE_002_missing_result_blocks_pass(self) -> None:
        task_id, reviewers, _ = self._completed_dispatch_for_finalization()
        result_file = phase_review_dir(task_dir(self.repo, task_id), "p1") / "results" / f"{reviewers[0]}.json"
        result_file.unlink()
        with self.assertRaisesRegex(ValidationError, "PHASE_REVIEW_RESULT_BLOCKED"):
            finalize_phase_review(self.repo, task_id, "p1")

    def test_PHASE_STATE_004_review_pass_remains_complete_after_all_writes(self) -> None:
        """PHASE_STATE_004: review PASS remains COMPLETE after all writes."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])

        for rev in meta["selected_reviewers"]:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=rev,
                execution_id="conv-1",
                verdict="PASS",
                findings=[],
                package_sha256=meta["package_sha256"],
            )

        res = finalize_phase_review(self.repo, task_id, "p1")
        self.assertEqual("PASS", res["verdict"])

        pstate = read_json(task_dir(self.repo, task_id) / "phase-state.json")
        self.assertIn("p1", pstate.get("completed_phases", []))
        self.assertEqual(PHASE_COMPLETE, phase_review.get_phase_substate(pstate, "p1"))

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("BEGIN_NEXT_PHASE", act["code"])

    def test_PHASE_STATE_005_review_findings_remain_review_blocked(self) -> None:
        """PHASE_STATE_005: review findings remain REVIEW_BLOCKED."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")
        record_phase_dispatch_batch(self.repo, task_id, "p1", meta["selected_reviewers"])

        rev = meta["selected_reviewers"][0]
        complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=rev,
            execution_id="conv-1",
            verdict="FINDINGS",
            findings=[{"id": "SEC-001", "severity": "HIGH", "message": "Insecure token"}],
            package_sha256=meta["package_sha256"],
        )
        for other_rev in meta["selected_reviewers"][1:]:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=other_rev,
                execution_id="conv-2",
                verdict="PASS",
                findings=[],
                package_sha256=meta["package_sha256"],
            )

        res = finalize_phase_review(self.repo, task_id, "p1")
        self.assertEqual("FINDINGS", res["verdict"])

        pstate = read_json(task_dir(self.repo, task_id) / "phase-state.json")
        self.assertNotIn("p1", pstate.get("completed_phases", []))
        self.assertEqual(PHASE_REVIEW_BLOCKED, phase_review.get_phase_substate(pstate, "p1"))

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("FIX_PHASE_FINDINGS", act["code"])

    def _run_pre_tool_safety(self, payload: dict) -> tuple[int, dict]:
        safety_script = Path(__file__).resolve().parent / "pre_tool_safety.py"
        env = {
            **os.environ,
            "HARNESS_REPO": str(self.repo),
            "HARNESS_REPO_DIR": str(self.repo),
            "PYTHONPATH": str(Path(__file__).resolve().parent),
        }
        proc = subprocess.run(
            [sys.executable, str(safety_script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        try:
            res = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except Exception:
            res = {"stdout": proc.stdout, "stderr": proc.stderr}
        return proc.returncode, res

    def _run_post_tool_reconcile(self, payload: dict) -> tuple[int, dict]:
        post_script = Path(__file__).resolve().parent / "post_tool_reconcile.py"
        env = {
            **os.environ,
            "HARNESS_REPO": str(self.repo),
            "HARNESS_REPO_DIR": str(self.repo),
            "PYTHONPATH": str(Path(__file__).resolve().parent),
        }
        proc = subprocess.run(
            [sys.executable, str(post_script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        try:
            res = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except Exception:
            res = {"stdout": proc.stdout, "stderr": proc.stderr}
        return proc.returncode, res

    def _setup_dispatch_state(self) -> tuple[str, list[str], dict[str, str], dict[str, Any]]:
        product_file = self.repo / ".agents" / "scripts" / "_product.py"
        if not product_file.exists():
            write_file(product_file, "PRIMARY_AI_HOST = 'antigravity'\n")
        phases = [
            {"id": "p1", "name": "Auth Phase", "description": "Implement TokenStorage with cryptographic tokens", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "UI Phase", "description": "Implement UI", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth {\n  fun encrypt(data: String) {}\n}\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        pkg_p, meta = build_phase_package(self.repo, task_id, "p1")
        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("DISPATCH_PHASE_REVIEWERS", act["code"])
        briefs = {}
        for r in act["reviewers"]:
            b_file = Path(act["briefs"][r])
            briefs[r] = b_file.read_text(encoding="utf-8")
        return task_id, act["reviewers"], briefs, meta

    def test_PHASE_HOOK_001_exact_batch_allowed(self) -> None:
        """PHASE_HOOK_001: exact batch allowed, receipts and ledger updated."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r]} for r in reviewers]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual(0, code)
        self.assertEqual("allow", res.get("decision"))

        run_id = meta["phase_review_run_id"]
        tdir = task_dir(self.repo, task_id)
        ok, err, ledger = load_phase_ledger(tdir, "p1", expected_run_id=run_id)
        self.assertTrue(ok, err)
        for r in reviewers:
            receipt_f = tdir / "phases" / "p1" / "review" / "dispatch" / run_id / f"{r}.json"
            self.assertTrue(receipt_f.is_file())
            self.assertEqual(REVIEW_DISPATCHED, ledger["reviewers"][r]["state"])

    def test_PHASE_HOOK_002_subset_denied(self) -> None:
        """PHASE_HOOK_002: subset denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": []}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_003_superset_denied(self) -> None:
        """PHASE_HOOK_003: superset denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r]} for r in reviewers]
        subagents.append({"TypeName": "extra-reviewer-agent", "Role": "extra-reviewer-agent", "Prompt": "Extra"})
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_004_duplicate_denied(self) -> None:
        """PHASE_HOOK_004: duplicate denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        subagents = [
            {"TypeName": r, "Role": r, "Prompt": briefs[r]},
            {"TypeName": r, "Role": r, "Prompt": briefs[r]},
        ]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_005_wrong_role_denied(self) -> None:
        """PHASE_HOOK_005: wrong Role denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": "other-role", "Prompt": briefs[r]} for r in reviewers]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_006_wrong_typename_denied(self) -> None:
        """PHASE_HOOK_006: wrong TypeName denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": "other-type", "Role": r, "Prompt": briefs[r]} for r in reviewers]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_007_missing_prompt_denied(self) -> None:
        """PHASE_HOOK_007: missing Prompt denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": ""} for r in reviewers]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_008_stale_prompt_denied(self) -> None:
        """PHASE_HOOK_008: stale/altered Prompt denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": "Altered prompt text that differs from brief"} for r in reviewers]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_009_model_key_denied(self) -> None:
        """PHASE_HOOK_009: model key denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r], "model": "pro"} for r in reviewers]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_010_model_null_denied(self) -> None:
        """PHASE_HOOK_010: Model:null denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r], "Model": None} for r in reviewers]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_011_unsupported_reasoning_key_denied(self) -> None:
        """PHASE_HOOK_011: unsupported reasoning key denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r], "reasoning": "high"} for r in reviewers]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_HOOK_012_valid_inherited_model_invocation_allowed(self) -> None:
        """PHASE_HOOK_012: valid inherited-model invocation allowed."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r]} for r in reviewers]
        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual("allow", res.get("decision"))

    def test_PHASE_HOOK_013_generic_implementation_specialist_allowed_outside_phase_dispatch(self) -> None:
        """PHASE_HOOK_013: generic implementation specialist allowed outside phase dispatch."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Implement normal coding", "expected_files": ["app/src/main/java/com/example/App.kt"]},
        ]
        task_id = self._create_phased_task(phases, kind="FEATURE")
        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("IMPLEMENT_APPROVED_SCOPE", act["code"])
        generic_call = {
            "toolName": "invoke_subagent",
            "toolArgs": {
                "Subagents": [
                    {"TypeName": "code-debugger", "Role": "code-debugger", "Prompt": "Help debug unit test"}
                ]
            }
        }
        code, res = self._run_pre_tool_safety(generic_call)
        self.assertEqual("allow", res.get("decision"))

    def test_PHASE_RETRY_HOOK_001_exact_correction_allowed(self) -> None:
        """PHASE_RETRY_HOOK_001: exact correction send_message allowed."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        ret = complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-r1",
            raw_response="not a valid json block",
            package_sha256=meta["package_sha256"],
        )
        self.assertEqual("PROTOCOL_RETRY_REQUIRED", ret["status"])

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("RETRY_PHASE_REVIEW_PROTOCOL", act["code"])
        msg = act["retry_prompt"]

        code, res = self._run_pre_tool_safety({
            "toolName": "send_message",
            "toolArgs": {"Recipient": "conv-r1", "Message": msg}
        })
        self.assertEqual(0, code)
        self.assertEqual("allow", res.get("decision"))

    def test_PHASE_RETRY_HOOK_002_wrong_recipient_denied(self) -> None:
        """PHASE_RETRY_HOOK_002: wrong recipient in send_message denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-r1",
            raw_response="not a valid json block",
            package_sha256=meta["package_sha256"],
        )
        act = resolve_next_action(self.repo, task_id)
        msg = act["retry_prompt"]

        code, res = self._run_pre_tool_safety({
            "toolName": "send_message",
            "toolArgs": {"Recipient": "wrong-conv-id", "Message": msg}
        })
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_RETRY_HOOK_003_changed_message_denied(self) -> None:
        """PHASE_RETRY_HOOK_003: changed message in send_message denied."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-r1",
            raw_response="not a valid json block",
            package_sha256=meta["package_sha256"],
        )
        code, res = self._run_pre_tool_safety({
            "toolName": "send_message",
            "toolArgs": {"Recipient": "conv-r1", "Message": "Altered message text"}
        })
        self.assertEqual("deny", res.get("decision"))

    def test_PHASE_RETRY_HOOK_004_correction_does_not_increment_call_count(self) -> None:
        """PHASE_RETRY_HOOK_004: correction does not increment review_calls_used."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        plan_before = read_json(task_dir(self.repo, task_id) / "plan.json")
        calls_before = plan_before.get("review_calls_used", 0)

        complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-r1",
            raw_response="not a valid json block",
            package_sha256=meta["package_sha256"],
        )
        plan_after = read_json(task_dir(self.repo, task_id) / "plan.json")
        self.assertEqual(calls_before, plan_after.get("review_calls_used", 0))

    def test_PHASE_POST_001_failed_launch_sets_env_blocked(self) -> None:
        """PHASE_POST_001: failed launch sets ENV_BLOCKED in phase ledger."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)

        payload = {
            "toolCall": {"name": "invoke_subagent", "args": {"Subagents": [{"TypeName": r} for r in reviewers]}},
            "error": "Failed to launch subagent: timeout",
        }
        code, _ = self._run_post_tool_reconcile(payload)
        self.assertEqual(0, code)

        tdir = task_dir(self.repo, task_id)
        ok, err, ledger = load_phase_ledger(tdir, "p1", expected_run_id=meta["phase_review_run_id"])
        self.assertTrue(ok, err)
        for r in reviewers:
            self.assertEqual(REVIEW_ENV_BLOCKED, ledger["reviewers"][r]["state"])

    def test_PHASE_POST_002_only_affected_phase_batch_changes(self) -> None:
        """PHASE_POST_002: only affected phase batch changes."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        if len(reviewers) < 2:
            return

        affected = reviewers[0]
        unaffected = reviewers[1]
        payload = {
            "toolCall": {"name": "invoke_subagent", "args": {"Subagents": [{"TypeName": affected}]}},
            "error": "Failed to launch subagent: rate limit",
        }
        self._run_post_tool_reconcile(payload)

        tdir = task_dir(self.repo, task_id)
        ok, err, ledger = load_phase_ledger(tdir, "p1", expected_run_id=meta["phase_review_run_id"])
        self.assertTrue(ok, err)
        self.assertEqual(REVIEW_ENV_BLOCKED, ledger["reviewers"][affected]["state"])
        self.assertEqual(REVIEW_DISPATCHED, ledger["reviewers"][unaffected]["state"])

    def test_PHASE_POST_003_reconciliation_exception_writes_durable_marker(self) -> None:
        """PHASE_POST_003: reconciliation exception writes durable marker."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)

        tdir = task_dir(self.repo, task_id)
        ledger_p = phase_review.phase_ledger_file(tdir, "p1")
        ledger_p.write_text("corrupted json", encoding="utf-8")

        payload = {
            "toolCall": {"name": "invoke_subagent", "args": {"Subagents": [{"TypeName": r} for r in reviewers]}},
            "error": "Error during launch",
        }
        self._run_post_tool_reconcile(payload)

        marker1 = phase_review_dir(tdir, "p1") / "post-tool-reconcile-error.json"
        self.assertTrue(marker1.is_file())

    def test_PHASE_POST_004_marker_causes_router_blocker(self) -> None:
        """PHASE_POST_004: post-tool-reconcile-error marker causes router blocker."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        tdir = task_dir(self.repo, task_id)
        marker1 = phase_review_dir(tdir, "p1") / "post-tool-reconcile-error.json"
        atomic_write_json(marker1, {"schema_version": 1, "task_id": task_id, "phase_id": "p1", "error_code": "POST_TOOL_RECONCILE_FAILED"})

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("PHASE_REVIEW_ENV_BLOCKED", act["code"])

    def test_PHASE_POST_005_no_wait_when_no_real_execution_exists(self) -> None:
        """PHASE_POST_005: no WAIT returned when no real execution exists."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        payload = {
            "toolCall": {"name": "invoke_subagent", "args": {"Subagents": [{"TypeName": r} for r in reviewers]}},
            "error": "Subagent failed",
        }
        self._run_post_tool_reconcile(payload)

        act = resolve_next_action(self.repo, task_id)
        self.assertNotEqual("WAIT_FOR_PHASE_REVIEWERS", act["code"])
        self.assertEqual("PHASE_REVIEW_ENV_BLOCKED", act["code"])

    def test_PHASE_EXEC_001_unknown_reviewer_rejected(self) -> None:
        """PHASE_EXEC_001: unknown reviewer rejected in complete_phase_review."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        with self.assertRaises(ValidationError) as ctx:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer="hallucinated-agent",
                execution_id="conv-1",
                verdict="PASS",
                findings=[],
                package_sha256=meta["package_sha256"],
            )
        self.assertIn("not in selected", str(ctx.exception))

    def test_PHASE_PROOF_001_completion_cannot_create_dispatch(self) -> None:
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        reviewer = reviewers[0]
        with self.assertRaisesRegex(ValidationError, "PHASE_REVIEW_NOT_DISPATCHED"):
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=reviewer,
                execution_id="conv-untrusted",
                raw_response=json.dumps({
                    "schema_version": 2,
                    "task_id": task_id,
                    "run_id": meta["phase_review_run_id"],
                    "reviewer": reviewer,
                    "review_package_sha256": meta["package_sha256"],
                    "verdict": "PASS",
                    "findings": [],
                }),
                package_sha256=meta["package_sha256"],
            )
        ok, err, ledger = load_phase_ledger(task_dir(self.repo, task_id), "p1", expected_run_id=meta["phase_review_run_id"])
        self.assertTrue(ok, err)
        self.assertEqual(REVIEW_NOT_DISPATCHED, ledger["reviewers"][reviewer]["state"])
        self.assertFalse((phase_review_dir(task_dir(self.repo, task_id), "p1") / "dispatch").exists())

    def test_PHASE_PROOF_002_reviewing_missing_run_blocks_router(self) -> None:
        task_id, _, _, _ = self._setup_dispatch_state()
        phase_run_file(task_dir(self.repo, task_id), "p1").unlink()
        self.assertEqual("PHASE_REVIEW_STATE_BLOCKED", resolve_next_action(self.repo, task_id)["code"])
        with self.assertRaisesRegex(ValidationError, "without a run identity"):
            checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))

    def test_PHASE_PROOF_003_reviewing_missing_ledger_blocks_router(self) -> None:
        task_id, _, _, _ = self._setup_dispatch_state()
        phase_review.phase_ledger_file(task_dir(self.repo, task_id), "p1").unlink()
        self.assertEqual("PHASE_REVIEW_LEDGER_BLOCKED", resolve_next_action(self.repo, task_id)["code"])

    def test_PHASE_PROOF_004_reviewing_corrupt_or_mismatched_artifacts_block_router(self) -> None:
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        tdir = task_dir(self.repo, task_id)
        run_file = phase_run_file(tdir, "p1")
        ledger_file = phase_review.phase_ledger_file(tdir, "p1")
        original_run = read_json(run_file)
        original_ledger = read_json(ledger_file)
        for mutation, expected in (
            ({"run": "corrupt"}, "PHASE_REVIEW_STATE_BLOCKED"),
            ({"run": {**original_run, "task_id": "other-task"}}, "PHASE_REVIEW_STATE_BLOCKED"),
            ({"ledger": "corrupt"}, "PHASE_REVIEW_LEDGER_BLOCKED"),
            ({"ledger": {**original_ledger, "run_id": "other-run"}}, "PHASE_REVIEW_LEDGER_BLOCKED"),
            ({"ledger": {**original_ledger, "reviewers": {}}}, "PHASE_REVIEW_LEDGER_BLOCKED"),
        ):
            with self.subTest(mutation=mutation):
                if "run" in mutation:
                    run_file.write_text("not json" if mutation["run"] == "corrupt" else json.dumps(mutation["run"]), encoding="utf-8")
                if "ledger" in mutation:
                    ledger_file.write_text("not json" if mutation["ledger"] == "corrupt" else json.dumps(mutation["ledger"]), encoding="utf-8")
                self.assertEqual(expected, resolve_next_action(self.repo, task_id)["code"])
                atomic_write_json(run_file, original_run)
                atomic_write_json(ledger_file, original_ledger)

    def test_PHASE_PROOF_005_completed_review_requires_live_proof_to_advance(self) -> None:
        task_id, reviewers, meta = self._completed_dispatch_for_finalization()
        finalize_phase_review(self.repo, task_id, "p1")
        self.assertEqual("BEGIN_NEXT_PHASE", resolve_next_action(self.repo, task_id)["code"])
        directory = task_dir(self.repo, task_id)
        review_dir = phase_review_dir(directory, "p1")
        proof_files = [
            phase_run_file(directory, "p1"),
            phase_review.phase_ledger_file(directory, "p1"),
            review_dir / "phase-review-package.md",
            review_dir / "phase_review_result.json",
            review_dir / "dispatch" / meta["phase_review_run_id"] / f"{reviewers[0]}.json",
            review_dir / "results" / f"{reviewers[0]}.json",
        ]
        for proof_file in proof_files:
            with self.subTest(missing=proof_file.name):
                saved = proof_file.read_bytes()
                proof_file.unlink()
                try:
                    self.assertEqual("PHASE_CHECKPOINT_STATE_BLOCKED", resolve_next_action(self.repo, task_id)["code"])
                    with self.assertRaisesRegex(ValidationError, "phase review proof"):
                        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id))
                finally:
                    proof_file.write_bytes(saved)
        result_file = review_dir / "results" / f"{reviewers[0]}.json"
        original_result = read_json(result_file)
        tampered_result = json.loads(json.dumps(original_result))
        tampered_result["result"]["verdict"] = "FINDINGS"
        tampered_result["result_sha256"] = canonical_sha256(tampered_result["result"])
        atomic_write_json(result_file, tampered_result)
        self.assertEqual("PHASE_CHECKPOINT_STATE_BLOCKED", resolve_next_action(self.repo, task_id)["code"])
        atomic_write_json(result_file, original_result)

    def test_ROUTER_MATRIX_001_phase_review_states_are_actionable(self) -> None:
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        ledger_file = phase_review.phase_ledger_file(task_dir(self.repo, task_id), "p1")
        run_file = phase_run_file(task_dir(self.repo, task_id), "p1")
        expected = [
            ("not dispatched", "DISPATCH_PHASE_REVIEWERS", "HOST_ACTION"),
        ]
        for label, code, kind in expected:
            with self.subTest(state=label):
                action = resolve_next_action(self.repo, task_id)
                self.assertEqual((code, kind), (action["code"], action["kind"]))
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        original_ledger = read_json(ledger_file)
        for label, state, code, kind in (
            ("dispatched", REVIEW_DISPATCHED, "WAIT_FOR_PHASE_REVIEWERS", "HOST_ACTION"),
            ("environment blocked", REVIEW_ENV_BLOCKED, "PHASE_REVIEW_ENV_BLOCKED", "HARNESS_DIAGNOSTIC"),
            ("protocol retry", REVIEW_PROTOCOL_RETRY_REQUIRED, "RETRY_PHASE_REVIEW_PROTOCOL", "HOST_ACTION"),
        ):
            ledger = json.loads(json.dumps(original_ledger))
            ledger["reviewers"][reviewers[0]]["state"] = state
            if state == REVIEW_PROTOCOL_RETRY_REQUIRED:
                ledger["reviewers"][reviewers[0]]["execution_id"] = "conv-matrix"
            ledger["ledger_sha256"] = phase_review.compute_ledger_sha(ledger)
            atomic_write_json(ledger_file, ledger)
            with self.subTest(state=label):
                action = resolve_next_action(self.repo, task_id)
                self.assertEqual((code, kind), (action["code"], action["kind"]))
        atomic_write_json(ledger_file, original_ledger)
        saved_run = read_json(run_file)
        run_file.unlink()
        action = resolve_next_action(self.repo, task_id)
        self.assertEqual(("PHASE_REVIEW_STATE_BLOCKED", "HARNESS_DIAGNOSTIC"), (action["code"], action["kind"]))
        atomic_write_json(run_file, saved_run)
        ledger_file.unlink()
        action = resolve_next_action(self.repo, task_id)
        self.assertEqual(("PHASE_REVIEW_LEDGER_BLOCKED", "HARNESS_DIAGNOSTIC"), (action["code"], action["kind"]))

    def test_PHASE_EXEC_002_first_completion_binds_id(self) -> None:
        """PHASE_EXEC_002: first completion binds execution ID."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-bound-01",
            verdict="PASS",
            findings=[],
            package_sha256=meta["package_sha256"],
        )
        ok, err, ledger = load_phase_ledger(task_dir(self.repo, task_id), "p1", expected_run_id=meta["phase_review_run_id"])
        self.assertTrue(ok, err)
        self.assertEqual("conv-bound-01", ledger["reviewers"][r]["execution_id"])

    def test_PHASE_EXEC_003_same_id_idempotent(self) -> None:
        """PHASE_EXEC_003: same execution ID idempotent in complete_phase_review."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        res1 = complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-bound-01",
            verdict="PASS",
            findings=[],
            package_sha256=meta["package_sha256"],
        )
        res2 = complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-bound-01",
            verdict="PASS",
            findings=[],
            package_sha256=meta["package_sha256"],
        )
        self.assertEqual(res1.get("verdict"), res2.get("verdict"))

    def test_PHASE_EXEC_003a_result_replay_restores_incomplete_ledger(self) -> None:
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        reviewer = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        complete_phase_review(
            repo=self.repo, task_id=task_id, phase_id="p1", reviewer=reviewer,
            execution_id="conv-replay", verdict="PASS", findings=[],
            package_sha256=meta["package_sha256"],
        )
        tdir = task_dir(self.repo, task_id)
        ledger_file = phase_review.phase_ledger_file(tdir, "p1")
        ledger = read_json(ledger_file)
        entry = ledger["reviewers"][reviewer]
        entry["state"] = REVIEW_DISPATCHED
        for key in ("verdict", "findings", "completed_at", "result_sha256"):
            entry.pop(key, None)
        ledger["ledger_sha256"] = phase_review.compute_ledger_sha(ledger)
        atomic_write_json(ledger_file, ledger)
        replay = complete_phase_review(
            repo=self.repo, task_id=task_id, phase_id="p1", reviewer=reviewer,
            execution_id="conv-replay", verdict="PASS", findings=[],
            package_sha256=meta["package_sha256"],
        )
        self.assertEqual("PASS", replay["verdict"])
        self.assertEqual(REVIEW_COMPLETED, read_json(ledger_file)["reviewers"][reviewer]["state"])

    def test_PHASE_EXEC_003b_corrupt_result_replay_rejected(self) -> None:
        task_id, reviewers, _, meta = self._setup_dispatch_state()
        reviewer = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        complete_phase_review(
            repo=self.repo, task_id=task_id, phase_id="p1", reviewer=reviewer,
            execution_id="conv-replay", verdict="PASS", findings=[],
            package_sha256=meta["package_sha256"],
        )
        result_file = phase_review_dir(task_dir(self.repo, task_id), "p1") / "results" / f"{reviewer}.json"
        result = read_json(result_file)
        result["result"]["verdict"] = "FINDINGS"
        atomic_write_json(result_file, result)
        with self.assertRaisesRegex(ValidationError, "PHASE_REVIEW_RESULT_BLOCKED"):
            complete_phase_review(
                repo=self.repo, task_id=task_id, phase_id="p1", reviewer=reviewer,
                execution_id="conv-replay", verdict="PASS", findings=[],
                package_sha256=meta["package_sha256"],
            )

    def test_PHASE_EXEC_004_different_id_rejected(self) -> None:
        """PHASE_EXEC_004: different execution ID rejected after binding."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-bound-01",
            verdict="PASS",
            findings=[],
            package_sha256=meta["package_sha256"],
        )
        with self.assertRaises(ValidationError) as ctx:
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=r,
                execution_id="conv-different-02",
                verdict="PASS",
                findings=[],
                package_sha256=meta["package_sha256"],
            )
        self.assertIn("rejecting different execution", str(ctx.exception))

    def test_PHASE_EXEC_005_completed_redispatch_rejected(self) -> None:
        """PHASE_EXEC_005: completed reviewer cannot be redispatched."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-bound-01",
            verdict="PASS",
            findings=[],
            package_sha256=meta["package_sha256"],
        )
        with self.assertRaises(ValidationError):
            record_phase_dispatch_batch(self.repo, task_id, "p1", [r])

    def test_PHASE_EXEC_006_retry_preserves_id(self) -> None:
        """PHASE_EXEC_006: retry preserves execution ID."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        r = reviewers[0]
        record_phase_dispatch_batch(self.repo, task_id, "p1", reviewers)
        complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-r1",
            raw_response="invalid raw output",
            package_sha256=meta["package_sha256"],
        )
        ok, err, ledger = load_phase_ledger(task_dir(self.repo, task_id), "p1", expected_run_id=meta["phase_review_run_id"])
        self.assertTrue(ok, err)
        self.assertEqual("conv-r1", ledger["reviewers"][r]["execution_id"])

    def test_PHASE_POLICY_001_t4_data_device_elevated_risk(self) -> None:
        """PHASE_POLICY_001: T4_DATA_DEVICE is recognized as elevated phase risk."""
        import review_policy
        self.assertEqual("T4_DATA_DEVICE", review_policy.canonical_risk_tier("T4_DATA_DEVICE"))
        self.assertEqual("T4_DATA_DEVICE", review_policy.canonical_risk_tier("t4_sensitive"))
        phases = [
            {"id": "p1", "name": "Room Database Phase", "description": "Database Room Migration", "expected_files": ["app/src/main/java/com/example/AppDatabase.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        plan = read_json(task_dir(self.repo, task_id) / "plan.json")
        policy = {"risk_tier": "T4_DATA_DEVICE", "reviewers": ["bug-reviewer-agent", "regression-impact-reviewer-agent"]}
        needed, reviewers = is_phase_review_needed(self.repo, task_id, plan, phases[0], [{"path": "app/src/main/java/com/example/AppDatabase.kt"}], policy)
        self.assertTrue(needed)

    def test_PHASE_DELTA_SIZE_001_large_delta_triggers_phase_review(self) -> None:
        """PHASE_DELTA_SIZE_001: 4 files with >600 changed lines triggers review."""
        phases = [
            {"id": "p1", "name": "Feature Core", "description": "Feature core implementation", "expected_files": [
                "app/src/main/java/com/example/F1.kt",
                "app/src/main/java/com/example/F2.kt",
                "app/src/main/java/com/example/F3.kt",
                "app/src/main/java/com/example/F4.kt",
            ]},
            {"id": "p2", "name": "Feature UI", "description": "Feature UI implementation", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=None)
        for i in range(1, 5):
            content = "package com.example\n" + "".join(f"class Class{i}_{j} {{\n  fun doWork() = {j}\n}}\n" for j in range(50))
            write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / f"F{i}.kt", content)

        plan = read_json(task_dir(self.repo, task_id) / "plan.json")
        changes = [{"path": f"app/src/main/java/com/example/F{i}.kt"} for i in range(1, 5)]
        needed, reviewers = is_phase_review_needed(self.repo, task_id, plan, phases[0], changes)
        self.assertTrue(needed, "4 files with >600 lines must trigger phase review even without explicit flag")

    def test_PHASE_HOST_E2E_001_complete_lifecycle(self) -> None:
        """PHASE_HOST_E2E_001: complete phase review host lifecycle E2E."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r]} for r in reviewers]

        code, res = self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})
        self.assertEqual(0, code)
        self.assertEqual("allow", res.get("decision"))

        plan = read_json(task_dir(self.repo, task_id) / "plan.json")
        self.assertGreaterEqual(plan.get("review_calls_used", 0), len(reviewers))

        pkg_sha = meta["package_sha256"]
        run_id = meta["phase_review_run_id"]
        for idx, r in enumerate(reviewers):
            conv_id = f"conv-e2e-{idx}"
            valid_review_result = {
                "schema_version": 2,
                "task_id": task_id,
                "run_id": run_id,
                "reviewer": r,
                "review_package_sha256": pkg_sha,
                "verdict": "PASS",
                "findings": [],
            }
            raw = f"Review done.\n```json\n{json.dumps(valid_review_result)}\n```\n"
            complete_phase_review(
                repo=self.repo,
                task_id=task_id,
                phase_id="p1",
                reviewer=r,
                execution_id=conv_id,
                raw_response=raw,
                package_sha256=pkg_sha,
            )

        act_fin = resolve_next_action(self.repo, task_id)
        self.assertEqual("FINALIZE_PHASE_REVIEW", act_fin["code"])

        fin = finalize_phase_review(self.repo, task_id, "p1")
        self.assertEqual("PASS", fin["verdict"])

        act_next = resolve_next_action(self.repo, task_id)
        self.assertEqual("BEGIN_NEXT_PHASE", act_next["code"])

    def test_PHASE_HOST_E2E_002_launch_failure_lifecycle(self) -> None:
        """PHASE_HOST_E2E_002: launch failure lifecycle E2E."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r]} for r in reviewers]
        self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})

        self._run_post_tool_reconcile({
            "toolCall": {"name": "invoke_subagent", "args": {"Subagents": subagents}},
            "error": "Failed to launch subagent: connection timeout",
        })

        act = resolve_next_action(self.repo, task_id)
        self.assertEqual("PHASE_REVIEW_ENV_BLOCKED", act["code"])
        self.assertNotEqual("WAIT_FOR_PHASE_REVIEWERS", act["code"])

    def test_PHASE_HOST_E2E_003_protocol_retry_lifecycle(self) -> None:
        """PHASE_HOST_E2E_003: protocol retry lifecycle E2E."""
        task_id, reviewers, briefs, meta = self._setup_dispatch_state()
        subagents = [{"TypeName": r, "Role": r, "Prompt": briefs[r]} for r in reviewers]
        self._run_pre_tool_safety({"toolName": "invoke_subagent", "toolArgs": {"Subagents": subagents}})

        r = reviewers[0]
        ret = complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-retry-01",
            raw_response="No JSON code block here.",
            package_sha256=meta["package_sha256"],
        )
        self.assertEqual("PROTOCOL_RETRY_REQUIRED", ret["status"])

        act_retry = resolve_next_action(self.repo, task_id)
        self.assertEqual("RETRY_PHASE_REVIEW_PROTOCOL", act_retry["code"])

        code, res = self._run_pre_tool_safety({
            "toolName": "send_message",
            "toolArgs": {"Recipient": "conv-retry-01", "Message": act_retry["retry_prompt"]}
        })
        self.assertEqual("allow", res.get("decision"))

        valid_result = {
            "schema_version": 2,
            "task_id": task_id,
            "run_id": meta["phase_review_run_id"],
            "reviewer": r,
            "review_package_sha256": meta["package_sha256"],
            "verdict": "PASS",
            "findings": [],
        }
        res_pass = complete_phase_review(
            repo=self.repo,
            task_id=task_id,
            phase_id="p1",
            reviewer=r,
            execution_id="conv-retry-01",
            raw_response=f"```json\n{json.dumps(valid_result)}\n```",
            package_sha256=meta["package_sha256"],
        )
        self.assertEqual("PASS", res_pass["verdict"])


if __name__ == "__main__":
    unittest.main()
