"""Deterministic review execution orchestrator, ledger, and result verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import (  # noqa: E402
    ValidationError,
    active_review_package_path,
    atomic_write_json,
    canonical_sha256,
    read_json,
    sha256_file,
    utc_now,
)
from evidence_store import EvidenceStore, StateLock  # noqa: E402
from record_review import (  # noqa: E402
    _extract_transcript_response,
    is_blocking_finding,
    resolve_trusted_subagent_transcript,
)
from review_sources import resolve_trusted_review_source  # noqa: E402
from workflow import state_root, task_dir  # noqa: E402

REVIEW_NOT_DISPATCHED = "NOT_DISPATCHED"
REVIEW_DISPATCHED = "DISPATCHED"
REVIEW_PROTOCOL_RETRY_REQUIRED = "PROTOCOL_RETRY_REQUIRED"
REVIEW_COMPLETED = "COMPLETED"
REVIEW_INGESTED = "INGESTED"
REVIEW_FAILED_PROTOCOL = "FAILED_PROTOCOL"
REVIEW_ENV_BLOCKED = "ENV_BLOCKED"

ALL_REVIEW_STATES = frozenset({
    REVIEW_NOT_DISPATCHED,
    REVIEW_DISPATCHED,
    REVIEW_PROTOCOL_RETRY_REQUIRED,
    REVIEW_COMPLETED,
    REVIEW_INGESTED,
    REVIEW_FAILED_PROTOCOL,
    REVIEW_ENV_BLOCKED,
})

VALID_SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
SEVERITY_NORMALIZE = {
    "BLOCKER": "CRITICAL",
    "MAJOR": "HIGH",
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "INFO": "INFO",
}


def review_execution_dir(task_directory: Path, run_id: str) -> Path:
    return task_directory / "review-execution" / run_id


def ledger_file(task_directory: Path, run_id: str) -> Path:
    return review_execution_dir(task_directory, run_id) / "ledger.json"


def dispatch_receipt_file(task_directory: Path, run_id: str, reviewer: str) -> Path:
    return review_execution_dir(task_directory, run_id) / "dispatch" / f"{reviewer}.json"


def result_file(task_directory: Path, run_id: str, reviewer: str) -> Path:
    return review_execution_dir(task_directory, run_id) / "results" / f"{reviewer}.json"


def compute_ledger_sha(ledger: dict[str, Any]) -> str:
    return canonical_sha256({k: v for k, v in ledger.items() if k != "ledger_sha256"})


def load_ledger(task_directory: Path, run_id: str) -> dict[str, Any]:
    l_path = ledger_file(task_directory, run_id)
    if not l_path.is_file():
        raise ValidationError(f"review ledger not found at {l_path}")
    ledger = read_json(l_path)
    if not isinstance(ledger, dict):
        raise ValidationError(f"corrupt review ledger at {l_path}")
    expected_sha = ledger.get("ledger_sha256")
    actual_sha = compute_ledger_sha(ledger)
    if expected_sha and expected_sha != actual_sha:
        raise ValidationError(f"review ledger sha mismatch: {expected_sha} != {actual_sha}")
    return ledger


def save_ledger(task_directory: Path, run_id: str, ledger: dict[str, Any]) -> None:
    l_path = ledger_file(task_directory, run_id)
    l_path.parent.mkdir(parents=True, exist_ok=True)
    ledger["ledger_sha256"] = compute_ledger_sha(ledger)
    atomic_write_json(l_path, ledger)


def dispatchable_reviewers(ledger: dict[str, Any], required_reviewers: list[str]) -> list[str]:
    rev_map = ledger.get("reviewers", {})
    return [
        r for r in sorted(required_reviewers)
        if rev_map.get(r, {}).get("state") in (REVIEW_NOT_DISPATCHED, None)
    ]


def init_ledger(
    task_directory: Path,
    task_id: str,
    run_id: str,
    delivery_snapshot_sha256: str,
    change_set_sha256: str,
    review_package_sha256: str,
    required_reviewers: list[str],
) -> dict[str, Any]:
    l_path = ledger_file(task_directory, run_id)
    if l_path.is_file():
        existing = load_ledger(task_directory, run_id)
        if (
            existing.get("schema_version") != 1
            or existing.get("task_id") != task_id
            or existing.get("run_id") != run_id
            or existing.get("delivery_snapshot_sha256") != delivery_snapshot_sha256
            or existing.get("change_set_sha256") != change_set_sha256
            or existing.get("review_package_sha256") != review_package_sha256
            or sorted(existing.get("required_reviewers") or []) != sorted(required_reviewers)
        ):
            raise ValidationError(f"existing review ledger at {l_path} does not match active task, run, or snapshot identity")
        return existing
    reviewers_dict: dict[str, Any] = {}
    for rev in required_reviewers:
        reviewers_dict[rev] = {
            "state": REVIEW_NOT_DISPATCHED,
            "dispatch_nonce": None,
            "execution_id": None,
            "dispatch_count": 0,
            "protocol_attempts": 0,
            "dispatched_at": None,
            "completed_at": None,
            "result_sha256": None,
            "last_error": None,
        }
    ledger = {
        "schema_version": 1,
        "task_id": task_id,
        "run_id": run_id,
        "delivery_snapshot_sha256": delivery_snapshot_sha256,
        "change_set_sha256": change_set_sha256,
        "review_package_sha256": review_package_sha256,
        "required_reviewers": sorted(required_reviewers),
        "reviewers": reviewers_dict,
    }
    save_ledger(task_directory, run_id, ledger)
    (review_execution_dir(task_directory, run_id) / "dispatch").mkdir(parents=True, exist_ok=True)
    (review_execution_dir(task_directory, run_id) / "results").mkdir(parents=True, exist_ok=True)
    return ledger



def record_dispatch_batch(
    repo: Path,
    task_id: str,
    reviewers: list[str],
    host: str = "antigravity",
) -> dict[str, dict]:
    directory = task_dir(repo, task_id)
    current_path = directory / "current-run.json"
    if not current_path.is_file():
        raise ValidationError(f"active current-run is missing for task '{task_id}'")
    current = read_json(current_path)
    run_id = str(current.get("run_id") or "").strip()
    if not run_id:
        raise ValidationError("run_id is missing from current-run")

    protocol = int(current.get("review_protocol_version") or 1)
    if protocol < 2:
        raise ValidationError(f"record_dispatch_batch requires review_protocol_version >= 2, found {protocol}")

    run_host = str(current.get("review_host") or "").strip().lower()
    if not run_host:
        raise ValidationError("review_host is missing from V2 current-run")

    requested_host = str(host or "").strip().lower()
    if requested_host != run_host:
        raise ValidationError(
            f"review dispatch host mismatch: run host is '{run_host}', got '{requested_host}'"
        )

    manifest_path = Path(str(current.get("manifest") or ""))
    if not manifest_path.is_file():
        raise ValidationError("active run manifest is missing")
    manifest = read_json(manifest_path)
    snapshot = str(manifest.get("delivery_snapshot_sha256") or "").strip()
    change_set = str(manifest.get("change_set_sha256") or manifest.get("delivery_snapshot_sha256") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot):
        raise ValidationError("delivery snapshot identity is missing or invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", change_set):
        raise ValidationError("change set identity is missing or invalid")

    pkg_path = active_review_package_path(repo, current)
    if not pkg_path.is_file():
        raise ValidationError("review package is missing")
    pkg_sha = sha256_file(pkg_path)
    if not re.fullmatch(r"[0-9a-f]{64}", pkg_sha):
        raise ValidationError("review package digest is invalid")

    policy_path = Path(str(current.get("policy") or ""))
    if not policy_path.is_file():
        raise ValidationError("policy artifact is missing")
    policy = read_json(policy_path)
    required_reviewers = list(policy.get("reviewers") or [])

    for r in reviewers:
        if r not in required_reviewers:
            raise ValidationError(f"reviewer '{r}' is not in policy required reviewers: {required_reviewers}")

    with StateLock(state_root(repo)):
        ledger = init_ledger(
            directory,
            task_id,
            run_id,
            snapshot,
            change_set,
            pkg_sha,
            required_reviewers,
        )

        dispatchable = set(dispatchable_reviewers(ledger, required_reviewers))
        requested = set(reviewers)
        if len(reviewers) != len(requested):
            raise ValidationError(f"duplicate reviewers in dispatch batch: {reviewers}")
        if requested != dispatchable:
            raise ValidationError(
                f"dispatch batch must exactly match dispatchable reviewers {sorted(dispatchable)}, got {sorted(requested)}"
            )

        for r in reviewers:
            rev_entry = ledger.get("reviewers", {}).get(r)
            if not rev_entry:
                raise ValidationError(f"reviewer '{r}' not in ledger")
            st = rev_entry.get("state")
            if st in (REVIEW_COMPLETED, REVIEW_INGESTED):
                raise ValidationError(f"cannot dispatch reviewer '{r}': state is already {st}")
            if st in (REVIEW_FAILED_PROTOCOL, REVIEW_ENV_BLOCKED):
                raise ValidationError(f"cannot silently dispatch reviewer '{r}': state is {st}")
            if st not in (REVIEW_NOT_DISPATCHED, REVIEW_DISPATCHED):
                raise ValidationError(f"cannot dispatch reviewer '{r}': state is {st}")

        receipts: dict[str, dict] = {}
        for r in reviewers:
            rev_entry = ledger["reviewers"][r]
            st = rev_entry.get("state")
            r_file = dispatch_receipt_file(directory, run_id, r)

            if st == REVIEW_DISPATCHED and r_file.is_file():
                existing_r = read_json(r_file)
                if (
                    existing_r.get("task_id") != task_id
                    or existing_r.get("run_id") != run_id
                    or existing_r.get("reviewer") != r
                    or str(existing_r.get("host") or "").strip().lower() != run_host
                    or existing_r.get("review_package_sha256") != pkg_sha
                    or existing_r.get("delivery_snapshot_sha256") != snapshot
                    or existing_r.get("change_set_sha256") != change_set
                ):
                    raise ValidationError(f"existing dispatch receipt for '{r}' does not match active task, run, or snapshot identity")
                expected_sha = canonical_sha256({k: v for k, v in existing_r.items() if k != "receipt_sha256"})
                if existing_r.get("receipt_sha256") != expected_sha:
                    raise ValidationError(f"existing dispatch receipt checksum mismatch for '{r}'")
                receipts[r] = existing_r
                continue


            dispatch_nonce = str(uuid.uuid4())
            receipt = {
                "schema_version": 2,
                "task_id": task_id,
                "run_id": run_id,
                "reviewer": r,
                "delivery_snapshot_sha256": snapshot,
                "change_set_sha256": change_set,
                "review_package_sha256": pkg_sha,
                "dispatch_nonce": dispatch_nonce,
                "host": run_host,
                "dispatched_at": utc_now(),
            }
            receipt["receipt_sha256"] = canonical_sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"})

            r_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(r_file, receipt)

            rev_entry["state"] = REVIEW_DISPATCHED
            rev_entry["dispatch_nonce"] = dispatch_nonce
            rev_entry["dispatch_count"] = int(rev_entry.get("dispatch_count", 0)) + 1
            rev_entry["dispatched_at"] = receipt["dispatched_at"]
            receipts[r] = receipt

        save_ledger(directory, run_id, ledger)
        return receipts


def record_dispatch(
    repo: Path,
    task_id: str,
    reviewer: str,
    host: str = "antigravity",
) -> dict[str, Any]:
    batch = record_dispatch_batch(repo, task_id, [reviewer], host=host)
    return batch[reviewer]


def _parse_nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"field '{field_name}' must be an integer, got bool")
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        if value < 0:
            raise ValidationError(f"field '{field_name}' cannot be negative, got {value}")
        return value
    if isinstance(value, str):
        val_s = value.strip()
        if not val_s.isdigit():
            raise ValidationError(f"field '{field_name}' must be numeric, got '{value}'")
        num = int(val_s)
        if num < 0:
            raise ValidationError(f"field '{field_name}' cannot be negative, got {num}")
        return num
    raise ValidationError(f"field '{field_name}' must be an integer, got {type(value).__name__}")


def _extract_v2_objects(text: str) -> list[dict[str, Any]]:
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    valid_fenced: list[dict[str, Any]] = []
    for block in reversed(fenced_blocks):
        try:
            cand = json.loads(block.strip())
            if isinstance(cand, dict) and cand.get("schema_version") == 2:
                valid_fenced.append(cand)
        except Exception:
            continue
    if valid_fenced:
        return valid_fenced

    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    idx = 0
    length = len(text)
    while idx < length:
        ch = text[idx]
        if ch == '{':
            try:
                obj, end_idx = decoder.raw_decode(text, idx)
                if isinstance(obj, dict) and obj.get("schema_version") == 2:
                    candidates.append(obj)
                idx = end_idx
                continue
            except Exception:
                pass
        idx += 1
    return candidates


def parse_structured_result(
    *,
    text: str,
    expected_task_id: str,
    expected_run_id: str,
    expected_reviewer: str,
    expected_package_sha256: str,
) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValidationError("reviewer output is empty")

    candidates = _extract_v2_objects(text)
    if not candidates:
        raise ValidationError("no valid HARNESS_REVIEW_RESULT_V2 JSON block found in reviewer output")

    first_sha = canonical_sha256(candidates[0])
    for cand in candidates[1:]:
        if canonical_sha256(cand) != first_sha:
            raise ValidationError("multiple conflicting HARNESS_REVIEW_RESULT_V2 JSON blocks found in reviewer output")

    raw_json_obj = candidates[0]

    if raw_json_obj.get("schema_version") != 2:
        raise ValidationError(f"expected schema_version == 2, got {raw_json_obj.get('schema_version')}")

    tid = str(raw_json_obj.get("task_id") or "")
    if tid != expected_task_id:
        raise ValidationError(f"task_id mismatch: expected '{expected_task_id}', got '{tid}'")

    rid = str(raw_json_obj.get("run_id") or "")
    if rid != expected_run_id:
        raise ValidationError(f"run_id mismatch: expected '{expected_run_id}', got '{rid}'")

    rev = str(raw_json_obj.get("reviewer") or "")
    if rev != expected_reviewer:
        raise ValidationError(f"reviewer mismatch: expected '{expected_reviewer}', got '{rev}'")

    pkg_sha = str(raw_json_obj.get("review_package_sha256") or "")
    if len(pkg_sha) != 64 or pkg_sha.lower() != expected_package_sha256.lower():
        raise ValidationError(f"review_package_sha256 mismatch: expected full 64-char '{expected_package_sha256}', got '{pkg_sha}'")

    verdict = str(raw_json_obj.get("verdict") or "").upper()
    if verdict not in ("PASS", "FINDINGS"):
        raise ValidationError(f"verdict must be PASS or FINDINGS, got '{verdict}'")

    raw_findings = raw_json_obj.get("findings")
    if not isinstance(raw_findings, list):
        raise ValidationError("findings must be a list")

    if verdict == "PASS" and raw_findings:
        raise ValidationError("verdict is PASS but findings list is not empty")

    if verdict == "FINDINGS" and not raw_findings:
        raise ValidationError("verdict is FINDINGS but findings list is empty")

    normalized_findings = []
    for f in raw_findings:
        if not isinstance(f, dict):
            raise ValidationError(f"each finding must be a JSON object, got {type(f)}")
        msg = str(f.get("message") or "").strip()
        if not msg:
            raise ValidationError("finding message cannot be empty")
        raw_sev = str(f.get("severity") or "").upper().strip()
        normalized_sev = SEVERITY_NORMALIZE.get(raw_sev)
        if not normalized_sev or normalized_sev not in VALID_SEVERITIES:
            raise ValidationError(f"invalid finding severity: '{raw_sev}'")

        l_start = _parse_nonnegative_int(f.get("line_start"), "line_start")
        l_end = _parse_nonnegative_int(f.get("line_end"), "line_end")
        if l_start > 0 and l_end > 0 and l_end < l_start:
            raise ValidationError(f"line_end ({l_end}) cannot be lower than line_start ({l_start})")

        finding_id = str(f.get("id") or "").strip()
        title = str(f.get("title") or "").strip()
        normalized_findings.append({
            "id": finding_id or f"{expected_reviewer}-{len(normalized_findings)+1:03d}",
            "severity": normalized_sev,
            "title": title or msg[:50],
            "message": msg,
            "file": str(f.get("file") or ""),
            "line_start": l_start,
            "line_end": l_end,
            "evidence": str(f.get("evidence") or ""),
            "recommended_fix": str(f.get("recommended_fix") or ""),
        })

    return {
        "schema_version": 2,
        "task_id": expected_task_id,
        "run_id": expected_run_id,
        "reviewer": expected_reviewer,
        "review_package_sha256": expected_package_sha256,
        "verdict": verdict,
        "findings": normalized_findings,
    }


def complete_review(

    repo: Path,
    task_id: str,
    reviewer: str,
    execution_id: str,
    host: str | None = None,
) -> dict[str, Any]:
    directory = task_dir(repo, task_id)
    current = read_json(directory / "current-run.json")
    run_id = str(current["run_id"])
    manifest = read_json(Path(current["manifest"]))
    pkg_path = active_review_package_path(repo, current)
    pkg_sha = sha256_file(pkg_path) if pkg_path.is_file() else ""
    policy = read_json(Path(current["policy"]))
    required_reviewers = list(policy.get("reviewers") or [])
    review_protocol_version = int(current.get("review_protocol_version") or 1)

    run_host = str(current.get("review_host") or "").strip().lower()
    if review_protocol_version >= 2:
        if not run_host:
            raise ValidationError("review_host is missing from V2 current-run")
        if host is not None and str(host).strip().lower() != run_host:
            raise ValidationError(f"host cannot change mid-run: run host is '{run_host}', got '{host}'")
        host = run_host
    elif not host:
        host = run_host or "generic"

    if reviewer not in required_reviewers:
        raise ValidationError(f"reviewer '{reviewer}' is not in policy required reviewers: {required_reviewers}")

    with StateLock(state_root(repo)):
        ledger = init_ledger(
            directory,
            task_id,
            run_id,
            manifest["delivery_snapshot_sha256"],
            manifest["change_set_sha256"],
            pkg_sha,
            required_reviewers,
        )

        r_file = dispatch_receipt_file(directory, run_id, reviewer)
        if not r_file.is_file():
            if review_protocol_version >= 2:
                ledger["reviewers"][reviewer]["state"] = REVIEW_FAILED_PROTOCOL
                ledger["reviewers"][reviewer]["last_error"] = "missing preexisting dispatch receipt"
                save_ledger(directory, run_id, ledger)
                raise ValidationError(f"missing preexisting dispatch receipt for reviewer '{reviewer}' in run '{run_id}'")

        # Validate dispatch receipt if present
        if r_file.is_file():
            r_data = read_json(r_file)
            if r_data.get("task_id") != task_id or r_data.get("run_id") != run_id or r_data.get("reviewer") != reviewer:
                raise ValidationError("dispatch receipt does not match active task, run, or reviewer")
            if r_data.get("review_package_sha256") != pkg_sha:
                raise ValidationError("dispatch receipt does not match active review package")
            if review_protocol_version >= 2:
                if str(r_data.get("host") or "").strip().lower() != run_host:
                    raise ValidationError(
                        "dispatch receipt host does not match active review host"
                    )

        # Idempotency check
        res_file = result_file(directory, run_id, reviewer)
        if res_file.is_file():
            existing_result = read_json(res_file)
            existing_exec = existing_result.get("execution_id")
            if existing_exec == execution_id:
                t_path = resolve_trusted_review_source(run_host, execution_id)
                if t_path and t_path.is_file():
                    new_text = _extract_transcript_response(t_path)
                    new_parsed = parse_structured_result(
                        text=new_text,
                        expected_task_id=task_id,
                        expected_run_id=run_id,
                        expected_reviewer=reviewer,
                        expected_package_sha256=pkg_sha,
                    )
                    if canonical_sha256(new_parsed) != canonical_sha256(existing_result.get("result", {})):
                        raise ValidationError("different result for same completed execution is rejected")
                return existing_result.get("result", {})

        existing_bound_id = ledger["reviewers"][reviewer].get("execution_id")
        if existing_bound_id and existing_bound_id != execution_id:
            raise ValidationError(f"reviewer '{reviewer}' already bound to execution '{existing_bound_id}', rejecting different execution '{execution_id}'")

        current_st = ledger["reviewers"][reviewer].get("state")
        if current_st not in (REVIEW_DISPATCHED, REVIEW_PROTOCOL_RETRY_REQUIRED):
            raise ValidationError(f"cannot complete review for '{reviewer}': state is '{current_st}', expected DISPATCHED or PROTOCOL_RETRY_REQUIRED")

        ledger["reviewers"][reviewer]["execution_id"] = execution_id
        ledger["reviewers"][reviewer]["execution_id_sha256"] = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()
        save_ledger(directory, run_id, ledger)

        # Resolve transcript text and extract response
        try:
            t_path = resolve_trusted_review_source(run_host, execution_id)
            if not t_path or not t_path.is_file():
                raise FileNotFoundError("trusted transcript not found")
            text = _extract_transcript_response(t_path)
            if not text or not text.strip():
                raise ValueError("no model response in transcript")
        except Exception as exc:
            ledger["reviewers"][reviewer]["state"] = REVIEW_ENV_BLOCKED
            if isinstance(exc, FileNotFoundError):
                err_code = "TRUSTED_TRANSCRIPT_NOT_FOUND"
            elif "no model response" in str(exc).lower():
                err_code = "TRUSTED_TRANSCRIPT_NO_MODEL_RESPONSE"
            else:
                err_code = "TRUSTED_TRANSCRIPT_UNREADABLE"
            ledger["reviewers"][reviewer]["last_error"] = err_code
            save_ledger(directory, run_id, ledger)
            raise ValidationError(f"could not extract trusted transcript for subagent '{execution_id}': {err_code}")


        # Parse structured result
        try:
            parsed = parse_structured_result(
                text=text,
                expected_task_id=task_id,
                expected_run_id=run_id,
                expected_reviewer=reviewer,
                expected_package_sha256=pkg_sha,
            )
        except ValidationError as exc:
            attempts = int(ledger["reviewers"][reviewer].get("protocol_attempts") or 0) + 1
            ledger["reviewers"][reviewer]["protocol_attempts"] = attempts
            if attempts <= 1:
                ledger["reviewers"][reviewer]["state"] = REVIEW_PROTOCOL_RETRY_REQUIRED
                ledger["reviewers"][reviewer]["last_error"] = str(exc)
            else:
                ledger["reviewers"][reviewer]["state"] = REVIEW_FAILED_PROTOCOL
                ledger["reviewers"][reviewer]["last_error"] = str(exc)
            save_ledger(directory, run_id, ledger)
            raise

        # Save result JSON
        result_sha = canonical_sha256(parsed)
        res_payload = {
            "schema_version": 2,
            "task_id": task_id,
            "run_id": run_id,
            "reviewer": reviewer,
            "execution_id": execution_id,
            "execution_id_sha256": hashlib.sha256(execution_id.encode("utf-8")).hexdigest(),
            "completed_at": utc_now(),
            "result": parsed,
            "result_sha256": result_sha,
        }
        res_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(res_file, res_payload)

        # Update ledger
        rev_entry = ledger["reviewers"][reviewer]
        rev_entry["state"] = REVIEW_COMPLETED
        rev_entry["execution_id"] = execution_id
        rev_entry["completed_at"] = res_payload["completed_at"]
        rev_entry["result_sha256"] = result_sha
        rev_entry["last_error"] = None
        save_ledger(directory, run_id, ledger)

        all_completed = all(
            ledger["reviewers"][r].get("state") in (REVIEW_COMPLETED, REVIEW_INGESTED)
            for r in required_reviewers
        )

    if all_completed:
        finalize_review_execution(repo, task_id, run_id)

    return parsed


def _finalize_review_execution_locked(
    repo: Path,
    task_id: str,
    run_id: str | None = None,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    directory = task_dir(repo, task_id)
    current = read_json(directory / "current-run.json")
    if not run_id:
        run_id = str(current["run_id"])
    manifest = read_json(Path(current["manifest"]))
    policy = read_json(Path(current["policy"]))
    plan = read_json(directory / "plan.json")
    pkg_path = active_review_package_path(repo, current)
    pkg_sha = sha256_file(pkg_path) if pkg_path.is_file() else ""
    required_reviewers = list(policy.get("reviewers") or [])

    if ledger is None:
        ledger = load_ledger(directory, run_id)

    store = EvidenceStore(state_root(repo))
    all_ingested = bool(required_reviewers) and all(
        ledger.get("reviewers", {}).get(r, {}).get("state") == REVIEW_INGESTED
        for r in required_reviewers
    )
    if all_ingested:
        try:
            existing_rec = store.read(manifest["delivery_snapshot_sha256"], run_id, "reviews")
            return existing_rec.get("evidence", {})
        except ValidationError:
            pass

    for r in required_reviewers:
        st = ledger.get("reviewers", {}).get(r, {}).get("state")
        if st not in (REVIEW_COMPLETED, REVIEW_INGESTED):
            raise ValidationError(f"cannot finalize reviews; reviewer '{r}' is in state '{st}', not COMPLETED")

    reports = []
    all_findings = []
    for r in required_reviewers:
        res_p = result_file(directory, run_id, r)
        if not res_p.is_file():
            raise ValidationError(f"result file missing for reviewer '{r}'")
        res_data = read_json(res_p)
        if res_data.get("task_id") != task_id or res_data.get("run_id") != run_id or res_data.get("reviewer") != r:
            raise ValidationError(f"result file for '{r}' identity mismatch")
        result_body = res_data.get("result", {})
        actual_res_sha = canonical_sha256(result_body)
        if res_data.get("result_sha256") != actual_res_sha:
            raise ValidationError(f"result file for '{r}' sha mismatch")
        expected_exec_sha = hashlib.sha256(str(res_data.get("execution_id") or "").encode("utf-8")).hexdigest()
        if res_data.get("execution_id_sha256") != expected_exec_sha:
            raise ValidationError(f"result file for '{r}' execution id hash mismatch")
        if str(result_body.get("review_package_sha256") or "").lower() != pkg_sha.lower():
            raise ValidationError(f"result file for '{r}' review package digest mismatch")

        verdict = result_body.get("verdict", "PASS")
        r_findings = result_body.get("findings", [])
        reports.append({
            "reviewer": r,
            "verdict": verdict,
            "result_sha256": res_data.get("result_sha256", ""),
            "execution_id_sha256": res_data.get("execution_id_sha256", ""),
            "independent_execution_verified": True,
        })
        for item in r_findings:
            all_findings.append({"reviewer": r, **item})

    blocking = [f for f in all_findings if is_blocking_finding(f, policy)]
    status = "FAIL" if blocking else "PASS"

    round_number = int(policy.get("review_round") or (((plan or {}).get("review_rounds") or 0) + 1))
    evidence_payload = {
        "review_protocol_version": 2,
        "package_sha256": pkg_sha,
        "reviewers": sorted(required_reviewers),
        "verdict": status,
        "reports": reports,
        "findings": all_findings,
        "blocking_findings": blocking,
        "is_truncated": False,
        "round": round_number,
    }

    version_file = (repo / ".agents" / "VERSION") if (repo / ".agents").is_dir() else (repo / "agents" / "VERSION")
    harness_ver = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "1.0.0"

    store.write(
        snapshot=manifest["delivery_snapshot_sha256"],
        run_id=run_id,
        name="reviews",
        producer="review_orchestrator",
        harness_version=harness_ver,
        change_set=manifest["change_set_sha256"],
        status=status,
        evidence=evidence_payload,
        lock=False,
    )

    for r in required_reviewers:
        ledger["reviewers"][r]["state"] = REVIEW_INGESTED
    save_ledger(directory, run_id, ledger)

    if plan is not None:
        prev_rounds = int(plan.get("review_rounds") or 0)
        prev_calls = int(plan.get("review_calls_used") or 0)
        plan["review_rounds"] = round_number
        plan["review_calls_used"] = prev_calls + len(required_reviewers)
        if blocking:
            plan["status"] = "BLOCKED"
            plan["blocked_reviewers"] = sorted({str(item.get("reviewer") or "") for item in blocking})
        from plan_authority import save_plan
        save_plan(directory / "plan.json", plan)


    return evidence_payload


def finalize_review_execution(
    repo: Path,
    task_id: str,
    run_id: str | None = None,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with StateLock(state_root(repo)):
        return _finalize_review_execution_locked(repo, task_id, run_id, ledger)


finalize_reviews = finalize_review_execution


def get_review_execution_status(repo: Path, task_id: str) -> dict[str, Any]:
    directory = task_dir(repo, task_id)
    current = read_json(directory / "current-run.json")
    run_id = str(current["run_id"])
    policy = read_json(Path(current["policy"]))
    required_reviewers = list(policy.get("reviewers") or [])
    l_file = ledger_file(directory, run_id)
    if not l_file.is_file():
        return {
            "task_id": task_id,
            "run_id": run_id,
            "required_reviewers": required_reviewers,
            "ledger_initialized": False,
            "reviewers": {r: {"state": REVIEW_NOT_DISPATCHED} for r in required_reviewers},
        }
    ledger = load_ledger(directory, run_id)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "required_reviewers": required_reviewers,
        "ledger_initialized": True,
        "reviewers": ledger.get("reviewers", {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness review execution orchestrator")
    subparsers = parser.add_subparsers(dest="subcommand")

    complete_p = subparsers.add_parser("complete", help="Record trusted completion of reviewer")
    complete_p.add_argument("--repo", default=".")
    complete_p.add_argument("--task", required=True, help="Task ID")
    complete_p.add_argument("--reviewer", required=True, help="Reviewer role")
    complete_p.add_argument("--execution-id", required=True, help="Trusted execution transcript ID")
    complete_p.add_argument("--host", default=None, help="Host environment")

    finalize_p = subparsers.add_parser("finalize", help="Aggregate review evidence")
    finalize_p.add_argument("--repo", default=".")
    finalize_p.add_argument("--task", required=True, help="Task ID")

    dispatch_p = subparsers.add_parser("dispatch", help="Record dispatch receipt")
    dispatch_p.add_argument("--repo", default=".")
    dispatch_p.add_argument("--task", required=True, help="Task ID")
    dispatch_p.add_argument("--reviewer", required=True, help="Reviewer role")
    dispatch_p.add_argument("--host", default="antigravity", help="Host environment")

    status_p = subparsers.add_parser("status", help="Review execution status")
    status_p.add_argument("--repo", default=".")
    status_p.add_argument("--task", required=True, help="Task ID")

    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help(sys.stderr)
        return 1

    repo = Path(args.repo).resolve()
    try:
        if args.subcommand == "complete":
            res = complete_review(
                repo,
                args.task,
                args.reviewer,
                args.execution_id,
                host=args.host,
            )
            print(f"REVIEW_COMPLETED: {args.reviewer} verdict={res.get('verdict')}")
            return 0
        elif args.subcommand == "finalize":
            res = finalize_review_execution(repo, args.task)
            print(f"REVIEW_FINALIZED: {len(res.get('reports', []))} reports, {len(res.get('blocking_findings', []))} blocking findings")
            return 0
        elif args.subcommand == "dispatch":
            receipt = record_dispatch(repo, args.task, args.reviewer, host=args.host)
            print(f"REVIEW_DISPATCHED: {args.reviewer} receipt={receipt.get('receipt_sha256')[:12]}")
            return 0
        elif args.subcommand == "status":
            st = get_review_execution_status(repo, args.task)
            print(json.dumps(st, indent=2))
            return 0
    except (ValidationError, OSError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
