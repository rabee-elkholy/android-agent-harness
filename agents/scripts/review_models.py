"""Developer-owned reviewer model choices and immutable native dispatch settings.

This selects models, never reviewers, risk levels, providers or review proof.
Claude aliases are a documented native contract, not an account entitlement probe.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from _vnext_common import (
    ValidationError, atomic_write_json, canonical_sha256, read_json,
    state_root, task_dir, utc_now,
)
from evidence_store import StateLock
from policy_vocab import CORE_ROUTED_REVIEWERS

MODEL_CHOICES = ("inherit", "sonnet", "opus", "haiku")
CLAUDE_MODEL_SOURCE = "https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields"


def validate_policy(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"schema_version", "default", "overrides"}:
        raise ValidationError("review_model_policy requires schema_version, default and overrides only")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationError("review_model_policy schema_version must be 1")
    if not isinstance(value["default"], str) or value["default"] not in MODEL_CHOICES:
        raise ValidationError("review_model_policy default must be inherit, sonnet, opus or haiku")
    overrides = value["overrides"]
    if not isinstance(overrides, dict) or any(
        role not in CORE_ROUTED_REVIEWERS or not isinstance(model, str) or model not in MODEL_CHOICES
        for role, model in overrides.items()
    ):
        raise ValidationError("review_model_policy overrides must map canonical reviewer roles to supported choices")
    return {"schema_version": 1, "default": value["default"], "overrides": dict(sorted(overrides.items()))}


def default_policy() -> dict:
    return {"schema_version": 1, "default": "inherit", "overrides": {}}


def host_capability(host: str) -> dict:
    host = str(host).strip().lower()
    supported = host == "claude"
    return {
        "host": host, "supports_override": supported,
        "choices": list(MODEL_CHOICES if supported else ("inherit",)),
        "argument_name": "model" if supported else None,
        "source": CLAUDE_MODEL_SOURCE if supported else "no_supported_native_model_override",
        "availability": "HOST_ACCOUNT_DEPENDENT" if supported else "INHERIT_ONLY",
        "enforcement": "RULE_ENFORCED" if supported else "UNSUPPORTED",
    }


def validate_for_host(policy: dict, host: str) -> dict:
    policy = validate_policy(policy)
    cap = host_capability(host)
    selected = {policy["default"], *policy["overrides"].values()}
    if not selected.issubset(cap["choices"]):
        raise ValidationError(
            f"REVIEW_MODEL_UNSUPPORTED: host '{host}' has no supported per-reviewer model override; "
            "choose inherit explicitly or use a supported native host. No fallback was applied."
        )
    return policy


def _policy_file(repo: Path, task_id: str | None) -> Path:
    root = task_dir(repo, task_id) if task_id else state_root(repo)
    path = root / "review-models.json"
    if path.is_symlink() or not path.resolve().is_relative_to(state_root(repo).resolve()):
        raise ValidationError("review model configuration escapes harness state")
    return path


def load_policy(repo: Path, task_id: str | None = None) -> tuple[dict, str]:
    # Task configuration is a complete replacement, so 'inherit' can explicitly
    # override a project choice without merging stale per-role exceptions.
    for scope, identity in (("task", task_id), ("project", None)):
        if scope == "task" and not task_id:
            continue
        path = _policy_file(repo, identity)
        if path.exists():
            record = read_json(path)
            if not isinstance(record, dict) or record.get("scope") != scope or record.get("task_id") != identity:
                raise ValidationError("review model configuration scope mismatch")
            if record.get("record_sha256") != canonical_sha256({k: v for k, v in record.items() if k != "record_sha256"}):
                raise ValidationError("review model configuration checksum mismatch")
            return validate_policy(record.get("policy")), scope
    answers = repo / ".harness-setup" / "answers.json"
    if answers.exists():
        data = read_json(answers)
        if "review_model_policy" in data:
            return validate_policy(data["review_model_policy"]), "setup"
    return default_policy(), "default"


def freeze_models(repo: Path, task_id: str, host: str, reviewers: list[str]) -> dict:
    policy, source = load_policy(repo, task_id)
    return _resolve_policy(policy, source, host, reviewers)


def _resolve_policy(policy: dict, source: str, host: str, reviewers: list[str]) -> dict:
    policy = validate_for_host(policy, host)
    selections = {}
    for role in reviewers:
        if role not in CORE_ROUTED_REVIEWERS:
            raise ValidationError(f"unknown reviewer role '{role}'")
        requested = policy["overrides"].get(role, policy["default"])
        selections[role] = {
            "requested_model": requested,
            "model_policy": "INHERIT_PARENT_BY_OMISSION" if requested == "inherit" else "DEVELOPER_SELECTED_NATIVE",
            "model_argument": None if requested == "inherit" else "model",
            "native_arguments": {} if requested == "inherit" else {"model": requested},
            "actual_model": None, "actual_model_status": "UNOBSERVED",
        }
    frozen = {"schema_version": 1, "host": host, "source": source, "policy": policy, "reviewers": selections}
    frozen["sha256"] = canonical_sha256(frozen)
    return frozen


def transfer_models(run: dict, host: str, reviewers: list[str]) -> dict:
    """A host continuation preserves the original choice, never a live default."""
    frozen_models(run)
    old = run.get("review_models") or {}
    return _resolve_policy(old.get("policy") or default_policy(), old.get("source") or "default", host, reviewers)


def frozen_models(run: dict) -> dict:
    frozen = run.get("review_models")
    if frozen is None:
        return {}  # Historical runs retain inheritance, never read live config.
    if not isinstance(frozen, dict) or frozen.get("sha256") != canonical_sha256({k: v for k, v in frozen.items() if k != "sha256"}):
        raise ValidationError("frozen reviewer model settings checksum mismatch")
    if frozen.get("host") != run.get("review_host"):
        raise ValidationError("frozen reviewer model host mismatch")
    policy = validate_for_host(frozen.get("policy"), frozen["host"])
    reviewers = frozen.get("reviewers")
    if not isinstance(reviewers, dict):
        raise ValidationError("invalid frozen reviewer model roster")
    for role, selection in reviewers.items():
        requested = policy["overrides"].get(role, policy["default"])
        if role not in CORE_ROUTED_REVIEWERS or not isinstance(selection, dict) or selection.get("requested_model") != requested:
            raise ValidationError("invalid frozen reviewer model selection")
        expected_args = {} if requested == "inherit" else {"model": requested}
        if selection.get("native_arguments") != expected_args:
            raise ValidationError("invalid frozen native model arguments")
    return reviewers


def model_evidence(run: dict, role: str, transcript_identity: dict | None = None) -> dict:
    selection = frozen_models(run).get(role, {"requested_model": "inherit"})
    identity = transcript_identity or {}
    if run.get("review_host") == "claude" and identity.get("transcript_path"):
        from review_sources import read_claude_subagent_transcript
        _, observed = read_claude_subagent_transcript(Path(identity["transcript_path"]))
        if observed["transcript_sha256"] != identity.get("transcript_sha256"):
            raise ValidationError("reviewer transcript changed after ingestion")
        identity = observed
    else:
        identity = {}  # A report's own model claim is never native evidence.
    actual = identity.get("host_reported_model") if run.get("review_host") == "claude" else None
    if not isinstance(actual, str) or not actual:
        actual = None
    requested = selection["requested_model"]
    # Aliases identify families, not fixed versions. Only compare an observed
    # native model ID, never a model name supplied in the review response body.
    observed_models = identity.get("host_reported_models") or ([actual] if actual else [])
    pattern = r"claude-(?:[0-9]+(?:-[0-9]+)*-)?" + re.escape(requested) + r"(?:-|$)"
    if actual and requested != "inherit" and any(not re.match(pattern, model) for model in observed_models):
        raise ValidationError(f"REVIEW_MODEL_MISMATCH: {role} requested {requested}, host reported {actual}")
    if requested != "inherit" and not actual:
        raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: {role} requires its unchanged Claude transcript with native model metadata")
    return {
        "requested_model": requested, "actual_model": actual,
        "actual_model_status": "HOST_REPORTED_UNVERIFIED" if actual else "UNOBSERVED",
        "settings_sha256": (run.get("review_models") or {}).get("sha256"),
    }


def validate_model_evidence(run: dict, role: str, evidence: object) -> None:
    selection = frozen_models(run).get(role)
    if not selection or selection["requested_model"] == "inherit":
        return
    if not isinstance(evidence, dict) or (
        evidence.get("settings_sha256") != run["review_models"]["sha256"]
        or evidence.get("requested_model") != selection["requested_model"]
        or evidence.get("actual_model_status") != "HOST_REPORTED_UNVERIFIED"
        or not isinstance(evidence.get("actual_model"), str)
        or not re.match(r"claude-(?:[0-9]+(?:-[0-9]+)*-)?" + re.escape(selection["requested_model"]) + r"(?:-|$)", evidence["actual_model"])
    ):
        raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: missing or mismatched frozen model evidence for {role}")


def set_policy(repo: Path, policy: dict, *, task_id: str | None, host: str, source: str, proof_reference: str) -> dict:
    if source not in ("conversation", "developer_terminal") or not proof_reference.strip():
        raise ValidationError("review model changes require explicit developer source and proof-reference")
    policy = validate_for_host(policy, host)
    with StateLock(state_root(repo)):
        if task_id:
            plan = read_json(task_dir(repo, task_id) / "plan.json")
            if plan.get("status") not in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING"):
                raise ValidationError("task model choices require an unstarted review; resume implementation before changing future runs")
        record = {"schema_version": 1, "scope": "task" if task_id else "project", "task_id": task_id,
                  "policy": policy, "validated_host": host, "source": source,
                  "proof_reference": proof_reference.strip(), "updated_at": utc_now()}
        record["record_sha256"] = canonical_sha256(record)
        atomic_write_json(_policy_file(repo, task_id), record)
        return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("show", "set"), nargs="?", default="show")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", "--task-id", dest="task")
    parser.add_argument("--host")
    parser.add_argument("--default", choices=MODEL_CHOICES, default="inherit")
    parser.add_argument("--reviewer", action="append", default=[], metavar="ROLE=MODEL")
    parser.add_argument("--source", choices=("conversation", "developer_terminal"))
    parser.add_argument("--proof-reference", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        from review_sources import resolve_review_host
        host = resolve_review_host(repo, args.host)
        if args.action == "set":
            overrides = {}
            for item in args.reviewer:
                role, sep, model = item.partition("=")
                if not sep or role in overrides:
                    raise ValidationError("--reviewer requires unique ROLE=MODEL entries")
                overrides[role] = model
            result = set_policy(repo, {"schema_version": 1, "default": args.default, "overrides": overrides},
                                task_id=args.task, host=host, source=args.source, proof_reference=args.proof_reference)
            result["applies_to"] = "future review runs only; existing runs are unchanged"
        else:
            policy, source = load_policy(repo, args.task)
            result = {"policy": policy, "source": source, "capability": host_capability(host)}
            if args.task:
                path = task_dir(repo, args.task) / "current-run.json"
                if path.is_file():
                    run = read_json(path)
                    result["active_run_models"] = frozen_models(run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValidationError, OSError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
