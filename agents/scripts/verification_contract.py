"""Optional approved acceptance criteria; evidence associations are not semantic proof."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _vnext_common import ValidationError, bounded_path, canonical_sha256, read_json, validate_id
from evidence_store import EvidenceStore

MAX_CONTRACT_BYTES = 262144
MAX_CRITERIA = 32
MAX_JOURNEYS = 8
METHODS = {"test", "manual", "journey", "review"}


def validate_criterion_results(value):
    if not isinstance(value, dict) or len(value) > MAX_CRITERIA:
        raise ValidationError("criterion_results must be a bounded mapping")
    for key, verdict in value.items():
        if validate_id(key) != key or not isinstance(verdict, str) or verdict not in {"PASS", "FAIL", "NEEDS_CONTEXT"}:
            raise ValidationError("invalid criterion-specific reviewer result")
    return value


def strict_keys(value: dict, allowed: set[str], required: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise ValidationError(f"invalid {label} fields")


def text(value, label: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValidationError(f"invalid {label}")
    return value


def load_definition(repo: Path, relative: str) -> dict:
    path = bounded_path(repo, relative)
    if path.is_symlink() or not path.is_file() or path.suffix != ".json" or path.stat().st_size > MAX_CONTRACT_BYTES:
        raise ValidationError("definition must be a bounded regular JSON file")
    return read_json(path)


def validate_contract(value: dict) -> dict:
    strict_keys(value, {"schema_version", "criteria", "journeys", "device_validation"}, {"schema_version", "criteria", "journeys"}, "verification contract")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationError("unsupported verification contract schema")
    if len(json.dumps(value).encode()) > MAX_CONTRACT_BYTES:
        raise ValidationError("verification contract is too large")
    criteria, journeys = value["criteria"], value["journeys"]
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= MAX_CRITERIA:
        raise ValidationError("contract requires 1..32 criteria")
    if not isinstance(journeys, list) or len(journeys) > MAX_JOURNEYS:
        raise ValidationError("too many journeys")
    seen = set()
    for item in criteria:
        strict_keys(item, {"id", "expected", "method", "required"}, {"id", "expected", "method", "required"}, "criterion")
        identity = validate_id(text(item["id"], "criterion id", 64))
        if identity in seen or item["id"] != identity:
            raise ValidationError("duplicate or noncanonical criterion id")
        seen.add(identity)
        text(item["expected"], "expected behavior")
        if not isinstance(item["method"], str) or item["method"] not in METHODS or type(item["required"]) is not bool:
            raise ValidationError("invalid criterion method or requirement")
    from journey_runner import validate_journey
    journey_ids = set()
    for item in journeys:
        validate_journey(item)
        if item["id"] in journey_ids or not set(item["criteria"]).issubset(seen):
            raise ValidationError("duplicate journey or unknown criterion")
        journey_ids.add(item["id"])
        for criterion_id in item["criteria"]:
            criterion = next(c for c in criteria if c["id"] == criterion_id)
            if criterion["method"] != "journey":
                raise ValidationError("journey maps to a non-journey criterion")
    for item in criteria:
        if item["method"] == "journey" and not any(item["id"] in j["criteria"] for j in journeys):
            raise ValidationError("journey criterion has no selected journey")
    if "device_validation" in value:
        if value["device_validation"] != "manual_or_automatic" or not journeys:
            raise ValidationError("device validation choice requires complete approved journeys")
        if any(c["required"] and c["method"] == "manual" for c in criteria):
            raise ValidationError("required human judgments cannot be replaced by automatic validation")
        if len({(j["module"], j["variant"], j["application_id"]) for j in journeys}) != 1 \
                or sum(len(j["steps"]) for j in journeys) > 40 \
                or sum(s.get("timeout", 3) for j in journeys for s in j["steps"]) > 120:
            raise ValidationError("complete walkthrough must share one application and a 40-step/120-second budget")
    return value


def allows_validation_choice(plan):
    return (plan.get("verification_contract") or {}).get("device_validation") == "manual_or_automatic"


def manual_journey_source(plan, current, store):
    """A complete developer walkthrough may replace selected replay only in choice mode."""
    if not allows_validation_choice(plan):
        raise ValidationError("manual replay substitution was not approved")
    record = store.read(current["delivery_snapshot_sha256"], current["run_id"], "device_signoff")
    try:
        selection = store.read(current["delivery_snapshot_sha256"], current["run_id"], "device_validation_result")
    except ValidationError as exc:
        if "cannot read JSON artifact" not in str(exc):
            raise
        selection = None
    if selection and not isinstance(selection.get("evidence"), dict):
        raise ValidationError("invalid device validation selection evidence")
    if selection and (selection.get("producer") != "device_validation" or selection.get("status") != record.get("status")
                      or selection.get("change_set_sha256") != current["change_set_sha256"]
                      or (selection.get("evidence") or {}).get("mode") != "manual"
                      or (selection.get("evidence") or {}).get("signoff_sha256") != record.get("artifact_sha256")):
        raise ValidationError("a newer automatic selection superseded manual validation")
    evidence = record.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValidationError("invalid manual walkthrough evidence")
    if record.get("producer") != "developer_approval" or record.get("schema_version") != 1 \
            or record.get("status") != "PASS" or record.get("change_set_sha256") != current["change_set_sha256"] \
            or evidence.get("task_id") != plan["task_id"] or evidence.get("plan_sha256") != plan["plan_sha256"] \
            or evidence.get("approval_source") not in {"conversation", "developer_terminal", "host_native"} \
            or not evidence.get("proof_reference_sha256"):
        raise ValidationError("complete manual walkthrough proof is missing")
    expected = {c for j in plan["verification_contract"]["journeys"] for c in j["criteria"]}
    if not isinstance(evidence.get("criterion_ids"), list) \
            or any(not isinstance(c, str) for c in evidence["criterion_ids"]) \
            or not expected <= set(evidence["criterion_ids"]):
        raise ValidationError("manual walkthrough did not identify all selected journey criteria")
    if current.get("harness_version") and record.get("harness_version") != current["harness_version"]:
        raise ValidationError("manual validation version mismatch")
    return record


def automatic_validation_result(plan, current, store):
    """Validate a developer-selected automatic result without manufacturing human sign-off."""
    if not allows_validation_choice(plan):
        raise ValidationError("automatic device validation was not approved")
    record = store.read(current["delivery_snapshot_sha256"], current["run_id"], "device_validation_result")
    evidence = record.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValidationError("invalid automatic validation evidence")
    if record.get("producer") != "device_validation" or evidence.get("mode") != "automatic" or record.get("schema_version") != 1 \
            or record.get("change_set_sha256") != current["change_set_sha256"] \
            or evidence.get("task_id") != plan["task_id"] or evidence.get("plan_sha256") != plan["plan_sha256"] \
            or evidence.get("contract_sha256") != canonical_sha256(plan["verification_contract"]) \
            or evidence.get("approval_source") not in {"conversation", "developer_terminal", "host_native"} \
            or not evidence.get("proof_reference_sha256"):
        raise ValidationError("invalid automatic device validation identity or developer selection")
    if current.get("harness_version") and record.get("harness_version") != current["harness_version"]:
        raise ValidationError("automatic validation version mismatch")
    if record.get("status") != "PASS":
        return record
    from final_verifier import _validate_artifact
    version = record["harness_version"]
    if not isinstance(evidence.get("prerequisite_sha256"), dict):
        raise ValidationError("invalid automatic validation prerequisite association")
    for name in ("assemble", "device_install", "device_launch"):
        source, error = _validate_artifact(store, current["delivery_snapshot_sha256"], current["change_set_sha256"],
                                           current["run_id"], name, version)
        if error or (evidence.get("prerequisite_sha256") or {}).get(name) != source.get("artifact_sha256"):
            raise ValidationError("automatic validation build/install/launch proof changed")
    sources = evidence.get("journey_sha256") or {}
    if not isinstance(sources, dict):
        raise ValidationError("invalid automatic journey association")
    installed = store.read(current["delivery_snapshot_sha256"], current["run_id"], "device_install")["evidence"]
    journeys = plan["verification_contract"]["journeys"]
    if set(sources) != {j["id"] for j in journeys}:
        raise ValidationError("automatic validation does not cover the complete walkthrough")
    for journey in journeys:
        for identity in journey["criteria"]:
            criterion = next(c for c in plan["verification_contract"]["criteria"] if c["id"] == identity)
            source = _source(plan, current, store, criterion, "journey-" + journey["id"], "")
            if source["artifact_sha256"] != sources[journey["id"]]:
                raise ValidationError("automatic validation journey has a newer attempt")
            proof = source.get("evidence") or {}
            if proof.get("artifact_set_sha256") != installed.get("artifact_set_sha256") \
                    or proof.get("serial_sha256") != installed.get("serial_sha256") \
                    or proof.get("application_id") != installed.get("application_id") \
                    or proof.get("variant") != journey["variant"]:
                raise ValidationError("automatic validation journey device or artifact mismatch")
    return record


def _source(plan, current, store, criterion, artifact, case):
    record = store.read(current["delivery_snapshot_sha256"], current["run_id"], artifact)
    if record.get("schema_version") != 1 or record.get("change_set_sha256") != current["change_set_sha256"]:
        raise ValidationError("evidence schema or change-set mismatch")
    if current.get("harness_version") and record.get("harness_version") != current["harness_version"]:
        raise ValidationError("evidence harness version mismatch")
    if record.get("status") != "PASS":
        raise ValidationError("referenced evidence is not PASS")
    evidence = record.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValidationError("invalid criterion source evidence")
    method = criterion["method"]
    if method == "test":
        if artifact != "unit_tests" or record.get("producer") != "run_tests_gate":
            raise ValidationError("test criterion requires unit-test evidence")
        if not case or not isinstance(evidence.get("test_outcomes"), dict) or evidence["test_outcomes"].get(case) != "PASS":
            raise ValidationError("exact test case did not execute successfully")
    elif method == "manual":
        if artifact != "device_signoff" or record.get("producer") != "developer_approval":
            raise ValidationError("manual criterion requires developer sign-off")
        if evidence.get("task_id") != plan["task_id"] or evidence.get("plan_sha256") != plan["plan_sha256"]:
            raise ValidationError("manual sign-off plan mismatch")
        if evidence.get("approval_source") not in {"conversation", "developer_terminal", "host_native"} \
                or not evidence.get("proof_reference_sha256"):
            raise ValidationError("manual sign-off lacks developer provenance")
        if not isinstance(evidence.get("criterion_ids"), list) or criterion["id"] not in evidence["criterion_ids"]:
            raise ValidationError("developer sign-off did not explicitly identify this criterion")
    elif method == "review":
        if artifact != "reviews" or record.get("producer") != "review_orchestrator":
            raise ValidationError("review criterion requires review evidence")
        reports = evidence.get("reports") or []
        if not isinstance(reports, list) or any(not isinstance(r, dict)
                or not isinstance(r.get("criterion_results", {}), dict) for r in reports):
            raise ValidationError("invalid criterion review reports")
        matched = [r for r in reports if r.get("reviewer") == case and r.get("verdict") == "PASS"
                   and r.get("independent_execution_verified") is True
                   and (r.get("criterion_results") or {}).get(criterion["id"]) == "PASS"]
        if not matched:
            raise ValidationError("no independent criterion-specific reviewer PASS")
        _validate_review_result(plan, current, store, evidence, matched[0], criterion["id"])
    else:
        if artifact == "device_signoff" and allows_validation_choice(plan):
            return manual_journey_source(plan, current, store)
        selected = next((j for j in plan["verification_contract"]["journeys"] if artifact == "journey-" + j["id"]
                         and criterion["id"] in j["criteria"]), None)
        if not selected or record.get("producer") != "journey_runner":
            raise ValidationError("journey was not selected for this criterion")
        if evidence.get("task_id") != plan["task_id"] or evidence.get("plan_sha256") != plan["plan_sha256"] \
                or evidence.get("definition_sha256") != canonical_sha256(selected):
            raise ValidationError("journey definition or plan mismatch")
        steps = evidence.get("steps") or []
        if not isinstance(steps, list) or len(steps) != len(selected["steps"]) \
                or any(not isinstance(s, dict) or s.get("status") != "PASS" for s in steps):
            raise ValidationError("journey does not contain complete passing step evidence")
    return record


def _validate_review_result(plan, current, store, aggregate, report, criterion_id):
    """Link optional results to established V2 ingestion, not a lead assertion."""
    from review_orchestrator import load_ledger, ledger_file, result_file, dispatch_receipt_file
    from _vnext_common import sha256_file, active_review_package_path
    reviewer = validate_id(report["reviewer"])
    directory = store.state_root / "tasks" / validate_id(plan["task_id"])
    if aggregate.get("review_protocol_version") != 2 or current.get("review_protocol_version") != 2:
        raise ValidationError("criterion-specific review requires trusted V2 ingestion")
    paths = [ledger_file(directory, current["run_id"]), result_file(directory, current["run_id"], reviewer),
             dispatch_receipt_file(directory, current["run_id"], reviewer)]
    for path in paths:
        if path.is_symlink() or path.stat().st_size > MAX_CONTRACT_BYTES:
            raise ValidationError("invalid criterion review proof file")
    ledger = load_ledger(directory, current["run_id"])
    entry = (ledger.get("reviewers") or {}).get(reviewer) or {}
    result, receipt = [read_json(path) for path in paths[1:]]
    body = result.get("result") or {}
    digest = canonical_sha256(body)
    if entry.get("state") != "INGESTED" or any(value != digest for value in
            (result.get("result_sha256"), entry.get("result_sha256"), report.get("result_sha256"))):
        raise ValidationError("criterion review result is not bound to trusted ingestion")
    for proof in (result, receipt):
        if any(proof.get(key) != expected for key, expected in
                (("task_id", plan["task_id"]), ("run_id", current["run_id"]), ("reviewer", reviewer))):
            raise ValidationError("criterion review proof identity mismatch")
    if receipt.get("delivery_snapshot_sha256") != current["delivery_snapshot_sha256"] \
            or receipt.get("change_set_sha256") != current["change_set_sha256"]:
        raise ValidationError("criterion review snapshot mismatch")
    package = active_review_package_path(store.state_root.parent.parent, current)
    package_sha = sha256_file(package)
    if any(value != package_sha for value in (aggregate.get("package_sha256"), body.get("review_package_sha256"),
            receipt.get("review_package_sha256"))):
        raise ValidationError("criterion review package mismatch")
    if receipt.get("receipt_sha256") != canonical_sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"}):
        raise ValidationError("criterion review dispatch receipt hash mismatch")
    if entry.get("execution_id_sha256") != result.get("execution_id_sha256") \
            or report.get("execution_id_sha256") != result.get("execution_id_sha256"):
        raise ValidationError("criterion review execution mismatch")
    if body.get("verdict") != "PASS" or (body.get("criterion_results") or {}).get(criterion_id) != "PASS":
        raise ValidationError("ingested reviewer did not pass this criterion")


def bind_evidence(plan, current, store, criterion_id, artifact, case="", *, lock=True):
    value = validate_contract(plan.get("verification_contract") or {})
    criterion = next((c for c in value["criteria"] if c["id"] == criterion_id), None)
    if not criterion:
        raise ValidationError("criterion not in approved contract")
    source = _source(plan, current, store, criterion, artifact, case)
    return store.write(snapshot=current["delivery_snapshot_sha256"], run_id=current["run_id"],
                       name="criterion-" + criterion_id, producer="criterion_binding",
                       harness_version=source["harness_version"], change_set=current["change_set_sha256"], status="PASS",
                       evidence={"task_id": plan["task_id"], "plan_sha256": plan["plan_sha256"],
                                 "contract_sha256": canonical_sha256(value), "source_artifact": artifact,
                                 "source_sha256": source["artifact_sha256"], "case": case}, allow_pass_retry=True, lock=lock)


def coverage_report(plan, current, store):
    report = {"schema_version": 1, "criteria": [], "blocking": [],
              "semantic_relevance": "Evidence associations remain subject to test-quality and completeness review."}
    if "verification_contract" not in plan:
        return report
    value = validate_contract(plan["verification_contract"])
    # One query-local read per artifact. Retain EvidenceStore chain validation;
    # never persist this cache or reuse it after a newer evidence attempt.
    class QueryStore:
        state_root = store.state_root

        def __init__(self):
            self.records = {}

        def read(self, snapshot, run_id, name):
            key = (snapshot, run_id, name)
            if key not in self.records:
                self.records[key] = store.read(snapshot, run_id, name)
            return self.records[key]

    query = QueryStore()
    for criterion in value["criteria"]:
        status, detail = "MISSING", "No current evidence association"
        if current:
            try:
                binding = store.read(current["delivery_snapshot_sha256"], current["run_id"], "criterion-" + criterion["id"])
                evidence = binding.get("evidence") or {}
                if binding.get("producer") != "criterion_binding" or binding.get("schema_version") != 1 \
                        or binding.get("status") != "PASS" or binding.get("change_set_sha256") != current["change_set_sha256"]:
                    raise ValidationError("invalid criterion association")
                if evidence.get("contract_sha256") != canonical_sha256(value) or evidence.get("plan_sha256") != plan["plan_sha256"] \
                        or evidence.get("task_id") != plan["task_id"]:
                    status, detail = "STALE", "Criterion or approved plan changed"
                else:
                    source = _source(plan, current, query, criterion, evidence["source_artifact"], evidence.get("case", ""))
                    if binding.get("harness_version") != source.get("harness_version"):
                        raise ValidationError("criterion association version mismatch")
                    if source["artifact_sha256"] != evidence.get("source_sha256"):
                        status, detail = "STALE", "Source evidence has a newer attempt; reassociate after checking it"
                    else:
                        status, detail = "VERIFIED", "Current evidence association validated"
            except (ValidationError, OSError, KeyError, TypeError) as exc:
                detail = str(exc)
                # Missing is distinct from malformed or failing evidence, both block required criteria.
                status = "MISSING" if "cannot read JSON artifact" in detail else "FAILED"
        if criterion["method"] == "manual" and status == "MISSING":
            status = "NEEDS_HUMAN"
        report["criteria"].append({**criterion, "status": status, "detail": detail})
        if criterion["required"] and status != "VERIFIED":
            report["blocking"].append(criterion["id"])
    return report


def journey_next_action(plan, current, store):
    """A selected replay has an actionable next step; unavailable proof never means PASS."""
    if allows_validation_choice(plan):
        try:
            manual_journey_source(plan, current, store)
            return None
        except ValidationError:
            pass
        try:
            result = automatic_validation_result(plan, current, store)
            if result.get("status") == "PASS":
                return None
            if result.get("status") == "FAIL":
                return {"code": "RESUME_IMPLEMENTATION", "kind": "TASK_STATE", "blocking": True,
                        "command": f"python .agents/harness.py task resume --task-id {plan['task_id']}",
                        "reason": "Automatic device validation failed; resolve the observed failure before delivery."}
        except ValidationError:
            pass
        # Selection is presented with the established manual PASS/FAIL question after install.
        return None
    for journey in plan["verification_contract"]["journeys"]:
        identity = journey["id"]
        try:
            record = store.read(current["delivery_snapshot_sha256"], current["run_id"], "journey-" + identity)
            evidence = record.get("evidence") or {}
            if not isinstance(evidence, dict) or not isinstance(evidence.get("steps", []), list) \
                    or any(not isinstance(s, dict) for s in evidence.get("steps", [])):
                raise ValidationError("invalid journey step evidence")
            if record.get("status") == "PASS" and record.get("producer") == "journey_runner" \
                    and record.get("schema_version") == 1 \
                    and record.get("change_set_sha256") == current["change_set_sha256"] \
                    and (not current.get("harness_version") or record.get("harness_version") == current["harness_version"]) \
                    and evidence.get("definition_sha256") == canonical_sha256(journey) \
                    and evidence.get("plan_sha256") == plan["plan_sha256"] and evidence.get("task_id") == plan["task_id"] \
                    and len(evidence.get("steps") or []) == len(journey["steps"]) \
                    and all(s.get("status") == "PASS" for s in (evidence.get("steps") or [])):
                continue
            if record.get("status") == "FAIL":
                return {"code": "RESUME_IMPLEMENTATION", "kind": "TASK_STATE", "blocking": True,
                        "command": f"python .agents/harness.py task resume --task-id {plan['task_id']}",
                        "reason": "Selected journey failed; diagnose the observed assertion before a fresh verification run."}
        except ValidationError:
            pass
        return {"code": "RUN_SELECTED_JOURNEY", "kind": "HOST_ACTION", "blocking": True,
                "command": f"python .agents/harness.py journey list --task-id {plan['task_id']} --json",
                "reason": "Confirm the stated prerequisites, resolve the installed device serial, and run the approved journey. "
                          "Use journey run --id with --task-id and --serial. An unavailable device requires intervention; do not retry in a loop.",
                "inputs": {"task_id": plan["task_id"], "journey_id": identity, "prerequisites": journey["prerequisites"]}}
    return None


def active_context(repo, task_id, require_fresh=False):
    from workflow import task_dir, state_root, verification_freshness
    from plan_authority import validate_plan_hash
    directory = task_dir(repo, task_id)
    plan = read_json(directory / "plan.json")
    if plan.get("task_id") != task_id or not validate_plan_hash(plan)[0]:
        raise ValidationError("invalid task plan identity")
    current_path = directory / "current-run.json"
    current = read_json(current_path) if current_path.exists() else {}
    if require_fresh:
        if plan.get("status") != "VERIFYING":
            raise ValidationError("evidence association requires VERIFYING")
        freshness = verification_freshness(repo, task_id)
        if not freshness.get("fresh"):
            raise ValidationError(str(freshness.get("reason")))
    return plan, current, EvidenceStore(state_root(repo))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("coverage", "bind-evidence"))
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--criterion")
    parser.add_argument("--artifact")
    parser.add_argument("--case", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        from workflow import acceptance_coverage, associate_acceptance_evidence
        if args.action == "bind-evidence":
            if not args.criterion or not args.artifact:
                raise ValidationError("--criterion and --artifact are required")
            report = associate_acceptance_evidence(args)
        else:
            report = acceptance_coverage(args)
        print(json.dumps(report, indent=2))
        return 0
    except (ValidationError, OSError, ValueError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
