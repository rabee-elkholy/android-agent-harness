"""Benchmark metrics collector: agent-alone vs agent+harness runs.

Stdlib only. Zero network. Given a run directory it renders a markdown
results row per task.

Run directory layout (all optional, missing files count as zero):

    events.jsonl         one JSON object per line:
                         {"ts": <epoch-seconds>, "task": "<task-id>",
                          "kind": "review_round" | "build" | "test" |
                                  "device" | "intervention" | "block",
                          "detail": "<free text>"}
    audit_log.jsonl      the harness safety audit log (optional; its "deny"
                         records are counted as unsafe-action blocks)
    interventions.json   {"<task-id>": <count>} manual human interventions
    tokens.jsonl         {"task": "<task-id>", "tokens": <int>} usage lines

Usage:

    python scripts_dev/benchmark/metrics.py --run-dir runs/harness-arm
    python scripts_dev/benchmark/metrics.py --run-dir runs/baseline-arm --label "Agent alone"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KINDS = ("review_round", "build", "test", "device", "intervention", "block")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def collect(run_dir: Path) -> dict[str, dict]:
    events = _read_jsonl(run_dir / "events.jsonl")
    audit = _read_jsonl(run_dir / "audit_log.jsonl")
    tokens = _read_jsonl(run_dir / "tokens.jsonl")
    interventions_path = run_dir / "interventions.json"
    manual: dict[str, int] = {}
    if interventions_path.is_file():
        try:
            raw = json.loads(interventions_path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                manual = {str(k): int(v) for k, v in raw.items()}
        except Exception:
            pass

    tasks: dict[str, dict] = {}

    def bucket(task_id: str) -> dict:
        return tasks.setdefault(
            task_id,
            {
                "retries": 0,
                "blocks": 0,
                "build_failures": 0,
                "test_failures": 0,
                "interventions": 0,
                "tokens": 0,
                "first_ts": None,
                "last_ts": None,
            },
        )

    for event in events:
        task_id = str(event.get("task") or "?")
        row = bucket(task_id)
        kind = str(event.get("kind") or "")
        ts = event.get("ts")
        if isinstance(ts, (int, float)):
            row["first_ts"] = ts if row["first_ts"] is None else min(row["first_ts"], ts)
            row["last_ts"] = ts if row["last_ts"] is None else max(row["last_ts"], ts)
        if kind == "review_round":
            row["retries"] += 1
        elif kind == "block":
            row["blocks"] += 1
        elif kind == "build":
            detail = str(event.get("detail") or "").lower()
            if "fail" in detail:
                row["build_failures"] += 1
        elif kind == "test":
            detail = str(event.get("detail") or "").lower()
            if "fail" in detail:
                row["test_failures"] += 1
        elif kind == "intervention":
            row["interventions"] += 1

    for record in audit:
        if str(record.get("decision") or "").lower() == "deny":
            bucket("?")  # audit rows have no task id; keep a shared bucket
            tasks["?"]["blocks"] += 1

    for task_id, count in manual.items():
        bucket(task_id)["interventions"] += count

    for record in tokens:
        task_id = str(record.get("task") or "?")
        value = record.get("tokens")
        if isinstance(value, (int, float)):
            bucket(task_id)["tokens"] += int(value)

    for row in tasks.values():
        if row["first_ts"] is not None and row["last_ts"] is not None:
            row["minutes"] = round((row["last_ts"] - row["first_ts"]) / 60.0, 1)
        else:
            row["minutes"] = ""
    return tasks


def render(tasks: dict[str, dict], label: str) -> str:
    header = (
        "| Task | Retries (review rounds) | Unsafe-action blocks | Build failures "
        "| Test failures | Human interventions | Tokens | Minutes |\n"
        "|---|---|---|---|---|---|---|---|"
    )
    lines = [f"# Benchmark results — {label}", "", header]
    for task_id in sorted(tasks):
        row = tasks[task_id]
        lines.append(
            f"| {task_id} | {row['retries']} | {row['blocks']} | {row['build_failures']} "
            f"| {row['test_failures']} | {row['interventions']} | {row['tokens'] or ''} "
            f"| {row['minutes']} |"
        )
    if not tasks:
        lines.append("")
        lines.append("(no events recorded yet)")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except OSError:
            pass
    parser = argparse.ArgumentParser(description="Render benchmark metrics as markdown.")
    parser.add_argument("--run-dir", required=True, help="Run directory with events.jsonl etc.")
    parser.add_argument("--label", default="Unnamed arm", help="Arm label for the table title.")
    args = parser.parse_args(argv)
    print(render(collect(Path(args.run_dir)), args.label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
