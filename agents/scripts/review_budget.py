"""Task-local reviewer spending authority, separate from immutable verification policy."""
from __future__ import annotations

from _vnext_common import ValidationError, atomic_write_json, canonical_sha256, read_json, state_root, utc_now, validate_id


def forecast_review_calls(plan, policy):
    """Advisory planning estimate; never changes the setup limit or selects reviewers."""
    from review_policy import _configured_model_call_budget
    from phase_review import is_documentation_path
    limit = int(policy.get("model_call_budget") or _configured_model_call_budget())
    phases = plan.get("phases") or []
    enabled = plan.get("scoped_phase_review_enabled")
    phase_estimates = []
    for phase in phases:
        paths = phase.get("expected_files") or []
        docs_only = bool(paths) and all(is_documentation_path(path) for path in paths)
        calls = 2 if enabled is not False and (len(phases) > 1 or enabled is True) and not docs_only else 0
        phase_estimates.append({"phase_id": phase["id"], "calls": calls})
    phase_calls = sum(item["calls"] for item in phase_estimates)
    final_calls = len(set(policy.get("reviewers") or []))
    reserve = max(final_calls, 2 if phase_calls else 0)
    first_pass = phase_calls + final_calls
    total = first_pass + reserve
    return {"schema_version": 1, "scope": "SHARED_TASK", "configured_limit": limit,
            "phase_estimates": phase_estimates, "phase_calls_estimate": phase_calls,
            "final_calls_estimate": final_calls, "correction_reserve": reserve,
            "estimated_first_pass": first_pass, "estimated_total_with_reserve": total,
            "status": "INSUFFICIENT_FIRST_PASS" if first_pass > limit else "HEADROOM_LIMITED" if total > limit else "WITHIN_LIMIT"}


def forecast_summary(forecast):
    summary = (f"Reviewer calls: shared task cap {forecast['configured_limit']} from setup; "
            f"phase estimate {forecast['phase_calls_estimate']} + final estimate {forecast['final_calls_estimate']} "
            f"+ correction reserve {forecast['correction_reserve']} = {forecast['estimated_total_with_reserve']} "
            f"({forecast['status']}). Advisory; the setup limit is unchanged.")
    if forecast['status'] != 'WITHIN_LIMIT':
        summary += (" Discuss insufficient headroom before implementation; any increase needs an explicit developer "
                    "spending decision through task review-budget. Plan approval alone does not raise the limit.")
    return summary


def effective_review_budget(repo, plan, policy=None):
    from review_policy import _configured_model_call_budget
    default = int((policy or {}).get("model_call_budget") or plan.get("max_review_calls")
                  or plan.get("model_call_budget") or _configured_model_call_budget())
    if repo is None or not plan.get("task_id"):
        return default
    path = state_root(repo) / "tasks" / validate_id(plan["task_id"]) / "review-budget.json"
    if not path.exists():
        return default
    if path.is_symlink() or path.stat().st_size > 16384:
        raise ValidationError("invalid review budget decision file")
    record = read_json(path)
    if record.get("decision_sha256") != canonical_sha256({k: v for k, v in record.items() if k != "decision_sha256"}):
        raise ValidationError("review budget decision integrity mismatch")
    if record.get("task_id") != plan.get("task_id") or record.get("repository") != plan.get("repository"):
        raise ValidationError("review budget decision task identity mismatch")
    if record.get("plan_sha256") != plan.get("plan_sha256"):
        return default
    limit = record.get("limit")
    proof_hash = record.get("proof_reference_sha256")
    if (record.get("schema_version") != 1 or type(limit) is not int or not 12 <= limit <= 100
            or record.get("source") not in {"conversation", "developer_terminal"}
            or record.get("enforcement_tier") != "RULE_ENFORCED"
            or not isinstance(proof_hash, str) or len(proof_hash) != 64):
        raise ValidationError("invalid review budget decision")
    return limit


def record_review_budget(args):
    from pathlib import Path
    from plan_authority import validate_plan_hash
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id)
    directory = state_root(repo) / "tasks" / task_id
    plan = read_json(directory / "plan.json")
    valid, reason = validate_plan_hash(plan)
    if not valid:
        raise ValidationError(reason)
    if (not isinstance(plan.get("approval"), dict) or plan["approval"].get("plan_sha256") != plan.get("plan_sha256")
            or plan.get("status") not in {"APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED"}):
        raise ValidationError("review budget requires an approved active task")
    proof = str(args.proof_reference or "").strip()
    if not proof or type(args.limit) is not int or not 12 <= args.limit <= 100 or args.source not in {"conversation", "developer_terminal"}:
        raise ValidationError("review budget requires explicit developer proof and a limit from 12 to 100")
    record = {"schema_version": 1, "task_id": task_id, "plan_sha256": plan["plan_sha256"],
              "repository": plan.get("repository"), "limit": args.limit, "source": args.source,
              "enforcement_tier": "RULE_ENFORCED", "proof_reference_sha256": canonical_sha256(proof),
              "recorded_at": utc_now()}
    record["decision_sha256"] = canonical_sha256(record)
    path = directory / "review-budget.json"
    if path.exists():
        previous = read_json(path)
        atomic_write_json(directory / "review-budget-history" / (canonical_sha256(previous) + ".json"), previous)
    atomic_write_json(path, record)
    return {"status": "PASS", "task_id": task_id, "review_call_budget": args.limit,
            "detail": "Developer spending decision recorded; policies, review proof, counters and plan unchanged."}
