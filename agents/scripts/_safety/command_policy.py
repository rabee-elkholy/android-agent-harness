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
        elif name in _engine.TASK_ENTRYPOINTS:
            after_entry = _strip_leading_cli_flags(tokens[index + 1:])
            if not after_entry or after_entry[0].strip(";&|").lower() != "task":
                continue
            rest = after_entry[1:]
        else:
            continue
        trimmed_rest = _strip_leading_cli_flags(rest)
        subcommand, skip_value = "", False
        for part in trimmed_rest:
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
def _strip_leading_cli_flags(tokens: list[str]) -> list[str]:
    idx = 0
    value_flags = {"--repo", "--task-id", "--task", "--kit"}
    while idx < len(tokens):
        tok = tokens[idx]
        low = tok.lower()
        if low in {"--json", "--no-advance"}:
            idx += 1
            continue
        if low in value_flags and idx + 1 < len(tokens):
            idx += 2
            continue
        if any(low.startswith(f + "=") for f in value_flags):
            idx += 1
            continue
        break
    return tokens[idx:]


def _developer_authority_violation(command: str) -> str:
    """Cancel, and approval from any source other than the conversation, belong to the developer.

    Returns the violated action ("cancel" or "approve"), or "" when the command is allowed.
    """
    for subcommand, rest in _engine._lifecycle_calls(command):
        if subcommand == "change-decision" and "--apply" in rest:
            support = _engine._flag(rest, "--mode").lower() == "extend-scope" and _engine._flag(rest, "--source").lower() == "approved-plan"
            if not support and (_engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference")):
                return "change-decision"
        if subcommand == "merge" and "--apply" in rest:
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "merge"
        if subcommand == "cancel":
            # The developer asked in chat: the agent runs it with their words as proof, like an approval.
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "cancel"
        if subcommand == "deliver" and "--accept-committed" in rest:
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "deliver-accept-committed"
        if subcommand in ("approve", "approve-sensitive", "quick-start"):
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "approve"
        if subcommand == "review-budget":
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "review-budget"
    tokens = _engine._split_command_tokens(command)
    for pos, token in enumerate(tokens):
        name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
        rest = _strip_leading_cli_flags(tokens[pos + 1:])
        is_models = name == "review_models.py" or (name in _engine.TASK_ENTRYPOINTS and rest[:2] == ["review", "models"])
        if is_models:
            sub_rest = _strip_leading_cli_flags(rest[2:] if name in _engine.TASK_ENTRYPOINTS else rest)
            if sub_rest[:1] == ["set"] and not any(flag in rest for flag in ("-h", "--help")):
                if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                    return "review-models"
        is_exec_mode = (
            name == "execution_mode.py"
            or (name in _engine.TASK_ENTRYPOINTS and rest[:1] == ["execution-mode"])
        )
        if is_exec_mode:
            sub_rest = _strip_leading_cli_flags(rest[1:] if name in _engine.TASK_ENTRYPOINTS else rest)
            if sub_rest[:1] == ["set"] and not any(flag in rest for flag in ("-h", "--help")):
                if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                    return "execution-mode"
        is_workspace_cmd = (
            name == "companion_workspaces.py"
            or (name in _engine.TASK_ENTRYPOINTS and rest[:1] == ["workspace"])
        )
        if is_workspace_cmd:
            ws_rest = _strip_leading_cli_flags(rest[1:] if name in _engine.TASK_ENTRYPOINTS else rest)
            if ws_rest[:1] in (["add"], ["remove"]) and not any(flag in rest for flag in ("-h", "--help")):
                if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                    return "workspace"
        is_web_apply = (
            (name == "web_relay.py" and rest[:1] == ["apply"])
            or (name in _engine.TASK_ENTRYPOINTS and (rest[:1] == ["web-apply"] or rest[:2] == ["web-relay", "apply"]))
        )
        if is_web_apply and not any(flag in rest for flag in ("-h", "--help", "--dry-run")):
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "web-apply"
        is_ctx_instruct = (
            (name == "generate_project_context.py" and rest[:1] == ["instruct"])
            or (name in _engine.TASK_ENTRYPOINTS and rest[:2] == ["context", "instruct"])
        )
        if is_ctx_instruct and not any(flag in rest for flag in ("-h", "--help")):
            if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                return "context-instruct"
        is_device_cmd = (
            name in ("run_device.py", "run_device")
            or (name in _engine.TASK_ENTRYPOINTS and rest[:1] == ["device"])
        )
        if is_device_cmd:
            dev_rest = _strip_leading_cli_flags(rest[1:] if name in _engine.TASK_ENTRYPOINTS else rest)
            if dev_rest[:1] in (["skip-validation"], ["validate-automatically"]) and not any(flag in rest for flag in ("-h", "--help")):
                if _engine._flag(rest, "--source").lower() != "conversation" or not _engine._flag(rest, "--proof-reference"):
                    return f"device-{dev_rest[0]}"
        is_pm_auth = (
            name in ("pm_discovery.py", "pm_discovery", "pm_sync.py", "pm_sync")
            or (name in _engine.TASK_ENTRYPOINTS and rest[:1] in (["pm"], ["zoho"]))
        )
        if is_pm_auth:
            pm_rest = _strip_leading_cli_flags(rest[1:] if name in _engine.TASK_ENTRYPOINTS else rest)
            if pm_rest[:1] == ["authorize"] and not any(flag in rest for flag in ("-h", "--help")):
                src = _engine._flag(rest, "--source").lower()
                proof = (_engine._flag(rest, "--proof-reference") or _engine._flag(rest, "--proof")).strip().strip("\"'")
                if src not in ("", "conversation") or not proof:
                    return "pm-authorize"
    return ""


def _authorized_conversation_device_signoff(command: str) -> bool:
    """True only when every `signoff_authority` match is an unlaundered public CLI `device signoff`
    with explicit `--source conversation` + non-empty `--proof-reference` (or read-only `--help`).

    Direct `run_device.py signoff`, bare `device signoff`, `--source developer_terminal`,
    `--source host_native`, empty proof references, and chained non-harness commands remain denied.
    """
    try:
        from mutation_guard import (
            SHELL_LAUNDERING,
            _entry,
            _operator_text_any_shell,
            _split_safe_and_chain,
        )
    except Exception:
        return False
    outside_quotes = _operator_text_any_shell(command or "")
    if outside_quotes is None or SHELL_LAUNDERING.search(outside_quotes):
        return False
    segments = _split_safe_and_chain(command or "", max_segments=8)
    if not segments:
        return False
    signoff_re = next((pat for code, pat in _engine.DANGEROUS if code == "signoff_authority"), None)
    if signoff_re is None:
        return False
    saw_signoff = False
    for seg in segments:
        entry, seg_args = _entry(seg, _engine.REPO)
        if entry not in {"harness_cli", "android-harness"} and not _single_audited_harness_segment(seg):
            return False
        if not signoff_re.search(seg):
            continue
        if entry not in {"harness_cli", "android-harness"}:
            return False
        clean = _strip_leading_cli_flags(seg_args)
        if clean[:1] != ["device"]:
            return False
        dev_rest = _strip_leading_cli_flags(clean[1:])
        if dev_rest[:1] != ["signoff"]:
            return False
        signoff_args = dev_rest[1:]
        if any(flag in signoff_args for flag in ("-h", "--help")):
            saw_signoff = True
            continue
        if _engine._flag(signoff_args, "--source").lower() != "conversation" or not _engine._flag(signoff_args, "--proof-reference").strip():
            return False
        saw_signoff = True
    return saw_signoff
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
                '(or switch to local mode via `execution-mode set --choice normal-task --source conversation --proof-reference "<words>"`).',
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
def _collect_csv_or_multi_flag(rest: list[str], flag_names: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    idx = 0
    while idx < len(rest):
        tok = rest[idx]
        matched_eq = False
        for fn in flag_names:
            if tok.startswith(fn + "="):
                raw_val = tok.split("=", 1)[1].strip(";&|").strip().strip("\"'")
                out.extend(p.strip().strip("\"'") for p in raw_val.split(",") if p.strip().strip("\"'"))
                matched_eq = True
                break
        if matched_eq:
            idx += 1
            continue
        if tok in flag_names:
            idx += 1
            while idx < len(rest) and not rest[idx].startswith("-"):
                raw_val = rest[idx].strip(";&|").strip().strip("\"'")
                if raw_val in {"&&", "||", ";", "|"}:
                    break
                out.extend(p.strip().strip("\"'") for p in raw_val.split(",") if p.strip().strip("\"'"))
                idx += 1
            continue
        idx += 1
    return out


def _collect_repeated_flag(rest: list[str], flag_name: str) -> list[str]:
    """Collect repeated `--flag value` or `--flag=value` occurrences without splitting on commas."""
    out: list[str] = []
    idx = 0
    while idx < len(rest):
        tok = rest[idx]
        if tok.startswith(flag_name + "="):
            val = tok.split("=", 1)[1].strip(";&|").strip().strip("\"'")
            if val:
                out.append(val)
            idx += 1
            continue
        if tok == flag_name and idx + 1 < len(rest):
            val = rest[idx + 1].strip(";&|").strip().strip("\"'")
            if val and val not in {"&&", "||", ";", "|"} and not val.startswith("-"):
                out.append(val)
                idx += 2
                continue
        idx += 1
    return out


def _estimate_cli_phases_count(repo: Path, raw_phases: str) -> int:
    s = str(raw_phases or "").strip().strip("\"'")
    if not s:
        return 0
    cand_file = (repo / s.replace("\\", "/").lstrip("/"))
    if not s.startswith(("[", "{")) and cand_file.is_file():
        try:
            loaded_f = _engine.json.loads(cand_file.read_text(encoding="utf-8"))
            if isinstance(loaded_f, list):
                return len(loaded_f)
            if isinstance(loaded_f, dict) and isinstance(loaded_f.get("phases"), list):
                return len(loaded_f["phases"])
        except (OSError, ValueError):
            pass
    for attempt in (s, s.replace(r'\"', '"')):
        try:
            loaded = _engine.json.loads(attempt)
            if isinstance(loaded, list):
                return len(loaded)
            if isinstance(loaded, dict) and isinstance(loaded.get("phases"), list):
                return len(loaded["phases"])
        except ValueError:
            pass
    if not s.startswith(("[", "{")):
        if ";" in s:
            return len([p.strip() for p in s.split(";") if p.strip()])
        if _engine.re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*\s*:", s):
            return len([p.strip() for p in _engine.re.split(r",\s*(?=[A-Za-z0-9][A-Za-z0-9_-]*\s*:)", s) if p.strip()])
        return len([p.strip() for p in s.split(",") if p.strip()])
    return 0


def _extract_execution_mode_kickoff_details(command: str, repo: Path | None = None) -> dict[str, object]:
    """Extract kickoff metadata (`draft`, `revise`, `quick-start`, or `web-pack`) for threshold-prompted Web-Relay evaluation."""
    empty: dict[str, object] = {
        "kind": "",
        "task_id": "",
        "task_kind": "",
        "files": [],
        "modules": [],
        "surfaces": [],
        "phases_count": 0,
    }
    cmd = str(command or "").strip()
    if not cmd:
        return empty
    try:
        from mutation_guard import _split_segments
        segments = _split_segments(cmd) or [cmd]
    except Exception:
        segments = [cmd]
    eff_repo = repo or _engine.REPO
    inline_mode_choice = ""
    for seg in segments:
        if any(h in f" {seg} " for h in (" --help ", " -h ")):
            continue
        tokens = _engine._split_command_tokens(seg)
        for pos, tok in enumerate(tokens):
            base = tok.replace("\\", "/").rsplit("/", 1)[-1].lower()
            rest = _strip_leading_cli_flags(tokens[pos + 1:])
            if (
                (base == "execution_mode.py" and rest[:1] == ["set"])
                or (base in _engine.TASK_ENTRYPOINTS and rest[:1] == ["execution-mode"] and _strip_leading_cli_flags(rest[1:])[:1] == ["set"])
            ):
                em_src = (_engine._flag(rest, "--source") or "").strip().lower()
                em_prf = (_engine._flag(rest, "--proof-reference") or "").strip()
                em_ch = (_engine._flag(rest, "--choice") or "").strip().lower()
                if em_src == "conversation" and em_prf and em_ch:
                    inline_mode_choice = em_ch
                break
            wf_subs = (["draft"], ["revise"], ["quick-start"])
            if (base == "workflow.py" and rest[:1] in wf_subs) or (
                base in _engine.TASK_ENTRYPOINTS and rest[:1] == ["task"] and _strip_leading_cli_flags(rest[1:])[:1] in wf_subs
            ):
                sub_k = rest[0] if base == "workflow.py" else _strip_leading_cli_flags(rest[1:])[0]
                tid = _engine._flag(rest, "--task-id") or _engine._flag(rest, "--task")
                tkind = _engine._flag(rest, "--kind").upper()
                files = _collect_csv_or_multi_flag(rest, ("--expected-files", "--files", "--file"))
                modules = _collect_csv_or_multi_flag(rest, ("--expected-modules", "--modules", "--module"))
                surfaces = [s.upper() for s in _collect_csv_or_multi_flag(rest, ("--expected-surfaces", "--surfaces", "--surface"))]
                phases_count = max(
                    _estimate_cli_phases_count(eff_repo, _engine._flag(rest, "--phases")),
                    len(_collect_repeated_flag(rest, "--phase")),
                )
                return {
                    "kind": sub_k,
                    "task_id": tid,
                    "task_kind": tkind,
                    "files": files,
                    "modules": modules,
                    "surfaces": surfaces,
                    "phases_count": phases_count,
                    "inline_mode_choice": inline_mode_choice,
                }
            if (base == "web_relay.py" and rest[:1] == ["pack"]) or (
                base in _engine.TASK_ENTRYPOINTS and (rest[:1] == ["web-pack"] or rest[:2] == ["web-relay", "pack"])
            ):
                if any(a in {"--retry", "--retry-failure", "--add-files"} or a.startswith("--add-files=") for a in rest):
                    continue
                tid = _engine._flag(rest, "--task-id") or _engine._flag(rest, "--task")
                tkind = _engine._flag(rest, "--kind").upper()
                files = _collect_csv_or_multi_flag(rest, ("--files", "--file", "--expected-files"))
                return {
                    "kind": "web-pack",
                    "task_id": tid,
                    "task_kind": tkind,
                    "files": files,
                    "modules": [],
                    "surfaces": [],
                    "phases_count": 0,
                    "inline_mode_choice": inline_mode_choice,
                }
    return empty


def _extract_execution_mode_kickoff(command: str) -> tuple[str, str, str]:
    """Return `(kickoff_kind, task_id, task_kind)` when `command` starts/revises a task (`draft`, `revise`, `quick-start`, or `web-pack`), else `('', '', '')`."""
    details = _extract_execution_mode_kickoff_details(command)
    return (
        str(details.get("kind") or ""),
        str(details.get("task_id") or ""),
        str(details.get("task_kind") or ""),
    )
def _single_audited_harness_segment(segment: str) -> bool:
    if not _engine.AUDITED_HARNESS_ENTRY.match(segment or ""):
        return False
    from mutation_guard import SHELL_LAUNDERING, _operator_text_any_shell
    outside_quotes = _operator_text_any_shell(segment)
    if outside_quotes is None or SHELL_LAUNDERING.search(outside_quotes):
        return False
    return not _engine.re.search(r";|&&|\|\||\n", outside_quotes)


def _audited_harness_command(command: str) -> bool:
    """One or more `&&`-chained audited harness entry-point calls, with zero external commands or pipes.

    Supports Antigravity CLI v1.5.13 related-command `&&` chaining when EVERY segment is an audited
    harness entrypoint, while rejecting any mixed external command, `;`, `||`, `|`, `
`, or redirection.
    """
    try:
        from mutation_guard import _split_safe_and_chain
    except Exception:
        return False
    segments = _split_safe_and_chain(command or "", max_segments=8)
    if not segments:
        return False
    return all(_single_audited_harness_segment(seg) for seg in segments)
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
def _contains_windows_start_process(command: str) -> bool:
    """Detect verb-position PowerShell `Start-Process` / `saps` launches outside quoted arguments (#1718)."""
    from mutation_guard import _split_segments, _tokens
    segments = _split_segments(command or "")
    if segments is None:
        return bool(_engine.re.search(
            r"(?:^|[;&|\r\n]\s*)(?:Microsoft\.PowerShell\.Management\\)?(?:Start-Process|saps)(?:\s|$)",
            command or "",
            _engine.re.I | _engine.re.M,
        ))
    start_verbs = {
        "start-process",
        "microsoft.powershell.management\\start-process",
        "microsoft.powershell.management/start-process",
        "saps",
    }
    for seg in segments:
        parts: list[str] = []
        buf: list[str] = []
        quote = ""
        for ch in seg:
            if quote:
                if ch == quote:
                    quote = ""
                buf.append(ch)
            elif ch in "\"'":
                quote = ch
                buf.append(ch)
            elif ch == "|":
                parts.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        if buf:
            parts.append("".join(buf).strip())
        for part in parts:
            toks = _tokens(part)
            if not toks:
                continue
            idx = 1 if toks[0] == "&" and len(toks) > 1 else 0
            head = toks[idx].strip().strip("\"'").lower()
            if head in start_verbs:
                return True
    return False


def _extract_single_file_delete_targets(segment: str) -> tuple[bool, list[str]]:
    from mutation_guard import _entry, _strip_workflow_top_flags
    name, args = _entry(segment, _engine.REPO)
    if name in {"harness_cli", "android-harness"}:
        clean = _strip_workflow_top_flags(args)
        if clean[:1] != ["file"]:
            return False, []
        sub_args = clean[1:]
    elif name == "safe_file_ops":
        sub_args = _strip_workflow_top_flags(args)
    else:
        return False, []
    if any(tok in {"-h", "--help"} for tok in sub_args):
        return False, []
    sub_clean = _strip_workflow_top_flags(sub_args)
    if sub_clean[:1] != ["delete"]:
        return True, []
    rest = sub_clean[1:]
    targets: list[str] = []
    idx = 0
    while idx < len(rest):
        tok = rest[idx]
        if tok == "--json":
            idx += 1
        elif tok in {"--repo", "--kit", "--task-id", "--task"} and idx + 1 < len(rest):
            idx += 2
        elif any(tok.startswith(f + "=") for f in ("--repo", "--kit", "--task-id", "--task")):
            idx += 1
        elif tok.startswith("-"):
            return True, []
        else:
            targets.append(tok)
            idx += 1
    return (True, targets) if targets else (True, [])


def _extract_file_delete_targets(command: str) -> tuple[bool, list[str]]:
    cmd = str(command or "").strip()
    if not cmd:
        return False, []
    low = cmd.lower()
    if not _engine.re.search(
        r"(?:harness(?:\.py)?|harness_cli(?:\.py)?|android-harness)\s+(?:--\S+\s+)*file\s+(?:--\S+\s+)*delete\b|safe_file_ops(?:\.py)?\b",
        low,
    ):
        return False, []
    from mutation_guard import _split_safe_and_chain
    segments = _split_safe_and_chain(cmd, max_segments=8)
    if not segments:
        return True, []
    any_del = False
    all_targets: list[str] = []
    for seg in segments:
        seg_del, seg_targets = _extract_single_file_delete_targets(seg)
        if seg_del:
            if not seg_targets:
                return True, []
            any_del = True
            for t in seg_targets:
                if t not in all_targets:
                    all_targets.append(t)
    if not any_del:
        return False, []
    return True, all_targets


def _handle_command(command: str, *, conversation: str = '', transcript_hint: str = '', cwd: Path | None = None) -> None:
    from mutation_guard import _is_read_only, _split_segments, _tokens
    from platform_quirks import is_quirk_enabled
    read_commands = {
        "cat", "type", "more", "less", "head", "tail", "sed", "awk", "gawk",
        "wc", "nl", "rg", "grep", "findstr", "get-content", "gc", "select-string", "sls",
        "get-childitem", "gci", "dir", "ls",
    }
    git_read_subs = {"show", "grep", "diff", "log", "blame", "ls-files"}
    for segment in _split_segments(command) or []:
        tokens = _tokens(segment)
        if not tokens:
            continue
        cmd0 = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
        if cmd0 in read_commands:
            if any(_engine._installed_engine_target(token, recursive=True) for token in tokens[1:]):
                _engine._deny_engine_read("run_command", command)
                return
            for token in tokens[1:]:
                if token.startswith("-") or not token.strip():
                    continue
                t_clean = token.strip().strip("\"'").replace("\\", "/")
                t_low = t_clean.lower()
                if any(
                    seg in t_low
                    for seg in ("/etc/passwd", "/etc/shadow", "/.ssh/", "/.aws/", "/.gnupg/", "/.kube/", "/.netrc")
                ) or t_low.endswith(("/.ssh", "/.aws", "/.gnupg", "/.netrc")):
                    _engine.emit(
                        "deny",
                        f"Target path '{token}' is outside the repository boundary.",
                        tool="run_command",
                        command=command,
                        reason_code="OUT_OF_REPO_READ_BLOCKED",
                    )
                    return
        elif cmd0 == "git" and len(tokens) >= 3:
            g_idx = 1
            while g_idx < len(tokens):
                gt = tokens[g_idx].lower()
                if gt == "--no-pager":
                    g_idx += 1
                elif gt in {"-c", "-C"} and g_idx + 1 < len(tokens):
                    g_idx += 2
                else:
                    break
            if g_idx < len(tokens) and tokens[g_idx].lower() in git_read_subs:
                for token in tokens[g_idx + 1:]:
                    git_rel = token.split(":", 1)[1] if ":" in token and not token.startswith("-") else token
                    if _engine._installed_engine_target(git_rel, recursive=True):
                        _engine._deny_engine_read("run_command", command)
                        return
    active_tid = ""
    active_status = ""
    try:
        p = _engine.active_plan(_engine.REPO)
        active_tid = str(p.get("task_id") or "")
        active_status = str(p.get("status") or "")
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
    from integrations.external_write_policy import classify_external_cli, external_cli_tokens
    ext_cli = external_cli_tokens(command, repo=_engine.REPO)
    for code, pattern in _engine.DANGEROUS:
        if pattern.search(command):
            if code == "agy_headless_loop_tos_guard" and not (
                is_quirk_enabled("199748", repo=_engine.REPO) or is_quirk_enabled("201582", repo=_engine.REPO)
            ):
                continue
            if code in ("tracker_write", "git_mutation", "raw_adb", "agy_headless_loop_tos_guard") and _engine._audited_harness_command(command):
                continue
            if code == "tracker_write" and ext_cli is not None and ext_cli[0] in {"workspace", "twg", "service"}:
                continue
            if code == "tracker_write" and _is_read_only(command, _engine.REPO):
                continue
            if code == "git_mutation" and _engine._read_only_git_branch_command(command):
                continue
            if code in ("raw_adb", "adb_destructive") and _engine._read_only_adb_command(command):
                continue
            if code == "signoff_authority" and _authorized_conversation_device_signoff(command):
                continue
            hint = f" {_engine.DENY_HINTS[code]}" if code in _engine.DENY_HINTS else ""
            _engine.emit("deny", f"Denied by local safety boundary: {code}.{hint}", tool="run_command", command=command, reason_code=code.upper(), task_id=active_tid)
            return
    if is_quirk_enabled("200632", repo=_engine.REPO) and _contains_windows_start_process(command):
        _engine.emit(
            "deny",
            "WINDOWS_START_PROCESS_PIPE_HANG (#1718 / #200632): Direct `Start-Process` / `saps` invocations inside `run_command` on Windows "
            "let spawned GUI/background child processes inherit parent stdout/stderr pipe handles, causing Antigravity's background task runner "
            "to hang indefinitely at `Empty log` waiting for pipe EOF. Use bounded headless `python .agents/harness.py <subcommand>` calls instead.",
            tool="run_command",
            command=command,
            reason_code="COMMAND_MUTATION_GUARD",
            task_id=active_tid,
        )
        return
    try:
        from companion_workspaces import evaluate_companion_command, match_companion_target
        cwd_is_companion = bool(cwd is not None and match_companion_target(_engine.REPO, str(cwd))[0])
        if cwd_is_companion or not _engine._audited_harness_command(command):
            comp_ok, comp_root, comp_reason = evaluate_companion_command(_engine.REPO, command, cwd=cwd)
            if comp_root is not None:
                if comp_ok:
                    _engine.emit(
                        "allow",
                        comp_reason,
                        tool="run_command",
                        command=command,
                        reason_code="COMPANION_WORKSPACE_COMMAND_ALLOWED",
                        task_id=active_tid,
                    )
                    return
                _engine.emit(
                    "deny",
                    comp_reason,
                    tool="run_command",
                    command=command,
                    reason_code="PROTECTED_PATH",
                    task_id=active_tid,
                )
                return
    except (ImportError, OSError, ValueError):
        pass
    if _engine.RAW_GRADLE.search(command):
        _engine.emit("deny", "Raw Gradle execution is blocked; use the harness Gradle/test gate.", tool="run_command", command=command, reason_code="RAW_GRADLE", task_id=active_tid)
        return
    required_host_message = "Antigravity verification must be prepared with --host antigravity\nso trusted Review Protocol V2 can be used."
    is_prepare_verif = any(sub == "prepare-verification" for sub, _ in _engine._lifecycle_calls(command)) or bool(
        _engine.re.search(
            r"(?:workflow(?:\.py)?\s+(?:--\S+\s+)*prepare-verification|(?:android-harness|harness_cli(?:\.py)?|harness(?:\.py)?)\s+(?:--\S+\s+)*task\s+(?:--\S+\s+)*prepare-verification)\b",
            command,
            _engine.re.I,
        )
    )
    if (
        is_prepare_verif
        and not _engine.re.search(r"(?:^|\s)(?:-h|--help)(?:\s|$)", command)
        and not _engine.re.search(r"--host(?:\s+|=)[\x22\x27]?antigravity(?![\w-])", command, _engine.re.I)
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
        r"(?:harness(?:\.py)?\s+(?:--\S+\s+)*(?:verify-steps|test|compile|assemble|review\s+package|task\s+(?:--\S+\s+)*(?:prepare-verification|checkpoint-phase|ship))|"
        r"(?:verification_steps|run_tests_gate|run_gradle_task|review_package)\.py|"
        r"workflow(?:\.py)?\s+(?:--\S+\s+)*(?:prepare-verification|checkpoint-phase|ship))\b",
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
    # External/plugin CLIs (Google Workspace, `twg`, `gh`, `firebase`, `gcloud`, etc.):
    # read-only queries are allowed, writes ask for confirmation, secret/protected paths stay denied,
    # and unknown non-dangerous external CLIs prompt outside IMPLEMENTING instead of hard-blocking.
    if ext_cli is not None:
        ext_kind, ext_toks = ext_cli
        classified = classify_external_cli(ext_kind, ext_toks, plan_status=active_status)
        if classified is not None:
            decision, reason, code = classified
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
    try:
        is_file_delete, file_delete_targets = _extract_file_delete_targets(command)
    except (ImportError, OSError, ValueError):
        is_file_delete, file_delete_targets = False, []
    if is_file_delete:
        if not file_delete_targets:
            _engine.emit("deny", "Malformed or chained `file delete` command; pass explicit repository file path(s).", tool="run_command", command=command, reason_code="PROTECTED_PATH", task_id=active_tid)
            return
        from safe_file_ops import _has_symlink_component, _is_unconditionally_protected
        repo_root = _engine.REPO.resolve()
        for ft in file_delete_targets:
            if _has_symlink_component(repo_root, ft):
                _engine.emit("deny", f"Refusing symlink target deletion: '{ft}'.", tool="run_command", command=command, reason_code="PROTECTED_PATH", task_id=active_tid)
                return
            safe_ft, detail_ft, is_ext_ft = _engine._safe_target(ft)
            if not safe_ft or is_ext_ft:
                _engine.emit("deny", detail_ft if not safe_ft else f"Target path '{ft}' is outside the repository boundary.", tool="run_command", command=command, reason_code="PROTECTED_PATH", task_id=active_tid)
                return
            cand_ft = Path(ft).expanduser()
            resolved_ft = cand_ft.resolve() if cand_ft.is_absolute() else (repo_root / cand_ft).resolve()
            if resolved_ft.is_dir():
                _engine.emit("deny", f"Refusing directory deletion: '{ft}'.", tool="run_command", command=command, reason_code="PROTECTED_PATH", task_id=active_tid)
                return
            if resolved_ft.is_relative_to(repo_root) and _is_unconditionally_protected(resolved_ft.relative_to(repo_root).as_posix()):
                _engine.emit("deny", f"Cannot delete protected harness, Git, wrapper, or adapter file '{ft}'.", tool="run_command", command=command, reason_code="PROTECTED_PATH", task_id=active_tid)
                return
        if _engine._pending_cancel(active_tid):
            _engine.emit("deny", _engine._cancel_pending_message(active_tid), tool="run_command", command=command, reason_code="CANCEL_PENDING", task_id=active_tid)
            return
        try:
            from plan_authority import require_mutation
            del_plan = _engine.active_plan(_engine.REPO)
            require_mutation(del_plan)
        except _engine.ValidationError as exc:
            _engine.emit("deny", str(exc), tool="run_command", command=command, reason_code="FILE_MUTATION_GUARD", task_id=active_tid)
            return
        del_allowed, del_reason, del_code = _engine.file_mutation_allowed(_engine.REPO, targets=file_delete_targets)
        if del_allowed:
            w_del_ok, w_del_reason, w_del_code = _engine._check_web_mode_direct_write_guard(
                _engine.REPO, file_delete_targets, conversation=conversation, transcript_hint=transcript_hint,
            )
            if not w_del_ok:
                del_allowed, del_reason, del_code = w_del_ok, w_del_reason, w_del_code
        if not del_allowed:
            _engine.emit("deny", del_reason, tool="run_command", command=command, reason_code=del_code, task_id=active_tid)
            return
        if conversation:
            try:
                from delegation_policy import mark_lead_edit_or_transition
                mark_lead_edit_or_transition(_engine.REPO, conversation)
            except (ImportError, OSError, ValueError):
                pass
    ko_details = _extract_execution_mode_kickoff_details(command, repo=_engine.REPO)
    kickoff_kind = str(ko_details.get("kind") or "")
    kickoff_tid = str(ko_details.get("task_id") or "")
    kickoff_task_kind = str(ko_details.get("task_kind") or "")
    if kickoff_kind and kickoff_task_kind not in {"CONFLICT", "FIX_CONFLICT", "MERGE"} and _engine._is_live_interactive_antigravity_lead(conversation, transcript_hint=transcript_hint):
        try:
            from execution_mode import build_execution_mode_prompt, resolve_effective_execution_mode
            ko_files = list(ko_details.get("files") or [])
            ko_modules = list(ko_details.get("modules") or [])
            ko_surfaces = list(ko_details.get("surfaces") or [])
            ko_phases = int(ko_details.get("phases_count") or 0)
            em_state = resolve_effective_execution_mode(
                _engine.REPO,
                task_id=kickoff_tid or active_tid or None,
                candidate_files=ko_files or None,
                candidate_modules=ko_modules or None,
                candidate_surfaces=ko_surfaces or None,
                candidate_phases_count=ko_phases,
                kickoff_kind=kickoff_kind,
            )
            inline_ch = str(ko_details.get("inline_mode_choice") or "")
            if inline_ch in {"normal-task", "normal-project", "web-task", "web-project", "ask-every-task"}:
                if kickoff_kind == "web-pack" and inline_ch in {"normal-task", "normal-project"}:
                    _engine.emit(
                        "deny",
                        f"LOCAL_EXECUTION_MODE_ACTIVE: Local execution (`{inline_ch}`) is active.",
                        tool="run_command",
                        command=command,
                        reason_code="LOCAL_EXECUTION_MODE_ACTIVE",
                        task_id=kickoff_tid or active_tid,
                    )
                    return
            elif em_state.get("selection_required"):
                prompt_c = em_state.get("prompt_contract") or build_execution_mode_prompt(
                    _engine.REPO,
                    task_id=kickoff_tid or active_tid,
                    scope_summary=str(em_state.get("scope_summary") or ""),
                    savings_pct_range=str(em_state.get("estimated_quota_savings_pct") or ""),
                )
                opts_summary = " | ".join(f"`{o['id']}` ({o['label']})" for o in prompt_c["options"])
                _engine.emit(
                    "deny",
                    f"SELECT_EXECUTION_MODE_REQUIRED: Expected heavy-task execution-mode prompt before `{kickoff_kind}` "
                    "(tip: run `python .agents/harness.py execution-mode show --files <csv> [--surfaces <csv>] [--phases <N>] --json` "
                    "before `task draft` so you can ask first without hitting this hook). Ask the developer via `ask_question` "
                    f"({prompt_c['question']}) with the 3 options: {opts_summary}. "
                    f"Translate the question (stating the approximate quota savings) and options professionally into the active conversation language, "
                    f"then record their choice via `{prompt_c['command_template']}` and continue.",
                    tool="run_command",
                    command=command,
                    reason_code="SELECT_EXECUTION_MODE_REQUIRED",
                    task_id=kickoff_tid or active_tid,
                )
                return
            if kickoff_kind == "web-pack" and em_state.get("mode") == "normal" and em_state.get("effective_scope") in {"project", "task", "pending_task"}:
                _engine.emit(
                    "deny",
                    f"LOCAL_EXECUTION_MODE_ACTIVE: Local execution (`{em_state.get('choice')}`) is active. "
                    "Continue locally in Antigravity, or if the developer explicitly asked to offload this task via Web-Relay, run "
                    '`python .agents/harness.py execution-mode set --choice web-task --source conversation --proof-reference "<developer request>"` first.',
                    tool="run_command",
                    command=command,
                    reason_code="LOCAL_EXECUTION_MODE_ACTIVE",
                    task_id=kickoff_tid or active_tid,
                )
                return
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            pass
    if (
        is_quirk_enabled("201209", repo=_engine.REPO)
        and _engine.os.environ.get("HARNESS_HOST", "").strip().lower() == "antigravity"
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
    if is_quirk_enabled("200632", repo=_engine.REPO) and _engine.re.search(
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
    if is_quirk_enabled("200632", repo=_engine.REPO) and _contains_windows_start_process(command):
        _engine.emit(
            "deny",
            "WINDOWS_START_PROCESS_PIPE_HANG (#1718 / #200632): Direct `Start-Process` / `saps` invocations inside `run_command` on Windows "
            "let spawned GUI/background child processes inherit parent stdout/stderr pipe handles, causing Antigravity's background task runner "
            "to hang indefinitely at `Empty log` waiting for pipe EOF. Use bounded headless `python .agents/harness.py <subcommand>` calls instead.",
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
    if allowed and conversation and not (is_sym_write or is_file_delete):
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
