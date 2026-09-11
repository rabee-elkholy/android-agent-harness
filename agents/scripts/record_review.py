"""Validate structured reviewer reports and record one immutable review artifact."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, canonical_sha256, read_json, sha256_file, utc_now  # noqa: E402
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
        report_identities.append({
            "reviewer": reviewer,
            "report_sha256": sha256_file(report_path),
            "verdict": verdict,
            "provenance": str(report.get("provenance") or "unspecified"),
        })

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


def verdict_to_report(
    repo: Path,
    task_id: str,
    reviewer: str,
    verdict: str,
    message: str = "",
    severity: str = "HIGH",
    evidence_pkg: str = "",
    citations: int = 0,
) -> dict:
    directory = task_dir(repo, task_id)
    current = read_json(directory / "current-run.json")
    manifest = read_json(Path(current["manifest"]))
    package = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"] / "review-package.md"
    if not package.is_file():
        raise ValidationError("immutable review package is missing")
    package_sha = sha256_file(package)
    if evidence_pkg:
        clean_pkg = evidence_pkg.strip().lower()
        if not package_sha[:12].startswith(clean_pkg) and not clean_pkg.startswith(package_sha[:12]):
            raise ValidationError(f"evidence package sha prefix mismatch: {clean_pkg} != {package_sha[:12]}")
    v_upper = verdict.strip().upper()
    if v_upper not in VALID_VERDICTS:
        raise ValidationError(f"invalid verdict {verdict}; must be PASS or FINDINGS")
    findings = []
    if v_upper != "PASS":
        findings.append({
            "severity": severity if severity in VALID_SEVERITIES else "HIGH",
            "message": message or f"Reviewer {reviewer} reported blocking findings.",
            "reported_citations": citations,
        })
    return {
        "schema_version": 1,
        "reviewer": reviewer,
        "package_sha256": package_sha,
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "change_set_sha256": manifest["change_set_sha256"],
        "verdict": v_upper,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", required=True)
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--response", action="append", default=[], metavar="REVIEWER=PATH", help="Ingest an unchanged reviewer response with its evidence footer")
    parser.add_argument("--verdict", action="append", default=[], metavar="[REVIEWER=]VERDICT", help="Record a reviewer verdict directly (e.g. bug-reviewer-agent=PASS, or PASS with --reviewer)")
    parser.add_argument("--reviewer", help="Reviewer name when recording a single verdict with --verdict")
    parser.add_argument("--evidence-pkg", default="", help="Optional package SHA prefix to validate against active review package")
    parser.add_argument("--message", default="", help="Optional finding message if verdict is FINDINGS")
    parser.add_argument("--severity", default="HIGH", help="Severity of findings (default HIGH)")
    parser.add_argument("--citations", type=int, default=0, help="Reported citations count")
    parser.add_argument("--status", action="store_true", help="Show currently staged review status for active run")
    parser.add_argument("--override-reviews", action="store_true", help="Record explicit developer override of semantic reviewers")
    parser.add_argument("--proof-reference", default="", help="Proof reference for developer override")
    parser.add_argument("--source", choices=("host_native", "conversation", "developer_terminal"), default="conversation", help="Source for developer override")
    args = parser.parse_args()
    try:
        repo = Path(args.repo).resolve()
        task_directory = task_dir(repo, args.task)
        plan = read_json(task_directory / "plan.json")
        current = read_json(task_directory / "current-run.json")
        policy = read_json(Path(current["policy"]))
        required = set(policy.get("reviewers") or [])
        staging_dir = task_directory / "staged-reviews" / str(current["run_id"])
        staging_dir.mkdir(parents=True, exist_ok=True)

        if args.override_reviews:
            if plan.get("status") != "VERIFYING":
                raise ValidationError("review override requires a VERIFYING plan")
            if not str(args.proof_reference).strip():
                raise ValidationError("review override requires non-empty --proof-reference")
            severity = str(policy.get("severity") or "").upper()
            if severity in ("HIGH", "CRITICAL"):
                raise ValidationError(f"review override is strictly forbidden for {severity} severity changes")
            sensitive = sorted(set(policy.get("surfaces") or []) & {"BILLING", "AUTH", "SECURITY", "SENSITIVE_DATA", "CRYPTO"})
            if sensitive:
                raise ValidationError(f"review override is strictly forbidden on sensitive surfaces: {', '.join(sensitive)}")
            manifest = read_json(Path(current["manifest"]))

            version_file = (repo / ".agents" / "VERSION") if (repo / ".agents").is_dir() else (repo / "agents" / "VERSION")
            harness_version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"
            override_evidence = {
                "schema_version": 1,
                "developer_override": True,
                "source": args.source,
                "proof_reference_sha256": canonical_sha256({"reference": args.proof_reference}),
                "overridden_reviewers": sorted(required),
                "timestamp": utc_now(),
            }
            path = EvidenceStore(state_root(repo)).write(
                snapshot=manifest["delivery_snapshot_sha256"],
                run_id=str(current["run_id"]),
                name="reviews",
                producer="developer_approval",
                harness_version=harness_version,
                change_set=manifest["change_set_sha256"],
                status="PASS",
                evidence=override_evidence,
            )
            print(f"REVIEW_OVERRIDE=DEVELOPER_OVERRIDE {path}")
            return 0

        if args.status:
            staged_files = list(staging_dir.glob("*.json"))
            staged_names = {p.stem for p in staged_files}
            missing = required - staged_names
            print(f"STAGED_REVIEWS={len(staged_names)}/{len(required)}")
            for p in sorted(staged_files):
                r = read_json(p)
                print(f"  - {r.get('reviewer')}: {r.get('verdict')}")
            if missing:
                print("MISSING_REVIEWERS=" + ", ".join(sorted(missing)))
            return 0

        for rep_str in args.report:
            rep_path = Path(rep_str).resolve()
            rep = read_json(rep_path)
            reviewer = str(rep.get("reviewer") or "")
            if not reviewer:
                raise ValidationError(f"report {rep_path} has no reviewer field")
            rep.setdefault("provenance", "structured_report")
            (staging_dir / f"{reviewer}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

        for item in args.response:
            reviewer, sep, raw_path = item.partition("=")
            if not sep:
                raise ValidationError("--response must be REVIEWER=PATH")
            rep = response_to_report(repo, args.task, reviewer.strip(), Path(raw_path).resolve())
            rep["provenance"] = "reviewer_response_footer"
            (staging_dir / f"{reviewer.strip()}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

        verdict_items = list(args.verdict)
        if args.reviewer and verdict_items:
            v_val = verdict_items[-1]
            if "=" in v_val:
                r_name, _, v_val = v_val.partition("=")
            else:
                r_name = args.reviewer
            rep = verdict_to_report(
                repo, args.task, r_name.strip(), v_val.strip(),
                message=args.message, severity=args.severity,
                evidence_pkg=args.evidence_pkg, citations=args.citations,
            )
            rep["provenance"] = "lead_agent_recorded_verdict"
            (staging_dir / f"{r_name.strip()}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        elif verdict_items:
            for item in verdict_items:
                reviewer, sep, v_val = item.partition("=")
                if not sep:
                    raise ValidationError("--verdict without --reviewer must be REVIEWER=VERDICT")
                rep = verdict_to_report(
                    repo, args.task, reviewer.strip(), v_val.strip(),
                    message=args.message, severity=args.severity,
                    evidence_pkg=args.evidence_pkg, citations=args.citations,
                )
                rep["provenance"] = "lead_agent_recorded_verdict"
                (staging_dir / f"{reviewer.strip()}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")


        staged_files = sorted(staging_dir.glob("*.json"))
        if not staged_files:
            raise ValidationError("at least one --report, --response, or --verdict is required")

        staged_names = {p.stem for p in staged_files}
        missing = required - staged_names
        if missing:
            print(f"STAGED_REVIEW ({len(staged_names)}/{len(required)} recorded, waiting for: {', '.join(sorted(missing))})")
            return 0

        path = ingest(repo, args.task, staged_files)
        print(f"REVIEW_EVIDENCE={path}")
        return 0
    except (ValidationError, OSError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
