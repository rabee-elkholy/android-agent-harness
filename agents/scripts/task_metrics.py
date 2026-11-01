"""Bounded, best-effort local operation timings; never delivery evidence."""
from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from pathlib import Path

from _vnext_common import ValidationError, atomic_write_json, bounded_path, read_json, validate_id

MAX_EVENTS = 512
MAX_EVENT_BYTES = 4096
DECISION_COMMANDS = frozenset({
    "task-approve", "task-approve-sensitive", "task-cancel", "device-signoff",
    "device-skip-validation", "device-validate-automatically", "task-review-budget",
})


def _directory(repo, task_id):
    return bounded_path(repo / ".agents/state/metrics", validate_id(task_id, "task id"))


def record_operation(repo, task_id, operation, duration, exit_code, started=None, *, counters=None, span_kind="command", parent_id=None):
    """Diagnostic errors must never change a command's outcome."""
    try:
        directory = _directory(repo, task_id)
        duration = float(duration)
        if not math.isfinite(duration) or duration < 0:
            return
        if directory.exists():
            import itertools
            if sum(1 for _ in itertools.islice(directory.iterdir(), MAX_EVENTS)) >= MAX_EVENTS:
                return
        end = time.time()
        start = float(started) if started is not None else end - duration
        if not math.isfinite(start) or start > end:
            return
        value = {"schema_version": 1, "task_id": task_id, "operation": validate_id(operation),
                 "duration_seconds": round(duration, 6), "exit_code": int(exit_code),
                 "started_at": start, "ended_at": end}
        if counters is not None or span_kind == "substep":
            allowed = {"graph_syncs", "targets", "read_ranges", "emitted_bytes", "facts_reads", "notes_reads", "instruction_reads", "manifest_calls", "dispatches"}
            safe = {k: v for k, v in (counters or {}).items() if k in allowed and type(v) is int and 0 <= v <= 10**12}
            value.update(schema_version=2, span_kind=span_kind, counters=safe, repetition_reason="UNKNOWN")
            if parent_id and isinstance(parent_id, str) and len(parent_id) == 32 and all(c in "0123456789abcdef" for c in parent_id):
                value["parent_id"] = parent_id
        if len(json.dumps(value).encode()) <= MAX_EVENT_BYTES:
            atomic_write_json(directory / (uuid.uuid4().hex + ".json"), value)
    except Exception:
        return


def metrics_report(repo, task_id):
    directory = _directory(repo, task_id)
    result = {"schema_version": 1, "task_id": task_id, "observed_execution_seconds": "UNAVAILABLE",
              "operation_elapsed_union_seconds": "UNAVAILABLE", "tokens": "UNAVAILABLE", "cost": "UNAVAILABLE",
              "developer_work_seconds": "UNAVAILABLE", "operations": {}, "invalid_events": 0,
              "review_rounds": "UNAVAILABLE", "developer_interventions": "UNAVAILABLE",
              "current_blocked_reviewers": [],
              "environment_failures": "UNAVAILABLE", "other_failed_commands": "UNAVAILABLE",
              "repeated_command_executions": "UNAVAILABLE", "successful_decision_commands": {},
              "reported_finding_verdicts": "UNAVAILABLE",
              "history_capped": False, "substeps": {}, "counters": {}, "repetition_reason": "UNKNOWN",
              "limitations": "Observed launcher commands only; repeats may be intentional. Decision command counts are not unique human interventions. Finding verdicts are recorded assessments, not independently proven false positives. Waits and host reviewer execution are not inferred."}
    if not directory.exists():
        return result
    plan_path = repo / ".agents/state/tasks" / validate_id(task_id) / "plan.json"
    try:
        if plan_path.stat().st_size <= 262144:
            plan = read_json(plan_path)
            if plan.get("task_id") == task_id:
                result["review_rounds"] = plan.get("review_rounds", 0)
                result["current_blocked_reviewers"] = plan.get("blocked_reviewers") or []
                findings_path = plan_path.with_name("finding-validations.json")
                if findings_path.is_file() and not findings_path.is_symlink() and findings_path.stat().st_size <= 262144:
                    findings = read_json(findings_path)
                    if findings.get("task_id") == task_id and plan.get("plan_sha256") and findings.get("plan_sha256") == plan["plan_sha256"]:
                        latest = {}
                        for item in findings.get("validations") or []:
                            if not isinstance(item, dict) or not item.get("finding_id") or item.get("status") not in {"CONFIRMED", "FALSE_POSITIVE", "NEEDS_CONTEXT", "NOT_REPRODUCIBLE"}:
                                raise ValidationError("invalid finding assessment")
                            latest[str(item["finding_id"])] = item["status"]
                        result["reported_finding_verdicts"] = {status: list(latest.values()).count(status) for status in sorted(set(latest.values()))}
    except (OSError, ValueError, TypeError, AttributeError, ValidationError):
        pass
    import itertools
    paths = list(itertools.islice(directory.iterdir(), MAX_EVENTS + 1))
    result["history_capped"] = len(paths) >= MAX_EVENTS
    total, intervals = 0.0, []
    valid = 0
    environment_failures = other_failures = 0
    for path in paths[:MAX_EVENTS]:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_EVENT_BYTES:
                raise ValidationError("oversized or symlink metric")
            event = read_json(path)
            if event.get("schema_version") not in (1, 2) or event.get("task_id") != task_id:
                raise ValidationError("invalid metric identity")
            duration = float(event["duration_seconds"])
            start, end = float(event["started_at"]), float(event["ended_at"])
            if not all(math.isfinite(x) for x in (duration, start, end)) or duration < 0 or end < start:
                raise ValidationError("invalid metric timing")
            operation = validate_id(event["operation"])
            exit_code = event["exit_code"]
            if type(exit_code) is not int:
                raise ValidationError("invalid metric exit code")
            if event.get("schema_version") == 2:
                for name, count in (event.get("counters") or {}).items():
                    if name in {"graph_syncs", "targets", "read_ranges", "emitted_bytes", "facts_reads", "notes_reads", "instruction_reads", "manifest_calls", "dispatches"} and type(count) is int and count >= 0:
                        result["counters"][name] = result["counters"].get(name, 0) + count
                if event.get("span_kind") == "substep":
                    sub = result["substeps"].setdefault(operation, {"attempts": 0, "seconds": 0.0})
                    sub["attempts"] += 1
                    sub["seconds"] += duration
                    continue
            row = result["operations"].setdefault(operation, {"attempts": 0, "nonzero_exits": 0, "seconds": 0.0})
            row["attempts"] += 1
            row["nonzero_exits"] += int(event["exit_code"] != 0)
            row["seconds"] += duration
            total += duration
            intervals.append((start, end))
            environment_failures += int(exit_code == 30)
            other_failures += int(exit_code not in (0, 30))
            if operation in DECISION_COMMANDS and exit_code == 0:
                decisions = result["successful_decision_commands"]
                decisions[operation] = decisions.get(operation, 0) + 1
            valid += 1
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ValidationError):
            result["invalid_events"] += 1
    if valid:
        result["environment_failures"] = environment_failures
        result["other_failed_commands"] = other_failures
        result["repeated_command_executions"] = sum(max(0, item["attempts"] - 1) for item in result["operations"].values())
        result["observed_execution_seconds"] = round(total, 6)
        intervals.sort()
        left, right = intervals[0]
        union = 0.0
        for start, end in intervals[1:]:
            if start <= right:
                right = max(right, end)
            else:
                union += right - left
                left, right = start, end
        result["operation_elapsed_union_seconds"] = round(union + right - left, 6)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(metrics_report(Path(args.repo).resolve(), args.task_id), indent=2))
        return 0
    except (OSError, ValidationError) as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


def metric_task_id(repo, args):
    """Capture ownership before a command can change task focus. No probes if off."""
    import os
    if os.environ.get("HARNESS_LOCAL_METRICS") != "1":
        return ""
    for i, arg in enumerate(args):
        if arg == "--task-id" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--task-id="):
            return arg.split("=", 1)[1]
    try:
        path = Path(repo) / ".agents/state/active-task.json"
        if not path.is_symlink() and path.stat().st_size <= 4096:
            return str(read_json(path).get("task_id") or "")
    except (OSError, ValueError, ValidationError):
        pass
    return ""


from contextlib import contextmanager

@contextmanager
def operation_span(repo, operation, *, task_id=None, counters=None):
    """Optional bounded diagnostics: never intercept stdout or alter operation outcomes."""
    import os
    if os.environ.get("HARNESS_LOCAL_METRICS") != "1":
        yield
        return
    owner = task_id or metric_task_id(repo, [])
    started, clock = time.time(), time.monotonic()
    code = 1
    try:
        yield
        code = 0
    finally:
        if owner:
            record_operation(Path(repo), owner, operation, time.monotonic()-clock, code,
                             started, counters=counters or {}, span_kind="substep",
                             parent_id=os.environ.get("HARNESS_METRIC_PARENT"))


def measured_operation(name):
    from functools import wraps
    def decorate(function):
        @wraps(function)
        def wrapped(repo, *args, **kwargs):
            owner = kwargs.get("task_id") or (args[0] if name == "review-package" and args else None)
            with operation_span(repo, name, task_id=owner, counters={"manifest_calls": 1} if name == "manifest" else None):
                result = function(repo, *args, **kwargs)
            if name == "context-query" and isinstance(result, dict) and "architecture_context" not in result:
                from context_presentation import architecture_context
                result["architecture_context"] = architecture_context(result)
            return result
        return wrapped
    return decorate
