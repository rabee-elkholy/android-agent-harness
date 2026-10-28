"""Readable plan document generated from the registered plan.

`plan.md` sits next to `plan.json` and is rewritten from it on every draft and
revise, so it never drifts from what the developer approves. It is derived,
never hand-authored: the plan hash it shows is the plan's own hash.
"""
from __future__ import annotations

import json
import re
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


def _classify_file_layer(rel_path: str) -> str:
    norm = rel_path.replace("\\", "/").lower()
    if "/test/" in norm or "/androidtest/" in norm or norm.endswith("test.kt") or norm.endswith("test.java"):
        return "Test"
    if "/res/values" in norm and "strings.xml" in norm:
        return "Localization"
    if "/res/navigation/" in norm:
        return "Navigation"
    if "/res/" in norm or norm.endswith(".xml"):
        return "Resources / XML"
    if norm.endswith(("build.gradle", "build.gradle.kts", "libs.versions.toml", "settings.gradle", "settings.gradle.kts")):
        return "Build / Config"
    if "viewmodel" in norm or "presenter" in norm or "state" in norm:
        return "Presentation / State"
    if "/ui/" in norm or "fragment" in norm or "activity" in norm or "screen" in norm or "sheet" in norm or "dialog" in norm:
        return "UI / Screen"
    if "/data/" in norm or "repo" in norm or "datasource" in norm or "dao" in norm or "entity" in norm or "model" in norm:
        return "Data / Domain"
    return "Source"


def _split_inline_numbered_steps(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    # Split inline "1. ... 2. ... 3. ..." while preserving single-sentence text when not numbered
    parts = [p.strip() for p in re.split(r"(?:^|\s+)(?=\d+\.\s+)", text) if p.strip()]
    if len(parts) > 1 and all(re.match(r"^\d+\.\s+", p) for p in parts):
        return parts
    # Also support newline-separated steps
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        return lines
    return [text]


def _format_structured_block(value: Any, *, default: str = "not stated", checklist: bool = False) -> list[str]:
    text = _text(value, default=default)
    if text == default:
        return [text]
    steps = _split_inline_numbered_steps(text)
    if len(steps) == 1 and not checklist and not re.match(r"^\d+\.\s+", steps[0]):
        return [steps[0]]
    out: list[str] = []
    for step in steps:
        if checklist:
            body = re.sub(r"^\d+\.\s+", "", step).strip()
            if "->" in body:
                action_part, expected_part = body.split("->", 1)
                expected_clean = re.sub(r"^expected\s*:\s*", "", expected_part.strip(), flags=re.IGNORECASE)
                out.append(f"- [ ] {step}")
                out.append(f"  - **Action**: {action_part.strip()}")
                out.append(f"  - **Expected**: {expected_clean}")
            else:
                out.append(f"- [ ] {step}")
        else:
            out.append(step if re.match(r"^\d+\.\s+", step) else f"- {step}")
    return out


def _render_files_section(repo: Path, files: list[str]) -> list[str]:
    if not files:
        return ["- not stated"]
    rows = [
        "| # | Layer | File (Full Path Link) |",
        "| :---: | :--- | :--- |",
    ]
    for idx, item in enumerate(files, 1):
        layer = _classify_file_layer(str(item))
        rows.append(f"| {idx} | `{layer}` | {_file_link(repo, str(item))} |")
    return rows


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

    SENSITIVE_SURFACES = {"BILLING", "AUTH", "SECURITY", "SENSITIVE_DATA", "CRYPTO"}

    policy = policy or {}
    plan_hash = str(plan.get("plan_sha256") or "")
    files = plan.get("expected_files") or []
    phases = plan.get("phases") or []
    surfaces = plan.get("expected_surfaces") or []
    sensitive = sorted(set(surfaces) & SENSITIVE_SURFACES)
    modules_str = ", ".join(plan.get("expected_modules") or []) or "not stated"
    risk_tier = str(policy.get("risk_tier") or "evaluated at verification")
    task_kind = str(plan.get("task_kind") or "AUTO")
    planning_depth = str(plan.get("planning_depth") or "BOUNDED")

    lines = [
        f"# Plan: {plan.get('task_id')}",
        "",
        f"Plan hash: `{plan_hash[:12]}` (the hash the approval is bound to). Generated from `plan.json`; do not edit.",
        "",
        "| Field | Value |",
        "| :--- | :--- |",
        f"| **Task Kind / Depth** | `{task_kind}` (`{planning_depth}`) |",
        f"| **Risk Tier** | `{risk_tier}` |",
        f"| **Planned Files** | `{len(files)}` file(s) across `{modules_str}` |",
        f"| **Phases** | `{len(phases) if phases else 1}` phase(s) |",
        f"| **Sensitive Surfaces** | {', '.join(f'`{s}`' for s in sensitive) if sensitive else 'None'} |",
        "",
    ]
    if plan.get("merge", {}).get("merged_into"):
        lines += [
            "> [!WARNING]",
            f"> This source task is CANCELLED after consolidation into `{plan['merge']['merged_into']}`. This document preserves its original plan; it grants no execution authority.",
            "",
        ]
    if plan.get("merged_from"):
        lines += ["Source plans (execution order): " + ", ".join(f"`{p['task_id']}` (`{p['plan_sha256'][:12]}`)" for p in plan["merged_from"]), ""]
    if previous:
        lines += [
            f"## What changed from the previous plan (`{str(previous.get('plan_sha256') or '')[:12]}`)",
            "",
            "> [!IMPORTANT]",
            "> Review the delta below against the previous plan version.",
            "",
            *_changes(previous, plan),
            "",
        ]
        if plan.get("material_change_reason"):
            lines += ["Reason for changed requirements: " + _text(plan["material_change_reason"]), ""]
    lines += [
        "## Outcome",
        "",
        f"> **Goal:** {_text(plan.get('requested_outcome'))}",
        "",
        "## Approach",
        "",
        *_format_structured_block(plan.get("approach")),
        "",
        f"## Files ({len(files)})",
        "",
        *_render_files_section(repo, files),
    ]
    reuse_cands = [c for c in (plan.get("reuse_candidates") or []) if isinstance(c, dict)]
    if reuse_cands:
        lines += ["", "## Existing codebase reuse candidates", ""]
        for cand in reuse_cands[:8]:
            existing_rel = str(cand.get("existing_file") or "")
            link = _file_link(repo, existing_rel) if existing_rel else "unknown"
            lines.append(
                f"- Planned `{cand.get('planned_file', '')}` overlaps existing `{cand.get('symbol', '')}` in {link} ({cand.get('kind', 'symbol')})"
            )
    readiness = plan.get("readiness_assessment") or {}
    if isinstance(readiness, dict) and readiness.get("advisories"):
        lines += ["", "## Architecture & spec readiness advisories", ""]
        for adv in readiness.get("advisories") or []:
            lines.append(f"- {redact(adv)}")
    if phases:
        lines += ["", "## Phases", ""]
        for index, phase in enumerate(phases, 1):
            if isinstance(phase, dict):
                title = phase.get("title") or phase.get("description") or ""
                lines.append(f"{index}. **`{phase.get('id')}`** — {_text(title, '')}")
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
    lines += [
        "",
        "## Risks",
        "",
    ]
    raw_risks = plan.get("risks") or []
    if raw_risks:
        for item in raw_risks:
            for r_line in _split_inline_numbered_steps(str(redact(item))):
                clean_r = re.sub(r"^\d+\.\s+", "", r_line).strip()
                lines.append(f"- {clean_r}")
    else:
        lines.append("- None stated in the plan.")
    notes = [SURFACE_NOTES[s] for s in surfaces if s in SURFACE_NOTES]
    if notes:
        lines += ["", "> [!CAUTION]", "> **Harness notes for this kind of change:**"] + [f"> - {note}" for note in notes]
    try:
        from project_context import load_project_notes
        notes_info = load_project_notes(repo)
        if notes_info.get("has_custom_notes"):
            lines += ["", "## Project notes and conventions", ""]
            lines.append(f"- Mandatory repo conventions: {_file_link(repo, notes_info['path'])}")
            for sec in notes_info.get("sections") or []:
                lines.append(f"  - {redact(sec)}")
    except (ImportError, OSError, ValueError, KeyError):
        notes_info = {}
    lines += [
        "",
        "## Tests",
        "",
        f"- {_text(plan.get('test_strategy'))}",
        "",
        "## Phone checks",
        "",
    ]
    device = str(plan.get("device_strategy") or "")
    if device and device != DEFAULT_DEVICE_STRATEGY:
        lines += _format_structured_block(device, checklist=True)
    elif policy.get("device_required"):
        lines.append("Not stated yet: the plan does not list the steps the developer will check on the phone.")
    else:
        lines.append("No phone check is expected for this change.")
    gates = policy.get("gates") or []
    reviewers = policy.get("reviewers") or []
    lines += ["", "## What the harness will check", ""]
    lines += [f"- {GATE_TEXT.get(g, g)}" for g in gates] or ["- Decided when verification starts."]
    if reviewers:
        lines.append(f"- **Reviewers ({len(reviewers)})**: " + ", ".join(f"`{r}`" for r in reviewers) + ".")
    from review_models import model_choice_summary
    lines.append("- " + model_choice_summary(repo, str(plan.get("task_id") or "")))
    if plan.get("review_budget_forecast"):
        from review_budget import forecast_summary
        lines += ["", "## Reviewer spending estimate (advisory)", "", forecast_summary(plan["review_budget_forecast"])]
    lines += [
        "",
        "## What needs you",
        "",
        "- [ ] Approve this plan (or ask for changes).",
    ]
    if "device" in gates:
        lines.append("- [ ] Check the phone steps above and sign off Pass or Fail.")
    if "verification_contract" in plan:
        lines.append("- [ ] Approve the listed criteria and selected journey effects with this plan. Manual checks must name the checked criteria at sign-off.")
    lines += [
        "- [ ] Commit the changes yourself; the agent never commits or pushes.",
        "",
        "## Rollback",
        "",
        _text(plan.get("rollback")),
        "",
        "## Modules and surfaces",
        "",
        f"- **Modules**: {modules_str}",
        f"- **Surfaces**: {', '.join(f'`{s}`' for s in surfaces) or 'not stated'}",
        f"- **External writes**: {', '.join(plan.get('external_writes') or []) or 'none'}",
        "",
        "## Full approval payload (redacted)",
        "",
        "<details>",
        "<summary>Click to expand raw JSON payload (covered by plan hash)</summary>",
        "",
        "Everything below is covered by the plan hash.",
        "",
        "```json",
        json.dumps(redact(plan_payload(plan)), ensure_ascii=False, sort_keys=True, indent=2),
        "```",
        "</details>",
        "",
    ]
    return "\n".join(lines)


def write_plan_document(repo: Path, task_directory: Path, plan: dict, *, policy: dict | None = None, previous: dict | None = None) -> Path:
    path = plan_document_path(task_directory)
    from plan_notes import note_section
    document = render_plan_document(repo, plan, policy=policy, previous=previous)
    atomic_write_bytes(path, (document + note_section(task_directory, plan)).encode("utf-8"))
    return path
