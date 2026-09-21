"""Project Architecture & Dependency Graph CLI Tool.

Usage:
    python .agents/scripts/project_graph.py [options]

Commands & Filters:
    --modules               Analyze and display Gradle module dependency DAG
    --arch                  Analyze and display Clean Architecture layers (UI->VM->Domain->Data)
    --screens               List UI screens, layouts, and their associated ViewModels
    --features              List all detected feature modules and packages with component counts
    --feature <name>        Analyze and display complete Clean Architecture slice for a feature
    --string <text>         Find UI string in strings.xml (values-*/) and trace associated screens
    --find <symbol>         Find specific class, screen, or symbol with its layer dependencies
    --module <name>         Filter graph around a specific module (e.g. :feature:auth)
    --screen <name>         Filter graph around a specific screen (e.g. LoginScreen)
    --depth <N>             Limit traversal depth around focus node (default: 2)
    --path-from <A> --path-to <B>
                            Find shortest architectural dependency path between two components

Output & Formatting:
    --format {compact,mermaid,dot,json}
                            Output representation format (default: compact)
    --render {svg,png}      Render visual image using system Graphviz CLI (dot) if available
    --output <path>         Write output directly to a file
    --sync                  Force full resynchronization of the code graph cache
    --stats                 Display cache statistics, node counts, and healed paths
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _graph_core import (  # noqa: E402
    REPO,
    EntityType,
    GraphEngine,
    render_dot_to_image,
)
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Universal Android Code & Architecture Graph CLI")
    parser.add_argument("--modules", action="store_true", help="Display Gradle module dependency graph")
    parser.add_argument("--arch", action="store_true", help="Display full Clean Architecture layers graph")
    parser.add_argument("--screens", action="store_true", help="List UI screens/layouts and associated ViewModels")
    parser.add_argument("--features", action="store_true", help="List all detected feature modules and packages with component counts")
    parser.add_argument("--string", "--ui-text", dest="string_query", metavar="TEXT", help="Find UI string resource in strings.xml and trace associated screens and layouts")
    parser.add_argument("--harness", "--tools", dest="harness", action="store_true", help="Display Harness tools, scripts, workflows, and subagents directory")
    parser.add_argument("--feature", metavar="NAME", help="Analyze and display complete Clean Architecture slice for a feature")
    parser.add_argument("--find", metavar="SYMBOL", help="Find symbol/class/screen/tool and its dependencies")
    parser.add_argument("--module", metavar="NAME", help="Focus graph on a specific Gradle module (e.g. :core:data)")
    parser.add_argument("--screen", metavar="NAME", help="Focus graph on a specific screen/composable")
    parser.add_argument("--depth", type=int, default=2, help="Traversal depth around focus node (default: 2)")
    parser.add_argument("--limit", type=int, default=80, help="Maximum nodes rendered for broad feature queries (default: 80; 0 disables cap)")
    parser.add_argument("--path-from", metavar="NODE_A", help="Starting node for shortest path search")
    parser.add_argument("--path-to", metavar="NODE_B", help="Target node for shortest path search")
    parser.add_argument(
        "--format",
        choices=("compact", "mermaid", "dot", "json"),
        default="compact",
        help="Output format (default: compact)",
    )
    parser.add_argument("--render", choices=("svg", "png"), help="Render image using system Graphviz CLI (dot)")
    parser.add_argument("--output", metavar="PATH", help="Write output to a specified file")
    parser.add_argument("--sync", action="store_true", help="Force full cache resynchronization")
    parser.add_argument("--repo", default=None, help="Android/KMP project root (default: auto-discover)")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON (alias for --format json)")
    parser.add_argument("--stats", action="store_true", help="Display graph cache statistics")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    enable_line_buffered_stdio()
    args = parse_args(argv)
    if args.json:
        args.format = "json"
    is_json = (args.format == "json")

    repo_root = Path(args.repo).resolve() if args.repo else REPO
    engine = GraphEngine(repo_root)
    if args.sync:
        live_print("[*] Rebuilding complete universal code graph from disk...", err=is_json)
    sync_res = engine.sync(force_full=args.sync)
    if sync_res.get("added") or sync_res.get("modified") or sync_res.get("deleted"):
        live_print(
            f"[*] Incremental code graph sync: +{sync_res['added']} added, ~{sync_res['modified']} modified, -{sync_res['deleted']} deleted files.",
            err=is_json,
        )

    if args.stats:
        live_print("==================================================")
        live_print("  Android Project Graph Statistics")
        live_print("==================================================")
        live_print(f"[*] Repository: {REPO}")
        live_print(f"[*] Total Nodes: {sync_res['total_nodes']}")
        live_print(f"[*] Total Edges: {sync_res['total_edges']}")
        live_print(f"[*] Added Files (Sync): {sync_res['added']}")
        live_print(f"[*] Modified Files (Sync): {sync_res['modified']}")
        live_print(f"[*] Deleted Files (Sync): {sync_res['deleted']}")
        if engine.healed_log:
            live_print("\n[*] Self-Healing History:")
            for h in engine.healed_log:
                live_print(f"  - {h}")
        return 0

    if args.harness:
        live_print(engine.graph.to_harness_inventory())
        return 0

    if args.features:
        live_print(engine.graph.to_features_summary())
        return 0

    if args.string_query:
        output = engine.dereference_string(args.string_query)
        live_print(output)
        return 0

    focus_node_id: str | None = None
    graph_to_render = engine.graph

    # Handle --feature query
    if args.feature:
        sub_nodes, sub_edges = engine.graph.extract_feature_graph(args.feature, max_depth=args.depth)
        if not sub_nodes:
            live_print(f"[!] No feature components found matching '{args.feature}'.")
            return 1
        original_count = len(sub_nodes)
        if args.limit > 0 and original_count > args.limit:
            query = args.feature.lower()
            ranked = sorted(
                sub_nodes.values(),
                key=lambda node: (
                    0 if query in node.name.lower() or query in node.file_path.lower() else 1,
                    0 if node.type in {EntityType.SCREEN.value, EntityType.VIEW_MODEL.value, EntityType.USE_CASE.value} else 1,
                    node.file_path,
                    node.id,
                ),
            )[:args.limit]
            keep = {node.id for node in ranked}
            sub_nodes = {node.id: node for node in ranked}
            sub_edges = [edge for edge in sub_edges if edge.source in keep and edge.target in keep]
            if not is_json:
                live_print(f"[*] Feature graph bounded to {len(sub_nodes)} of {original_count} nodes; use --limit 0 for the full graph.")
        if not is_json:
            live_print(engine.graph.to_slice_summary(sub_nodes))
        from _graph_core import DependencyGraph
        sub_g = DependencyGraph()
        for sn in sub_nodes.values():
            sub_g.add_node(sn)
        for se in sub_edges:
            sub_g.add_edge(se.source, se.target, kind=se.kind)
        graph_to_render = sub_g

    # Handle --find query with self-healing, rich match details, and ranked symbol discovery
    elif args.find:
        exact_matches, partial_matches = engine.graph.find_nodes_partitioned(args.find, limit=15)
        if not exact_matches and not partial_matches:
            node, heal_msg = engine.heal_symbol(args.find)
            if heal_msg:
                live_print(f"[*] {heal_msg}")
            if not node:
                live_print(f"[!] Symbol '{args.find}' not found in code graph.")
                live_print("[*] Tip: '--find' searches code AST symbols (classes, methods, composables). For feature packages use '--feature <name>', or for UI string resources use '--string <text>'.")
                return 1
            exact_matches = [node]

        if not is_json:
            if exact_matches:
                live_print(f"[*] Exact Matches ({len(exact_matches)}):")
                for m in exact_matches:
                    live_print(engine.graph.format_symbol_match(m, query=args.find, match_badge="[EXACT MATCH]"))

            if partial_matches:
                header = (
                    f"\n[*] Partial / Related Matches ({len(partial_matches)}, top 15):"
                    if exact_matches
                    else f"[*] Partial Matches ({len(partial_matches)}, top 15):"
                )
                live_print(header)
                for m in partial_matches:
                    live_print(engine.graph.format_symbol_match(m, query=args.find, match_badge="[PARTIAL MATCH]"))

        if len(exact_matches) == 1:
            focus_node_id = exact_matches[0].id
        elif not exact_matches and len(partial_matches) == 1:
            focus_node_id = partial_matches[0].id
        else:
            if len(exact_matches) > 1:
                live_print("\n[*] Multiple exact matches found across modules. Specify module or use 'task-context --file <path>'.")
            else:
                live_print("\n[*] Tip: Multiple partial matches found. Specify the exact symbol with '--find <ExactSymbol>' to view its dependency graph.")
            return 0

    # Handle --screen query
    elif args.screen:
        node, heal_msg = engine.heal_symbol(args.screen)
        if heal_msg:
            live_print(f"[*] {heal_msg}")
        if not node:
            live_print(f"[!] Screen '{args.screen}' not found in code graph.")
            return 1
        focus_node_id = node.id

    # Handle --module query
    elif args.module:
        mod_name = args.module if args.module.startswith(":") else f":{args.module}"
        node = engine.graph.find_node(mod_name)
        if not node:
            live_print(f"[!] Module '{mod_name}' not found in Gradle settings.")
            return 1
        focus_node_id = node.id

    # Handle --path-from / --path-to
    if bool(args.path_from) != bool(args.path_to):
        live_print("[!] Both --path-from and --path-to must be specified together for path search.")
        return 1

    if args.path_from and args.path_to:
        path = engine.graph.find_shortest_path(args.path_from, args.path_to)
        if not path:
            live_print(f"[-] No architectural dependency path found between '{args.path_from}' and '{args.path_to}'.")
            return 0
        live_print(f"[*] Dependency Path ({len(path)-1} hops):")
        live_print(" -> ".join(path))
        return 0

    # Handle --screens list
    if args.screens:
        screens = [n for n in engine.graph.nodes.values() if n.type in (EntityType.SCREEN.value, EntityType.XML_LAYOUT.value)]
        live_print(f"[*] UI Screens and Layouts ({len(screens)}):")
        for sc in sorted(screens, key=lambda x: x.name):
            mod_tag = f"[{sc.module}]" if sc.module else ""
            targets = [engine.graph.nodes[t].name for t in engine.graph.get_targets(sc.id) if t in engine.graph.nodes]
            deps_str = f" -> {', '.join(targets)}" if targets else ""
            live_print(f"  - {sc.name} ({sc.type}) {mod_tag}{deps_str}")
        return 0

    # Filter by graph view
    if args.modules and not focus_node_id and not args.feature and not args.find:
        # Filter to only module nodes
        mod_nodes = {nid: n for nid, n in engine.graph.nodes.items() if n.type == EntityType.MODULE.value}
        mod_edges = [e for e in engine.graph.edges if e.source in mod_nodes and e.target in mod_nodes]
        from _graph_core import DependencyGraph
        sub_g = DependencyGraph()
        for mn in mod_nodes.values():
            sub_g.add_node(mn)
        for me in mod_edges:
            sub_g.add_edge(me.source, me.target, kind=me.kind)
        graph_to_render = sub_g

    # Build and save discovery receipt for any structured graph query
    receipt = None
    query_kind = ""
    query_val = ""
    mode = "FEATURE_GRAPH"
    if args.feature:
        query_kind = "feature"
        query_val = args.feature
        mode = "FEATURE_GRAPH"
    elif args.find:
        query_kind = "symbol"
        query_val = args.find
        mode = "FEATURE_GRAPH"
    elif args.module:
        query_kind = "module"
        query_val = args.module
        mode = "FEATURE_GRAPH"
    elif args.screen:
        query_kind = "screen"
        query_val = args.screen
        mode = "FEATURE_GRAPH"
    elif args.arch:
        query_kind = "arch"
        query_val = "full"
        mode = "ARCHITECTURAL_GRAPH"
    elif args.modules:
        query_kind = "modules"
        query_val = "dag"
        mode = "ARCHITECTURAL_GRAPH"

    if query_kind:
        res_modules = sorted({n.module for n in graph_to_render.nodes.values() if getattr(n, "module", None)})
        res_paths = sorted({str(n.file_path) for n in graph_to_render.nodes.values() if getattr(n, "file_path", None)})
        res_symbols = sorted({n.name for n in graph_to_render.nodes.values() if getattr(n, "type", None) != EntityType.MODULE.value})
        graph_fp = str(sync_res.get("graph_fingerprint") or getattr(engine, "graph_fingerprint", "") or "")
        try:
            from discovery_receipt import create_discovery_receipt, save_discovery_receipt
            receipt = create_discovery_receipt(
                mode=mode,
                query_kind=query_kind,
                query_value=query_val,
                graph_fingerprint=graph_fp,
                resolved_modules=res_modules,
                resolved_paths=res_paths,
                resolved_symbols=res_symbols,
            )
            save_discovery_receipt(repo_root, receipt)
        except Exception as exc:
            if not is_json:
                live_print(f"[!] Discovery receipt generation failed: {exc}", err=True)

    # Format output
    output_text = ""
    if args.format == "compact":
        output_text = graph_to_render.to_compact(focus_id=focus_node_id, max_depth=args.depth)
    elif args.format == "mermaid":
        output_text = graph_to_render.to_mermaid(title="Android Project Code Graph")
    elif args.format == "dot":
        output_text = graph_to_render.to_dot(title="Android Project Code Graph")
    elif args.format == "json":
        payload = graph_to_render.to_dict()
        if receipt:
            payload["discovery"] = receipt
        output_text = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
        live_print(f"[*] Graph output written to: {out_path}")
    else:
        print(output_text)

    # Optional image rendering via dot
    if args.render:
        dot_str = graph_to_render.to_dot()
        img_out = Path(args.output) if args.output else REPO / ".agents" / "cache" / f"graph.{args.render}"
        ok, msg = render_dot_to_image(dot_str, img_out, img_format=args.render)
        live_print(f"[*] Visual Render: {'[PASS]' if ok else '[INFO]'} {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
