"""Lightweight, read-only reviewer execution router and profile resolver."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, read_json
from review_policy import CAPABILITY_STANDARD, CAPABILITY_STRONG, review_execution_requirements
from workflow import state_root, task_dir


def load_host_model_routes(host: str) -> dict[str, str]:
    """Load trusted host model mapping from local config or environment.

    Fallback is empty dict (meaning all capabilities resolve to 'inherit').
    """
    host_key = host.lower().strip()
    env_routes = os.environ.get("HARNESS_MODEL_ROUTES")
    if env_routes:
        try:
            if env_routes.strip().startswith("{"):
                data = json.loads(env_routes)
                if host_key in data and isinstance(data[host_key], dict):
                    return data[host_key]
            else:
                p = Path(env_routes)
                if p.is_file():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if host_key in data and isinstance(data[host_key], dict):
                        return data[host_key]
        except Exception:
            pass

    user_file = Path.home() / ".android-harness" / "model_routes.json"
    if user_file.is_file():
        try:
            data = json.loads(user_file.read_text(encoding="utf-8"))
            if host_key in data and isinstance(data[host_key], dict):
                return data[host_key]
        except Exception:
            pass

    try:
        from _product import HOST_MODEL_ROUTES
        if isinstance(HOST_MODEL_ROUTES, dict) and host_key in HOST_MODEL_ROUTES:
            return {str(k).upper(): str(v) for k, v in HOST_MODEL_ROUTES[host_key].items()}
    except Exception:
        pass

    # Core default: no exact provider/model literal is required by core.
    # Unknown host or missing route config -> empty mapping -> inherit
    return {}


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

    env_escalation = os.environ.get("HARNESS_ALLOW_MODEL_ESCALATION")
    if env_escalation is not None:
        allow_escalation = env_escalation.strip().lower() in ("1", "true", "yes", "on")

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
    host_routes = load_host_model_routes(host)
    run_id = str(current.get("run_id") or "")
    snapshot = str(current.get("delivery_snapshot_sha256") or "")
    st_root = state_root(repo)

    candidate_pkg_dirs = []
    if snapshot and run_id:
        candidate_pkg_dirs.append(st_root / "runs" / snapshot / run_id)
    candidate_pkg_dirs.append(directory / f"review-{run_id}")
    candidate_pkg_dirs.append(directory)

    active_pkg_dir = next((d for d in candidate_pkg_dirs if d.is_dir()), candidate_pkg_dirs[0])

    resolved_reviewers = {}
    for rev, req in requirements.get("reviewers", {}).items():
        cap = req["requested_capability"]
        pref_model = "inherit"
        res_status = "INHERIT_FALLBACK"

        # Global Kill Switch: when escalation is disabled, ALL reviewers unconditionally inherit
        if not allow_escalation:
            pref_model = "inherit"
            res_status = "INHERIT_FALLBACK"
        elif cap == CAPABILITY_STRONG and host_routes.get("STRONG"):
            pref_model = host_routes["STRONG"]
            res_status = "TRUSTED_MAPPING" if pref_model != "inherit" else "INHERIT_FALLBACK"
        elif cap == CAPABILITY_STANDARD and host_routes.get("STANDARD"):
            pref_model = host_routes["STANDARD"]
            res_status = "TRUSTED_MAPPING" if pref_model != "inherit" else "STANDARD_MAPPING"
        else:
            pref_model = "inherit"
            res_status = "STANDARD_MAPPING" if cap == CAPABILITY_STANDARD else "INHERIT_FALLBACK"

        brief_candidates = [
            d / f"brief-{rev}.md" for d in candidate_pkg_dirs
        ] + [
            d / "review-package.md" for d in candidate_pkg_dirs
        ]
        brief_file = next((str(p) for p in brief_candidates if p.is_file()), "")

        resolved_reviewers[rev] = {
            **req,
            "preferred_model": pref_model,
            "fallback_model": "inherit",
            "resolution": res_status,
            "brief_path": brief_file,
        }

    return {
        "schema_version": 1,
        "task_id": task_id,
        "round_number": round_number,
        "host": host,
        "allow_model_escalation": allow_escalation,
        "package_dir": str(active_pkg_dir) if active_pkg_dir.is_dir() else "",
        "reviewers": resolved_reviewers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", default=os.environ.get("HARNESS_TASK_ID"))
    parser.add_argument("--host", default="antigravity", help="Target host environment")
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
        print(f"Task: {args.task} (Host: {args.host}, Escalation: {profile['allow_model_escalation']})")
        for rev, data in profile["reviewers"].items():
            print(f"  - {rev}: {data['preferred_model']} [{data['requested_capability']}] ({data['resolution']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
