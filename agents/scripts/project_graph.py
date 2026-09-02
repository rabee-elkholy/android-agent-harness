"""Project Architecture & Dependency Graph CLI Tool.

Usage:
    python .agents/scripts/project_graph.py [options]

Commands & Filters:
    --modules               Analyze and display Gradle module dependency DAG
    --arch                  Analyze and display Clean Architecture layers (UI->VM->Domain->Data)
    --screens               List UI screens, layouts, and their associated ViewModels
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
    parser.add_argument("--feature", metavar="NAME", help="Analyze and display complete Clean Architecture slice for a feature")
    parser.add_argument("--find", metavar="SYMBOL", help="Find symbol/class/screen and its dependencies")
    parser.add_argument("--module", metavar="NAME", help="Focus graph on a specific Gradle module (e.g. :core:data)")
    parser.add_argument("--screen", metavar="NAME", help="Focus graph on a specific screen/composable")
    parser.add_argument("--depth", type=int, default=2, help="Traversal depth around focus node (default: 2)")
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
    parser.add_argument("--stats", action="store_true", help="Display graph cache statistics")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    enable_line_buffered_stdio()
    args = parse_args(argv)

    engine = GraphEngine(REPO)
    sync_res = engine.sync(force_full=args.sync)

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

    focus_node_id: str | None = None
    graph_to_render = engine.graph

    # Handle --feature query
    if args.feature:
        sub_nodes, sub_edges = engine.graph.extract_feature_graph(args.feature, max_depth=args.depth)
        if not sub_nodes:
            live_print(f"[!] No feature components found matching '{args.feature}'.")
            return 1
        live_print(engine.graph.to_slice_summary(sub_nodes))
        from _graph_core import DependencyGraph
        sub_g = DependencyGraph()
        for sn in sub_nodes.values():
            sub_g.add_node(sn)
        for se in sub_edges:
            sub_g.add_edge(se.source, se.target, kind=se.kind)
        graph_to_render = sub_g

    # Handle --find query with self-healing and multi-match
    elif args.find:
        matches = engine.graph.find_nodes(args.find)
        if not matches:
            node, heal_msg = engine.heal_symbol(args.find)
            if heal_msg:
                live_print(f"[*] {heal_msg}")
            if not node:
                live_print(f"[!] Symbol '{args.find}' not found in code graph.")
                return 1
            focus_node_id = node.id
        elif len(matches) == 1:
            focus_node_id = matches[0].id
        else:
            # Multi-match query: extract unified subgraph across all matching nodes
            start_ids = [m.id for m in matches[:15]]
            sub_nodes, sub_edges = engine.graph.extract_subgraph(start_ids, max_depth=args.depth, direction="both")
            live_print(engine.graph.to_slice_summary(sub_nodes))
            from _graph_core import DependencyGraph
            sub_g = DependencyGraph()
            for sn in sub_nodes.values():
                sub_g.add_node(sn)
            for se in sub_edges:
                sub_g.add_edge(se.source, se.target, kind=se.kind)
            graph_to_render = sub_g

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

    # Format output
    output_text = ""
    if args.format == "compact":
        output_text = graph_to_render.to_compact(focus_id=focus_node_id, max_depth=args.depth)
    elif args.format == "mermaid":
        output_text = graph_to_render.to_mermaid(title="Android Project Code Graph")
    elif args.format == "dot":
        output_text = graph_to_render.to_dot(title="Android Project Code Graph")
    elif args.format == "json":
        output_text = json.dumps(graph_to_render.to_dict(), indent=2, ensure_ascii=False)

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
