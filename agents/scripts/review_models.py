"""Developer-owned reviewer model choices and immutable native dispatch settings.

This selects models, never reviewers, risk levels, providers or review proof.
Claude aliases and Antigravity subagent frontmatter models are documented native
contracts, not an account entitlement probe.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from _vnext_common import (
    ValidationError,
    active_review_package_path,
    atomic_write_bytes,
    atomic_write_json,
    canonical_sha256,
    read_json,
    sha256_file,
    state_root,
    task_dir,
    utc_now,
)
from evidence_store import StateLock
from policy_vocab import CORE_ROUTED_REVIEWERS

CLAUDE_MODEL_CHOICES = ("inherit", "sonnet", "opus", "haiku")
ANTIGRAVITY_MODEL_CHOICES = (
    "inherit",
    "flash-dynamic",
    "gemini-3.8-flash",
    "gemini-3.8-flash-fast",
    "gemini-3.8-flash-low",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-high",
    "flash",
    "argon-dynamic",
    "gemini-4-argon",
    "gemini-4-argon-low",
    "gemini-4-argon-medium",
    "gemini-4-argon-high",
    "argon",
    "gemini-3.1-pro",
    "gemini-3.1-pro-low",
    "gemini-3.1-pro-high",
    "pro",
)
MODEL_CHOICES = tuple(dict.fromkeys((*CLAUDE_MODEL_CHOICES, *ANTIGRAVITY_MODEL_CHOICES)))
CLAUDE_MODEL_SOURCE = "https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields"
ANTIGRAVITY_MODEL_SOURCE = "https://antigravity.google/docs/subagents/#frontmatter-configuration-yaml"

CRITICAL_HYBRID_REVIEWERS = (
    "bug-reviewer-agent",
    "perf-anr-guardian-agent",
    "security-reviewer-agent",
)

ANTIGRAVITY_INTERACTIVE_CHOICES: dict[str, dict[str, Any]] = {
    "flash-dynamic-task": {
        "id": "flash-dynamic-task",
        "index": 1,
        "scope": "task",
        "preset": "flash-dynamic",
        "label_ar": "فلاش مع مستويات ديناميك — للمهمة",
        "label_en": "Gemini 3.8 Flash (Dynamic Medium/High thinking) — for this task",
        "policy": {"schema_version": 1, "default": "flash-dynamic", "overrides": {}},
    },
    "flash-dynamic-once": {
        "id": "flash-dynamic-once",
        "index": 2,
        "scope": "run",
        "preset": "flash-dynamic",
        "label_ar": "فلاش مع مستويات ديناميك — هذه المرة فقط",
        "label_en": "Gemini 3.8 Flash (Dynamic Medium/High thinking) — this review only",
        "policy": {"schema_version": 1, "default": "flash-dynamic", "overrides": {}},
    },
    "inherit-task": {
        "id": "inherit-task",
        "index": 3,
        "scope": "task",
        "preset": "inherit",
        "label_ar": "موديل المحادثة — للمهمة",
        "label_en": "Current chat model (Inherit) — for this task",
        "policy": {"schema_version": 1, "default": "inherit", "overrides": {}},
    },
    "inherit-once": {
        "id": "inherit-once",
        "index": 4,
        "scope": "run",
        "preset": "inherit",
        "label_ar": "موديل المحادثة — هذه المرة فقط",
        "label_en": "Current chat model (Inherit) — this review only",
        "policy": {"schema_version": 1, "default": "inherit", "overrides": {}},
    },
    "hybrid-smart-task": {
        "id": "hybrid-smart-task",
        "index": 5,
        "scope": "task",
        "preset": "hybrid-smart",
        "label_ar": "هجين ذكي (فلاش للعادي + موديل المحادثة للحرج) — للمهمة",
        "label_en": "Smart Hybrid (Flash dynamic for standard + Chat model for critical) — for this task",
        "policy": {
            "schema_version": 1,
            "default": "flash-dynamic",
            "overrides": {role: "inherit" for role in CRITICAL_HYBRID_REVIEWERS},
        },
    },
    "hybrid-smart-once": {
        "id": "hybrid-smart-once",
        "index": 6,
        "scope": "run",
        "preset": "hybrid-smart",
        "label_ar": "هجين ذكي (فلاش للعادي + موديل المحادثة للحرج) — هذه المرة فقط",
        "label_en": "Smart Hybrid (Flash dynamic for standard + Chat model for critical) — this review only",
        "policy": {
            "schema_version": 1,
            "default": "flash-dynamic",
            "overrides": {role: "inherit" for role in CRITICAL_HYBRID_REVIEWERS},
        },
    },
}

_SHORTHAND_MAP = {
    "flash@dynamic": "flash-dynamic",
    "flash@auto": "flash-dynamic",
    "gemini-3.8-flash@dynamic": "flash-dynamic",
    "gemini-3.8-flash@auto": "flash-dynamic",
    "flash@fast": "gemini-3.8-flash-fast",
    "flash@low": "gemini-3.8-flash-low",
    "flash@medium": "gemini-3.8-flash-medium",
    "flash@high": "gemini-3.8-flash-high",
    "gemini-3.8-flash@fast": "gemini-3.8-flash-fast",
    "gemini-3.8-flash@low": "gemini-3.8-flash-low",
    "gemini-3.8-flash@medium": "gemini-3.8-flash-medium",
    "gemini-3.8-flash@high": "gemini-3.8-flash-high",
    "argon@dynamic": "argon-dynamic",
    "argon@auto": "argon-dynamic",
    "gemini-4-argon@dynamic": "argon-dynamic",
    "gemini-4-argon@auto": "argon-dynamic",
    "argon@low": "gemini-4-argon-low",
    "argon@medium": "gemini-4-argon-medium",
    "argon@high": "gemini-4-argon-high",
    "gemini-4-argon@low": "gemini-4-argon-low",
    "gemini-4-argon@medium": "gemini-4-argon-medium",
    "gemini-4-argon@high": "gemini-4-argon-high",
    "pro@low": "gemini-3.1-pro-low",
    "pro@high": "gemini-3.1-pro-high",
    "gemini-3.1-pro@low": "gemini-3.1-pro-low",
    "gemini-3.1-pro@high": "gemini-3.1-pro-high",
}


def normalize_model_token(token: object) -> object:
    if not isinstance(token, str):
        return token
    cleaned = token.strip().lower()
    return _SHORTHAND_MAP.get(cleaned, cleaned)


def choice_to_policy(choice_id: str) -> tuple[dict, str]:
    return resolve_interactive_choice(choice_id)


def resolve_interactive_choice(choice: str) -> tuple[dict, str]:
    raw = str(choice or "").strip()
    lower = raw.lower()
    if lower in ANTIGRAVITY_INTERACTIVE_CHOICES:
        entry = ANTIGRAVITY_INTERACTIVE_CHOICES[lower]
        return dict(entry["policy"]), str(entry["scope"])
    by_index = {str(v["index"]): v for v in ANTIGRAVITY_INTERACTIVE_CHOICES.values()}
    if lower in by_index:
        entry = by_index[lower]
        return dict(entry["policy"]), str(entry["scope"])
    for entry in ANTIGRAVITY_INTERACTIVE_CHOICES.values():
        if raw == entry["label_ar"] or lower == entry["label_en"].lower():
            return dict(entry["policy"]), str(entry["scope"])
    raise ValidationError(
        f"unknown reviewer model choice '{choice}'; supported choices: "
        + ", ".join(sorted(ANTIGRAVITY_INTERACTIVE_CHOICES))
    )


def resolve_preset_policy(preset: str) -> dict:
    norm = str(preset or "").strip().lower()
    if norm in ("flash-dynamic", "flash"):
        return {"schema_version": 1, "default": "flash-dynamic", "overrides": {}}
    if norm == "inherit":
        return default_policy()
    if norm in ("hybrid-smart", "hybrid"):
        return {
            "schema_version": 1,
            "default": "flash-dynamic",
            "overrides": {role: "inherit" for role in CRITICAL_HYBRID_REVIEWERS},
        }
    raise ValidationError(f"unknown reviewer model preset '{preset}'; use flash-dynamic, inherit, or hybrid-smart")


def resolve_antigravity_model(requested: str, role: str, effort_intent: str = "NORMAL") -> tuple[str, str]:
    """Resolve an Antigravity model choice and dynamic thinking level for a specific reviewer role."""
    req = str(normalize_model_token(requested) or "inherit")
    intent = str(effort_intent or "NORMAL").upper()
    is_deep = intent in ("DEEP", "MAX") or role in CRITICAL_HYBRID_REVIEWERS
    if req == "inherit":
        return "inherit", "inherit"
    if req in ("flash-dynamic", "gemini-3.8-flash", "flash"):
        return ("gemini-3.8-flash-high", "high") if is_deep else ("gemini-3.8-flash-medium", "medium")
    if req in ("argon-dynamic", "gemini-4-argon", "argon"):
        return ("gemini-4-argon-high", "high") if is_deep else ("gemini-4-argon-medium", "medium")
    if req in ("gemini-3.1-pro", "pro"):
        return "gemini-3.1-pro-high", "high"
    for suffix in ("fast", "low", "medium", "high"):
        if req.endswith(f"-{suffix}"):
            return req, suffix
    return req, "medium"


def validate_policy(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"schema_version", "default", "overrides"}:
        raise ValidationError("review_model_policy requires schema_version, default and overrides only")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationError("review_model_policy schema_version must be 1")
    default_val = normalize_model_token(value["default"]) if isinstance(value["default"], str) else value["default"]
    if not isinstance(default_val, str) or default_val not in MODEL_CHOICES:
        raise ValidationError(
            "review_model_policy default must be a supported model choice "
            "(inherit, sonnet, opus, haiku, flash-dynamic, gemini-3.8-flash-*, gemini-4-argon-*, gemini-3.1-pro-*)"
        )
    overrides = value["overrides"]
    if not isinstance(overrides, dict):
        raise ValidationError("review_model_policy overrides must map canonical reviewer roles to supported choices")
    normalized_overrides: dict[str, str] = {}
    for role, model in overrides.items():
        norm_model = normalize_model_token(model) if isinstance(model, str) else model
        if role not in CORE_ROUTED_REVIEWERS or not isinstance(norm_model, str) or norm_model not in MODEL_CHOICES:
            raise ValidationError("review_model_policy overrides must map canonical reviewer roles to supported choices")
        normalized_overrides[role] = norm_model
    return {"schema_version": 1, "default": default_val, "overrides": dict(sorted(normalized_overrides.items()))}


def default_policy() -> dict:
    return {"schema_version": 1, "default": "inherit", "overrides": {}}


def host_capability(host: str) -> dict:
    host = str(host).strip().lower()
    if host == "claude":
        return {
            "host": host,
            "supports_override": True,
            "choices": list(CLAUDE_MODEL_CHOICES),
            "argument_name": "model",
            "source": CLAUDE_MODEL_SOURCE,
            "availability": "HOST_ACCOUNT_DEPENDENT",
            "enforcement": "RULE_ENFORCED",
        }
    if host == "antigravity":
        return {
            "host": host,
            "supports_override": True,
            "choices": list(ANTIGRAVITY_MODEL_CHOICES),
            "interactive_choices": [
                {
                    "id": item["id"],
                    "scope": item["scope"],
                    "preset": item["preset"],
                    "label_ar": item["label_ar"],
                    "label_en": item["label_en"],
                }
                for item in ANTIGRAVITY_INTERACTIVE_CHOICES.values()
                if item["index"] <= 5
            ],
            "argument_name": None,
            "agent_frontmatter_field": "model",
            "source": ANTIGRAVITY_MODEL_SOURCE,
            "availability": "HOST_ACCOUNT_DEPENDENT",
            "enforcement": "FRONTMATTER_ENFORCED",
        }
    return {
        "host": host,
        "supports_override": False,
        "choices": ["inherit"],
        "argument_name": None,
        "source": "no_supported_native_model_override",
        "availability": "INHERIT_ONLY",
        "enforcement": "UNSUPPORTED",
    }


def validate_for_host(policy: dict, host: str) -> dict:
    policy = validate_policy(policy)
    cap = host_capability(host)
    selected = {policy["default"], *policy["overrides"].values()}
    if not selected.issubset(cap["choices"]):
        raise ValidationError(
            f"REVIEW_MODEL_UNSUPPORTED: host '{host}' does not support model choice(s) {sorted(selected - set(cap['choices']))}; "
            "choose inherit explicitly or use a supported native model for this host. No fallback was applied."
        )
    return policy


def _policy_file(repo: Path, task_id: str | None, *, scope: str = "task") -> Path:
    root = task_dir(repo, task_id) if task_id else state_root(repo)
    filename = "review-models-run.json" if (task_id and scope == "run") else "review-models.json"
    path = root / filename
    if path.is_symlink() or not path.resolve().is_relative_to(state_root(repo).resolve()):
        raise ValidationError("review model configuration escapes harness state")
    return path


def _active_run_identifiers(repo: Path, task_id: str) -> set[str]:
    """Return active run IDs (final verification run_id and/or active phase_review_run_id) for task_id."""
    active_ids: set[str] = set()
    tdir = task_dir(repo, task_id)
    crun = tdir / "current-run.json"
    if crun.is_file():
        try:
            rid = str(read_json(crun).get("run_id") or "").strip()
            if rid:
                active_ids.add(rid)
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            pass
    pstate_f = tdir / "phase-state.json"
    if pstate_f.is_file():
        try:
            pstate = read_json(pstate_f)
            cur_phase = str(pstate.get("current_phase_id") or "").strip()
            if cur_phase:
                from phase_review import phase_run_file
                prun_f = phase_run_file(tdir, cur_phase)
                if prun_f.is_file():
                    prid = str(read_json(prun_f).get("phase_review_run_id") or "").strip()
                    if prid:
                        active_ids.add(prid)
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            pass
    return active_ids


def load_policy(
    repo: Path,
    task_id: str | None = None,
    *,
    run_id: str | None = None,
    consume_next_run: bool = False,
) -> tuple[dict, str]:
    # 1. Run-scoped ("this review only") configuration takes highest precedence for its bound run_id.
    if task_id:
        run_path = _policy_file(repo, task_id, scope="run")
        if run_path.exists():
            record = read_json(run_path)
            if not isinstance(record, dict) or record.get("scope") != "run" or record.get("task_id") != task_id:
                raise ValidationError("review model run configuration scope mismatch")
            if record.get("record_sha256") != canonical_sha256({k: v for k, v in record.items() if k != "record_sha256"}):
                raise ValidationError("review model configuration checksum mismatch")
            bound_run = str(record.get("bound_run_id") or "")
            if bound_run == "next_run":
                if consume_next_run and run_id:
                    record["bound_run_id"] = run_id
                    record["record_sha256"] = canonical_sha256({k: v for k, v in record.items() if k != "record_sha256"})
                    atomic_write_json(run_path, record)
                return validate_policy(record.get("policy")), "run"
            if run_id and bound_run == run_id:
                return validate_policy(record.get("policy")), "run"
            if run_id is None and bound_run and bound_run in _active_run_identifiers(repo, task_id):
                return validate_policy(record.get("policy")), "run"

    # 2. Task-scoped and Project-scoped configuration.
    for scope, identity in (("task", task_id), ("project", None)):
        if scope == "task" and not task_id:
            continue
        path = _policy_file(repo, identity, scope=scope)
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


def _compute_efforts_by_role(
    repo: Path,
    task_id: str | None,
    reviewers: list[str],
    policy_data: dict | None = None,
    plan: dict | None = None,
) -> dict[str, str]:
    efforts: dict[str, str] = {}
    if task_id and (policy_data is None or plan is None):
        tdir = task_dir(repo, task_id)
        if plan is None and (tdir / "plan.json").is_file():
            try:
                plan = read_json(tdir / "plan.json")
            except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
                plan = {}
        if policy_data is None:
            crun = tdir / "current-run.json"
            if crun.is_file():
                try:
                    pol_p = Path(str(read_json(crun).get("policy") or ""))
                    if pol_p.is_file():
                        policy_data = read_json(pol_p)
                except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
                    policy_data = {}
            elif (tdir / "policy.json").is_file():
                try:
                    policy_data = read_json(tdir / "policy.json")
                except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
                    policy_data = {}
    try:
        from review_policy import reviewer_effort_for
        surfaces = (policy_data or {}).get("surfaces") or (plan or {}).get("expected_surfaces") or []
        severity = (policy_data or {}).get("severity") or "HIGH"
        round_number = int((policy_data or {}).get("review_round") or (((plan or {}).get("review_rounds") or 0) + 1))
        finding_owners = set(((policy_data or {}).get("later_round_source") or {}).get("finding_owners") or [])
        planning_depth = str((plan or {}).get("planning_depth") or "BOUNDED")
        raw_mods = (plan or {}).get("changed_modules") or (plan or {}).get("expected_modules") or []
        mod_count = len(raw_mods) if isinstance(raw_mods, list) and raw_mods else 1
        for role in reviewers:
            efforts[role] = reviewer_effort_for(
                role,
                surfaces=surfaces,
                severity=severity,
                round_number=round_number,
                is_finding_owner=(role in finding_owners),
                planning_depth=planning_depth,
                changed_modules_count=mod_count,
            )
    except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
        for role in reviewers:
            efforts[role] = "DEEP" if role in CRITICAL_HYBRID_REVIEWERS else "NORMAL"
    return efforts


def sync_antigravity_agent_models(repo: Path, selections: dict[str, dict] | None = None) -> list[str]:
    """Synchronize resolved Antigravity reviewer models into .agents/agents/<role>/agent.md frontmatter."""
    agents_base = repo / ".agents" / "agents"
    subagents_base = repo / ".agents" / "subagents"
    if not subagents_base.is_dir():
        kit_subagents = Path(__file__).resolve().parents[1] / "subagents"
        if kit_subagents.is_dir():
            subagents_base = kit_subagents
    if not agents_base.is_dir() or not subagents_base.is_dir():
        return []
    try:
        from install_tool_adapters import antigravity_agent_markdown, with_managed_marker
    except ImportError:
        return []

    updated: list[str] = []
    selections = selections or {}
    from reviewer_host import active_reviews, _load_ledger
    for run, ledger_file in active_reviews(repo):
        if run.get("review_host") != "antigravity" or not ledger_file.is_file():
            continue
        for role, entry in _load_ledger(run, ledger_file).get("reviewers", {}).items():
            if role not in selections or entry.get("state") != "DISPATCHED" or entry.get("execution_id"):
                continue
            pending = frozen_models(run).get(role, {})
            expected = pending.get("agent_frontmatter_model") or pending.get("resolved_model")
            desired = selections[role].get("agent_frontmatter_model") or selections[role].get("resolved_model")
            if expected != desired:
                raise ValidationError(f"REVIEW_MODEL_LAUNCH_PENDING: {role} still needs execution binding in task {run['task_id']}; its launch settings cannot change")
    for role in selections:
        if role not in CORE_ROUTED_REVIEWERS:
            raise ValidationError(f"unknown reviewer role '{role}'")
        json_path = subagents_base / f"{role}.json"
        dest = agents_base / role / "agent.md"
        if not json_path.is_file() or not dest.parent.is_dir():
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            continue
        sel = selections[role]
        fm_model = sel.get("agent_frontmatter_model") or sel.get("resolved_model")
        if fm_model == "inherit":
            fm_model = None
        rendered = with_managed_marker(antigravity_agent_markdown(data, model=fm_model))
        rendered_bytes = rendered.encode("utf-8")
        try:
            current_bytes = dest.read_bytes() if dest.is_file() else None
        except OSError:
            current_bytes = None
        if current_bytes != rendered_bytes:
            dest.write_bytes(rendered_bytes)
            updated.append(f".agents/agents/{role}/agent.md")

    ownership_file = repo / ".harness-setup" / "ownership-v1.json"
    if updated and ownership_file.is_file():
        try:
            manifest = read_json(ownership_file)
            entries = manifest.get("entries")
            if isinstance(entries, list):
                changed = False
                updated_set = set(updated)
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("path") in updated_set:
                        target = repo / str(entry["path"])
                        if target.is_file():
                            entry["post_install_sha256"] = sha256_file(target)
                            changed = True
                if changed:
                    manifest["ownership_sha256"] = canonical_sha256(
                        {k: v for k, v in manifest.items() if k != "ownership_sha256"}
                    )
                    atomic_write_json(ownership_file, manifest)
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            pass
    return updated


def freeze_models(
    repo: Path,
    task_id: str,
    host: str,
    reviewers: list[str],
    *,
    run_id: str | None = None,
    policy_data: dict | None = None,
    plan: dict | None = None,
) -> dict:
    policy, source = load_policy(repo, task_id, run_id=run_id, consume_next_run=bool(run_id))
    efforts = _compute_efforts_by_role(repo, task_id, reviewers, policy_data=policy_data, plan=plan)
    frozen = _resolve_policy(policy, source, host, reviewers, efforts_by_role=efforts)
    if str(host).strip().lower() == "antigravity":
        sync_antigravity_agent_models(repo, frozen.get("reviewers") or {})
    return frozen


def _resolve_policy(
    policy: dict,
    source: str,
    host: str,
    reviewers: list[str],
    *,
    efforts_by_role: dict[str, str] | None = None,
) -> dict:
    host_norm = str(host).strip().lower()
    policy = validate_for_host(policy, host_norm)
    efforts = efforts_by_role or {}
    selections = {}
    for role in reviewers:
        if role not in CORE_ROUTED_REVIEWERS:
            raise ValidationError(f"unknown reviewer role '{role}'")
        requested = policy["overrides"].get(role, policy["default"])
        if host_norm == "antigravity" and requested != "inherit":
            effort_intent = efforts.get(role) or ("DEEP" if role in CRITICAL_HYBRID_REVIEWERS else "NORMAL")
            resolved_model, thinking_level = resolve_antigravity_model(requested, role, effort_intent)
            selections[role] = {
                "requested_model": requested,
                "resolved_model": resolved_model,
                "thinking_level": thinking_level,
                "reasoning_intent": effort_intent,
                "model_policy": "DEVELOPER_SELECTED_NATIVE",
                "model_argument": None,
                "native_arguments": {},
                "agent_frontmatter_model": resolved_model,
                "actual_model": None,
                "actual_model_status": "UNOBSERVED",
            }
        else:
            selections[role] = {
                "requested_model": requested,
                "model_policy": "INHERIT_PARENT_BY_OMISSION" if requested == "inherit" else "DEVELOPER_SELECTED_NATIVE",
                "model_argument": None if requested == "inherit" else "model",
                "native_arguments": {} if requested == "inherit" else {"model": requested},
                "actual_model": None,
                "actual_model_status": "UNOBSERVED",
            }
    frozen = {"schema_version": 1, "host": host_norm, "source": source, "policy": policy, "reviewers": selections}
    if host_norm == "antigravity":
        frozen["selection_required"] = source == "default"
    frozen["sha256"] = canonical_sha256(frozen)
    return frozen


def transfer_models(run: dict, host: str, reviewers: list[str], *, plan: dict | None = None) -> dict:
    """A host continuation preserves the original choice, never a live default."""
    frozen_models(run)
    old = run.get("review_models") or {}
    old_efforts = {
        role: str(sel.get("reasoning_intent") or ("DEEP" if role in CRITICAL_HYBRID_REVIEWERS else "NORMAL"))
        for role, sel in (old.get("reviewers") or {}).items()
        if isinstance(sel, dict)
    }
    return _resolve_policy(
        old.get("policy") or default_policy(),
        old.get("source") or "default",
        host,
        reviewers,
        efforts_by_role=old_efforts,
    )


def frozen_models(run: dict) -> dict:
    frozen = run.get("review_models")
    if frozen is None:
        return {}  # Historical runs retain inheritance, never read live config.
    if not isinstance(frozen, dict) or frozen.get("sha256") != canonical_sha256({k: v for k, v in frozen.items() if k != "sha256"}):
        raise ValidationError("frozen reviewer model settings checksum mismatch")
    if frozen.get("host") != run.get("review_host"):
        raise ValidationError("frozen reviewer model host mismatch")
    host_norm = str(frozen["host"]).strip().lower()
    policy = validate_for_host(frozen.get("policy"), host_norm)
    reviewers = frozen.get("reviewers")
    if not isinstance(reviewers, dict):
        raise ValidationError("invalid frozen reviewer model roster")
    for role, selection in reviewers.items():
        requested = policy["overrides"].get(role, policy["default"])
        if role not in CORE_ROUTED_REVIEWERS or not isinstance(selection, dict) or selection.get("requested_model") != requested:
            raise ValidationError("invalid frozen reviewer model selection")
        expected_args = {} if (requested == "inherit" or host_norm == "antigravity") else {"model": requested}
        if selection.get("native_arguments") != expected_args:
            raise ValidationError("invalid frozen native model arguments")
        if host_norm == "antigravity" and requested != "inherit":
            intent = str(selection.get("reasoning_intent") or ("DEEP" if role in CRITICAL_HYBRID_REVIEWERS else "NORMAL"))
            exp_resolved, exp_thinking = resolve_antigravity_model(requested, role, intent)
            if selection.get("resolved_model") != exp_resolved or selection.get("thinking_level") != exp_thinking:
                raise ValidationError("invalid frozen Antigravity resolved model or thinking level")
    return reviewers


def _antigravity_frontmatter_model(repo: Path | None, role: str) -> str | None:
    if repo is None:
        return None
    agent_file = Path(repo) / ".agents" / "agents" / role / "agent.md"
    if not agent_file.is_file():
        return None
    try:
        text = agent_file.read_text(encoding="utf-8", errors="replace")
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if line.strip().startswith("model:"):
                    raw_val = line.split(":", 1)[1].strip().strip('"').strip("'")
                    return raw_val or None
    except OSError:
        return None
    return None


def model_evidence(run: dict, role: str, transcript_identity: dict | None = None) -> dict:
    selection = frozen_models(run).get(role, {"requested_model": "inherit"})
    requested = selection["requested_model"]
    host_norm = str(run.get("review_host") or "").strip().lower()
    identity = transcript_identity or {}

    if host_norm == "antigravity":
        from antigravity_runtime import native_model_metadata
        try:
            observed = native_model_metadata(Path(identity["transcript_path"])) if identity.get("transcript_path") else {}
        except ValidationError:
            if requested != "inherit":
                raise
            observed = {}  # Legacy inheritance requires no invented native proof.
        expected_resolved = selection.get("resolved_model")
        if requested != "inherit":
            if not observed:
                raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: {role} requires native execution model metadata; frontmatter is configuration only")
            # The native runtime ID omits thinking and may use a backend suffix.
            # The executor's separate model field binds the exact thinking choice.
            family = re.sub(r"-(?:fast|low|medium|high|tiered)$", "", str(expected_resolved))
            valid_configured = {expected_resolved, f"{family}-tiered"}
            if observed.get("host_configured_model") not in valid_configured or any(
                not re.fullmatch(re.escape(family) + r"(?:-(?:n|tiered))?", m) and m != expected_resolved
                for m in observed.get("host_reported_models", [])
            ):
                raise ValidationError(f"REVIEW_MODEL_MISMATCH: {role} native execution does not match {expected_resolved}")
        return {
            "requested_model": requested,
            "resolved_model": expected_resolved,
            "thinking_level": selection.get("thinking_level"),
            "actual_model": (observed.get("host_reported_models") or [None])[-1],
            "actual_model_status": "NATIVE_METADATA_OBSERVED" if observed else "UNOBSERVED",
            **observed,
            "settings_sha256": (run.get("review_models") or {}).get("sha256"),
        }

    if host_norm == "claude" and identity.get("transcript_path"):
        from review_sources import read_claude_subagent_transcript
        _, observed = read_claude_subagent_transcript(Path(identity["transcript_path"]))
        if observed["transcript_sha256"] != identity.get("transcript_sha256"):
            raise ValidationError("reviewer transcript changed after ingestion")
        identity = observed
    else:
        identity = {}  # A report's own model claim is never native evidence.
    actual = identity.get("host_reported_model") if host_norm == "claude" else None
    if not isinstance(actual, str) or not actual:
        actual = None
    # Aliases identify families, not fixed versions. Only compare an observed
    # native model ID, never a model name supplied in the review response body.
    observed_models = identity.get("host_reported_models") or ([actual] if actual else [])
    pattern = r"claude-(?:[0-9]+(?:-[0-9]+)*-)?" + re.escape(requested) + r"(?:-|$)"
    if actual and requested != "inherit" and any(not re.match(pattern, model) for model in observed_models):
        raise ValidationError(f"REVIEW_MODEL_MISMATCH: {role} requested {requested}, host reported {actual}")
    if requested != "inherit" and not actual:
        raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: {role} requires its unchanged Claude transcript with native model metadata")
    return {
        "requested_model": requested,
        "actual_model": actual,
        "actual_model_status": "HOST_REPORTED_UNVERIFIED" if actual else "UNOBSERVED",
        "settings_sha256": (run.get("review_models") or {}).get("sha256"),
    }


def validate_model_evidence(run: dict, role: str, evidence: object) -> None:
    selection = frozen_models(run).get(role)
    if not selection or selection["requested_model"] == "inherit":
        return
    host_norm = str(run.get("review_host") or "").strip().lower()
    if host_norm == "antigravity":
        family = re.sub(r"-(?:fast|low|medium|high|tiered)$", "", str(selection.get("resolved_model")))
        valid_configured = {selection.get("resolved_model"), f"{family}-tiered"}
        if not isinstance(evidence, dict) or (
            evidence.get("settings_sha256") != run["review_models"]["sha256"]
            or evidence.get("requested_model") != selection["requested_model"]
            or evidence.get("resolved_model") != selection.get("resolved_model")
            or evidence.get("thinking_level") != selection.get("thinking_level")
            or evidence.get("actual_model_status") != "NATIVE_METADATA_OBSERVED"
            or evidence.get("host_configured_model") not in valid_configured
            or not evidence.get("native_metadata_sha256")
            or not evidence.get("execution_id")
            or not evidence.get("host_reported_models")
        ):
            raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: missing or mismatched frozen Antigravity model evidence for {role}")
        native = {key: evidence[key] for key in ("execution_id", "host_configured_model", "host_reported_models", "native_metadata_source") if key in evidence}
        if evidence["native_metadata_sha256"] != canonical_sha256(native) or any(
            not re.fullmatch(re.escape(family) + r"(?:-(?:n|tiered))?", m) and m != selection.get("resolved_model")
            for m in evidence["host_reported_models"]
        ):
            raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: native model evidence integrity mismatch for {role}")
        return

    if not isinstance(evidence, dict) or (
        evidence.get("settings_sha256") != run["review_models"]["sha256"]
        or evidence.get("requested_model") != selection["requested_model"]
        or evidence.get("actual_model_status") != "HOST_REPORTED_UNVERIFIED"
        or not isinstance(evidence.get("actual_model"), str)
        or not re.match(r"claude-(?:[0-9]+(?:-[0-9]+)*-)?" + re.escape(selection["requested_model"]) + r"(?:-|$)", evidence["actual_model"])
    ):
        raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: missing or mismatched frozen model evidence for {role}")


def effective_reviewer_model(selection: dict | None) -> str:
    """Return a concise human-readable model label for a reviewer selection."""
    if not isinstance(selection, dict):
        return "inherit"
    resolved = str(selection.get("resolved_model") or selection.get("agent_frontmatter_model") or "").strip()
    requested = str(selection.get("requested_model") or "inherit").strip() or "inherit"
    actual = str(selection.get("actual_model") or "").strip()
    if resolved and resolved != "inherit":
        return resolved
    if requested != "inherit":
        return actual or requested
    if actual:
        return f"inherit ({actual})"
    return "inherit"


def reviewer_model_map(run_or_profile: dict | None, reviewers: list[str] | None = None) -> dict[str, str]:
    """Map each reviewer role to its effective model label."""
    if not isinstance(run_or_profile, dict):
        return {role: "inherit" for role in (reviewers or [])}
    rev_source: dict[str, Any] = {}
    if isinstance(run_or_profile.get("review_models"), dict):
        rev_source = run_or_profile["review_models"].get("reviewers") or {}
    elif isinstance(run_or_profile.get("reviewers"), dict):
        rev_source = run_or_profile["reviewers"]
    roles = list(reviewers) if reviewers is not None else sorted(rev_source.keys())
    return {role: effective_reviewer_model(rev_source.get(role)) for role in roles}


def format_reviewers_with_models(run_or_profile: dict | None, reviewers: list[str]) -> str:
    """Format a list of reviewer roles with their active model in brackets."""
    mapping = reviewer_model_map(run_or_profile, reviewers)
    return ", ".join(f"{role} [{mapping.get(role, 'inherit')}]" for role in reviewers)


def model_choice_summary(repo: Path, task_id: str) -> str:
    policy, source = load_policy(repo, task_id)
    overrides = ", ".join(f"{r}={m}" for r, m in sorted(policy["overrides"].items()))
    return (f"Reviewer model: {policy['default']} (source: {source})"
            + (f"; overrides: {overrides}" if overrides else "")
            + ". Model selection is separate from plan approval; an unresolved Antigravity choice is asked once before first dispatch.")


def build_antigravity_model_prompt(
    repo: Path,
    task_id: str,
    reviewers: list[str],
    *,
    run_id: str = "",
    phase_id: str = "",
    efforts_by_role: dict[str, str] | None = None,
) -> dict:
    """Build the 5-option developer prompt shown before the first review in a task/run on Antigravity."""
    efforts = efforts_by_role or _compute_efforts_by_role(repo, task_id, reviewers)
    flash_preview = {
        role: resolve_antigravity_model("flash-dynamic", role, efforts.get(role, "NORMAL"))[0]
        for role in reviewers
    }
    hybrid_preview = {
        role: (
            "inherit"
            if role in CRITICAL_HYBRID_REVIEWERS
            else resolve_antigravity_model("flash-dynamic", role, efforts.get(role, "NORMAL"))[0]
        )
        for role in reviewers
    }
    options = []
    for key in (
        "flash-dynamic-task",
        "flash-dynamic-once",
        "inherit-task",
        "inherit-once",
        "hybrid-smart-task",
    ):
        item = ANTIGRAVITY_INTERACTIVE_CHOICES[key]
        options.append({
            "id": item["id"],
            "label_ar": item["label_ar"],
            "label_en": item["label_en"],
            "scope": item["scope"],
            "command": (
                f'python .agents/harness.py review models set --task-id {task_id} --host antigravity '
                f'--choice {item["id"]} --source conversation --proof-reference "<developer answer>"'
            ),
        })
    return {
        "code": "SELECT_REVIEW_MODEL",
        "tool": "ask_question",
        "task_id": task_id,
        "run_id": run_id,
        "phase_id": phase_id,
        "reviewers": list(reviewers),
        "question_ar": "اختر موديل ومستوى تفكير المراجعين قبل بدء المراجعة:",
        "question_en": "Choose the reviewer model and thinking level before launching reviewers:",
        "flash_dynamic_resolution": flash_preview,
        "hybrid_smart_resolution": hybrid_preview,
        "options": options,
        "choices": options,
    }


def _is_undispatched_final_run(tdir: Path, current: dict) -> bool:
    run_id = str(current.get("run_id") or "")
    if not run_id:
        return False
    ledger_p = tdir / "review-execution" / run_id / "ledger.json"
    if ledger_p.is_file():
        try:
            ledger = read_json(ledger_p)
            for info in (ledger.get("reviewers") or {}).values():
                if isinstance(info, dict) and info.get("state") not in (None, "NOT_DISPATCHED"):
                    return False
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            return False
    disp_dir = tdir / "reviewer-dispatches"
    if disp_dir.is_dir():
        for f in disp_dir.glob("*.json"):
            try:
                if str(read_json(f).get("run_id") or "") in ("", run_id):
                    return False
            except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
                return False
        if (disp_dir / run_id).is_dir() and any((disp_dir / run_id).glob("*.json")):
            return False
    staged_dir = tdir / "staged-reviews" / run_id
    if staged_dir.is_dir() and any(staged_dir.glob("*.json")):
        return False
    return True


def assert_dispatch_ready(repo: Path, run: dict, roles: list[str]) -> None:
    """Validate publication and bind shared native controls before spending calls.

    Callers hold the repository state lock through receipt publication. A pending
    launch keeps its native settings until its execution has been identified.
    """
    if (state_root(repo) / "review-model-update.json").exists():
        raise ValidationError("REVIEW_MODEL_UPDATE_INCOMPLETE: repeat the recorded model choice to finish publication")
    selections = frozen_models(run)
    if (run.get("review_models") or {}).get("selection_required"):
        raise ValidationError("SELECT_REVIEW_MODEL: record the developer's model choice before dispatch; plan approval is separate")
    if str(run.get("review_host") or "").lower() == "antigravity":
        active_policy, source = load_policy(repo, run.get("task_id"), run_id=run.get("phase_review_run_id") or run.get("run_id"))
        if source in {"task", "run"} and ((run.get("review_models") or {}).get("source") != source or (run.get("review_models") or {}).get("policy") != active_policy):
            raise ValidationError("REVIEW_MODEL_SELECTION_STALE: the active run does not bind the recorded task/run choice")
        sync_antigravity_agent_models(repo, {r: selections[r] for r in roles if r in selections})
        for role in roles:
            selection = selections.get(role, {})
            expected = selection.get("agent_frontmatter_model") or selection.get("resolved_model")
            expected = None if expected == "inherit" else expected
            if _antigravity_frontmatter_model(repo, role) != expected:
                raise ValidationError(f"REVIEW_MODEL_CONFIGURATION_UNAVAILABLE: {role} native configuration is not synchronized")


def _is_undispatched_phase_run(tdir: Path, phase_id: str) -> tuple[bool, Path | None]:
    from phase_review import phase_run_file, phase_ledger_file, load_phase_ledger, phase_review_dir
    prun_f = phase_run_file(tdir, phase_id)
    if not prun_f.is_file():
        return True, None
    run = read_json(prun_f)
    ok, reason, ledger = load_phase_ledger(tdir, phase_id, expected_run_id=run.get("phase_review_run_id"))
    if not ok:
        raise ValidationError(f"phase review ledger cannot establish an unstarted review: {reason}")
    if any(info.get("state") != "NOT_DISPATCHED" for info in ledger["reviewers"].values()):
        return False, prun_f
    if any((phase_review_dir(tdir, phase_id) / "dispatch" / str(run["phase_review_run_id"])).glob("*.json")):
        return False, prun_f
    return True, prun_f


def _refresh_undispatched_runs(repo: Path, task_id: str, host: str) -> dict[str, Any]:
    """Refresh active undispatched final or phase review run and regenerate briefs when model choice changes."""
    tdir = task_dir(repo, task_id)
    plan_f = tdir / "plan.json"
    if not plan_f.is_file():
        return {}
    plan = read_json(plan_f)
    refreshed: dict[str, Any] = {}

    # 1. Check active phase review run if in IMPLEMENTING
    pstate_f = tdir / "phase-state.json"
    if plan.get("status") == "IMPLEMENTING" and pstate_f.is_file():
        pstate = read_json(pstate_f)
        phase_id = str(pstate.get("current_phase_id") or "")
        ok_phase, prun_f = _is_undispatched_phase_run(tdir, phase_id)
        if ok_phase and prun_f:
            from phase_review import refresh_undispatched_phase_models
            run_meta = refresh_undispatched_phase_models(repo, task_id, phase_id)
            refreshed["phase_review_run_id"] = run_meta["phase_review_run_id"]
            refreshed["active_run_models"] = run_meta["review_models"]["reviewers"]

    # 2. Check active final verification run if in VERIFYING
    crun_f = tdir / "current-run.json"
    if plan.get("status") == "VERIFYING" and crun_f.is_file():
        current = read_json(crun_f)
        if _is_undispatched_final_run(tdir, current):
            pol_p = Path(str(current.get("policy") or ""))
            policy_data = read_json(pol_p) if pol_p.is_file() else {}
            roster = list(policy_data.get("reviewers") or [])
            run_id = str(current.get("run_id") or "")
            run_host = str(current.get("review_host") or host)
            frozen = freeze_models(
                repo, task_id, run_host, roster, run_id=run_id, policy_data=policy_data, plan=plan
            )
            current["review_models"] = frozen
            atomic_write_json(crun_f, current)
            pkg_path = active_review_package_path(repo, current)
            if pkg_path.is_file():
                pkg_dir = pkg_path.parent
                pkg_path.unlink(missing_ok=True)
                for b_file in pkg_dir.glob("brief-*.md"):
                    b_file.unlink(missing_ok=True)
                ledger_p = tdir / "review-execution" / run_id / "ledger.json"
                ledger_p.unlink(missing_ok=True)
                from review_package import build_package
                build_package(repo, task_id)
            refreshed["run_id"] = run_id
            refreshed["active_run_models"] = frozen.get("reviewers") or {}

    return refreshed


def set_policy(
    repo: Path,
    policy: dict,
    *,
    task_id: str | None,
    host: str,
    source: str,
    proof_reference: str,
    scope: str | None = None,
) -> dict:
    if source not in ("conversation", "developer_terminal") or not proof_reference.strip():
        raise ValidationError("review model changes require explicit developer source and proof-reference")
    policy = validate_for_host(policy, host)
    resolved_scope = scope or ("task" if task_id else "project")
    if resolved_scope not in ("project", "task", "run"):
        raise ValidationError("scope must be project, task, or run")
    if resolved_scope in ("task", "run") and not task_id:
        raise ValidationError(f"scope '{resolved_scope}' requires --task-id")

    with StateLock(state_root(repo)):
        pending_file = state_root(repo) / "review-model-update.json"
        operation = {"task_id": task_id, "scope": resolved_scope, "host": host, "policy": policy}
        if pending_file.exists() and read_json(pending_file) != operation:
            raise ValidationError("REVIEW_MODEL_UPDATE_INCOMPLETE: repeat the pending model choice before making another change")

        def already_applied(run: dict) -> dict | None:
            path = _policy_file(repo, task_id, scope=resolved_scope)
            if pending_file.exists() or not path.is_file():
                return None
            existing = read_json(path)
            if existing.get("record_sha256") != canonical_sha256({k: v for k, v in existing.items() if k != "record_sha256"}):
                raise ValidationError("review model configuration checksum mismatch")
            frozen_models(run)
            if (existing.get("policy") == policy and existing.get("scope") == resolved_scope
                    and existing.get("validated_host") == host
                    and (run.get("review_models") or {}).get("policy") == policy
                    and (run.get("review_models") or {}).get("source") == resolved_scope):
                return {**existing, "already_applied": True}
            return None
        bound_run_id = None
        if task_id:
            tdir = task_dir(repo, task_id)
            plan_path = tdir / "plan.json"
            if not plan_path.is_file():
                raise ValidationError(f"task '{task_id}' has no plan.json")
            plan = read_json(plan_path)
            status = str(plan.get("status") or "")
            if status == "VERIFYING":
                crun_f = tdir / "current-run.json"
                if not crun_f.is_file() or not _is_undispatched_final_run(tdir, read_json(crun_f)):
                    previous = already_applied(read_json(crun_f)) if crun_f.is_file() else None
                    if previous:
                        return previous
                    raise ValidationError("task model choices require an unstarted review; resume implementation before changing future runs")
                bound_run_id = str(read_json(crun_f).get("run_id") or "next_run")
            elif status == "IMPLEMENTING":
                pstate_f = tdir / "phase-state.json"
                if pstate_f.is_file():
                    pstate = read_json(pstate_f)
                    cur_phase = str(pstate.get("current_phase_id") or "")
                    if cur_phase:
                        ok_phase, prun_f = _is_undispatched_phase_run(tdir, cur_phase)
                        if not ok_phase:
                            previous = already_applied(read_json(prun_f)) if prun_f else None
                            if previous:
                                return previous
                            raise ValidationError("phase review already dispatched; finish or re-checkpoint before changing reviewer models")
                        if prun_f and prun_f.is_file():
                            bound_run_id = str(read_json(prun_f).get("phase_review_run_id") or "next_run")
                if not bound_run_id:
                    bound_run_id = "next_run"
            elif status in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED"):
                bound_run_id = "next_run"
            else:
                raise ValidationError("task model choices require an unstarted review; resume implementation before changing future runs")

        record: dict[str, Any] = {
            "schema_version": 1,
            "scope": resolved_scope,
            "task_id": task_id if resolved_scope in ("task", "run") else None,
            "policy": policy,
            "validated_host": host,
            "source": source,
            "proof_reference": proof_reference.strip(),
            "updated_at": utc_now(),
        }
        if resolved_scope == "run":
            record["bound_run_id"] = bound_run_id or "next_run"
        record["record_sha256"] = canonical_sha256(record)
        target_file = _policy_file(repo, task_id if resolved_scope in ("task", "run") else None, scope=resolved_scope)
        atomic_write_json(pending_file, operation)
        # The marker survives interruption. Dispatch remains blocked until the same
        # explicit operation has repaired all derived artifacts under this lock.
        atomic_write_json(target_file, record)

        if resolved_scope == "task" and task_id:
            # A task-wide choice supersedes any prior one-time run file on this task.
            _policy_file(repo, task_id, scope="run").unlink(missing_ok=True)

        if str(host).strip().lower() == "antigravity":
            efforts = _compute_efforts_by_role(repo, task_id, list(CORE_ROUTED_REVIEWERS))
            resolved_all = _resolve_policy(policy, resolved_scope, host, list(CORE_ROUTED_REVIEWERS), efforts_by_role=efforts)
            sync_antigravity_agent_models(repo, resolved_all.get("reviewers") or {})

        if task_id:
            refreshed = _refresh_undispatched_runs(repo, task_id, host)
            if refreshed:
                record["refreshed_run"] = refreshed

        pending_file.unlink()
        return record


def main(argv: list[str] | None = None) -> int:
    from _vnext_common import configure_utf8_output
    configure_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("show", "set"), nargs="?", default="show")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", "--task-id", dest="task")
    parser.add_argument("--host")
    parser.add_argument("--choice", help="Interactive choice ID (e.g. flash-dynamic-task, flash-dynamic-once, inherit-task, inherit-once, hybrid-smart-task)")
    parser.add_argument("--preset", choices=("flash-dynamic", "inherit", "hybrid-smart", "flash", "hybrid"), help="Preset reviewer model profile")
    parser.add_argument("--scope", choices=("project", "task", "run"), default=None, help="Policy persistence scope (project, task, or run/once)")
    parser.add_argument("--default", default="inherit", help="Default reviewer model or model@effort")
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
            scope = args.scope
            if args.choice:
                policy, choice_scope = resolve_interactive_choice(args.choice)
                scope = scope or choice_scope
            elif args.preset:
                policy = resolve_preset_policy(args.preset)
            else:
                overrides = {}
                for item in args.reviewer:
                    role, sep, model = item.partition("=")
                    if not sep or role in overrides:
                        raise ValidationError("--reviewer requires unique ROLE=MODEL entries")
                    overrides[role] = normalize_model_token(model)
                policy = {
                    "schema_version": 1,
                    "default": normalize_model_token(args.default),
                    "overrides": overrides,
                }
            result = set_policy(
                repo,
                policy,
                task_id=args.task,
                host=host,
                source=args.source,
                proof_reference=args.proof_reference,
                scope=scope,
            )
            result["applies_to"] = (
                "current review run only; subsequent review runs will prompt again"
                if result.get("scope") == "run"
                else "all review runs in this task"
                if result.get("scope") == "task"
                else "future review runs across the project; existing runs are unchanged"
            )
            if str(host).strip().lower() == "antigravity":
                result["dispatch_hint"] = (
                    "When calling invoke_subagent, pass Model='flash' for every reviewer whose model in reviewer_models is gemini-3.8-flash-*, "
                    "and omit Model (INHERIT_PARENT_BY_OMISSION) for reviewers set to inherit."
                )
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
