"""Validate structured reviewer reports and record one immutable review artifact."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, read_json, sha256_file  # noqa: E402
from evidence_store import EvidenceStore  # noqa: E402
from workflow import state_root, task_dir  # noqa: E402


VALID_VERDICTS = {"PASS", "FINDINGS"}
VALID_SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH", "MAJOR", "CRITICAL", "BLOCKER"}
PASS_TOKENS = {
    "bug-reviewer-agent": "BUG_PASS",
    "convention-reviewer-agent": "CONVENTION_PASS",
    "security-reviewer-agent": "SECURITY_PASS",
    "perf-anr-guardian-agent": "PERF_PASS",
    "regression-impact-reviewer-agent": "REGRESSION_PASS",
    "test-quality-reviewer-agent": "TEST_PASS",
}


def response_to_report(repo: Path, task_id: str, reviewer: str, response_path: Path) -> dict:
    directory = task_dir(repo, task_id)
    current = read_json(directory / "current-run.json")
    manifest = read_json(Path(current["manifest"]))
    package = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"] / "review-package.md"
    package_sha = sha256_file(package)
    text = response_path.read_text(encoding="utf-8", errors="replace")
    footer = re.search(r"EVIDENCE\s+pkg=([0-9a-fA-F]{12})\s+cites=(\d+)\s*$", text.strip())
    if not footer or footer.group(1).lower() != package_sha[:12]:
        raise ValidationError(f"reviewer {reviewer} response has no matching evidence footer")
    pass_token = PASS_TOKENS.get(reviewer)
    clean = bool(pass_token and re.search(rf"(?m)^\s*{re.escape(pass_token)}\s*$", text))
    return {
        "schema_version": 1,
        "reviewer": reviewer,
        "package_sha256": package_sha,
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "change_set_sha256": manifest["change_set_sha256"],
        "verdict": "PASS" if clean else "FINDINGS",
        "findings": [] if clean else [{
            "severity": "HIGH",
            "message": "Reviewer reported blocking findings; consult the immutable response identity.",
            "response_sha256": sha256_file(response_path),
            "reported_citations": int(footer.group(2)),
        }],
    }


def ingest(repo: Path, task_id: str, reports: list[Path]) -> Path:
    directory = task_dir(repo, task_id)
    plan = read_json(directory / "plan.json")
    current = read_json(directory / "current-run.json")
    manifest = read_json(Path(current["manifest"]))
    policy = read_json(Path(current["policy"]))
    if plan.get("status") != "VERIFYING":
        raise ValidationError("review ingestion requires a VERIFYING plan")
    round_number = int(plan.get("review_rounds") or 0) + 1
    if round_number > int(policy.get("max_review_rounds") or 3):
        raise ValidationError("review round cap reached; developer decision is required")
    package = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"] / "review-package.md"
    if not package.is_file():
        raise ValidationError("immutable review package is missing")
    package_sha = sha256_file(package)
    required = set(policy.get("reviewers") or [])
    seen: set[str] = set()
    findings: list[dict] = []
    report_identities: list[dict] = []
    for report_path in reports:
        report = read_json(report_path)
        reviewer = str(report.get("reviewer") or "")
        if report.get("schema_version") != 1:
            raise ValidationError(f"reviewer {reviewer or '<missing>'} report schema is unsupported")
        if reviewer not in required:
            raise ValidationError(f"unexpected reviewer report: {reviewer or '<missing>'}")
        if reviewer in seen:
            raise ValidationError(f"duplicate reviewer report: {reviewer}")
        seen.add(reviewer)
        if report.get("package_sha256") != package_sha:
            raise ValidationError(f"reviewer {reviewer} did not inspect the active package")
        if report.get("delivery_snapshot_sha256") != manifest["delivery_snapshot_sha256"]:
            raise ValidationError(f"reviewer {reviewer} snapshot mismatch")
        if report.get("change_set_sha256") != manifest["change_set_sha256"]:
            raise ValidationError(f"reviewer {reviewer} change-set mismatch")
        verdict = str(report.get("verdict") or "").upper()
        if verdict not in VALID_VERDICTS:
            raise ValidationError(f"reviewer {reviewer} returned malformed verdict")
        report_findings = report.get("findings") or []
        if not isinstance(report_findings, list):
            raise ValidationError(f"reviewer {reviewer} findings must be a list")
        if verdict == "PASS" and report_findings:
            raise ValidationError(f"reviewer {reviewer} claims PASS with findings")
        for finding in report_findings:
            if not isinstance(finding, dict) or str(finding.get("severity") or "").upper() not in VALID_SEVERITIES:
                raise ValidationError(f"reviewer {reviewer} returned a malformed finding")
            if not str(finding.get("message") or "").strip():
                raise ValidationError(f"reviewer {reviewer} finding has no message")
        findings.extend({"reviewer": reviewer, **item} for item in report_findings if isinstance(item, dict))
        report_identities.append({"reviewer": reviewer, "report_sha256": sha256_file(report_path), "verdict": verdict})
    missing = required - seen
    if missing:
        raise ValidationError("missing required reviewer reports: " + ", ".join(sorted(missing)))
    used_calls = int(plan.get("review_calls_used") or 0)
    budget = int(policy.get("model_call_budget") or 0)
    if used_calls + len(seen) > budget:
        raise ValidationError("review model-call budget exceeded; developer decision is required")
    blocking = [item for item in findings if str(item.get("severity") or "").upper() in ("BLOCKER", "MAJOR", "CRITICAL", "HIGH")]
    status = "FAIL" if blocking else "PASS"
    evidence_path = EvidenceStore(state_root(repo)).write(
        snapshot=manifest["delivery_snapshot_sha256"],
        run_id=current["run_id"],
        name="reviews",
        producer="review_orchestrator",
        harness_version=(repo / ".agents" / "VERSION").read_text(encoding="utf-8").strip(),
        change_set=manifest["change_set_sha256"],
        status=status,
        evidence={
            "package_sha256": package_sha,
            "reviewers": sorted(seen),
            "reports": report_identities,
            "findings": findings,
            "blocking_findings": blocking,
            "is_truncated": False,
            "round": round_number,
        },
    )
    plan["review_rounds"] = round_number
    plan["review_calls_used"] = used_calls + len(seen)
    if blocking:
        plan["status"] = "BLOCKED"
        plan["blocked_reviewers"] = sorted({str(item.get("reviewer") or "") for item in blocking})
    from plan_authority import save_plan
    save_plan(directory / "plan.json", plan)
    return evidence_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", required=True)
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--response", action="append", default=[], metavar="REVIEWER=PATH", help="Ingest an unchanged reviewer response with its evidence footer")
    args = parser.parse_args()
    try:
        repo = Path(args.repo).resolve()
        report_paths = [Path(item).resolve() for item in args.report]
        with tempfile.TemporaryDirectory(prefix="harness-review-") as temp:
            for index, item in enumerate(args.response):
                reviewer, sep, raw_path = item.partition("=")
                if not sep:
                    raise ValidationError("--response must be REVIEWER=PATH")
                report = response_to_report(repo, args.task, reviewer.strip(), Path(raw_path).resolve())
                generated = Path(temp) / f"report-{index}.json"
                generated.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
                report_paths.append(generated)
            if not report_paths:
                raise ValidationError("at least one --report or --response is required")
            path = ingest(repo, args.task, report_paths)
    except (ValidationError, OSError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"REVIEW_EVIDENCE={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
