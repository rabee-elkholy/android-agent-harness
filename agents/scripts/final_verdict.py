"""Aggregate every delivery gate into one machine-readable verdict.

Usage:
  python .agents/scripts/final_verdict.py [--task TASK_ID] [--json]

Reads:
  - gate artifacts: <state>/results/*.json (written by each gate script)
  - review verdict records: <state>/verdicts/verdict-<pkg12>.json via the
    review ledger (<state>/review_ledger.json)

Writes:
  - <state>/last_verdict.json (atomic) — the single delivery decision artifact

Status values:
  APPROVED     every required gate PASS and the 5-leaf verdict is APPROVED
               for the same tree fingerprint
  ENV_BLOCKED  at least one gate failed environmentally (exit-30 protocol:
               HALT, never edit code to bypass)
  STALE        code changed after the review package was generated
  EXPIRED      the review round expired via the barrier TTL
  BLOCKED      any required gate FAIL/MISSING/STALE-artifact, or no git HEAD

Exit codes: 0 = APPROVED, 30 = ENV_BLOCKED, 1 = any other status.
CI must re-run the gates itself and never trust this file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env_codes import EXIT_ENV  # noqa: E402
from _gate_results import (  # noqa: E402
    current_head_sha,
    gate_artifact_name,
    read_gate_result,
)
from _hook_state import (  # noqa: E402
    file_sha256,
    read_verdict_record,
    rounds_used,
    state_path,
    tree_code_fingerprint,
)
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _repo_files import REPO, changed_paths  # noqa: E402

LEAF_KEYS = [
    "bug_reviewer",
    "convention_reviewer",
    "security_reviewer",
    "perf_guardian",
    "regression_reviewer",
]

LEAF_PASS_VALUES = {
    "bug_reviewer": "BUG_PASS",
    "convention_reviewer": "CONVENTION_PASS",
    "security_reviewer": "SECURITY_PASS",
    "perf_guardian": "PERF_PASS",
    "regression_reviewer": "REGRESSION_PASS",
}

LEAF_ALIASES = {
    "bug_reviewer": ("bug_reviewer", "bug-reviewer-agent", "bug-reviewer", "bug"),
    "convention_reviewer": ("convention_reviewer", "convention-reviewer-agent", "convention-reviewer", "convention"),
    "security_reviewer": ("security_reviewer", "security-reviewer-agent", "security-reviewer", "security"),
    "perf_guardian": ("perf_guardian", "perf-anr-guardian-agent", "perf-anr-guardian", "perf"),
    "regression_reviewer": ("regression_reviewer", "regression-impact-reviewer-agent", "regression-impact-reviewer", "regression"),
}


def _product_bits() -> dict:
    try:
        import _product  # noqa: PLC0415

        return {
            "unit_test_task": str(getattr(_product, "UNIT_TEST_TASK", ":app:testDebugUnitTest")),
            "assemble_task": str(getattr(_product, "ASSEMBLE_TASK", ":app:assembleDebug")),
            "device_mode": str(getattr(_product, "DEVICE_VERIFICATION_MODE", "autonomous_e2e") or "autonomous_e2e"),
        }
    except Exception:
        return {
            "unit_test_task": ":app:testDebugUnitTest",
            "assemble_task": ":app:assembleDebug",
            "device_mode": "autonomous_e2e",
        }


def _ledger_path() -> Path:
    return state_path().with_name("review_ledger.json")


def _read_ledger() -> dict | None:
    try:
        path = _ledger_path()
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def diff_sha256(files: list[tuple[str, str]]) -> str:
    lines = "\n".join(f"{rel} {digest}" for rel, digest in sorted(files))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def working_files(files_override: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    if files_override is not None:
        return list(files_override)
    out: list[tuple[str, str]] = []
    for path in changed_paths():
        try:
            rel = path.relative_to(REPO).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            out.append((rel, file_sha256(path)))
        except Exception:
            continue
    return out


def _normalize_check(name: str, rec: dict | None, head_sha: str) -> dict:
    if rec is None:
        return {
            "name": name,
            "status": "MISSING",
            "exit_code": None,
            "env_class": None,
            "detail": "gate artifact not found; run this gate first",
        }
    exit_code = rec.get("exit_code")
    env_class = str(rec.get("env_class") or "").upper()
    status = str(rec.get("status") or "").upper()
    if status not in ("PASS", "FAIL", "ENV"):
        if env_class in ("ENV", "AMBIGUOUS") or exit_code == EXIT_ENV:
            status = "ENV"
        elif exit_code == 0:
            status = "PASS"
        else:
            status = "FAIL"
    artifact_head = str(rec.get("git_sha") or "")
    if head_sha and artifact_head and artifact_head != head_sha:
        status = "STALE"
    return {
        "name": name,
        "status": status,
        "exit_code": exit_code,
        "env_class": env_class,
        "detail": str(rec.get("detail") or "")[:300],
    }


def _pick_leaf(leaves: dict, key: str) -> str | None:
    for alias in LEAF_ALIASES[key]:
        value = leaves.get(alias)
        if value:
            return str(value)
    return None


def _review_outcome(tree_fp: str | None) -> tuple[dict, dict, str, bool]:
    ledger = _read_ledger()
    check = {
        "name": "five_leaves",
        "status": "MISSING",
        "exit_code": None,
        "env_class": None,
        "detail": "no review ledger; run review_package.py and the 5 leaves first",
    }
    leaves_map: dict = {}
    stale = ""
    expired = False
    if not ledger:
        return check, leaves_map, stale, expired
    digest = str(ledger.get("sha256") or "")
    if len(digest) < 12:
        check["detail"] = "review ledger has no package sha256"
        return check, leaves_map, stale, expired
    pkg12 = digest[:12]
    record = read_verdict_record(pkg12)
    if not record:
        check["detail"] = f"no verdict record for package {pkg12}"
        return check, leaves_map, stale, expired
    verdict = str(record.get("verdict") or "").upper()
    if verdict == "EXPIRED":
        expired = True
        check["status"] = "FAIL"
        check["detail"] = "review round EXPIRED via the barrier TTL; re-dispatch the 5 leaves"
        return check, leaves_map, stale, expired
    raw_leaves = record.get("leaves") or {}
    for key in LEAF_KEYS:
        leaves_map[key] = _pick_leaf(raw_leaves, key)
    missing = [key for key, value in leaves_map.items() if value != LEAF_PASS_VALUES[key]]
    if verdict != "APPROVED":
        check["status"] = "FAIL"
        check["detail"] = f"review verdict is {verdict or 'PENDING'}, not APPROVED"
    elif missing:
        check["status"] = "FAIL"
        check["detail"] = "missing leaf verdicts: " + ", ".join(missing)
    else:
        check["status"] = "PASS"
        check["detail"] = f"5 leaves APPROVED for package {pkg12}"
    fp_now = tree_fp
    if fp_now is not None:
        record_fp = record.get("tree_fingerprint")
        ledger_fp = ledger.get("tree_fingerprint")
        if record_fp and record_fp != fp_now:
            stale = "code changed after the review package was generated (verdict fingerprint mismatch)"
        elif ledger_fp and ledger_fp != fp_now:
            stale = "code changed after the review package was generated (ledger fingerprint mismatch)"
    return check, leaves_map, stale, expired


def _baseline_ignored_count() -> int:
    try:
        path = state_path().with_name("baseline.json")
        if not path.is_file():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return 0
        tests = data.get("unit_tests") or []
        return len(tests) if isinstance(tests, list) else 0
    except Exception:
        return 0


def build_verdict(
    *,
    task_id: str = "",
    head_sha: str | None = None,
    tree_fp: str | None = None,
    files_override: list[tuple[str, str]] | None = None,
    bits: dict | None = None,
) -> dict:
    bits = bits or _product_bits()
    head = head_sha if head_sha is not None else current_head_sha()
    fp = tree_fp if tree_fp is not None else tree_code_fingerprint()
    files = working_files(files_override)
    required_devices = str(bits.get("device_mode") or "autonomous_e2e") != "disabled"

    checks = [
        _normalize_check(
            "unit_tests",
            read_gate_result("unit_tests")
            or read_gate_result(gate_artifact_name(bits["unit_test_task"])),
            head,
        ),
        _normalize_check("preflight", read_gate_result("preflight"), head),
        _normalize_check("assemble", read_gate_result(gate_artifact_name(bits["assemble_task"])), head),
    ]
    if required_devices:
        checks.append(_normalize_check("device", read_gate_result("device"), head))
        checks.append(_normalize_check("e2e", read_gate_result("e2e"), head))
    review_check, leaves_map, stale_review, expired = _review_outcome(fp)
    checks.append(review_check)

    blocked_by: list[str] = []
    status = "APPROVED"
    if not head:
        status = "BLOCKED"
        blocked_by.append("no git HEAD in this checkout; create an initial commit")
    elif expired:
        status = "EXPIRED"
        blocked_by.append(review_check["detail"])
    elif any(c["status"] == "ENV" for c in checks):
        status = "ENV_BLOCKED"
        blocked_by.extend(f"{c['name']}: {c['detail']}" for c in checks if c["status"] == "ENV")
    elif stale_review:
        status = "STALE"
        blocked_by.append(stale_review)
    else:
        bad = [c for c in checks if c["status"] in ("FAIL", "MISSING", "STALE")]
        if bad:
            status = "BLOCKED"
            blocked_by.extend(f"{c['name']}: {c['detail']}" for c in bad)

    return {
        "schema_version": 1,
        "task_id": task_id,
        "status": status,
        "verdict_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_context": {
            "head_commit": head,
            "diff_sha256": diff_sha256(files),
            "files_count": len(files),
        },
        "tree_fingerprint": fp,
        "checks": checks,
        "leaves": leaves_map,
        "blocked_by": blocked_by,
        "pre_existing_debt_ignored": _baseline_ignored_count(),
        "review_rounds_used": rounds_used(task_id),
    }


def write_last_verdict(verdict: dict) -> Path | None:
    target = state_path().with_name("last_verdict.json")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, target)
        return target
    except Exception:
        return None


def exit_code_for(status: str) -> int:
    if status == "APPROVED":
        return 0
    if status == "ENV_BLOCKED":
        return EXIT_ENV
    return 1


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Aggregate delivery gates into one machine-readable verdict")
    parser.add_argument("--task", default=None, help="Task id recorded in the verdict (default: $HARNESS_TASK_ID).")
    parser.add_argument("--json", action="store_true", help="Print the verdict JSON to stdout")
    args = parser.parse_args()

    task_id = (args.task or os.environ.get("HARNESS_TASK_ID") or "").strip()
    verdict = build_verdict(task_id=task_id)
    target = write_last_verdict(verdict)

    live_print(f"[*] Final verdict: {verdict['status']}")
    for check in verdict["checks"]:
        live_print(f"  - {check['name']}: {check['status']}")
    if verdict["blocked_by"]:
        live_print("[!] Blocked by:")
        for item in verdict["blocked_by"]:
            live_print(f"  - {item}")
    if target:
        live_print(f"[*] Verdict artifact: {target}")
    else:
        live_print("[!] Could not write last_verdict.json", err=True)
    if args.json:
        print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return exit_code_for(verdict["status"])


if __name__ == "__main__":
    sys.exit(main())
