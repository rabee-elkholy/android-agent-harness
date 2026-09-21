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


def package_is_same_or_parent(parent: str, child: str) -> bool:
    """Return True if parent is identical to or an ancestor package of child."""
    p_parts = [p for p in parent.strip().strip(".").split(".") if p]
    c_parts = [p for p in child.strip().strip(".").split(".") if p]
    if len(p_parts) > len(c_parts):
        return False
    return c_parts[:len(p_parts)] == p_parts


def path_scope_is_same_or_parent(parent_path: str, child_path: str) -> bool:
    """Return True if parent_path is identical to or an ancestor directory of child_path."""
    norm_parent = parent_path.strip().replace("\\", "/").strip("/")
    norm_child = child_path.strip().replace("\\", "/").strip("/")
    p_parts = [p for p in norm_parent.split("/") if p]
    c_parts = [p for p in norm_child.split("/") if p]
    if len(p_parts) > len(c_parts):
        return False
    return c_parts[:len(p_parts)] == p_parts


def _scope_matches_node(profile: dict[str, Any], node: GraphNode, node_source_set: str) -> bool:
    if profile.get("module") != node.module or profile.get("source_set") != node_source_set:
        return False
    paths = profile.get("paths") or []
    if node.file_path in paths:
        return True
    logical_scope = str(profile.get("logical_scope") or "").strip()
    if not logical_scope:
        return False
    if node.package and package_is_same_or_parent(logical_scope, node.package):
        return True
    scope_path = logical_scope.replace(".", "/")
    if path_scope_is_same_or_parent(scope_path, node.file_path):
        return True
    node_dir = Path(node.file_path).parent.as_posix()
    if path_scope_is_same_or_parent(scope_path, node_dir):
        return True
    file_parts = Path(node.file_path).as_posix().split("/")
    scope_parts = [p for p in scope_path.strip("/").split("/") if p]
    if scope_parts and len(file_parts) >= len(scope_parts):
        for idx in range(len(file_parts) - len(scope_parts) + 1):
            if file_parts[idx:idx + len(scope_parts)] == scope_parts:
                return True
    return False


def _matching_profiles(repo: Path, payload: dict[str, Any], node: GraphNode) -> tuple[list[dict[str, Any]], bool]:
    valid, _ = validate_advisory_knowledge(payload)
    if not valid:
        return [], False
    advisory = payload.get("advisory_knowledge") or {}
    node_source_set = _source_set(node.file_path)
    fresh: list[dict[str, Any]] = []
    stale_seen = False
    for profile in advisory.get("local_profiles") or []:
        if not _scope_matches_node(profile, node, node_source_set):
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


def _load_developer_instructions(repo: Path) -> list[dict[str, Any]]:
    path = repo / ".agents" / "project-context" / "developer-instructions.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("instructions"), list):
            return data["instructions"]
        return []
    except Exception:
        return []


def _instruction_matches_node(
    inst: dict[str, Any],
    node: GraphNode,
    node_source_set: str,
    profiles: list[dict[str, Any]],
) -> bool:
    if inst.get("status") != "ACTIVE":
        return False
    scope = inst.get("scope") or {}
    kind = str(scope.get("kind") or "GLOBAL").upper()
    val = str(scope.get("value") or "").strip()

    if kind == "GLOBAL" or val == "*":
        return True
    if kind == "MODULE":
        mod_norm = val if val.startswith(":") else f":{val}"
        return node.module == mod_norm or node.module == val
    if kind == "SOURCE_SET":
        return node_source_set.lower() == val.lower()
    if kind == "PACKAGE":
        return bool(node.package and package_is_same_or_parent(val, node.package))
    if kind == "PATH":
        return bool(path_scope_is_same_or_parent(val, node.file_path))
    if kind == "FEATURE":
        file_parts = Path(node.file_path).as_posix().split("/")
        return val in file_parts or any(val in str(p.get("logical_scope") or "") for p in profiles)
    if kind == "ARCH_FAMILY":
        return any(str(p.get("family_id")) == val for p in profiles)
    return False


def _detect_instruction_conflict(instructions: list[dict[str, Any]]) -> str | None:
    for i in range(len(instructions)):
        for j in range(i + 1, len(instructions)):
            i1 = instructions[i]
            i2 = instructions[j]
            s1 = i1.get("scope") or {}
            s2 = i2.get("scope") or {}
            if s1.get("kind") == s2.get("kind") and s1.get("value") == s2.get("value"):
                t1 = i1.get("text", "").lower()
                t2 = i2.get("text", "").lower()
                negatives = ("never", "do not", "must not", "don't", "avoid", "no ")
                positives = ("always", "must use", "require", "mandatory", "use ")
                has_neg_1 = any(n in t1 for n in negatives)
                has_pos_1 = any(p in t1 for p in positives)
                has_neg_2 = any(n in t2 for n in negatives)
                has_pos_2 = any(p in t2 for p in positives)
                if (has_neg_1 and has_pos_2) or (has_pos_1 and has_neg_2):
                    return f"Conflicting developer instructions '{i1.get('id')}' and '{i2.get('id')}' in same scope {s1.get('kind')}:{s1.get('value')}."
                if i1.get("strength") == "REQUIREMENT" and i2.get("strength") == "REQUIREMENT" and t1 != t2:
                    if ("mvi" in t1 and "mvvm" in t2) or ("mvvm" in t1 and "mvi" in t2):
                        return f"Conflicting developer architecture instructions '{i1.get('id')}' and '{i2.get('id')}' in scope {s1.get('kind')}:{s1.get('value')}."
                    if i1.get("conflict_with") == i2.get("id") or i2.get("conflict_with") == i1.get("id"):
                        return f"Explicitly conflicting instructions '{i1.get('id')}' and '{i2.get('id')}'."
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
    # Bounded test discovery
    all_test_nodes = [
        node for node in engine.graph.nodes.values()
        if _source_set(node.file_path).lower().startswith(("test", "androidtest"))
    ]
    target_names = {node.name for node in target_nodes}
    target_stems = {Path(node.file_path).stem for node in target_nodes}
    target_module = primary.module
    target_package = primary.package

    scored_candidates: list[tuple[int, GraphNode]] = []
    for test_node in all_test_nodes:
        score = 0
        if test_node.id in dependent_ids or test_node.id in dependency_ids:
            score += 100
        test_stem = Path(test_node.file_path).stem
        if any(t_name.lower() in test_node.name.lower() for t_name in target_names) or any(t_stem.lower() in test_stem.lower() for t_stem in target_stems):
            score += 50
        if test_node.module == target_module:
            score += 20
        if target_package and test_node.package and package_is_same_or_parent(target_package, test_node.package):
            score += 10
        if score > 0:
            scored_candidates.append((score, test_node))

    scored_candidates.sort(key=lambda item: (-item[0], item[1].file_path))
    test_candidates = [item[1] for item in scored_candidates]
    if not test_candidates:
        test_candidates = [n for n in all_test_nodes if n.module == target_module]

    MAX_OPEN_FILES = 30
    files_to_open = test_candidates[:MAX_OPEN_FILES]
    files_opened = len(files_to_open)
    tests = [
        node for node in files_to_open
        if any(target.name in (_safe_read(root / node.file_path)) for target in target_nodes)
    ]
    test_discovery_status = "BOUNDED_COMPLETE" if len(test_candidates) <= MAX_OPEN_FILES else "PARTIAL"

    facts_payload = _load_facts(root)
    profiles, stale_seen = _matching_profiles(root, facts_payload, primary)
    contract = _active_contract(root)
    conflicts: list[str] = []
    local_family_ids = {str(profile.get("family_id")) for profile in profiles if profile.get("family_id")}
    if contract and contract.get("mode") in {"PRESERVE", "REFACTOR"}:
        source_family = str(contract.get("source_family_id") or "")
        if source_family and local_family_ids and source_family not in local_family_ids:
            conflicts.append("Live local profile disagrees with the approved source architecture family.")

    # Load and match developer instructions
    all_instructions = _load_developer_instructions(root)
    matched_instructions = [
        inst for inst in all_instructions
        if _instruction_matches_node(inst, primary, _source_set(primary.file_path), profiles)
    ]
    inst_conflict = _detect_instruction_conflict(matched_instructions)
    if inst_conflict:
        conflicts.append(inst_conflict)

    if inst_conflict:
        result_status = "DEVELOPER_INSTRUCTION_CONFLICT"
    elif conflicts:
        result_status = "CONTEXT_CONFLICT_WITH_APPROVED_CONTRACT"
    elif stale_seen:
        result_status = "ADVISORY_STALE_FALLBACK_USED"
    else:
        result_status = "RESOLVED"

    target_surfaces: list[str] = []
    try:
        from change_classifier import classify
        cl = classify(root, task_changes=[{"path": primary.file_path}])
        target_surfaces = list(cl.get("surfaces") or [])
    except Exception:
        target_surfaces = []

    graph_fp = str(sync.get("graph_fingerprint") or getattr(engine, "graph_fingerprint", "") or "")
    graph_basis = {
        "used": True,
        "sync_mode": "incremental" if not sync.get("forced_full") else "full",
        "graph_fingerprint": graph_fp,
        "target_node_ids": sorted(target_ids),
        "dependency_nodes_considered": len(dependencies),
        "dependent_nodes_considered": len(dependents),
    }

    participating_modules = sorted({n.module for n in target_nodes + dependencies + dependents if n.module})
    is_public_contract = any("interface" in (n.type or "").lower() or "contract" in (n.name or "").lower() for n in target_nodes)
    dependents_truncated = len(dependents) > bounded_limit
    dependencies_truncated = len(dependencies) > bounded_limit

    graph_expansion_required = bool(
        dependents_truncated
        or (len(participating_modules) > 1 and is_public_contract)
    )
    expansion_action = None
    if graph_expansion_required:
        target_rep = primary.name or Path(primary.file_path).stem
        expansion_action = {
            "code": "RUN_PROJECT_GRAPH",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py graph --find {target_rep} --json",
        }

    res_modules = sorted(participating_modules)
    res_paths = sorted({primary.file_path} | {node.file_path for node in dependencies + dependents + tests})
    res_symbols = sorted({node.name for node in target_nodes + dependencies[:10] + dependents[:10]})
    receipt = None
    try:
        from discovery_receipt import create_discovery_receipt, save_discovery_receipt
        receipt = create_discovery_receipt(
            mode="TARGETED_GRAPH_CONTEXT",
            query_kind="file" if file else "symbol",
            query_value=query,
            graph_fingerprint=graph_fp,
            resolved_modules=res_modules,
            resolved_paths=res_paths,
            resolved_symbols=res_symbols,
        )
        save_discovery_receipt(root, receipt)
    except Exception:
        pass

    base.update({
        "status": result_status,
        "graph_basis": graph_basis,
        "graph_expansion_required": graph_expansion_required,
        "target": {
            "path": primary.file_path,
            "module": primary.module,
            "source_set": _source_set(primary.file_path),
            "package": primary.package,
            "candidate_surfaces": target_surfaces,
            "symbols": sorted({node.name for node in target_nodes}),
            "nodes": _candidate_summaries(target_nodes),
        },
        "developer_instructions": [
            {
                "id": inst["id"],
                "text": inst["text"],
                "scope": inst.get("scope", {}),
                "strength": inst.get("strength", "REQUIREMENT"),
                "applies_to": inst.get("applies_to", ["ANY"]),
                "sha256": inst.get("sha256", ""),
                "status": inst.get("status", "ACTIVE"),
            }
            for inst in matched_instructions
        ],
        "test_discovery": {
            "candidate_files": len(test_candidates),
            "files_opened": files_opened,
            "status": test_discovery_status,
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
    if receipt:
        base["discovery"] = receipt
    if expansion_action:
        base["recommended_action"] = expansion_action
    if result_status in {"RESOLVED", "ADVISORY_STALE_FALLBACK_USED"}:
        target_path = primary.file_path
        if target_path and (root / target_path).is_file():
            try:
                import time
                from _vnext_common import atomic_write_json
                id_material = f"{root.as_posix()}:{primary.file_path}:{primary.module}:{_source_set(primary.file_path)}:{query}"
                context_id = f"ctx-{hashlib.sha256(id_material.encode('utf-8')).hexdigest()[:16]}"
                base["context_id"] = context_id

                cache_dir = root / ".agents" / "cache" / "task-context"
                cache_dir.mkdir(parents=True, exist_ok=True)

                now = time.time()
                for cf in cache_dir.glob("ctx-*.json"):
                    try:
                        if now - cf.stat().st_mtime > 1800:
                            cf.unlink(missing_ok=True)
                    except OSError:
                        pass
                remaining = sorted(cache_dir.glob("ctx-*.json"), key=lambda p: p.stat().st_mtime)
                if len(remaining) > 50:
                    for old_p in remaining[:-50]:
                        try:
                            old_p.unlink(missing_ok=True)
                        except OSError:
                            pass

                cache_entry = {
                    "context_id": context_id,
                    "repo_path": root.as_posix(),
                    "target_file": primary.file_path,
                    "module": primary.module,
                    "source_set": _source_set(primary.file_path),
                    "query": query,
                    "timestamp": now,
                    "status": result_status,
                    "candidate_surfaces": target_surfaces,
                    "developer_instructions": base.get("developer_instructions", []),
                }
                atomic_write_json(cache_dir / f"{context_id}.json", cache_entry)
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
    return 0 if result["status"] in {"RESOLVED", "AMBIGUOUS", "ADVISORY_STALE_FALLBACK_USED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
