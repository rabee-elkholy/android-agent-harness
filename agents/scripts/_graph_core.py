"""Universal Android Code Graph & Topology Engine.

Zero-dependency, multi-paradigm graph analysis for Android & KMP projects.
Supports:
- Multi-Module Gradle DAG (Groovy, Kotlin DSL, Version Catalogs, Type-Safe Accessors)
- Universal Android Components (Java & Kotlin, XML Layouts & Nav, Compose Screens)
- Clean Architecture Layer Classification (UI -> VM/Presenter -> UseCase -> Repo -> DataSource -> Tests)
- Incremental SHA-256 / mtime Cache
- Self-Healing & Heuristic Path Resolution
- Multi-Format Serializers: Compact (LLM-optimized), Mermaid, Graphviz DOT, JSON
- Optional Graphviz CLI (dot) image rendering (SVG/PNG)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# Resolve repo root relative to scripts location
SCRIPTS_DIR = Path(__file__).resolve().parent
_env_repo = os.environ.get("HARNESS_REPO", "").strip()
REPO = Path(_env_repo).resolve() if _env_repo else SCRIPTS_DIR.parent.parent


class EntityType(str, Enum):
    MODULE = "MODULE"
    SCREEN = "SCREEN"
    VIEW_MODEL = "VIEW_MODEL"
    USE_CASE = "USE_CASE"
    REPOSITORY = "REPOSITORY"
    DATA_SOURCE = "DATA_SOURCE"
    TEST = "TEST"
    XML_LAYOUT = "XML_LAYOUT"
    NAV_GRAPH = "NAV_GRAPH"
    COMPONENT = "COMPONENT"
    HARNESS_TOOL = "HARNESS_TOOL"
    WORKFLOW_PLAYBOOK = "WORKFLOW_PLAYBOOK"
    SUBAGENT_ROSTER = "SUBAGENT_ROSTER"
    UNKNOWN = "UNKNOWN"


class EdgeKind(str, Enum):
    DEPENDS_ON = "DEPENDS_ON"
    CONTAINS = "CONTAINS"
    RENDERS = "RENDERS"
    BINDS = "BINDS"
    NAVIGATES_TO = "NAVIGATES_TO"
    TESTS = "TESTS"


@dataclass
class GraphNode:
    id: str  # Unique identifier, e.g. ":core:network" or "com.app.ui.LoginScreen"
    name: str  # Short human-readable name, e.g. "LoginScreen"
    type: str  # EntityType value
    file_path: str = ""  # Relative path to repo
    module: str = ":app"  # Associated Gradle module
    package: str = ""  # Package name
    declarations: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphNode:
        return cls(**data)


@dataclass
class GraphEdge:
    source: str  # Source node ID
    target: str  # Target node ID
    kind: str = EdgeKind.DEPENDS_ON.value  # EdgeKind value
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphEdge:
        return cls(**data)


# Standard Android Framework, Jetpack & Java/Kotlin root types across ANY Android codebase
FRAMEWORK_ROOT_TYPES = {
    # Android SDK & Jetpack Core
    "Activity",
    "Fragment",
    "ComponentActivity",
    "AppCompatActivity",
    "FragmentActivity",
    "DialogFragment",
    "BottomSheetDialogFragment",
    "Application",
    "Context",
    "ContextWrapper",
    "Service",
    "BroadcastReceiver",
    "ContentProvider",
    "View",
    "ViewGroup",
    "R",
    "BuildConfig",
    # Architecture Components
    "ViewModel",
    "AndroidViewModel",
    # Java/Kotlin standard roots
    "Object",
    "Any",
    "Throwable",
    "Exception",
    "Serializable",
    "Parcelable",
}


def is_hub_or_base_symbol(name: str, fan_in_count: int = 0) -> bool:
    """Universally detects framework roots, generic base classes (Base* / *Base / Abstract*), or high fan-in hubs."""
    if name in FRAMEWORK_ROOT_TYPES:
        return True
    if name.startswith("Base") or name.endswith("Base") or name.startswith("Abstract") or name.endswith("Abstract"):
        return True
    # High fan-in threshold: any symbol imported/depended on by >= 25 classes is a project-level hub
    if fan_in_count >= 25:
        return True
    return False


# Kotlin & Java language specification keywords to ignore in declarations
KOTLIN_RESERVED_DECLARATIONS = {
    "companion",
    "object",
    "val",
    "var",
    "fun",
    "class",
    "interface",
    "get",
    "set",
    "for",
    "in",
    "is",
    "as",
    "when",
    "if",
    "else",
    "return",
    "override",
    "private",
    "public",
    "internal",
    "protected",
    "import",
    "package",
    "where",
    "by",
    "constructor",
    "init",
    "typealias",
    "enum",
    "sealed",
    "data",
    "abstract",
    "open",
    "final",
    "annotation",
    "suspend",
    "inline",
    "value",
    "operator",
    "infix",
    "tailrec",
    "external",
    "const",
    "lateinit",
    "vararg",
    "reified",
    "crossinline",
    "noinline",
    "it",
    "this",
    "super",
    "null",
    "true",
    "false",
}


def strip_comments_and_strings(text: str) -> str:
    """Removes single-line comments, multi-line comments, and string literals for accurate symbol parsing."""
    # Remove multi-line comments /* ... */
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    # Remove single-line comments // ...
    text = re.sub(r"//.*$", " ", text, flags=re.MULTILINE)
    # Remove triple-quoted strings """ ... """
    text = re.sub(r'"""[\s\S]*?"""', '""', text)
    # Remove standard double-quoted strings " ... " (handling escaped quotes)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    return text


# Regex patterns for static parsing
PACKAGE_PATTERN = re.compile(r"^\s*package\s+([a-zA-Z0-9_.]+)", re.MULTILINE)
IMPORT_PATTERN = re.compile(r"^\s*import\s+(?:static\s+)?([a-zA-Z0-9_.*]+)", re.MULTILINE)
DECLARATION_PATTERN = re.compile(
    r"\b(?:class|interface|enum\s+class|sealed\s+class|sealed\s+interface|data\s+class|record)\s+([a-zA-Z0-9_]+)\b"
)
NAMED_OBJECT_PATTERN = re.compile(r"\bobject\s+([a-zA-Z0-9_]+)\b")
COMPOSABLE_FUNC_PATTERN = re.compile(r"@Composable\s+(?:(?:public|private|internal)\s+)?fun\s+([a-zA-Z0-9_]+)\s*\(")
EXTENDS_PATTERN = re.compile(r"\b(?:class|interface)\s+[a-zA-Z0-9_]+\s*(?:\([^)]*\))?\s*:\s*([a-zA-Z0-9_,\s<>]+)")
JAVA_EXTENDS_PATTERN = re.compile(r"\bclass\s+[a-zA-Z0-9_]+\s+extends\s+([a-zA-Z0-9_]+)")
JAVA_IMPLEMENTS_PATTERN = re.compile(r"\bclass\s+[a-zA-Z0-9_]+\s+implements\s+([a-zA-Z0-9_,\s]+)")
SET_CONTENT_LAYOUT_PATTERN = re.compile(r"R\.layout\.([a-zA-Z0-9_]+)")
XML_INCLUDE_PATTERN = re.compile(r'@layout/([a-zA-Z0-9_]+)')
XML_FRAGMENT_CLASS_PATTERN = re.compile(r'(?:android:name|class)="([a-zA-Z0-9_.]+)"')

GRADLE_INCLUDE_PATTERN = re.compile(r'''include\s*\(?\s*['":]([a-zA-Z0-9_:\-./]+)['"]?\s*\)?''')
GRADLE_PROJECT_DEP_PATTERN = re.compile(r'''(?:implementation|api|compileOnly|runtimeOnly|testImplementation|androidTestImplementation)\s*\(?\s*project\s*\(?\s*['"](:[a-zA-Z0-9_:\-]+)['"]\s*\)\s*\)?''')
GRADLE_TYPE_SAFE_DEP_PATTERN = re.compile(r'''(?:implementation|api|compileOnly|runtimeOnly)\s*\(?\s*projects\.([a-zA-Z0-9_.]+)\s*\)?''')


class DependencyGraph:
    """Directed graph representing Android modules, classes, screens, and relationships."""

    def __init__(self):
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []
        self._adj: dict[str, set[str]] = {}
        self._rev_adj: dict[str, set[str]] = {}

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node
        if node.id not in self._adj:
            self._adj[node.id] = set()
        if node.id not in self._rev_adj:
            self._rev_adj[node.id] = set()

    def add_edge(self, source: str, target: str, kind: str = EdgeKind.DEPENDS_ON.value, metadata: dict | None = None) -> None:
        if source == target:
            return
        edge = GraphEdge(source=source, target=target, kind=kind, metadata=metadata or {})
        self.edges.append(edge)
        if source not in self._adj:
            self._adj[source] = set()
        if target not in self._rev_adj:
            self._rev_adj[target] = set()
        self._adj[source].add(target)
        self._rev_adj[target].add(source)

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        targets = self._adj.pop(node_id, set())
        for t in targets:
            if t in self._rev_adj:
                self._rev_adj[t].discard(node_id)
        sources = self._rev_adj.pop(node_id, set())
        for s in sources:
            if s in self._adj:
                self._adj[s].discard(node_id)
        self.edges = [e for e in self.edges if e.source != node_id and e.target != node_id]

    def get_targets(self, node_id: str) -> set[str]:
        return self._adj.get(node_id, set())

    def get_sources(self, node_id: str) -> set[str]:
        return self._rev_adj.get(node_id, set())

    def find_node(self, query: str) -> GraphNode | None:
        """Find node by exact ID, or match name/symbol/filepath case-insensitively with priority."""
        if query in self.nodes:
            return self.nodes[query]
        q_lower = query.lower()
        # 1. Exact name match
        for node in self.nodes.values():
            if node.name.lower() == q_lower:
                return node
        # 2. Exact declaration match
        for node in self.nodes.values():
            if any(d.lower() == q_lower for d in node.declarations):
                return node
        # 3. File path exact stem / filename match
        for node in self.nodes.values():
            if node.file_path and Path(node.file_path).stem.lower() == q_lower:
                return node
        # 4. Prefix / Substring match on name
        for node in self.nodes.values():
            if q_lower in node.name.lower():
                return node
        return None

    def find_nodes(self, query: str, limit: int = 60) -> list[GraphNode]:
        """Find all nodes matching query across ID, name, declarations, file path, or metadata."""
        q_lower = query.lower().strip()
        exact_matches: list[GraphNode] = []
        name_matches: list[GraphNode] = []
        path_matches: list[GraphNode] = []
        seen: set[str] = set()

        for node in self.nodes.values():
            if node.id in seen:
                continue
            meta = node.metadata or {}
            meta_desc = str(meta.get("description") or meta.get("title") or meta.get("role") or "").lower()
            meta_usage = str(meta.get("usage") or "").lower()
            flags = [str(f).lower() for f in meta.get("flags", [])]

            if node.id == query or node.name == query or any(d == query for d in node.declarations):
                exact_matches.append(node)
                seen.add(node.id)
            elif node.name.lower() == q_lower or any(d.lower() == q_lower for d in node.declarations):
                exact_matches.append(node)
                seen.add(node.id)
            elif q_lower in node.name.lower():
                name_matches.append(node)
                seen.add(node.id)
            elif node.file_path and q_lower in node.file_path.lower():
                path_matches.append(node)
                seen.add(node.id)
            elif q_lower in meta_desc or q_lower in meta_usage or any(q_lower in f for f in flags):
                path_matches.append(node)
                seen.add(node.id)

        results = exact_matches + name_matches + path_matches
        return results[:limit]

    def format_symbol_match(self, node: GraphNode) -> str:
        """Formats a single matching node with explicit language, path, and layer."""
        lines = []
        lang = node.metadata.get("language", "")
        composable = node.metadata.get("composable", False)

        if node.type == EntityType.HARNESS_TOOL.value:
            lines.append(f"  * {node.name} [HARNESS_TOOL]")
            lines.append(f"    Path: {node.file_path}")
            if node.metadata.get("description"):
                lines.append(f"    Description: {node.metadata.get('description')}")
            if node.metadata.get("usage"):
                lines.append(f"    Usage: {node.metadata.get('usage')}")
        elif node.type == EntityType.WORKFLOW_PLAYBOOK.value:
            lines.append(f"  * {node.name} [WORKFLOW_PLAYBOOK]")
            lines.append(f"    Path: {node.file_path}")
            if node.metadata.get("title"):
                lines.append(f"    Title: {node.metadata.get('title')}")
        elif node.type == EntityType.SUBAGENT_ROSTER.value:
            lines.append(f"  * {node.name} [SUBAGENT]")
            lines.append(f"    Path: {node.file_path}")
            if node.metadata.get("role"):
                lines.append(f"    Role: {node.metadata.get('role')}")
            if node.metadata.get("description"):
                lines.append(f"    Description: {node.metadata.get('description')}")
        elif node.type in (EntityType.XML_LAYOUT.value, EntityType.NAV_GRAPH.value):
            lines.append(f"  * {node.name} [{node.type}]")
            lines.append(f"    Path: {node.file_path}")
            lines.append(f"    Module: {node.module}")
        else:
            tag = f"[{lang.upper()}_{node.type}]" if lang else f"[{node.type}]"
            if composable:
                tag = f"[COMPOSE_{node.type}]"
            lines.append(f"  * {node.name} {tag}")
            lines.append(f"    Path: {node.file_path}")
            if node.module:
                lines.append(f"    Module: {node.module}")
            if node.package:
                lines.append(f"    Package: {node.package}")
            targets = [self.nodes[t].name for t in self.get_targets(node.id) if t in self.nodes]
            if targets:
                lines.append(f"    Dependencies: {', '.join(targets[:6])}")
        return "\n".join(lines)

    def to_harness_inventory(self) -> str:
        """Renders an organized directory of all Harness CLI tools, workflows, and subagents."""
        tools = [n for n in self.nodes.values() if n.type == EntityType.HARNESS_TOOL.value]
        workflows = [n for n in self.nodes.values() if n.type == EntityType.WORKFLOW_PLAYBOOK.value]
        subagents = [n for n in self.nodes.values() if n.type == EntityType.SUBAGENT_ROSTER.value]

        lines = [
            "=" * 78,
            f"  Android AI Harness Infrastructure Topology ({len(tools)} tools, {len(workflows)} workflows, {len(subagents)} subagents)",
            "=" * 78,
        ]

        if tools:
            lines.append(f"\n[*] Core Harness CLI & Automation Tools ({len(tools)}):")
            for t in sorted(tools, key=lambda x: x.name):
                desc = t.metadata.get("description", "")
                usage = t.metadata.get("usage", "")
                lines.append(f"  - {t.name} [HARNESS_TOOL] ({t.file_path})")
                if desc and desc != t.name:
                    lines.append(f"    -> {desc}")
                if usage:
                    first_usage = usage.splitlines()[0] if usage else ""
                    lines.append(f"    -> Usage: {first_usage}")

        if workflows:
            lines.append(f"\n[*] Workflows & Governance Playbooks ({len(workflows)}):")
            for w in sorted(workflows, key=lambda x: x.name):
                title = w.metadata.get("title", w.name)
                lines.append(f"  - {w.name} [WORKFLOW_PLAYBOOK] ({w.file_path})")
                if title and title != w.name:
                    lines.append(f"    -> {title}")

        if subagents:
            lines.append(f"\n[*] Specialized Subagent Roster ({len(subagents)}):")
            for a in sorted(subagents, key=lambda x: x.name):
                role = a.metadata.get("role", a.name)
                desc = a.metadata.get("description", "")
                lines.append(f"  - {a.name} [SUBAGENT] ({a.file_path})")
                lines.append(f"    -> Role: {role}")
                if desc:
                    lines.append(f"    -> {desc}")

        return "\n".join(lines)

    def extract_feature_graph(
        self,
        feature_name: str,
        max_depth: int = 1,
    ) -> tuple[dict[str, GraphNode], list[GraphEdge]]:
        """Finds all nodes belonging to a feature package/module across any standard Android project layout."""
        q_lower = feature_name.lower().strip()
        feature_nodes: list[GraphNode] = []
        seen: set[str] = set()

        # 1. Match standard Android module or package directory structures
        for node in self.nodes.values():
            if node.id in seen:
                continue
            fp = (node.file_path or "").lower()
            mod = (node.module or "").lower()
            pkg = (node.package or "").lower()

            is_feature_path = (
                f"/features/{q_lower}/" in fp
                or f"/feature/{q_lower}/" in fp
                or f"/feature_{q_lower}/" in fp
                or f"/features_{q_lower}/" in fp
                or f"/{q_lower}/" in fp
                or fp.endswith(f"/{q_lower}.kt")
                or fp.endswith(f"/{q_lower}.java")
                or mod == f":feature:{q_lower}"
                or mod == f":features:{q_lower}"
                or mod == f":{q_lower}"
                or f".feature.{q_lower}." in f".{pkg}."
                or f".features.{q_lower}." in f".{pkg}."
            )
            if is_feature_path:
                feature_nodes.append(node)
                seen.add(node.id)

        # 2. If no directory matched, match class names starting with or containing the feature name
        if not feature_nodes:
            for node in self.nodes.values():
                if node.id in seen:
                    continue
                if (
                    node.name.lower() == q_lower
                    or node.name.lower().startswith(q_lower)
                    or any(d.lower() == q_lower or d.lower().startswith(q_lower) for d in node.declarations)
                ):
                    feature_nodes.append(node)
                    seen.add(node.id)

        start_ids = [n.id for n in feature_nodes]
        if not start_ids:
            matched = self.find_nodes(feature_name)
            start_ids = [n.id for n in matched]

        return self.extract_subgraph(start_ids, max_depth=max_depth, direction="outgoing")

    def to_slice_summary(self, nodes: dict[str, GraphNode] | None = None) -> str:
        """Renders a high-signal Clean Architecture layer breakdown for a set of nodes."""
        target_nodes = list(nodes.values()) if nodes is not None else list(self.nodes.values())
        if not target_nodes:
            return "[Empty Architecture Slice]"

        screens = [n for n in target_nodes if n.type in (EntityType.SCREEN.value, EntityType.XML_LAYOUT.value)]
        view_models = [n for n in target_nodes if n.type == EntityType.VIEW_MODEL.value]
        domain = [n for n in target_nodes if n.type == EntityType.USE_CASE.value or (n.file_path and "/domain/" in n.file_path)]
        data = [n for n in target_nodes if n.type in (EntityType.REPOSITORY.value, EntityType.DATA_SOURCE.value) or (n.file_path and "/data/" in n.file_path)]
        tests = [n for n in target_nodes if n.type == EntityType.TEST.value or (n.file_path and ("src/test" in n.file_path or "src/androidTest" in n.file_path))]

        lines = [
            f"=== Feature Architecture Slice ({len(target_nodes)} components) ===",
        ]

        if screens:
            lines.append(f"\n[UI Screens & Layouts] ({len(screens)}):")
            for sc in sorted(screens, key=lambda x: x.name):
                tag = "[COMPOSE]" if sc.metadata.get("compose") else "[XML]"
                targets = [self.nodes[t].name for t in self.get_targets(sc.id) if t in self.nodes]
                deps = f" -> {', '.join(targets[:4])}" if targets else ""
                lines.append(f"  * {sc.name} {tag} ({sc.file_path or 'unknown'}){deps}")

        if view_models:
            lines.append(f"\n[ViewModels & State Holders] ({len(view_models)}):")
            for vm in sorted(view_models, key=lambda x: x.name):
                targets = [self.nodes[t].name for t in self.get_targets(vm.id) if t in self.nodes]
                deps = f" -> {', '.join(targets[:4])}" if targets else ""
                lines.append(f"  * {vm.name} ({vm.file_path or 'unknown'}){deps}")

        if domain:
            lines.append(f"\n[Domain Layer (UseCases & Contracts)] ({len(domain)}):")
            for dm in sorted(domain, key=lambda x: x.name):
                lines.append(f"  * {dm.name} ({dm.file_path or 'unknown'})")

        if data:
            lines.append(f"\n[Data Layer (Repositories & Sources)] ({len(data)}):")
            for dt in sorted(data, key=lambda x: x.name):
                lines.append(f"  * {dt.name} ({dt.file_path or 'unknown'})")

        if tests:
            lines.append(f"\n[Unit & UI Tests] ({len(tests)}):")
            for tst in sorted(tests, key=lambda x: x.name):
                lines.append(f"  * {tst.name} ({tst.file_path or 'unknown'})")

        return "\n".join(lines)

    def find_shortest_path(self, from_id: str, to_id: str) -> list[str]:
        """BFS shortest path from from_id to to_id."""
        if from_id not in self.nodes or to_id not in self.nodes:
            n_from = self.find_node(from_id)
            n_to = self.find_node(to_id)
            if not n_from or not n_to:
                return []
            from_id, to_id = n_from.id, n_to.id

        if from_id == to_id:
            return [from_id]

        queue: list[list[str]] = [[from_id]]
        visited: set[str] = {from_id}

        while queue:
            path = queue.pop(0)
            curr = path[-1]
            for neighbor in self.get_targets(curr):
                if neighbor == to_id:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return []

    def extract_subgraph(
        self,
        start_ids: list[str],
        max_depth: int = 1,
        direction: str = "outgoing",
    ) -> tuple[dict[str, GraphNode], list[GraphEdge]]:
        """Extract nodes and edges within max_depth hops around start_ids with universal hub protection."""
        sub_nodes: dict[str, GraphNode] = {}
        visited: set[str] = set()
        frontier: set[str] = set()

        for sid in start_ids:
            node = self.find_node(sid)
            if node:
                sub_nodes[node.id] = node
                frontier.add(node.id)
                visited.add(node.id)

        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for curr in frontier:
                curr_node = self.nodes.get(curr)
                # Universal check: never expand out of framework roots or generic base classes
                if curr_node and is_hub_or_base_symbol(curr_node.name, len(self.get_sources(curr))):
                    continue

                neighbors: set[str] = set()
                if direction in ("outgoing", "both"):
                    neighbors.update(self.get_targets(curr))
                if direction in ("incoming", "both"):
                    for src in self.get_sources(curr):
                        src_node = self.nodes.get(src)
                        if src_node and not is_hub_or_base_symbol(src_node.name, len(self.get_sources(src))):
                            neighbors.add(src)

                for nbr in neighbors:
                    if nbr not in visited and nbr in self.nodes:
                        visited.add(nbr)
                        sub_nodes[nbr] = self.nodes[nbr]
                        nbr_node = self.nodes[nbr]
                        if not is_hub_or_base_symbol(nbr_node.name, len(self.get_sources(nbr))):
                            next_frontier.add(nbr)
            frontier = next_frontier
            if not frontier:
                break

        sub_node_ids = set(sub_nodes.keys())
        sub_edges = [
            e for e in self.edges
            if e.source in sub_node_ids and e.target in sub_node_ids
        ]
        return sub_nodes, sub_edges

    def to_compact(self, focus_id: str | None = None, max_depth: int = 2) -> str:
        """Compact text representation optimized for minimal tokens."""
        if focus_id:
            sub_nodes, sub_edges = self.extract_subgraph([focus_id], max_depth=max_depth)
        else:
            sub_nodes, sub_edges = self.nodes, self.edges

        if not sub_nodes:
            return "[Empty Graph]"

        lines: list[str] = []
        by_type: dict[str, list[GraphNode]] = {}
        for n in sub_nodes.values():
            by_type.setdefault(n.type, []).append(n)

        lines.append(f"Graph Summary: {len(sub_nodes)} nodes, {len(sub_edges)} edges")
        for t, nodes in sorted(by_type.items()):
            lines.append(f"[{t}] ({len(nodes)}): " + ", ".join(sorted(n.name for n in nodes)[:15]))
            if len(nodes) > 15:
                lines[-1] += f" ... +{len(nodes)-15} more"

        lines.append("Topology:")
        for edge in sub_edges[:40]:
            s_name = sub_nodes[edge.source].name if edge.source in sub_nodes else edge.source
            t_name = sub_nodes[edge.target].name if edge.target in sub_nodes else edge.target
            lines.append(f"  {s_name} -> {t_name} [{edge.kind}]")
        if len(sub_edges) > 40:
            lines.append(f"  ... and {len(sub_edges) - 40} more edges")

        return "\n".join(lines)

    def to_mermaid(self, title: str = "Android Code Graph", direction: str = "TD") -> str:
        """Mermaid diagram format for Markdown / Artifacts."""
        lines = [f"```mermaid\ngraph {direction}"]
        if title:
            lines.append(f'    %% {title}')

        styles = {
            EntityType.MODULE.value: "fill:#e1f5fe,stroke:#0288d1,stroke-width:2px",
            EntityType.SCREEN.value: "fill:#e8f5e9,stroke:#388e3c,stroke-width:2px",
            EntityType.VIEW_MODEL.value: "fill:#fff3e0,stroke:#f57c00,stroke-width:2px",
            EntityType.USE_CASE.value: "fill:#ede7f6,stroke:#512da8,stroke-width:1px",
            EntityType.REPOSITORY.value: "fill:#fce4ec,stroke:#c2185b,stroke-width:2px",
            EntityType.DATA_SOURCE.value: "fill:#efebe9,stroke:#5d4037,stroke-width:1px",
            EntityType.TEST.value: "fill:#f3e5f5,stroke:#7b1fa2,stroke-dasharray: 5 5",
            EntityType.XML_LAYOUT.value: "fill:#f9fbe7,stroke:#afb42b,stroke-width:1px",
        }

        def safe_id(nid: str) -> str:
            return re.sub(r"[^a-zA-Z0-9_]", "_", nid)

        for nid, node in sorted(self.nodes.items()):
            sid = safe_id(nid)
            label = f"{node.name}\\n({node.type})"
            lines.append(f'    {sid}["{label}"]')

        for edge in self.edges:
            s_id = safe_id(edge.source)
            t_id = safe_id(edge.target)
            lines.append(f'    {s_id} --> {t_id}')

        for nid, node in self.nodes.items():
            st = styles.get(node.type)
            if st:
                lines.append(f'    style {safe_id(nid)} {st}')

        lines.append("```")
        return "\n".join(lines)

    def to_dot(self, title: str = "Android Code Graph") -> str:
        """Graphviz DOT format."""
        lines = ['digraph AndroidGraph {', f'    label="{title}";', '    rankdir=LR;', '    node [shape=box, style=rounded, fontname="Helvetica"];']

        colors = {
            EntityType.MODULE.value: 'fillcolor="#E1F5FE", color="#0288D1", style="filled,rounded,bold"',
            EntityType.SCREEN.value: 'fillcolor="#E8F5E9", color="#388E3C", style="filled,rounded"',
            EntityType.VIEW_MODEL.value: 'fillcolor="#FFF3E0", color="#F57C00", style="filled,rounded"',
            EntityType.USE_CASE.value: 'fillcolor="#EDE7F6", color="#512DA8", style="filled,rounded"',
            EntityType.REPOSITORY.value: 'fillcolor="#FCE4EC", color="#C2185B", style="filled,rounded"',
            EntityType.DATA_SOURCE.value: 'fillcolor="#EFEBE9", color="#5D4037", style="filled,rounded"',
            EntityType.TEST.value: 'fillcolor="#F3E5F5", color="#7B1FA2", style="filled,rounded,dashed"',
            EntityType.XML_LAYOUT.value: 'fillcolor="#F9FBE7", color="#AFB42B", style="filled,rounded"',
        }

        def dot_id(nid: str) -> str:
            return '"' + nid.replace('"', '\\"') + '"'

        for nid, node in self.nodes.items():
            color_attr = colors.get(node.type, 'fillcolor="#FFFFFF", style="filled,rounded"')
            label = f"{node.name}\\n[{node.type}]"
            lines.append(f'    {dot_id(nid)} [label="{label}", {color_attr}];')

        for edge in self.edges:
            lines.append(f'    {dot_id(edge.source)} -> {dot_id(edge.target)};')

        lines.append('}')
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DependencyGraph:
        graph = cls()
        for nd in data.get("nodes", []):
            graph.add_node(GraphNode.from_dict(nd))
        for ed in data.get("edges", []):
            graph.add_edge(ed["source"], ed["target"], kind=ed.get("kind", EdgeKind.DEPENDS_ON.value), metadata=ed.get("metadata", {}))
        return graph


# =========================================================================
# Parsers & Analyzers
# =========================================================================

def classify_entity_type(name: str, file_path: str, declarations: list[str], text: str) -> EntityType:
    """Universal classification for Android components across legacy & modern paradigms."""
    lower_path = file_path.lower()
    lower_name = name.lower()

    if "/test/" in lower_path or "/androidtest/" in lower_path or lower_name.endswith("test") or lower_name.endswith("tests"):
        return EntityType.TEST

    if lower_name.endswith("screen") or "@composable" in text.lower() or "activity" in lower_name or "fragment" in lower_name or "dialog" in lower_name:
        return EntityType.SCREEN

    if lower_name.endswith("viewmodel") or lower_name.endswith("presenter") or lower_name.endswith("controller") or "@hiltviewmodel" in text.lower() or "viewmodel" in text.lower():
        return EntityType.VIEW_MODEL

    if lower_name.endswith("usecase") or lower_name.endswith("interactor"):
        return EntityType.USE_CASE

    if lower_name.endswith("repository") or lower_name.endswith("repo"):
        return EntityType.REPOSITORY

    if (
        lower_name.endswith("datasource")
        or lower_name.endswith("dao")
        or lower_name.endswith("api")
        or lower_name.endswith("service")
        or lower_name.endswith("database")
        or lower_name.endswith("db")
        or "@dao" in text.lower()
        or "@entity" in text.lower()
        or "@database" in text.lower()
    ):
        return EntityType.DATA_SOURCE

    return EntityType.COMPONENT


def parse_gradle_modules(repo: Path) -> tuple[dict[str, GraphNode], list[GraphEdge]]:
    """Parse settings.gradle(.kts) and build.gradle(.kts) across multi-module projects."""
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    settings_files = [repo / "settings.gradle.kts", repo / "settings.gradle"]
    found_modules: set[str] = {":app"}

    for sf in settings_files:
        if sf.is_file():
            try:
                content = sf.read_text(encoding="utf-8", errors="replace")
                for m in GRADLE_INCLUDE_PATTERN.finditer(content):
                    mod = m.group(1).strip()
                    if not mod.startswith(":"):
                        mod = f":{mod}"
                    found_modules.add(mod)
                for m in re.finditer(r'''include\s*['":]([a-zA-Z0-9_:\-./]+)['"]?''', content):
                    mod = m.group(1).strip()
                    if not mod.startswith(":"):
                        mod = f":{mod}"
                    found_modules.add(mod)
            except Exception:
                pass

    for mod in sorted(found_modules):
        nodes[mod] = GraphNode(
            id=mod,
            name=mod,
            type=EntityType.MODULE.value,
            module=mod,
            file_path="",
        )

    for mod in found_modules:
        mod_rel_path = mod.lstrip(":").replace(":", "/")
        mod_dir = repo / mod_rel_path if mod_rel_path else repo
        for bg_name in ("build.gradle.kts", "build.gradle"):
            bg_file = mod_dir / bg_name
            if bg_file.is_file():
                nodes[mod].file_path = bg_file.relative_to(repo).as_posix()
                try:
                    text = bg_file.read_text(encoding="utf-8", errors="replace")
                    for m in GRADLE_PROJECT_DEP_PATTERN.finditer(text):
                        target_mod = m.group(1).strip()
                        if target_mod in found_modules and target_mod != mod:
                            edges.append(GraphEdge(source=mod, target=target_mod, kind=EdgeKind.DEPENDS_ON.value))

                    for m in GRADLE_TYPE_SAFE_DEP_PATTERN.finditer(text):
                        raw_target = m.group(1).strip().replace(".", ":")
                        target_mod = f":{raw_target}"
                        if target_mod in found_modules and target_mod != mod:
                            edges.append(GraphEdge(source=mod, target=target_mod, kind=EdgeKind.DEPENDS_ON.value))
                except Exception:
                    pass

    return nodes, edges


def parse_code_file(path: Path, repo: Path) -> list[GraphNode]:
    """Extract classes, screens, viewmodels, and layers from a Java or Kotlin source file."""
    try:
        rel_path = path.relative_to(repo).as_posix()
    except ValueError:
        rel_path = path.as_posix()

    mod_parts = rel_path.split("/src/")[0]
    module_id = ":" + mod_parts.replace("/", ":") if mod_parts and mod_parts != "." else ":app"

    try:
        raw_text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    # Strip comments and string literals to prevent phantom symbols and false positive regex hits
    clean_text = strip_comments_and_strings(raw_text)

    pkg = ""
    pkg_m = PACKAGE_PATTERN.search(clean_text)
    if pkg_m:
        pkg = pkg_m.group(1).strip()

    raw_imports = [m.group(1).strip() for m in IMPORT_PATTERN.finditer(clean_text)]
    imports = [
        imp for imp in raw_imports
        if not imp.endswith(".*") and imp.split(".")[-1].lower() not in KOTLIN_RESERVED_DECLARATIONS
    ]

    raw_decls = [m.group(1).strip() for m in DECLARATION_PATTERN.finditer(clean_text)]
    for m in NAMED_OBJECT_PATTERN.finditer(clean_text):
        obj_name = m.group(1).strip()
        if obj_name.lower() not in KOTLIN_RESERVED_DECLARATIONS:
            raw_decls.append(obj_name)

    declarations = [
        d for d in raw_decls
        if d.lower() not in KOTLIN_RESERVED_DECLARATIONS and not d.startswith("_") and len(d) > 1
    ]

    composable_funcs = [
        m.group(1).strip() for m in COMPOSABLE_FUNC_PATTERN.finditer(clean_text)
        if m.group(1).strip().lower() not in KOTLIN_RESERVED_DECLARATIONS
    ]

    nodes: list[GraphNode] = []

    is_java = path.suffix.lower() == ".java"
    lang = "Java" if is_java else "Kotlin"

    for fn in composable_funcs:
        if fn.endswith("Screen") or fn.endswith("View") or fn.endswith("Dialog") or fn.endswith("BottomSheet"):
            node_id = f"{pkg}.{fn}" if pkg else fn
            nodes.append(
                GraphNode(
                    id=node_id,
                    name=fn,
                    type=EntityType.SCREEN.value,
                    file_path=rel_path,
                    module=module_id,
                    package=pkg,
                    declarations=[fn],
                    imports=imports,
                    metadata={"composable": True, "language": lang},
                )
            )

    for decl in declarations:
        node_id = f"{pkg}.{decl}" if pkg else decl
        etype = classify_entity_type(decl, rel_path, declarations, raw_text)
        nodes.append(
            GraphNode(
                id=node_id,
                name=decl,
                type=etype.value,
                file_path=rel_path,
                module=module_id,
                package=pkg,
                declarations=declarations,
                imports=imports,
                metadata={"language": lang},
            )
        )

    if not nodes:
        name = path.stem
        if name.lower() not in KOTLIN_RESERVED_DECLARATIONS:
            etype = classify_entity_type(name, rel_path, [], raw_text)
            node_id = f"{pkg}.{name}" if pkg else name
            nodes.append(
                GraphNode(
                    id=node_id,
                    name=name,
                    type=etype.value,
                    file_path=rel_path,
                    module=module_id,
                    package=pkg,
                    declarations=[name],
                    imports=imports,
                    metadata={"language": lang},
                )
            )

    return nodes


def parse_xml_file(path: Path, repo: Path) -> list[tuple[GraphNode, list[str]]]:
    """Parse XML layout or navigation files and return node with layout dependencies."""
    try:
        rel_path = path.relative_to(repo).as_posix()
    except ValueError:
        rel_path = path.as_posix()

    mod_parts = rel_path.split("/src/")[0]
    module_id = ":" + mod_parts.replace("/", ":") if mod_parts and mod_parts != "." else ":app"

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    name = path.stem
    is_nav = "/navigation" in rel_path
    etype = EntityType.NAV_GRAPH.value if is_nav else EntityType.XML_LAYOUT.value

    referenced_symbols: list[str] = []
    for inc in XML_INCLUDE_PATTERN.findall(text):
        referenced_symbols.append(inc)
    for frag in XML_FRAGMENT_CLASS_PATTERN.findall(text):
        referenced_symbols.append(frag)

    node = GraphNode(
        id=f"layout:{name}",
        name=f"layout/{name}",
        type=etype,
        file_path=rel_path,
        module=module_id,
        declarations=[name],
        metadata={"xml": True, "is_nav": is_nav, "language": "XML"},
    )
    return [(node, referenced_symbols)]


def parse_harness_script(path: Path, repo: Path) -> GraphNode | None:
    """Extract metadata and CLI usage from a Harness Python tool script."""
    try:
        rel_path = path.relative_to(repo).as_posix()
    except ValueError:
        rel_path = path.as_posix()

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        import ast
        tree = ast.parse(text)
        doc = ast.get_docstring(tree) or ""
        doc_lines = [l.strip() for l in doc.splitlines() if l.strip()]
        title = doc_lines[0] if doc_lines else path.name
        usage_lines = [l for l in doc_lines if "python " in l or l.startswith("Usage:")]
        usage = "\n".join(usage_lines) if usage_lines else f"python {rel_path}"
        flags = re.findall(r"(--[a-zA-Z0-9_\-]+)", text)
    except Exception:
        title = path.name
        usage = f"python {rel_path}"
        flags = []

    return GraphNode(
        id=f"harness:{path.name}",
        name=path.name,
        type=EntityType.HARNESS_TOOL.value,
        file_path=rel_path,
        module=":harness",
        declarations=[path.stem, path.name],
        metadata={
            "description": title,
            "usage": usage,
            "flags": sorted(set(flags)),
            "harness": True,
            "language": "Python",
        },
    )


def parse_workflow_file(path: Path, repo: Path) -> GraphNode | None:
    """Extract metadata from a Harness workflow guide."""
    try:
        rel_path = path.relative_to(repo).as_posix()
    except ValueError:
        rel_path = path.as_posix()

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        title = path.stem
        for line in text.splitlines():
            line_s = line.strip()
            if line_s.startswith("# "):
                title = line_s.lstrip("# ").strip()
                break
    except Exception:
        title = path.stem

    return GraphNode(
        id=f"workflow:{path.name}",
        name=path.name,
        type=EntityType.WORKFLOW_PLAYBOOK.value,
        file_path=rel_path,
        module=":harness",
        declarations=[path.stem, path.name],
        metadata={
            "title": title,
            "harness": True,
            "language": "Markdown",
        },
    )


def parse_subagent_file(path: Path, repo: Path) -> GraphNode | None:
    """Extract metadata from a Harness subagent spec JSON."""
    try:
        rel_path = path.relative_to(repo).as_posix()
    except ValueError:
        rel_path = path.as_posix()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        role = data.get("role", path.stem)
        desc = data.get("description", "")
    except Exception:
        role = path.stem
        desc = ""

    return GraphNode(
        id=f"subagent:{path.stem}",
        name=path.stem,
        type=EntityType.SUBAGENT_ROSTER.value,
        file_path=rel_path,
        module=":harness",
        declarations=[path.stem],
        metadata={
            "role": role,
            "description": desc,
            "harness": True,
            "language": "JSON",
        },
    )


# =========================================================================
# Incremental Cache & Self-Healing Engine
# =========================================================================

def resolve_cache_file(repo: Path) -> Path:
    """Resolve cache location based on layout (raw kit vs installed app)."""
    if (repo / "agents" / "VERSION").is_file() and not (repo / ".agents").is_dir():
        return repo / "agents" / "cache" / "project_graph.json"
    return repo / ".agents" / "cache" / "project_graph.json"


class GraphEngine:
    """Manages full dependency graph caching, incremental synchronization, and self-healing."""

    def __init__(self, repo_dir: Path | None = None):
        self.repo = (repo_dir or REPO).resolve()
        self.cache_file = resolve_cache_file(self.repo)
        self.graph = DependencyGraph()
        self.file_hashes: dict[str, str] = {}
        self.symbol_to_node_id: dict[str, str] = {}
        self.healed_log: list[str] = []

    def compute_file_hash(self, path: Path) -> str:
        try:
            content = path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except Exception:
            return ""

    def load_cache(self) -> bool:
        if not self.cache_file.is_file():
            return False
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self.file_hashes = data.get("file_hashes", {})
            self.graph = DependencyGraph.from_dict(data.get("graph", {}))
            self._rebuild_symbol_index()
            return True
        except Exception:
            return False

    def save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": "1.0.0",
                "file_hashes": self.file_hashes,
                "graph": self.graph.to_dict(),
            }
            self.cache_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _rebuild_symbol_index(self) -> None:
        self.symbol_to_node_id.clear()
        for node in self.graph.nodes.values():
            if node.name.lower() not in KOTLIN_RESERVED_DECLARATIONS:
                self.symbol_to_node_id[node.name] = node.id
            for decl in node.declarations:
                if decl.lower() not in KOTLIN_RESERVED_DECLARATIONS:
                    self.symbol_to_node_id[decl] = node.id

    def sync(self, force_full: bool = False) -> dict[str, Any]:
        """Incremental synchronization: scans repo, updates dirty files, heals stale paths."""
        if not force_full:
            self.load_cache()

        extensions = {".kt", ".java", ".xml", ".gradle", ".kts"}
        current_files: dict[str, Path] = {}

        for p in self.repo.glob("**/*"):
            if p.is_file() and p.suffix.lower() in extensions:
                rel = p.relative_to(self.repo).as_posix()
                if any(part in (".git", "build", ".gradle", ".agents", ".harness-backup", "node_modules") for part in p.parts):
                    continue
                current_files[rel] = p

        # Discover Harness infrastructure (.agents in target project or agents in kit repo)
        harness_roots: list[Path] = []
        if (self.repo / ".agents" / "scripts").is_dir():
            harness_roots.append(self.repo / ".agents")
        if (self.repo / "agents" / "scripts").is_dir() and (self.repo / "agents" / "VERSION").is_file():
            harness_roots.append(self.repo / "agents")

        for hroot in harness_roots:
            scripts_dir = hroot / "scripts"
            workflows_dir = hroot / "workflows"
            subagents_dir = hroot / "subagents"

            if scripts_dir.is_dir():
                for sp in scripts_dir.glob("*.py"):
                    if not sp.name.startswith("_") or sp.name in ("_maestro_core.py", "_adb_core.py"):
                        rel = sp.relative_to(self.repo).as_posix()
                        current_files[rel] = sp
            if workflows_dir.is_dir():
                for wp in workflows_dir.glob("*.md"):
                    rel = wp.relative_to(self.repo).as_posix()
                    current_files[rel] = wp
            if subagents_dir.is_dir():
                for ap in subagents_dir.glob("*.json"):
                    rel = ap.relative_to(self.repo).as_posix()
                    current_files[rel] = ap

        added: list[str] = []
        modified: list[str] = []
        deleted: list[str] = [rel for rel in self.file_hashes if rel not in current_files]

        for rel, path in current_files.items():
            curr_hash = self.compute_file_hash(path)
            cached_hash = self.file_hashes.get(rel)
            if cached_hash is None:
                added.append(rel)
                self.file_hashes[rel] = curr_hash
            elif cached_hash != curr_hash:
                modified.append(rel)
                self.file_hashes[rel] = curr_hash

        for rel in deleted:
            self.file_hashes.pop(rel, None)
            nodes_to_remove = [nid for nid, n in self.graph.nodes.items() if n.file_path == rel]
            for nid in nodes_to_remove:
                self.graph.remove_node(nid)

        dirty_files = set(added + modified)
        if dirty_files or not self.graph.nodes:
            mod_nodes, mod_edges = parse_gradle_modules(self.repo)
            for m_node in mod_nodes.values():
                self.graph.add_node(m_node)
            for m_edge in mod_edges:
                self.graph.add_edge(m_edge.source, m_edge.target, kind=m_edge.kind)

            xml_connections: list[tuple[GraphNode, list[str]]] = []

            for rel in (dirty_files if self.graph.nodes else current_files.keys()):
                p = current_files[rel]
                existing_nodes = [nid for nid, n in self.graph.nodes.items() if n.file_path == rel]
                for nid in existing_nodes:
                    self.graph.remove_node(nid)

                if p.suffix.lower() in (".kt", ".java"):
                    nodes = parse_code_file(p, self.repo)
                    for n in nodes:
                        self.graph.add_node(n)
                elif p.suffix.lower() == ".xml" and ("/layout" in rel or "/navigation" in rel):
                    xml_items = parse_xml_file(p, self.repo)
                    for n, refs in xml_items:
                        self.graph.add_node(n)
                        xml_connections.append((n, refs))
                elif p.suffix.lower() == ".py" and ("/scripts/" in rel or rel.startswith("agents/scripts") or rel.startswith(".agents/scripts")):
                    hn = parse_harness_script(p, self.repo)
                    if hn:
                        self.graph.add_node(hn)
                elif p.suffix.lower() == ".md" and ("/workflows/" in rel or rel.startswith("agents/workflows") or rel.startswith(".agents/workflows")):
                    wn = parse_workflow_file(p, self.repo)
                    if wn:
                        self.graph.add_node(wn)
                elif p.suffix.lower() == ".json" and ("/subagents/" in rel or rel.startswith("agents/subagents") or rel.startswith(".agents/subagents")):
                    an = parse_subagent_file(p, self.repo)
                    if an:
                        self.graph.add_node(an)

            self._rebuild_symbol_index()

            for node in list(self.graph.nodes.values()):
                if node.type == EntityType.MODULE.value:
                    continue

                for imp in node.imports:
                    target_sym = imp.split(".")[-1]
                    if target_sym in self.symbol_to_node_id:
                        target_id = self.symbol_to_node_id[target_sym]
                        if target_id != node.id:
                            self.graph.add_edge(node.id, target_id, kind=EdgeKind.DEPENDS_ON.value)

            for xnode, refs in xml_connections:
                for ref in refs:
                    if ref in self.symbol_to_node_id:
                        self.graph.add_edge(xnode.id, self.symbol_to_node_id[ref], kind=EdgeKind.RENDERS.value)
                    elif f"layout:{ref}" in self.graph.nodes:
                        self.graph.add_edge(xnode.id, f"layout:{ref}", kind=EdgeKind.CONTAINS.value)

            self.save_cache()

        return {
            "added": len(added),
            "modified": len(modified),
            "deleted": len(deleted),
            "total_nodes": len(self.graph.nodes),
            "total_edges": len(self.graph.edges),
            "healed": len(self.healed_log),
        }

    def heal_symbol(self, query: str) -> tuple[GraphNode | None, str | None]:
        """Self-healing lookup: verifies disk path, auto-corrects moved/renamed files."""
        node = self.graph.find_node(query)
        if not node:
            return None, None

        if node.file_path:
            full_path = self.repo / node.file_path
            if full_path.is_file():
                return node, None

            old_path = node.file_path
            found_path: Path | None = None

            target_filename = Path(old_path).name
            for cand in self.repo.glob(f"**/{target_filename}"):
                if cand.is_file() and not any(part in (".git", "build", ".gradle") for part in cand.parts):
                    found_path = cand
                    break

            if found_path:
                new_rel = found_path.relative_to(self.repo).as_posix()
                node.file_path = new_rel
                heal_msg = f"[HEALED] Symbol '{node.name}' moved from '{old_path}' -> '{new_rel}'"
                self.healed_log.append(heal_msg)
                self.save_cache()
                return node, heal_msg

        return node, None


def render_dot_to_image(dot_content: str, output_path: Path, img_format: str = "svg") -> tuple[bool, str]:
    """Optional rendering using system Graphviz CLI (dot) if available."""
    dot_bin = shutil.which("dot")
    if not dot_bin:
        return False, "Graphviz 'dot' binary is not installed or not in PATH."

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        res = subprocess.run(
            [dot_bin, f"-T{img_format}", "-o", str(output_path)],
            input=dot_content,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return True, f"Rendered graph successfully to: {output_path}"
        return False, f"Graphviz dot error (exit {res.returncode}): {res.stderr}"
    except Exception as e:
        return False, f"Failed to execute dot: {e}"
