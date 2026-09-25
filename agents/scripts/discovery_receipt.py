"""Discovery Receipt and Scope Tracking for Graph-First Discovery.

Standard library only. Manages machine-readable discovery receipts, scope boundaries,
and discovery freshness validation across Project Graph and Task Context.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DISCOVERY_CACHE_SUBDIR = Path(".agents") / "cache" / "discovery"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_receipt_id(mode: str, query_kind: str, query_value: str, graph_fp: str) -> str:
    raw = f"{mode}:{query_kind}:{query_value}:{graph_fp}"
    h = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"disc-{h}"


def compute_allowed_search_roots(
    resolved_paths: list[str],
    resolved_modules: list[str] | None = None,
    *,
    include_module_roots: bool = True,
) -> list[str]:
    """Search roots granted by a discovery. Whole-module roots are granted only when the
    discovery itself was about that module; a file, symbol or architecture anchor stays
    within the directories the graph returned."""
    roots: set[str] = set()
    for p_str in resolved_paths:
        norm = str(p_str).replace("\\", "/").strip().lstrip("/")
        if not norm:
            continue
        roots.add(norm)
        p = Path(norm)
        parent = p.parent.as_posix()
        if parent and parent != ".":
            roots.add(parent)
            grandparent = Path(parent).parent.as_posix()
            # If parent is something like 'com/example/feature/profile', grandparent is also useful
            if grandparent and grandparent != ".":
                # Only add if it's within feature / src structure
                parts = grandparent.split("/")
                if any(part in {"feature", "features", "ui", "domain", "data", "presentation"} for part in parts):
                    roots.add(grandparent)

    if resolved_modules and include_module_roots:
        for mod in resolved_modules:
            m_norm = mod.strip().lstrip(":").replace(":", "/")
            if m_norm:
                roots.add(m_norm)

    return sorted(roots)


def create_discovery_receipt(
    mode: str,
    query_kind: str,
    query_value: str,
    graph_fingerprint: str,
    resolved_modules: list[str],
    resolved_paths: list[str],
    resolved_symbols: list[str],
    allowed_search_roots: list[str] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    norm_modules = sorted({str(m) for m in resolved_modules if str(m).strip()})
    norm_paths = sorted({str(p).replace("\\", "/").strip().lstrip("/") for p in resolved_paths if str(p).strip()})
    norm_symbols = sorted({str(s).strip() for s in resolved_symbols if str(s).strip()})

    if allowed_search_roots is None:
        search_roots = compute_allowed_search_roots(
            norm_paths, norm_modules, include_module_roots=str(query_kind).lower() == "module",
        )
    else:
        search_roots = sorted({str(r).replace("\\", "/").strip().lstrip("/") for r in allowed_search_roots if str(r).strip()})

    receipt_id = compute_receipt_id(mode, query_kind, query_value, graph_fingerprint)
    return {
        "id": receipt_id,
        "mode": mode,
        "query": {
            "kind": query_kind,
            "value": query_value,
        },
        "graph_fingerprint": graph_fingerprint,
        "resolved_modules": norm_modules,
        "resolved_paths": norm_paths,
        "resolved_symbols": norm_symbols,
        "allowed_search_roots": search_roots,
        "created_at": created_at or _utc_iso(),
    }


def save_discovery_receipt(repo: Path, receipt: dict[str, Any]) -> Path:
    disc_dir = repo / DISCOVERY_CACHE_SUBDIR
    disc_dir.mkdir(parents=True, exist_ok=True)
    rec_id = str(receipt.get("id") or "")
    if not rec_id:
        rec_id = compute_receipt_id(
            str(receipt.get("mode") or ""),
            str((receipt.get("query") or {}).get("kind") or ""),
            str((receipt.get("query") or {}).get("value") or ""),
            str(receipt.get("graph_fingerprint") or ""),
        )
        receipt["id"] = rec_id

    file_path = disc_dir / f"{rec_id}.json"
    content = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    file_path.write_text(content, encoding="utf-8")

    latest_file = disc_dir / "latest-discovery.json"
    latest_file.write_text(content, encoding="utf-8")
    return file_path


def load_discovery_receipt(repo: Path, receipt_id: str) -> dict[str, Any] | None:
    disc_dir = repo / DISCOVERY_CACHE_SUBDIR
    rec_path = disc_dir / f"{receipt_id}.json"
    if not rec_path.is_file():
        return None
    try:
        data = json.loads(rec_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


# Set by the tool hook to the start of the calling conversation: a receipt written before it came
# from an earlier conversation and grants no scope in this one. None keeps the age check only.
RECEIPT_NOT_BEFORE: float | None = None


def load_latest_discovery_receipt(repo: Path, max_age_seconds: float = 3600.0) -> dict[str, Any] | None:
    disc_dir = repo / DISCOVERY_CACHE_SUBDIR
    latest_file = disc_dir / "latest-discovery.json"
    if not latest_file.is_file():
        candidates = sorted(disc_dir.glob("disc-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return None
        latest_file = candidates[0]

    try:
        st = latest_file.stat()
        if max_age_seconds > 0 and (time.time() - st.st_mtime) > max_age_seconds:
            return None
        if RECEIPT_NOT_BEFORE is not None and st.st_mtime < RECEIPT_NOT_BEFORE:
            return None
        data = json.loads(latest_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def is_path_in_discovery_scope(repo: Path, target_path: str | Path, receipt: dict[str, Any]) -> bool:
    """Checks if a search target path or directory falls within the receipt's discovered scope."""
    if not receipt:
        return False
    repo_root = repo.resolve()
    target_str = str(target_path).replace("\\", "/").strip().rstrip("/")
    if not target_str or target_str in {".", "./"}:
        return False

    try:
        p = Path(target_str)
        if p.is_absolute():
            rel = p.resolve().relative_to(repo_root).as_posix().lower()
        else:
            rel = target_str.lstrip("./").lower()
    except Exception:
        rel = target_str.lstrip("./").lower()

    allowed_roots = [str(r).lower().rstrip("/") for r in receipt.get("allowed_search_roots") or []]
    resolved_paths = [str(rp).lower() for rp in receipt.get("resolved_paths") or []]

    # Exact match on resolved path
    if rel in resolved_paths:
        return True

    # Search target is inside one of the allowed search roots
    for root in allowed_roots:
        if not root:
            continue
        if rel == root or rel.startswith(root + "/"):
            return True
        # Or root is inside target if target is a specific enclosing package
        if root.startswith(rel + "/") and len(rel.split("/")) >= 4:
            return True

    return False


def check_discovery_freshness(repo: Path, receipt: dict[str, Any]) -> tuple[bool, str]:
    """Validates that a discovery receipt is still fresh with respect to the repository."""
    if not receipt:
        return False, "DISCOVERY_RECEIPT_MISSING"

    query = receipt.get("query") or {}
    q_kind = str(query.get("kind") or "")
    q_val = str(query.get("value") or "")

    # 1. If query target was an exact file, assert file still exists
    if q_kind == "file" and q_val:
        f_path = repo / q_val
        if not f_path.is_file():
            return False, f"PRIMARY_TARGET_MISSING: exact file '{q_val}' was deleted or moved"

    # 2. Check that at least primary resolved paths still exist
    resolved_paths = receipt.get("resolved_paths") or []
    if resolved_paths:
        missing_paths = [p for p in resolved_paths[:3] if not (repo / p).is_file()]
        if len(missing_paths) == len(resolved_paths[:3]):
            return False, f"PRIMARY_TARGET_MISSING: all primary paths {missing_paths} are missing"

    # 3. The graph the receipt was computed from must still be the current graph.
    receipt_fp = str(receipt.get("graph_fingerprint") or "").strip()
    current_fp = current_graph_fingerprint(repo)
    if receipt_fp and current_fp and receipt_fp != current_fp:
        return False, f"GRAPH_CHANGED: receipt graph {receipt_fp[:12]} is not the current graph {current_fp[:12]}; query the graph again"

    return True, "FRESH"


def current_graph_fingerprint(repo: Path) -> str:
    """Fingerprint of the last saved project graph, from its sidecar ('' when unknown)."""
    for cache in (repo / ".agents" / "cache" / "project_graph.json", repo / "agents" / "cache" / "project_graph.json"):
        sidecar = cache.with_name(cache.name + ".fingerprint")
        try:
            if sidecar.is_file():
                return sidecar.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def clear_latest_discovery_receipt(repo: Path) -> None:
    """Forget the latest discovery so a finished task's anchor does not carry into the next task."""
    disc_dir = repo / DISCOVERY_CACHE_SUBDIR
    for path in [disc_dir / "latest-discovery.json", *disc_dir.glob("disc-*.json")]:
        try:
            path.unlink()
        except OSError:
            pass


cache_discovery_receipt = save_discovery_receipt
