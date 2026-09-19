"""Public CLI acceptance tests for external command contracts.

Verifies the exact CLI entrypoints that agents execute via subprocess.
Covers P0 regression cases P0-T1 through P0-T5:
- P0-T1: review_policy.py public CLI execution without NameError/traceback.
- P0-T2: run_gradle_task.py assembleDebug blocked when reviewers missing.
- P0-T3: run_gradle_task.py assembleDebug allowed when review evidence is valid.
- P0-T4: run_gradle_task.py assembleDebug fails closed on malformed/stale/incomplete reviews.
- P0-T5: CLI sanity for version, doctor, and change_classifier.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import atomic_write_json, canonical_sha256, utc_now  # noqa: E402
from evidence_store import EvidenceStore  # noqa: E402

KIT = Path(__file__).resolve().parents[2]


def run_git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {repo}:\n{proc.stderr}\n{proc.stdout}")


def _make_executable(path: Path) -> None:
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _setup_fake_gradlew(repo: Path) -> Path:
    sentinel = repo / ".gradle_was_executed"
    if sentinel.is_file():
        sentinel.unlink()

    # Unix wrapper
    unix_script = repo / "gradlew"
    unix_script.write_text(
        "#!/bin/sh\n"
        "echo executed > .gradle_was_executed\n"
        "mkdir -p app/build/outputs/apk/debug\n"
        "echo apk > app/build/outputs/apk/debug/app-debug.apk\n"
        "exit 0\n",
        encoding="utf-8",
    )
    _make_executable(unix_script)

    # Windows batch wrapper
    win_script = repo / "gradlew.bat"
    win_script.write_text(
        "@echo off\r\n"
        "echo executed > .gradle_was_executed\r\n"
        "if not exist app\\build\\outputs\\apk\\debug mkdir app\\build\\outputs\\apk\\debug\r\n"
        "echo apk > app\\build\\outputs\\apk\\debug\\app-debug.apk\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
    )
    return sentinel


class PublicCliSelftest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="public_cli_test_")
        self.repo = Path(self.temp_dir.name).resolve()

        # Git init
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Public CLI Test")
        run_git(self.repo, "config", "user.email", "test@example.invalid")
        run_git(self.repo, "config", "core.autocrlf", "false")

        # Minimal Android repo layout
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example").mkdir(parents=True, exist_ok=True)
        (self.repo / "app" / "src" / "main" / "res" / "values").mkdir(parents=True, exist_ok=True)
        (self.repo / "settings.gradle.kts").write_text('rootProject.name = "TestApp"\ninclude(":app")\n', encoding="utf-8")
        (self.repo / "app" / "build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
        (self.repo / "app" / "src" / "main" / "res" / "values" / "strings.xml").write_text(
            '<resources>\n    <string name="app_name">TestApp</string>\n</resources>\n',
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "MainActivity.kt").write_text(
            "package com.example\n\nclass MainActivity\n",
            encoding="utf-8",
        )
        (self.repo / "agents").mkdir(parents=True, exist_ok=True)
        (self.repo / "agents" / "VERSION").write_text("1.0.48\n", encoding="utf-8")

        # Initial commit
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "initial commit")

        # Setup ownership manifest
        from lifecycle import SCHEMA_VERSION, ARCHITECTURE_MAJOR, OWNERSHIP_RELATIVE, EXCLUDE_BEGIN, EXCLUDE_END
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "architecture_major": ARCHITECTURE_MAJOR,
            "harness_version": "1.0.48",
            "installed_at": utc_now(),
            "install_backup": None,
            "latest_backup": None,
            "managed_exclude_block": {"begin": EXCLUDE_BEGIN, "end": EXCLUDE_END},
            "entries": [],
        }
        manifest["ownership_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "ownership_sha256"})
        atomic_write_json(self.repo / OWNERSHIP_RELATIVE, manifest)
        answers_path = self.repo / ".harness-setup" / "answers.json"
        answers_path.parent.mkdir(parents=True, exist_ok=True)
        answers_path.write_text(json.dumps({"confirm_installation": True, "target_branch": "main"}), encoding="utf-8")

        # Copy skills from kit if available
        kit_skills = KIT / "agents" / "skills"
        if kit_skills.is_dir():
            shutil.copytree(kit_skills, self.repo / ".agents" / "skills", dirs_exist_ok=True)

        self.env = dict(os.environ)
        self.env["HARNESS_REPO"] = str(self.repo)
        self.env["PYTHONUNBUFFERED"] = "1"
        self.env["PYTHONIOENCODING"] = "utf-8"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # P0-T1: review_policy.py public CLI
    # -------------------------------------------------------------------------

    def test_p0_t1_review_policy_public_cli_json(self) -> None:
        """P0-T1: python review_policy.py --repo <fixture> --json executes without traceback and yields valid policy JSON."""
        script = KIT / "agents" / "scripts" / "review_policy.py"
        self.assertTrue(script.is_file(), f"review_policy.py missing at {script}")

        # Modify a file to create a delivery change
        target_file = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "MainActivity.kt"
        target_file.write_text("package com.example\n\nclass MainActivity {\n    val greeting = \"hello\"\n}\n", encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(script), "--repo", str(self.repo), "--json"],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

        self.assertNotIn("NameError", proc.stderr, f"review_policy raised NameError: {proc.stderr}")
        self.assertNotIn("Traceback", proc.stderr, f"review_policy raised Traceback: {proc.stderr}")
        self.assertEqual(0, proc.returncode, f"review_policy failed with exit code {proc.returncode}:\n{proc.stderr}\n{proc.stdout}")

        # Stdout must contain valid JSON policy payload
        raw = proc.stdout.strip()
        json_start = raw.find("{")
        self.assertNotEqual(-1, json_start, f"No JSON object found in output: {raw}")
        policy_data = json.loads(raw[json_start:])

        self.assertIn("surfaces", policy_data)
        self.assertIn("gates", policy_data)
        self.assertIn("reviewers", policy_data)
        self.assertIn("policy_sha256", policy_data)
        self.assertIn(policy_data.get("status"), ("PASS", "USER_DECISION_REQUIRED", "BLOCKED"))

    def test_p0_t1_review_policy_public_cli_plain(self) -> None:
        """P0-T1 (b): Plain output mode for review_policy.py contains expected policy lines."""
        script = KIT / "agents" / "scripts" / "review_policy.py"

        # Modify a file to create a delivery change
        target_file = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "MainActivity.kt"
        target_file.write_text("package com.example\n\nclass MainActivity {\n    val title = \"hello\"\n}\n", encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(script), "--repo", str(self.repo)],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc.returncode, f"Plain mode failed:\n{proc.stderr}\n{proc.stdout}")
        self.assertIn("POLICY_STATUS=", proc.stdout)
        self.assertIn("REVIEWERS=", proc.stdout)
        self.assertIn("GATES=", proc.stdout)

    # -------------------------------------------------------------------------
    # P0-T2: Assemble gate blocks when reviews missing
    # -------------------------------------------------------------------------

    def _setup_verifying_task(
        self,
        task_id: str = "task-001",
        reviewers: list[str] | None = None,
        snapshot: str = "snap1234567890abcdef1234567890abcdef",
        run_id: str = "run-001",
        change_set: str = "cs1234567890abcdef1234567890abcdef",
    ) -> tuple[Path, Path]:
        state_dir = self.repo / ".agents" / "state"
        task_dir = state_dir / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        if reviewers is None:
            reviewers = ["bug-reviewer-agent"]

        policy_obj = {
            "schema_version": 1,
            "status": "PASS",
            "reviewers": reviewers,
            "gates": ["preflight", "unit_tests", "assemble", "device"],
            "device_required": True,
            "classification_sha256": "fake_class_sha",
            "policy_sha256": "fake_pol_sha",
        }
        policy_path = task_dir / "policy.json"
        policy_path.write_text(json.dumps(policy_obj, indent=2), encoding="utf-8")

        # active-task.json
        (state_dir / "active-task.json").write_text(
            json.dumps({"schema_version": 1, "task_id": task_id}, indent=2),
            encoding="utf-8",
        )

        # plan.json with VERIFYING status
        plan_obj = {
            "schema_version": 1,
            "task_id": task_id,
            "status": "VERIFYING",
            "execution_nonce": "nonce123",
        }
        (task_dir / "plan.json").write_text(json.dumps(plan_obj, indent=2), encoding="utf-8")

        # current-run.json
        current_run_obj = {
            "schema_version": 1,
            "run_id": run_id,
            "snapshot": snapshot,
            "delivery_snapshot_sha256": snapshot,
            "change_set_sha256": change_set,
            "policy": str(policy_path),
        }
        (task_dir / "current-run.json").write_text(
            json.dumps(current_run_obj, indent=2),
            encoding="utf-8",
        )

        return state_dir, policy_path

    def test_p0_t2_reviewer_gate_blocks_assemble_when_reviews_missing(self) -> None:
        """P0-T2: Assemble gate fails closed and does not run Gradle when required reviews are missing."""
        sentinel = _setup_fake_gradlew(self.repo)
        self._setup_verifying_task(task_id="assemble-block-test", reviewers=["bug-reviewer-agent"])

        script = KIT / "agents" / "scripts" / "run_gradle_task.py"
        proc = subprocess.run(
            [sys.executable, str(script), ":app:assembleDebug"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

        self.assertNotEqual(0, proc.returncode, "Assemble must not exit 0 when reviews missing")
        self.assertFalse(sentinel.exists(), "Gradle wrapper must not execute when reviews missing")
        combined = proc.stdout + proc.stderr
        self.assertIn("Pipeline order violation", combined)

    # -------------------------------------------------------------------------
    # P0-T3: Assemble gate allows assemble after valid reviews
    # -------------------------------------------------------------------------

    def test_p0_t3_reviewer_gate_allows_assemble_after_valid_review(self) -> None:
        """P0-T3: Assemble gate allows Gradle execution when valid review evidence is present."""
        sentinel = _setup_fake_gradlew(self.repo)
        snapshot = "snap1234567890abcdef1234567890abcdef"
        run_id = "run-001"
        change_set = "cs1234567890abcdef1234567890abcdef"
        state_dir, _ = self._setup_verifying_task(
            task_id="assemble-pass-test",
            reviewers=["bug-reviewer-agent"],
            snapshot=snapshot,
            run_id=run_id,
            change_set=change_set,
        )

        # Write authentic review evidence using EvidenceStore
        store = EvidenceStore(state_dir)
        store.write(
            snapshot=snapshot,
            run_id=run_id,
            name="reviews",
            producer="review_orchestrator",
            harness_version="1.0.48",
            change_set=change_set,
            status="PASS",
            evidence={
                "reviewers": ["bug-reviewer-agent"],
                "blocking_findings": [],
                "reports": [{"reviewer": "bug-reviewer-agent", "status": "PASS"}],
            },
        )

        script = KIT / "agents" / "scripts" / "run_gradle_task.py"
        proc = subprocess.run(
            [sys.executable, str(script), ":app:assembleDebug"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

        self.assertEqual(0, proc.returncode, f"Assemble failed unexpectedly:\n{proc.stdout}\n{proc.stderr}")
        self.assertTrue(sentinel.exists(), "Gradle wrapper should have executed and created sentinel")

    # -------------------------------------------------------------------------
    # P0-T4: Malformed/stale/incomplete review evidence fails closed
    # -------------------------------------------------------------------------

    def test_p0_t4_incomplete_reviewer_coverage_fails_closed(self) -> None:
        """P0-T4 (a): Incomplete reviewer coverage blocks assemble and does not run Gradle."""
        sentinel = _setup_fake_gradlew(self.repo)
        snapshot = "snap1234567890abcdef1234567890abcdef"
        run_id = "run-002"
        change_set = "cs1234567890abcdef1234567890abcdef"
        state_dir, _ = self._setup_verifying_task(
            task_id="incomplete-rev-test",
            reviewers=["bug-reviewer-agent", "security-reviewer-agent"],
            snapshot=snapshot,
            run_id=run_id,
            change_set=change_set,
        )

        # Only one reviewer covered
        store = EvidenceStore(state_dir)
        store.write(
            snapshot=snapshot,
            run_id=run_id,
            name="reviews",
            producer="review_orchestrator",
            harness_version="1.0.48",
            change_set=change_set,
            status="PASS",
            evidence={
                "reviewers": ["bug-reviewer-agent"],
                "blocking_findings": [],
            },
        )

        script = KIT / "agents" / "scripts" / "run_gradle_task.py"
        proc = subprocess.run(
            [sys.executable, str(script), ":app:assembleDebug"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

        self.assertNotEqual(0, proc.returncode)
        self.assertFalse(sentinel.exists(), "Gradle must not execute when reviewer coverage is incomplete")
        self.assertIn("Incomplete reviewer coverage", proc.stdout + proc.stderr)

    def test_p0_t4_blocking_findings_fail_closed(self) -> None:
        """P0-T4 (b): Reviews with blocking findings fail closed and block assemble."""
        sentinel = _setup_fake_gradlew(self.repo)
        snapshot = "snap1234567890abcdef1234567890abcdef"
        run_id = "run-003"
        change_set = "cs1234567890abcdef1234567890abcdef"
        state_dir, _ = self._setup_verifying_task(
            task_id="blocking-find-test",
            reviewers=["bug-reviewer-agent"],
            snapshot=snapshot,
            run_id=run_id,
            change_set=change_set,
        )

        store = EvidenceStore(state_dir)
        store.write(
            snapshot=snapshot,
            run_id=run_id,
            name="reviews",
            producer="review_orchestrator",
            harness_version="1.0.48",
            change_set=change_set,
            status="PASS",
            evidence={
                "reviewers": ["bug-reviewer-agent"],
                "blocking_findings": [{"reviewer": "bug-reviewer-agent", "finding": "NPE in profile"}],
            },
        )

        script = KIT / "agents" / "scripts" / "run_gradle_task.py"
        proc = subprocess.run(
            [sys.executable, str(script), ":app:assembleDebug"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

        self.assertNotEqual(0, proc.returncode)
        self.assertFalse(sentinel.exists(), "Gradle must not execute when reviews contain blocking findings")
        self.assertIn("blocking findings", proc.stdout + proc.stderr)

    def test_p0_t4_malformed_evidence_file_fails_closed(self) -> None:
        """P0-T4 (c): Corrupted reviews evidence fails closed."""
        sentinel = _setup_fake_gradlew(self.repo)
        snapshot = "snap1234567890abcdef1234567890abcdef"
        run_id = "run-004"
        change_set = "cs1234567890abcdef1234567890abcdef"
        state_dir, _ = self._setup_verifying_task(
            task_id="corrupt-ev-test",
            reviewers=["bug-reviewer-agent"],
            snapshot=snapshot,
            run_id=run_id,
            change_set=change_set,
        )

        rev_file = state_dir / "runs" / snapshot / run_id / "reviews.json"
        rev_file.parent.mkdir(parents=True, exist_ok=True)
        rev_file.write_text("{ corrupt json !! }", encoding="utf-8")

        script = KIT / "agents" / "scripts" / "run_gradle_task.py"
        proc = subprocess.run(
            [sys.executable, str(script), ":app:assembleDebug"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

        self.assertNotEqual(0, proc.returncode)
        self.assertFalse(sentinel.exists(), "Gradle must not execute when reviews evidence is corrupt")

    # -------------------------------------------------------------------------
    # Non-verifying or no active task cases
    # -------------------------------------------------------------------------

    def test_assemble_allowed_when_no_active_task(self) -> None:
        """Assemble runs normally when there is no active task."""
        sentinel = _setup_fake_gradlew(self.repo)
        script = KIT / "agents" / "scripts" / "run_gradle_task.py"
        proc = subprocess.run(
            [sys.executable, str(script), ":app:assembleDebug"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc.returncode)
        self.assertTrue(sentinel.exists(), "Gradle must run when no active task exists")

    def test_assemble_allowed_when_task_in_implementing_status(self) -> None:
        """Assemble runs when task is IMPLEMENTING, not yet in VERIFYING."""
        sentinel = _setup_fake_gradlew(self.repo)
        state_dir = self.repo / ".agents" / "state"
        task_dir = state_dir / "tasks" / "impl-task"
        task_dir.mkdir(parents=True, exist_ok=True)

        (state_dir / "active-task.json").write_text(json.dumps({"task_id": "impl-task"}), encoding="utf-8")
        (task_dir / "plan.json").write_text(json.dumps({"task_id": "impl-task", "status": "IMPLEMENTING"}), encoding="utf-8")

        script = KIT / "agents" / "scripts" / "run_gradle_task.py"
        proc = subprocess.run(
            [sys.executable, str(script), ":app:assembleDebug"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc.returncode)
        self.assertTrue(sentinel.exists(), "Gradle must run when task is in IMPLEMENTING status")

    # -------------------------------------------------------------------------
    # P0-T5: Public CLI dispatch sanity
    # -------------------------------------------------------------------------

    def test_p0_t5_public_cli_sanity(self) -> None:
        """P0-T5: harness_cli.py version, doctor --json, and change_classifier execute cleanly."""
        harness_cli = KIT / "harness_cli.py"
        classifier = KIT / "agents" / "scripts" / "change_classifier.py"

        # version
        proc_ver = subprocess.run(
            [sys.executable, str(harness_cli), "version"],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc_ver.returncode)
        self.assertTrue(len(proc_ver.stdout.strip()) > 0)

        # doctor --json
        proc_doc = subprocess.run(
            [sys.executable, str(harness_cli), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertIn(proc_doc.returncode, (0, 1, 2))
        raw_doc = proc_doc.stdout.strip()
        start = raw_doc.find("{")
        self.assertNotEqual(-1, start, f"No JSON found in doctor output:\nstdout: {proc_doc.stdout}\nstderr: {proc_doc.stderr}")
        doc_json = json.loads(raw_doc[start:])
        self.assertIn("checks", doc_json)

        # change_classifier --json
        proc_class = subprocess.run(
            [sys.executable, str(classifier), "--repo", str(self.repo), "--json"],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc_class.returncode)
        raw_class = proc_class.stdout.strip()
        start_c = raw_class.find("{")
        self.assertNotEqual(-1, start_c, f"No JSON found in classifier output:\n{proc_class.stdout}")
        class_json = json.loads(raw_class[start_c:])
        self.assertIn("surfaces", class_json)

    def test_task_context_public_cli_json(self) -> None:
        """The public task-context command returns bounded, read-only JSON."""
        harness_cli = KIT / "harness_cli.py"
        (self.repo / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
        target = "app/src/main/kotlin/com/example/MainActivity.kt"
        cache = self.repo / ".agents" / "cache" / "project-graph.json"
        before = cache.read_bytes() if cache.is_file() else None
        proc = subprocess.run(
            [
                sys.executable,
                str(harness_cli),
                "task-context",
                "--repo",
                str(self.repo),
                "--kit",
                str(KIT),
                "--file",
                target,
                "--json",
            ],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc.returncode, f"{proc.stderr}\n{proc.stdout}")
        payload = json.loads(proc.stdout)
        self.assertEqual("RESOLVED", payload["status"])
        self.assertEqual(target, payload["target"]["path"])
        after = cache.read_bytes() if cache.is_file() else None
        self.assertEqual(before, after, "task-context must not write the persistent graph cache")


class PhaseBLeanWorkflowSelftest(unittest.TestCase):
    """Phase B acceptance tests: Risk lanes, proportional device, adaptive graph, multi-phase threshold."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="phase_b_test_")
        self.repo = Path(self.temp_dir.name).resolve()
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Phase B Test")
        run_git(self.repo, "config", "user.email", "phaseb@example.invalid")
        run_git(self.repo, "config", "core.autocrlf", "false")
        (self.repo / "settings.gradle.kts").write_text('rootProject.name = "PhaseBTest"\n', encoding="utf-8")
        _setup_fake_gradlew(self.repo)
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "initial commit")

        self.skills_root = KIT / "agents" / "skills"
        self.env = {**os.environ, "HARNESS_REPO": str(self.repo)}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_p1_b1_b2_risk_lanes_and_proportional_device(self) -> None:
        """P1-B1 & B2: Proportional risk lanes (MICRO/STANDARD/CRITICAL) and UI verification classes."""
        import review_policy

        # Case 1: Compose padding-only (VISUAL_MICRO)
        cls_pad = {
            "surfaces": ["COMPOSE_UI"],
            "severity": "LOW",
            "changed_files": 1,
            "changed_lines": 5,
            "has_delete_or_rename": False,
        }
        pol_pad = review_policy.decide(cls_pad, self.skills_root, project_kind="application")
        self.assertEqual("MICRO", pol_pad["risk_lane"])
        self.assertEqual("VISUAL_MICRO", pol_pad["ui_verification_class"])
        self.assertFalse(pol_pad["device_required"])
        self.assertEqual([], pol_pad["reviewers"])
        self.assertNotIn("unit_tests", pol_pad["gates"])
        self.assertNotIn("device", pol_pad["gates"])

        # Case 2: Drawable-only (VISUAL_MICRO)
        cls_draw = {
            "surfaces": ["RESOURCE_UI"],
            "severity": "LOW",
            "changed_files": 1,
            "changed_lines": 12,
            "has_delete_or_rename": False,
        }
        pol_draw = review_policy.decide(cls_draw, self.skills_root, project_kind="application")
        self.assertEqual("MICRO", pol_draw["risk_lane"])
        self.assertEqual("VISUAL_MICRO", pol_draw["ui_verification_class"])
        self.assertFalse(pol_draw["device_required"])
        self.assertEqual([], pol_draw["reviewers"])

        # Case 3: Compose click invoking ViewModel (UI_BEHAVIOR -> STANDARD)
        cls_click = {
            "surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"],
            "severity": "MEDIUM",
            "changed_files": 2,
            "changed_lines": 25,
            "has_delete_or_rename": False,
        }
        pol_click = review_policy.decide(cls_click, self.skills_root, project_kind="application")
        self.assertEqual("STANDARD", pol_click["risk_lane"])
        self.assertEqual("UI_BEHAVIOR", pol_click["ui_verification_class"])
        self.assertTrue(pol_click["device_required"])
        self.assertEqual(["bug-reviewer-agent", "regression-impact-reviewer-agent"], pol_click["reviewers"])
        self.assertNotIn("convention-reviewer-agent", pol_click["reviewers"])
        self.assertIn("unit_tests", pol_click["gates"])
        self.assertIn("device", pol_click["gates"])

        # Case 4: Navigation route behavior (UI_BEHAVIOR)
        cls_nav = {
            "surfaces": ["NAVIGATION"],
            "severity": "MEDIUM",
            "changed_files": 1,
            "changed_lines": 15,
            "has_delete_or_rename": False,
        }
        pol_nav = review_policy.decide(cls_nav, self.skills_root, project_kind="application")
        self.assertEqual("STANDARD", pol_nav["risk_lane"])
        self.assertEqual("UI_BEHAVIOR", pol_nav["ui_verification_class"])
        self.assertTrue(pol_nav["device_required"])
        self.assertIn("bug-reviewer-agent", pol_nav["reviewers"])
        self.assertNotIn("convention-reviewer-agent", pol_nav["reviewers"])

        # Case 5: Foreground service (DEVICE_BEHAVIOR)
        cls_fg = {
            "surfaces": ["DEVICE_API"],
            "severity": "MEDIUM",
            "changed_files": 1,
            "changed_lines": 20,
            "has_delete_or_rename": False,
        }
        pol_fg = review_policy.decide(cls_fg, self.skills_root, project_kind="application")
        self.assertEqual("DEVICE_BEHAVIOR", pol_fg["ui_verification_class"])
        self.assertTrue(pol_fg["device_required"])

        # Case 6: Billing / Auth (DEVICE_BEHAVIOR -> CRITICAL)
        cls_bill = {
            "surfaces": ["BILLING"],
            "severity": "CRITICAL",
            "changed_files": 1,
            "changed_lines": 30,
            "has_delete_or_rename": False,
        }
        pol_bill = review_policy.decide(cls_bill, self.skills_root, project_kind="application")
        self.assertEqual("CRITICAL", pol_bill["risk_lane"])
        self.assertEqual("DEVICE_BEHAVIOR", pol_bill["ui_verification_class"])
        self.assertTrue(pol_bill["device_required"])
        self.assertEqual(5, len(pol_bill["reviewers"]))

        # Case 7: Pure business logic (NONE)
        cls_logic = {
            "surfaces": ["BUSINESS_LOGIC"],
            "severity": "MEDIUM",
            "changed_files": 1,
            "changed_lines": 15,
            "has_delete_or_rename": False,
        }
        pol_logic = review_policy.decide(cls_logic, self.skills_root, project_kind="application")
        self.assertEqual("STANDARD", pol_logic["risk_lane"])
        self.assertEqual("NONE", pol_logic["ui_verification_class"])
        self.assertFalse(pol_logic["device_required"])

        # Case 8: Architectural planning depth adds convention & spec-compliance
        pol_arch = review_policy.decide(
            cls_click, self.skills_root, project_kind="application",
            plan={"planning_depth": "ARCHITECTURAL"}
        )
        self.assertIn("convention-reviewer-agent", pol_arch["reviewers"])
        self.assertIn("spec-compliance-agent", pol_arch["reviewers"])

    def test_p1_b2_cli_policy_output_fields(self) -> None:
        """P1-B2 (b): Public CLI returns RISK_LANE and UI_VERIFICATION_CLASS in plain text and JSON."""
        rev_policy = KIT / "agents" / "scripts" / "review_policy.py"

        # JSON mode
        proc_json = subprocess.run(
            [sys.executable, str(rev_policy), "--repo", str(self.repo), "--json"],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc_json.returncode, proc_json.stderr)
        data = json.loads(proc_json.stdout)
        self.assertIn("risk_lane", data)
        self.assertIn("ui_verification_class", data)

        # Plain text mode
        proc_plain = subprocess.run(
            [sys.executable, str(rev_policy), "--repo", str(self.repo)],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc_plain.returncode, proc_plain.stderr)
        self.assertIn("RISK_LANE=", proc_plain.stdout)
        self.assertIn("UI_VERIFICATION_CLASS=", proc_plain.stdout)

    def test_p1_b3_adaptive_project_graph(self) -> None:
        """P1-B3: pre_tool_safety permits direct targeted searches without project graph."""
        safety_script = KIT / "agents" / "scripts" / "pre_tool_safety.py"

        def _invoke_hook(tool_name: str, tool_args: dict) -> dict:
            payload = json.dumps({"toolName": tool_name, "toolArgs": tool_args})
            proc = subprocess.run(
                [sys.executable, str(safety_script)],
                input=payload,
                capture_output=True,
                text=True,
                env=self.env,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            return json.loads(proc.stdout.strip())

        # 1. Exact file pattern search via find_by_name -> allowed
        res1 = _invoke_hook("find_by_name", {"SearchDirectory": ".", "Pattern": "ProfileViewModel.kt"})
        self.assertEqual("allow", res1["decision"])

        # 2. Exact file path search via grep_search -> allowed
        res2 = _invoke_hook("grep_search", {"SearchPath": "app/src/main/kotlin/ProfileViewModel.kt", "Query": "validateAge"})
        self.assertEqual("allow", res2["decision"])

        # 3. Exact feature directory search via grep_search -> allowed
        res3 = _invoke_hook("grep_search", {"SearchPath": "app/src/main/kotlin/feature/profile", "Query": "validateAge"})
        self.assertEqual("allow", res3["decision"])

        # 4. Unanchored repository-wide grep without graph -> denied (GRAPH_FIRST_REQUIRED)
        res4 = _invoke_hook("grep_search", {"SearchPath": ".", "Query": "validateAge"})
        self.assertEqual("deny", res4["decision"])
        self.assertIn("project_graph.py", res4["reason"])

        # 5. Unanchored repository-wide wildcard find without graph -> denied
        res5 = _invoke_hook("find_by_name", {"SearchDirectory": ".", "Pattern": "*.kt"})
        self.assertEqual("deny", res5["decision"])
        self.assertIn("project_graph.py", res5["reason"])

    def test_p1_b4_multi_phase_threshold(self) -> None:
        """P1-B4: Clean Architecture multi-file features stay single-phase; multi-module/migration requires phases."""
        import workflow
        from _vnext_common import ValidationError

        # 1. Normal Clean Architecture feature (5 files in single module) -> Single phase allowed
        clean_arch_files = [
            "app/src/main/kotlin/com/example/ui/ProfileScreen.kt",
            "app/src/main/kotlin/com/example/presentation/ProfileViewModel.kt",
            "app/src/main/kotlin/com/example/domain/GetProfileUseCase.kt",
            "app/src/main/kotlin/com/example/domain/ProfileRepository.kt",
            "app/src/main/kotlin/com/example/data/ProfileRepositoryImpl.kt",
        ]
        args_clean = argparse.Namespace(
            repo=str(self.repo),
            task_id="task-clean-arch",
            outcome="Add profile screen and repository",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces="COMPOSE_UI,BUSINESS_LOGIC",
            expected_modules="app",
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files=",".join(clean_arch_files),
            phases=None,
            force=False,
        )
        # Should NOT raise PHASE_PLAN_REQUIRED
        workflow.draft(args_clean)

        # 2. Multi-module feature without phases -> raises PHASE_PLAN_REQUIRED
        multi_module_files = [
            "app/src/main/kotlin/com/example/ui/HomeScreen.kt",
            "core/data/src/main/kotlin/com/example/data/HomeRepository.kt",
        ]
        args_multi = argparse.Namespace(
            repo=str(self.repo),
            task_id="task-multi-module",
            outcome="Add home cross-module feature",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces="COMPOSE_UI,BUSINESS_LOGIC",
            expected_modules="app,core:data",
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files=",".join(multi_module_files),
            phases=None,
            force=False,
        )
        with self.assertRaises(ValidationError) as ctx_multi:
            workflow.draft(args_multi)
        self.assertIn("PHASE_PLAN_REQUIRED", str(ctx_multi.exception))

        # 3. Architectural migration without phases -> raises PHASE_PLAN_REQUIRED
        args_mig = argparse.Namespace(
            repo=str(self.repo),
            task_id="task-arch-mig",
            outcome="Migrate storage layer",
            kind="FEATURE",
            planning_depth="ARCHITECTURAL",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app",
            architecture_intent="MIGRATION",
            architecture_target_scope="app",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/Store.kt",
            phases=None,
            force=False,
        )
        with self.assertRaises(ValidationError) as ctx_mig:
            workflow.draft(args_mig)
        self.assertIn("PHASE_PLAN_REQUIRED", str(ctx_mig.exception))

        # 4. Large implementation (> 8 files) without phases -> raises PHASE_PLAN_REQUIRED
        large_files = [f"app/src/main/kotlin/com/example/F{i}.kt" for i in range(10)]
        args_large = argparse.Namespace(
            repo=str(self.repo),
            task_id="task-large-impl",
            outcome="Massive refactor",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app",
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files=",".join(large_files),
            phases=None,
            force=False,
        )
        with self.assertRaises(ValidationError) as ctx_large:
            workflow.draft(args_large)
        self.assertIn("PHASE_PLAN_REQUIRED", str(ctx_large.exception))


class PhaseCSensitiveDependencySelftest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="phase_c_dep_")
        self.repo = Path(self.temp_dir.name).resolve()

        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Phase C Test")
        run_git(self.repo, "config", "user.email", "test@example.invalid")
        run_git(self.repo, "config", "core.autocrlf", "false")

        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example").mkdir(parents=True, exist_ok=True)
        # Create base files
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "BillingRepository.kt").write_text(
            "package com.example\n\nclass BillingRepository\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "UserRepository.kt").write_text(
            "package com.example\n\nclass UserRepository\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "AuthFacade.kt").write_text(
            "package com.example\n\nclass AuthFacade\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "CryptoWrapper.kt").write_text(
            "package com.example\n\nclass CryptoWrapper\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "AppModule.kt").write_text(
            "package com.example\n\nclass AppModule {\n    fun provideBilling(): BillingRepository = BillingRepository()\n}\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "OrderViewModel.kt").write_text(
            "package com.example\n\nclass OrderViewModel(\n    private val billingRepository: BillingRepository,\n) {\n    fun submitOrder() {}\n}\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "ProfileViewModel.kt").write_text(
            "package com.example\n\nclass ProfileViewModel(\n    private val userRepository: UserRepository,\n) {\n    fun loadUser() {}\n}\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "AccountViewModel.kt").write_text(
            "package com.example\n\nclass AccountViewModel(\n    private val authFacade: AuthFacade,\n) {\n    fun performAction() {}\n}\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "SecureStoreViewModel.kt").write_text(
            "package com.example\n\nclass SecureStoreViewModel(\n    private val crypto: CryptoWrapper,\n) {\n    fun save() {}\n}\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "HomeScreen.kt").write_text(
            "package com.example\n\nclass HomeScreen\n",
            encoding="utf-8",
        )
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_direct_billing_keyword_change(self) -> None:
        """Scenario 1: Direct billing keyword change produces BILLING with HIGH confidence."""
        from change_classifier import classify
        target = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "BillingRepository.kt"
        target.write_text("package com.example\n\nclass BillingRepository {\n    fun purchaseSubscription() {}\n}\n", encoding="utf-8")
        result = classify(self.repo)
        self.assertIn("BILLING", result["surfaces"])
        self.assertEqual(result["confidence"], "HIGH")

    def test_injected_billing_dependency_propagation(self) -> None:
        """Scenario 2: Enclosing class injects BillingRepository without hunk keywords -> BILLING with MEDIUM confidence."""
        from change_classifier import classify
        target = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "OrderViewModel.kt"
        target.write_text(
            "package com.example\n\nclass OrderViewModel(\n    private val billingRepository: BillingRepository,\n) {\n    fun submitOrder() {\n        val count = 1 + 1\n    }\n}\n",
            encoding="utf-8",
        )
        result = classify(self.repo)
        self.assertIn("BILLING", result["surfaces"])
        self.assertEqual(result["confidence"], "MEDIUM")
        reasons = result["details"].get("BILLING", {}).get("reasons", [])
        self.assertTrue(any("BILLING_DEPENDENCY_PROPAGATION" in reason for reason in reasons))

    def test_generic_dependency_no_billing(self) -> None:
        """Scenario 3: Generic repository (UserRepository) without sensitive keywords does NOT trigger BILLING."""
        from change_classifier import classify
        target = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "ProfileViewModel.kt"
        target.write_text(
            "package com.example\n\nclass ProfileViewModel(\n    private val userRepository: UserRepository,\n) {\n    fun loadUser() {\n        val flag = true\n    }\n}\n",
            encoding="utf-8",
        )
        result = classify(self.repo)
        self.assertNotIn("BILLING", result["surfaces"])

    def test_author_repository_does_not_false_positive_as_auth(self) -> None:
        """The common Author prefix must not be mistaken for an Auth dependency."""
        from change_classifier import classify
        target = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "BookViewModel.kt"
        target.write_text(
            "package com.example\n\nclass BookViewModel(private val authors: AuthorRepository) {\n    fun refresh() = Unit\n}\n",
            encoding="utf-8",
        )
        result = classify(self.repo)
        self.assertNotIn("AUTH", result["surfaces"])

    def test_app_module_not_propagating_as_universal_hub(self) -> None:
        """Scenario 4: AppModule references Billing globally; changing unrelated UI does not become BILLING."""
        from change_classifier import classify
        target = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "HomeScreen.kt"
        target.write_text(
            "package com.example\n\nclass HomeScreen {\n    val title = \"Home\"\n}\n",
            encoding="utf-8",
        )
        result = classify(self.repo)
        self.assertNotIn("BILLING", result["surfaces"])

    def test_injected_auth_dependency_propagation(self) -> None:
        """Scenario 5: Enclosing class injects AuthFacade -> AUTH with MEDIUM confidence."""
        from change_classifier import classify
        target = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "AccountViewModel.kt"
        target.write_text(
            "package com.example\n\nclass AccountViewModel(\n    private val authFacade: AuthFacade,\n) {\n    fun performAction() {\n        val step = 1\n    }\n}\n",
            encoding="utf-8",
        )
        result = classify(self.repo)
        self.assertIn("AUTH", result["surfaces"])
        self.assertEqual(result["confidence"], "MEDIUM")
        reasons = result["details"].get("AUTH", {}).get("reasons", [])
        self.assertTrue(any("AUTH_DEPENDENCY_PROPAGATION" in reason for reason in reasons))

    def test_injected_crypto_dependency_propagation(self) -> None:
        """Scenario 6: Enclosing class injects CryptoWrapper -> CRYPTO with MEDIUM confidence."""
        from change_classifier import classify
        target = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "SecureStoreViewModel.kt"
        target.write_text(
            "package com.example\n\nclass SecureStoreViewModel(\n    private val crypto: CryptoWrapper,\n) {\n    fun save() {\n        val cached = 42\n    }\n}\n",
            encoding="utf-8",
        )
        result = classify(self.repo)
        self.assertIn("CRYPTO", result["surfaces"])
        self.assertEqual(result["confidence"], "MEDIUM")
        reasons = result["details"].get("CRYPTO", {}).get("reasons", [])
        self.assertTrue(any("CRYPTO_DEPENDENCY_PROPAGATION" in reason for reason in reasons))


class PhaseDRepairSelftest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="phase_d_repair_")
        self.repo = Path(self.temp_dir.name).resolve()

        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Repair Test")
        run_git(self.repo, "config", "user.email", "test@example.invalid")
        run_git(self.repo, "config", "core.autocrlf", "false")

        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example").mkdir(parents=True, exist_ok=True)
        (self.repo / "app" / "src" / "main" / "res" / "values").mkdir(parents=True, exist_ok=True)
        (self.repo / "settings.gradle.kts").write_text('rootProject.name = "TestApp"\ninclude(":app")\n', encoding="utf-8")
        (self.repo / "app" / "build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
        (self.repo / "app" / "src" / "main" / "res" / "values" / "strings.xml").write_text(
            '<resources>\n    <string name="app_name">TestApp</string>\n</resources>\n',
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "MainActivity.kt").write_text(
            "package com.example\n\nclass MainActivity\n",
            encoding="utf-8",
        )
        _setup_fake_gradlew(self.repo)

        kit_version = (KIT / "agents" / "VERSION").read_text(encoding="utf-8").strip()
        (self.repo / ".agents").mkdir(parents=True, exist_ok=True)
        (self.repo / ".agents" / "VERSION").write_text(f"{kit_version}\n", encoding="utf-8")

        shutil.copytree(KIT / "agents", self.repo / ".agents", dirs_exist_ok=True)
        # Runtime state in a raw kit checkout is not installable content. Keep
        # this fixture isolated from any earlier suite that exercised the kit
        # in-place and may have left a fail-closed active-task record.
        shutil.rmtree(self.repo / ".agents" / "state", ignore_errors=True)
        (self.repo / ".agents" / "state").mkdir(parents=True, exist_ok=True)

        ctx_dir = self.repo / ".agents" / "project-context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        self.project_notes = "# Custom Domain Notes\nImportant business rules\n"
        (ctx_dir / "project-notes.md").write_text(self.project_notes, encoding="utf-8")
        from architecture_policy import create_architecture_policy
        self.arch_policy = json.dumps(create_architecture_policy(), indent=2)
        (ctx_dir / "architecture-policy.json").write_text(self.arch_policy, encoding="utf-8")

        from lifecycle import SCHEMA_VERSION, ARCHITECTURE_MAJOR, OWNERSHIP_RELATIVE, EXCLUDE_BEGIN, EXCLUDE_END
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "architecture_major": ARCHITECTURE_MAJOR,
            "harness_version": kit_version,
            "installed_at": utc_now(),
            "install_backup": None,
            "latest_backup": None,
            "managed_exclude_block": {"begin": EXCLUDE_BEGIN, "end": EXCLUDE_END},
            "entries": [],
        }
        manifest["ownership_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "ownership_sha256"})
        atomic_write_json(self.repo / OWNERSHIP_RELATIVE, manifest)
        answers_path = self.repo / ".harness-setup" / "answers.json"
        answers_path.parent.mkdir(parents=True, exist_ok=True)
        answers_path.write_text(json.dumps({"confirm_installation": True, "target_branch": "main"}), encoding="utf-8")

        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_repair_missing_managed_script(self) -> None:
        """Missing managed script under .agents/scripts/ is restored from pinned kit."""
        from repair import repair_repository
        target_script = self.repo / ".agents" / "scripts" / "workflow.py"
        self.assertTrue(target_script.is_file())
        target_script.unlink()
        self.assertFalse(target_script.is_file())

        report = repair_repository(self.repo, KIT)
        self.assertEqual(report["status"], "PASS", f"Failures: {report['doctor'].get('failure_details')}")
        self.assertTrue(target_script.is_file())
        self.assertIn(".agents/scripts/workflow.py", report["restored"]["missing"])
        self.assertEqual(
            (self.repo / ".agents" / "project-context" / "project-notes.md").read_text(encoding="utf-8"),
            self.project_notes,
        )

    def test_repair_modified_and_corrupted_script(self) -> None:
        """Modified or corrupted (0-byte/invalid syntax) script is restored."""
        from repair import repair_repository
        target_script = self.repo / ".agents" / "scripts" / "review_policy.py"
        target_script.write_text("", encoding="utf-8")

        target_rules = self.repo / ".agents" / "rules" / "harness-rules.md"
        target_rules.write_text("# Corrupted Rules\n", encoding="utf-8")

        report = repair_repository(self.repo, KIT)
        self.assertEqual(report["status"], "PASS")
        self.assertIn(".agents/scripts/review_policy.py", report["restored"]["corrupted"])
        self.assertIn(".agents/rules/harness-rules.md", report["restored"]["modified"])

        self.assertEqual(
            target_script.read_bytes(),
            (KIT / "agents" / "scripts" / "review_policy.py").read_bytes(),
        )
        self.assertEqual(
            target_rules.read_bytes(),
            (KIT / "agents" / "rules" / "harness-rules.md").read_bytes(),
        )

    def test_repair_preserves_developer_context_and_app_source(self) -> None:
        """Repair preserves project context, generated config, tracker wiring, and app source."""
        from repair import repair_repository
        app_main = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "MainActivity.kt"
        app_before_bytes = app_main.read_bytes()
        product_file = self.repo / ".agents" / "scripts" / "_product.py"
        product_bytes = b'PRODUCT_NAME = "Tailored App"\nAPPLICATION_ID = "com.example.tailored"\n'
        product_file.write_bytes(product_bytes)
        mcp_file = self.repo / ".agents" / "mcp_config.json"
        mcp_bytes = b'{"mcpServers":{"zoho":{"command":"python"}}}\n'
        mcp_file.write_bytes(mcp_bytes)
        workflow_defaults = self.repo / ".agents" / "mcp" / "zoho_sprints" / "workflow_defaults.json"
        workflow_defaults_bytes = b'{"custom_status":"Ready for QA"}\n'
        workflow_defaults.write_bytes(workflow_defaults_bytes)

        report = repair_repository(self.repo, KIT)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            (self.repo / ".agents" / "project-context" / "project-notes.md").read_text(encoding="utf-8"),
            self.project_notes,
        )
        self.assertEqual(
            (self.repo / ".agents" / "project-context" / "architecture-policy.json").read_text(encoding="utf-8"),
            self.arch_policy,
        )
        self.assertEqual(app_main.read_bytes(), app_before_bytes)
        self.assertEqual(product_file.read_bytes(), product_bytes)
        self.assertEqual(mcp_file.read_bytes(), mcp_bytes)
        self.assertEqual(workflow_defaults.read_bytes(), workflow_defaults_bytes)

    def test_repair_mismatched_kit_version_fails_closed(self) -> None:
        """Kit version mismatch does not silently repair from wrong version."""
        from repair import repair_repository
        from _vnext_common import ValidationError
        with tempfile.TemporaryDirectory(prefix="fake_kit_") as fake_kit_dir:
            fake_kit = Path(fake_kit_dir)
            shutil.copytree(KIT / "agents", fake_kit / "agents")
            (fake_kit / "agents" / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            with self.assertRaises(ValidationError) as ctx:
                repair_repository(self.repo, fake_kit)
            self.assertIn("Repair cannot silently repair from another version", str(ctx.exception))

    def test_repair_corrupted_checksum_manifest_fails_closed(self) -> None:
        """Corrupted release checksum manifest in kit fails closed."""
        from repair import repair_repository
        from _vnext_common import ValidationError
        with tempfile.TemporaryDirectory(prefix="fake_kit_corrupt_") as fake_kit_dir:
            fake_kit = Path(fake_kit_dir)
            shutil.copytree(KIT / "agents", fake_kit / "agents")
            (fake_kit / "agents" / "release_checksums.json").write_text("not-json", encoding="utf-8")
            with self.assertRaises(ValidationError) as ctx:
                repair_repository(self.repo, fake_kit)
            self.assertIn("release checksums manifest", str(ctx.exception).lower())

    def test_repair_active_task_requires_force(self) -> None:
        """Active task in PLANNED/IMPLEMENTING/VERIFYING requires --force."""
        from repair import repair_repository
        from _vnext_common import ValidationError
        task_dir = self.repo / ".agents" / "state" / "tasks" / "task-test-42"
        task_dir.mkdir(parents=True, exist_ok=True)
        plan_path = task_dir / "plan.json"
        plan_path.write_text(json.dumps({"task_id": "task-test-42", "status": "IMPLEMENTING"}), encoding="utf-8")
        active_task = self.repo / ".agents" / "state" / "active-task.json"
        active_task.parent.mkdir(parents=True, exist_ok=True)
        active_task.write_text(
            json.dumps({"task_id": "task-test-42", "plan_path": str(plan_path)}),
            encoding="utf-8",
        )

        with self.assertRaises(ValidationError) as ctx:
            repair_repository(self.repo, KIT, force=False)
        self.assertIn("Pass --force to repair while a task is active", str(ctx.exception))

        report = repair_repository(self.repo, KIT, force=True)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["active_task_detected"])

    def test_public_cli_repair_command(self) -> None:
        """harness_cli.py repair --repo <path> --kit <kit> --json runs cleanly via subprocess."""
        cli = KIT / "harness_cli.py"
        proc = subprocess.run(
            [sys.executable, str(cli), "repair", "--repo", str(self.repo), "--kit", str(KIT), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"repair failed:\nstderr: {proc.stderr}\nstdout: {proc.stdout}")
        data = json.loads(proc.stdout)
        self.assertEqual(data.get("status"), "PASS")


class PhaseEDecoupleZohoSelftest(unittest.TestCase):
    """Phase E Acceptance Tests: Decouple Zoho Sprints from Delivery Core."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="phase_e_test_")
        self.repo = Path(self.temp_dir.name)
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Test Agent")
        run_git(self.repo, "config", "user.email", "agent@example.com")
        (self.repo / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        run_git(self.repo, "add", ".")
        run_git(self.repo, "commit", "-qm", "initial commit")

        self.state_dir = self.repo / ".agents" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.env = os.environ.copy()
        self.env["HARNESS_REPO"] = str(self.repo)
        self.env["HARNESS_HOOK_STATE"] = str(self.state_dir / "hook-state.json")
        self.safety_script = KIT / "agents" / "scripts" / "pre_tool_safety.py"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _invoke_hook(self, tool_name: str, tool_args: dict | None = None) -> dict:
        payload = json.dumps({"toolName": tool_name, "toolArgs": tool_args or {}})
        proc = subprocess.run(
            [sys.executable, str(self.safety_script)],
            input=payload,
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc.returncode, f"pre_tool_safety error:\nstderr: {proc.stderr}\nstdout: {proc.stdout}")
        return json.loads(proc.stdout.strip())

    def _activate_plan(self, status: str = "IMPLEMENTING", external_writes: list[str] | None = None) -> None:
        tasks_dir = self.state_dir / "tasks" / "task-phase-e"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        plan = {
            "plan_id": "plan-phase-e",
            "task_id": "task-phase-e",
            "status": status,
            "execution_nonce": "test-nonce-123",
            "approval": {"single_use_nonce": "test-nonce-123"},
            "external_writes": external_writes or [],
        }
        (tasks_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (self.state_dir / "active-task.json").write_text(
            json.dumps({"task_id": "task-phase-e", "plan_path": str(tasks_dir / "plan.json")}),
            encoding="utf-8",
        )

    def test_registry_resolution_and_matching(self) -> None:
        """Integration registry correctly resolves zoho_sprints integration and matches tools."""
        from integrations.registry import registry
        from integrations.zoho_sprints.integration import ZohoSprintsIntegration

        zoho = registry.get("zoho_sprints")
        self.assertIsNotNone(zoho)
        self.assertIsInstance(zoho, ZohoSprintsIntegration)

        # Resolves via server name
        resolved_server = registry.resolve("zoho-sprints", "some_tool")
        self.assertEqual(resolved_server, zoho)

        # Resolves via tool name
        resolved_tool = registry.resolve("", "zoho_update_task_status")
        self.assertEqual(resolved_tool, zoho)

        # Unregistered tool/server returns None
        self.assertIsNone(registry.resolve("unregistered_pm", "custom_tool"))

        # Read-only distinction
        self.assertTrue(zoho.is_read_only("zoho_list_sprints", {}))
        self.assertTrue(zoho.is_read_only("zoho_list_tasks", {}))
        self.assertFalse(zoho.is_read_only("zoho_create_task", {}))
        self.assertFalse(zoho.is_read_only("zoho_update_task_status", {}))

    def test_workflow_accepts_generic_external_integration_name(self) -> None:
        """Core plan parsing is integration-neutral; the registry gates actual tool calls."""
        from workflow import build_parser
        args = build_parser().parse_args([
            "draft", "--repo", str(self.repo), "--task-id", "generic-external",
            "--outcome", "Update external tracker", "--expected-surfaces", "DOCS",
            "--expected-modules", "docs", "--external-write", "custom_tracker",
        ])
        self.assertEqual(args.external_write, ["custom_tracker"])

    def test_zoho_read_tools_allowed_without_active_plan(self) -> None:
        """Read-only inspection via MCP or host tool is allowed without active plan."""
        # MCP tool call
        res_mcp = self._invoke_hook("call_mcp_tool", {
            "ServerName": "zoho-sprints",
            "ToolName": "zoho_list_tasks",
            "Arguments": {"sprint_id": "1"},
        })
        self.assertEqual("allow", res_mcp["decision"])
        self.assertIn("Read-only Zoho inspection is allowed", res_mcp["reason"])

        # Direct host tool call
        res_host = self._invoke_hook("zoho_get_task_details", {"sprint_id": "1", "item_id": "101"})
        self.assertEqual("allow", res_host["decision"])
        self.assertIn("Read-only Zoho inspection is allowed", res_host["reason"])

    def test_zoho_mutation_denied_without_plan_authorization(self) -> None:
        """Zoho mutation is denied when external_writes does not include zoho_sprints."""
        # 1. No active plan at all
        res_no_plan = self._invoke_hook("call_mcp_tool", {
            "ServerName": "zoho-sprints",
            "ToolName": "zoho_create_task",
            "Arguments": {"name": "Test Bug", "operation_id": "op-1"},
        })
        self.assertEqual("deny", res_no_plan["decision"])
        self.assertIn("Zoho mutation is not included in the active approved plan", res_no_plan["reason"])

        # 2. Active plan exists but external_writes is empty
        self._activate_plan(external_writes=[])
        res_empty = self._invoke_hook("zoho_create_task", {"name": "Test Bug", "operation_id": "op-1"})
        self.assertEqual("deny", res_empty["decision"])
        self.assertIn("Zoho mutation is not included in the active approved plan", res_empty["reason"])

    def test_zoho_mutation_denied_without_operation_id(self) -> None:
        """Zoho mutation is denied if operation_id is missing (idempotency requirement)."""
        self._activate_plan(external_writes=["zoho_sprints"])
        res = self._invoke_hook("call_mcp_tool", {
            "ServerName": "zoho-sprints",
            "ToolName": "zoho_add_comment",
            "Arguments": {"item_id": "101", "comment": "work in progress"},
        })
        self.assertEqual("deny", res["decision"])
        self.assertIn("require a stable operation_id for idempotency", res["reason"])

    def test_zoho_mutation_denied_on_terminal_status(self) -> None:
        """Zoho mutation requesting terminal status (Done/Solved/Closed/Completed) is rejected."""
        self._activate_plan(external_writes=["zoho_sprints"])
        for term_status in ("Done", "done", "Solved", "solved", "Closed", "closed", "Completed", "completed"):
            with self.subTest(status=term_status):
                res = self._invoke_hook("zoho_update_task_status", {
                    "item_id": "101",
                    "status": term_status,
                    "operation_id": f"op-term-{term_status}",
                })
                self.assertEqual("deny", res["decision"])
                self.assertIn("Terminal tracker states are developer-owned", res["reason"])

    def test_zoho_mutation_allowed_when_plan_and_idempotency_satisfied(self) -> None:
        """Zoho mutation is allowed when authorized in plan with stable operation_id and non-terminal status."""
        self._activate_plan(external_writes=["zoho_sprints"])

        # Host tool call
        res_host = self._invoke_hook("zoho_update_task_status", {
            "item_id": "101",
            "status": "In progress",
            "operation_id": "op-progress-1",
        })
        self.assertEqual("allow", res_host["decision"])
        self.assertIn("Zoho mutation is plan-bound and idempotency-bound", res_host["reason"])

        # MCP tool call
        res_mcp = self._invoke_hook("call_mcp_tool", {
            "ServerName": "zoho-sprints",
            "ToolName": "zoho_add_comment",
            "Arguments": {"item_id": "101", "comment": "update details", "operation_id": "op-comment-1"},
        })
        self.assertEqual("allow", res_mcp["decision"])
        self.assertIn("Zoho mutation is plan-bound and idempotency-bound", res_mcp["reason"])

    def test_unregistered_mcp_mutation_denied(self) -> None:
        """Unregistered external mutation tool is denied fail-closed."""
        res = self._invoke_hook("call_mcp_tool", {
            "ServerName": "custom_tracker",
            "ToolName": "create_issue",
            "Arguments": {"title": "Issue"},
        })
        self.assertEqual("deny", res["decision"])
        self.assertIn("not registered as read-only and is not authorized", res["reason"])

    def test_core_delivery_operates_cleanly_without_zoho(self) -> None:
        """Core delivery workflow operates 100% cleanly with external_writes: [] when tracker is not used."""
        self._activate_plan(status="IMPLEMENTING", external_writes=[])
        # Normal file write and command execution should succeed without any Zoho dependency
        res_write = self._invoke_hook("write_to_file", {"TargetFile": "app/src/main/kotlin/com/example/Feature.kt"})
        self.assertEqual("allow", res_write["decision"])

        # Verification transition operates without Zoho dependency
        from delivery_manifest import build_manifest
        manifest = build_manifest(self.repo)
        task_plan_path = self.state_dir / "tasks" / "task-phase-e" / "plan.json"
        plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
        plan["status"] = "READY_FOR_DELIVERY"
        plan["ready_delivery_snapshot_sha256"] = manifest["delivery_snapshot_sha256"]
        plan["ready_change_set_sha256"] = manifest["change_set_sha256"]
        task_plan_path.write_text(json.dumps(plan), encoding="utf-8")

        # Stop turn allowed in ready for delivery
        stop_payload = json.dumps({"terminationReason": "model_stop"})
        proc = subprocess.run(
            [sys.executable, str(self.safety_script)],
            input=stop_payload,
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc.returncode)
        self.assertEqual("allow", json.loads(proc.stdout.strip())["decision"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
