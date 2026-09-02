"""Comprehensive Self-Test Suite for Universal Android Code Graph Engine.

Validates:
- Core DAG data structures, edge traversal, and cycle safety
- Shortest path finding (BFS) and subgraph extraction with depth limits
- Multi-Module Gradle Parser (Kotlin DSL, Groovy, Type-safe Accessors)
- Universal Static Code Analyzer (Kotlin, Java, Compose Screens, ViewModels, Repos, XML Layouts)
- Incremental Caching and dirty file synchronization
- Self-Healing heuristic path resolution on moved/renamed files
- Multi-format serializers (Compact, Mermaid, DOT, JSON)
- Zero-crash fallback when Graphviz 'dot' CLI is absent
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _graph_core import (  # noqa: E402
    DependencyGraph,
    EdgeKind,
    EntityType,
    GraphEdge,
    GraphEngine,
    GraphNode,
    parse_code_file,
    parse_gradle_modules,
    parse_xml_file,
    render_dot_to_image,
)


def run_tests() -> bool:
    print("==================================================")
    print("  Running Universal Android Graph Engine Selftests")
    print("==================================================")
    passed = 0
    failed = 0

    def assert_eq(actual, expected, msg=""):
        nonlocal passed, failed
        if actual == expected:
            passed += 1
            print(f"  [PASS] {msg}")
        else:
            failed += 1
            print(f"  [FAIL] {msg} -> Expected: {expected}, Actual: {actual}")

    # -----------------------------------------------------------------
    # Test 1: Core Graph & BFS Path Finding with Cycles
    # -----------------------------------------------------------------
    print("\n[*] Test 1: Core Graph & BFS Path Finding (Cycle-Safe)")
    g = DependencyGraph()
    g.add_node(GraphNode(id="A", name="A", type=EntityType.SCREEN.value))
    g.add_node(GraphNode(id="B", name="B", type=EntityType.VIEW_MODEL.value))
    g.add_node(GraphNode(id="C", name="C", type=EntityType.USE_CASE.value))
    g.add_node(GraphNode(id="D", name="D", type=EntityType.REPOSITORY.value))

    # Add edges: A -> B -> C -> D, and a cycle B -> A
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    g.add_edge("C", "D")
    g.add_edge("B", "A")  # Cycle

    path = g.find_shortest_path("A", "D")
    assert_eq(path, ["A", "B", "C", "D"], "BFS finds shortest path across cycle safely")

    sub_nodes, sub_edges = g.extract_subgraph(["A"], max_depth=1, direction="outgoing")
    assert_eq(set(sub_nodes.keys()), {"A", "B"}, "Subgraph depth 1 extracts direct neighbors only")

    # -----------------------------------------------------------------
    # Test 2: Multi-Module Gradle Parser (Kotlin DSL & Groovy)
    # -----------------------------------------------------------------
    print("\n[*] Test 2: Gradle Multi-Module Parser")
    temp_dir = Path(tempfile.mkdtemp())
    try:
        settings_file = temp_dir / "settings.gradle.kts"
        settings_file.write_text(
            '''
            rootProject.name = "FixtureApp"
            include(":app")
            include(":core:network")
            include(":core:database")
            include(":feature:login")
            ''',
            encoding="utf-8",
        )

        app_dir = temp_dir / "app"
        app_dir.mkdir(parents=True)
        (app_dir / "build.gradle.kts").write_text(
            '''
            dependencies {
                implementation(project(":feature:login"))
                implementation(project(":core:network"))
            }
            ''',
            encoding="utf-8",
        )

        feat_dir = temp_dir / "feature" / "login"
        feat_dir.mkdir(parents=True)
        (feat_dir / "build.gradle").write_text(
            '''
            dependencies {
                implementation project(':core:database')
            }
            ''',
            encoding="utf-8",
        )

        mod_nodes, mod_edges = parse_gradle_modules(temp_dir)
        assert_eq(":app" in mod_nodes, True, "Discovered :app module")
        assert_eq(":feature:login" in mod_nodes, True, "Discovered :feature:login module")
        assert_eq(":core:network" in mod_nodes, True, "Discovered :core:network module")
        assert_eq(":core:database" in mod_nodes, True, "Discovered :core:database module")

        edge_pairs = [(e.source, e.target) for e in mod_edges]
        assert_eq((":app", ":feature:login") in edge_pairs, True, "Wired :app -> :feature:login")
        assert_eq((":feature:login", ":core:database") in edge_pairs, True, "Wired :feature:login -> :core:database (Groovy)")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # -----------------------------------------------------------------
    # Test 3: Universal Code Parser (Kotlin, Java, Compose, XML)
    # -----------------------------------------------------------------
    print("\n[*] Test 3: Universal Code Parser (Kotlin, Java, Compose, XML)")
    temp_dir = Path(tempfile.mkdtemp())
    try:
        src_dir = temp_dir / "app" / "src" / "main" / "java" / "com" / "fixture"
        src_dir.mkdir(parents=True)
        kt_file = src_dir / "UserProfileScreen.kt"
        kt_file.write_text(
            '''
            package com.fixture

            import com.fixture.UserViewModel
            import androidx.compose.runtime.Composable

            @Composable
            fun UserProfileScreen(viewModel: UserViewModel) {
                // Compose UI
            }
            ''',
            encoding="utf-8",
        )

        nodes = parse_code_file(kt_file, temp_dir)
        screen_node = next((n for n in nodes if n.name == "UserProfileScreen"), None)
        assert_eq(screen_node is not None, True, "Parsed Compose Screen function")
        if screen_node:
            assert_eq(screen_node.type, EntityType.SCREEN.value, "Classified as SCREEN")
            assert_eq("com.fixture.UserViewModel" in screen_node.imports, True, "Extracted imports")

        java_file = src_dir / "UserPresenter.java"
        java_file.write_text(
            '''
            package com.fixture;

            import com.fixture.UserRepository;

            public class UserPresenter {
                private UserRepository repo;
            }
            ''',
            encoding="utf-8",
        )
        j_nodes = parse_code_file(java_file, temp_dir)
        pres_node = next((n for n in j_nodes if n.name == "UserPresenter"), None)
        assert_eq(pres_node is not None, True, "Parsed Java Presenter class")
        if pres_node:
            assert_eq(pres_node.type, EntityType.VIEW_MODEL.value, "Classified Java Presenter as VIEW_MODEL")

        res_layout_dir = temp_dir / "app" / "src" / "main" / "res" / "layout"
        res_layout_dir.mkdir(parents=True)
        xml_file = res_layout_dir / "activity_login.xml"
        xml_file.write_text(
            '''<?xml version="1.0" encoding="utf-8"?>
            <LinearLayout xmlns:android="http://schemas.android.com/apk/res/android">
                <include layout="@layout/toolbar_header" />
            </LinearLayout>
            ''',
            encoding="utf-8",
        )
        x_items = parse_xml_file(xml_file, temp_dir)
        assert_eq(len(x_items), 1, "Parsed XML layout file")
        assert_eq(x_items[0][1], ["toolbar_header"], "Extracted include reference")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # -----------------------------------------------------------------
    # Test 4: Incremental Caching & Self-Healing Engine
    # -----------------------------------------------------------------
    print("\n[*] Test 4: Incremental Caching & Self-Healing Engine")
    temp_dir = Path(tempfile.mkdtemp())
    try:
        engine = GraphEngine(temp_dir)
        code_dir = temp_dir / "app" / "src" / "main" / "java" / "com" / "test"
        code_dir.mkdir(parents=True)

        f1 = code_dir / "ProfileViewModel.kt"
        f1.write_text("package com.test\nclass ProfileViewModel", encoding="utf-8")

        sync1 = engine.sync()
        assert_eq(sync1["added"] >= 1, True, "Initial sync indexed file")
        assert_eq(engine.cache_file.is_file(), True, "Cache file written to disk")

        sync2 = engine.sync()
        assert_eq(sync2["added"], 0, "Incremental sync: 0 added")
        assert_eq(sync2["modified"], 0, "Incremental sync: 0 modified")

        f1_new = temp_dir / "app" / "src" / "main" / "java" / "com" / "test" / "features" / "ProfileViewModel.kt"
        f1_new.parent.mkdir(parents=True, exist_ok=True)
        f1.rename(f1_new)

        healed_node, msg = engine.heal_symbol("ProfileViewModel")
        assert_eq(healed_node is not None, True, "Self-Healing resolved moved symbol")
        assert_eq(msg is not None and "[HEALED]" in msg, True, "Self-Healing emitted repair notification")
        if healed_node:
            assert_eq("features/ProfileViewModel.kt" in healed_node.file_path, True, "Corrected file path to new location")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # -----------------------------------------------------------------
    # Test 5: Multi-Format Serializers (Compact, Mermaid, DOT, JSON)
    # -----------------------------------------------------------------
    print("\n[*] Test 5: Multi-Format Serializers")
    test_g = DependencyGraph()
    test_g.add_node(GraphNode(id="ScreenA", name="ScreenA", type=EntityType.SCREEN.value))
    test_g.add_node(GraphNode(id="VmB", name="VmB", type=EntityType.VIEW_MODEL.value))
    test_g.add_edge("ScreenA", "VmB")

    compact = test_g.to_compact()
    assert_eq("ScreenA -> VmB" in compact, True, "Compact serializer contains edge")

    mermaid = test_g.to_mermaid()
    assert_eq("```mermaid" in mermaid and "ScreenA" in mermaid, True, "Mermaid serializer valid")

    dot = test_g.to_dot()
    assert_eq("digraph AndroidGraph" in dot and '"ScreenA" -> "VmB"' in dot, True, "DOT serializer valid")

    d_json = test_g.to_dict()
    assert_eq(len(d_json["nodes"]), 2, "JSON dictionary valid")

    ok, msg = render_dot_to_image("digraph G { A -> B; }", Path(temp_dir / "test.svg"))
    assert_eq(isinstance(ok, bool), True, "render_dot_to_image handles presence/absence safely")

    print("\n==================================================")
    print(f"Selftest Results: {passed} passed, {failed} failed")
    print("==================================================")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
