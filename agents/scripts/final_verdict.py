"""Backward command name for the vNext read-only final verifier."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError  # noqa: E402
from workflow import task_dir, verify_task  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", default=os.environ.get("HARNESS_TASK_ID"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.task:
        print("[FAIL] --task or HARNESS_TASK_ID is required", file=sys.stderr)
        return 1
    try:
        result = verify_task(args)
    except (ValidationError, OSError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"FINAL_VERDICT={result['status']}")
        for reason in result.get("blocked_by") or []:
            print(f"[BLOCKED] {reason}")
    return 0 if result["status"] == "APPROVED" else 30 if result["status"] == "ENV_BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
