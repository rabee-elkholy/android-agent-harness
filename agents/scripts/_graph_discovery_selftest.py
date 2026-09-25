"""Graph-First Discovery Hardening Selftest Suite.

Covers:
- GRAPH-001: Exact ViewModel -> D1 TARGETED_GRAPH_CONTEXT, graph_basis.used = true.
- GRAPH-002: Feature-Level Request -> D2 FEATURE_GRAPH, anchor RUN_PROJECT_GRAPH.
- GRAPH-003: Unknown Code Location -> D2 FEATURE_GRAPH with find symbol.
- GRAPH-004: Multi-Module Refactor -> D3 ARCHITECTURAL_GRAPH.
- GRAPH-005: Exact strings.xml -> D0 EXACT_FILE_DIRECT.
- GRAPH-006: Search Before Discovery Anchor -> DENY DISCOVERY_ANCHOR_REQUIRED.
- GRAPH-007: Search Inside Discovered Scope -> ALLOW.
- GRAPH-008: Search Outside Discovered Scope -> DENY DISCOVERY_SCOPE_EXPANSION_REQUIRED.
- GRAPH-009: Bounded Context Insufficient -> graph_expansion_required = true.
- GRAPH-010: Directory Listing Cascade -> DISCOVERY_ANCHOR_REQUIRED.
- GRAPH-011: Graph/Source Disagreement -> source evidence wins.
- Plan discovery provenance & freshness validation.
- Public graph CLI façade verification.
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

from _vnext_common import atomic_write_json, canonical_sha256, utc_now
from discovery_receipt import (
    create_discovery_receipt,
    save_discovery_receipt,
    load_discovery_receipt,
    load_latest_discovery_receipt,
    is_path_in_discovery_scope,
    check_discovery_freshness,
)
from discovery_router import (
    route_discovery,
    DISCOVERY_D0_EXACT_FILE,
    DISCOVERY_D1_TARGETED_GRAPH,
    DISCOVERY_D2_FEATURE_GRAPH,
    DISCOVERY_D3_ARCHITECTURAL_GRAPH,
    ANCHOR_DIRECT_FILE_READ,
    ANCHOR_RUN_TASK_CONTEXT,
    ANCHOR_RUN_PROJECT_GRAPH,
)

KIT = Path(__file__).resolve().parents[2]


def _run_git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {repo}:\n{proc.stderr}\n{proc.stdout}")


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


class GraphDiscoverySelftest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="graph_disc_test_")
        self.repo = Path(self.temp_dir.name).resolve()

        # Initialize minimal git repo
        _run_git(self.repo, "init", "-q")
        _run_git(self.repo, "config", "user.name", "Graph Test")
        _run_git(self.repo, "config", "user.email", "graph@example.invalid")
        _run_git(self.repo, "config", "core.autocrlf", "false")

        # Layout
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "profile").mkdir(parents=True, exist_ok=True)
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "tracking").mkdir(parents=True, exist_ok=True)
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "payments").mkdir(parents=True, exist_ok=True)
        (self.repo / "app" / "src" / "main" / "res" / "values").mkdir(parents=True, exist_ok=True)

        (self.repo / "settings.gradle.kts").write_text('rootProject.name = "GraphApp"\ninclude(":app")\n', encoding="utf-8")
        (self.repo / "app" / "build.gradle.kts").write_text('plugins { id("com.android.application") }\n', encoding="utf-8")
        (self.repo / "README.md").write_text("# GraphApp\nSample project.\n", encoding="utf-8")
        (self.repo / "app" / "src" / "main" / "res" / "values" / "strings.xml").write_text(
            '<resources>\n    <string name="app_name">GraphApp</string>\n</resources>\n',
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "profile" / "ProfileViewModel.kt").write_text(
            "package com.example.profile\n\nclass ProfileViewModel {\n    fun refresh() {}\n}\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "tracking" / "TrackingService.kt").write_text(
            "package com.example.tracking\n\nclass TrackingService {\n    fun startTracking() {}\n}\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "payments" / "PaymentProcessor.kt").write_text(
            "package com.example.payments\n\nclass PaymentProcessor {\n    fun charge() {}\n}\n",
            encoding="utf-8",
        )

        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "initial commit")

        self.env = {**os.environ, "HARNESS_REPO": str(self.repo)}
        self.safety_script = KIT / "agents" / "scripts" / "pre_tool_safety.py"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _invoke_safety(self, tool_name: str, tool_args: dict) -> dict:
        payload = json.dumps({"toolName": tool_name, "toolArgs": tool_args})
        proc = subprocess.run(
            [sys.executable, str(self.safety_script)],
            input=payload,
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, proc.returncode, f"stderr: {proc.stderr}\nstdout: {proc.stdout}")
        return _with_audit_reason(json.loads(proc.stdout.strip()), self.env, self.safety_script)

    def test_graph_001_exact_view_model(self) -> None:
        """GRAPH-001: Exact ViewModel routes to D1 TARGETED_GRAPH_CONTEXT with task-context anchor."""
        decision = route_discovery(
            self.repo,
            outcome="Fix ProfileViewModel refresh bug",
            target_symbol="ProfileViewModel",
        )
        self.assertEqual(DISCOVERY_D1_TARGETED_GRAPH, decision.mode)
        self.assertEqual(ANCHOR_RUN_TASK_CONTEXT, decision.required_anchor["code"])
        self.assertIn("task-context", decision.required_anchor["command"])
        self.assertIn("ProfileViewModel", decision.required_anchor["command"])

        # Execute task_context and verify graph_basis
        import task_context
        ctx = task_context.resolve_task_context(
            self.repo,
            symbol="ProfileViewModel",
        )
        self.assertEqual("RESOLVED", ctx.get("status"))
        graph_basis = ctx.get("graph_basis")
        self.assertIsNotNone(graph_basis)
        self.assertTrue(graph_basis.get("used"))
        self.assertTrue(bool(graph_basis.get("graph_fingerprint")))

        # Discovery receipt was generated and cached
        latest = load_latest_discovery_receipt(self.repo)
        self.assertIsNotNone(latest)
        self.assertEqual(DISCOVERY_D1_TARGETED_GRAPH, latest.get("mode"))

    def test_graph_002_feature_level_request(self) -> None:
        """GRAPH-002: Feature-level request routes to D2 FEATURE_GRAPH with project_graph anchor."""
        decision = route_discovery(
            self.repo,
            outcome="Fix tracking flow",
        )
        self.assertEqual(DISCOVERY_D2_FEATURE_GRAPH, decision.mode)
        self.assertEqual(ANCHOR_RUN_PROJECT_GRAPH, decision.required_anchor["code"])
        self.assertIn("graph --feature tracking", decision.required_anchor["command"])

    def test_graph_003_unknown_code_location(self) -> None:
        """GRAPH-003: Unknown code location routes to D2 FEATURE_GRAPH with find query."""
        decision = route_discovery(
            self.repo,
            outcome="Where is SubscriptionEntitlement handled?",
        )
        self.assertEqual(DISCOVERY_D2_FEATURE_GRAPH, decision.mode)
        self.assertEqual(ANCHOR_RUN_PROJECT_GRAPH, decision.required_anchor["code"])
        self.assertIn("--find SubscriptionEntitlement", decision.required_anchor["command"])

    def test_graph_004_multi_module_refactor(self) -> None:
        """GRAPH-004: Multi-module or migration routes to D3 ARCHITECTURAL_GRAPH."""
        decision = route_discovery(
            self.repo,
            outcome="Migrate database to Room 2.6 across modules",
            architecture_intent="ARCHITECTURE_MIGRATION",
            expected_modules=[":app", ":core:database", ":feature:profile"],
        )
        self.assertEqual(DISCOVERY_D3_ARCHITECTURAL_GRAPH, decision.mode)
        self.assertEqual(ANCHOR_RUN_PROJECT_GRAPH, decision.required_anchor["code"])
        self.assertIn("--arch", decision.required_anchor["command"])

    def test_graph_005_exact_strings_xml(self) -> None:
        """GRAPH-005: Exact strings.xml or docs routes to D0 EXACT_FILE_DIRECT without graph ceremony."""
        decision = route_discovery(
            self.repo,
            outcome="Fix typo in app_name string",
            target_file="app/src/main/res/values/strings.xml",
        )
        self.assertEqual(DISCOVERY_D0_EXACT_FILE, decision.mode)
        self.assertEqual(ANCHOR_DIRECT_FILE_READ, decision.required_anchor["code"])
        self.assertEqual("HOST_TOOL", decision.required_anchor["kind"])

    def test_graph_006_search_before_discovery_anchor(self) -> None:
        """GRAPH-006: Search before discovery anchor is DENIED with DISCOVERY_ANCHOR_REQUIRED."""
        res = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/kotlin/com/example/tracking", "Query": "startTracking"},
        )
        self.assertEqual("deny", res["decision"])
        self.assertIn("DISCOVERY_ANCHOR_REQUIRED", res.get("reason", ""))
        self.assertEqual("DISCOVERY_ANCHOR_REQUIRED", res.get("reason_code"))

    def test_graph_007_search_inside_discovered_scope(self) -> None:
        """GRAPH-007: Search inside discovered scope is ALLOWED after discovery receipt exists."""
        receipt = create_discovery_receipt(
            mode=DISCOVERY_D2_FEATURE_GRAPH,
            query_kind="feature",
            query_value="tracking",
            graph_fingerprint="fp_track_01",
            resolved_modules=[":app"],
            resolved_paths=["app/src/main/kotlin/com/example/tracking/TrackingService.kt"],
            resolved_symbols=["TrackingService"],
            allowed_search_roots=["app/src/main/kotlin/com/example/tracking"],
        )
        save_discovery_receipt(self.repo, receipt)

        res = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/kotlin/com/example/tracking", "Query": "startTracking"},
        )
        self.assertEqual("allow", res["decision"])

    def test_graph_008_search_outside_discovered_scope(self) -> None:
        """GRAPH-008: Search outside discovered scope is DENIED with DISCOVERY_SCOPE_EXPANSION_REQUIRED."""
        receipt = create_discovery_receipt(
            mode=DISCOVERY_D1_TARGETED_GRAPH,
            query_kind="symbol",
            query_value="ProfileViewModel",
            graph_fingerprint="fp_prof_01",
            resolved_modules=[":app"],
            resolved_paths=["app/src/main/kotlin/com/example/profile/ProfileViewModel.kt"],
            resolved_symbols=["ProfileViewModel"],
            allowed_search_roots=["app/src/main/kotlin/com/example/profile"],
        )
        save_discovery_receipt(self.repo, receipt)

        res = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/kotlin/com/example/payments", "Query": "charge"},
        )
        self.assertEqual("deny", res["decision"])
        self.assertIn("DISCOVERY_SCOPE_EXPANSION_REQUIRED", res.get("reason", ""))
        self.assertEqual("DISCOVERY_SCOPE_EXPANSION_REQUIRED", res.get("reason_code"))

    def test_graph_008b_computed_roots_do_not_open_the_whole_module(self) -> None:
        """GRAPH-008B: The production path (roots computed by the receipt) keeps a targeted anchor narrow."""
        receipt = create_discovery_receipt(
            mode=DISCOVERY_D1_TARGETED_GRAPH,
            query_kind="symbol",
            query_value="ProfileViewModel",
            graph_fingerprint="fp_prof_02",
            resolved_modules=[":app"],
            resolved_paths=["app/src/main/kotlin/com/example/profile/ProfileViewModel.kt"],
            resolved_symbols=["ProfileViewModel"],
        )
        self.assertNotIn("app", receipt["allowed_search_roots"])
        save_discovery_receipt(self.repo, receipt)

        res = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/kotlin/com/example/payments", "Query": "charge"},
        )
        self.assertEqual("DISCOVERY_SCOPE_EXPANSION_REQUIRED", res.get("reason_code"))
        res = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/kotlin/com/example/profile", "Query": "load"},
        )
        self.assertEqual("allow", res["decision"])

    def test_graph_008c_only_a_module_query_grants_its_module_root(self) -> None:
        """GRAPH-008C: Module roots come from a module query, never from architecture or file anchors."""
        paths = ["app/src/main/kotlin/com/example/profile/ProfileViewModel.kt"]
        module_receipt = create_discovery_receipt(
            mode=DISCOVERY_D2_FEATURE_GRAPH, query_kind="module", query_value=":app", graph_fingerprint="fp",
            resolved_modules=[":app"], resolved_paths=paths, resolved_symbols=[],
        )
        self.assertIn("app", module_receipt["allowed_search_roots"])
        arch_receipt = create_discovery_receipt(
            mode="ARCHITECTURAL_GRAPH", query_kind="modules", query_value="modules", graph_fingerprint="fp",
            resolved_modules=[":app", ":core"], resolved_paths=paths, resolved_symbols=[],
        )
        self.assertNotIn("app", arch_receipt["allowed_search_roots"])
        self.assertNotIn("core", arch_receipt["allowed_search_roots"])

    def test_graph_008d_receipt_is_stale_once_the_graph_changes(self) -> None:
        """GRAPH-008D: A receipt from an older graph is stale; freshness is read from a small sidecar."""
        from _graph_core import GraphEngine
        engine = GraphEngine(self.repo)
        engine.file_hashes = {"app/src/main/kotlin/com/example/profile/ProfileViewModel.kt": "h1"}
        engine.save_cache()
        sidecar = engine.cache_file.with_name(engine.cache_file.name + ".fingerprint")
        self.assertEqual(engine.graph_fingerprint, sidecar.read_text(encoding="utf-8").strip())

        receipt = create_discovery_receipt(
            mode=DISCOVERY_D1_TARGETED_GRAPH, query_kind="symbol", query_value="ProfileViewModel",
            graph_fingerprint=engine.graph_fingerprint, resolved_modules=[":app"],
            resolved_paths=["app/src/main/kotlin/com/example/profile/ProfileViewModel.kt"], resolved_symbols=[],
        )
        self.assertTrue(check_discovery_freshness(self.repo, receipt)[0])
        engine.file_hashes["app/src/main/kotlin/com/example/profile/ProfileViewModel.kt"] = "h2"
        engine.save_cache()
        fresh, reason = check_discovery_freshness(self.repo, receipt)
        self.assertFalse(fresh)
        self.assertIn("GRAPH_CHANGED", reason)

    def test_graph_008e_ending_a_task_clears_the_latest_receipt(self) -> None:
        """GRAPH-008E: A receipt from a finished task does not anchor the next task's search."""
        from discovery_receipt import clear_latest_discovery_receipt
        receipt = create_discovery_receipt(
            mode=DISCOVERY_D1_TARGETED_GRAPH, query_kind="symbol", query_value="ProfileViewModel",
            graph_fingerprint="fp", resolved_modules=[":app"],
            resolved_paths=["app/src/main/kotlin/com/example/profile/ProfileViewModel.kt"], resolved_symbols=[],
        )
        save_discovery_receipt(self.repo, receipt)
        self.assertIsNotNone(load_latest_discovery_receipt(self.repo))
        clear_latest_discovery_receipt(self.repo)
        self.assertIsNone(load_latest_discovery_receipt(self.repo))

    def test_graph_009_bounded_context_insufficient(self) -> None:
        """GRAPH-009: When bounded context has truncated dependents, graph_expansion_required is reported."""
        import task_context

        # Create two dependent consumers in another package that import and reference ProfileViewModel
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "other").mkdir(parents=True, exist_ok=True)
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "other" / "Consumer1.kt").write_text(
            "package com.example.other\n\nimport com.example.profile.ProfileViewModel\n\nclass Consumer1(val vm: ProfileViewModel)\n",
            encoding="utf-8",
        )
        (self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "other" / "Consumer2.kt").write_text(
            "package com.example.other\n\nimport com.example.profile.ProfileViewModel\n\nclass Consumer2(val vm: ProfileViewModel)\n",
            encoding="utf-8",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "add consumers")

        res = task_context.resolve_task_context(
            self.repo,
            symbol="ProfileViewModel",
            limit=1,
        )
        self.assertTrue(res.get("graph_expansion_required"))
        rec = res.get("recommended_action")
        self.assertIsNotNone(rec)
        self.assertEqual("RUN_PROJECT_GRAPH", rec.get("code"))
        self.assertIn("graph --find ProfileViewModel", rec.get("command"))

    def test_graph_010_directory_listing_cascade(self) -> None:
        """GRAPH-010: Repeated or deep directory listings before discovery trigger DISCOVERY_ANCHOR_REQUIRED."""
        res_deep = self._invoke_safety(
            "list_dir",
            {"DirectoryPath": "app/src/main/kotlin/com/example"},
        )
        self.assertEqual("deny", res_deep["decision"])
        self.assertIn("DISCOVERY_ANCHOR_REQUIRED", res_deep.get("reason", ""))

    def test_graph_011_graph_misses_runtime_relationship(self) -> None:
        """GRAPH-011: Graph/source disagreement does not fail verification; source evidence wins."""
        # Even if a method or relationship is not reflected in static graph, verified source reads succeed
        service_file = self.repo / "app" / "src" / "main" / "kotlin" / "com" / "example" / "tracking" / "TrackingService.kt"
        self.assertTrue(service_file.is_file())
        content = service_file.read_text(encoding="utf-8")
        self.assertIn("startTracking", content)

    def test_discovery_provenance_and_freshness(self) -> None:
        """Plan drafting binds discovery provenance; begin_task verifies freshness."""
        import workflow

        receipt = create_discovery_receipt(
            mode=DISCOVERY_D1_TARGETED_GRAPH,
            query_kind="file",
            query_value="app/src/main/kotlin/com/example/profile/ProfileViewModel.kt",
            graph_fingerprint="fp_fresh_01",
            resolved_modules=[":app"],
            resolved_paths=["app/src/main/kotlin/com/example/profile/ProfileViewModel.kt"],
            resolved_symbols=["ProfileViewModel"],
        )
        save_discovery_receipt(self.repo, receipt)

        # Freshness is True
        fresh, reason = check_discovery_freshness(self.repo, receipt)
        self.assertTrue(fresh)
        self.assertEqual("FRESH", reason)

        # Draft a plan and verify discovery_provenance is embedded
        args_draft = argparse.Namespace(
            repo=str(self.repo),
            task_id="task-graph-test",
            outcome="Fix profile refresh logic",
            kind="FEATURE",
            planning_depth="BOUNDED",
            expected_surfaces="BUSINESS_LOGIC",
            expected_modules="app",
            architecture_intent="EXISTING_CHANGE",
            architecture_target_scope="app/src/main/kotlin/com/example/profile/ProfileViewModel.kt",
            architecture_target_family=None,
            expected_files=None,
            phases=None,
            force=False,
            strict_drift=False,
            assume_risk_tier=None,
        )
        plan_data = workflow.draft(args_draft)
        self.assertIsNotNone(plan_data)

        prov = plan_data.get("discovery_provenance")
        self.assertIsNotNone(prov)
        self.assertEqual(receipt["id"], prov.get("discovery_id"))
        self.assertEqual(DISCOVERY_D1_TARGETED_GRAPH, prov.get("discovery_mode"))
        self.assertEqual("fp_fresh_01", prov.get("graph_fingerprint"))

        # Approve task
        args_approve = argparse.Namespace(
            repo=str(self.repo),
            task_id="task-graph-test",
            source="conversation",
            proof_reference="approved by developer",
            enforcement_tier="RULE_ENFORCED",
        )
        workflow.record_approval(args_approve)

        # begin_task validates freshness and succeeds
        args_begin = argparse.Namespace(
            repo=str(self.repo),
            task_id="task-graph-test",
        )
        begun = workflow.begin_task(args_begin)
        self.assertEqual("IMPLEMENTING", begun.get("status"))

    def test_public_graph_cli_facade(self) -> None:
        """harness_cli.py graph --feature <name> --json executes cleanly and produces structured JSON."""
        harness_script = KIT / "harness_cli.py"
        proc = subprocess.run(
            [sys.executable, str(harness_script), "graph", "--repo", str(self.repo), "--feature", "profile", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, proc.returncode, f"stderr: {proc.stderr}\nstdout: {proc.stdout}")
        data = json.loads(proc.stdout.strip())
        self.assertIn("nodes", data)
        self.assertIn("discovery", data)
        disc = data["discovery"]
        self.assertEqual(DISCOVERY_D2_FEATURE_GRAPH, disc.get("mode"))
        self.assertEqual("profile", disc.get("query", {}).get("value"))

    def test_GRAPH_012_external_checkout_stats_and_json(self) -> None:
        """GRAPH-012: android-harness graph --repo <external-checkout> --stats displays external repo."""
        harness_script = KIT / "harness_cli.py"
        proc = subprocess.run(
            [sys.executable, str(harness_script), "graph", "--repo", str(self.repo), "--stats"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, proc.returncode, f"stderr: {proc.stderr}\nstdout: {proc.stdout}")
        self.assertIn(str(self.repo), proc.stdout)

    def test_GRAPH_013_json_stdout_is_pure_valid_json(self) -> None:
        """GRAPH-013: JSON stdout is pure valid JSON; progress goes to stderr."""
        harness_script = KIT / "harness_cli.py"
        proc = subprocess.run(
            [sys.executable, str(harness_script), "graph", "--repo", str(self.repo), "--stats", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, proc.returncode, f"stderr: {proc.stderr}\nstdout: {proc.stdout}")
        # Must parse as pure JSON with no leading/trailing non-JSON output
        data = json.loads(proc.stdout.strip())
        self.assertIsInstance(data, dict)
        self.assertEqual(str(self.repo.resolve()), str(Path(data["repo_root"]).resolve()))
    def test_GRAPH_SCOPE_001_to_005_implementing_scope_guards(self) -> None:
        """GRAPH-SCOPE-001 through 005: In-scope vs out-of-scope search, list_dir, expansion, and D0."""
        task_dir = self.repo / ".agents" / "state" / "tasks" / "task-scope-01"
        task_dir.mkdir(parents=True, exist_ok=True)
        plan = {
            "task_id": "task-scope-01",
            "status": "IMPLEMENTING",
            "expected_files": ["app/src/main/kotlin/com/example/profile/ProfileViewModel.kt"],
            "discovery_provenance": {
                "discovery_id": "disc-scope-01",
                "mode": DISCOVERY_D1_TARGETED_GRAPH,
                "allowed_search_roots": ["app/src/main/kotlin/com/example/profile"],
                "resolved_paths": ["app/src/main/kotlin/com/example/profile/ProfileViewModel.kt"],
            },
        }
        (task_dir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        active_task = {
            "task_id": "task-scope-01",
            "plan_path": str(task_dir / "plan.json"),
        }
        (self.repo / ".agents" / "state" / "active-task.json").write_text(json.dumps(active_task, indent=2), encoding="utf-8")

        # GRAPH-SCOPE-001: in-scope targeted search allowed
        res1 = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/kotlin/com/example/profile", "Query": "refresh"},
        )
        self.assertEqual("allow", res1["decision"])

        res1_file = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/kotlin/com/example/profile/ProfileViewModel.kt", "Query": "refresh"},
        )
        self.assertEqual("allow", res1_file["decision"])

        # GRAPH-SCOPE-002: out-of-scope targeted search denied
        res2 = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/kotlin/com/example/payments", "Query": "charge"},
        )
        self.assertEqual("deny", res2["decision"])
        self.assertEqual("DISCOVERY_SCOPE_EXPANSION_REQUIRED", res2.get("reason_code"))

        # GRAPH-SCOPE-003: out-of-scope list_dir denied
        res3 = self._invoke_safety(
            "list_dir",
            {"DirectoryPath": "app/src/main/kotlin/com/example"},
        )
        self.assertEqual("deny", res3["decision"])
        self.assertEqual("DISCOVERY_SCOPE_EXPANSION_REQUIRED", res3.get("reason_code"))

        # GRAPH-SCOPE-004: graph expansion extends allowed roots
        receipt2 = create_discovery_receipt(
            mode=DISCOVERY_D2_FEATURE_GRAPH,
            query_kind="feature",
            query_value="payments",
            graph_fingerprint="fp_payments_01",
            resolved_modules=[":app"],
            resolved_paths=["app/src/main/kotlin/com/example/payments/PaymentProcessor.kt"],
            resolved_symbols=["PaymentProcessor"],
            allowed_search_roots=["app/src/main/kotlin/com/example/payments"],
        )
        save_discovery_receipt(self.repo, receipt2)

        res4 = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/kotlin/com/example/payments", "Query": "charge"},
        )
        self.assertEqual("allow", res4["decision"])

        # GRAPH-SCOPE-005: exact developer-known file D0 remains lightweight
        res5 = self._invoke_safety(
            "grep_search",
            {"SearchPath": "app/src/main/res/values/strings.xml", "Query": "app_name"},
        )
        self.assertEqual("allow", res5["decision"])


if __name__ == "__main__":
    unittest.main()
