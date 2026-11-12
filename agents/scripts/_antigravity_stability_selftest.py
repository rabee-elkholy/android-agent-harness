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
    if not state and Path(engine).resolve().parent == Path(__file__).resolve().parent:
        # The kit's own agents/state log is shared by every parallel selftest worker, so its
        # last line can belong to another process (flaky reason codes on CI).
        raise AssertionError("hook call on the kit engine needs HARNESS_HOOK_STATE for an isolated audit log")
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
            "name": "security-perf-reviewer-agent",
            "description": "Senior Android Performance & ANR Guardian: Main-thread blockages, UI freezing, battery drain, and memory leaks.",
            "system_prompt": "You are the Senior Android Performance Guardian.",
        }
        rendered = antigravity_agent_markdown(data)
        # Frontmatter must contain quoted description
        self.assertIn('description: "Senior Android Performance & ANR Guardian: Main-thread blockages, UI freezing, battery drain, and memory leaks."', rendered)
        self.assertIn('name: "security-perf-reviewer-agent"', rendered)

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
                "bug-test-reviewer-agent",
                "security-perf-reviewer-agent",
                "arch-regression-reviewer-agent",
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
                "bug-test-reviewer-agent",
                "security-perf-reviewer-agent",
                "arch-regression-reviewer-agent",
                "spec-compliance-agent",
            ]:
                agent_file = repo / ".agents" / "agents" / role / "agent.md"
                content = agent_file.read_text(encoding="utf-8")
                # Parse frontmatter tools
                parts = content.split("---")
                self.assertGreaterEqual(len(parts), 3)
                frontmatter = parts[1]
                self.assertIn("tools:\n  - view_file\n  - grep_search\n  - find_by_name", frontmatter)
                self.assertNotIn("write_to_file", frontmatter)
                self.assertNotIn("run_command", frontmatter)
                self.assertNotIn("list_dir", frontmatter)
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
            antigravity_agent_markdown({"name": "bug-test-reviewer-agent", "description": "desc", "system_prompt": ""})

    def test_AG_YAML_006_in_place_engine_sync_preserves_agents_directory(self):
        from lifecycle import IN_PLACE_KEEP, _sync_tree_in_place
        self.assertIn("agents", IN_PLACE_KEEP)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "staging"
            dst = root / "repo_agents"
            (src / "subagents").mkdir(parents=True)
            (src / "subagents" / "bug-test-reviewer-agent.json").write_text('{"name":"bug-test-reviewer-agent"}', encoding="utf-8")
            agent_dir = dst / "agents" / "bug-test-reviewer-agent"
            agent_dir.mkdir(parents=True)
            agent_md = agent_dir / "agent.md"
            agent_md.write_text("# existing custom agent\n", encoding="utf-8")
            _sync_tree_in_place(src, dst, keep=IN_PLACE_KEEP)
            self.assertTrue(agent_md.is_file(), "in-place sync must keep .agents/agents/<role>/agent.md intact")
            self.assertEqual("# existing custom agent\n", agent_md.read_text(encoding="utf-8"))

    def test_AG_YAML_007_doctor_checks_vscode_watcher_exclusions(self):
        from doctor.engine import HarnessDoctor
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents").mkdir(parents=True)
            (repo / ".vscode").mkdir(parents=True)
            (repo / ".vscode" / "settings.json").write_text('{"files.watcherExclude": {"**/build/**": true}}', encoding="utf-8")
            doc = HarnessDoctor(repo, run_selftest=False)
            doc.is_raw_kit = False
            doc._check_watcher_exclusions("13. Antigravity & Review V2 Foundation", is_ag=True)
            chk = next(r for r in doc.results if r.name == "File Watcher Exclusions")
            self.assertEqual("WARN", chk.status)
            self.assertTrue(any("**/.gradle/**" in d for d in (chk.details or [])))

            (repo / ".vscode" / "settings.json").write_text(
                json.dumps({
                    "files.watcherExclude": {
                        "**/build/**": True,
                        "**/.gradle/**": True,
                        "**/.kotlin/**": True,
                        "**/.cxx/**": True,
                        "**/.agents/cache/**": True,
                    }
                }),
                encoding="utf-8",
            )
            doc2 = HarnessDoctor(repo, run_selftest=False)
            doc2.is_raw_kit = False
            doc2._check_watcher_exclusions("13. Antigravity & Review V2 Foundation", is_ag=True)
            chk2 = next(r for r in doc2.results if r.name == "File Watcher Exclusions")
            self.assertEqual("PASS", chk2.status)


class TestBatchDispatchContract(unittest.TestCase):
    """P0: Exact batch and invocation identity checks."""

    def test_AG_BATCH_010_core_dispatch_api_enforces_exact_batch(self):
        from review_orchestrator import dispatchable_reviewers
        ledger = {
            "reviewers": {
                "bug-test-reviewer-agent": {"state": "NOT_DISPATCHED"},
                "security-perf-reviewer-agent": {"state": "NOT_DISPATCHED"},
            }
        }
        required = ["bug-test-reviewer-agent", "security-perf-reviewer-agent"]
        dispatchable = dispatchable_reviewers(ledger, required)
        self.assertEqual(sorted(required), sorted(dispatchable))

        # When one is already completed
        ledger["reviewers"]["bug-test-reviewer-agent"]["state"] = "COMPLETED"
        dispatchable2 = dispatchable_reviewers(ledger, required)
        self.assertEqual(["security-perf-reviewer-agent"], dispatchable2)


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
                "task_id": "task-1",
                "run_id": "run-1",
                "delivery_snapshot_sha256": "a" * 64,
                "manifest": str(tdir / "manifest-run-1.json"),
                "policy": str(tdir / "policy.json"),
                "review_package": str(tdir / "review-package.md"),
                "review_protocol_version": 2,
                "review_host": "antigravity",
            }), encoding="utf-8")
            (tdir / "manifest-run-1.json").write_text(json.dumps({
                "delivery_snapshot_sha256": "a" * 64,
                "change_set_sha256": "b" * 64,
            }), encoding="utf-8")
            (tdir / "policy.json").write_text(json.dumps({
                "reviewers": ["bug-test-reviewer-agent", "security-perf-reviewer-agent"],
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
            for r in ["bug-test-reviewer-agent", "security-perf-reviewer-agent"]:
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
                "required_reviewers": ["bug-test-reviewer-agent", "security-perf-reviewer-agent"],
                "reviewers": {
                    "bug-test-reviewer-agent": {"state": "COMPLETED"},
                    "security-perf-reviewer-agent": {"state": "COMPLETED"},
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
  "reviewer": "bug-test-reviewer-agent",
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
            expected_reviewer="bug-test-reviewer-agent",
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
  "reviewer": "bug-test-reviewer-agent",
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
            expected_reviewer="bug-test-reviewer-agent",
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
  "reviewer": "bug-test-reviewer-agent",
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
                expected_reviewer="bug-test-reviewer-agent",
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
  "reviewer": "bug-test-reviewer-agent",
  "review_package_sha256": "{pkg_sha}",
  "verdict": "PASS",
  "findings": []
}}
```"""
        parsed = parse_structured_result(
            text=text,
            expected_task_id="t1",
            expected_run_id="r1",
            expected_reviewer="bug-test-reviewer-agent",
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
  "reviewer": "bug-test-reviewer-agent",
  "review_package_sha256": "{pkg_sha}",
  "verdict": "PASS",
  "findings": []
}}
```"""
        parsed = parse_structured_result(
            text=text,
            expected_task_id="t1",
            expected_run_id="r1",
            expected_reviewer="bug-test-reviewer-agent",
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
                "reviewers": ["bug-test-reviewer-agent"],
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
                "reviewer": "bug-test-reviewer-agent",
                "delivery_snapshot_sha256": "a" * 64,
                "change_set_sha256": "b" * 64,
                "review_package_sha256": "f" * 64,
                "dispatch_nonce": "nonce-1",
                "host": "antigravity",
                "dispatched_at": "2026-09-22T00:00:00Z",
            }
            from _vnext_common import canonical_sha256
            receipt["receipt_sha256"] = canonical_sha256(receipt)
            (dispatch_dir / "bug-test-reviewer-agent.json").write_text(json.dumps(receipt), encoding="utf-8")

            ledger = {
                "schema_version": 1,
                "task_id": "task-1",
                "run_id": "run-1",
                "delivery_snapshot_sha256": "a" * 64,
                "change_set_sha256": "b" * 64,
                "review_package_sha256": "f" * 64,
                "required_reviewers": ["bug-test-reviewer-agent"],
                "reviewers": {
                    "bug-test-reviewer-agent": {
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
                complete_review(repo, "task-1", "bug-test-reviewer-agent", "exec-different", host="antigravity")


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
        gemini_tpl = (REPO_ROOT / "agents" / "tool-adapters" / "GEMINI.md.template").read_text(encoding="utf-8")
        global_tpl = (REPO_ROOT / "agents" / "tool-adapters" / "gemini-runtime" / "android-harness-global.md.template").read_text(encoding="utf-8")

        for name, content in [("GEMINI.md.template", gemini_tpl), ("android-harness-global.md.template", global_tpl)]:
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
        for path in (REPO_ROOT / "agents" / "tool-adapters" / "GEMINI.md.template",):
            row = next(line for line in path.read_text(encoding="utf-8").splitlines()
                       if "harness.py task draft --repo . --task-id <id>" in line)
            with self.subTest(path=path.name):
                self.assertIn("--expected-files <paths>", row)


class TestAntigravityPlanHashApproval(unittest.TestCase):
    """B3: the documented Antigravity approval binds the plan hash that draft prints (PLAN_HASH)."""

    DOCS = (REPO_ROOT / "agents" / "tool-adapters" / "GEMINI.md.template",)

    def _approve_commands(self, path: Path) -> list[str]:
        return re.findall(r"`[^`]*harness\.py task approve [^`]*`", path.read_text(encoding="utf-8"))

    def test_every_documented_approve_carries_the_summary_hash(self):
        for path in self.DOCS:
            commands = self._approve_commands(path)
            with self.subTest(path=path.name):
                self.assertGreaterEqual(len(commands), 2)
                for command in commands:
                    self.assertIn("--plan-hash <hash from PLAN_HASH>", command)

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
            argv = documented.split("harness.py task ", 1)[1].replace('"<phrase>"', "ok").replace("<id>", "ag-approve").split()
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
            "reviewers": ["bug-test-reviewer-agent"],
            "max_review_rounds": 3,
            "model_call_budget": 20,
        }), encoding="utf-8")

        self.snapshot = "a" * 64
        self.change_set = "b" * 64
        self.manifest_f = self.task_d / "manifest-r1.json"
        self.manifest_f.write_text(json.dumps({
            "delivery_snapshot_sha256": self.snapshot,
            "change_set_sha256": self.change_set,
        }), encoding="utf-8")

        self.runs_d = self.state / "runs" / self.snapshot / "r1"
        self.runs_d.mkdir(parents=True, exist_ok=True)
        self.pkg_f = self.runs_d / "review-package.md"
        self.pkg_f.write_text("# Review Package\n", encoding="utf-8")
        self.brief_f = self.runs_d / "brief-bug-test-reviewer-agent.md"
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
            sha256_file(self.pkg_f), ["bug-test-reviewer-agent"]
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
            ["dispatch", "--repo", str(self.repo), "--task", "task-v2", "--reviewer", "bug-test-reviewer-agent", "--host", "antigravity"],
        ):
            self.assertEqual(1, orchestrator_main(argv), argv)
        status = get_review_execution_status(self.repo, "task-v2")
        self.assertEqual("NOT_DISPATCHED", status["reviewers"]["bug-test-reviewer-agent"]["state"])
        # The real launch path stays open.
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": self.brief_f.read_text(encoding="utf-8")}])
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
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEW_PROFILE_BLOCKED", res.get("reason_code"))

    def test_V2_BOUNDARY_PROFILE_002_empty_profile_denies_dispatch(self):
        self.policy_f.write_text(json.dumps({"reviewers": [], "max_review_rounds": 3, "model_call_budget": 20}), encoding="utf-8")
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertIn(res.get("reason_code"), ("REVIEW_PROFILE_BLOCKED", "REVIEWER_ROSTER_EMPTY", "REVIEWER_ROSTER_EXTRA"))

    def test_V2_BOUNDARY_PROFILE_003_reviewer_missing_from_profile_denies(self):
        self.policy_f.write_text(json.dumps({"reviewers": ["bug-test-reviewer-agent", "security-perf-reviewer-agent"], "max_review_rounds": 3, "model_call_budget": 20}), encoding="utf-8")
        res = self._call_hook([
            {"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"},
            {"Role": "security-perf-reviewer-agent", "TypeName": "security-perf-reviewer-agent", "Prompt": "Security brief"},
        ])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEW_PROFILE_BLOCKED", res.get("reason_code"))

    def test_V2_BOUNDARY_PROFILE_004_missing_brief_denies_before_receipt(self):
        self.brief_f.unlink()
        receipt_p = self.task_d / "review-execution/r1/dispatch/bug-test-reviewer-agent.json"
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEW_PROFILE_BLOCKED", res.get("reason_code"))
        self.assertFalse(receipt_p.is_file())

    def test_V2_BOUNDARY_PROFILE_005_no_ledger_state_change_on_profile_denial(self):
        from review_orchestrator import load_ledger
        self.brief_f.unlink()
        l_before = load_ledger(self.task_d, "r1")
        self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        l_after = load_ledger(self.task_d, "r1")
        self.assertEqual(l_before, l_after)

    def test_V2_IDENTITY_001_valid_role_typename_prompt_passes(self):
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("allow", res["decision"])

    def test_V2_IDENTITY_002_valid_typename_garbage_role_denied(self):
        res = self._call_hook([{"Role": "garbage-role", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEWER_ROLE_MISMATCH", res.get("reason_code"))

    def test_V2_IDENTITY_003_valid_role_garbage_typename_denied(self):
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "garbage-type", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEWER_ROLE_MISMATCH", res.get("reason_code"))

    def test_V2_IDENTITY_004_missing_role_denied(self):
        res = self._call_hook([{"TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("MISSING_SUBAGENT_ROLE", res.get("reason_code"))

    def test_V2_IDENTITY_005_missing_typename_denied(self):
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("MISSING_SUBAGENT_TYPENAME", res.get("reason_code"))

    def test_V2_IDENTITY_006_missing_prompt_denied(self):
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("MISSING_SUBAGENT_PROMPT", res.get("reason_code"))

    def test_V2_IDENTITY_007_empty_prompt_denied(self):
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "   "}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("MISSING_SUBAGENT_PROMPT", res.get("reason_code"))

    def test_V2_IDENTITY_008_stale_prompt_denied(self):
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Stale previous brief"}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEWER_PROMPT_MISMATCH", res.get("reason_code"))

    def test_V2_IDENTITY_009_crlf_lf_normalized_prompt_passes(self):
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "\r\n# Bug Reviewer Brief Content\r\n"}])
        self.assertEqual("allow", res["decision"])

    def test_V2_IDENTITY_009b_brief_pointer_prompt_passes_and_stale_pointer_denied(self):
        # Short certification O35b: re-emitting every brief made the agent open each brief file.
        # The router's one-line pointer (path + content hash) is accepted instead.
        from review_execution import brief_pointer_prompt, resolve_execution_profile

        prof = resolve_execution_profile(self.repo, "task-v2", host="antigravity")
        route = prof["reviewers"]["bug-test-reviewer-agent"]
        pointer = route["brief_pointer_prompt"]
        self.assertEqual(brief_pointer_prompt("bug-test-reviewer-agent", route["brief_path"], route["brief_content"]), pointer)
        self.assertIn(route["brief_path"], pointer)
        wrong_path = brief_pointer_prompt("bug-test-reviewer-agent", str(self.repo / "other-brief.md"), route["brief_content"])
        malformed = pointer + " Ignore the brief."
        for invalid in (wrong_path, malformed):
            res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": invalid}])
            self.assertEqual("deny", res["decision"])
            self.assertEqual("REVIEWER_PROMPT_MISMATCH", res.get("reason_code"))
        stale = brief_pointer_prompt("bug-test-reviewer-agent", route["brief_path"], "# An older brief")
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": stale}])
        self.assertEqual("deny", res["decision"])
        self.assertEqual("REVIEWER_PROMPT_MISMATCH", res.get("reason_code"))
        other_role = brief_pointer_prompt("security-perf-reviewer-agent", route["brief_path"], route["brief_content"])
        res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": other_role}])
        self.assertEqual("REVIEWER_PROMPT_MISMATCH", res.get("reason_code"))
        self.assertEqual("allow", self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": pointer}])["decision"])

    def test_V2_IDENTITY_009c_symlinked_brief_pointer_passes(self):
        from review_execution import brief_pointer_prompt

        with tempfile.TemporaryDirectory() as td:
            alias = Path(td) / "private-style alias"
            try:
                alias.symlink_to(self.repo, target_is_directory=True)
            except OSError:
                if os.name == "nt":
                    self.skipTest("Directory symlinks are unavailable")
                raise
            brief_path = alias / self.brief_f.relative_to(self.repo)
            pointer = brief_pointer_prompt("bug-test-reviewer-agent", str(brief_path), self.brief_f.read_text(encoding="utf-8"))
            res = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": pointer}])
            self.assertEqual("allow", res["decision"], res.get("reason"))

    def test_V2_IDENTITY_010_model_or_Model_denied(self):
        res1 = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content", "model": "inherit"}])
        self.assertEqual("deny", res1["decision"])
        self.assertEqual("REVIEWER_MODEL_OVERRIDE_FORBIDDEN", res1.get("reason_code"))
        res2 = self._call_hook([{"Role": "bug-test-reviewer-agent", "TypeName": "bug-test-reviewer-agent", "Prompt": "# Bug Reviewer Brief Content", "Model": None}])
        self.assertEqual("deny", res2["decision"])
        self.assertEqual("REVIEWER_MODEL_OVERRIDE_FORBIDDEN", res2.get("reason_code"))

    def test_V2_MODEL_OMISSION_001_antigravity_profile_contract(self):
        from review_execution import resolve_execution_profile
        prof = resolve_execution_profile(self.repo, "task-v2", host="antigravity")
        self.assertEqual("INHERIT_PARENT_BY_OMISSION", prof["model_policy"])
        self.assertIsNone(prof["dispatch_contract"]["model_argument"])
        self.assertNotIn("model", prof)
        rev = prof["reviewers"]["bug-test-reviewer-agent"]
        self.assertNotIn("required_model", rev)
        self.assertNotIn("preferred_model", rev)
        self.assertNotIn("fallback_model", rev)

    def test_V2_TOP_LEVEL_SUBAGENT_001_parallel_single_reviewer_dispatches_pass(self):
        """Antigravity's top-level invoke_subagent schema (without Subagents array) dispatches multi-reviewer rosters one by one."""
        from review_orchestrator import get_review_execution_status, init_ledger, ledger_file, sha256_file
        reviewers = ["bug-test-reviewer-agent", "arch-regression-reviewer-agent", "security-perf-reviewer-agent"]
        self.policy_f.write_text(json.dumps({
            "reviewers": reviewers,
            "max_review_rounds": 3,
            "model_call_budget": 20,
        }), encoding="utf-8")
        for r in reviewers:
            (self.runs_d / f"brief-{r}.md").write_text(f"# Brief for {r}\n", encoding="utf-8")
        ledger_file(self.task_d, "r1").unlink(missing_ok=True)
        init_ledger(
            self.task_d, "task-v2", "r1", self.snapshot, self.change_set,
            sha256_file(self.pkg_f), reviewers,
        )
        for r in reviewers:
            payload = {
                "toolCall": {
                    "name": "invoke_subagent",
                    "args": {
                        "Role": r,
                        "TypeName": r,
                        "Prompt": f"# Brief for {r}\n",
                        "Workspace": "inherit",
                    },
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
            res = _with_audit_reason(json.loads(proc.stdout), self.env, SCRIPTS / "pre_tool_safety.py")
            self.assertEqual("allow", res["decision"], (r, res))
        st = get_review_execution_status(self.repo, "task-v2")
        for r in reviewers:
            self.assertEqual("DISPATCHED", st["reviewers"][r]["state"], r)


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
            expected_surfaces='LOCALIZATION', expected_modules=':app'))
        approval = argparse.Namespace(repo=str(repo), task_id='resource-scope', source='conversation',
                                      proof_reference='approved', enforcement_tier='RULE_ENFORCED',
                                      plan_hash=plan['plan_sha256'][:12])
        workflow.record_approval(approval)
        self.assertTrue(file_mutation_allowed(repo, targets=[approved])[0])
        self.assertTrue(file_mutation_allowed(repo, targets=[added])[0])
        allowed_other, reason_other, code_other = file_mutation_allowed(repo, targets=[other])
        self.assertFalse(allowed_other, reason_other)
        self.assertEqual('SCOPE_EXPANSION_REQUIRES_REVISED_APPROVAL', code_other)
        write_file(repo / added, '<resources><string name="new_label">New</string></resources>\n')
        prep1 = workflow.prepare_verification(repo, 'resource-scope')
        self.assertTrue(prep1['run_id'])
        parser = workflow.build_parser()
        revision = workflow.revise(parser.parse_args(['revise', '--repo', str(repo), '--task-id',
            'resource-scope', '--expected-modules', ':app,:core', '--expected-files', ','.join([approved, added, other])]))
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
        from _vnext_common import read_json
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
        self.assertTrue(file_mutation_allowed(repo, targets=[source, target])[0])
        (repo / source).rename(repo / target)
        prep = workflow.prepare_verification(repo, 'rename-scope')
        self.assertTrue(prep['run_id'])
        updated_plan = read_json(workflow.task_dir(repo, 'rename-scope') / 'plan.json')
        self.assertIn(source, updated_plan['expected_files'])
        self.assertIn(target, updated_plan['expected_files'])

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
                with mock.patch.object(workflow, 'check_material_drift', return_value=[]):
                    workflow.prepare_verification(repo, 'frozen-scope')
                result = verify_task(repo, 'frozen-scope')
                self.assertEqual('BLOCKED', result['status'], result)


class TestReviewerBriefCLI(unittest.TestCase):
    def test_O20_text_cli_exposes_dispatch_inputs_once_and_preserves_json(self):
        import contextlib
        import io
        from unittest import mock
        import workflow
        role = 'bug-test-reviewer-agent'
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

    def test_O47_step_heartbeat_names_the_step_and_yields_to_streaming(self):
        # Short certification O47/O54: a 85 s Room gate printed 16 bare "still running" lines, and a
        # Gradle run inside a step printed two heartbeats in two formats.
        import time as real_time
        from unittest import mock
        import _live_process as live

        self.assertGreaterEqual(live.STEP_HEARTBEAT_SEC, 30)
        with mock.patch.object(live, 'live_print') as output:
            with live.step_progress("Room Database Migrations", heartbeat_sec=1):
                real_time.sleep(2.3)
        beats = [c.args[0] for c in output.call_args_list if 'still running' in c.args[0]]
        self.assertTrue(beats)
        self.assertTrue(all("Room Database Migrations: still running" in b for b in beats), beats)
        live._streaming_active[0] += 1
        try:
            with mock.patch.object(live, 'live_print') as output:
                with live.step_progress("Gradle step", heartbeat_sec=1):
                    real_time.sleep(2.3)
            self.assertFalse([c for c in output.call_args_list if 'still running' in c.args[0]])
        finally:
            live._streaming_active[0] -= 1

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

class Option4HybridDelegationSelftest(unittest.TestCase):
    """End-to-end verification of Option 4 Risk-Gated Hybrid Delegation & Quota Safety."""

    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        self.repo = Path(self.td.name).resolve() / "app_repo"
        self.repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=str(self.repo), check=True)
        subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=str(self.repo), check=True)
        subprocess.run(["git", "config", "user.name", "Dev"], cwd=str(self.repo), check=True)
        (self.repo / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        (self.repo / "settings.gradle.kts").write_text('rootProject.name = "demo"\ninclude(":app")\n', encoding="utf-8")
        (self.repo / "app/src/main/kotlin/com/example").mkdir(parents=True)
        (self.repo / "app/src/test/kotlin/com/example").mkdir(parents=True)
        (self.repo / "app/build.gradle.kts").write_text('plugins { kotlin("jvm") }\n', encoding="utf-8")
        (self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt").write_text(
            "package com.example\nclass HomeViewModel\n", encoding="utf-8"
        )
        (self.repo / "app/src/main/kotlin/com/example/HomeUiState.kt").write_text(
            "package com.example\ndata class HomeUiState(val loading: Boolean = false)\n", encoding="utf-8"
        )
        (self.repo / "app/src/main/kotlin/com/example/AuthManager.kt").write_text(
            "package com.example\nclass AuthManager\n", encoding="utf-8"
        )
        (self.repo / "app/src/test/kotlin/com/example/HomeViewModelTest.kt").write_text(
            "package com.example\nclass HomeViewModelTest\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=str(self.repo), check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=str(self.repo), check=True)

        # Install core .agents layout for hook subprocess tests
        kit_root = Path(__file__).resolve().parents[2]
        self.agents_dir = self.repo / ".agents"
        shutil.copytree(kit_root / "agents/scripts", self.agents_dir / "scripts")
        shutil.copytree(kit_root / "agents/harness_shared", self.agents_dir / "harness_shared")
        shutil.copytree(kit_root / "agents/subagents", self.agents_dir / "subagents")
        shutil.copytree(kit_root / "agents/rules", self.agents_dir / "rules")
        shutil.copyfile(kit_root / "agents/harness.py", self.agents_dir / "harness.py")
        shutil.copyfile(kit_root / "agents/VERSION", self.agents_dir / "VERSION")
        self.ag_runtime = Path(self.td.name).resolve() / "_ag_runtime"
        (self.ag_runtime / "brain").mkdir(parents=True)

    def tearDown(self) -> None:
        self.td.cleanup()

    def _run_pre_hook(self, payload: dict, extra_env: dict | None = None) -> dict:
        wire = dict(payload)
        if "tool" in wire and "toolCall" not in wire:
            wire["toolCall"] = {"name": wire.pop("tool"), "args": wire.pop("arguments", {})}
        hook_state = self.agents_dir / "state" / "hook-state.json"
        env = {
            **os.environ,
            "HARNESS_REPO": str(self.repo),
            "HARNESS_HOOK_STATE": str(hook_state),
            "ANTIGRAVITY_APP_DATA": str(self.ag_runtime),
        }
        if extra_env:
            env.update(extra_env)
        engine = self.agents_dir / "scripts" / "pre_tool_safety.py"
        proc = subprocess.run(
            [sys.executable, str(engine)],
            input=json.dumps(wire),
            cwd=str(self.repo),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return _with_audit_reason(json.loads(proc.stdout), env, engine)

    def _write_child_transcript(self, conv_id: str, parent_id: str, prompt: str) -> Path:
        tx = self.ag_runtime / "brain" / conv_id / ".system_generated/logs/transcript.jsonl"
        tx.parent.mkdir(parents=True, exist_ok=True)
        sys_msg = {
            "source": "SYSTEM_SDK",
            "type": "SYSTEM_MESSAGE",
            "content": f"<SYSTEM_MESSAGE>\nsender={parent_id} priority=MESSAGE_PRIORITY_HIGH content={prompt}\n</SYSTEM_MESSAGE>",
        }
        tx.write_text(json.dumps(sys_msg) + "\n", encoding="utf-8")
        return tx

    def test_utility_agents_generated_validated_by_doctor_and_preserved_across_lifecycle(self) -> None:
        from install_tool_adapters import generate_antigravity_agents
        from lifecycle import _antigravity_agent_matches_policy
        from doctor.engine import HarnessDoctor

        generate_antigravity_agents(self.repo, dry_run=False)
        for role in ("harness-scout-agent", "harness-worker-agent"):
            rel = f".agents/agents/{role}/agent.md"
            p = self.repo / rel
            self.assertTrue(p.is_file(), f"Missing {rel}")
            txt = p.read_text(encoding="utf-8")
            self.assertIn('model: "gemini-3.8-flash-medium"', txt)
            self.assertIn("subagent: true", txt)
            self.assertIn("mainAgent: false", txt)
            self.assertTrue(_antigravity_agent_matches_policy(self.repo, rel))

        scout_md = (self.repo / ".agents/agents/harness-scout-agent/agent.md").read_text(encoding="utf-8")
        scout_fm = scout_md.split("---")[1]
        self.assertNotIn("write_to_file", scout_fm)
        worker_md = (self.repo / ".agents/agents/harness-worker-agent/agent.md").read_text(encoding="utf-8")
        worker_fm = worker_md.split("---")[1]
        self.assertIn("write_to_file", worker_fm)
        self.assertNotIn("ask_question", worker_fm)
        self.assertNotIn("invoke_subagent", worker_fm)

        doc = HarnessDoctor(self.repo, run_selftest=False)
        doc.check_antigravity_installation()
        rev_check = next(r for r in doc.results if r.name == "Custom Reviewer Agents")
        self.assertEqual("PASS", rev_check.status, rev_check.message)

    def test_scout_preplan_dispatch_readonly_enforcement_and_bridge_protection(self) -> None:
        from task_bridge import record_active_conversation_turn, _active_conversation_file
        import pre_invocation_reminder, io, contextlib
        from unittest import mock

        # Parent lead conversation records turns
        record_active_conversation_turn(self.repo, "parent-carbon-1")
        record_active_conversation_turn(self.repo, "parent-carbon-1")
        self.assertEqual(2, json.loads(_active_conversation_file(self.repo).read_text())["hook_calls"])

        # 1. Blocking Model='pro' quota leak on Scout
        bad_pro = self._run_pre_hook({
            "conversationId": "parent-carbon-1",
            "tool": "invoke_subagent",
            "arguments": {"Subagents": [{"TypeName": "harness-scout-agent", "Role": "scout", "Model": "pro", "Prompt": "Inspect HomeViewModel and graph"}]},
        })
        self.assertEqual("deny", bad_pro["decision"], bad_pro)
        self.assertEqual("UTILITY_MODEL_QUOTA_GUARD", bad_pro.get("reason_code"))

        # 2. Valid Scout dispatch before any task plan exists (top-level Antigravity invoke_subagent shape)
        scout_prompt = "Run graph --feature home and summarize HomeViewModel signatures."
        ok_scout = self._run_pre_hook({
            "conversationId": "parent-carbon-1",
            "tool": "invoke_subagent",
            "arguments": {"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Workspace": "inherit", "Prompt": scout_prompt},
        })
        self.assertEqual("allow", ok_scout["decision"], ok_scout)
        self.assertEqual("UTILITY_SUBAGENT_ALLOWED", ok_scout.get("reason_code"))

        # Bind child transcript via PostToolUse + verify Scout read-only boundary & parent bridge protection
        child_tx = self._write_child_transcript("scout-child-1", "parent-carbon-1", scout_prompt)
        post_proc = subprocess.run(
            [sys.executable, str(self.agents_dir / "scripts/post_tool_reconcile.py")],
            input=json.dumps({
                "conversationId": "parent-carbon-1",
                "transcriptPath": str(self.ag_runtime / "brain/parent-carbon-1/.system_generated/logs/transcript.jsonl"),
                "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "harness-scout-agent"}},
            }),
            cwd=str(self.repo),
            env={**os.environ, "HARNESS_REPO": str(self.repo), "ANTIGRAVITY_APP_DATA": str(self.ag_runtime)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, post_proc.returncode, post_proc.stderr)
        self.assertTrue(child_tx.is_file())

        allow_graph = self._run_pre_hook({
            "conversationId": "scout-child-1",
            "tool": "run_command",
            "arguments": {"CommandLine": "python .agents/harness.py graph --stats --json", "Cwd": str(self.repo)},
        })
        self.assertEqual("allow", allow_graph["decision"], allow_graph)

        deny_write = self._run_pre_hook({
            "conversationId": "scout-child-1",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt"), "CodeContent": "broken"},
        })
        self.assertEqual("deny", deny_write["decision"], deny_write)
        self.assertEqual("SCOUT_READ_ONLY_BOUNDARY", deny_write.get("reason_code"))

        deny_gradle = self._run_pre_hook({
            "conversationId": "scout-child-1",
            "tool": "run_command",
            "arguments": {"CommandLine": "python .agents/harness.py compile", "Cwd": str(self.repo)},
        })
        self.assertEqual("deny", deny_gradle["decision"], deny_gradle)
        self.assertEqual("SCOUT_READ_ONLY_BOUNDARY", deny_gradle.get("reason_code"))

        # Parent active-conversation.json must STILL belong to parent-carbon-1 (untouched by scout-child-1)
        conv_state = json.loads(_active_conversation_file(self.repo).read_text())
        self.assertEqual("parent-carbon-1", conv_state["conversation_id"])

        # PreInvocation hook must emit {} for scout-child-1
        buf = io.StringIO()
        with mock.patch.object(pre_invocation_reminder, "REPO", self.repo),              mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(self.ag_runtime)}),              mock.patch("sys.stdin", io.StringIO(json.dumps({"invocationNum": 0, "conversationId": "scout-child-1"}))),              contextlib.redirect_stdout(buf):
            pre_invocation_reminder.main()
        self.assertEqual({}, json.loads(buf.getvalue()))

    def test_worker_across_all_task_kinds_tdd_red_sensitive_conflict_and_phases(self) -> None:
        import workflow
        from delegation_policy import evaluate_delegation_policy

        wf_parser = workflow.build_parser()

        def _draft_and_begin(argv: list[str], tid: str) -> dict:
            plan = workflow.draft(wf_parser.parse_args(["draft", "--repo", str(self.repo), "--task-id", tid, "--force", *argv]))
            workflow.record_approval(wf_parser.parse_args([
                "approve", "--repo", str(self.repo), "--task-id", tid,
                "--source", "conversation", "--proof-reference", "approved",
                "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", plan["plan_sha256"][:12],
            ]))
            return plan

        def _cancel(tid: str) -> None:
            # Clean any uncommitted test edits before canceling
            subprocess.run(["git", "checkout", "--", "."], cwd=str(self.repo), check=False)
            workflow.cancel(wf_parser.parse_args([
                "cancel", "--repo", str(self.repo), "--task-id", tid,
                "--source", "conversation", "--proof-reference", "cancel test",
            ]))

        # --- Case A: T0_TRIVIAL single-file recommends inline lead ---
        _draft_and_begin([
            "--outcome", "Update single comment",
            "--kind", "REFACTOR",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "DOCS",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeUiState.kt",
        ], "t-trivial")
        pol_t0 = evaluate_delegation_policy(self.repo)
        self.assertIn(pol_t0["strategy"], ("TRIVIAL_INLINE_LEAD", "DELEGATE_WORKER_SLICE"))
        _cancel("t-trivial")

        # --- Case B: Standard Multi-file FEATURE -> DELEGATE_WORKER_SLICE + Guards + CLI ---
        _draft_and_begin([
            "--outcome", "Add home state & test",
            "--kind", "FEATURE",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-feat")
        pol_feat = evaluate_delegation_policy(self.repo)
        self.assertEqual("DELEGATE_WORKER_SLICE", pol_feat["strategy"])
        self.assertEqual("FULL_SLICE", pol_feat["worker_mode"])

        # Public CLI `harness.py delegate-plan --json` works cleanly
        cli_proc = subprocess.run(
            [sys.executable, str(self.agents_dir / "harness.py"), "delegate-plan", "--json"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, cli_proc.returncode, cli_proc.stderr)
        cli_json = json.loads(cli_proc.stdout)
        self.assertEqual("DELEGATE_WORKER_SLICE", cli_json["strategy"])
        self.assertEqual("Gemini 4 Carbon (Medium)", cli_json["quota_strategy"]["primary_chat_model"])

        # Router attaches delegation_advisory on Antigravity
        act_ag = workflow.resolve_next_action(self.repo, "t-feat", host="antigravity")
        self.assertIn("delegation_advisory", act_ag)
        self.assertEqual("DELEGATE_WORKER_SLICE", act_ag["delegation_advisory"]["strategy"])

        # Parallel workers MUST be denied (prevents StateLock + edit collisions)
        brief = "Update HomeViewModel.kt to expose StateFlow<HomeUiState>, add unit test in HomeViewModelTest.kt, and run python .agents/harness.py test."
        par_deny = self._run_pre_hook({
            "conversationId": "parent-carbon-2",
            "tool": "invoke_subagent",
            "arguments": {"Subagents": [
                {"TypeName": "harness-worker-agent", "Role": "w1", "Prompt": brief},
                {"TypeName": "harness-worker-agent", "Role": "w2", "Prompt": brief},
            ]},
        })
        self.assertEqual("deny", par_deny["decision"], par_deny)
        self.assertEqual("PARALLEL_WORKER_FORBIDDEN", par_deny.get("reason_code"))

        # Worktree workspace override MUST be denied on Worker
        ws_deny = self._run_pre_hook({
            "conversationId": "parent-carbon-2",
            "tool": "invoke_subagent",
            "arguments": {"Subagents": [{"TypeName": "harness-worker-agent", "Role": "w1", "Workspace": "worktree", "Prompt": brief}]},
        })
        self.assertEqual("deny", ws_deny["decision"], ws_deny)
        self.assertEqual("WORKER_WORKSPACE_MISMATCH", ws_deny.get("reason_code"))

        # Short lazy brief MUST be denied
        short_deny = self._run_pre_hook({
            "conversationId": "parent-carbon-2",
            "tool": "invoke_subagent",
            "arguments": {"Subagents": [{"TypeName": "harness-worker-agent", "Role": "w1", "Prompt": "do it"}]},
        })
        self.assertEqual("deny", short_deny["decision"], short_deny)
        self.assertEqual("INCOMPLETE_WORKER_BRIEF", short_deny.get("reason_code"))

        # Valid single worker dispatch succeeds
        ok_worker = self._run_pre_hook({
            "conversationId": "parent-carbon-2",
            "tool": "invoke_subagent",
            "arguments": {"TypeName": "harness-worker-agent", "Role": "harness-worker-agent", "Workspace": "inherit", "Prompt": brief},
        })
        self.assertEqual("allow", ok_worker["decision"], ok_worker)

        self._write_child_transcript("worker-child-1", "parent-carbon-2", brief)

        # Worker CAN edit in-scope HomeViewModel.kt, CANNOT edit out-of-scope AuthManager.kt, CANNOT call ask_question or task prepare-verification
        w_in_scope = self._run_pre_hook({
            "conversationId": "worker-child-1",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt"), "CodeContent": "package com.example\nclass HomeViewModel { val ok = true }\n"},
        })
        self.assertEqual("allow", w_in_scope["decision"], w_in_scope)

        w_out_scope = self._run_pre_hook({
            "conversationId": "worker-child-1",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/main/kotlin/com/example/AuthManager.kt"), "CodeContent": "hack"},
        })
        self.assertEqual("deny", w_out_scope["decision"], w_out_scope)
        self.assertEqual("WORKER_OUTSIDE_PLANNED_FILES", w_out_scope.get("reason_code"))

        w_ask = self._run_pre_hook({
            "conversationId": "worker-child-1",
            "tool": "ask_question",
            "arguments": {"question": "approve me?"},
        })
        self.assertEqual("deny", w_ask["decision"], w_ask)
        self.assertEqual("WORKER_NO_DELEGATION_OR_APPROVAL", w_ask.get("reason_code"))

        w_lifecycle = self._run_pre_hook({
            "conversationId": "worker-child-1",
            "tool": "run_command",
            "arguments": {"CommandLine": "python .agents/harness.py task prepare-verification --task-id t-feat --host antigravity"},
        })
        self.assertEqual("deny", w_lifecycle["decision"], w_lifecycle)
        self.assertEqual("WORKER_LIFECYCLE_COMMAND_FORBIDDEN", w_lifecycle.get("reason_code"))
        _cancel("t-feat")

        # --- Case C: Sensitive AUTH / SECURITY task -> SENSITIVE_LEAD_CORE_WORKER_TESTS ---
        _draft_and_begin([
            "--outcome", "Harden token auth",
            "--kind", "FEATURE",
            "--planning-depth", "ARCHITECTURAL",
            "--approach", "Rotate refresh tokens atomically",
            "--risks", "Token race on concurrent refresh",
            "--test-strategy", "Unit test AuthManager refresh race",
            "--expected-surfaces", "AUTH,SECURITY",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/AuthManager.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-auth")
        pol_auth = evaluate_delegation_policy(self.repo)
        self.assertEqual("SENSITIVE_LEAD_CORE_WORKER_TESTS", pol_auth["strategy"])
        self.assertEqual("TESTS_AND_GATES_ONLY", pol_auth["worker_mode"])

        auth_brief = "Write unit tests in app/src/test/kotlin/com/example/HomeViewModelTest.kt covering AuthManager token expiry and run harness test."
        self.assertEqual("allow", self._run_pre_hook({
            "conversationId": "parent-carbon-3",
            "tool": "invoke_subagent",
            "arguments": {"Subagents": [{"TypeName": "harness-worker-agent", "Role": "harness-worker-agent", "Prompt": auth_brief}]},
        })["decision"])
        self._write_child_transcript("worker-auth-1", "parent-carbon-3", auth_brief)

        # Worker is BLOCKED from touching sensitive AuthManager.kt even though AuthManager.kt IS in plan.json!
        deny_sens_prod = self._run_pre_hook({
            "conversationId": "worker-auth-1",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/main/kotlin/com/example/AuthManager.kt"), "CodeContent": "package com.example\nclass AuthManager\n"},
        })
        self.assertEqual("deny", deny_sens_prod["decision"], deny_sens_prod)
        self.assertEqual("WORKER_SENSITIVE_CORE_PROTECTED", deny_sens_prod.get("reason_code"))

        # Worker IS allowed to edit the unit test file!
        allow_sens_test = self._run_pre_hook({
            "conversationId": "worker-auth-1",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/test/kotlin/com/example/HomeViewModelTest.kt"), "CodeContent": "package com.example\nclass HomeViewModelTest { }\n"},
        })
        self.assertEqual("allow", allow_sens_test["decision"], allow_sens_test)

        # Meanwhile Lead Architect (parent-carbon-3) CAN edit sensitive AuthManager.kt directly!
        allow_lead_prod = self._run_pre_hook({
            "conversationId": "parent-carbon-3",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/main/kotlin/com/example/AuthManager.kt"), "CodeContent": "package com.example\nclass AuthManager { fun verify() = true }\n"},
        })
        self.assertEqual("allow", allow_lead_prod["decision"], allow_lead_prod)
        _cancel("t-auth")

        # --- Case D: BUG task before red-evidence -> CAPTURE_RED_ONLY ---
        _draft_and_begin([
            "--outcome", "Fix crash in HomeViewModel",
            "--kind", "BUG",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-bug")
        pol_bug = evaluate_delegation_policy(self.repo)
        self.assertEqual("DELEGATE_RED_REPRODUCTION_TO_WORKER", pol_bug["strategy"])
        self.assertEqual("CAPTURE_RED_ONLY", pol_bug["worker_mode"])

        bug_brief = "Add failing reproduction test in app/src/test/kotlin/com/example/HomeViewModelTest.kt and run python .agents/harness.py test --capture-red."
        self.assertEqual("allow", self._run_pre_hook({
            "conversationId": "parent-carbon-4",
            "tool": "invoke_subagent",
            "arguments": {"TypeName": "harness-worker-agent", "Role": "harness-worker-agent", "Prompt": bug_brief},
        })["decision"])
        self._write_child_transcript("worker-bug-1", "parent-carbon-4", bug_brief)

        deny_bug_prod = self._run_pre_hook({
            "conversationId": "worker-bug-1",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt"), "CodeContent": "package com.example\nclass HomeViewModel\n"},
        })
        self.assertEqual("deny", deny_bug_prod["decision"], deny_bug_prod)
        self.assertIn(deny_bug_prod.get("reason_code"), ("WORKER_CAPTURE_RED_ONLY", "RED_EVIDENCE_REQUIRED"))

        allow_bug_test = self._run_pre_hook({
            "conversationId": "worker-bug-1",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/test/kotlin/com/example/HomeViewModelTest.kt"), "CodeContent": "package com.example\nclass HomeViewModelTest\n"},
        })
        self.assertEqual("allow", allow_bug_test["decision"], allow_bug_test)
        _cancel("t-bug")

        # --- Case E: CONFLICT task -> CONFLICT_LEAD_CORE_WORKER_VERIFY ---
        _draft_and_begin([
            "--outcome", "Resolve merge conflict in HomeViewModel",
            "--kind", "CONFLICT",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-conflict")
        pol_conf = evaluate_delegation_policy(self.repo)
        self.assertEqual("CONFLICT_LEAD_CORE_WORKER_VERIFY", pol_conf["strategy"])
        self.assertEqual("TESTS_AND_GATES_ONLY", pol_conf["worker_mode"])
        _cancel("t-conflict")

        # --- Case F: Multi-phase task -> phase-scoped delegation advisory ---
        phases_spec = json.dumps([
            {"id": "p1-state", "title": "State model", "expected_modules": [":app"], "expected_files": ["app/src/main/kotlin/com/example/HomeUiState.kt", "app/src/main/kotlin/com/example/HomeViewModel.kt"]},
            {"id": "p2-tests", "title": "Unit tests", "expected_modules": [":app"], "expected_files": ["app/src/test/kotlin/com/example/HomeViewModelTest.kt"]},
        ])
        _draft_and_begin([
            "--outcome", "Phased home refactor",
            "--kind", "REFACTOR",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeUiState.kt,app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
            "--phases", phases_spec,
        ], "t-phased")
        pol_phased = evaluate_delegation_policy(self.repo)
        self.assertEqual("p1-state", pol_phased["phase_id"])
        self.assertEqual(
            ["app/src/main/kotlin/com/example/HomeUiState.kt", "app/src/main/kotlin/com/example/HomeViewModel.kt"],
            pol_phased["target_files"],
        )
        act_phased = workflow.resolve_next_action(self.repo, "t-phased", host="antigravity")
        self.assertIn("delegation_advisory", act_phased)
        self.assertEqual("DELEGATE_WORKER_SLICE", act_phased["delegation_advisory"]["strategy"])
        _cancel("t-phased")



class SixEngineOptimizationsSelftest(unittest.TestCase):
    """End-to-end verification of the 6 speed, host-fidelity, and batch-completion optimizations."""

    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        self.repo = Path(self.td.name).resolve() / "opt_repo"
        self.repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=str(self.repo), check=True)
        subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=str(self.repo), check=True)
        subprocess.run(["git", "config", "user.name", "Dev"], cwd=str(self.repo), check=True)
        (self.repo / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        (self.repo / "settings.gradle.kts").write_text('rootProject.name = "opt"\ninclude(":app")\n', encoding="utf-8")
        (self.repo / "app/src/main/kotlin/com/example").mkdir(parents=True)
        (self.repo / "app/src/test/kotlin/com/example").mkdir(parents=True)
        (self.repo / "app/build.gradle.kts").write_text('plugins { kotlin("jvm") }\n', encoding="utf-8")
        (self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt").write_text(
            "package com.example\nclass HomeViewModel\n", encoding="utf-8"
        )
        (self.repo / "app/src/main/kotlin/com/example/HomeUiState.kt").write_text(
            "package com.example\ndata class HomeUiState(val v: Int = 0)\n", encoding="utf-8"
        )
        (self.repo / "app/src/test/kotlin/com/example/HomeViewModelTest.kt").write_text(
            "package com.example\nclass HomeViewModelTest\n", encoding="utf-8"
        )
        (self.repo / "README.md").write_text("# Demo\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.repo), check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=str(self.repo), check=True)

        kit_root = Path(__file__).resolve().parents[2]
        self.agents_dir = self.repo / ".agents"
        shutil.copytree(kit_root / "agents/scripts", self.agents_dir / "scripts")
        shutil.copytree(kit_root / "agents/harness_shared", self.agents_dir / "harness_shared")
        shutil.copytree(kit_root / "agents/subagents", self.agents_dir / "subagents")
        shutil.copytree(kit_root / "agents/rules", self.agents_dir / "rules")
        shutil.copyfile(kit_root / "agents/harness.py", self.agents_dir / "harness.py")
        shutil.copyfile(kit_root / "agents/VERSION", self.agents_dir / "VERSION")
        self.ag_runtime = Path(self.td.name).resolve() / "_ag_runtime"
        (self.ag_runtime / "brain").mkdir(parents=True)

    def tearDown(self) -> None:
        self.td.cleanup()

    def test_opt1_opt2_opt3_no_double_router_fast_mutation_and_ephemeral_facts_cache(self) -> None:
        from unittest import mock
        import workflow
        import change_classifier
        import project_context
        from mutation_guard import file_mutation_allowed

        wf_parser = workflow.build_parser()
        # OPT 3: First draft populates `.agents/cache/ephemeral-project-facts.json` without touching `.agents/project-context/project-facts.json`
        plan1 = workflow.draft(wf_parser.parse_args([
            "draft", "--repo", str(self.repo), "--task-id", "t-opt", "--force",
            "--outcome", "Add HomeViewModel state", "--kind", "FEATURE",
            "--expected-surfaces", "BUSINESS_LOGIC", "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/main/kotlin/com/example/HomeUiState.kt",
        ]))
        import architecture_resolver
        self.assertIn(str(self.repo.resolve()), architecture_resolver._LIVE_FACTS_MEM_CACHE)
        self.assertFalse((self.repo / ".agents/project-context/project-facts.json").is_file())

        # Second revise on unchanged sources MUST hit in-memory cache without calling extract_project_facts!
        with mock.patch.object(project_context, "extract_project_facts", side_effect=AssertionError("should hit in-memory facts cache")):
            plan2 = workflow.revise(wf_parser.parse_args([
                "revise", "--repo", str(self.repo), "--task-id", "t-opt",
                "--outcome", "Add HomeViewModel state refined",
                "--material-change-reason", "clarify outcome",
            ]))

        workflow.record_approval(wf_parser.parse_args([
            "approve", "--repo", str(self.repo), "--task-id", "t-opt",
            "--source", "conversation", "--proof-reference", "approved",
            "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", plan2["plan_sha256"][:12],
        ]))

        # OPT 1: resolve_next_action(host="antigravity") builds task manifest ONLY ONCE (no recursive re-entry!)
        import _workflow.engine as _wf_engine
        with mock.patch.object(_wf_engine, "build_task_manifest", wraps=_wf_engine.build_task_manifest) as spy_manifest:
            act = workflow.resolve_next_action(self.repo, "t-opt", host="antigravity")
            self.assertEqual("IMPLEMENT_APPROVED_SCOPE", act["code"])
            self.assertIn("delegation_advisory", act)
            self.assertEqual(1, spy_manifest.call_count)

        # OPT 2: file_mutation_allowed on BUSINESS_LOGIC task skips full-repo _build_type_file_index walk!
        with mock.patch.object(change_classifier, "_build_type_file_index", side_effect=AssertionError("full repo walk must be skipped on fast pre-edit")):
            ok_mut, _, _ = file_mutation_allowed(self.repo, targets=["app/src/main/kotlin/com/example/HomeViewModel.kt"])
            self.assertTrue(ok_mut)

        # Meanwhile standalone classify() (used by prepare-verification / policy) STILL runs _build_type_file_index as normal!
        (self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt").write_text(
            "package com.example\nclass HomeViewModel { val ready = true }\n", encoding="utf-8"
        )
        with mock.patch.object(change_classifier, "_build_type_file_index", wraps=change_classifier._build_type_file_index) as spy_idx:
            cls_res = change_classifier.classify(self.repo, progress=False)
            self.assertIn("BUSINESS_LOGIC", cls_res["surfaces"])
            self.assertEqual(1, spy_idx.call_count)

    def test_opt4_and_opt5_in_process_readonly_and_host_aware_next_step(self) -> None:
        import importlib.util
        import io
        import contextlib
        from unittest import mock

        spec = importlib.util.spec_from_file_location("opt_installed_launcher", REPO_ROOT / "agents" / "harness.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        launcher.REPO_ROOT = self.repo
        launcher.AGENTS_ROOT = self.agents_dir

        # OPT 5: Read-only commands execute in-process without spawning subprocess.run!
        buf = io.StringIO()
        with mock.patch.object(launcher.subprocess, "run", side_effect=AssertionError("subprocess should not spawn for in-process read-only command")),              contextlib.redirect_stdout(buf):
            rc = launcher.main(["delegate-plan", "--json"])
        self.assertEqual(0, rc)
        self.assertEqual("PRE_PLAN_DISCOVERY", json.loads(buf.getvalue())["status"])

        # OPT 4: _print_next_step resolves active review_host from current-run.json when HARNESS_HOST is unset
        t_dir = self.agents_dir / "state/tasks/t-host"
        t_dir.mkdir(parents=True)
        (t_dir / "current-run.json").write_text(json.dumps({"run_id": "r1", "review_host": "antigravity"}), encoding="utf-8")
        captured_kwargs = {}

        def fake_resolve(repo_arg, tid_arg, plan_arg, **kw):
            captured_kwargs.update(kw)
            return {"code": "DISPATCH_REVIEWERS", "kind": "HOST_ACTION", "command": "", "reason": "Dispatch V2"}

        out_step = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=False),              mock.patch("mutation_guard.active_plan", return_value={"task_id": "t-host", "status": "VERIFYING"}),              mock.patch("workflow.resolve_next_action", side_effect=fake_resolve),              contextlib.redirect_stdout(out_step):
            os.environ.pop("HARNESS_HOST", None)
            launcher._print_next_step(step_args=["preflight"], exit_code=0)
        self.assertEqual("antigravity", captured_kwargs.get("host"))
        self.assertIn("NEXT_ACTION=DISPATCH_REVIEWERS", out_step.getvalue())

    def test_opt6_review_complete_all_auto_binds_brain_transcripts_and_finalizes_in_one_turn(self) -> None:
        import workflow
        from review_orchestrator import record_dispatch_batch, sha256_file
        from _vnext_common import read_json

        wf_parser = workflow.build_parser()
        plan = workflow.draft(wf_parser.parse_args([
            "draft", "--repo", str(self.repo), "--task-id", "t-batch", "--force",
            "--outcome", "Implement HomeViewModel update", "--kind", "FEATURE",
            "--expected-surfaces", "BUSINESS_LOGIC", "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ]))
        workflow.record_approval(wf_parser.parse_args([
            "approve", "--repo", str(self.repo), "--task-id", "t-batch",
            "--source", "conversation", "--proof-reference", "approved",
            "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", plan["plan_sha256"][:12],
        ]))
        (self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt").write_text(
            "package com.example\nclass HomeViewModel { fun load() = 42 }\n", encoding="utf-8"
        )
        (self.repo / "app/src/test/kotlin/com/example/HomeViewModelTest.kt").write_text(
            "package com.example\nclass HomeViewModelTest { fun testLoad() {} }\n", encoding="utf-8"
        )
        import review_models
        review_models.main(["set", "--repo", str(self.repo), "--task", "t-batch", "--scope", "task", "--preset", "inherit", "--source", "conversation", "--proof-reference", "use inherit"])
        workflow.main(["prepare-verification", "--repo", str(self.repo), "--task-id", "t-batch", "--host", "antigravity"])
        from review_package import build_package
        pkg_path, _ = build_package(self.repo, "t-batch")

        tdir = self.repo / ".agents/state/tasks/t-batch"
        current = read_json(tdir / "current-run.json")
        run_id = current["run_id"]
        policy = read_json(Path(current["policy"]))
        revs = list(policy["reviewers"])
        self.assertGreaterEqual(len(revs), 2)
        pkg_sha = sha256_file(pkg_path)

        # Record native dispatch batch (execution_id initially unbound in ledger!)
        record_dispatch_batch(self.repo, "t-batch", revs, host="antigravity")

        # Write matching child transcripts in Antigravity brain/ for ALL dispatched reviewers
        from review_execution import resolve_execution_profile
        prof = resolve_execution_profile(self.repo, "t-batch", host="antigravity")
        for idx, r_role in enumerate(revs):
            pointer = prof["reviewers"][r_role]["brief_pointer_prompt"]
            cid = f"rev-child-{idx}"
            tx = self.ag_runtime / "brain" / cid / ".system_generated/logs/transcript.jsonl"
            tx.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "source": "SYSTEM_SDK",
                    "type": "SYSTEM_MESSAGE",
                    "content": f"<SYSTEM_MESSAGE>\nsender=parent-lead priority=MESSAGE_PRIORITY_HIGH content={pointer}\n</SYSTEM_MESSAGE>",
                },
                {
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "content": "Review complete.\n```json\n" + json.dumps({
                        "schema_version": 2,
                        "task_id": "t-batch",
                        "run_id": run_id,
                        "reviewer": r_role,
                        "review_package_sha256": pkg_sha,
                        "verdict": "PASS",
                        "findings": [],
                    }, indent=2) + "\n```",
                },
            ]
            tx.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

        # Execute SINGLE-TURN `harness.py review complete-all --task t-batch` WITHOUT passing any --execution-id!
        proc = subprocess.run(
            [sys.executable, str(self.agents_dir / "harness.py"), "review", "complete-all", "--task", "t-batch"],
            cwd=str(self.repo),
            env={**os.environ, "ANTIGRAVITY_APP_DATA": str(self.ag_runtime)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr + proc.stdout)
        self.assertIn("REVIEW_FINALIZED:", proc.stdout)
        self.assertIn("REVIEW_SUMMARY_TABLE_BEGIN", proc.stdout)



class CoreFeatureUpgradesSelftest(unittest.TestCase):
    """Comprehensive verification for the 8 Core Feature Upgrades."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir(parents=True)
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example").mkdir(parents=True)
        (self.repo / "app" / "build.gradle.kts").write_text(
            'plugins { id("com.android.application") }\nandroid { namespace = "com.example" }\n',
            encoding="utf-8",
        )
        (self.repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "test@example.com"],
            ["git", "config", "user.name", "Test"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "init"],
        ):
            subprocess.run(cmd, cwd=str(self.repo), check=True)
        self.skills_root = SCRIPTS.parent / "skills"

    def tearDown(self):
        self.tmp.cleanup()

    def test_upgrade_1_coroutines_structured_vs_dispatcher_hazard_routing(self):
        from change_classifier import classify
        from review_policy import decide

        # Structured MVI/Flow coroutine without custom dispatchers/blocking -> 2 reviewers (no security-perf)
        vm = self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt"
        vm.write_text(
            "package com.example\n"
            "import kotlinx.coroutines.flow.MutableStateFlow\n"
            "import kotlinx.coroutines.flow.StateFlow\n"
            "class HomeViewModel {\n"
            "    private val _state = MutableStateFlow(0)\n"
            "    val state: StateFlow<Int> = _state\n"
            "    suspend fun refresh() { _state.value = 1 }\n"
            "}\n",
            encoding="utf-8",
        )
        cls_struct = classify(self.repo)
        self.assertIn("COROUTINES", cls_struct["surfaces"])
        self.assertIn("COROUTINE_STRUCTURED_ONLY", cls_struct["details"]["COROUTINES"]["reasons"])
        pol_struct = decide(cls_struct, self.skills_root, project_kind="application")
        self.assertEqual(["arch-regression-reviewer-agent", "bug-test-reviewer-agent"], pol_struct["reviewers"])
        self.assertNotIn("security-perf-reviewer-agent", pol_struct["reviewers"])

        # Explicit Dispatcher / GlobalScope / blocking hazard -> keeps security-perf-reviewer-agent!
        vm.write_text(
            "package com.example\n"
            "import kotlinx.coroutines.Dispatchers\n"
            "import kotlinx.coroutines.withContext\n"
            "class HomeViewModel {\n"
            "    suspend fun refresh() = withContext(Dispatchers.IO) { 42 }\n"
            "}\n",
            encoding="utf-8",
        )
        cls_hazard = classify(self.repo)
        self.assertIn("COROUTINE_DISPATCHER_OR_HAZARD", cls_hazard["details"]["COROUTINES"]["reasons"])
        pol_hazard = decide(cls_hazard, self.skills_root, project_kind="application")
        self.assertIn("security-perf-reviewer-agent", pol_hazard["reviewers"])

    def test_upgrade_2_ui_nav_login_and_purchase_calls_do_not_false_positive_critical(self):
        from change_classifier import classify

        ui_file = self.repo / "app/src/main/kotlin/com/example/PromoCard.kt"
        ui_file.write_text(
            "package com.example\n"
            "class PromoCoordinator {\n"
            "    fun onLoginClick() { navigateToLogin() }\n"
            "    fun navigateToLogin() { showLoginDialog() }\n"
            "    fun showLoginDialog() { loginBanner() }\n"
            "    fun loginBanner() {}\n"
            "    fun onPurchaseClick() { showPurchaseSheet() }\n"
            "    fun showPurchaseSheet() { purchaseBanner() }\n"
            "    fun purchaseBanner() {}\n"
            "}\n",
            encoding="utf-8",
        )
        cls_ui = classify(self.repo)
        self.assertNotIn("AUTH", cls_ui["surfaces"])
        self.assertNotIn("BILLING", cls_ui["surfaces"])
        self.assertNotEqual("CRITICAL", cls_ui["severity"])

        # Real auth & billing calls still trigger CRITICAL
        ui_file.write_text(
            "package com.example\n"
            "class AuthService {\n"
            "    fun login(email: String, token: String) { authenticate(token) }\n"
            "    fun authenticate(token: String) {}\n"
            "}\n",
            encoding="utf-8",
        )
        cls_real = classify(self.repo)
        self.assertIn("AUTH", cls_real["surfaces"])
        self.assertEqual("CRITICAL", cls_real["severity"])

    def test_upgrade_3_scoped_compose_and_xml_ui_ignores_untouched_ui_when_editing_pure_helper(self):
        from change_classifier import classify
        from review_policy import decide

        mixed = self.repo / "app/src/main/kotlin/com/example/CheckoutScreen.kt"
        mixed.write_text(
            "package com.example\n"
            "import androidx.compose.runtime.Composable\n"
            "@Composable\n"
            "fun CheckoutScreen(total: Double) {}\n\n"
            "internal fun calculateDiscount(amount: Double): Double {\n"
            "    return amount * 0.90\n"
            "}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=str(self.repo), check=True)
        subprocess.run(["git", "commit", "-qm", "add checkout screen"], cwd=str(self.repo), check=True)

        # Edit ONLY pure non-UI top-level helper calculateDiscount
        mixed.write_text(
            "package com.example\n"
            "import androidx.compose.runtime.Composable\n"
            "@Composable\n"
            "fun CheckoutScreen(total: Double) {}\n\n"
            "internal fun calculateDiscount(amount: Double): Double {\n"
            "    return amount * 0.85\n"
            "}\n",
            encoding="utf-8",
        )
        cls_helper = classify(self.repo)
        self.assertIn("BUSINESS_LOGIC", cls_helper["surfaces"])
        self.assertNotIn("COMPOSE_UI", cls_helper["surfaces"])
        pol_helper = decide(cls_helper, self.skills_root, project_kind="application")
        self.assertFalse(pol_helper["device_required"])
        self.assertNotIn("localization", pol_helper["gates"])

    def test_upgrade_4_lightweight_datastore_persistence_vs_heavy_schema_persistence(self):
        from change_classifier import classify
        from review_policy import decide

        prefs_kt = self.repo / "app/src/main/kotlin/com/example/ThemePrefs.kt"
        prefs_kt.write_text(
            "package com.example\n"
            "class ThemePrefs(private val store: androidx.datastore.core.DataStore<Any>) {\n"
            "    fun isDark(): Boolean = false\n"
            "}\n",
            encoding="utf-8",
        )
        cls_prefs = classify(self.repo)
        self.assertIn("PERSISTENCE", cls_prefs["surfaces"])
        pol_prefs = decide(cls_prefs, self.skills_root, project_kind="application")
        self.assertEqual("T2_FEATURE", pol_prefs["risk_tier"])
        self.assertEqual("STANDARD", pol_prefs["risk_lane"])
        self.assertIn("unit_tests", pol_prefs["gates"])

        # Heavy SQLite / SQLDelight persistence stays T4_DATA_DEVICE
        prefs_kt.write_text(
            "package com.example\n"
            "import android.database.sqlite.SQLiteDatabase\n"
            "class LegacyDb(private val db: SQLiteDatabase)\n",
            encoding="utf-8",
        )
        cls_db = classify(self.repo)
        pol_db = decide(cls_db, self.skills_root, project_kind="application")
        self.assertEqual("T4_DATA_DEVICE", pol_db["risk_tier"])
        self.assertEqual("DATA", pol_db["risk_lane"])

    def test_upgrade_5_isolated_private_delta_consolidates_to_single_bug_reviewer(self):
        from change_classifier import classify
        from review_policy import decide

        svc = self.repo / "app/src/main/kotlin/com/example/PriceCalculator.kt"
        svc.write_text(
            "package com.example\n"
            "class PriceCalculator {\n"
            "    fun total(raw: Int): Int = applyRounding(raw)\n"
            "    private fun applyRounding(raw: Int): Int {\n"
            "        return raw + 1\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=str(self.repo), check=True)
        subprocess.run(["git", "commit", "-qm", "add price calculator"], cwd=str(self.repo), check=True)

        # Edit ONLY inside private fun applyRounding -> 1 file, <=25 lines, private scope
        svc.write_text(
            "package com.example\n"
            "class PriceCalculator {\n"
            "    fun total(raw: Int): Int = applyRounding(raw)\n"
            "    private fun applyRounding(raw: Int): Int {\n"
            "        return raw + 2\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        cls_priv = classify(self.repo)
        self.assertIn("ISOLATED_PRIVATE_EDIT", cls_priv["details"]["BUSINESS_LOGIC"]["reasons"])
        pol_priv = decide(cls_priv, self.skills_root, project_kind="application")
        self.assertEqual("T2_FEATURE", pol_priv["risk_tier"])
        self.assertEqual(["bug-test-reviewer-agent"], pol_priv["reviewers"])
        self.assertIn("ISOLATED_PRIVATE_DELTA_CONSOLIDATED", pol_priv["explanation"]["reviewers"]["bug-test-reviewer-agent"])

    def test_upgrade_6_reading_guide_skips_passive_docs_and_strings_for_bug_and_spec_reviewers(self):
        from review_package import review_reading_guide

        content = (
            "# Review Package\n\n"
            "## Git diff\n"
            "```diff\n"
            "diff --git a/README.md b/README.md\n"
            "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"
            "diff --git a/app/src/main/res/values/strings.xml b/app/src/main/res/values/strings.xml\n"
            "--- a/app/src/main/res/values/strings.xml\n+++ b/app/src/main/res/values/strings.xml\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/app/src/main/kotlin/com/example/Logic.kt b/app/src/main/kotlin/com/example/Logic.kt\n"
            "--- a/app/src/main/kotlin/com/example/Logic.kt\n+++ b/app/src/main/kotlin/com/example/Logic.kt\n@@ -1 +1 @@\n-1\n+2\n"
            "```\n"
            "## Verification Summary\nOK\n"
        )
        policy = {
            "surfaces": ["DOCS", "LOCALIZATION", "BUSINESS_LOGIC"],
            "explanation": {
                "classification": {
                    "DOCS": {"files": ["README.md"]},
                    "LOCALIZATION": {"files": ["app/src/main/res/values/strings.xml"]},
                    "BUSINESS_LOGIC": {"files": ["app/src/main/kotlin/com/example/Logic.kt"]},
                }
            },
        }
        changes = [
            {"path": "README.md"},
            {"path": "app/src/main/res/values/strings.xml"},
            {"path": "app/src/main/kotlin/com/example/Logic.kt"},
        ]
        guide_bug = review_reading_guide(content, "bug-test-reviewer-agent", policy, changes)
        self.assertIsNotNone(guide_bug)
        self.assertEqual(["app/src/main/kotlin/com/example/Logic.kt"], guide_bug["focus_files"])
        guide_spec = review_reading_guide(content, "spec-compliance-agent", policy, changes)
        self.assertIsNotNone(guide_spec)
        self.assertEqual(["app/src/main/kotlin/com/example/Logic.kt"], guide_spec["focus_files"])
        # Cross-cutting arch-regression reviewer continues receiving full package (None reading guide)
        self.assertIsNone(review_reading_guide(content, "arch-regression-reviewer-agent", policy, changes))

    def test_upgrade_7_subagent_android15_16_and_strong_skipping_prompts(self):
        sub_dir = SCRIPTS.parent / "subagents"
        sec = json.loads((sub_dir / "security-perf-reviewer-agent.json").read_text(encoding="utf-8"))["system_prompt"]
        arch = json.loads((sub_dir / "arch-regression-reviewer-agent.json").read_text(encoding="utf-8"))["system_prompt"]
        bug = json.loads((sub_dir / "bug-test-reviewer-agent.json").read_text(encoding="utf-8"))["system_prompt"]
        ui = json.loads((sub_dir / "android-ui-expert-agent.json").read_text(encoding="utf-8"))["system_prompt"]

        self.assertIn("16 KB Page Size", sec)
        self.assertIn("foregroundServiceType", sec)
        self.assertIn("WindowInsets", arch)
        self.assertIn("Strong Skipping Mode", bug)
        self.assertIn("collectAsStateWithLifecycle()", bug)
        self.assertIn("Edge-to-Edge", ui)

    def test_upgrade_8_fast_kt_lint_catches_pending_intent_and_suspend_cancellation_swallow(self):
        import fast_kt_lint

        bad_kt = self.repo / "app/src/main/kotlin/com/example/SyncWorker.kt"
        bad_kt.write_text(
            "package com.example\n"
            "import android.app.PendingIntent\n"
            "import android.content.Context\n"
            "import android.content.Intent\n"
            "import kotlin.coroutines.cancellation.CancellationException\n\n"
            "class SyncWorker {\n"
            "    fun buildPi(ctx: Context, intent: Intent): PendingIntent {\n"
            "        return PendingIntent.getActivity(ctx, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT)\n"
            "    }\n"
            "    suspend fun syncBad(): Boolean {\n"
            "        return try {\n"
            "            true\n"
            "        } catch (e: Exception) {\n"
            "            false\n"
            "        }\n"
            "    }\n"
            "    suspend fun syncGood(): Boolean {\n"
            "        return try {\n"
            "            true\n"
            "        } catch (e: Exception) {\n"
            "            if (e is CancellationException) throw e\n"
            "            false\n"
            "        }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        issues = fast_kt_lint.lint_file(bad_kt)
        issue_types = [i["type"] for i in issues]
        self.assertIn("PENDING_INTENT_MISSING_IMMUTABILITY", issue_types)
        swallow_issues = [i for i in issues if i["type"] == "SUSPEND_CANCELLATION_SWALLOWED"]
        self.assertEqual(1, len(swallow_issues), issues)
        self.assertEqual(14, swallow_issues[0]["line"])

        # Adding FLAG_IMMUTABLE clears PendingIntent issue
        good_kt = self.repo / "app/src/main/kotlin/com/example/SafePi.kt"
        good_kt.write_text(
            "package com.example\n"
            "import android.app.PendingIntent\n"
            "import android.content.Context\n"
            "import android.content.Intent\n"
            "class SafePi {\n"
            "    fun buildPi(ctx: Context, intent: Intent): PendingIntent {\n"
            "        return PendingIntent.getActivity(\n"
            "            ctx,\n"
            "            0,\n"
            "            intent,\n"
            "            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,\n"
            "        )\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        self.assertEqual([], fast_kt_lint.lint_file(good_kt))




class ReviewerSpeedAndModelUpgradesSelftest(unittest.TestCase):
    """End-to-end verification for the 6 Reviewer Speed & Model-Selection Upgrades."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir(parents=True)
        (self.repo / ".agents" / "subagents").mkdir(parents=True)
        shutil.copytree(REPO_ROOT / "agents" / "subagents", self.repo / ".agents" / "subagents", dirs_exist_ok=True)
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example").mkdir(parents=True)
        (self.repo / "app" / "build.gradle.kts").write_text(
            'plugins { id("com.android.application") }\nandroid { namespace = "com.example" }\n',
            encoding="utf-8",
        )
        (self.repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "test@example.com"],
            ["git", "config", "user.name", "Test"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "init"],
        ):
            subprocess.run(cmd, cwd=str(self.repo), check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rev_upg_1_and_2_calibrated_flash_thinking_and_risk_hybrid_escalation(self):
        import review_models as rm
        from install_tool_adapters import generate_antigravity_agents

        generate_antigravity_agents(self.repo, dry_run=False)
        roster = ["bug-test-reviewer-agent", "arch-regression-reviewer-agent", "security-perf-reviewer-agent"]

        # 1. Calibrated flash-dynamic: NORMAL T2 task -> ALL reviewers use gemini-3.8-flash-medium (zero unnecessary flash-high!)
        rm.set_policy(
            self.repo,
            rm.resolve_preset_policy("flash-dynamic"),
            task_id=None,
            host="antigravity",
            source="conversation",
            proof_reference="Use flash-dynamic",
        )
        frozen_t2 = rm.freeze_models(
            self.repo,
            "t-normal",
            "antigravity",
            ["bug-test-reviewer-agent", "arch-regression-reviewer-agent"],
            policy_data={"surfaces": ["BUSINESS_LOGIC"], "severity": "MEDIUM"},
        )
        self.assertEqual("gemini-3.8-flash-medium", frozen_t2["reviewers"]["bug-test-reviewer-agent"]["resolved_model"])
        self.assertEqual("medium", frozen_t2["reviewers"]["bug-test-reviewer-agent"]["thinking_level"])
        self.assertEqual("gemini-3.8-flash-medium", frozen_t2["reviewers"]["arch-regression-reviewer-agent"]["resolved_model"])

        # 2. Risk-Hybrid: T2 NORMAL -> gemini-3.8-flash-medium; T5 CRITICAL -> automatic escalation to inherit!
        rm.set_policy(
            self.repo,
            rm.resolve_preset_policy("risk-hybrid"),
            task_id=None,
            host="antigravity",
            source="conversation",
            proof_reference="Use risk-hybrid project-wide",
        )
        frozen_rh_t2 = rm.freeze_models(
            self.repo,
            "t-rh-std",
            "antigravity",
            ["bug-test-reviewer-agent", "arch-regression-reviewer-agent"],
            policy_data={"surfaces": ["BUSINESS_LOGIC", "COMPOSE_UI"], "severity": "MEDIUM"},
        )
        self.assertEqual("gemini-3.8-flash-medium", frozen_rh_t2["reviewers"]["bug-test-reviewer-agent"]["resolved_model"])
        self.assertEqual("DEVELOPER_SELECTED_NATIVE", frozen_rh_t2["reviewers"]["bug-test-reviewer-agent"]["model_policy"])

        frozen_rh_t5 = rm.freeze_models(
            self.repo,
            "t-rh-crit",
            "antigravity",
            roster,
            policy_data={"surfaces": ["AUTH", "CRYPTO"], "severity": "CRITICAL"},
        )
        for r in roster:
            self.assertEqual("inherit", frozen_rh_t5["reviewers"][r]["resolved_model"], r)
            self.assertEqual("INHERIT_PARENT_BY_OMISSION", frozen_rh_t5["reviewers"][r]["model_policy"], r)
            self.assertIsNone(frozen_rh_t5["reviewers"][r]["agent_frontmatter_model"], r)
            # Parent-inherited escalation requires no fabricated SQLite model metadata
            rm.validate_model_evidence({"review_host": "antigravity", "review_models": frozen_rh_t5}, r, None)

        # 3. Complexity-Adaptive `flash-argon-hybrid` Worker & Doctor sync:
        import delegation_policy as dp
        from doctor.engine import HarnessDoctor
        from lifecycle import _antigravity_agent_matches_policy
        from _vnext_common import atomic_write_json, task_dir

        rm.set_policy(
            self.repo,
            rm.resolve_preset_policy("flash-argon-hybrid"),
            task_id=None,
            host="antigravity",
            source="conversation",
            proof_reference="Use flash-argon-hybrid project-wide",
        )
        # 3a. SIMPLE task -> Worker stays on gemini-3.8-flash-medium
        s_plan = {
            "task_id": "w-simple",
            "status": "IMPLEMENTING",
            "task_kind": "FEATURE",
            "risk_tier": "T2_FEATURE",
            "expected_modules": [":app"],
            "expected_surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"],
            "expected_files": [
                "app/src/main/kotlin/com/example/SimpleCard.kt",
                "app/src/test/kotlin/com/example/SimpleCardTest.kt",
            ],
        }
        atomic_write_json(task_dir(self.repo, "w-simple") / "plan.json", s_plan)
        dec_simple = dp.evaluate_delegation_policy(self.repo, task_id="w-simple", plan=s_plan, router_action="IMPLEMENT_TASK")
        self.assertEqual("SIMPLE", dec_simple["complexity_tier"])
        self.assertEqual("gemini-3.8-flash-medium", dec_simple["worker_model"])
        self.assertIn('model: "gemini-3.8-flash-medium"', (self.repo / ".agents/agents/harness-worker-agent/agent.md").read_text(encoding="utf-8"))

        # 3b. COMPLEX multi-module slice -> Worker upgrades to gemini-4-argon-low, Scout stays Flash, Doctor & lifecycle pass!
        c_plan = {
            "task_id": "w-complex",
            "status": "IMPLEMENTING",
            "task_kind": "FEATURE",
            "risk_tier": "T3_SUBSYSTEM",
            "expected_modules": [":app", ":core:data"],
            "expected_surfaces": ["COROUTINES", "NETWORK"],
            "expected_files": [
                "app/src/main/kotlin/com/example/SyncViewModel.kt",
                "core/data/src/main/kotlin/com/example/SyncRepo.kt",
            ],
        }
        atomic_write_json(task_dir(self.repo, "w-complex") / "plan.json", c_plan)
        dec_complex = dp.evaluate_delegation_policy(self.repo, task_id="w-complex", plan=c_plan, router_action="IMPLEMENT_TASK")
        self.assertEqual("COMPLEX", dec_complex["complexity_tier"])
        self.assertEqual("gemini-4-argon-low", dec_complex["worker_model"])
        self.assertIsNone(dec_complex["worker_invoke_model_arg"])
        self.assertIn('model: "gemini-4-argon-low"', (self.repo / ".agents/agents/harness-worker-agent/agent.md").read_text(encoding="utf-8"))
        self.assertIn('model: "gemini-3.8-flash-medium"', (self.repo / ".agents/agents/harness-scout-agent/agent.md").read_text(encoding="utf-8"))
        self.assertTrue(_antigravity_agent_matches_policy(self.repo, ".agents/agents/harness-worker-agent/agent.md"))
        doc_c = HarnessDoctor(self.repo, run_selftest=False)
        doc_c.check_antigravity_installation()
        rev_chk = next(r for r in doc_c.results if r.name == "Custom Reviewer Agents")
        self.assertEqual("PASS", rev_chk.status, rev_chk.message)

        # Validate utility dispatch allows omitted Model on Argon Low Worker, blocks Model='pro', and blocks Model='pro' on Scout
        ok_w, msg_w, _ = dp.validate_utility_dispatch(
            self.repo,
            c_plan,
            [{"TypeName": "harness-worker-agent", "Role": "harness-worker-agent", "Workspace": "inherit",
              "Prompt": "Implement SyncViewModel.kt and SyncRepo.kt following exact CoroutineDispatcher injection and run compile + test."}],
        )
        self.assertTrue(ok_w, msg_w)
        bad_w, _, code_w = dp.validate_utility_dispatch(
            self.repo,
            c_plan,
            [{"TypeName": "harness-worker-agent", "Role": "harness-worker-agent", "Workspace": "inherit", "Model": "pro",
              "Prompt": "Implement SyncViewModel.kt and SyncRepo.kt following exact CoroutineDispatcher injection and run compile + test."}],
        )
        self.assertFalse(bad_w)
        self.assertEqual("UTILITY_MODEL_QUOTA_GUARD", code_w)

        # Switching back to SIMPLE restores harness-worker-agent/agent.md to gemini-3.8-flash-medium
        dp.evaluate_delegation_policy(self.repo, task_id="w-simple", plan=s_plan, router_action="IMPLEMENT_TASK")
        self.assertIn('model: "gemini-3.8-flash-medium"', (self.repo / ".agents/agents/harness-worker-agent/agent.md").read_text(encoding="utf-8"))

    def test_rev_upg_3_4_5_6_inlined_package_pure_tools_turn_cap_and_gate_evidence(self):
        import argparse
        import workflow
        import review_package as rp
        from evidence_store import EvidenceStore
        from _vnext_common import read_json, state_root
        from install_tool_adapters import generate_antigravity_agents

        generate_antigravity_agents(self.repo, dry_run=False)
        for role in ("bug-test-reviewer-agent", "security-perf-reviewer-agent", "arch-regression-reviewer-agent", "spec-compliance-agent"):
            md = (self.repo / ".agents" / "agents" / role / "agent.md").read_text(encoding="utf-8")
            self.assertNotIn("- run_command", md)
            self.assertNotIn("- list_dir", md)
            self.assertIn("Strict 2-Turn Verification Budget", md)

        target = self.repo / "app/src/main/kotlin/com/example/FeatureUseCase.kt"
        target.write_text("package com.example\nclass FeatureUseCase { fun run(x: Int): Int = x + 1 }\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.repo), check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=str(self.repo), check=True)

        plan = workflow.draft(argparse.Namespace(
            repo=str(self.repo),
            task_id="t-inline",
            outcome="Update FeatureUseCase calculation",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules=":app",
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="",
            architecture_target_family=None,
            expected_files="app/src/main/kotlin/com/example/FeatureUseCase.kt",
            phases=None,
            force=True,
        ))
        workflow.record_approval(argparse.Namespace(
            repo=str(self.repo),
            task_id="t-inline",
            source="conversation",
            proof_reference="Proceed",
            enforcement_tier="RULE_ENFORCED",
            plan_hash=plan["plan_sha256"][:12],
        ))
        target.write_text("package com.example\nclass FeatureUseCase { fun run(x: Int): Int = x + 2 }\n", encoding="utf-8")
        current = workflow.prepare_verification(argparse.Namespace(repo=str(self.repo), task_id="t-inline", host="antigravity"))

        # Record preflight & unit_tests PASS evidence on this exact change_set_sha256 before building review package
        manifest = read_json(Path(current["manifest"]))
        store = EvidenceStore(state_root(self.repo))
        pkg_existing = Path(current.get("package_path") or "")
        if pkg_existing.is_file():
            pkg_existing.unlink()
        for gate in ("preflight", "unit_tests"):
            store.write(
                snapshot=manifest["delivery_snapshot_sha256"],
                run_id=current["run_id"],
                name=gate,
                producer="selftest",
                harness_version="1.2.16",
                change_set=manifest["change_set_sha256"],
                status="PASS",
                evidence={"detail": f"{gate} passed"},
            )

        pkg_path, meta = rp.build_package(self.repo, "t-inline")
        pkg_text = pkg_path.read_text(encoding="utf-8")
        self.assertIn("Verified Deterministic Gate Evidence", pkg_text)
        self.assertIn("`preflight`", pkg_text)
        self.assertIn("`unit_tests`", pkg_text)

        brief_text = Path(meta["briefs"]["bug-test-reviewer-agent"]).read_text(encoding="utf-8")
        self.assertIn("ZERO-HOP FAST PATH (ALREADY INLINED BELOW)", brief_text)
        self.assertIn("--- BEGIN INLINED CANONICAL REVIEW PACKAGE ---", brief_text)
        self.assertIn("Pre-Verified Deterministic Gates", brief_text)
        self.assertIn("Strict 2-Turn Cap", brief_text)



class ContextBridgeAndHookPolishSelftest(unittest.TestCase):
    """Verify Context Bridge anti-spam cooldown, verification silence, IDLE-only bridge reminder, background log guard, and D0 single-file grep."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir(parents=True)
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "dev@example.com"],
            ["git", "config", "user.name", "Dev"],
        ):
            subprocess.run(cmd, cwd=str(self.repo), check=True)
        (self.repo / "settings.gradle.kts").write_text('rootProject.name = "demo"\ninclude(":app")\n', encoding="utf-8")
        (self.repo / "app").mkdir()
        (self.repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
        src = self.repo / "app/src/main/kotlin/com/example"
        src.mkdir(parents=True)
        (src / "FoodPlanViewModelTest.kt").write_text("package com.example\nclass FoodPlanViewModelTest { fun testRefresh() {} }\n", encoding="utf-8")
        (self.repo / ".agents/state").mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "add", "."], cwd=str(self.repo), check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=str(self.repo), check=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cb_1_no_rotation_nag_during_prepare_verification_or_resume_and_auto_cooldown(self):
        from _workflow import router as wf_router
        from task_bridge import evaluate_rotation_advisory, should_emit_cli_rotation_advisory

        prev_steps = os.environ.get("HARNESS_CONVERSATION_STEPS")
        prev_conv = os.environ.get("HARNESS_CONVERSATION_ID")
        try:
            os.environ["HARNESS_CONVERSATION_STEPS"] = "300"
            os.environ["HARNESS_CONVERSATION_ID"] = "11111111-2222-3333-4444-555555555555"

            # PREPARE_VERIFICATION & RESUME_IMPLEMENTATION must NEVER attach context_rotation
            act_prep = wf_router._attach_rotation_advisory(
                self.repo, "t-1", {"task_id": "t-1", "status": "IMPLEMENTING"}, {"code": "PREPARE_VERIFICATION"}
            )
            self.assertNotIn("context_rotation", act_prep)
            act_res = wf_router._attach_rotation_advisory(
                self.repo, "t-1", {"task_id": "t-1", "status": "BLOCKED"}, {"code": "RESUME_IMPLEMENTATION"}
            )
            self.assertNotIn("context_rotation", act_res)

            #TASK_DELIVERED still attaches follow-up advisory with anti-spam instructions
            act_deliv = wf_router._attach_rotation_advisory(
                self.repo, "t-1", {"task_id": "t-1", "status": "DELIVERED"}, {"code": "TASK_DELIVERED"}
            )
            self.assertIn("context_rotation", act_deliv)
            rot = act_deliv["context_rotation"]
            self.assertIn("Never show or ask the developer to run CLI commands", rot["instructions"])
            self.assertIn("NEVER emit repetitive", rot["instructions"])

            # CLI auto-cooldown emits once at step 300, suppresses at step 305..419, and re-allows at step 425
            self.assertTrue(should_emit_cli_rotation_advisory(self.repo, rot))
            os.environ["HARNESS_CONVERSATION_STEPS"] = "310"
            rot_310 = evaluate_rotation_advisory(self.repo, "FOLLOW_UP_BOUNDARY", task_id="t-1")
            self.assertIsNotNone(rot_310)
            self.assertFalse(should_emit_cli_rotation_advisory(self.repo, rot_310))
            os.environ["HARNESS_CONVERSATION_STEPS"] = "425"
            rot_425 = evaluate_rotation_advisory(self.repo, "FOLLOW_UP_BOUNDARY", task_id="t-1")
            self.assertTrue(should_emit_cli_rotation_advisory(self.repo, rot_425))
        finally:
            if prev_steps is None:
                os.environ.pop("HARNESS_CONVERSATION_STEPS", None)
            else:
                os.environ["HARNESS_CONVERSATION_STEPS"] = prev_steps
            if prev_conv is None:
                os.environ.pop("HARNESS_CONVERSATION_ID", None)
            else:
                os.environ["HARNESS_CONVERSATION_ID"] = prev_conv

    def test_cb_2_and_hk_1_idle_only_bridge_reminder_and_background_yield_message(self):
        import argparse
        import pre_invocation_reminder as pir
        from task_bridge import save_task_bridge

        tdir = self.repo / ".agents/state/tasks/t-done"
        tdir.mkdir(parents=True, exist_ok=True)
        plan_p = tdir / "plan.json"
        plan_p.write_text(json.dumps({
            "task_id": "t-done",
            "status": "DELIVERED",
            "outcome": "Delivered food plan sync",
            "expected_files": ["app/src/main/kotlin/com/example/FoodPlanViewModelTest.kt"],
        }), encoding="utf-8")
        save_task_bridge(argparse.Namespace(repo=str(self.repo), task_id="t-done", next_outcome="Add meal swap analytics", summary="Sync worker shipped", bridge_id=None))

        old_repo = pir.REPO
        try:
            pir.REPO = self.repo
            # IDLE: Pending Task Bridge reminder IS shown
            idle_msg = pir._compact_message()
            self.assertTrue(idle_msg.startswith("Android Harness: Idle (no active task)."))
            self.assertIn("Pending Task Bridge", idle_msg)

            # Active IMPLEMENTING / VERIFYING: Pending Task Bridge is NOT shown, and background yield directive IS present
            active_dir = self.repo / ".agents/state/tasks/t-active"
            active_dir.mkdir(parents=True, exist_ok=True)
            active_plan_p = active_dir / "plan.json"
            for st in ("IMPLEMENTING", "VERIFYING"):
                active_plan_p.write_text(json.dumps({"task_id": "t-active", "status": st}), encoding="utf-8")
                (self.repo / ".agents/state/active-task.json").write_text(
                    json.dumps({"task_id": "t-active", "plan_path": str(active_plan_p)}), encoding="utf-8"
                )
                active_msg = pir._compact_message()
                self.assertNotIn("Pending Task Bridge", active_msg, st)
                self.assertIn("ZERO tool calls", active_msg, st)

            unchanged = pir._unchanged_state_message("t-active", "VERIFYING")
            self.assertIn("State unchanged", unchanged)
            self.assertIn("ZERO tool calls", unchanged)
        finally:
            pir.REPO = old_repo

    def test_hk_2_and_hk_3_block_background_task_log_and_allow_single_file_d0_grep(self):
        env = os.environ.copy()
        env["HARNESS_REPO"] = str(self.repo)
        env["HARNESS_HOOK_STATE"] = str(self.repo / ".agents/cache/hook-audit.jsonl")

        def call_safety(tool_name: str, args: dict) -> dict:
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "pre_tool_safety.py")],
                input=json.dumps({"toolCall": {"name": tool_name, "args": args}}),
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=15,
            )
            return _with_audit_reason(json.loads(proc.stdout), env, SCRIPTS / "pre_tool_safety.py")

        # 1. Reading .system_generated/tasks/task-355.log is deterministically denied
        res_log = call_safety("view_file", {"AbsolutePath": str(self.repo / ".system_generated/tasks/task-355.log")})
        self.assertEqual("deny", res_log["decision"])
        self.assertEqual("BACKGROUND_TASK_LOG_POLLING_FORBIDDEN", res_log.get("reason_code"))

        # 2. Single-file grep_search on an exact existing file is allowed under D0 without discovery receipt
        res_file_grep = call_safety("grep_search", {
            "SearchPath": "app/src/main/kotlin/com/example/FoodPlanViewModelTest.kt",
            "Query": "testRefresh",
        })
        self.assertEqual("allow", res_file_grep["decision"], res_file_grep.get("reason"))

        # 3. Directory-wide grep_search without discovery receipt STILL requires DISCOVERY_ANCHOR_REQUIRED
        res_dir_grep = call_safety("grep_search", {
            "SearchPath": "app/src/main/kotlin/com/example",
            "Query": "testRefresh",
        })
        self.assertEqual("deny", res_dir_grep["decision"])
        self.assertEqual("DISCOVERY_ANCHOR_REQUIRED", res_dir_grep.get("reason_code"))



class V135RealWorldAntigravityHardeningTests(unittest.TestCase):
    """Regression locks for v1.3.5 live Fitness_Android / Antigravity findings."""

    def test_v135_remote_mode_log_bloat_windows_mcp_and_a2ui_compose_lint_guards(self):
        import tempfile
        from unittest import mock
        import delegation_policy as dp
        import fast_kt_lint as fkl
        from doctor.engine import HarnessDoctor

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve()
        (self.repo / ".agents").mkdir(parents=True, exist_ok=True)

        # A) Remote Mode (#198819) blocks silent Flash->Argon quota leak in Scout & Worker unless explicitly overridden
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_REMOTE_AGENT": "1"}, clear=False):
            os.environ.pop("HARNESS_ALLOW_REMOTE_SUBAGENTS", None)
            pre_dec = dp.evaluate_delegation_policy(self.repo, plan=None)
            self.assertEqual("INLINE_LEAD_REMOTE_QUOTA_GUARD", pre_dec["strategy"])
            self.assertFalse(pre_dec["scout_allowed"])
            ok_rem, _, code_rem = dp.validate_utility_dispatch(
                self.repo,
                None,
                [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Prompt": "Inspect HomeViewModel callers and graph"}],
            )
            self.assertFalse(ok_rem)
            self.assertEqual("REMOTE_MODE_FLASH_QUOTA_LEAK_GUARD", code_rem)

        with mock.patch.dict(os.environ, {"ANTIGRAVITY_REMOTE_AGENT": "1", "HARNESS_ALLOW_REMOTE_SUBAGENTS": "1"}, clear=False):
            ok_ovr, msg_ovr, _ = dp.validate_utility_dispatch(
                self.repo,
                None,
                [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Prompt": "Inspect HomeViewModel callers and graph"}],
            )
            self.assertTrue(ok_ovr, msg_ovr)

        # B) Doctor detects WatchVersionControlState spin-loop in language_server.log (#198689) & Windows stdio MCPs (#199301)
        log_dir = self.repo / "ag_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "language_server.log").write_text(
            ("2026/11/12 01:10:00 WatchVersionControlState vcs watcher error: <nil>\n" * 30),
            encoding="utf-8",
        )
        (self.repo / ".agents" / "mcp.json").write_text(
            json.dumps({
                "mcpServers": {
                    "zoho": {"command": "node", "args": ["zoho-mcp.js"]},
                    "sqlite": {"command": "npx", "args": ["-y", "mcp-sqlite"]},
                }
            }),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_LOG_DIR": str(log_dir), "HARNESS_SIMULATE_WINDOWS_MCP": "1"}, clear=False):
            doc_h = HarnessDoctor(self.repo, run_selftest=False)
            doc_h.check_antigravity_installation()
            log_chk = next(r for r in doc_h.results if r.name == "Antigravity Log & Remote Guard")
            mcp_chk = next(r for r in doc_h.results if r.name == "Windows MCP Transport Guard")
            self.assertEqual("WARN", log_chk.status, log_chk.message)
            self.assertIn("WatchVersionControlState", log_chk.message)
            self.assertEqual("WARN", mcp_chk.status, mcp_chk.message)
            self.assertIn("#199301", mcp_chk.message)

        # C) Jetpack Compose A2UI 1.0 static lint traps in fast_kt_lint.py
        a2ui_dir = self.repo / "app/src/main/java/com/example/agentui"
        a2ui_dir.mkdir(parents=True, exist_ok=True)
        bad_vm = a2ui_dir / "CoachA2uiViewModel.kt"
        bad_vm.write_text(
            'package com.example.agentui\n'
            'import androidx.a2ui.model.A2uiMessageProcessor\n'
            'import androidx.a2ui.model.processor.processInput\n'
            'import androidx.compose.material3.a2ui.BasicCatalog\n'
            'class CoachA2uiViewModel(private val processor: A2uiMessageProcessor) {\n'
            '    val catalog = BasicCatalog\n'
            '    fun onAgentChunk(chunk: String) {\n'
            '        val initJson = """{"version":"1.0","createSurface":{"surfaceId":"s1","catalogId":"wrong-id"}}"""\n'
            '        processInput(processor, chunk)\n'
            '    }\n'
            '}\n',
            encoding="utf-8",
        )
        vm_issues = fkl.lint_file(bad_vm, modified_lines=None)
        vm_types = {i["type"] for i in vm_issues}
        self.assertIn("A2UI_UNCOLLECTED_OUTBOUND_EVENTS", vm_types, vm_issues)
        self.assertIn("A2UI_CATALOG_ID_MISMATCH", vm_types, vm_issues)

        # Fix both traps -> 0 A2UI issues!
        bad_vm.write_text(
            'package com.example.agentui\n'
            'import androidx.a2ui.model.A2uiMessageProcessor\n'
            'import androidx.a2ui.model.processor.processInput\n'
            'import androidx.compose.material3.a2ui.BasicCatalog\n'
            'class CoachA2uiViewModel(private val processor: A2uiMessageProcessor) {\n'
            '    val catalog = BasicCatalog\n'
            '    val events = processor.outboundEvents\n'
            '    fun onAgentChunk(chunk: String) {\n'
            '        val initJson = """{"version":"1.0","createSurface":{"surfaceId":"s1","catalogId":"https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"}}"""\n'
            '        processInput(processor, chunk)\n'
            '    }\n'
            '}\n',
            encoding="utf-8",
        )
        clean_vm_types = {i["type"] for i in fkl.lint_file(bad_vm, modified_lines=None)}
        self.assertNotIn("A2UI_UNCOLLECTED_OUTBOUND_EVENTS", clean_vm_types)
        self.assertNotIn("A2UI_CATALOG_ID_MISMATCH", clean_vm_types)

        # Build script BOM conflict + KMP commonMain Android-only AAR guard
        bad_gradle = self.repo / "feature_agent_build.gradle.kts"
        bad_gradle.write_text(
            'kotlin {\n'
            '    sourceSets {\n'
            '        commonMain.dependencies {\n'
            '            implementation(platform("androidx.compose:compose-bom:2026.05.00"))\n'
            '            implementation("androidx.compose.material3:material3-a2ui:1.0.0-alpha02")\n'
            '        }\n'
            '    }\n'
            '}\n',
            encoding="utf-8",
        )
        gradle_types = {i["type"] for i in fkl.lint_build_script(bad_gradle)}
        self.assertIn("A2UI_COMPOSE_BOM_CONFLICT", gradle_types)
        self.assertIn("A2UI_ANDROID_ONLY_IN_COMMON_MAIN", gradle_types)

    def test_v135_system_source_and_transcript_full_upgrade(self):
        from antigravity_runtime import prefer_full_transcript
        from delegation_policy import _transcript_head_and_dispatch, _prompt_sha256
        from reviewer_host import identity_messages, _steps

        with tempfile.TemporaryDirectory(prefix="v135_tx_") as td:
            logs = Path(td) / ".system_generated" / "logs"
            logs.mkdir(parents=True)
            long_brief = "Worker brief line\n" * 400
            full_sys = f"<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-11T17:18:00Z sender=lead-123 priority=MESSAGE_PRIORITY_HIGH content={long_brief}\n</SYSTEM_MESSAGE>"
            trunc_tx = logs / "transcript.jsonl"
            full_tx = logs / "transcript_full.jsonl"
            trunc_tx.write_text(
                json.dumps({"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "content": full_sys[:500] + "\n</SYSTEM_MESSAGE>", "truncated_fields": ["content"]}) + "\n"
                + json.dumps({"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "nudge"}) + "\n"
                + json.dumps({"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "short", "truncated_fields": ["content"]}) + "\n",
                encoding="utf-8",
            )
            full_tx.write_text(
                json.dumps({"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "content": full_sys}) + "\n"
                + json.dumps({"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "nudge"}) + "\n"
                + json.dumps({"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "UNTRUNCATED_VERDICT"}) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(full_tx, prefer_full_transcript(trunc_tx))
            has_user, sender, phash = _transcript_head_and_dispatch(trunc_tx)
            self.assertFalse(has_user)
            self.assertEqual("lead-123", sender)
            self.assertEqual(_prompt_sha256(long_brief), phash)
            msgs = list(identity_messages(trunc_tx))
            self.assertEqual(1, len(msgs))
            self.assertIn(long_brief, msgs[0])
            steps = _steps(trunc_tx)
            self.assertEqual("UNTRUNCATED_VERDICT", steps[-1]["content"])

    def test_v135_fast_tests_filter_and_compact_plan_md(self):
        import run_tests_gate
        from plan_document import _compact_display_payload

        bloated = {
            "base_delivery_snapshot_sha256": "a" * 64,
            "base_file_identities": [{"path": f"f{i}.kt", "content_identity": "x"} for i in range(200)],
        }
        compacted = _compact_display_payload(bloated)
        self.assertEqual(1, len(compacted["base_file_identities"]))
        self.assertIn("200 baseline entries", compacted["base_file_identities"][0])
        self.assertEqual(200, len(bloated["base_file_identities"]))

        cause = run_tests_gate._compact_failure_cause(
            "io.mockk.MockKException: Failed matching\n\tat com.app.HomeTest.myCase(HomeTest.kt:94)"
        )
        self.assertIn("MockKException", cause)
        self.assertIn("HomeTest.kt:94", cause)


    def test_v135_live_dual_app_kmp_and_android_fixes(self):
        from unittest.mock import patch
        import _product
        import _repo_files
        import run_tests_gate
        from _graph_core import parse_gradle_modules
        from project_context import normalize_instruction_record, normalize_instruction_scope

        # 1) String shorthand scope & hand-authored instruction record normalization
        self.assertEqual({"kind": "GLOBAL", "value": "*"}, normalize_instruction_scope("global"))
        self.assertEqual({"kind": "MODULE", "value": ":common"}, normalize_instruction_scope(":common"))
        rec = normalize_instruction_record({"id": "k1", "scope": "global", "text": "Use Koin", "active": True})
        self.assertEqual("ACTIVE", rec["status"])
        self.assertEqual(64, len(rec["sha256"]))
        self.assertEqual("REVOKED", normalize_instruction_record({"id": "k2", "active": False})["status"])

        # 2) Kebab-case Gradle TYPESAFE_PROJECT_ACCESSORS + root allprojects non-broadening + test-only consumer pruning
        with tempfile.TemporaryDirectory(prefix="v135_kmp_gate_") as td:
            repo = Path(td)
            (repo / "settings.gradle.kts").write_text(
                'enableFeaturePreview("TYPESAFE_PROJECT_ACCESSORS")\n'
                'include(":app", ":common", ":compose-desktop", ":ios-export")\n',
                encoding="utf-8",
            )
            (repo / "build.gradle.kts").write_text(
                'allprojects { configurations.all { resolutionStrategy {} } }\n',
                encoding="utf-8",
            )
            for mod, body in (
                ("app", 'plugins { id("com.android.application") }\ndependencies { implementation(projects.common) }'),
                ("common", 'plugins { kotlin("multiplatform"); id("com.android.kotlin.multiplatform.library") }'),
                ("compose-desktop", 'plugins { kotlin("jvm") }\ndependencies { implementation(projects.common) }'),
                ("ios-export", 'plugins { kotlin("multiplatform") }\nkotlin { iosArm64(); iosSimulatorArm64() }\ndependencies { api(projects.common) }'),
            ):
                (repo / mod).mkdir(parents=True)
                (repo / mod / "build.gradle.kts").write_text(body + "\n", encoding="utf-8")

            # Also verify camelCase accessor pointing to `:compose-desktop` resolves without unresolved_dependencies!
            (repo / "app/build.gradle.kts").write_text(
                'plugins { id("com.android.application") }\ndependencies { implementation(projects.common); implementation(projects.composeDesktop) }\n',
                encoding="utf-8",
            )
            nodes, edges = parse_gradle_modules(repo)
            self.assertFalse(any(n.metadata.get("unresolved_dependencies") for n in nodes.values()))
            self.assertTrue(any(e.source == ":app" and e.target == ":compose-desktop" for e in edges))

            # Test-only edit in :common runs ONLY :common:testAndroidHostTest (does NOT expand to :app or :compose-desktop!)
            test_only_path = repo / "common/src/commonTest/kotlin/dev/CommonTest.kt"
            with patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), \
                 patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"), \
                 patch.object(_repo_files, "changed_paths", return_value=[test_only_path]):
                self.assertEqual([":common:testAndroidHostTest"], run_tests_gate.resolve_target_tasks(repo, None))

            # Production edit in :common expands to :app and :compose-desktop (and skips Apple-only :ios-export on non-macOS)
            prod_path = repo / "common/src/commonMain/kotlin/dev/Common.kt"
            with patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True), \
                 patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"), \
                 patch.object(_repo_files, "changed_paths", return_value=[prod_path]):
                resolved = run_tests_gate.resolve_target_tasks(repo, None)
                self.assertIn(":common:testAndroidHostTest", resolved)
                self.assertIn(":app:testDebugUnitTest", resolved)
                self.assertIn(":compose-desktop:test", resolved)
                if sys.platform != "darwin":
                    self.assertNotIn(":ios-export:allTests", resolved)

            # 3) Non-Gradle Xcode SwiftUI directory in KMP repo does not invent fake Gradle module in resolve_phase_modules
            from _workflow.engine import resolve_phase_modules
            (repo / "PeopleInSpaceSwiftUI/PeopleInSpaceSwiftUI").mkdir(parents=True)
            (repo / "PeopleInSpaceSwiftUI/PeopleInSpaceSwiftUI/ContentView.swift").write_text("struct ContentView {}\n", encoding="utf-8")
            swift_mods = resolve_phase_modules(repo, {"expected_files": ["PeopleInSpaceSwiftUI/PeopleInSpaceSwiftUI/ContentView.swift"]})
            self.assertEqual([], swift_mods)

            # 4) UI screens containing Dao/Store/Service in their feature name still trigger UI_TO_DATA_SOURCE_BYPASS
            from architecture_drift import _detect_ui_data_source_bypass
            self.assertIsNotNone(
                _detect_ui_data_source_bypass(
                    "CartDirectDaoScreen",
                    "import androidx.compose.runtime.Composable\nimport androidx.room.Dao\n@Composable fun CartDirectDaoScreen() {}",
                )
            )
            self.assertIsNotNone(
                _detect_ui_data_source_bypass(
                    "ProductStoreScreen",
                    "import androidx.compose.runtime.Composable\nimport retrofit2.Retrofit\n@Composable fun ProductStoreScreen() {}",
                )
            )
            self.assertIsNone(
                _detect_ui_data_source_bypass(
                    "CartDao",
                    "import androidx.room.Dao\n@Dao interface CartDao",
                )
            )
            self.assertIsNone(
                _detect_ui_data_source_bypass(
                    "ProductRepositoryImpl",
                    "import androidx.room.Dao\nclass ProductRepositoryImpl",
                )
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
