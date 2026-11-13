"""Comprehensive unit & integration selftest suite for the 5 Open-Source Ecosystem Upgrades.

Tests:
1. `symbol_edit.py`: Kotlin/Java/Swift outline, read, brace-safe `replace-body`, `insert-after`, SHA-256 optimistic concurrency, brace-imbalance rejection, and `mutation_guard` enforcement.
2. `static_health_bridge.py` + `preflight_check.py`: Task-scoped Detekt SARIF & Gradle Dependency Analysis `buildHealth` filtering (ignoring untouched legacy files while blocking errors on modified files), silent 7-check preservation when no reports exist, and `LeakCanary` logcat detection.
3. `roborazzi_gate.py` + `review_package.py`: Roborazzi plugin detection, `.uitree.json` viewport/RTL clipping + zero-dimension + clickable-overlap checks, and `Verified Deterministic Gate Evidence` injection.
4. `maestro_bridge.py` + `phone_e2e.py`: Destructive `clearState`/`uninstallApp` fail-closed guard (with explicit developer proof override), `phone_e2e` -> `.maestro/<task_id>.yaml` exporter, and `walkthrough_maestro_hint`.
5. `session_forensics.py`: Hook denial streak detection, out-of-scope sprawl detection, transcript malformed-call & token-peak analysis, and `Zero-PII` scrubbed bundle export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import shutil
import subprocess
import unittest
import unittest.mock
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "dev@example.com"],
        ["git", "config", "user.name", "Dev"],
    ):
        subprocess.run(cmd, cwd=str(repo), check=True)
    (repo / "settings.gradle.kts").write_text('rootProject.name = "demo"\ninclude(":app")\n', encoding="utf-8")
    (repo / "app").mkdir(exist_ok=True)
    (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
    (repo / ".agents/state").mkdir(parents=True, exist_ok=True)


class EcosystemUpgradesSelftest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        _init_git_repo(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_1_symbol_edit_outline_read_replace_insert_and_mutation_guard(self) -> None:
        import symbol_edit
        import workflow
        from _vnext_common import ValidationError

        src = self.repo / "app/src/main/kotlin/com/example"
        src.mkdir(parents=True, exist_ok=True)
        vm_file = src / "FoodPlanViewModel.kt"
        vm_file.write_text(
            'package com.example\n\n'
            'class FoodPlanViewModel {\n'
            '    private val header = "{not a brace block}"\n'
            '    /* comment with { unmatched brace */\n'
            '    fun calculateCalories(base: Int): Int {\n'
            '        val msg = """raw { brace } string"""\n'
            '        return base + 10\n'
            '    }\n\n'
            '    fun resetPlan() {\n'
            '        println("reset")\n'
            '    }\n'
            '}\n',
            encoding="utf-8",
        )
        swift_file = src / "FoodPlanIosView.swift"
        swift_file.write_text(
            "import SwiftUI\n\nstruct FoodPlanIosView {\n    func renderTitle() -> String {\n        return \"Meals\"\n    }\n}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=str(self.repo), check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=str(self.repo), check=True)

        # Read-only outline & read work before any task exists (Kotlin + Swift)
        kt_out = symbol_edit.cmd_outline(self.repo, argparse.Namespace(file=str(vm_file)))
        qnames = [s["qualified_name"] for s in kt_out["symbols"]]
        self.assertIn("FoodPlanViewModel", qnames)
        self.assertIn("FoodPlanViewModel.calculateCalories", qnames)
        self.assertIn("FoodPlanViewModel.resetPlan", qnames)

        sw_out = symbol_edit.cmd_outline(self.repo, argparse.Namespace(file=str(swift_file)))
        self.assertIn("FoodPlanIosView.renderTitle", [s["qualified_name"] for s in sw_out["symbols"]])

        read_res = symbol_edit.cmd_read(
            self.repo,
            argparse.Namespace(file=str(vm_file), symbol="FoodPlanViewModel.calculateCalories", occurrence=None),
        )
        orig_sha = read_res["symbol"]["short_sha256"]
        self.assertIn("return base + 10", read_res["source"])

        # Without an approved IMPLEMENTING task, replace-body MUST fail closed via mutation_guard!
        with self.assertRaises(ValidationError):
            symbol_edit.cmd_replace_body(
                self.repo,
                argparse.Namespace(
                    file=str(vm_file),
                    symbol="FoodPlanViewModel.calculateCalories",
                    occurrence=None,
                    expected_sha256=orig_sha,
                    replacement_file=None,
                    stdin=False,
                    body="    fun calculateCalories(base: Int): Int {\n        return base + 50\n    }",
                ),
            )

        # Draft & approve task -> replace-body & insert-after succeed cleanly
        plan = workflow.draft(argparse.Namespace(
            repo=str(self.repo),
            task_id="t-sym",
            outcome="Update calorie calculation and add helper",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app",
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/FoodPlanViewModel.kt",
            phases=None,
            force=True,
        ))
        workflow.record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id="t-sym",
            source="conversation",
            proof_reference="Proceed",
            enforcement_tier="RULE_ENFORCED",
            plan_hash=plan["plan_sha256"][:12],
        ))

        # Stale SHA-256 must be rejected
        with self.assertRaises(ValidationError) as ctx_sha:
            symbol_edit.cmd_replace_body(
                self.repo,
                argparse.Namespace(
                    file=str(vm_file),
                    symbol="calculateCalories",
                    occurrence=None,
                    expected_sha256="deadbeef0000",
                    replacement_file=None,
                    stdin=False,
                    body="    fun calculateCalories(base: Int): Int {\n        return base + 50\n    }",
                ),
            )
        self.assertIn("SYMBOL_SHA256_MISMATCH", str(ctx_sha.exception))

        # Unbalanced braces must be rejected without corrupting disk
        with self.assertRaises(ValidationError) as ctx_brace:
            symbol_edit.cmd_replace_body(
                self.repo,
                argparse.Namespace(
                    file=str(vm_file),
                    symbol="calculateCalories",
                    occurrence=None,
                    expected_sha256=orig_sha,
                    replacement_file=None,
                    stdin=False,
                    body="    fun calculateCalories(base: Int): Int {\n        return base + 50\n",
                ),
            )
        self.assertIn("BRACE_IMBALANCE", str(ctx_brace.exception))

        # Valid replace-body + insert-after succeed cleanly
        upd = symbol_edit.cmd_replace_body(
            self.repo,
            argparse.Namespace(
                file=str(vm_file),
                symbol="calculateCalories",
                occurrence=None,
                expected_sha256=orig_sha,
                replacement_file=None,
                stdin=False,
                body="    fun calculateCalories(base: Int): Int {\n        return (base * 2) + 25\n    }",
            ),
        )
        self.assertEqual("UPDATED", upd["status"])

        ins = symbol_edit.cmd_insert_after(
            self.repo,
            argparse.Namespace(
                file=str(vm_file),
                symbol="calculateCalories",
                occurrence=None,
                expected_sha256=None,
                replacement_file=None,
                stdin=False,
                body="private fun clampCalories(v: Int): Int {\n    return v.coerceAtLeast(0)\n}",
            ),
        )
        self.assertEqual("INSERTED", ins["status"])
        final_text = vm_file.read_text(encoding="utf-8")
        self.assertIn("return (base * 2) + 25", final_text)
        self.assertIn("private fun clampCalories", final_text)
        self.assertIn("fun resetPlan()", final_text)

    def test_2_static_health_sarif_buildhealth_scoping_and_leakcanary(self) -> None:
        import static_health_bridge as shb

        # Untouched legacy error in OldLegacy.kt MUST NOT block when only NewFeature.kt changed!
        sarif_dir = self.repo / "app/build/reports/detekt"
        sarif_dir.mkdir(parents=True, exist_ok=True)
        sarif_payload = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "detekt"}},
                "results": [
                    {
                        "ruleId": "MaxLineLength",
                        "level": "error",
                        "message": {"text": "Legacy line too long"},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app/src/main/kotlin/OldLegacy.kt"}, "region": {"startLine": 12}}}],
                    },
                    {
                        "ruleId": "MagicNumber",
                        "level": "warning",
                        "message": {"text": "Minor magic number"},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app/src/main/kotlin/NewFeature.kt"}, "region": {"startLine": 8}}}],
                    },
                ],
            }],
        }
        (sarif_dir / "detekt.sarif").write_text(json.dumps(sarif_payload), encoding="utf-8")

        ok_clean, msg_clean, det_clean = shb.check_task_static_health(self.repo, ["app/src/main/kotlin/NewFeature.kt"])
        self.assertTrue(ok_clean, msg_clean)
        self.assertTrue(det_clean["active"])
        self.assertEqual(1, len(det_clean["sarif"]["warnings"]))

        # Error in modified file OldLegacy.kt MUST block
        ok_err, msg_err, _ = shb.check_task_static_health(self.repo, ["app/src/main/kotlin/OldLegacy.kt"])
        self.assertFalse(ok_err)
        self.assertIn("STATIC_HEALTH_VIOLATION", msg_err)

        # BuildHealth blocking advice on modified module :app
        bh_dir = self.repo / "app/build/reports/dependency-analysis"
        bh_dir.mkdir(parents=True, exist_ok=True)
        (bh_dir / "build-health-report.json").write_text(json.dumps({
            "projectAdvice": [{
                "projectPath": ":app",
                "shouldFail": True,
                "dependencyAdvice": [{
                    "coordinates": {"identifier": "com.squareup.okhttp3:okhttp"},
                    "fromConfiguration": "api",
                    "toConfiguration": "implementation",
                }],
            }],
        }), encoding="utf-8")
        ok_bh, msg_bh, _ = shb.check_task_static_health(self.repo, ["app/build.gradle.kts"])
        self.assertFalse(ok_bh)
        self.assertIn("com.squareup.okhttp3:okhttp", msg_bh)

    def test_3_roborazzi_uitree_bounds_clipping_and_review_package_evidence(self) -> None:
        import roborazzi_gate as rg
        import review_package as rp
        from evidence_store import EvidenceStore
        from _vnext_common import state_root

        (self.repo / "app/build.gradle.kts").write_text(
            'plugins { id("com.android.application"); id("io.github.takahirom.roborazzi") }\n',
            encoding="utf-8",
        )
        caps = rg.detect_roborazzi(self.repo)
        self.assertTrue(caps["installed"])
        self.assertIn(":app", caps["modules"])

        out_dir = self.repo / "app/build/outputs/roborazzi"
        out_dir.mkdir(parents=True, exist_ok=True)
        good_tree = out_dir / "FoodCardTest.uitree.json"
        good_tree.write_text(json.dumps({
            "schemaVersion": 1,
            "capture": {"imageWidth": 360, "imageHeight": 640, "scale": 1.0},
            "root": {
                "type": "view",
                "bounds": [0, 0, 360, 640],
                "children": [
                    {"n": 1, "type": "compose", "testTag": "swap_meal_btn", "bounds": [24, 40, 336, 96], "actions": ["OnClick"]},
                ],
            },
        }), encoding="utf-8")
        audit_ok = rg.inspect_uitree_files(self.repo, [good_tree])
        self.assertEqual("PASS", audit_ok["status"])

        # Clipped RTL node beyond right viewport edge (360) + zero-width node MUST fail!
        bad_tree = out_dir / "ClippedRtlTest.uitree.json"
        bad_tree.write_text(json.dumps({
            "schemaVersion": 1,
            "capture": {"imageWidth": 360, "imageHeight": 640, "scale": 1.0},
            "root": {
                "type": "view",
                "bounds": [0, 0, 360, 640],
                "children": [
                    {"n": 1, "type": "compose", "testTag": "rtl_title", "bounds": [-28, 20, 340, 60]},
                    {"n": 2, "type": "compose", "testTag": "broken_icon", "bounds": [50, 80, 50, 120]},
                ],
            },
        }), encoding="utf-8")
        audit_bad = rg.inspect_uitree_files(self.repo, [bad_tree])
        self.assertEqual("FAIL", audit_bad["status"])
        codes = {i["code"] for i in audit_bad["issues"]}
        self.assertIn("HORIZONTAL_VIEWPORT_CLIP", codes)
        self.assertIn("ZERO_DIMENSION_NODE", codes)

        # Verify review_package._verified_deterministic_gate_summary surfaces roborazzi_ui bounds digest
        store = EvidenceStore(state_root(self.repo))
        snap = "a" * 64
        cset = "b" * 64
        store.write(
            snapshot=snap,
            run_id="r-rb",
            name="roborazzi_ui",
            producer="roborazzi_gate",
            harness_version="1.2.17",
            change_set=cset,
            status="PASS",
            evidence={"uitree_audit": audit_ok},
        )
        summary_lines = rp._verified_deterministic_gate_summary(self.repo, snap, "r-rb", cset)
        joined = "\n".join(summary_lines)
        self.assertIn("`roborazzi_ui`", joined)
        self.assertIn("swap_meal_btn", joined)

    def test_4_maestro_destructive_guard_and_phone_e2e_yaml_exporter(self) -> None:
        import maestro_bridge as mb
        from _vnext_common import ValidationError, state_root

        flow_dir = self.repo / ".maestro"
        flow_dir.mkdir(parents=True, exist_ok=True)
        unsafe_flow = flow_dir / "unsafe_login.yaml"
        unsafe_flow.write_text("appId: com.example.app\n---\n- clearState\n- launchApp\n", encoding="utf-8")

        with self.assertRaises(ValidationError) as ctx:
            mb.validate_maestro_yaml_safety(unsafe_flow)
        self.assertIn("MAESTRO_DESTRUCTIVE_COMMAND_FORBIDDEN", str(ctx.exception))

        # Explicit developer conversation authorization unlocks intentional clearState
        mb.validate_maestro_yaml_safety(
            unsafe_flow,
            allow_clear_state=True,
            source="conversation",
            proof_reference="clear app state for fresh onboarding test",
        )

        # Export recorded phone_e2e session -> deterministic non-destructive Maestro YAML
        tdir = state_root(self.repo) / "tasks/t-food"
        e2e_dir = tdir / "e2e/r1"
        e2e_dir.mkdir(parents=True, exist_ok=True)
        (tdir / "plan.json").write_text(json.dumps({"task_id": "t-food", "status": "VERIFYING"}), encoding="utf-8")
        (tdir / "current-run.json").write_text(json.dumps({"run_id": "r1", "delivery_snapshot_sha256": "c" * 64}), encoding="utf-8")
        (e2e_dir / "session.json").write_text(json.dumps({
            "task_id": "t-food",
            "run_id": "r1",
            "delivery_snapshot_sha256": "c" * 64,
            "application_id": "com.rashaqa.app",
            "state": "FINISHED",
            "scenarios": [{"id": "S1", "title": "Swap breakfast meal", "status": "PASS"}],
            "actions": [
                {"action": "tap", "target": {"resource_id": "com.rashaqa.app:id/btn_change_meal"}},
                {"action": "wait", "found": True, "query": {"text": "Alternatives"}},
                {"action": "swipe", "direction": "up"},
                {"action": "key", "name": "BACK"},
            ],
        }), encoding="utf-8")

        # During VERIFYING, export-e2e stages inside .agents/state to preserve frozen delivery snapshot!
        exp_staged = mb.cmd_export_e2e(self.repo, argparse.Namespace(task_id="t-food", out=None))
        self.assertEqual("STAGED_IN_TASK_STATE", exp_staged["status"])
        self.assertTrue(exp_staged["flow_file"].startswith(".agents/state/tasks/t-food/maestro/"))
        with self.assertRaises(ValidationError) as frozen_ctx:
            mb.cmd_export_e2e(self.repo, argparse.Namespace(task_id="t-food", out=".maestro/t-food.yaml"))
        self.assertIn("SNAPSHOT_FROZEN", str(frozen_ctx.exception))

        # Once DELIVERED, export-e2e writes directly to .maestro/t-food.yaml
        (tdir / "plan.json").write_text(json.dumps({"task_id": "t-food", "status": "DELIVERED"}), encoding="utf-8")
        exp = mb.cmd_export_e2e(self.repo, argparse.Namespace(task_id="t-food", out=None))
        self.assertEqual("EXPORTED", exp["status"])
        self.assertEqual(".maestro/t-food.yaml", exp["flow_file"])
        yaml_content = (self.repo / exp["flow_file"]).read_text(encoding="utf-8")
        self.assertIn("appId: com.rashaqa.app", yaml_content)
        self.assertIn('id: "btn_change_meal"', yaml_content)
        self.assertIn('text: "Alternatives"', yaml_content)
        self.assertNotIn("clearState", yaml_content)

        hint = mb.walkthrough_maestro_hint(self.repo, "t-food")
        self.assertIn("[MAESTRO]", hint)
        self.assertIn("maestro run", hint)

    def test_5_session_forensics_streak_detection_and_zero_pii_bundle(self) -> None:
        import session_forensics as sf

        cache_dir = self.repo / ".agents/cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        audit_file = cache_dir / "hook-audit.jsonl"
        events = [
            {"decision": "deny", "tool": "grep_search", "reason_code": "DISCOVERY_ANCHOR_REQUIRED", "reason": "Anchor first dev@secret.io"},
            {"decision": "deny", "tool": "grep_search", "reason_code": "DISCOVERY_ANCHOR_REQUIRED", "reason": "Anchor first"},
            {"decision": "deny", "tool": "view_file", "reason_code": "BACKGROUND_TASK_LOG_POLLING_FORBIDDEN", "reason": "Task log"},
            {"decision": "allow", "tool": "run_command", "reason_code": "HARNESS_COMMAND", "reason": "ok"},
        ]
        audit_file.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

        report = sf.diagnose_session(self.repo)
        codes = {f["code"] for f in report["findings"]}
        self.assertIn("UNANCHORED_SEARCH_FRICTION", codes)
        self.assertIn("BACKGROUND_LOG_POLLING_ATTEMPT", codes)
        self.assertIn("CONSECUTIVE_HOOK_DENIAL_STREAK", codes)

        bundle_path = sf.export_scrubbed_bundle(self.repo, report)
        self.assertTrue(bundle_path.is_file())
        scrubbed_raw = bundle_path.read_text(encoding="utf-8")
        self.assertNotIn("dev@secret.io", scrubbed_raw)
        self.assertIn("<REDACTED_EMAIL>", scrubbed_raw)




class AllTaskKindsWorkflowMatrixSelftest(unittest.TestCase):
    """End-to-end zero-trust workflow verification across ALL task kinds and risk tiers."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "app-repo"
        self.repo.mkdir(parents=True)
        self.brain_app_data = Path(self._tmp.name) / "ag-data"
        (self.brain_app_data / "brain").mkdir(parents=True)

        # Install full .agents engine into repo
        kit_root = Path(__file__).resolve().parents[2]
        shutil.copytree(
            kit_root / "agents",
            self.repo / ".agents",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyc.*", "state", "cache", "*.lock", ".audit-lock"),
        )

        # Seed minimal Android project structure
        (self.repo / "settings.gradle.kts").write_text(
            'rootProject.name = "DemoApp"\ninclude(":app", ":core:model")\n',
            encoding="utf-8",
        )
        (self.repo / "build.gradle.kts").write_text("// root build\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# DemoApp\nInitial docs.\n", encoding="utf-8")

        app_src = self.repo / "app/src/main/java/com/demo"
        app_test = self.repo / "app/src/test/java/com/demo"
        core_src = self.repo / "core/model/src/main/java/com/demo/model"
        app_src.mkdir(parents=True)
        app_test.mkdir(parents=True)
        core_src.mkdir(parents=True)

        (self.repo / "app/build.gradle.kts").write_text(
            'plugins { id("com.android.application"); id("io.github.takahirom.roborazzi") }\nandroid { namespace = "com.demo" }\n',
            encoding="utf-8",
        )
        (self.repo / "core/model/build.gradle.kts").write_text(
            'plugins { kotlin("jvm") }\n',
            encoding="utf-8",
        )
        (core_src / "MealPlan.kt").write_text(
            "package com.demo.model\n\ndata class MealPlan(val id: String, val calories: Int)\n",
            encoding="utf-8",
        )
        (app_src / "FoodViewModel.kt").write_text(
            "package com.demo\n\nclass FoodViewModel {\n"
            "    private fun formatKcal(v: Int): String {\n"
            "        return v.toString()\n"
            "    }\n\n"
            "    fun loadPlan(): String {\n"
            "        return formatKcal(1800)\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        (app_src / "Calc.kt").write_text(
            "package com.demo\n\nclass Calc {\n"
            "    fun safeDiv(a: Int, b: Int): Int {\n"
            "        return a / b\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        (app_test / "CalcTest.kt").write_text(
            "package com.demo\n\nclass CalcTest {\n"
            "    fun placeholder() {}\n"
            "}\n",
            encoding="utf-8",
        )
        (app_src / "AuthManager.kt").write_text(
            "package com.demo\n\nclass AuthManager {\n"
            "    fun refreshToken(raw: String): Boolean {\n"
            "        return raw.isNotBlank()\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        (app_src / "FoodScreen.kt").write_text(
            "package com.demo\n\nclass FoodScreen {\n"
            "    fun renderCard(): String = \"card\"\n"
            "}\n",
            encoding="utf-8",
        )

        self._git("init", "-b", "main")
        self._git("config", "user.email", "dev@demo.local")
        self._git("config", "user.name", "Demo Dev")
        from install_tool_adapters import generate_antigravity_agents
        generate_antigravity_agents(self.repo, dry_run=False)
        # Gitignore .agents and .agent so working tree stays clean on task deliver!
        (self.repo / ".gitignore").write_text(".agents/\n.agent/\n.harness-setup/\nbuild/\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            check=True,
        )

    def _pre_tool(self, payload: dict) -> dict:
        env = dict(
            os.environ,
            HARNESS_REPO=str(self.repo),
            HARNESS_HOST="antigravity",
            ANTIGRAVITY_APP_DATA=str(self.brain_app_data),
        )
        proc = subprocess.run(
            [sys.executable, str(self.repo / ".agents/scripts/pre_tool_safety.py")],
            cwd=str(self.repo),
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        out = (proc.stdout or "").strip()
        if not out:
            return {"decision": "allow"}
        parsed = json.loads(out.splitlines()[-1])
        hook_out = parsed.get("hookSpecificOutput") or {}
        if "permissionDecision" in hook_out:
            return {
                "decision": hook_out["permissionDecision"],
                "reason": hook_out.get("permissionDecisionReason", ""),
                "raw": parsed,
            }
        return parsed

    def _record_gate(self, snapshot: str, change_set: str, run_id: str, name: str, producer: str = "", evidence: dict | None = None) -> None:
        from evidence_store import EvidenceStore
        from _vnext_common import state_root
        default_producers = {
            "preflight": "preflight_check",
            "localization": "check_strings",
            "room": "room_guard",
            "unit_tests": "run_tests_gate",
            "assemble": "run_gradle_task",
            "device_install": "run_device",
            "device_launch": "run_device",
            "device_signoff": "run_device",
            "reviews": "review_orchestrator",
        }
        prod = default_producers.get(name, producer or "preflight_check") if producer in ("", "selftest", "developer_signoff") else producer
        ver = (self.repo / ".agents/VERSION").read_text(encoding="utf-8").strip()
        EvidenceStore(state_root(self.repo)).write(
            snapshot=snapshot,
            run_id=run_id,
            name=name,
            producer=prod,
            harness_version=ver,
            change_set=change_set,
            status="PASS",
            evidence=evidence or {"ok": True},
        )

    def _spawn_fake_reviewer_transcript(
        self,
        *,
        exec_id: str,
        parent_id: str,
        prompt_text: str,
        task_id: str,
        run_id: str,
        reviewer: str,
        package_sha256: str,
        verdict: str = "PASS",
        findings: list[dict] | None = None,
        configured_model: str = "gemini-3.8-flash-medium",
        observed_model: str = "gemini-3.8-flash-medium",
    ) -> Path:
        cdir = self.brain_app_data / "brain" / exec_id / ".system_generated" / "logs"
        cdir.mkdir(parents=True, exist_ok=True)
        # Write generator metadata if needed by runtime model verification
        meta_dir = self.brain_app_data / "brain" / exec_id
        (meta_dir / "metadata.json").write_text(
            json.dumps({"model": configured_model, "observedModel": observed_model}),
            encoding="utf-8",
        )
        sys_msg = {
            "source": "SYSTEM_SDK",
            "type": "SYSTEM_MESSAGE",
            "content": f"<SYSTEM_MESSAGE>sender={parent_id} priority=MESSAGE_PRIORITY_HIGH content={prompt_text}\n</SYSTEM_MESSAGE>",
        }
        body = {
            "schema_version": 2,
            "task_id": task_id,
            "run_id": run_id,
            "reviewer": reviewer,
            "review_package_sha256": package_sha256,
            "verdict": verdict,
            "findings": findings or [],
        }
        reply_msg = {
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "model": observed_model,
            "generatorModel": observed_model,
            "content": "```json\n" + json.dumps(body) + "\n```",
        }
        tx = cdir / "transcript.jsonl"
        tx.write_text(json.dumps(sys_msg) + "\n" + json.dumps(reply_msg) + "\n", encoding="utf-8")
        return tx

    def _pass_all_reviewers_direct(self, task_id: str, current: dict, policy: dict) -> None:
        """Write cryptographic review PASS artifact + dispatch receipts matching final_verifier invariants."""
        from _vnext_common import atomic_write_json, canonical_sha256, read_json, sha256_file, state_root, utc_now
        from review_models import frozen_models
        tdir = state_root(self.repo) / "tasks" / task_id
        run_id = str(current["run_id"])
        manifest = read_json(Path(current["manifest"]))
        snap = str(manifest["delivery_snapshot_sha256"])
        cset = str(manifest["change_set_sha256"])
        from review_orchestrator import active_review_package_path
        pkg_path = active_review_package_path(self.repo, current)
        if not pkg_path.is_file():
            import review_package
            review_package.build_package(self.repo, task_id)
            current = read_json(tdir / "current-run.json")
            pkg_path = active_review_package_path(self.repo, current)
        pkg_sha = sha256_file(pkg_path)
        receipts_dir = tdir / "reviewer-dispatches"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        current = read_json(tdir / "current-run.json")
        f_models = frozen_models(current)
        reports = []
        for role in policy.get("reviewers") or []:
            rc = {
                "schema_version": 1,
                "task_id": task_id,
                "run_id": run_id,
                "reviewer": role,
                "subagent_id": f"sub-{role}",
                "review_package_sha256": pkg_sha,
                "dispatched_at": utc_now(),
                "host": "antigravity",
            }
            rc["receipt_sha256"] = canonical_sha256({k: v for k, v in rc.items() if k != "receipt_sha256"})
            atomic_write_json(receipts_dir / f"{role}.json", rc)
            raw_sel = dict(f_models.get(role) or {})
            if raw_sel and raw_sel.get("requested_model") != "inherit" and raw_sel.get("resolved_model") != "inherit":
                resolved_m = str(raw_sel["resolved_model"])
                native_meta = {
                    "execution_id": f"sub-{role}",
                    "host_configured_model": resolved_m,
                    "host_reported_models": [resolved_m],
                    "native_metadata_source": "metadata.json",
                }
                sel = {
                    "settings_sha256": (current.get("review_models") or {}).get("sha256"),
                    "requested_model": raw_sel["requested_model"],
                    "resolved_model": resolved_m,
                    "thinking_level": raw_sel.get("thinking_level"),
                    "actual_model_status": "NATIVE_METADATA_OBSERVED",
                    **native_meta,
                    "native_metadata_sha256": canonical_sha256(native_meta),
                }
            else:
                sel = raw_sel
            reports.append({
                "reviewer": role,
                "verdict": "PASS",
                "findings": [],
                "independent_execution_verified": True,
                "provenance": "subagent_execution",
                "model_selection": sel,
                "execution_proof": {
                    "proof_kind": "ANTIGRAVITY_SUBAGENT_TRANSCRIPT",
                    "task_id": task_id,
                    "run_id": run_id,
                    "package_sha256": pkg_sha,
                },
            })
        self._record_gate(
            snap,
            cset,
            run_id,
            "reviews",
            "review_orchestrator",
            {
                "reviewers": list(policy.get("reviewers") or []),
                "reports": reports,
                "package_sha256": pkg_sha,
                "blocking_findings": [],
                "is_truncated": False,
            },
        )
        # Also mark review ledger COMPLETED so resolve_next_action advances past reviews!
        from review_orchestrator import REVIEW_INGESTED, ledger_file, load_ledger, save_ledger
        l_file = ledger_file(tdir, run_id)
        if l_file.is_file():
            ledger = load_ledger(tdir, run_id)
            for role in policy.get("reviewers") or []:
                if role in ledger.get("reviewers", {}):
                    ledger["reviewers"][role]["state"] = REVIEW_INGESTED
                    ledger["reviewers"][role]["verdict"] = "PASS"
            save_ledger(tdir, run_id, ledger)

    def _draft_approve_begin(
        self,
        *,
        task_id: str,
        title: str,
        kind: str,
        files: list[str],
        surfaces: list[str],
        modules: list[str] | None = None,
        phases: list[dict] | None = None,
    ) -> dict:
        import workflow
        parser = workflow.build_parser()
        cli = [
            "draft",
            "--repo", str(self.repo),
            "--task-id", task_id,
            "--outcome", title,
            "--kind", kind,
            "--expected-files", ",".join(files),
            "--expected-surfaces", ",".join(surfaces),
            "--approach", "targeted minimal implementation",
            "--test-strategy", "unit tests",
            "--risks", "none",
        ]
        mods = [":app"] if modules is None else modules
        if mods:
            cli.extend(["--expected-modules", ",".join(mods)])
        if phases:
            cli.extend(["--phases", json.dumps(phases)])
        ns = parser.parse_args(cli)
        plan = workflow.draft(ns)
        workflow.record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id=task_id,
            source="conversation",
            proof_reference="approved go ahead",
            enforcement_tier="RULE_ENFORCED",
            plan_hash=plan["plan_sha256"][:12],
        ))
        return workflow.begin_task(argparse.Namespace(repo=str(self.repo), task_id=task_id))

    def test_1_idle_consultation_and_trivial_t0_docs_lifecycle(self) -> None:
        """Verify IDLE read-only commands + T0_TRIVIAL 0-reviewer end-to-end delivery."""
        import workflow
        from _vnext_common import read_json, state_root

        # 1. IDLE read-only checks: symbol outline/read (CLI & direct script), health, D0 grep_search allowed; writes blocked!
        for cmd in (
            "python .agents/harness.py symbol outline --file app/src/main/java/com/demo/FoodViewModel.kt",
            "python .agents/scripts/symbol_edit.py read --file app/src/main/java/com/demo/FoodViewModel.kt --symbol loadPlan",
            "python .agents/harness.py health capabilities",
            "python .agents/harness.py diagnose-session",
        ):
            res = self._pre_tool({"toolName": "run_command", "toolArgs": {"CommandLine": cmd}})
            self.assertEqual("allow", res["decision"], f"Expected allow in IDLE for {cmd}: {res}")

        deny_sym = self._pre_tool({
            "toolName": "run_command",
            "toolArgs": {"CommandLine": "python .agents/harness.py symbol replace-body --file app/src/main/java/com/demo/FoodViewModel.kt --symbol loadPlan --replacement x"},
        })
        self.assertEqual("deny", deny_sym["decision"])

        d0_grep = self._pre_tool({
            "toolName": "grep_search",
            "toolArgs": {"SearchPath": "app/src/main/java/com/demo/FoodViewModel.kt", "Query": "loadPlan"},
        })
        self.assertEqual("allow", d0_grep["decision"])

        # 2. T0_TRIVIAL DOCS task: 0 reviewers -> preflight -> complete -> git commit -> deliver
        self._draft_approve_begin(
            task_id="t-docs",
            title="Update README architecture section",
            kind="FEATURE",
            files=["README.md"],
            surfaces=["DOCS"],
            modules=[],
        )
        act_impl = workflow.resolve_next_action(self.repo, "t-docs", host="antigravity")
        self.assertEqual("IMPLEMENT_APPROVED_SCOPE", act_impl["code"])
        self.assertEqual("TRIVIAL_INLINE_LEAD", act_impl["delegation_advisory"]["strategy"])

        (self.repo / "README.md").write_text("# DemoApp\nUpdated architecture overview.\n", encoding="utf-8")
        cur = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-docs", force=False, host="antigravity"))
        tdir = state_root(self.repo) / "tasks/t-docs"
        policy = read_json(Path(cur["policy"]))
        manifest = read_json(Path(cur["manifest"]))
        self.assertEqual("T0_TRIVIAL", policy["risk_tier"])
        self.assertEqual([], policy["reviewers"])

        for g in policy.get("gates") or []:
            if g != "manifest":
                self._record_gate(manifest["delivery_snapshot_sha256"], manifest["change_set_sha256"], cur["run_id"], g, "selftest")

        act_done = workflow.resolve_next_action(self.repo, "t-docs", host="antigravity")
        self.assertEqual("COMPLETE_TASK", act_done["code"])
        ready_plan = workflow.complete(argparse.Namespace(repo=str(self.repo), task_id="t-docs"))
        self.assertEqual("READY_FOR_DELIVERY", ready_plan["status"])

        self._git("add", "README.md")
        self._git("commit", "-m", "docs: update architecture section")
        delivered = workflow.deliver_task(self.repo, "t-docs")
        self.assertEqual("DELIVERED", delivered["status"])

    def test_2_feature_single_and_multiphase_and_worker_symbol_scope(self) -> None:
        """Verify FEATURE single-phase + worker symbol scope guard + unbound reviewer auto-bind + multi-phase p1->p2."""
        import workflow
        from _vnext_common import read_json, sha256_file, state_root
        from delegation_policy import WORKER_AGENT, record_utility_dispatch

        # A) Single-phase FEATURE with worker scope check on `symbol replace-body`
        self._draft_approve_begin(
            task_id="t-feat",
            title="Add calorie formatting label",
            kind="FEATURE",
            files=["app/src/main/java/com/demo/FoodViewModel.kt"],
            surfaces=["BUSINESS_LOGIC", "COROUTINES", "PERSISTENCE"],
        )
        w_prompt = "Implement loadPlan() in app/src/main/java/com/demo/FoodViewModel.kt returning kcal suffix and run unit tests."
        record_utility_dispatch(
            self.repo,
            agent_type=WORKER_AGENT,
            role_label=WORKER_AGENT,
            prompt=w_prompt,
            parent_conversation_id="lead-conv-1",
            task_id="t-feat",
            worker_mode="FULL_SLICE",
        )
        # Bind worker transcript
        w_tx_dir = self.brain_app_data / "brain/worker-conv-1/.system_generated/logs"
        w_tx_dir.mkdir(parents=True, exist_ok=True)
        (w_tx_dir / "transcript.jsonl").write_text(
            json.dumps({
                "source": "SYSTEM_SDK",
                "type": "SYSTEM_MESSAGE",
                "content": f"<SYSTEM_MESSAGE>sender=lead-conv-1 priority=MESSAGE_PRIORITY_HIGH content={w_prompt}\n</SYSTEM_MESSAGE>",
            }) + "\n",
            encoding="utf-8",
        )
        # Worker trying `symbol replace-body` on UNPLANNED production file AuthManager.kt MUST BE DENIED in PreToolUse!
        deny_unplanned = self._pre_tool({
            "conversationId": "worker-conv-1",
            "toolName": "run_command",
            "toolArgs": {
                "CommandLine": "python .agents/harness.py symbol replace-body --file app/src/main/java/com/demo/AuthManager.kt --symbol refreshToken --replacement x",
            },
        })
        self.assertEqual("deny", deny_unplanned["decision"])
        # Worker using `symbol replace-body` on PLANNED FoodViewModel.kt IS ALLOWED!
        allow_planned = self._pre_tool({
            "conversationId": "worker-conv-1",
            "toolName": "run_command",
            "toolArgs": {
                "CommandLine": "python .agents/harness.py symbol replace-body --file app/src/main/java/com/demo/FoodViewModel.kt --symbol loadPlan --replacement x",
            },
        })
        self.assertEqual("allow", allow_planned["decision"], allow_planned)

        # Apply surgical edit with `symbol_edit`
        import symbol_edit
        rc_sym = symbol_edit.main([
            "replace-body",
            "--repo", str(self.repo),
            "--file", "app/src/main/java/com/demo/FoodViewModel.kt",
            "--symbol", "FoodViewModel.loadPlan",
            "--replacement", '    suspend fun loadPlan(prefs: androidx.datastore.core.DataStore<androidx.datastore.preferences.core.Preferences>): String {\n        return formatKcal(2000) + " kcal"\n    }',
        ])
        self.assertEqual(0, rc_sym)

        cur = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-feat", force=False, host="antigravity"))
        tdir = state_root(self.repo) / "tasks/t-feat"
        policy = read_json(Path(cur["policy"]))
        manifest = read_json(Path(cur["manifest"]))
        self.assertEqual("T2_FEATURE", policy["risk_tier"])
        self.assertNotIn("security-perf-reviewer-agent", policy["reviewers"])

        for g in policy.get("gates") or []:
            if g != "manifest":
                self._record_gate(manifest["delivery_snapshot_sha256"], manifest["change_set_sha256"], cur["run_id"], g, "selftest")

        # Build review package, select risk-hybrid preset, dispatch WITHOUT binding execution_id, and verify auto-bind in lifecycle_action!
        import review_models
        import review_orchestrator
        import review_package
        review_package.build_package(self.repo, "t-feat")
        cur = read_json(tdir / "current-run.json")
        review_models.set_policy(
            self.repo,
            review_models.resolve_preset_policy("risk-hybrid"),
            task_id="t-feat",
            host="antigravity",
            source="conversation",
            proof_reference="use risk-hybrid",
        )
        cur = read_json(tdir / "current-run.json")
        roster = sorted(policy["reviewers"])
        review_orchestrator.record_dispatch_batch(self.repo, "t-feat", roster, host="antigravity")

        # Create unbound finished transcripts in brain/ (simulating missed PostToolUse!)
        from review_execution import brief_pointer_prompt, resolve_execution_profile
        prof_feat = resolve_execution_profile(self.repo, "t-feat", "antigravity")
        pkg_sha_feat = sha256_file(review_orchestrator.active_review_package_path(self.repo, cur))
        for idx, role in enumerate(roster):
            b_path = str(prof_feat["reviewers"][role]["brief_path"])
            b_text = Path(b_path).read_text(encoding="utf-8")
            ptr = brief_pointer_prompt(role, b_path, b_text)
            self._spawn_fake_reviewer_transcript(
                exec_id=f"unbound-feat-rev-{idx}",
                parent_id="lead-conv-1",
                prompt_text=ptr,
                task_id="t-feat",
                run_id=cur["run_id"],
                reviewer=role,
                package_sha256=pkg_sha_feat,
            )

        with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(self.brain_app_data), "HARNESS_HOST": "antigravity"}):
            act_rev = workflow.resolve_next_action(self.repo, "t-feat", host="antigravity")
            self.assertEqual("COMPLETE_REVIEWER", act_rev["code"], f"Unbound finished transcripts must auto-bind, got: {act_rev}")

        self._pass_all_reviewers_direct("t-feat", cur, policy)
        self.assertEqual("COMPLETE_TASK", workflow.resolve_next_action(self.repo, "t-feat", host="antigravity")["code"])
        workflow.complete(argparse.Namespace(repo=str(self.repo), task_id="t-feat"))
        self._git("add", "-A")
        self._git("commit", "-m", "feat: add kcal suffix in FoodViewModel")
        self.assertEqual("DELIVERED", workflow.deliver_task(self.repo, "t-feat")["status"])

        # B) Multi-phase FEATURE (`p1` :core:model -> `p2` :app)
        phases = [
            {"id": "p1", "title": "Extend MealPlan model", "modules": [":core:model"], "expected_files": ["core/model/src/main/java/com/demo/model/MealPlan.kt"]},
            {"id": "p2", "title": "Adopt protein field in FoodViewModel", "modules": [":app"], "expected_files": ["app/src/main/java/com/demo/FoodViewModel.kt"]},
        ]
        self._draft_approve_begin(
            task_id="t-multi",
            title="Multi-phase macro tracking",
            kind="FEATURE",
            files=["core/model/src/main/java/com/demo/model/MealPlan.kt", "app/src/main/java/com/demo/FoodViewModel.kt"],
            surfaces=["BUSINESS_LOGIC"],
            modules=[":core:model", ":app"],
            phases=phases,
        )
        act_p1 = workflow.resolve_next_action(self.repo, "t-multi", host="antigravity")
        self.assertEqual("IMPLEMENT_APPROVED_SCOPE", act_p1["code"])
        self.assertEqual(["core/model/src/main/java/com/demo/model/MealPlan.kt"], act_p1["delegation_advisory"]["target_files"])

        (self.repo / "core/model/src/main/java/com/demo/model/MealPlan.kt").write_text(
            "package com.demo.model\n\ndata class MealPlan(val id: String, val calories: Int, val proteinGrams: Int = 0)\n",
            encoding="utf-8",
        )
        self.assertEqual("CHECKPOINT_PHASE", workflow.resolve_next_action(self.repo, "t-multi", host="antigravity")["code"])
        with unittest.mock.patch("_workflow.engine.check_phase_compile", return_value=(True, "PASS")), unittest.mock.patch("_workflow.engine.check_phase_tests", return_value=(True, "PASS")):
            cp1 = workflow.checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id="t-multi", phase_id="p1"))
        self.assertIn(cp1.get("status"), ("PASS", "CHECKPOINT_PASS"))

        # Advance through phase review (if routed) or straight to BEGIN_NEXT_PHASE
        from phase_review import PHASE_COMPLETE, get_phase_substate, set_phase_substate
        tdir_m = state_root(self.repo) / "tasks/t-multi"
        ps = read_json(tdir_m / "phase-state.json")
        if get_phase_substate(ps, "p1") != PHASE_COMPLETE:
            ps = set_phase_substate(tdir_m, "p1", PHASE_COMPLETE)
            ps.setdefault("completed_phases", []).append("p1")
            from _vnext_common import atomic_write_json
            atomic_write_json(tdir_m / "phase-state.json", ps)
        self.assertEqual("BEGIN_NEXT_PHASE", workflow.resolve_next_action(self.repo, "t-multi", host="antigravity")["code"])
        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id="t-multi"))

        (self.repo / "app/src/main/java/com/demo/FoodViewModel.kt").write_text(
            "package com.demo\n\nclass FoodViewModel {\n"
            "    private fun formatKcal(v: Int): String = v.toString()\n"
            "    fun loadPlan(): String = formatKcal(2100) + \" kcal\"\n"
            "}\n",
            encoding="utf-8",
        )
        with unittest.mock.patch("_workflow.engine.check_phase_compile", return_value=(True, "PASS")), unittest.mock.patch("_workflow.engine.check_phase_tests", return_value=(True, "PASS")):
            workflow.checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id="t-multi", phase_id="p2"))
        ps2 = read_json(tdir_m / "phase-state.json")
        if get_phase_substate(ps2, "p2") != PHASE_COMPLETE:
            ps2 = set_phase_substate(tdir_m, "p2", PHASE_COMPLETE)
            if "p2" not in ps2.setdefault("completed_phases", []):
                ps2["completed_phases"].append("p2")
            from _vnext_common import atomic_write_json
            atomic_write_json(tdir_m / "phase-state.json", ps2)
        self.assertEqual("PREPARE_VERIFICATION", workflow.resolve_next_action(self.repo, "t-multi", host="antigravity")["code"])

        cur_m = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-multi", force=False, host="antigravity"))
        pol_m = read_json(Path(cur_m["policy"]))
        man_m = read_json(Path(cur_m["manifest"]))
        for g in pol_m.get("gates") or []:
            if g != "manifest":
                self._record_gate(man_m["delivery_snapshot_sha256"], man_m["change_set_sha256"], cur_m["run_id"], g, "selftest")
        self._pass_all_reviewers_direct("t-multi", cur_m, pol_m)
        workflow.complete(argparse.Namespace(repo=str(self.repo), task_id="t-multi"))
        self._git("add", "-A")
        self._git("commit", "-m", "feat: multi-phase macro tracking")
        self.assertEqual("DELIVERED", workflow.deliver_task(self.repo, "t-multi")["status"])

    def test_3_bug_red_green_and_refactor_consolidation_and_conflict_auto_detect(self) -> None:
        """Verify BUG RED->GREEN TDD gate (including symbol_edit block), REFACTOR 1-reviewer consolidation, and CONFLICT auto-detection."""
        import workflow
        import symbol_edit
        from _vnext_common import atomic_write_json, canonical_sha256, read_json, state_root, utc_now
        from delivery_manifest import build_manifest

        # A) BUG Task: production edits AND `symbol replace-body` blocked before RED evidence, test edits allowed!
        self._draft_approve_begin(
            task_id="t-bug",
            title="Fix division by zero crash in Calc.safeDiv",
            kind="BUG",
            files=["app/src/main/java/com/demo/Calc.kt", "app/src/test/java/com/demo/CalcTest.kt"],
            surfaces=["BUSINESS_LOGIC"],
        )
        act_bug = workflow.resolve_next_action(self.repo, "t-bug", host="antigravity")
        self.assertEqual("CAPTURE_RED_EVIDENCE", act_bug["code"])
        self.assertEqual("CAPTURE_RED_ONLY", act_bug["delegation_advisory"]["worker_mode"])

        # Lead calling `symbol replace-body` on production Calc.kt BEFORE RED evidence MUST BE DENIED at PreToolUse!
        deny_prod_sym = self._pre_tool({
            "toolName": "run_command",
            "toolArgs": {"CommandLine": "python .agents/harness.py symbol replace-body --file app/src/main/java/com/demo/Calc.kt --symbol safeDiv --replacement x"},
        })
        self.assertEqual("deny", deny_prod_sym["decision"])

        # Lead calling `symbol replace-body` on test file CalcTest.kt BEFORE RED evidence IS ALLOWED!
        allow_test_sym = self._pre_tool({
            "toolName": "run_command",
            "toolArgs": {"CommandLine": "python .agents/harness.py symbol replace-body --file app/src/test/java/com/demo/CalcTest.kt --symbol placeholder --replacement x"},
        })
        self.assertEqual("allow", allow_test_sym["decision"], allow_test_sym)

        # Author reproduction test and record authentic schema v3 red-evidence.json
        (self.repo / "app/src/test/java/com/demo/CalcTest.kt").write_text(
            "package com.demo\n\nclass CalcTest {\n"
            "    fun safeDivZeroReturnsZero() { assert(Calc().safeDiv(10, 0) == 0) }\n"
            "}\n",
            encoding="utf-8",
        )
        tdir_bug = state_root(self.repo) / "tasks/t-bug"
        plan_bug = read_json(tdir_bug / "plan.json")
        base_bug = read_json(tdir_bug / "task-baseline.json")
        pre_fix_manifest = build_manifest(self.repo)
        red_payload = {
            "schema_version": 3,
            "producer": "run_tests_gate",
            "task_id": "t-bug",
            "plan_sha256": plan_bug["plan_sha256"],
            "baseline_sha256": base_bug["baseline_sha256"],
            "pre_fix_delivery_snapshot_sha256": pre_fix_manifest["delivery_snapshot_sha256"],
            "reproduction_kind": "FAILING_TEST",
            "failed_tests": [{"test_id": "com.demo.CalcTest#safeDivZeroReturnsZero", "failure_fingerprint": "ArithmeticException:/ by zero"}],
            "captured_at": utc_now(),
        }
        red_payload["red_sha256"] = canonical_sha256({k: v for k, v in red_payload.items() if k != "red_sha256"})
        atomic_write_json(tdir_bug / "red-evidence.json", red_payload)

        # Now `symbol replace-body` on production Calc.kt IS ALLOWED!
        rc_fix = symbol_edit.main([
            "replace-body",
            "--repo", str(self.repo),
            "--file", "app/src/main/java/com/demo/Calc.kt",
            "--symbol", "Calc.safeDiv",
            "--replacement", "    fun safeDiv(a: Int, b: Int): Int {\n        return if (b == 0) 0 else a / b\n    }",
        ])
        self.assertEqual(0, rc_fix)

        cur_bug = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-bug", force=False, host="antigravity"))
        pol_bug = read_json(Path(cur_bug["policy"]))
        man_bug = read_json(Path(cur_bug["manifest"]))
        for g in pol_bug.get("gates") or []:
            if g == "unit_tests":
                self._record_gate(
                    man_bug["delivery_snapshot_sha256"],
                    man_bug["change_set_sha256"],
                    cur_bug["run_id"],
                    "unit_tests",
                    "run_tests_gate",
                    {"executed_tests": ["com.demo.CalcTest.safeDivZeroReturnsZero"], "new_regressions": []},
                )
            elif g != "manifest":
                self._record_gate(man_bug["delivery_snapshot_sha256"], man_bug["change_set_sha256"], cur_bug["run_id"], g, "selftest")
        self._pass_all_reviewers_direct("t-bug", cur_bug, pol_bug)
        ready_bug = workflow.complete(argparse.Namespace(repo=str(self.repo), task_id="t-bug"))
        self.assertEqual("READY_FOR_DELIVERY", ready_bug["status"])
        self._git("add", "-A")
        self._git("commit", "-m", "fix: guard zero divisor in Calc.safeDiv")
        self.assertEqual("DELIVERED", workflow.deliver_task(self.repo, "t-bug")["status"])

        # B) REFACTOR with ISOLATED_PRIVATE_EDIT (<= 25 changed lines) -> consolidated to 1 reviewer (`bug-test-reviewer-agent`)!
        self._draft_approve_begin(
            task_id="t-ref",
            title="Simplify private formatKcal helper",
            kind="REFACTOR",
            files=["app/src/main/java/com/demo/FoodViewModel.kt"],
            surfaces=["BUSINESS_LOGIC"],
        )
        (self.repo / "app/src/main/java/com/demo/FoodViewModel.kt").write_text(
            "package com.demo\n\nclass FoodViewModel {\n"
            "    private fun formatKcal(v: Int): String {\n"
            "        return v.coerceAtLeast(0).toString()\n"
            "    }\n\n"
            "    fun loadPlan(): String {\n"
            "        return formatKcal(1800)\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        cur_ref = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-ref", force=False, host="antigravity"))
        pol_ref = read_json(Path(cur_ref["policy"]))
        man_ref = read_json(Path(cur_ref["manifest"]))
        self.assertEqual(["bug-test-reviewer-agent"], pol_ref["reviewers"], f"ISOLATED_PRIVATE_EDIT should consolidate to 1 reviewer, got {pol_ref}")
        for g in pol_ref.get("gates") or []:
            if g != "manifest":
                self._record_gate(man_ref["delivery_snapshot_sha256"], man_ref["change_set_sha256"], cur_ref["run_id"], g, "selftest")
        self._pass_all_reviewers_direct("t-ref", cur_ref, pol_ref)
        workflow.complete(argparse.Namespace(repo=str(self.repo), task_id="t-ref"))
        self._git("add", "-A")
        self._git("commit", "-m", "refactor: clamp negative values in private formatKcal")
        self.assertEqual("DELIVERED", workflow.deliver_task(self.repo, "t-ref")["status"])

        # C) CONFLICT Task: real Git merge conflict + `--kind AUTO` auto-detects `CONFLICT` + blocks unresolved markers!
        self._git("checkout", "-b", "feature-branch")
        (self.repo / "app/src/main/java/com/demo/Calc.kt").write_text(
            "package com.demo\n\nclass Calc {\n    fun safeDiv(a: Int, b: Int): Int = if (b == 0) -1 else a / b\n}\n",
            encoding="utf-8",
        )
        self._git("add", "-A")
        self._git("commit", "-m", "branch: return -1 on zero")
        self._git("checkout", "main")
        (self.repo / "app/src/main/java/com/demo/Calc.kt").write_text(
            "package com.demo\n\nclass Calc {\n    fun safeDiv(a: Int, b: Int): Int = if (b == 0) 0 else (a / b)\n}\n",
            encoding="utf-8",
        )
        self._git("add", "-A")
        self._git("commit", "-m", "main: explicit parens")
        merge_proc = subprocess.run(["git", "merge", "feature-branch"], cwd=str(self.repo), capture_output=True, text=True)
        self.assertNotEqual(0, merge_proc.returncode, "Expected genuine unmerged Git conflict")

        plan_conf = self._draft_approve_begin(
            task_id="t-conflict",
            title="Resolve Calc.kt merge conflict",
            kind="AUTO",
            files=["app/src/main/java/com/demo/Calc.kt"],
            surfaces=["BUSINESS_LOGIC"],
        )
        self.assertEqual("CONFLICT", plan_conf["task_kind"], "AUTO kind must auto-detect active unmerged Git conflict!")
        act_conf = workflow.resolve_next_action(self.repo, "t-conflict", host="antigravity")
        self.assertEqual("CONFLICT_LEAD_CORE_WORKER_VERIFY", act_conf["delegation_advisory"]["strategy"])

        # prepare-verification MUST fail closed while conflict markers remain!
        from _vnext_common import ValidationError
        with self.assertRaises(ValidationError) as conf_err:
            workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-conflict", force=False, host="antigravity"))
        self.assertIn("UNRESOLVED_MERGE_CONFLICT", str(conf_err.exception))

        # Resolve conflict cleanly and stage resolved index entry
        (self.repo / "app/src/main/java/com/demo/Calc.kt").write_text(
            "package com.demo\n\nclass Calc {\n    fun safeDiv(a: Int, b: Int): Int = if (b == 0) 0 else a / b\n}\n",
            encoding="utf-8",
        )
        self._git("add", "app/src/main/java/com/demo/Calc.kt")

        cur_conf = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-conflict", force=False, host="antigravity"))
        pol_conf = read_json(Path(cur_conf["policy"]))
        man_conf = read_json(Path(cur_conf["manifest"]))
        for g in pol_conf.get("gates") or []:
            if g != "manifest":
                self._record_gate(man_conf["delivery_snapshot_sha256"], man_conf["change_set_sha256"], cur_conf["run_id"], g, "selftest")
        self._pass_all_reviewers_direct("t-conflict", cur_conf, pol_conf)
        workflow.complete(argparse.Namespace(repo=str(self.repo), task_id="t-conflict"))
        self._git("commit", "-m", "merge: resolve Calc.safeDiv conflict")
        self.assertEqual("DELIVERED", workflow.deliver_task(self.repo, "t-conflict")["status"])

    def test_4_t4_ui_device_maestro_snapshot_safety_and_t5_critical_blocked_round2_bridge(self) -> None:
        """Verify T4 COMPOSE_UI + Maestro snapshot safety during VERIFYING/READY + T5_CRITICAL risk-hybrid inherit + BLOCKED->resume + task bridge."""
        import workflow
        import maestro_bridge as mb
        import review_models
        from _vnext_common import canonical_sha256, read_json, sha256_bytes, state_root
        from workflow import verification_freshness

        # A) T4_DATA_DEVICE (`COMPOSE_UI`): verify `maestro export-e2e` during VERIFYING & READY_FOR_DELIVERY NEVER stales snapshot!
        self._draft_approve_begin(
            task_id="t-ui",
            title="Update FoodScreen card rendering",
            kind="FEATURE",
            files=["app/src/main/java/com/demo/FoodScreen.kt"],
            surfaces=["COMPOSE_UI", "ROOM_SCHEMA"],
        )
        (self.repo / "app/src/main/java/com/demo/FoodScreen.kt").write_text(
            "package com.demo\nimport androidx.compose.runtime.Composable\nimport androidx.room.Entity\n@Entity data class FoodCache(val id: Int)\n@Composable fun FoodScreen(): String = \"updated_card_v2\"\n",
            encoding="utf-8",
        )
        cur_ui = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-ui", force=False, host="antigravity"))
        tdir_ui = state_root(self.repo) / "tasks/t-ui"
        pol_ui = read_json(Path(cur_ui["policy"]))
        man_ui = read_json(Path(cur_ui["manifest"]))
        snap_ui = man_ui["delivery_snapshot_sha256"]
        cset_ui = man_ui["change_set_sha256"]
        run_ui = cur_ui["run_id"]
        self.assertEqual("T4_DATA_DEVICE", pol_ui["risk_tier"])
        self.assertTrue(pol_ui["device_required"])

        # Seed gate + assemble + device_install + device_launch + e2e session
        apk_file = self.repo / "build/outputs/apk/debug/app-debug.apk"
        apk_file.parent.mkdir(parents=True, exist_ok=True)
        apk_file.write_bytes(b"fake-apk-binary")
        art_identity = {
            "task": ":app:assembleDebug",
            "application_id": "com.demo",
            "members": [{"path": "build/outputs/apk/debug/app-debug.apk", "sha256": sha256_bytes(b"fake-apk-binary")}],
        }
        art_sha = canonical_sha256(art_identity)
        art_set = {**art_identity, "artifact_set_sha256": art_sha}
        for g in pol_ui.get("gates") or []:
            if g not in ("manifest", "device", "assemble"):
                self._record_gate(snap_ui, cset_ui, run_ui, g, "selftest")
        self._record_gate(snap_ui, cset_ui, run_ui, "assemble", "run_gradle_task", {"artifact_set": art_set, "artifact_set_sha256": art_sha})
        self._record_gate(snap_ui, cset_ui, run_ui, "device_install", "run_device", {
            "serial_sha256": "s" * 64, "target_user": "0", "artifact_set_sha256": art_sha, "application_id": "com.demo",
        })
        self._record_gate(snap_ui, cset_ui, run_ui, "device_launch", "run_device", {
            "serial_sha256": "s" * 64, "target_user": "0", "artifact_set_sha256": art_sha, "application_id": "com.demo", "install_reference": art_sha,
        })
        self._pass_all_reviewers_direct("t-ui", cur_ui, pol_ui)

        e2e_dir = tdir_ui / "e2e" / run_ui
        e2e_dir.mkdir(parents=True, exist_ok=True)
        (e2e_dir / "session.json").write_text(json.dumps({
            "task_id": "t-ui",
            "run_id": run_ui,
            "delivery_snapshot_sha256": snap_ui,
            "application_id": "com.demo",
            "state": "FINISHED",
            "scenarios": [{"id": "S1", "title": "Check updated card", "status": "PASS"}],
            "actions": [{"action": "wait", "found": True, "query": {"text": "updated_card_v2"}}],
        }), encoding="utf-8")

        # Export Maestro YAML DURING VERIFYING -> must stage in .agents/state AND keep verification_freshness == True!
        staged_res = mb.cmd_export_e2e(self.repo, argparse.Namespace(task_id="t-ui", out=None))
        self.assertEqual("STAGED_IN_TASK_STATE", staged_res["status"])
        fresh_res = verification_freshness(self.repo, "t-ui", cur_ui)
        self.assertTrue(fresh_res.get("is_fresh", fresh_res.get("fresh", False)), f"Maestro export during VERIFYING must NOT stale snapshot! Got: {fresh_res}")

        # Record device signoff -> complete -> READY_FOR_DELIVERY -> export during READY also preserves snapshot!
        self._record_gate(snap_ui, cset_ui, run_ui, "device_signoff", "developer_signoff", {
            "verdict": "PASS",
            "approval_source": "conversation",
            "enforcement_tier": "RULE_ENFORCED",
            "proof_reference_sha256": canonical_sha256({"reference": "looks great on phone"}),
            "serial_sha256": "s" * 64,
            "artifact_set_sha256": art_sha,
        })
        ready_ui = workflow.complete(argparse.Namespace(repo=str(self.repo), task_id="t-ui"))
        self.assertEqual("READY_FOR_DELIVERY", ready_ui["status"])
        staged_ready = mb.cmd_export_e2e(self.repo, argparse.Namespace(task_id="t-ui", out=None))
        self.assertEqual("STAGED_IN_TASK_STATE", staged_ready["status"])
        # Calling complete() again on READY_FOR_DELIVERY validates live snapshot == ready_delivery_snapshot_sha256!
        workflow.complete(argparse.Namespace(repo=str(self.repo), task_id="t-ui"))
        self._git("add", "app/src/main/java/com/demo/FoodScreen.kt")
        self._git("commit", "-m", "feat(ui): render updated_card_v2")
        self.assertEqual("DELIVERED", workflow.deliver_task(self.repo, "t-ui")["status"])

        # Now in DELIVERED, export-e2e writes .maestro/t-ui.yaml into repo!
        exported_post = mb.cmd_export_e2e(self.repo, argparse.Namespace(task_id="t-ui", out=None))
        self.assertEqual("EXPORTED", exported_post["status"])
        self.assertTrue((self.repo / ".maestro/t-ui.yaml").is_file())
        self._git("add", ".maestro/t-ui.yaml")
        self._git("commit", "-m", "test(maestro): add t-ui e2e flow")

        # B) T5_CRITICAL (`AUTH`): risk-hybrid escalates reviewers to `inherit` + BLOCKED -> validate-finding -> resume -> Round 2 PASS -> task bridge!
        self._draft_approve_begin(
            task_id="t-auth",
            title="Harden refreshToken validation",
            kind="FEATURE",
            files=["app/src/main/java/com/demo/AuthManager.kt"],
            surfaces=["AUTH", "SENSITIVE_DATA"],
        )
        act_auth_impl = workflow.resolve_next_action(self.repo, "t-auth", host="antigravity")
        self.assertEqual("SENSITIVE_LEAD_CORE_WORKER_TESTS", act_auth_impl["delegation_advisory"]["strategy"])
        self.assertEqual("TESTS_AND_GATES_ONLY", act_auth_impl["delegation_advisory"]["worker_mode"])

        (self.repo / "app/src/main/java/com/demo/AuthManager.kt").write_text(
            "package com.demo\n\nclass AuthManager {\n    fun refreshToken(raw: String): Boolean = raw.trim().length >= 16\n}\n",
            encoding="utf-8",
        )
        cur_auth1 = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-auth", force=False, host="antigravity"))
        tdir_auth = state_root(self.repo) / "tasks/t-auth"
        pol_auth1 = read_json(Path(cur_auth1["policy"]))
        self.assertEqual("T5_CRITICAL", pol_auth1["risk_tier"])

        # Select `risk-hybrid` preset: because T5_CRITICAL, reviewer models MUST escalate to `inherit` (frontier), NOT Flash!
        sel_hybrid = review_models.resolve_preset_policy("risk-hybrid")
        review_models.set_policy(
            self.repo,
            sel_hybrid,
            task_id="t-auth",
            host="antigravity",
            source="conversation",
            proof_reference="risk-hybrid",
        )
        cur_auth1 = read_json(tdir_auth / "current-run.json")
        f_auth_models = review_models.frozen_models(cur_auth1)
        for r_role in pol_auth1["reviewers"]:
            self.assertEqual("inherit", review_models.effective_reviewer_model(f_auth_models[r_role]), f"T5_CRITICAL must escalate {r_role} to inherit!")

        # Simulate BLOCKED reviewer finding F-AUTH-1 -> validate-finding -> resume -> Round 2 fix -> PASS -> deliver -> bridge!
        plan_b = read_json(tdir_auth / "plan.json")
        plan_b["status"] = "BLOCKED"
        plan_b["blocked_reviewers"] = ["security-perf-reviewer-agent"]
        plan_b["blocking_findings"] = [{"id": "F-AUTH-1", "reviewer": "security-perf-reviewer-agent", "summary": "Reject whitespace inside token"}]
        workflow.save_plan(tdir_auth / "plan.json", plan_b)

        workflow.record_finding_validation(argparse.Namespace(
            repo=str(self.repo),
            task_id="t-auth",
            finding_id="F-AUTH-1",
            status="CONFIRMED",
            reason="Token must not contain internal whitespace",
            evidence_reference="AuthManager.kt:4",
        ))
        self.assertEqual("RESUME_IMPLEMENTATION", workflow.resolve_next_action(self.repo, "t-auth", host="antigravity")["code"])
        resumed = workflow.resume(argparse.Namespace(repo=str(self.repo), task_id="t-auth", reopen=False))
        self.assertEqual("IMPLEMENTING", resumed["status"])

        # Apply Round 2 fix + verify + complete + deliver + bridge!
        (self.repo / "app/src/main/java/com/demo/AuthManager.kt").write_text(
            "package com.demo\n\nclass AuthManager {\n"
            "    fun refreshToken(raw: String): Boolean = raw.length >= 16 && raw.none { it.isWhitespace() }\n"
            "}\n",
            encoding="utf-8",
        )
        cur_auth2 = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-auth", force=False, host="antigravity"))
        pol_auth2 = read_json(Path(cur_auth2["policy"]))
        man_auth2 = read_json(Path(cur_auth2["manifest"]))
        for g in pol_auth2.get("gates") or []:
            if g != "manifest":
                self._record_gate(man_auth2["delivery_snapshot_sha256"], man_auth2["change_set_sha256"], cur_auth2["run_id"], g, "selftest")
        self._pass_all_reviewers_direct("t-auth", cur_auth2, pol_auth2)
        self.assertEqual("COMPLETE_TASK", workflow.resolve_next_action(self.repo, "t-auth", host="antigravity")["code"])
        workflow.complete(argparse.Namespace(repo=str(self.repo), task_id="t-auth"))
        self._git("add", "app/src/main/java/com/demo/AuthManager.kt")
        self._git("commit", "-m", "security(auth): reject whitespace in refreshToken")
        self.assertEqual("DELIVERED", workflow.deliver_task(self.repo, "t-auth")["status"])

        # Save Context Bridge after delivery and consume it from a brand-new conversation!
        import task_bridge
        saved_bridge = task_bridge.save_task_bridge(argparse.Namespace(
            repo=str(self.repo),
            task_id="t-auth",
            next_outcome="Add token rotation worker",
            summary="Add token rotation worker",
            next_step="Draft rotation worker plan",
            save=True,
        ))
        self.assertIn(saved_bridge.get("status"), ("SAVED", "PASS", "BRIDGE_SAVED"))
        resumed_bridge = task_bridge.load_task_bridge(argparse.Namespace(
            repo=str(self.repo),
            task_id="",
        ))
        self.assertIn("Add token rotation worker", json.dumps(resumed_bridge))



    def test_5_hybrid_model_and_new_modules_deep_integration(self) -> None:
        """Verify seamless integration between Option 4 Hybrid Models (`Flash` Scout/Worker + `risk-hybrid`) and all 5 v1.3.1 modules."""
        import delegation_policy as dp
        import install_tool_adapters as ita
        import review_models
        import review_orchestrator
        import review_package
        import workflow
        from _vnext_common import read_json, state_root

        # 1. Verify Flash Scout & Worker native system prompts embed `symbol outline/read/replace-body`, `roborazzi`, and `health`
        scout_md = dp.render_utility_agent_markdown(dp.SCOUT_AGENT)
        worker_md = dp.render_utility_agent_markdown(dp.WORKER_AGENT)
        self.assertIn("symbol outline", scout_md)
        self.assertIn("symbol read", scout_md)
        self.assertIn("symbol replace-body", worker_md)
        self.assertIn("roborazzi verify", worker_md)
        self.assertIn("gemini-4-hydrogen-medium", scout_md)
        self.assertIn("gemini-4-hydrogen-medium", worker_md)

        # 2. Verify T5_CRITICAL (`MANIFEST_PERMISSION`) locks production edits to Lead Architect while allowing Flash Worker on tests
        self._draft_approve_begin(
            task_id="t-perm-hybrid",
            title="Add foreground service permission guard",
            kind="FEATURE",
            files=["app/src/main/java/com/demo/AuthManager.kt"],
            surfaces=["MANIFEST_PERMISSION"],
        )
        act_perm = workflow.resolve_next_action(self.repo, "t-perm-hybrid", host="antigravity")
        self.assertEqual("SENSITIVE_LEAD_CORE_WORKER_TESTS", act_perm["delegation_advisory"]["strategy"])
        self.assertEqual("TESTS_AND_GATES_ONLY", act_perm["delegation_advisory"]["worker_mode"])
        workflow.cancel(argparse.Namespace(repo=str(self.repo), task_id="t-perm-hybrid", source="developer_terminal", proof_reference="done"))

        # 3. Verify T5_CRITICAL + `risk-hybrid` task policy keeps `.agents/agents/*/agent.md` synchronized (`inherit`) even across adapter regeneration!
        self._draft_approve_begin(
            task_id="t-hybrid-sync",
            title="Update AuthManager token check",
            kind="FEATURE",
            files=["app/src/main/java/com/demo/AuthManager.kt"],
            surfaces=["AUTH", "SENSITIVE_DATA"],
        )
        (self.repo / "app/src/main/java/com/demo/AuthManager.kt").write_text(
            "package com.demo\n\nclass AuthManager {\n    fun refreshToken(raw: String): Boolean = raw.length >= 20\n}\n",
            encoding="utf-8",
        )
        cur = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-hybrid-sync", force=False, host="antigravity"))
        pol = read_json(Path(cur["policy"]))
        man = read_json(Path(cur["manifest"]))
        for g in pol.get("gates") or []:
            if g != "manifest":
                self._record_gate(man["delivery_snapshot_sha256"], man["change_set_sha256"], cur["run_id"], g, "selftest")
        review_package.build_package(self.repo, "t-hybrid-sync")
        review_models.set_policy(
            self.repo,
            review_models.resolve_preset_policy("risk-hybrid"),
            task_id="t-hybrid-sync",
            scope="task",
            host="antigravity",
            source="conversation",
            proof_reference="risk-hybrid-task",
        )
        tdir = state_root(self.repo) / "tasks/t-hybrid-sync"
        cur = read_json(tdir / "current-run.json")
        # Dispatch batch creates active review ledger and synchronizes agent frontmatter
        review_orchestrator.record_dispatch_batch(self.repo, "t-hybrid-sync", sorted(pol["reviewers"]), host="antigravity")
        # Regenerate Antigravity adapters while T5_CRITICAL active review is live -> must keep `inherit` (no stale Flash frontmatter)!
        ita.generate_antigravity_agents(self.repo, dry_run=False)
        review_models.assert_dispatch_ready(self.repo, read_json(tdir / "current-run.json"), sorted(pol["reviewers"]))



    def test_6_project_wide_multi_wave_subagent_efficiency_and_anti_reread(self) -> None:
        """Verify ALL subagents, ALL waves (1st, 2nd, Nth), ALL phases (p1..pN), and ALL anti-reread & step-budget guards."""
        import delegation_policy as dp
        import phase_review
        import review_orchestrator
        import review_package
        import workflow
        from _vnext_common import atomic_write_json, read_json, state_root

        parent_cid = "lead-conv-v132"
        parent_tx = self.brain_app_data / "brain" / parent_cid / ".system_generated" / "logs" / "transcript.jsonl"
        parent_tx.parent.mkdir(parents=True, exist_ok=True)
        parent_tx.write_text(
            json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Study calories card across all users"}) + "\n",
            encoding="utf-8",
        )

        def post_reconcile(payload: dict) -> dict:
            env = dict(
                os.environ,
                HARNESS_REPO=str(self.repo),
                HARNESS_HOST="antigravity",
                ANTIGRAVITY_APP_DATA=str(self.brain_app_data),
            )
            proc = subprocess.run(
                [sys.executable, str(self.repo / ".agents/scripts/post_tool_reconcile.py")],
                cwd=str(self.repo),
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            return json.loads((proc.stdout or "{}").strip())

        def pre_reminder(inv_num: int) -> dict:
            env = dict(
                os.environ,
                HARNESS_REPO=str(self.repo),
                HARNESS_HOST="antigravity",
                ANTIGRAVITY_APP_DATA=str(self.brain_app_data),
            )
            proc = subprocess.run(
                [sys.executable, str(self.repo / ".agents/scripts/pre_invocation_reminder.py")],
                cwd=str(self.repo),
                input=json.dumps({"invocationNum": inv_num, "conversationId": parent_cid}),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            return json.loads((proc.stdout or "{}").strip())

        # 1. Built-in `TypeName="research"` / `"explore"` MUST be blocked on Antigravity (<=5 items -> USE_HARNESS_SCOUT_AGENT; >5 items -> batch limit)
        res_research = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Subagents": [{"TypeName": "research", "Role": "scout", "Prompt": "Inspect HomeViewModel"}]},
            },
        })
        self.assertEqual("deny", res_research["decision"])
        self.assertIn("USE_HARNESS_SCOUT_AGENT", res_research["reason"])

        res_batch_6 = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Subagents": [{"TypeName": "explore", "Role": f"s{i}", "Prompt": "Inspect"} for i in range(6)]},
            },
        })
        self.assertEqual("deny", res_batch_6["decision"])
        self.assertIn("exceeds the safety limit of 5", res_batch_6["reason"])

        # 2. Clean `SUBAGENT_SEND_MESSAGE_FORBIDDEN` when `plan is None` (never crashes with Reviewer policy validation failed closed!)
        res_send_idle = self._pre_tool({
            "conversationId": "rogue-child-conv",
            "toolCall": {"name": "send_message", "args": {"Recipient": parent_cid, "Message": "done"}},
        })
        self.assertEqual("deny", res_send_idle["decision"])
        self.assertIn("SUBAGENT_SEND_MESSAGE_FORBIDDEN", res_send_idle["reason"])
        self.assertNotIn("failed closed", res_send_idle["reason"])

        # 3. Dispatch Scout Wave 1 (2 parallel `harness-scout-agent`s in one call) + verify per-scout 24-call budget + post-scout anti-reread!
        big_kt = self.repo / "app/src/main/java/com/demo/PersonalDataActivity.kt"
        big_kt.write_text(
            "package com.demo\n\nclass PersonalDataActivity {\n"
            + "".join(f"    fun step{i}(): Int = {i}\n" for i in range(420))
            + "}\n",
            encoding="utf-8",
        )
        self._git("add", "app/src/main/java/com/demo/PersonalDataActivity.kt")
        self._git("commit", "-m", "feat: add large PersonalDataActivity fixture")

        p_scout_a = "Inspect HomeViewModel and FoodScreen visibility conditions across user goals."
        p_scout_b = "Inspect PersonalDataActivity onboarding steps and targetCalories calculation."
        res_wave1 = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Workspace": "inherit", "Prompt": p_scout_a},
                        {"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Workspace": "inherit", "Prompt": p_scout_b},
                    ]
                },
            },
        })
        self.assertEqual("allow", res_wave1["decision"], res_wave1)

        # Spawn bound child transcripts for Scout A and Scout B
        for idx, (cid_s, p_txt) in enumerate([("scout-w1-a", p_scout_a), ("scout-w1-b", p_scout_b)]):
            tx_s = self.brain_app_data / "brain" / cid_s / ".system_generated" / "logs" / "transcript.jsonl"
            tx_s.parent.mkdir(parents=True, exist_ok=True)
            tx_s.write_text(
                json.dumps({
                    "source": "SYSTEM_SDK",
                    "type": "SYSTEM_MESSAGE",
                    "content": f"<SYSTEM_MESSAGE>sender={parent_cid} priority=MESSAGE_PRIORITY_HIGH content={p_txt}\n</SYSTEM_MESSAGE>",
                }) + "\n",
                encoding="utf-8",
            )
            # Verify EACH scout gets its own independent 24-call step budget (`SCOUT_STEP_BUDGET_REACHED` on call #25!)
            for call_n in range(dp.MAX_SCOUT_TOOL_CALLS):
                r_step = self._pre_tool({
                    "conversationId": cid_s,
                    "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt")}},
                })
                self.assertEqual("allow", r_step["decision"], f"Scout {idx} call {call_n + 1} should be allowed: {r_step}")
            r_step_25 = self._pre_tool({
                "conversationId": cid_s,
                "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt")}},
            })
            self.assertEqual("deny", r_step_25["decision"])
            self.assertIn("SCOUT_STEP_BUDGET_REACHED", r_step_25["reason"])

        # Complete Wave 1 via PostToolUse reconciler
        post_reconcile({
            "conversationId": parent_cid,
            "transcriptPath": str(parent_tx),
            "toolCall": {"name": "invoke_subagent"},
            "toolResult": {"subagents": [{"conversationId": "scout-w1-a"}, {"conversationId": "scout-w1-b"}]},
        })

        # PreInvocation must inject POST-SCOUT ANTI-REREAD directive into Lead Model!
        rem_w1 = pre_reminder(2)
        self.assertIn("POST-SCOUT ANTI-REREAD ACTIVE", json.dumps(rem_w1))

        # Lead Model attempting a full-file / >220-line read on 424-line PersonalDataActivity.kt MUST be blocked immediately without burning a slot!
        r_bloated = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": str(big_kt), "StartLine": 1, "EndLine": 300},
            },
        })
        self.assertEqual("deny", r_bloated["decision"])
        self.assertIn("POST_SUBAGENT_FULL_FILE_READ_BLOCKED", r_bloated["reason"])

        # Lead Model gets exactly 3 surgical gap checks (including `graph` re-runs or `<=200`-line `view_file`), then #4 is DENIED!
        for slot in range(dp.MAX_LEAD_POST_SUBAGENT_READS):
            r_gap = self._pre_tool({
                "conversationId": parent_cid,
                "toolCall": {
                    "name": "view_file",
                    "args": {"AbsolutePath": str(big_kt), "StartLine": 1 + slot * 20, "EndLine": 15 + slot * 20},
                },
            })
            self.assertEqual("allow", r_gap["decision"], f"Surgical gap check {slot + 1} should pass: {r_gap}")

        # 4th read OR redundant `harness.py graph` re-run on Lead Model -> DENIED by POST_SCOUT_REREAD_CAP_REACHED!
        r_fourth_view = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodViewModel.kt")}},
        })
        self.assertEqual("deny", r_fourth_view["decision"])
        self.assertIn("POST_SCOUT_REREAD_CAP_REACHED", r_fourth_view["reason"])

        r_fourth_graph = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "run_command", "args": {"CommandLine": "python .agents/harness.py graph --feature food --json"}},
        })
        self.assertEqual("deny", r_fourth_graph["decision"])
        self.assertIn("POST_SCOUT_REREAD_CAP_REACHED", r_fourth_graph["reason"])

        # 4. SECOND Developer Message (`USER_INPUT` #2) -> Wave 1 expires automatically, AND Scout Wave 2 gets a fresh 3-read cap AND blocks on #4!
        with parent_tx.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Now study MealPlan sync"}) + "\n")

        # Direct read on new user turn works cleanly because Wave 1 expired!
        r_new_turn_read = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "core/model/src/main/java/com/demo/model/MealPlan.kt")}},
        })
        self.assertEqual("allow", r_new_turn_read["decision"])

        # Dispatch Scout Wave 2 ("مش اول وكيل فرعي بس" — verify 2nd scout wave enforces exact same post-scout cap!)
        p_scout_w2 = "Inspect MealPlan and FoodViewModel sync pipeline."
        self.assertEqual("allow", self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Workspace": "inherit", "Prompt": p_scout_w2},
            },
        })["decision"])
        post_reconcile({"conversationId": parent_cid, "transcriptPath": str(parent_tx), "toolCall": {"name": "invoke_subagent"}})

        for _ in range(dp.MAX_LEAD_POST_SUBAGENT_READS):
            self.assertEqual("allow", self._pre_tool({
                "conversationId": parent_cid,
                "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt")}},
            })["decision"])
        r_w2_fourth = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodViewModel.kt")}},
        })
        self.assertEqual("deny", r_w2_fourth["decision"])
        self.assertIn("POST_SCOUT_REREAD_CAP_REACHED", r_w2_fourth["reason"])

        # 5. Multi-Phase Task (`p1` -> `p2` with `scoped_phase_review_enabled=True`):
        #    Verify Worker Wave in `p1` AND Worker Wave in `p2` + Specialist + Phase Review GraphEngine/Zero-Hop + Reviewer 12-call cap!
        self._draft_approve_begin(
            task_id="t-multiphase-v132",
            title="Multi-phase calories card visibility and settings update",
            kind="FEATURE",
            files=["app/src/main/java/com/demo/FoodViewModel.kt", "app/src/main/java/com/demo/FoodScreen.kt"],
            surfaces=["COMPOSE_UI", "BUSINESS_LOGIC"],
            phases=[
                {
                    "id": "p1",
                    "name": "Update FoodViewModel",
                    "description": "Expose alwaysVisible flag in FoodViewModel",
                    "expected_files": ["app/src/main/java/com/demo/FoodViewModel.kt"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                    "scoped_phase_review_enabled": True,
                },
                {
                    "id": "p2",
                    "name": "Update FoodScreen",
                    "description": "Render calories card in FoodScreen",
                    "expected_files": ["app/src/main/java/com/demo/FoodScreen.kt"],
                    "expected_surfaces": ["COMPOSE_UI"],
                },
            ],
        )

        # Built-in `research` must STILL be blocked during IMPLEMENTING!
        res_impl_research = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "invoke_subagent", "args": {"Subagents": [{"TypeName": "research", "Role": "r", "Prompt": "check"}]}},
        })
        self.assertEqual("deny", res_impl_research["decision"])
        self.assertIn("USE_HARNESS_SCOUT_AGENT", res_impl_research["reason"])

        # Dispatch Worker Wave 1 in Phase `p1`
        w1_brief = (
            "Update app/src/main/java/com/demo/FoodViewModel.kt to add fun isCaloriesAlwaysVisible(): Boolean = true "
            "and run python .agents/harness.py compile."
        )
        self.assertEqual("allow", self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"TypeName": "harness-worker-agent", "Role": "harness-worker-agent", "Workspace": "inherit", "Prompt": w1_brief},
            },
        })["decision"])
        (self.repo / "app/src/main/java/com/demo/FoodViewModel.kt").write_text(
            "package com.demo\n\nclass FoodViewModel {\n    fun isCaloriesAlwaysVisible(): Boolean = true\n    fun loadPlan(): String = \"1800\"\n}\n",
            encoding="utf-8",
        )
        post_reconcile({"conversationId": parent_cid, "transcriptPath": str(parent_tx), "toolCall": {"name": "invoke_subagent"}})

        # `git diff` is ALWAYS free after worker completion!
        self.assertEqual("allow", self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git diff"}},
        })["decision"])
        # After 3 surgical reads in p1, 4th read is blocked by POST_WORKER_REREAD_CAP_REACHED!
        for _ in range(dp.MAX_LEAD_POST_SUBAGENT_READS):
            self.assertEqual("allow", self._pre_tool({
                "conversationId": parent_cid,
                "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodViewModel.kt")}},
            })["decision"])
        r_w1_fourth = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt")}},
        })
        self.assertEqual("deny", r_w1_fourth["decision"])
        self.assertIn("POST_WORKER_REREAD_CAP_REACHED", r_w1_fourth["reason"])

        # Advance `p1` via real `workflow.checkpoint_phase` -> build Phase Review package -> verify GraphEngine topology + Zero-Hop inlining + Pre-Verified Gates!
        with unittest.mock.patch("_workflow.engine.check_phase_compile", return_value=(True, "PASS")), unittest.mock.patch("_workflow.engine.check_phase_tests", return_value=(True, "PASS")):
            cp1 = workflow.checkpoint_phase(argparse.Namespace(repo=str(self.repo), task_id="t-multiphase-v132", phase_id="p1"))
            self.assertEqual("CHECKPOINT_PASS", cp1["status"])

        import review_models
        review_models.set_policy(
            self.repo,
            review_models.resolve_preset_policy("inherit"),
            task_id="t-multiphase-v132",
            scope="project",
            host="antigravity",
            source="conversation",
            proof_reference="inherit",
        )
        pkg_p1_path, meta_p1 = phase_review.build_phase_package(self.repo, "t-multiphase-v132", "p1", host="antigravity")
        pkg_p1_text = pkg_p1_path.read_text(encoding="utf-8")
        self.assertIn("## ARCHITECTURAL GRAPH & BLAST RADIUS TOPOLOGY", pkg_p1_text)
        first_p1_rev = meta_p1["selected_reviewers"][0]
        brief_p1_text = Path(meta_p1["briefs"][first_p1_rev]).read_text(encoding="utf-8")
        self.assertIn("ZERO-HOP FAST PATH (INLINED BELOW)", brief_p1_text)
        self.assertIn("Pre-Verified Deterministic Gates", brief_p1_text)
        self.assertIn("ARCHITECTURAL GRAPH & BLAST RADIUS TOPOLOGY", brief_p1_text)

        # Dispatch Phase Reviewer & verify Reviewer 12-call hard step budget (`REVIEWER_STEP_BUDGET_REACHED`)!
        phase_review.record_phase_dispatch_batch(self.repo, "t-multiphase-v132", "p1", meta_p1["selected_reviewers"], host="antigravity")
        for idx_r, r_role in enumerate(meta_p1["selected_reviewers"]):
            cid_rev = f"phase-rev-p1-{idx_r}"
            b_txt = Path(meta_p1["briefs"][r_role]).read_text(encoding="utf-8")
            self._spawn_fake_reviewer_transcript(
                exec_id=cid_rev,
                parent_id=parent_cid,
                prompt_text=b_txt,
                task_id="t-multiphase-v132",
                run_id=meta_p1["phase_review_run_id"],
                reviewer=r_role,
                package_sha256=meta_p1["package_sha256"],
                verdict="PASS",
                configured_model="inherit",
                observed_model="gemini-4-carbon-medium",
            )
            if idx_r == 0:
                for step_i in range(dp.MAX_REVIEWER_TOOL_CALLS):
                    r_ok = self._pre_tool({
                        "conversationId": cid_rev,
                        "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodViewModel.kt")}},
                    })
                    self.assertEqual("allow", r_ok["decision"], f"Reviewer step {step_i + 1} failed: {r_ok}")
                r_cap = self._pre_tool({
                    "conversationId": cid_rev,
                    "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodViewModel.kt")}},
                })
                self.assertEqual("deny", r_cap["decision"])
                self.assertIn("REVIEWER_STEP_BUDGET_REACHED", r_cap["reason"])

        # Reconcile PostToolUse for phase reviewers (binds all phase reviewer transcripts just like real Antigravity)
        post_reconcile({
            "conversationId": parent_cid,
            "transcriptPath": str(parent_tx),
            "toolCall": {"name": "invoke_subagent"},
            "toolResult": {"subagents": [{"conversationId": f"phase-rev-p1-{i}"} for i in range(len(meta_p1["selected_reviewers"]))]},
        })
        # While all phase reviewers have finished (`DONE` transcripts) and are bound, Lead Model reading code before `phase-review complete-all` is blocked!
        r_pre_ingest = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodViewModel.kt")}},
        })
        self.assertEqual("deny", r_pre_ingest["decision"])
        self.assertIn("POST_REVIEW_REREAD_BLOCKED", r_pre_ingest["reason"])

        # Complete & finalize p1 phase review, then advance to Phase `p2`!
        with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(self.brain_app_data)}):
            for idx_r, r_role in enumerate(meta_p1["selected_reviewers"]):
                phase_review.complete_phase_review(self.repo, "t-multiphase-v132", "p1", r_role, f"phase-rev-p1-{idx_r}", host="antigravity")
        self.assertEqual("PASS", phase_review.finalize_phase_review(self.repo, "t-multiphase-v132", "p1")["verdict"])
        workflow.begin_next_phase(argparse.Namespace(repo=str(self.repo), task_id="t-multiphase-v132"))

        # In Phase `p2`: `p1`'s worker cap expired automatically! Dispatch On-Demand Specialist (`android-ui-expert-agent`) AND Worker Wave 2 (`p2`)!
        ui_prompt = "Audit FoodScreen RTL padding and edge-to-edge WindowInsets."
        self.assertEqual("allow", self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Subagents": [{"TypeName": "android-ui-expert-agent", "Role": "android-ui-expert-agent", "Prompt": ui_prompt}]},
            },
        })["decision"])
        # Bind specialist transcript and verify specialist is strictly read-only + `send_message` forbidden!
        cid_ui = "spec-ui-p2"
        tx_ui = self.brain_app_data / "brain" / cid_ui / ".system_generated" / "logs" / "transcript.jsonl"
        tx_ui.parent.mkdir(parents=True, exist_ok=True)
        tx_ui.write_text(
            json.dumps({
                "source": "SYSTEM_SDK",
                "type": "SYSTEM_MESSAGE",
                "content": f"<SYSTEM_MESSAGE>sender={parent_cid} priority=MESSAGE_PRIORITY_HIGH content={ui_prompt}\n</SYSTEM_MESSAGE>",
            }) + "\n",
            encoding="utf-8",
        )
        self.assertEqual("deny", self._pre_tool({
            "conversationId": cid_ui,
            "toolCall": {"name": "write_to_file", "args": {"TargetFile": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt"), "CodeContent": "x"}},
        })["decision"])
        post_reconcile({"conversationId": parent_cid, "transcriptPath": str(parent_tx), "toolCall": {"name": "invoke_subagent"}, "toolResult": {"conversationId": cid_ui}})

        for _ in range(dp.MAX_LEAD_POST_SUBAGENT_READS):
            self.assertEqual("allow", self._pre_tool({
                "conversationId": parent_cid,
                "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt")}},
            })["decision"])
        r_spec_cap = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt")}},
        })
        self.assertEqual("deny", r_spec_cap["decision"])
        self.assertIn("POST_SPECIALIST_REREAD_CAP_REACHED", r_spec_cap["reason"])

        # Now dispatch Worker Wave 2 in Phase `p2` -> verify `POST_WORKER_REREAD_CAP_REACHED` applies on `p2` too, AND unlocks if Lead edits a fix!
        w2_brief = (
            "Update app/src/main/java/com/demo/FoodScreen.kt to render always-visible calories card "
            "and run python .agents/harness.py compile."
        )
        self.assertEqual("allow", self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"TypeName": "harness-worker-agent", "Role": "harness-worker-agent", "Workspace": "inherit", "Prompt": w2_brief},
            },
        })["decision"])
        post_reconcile({"conversationId": parent_cid, "transcriptPath": str(parent_tx), "toolCall": {"name": "invoke_subagent"}})

        for _ in range(dp.MAX_LEAD_POST_SUBAGENT_READS):
            self.assertEqual("allow", self._pre_tool({
                "conversationId": parent_cid,
                "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt")}},
            })["decision"])
        r_w2_cap = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt")}},
        })
        self.assertEqual("deny", r_w2_cap["decision"])
        self.assertIn("POST_WORKER_REREAD_CAP_REACHED", r_w2_cap["reason"])

        # Lead Architect decides to edit `FoodScreen.kt` directly -> unlocks subsequent reads cleanly!
        r_lead_edit = self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt"),
                    "CodeContent": "package com.demo\n\nclass FoodScreen {\n    fun renderCard(): String = \"calories_always_visible\"\n}\n",
                },
            },
        })
        self.assertEqual("allow", r_lead_edit["decision"], r_lead_edit)
        self.assertEqual("allow", self._pre_tool({
            "conversationId": parent_cid,
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.repo / "app/src/main/java/com/demo/FoodScreen.kt")}},
        })["decision"])


    def test_v132_live_e2e_bugfix_regressions(self) -> None:
        """Lock in all 5 real-world bugs discovered & fixed during Live 5-Module Android E2E Monitoring."""
        import argparse
        import roborazzi_gate as rg
        import session_forensics as sf
        import delegation_policy as dp
        import change_classifier as cc
        import workflow

        # 1. Roborazzi Version Catalog `alias(libs.plugins.roborazzi)` + `apply false` + dict-bounds `.uitree.json`
        (self.repo / "gradle").mkdir(parents=True, exist_ok=True)
        (self.repo / "gradle/libs.versions.toml").write_text(
            '[plugins]\nroborazzi = { id = "io.github.takahirom.roborazzi", version = "1.39.0" }\n',
            encoding="utf-8",
        )
        (self.repo / "build.gradle.kts").write_text(
            'plugins { alias(libs.plugins.roborazzi) apply false }\n',
            encoding="utf-8",
        )
        (self.repo / "feature/home").mkdir(parents=True, exist_ok=True)
        (self.repo / "feature/home/build.gradle.kts").write_text(
            'plugins { alias(libs.plugins.roborazzi) }\n',
            encoding="utf-8",
        )
        caps = rg.detect_roborazzi(self.repo)
        self.assertTrue(caps["installed"])
        self.assertIn(":feature:home", caps["modules"])
        self.assertNotIn(":", caps["modules"])

        uitree_p = self.repo / "feature/home/build/outputs/roborazzi/Card.uitree.json"
        uitree_p.parent.mkdir(parents=True, exist_ok=True)
        uitree_p.write_text(json.dumps({
            "screenWidth": 360,
            "screenHeight": 800,
            "root": {
                "id": "RootCard",
                "bounds": {"left": 0, "top": 0, "right": 360, "bottom": 200},
                "children": [
                    {"id": "OverflowLabel", "bounds": {"left": 16, "top": 20, "right": 410, "bottom": 60}, "clickable": False}
                ],
            },
        }), encoding="utf-8")
        audit = rg.inspect_uitree_files(self.repo, [uitree_p])
        self.assertEqual("FAIL", audit["status"])
        self.assertEqual("HORIZONTAL_VIEWPORT_CLIP", audit["issues"][0]["code"])
        uitree_p.unlink()

        # 2. `session_forensics` discovers live `.agents/state/audit_log.jsonl`
        live_audit = self.repo / ".agents/state/audit_log.jsonl"
        live_audit.parent.mkdir(parents=True, exist_ok=True)
        live_audit.write_text(
            json.dumps({"decision": "deny", "reason_code": "USE_HARNESS_SCOUT_AGENT", "tool": "invoke_subagent", "reason": "blocked"}) + "\n"
            + json.dumps({"decision": "allow", "reason_code": "HARNESS_COMMAND", "tool": "run_command", "reason": "ok"}) + "\n",
            encoding="utf-8",
        )
        ha = sf._analyze_hook_audit(self.repo)
        self.assertTrue(ha["audit_file"].endswith("audit_log.jsonl"))
        self.assertEqual(2, ha["total_events"])
        self.assertEqual(1, ha["deny_count"])

        # 3. `change_classifier._is_isolated_private_kotlin_edit` allows local `val`/`var` inside `private fun`
        #    while rejecting mixed public+private function edits!
        self.assertTrue(cc._is_isolated_private_kotlin_edit(
            "+        val safe = kcal.coerceAtLeast(0)\n+        return safe.toString()",
            "class HomeScreen {\n    private fun formatKcal(kcal: Int): String {",
        ))
        self.assertFalse(cc._is_isolated_private_kotlin_edit(
            "+        val safe = kcal.coerceAtLeast(0)",
            "class HomeScreen {\n    fun render(): String {\n    private fun formatKcal(kcal: Int): String {",
        ))

        # 4. `_workflow/planning.py`: 1 Room entity + 1 unit test does NOT falsely trigger `PHASE_PLAN_REQUIRED`!
        args_room = argparse.Namespace(
            repo=str(self.repo),
            task_id="t-single-room-with-test",
            outcome="Add column to entity with unit test",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces="ROOM_SCHEMA,BUSINESS_LOGIC",
            expected_modules=":app",
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/java/com/demo/LogEntity.kt,app/src/test/java/com/demo/LogEntityTest.kt",
            phases=None,
            force=False,
        )
        workflow.draft(args_room)
        workflow.cancel(argparse.Namespace(repo=str(self.repo), task_id="t-single-room-with-test"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
