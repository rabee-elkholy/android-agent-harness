"""Governed Antigravity v2.32.0+ / CLI 1.5.9+ Dynamic Workflow for single-turn Review Protocol V2.

Executes inside Antigravity's `run_workflow` bundled Python runtime (or `--plan-json` from CLI)
to fan out all pending V2 specialist reviewers in parallel, await completion, and run
`review_orchestrator.py complete-all` in a single turn without burning multi-turn Lead round-trips.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _vnext_common import ValidationError, read_json, task_dir, validate_id  # noqa: E402

WORKFLOW_FINGERPRINT = "HARNESS_DYNAMIC_REVIEW_WORKFLOW_V1"


def build_dynamic_review_plan(repo: Path, task_id: str | None = None) -> dict[str, Any]:
    """Build deterministic fan-out specification for the active V2 review run."""
    repo_root = repo.resolve()
    state = (repo_root / ".agents" / "state") if (repo_root / ".agents").is_dir() else (repo_root / "agents" / "state")
    resolved_tid = str(task_id or "").strip()
    if not resolved_tid:
        active_f = state / "active-task.json"
        if not active_f.is_file():
            raise ValidationError("no active task found for dynamic review workflow")
        resolved_tid = str(read_json(active_f).get("task_id") or "").strip()
    resolved_tid = validate_id(resolved_tid, "task_id")
    tdir = task_dir(repo_root, resolved_tid)
    plan_file = tdir / "plan.json"
    current_file = tdir / "current-run.json"
    if not plan_file.is_file() or not current_file.is_file():
        raise ValidationError(f"task '{resolved_tid}' has no active review run")
    plan = read_json(plan_file)
    if str(plan.get("status") or "") != "VERIFYING":
        raise ValidationError(f"task '{resolved_tid}' must be in VERIFYING state (got {plan.get('status')})")
    current = read_json(current_file)
    if int(current.get("review_protocol_version") or 1) < 2:
        raise ValidationError("dynamic review workflow requires Review Protocol V2")

    run_id = validate_id(str(current.get("run_id") or ""), "run_id")
    policy = read_json(Path(str(current["policy"])))
    required = list(policy.get("reviewers") or [])
    from review_orchestrator import REVIEW_COMPLETED, REVIEW_INGESTED, load_ledger
    try:
        ledger = load_ledger(tdir, run_id)
    except Exception:
        ledger = {}
    rev_states = (ledger or {}).get("reviewers") or {}
    pending = [
        r for r in required
        if str((rev_states.get(r) or {}).get("state") or "") not in {REVIEW_COMPLETED, REVIEW_INGESTED}
    ]
    review_host = str(current.get("review_host") or "antigravity").strip().lower()
    from review_execution import resolve_execution_profile
    profile = resolve_execution_profile(repo_root, resolved_tid, host=review_host)
    from workflow import _reviewer_prompts
    prompts = _reviewer_prompts(profile, pending)
    from review_models import antigravity_dispatch_model_hint, reviewer_model_map
    hint_text = str(antigravity_dispatch_model_hint(profile, pending, repo=repo_root) or "")
    use_flash_offload = '"flash"' in hint_text or "'flash'" in hint_text

    invocations: list[dict[str, str]] = []
    for role in pending:
        item: dict[str, str] = {
            "TypeName": role,
            "Role": f"V2 Specialist Review ({role})",
            "Prompt": str(prompts.get(role) or f"Execute specialist V2 code review from .agents/state/tasks/{resolved_tid}/brief-{role}.md"),
            "Workspace": str(repo_root),
        }
        if use_flash_offload:
            item["Model"] = "flash"
        invocations.append(item)

    return {
        "schema_version": 1,
        "fingerprint": WORKFLOW_FINGERPRINT,
        "task_id": resolved_tid,
        "run_id": run_id,
        "required_reviewers": required,
        "pending_reviewers": pending,
        "reviewer_models": reviewer_model_map(profile or current, pending),
        "subagent_invocations": invocations,
    }


def execute_dynamic_review(
    repo: Path,
    task_id: str | None = None,
    *,
    spawner: Callable[[list[dict[str, str]]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Emit a deterministic V2 reviewer fan-out plan, or execute via an injected spawner and run complete-all."""
    spec = build_dynamic_review_plan(repo, task_id)
    resolved_tid = spec["task_id"]
    invocations = spec["subagent_invocations"]

    active_spawner = spawner
    spawn_results: list[dict[str, Any]] = []
    if invocations and active_spawner is not None:
        from review_orchestrator import record_dispatch_batch
        record_dispatch_batch(repo.resolve(), resolved_tid, spec["pending_reviewers"], host="antigravity")
        raw_res = active_spawner(invocations)
        if isinstance(raw_res, list):
            spawn_results = [r for r in raw_res if isinstance(r, dict)]

    exec_ids: list[str] = []
    roles_with_ids: list[str] = []
    for item_spec, res in zip(invocations, spawn_results):
        cid = str(res.get("conversationId") or res.get("conversation_id") or res.get("execution_id") or "").strip()
        if cid:
            roles_with_ids.append(item_spec["TypeName"])
            exec_ids.append(cid)

    if invocations and active_spawner is None:
        return {
            "status": "PLAN_READY",
            "reason": "No synchronous workflow spawner bound; dispatch subagent_invocations via invoke_subagent and finalize with review complete-all.",
            "plan": spec,
        }

    import review_orchestrator
    cli_args = ["complete-all", "--repo", str(repo.resolve()), "--task", resolved_tid]
    for r_name, eid in zip(roles_with_ids, exec_ids):
        cli_args.extend(["--reviewer", r_name, "--execution-id", eid])
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        rc = review_orchestrator.main(cli_args)
    return {
        "status": "COMPLETED" if rc == 0 else "BLOCKED",
        "exit_code": rc,
        "task_id": resolved_tid,
        "run_id": spec["run_id"],
        "dispatched_count": len(invocations),
        "stdout": out_buf.getvalue().strip(),
        "stderr": err_buf.getvalue().strip(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("HARNESS_REPO", "."))
    parser.add_argument("--task", "--task-id", dest="task", default="")
    parser.add_argument("--plan-json", action="store_true", help="Emit deterministic V2 review workflow spec without executing")
    args = parser.parse_args(argv)
    try:
        repo = Path(args.repo).resolve()
        if args.plan_json:
            print(json.dumps(build_dynamic_review_plan(repo, args.task or None), ensure_ascii=False, indent=2))
            return 0
        res = execute_dynamic_review(repo, args.task or None)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("status") in {"COMPLETED", "PLAN_READY"} else int(res.get("exit_code") or 1)
    except ValidationError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
