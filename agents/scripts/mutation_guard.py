"""Plan-aware mutation barrier shared by host hook adapters."""
from __future__ import annotations

import re
import os
from pathlib import Path

from _vnext_common import ValidationError, read_json
from plan_authority import require_mutation


INSPECTION_SCRIPTS = {"project_graph", "task_context", "harness_doctor", "change_classifier", "review_policy", "delivery_manifest", "review_execution"}
VERIFICATION_SCRIPTS = {
    "run_gradle_task", "run_tests_gate", "preflight", "preflight_check", "review_package",
    "record_review", "final_verifier", "final_verdict", "check_strings",
    "room_guard", "perf_guard", "fast_kt_lint", "run_device", "capture_screen", "logcat_doctor",
    "phase_review", "task_git_lineage",
}
BOOTSTRAP_ACTIONS = {
    "draft", "revise", "begin", "status", "approve", "approve-sensitive", "prepare-verification",
    "deliver", "debug-evidence", "recover-stale", "recover-active", "validate-finding", "reconcile-delivery",
    "checkpoint-phase", "begin-next-phase", "handoff", "reconcile-handoff",
}
SHELL_LAUNDERING = re.compile(r"`|\$|[<>^]|(?<!\|)\|(?!\|)|(?<!&)&(?!&)")


# Read-only PowerShell cmdlets (Antigravity on Windows runs PowerShell). Pipes,
# redirection and $(...) are rejected before this by SHELL_LAUNDERING.
POWERSHELL_READ_CMDLETS = {"get-childitem", "gci", "dir", "get-content", "gc", "select-string", "sls", "test-path", "get-location"}

# Content-derived surfaces that a pre-edit check must not take from a tracked file's existing text.
PRE_EXISTING_CONTENT_SURFACES = {"AUTH", "BILLING", "SECURITY", "SENSITIVE_DATA", "CRYPTO"}


def _is_tracked(root: Path, rel_posix: str) -> bool:
    import subprocess
    try:
        return subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel_posix],
            cwd=str(root), capture_output=True, check=False, timeout=10,
        ).returncode == 0
    except Exception:
        return False


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
    if name not in {"harness_cli.py", "harness.py"} and resolved in {root / ".agents/scripts" / name, here / name}:
        return True
    if name == "harness_cli.py" and here.parent.name == "agents" and resolved == here.parents[1] / name:
        return True
    if name == "harness.py" and resolved in {root / ".agents/harness.py", root / "agents/harness.py", here.parent / "harness.py"}:
        return True
    configured = os.environ.get("HARNESS_KIT", "").strip()
    if configured:
        kit = Path(configured).expanduser().resolve()
        expected = kit / name if name in {"harness_cli.py", "harness.py"} else kit / "agents/scripts" / name
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
    expected = (name,) if name in {"harness_cli.py", "harness.py"} else ("agents", "scripts", name)
    return parts[1:] == expected


def _entry(command: str, repo: Path | str = ".") -> tuple[str, list[str]]:
    tokens = _tokens(command)
    if not tokens:
        return "", []
    executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if re.fullmatch(r"(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?", executable):
        if len(tokens) < 2:
            return "", []
        if tokens[1] == "-m" and len(tokens) >= 3 and tokens[2] == "compileall":
            return "compileall", tokens[3:]
        path = tokens[1].replace("\\", "/")
        name = path.rsplit("/", 1)[-1]
        known = INSPECTION_SCRIPTS | VERIFICATION_SCRIPTS | {"workflow", "setup_wizard", "repair"}
        if not _trusted_script(path, repo, name):
            return "", []
        if name in {"harness_cli.py", "harness.py"}:
            return "harness_cli", tokens[2:]
        if name.endswith(".py") and name[:-3] in known:
            return name[:-3], tokens[2:]
        return "", []
    if executable in {"git", "rg", "grep", "head", "tail", "ls", "pwd", "wc", "cat", "android-harness", "adb", "test", "["}:
        return executable, tokens[1:]
    if executable in POWERSHELL_READ_CMDLETS:
        return "powershell-read", tokens[1:]
    if executable in {"gradlew", "gradlew.bat", "gradle"}:
        return executable, tokens[1:]
    return "", []


def _is_read_only(command: str, repo: Path | str = ".") -> bool:
    name, args = _entry(command, repo)
    if name == "git":
        if args[:1] == ["-C"] and len(args) >= 3:
            args = args[2:]
        if not args or args[0] not in {"status", "diff", "log", "show", "ls-files", "rev-parse", "symbolic-ref", "check-ignore", "describe", "grep", "blame"}:
            return False
        if any(arg.startswith(("--output", "--ext-diff", "--textconv")) for arg in args[1:]):
            return False
        # git grep -O/--open-files-in-pager runs an arbitrary program.
        if args[0] == "grep" and any(arg.startswith("--open") or (arg[:2] != "--" and arg.startswith("-") and "O" in arg) for arg in args[1:]):
            return False
        if args[0] == "symbolic-ref":
            return len(args) == 2 and not args[1].startswith("-")
        return True
    if name == "adb":
        if not args:
            return False
        sub = args[0].lower()
        if sub in {"logcat", "devices", "version", "help"}:
            return not any(arg.startswith(("-f", "--filename")) for arg in args)
        if sub == "shell" and len(args) >= 2 and args[1].lower() in {"getprop", "dumpsys"}:
            return True
        return False
    if name in {"gradlew", "gradlew.bat", "gradle"}:
        return bool(args) and args[0].lower() in {"dependencies", "tasks", "projects", "properties", "help", "--help", "-h"}
    if name == "powershell-read":
        return True
    if name in {"test", "["}:
        # File tests (`test -f x`, `[ -d x ]`) only read; operators around them are checked as segments.
        return name == "test" or args[-1:] == ["]"]
    if name in {"rg", "grep", "head", "tail", "ls", "pwd", "wc", "cat"}:
        return not any(arg.startswith(("--pre", "--hostname-bin")) for arg in args)
    if name == "compileall":
        return True
    if name in INSPECTION_SCRIPTS:
        if name == "task_context":
            targets = sum(1 for arg in args if arg in {"--file", "--symbol"})
            return targets == 1 and not any(arg.startswith("--out") for arg in args)
        return not any(arg.startswith("--out") for arg in args)
    if name == "setup_wizard" and args[:1] == ["questions"]:
        return True
    if name in {"harness_cli", "android-harness"}:
        if args[:1] in (["version"], ["doctor"], ["explain"]):
            return True
        if args[:1] == ["task-context"]:
            targets = sum(1 for arg in args if arg in {"--file", "--symbol"})
            return targets == 1 and not any(arg.startswith("--out") for arg in args)
        if args[:2] in (["context", "preview"], ["context", "status"]):
            return True
        # `graph` forwards to project_graph.py and gets the same read-only rule.
        if args[:1] == ["graph"]:
            return not any(arg.startswith("--out") for arg in args)
    # Only known harness parsers implement help without running arbitrary code.
    return name in INSPECTION_SCRIPTS | VERIFICATION_SCRIPTS | {"workflow", "setup_wizard", "harness_cli", "android-harness"} and bool(args) and args[-1] in {"--help", "-h"}


def _is_harness_cache_path(raw: str) -> bool:
    cache = (Path.home() / ".android-harness").resolve()
    clean = os.path.expandvars(str(raw).strip().strip('"\''))
    candidate = Path(clean).expanduser()
    if not candidate.is_absolute():
        candidate = candidate.resolve()
    else:
        candidate = candidate.resolve()
    try:
        rel = candidate.relative_to(cache)
    except ValueError:
        return False
    if not rel.parts:
        return False
    first = rel.parts[0]
    return (
        first == "kit"
        or first.startswith("kit-stage-")
        or first.startswith("staging_")
    )


def _is_lifecycle_command(command: str, repo: Path | str = ".") -> bool:
    name, args = _entry(command, repo)
    return (
        name in {"harness_cli", "android-harness"} and args[:1] in (["init"], ["update"], ["uninstall"], ["repair"])
        or name in {"harness_cli", "android-harness"} and args[:2] == ["context", "note"]
        or name == "repair"
        or name == "setup_wizard" and args[:1] == ["write"]
        or name == "git" and args[:1] == ["clone"] and len(args) >= 3
        and _is_harness_cache_path(args[-1])
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
    active_file = state / "active-task.json"
    if active_file.is_file():
        try:
            active = read_json(active_file)
            plan_path = Path(str(active.get("plan_path") or ""))
            if not plan_path.is_absolute():
                plan_path = repo_path / plan_path
            plan_resolved = plan_path.resolve()
            state_resolved = state.resolve()
            if state_resolved != plan_resolved and state_resolved not in plan_resolved.parents:
                raise ValidationError("active plan path escapes harness state")
            if plan_resolved.is_file():
                return read_json(plan_resolved)
        except ValidationError:
            raise
        except Exception:
            pass

    tasks_dir = state / "tasks"
    if tasks_dir.is_dir():
        candidates = []
        for task_sub in tasks_dir.iterdir():
            if task_sub.is_dir():
                p_file = task_sub / "plan.json"
                if p_file.is_file():
                    try:
                        p_data = read_json(p_file)
                        st = str(p_data.get("status") or "")
                        if st in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"):
                            candidates.append((p_data, p_file, task_sub.name))
                    except Exception:
                        continue
        if len(candidates) == 1:
            chosen_plan = candidates[0][0]
            chosen_file = candidates[0][1]
            chosen_tid = candidates[0][2]
            try:
                from _vnext_common import atomic_write_json, utc_now
                atomic_write_json(active_file, {"task_id": chosen_tid, "plan_path": str(chosen_file), "updated_at": utc_now()})
            except Exception:
                pass
            return chosen_plan
        elif len(candidates) > 1:
            details = []
            for p_data, _, tid in candidates:
                st = str(p_data.get("status") or "UNKNOWN")
                sha = str(p_data.get("plan_sha256") or "")[:12]
                ca = str(p_data.get("created_at") or "")
                details.append(f"{tid} ({st}, sha:{sha}, created:{ca})")
            raise ValidationError(
                f"AMBIGUOUS_ACTIVE_TASK: Multiple live tasks found in worktree without an active pointer: {'; '.join(details)}. "
                "Specify the active task via 'workflow.py recover-active --task-id <id>' or cancel obsolete tasks."
            )

    raise ValidationError(f"cannot read JSON artifact {active_file}: No active task found")


def file_mutation_allowed(repo: Path, targets: list[str] | None = None) -> tuple[bool, str, str]:
    root = repo.resolve()
    try:
        plan = active_plan(root)
        require_mutation(plan)
    except ValidationError as exc:
        return False, str(exc), "FILE_MUTATION_GUARD"

    if not targets:
        return True, f"mutation authorized by approved plan {plan.get('plan_id')}", "FILE_MUTATION_ALLOWED"

    external_writes = set(plan.get("external_writes") or [])
    expected_files = set(plan.get("expected_files") or [])
    expected_surfaces = set(plan.get("expected_surfaces") or [])
    expected_modules = set(plan.get("expected_modules") or [])

    if not expected_files and not expected_surfaces:
        return True, f"mutation authorized by approved plan {plan.get('plan_id')}", "FILE_MUTATION_ALLOWED"

    from plan_authority import check_material_drift, changed_modules
    from change_classifier import classify

    for target in targets:
        target_str = str(target or "").strip()
        if not target_str:
            continue
        try:
            target_path = Path(target_str)
            if not target_path.is_absolute():
                target_path = (root / target_path).resolve()
            else:
                target_path = target_path.resolve()
            if not target_path.is_relative_to(root):
                return False, f"target {target_str} is outside repository root", "PROTECTED_PATH"
            rel_posix = target_path.relative_to(root).as_posix()
        except Exception as exc:
            return False, f"invalid target path {target_str}: {exc}", "PROTECTED_PATH"

        if rel_posix in external_writes:
            continue

        try:
            candidate_res = classify(
                root,
                task_changes=[{"path": rel_posix}],
                candidate_paths=[rel_posix],
                progress=False,
            )
            surfaces = candidate_res.get("surfaces") or []
        except Exception:
            surfaces = ["UNKNOWN"]
        if _is_tracked(root, rel_posix):
            # Before an edit the classifier sees the whole file, so an existing file that already
            # mentions sign-in or purchases would make any edit sensitive. Sensitive surfaces of a
            # tracked file are judged on its actual diff at prepare-verification and by the verifier.
            surfaces = [s for s in surfaces if s not in PRE_EXISTING_CONTENT_SURFACES]

        try:
            modules = changed_modules(root, {"task_changes": [{"path": rel_posix}]})
            if modules == [":"] and (rel_posix.startswith("app/") or rel_posix == "app") and ":app" in expected_modules:
                modules = [":app"]
        except Exception:
            modules = [":app"]

        drift = check_material_drift(
            plan,
            surfaces,
            modules,
            actual_files=[rel_posix],
        )
        if drift:
            hint = _all_missing_surfaces_hint(root, plan, rel_posix, drift, classify, check_material_drift)
            return (
                False,
                f"Write target '{rel_posix}' causes material scope drift: {', '.join(drift)}. Plan reconciliation and revised approval required.{hint}",
                "SCOPE_EXPANSION_REQUIRES_REVISED_APPROVAL",
            )

    return True, f"mutation authorized by approved plan {plan.get('plan_id')}", "FILE_MUTATION_ALLOWED"


def _all_missing_surfaces_hint(root: Path, plan: dict, target: str, drift: list[str], classify, check_material_drift) -> str:
    """Name every surface the planned files still lack, so one revision covers them all.

    Without this, each planned file's first edit revealed one more surface and one small change
    needed up to three approvals.
    """
    missing = {item.split(":", 1)[1] for item in drift if item.startswith("surface:")}
    for rel in plan.get("expected_files") or []:
        rel = str(rel).replace("\\", "/").strip("/")
        if not rel or rel == target or rel in set(plan.get("external_writes") or []) or not (root / rel).is_file():
            continue
        try:
            surfaces = classify(root, task_changes=[{"path": rel}], candidate_paths=[rel], progress=False).get("surfaces") or []
        except Exception:
            continue
        if _is_tracked(root, rel):
            surfaces = [s for s in surfaces if s not in PRE_EXISTING_CONTENT_SURFACES]
        missing |= {item.split(":", 1)[1] for item in check_material_drift(plan, surfaces) if item.startswith("surface:")}
    files = set(plan.get("expected_files") or []) | {item.split(":", 1)[1] for item in drift if item.startswith("file:")}
    modules = set(plan.get("expected_modules") or []) | {
        ":" + item[len("module:"):].lstrip(":") for item in drift if item.startswith("module:")
    }
    surfaces = set(plan.get("expected_surfaces") or []) | missing
    # A partial revise keeps omitted fields, but the full command shows the developer the whole scope.
    import shlex
    command = f"python .agents/scripts/workflow.py revise --repo . --task-id {shlex.quote(str(plan.get('task_id') or '<task-id>'))}"
    for flag, values in (("--expected-files", files), ("--expected-modules", modules), ("--expected-surfaces", surfaces)):
        if values:
            command += f" {flag} {shlex.quote(','.join(sorted(values)))}"
    missing_text = f" Surfaces missing across the planned files: {', '.join(sorted(missing))}." if missing else ""
    return f"{missing_text} Revise the plan in one command: {command}"


def join_continuations(command: str) -> str:
    """Replace backslash-newline outside quotes with a space, as a POSIX shell does.

    Agents wrap long harness commands over several lines; each line is not a separate command.
    """
    out, quote, i = [], "", 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "\\" and command.startswith(("\\\n", "\\\r\n"), i):
            out.append(" ")
            i += 3 if command[i + 1] == "\r" else 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_segments(command: str) -> list[str] | None:
    """Split on &&, ||, ; and newlines outside quotes; None for an unterminated quote.

    On the Claude bridge (Bash), backslash-newline outside quotes is a line continuation. Other
    hosts may run PowerShell or cmd, where a trailing backslash ends a Windows path, so every
    newline stays a command boundary there.
    """
    if _posix_shell_host():
        command = join_continuations(command)
    segments, current, quote, i = [], [], "", 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == quote:
                quote = ""
            current.append(ch)
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif command.startswith(("&&", "||"), i):
            segments.append("".join(current))
            current = []
            i += 1
        elif ch in ";\n":
            segments.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if quote:
        return None
    segments.append("".join(current))
    return [item.strip() for item in segments if item.strip()]


def _without_single_quoted_text(command: str) -> str | None:
    """The command with single-quoted text removed, as a POSIX shell reads it.

    Inside single quotes nothing is special, so a reviewer reply there cannot pipe, redirect or
    substitute. Double-quoted text is kept because `$` and backticks still expand in it, and a
    backslash outside single quotes keeps the next character. None for an unterminated quote.
    """
    out, quote, i = [], "", 0
    while i < len(command):
        ch = command[i]
        if quote == "'":
            if ch == "'":
                quote = ""
            i += 1
            continue
        if ch == "\\":
            out.append(command[i:i + 2])
            i += 2
            continue
        if quote == '"':
            if ch == '"':
                quote = ""
        elif ch in "\"'":
            quote = ch
            if ch == "'":
                out.append(" ")
                i += 1
                continue
        out.append(ch)
        i += 1
    return None if quote else "".join(out)


def _posix_shell_host() -> bool:
    # Claude Code runs Bash on every platform; its bridge marks the host. Antigravity calls the
    # engine without a marker and may run PowerShell or cmd, so it keeps the character check.
    return os.environ.get("HARNESS_HOOK_HOST", "").strip().lower() == "claude"


def command_allowed(repo: Path | str, command: str) -> tuple[bool, str]:
    if isinstance(repo, str) and (isinstance(command, Path) or (" " in repo and not " " in str(command))):
        repo, command = command, repo
    normalized = str(command or "").strip()
    if not normalized:
        return True, "empty command"
    operator_text = _without_single_quoted_text(normalized) if _posix_shell_host() else normalized
    if operator_text is None:
        return False, "unterminated quote in command"
    if SHELL_LAUNDERING.search(operator_text):
        return False, "shell redirection, piping, or command substitution is outside the read-only boundary"
    segments = _split_segments(normalized)
    if segments is None:
        return False, "unterminated quote in command"
    if len(segments) > 1:
        for item in segments:
            allowed, reason = command_allowed(repo, item)
            if not allowed:
                return False, f"command segment '{item}' is denied: {reason}"
        return True, "every command segment is authorized"
    if segments:
        normalized = segments[0]
    if _workflow_action(normalized, repo) in BOOTSTRAP_ACTIONS:
        return True, "task-authority workflow command"
    if _is_read_only(normalized, repo):
        return True, "read-only inspection command"
    if _is_lifecycle_command(normalized, repo):
        return True, "harness lifecycle engine command"
    try:
        plan = active_plan(repo)
    except ValidationError as exc:
        lower = normalized.lower()
        if any(kw in lower for kw in ("task-context", "task_context", "project_graph", "doctor", "preflight")):
            return False, f"Harness read-only inspection command was not recognized or has invalid arguments: '{normalized}'. Detail: {exc}"
        return False, f"mutation requires an active approved plan: {exc}"
    status = str(plan.get("status") or "")
    entry, arguments = _entry(normalized, repo)
    action = _workflow_action(normalized, repo)
    if status == "IMPLEMENTING":
        if re.search(r"(?:^|\s|python(?:\d+(?:\.\d+)?)?(?:\.exe)?\s+.*)run_device(?:\.py)?\b", normalized, re.I) or (entry == "harness_cli" and arguments[:1] == ["device"]):
            return False, "Device operation is blocked during IMPLEMENTING. Transition to verification via 'python .agents/scripts/workflow.py prepare-verification' first."
        if re.search(r"\b(?:del(?:\s+\/[a-z]+)*\s|rmdir\b|rm\s+-rf\b|powershell\b.*-file\b|bash\s+\S+\.sh\b)", normalized, re.I):
            return False, "Destructive filesystem or external script commands are blocked during implementation."
        if re.search(r"\b(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?\s+(?:-c|-m\s+(?!compileall\b))\b", normalized, re.I):
            return False, "Inline Python execution (-c/-m) is blocked; only audited harness scripts may run."
        if re.search(r"(?:^|[;&|\n]\s*)(?:\.\/?|[^\s]+[/\\])?(?:gradlew|gradle)(?:\.bat)?\s+", normalized, re.I):
            return False, "Raw Gradle execution is blocked; use the harness Gradle wrapper or test gate."
        allowed_implementing_entries = INSPECTION_SCRIPTS | VERIFICATION_SCRIPTS | {"workflow", "setup_wizard", "harness_cli", "compileall"}
        if entry not in allowed_implementing_entries:
            return False, "Arbitrary shell mutation commands are blocked during IMPLEMENTING. File modifications must use host file-edit tools where protected roots are enforced."
        try:
            require_mutation(plan)
        except ValidationError as exc:
            return False, str(exc)
        return True, f"command authorized by approved plan {plan.get('plan_id')}"
    if status == "VERIFYING" and (
        entry in VERIFICATION_SCRIPTS
        or action in {"verify", "complete"}
        or (entry == "harness_cli" and arguments[:1] in (["verify"], ["preflight"], ["test"], ["assemble"], ["device"], ["review"]))
    ):
        return True, f"verification command authorized for plan {plan.get('plan_id')}"
    # READY resume is routed for a stale delivery; workflow.resume() refuses an unchanged one unless --reopen.
    if status in ("VERIFYING", "BLOCKED", "READY_FOR_DELIVERY") and action == "resume":
        return True, f"resume authorized for {status.lower()} plan {plan.get('plan_id')}"
    if status == "BLOCKED":
        blocked = plan.get("blocked_reviewers", [])
        blocked_str = f" from: {', '.join(blocked)}" if blocked else " due to blocking review findings"
        task_id = str(plan.get("task_id") or plan.get("plan_id") or "")
        return False, (
            f"Task {task_id} is BLOCKED{blocked_str}. "
            f"Fix the reported issues, then resume the plan via: python .agents/scripts/workflow.py resume --repo . --task-id {task_id}"
        )
    return False, f"command is not allowed while plan status is {status or 'missing'}"
