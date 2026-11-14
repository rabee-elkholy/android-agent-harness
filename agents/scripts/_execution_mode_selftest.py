#!/usr/bin/env python3
"""Comprehensive End-to-End Selftest Suite for Interactive Execution Mode Selector & All 9 Edge Cases."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
KIT_ROOT = SCRIPTS_DIR.parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(KIT_ROOT / "agents"))

from _vnext_common import ValidationError, atomic_write_json, read_json  # noqa: E402
import delegation_policy  # noqa: E402
import execution_mode  # noqa: E402
import web_relay  # noqa: E402


def _init_sample_android_repo(dst: Path) -> Path:
    from _vnext_common import canonical_sha256, utc_now
    from lifecycle import ARCHITECTURE_MAJOR, EXCLUDE_BEGIN, EXCLUDE_END, OWNERSHIP_RELATIVE, SCHEMA_VERSION

    repo = dst / "sample_app"
    repo.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        KIT_ROOT / "agents",
        repo / ".agents",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "state", "cache"),
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "architecture_major": ARCHITECTURE_MAJOR,
        "harness_version": (KIT_ROOT / "agents" / "VERSION").read_text(encoding="utf-8").strip(),
        "installed_at": utc_now(),
        "install_backup": None,
        "latest_backup": None,
        "managed_exclude_block": {"begin": EXCLUDE_BEGIN, "end": EXCLUDE_END},
        "entries": [],
    }
    manifest["ownership_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "ownership_sha256"})
    atomic_write_json(repo / OWNERSHIP_RELATIVE, manifest)
    (repo / ".gitignore").write_text(".agents/\n.harness-setup/\nlocal.properties\napp/google-services.json\n", encoding="utf-8")
    ctx_d = repo / ".agents" / "project-context"
    ctx_d.mkdir(parents=True, exist_ok=True)
    (ctx_d / "project-notes.md").write_text("# Notes\n- Keep Clean Architecture boundaries strict.\n", encoding="utf-8")

    (repo / "settings.gradle.kts").write_text('rootProject.name = "SampleApp"\ninclude(":app")\n', encoding="utf-8")
    (repo / "build.gradle.kts").write_text("// root\n", encoding="utf-8")
    (repo / "gradlew").write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
    (repo / "gradlew").chmod(0o755)
    app_src = repo / "app/src/main/java/com/example/sample"
    app_test = repo / "app/src/test/java/com/example/sample"
    res_en = repo / "app/src/main/res/values"
    app_src.mkdir(parents=True, exist_ok=True)
    app_test.mkdir(parents=True, exist_ok=True)
    res_en.mkdir(parents=True, exist_ok=True)
    (repo / "app/build.gradle.kts").write_text(
        'plugins { id("com.android.application"); kotlin("android") }\nandroid { namespace = "com.example.sample"; compileSdk = 35 }\n',
        encoding="utf-8",
    )
    (repo / "app/src/main/AndroidManifest.xml").write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application><activity android:name=".MainActivity" android:exported="true"/></application></manifest>\n',
        encoding="utf-8",
    )
    (res_en / "strings.xml").write_text('<resources>\n    <string name="app_name">Sample</string>\n</resources>\n', encoding="utf-8")
    for idx, cls in enumerate(("MainActivity", "CartViewModel", "OrderRepository", "CheckoutUseCase", "ProfileFormatter"), 1):
        (app_src / f"{cls}.kt").write_text(
            f"package com.example.sample\n\nclass {cls} {{\n    fun step{idx}(): Int = {idx}\n}}\n",
            encoding="utf-8",
        )
    (app_test / "CartViewModelTest.kt").write_text(
        "package com.example.sample\n\nimport org.junit.Test\nclass CartViewModelTest {\n    @Test fun baseline() {}\n}\n",
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "chore: initial"], cwd=repo, env=env, check=True)
    (repo / "local.properties").write_text("sdk.dir=/opt/android-sdk\n", encoding="utf-8")
    (repo / "app/google-services.json").write_text('{"project_info": {"project_id": "secret-proj"}}\n', encoding="utf-8")
    return repo


def _run_pre_tool_hook(
    repo: Path,
    payload: dict,
    *,
    brain_root: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict:
    env = {**os.environ, "HARNESS_HOOK_HOST": "antigravity"}
    if brain_root is not None:
        env["ANTIGRAVITY_APP_DATA"] = str(brain_root)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(repo / ".agents/scripts/pre_tool_safety.py")],
        cwd=repo,
        env=env,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    out = proc.stdout.strip()
    return json.loads(out) if out else {"exit_code": proc.returncode, "stderr": proc.stderr}


class ExecutionModeSelectorSelftest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="exec_mode_selftest_")
        cls.tmp_root = Path(cls._tmp.name)
        cls.base_repo = _init_sample_android_repo(cls.tmp_root / "template")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _fresh_repo(self, name: str) -> tuple[Path, Path, str]:
        dest = self.tmp_root / name / "app"
        shutil.copytree(self.base_repo, dest)
        # Refresh repository fingerprint in git/graph if needed
        brain = self.tmp_root / name / "brain_data"
        conv_id = f"conv-{name}-001"
        conv_dir = brain / "brain" / conv_id
        conv_dir.mkdir(parents=True, exist_ok=True)
        (conv_dir / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_EXPLICIT", "role": "user", "content": "Please implement this feature"}) + "\n",
            encoding="utf-8",
        )
        return dest, brain, conv_id

    def test_01_english_only_questions_and_concise_labels(self) -> None:
        import re
        import review_models

        arabic_re = re.compile(r"[\u0600-\u06FF]")
        pure_english_targets = [
            KIT_ROOT / "agents/scripts/execution_mode.py",
            KIT_ROOT / "agents/scripts/review_models.py",
            KIT_ROOT / "agents/tool-adapters/GEMINI.md.template",
            KIT_ROOT / "agents/rules/harness-rules.md",
            KIT_ROOT / "agents/workflows/web-relay.md",
            KIT_ROOT / "agents/skills/android-harness/SKILL.md",
        ]
        for path in pure_english_targets:
            txt = path.read_text(encoding="utf-8")
            self.assertIsNone(arabic_re.search(txt), f"Unexpected Arabic text found in {path}")

        em_prompt = execution_mode.build_execution_mode_prompt(self.base_repo)
        self.assertEqual(em_prompt["code"], "SELECT_EXECUTION_MODE")
        self.assertEqual(em_prompt["tool"], "ask_question")
        self.assertEqual(em_prompt["question"], "How would you like to run this task?")
        self.assertNotIn("question_ar", em_prompt)
        self.assertEqual([o["id"] for o in em_prompt["options"]], ["auto-project", "normal-task", "normal-project", "web-task", "web-project"])
        for opt in em_prompt["options"]:
            self.assertNotIn("label_ar", opt)
            self.assertLessEqual(len(opt["label"]), 95)

        for key, item in review_models.ANTIGRAVITY_INTERACTIVE_CHOICES.items():
            self.assertNotIn("label_ar", item, f"Arabic label left in {key}")
            self.assertLessEqual(len(item["label_en"]), 95, f"Verbose label in {key}: {item['label_en']}")

    def test_02_edge_case_1_and_2_idle_readonly_allowed_vs_kickoff_enforced(self) -> None:
        repo, brain, cid = self._fresh_repo("ec1_ec2")

        # Edge Case 1: Read-only tools & commands are 100% allowed when mode is unset
        for ro_payload in (
            {"conversationId": cid, "toolName": "run_command", "toolArgs": {"CommandLine": "python .agents/harness.py graph --feature Cart --json"}},
            {"conversationId": cid, "toolName": "run_command", "toolArgs": {"CommandLine": "python .agents/harness.py doctor --quick"}},
            {"conversationId": cid, "toolName": "run_command", "toolArgs": {"CommandLine": "python .agents/harness.py execution-mode show --json"}},
            {"conversationId": cid, "toolName": "view_file", "toolArgs": {"AbsolutePath": str(repo / "app/src/main/java/com/example/sample/CartViewModel.kt")}},
            {"conversationId": cid, "toolName": "ask_question", "toolArgs": {"question": "How would you like to run this task?"}},
        ):
            res = _run_pre_tool_hook(repo, ro_payload, brain_root=brain)
            decision = (res.get("hookSpecificOutput") or {}).get("permissionDecision") or res.get("decision")
            self.assertEqual(decision, "allow", f"Read-only call unexpectedly blocked: {ro_payload} -> {res}")

        # Edge Case 2: `task draft` and cold-start `web-pack` are hard-blocked with SELECT_EXECUTION_MODE_REQUIRED when unset
        for ko_cmd in (
            'python .agents/harness.py task draft --repo . --task-id feat-1 --outcome "Add discount" --kind FEATURE --expected-files app/src/main/java/com/example/sample/CartViewModel.kt',
            'python .agents/harness.py web-pack --files app/src/main/java/com/example/sample/CartViewModel.kt --prompt "Add discount"',
        ):
            res = _run_pre_tool_hook(
                repo,
                {"conversationId": cid, "toolName": "run_command", "toolArgs": {"CommandLine": ko_cmd}},
                brain_root=brain,
            )
            reason = str((res.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or res.get("reason") or "")
            decision = (res.get("hookSpecificOutput") or {}).get("permissionDecision") or res.get("decision")
            self.assertEqual(decision, "deny")
            self.assertIn("SELECT_EXECUTION_MODE_REQUIRED", reason)

        # Edge Case 9a: Non-Antigravity host (`claude`) and synthetic non-transcript CLI calls are NOT blocked
        res_claude = _run_pre_tool_hook(
            repo,
            {"conversationId": cid, "toolName": "run_command", "toolArgs": {"CommandLine": "python .agents/harness.py web-pack --files app/src/main/java/com/example/sample/CartViewModel.kt"}},
            brain_root=brain,
            extra_env={"HARNESS_HOOK_HOST": "claude"},
        )
        self.assertEqual((res_claude.get("hookSpecificOutput") or {}).get("permissionDecision") or res_claude.get("decision"), "allow")

        # Authority enforcement: `execution-mode set` without `--source conversation` / `--proof-reference` is denied
        res_unauth = _run_pre_tool_hook(
            repo,
            {"conversationId": cid, "toolName": "run_command", "toolArgs": {"CommandLine": "python .agents/harness.py execution-mode set --choice normal-project"}},
            brain_root=brain,
        )
        self.assertEqual((res_unauth.get("hookSpecificOutput") or {}).get("permissionDecision") or res_unauth.get("decision"), "deny")

        # Subagent isolation: Scout allows `execution-mode show` only and blocks `execution-mode set`; Worker blocks `execution-mode set`
        self.assertTrue(delegation_policy.scout_command_allowed("python .agents/harness.py execution-mode show --json"))
        self.assertFalse(delegation_policy.scout_command_allowed('python .agents/harness.py execution-mode set --choice web-project --source conversation --proof-reference "ok"'))
        w_ok, _ = delegation_policy.worker_command_allowed('python .agents/harness.py execution-mode set --choice normal-task --source conversation --proof-reference "ok"')
        self.assertFalse(w_ok)

    def test_03_edge_case_3_single_task_override_preserves_project_default(self) -> None:
        repo, brain, cid = self._fresh_repo("ec3")

        # 1. Persist `web-project` as project default
        subprocess.run(
            [sys.executable, str(repo / ".agents/harness.py"), "execution-mode", "set", "--choice", "web-project", "--source", "conversation", "--proof-reference", "Use web always"],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        eff0 = execution_mode.resolve_effective_execution_mode(repo)
        self.assertEqual(eff0["mode"], "web")
        self.assertEqual(eff0["effective_scope"], "project")

        # 2. Override for ONE task only (`normal-task`) before `draft`
        subprocess.run(
            [sys.executable, str(repo / ".agents/harness.py"), "execution-mode", "set", "--choice", "normal-task", "--source", "conversation", "--proof-reference", "Do this quick fix locally"],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        eff_pending = execution_mode.resolve_effective_execution_mode(repo)
        self.assertEqual(eff_pending["mode"], "normal")
        self.assertEqual(eff_pending["effective_scope"], "pending_task")
        self.assertEqual(eff_pending["project_choice"], "web-project")

        # Seed discovery receipt via `task-context` and draft `quick-local-1`
        subprocess.run(
            [sys.executable, str(repo / ".agents/harness.py"), "task-context", "--file", "app/src/main/java/com/example/sample/CartViewModel.kt", "--json"],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        subprocess.run(
            [
                sys.executable, str(repo / ".agents/harness.py"), "task", "draft",
                "--repo", ".", "--task-id", "quick-local-1", "--outcome", "Quick local tweak",
                "--kind", "FEATURE", "--expected-files", "app/src/main/java/com/example/sample/CartViewModel.kt,app/src/test/java/com/example/sample/CartViewModelTest.kt",
                "--approach", "Update step2", "--risks", "Low", "--test-strategy", "JUnit", "--device-strategy", "Skip",
            ],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        # Pending file must be promoted into `tasks/quick-local-1/execution-mode.json`!
        self.assertFalse(execution_mode.pending_task_mode_file(repo).exists())
        self.assertTrue(execution_mode.task_mode_file(repo, "quick-local-1").is_file())
        eff_bound = execution_mode.resolve_effective_execution_mode(repo)
        self.assertEqual(eff_bound["mode"], "normal")
        self.assertEqual(eff_bound["effective_scope"], "task")
        self.assertEqual(eff_bound["project_choice"], "web-project")

        # 3. Cancel/finish `quick-local-1` -> next task automatically reverts to `web-project`!
        subprocess.run(
            [sys.executable, str(repo / ".agents/harness.py"), "task", "cancel", "--repo", ".", "--task-id", "quick-local-1", "--source", "conversation", "--proof-reference", "Cancel test task"],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        eff_after = execution_mode.resolve_effective_execution_mode(repo)
        self.assertEqual(eff_after["mode"], "web")
        self.assertEqual(eff_after["choice"], "web-project")
        self.assertEqual(eff_after["effective_scope"], "project")

    def test_04_edge_case_4_bidirectional_mid_task_switching(self) -> None:
        repo, brain, cid = self._fresh_repo("ec4")

        execution_mode.set_execution_mode(repo, choice="normal-project", source="conversation", proof_reference="Normal default")
        subprocess.run(
            [sys.executable, str(repo / ".agents/harness.py"), "task-context", "--file", "app/src/main/java/com/example/sample/CartViewModel.kt", "--json"],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        files_4 = ",".join([
            "app/src/main/java/com/example/sample/CartViewModel.kt",
            "app/src/main/java/com/example/sample/OrderRepository.kt",
            "app/src/main/java/com/example/sample/CheckoutUseCase.kt",
            "app/src/test/java/com/example/sample/CartViewModelTest.kt",
        ])
        subprocess.run(
            [
                sys.executable, str(repo / ".agents/harness.py"), "task", "draft",
                "--repo", ".", "--task-id", "mid-switch", "--outcome", "Multi-file checkout update",
                "--kind", "FEATURE", "--expected-files", files_4,
                "--approach", "Coordinate 4 files", "--risks", "Low", "--test-strategy", "JUnit", "--device-strategy", "Skip",
            ],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        plan_before = read_json(repo / ".agents/state/tasks/mid-switch/plan.json")
        sha_before = plan_before["plan_sha256"]
        subprocess.run(
            [
                sys.executable, str(repo / ".agents/harness.py"), "task", "approve",
                "--repo", ".", "--task-id", "mid-switch", "--source", "conversation",
                "--proof-reference", "Proceed", "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", sha_before,
            ],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )

        # Initially in `normal` mode on 4 files -> `DELEGATE_WORKER_SLICE`
        adv_normal = delegation_policy.evaluate_delegation_policy(repo, task_id="mid-switch")
        self.assertEqual(adv_normal["strategy"], "DELEGATE_WORKER_SLICE")
        self.assertTrue(adv_normal["worker_allowed"])

        # Switch mid-task `normal -> web` without invalidating `plan_sha256`!
        sw_web = execution_mode.set_execution_mode(
            repo, choice="web-task", source="conversation", proof_reference="Finish this task on Gemini Web"
        )
        self.assertEqual(sw_web["task_id"], "mid-switch")
        self.assertEqual(read_json(repo / ".agents/state/tasks/mid-switch/plan.json")["plan_sha256"], sha_before)

        adv_web = delegation_policy.evaluate_delegation_policy(repo, task_id="mid-switch")
        self.assertEqual(adv_web["strategy"], "WEB_RELAY_ACTIVE")
        self.assertFalse(adv_web["worker_allowed"])
        self.assertIn("web-pack --task-id mid-switch", adv_web["next_command"])

        # Build a web-pack for `mid-switch`, then switch BACK `web -> normal`!
        pack_res = web_relay.build_web_pack(repo, task_id="mid-switch", no_clipboard=True)
        self.assertTrue((repo / ".agents/state/tasks/mid-switch/latest-web-pack.json").is_file())

        sw_norm = execution_mode.set_execution_mode(
            repo, choice="normal-task", source="conversation", proof_reference="Gemini Web is busy, continue locally"
        )
        self.assertIn(pack_res["pack_id"], sw_norm.get("superseded_web_packs", []))
        ptr_after = read_json(repo / ".agents/state/tasks/mid-switch/latest-web-pack.json")
        self.assertTrue(ptr_after.get("superseded_by_normal_mode"))
        self.assertEqual(read_json(repo / ".agents/state/tasks/mid-switch/plan.json")["plan_sha256"], sha_before)

        adv_back = delegation_policy.evaluate_delegation_policy(repo, task_id="mid-switch")
        self.assertEqual(adv_back["strategy"], "DELEGATE_WORKER_SLICE")
        self.assertTrue(adv_back["worker_allowed"])

    def test_05_edge_case_5_and_6_bridge_continuity_parallel_switch_and_tamper_guard(self) -> None:
        repo, brain, cid = self._fresh_repo("ec5_ec6")

        # Create Task A (`web-task`) and Task B (`normal-task`) on disjoint files
        execution_mode.set_execution_mode(repo, choice="web-task", task_id="task-a", new_task=True, source="conversation", proof_reference="Task A on web")
        subprocess.run([sys.executable, str(repo / ".agents/harness.py"), "task-context", "--file", "app/src/main/java/com/example/sample/CartViewModel.kt", "--json"], cwd=repo, check=True, stdout=subprocess.PIPE)
        subprocess.run(
            [
                sys.executable, str(repo / ".agents/harness.py"), "task", "draft",
                "--repo", ".", "--task-id", "task-a", "--outcome", "Task A feature",
                "--kind", "FEATURE", "--expected-files", "app/src/main/java/com/example/sample/CartViewModel.kt,app/src/test/java/com/example/sample/CartViewModelTest.kt",
                "--approach", "A", "--risks", "Low", "--test-strategy", "JUnit", "--device-strategy", "Skip",
            ],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )

        execution_mode.set_execution_mode(repo, choice="normal-task", task_id="task-b", new_task=True, source="conversation", proof_reference="Task B locally")
        subprocess.run([sys.executable, str(repo / ".agents/harness.py"), "task-context", "--file", "app/src/main/java/com/example/sample/ProfileFormatter.kt", "--json"], cwd=repo, check=True, stdout=subprocess.PIPE)
        subprocess.run(
            [
                sys.executable, str(repo / ".agents/harness.py"), "task", "draft",
                "--repo", ".", "--task-id", "task-b", "--outcome", "Task B docs/format",
                "--kind", "REFACTOR", "--expected-files", "app/src/main/java/com/example/sample/ProfileFormatter.kt",
                "--approach", "B", "--risks", "Low", "--test-strategy", "JUnit", "--device-strategy", "Skip",
            ],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )

        # Focused task is now `task-b` (`normal`)
        self.assertEqual(execution_mode.resolve_effective_execution_mode(repo)["mode"], "normal")

        # Switch focus to `task-a` -> mode immediately resolves to `web`!
        subprocess.run([sys.executable, str(repo / ".agents/harness.py"), "task", "switch", "--repo", ".", "--task-id", "task-a"], cwd=repo, check=True, stdout=subprocess.PIPE)
        self.assertEqual(execution_mode.resolve_effective_execution_mode(repo)["mode"], "web")

        # Save Task Bridge for `task-a` and verify `execution_mode` is embedded & restored if missing
        save_proc = subprocess.run(
            [sys.executable, str(repo / ".agents/harness.py"), "task", "bridge", "--save", "--task-id", "task-a", "--mode", "MID_TASK_HANDOFF", "--summary", "Continuing Task A in new chat", "--json"],
            cwd=repo, check=True, capture_output=True, text=True,
        )
        bridge_saved = json.loads(save_proc.stdout)
        b_obj = bridge_saved.get("bridge") if isinstance(bridge_saved.get("bridge"), dict) else bridge_saved
        snap_obj = b_obj.get("task_snapshot") or read_json(repo / ".agents/state/task-bridge.json").get("task_snapshot") or {}
        self.assertEqual(snap_obj["execution_mode"]["mode"], "web")

        # Simulate worktree transfer where `tasks/task-a/execution-mode.json` was absent, then load bridge
        execution_mode.task_mode_file(repo, "task-a").unlink()
        subprocess.run([sys.executable, str(repo / ".agents/harness.py"), "task", "bridge", "--task-id", "task-a", "--json"], cwd=repo, check=True, stdout=subprocess.PIPE)
        self.assertTrue(execution_mode.task_mode_file(repo, "task-a").is_file())
        self.assertEqual(execution_mode.resolve_effective_execution_mode(repo, task_id="task-a")["mode"], "web")

        # Verify `pre_invocation_reminder.py` is 100% read-only and includes `[Execution Mode: web (task)]`
        rem_proc = subprocess.run(
            [sys.executable, str(repo / ".agents/scripts/pre_invocation_reminder.py")],
            cwd=repo, input="{}", text=True, capture_output=True, check=True,
        )
        self.assertIn("Execution Mode: web", rem_proc.stdout)

        # Tamper test: corrupt `execution-mode.json` -> fails closed & `doctor` detects tamper!
        execution_mode.set_execution_mode(repo, choice="normal-project", source="conversation", proof_reference="Save project mode")
        p_file = execution_mode.project_mode_file(repo)
        tampered = read_json(p_file)
        tampered["mode"] = "web"  # mutate without updating record_sha256!
        atomic_write_json(p_file, tampered)

        ok_int, errs_int = execution_mode.verify_execution_mode_integrity(repo)
        self.assertFalse(ok_int)
        self.assertTrue(any("EXECUTION_MODE_TAMPERED" in e for e in errs_int))

    def test_06_edge_case_7_8_9_secret_fallback_conflict_exemption_and_reset(self) -> None:
        repo, brain, cid = self._fresh_repo("ec7_ec8_ec9")

        # Enable `web-project`
        execution_mode.set_execution_mode(repo, choice="web-project", source="conversation", proof_reference="Web always")

        # Edge Case 7: `web-pack` on secret/protected files (`local.properties`, `app/google-services.json`) raises structured `ask_question` fallback!
        with self.assertRaises(ValidationError) as ctx_sec:
            web_relay.build_web_pack(repo, files=["local.properties", "app/google-services.json"], prompt="Update API config", no_clipboard=True)
        self.assertIn("WEB_RELAY_SECRET_SCOPE_FALLBACK", str(ctx_sec.exception))
        self.assertIn("TOOL_CALL_REQUIRED=ask_question", str(ctx_sec.exception))
        self.assertIn("--choice normal-task", str(ctx_sec.exception))
        # Project default `web-project` remains untouched!
        self.assertEqual(execution_mode.resolve_effective_execution_mode(repo)["choice"], "web-project")

        # Edge Case 8: `CONFLICT` task or file with `<<<<<<< ` conflict markers automatically runs locally while preserving `web-project`!
        eff_conf_plan = execution_mode.resolve_effective_execution_mode(
            repo, plan={"task_id": "merge-1", "status": "IMPLEMENTING", "task_kind": "CONFLICT", "expected_files": ["app/src/main/java/com/example/sample/CartViewModel.kt"]}
        )
        self.assertEqual(eff_conf_plan["mode"], "normal")
        self.assertTrue(eff_conf_plan["conflict_auto_local_override"])
        self.assertEqual(eff_conf_plan["project_choice"], "web-project")

        # Also test actual Git conflict markers in file on disk
        cart_f = repo / "app/src/main/java/com/example/sample/CartViewModel.kt"
        orig_cart = cart_f.read_text(encoding="utf-8")
        cart_f.write_text(
            "package com.example.sample\n<<<<<<< HEAD\nclass CartViewModel { fun a() = 1 }\n=======\nclass CartViewModel { fun a() = 2 }\n>>>>>>> feature/branch\n",
            encoding="utf-8",
        )
        try:
            with self.assertRaises(ValidationError) as ctx_conf:
                web_relay.build_web_pack(repo, files=["app/src/main/java/com/example/sample/CartViewModel.kt"], prompt="Resolve merge", no_clipboard=True)
            self.assertIn("WEB_RELAY_CONFLICT_LOCAL_RECOMMENDED", str(ctx_conf.exception))
        finally:
            cart_f.write_text(orig_cart, encoding="utf-8")

        # Also verify `--files` plural CLI alias works cleanly on `web-pack`!
        wp_proc = subprocess.run(
            [sys.executable, str(repo / ".agents/harness.py"), "web-pack", "--files", "app/src/main/java/com/example/sample/CartViewModel.kt", "--prompt", "Add coupon", "--no-clipboard", "--json"],
            cwd=repo, check=True, capture_output=True, text=True,
        )
        wp_out = json.loads(wp_proc.stdout)
        self.assertIn("app/src/main/java/com/example/sample/CartViewModel.kt", wp_out["editable_files"])

        # Edge Case 9b: Reset via `--choice ask-every-task` clears project default cleanly
        rst = execution_mode.set_execution_mode(repo, choice="ask-every-task", source="conversation", proof_reference="Ask me on every new task")
        self.assertEqual(rst["status"], "RESET_TO_ASK_EVERY_TASK")
        self.assertTrue(rst["effective"]["selection_required"])
        self.assertEqual(rst["effective"]["mode"], "unset")


    def test_07_windows_backslash_paths_and_large_transcript_lead_detection(self) -> None:
        repo, brain, cid = self._fresh_repo("win_backslash_and_large_transcript")

        # 1) Append > 48 KB of tool-output noise after initial USER_EXPLICIT so USER_EXPLICIT is outside the last 32 KB!
        tp = brain / "brain" / cid / "transcript.jsonl"
        with tp.open("a", encoding="utf-8") as fh:
            for i in range(60):
                fh.write(json.dumps({"type": "TOOL_OUTPUT", "seq": i, "blob": "X" * 900}) + "\n")
        self.assertGreater(tp.stat().st_size, 48 * 1024)

        # 2) Invoke `task draft` using a Windows backslash launcher path `.agents\harness.py`!
        verdict_win = _run_pre_tool_hook(
            repo,
            {
                "conversationId": cid,
                "toolName": "run_command",
                "toolArgs": {
                    "CommandLine": 'python .agents\\harness.py task draft --repo . --task-id win-t1 --outcome "Fix bug" --kind FEATURE --expected-files app/src/main/java/com/example/sample/CartViewModel.kt'
                },
            },
            brain_root=brain,
        )
        decision_w = (verdict_win.get("hookSpecificOutput") or {}).get("permissionDecision") or verdict_win.get("decision")
        reason_w = str((verdict_win.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or verdict_win.get("reason") or "")
        self.assertEqual(decision_w, "deny")
        self.assertIn("SELECT_EXECUTION_MODE_REQUIRED", reason_w)

        # 3) Verify developer authority check ALSO catches Windows backslash `execution-mode set` without `--source conversation`!
        verdict_spoof = _run_pre_tool_hook(
            repo,
            {
                "conversationId": cid,
                "toolName": "run_command",
                "toolArgs": {"CommandLine": "python C:\\Users\\dev\\repo\\.agents\\harness.py execution-mode set --choice web-project"},
            },
            brain_root=brain,
        )
        decision_sp = (verdict_spoof.get("hookSpecificOutput") or {}).get("permissionDecision") or verdict_spoof.get("decision")
        self.assertEqual(decision_sp, "deny")

        # 4) Verify spawned subagent transcript (`SYSTEM_SDK` start without `USER_EXPLICIT`) is NEVER treated as interactive Lead!
        sub_cid = "subagent-conv-001"
        sub_tp = brain / "brain" / sub_cid / "transcript.jsonl"
        sub_tp.parent.mkdir(parents=True, exist_ok=True)
        sub_tp.write_text(
            json.dumps({"type": "SYSTEM_MESSAGE", "source": "SYSTEM_SDK", "text": "Subagent brief"}) + "\n",
            encoding="utf-8",
        )
        import pre_tool_safety
        self.assertFalse(pre_tool_safety._is_live_interactive_antigravity_lead(sub_cid, transcript_hint=str(sub_tp)))

    def test_08_mid_task_project_switch_multiphase_web_and_direct_write_guard(self) -> None:
        repo, brain, cid = self._fresh_repo("round2_multiphase_and_write_guard")

        # Start a task initially with `web-task`
        execution_mode.set_execution_mode(repo, choice="web-task", source="conversation", proof_reference="Web for this task")
        subprocess.run(
            [sys.executable, str(repo / ".agents/harness.py"), "task-context", "--file", "app/src/main/java/com/example/sample/OrderRepository.kt", "--json"],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        subprocess.run(
            [sys.executable, str(repo / ".agents/harness.py"), "task-context", "--file", "app/src/main/java/com/example/sample/CartViewModel.kt", "--json"],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        subprocess.run(
            [
                sys.executable, str(repo / ".agents/harness.py"), "task", "draft",
                "--repo", ".",
                "--task-id", "mp-web-1",
                "--kind", "FEATURE",
                "--outcome", "Two-phase order and cart update",
                "--expected-files", "app/src/main/java/com/example/sample/OrderRepository.kt,app/src/main/java/com/example/sample/CartViewModel.kt,app/src/test/java/com/example/sample/CartViewModelTest.kt",
                "--approach", "Phase 1 OrderRepository then Phase 2 CartViewModel",
                "--risks", "Low",
                "--test-strategy", "JUnit",
                "--device-strategy", "Skip",
            ],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )
        plan_obj = read_json(repo / ".agents/state/tasks/mp-web-1/plan.json")
        subprocess.run(
            [
                sys.executable, str(repo / ".agents/harness.py"), "task", "approve",
                "--repo", ".",
                "--task-id", "mp-web-1",
                "--source", "conversation",
                "--proof-reference", "Approved",
                "--enforcement-tier", "RULE_ENFORCED",
                "--plan-hash", plan_obj["plan_sha256"],
            ],
            cwd=repo, check=True, stdout=subprocess.PIPE,
        )

        # A) Before `web-pack` / `web-apply` runs, direct Lead `replace_file_content` on `OrderRepository.kt` is blocked by `WEB_EXECUTION_MODE_PACK_FIRST`!
        v_direct = _run_pre_tool_hook(
            repo,
            {
                "conversationId": cid,
                "toolName": "replace_file_content",
                "toolArgs": {
                    "TargetFile": str(repo / "app/src/main/java/com/example/sample/OrderRepository.kt"),
                    "TargetContent": "fun step3(): Int = 3",
                    "ReplacementContent": "fun step3(): Int = 30",
                },
            },
            brain_root=brain,
        )
        dec_d = (v_direct.get("hookSpecificOutput") or {}).get("permissionDecision") or v_direct.get("decision")
        rsn_d = str((v_direct.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or v_direct.get("reason") or "")
        self.assertEqual(dec_d, "deny")
        self.assertIn("WEB_EXECUTION_MODE_PACK_FIRST", rsn_d)

        # B) Simulate multi-phase `p1` (`COMPLETED`) -> `p2` (`IN_PROGRESS`) after `p1` was applied via Web-Relay!
        (repo / "app/src/main/java/com/example/sample/OrderRepository.kt").write_text(
            "package com.example.sample\n\nclass OrderRepository {\n    fun step3(): Int = 30\n}\n",
            encoding="utf-8",
        )
        atomic_write_json(
            repo / ".agents/state/tasks/mp-web-1/web-relay-receipt.json",
            {"pack_id": "pack-p1", "phase_id": "p1", "files_written": ["app/src/main/java/com/example/sample/OrderRepository.kt"]},
        )
        live_plan = dict(read_json(repo / ".agents/state/tasks/mp-web-1/plan.json"))
        live_plan["phases"] = [
            {"id": "p1", "title": "Phase 1 Repo", "status": "COMPLETED", "files": ["app/src/main/java/com/example/sample/OrderRepository.kt"]},
            {"id": "p2", "title": "Phase 2 VM", "status": "IN_PROGRESS", "files": ["app/src/main/java/com/example/sample/CartViewModel.kt"]},
        ]

        # Even though `p1` modified `OrderRepository.kt`, `p2` (`CartViewModel.kt`) has NOT been applied yet -> `delegate-plan` MUST stay `WEB_RELAY_ACTIVE`!
        dp_p2 = delegation_policy.evaluate_delegation_policy(repo, plan=live_plan)
        self.assertEqual(dp_p2["strategy"], "WEB_RELAY_ACTIVE")
        self.assertIn("web-pack --task-id mp-web-1", dp_p2["next_command"])

        # And if `staged-web-phases/p2.json` exists, `delegate-plan` routes directly to `web-apply --staged-phase`!
        staged_p2 = repo / ".agents/state/tasks/mp-web-1/staged-web-phases/p2.json"
        staged_p2.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(staged_p2, {"writes": [{"path": "app/src/main/java/com/example/sample/CartViewModel.kt"}], "deletes": []})
        dp_p2_staged = delegation_policy.evaluate_delegation_policy(repo, plan=live_plan)
        self.assertEqual(dp_p2_staged["strategy"], "WEB_RELAY_ACTIVE")
        self.assertIn("--staged-phase", dp_p2_staged["next_command"])

        # C) Mid-task switch via `--choice normal-project` WITHOUT `--task-id` immediately overrides active task's prior `web-task` and supersedes unapplied pack!
        pack_res = web_relay.build_web_pack(repo, task_id="mp-web-1", files=["app/src/main/java/com/example/sample/CartViewModel.kt"], prompt="Finish p2", no_clipboard=True)
        sw_proj = execution_mode.set_execution_mode(repo, choice="normal-project", source="conversation", proof_reference="Switch project to normal always")
        self.assertEqual(sw_proj["effective"]["mode"], "normal")
        self.assertEqual(execution_mode.resolve_effective_execution_mode(repo, task_id="mp-web-1")["mode"], "normal")
        self.assertIn(pack_res["pack_id"], sw_proj.get("superseded_web_packs", []))


    def test_09_concurrent_toctou_safety_post_apply_verify_and_phase_state_routing(self) -> None:
        import concurrent.futures
        import random

        repo, brain, cid = self._fresh_repo("round3_concurrency_and_phase_state")

        # 1) 12-thread concurrent TOCTOU stress across set/show/verify_execution_mode_integrity
        choices = ["auto-project", "auto-task", "normal-task", "web-task", "normal-project", "web-project", "ask-every-task"]

        def _worker(i: int) -> None:
            rng = random.Random(500 + i)
            for s in range(15):
                if s % 3 == 0:
                    ch = rng.choice(choices)
                    execution_mode.set_execution_mode(repo, choice=ch, source="conversation", proof_reference=f"w{i}-{s}")
                else:
                    eff = execution_mode.resolve_effective_execution_mode(repo)
                    self.assertIn(eff["mode"], {"normal", "web", "unset"})
                    ok, errs = execution_mode.verify_execution_mode_integrity(repo)
                    self.assertTrue(ok, f"Concurrent TOCTOU integrity error: {errs}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(_worker, range(12)))

        # 2) Cold-start `web-task` -> `web-pack` -> `web-apply` on 4 files -> `WEB_RELAY_APPLIED_VERIFY` + `task heal`
        execution_mode.set_execution_mode(repo, choice="normal-project", source="conversation", proof_reference="Default normal")
        execution_mode.set_execution_mode(repo, choice="web-task", new_task=True, source="conversation", proof_reference="Web once")
        p_info = web_relay.build_web_pack(
            repo,
            files=[
                "app/src/main/java/com/example/sample/CartViewModel.kt",
                "app/src/main/java/com/example/sample/OrderRepository.kt",
                "app/src/main/java/com/example/sample/CheckoutUseCase.kt",
                "app/src/test/java/com/example/sample/CartViewModelTest.kt",
            ],
            prompt="Add discount helper",
            no_clipboard=True,
        )
        reply_doc = {
            "schema": "HARNESS_WEB_MERGE_V1",
            "pack_id": p_info["pack_id"],
            "repo_fingerprint": p_info["repo_fingerprint"],
            "status": "READY",
            "summary": "Added discount helper",
            "operations": [
                {
                    "op": "MODIFY",
                    "path": "app/src/main/java/com/example/sample/CartViewModel.kt",
                    "hunks": [{"search": "    fun step2(): Int = 2", "replace": "    fun step2(): Int = 2\n    fun discount(): Int = 10"}],
                }
            ],
        }
        reply_f = self.tmp_root / "round3_reply.json"
        reply_f.write_text(json.dumps(reply_doc), encoding="utf-8")
        applied = subprocess.run(
            [
                sys.executable, str(repo / ".agents/harness.py"), "web-apply",
                "--file", str(reply_f), "--source", "conversation", "--proof-reference", "Apply reply", "--json",
            ],
            cwd=repo, check=True, capture_output=True, text=True,
        )
        tid = json.loads(applied.stdout)["task_id"]
        adv_post = delegation_policy.evaluate_delegation_policy(repo, task_id=tid)
        self.assertEqual(adv_post["strategy"], "WEB_RELAY_APPLIED_VERIFY")
        self.assertEqual(adv_post["worker_mode"], "TESTS_AND_GATES_ONLY")

        # 3) Real `phase-state.json` + `expected_files` multi-phase routing check (`phase_routing.py`)
        plan_mp = dict(read_json(repo / f".agents/state/tasks/{tid}/plan.json"))
        plan_mp["active_phase_index"] = 1
        plan_mp["phases"] = [
            {"id": "p1", "expected_files": ["app/src/main/java/com/example/sample/CartViewModel.kt"]},
            {"id": "p2", "expected_files": ["app/src/main/java/com/example/sample/OrderRepository.kt"]},
        ]
        atomic_write_json(
            repo / f".agents/state/tasks/{tid}/phase-state.json",
            {"current_phase_id": "p2", "completed_phases": ["p1"], "phase_checkpoints": {}},
        )
        adv_p2 = delegation_policy.evaluate_delegation_policy(repo, task_id=tid, plan=plan_mp)
        self.assertEqual(adv_p2["strategy"], "WEB_RELAY_ACTIVE")
        self.assertIn(f"web-pack --task-id {tid}", adv_p2["next_command"])


    def test_10_smart_auto_project_routing_across_size_modules_t5_handoff_and_overrides(self) -> None:
        repo, brain, cid = self._fresh_repo("smart_auto_project")

        # 1) Save `auto-project` via alias `smart-auto` -> no longer requires prompt on IDLE!
        res_set = execution_mode.set_execution_mode(
            repo, choice="smart-auto", source="conversation", proof_reference="Use smart auto mode"
        )
        self.assertEqual(res_set["choice"], "auto-project")
        self.assertEqual(res_set["configured_mode"], "auto")
        eff_idle = execution_mode.resolve_effective_execution_mode(repo)
        self.assertFalse(eff_idle["selection_required"])
        self.assertEqual(eff_idle["configured_mode"], "auto")
        self.assertEqual(eff_idle["mode"], "normal")

        # PreToolUse allows both `task draft` and `web-pack` immediately under `auto-project`
        allow_draft = _run_pre_tool_hook(
            repo,
            {"conversationId": cid, "toolName": "run_command", "toolArgs": {"CommandLine": 'python .agents/harness.py task draft --repo . --task-id small-3 --outcome "Fix step" --kind FEATURE --expected-files app/src/main/java/com/example/sample/CartViewModel.kt'}},
            brain_root=brain,
        )
        self.assertEqual((allow_draft.get("hookSpecificOutput") or {}).get("permissionDecision") or allow_draft.get("decision"), "allow")

        # 2) Compact 3-file single-module T2 plan -> Smart Auto resolves to `normal`!
        small_plan = {
            "task_id": "auto-small-3",
            "status": "IMPLEMENTING",
            "task_kind": "FEATURE",
            "expected_files": [
                "app/src/main/java/com/example/sample/CartViewModel.kt",
                "app/src/main/java/com/example/sample/OrderRepository.kt",
                "app/src/test/java/com/example/sample/CartViewModelTest.kt",
            ],
            "expected_modules": [":app"],
            "expected_surfaces": ["BUSINESS_LOGIC"],
        }
        (repo / ".agents/state/tasks/auto-small-3").mkdir(parents=True, exist_ok=True)
        atomic_write_json(repo / ".agents/state/tasks/auto-small-3/plan.json", small_plan)
        eff_small = execution_mode.resolve_effective_execution_mode(repo, task_id="auto-small-3", plan=small_plan)
        self.assertEqual(eff_small["mode"], "normal")
        self.assertEqual(eff_small["configured_mode"], "auto")
        self.assertTrue(eff_small["auto_routed"])
        self.assertEqual(eff_small["auto_route_trigger"], "AUTO_NORMAL_COMPACT_SCOPE_3_FILES")

        # 2b) Simulate a 2-Strike unresolved `worker-handoff.json` on that exact 3-file task -> Smart Auto escalates to `web`!
        atomic_write_json(repo / ".agents/state/tasks/auto-small-3/worker-handoff.json", {
            "status": "OPEN",
            "takeover_trigger": "TWO_STRIKE_HYDROGEN_HIGH",
            "summary_for_lead": "Algorithmic edge case failed twice",
        })
        eff_handoff = execution_mode.resolve_effective_execution_mode(repo, task_id="auto-small-3", plan=small_plan)
        self.assertEqual(eff_handoff["mode"], "web")
        self.assertEqual(eff_handoff["auto_route_trigger"], "AUTO_WEB_2_STRIKE_HANDOFF")

        # 3) Large 15-file plan -> Smart Auto promotes to `web` + delegation_policy returns `WEB_RELAY_ACTIVE`!
        large_files = [f"app/src/main/java/com/example/sample/Screen{i}.kt" for i in range(1, 16)]
        large_plan = {
            "task_id": "auto-large-15",
            "status": "IMPLEMENTING",
            "task_kind": "REFACTOR",
            "expected_files": large_files,
            "expected_modules": [":app"],
            "expected_surfaces": ["COMPOSE_UI"],
        }
        (repo / ".agents/state/tasks/auto-large-15").mkdir(parents=True, exist_ok=True)
        atomic_write_json(repo / ".agents/state/tasks/auto-large-15/plan.json", large_plan)
        eff_large = execution_mode.resolve_effective_execution_mode(repo, task_id="auto-large-15", plan=large_plan)
        self.assertEqual(eff_large["mode"], "web")
        self.assertEqual(eff_large["auto_route_trigger"], "AUTO_WEB_LARGE_SCOPE_15_FILES")
        dp_large = delegation_policy.evaluate_delegation_policy(repo, task_id="auto-large-15", plan=large_plan)
        self.assertEqual(dp_large["strategy"], "WEB_RELAY_ACTIVE")

        # 4) Multi-module (`:core` + `:app`) and Critical `T5` (`AUTH`) plans -> both promote to `web`!
        mm_plan = {
            "task_id": "auto-mm",
            "status": "IMPLEMENTING",
            "task_kind": "FEATURE",
            "expected_files": ["core/src/main/Core.kt", "app/src/main/App.kt"],
            "expected_modules": [":core", ":app"],
            "expected_surfaces": ["BUSINESS_LOGIC"],
        }
        (repo / ".agents/state/tasks/auto-mm").mkdir(parents=True, exist_ok=True)
        atomic_write_json(repo / ".agents/state/tasks/auto-mm/plan.json", mm_plan)
        self.assertEqual(execution_mode.resolve_effective_execution_mode(repo, task_id="auto-mm", plan=mm_plan)["mode"], "web")

        t5_plan = {
            "task_id": "auto-t5",
            "status": "IMPLEMENTING",
            "task_kind": "FEATURE",
            "expected_files": ["app/src/main/AuthManager.kt"],
            "expected_modules": [":app"],
            "expected_surfaces": ["AUTH"],
        }
        (repo / ".agents/state/tasks/auto-t5").mkdir(parents=True, exist_ok=True)
        atomic_write_json(repo / ".agents/state/tasks/auto-t5/plan.json", t5_plan)
        eff_t5 = execution_mode.resolve_effective_execution_mode(repo, task_id="auto-t5", plan=t5_plan)
        self.assertEqual(eff_t5["mode"], "web")
        self.assertEqual(eff_t5["auto_route_trigger"], "AUTO_WEB_CRITICAL_T5_SURFACE")

        # 5) Conflict task under `auto-project` stays local (`normal`) + manual `normal-task` override works on `auto-large-15`!
        conf_plan = {
            "task_id": "auto-conf",
            "status": "IMPLEMENTING",
            "task_kind": "CONFLICT",
            "expected_files": large_files,
        }
        (repo / ".agents/state/tasks/auto-conf").mkdir(parents=True, exist_ok=True)
        atomic_write_json(repo / ".agents/state/tasks/auto-conf/plan.json", conf_plan)
        eff_conf = execution_mode.resolve_effective_execution_mode(repo, task_id="auto-conf", plan=conf_plan)
        self.assertEqual(eff_conf["mode"], "normal")
        self.assertTrue(eff_conf["conflict_auto_local_override"])

        execution_mode.set_execution_mode(
            repo, choice="normal-task", task_id="auto-large-15", source="conversation", proof_reference="Run this 15-file refactor locally"
        )
        eff_over = execution_mode.resolve_effective_execution_mode(repo, task_id="auto-large-15", plan=large_plan)
        self.assertEqual(eff_over["mode"], "normal")
        self.assertEqual(eff_over["project_choice"], "auto-project")

if __name__ == "__main__":
    unittest.main(verbosity=2)
