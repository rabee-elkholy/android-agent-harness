"""Plan-aware mutation barrier shared by host hook adapters."""
from __future__ import annotations

import re
import os
from pathlib import Path

from _vnext_common import ValidationError, read_json
from plan_authority import require_mutation


INSPECTION_SCRIPTS = {"project_graph", "harness_doctor", "change_classifier", "review_policy", "delivery_manifest"}
VERIFICATION_SCRIPTS = {
    "run_gradle_task", "run_tests_gate", "preflight_check", "review_package",
    "record_review", "final_verifier", "final_verdict", "check_strings",
    "room_guard", "perf_guard", "fast_kt_lint", "run_device", "capture_screen", "logcat_doctor",
}
BOOTSTRAP_ACTIONS = {"draft", "begin", "status", "approve", "approve-sensitive", "deliver", "debug-evidence"}
SHELL_LAUNDERING = re.compile(r"`|\$|[<>^]|(?<!\|)\|(?!\|)|(?<!&)&(?!&)")


def _tokens(command: str) -> list[str]:
    # Windows paths must retain backslashes. Reject ambiguous shell syntax;
    # these exemptions are intentionally narrower than a general shell parser.
    import shlex
    try:
        values = shlex.split(command, posix=False)
    except ValueError:
        return []
    return [value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" else value for value in values]


def _trusted_script(path: str, repo: Path | str, name: str) -> bool:
    root = Path(repo).resolve()
    script = Path(path)
    resolved = (script if script.is_absolute() else root / script).resolve()
    here = Path(__file__).resolve().parent
    if name != "harness_cli.py" and resolved in {root / ".agents/scripts" / name, here / name}:
        return True
    if name == "harness_cli.py" and here.parent.name == "agents" and resolved == here.parents[1] / name:
        return True
    configured = os.environ.get("HARNESS_KIT", "").strip()
    if configured:
        kit = Path(configured).expanduser().resolve()
        expected = kit / name if name == "harness_cli.py" else kit / "agents/scripts" / name
        if resolved == expected:
            return True
    # Installer entry points also live in the user's pinned kit cache. Resolve
    # first so traversal and symlinks cannot escape the expected script path.
    cache = (Path.home() / ".android-harness").resolve()
    try:
        parts = resolved.relative_to(cache).parts
    except ValueError:
        return False
    if not parts or not (parts[0] == "kit" or parts[0].startswith("kit-stage-")):
        return False
    expected = (name,) if name == "harness_cli.py" else ("agents", "scripts", name)
    return parts[1:] == expected


def _entry(command: str, repo: Path | str = ".") -> tuple[str, list[str]]:
    tokens = _tokens(command)
    if not tokens:
        return "", []
    executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if re.fullmatch(r"(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?", executable):
        if len(tokens) < 2:
            return "", []
        path = tokens[1].replace("\\", "/")
        name = path.rsplit("/", 1)[-1]
        known = INSPECTION_SCRIPTS | VERIFICATION_SCRIPTS | {"workflow", "setup_wizard"}
        if not _trusted_script(path, repo, name):
            return "", []
        if name == "harness_cli.py":
            return "harness_cli", tokens[2:]
        if name.endswith(".py") and name[:-3] in known:
            return name[:-3], tokens[2:]
        return "", []
    if executable in {"git", "rg", "grep", "head", "tail", "ls", "pwd", "wc", "android-harness"}:
        return executable, tokens[1:]
    return "", []


def _is_read_only(command: str, repo: Path | str = ".") -> bool:
    name, args = _entry(command, repo)
    if name == "git":
        if args[:1] == ["-C"] and len(args) >= 3:
            args = args[2:]
        if not args or args[0] not in {"status", "diff", "log", "show", "ls-files", "rev-parse", "symbolic-ref", "check-ignore", "describe"}:
            return False
        if any(arg.startswith(("--output", "--ext-diff", "--textconv")) for arg in args[1:]):
            return False
        if args[0] == "symbolic-ref":
            return len(args) == 2 and not args[1].startswith("-")
        return True
    if name in {"rg", "grep", "head", "tail", "ls", "pwd", "wc"}:
        return not any(arg.startswith(("--pre", "--hostname-bin")) for arg in args)
    if name in INSPECTION_SCRIPTS:
        return not any(arg.startswith("--out") for arg in args)
    if name == "setup_wizard" and args[:1] == ["questions"]:
        return True
    if name == "harness_cli" and args[:1] in (["version"], ["doctor"], ["explain"]):
        return True
    # Only known harness parsers implement help without running arbitrary code.
    return name in INSPECTION_SCRIPTS | VERIFICATION_SCRIPTS | {"workflow", "setup_wizard", "harness_cli"} and bool(args) and args[-1] in {"--help", "-h"}


def _is_lifecycle_command(command: str, repo: Path | str = ".") -> bool:
    name, args = _entry(command, repo)
    return (
        name == "harness_cli" and args[:1] in (["init"], ["update"], ["uninstall"])
        or name == "setup_wizard" and args[:1] == ["write"]
        or name == "git" and args[:1] == ["clone"] and len(args) >= 3
        and ("/.android-harness/" in args[-1].replace("\\", "/") or Path(args[-1]).name.startswith("kit-stage"))
    )


def _workflow_action(command: str, repo: Path | str = ".") -> str:
    name, args = _entry(command, repo)
    if name == "workflow":
        return args[0] if args else ""
    if name in {"android-harness", "harness_cli"} and args[:1] == ["task"]:
        return args[1] if len(args) > 1 else ""
    return ""


def _state_root(repo: Path | str) -> Path:
    repo_path = Path(repo)
    installed = repo_path / ".agents" / "state"
    return installed if installed.parent.is_dir() else repo_path / "agents" / "state"


def active_plan(repo: Path | str) -> dict:
    repo_path = Path(repo)
    state = _state_root(repo_path)
    active = read_json(state / "active-task.json")
    plan_path = Path(str(active.get("plan_path") or ""))
    if not plan_path.is_absolute():
        plan_path = repo_path / plan_path
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


def command_allowed(repo: Path | str, command: str) -> tuple[bool, str]:
    if isinstance(repo, str) and (isinstance(command, Path) or (" " in repo and not " " in str(command))):
        repo, command = command, repo
    normalized = str(command or "").strip()
    if not normalized:
        return True, "empty command"
    if SHELL_LAUNDERING.search(normalized):
        return False, "shell redirection, piping, or command substitution is outside the read-only boundary"
    segments = [item.strip() for item in re.split(r"(?:&&|\|\||;|\r?\n)", normalized) if item.strip()]
    if len(segments) > 1:
        decisions = [command_allowed(repo, item) for item in segments]
        return next((decision for decision in decisions if not decision[0]), (True, "every command segment is authorized"))
    if _workflow_action(normalized, repo) in BOOTSTRAP_ACTIONS:
        return True, "task-authority workflow command"
    if _is_read_only(normalized, repo):
        return True, "read-only inspection command"
    if _is_lifecycle_command(normalized, repo):
        return True, "harness lifecycle engine command"
    try:
        plan = active_plan(repo)
    except ValidationError as exc:
        return False, f"mutation requires an active approved plan: {exc}"
    status = str(plan.get("status") or "")
    if status == "IMPLEMENTING":
        if re.search(r"(?:^|\s|python(?:\d+(?:\.\d+)?)?(?:\.exe)?\s+.*)run_device(?:\.py)?\b", normalized, re.I):
            return False, "Device operation is blocked during IMPLEMENTING. Transition to verification via 'python .agents/scripts/workflow.py prepare-verification' first."
        try:
            require_mutation(plan)
        except ValidationError as exc:
            return False, str(exc)
        return True, f"command authorized by approved plan {plan.get('plan_id')}"
    entry, arguments = _entry(normalized, repo)
    action = _workflow_action(normalized, repo)
    if status == "VERIFYING" and (entry in VERIFICATION_SCRIPTS or action in {"verify", "complete"} or (entry == "harness_cli" and arguments[:1] == ["verify"])):
        return True, f"verification command authorized for plan {plan.get('plan_id')}"
    if status in ("VERIFYING", "BLOCKED") and action == "resume":
        return True, f"resume authorized for {status.lower()} plan {plan.get('plan_id')}"
    return False, f"command is not allowed while plan status is {status or 'missing'}"
