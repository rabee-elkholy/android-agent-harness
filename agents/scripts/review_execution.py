"""Lightweight, read-only reviewer execution router and profile resolver."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, active_review_package_path, read_json
from policy_vocab import ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS
from review_policy import review_execution_requirements
from review_reasoning import HostReasoningCapability, capability_for_host, resolve_reasoning
from workflow import state_root, task_dir


def _resolve_changed_module_count(repo: Path, manifest: dict, plan: dict, policy: dict) -> dict:
    try:
        from plan_authority import changed_modules
        mods = changed_modules(repo, manifest)
        if mods:
            return {"count": max(1, len(mods)), "source": "graph"}
    except Exception:
        pass

    try:
        changes = manifest.get("task_changes") or manifest.get("changes") or []
        inferred = set()
        for change in changes:
            p = change.get("path") if isinstance(change, dict) else str(change)
            if p:
                parts = p.replace("\\", "/").strip("/").split("/")
                if len(parts) > 1:
                    inferred.add(parts[0])
                else:
                    inferred.add(":")
        if inferred:
            return {"count": max(1, len(inferred)), "source": "manifest"}
    except Exception:
        pass

    try:
        exp_mods = plan.get("expected_modules") or []
        if exp_mods:
            return {"count": max(1, len(exp_mods)), "source": "plan"}
    except Exception:
        pass

    surfaces = set(policy.get("surfaces") or manifest.get("surfaces") or plan.get("expected_surfaces") or [])
    sensitive = {"NAVIGATION", "PUBLIC_API", "ARCHITECTURE"}
    if surfaces.intersection(sensitive):
        return {"count": 2, "source": "conservative"}

    return {"count": 1, "source": "conservative"}


def resolve_execution_profile(repo: Path, task_id: str, host: str = "generic") -> dict:
    state = state_root(repo)
    directory = task_dir(repo, task_id)
    plan_path = directory / "plan.json"
    current_path = directory / "current-run.json"
    if not plan_path.is_file() or not current_path.is_file():
        raise ValidationError(f"task '{task_id}' state is missing plan or current-run")

    plan = read_json(plan_path)
    current = read_json(current_path)
    policy = read_json(Path(current["policy"]))
    protocol = int(current.get("review_protocol_version") or 1)

    manifest_path = Path(current.get("manifest") or "")
    manifest_data = read_json(manifest_path) if manifest_path.is_file() else {}
    mod_info = _resolve_changed_module_count(repo, manifest_data, plan, policy)
    module_count = mod_info["count"]

    round_number = int(policy.get("review_round") or (((plan or {}).get("review_rounds") or 0) + 1))
    requirements = review_execution_requirements(
        policy,
        plan=plan,
        round_number=round_number,
        changed_modules_count=module_count,
    )

    run_id = str(current.get("run_id") or "")
    snapshot = str(current.get("delivery_snapshot_sha256") or "")
    st_root = state_root(repo)

    canonical_pkg_path = active_review_package_path(repo, current)
    candidate_pkg_dirs = [canonical_pkg_path.parent]
    if snapshot and run_id:
        candidate_pkg_dirs.append(st_root / "runs" / snapshot / run_id)
    candidate_pkg_dirs.append(directory / f"review-{run_id}")
    candidate_pkg_dirs.append(directory)

    active_pkg_dir = next((d for d in candidate_pkg_dirs if d.is_dir()), canonical_pkg_path.parent)

    resolved_reviewers = {}
    review_pkg_file = canonical_pkg_path if canonical_pkg_path.is_file() else active_pkg_dir / "review-package.md"
    review_pkg_str = str(review_pkg_file) if review_pkg_file.is_file() else ""

    try:
        capability = capability_for_host(host)
    except Exception as exc:
        capability = HostReasoningCapability(
            host=host,
            supported=False,
            argument_name=None,
            ordered_levels=(),
            current_level=None,
            source=f"capability_probe_failed:{type(exc).__name__}",
        )

    for rev, req in requirements.get("reviewers", {}).items():
        reasoning = resolve_reasoning(
            capability,
            req["reasoning_intent"],
        )

        brief_file = ""
        brief_text = ""
        if protocol >= 2:
            exact_brief = canonical_pkg_path.parent / f"brief-{rev}.md"
            if exact_brief.is_file():
                brief_file = str(exact_brief)
                try:
                    brief_text = exact_brief.read_text(encoding="utf-8")
                except Exception:
                    brief_text = ""
        else:
            brief_candidates = [
                d / f"brief-{rev}.md" for d in candidate_pkg_dirs
            ] + [
                d / "review-package.md" for d in candidate_pkg_dirs
            ]
            brief_file = next((str(p) for p in brief_candidates if p.is_file()), "")
            if brief_file:
                try:
                    brief_text = Path(brief_file).read_text(encoding="utf-8")
                except Exception:
                    brief_text = ""

        rev_entry = {
            **req,
            "reviewer_role": rev,
            "reasoning": reasoning,
            "dispatch_contract": {
                "model_policy": "INHERIT_PARENT_BY_OMISSION",
                "model_argument": None,
                "reasoning_argument": reasoning["argument_name"],
                "reasoning_value": reasoning["native_value"],
            },
            "brief_path": brief_file,
            "brief_content": brief_text,
            "review_package_path": review_pkg_str,
            "output_contract": "HARNESS_REVIEW_RESULT_V2",
            "v2_output_contract": "HARNESS_REVIEW_RESULT_V2",
        }
        is_antigravity = (
            str(host).strip().lower() == "antigravity"
            or str(current.get("review_host") or "").strip().lower() == "antigravity"
        )
        if is_antigravity or protocol >= 2:
            rev_entry.pop("required_model", None)
            rev_entry["model_policy"] = "INHERIT_PARENT_BY_OMISSION"
            rev_entry["model_argument"] = None
        else:
            rev_entry["required_model"] = "inherit"
        resolved_reviewers[rev] = rev_entry

    return {
        "schema_version": 2,
        "task_id": task_id,
        "round_number": round_number,
        "host": host,
        "model_policy": "INHERIT_PARENT_BY_OMISSION",
        "dispatch_contract": {
            "tool": "invoke_subagent",
            "subagent_allowed_keys": list(ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS),
            "workspace_policy": "inherit_or_omit",
            "model_policy": "INHERIT_PARENT_BY_OMISSION",
            "model_argument": None,
            "reasoning_argument": None,
        },
        "package_dir": str(active_pkg_dir) if active_pkg_dir.is_dir() else "",
        "reviewers": resolved_reviewers,
    }



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", default=os.environ.get("HARNESS_TASK_ID"))
    parser.add_argument("--host", default="generic", help="Target host environment")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args(argv)
    if not args.task:
        print("[FAIL] --task or HARNESS_TASK_ID is required", file=sys.stderr)
        return 1
    try:
        profile = resolve_execution_profile(Path(args.repo).resolve(), args.task, host=args.host)
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(profile, indent=2))
    else:
        print(f"Task: {args.task} (Host: {args.host}, Model: inherit-parent)")
        for rev, data in profile["reviewers"].items():
            effort = data.get("reasoning_intent", "NORMAL")
            res = (data.get("reasoning") or {}).get("resolution", "HOST_CONTROL_UNAVAILABLE")
            print(f"\n{rev}:")
            print(f"  effort={effort}")
            print(f"  reasoning={res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
