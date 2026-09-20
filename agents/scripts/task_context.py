"""Read-only, bounded local task context resolver for Android and KMP projects."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _graph_core import GraphEngine, GraphNode  # noqa: E402
from project_context import (  # noqa: E402
    _safe_read,
    source_identity,
    validate_advisory_knowledge,
)

SCHEMA_VERSION = 1
RESOLVER_VERSION = "1.0.0"
SUPPORTED_TARGET_SUFFIXES = {".kt", ".java", ".xml"}
DEFAULT_NEIGHBOR_LIMIT = 20
MAX_NEIGHBOR_LIMIT = 100


def _inside_repo(repo: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(repo)
        return True
    except ValueError:
        return False


def _source_set(path: str) -> str:
    return source_identity(path).get("source_set", "unknown")


def _node_summary(node: GraphNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "fqn": f"{node.package}.{node.name}" if node.package else node.name,
        "type": node.type,
        "path": node.file_path,
        "module": node.module,
        "source_set": _source_set(node.file_path),
        "package": node.package,
    }


def _candidate_summaries(nodes: list[GraphNode]) -> list[dict[str, Any]]:
    return [_node_summary(node) for node in sorted(nodes, key=lambda item: (item.file_path, item.id))]


def _resolve_file(repo: Path, value: str, engine: GraphEngine) -> tuple[str, list[GraphNode], str | None]:
    raw = Path(value)
    candidate = (raw if raw.is_absolute() else repo / raw).resolve(strict=False)
    if not _inside_repo(repo, candidate):
        return "INVALID_TARGET_PATH", [], "Target resolves outside the repository."
    if not candidate.exists() or not candidate.is_file():
        return "NOT_FOUND", [], "Target file does not exist."
    if candidate.suffix.lower() not in SUPPORTED_TARGET_SUFFIXES:
        return "INVALID_TARGET_PATH", [], "Target file type is not supported."
    rel = candidate.relative_to(repo).as_posix()
    nodes = [node for node in engine.graph.nodes.values() if node.file_path == rel]
    if not nodes:
        return "NOT_FOUND", [], "Target file is not represented in the live graph."
    return "RESOLVED", sorted(nodes, key=lambda item: item.id), None


def _resolve_symbol(
    query: str,
    engine: GraphEngine,
    *,
    module: str | None,
    source_set: str | None,
) -> tuple[str, list[GraphNode], str | None]:
    exact_fqn_ids = engine.fqn_to_node_ids.get(query, [])
    if exact_fqn_ids:
        nodes = [engine.graph.nodes[node_id] for node_id in exact_fqn_ids if node_id in engine.graph.nodes]
        if len(nodes) == 1:
            return "RESOLVED", nodes, None
        if module or source_set:
            qualified = [
                node for node in nodes
                if (not module or node.module == module)
                and (not source_set or _source_set(node.file_path).lower() == source_set.lower())
            ]
            if len(qualified) == 1:
                return "RESOLVED", qualified, None
            if len(qualified) > 1:
                return "AMBIGUOUS", qualified, "Qualified FQN still has multiple candidates."
            return "NOT_FOUND", [], "No FQN candidate matches the requested module/source set."
        return "AMBIGUOUS", nodes, "Exact FQN exists in multiple modules or source sets."

    short = query.rsplit(".", 1)[-1]
    ids = engine.symbol_to_node_ids.get(short, [])
    nodes = [engine.graph.nodes[node_id] for node_id in ids if node_id in engine.graph.nodes]
    if module or source_set:
        qualified = [
            node for node in nodes
            if (not module or node.module == module)
            and (not source_set or _source_set(node.file_path).lower() == source_set.lower())
        ]
        if len(qualified) == 1:
            return "RESOLVED", qualified, None
        if len(qualified) > 1:
            return "AMBIGUOUS", qualified, "Qualified symbol still has multiple candidates."
        return "NOT_FOUND", [], "No symbol matches the requested module/source set."
    if len(nodes) == 1:
        return "RESOLVED", nodes, None
    if len(nodes) > 1:
        return "AMBIGUOUS", nodes, "Symbol has multiple candidates; provide a path or module/source set."
    return "NOT_FOUND", [], "Symbol was not found in the live graph."


def _load_facts(repo: Path) -> dict[str, Any]:
    path = repo / ".agents" / "project-context" / "project-facts.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _profile_is_fresh(repo: Path, profile: dict[str, Any]) -> bool:
    for evidence in profile.get("evidence") or []:
        rel = str((evidence or {}).get("path") or "")
        expected = str((evidence or {}).get("sha256") or "")
        path = (repo / rel).resolve(strict=False)
        if not rel or not expected or not _inside_repo(repo, path) or not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            return False
    return True


def _matching_profiles(repo: Path, payload: dict[str, Any], node: GraphNode) -> tuple[list[dict[str, Any]], bool]:
    valid, _ = validate_advisory_knowledge(payload)
    if not valid:
        return [], False
    advisory = payload.get("advisory_knowledge") or {}
    node_source_set = _source_set(node.file_path)
    fresh: list[dict[str, Any]] = []
    stale_seen = False
    for profile in advisory.get("local_profiles") or []:
        paths = profile.get("paths") or []
        same_identity = (
            profile.get("module") == node.module
            and profile.get("source_set") == node_source_set
            and (node.file_path in paths or str(profile.get("logical_scope") or "").replace(".", "/") in node.file_path)
        )
        if not same_identity:
            continue
        if _profile_is_fresh(repo, profile):
            fresh.append(profile)
        else:
            stale_seen = True
    return sorted(fresh, key=lambda item: item.get("profile_id", ""))[:3], stale_seen


def _active_contract(repo: Path) -> dict[str, Any] | None:
    active_path = repo / ".agents" / "state" / "active-task.json"
    if not active_path.is_file():
        return None
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        task_id = str(active.get("task_id") or "")
        plan_path = repo / ".agents" / "state" / "tasks" / task_id / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan.get("status") not in {"IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"} or not plan.get("approval"):
            return None
        contract = plan.get("architecture_contract")
        if not isinstance(contract, dict):
            return None
        from architecture_resolver import compute_contract_hash
        if contract.get("contract_sha256") != compute_contract_hash(contract):
            return None
        return contract
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def resolve_task_context(
    repo: Path,
    *,
    file: str | None = None,
    symbol: str | None = None,
    module: str | None = None,
    source_set: str | None = None,
    limit: int = DEFAULT_NEIGHBOR_LIMIT,
) -> dict[str, Any]:
    """Resolve bounded task-local context without persistent writes."""
    root = repo.resolve()
    bounded_limit = max(1, min(int(limit), MAX_NEIGHBOR_LIMIT))
    engine = GraphEngine(root)
    sync = engine.sync(persist=False)
    if file:
        status, candidates, error = _resolve_file(root, file, engine)
        query = file
    elif symbol:
        status, candidates, error = _resolve_symbol(symbol, engine, module=module, source_set=source_set)
        query = symbol
    else:
        status, candidates, error = "INVALID_TARGET_PATH", [], "Exactly one of --file or --symbol is required."
        query = ""

    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "resolver_version": RESOLVER_VERSION,
        "status": status,
        "query": query,
        "graph_sync": sync,
        "warnings": [error] if error else [],
    }
    if status in {"AMBIGUOUS", "NOT_FOUND", "INVALID_TARGET_PATH"}:
        base["candidates"] = _candidate_summaries(candidates)[:bounded_limit]
        return base

    target_nodes = candidates
    primary = target_nodes[0]
    target_ids = {node.id for node in target_nodes}
    dependency_ids: set[str] = set()
    dependent_ids: set[str] = set()
    for node_id in target_ids:
        dependency_ids.update(engine.graph.get_targets(node_id))
        dependent_ids.update(engine.graph.get_sources(node_id))
    dependencies = [engine.graph.nodes[item] for item in dependency_ids if item in engine.graph.nodes and item not in target_ids]
    dependents = [engine.graph.nodes[item] for item in dependent_ids if item in engine.graph.nodes and item not in target_ids]
    tests = [
        node for node in engine.graph.nodes.values()
        if _source_set(node.file_path).lower().startswith(("test", "androidtest"))
        and any(target.name in (_safe_read(root / node.file_path)) for target in target_nodes)
    ]

    facts_payload = _load_facts(root)
    profiles, stale_seen = _matching_profiles(root, facts_payload, primary)
    contract = _active_contract(root)
    conflicts: list[str] = []
    local_family_ids = {str(profile.get("family_id")) for profile in profiles if profile.get("family_id")}
    if contract and contract.get("mode") in {"PRESERVE", "REFACTOR"}:
        source_family = str(contract.get("source_family_id") or "")
        if source_family and local_family_ids and source_family not in local_family_ids:
            conflicts.append("Live local profile disagrees with the approved source architecture family.")

    result_status = "CONTEXT_CONFLICT_WITH_APPROVED_CONTRACT" if conflicts else "ADVISORY_STALE_FALLBACK_USED" if stale_seen else "RESOLVED"
    base.update({
        "status": result_status,
        "target": {
            "path": primary.file_path,
            "module": primary.module,
            "source_set": _source_set(primary.file_path),
            "package": primary.package,
            "symbols": sorted({node.name for node in target_nodes}),
            "nodes": _candidate_summaries(target_nodes),
        },
        "local_profiles": profiles,
        "architecture_contract": contract or {},
        "relevant_files": sorted({node.file_path for node in dependencies + dependents + tests})[:bounded_limit],
        "direct_dependencies": _candidate_summaries(dependencies)[:bounded_limit],
        "direct_dependents": _candidate_summaries(dependents)[:bounded_limit],
        "tests": _candidate_summaries(tests)[:bounded_limit],
        "interop_boundaries": sorted({item for profile in profiles for item in profile.get("interop") or []}),
        "confidence": profiles[0].get("confidence", "UNKNOWN") if profiles else "UNKNOWN",
        "warnings": base["warnings"] + conflicts + (["Cached advisory evidence was stale; live graph/source context was used."] if stale_seen else []),
    })
    if result_status in {"RESOLVED", "ADVISORY_STALE_FALLBACK_USED"}:
        target_path = primary.file_path
        if target_path and (repo / target_path).is_file():
            try:
                import time
                from _vnext_common import atomic_write_json
                cache_dir = repo / ".agents" / "cache"
                cache_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_json(cache_dir / "last-task-context.json", {
                    "file": target_path,
                    "timestamp": time.time(),
                })
            except Exception:
                pass
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--file")
    target.add_argument("--symbol")
    parser.add_argument("--module")
    parser.add_argument("--source-set")
    parser.add_argument("--limit", type=int, default=DEFAULT_NEIGHBOR_LIMIT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = resolve_task_context(
        Path(args.repo),
        file=args.file,
        symbol=args.symbol,
        module=args.module,
        source_set=args.source_set,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[{result['status']}] {result.get('query', '')}")
        target_info = result.get("target") or {}
        if target_info:
            print(f"  Path: {target_info.get('path')}")
            print(f"  Module/source set: {target_info.get('module')} / {target_info.get('source_set')}")
        for warning in result.get("warnings") or []:
            print(f"  Warning: {warning}")
    return 0 if result["status"] in {"RESOLVED", "AMBIGUOUS", "ADVISORY_STALE_FALLBACK_USED", "CONTEXT_CONFLICT_WITH_APPROVED_CONTRACT"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
