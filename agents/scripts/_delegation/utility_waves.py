"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


def reconcile_completed_async_utility_waves(repo: Path) -> list[str]:
    """Close any open utility waves whose bound async child transcripts have now reached COMPLETED_DONE or EMPTY_DONE."""
    ledger = _engine._load_utility_ledger(repo)
    entries = ledger.get("entries") or []
    if not entries:
        return []
    open_entries = [
        e for e in entries
        if isinstance(e, dict) and not e.get("wave_completed") and not e.get("dispatch_failed") and str(e.get("execution_id") or "").strip()
    ]
    if not open_entries:
        return []
    now_ts = _engine.time.time()
    updates_by_exec: dict[str, dict[str, Any]] = {}
    closed_ids: list[str] = []
    check_empty_payload = _engine.is_quirk_enabled("201209", repo=repo)
    for item in open_entries:
        cid_b = str(item.get("execution_id") or "").strip()
        t_st = _engine._child_transcript_terminal_state(cid_b)
        if t_st == "EMPTY_DONE" and check_empty_payload:
            updates_by_exec[cid_b] = {
                "dispatch_failed": True,
                "empty_terminal_response": True,
                "failure_code": "EMPTY_SUBAGENT_TERMINAL_RESPONSE",
                "completed_at": _engine.utc_now(),
                "completed_at_epoch": now_ts,
            }
            closed_ids.append(cid_b)
        elif t_st in {"COMPLETED_DONE", "EMPTY_DONE"}:
            updates_by_exec[cid_b] = {
                "wave_completed": True,
                "completed_at": _engine.utc_now(),
                "completed_at_epoch": now_ts,
            }
            closed_ids.append(cid_b)
    if updates_by_exec:
        try:
            with _engine.StateLock(_engine.state_root(repo)):
                fresh_ledger = _engine._load_utility_ledger(repo)
                for fe in fresh_ledger.get("entries") or []:
                    if isinstance(fe, dict):
                        ex_id = str(fe.get("execution_id") or "").strip()
                        if ex_id in updates_by_exec:
                            fe.update(updates_by_exec[ex_id])
                _engine._save_utility_ledger(repo, fresh_ledger)
        except (OSError, _engine.ValidationError):
            pass
    return closed_ids
def _ledger_path(repo: Path) -> Path:
    return _engine.state_root(repo) / "utility-subagents.json"
def _step_budgets_path(repo: Path) -> Path:
    return _engine.state_root(repo) / "cache" / "subagent-step-budgets.json"
def _unloaded_agents_path(repo: Path) -> Path:
    return _engine.state_root(repo) / "cache" / "unloaded-utility-agents.json"
def record_unloaded_utility_agent(repo: Path, conversation_id: str, agent_name: str) -> None:
    cid = str(conversation_id or "").strip()
    role = str(agent_name or "").strip()
    if not cid or not role:
        return
    path = _engine._unloaded_agents_path(repo)
    try:
        with _engine.StateLock(_engine.state_root(repo)):
            data = _engine.read_json(path) if path.is_file() else {"sessions": {}}
            if not isinstance(data, dict):
                data = {"sessions": {}}
            sessions = data.setdefault("sessions", {})
            cur = set(sessions.get(cid) or [])
            cur.add(role)
            sessions[cid] = sorted(cur)
            path.parent.mkdir(parents=True, exist_ok=True)
            _engine.atomic_write_json(path, data)
    except (OSError, _engine.ValidationError):
        pass
def is_utility_agent_unloaded_in_session(repo: Path, conversation_id: str, agent_name: str) -> bool:
    cid = str(conversation_id or "").strip()
    role = str(agent_name or "").strip()
    if not role:
        return False
    path = _engine._unloaded_agents_path(repo)
    if not path.is_file():
        return False
    try:
        data = _engine.read_json(path)
        sessions = data.get("sessions") or {}
        if cid and role in (sessions.get(cid) or []):
            return True
        return role in (sessions.get("global") or [])
    except (OSError, ValueError, KeyError, _engine.ValidationError):
        return False
def discover_impacted_existing_tests(repo: Path, expected_files: list[str] | set[str]) -> list[dict[str, Any]]:
    """Find existing tracked unit/regression test files outside `expected_files` that reference planned production classes."""
    import subprocess
    norm_expected = {_engine._normalize_repo_rel(repo, f) for f in (expected_files or []) if str(f or "").strip()}
    prod_stems = sorted({
        Path(p).stem
        for p in norm_expected
        if p.endswith((".kt", ".java")) and not _engine.is_test_file(p) and len(Path(p).stem) >= 4
    })
    if not prod_stems or not (repo / ".git").exists():
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "-c", "core.quotepath=false", "ls-files"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    candidates = [
        line.strip().replace("\\", "/")
        for line in proc.stdout.splitlines()
        if line.strip() and line.strip().replace("\\", "/") not in norm_expected and _engine.is_test_file(line.strip())
    ]
    if not candidates:
        return []
    # Also collect non-private top-level / extension fun & class symbols from planned production files
    extra_symbols: set[str] = set(prod_stems)
    sym_decl_re = _engine.re.compile(
        r"^\s*(?:(?:public|internal|open|abstract|data|sealed|inline|suspend|actual|expect)\s+)*"
        r"(?:class|interface|object|fun)\s+(?:[A-Za-z0-9_<>,.?*\s]+\.)?([A-Za-z_][A-Za-z0-9_]*)\b",
        _engine.re.M,
    )
    for rel_p in sorted(norm_expected)[:120]:
        if not rel_p.endswith((".kt", ".java")) or _engine.is_test_file(rel_p):
            continue
        fp = repo / rel_p
        if fp.is_file():
            try:
                src_txt = fp.read_text(encoding="utf-8", errors="replace")
                for m_sym in sym_decl_re.finditer(src_txt):
                    sname = m_sym.group(1)
                    if len(sname) >= 5 and sname not in {"invoke", "apply", "build", "create", "equals", "toString", "hashCode"}:
                        extra_symbols.add(sname)
            except OSError:
                pass

    impacted: list[dict[str, Any]] = []
    word_patterns = {sym: _engine.re.compile(rf"\b{_engine.re.escape(sym)}\b") for sym in sorted(extra_symbols)[:40]}
    stem_set = set(prod_stems)
    for rel in candidates[:250]:
        fpath = repo / rel
        if not fpath.is_file():
            continue
        test_stem = fpath.stem
        companion_hits = [st for st in stem_set if test_stem in {f"{st}Test", f"{st}Tests", f"{st}Spec"}]
        try:
            if fpath.stat().st_size > 512 * 1024:
                continue
            ftxt = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        matched = list(dict.fromkeys(companion_hits + [sym for sym, pat in word_patterns.items() if pat.search(ftxt)]))
        if matched:
            impacted.append({"test_file": rel, "referenced_symbols": matched[:8]})
    return impacted[:12]
def _load_utility_ledger(repo: Path) -> dict[str, Any]:
    path = _engine._ledger_path(repo)
    if not path.is_file():
        return {"schema_version": 2, "entries": []}
    try:
        data = _engine.read_json(path)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    except (OSError, ValueError, _engine.ValidationError):
        pass
    return {"schema_version": 2, "entries": []}
def _save_utility_ledger(repo: Path, data: dict[str, Any]) -> None:
    now = _engine.time.time()
    raw_entries = [
        e for e in (data.get("entries") or [])
        if isinstance(e, dict) and (now - float(e.get("dispatched_epoch") or 0)) <= _engine.LEDGER_TTL_SECONDS
    ]
    data["entries"] = raw_entries[-_engine.MAX_LEDGER_ENTRIES:]
    data["schema_version"] = 2
    path = _engine._ledger_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    _engine.atomic_write_json(path, data)
def _prompt_sha256(prompt: str) -> str:
    norm = str(prompt or "").replace("\r\n", "\n").strip()
    return _engine.hashlib.sha256(norm.encode("utf-8")).hexdigest()
def _count_parent_user_turns(parent_conversation_id: str) -> int:
    """Count explicit developer messages and completed `ask_question` answers in parent transcript."""
    cid = str(parent_conversation_id or "").strip()
    if not cid:
        return 0
    tx = _engine.prefer_full_transcript(_engine.resolve_transcript(cid))
    if tx is None or not tx.is_file():
        return 0
    try:
        if tx.stat().st_size > 32 * 1024 * 1024:
            return 0
        count = 0
        pending_ask = False
        with tx.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not pending_ask and '"USER_INPUT"' not in line and '"ask_question"' not in line:
                    continue
                try:
                    row = _engine.json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                rtype = str(row.get("type") or "")
                if row.get("source") == "USER_EXPLICIT" and rtype == "USER_INPUT":
                    count += 1
                    pending_ask = False
                elif rtype == "PLANNER_RESPONSE":
                    tcs = row.get("tool_calls") or []
                    pending_ask = any(
                        isinstance(tc, dict) and str(tc.get("name") or "") == "ask_question"
                        for tc in tcs
                    )
                elif pending_ask and rtype in {"GENERIC", "TOOL_RESULT"}:
                    if not row.get("error") and str(row.get("status") or "DONE").upper() != "ERROR":
                        count += 1
                    pending_ask = False
        return count
    except OSError:
        return 0
def _count_parent_planner_turns(parent_conversation_id: str) -> int:
    """Count PLANNER_RESPONSE events in parent transcript so parallel single-subagent calls share one wave_id."""
    cid = str(parent_conversation_id or "").strip()
    if not cid:
        return 0
    tx = _engine.prefer_full_transcript(_engine.resolve_transcript(cid))
    if tx is None or not tx.is_file():
        return 0
    try:
        if tx.stat().st_size > 32 * 1024 * 1024:
            return 0
        count = 0
        with tx.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"PLANNER_RESPONSE"' not in line:
                    continue
                try:
                    row = _engine.json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("type") == "PLANNER_RESPONSE":
                    count += 1
        return count
    except OSError:
        return 0
def _parent_has_user_input_after(parent_conversation_id: str, min_iso_timestamp: str) -> bool:
    """True when parent transcript contains an explicit USER_INPUT timestamp strictly newer than `min_iso_timestamp`."""
    cid = str(parent_conversation_id or "").strip()
    baseline_ts = str(min_iso_timestamp or "").strip()
    if not cid or not baseline_ts:
        return False
    tx = _engine.prefer_full_transcript(_engine.resolve_transcript(cid))
    if tx is None or not tx.is_file():
        return False
    try:
        if tx.stat().st_size > 32 * 1024 * 1024:
            return False
        latest_user_ts = ""
        with tx.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"USER_INPUT"' not in line:
                    continue
                try:
                    row = _engine.json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("source") == "USER_EXPLICIT" and row.get("type") == "USER_INPUT":
                    ts = str(row.get("created_at") or row.get("timestamp") or "").strip()
                    if ts > latest_user_ts:
                        latest_user_ts = ts
        return bool(latest_user_ts and latest_user_ts > baseline_ts)
    except OSError:
        return False
def _child_transcript_terminal_state(execution_id: str) -> str:
    """Classify child transcript tail: COMPLETED_DONE | EMPTY_DONE | ACTIVE | HEADER_ONLY."""
    cid = str(execution_id or "").strip()
    if not cid:
        return "HEADER_ONLY"
    tx = _engine.prefer_full_transcript(_engine.resolve_transcript(cid))
    if tx is None or not tx.is_file():
        return "HEADER_ONLY"
    try:
        size = tx.stat().st_size
        if size == 0 or size > 32 * 1024 * 1024:
            return "HEADER_ONLY"
        with tx.open("rb") as fh:
            fh.seek(max(0, size - 32768))
            if size > 32768:
                fh.readline()
            tail_lines = fh.read().decode("utf-8", errors="replace").splitlines()
        for raw in reversed(tail_lines):
            if not raw.strip():
                continue
            try:
                row = _engine.json.loads(raw)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            src = str(row.get("source") or "").upper()
            rtype = str(row.get("type") or "").upper()
            if src == "MODEL" and rtype in ("PLANNER_RESPONSE", "ASSISTANT_RESPONSE"):
                has_tools = bool(row.get("tool_calls") or row.get("toolCalls"))
                status = str(row.get("status") or "").upper()
                if status == "DONE" and not has_tools:
                    txt = str(row.get("content") or "").strip()
                    if not txt or len(txt) < 16:
                        return "EMPTY_DONE"
                    return "COMPLETED_DONE"
                return "ACTIVE"
        return "HEADER_ONLY"
    except OSError:
        return "HEADER_ONLY"
def _child_transcript_completed(execution_id: str) -> bool:
    """Return True if bound child transcript contains a non-empty completed terminal model response."""
    return _engine._child_transcript_terminal_state(execution_id) == "COMPLETED_DONE"
def _current_task_phase_and_status(repo: Path, plan: dict[str, Any] | None = None) -> tuple[str, str, str]:
    if plan is None:
        try:
            from mutation_guard import active_plan
            plan = active_plan(repo)
        except Exception:
            plan = None
    if not isinstance(plan, dict) or not plan:
        return ("", "IDLE", "")
    tid = str(plan.get("task_id") or "").strip()
    status = str(plan.get("status") or "IDLE").upper()
    phase_id = ""
    phases = plan.get("phases") or []
    active_idx = int(plan.get("active_phase_index") or 0)
    if phases and 0 <= active_idx < len(phases):
        phase_id = str(phases[active_idx].get("id") or "")
    if tid and status == "IMPLEMENTING":
        pstate_f = _engine.task_dir(repo, tid) / "phase-state.json"
        if pstate_f.is_file():
            try:
                cur_pid = str(_engine.read_json(pstate_f).get("current_phase_id") or "").strip()
                if cur_pid:
                    phase_id = cur_pid
            except (OSError, ValueError, _engine.ValidationError):
                pass
    return (tid, status, phase_id)
def record_utility_dispatch(
    repo: Path,
    *,
    agent_type: str,
    role_label: str,
    prompt: str,
    parent_conversation_id: str = "",
    task_id: str = "",
    worker_mode: str = "READ_ONLY",
    wave_id: str = "",
    task_status: str = "",
    phase_id: str = "",
    read_only_specialist: bool = True,
) -> dict[str, Any]:
    parent_cid = str(parent_conversation_id or "").strip()
    tid_cur, st_cur, pid_cur = _engine._current_task_phase_and_status(repo)
    resolved_tid = str(task_id or tid_cur).strip()
    resolved_status = str(task_status or st_cur or "IDLE").upper()
    resolved_pid = str(phase_id or pid_cur).strip()
    resolved_wave = str(wave_id or _engine.uuid.uuid4().hex[:10]).strip()
    user_turns = _engine._count_parent_user_turns(parent_cid)
    planner_turns = _engine._count_parent_planner_turns(parent_cid)
    entry = {
        "wave_id": resolved_wave,
        "agent_type": agent_type,
        "role": role_label,
        "prompt_sha256": _engine._prompt_sha256(prompt),
        "parent_conversation_id": parent_cid,
        "parent_user_turns": user_turns,
        "parent_planner_turns": planner_turns,
        "execution_id": "",
        "task_id": resolved_tid,
        "task_status": resolved_status,
        "phase_id": resolved_pid,
        "worker_mode": worker_mode,
        "read_only_specialist": bool(read_only_specialist),
        "dispatched_at": _engine.utc_now(),
        "dispatched_epoch": _engine.time.time(),
        "completed_at": "",
        "completed_at_epoch": 0.0,
        "wave_completed": False,
        "tool_calls_used": 0,
        "lead_post_reads": 0,
        "lead_edited_after_wave": False,
    }
    try:
        with _engine.StateLock(_engine.state_root(repo)):
            ledger = _engine._load_utility_ledger(repo)
            ledger["entries"].append(entry)
            _engine._save_utility_ledger(repo, ledger)
    except (OSError, _engine.ValidationError):
        pass
    return entry
def record_specialist_dispatch(
    repo: Path,
    plan: dict[str, Any] | None,
    raw_subs: list[Any],
    *,
    parent_conversation_id: str = "",
) -> None:
    """Record on-demand specialist subagents (e.g. qa-diagnostics-agent, android-ui-expert-agent) for step & anti-reread governance."""
    tid, st, pid = _engine._current_task_phase_and_status(repo, plan)
    wave_id = _engine.uuid.uuid4().hex[:10]
    for item in raw_subs:
        if not isinstance(item, dict):
            continue
        raw_t_name = str(item.get("TypeName") or item.get("typeName") or item.get("Role") or item.get("role") or "").strip()
        t_name = _engine.canonical_utility_or_reviewer_role(raw_t_name)
        prompt = str(item.get("Prompt") or item.get("prompt") or "").strip()
        if not t_name or not prompt or t_name in _engine.CORE_ROUTED_REVIEWERS or t_name in _engine.CORE_UTILITY_AGENTS:
            continue
        is_ro = True
        _engine.record_utility_dispatch(
            repo,
            agent_type=_engine.SPECIALIST_AGENT,
            role_label=t_name,
            prompt=prompt,
            parent_conversation_id=parent_conversation_id,
            task_id=tid,
            worker_mode="READ_ONLY" if is_ro else "SPECIALIST",
            wave_id=wave_id,
            task_status=st,
            phase_id=pid,
            read_only_specialist=is_ro,
        )
def _transcript_head_and_dispatch(transcript: Path) -> tuple[bool, str, str]:
    """Return (has_user_explicit_input, sender_parent_id, prompt_sha256) from bounded transcript head."""
    read_path = _engine.prefer_full_transcript(transcript) or transcript
    if not read_path.is_file() or read_path.stat().st_size > 32 * 1024 * 1024:
        return False, "", ""
    has_user = False
    sender_id = ""
    prompt_hash = ""
    seen = 0
    try:
        with read_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                seen += 1
                if seen > 10:
                    break
                try:
                    row = _engine.json.loads(line)
                except ValueError:
                    break
                if not isinstance(row, dict):
                    continue
                if row.get("source") == "USER_EXPLICIT" and row.get("type") == "USER_INPUT" and not prompt_hash:
                    has_user = True
                    break
                if row.get("source") in _engine.ACCEPTED_SYSTEM_SOURCES and row.get("type") == "SYSTEM_MESSAGE" and not prompt_hash:
                    content = str(row.get("content") or "")
                    m = _engine.re.search(
                        r"sender=([A-Za-z0-9_/-]+)\s+priority=MESSAGE_PRIORITY_HIGH\s+content=([\s\S]+?)\n</SYSTEM_MESSAGE>",
                        content,
                    )
                    if m:
                        cand_sender = m.group(1)
                        if "/" not in cand_sender or not _engine._is_invalid_conversation_id(cand_sender):
                            sender_id = cand_sender
                            prompt_hash = _engine._prompt_sha256(m.group(2))
    except OSError:
        return False, "", ""
    return has_user, sender_id, prompt_hash
def utility_subagent_context(repo: Path, conversation_id: str, *, bind: bool = False) -> dict[str, Any] | None:
    """Identify whether `conversation_id` belongs to `harness-scout-agent` or a tracked specialist."""
    env_override = _engine.os.environ.get("HARNESS_UTILITY_AGENT", "").strip()
    if env_override in (*_engine.CORE_UTILITY_AGENTS, _engine.SPECIALIST_AGENT):
        mode_override = _engine.os.environ.get("HARNESS_UTILITY_WORKER_MODE", "READ_ONLY").strip() or "READ_ONLY"
        return {
            "agent_type": env_override,
            "execution_id": conversation_id or "env-utility",
            "worker_mode": mode_override,
            "read_only_specialist": True,
        }

    cid = str(conversation_id or "").strip()
    if not cid:
        return None

    ledger = _engine._load_utility_ledger(repo)
    entries = ledger.get("entries") or []
    if not entries:
        return None

    transcript = _engine.resolve_transcript(cid)
    has_user, sender_id, prompt_hash = (False, "", "")
    if transcript is not None:
        has_user, sender_id, prompt_hash = _engine._transcript_head_and_dispatch(transcript)
        if has_user:
            return None

    # 1. Fast path: already bound execution_id
    for item in reversed(entries):
        if item.get("execution_id") == cid:
            return dict(item)

    # 2. Match via native Antigravity SYSTEM_MESSAGE prompt hash (skipping dispatch_failed waves!)
    if prompt_hash:
        for idx in range(len(entries) - 1, -1, -1):
            item = entries[idx]
            if item.get("dispatch_failed"):
                continue
            if item.get("execution_id") not in ("", None, cid):
                continue
            if item.get("prompt_sha256") != prompt_hash:
                continue
            parent_expected = str(item.get("parent_conversation_id") or "")
            if parent_expected and sender_id and parent_expected != sender_id:
                continue
            matched = dict(item)
            matched["execution_id"] = cid
            if sender_id and not matched.get("parent_conversation_id"):
                matched["parent_conversation_id"] = sender_id
            if bind:
                try:
                    with _engine.StateLock(_engine.state_root(repo)):
                        live = _engine._load_utility_ledger(repo)
                        for live_item in reversed(live.get("entries") or []):
                            if (
                                not live_item.get("dispatch_failed")
                                and live_item.get("prompt_sha256") == prompt_hash
                                and live_item.get("execution_id") in ("", None, cid)
                            ):
                                live_item["execution_id"] = cid
                                if sender_id and not live_item.get("parent_conversation_id"):
                                    live_item["parent_conversation_id"] = sender_id
                                break
                        _engine._save_utility_ledger(repo, live)
                except (OSError, _engine.ValidationError):
                    pass
            return matched
    return None
def _extract_transcript_read_files(repo: Path, transcript: Path | None) -> list[str]:
    """Extract normalized repo-relative paths read via `read_file`/`view_file` in a child subagent transcript."""
    read_path = _engine.prefer_full_transcript(transcript) or transcript
    if read_path is None or not read_path.is_file():
        return []
    seen: list[str] = []
    try:
        if read_path.stat().st_size > 32 * 1024 * 1024:
            return []
        with read_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = _engine.json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                tcs = row.get("tool_calls") or row.get("toolCalls") or []
                if not isinstance(tcs, list):
                    continue
                for tc in tcs:
                    if not isinstance(tc, dict):
                        continue
                    tname = str(tc.get("name") or tc.get("toolName") or "").strip().lower()
                    if tname not in {"read_file", "view_file", "read", "write_to_file", "write_file", "replace_file_content", "multi_replace_file_content", "edit_file", "edit", "multiedit"}:
                        continue
                    targs = tc.get("args") or tc.get("input") or tc.get("arguments") or {}
                    if isinstance(targs, str):
                        try:
                            targs = _engine.json.loads(targs)
                        except ValueError:
                            targs = {}
                    if not isinstance(targs, dict):
                        continue
                    raw_p = str(
                        targs.get("Path") or targs.get("AbsolutePath") or targs.get("file_path") or targs.get("path") or ""
                    ).strip()
                    if not raw_p:
                        continue
                    rel_p = _engine._normalize_repo_rel(repo, raw_p)
                    if rel_p and not rel_p.startswith("..") and rel_p not in seen:
                        seen.append(rel_p)
    except OSError:
        return []
    return seen
def _count_transcript_tool_calls(transcript: Path | None) -> int:
    """Count executed tool calls recorded in a subagent transcript as a reliable ground-truth floor."""
    read_path = _engine.prefer_full_transcript(transcript) or transcript
    if read_path is None or not read_path.is_file():
        return 0
    try:
        if read_path.stat().st_size > 32 * 1024 * 1024:
            return 0
        total = 0
        with read_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = _engine.json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                rtype = str(row.get("type") or "").upper()
                if rtype in {"TOOL_CALL", "TOOL_USE", "FUNCTION_CALL"}:
                    total += 1
                else:
                    tcs = row.get("tool_calls") or row.get("toolCalls")
                    if isinstance(tcs, list) and tcs:
                        total += len(tcs)
        return total
    except OSError:
        return 0
def bind_utility_from_post_tool(repo: Path, payload: dict[str, Any]) -> list[str]:
    """Bind child `execution_id` AND mark completed wave(s) in utility ledger after `invoke_subagent` PostToolUse."""
    bound: list[str] = []
    ledger = _engine._load_utility_ledger(repo)
    entries = ledger.get("entries") or []
    if not entries:
        return bound

    parent_cid = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()
    parent_tx_raw = str(payload.get("transcriptPath") or payload.get("transcript_path") or "").strip()
    brain_dirs: list[Path] = []
    if parent_tx_raw:
        p = Path(parent_tx_raw)
        for anc in p.parents:
            if anc.name == "brain" and anc.is_dir():
                brain_dirs.append(anc)
                break
    if not brain_dirs:
        from antigravity_runtime import candidate_brain_roots
        brain_dirs = [b for b in candidate_brain_roots() if b.is_dir()]

    already_claimed_cids = {
        str(e.get("execution_id") or "")
        for e in entries
        if e.get("execution_id")
    }
    changed = False
    if any(not e.get("execution_id") and not e.get("dispatch_failed") for e in entries):
        for brain in brain_dirs:
            for child_cid, _child_dir in _engine.iter_recent_brain_conversations(brain, limit=24):
                if child_cid in already_claimed_cids:
                    continue
                tx = _engine.resolve_transcript(child_cid)
                if tx is None:
                    continue
                has_user, sender_id, prompt_hash = _engine._transcript_head_and_dispatch(tx)
                if has_user or not prompt_hash:
                    continue
                for item in reversed(entries):
                    if item.get("dispatch_failed") or item.get("execution_id") or item.get("prompt_sha256") != prompt_hash:
                        continue
                    parent_expected = str(item.get("parent_conversation_id") or "")
                    if parent_expected and sender_id and parent_expected != sender_id:
                        continue
                    item["execution_id"] = child_cid
                    already_claimed_cids.add(child_cid)
                    tx_calls = _engine._count_transcript_tool_calls(tx)
                    if tx_calls > int(item.get("tool_calls_used") or 0):
                        item["tool_calls_used"] = tx_calls
                    bound.append(child_cid)
                    changed = True
                    break

    # Mark the latest non-failed wave dispatched by parent_cid (or bound child when parent_cid is blank) as completed
    target_wave_id = ""
    if parent_cid:
        for item in reversed(entries):
            if not item.get("dispatch_failed") and str(item.get("parent_conversation_id") or "") == parent_cid:
                target_wave_id = str(item.get("wave_id") or "")
                break
    elif bound:
        bound_set = set(bound)
        for item in reversed(entries):
            if not item.get("dispatch_failed") and str(item.get("execution_id") or "") in bound_set:
                target_wave_id = str(item.get("wave_id") or "")
                break
    returned_cids: set[str] = set()
    tool_res = payload.get("toolResult") or payload.get("tool_result") or {}
    if isinstance(tool_res, dict):
        top_cid = str(tool_res.get("conversationId") or tool_res.get("conversation_id") or tool_res.get("id") or "").strip()
        if top_cid:
            returned_cids.add(top_cid)
        for sub_item in (tool_res.get("subagents") or []):
            if isinstance(sub_item, dict):
                scid = str(sub_item.get("conversationId") or sub_item.get("conversation_id") or sub_item.get("id") or "").strip()
                if scid:
                    returned_cids.add(scid)

    if target_wave_id:
        wave_size = sum(
            1
            for e in entries
            if not e.get("dispatch_failed")
            and str(e.get("wave_id") or "") == target_wave_id
            and (not parent_cid or str(e.get("parent_conversation_id") or "") == parent_cid)
        )
        now_ts = _engine.time.time()
        cur_turns = _engine._count_parent_user_turns(parent_cid) if parent_cid else 0
        for item in entries:
            if (
                not item.get("dispatch_failed")
                and str(item.get("wave_id") or "") == target_wave_id
                and (not parent_cid or str(item.get("parent_conversation_id") or "") == parent_cid)
            ):
                cid_bound = str(item.get("execution_id") or "")
                tx_b = _engine.resolve_transcript(cid_bound) if cid_bound else None
                if cid_bound and tx_b is not None:
                    tx_calls = _engine._count_transcript_tool_calls(tx_b)
                    if tx_calls > int(item.get("tool_calls_used") or 0):
                        item["tool_calls_used"] = tx_calls
                        changed = True
                    tx_files = _engine._extract_transcript_read_files(repo, tx_b)
                    if tx_files and tx_files != list(item.get("inspected_files") or []):
                        item["inspected_files"] = tx_files
                        changed = True
                t_state = _engine._child_transcript_terminal_state(cid_bound) if (cid_bound and tx_b is not None) else "HEADER_ONLY"
                if t_state == "EMPTY_DONE" and _engine.is_quirk_enabled("201209", repo=repo):
                    item["dispatch_failed"] = True
                    item["empty_terminal_response"] = True
                    item["failure_code"] = "EMPTY_SUBAGENT_TERMINAL_RESPONSE"
                    item["completed_at"] = _engine.utc_now()
                    item["completed_at_epoch"] = now_ts
                    changed = True
                    continue
                child_ready_to_close = (
                    tx_b is None
                    or t_state in {"COMPLETED_DONE", "EMPTY_DONE"}
                    or ((wave_size == 1 or cid_bound in returned_cids) and t_state != "ACTIVE")
                )
                if not item.get("wave_completed") and child_ready_to_close:
                    item["wave_completed"] = True
                    item["completed_at"] = _engine.utc_now()
                    item["completed_at_epoch"] = now_ts
                    if cur_turns > int(item.get("parent_user_turns") or 0):
                        item["parent_user_turns"] = cur_turns
                    changed = True

    if changed:
        try:
            with _engine.StateLock(_engine.state_root(repo)):
                live = _engine._load_utility_ledger(repo)
                live_entries = live.get("entries") or []
                bound_map = {
                    (e.get("wave_id"), e.get("prompt_sha256")): e
                    for e in entries
                }
                for le in live_entries:
                    if le.get("dispatch_failed"):
                        continue
                    src = bound_map.get((le.get("wave_id"), le.get("prompt_sha256")))
                    if src:
                        if src.get("execution_id") and not le.get("execution_id"):
                            le["execution_id"] = src["execution_id"]
                        le["tool_calls_used"] = max(
                            int(le.get("tool_calls_used") or 0),
                            int(src.get("tool_calls_used") or 0),
                        )
                        if src.get("inspected_files"):
                            le["inspected_files"] = list(src["inspected_files"])
                        if src.get("dispatch_failed"):
                            le["dispatch_failed"] = True
                            if src.get("empty_terminal_response"):
                                le["empty_terminal_response"] = True
                            if src.get("failure_code"):
                                le["failure_code"] = str(src["failure_code"])
                            le["completed_at"] = str(src.get("completed_at") or _engine.utc_now())
                            le["completed_at_epoch"] = src.get("completed_at_epoch", _engine.time.time())
                        if src.get("wave_completed") and not le.get("wave_completed"):
                            le["wave_completed"] = True
                            le["completed_at"] = str(src.get("completed_at") or _engine.utc_now())
                            le["completed_at_epoch"] = src.get("completed_at_epoch", _engine.time.time())
                            le["parent_user_turns"] = max(int(le.get("parent_user_turns") or 0), int(src.get("parent_user_turns") or 0))
                _engine._save_utility_ledger(repo, live)
        except (OSError, _engine.ValidationError):
            pass

    return bound
def _latest_invoke_subagent_denial(repo: Path, parent_cid: str, *, max_age_seconds: float = 120.0) -> dict[str, Any] | None:
    """Return latest PreToolUse `invoke_subagent` deny row if not superseded by a later allow (`#640`)."""
    candidates: list[Path] = []
    hook_state_env = _engine.os.environ.get("HARNESS_HOOK_STATE", "").strip()
    if hook_state_env:
        candidates.append(Path(hook_state_env).with_name("audit_log.jsonl"))
    candidates.append(_engine.state_root(repo) / "audit_log.jsonl")
    now = _engine.time.time()
    for audit_path in candidates:
        if not audit_path.is_file():
            continue
        try:
            lines = audit_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
        except OSError:
            continue
        for raw_line in reversed(lines):
            if not raw_line.strip():
                continue
            try:
                rec = _engine.json.loads(raw_line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or str(rec.get("tool") or "").lower() != "invoke_subagent":
                continue
            rec_conv = str(rec.get("conv_hint") or "").strip()
            if parent_cid and rec_conv and rec_conv != parent_cid:
                continue
            ts = float(rec.get("ts") or 0.0)
            if ts and (now - ts) > max_age_seconds:
                return None
            if str(rec.get("decision") or "").lower() == "deny":
                return rec
            return None
    return None
def inspect_and_record_post_tool_subagent_bypass(
    repo: Path,
    payload: dict[str, Any],
    *,
    matched_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Post-hoc audit for antigravity-cli#640 (`PreToolUse` block ignored on `invoke_subagent`).

    Detects when an `invoke_subagent` call actually executed despite a recent PreToolUse denial
    or directly violated active task policy (such as `research`/`explore` when `USE_HARNESS_SCOUT_AGENT`
    applies, unauthorized `harness-worker-agent`, or any subagent in `T0_TRIVIAL`). Records durable
    violations in `.agents/state/tasks/<task_id>/subagent-policy-violations.json` for `final_verifier`.
    """
    try:
        from platform_quirks import is_quirk_enabled
        if not is_quirk_enabled("640", repo=repo):
            return []
    except ImportError:
        pass
    call = payload.get("toolCall") or payload.get("tool_call") or {}
    args = call.get("args") or payload.get("toolArgs") or payload.get("tool_input") or {}
    if isinstance(args, str):
        try:
            args = _engine.json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        args = {}

    raw_subs = args.get("Subagents") or args.get("subagents") or []
    sub_items: list[dict[str, Any]] = (
        [s for s in raw_subs if isinstance(s, dict)]
        if isinstance(raw_subs, list) and raw_subs
        else ([args] if (args.get("TypeName") or args.get("typeName") or args.get("Role") or args.get("role")) else [])
    )
    raw_types = [str(s.get("TypeName") or s.get("typeName") or s.get("Role") or s.get("role") or "").strip() for s in sub_items]
    raw_types = [t for t in raw_types if t]
    canonical_roles = [_engine.canonical_utility_or_reviewer_role(t) for t in raw_types]

    parent_cid = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()
    active_tid = ""
    plan: dict[str, Any] | None = None
    active_f = _engine.state_root(repo) / "active-task.json"
    if active_f.is_file():
        try:
            active_tid = str(_engine.read_json(active_f).get("task_id") or "").strip()
            if active_tid and (_engine.task_dir(repo, active_tid) / "plan.json").is_file():
                plan = _engine.read_json(_engine.task_dir(repo, active_tid) / "plan.json")
        except (OSError, ValueError, _engine.ValidationError):
            plan = None

    violation_codes: list[str] = []
    denial = _engine._latest_invoke_subagent_denial(repo, parent_cid)
    if denial is not None:
        code = str(denial.get("reason_code") or "PRETOOL_DENY_IGNORED").strip()
        violation_codes.append(f"PRETOOL_BYPASS:{code}")

    if raw_types and any(t.lower() in {"research", "explore"} for t in raw_types):
        if (repo / ".agents" / "agents" / _engine.SCOUT_AGENT / "agent.md").is_file() and not _engine.is_utility_agent_unloaded_in_session(repo, parent_cid, _engine.SCOUT_AGENT):
            if not any("USE_HARNESS_SCOUT_AGENT" in c for c in violation_codes):
                violation_codes.append("USE_HARNESS_SCOUT_AGENT_BYPASS")

    if plan and active_tid:
        status_up = str(plan.get("status") or "").strip().upper()
        policy = _engine._resolve_active_policy(repo, active_tid, plan)
        risk_tier = str(policy.get("risk_tier") or plan.get("risk_tier") or "").strip().upper()
        if _engine.RETIRED_WORKER_AGENT in canonical_roles:
            violation_codes.append("UNAUTHORIZED_WORKER_SPAWN")
        routed_reviewers_in_call = [r for r in canonical_roles if r in _engine.CORE_ROUTED_REVIEWERS]
        if routed_reviewers_in_call:
            if risk_tier == "T0_TRIVIAL":
                violation_codes.append("T0_TRIVIAL_REVIEWER_FORBIDDEN")
            elif status_up == "VERIFYING":
                cur_run_f = _engine.task_dir(repo, active_tid) / "current-run.json"
                expected_revs: set[str] = set()
                if cur_run_f.is_file():
                    try:
                        cur_run = _engine.read_json(cur_run_f)
                        run_id_val = str(cur_run.get("run_id") or "")
                        if run_id_val:
                            from review_orchestrator import load_ledger as load_rev_ledger
                            rev_ledger = load_rev_ledger(_engine.task_dir(repo, active_tid), run_id_val)
                            expected_revs = {
                                rn for rn, rd in (rev_ledger.get("reviewers") or {}).items()
                                if isinstance(rd, dict)
                            }
                    except (ImportError, OSError, ValueError, _engine.ValidationError):
                        expected_revs = set()
                if any(r not in expected_revs for r in routed_reviewers_in_call):
                    violation_codes.append("UNAUTHORIZED_REVIEWER_SPAWN")

    if not violation_codes or not active_tid:
        return []

    dedup_codes = list(dict.fromkeys(violation_codes))
    entry = {
        "issue": "antigravity-cli#640",
        "codes": dedup_codes,
        "types": raw_types or canonical_roles,
        "execution_ids": sorted(matched_ids or set()),
        "parent_conversation_id": parent_cid,
        "detected_at": _engine.utc_now(),
    }
    vpath = _engine.task_dir(repo, active_tid) / "subagent-policy-violations.json"
    try:
        with _engine.StateLock(_engine.state_root(repo)):
            store: dict[str, Any] = {"schema_version": 1, "task_id": active_tid, "violations": []}
            if vpath.is_file():
                try:
                    raw_store = _engine.read_json(vpath)
                    if isinstance(raw_store, dict) and isinstance(raw_store.get("violations"), list):
                        store = raw_store
                except (OSError, ValueError, _engine.ValidationError):
                    pass
            store["violations"] = [*list(store.get("violations") or [])[-49:], entry]
            _engine.atomic_write_json(vpath, store)
    except (OSError, _engine.ValidationError):
        return []
    return [entry]
def mark_utility_wave_completed(
    repo: Path,
    parent_conversation_id: str,
    *,
    wave_id: str = "",
    dispatch_failed: bool = False,
) -> None:
    """Explicitly mark the latest (or specified) utility wave as completed (and optionally `dispatch_failed`)."""
    parent_cid = str(parent_conversation_id or "").strip()
    try:
        with _engine.StateLock(_engine.state_root(repo)):
            ledger = _engine._load_utility_ledger(repo)
            entries = ledger.get("entries") or []
            target_wave = wave_id
            if not target_wave:
                for item in reversed(entries):
                    if not parent_cid or str(item.get("parent_conversation_id") or "") == parent_cid:
                        target_wave = str(item.get("wave_id") or "")
                        break
            if not target_wave:
                return
            now_ts = _engine.time.time()
            cur_turns = _engine._count_parent_user_turns(parent_cid) if parent_cid else 0
            for item in entries:
                if (not parent_cid or str(item.get("parent_conversation_id") or "") == parent_cid) and str(item.get("wave_id") or "") == target_wave:
                    item["wave_completed"] = True
                    if dispatch_failed:
                        item["dispatch_failed"] = True
                    if not item.get("completed_at"):
                        item["completed_at"] = _engine.utc_now()
                    if not item.get("completed_at_epoch"):
                        item["completed_at_epoch"] = now_ts
                    if cur_turns > int(item.get("parent_user_turns") or 0):
                        item["parent_user_turns"] = cur_turns
            _engine._save_utility_ledger(repo, ledger)
    except (OSError, _engine.ValidationError):
        pass
def _adaptive_slice_file_count(repo: Path, *, full_task: bool = False) -> int:
    """Return active phase/task file count for scale-adaptive subagent read caps."""
    plan: dict[str, Any] | None = None
    try:
        from mutation_guard import active_plan
        plan = active_plan(repo)
    except (ImportError, OSError, ValueError, TypeError, _engine.ValidationError):
        plan = None
    if not isinstance(plan, dict) or not plan:
        try:
            at_f = _engine.state_root(repo) / "active-task.json"
            if at_f.is_file():
                at_tid = str(_engine.read_json(at_f).get("task_id") or "").strip()
                if at_tid and (_engine.task_dir(repo, at_tid) / "plan.json").is_file():
                    plan = _engine.read_json(_engine.task_dir(repo, at_tid) / "plan.json")
        except (OSError, ValueError, _engine.ValidationError):
            plan = None
    if not isinstance(plan, dict) or not plan:
        return 0
    total_expected = len(plan.get("expected_files") or [])
    status_up = str(plan.get("status") or "").strip().upper()
    if full_task or status_up in {"VERIFYING", "READY_FOR_DELIVERY"}:
        tid_cur = str(plan.get("task_id") or "").strip()
        manifest_len = 0
        if tid_cur:
            try:
                cr_f = _engine.task_dir(repo, tid_cur) / "current-run.json"
                if cr_f.is_file():
                    m_path = Path(str(_engine.read_json(cr_f).get("manifest") or ""))
                    if m_path.is_file():
                        m_doc = _engine.read_json(m_path)
                        t_ch = m_doc.get("task_changes") if "task_changes" in m_doc else m_doc.get("changes")
                        if isinstance(t_ch, (list, dict)):
                            manifest_len = len(t_ch)
            except (OSError, ValueError, _engine.ValidationError):
                manifest_len = 0
        return max(total_expected, manifest_len)
    phases = plan.get("phases")
    if isinstance(phases, list) and phases:
        tid = str(plan.get("task_id") or "").strip()
        completed: set[str] = set()
        cur_pid = ""
        if tid:
            ps_f = _engine.task_dir(repo, tid) / "phase-state.json"
            if ps_f.is_file():
                try:
                    ps = _engine.read_json(ps_f)
                    if isinstance(ps, dict):
                        cur_pid = str(ps.get("current_phase_id") or "").strip()
                        completed = {str(x).strip() for x in (ps.get("completed_phases") or []) if str(x).strip()}
                except (OSError, ValueError, _engine.ValidationError):
                    pass
        cur_len = 0
        if cur_pid:
            for ph in phases:
                if isinstance(ph, dict) and str(ph.get("id") or "") == cur_pid and cur_pid not in completed:
                    pf = ph.get("expected_files") or ph.get("files") or []
                    cur_len = len(pf)
                    break
        idx_len = 0
        try:
            idx = int(plan.get("active_phase_index") or 0)
        except (TypeError, ValueError):
            idx = 0
        if 0 <= idx < len(phases) and isinstance(phases[idx], dict):
            pf = phases[idx].get("expected_files") or phases[idx].get("files") or []
            idx_len = len(pf)
        best_phase_len = max(cur_len, idx_len)
        if best_phase_len > 0:
            return best_phase_len
    return total_expected
def check_and_record_subagent_step_budget(
    repo: Path,
    execution_id: str,
    *,
    kind: str,
    tool_name: str,
    run_id: str = "",
    role: str = "",
) -> tuple[bool, str, str]:
    """Enforce per-subagent tool-call caps across EVERY subagent instance (1st, 2nd, Nth).

    - `SCOUT`: max 24 calls (read/search/graph) -> `SCOUT_STEP_BUDGET_REACHED`
    - `SPECIALIST`: max 24 calls -> `SPECIALIST_STEP_BUDGET_REACHED`
    - `REVIEWER`: max 12 calls (phase review & final review) -> `REVIEWER_STEP_BUDGET_REACHED`
    """
    exec_key = str(execution_id or "").strip()
    if not exec_key:
        return (True, "", "")

    kind_up = str(kind or "").upper()
    t_low = str(tool_name or "").lower()
    read_search_tools = {"view_file", "read_file", "read", "grep_search", "find_by_name", "list_dir", "search_web"}

    if kind_up == "SCOUT":
        if t_low not in (read_search_tools | {"run_command"}):
            return (True, "", "")
        cap = _engine.MAX_SCOUT_TOOL_CALLS
        code = "SCOUT_STEP_BUDGET_REACHED"
        label = _engine.SCOUT_AGENT
        guidance = (
            f"{code}: `{label}` reached the {cap}-call exploration cap. "
            "Stop calling tools immediately and emit your structured file:line architectural digest now as plain assistant text (do NOT call `send_message`)."
        )
    elif kind_up == "SPECIALIST":
        if t_low not in (read_search_tools | {"run_command"}):
            return (True, "", "")
        cap = _engine.MAX_SPECIALIST_TOOL_CALLS
        code = "SPECIALIST_STEP_BUDGET_REACHED"
        label = role or "specialist-subagent"
        guidance = (
            f"{code}: `{label}` reached the {cap}-call diagnostic cap. "
            "Stop calling tools immediately and emit your structured report now as plain assistant text (do NOT call `send_message`)."
        )
    elif kind_up == "REVIEWER":
        if t_low not in (read_search_tools | {"run_command"}):
            return (True, "", "")
        is_final_review = not str(run_id or "").strip().lower().startswith("phase-")
        slice_n = _engine._adaptive_slice_file_count(repo, full_task=is_final_review)
        if slice_n > 8:
            scaled_cap = (slice_n + 6) if is_final_review else ((slice_n // 2) + 8)
            cap = max(_engine.MAX_REVIEWER_TOOL_CALLS, min(36 if is_final_review else 48, scaled_cap))
        else:
            cap = _engine.MAX_REVIEWER_TOOL_CALLS
        code = "REVIEWER_STEP_BUDGET_REACHED"
        label = role or "reviewer-subagent"
        guidance = (
            f"{code}: Reviewer `{label}` reached the {cap}-call verification cap. "
            "Stop calling tools immediately and emit your final `HARNESS_REVIEW_RESULT_V2` JSON response now as plain assistant text (do NOT call `send_message`)."
        )
    else:
        return (True, "", "")

    bucket_key = f"{kind_up}:{run_id}:{role}:{exec_key}"
    path = _engine._step_budgets_path(repo)
    try:
        with _engine.StateLock(_engine.state_root(repo)):
            now = _engine.time.time()
            store: dict[str, Any] = {}
            if path.is_file():
                try:
                    raw = _engine.read_json(path)
                    if isinstance(raw, dict):
                        store = {
                            k: v for k, v in raw.items()
                            if isinstance(v, dict) and (now - float(v.get("updated_epoch") or 0)) <= _engine.LEDGER_TTL_SECONDS
                        }
                except (OSError, ValueError, _engine.ValidationError):
                    store = {}
            rec = store.get(bucket_key)
            if not isinstance(rec, dict):
                rec = {"count": 0, "updated_epoch": now}
            current_count = int(rec.get("count") or 0)
            if current_count >= cap:
                return (False, guidance, code)
            rec["count"] = current_count + 1
            rec["updated_epoch"] = now
            # Keep bounded to 128 entries
            if len(store) >= 128 and bucket_key not in store:
                oldest_k = min(store, key=lambda k: float(store[k].get("updated_epoch") or 0))
                store.pop(oldest_k, None)
            store[bucket_key] = rec
            path.parent.mkdir(parents=True, exist_ok=True)
            _engine.atomic_write_json(path, store)
            if kind_up in {"SCOUT", "SPECIALIST"}:
                u_ledger = _engine._load_utility_ledger(repo)
                u_changed = False
                for u_ent in reversed(u_ledger.get("entries") or []):
                    if not u_ent.get("dispatch_failed") and str(u_ent.get("execution_id") or "") == exec_key:
                        u_ent["tool_calls_used"] = max(int(u_ent.get("tool_calls_used") or 0) + 1, int(rec["count"]))
                        u_changed = True
                        break
                if u_changed:
                    _engine._save_utility_ledger(repo, u_ledger)
    except (OSError, _engine.ValidationError):
        return (True, "", "")
    return (True, "", "")
def _resolve_surgical_web_resume_files(repo: Path, task_id: str, plan: dict[str, Any]) -> list[str]:
    """Return 1..3 normalized file paths when a resumed Web task has small surgical review findings (<48KB)."""
    if not task_id:
        return []
    tdir = _engine.task_dir(repo, task_id)
    candidates: list[str] = []
    meta_f = tdir / "last-review-findings.json"
    if meta_f.is_file():
        try:
            doc = _engine.read_json(meta_f)
            if isinstance(doc, dict):
                candidates = [
                    _engine._normalize_repo_rel(repo, str(x))
                    for x in (doc.get("blocking_files") or [])
                    if str(x).strip()
                ]
        except (OSError, ValueError, _engine.ValidationError):
            candidates = []
    if not candidates and isinstance(plan.get("blocking_findings"), list):
        candidates = [
            _engine._normalize_repo_rel(repo, str(item.get("file") or ""))
            for item in (plan.get("blocking_findings") or [])
            if isinstance(item, dict) and str(item.get("file") or "").strip()
        ]
    if not candidates:
        run_hist_dir = tdir / "run-history"
        run_candidates = sorted(run_hist_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if run_hist_dir.is_dir() else []
        cur_run_f = tdir / "current-run.json"
        if cur_run_f.is_file():
            run_candidates.insert(0, cur_run_f)
        for rf in run_candidates[:3]:
            try:
                rdoc = _engine.read_json(rf)
                snap = str(rdoc.get("delivery_snapshot_sha256") or "")
                rid = str(rdoc.get("run_id") or "")
                if snap and rid:
                    from evidence_store import EvidenceStore
                    rev_art = EvidenceStore(_engine.state_root(repo)).read(snap, rid, "reviews")
                    bf_list = ((rev_art or {}).get("evidence") or {}).get("blocking_findings") or []
                    if bf_list:
                        candidates = [
                            _engine._normalize_repo_rel(repo, str(item.get("file") or ""))
                            for item in bf_list
                            if isinstance(item, dict) and str(item.get("file") or "").strip()
                        ]
                        if candidates:
                            break
            except Exception:
                continue
    unique_files = list(dict.fromkeys(f for f in candidates if f and f != "diff"))
    if not (1 <= len(unique_files) <= 3):
        return []
    mass_bytes = 0
    for rel_f in unique_files:
        if _engine.is_test_file(rel_f):
            continue
        fp = repo / rel_f
        try:
            if fp.is_file() and not fp.is_symlink():
                mass_bytes += fp.stat().st_size
        except OSError:
            pass
    if mass_bytes >= 48 * 1024:
        return []
    return unique_files
def get_subagent_budget_reminder(repo: Path, conversation_id: str, invocation: Any) -> str:
    """Read-only late-turn step budget notice for `harness-scout-agent` (silent on Turn 0 and while >4 calls remain)."""
    if not conversation_id or not (type(invocation) is int and invocation > 0):
        return ""
    try:
        ctx = _engine.utility_subagent_context(repo, conversation_id, bind=False)
    except Exception:
        ctx = None
    if not isinstance(ctx, dict) or str(ctx.get("agent_type") or "") != _engine.SCOUT_AGENT:
        return ""
    exec_key = str(ctx.get("execution_id") or conversation_id).strip()
    if not exec_key:
        return ""
    used = int(ctx.get("tool_calls_used") or 0)
    try:
        sb_path = _engine._step_budgets_path(repo)
        if sb_path.is_file():
            raw = _engine.read_json(sb_path)
            if isinstance(raw, dict):
                bucket_key = f"SCOUT::{_engine.SCOUT_AGENT}:{exec_key}"
                rec = raw.get(bucket_key)
                if isinstance(rec, dict):
                    used = max(used, int(rec.get("count") or 0))
    except (OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
        used = used
    if used >= _engine.MAX_SCOUT_TOOL_CALLS:
        return (
            f"CRITICAL SCOUT_STEP_BUDGET_EXHAUSTED ({used}/{_engine.MAX_SCOUT_TOOL_CALLS} calls used, 0 remaining): "
            "Emit ZERO tool calls in this turn. Synthesize and output your complete structured file:line architectural digest now as plain assistant text."
        )
    if used >= _engine.MAX_SCOUT_TOOL_CALLS - 4:
        rem = _engine.MAX_SCOUT_TOOL_CALLS - used
        return (
            f"[Scout Budget Notice: {rem}/{_engine.MAX_SCOUT_TOOL_CALLS} tool call(s) remaining — "
            "avoid large parallel batches and finish only essential surgical reads before emitting your digest.]"
        )
    return ""
def mark_lead_edit_or_transition(repo: Path, parent_conversation_id: str) -> None:
    """Unlock post-worker read cap when the Lead Architect performs a direct code edit."""
    parent_cid = str(parent_conversation_id or "").strip()
    if not parent_cid:
        return
    try:
        with _engine.StateLock(_engine.state_root(repo)):
            ledger = _engine._load_utility_ledger(repo)
            changed = False
            for item in reversed(ledger.get("entries") or []):
                if str(item.get("parent_conversation_id") or "") == parent_cid:
                    if not item.get("lead_edited_after_wave"):
                        item["lead_edited_after_wave"] = True
                        changed = True
                    break
            if changed:
                _engine._save_utility_ledger(repo, ledger)
    except (OSError, _engine.ValidationError):
        pass
def _is_wave_active_for_lead(
    repo: Path,
    wave_entries: list[dict[str, Any]],
    parent_cid: str,
    plan: dict[str, Any] | None,
) -> bool:
    """Return True if a subagent wave has completed and its post-subagent anti-reread window is still active."""
    if not wave_entries or all(bool(e.get("dispatch_failed")) for e in wave_entries):
        return False
    sample = wave_entries[-1]
    # Check whether the wave has completed (via PostToolUse mark OR bound child DONE transcript)
    wave_done = any(bool(e.get("wave_completed")) for e in wave_entries)
    if not wave_done:
        bound_ids = [str(e.get("execution_id") or "") for e in wave_entries if e.get("execution_id")]
        if bound_ids and all(_engine._child_transcript_completed(bid) for bid in bound_ids):
            wave_done = True
            _engine.mark_utility_wave_completed(repo, parent_cid, wave_id=str(sample.get("wave_id") or ""))
    if not wave_done:
        return False

    if any(bool(e.get("lead_edited_after_wave")) for e in wave_entries):
        return False

    # 1. Expire automatically as soon as the developer sends a new USER_INPUT message in chat
    cur_user_turns = _engine._count_parent_user_turns(parent_cid)
    recorded_turns = max(int(e.get("parent_user_turns") or 0) for e in wave_entries)
    if cur_user_turns > recorded_turns:
        return False

    tid_now, status_now, pid_now = _engine._current_task_phase_and_status(repo, plan)
    # Expire anti-reread window if developer switched mid-task to Manual Web-Relay (`web-apply`) after the subagent wave
    if tid_now:
        wr_receipt = _engine.task_dir(repo, tid_now) / "web-relay-receipt.json"
        if wr_receipt.is_file():
            try:
                wr_doc = _engine.read_json(wr_receipt)
                wr_at = str(wr_doc.get("applied_at") or "")
                wave_at = max(str(e.get("completed_at") or e.get("dispatched_at") or "") for e in wave_entries)
                if wr_at and (not wave_at or wr_at >= wave_at):
                    return False
            except (OSError, ValueError, _engine.ValidationError):
                pass
    a_type = str(sample.get("agent_type") or "")
    rec_status = str(sample.get("task_status") or "IDLE").upper()
    rec_tid = str(sample.get("task_id") or "")
    rec_pid = str(sample.get("phase_id") or "")

    pre_impl_states = {"", "IDLE", "DRAFT", "AWAITING_DEVELOPER_APPROVAL", "APPROVED"}
    if a_type == _engine.SCOUT_AGENT:
        if rec_status in pre_impl_states:
            return status_now in pre_impl_states
        if rec_status == "IMPLEMENTING":
            return status_now == "IMPLEMENTING" and tid_now == rec_tid and pid_now == rec_pid
        return status_now == rec_status and tid_now == rec_tid

    if a_type == _engine.SPECIALIST_AGENT:
        if status_now != "IMPLEMENTING" or tid_now != rec_tid or pid_now != rec_pid:
            return False
        if rec_pid and tid_now:
            pstate_f = _engine.task_dir(repo, tid_now) / "phase-state.json"
            if pstate_f.is_file():
                try:
                    ps_data = _engine.read_json(pstate_f)
                    sub = str((ps_data.get("phase_substates") or {}).get(rec_pid) or "")
                    if sub in {"PHASE_REVIEWING", "PHASE_REVIEW_BLOCKED", "PHASE_COMPLETE"}:
                        return False
                except (OSError, ValueError, _engine.ValidationError):
                    pass
        return True

    return False
def _is_exempt_lead_target(repo: Path, raw_target: str) -> bool:
    cleaned = str(raw_target or "").strip()
    if not cleaned:
        return False
    try:
        root = repo.resolve()
        cand = Path(cleaned).expanduser().resolve() if Path(cleaned).expanduser().is_absolute() else (root / cleaned).resolve()
        if not cand.is_relative_to(root):
            # External user document (e.g. Desktop markdown spec) is always exempt
            return True
        rel = cand.relative_to(root).as_posix()
    except OSError:
        rel = _engine.re.sub(r"^(?:\./)+", "", cleaned.replace("\\", "/")).lstrip("/")
    rel_low = rel.lower()
    if rel_low.startswith(_engine._EXEMPT_REPO_READ_PREFIXES):
        return True
    if Path(rel_low).name in {"plan.md", "review-package.md", "phase-review-package.md", "agents.md", "gemini.md"}:
        return True
    return False
def _is_lead_owned_impl_target(repo: Path, raw_target: str, plan: dict[str, Any] | None = None) -> bool:
    """Return True when the active task is `IMPLEMENTING` and the Lead Architect directly owns `raw_target`."""
    cleaned = str(raw_target or "").strip()
    if not cleaned:
        return False
    rel = _engine._normalize_repo_rel(repo, cleaned)
    if not rel:
        return False
    tid, status, pid = _engine._current_task_phase_and_status(repo, plan)
    if not tid or status != "IMPLEMENTING":
        return False
    ledger = _engine._load_utility_ledger(repo)
    if any(
        isinstance(e, dict)
        and not bool(e.get("dispatch_failed"))
        and str(e.get("agent_type") or "") == _engine.SPECIALIST_AGENT
        and str(e.get("task_id") or "") == tid
        and str(e.get("phase_id") or "") == pid
        and not bool(e.get("lead_edited_after_wave"))
        for e in (ledger.get("entries") or [])
    ):
        return False
    try:
        pol = _engine.evaluate_delegation_policy(repo, task_id=tid, plan=plan)
    except Exception:
        return False
    strat = str(pol.get("strategy") or "")
    if strat not in {
        "INLINE_LEAD_DIRECT",
        "TRIVIAL_INLINE_LEAD",
        "CONFLICT_INLINE_LEAD",
        "CAPTURE_RED_INLINE_LEAD",
        "INLINE_LEAD_REMOTE_QUOTA_GUARD",
    }:
        return False
    if plan is None:
        p_file = _engine.task_dir(repo, tid) / "plan.json"
        if p_file.is_file():
            try:
                plan = _engine.read_json(p_file)
            except Exception:
                plan = {}
    raw_t = list(pol.get("target_files") or (plan or {}).get("expected_files") or [])
    if not raw_t:
        return False
    norm_owned = {_engine._normalize_repo_rel(repo, str(f)).lower() for f in raw_t if f}
    return rel.lower() in norm_owned
def check_and_record_lead_post_subagent_read(
    repo: Path,
    parent_conversation_id: str,
    *,
    tool_name: str,
    args: dict[str, Any],
    command: str = "",
    plan: dict[str, Any] | None = None,
) -> tuple[bool, str, str]:
    """Prevent the Lead Model from re-analyzing the codebase after ANY Scout, Worker, or Specialist wave returns.

    Applies across ALL waves (Wave 1, Wave 2, ..., Wave N) and resets cleanly on new developer
    `USER_INPUT` turns, phase transitions (`p1 -> p2`), lifecycle transitions (`IDLE -> IMPLEMENTING`),
    or Lead Architect code edits.
    """
    parent_cid = str(parent_conversation_id or "").strip()
    if not parent_cid:
        return (True, "", "")

    t_low = str(tool_name or "").lower()
    is_view = t_low in {"view_file", "read_file", "read"}
    is_search = t_low in {"grep_search", "find_by_name", "list_dir"}
    is_graph_cmd = t_low == "run_command" and bool(_engine._LEAD_GRAPH_OR_CONTEXT_CMD_RE.search(str(command or "")))
    if not (is_view or is_search or is_graph_cmd):
        return (True, "", "")

    target = ""
    if is_view or is_search:
        for k in (
            "AbsolutePath", "absolutePath", "TargetFile", "targetFile", "Path", "path",
            "file_path", "filePath", "SearchPath", "searchPath", "SearchDirectory",
            "searchDirectory", "DirectoryPath", "directoryPath",
        ):
            if args.get(k):
                target = str(args[k])
                break
        if target and (_engine._is_exempt_lead_target(repo, target) or _engine._is_lead_owned_impl_target(repo, target, plan)):
            return (True, "", "")

    ledger = _engine._load_utility_ledger(repo)
    entries = [
        e for e in (ledger.get("entries") or [])
        if isinstance(e, dict) and str(e.get("parent_conversation_id") or "") == parent_cid
    ]
    if not entries:
        return (True, "", "")

    latest_wave_id = str(entries[-1].get("wave_id") or "")
    if not latest_wave_id:
        return (True, "", "")
    wave_entries = [e for e in entries if str(e.get("wave_id") or "") == latest_wave_id]
    if not _engine._is_wave_active_for_lead(repo, wave_entries, parent_cid, plan):
        return (True, "", "")

    sample = wave_entries[-1]
    a_type = str(sample.get("agent_type") or "")

    # Nonexistent paths return `file does not exist` in 0ms without loading file tokens; never burn post-scout read slots on path typos.
    if is_view and target:
        try:
            cand = Path(target).expanduser().resolve() if Path(target).expanduser().is_absolute() else (repo / target).resolve()
            if not cand.exists():
                return (True, "", "")
            if cand.is_file() and cand.suffix.lower() in {".kt", ".kts", ".java", ".swift", ".xml"}:
                total_lines = cand.read_text(encoding="utf-8", errors="replace").count("\n") + 1
                if total_lines > _engine.LARGE_SOURCE_FILE_LINE_THRESHOLD:
                    start_ln = args.get("StartLine") or args.get("startLine") or args.get("offset")
                    end_ln = args.get("EndLine") or args.get("endLine")
                    limit_ln = args.get("limit")
                    span = total_lines
                    if start_ln is not None and end_ln is not None:
                        span = max(1, int(end_ln) - int(start_ln) + 1)
                    elif limit_ln is not None:
                        span = max(1, int(limit_ln))
                    if span > _engine.MAX_POST_SUBAGENT_VIEW_LINES:
                        rel_disp = _engine._normalize_repo_rel(repo, str(cand))
                        return (
                            False,
                            f"POST_SUBAGENT_FULL_FILE_READ_BLOCKED: `{rel_disp}` has {total_lines} lines (requested {span} lines) "
                            f"after `{sample.get('role') or a_type}` already analyzed this scope. "
                            "Do NOT re-read large files in 250+ line chunks on the Lead Model — trust and synthesize the subagent's digest directly, "
                            f"or inspect one specific declaration via `python .agents/harness.py symbol outline --file {rel_disp}` / `symbol read` (or `view_file` <=150 lines).",
                            "POST_SUBAGENT_FULL_FILE_READ_BLOCKED",
                        )
        except (OSError, ValueError, TypeError):
            pass

    wave_inspected_files: set[str] = set()
    for e in wave_entries:
        for inf in (e.get("inspected_files") or []):
            if isinstance(inf, str) and inf.strip():
                wave_inspected_files.add(inf.strip())
    rel_target = _engine._normalize_repo_rel(repo, str(target)) if (is_view and target) else ""
    wave_inspected_cmp = {p.lower() for p in wave_inspected_files} if _engine.os.name == "nt" else wave_inspected_files
    rel_target_cmp = rel_target.lower() if _engine.os.name == "nt" else rel_target
    is_unread_gap_target = bool(
        a_type in {_engine.SCOUT_AGENT, _engine.SPECIALIST_AGENT}
        and is_view
        and rel_target
        and wave_inspected_files
        and rel_target_cmp not in wave_inspected_cmp
    )
    if is_unread_gap_target:
        unread_used = max(int(e.get("lead_unread_post_reads") or 0) for e in wave_entries)
        if unread_used < _engine.MAX_LEAD_UNREAD_POST_SCOUT_READS:
            try:
                with _engine.StateLock(_engine.state_root(repo)):
                    live = _engine._load_utility_ledger(repo)
                    for le in live.get("entries") or []:
                        if str(le.get("parent_conversation_id") or "") == parent_cid and str(le.get("wave_id") or "") == latest_wave_id:
                            le["lead_unread_post_reads"] = unread_used + 1
                    _engine._save_utility_ledger(repo, live)
            except (OSError, _engine.ValidationError):
                pass
            return (True, "", "")

    used_reads = max(int(e.get("lead_post_reads") or 0) for e in wave_entries)
    if used_reads >= _engine.MAX_LEAD_POST_SUBAGENT_READS:
        if a_type == _engine.SCOUT_AGENT:
            return (
                False,
                f"POST_SCOUT_REREAD_CAP_REACHED: `{_engine.SCOUT_AGENT}` wave `{latest_wave_id}` already returned its file:line digest and "
                f"all {_engine.MAX_LEAD_POST_SUBAGENT_READS} surgical gap checks were used. Do NOT re-analyze the codebase on the Lead Model — "
                "synthesize your answer in chat (or run `task draft` if implementation was requested) immediately from the scout's findings.",
                "POST_SCOUT_REREAD_CAP_REACHED",
            )
        return (
            False,
            f"POST_SPECIALIST_REREAD_CAP_REACHED: Specialist `{sample.get('role')}` wave `{latest_wave_id}` already returned its report and "
            f"all {_engine.MAX_LEAD_POST_SUBAGENT_READS} surgical gap checks were used. Act on the specialist's findings directly without re-reading the codebase.",
            "POST_SPECIALIST_REREAD_CAP_REACHED",
        )

    # Record surgical read slot usage across this wave_id
    try:
        with _engine.StateLock(_engine.state_root(repo)):
            live = _engine._load_utility_ledger(repo)
            for le in live.get("entries") or []:
                if str(le.get("parent_conversation_id") or "") == parent_cid and str(le.get("wave_id") or "") == latest_wave_id:
                    le["lead_post_reads"] = used_reads + 1
            _engine._save_utility_ledger(repo, live)
    except (OSError, _engine.ValidationError):
        pass
    return (True, "", "")
def check_post_reviewer_reread_guard(
    repo: Path,
    parent_conversation_id: str,
    *,
    tool_name: str,
    args: dict[str, Any],
    command: str = "",
    plan: dict[str, Any] | None = None,
) -> tuple[bool, str, str]:
    """Prevent the Lead Model from re-reading application source files while reviewers are finished and awaiting `complete-all` / `assemble`."""
    parent_cid = str(parent_conversation_id or "").strip()
    if not parent_cid:
        return (True, "", "")
    t_low = str(tool_name or "").lower()
    is_view = t_low in {"view_file", "read_file", "read"}
    is_search = t_low in {"grep_search", "find_by_name", "list_dir"}
    is_graph_cmd = t_low == "run_command" and bool(_engine._LEAD_GRAPH_OR_CONTEXT_CMD_RE.search(str(command or "")))
    if not (is_view or is_search or is_graph_cmd):
        return (True, "", "")

    if is_view or is_search:
        for k in (
            "AbsolutePath", "absolutePath", "TargetFile", "targetFile", "Path", "path",
            "file_path", "filePath", "SearchPath", "searchPath", "SearchDirectory",
            "searchDirectory", "DirectoryPath", "directoryPath",
        ):
            if args.get(k) and _engine._is_exempt_lead_target(repo, str(args[k])):
                return (True, "", "")

    tid, status, phase_id = _engine._current_task_phase_and_status(repo, plan)
    if not tid or status not in {"VERIFYING", "IMPLEMENTING"}:
        return (True, "", "")

    try:
        from reviewer_host import active_reviews, _load_ledger
        for run, ledger_path in active_reviews(repo):
            if str(run.get("task_id") or "") != tid or not ledger_path.is_file():
                continue
            ledger = _load_ledger(run, ledger_path)
            revs = ledger.get("reviewers") or {}
            if not revs:
                continue
            verdicts: list[str] = []
            has_findings = False
            all_finished = True
            for r_role, d in revs.items():
                if not isinstance(d, dict):
                    all_finished = False
                    continue
                st = str(d.get("state") or "")
                v = str(d.get("verdict") or "")
                f_list = d.get("findings") or []
                if st == "INGESTED" and not v:
                    res_p = ledger_path.parent / "results" / f"{r_role}.json"
                    if res_p.is_file():
                        res_doc = _engine.read_json(res_p)
                        inner = res_doc.get("result") if isinstance(res_doc.get("result"), dict) else res_doc
                        v = str(inner.get("verdict") or "")
                        f_list = inner.get("findings") or []
                if v == "FINDINGS" or f_list:
                    has_findings = True
                if st in {"COMPLETED", "INGESTED"} and v:
                    verdicts.append(v)
                else:
                    all_finished = False
            # If any reviewer has FINDINGS, do not block reads (task will block/resume for fixes)
            if has_findings:
                return (True, "", "")
            # Case 1: All reviewers completed/ingested with PASS -> advance to next phase / assemble, do NOT re-read code
            # UNLESS the developer explicitly sent a brand-new USER_INPUT follow-up after the reviews completed!
            if all_finished and verdicts and all(v == "PASS" for v in verdicts):
                latest_rev_ts = max(
                    [
                        str(d.get("completed_at") or d.get("ingested_at") or d.get("updated_at") or "")
                        for d in revs.values()
                        if isinstance(d, dict)
                    ]
                    + [str(ledger.get("updated_at") or run.get("created_at") or "")]
                )
                if _engine._parent_has_user_input_after(parent_cid, latest_rev_ts):
                    return (True, "", "")
                if status in {"VERIFYING", "IMPLEMENTING"}:
                    return (
                        False,
                        "POST_REVIEW_REREAD_BLOCKED: All specialist reviewers already passed. Do NOT re-read source files on the Lead Model — "
                        "follow NEXT_ACTION (`begin-next-phase` / `prepare-verification` / `assemble` / `device install-start`) immediately "
                        "(or run `python .agents/harness.py task resume` first if applying a developer-requested change).",
                        "POST_REVIEW_REREAD_BLOCKED",
                    )
            # Case 2: Dispatched reviewers whose transcripts are all finished (`DONE`) -> ingest verdicts first instead of reading code!
            dispatched = [d for d in revs.values() if isinstance(d, dict) and d.get("state") == "DISPATCHED"]
            if dispatched and all(d.get("execution_id") and _engine._child_transcript_completed(str(d["execution_id"])) for d in dispatched):
                ingest_cmd = (
                    f"python .agents/harness.py phase-review complete-all --task-id {tid} --phase-id {run.get('phase_id')}"
                    if run.get("phase_id")
                    else f"python .agents/harness.py review complete-all --task {tid}"
                )
                return (
                    False,
                    f"POST_REVIEW_REREAD_BLOCKED: Reviewer subagents have finished. Run `{ingest_cmd}` immediately before inspecting any source files.",
                    "POST_REVIEW_REREAD_BLOCKED",
                )
    except Exception:
        return (True, "", "")
    return (True, "", "")
def pending_post_subagent_directive(repo: Path, conversation_id: str) -> tuple[str, str]:
    """Return `(wave_state_key, directive)` for `pre_invocation_reminder.py` right after any subagent wave completes."""
    cid = str(conversation_id or "").strip()
    if not cid:
        return ("", "")
    try:
        from mutation_guard import active_plan
        plan = active_plan(repo)
    except Exception:
        plan = None
    if plan is None:
        try:
            at_f = _engine.state_root(repo) / "active-task.json"
            if at_f.is_file():
                at_id = str(_engine.read_json(at_f).get("task_id") or "").strip()
                if at_id and (_engine.task_dir(repo, at_id) / "plan.json").is_file():
                    plan = _engine.read_json(_engine.task_dir(repo, at_id) / "plan.json")
        except (OSError, ValueError, _engine.ValidationError):
            plan = None

    ledger = _engine._load_utility_ledger(repo)
    entries = [
        e for e in (ledger.get("entries") or [])
        if isinstance(e, dict) and str(e.get("parent_conversation_id") or "") == cid
    ]
    if entries:
        latest_wave_id = str(entries[-1].get("wave_id") or "")
        wave_entries = [e for e in entries if str(e.get("wave_id") or "") == latest_wave_id]
        if latest_wave_id and _engine._is_wave_active_for_lead(repo, wave_entries, cid, plan):
            a_type = str(wave_entries[-1].get("agent_type") or "")
            rem = max(0, _engine.MAX_LEAD_POST_SUBAGENT_READS - max(int(e.get("lead_post_reads") or 0) for e in wave_entries))
            if a_type == _engine.SCOUT_AGENT:
                return (
                    f"scout-{latest_wave_id}",
                    f"POST-SCOUT ANTI-REREAD ACTIVE (wave `{latest_wave_id}`): Synthesize the scout's file:line digest directly in chat "
                    f"(or run `task draft` if implementation was requested). Do NOT re-run `graph` or re-read files already analyzed by the scout "
                    f"(hard hook cap: {rem} surgical <=200-line gap checks remaining).",
                )
            return (
                f"spec-{latest_wave_id}",
                f"POST-SPECIALIST ANTI-REREAD ACTIVE (`{wave_entries[-1].get('role')}`): Act directly on the specialist's findings without re-reading analyzed files ({rem} surgical checks remaining).",
            )
    return ("", "")
