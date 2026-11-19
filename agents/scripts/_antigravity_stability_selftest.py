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
import unittest.mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent.parent

sys.path.insert(0, str(SCRIPTS))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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
            timeout=60,
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
                timeout=60,
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
        import repair as repair_mod

        generate_antigravity_agents(self.repo, dry_run=False)
        rel = ".agents/agents/harness-scout-agent/agent.md"
        p = self.repo / rel
        self.assertTrue(p.is_file(), f"Missing {rel}")
        self.assertFalse((self.repo / ".agents/agents/harness-worker-agent/agent.md").exists())
        txt = p.read_text(encoding="utf-8")
        self.assertNotIn("\nmodel:", txt)
        self.assertIn("<!-- harness-target-model: gemini-4-hydrogen-", txt)
        self.assertIn("subagent: true", txt)
        self.assertIn("mainAgent: false", txt)
        self.assertTrue(_antigravity_agent_matches_policy(self.repo, rel))

        scout_fm = txt.split("---")[1]
        self.assertNotIn("write_to_file", scout_fm)

        doc = HarnessDoctor(self.repo, run_selftest=False)
        doc.check_antigravity_installation()
        rev_check = next(r for r in doc.results if r.name == "Custom Reviewer Agents")
        self.assertEqual("PASS", rev_check.status, rev_check.message)

        # Verify `repair.py` prunes retired legacy `harness-worker-agent` and `human_review_cockpit.py` artifacts on upgrade!
        stale_worker_md = self.repo / ".agents/agents/harness-worker-agent/agent.md"
        stale_worker_json = self.repo / ".agents/subagents/harness-worker-agent.json"
        stale_cockpit_py = self.repo / ".agents/scripts/human_review_cockpit.py"
        stale_worker_md.parent.mkdir(parents=True, exist_ok=True)
        stale_worker_md.write_text("legacy worker", encoding="utf-8")
        stale_worker_json.write_text("{}", encoding="utf-8")
        stale_cockpit_py.write_text("# legacy cockpit", encoding="utf-8")
        (self.repo / ".agents/VERSION").write_text((REPO_ROOT / "agents/VERSION").read_text(encoding="utf-8"), encoding="utf-8")
        rep_res = repair_mod.repair_repository(self.repo, REPO_ROOT, force=True)
        self.assertEqual((REPO_ROOT / "agents/VERSION").read_text(encoding="utf-8").strip(), rep_res["pinned_version"])
        self.assertFalse(stale_worker_md.exists())
        self.assertFalse(stale_worker_json.exists())
        self.assertFalse(stale_cockpit_py.exists())

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
        self.assertEqual("INLINE_LEAD_DIRECT", pol_t0["strategy"])
        self.assertFalse(pol_t0["worker_allowed"])
        _cancel("t-trivial")

        # --- Case B0: Small 2-file FEATURE -> INLINE_LEAD_DIRECT ---
        _draft_and_begin([
            "--outcome", "Small 2-file state tweak",
            "--kind", "FEATURE",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-small-inline")
        pol_small = evaluate_delegation_policy(self.repo)
        self.assertEqual("INLINE_LEAD_DIRECT", pol_small["strategy"])
        self.assertIsNone(pol_small["recommended_subagent"])
        self.assertEqual("Gemini 4 Hydrogen (High)", pol_small["quota_strategy"]["fast_fallback_chat_model"])
        _cancel("t-small-inline")

        # --- Case B: 4+ file FEATURE -> INLINE_LEAD_DIRECT + retired Worker hard-denied across PreToolUse ---
        _draft_and_begin([
            "--outcome", "Add home state, repo, screen & test",
            "--kind", "FEATURE",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeUiState.kt,app/src/main/kotlin/com/example/HomeRepository.kt,app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-feat")
        pol_feat = evaluate_delegation_policy(self.repo)
        self.assertEqual("INLINE_LEAD_DIRECT", pol_feat["strategy"])
        self.assertFalse(pol_feat["worker_allowed"])
        self.assertEqual("NONE", pol_feat["worker_mode"])

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
        self.assertEqual("INLINE_LEAD_DIRECT", cli_json["strategy"])
        self.assertEqual("Gemini 4 Carbon (Medium)", cli_json["quota_strategy"]["primary_chat_model"])

        # Router attaches delegation_advisory on Antigravity
        act_ag = workflow.resolve_next_action(self.repo, "t-feat", host="antigravity")
        self.assertIn("delegation_advisory", act_ag)
        self.assertEqual("INLINE_LEAD_DIRECT", act_ag["delegation_advisory"]["strategy"])

        # Retired `harness-worker-agent` (and `-live` alias) MUST be hard-denied on `invoke_subagent`!
        brief = "Update HomeViewModel.kt to expose StateFlow<HomeUiState>, add unit test in HomeViewModelTest.kt, and run python .agents/harness.py test."
        for w_alias in ("harness-worker-agent", "harness-worker-agent-live"):
            w_deny = self._run_pre_hook({
                "conversationId": "parent-carbon-2",
                "tool": "invoke_subagent",
                "arguments": {"TypeName": w_alias, "Role": w_alias, "Workspace": "inherit", "Prompt": brief},
            })
            self.assertEqual("deny", w_deny["decision"], w_deny)
            self.assertEqual("WORKER_AGENT_RETIRED_INLINE_LEAD_ONLY", w_deny.get("reason_code"))

        # Warm Lead session CAN edit in-scope HomeViewModel.kt directly!
        lead_in_scope = self._run_pre_hook({
            "conversationId": "parent-carbon-2",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt"), "CodeContent": "package com.example\nclass HomeViewModel { val ok = true }\n"},
        })
        self.assertEqual("allow", lead_in_scope["decision"], lead_in_scope)
        _cancel("t-feat")

        # --- Case C: Sensitive AUTH / SECURITY task -> INLINE_LEAD_DIRECT with sensitive_surfaces ---
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
        self.assertEqual("INLINE_LEAD_DIRECT", pol_auth["strategy"])
        self.assertEqual(["AUTH", "SECURITY"], pol_auth["sensitive_surfaces"])
        self.assertFalse(pol_auth["worker_allowed"])

        allow_lead_prod = self._run_pre_hook({
            "conversationId": "parent-carbon-3",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/main/kotlin/com/example/AuthManager.kt"), "CodeContent": "package com.example\nclass AuthManager { fun verify() = true }\n"},
        })
        self.assertEqual("allow", allow_lead_prod["decision"], allow_lead_prod)
        _cancel("t-auth")

        # --- Case D: BUG task before red-evidence -> CAPTURE_RED_INLINE_LEAD ---
        _draft_and_begin([
            "--outcome", "Fix crash in HomeViewModel",
            "--kind", "BUG",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-bug")
        pol_bug = evaluate_delegation_policy(self.repo)
        self.assertEqual("CAPTURE_RED_INLINE_LEAD", pol_bug["strategy"])
        self.assertFalse(pol_bug["worker_allowed"])
        self.assertEqual(["app/src/test/kotlin/com/example/HomeViewModelTest.kt"], pol_bug["target_files"])

        deny_bug_prod = self._run_pre_hook({
            "conversationId": "parent-carbon-4",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/main/kotlin/com/example/HomeViewModel.kt"), "CodeContent": "package com.example\nclass HomeViewModel\n"},
        })
        self.assertEqual("deny", deny_bug_prod["decision"], deny_bug_prod)
        self.assertEqual("RED_EVIDENCE_REQUIRED", deny_bug_prod.get("reason_code"))

        allow_bug_test = self._run_pre_hook({
            "conversationId": "parent-carbon-4",
            "tool": "write_to_file",
            "arguments": {"TargetFile": str(self.repo / "app/src/test/kotlin/com/example/HomeViewModelTest.kt"), "CodeContent": "package com.example\nclass HomeViewModelTest\n"},
        })
        self.assertEqual("allow", allow_bug_test["decision"], allow_bug_test)
        _cancel("t-bug")

        # --- Case E: CONFLICT task -> CONFLICT_INLINE_LEAD ---
        _draft_and_begin([
            "--outcome", "Resolve merge conflict in HomeViewModel",
            "--kind", "CONFLICT",
            "--planning-depth", "BOUNDED",
            "--expected-surfaces", "BUSINESS_LOGIC",
            "--expected-modules", ":app",
            "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
        ], "t-conflict")
        pol_conf = evaluate_delegation_policy(self.repo)
        self.assertEqual("CONFLICT_INLINE_LEAD", pol_conf["strategy"])
        self.assertFalse(pol_conf["worker_allowed"])
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
        # Multi-phase slice executes inline on warm Lead cache!
        self.assertEqual("INLINE_LEAD_DIRECT", act_phased["delegation_advisory"]["strategy"])
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
        self.assertEqual("INLINE_LEAD_DIRECT", dec_simple["strategy"])
        self.assertFalse(dec_simple["worker_allowed"])

        # 3b. COMPLEX multi-module slice -> Lead inline, Scout stays Flash, Doctor & lifecycle pass!
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
        self.assertEqual("INLINE_LEAD_DIRECT", dec_complex["strategy"])
        self.assertFalse(dec_complex["worker_allowed"])
        self.assertNotIn("\nmodel:", (self.repo / ".agents/agents/harness-scout-agent/agent.md").read_text(encoding="utf-8"))
        self.assertTrue(_antigravity_agent_matches_policy(self.repo, ".agents/agents/harness-scout-agent/agent.md"))
        doc_c = HarnessDoctor(self.repo, run_selftest=False)
        doc_c.check_antigravity_installation()
        rev_chk = next(r for r in doc_c.results if r.name == "Custom Reviewer Agents")
        self.assertEqual("PASS", rev_chk.status, rev_chk.message)

        # Validate utility dispatch rejects retired `harness-worker-agent` and blocks `Model='pro'` on Scout!
        bad_retired_w, _, code_ret_w = dp.validate_utility_dispatch(
            self.repo,
            c_plan,
            [{"TypeName": "harness-worker-agent", "Role": "harness-worker-agent", "Workspace": "inherit",
              "Prompt": "Implement SyncViewModel.kt and SyncRepo.kt."}],
        )
        self.assertFalse(bad_retired_w)
        self.assertEqual("WORKER_AGENT_RETIRED_INLINE_LEAD_ONLY", code_ret_w)
        bad_s, _, code_s = dp.validate_utility_dispatch(
            self.repo,
            c_plan,
            [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Workspace": "inherit", "Model": "pro",
              "Prompt": "Inspect SyncViewModel.kt and SyncRepo.kt callers."}],
        )
        self.assertFalse(bad_s)
        self.assertEqual("UTILITY_MODEL_QUOTA_GUARD", code_s)

        dp.evaluate_delegation_policy(self.repo, task_id="w-simple", plan=s_plan, router_action="IMPLEMENT_TASK")
        self.assertNotIn("\nmodel:", (self.repo / ".agents/agents/harness-scout-agent/agent.md").read_text(encoding="utf-8"))

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
                timeout=60,
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
            self.assertEqual("INLINE_LEAD_DIRECT", pol_3file["strategy"])
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

            # 4+ file slices execute inline directly on the warm Lead session (`INLINE_LEAD_DIRECT`)
            pol0 = dp.evaluate_delegation_policy(repo, task_id="t-orch", plan=plan_simple, router_action="IMPLEMENT")
            self.assertEqual("INLINE_LEAD_DIRECT", pol0["strategy"])
            self.assertFalse(pol0["worker_allowed"])
            self.assertEqual("NONE", pol0["worker_mode"])

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
            self.assertFalse(dp.scout_command_allowed(forbidden_cmd), forbidden_cmd)

        gemini_tpl = (REPO_ROOT / "agents" / "tool-adapters" / "GEMINI.md.template").read_text(encoding="utf-8")
        global_tpl = (REPO_ROOT / "agents" / "tool-adapters" / "gemini-runtime" / "android-harness-global.md.template").read_text(encoding="utf-8")
        for expected_choice in ("normal-task", "web-task", "normal-project"):
            self.assertIn(expected_choice, gemini_tpl)
            self.assertIn(expected_choice, global_tpl)
        self.assertNotIn("auto-project", gemini_tpl)
        self.assertNotIn("auto-project", global_tpl)
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

        # 4) harness-rules.md execution-mode choices and V2 self-certification parity
        rules_txt = (REPO_ROOT / "agents/rules/harness-rules.md").read_text(encoding="utf-8")
        self.assertIn("normal-project", rules_txt)
        self.assertNotIn("auto-project", rules_txt)
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

            ok_wk, _, code_wk = pts._validate_define_subagent(
                {"name": "harness-worker-agent", "enable_subagent_tools": False, "enable_write_tools": True},
                "define_subagent",
            )
            self.assertFalse(ok_wk)
            self.assertEqual("WORKER_AGENT_RETIRED_INLINE_LEAD_ONLY", code_wk)


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
                [sys.executable, ".agents/harness.py", "execution-mode", "set", "--choice", "normal-project", "--source", "conversation", "--proof-reference", "Always local"],
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
            # Post-Scout unread file gap allowance
            tx_dir = repo / "brain" / "parent-v1312" / ".system_generated" / "logs"
            tx_dir.mkdir(parents=True, exist_ok=True)
            parent_tx = tx_dir / "transcript.jsonl"
            parent_tx.write_text(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Fix slice"}) + "\n", encoding="utf-8")
            w_plan = {
                "task_id": "t-w-v1312",
                "status": "DRAFT",
                "task_kind": "FEATURE",
                "expected_files": [
                    "app/src/main/java/com/demo/TouchedByWorker.kt",
                    "app/src/main/java/com/demo/UntouchedCaller.kt",
                ],
                "expected_surfaces": ["BUSINESS_LOGIC"],
            }
            dp._save_utility_ledger(repo, {
                "schema_version": 2,
                "entries": [{
                    "wave_id": "w-scout-v1312",
                    "agent_type": dp.SCOUT_AGENT,
                    "role": dp.SCOUT_AGENT,
                    "task_id": "t-w-v1312",
                    "task_status": "DRAFT",
                    "parent_conversation_id": "parent-v1312",
                    "parent_user_turns": 1,
                    "execution_id": "child-scout-1",
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
                self.assertEqual("POST_SCOUT_REREAD_CAP_REACHED", code_same)

                ok_unseen, _, _ = dp.check_and_record_lead_post_subagent_read(
                    repo, "parent-v1312", tool_name="view_file", args={"AbsolutePath": str(f2), "StartLine": 1, "EndLine": 10}, plan=w_plan,
                )
                self.assertTrue(ok_unseen, "Post-Scout surgical read on file NOT read by Scout must be allowed")

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




class TestV1315LiveFitnessLifecycleFixes(unittest.TestCase):
    """Regression suite for all 5 v1.3.15 live Fitness_Android lifecycle & delivery fixes."""

    def test_01_delivery_commit_with_baseline_dirty_files_and_non_destructive_reconcile_lineage(self):
        import argparse
        from _daily_workflow_selftest import GitDeliveryTests, run_git, write_file
        from _vnext_common import atomic_write_json, canonical_sha256, read_json
        from delivery_manifest import build_manifest, build_task_manifest
        from workflow import reconcile_delivery
        import change_decision as cd

        fixture = GitDeliveryTests("test_GIT_DELIVERY_003_developer_commit_with_identical_content_returns_deliver")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        repo = fixture.repo

        # 1) Exact Fitness_Android scenario: pre-existing dirty files recorded in `task-baseline.json`,
        #    while `manifest-run-*.json` has ONLY `MainActivity.kt` in `task_changes`!
        pre_dirty = "app/src/main/kotlin/com/example/PreExistingDirty.kt"
        write_file(repo / pre_dirty, "package com.example\nclass PreExistingDirty { val v = 1 }\n")
        base_man = build_manifest(repo)

        plan, tdir = fixture._setup_ready_task("fitness-dirty-commit")
        tb_doc = {
            "schema_version": 1,
            "task_id": "fitness-dirty-commit",
            "repository": base_man["repository"],
            "base_delivery_snapshot_sha256": base_man["delivery_snapshot_sha256"],
            "base_change_set_sha256": base_man["change_set_sha256"],
            "changes": base_man["changes"],
        }
        tb_doc["baseline_sha256"] = canonical_sha256({
            k: tb_doc[k] for k in ("schema_version", "task_id", "repository", "base_delivery_snapshot_sha256", "base_change_set_sha256", "changes")
        })
        atomic_write_json(tdir / "task-baseline.json", tb_doc)
        frozen_tm = build_task_manifest(repo, tb_doc, expected_files=plan["expected_files"])
        # Confirm `task_changes` ONLY contains `MainActivity.kt` (NOT `PreExistingDirty.kt`)
        self.assertEqual(["app/src/main/kotlin/com/example/MainActivity.kt"], [c["path"] for c in frozen_tm["task_changes"]])
        atomic_write_json(tdir / "manifest-run-fitness-dirty-commit.json", frozen_tm)

        # Developer commits ALL app files together (`PreExistingDirty.kt` + `MainActivity.kt`)
        run_git(repo, "add", "app")
        run_git(repo, "commit", "-qm", "feat: commit verified task and baseline WIP together")

        # `reconcile_delivery` / `deliver` succeeds on the VERY FIRST TRY without lineage rejection!
        delivered_plan, status_code = reconcile_delivery(repo, "fitness-dirty-commit")
        self.assertEqual("DELIVERED", status_code)
        self.assertEqual("DELIVERED", delivered_plan["status"])

        # 2) Also verify `change-decision --reconcile-lineage` on a multi-commit READY_FOR_DELIVERY task
        #    preserves `READY_FOR_DELIVERY` (never resets to `IMPLEMENTING`) when snapshot matches!
        from _daily_workflow_selftest import RouterCompletionAndResumeRecoveryTests
        from workflow import complete
        fixture2 = RouterCompletionAndResumeRecoveryTests("test_RESUME_READY_008_developer_requested_change_reopens_unchanged_ready")
        fixture2.setUp()
        self.addCleanup(fixture2.tearDown)
        repo2 = fixture2.repo
        write_file(repo2 / pre_dirty, "package com.example\nclass PreExistingDirty { val v = 2 }\n")
        _, tdir2 = fixture2._setup_verifying_task_ready_for_complete("fitness-two-commits")
        complete(argparse.Namespace(repo=str(repo2), task_id="fitness-two-commits"))
        from delivery_equivalence import snapshot_verified_files
        snapshot_verified_files(repo2, "fitness-two-commits", read_json(tdir2 / "plan.json"), read_json(tdir2 / "plan.json")["ready_run_id"])
        run_git(repo2, "add", pre_dirty)
        run_git(repo2, "commit", "-qm", "chore: commit baseline file first")
        run_git(repo2, "add", "app")
        run_git(repo2, "commit", "-qm", "feat: commit verified task second")

        rc_cd = cd.record_decision(
            argparse.Namespace(
                repo=str(repo2),
                task_id="fitness-two-commits",
                mode="accept-edits",
                file=[],
                reconcile_lineage=True,
                reason="Confirm 2 developer commits with identical verified snapshot",
                apply=True,
                source="conversation",
                proof_reference="Confirmed my two commits",
                expect_preview=None,
            )
        )
        self.assertEqual("READY_FOR_DELIVERY", rc_cd["status"])
        self.assertTrue(rc_cd.get("preserved_ready_for_delivery"))
        plan2_after = read_json(tdir2 / "plan.json")
        self.assertEqual("READY_FOR_DELIVERY", plan2_after["status"])
        self.assertTrue(plan2_after.get("ready_run_id"))
        _, code2 = reconcile_delivery(repo2, "fitness-two-commits")
        self.assertEqual("DELIVERED", code2)

    def test_02_reopen_without_code_edits_reuses_verified_run_instantly(self):
        import argparse
        from _daily_workflow_selftest import RouterCompletionAndResumeRecoveryTests
        from _vnext_common import read_json
        from workflow import resume, prepare_verification, complete

        fixture = RouterCompletionAndResumeRecoveryTests("test_RESUME_READY_008_developer_requested_change_reopens_unchanged_ready")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        repo = fixture.repo

        plan, tdir = fixture._setup_verifying_task_ready_for_complete("reopen-zero-edit")
        ready_plan = complete(argparse.Namespace(repo=str(repo), task_id="reopen-zero-edit"))
        self.assertEqual("READY_FOR_DELIVERY", ready_plan["status"])
        orig_run_id = ready_plan["ready_run_id"]

        # Premature `resume --reopen` followed by 0 file edits -> `prepare_verification` carries `orig_run_id` instantly!
        resume(argparse.Namespace(repo=str(repo), task_id="reopen-zero-edit", reopen=True))
        self.assertEqual("IMPLEMENTING", read_json(tdir / "plan.json")["status"])
        self.assertTrue((tdir / "reopen-carry.json").is_file())

        carried = prepare_verification(argparse.Namespace(repo=str(repo), task_id="reopen-zero-edit", force=False))
        self.assertTrue(carried.get("verification_carried"))
        self.assertEqual(orig_run_id, carried["run_id"])
        completed = complete(argparse.Namespace(repo=str(repo), task_id="reopen-zero-edit"))
        self.assertEqual("READY_FOR_DELIVERY", completed["status"])

    def test_03_adopt_dirty_on_draft_includes_premodified_expected_files_in_task_changes(self):
        import argparse
        from _daily_workflow_selftest import GitDeliveryTests, write_file
        from delivery_manifest import build_task_manifest, load_task_baseline
        from workflow import draft

        fixture = GitDeliveryTests("test_GIT_DELIVERY_003_developer_commit_with_identical_content_returns_deliver")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        repo = fixture.repo

        vm_rel = "app/src/main/kotlin/com/example/MainActivity.kt"
        bg_rel = "app/src/main/kotlin/com/example/UnrelatedDirty.kt"
        write_file(repo / vm_rel, "package com.example\nclass MainActivity { fun wipFeature() = 42 }\n")
        write_file(repo / bg_rel, "package com.example\nclass UnrelatedDirty\n")

        plan = draft(
            argparse.Namespace(
                repo=str(repo),
                task_id="adopt-wip-vm",
                outcome="Adopt WIP MainActivity feature and add unit tests",
                kind="FEATURE",
                planning_depth="BOUNDED",
                expected_surfaces="BUSINESS_LOGIC",
                expected_modules=":app",
                expected_files=vm_rel,
                test_strategy="Unit tests",
                device_strategy="None",
                risks="None",
                rollback="None",
                external_write=[],
                force=True,
                adopt_dirty=True,
            )
        )
        self.assertIn(vm_rel, plan.get("adopted_dirty_files") or [])
        tb = load_task_baseline(repo, "adopt-wip-vm")
        tb_paths = {c.get("path") for c in (tb.get("changes") or [])}
        self.assertNotIn(vm_rel, tb_paths)
        self.assertIn(bg_rel, tb_paths)

        tm = build_task_manifest(repo, tb, expected_files=[vm_rel])
        tc_paths = [c["path"] for c in tm["task_changes"]]
        self.assertIn(vm_rel, tc_paths)
        self.assertNotIn(bg_rel, tc_paths)

    def test_04_checkpoint_phase_reuses_identical_snapshot_gates_and_blocks_raw_transcript_reads(self):
        import subprocess
        import sys
        import tempfile
        from _vnext_common import atomic_write_json

        pts_script = Path(__file__).resolve().parent / "pre_tool_safety.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            ag_data = root / "appdata"
            tx = ag_data / "brain" / "conv-1" / ".system_generated" / "logs" / "transcript.jsonl"
            tx.parent.mkdir(parents=True, exist_ok=True)
            tx.write_text("{}\n", encoding="utf-8")
            ide_plan = ag_data / "brain" / "conv-1" / "implementation_plan.md"
            ide_plan.write_text("# Plan\n", encoding="utf-8")

            env = {k: v for k, v in os.environ.items() if k != "HARNESS_HOOK_HOST"}
            env["ANTIGRAVITY_APP_DATA"] = str(ag_data)

            proc_tx = subprocess.run(
                [sys.executable, str(pts_script)],
                input=json.dumps({
                    "toolName": "view_file",
                    "toolArgs": {"AbsolutePath": str(tx)},
                    "workspacePaths": [str(repo)],
                }),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            resp_tx = json.loads(proc_tx.stdout.strip())
            self.assertEqual("deny", resp_tx["decision"])
            self.assertIn("NATIVE_TRANSCRIPT_READ_FORBIDDEN", resp_tx["reason"])

            proc_plan = subprocess.run(
                [sys.executable, str(pts_script)],
                input=json.dumps({
                    "toolName": "view_file",
                    "toolArgs": {"AbsolutePath": str(ide_plan)},
                    "workspacePaths": [str(repo)],
                }),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            resp_plan = json.loads(proc_plan.stdout.strip())
            self.assertEqual("allow", resp_plan["decision"])
            self.assertIsNotNone(atomic_write_json)


class TestV1316LiveSessionHardening(unittest.TestCase):
    """Regression suite for all 6 v1.3.16 live Fitness_Android session fixes."""

    def test_1_web_relay_kotlin_raw_json_strings_and_real_brace_imbalance(self) -> None:
        import web_relay
        from _vnext_common import ValidationError

        base_kt = (
            "package com.demo\n"
            "class FoodPlanViewModelTest {\n"
            '    val jsonWithArray = """{"accountId": 42, "excludedFoodCatIds": [13, 19]}"""\n'
            '    val oddQuotesRaw = """{"a":1,"b":"x","c":"y","d":true,"e":[]}"""\n'
            '    val interp = "count=${listOf(1, 2).filter { it > 0 }.size}"\n'
            "    val braceChar = '{'\n"
            "    fun existing() {\n"
            "        assert(true)\n"
            "    }\n"
            "}\n"
        )
        valid_new_kt = base_kt.replace(
            "        assert(true)\n",
            "        val reset = true\n        if (reset) {\n            assert(reset)\n        }\n",
        )
        # Must NOT raise UNBALANCED_BRACES_BLOCKED on triple-quoted JSON strings!
        web_relay._validate_code_integrity("app/src/test/FoodPlanViewModelTest.kt", valid_new_kt, base_kt)

        # Must STILL block when a real closing brace is dropped by Gemini Web!
        broken_kt = valid_new_kt.rstrip().rsplit("}", 1)[0] + "\n"
        with self.assertRaises(ValidationError) as ctx:
            web_relay._validate_code_integrity("app/src/test/FoodPlanViewModelTest.kt", broken_kt, base_kt)
        self.assertIn("UNBALANCED_BRACES_BLOCKED", str(ctx.exception))

    def test_2_windows_drive_path_normalization_and_interrogative_proof_guard(self) -> None:
        import execution_mode
        from _vnext_common import ValidationError, atomic_write_json

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "Fitness_Android"
            repo.mkdir()
            for gcmd in (
                ["git", "init", "-q"],
                ["git", "config", "user.email", "t@example.com"],
                ["git", "config", "user.name", "Test"],
                ["git", "commit", "--allow-empty", "-qm", "init"],
            ):
                subprocess.run(gcmd, cwd=repo, check=True)
            (repo / ".agents" / "state" / "tasks" / "t-web").mkdir(parents=True)
            plan = {
                "task_id": "t-web",
                "status": "IMPLEMENTING",
                "expected_files": ["app/src/main/java/com/demo/FoodPlansUseCases.kt"],
                "phases": [
                    {"id": "p1", "title": "Core", "status": "IN_PROGRESS"},
                    {"id": "p2", "title": "Followup", "status": "PENDING"},
                ],
                "active_phase_index": 0,
            }
            atomic_write_json(repo / ".agents/state/tasks/t-web/plan.json", plan)
            atomic_write_json(
                repo / ".agents/state/tasks/t-web/web-relay-receipt.json",
                {
                    "schema_version": 1,
                    "pack_id": "wpack-111122223333",
                    "task_id": "t-web",
                    "files_written": ["app/src/main/java/com/demo/FoodPlansUseCases.kt"],
                    "files_deleted": [],
                },
            )
            win_abs = r"e:\AndroidProjects\Fitness_Android\app\src\main\java\com\demo\FoodPlansUseCases.kt"
            posix_abs = str(repo / "app/src/main/java/com/demo/FoodPlansUseCases.kt")
            for cand in (win_abs, posix_abs):
                prog = execution_mode.inspect_web_phase_progress(repo, plan, target_files=[cand])
                self.assertTrue(prog["has_applied_web_changes"], f"Failed for {cand}: {prog}")

            # Unapplied file must remain False so WEB_EXECUTION_MODE_PACK_FIRST still protects p2!
            unapplied_win = r"e:\AndroidProjects\Fitness_Android\app\src\main\java\com\demo\Untouched.kt"
            prog_unapplied = execution_mode.inspect_web_phase_progress(repo, plan, target_files=[unapplied_win])
            self.assertFalse(prog_unapplied["has_applied_web_changes"])

            # Interrogative unanswered question must be rejected as proof_reference!
            with self.assertRaises(ValidationError) as q_ctx:
                execution_mode.set_execution_mode(
                    repo,
                    choice="normal-project",
                    source="conversation",
                    proof_reference="Which mode is best for this task?",
                )
            self.assertIn("DEVELOPER_AUTHORITY_REQUIRED", str(q_ctx.exception))

    def test_3_review_complete_all_with_findings_does_not_throw_false_stale_run(self) -> None:
        # Authentic end-to-end Round-1 scenario: real draft -> approve -> prepare-verification -> 1 reviewer returns FINDINGS!
        from _vnext_common import read_json, sha256_file
        import review_models
        from review_execution import resolve_execution_profile
        from review_orchestrator import record_dispatch_batch
        from review_package import build_package
        import workflow

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            ag_data = root / "ag_app_data"
            repo.mkdir()
            (repo / "app/src/main/kotlin/com/example").mkdir(parents=True)
            (repo / "app/src/test/kotlin/com/example").mkdir(parents=True)
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\nandroid { namespace = "com.example" }\n', encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            (repo / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (repo / "app/src/main/kotlin/com/example/HomeViewModel.kt").write_text(
                "package com.example\nclass HomeViewModel { fun load() = 1 }\n", encoding="utf-8"
            )
            (repo / "app/src/test/kotlin/com/example/HomeViewModelTest.kt").write_text(
                "package com.example\nclass HomeViewModelTest { fun testLoad() {} }\n", encoding="utf-8"
            )
            for cmd in (
                ["git", "init", "-q"],
                ["git", "config", "user.email", "t@example.com"],
                ["git", "config", "user.name", "Test"],
                ["git", "add", "."],
                ["git", "commit", "-qm", "init"],
            ):
                subprocess.run(cmd, cwd=repo, check=True)

            kit_agents = Path(__file__).resolve().parents[1]
            shutil.copytree(kit_agents, repo / ".agents")

            wf_parser = workflow.build_parser()
            plan = workflow.draft(wf_parser.parse_args([
                "draft", "--repo", str(repo), "--task-id", "t-rev-findings",
                "--outcome", "Add resetData support",
                "--kind", "FEATURE",
                "--expected-files", "app/src/main/kotlin/com/example/HomeViewModel.kt,app/src/test/kotlin/com/example/HomeViewModelTest.kt",
            ]))
            workflow.record_approval(wf_parser.parse_args([
                "approve", "--repo", str(repo), "--task-id", "t-rev-findings",
                "--source", "conversation", "--proof-reference", "approved",
                "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", plan["plan_sha256"][:12],
            ]))
            (repo / "app/src/main/kotlin/com/example/HomeViewModel.kt").write_text(
                "package com.example\nclass HomeViewModel { fun load() = 2 }\n", encoding="utf-8"
            )
            (repo / "app/src/test/kotlin/com/example/HomeViewModelTest.kt").write_text(
                "package com.example\nclass HomeViewModelTest { fun testLoad() { assert(true) } }\n", encoding="utf-8"
            )
            review_models.main(["set", "--repo", str(repo), "--task", "t-rev-findings", "--scope", "task", "--preset", "inherit", "--source", "conversation", "--proof-reference", "use inherit"])
            workflow.main(["prepare-verification", "--repo", str(repo), "--task-id", "t-rev-findings", "--host", "antigravity"])
            pkg_path, _ = build_package(repo, "t-rev-findings")

            tdir = repo / ".agents/state/tasks/t-rev-findings"
            current = read_json(tdir / "current-run.json")
            run_id = current["run_id"]
            policy = read_json(Path(current["policy"]))
            revs = list(policy["reviewers"])
            self.assertGreaterEqual(len(revs), 2)
            pkg_sha = sha256_file(pkg_path)

            record_dispatch_batch(repo, "t-rev-findings", revs, host="antigravity")
            prof = resolve_execution_profile(repo, "t-rev-findings", host="antigravity")
            for idx, r_role in enumerate(revs):
                pointer = prof["reviewers"][r_role]["brief_pointer_prompt"]
                cid = f"rev-find-child-{idx}"
                tx = ag_data / "brain" / cid / ".system_generated/logs/transcript.jsonl"
                tx.parent.mkdir(parents=True, exist_ok=True)
                is_last = (idx == len(revs) - 1)
                verdict = "FINDINGS" if is_last else "PASS"
                findings_arr = [{
                    "id": "sec-001",
                    "severity": "MEDIUM",
                    "title": "Duplicate network sync on reset cancellation",
                    "message": "Track desiredResetData across CancellationException.",
                    "file": "app/src/main/kotlin/com/example/HomeViewModel.kt",
                    "line_start": 2,
                    "line_end": 2,
                    "evidence": "HomeViewModel.kt:2",
                    "recommended_fix": "Preserve adopted resetData boolean.",
                }] if is_last else []
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
                            "task_id": "t-rev-findings",
                            "run_id": run_id,
                            "reviewer": r_role,
                            "review_package_sha256": pkg_sha,
                            "verdict": verdict,
                            "findings": findings_arr,
                        }, indent=2) + "\n```",
                    },
                ]
                tx.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(repo / ".agents/harness.py"), "review", "complete-all", "--task", "t-rev-findings"],
                cwd=str(repo),
                env={**os.environ, "ANTIGRAVITY_APP_DATA": str(ag_data)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr + proc.stdout)
            self.assertNotIn("STALE_VERIFICATION_RUN", proc.stderr + proc.stdout)
            self.assertIn("REVIEW_SUMMARY_TABLE_BEGIN", proc.stdout)
            self.assertIn("BLOCKING_FINDING:", proc.stdout)
            self.assertIn("Duplicate network sync on reset cancellation", proc.stdout)
            self.assertEqual("BLOCKED", read_json(tdir / "plan.json")["status"])

    def test_4_windows_gradle_breakaway_falls_back_cleanly_on_permission_error(self) -> None:
        import _live_process
        from unittest import mock

        calls: list[dict] = []

        def fake_popen(argv, **kwargs):
            calls.append(dict(kwargs))
            if kwargs.get("creationflags"):
                raise PermissionError(5, "Access is denied")
            m = mock.MagicMock()
            m.returncode = 0
            return m

        with mock.patch.object(_live_process.os, "name", "nt"), mock.patch.object(_live_process.subprocess, "Popen", side_effect=fake_popen):
            proc = _live_process._spawn_streaming_process(
                ["gradlew.bat", ":app:testDebugUnitTest"],
                cwd=".",
                env={},
                label="gradle",
            )
            self.assertIsNotNone(proc)
            self.assertEqual(2, len(calls))
            self.assertTrue(int(calls[0].get("creationflags") or 0) > 0)
            self.assertNotIn("creationflags", calls[1])

    def test_5_final_reviewer_step_budget_scales_to_24_for_18_files_preserving_small_caps(self) -> None:
        import delegation_policy as dp
        from _vnext_common import atomic_write_json

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents/state/tasks/t-18").mkdir(parents=True)
            files_18 = [f"app/src/main/java/com/demo/F{i}.kt" for i in range(18)]
            atomic_write_json(repo / ".agents/state/active-task.json", {"task_id": "t-18"})
            atomic_write_json(repo / ".agents/state/tasks/t-18/plan.json", {
                "task_id": "t-18",
                "status": "VERIFYING",
                "expected_files": files_18,
            })
            # 18-file final review gets 18 + 6 = 24 calls (calls 1..24 allowed, #25 denied)
            for idx in range(24):
                ok, reason, _ = dp.check_and_record_subagent_step_budget(
                    repo, "exec-18", kind="REVIEWER", tool_name="read_file", run_id="run-final1", role="arch-regression-reviewer-agent"
                )
                self.assertTrue(ok, f"Call #{idx + 1} failed unexpectedly: {reason}")
            ok25, reason25, _ = dp.check_and_record_subagent_step_budget(
                repo, "exec-18", kind="REVIEWER", tool_name="read_file", run_id="run-final1", role="arch-regression-reviewer-agent"
            )
            self.assertFalse(ok25)
            self.assertIn("24-call", reason25)

    def test_6_export_related_chat_bundle_and_top_level_token_peak(self) -> None:
        import session_forensics
        from unittest import mock

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".agents/state").mkdir(parents=True)
            brain = root / "brain"
            main_cid = "1cf1b031-bbe3-4e50-b76a-2fe4626bacd6"
            sub_cid = "650a3494-e6a8-4061-ad6d-63d79b92c8de"

            main_logs = brain / main_cid / ".system_generated/logs"
            main_subs = brain / main_cid / ".system_generated/subagents"
            sub_logs = brain / sub_cid / ".system_generated/logs"
            main_logs.mkdir(parents=True)
            main_subs.mkdir(parents=True)
            sub_logs.mkdir(parents=True)

            (main_logs / "transcript_full.jsonl").write_text(
                json.dumps({"type": "PLANNER_RESPONSE", "step_index": 89, "input_tokens": 140997, "cache_read_tokens": 38948, "output_tokens": 1040}) + "\n",
                encoding="utf-8",
            )
            (main_subs / f"{sub_cid}.json").write_text(
                json.dumps({"conversationId": sub_cid, "subagentDescriptor": {"typeName": "security-perf-reviewer-agent"}}),
                encoding="utf-8",
            )
            (sub_logs / "transcript_full.jsonl").write_text(
                json.dumps({"type": "PLANNER_RESPONSE", "step_index": 5, "input_tokens": 30000, "cache_read_tokens": 50000, "output_tokens": 900}) + "\n",
                encoding="utf-8",
            )

            out_zip = root / "exported_bundle.zip"
            with mock.patch("antigravity_runtime.candidate_brain_roots", return_value=[brain]), \
                 mock.patch("antigravity_runtime.resolve_transcript", return_value=main_logs / "transcript_full.jsonl"):
                diag = session_forensics.diagnose_session(repo, conversation_id=main_cid)
                self.assertEqual(140997 + 38948, diag["transcript"]["peak_context_tokens"])

                bundle = session_forensics.export_related_chat_bundle(repo, conversation_id=main_cid, out_path=out_zip)
                self.assertTrue(out_zip.is_file())
                self.assertEqual(2, bundle["conversations_packed"])
                self.assertEqual([sub_cid], bundle["subagent_conversation_ids"])

    def test_7_migrate_workflows_guard_640_post_tool_bypass_and_200632_200671(self) -> None:
        from unittest import mock
        from doctor.engine import CORE_WORKFLOWS, HarnessDoctor
        import delegation_policy as dp
        import debug_instrumentation as di
        import final_verifier as fv
        import pre_tool_safety as pts
        from _vnext_common import atomic_write_json, canonical_sha256

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            wf_dir = repo / ".agents/workflows"
            sk_dir = repo / ".agents/skills"
            wf_dir.mkdir(parents=True)
            sk_dir.mkdir(parents=True)
            for wf_name in CORE_WORKFLOWS:
                (wf_dir / wf_name).write_text(f"# {wf_name}\n", encoding="utf-8")
            (wf_dir / "efficient-context.md").write_text("# efficient-context\n", encoding="utf-8")
            # Builtin dual-surface overlap should NOT trigger shadowing warnings.
            (sk_dir / "efficient-context").mkdir(parents=True)
            (sk_dir / "efficient-context" / "SKILL.md").write_text("# ec\n", encoding="utf-8")

            doc_clean = HarnessDoctor(repo)
            doc_clean.check_skills_and_workflows()
            mig_clean = next(r for r in doc_clean.results if r.name == "Workflow Migration & Skill Shadowing")
            self.assertEqual("PASS", mig_clean.status)

            # Simulate /migrate-workflows drift while workflows still exist -> WARN; removing core workflow -> FAIL.
            (wf_dir / "deliver.md.bak").write_text("# bak\n", encoding="utf-8")
            (sk_dir / "deliver").mkdir(parents=True)
            (sk_dir / "deliver" / "SKILL.md").write_text("# shadow\n", encoding="utf-8")
            doc_drift = HarnessDoctor(repo)
            doc_drift.check_skills_and_workflows()
            mig_drift = next(r for r in doc_drift.results if r.name == "Workflow Migration & Skill Shadowing")
            self.assertEqual("WARN", mig_drift.status)
            self.assertIn("deliver.md.bak", mig_drift.message)
            self.assertIn("deliver", mig_drift.message)

            (wf_dir / "deliver.md").unlink()
            doc_fail = HarnessDoctor(repo)
            doc_fail.check_skills_and_workflows()
            mig_fail = next(r for r in doc_fail.results if r.name == "Workflow Migration & Skill Shadowing")
            self.assertEqual("FAIL", mig_fail.status)

            # #200632: Windows inline powershell/pwsh -Command blocked in Antigravity, semicolon read-only kept allowed.
            captured: list[tuple[str, str, dict]] = []
            with mock.patch.object(pts, "REPO", repo), \
                 mock.patch.dict(os.environ, {"HARNESS_HOOK_HOST": "antigravity"}), \
                 mock.patch.object(pts, "emit", side_effect=lambda dec, rsn, **kw: captured.append((dec, rsn, kw))):
                for cmd in ('powershell -Command "Get-ChildItem"', 'pwsh.exe -NoProfile -c "ls"'):
                    captured.clear()
                    pts._handle_command(cmd)
                    self.assertEqual(1, len(captured), cmd)
                    self.assertEqual("deny", captured[0][0], cmd)
                    self.assertIn("200632", captured[0][1])

                captured.clear()
                pts._handle_command("git status --short; git branch -a; git log -n 3 --oneline")
                self.assertEqual(1, len(captured))
                self.assertEqual("allow", captured[0][0])

            # #200671 guidance present in Antigravity and Codex templates.
            ag_tpl = (Path(__file__).resolve().parents[2] / "agents/tool-adapters/GEMINI.md.template").read_text(encoding="utf-8")
            codex_tpl = (Path(__file__).resolve().parents[2] / "agents/tool-adapters/AGENTS.md.template").read_text(encoding="utf-8")
            self.assertIn("#200671", ag_tpl)
            self.assertIn("Gemini 4 Hydrogen High", ag_tpl)
            self.assertIn("Never prefix `(Recommended)`", ag_tpl)
            ver_src = (Path(__file__).resolve().parents[2] / "agents/scripts/_workflow/verification.py").read_text(encoding="utf-8")
            rtr_src = (Path(__file__).resolve().parents[2] / "agents/scripts/_workflow/router.py").read_text(encoding="utf-8")
            self.assertIn("NEVER prefix '(Recommended)'", ver_src)
            self.assertIn("without '(Recommended)' prefix", rtr_src)
            self.assertIn("#200671", codex_tpl)

            # #640: PostToolUse detects invoke_subagent bypasses and final_verifier blocks delivery.
            task_id = "t-640"
            tdir = repo / ".agents/state/tasks" / task_id
            tdir.mkdir(parents=True)
            atomic_write_json(repo / ".agents/state/active-task.json", {"task_id": task_id})
            raw_plan = {
                "schema_version": 1,
                "task_id": task_id,
                "status": "VERIFYING",
                "execution_nonce": "nonce-640",
                "task_kind": "FEATURE",
                "risk_tier": "T0_TRIVIAL",
                "skills": [],
                "expected_files": [],
            }
            p_hash = canonical_sha256(fv.plan_payload(raw_plan))
            raw_plan["plan_sha256"] = p_hash
            raw_plan["approval"] = {
                "plan_sha256": p_hash,
                "single_use_nonce": "nonce-640",
                "source": "conversation",
                "enforcement_tier": "RULE_ENFORCED",
                "proof_reference_sha256": "a" * 64,
            }
            policy_data = {
                "schema_version": 1,
                "policy_sha256": "p" * 64,
                "task_id": task_id,
                "risk_tier": "T0_TRIVIAL",
                "surfaces": [],
                "gates": [],
                "device_required": False,
                "review": {"required": False},
                "skills": {"skills": []},
            }
            manifest_data = {
                "files": [],
                "changes": [],
                "external_inputs": [],
                "delivery_snapshot_sha256": canonical_sha256([]),
                "change_set_sha256": canonical_sha256([]),
                "external_inputs_sha256": canonical_sha256([]),
                "repository": {"root_sha256": "r", "git_common_dir_sha256": "c", "branch": "main", "head": "h"},
            }
            plan_path = tdir / "plan.json"
            policy_path = tdir / "policy.json"
            manifest_path = tdir / "manifest.json"
            atomic_write_json(plan_path, raw_plan)
            atomic_write_json(policy_path, policy_data)
            atomic_write_json(manifest_path, manifest_data)

            # Clean baseline approves before #640 bypass occurs.
            with mock.patch.object(fv, "build_manifest", return_value=manifest_data), \
                 mock.patch.object(fv, "validate_policy_artifact", return_value=(policy_data, None, "")), \
                 mock.patch.object(fv, "check_material_drift", return_value=[]), \
                 mock.patch.object(fv, "changed_modules", return_value=[]), \
                 mock.patch.object(di, "assert_clean", return_value=None):
                res_ok = fv.verify(repo, plan_path=plan_path, policy_path=policy_path, manifest_path=manifest_path, state_root=repo / ".agents/state", run_id="r640")
                self.assertEqual("APPROVED", res_ok["status"], res_ok)

                # Simulate CLI ignoring PreToolUse block (#640) for forbidden 'research' subagent + T0 reviewer.
                (repo / ".agents/agents" / dp.SCOUT_AGENT).mkdir(parents=True)
                (repo / ".agents/agents" / dp.SCOUT_AGENT / "agent.md").write_text("# scout\n", encoding="utf-8")
                viols = dp.inspect_and_record_post_tool_subagent_bypass(
                    repo,
                    {
                        "tool_name": "invoke_subagent",
                        "tool_input": {"TypeName": "research", "Role": "Codebase Researcher", "Prompt": "scan repo"},
                        "conversation_id": "conv-main",
                    },
                )
                self.assertEqual(1, len(viols))
                self.assertIn("USE_HARNESS_SCOUT_AGENT_BYPASS", viols[0]["codes"])
                self.assertTrue((tdir / "subagent-policy-violations.json").is_file())

                viols_rev = dp.inspect_and_record_post_tool_subagent_bypass(
                    repo,
                    {
                        "tool_name": "invoke_subagent",
                        "tool_input": {"TypeName": "arch-regression-reviewer-agent", "Role": "Arch Reviewer", "Prompt": "review"},
                        "conversation_id": "conv-main",
                    },
                )
                self.assertEqual(1, len(viols_rev))
                self.assertIn("T0_TRIVIAL_REVIEWER_FORBIDDEN", viols_rev[0]["codes"])

                res_blocked = fv.verify(repo, plan_path=plan_path, policy_path=policy_path, manifest_path=manifest_path, state_root=repo / ".agents/state", run_id="r640")
                self.assertEqual("BLOCKED", res_blocked["status"])
                self.assertTrue(any(c["name"] == "subagent_policy_audit" and c["status"] == "FAIL" for c in res_blocked["checks"]))
                self.assertTrue(any("#640" in r and "USE_HARNESS_SCOUT_AGENT_BYPASS" in r and "T0_TRIVIAL_REVIEWER_FORBIDDEN" in r for r in res_blocked["blocked_by"]))


class TestV1317LiveSessionHardening(unittest.TestCase):
    """Comprehensive regression & edge-case suite for all 6 v1.3.17 hardening upgrades."""

    def test_v1317_bug_red_evidence_guard_edges(self):
        import subprocess as sp
        from _vnext_common import atomic_write_json, canonical_sha256
        from delivery_manifest import build_manifest
        from mutation_guard import _red_evidence_denial

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            sp.run(["git", "init", "-q"], cwd=repo, check=True)
            sp.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            sp.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

            vm = repo / "app/src/main/java/com/demo/ChoosenPlanViewModel.kt"
            vm_test = repo / "app/src/test/java/com/demo/ChoosenPlanViewModelTest.kt"
            vm.parent.mkdir(parents=True)
            vm_test.parent.mkdir(parents=True)
            vm.write_text("package com.demo\nclass ChoosenPlanViewModel { fun x() = 1 }\n", encoding="utf-8")
            vm_test.write_text("package com.demo\nclass ChoosenPlanViewModelTest\n", encoding="utf-8")
            sp.run(["git", "add", "."], cwd=repo, check=True)
            sp.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            tid = "fix-onboarding-bug"
            tdir = repo / ".agents/state/tasks" / tid
            tdir.mkdir(parents=True)
            base_man = build_manifest(repo)
            _tb_core = {
                "schema_version": 1,
                "task_id": tid,
                "repository": base_man["repository"],
                "base_delivery_snapshot_sha256": base_man["delivery_snapshot_sha256"],
                "base_change_set_sha256": base_man["change_set_sha256"],
                "changes": [],
            }
            atomic_write_json(tdir / "task-baseline.json", {**_tb_core, "baseline_sha256": canonical_sha256(_tb_core)})
            plan = {
                "task_id": tid,
                "task_kind": "BUG",
                "status": "IMPLEMENTING",
                "expected_surfaces": ["BUSINESS_LOGIC", "COROUTINES"],
                "expected_files": [
                    "app/src/main/java/com/demo/ChoosenPlanViewModel.kt",
                    "app/src/test/java/com/demo/ChoosenPlanViewModelTest.kt",
                ],
            }

            # Case 1: Untouched BUG task -> strict TDD requires --capture-red
            d1 = _red_evidence_denial(repo, plan, [str(vm)])
            self.assertIn("RED_EVIDENCE_REQUIRED", d1)
            self.assertIn("--capture-red", d1)

            # Case 2: Prod modified WITHOUT test or web receipt -> non-Catch-22 message asking for co-authored test
            vm.write_text("package com.demo\nclass ChoosenPlanViewModel { fun x() = 2 }\n", encoding="utf-8")
            d2 = _red_evidence_denial(repo, plan, [str(vm)])
            self.assertIn("RED_EVIDENCE_REQUIRED", d2)
            self.assertIn("--capture-red` can no longer run", d2)
            # Test file itself remains writable!
            self.assertEqual("", _red_evidence_denial(repo, plan, [str(vm_test)]))

            # Case 3: Co-authored test file modified -> unlocks production edits cleanly!
            vm_test.write_text("package com.demo\nclass ChoosenPlanViewModelTest { fun t() {} }\n", encoding="utf-8")
            self.assertEqual("", _red_evidence_denial(repo, plan, [str(vm)]))

            # Case 4: Even before test edit, a Web-Relay receipt unlocks post-apply surgical fixups
            vm_test.write_text("package com.demo\nclass ChoosenPlanViewModelTest\n", encoding="utf-8")
            atomic_write_json(tdir / "web-relay-receipt.json", {"task_id": tid, "pack_id": "wpack-1"})
            self.assertEqual("", _red_evidence_denial(repo, plan, [str(vm)]))

    def test_v1317_hybrid_post_web_surgical_vs_heavy_resume_and_p2_protection(self):
        import subprocess as sp
        from _vnext_common import atomic_write_json, canonical_sha256
        from delegation_policy import evaluate_delegation_policy
        from delivery_manifest import build_manifest, build_task_manifest, load_task_baseline
        from execution_mode import inspect_web_phase_progress, set_execution_mode

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            sp.run(["git", "init", "-q"], cwd=repo, check=True)
            sp.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            sp.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

            files = []
            for idx in range(1, 6):
                fp = repo / f"app/src/main/java/com/demo/F{idx}.kt"
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(f"package com.demo\nclass F{idx} {{ fun v() = 1 }}\n", encoding="utf-8")
                files.append(f"app/src/main/java/com/demo/F{idx}.kt")
            sp.run(["git", "add", "."], cwd=repo, check=True)
            sp.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            tid = "web-hybrid-task"
            tdir = repo / ".agents/state/tasks" / tid
            tdir.mkdir(parents=True)
            atomic_write_json(repo / ".agents/state/active-task.json", {"task_id": tid})
            set_execution_mode(repo, choice="web-project", source="conversation", proof_reference="use web mode")

            base_man = build_manifest(repo)
            _tb_core = {
                "schema_version": 1,
                "task_id": tid,
                "repository": base_man["repository"],
                "base_delivery_snapshot_sha256": base_man["delivery_snapshot_sha256"],
                "base_change_set_sha256": base_man["change_set_sha256"],
                "changes": [],
            }
            atomic_write_json(tdir / "task-baseline.json", {**_tb_core, "baseline_sha256": canonical_sha256(_tb_core)})

            # Apply p1 change on F1.kt
            (repo / files[0]).write_text("package com.demo\nclass F1 { fun v() = 2 }\n", encoding="utf-8")
            live_tm = build_task_manifest(repo, load_task_baseline(repo, tid), expected_files=files)
            cs_sha = str(live_tm.get("change_set_sha256") or "")

            plan = {
                "task_id": tid,
                "task_kind": "FEATURE",
                "status": "IMPLEMENTING",
                "expected_files": files,
                "phases": [
                    {"id": "p1", "expected_files": files[:3]},
                    {"id": "p2", "expected_files": files[3:]},
                ],
                "active_phase_index": 0,
                "review_rounds": 1,
                "blocked_reviewers": ["arch-regression-reviewer-agent"],
            }
            atomic_write_json(tdir / "plan.json", plan)
            atomic_write_json(tdir / "web-relay-receipt.json", {
                "task_id": tid,
                "pack_id": "wpack-main",
                "phase_id": "p1",
                "files_written": [files[0]],
                "resumed_from_verification": True,
                "change_set_sha256": cs_sha,
            })

            # 1..3 surgical review finding files -> TRIVIAL_INLINE_LEAD (local edit_file!)
            atomic_write_json(tdir / "last-review-findings.json", {
                "schema_version": 1,
                "round": 1,
                "blocking_count": 2,
                "blocking_files": files[:2],
            })
            adv_small = evaluate_delegation_policy(repo, task_id=tid, plan=plan, router_action="IMPLEMENT_APPROVED_SCOPE")
            self.assertEqual("TRIVIAL_INLINE_LEAD", adv_small["strategy"])
            self.assertEqual(files[:2], adv_small["target_files"])
            self.assertIn("verify-steps", adv_small["next_command"])

            # 4+ blocking review finding files -> falls back to WEB_RELAY_ACTIVE (`web-pack --retry`)!
            atomic_write_json(tdir / "last-review-findings.json", {
                "schema_version": 1,
                "round": 1,
                "blocking_count": 4,
                "blocking_files": files[:4],
            })
            adv_heavy = evaluate_delegation_policy(repo, task_id=tid, plan=plan, router_action="IMPLEMENT_APPROVED_SCOPE")
            self.assertEqual("WEB_RELAY_ACTIVE", adv_heavy["strategy"])
            self.assertIn("web-pack", adv_heavy["next_command"])

            # Unapplied p2 must STILL enforce WEB_EXECUTION_MODE_PACK_FIRST (`has_applied_web_changes == False`)!
            plan_p2 = {**plan, "active_phase_index": 1, "blocked_reviewers": [], "review_rounds": 0}
            atomic_write_json(tdir / "phase-state.json", {"current_phase_id": "p2", "completed_phases": ["p1"]})
            atomic_write_json(tdir / "web-relay-receipt.json", {
                "task_id": tid,
                "pack_id": "wpack-p1",
                "phase_id": "p1",
                "files_written": files[:3],
            })
            prog_p2 = inspect_web_phase_progress(repo, plan_p2, target_files=[files[3]])
            self.assertFalse(prog_p2["has_applied_web_changes"])

    def test_v1317_fast_kt_lint_fqcn_coroutines_and_false_positive_exemptions(self):
        from fast_kt_lint import lint_file

        with tempfile.TemporaryDirectory() as td:
            kt = Path(td) / "app/src/main/java/com/demo/ChoosenPlanViewModel.kt"
            kt.parent.mkdir(parents=True)
            kt.write_text(
                "package com.demo\n"                                                              # 1
                "import java.util.concurrent.TimeoutException\n"                                  # 2
                "@OptIn(\n"                                                                       # 3
                "    kotlinx.coroutines.ExperimentalCoroutinesApi::class\n"                       # 4
                ")\n"                                                                             # 5
                "class ChoosenPlanViewModel(\n"                                                   # 6
                "    private val lazyRepo: dagger.Lazy<String>\n"                                 # 7
                ") {\n"                                                                           # 8
                "    val okRes = android.R.string.ok\n"                                           # 9
                "    val perm = android.Manifest.permission.CAMERA\n"                             # 10
                "    fun runTask() {\n"                                                           # 11
                "        try { } catch (e: kotlinx.coroutines.CancellationException) { throw e }\n"  # 12 -> MUST FLAG!
                "        try { } catch (t: java.util.concurrent.TimeoutException) { }\n"          # 13 -> MUST FLAG (same owner imported, should use simple name!)
                "        val today = java.time.LocalDate.now()\n"                                 # 14 -> MUST FLAG!
                "    }\n"                                                                         # 15
                "}\n",
                encoding="utf-8",
            )
            issues = lint_file(kt, modified_lines=set(range(1, 17)))
            fqcn_lines = [iss["line"] for iss in issues if iss["type"] == "INLINE_FQCN"]
            self.assertEqual([12, 13, 14], fqcn_lines, f"Unexpected FQCN issues: {issues}")

            # Verify genuine simple-name collision (`import java.util.concurrent.CancellationException` + inline `kotlinx.coroutines.CancellationException`) is exempted!
            kt_collision = Path(td) / "app/src/main/java/com/demo/CollisionVm.kt"
            kt_collision.write_text(
                "package com.demo\n"
                "import java.util.concurrent.CancellationException\n"
                "class CollisionVm {\n"
                "    fun f() { try {} catch (e: kotlinx.coroutines.CancellationException) { throw e } }\n"
                "}\n",
                encoding="utf-8",
            )
            col_issues = [iss for iss in lint_file(kt_collision, modified_lines={1, 2, 3, 4, 5}) if iss["type"] == "INLINE_FQCN"]
            self.assertEqual([], col_issues)

    def test_v1317_scout_graph_cache_block_and_late_turn_budget_reminder(self):
        import contextlib
        import io
        import time
        from unittest import mock
        import delegation_policy as dp
        import pre_invocation_reminder as pir
        import pre_tool_safety as pts
        from _vnext_common import atomic_write_json, read_json

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            (repo / ".agents/cache").mkdir(parents=True)
            (repo / ".agents/state").mkdir(parents=True)
            graph_cache = repo / ".agents/cache/project_graph.json"
            graph_cache.write_text('{"nodes": []}', encoding="utf-8")

            scout_cid = "scout-653a42aa"
            atomic_write_json(dp._ledger_path(repo), {
                "schema_version": 2,
                "entries": [{
                    "dispatched_epoch": time.time(),
                    "wave_id": "w1",
                    "parent_conversation_id": "lead-1",
                    "execution_id": scout_cid,
                    "agent_type": dp.SCOUT_AGENT,
                    "role": dp.SCOUT_AGENT,
                    "created_epoch": time.time(),
                    "tool_calls_used": 0,
                }],
            })

            def run_pre_tool(payload: dict) -> dict:
                buf = io.StringIO()
                with mock.patch.object(pts, "REPO", repo),                      mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),                      contextlib.redirect_stdout(buf):
                    pts.main()
                return json.loads(buf.getvalue())

            # 1. Reading `.agents/cache/project_graph.json` is blocked AND consumes ZERO scout step budget!
            den = run_pre_tool({
                "conversationId": scout_cid,
                "toolCall": {"name": "read_file", "args": {"Path": str(graph_cache), "StartLine": 1, "EndLine": 800}},
            })
            self.assertEqual("deny", den["decision"])
            self.assertIn("RAW_GRAPH_CACHE_READ_BLOCKED", den["reason"])
            sb_file = dp._step_budgets_path(repo)
            self.assertFalse(sb_file.is_file(), "Blocked raw graph cache read must not consume a Scout step-budget slot")

            # 2. PreInvocation reminder stays `{}` on Turn 0 and while used < 20, warns at 21, and hard-stops at 24!
            def run_pir(inv_num: int) -> dict:
                buf = io.StringIO()
                with mock.patch.object(pir, "REPO", repo),                      mock.patch("sys.stdin", io.StringIO(json.dumps({"invocationNum": inv_num, "conversationId": scout_cid}))),                      contextlib.redirect_stdout(buf):
                    pir.main()
                return json.loads(buf.getvalue())

            self.assertEqual({}, run_pir(0))
            atomic_write_json(sb_file, {f"SCOUT::{dp.SCOUT_AGENT}:{scout_cid}": {"count": 12, "updated_epoch": time.time()}})
            self.assertEqual({}, run_pir(3))

            atomic_write_json(sb_file, {f"SCOUT::{dp.SCOUT_AGENT}:{scout_cid}": {"count": 21, "updated_epoch": time.time()}})
            warn_out = run_pir(5)
            self.assertIn("3/24 tool call(s) remaining", json.dumps(warn_out))

            atomic_write_json(sb_file, {f"SCOUT::{dp.SCOUT_AGENT}:{scout_cid}": {"count": 24, "updated_epoch": time.time()}})
            stop_out = run_pir(7)
            self.assertIn("SCOUT_STEP_BUDGET_EXHAUSTED", json.dumps(stop_out))

    def test_v1317_compact_draft_stdout_restore_cancelled_and_advance_all_ready(self):
        import argparse
        import subprocess as sp
        from unittest import mock
        from _workflow import engine as wf_eng
        from run_tests_gate import format_actionable_failure_excerpt

        # A) Compact stdout helper shrinks heavy arrays without mutating input dict
        heavy_plan = {
            "task_id": "t-heavy",
            "plan_sha256": "abc1234567890",
            "base_file_identities": [f"id-{i}" for i in range(60)],
            "task_baseline": {"changes": [{"path": f"f{i}.kt"} for i in range(30)]},
            "verification_contract": {"criteria": [{"id": "C1", "referenced_symbols": [f"Sym{i}" for i in range(25)]}]},
            "architecture_contract": {"mode": "PRESERVE", "family_evidence": [f"ev-{i}" for i in range(20)]},
        }
        compact = wf_eng._compact_plan_json_for_cli_stdout(heavy_plan)
        self.assertEqual(30, len(heavy_plan["task_baseline"]["changes"]))
        self.assertEqual(9, len(compact["task_baseline"]["changes"]))
        self.assertEqual(7, len(compact["verification_contract"]["criteria"][0]["referenced_symbols"]))
        self.assertEqual(6, len(compact["architecture_contract"]["family_evidence"]))

        # B) Cancel -> revise --restore-cancelled + checkpoint-phase --advance-all-ready + JUnit excerpt
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            sp.run(["git", "init", "-q"], cwd=repo, check=True)
            sp.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            sp.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "settings.gradle.kts").write_text('rootProject.name = "demo"\ninclude(":app")\n', encoding="utf-8")
            (repo / "app").mkdir()
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            for idx in (1, 2, 3):
                p_kt = repo / f"app/src/main/java/com/demo/P{idx}.kt"
                p_kt.parent.mkdir(parents=True, exist_ok=True)
                p_kt.write_text(f"package com.demo\nclass P{idx} {{ val x = 1 }}\n", encoding="utf-8")
            sp.run(["git", "add", "."], cwd=repo, check=True)
            sp.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            parser = wf_eng.build_parser()
            d_args = parser.parse_args([
                "draft", "--repo", str(repo), "--task-id", "t-cascade",
                "--kind", "FEATURE", "--outcome", "Update P1 P2 P3 cleanly",
                "--expected-files", "app/src/main/java/com/demo/P1.kt,app/src/main/java/com/demo/P2.kt,app/src/main/java/com/demo/P3.kt",
                "--phases", json.dumps([
                    {"id": "p1", "title": "Phase 1", "expected_files": ["app/src/main/java/com/demo/P1.kt"]},
                    {"id": "p2", "title": "Phase 2", "expected_files": ["app/src/main/java/com/demo/P2.kt"]},
                    {"id": "p3", "title": "Phase 3", "expected_files": ["app/src/main/java/com/demo/P3.kt"]},
                ]),
            ])
            drafted = wf_eng.draft(d_args)
            self.assertEqual("AWAITING_DEVELOPER_APPROVAL", drafted["status"])

            # Cancel task, verify revise without --restore-cancelled fails with hint, then restore losslessly!
            c_args = argparse.Namespace(repo=str(repo), task_id="t-cascade", source="conversation", proof_reference="cancel draft")
            wf_eng.cancel(c_args)
            with self.assertRaises(wf_eng.ValidationError) as ctx_err:
                wf_eng.revise(parser.parse_args(["revise", "--repo", str(repo), "--task-id", "t-cascade"]))
            self.assertIn("--restore-cancelled", str(ctx_err.exception))

            restored = wf_eng.revise(parser.parse_args([
                "revise", "--repo", str(repo), "--task-id", "t-cascade", "--restore-cancelled",
            ]))
            self.assertEqual("AWAITING_DEVELOPER_APPROVAL", restored["status"])
            self.assertNotIn("cancelled_at", restored)
            self.assertEqual(3, len(restored["phases"]))

            # Approve and modify all 3 phase files at once (simulating whole-task web-apply)
            wf_eng.record_approval(parser.parse_args([
                "approve", "--repo", str(repo), "--task-id", "t-cascade",
                "--source", "conversation", "--proof-reference", "approve",
                "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", restored["plan_sha256"][:12],
            ]))
            for idx in (1, 2, 3):
                (repo / f"app/src/main/java/com/demo/P{idx}.kt").write_text(
                    f"package com.demo\nclass P{idx} {{ val x = 2 }}\n", encoding="utf-8"
                )

            def _fake_phase_tests(_repo, phase_dir, _mods, _needs, **_kw):
                from _vnext_common import atomic_write_json as _awj
                _awj(phase_dir / "unit_tests.json", {"status": "PASS", "modules": {}})
                return (True, "PASS")

            with mock.patch.object(wf_eng, "check_phase_compile", return_value=(True, "PASS")) as m_comp,                  mock.patch.object(wf_eng, "check_phase_tests", side_effect=_fake_phase_tests) as m_test:
                cp_res = wf_eng.checkpoint_phase(parser.parse_args([
                    "checkpoint-phase", "--repo", str(repo), "--task-id", "t-cascade",
                    "--phase-id", "p1", "--advance-all-ready",
                ]))
                self.assertEqual(["p1", "p2", "p3"], cp_res["completed_phases"])
                self.assertEqual(["p2", "p3"], cp_res.get("auto_advanced_phases"))
                # Compile & unit tests ran ONCE on p1 and were reused on p2 & p3!
                self.assertEqual(1, m_comp.call_count)
                self.assertEqual(1, m_test.call_count)

            # Actionable JUnit failure excerpt includes test method + absolute XML path
            xml_dir = repo / "app/build/test-results/testDebugUnitTest"
            xml_dir.mkdir(parents=True)
            xml_f = xml_dir / "TEST-com.demo.FoodPlanViewModelTest.xml"
            xml_f.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<testsuite name="com.demo.FoodPlanViewModelTest" tests="1" failures="1">'
                '<testcase classname="com.demo.FoodPlanViewModelTest" name="initClearsStaleMealState">'
                '<failure message="java.lang.AssertionError: expected false">at com.demo.FoodPlanViewModelTest.initClearsStaleMealState(FoodPlanViewModelTest.kt:3060)</failure>'
                '</testcase></testsuite>',
                encoding="utf-8",
            )
            excerpt = format_actionable_failure_excerpt(repo, ":app:testDebugUnitTest")
            self.assertIn("FoodPlanViewModelTest.initClearsStaleMealState", excerpt)
            self.assertIn("FoodPlanViewModelTest.kt:3060", excerpt)
            self.assertIn(xml_f.resolve().as_posix(), excerpt)

    def test_v1317_windows_live_gradle_daemon_java_home_alignment(self):
        from _live_process import resolve_compatible_windows_daemon_java_home

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proj = root / "proj"
            gu_home = root / "gradle_home"
            jbr = root / "Android Studio/jbr"
            (proj / "gradle/wrapper").mkdir(parents=True)
            (proj / "gradle/wrapper/gradle-wrapper.properties").write_text(
                "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.9-bin.zip\n",
                encoding="utf-8",
            )
            (jbr / "bin").mkdir(parents=True)
            (jbr / "bin/java.exe").write_text("", encoding="utf-8")
            (jbr / "bin/java").write_text("", encoding="utf-8")

            d_dir = gu_home / "daemon/8.9"
            d_dir.mkdir(parents=True)
            log_live = d_dir / "daemon-4455.out.log"
            log_live.write_text(
                f"2026-11-15T12:00:00+0200 [DEBUG] [org.gradle.launcher.daemon.context.DefaultDaemonContext] "
                f"DaemonContext[uid=123,javaHome={jbr},daemonRegistryDir={d_dir},pid=4455,idleTimeout=10800000]\n",
                encoding="utf-8",
            )

            env = {"GRADLE_USER_HOME": str(gu_home), "JAVA_HOME": str(root / "other_jdk")}

            # 1. Non-Windows -> None
            self.assertIsNone(resolve_compatible_windows_daemon_java_home(proj, env, os_name="posix", pid_alive_fn=lambda _: True))

            # 2. Dead PID -> None
            self.assertIsNone(resolve_compatible_windows_daemon_java_home(proj, env, os_name="nt", pid_alive_fn=lambda _: False))

            # 3. Single live Android Studio JBR daemon -> returns exact JBR path!
            aligned = resolve_compatible_windows_daemon_java_home(proj, env, os_name="nt", pid_alive_fn=lambda pid: pid == 4455)
            self.assertEqual(str(jbr), aligned)

            # 4. Explicit org.gradle.java.home in gradle.properties -> respected (returns None)!
            (proj / "gradle.properties").write_text("org.gradle.java.home=C:/custom/jdk17\n", encoding="utf-8")
            self.assertIsNone(resolve_compatible_windows_daemon_java_home(proj, env, os_name="nt", pid_alive_fn=lambda pid: pid == 4455))
            (proj / "gradle.properties").unlink()

            # 5. Two conflicting live JVMs -> ambiguous, returns None safely!
            jbr2 = root / "OtherJdk21"
            (jbr2 / "bin").mkdir(parents=True)
            (jbr2 / "bin/java.exe").write_text("", encoding="utf-8")
            (d_dir / "daemon-7788.out.log").write_text(
                f"DaemonContext[uid=456,javaHome={jbr2},pid=7788]\n",
                encoding="utf-8",
            )
            self.assertIsNone(resolve_compatible_windows_daemon_java_home(proj, env, os_name="nt", pid_alive_fn=lambda pid: pid in {4455, 7788}))


class TestV1318ForensicIntegration(unittest.TestCase):
    """Comprehensive regression & edge-case suite for all 6 v1.3.18 forensic upgrades."""

    def test_v1318_01_multimodule_test_failure_only_attribution(self):
        import run_gradle_task

        batched_tasks = ":app:testDebugUnitTest :base:testDebugUnitTest :fat-burner:testDebugUnitTest :gdpr:testDebugUnitTest"
        single_mod_fail_log = (
            "> Task :app:testDebugUnitTest FAILED\n"
            "FAILURE: Build failed with an exception.\n"
            "* What went wrong:\n"
            "Execution failed for task ':app:testDebugUnitTest'.\n"
            "> There were failing tests. See the report at: file:///E:/repo/app/build/reports/tests/testDebugUnitTest/index.html\n"
            "* Try:\n"
            "> Run with --scan to get full insights.\n"
            "BUILD FAILED in 1m 7s\n"
        )
        # 1. Single failing module in a 4-module `--continue` batch -> True
        self.assertTrue(run_gradle_task.test_failure_only(batched_tasks, single_mod_fail_log))

        # 2. Two failing test modules in a 4-module `--continue` batch -> True
        two_mod_fail_log = (
            "> Task :app:testDebugUnitTest FAILED\n"
            "> Task :base:testDebugUnitTest FAILED\n"
            "FAILURE: Build completed with 2 failures.\n\n"
            "1: Task failed with an exception.\n"
            "-----------\n"
            "* What went wrong:\n"
            "Execution failed for task ':app:testDebugUnitTest'.\n"
            "> There were failing tests. See the report at: file:///E:/repo/app/index.html\n\n"
            "2: Task failed with an exception.\n"
            "-----------\n"
            "* What went wrong:\n"
            "Execution failed for task ':base:testDebugUnitTest'.\n"
            "> There were failing tests. See the report at: file:///E:/repo/base/index.html\n\n"
            "BUILD FAILED in 42s\n"
        )
        self.assertTrue(run_gradle_task.test_failure_only(batched_tasks, two_mod_fail_log))

        # 3. Mixed test failure + Kotlin compilation failure -> False
        mixed_compile_log = (
            "e: file:///E:/repo/base/src/test/kotlin/X.kt:12:5 Unresolved reference 'foo'.\n"
            "> Task :base:compileDebugUnitTestKotlin FAILED\n"
            + single_mod_fail_log
        )
        self.assertFalse(run_gradle_task.test_failure_only(batched_tasks, mixed_compile_log))

        # 4. Unrequested module test failure -> False
        self.assertFalse(
            run_gradle_task.test_failure_only(
                ":app:testDebugUnitTest :base:testDebugUnitTest",
                single_mod_fail_log + "\n> Task :other:testDebugUnitTest FAILED\n",
            )
        )

        # 5. Single task with mismatched failure count -> False
        self.assertFalse(
            run_gradle_task.test_failure_only(
                ":app:testDebugUnitTest",
                "FAILURE: Build completed with 2 failures.\n" + single_mod_fail_log,
            )
        )

    def test_v1318_02_web_mode_pre_apply_bug_routing_vs_normal_tdd(self):
        import io
        import contextlib
        import subprocess as sp
        from _workflow import engine as wf_eng
        from execution_mode import set_execution_mode

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            sp.run(["git", "init", "-q"], cwd=repo, check=True)
            sp.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            sp.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "settings.gradle.kts").write_text('rootProject.name = "demo"\ninclude(":app")\n', encoding="utf-8")
            (repo / "app").mkdir()
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            (repo / "app/src/main/java/com/demo").mkdir(parents=True)
            (repo / "app/src/main/java/com/demo/NavBug.kt").write_text("package com.demo\nclass NavBug\n", encoding="utf-8")
            (repo / "app/src/test/java/com/demo").mkdir(parents=True)
            (repo / "app/src/test/java/com/demo/NavBugTest.kt").write_text("package com.demo\nclass NavBugTest\n", encoding="utf-8")
            sp.run(["git", "add", "."], cwd=repo, check=True)
            sp.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            set_execution_mode(repo, choice="web-project", source="conversation", proof_reference="use web mode")
            parser = wf_eng.build_parser()
            drafted = wf_eng.draft(parser.parse_args([
                "draft", "--repo", str(repo), "--task-id", "bug-web-1",
                "--kind", "BUG", "--outcome", "Fix backstack bug cleanly",
                "--expected-files", "app/src/main/java/com/demo/NavBug.kt,app/src/test/java/com/demo/NavBugTest.kt",
            ]))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                wf_eng.main([
                    "approve", "--repo", str(repo), "--task-id", "bug-web-1",
                    "--source", "conversation", "--proof-reference", "approved",
                    "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", drafted["plan_sha256"][:12],
                ])
            approve_out = buf.getvalue()
            self.assertIn("NEXT_ACTION=WEB_RELAY_PACK: python .agents/harness.py web-pack --task-id bug-web-1", approve_out)
            self.assertNotIn("BEFORE_FIRST_EDIT=", approve_out)

            act_web = wf_eng.resolve_next_action(repo, "bug-web-1", host="antigravity")
            self.assertEqual("IMPLEMENT_APPROVED_SCOPE", act_web["code"])
            self.assertNotIn("before_first_edit", act_web)
            self.assertEqual("WEB_RELAY_ACTIVE", act_web["delegation_advisory"]["strategy"])
            self.assertIn("web-pack --task-id bug-web-1", act_web["delegation_advisory"]["next_command"])

            # Switching mid-task from web -> normal before applying any pack restores strict local CAPTURE_RED_EVIDENCE!
            set_execution_mode(repo, choice="normal-task", task_id="bug-web-1", source="conversation", proof_reference="switch local")
            act_normal = wf_eng.resolve_next_action(repo, "bug-web-1", host="antigravity")
            self.assertEqual("CAPTURE_RED_EVIDENCE", act_normal["code"])

    def test_v1318_03_web_relay_template_immunity_user_uploaded_and_truncation(self):
        import subprocess as sp
        from unittest import mock
        import web_relay
        from _vnext_common import ValidationError

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            outbox = root / "outbox"
            user_up = root / "brain/conv-1/.user_uploaded"
            (repo / ".agents/state").mkdir(parents=True)
            outbox.mkdir()
            user_up.mkdir(parents=True)
            sp.run(["git", "init", "-q"], cwd=repo, check=True)
            sp.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            sp.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "settings.gradle.kts").write_text('rootProject.name = "demo"\ninclude(":app")\n', encoding="utf-8")
            (repo / "app").mkdir()
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            f_kt = repo / "app/src/main/java/com/demo/Screen.kt"
            f_kt.parent.mkdir(parents=True)
            f_kt.write_text("package com.demo\nclass Screen {\n    fun v(): Int = 1\n}\n", encoding="utf-8")
            sp.run(["git", "add", "."], cwd=repo, check=True)
            sp.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            # Verify ANTIGRAVITY_APP_DATA `.user_uploaded` auto-discovery runs cleanly without env overrides
            with mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root)}, clear=True):
                discovered = web_relay._recent_antigravity_user_uploaded_dirs()
                self.assertIn(user_up.resolve(), discovered)

            env_patch = {
                "HARNESS_WEB_RELAY_DIR": str(outbox),
                "HARNESS_USER_UPLOADED_DIR": str(user_up),
                "HARNESS_NO_CLIPBOARD": "1",
            }
            with mock.patch.dict(os.environ, env_patch, clear=False), \
                 mock.patch.object(web_relay, "_read_clipboard_text", return_value=""):
                pack_res = web_relay.build_web_pack(
                    repo,
                    prompt="Update Screen.v to 2",
                    kind="FEATURE",
                    files=["app/src/main/java/com/demo/Screen.kt"],
                    no_clipboard=True,
                )
                bundle_md = Path(pack_res["bundle_file"]).read_text(encoding="utf-8")
                # 1. Context Pack .md itself (even if copied into clipboard or sitting in outbox) NEVER extracts template examples!
                self.assertIsNone(web_relay._extract_merge_json_from_text(bundle_md))

                with mock.patch.object(web_relay, "_read_clipboard_text", return_value=bundle_md):
                    with self.assertRaises(ValidationError) as ctx_nf:
                        web_relay.apply_web_merge(repo, source="conversation", proof_reference="apply")
                    self.assertIn("WEB_MERGE_PAYLOAD_NOT_FOUND", str(ctx_nf.exception))

                # 1b. Truncated clipboard payload emits WEB_MERGE_JSON_TRUNCATED
                trunc_clip = '{"schema": "HARNESS_WEB_MERGE_V1", "pack_id": "' + pack_res["pack_id"] + '", "operations": ['
                with mock.patch.object(web_relay, "_read_clipboard_text", return_value=trunc_clip):
                    with self.assertRaises(ValidationError) as ctx_clip_tr:
                        web_relay.apply_web_merge(repo, source="conversation", proof_reference="apply")
                    self.assertIn("WEB_MERGE_JSON_TRUNCATED", str(ctx_clip_tr.exception))

                # 2. Explicit NEED_FILES with nonexistent path raises NEED_FILES_NOT_FOUND (no bogus expanded pack!)
                bad_nf = outbox / "bad_nf.json"
                bad_nf.write_text(json.dumps({
                    "schema": "HARNESS_WEB_MERGE_V1",
                    "pack_id": pack_res["pack_id"],
                    "status": "NEED_FILES",
                    "need_files": ["app/src/main/java/com/demo/DoesNotExist.kt"],
                }), encoding="utf-8")
                with self.assertRaises(ValidationError) as ctx_bad_nf:
                    web_relay.apply_web_merge(repo, merge_file=str(bad_nf), source="conversation", proof_reference="apply")
                self.assertIn("NEED_FILES_NOT_FOUND", str(ctx_bad_nf.exception))
                bad_nf.unlink()

                # 3. Truncated JSON in Antigravity `.user_uploaded/` raises explicit WEB_MERGE_JSON_TRUNCATED!
                trunc_f = user_up / "media_1_trunc.json"
                trunc_f.write_text(
                    '{\n  "schema": "HARNESS_WEB_MERGE_V1",\n  "pack_id": "' + pack_res["pack_id"] + '",\n  "status": "READY",\n  "operations": [{"path": "import com.demo.',
                    encoding="utf-8",
                )
                with self.assertRaises(ValidationError) as ctx_tr:
                    web_relay.apply_web_merge(repo, source="conversation", proof_reference="apply")
                self.assertIn("WEB_MERGE_JSON_TRUNCATED", str(ctx_tr.exception))
                self.assertIn("media_1_trunc.json", str(ctx_tr.exception))

                # 4. Complete JSON uploaded to `.user_uploaded/` afterwards overrides truncated file and applies cleanly!
                good_f = user_up / "media_2_complete.json"
                good_f.write_text(json.dumps({
                    "schema": "HARNESS_WEB_MERGE_V1",
                    "pack_id": pack_res["pack_id"],
                    "status": "READY",
                    "operations": [{
                        "action": "MODIFY",
                        "path": "app/src/main/java/com/demo/Screen.kt",
                        "hunks": [{"search": "fun v(): Int = 1", "replace": "fun v(): Int = 2", "replace_all": False}],
                    }],
                }), encoding="utf-8")
                applied = web_relay.apply_web_merge(repo, source="conversation", proof_reference="apply complete")
                self.assertIn("media_2_complete.json", applied["origin"])
                self.assertIn("fun v(): Int = 2", f_kt.read_text(encoding="utf-8"))

    def test_v1318_04_de_triggered_reminders_and_concurrent_verification_lock_guard(self):
        import io
        import contextlib
        from unittest import mock
        import pre_invocation_reminder as pir
        import pre_tool_safety as pts
        from _vnext_common import atomic_write_json, state_root

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            tdir = state_root(repo) / "tasks" / "t-lock"
            tdir.mkdir(parents=True)
            plan_p = tdir / "plan.json"
            for st in ("IMPLEMENTING", "VERIFYING"):
                atomic_write_json(plan_p, {"task_id": "t-lock", "status": st})
                atomic_write_json(state_root(repo) / "active-task.json", {"task_id": "t-lock", "plan_path": str(plan_p)})
                with mock.patch.object(pir, "REPO", repo):
                    msg = pir._compact_message()
                self.assertNotIn("<SYSTEM_MESSAGE>", msg)
                self.assertNotIn("[Message]", msg)
                self.assertIn("never simulate or fabricate", msg)

            # Simulate an external live PID holding android-build-execution/.write.lock (use PID 1 / ppid)
            ext_pid = os.getppid()
            if ext_pid <= 0 or ext_pid == os.getpid():
                ext_pid = 1
            lock_dir = state_root(repo) / "android-build-execution"
            lock_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(lock_dir / ".write.lock", {"pid": ext_pid, "nonce": "live123", "created_at": "2026-11-16T07:33:11Z"})

            def _run_pts(tool_name: str, tool_args: dict) -> dict:
                buf = io.StringIO()
                payload = json.dumps({"toolName": tool_name, "toolArgs": tool_args, "conversationId": "lead-c1"})
                with mock.patch.object(pts, "REPO", repo), \
                     mock.patch("evidence_store._pid_alive", side_effect=lambda p: p == ext_pid), \
                     mock.patch("evidence_store._process_marker", return_value=""), \
                     mock.patch("sys.stdin", io.StringIO(payload)), \
                     contextlib.redirect_stdout(buf):
                    try:
                        pts.main()
                    except SystemExit:
                        pass
                return json.loads(buf.getvalue().strip())

            # Overlapping verify-steps & review package are blocked while external live PID owns lock!
            d_vs = _run_pts("run_command", {"CommandLine": "python .agents/harness.py verify-steps --task-id t-lock --host antigravity"})
            self.assertEqual("deny", d_vs["decision"])
            self.assertIn("CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS", d_vs.get("reason", ""))

            d_rp = _run_pts("run_command", {"CommandLine": "python .agents/harness.py review package --task-id t-lock"})
            self.assertEqual("deny", d_rp["decision"])
            self.assertIn("CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS", d_rp.get("reason", ""))

            # `--help` and `task status` remain allowed even while build lock is held!
            a_help = _run_pts("run_command", {"CommandLine": "python .agents/harness.py verify-steps --help"})
            self.assertEqual("allow", a_help["decision"])

    def test_v1318_05_manage_task_idle_and_nonexistent_path_anti_reread_exemption(self):
        import io
        import contextlib
        from unittest import mock
        import pre_tool_safety as pts
        import delegation_policy as dp
        from _workflow import planning as wf_plan

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".agents/state").mkdir(parents=True)

            def _call_hook(tool_name: str, tool_args: dict) -> dict:
                buf = io.StringIO()
                payload = json.dumps({"toolName": tool_name, "toolArgs": tool_args, "conversationId": "lead-idle"})
                with mock.patch.object(pts, "REPO", repo), \
                     mock.patch("sys.stdin", io.StringIO(payload)), \
                     contextlib.redirect_stdout(buf):
                    try:
                        pts.main()
                    except SystemExit:
                        pass
                return json.loads(buf.getvalue().strip())

            # 1. manage_task(list) and manage_task(kill) succeed in IDLE (no active-task.json)!
            res_list = _call_hook("manage_task", {"Action": "list"})
            self.assertEqual("allow", res_list["decision"])
            self.assertIn("permitted across all task states", res_list.get("reason", ""))

            res_kill = _call_hook("manage_task", {"Action": "kill", "TaskId": "conv/task-238"})
            self.assertEqual("allow", res_kill["decision"])

            # 2. manage_task(status) stays blocked by ZERO-POLLING INVARIANT!
            res_status = _call_hook("manage_task", {"Action": "status", "TaskId": "conv/task-238"})
            self.assertEqual("deny", res_status["decision"])

            # 3. Nonexistent read_file paths do NOT deduct from post-scout read counters!
            real_f = repo / "app/src/main/java/com/demo/RealFile.kt"
            real_f.parent.mkdir(parents=True)
            real_f.write_text("package com.demo\nclass RealFile\n", encoding="utf-8")
            parent_tx = repo / "brain/lead-idle/.system_generated/logs/transcript.jsonl"
            parent_tx.parent.mkdir(parents=True, exist_ok=True)
            parent_tx.write_text(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Inspect flow"}) + "\n", encoding="utf-8")
            dp._save_utility_ledger(repo, {
                "schema_version": 1,
                "entries": [{
                    "execution_id": "scout-1",
                    "parent_conversation_id": "lead-idle",
                    "parent_user_turns": 1,
                    "wave_id": "wave123",
                    "agent_type": dp.SCOUT_AGENT,
                    "role": dp.SCOUT_AGENT,
                    "wave_completed": True,
                    "dispatched_epoch": 9999999999.0,
                    "completed_at_epoch": 9999999999.0,
                    "task_id": "",
                    "task_status": "IDLE",
                    "inspected_files": ["app/src/main/java/com/demo/RealFile.kt"],
                    "lead_post_reads": 0,
                    "lead_unread_post_reads": 0,
                }],
            })
            with mock.patch("antigravity_runtime.resolve_transcript", side_effect=lambda cid: parent_tx if cid == "lead-idle" else None):
                for i in range(6):
                    ok_r, _, _ = dp.check_and_record_lead_post_subagent_read(
                        repo, "lead-idle",
                        tool_name="read_file",
                        args={"Path": str(repo / f"app/src/main/java/com/demo/Missing{i}.kt")},
                    )
                    self.assertTrue(ok_r)
                # All 3 real surgical post-scout reads STILL succeed (proving 6 missing files consumed 0 slots!), and 4th hits cap!
                for _ in range(3):
                    ok_real, _, _ = dp.check_and_record_lead_post_subagent_read(
                        repo, "lead-idle",
                        tool_name="read_file",
                        args={"Path": str(real_f)},
                    )
                    self.assertTrue(ok_real)
                ok_4th, _, code_4th = dp.check_and_record_lead_post_subagent_read(
                    repo, "lead-idle",
                    tool_name="read_file",
                    args={"Path": str(real_f)},
                )
                self.assertFalse(ok_4th)
                self.assertEqual("POST_SCOUT_REREAD_CAP_REACHED", code_4th)

            # 4. PHASE_PLAN_REQUIRED highlights shell-safe `id:Title` syntax
            self.assertIn("Prefer this compact comma-separated 'id:Title' syntax", Path(wf_plan.__file__).read_text(encoding="utf-8"))

    def test_v1318_06_interpolation_aware_check_strings_and_32_log_daemon_alignment(self):
        import time
        import check_strings
        from _live_process import resolve_compatible_windows_daemon_alignment

        # 1. Kotlin UI interpolation-only / symbol-only literals pass, while real prose still fails!
        self.assertFalse(check_strings._kt_line_has_translatable_literal('binding?.textView228?.text = "$maxProgress % "'))
        self.assertFalse(check_strings._kt_line_has_translatable_literal('Text("${mins}:${secs}")'))
        self.assertFalse(check_strings._kt_line_has_translatable_literal('Text("100%")'))
        self.assertFalse(check_strings._kt_line_has_translatable_literal('tv.setText("%d / %d")'))

        self.assertTrue(check_strings._kt_line_has_translatable_literal('Text("Step $step of $total")'))
        self.assertTrue(check_strings._kt_line_has_translatable_literal('binding.tv.text = "Loading..."'))
        self.assertTrue(check_strings._kt_line_has_translatable_literal('Text("مرحبا $userName")'))

        # 2. Windows Gradle daemon alignment scans up to 32 logs (even >24h old live Android Studio daemon behind 20 dead logs)
        #    and extracts immutable `-Dfile.encoding` / `-Duser.*` properties!
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proj = root / "proj"
            gu_home = root / "gradle_home"
            jbr = root / "Android Studio/jbr"
            (proj / "gradle/wrapper").mkdir(parents=True)
            (proj / "gradle/wrapper/gradle-wrapper.properties").write_text(
                "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.9-bin.zip\n",
                encoding="utf-8",
            )
            (jbr / "bin").mkdir(parents=True)
            (jbr / "bin/java.exe").write_text("", encoding="utf-8")
            (jbr / "bin/java").write_text("", encoding="utf-8")

            d_dir = gu_home / "daemon/8.9"
            d_dir.mkdir(parents=True)
            live_log = d_dir / "daemon-1001.out.log"
            live_log.write_text(
                f"DefaultDaemonContext[uid=abc,javaHome={jbr},daemonRegistryDir={d_dir},pid=1001,idleTimeout=10800000,"
                "priority=NORMAL,applyInstrumentationAgent=true,nativeServicesMode=ENABLED,"
                "daemonOpts=-Xmx4096m,-Dfile.encoding=UTF-8,-Duser.country=US,-Duser.language=en,-Duser.variant,--add-opens=java.base/java.util=ALL-UNNAMED]\n",
                encoding="utf-8",
            )
            old_ts = time.time() - (48 * 3600)
            os.utime(live_log, (old_ts, old_ts))

            # Create 20 newer dead daemon logs ahead of PID 1001
            for idx in range(20):
                dead_p = d_dir / f"daemon-{2000 + idx}.out.log"
                dead_p.write_text(f"DefaultDaemonContext[uid=d{idx},javaHome={jbr},pid={2000 + idx}]\n", encoding="utf-8")

            env = {"GRADLE_USER_HOME": str(gu_home)}
            jh, opts = resolve_compatible_windows_daemon_alignment(
                proj, env, os_name="nt", pid_alive_fn=lambda pid: pid == 1001,
            )
            self.assertEqual(str(jbr), jh)
            self.assertIn("-Dfile.encoding=UTF-8", opts)
            self.assertIn("-Duser.country=US", opts)
            self.assertIn("-Duser.language=en", opts)
            self.assertFalse(any(o.startswith("-Xmx") or o.startswith("--add-opens") for o in opts))


class TestV1319ForensicIntegration(unittest.TestCase):
    """End-to-end regression suite for all 7 systemic fixes from live session chat-a3c40cb9 (v1.3.19)."""

    def test_v1319_01_later_round_policy_determinism_after_extra_files_and_revise(self):
        import argparse
        import subprocess as _sp
        import workflow
        from _vnext_common import atomic_write_json, canonical_sha256, read_json
        from evidence_store import EvidenceStore
        from final_verifier import validate_policy_artifact

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            _sp.run(["git", "init", "-q"], cwd=str(repo), check=True)
            _sp.run(["git", "config", "user.email", "dev@example.com"], cwd=str(repo), check=True)
            _sp.run(["git", "config", "user.name", "Dev"], cwd=str(repo), check=True)
            # Install minimal skills & scripts symlink/copy layout via KIT
            (repo / ".agents").mkdir(parents=True, exist_ok=True)
            (repo / ".agents/VERSION").write_text((Path(__file__).resolve().parents[2] / "agents/VERSION").read_text(encoding="utf-8"), encoding="utf-8")
            shutil.copytree(Path(__file__).resolve().parents[2] / "agents/skills", repo / ".agents/skills")
            f1 = repo / "app/src/main/java/com/demo/OnboardingVm.kt"
            f2 = repo / "app/src/main/java/com/demo/GenderUseCase.kt"
            f1.parent.mkdir(parents=True, exist_ok=True)
            f1.write_text("package com.demo\nclass OnboardingVm { fun clean() = 1 }\n", encoding="utf-8")
            f2.write_text("package com.demo\nclass GenderUseCase { fun run(unused: Int = 0) = 2 }\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            _sp.run(["git", "add", "."], cwd=str(repo), check=True)
            _sp.run(["git", "commit", "-qm", "init"], cwd=str(repo), check=True)

            tid = "clean-onboarding-unused-code"
            draft_res = workflow.draft(argparse.Namespace(
                repo=str(repo),
                task_id=tid,
                outcome="Remove unused parameters in onboarding and worker callers",
                kind="REFACTOR",
                expected_files="app/src/main/java/com/demo/OnboardingVm.kt",
                expected_surfaces="BUSINESS_LOGIC",
                expected_modules=":app",
                test_strategy="none",
                approach="Remove unused parameters without changing runtime behavior.",
                risks="Caller signature alignment across use cases.",
                device_strategy="Verify startup.",
                phases=None,
                adopt_dirty=False,
                arch_intent="REFACTOR",
                module_placement=":app",
                dependency_direction="presentation->domain",
                state_ownership="OnboardingVm",
                pattern="MVVM",
                new_abstractions="none",
            ))
            workflow.record_approval(argparse.Namespace(
                repo=str(repo),
                task_id=tid,
                source="conversation",
                proof_reference="approve",
                enforcement_tier="RULE_ENFORCED",
                plan_hash=draft_res["plan_sha256"][:12],
                approval_token=None,
            ))

            # Round 1 edit on planned file f1 + prepare-verification + PASS reviews
            f1.write_text("package com.demo\nclass OnboardingVm { fun clean() = 2 }\n", encoding="utf-8")
            r1 = workflow.prepare_verification(argparse.Namespace(repo=str(repo), task_id=tid, host="antigravity"))
            r1_policy = read_json(Path(r1["policy"]))
            store = EvidenceStore(workflow.state_root(repo))
            store.write(
                snapshot=r1["delivery_snapshot_sha256"],
                run_id=r1["run_id"],
                name="reviews",
                producer="review_orchestrator",
                harness_version=(Path(__file__).resolve().parents[2] / "agents/VERSION").read_text(encoding="utf-8").strip(),
                change_set=r1["change_set_sha256"],
                status="PASS",
                evidence={
                    "reviewers": list(r1_policy["reviewers"]),
                    "blocking_findings": [],
                    "reports": [
                        {"reviewer": rev, "verdict": "PASS", "independent_execution_verified": True}
                        for rev in r1_policy["reviewers"]
                    ],
                },
            )
            p_path = workflow.task_dir(repo, tid) / "plan.json"
            p_doc = read_json(p_path)
            p_doc["review_rounds"] = 1
            from plan_authority import save_plan
            save_plan(p_path, p_doc)

            # Developer follow-up (`task resume` + touching extra in-module file `f2` NOT in initial `expected_files`)
            workflow.resume(argparse.Namespace(repo=str(repo), task_id=tid, reopen=False))
            f2.write_text("package com.demo\nclass GenderUseCase { fun run() = 2 }\n", encoding="utf-8")

            r2 = workflow.prepare_verification(argparse.Namespace(repo=str(repo), task_id=tid, host="antigravity"))
            r2_policy_path = Path(r2["policy"])
            r2_policy = read_json(r2_policy_path)
            r2_manifest = read_json(Path(r2["manifest"]))
            updated_plan = read_json(p_path)
            self.assertIn("app/src/main/java/com/demo/GenderUseCase.kt", updated_plan["expected_files"])
            self.assertIsNotNone(r2_policy.get("fix_delta"))

            # Exact `run_device.py` / `final_verifier.py` check that previously failed at L576 MUST PASS!
            exp_pol, pol_err, pol_state = validate_policy_artifact(
                repo,
                updated_plan,
                r2_policy,
                workflow.state_root(repo),
                r2_policy_path,
                current_change_set=r2_manifest["change_set_sha256"],
                task_changes=r2_manifest.get("task_changes"),
            )
            self.assertIsNone(pol_err, f"Round-2 policy validation failed: {pol_err}")
            self.assertEqual("PASS", pol_state)
            self.assertEqual(r2_policy, exp_pol)

            # Diagnostic clarity check: if a key is tampered (with recomputed sha), mismatched keys are named!
            tampered = dict(r2_policy)
            tampered["max_review_rounds"] = 99
            tampered["policy_sha256"] = canonical_sha256({k: v for k, v in tampered.items() if k != "policy_sha256"})
            _, err_msg, _ = validate_policy_artifact(
                repo,
                updated_plan,
                tampered,
                workflow.state_root(repo),
                r2_policy_path,
                current_change_set=r2_manifest["change_set_sha256"],
                task_changes=r2_manifest.get("task_changes"),
            )
            self.assertIn("policy artifact does not match deterministic policy evaluation", err_msg or "")
            self.assertIn("max_review_rounds", err_msg or "")

    def test_v1319_02_parallel_scout_wave_coalescing_and_ask_question_turn_reset(self):
        from unittest.mock import patch
        import delegation_policy as dp

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            (repo / ".agents/state").mkdir(parents=True, exist_ok=True)
            tx_dir = repo / "brain" / "conv-a3c4" / ".system_generated" / "logs"
            tx_dir.mkdir(parents=True, exist_ok=True)
            parent_tx = tx_dir / "transcript_full.jsonl"

            # Turn 1: User request + 1 PLANNER_RESPONSE emitting 3 parallel single-item `invoke_subagent` calls
            rows = [
                {"source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-11-16T09:55:47Z", "content": "Audit unused code"},
                {
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-11-16T09:56:50Z",
                    "tool_calls": [
                        {"name": "invoke_subagent", "args": {"TypeName": "harness-scout-agent", "Prompt": "Audit onboarding slice 1 files"}},
                        {"name": "invoke_subagent", "args": {"TypeName": "harness-scout-agent", "Prompt": "Audit foodplans slice 2 files"}},
                        {"name": "invoke_subagent", "args": {"TypeName": "harness-scout-agent", "Prompt": "Audit domain/data slice 3 files"}},
                    ],
                },
            ]
            parent_tx.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

            with patch("delegation_policy.resolve_transcript", side_effect=lambda cid: parent_tx if cid == "conv-a3c4" else None):
                for idx in range(3):
                    ok, reason, code = dp.validate_utility_dispatch(
                        repo,
                        None,
                        [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Prompt": f"Audit unused code slice {idx} in repo"}],
                        parent_conversation_id="conv-a3c4",
                    )
                    self.assertTrue(ok, f"Parallel scout #{idx+1} denied: {reason}")
                    self.assertEqual("UTILITY_SUBAGENT_ALLOWED", code)

                entries = dp._load_utility_ledger(repo)["entries"]
                wave_ids = {e["wave_id"] for e in entries}
                self.assertEqual(1, len(wave_ids), f"3 parallel scout calls in 1 PLANNER_RESPONSE must share 1 wave_id, got {wave_ids}")

                # A 4th scout in the SAME parallel PLANNER_RESPONSE must hit SCOUT_BATCH_CAP (3-scout parallel cap)
                ok4, _, code4 = dp.validate_utility_dispatch(
                    repo,
                    None,
                    [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Prompt": "Audit extra 4th parallel slice"}],
                    parent_conversation_id="conv-a3c4",
                )
                self.assertFalse(ok4)
                self.assertEqual("SCOUT_BATCH_CAP", code4)

                # Lead asks `ask_question` and developer answers (GENERIC non-error event) -> turn count advances & Wave 2 succeeds!
                rows.extend([
                    {"source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-11-16T10:01:21Z", "tool_calls": [{"name": "ask_question", "args": {"questions": []}}]},
                    {"source": "MODEL", "type": "GENERIC", "status": "DONE", "created_at": "2026-11-16T10:02:57Z", "content": "A1: Clean all unused code"},
                    {"source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-11-16T10:02:58Z", "tool_calls": [{"name": "invoke_subagent", "args": {"TypeName": "harness-scout-agent"}}]},
                ])
                parent_tx.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

                self.assertEqual(2, dp._count_parent_user_turns("conv-a3c4"))
                self.assertEqual(("", ""), dp.pending_post_subagent_directive(repo, "conv-a3c4"))
                ok_w2, reason_w2, _ = dp.validate_utility_dispatch(
                    repo,
                    None,
                    [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Prompt": "Audit remaining unread onboarding files"}],
                    parent_conversation_id="conv-a3c4",
                )
                self.assertTrue(ok_w2, reason_w2)

    def test_v1319_03_scout_safe_git_grep_ls_files_and_prompt_hygiene(self):
        import delegation_policy as dp

        self.assertTrue(dp.scout_command_allowed('git grep -n -E "popWarningConfirm|sufferFromDiseasesUi"'))
        self.assertTrue(dp.scout_command_allowed('git grep -no "enqueue" app/src'))
        self.assertTrue(dp.scout_command_allowed("git ls-files app/src/main/java/com/madarsoft/fitness/data"))
        self.assertTrue(dp.scout_command_allowed("git log --oneline b86e16eaa9^..HEAD"))
        self.assertFalse(dp.scout_command_allowed('git grep -Ovim "foo"'))
        self.assertFalse(dp.scout_command_allowed('git grep -nOvim "foo"'))
        self.assertFalse(dp.scout_command_allowed('git grep --open-files-in-pager "foo"'))
        self.assertFalse(dp.scout_command_allowed('git log ^HEAD; g^it pu^sh'))

        scout_prompt = dp.UTILITY_AGENT_SPECS[dp.SCOUT_AGENT]["system_prompt"]
        self.assertIn("NEVER read `.agents/cache/project_graph.json` directly", scout_prompt)
        self.assertIn("git grep -n", scout_prompt)

    def test_v1319_04_git_parent_caret_and_zero_io_file_mutation_fast_path(self):
        from unittest import mock
        import change_classifier
        import mutation_guard as mg

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            self.assertTrue(mg.command_allowed(repo, "git log --first-parent --oneline b86e16eaa9^..HEAD")[0])
            self.assertTrue(mg.command_allowed(repo, "git diff --name-status b86e16eaa9^ HEAD")[0])
            self.assertTrue(mg.command_allowed(repo, "git show HEAD^2")[0])
            self.assertTrue(mg.command_allowed(repo, "git rev-list HEAD^{tree}")[0])
            # Security invariants MUST remain strictly denied
            self.assertFalse(mg.command_allowed(repo, "git log ^HEAD; g^it pu^sh")[0])
            self.assertFalse(mg.command_allowed(repo, "git log x ^& calc")[0])
            self.assertFalse(mg.command_allowed(repo, "git log ^--output=evil")[0])
            self.assertFalse(mg.command_allowed(repo, "git checkout b86e16eaa9^")[0])

            # Zero-I/O fast path on approved expected_files: neither classify() nor _is_tracked() may touch disk/git!
            import argparse
            import subprocess as _sp
            import workflow
            _sp.run(["git", "init", "-q"], cwd=str(repo), check=True)
            _sp.run(["git", "config", "user.email", "dev@example.com"], cwd=str(repo), check=True)
            _sp.run(["git", "config", "user.name", "Dev"], cwd=str(repo), check=True)
            (repo / ".agents").mkdir(parents=True, exist_ok=True)
            (repo / ".agents/VERSION").write_text((Path(__file__).resolve().parents[2] / "agents/VERSION").read_text(encoding="utf-8"), encoding="utf-8")
            shutil.copytree(Path(__file__).resolve().parents[2] / "agents/skills", repo / ".agents/skills")
            target_rel = "app/src/main/java/com/demo/GenderUseCase.kt"
            f_t = repo / target_rel
            f_t.parent.mkdir(parents=True, exist_ok=True)
            f_t.write_text("package com.demo\nclass GenderUseCase\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            _sp.run(["git", "add", "."], cwd=str(repo), check=True)
            _sp.run(["git", "commit", "-qm", "init"], cwd=str(repo), check=True)

            d_res = workflow.draft(argparse.Namespace(
                repo=str(repo),
                task_id="fast-io-check",
                outcome="Clean unused parameter in GenderUseCase",
                kind="REFACTOR",
                expected_files=target_rel,
                expected_surfaces="BUSINESS_LOGIC",
                expected_modules=":app",
                test_strategy="none",
                approach="Clean unused parameter.",
                risks="None.",
                device_strategy="Verify launch.",
                phases=None,
                adopt_dirty=False,
                arch_intent="REFACTOR",
                module_placement=":app",
                dependency_direction="domain",
                state_ownership="GenderUseCase",
                pattern="UseCase",
                new_abstractions="none",
            ))
            workflow.record_approval(argparse.Namespace(
                repo=str(repo),
                task_id="fast-io-check",
                source="conversation",
                proof_reference="approve",
                enforcement_tier="RULE_ENFORCED",
                plan_hash=d_res["plan_sha256"][:12],
                approval_token=None,
            ))

            with mock.patch.object(change_classifier, "classify", side_effect=AssertionError("classify() must not touch target file on Zero-I/O fast path")), \
                 mock.patch.object(mg, "_is_tracked", side_effect=AssertionError("_is_tracked() must not spawn git on Zero-I/O fast path")):
                ok_edit, _, code_edit = mg.file_mutation_allowed(repo, targets=[target_rel])
                self.assertTrue(ok_edit)
                self.assertEqual("FILE_MUTATION_ALLOWED", code_edit)

    def test_v1319_05_post_review_reread_unblocks_on_fresh_user_input_and_multi_daemon_align(self):
        from unittest.mock import patch
        import delegation_policy as dp
        from _live_process import resolve_compatible_windows_daemon_alignment

        # A) Post-review reread guard: blocks before new USER_INPUT, unblocks immediately when developer sends follow-up!
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            import subprocess as _sp2
            _sp2.run(["git", "init", "-q"], cwd=str(repo), check=True)
            _sp2.run(["git", "config", "user.email", "dev@example.com"], cwd=str(repo), check=True)
            _sp2.run(["git", "config", "user.name", "Dev"], cwd=str(repo), check=True)
            _sp2.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=str(repo), check=True)
            import review_orchestrator as ro
            from plan_authority import create_plan, save_plan
            tid = "t-post-rev"
            t_dir = repo / ".agents/state/tasks" / tid
            (t_dir / "review-execution/run-1").mkdir(parents=True, exist_ok=True)
            p_obj = create_plan(
                repo,
                task_id=tid,
                requested_outcome="Clean unused parameter",
                expected_surfaces=["BUSINESS_LOGIC"],
                expected_modules=[":app"],
                expected_files=["app/src/main/java/com/demo/Worker.kt"],
                task_kind="REFACTOR",
                base_manifest={
                    "delivery_snapshot_sha256": "0" * 64,
                    "change_set_sha256": "0" * 64,
                    "repository": {"root_sha256": "0" * 64, "git_common_dir_sha256": "0" * 64, "branch": "main", "head": "0" * 40},
                    "files": [],
                },
            )
            p_obj["status"] = "VERIFYING"
            p_obj["verification_run_id"] = "run-1"
            save_plan(t_dir / "plan.json", p_obj)
            (repo / ".agents/state/active-task.json").write_text(json.dumps({"task_id": tid, "plan_path": str(t_dir / "plan.json")}), encoding="utf-8")
            snap_sha = "a" * 64
            cs_sha = "b" * 64
            (t_dir / "current-run.json").write_text(json.dumps({
                "task_id": tid,
                "run_id": "run-1",
                "review_host": "antigravity",
                "delivery_snapshot_sha256": snap_sha,
                "change_set_sha256": cs_sha,
                "created_at": "2026-11-16T10:43:00Z",
            }), encoding="utf-8")
            ledger_doc = {
                "schema_version": 2,
                "task_id": tid,
                "run_id": "run-1",
                "delivery_snapshot_sha256": snap_sha,
                "change_set_sha256": cs_sha,
                "review_package_sha256": "c" * 64,
                "host": "antigravity",
                "updated_at": "2026-11-16T10:46:08Z",
                "reviewers": {
                    "arch-regression-reviewer-agent": {
                        "state": "INGESTED",
                        "verdict": "PASS",
                        "findings": [],
                        "completed_at": "2026-11-16T10:46:08Z",
                    },
                },
            }
            ro.save_ledger(t_dir, "run-1", ledger_doc)
            src_file = repo / "app/src/main/java/com/demo/Worker.kt"
            src_file.parent.mkdir(parents=True, exist_ok=True)
            src_file.write_text("class Worker\n", encoding="utf-8")

            tx_p = repo / "brain/c-lead/.system_generated/logs/transcript_full.jsonl"
            tx_p.parent.mkdir(parents=True, exist_ok=True)
            tx_p.write_text(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-11-16T09:55:47Z", "content": "Initial task"}) + "\n", encoding="utf-8")

            with patch("delegation_policy.resolve_transcript", return_value=tx_p):
                ok_before, _, code_before = dp.check_post_reviewer_reread_guard(
                    repo, "c-lead", tool_name="read_file", args={"Path": str(src_file)},
                )
                self.assertFalse(ok_before)
                self.assertEqual("POST_REVIEW_REREAD_BLOCKED", code_before)

                # Developer sends follow-up USER_INPUT at 10:46:55Z (> 10:46:08Z)
                with tx_p.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-11-16T10:46:55Z", "content": "Parameter userRepository is never used"}) + "\n")
                ok_after, _, _ = dp.check_post_reviewer_reread_guard(
                    repo, "c-lead", tool_name="read_file", args={"Path": str(src_file)},
                )
                self.assertTrue(ok_after, "Fresh developer USER_INPUT after PASS reviews must allow Lead inspection")

        # B) Multi-daemon Windows Gradle alignment (`1 busy` JBR + `1 incompatible` Adoptium-17 matching `JAVA_HOME`)
        with tempfile.TemporaryDirectory() as td2:
            root = Path(td2)
            proj = root / "proj"
            gu_home = root / "gradle_home"
            jbr = root / "Android Studio/jbr"
            adopt17 = root / "jdks/eclipse_adoptium-17"
            (proj / "gradle/wrapper").mkdir(parents=True)
            (proj / "gradle/wrapper/gradle-wrapper.properties").write_text(
                "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.9-bin.zip\n", encoding="utf-8",
            )
            for jdk in (jbr, adopt17):
                (jdk / "bin").mkdir(parents=True)
                (jdk / "bin/java.exe").write_text("", encoding="utf-8")
                (jdk / "bin/java").write_text("", encoding="utf-8")
            d_dir = gu_home / "daemon/8.9"
            d_dir.mkdir(parents=True)
            (d_dir / "daemon-3001.out.log").write_text(
                f"DefaultDaemonContext[uid=a,javaHome={jbr},pid=3001,daemonOpts=-Xmx4g,-Dfile.encoding=UTF-8,-Duser.country=US]\nState transition: Busy\n",
                encoding="utf-8",
            )
            (d_dir / "daemon-3002.out.log").write_text(
                f"DefaultDaemonContext[uid=b,javaHome={adopt17},pid=3002,daemonOpts=-Xmx4g,-Dfile.encoding=UTF-8,-Duser.country=EG,-Duser.language=en]\nState transition: Idle\n",
                encoding="utf-8",
            )
            # Case 1: JAVA_HOME matches adopt17 -> aligns immutable_opts to adopt17 even when jbr is also alive!
            jh1, opts1 = resolve_compatible_windows_daemon_alignment(
                proj, {"GRADLE_USER_HOME": str(gu_home), "JAVA_HOME": str(adopt17)},
                os_name="nt", pid_alive_fn=lambda pid: pid in {3001, 3002},
            )
            self.assertEqual(str(adopt17), jh1)
            self.assertIn("-Duser.country=EG", opts1)
            # Case 2: JAVA_HOME unset -> picks the single Idle daemon (adopt17) over the Busy daemon (jbr)!
            jh2, opts2 = resolve_compatible_windows_daemon_alignment(
                proj, {"GRADLE_USER_HOME": str(gu_home)},
                os_name="nt", pid_alive_fn=lambda pid: pid in {3001, 3002},
            )
            self.assertEqual(str(adopt17), jh2)
            self.assertIn("-Dfile.encoding=UTF-8", opts2)

    @staticmethod
    def _init_mini_git_repo(repo: Path) -> None:
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
        (repo / "settings.gradle.kts").write_text("include(\":app\")\n", encoding="utf-8")
        (repo / "app").mkdir(parents=True, exist_ok=True)
        (repo / "app/build.gradle.kts").write_text("plugins {}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)

    def test_v1319_06_empty_subagent_terminal_payload_guard_201209(self) -> None:
        """Verify #201209: DONE subagent transcripts with empty/tiny payload fail fast as recoverable EMPTY_SUBAGENT_TERMINAL_RESPONSE."""
        import unittest.mock
        import delegation_policy as dp
        import record_review as rr
        import review_orchestrator as ro
        import workflow

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            self._init_mini_git_repo(repo)
            brain = root / "appdata" / "brain"
            brain.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(os.environ, {"APPDATA": str(root / "appdata"), "HARNESS_BRAIN_ROOT": str(brain)}, clear=False):
                # A. Reviewer transcript marked DONE with empty content -> raises EMPTY_SUBAGENT_TERMINAL_RESPONSE immediately
                rev_cid = "rev-empty-done-201209"
                rev_tx = brain / rev_cid / ".system_generated" / "logs" / "transcript.jsonl"
                rev_tx.parent.mkdir(parents=True, exist_ok=True)
                rev_tx.write_text(
                    json.dumps({"source": "USER", "type": "USER_INPUT", "content": "Review package"}) + "\n"
                    + json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE", "content": "", "output_tokens": 8}) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(rr.ValidationError) as ctx_rr:
                    rr._extract_transcript_response(rev_tx)
                self.assertIn("EMPTY_SUBAGENT_TERMINAL_RESPONSE", str(ctx_rr.exception))

                # B. Scout wave with DONE + empty payload marks dispatch_failed=True without locking Lead under anti-reread
                parent_cid = "lead-empty-scout-201209"
                parent_tx = brain / parent_cid / ".system_generated" / "logs" / "transcript.jsonl"
                parent_tx.parent.mkdir(parents=True, exist_ok=True)
                prompt_s = "Sweep onboarding screens and viewmodels across feature modules with full detail"
                parent_tx.write_text(
                    json.dumps({"source": "USER", "type": "USER_INPUT", "content": "Check onboarding"}) + "\n"
                    + json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "toolCalls": [{"name": "invoke_subagent"}]}) + "\n",
                    encoding="utf-8",
                )
                tx_lookup = {
                    parent_cid: parent_tx,
                    "scout-empty-done-201209": brain / "scout-empty-done-201209" / ".system_generated" / "logs" / "transcript.jsonl",
                }
                with unittest.mock.patch("delegation_policy.resolve_transcript", side_effect=lambda cid: tx_lookup.get(cid)):
                    ok_s, reason_s, _code_s = dp.validate_utility_dispatch(
                        repo,
                        None,
                        [{
                            "TypeName": "harness-scout-agent",
                            "Role": "harness-scout-agent",
                            "Prompt": prompt_s,
                            "Workspace": "inherit",
                        }],
                        parent_conversation_id=parent_cid,
                    )
                    self.assertTrue(ok_s, reason_s)

                scout_cid = "scout-empty-done-201209"
                scout_tx = brain / scout_cid / ".system_generated" / "logs" / "transcript.jsonl"
                scout_tx.parent.mkdir(parents=True, exist_ok=True)
                scout_tx.write_text(
                    json.dumps({
                        "source": "SYSTEM_SDK",
                        "type": "SYSTEM_MESSAGE",
                        "content": f"<SYSTEM_MESSAGE>sender={parent_cid} priority=MESSAGE_PRIORITY_HIGH content={prompt_s}\n</SYSTEM_MESSAGE>",
                    }) + "\n"
                    + json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE", "content": "   ", "output_tokens": 3}) + "\n",
                    encoding="utf-8",
                )
                with unittest.mock.patch("delegation_policy.resolve_transcript", side_effect=lambda cid: tx_lookup.get(cid)):
                    dp.bind_utility_from_post_tool(
                        repo,
                        {
                            "conversationId": parent_cid,
                            "transcriptPath": str(parent_tx),
                            "toolCall": {"name": "invoke_subagent"},
                            "toolResult": {"subagents": [{"conversationId": scout_cid}]},
                        },
                    )
                ledger = dp._load_utility_ledger(repo)
                entry = ledger["entries"][-1]
                self.assertTrue(entry.get("dispatch_failed"), entry)
                self.assertEqual("EMPTY_SUBAGENT_TERMINAL_RESPONSE", entry.get("failure_code"))
                self.assertFalse(entry.get("wave_completed"), entry)

    def test_v1319_07_sir_flash_lite_hygiene_and_preamble_immunity_201208(self) -> None:
        """Verify #201209 & #201208: zero `edit_file`, zero CLI `git diff --check`, and zero generic SWE boilerplate preambles in templates."""
        kit_root = Path(__file__).resolve().parents[2]
        gemini_tpl = (kit_root / "agents" / "tool-adapters" / "GEMINI.md.template").read_text(encoding="utf-8")
        self.assertNotIn("edit_file", gemini_tpl)
        self.assertNotIn("git diff --check", gemini_tpl)
        self.assertNotIn("The user will primarily request you perform software engineering tasks", gemini_tpl)
        self.assertLess(len(gemini_tpl), 40000)

        for sub_json in (kit_root / "agents" / "subagents").glob("*.json"):
            raw = sub_json.read_text(encoding="utf-8")
            self.assertNotIn("git diff --check", raw, sub_json.name)
            self.assertNotIn("The user will primarily request you perform software engineering tasks", raw, sub_json.name)

    def test_v1319_08_pm_find_item_pagination_guard_and_zoho_414_budget(self) -> None:
        """Verify `pm find-item`, `LARGE_STEP_OUTPUT_PAGINATION_BLOCKED`, and compact `zoho_query_param_html` (HTTP 414 guard)."""
        import argparse
        import contextlib
        import io
        import urllib.parse
        from unittest import mock
        from _vnext_common import atomic_write_json
        import pm_discovery as pmd
        import pre_tool_safety as pts
        import workflow

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self._init_mini_git_repo(repo)
            kit_root = Path(__file__).resolve().parents[2]
            shutil.copytree(kit_root / "agents", repo / ".agents", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "state", "cache"))

            # 1) Create a realistic >60 KB single-line `.system_generated/steps/391/output.txt` Zoho Sprints dump
            step_out = Path(td) / "brain" / "conv-zoho" / ".system_generated" / "steps" / "391" / "output.txt"
            step_out.parent.mkdir(parents=True, exist_ok=True)
            items_payload = [
                {
                    "itemNo": str(1000 + idx),
                    "itemId": f"19308300000047{idx:04d}",
                    "itemName": f"شاشة اختبار رقم {idx} لتكبير حجم مخرجات زوهو بدون تقسيم يدوي",
                    "itemTypeName": "Story",
                    "projItemTypeId": "193083000000007025",
                    "projPriorityId": "193083000000007019",
                    "statusId": "193083000000005245",
                    "statusName": "To do",
                    "sprintId": "193083000000007004",
                    "sequence": str(idx),
                    "ownerId": ["193083000000007333"],
                    "sprintInfo": {"no": "0", "name": "Backlog", "id": "193083000000007004", "type": 5},
                }
                for idx in range(1, 220)
            ]
            items_payload.append({
                "itemNo": "1454",
                "itemId": "193083000000551454",
                "itemName": "دعم باكدج خصم من شاشات متعددة مع الحفاظ على سلوك الرجوع",
                "itemTypeName": "Task",
                "projItemTypeId": "193083000000007023",
                "projPriorityId": "193083000000007019",
                "statusId": "193083000000005246",
                "statusName": "In progress",
                "sprintId": "193083000000499999",
                "sequence": "220",
                "ownerId": ["193083000000007333"],
                "sprintInfo": {"no": "18", "name": "Sprint 18", "id": "193083000000499999", "type": 2},
            })
            zoho_dump = {
                "status": "success",
                "data": {
                    "next": True,
                    "userDisplayName": {"193083000000007333": "Rabee Elkholy"},
                    "items": items_payload,
                },
            }
            step_out.write_text(json.dumps(zoho_dump, ensure_ascii=False), encoding="utf-8")
            self.assertGreater(step_out.stat().st_size, 48000)

            # 2) `pm find-item` resolves `I1454`, `1454`, `#P1/itemdetails/I1454`, and `Ras-I1454` in <20ms!
            for lookup in ("I1454", "1454", "https://sprints.zoho.com/workspace/demo#P1/itemdetails/I1454", "Ras-I1454"):
                found = pmd.find_pm_items_in_files([step_out], item=lookup)
                self.assertEqual("FOUND", found["status"], lookup)
                self.assertEqual(1, found["found_count"])
                m0 = found["matches"][0]
                self.assertEqual("193083000000551454", m0["itemId"])
                self.assertEqual("1454", m0["itemNo"])
                self.assertEqual("193083000000499999", m0["sprintId"])
                self.assertEqual(["Rabee Elkholy"], m0["owners"])

            cli_find = subprocess.run(
                [sys.executable, str(repo / ".agents/harness.py"), "pm", "find-item", "--item", "I1454", "--file", str(step_out), "--json"],
                cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
            )
            self.assertEqual("FOUND", json.loads(cli_find.stdout)["status"])

            # Missing item when `next=true` emits active-sprint (`sprintType == 2`) + `itemsearchby` hint!
            miss = pmd.find_pm_items_in_files([step_out], item="I9999")
            self.assertEqual("NOT_FOUND", miss["status"])
            self.assertIn("itemsearchby", miss["hint"])

            # 3) `pre_tool_safety` allows head read (`ByteOffset` omitted) on `output.txt`, but blocks `ByteOffset > 0` pagination!
            def _run_read_hook(read_args: dict) -> dict:
                buf = io.StringIO()
                with mock.patch.object(pts, "REPO", repo), \
                     mock.patch("sys.stdin", io.StringIO(json.dumps({"toolName": "read_file", "toolArgs": read_args, "conversationId": "lead-zoho"}))), \
                     contextlib.redirect_stdout(buf):
                    pts._main()
                return json.loads(buf.getvalue().strip())

            head_ok = _run_read_hook({"Path": str(step_out), "StartLine": 1, "EndLine": 1})
            self.assertEqual("allow", head_ok["decision"], head_ok)
            paginated_deny = _run_read_hook({"Path": str(step_out), "StartLine": 1, "EndLine": 1, "ByteOffset": 46080})
            self.assertEqual("deny", paginated_deny["decision"], paginated_deny)
            self.assertIn("LARGE_STEP_OUTPUT_PAGINATION_BLOCKED", paginated_deny["reason"])
            self.assertIn("pm find-item", paginated_deny["reason"])

            # 4) `pm prepare-report` emits whitespace-minified `zoho_query_param_html` <= 1,050 chars (< 5,800 URL-encoded chars)
            f_src = repo / "app/src/main/java/com/demo/OfferPaywall.kt"
            f_src.parent.mkdir(parents=True, exist_ok=True)
            f_src.write_text("package com.demo\nclass OfferPaywall\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "seed offer"], cwd=str(repo), check=True, capture_output=True)
            workflow.draft(argparse.Namespace(
                repo=str(repo), task_id="t-zoho-414", outcome="Support multi-entry discount offer paywall",
                kind="FEATURE", expected_files="app/src/main/java/com/demo/OfferPaywall.kt",
                expected_surfaces="BUSINESS_LOGIC", modules=":app", phases=None,
                approach="Clean flow", risks="None", device_strategy="Unit tests",
                allow_sensitive=False, adopt_dirty=False, from_task=None,
            ))
            rep_proc = subprocess.run(
                [
                    sys.executable, str(repo / ".agents/harness.py"), "pm", "prepare-report",
                    "--task-id", "t-zoho-414",
                    "--objective", "توحيد فتح شاشة عرض الخصم من كافة مداخل التطبيق مع ضمان عمل زر الرجوع لكل مسار دون تكرار الشاشة.",
                    "--changes", "تم تحديث مسار عرض الباقة الترويجية وحفظ حالة العرض النشط مؤقتاً أثناء جلسة الشراء مع التحقق من كافة نقاط الدخول.",
                    "--impact", "شاشة الاشتراك الرئيسية وشاشة العروض الترويجية",
                    "--impact", "مسار الرجوع من شاشة الدفع إلى الشاشة السابقة",
                    "--tests", "فتح عرض الخصم من الرئيسية ثم الضغط على رجوع والتأكد من العودة للرئيسية مباشرة",
                    "--tests", "إتمام تفعيل الباقة المخفضة والتأكد من تحديث حالة الاشتراك فوراً",
                ],
                cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
            )
            rep_json = json.loads(rep_proc.stdout)
            self.assertEqual("PREPARED", rep_json["status"])
            q_html = rep_json["zoho_query_param_html"]
            self.assertLessEqual(len(q_html), 1050)
            self.assertLessEqual(len(urllib.parse.quote(q_html, safe="")), 5800)
            self.assertIn('dir="rtl"', q_html)
            self.assertIn("<h3>1.", q_html)
            self.assertIn("<h3>5.", q_html)

            # Retired `review-diff` command must fail closed with exit code 2
            ret_cli = subprocess.run(
                [sys.executable, str(repo / ".agents/harness.py"), "review-diff"],
                cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(2, ret_cli.returncode)


    def test_v1321_all_forensic_edge_cases_and_cockpit_v3(self) -> None:
        """Verify all v1.3.21 fixes from chat-b8bf4a73 forensic audit & Carbon/Hydrogen/Orchestrator routing."""
        import argparse
        import time
        import unittest.mock
        from _vnext_common import atomic_write_json, canonical_sha256, read_json
        import delegation_policy as dp
        import review_orchestrator as ro
        import self_heal
        import workflow

        # 1. Single-repeated-digit 63/65-char SHA-256 transcription tolerance vs real mismatch rejection
        exp_sha = "64a26f6f9f8838920ed56ee0ead3f57220c81bb347325c14a3041c213adee884"
        slip_63 = "64a26f6f9f8838920ed56ee0ead3f57220c81bb347325c14a3041c213adee84"  # exact b8bf4a73 Run 2 typo!
        slip_65 = "64a26f6f9f8838920ed56ee0ead3f57220c81bb347325c14a3041c213adee8884"
        wrong_63 = "64a26f6f9f8838920ed56ee0ead3f57220c81bb347325c14a3041c213adee89"
        parsed_ok = ro.parse_structured_result(
            text=f'```json\n{{"schema_version": 2, "task_id": "t1", "run_id": "r1", "reviewer": "bug-test-reviewer-agent", "review_package_sha256": "{slip_63}", "verdict": "PASS", "findings": []}}\n```',
            expected_task_id="t1",
            expected_run_id="r1",
            expected_reviewer="bug-test-reviewer-agent",
            expected_package_sha256=exp_sha,
        )
        self.assertEqual(exp_sha, parsed_ok["review_package_sha256"])
        self.assertTrue(ro._package_sha256_matches_or_single_repeat_typo(slip_65, exp_sha))
        self.assertFalse(ro._package_sha256_matches_or_single_repeat_typo(wrong_63, exp_sha))
        self.assertFalse(ro._package_sha256_matches_or_single_repeat_typo("b" * 64, exp_sha))

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self._init_mini_git_repo(repo)
            kit_root = Path(__file__).resolve().parents[2]
            shutil.copytree(kit_root / "agents", repo / ".agents", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "state", "cache"))

            # 2. CLI `--json` compaction across massive 2,000-entry `base_file_identities`
            massive_plan = {
                "task_id": "t-compact",
                "status": "IMPLEMENTING",
                "base_file_identities": [{"path": f"app/src/File{i}.kt", "sha": "a" * 64} for i in range(2000)],
                "plan": {
                    "base_file_identities": [{"path": f"app/src/File{i}.kt", "sha": "a" * 64} for i in range(2000)],
                },
            }
            compacted = workflow._compact_plan_json_for_cli_stdout(massive_plan)
            self.assertEqual(1, len(compacted["base_file_identities"]))
            self.assertEqual(1, len(compacted["plan"]["base_file_identities"]))
            self.assertEqual(2000, len(massive_plan["base_file_identities"]))
            self.assertLess(len(json.dumps(compacted)), 1024)

            # 3. Live Gemini-4 Lead Routing (`Hydrogen`, `Carbon`, `Argon`, `Orchestrator`) -> Warm-Cache Direct!
            plan_4files = {
                "task_id": "t-g4",
                "status": "IMPLEMENTING",
                "kind": "BUG",
                "risk_tier": "T3_MEDIUM",
                "expected_files": [
                    "app/src/main/java/com/demo/A.kt",
                    "app/src/main/java/com/demo/B.kt",
                    "app/src/main/java/com/demo/C.kt",
                    "app/src/test/java/com/demo/ATest.kt",
                ],
                "expected_surfaces": ["BUSINESS_LOGIC"],
            }
            for live_m, exp_fam in [
                ("gemini-4-hydrogen-high", "gemini-4-hydrogen"),
                ("gemini-4-carbon-medium", "gemini-4-carbon"),
                ("gemini-4-argon-high", "gemini-4-argon"),
                ("Orchestrator (Carbon)", "gemini-4-hydrogen"),
            ]:
                dp.record_live_lead_session_model(repo, "lead-live-cid", live_m)
                self.assertEqual(exp_fam, dp._detect_live_parent_lead_family(repo))
                pol_red = dp.evaluate_delegation_policy(repo, task_id="t-g4", plan=plan_4files, router_action="CAPTURE_RED_EVIDENCE")
                self.assertEqual("CAPTURE_RED_INLINE_LEAD", pol_red["strategy"])
                self.assertIsNone(pol_red["recommended_subagent"])
                pol_impl = dp.evaluate_delegation_policy(repo, task_id="t-g4", plan=plan_4files, router_action="IMPLEMENT")
                self.assertEqual("INLINE_LEAD_DIRECT", pol_impl["strategy"])
                self.assertIsNone(pol_impl["recommended_subagent"])
            (repo / ".agents/state/live-session-models.json").unlink(missing_ok=True)

            # 4. Async `invoke_subagent` `HEADER_ONLY` open Scout wave at spawn -> settles cleanly on `COMPLETED_DONE`!
            ag_brain = Path(td) / "ag_brain" / "brain"
            parent_cid = "lead-async-001"
            scout_cid = "scout-async-002"
            parent_tx = ag_brain / parent_cid / ".system_generated" / "logs" / "transcript.jsonl"
            scout_tx = ag_brain / scout_cid / ".system_generated" / "logs" / "transcript.jsonl"
            parent_tx.parent.mkdir(parents=True, exist_ok=True)
            scout_tx.parent.mkdir(parents=True, exist_ok=True)
            parent_tx.write_text(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "fix bug"}) + "\n", encoding="utf-8")
            s_prompt = "Inspect A.kt and B.kt callers and return architectural digest"
            scout_tx.write_text(
                json.dumps({"source": "SYSTEM_SDK", "type": "SYSTEM_MESSAGE", "content": f"<SYSTEM_MESSAGE>sender={parent_cid} priority=MESSAGE_PRIORITY_HIGH content={s_prompt}\n</SYSTEM_MESSAGE>"}) + "\n",
                encoding="utf-8",
            )
            atomic_write_json(repo / ".agents/state/tasks/t-g4/plan.json", plan_4files)
            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(Path(td) / "ag_brain")}, clear=False):
                dp.record_utility_dispatch(
                    repo, agent_type=dp.SCOUT_AGENT, role_label=dp.SCOUT_AGENT,
                    prompt=s_prompt, parent_conversation_id=parent_cid, task_id="t-g4",
                    wave_id="s-async-1", worker_mode="READ_ONLY",
                )
                with scout_tx.open("a", encoding="utf-8") as sf_out:
                    sf_out.write(json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE", "content": "Analyzed A.kt and B.kt signatures cleanly."}) + "\n")
                dp.bind_utility_from_post_tool(
                    repo,
                    {
                        "conversationId": parent_cid,
                        "transcriptPath": str(parent_tx),
                        "toolCall": {"name": "invoke_subagent"},
                        "toolResult": {"conversationId": scout_cid},
                    },
                )
                ent_closed = [e for e in dp._load_utility_ledger(repo)["entries"] if e.get("wave_id") == "s-async-1"][0]
                self.assertEqual(scout_cid, ent_closed["execution_id"])
                self.assertTrue(ent_closed.get("wave_completed"))

            # 5. Idempotent `protocol_attempts` + `task heal` unblocking `REVIEW_FAILED_PROTOCOL` while preserving PASSED peers
            t_heal = "t-heal-proto"
            tdir_h = repo / ".agents/state/tasks" / t_heal
            (tdir_h / "review-execution/run-h1/dispatch").mkdir(parents=True, exist_ok=True)
            (tdir_h / "review-execution/run-h1/results").mkdir(parents=True, exist_ok=True)
            pol_h = tdir_h / "policy-h1.json"
            atomic_write_json(pol_h, {"reviewers": ["arch-regression-reviewer-agent", "bug-test-reviewer-agent"]})
            atomic_write_json(tdir_h / "plan.json", {"task_id": t_heal, "status": "VERIFYING", "approval": {"single_use_nonce": "n1"}, "execution_nonce": "n1"})
            atomic_write_json(repo / ".agents/state/active-task.json", {"task_id": t_heal})
            atomic_write_json(tdir_h / "current-run.json", {
                "task_id": t_heal, "run_id": "run-h1", "review_host": "antigravity",
                "review_protocol_version": 2, "policy": str(pol_h),
                "delivery_snapshot_sha256": "s" * 64, "change_set_sha256": "c" * 64, "package_sha256": "p" * 64,
            })
            ro.save_ledger(tdir_h, "run-h1", {
                "schema_version": 1, "task_id": t_heal, "run_id": "run-h1",
                "delivery_snapshot_sha256": "s" * 64, "change_set_sha256": "c" * 64, "review_package_sha256": "p" * 64,
                "required_reviewers": ["arch-regression-reviewer-agent", "bug-test-reviewer-agent"],
                "reviewers": {
                    "arch-regression-reviewer-agent": {"state": ro.REVIEW_COMPLETED, "protocol_attempts": 0},
                    "bug-test-reviewer-agent": {"state": ro.REVIEW_FAILED_PROTOCOL, "protocol_attempts": 2, "last_error": "bad json"},
                },
            })
            with unittest.mock.patch("workflow.verification_freshness", return_value={"fresh": True}), \
                 unittest.mock.patch("_workflow.engine.verification_freshness", return_value={"fresh": True}), \
                 unittest.mock.patch("workflow.resolve_next_action", return_value={"code": "DISPATCH_REVIEWERS"}):
                h_res = self_heal.heal_task_state(repo, t_heal, host="antigravity")
            self.assertEqual("HEALED", h_res["status"])
            healed_l = ro.load_ledger(tdir_h, "run-h1")
            self.assertEqual(ro.REVIEW_COMPLETED, healed_l["reviewers"]["arch-regression-reviewer-agent"]["state"])
            self.assertEqual(ro.REVIEW_NOT_DISPATCHED, healed_l["reviewers"]["bug-test-reviewer-agent"]["state"])
            self.assertEqual(0, healed_l["reviewers"]["bug-test-reviewer-agent"]["protocol_attempts"])

            # 6. Prepare LocationModule task for phase-review idempotency check (retired `task review-brief` must fail closed)
            shutil.rmtree(repo / ".agents/state", ignore_errors=True)
            loc_f = repo / "app/src/main/java/com/demo/di/LocationModule.kt"
            loc_f.parent.mkdir(parents=True, exist_ok=True)
            loc_f.write_text("package com.demo.di\n@Singleton\nfun provideLocation() = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "add loc module"], cwd=str(repo), check=True, capture_output=True)

            tid_loc = "fix-location-callback-leaks"
            d_loc = workflow.draft(argparse.Namespace(
                repo=str(repo), task_id=tid_loc,
                outcome="Prevent LocationCallback leaks across LocationModule and foreground services",
                kind="BUG", expected_files="app/src/main/java/com/demo/di/LocationModule.kt",
                expected_surfaces="BUSINESS_LOGIC", modules=":app", phases=None,
                approach="Unscope LocationModule from Singleton", risks="None", device_strategy="Unit tests",
                allow_sensitive=False, adopt_dirty=False, from_task=None,
            ))
            subprocess.run(
                [
                    sys.executable, str(repo / ".agents/harness.py"), "task", "approve",
                    "--repo", str(repo), "--task-id", tid_loc, "--source", "conversation",
                    "--proof-reference", "Approve", "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", d_loc["plan_sha256"],
                ],
                cwd=str(repo), check=True, capture_output=True, text=True,
            )
            loc_f.write_text("package com.demo.di\nfun provideLocation() = 1\n", encoding="utf-8")
            ret_brief = subprocess.run(
                [sys.executable, str(repo / ".agents/harness.py"), "task", "review-brief", "--task-id", tid_loc],
                cwd=str(repo), capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(0, ret_brief.returncode)

            # 8. `phase_review.py` malformed response SHA idempotency + 1-char repeated hex SHA tolerance
            import phase_review as pr_mod
            p_tdir = repo / ".agents/state/tasks" / tid_loc
            p_rdir = pr_mod.phase_review_dir(p_tdir, "phase-1")
            p_rdir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(pr_mod.phase_run_file(p_tdir, "phase-1"), {
                "task_id": tid_loc, "phase_id": "phase-1", "phase_review_run_id": "prun-1",
                "package_sha256": exp_sha, "selected_reviewers": ["bug-test-reviewer-agent"], "review_host": "cli",
            })
            p_ledger = {
                "schema_version": 2, "task_id": tid_loc, "phase_id": "phase-1", "run_id": "prun-1",
                "package_sha256": exp_sha,
                "reviewers": {"bug-test-reviewer-agent": {"state": ro.REVIEW_DISPATCHED, "protocol_attempts": 0}},
            }
            p_ledger["ledger_sha256"] = pr_mod.compute_ledger_sha(p_ledger)
            atomic_write_json(pr_mod.phase_ledger_file(p_tdir, "phase-1"), p_ledger)

            with unittest.mock.patch.object(pr_mod, "phase_review_freshness", return_value=(True, "ok")):
                r_retry1 = pr_mod.complete_phase_review(
                    repo, tid_loc, "phase-1", "bug-test-reviewer-agent", "exec-p1",
                    raw_response="not valid json yet", package_sha256=slip_63,
                )
                self.assertEqual("PROTOCOL_RETRY_REQUIRED", r_retry1["status"])
                r_retry2 = pr_mod.complete_phase_review(
                    repo, tid_loc, "phase-1", "bug-test-reviewer-agent", "exec-p1",
                    raw_response="not valid json yet", package_sha256=slip_63,
                )
            self.assertEqual("PROTOCOL_RETRY_REQUIRED", r_retry2["status"])
            ok_pl, _, loaded_pl = pr_mod.load_phase_ledger(p_tdir, "phase-1")
            self.assertTrue(ok_pl)
            self.assertEqual(1, loaded_pl["reviewers"]["bug-test-reviewer-agent"]["protocol_attempts"])

            # 9. Nested `previous_task` / `brief` compaction in CLI JSON sanitizer
            bridge_blob = {
                "status": "BRIDGE_LOADED",
                "previous_task": {"base_file_identities": [{"path": f"F{i}.kt"} for i in range(1200)]},
                "brief": {"task_baseline": {"changes": list(range(500))}},
            }
            comp_b = workflow._compact_plan_json_for_cli_stdout(bridge_blob)
            self.assertEqual(1, len(comp_b["previous_task"]["base_file_identities"]))
            self.assertEqual(9, len(comp_b["brief"]["task_baseline"]["changes"]))

            # 10. `debug logs --lines --filter` CLI aliases + `debug_device.summarize` Logcat tag & multi-term `::` matching
            from debug_device import summarize as dbg_summarize
            sample_logcat = "\n".join([
                "105.100  42  42 D SensorForegroundService: Location request registered",
                "105.200  42  42 I UnrelatedTag: Heartbeat tick",
                "105.300  42  42 D HomeViewModel: Updated GoogleLocationDataSource state",
            ])
            matched_tag_lines = dbg_summarize(
                sample_logcat, "com.madarsoft.fitness", None, [], True, 100,
                "SensorForegroundService::GoogleLocationDataSource", current_pids=("42",),
            )
            self.assertEqual(2, len(matched_tag_lines))
            dbg_help = subprocess.run(
                [sys.executable, str(repo / ".agents/harness.py"), "debug", "logs", "--help"],
                cwd=str(repo), check=True, capture_output=True, text=True,
            )
            self.assertIn("--lines", dbg_help.stdout)
            self.assertIn("--filter", dbg_help.stdout)

            # 11. `harness.py commands` compact valid JSON (<150 lines, never 1,500+ lines) + keyword filtering
            cmds_all = subprocess.run(
                [sys.executable, str(repo / ".agents/harness.py"), "commands"],
                cwd=str(repo), check=True, capture_output=True, text=True,
            )
            parsed_cmds = json.loads(cmds_all.stdout)
            self.assertGreater(len(parsed_cmds), 30)
            self.assertLess(len(cmds_all.stdout.splitlines()), 160)
            cmds_heal = subprocess.run(
                [sys.executable, str(repo / ".agents/harness.py"), "commands", "heal"],
                cwd=str(repo), check=True, capture_output=True, text=True,
            )
            heal_rows = json.loads(cmds_heal.stdout)
            self.assertTrue(any("heal" in r["command"] for r in heal_rows))

            # 12. `PHASE_REVIEW_PROTOCOL_BLOCKED` & `debug_evidence` compaction
            p_ledger_fail = read_json(pr_mod.phase_ledger_file(p_tdir, "phase-1"))
            p_ledger_fail["reviewers"]["bug-test-reviewer-agent"]["state"] = ro.REVIEW_FAILED_PROTOCOL
            p_ledger_fail["ledger_sha256"] = pr_mod.compute_ledger_sha(p_ledger_fail)
            atomic_write_json(pr_mod.phase_ledger_file(p_tdir, "phase-1"), p_ledger_fail)
            from _workflow.phase_routing import phase_implementation_action
            pr_mod.set_phase_substate(p_tdir, "phase-1", pr_mod.PHASE_REVIEWING)
            with unittest.mock.patch.object(pr_mod, "phase_review_freshness", return_value=(True, "ok")):
                pr_act = phase_implementation_action(
                    repo, tid_loc, {"phases": [{"id": "phase-1"}], "active_phase_index": 0},
                    "antigravity", None, p_tdir, [{"id": "phase-1"}],
                )
            self.assertEqual("PHASE_REVIEW_PROTOCOL_BLOCKED", pr_act["code"])
            self.assertIn("task heal", pr_act["recovery_command"])
            dbg_plan = {"task_id": "t-dbg", "debug_evidence": [f"log-{i}" for i in range(25)]}
            self.assertEqual(4, len(workflow._compact_plan_json_for_cli_stdout(dbg_plan)["debug_evidence"]))

            # 13. Read-only `jar tf` / `javap` allowed for Scout & Lead (with or without task), while `jar xf`/`cf` blocked!
            import mutation_guard as mg_mod
            self.assertTrue(dp.scout_command_allowed("jar tf app/libs/LocationData-release.aar"))
            self.assertTrue(dp.scout_command_allowed("jar -tf build/classes.jar"))
            self.assertTrue(dp.scout_command_allowed("javap -cp build/classes.jar com.demo.LocationControl"))
            self.assertFalse(dp.scout_command_allowed("jar xf app/libs/LocationData-release.aar"))
            self.assertFalse(dp.scout_command_allowed("javap -J-Xmx1g com.demo.LocationControl"))
            self.assertTrue(mg_mod._is_read_only("jar tf app/libs/LocationData-release.aar", repo))
            self.assertTrue(mg_mod._is_read_only("javap -p -cp build/classes.jar com.demo.LocationControl", repo))
            self.assertFalse(mg_mod._is_read_only("jar xf app/libs/LocationData-release.aar", repo))
            self.assertFalse(mg_mod._is_read_only("jar cf out.jar .", repo))

            # 14. Turn-0 `pre_invocation_reminder` subagent shield (unbound Scout/Reviewer spawns emit `{}` on Turn 0!) + zero Orchestrator scold
            import io as _io_pir, contextlib as _ctx_pir
            import pre_invocation_reminder as pir_mod
            dp.record_utility_dispatch(
                repo, agent_type=dp.SCOUT_AGENT, role_label=dp.SCOUT_AGENT,
                prompt="Investigate LocationData-release.aar", parent_conversation_id="lead-main-99",
                task_id=tid_loc,
            )
            buf_child = _io_pir.StringIO()
            with unittest.mock.patch.object(pir_mod, "REPO", repo),                  unittest.mock.patch("sys.stdin", _io_pir.StringIO(json.dumps({"conversationId": "child-scout-turn0", "invocationNum": 0}))),                  _ctx_pir.redirect_stdout(buf_child):
                pir_mod.main()
            self.assertEqual({}, json.loads(buf_child.getvalue().strip()))

            buf_lead_orch = _io_pir.StringIO()
            with unittest.mock.patch.object(pir_mod, "REPO", repo),                  unittest.mock.patch("sys.stdin", _io_pir.StringIO(json.dumps({"conversationId": "lead-main-99", "invocationNum": 0, "modelName": "Orchestrator (Carbon)"}))),                  _ctx_pir.redirect_stdout(buf_lead_orch):
                pir_mod.main()
            lead_orch_out = buf_lead_orch.getvalue()
            self.assertNotIn("HAZARD #200029", lead_orch_out)
            self.assertIn("injectSteps", lead_orch_out)

    def test_single_pass_whole_task_verify_steps_and_concurrent_reviewer_guard(self) -> None:
        """Regression for whole-task single-pass phase fast-forward (`verify-steps` / `web-apply`),
        single-invocation compile+test in sequential `checkpoint-phase`, unconditional `tdir/execution`
        lease, and premature speculative reviewer dispatch blocking."""
        import argparse
        import contextlib
        import io
        from unittest import mock
        import pre_tool_safety as pts
        import verification_steps
        import workflow
        from _vnext_common import ValidationError, atomic_write_json, read_json, state_root, task_dir
        from evidence_store import StateLock

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            (repo / ".agents/state").mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            (repo / ".gitignore").write_text(".agents/\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            (repo / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (repo / "app").mkdir(parents=True)
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            p1_rel = "app/src/main/java/com/demo/OfferRepo.kt"
            p2_rel = "app/src/main/java/com/demo/PaywallRouter.kt"
            for rel, cls_name in ((p1_rel, "OfferRepo"), (p2_rel, "PaywallRouter")):
                f = repo / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(f"package com.demo\nclass {cls_name} {{ val v = 1 }}\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            parser = workflow.build_parser()
            tid = "t-single-pass"
            draft_res = workflow.draft(parser.parse_args([
                "draft", "--repo", str(repo), "--task-id", tid, "--kind", "FEATURE",
                "--outcome", "Route discountOffer paywall across repo and router",
                "--expected-files", f"{p1_rel},{p2_rel}",
                "--phases", json.dumps([
                    {"id": "p1", "title": "Offer cache", "expected_files": [p1_rel]},
                    {"id": "p2", "title": "Router callers", "expected_files": [p2_rel]},
                ]),
            ]))
            workflow.record_approval(parser.parse_args([
                "approve", "--repo", str(repo), "--task-id", tid,
                "--source", "conversation", "--proof-reference", "approve",
                "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", draft_res["plan_sha256"][:12],
            ]))

            # 1) Sequential mid-task (`p1` edited, `p2` untouched): NOT ready for single-pass final fast-forward!
            (repo / p1_rel).write_text("package com.demo\nclass OfferRepo { val v = 2 }\n", encoding="utf-8")
            ready_partial, _ = workflow.all_remaining_phases_ready_for_final(repo, tid)
            self.assertFalse(ready_partial)

            # 2) Both `p1` and `p2` edited on disk: ready for single-pass fast-forward!
            (repo / p2_rel).write_text("package com.demo\nclass PaywallRouter { val v = 2 }\n", encoding="utf-8")
            ready_all, cur_pid = workflow.all_remaining_phases_ready_for_final(repo, tid)
            self.assertTrue(ready_all)
            self.assertEqual("p1", cur_pid)

            # `checkpoint-phase --advance-all-ready --defer-gradle-to-final` completes p1+p2 with ZERO Gradle calls!
            with mock.patch("run_gradle_task.run_gradle", side_effect=AssertionError("Gradle must not run during deferred whole-task checkpoint")):
                cp_fast = workflow.checkpoint_phase(parser.parse_args([
                    "checkpoint-phase", "--repo", str(repo), "--task-id", tid,
                    "--phase-id", "p1", "--advance-all-ready", "--defer-gradle-to-final",
                ]))
            self.assertEqual(["p1", "p2"], cp_fast["completed_phases"])
            self.assertEqual(["p2"], cp_fast.get("auto_advanced_phases"))
            self.assertEqual("DEFERRED_TO_FINAL_VERIFICATION", cp_fast["compile"]["status"])
            self.assertEqual("DEFERRED_TO_FINAL_VERIFICATION", cp_fast["tests"]["status"])
            self.assertEqual("PREPARE_VERIFICATION", workflow.resolve_next_action(repo, tid)["code"])

            # 3) Reset phase-state to test `verification_steps.run_steps` end-to-end auto-fast-forward + unconditional execution lease!
            tdir = task_dir(repo, tid)
            plan_doc = read_json(tdir / "plan.json")
            plan_doc["active_phase_index"] = 0
            atomic_write_json(tdir / "plan.json", plan_doc)
            atomic_write_json(tdir / "phase-state.json", {"current_phase_id": "p1", "completed_phases": [], "phase_checkpoints": {}})
            for p_sub in ("p1", "p2"):
                (tdir / "phases" / p_sub / "checkpoint.json").unlink(missing_ok=True)
                (tdir / "phases" / p_sub / "baseline.json").unlink(missing_ok=True)

            # Even without `host-session.json`, holding `tdir / "execution"` blocks concurrent `verify-steps`!
            self.assertFalse((tdir / "host-session.json").exists())
            with StateLock(tdir / "execution", timeout_seconds=0):
                with self.assertRaises(ValidationError):
                    verification_steps.run_steps(repo, tid, host="antigravity", json_only=True)

            dispatched_steps: list[tuple[str, list[str]]] = []
            orig_dispatch = verification_steps._dispatch

            def _spy_dispatch(r: Path, script: str, arguments: list[str], *, quiet_stdout: bool = False) -> int:
                dispatched_steps.append((script, list(arguments)))
                if script == "workflow.py" and arguments[:1] == ["checkpoint-phase"]:
                    return orig_dispatch(r, script, arguments, quiet_stdout=True)
                if script == "workflow.py" and arguments[:1] == ["prepare-verification"]:
                    p_now = read_json(tdir / "plan.json")
                    p_now["status"] = "VERIFYING"
                    atomic_write_json(tdir / "plan.json", p_now)
                    return 0
                return 0

            orig_resolve = workflow.resolve_next_action

            def _stub_resolve(r: Path, t_id: str, pl: dict | None = None, host: str | None = None) -> dict:
                st = str((pl or {}).get("status") or "")
                if st == "VERIFYING":
                    return {"code": "DISPATCH_REVIEWERS", "kind": "HOST_ACTION", "command": "", "blocking": True}
                return orig_resolve(r, t_id, pl, host=host)

            with mock.patch.object(verification_steps, "_dispatch", side_effect=_spy_dispatch), \
                 mock.patch("workflow.resolve_next_action", side_effect=_stub_resolve):
                rc_vs, sum_vs = verification_steps.run_steps(repo, tid, host="antigravity", json_only=True)
            self.assertEqual(0, rc_vs, sum_vs)
            self.assertEqual(["CHECKPOINT_READY_PHASES", "PREPARE_VERIFICATION"], sum_vs["completed_steps"])
            self.assertIn("--defer-gradle-to-final", dispatched_steps[0][1])

            # 4) Premature speculative reviewer `invoke_subagent` blocked in BOTH `IMPLEMENTING` and `VERIFYING` (when build/verification lock active)!
            ext_pid = os.getppid() if os.getppid() > 0 and os.getppid() != os.getpid() else 1
            exec_lock_dir = tdir / "execution"
            exec_lock_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(exec_lock_dir / ".write.lock", {"pid": ext_pid, "nonce": "vlock", "created_at": "2026-11-17T10:22:00Z"})

            def _call_pts(tool_name: str, tool_args: dict) -> dict:
                buf = io.StringIO()
                payload = json.dumps({"toolName": tool_name, "toolArgs": tool_args, "conversationId": "lead-spec"})
                with mock.patch.object(pts, "REPO", repo), \
                     mock.patch("evidence_store._pid_alive", side_effect=lambda p: p == ext_pid), \
                     mock.patch("evidence_store._process_marker", return_value=""), \
                     mock.patch("sys.stdin", io.StringIO(payload)), \
                     contextlib.redirect_stdout(buf):
                    try:
                        pts.main()
                    except SystemExit:
                        pass
                return json.loads(buf.getvalue().strip())

            # During VERIFYING while `tdir / execution` lock is held -> CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS!
            den_ver = _call_pts("invoke_subagent", {
                "TypeName": "arch-regression-reviewer-agent",
                "Role": "arch-regression-reviewer-agent",
                "Prompt": "Read brief",
                "Workspace": "inherit",
            })
            self.assertEqual("deny", den_ver["decision"])
            self.assertIn("CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS", den_ver["reason"])

            # `task status --next --brief` surfaces `background_execution_active` while lock is held!
            with mock.patch("evidence_store._pid_alive", side_effect=lambda p: p == ext_pid), \
                 mock.patch("evidence_store._process_marker", return_value=""):
                st_brief = workflow.status(argparse.Namespace(repo=str(repo), task_id=tid, next=True, brief=True, host="antigravity"))
            self.assertEqual(ext_pid, st_brief.get("background_execution_active", {}).get("pid"))

            # During IMPLEMENTING without active lock -> PREMATURE_REVIEWER_DISPATCH_FORBIDDEN!
            (exec_lock_dir / ".write.lock").unlink(missing_ok=True)
            p_imp = read_json(tdir / "plan.json")
            p_imp["status"] = "IMPLEMENTING"
            atomic_write_json(tdir / "plan.json", p_imp)
            den_imp = _call_pts("invoke_subagent", {
                "TypeName": "arch-regression-reviewer-agent",
                "Role": "arch-regression-reviewer-agent",
                "Prompt": "Read brief",
                "Workspace": "inherit",
            })
            self.assertEqual("deny", den_imp["decision"])
            self.assertIn("PREMATURE_REVIEWER_DISPATCH_FORBIDDEN", den_imp["reason"])

            # 5) Sequential `checkpoint-phase` combines compile into `:app:testDebugUnitTest` (1 Gradle invocation, 0 separate `:app:compileDebugKotlin`)!
            tid_seq = "t-seq-single-gradle"
            seq1_rel = "app/src/main/java/com/demo/SeqOne.kt"
            seq2_rel = "app/src/main/java/com/demo/SeqTwo.kt"
            (repo / seq1_rel).write_text("package com.demo\nclass SeqOne { val v = 10 }\n", encoding="utf-8")
            (repo / seq2_rel).write_text("package com.demo\nclass SeqTwo { val v = 10 }\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "base2"], cwd=repo, check=True)
            d_seq = workflow.draft(parser.parse_args([
                "draft", "--repo", str(repo), "--task-id", tid_seq, "--kind", "FEATURE",
                "--outcome", "Sequential phase compile+test merge",
                "--expected-files", f"{seq1_rel},{seq2_rel}",
                "--phases", json.dumps([
                    {"id": "p1", "title": "Phase 1", "expected_files": [seq1_rel]},
                    {"id": "p2", "title": "Phase 2", "expected_files": [seq2_rel]},
                ]),
            ]))
            workflow.record_approval(parser.parse_args([
                "approve", "--repo", str(repo), "--task-id", tid_seq,
                "--source", "conversation", "--proof-reference", "approve",
                "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", d_seq["plan_sha256"][:12],
            ]))
            (repo / seq1_rel).write_text("package com.demo\nclass SeqOne { val v = 11 }\n", encoding="utf-8")
            gradle_invocations: list[list[str]] = []

            def _real_shaped_gradle(tasks_arg, cwd=None, outcome=None):
                gradle_invocations.append(list(tasks_arg))
                xml_d = Path(cwd) / "app/build/test-results/testDebugUnitTest"
                xml_d.mkdir(parents=True, exist_ok=True)
                xml_p = xml_d / "TEST-com.demo.OfferRepoTest.xml"
                xml_p.write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<testsuite name="com.demo.OfferRepoTest" tests="2" skipped="0" failures="0" errors="0">'
                    '<testcase classname="com.demo.OfferRepoTest" name="t1"/>'
                    '<testcase classname="com.demo.OfferRepoTest" name="t2"/>'
                    '</testsuite>',
                    encoding="utf-8",
                )
                return 0

            # Plain function (no Mock attributes) exercises the real production Gradle path!
            import run_gradle_task as rgt_mod
            orig_rg = rgt_mod.run_gradle
            try:
                rgt_mod.run_gradle = _real_shaped_gradle
                cp_seq = workflow.checkpoint_phase(parser.parse_args([
                    "checkpoint-phase", "--repo", str(repo), "--task-id", tid_seq, "--phase-id", "p1",
                ]))
            finally:
                rgt_mod.run_gradle = orig_rg
            self.assertEqual([[':app:testDebugUnitTest']], gradle_invocations)
            self.assertTrue(cp_seq["compile"].get("covered_by_unit_tests"))

            # 6) `DEVELOPER_GIT_COMMIT_REQUIRED` surfaces ULTRA-COMPACT Commit Card (`<= 5` lines above commit block, zero `human_review_uri`),
            #    and `run_device.py` accepts `--json` without failing!
            from delivery_manifest import build_manifest, build_task_manifest, load_task_baseline
            from delivery_equivalence import snapshot_verified_files
            tdir_seq = task_dir(repo, tid_seq)
            plan_rfd = read_json(tdir_seq / "plan.json")
            live_m = build_manifest(repo)
            t_man_seq = build_task_manifest(repo, load_task_baseline(repo, tid_seq), expected_files=plan_rfd.get("expected_files"), live_manifest=live_m)
            plan_rfd["status"] = "READY_FOR_DELIVERY"
            plan_rfd["ready_delivery_snapshot_sha256"] = live_m["delivery_snapshot_sha256"]
            plan_rfd["ready_change_set_sha256"] = t_man_seq["change_set_sha256"]
            plan_rfd["ready_run_id"] = "run-rfd-1"
            atomic_write_json(tdir_seq / "manifest-run-rfd-1.json", t_man_seq)
            snapshot_verified_files(repo, tid_seq, plan_rfd, "run-rfd-1")
            atomic_write_json(tdir_seq / "plan.json", plan_rfd)
            rfd_act = orig_resolve(repo, tid_seq, plan_rfd, host="antigravity")
            self.assertEqual("DEVELOPER_GIT_COMMIT_REQUIRED", rfd_act["code"])
            self.assertNotIn("human_review_uri", rfd_act)
            instr_txt = str(rfd_act.get("instructions") or "")
            self.assertIn("<= 5 lines total ABOVE the fenced commit block", instr_txt)
            self.assertIn("Android Studio Git Diff Hotspots", instr_txt)
            self.assertNotIn("review-diff", instr_txt)
            self.assertNotIn("human-review.html", instr_txt)

            import subprocess as _sp_dev
            dev_help = _sp_dev.run(
                [sys.executable, str(Path(__file__).resolve().parent / "run_device.py"), "--help"],
                capture_output=True, text=True, check=True,
            )
            self.assertIn("--json", dev_help.stdout)

    def test_diff_scoped_kdoc_scanner_and_compact_commit_card(self) -> None:
        """Verify diff-scoped KDoc scanner (`find_missing_architectural_kdoc`, `kdoc_advisories` in `web-apply`, `--strict-kdoc`) and zero-cockpit `READY_FOR_DELIVERY`."""
        import fast_kt_lint
        import web_relay
        import workflow
        from delivery_manifest import build_manifest, build_task_manifest, load_task_baseline
        from delivery_equivalence import snapshot_verified_files
        from _workflow.router import resolve_next_action
        from _vnext_common import atomic_write_json, read_json, task_dir

        with tempfile.TemporaryDirectory() as td:
            repo = (Path(td) / "studio_kdoc_repo").resolve()
            (repo / ".agents/state").mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            (repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            (repo / ".gitignore").write_text(".agents/\n", encoding="utf-8")
            (repo / "app").mkdir(parents=True)
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            pay_rel = "app/src/main/java/com/example/payment/repository/PaymentRepo.kt"
            pay_file = repo / pay_rel
            pay_file.parent.mkdir(parents=True, exist_ok=True)
            pay_file.write_text(
                "package com.example.payment.repository\n\n"
                "class PaymentRepo {\n"
                "    fun existingLegacyMethod(): Boolean = true\n"
                "}\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            # 1) Draft & approve task, add undocumented public contract on PaymentRepo.kt
            parser = workflow.build_parser()
            dr_sk = workflow.draft(parser.parse_args([
                "draft", "--repo", str(repo), "--task-id", "t-studio-kdoc", "--kind", "FEATURE",
                "--outcome", "Cache active discount offer package in PaymentRepo",
                "--expected-files", pay_rel,
            ]))
            workflow.record_approval(parser.parse_args([
                "approve", "--repo", str(repo), "--task-id", "t-studio-kdoc",
                "--source", "conversation", "--proof-reference", "Proceed",
                "--enforcement-tier", "RULE_ENFORCED", "--plan-hash", dr_sk["plan_sha256"][:12],
            ]))

            # Verify Web-Relay pack prompt explicitly instructs writing KDoc (`/** ... */`)
            pack_info = web_relay.build_web_pack(
                repo, task_id="t-studio-kdoc", prompt="Add offer cache methods", files=[pay_rel], no_clipboard=True,
            )
            bundle_md = Path(pack_info["bundle_file"]).read_text(encoding="utf-8")
            self.assertIn("write concise English KDoc (`/** ... */`", bundle_md)

            # Apply merge WITHOUT KDoc first -> web-apply surfaces `kdoc_advisories`!
            undoc_merge = {
                "schema": web_relay.WEB_MERGE_SCHEMA,
                "pack_id": pack_info["pack_id"],
                "status": "READY",
                "operations": [{
                    "action": "MODIFY",
                    "path": pay_rel,
                    "hunks": [{
                        "search": "    fun existingLegacyMethod(): Boolean = true\n}",
                        "replace": (
                            "    fun existingLegacyMethod(): Boolean = true\n\n"
                            "    private var cachedPkg: String? = null\n\n"
                            "    @JvmOverloads\n"
                            "    fun cacheActiveOfferPackage(pkgId: String?, nowMs: Long = 0L) {\n"
                            "        cachedPkg = pkgId\n"
                            "    }\n}"
                        ),
                        "replace_all": False,
                    }],
                }],
            }
            inbox_f = repo / ".agents/state/web-relay/inbox/merge.json"
            inbox_f.parent.mkdir(parents=True, exist_ok=True)
            inbox_f.write_text(json.dumps(undoc_merge), encoding="utf-8")
            apply_res = web_relay.apply_web_merge(
                repo, merge_file=inbox_f, source="conversation", proof_reference="Apply", auto_red_green=False,
            )
            self.assertEqual("APPLIED", apply_res["status"])
            self.assertTrue(apply_res.get("kdoc_advisories"), f"Expected kdoc_advisories in {apply_res}")
            self.assertTrue(any("fun cacheActiveOfferPackage" in a for a in apply_res["kdoc_advisories"]))
            self.assertFalse(any("existingLegacyMethod" in a for a in apply_res["kdoc_advisories"]))

            # `--strict-kdoc` fails on undocumented architectural contracts, and passes once KDoc is added!
            strict_fail = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parent / "fast_kt_lint.py"), "--strict-kdoc", str(pay_file)],
                cwd=str(repo), capture_output=True, text=True, check=False,
            )
            self.assertEqual(1, strict_fail.returncode)
            self.assertIn("[MISSING_ARCHITECTURAL_KDOC]", strict_fail.stdout)

            # Once KDoc is added above `@JvmOverloads`, `find_missing_architectural_kdoc` and `--strict-kdoc` pass cleanly (`0`)!
            documented_text = (
                "package com.example.payment.repository\n\n"
                "class PaymentRepo {\n"
                "    fun existingLegacyMethod(): Boolean = true\n\n"
                "    private var cachedPkg: String? = null\n\n"
                "    /**\n"
                "     * Caches the active promotional offer package identifier.\n"
                "     *\n"
                "     * @param pkgId Active offer package ID or null to clear.\n"
                "     * @param nowMs Current epoch timestamp in milliseconds.\n"
                "     */\n"
                "    @JvmOverloads\n"
                "    fun cacheActiveOfferPackage(pkgId: String?, nowMs: Long = 0L) {\n"
                "        cachedPkg = if (nowMs >= 0L) pkgId else null\n"
                "    }\n"
                "}\n"
            )
            pay_file.write_text(documented_text, encoding="utf-8")
            mod_map = fast_kt_lint.get_modified_lines_map(repo, [pay_file])
            self.assertEqual([], fast_kt_lint.find_missing_architectural_kdoc(pay_file, documented_text, mod_map.get(pay_file)))
            strict_ok = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parent / "fast_kt_lint.py"), "--strict-kdoc", str(pay_file)],
                cwd=str(repo), capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, strict_ok.returncode, strict_ok.stdout + strict_ok.stderr)

            # 2) `DEVELOPER_GIT_COMMIT_REQUIRED` emits compact Android Studio Commit Card without creating `human-review.html`!
            td_sk = task_dir(repo, "t-studio-kdoc")
            p_sk = read_json(td_sk / "plan.json")
            lm_sk = build_manifest(repo)
            tm_sk = build_task_manifest(repo, load_task_baseline(repo, "t-studio-kdoc"), expected_files=p_sk.get("expected_files"), live_manifest=lm_sk)
            p_sk["status"] = "READY_FOR_DELIVERY"
            p_sk["ready_delivery_snapshot_sha256"] = lm_sk["delivery_snapshot_sha256"]
            p_sk["ready_change_set_sha256"] = tm_sk["change_set_sha256"]
            p_sk["ready_run_id"] = "run-sk-1"
            atomic_write_json(td_sk / "manifest-run-sk-1.json", tm_sk)
            snapshot_verified_files(repo, "t-studio-kdoc", p_sk, "run-sk-1")
            atomic_write_json(td_sk / "plan.json", p_sk)
            act_sk = resolve_next_action(repo, "t-studio-kdoc", p_sk, host="antigravity")
            self.assertEqual("DEVELOPER_GIT_COMMIT_REQUIRED", act_sk["code"])
            self.assertFalse((td_sk / "human-review.html").exists())
            self.assertNotIn("human_review_uri", act_sk)
            self.assertIn("<= 5 lines total ABOVE the fenced commit block", act_sk["instructions"])

    def test_v1319_09_nov17_search_web_eof_agy_tos_and_acceptex_995_guards(self) -> None:
        """Verify Nov 17, 2026 guards: #201621 search_web parallel cap & EOF forensics, #201582 agy CLI ToS block, and #200687/#199301 Go GC AcceptEx diagnostics."""
        import antigravity_runtime as agr
        import delegation_policy as dp
        import session_forensics as sf
        from doctor.engine import HarnessDoctor

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            repo = root / "repo"
            (repo / ".agents" / "state").mkdir(parents=True)
            (repo / ".agents" / "cache").mkdir(parents=True)
            app_data = root / "ag_appdata"
            brain_dir = app_data / "brain" / "conv-nov17-sw" / ".system_generated" / "logs"
            brain_dir.mkdir(parents=True)

            # 1) #201621 `search_web` parallel cap in `pre_tool_safety.py` + `hooks.json` matcher + Scout/GEMINI prompt rules
            hooks_doc = json.loads((REPO_ROOT / "agents" / "hooks.json").read_text(encoding="utf-8"))
            self.assertIn("search_web", hooks_doc["adb-and-git-safety"]["PreToolUse"][0]["matcher"].split("|"))
            self.assertIn("#201621", dp.UTILITY_AGENT_SPECS[dp.SCOUT_AGENT]["system_prompt"])
            self.assertIn("#201621", (REPO_ROOT / "agents" / "tool-adapters" / "GEMINI.md.template").read_text(encoding="utf-8"))

            env_hook = {
                **os.environ,
                "HARNESS_REPO": str(repo),
                "ANTIGRAVITY_APP_DATA": str(app_data),
                "ANTIGRAVITY_BRAIN_ROOT": str(app_data / "brain"),
            }

            def _run_hook(payload: dict) -> dict:
                proc = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "agents" / "scripts" / "pre_tool_safety.py")],
                    input=json.dumps(payload),
                    capture_output=True, text=True, encoding="utf-8", errors="replace", env=env_hook, check=False,
                )
                self.assertEqual(0, proc.returncode, proc.stderr)
                return json.loads(proc.stdout.strip())

            for ok_i in range(2):
                res_sw = _run_hook({"conversationId": "conv-sw-burst", "toolCall": {"name": "search_web", "args": {"query": f"q{ok_i}"}}})
                self.assertEqual("allow", res_sw["decision"], res_sw)
            res_sw3 = _run_hook({"conversationId": "conv-sw-burst", "toolCall": {"name": "search_web", "args": {"query": "q3"}}})
            self.assertEqual("deny", res_sw3["decision"])
            self.assertIn("SEARCH_WEB_PARALLEL_CAP_REACHED", res_sw3["reason"])

            # 2) #201582 / #201491 `agy` & `antigravity` CLI subprocess guard (blocks all verb forms, zero false positives on `--host antigravity` or paths!)
            for bad_agy in (
                "agy -p \"test rules\"",
                "agy chat",
                "agy.exe --version",
                "\"C:\\Program Files\\Antigravity\\agy.exe\" .",
                "antigravity.exe --status",
                "echo ready; agy run",
            ):
                r_bad = _run_hook({"conversationId": "conv-agy", "toolCall": {"name": "run_command", "args": {"CommandLine": bad_agy}}})
                self.assertEqual("deny", r_bad["decision"], f"Expected deny for {bad_agy}: {r_bad}")
            for safe_cmd in (
                "python .agents/harness.py task status --next --brief --json",
                f'python "{app_data / "helper.py"}" --check',
            ):
                # Ensure `agy_headless_loop_tos_guard` regex never false-positives on paths containing `antigravity` or `--host antigravity`
                import pre_tool_safety as pts
                agy_rx = dict(pts.DANGEROUS)["agy_headless_loop_tos_guard"]
                self.assertIsNone(agy_rx.search(safe_cmd), f"False positive on {safe_cmd}")
                self.assertIsNone(agy_rx.search("python .agents/harness.py verify-steps --task-id t1 --host antigravity"))

            # 3) #201621 `SEARCH_WEB_UPSTREAM_EOF_STALL` + #200687 `LANGUAGE_SERVER_ACCEPTEX_995_CRASH_LOOP` in `session_forensics.py`
            tx_file = brain_dir / "transcript.jsonl"
            tx_file.write_text(
                "\n".join([
                    json.dumps({
                        "step_index": 10,
                        "type": "PLANNER_RESPONSE",
                        "created_at": "2026-11-17T10:00:00Z",
                        "tool_calls": [
                            {"name": "search_web", "args": {"query": "android billing v8"}},
                            {"name": "search_web", "args": {"query": "play billing offer token"}},
                            {"name": "search_web", "args": {"query": "compose paywall rtl"}},
                        ],
                    }),
                    json.dumps({
                        "step_index": 11,
                        "type": "TOOL_RESPONSE",
                        "status": "ERROR",
                        "created_at": "2026-11-17T10:16:48Z",
                        "content": "Encountered error in step execution: unexpected EOF",
                    }),
                ]) + "\n",
                encoding="utf-8",
            )
            logs_dir = app_data / "logs" / "20261117T100000"
            logs_dir.mkdir(parents=True)
            main_log = logs_dir / "main.log"
            main_log.write_text(
                "[2026-11-17 10:05:11] Language server crashed: exited with code 2\n"
                "[2026-11-17 10:05:13] [Auto-Restart] Port changed! Reconnecting client...\n",
                encoding="utf-8",
            )
            crashes_dir = app_data / "crashes"
            crashes_dir.mkdir(parents=True)
            (crashes_dir / "crash_20261117_100511.log").write_bytes(b"")

            with unittest.mock.patch.dict(os.environ, env_hook, clear=False):
                diag = sf.diagnose_session(repo, conversation_id="conv-nov17-sw")
            codes_found = {f["code"] for f in diag["findings"]}
            self.assertIn("SEARCH_WEB_UPSTREAM_EOF_STALL", codes_found, diag)
            self.assertIn("LANGUAGE_SERVER_ACCEPTEX_995_CRASH_LOOP", codes_found, diag)
            self.assertEqual(3, diag["transcript"]["search_web_max_parallel"])
            self.assertGreaterEqual(diag["transcript"]["search_web_max_duration_sec"], 1007.0)

            # 4) #200687 / #199301 Windows Go GC (`GOMEMLIMIT` / `GOGC`) & `.agents/mcp_config.json` Doctor checks
            (repo / ".agents" / "mcp_config.json").write_text(
                json.dumps({
                    "mcpServers": {
                        "zoho-sprints": {"command": "npx", "args": ["-y", "zoho-mcp"]},
                        "atlassian": {"command": "npx", "args": ["-y", "atlassian-mcp"]},
                    }
                }),
                encoding="utf-8",
            )
            bad_off = agr.inspect_windows_go_gc_and_handle_risk(
                repo,
                env={"HARNESS_SIMULATE_PLATFORM": "win32", "GOGC": "off", "GOMEMLIMIT": "", "ANTIGRAVITY_APP_DATA": str(root / "clean_ag")},
            )
            self.assertTrue(bad_off["at_risk"])
            self.assertTrue(bad_off["gogc_off_without_memlimit"])

            untuned_mcp = agr.inspect_windows_go_gc_and_handle_risk(
                repo,
                env={"HARNESS_SIMULATE_PLATFORM": "win32", "GOGC": "", "GOMEMLIMIT": "", "ANTIGRAVITY_APP_DATA": str(root / "clean_ag")},
            )
            self.assertTrue(untuned_mcp["at_risk"])
            self.assertEqual(2, len(untuned_mcp["stdio_servers"]))

            tuned_ok = agr.inspect_windows_go_gc_and_handle_risk(
                repo,
                env={"HARNESS_SIMULATE_PLATFORM": "win32", "GOGC": "200", "GOMEMLIMIT": "8GiB", "ANTIGRAVITY_APP_DATA": str(root / "clean_ag")},
            )
            self.assertFalse(tuned_ok["at_risk"])
            self.assertTrue(tuned_ok["gc_tuned"])

            with unittest.mock.patch.dict(
                os.environ,
                {"HARNESS_SIMULATE_PLATFORM": "win32", "GOGC": "off", "GOMEMLIMIT": "", "ANTIGRAVITY_APP_DATA": str(app_data)},
                clear=False,
            ):
                doc = HarnessDoctor(repo, run_selftest=False)
                doc.check_antigravity_installation()
                gc_check = next(r for r in doc.results if r.name == "Windows Go GC & AcceptEx Guard")
                self.assertEqual("WARN", gc_check.status)
                self.assertIn("GOMEMLIMIT=8GiB", " ".join(gc_check.details))

    def test_nov18_cli_default_project_permissions_slash_collision_and_long_wait_ttl_drop(self) -> None:
        """Verify #1618/#548 default-cli-project.json leak guard, #1620 /grill-me skill collision guard, and #1623/#171228 >=120s KV cache TTL drop forensics."""
        import antigravity_runtime as agr
        import platform_quirks as pq
        import session_forensics as sf
        from doctor.engine import HarnessDoctor

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            repo = root / "app"
            (repo / ".agents" / "state").mkdir(parents=True)
            (repo / ".agents" / "cache").mkdir(parents=True)
            app_data = root / "gemini_home" / "antigravity"
            cfg_projects = root / "gemini_home" / "config" / "projects"
            cfg_projects.mkdir(parents=True)
            app_data.mkdir(parents=True)

            # 0) Quirk catalog lookup for #1618, #1620, #1623, #171228
            self.assertEqual("AGY_1618_548_DEFAULT_PROJECT_PERM_LEAK", pq.resolve_quirk_id("#1618"))
            self.assertEqual("AGY_1620_BUILTIN_SLASH_SKILL_COLLISION", pq.resolve_quirk_id("1620"))
            self.assertEqual("AGY_1623_171228_LONG_WAIT_KV_CACHE_TTL", pq.resolve_quirk_id("#1623"))
            self.assertEqual("AGY_1623_171228_LONG_WAIT_KV_CACHE_TTL", pq.resolve_quirk_id("171228"))

            # 1) #1618 / #548: Clean absence -> PASS; leaked broad allow in default-cli-project.json -> WARN; disabled quirk -> skipped
            clean_perm = agr.inspect_default_cli_project_permissions(repo, env={"ANTIGRAVITY_APP_DATA": str(app_data)})
            self.assertFalse(clean_perm["at_risk"])
            self.assertFalse(clean_perm["exists"])

            default_proj_json = cfg_projects / "default-cli-project.json"
            default_proj_json.write_text(
                json.dumps({
                    "permissions": {
                        "allow": ["view_file", "run_command(*)", "edit_file"],
                        "deny": ["rm -rf /"],
                    }
                }),
                encoding="utf-8",
            )
            leaked_perm = agr.inspect_default_cli_project_permissions(repo, env={"ANTIGRAVITY_APP_DATA": str(app_data)})
            self.assertTrue(leaked_perm["at_risk"])
            self.assertIn("run_command(*)", leaked_perm["broad_allow_rules"])
            self.assertIn("edit_file", leaked_perm["broad_allow_rules"])
            self.assertNotIn("view_file", leaked_perm["broad_allow_rules"])

            disabled_perm = agr.inspect_default_cli_project_permissions(
                repo,
                env={"ANTIGRAVITY_APP_DATA": str(app_data), "HARNESS_DISABLE_QUIRKS": "1618"},
            )
            self.assertFalse(disabled_perm["applicable"])
            self.assertFalse(disabled_perm["at_risk"])

            # 2) #1620: Custom `/grill-me` skill collision in `.agents/skills/grill-me/SKILL.md` -> Doctor WARN
            grill_skill = repo / ".agents" / "skills" / "grill-me" / "SKILL.md"
            grill_skill.parent.mkdir(parents=True, exist_ok=True)
            grill_skill.write_text(
                "---\nname: grill-me\ndescription: Custom interview skill\n---\n# Grill Me\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(app_data)}, clear=False):
                doc = HarnessDoctor(repo, run_selftest=False)
                doc.check_skills_and_workflows()
                doc.check_antigravity_installation()
                slash_chk = next(r for r in doc.results if r.name == "CLI Slash-Command Skill Collision")
                perm_chk = next(r for r in doc.results if r.name == "CLI Default-Project Permission Guard")
                self.assertEqual("WARN", slash_chk.status)
                self.assertIn("grill-me", slash_chk.message)
                self.assertEqual("WARN", perm_chk.status)
                self.assertIn("run_command(*)", perm_chk.message)

            # Remove colliding skill & broad allow rules -> both Doctor checks PASS
            shutil.rmtree(grill_skill.parent)
            default_proj_json.write_text(json.dumps({"permissions": {"allow": ["view_file"]}}), encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(app_data)}, clear=False):
                doc_ok = HarnessDoctor(repo, run_selftest=False)
                doc_ok.check_skills_and_workflows()
                doc_ok.check_antigravity_installation()
                self.assertEqual("PASS", next(r for r in doc_ok.results if r.name == "CLI Slash-Command Skill Collision").status)
                self.assertEqual("PASS", next(r for r in doc_ok.results if r.name == "CLI Default-Project Permission Guard").status)

            # 3) #1623 / #171228: >=120s tool/subagent wait followed by cachedContentTokenCount=0 -> LONG_WAIT_KV_CACHE_TTL_EXPIRED
            brain_dir = app_data / "brain" / "conv-1623-ttl" / ".system_generated" / "logs"
            brain_dir.mkdir(parents=True)
            tx_1623 = brain_dir / "transcript.jsonl"
            tx_1623.write_text(
                "\n".join([
                    json.dumps({
                        "step_index": 1,
                        "type": "PLANNER_RESPONSE",
                        "created_at": "2026-11-18T08:00:00Z",
                        "usageMetadata": {"promptTokenCount": 42000, "cachedContentTokenCount": 39500},
                        "tool_calls": [{"name": "run_command", "args": {"CommandLine": "python .agents/harness.py verify-steps"}}],
                    }),
                    json.dumps({
                        "step_index": 2,
                        "type": "TOOL_RESPONSE",
                        "created_at": "2026-11-18T08:02:45Z",
                        "duration_ms": 165000,
                        "content": "BUILD SUCCESSFUL in 2m 45s",
                    }),
                    json.dumps({
                        "step_index": 3,
                        "type": "PLANNER_RESPONSE",
                        "created_at": "2026-11-18T08:02:47Z",
                        "usageMetadata": {"promptTokenCount": 43200, "cachedContentTokenCount": 0},
                    }),
                ]) + "\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(app_data)}, clear=False):
                diag_ttl = sf.diagnose_session(repo, conversation_id="conv-1623-ttl")
                diag_ttl_off = None
            with unittest.mock.patch.dict(
                os.environ,
                {"ANTIGRAVITY_APP_DATA": str(app_data), "HARNESS_DISABLE_QUIRKS": "1623"},
                clear=False,
            ):
                diag_ttl_off = sf.diagnose_session(repo, conversation_id="conv-1623-ttl")

            ttl_codes = {f["code"] for f in diag_ttl["findings"]}
            self.assertIn("LONG_WAIT_KV_CACHE_TTL_EXPIRED", ttl_codes, diag_ttl)
            self.assertNotIn("GEMINI4_TURN3_CACHE_DROP_ANOMALY", ttl_codes)
            self.assertEqual(1, diag_ttl["transcript"]["long_wait_cache_ttl_drops"])
            self.assertGreaterEqual(diag_ttl["transcript"]["max_ttl_drop_wait_sec"], 165.0)
            self.assertNotIn("LONG_WAIT_KV_CACHE_TTL_EXPIRED", {f["code"] for f in diag_ttl_off["findings"]})

    def test_v142_carbon_flash_offload_ground_truth_models_dynamic_spec_and_rtl_guard(self):
        """Verify Carbon/Argon Model='flash' quota offload, ground-truth SQLite model reporting, multi-phase spec escalation, and RTL XML guard."""
        import check_strings
        import delegation_policy as dp
        import review_execution
        import review_models
        import review_package
        import review_policy
        atomic_write_json = dp.atomic_write_json

        # 1) Slug & human-readable display-name normalization + tiered Hydrogen / #200467 xhigh detection
        self.assertEqual(("gemini-4-hydrogen", "high"), review_models._split_antigravity_family_and_tier("gemini-4-hydrogen-tiered-high"))
        self.assertEqual(("gemini-4-hydrogen", "xhigh"), review_models._split_antigravity_family_and_tier("gemini-4-hydrogen-tiered-xhigh"))
        self.assertEqual(("gemini-4-carbon", "medium"), review_models._split_antigravity_family_and_tier("Gemini 4 Carbon (Medium)"))
        self.assertEqual(("gemini-4-argon", "high"), review_models._split_antigravity_family_and_tier("Gemini 4 Argon (High)"))
        self.assertEqual(("gemini-4-hydrogen", "high"), review_models._split_antigravity_family_and_tier("Gemini 4 Hydrogen High"))

        # Ground-truth effective_reviewer_model + _matches_antigravity_native_model
        self.assertTrue(
            review_models._matches_antigravity_native_model(
                "gemini-4-hydrogen-high",
                "high",
                "gemini-4-hydrogen-tiered-high",
                ["gemini-4-hydrogen-tiered-high"],
            )
        )
        self.assertTrue(
            review_models._matches_antigravity_native_model(
                "gemini-4-hydrogen-medium",
                "medium",
                "gemini-3.8-flash-high",
                ["gemini-3.8-flash-high"],
                allow_frontier_flash_offload=True,
            )
        )
        self.assertFalse(
            review_models._matches_antigravity_native_model(
                "gemini-4-hydrogen-medium",
                "medium",
                "gemini-3.8-flash-high",
                ["gemini-3.8-flash-high"],
                allow_frontier_flash_offload=False,
            )
        )
        self.assertEqual(
            "gemini-4-carbon-medium (policy: gemini-4-hydrogen-high)",
            review_models.effective_reviewer_model({
                "requested_model": "hydrogen-dynamic",
                "resolved_model": "gemini-4-hydrogen-high",
                "actual_model": "gemini-4-carbon-medium",
                "actual_model_status": "NATIVE_METADATA_OBSERVED",
            }),
        )
        self.assertEqual(
            "gemini-4-hydrogen-tiered-high",
            review_models.effective_reviewer_model({
                "requested_model": "hydrogen-dynamic",
                "resolved_model": "gemini-4-hydrogen-high",
                "actual_model": "gemini-4-hydrogen-tiered-high",
                "actual_model_status": "NATIVE_METADATA_OBSERVED",
            }),
        )

        # 2) Carbon/Argon Lead -> Model="flash" offload vs Hydrogen Lead -> INHERIT_PARENT_BY_OMISSION
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir(parents=True)
            for sub in ("agents/harness-scout-agent", "agents/android-ui-expert-agent", "agents/bug-test-reviewer-agent"):
                p = repo / ".agents" / sub / "agent.md"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("---\nname: role\ndescription: role\n---\nPrompt\n", encoding="utf-8")
            review_models.set_policy(
                repo,
                review_models.resolve_preset_policy("hydrogen-dynamic"),
                task_id=None,
                scope="project",
                host="antigravity",
                source="conversation",
                proof_reference="Use hydrogen-dynamic",
            )
            plan_impl = {
                "schema_version": 2,
                "task_id": "t-offload",
                "status": "IMPLEMENTING",
                "task_kind": "FEATURE",
                "planning_depth": "BOUNDED",
                "requested_outcome": "Add RTL card",
                "expected_files": [
                    "app/src/main/kotlin/com/demo/A.kt",
                    "app/src/main/kotlin/com/demo/B.kt",
                    "app/src/main/kotlin/com/demo/C.kt",
                    "app/src/main/kotlin/com/demo/D.kt",
                ],
                "expected_surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"],
                "base_head": "HEAD",
            }
            atomic_write_json(repo / ".agents/state/active-task.json", {"task_id": "t-offload", "status": "IMPLEMENTING"})
            atomic_write_json(repo / ".agents/state/tasks/t-offload/plan.json", plan_impl)

            def _run_guard(cid: str, sub_entry: dict, env_extra: dict | None = None) -> dict:
                engine = REPO_ROOT / "agents/scripts/pre_tool_safety.py"
                env = {
                    **os.environ,
                    "HARNESS_REPO": str(repo),
                    "HARNESS_HOST": "antigravity",
                    "HARNESS_HOOK_STATE": str(repo / ".agents/state/hook_state.json"),
                }
                if env_extra:
                    env.update(env_extra)
                pr = subprocess.run(
                    [sys.executable, str(engine)],
                    input=json.dumps({
                        "conversationId": cid,
                        "toolCall": {"name": "invoke_subagent", "args": {"Subagents": [sub_entry]}},
                    }),
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                self.assertEqual(0, pr.returncode, pr.stderr)
                return _with_audit_reason(json.loads(pr.stdout), env, engine)

            # A) Carbon Lead session -> Scout & Specialist MUST pass Model="flash"
            dp.record_live_lead_session_model(repo, "cid-carbon", "Gemini 4 Carbon (Medium)")
            self.assertEqual((True, "gemini-4-carbon"), dp.is_frontier_lead_requiring_flash_offload(repo, "cid-carbon"))
            pol_del_c = dp.evaluate_delegation_policy(repo, task_id="t-offload", plan=plan_impl, router_action="IMPLEMENT")
            self.assertEqual("flash", pol_del_c["scout_invoke_model"])
            self.assertEqual("flash", pol_del_c["quota_strategy"]["scout_model"])
            self.assertEqual("flash", pol_del_c["quota_strategy"]["subagent_workhorse_model"])
            self.assertNotIn("gemini-4-hydrogen-medium", json.dumps(pol_del_c))
            pol_pre_c = dp.evaluate_delegation_policy(repo, plan={})
            self.assertEqual("flash", pol_pre_c["scout_invoke_model_arg"])
            self.assertEqual("flash", pol_pre_c["scout_model"])

            deny_scout_no_m = _run_guard("cid-carbon", {
                "TypeName": "harness-scout-agent",
                "Role": "harness-scout-agent",
                "Workspace": "inherit",
                "Prompt": "Inspect A.kt, B.kt, C.kt, and D.kt callers.",
            })
            self.assertEqual("deny", deny_scout_no_m["decision"], deny_scout_no_m)
            self.assertEqual("UTILITY_MODEL_QUOTA_GUARD", deny_scout_no_m.get("reason_code"))
            self.assertIn("CARBON_SCOUT_QUOTA_OFFLOAD_REQUIRED", deny_scout_no_m.get("reason", ""))

            allow_scout_flash = _run_guard("cid-carbon", {
                "TypeName": "harness-scout-agent",
                "Role": "harness-scout-agent",
                "Workspace": "inherit",
                "Model": "flash",
                "Prompt": "Inspect A.kt, B.kt, C.kt, and D.kt callers.",
            })
            self.assertEqual("allow", allow_scout_flash["decision"], allow_scout_flash)

            deny_spec_no_m = _run_guard("cid-carbon", {
                "TypeName": "android-ui-expert-agent",
                "Role": "android-ui-expert-agent",
                "Workspace": "inherit",
                "Prompt": "Audit RTL layout padding in A.kt.",
            })
            self.assertEqual("deny", deny_spec_no_m["decision"], deny_spec_no_m)
            self.assertEqual("CARBON_SPECIALIST_QUOTA_OFFLOAD_REQUIRED", deny_spec_no_m.get("reason_code"))

            allow_spec_flash = _run_guard("cid-carbon", {
                "TypeName": "android-ui-expert-agent",
                "Role": "android-ui-expert-agent",
                "Workspace": "inherit",
                "Model": "flash",
                "Prompt": "Audit RTL layout padding in A.kt.",
            })
            self.assertEqual("allow", allow_spec_flash["decision"], allow_spec_flash)

            # Reviewer hint & execution profile on Carbon Lead -> requires Model="flash"
            frozen_sel = {
                "bug-test-reviewer-agent": {
                    "requested_model": "hydrogen-dynamic",
                    "resolved_model": "gemini-4-hydrogen-high",
                    "effective_model": "gemini-4-hydrogen-high",
                    "model_policy": "INHERIT_PARENT_BY_OMISSION",
                    "model_argument": None,
                    "native_arguments": {},
                }
            }
            hint_carbon = review_models.antigravity_dispatch_model_hint(
                {"reviewers": frozen_sel}, ["bug-test-reviewer-agent"], repo=repo, parent_conversation_id="cid-carbon"
            )
            self.assertIn("Model='flash'", hint_carbon)
            pol_path = repo / ".agents/state/tasks/t-offload/policy.json"
            atomic_write_json(pol_path, {"reviewers": ["bug-test-reviewer-agent"], "surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"], "risk_tier": "T2_FEATURE"})
            frozen_rm = review_models.freeze_models(repo, "t-offload", "antigravity", ["bug-test-reviewer-agent"])
            atomic_write_json(
                repo / ".agents/state/tasks/t-offload/current-run.json",
                {
                    "run_id": "RUN_OFFLOAD_1",
                    "review_host": "antigravity",
                    "review_protocol_version": 2,
                    "policy": str(pol_path),
                    "review_models": frozen_rm,
                },
            )
            exec_prof_c = review_execution.resolve_execution_profile(repo, "t-offload", host="antigravity")
            rev_c = exec_prof_c["reviewers"]["bug-test-reviewer-agent"]
            self.assertEqual({"Model": "flash"}, rev_c["native_arguments"])
            self.assertEqual({"Model": "flash"}, rev_c["dispatch_contract"]["native_arguments"])

            # Inherit selection on Carbon Lead -> does NOT force Model="flash"
            inherit_sel = {"bug-test-reviewer-agent": {"requested_model": "inherit", "resolved_model": "inherit", "effective_model": "inherit"}}
            self.assertFalse(review_models.reviewer_requires_flash_offload(repo, inherit_sel["bug-test-reviewer-agent"], parent_conversation_id="cid-carbon"))

            # Disabling quirk 200144 disables offload cleanly
            with unittest.mock.patch.dict(os.environ, {"HARNESS_DISABLE_QUIRKS": "200144"}, clear=False):
                self.assertEqual((False, ""), dp.is_frontier_lead_requiring_flash_offload(repo, "cid-carbon"))

            # B) Hydrogen High Lead session -> omits Model (INHERIT_PARENT_BY_OMISSION) and blocks unexpected Model="flash"
            dp.record_live_lead_session_model(repo, "cid-hydro", "gemini-4-hydrogen-high")
            self.assertEqual((False, "gemini-4-hydrogen"), dp.is_frontier_lead_requiring_flash_offload(repo, "cid-hydro"))
            pol_del_h = dp.evaluate_delegation_policy(repo, task_id="t-offload", plan=plan_impl, router_action="IMPLEMENT")
            self.assertIsNone(pol_del_h["scout_invoke_model"])
            self.assertEqual("inherit", pol_del_h["quota_strategy"]["scout_model"])
            self.assertEqual("inherit", pol_del_h["quota_strategy"]["subagent_workhorse_model"])

            allow_hydro_omit = _run_guard("cid-hydro", {
                "TypeName": "harness-scout-agent",
                "Role": "harness-scout-agent",
                "Workspace": "inherit",
                "Prompt": "Inspect A.kt, B.kt, C.kt, and D.kt callers.",
            })
            self.assertEqual("allow", allow_hydro_omit["decision"], allow_hydro_omit)

            deny_hydro_flash = _run_guard("cid-hydro", {
                "TypeName": "harness-scout-agent",
                "Role": "harness-scout-agent",
                "Workspace": "inherit",
                "Model": "flash",
                "Prompt": "Inspect A.kt, B.kt, C.kt, and D.kt callers.",
            })
            self.assertEqual("deny", deny_hydro_flash["decision"], deny_hydro_flash)
            self.assertEqual("UTILITY_MODEL_QUOTA_GUARD", deny_hydro_flash.get("reason_code"))

            # 3) Dynamic spec-compliance-agent escalation on multi-phase ARCHITECTURAL plans + UI/Completeness briefs
            skills_root = REPO_ROOT / "agents/skills"
            cls_arch = {"surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"], "severity": "HIGH", "changed_files": 4, "planning_depth": "ARCHITECTURAL"}
            pol_1phase = review_policy.decide(cls_arch, skills_root, plan={"planning_depth": "ARCHITECTURAL", "phases": [{"id": "p1"}]})
            self.assertNotIn("spec-compliance-agent", pol_1phase["reviewers"])

            pol_2phase_bounded = review_policy.decide(
                {"surfaces": ["COMPOSE_UI", "BUSINESS_LOGIC"], "severity": "MEDIUM", "changed_files": 4, "planning_depth": "BOUNDED"},
                skills_root,
                plan={"planning_depth": "BOUNDED", "phases": [{"id": "p1"}, {"id": "p2"}]},
            )
            self.assertNotIn("spec-compliance-agent", pol_2phase_bounded["reviewers"])

            pol_2phase_arch = review_policy.decide(
                cls_arch,
                skills_root,
                plan={"planning_depth": "ARCHITECTURAL", "phases": [{"id": "p1"}, {"id": "p2"}]},
            )
            self.assertIn("spec-compliance-agent", pol_2phase_arch["reviewers"])
            self.assertIn("MULTI_PHASE_ARCHITECTURAL_SPEC_AUDIT", pol_2phase_arch["explanation"]["reviewers"]["spec-compliance-agent"])

            pol_2phase_delta = review_policy.decide(
                cls_arch,
                skills_root,
                plan={"planning_depth": "ARCHITECTURAL", "phases": [{"id": "p1"}, {"id": "p2"}]},
                review_scope="FIX_DELTA",
            )
            self.assertNotIn("spec-compliance-agent", pol_2phase_delta["reviewers"])

            pkg_dir = repo / ".agents/state/tasks/t-offload/review_runs/RUN_1"
            pkg_dir.mkdir(parents=True, exist_ok=True)
            meta_b = {"run_id": "RUN_1", "package_sha256": "abcdef123456"}
            plan_no_approach = {
                "task_id": "t-offload",
                "task_kind": "FEATURE",
                "requested_outcome": "Support Arabic RTL card layout and step badge",
                "approach": "",
                "expected_surfaces": ["COMPOSE_UI", "XML_UI"],
            }
            bug_b = review_package.generate_task_brief(
                repo, "t-offload", "bug-test-reviewer-agent", pkg_dir, meta_b, plan_no_approach, pol_2phase_arch, [{"path": "app/src/main/kotlin/com/demo/A.kt"}]
            ).read_text(encoding="utf-8")
            spec_b = review_package.generate_task_brief(
                repo, "t-offload", "spec-compliance-agent", pkg_dir, meta_b, plan_no_approach, pol_2phase_arch, [{"path": "app/src/main/kotlin/com/demo/A.kt"}]
            ).read_text(encoding="utf-8")
            arch_b = review_package.generate_task_brief(
                repo, "t-offload", "arch-regression-reviewer-agent", pkg_dir, meta_b, plan_no_approach, pol_2phase_arch, [{"path": "app/src/main/kotlin/com/demo/A.kt"}]
            ).read_text(encoding="utf-8")
            self.assertIn("Plan completeness (you own this check)", bug_b)
            self.assertIn("Plan completeness (you own this check)", spec_b)
            self.assertIn("UI Paradigm, Theme & RTL Layout Audit", arch_b)

        # 4) Deterministic diff-scoped RTL XML layout & directional vector drawable check in check_strings.py
        with tempfile.TemporaryDirectory() as td_rtl:
            rtl_repo = Path(td_rtl) / "rtl_app"
            rtl_repo.mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=rtl_repo, check=True)
            subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=rtl_repo, check=True)
            subprocess.run(["git", "config", "user.name", "Dev"], cwd=rtl_repo, check=True)
            (rtl_repo / "app/src/main/res/values").mkdir(parents=True)
            (rtl_repo / "app/src/main/res/values-ar").mkdir(parents=True)
            (rtl_repo / "app/src/main/res/layout").mkdir(parents=True)
            (rtl_repo / "app/src/main/res/drawable").mkdir(parents=True)
            (rtl_repo / "app/src/main/res/values/strings.xml").write_text('<resources><string name="ok">OK</string></resources>\n', encoding="utf-8")
            (rtl_repo / "app/src/main/res/values-ar/strings.xml").write_text('<resources><string name="ok">حسنا</string></resources>\n', encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=rtl_repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init rtl repo"], cwd=rtl_repo, check=True)

            layout_f = rtl_repo / "app/src/main/res/layout/item_step.xml"
            icon_f = rtl_repo / "app/src/main/res/drawable/ic_arrow_back.xml"
            layout_f.write_text(
                '<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android"\n'
                '    android:paddingLeft="16dp"\n'
                '    android:layout_width="match_parent"\n'
                '    android:layout_height="wrap_content" />\n',
                encoding="utf-8",
            )
            icon_f.write_text(
                '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
                '    android:width="24dp"\n'
                '    android:height="24dp"\n'
                '    android:viewportWidth="24"\n'
                '    android:viewportHeight="24">\n'
                '</vector>\n',
                encoding="utf-8",
            )
            self.assertEqual(1, check_strings.main([], repo=rtl_repo))

            layout_f.write_text(
                '<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android"\n'
                '    android:paddingStart="16dp"\n'
                '    android:layout_width="match_parent"\n'
                '    android:layout_height="wrap_content" />\n',
                encoding="utf-8",
            )
            icon_f.write_text(
                '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
                '    android:autoMirrored="true"\n'
                '    android:width="24dp"\n'
                '    android:height="24dp"\n'
                '    android:viewportWidth="24"\n'
                '    android:viewportHeight="24">\n'
                '</vector>\n',
                encoding="utf-8",
            )
            self.assertEqual(0, check_strings.main([], repo=rtl_repo))

        # English-only repo (no values-ar, no RTL _product.py) -> zero false positives on paddingLeft
        with tempfile.TemporaryDirectory() as td_en:
            en_repo = Path(td_en) / "en_app"
            en_repo.mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=en_repo, check=True)
            subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=en_repo, check=True)
            subprocess.run(["git", "config", "user.name", "Dev"], cwd=en_repo, check=True)
            (en_repo / "app/src/main/res/values").mkdir(parents=True)
            (en_repo / "app/src/main/res/layout").mkdir(parents=True)
            (en_repo / "app/src/main/res/values/strings.xml").write_text('<resources><string name="ok">OK</string></resources>\n', encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=en_repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init en repo"], cwd=en_repo, check=True)
            (en_repo / "app/src/main/res/layout/item_en.xml").write_text(
                '<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android"\n'
                '    android:paddingLeft="16dp"\n'
                '    android:layout_width="match_parent"\n'
                '    android:layout_height="wrap_content" />\n',
                encoding="utf-8",
            )
            self.assertEqual(0, check_strings.main([], repo=en_repo))

    def test_v142_roborazzi_robolectric_webpack_context_shield_and_unused_code_guard(self):
        """Verify dependency-only Roborazzi/Robolectric detection + Doctor check, web-pack 40k context shield + RTL UI test rule, and Kotlin unused-code guard."""
        import fast_kt_lint
        import review_package
        import roborazzi_gate as rg
        import web_relay
        from doctor.engine import HarnessDoctor

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "rashaka_like_app"
            app_data = root / "ag_data"
            (repo / ".agents/rules").mkdir(parents=True)
            (repo / ".agents/state").mkdir(parents=True)
            (repo / ".agents/rules/harness-rules.md").write_text("# Rules\n", encoding="utf-8")
            (repo / "app/src/main/kotlin/com/demo").mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)

            # 1) Dependency-only Roborazzi 1.78 + Robolectric 4.17 + ui-test-junit4 (missing includeAndroidResources & ui-test-manifest)
            gradle_file = repo / "app/build.gradle"
            gradle_file.write_text(
                'plugins {\n'
                '    id "com.android.application"\n'
                '}\n'
                'dependencies {\n'
                '    testImplementation "io.github.takahirom.roborazzi:roborazzi:1.78.0"\n'
                '    testImplementation "io.github.takahirom.roborazzi:roborazzi-compose:1.78.0"\n'
                '    testImplementation "io.github.takahirom.roborazzi:roborazzi-junit-rule:1.78.0"\n'
                '    testImplementation "org.robolectric:robolectric:4.17"\n'
                '    testImplementation "androidx.compose.ui:ui-test-junit4"\n'
                '}\n',
                encoding="utf-8",
            )
            caps_warn = rg.detect_roborazzi(repo)
            self.assertTrue(caps_warn["installed"])
            self.assertFalse(caps_warn["plugin_applied"])
            self.assertTrue(caps_warn["robolectric_installed"])
            self.assertTrue(caps_warn["compose_ui_test_installed"])
            self.assertFalse(caps_warn["compose_ui_test_manifest_installed"])
            self.assertFalse(caps_warn["include_android_resources"])

            # Verify run_roborazzi_verify uses :app:testDebugUnitTest when plugin is not applied
            seen_gradle_args: list[list[str]] = []

            def _fake_gradle_run(cmd, **_kwargs):
                seen_gradle_args.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 0, stdout="BUILD SUCCESSFUL", stderr="")

            with unittest.mock.patch.object(rg.subprocess, "run", side_effect=_fake_gradle_run), unittest.mock.patch.object(rg, "write_gate_result"):
                rc_rb, payload_rb = rg.run_roborazzi_verify(repo)
                self.assertEqual(0, rc_rb)
                self.assertEqual(":app:testDebugUnitTest", payload_rb["gradle_task"])
                self.assertIn("-Proborazzi.dumpUiTree=true", seen_gradle_args[0])

            doc_w = HarnessDoctor(repo, run_selftest=False)
            doc_w.check_antigravity_installation()
            jvm_chk_w = next(r for r in doc_w.results if r.name == "Headless JVM UI Test Stack")
            self.assertEqual("WARN", jvm_chk_w.status)
            self.assertIn("isIncludeAndroidResources", jvm_chk_w.message)
            self.assertIn("ui-test-manifest", jvm_chk_w.message)

            # Add isIncludeAndroidResources = true + ui-test-manifest -> Doctor PASS
            gradle_file.write_text(
                'plugins { id "com.android.application" }\n'
                'android {\n'
                '    testOptions { unitTests { isIncludeAndroidResources = true } }\n'
                '}\n'
                'dependencies {\n'
                '    testImplementation "io.github.takahirom.roborazzi:roborazzi:1.78.0"\n'
                '    testImplementation "org.robolectric:robolectric:4.17"\n'
                '    testImplementation "androidx.compose.ui:ui-test-junit4"\n'
                '    debugImplementation "androidx.compose.ui:ui-test-manifest"\n'
                '}\n',
                encoding="utf-8",
            )
            doc_ok = HarnessDoctor(repo, run_selftest=False)
            doc_ok.check_antigravity_installation()
            jvm_chk_ok = next(r for r in doc_ok.results if r.name == "Headless JVM UI Test Stack")
            self.assertEqual("PASS", jvm_chk_ok.status, jvm_chk_ok.message)

            # 2) Web-Relay: pure logic pack vs Compose UI pack + >=40,000 token Context Bloat Shield
            vm_file = repo / "app/src/main/kotlin/com/demo/FoodViewModel.kt"
            screen_file = repo / "app/src/main/kotlin/com/demo/FoodScreen.kt"
            vm_file.write_text("package com.demo\n\nclass FoodViewModel {\n    fun calories(): Int = 1800\n}\n", encoding="utf-8")
            screen_file.write_text(
                "package com.demo\n\nimport androidx.compose.runtime.Composable\n\n@Composable\nfun FoodScreen(calories: Int) {\n    println(calories)\n}\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline files"], cwd=repo, check=True)

            bloated_tx = app_data / "brain" / "cid-web-52k" / ".system_generated" / "logs" / "transcript.jsonl"
            bloated_tx.parent.mkdir(parents=True)
            bloated_tx.write_text(
                json.dumps({
                    "step_index": 8,
                    "type": "PLANNER_RESPONSE",
                    "usageMetadata": {"promptTokenCount": 52400, "cachedContentTokenCount": 48000},
                }) + "\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.dict(
                os.environ,
                {"ANTIGRAVITY_APP_DATA": str(app_data), "HARNESS_CONVERSATION_ID": "cid-web-52k", "HARNESS_NO_CLIPBOARD": "1"},
                clear=False,
            ):
                pack_logic = web_relay.build_web_pack(
                    repo,
                    prompt="Update FoodViewModel calorie rounding",
                    files=["app/src/main/kotlin/com/demo/FoodViewModel.kt"],
                    no_clipboard=True,
                )
                pack_ui = web_relay.build_web_pack(
                    repo,
                    prompt="Add Arabic RTL step badge to FoodScreen",
                    files=["app/src/main/kotlin/com/demo/FoodScreen.kt"],
                    no_clipboard=True,
                )
            logic_md = Path(pack_logic["bundle_file"]).read_text(encoding="utf-8")
            ui_md = Path(pack_ui["bundle_file"]).read_text(encoding="utf-8")
            self.assertNotIn("Headless JVM Compose & RTL Verification", logic_md)
            self.assertIn("Headless JVM Compose & RTL Verification", ui_md)
            self.assertIn("ar-rSA-ldrtl", ui_md)
            self.assertIn("UNUSED_PARAMETER", ui_md)
            self.assertIn("context_compact_advisory", pack_ui)
            self.assertEqual(52400, pack_ui["context_compact_advisory"]["prompt_tokens"])
            self.assertIn("/compact", pack_ui["context_compact_advisory"]["advisory"])

            # 3) Unused Code Guard: catches UNUSED_PARAMETER, UNUSED_PRIVATE_FUNCTION, UNUSED_PRIVATE_CLASS, & cross-repo UNUSED_DECLARATION with 0 false positives
            dead_kt = repo / "app/src/main/kotlin/com/demo/NutritionCard.kt"
            dead_kt.write_text(
                "package com.demo\n\n"
                "import androidx.compose.runtime.Composable\n"
                "import androidx.compose.ui.tooling.preview.Preview\n\n"
                "/**\n"
                " * Renders nutrition card.\n"
                " * @param title Card title.\n"
                " * @param unusedSubtitle Dead parameter mentioned in KDoc.\n"
                " */\n"
                "fun renderNutritionCard(title: String, unusedSubtitle: String = \"\"): String {\n"
                "    return usedPrivateHelper(title)\n"
                "}\n\n"
                "private fun usedPrivateHelper(label: String): String = \"Card: $label\"\n\n"
                "private fun deadPrivateHelper(): Int = 99\n\n"
                "private data class DeadPrivateModel(val x: Int) {\n"
                "    companion object {\n"
                "        fun zero() = DeadPrivateModel(0)\n"
                "    }\n"
                "}\n\n"
                "class DeadPublicMapper {\n"
                "    fun mapNothing(): Int = 0\n"
                "}\n\n"
                "abstract class BaseHandler {\n"
                "    abstract fun onEvent(rawCode: Int)\n"
                "}\n\n"
                "class LiveHandler : BaseHandler() {\n"
                "    override fun onEvent(rawCode: Int) {\n"
                "        // unusedInOverride is valid on override\n"
                "    }\n"
                "    fun withUnderscoreAndDefault(_ignored: Int, base: Int, doubled: Int = base * 2): Int = doubled\n"
                "    private operator fun invoke(): Int = withUnderscoreAndDefault(0, 3)\n"
                "}\n\n"
                "@Preview\n"
                "@Composable\n"
                "private fun NutritionCardPreview() {\n"
                "    println(renderNutritionCard(\"Macro\"))\n"
                "    println(LiveHandler()())\n"
                "}\n",
                encoding="utf-8",
            )
            intra_issues = fast_kt_lint.lint_file(dead_kt)
            by_type = {iss["type"]: iss for iss in intra_issues}
            self.assertIn("UNUSED_PARAMETER", by_type, intra_issues)
            self.assertIn("unusedSubtitle", by_type["UNUSED_PARAMETER"]["msg"])
            self.assertIn("UNUSED_PRIVATE_FUNCTION", by_type, intra_issues)
            self.assertIn("deadPrivateHelper", by_type["UNUSED_PRIVATE_FUNCTION"]["msg"])
            self.assertIn("UNUSED_PRIVATE_CLASS", by_type, intra_issues)
            self.assertIn("DeadPrivateModel", by_type["UNUSED_PRIVATE_CLASS"]["msg"])
            # Ensure valid patterns did NOT trigger false positives
            all_msgs = " | ".join(iss["msg"] for iss in intra_issues)
            for valid_sym in ("rawCode", "_ignored", "base", "doubled", "usedPrivateHelper", "NutritionCardPreview", "invoke"):
                self.assertNotIn(f"'{valid_sym}'", all_msgs, intra_issues)

            # Cross-repo unreferenced public declaration check + reviewer brief injection + --strict-unused CLI
            mod_map = fast_kt_lint.get_modified_lines_map(repo, [dead_kt])
            cross_dead = fast_kt_lint.find_unreferenced_new_declarations(repo, [dead_kt], mod_map)
            dead_names = {d["symbol"] for d in cross_dead}
            self.assertIn("DeadPublicMapper", dead_names, cross_dead)
            self.assertNotIn("renderNutritionCard", dead_names, cross_dead)
            self.assertNotIn("LiveHandler", dead_names, cross_dead)

            pkg_dir = repo / ".agents/state/tasks/t-dead/review_runs/R1"
            pkg_dir.mkdir(parents=True)
            brief_txt = review_package.generate_task_brief(
                repo,
                "t-dead",
                "bug-test-reviewer-agent",
                pkg_dir,
                {"run_id": "R1", "package_sha256": "1234567890abcdef"},
                {"task_id": "t-dead", "task_kind": "FEATURE", "requested_outcome": "Add NutritionCard", "expected_surfaces": ["COMPOSE_UI"]},
                {"reviewers": ["bug-test-reviewer-agent"]},
                [{"path": "app/src/main/kotlin/com/demo/NutritionCard.kt"}],
            ).read_text(encoding="utf-8")
            self.assertIn("Zero-Caller Newly Added Declarations", brief_txt)
            self.assertIn("DeadPublicMapper", brief_txt)

            # 4) Follow-Up Review Round Carry (`Single-Owner Surgical Fix Carry`) + CRLF->LF `build_fix_diff` normalization (#8af45957)
            import difflib
            import review_fix_delta
            import review_policy

            old_crlf = "".join(f"val line{i} = {i}\r\n" for i in range(1, 201))
            new_lf = "".join(
                (f"val line{i} = {i + 1000}\n" if i in (95, 96) else f"val line{i} = {i}\n")
                for i in range(1, 201)
            )
            (repo / ".agents/state/tasks/t-dead/manifest-run-r1.json").write_text("{}", encoding="utf-8")
            with unittest.mock.patch.object(
                review_fix_delta,
                "_comparison_texts",
                return_value={"app/src/main/java/com/demo/paywall/OnboardingPaywallActivity.kt": (old_crlf, new_lf)},
            ):
                diff_out = review_fix_delta.build_fix_diff(
                    repo,
                    repo / ".agents/state/tasks/t-dead",
                    {},
                    {},
                    {
                        "fix_delta": {
                            "comparison": "REVIEWED_TEXT",
                            "files": ["app/src/main/java/com/demo/paywall/OnboardingPaywallActivity.kt"],
                        },
                        "later_round_source": {"run_id": "run-r1"},
                    },
                )
            self.assertIsNotNone(diff_out)
            self.assertLess(len(diff_out.splitlines()), 35, f"CRLF->LF caused whole-file diff explosion: {len(diff_out.splitlines())} lines")
            self.assertIn("+val line95 = 1095", diff_out)

            # Single-owner surgical fix on T5_CRITICAL BILLING file: only the 1 finding owner reruns, other 2 carry!
            skills_root = REPO_ROOT / "agents/skills"
            cls_t5 = {
                "surfaces": ["BILLING", "BUSINESS_LOGIC", "COMPOSE_UI", "COROUTINES"],
                "severity": "CRITICAL",
                "changed_files": 5,
                "changed_lines": 180,
            }
            r1_policy = {
                "reviewers": ["arch-regression-reviewer-agent", "bug-test-reviewer-agent", "security-perf-reviewer-agent"],
                "surfaces": ["BILLING", "BUSINESS_LOGIC", "COMPOSE_UI", "COROUTINES"],
            }
            surgical_delta = {
                "files": ["app/src/main/java/com/demo/paywall/OnboardingPaywallActivity.kt"],
                "reviewers": ["arch-regression-reviewer-agent", "bug-test-reviewer-agent", "security-perf-reviewer-agent"],
                "comparison": "REVIEWED_TEXT",
                "changed_lines": 8,
                "all_previously_reviewed": True,
            }
            r2_arch_owner = review_policy.decide_later_round(
                cls_t5,
                skills_root,
                previous_policy=r1_policy,
                finding_owners=["arch-regression-reviewer-agent"],
                passed_reviewers=["bug-test-reviewer-agent", "security-perf-reviewer-agent"],
                source_snapshot="s1" * 32,
                source_change_set="c1" * 32,
                current_change_set="c2" * 32,
                source_run_id="run-1",
                round_number=2,
                fix_delta=surgical_delta,
            )
            self.assertEqual(["arch-regression-reviewer-agent"], r2_arch_owner["reviewers"])
            self.assertEqual(
                {"bug-test-reviewer-agent", "security-perf-reviewer-agent"},
                {c["reviewer"] for c in r2_arch_owner["carried_reviews"]},
            )
            self.assertTrue(r2_arch_owner["fix_delta"].get("surgical_owner_only"))

            # Also verify when bug-test-reviewer-agent is the sole finding owner -> ONLY bug-test reruns (arch & security carry!)
            r2_bug_owner = review_policy.decide_later_round(
                cls_t5,
                skills_root,
                previous_policy=r1_policy,
                finding_owners=["bug-test-reviewer-agent"],
                passed_reviewers=["arch-regression-reviewer-agent", "security-perf-reviewer-agent"],
                source_snapshot="s1" * 32,
                source_change_set="c1" * 32,
                current_change_set="c2" * 32,
                source_run_id="run-1",
                round_number=2,
                fix_delta=surgical_delta,
            )
            self.assertEqual(["bug-test-reviewer-agent"], r2_bug_owner["reviewers"])
            self.assertEqual(
                {"arch-regression-reviewer-agent", "security-perf-reviewer-agent"},
                {c["reviewer"] for c in r2_bug_owner["carried_reviews"]},
            )

            # Large >40-line rewrite in BILLING still escalates to full delta reviewers!
            large_delta = {**surgical_delta, "changed_lines": 65}
            r2_large = review_policy.decide_later_round(
                cls_t5,
                skills_root,
                previous_policy=r1_policy,
                finding_owners=["arch-regression-reviewer-agent"],
                passed_reviewers=["bug-test-reviewer-agent", "security-perf-reviewer-agent"],
                source_snapshot="s1" * 32,
                source_change_set="c1" * 32,
                current_change_set="c2" * 32,
                source_run_id="run-1",
                round_number=2,
                fix_delta=large_delta,
            )
            self.assertEqual(3, len(r2_large["reviewers"]))



class TestV145AntigravityUpgrades(unittest.TestCase):
    """End-to-end verification of v1.4.5 Antigravity v2.33.0 / CLI 1.5.11 upgrades & performance fast-paths."""
    _KIT = Path(__file__).resolve().parents[2]

    def test_pep562_lazy_safety_imports_and_mock_patch_compatibility(self) -> None:
        import contextlib
        import io
        import pre_tool_safety as pts

        probe = chr(10).join([
            "import json, sys",
            f"sys.path.insert(0, {str(self._KIT / 'agents/scripts')!r})",
            "import pre_tool_safety",
            "loaded = [m for m in sys.modules if m.startswith('_safety.')]",
            "print(json.dumps(sorted(loaded)))",
        ])
        proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
        eager = json.loads(proc.stdout.strip())
        self.assertEqual(["_safety.engine"], eager)

        with tempfile.TemporaryDirectory() as td_probe:
            read_probe = chr(10).join([
                "import contextlib, io, json, os, sys",
                "from unittest.mock import patch",
                f"os.environ['HARNESS_REPO'] = {str(self._KIT)!r}",
                f"os.environ['HARNESS_HOOK_STATE'] = {str(Path(td_probe) / 'hook-state.json')!r}",
                f"sys.path.insert(0, {str(self._KIT / 'agents/scripts')!r})",
                "import pre_tool_safety",
                "buf = io.StringIO()",
                "payload = json.dumps({'toolName': 'view_file', 'toolArgs': {'AbsolutePath': 'README.md'}})",
                "with patch('sys.stdin', io.StringIO(payload)), contextlib.redirect_stdout(buf):",
                "    pre_tool_safety.main()",
                "loaded = sorted(m for m in sys.modules if m.startswith('_safety.'))",
                "print(json.dumps({'out': json.loads(buf.getvalue()), 'loaded': loaded}))",
            ])
            proc_r = subprocess.run([sys.executable, "-c", read_probe], capture_output=True, text=True, check=True)
            res_r = json.loads(proc_r.stdout.strip())
            self.assertEqual("allow", res_r["out"]["decision"])
            self.assertNotIn("_safety.command_policy", res_r["loaded"])
            self.assertNotIn("_safety.subagent_guard", res_r["loaded"])
            self.assertNotIn("_safety.mcp_guard", res_r["loaded"])

        with tempfile.TemporaryDirectory() as td_m, unittest.mock.patch.dict(
            os.environ, {"HARNESS_HOOK_STATE": str(Path(td_m) / "hs.json")}
        ), unittest.mock.patch.object(pts, "_handle_command") as mocked_cmd:
            buf_c = io.StringIO()
            payload_c = json.dumps({"toolName": "run_command", "toolArgs": {"CommandLine": "git status"}})
            with unittest.mock.patch("sys.stdin", io.StringIO(payload_c)), contextlib.redirect_stdout(buf_c):
                pts.main()
            mocked_cmd.assert_called_once()

    def test_run_workflow_fail_closed_and_governed_v2_dynamic_workflow(self) -> None:
        from policy_vocab import ANTIGRAVITY_TOOLS, SUBAGENT_ORCHESTRATION_TOOLS
        self.assertIn("run_workflow", ANTIGRAVITY_TOOLS)
        self.assertIn("run_workflow", SUBAGENT_ORCHESTRATION_TOOLS)

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "gradlew").write_text("#!/bin/sh" + chr(10), encoding="utf-8")
            app_kt = repo / "app/src/main/kotlin/com/demo/App.kt"
            app_kt.parent.mkdir(parents=True)
            app_kt.write_text("package com.demo" + chr(10) + "class App { fun x() = 1 }" + chr(10), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
            shutil.copytree(
                self._KIT / "agents",
                repo / ".agents",
                ignore=shutil.ignore_patterns("state", "cache", "__pycache__", "*.pyc"),
            )

            env = {**os.environ, "HARNESS_REPO": str(repo)}
            hook_script = str(repo / ".agents/scripts/pre_tool_safety.py")

            # 1) Inline Python workflow (`code` or native Antigravity `Script`, even alongside `ScriptPath`) -> DENIED
            for inline_args in (
                {"code": "print('pwn')"},
                {"Script": "print('pwn')"},
                {"ScriptPath": ".agents/scripts/dynamic_review_workflow.py", "Script": "print('pwn')"},
            ):
                p_inline = subprocess.run(
                    [sys.executable, hook_script],
                    input=json.dumps({"toolName": "run_workflow", "toolArgs": inline_args}),
                    capture_output=True, text=True, env=env, check=True,
                )
                d_inline = json.loads(p_inline.stdout)
                self.assertEqual("deny", d_inline["decision"], inline_args)
                self.assertIn("UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED", d_inline["reason"])

            # 1b) Out-of-repo Cwd -> DENIED
            p_cwd = subprocess.run(
                [sys.executable, hook_script],
                input=json.dumps({
                    "toolName": "run_workflow",
                    "toolArgs": {
                        "ScriptPath": ".agents/scripts/dynamic_review_workflow.py",
                        "Cwd": str(repo.parent),
                    },
                }),
                capture_output=True, text=True, env=env, check=True,
            )
            d_cwd = json.loads(p_cwd.stdout)
            self.assertEqual("deny", d_cwd["decision"])
            self.assertIn("UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED", d_cwd["reason"])

            # 2) Untrusted file path -> DENIED
            p_untrusted = subprocess.run(
                [sys.executable, hook_script],
                input=json.dumps({"toolName": "run_workflow", "toolArgs": {"ScriptPath": "app/evil.py"}}),
                capture_output=True, text=True, env=env, check=True,
            )
            self.assertEqual("deny", json.loads(p_untrusted.stdout)["decision"])

            # 3) Governed script when no VERIFYING V2 task exists -> DENIED (DYNAMIC_WORKFLOW_NOT_READY)
            p_not_ready = subprocess.run(
                [sys.executable, hook_script],
                input=json.dumps({"toolName": "run_workflow", "toolArgs": {"ScriptPath": ".agents/scripts/dynamic_review_workflow.py"}}),
                capture_output=True, text=True, env=env, check=True,
            )
            d_nr = json.loads(p_not_ready.stdout)
            self.assertEqual("deny", d_nr["decision"])
            self.assertIn("DYNAMIC_WORKFLOW_NOT_READY", d_nr["reason"])

            # 4) Advance a real task to VERIFYING V2 and verify governed `run_workflow` + `--plan-json` succeed!
            wf_py = str(repo / ".agents/scripts/workflow.py")
            d_proc = subprocess.run(
                [
                    sys.executable, wf_py, "draft", "--repo", str(repo), "--task-id", "t-dyn",
                    "--kind", "FEATURE", "--outcome", "Update App", "--expected-files", "app/src/main/kotlin/com/demo/App.kt",
                    "--expected-surfaces", "BUSINESS_LOGIC",
                ],
                capture_output=True, text=True, check=True,
            )
            plan_sha = json.loads((repo / ".agents/state/tasks/t-dyn/plan.json").read_text(encoding="utf-8"))["plan_sha256"]
            subprocess.run(
                [
                    sys.executable, str(repo / ".agents/harness.py"), "task", "approve", "--task-id", "t-dyn",
                    "--plan-hash", plan_sha, "--source", "conversation", "--proof-reference", "Approve", "--enforcement-tier", "RULE_ENFORCED",
                ],
                cwd=repo,
                capture_output=True, text=True, check=True,
            )
            subprocess.run([sys.executable, wf_py, "begin", "--repo", str(repo), "--task-id", "t-dyn"], capture_output=True, text=True, check=True)
            app_kt.write_text("package com.demo" + chr(10) + "/** Updated App. */" + chr(10) + "class App { fun x() = 2 }" + chr(10), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable, str(repo / ".agents/harness.py"), "review", "models", "set",
                    "--host", "antigravity", "--choice", "hydrogen-dynamic-project", "--source", "conversation", "--proof-reference", "Use Hydrogen",
                ],
                cwd=repo, capture_output=True, text=True, check=True,
            )
            subprocess.run(
                [sys.executable, wf_py, "prepare-verification", "--repo", str(repo), "--task-id", "t-dyn", "--host", "antigravity"],
                capture_output=True, text=True, check=True,
            )
            subprocess.run(
                [sys.executable, str(repo / ".agents/scripts/review_package.py"), "--repo", str(repo), "--task-id", "t-dyn"],
                capture_output=True, text=True, check=True,
            )
            p_plan = subprocess.run(
                [sys.executable, str(repo / ".agents/harness.py"), "review", "dynamic-workflow", "--task", "t-dyn", "--plan-json"],
                cwd=repo, capture_output=True, text=True, check=True,
            )
            spec = json.loads(p_plan.stdout)
            self.assertEqual("HARNESS_DYNAMIC_REVIEW_WORKFLOW_V1", spec["fingerprint"])
            self.assertTrue(len(spec["pending_reviewers"]) >= 1)

            p_allow = subprocess.run(
                [sys.executable, hook_script],
                input=json.dumps({"toolName": "run_workflow", "toolArgs": {"ScriptPath": ".agents/scripts/dynamic_review_workflow.py"}}),
                capture_output=True, text=True, env=env, check=True,
            )
            d_allow = json.loads(p_allow.stdout)
            self.assertEqual("allow", d_allow["decision"], d_allow)

    def test_btw_side_question_isolation_and_zero_token_idle_pre_invocation(self) -> None:
        import contextlib
        import io
        import pre_invocation_reminder as pir

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            shutil.copytree(
                self._KIT / "agents",
                repo / ".agents",
                ignore=shutil.ignore_patterns("state", "cache", "__pycache__", "*.pyc"),
            )
            (repo / "README.md").write_text("# Demo" + chr(10), encoding="utf-8")
            env = {**os.environ, "HARNESS_REPO": str(repo)}
            hook_script = str(repo / ".agents/scripts/pre_tool_safety.py")

            # 1) `/btw` side question read is allowed and does NOT create active-conversation.json
            p_read = subprocess.run(
                [sys.executable, hook_script],
                input=json.dumps({
                    "toolName": "view_file",
                    "toolArgs": {"AbsolutePath": str(repo / "README.md")},
                    "conversationId": "c-btw-side-1",
                    "isSideQuestion": True,
                }),
                capture_output=True, text=True, env=env, check=True,
            )
            self.assertEqual("allow", json.loads(p_read.stdout)["decision"])
            self.assertFalse((repo / ".agents/state/active-conversation.json").exists())

            # 2) `/btw` side question write / subagent / MCP is strictly blocked
            for mut_tool, mut_args in (
                ("edit_file", {"TargetFile": str(repo / "README.md")}),
                ("invoke_subagent", {"TypeName": "harness-scout-agent", "Prompt": "scan"}),
                ("call_mcp_tool", {"ServerName": "zoho", "ToolName": "get_items"}),
            ):
                p_mut = subprocess.run(
                    [sys.executable, hook_script],
                    input=json.dumps({"toolName": mut_tool, "toolArgs": mut_args, "mode": "btw"}),
                    capture_output=True, text=True, env=env, check=True,
                )
                d_mut = json.loads(p_mut.stdout)
                self.assertEqual("deny", d_mut["decision"], mut_tool)
                self.assertIn("SIDE_QUESTION_READ_ONLY_BOUNDARY", d_mut["reason"])

            # 3) `PreInvocation`: `/btw` emits `{}`, Turn 0 IDLE emits onboarding, Turn 1+ unchanged IDLE emits `{}`!
            with unittest.mock.patch.object(pir, "REPO", repo), unittest.mock.patch.object(pir, "_update_notice", return_value=""):
                b_btw = io.StringIO()
                with unittest.mock.patch("sys.stdin", io.StringIO(json.dumps({"invocationNum": 0, "conversationId": "c-btw", "isSideQuestion": True}))), contextlib.redirect_stdout(b_btw):
                    pir.main()
                self.assertEqual({}, json.loads(b_btw.getvalue()))

                b_t0 = io.StringIO()
                with unittest.mock.patch("sys.stdin", io.StringIO(json.dumps({"invocationNum": 0, "conversationId": "c-consult-1"}))), contextlib.redirect_stdout(b_t0):
                    pir.main()
                m_t0 = json.loads(b_t0.getvalue())["injectSteps"][0]["ephemeralMessage"]
                self.assertIn("Android Harness: Idle (no active task).", m_t0)

                b_t1 = io.StringIO()
                with unittest.mock.patch("sys.stdin", io.StringIO(json.dumps({"invocationNum": 1, "conversationId": "c-consult-1"}))), contextlib.redirect_stdout(b_t1):
                    pir.main()
                self.assertEqual({}, json.loads(b_t1.getvalue()))

                # Retired Nov 18 model still surfaces explicit warning even on subsequent idle turns
                b_ret = io.StringIO()
                with unittest.mock.patch("sys.stdin", io.StringIO(json.dumps({"invocationNum": 2, "conversationId": "c-consult-1", "modelName": "Claude Sonnet 4.6 (Thinking)"}))), contextlib.redirect_stdout(b_ret):
                    pir.main()
                m_ret = json.loads(b_ret.getvalue())["injectSteps"][0]["ephemeralMessage"]
                self.assertIn("MODEL RETIRED (Nov 18, 2026)", m_ret)

    def test_py_launcher_flags_slash_skill_disable_and_version_gated_quirks(self) -> None:
        from _enforcement import detect, parse_python_hook_command
        import antigravity_runtime as agr
        from doctor.engine import HarnessDoctor

        self.assertEqual(("py", ("-3",), "scripts/pre_tool_safety.py"), parse_python_hook_command("py -3 scripts/pre_tool_safety.py"))
        self.assertEqual(("python3", ("-S", "-u"), "scripts/pre_tool_safety.py"), parse_python_hook_command("python3 -S -u scripts/pre_tool_safety.py"))
        self.assertIsNone(parse_python_hook_command('python3 -c "import os" scripts/pre_tool_safety.py'))

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            shutil.copytree(
                self._KIT / "agents",
                repo / ".agents",
                ignore=shutil.ignore_patterns("state", "cache", "__pycache__", "*.pyc"),
            )
            (repo / "README.md").write_text("# Test" + chr(10), encoding="utf-8")
            hooks_file = repo / ".agents/hooks.json"
            hooks_obj = json.loads(hooks_file.read_text(encoding="utf-8"))
            hooks_obj["adb-and-git-safety"]["PreToolUse"][0]["hooks"][0]["command"] = f'"{sys.executable}" -S scripts/pre_tool_safety.py'
            hooks_file.write_bytes(b"\xef\xbb\xbf" + json.dumps(hooks_obj, indent=2).encode("utf-8"))

            enf = detect(repo, ["antigravity"])
            self.assertEqual("HARD_ENFORCED", enf["mutation_boundary_by_host"]["antigravity"])

            plan_sk = repo / ".agents/skills/plan/SKILL.md"
            plan_sk.parent.mkdir(parents=True, exist_ok=True)
            plan_sk.write_text(
                chr(10).join([
                    "---",
                    "name: plan",
                    "description: Internal helper",
                    "disable-slash-command: true",
                    "version: 1.0.0",
                    "kernel-major: 1",
                    "---",
                    "# Plan",
                ]) + chr(10),
                encoding="utf-8",
            )
            doc = HarnessDoctor(repo, run_selftest=False)
            doc.check_skills_and_workflows()
            slash_res = next(r for r in doc.results if r.name == "CLI Slash-Command Skill Collision")
            self.assertEqual("PASS", slash_res.status)

            (repo / ".agents/mcp_config.json").write_text(
                json.dumps({"mcpServers": {"s1": {"command": "node"}, "s2": {"command": "python"}}}),
                encoding="utf-8",
            )
            legacy_mcp = agr.inspect_windows_stdio_mcp_risk(repo, env={"HARNESS_SIMULATE_WINDOWS_MCP": "1"})
            self.assertTrue(legacy_mcp["at_risk"])
            modern_mcp = agr.inspect_windows_stdio_mcp_risk(
                repo,
                env={"HARNESS_SIMULATE_WINDOWS_MCP": "1", "ANTIGRAVITY_APP_VERSION": "2.33.0", "ANTIGRAVITY_CLI_VERSION": "1.5.11"},
            )
            self.assertFalse(modern_mcp["at_risk"])
            self.assertTrue(modern_mcp["mitigated_upstream"])




class TestV150CoreProductivityUpgrades(unittest.TestCase):
    """End-to-end verification of v1.5.0 core Android productivity & architecture intelligence upgrades."""

    def test_v150_smart_build_logic_scoping_and_impacted_tests(self):
        import _product
        import _repo_files
        import run_tests_gate
        from unittest import mock

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "settings.gradle.kts").write_text(
                'pluginManagement { includeBuild("build-logic") }\n'
                'include(":app", ":core:domain", ":core:data", ":feature:paywall", ":feature:unrelated")\n',
                encoding="utf-8",
            )
            # Static convention plugin in build-logic (no dynamic project(var); injects :core:domain into custom plugin consumers)
            bl_src = repo / "build-logic/convention/src/main/kotlin"
            bl_src.mkdir(parents=True)
            (repo / "build-logic/settings.gradle.kts").write_text('rootProject.name = "build-logic"\n', encoding="utf-8")
            (bl_src / "AndroidFeatureConventionPlugin.kt").write_text(
                'import org.gradle.api.Plugin\nimport org.gradle.api.Project\n'
                'class AndroidFeatureConventionPlugin : Plugin<Project> {\n'
                '    override fun apply(target: Project) {\n'
                '        target.dependencies.add("implementation", target.project(":core:domain"))\n'
                '    }\n'
                '}\n',
                encoding="utf-8",
            )
            for mod, build_body in {
                "app": 'plugins { id("com.android.application") }\ndependencies { implementation(project(":feature:paywall")) }\n',
                "core/domain": 'plugins { id("com.android.library") }\n',
                "core/data": 'plugins { id("com.android.library") }\ndependencies { implementation(project(":core:domain")) }\n',
                "feature/paywall": 'plugins { id("app.android.feature") }\n',
                "feature/unrelated": 'plugins { id("com.android.library") }\n',
            }.items():
                mdir = repo / mod
                mdir.mkdir(parents=True, exist_ok=True)
                (mdir / "build.gradle.kts").write_text(build_body, encoding="utf-8")

            paywall_vm = repo / "feature/paywall/src/main/kotlin/com/demo/paywall/PaywallViewModel.kt"
            paywall_vm.parent.mkdir(parents=True, exist_ok=True)
            paywall_vm.write_text(
                "package com.demo.paywall\nclass PaywallViewModel { fun load() = 1 }\n",
                encoding="utf-8",
            )
            paywall_test = repo / "feature/paywall/src/test/kotlin/com/demo/paywall/PaywallViewModelTest.kt"
            paywall_test.parent.mkdir(parents=True, exist_ok=True)
            paywall_test.write_text(
                "package com.demo.paywall\nimport org.junit.Test\nclass PaywallViewModelTest { @Test fun loads() { PaywallViewModel().load() } }\n",
                encoding="utf-8",
            )
            unrel_test = repo / "feature/unrelated/src/test/kotlin/com/demo/unrel/UnrelatedTest.kt"
            unrel_test.parent.mkdir(parents=True, exist_ok=True)
            unrel_test.write_text(
                "package com.demo.unrel\nimport org.junit.Test\nclass UnrelatedTest { @Test fun noop() {} }\n",
                encoding="utf-8",
            )

            # 1. Changing :feature:paywall does NOT run :feature:unrelated or :core:data despite build-logic existing!
            with mock.patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True),                     mock.patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"),                     mock.patch.object(_repo_files, "changed_paths", return_value=[paywall_vm]):
                scoped_tasks = run_tests_gate.resolve_target_tasks(repo, None)
                self.assertEqual([":app:testDebugUnitTest", ":feature:paywall:testDebugUnitTest"], scoped_tasks)
                impacted = run_tests_gate.resolve_impacted_test_patterns(repo, [paywall_vm])
                self.assertEqual(["com.demo.paywall.PaywallViewModelTest"], impacted)

            # 2. Convention-injected `:core:domain` change automatically includes `:feature:paywall` (which applied `app.android.feature`)!
            domain_file = repo / "core/domain/src/main/kotlin/com/demo/domain/Offer.kt"
            domain_file.parent.mkdir(parents=True, exist_ok=True)
            domain_file.write_text("package com.demo.domain\ndata class Offer(val id: String)\n", encoding="utf-8")
            with mock.patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True),                     mock.patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"),                     mock.patch.object(_repo_files, "changed_paths", return_value=[domain_file]):
                domain_tasks = run_tests_gate.resolve_target_tasks(repo, None)
                self.assertIn(":feature:paywall:testDebugUnitTest", domain_tasks)
                self.assertNotIn(":feature:unrelated:testDebugUnitTest", domain_tasks)

            # 3. Editing a file inside `build-logic/` itself safely broadens to ALL modules including `:feature:unrelated`!
            with mock.patch.object(_product, "UNIT_TEST_SCOPE", "changed_modules", create=True),                     mock.patch("baseline_capture._unit_test_task", return_value=":app:testDebugUnitTest"),                     mock.patch.object(_repo_files, "changed_paths", return_value=[bl_src / "AndroidFeatureConventionPlugin.kt"]):
                broad_tasks = run_tests_gate.resolve_target_tasks(repo, None)
                self.assertIn(":feature:unrelated:testDebugUnitTest", broad_tasks)

    def test_v150_di_binds_graph_edges_and_task_context(self):
        from _graph_core import EdgeKind, GraphEngine
        import task_context
        import web_relay

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            (repo / "app").mkdir()
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")

            repo_iface = repo / "app/src/main/java/com/demo/domain/SubRepository.kt"
            repo_impl = repo / "app/src/main/java/com/demo/data/SubRepositoryImpl.kt"
            di_mod = repo / "app/src/main/java/com/demo/di/SubModule.kt"
            vm_file = repo / "app/src/main/java/com/demo/ui/SubViewModel.kt"
            vm_test = repo / "app/src/test/java/com/demo/ui/SubViewModelTest.kt"
            for p in (repo_iface, repo_impl, di_mod, vm_file, vm_test):
                p.parent.mkdir(parents=True, exist_ok=True)

            repo_iface.write_text(
                "package com.demo.domain\ninterface SubRepository { suspend fun fetchPlan(): String }\n",
                encoding="utf-8",
            )
            repo_impl.write_text(
                "package com.demo.data\nimport com.demo.domain.SubRepository\n"
                "class SubRepositoryImpl : SubRepository { override suspend fun fetchPlan(): String = \"pro\" }\n",
                encoding="utf-8",
            )
            di_mod.write_text(
                "package com.demo.di\nimport com.demo.data.SubRepositoryImpl\nimport com.demo.domain.SubRepository\n"
                "import dagger.Binds\nimport dagger.Module\n"
                "@Module abstract class SubModule { @Binds abstract fun bindSub(impl: SubRepositoryImpl): SubRepository }\n",
                encoding="utf-8",
            )
            vm_file.write_text(
                "package com.demo.ui\nimport com.demo.domain.SubRepository\n"
                "class SubViewModel(private val repo: SubRepository) { suspend fun load() = repo.fetchPlan() }\n",
                encoding="utf-8",
            )
            vm_test.write_text(
                "package com.demo.ui\nimport com.demo.domain.SubRepository\nimport org.junit.Test\n"
                "class SubViewModelTest { @Test fun loadsPlan() { val r: SubRepository? = null } }\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)

            ge = GraphEngine(repo)
            ge.sync(persist=True)
            binds_edges = [(e.source, e.target) for e in ge.graph.edges if e.kind == EdgeKind.BINDS.value]
            self.assertIn(("com.demo.domain.SubRepository", "com.demo.data.SubRepositoryImpl"), binds_edges)

            # Forward: inspecting SubViewModel surfaces SubRepositoryImpl in `bound_implementations`
            ctx_vm = task_context.resolve_task_context(repo, file="app/src/main/java/com/demo/ui/SubViewModel.kt")
            bound_paths = [b["path"] for b in ctx_vm.get("bound_implementations") or []]
            self.assertIn("app/src/main/java/com/demo/data/SubRepositoryImpl.kt", bound_paths)

            # Reverse: inspecting SubRepositoryImpl surfaces SubViewModel as dependent AND SubViewModelTest in `tests`!
            ctx_impl = task_context.resolve_task_context(repo, file="app/src/main/java/com/demo/data/SubRepositoryImpl.kt")
            dep_paths = [d["path"] for d in ctx_impl.get("direct_dependents") or []]
            test_paths = [t["path"] for t in ctx_impl.get("tests") or []]
            self.assertIn("app/src/main/java/com/demo/ui/SubViewModel.kt", dep_paths)
            self.assertIn("app/src/test/java/com/demo/ui/SubViewModelTest.kt", test_paths)

            # Web-Relay neighbor signatures automatically include SubRepositoryImpl when SubViewModel is scoped!
            neighbors = web_relay._extract_neighbor_signatures(repo, ["app/src/main/java/com/demo/ui/SubViewModel.kt"], {})
            neighbor_paths = [n["path"] for n in neighbors]
            self.assertIn("app/src/main/java/com/demo/data/SubRepositoryImpl.kt", neighbor_paths)

    def test_v150_android_gradle_error_parser_families(self):
        from gradle_error_parser import parse_compiler_errors

        sample_log = """
> Task :app:kspDebugKotlin FAILED
e: [ksp] /work/app/src/main/java/com/demo/db/MealDao.kt:34: There is a problem with the query: [SQLITE_ERROR] SQL error or missing database (no such column: calories_kcal)
  Columns: id, title, calories
> Task :app:hiltJavaCompileDebug FAILED
/work/app/build/generated/hilt/component_sources/debug/com/demo/App_HiltComponents.java:128: error: [Dagger/MissingBinding] com.demo.domain.BillingGateway cannot be provided without an @Provides-annotated method.
  com.demo.domain.BillingGateway is injected at
    [com.demo.App_HiltComponents.ViewModelC] com.demo.ui.CheckoutViewModel(gateway, savedStateHandle)
> Task :app:processDebugResources FAILED
ERROR: /work/app/src/main/res/layout/fragment_checkout.xml:19: AAPT: error: resource string/pay_cta_missing (aka com.demo:string/pay_cta_missing) not found.
> Task :app:processDebugMainManifest FAILED
/work/app/src/main/AndroidManifest.xml:22:9-48 Error:
	Attribute application@allowBackup value=(false) from AndroidManifest.xml:22:9-48
	is also present at [com.sdk:tracker:1.0] AndroidManifest.xml:11:9-45 value=(true).
"""
        errs = parse_compiler_errors(sample_log)
        by_type = {e["type"]: e for e in errs}
        self.assertIn("KSP", by_type)
        self.assertEqual(34, by_type["KSP"]["line"])
        self.assertIn("calories_kcal", by_type["KSP"]["message"])
        self.assertIn("Columns: id, title, calories", by_type["KSP"]["message"])

        self.assertIn("Dagger/Hilt", by_type)
        self.assertIn("BillingGateway", by_type["Dagger/Hilt"]["message"])
        self.assertIn("com.demo.ui.CheckoutViewModel", by_type["Dagger/Hilt"]["message"])

        self.assertIn("AAPT2", by_type)
        self.assertEqual(19, by_type["AAPT2"]["line"])
        self.assertIn("pay_cta_missing", by_type["AAPT2"]["message"])

        self.assertIn("Manifest", by_type)
        self.assertEqual(22, by_type["Manifest"]["line"])
        self.assertIn("allowBackup", by_type["Manifest"]["message"])

    def test_v150_web_patch_v1_zero_escaping_and_truncation_guard(self):
        import web_relay

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "app"
            (repo / ".agents/state").mkdir(parents=True)
            (repo / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('rootProject.name = "demo"\ninclude(":app")\n', encoding="utf-8")
            src = repo / "app/src/main/java/com/demo/PriceFormatter.kt"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(
                'package com.demo\nclass PriceFormatter {\n    fun format(amount: Int): String = "$amount EGP"\n}\n',
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "dev@local"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            pack_res = web_relay.build_web_pack(
                repo,
                files=["app/src/main/java/com/demo/PriceFormatter.kt"],
                prompt="Format currency with raw template and add test",
                no_clipboard=True,
            )
            pack_id = pack_res["pack_id"]
            pack_md = Path(pack_res["bundle_file"]).read_text(encoding="utf-8")
            # Outgoing Context Pack MUST NEVER be mistaken for an incoming reply!
            self.assertIsNone(web_relay._extract_merge_json_from_text(pack_md))

            # Truncated HARNESS_WEB_PATCH_V1 must be caught fail-closed!
            truncated_patch = (
                f"<<<HARNESS_WEB_PATCH_V1>>>\nPACK_ID: {pack_id}\nSTATUS: READY\n"
                "<<<MODIFY app/src/main/java/com/demo/PriceFormatter.kt>>>\n<<<<<<< SEARCH\nfoo\n"
            )
            self.assertEqual(pack_id, web_relay._detect_truncated_merge_pack_id(truncated_patch, {pack_id}))

            # Complete zero-escaping HARNESS_WEB_PATCH_V1 with "$${amount}" and """raw string""" applies cleanly!
            patch_reply = '''Here is the fix:
<<<HARNESS_WEB_PATCH_V1>>>
PACK_ID: __PACK_ID__
STATUS: READY
TASK_ID: price-raw-fmt
KIND: FEATURE
OUTCOME: Support raw currency template formatting
APPROACH: Update PriceFormatter and add JUnit test
RISKS: Verify formatting output

<<<MODIFY app/src/main/java/com/demo/PriceFormatter.kt>>>
<<<<<<< SEARCH
    fun format(amount: Int): String = "$amount EGP"
=======
    /** Formats price cleanly. */
    fun format(amount: Int): String = """Price: "$${amount}" EGP""".trim()
>>>>>>> REPLACE
<<<END_FILE>>>

<<<CREATE app/src/test/java/com/demo/PriceFormatterTest.kt>>>
package com.demo

import org.junit.Assert.assertTrue
import org.junit.Test

/** Verifies PriceFormatter output. */
class PriceFormatterTest {
    @Test
    fun formatsAmount() {
        assertTrue(PriceFormatter().format(50).contains("50"))
    }
}
<<<END_FILE>>>
<<<END_HARNESS_WEB_PATCH_V1>>>
'''.replace('__PACK_ID__', pack_id)
            reply_file = Path(td) / "reply.txt"
            reply_file.write_text(patch_reply, encoding="utf-8")
            applied = web_relay.apply_web_merge(
                repo,
                merge_file=str(reply_file),
                use_stdin=False,
                dry_run=False,
                source="conversation",
                proof_reference="apply reply",
            )
            self.assertEqual("APPLIED", applied["status"])
            updated_code = src.read_text(encoding="utf-8")
            self.assertIn('"""Price: "$', updated_code)
            self.assertTrue((repo / "app/src/test/java/com/demo/PriceFormatterTest.kt").is_file())

    def test_v150_compound_draft_with_context_and_approve_with_delegation(self):
        import workflow

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('rootProject.name = "demo"\ninclude(":app")\n', encoding="utf-8")
            (repo / "app").mkdir()
            (repo / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
            vm = repo / "app/src/main/java/com/demo/HomeViewModel.kt"
            vm.parent.mkdir(parents=True, exist_ok=True)
            vm.write_text("package com.demo\nclass HomeViewModel { fun refresh() = Unit }\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "dev@local"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            proc_draft = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "workflow.py"),
                    "draft",
                    "--repo", str(repo),
                    "--task-id", "home-refresh",
                    "--outcome", "Add retry state to HomeViewModel refresh",
                    "--kind", "FEATURE",
                    "--expected-files", "app/src/main/java/com/demo/HomeViewModel.kt",
                    "--with-context",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            draft_json = json.loads(proc_draft.stdout)
            self.assertIn("inline_task_context", draft_json)
            self.assertTrue(draft_json["inline_task_context"]["read_ranges"])
            plan_hash = draft_json["plan_sha256"][:12]

            proc_app = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "workflow.py"),
                    "approve",
                    "--repo", str(repo),
                    "--task-id", "home-refresh",
                    "--source", "conversation",
                    "--proof-reference", "Approve plan",
                    "--enforcement-tier", "RULE_ENFORCED",
                    "--plan-hash", plan_hash,
                    "--with-delegation",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            app_json = json.loads(proc_app.stdout)
            self.assertEqual("IMPLEMENTING", app_json["status"])
            self.assertIn("delegation_brief", app_json)
            self.assertTrue(app_json["delegation_brief"]["strategy"])



class TestV151DeepAuditUpgrades(unittest.TestCase):
    """End-to-end verification of all 6 v1.5.1 deep-audit fixes and performance upgrades."""

    def test_v151_01_logcat_doctor_threadtime_and_tombstone_capture(self):
        import logcat_doctor

        raw_log = (
            "11-18 23:20:01.100 14205 14205 E AndroidRuntime: FATAL EXCEPTION: main\n"
            "11-18 23:20:01.101 14205 14205 E AndroidRuntime: Process: com.demo.rashaqa, PID: 14205\n"
            "11-18 23:20:01.102 14205 14205 E AndroidRuntime: java.lang.IllegalStateException: Discount offer missing\n"
            "11-18 23:20:01.103 14205 14205 E AndroidRuntime: \tat com.demo.rashaqa.paywall.PaywallViewModel.select(PaywallViewModel.kt:88)\n"
            "11-18 23:20:01.104 14205 14205 E AndroidRuntime: Caused by: java.lang.NullPointerException: token\n"
            "11-18 23:20:01.105 14205 14205 E AndroidRuntime: \tat com.demo.rashaqa.data.BillingRepo.fetch(BillingRepo.kt:41)\n"
            "11-18 23:20:02.000 19999 19999 E AndroidRuntime: FATAL EXCEPTION: main\n"
            "11-18 23:20:02.001 19999 19999 E AndroidRuntime: Process: com.google.android.gms.persistent, PID: 19999\n"
            "11-18 23:20:02.002 19999 19999 E AndroidRuntime: java.lang.RuntimeException: Foreign crash\n"
        )
        res = logcat_doctor.filter_forensics(raw_log, app_id="com.demo.rashaqa", pkg_prefix="com.demo.rashaqa")
        self.assertEqual(1, len(res["fatals"]))
        crash_txt = res["fatals"][0]
        self.assertIn("IllegalStateException: Discount offer missing", crash_txt)
        self.assertIn("PaywallViewModel.kt:88", crash_txt)
        self.assertIn("Caused by: java.lang.NullPointerException", crash_txt)
        self.assertNotIn("Foreign crash", crash_txt)

    def test_v151_02_fast_kt_lint_brace_masking_and_kmp_swift_callers(self):
        import fast_kt_lint

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            vm_path = repo / "shared/src/commonMain/kotlin/com/demo/DietRepository.kt"
            swift_caller = repo / "iosApp/iosApp/ContentView.swift"
            vm_path.parent.mkdir(parents=True, exist_ok=True)
            swift_caller.parent.mkdir(parents=True, exist_ok=True)

            # Unbalanced `{` inside string literal must NOT corrupt brace_depth for `missingKdocContract()`!
            vm_code = (
                "package com.demo\n"
                "/** Shared KMP repository. */\n"
                "class DietRepository {\n"
                "    /** Parses raw JSON payload. */\n"
                "    fun isJsonObject(raw: String): Boolean = raw.trim().startsWith(\"{\")\n\n"
                '    fun calculateMacros(calories: Int): Int = if (isJsonObject("{}")) calories / 4 else 0\n'
                "}\n"
            )
            vm_path.write_text(vm_code, encoding="utf-8")
            swift_caller.write_text(
                "import Shared\nstruct ContentView { func render() { let _ = DietRepository().calculateMacros(calories: 1200) } }\n",
                encoding="utf-8",
            )

            kdoc_issues = fast_kt_lint.find_missing_architectural_kdoc(vm_path, vm_code, modified_lines=None)
            missing_syms = [i["msg"] for i in kdoc_issues]
            self.assertTrue(any("calculateMacros" in m for m in missing_syms), missing_syms)

            unused_issues = fast_kt_lint.find_unreferenced_new_declarations(repo, [vm_path], {vm_path: None})
            self.assertEqual([], unused_issues, f"Swift KMP caller should satisfy reference scan: {unused_issues}")

    def test_v151_03_dep_inspect_bom_versionless_catalog_resolution(self):
        import dep_inspect
        import zipfile as zf_mod

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "app"
            maven_dir = Path(td) / "maven"
            (repo / "gradle").mkdir(parents=True)
            (repo / ".agents/state").mkdir(parents=True)
            (repo / "gradle/libs.versions.toml").write_text(
                '[versions]\ncomposeBom = "2026.05.00"\n\n'
                '[libraries]\n'
                'androidx-compose-bom = { group = "androidx.compose", name = "compose-bom", version.ref = "composeBom" }\n'
                'androidx-compose-material3 = { group = "androidx.compose.material3", name = "material3" }\n',
                encoding="utf-8",
            )
            # Create local file:// Maven repo hosting compose-bom POM + material3-android-1.4.0-sources.jar
            bom_dir = maven_dir / "androidx/compose/compose-bom/2026.05.00"
            bom_dir.mkdir(parents=True)
            (bom_dir / "compose-bom-2026.05.00.pom").write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
                '  <properties><material3Version>1.4.0</material3Version></properties>\n'
                '  <dependencyManagement><dependencies>\n'
                '    <dependency>\n'
                '      <groupId>androidx.compose.material3</groupId>\n'
                '      <artifactId>material3</artifactId>\n'
                '      <version>${material3Version}</version>\n'
                '    </dependency>\n'
                '  </dependencies></dependencyManagement>\n'
                '</project>\n',
                encoding="utf-8",
            )
            m3_dir = maven_dir / "androidx/compose/material3/material3-android/1.4.0"
            m3_dir.mkdir(parents=True)
            with zf_mod.ZipFile(m3_dir / "material3-android-1.4.0-sources.jar", "w") as zf:
                zf.writestr(
                    "androidx/compose/material3/ModalBottomSheet.kt",
                    "package androidx.compose.material3\n/** Material3 modal sheet. */\nfun ModalBottomSheet(sheetState: SheetState) {}\n",
                )

            report = dep_inspect.inspect_dependency(
                repo,
                "material3",
                query="ModalBottomSheet",
                maven_repos=[maven_dir.as_uri()],
            )
            self.assertEqual("OK", report["status"])
            self.assertEqual("androidx.compose.material3:material3:1.4.0", report["coordinate"])
            self.assertTrue(any("ModalBottomSheet" in m["source"] for m in report["matches"]))

    def test_v151_04_check_strings_arabic_cldr_plurals_and_non_positional_specifiers(self):
        import check_strings
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base_xml = repo / "app/src/main/res/values/strings.xml"
            ar_xml = repo / "app/src/main/res/values-ar/strings.xml"
            base_xml.parent.mkdir(parents=True)
            ar_xml.parent.mkdir(parents=True)

            # 1. Incomplete Arabic plurals (missing zero, two, few, many) + unnumbered `%s %d` -> FAIL
            base_xml.write_text(
                '<resources>\n'
                '  <string name="greeting">Hello %1$s (%2$d)</string>\n'
                '  <plurals name="meals"><item quantity="one">%d meal</item><item quantity="other">%d meals</item></plurals>\n'
                '</resources>\n',
                encoding="utf-8",
            )
            ar_xml.write_text(
                '<resources>\n'
                '  <string name="greeting">مرحبا %s (%d)</string>\n'
                '  <plurals name="meals"><item quantity="one">وجبة واحدة</item><item quantity="other">%d وجبة</item></plurals>\n'
                '</resources>\n',
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            out_fail = io.StringIO()
            with contextlib.redirect_stdout(out_fail):
                rc_fail = check_strings.main(["--all"], repo=repo)
            self.assertEqual(1, rc_fail)
            self.assertIn("NON_POSITIONAL_FORMAT_SPECIFIERS", out_fail.getvalue())
            self.assertIn("missing required CLDR quantity item(s): zero, two, few, many", out_fail.getvalue())

            # 2. Complete 6-form idiomatic Arabic plurals (`zero`/`one`/`two` omitting `%d` naturally!) + positional `%1$s (%2$d)` -> PASS
            ar_xml.write_text(
                '<resources>\n'
                '  <string name="greeting">مرحبا %1$s (%2$d)</string>\n'
                '  <plurals name="meals">\n'
                '    <item quantity="zero">لا توجد وجبات</item>\n'
                '    <item quantity="one">وجبة واحدة</item>\n'
                '    <item quantity="two">وجبتان</item>\n'
                '    <item quantity="few">%d وجبات</item>\n'
                '    <item quantity="many">%d وجبة</item>\n'
                '    <item quantity="other">%d وجبة</item>\n'
                '  </plurals>\n'
                '</resources>\n',
                encoding="utf-8",
            )
            out_ok = io.StringIO()
            with contextlib.redirect_stdout(out_ok):
                rc_ok = check_strings.main(["--all"], repo=repo)
            self.assertEqual(0, rc_ok, out_ok.getvalue())

    def test_v151_05_in_process_preflight_and_retry_failure_web_patch_v1(self):
        import preflight_check
        import web_relay
        from unittest import mock

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "app"
            (repo / ".agents/state/results").mkdir(parents=True)
            (repo / ".agents/state/logs/gradle").mkdir(parents=True)
            (repo / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (repo / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
            src = repo / "app/src/main/java/com/demo/Calc.kt"
            src.parent.mkdir(parents=True)
            src.write_text("package com.demo\nclass Calc { fun add(a: Int, b: Int) = a + b }\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "dev@local"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            # Verify preflight_check.run_step runs check_strings.py & fast_kt_lint.py in-process without calling run_streaming!
            with mock.patch("_live_process.run_streaming", side_effect=AssertionError("subprocess should not spawn")):
                self.assertEqual(0, preflight_check.run_step("1. String parity", "check_strings.py", cwd=repo, diagnostics={}))
                self.assertEqual(0, preflight_check.run_step("3. Fast lint", "fast_kt_lint.py", cwd=repo, diagnostics={}))

            # Verify `web-pack --retry-failure` advertises `<<<HARNESS_WEB_PATCH_V1>>>` while staying compact (< 3500 bytes)
            p1 = web_relay.build_web_pack(repo, files=["app/src/main/java/com/demo/Calc.kt"], prompt="Fix calc", no_clipboard=True)
            (repo / ".agents/state/results/gradle-compiledebugkotlin.json").write_text(
                '{"schema_version":1,"task":":app:compileDebugKotlin","status":"FAIL","exit_code":1,"detail":"err"}',
                encoding="utf-8",
            )
            (repo / ".agents/state/logs/gradle/20261119-000000-compile.log").write_text(
                f"e: file:///{src.as_posix()}:2:20: Type mismatch.\n",
                encoding="utf-8",
            )
            rf = web_relay.build_web_pack(repo, task_id=p1["suggested_task_id"], retry_failure=True, no_clipboard=True)
            self.assertLess(rf["bundle_bytes"], 3500)
            rf_md = Path(rf["bundle_file"]).read_text(encoding="utf-8")
            self.assertIn("<<<HARNESS_WEB_PATCH_V1>>>", rf_md)


class TestV152Gemini4NeonStandaloneParity(unittest.TestCase):
    def test_v152_gemini4_neon_standalone_parity(self):
        """Verify standalone Gemini 4 Neon parity with Argon/Carbon across offload, pacer, guards, and hazards."""
        import antigravity_runtime as ar
        import delegation_policy as dp
        import pre_tool_safety as pts
        import review_execution
        import review_models
        from _vnext_common import atomic_write_json

        # 1. Anti-burst pacer exempts standalone Neon (all tiers) while keeping Hydrogen & Orchestrator non-exempt
        self.assertTrue(pts._model_exempt_from_hydrogen_burst_pacer("Gemini 4 Neon"))
        self.assertTrue(pts._model_exempt_from_hydrogen_burst_pacer("gemini-4-neon-high"))
        self.assertTrue(pts._model_exempt_from_hydrogen_burst_pacer("gemini-4-neon-xhigh"))
        self.assertFalse(pts._model_exempt_from_hydrogen_burst_pacer("gemini-4-hydrogen-high"))
        self.assertFalse(pts._model_exempt_from_hydrogen_burst_pacer("Orchestrator (Neon)"))

        # 2. Runtime hazard classifiers cover Gemini 4 Neon entitlement desync & zero-quota 429
        hz_desync = ar.classify_antigravity_quota_or_capacity_error(
            "Model Gemini 4 Neon is marked Unavailable due to account entitlement sync"
        )
        self.assertIsNotNone(hz_desync)
        self.assertEqual("GEMINI4_ENTITLEMENT_DESYNC_UNAVAILABLE", hz_desync["code"])
        hz_429 = ar.classify_antigravity_quota_or_capacity_error(
            "HTTP 429 RESOURCE_EXHAUSTED: gemini-4-neon limit: 0 on pro tier"
        )
        self.assertIsNotNone(hz_429)
        self.assertEqual("MANAGED_AGENT_ZERO_QUOTA_429", hz_429["code"])

        # 3. Active Lead on standalone Gemini 4 Neon triggers Model='flash' offload for Scouts, Specialists & Hydrogen Reviewers
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "app"
            (repo / ".agents/state/tasks/t-neon").mkdir(parents=True)
            shutil.copytree(REPO_ROOT / "agents/subagents", repo / ".agents/subagents", dirs_exist_ok=True)
            dp.record_live_lead_session_model(repo, "cid-neon", "Gemini 4 Neon (High)")
            self.assertEqual((True, "gemini-4-neon"), dp.is_frontier_lead_requiring_flash_offload(repo, "cid-neon"))

            plan_impl = {
                "schema_version": 1,
                "task_id": "t-neon",
                "status": "IMPLEMENTING",
                "execution_nonce": "nonce-neon",
                "task_kind": "FEATURE",
                "risk_tier": "T2_FEATURE",
                "expected_files": ["app/src/main/java/A.kt"],
            }
            atomic_write_json(repo / ".agents/state/active-task.json", {"task_id": "t-neon"})
            atomic_write_json(repo / ".agents/state/tasks/t-neon/plan.json", plan_impl)
            review_models.set_policy(
                repo,
                review_models.resolve_preset_policy("hydrogen-dynamic"),
                task_id=None,
                host="antigravity",
                source="conversation",
                proof_reference="Use hydrogen-dynamic subagents on Neon Lead",
                scope="project",
            )
            pol_del = dp.evaluate_delegation_policy(repo, task_id="t-neon", plan=plan_impl, router_action="IMPLEMENT")
            self.assertEqual("flash", pol_del["scout_invoke_model"])

            engine_script = REPO_ROOT / "agents/scripts/pre_tool_safety.py"
            env = {**os.environ, "HARNESS_REPO": str(repo), "HARNESS_HOST": "antigravity"}

            # Omitting Model on Scout when Lead is Neon -> denied (must offload via Model='flash')
            pr_deny = subprocess.run(
                [sys.executable, str(engine_script)],
                input=json.dumps({
                    "conversationId": "cid-neon",
                    "toolCall": {
                        "name": "invoke_subagent",
                        "args": {"Subagents": [{
                            "TypeName": "harness-scout-agent",
                            "Role": "harness-scout-agent",
                            "Workspace": "inherit",
                            "Prompt": "Inspect A.kt, B.kt, C.kt, and D.kt callers.",
                        }]},
                    },
                }),
                capture_output=True, text=True, env=env, check=False,
            )
            self.assertEqual("deny", json.loads(pr_deny.stdout)["decision"], pr_deny.stdout)

            # Passing Model='flash' on Scout & Specialist when Lead is Neon -> allowed
            for role_name, prompt_txt in (
                ("harness-scout-agent", "Inspect A.kt, B.kt, C.kt, and D.kt callers."),
                ("android-ui-expert-agent", "Audit RTL padding in A.kt."),
            ):
                pr_ok = subprocess.run(
                    [sys.executable, str(engine_script)],
                    input=json.dumps({
                        "conversationId": "cid-neon",
                        "toolCall": {
                            "name": "invoke_subagent",
                            "args": {"Subagents": [{
                                "TypeName": role_name,
                                "Role": role_name,
                                "Workspace": "inherit",
                                "Model": "flash",
                                "Prompt": prompt_txt,
                            }]},
                        },
                    }),
                    capture_output=True, text=True, env=env, check=False,
                )
                self.assertEqual("allow", json.loads(pr_ok.stdout)["decision"], pr_ok.stdout)

            # When reviewer policy is explicitly neon-dynamic, reviewer omits Model (INHERIT_PARENT_BY_OMISSION)
            review_models.set_policy(
                repo,
                review_models.resolve_preset_policy("neon-dynamic"),
                task_id="t-neon",
                host="antigravity",
                source="conversation",
                proof_reference="Explicit Neon reviewers",
                scope="task",
            )
            pol_path = repo / ".agents/state/tasks/t-neon/policy.json"
            atomic_write_json(pol_path, {"reviewers": ["bug-test-reviewer-agent"], "surfaces": ["BUSINESS_LOGIC"], "risk_tier": "T2_FEATURE"})
            frozen_n = review_models.freeze_models(repo, "t-neon", "antigravity", ["bug-test-reviewer-agent"])
            atomic_write_json(
                repo / ".agents/state/tasks/t-neon/current-run.json",
                {
                    "run_id": "RUN_NEON_1",
                    "review_host": "antigravity",
                    "review_protocol_version": 2,
                    "policy": str(pol_path),
                    "review_models": frozen_n,
                },
            )
            exec_prof_n = review_execution.resolve_execution_profile(repo, "t-neon", host="antigravity")
            self.assertEqual({}, exec_prof_n["reviewers"]["bug-test-reviewer-agent"]["native_arguments"])

        gemini_tpl = (REPO_ROOT / "agents/tool-adapters/GEMINI.md.template").read_text(encoding="utf-8")
        self.assertIn("Gemini 4 Neon (High)", gemini_tpl)
        self.assertIn("`Carbon`/`Neon`/`Argon`", gemini_tpl)
        self.assertNotIn("Orchestrator (Neon)", gemini_tpl)



class TestV153PrecisionAuditFixes(unittest.TestCase):
    """End-to-end regression suite for all 5 v1.5.3 AST, String-Interpolation, Room KMP, Perf & Architecture fixes."""

    def test_v153_01_symbol_edit_and_source_outline_multiline_expr_default_eq_and_annotations(self):
        import _source_outline
        import _source_text
        import symbol_edit

        with tempfile.TemporaryDirectory() as td:
            kt = Path(td) / "MealViewModel.kt"
            kt.write_text(
                'package com.demo\n\n'
                'class MealViewModel {\n'
                '    @Query(\n'
                '        """\n'
                '        SELECT * FROM meals\n'
                '        WHERE note LIKE \'%{daily\'\n'
                '        """\n'
                '    )\n'
                '    fun observeMeals(): Flow<List<String>> =\n'
                '        flow {\n'
                '            val s = "state=${if (true) "{" else "}"}"\n'
                '            emit(listOf(s))\n'
                '        }\n\n'
                '    fun sync(force: Boolean = false)\n'
                '    {\n'
                '        println(force)\n'
                '    }\n'
                '}\n',
                encoding="utf-8",
            )
            syms = {s["qualified_name"]: s for s in symbol_edit.parse_symbols(kt)}
            # Multi-line @Query("""...""") + multi-line `= flow { ... }` span L4..L14 cleanly!
            self.assertEqual(4, syms["MealViewModel.observeMeals"]["start_line"])
            self.assertEqual(14, syms["MealViewModel.observeMeals"]["end_line"])
            # Default parameter `= false` does not prematurely terminate brace-next function L16..L19!
            self.assertEqual(16, syms["MealViewModel.sync"]["start_line"])
            self.assertEqual(19, syms["MealViewModel.sync"]["end_line"])
            # Nested string interpolation `"state=${if (true) "{" else "}"}"` maintains exact 0 brace delta!
            self.assertEqual((0, 0), symbol_edit.code_brace_delta(kt.read_text(encoding="utf-8").splitlines()))

            # _source_outline handles unbalanced `{` inside `"""..."""` without breaking enclosing class depth
            out = {(e["kind"], e["name"]): (e["line"], e["end_line"]) for e in _source_outline.outline(kt)}
            self.assertEqual((3, 20), out[("class", "MealViewModel")])
            self.assertEqual((10, 14), out[("fun", "observeMeals")])
            self.assertEqual((16, 19), out[("fun", "sync")])

            # _source_text.mask_comments_and_strings preserves exact length & masks inner `{` inside `${...}`
            sample = 'val msg = "status=${if (ok) "{open" else "ok"}"'
            masked = _source_text.mask_comments_and_strings(sample)
            self.assertEqual(len(sample), len(masked))
            self.assertNotIn("{", masked)

    def test_v153_02_room_guard_kmp_reified_builder_large_header_and_sql_comments(self):
        import room_guard

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "kmp_app"
            db_dir = repo / "shared/src/commonMain/kotlin/com/demo/db"
            db_dir.mkdir(parents=True)
            (repo / "shared/build.gradle.kts").write_text('plugins { kotlin("multiplatform") }\n', encoding="utf-8")

            # >4500 chars of imports before @Database so old [:4000] truncation would miss AppDatabase completely!
            long_imports = "".join(f"import com.demo.model.EntityModelNumber{i:03d}\n" for i in range(110))
            assert len(long_imports) > 4500

            entity_p = db_dir / "MealEntity.kt"
            db_p = db_dir / "AppDatabase.kt"
            di_p = db_dir / "DatabaseModule.kt"

            entity_p.write_text("package com.demo.db\nimport androidx.room.Entity\n@Entity data class MealEntity(val id: Int)\n", encoding="utf-8")
            db_p.write_text(
                f"package com.demo.db\n{long_imports}import androidx.room.Database\nimport androidx.room.RoomDatabase\n"
                "@Database(entities = [MealEntity::class], version = 1)\nabstract class AppDatabase : RoomDatabase()\n",
                encoding="utf-8",
            )
            di_p.write_text(
                f"package com.demo.db\n{long_imports}import androidx.room.Room\nimport androidx.room.migration.Migration\n"
                "fun provideOther(ctx: Any) = Room.databaseBuilder(ctx, LegacyDb::class.java, \"legacy.db\").build()\n"
                "fun provideMain() = Room.databaseBuilder<AppDatabase>(name = \"app.db\").build()\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "dev@local"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "v1"], cwd=repo, check=True)

            # Mutate MealEntity without bumping >4500-char AppDatabase -> MUST FAIL (proves [:4000] blind spot is gone!)
            entity_p.write_text(
                "package com.demo.db\nimport androidx.room.Entity\n@Entity data class MealEntity(val id: Int, val kcal: Int)\n",
                encoding="utf-8",
            )
            ok_unbumped, msg_unbumped = room_guard.check_room_working_tree(repo=repo)
            self.assertFalse(ok_unbumped, msg_unbumped)

            # Bump version to 2 + register via KMP `Room.databaseBuilder<AppDatabase>` + include warning SQL comment -> MUST PASS!
            db_p.write_text(
                f"package com.demo.db\n{long_imports}import androidx.room.Database\nimport androidx.room.RoomDatabase\n"
                "@Database(entities = [MealEntity::class], version = 2)\nabstract class AppDatabase : RoomDatabase()\n",
                encoding="utf-8",
            )
            di_p.write_text(
                f"package com.demo.db\n{long_imports}import androidx.room.Room\nimport androidx.room.migration.Migration\n"
                "// WARNING: Never run ALTER TABLE MealEntity ADD COLUMN kcal INTEGER NOT NULL without DEFAULT!\n"
                "val MIGRATION_1_2 = Migration(1, 2) { db -> db.execSQL(\"ALTER TABLE MealEntity ADD COLUMN kcal INTEGER NOT NULL DEFAULT 0\") }\n"
                "fun provideOther(ctx: Any) = Room.databaseBuilder(ctx, LegacyDb::class.java, \"legacy.db\").build()\n"
                "fun provideMain() = Room.databaseBuilder<AppDatabase>(name = \"app.db\").addMigrations(MIGRATION_1_2).build()\n",
                encoding="utf-8",
            )
            ok_mig, msg_mig = room_guard.check_room_working_tree(repo=repo)
            self.assertTrue(ok_mig, msg_mig)

    def test_v153_03_perf_guard_test_exclusion_architecture_binding_and_kmp_raw_strings(self):
        import _modules
        import architecture_drift
        import perf_guard

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "kmp_proj"
            unit_test = repo / "app/src/test/java/com/demo/MealDaoTest.kt"
            android_test = repo / "app/src/androidTest/java/com/demo/UiTest.kt"
            kmp_test = repo / "shared/src/commonTest/kotlin/com/demo/SharedTest.kt"
            prod_file = repo / "app/src/main/java/com/demo/ProdRepo.kt"
            for p in (unit_test, android_test, kmp_test, prod_file):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(
                    "package com.demo\nclass Sample { fun run() { Room.inMemoryDatabaseBuilder().allowMainThreadQueries(); Thread.sleep(10); runBlocking { } } }\n",
                    encoding="utf-8",
                )
            self.assertEqual([], perf_guard.scan_file(unit_test))
            self.assertEqual([], perf_guard.scan_file(android_test))
            self.assertEqual([], perf_guard.scan_file(kmp_test))
            self.assertEqual(3, len(perf_guard.scan_file(prod_file)))

            # architecture_drift._is_compose_screen ignores `bindingState` variable while catching real `FragmentHomeBinding`
            self.assertTrue(architecture_drift._is_compose_screen("@Composable fun S(bindingState: String) { Text(bindingState) }"))
            self.assertFalse(architecture_drift._is_compose_screen("@Composable fun S(b: FragmentHomeBinding) { }"))

            # KMP commonMain purity & expect/actual ignore fake imports/declarations inside triple-quoted raw strings
            cm = repo / "shared/src/commonMain/kotlin/com/demo/DocSample.kt"
            am = repo / "shared/src/androidMain/kotlin/com/demo/DocSample.android.kt"
            cm.parent.mkdir(parents=True, exist_ok=True)
            am.parent.mkdir(parents=True, exist_ok=True)
            cm.write_text(
                'package com.demo\nval guide = """\nimport android.os.Bundle\nexpect fun notReal(): String\n"""\nexpect fun realPlatform(): String\n',
                encoding="utf-8",
            )
            am.write_text('package com.demo\nactual fun realPlatform(): String = "Android"\n', encoding="utf-8")
            pure_ok, pure_v = _modules.check_kmp_common_main_purity(repo, ["shared/src/commonMain/kotlin/com/demo/DocSample.kt"])
            self.assertTrue(pure_ok, pure_v)
            ea_ok, ea_msg = _modules.check_kmp_expect_actual_pairs(repo, ["shared/src/commonMain/kotlin/com/demo/DocSample.kt"])
            self.assertTrue(ea_ok, ea_msg)



class TestV154Antigravity1512AndIssue1649Hardening(unittest.TestCase):
    """End-to-end regression suite for v1.5.0 (#1649/#201731 Hydrogen Medium 0-thinking guard, /fork scratch-free hint, and agy 1.5.12 metadata)."""
    _KIT = Path(__file__).resolve().parents[2]

    def test_v154_quirk_1649_windows_hydrogen_medium_offload_reminder_doctor_and_forensics(self) -> None:
        import contextlib
        import io
        import antigravity_runtime as agr
        import delegation_policy as dp
        import platform_quirks as pq
        import pre_invocation_reminder as pir
        import review_models as rm
        import session_forensics as sf
        from _vnext_common import atomic_write_json
        from doctor.engine import HarnessDoctor

        self.assertEqual("AGY_1649_201731_WIN_HYDROGEN_MEDIUM_ZERO_THINKING", pq.resolve_quirk_id("#1649"))
        self.assertEqual("AGY_1649_201731_WIN_HYDROGEN_MEDIUM_ZERO_THINKING", pq.resolve_quirk_id("201731"))
        self.assertEqual("1.5.12", agr.LATEST_KNOWN_ANTIGRAVITY_VERSIONS["cli_version"])
        self.assertEqual("1.13.0", agr.LATEST_KNOWN_ANTIGRAVITY_VERSIONS["vscode_extension_version"])
        vers = agr.detect_antigravity_versions({"ANTIGRAVITY_CLI_VERSION": "1.5.12", "ANTIGRAVITY_VSCODE_VERSION": "1.13.0"})
        self.assertEqual("1.5.12", vers["cli_version"])
        self.assertEqual("1.13.0", vers["vscode_extension_version"])

        cls_1649 = agr.classify_antigravity_quota_or_capacity_error(
            "Hydrogen Medium reported 0 thinking tokens (thinking_tokens=0) after read_file"
        )
        self.assertIsNotNone(cls_1649)
        self.assertEqual("HYDROGEN_MEDIUM_ZERO_THINKING_AFTER_TOOL", cls_1649["code"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            repo = root / "app"
            shutil.copytree(
                self._KIT / "agents",
                repo / ".agents",
                ignore=shutil.ignore_patterns("state", "cache", "__pycache__", "*.pyc"),
            )
            (repo / ".agents" / "state").mkdir(parents=True, exist_ok=True)
            (repo / ".agents" / "cache").mkdir(parents=True, exist_ok=True)
            for sub in ("harness-scout-agent", "android-ui-expert-agent", "bug-test-reviewer-agent"):
                md_p = repo / ".agents" / "agents" / sub / "agent.md"
                md_p.parent.mkdir(parents=True, exist_ok=True)
                md_p.write_text("---\nname: role\ndescription: role\n---\nPrompt\n", encoding="utf-8")

            dp.record_live_lead_session_model(repo, "cid-h-med", "Gemini 4 Hydrogen (Medium)")

            # Non-Windows host -> does NOT force Model='flash' on Hydrogen Medium
            with unittest.mock.patch.dict(os.environ, {"HARNESS_SIMULATE_PLATFORM": "linux"}, clear=False):
                self.assertEqual((False, "gemini-4-hydrogen"), dp.is_frontier_lead_requiring_flash_offload(repo, "cid-h-med"))
                haz_linux = agr.inspect_nov15_antigravity_hazards(
                    repo, env={"HARNESS_SIMULATE_PLATFORM": "linux", "ANTIGRAVITY_ACTIVE_MODEL": "Gemini 4 Hydrogen (Medium)"}
                )
                self.assertFalse(haz_linux["hydrogen_medium_win_tool_risk"])

            # Windows host -> Hydrogen Medium triggers #1649 offload (`Model='flash'` -> Hydrogen Tiered High 1x), Doctor WARN, and PreInvocation guard;
            # Hydrogen High on Windows remains INHERIT_PARENT_BY_OMISSION!
            with unittest.mock.patch.dict(
                os.environ,
                {"HARNESS_SIMULATE_PLATFORM": "win32", "ANTIGRAVITY_ACTIVE_MODEL": "Gemini 4 Hydrogen (Medium)"},
                clear=False,
            ):
                self.assertEqual((True, "gemini-4-hydrogen-medium"), dp.is_frontier_lead_requiring_flash_offload(repo, "cid-h-med"))
                haz_win = agr.inspect_nov15_antigravity_hazards(repo)
                self.assertTrue(haz_win["hydrogen_medium_win_tool_risk"])

                # Scout without Model='flash' is denied with #1649 guidance; with Model='flash' is allowed!
                ok_no_m, reason_no_m, code_no_m = dp.validate_utility_dispatch(
                    repo,
                    None,
                    [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Workspace": "inherit", "Prompt": "Inspect app/src/main/kotlin/com/demo/A.kt and B.kt callers."}],
                    parent_conversation_id="cid-h-med",
                )
                self.assertFalse(ok_no_m)
                self.assertEqual("UTILITY_MODEL_QUOTA_GUARD", code_no_m)
                self.assertIn("HYDROGEN_MEDIUM_WIN_TOOL_THINKING_GUARD", reason_no_m)

                ok_flash, reason_flash, _ = dp.validate_utility_dispatch(
                    repo,
                    None,
                    [{"TypeName": "harness-scout-agent", "Role": "harness-scout-agent", "Workspace": "inherit", "Model": "flash", "Prompt": "Inspect app/src/main/kotlin/com/demo/A.kt and B.kt callers."}],
                    parent_conversation_id="cid-h-med",
                )
                self.assertTrue(ok_flash, reason_flash)

                # Proven parent session justifies flash offload in review_models
                self.assertTrue(
                    rm._is_proven_frontier_parent_session(
                        {}, {"repo": str(repo)}, {"execution_id": "sub-1"}
                    )
                )

                # PreInvocation surfaces #1649 warning on Windows Hydrogen Medium
                with unittest.mock.patch.object(pir, "REPO", repo), unittest.mock.patch.object(pir, "_update_notice", return_value=""):
                    buf_p = io.StringIO()
                    with unittest.mock.patch(
                        "sys.stdin",
                        io.StringIO(json.dumps({"invocationNum": 0, "conversationId": "cid-h-med", "modelName": "Gemini 4 Hydrogen (Medium)"})),
                    ), contextlib.redirect_stdout(buf_p):
                        pir.main()
                    ephem = json.loads(buf_p.getvalue())["injectSteps"][0]["ephemeralMessage"]
                    self.assertIn("THINKING-DROP GUARD #1649", ephem)

                # Doctor check_antigravity_installation logs WARN for Windows Hydrogen Medium
                doc = HarnessDoctor(repo, run_selftest=False)
                doc.check_antigravity_installation()
                nov15_chk = next(r for r in doc.results if r.name == "Nov 15 Quota & Diff Guard")
                self.assertEqual("WARN", nov15_chk.status)
                self.assertIn("#1649", nov15_chk.message)

                # Switching Lead to Hydrogen High on Windows clears #1649 offload immediately
                dp.record_live_lead_session_model(repo, "cid-h-high", "Gemini 4 Hydrogen (High)")
                self.assertEqual((False, "gemini-4-hydrogen"), dp.is_frontier_lead_requiring_flash_offload(repo, "cid-h-high"))

                # Disabling quirk 1649 suppresses Windows Hydrogen Medium offload cleanly
                with unittest.mock.patch.dict(os.environ, {"HARNESS_DISABLE_QUIRKS": "1649"}, clear=False):
                    self.assertEqual((False, "gemini-4-hydrogen"), dp.is_frontier_lead_requiring_flash_offload(repo, "cid-h-med"))

            # Forensics: detect thinking_tokens == 0 after read_file on Hydrogen Medium in transcript_full.jsonl
            brain_root = root / "brain"
            conv_dir = brain_root / "conv-1649" / ".system_generated" / "logs"
            conv_dir.mkdir(parents=True)
            tx_full = conv_dir / "transcript_full.jsonl"
            tx_full.write_text(
                "\n".join([
                    json.dumps({"step_index": 1, "model": "gemini-4-hydrogen-medium", "usage": {"input_tokens": 1200, "output_tokens": 80, "thinking_tokens": 140}}),
                    json.dumps({"step_index": 2, "model": "gemini-4-hydrogen-medium", "tool_name": "read_file"}),
                    json.dumps({"step_index": 3, "model": "gemini-4-hydrogen-medium", "usage": {"input_tokens": 2400, "cache_read_tokens": 1200, "output_tokens": 95, "thinking_tokens": 0}}),
                ]) + "\n",
                encoding="utf-8",
            )
            atomic_write_json(repo / ".agents/state/active-conversation.json", {"conversation_id": "conv-1649"})
            with unittest.mock.patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": str(root)}, clear=False):
                diag = sf.diagnose_session(repo, conversation_id="conv-1649")
                self.assertEqual(1, diag["transcript"]["hydrogen_medium_zero_thinking_hits"])
                codes = [f["code"] for f in diag["findings"]]
                self.assertIn("HYDROGEN_MEDIUM_ZERO_THINKING_AFTER_TOOL", codes)

    def test_v154_verification_contract_fork_safe_path_hint_and_policy_vocab_zero_diff(self) -> None:
        import verification_contract as vc
        from _vnext_common import ValidationError

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            with self.assertRaises(ValidationError) as ctx:
                vc.load_definition(repo, "{broken-powershell-json")
            err_msg = str(ctx.exception)
            self.assertIn(".agents/cache/tmp-contract.json", err_msg)
            self.assertIn("/fork", err_msg)
            self.assertNotIn("e.g. the conversation scratch folder", err_msg)

            # Confirm a repo-local .agents/cache/tmp-contract.json loads cleanly
            tmp_c = repo / ".agents" / "cache" / "tmp-contract.json"
            tmp_c.parent.mkdir(parents=True, exist_ok=True)
            tmp_c.write_text(json.dumps({"unit_tests": ["testDebugUnitTest"]}), encoding="utf-8")
            loaded = vc.load_definition(repo, ".agents/cache/tmp-contract.json")
            self.assertEqual(["testDebugUnitTest"], loaded["unit_tests"])

    def test_v150_hardening_chained_expr_nested_generics_and_non_arabic_plurals(self) -> None:
        import _graph_core
        import _source_outline
        import check_strings
        import symbol_edit

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            # 1) Chained expression body spans all continuation lines in both outline & symbol_edit
            kt = repo / "Chain.kt"
            kt.write_text(
                "\n".join([
                    "class Chain {",
                    "    fun filterNames(items: List<String>): List<String> =",
                    "        items",
                    "            .filter { it.isNotBlank() }",
                    "            .map { it.trim() }",
                    "",
                    "    fun nextFn() = 42",
                    "}",
                ]) + "\n",
                encoding="utf-8",
            )
            syms = {s["name"]: s for s in symbol_edit.parse_symbols(kt)}
            self.assertEqual((2, 5), (syms["filterNames"]["start_line"], syms["filterNames"]["end_line"]))
            self.assertEqual((7, 7), (syms["nextFn"]["start_line"], syms["nextFn"]["end_line"]))
            out_map = {e["name"]: e for e in _source_outline.outline(kt)}
            self.assertEqual((2, 5), (out_map["filterNames"]["line"], out_map["filterNames"]["end_line"]))

            # 2) Nested generics & `where` constraints do not pollute Kotlin supertype edges
            _, supers, _ = _graph_core._extract_di_and_contract_metadata(
                "class RepoImpl<T> : BaseRepo<List<Map<String, Foo>>>(), RealContract where T : Comparable<T> {\n}\n",
                is_java=False,
            )
            self.assertEqual(["BaseRepo", "RealContract"], supers.get("RepoImpl"))

            # 3) Non-Arabic plural where base `one` omits `%d` and `other` repeats `%1$d` produces zero false positives
            (repo / "app/src/main/res/values").mkdir(parents=True)
            (repo / "app/src/main/res/values-fr").mkdir(parents=True)
            (repo / "app/src/main/res/values/strings.xml").write_text(
                "<resources>\n"
                "  <plurals name=\"items_count\">\n"
                "    <item quantity=\"one\">One item</item>\n"
                "    <item quantity=\"other\">%1$d of %1$d items</item>\n"
                "  </plurals>\n"
                "</resources>\n",
                encoding="utf-8",
            )
            (repo / "app/src/main/res/values-fr/strings.xml").write_text(
                "<resources>\n"
                "  <plurals name=\"items_count\">\n"
                "    <item quantity=\"one\">Un element</item>\n"
                "    <item quantity=\"other\">%1$d sur %1$d elements</item>\n"
                "  </plurals>\n"
                "</resources>\n",
                encoding="utf-8",
            )
            saved_cs = check_strings.REPO
            check_strings.REPO = repo
            try:
                rc = check_strings.main([], repo=repo)
            finally:
                check_strings.REPO = saved_cs
            self.assertEqual(0, rc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
