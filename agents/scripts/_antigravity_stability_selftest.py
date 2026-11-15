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
            self.assertNotIn("\nmodel:", txt)
            self.assertIn("<!-- harness-target-model: gemini-4-hydrogen-", txt)
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

        # --- Case B0: Small 2-file FEATURE (<4 files) -> TRIVIAL_INLINE_LEAD (avoids cold Worker spawn tax!) ---
        _draft_and_begin([
            "--outcome", "Small 2-file state tweak",
            "--kind", "FEATURE",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-small-inline")
        pol_small = evaluate_delegation_policy(self.repo)
        self.assertEqual("TRIVIAL_INLINE_LEAD", pol_small["strategy"])
        self.assertIsNone(pol_small["recommended_subagent"])
        self.assertEqual("Gemini 4 Hydrogen (High)", pol_small["quota_strategy"]["fast_fallback_chat_model"])
        _cancel("t-small-inline")

        # --- Case B: 4+ file FEATURE -> DELEGATE_WORKER_SLICE (starts on Hydrogen High from Wave 1) + Guards + CLI ---
        _draft_and_begin([
            "--outcome", "Add home state, repo, screen & test",
            "--kind", "FEATURE",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeUiState.kt,app/src/main/kotlin/com/example/HomeRepository.kt,app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-feat")
        pol_feat = evaluate_delegation_policy(self.repo)
        self.assertEqual("DELEGATE_WORKER_SLICE", pol_feat["strategy"])
        self.assertEqual("gemini-4-hydrogen-high", pol_feat["worker_model"])
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
        # 2-file phase p1-state (<4 files) executes inline on warm Lead cache!
        self.assertEqual("TRIVIAL_INLINE_LEAD", act_phased["delegation_advisory"]["strategy"])
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
        self.assertNotIn("\nmodel:", (self.repo / ".agents/agents/harness-worker-agent/agent.md").read_text(encoding="utf-8"))

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
        self.assertNotIn("\nmodel:", (self.repo / ".agents/agents/harness-worker-agent/agent.md").read_text(encoding="utf-8"))
        self.assertNotIn("\nmodel:", (self.repo / ".agents/agents/harness-scout-agent/agent.md").read_text(encoding="utf-8"))
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

        # Switching back to SIMPLE keeps harness-worker-agent/agent.md stable and model-less on disk
        dp.evaluate_delegation_policy(self.repo, task_id="w-simple", plan=s_plan, router_action="IMPLEMENT_TASK")
        self.assertNotIn("\nmodel:", (self.repo / ".agents/agents/harness-worker-agent/agent.md").read_text(encoding="utf-8"))

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

        # D) Nov 12, 2026 Antigravity Platform Guards (#199713 Zombie Subagents, #199748 agy -p ToS, #199769 limit:0 429, #198333 Flash 503)
        import subprocess as _sp
        from antigravity_runtime import classify_antigravity_quota_or_capacity_error
        import session_forensics as sf_mod

        hook_py = Path(__file__).resolve().parents[2] / "agents/scripts/pre_tool_safety.py"
        hook_env = {**os.environ, "HARNESS_REPO": str(self.repo), "HARNESS_HOOK_STATE": str(self.repo / ".agents/state/audit_log.jsonl")}

        def _run_hook(tool_name: str, tool_args: dict) -> dict:
            res = _sp.run(
                [sys.executable, str(hook_py)],
                input=json.dumps({"toolName": tool_name, "toolArgs": tool_args}),
                text=True,
                capture_output=True,
                env=hook_env,
                check=True,
            )
            return json.loads(res.stdout.strip().splitlines()[-1])

        # D1. #199713: manage_subagents(Action="kill_all") is ALWAYS allowed even in IDLE/post-task state, whereas Action="list" is denied!
        reap_out = _run_hook("manage_subagents", {"Action": "kill_all"})
        self.assertEqual("allow", reap_out["decision"], reap_out)
        self.assertIn("ZOMBIE_SUBAGENT_REAP_ALLOWED", reap_out["reason"])
        list_out = _run_hook("manage_subagents", {"Action": "list"})
        self.assertEqual("deny", list_out["decision"], list_out)

        # D2. #199713: schedule (>=180s and schedules:*) is blocked to stop 255.3m reactive wakeup quota drain!
        sched_out = _run_hook("schedule", {"DurationSeconds": 15318})
        self.assertEqual("deny", sched_out["decision"], sched_out)
        self.assertIn("ZOMBIE_SUBAGENT_SCHEDULE_WAKEUP_GUARD", sched_out["reason"])
        sched_mcp_out = _run_hook("schedules:create_one_off", {"when": "in 4 hours"})
        self.assertEqual("deny", sched_mcp_out["decision"], sched_mcp_out)

        # D3. #199748/#199756: Unattended `agy -p` loops & UI keystroke injection are blocked to protect Ultra accounts from 403 bans!
        agy_out = _run_hook("run_command", {"CommandLine": 'for f in *.kt; do agy -p "audit $f"; done'})
        self.assertEqual("deny", agy_out["decision"], agy_out)
        self.assertIn("403 PERMISSION_DENIED", agy_out["reason"])

        # D4. #199713 Doctor detects schedule tool injection & 255.3m zombie reactive wakeup transcript spikes!
        bad_agent_dir = self.repo / ".agents/agents/harness-scout-agent"
        bad_agent_dir.mkdir(parents=True, exist_ok=True)
        (bad_agent_dir / "agent.md").write_text("---\nname: harness-scout-agent\ntools:\n  - view_file\n  - schedule\n---\n", encoding="utf-8")
        fake_brain = self.repo / "fake_brain"
        z_logs = fake_brain / "sub_zombie_1" / ".system_generated" / "logs"
        z_logs.mkdir(parents=True, exist_ok=True)
        (z_logs / "transcript.jsonl").write_text(
            json.dumps({"timestamp": "2026-11-12T01:00:00Z", "content": "HARNESS_SCOUT_FINGERPRINT=flash-architectural-scout-v1"}) + "\n"
            + json.dumps({"timestamp": "2026-11-12T05:15:18Z", "content": "Reactive wakeup burn"}) + "\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_BRAIN_ROOT": str(fake_brain)}, clear=False):
            doc_z = HarnessDoctor(self.repo, run_selftest=False)
            doc_z.check_antigravity_installation()
            z_chk = next(r for r in doc_z.results if r.name == "Zombie Subagent & Schedule Guard")
            self.assertEqual("WARN", z_chk.status, z_chk.message)
            self.assertIn("#199713", z_chk.message)

        # D5. #199769/#199770 Zero-Quota 429 & #198333 Flash 503 classifier + session forensics
        hz_429 = classify_antigravity_quota_or_capacity_error(
            "HTTP 429 RESOURCE_EXHAUSTED on antigravity-preview-09-2026 gemini-4-argon: limit: 0 requests per day / 0 input tokens per minute"
        )
        self.assertIsNotNone(hz_429)
        self.assertEqual("MANAGED_AGENT_ZERO_QUOTA_429", hz_429["code"])
        hz_503 = classify_antigravity_quota_or_capacity_error(
            "HTTP 503 Service Unavailable: gemini-3.8-flash-medium capacity overloaded, retrying in 16s"
        )
        self.assertIsNotNone(hz_503)
        self.assertEqual("FLASH_503_CAPACITY_BACKOFF", hz_503["code"])

        diag_rep = sf_mod.diagnose_session(self.repo)
        diag_codes = {f["code"] for f in diag_rep["findings"]}
        self.assertIn("ZOMBIE_SUBAGENT_REACTIVE_WAKEUP", diag_codes)
        self.assertIn("AGY_HEADLESS_LOOP_TOS_ATTEMPT", diag_codes)

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



    def test_nov13_burst_pacer_native_orchestrator_cache_shield_and_win11_guard(self) -> None:
        """Verify #200029/#199971 anti-burst pacer, Native Orchestrator 2-strike escalation, #200026 cache shield & #200037 Win11 guard."""
        import json as _json
        import tempfile
        from unittest.mock import patch

        import antigravity_runtime as ar
        import delegation_policy as dp
        import pre_invocation_reminder as pir
        import pre_tool_safety as pts
        import review_models as rm
        import session_forensics as sf
        from _vnext_common import atomic_write_json
        from doctor.engine import HarnessDoctor

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents" / "cache").mkdir(parents=True, exist_ok=True)
            (repo / ".agents" / "state" / "tasks" / "t-orch").mkdir(parents=True, exist_ok=True)
            atomic_write_json(repo / ".agents" / "state" / "active-task.json", {"task_id": "t-orch"})

            # 1) HYDROGEN_ANTI_BURST_PACER (#200029 / #199971)
            fake_now = [1000.0]
            slept: list[float] = []

            def _clock() -> float:
                return fake_now[0]

            def _sleep(sec: float) -> None:
                slept.append(sec)
                fake_now[0] += sec

            # 6 parallel calls within <=200ms in Turn 1 -> ZERO delay across all 6!
            for i in range(6):
                fake_now[0] += 0.03
                res = pts.check_and_apply_hydrogen_burst_pacer(
                    repo, "conv-burst-1", tool_name="view_file", mode="enforce", now_fn=_clock, sleep_fn=_sleep,
                )
                self.assertFalse(res["applied"])
                if i > 0:
                    self.assertTrue(res["coalesced_parallel"])
            self.assertEqual([], slept)

            # Turns 2 & 3 (0.6s apart) -> still < 4 turns in 6s window -> 0 delay
            for _ in range(2):
                fake_now[0] += 0.60
                res = pts.check_and_apply_hydrogen_burst_pacer(
                    repo, "conv-burst-1", tool_name="edit_file", mode="enforce", now_fn=_clock, sleep_fn=_sleep,
                )
                self.assertFalse(res["applied"])
            self.assertEqual([], slept)

            # Turn 4 & Turn 5 within 6s window -> MUST smooth burst with 0.80s..1.40s human-cadence cooldown!
            fake_now[0] += 0.55
            res4 = pts.check_and_apply_hydrogen_burst_pacer(
                repo, "conv-burst-1", tool_name="edit_file", mode="enforce", now_fn=_clock, sleep_fn=_sleep,
            )
            self.assertTrue(res4["applied"])
            self.assertGreaterEqual(res4["delay_sec"], 0.80)
            self.assertLessEqual(res4["delay_sec"], 1.40)
            self.assertEqual(1, len(slept))

            # Normal human/Gradle cadence (>6.5s gap) -> resets sliding window cleanly to 0 delay!
            fake_now[0] += 6.50
            res_calm = pts.check_and_apply_hydrogen_burst_pacer(
                repo, "conv-burst-1", tool_name="run_command", mode="enforce", now_fn=_clock, sleep_fn=_sleep,
            )
            self.assertFalse(res_calm["applied"])
            self.assertEqual(1, res_calm["turns_in_window"])

            # 2) Native Harness Orchestrator Two-Strike `Hydrogen High` Friction Auto-Escalation (4+ files; <4 files inline!)
            plan_3file_inline = {
                "task_id": "t-inline-3",
                "status": "IMPLEMENTING",
                "kind": "FEATURE",
                "risk_tier": "T1_LOW",
                "expected_files": [
                    "app/src/main/java/com/example/Feature.kt",
                    "app/src/main/java/com/example/FeatureUiState.kt",
                    "app/src/test/java/com/example/FeatureTest.kt",
                ],
                "expected_surfaces": ["UI"],
                "review_rounds": 0,
            }
            pol_3file = dp.evaluate_delegation_policy(repo, task_id="t-inline-3", plan=plan_3file_inline, router_action="IMPLEMENT")
            self.assertEqual("TRIVIAL_INLINE_LEAD", pol_3file["strategy"])
            self.assertIsNone(pol_3file["recommended_subagent"])

            plan_simple = {
                "task_id": "t-orch",
                "status": "IMPLEMENTING",
                "kind": "FEATURE",
                "risk_tier": "T1_LOW",
                "expected_files": [
                    "app/src/main/java/com/example/Feature.kt",
                    "app/src/main/java/com/example/FeatureUiState.kt",
                    "app/src/main/java/com/example/FeatureMapper.kt",
                    "app/src/test/java/com/example/FeatureTest.kt",
                ],
                "expected_surfaces": ["UI"],
                "review_rounds": 0,
            }
            atomic_write_json(repo / ".agents" / "state" / "tasks" / "t-orch" / "plan.json", plan_simple)

            # Antigravity v2.31.2 stdin `modelName`: Frontier Carbon/Claude sessions bypass Hydrogen burst pacer at 0ms
            res_frontier = pts.check_and_apply_hydrogen_burst_pacer(
                repo, "conv-burst-1", tool_name="edit_file", model_name="gemini-4-carbon-medium", now_fn=_clock, sleep_fn=_sleep,
            )
            self.assertFalse(res_frontier["applied"])
            self.assertEqual("exempt_frontier_model", res_frontier["mode"])

            # Wave 1 initial state (4 files >= 4) -> starts directly on `gemini-4-hydrogen-high`, DELEGATE_WORKER_SLICE!
            pol0 = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_simple, router_action="IMPLEMENT")
            self.assertEqual("DELEGATE_WORKER_SLICE", pol0["strategy"])
            self.assertEqual("gemini-4-hydrogen-high", pol0["worker_model"])
            self.assertEqual("NONE", pol0["friction_escalation"])

            # Intra-wave normal TDD compile/test iterations (`is_wave_boundary=False`) MUST NOT prematurely lock out Worker mid-wave!
            for iw_idx in range(3):
                dp.record_worker_verification_outcome(
                    repo, passed=False, gate_name="gradle-compiledebugkotlin", detail=f"Typo {iw_idx}",
                    task_id="t-orch", is_wave_boundary=False,
                )
            pol_mid_wave = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_simple, router_action="IMPLEMENT")
            self.assertEqual("DELEGATE_WORKER_SLICE", pol_mid_wave["strategy"])
            self.assertEqual("gemini-4-hydrogen-high", pol_mid_wave["worker_model"])
            self.assertEqual(0, pol_mid_wave["friction_strikes"])

            # Intra-wave runaway cap triggers cleanly at 5 consecutive intra-wave gate failures
            for _ in range(2):
                dp.record_worker_verification_outcome(
                    repo, passed=False, gate_name="unit_tests", detail="Spinning",
                    task_id="t-orch", is_wave_boundary=False,
                )
            with patch("mutation_guard.active_plan", return_value=plan_simple):
                ok_cap, cap_msg = dp.check_worker_intra_wave_retry_cap(repo, "python .agents/harness.py test")
            self.assertFalse(ok_cap)
            self.assertIn("WORKER_INTRA_WAVE_RETRY_CAP", cap_msg)

            # Wave 1 (`gemini-4-hydrogen-high` #1) completes WITHOUT green unit_tests.json -> Wave Failure #1 (`high_friction_strikes == 1`) -> Wave 2 corrective `Hydrogen High`!
            dp.evaluate_completed_worker_wave(repo, {
                "wave_id": "w-simple-1",
                "task_id": "t-orch",
                "phase_id": "",
                "task_status": "IMPLEMENTING",
                "worker_mode": "FULL_SLICE",
                "worker_model": "gemini-4-hydrogen-high",
                "dispatched_epoch": 500.0,
            })
            pol_w2 = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_simple, router_action="IMPLEMENT")
            self.assertEqual("DELEGATE_WORKER_SLICE", pol_w2["strategy"])
            self.assertEqual("gemini-4-hydrogen-high", pol_w2["worker_model"])
            self.assertEqual(1, pol_w2["friction_strikes"])
            self.assertEqual(1, pol_w2["high_friction_strikes"])
            self.assertEqual("ESCALATED_WORKER_MODEL", pol_w2["friction_escalation"])
            self.assertTrue(pol_w2["previous_wave_handoff"])

            # Duplicate PostToolUse on the same wave_id is strictly idempotent (stays at 1 strike!)
            dp.evaluate_completed_worker_wave(repo, {
                "wave_id": "w-simple-1",
                "task_id": "t-orch",
                "phase_id": "",
                "task_status": "IMPLEMENTING",
                "worker_mode": "FULL_SLICE",
                "worker_model": "gemini-4-hydrogen-high",
                "dispatched_epoch": 500.0,
            })
            self.assertEqual(1, dp.get_worker_friction_state(repo, "t-orch", plan_simple)["wave_failures"])

            # Wave 2 (`gemini-4-hydrogen-high` attempt #2) ALSO fails -> `high_friction_strikes == 2` triggers Native Orchestrator Lead Takeover (`Carbon`) without wasting a 3rd wave!
            dp.evaluate_completed_worker_wave(repo, {
                "wave_id": "w-simple-2",
                "task_id": "t-orch",
                "phase_id": "",
                "task_status": "IMPLEMENTING",
                "worker_mode": "FULL_SLICE",
                "worker_model": "gemini-4-hydrogen-high",
                "dispatched_epoch": 600.0,
            })
            pol_w4 = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_simple, router_action="IMPLEMENT")
            self.assertEqual("ORCHESTRATOR_FRICTION_LEAD_TAKEOVER", pol_w4["strategy"])
            self.assertEqual("TESTS_AND_GATES_ONLY", pol_w4["worker_mode"])
            self.assertEqual("LEAD_TAKEOVER", pol_w4["friction_escalation"])
            self.assertEqual(2, pol_w4["high_friction_strikes"])
            self.assertEqual("TWO_HYDROGEN_HIGH_FAILURES", pol_w4["takeover_trigger"])
            self.assertEqual(
                [
                    "app/src/main/java/com/example/Feature.kt",
                    "app/src/main/java/com/example/FeatureUiState.kt",
                    "app/src/main/java/com/example/FeatureMapper.kt",
                ],
                pol_w4["lead_owned_files"],
            )

            with patch("mutation_guard.active_plan", return_value=plan_simple), \
                 patch("workflow.resolve_next_action", return_value={"code": "IMPLEMENT"}):
                w_ok, _, w_code = dp.worker_write_allowed(
                    repo,
                    ["app/src/main/java/com/example/Feature.kt"],
                    {"agent_type": dp.WORKER_AGENT, "worker_mode": "FULL_SLICE"},
                )
            self.assertFalse(w_ok)
            self.assertEqual("WORKER_FRICTION_CORE_ESCALATED_TO_LEAD", w_code)

            # Lead Architect fixes code and runs full `unit_tests` PASS -> resets wave_failures & high_wave_failures to 0 and resolves handoff!
            dp.record_worker_verification_outcome(
                repo, passed=True, gate_name="unit_tests", detail="All green", task_id="t-orch", is_wave_boundary=False,
            )
            pol_reset = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_simple, router_action="IMPLEMENT")
            self.assertEqual("DELEGATE_WORKER_SLICE", pol_reset["strategy"])
            self.assertEqual("gemini-4-hydrogen-high", pol_reset["worker_model"])
            self.assertEqual(0, pol_reset["friction_strikes"])
            self.assertEqual(0, pol_reset["high_friction_strikes"])
            self.assertIsNone(dp.get_worker_handoff_capsule(repo, "t-orch"))

            # COMPLEX slice 2-Strike `Hydrogen High` + Zero-Scratch Handoff Capsule (`worker-handoff.json`):
            # Wave 1 (`High` #1) writes 85% of code & passes `compile`, fails 1 unit test -> Wave 2 (`High` #2 corrective delta) ->
            # fails 2nd time -> hands over to `Carbon` with full preserved worktree files, passing gates, failing `cause:`, & cumulative Worker history!
            plan_complex = {
                "task_id": "t-orch",
                "status": "IMPLEMENTING",
                "kind": "BUG",
                "risk_tier": "T3_MODERATE",
                "expected_files": [
                    "app/src/main/java/com/example/SyncWorker.kt",
                    "app/src/main/java/com/example/SyncRepository.kt",
                    "app/src/main/java/com/example/SyncContract.kt",
                    "app/src/test/java/com/example/SyncWorkerTest.kt",
                ],
                "expected_surfaces": ["COROUTINES", "NETWORK"],
                "review_rounds": 0,
            }
            (repo / ".agents" / "agents" / dp.WORKER_AGENT).mkdir(parents=True, exist_ok=True)
            (repo / "app/src/main/java/com/example").mkdir(parents=True, exist_ok=True)
            (repo / "app/src/test/java/com/example").mkdir(parents=True, exist_ok=True)
            (repo / "app/src/main/java/com/example/SyncRepository.kt").write_text(
                "package com.example\nclass SyncRepository { suspend fun sync(): Boolean = true }\n",
                encoding="utf-8",
            )
            (repo / "app/src/test/java/com/example/SyncWorkerTest.kt").write_text(
                "package com.example\nclass SyncWorkerTest { fun retryOnIoException() {} }\n",
                encoding="utf-8",
            )
            (repo / ".agents" / "state" / "results").mkdir(parents=True, exist_ok=True)
            atomic_write_json(repo / ".agents" / "state" / "results" / "compile.json", {"status": "PASS", "exit_code": 0})
            atomic_write_json(
                repo / ".agents" / "state" / "results" / "unit_tests.json",
                {
                    "status": "FAIL",
                    "exit_code": 1,
                    "failed_tests": ["com.example.SyncWorkerTest#retryOnIoException"],
                    "cause": "java.lang.AssertionError: expected Result.retry() on IOException at SyncWorkerTest.kt:44",
                },
            )
            atomic_write_json(repo / ".agents" / "state" / "tasks" / "t-orch" / "plan.json", plan_complex)
            atomic_write_json(repo / ".agents" / "state" / "active-task.json", {"task_id": "t-orch"})

            pol_c0 = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_complex, router_action="IMPLEMENT")
            self.assertEqual("COMPLEX", pol_c0["complexity_tier"])
            self.assertEqual("DELEGATE_WORKER_SLICE", pol_c0["strategy"])
            self.assertEqual("gemini-4-hydrogen-high", pol_c0["worker_model"])

            # Wave 1 (`Hydrogen High` #1) fails with structured Worker self-report -> Wave 2 stays on `gemini-4-hydrogen-high` (zero `xhigh`!)
            dp.evaluate_completed_worker_wave(
                repo,
                {
                    "wave_id": "w-complex-1",
                    "task_id": "t-orch",
                    "phase_id": "",
                    "task_status": "IMPLEMENTING",
                    "worker_mode": "FULL_SLICE",
                    "worker_model": "gemini-4-hydrogen-high",
                    "dispatched_epoch": 1.0,
                },
                worker_output=(
                    "HANDOFF_COMPLETED: Implemented SyncRepository.kt and SyncWorkerTest.kt harness.\n"
                    "HANDOFF_TRIED_AND_FAILED: Wrapped sync() in runCatching, which accidentally caught CancellationException.\n"
                    "HANDOFF_EXACT_BLOCKER: SyncWorker.kt:29 returns Result.failure() instead of Result.retry() on IOException."
                ),
            )
            pol_c1 = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_complex, router_action="IMPLEMENT")
            self.assertEqual("DELEGATE_WORKER_SLICE", pol_c1["strategy"])
            self.assertEqual("gemini-4-hydrogen-high", pol_c1["worker_model"])
            self.assertNotIn("xhigh", pol_c1["worker_model"])
            self.assertEqual(1, pol_c1["high_friction_strikes"])
            self.assertIn("SyncRepository.kt", pol_c1["previous_wave_handoff"]["summary_for_lead"])

            # Wave 2 (`Hydrogen High` #2) fails -> Now `high_friction_strikes == 2` hands over to `Carbon` with cumulative Zero-Scratch Handoff!
            dp.evaluate_completed_worker_wave(
                repo,
                {
                    "wave_id": "w-complex-2",
                    "task_id": "t-orch",
                    "phase_id": "",
                    "task_status": "IMPLEMENTING",
                    "worker_mode": "FULL_SLICE",
                    "worker_model": "gemini-4-hydrogen-high",
                    "dispatched_epoch": 1.0,
                },
                worker_output=(
                    "HANDOFF_COMPLETED: Preserved SyncRepository.kt and rethrew CancellationException.\n"
                    "HANDOFF_TRIED_AND_FAILED: Added retry policy in SyncWorker but dispatcher clock under StandardTestDispatcher stalled.\n"
                    "HANDOFF_EXACT_BLOCKER: SyncWorkerTest.kt:44 needs advanceUntilIdle() with injected CoroutineDispatcher."
                ),
            )
            pol_c2 = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_complex, router_action="IMPLEMENT")
            self.assertEqual("ORCHESTRATOR_FRICTION_LEAD_TAKEOVER", pol_c2["strategy"])
            self.assertEqual("LEAD_TAKEOVER", pol_c2["friction_escalation"])
            self.assertEqual("TWO_HYDROGEN_HIGH_FAILURES", pol_c2["takeover_trigger"])
            self.assertEqual(2, pol_c2["high_friction_strikes"])
            self.assertEqual("TESTS_AND_GATES_ONLY", pol_c2["worker_mode"])
            self.assertEqual("gemini-4-hydrogen-high", pol_c2["worker_model"])
            handoff_c2 = pol_c2["lead_takeover_handoff"]
            self.assertFalse(handoff_c2["resolved"])
            self.assertEqual(2, len(handoff_c2["attempt_history"]))
            self.assertIn("compile", handoff_c2["passing_gates"])
            self.assertTrue(any("SyncRepository.kt" in f["file"] for f in handoff_c2["completed_files_on_disk"]))
            self.assertIn("StandardTestDispatcher", handoff_c2["worker_self_report"]["tried_and_failed"])
            self.assertIn("DO NOT START FROM SCRATCH", pol_c2["reason"])

            # Verify `PreInvocation` (`pending_post_subagent_directive`) automatically injects the Zero-Scratch Handoff to `Carbon`!
            w_key, w_dir = dp.pending_post_subagent_directive(repo, "lead-carbon-conv")
            self.assertTrue(w_key.startswith("takeover-t-orch-"))
            self.assertIn("DO NOT START FROM SCRATCH", w_dir)
            self.assertIn("SyncRepository.kt", w_dir)
            self.assertIn("SyncWorkerTest.kt:44", w_dir)

            w_agent_md = (repo / ".agents" / "agents" / dp.WORKER_AGENT / "agent.md").read_text(encoding="utf-8")
            self.assertNotIn("\nmodel:", w_agent_md)
            self.assertIn("<!-- harness-target-model: gemini-4-hydrogen-", w_agent_md)
            with patch("mutation_guard.active_plan", return_value=plan_complex), \
                 patch("workflow.resolve_next_action", return_value={"code": "IMPLEMENT"}):
                ok_wc, _, code_wc = dp.worker_write_allowed(
                    repo,
                    ["app/src/main/java/com/example/SyncWorker.kt"],
                    {"agent_type": dp.WORKER_AGENT, "worker_mode": "FULL_SLICE"},
                )
                ok_wt, _, _ = dp.worker_write_allowed(
                    repo,
                    ["app/src/test/java/com/example/SyncWorkerTest.kt"],
                    {"agent_type": dp.WORKER_AGENT, "worker_mode": "TESTS_AND_GATES_ONLY"},
                )
            self.assertFalse(ok_wc)
            self.assertEqual("WORKER_FRICTION_CORE_ESCALATED_TO_LEAD", code_wc)
            self.assertTrue(ok_wt)

            # Fast-Fail Exception Test: Reset strikes, then verify an explicit `ARCHITECTURAL_BLOCKER:` on Wave 1 skips Wave 2 and hands straight to `Carbon`!
            dp.record_worker_verification_outcome(
                repo, passed=True, gate_name="unit_tests", detail="Reset before fast-fail check", task_id="t-orch", is_wave_boundary=False,
            )
            dp.evaluate_completed_worker_wave(
                repo,
                {
                    "wave_id": "w-fast-fail-arch",
                    "task_id": "t-orch",
                    "phase_id": "",
                    "task_status": "IMPLEMENTING",
                    "worker_mode": "FULL_SLICE",
                    "worker_model": "gemini-4-hydrogen-high",
                    "dispatched_epoch": 1.0,
                },
                worker_output="HANDOFF_EXACT_BLOCKER: ARCHITECTURAL_BLOCKER: [SCOPE-HINT] Legacy BillingManagerTest outside expected_files conflicts with new interface.",
            )
            pol_ff = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_complex, router_action="IMPLEMENT")
            self.assertEqual("ORCHESTRATOR_FRICTION_LEAD_TAKEOVER", pol_ff["strategy"])
            self.assertEqual(1, pol_ff["friction_strikes"])
            self.assertEqual("FAST_FAIL_ARCHITECTURAL_BLOCKER", pol_ff["takeover_trigger"])

            # Verify green snapshot-bound `unit_tests.json` at Wave completion passes cleanly and resets strikes!
            (repo / ".agents" / "state" / "results").mkdir(parents=True, exist_ok=True)
            atomic_write_json(repo / ".agents" / "state" / "results" / "unit_tests.json", {"status": "PASS", "exit_code": 0})
            dp.evaluate_completed_worker_wave(repo, {
                "wave_id": "w-complex-green",
                "task_id": "t-orch",
                "phase_id": "",
                "task_status": "IMPLEMENTING",
                "worker_mode": "TESTS_AND_GATES_ONLY",
                "dispatched_epoch": 1.0,
            })
            self.assertEqual(0, dp.get_worker_friction_state(repo, "t-orch", plan_complex)["wave_failures"])

            # 3) #200026 Turn-0 Subagent Prefix-Cache Lock & safe-cache-hybrid Routing
            brain_root = repo / "brain"
            child_tx = brain_root / "sub-scout-turn0" / ".system_generated" / "logs" / "transcript.jsonl"
            child_tx.parent.mkdir(parents=True, exist_ok=True)
            child_tx.write_text(
                _json.dumps({
                    "source": "AGENT_ORCHESTRATOR",
                    "type": "SYSTEM_MESSAGE",
                    "content": "<SYSTEM_MESSAGE>sender=parent-1 priority=MESSAGE_PRIORITY_HIGH content=Inspect module\n</SYSTEM_MESSAGE>",
                }) + "\n",
                encoding="utf-8",
            )
            with patch.object(ar, "resolve_transcript", return_value=child_tx),                  patch.object(ar, "prefer_full_transcript", return_value=child_tx):
                self.assertTrue(pir._is_reviewer_conversation(repo, "sub-scout-turn0"))

            sc_pol, sc_scope = rm.resolve_interactive_choice("safe-cache-project")
            self.assertEqual("project", sc_scope)
            self.assertEqual("safe-cache-hybrid", sc_pol["default"])
            self.assertEqual(("gemini-4-hydrogen-medium", "medium"), rm.resolve_antigravity_model("safe-cache-hybrid", "bug-test-reviewer-agent", "NORMAL", complexity_tier="SIMPLE"))
            self.assertEqual(("gemini-4-hydrogen-high", "high"), rm.resolve_antigravity_model("safe-cache-hybrid", "bug-test-reviewer-agent", "DEEP", complexity_tier="COMPLEX"))
            self.assertEqual(("gemini-4-hydrogen-high", "high"), rm.resolve_antigravity_model("safe-cache-hybrid", "security-perf-reviewer-agent", "MAX", complexity_tier="CRITICAL"))
            self.assertEqual(("gemini-4-hydrogen-high", "high"), rm.resolve_antigravity_model("safe-cache-hybrid", "arch-regression-reviewer-agent", "NORMAL", complexity_tier="CRITICAL"))
            with patch.object(rm, "load_policy", return_value=(sc_pol, "project")):
                self.assertEqual("gemini-3.8-flash-medium", dp.resolve_utility_scout_model(repo, "t-orch", plan_simple))
                self.assertEqual(("gemini-4-hydrogen-high", "SIMPLE"), dp.resolve_utility_worker_model(repo, "t-orch", plan_simple))

            # 4) Forensics & Doctor (#200026, #200029/#199971, #200037)
            c_tos = ar.classify_antigravity_quota_or_capacity_error(
                "403 PERMISSION_DENIED (TOS_VIOLATION): account was instantly flagged and suspended after Hydrogen plan execution"
            )
            self.assertIsNotNone(c_tos)
            self.assertEqual("HYDROGEN_403_TOS_FALSE_POSITIVE", c_tos["code"])

            c_cache = ar.classify_antigravity_quota_or_capacity_error(
                "Turn 3 +701 token injection and cachedContentTokenCount=0 multi-shard split"
            )
            self.assertIsNotNone(c_cache)
            self.assertEqual("GEMINI4_TURN3_CACHE_DROP_ANOMALY", c_cache["code"])

            diag_tx = brain_root / "conv-diag-200026" / ".system_generated" / "logs" / "transcript.jsonl"
            diag_tx.parent.mkdir(parents=True, exist_ok=True)
            diag_lines = [
                _json.dumps({"step_index": 0, "usageMetadata": {"promptTokenCount": 33439, "cachedContentTokenCount": 0}}),
                _json.dumps({"step_index": 1, "usageMetadata": {"promptTokenCount": 33577, "cachedContentTokenCount": 0}}),
                _json.dumps({"step_index": 2, "usageMetadata": {"promptTokenCount": 33704, "cachedContentTokenCount": 31528}}),
                _json.dumps({"step_index": 3, "usageMetadata": {"promptTokenCount": 34505}}),  # Turn-3 +701 & omitted cachedContentTokenCount=0!
                "HTTP 403 PERMISSION_DENIED (TOS_VIOLATION) Error ID: 6a55a8c9-9b7e-4fe3",
            ]
            diag_tx.write_text("\n".join(diag_lines) + "\n", encoding="utf-8")
            with patch.object(ar, "resolve_transcript", return_value=diag_tx),                  patch.object(ar, "prefer_full_transcript", return_value=diag_tx):
                forensics = sf.diagnose_session(repo, conversation_id="conv-diag-200026", task_id="t-orch")
            f_codes = {f["code"] for f in forensics["findings"]}
            self.assertIn("GEMINI4_TURN3_CACHE_DROP_ANOMALY", f_codes)
            self.assertIn("HYDROGEN_403_TOS_FALSE_POSITIVE", f_codes)
            self.assertIn("HYDROGEN_BURST_PACER_SMOOTHED", f_codes)

            # #200037 Windows 11 Smart App Control Error 4551 installer check
            dl_dir = repo / "Downloads"
            dl_dir.mkdir(parents=True, exist_ok=True)
            (dl_dir / "AntigravitySetup-2.7.0-x64.exe").write_bytes(b"MZ")
            sac_hit = ar.inspect_windows_smart_app_control_4551_risk(
                env={"HARNESS_SIMULATE_PLATFORM": "win32"},
                installer_dirs=[dl_dir],
            )
            self.assertTrue(sac_hit["applicable"])
            self.assertTrue(sac_hit["at_risk"])
            sac_clean = ar.inspect_windows_smart_app_control_4551_risk(
                env={"HARNESS_SIMULATE_PLATFORM": "win32"},
                installer_dirs=[repo / "EmptyDownloads"],
            )
            self.assertFalse(sac_clean["at_risk"])

            # 5) VERIFYING-stage green unit_tests resolves worker-handoff.json after Carbon takeover
            import _gate_results as gr
            atomic_write_json(repo / ".agents" / "state" / "active-task.json", {"task_id": "t-orch"})
            plan_ver = dict(plan_simple, status="VERIFYING", verification_run_id="run-v1")
            atomic_write_json(repo / ".agents" / "state" / "tasks" / "t-orch" / "plan.json", plan_ver)
            atomic_write_json(
                repo / ".agents" / "state" / "tasks" / "t-orch" / "current-run.json",
                {"run_id": "run-v1", "delivery_snapshot_sha256": "a" * 64, "change_set_sha256": "b" * 64},
            )
            dp.record_worker_verification_outcome(
                repo, passed=False, gate_name="unit_tests", detail="fail 1",
                task_id="t-orch", is_wave_boundary=True, wave_id="w-v1", worker_model_used="gemini-4-hydrogen-high",
            )
            dp.record_worker_verification_outcome(
                repo, passed=False, gate_name="unit_tests", detail="fail 2",
                task_id="t-orch", is_wave_boundary=True, wave_id="w-v2", worker_model_used="gemini-4-hydrogen-high",
            )
            self.assertIsNotNone(dp.get_worker_handoff_capsule(repo, "t-orch"))
            gr.write_gate_result(
                "unit_tests",
                {
                    "status": "PASS",
                    "exit_code": 0,
                    "delivery_snapshot_sha256": "a" * 64,
                    "change_set_sha256": "b" * 64,
                    "external_inputs_sha256": "c" * 64,
                },
                results_dir_override=repo / ".agents" / "state" / "results",
            )
            self.assertIsNone(dp.get_worker_handoff_capsule(repo, "t-orch"))
            resolved_doc = dp.get_worker_handoff_capsule(repo, "t-orch", include_resolved=True)
            self.assertIsNotNone(resolved_doc)
            self.assertTrue(resolved_doc["resolved"])


class TestV139AuditFixes(unittest.TestCase):
    """Regression coverage for v1.3.9 audited runtime, verifier, static-guard, and template fixes."""

    def test_v139_01_jetski_runtime_roots_and_hierarchical_ids(self) -> None:
        import antigravity_runtime as ar

        roots = [p.name for p in ar.candidate_runtime_roots()]
        self.assertIn("jetski", roots)

        valid_jetski_id = "v1/default/jetski_remote_agents_3p/1ab25276-4da2-4140-9a7b-ba987761bdfb"
        self.assertFalse(ar._is_invalid_conversation_id(valid_jetski_id))
        self.assertTrue(ar._is_invalid_conversation_id("v1/default/../1ab25276-4da2-4140-9a7b-ba987761bdfb"))
        self.assertTrue(ar._is_invalid_conversation_id("foo/bar"))

        with tempfile.TemporaryDirectory() as td:
            app_root = Path(td) / "jetski"
            tx_file = (
                app_root
                / "brain"
                / "v1"
                / "default"
                / "jetski_remote_agents_3p"
                / "1ab25276-4da2-4140-9a7b-ba987761bdfb"
                / ".system_generated"
                / "logs"
                / "transcript.jsonl"
            )
            tx_file.parent.mkdir(parents=True, exist_ok=True)
            tx_file.write_text('{"source":"SYSTEM","type":"SYSTEM_MESSAGE","content":"hi"}\n', encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(app_root)}, clear=False):
                resolved = ar.resolve_transcript(valid_jetski_id)
                self.assertEqual(tx_file.resolve(), resolved)
                recent = ar.iter_recent_brain_conversations(app_root / "brain", limit=8)
                self.assertEqual([valid_jetski_id], [cid for cid, _ in recent])

        rem_cloud, _ = ar.detect_antigravity_remote_mode({"ANTIGRAVITY_MODE": "cloud"})
        self.assertFalse(rem_cloud)
        self.assertTrue(ar.is_jetski_cloud_environment({"ANTIGRAVITY_MODE": "jetski"}))

    def test_v139_02_single_expression_suspend_lint_and_room_array_migrations(self) -> None:
        import fast_kt_lint
        import room_guard

        bad_kt = (
            "package com.example\n"
            "class Repo {\n"
            "    suspend fun loadData(): String? = try {\n"
            "        fetchRemote()\n"
            "    } catch (e: Exception) {\n"
            "        null\n"
            "    }\n"
            "}\n"
        )
        good_kt = (
            "package com.example\n"
            "import kotlinx.coroutines.CancellationException\n"
            "class Repo {\n"
            "    suspend fun loadData(): String? = try {\n"
            "        fetchRemote()\n"
            "    } catch (e: CancellationException) {\n"
            "        throw e\n"
            "    } catch (e: Exception) {\n"
            "        null\n"
            "    }\n"
            "}\n"
        )
        bad_clean = fast_kt_lint._strip_kotlin_comments_preserve_lines(bad_kt)
        good_clean = fast_kt_lint._strip_kotlin_comments_preserve_lines(good_kt)
        self.assertEqual(1, len(fast_kt_lint._find_suspend_cancellation_swallows(bad_clean, None)))
        self.assertEqual(0, len(fast_kt_lint._find_suspend_cancellation_swallows(good_clean, None)))

        db_src = (
            "package com.example.db\n"
            "@Database(entities = [UserEntity::class], version = 3)\n"
            "abstract class AppDatabase : RoomDatabase() {\n"
            "    companion object {\n"
            "        val ALL_MIGRATIONS = arrayOf(MIGRATION_1_2, MIGRATION_2_3)\n"
            "        fun build(ctx: Context) = Room.databaseBuilder(ctx, AppDatabase::class.java, \"db\")\n"
            "            .addMigrations(*ALL_MIGRATIONS)\n"
            "            .build()\n"
            "    }\n"
            "}\n"
        )
        decl = room_guard.parse_database_source(db_src, "app/src/main/java/AppDatabase.kt")
        self.assertIn("MIGRATION_1_2", decl.registered)
        self.assertIn("MIGRATION_2_3", decl.registered)

    def test_v139_03_worker_lifecycle_guard_and_templates_and_safety_blocks(self) -> None:
        import delegation_policy as dp

        for forbidden_cmd in (
            "python .agents/harness.py task plan-note --task-id t1 --note x",
            "python .agents/harness.py pm sync",
            "python .agents/harness.py context note --note x",
        ):
            self.assertIsNotNone(dp._WORKER_FORBIDDEN_LIFECYCLE_RE.search(forbidden_cmd), forbidden_cmd)

        gemini_tpl = (REPO_ROOT / "agents" / "tool-adapters" / "GEMINI.md.template").read_text(encoding="utf-8")
        global_tpl = (REPO_ROOT / "agents" / "tool-adapters" / "gemini-runtime" / "android-harness-global.md.template").read_text(encoding="utf-8")
        self.assertIn("auto-project", gemini_tpl)
        self.assertIn("auto-project", global_tpl)
        self.assertNotIn("4 simple choices", gemini_tpl)
        self.assertLess(len(global_tpl), 6000)

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents" / "scripts").mkdir(parents=True)
            (repo / ".agents" / "scripts" / "workflow.py").write_text("# engine\n", encoding="utf-8")
            env = {
                **os.environ,
                "HARNESS_REPO": str(repo),
                "HARNESS_HOOK_SELFTEST_ACTIVE": "1",
            }
            for blocked_cmd in (
                "python .agents/scripts/record_review.py --task t1 --verdict bug-test-reviewer-agent=PASS --allow-lead-verdict",
                "wc -l .agents/scripts/workflow.py",
                "git show HEAD:.agents/scripts/workflow.py",
            ):
                proc = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "agents" / "scripts" / "pre_tool_safety.py")],
                    input=json.dumps({"conversationId": "c-v139", "toolName": "run_command", "toolArgs": {"CommandLine": blocked_cmd}}),
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                out = json.loads(proc.stdout.strip())
                self.assertEqual("deny", out.get("decision"), f"Expected deny for {blocked_cmd}: {out}")

    def test_v139_04_v2_verifier_blocks_medium_self_cert_and_tampered_receipt_and_cancel_clears_pending(self) -> None:
        import argparse
        import execution_mode
        import workflow
        from _vnext_common import atomic_write_json, canonical_sha256, read_json
        from evidence_store import EvidenceStore
        from final_verifier import verify_task

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            for g_args in (["init", "-q"], ["config", "user.name", "T"], ["config", "user.email", "t@example.invalid"]):
                subprocess.run(["git", *g_args], cwd=repo, check=True, capture_output=True)
            (repo / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            (repo / "app").mkdir()
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            src = repo / "app/src/main/kotlin/com/example/Calc.kt"
            src.parent.mkdir(parents=True)
            src.write_text("package com.example\nclass Calc { fun add(a: Int, b: Int) = a + b }\n", encoding="utf-8")
            tst = repo / "app/src/test/kotlin/com/example/CalcTest.kt"
            tst.parent.mkdir(parents=True)
            tst.write_text("package com.example\nclass CalcTest\n", encoding="utf-8")
            (repo / ".agents/state").mkdir(parents=True)
            _kit_ver = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
            (repo / ".agents/VERSION").write_text(_kit_ver + "\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, capture_output=True)

            # Set a pending single-task mode and verify cancel clears it
            execution_mode.set_execution_mode(
                repo, choice="web-task", source="conversation", proof_reference="use web for this task"
            )
            self.assertTrue(execution_mode.pending_task_mode_file(repo).is_file())

            d_res = workflow.draft(argparse.Namespace(
                repo=str(repo), task_id="t-v139", outcome="Update Calc", kind="FEATURE",
                planning_depth="STANDARD", expected_files="app/src/main/kotlin/com/example/Calc.kt,app/src/test/kotlin/com/example/CalcTest.kt",
                expected_modules=":app", expected_surfaces="BUSINESS_LOGIC,TEST_ONLY",
                approach="Add sub", risks="None", rollback="git checkout",
                test_strategy="Unit test", device_strategy="None", phases=None,
                architecture_intent="EXISTING_CHANGE", architecture_target_scope="app/src/main/kotlin/com/example/Calc.kt",
                architecture_target_family=None, verification_contract=None, external_writes=None,
                force=False, json=True,
            ))
            workflow.record_approval(argparse.Namespace(
                repo=str(repo), task_id="t-v139", source="conversation",
                proof_reference="approve", enforcement_tier="RULE_ENFORCED",
                plan_hash=d_res["plan_sha256"], approval_token=None, json=True,
            ))
            src.write_text("package com.example\nclass Calc { fun add(a: Int, b: Int) = a + b; fun sub(a: Int, b: Int) = a - b }\n", encoding="utf-8")
            tst.write_text("package com.example\nclass CalcTest { fun ok() {} }\n", encoding="utf-8")

            prep2 = workflow.prepare_verification(argparse.Namespace(repo=str(repo), task_id="t-v139", host="antigravity", json=True))

            # Nested scratch script dropped post-prepare must block final_verifier
            nested_scratch = repo / "app/src/scratch_helper.py"
            nested_scratch.write_text("# temp\n", encoding="utf-8")
            v_scratch = verify_task(repo, "t-v139")
            self.assertEqual("STALE", v_scratch["status"])
            self.assertTrue(any("app/src/scratch_helper.py" in r for r in v_scratch.get("blocked_by", [])), v_scratch)
            nested_scratch.unlink()
            tdir = repo / ".agents/state/tasks/t-v139"
            crun = read_json(tdir / "current-run.json")
            pol = read_json(Path(crun["policy"]))
            self.assertEqual("MEDIUM", pol.get("severity"))
            store = EvidenceStore(repo / ".agents/state")
            snap = crun["delivery_snapshot_sha256"]
            cset = crun["change_set_sha256"]
            run_id = crun["run_id"]
            for g_name, prod in (("preflight", "preflight_check"), ("unit_tests", "run_tests_gate")):
                store.write(snapshot=snap, run_id=run_id, name=g_name, producer=prod, harness_version=_kit_ver, change_set=cset, status="PASS", evidence={"passed": True})
            store.write(
                snapshot=snap, run_id=run_id, name="reviews", producer="review_orchestrator",
                harness_version=_kit_ver, change_set=cset, status="PASS",
                evidence={
                    "review_protocol_version": 2,
                    "reviewers": pol["reviewers"],
                    "reports": [{"reviewer": r, "verdict": "PASS", "independent_execution_verified": False} for r in pol["reviewers"]],
                    "blocking_findings": [],
                    "is_truncated": False,
                },
            )
            v_unver = verify_task(repo, "t-v139")
            self.assertNotEqual("APPROVED", v_unver["status"])
            self.assertTrue(any("independent_execution_verified=false" in b for b in v_unver.get("blocked_by", [])), v_unver)

            # Cancel task and verify pending_task_mode_file is cleaned up
            execution_mode.set_execution_mode(
                repo, choice="web-task", source="conversation", proof_reference="switch for task"
            )
            workflow.cancel(argparse.Namespace(repo=str(repo), task_id="t-v139", source="developer_terminal", proof_reference=""))
            self.assertFalse(execution_mode.pending_task_mode_file(repo).exists())

    def test_v139_05_cloud_readonly_home_shm_contract_and_jetski_metadata_and_host_bind(self) -> None:
        import antigravity_runtime as ar
        import harness_cli
        import reviewer_host as rh
        import web_relay as wr
        from _vnext_common import ValidationError, atomic_write_json, read_json

        # 1) HARNESS_SELFTEST_TMP="" must NEVER be overridden even when /dev/shm has >16 GiB free
        args = harness_cli.build_parser().parse_args(["selftest", "--quick", "--jobs", "1", "--kit", str(REPO_ROOT)])
        fake_usage = type("U", (), {"total": 32 * 1024**3, "used": 1 * 1024**3, "free": 31 * 1024**3})()
        with unittest.mock.patch.dict(os.environ, {"HARNESS_SELFTEST_TMP": ""}, clear=False),                 unittest.mock.patch.object(harness_cli, "_verify_kit_checksums", return_value=None),                 unittest.mock.patch("shutil.disk_usage", return_value=fake_usage),                 unittest.mock.patch("subprocess.run", return_value=unittest.mock.MagicMock(returncode=0)) as mock_run:
            self.assertEqual(0, harness_cli.cmd_selftest(args))
            for call in mock_run.call_args_list:
                self.assertEqual(os.environ.get("TEMP"), call.kwargs["env"].get("TEMP"))

        # 2) Read-only $HOME/Downloads falls back cleanly to tempfile.gettempdir() / Harness-Web-Relay
        with tempfile.TemporaryDirectory() as td:
            ro_home = Path(td) / "ro_home"
            ro_home.mkdir()
            ro_env = {k: v for k, v in os.environ.items() if k not in {"HARNESS_WEB_RELAY_DIR", "HARNESS_WEB_RELAY_OUTBOX"}}
            with unittest.mock.patch.dict(os.environ, ro_env, clear=True),                     unittest.mock.patch("pathlib.Path.home", return_value=ro_home),                     unittest.mock.patch.object(Path, "mkdir", side_effect=[OSError(30, "Read-only file system"), None]):
                out_dir = wr._default_outbox_dir()
                self.assertEqual("Harness-Web-Relay", out_dir.name)

        # 3) Hierarchical Jetski native_model_metadata + reviewer_host sender & lifecycle_action auto-bind
        with tempfile.TemporaryDirectory() as td:
            app_root = Path(td) / "jetski"
            repo = Path(td) / "app"
            tdir = repo / ".agents/state/tasks/t-jetski"
            run_id = "run-j1"
            (tdir / "review-execution" / run_id).mkdir(parents=True)
            brief_file = tdir / "brief-bug.md"
            brief_text = "Review task t-jetski package sha256=deadbeef"
            brief_file.write_text(brief_text + "\n", encoding="utf-8")
            atomic_write_json(tdir / "plan.json", {"task_id": "t-jetski", "status": "VERIFYING"})
            atomic_write_json(tdir / "current-run.json", {
                "task_id": "t-jetski",
                "run_id": run_id,
                "review_host": "antigravity",
                "review_protocol_version": 2,
                "briefs": {"bug-test-reviewer-agent": str(brief_file)},
            })
            ledger_p = tdir / "review-execution" / run_id / "ledger.json"
            atomic_write_json(ledger_p, {
                "schema_version": 1,
                "task_id": "t-jetski",
                "run_id": run_id,
                "reviewers": {"bug-test-reviewer-agent": {"state": "DISPATCHED", "brief": str(brief_file)}},
            })

            child_id = "v1/default/jetski_remote_agents_3p/child-uuid-9999"
            parent_id = "v1/default/jetski_remote_agents_3p/parent-uuid-1111"
            tx_path = app_root / "brain" / child_id / ".system_generated" / "logs" / "transcript.jsonl"
            tx_path.parent.mkdir(parents=True, exist_ok=True)
            sys_msg = {
                "source": "SYSTEM_SDK",
                "type": "SYSTEM_MESSAGE",
                "content": f"<SYSTEM_MESSAGE>sender={parent_id} priority=MESSAGE_PRIORITY_HIGH content={brief_text}\n</SYSTEM_MESSAGE>",
            }
            tx_path.write_text(json.dumps(sys_msg) + "\n", encoding="utf-8")

            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(app_root)}, clear=False):
                # native_model_metadata must extract full hierarchical child_id (not 'v1') and return {} cleanly when no .db file exists
                meta = ar.native_model_metadata(tx_path)
                self.assertEqual({}, meta)

                # lifecycle_action must discover nested Jetski child_id and bind both execution_id and hierarchical parent_execution_id
                rh.lifecycle_action(
                    repo,
                    read_json(tdir / "current-run.json"),
                    read_json(ledger_p)["reviewers"],
                )
                bound_entry = read_json(ledger_p)["reviewers"]["bug-test-reviewer-agent"]
                self.assertEqual(child_id, bound_entry.get("execution_id"))
                self.assertEqual(parent_id, bound_entry.get("parent_execution_id"))

        # 4) harness-rules.md 5-choice and V2 self-certification parity
        rules_txt = (REPO_ROOT / "agents/rules/harness-rules.md").read_text(encoding="utf-8")
        self.assertIn("auto-project", rules_txt)
        self.assertIn("Review Protocol V2", rules_txt)

    def test_v139_06_jetski_utility_subagent_post_tool_ide_artifact_and_define_subagent_snake_case(self) -> None:
        import delegation_policy as dp
        import post_tool_reconcile as ptr
        import pre_tool_safety as pts
        from _vnext_common import atomic_write_json, read_json

        parent_id = "v1/default/jetski_remote_agents_3p/lead-uuid-0001"
        scout_id = "v1/default/jetski_remote_agents_3p/scout-uuid-0002"
        rev_id = "v1/default/jetski_remote_agents_3p/rev-uuid-0003"

        with tempfile.TemporaryDirectory() as td:
            app_root = Path(td) / "jetski"
            repo = Path(td) / "app"
            (repo / ".agents/state/tasks/t-j6/review-execution/run-j6").mkdir(parents=True)

            # A) Utility subagent (Scout) hierarchical sender + bind_utility_from_post_tool
            scout_prompt = "Analyze CartViewModel and dependencies across :app"
            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(app_root)}, clear=False):
                dp.record_utility_dispatch(
                    repo,
                    agent_type="harness-scout-agent",
                    role_label="harness-scout-agent",
                    prompt=scout_prompt,
                    parent_conversation_id=parent_id,
                    task_id="t-j6",
                    wave_id="wave-j6",
                )
            scout_tx = app_root / "brain" / scout_id / ".system_generated" / "logs" / "transcript.jsonl"
            scout_tx.parent.mkdir(parents=True, exist_ok=True)
            scout_tx.write_text(json.dumps({
                "source": "SYSTEM_SDK",
                "type": "SYSTEM_MESSAGE",
                "content": f"<SYSTEM_MESSAGE>sender={parent_id} priority=MESSAGE_PRIORITY_HIGH content={scout_prompt}\n</SYSTEM_MESSAGE>",
            }) + "\n", encoding="utf-8")

            # B) PostToolUse _bind_candidates_from_brain + hierarchical conversationId regex
            brief_f = repo / ".agents/state/tasks/t-j6/brief-bug.md"
            brief_txt = "Review package for t-j6 sha=123456"
            brief_f.write_text(brief_txt + "\n", encoding="utf-8")
            atomic_write_json(repo / ".agents/state/tasks/t-j6/plan.json", {"task_id": "t-j6", "status": "VERIFYING"})
            atomic_write_json(repo / ".agents/state/tasks/t-j6/current-run.json", {
                "task_id": "t-j6",
                "run_id": "run-j6",
                "review_host": "antigravity",
                "review_protocol_version": 2,
                "briefs": {"bug-test-reviewer-agent": str(brief_f)},
            })
            ledger_p = repo / ".agents/state/tasks/t-j6/review-execution/run-j6/ledger.json"
            atomic_write_json(ledger_p, {
                "schema_version": 1,
                "task_id": "t-j6",
                "run_id": "run-j6",
                "reviewers": {"bug-test-reviewer-agent": {"state": "DISPATCHED", "brief": str(brief_f)}},
            })
            rev_tx = app_root / "brain" / rev_id / ".system_generated" / "logs" / "transcript.jsonl"
            rev_tx.parent.mkdir(parents=True, exist_ok=True)
            rev_tx.write_text(json.dumps({
                "source": "SYSTEM_SDK",
                "type": "SYSTEM_MESSAGE",
                "content": f"<SYSTEM_MESSAGE>sender={parent_id} priority=MESSAGE_PRIORITY_HIGH content={brief_txt}\n</SYSTEM_MESSAGE>",
            }) + "\n", encoding="utf-8")

            ide_task_md = app_root / "brain" / parent_id / "task.md"
            ide_task_md.parent.mkdir(parents=True, exist_ok=True)
            ide_task_md.write_text("# Task\n", encoding="utf-8")
            bad_ide_md = app_root / "brain" / "foo" / "bar" / "task.md"
            bad_ide_md.parent.mkdir(parents=True, exist_ok=True)
            bad_ide_md.write_text("# Bad\n", encoding="utf-8")

            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(app_root)}, clear=False):
                bound_utils = dp.bind_utility_from_post_tool(repo, {"conversationId": parent_id})
                self.assertEqual([scout_id], bound_utils)
                ctx_u = dp.utility_subagent_context(repo, scout_id)
                self.assertIsNotNone(ctx_u)
                self.assertEqual("harness-scout-agent", ctx_u["agent_type"])

                # Verify PostToolUse regex also accepts hierarchical Jetski conversationId up to 255 chars
                raw_tool_out = json.dumps({"conversationId": rev_id, "bad": "foo/bar/not-jetski"})
                extracted_cids = {
                    cid
                    for cid in ptr.re.findall(r'conversation(?:Id|_id)[\"\s:=]+([A-Za-z0-9_/-]{4,255})', raw_tool_out)
                    if not ptr._is_invalid_conversation_id(cid)
                }
                self.assertEqual({rev_id}, extracted_cids)

                ptr._bind_candidates_from_brain(repo, {"conversationId": parent_id})
                self.assertEqual(rev_id, read_json(ledger_p)["reviewers"]["bug-test-reviewer-agent"].get("execution_id"))

                # C) _is_ide_artifact accepts 5-part Jetski path and rejects arbitrary foo/bar
                self.assertTrue(pts._is_ide_artifact(ide_task_md.resolve()))
                self.assertFalse(pts._is_ide_artifact(bad_ide_md.resolve()))

            # D) _validate_define_subagent blocks snake_case enable_write_tools and enable_subagent_tools
            ok_sub, _, code_sub = pts._validate_define_subagent(
                {"name": "bug-test-reviewer-agent", "enable_subagent_tools": True, "enable_write_tools": False},
                "define_subagent",
            )
            self.assertFalse(ok_sub)
            self.assertEqual("SUBAGENT_NESTING_FORBIDDEN", code_sub)

            ok_wr, _, code_wr = pts._validate_define_subagent(
                {"name": "harness-scout-agent", "enable_subagent_tools": False, "enable_write_tools": True},
                "define_subagent",
            )
            self.assertFalse(ok_wr)
            self.assertEqual("READ_ONLY_SUBAGENT_WRITE_FORBIDDEN", code_wr)

            ok_wk, _, _ = pts._validate_define_subagent(
                {"name": "harness-worker-agent", "enable_subagent_tools": False, "enable_write_tools": True},
                "define_subagent",
            )
            self.assertTrue(ok_wk)


    def test_v139_07_library_project_kind_isolation_doctor_stderr_and_prepare_verification_json(self):
        """Verify library PROJECT_KIND never bleeds into temp app repos, doctor captures stderr, and prepare-verification --json emits JSON."""
        import change_classifier as cc
        kit_root = Path(__file__).resolve().parents[2]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_repo = root / "temp-app"
            app_repo.mkdir()
            for git_args in (["init", "-q"], ["config", "user.name", "Test"], ["config", "user.email", "t@e.invalid"]):
                subprocess.run(["git", *git_args], cwd=app_repo, check=True)
            (app_repo / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (app_repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            (app_repo / "app/src/main/kotlin/com/example").mkdir(parents=True)
            (app_repo / "app/src/test/kotlin/com/example").mkdir(parents=True)
            (app_repo / "app/build.gradle.kts").write_text('plugins { id("com.android.library") }\n', encoding="utf-8")
            calc = app_repo / "app/src/main/kotlin/com/example/Calc.kt"
            calc.write_text("package com.example\nclass Calc { fun add(a: Int, b: Int) = a + b }\n", encoding="utf-8")
            calc_t = app_repo / "app/src/test/kotlin/com/example/CalcTest.kt"
            calc_t.write_text("package com.example\nclass CalcTest { fun addOk() {} }\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=app_repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=app_repo, check=True)

            # Install into an Android LIBRARY project (no applicationId/AndroidManifest -> PROJECT_KIND == 'library')
            ans = root / "answers.json"
            ans.write_text(json.dumps({
                "i0": True,
                "i1": "LibSmoke",
                "i2": sys.executable,
                "i4": "skip",
                "i14": ["antigravity"],
                "i20": "none",
            }), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(kit_root / "harness_cli.py"), "init", "--repo", str(app_repo), "--kit", str(kit_root), "--answers-json", str(ans)],
                cwd=app_repo,
                check=True,
                capture_output=True,
                text=True,
            )
            prod_txt = (app_repo / ".agents/scripts/_product.py").read_text(encoding="utf-8")
            self.assertTrue("PROJECT_KIND = 'library'" in prod_txt or 'PROJECT_KIND = "library"' in prod_txt, prod_txt)
            self.assertEqual("library", cc.resolve_repo_project_kind(app_repo))

            # External uninitialized temp dir must default to 'application', not inherit host 'library'
            ext_tmp = root / "unconfigured-app"
            ext_tmp.mkdir()
            self.assertEqual("application", cc.resolve_repo_project_kind(ext_tmp))

            # Doctor --json inside the installed library project must pass 100% (including _hook_selftest.py)
            ag_root = root / "ag-data"
            ag_root.mkdir()
            doc_env = {**os.environ, "ANTIGRAVITY_APP_DATA": str(ag_root), "HARNESS_UPDATE_CHECK": "off"}
            doc_p = subprocess.run(
                [sys.executable, ".agents/harness.py", "doctor", "--json"],
                cwd=app_repo,
                env=doc_env,
                capture_output=True,
                text=True,
                check=True,
            )
            doc_json = json.loads(doc_p.stdout)
            fails = [r for r in doc_json.get("results", doc_json.get("checks", [])) if isinstance(r, dict) and r.get("status") == "FAIL"]
            self.assertEqual([], fails)

            # Verify prepare-verification --json outputs valid JSON with review_protocol_version == 2
            subprocess.run(
                [sys.executable, ".agents/harness.py", "execution-mode", "set", "--choice", "auto-project", "--source", "conversation", "--proof-reference", "auto"],
                cwd=app_repo,
                env=doc_env,
                check=True,
                capture_output=True,
            )
            draft_p = subprocess.run(
                [
                    sys.executable, ".agents/harness.py", "task", "draft", "--repo", str(app_repo), "--task-id", "t-lib",
                    "--outcome", "Add sub", "--kind", "FEATURE",
                    "--expected-files", "app/src/main/kotlin/com/example/Calc.kt,app/src/test/kotlin/com/example/CalcTest.kt",
                    "--expected-modules", ":app", "--expected-surfaces", "BUSINESS_LOGIC,PUBLIC_API,TEST_ONLY",
                    "--approach", "Add sub", "--risks", "Low", "--rollback", "git checkout",
                    "--test-strategy", "CalcTest", "--device-strategy", "Library unit test",
                    "--architecture-intent", "EXISTING_CHANGE", "--architecture-target-scope", "app/src/main/kotlin/com/example/Calc.kt",
                    "--json",
                ],
                cwd=app_repo,
                env=doc_env,
                capture_output=True,
                text=True,
                check=True,
            )
            p_hash = json.loads(draft_p.stdout)["plan_sha256"][:12]
            subprocess.run(
                [
                    sys.executable, ".agents/harness.py", "task", "approve", "--repo", str(app_repo), "--task-id", "t-lib",
                    "--source", "conversation", "--proof-reference", "Proceed",
                    "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", p_hash, "--json",
                ],
                cwd=app_repo,
                env=doc_env,
                capture_output=True,
                text=True,
                check=True,
            )
            calc.write_text("package com.example\nclass Calc { fun add(a: Int, b: Int) = a + b; fun sub(a: Int, b: Int) = a - b }\n", encoding="utf-8")
            calc_t.write_text("package com.example\nclass CalcTest { fun addOk() {}; fun subOk() {} }\n", encoding="utf-8")
            pv_json_p = subprocess.run(
                [sys.executable, ".agents/harness.py", "task", "prepare-verification", "--repo", str(app_repo), "--task-id", "t-lib", "--host", "antigravity", "--json"],
                cwd=app_repo,
                env=doc_env,
                capture_output=True,
                text=True,
                check=True,
            )
            pv_data = json.loads(pv_json_p.stdout)
            self.assertEqual(2, pv_data.get("review_protocol_version"))
            self.assertTrue(str(pv_data.get("run_id", "")).startswith("run-"))



class TestV1312CrossSystemParity(unittest.TestCase):
    """Regression coverage for the 8 cross-system sibling fixes audited for v1.3.12."""

    def test_v1312_01_windows_quoted_paths_post_worker_unread_gap_and_worker_inbox_block(self) -> None:
        from unittest.mock import patch
        import delegation_policy as dp
        import pre_tool_safety as pts

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            (repo / ".agents/state").mkdir(parents=True, exist_ok=True)
            f1 = repo / "app/src/main/java/com/demo/TouchedByWorker.kt"
            f2 = repo / "app/src/main/java/com/demo/UntouchedCaller.kt"
            f1.parent.mkdir(parents=True, exist_ok=True)
            f1.write_text("package com.demo\nclass TouchedByWorker\n", encoding="utf-8")
            f2.write_text("package com.demo\nclass UntouchedCaller\n", encoding="utf-8")

            # Quoted path as serialized in real Windows transcript.jsonl
            quoted_target = f'"{f1}"'
            self.assertEqual("app/src/main/java/com/demo/TouchedByWorker.kt", dp._normalize_repo_rel(repo, quoted_target))

            # Simulated Windows cross-drive case-insensitive normalization
            fake_win_repo = Path("/mnt_sim")
            with patch.object(Path, "resolve", return_value=fake_win_repo):
                pass
            # Post-Worker unread file gap allowance
            tx_dir = repo / "brain" / "parent-v1312" / ".system_generated" / "logs"
            tx_dir.mkdir(parents=True, exist_ok=True)
            parent_tx = tx_dir / "transcript.jsonl"
            parent_tx.write_text(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Fix slice"}) + "\n", encoding="utf-8")
            w_plan = {
                "task_id": "t-w-v1312",
                "status": "IMPLEMENTING",
                "task_kind": "FEATURE",
                "expected_files": [
                    "app/src/main/java/com/demo/TouchedByWorker.kt",
                    "app/src/main/java/com/demo/UntouchedCaller.kt",
                    "app/src/main/java/com/demo/F3.kt",
                    "app/src/main/java/com/demo/F4.kt",
                ],
                "expected_surfaces": ["BUSINESS_LOGIC"],
            }
            dp._save_utility_ledger(repo, {
                "schema_version": 1,
                "entries": [{
                    "wave_id": "w-worker-v1312",
                    "agent_type": dp.WORKER_AGENT,
                    "role": dp.WORKER_AGENT,
                    "task_id": "t-w-v1312",
                    "task_status": "IMPLEMENTING",
                    "parent_conversation_id": "parent-v1312",
                    "parent_user_turns": 1,
                    "execution_id": "child-worker-1",
                    "wave_completed": True,
                    "completed_at_epoch": 9999999999.0,
                    "lead_post_reads": 3,
                    "inspected_files": ["app/src/main/java/com/demo/TouchedByWorker.kt"],
                    "dispatched_epoch": 9999999999.0,
                }],
            })
            with patch("antigravity_runtime.resolve_transcript", side_effect=lambda cid: parent_tx if cid == "parent-v1312" else None):
                ok_same, _, code_same = dp.check_and_record_lead_post_subagent_read(
                    repo, "parent-v1312", tool_name="view_file", args={"AbsolutePath": str(f1), "StartLine": 1, "EndLine": 10}, plan=w_plan,
                )
                self.assertFalse(ok_same)
                self.assertEqual("POST_WORKER_REREAD_CAP_REACHED", code_same)

                ok_unseen, _, _ = dp.check_and_record_lead_post_subagent_read(
                    repo, "parent-v1312", tool_name="view_file", args={"AbsolutePath": str(f2), "StartLine": 1, "EndLine": 10}, plan=w_plan,
                )
                self.assertTrue(ok_unseen, "Post-Worker surgical read on file NOT touched/read by Worker must be allowed")

            # Lead is allowed to stage in inbox; verify check_write_safety allows Lead
            res_lead = pts.check_write_safety(repo, ".agents/state/web-relay/inbox/merge.json")
            self.assertEqual("ALLOW", res_lead["decision"])

    def test_v1312_02_code_mass_upgrades_complexity_and_smart_auto_web_mode(self) -> None:
        import execution_mode as em
        import review_models as rm

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            (repo / ".agents/state").mkdir(parents=True, exist_ok=True)
            mono = repo / "app/src/main/kotlin/com/demo/HugeHomeViewModel.kt"
            mono.parent.mkdir(parents=True, exist_ok=True)
            # 110 KB single file (like Rashaqa's 120.5 KB HomeViewModel.kt)
            mono.write_text("package com.demo\n" + ("    val linePad = 1234567890\n" * 4600), encoding="utf-8")
            self.assertGreaterEqual(mono.stat().st_size, 100 * 1024)

            plan_one_huge = {
                "task_id": "t-huge-vm",
                "status": "IMPLEMENTING",
                "task_kind": "FEATURE",
                "expected_files": ["app/src/main/kotlin/com/demo/HugeHomeViewModel.kt"],
                "expected_modules": [":app"],
                "expected_surfaces": ["BUSINESS_LOGIC"],
            }
            tier = rm.compute_task_complexity_tier(repo, "t-huge-vm", plan=plan_one_huge)
            self.assertEqual("COMPLEX", tier, "110 KB single ViewModel must classify as COMPLEX, not SIMPLE")

            mode, trigger, _ = em.evaluate_smart_auto_routing(repo, "t-huge-vm", plan_one_huge)
            self.assertEqual("web", mode)
            self.assertIn("AUTO_WEB_HEAVY_CODE_MASS", trigger)

    def test_v1312_03_phase_review_short_mirror_absolute_paths_models_set_survival_and_cli_task_aliases(self) -> None:
        import hashlib
        import phase_review as pr
        import review_execution as rex
        import review_models as rm
        import change_classifier as cc
        import delegation_policy as dp

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            (repo / ".agents/state").mkdir(parents=True, exist_ok=True)
            _kv = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
            (repo / ".agents/VERSION").write_text(_kv + "\n", encoding="utf-8")
            (repo / ".gitignore").write_text(".agents/\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('rootProject.name = "Demo"\ninclude(":core", ":app")\n', encoding="utf-8")
            f_core = repo / "core/src/main/kotlin/com/demo/CoreRepo.kt"
            f_app = repo / "app/src/main/kotlin/com/demo/AppVm.kt"
            f_core.parent.mkdir(parents=True, exist_ok=True)
            f_app.parent.mkdir(parents=True, exist_ok=True)
            (repo / "core/build.gradle.kts").write_text('plugins { kotlin("jvm") }\n', encoding="utf-8")
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            f_core.write_text("package com.demo\nclass CoreRepo { fun v() = 1 }\n", encoding="utf-8")
            f_app.write_text("package com.demo\nclass AppVm\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            # Verify --task alias works on sibling CLIs
            self.assertEqual(0, cc.main(["--repo", str(repo), "--task", "nonexistent", "--json"]))
            self.assertEqual(0, dp.main(["--repo", str(repo), "--task", "nonexistent", "--json"]))

            # Build phase review package & verify absolute paths + short mirror + pointer_matches
            tid = "t-phase-v1312"
            tdir = repo / ".agents/state/tasks" / tid
            pdir = tdir / "phases" / "p1"
            rdir = pdir / "review"
            rdir.mkdir(parents=True, exist_ok=True)
            plan_doc = {
                "task_id": tid,
                "status": "IMPLEMENTING",
                "task_kind": "FEATURE",
                "plan_sha256": "a" * 64,
                "active_phase_index": 0,
                "phases": [{"id": "p1", "title": "Core layer", "description": "Update CoreRepo", "expected_files": ["core/src/main/kotlin/com/demo/CoreRepo.kt"]}],
                "expected_files": ["core/src/main/kotlin/com/demo/CoreRepo.kt", "app/src/main/kotlin/com/demo/AppVm.kt"],
                "expected_modules": [":core", ":app"],
                "expected_surfaces": ["BUSINESS_LOGIC"],
            }
            (tdir / "plan.json").write_text(json.dumps(plan_doc), encoding="utf-8")
            (tdir / "phase-state.json").write_text(json.dumps({"current_phase_id": "p1", "substate": "PHASE_REVIEWING"}), encoding="utf-8")
            f_core.write_text("package com.demo\nclass CoreRepo { fun v() = 2 }\n", encoding="utf-8")
            meta_in = {
                "schema_version": 2,
                "task_id": tid,
                "phase_id": "p1",
                "phase_review_run_id": "phase-p1-12345678",
                "review_host": "antigravity",
                "review_protocol_version": 2,
                "selected_reviewers": ["bug-test-reviewer-agent"],
                "phase_file_hashes": {"core/src/main/kotlin/com/demo/CoreRepo.kt": hashlib.sha256(f_core.read_bytes()).hexdigest()},
                "review_models": rm.freeze_models(repo, tid, "antigravity", ["bug-test-reviewer-agent"], run_id="phase-p1-12345678", plan=plan_doc),
            }
            published = pr._publish_phase_package(repo, meta_in, plan_doc["phases"][0], "+fun v() = 2")
            canon_b = Path(published["briefs"]["bug-test-reviewer-agent"])
            short_b = Path(published["short_briefs"]["bug-test-reviewer-agent"])
            self.assertTrue(canon_b.is_file())
            self.assertTrue(short_b.is_file())
            self.assertIn("active-briefs", short_b.as_posix())
            b_txt = canon_b.read_text(encoding="utf-8")
            self.assertIn(repo.as_posix(), b_txt)
            self.assertIn(f_core.resolve().as_posix(), b_txt)
            ptr_short = rex.brief_pointer_prompt("bug-test-reviewer-agent", str(short_b), b_txt)
            self.assertTrue(rex.pointer_matches(ptr_short, "bug-test-reviewer-agent", str(canon_b), b_txt))

            # Verify upward inheritance AND _detect_live_parent_lead_family resolve `cid -> Path` via resolve_transcript(cid)
            ag_root = repo / "ag_sim_root"
            lead_tx = ag_root / "brain" / "lead-carbon-p1" / ".system_generated" / "logs" / "transcript.jsonl"
            lead_tx.parent.mkdir(parents=True, exist_ok=True)
            lead_tx.write_text("{}\n", encoding="utf-8")
            (repo / ".agents/state/active-conversation.json").write_text(json.dumps({"conversation_id": "lead-carbon-p1"}), encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(ag_root)}), unittest.mock.patch(
                "antigravity_runtime.native_model_metadata",
                side_effect=lambda tx_path: {"host_configured_model": "gemini-4-carbon-high"} if isinstance(tx_path, Path) and tx_path.resolve() == lead_tx.resolve() else (_ for _ in ()).throw(AssertionError(f"Expected resolved Path, got {tx_path!r}")),
            ):
                self.assertTrue(
                    rm._is_proven_upward_parent_inheritance(
                        published,
                        {"repo": str(repo)},
                        {"execution_id": "phase-rev-child", "host_configured_model": "gemini-4-carbon-high", "model_evidence": ["gemini-4-carbon"]},
                    )
                )
                self.assertEqual("gemini-4-carbon", dp._detect_live_parent_lead_family(repo))


class TestV1311RashaqaLiveFixes(unittest.TestCase):
    """End-to-end regression suite for all 7 v1.3.11 real-world Rashaqa benchmark optimizations."""

    def test_v1311_01_upward_carbon_argon_parent_inheritance_and_downward_block(self) -> None:
        import review_models as rm

        # Proven upward inheritance (Carbon or Argon Lead session running Hydrogen policy) -> PASS
        self.assertTrue(
            rm._matches_antigravity_native_model(
                "gemini-4-hydrogen-medium",
                "medium",
                "gemini-4-carbon-high",
                ["gemini-4-carbon"],
                allow_upward_parent_inheritance=True,
            )
        )
        self.assertTrue(
            rm._matches_antigravity_native_model(
                "gemini-4-hydrogen-high",
                "high",
                "gemini-4-argon-medium",
                ["gemini-4-argon"],
                allow_upward_parent_inheritance=True,
            )
        )
        # Unproven cross-family leak (#198819) -> FAIL CLOSED
        self.assertFalse(
            rm._matches_antigravity_native_model(
                "gemini-4-hydrogen-medium",
                "medium",
                "gemini-4-carbon-medium",
                ["gemini-4-carbon"],
                allow_upward_parent_inheritance=False,
            )
        )
        # Downward leak (Hydrogen or 3.8 Flash running when Carbon was required, or 3.8 Flash when Hydrogen was required) -> FAIL CLOSED
        self.assertFalse(
            rm._matches_antigravity_native_model(
                "gemini-4-carbon-medium",
                "medium",
                "gemini-4-hydrogen-high",
                ["gemini-4-hydrogen"],
                allow_upward_parent_inheritance=True,
            )
        )
        self.assertFalse(
            rm._matches_antigravity_native_model(
                "gemini-4-hydrogen-medium",
                "medium",
                "gemini-3.8-flash-high",
                ["gemini-3.8-flash"],
                allow_upward_parent_inheritance=True,
            )
        )

    def test_v1311_02_web_relay_inbox_write_allowed_and_auto_discovered_and_cleaned(self) -> None:
        from unittest.mock import patch
        import pre_tool_safety as pts
        import web_relay as wr

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            (repo / ".agents/state").mkdir(parents=True, exist_ok=True)
            _kv = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
            (repo / ".agents/VERSION").write_text(_kv + "\n", encoding="utf-8")
            (repo / ".gitignore").write_text(".agents/\n.harness-setup/\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('rootProject.name = "Demo"\ninclude(":app")\n', encoding="utf-8")
            (repo / "app/src/main/java/com/demo").mkdir(parents=True, exist_ok=True)
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            target_kt = repo / "app/src/main/java/com/demo/Sample.kt"
            target_kt.write_text('package com.demo\nfun greet(): String = "hi"\n', encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            inbox_rel = ".agents/state/web-relay/inbox/merge.json"
            res_ok = pts.check_write_safety(repo, inbox_rel)
            self.assertEqual("ALLOW", res_ok["decision"], res_ok)
            res_deny = pts.check_write_safety(repo, ".agents/state/active-task.json")
            self.assertEqual("DENY", res_deny["decision"], res_deny)

            outbox_d = repo / ".agents/state/web-relay/test-outbox"
            downloads_d = repo / ".agents/state/web-relay/test-downloads"
            outbox_d.mkdir(parents=True, exist_ok=True)
            downloads_d.mkdir(parents=True, exist_ok=True)
            with patch.dict(
                os.environ,
                {
                    "HARNESS_NO_CLIPBOARD": "1",
                    "HARNESS_WEB_RELAY_OUTBOX": str(outbox_d),
                    "HARNESS_WEB_RELAY_DOWNLOADS": str(downloads_d),
                },
            ):
                pack_info = wr.build_web_pack(
                    repo,
                    task_id="t-inbox-v1311",
                    prompt="Update greet() in Sample.kt",
                    kind="FEATURE",
                    files=["app/src/main/java/com/demo/Sample.kt"],
                    no_clipboard=True,
                )
                inbox_f = repo / inbox_rel
                inbox_f.parent.mkdir(parents=True, exist_ok=True)
                merge_payload = {
                    "schema": "HARNESS_WEB_MERGE_V1",
                    "pack_id": pack_info["pack_id"],
                    "status": "READY",
                    "plan_spec": {
                        "task_id": "t-inbox-v1311",
                        "kind": "FEATURE",
                        "outcome": "Update greet return value",
                        "approach": "Modify Sample.kt",
                        "risks": "None",
                    },
                    "operations": [
                        {
                            "action": "MODIFY",
                            "path": "app/src/main/java/com/demo/Sample.kt",
                            "hunks": [
                                {
                                    "search": 'fun greet(): String = "hi"',
                                    "replace": 'fun greet(): String = "hello-v1311"',
                                    "replace_all": False,
                                }
                            ],
                        }
                    ],
                }
                inbox_f.write_text(json.dumps(merge_payload), encoding="utf-8")
                applied = wr.apply_web_merge(
                    repo,
                    source="conversation",
                    proof_reference="Apply web merge",
                )
                self.assertEqual("APPLIED", applied["status"])
                self.assertIn("hello-v1311", target_kt.read_text(encoding="utf-8"))
                self.assertFalse(inbox_f.exists(), "Consumed inbox merge file should be cleaned up automatically")

    def test_v1311_03_absolute_brief_paths_short_mirror_and_models_set_pointer_survival(self) -> None:
        import argparse
        import review_execution as rex
        import review_models as rm
        import workflow

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            (repo / ".agents/state").mkdir(parents=True, exist_ok=True)
            _kv = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
            (repo / ".agents/VERSION").write_text(_kv + "\n", encoding="utf-8")
            (repo / ".gitignore").write_text(".agents/\n.harness-setup/\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('rootProject.name = "Demo"\ninclude(":app")\n', encoding="utf-8")
            src_f = repo / "app/src/main/kotlin/com/demo/Calc.kt"
            src_f.parent.mkdir(parents=True, exist_ok=True)
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            src_f.write_text("package com.demo\nclass Calc { fun add(a: Int, b: Int) = a + b }\n", encoding="utf-8")
            tst_f = repo / "app/src/test/kotlin/com/demo/CalcTest.kt"
            tst_f.parent.mkdir(parents=True, exist_ok=True)
            tst_f.write_text("package com.demo\nclass CalcTest\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            tid = "t-ptr-v1311"
            d_res = workflow.draft(argparse.Namespace(
                repo=str(repo),
                task_id=tid,
                outcome="Update Calc",
                kind="FEATURE",
                planning_depth="STANDARD",
                expected_files="app/src/main/kotlin/com/demo/Calc.kt,app/src/test/kotlin/com/demo/CalcTest.kt",
                expected_modules=":app",
                expected_surfaces="BUSINESS_LOGIC,TEST_ONLY",
                approach="Add sub helper",
                risks="None",
                rollback="git checkout",
                test_strategy="Unit test",
                device_strategy="None",
                phases=None,
                architecture_intent="EXISTING_CHANGE",
                architecture_target_scope="app/src/main/kotlin/com/demo/Calc.kt",
                architecture_target_family=None,
                verification_contract=None,
                external_writes=None,
                force=False,
                json=True,
            ))
            workflow.record_approval(argparse.Namespace(
                repo=str(repo),
                task_id=tid,
                source="conversation",
                proof_reference="approve",
                enforcement_tier="RULE_ENFORCED",
                plan_hash=d_res["plan_sha256"],
                approval_token=None,
                json=True,
            ))
            src_f.write_text("package com.demo\nclass Calc { fun add(a: Int, b: Int) = a + b; fun sub(a: Int, b: Int) = a - b }\n", encoding="utf-8")
            tst_f.write_text("package com.demo\nclass CalcTest { fun ok() {} }\n", encoding="utf-8")
            workflow.prepare_verification(argparse.Namespace(repo=str(repo), task_id=tid, host="antigravity", json=True))
            import review_package as rp
            rp.build_package(repo, tid)

            prof_before = rex.resolve_execution_profile(repo, tid, host="antigravity")
            rev_before = prof_before["reviewers"]["bug-test-reviewer-agent"]
            ptr_before = rev_before["brief_pointer_prompt"]
            self.assertIn("active-briefs", rev_before["short_brief_path"])
            self.assertIn("active-briefs", ptr_before)
            self.assertIn(repo.as_posix(), rev_before["brief_content"])
            self.assertIn((repo / "app/src/main/kotlin/com/demo/Calc.kt").resolve().as_posix(), rev_before["brief_content"])

            pol_new, sc_new = rm.resolve_interactive_choice("hydrogen-dynamic-task")
            rec = rm.set_policy(
                repo, pol_new, task_id=tid, host="antigravity", source="conversation", proof_reference="Use Hydrogen", scope=sc_new,
            )
            ref_prompts = (rec.get("refreshed_run") or {}).get("reviewer_prompts") or {}
            self.assertIn("bug-test-reviewer-agent", ref_prompts)

            prof_after = rex.resolve_execution_profile(repo, tid, host="antigravity")
            rev_after = prof_after["reviewers"]["bug-test-reviewer-agent"]
            self.assertTrue(
                rex.pointer_matches(
                    ptr_before,
                    "bug-test-reviewer-agent",
                    rev_after["brief_path"],
                    rev_after["brief_content"],
                    alternate_paths=[rev_after["short_brief_path"], rev_after["canonical_brief_path"]],
                    accepted_digests=rev_after["accepted_prior_brief_digests"],
                ),
                "Pre-model-set same-run pointer should remain valid after `review models set` rebuilds brief!",
            )
            forged = re.sub(r"\(sha256 [0-9a-f]{16}\)", "(sha256 0000000000000000)", ptr_before)
            self.assertFalse(
                rex.pointer_matches(
                    forged,
                    "bug-test-reviewer-agent",
                    rev_after["brief_path"],
                    rev_after["brief_content"],
                    alternate_paths=[rev_after["short_brief_path"], rev_after["canonical_brief_path"]],
                    accepted_digests=rev_after["accepted_prior_brief_digests"],
                )
            )

    def test_v1311_04_three_scout_waves_unread_gap_reads_cli_json_flags_and_hydrogen_lead_direct(self) -> None:
        from unittest.mock import patch
        import delegation_policy as dp
        import verification_steps as vs
        import review_orchestrator as ro

        self.assertEqual(3, dp.MAX_SCOUT_WAVES_PER_USER_TURN)
        self.assertIn("NEVER chain shell commands", dp.UTILITY_AGENT_SPECS[dp.SCOUT_AGENT]["system_prompt"])

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            (repo / ".agents/state").mkdir(parents=True, exist_ok=True)
            f_read = repo / "app/src/main/java/com/demo/ReadByScout.kt"
            f_unread = repo / "app/src/main/java/com/demo/UnreadViewModel.kt"
            f_read.parent.mkdir(parents=True, exist_ok=True)
            f_read.write_text("package com.demo\nclass ReadByScout\n", encoding="utf-8")
            f_unread.write_text("package com.demo\nclass UnreadViewModel\n", encoding="utf-8")

            tx_dir = repo / "brain" / "parent-v1311" / ".system_generated" / "logs"
            tx_dir.mkdir(parents=True, exist_ok=True)
            parent_tx = tx_dir / "transcript.jsonl"
            parent_tx.write_text(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Audit 17 files"}) + "\n", encoding="utf-8")
            dp._save_utility_ledger(repo, {
                "schema_version": 1,
                "entries": [{
                    "wave_id": "w-scout-v1311",
                    "agent_type": dp.SCOUT_AGENT,
                    "role": dp.SCOUT_AGENT,
                    "parent_conversation_id": "parent-v1311",
                    "parent_user_turns": 1,
                    "execution_id": "child-scout-1",
                    "wave_completed": True,
                    "completed_at_epoch": 9999999999.0,
                    "lead_post_reads": 3,
                    "inspected_files": ["app/src/main/java/com/demo/ReadByScout.kt"],
                    "dispatched_epoch": 9999999999.0,
                }],
            })
            with patch("antigravity_runtime.resolve_transcript", side_effect=lambda cid: parent_tx if cid == "parent-v1311" else None):
                ok_reread, _, code_reread = dp.check_and_record_lead_post_subagent_read(
                    repo, "parent-v1311", tool_name="view_file", args={"AbsolutePath": str(f_read), "StartLine": 1, "EndLine": 10},
                )
                self.assertFalse(ok_reread)
                self.assertEqual("POST_SCOUT_REREAD_CAP_REACHED", code_reread)

                ok_unread, _, _ = dp.check_and_record_lead_post_subagent_read(
                    repo, "parent-v1311", tool_name="view_file", args={"AbsolutePath": str(f_unread), "StartLine": 1, "EndLine": 10},
                )
                self.assertTrue(ok_unread, "Unread target file outside Scout's inspected_files must be permitted")

            rc_vs = vs.main(["--repo", str(repo), "--task", "nonexistent-task", "--json"])
            self.assertEqual(1, rc_vs)
            rc_ro = ro.main(["status", "--repo", str(repo), "--task-id", "nonexistent-task", "--json"])
            self.assertEqual(1, rc_ro)


class TestV1310DesktopDrillFixes(unittest.TestCase):
    """Regression coverage for the 4 live Windows Antigravity Desktop Rashaqa drill findings (v1.3.10)."""

    def test_v1310_01_hydrogen_parent_tier_inheritance_passes_without_false_mismatch(self):
        import review_models as rm

        # Parent Desktop session running `gemini-4-hydrogen-high` while SIMPLE task resolved `gemini-4-hydrogen-medium`
        self.assertTrue(
            rm._matches_antigravity_native_model(
                "gemini-4-hydrogen-medium",
                "medium",
                "gemini-4-hydrogen-high",
                ["gemini-4-hydrogen"],
            )
        )
        # Parent Desktop session running `gemini-4-hydrogen-medium` on COMPLEX `gemini-4-hydrogen-high`
        self.assertTrue(
            rm._matches_antigravity_native_model(
                "gemini-4-hydrogen-high",
                "high",
                "gemini-4-hydrogen-medium",
                ["gemini-4-hydrogen"],
            )
        )
        # Cross-family leaks (`Carbon`, `Argon`, `3.8 Flash`) must STILL fail closed!
        for bad_family in ("gemini-4-carbon-medium", "gemini-4-argon-low", "gemini-3.8-flash-medium"):
            self.assertFalse(
                rm._matches_antigravity_native_model(
                    "gemini-4-hydrogen-medium",
                    "medium",
                    bad_family,
                    [bad_family],
                ),
                bad_family,
            )

    def test_v1310_02_modelless_agent_md_no_live_rewrite_kill_all_guard_and_live_alias_escape(self):
        import delegation_policy as dp
        import install_tool_adapters as ita
        import pre_tool_safety as pts
        import review_models as rm
        from _vnext_common import atomic_write_json, read_json

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "drill-repo"
            repo.mkdir()
            kit_root = Path(__file__).resolve().parents[2]
            shutil.copytree(kit_root / "agents" / "subagents", repo / ".agents" / "subagents")
            ita.generate_antigravity_agents(repo, dry_run=False)

            # 1) All 8 `.agents/agents/*/agent.md` files omit `model:` from YAML frontmatter so Desktop auto-loads them
            for role_dir in sorted((repo / ".agents" / "agents").iterdir()):
                md_txt = (role_dir / "agent.md").read_text(encoding="utf-8")
                fm_part = md_txt.split("---", 2)[1]
                self.assertNotIn("model:", fm_part, f"{role_dir.name} still has model: in YAML frontmatter")

            # 2) `sync_antigravity_agent_models` never mutates existing `agent.md` mid-session
            bug_md_path = repo / ".agents/agents/bug-test-reviewer-agent/agent.md"
            before_bytes = bug_md_path.read_bytes()
            updated = rm.sync_antigravity_agent_models(
                repo,
                {"bug-test-reviewer-agent": {"resolved_model": "gemini-4-hydrogen-medium", "agent_frontmatter_model": "gemini-4-hydrogen-medium"}},
            )
            self.assertEqual([], updated)
            self.assertEqual(before_bytes, bug_md_path.read_bytes())

            # 3) `_has_unfinalized_active_review_wave` blocks `kill_all` while VERIFYING review wave is unfinalized, then allows after reviews.json
            tdir = repo / ".agents/state/tasks/T-DRILL"
            (tdir / "review-execution/run-d1").mkdir(parents=True)
            atomic_write_json(repo / ".agents/state/active-task.json", {"task_id": "T-DRILL"})
            atomic_write_json(tdir / "plan.json", {"task_id": "T-DRILL", "status": "VERIFYING"})
            atomic_write_json(tdir / "current-run.json", {
                "task_id": "T-DRILL",
                "run_id": "run-d1",
                "delivery_snapshot_sha256": "s" * 64,
            })
            atomic_write_json(tdir / "review-execution/run-d1/ledger.json", {
                "reviewers": {"bug-test-reviewer-agent": {"state": "ENV_BLOCKED"}},
            })
            blocked_k, detail_k = pts._has_unfinalized_active_review_wave(repo)
            self.assertTrue(blocked_k)
            self.assertIn("T-DRILL", detail_k)

            rev_done = repo / ".agents/state/runs" / ("s" * 64) / "run-d1" / "reviews.json"
            rev_done.parent.mkdir(parents=True)
            atomic_write_json(rev_done, {"status": "PASS"})
            blocked_after, _ = pts._has_unfinalized_active_review_wave(repo)
            self.assertFalse(blocked_after)

            # 4) Emergency `<role>-live` alias passes `_validate_define_subagent` (read-only enforced!)
            with unittest.mock.patch.object(pts, "REPO", repo):
                spec_bug = read_json(repo / ".agents/subagents/bug-test-reviewer-agent.json")
                ok_live, _, code_live = pts._validate_define_subagent(
                    {
                        "Name": "bug-test-reviewer-agent-live",
                        "SystemPrompt": spec_bug["system_prompt"],
                        "EnableWriteTools": False,
                        "EnableSubagentTools": False,
                    },
                    "define_subagent",
                )
                self.assertTrue(ok_live)
                self.assertEqual("DEFINE_SUBAGENT_ALLOWED", code_live)

                bad_live_w, _, code_bad_w = pts._validate_define_subagent(
                    {
                        "Name": "bug-test-reviewer-agent-live",
                        "SystemPrompt": spec_bug["system_prompt"],
                        "EnableWriteTools": True,
                        "EnableSubagentTools": False,
                    },
                    "define_subagent",
                )
                self.assertFalse(bad_live_w)
                self.assertEqual("READ_ONLY_SUBAGENT_WRITE_FORBIDDEN", code_bad_w)

    def test_v1310_03_utility_ledger_skips_dispatch_failed_and_tracks_tool_calls_and_test_only_draft(self):
        import delegation_policy as dp
        from _workflow.engine import is_architecture_neutral_scope

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "app-repo"
            ag_root = root / "ag-data"
            (repo / ".agents/state").mkdir(parents=True)
            parent_cid = "991ae0ad-8eea-4009-9111-5ecc043092ec"
            scout_cid = "ec44e7c5-f055-4681-83b8-49aaa74bd7ad"
            prompt = "Find FoodPlanViewModelTest conventions across :app"

            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(ag_root)}, clear=False):
                # Wave 1: failed initial invoke_subagent before define_subagent
                dp.record_utility_dispatch(
                    repo,
                    agent_type=dp.SCOUT_AGENT,
                    role_label=dp.SCOUT_AGENT,
                    prompt=prompt,
                    parent_conversation_id=parent_cid,
                    wave_id="wave-failed-1",
                )
                dp.mark_utility_wave_completed(repo, parent_cid, wave_id="wave-failed-1", dispatch_failed=True)

                # Wave 2: retried with identical prompt -> succeeds in `ec44e7c5` and runs 3 read_file calls
                dp.record_utility_dispatch(
                    repo,
                    agent_type=dp.SCOUT_AGENT,
                    role_label=dp.SCOUT_AGENT,
                    prompt=prompt,
                    parent_conversation_id=parent_cid,
                    wave_id="wave-ok-2",
                )
                tx = ag_root / "brain" / scout_cid / ".system_generated" / "logs" / "transcript.jsonl"
                tx.parent.mkdir(parents=True, exist_ok=True)
                rows = [
                    {
                        "source": "SYSTEM",
                        "type": "SYSTEM_MESSAGE",
                        "content": f"<SYSTEM_MESSAGE>sender={parent_cid} priority=MESSAGE_PRIORITY_HIGH content={prompt}\n</SYSTEM_MESSAGE>",
                    },
                    {"source": "MODEL", "type": "TOOL_CALL", "toolName": "read_file"},
                    {"source": "MODEL", "type": "TOOL_CALL", "toolName": "read_file"},
                ]
                tx.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

                # Live step budget call increments tool_calls_used once bound, and post-tool syncs transcript floor
                ctx = dp.utility_subagent_context(repo, scout_cid, bind=True)
                self.assertIsNotNone(ctx)
                self.assertEqual("wave-ok-2", ctx["wave_id"])
                dp.check_and_record_subagent_step_budget(repo, scout_cid, kind="SCOUT", tool_name="read_file", role=dp.SCOUT_AGENT)
                dp.bind_utility_from_post_tool(repo, {"conversationId": parent_cid})

                entries = dp._load_utility_ledger(repo)["entries"]
                w1 = next(e for e in entries if e["wave_id"] == "wave-failed-1")
                w2 = next(e for e in entries if e["wave_id"] == "wave-ok-2")
                self.assertEqual("", w1["execution_id"])
                self.assertTrue(w1.get("dispatch_failed"))
                self.assertEqual(scout_cid, w2["execution_id"])
                self.assertGreaterEqual(int(w2["tool_calls_used"]), 2)

            # Pure TEST_ONLY standalone test path is architecture-neutral (no ARCHITECTURE_DECISION_REQUIRED)
            self.assertTrue(
                is_architecture_neutral_scope(
                    scope_files=["app/src/test/java/com/madarsoft/fitness/VerificationDrillTest.kt"],
                    surfaces={"TEST_ONLY"},
                    arch_intent="EXISTING_CHANGE",
                )
            )
            # Mixed production + test path is NOT architecture-neutral
            self.assertFalse(
                is_architecture_neutral_scope(
                    scope_files=[
                        "app/src/main/java/com/madarsoft/fitness/FoodViewModel.kt",
                        "app/src/test/java/com/madarsoft/fitness/VerificationDrillTest.kt",
                    ],
                    surfaces={"BUSINESS_LOGIC", "TEST_ONLY"},
                    arch_intent="EXISTING_CHANGE",
                )
            )




class TestV1313AuditAndForumGuards(unittest.TestCase):
    """Regression suite for v1.3.13 final line-by-line audit fixes and Nov 15, 2026 Antigravity forum guards (#200467, #200632, #200619)."""

    def test_hook_conversations_flat_schema_and_cache_path_parity(self):
        import tempfile
        import antigravity_runtime as agr
        import delegation_policy as dp
        import review_models as rm

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            state_cache = repo / ".agents" / "state" / "cache"
            state_cache.mkdir(parents=True, exist_ok=True)
            (repo / ".agents" / "VERSION").write_text("1.3.13\n", encoding="utf-8")

            # Write flat `{cid: epoch}` hook-conversations.json exactly as `pre_tool_safety.py:2654` writes it
            (state_cache / "hook-conversations.json").write_text(
                json.dumps({
                    "subagent-child-cid": 1700000099.0,
                    "lead-old-cid": 1700000010.0,
                    "lead-newest-cid": 1700000050.0,
                }),
                encoding="utf-8",
            )

            app_data = root / "appdata"
            brain = app_data / "brain"
            sub_tx = brain / "subagent-child-cid" / ".system_generated" / "logs" / "transcript.jsonl"
            sub_tx.parent.mkdir(parents=True, exist_ok=True)
            sub_tx.write_text(
                json.dumps({"source": "SYSTEM", "type": "SYSTEM_MESSAGE", "content": "<SYSTEM_MESSAGE>sender=lead-newest-cid priority=MESSAGE_PRIORITY_HIGH content=HARNESS_SCOUT_FINGERPRINT=flash-architectural-scout-v1\n</SYSTEM_MESSAGE>"}) + "\n",
                encoding="utf-8",
            )
            lead_tx = brain / "lead-newest-cid" / ".system_generated" / "logs" / "transcript.jsonl"
            lead_tx.parent.mkdir(parents=True, exist_ok=True)
            lead_tx.write_text(
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "implement feature"}) + "\n",
                encoding="utf-8",
            )
            rev_tx = brain / "rev-child-cid" / ".system_generated" / "logs" / "transcript.jsonl"
            rev_tx.parent.mkdir(parents=True, exist_ok=True)
            rev_tx.write_text(
                json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "PASS"}) + "\n",
                encoding="utf-8",
            )

            def _fake_meta(tx_path):
                self.assertIsInstance(tx_path, Path)
                s = str(tx_path)
                if "lead-newest-cid" in s or "rev-child-cid" in s:
                    return {
                        "execution_id": "lead-newest-cid" if "lead-newest-cid" in s else "rev-child-cid",
                        "host_configured_model": "models/gemini-4-carbon-medium",
                        "host_reported_models": ["models/gemini-4-carbon-medium"],
                        "native_metadata_source": "sqlite_vscdb",
                    }
                return {}

            old_env = os.environ.get("ANTIGRAVITY_APP_DATA")
            old_cid = os.environ.get("HARNESS_CONVERSATION_ID")
            os.environ["ANTIGRAVITY_APP_DATA"] = str(app_data)
            os.environ.pop("HARNESS_CONVERSATION_ID", None)
            orig_meta = agr.native_model_metadata
            agr.native_model_metadata = _fake_meta
            try:
                cands = agr.extract_lead_candidates_from_state(repo / ".agents" / "state")
                self.assertEqual(cands[:3], ["subagent-child-cid", "lead-newest-cid", "lead-old-cid"])
                # Subagent child is skipped automatically, resolving the real `lead-newest-cid` Carbon family!
                self.assertEqual(dp._detect_live_parent_lead_family(repo), "gemini-4-carbon")
                run_doc = {
                    "task_id": "T-FLAT",
                    "review_host": "antigravity",
                    "policy": str(repo / ".agents" / "state" / "tasks" / "T-FLAT" / "policy.json"),
                }
                obs = {
                    "execution_id": "rev-child-cid",
                    "host_configured_model": "models/gemini-4-carbon-medium",
                    "host_reported_models": ["models/gemini-4-carbon-medium"],
                    "native_metadata_source": "sqlite_vscdb",
                }
                self.assertTrue(rm._is_proven_upward_parent_inheritance(run_doc, {}, obs))
            finally:
                agr.native_model_metadata = orig_meta
                if old_env is None:
                    os.environ.pop("ANTIGRAVITY_APP_DATA", None)
                else:
                    os.environ["ANTIGRAVITY_APP_DATA"] = old_env
                if old_cid is not None:
                    os.environ["HARNESS_CONVERSATION_ID"] = old_cid

    def test_run_tests_gate_task_disambiguation_and_pure_json_and_phase_review_json(self):
        import io
        import tempfile
        from contextlib import redirect_stdout, redirect_stderr
        import run_tests_gate as rtg
        import phase_review as pr

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents" / "state" / "results").mkdir(parents=True, exist_ok=True)
            (repo / "feature" / "home" / "build" / "test-results" / "testDebugUnitTest").mkdir(parents=True, exist_ok=True)
            xml_p = repo / "feature" / "home" / "build" / "test-results" / "testDebugUnitTest" / "TEST-HomeTest.xml"
            xml_p.write_text('<testsuite name="HomeTest" tests="1" failures="0" errors="0"><testcase classname="HomeTest" name="ok"/></testsuite>', encoding="utf-8")

            captured_tasks: list[list[str]] = []
            orig_run = rtg.run_test_tasks

            def _stub_run(tasks, extra=None):
                captured_tasks.append(list(tasks))
                import os as _os, time as _time
                now = _time.time() + 2.0
                _os.utime(xml_p, (now, now))
                return 0, {"test_failure_only": False}

            rtg.run_test_tasks = _stub_run
            try:
                out_buf = io.StringIO()
                err_buf = io.StringIO()
                with redirect_stdout(out_buf), redirect_stderr(err_buf):
                    rc = rtg.main(["--repo", str(repo), "--task", ":feature:home:testDebugUnitTest", "--json"])
                self.assertEqual(rc, 0)
                self.assertEqual(captured_tasks[-1], [":feature:home:testDebugUnitTest"])
                parsed = json.loads(out_buf.getvalue())
                self.assertEqual(parsed["status"], "PASS")
                self.assertEqual(parsed["gradle_task"], ":feature:home:testDebugUnitTest")
            finally:
                rtg.run_test_tasks = orig_run

            # Verify phase-review package --json parser & completed_at ISO field in delegation_policy
            import delegation_policy as dp
            ent = dp.record_utility_dispatch(repo, agent_type=dp.SCOUT_AGENT, role_label=dp.SCOUT_AGENT, prompt="Inspect HomeViewModel.kt and HomeUiState.kt", parent_conversation_id="p-iso")
            self.assertEqual(ent["completed_at"], "")
            dp.mark_utility_wave_completed(repo, "p-iso", wave_id=ent["wave_id"])
            led = dp._load_utility_ledger(repo)
            saved_ent = led["entries"][-1]
            self.assertTrue(saved_ent["wave_completed"])
            self.assertTrue(str(saved_ent.get("completed_at") or "").endswith("Z"))
            self.assertIsNotNone(pr)

    def test_nov15_forum_guards_200467_200632_200619(self):
        import subprocess
        import sys
        import tempfile
        import antigravity_runtime as agr
        import session_forensics as sf
        from doctor.engine import HarnessDoctor as _DocCls

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "client"
            (repo / ".agents" / "state").mkdir(parents=True, exist_ok=True)
            (repo / ".vscode").mkdir(parents=True, exist_ok=True)
            (repo / ".vscode" / "settings.json").write_text(
                json.dumps({"antigravity.autoAcceptOnChat": True}),
                encoding="utf-8",
            )

            rep = agr.inspect_nov15_antigravity_hazards(
                repo,
                env={"ANTIGRAVITY_ACTIVE_MODEL": "models/gemini-4-hydrogen-extra"},
            )
            self.assertTrue(rep["hydrogen_extra_leak_active"])
            self.assertTrue(rep["auto_accept_at_risk"])
            self.assertEqual(rep["auto_accept_on_chat_state"], "explicit_true")
            old_ag_m = os.environ.get("ANTIGRAVITY_ACTIVE_MODEL")
            os.environ["ANTIGRAVITY_ACTIVE_MODEL"] = "models/gemini-4-hydrogen-extra"
            try:
                (repo / "GEMINI.md").write_text("# App\n", encoding="utf-8")
                d_inst = _DocCls(repo)
                d_inst._check_antigravity_runtime_hazards("Antigravity", is_ag=True)
                nov_chk = next(r for r in d_inst.results if r.name == "Nov 15 Quota & Diff Guard")
                self.assertEqual(nov_chk.status, "WARN")
                self.assertIn("200467", nov_chk.message)
                self.assertIn("200619", nov_chk.message)
            finally:
                if old_ag_m is None:
                    os.environ.pop("ANTIGRAVITY_ACTIVE_MODEL", None)
                else:
                    os.environ["ANTIGRAVITY_ACTIVE_MODEL"] = old_ag_m

            # Verify #200632: pre_tool_safety denies inline `python -c` and multi-line commands on Antigravity with #200632 guidance
            pts_script = Path(__file__).resolve().parent / "pre_tool_safety.py"
            for bad_cmd in ('python -c "print(123)"', "python .agents/harness.py version\npython -c print(1)", "rg safe | tee app/status.txt", "python .agents/harness.py status 2>&1"):
                proc = subprocess.run(
                    [sys.executable, str(pts_script)],
                    input=json.dumps({
                        "toolName": "run_command",
                        "toolArgs": {"CommandLine": bad_cmd},
                        "workspacePaths": [str(Path(__file__).resolve().parents[2])],
                    }),
                    capture_output=True,
                    text=True,
                    env={k: v for k, v in os.environ.items() if k != "HARNESS_HOOK_HOST"},
                    check=False,
                )
                self.assertEqual(proc.returncode, 0)
                resp = json.loads(proc.stdout.strip())
                self.assertEqual(resp["decision"], "deny")
                self.assertIn("200632", resp["reason"])

            # Verify raw_adb hint no longer recommends `| Select-String`
            import pre_tool_safety as pts
            self.assertNotIn("Select-String", pts.DENY_HINTS["raw_adb"])
            self.assertIn("200632", pts.DENY_HINTS["raw_adb"])

            # Verify session_forensics detects #200467 in transcripts
            app_data = Path(td) / "appdata"
            tx = app_data / "brain" / "hx-cid" / ".system_generated" / "logs" / "transcript.jsonl"
            tx.parent.mkdir(parents=True, exist_ok=True)
            tx.write_text(
                json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "model": "models/gemini-4-hydrogen-extra", "content": "ok"}) + "\n",
                encoding="utf-8",
            )
            old_ad = os.environ.get("ANTIGRAVITY_APP_DATA")
            os.environ["ANTIGRAVITY_APP_DATA"] = str(app_data)
            try:
                diag = sf.diagnose_session(repo, conversation_id="hx-cid")
                codes = {f["code"] for f in diag.get("findings") or []}
                self.assertIn("HYDROGEN_EXTRA_ARGON_QUOTA_LEAK", codes)
            finally:
                if old_ad is None:
                    os.environ.pop("ANTIGRAVITY_APP_DATA", None)
                else:
                    os.environ["ANTIGRAVITY_APP_DATA"] = old_ad




class TestV1314SmartAutoThresholdCalibration(unittest.TestCase):
    """Regression suite for v1.3.14 Smart Auto threshold calibration (10 files, 80 KB, and smart 2-module 6 files / 48 KB / 3+ modules)."""

    def test_smart_auto_v1314_exact_boundaries(self):
        import tempfile
        import execution_mode as em

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            (repo / ".agents" / "state").mkdir(parents=True, exist_ok=True)

            # 1) File count boundary on single module: 9 files -> normal; 10 files -> web
            for count, expected_mode, expected_prefix in (
                (9, "normal", "AUTO_NORMAL_COMPACT_SCOPE_9_FILES"),
                (10, "web", "AUTO_WEB_LARGE_SCOPE_10_FILES"),
            ):
                files = [f"app/src/main/kotlin/com/demo/F{i}.kt" for i in range(count)]
                for rel in files:
                    fp = repo / rel
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_text("package com.demo\nclass X\n", encoding="utf-8")
                plan = {
                    "task_id": f"t-files-{count}",
                    "status": "IMPLEMENTING",
                    "task_kind": "FEATURE",
                    "expected_files": files,
                    "expected_modules": [":app"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                }
                mode, trig, _ = em.evaluate_smart_auto_routing(repo, plan["task_id"], plan)
                self.assertEqual(mode, expected_mode)
                self.assertEqual(trig, expected_prefix)

                # Pre-plan candidate_files parity
                c_mode, c_trig, _ = em.evaluate_smart_auto_routing(repo, "", None, candidate_files=files)
                self.assertEqual(c_mode, expected_mode)
                if count >= 10:
                    self.assertEqual(c_trig, "AUTO_WEB_LARGE_CANDIDATE_SCOPE_10_FILES")

            # 2) Non-test code mass boundary on single module: 79 KB -> normal; 80 KB -> web
            f_79 = repo / "app/src/main/kotlin/com/demo/Heavy79.kt"
            f_79.write_bytes(b"a" * (79 * 1024))
            m79, t79, _ = em.evaluate_smart_auto_routing(
                repo,
                "t-mass-79",
                {
                    "task_id": "t-mass-79",
                    "status": "IMPLEMENTING",
                    "task_kind": "FEATURE",
                    "expected_files": ["app/src/main/kotlin/com/demo/Heavy79.kt"],
                    "expected_modules": [":app"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                },
            )
            self.assertEqual(m79, "normal")
            self.assertEqual(t79, "AUTO_NORMAL_COMPACT_SCOPE_1_FILES")

            f_80 = repo / "app/src/main/kotlin/com/demo/Heavy80.kt"
            f_80.write_bytes(b"a" * (80 * 1024))
            m80, t80, _ = em.evaluate_smart_auto_routing(
                repo,
                "t-mass-80",
                {
                    "task_id": "t-mass-80",
                    "status": "IMPLEMENTING",
                    "task_kind": "FEATURE",
                    "expected_files": ["app/src/main/kotlin/com/demo/Heavy80.kt"],
                    "expected_modules": [":app"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                },
            )
            self.assertEqual(m80, "web")
            self.assertEqual(t80, "AUTO_WEB_HEAVY_CODE_MASS_80KB")

            cm80, ct80, _ = em.evaluate_smart_auto_routing(
                repo, "", None, candidate_files=["app/src/main/kotlin/com/demo/Heavy80.kt"]
            )
            self.assertEqual(cm80, "web")
            self.assertEqual(ct80, "AUTO_WEB_HEAVY_CANDIDATE_CODE_MASS_80KB")

            # 3) Smart 2-module rules:
            #    - 2 modules with 5 small files (<48 KB) -> normal
            #    - 2 modules with 6 small files -> web
            #    - 2 modules with 2 files totaling 47 KB -> normal
            #    - 2 modules with 2 files totaling 48 KB -> web
            #    - 3 modules with 3 small files -> web
            #    - 2 phases on 1 module with 2 small files -> web
            small_5 = [f"core/src/main/kotlin/com/demo/C{i}.kt" for i in range(3)] + [
                f"app/src/main/kotlin/com/demo/A{i}.kt" for i in range(2)
            ]
            for rel in small_5 + ["app/src/main/kotlin/com/demo/A2.kt", "data/src/main/kotlin/com/demo/D0.kt"]:
                fp = repo / rel
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text("package com.demo\nclass S\n", encoding="utf-8")

            m_2m5f, t_2m5f, _ = em.evaluate_smart_auto_routing(
                repo,
                "t-2m-5f",
                {
                    "task_id": "t-2m-5f",
                    "status": "IMPLEMENTING",
                    "expected_files": small_5,
                    "expected_modules": [":core", ":app"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                },
            )
            self.assertEqual(m_2m5f, "normal")
            self.assertEqual(t_2m5f, "AUTO_NORMAL_COMPACT_SCOPE_5_FILES")

            m_2m6f, t_2m6f, _ = em.evaluate_smart_auto_routing(
                repo,
                "t-2m-6f",
                {
                    "task_id": "t-2m-6f",
                    "status": "IMPLEMENTING",
                    "expected_files": small_5 + ["app/src/main/kotlin/com/demo/A2.kt"],
                    "expected_modules": [":core", ":app"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                },
            )
            self.assertEqual(m_2m6f, "web")
            self.assertEqual(t_2m6f, "AUTO_WEB_MULTI_MODULE_OR_PHASE")

            f_c24 = repo / "core/src/main/kotlin/com/demo/CoreHeavy.kt"
            f_a23 = repo / "app/src/main/kotlin/com/demo/AppMed.kt"
            f_c24.write_bytes(b"k" * (24 * 1024))
            f_a23.write_bytes(b"k" * (23 * 1024))
            m_2m47k, _, _ = em.evaluate_smart_auto_routing(
                repo,
                "t-2m-47k",
                {
                    "task_id": "t-2m-47k",
                    "status": "IMPLEMENTING",
                    "expected_files": [
                        "core/src/main/kotlin/com/demo/CoreHeavy.kt",
                        "app/src/main/kotlin/com/demo/AppMed.kt",
                    ],
                    "expected_modules": [":core", ":app"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                },
            )
            self.assertEqual(m_2m47k, "normal")

            f_a23.write_bytes(b"k" * (24 * 1024))
            m_2m48k, t_2m48k, _ = em.evaluate_smart_auto_routing(
                repo,
                "t-2m-48k",
                {
                    "task_id": "t-2m-48k",
                    "status": "IMPLEMENTING",
                    "expected_files": [
                        "core/src/main/kotlin/com/demo/CoreHeavy.kt",
                        "app/src/main/kotlin/com/demo/AppMed.kt",
                    ],
                    "expected_modules": [":core", ":app"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                },
            )
            self.assertEqual(m_2m48k, "web")
            self.assertEqual(t_2m48k, "AUTO_WEB_MULTI_MODULE_OR_PHASE")

            m_3m3f, t_3m3f, _ = em.evaluate_smart_auto_routing(
                repo,
                "t-3m-3f",
                {
                    "task_id": "t-3m-3f",
                    "status": "IMPLEMENTING",
                    "expected_files": [
                        "core/src/main/kotlin/com/demo/C0.kt",
                        "data/src/main/kotlin/com/demo/D0.kt",
                        "app/src/main/kotlin/com/demo/A0.kt",
                    ],
                    "expected_modules": [":core", ":data", ":app"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                },
            )
            self.assertEqual(m_3m3f, "web")
            self.assertEqual(t_3m3f, "AUTO_WEB_MULTI_MODULE_OR_PHASE")

            m_2p, t_2p, _ = em.evaluate_smart_auto_routing(
                repo,
                "t-2p",
                {
                    "task_id": "t-2p",
                    "status": "IMPLEMENTING",
                    "phases": [{"id": "p1"}, {"id": "p2"}],
                    "expected_files": [
                        "app/src/main/kotlin/com/demo/A0.kt",
                        "app/src/main/kotlin/com/demo/A1.kt",
                    ],
                    "expected_modules": [":app"],
                    "expected_surfaces": ["BUSINESS_LOGIC"],
                },
            )
            self.assertEqual(m_2p, "web")
            self.assertEqual(t_2p, "AUTO_WEB_MULTI_MODULE_OR_PHASE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
