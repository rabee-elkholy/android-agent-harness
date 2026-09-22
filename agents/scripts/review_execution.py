"""Lightweight, read-only reviewer execution router and profile resolver."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, active_review_package_path, read_json
from review_policy import review_execution_requirements
from review_reasoning import capability_for_host, resolve_reasoning
from workflow import state_root, task_dir


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

    # Derive actual changed modules from immutable manifest
    module_count = 1
    manifest_path = Path(current.get("manifest") or "")
    if manifest_path.is_file():
        try:
            from plan_authority import changed_modules
            manifest_data = read_json(manifest_path)
            modules = changed_modules(repo, manifest_data)
            module_count = max(1, len(modules))
        except Exception:
            pass

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

    capability = capability_for_host(host)

    for rev, req in requirements.get("reviewers", {}).items():
        reasoning = resolve_reasoning(
            capability,
            req["reasoning_intent"],
        )

        brief_candidates = [
            d / f"brief-{rev}.md" for d in candidate_pkg_dirs
        ] + [
            d / "review-package.md" for d in candidate_pkg_dirs
        ]
        brief_file = next((str(p) for p in brief_candidates if p.is_file()), "")
        brief_text = ""
        if brief_file:
            try:
                brief_text = Path(brief_file).read_text(encoding="utf-8")
            except Exception:
                brief_text = ""

        resolved_reviewers[rev] = {
            **req,
            "reviewer_role": rev,
            "required_model": "inherit",
            "reasoning": reasoning,
            "dispatch_contract": {
                "model": "inherit",
                "reasoning_argument": reasoning["argument_name"],
                "reasoning_value": reasoning["native_value"],
            },
            "brief_path": brief_file,
            "brief_content": brief_text,
            "review_package_path": review_pkg_str,
            "evidence_footer_contract": "EVIDENCE pkg=<sha12> cites=<count>",
        }

    return {
        "schema_version": 2,
        "task_id": task_id,
        "round_number": round_number,
        "host": host,
        "model_policy": "INHERIT_PARENT_ONLY",
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
