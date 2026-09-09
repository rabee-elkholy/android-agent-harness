"""Plan-aware mutation barrier shared by host hook adapters."""
from __future__ import annotations

import re
from pathlib import Path

from _vnext_common import ValidationError, read_json
from plan_authority import require_mutation


READ_ONLY_COMMANDS = (
    re.compile(r"^\s*(?:git\s+)?(?:status|diff|log|show|ls-files|rev-parse)\b", re.I),
    re.compile(r"^\s*git\s+(?:-C\s+(?:\"[^\"]+\"|\S+)\s+)?(?:status|diff|log|show|ls-files|rev-parse|symbolic-ref|check-ignore|describe)\b", re.I),
    re.compile(r"^\s*(?:rg|grep|sed|head|tail|ls|pwd|wc)\b", re.I),
    re.compile(r"^\s*(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?\s+(?:\"[^\"]*(?:project_graph|harness_doctor|change_classifier|review_policy|delivery_manifest)\.py\"|\S*(?:project_graph|harness_doctor|change_classifier|review_policy|delivery_manifest)\.py)\b(?!.*--output)", re.I),
    re.compile(r"^\s*(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?\s+(?:\"[^\"]*setup_wizard\.py\"|\S*setup_wizard\.py)\s+questions\b", re.I),
    re.compile(r"^\s*(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?\s+(?:\"[^\"]*harness_cli\.py\"|\S*harness_cli\.py)\s+(?:version|doctor|explain)\b", re.I),
    re.compile(r"^\s*(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?\s+(?:\"[^\"]*harness_cli\.py\"|\S*harness_cli\.py)(?:\s+\w+)?\s+--help\s*$", re.I),
)
VERIFY_COMMANDS = re.compile(
    r"(?:run_gradle_task|run_tests_gate|preflight_check|review_package|final_verifier|check_strings|room_guard|fast_kt_lint|run_device)\.py|workflow\.py\s+(?:verify|complete)\b|harness_cli\.py\s+verify\b",
    re.I,
)
BOOTSTRAP_WORKFLOW = re.compile(
    r"(?:workflow\.py|android-harness\s+task)\s+(?:draft|begin|status)\b",
    re.I,
)
LIFECYCLE_COMMANDS = (
    re.compile(r"^\s*(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?\s+(?:\"[^\"]*harness_cli\.py\"|\S*harness_cli\.py)\s+(?:init|update|uninstall)\b", re.I),
    re.compile(r"^\s*(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?\s+(?:\"[^\"]*setup_wizard\.py\"|\S*setup_wizard\.py)\s+write\b", re.I),
    re.compile(r"^\s*git\s+clone\s+.*(?:\.android-harness|kit-stage)", re.I),
)
SHELL_LAUNDERING = re.compile(r"`|\$\(|[<>]|(?<!\|)\|(?!\|)")


def _is_read_only(command: str) -> bool:
    # Prefix matching must never bless a later mutating segment.
    if SHELL_LAUNDERING.search(command):
        return False
    segments = [item.strip() for item in re.split(r"(?:&&|\|\||;|\r?\n)", command) if item.strip()]
    return bool(segments) and all(any(pattern.search(item) for pattern in READ_ONLY_COMMANDS) for item in segments)


def _is_lifecycle_command(command: str) -> bool:
    if SHELL_LAUNDERING.search(command):
        return False
    segments = [item.strip() for item in re.split(r"(?:&&|\|\||;|\r?\n)", command) if item.strip()]
    return bool(segments) and all(any(pattern.search(item) for pattern in LIFECYCLE_COMMANDS) for item in segments)


def _state_root(repo: Path) -> Path:
    installed = repo / ".agents" / "state"
    return installed if installed.parent.is_dir() else repo / "agents" / "state"


def active_plan(repo: Path) -> dict:
    state = _state_root(repo)
    active = read_json(state / "active-task.json")
    plan_path = Path(str(active.get("plan_path") or ""))
    if not plan_path.is_absolute():
        plan_path = repo / plan_path
    plan_resolved = plan_path.resolve()
    state_resolved = state.resolve()
    if state_resolved != plan_resolved and state_resolved not in plan_resolved.parents:
        raise ValidationError("active plan path escapes harness state")
    return read_json(plan_resolved)


def file_mutation_allowed(repo: Path) -> tuple[bool, str]:
    try:
        plan = active_plan(repo)
        require_mutation(plan)
    except ValidationError as exc:
        return False, str(exc)
    return True, f"mutation authorized by approved plan {plan.get('plan_id')}"


def command_allowed(repo: Path, command: str) -> tuple[bool, str]:
    normalized = str(command or "").strip()
    if not normalized:
        return True, "empty command"
    if SHELL_LAUNDERING.search(normalized):
        return False, "shell redirection, piping, or command substitution is outside the read-only boundary"
    if BOOTSTRAP_WORKFLOW.search(normalized):
        return True, "task-authority workflow command"
    if _is_read_only(normalized):
        return True, "read-only inspection command"
    if _is_lifecycle_command(normalized):
        return True, "harness lifecycle engine command"
    try:
        plan = active_plan(repo)
    except ValidationError as exc:
        return False, f"mutation requires an active approved plan: {exc}"
    status = str(plan.get("status") or "")
    if status == "IMPLEMENTING":
        try:
            require_mutation(plan)
        except ValidationError as exc:
            return False, str(exc)
        return True, f"command authorized by approved plan {plan.get('plan_id')}"
    if status == "VERIFYING" and VERIFY_COMMANDS.search(normalized):
        return True, f"verification command authorized for plan {plan.get('plan_id')}"
    if status == "BLOCKED" and re.search(r"workflow\.py\s+resume\b", normalized, re.I):
        return True, f"resume authorized for blocked plan {plan.get('plan_id')}"
    return False, f"command is not allowed while plan status is {status or 'missing'}"
