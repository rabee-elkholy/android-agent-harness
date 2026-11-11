"""Headless JVM UI & RTL layout bounds verification via Roborazzi `.uitree.json` sidecars.

Auto-detects `io.github.takahirom.roborazzi` in project Gradle configurations (silent 0 ms
no-op when absent), inspects deterministic `.uitree.json` files for viewport/RTL clipping,
zero-dimension visible controls, and interactive sibling collisions, and records compact
mathematical UI bounds evidence into `EvidenceStore` for specialist reviewers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _repo_files import repo_glob  # noqa: E402
from _vnext_common import ValidationError  # noqa: E402

ROBORAZZI_MARKER_RE = re.compile(r"io\.github\.takahirom\.roborazzi|roborazzi-gradle-plugin|roborazzi-compose", re.I)


def detect_roborazzi(repo: Path) -> dict[str, Any]:
    """Detect Roborazzi plugin/dependency presence across root and module Gradle files."""
    modules_with_roborazzi: list[str] = []
    preview_scanner = False
    for gf in sorted(repo_glob(repo, "**/build.gradle*"))[:50]:
        if not gf.is_file():
            continue
        try:
            txt = gf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "composablepreviewscanner" in txt.lower():
            preview_scanner = True
        if ROBORAZZI_MARKER_RE.search(txt):
            rel_parent = gf.parent.relative_to(repo).as_posix()
            mod_name = ":" if rel_parent in ("", ".") else ":" + rel_parent.replace("/", ":")
            if mod_name not in modules_with_roborazzi:
                modules_with_roborazzi.append(mod_name)

    toml = repo / "gradle" / "libs.versions.toml"
    in_catalog = False
    if toml.is_file():
        try:
            t_txt = toml.read_text(encoding="utf-8", errors="replace")
            in_catalog = bool(ROBORAZZI_MARKER_RE.search(t_txt))
            if "composablepreviewscanner" in t_txt.lower():
                preview_scanner = True
        except OSError:
            pass

    uitree_files = [
        p.relative_to(repo).as_posix()
        for p in sorted(repo_glob(repo, "**/*.uitree.json"))
        if p.is_file()
    ]
    return {
        "installed": bool(modules_with_roborazzi or in_catalog),
        "modules": modules_with_roborazzi,
        "composable_preview_scanner": preview_scanner,
        "uitree_files": uitree_files[:50],
    }


def _flatten_nodes(
    node: dict[str, Any],
    out: list[dict[str, Any]],
    *,
    parent_children_siblings: list[dict[str, Any]] | None = None,
) -> None:
    if not isinstance(node, dict):
        return
    bounds = node.get("bounds")
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    actions = node.get("actions") if isinstance(node.get("actions"), list) else []
    label = str(
        node.get("testTag")
        or props.get("Text")
        or props.get("ContentDescription")
        or node.get("resourceId")
        or ""
    ).strip()
    entry = {
        "n": node.get("n"),
        "type": str(node.get("type") or ""),
        "label": label[:80],
        "bounds": bounds if (isinstance(bounds, list) and len(bounds) == 4) else None,
        "clickable": "OnClick" in actions,
    }
    if entry["label"] or entry["n"] is not None:
        out.append(entry)
    children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
    if parent_children_siblings is not None and len(children) >= 2:
        parent_children_siblings.append({"children": children})
    for child in children:
        _flatten_nodes(child, out, parent_children_siblings=parent_children_siblings)


def _overlap_ratio(b1: list[int | float], b2: list[int | float]) -> float:
    l1, t1, r1, btm1 = b1
    l2, t2, r2, btm2 = b2
    iw = max(0.0, float(min(r1, r2)) - float(max(l1, l2)))
    ih = max(0.0, float(min(btm1, btm2)) - float(max(t1, t2)))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    a1 = max(1.0, float(r1 - l1) * float(btm1 - t1))
    a2 = max(1.0, float(r2 - l2) * float(btm2 - t2))
    return inter / min(a1, a2)


def inspect_uitree_files(repo: Path, uitree_paths: list[Path] | None = None) -> dict[str, Any]:
    """Audit Roborazzi `.uitree.json` sidecars for deterministic bounds & clipping defects."""
    if uitree_paths is None:
        uitree_paths = [p for p in sorted(repo_glob(repo, "**/*.uitree.json")) if p.is_file()]

    issues: list[dict[str, Any]] = []
    digests: list[str] = []
    scanned = 0

    for up in uitree_paths[:30]:
        try:
            doc = json.loads(up.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("root"), dict):
            continue
        scanned += 1
        rel = up.relative_to(repo).as_posix() if up.is_relative_to(repo) else up.name
        root = doc["root"]
        capture = doc.get("capture") if isinstance(doc.get("capture"), dict) else {}
        scale = float(capture.get("scale") or 1.0) or 1.0
        root_bounds = root.get("bounds")
        if isinstance(root_bounds, list) and len(root_bounds) == 4:
            vp_left, vp_top, vp_right, vp_bottom = [float(x) for x in root_bounds]
        else:
            vp_left, vp_top = 0.0, 0.0
            vp_right = float(capture.get("imageWidth") or 1080) / scale
            vp_bottom = float(capture.get("imageHeight") or 2400) / scale

        flat: list[dict[str, Any]] = []
        sibling_groups: list[dict[str, Any]] = []
        _flatten_nodes(root, flat, parent_children_siblings=sibling_groups)

        sample_nodes: list[str] = []
        for item in flat:
            b = item["bounds"]
            if not b:
                continue
            left, top, right, bottom = [float(x) for x in b]
            w = right - left
            h = bottom - top
            lbl = item["label"] or f"node#{item['n']}"
            if len(sample_nodes) < 6:
                sample_nodes.append(f"`{lbl}`[{int(left)},{int(top)},{int(right)},{int(bottom)}]")
            if w <= 0 or h <= 0:
                issues.append({
                    "code": "ZERO_DIMENSION_NODE",
                    "file": rel,
                    "node": lbl,
                    "bounds": b,
                    "detail": f"Visible UI node '{lbl}' rendered with zero/negative size ({w}x{h}).",
                })
            elif left < vp_left - 2 or right > vp_right + 2:
                issues.append({
                    "code": "HORIZONTAL_VIEWPORT_CLIP",
                    "file": rel,
                    "node": lbl,
                    "bounds": b,
                    "viewport": [vp_left, vp_top, vp_right, vp_bottom],
                    "detail": f"UI node '{lbl}' bounds [{int(left)}..{int(right)}] clip horizontal viewport [{int(vp_left)}..{int(vp_right)}] (check RTL/padding).",
                })

        for grp in sibling_groups:
            clickables = []
            for ch in grp["children"]:
                acts = ch.get("actions") if isinstance(ch.get("actions"), list) else []
                cb = ch.get("bounds")
                if "OnClick" in acts and isinstance(cb, list) and len(cb) == 4:
                    p = ch.get("properties") if isinstance(ch.get("properties"), dict) else {}
                    clbl = str(ch.get("testTag") or p.get("Text") or ch.get("n") or "clickable")
                    clickables.append((clbl, cb))
            for idx_a in range(len(clickables)):
                for idx_b in range(idx_a + 1, len(clickables)):
                    la, ba = clickables[idx_a]
                    lb, bb = clickables[idx_b]
                    ratio = _overlap_ratio(ba, bb)
                    if ratio > 0.25:
                        issues.append({
                            "code": "CLICKABLE_SIBLING_COLLISION",
                            "file": rel,
                            "nodes": [la, lb],
                            "overlap_ratio": round(ratio, 2),
                            "detail": f"Interactive siblings '{la}' and '{lb}' overlap by {int(ratio * 100)}%.",
                        })

        digests.append(f"{Path(rel).name}: " + (", ".join(sample_nodes) if sample_nodes else "clean root"))

    return {
        "status": "FAIL" if issues else ("PASS" if scanned > 0 else "NO_UITREE_FILES"),
        "scanned_files": scanned,
        "issues": issues[:30],
        "digests": digests[:12],
    }


def run_roborazzi_verify(repo: Path, module: str | None = None) -> tuple[int, dict[str, Any]]:
    info = detect_roborazzi(repo)
    if not info["installed"]:
        return 0, {"status": "SKIPPED", "reason": "Roborazzi is not configured in this repository."}

    target_mod = module or (info["modules"][0] if info["modules"] else ":app")
    if target_mod == ":":
        gradle_task = "verifyRoborazziDebug"
    else:
        gradle_task = f"{target_mod.rstrip(':')}:verifyRoborazziDebug"

    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "run_gradle_task.py"), gradle_task, "-Proborazzi.dumpUiTree=true"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    tree_audit = inspect_uitree_files(repo)
    ok = (proc.returncode == 0) and (tree_audit["status"] != "FAIL")
    status = "PASS" if ok else ("ENV" if proc.returncode == 30 else "FAIL")
    payload = {
        "schema_version": 1,
        "producer": "roborazzi_gate",
        "status": status,
        "exit_code": 0 if ok else (30 if proc.returncode == 30 else 1),
        "git_sha": current_head_sha(repo),
        "gradle_task": gradle_task,
        "uitree_audit": tree_audit,
        "detail": (
            f"{gradle_task} passed ({tree_audit['scanned_files']} uitree sidecar(s) verified)"
            if ok else f"{gradle_task} rc={proc.returncode}, issues={len(tree_audit['issues'])}"
        ),
    }
    write_gate_result("roborazzi_ui", payload)
    return (0 if ok else payload["exit_code"]), payload


def auto_collect_after_unit_tests(repo: Path, surfaces: list[str] | set[str]) -> dict[str, Any] | None:
    """Automatically audit fresh `.uitree.json` sidecars when UI surfaces run unit tests."""
    if not ({"COMPOSE_UI", "XML_UI"} & set(surfaces)):
        return None
    info = detect_roborazzi(repo)
    if not info["installed"] and not info["uitree_files"]:
        return None
    audit = inspect_uitree_files(repo)
    if audit["scanned_files"] == 0:
        return None
    ok = audit["status"] == "PASS"
    payload = {
        "schema_version": 1,
        "producer": "roborazzi_gate",
        "status": "PASS" if ok else "FAIL",
        "exit_code": 0 if ok else 1,
        "git_sha": current_head_sha(repo),
        "uitree_audit": audit,
        "detail": (
            f"{audit['scanned_files']} Roborazzi uitree sidecar(s) bounds-verified"
            if ok else f"Roborazzi uitree bounds defects: {len(audit['issues'])}"
        ),
    }
    write_gate_result("roborazzi_ui", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capabilities", "verify", "inspect-tree"))
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("HARNESS_REPO") or Path(__file__).resolve().parents[2]))
    parser.add_argument("--module", help="Optional Gradle module path (e.g. :app or :feature:food)")
    parser.add_argument("--paths", nargs="*", help="Optional explicit .uitree.json file paths")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    try:
        if args.action == "capabilities":
            print(json.dumps(detect_roborazzi(repo), ensure_ascii=False, indent=2))
            return 0
        if args.action == "inspect-tree":
            explicit = [Path(p) if Path(p).is_absolute() else (repo / p) for p in args.paths] if args.paths else None
            audit = inspect_uitree_files(repo, explicit)
            print(json.dumps(audit, ensure_ascii=False, indent=2))
            return 1 if audit["status"] == "FAIL" else 0
        rc, payload = run_roborazzi_verify(repo, args.module)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return rc
    except (OSError, ValueError, ValidationError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
