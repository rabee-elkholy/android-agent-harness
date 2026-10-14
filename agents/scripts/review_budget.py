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


def _review_budget_decision(repo, plan):
    if repo is None or not plan.get("task_id"):
        return None
    path = state_root(repo) / "tasks" / validate_id(plan["task_id"]) / "review-budget.json"
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 16384:
        raise ValidationError("invalid review budget decision file")
    record = read_json(path)
    if record.get("decision_sha256") != canonical_sha256({k: v for k, v in record.items() if k != "decision_sha256"}):
        raise ValidationError("review budget decision integrity mismatch")
    if record.get("task_id") != plan.get("task_id") or record.get("repository") != plan.get("repository"):
        raise ValidationError("review budget decision task identity mismatch")
    if record.get("plan_sha256") != plan.get("plan_sha256"):
        return None
    limit = record.get("limit")
    proof_hash = record.get("proof_reference_sha256")
    schema = record.get("schema_version")
    if (type(schema) is not int or schema not in {1, 2} or type(limit) is not int or not 12 <= limit <= 100
            or record.get("source") not in {"conversation", "developer_terminal"}
            or record.get("enforcement_tier") != "RULE_ENFORCED"
            or not isinstance(proof_hash, str) or len(proof_hash) != 64):
        raise ValidationError("invalid review budget decision")
    if schema == 2 and (type(record.get("round_limit")) is not int or not 3 <= record["round_limit"] <= 100):
        raise ValidationError("invalid review round limit decision")
    return record


def effective_review_budget(repo, plan, policy=None):
    from review_policy import _configured_model_call_budget
    default = int((policy or {}).get("model_call_budget") or plan.get("max_review_calls")
                  or plan.get("model_call_budget") or _configured_model_call_budget())
    record = _review_budget_decision(repo, plan)
    return record["limit"] if record else default


def effective_review_round_limit(repo, plan, policy=None):
    default = int((policy or {}).get("max_review_rounds") or 3)
    record = _review_budget_decision(repo, plan)
    return record["round_limit"] if record and record["schema_version"] == 2 else default


def review_round_cap_action(repo, plan, policy=None):
    completed = int(plan.get("review_rounds") or 0)
    limit = effective_review_round_limit(repo, plan, policy)
    requested = max(completed + 1, int((policy or {}).get("review_round") or 0))
    if requested <= limit:
        return None
    task_id = str(plan.get("task_id") or "<task_id>")
    return {"code": "REVIEW_ROUND_CAP_REACHED", "kind": "DEVELOPER_ACTION", "command": "", "blocking": True,
            "reason": (f"REVIEW_ROUND_CAP_REACHED: Completed {completed} final review rounds; requested round {requested} "
                       f"exceeds the task round limit {limit}. Ask the developer to approve an explicit round limit, then run "
                       f"`python .agents/harness.py task review-budget --task-id {task_id} --round-limit <approved limit> "
                       "--source conversation --proof-reference <developer answer>`. The reviewer-call spending limit is "
                       "separate: --limit changes calls only; --round-limit changes rounds only. Neither resets counters. "
                       "Do not edit engine/policy/evidence files, disable hooks, skip reviewers or override reviews to bypass this limit."),
            "inputs": {"repo": ".", "task_id": task_id, "completed_rounds": completed,
                       "round_limit": limit, "requested_round": requested}, "expected": {}}


def record_review_budget(args):
    from pathlib import Path
    from evidence_store import StateLock
    repo = Path(args.repo).resolve()
    with StateLock(state_root(repo)):
        return _record_review_budget_locked(args, repo)


def _record_review_budget_locked(args, repo):
    from pathlib import Path
    from plan_authority import validate_plan_hash
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
    call_limit, round_limit = getattr(args, "limit", None), getattr(args, "round_limit", None)
    if not proof or args.source not in {"conversation", "developer_terminal"} or (call_limit is None and round_limit is None):
        raise ValidationError("review budget requires explicit developer proof and --limit or --round-limit")
    if call_limit is not None and (type(call_limit) is not int or not 12 <= call_limit <= 100):
        raise ValidationError("review call limit must be from 12 to 100")
    if round_limit is not None and (type(round_limit) is not int or not 3 <= round_limit <= 100
                                  or round_limit <= int(plan.get("review_rounds") or 0)):
        raise ValidationError("review round limit must be from 3 to 100 and exceed completed rounds")
    _review_budget_decision(repo, plan)  # A new approval must not silently repair a corrupted decision.
    policy = {}
    current_file = directory / "current-run.json"
    if current_file.is_file():
        policy_path = Path(str(read_json(current_file).get("policy") or ""))
        if not policy_path.is_absolute():
            policy_path = repo / policy_path
        if policy_path.resolve().parent != directory.resolve():
            raise ValidationError("review budget policy path escapes task state")
        policy = read_json(policy_path)
    # Preserve the other limit and its recorded history when approving only one dimension.
    calls = effective_review_budget(repo, plan, policy) if call_limit is None else call_limit
    rounds = effective_review_round_limit(repo, plan, policy) if round_limit is None else round_limit
    if not 12 <= calls <= 100 or not 3 <= rounds <= 100:
        raise ValidationError("existing review limits are outside supported bounds; stop for harness diagnosis")
    record = {"schema_version": 2, "task_id": task_id, "plan_sha256": plan["plan_sha256"],
              "repository": plan.get("repository"), "limit": calls, "round_limit": rounds, "source": args.source,
              "changed_limits": [name for name, value in (("calls", call_limit), ("rounds", round_limit)) if value is not None],
              "enforcement_tier": "RULE_ENFORCED", "proof_reference_sha256": canonical_sha256(proof),
              "recorded_at": utc_now()}
    record["decision_sha256"] = canonical_sha256(record)
    path = directory / "review-budget.json"
    if path.exists():
        previous = read_json(path)
        atomic_write_json(directory / "review-budget-history" / (canonical_sha256(previous) + ".json"), previous)
    atomic_write_json(path, record)
    return {"status": "PASS", "task_id": task_id, "review_call_budget": calls, "review_round_limit": rounds,
            "detail": "Developer spending decision recorded; policies, review proof, counters and plan unchanged."}
