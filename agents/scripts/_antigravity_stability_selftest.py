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


if __name__ == "__main__":
    unittest.main(verbosity=2)
