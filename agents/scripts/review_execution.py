"""Lightweight, read-only reviewer execution router and profile resolver."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, read_json
from review_policy import review_execution_requirements
from workflow import state_root, task_dir

ANTIGRAVITY_MODEL_MAP = {
    "STANDARD": "flash",
    "STRONG": "pro",
}


def resolve_execution_profile(repo: Path, task_id: str, host: str = "antigravity") -> dict:
    state = state_root(repo)
    directory = task_dir(repo, task_id)
    plan_path = directory / "plan.json"
    current_path = directory / "current-run.json"
    if not plan_path.is_file() or not current_path.is_file():
        raise ValidationError(f"task '{task_id}' state is missing plan or current-run")

    plan = read_json(plan_path)
    current = read_json(current_path)
    policy = read_json(Path(current["policy"]))

    try:
        from _product import ALLOW_MODEL_ESCALATION
        allow_escalation = bool(ALLOW_MODEL_ESCALATION)
    except Exception:
        allow_escalation = False

    requirements = review_execution_requirements(policy, plan=plan)
    resolved_reviewers = {}
    for rev, req in requirements.get("reviewers", {}).items():
        cap = req["requested_capability"]
        if host.lower() == "antigravity":
            if allow_escalation and cap == "STRONG":
                pref_model = ANTIGRAVITY_MODEL_MAP.get("STRONG", "pro")
                res_status = "TRUSTED_MAPPING"
            else:
                pref_model = "inherit"
                res_status = "INHERIT_FALLBACK" if cap == "STRONG" else "STANDARD_MAPPING"
        else:
            pref_model = "inherit"
            res_status = "INHERIT_FALLBACK"

        resolved_reviewers[rev] = {
            **req,
            "preferred_model": pref_model,
            "fallback_model": "inherit",
            "resolution": res_status,
        }

    return {
        "schema_version": 1,
        "task_id": task_id,
        "host": host,
        "allow_model_escalation": allow_escalation,
        "reviewers": resolved_reviewers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", default=os.environ.get("HARNESS_TASK_ID"))
    parser.add_argument("--host", default="antigravity", help="Target host environment")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
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
        print(f"Task: {args.task} (Host: {args.host}, Escalation: {profile['allow_model_escalation']})")
        for rev, data in profile["reviewers"].items():
            print(f"  - {rev}: {data['preferred_model']} [{data['requested_capability']}] ({data['resolution']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
