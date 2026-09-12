"""Create one complete, immutable review package for the active vNext run."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, atomic_write_bytes, canonical_sha256, read_json, sha256_file, utc_now  # noqa: E402
from workflow import state_root, task_dir  # noqa: E402


HEADER = "# ANDROID_HARNESS_REVIEW_PACKAGE_VNEXT"
SECRET_PATH_MARKERS = (".env", "keystore", "jks", "secret", "token", "credentials", "local.properties")
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ttf", ".otf", ".wav", ".mp3", ".ogg", ".mp4", ".jar", ".aar", ".so", ".apk"}


def _git_diff(repo: Path, paths: list[str]) -> str:
    if not paths:
        return ""
    chunks: list[str] = []
    for offset in range(0, len(paths), 100):
        proc = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--full-index", "--find-renames", "--unified=10", "HEAD", "--", *paths[offset:offset + 100]],
            cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if proc.returncode != 0:
            raise ValidationError((proc.stderr or "git diff failed").strip())
        chunks.append(proc.stdout or "")
    return "".join(chunks)


def generate_review_topology(repo: Path, changed_paths: list[str]) -> str:
    try:
        from _graph_core import GraphEngine
        engine = GraphEngine(repo)
        engine.sync()
        graph = engine.graph

        touched_nodes = []
        for path in changed_paths:
            norm_p = path.replace("\\", "/").lower()
            for nid, node in graph.nodes.items():
                if node.file_path and node.file_path.replace("\\", "/").lower() == norm_p:
                    touched_nodes.append(node)

        ambiguous_matches: list[tuple[str, list[str]]] = []
        if not touched_nodes:
            for path in changed_paths:
                stem = Path(path).stem
                matches = graph.find_nodes(stem)
                matched_candidates = [
                    n for n in matches
                    if n.name.lower() == stem.lower()
                    or (n.file_path and Path(n.file_path).stem.lower() == stem.lower())
                ]
                if len(matched_candidates) == 1:
                    if matched_candidates[0] not in touched_nodes:
                        touched_nodes.append(matched_candidates[0])
                elif len(matched_candidates) > 1:
                    cands = [f"`{m.name}` [{m.file_path or 'unknown'}]" for m in matched_candidates[:4]]
                    ambiguous_matches.append((stem, cands))

        lines = [
            "## ARCHITECTURAL GRAPH & BLAST RADIUS TOPOLOGY",
            "*(Pre-computed architectural graph context extracted by GraphEngine)*",
            "",
        ]

        if ambiguous_matches:
            lines.append("### Topology Ambiguity Notice:")
            for stem, cands in ambiguous_matches:
                lines.append(f"- Symbol `{stem}` has multiple architectural candidates: {', '.join(cands)} (advisory only; inspect callers directly).")
            lines.append("")

        features = set()
        for node in touched_nodes:
            m = re.search(r"/(?:features|feature)/([a-zA-Z0-9_]+)/", node.file_path or "", re.I)
            if m:
                features.add(m.group(1))
        if features:
            lines.append(f"**Associated Features**: {', '.join(sorted(features))}")

        lines.append("\n### Touched Components & Architecture Layers:")
        if touched_nodes:
            for node in sorted(touched_nodes, key=lambda n: n.name):
                targets = [graph.nodes[t].name for t in graph.get_targets(node.id) if t in graph.nodes][:5]
                deps_str = f" -> [{', '.join(targets)}]" if targets else ""
                lines.append(f"- **{node.name}** (`{node.type}`) [{node.file_path or 'unknown'}]{deps_str}")
        else:
            lines.append("- *(No direct architectural nodes detected for changed paths; e.g. non-code or root config)*")

        lines.append("\n### Blast Radius (Immediate Callers & Upstream Consumers):")
        has_sources = False
        for node in touched_nodes:
            sources = [graph.nodes[s] for s in graph.get_sources(node.id) if s in graph.nodes]
            if sources:
                has_sources = True
                callers = [f"`{s.name}` (`{s.type}`, {s.file_path})" for s in sources[:6]]
                lines.append(f"- **Callers of {node.name}** ({len(sources)} total):")
                for c in callers:
                    lines.append(f"  * {c}")
        if not has_sources:
            lines.append("- Zero external callers detected in codebase graph (isolated leaf or new component).")

        lines.append("\n### Reviewer Call-Chain Guidance:")
        lines.append("- Inspect any identified callers or contract files directly with `view_file` (maximum 2 hops).")
        lines.append("- Topology guidance is advisory; inspect callers and related contracts directly when verifying cross-component impact.")
        lines.append("")
        return "\n".join(lines)
    except Exception as exc:
        return f"\n## ARCHITECTURAL GRAPH & BLAST RADIUS TOPOLOGY\n*(Graph slice generation notice: {exc})*\n"


def build_package(repo: Path, task_id: str) -> tuple[Path, dict]:
    directory = task_dir(repo, task_id)
    plan = read_json(directory / "plan.json")
    current = read_json(directory / "current-run.json")
    if plan.get("status") != "VERIFYING":
        raise ValidationError("review packaging requires a VERIFYING plan")
    manifest = read_json(Path(current["manifest"]))
    policy = read_json(Path(current["policy"]))
    changes = manifest.get("changes") or []
    paths = sorted({str(item.get("path") or "") for item in changes if item.get("path")} | {str(item.get("old_path") or "") for item in changes if item.get("old_path")})
    secret_paths = {rel for rel in paths if any(marker in rel.lower() for marker in SECRET_PATH_MARKERS)}
    diff = _git_diff(repo, [rel for rel in paths if rel not in secret_paths])
    extras: list[str] = []
    for rel in sorted(secret_paths):
        extras.append(f"\n## REDACTED FILE {rel}\n[Content redacted because the path may contain secrets.]\n")
    for item in changes:
        if item.get("status") not in ("A", "R"):
            continue
        rel = str(item.get("path") or "")
        path = repo / rel
        if rel in secret_paths:
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            extras.append(f"\n## BINARY FILE {rel}\n[Binary content: sha256={sha256_file(path)} size={path.stat().st_size}]\n")
            continue
        already_in_diff = f"+++ b/{rel}" in diff or f"diff --git a/{rel} b/{rel}" in diff
        if not already_in_diff:
            extras.append(f"\n## NEW UNTRACKED FILE {rel}\n")
            extras.append(path.read_text(encoding="utf-8", errors="replace"))
            extras.append("\n")
    metadata = {
        "schema_version": 1,
        "task_id": task_id,
        "run_id": current["run_id"],
        "plan_sha256": plan["plan_sha256"],
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "change_set_sha256": manifest["change_set_sha256"],
        "policy_sha256": policy["policy_sha256"],
        "required_reviewers": policy.get("reviewers") or [],
        "carried_reviews": policy.get("carried_reviews") or [],
        "surfaces": policy.get("surfaces") or [],
        "generated_at": utc_now(),
        "is_truncated": False,
        "changed_files": len(changes),
    }
    topology = generate_review_topology(repo, paths)
    content = "\n".join((HEADER, "```json", json.dumps(metadata, ensure_ascii=False, indent=2), "```", "", topology, "", "## Git diff", "```diff", diff, "```", *extras))
    package_dir = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"]
    package_path = package_dir / "review-package.md"
    if package_path.exists():
        raise ValidationError("review package already exists for this immutable run")
    atomic_write_bytes(package_path, content.encode("utf-8"))
    metadata["package_path"] = str(package_path)
    metadata["package_sha256"] = sha256_file(package_path)
    metadata["metadata_sha256"] = canonical_sha256({key: value for key, value in metadata.items() if key != "metadata_sha256"})
    return package_path, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", default=os.environ.get("HARNESS_TASK_ID"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.task:
        print("[FAIL] --task or HARNESS_TASK_ID is required", file=sys.stderr)
        return 1
    try:
        path, metadata = build_package(Path(args.repo).resolve(), args.task)
    except (ValidationError, OSError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    else:
        print(f"HARNESS_REVIEW_PACKAGE={path}")
        print(f"HARNESS_PACKAGE_SHA256={metadata['package_sha256']}")
        print(f"HARNESS_PACKAGE_SHA256_12={metadata['package_sha256'][:12]}")
        print(f"REQUIRED_REVIEWERS={','.join(metadata['required_reviewers']) or 'NONE'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
