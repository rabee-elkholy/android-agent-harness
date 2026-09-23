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
        is_phase_review_needed,
        build_phase_package,
        complete_phase_review,
        finalize_phase_review,
        format_phase_provenance_section,
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

    def _create_phased_task(self, phases: list[dict], kind: str = "FEATURE", scoped_phase_review: bool | None = None) -> str:
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
        self.assertIn(act["code"], ("BEGIN_NEXT_PHASE", "IMPLEMENT_APPROVED_SCOPE"))

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
        """PHASE_V2_013: protocol retry via send_message does not increment review_calls_used."""
        phases = [
            {"id": "p1", "name": "Phase 1", "description": "Auth Phase", "expected_files": ["app/src/main/java/com/example/Auth.kt"]},
            {"id": "p2", "name": "Phase 2", "description": "UI Phase", "expected_files": ["app/src/main/java/com/example/UI.kt"]},
        ]
        task_id = self._create_phased_task(phases, scoped_phase_review=True)
        write_file(self.repo / "app" / "src" / "main" / "java" / "com" / "example" / "Auth.kt", "package com.example\nclass Auth\n")
        self._pass_phase_tests(task_id, "p1")
        checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id=task_id, phase_id="p1"))
        _, meta = build_phase_package(self.repo, task_id, "p1")

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
        self.assertEqual("RETRY_REVIEW_PROTOCOL", act["code"])
        self.assertIn("send_message", act.get("command", "") or act.get("action", ""))

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


if __name__ == "__main__":
    unittest.main()
