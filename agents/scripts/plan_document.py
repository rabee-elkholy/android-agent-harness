"""Readable plan document generated from the registered plan.

`plan.md` sits next to `plan.json` and is rewritten from it on every draft and
revise, so it never drifts from what the developer approves. It is derived,
never hand-authored: the plan hash it shows is the plan's own hash.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _vnext_common import atomic_write_bytes, redact

PLAN_DOCUMENT_NAME = "plan.md"
DEFAULT_TEST_STRATEGY = "Policy-selected relevant tests"
DEFAULT_DEVICE_STRATEGY = "Policy-selected device verification"

GATE_TEXT = {
    "preflight": "Preflight: hook selftest, string parity, Room migration gate, fast Kotlin lint, plan authority, architecture drift, exported components.",
    "localization": "Localization: English/Arabic string parity and no hardcoded user-facing text.",
    "room": "Room: schema change needs a version bump and a migration; a pre-existing destructive fallback is reported as a warning.",
    "manifest": "Manifest: only the planned files may change.",
    "unit_tests": "Unit tests of the changed modules (failures already in the baseline are ignored).",
    "assemble": "Build the debug APK.",
    "device": "Install on the connected phone; the developer does the phone checks above and signs off.",
}

SURFACE_NOTES = {
    "MANIFEST_PERMISSION": "A newly exported component without a permission stops at preflight until the developer accepts it in their own terminal.",
    "ROOM_SCHEMA": "Database schema change: existing users are upgraded by the migration, so it must keep their data.",
}


def plan_document_path(task_directory: Path) -> Path:
    return task_directory / PLAN_DOCUMENT_NAME


def plan_gaps(plan: dict) -> list[str]:
    """Fields the developer cannot review because the plan does not state them."""
    gaps = []
    if not str(plan.get("approach") or "").strip():
        gaps.append("approach")
    if not plan.get("risks"):
        gaps.append("risks")
    if str(plan.get("device_strategy") or "").strip() in ("", DEFAULT_DEVICE_STRATEGY):
        gaps.append("device checks")
    return gaps


def _text(value: Any, default: str = "not stated") -> str:
    if value in (None, "", [], {}):
        return default
    return str(redact(value))


def _file_link(repo: Path, relative: str) -> str:
    target = (repo / relative).resolve()
    return f"[{relative}]({target.as_uri()})"


def _changes(old: dict | None, new: dict) -> list[str]:
    if not old:
        return []
    labels = {
        "requested_outcome": "Outcome",
        "approach": "Approach",
        "expected_files": "Files",
        "expected_modules": "Modules",
        "expected_surfaces": "Surfaces",
        "test_strategy": "Tests",
        "device_strategy": "Device checks",
        "risks": "Risks",
        "rollback": "Rollback",
        "external_writes": "External writes",
        "phases": "Phases",
        "verification_contract": "Acceptance criteria and journeys",
    }
    lines = []
    for key, label in labels.items():
        before, after = old.get(key), new.get(key)
        if isinstance(before, list) and isinstance(after, list):
            added = [str(v) for v in after if v not in before]
            removed = [str(v) for v in before if v not in after]
            if added or removed:
                parts = []
                if added:
                    parts.append("added " + ", ".join(str(redact(v)) for v in added))
                if removed:
                    parts.append("removed " + ", ".join(str(redact(v)) for v in removed))
                lines.append(f"- {label}: {'; '.join(parts)}")
        elif (before or "") != (after or ""):
            lines.append(f"- {label}: {_text(before, 'none')} → {_text(after, 'none')}")
    return lines or ["- No reviewable field changed (binding or tree state only)."]


def render_plan_document(repo: Path, plan: dict, *, policy: dict | None = None, previous: dict | None = None) -> str:
    from plan_authority import plan_payload

    policy = policy or {}
    plan_hash = str(plan.get("plan_sha256") or "")
    lines = [
        f"# Plan: {plan.get('task_id')}",
        "",
        f"Plan hash: `{plan_hash[:12]}` (the hash the approval is bound to). Generated from `plan.json`; do not edit.",
        "",
    ]
    if previous:
        lines += [
            f"## What changed from the previous plan (`{str(previous.get('plan_sha256') or '')[:12]}`)",
            "",
            *_changes(previous, plan),
            "",
        ]
    lines += [
        "## Outcome",
        "",
        _text(plan.get("requested_outcome")),
        "",
        "## Approach",
        "",
        _text(plan.get("approach")),
        "",
        "## Files",
        "",
    ]
    files = plan.get("expected_files") or []
    lines += [f"- {_file_link(repo, item)}" for item in files] or ["- not stated"]
    phases = plan.get("phases") or []
    if phases:
        lines += ["", "## Phases", ""]
        for index, phase in enumerate(phases, 1):
            if isinstance(phase, dict):
                title = phase.get("title") or phase.get("description") or ""
                lines.append(f"{index}. `{phase.get('id')}`: {_text(title, '')}")
                for item in phase.get("expected_files") or []:
                    lines.append(f"   - {_file_link(repo, item)}")
    if "verification_contract" in plan:
        value = plan["verification_contract"]
        lines += ["", "## Acceptance criteria and evidence", ""]
        if value.get("device_validation") == "manual_or_automatic":
            lines.append("Device validation: the selected journeys define the complete walkthrough. After install, choose manual PASS/FAIL or Run Automatically; automatic PASS replaces manual repetition. Sensitive approval remains separate.")
        for criterion in value["criteria"]:
            obligation = "required" if criterion["required"] else "advisory"
            lines.append(f"- `{criterion['id']}` ({obligation}, {criterion['method']}): {_text(criterion['expected'])}")
        for journey in value["journeys"]:
            lines.append(f"- Journey `{journey['id']}` v{journey['version']}, {journey['module']}/{journey['variant']}: "
                         f"{_text(journey['purpose'])}; prerequisites: {_text(journey['prerequisites'])}; "
                         f"effects: {_text(journey['effects'], 'none')}")
        lines.append("Evidence association records provenance; reviewers still assess semantic relevance.")
    surfaces = plan.get("expected_surfaces") or []
    lines += [
        "",
        "## Risks",
        "",
    ]
    lines += [f"- {redact(item)}" for item in plan.get("risks") or []] or ["- None stated in the plan."]
    notes = [SURFACE_NOTES[s] for s in surfaces if s in SURFACE_NOTES]
    if notes:
        lines += ["", "Harness notes for this kind of change:", ""] + [f"- {note}" for note in notes]
    lines += [
        "",
        "## Tests",
        "",
        _text(plan.get("test_strategy")),
        "",
        "## Phone checks",
        "",
    ]
    device = str(plan.get("device_strategy") or "")
    if device and device != DEFAULT_DEVICE_STRATEGY:
        lines.append(_text(device))
    elif policy.get("device_required"):
        lines.append("Not stated yet: the plan does not list the steps the developer will check on the phone.")
    else:
        lines.append("No phone check is expected for this change.")
    gates = policy.get("gates") or []
    reviewers = policy.get("reviewers") or []
    lines += ["", "## What the harness will check", ""]
    lines += [f"- {GATE_TEXT.get(g, g)}" for g in gates] or ["- Decided when verification starts."]
    if reviewers:
        lines.append(f"- Reviewers: {', '.join(reviewers)}.")
    lines += [
        "",
        "## What needs you",
        "",
        "- Approve this plan (or ask for changes).",
    ]
    if "device" in gates:
        lines.append("- Check the phone steps above and sign off Pass or Fail.")
    if "verification_contract" in plan:
        lines.append("- Approve the listed criteria and selected journey effects with this plan. Manual checks must name the checked criteria at sign-off.")
    lines += [
        "- Commit the changes yourself; the agent never commits or pushes.",
        "",
        "## Rollback",
        "",
        _text(plan.get("rollback")),
        "",
        "## Modules and surfaces",
        "",
        f"- Modules: {', '.join(plan.get('expected_modules') or []) or 'not stated'}",
        f"- Surfaces: {', '.join(surfaces) or 'not stated'}",
        f"- External writes: {', '.join(plan.get('external_writes') or []) or 'none'}",
        "",
        "## Full approval payload (redacted)",
        "",
        "Everything below is covered by the plan hash.",
        "",
        "```json",
        json.dumps(redact(plan_payload(plan)), ensure_ascii=False, sort_keys=True, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def write_plan_document(repo: Path, task_directory: Path, plan: dict, *, policy: dict | None = None, previous: dict | None = None) -> Path:
    path = plan_document_path(task_directory)
    atomic_write_bytes(path, render_plan_document(repo, plan, policy=policy, previous=previous).encode("utf-8"))
    return path
