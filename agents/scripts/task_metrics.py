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


def _directory(repo, task_id):
    return bounded_path(repo / ".agents/state/metrics", validate_id(task_id, "task id"))


def record_operation(repo, task_id, operation, duration, exit_code, started=None):
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
              "history_capped": False,
              "limitations": "Observed launcher commands only; waits and host reviewer execution are not inferred."}
    if not directory.exists():
        return result
    plan_path = repo / ".agents/state/tasks" / validate_id(task_id) / "plan.json"
    try:
        if plan_path.stat().st_size <= 262144:
            plan = read_json(plan_path)
            if plan.get("task_id") == task_id:
                result["review_rounds"] = plan.get("review_rounds", 0)
                result["current_blocked_reviewers"] = plan.get("blocked_reviewers") or []
    except (OSError, ValidationError):
        pass
    import itertools
    paths = list(itertools.islice(directory.iterdir(), MAX_EVENTS + 1))
    result["history_capped"] = len(paths) >= MAX_EVENTS
    total, intervals = 0.0, []
    valid = 0
    for path in paths[:MAX_EVENTS]:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_EVENT_BYTES:
                raise ValidationError("oversized or symlink metric")
            event = read_json(path)
            if event.get("schema_version") != 1 or event.get("task_id") != task_id:
                raise ValidationError("invalid metric identity")
            duration = float(event["duration_seconds"])
            start, end = float(event["started_at"]), float(event["ended_at"])
            if not all(math.isfinite(x) for x in (duration, start, end)) or duration < 0 or end < start:
                raise ValidationError("invalid metric timing")
            operation = validate_id(event["operation"])
            row = result["operations"].setdefault(operation, {"attempts": 0, "nonzero_exits": 0, "seconds": 0.0})
            row["attempts"] += 1
            row["nonzero_exits"] += int(event["exit_code"] != 0)
            row["seconds"] += duration
            total += duration
            intervals.append((start, end))
            valid += 1
        except (OSError, ValueError, KeyError, TypeError, ValidationError):
            result["invalid_events"] += 1
    if valid:
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
