"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


def _split_command_tokens(command: str) -> list[str]:
    """Tokenize a shell command while preserving Windows path backslashes (e.g. `.agents\\harness.py`)."""
    normalized_cmd = _engine.re.sub(r'\\(?!["\'\\])', "/", str(command or ""))
    try:
        return _engine.shlex.split(normalized_cmd, posix=True)
    except ValueError:
        return normalized_cmd.split()
def _lifecycle_calls(command: str) -> list[tuple[str, list[str]]]:
    """(subcommand, arguments) for each workflow.py / `harness.py task` call in the command.

    Read from the actual command tokens, never from free text such as an outcome
    ("Fix cancel button") or an approval quote.
    """
    tokens = _engine._split_command_tokens(command)
    calls: list[tuple[str, list[str]]] = []
    for index, token in enumerate(tokens):
        name = token.strip(";&|").replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name in _engine.WORKFLOW_ENTRYPOINTS:
            rest = tokens[index + 1:]
        elif name in _engine.TASK_ENTRYPOINTS and index + 1 < len(tokens) and tokens[index + 1].lower() == "task":
            rest = tokens[index + 2:]
        else:
            continue
        subcommand, skip_value = "", False
        for part in rest:
            if skip_value:
                skip_value = False
                continue
            if part.startswith("-"):
                skip_value = part.lower() in _engine.WORKFLOW_VALUE_FLAGS
                continue
            subcommand = part.strip(";&|").lower()
            break
        if "-h" in rest or "--help" in rest:
            continue  # reading usage changes nothing
        calls.append((subcommand, rest))
    return calls
def _developer_authority_violation(command: str) -> str:
    """Cancel, and approval from any source other than the conversation, belong to the developer.

    Returns the violated action ("cancel" or "approve"), or "" when the command is allowed.
    """
    for subcommand, rest in _engine._lifecycle_calls(command):
        if subcommand == "change-decision" and "--apply" in rest:
            support = _engine._flag(rest, "--mode") == "extend-scope" and _engine._flag(rest, "--source") == "approved-plan"
            if not support and (_engine._flag(rest, "--source") != "conversation" or not _engine._flag(rest, "--proof-reference")):
                return "change-decision"
        if subcommand == "merge" and "--apply" in rest:
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "merge"
        if subcommand == "cancel":
            # The developer asked in chat: the agent runs it with their words as proof, like an approval.
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "cancel"
        if subcommand in ("approve", "approve-sensitive"):
            if _engine._flag(rest, "--source").lower() != "conversation":
                return "approve"
    tokens = _engine._split_command_tokens(command)
    for pos, token in enumerate(tokens):
        name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
        rest = tokens[pos + 1:]
        is_models = name == "review_models.py" or (name in _engine.TASK_ENTRYPOINTS and rest[:2] == ["review", "models"])
        if is_models and "set" in rest and not any(flag in rest for flag in ("-h", "--help")):
            if _engine._flag(rest, "--source") != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "review-models"
        is_exec_mode = (
            name == "execution_mode.py"
            or (name in _engine.TASK_ENTRYPOINTS and rest[:1] == ["execution-mode"])
        )
        if is_exec_mode and "set" in rest and not any(flag in rest for flag in ("-h", "--help")):
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "execution-mode"
        is_web_apply = (
            (name == "web_relay.py" and rest[:1] == ["apply"])
            or (name in _engine.TASK_ENTRYPOINTS and (rest[:1] == ["web-apply"] or rest[:2] == ["web-relay", "apply"]))
        )
        if is_web_apply and not any(flag in rest for flag in ("-h", "--help", "--dry-run")):
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "web-apply"
    return ""
def _flag(rest: list[str], name: str) -> str:
    for pos, part in enumerate(rest):
        if part.startswith(name + "="):
            return part.split("=", 1)[1].strip(";&|").strip()
        if part == name and pos + 1 < len(rest):
            return rest[pos + 1].strip(";&|").strip()
    return ""
def _is_live_interactive_antigravity_lead(conversation: str, transcript_hint: str = "") -> bool:
    if _engine.os.environ.get("HARNESS_ENFORCE_EXECUTION_MODE_PROMPT") == "1":
        return True
    if _engine.os.environ.get("HARNESS_ENFORCE_EXECUTION_MODE_PROMPT") == "0":
        return False
    cid = str(conversation or "").strip()
    if not cid:
        return False
    try:
        from antigravity_runtime import resolve_transcript
        tp = resolve_transcript(cid)
        if tp is None and transcript_hint:
            cand_tp = Path(transcript_hint).expanduser()
            if cand_tp.is_file():
                tp = cand_tp
        if tp and tp.is_file():
            size = tp.stat().st_size
            with tp.open("rb") as fh:
                head_bytes = fh.read(16384)
                tail_bytes = b""
                if size > 16384:
                    fh.seek(max(16384, size - 32768))
                    tail_bytes = fh.read(32768)
            head = head_bytes.decode("utf-8", errors="ignore")
            combined = head + "\n" + tail_bytes.decode("utf-8", errors="ignore")
            has_user_turn = (
                "USER_EXPLICIT" in combined
                or "USER_INPUT" in combined
                or '"role": "user"' in combined
                or '"role":"user"' in combined
            )
            if not has_user_turn:
                return False
            # Spawned subagent transcripts begin with SYSTEM / SYSTEM_SDK dispatch frames and have no real developer USER_EXPLICIT turn
            first_chunk = head[:4096]
            if ('"SYSTEM_SDK"' in first_chunk or '"source": "SYSTEM"' in first_chunk or '"source":"SYSTEM"' in first_chunk) and "USER_EXPLICIT" not in combined:
                return False
            return True
    except (ImportError, OSError, ValueError):
        return False
    return False
def _check_web_mode_direct_write_guard(
    repo: Path,
    targets: list[str],
    *,
    conversation: str = "",
    transcript_hint: str = "",
) -> tuple[bool, str, str]:
    """Prevent Lead from writing production files locally before packing/applying in active `web` mode."""
    if not _engine._is_live_interactive_antigravity_lead(conversation, transcript_hint=transcript_hint):
        return True, "", ""
    try:
        plan = _engine.active_plan(repo)
    except _engine.ValidationError:
        return True, "", ""
    if not isinstance(plan, dict) or str(plan.get("status") or "").upper() != "IMPLEMENTING":
        return True, "", ""
    tid = str(plan.get("task_id") or "").strip()
    if not tid:
        return True, "", ""
    try:
        from delegation_policy import is_test_file
        if targets and all(is_test_file(str(t)) for t in targets if str(t).strip()):
            return True, "", ""
        from execution_mode import inspect_web_phase_progress, resolve_effective_execution_mode
        eff = resolve_effective_execution_mode(repo, task_id=tid, plan=plan, candidate_files=targets)
        if eff.get("mode") != "web" or eff.get("conflict_auto_local_override"):
            return True, "", ""
        prog = inspect_web_phase_progress(repo, plan, target_files=targets)
        if prog.get("has_applied_web_changes") or (prog.get("has_prior_web_round") and not prog.get("pending_continuation_pack_id")):
            return True, "", ""
        if prog.get("pending_continuation_pack_id"):
            return (
                False,
                f"WEB_EXECUTION_MODE_PACK_FIRST: Continuation pack `{prog['pending_continuation_pack_id']}` "
                f"(batch {prog.get('batch_index')}/{prog.get('total_batches')}) is awaiting external AI chat reply on task `{tid}`. "
                "Do NOT re-run `web-pack` or edit files directly — wait for the developer reply and run "
                '`python .agents/harness.py web-apply --source conversation --proof-reference "<words>"` '
                "(or switch to local mode via `execution-mode set --choice normal-task --source conversation --proof-reference "<words>"`).",
                "WEB_EXECUTION_MODE_PACK_FIRST",
            )
        if prog.get("has_staged_phase"):
            return (
                False,
                f"WEB_EXECUTION_MODE_PACK_FIRST: Web mode (`{eff.get('choice')}`) has pre-staged changes for phase "
                f"`{prog.get('phase_id')}` on task `{tid}`. Apply them via "
                '`python .agents/harness.py web-apply --staged-phase --source conversation --proof-reference "<words>"` '
                "before editing files directly.",
                "WEB_EXECUTION_MODE_PACK_FIRST",
            )
        return (
            False,
            f"WEB_EXECUTION_MODE_PACK_FIRST: Web execution mode (`{eff.get('choice')}`) is active for task `{tid}`. "
            f"Run `python .agents/harness.py web-pack --task-id {tid}` to copy the Context Pack for your external AI chat "
            "(or if the developer asked to switch to local mode, run "
            '`python .agents/harness.py execution-mode set --choice normal-task --source conversation --proof-reference "<words>"` first).',
            "WEB_EXECUTION_MODE_PACK_FIRST",
        )
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        return True, "", ""
def _extract_execution_mode_kickoff(command: str) -> tuple[str, str, str]:
    """Return `(kickoff_kind, task_id, task_kind)` when `command` starts a new task (`draft` or `web-pack`), else `('', '', '')`."""
    cmd = str(command or "").strip()
    if not cmd or any(h in cmd for h in (" --help", " -h")):
        return ("", "", "")
    tokens = _engine._split_command_tokens(cmd)
    for pos, tok in enumerate(tokens):
        base = tok.replace("\\", "/").rsplit("/", 1)[-1].lower()
        rest = tokens[pos + 1:]
        if (base == "workflow.py" and rest[:1] == ["draft"]) or (base in _engine.TASK_ENTRYPOINTS and rest[:2] == ["task", "draft"]):
            return ("draft", _engine._flag(rest, "--task-id"), _engine._flag(rest, "--kind").upper())
        if (base == "web_relay.py" and rest[:1] == ["pack"]) or (
            base in _engine.TASK_ENTRYPOINTS and (rest[:1] == ["web-pack"] or rest[:2] == ["web-relay", "pack"])
        ):
            if any(a in {"--retry", "--retry-failure", "--add-files"} or a.startswith("--add-files=") for a in rest):
                return ("", "", "")
            return ("web-pack", _engine._flag(rest, "--task-id"), _engine._flag(rest, "--kind").upper())
    return ("", "", "")
def _audited_harness_command(command: str) -> bool:
    """One harness entry-point call and nothing chained to it.

    `tracker_write` stops tracker writes through raw shell (curl, ad-hoc scripts). Real app: it also
    refused the harness's own audited `zoho authorize --proof-reference "... update zoho ..."` (the
    words that grant the write) and a `draft` whose outcome said "Update Zoho". The harness commands
    enforce Zoho authority themselves; a chained command is never exempt.
    """
    if not _engine.AUDITED_HARNESS_ENTRY.match(command or ""):
        return False
    try:
        from mutation_guard import SHELL_LAUNDERING, _operator_text_any_shell
    except Exception:
        return False
    outside_quotes = _operator_text_any_shell(command)
    if outside_quotes is None or SHELL_LAUNDERING.search(outside_quotes):
        return False
    return not _engine.re.search(r";|&&|\|\||\n", outside_quotes)
def _read_only_git_branch_command(command: str) -> bool:
    """True when every `git_mutation` match in `command` is a read-only `git branch` segment."""
    try:
        from mutation_guard import (
            SHELL_LAUNDERING,
            _entry,
            _operator_text_any_shell,
            _split_segments,
            is_read_only_git_branch,
        )
    except Exception:
        return False
    outside_quotes = _operator_text_any_shell(command or "")
    if outside_quotes is None or SHELL_LAUNDERING.search(outside_quotes):
        return False
    segments = _split_segments(command or "")
    if not segments:
        return False
    git_mut_re = _engine.DANGEROUS[0][1]
    saw_branch = False
    for seg in segments:
        if not git_mut_re.search(seg):
            continue
        name, args = _entry(seg, _engine.REPO)
        if name != "git":
            return False
        if args[:1] == ["-C"] and len(args) >= 3:
            args = args[2:]
        if not is_read_only_git_branch(args):
            return False
        saw_branch = True
    return saw_branch
def _read_only_adb_command(command: str) -> bool:
    """True when every `adb` match in `command` is a bounded read-only `adb logcat` or `pidof` command."""
    try:
        from mutation_guard import (
            SHELL_LAUNDERING,
            _entry,
            _operator_text_any_shell,
            _split_segments,
            _strip_adb_logcat_pipes,
            is_read_only_adb,
        )
    except Exception:
        return False
    normalized = _strip_adb_logcat_pipes(command or "", _engine.REPO) or (command or "")
    outside_quotes = _operator_text_any_shell(normalized)
    if outside_quotes is None or SHELL_LAUNDERING.search(outside_quotes):
        return False
    segments = _split_segments(normalized)
    if not segments:
        return False
    adb_re = _engine.re.compile(r"(?:^|[;&|\n]\s*|\s)(?:[^\s/\\]+[/\\])*adb(?:\.exe)?\b", _engine.re.I)
    saw_adb = False
    for seg in segments:
        if not adb_re.search(seg):
            continue
        name, args = _entry(seg, _engine.REPO)
        if name != "adb" or not is_read_only_adb(args):
            return False
        saw_adb = True
    return saw_adb
def _handle_command(command: str, *, conversation: str = '', transcript_hint: str = '') -> None:
    from mutation_guard import _split_segments, _tokens
    read_commands = {
        "cat", "type", "more", "less", "head", "tail", "sed", "awk", "gawk",
        "wc", "nl", "rg", "grep", "get-content", "gc", "select-string", "sls",
    }
    for segment in _split_segments(command) or []:
        tokens = _tokens(segment)
        if not tokens:
            continue
        cmd0 = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
        if cmd0 in read_commands:
            if any(_engine._installed_engine_target(token, recursive=True) for token in tokens[1:]):
                _engine._deny_engine_read("run_command", command)
                return
        elif cmd0 == "git" and len(tokens) >= 3 and tokens[1].lower() == "show":
            for token in tokens[2:]:
                git_rel = token.split(":", 1)[1] if ":" in token and not token.startswith("-") else token
                if _engine._installed_engine_target(git_rel, recursive=True):
                    _engine._deny_engine_read("run_command", command)
                    return
    active_tid = ""
    try:
        p = _engine.active_plan(_engine.REPO)
        active_tid = str(p.get("task_id") or "")
    except (OSError, ValueError, _engine.ValidationError):
        pass
    violated = _engine._developer_authority_violation(command)
    if violated == "cancel":
        _engine._record_cancel_request(active_tid)
        _engine.emit("deny", "Denied by local safety boundary: developer_authority. " + _engine._cancel_pending_message(active_tid or "<id>"),
             tool="run_command", command=command, reason_code="DEVELOPER_AUTHORITY", task_id=active_tid)
        return
    if violated:
        _engine.emit("deny", "Denied by local safety boundary: developer_authority.", tool="run_command", command=command, reason_code="DEVELOPER_AUTHORITY", task_id=active_tid)
        return
    if _engine._pending_cancel(active_tid) and any(sub in ("resume", "revise", "change-decision") for sub, _ in _engine._lifecycle_calls(command)):
        _engine.emit("deny", _engine._cancel_pending_message(active_tid), tool="run_command", command=command, reason_code="CANCEL_PENDING", task_id=active_tid)
        return
    for code, pattern in _engine.DANGEROUS:
        if pattern.search(command):
            if code in ("tracker_write", "git_mutation", "raw_adb", "agy_headless_loop_tos_guard") and _engine._audited_harness_command(command):
                continue
            if code == "git_mutation" and _engine._read_only_git_branch_command(command):
                continue
            if code in ("raw_adb", "adb_destructive") and _engine._read_only_adb_command(command):
                continue
            hint = f" {_engine.DENY_HINTS[code]}" if code in _engine.DENY_HINTS else ""
            _engine.emit("deny", f"Denied by local safety boundary: {code}.{hint}", tool="run_command", command=command, reason_code=code.upper(), task_id=active_tid)
            return
    if _engine.RAW_GRADLE.search(command):
        _engine.emit("deny", "Raw Gradle execution is blocked; use the harness Gradle/test gate.", tool="run_command", command=command, reason_code="RAW_GRADLE", task_id=active_tid)
        return
    required_host_message = "Antigravity verification must be prepared with --host antigravity\nso trusted Review Protocol V2 can be used."
    if (
        _engine.re.search(r"(?:workflow(?:\.py)?\s+prepare-verification|harness(?:\.py)?\s+task\s+prepare-verification)\b", command, _engine.re.I)
        and not _engine.re.search(r"--host\s+antigravity(?![\w-])", command, _engine.re.I)
    ):
        _engine.emit(
            "deny",
            f"REVIEW_HOST_REQUIRED:\n{required_host_message}",
            tool="run_command",
            command=command,
            reason_code="REVIEW_HOST_REQUIRED",
            task_id=active_tid,
        )
        return
    if not _engine.re.search(r"(?:^|\s)(?:-h|--help)(?:\s|$)", command) and _engine.re.search(
        r"(?:harness(?:\.py)?\s+(?:verify-steps|test|compile|assemble|review\s+package|task\s+(?:prepare-verification|checkpoint-phase))|"
        r"(?:verification_steps|run_tests_gate|run_gradle_task|review_package)\.py|"
        r"workflow\.py\s+(?:prepare-verification|checkpoint-phase))\b",
        command,
        _engine.re.I,
    ):
        busy_pid = _engine._detect_live_verification_or_build_owner(_engine.REPO, active_tid)
        if busy_pid:
            _engine.emit(
                "deny",
                f"CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS: Background verification/Gradle process (PID {busy_pid}) "
                "is still actively running for this workspace. Do NOT launch overlapping `verify-steps`, `prepare-verification`, "
                "`review package`, or Gradle commands — output one short status sentence and wait for the background task notification "
                "(or inspect via `manage_task(Action='list')` if stuck).",
                tool="run_command",
                command=command,
                reason_code="CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS",
                task_id=active_tid,
            )
            return
    # Google Workspace skill CLIs (gdrive, gdocs, gsheets, ...) are external integrations, not project
    # mutations: their readonly namespace is allowed and their mutate namespace asks the developer,
    # whatever state the code task plan is in. Chained or redirected commands are never recognized.
    from integrations.external_write_policy import classify_workspace_cli, workspace_cli_tokens
    workspace_tokens = workspace_cli_tokens(command)
    if workspace_tokens:
        decision, reason, code = classify_workspace_cli(workspace_tokens)
        _engine.emit(decision, reason, tool="run_command", command=command, reason_code=code, task_id=active_tid)
        return
    try:
        from delegation_policy import extract_symbol_write_targets
        is_sym_write, sym_write_targets = extract_symbol_write_targets(command)
    except (ImportError, OSError, ValueError):
        is_sym_write, sym_write_targets = False, []
    if is_sym_write:
        if not sym_write_targets:
            _engine.emit("deny", "Malformed or chained `symbol` write command; pass a single explicit `--file <path>`.", tool="run_command", command=command, reason_code="PROTECTED_PATH", task_id=active_tid)
            return
        for st in sym_write_targets:
            safe_st, detail_st, _ = _engine._safe_target(st)
            if not safe_st:
                _engine.emit("deny", detail_st, tool="run_command", command=command, reason_code="PROTECTED_PATH", task_id=active_tid)
                return
        if _engine._pending_cancel(active_tid):
            _engine.emit("deny", _engine._cancel_pending_message(active_tid), tool="run_command", command=command, reason_code="CANCEL_PENDING", task_id=active_tid)
            return
        sym_allowed, sym_reason, sym_code = _engine.file_mutation_allowed(_engine.REPO, targets=sym_write_targets)
        if sym_allowed:
            w_sym_ok, w_sym_reason, w_sym_code = _engine._check_web_mode_direct_write_guard(
                _engine.REPO, sym_write_targets, conversation=conversation, transcript_hint=transcript_hint,
            )
            if not w_sym_ok:
                sym_allowed, sym_reason, sym_code = w_sym_ok, w_sym_reason, w_sym_code
        if not sym_allowed:
            _engine.emit("deny", sym_reason, tool="run_command", command=command, reason_code=sym_code, task_id=active_tid)
            return
        if conversation:
            try:
                from delegation_policy import mark_lead_edit_or_transition
                mark_lead_edit_or_transition(_engine.REPO, conversation)
            except (ImportError, OSError, ValueError):
                pass
    kickoff_kind, kickoff_tid, kickoff_task_kind = _engine._extract_execution_mode_kickoff(command)
    if kickoff_kind and kickoff_task_kind not in {"CONFLICT", "FIX_CONFLICT", "MERGE"} and _engine._is_live_interactive_antigravity_lead(conversation, transcript_hint=transcript_hint):
        try:
            from execution_mode import build_execution_mode_prompt, resolve_effective_execution_mode
            em_state = resolve_effective_execution_mode(_engine.REPO, task_id=kickoff_tid or None)
            if em_state.get("selection_required"):
                prompt_c = build_execution_mode_prompt(_engine.REPO, task_id=kickoff_tid)
                opts_summary = " | ".join(f"`{o['id']}` ({o['label']})" for o in prompt_c["options"])
                _engine.emit(
                    "deny",
                    f"SELECT_EXECUTION_MODE_REQUIRED: Before starting `{kickoff_kind}`, ask the developer via `ask_question` "
                    f"({prompt_c['question']}) with options: {opts_summary}. "
                    f"Then record their choice via `{prompt_c['command_template']}` and continue.",
                    tool="run_command",
                    command=command,
                    reason_code="SELECT_EXECUTION_MODE_REQUIRED",
                    task_id=kickoff_tid or active_tid,
                )
                return
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            pass
    if (
        _engine.os.environ.get("HARNESS_HOST", "").strip().lower() == "antigravity"
        and _engine._is_live_interactive_antigravity_lead(conversation, transcript_hint=transcript_hint)
        and _engine.re.search(
            r"(?:^|[;&|\r\n]\s*)(?:rg(?:\.exe)?|ripgrep(?:\.exe)?)\b|(?:^|[;&|\r\n]\s*)git(?:\.exe)?\s+diff\s+[^;&|\r\n]*--check\b",
            command,
            _engine.re.I | _engine.re.M,
        )
    ):
        _engine.emit(
            "deny",
            "ANTIGRAVITY_FAST_TOOL_HYGIENE (#201209 / Windows mmap guard): Do NOT invoke `rg` or `git diff --check` via `run_command` — "
            "`rg` triggers a 1.7s `sir_flash_lite` cloud safety scan and memory-maps files on Windows (causing `ERROR_USER_MAPPED_FILE` when paired with parallel file edits). "
            "Use the built-in `grep_search` tool for fast code search, and `python .agents/harness.py preflight` for diff/whitespace checks.",
            tool="run_command",
            command=command,
            reason_code="COMMAND_MUTATION_GUARD",
            task_id=active_tid,
        )
        return
    if _engine.re.search(
        r"(?:^|[;&|\r\n]\s*)(?:(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?\s+(?:-\S+\s+)*-c\b|(?:powershell|pwsh)(?:\.exe)?\s+(?:-\S+\s+)*(?:-c|-command)\b)",
        command,
        _engine.re.I | _engine.re.M,
    ):
        _engine.emit(
            "deny",
            "WINDOWS_TURBO_SHELL_HYGIENE (#200632): Inline `python -c` / `py -c` / `powershell -Command` snippets inside `run_command` break "
            "Antigravity Turbo Mode auto-approval on Windows PowerShell and bypass standalone CLI auditing. "
            "Run a single-line `python .agents/harness.py <subcommand>` or use native `view_file`/`grep_search` tools instead.",
            tool="run_command",
            command=command,
            reason_code="COMMAND_MUTATION_GUARD",
            task_id=active_tid,
        )
        return
    allowed, reason = _engine.command_allowed(_engine.REPO, command)
    if not allowed and (
        "2>&1" in command
        or "|" in command
        or "\n" in command.strip()
        or _engine.re.search(r"^\s*(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?\s+(?:-\S+\s+)*-c\b", command)
    ):
        reason = (
            f"{reason} [WINDOWS_TURBO_SHELL_HYGIENE #200632: Never use pipes (`|`), `2>&1` stream redirections, multi-line scripts, "
            "or inline `python -c` in `run_command` on Antigravity — they force Windows PowerShell out of Turbo Mode into manual approval stalls; "
            "run standalone single-line `python .agents/harness.py` commands or native `view_file`/`grep_search` tools instead.]"
        )
    if allowed and conversation and not is_sym_write:
        try:
            from delegation_policy import check_and_record_lead_post_subagent_read, check_post_reviewer_reread_guard
            ok_pr, reason_pr, code_pr = check_post_reviewer_reread_guard(
                _engine.REPO, conversation, tool_name="run_command", args={}, command=command,
            )
            if not ok_pr:
                _engine.emit("deny", reason_pr, tool="run_command", command=command, reason_code=code_pr, task_id=active_tid)
                return
            ok_ps, reason_ps, code_ps = check_and_record_lead_post_subagent_read(
                _engine.REPO, conversation, tool_name="run_command", args={}, command=command,
            )
            if not ok_ps:
                _engine.emit("deny", reason_ps, tool="run_command", command=command, reason_code=code_ps, task_id=active_tid)
                return
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            pass
    if allowed and _engine.re.search(r"project_graph(?:\.py)?\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+graph\b", command, _engine.re.I):
        reason = f"project_graph executed: {reason}"
    elif allowed and _engine.re.search(r"task_context(?:\.py)?\b|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+task-context\b", command, _engine.re.I):
        # This is a pre-tool hook, so validate the target independently before
        # recording it as a discovery anchor. Merely invoking a missing or
        # invalid target must not unlock broad repository search.
        try:
            entry, command_args = _engine._entry(command, _engine.REPO)
            if entry in {"harness_cli", "android-harness"} and command_args[:1] == ["task-context"]:
                command_args = command_args[1:]

            def option(name: str) -> str | None:
                return command_args[command_args.index(name) + 1] if name in command_args and command_args.index(name) + 1 < len(command_args) else None

            from task_context import lightweight_target_probe
            probe_status = lightweight_target_probe(
                _engine.REPO,
                file=option("--file"),
                symbol=option("--symbol"),
                module=option("--module"),
                source_set=option("--source-set"),
            )
            if probe_status in {"RESOLVED", "AMBIGUOUS"}:
                reason = f"targeted task_context executed: {reason}"
        except (OSError, ValueError, ImportError, _engine.ValidationError):
            pass
    _engine.emit("allow" if allowed else "deny", reason, tool="run_command", command=command, reason_code="HARNESS_COMMAND" if allowed else "COMMAND_MUTATION_GUARD", task_id=active_tid)
