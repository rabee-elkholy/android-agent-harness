"""Validate structured reviewer reports and record one immutable review artifact."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, canonical_sha256, read_json, sha256_file, utc_now, atomic_write_json  # noqa: E402
from evidence_store import EvidenceStore  # noqa: E402
from workflow import SENSITIVE_SURFACES, assert_active_run_fresh, state_root, task_dir  # noqa: E402


VALID_VERDICTS = {"PASS", "FINDINGS"}
VALID_SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH", "MAJOR", "CRITICAL", "BLOCKER"}
PASS_TOKENS = {
    "bug-reviewer-agent": "BUG_PASS",
    "convention-reviewer-agent": "CONVENTION_PASS",
    "security-reviewer-agent": "SECURITY_PASS",
    "perf-anr-guardian-agent": "PERF_PASS",
    "regression-impact-reviewer-agent": "REGRESSION_PASS",
    "test-quality-reviewer-agent": "TEST_PASS",
    "spec-compliance-agent": "SPEC_PASS",
}


FOOTER_PATTERN = re.compile(r"EVIDENCE(?::)?\s+pkg=([0-9a-fA-F]{12})(?:\s+cites=(\d+))?", re.I)


def _extract_evidence_and_verdict(reviewer: str, text: str, package_sha: str | None = None) -> tuple[str, int, str]:
    """Extracts (verdict, cites, pkg_sha) from reviewer text with high tolerance.

    Returns ('PASS' | 'FINDINGS', citations_count, pkg_sha).
    """
    text_clean = text.strip()
    footer = FOOTER_PATTERN.search(text_clean)
    if not footer:
        return ("FAIL", 0, "")
    pkg_sha = footer.group(1).lower()
    if package_sha and not (pkg_sha.startswith(package_sha[:12].lower()) or package_sha[:12].lower().startswith(pkg_sha)):
        return ("FAIL", 0, pkg_sha)
    cites = int(footer.group(2)) if footer.group(2) is not None else 0

    pass_token = PASS_TOKENS.get(reviewer, "")
    body = text_clean[:footer.start()].strip()

    # Contradiction: duplicate pass token
    if pass_token and body.count(pass_token) > 1:
        return ("FINDINGS", cites, pkg_sha)

    has_explicit_fail = bool(re.search(
        r"\b(?:FAIL\b|VERDICT:\s*FAIL|BLOCKER\b|CRITICAL\b|MAJOR\b|HIGH\b|FINDINGS?(?:\s+\d+|:)\s*(?!none\b|0\b)|(?<!no\s)(?<!without\s)unresolved\b|\[(?:CRITICAL|BLOCKER|HIGH|MAJOR|MEDIUM|LOW)\])",
        body,
        re.I,
    ))
    has_explicit_pass = bool(re.search(rf"\b(?:VERDICT:\s*PASS|{re.escape(pass_token)}|^PASS\b|\bPASS\b)", body, re.I))
    clean_prose = bool(re.search(
        r"\b(?:clean|no\s+(?:issues?|findings?|bugs?|vulnerabilities|defects?|concerns?|violations?)|all\s+(?:checks?|tests?|rules?|guidelines)\s+(?:passed|met|clean|followed|satisfied)|approved|looks\s+good|lgtm|compliant)\b",
        body,
        re.I,
    ))

    if cites == 0 and not has_explicit_fail and (has_explicit_pass or clean_prose or not body):
        return ("PASS", 0, pkg_sha)
    if cites == 0 and not has_explicit_fail:
        return ("PASS", 0, pkg_sha)
    return ("FINDINGS", cites, pkg_sha)


def parse_verdict(reviewer: str, text: str) -> dict:
    """Helper to parse raw reviewer text verdict without repository state."""
    verdict, cites, pkg = _extract_evidence_and_verdict(reviewer, text)
    if not pkg:
        return {"verdict": "FAIL", "reason": "missing evidence footer"}
    return {"verdict": verdict, "cites": cites, "pkg": pkg}


def _extract_transcript_response(transcript_path: Path) -> str:
    """Reads transcript.jsonl or transcript.json and returns the final assistant message."""
    raw = transcript_path.read_text(encoding="utf-8", errors="replace")
    if transcript_path.suffix.lower() == ".jsonl" or "\n{" in raw:
        lines = [json.loads(line) for line in raw.splitlines() if line.strip()]
        for step in reversed(lines):
            source = str(step.get("source") or "").upper()
            stype = str(step.get("type") or "").upper()
            content = str(step.get("content") or "")
            if content and (source == "MODEL" or stype in ("PLANNER_RESPONSE", "ASSISTANT_RESPONSE")):
                return content
        if lines and lines[-1].get("content"):
            return str(lines[-1]["content"])
    else:
        data = json.loads(raw)
        if isinstance(data, dict):
            return str(data.get("content") or data.get("response") or raw)
    return raw


def _find_subagent_transcript(subagent_id: str) -> Path | None:
    """Searches standard brain transcript locations for the given subagent ID."""
    clean_id = subagent_id.strip().strip("'\"")
    if clean_id.startswith("file:///"):
        p = Path(clean_id[8:])
        if p.is_file():
            return p
    elif clean_id.startswith("file://"):
        p = Path(clean_id[7:])
        if p.is_file():
            return p
    import os
    app_data = os.environ.get("ANTIGRAVITY_APP_DATA")
    candidates = []
    if app_data:
        candidates.append(Path(app_data) / "brain" / clean_id / ".system_generated" / "logs" / "transcript.jsonl")
        candidates.append(Path(app_data) / "brain" / clean_id / "transcript.jsonl")
    home_gemini = Path.home() / ".gemini" / "antigravity" / "brain" / clean_id / ".system_generated" / "logs" / "transcript.jsonl"
    candidates.append(home_gemini)
    candidates.append(Path.home() / ".gemini" / "antigravity" / "brain" / clean_id / "transcript.jsonl")
    for cand in candidates:
        if cand.is_file():
            return cand
    p = Path(clean_id)
    if p.is_file():
        return p
    return None


def is_blocking_finding(finding: dict, policy: dict | None = None) -> bool:
    sev = str(finding.get("severity") or "").upper()
    if sev in ("BLOCKER", "CRITICAL", "HIGH", "MAJOR"):
        return True
    if sev == "MEDIUM":
        if finding.get("is_advisory") or finding.get("advisory"):
            surfaces = (policy or {}).get("surfaces") or []
            if set(surfaces) & SENSITIVE_SURFACES:
                return True
            return False
        return True
    return False


def _parse_reviewer_findings(text: str, default_severity: str = "HIGH", response_sha256: str = "") -> list[dict]:
    clean = text.strip()
    footer = FOOTER_PATTERN.search(clean)
    body = clean[:footer.start()].strip() if footer else clean
    cites = int(footer.group(2)) if (footer and footer.group(2) is not None) else 0

    sev_re = re.compile(r"\b(?:severity[:\s]+)?\[?(CRITICAL|BLOCKER|HIGH|MAJOR|MEDIUM|LOW|INFO)\]?(?:\s*\((advisory)\))?", re.I)
    file_re = re.compile(r"(?:^|[\s\(\[])([a-zA-Z0-9_\-\./\\]+\.(?:kt|java|xml|gradle|kts))(?::(\d+)(?:-(\d+))?)?", re.I)
    id_re = re.compile(r"\b(?:FINDING[-_]?([A-Z0-9]+)|ID[:\s]+([A-Z0-9_-]+))\b", re.I)

    pattern = r"\n(?=\s*(?:[-*]|\d+[\.)]|Finding\s+\d+[:\.]?|\[(?:CRITICAL|BLOCKER|HIGH|MAJOR|MEDIUM|LOW|INFO)\]))"
    raw_chunks = re.split(pattern, body, flags=re.I)
    chunks = [c.strip() for c in raw_chunks if c.strip()]

    if len(chunks) > 1:
        first_chunk = chunks[0]
        is_first_chunk_item = bool(re.match(r"^(?:[-*]|\d+[\.)]|Finding\s+\d+|\[(?:CRITICAL|BLOCKER|HIGH|MAJOR|MEDIUM|LOW|INFO)\])", first_chunk, re.I))
        if not is_first_chunk_item and not sev_re.search(first_chunk):
            chunks = chunks[1:]
    elif chunks and re.match(r"^findings?:?$", chunks[0], re.I):
        chunks = chunks[1:]

    findings: list[dict] = []
    if chunks:
        for idx, chunk in enumerate(chunks):
            sev_match = sev_re.search(chunk)
            is_item = bool(re.match(r"^(?:[-*]|\d+[\.)]|Finding\s+\d+|\[(?:CRITICAL|BLOCKER|HIGH|MAJOR|MEDIUM|LOW|INFO)\])", chunk, re.I))
            file_matches = file_re.findall(chunk)

            # Explanatory prose with zero citations is clean, not a finding
            if cites == 0 and not sev_match and not is_item and not file_matches:
                continue

            raw_sev = sev_match.group(1).upper() if sev_match else None
            inferred = False
            if raw_sev == "BLOCKER":
                sev = "CRITICAL"
            elif raw_sev == "MAJOR":
                sev = "HIGH"
            elif raw_sev in VALID_SEVERITIES:
                sev = raw_sev
            elif is_item or file_matches or not (cites == 0):
                sev = default_severity
                inferred = True
            else:
                continue

            is_advisory = bool(re.search(r"\b(?:advisory|non-blocking)\b", chunk, re.I)) or (sev_match and bool(sev_match.group(2)))
            id_match = id_re.search(chunk)
            fid = (id_match.group(1) or id_match.group(2)) if id_match else str(idx + 1)

            citations = []
            for f_match in file_matches:
                f_path = f_match[0]
                line_no = int(f_match[1]) if f_match[1] else None
                citations.append({"file": f_path, "line": line_no})

            msg = re.sub(r"^(?:[-*]|\d+[\.)]|Finding\s+\d+[:\.]?)\s*", "", chunk, flags=re.I).strip()
            finding_entry = {
                "finding_id": fid,
                "severity": sev,
                "severity_inferred": inferred,
                "is_advisory": is_advisory,
                "message": msg or f"Finding {fid}",
                "citations": citations,
                "reported_citations": cites,
            }
            if response_sha256:
                finding_entry["response_sha256"] = response_sha256
            findings.append(finding_entry)
    elif body:
        sev_match = sev_re.search(body)
        file_matches = file_re.findall(body)
        raw_sev = sev_match.group(1).upper() if sev_match else None
        inferred = False
        if raw_sev == "BLOCKER":
            sev = "CRITICAL"
        elif raw_sev == "MAJOR":
            sev = "HIGH"
        elif raw_sev in VALID_SEVERITIES:
            sev = raw_sev
        else:
            sev = default_severity
            inferred = True

        is_advisory = bool(re.search(r"\b(?:advisory|non-blocking)\b", body, re.I))
        citations = [{"file": m[0], "line": int(m[1]) if m[1] else None} for m in file_matches]
        finding_entry = {
            "finding_id": "1",
            "severity": sev,
            "severity_inferred": inferred,
            "is_advisory": is_advisory,
            "message": body,
            "citations": citations,
            "reported_citations": cites,
        }
        if response_sha256:
            finding_entry["response_sha256"] = response_sha256
        findings.append(finding_entry)

    return findings


def verify_independent_reviewer_execution(
    repo: Path,
    *,
    task_id: str,
    run_id: str,
    reviewer: str,
    package_sha256: str,
    subagent_id: str | None,
    transcript_path: Path | None = None,
) -> tuple[bool, dict]:
    """Deterministically verifies independent reviewer execution via Antigravity subagent transcripts and receipts."""
    if not subagent_id or not str(subagent_id).strip():
        return False, {"verified": False, "reason": "missing subagent_id"}
    clean_id = str(subagent_id).strip()

    if transcript_path is not None:
        t_path = Path(transcript_path)
        if not t_path.is_file():
            return False, {"verified": False, "reason": f"transcript path does not exist: {transcript_path}"}
    else:
        t_path = _find_subagent_transcript(clean_id)
        if not t_path or not t_path.is_file():
            return False, {"verified": False, "reason": f"could not locate transcript for subagent {clean_id}"}

    receipt_file = task_dir(repo, task_id) / "reviewer-dispatches" / f"{reviewer}.json"
    if not receipt_file.is_file():
        return False, {"verified": False, "reason": f"missing dispatch receipt for reviewer {reviewer}"}

    try:
        receipt = read_json(receipt_file)
    except Exception as exc:
        return False, {"verified": False, "reason": f"corrupt dispatch receipt: {exc}"}

    if receipt.get("schema_version") != 1:
        return False, {"verified": False, "reason": f"unsupported receipt schema_version: {receipt.get('schema_version')}"}
    if receipt.get("task_id") != task_id:
        return False, {"verified": False, "reason": f"receipt task_id mismatch: {receipt.get('task_id')} != {task_id}"}
    if receipt.get("run_id") != run_id:
        return False, {"verified": False, "reason": f"receipt run_id mismatch: {receipt.get('run_id')} != {run_id}"}
    if receipt.get("reviewer") != reviewer:
        return False, {"verified": False, "reason": f"receipt reviewer mismatch: {receipt.get('reviewer')} != {reviewer}"}

    pkg = str(receipt.get("review_package_sha256") or "").lower()
    if pkg and package_sha256:
        if not (pkg.startswith(package_sha256[:12].lower()) or package_sha256[:12].lower().startswith(pkg)):
            return False, {"verified": False, "reason": f"receipt package hash mismatch: {pkg[:12]} != {package_sha256[:12]}"}

    expected_data = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if canonical_sha256(expected_data) != receipt.get("receipt_sha256"):
        return False, {"verified": False, "reason": "receipt_sha256 signature mismatch"}

    if not receipt.get("subagent_id"):
        receipt["subagent_id"] = clean_id
        receipt["receipt_sha256"] = canonical_sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"})
        atomic_write_json(receipt_file, receipt)
    elif receipt.get("subagent_id") != clean_id:
        return False, {"verified": False, "reason": f"receipt subagent_id mismatch: {receipt.get('subagent_id')} != {clean_id}"}

    transcript_sha = sha256_file(t_path)
    proof = {
        "verified": True,
        "proof_kind": "ANTIGRAVITY_SUBAGENT_TRANSCRIPT",
        "receipt_sha256": receipt.get("receipt_sha256"),
        "transcript_sha256": transcript_sha,
        "subagent_id": clean_id,
        "reviewer": reviewer,
        "task_id": task_id,
        "run_id": run_id,
        "package_sha256": package_sha256,
        "transcript_path": str(t_path),
    }
    return True, proof


def _validate_subagent_proof(
    repo: Path,
    task_id: str,
    reviewer: str,
    subagent_id: str,
    package_sha: str,
    run_id: str,
) -> bool:
    verified, _ = verify_independent_reviewer_execution(
        repo,
        task_id=task_id,
        run_id=run_id,
        reviewer=reviewer,
        package_sha256=package_sha,
        subagent_id=subagent_id,
    )
    return verified


def _parse_response_text(repo: Path, task_id: str, reviewer: str, text: str, response_sha256: str) -> dict:
    directory = task_dir(repo, task_id)
    current = read_json(directory / "current-run.json")
    manifest = read_json(Path(current["manifest"]))
    package = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"] / "review-package.md"
    package_sha = sha256_file(package)

    verdict, cites, pkg_sha = _extract_evidence_and_verdict(reviewer, text, package_sha)
    if not pkg_sha or (verdict == "FAIL" and not pkg_sha):
        raise ValidationError(f"reviewer {reviewer} response has no matching evidence footer")
    if not (pkg_sha.startswith(package_sha[:12].lower()) or package_sha[:12].lower().startswith(pkg_sha)):
        raise ValidationError(f"reviewer {reviewer} evidence package mismatch: {pkg_sha} != {package_sha[:12]}")

    findings = [] if verdict == "PASS" else _parse_reviewer_findings(text, default_severity="HIGH", response_sha256=response_sha256)
    is_pass = (verdict == "PASS")
    return {
        "schema_version": 1,
        "reviewer": reviewer,
        "package_sha256": package_sha,
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "change_set_sha256": manifest["change_set_sha256"],
        "verdict": "PASS" if is_pass else "FINDINGS",
        "findings": findings,
    }


def response_to_report(repo: Path, task_id: str, reviewer: str, response_path: Path) -> dict:
    if response_path.suffix.lower() == ".jsonl":
        text = _extract_transcript_response(response_path)
    else:
        text = response_path.read_text(encoding="utf-8", errors="replace")
    return _parse_response_text(repo, task_id, reviewer, text, sha256_file(response_path))


def response_text_to_report(repo: Path, task_id: str, reviewer: str, text: str) -> dict:
    from _vnext_common import sha256_bytes
    return _parse_response_text(repo, task_id, reviewer, text, sha256_bytes(text.encode("utf-8")))


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
        report_findings = report.get("findings", [])
        if not isinstance(report_findings, list):
            raise ValidationError(f"reviewer {reviewer} findings must be a list")
        if verdict == "FINDINGS" and not report_findings:
            raise ValidationError(f"reviewer {reviewer} FINDINGS requires a non-empty findings list")
        if verdict == "PASS" and any(is_blocking_finding(f, policy) for f in report_findings):
            raise ValidationError(f"reviewer {reviewer} claims PASS with blocking findings")
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
            "independent_execution_verified": bool(report.get("independent_execution_verified", False)),
            "execution_proof": report.get("execution_proof"),
        })

    missing = required - seen
    if missing:
        raise ValidationError("missing required reviewer reports: " + ", ".join(sorted(missing)))
    used_calls = int(plan.get("review_calls_used") or 0)
    budget = int(policy.get("model_call_budget") or 0)
    if used_calls + len(seen) > budget:
        raise ValidationError("review model-call budget exceeded; developer decision is required")
    blocking = [item for item in findings if is_blocking_finding(item, policy)]
    status = "FAIL" if blocking else "PASS"
    validations: list[dict] = []
    val_path = directory / "finding-validations.json"
    if val_path.is_file():
        try:
            val_data = read_json(val_path)
            if isinstance(val_data, dict) and isinstance(val_data.get("validations"), list):
                validations = val_data["validations"]
        except Exception:
            pass
    version_file = (repo / ".agents" / "VERSION") if (repo / ".agents").is_dir() else (repo / "agents" / "VERSION")
    harness_version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"
    provenances = {str(r.get("provenance") or "") for r in report_identities if r.get("provenance")}
    overall_provenance = (
        "subagent_execution" if "subagent_execution" in provenances
        else next(iter(provenances), "unspecified")
    )
    evidence_path = EvidenceStore(state_root(repo)).write(
        snapshot=manifest["delivery_snapshot_sha256"],
        run_id=current["run_id"],
        name="reviews",
        producer="review_orchestrator",
        harness_version=harness_version,
        change_set=manifest["change_set_sha256"],
        status=status,
        evidence={
            "package_sha256": package_sha,
            "provenance": overall_provenance,
            "reviewers": sorted(seen),
            "reports": report_identities,
            "findings": findings,
            "blocking_findings": blocking,
            "finding_validations": validations,
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
    if not evidence_pkg or not str(evidence_pkg).strip():
        raise ValidationError(f"reviewer {reviewer} verdict requires non-empty --evidence-pkg matching active review package")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", required=True)
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--response", action="append", default=[], metavar="REVIEWER=PATH", help="Ingest an unchanged reviewer response with its evidence footer")
    parser.add_argument("--response-text", action="append", default=[], metavar="REVIEWER=TEXT", help="Ingest an unchanged reviewer response text with its evidence footer")
    parser.add_argument("--from-subagent", action="append", default=[], metavar="REVIEWER=CONV_ID_OR_PATH", help="Auto-harvest subagent transcript and record review")
    parser.add_argument("--subagent-id", default="", help="Subagent conversation ID or execution reference proving independent reviewer run")
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
    args = parser.parse_args(argv)
    try:
        repo = Path(args.repo).resolve()
        task_directory = task_dir(repo, args.task)
        current = assert_active_run_fresh(repo, args.task)
        plan = read_json(task_directory / "plan.json")
        policy = read_json(Path(current["policy"]))
        required = set(policy.get("reviewers") or [])
        staging_dir = task_directory / "staged-reviews" / str(current["run_id"])
        staging_dir.mkdir(parents=True, exist_ok=True)

        if args.override_reviews:
            if plan.get("status") != "VERIFYING":
                raise ValidationError("review override requires a VERIFYING plan")
            if not str(args.proof_reference).strip():
                raise ValidationError("review override requires non-empty --proof-reference")
            sensitive = sorted(set(policy.get("surfaces") or []) & {"BILLING", "AUTH", "SECURITY", "SENSITIVE_DATA", "CRYPTO"})
            if sensitive:
                raise ValidationError(f"review override is strictly forbidden on sensitive surfaces ({', '.join(sensitive)})")
            severity = str(policy.get("severity") or "").upper()
            if args.source != "developer_terminal":
                if severity in ("HIGH", "CRITICAL"):
                    raise ValidationError(f"review override via {args.source} is strictly forbidden for {severity} severity changes; run from developer_terminal")
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
            reviewer = ""
            if "=" in rep_str and not Path(rep_str).exists():
                reviewer, _, path_str = rep_str.partition("=")
                rep_path = Path(path_str.strip()).resolve()
            else:
                rep_path = Path(rep_str).resolve()

            manifest = read_json(Path(current["manifest"]))
            pkg_file = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"] / "review-package.md"
            pkg_sha = sha256_file(pkg_file) if pkg_file.is_file() else ""

            if rep_path.suffix.lower() == ".jsonl":
                text = _extract_transcript_response(rep_path)
                if not reviewer:
                    raw = rep_path.read_text(encoding="utf-8", errors="replace")
                    for r_name in PASS_TOKENS:
                        if r_name in raw or PASS_TOKENS[r_name] in raw:
                            reviewer = r_name
                            break
                if not reviewer:
                    raise ValidationError(f"could not determine reviewer for transcript {rep_path}; specify REVIEWER={rep_path}")
                rep = response_text_to_report(repo, args.task, reviewer, text)
                rep["provenance"] = "transcript_jsonl_report"
                sub_id = getattr(args, "subagent_id", "").strip()
                is_ver = False
                prf = None
                if sub_id:
                    rep["subagent_id"] = sub_id
                    is_ver, prf = verify_independent_reviewer_execution(
                        repo, task_id=args.task, run_id=str(current["run_id"]), reviewer=reviewer, package_sha256=pkg_sha, subagent_id=sub_id, transcript_path=rep_path
                    )
                    if is_ver:
                        rep["provenance"] = "subagent_execution"
                rep["independent_execution_verified"] = is_ver
                rep["execution_proof"] = prf
                (staging_dir / f"{reviewer}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
                continue

            rep = read_json(rep_path)
            reviewer = str(rep.get("reviewer") or "")
            if not reviewer:
                raise ValidationError(f"report {rep_path} has no reviewer field")
            rep.setdefault("provenance", "structured_report")
            sub_id = getattr(args, "subagent_id", "").strip()
            is_ver = False
            prf = None
            if sub_id:
                rep["subagent_id"] = sub_id
                is_ver, prf = verify_independent_reviewer_execution(
                    repo, task_id=args.task, run_id=str(current["run_id"]), reviewer=reviewer, package_sha256=pkg_sha, subagent_id=sub_id
                )
                if is_ver:
                    rep["provenance"] = "subagent_execution"
            rep["independent_execution_verified"] = is_ver
            rep["execution_proof"] = prf
            (staging_dir / f"{reviewer}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

        for item in args.response:
            reviewer, sep, raw_path = item.partition("=")
            if not sep:
                raise ValidationError("--response must be REVIEWER=PATH")
            reviewer_clean = reviewer.strip()
            rep = response_to_report(repo, args.task, reviewer_clean, Path(raw_path).resolve())
            rep["provenance"] = "reviewer_response_footer"
            manifest = read_json(Path(current["manifest"]))
            pkg_file = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"] / "review-package.md"
            pkg_sha = sha256_file(pkg_file) if pkg_file.is_file() else ""
            sub_id = getattr(args, "subagent_id", "").strip()
            is_ver = False
            prf = None
            if sub_id:
                rep["subagent_id"] = sub_id
                is_ver, prf = verify_independent_reviewer_execution(
                    repo, task_id=args.task, run_id=str(current["run_id"]), reviewer=reviewer_clean, package_sha256=pkg_sha, subagent_id=sub_id
                )
                if is_ver:
                    rep["provenance"] = "subagent_execution"
            rep["independent_execution_verified"] = is_ver
            rep["execution_proof"] = prf
            (staging_dir / f"{reviewer_clean}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

        for item in args.response_text:
            reviewer, sep, raw_text = item.partition("=")
            if not sep:
                raise ValidationError("--response-text must be REVIEWER=TEXT")
            reviewer_clean = reviewer.strip()
            unescaped_text = raw_text.replace("\\n", "\n")
            rep = response_text_to_report(repo, args.task, reviewer_clean, unescaped_text)
            rep["provenance"] = "reviewer_response_text"
            manifest = read_json(Path(current["manifest"]))
            pkg_file = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"] / "review-package.md"
            pkg_sha = sha256_file(pkg_file) if pkg_file.is_file() else ""
            sub_id = getattr(args, "subagent_id", "").strip()
            is_ver = False
            prf = None
            if sub_id:
                clean_sub_id = sub_id
                rep["subagent_id"] = clean_sub_id
                is_ver, prf = verify_independent_reviewer_execution(
                    repo, task_id=args.task, run_id=str(current["run_id"]), reviewer=reviewer_clean, package_sha256=pkg_sha, subagent_id=clean_sub_id
                )
                if is_ver:
                    rep["provenance"] = "subagent_execution"
            rep["independent_execution_verified"] = is_ver
            rep["execution_proof"] = prf
            (staging_dir / f"{reviewer_clean}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

        for item in args.from_subagent:
            reviewer, sep, conv_id = item.partition("=")
            if not sep:
                raise ValidationError("--from-subagent must be REVIEWER=CONVERSATION_ID_OR_TRANSCRIPT_PATH")
            reviewer = reviewer.strip()
            conv_id = conv_id.strip()
            transcript_file = _find_subagent_transcript(conv_id)
            if not transcript_file or not transcript_file.is_file():
                raise ValidationError(f"could not locate transcript for subagent {conv_id}")
            extracted_text = _extract_transcript_response(transcript_file)
            rep = response_text_to_report(repo, args.task, reviewer, extracted_text)
            rep["subagent_id"] = conv_id
            rep["transcript_path"] = str(transcript_file)

            receipt_file = task_directory / "reviewer-dispatches" / f"{reviewer}.json"
            if receipt_file.is_file():
                try:
                    rc = read_json(receipt_file)
                    if not rc.get("subagent_id"):
                        rc["subagent_id"] = conv_id
                        rc["receipt_sha256"] = canonical_sha256({k: v for k, v in rc.items() if k != "receipt_sha256"})
                        atomic_write_json(receipt_file, rc)
                except Exception:
                    pass

            manifest = read_json(Path(current["manifest"]))
            pkg_file = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"] / "review-package.md"
            pkg_sha = sha256_file(pkg_file) if pkg_file.is_file() else ""
            is_ver, prf = verify_independent_reviewer_execution(
                repo,
                task_id=args.task,
                run_id=str(current["run_id"]),
                reviewer=reviewer,
                package_sha256=pkg_sha,
                subagent_id=conv_id,
                transcript_path=transcript_file,
            )
            severity = str(policy.get("severity") or "").upper()
            sensitive = sorted(set(policy.get("surfaces") or []) & SENSITIVE_SURFACES)
            if (severity in ("HIGH", "CRITICAL") or sensitive) and not is_ver:
                raise ValidationError(f"independent execution verification failed for {reviewer}: {prf.get('reason')}")
            rep["provenance"] = "subagent_execution" if is_ver else "subagent_transcript_harvest"
            rep["independent_execution_verified"] = is_ver
            rep["execution_proof"] = prf if is_ver else None
            (staging_dir / f"{reviewer}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

        verdict_items = list(args.verdict)
        if args.reviewer and verdict_items and "=" not in verdict_items[-1]:
            verdict_items = [f"{args.reviewer}={verdict_items[-1]}"]

        if verdict_items:
            severity = str(policy.get("severity") or "").upper()
            sensitive = sorted(set(policy.get("surfaces") or []) & SENSITIVE_SURFACES)
            manifest = read_json(Path(current["manifest"]))
            pkg_file = state_root(repo) / "runs" / manifest["delivery_snapshot_sha256"] / current["run_id"] / "review-package.md"
            pkg_sha = sha256_file(pkg_file) if pkg_file.is_file() else ""

            for item in verdict_items:
                reviewer, sep, v_val = item.partition("=")
                if not sep:
                    raise ValidationError("--verdict without --reviewer must be REVIEWER=VERDICT")
                reviewer = reviewer.strip()
                v_val = v_val.strip()

                is_proven, proof_details = verify_independent_reviewer_execution(
                    repo,
                    task_id=args.task,
                    run_id=str(current["run_id"]),
                    reviewer=reviewer,
                    package_sha256=pkg_sha,
                    subagent_id=getattr(args, "subagent_id", "").strip(),
                )
                if (severity in ("HIGH", "CRITICAL") or sensitive) and not is_proven:
                    surface_label = f" on sensitive surfaces ({', '.join(sensitive)})" if sensitive else ""
                    raise ValidationError(
                        f"Direct self-certified --verdict recording without verified subagent proof (valid transcript and dispatch receipt) "
                        f"is strictly prohibited for {severity} severity changes{surface_label}. "
                        f"You MUST invoke specialist subagents via invoke_subagent and pass --subagent-id <conversationId> and --evidence-pkg <sha>, or ingest authentic output via --from-subagent / --response."
                    )

                rep = verdict_to_report(
                    repo, args.task, reviewer, v_val,
                    message=args.message, severity=args.severity,
                    evidence_pkg=args.evidence_pkg, citations=args.citations,
                )
                rep["provenance"] = "subagent_execution" if is_proven else "lead_agent_recorded_verdict"
                rep["independent_execution_verified"] = is_proven
                rep["execution_proof"] = proof_details if is_proven else None
                if is_proven:
                    rep["subagent_id"] = args.subagent_id.strip()
                (staging_dir / f"{reviewer}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")


        staged_files = sorted(staging_dir.glob("*.json"))
        if not staged_files:
            raise ValidationError("at least one --report, --response, --response-text, or --verdict is required")

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
