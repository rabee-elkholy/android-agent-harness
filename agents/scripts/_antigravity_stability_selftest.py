"""Automated tests for Antigravity stability hardening repair spec."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent.parent

sys.path.insert(0, str(SCRIPTS))


def _with_audit_reason(out: dict, env: dict, engine: Path) -> dict:
    """Hook stdout carries only decision/reason; the reason code is in the audit log."""
    state = env.get("HARNESS_HOOK_STATE")
    audit = Path(state).with_name("audit_log.jsonl") if state else Path(engine).resolve().parent.parent / "state" / "audit_log.jsonl"
    lines = audit.read_text(encoding="utf-8").splitlines() if audit.is_file() else []
    if not lines:
        return out
    record = json.loads(lines[-1])
    enriched = {**out, "reason_code": record.get("reason_code")}
    if record.get("mcp_fingerprint"):
        enriched["mcp_fingerprint"] = record["mcp_fingerprint"]
    return enriched


class TestAgentYaml(unittest.TestCase):
    """P0: Generated custom agent frontmatter and safety checks."""

    def test_AG_YAML_001_colon_in_description_is_safely_quoted(self):
        from install_tool_adapters import antigravity_agent_markdown
        data = {
            "name": "perf-anr-guardian-agent",
            "description": "Senior Android Performance & ANR Guardian: Main-thread blockages, UI freezing, battery drain, and memory leaks.",
            "system_prompt": "You are the Senior Android Performance Guardian.",
        }
        rendered = antigravity_agent_markdown(data)
        # Frontmatter must contain quoted description
        self.assertIn('description: "Senior Android Performance & ANR Guardian: Main-thread blockages, UI freezing, battery drain, and memory leaks."', rendered)
        self.assertIn('name: "perf-anr-guardian-agent"', rendered)

    def test_AG_YAML_002_seven_agents_generated(self):
        from install_tool_adapters import generate_antigravity_agents
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents").mkdir(parents=True)
            # Copy subagents from kit
            kit_subagents = REPO_ROOT / "agents" / "subagents"
            target_subagents = repo / ".agents" / "subagents"
            shutil.copytree(kit_subagents, target_subagents)
            logs = generate_antigravity_agents(repo, dry_run=False)
            expected_roles = [
                "bug-reviewer-agent",
                "security-reviewer-agent",
                "perf-anr-guardian-agent",
                "convention-reviewer-agent",
                "regression-impact-reviewer-agent",
                "test-quality-reviewer-agent",
                "spec-compliance-agent",
            ]
            for role in expected_roles:
                agent_file = repo / ".agents" / "agents" / role / "agent.md"
                self.assertTrue(agent_file.is_file(), f"Missing custom agent: {agent_file}")

    def test_AG_YAML_003_exact_read_only_tools(self):
        from install_tool_adapters import generate_antigravity_agents
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents").mkdir(parents=True)
            shutil.copytree(REPO_ROOT / "agents" / "subagents", repo / ".agents" / "subagents")
            generate_antigravity_agents(repo, dry_run=False)
            for role in [
                "bug-reviewer-agent",
                "security-reviewer-agent",
                "perf-anr-guardian-agent",
                "convention-reviewer-agent",
                "regression-impact-reviewer-agent",
                "test-quality-reviewer-agent",
                "spec-compliance-agent",
            ]:
                agent_file = repo / ".agents" / "agents" / role / "agent.md"
                content = agent_file.read_text(encoding="utf-8")
                # Parse frontmatter tools
                parts = content.split("---")
                self.assertGreaterEqual(len(parts), 3)
                frontmatter = parts[1]
                self.assertIn("tools:\n  - view_file\n  - grep_search\n  - find_by_name\n  - list_dir", frontmatter)
                self.assertNotIn("write_to_file", frontmatter)
                self.assertNotIn("run_command", frontmatter)
                self.assertNotIn("invoke_subagent", frontmatter)
                self.assertNotIn("model:", frontmatter.lower())


    def test_AG_YAML_004_missing_source_fails_closed(self):
        from install_tool_adapters import generate_antigravity_agents
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents" / "subagents").mkdir(parents=True)
            # subagents directory is empty (missing core sources)
            with self.assertRaises((SystemExit, RuntimeError, ValueError)):
                generate_antigravity_agents(repo, dry_run=False)

    def test_AG_YAML_005_invalid_agent_name_or_empty_prompt_fails(self):
        from install_tool_adapters import antigravity_agent_markdown
        with self.assertRaises((ValueError, RuntimeError)):
            antigravity_agent_markdown({"name": "", "description": "desc", "system_prompt": "prompt"})
        with self.assertRaises((ValueError, RuntimeError)):
            antigravity_agent_markdown({"name": "bug-reviewer-agent", "description": "desc", "system_prompt": ""})


class TestBatchDispatchContract(unittest.TestCase):
    """P0: Exact batch and invocation identity checks."""

    def test_AG_BATCH_010_core_dispatch_api_enforces_exact_batch(self):
        from review_orchestrator import dispatchable_reviewers
        ledger = {
            "reviewers": {
                "bug-reviewer-agent": {"state": "NOT_DISPATCHED"},
                "security-reviewer-agent": {"state": "NOT_DISPATCHED"},
            }
        }
        required = ["bug-reviewer-agent", "security-reviewer-agent"]
        dispatchable = dispatchable_reviewers(ledger, required)
        self.assertEqual(sorted(required), sorted(dispatchable))

        # When one is already completed
        ledger["reviewers"]["bug-reviewer-agent"]["state"] = "COMPLETED"
        dispatchable2 = dispatchable_reviewers(ledger, required)
        self.assertEqual(["security-reviewer-agent"], dispatchable2)


class TestV2Accounting(unittest.TestCase):
    """P0: Review rounds and reviewer call accounting in V2."""

    def test_V2_ACCOUNT_001_and_005_finalize_accounting_and_idempotence(self):
        from review_orchestrator import _finalize_review_execution_locked
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            tdir = repo / ".agents" / "state" / "tasks" / "task-1"
            tdir.mkdir(parents=True)
            plan = {
                "schema_version": 2,
                "task_id": "task-1",
                "status": "VERIFYING",
                "review_rounds": 0,
                "review_calls_used": 0,
            }
            (tdir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            (tdir / "current-run.json").write_text(json.dumps({
                "run_id": "run-1",
                "delivery_snapshot_sha256": "a" * 64,
                "manifest": str(tdir / "manifest.json"),
                "policy": str(tdir / "policy.json"),
                "review_package": str(tdir / "review-package.md"),
                "review_protocol_version": 2,
                "review_host": "antigravity",
            }), encoding="utf-8")
            (tdir / "manifest.json").write_text(json.dumps({
                "delivery_snapshot_sha256": "a" * 64,
                "change_set_sha256": "b" * 64,
            }), encoding="utf-8")
            (tdir / "policy.json").write_text(json.dumps({
                "reviewers": ["bug-reviewer-agent", "security-reviewer-agent"],
                "review_round": 1,
                "max_review_rounds": 3,
                "model_call_budget": 20,
            }), encoding="utf-8")
            pkg_file = tdir / "review-package.md"
            pkg_file.write_text("# Review Package\n", encoding="utf-8")
            from _vnext_common import canonical_sha256, sha256_file
            import hashlib
            pkg_sha = sha256_file(pkg_file)

            results_dir = tdir / "review-execution" / "run-1" / "results"
            results_dir.mkdir(parents=True)
            for r in ["bug-reviewer-agent", "security-reviewer-agent"]:
                exec_id = f"exec-{r}"
                parsed_res = {
                    "schema_version": 2,
                    "task_id": "task-1",
                    "run_id": "run-1",
                    "reviewer": r,
                    "review_package_sha256": pkg_sha,
                    "verdict": "PASS",
                    "findings": [],
                }
                res_payload = {
                    "schema_version": 2,
                    "task_id": "task-1",
                    "run_id": "run-1",
                    "reviewer": r,
                    "execution_id": exec_id,
                    "execution_id_sha256": hashlib.sha256(exec_id.encode("utf-8")).hexdigest(),
                    "result_sha256": canonical_sha256(parsed_res),
                    "completed_at": "2026-09-22T00:00:00Z",
                    "result": parsed_res,
                }
                (results_dir / f"{r}.json").write_text(json.dumps(res_payload), encoding="utf-8")

            ledger = {
                "schema_version": 1,
                "task_id": "task-1",
                "run_id": "run-1",
                "delivery_snapshot_sha256": "a" * 64,
                "change_set_sha256": "b" * 64,
                "review_package_sha256": pkg_sha,
                "required_reviewers": ["bug-reviewer-agent", "security-reviewer-agent"],
                "reviewers": {
                    "bug-reviewer-agent": {"state": "COMPLETED"},
                    "security-reviewer-agent": {"state": "COMPLETED"},
                },
            }

            from unittest import mock
            with mock.patch("workflow.verification_freshness", return_value={"fresh": True}):
                evidence = _finalize_review_execution_locked(repo, "task-1", "run-1", ledger)
                self.assertEqual("PASS", evidence.get("verdict"))

                updated_plan = json.loads((tdir / "plan.json").read_text(encoding="utf-8"))
                self.assertEqual(1, updated_plan.get("review_rounds"))
                self.assertEqual(2, updated_plan.get("review_calls_used"))

                # Calling again must be idempotent and not re-increment
                evidence2 = _finalize_review_execution_locked(repo, "task-1", "run-1", ledger)
                updated_plan2 = json.loads((tdir / "plan.json").read_text(encoding="utf-8"))
                self.assertEqual(1, updated_plan2.get("review_rounds"))
                self.assertEqual(2, updated_plan2.get("review_calls_used"))


class TestReasoningSafety(unittest.TestCase):
    """P0: Reasoning capability fail-safe."""

    def test_REASON_SAFE_001_missing_argument_name(self):
        from review_reasoning import HostReasoningCapability, resolve_reasoning
        cap = HostReasoningCapability(
            host="future-host",
            supported=True,
            argument_name=None,
            ordered_levels=("low", "high"),
            current_level="low",
            source="test",
        )
        res = resolve_reasoning(cap, "DEEP")
        self.assertEqual("UNAVAILABLE", res["control"])
        self.assertEqual("INVALID_HOST_CAPABILITY", res["resolution"])
        self.assertIsNone(res["argument_name"])

    def test_REASON_SAFE_002_blank_argument_name(self):
        from review_reasoning import HostReasoningCapability, resolve_reasoning
        cap = HostReasoningCapability(
            host="future-host",
            supported=True,
            argument_name="   ",
            ordered_levels=("low", "high"),
            current_level="low",
            source="test",
        )
        res = resolve_reasoning(cap, "DEEP")
        self.assertEqual("UNAVAILABLE", res["control"])
        self.assertEqual("INVALID_HOST_CAPABILITY", res["resolution"])

    def test_REASON_SAFE_003_invalid_levels(self):
        from review_reasoning import HostReasoningCapability, resolve_reasoning
        # Duplicate levels
        cap1 = HostReasoningCapability(
            host="future-host",
            supported=True,
            argument_name="effort",
            ordered_levels=("low", "low"),
            current_level="low",
            source="test",
        )
        self.assertEqual("UNAVAILABLE", resolve_reasoning(cap1, "DEEP")["control"])

        # Unknown current level
        cap2 = HostReasoningCapability(
            host="future-host",
            supported=True,
            argument_name="effort",
            ordered_levels=("low", "high"),
            current_level="unknown",
            source="test",
        )
        self.assertEqual("UNAVAILABLE", resolve_reasoning(cap2, "DEEP")["control"])

    def test_REASON_SAFE_005_current_antigravity_no_override(self):
        from review_reasoning import capability_for_host, resolve_reasoning
        cap = capability_for_host("antigravity")
        self.assertFalse(cap.supported)
        res = resolve_reasoning(cap, "DEEP")
        self.assertEqual("UNAVAILABLE", res["control"])
        self.assertEqual("HOST_CONTROL_UNAVAILABLE", res["resolution"])
        self.assertIsNone(res["argument_name"])
        self.assertIsNone(res["native_value"])


class TestProtocolParser(unittest.TestCase):
    """P0: Deterministic and total result parsing."""

    def test_V2_PARSE_001_pass_json(self):
        from review_orchestrator import parse_structured_result
        pkg_sha = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        text = f"""Here is my review:
```json
{{
  "schema_version": 2,
  "task_id": "t1",
  "run_id": "r1",
  "reviewer": "bug-reviewer-agent",
  "review_package_sha256": "{pkg_sha}",
  "verdict": "PASS",
  "findings": []
}}
```
"""
        parsed = parse_structured_result(
            text=text,
            expected_task_id="t1",
            expected_run_id="r1",
            expected_reviewer="bug-reviewer-agent",
            expected_package_sha256=pkg_sha,
        )
        self.assertEqual("PASS", parsed["verdict"])
        self.assertEqual([], parsed["findings"])

    def test_V2_PARSE_002_nested_findings(self):
        from review_orchestrator import parse_structured_result
        pkg_sha = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        text = f"""```json
{{
  "schema_version": 2,
  "task_id": "t1",
  "run_id": "r1",
  "reviewer": "bug-reviewer-agent",
  "review_package_sha256": "{pkg_sha}",
  "verdict": "FINDINGS",
  "findings": [
    {{
      "id": "bug-001",
      "severity": "HIGH",
      "message": "Potential null pointer exception",
      "file": "app/src/main/MainActivity.kt",
      "line_start": 42,
      "line_end": 45
    }}
  ]
}}
```"""
        parsed = parse_structured_result(
            text=text,
            expected_task_id="t1",
            expected_run_id="r1",
            expected_reviewer="bug-reviewer-agent",
            expected_package_sha256=pkg_sha,
        )
        self.assertEqual("FINDINGS", parsed["verdict"])
        self.assertEqual(1, len(parsed["findings"]))
        self.assertEqual(42, parsed["findings"][0]["line_start"])

    def test_V2_PARSE_003_invalid_numeric_field_raises_validation_error(self):
        from _vnext_common import ValidationError
        from review_orchestrator import parse_structured_result
        pkg_sha = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        text = f"""```json
{{
  "schema_version": 2,
  "task_id": "t1",
  "run_id": "r1",
  "reviewer": "bug-reviewer-agent",
  "review_package_sha256": "{pkg_sha}",
  "verdict": "FINDINGS",
  "findings": [
    {{
      "id": "bug-001",
      "severity": "HIGH",
      "message": "Invalid line number",
      "file": "app/src/main/MainActivity.kt",
      "line_start": "abc",
      "line_end": 45
    }}
  ]
}}
```"""
        with self.assertRaises(ValidationError):
            parse_structured_result(
                text=text,
                expected_task_id="t1",
                expected_run_id="r1",
                expected_reviewer="bug-reviewer-agent",
                expected_package_sha256=pkg_sha,
            )

    def test_V2_PARSE_004_braces_before_final_json(self):
        from review_orchestrator import parse_structured_result
        pkg_sha = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        text = f"""I found issues with {{variable_name}} in the code.
```json
{{
  "schema_version": 2,
  "task_id": "t1",
  "run_id": "r1",
  "reviewer": "bug-reviewer-agent",
  "review_package_sha256": "{pkg_sha}",
  "verdict": "PASS",
  "findings": []
}}
```"""
        parsed = parse_structured_result(
            text=text,
            expected_task_id="t1",
            expected_run_id="r1",
            expected_reviewer="bug-reviewer-agent",
            expected_package_sha256=pkg_sha,
        )
        self.assertEqual("PASS", parsed["verdict"])

    def test_V2_PARSE_005_malformed_earlier_block(self):
        from review_orchestrator import parse_structured_result
        pkg_sha = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        text = f"""Here is some broken JSON:
```json
{{ "not": "complete"
```
And here is the actual final response:
```json
{{
  "schema_version": 2,
  "task_id": "t1",
  "run_id": "r1",
  "reviewer": "bug-reviewer-agent",
  "review_package_sha256": "{pkg_sha}",
  "verdict": "PASS",
  "findings": []
}}
```"""
        parsed = parse_structured_result(
            text=text,
            expected_task_id="t1",
            expected_run_id="r1",
            expected_reviewer="bug-reviewer-agent",
            expected_package_sha256=pkg_sha,
        )
        self.assertEqual("PASS", parsed["verdict"])


class TestTrustBoundary(unittest.TestCase):
    """P0: Trusted Antigravity path boundary checks."""

    def test_AG_PATH_004_arbitrary_tmp_path_rejected(self):
        from antigravity_runtime import is_trusted_antigravity_path
        with tempfile.TemporaryDirectory() as td:
            fake_dir = Path(td) / ".gemini" / "antigravity" / "brain" / "some-task"
            fake_dir.mkdir(parents=True)
            fake_file = fake_dir / "test.txt"
            fake_file.write_text("hello", encoding="utf-8")
            # Without ANTIGRAVITY_APP_DATA override, an arbitrary /tmp path must be rejected!
            self.assertFalse(is_trusted_antigravity_path(fake_file))

    def test_AG_PATH_005_test_override_works(self):
        from antigravity_runtime import is_trusted_antigravity_path
        with tempfile.TemporaryDirectory() as td:
            orig = os.environ.get("ANTIGRAVITY_APP_DATA")
            try:
                os.environ["ANTIGRAVITY_APP_DATA"] = td
                test_path = Path(td) / "brain" / "conv-1" / "file.txt"
                test_path.parent.mkdir(parents=True)
                test_path.write_text("hello", encoding="utf-8")
                self.assertTrue(is_trusted_antigravity_path(test_path))
            finally:
                if orig is not None:
                    os.environ["ANTIGRAVITY_APP_DATA"] = orig
                else:
                    os.environ.pop("ANTIGRAVITY_APP_DATA", None)

    def test_AG_PATH_006_invalid_conversation_id(self):
        from antigravity_runtime import _is_invalid_conversation_id
        self.assertTrue(_is_invalid_conversation_id("../secret"))
        self.assertTrue(_is_invalid_conversation_id("foo/bar"))
        self.assertTrue(_is_invalid_conversation_id("foo\\bar"))
        self.assertTrue(_is_invalid_conversation_id("foo\0bar"))
        self.assertTrue(_is_invalid_conversation_id("a" * 1000))
        self.assertFalse(_is_invalid_conversation_id("1ab25276-4da2-4140-9a7b-ba987761bdfb"))


class TestExecutionIdentity(unittest.TestCase):
    """P0: Bound execution ID immutability."""

    def test_AG_EXEC_001_and_002_execution_id_immutable(self):
        from _vnext_common import ValidationError
        from review_orchestrator import complete_review
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            tdir = repo / ".agents" / "state" / "tasks" / "task-1"
            tdir.mkdir(parents=True)
            (tdir / "current-run.json").write_text(json.dumps({
                "run_id": "run-1",
                "manifest": str(tdir / "manifest.json"),
                "policy": str(tdir / "policy.json"),
                "review_package": str(tdir / "review-package.md"),
                "review_protocol_version": 2,
                "review_host": "antigravity",
            }), encoding="utf-8")
            (tdir / "manifest.json").write_text(json.dumps({
                "delivery_snapshot_sha256": "a" * 64,
                "change_set_sha256": "b" * 64,
            }), encoding="utf-8")
            (tdir / "policy.json").write_text(json.dumps({
                "reviewers": ["bug-reviewer-agent"],
            }), encoding="utf-8")
            (tdir / "review-package.md").write_text("# Review Package\n", encoding="utf-8")

            # Initialize ledger with bound execution_id in ENV_BLOCKED state
            exec_dir = tdir / "review-execution" / "run-1"
            exec_dir.mkdir(parents=True)
            dispatch_dir = exec_dir / "dispatch"
            dispatch_dir.mkdir(parents=True)
            receipt = {
                "schema_version": 2,
                "task_id": "task-1",
                "run_id": "run-1",
                "reviewer": "bug-reviewer-agent",
                "delivery_snapshot_sha256": "a" * 64,
                "change_set_sha256": "b" * 64,
                "review_package_sha256": "f" * 64,
                "dispatch_nonce": "nonce-1",
                "host": "antigravity",
                "dispatched_at": "2026-09-22T00:00:00Z",
            }
            from _vnext_common import canonical_sha256
            receipt["receipt_sha256"] = canonical_sha256(receipt)
            (dispatch_dir / "bug-reviewer-agent.json").write_text(json.dumps(receipt), encoding="utf-8")

            ledger = {
                "schema_version": 1,
                "task_id": "task-1",
                "run_id": "run-1",
                "delivery_snapshot_sha256": "a" * 64,
                "change_set_sha256": "b" * 64,
                "review_package_sha256": "f" * 64,
                "required_reviewers": ["bug-reviewer-agent"],
                "reviewers": {
                    "bug-reviewer-agent": {
                        "state": "ENV_BLOCKED",
                        "execution_id": "exec-original",
                        "execution_id_sha256": "hash-original",
                    },
                },
            }
            from review_orchestrator import save_ledger
            save_ledger(tdir, "run-1", ledger)

            # Attempting to complete with a different execution ID must be rejected even if ENV_BLOCKED!
            with self.assertRaises(ValidationError):
                complete_review(repo, "task-1", "bug-reviewer-agent", "exec-different", host="antigravity")


class TestDefaultsAndTerminology(unittest.TestCase):
    """P1: Terminology and default budget cap = 20."""

    def test_TERM_001_default_cap_is_20(self):
        import _installer_config
        import _product
        import review_policy
        from doctor.engine import HarnessDoctor

        self.assertEqual(20, _product.MODEL_CALL_BUDGET)
        self.assertEqual(20, review_policy._configured_model_call_budget())

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            prod_path = _installer_config.generate_product_py(repo, {"product": "TestApp"})
            content = prod_path.read_text(encoding="utf-8")
            self.assertIn("MODEL_CALL_BUDGET = 20", content)

    def test_DOCS_001_antigravity_instructions(self):
        gemini_md = (REPO_ROOT / "GEMINI.md").read_text(encoding="utf-8")
        gemini_tpl = (REPO_ROOT / "agents" / "tool-adapters" / "GEMINI.md.template").read_text(encoding="utf-8")
        global_tpl = (REPO_ROOT / "templates" / "gemini-runtime" / "android-harness-global.md.template").read_text(encoding="utf-8")

        for name, content in [("GEMINI.md", gemini_md), ("GEMINI.md.template", gemini_tpl), ("android-harness-global.md.template", global_tpl)]:
            self.assertIn("INHERIT_PARENT_BY_OMISSION", content, f"{name} missing INHERIT_PARENT_BY_OMISSION")
            self.assertNotIn("model must remain inherit", content, f"{name} still has 'model must remain inherit'")
            self.assertNotIn("VERDICT: PASS", content, f"{name} contains legacy PASS token")
            self.assertIn("Exact Reviewer Dispatch Procedure", content, f"{name} missing exact dispatch procedure")

        questions_py = (REPO_ROOT / "agents" / "scripts" / "wizard" / "questions.py").read_text(encoding="utf-8")
        self.assertIn("Reviewer Call Safety Cap", questions_py)


class TestCanonicalDraftRow(unittest.TestCase):
    def test_D2_antigravity_draft_row_names_expected_files(self):
        # New installs refuse a non-trivial draft without --expected-files (PLAN_SCOPE_REQUIRED); the
        # canonical Antigravity draft row did not mention the flag, so the first draft failed.
        for path in (REPO_ROOT / "GEMINI.md", REPO_ROOT / "agents" / "tool-adapters" / "GEMINI.md.template"):
            row = next(line for line in path.read_text(encoding="utf-8").splitlines()
                       if "workflow.py draft --repo . --task-id <id>" in line)
            with self.subTest(path=path.name):
                self.assertIn("--expected-files <paths>", row)


class TestAntigravityPlanHashApproval(unittest.TestCase):
    """B3: the documented Antigravity approval binds the plan hash shown in PLAN_SUMMARY."""

    DOCS = (REPO_ROOT / "GEMINI.md", REPO_ROOT / "agents" / "tool-adapters" / "GEMINI.md.template")

    def _approve_commands(self, path: Path) -> list[str]:
        return re.findall(r"`[^`]*workflow\.py approve [^`]*`", path.read_text(encoding="utf-8"))

    def test_every_documented_approve_carries_the_summary_hash(self):
        for path in self.DOCS:
            commands = self._approve_commands(path)
            with self.subTest(path=path.name):
                self.assertGreaterEqual(len(commands), 2)
                for command in commands:
                    self.assertIn("--plan-hash <hash from PLAN_SUMMARY>", command)

    def test_documented_approval_accepts_the_shown_plan_and_rejects_a_mismatch(self):
        import argparse
        import contextlib
        import io
        import workflow
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            for args in (["init", "-q"], ["config", "user.name", "T"], ["config", "user.email", "t@example.invalid"]):
                subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
            files = {
                "gradlew": "#!/bin/sh\n", "settings.gradle.kts": 'include(":app")\n',
                "app/build.gradle.kts": 'plugins { id("com.android.application") }\n',
                "app/src/main/kotlin/com/example/MainActivity.kt": "package com.example\n\nclass MainActivity\n",
            }
            for rel, text in files.items():
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text(text, encoding="utf-8")
            (repo / ".agents" / "state").mkdir(parents=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True, capture_output=True)
            plan = workflow.draft(argparse.Namespace(
                repo=str(repo), task_id="ag-approve", outcome="Show a finished message", kind="FEATURE",
                planning_depth="BOUNDED", expected_surfaces="BUSINESS_LOGIC", expected_modules=":app",
                architecture_intent="EXISTING_CHANGE", architecture_target_scope="", architecture_target_family=None,
                expected_files="app/src/main/kotlin/com/example/MainActivity.kt", phases=None, force=True,
            ))
            shown = re.search(r"Plan hash: ([0-9a-f]{12})", workflow.plan_summary(plan)).group(1)
            documented = self._approve_commands(self.DOCS[0])[-1].strip("`")
            argv = documented.split("workflow.py ", 1)[1].replace('"<phrase>"', "ok").replace("<id>", "ag-approve").split()
            argv[argv.index("--repo") + 1] = str(repo)
            hash_at = argv.index("<hash") 
            del argv[hash_at:hash_at + 3]
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(1, workflow.main(argv[:hash_at] + ["0" * 12] + argv[hash_at:]))
            self.assertIn("PLAN_HASH_MISMATCH", err.getvalue())
            plan_file = repo / ".agents" / "state" / "tasks" / "ag-approve" / "plan.json"
            self.assertEqual("AWAITING_DEVELOPER_APPROVAL", json.loads(plan_file.read_text(encoding="utf-8"))["status"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, workflow.main(argv[:hash_at] + [shown] + argv[hash_at:]))
            approved = json.loads(plan_file.read_text(encoding="utf-8"))
            self.assertEqual("IMPLEMENTING", approved["status"])
            self.assertEqual(shown, approved["approval"]["presented_plan_hash"])


class TestReviewProtocolV2FailClosed(unittest.TestCase):
    """P0 Section 4: Close remaining Review V2 fail-open boundaries."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        self.state = self.repo / ".agents" / "state"
        self.task_d = self.state / "tasks" / "task-v2"
        self.task_d.mkdir(parents=True, exist_ok=True)

        self.plan_f = self.task_d / "plan.json"
        self.plan_f.write_text(json.dumps({
            "task_id": "task-v2",
            "status": "VERIFYING",
            "review_rounds": 0,
            "review_calls_used": 0,
        }), encoding="utf-8")

        (self.state / "active-task.json").write_text(json.dumps({
            "task_id": "task-v2",
            "plan_path": str(self.plan_f),
        }), encoding="utf-8")

        self.policy_f = self.task_d / "policy.json"
        self.policy_f.write_text(json.dumps({
            "reviewers": ["bug-reviewer-agent"],
            "max_review_rounds": 3,
            "model_call_budget": 20,
        }), encoding="utf-8")

        self.snapshot = "a" * 64
        self.change_set = "b" * 64
        self.manifest_f = self.task_d / "manifest.json"
        self.manifest_f.write_text(json.dumps({
            "delivery_snapshot_sha256": self.snapshot,
            "change_set_sha256": self.change_set,
        }), encoding="utf-8")

        self.runs_d = self.state / "runs" / self.snapshot / "r1"
        self.runs_d.mkdir(parents=True, exist_ok=True)
        self.pkg_f = self.runs_d / "review-package.md"
        self.pkg_f.write_text("# Review Package\n", encoding="utf-8")
        self.brief_f = self.runs_d / "brief-bug-reviewer-agent.md"
        self.brief_f.write_text("# Bug Reviewer Brief Content\n", encoding="utf-8")

        self.current_f = self.task_d / "current-run.json"
        self.current_f.write_text(json.dumps({
            "task_id": "task-v2",
            "run_id": "r1",
            "policy": str(self.policy_f),
            "manifest": str(self.manifest_f),
            "delivery_snapshot_sha256": self.snapshot,
            "change_set_sha256": self.change_set,
            "review_host": "antigravity",
            "review_protocol_version": 2,
        }), encoding="utf-8")

        from review_orchestrator import init_ledger, sha256_file
        init_ledger(
            self.task_d, "task-v2", "r1", self.snapshot, self.change_set,
            sha256_file(self.pkg_f), ["bug-reviewer-agent"]
        )

        self.env = os.environ.copy()
        self.env["HARNESS_REPO"] = str(self.repo)
        self.env["HARNESS_HOOK_STATE"] = str(self.repo / "audit/state.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _call_hook(self, subagents: list[dict]) -> dict:
        payload = {
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Subagents": subagents}
            }
        }
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "pre_tool_safety.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
            timeout=15,
        )
        return _with_audit_reason(json.loads(proc.stdout), self.env, SCRIPTS / "pre_tool_safety.py")

    def test_V2_BOUNDARY_MANUAL_DISPATCH_001_trusted_host_refuses_cli_dispatch(self):
        """On a hook-recorded host, a manual dispatch receipt would strand reviewers that never launched."""
        from review_orchestrator import get_review_execution_status, main as orchestrator_main
        for argv in (
            ["dispatch-batch", "--repo", str(self.repo), "--task", "task-v2", "--host", "antigravity"],
            ["dispatch", "--repo", str(self.repo), "--task", "task-v2", "--reviewer", "bug-reviewer-agent", "--host", "antigravity"],
        ):
            self.assertEqual(1, orchestrator_main(argv), argv)
        status = get_review_execution_status(self.repo, "task-v2")
        self.assertEqual("NOT_DISPATCHED", status["reviewers"]["bug-reviewer-agent"]["state"])
        # The real launch path stays open.
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": self.brief_f.read_text(encoding="utf-8")}])
        self.assertEqual("allow", res["decision"], res.get("reason"))

    def test_V2_BOUNDARY_PROFILE_001_profile_exception_denies_dispatch(self):
        self.current_f.write_text(json.dumps({
            "task_id": "task-v2",
            "run_id": "r1",
            "policy": str(self.task_d / "nonexistent_policy.json"),
            "manifest": str(self.manifest_f),
            "review_host": "antigravity",
            "review_protocol_version": 2,
        }), encoding="utf-8")
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEW_PROFILE_BLOCKED", res.get("reason_code"))

    def test_V2_BOUNDARY_PROFILE_002_empty_profile_denies_dispatch(self):
        self.policy_f.write_text(json.dumps({"reviewers": [], "max_review_rounds": 3, "model_call_budget": 20}), encoding="utf-8")
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertIn(res.get("reason_code"), ("REVIEW_PROFILE_BLOCKED", "REVIEWER_ROSTER_EMPTY", "REVIEWER_ROSTER_EXTRA"))

    def test_V2_BOUNDARY_PROFILE_003_reviewer_missing_from_profile_denies(self):
        self.policy_f.write_text(json.dumps({"reviewers": ["bug-reviewer-agent", "security-reviewer-agent"], "max_review_rounds": 3, "model_call_budget": 20}), encoding="utf-8")
        res = self._call_hook([
            {"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"},
            {"Role": "security-reviewer-agent", "TypeName": "security-reviewer-agent", "Prompt": "Security brief"},
        ])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEW_PROFILE_BLOCKED", res.get("reason_code"))

    def test_V2_BOUNDARY_PROFILE_004_missing_brief_denies_before_receipt(self):
        self.brief_f.unlink()
        receipt_p = self.task_d / "review-execution/r1/dispatch/bug-reviewer-agent.json"
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEW_PROFILE_BLOCKED", res.get("reason_code"))
        self.assertFalse(receipt_p.is_file())

    def test_V2_BOUNDARY_PROFILE_005_no_ledger_state_change_on_profile_denial(self):
        from review_orchestrator import load_ledger
        self.brief_f.unlink()
        l_before = load_ledger(self.task_d, "r1")
        self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        l_after = load_ledger(self.task_d, "r1")
        self.assertEqual(l_before, l_after)

    def test_V2_IDENTITY_001_valid_role_typename_prompt_passes(self):
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("allow", res["decision"])

    def test_V2_IDENTITY_002_valid_typename_garbage_role_denied(self):
        res = self._call_hook([{"Role": "garbage-role", "TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEWER_ROLE_MISMATCH", res.get("reason_code"))

    def test_V2_IDENTITY_003_valid_role_garbage_typename_denied(self):
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "garbage-type", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEWER_ROLE_MISMATCH", res.get("reason_code"))

    def test_V2_IDENTITY_004_missing_role_denied(self):
        res = self._call_hook([{"TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("MISSING_SUBAGENT_ROLE", res.get("reason_code"))

    def test_V2_IDENTITY_005_missing_typename_denied(self):
        res = self._call_hook([{"Role": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("MISSING_SUBAGENT_TYPENAME", res.get("reason_code"))

    def test_V2_IDENTITY_006_missing_prompt_denied(self):
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("MISSING_SUBAGENT_PROMPT", res.get("reason_code"))

    def test_V2_IDENTITY_007_empty_prompt_denied(self):
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "   "}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("MISSING_SUBAGENT_PROMPT", res.get("reason_code"))

    def test_V2_IDENTITY_008_stale_prompt_denied(self):
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "# Stale previous brief"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEWER_PROMPT_MISMATCH", res.get("reason_code"))

    def test_V2_IDENTITY_009_crlf_lf_normalized_prompt_passes(self):
        res = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "\r\n# Bug Reviewer Brief Content\r\n"}])
        self.assertEqual("allow", res["decision"])

    def test_V2_IDENTITY_010_model_or_Model_denied(self):
        res1 = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content", "model": "inherit"}])
        self.assertEqual("deny", res1["decision"])
        self.assertEqual("REVIEWER_MODEL_OVERRIDE_FORBIDDEN", res1.get("reason_code"))
        res2 = self._call_hook([{"Role": "bug-reviewer-agent", "TypeName": "bug-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content", "Model": None}])
        self.assertEqual("deny", res2["decision"])
        self.assertEqual("REVIEWER_MODEL_OVERRIDE_FORBIDDEN", res2.get("reason_code"))

    def test_V2_MODEL_OMISSION_001_antigravity_profile_contract(self):
        from review_execution import resolve_execution_profile
        prof = resolve_execution_profile(self.repo, "task-v2", host="antigravity")
        self.assertEqual("INHERIT_PARENT_BY_OMISSION", prof["model_policy"])
        self.assertIsNone(prof["dispatch_contract"]["model_argument"])
        self.assertNotIn("model", prof)
        rev = prof["reviewers"]["bug-reviewer-agent"]
        self.assertNotIn("required_model", rev)
        self.assertNotIn("preferred_model", rev)
        self.assertNotIn("fallback_model", rev)


class TestResourceWriteScope(unittest.TestCase):
    def test_O13_resource_surface_never_expands_explicit_files(self):
        from plan_authority import check_material_drift
        approved = 'app/src/main/res/values/strings.xml'
        for surface in ('RESOURCE_UI', 'XML_UI', 'LOCALIZATION'):
            plan = dict(expected_files=[approved], expected_surfaces=[surface],
                        expected_modules=[':app', ':core'])
            for path in ('app/src/main/res/values/colors.xml',
                         'app/src/debug/res/values/strings.xml',
                         'app/src/demo/res/values-ar/strings.xml',
                         'core/src/main/res/values/strings.xml'):
                for candidate in (path, path.replace('/', '\\')):
                    with self.subTest(surface=surface, path=candidate):
                        self.assertEqual(['file:' + path], check_material_drift(
                            plan, [surface], [':core' if path.startswith('core/') else ':app'], [candidate]))
            self.assertEqual([], check_material_drift(plan, [surface], [':app'], [approved]))
            plan['expected_files'] = [approved.replace('/', '\\')]
            self.assertEqual([], check_material_drift(plan, [surface], [':app'], [approved]))

    def test_O13_existing_surface_scope_and_test_companions_remain_supported(self):
        from plan_authority import check_material_drift
        plan = dict(expected_files=[], expected_surfaces=['LOCALIZATION'], expected_modules=[':app'])
        self.assertEqual([], check_material_drift(plan, ['RESOURCE_UI'], [':app'],
                                                ['app/src/demo/res/values-ar/new.xml']))
        self.assertEqual(['module:core'], check_material_drift(plan, ['RESOURCE_UI'], [':core'],
                                                               ['core/src/main/res/values/new.xml']))
        plan.update(expected_files=['app/src/main/res/values/strings.xml'], test_strategy='add unit tests')
        self.assertEqual([], check_material_drift(plan, ['TEST_ONLY'], [':app'],
                                                ['app/src/test/kotlin/LabelTest.kt']))

    def test_O13_guard_prepare_and_revised_approval_agree_on_new_resources(self):
        import argparse
        import workflow
        from _daily_workflow_selftest import DailyWorkflowSelftest, write_file
        from mutation_guard import file_mutation_allowed
        from _vnext_common import ValidationError
        fixture = DailyWorkflowSelftest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        repo = fixture.repo
        approved = 'app/src/main/res/values/strings.xml'
        added = 'app/src/debug/res/values/new.xml'
        other = 'core/src/main/res/values/new.xml'
        # Declare both modules before drafting; file authority is independent of module authority.
        write_file(repo / 'core/build.gradle.kts', 'plugins { id("com.android.library") }\n')
        write_file(repo / 'settings.gradle.kts', 'include(":app", ":core")\n')
        from _daily_workflow_selftest import run_git
        run_git(repo, 'add', '.')
        run_git(repo, 'commit', '-qm', 'declare modules')
        plan = workflow.draft(fixture._draft_ns('resource-scope', expected_files=approved,
            expected_surfaces='LOCALIZATION', expected_modules=':app,:core'))
        approval = argparse.Namespace(repo=str(repo), task_id='resource-scope', source='conversation',
                                      proof_reference='approved', enforcement_tier='RULE_ENFORCED',
                                      plan_hash=plan['plan_sha256'][:12])
        workflow.record_approval(approval)
        self.assertTrue(file_mutation_allowed(repo, targets=[approved])[0])
        for target in (added, other):
            allowed, reason, code = file_mutation_allowed(repo, targets=[target])
            self.assertFalse(allowed, reason)
            self.assertEqual('SCOPE_EXPANSION_REQUIRES_REVISED_APPROVAL', code)
            self.assertIn('file:' + target, reason)
        write_file(repo / added, '<resources><string name="new_label">New</string></resources>\n')
        with self.assertRaisesRegex(ValidationError, 'file:app/src/debug/res/values/new.xml'):
            workflow.prepare_verification(repo, 'resource-scope')
        parser = workflow.build_parser()
        revision = workflow.revise(parser.parse_args(['revise', '--repo', str(repo), '--task-id',
            'resource-scope', '--expected-files', ','.join([approved, added, other])]))
        self.assertFalse(file_mutation_allowed(repo, targets=[other])[0])
        with self.assertRaises(ValidationError):
            workflow.record_approval(approval)  # Old hash cannot authorize new scope.
        approval.plan_hash = revision['plan_sha256'][:12]
        workflow.record_approval(approval)
        for target in (added, other):
            self.assertTrue(file_mutation_allowed(repo, targets=[target])[0])
        write_file(repo / other, '<resources><string name="core_label">Core</string></resources>\n')
        current = workflow.prepare_verification(repo, 'resource-scope')
        self.assertTrue(current['run_id'])

    def test_O13_changed_paths_preserve_task_delta_and_copy_semantics(self):
        from plan_authority import changed_file_paths
        baseline = {'path': 'outside/baseline.xml', 'status': 'M'}
        self.assertEqual([], changed_file_paths({'task_changes': [], 'changes': [baseline]}))
        self.assertEqual(['outside/baseline.xml'], changed_file_paths({'changes': [baseline]}))
        manifest = {'task_changes': [
            {'path': r'app\src\debug\res\values\new.xml',
             'old_path': r'app\src\main\res\values\old.xml', 'status': 'R100'},
            {'path': 'app/src/main/res/values/copy.xml', 'old_path': 'outside/read-only.xml', 'status': 'C100'},
            {'path': 'app/src/main/res/values/deleted.xml', 'status': 'D'},
        ], 'changes': [baseline]}
        self.assertEqual([
            'app/src/debug/res/values/new.xml', 'app/src/main/res/values/copy.xml',
            'app/src/main/res/values/deleted.xml', 'app/src/main/res/values/old.xml',
        ], changed_file_paths(manifest))
        self.assertEqual(['outside/baseline.xml'], changed_file_paths(manifest, task_only=False))

    def test_O13_prepare_checks_rename_source_and_revise_hint(self):
        import argparse
        import workflow
        from _daily_workflow_selftest import DailyWorkflowSelftest
        from _vnext_common import ValidationError
        from mutation_guard import file_mutation_allowed
        fixture = DailyWorkflowSelftest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        repo = fixture.repo
        source = 'app/src/main/res/values/strings.xml'
        target = 'app/src/main/res/values/labels.xml'
        plan = workflow.draft(fixture._draft_ns('rename-scope', expected_files=target,
            expected_surfaces='LOCALIZATION'))
        approval = argparse.Namespace(repo=str(repo), task_id='rename-scope', source='conversation',
            proof_reference='approved', enforcement_tier='RULE_ENFORCED', plan_hash=plan['plan_sha256'][:12])
        workflow.record_approval(approval)
        self.assertFalse(file_mutation_allowed(repo, targets=[source, target])[0])
        (repo / source).rename(repo / target)
        with self.assertRaisesRegex(ValidationError, 'file:' + source) as failure:
            workflow.prepare_verification(repo, 'rename-scope')
        self.assertIn(source, str(failure.exception).split('--expected-files', 1)[1])
        revised = workflow.revise(workflow.build_parser().parse_args([
            'revise', '--repo', str(repo), '--task-id', 'rename-scope', '--expected-files', source + ',' + target]))
        approval.plan_hash = revised['plan_sha256'][:12]
        workflow.record_approval(approval)
        self.assertTrue(workflow.prepare_verification(repo, 'rename-scope')['run_id'])

    def test_O13_final_verifier_rechecks_files_in_previously_frozen_runs(self):
        import argparse
        from unittest import mock
        import workflow
        from final_verifier import verify_task
        from _daily_workflow_selftest import DailyWorkflowSelftest, write_file
        for rename in (False, True):
            with self.subTest(rename=rename):
                fixture = DailyWorkflowSelftest()
                fixture.setUp()
                self.addCleanup(fixture.tearDown)
                repo = fixture.repo
                source = 'app/src/main/res/values/strings.xml'
                target = 'app/src/main/res/values/labels.xml'
                plan = workflow.draft(fixture._draft_ns('frozen-scope',
                    expected_files=target if rename else source, expected_surfaces='LOCALIZATION'))
                workflow.record_approval(argparse.Namespace(repo=str(repo), task_id='frozen-scope',
                    source='conversation', proof_reference='approved', enforcement_tier='RULE_ENFORCED',
                    plan_hash=plan['plan_sha256'][:12]))
                if rename:
                    (repo / source).rename(repo / target)
                else:
                    write_file(repo / target, '<resources><string name="new">New</string></resources>\n')
                # Model a frozen run from the older, permissive preparation path.
                # The real final verifier must independently enforce approved file authority.
                with mock.patch.object(workflow, 'check_material_drift', return_value=[]):
                    workflow.prepare_verification(repo, 'frozen-scope')
                result = verify_task(repo, 'frozen-scope')
                self.assertEqual('PLAN_APPROVAL_REQUIRED', result['status'], result)
                self.assertIn('file:' + (source if rename else target), '\n'.join(result['blocked_by']))


class TestReviewerBriefCLI(unittest.TestCase):
    def test_O20_text_cli_exposes_dispatch_inputs_once_and_preserves_json(self):
        import contextlib
        import io
        from unittest import mock
        import workflow
        role = 'bug-reviewer-agent'
        for code in ('DISPATCH_REVIEWERS', 'DISPATCH_PHASE_REVIEWERS'):
            for protocol in (1, 2):
                with self.subTest(code=code, protocol=protocol):
                    inputs = {'repo': '.', 'task_id': 't', 'run_id': 'current-run',
                              'reviewers': [role], 'briefs': {role: '/current/brief.md'},
                              'review_execution_profile': {'reviewers': {role: {
                                  'brief_path': '/current/brief.md',
                                  'brief_content': '# Exact brief\nRun: current-run\nSnapshot: abc\n',
                                  'model_policy': 'INHERIT_PARENT_BY_OMISSION'}}}}
                    if code == 'DISPATCH_PHASE_REVIEWERS':
                        inputs['phase_id'] = 'p1'
                    action = dict(code=code, kind='HOST_ACTION', command='', reason='Dispatch', inputs=inputs)
                    plan = {'task_id': 't', 'status': 'VERIFYING', 'review_protocol_version': protocol}
                    with mock.patch.object(workflow, '_load_plan', return_value=plan), \
                         mock.patch.object(workflow, 'resolve_next_action', return_value=action):
                        out = io.StringIO()
                        args = ['status', '--repo', '.', '--task-id', 't', '--next']
                        with contextlib.redirect_stdout(out):
                            self.assertEqual(0, workflow.main(args))
                        lines = [line for line in out.getvalue().splitlines() if line.startswith('NEXT_ACTION_INPUTS=')]
                        self.assertEqual(1, len(lines), out.getvalue())
                        self.assertEqual(inputs, json.loads(lines[0].split('=', 1)[1]))
                        out = io.StringIO()
                        with contextlib.redirect_stdout(out):
                            self.assertEqual(0, workflow.main(args + ['--json']))
                        self.assertEqual(inputs, json.loads(out.getvalue())['next_action']['inputs'])

    def test_O20_wait_does_not_repeat_briefs_or_request_dispatch(self):
        import contextlib
        import io
        from unittest import mock
        import workflow
        with mock.patch.object(workflow, '_load_plan', return_value={'status': 'VERIFYING'}), \
             mock.patch.object(workflow, 'resolve_next_action', return_value={
                 'code': 'WAIT_FOR_REVIEWERS', 'kind': 'HOST_ACTION', 'inputs': {'task_id': 't'}}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(0, workflow.main(['status', '--task-id', 't', '--next']))
            self.assertNotIn('NEXT_ACTION_INPUTS=', out.getvalue())
            self.assertNotIn('DISPATCH_REVIEWERS', out.getvalue())


class TestGradleProgress(unittest.TestCase):
    def test_O3_gradle_uses_only_stream_heartbeat_and_preserves_outcomes(self):
        import contextlib
        from unittest import mock
        import run_gradle_task as runner
        for code, raw in ((0, 'BUILD SUCCESSFUL\n'), (7, 'compiler failed\n')):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as td:
                beats = []
                @contextlib.contextmanager
                def step(name, **kwargs):
                    beats.append(kwargs.get('heartbeat_sec', 5.0))
                    yield
                def stream(*args, **kwargs):
                    beats.append(kwargs['heartbeat_sec'])
                    return code, raw, raw.splitlines()
                with mock.patch.object(runner, 'step_progress', step), \
                     mock.patch.object(runner, 'run_streaming', stream), \
                     mock.patch.object(runner, 'gradle_wrapper', return_value=Path(td) / 'gradlew'), \
                     mock.patch.object(runner, 'write_gate_result') as record, \
                     mock.patch.object(runner, 'live_print'), \
                     mock.patch.object(runner, 'enable_line_buffered_stdio'), \
                     mock.patch.object(runner, 'current_head_sha', return_value='head'):
                    self.assertEqual(code, runner.run_gradle([':app:compileDebugKotlin'], cwd=td))
                    self.assertEqual(1, sum(beat > 0 for beat in beats))
                    self.assertEqual(code, record.call_args.args[1]['exit_code'])
                    self.assertEqual('PASS' if code == 0 else 'FAIL', record.call_args.args[1]['status'])

    def test_O3_step_stops_and_joins_heartbeat_on_all_exits(self):
        from unittest import mock
        import _live_process as live
        for error in (None, RuntimeError, KeyboardInterrupt, SystemExit):
            with self.subTest(error=error):
                depth = len(live._active_step_has_sublogs)
                event = mock.Mock()
                worker = mock.Mock()
                with mock.patch.object(live.threading, 'Event', return_value=event), \
                     mock.patch.object(live.threading, 'Thread', return_value=worker), \
                     mock.patch.object(live, 'live_print') as output:
                    try:
                        with live.step_progress('test'):
                            if error:
                                raise error()
                    except BaseException as exc:
                        self.assertIsInstance(exc, error)
                    event.set.assert_called()
                    worker.join.assert_called_once()
                    self.assertEqual(depth, len(live._active_step_has_sublogs))
                    self.assertIn('[Fail]' if error else '[Done]', output.call_args.args[0])
                # Keep a RED failure isolated from later tests.
                del live._active_step_has_sublogs[depth:]

    def test_O3_stream_silence_output_failure_and_interrupt_preserve_raw_log(self):
        from unittest import mock
        import _live_process as live
        # Explicit clock/event ticks exercise silence without timing thresholds or sleeps.
        for lines, code, interrupted in (([], 0, False), (['one\n', 'two\n'], 0, False),
                                         (['failed\n'], 9, False), ([], 0, True)):
            with self.subTest(lines=lines, code=code, interrupted=interrupted):
                clock = [0.0]
                events = []
                workers = []
                class Event:
                    def __init__(self):
                        self.stopped = False
                        self.ticks = 0
                        events.append(self)
                    def set(self):
                        self.stopped = True
                    def wait(self, delay):
                        if self.stopped or self.ticks:
                            return True
                        self.ticks += 1
                        clock[0] += 1 if lines else 11
                        return False
                class Worker:
                    def __init__(self, target, **kwargs):
                        self.target = target
                        self.joined = False
                        workers.append(self)
                    def start(self):
                        pass
                    def join(self, **kwargs):
                        self.joined = True
                class Output:
                    def __iter__(self):
                        if interrupted:
                            raise KeyboardInterrupt()
                        if not lines:
                            workers[0].target()
                        for line in lines:
                            yield line
                            events[0].ticks = 0
                            workers[0].target()  # Advance one second between visible lines.
                    def close(self):
                        pass
                proc = mock.Mock(stdout=Output(), returncode=code)
                with mock.patch.object(live.threading, 'Event', Event), \
                     mock.patch.object(live.threading, 'Thread', Worker), \
                     mock.patch.object(live.time, 'time', side_effect=lambda: clock[0]), \
                     mock.patch.object(live.subprocess, 'Popen', return_value=proc), \
                     mock.patch.object(live, 'enable_line_buffered_stdio'), \
                     mock.patch.object(live, 'live_print') as output:
                    if interrupted:
                        with self.assertRaises(KeyboardInterrupt):
                            live.run_streaming(['gradle'])
                        proc.terminate.assert_called_once()
                    else:
                        result = live.run_streaming(['gradle'])
                        self.assertEqual((code, ''.join(lines), [s.rstrip('\n') for s in lines]), result)
                        beats = [c for c in output.call_args_list if 'still running' in c.args[0]]
                        self.assertEqual(0 if lines else 1, len(beats))
                    self.assertTrue(events[0].stopped)
                    self.assertTrue(workers[0].joined)
                    count = output.call_count
                    workers[0].target()
                    self.assertEqual(count, output.call_count)  # No heartbeat after completion.
        with mock.patch.object(live.subprocess, 'Popen', side_effect=OSError('launch failed')), \
             mock.patch.object(live.threading, 'Thread') as worker, \
             mock.patch.object(live, 'enable_line_buffered_stdio'), mock.patch.object(live, 'live_print'):
            self.assertEqual((1, '', []), live.run_streaming(['missing-gradle']))
            worker.assert_not_called()

    def test_O3_real_child_preserves_output_and_exit_codes(self):
        from unittest import mock
        import _live_process as live
        for code in (0, 7):
            with self.subTest(code=code), mock.patch.object(live, "enable_line_buffered_stdio"), \
                 mock.patch.object(live, "live_print"):
                result = live.run_streaming(
                    [sys.executable, "-c", f"print('child output', flush=True); raise SystemExit({code})"],
                )
                self.assertEqual((code, "child output\n", ["child output"]), result)

    def test_O15_gradle_preserves_explicit_daemon_arguments_and_environment(self):
        from unittest import mock
        import run_gradle_task as runner
        for flag in ([], ['--no-daemon'], ['--daemon'], ['-Dorg.gradle.daemon=false']):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as td:
                env = {'JAVA_HOME': '/selected/jdk', 'GRADLE_USER_HOME': '/selected/gradle',
                       'JAVA_OPTS': '-Xmx128m', 'GRADLE_OPTS': '-Dorg.gradle.daemon=false'}
                with mock.patch.dict(os.environ, env), \
                     mock.patch.object(runner, 'gradle_wrapper', return_value=Path(td) / 'gradlew'), \
                     mock.patch.object(runner, 'run_streaming', return_value=(0, '', [])) as stream, \
                     mock.patch.object(runner, 'write_gate_result'), mock.patch.object(runner, 'live_print'), \
                     mock.patch.object(runner, 'current_head_sha', return_value='head'), \
                     mock.patch.object(runner, 'enable_line_buffered_stdio'):
                    self.assertEqual(0, runner.run_gradle([':app:compileDebugKotlin', *flag], cwd=td))
                args, kwargs = stream.call_args
                self.assertEqual(['--console=plain', ':app:compileDebugKotlin', *flag], args[0][-2-len(flag):])
                for key, value in env.items():
                    self.assertEqual(value, kwargs['env'][key])
                self.assertEqual(str(Path(td).resolve()), kwargs['cwd'])

if __name__ == "__main__":
    unittest.main(verbosity=2)
