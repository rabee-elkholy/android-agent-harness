"""Canonical automated Zoho Sprints lifecycle writer.

Provides deterministic start and delivery sync, structured QA delivery reports,
and stable idempotency operation IDs for Zoho Sprints items linked to task plans.
Standard library Python only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from _vnext_common import ValidationError, atomic_write_json, canonical_sha256, read_json, state_root, utc_now, validate_id
from integrations.zoho_sprints.policy import ZohoPolicyResolver

_SERVER_MODULE = None


def _get_zoho_server():
    global _SERVER_MODULE
    if _SERVER_MODULE is not None:
        return _SERVER_MODULE
    mcp_dir = Path(__file__).resolve().parent.parent / "mcp" / "zoho_sprints"
    if str(mcp_dir) not in sys.path:
        sys.path.insert(0, str(mcp_dir))
    server_path = mcp_dir / "server.py"
    if not server_path.is_file():
        raise RuntimeError(f"Zoho MCP server not found at {server_path}")
    spec = importlib.util.spec_from_file_location("zoho_sprints_server", server_path)
    if not spec or not spec.loader:
        raise RuntimeError("Failed to load Zoho MCP server module spec")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _SERVER_MODULE = mod
    return _SERVER_MODULE


def _sanitize_op_id(raw_id: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]", "-", raw_id)
    return clean[:128]


def resolve_new_item_type(task_kind: str, explicit_type: str | None = None) -> str:
    """Resolve Zoho item type for explicit create operations (Section 52)."""
    if explicit_type:
        norm = str(explicit_type).strip().lower().capitalize()
        if norm in ("Bug", "Task", "Story"):
            return norm
    kind = str(task_kind or "").upper().strip()
    if kind == "BUG":
        return "Bug"
    if kind == "FEATURE":
        return "Story"
    if kind == "REFACTOR":
        return "Task"
    return "Task"


def cmd_prepare_report(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id, "task id")
    from workflow import task_dir
    tdir = task_dir(repo, task_id)
    plan_path = tdir / "plan.json"
    if not plan_path.is_file():
        sys.stderr.write(f"ERROR: plan.json not found for task '{task_id}'\n")
        return 1

    plan = read_json(plan_path)

    objective = str(args.objective or "").strip()
    changes = str(args.changes or "").strip()
    if not objective:
        sys.stderr.write("ERROR: --objective must be non-empty\n")
        return 1
    if not changes:
        sys.stderr.write("ERROR: --changes must be non-empty\n")
        return 1

    try:
        raw_impact = json.loads(args.impact_json) if isinstance(args.impact_json, str) else args.impact_json
        if not isinstance(raw_impact, list) or not (1 <= len(raw_impact) <= 20):
            sys.stderr.write("ERROR: --impact-json must be a JSON array of 1 to 20 items\n")
            return 1
        impact_list = [str(x).strip() for x in raw_impact if str(x).strip()]
        if not impact_list:
            sys.stderr.write("ERROR: --impact-json items must be non-empty strings\n")
            return 1
    except Exception as exc:
        sys.stderr.write(f"ERROR: invalid --impact-json: {exc}\n")
        return 1

    try:
        raw_tests = json.loads(args.tests_json) if isinstance(args.tests_json, str) else args.tests_json
        if not isinstance(raw_tests, list) or not (1 <= len(raw_tests) <= 30):
            sys.stderr.write("ERROR: --tests-json must be a JSON array of 1 to 30 items\n")
            return 1
        tests_list = [str(x).strip() for x in raw_tests if str(x).strip()]
        if not tests_list:
            sys.stderr.write("ERROR: --tests-json items must be non-empty strings\n")
            return 1
    except Exception as exc:
        sys.stderr.write(f"ERROR: invalid --tests-json: {exc}\n")
        return 1

    # Security validation (Section 48): no secrets, no absolute paths, no raw diff
    combined_text = " ".join([objective, changes] + impact_list + tests_list)
    secret_patterns = (r"(?:ghp|gho|pat|sec)_[A-Za-z0-9_]{16,}", r"(?:Bearer|token)\s+[A-Za-z0-9_.-]{16,}")
    for pat in secret_patterns:
        if re.search(pat, combined_text, re.IGNORECASE):
            sys.stderr.write("ERROR: delivery report contains suspected secrets or bearer tokens\n")
            return 1

    if re.search(r"^[A-Za-z]:[\\/]", combined_text) or re.search(r"\s+[A-Za-z]:[\\/]", combined_text) or "/Users/" in combined_text or "/home/" in combined_text:
        sys.stderr.write("ERROR: delivery report must not contain absolute filesystem paths\n")
        return 1

    if "diff --git" in combined_text or "@@ -" in combined_text:
        sys.stderr.write("ERROR: delivery report must not contain raw diff markers\n")
        return 1

    report_payload = {
        "schema_version": 1,
        "task_id": task_id,
        "plan_sha256": plan.get("plan_sha256") or "",
        "objective_or_root_cause": objective,
        "solution_or_changes": changes,
        "impact_area": impact_list,
        "test_cases": tests_list,
    }
    report_sha = canonical_sha256(report_payload)
    report_payload["report_sha256"] = report_sha

    report_file = tdir / "zoho-delivery-report.json"
    atomic_write_json(report_file, report_payload)
    sys.stdout.write(json.dumps({"status": "PREPARED", "report_path": str(report_file), "report_sha256": report_sha}, indent=2) + "\n")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id, "task id")
    from workflow import task_dir
    tdir = task_dir(repo, task_id)
    plan_path = tdir / "plan.json"
    if not plan_path.is_file():
        sys.stderr.write(f"ERROR: plan.json not found for task '{task_id}'\n")
        return 1

    plan = read_json(plan_path)
    zoho_link = plan.get("zoho_link")
    if not zoho_link:
        sys.stderr.write(f"ERROR: Task '{task_id}' has no linked Zoho item.\n")
        return 1

    external_writes = plan.get("external_writes") or []
    if "zoho_sprints" not in external_writes:
        msg = (
            "EXTERNAL_WRITE_SCOPE_REQUIRED: zoho_sprints external write scope is required. "
            "Run 'workflow.py revise --external-write zoho_sprints' and obtain developer approval."
        )
        sys.stderr.write(f"ERROR: {msg}\n")
        return 1

    status = str(plan.get("status") or "")
    if status != "IMPLEMENTING":
        sys.stderr.write(f"ERROR: TASK_NOT_IMPLEMENTING: Start sync requires status to be IMPLEMENTING, but current status is '{status}'.\n")
        return 1

    approval = plan.get("approval") or {}
    single_use_nonce = approval.get("single_use_nonce")
    if not single_use_nonce:
        sys.stderr.write("ERROR: PLAN_NOT_APPROVED: Active task plan has not been approved by developer.\n")
        return 1

    execution_nonce = plan.get("execution_nonce")
    if not execution_nonce or execution_nonce != single_use_nonce:
        sys.stderr.write("ERROR: EXECUTION_NONCE_MISMATCH: plan.execution_nonce does not match approval.single_use_nonce.\n")
        return 1

    from plan_authority import validate_plan_hash
    valid, expected_hash = validate_plan_hash(plan, plan.get("plan_sha256"))
    if not valid:
        sys.stderr.write("ERROR: PLAN_HASH_INVALID: plan hash validation failed.\n")
        return 1

    if approval.get("plan_sha256") != expected_hash:
        sys.stderr.write("ERROR: APPROVAL_PLAN_HASH_MISMATCH: approval.plan_sha256 does not match validated plan hash.\n")
        return 1

    item_type = str(zoho_link.get("item_type") or "Task")
    policy_res = ZohoPolicyResolver.resolve(
        item_type=item_type,
        task_state="IMPLEMENTING",
        delivery_state="NONE",
        approved_external_write_scope=external_writes,
    )
    if not policy_res.get("allowed") or policy_res.get("action") != "UPDATE_STATUS" or policy_res.get("status") != "In progress":
        sys.stderr.write(f"ERROR: Zoho start policy denied: {policy_res.get('denied_reason')}\n")
        return 1

    plan_sha12 = str(plan.get("plan_sha256") or "000000000000")[:12]
    op_id = _sanitize_op_id(f"{task_id}.zoho.start.{plan_sha12}")
    item_id = str(zoho_link.get("item_id") or "")
    sprint_id = str(zoho_link.get("sprint_id") or "")

    tool_args: dict[str, Any] = {
        "item_id": item_id,
        "status": "In progress",
        "operation_id": op_id,
    }
    if sprint_id:
        tool_args["sprint_id"] = sprint_id

    sync_file = tdir / "zoho-start-sync.json"
    try:
        server = _get_zoho_server()
        res = server.handle_call_tool("zoho_update_task_status", tool_args)
        if isinstance(res, dict) and res.get("isError"):
            err_text = str((res.get("content") or [{}])[0].get("text") or "Unknown Zoho error")
            raise RuntimeError(err_text)
        atomic_write_json(sync_file, {
            "task_id": task_id,
            "status": "PASS",
            "operation_id": op_id,
            "item_id": item_id,
            "sprint_id": sprint_id,
            "target_status": "In progress",
            "updated_at": utc_now(),
        })
        sys.stdout.write(json.dumps({"status": "PASS", "operation_id": op_id}, indent=2) + "\n")
        return 0
    except Exception as exc:
        atomic_write_json(sync_file, {
            "task_id": task_id,
            "status": "ENV",
            "operation_id": op_id,
            "item_id": item_id,
            "sprint_id": sprint_id,
            "error": str(exc),
            "updated_at": utc_now(),
        })
        sys.stderr.write(f"WARNING: Zoho start sync recorded ENV_BLOCKED: {exc}\n")
        sys.stdout.write(json.dumps({"status": "ENV", "operation_id": op_id, "detail": str(exc)}, indent=2) + "\n")
        return 0


def cmd_delivery(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id, "task id")
    from workflow import task_dir
    tdir = task_dir(repo, task_id)
    plan_path = tdir / "plan.json"
    if not plan_path.is_file():
        sys.stderr.write(f"ERROR: plan.json not found for task '{task_id}'\n")
        return 1

    plan = read_json(plan_path)
    status = str(plan.get("status") or "")
    if status != "DELIVERED":
        sys.stderr.write(f"ERROR: TASK_NOT_DELIVERED: Delivery sync requires status to be DELIVERED, but current status is '{status}'.\n")
        return 1

    zoho_link = plan.get("zoho_link")
    if not zoho_link:
        sys.stderr.write(f"ERROR: Task '{task_id}' has no linked Zoho item.\n")
        return 1

    external_writes = plan.get("external_writes") or []
    if "zoho_sprints" not in external_writes:
        msg = (
            "EXTERNAL_WRITE_SCOPE_REQUIRED: zoho_sprints external write scope is required. "
            "Run 'workflow.py revise --external-write zoho_sprints' and obtain developer approval."
        )
        sys.stderr.write(f"ERROR: {msg}\n")
        return 1

    commit_sha = str(plan.get("delivery_commit_sha") or "").strip()
    if not commit_sha:
        sys.stderr.write("ERROR: DELIVERY_COMMIT_MISSING: Delivery sync requires delivery_commit_sha in plan.\n")
        return 1
    short_commit = commit_sha[:7]

    report_file = tdir / "zoho-delivery-report.json"
    if not report_file.is_file():
        sys.stderr.write("ERROR: DELIVERY_REPORT_MISSING: zoho-delivery-report.json not found. Run prepare-report first.\n")
        return 1

    report_data = read_json(report_file)
    if report_data.get("schema_version") != 1:
        sys.stderr.write("ERROR: DELIVERY_REPORT_INVALID_SCHEMA: zoho-delivery-report.json schema_version must be 1.\n")
        return 1
    if str(report_data.get("task_id") or "") != task_id:
        sys.stderr.write(f"ERROR: DELIVERY_REPORT_TASK_MISMATCH: zoho-delivery-report.json task_id '{report_data.get('task_id')}' != '{task_id}'.\n")
        return 1
    plan_sha = str(plan.get("plan_sha256") or "")
    if str(report_data.get("plan_sha256") or "") != plan_sha:
        sys.stderr.write("ERROR: DELIVERY_REPORT_PLAN_MISMATCH: zoho-delivery-report.json was produced for a different plan hash.\n")
        return 1
    recomputed_report_sha = canonical_sha256({k: v for k, v in report_data.items() if k != "report_sha256"})
    if str(report_data.get("report_sha256") or "") != recomputed_report_sha:
        sys.stderr.write("ERROR: DELIVERY_REPORT_TAMPERED: zoho-delivery-report.json report_sha256 does not match canonical contents.\n")
        return 1

    policy_res = ZohoPolicyResolver.resolve(
        item_type=str(zoho_link.get("item_type") or "Task"),
        task_state=status,
        delivery_state="DELIVERED",
        approved_external_write_scope=external_writes,
        configured_language=plan.get("language") or "en_titles_ar_comments",
        commit_hash=short_commit,
    )
    if not policy_res.get("allowed"):
        sys.stderr.write(f"ERROR: Zoho delivery policy denied: {policy_res.get('denied_reason')}\n")
        return 1

    primary_action = str(policy_res.get("action") or "NONE")
    secondary_action = policy_res.get("secondary_action")
    target_status = str(policy_res.get("status") or "Ready To ReTest")
    tmpl_name = str(policy_res.get("template") or "TASK_DESCRIPTION")

    language = plan.get("language") or "en_titles_ar_comments"
    rendered = ZohoPolicyResolver.render_template(
        tmpl_name,
        language=language,
        commit_hash=short_commit,
        root_cause_or_objective=report_data.get("objective_or_root_cause") or "",
        solution_or_changes=report_data.get("solution_or_changes") or "",
        blast_radius=report_data.get("impact_area") or [],
        test_cases=report_data.get("test_cases") or [],
    )

    item_id = str(zoho_link.get("item_id") or "")
    sprint_id = str(zoho_link.get("sprint_id") or "")

    commit_sha12 = commit_sha[:12]
    status_op_id = _sanitize_op_id(f"{task_id}.zoho.ready.{commit_sha12}")
    bug_comment_op_id = _sanitize_op_id(f"{task_id}.zoho.bug-report.{commit_sha12}")
    desc_op_id = _sanitize_op_id(f"{task_id}.zoho.description.{commit_sha12}")
    commit_comment_op_id = _sanitize_op_id(f"{task_id}.zoho.commit-comment.{commit_sha12}")

    sync_file = tdir / "zoho-delivery-sync.json"
    try:
        server = _get_zoho_server()
        if primary_action == "ADD_COMMENT":
            # Bug: 1. Add QA report as Comment, 2. Set status Ready To ReTest (never edit description)
            c_args: dict[str, Any] = {"item_id": item_id, "comment": rendered, "operation_id": bug_comment_op_id}
            if sprint_id:
                c_args["sprint_id"] = sprint_id
            c_res = server.handle_call_tool("zoho_add_comment", c_args)
            if isinstance(c_res, dict) and c_res.get("isError"):
                raise RuntimeError(str((c_res.get("content") or [{}])[0].get("text") or "Comment failed"))

            s_args: dict[str, Any] = {"item_id": item_id, "status": target_status, "operation_id": status_op_id}
            if sprint_id:
                s_args["sprint_id"] = sprint_id
            s_res = server.handle_call_tool("zoho_update_task_status", s_args)
            if isinstance(s_res, dict) and s_res.get("isError"):
                raise RuntimeError(str((s_res.get("content") or [{}])[0].get("text") or "Status update failed"))
        elif primary_action == "UPDATE_DESCRIPTION":
            # Task/Story: 1. Update Description, 2. Add commit Comment, 3. Set status Ready To ReTest
            d_args: dict[str, Any] = {"item_id": item_id, "description": rendered, "operation_id": desc_op_id}
            if sprint_id:
                d_args["sprint_id"] = sprint_id
            d_res = server.handle_call_tool("zoho_update_task_description", d_args)
            if isinstance(d_res, dict) and d_res.get("isError"):
                raise RuntimeError(str((d_res.get("content") or [{}])[0].get("text") or "Description update failed"))

            if secondary_action == "ADD_COMMENT":
                c_args = {"item_id": item_id, "comment": f"Commit: {short_commit}", "operation_id": commit_comment_op_id}
                if sprint_id:
                    c_args["sprint_id"] = sprint_id
                c_res = server.handle_call_tool("zoho_add_comment", c_args)
                if isinstance(c_res, dict) and c_res.get("isError"):
                    raise RuntimeError(str((c_res.get("content") or [{}])[0].get("text") or "Commit comment failed"))

            s_args = {"item_id": item_id, "status": target_status, "operation_id": status_op_id}
            if sprint_id:
                s_args["sprint_id"] = sprint_id
            s_res = server.handle_call_tool("zoho_update_task_status", s_args)
            if isinstance(s_res, dict) and s_res.get("isError"):
                raise RuntimeError(str((s_res.get("content") or [{}])[0].get("text") or "Status update failed"))
        else:
            sys.stderr.write(f"ERROR: Unsupported primary action: {primary_action}\n")
            return 1

        atomic_write_json(sync_file, {
            "task_id": task_id,
            "status": "PASS",
            "commit_sha": commit_sha,
            "item_id": item_id,
            "sprint_id": sprint_id,
            "target_status": target_status,
            "updated_at": utc_now(),
        })
        sys.stdout.write(json.dumps({"status": "PASS", "commit_sha": short_commit}, indent=2) + "\n")
        return 0
    except Exception as exc:
        atomic_write_json(sync_file, {
            "task_id": task_id,
            "status": "ENV",
            "commit_sha": commit_sha,
            "item_id": item_id,
            "sprint_id": sprint_id,
            "error": str(exc),
            "updated_at": utc_now(),
        })
        sys.stderr.write(f"WARNING: Zoho delivery sync recorded ENV_BLOCKED: {exc}\n")
        sys.stdout.write(json.dumps({"status": "ENV", "detail": str(exc)}, indent=2) + "\n")
        return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    task_id = validate_id(args.task_id, "task id")
    from workflow import task_dir
    tdir = task_dir(repo, task_id)
    plan_path = tdir / "plan.json"
    if not plan_path.is_file():
        sys.stderr.write(f"ERROR: plan.json not found for task '{task_id}'\n")
        return 1

    plan = read_json(plan_path)
    zoho_link = plan.get("zoho_link")
    start_sync = read_json(tdir / "zoho-start-sync.json") if (tdir / "zoho-start-sync.json").is_file() else None
    report = read_json(tdir / "zoho-delivery-report.json") if (tdir / "zoho-delivery-report.json").is_file() else None
    deliv_sync = read_json(tdir / "zoho-delivery-sync.json") if (tdir / "zoho-delivery-sync.json").is_file() else None

    result = {
        "task_id": task_id,
        "task_status": plan.get("status"),
        "zoho_link": zoho_link,
        "start_sync": start_sync.get("status") if start_sync else "PENDING" if zoho_link else "N/A",
        "delivery_report": "PREPARED" if report else "MISSING" if zoho_link else "N/A",
        "delivery_sync": deliv_sync.get("status") if deliv_sync else "PENDING" if zoho_link else "N/A",
    }
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="Repository root")
    common.add_argument("--task-id", required=True, help="Task ID")

    prep_cmd = sub.add_parser("prepare-report", parents=[common])
    prep_cmd.add_argument("--objective", required=True, help="Objective or root cause")
    prep_cmd.add_argument("--changes", required=True, help="Functional solution or changes")
    prep_cmd.add_argument("--impact-json", required=True, help="JSON array of impact areas (1..20)")
    prep_cmd.add_argument("--tests-json", required=True, help="JSON array of test cases (1..30)")
    prep_cmd.set_defaults(handler=cmd_prepare_report)

    start_cmd = sub.add_parser("start", aliases=["start-sync"], parents=[common])
    start_cmd.set_defaults(handler=cmd_start)

    deliv_cmd = sub.add_parser("delivery", aliases=["delivery-sync"], parents=[common])
    deliv_cmd.set_defaults(handler=cmd_delivery)

    status_cmd = sub.add_parser("status", parents=[common])
    status_cmd.set_defaults(handler=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if not handler:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
