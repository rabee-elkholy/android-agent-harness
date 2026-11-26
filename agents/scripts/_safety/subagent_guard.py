"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine

_HARD_DENIED_SUBAGENT_ROLES = frozenset({"self", "harness-worker-agent"})
_SCOUT_REDIRECT_ROLES = frozenset({"research", "explore"})
_HOST_AUXILIARY_TTL_SECONDS = 24 * 3600
_HOST_AUXILIARY_UNBOUND_SEND_TTL_SECONDS = 2 * 3600
_HOST_AUXILIARY_MAX_ENTRIES = 64
_REVIEW_BRIEF_SPOOF_RE = _engine.re.compile(
    r"(?:HARNESS_REVIEW_RESULT_V2|brief-(?:bug-test|security-perf|arch-regression|spec-compliance)-reviewer-agent|phase-brief-)",
    _engine.re.IGNORECASE,
)


def _harness_governed_roles() -> set[str]:
    return (
        set(_engine.CORE_ROUTED_REVIEWERS)
        | set(_engine.CORE_UTILITY_AGENTS)
        | set(_engine.ON_DEMAND_SPECIALIST_AGENTS)
    )


def _extract_subagent_type_and_role(item: Any) -> tuple[str, str, str, str]:
    if not isinstance(item, dict):
        return "", "", "", ""
    raw_type = str(item.get("TypeName") or item.get("typeName") or "").strip()
    raw_role = str(item.get("Role") or item.get("role") or "").strip()
    canon_type = _engine._canonical_subagent_role(raw_type) if raw_type else ""
    canon_role = _engine._canonical_subagent_role(raw_role) if raw_role else ""
    return raw_type, raw_role, canon_type, canon_role


def _item_touches_harness_or_denied(
    item: Any,
    *,
    extra_reviewer_roles: set[str] | frozenset[str] = frozenset(),
) -> bool:
    """Return True if a subagent entry targets any harness-governed, denied, or reviewer-like role."""
    if not isinstance(item, dict):
        return True
    raw_type, raw_role, canon_type, canon_role = _extract_subagent_type_and_role(item)
    if not raw_type:
        return True
    governed = _harness_governed_roles() | set(extra_reviewer_roles)
    blocked_low = {r.lower() for r in governed} | _HARD_DENIED_SUBAGENT_ROLES | _SCOUT_REDIRECT_ROLES
    for cand in (raw_type, raw_role, canon_type, canon_role):
        if cand and (cand in governed or cand.lower() in blocked_low):
            return True
    prompt_val = str(item.get("Prompt") or item.get("prompt") or "")
    if prompt_val and _REVIEW_BRIEF_SPOOF_RE.search(prompt_val):
        return True
    return False


def _host_auxiliary_ledger_path(repo: Path) -> Path:
    return _engine.state_root(repo) / "host-auxiliary-subagents.json"


def _load_host_auxiliary_ledger(repo: Path) -> dict[str, Any]:
    path = _host_auxiliary_ledger_path(repo)
    if not path.is_file():
        return {"schema_version": 1, "entries": []}
    try:
        data = _engine.read_json(path)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    except (OSError, ValueError, _engine.ValidationError):
        pass
    return {"schema_version": 1, "entries": []}


def _save_host_auxiliary_ledger(repo: Path, data: dict[str, Any]) -> None:
    from _vnext_common import atomic_write_json

    now = _engine.time.time()
    kept = [
        e for e in (data.get("entries") or [])
        if isinstance(e, dict) and (now - float(e.get("dispatched_epoch") or 0)) <= _HOST_AUXILIARY_TTL_SECONDS
    ][-_HOST_AUXILIARY_MAX_ENTRIES:]
    path = _host_auxiliary_ledger_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {"schema_version": 1, "entries": kept})


def record_host_auxiliary_dispatch(
    repo: Path,
    items: list[dict[str, Any]],
    *,
    parent_conversation_id: str = "",
) -> None:
    """Persist pending host-auxiliary subagent dispatches so `send_message` can safely resume them."""
    try:
        from evidence_store import StateLock

        now = _engine.time.time()
        parent_cid = str(parent_conversation_id or "").strip()
        with StateLock(_engine.state_root(repo)):
            ledger = _load_host_auxiliary_ledger(repo)
            entries = list(ledger.get("entries") or [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                raw_type = str(item.get("TypeName") or item.get("typeName") or "").strip()
                raw_role = str(item.get("Role") or item.get("role") or raw_type).strip()
                if not raw_type:
                    continue
                entries.append({
                    "type_name": raw_type,
                    "role": raw_role,
                    "parent_conversation_id": parent_cid,
                    "execution_id": "",
                    "dispatched_epoch": now,
                    "dispatch_failed": False,
                })
            ledger["entries"] = entries
            _save_host_auxiliary_ledger(repo, ledger)
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        pass


def _is_known_harness_execution_id(repo: Path, execution_id: str) -> bool:
    """Return True when `execution_id` belongs to a reviewer, scout, or specialist subagent."""
    cid = str(execution_id or "").strip()
    if not cid:
        return False
    try:
        from reviewer_host import _load_ledger, active_reviews

        for run, ledger_path in active_reviews(repo):
            if not ledger_path.is_file():
                continue
            try:
                ledger = _load_ledger(run, ledger_path)
            except _engine.ValidationError:
                continue
            for entry in (ledger.get("reviewers") or {}).values():
                if isinstance(entry, dict) and str(entry.get("execution_id") or "").strip() == cid:
                    return True
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        pass
    try:
        u_path = _engine.state_root(repo) / "utility-subagents.json"
        if u_path.is_file():
            u_data = _engine.read_json(u_path)
            for entry in (u_data.get("entries") or []):
                if isinstance(entry, dict) and str(entry.get("execution_id") or "").strip() == cid:
                    return True
    except (OSError, ValueError, _engine.ValidationError):
        pass
    return False


def bind_host_auxiliary_from_post_tool(
    repo: Path,
    payload: dict[str, Any],
    *,
    matched_ids: set[str] | None = None,
    failed: bool = False,
) -> list[str]:
    """Bind returned `conversationId`s (or mark `dispatch_failed`) for pending host-auxiliary dispatches."""
    bound: list[str] = []
    try:
        from evidence_store import StateLock

        parent_cid = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()
        call = payload.get("toolCall") or payload.get("tool_call") or {}
        if not isinstance(call, dict):
            call = {}
        args = call.get("args") or payload.get("toolArgs") or payload.get("tool_input") or {}
        if isinstance(args, str):
            try:
                args = _engine.json.loads(args)
            except ValueError:
                args = {}
        raw_subs, _ = _normalize_subagent_items(args if isinstance(args, dict) else {})
        call_types = [
            str(s.get("TypeName") or s.get("typeName") or "").strip()
            for s in raw_subs
            if isinstance(s, dict) and str(s.get("TypeName") or s.get("typeName") or "").strip()
        ]

        with StateLock(_engine.state_root(repo)):
            ledger = _load_host_auxiliary_ledger(repo)
            entries = list(ledger.get("entries") or [])
            if not entries:
                return bound
            changed = False
            if failed:
                to_fail = len(call_types) or 1
                for entry in reversed(entries):
                    if to_fail <= 0:
                        break
                    if not isinstance(entry, dict) or entry.get("execution_id") or entry.get("dispatch_failed"):
                        continue
                    if parent_cid and entry.get("parent_conversation_id") and entry.get("parent_conversation_id") != parent_cid:
                        continue
                    if call_types and str(entry.get("type_name") or "") not in call_types:
                        continue
                    entry["dispatch_failed"] = True
                    changed = True
                    to_fail -= 1
            elif matched_ids:
                claimed = {
                    str(e.get("execution_id") or "").strip()
                    for e in entries
                    if isinstance(e, dict) and e.get("execution_id")
                }
                free_ids = [
                    cid for cid in sorted(matched_ids)
                    if cid
                    and cid != parent_cid
                    and cid not in claimed
                    and not _is_known_harness_execution_id(repo, cid)
                ]
                for cid in free_ids:
                    for entry in reversed(entries):
                        if not isinstance(entry, dict) or entry.get("execution_id") or entry.get("dispatch_failed"):
                            continue
                        if parent_cid and entry.get("parent_conversation_id") and entry.get("parent_conversation_id") != parent_cid:
                            continue
                        if call_types and str(entry.get("type_name") or "") not in call_types:
                            continue
                        entry["execution_id"] = cid
                        claimed.add(cid)
                        bound.append(cid)
                        changed = True
                        break
            if changed:
                ledger["entries"] = entries
                _save_host_auxiliary_ledger(repo, ledger)
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        return bound
    return bound


def _check_host_auxiliary_send_message(
    repo: Path,
    args: dict[str, Any],
    *,
    caller_conversation_id: str = "",
) -> tuple[bool, str, str]:
    """Return `(allowed, reason, reason_code)` when `send_message` targets a tracked host-auxiliary subagent."""
    recipient = str(args.get("Recipient") or args.get("recipient") or "").strip()
    message = str(args.get("Message") or args.get("message") or "").strip()
    caller_cid = str(caller_conversation_id or "").strip()
    if not recipient or not message:
        return (False, "", "")
    if caller_cid and recipient == caller_cid:
        return (False, "", "")
    if _is_known_harness_execution_id(repo, recipient):
        return (False, "", "")

    try:
        from evidence_store import StateLock

        now = _engine.time.time()
        matched_type = ""
        with StateLock(_engine.state_root(repo)):
            ledger = _load_host_auxiliary_ledger(repo)
            entries = list(ledger.get("entries") or [])
            known_parents = {
                str(e.get("parent_conversation_id") or "").strip()
                for e in entries
                if isinstance(e, dict) and e.get("parent_conversation_id")
            }
            # Pass 1: exact bound execution_id match
            for entry in reversed(entries):
                if not isinstance(entry, dict) or entry.get("dispatch_failed"):
                    continue
                if str(entry.get("execution_id") or "").strip() != recipient:
                    continue
                p_cid = str(entry.get("parent_conversation_id") or "").strip()
                if caller_cid and p_cid and p_cid != caller_cid:
                    continue
                matched_type = str(entry.get("type_name") or "host-auxiliary")
                break
            # Pass 2: recent unbound fallback when host omitted toolResult in PostToolUse
            if not matched_type and caller_cid and recipient not in known_parents:
                for entry in reversed(entries):
                    if not isinstance(entry, dict) or entry.get("dispatch_failed") or entry.get("execution_id"):
                        continue
                    if str(entry.get("parent_conversation_id") or "").strip() != caller_cid:
                        continue
                    if (now - float(entry.get("dispatched_epoch") or 0)) > _HOST_AUXILIARY_UNBOUND_SEND_TTL_SECONDS:
                        continue
                    entry["execution_id"] = recipient
                    matched_type = str(entry.get("type_name") or "host-auxiliary")
                    ledger["entries"] = entries
                    _save_host_auxiliary_ledger(repo, ledger)
                    break
        if not matched_type:
            return (False, "", "")
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        return (False, "", "")

    from integrations.external_write_policy import sensitive_values

    if sensitive_values([message]):
        return (
            False,
            f"SENSITIVE_SUBAGENT_PROMPT_BLOCKED: Denied `send_message` to host auxiliary subagent '{matched_type}' carrying credential, token, or signing file path.",
            "SENSITIVE_SUBAGENT_PROMPT_BLOCKED",
        )
    return (
        True,
        f"Resuming tracked host auxiliary subagent '{matched_type}' via send_message.",
        "HOST_AUXILIARY_SEND_MESSAGE_ALLOWED",
    )


def _validate_and_allow_host_auxiliary(
    raw_subs: list[Any],
    tool_name: str,
    *,
    parent_conversation_id: str = "",
) -> None:
    """Validate and allow a pure batch of non-harness host auxiliary subagents (e.g., `browser`, `image-generator`)."""
    if not raw_subs:
        _engine.emit("deny", "No subagent entry specified in invoke_subagent.", tool=tool_name, reason_code="SUBAGENT_ROSTER_EMPTY")
        return
    if len(raw_subs) > 5:
        _engine.emit(
            "deny",
            f"Subagent batch size {len(raw_subs)} exceeds the safety limit of 5.",
            tool=tool_name,
            reason_code="SUBAGENT_BATCH_LIMIT_EXCEEDED",
        )
        return

    from integrations.external_write_policy import sensitive_values

    type_names: list[str] = []
    for item in raw_subs:
        if not isinstance(item, dict):
            _engine.emit("deny", "Each entry in Subagents array must be an object.", tool=tool_name, reason_code="SUBAGENT_NOT_OBJECT")
            return
        raw_type = str(item.get("TypeName") or item.get("typeName") or "").strip()
        if not raw_type:
            _engine.emit("deny", "Subagent entry missing mandatory TypeName.", tool=tool_name, reason_code="MISSING_SUBAGENT_TYPENAME")
            return
        raw_prompt = str(item.get("Prompt") or item.get("prompt") or "").strip()
        if not raw_prompt:
            _engine.emit("deny", "Subagent entry missing mandatory Prompt.", tool=tool_name, reason_code="MISSING_SUBAGENT_PROMPT")
            return
        raw_ws = str(item.get("Workspace") or item.get("workspace") or "").strip().lower()
        if raw_ws and raw_ws != "inherit":
            _engine.emit(
                "deny",
                f"SUBAGENT_WORKSPACE_MUTATION_FORBIDDEN: Host auxiliary subagent '{raw_type}' cannot create isolated Git branches/worktrees (`Workspace='{raw_ws}'`). Omit `Workspace` or pass `Workspace='inherit'`.",
                tool=tool_name,
                reason_code="SUBAGENT_WORKSPACE_MUTATION_FORBIDDEN",
            )
            return
        if sensitive_values([item]):
            _engine.emit(
                "deny",
                f"SENSITIVE_SUBAGENT_PROMPT_BLOCKED: Denied host auxiliary subagent '{raw_type}' carrying credential, token, or signing file path.",
                tool=tool_name,
                reason_code="SENSITIVE_SUBAGENT_PROMPT_BLOCKED",
            )
            return
        type_names.append(raw_type)

    record_host_auxiliary_dispatch(_engine.REPO, raw_subs, parent_conversation_id=parent_conversation_id)
    _engine.emit(
        "allow",
        f"Host auxiliary subagent ({', '.join(sorted(set(type_names)))}) is allowed outside harness-restricted roles.",
        tool=tool_name,
        reason_code="HOST_AUXILIARY_SUBAGENT_ALLOWED",
    )


def _normalize_subagent_items(args: dict) -> tuple[list[Any], bool]:
    if not isinstance(args, dict):
        return [], False
    if "Subagents" in args or "subagents" in args:
        raw = args.get("Subagents") if "Subagents" in args else args.get("subagents")
        return (raw if isinstance(raw, list) else []), False
    top_level_markers = {
        "Role", "role", "TypeName", "typeName", "Prompt", "prompt",
        "Workspace", "workspace", "Model", "model", "name",
    } | set(_engine.COMMON_REASONING_KEYS)
    if any(k in args for k in top_level_markers):
        host_meta_keys = {"toolAction", "toolSummary", "waitForPreviousTools"}
        cleaned = {k: v for k, v in args.items() if k not in host_meta_keys}
        return [cleaned], True
    return [], False
def _handle_phase_reviewer_dispatch(act: dict[str, Any], plan: dict[str, Any], args: dict, tool_name: str, *, parent_conversation_id: str = "") -> None:
    raw_subs, is_single_top_level = _engine._normalize_subagent_items(args)
    if not isinstance(raw_subs, list) or not raw_subs:
        _engine.emit("deny", "No reviewers specified in Subagents array.", tool=tool_name, reason_code="REVIEWER_ROSTER_EMPTY")
        return

    dispatchable = list(act.get("reviewers") or [])
    phase_id = str(act.get("phase_id") or act.get("inputs", {}).get("phase_id") or "")
    if not phase_id:
        try:
            state_dir = _engine.REPO / ".agents/state" if (_engine.REPO / ".agents").is_dir() else _engine.REPO / "agents/state"
            ps_file = state_dir / "tasks" / str(plan.get("task_id") or "") / "phase-state.json"
            if ps_file.is_file():
                phase_id = str(_engine.read_json(ps_file).get("current_phase_id") or "")
        except (OSError, ValueError, _engine.ValidationError):
            pass
    briefs = dict(act.get("briefs") or {})
    is_unbound_replay = bool(act.get("_unbound_replay"))
    if is_single_top_level and len(raw_subs) == 1 and isinstance(raw_subs[0], dict):
        hint_role = _engine._canonical_subagent_role(str(raw_subs[0].get("Role") or raw_subs[0].get("TypeName") or "").strip())
        if hint_role and hint_role not in dispatchable:
            try:
                from _vnext_common import task_dir as _tdir
                from phase_review import load_phase_ledger, phase_run_file
                td = _tdir(_engine.REPO, str(plan.get("task_id") or ""))
                prun_f = phase_run_file(td, phase_id)
                run_meta = _engine.read_json(prun_f) if prun_f.is_file() else {}
                ok, _, ledger = load_phase_ledger(td, phase_id, expected_run_id=run_meta.get("phase_review_run_id"))
                rev_entry = ((ledger or {}).get("reviewers") or {}).get(hint_role) or {}
                if ok and rev_entry.get("state") == "DISPATCHED" and not rev_entry.get("execution_id"):
                    dispatchable.append(hint_role)
                    is_unbound_replay = True
                    if not briefs:
                        briefs = dict(run_meta.get("briefs") or {})
            except (OSError, ValueError, _engine.ValidationError):
                briefs = dict(briefs)

    from phase_review import check_phase_safety_cap
    new_phase_dispatches = 0 if is_unbound_replay else (len(raw_subs) if is_single_top_level else len(dispatchable))
    cap_ok, cap_msg = check_phase_safety_cap(plan, new_phase_dispatches, repo=_engine.REPO)
    if not cap_ok:
        _engine.emit("deny", cap_msg, tool=tool_name, reason_code="REVIEWER_CALL_SAFETY_CAP_REACHED")
        return

    allowed_keys_set = set(_engine.ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS)
    phase_run_models: dict[str, Any] = {}
    try:
        from _vnext_common import task_dir as _tdir
        from phase_review import phase_run_file
        prun_f = phase_run_file(_tdir(_engine.REPO, str(plan.get("task_id") or "")), phase_id)
        if prun_f.is_file():
            phase_run_models = ((_engine.read_json(prun_f).get("review_models") or {}).get("reviewers") or {})
    except Exception:
        phase_run_models = {}
    actual = []
    for item in raw_subs:
        if not isinstance(item, dict):
            _engine.emit("deny", "Each entry in Subagents array must be an object.", tool=tool_name, reason_code="SUBAGENT_NOT_OBJECT")
            return

        r_role_hint = _engine._canonical_subagent_role(str(item.get("Role") or item.get("TypeName") or "").strip())
        sel_info = phase_run_models.get(r_role_hint) if isinstance(phase_run_models, dict) else None
        resolved_m = str((sel_info or {}).get("resolved_model") or "")
        from review_models import reviewer_requires_flash_offload
        needs_flash = reviewer_requires_flash_offload(
            _engine.REPO,
            sel_info if isinstance(sel_info, dict) else {"resolved_model": resolved_m},
            parent_conversation_id=parent_conversation_id,
        )
        allowed_native_model = "flash" if needs_flash else ("pro" if "pro" in resolved_m else None)

        if "model" in item or (not allowed_native_model and "Model" in item):
            bound_note = (
                f"Reviewer '{r_role_hint}' is bound to '{resolved_m}' via .agents/agents/{r_role_hint}/agent.md frontmatter; omit 'Model' in invoke_subagent."
                if resolved_m and resolved_m != "inherit"
                else "Do not send 'model' or 'Model' in reviewer invocation. Reviewer model inheritance is achieved by omission."
            )
            _engine.emit(
                "deny",
                f"REVIEWER_MODEL_OVERRIDE_FORBIDDEN: {bound_note}",
                tool=tool_name,
                reason_code="REVIEWER_MODEL_OVERRIDE_FORBIDDEN",
            )
            return
        if allowed_native_model == "flash" or "gemini-4-hydrogen" in resolved_m:
            from antigravity_runtime import detect_antigravity_remote_mode, remote_subagents_explicitly_allowed
            from platform_quirks import is_quirk_enabled
            rem_active, rem_signals = detect_antigravity_remote_mode()
            if is_quirk_enabled("198819", repo=_engine.REPO) and rem_active and not remote_subagents_explicitly_allowed():
                _engine.emit(
                    "deny",
                    (
                        f"REMOTE_MODE_FLASH_QUOTA_LEAK_GUARD (#198819): Antigravity Remote Mode detected ({', '.join(rem_signals)}). "
                        f"Reviewer '{r_role_hint}' is configured for '{resolved_m}', which ignores fast-tier subagent overrides in Remote Mode on Frontier sessions and drains 3x Frontier quota. "
                        "Run reviews in Local Mode, switch reviewer policy to 'inherit' on a Carbon/Claude session, or set HARNESS_ALLOW_REMOTE_SUBAGENTS=1."
                    ),
                    tool=tool_name,
                    reason_code="REMOTE_MODE_FLASH_QUOTA_LEAK_GUARD",
                )
                return
        if allowed_native_model and item.get("Model") != allowed_native_model:
            offload_ctx = (
                " (routes natively to Gemini 4 Hydrogen High 1x regardless of main-chat model)"
                if resolved_m.startswith(("gemini-4-hydrogen", "gemini-3.8-flash"))
                else ""
            )
            _engine.emit(
                "deny",
                (
                    f"REVIEWER_MODEL_MISMATCH: Reviewer '{r_role_hint}' is configured for '{resolved_m}'{offload_ctx}; "
                    f"you MUST pass Model='{allowed_native_model}' in invoke_subagent."
                ),
                tool=tool_name,
                reason_code="REVIEWER_MODEL_MISMATCH",
            )
            return

        supplied_reasoning_keys = [k for k in item if k in _engine.COMMON_REASONING_KEYS]
        if supplied_reasoning_keys:
            _engine.emit(
                "deny",
                "This host does not expose trusted per-subagent reasoning control. Omit reasoning override and inherit the parent setting.",
                tool=tool_name,
                reason_code="UNSUPPORTED_REASONING_KEY",
            )
            return

        item_allowed_keys = set(allowed_keys_set) | ({"Model"} if allowed_native_model else set())
        for k in item:
            if k not in item_allowed_keys:
                _engine.emit(
                    "deny",
                    f"Unexpected key '{k}' in subagent invocation. Allowed keys: {sorted(item_allowed_keys)}.",
                    tool=tool_name,
                    reason_code="UNEXPECTED_SUBAGENT_KEY",
                )
                return

        if "Role" not in item:
            _engine.emit("deny", "Subagent entry missing mandatory Role.", tool=tool_name, reason_code="MISSING_SUBAGENT_ROLE")
            return
        r_role = str(item["Role"]).strip()
        if not r_role:
            _engine.emit("deny", "Subagent entry Role is empty.", tool=tool_name, reason_code="MISSING_SUBAGENT_ROLE")
            return

        if "TypeName" not in item:
            _engine.emit("deny", "Subagent entry missing mandatory TypeName.", tool=tool_name, reason_code="MISSING_SUBAGENT_TYPENAME")
            return
        r_type = str(item["TypeName"]).strip()
        if not r_type:
            _engine.emit("deny", "Subagent entry TypeName is empty.", tool=tool_name, reason_code="MISSING_SUBAGENT_TYPENAME")
            return

        canon_type = _engine._canonical_subagent_role(r_type)
        canon_role = _engine._canonical_subagent_role(r_role)
        if canon_type != canon_role:
            _engine.emit(
                "deny",
                f"Reviewer invocation mismatch: TypeName '{r_type}' does not match Role '{r_role}'. Both must refer to the same reviewer.",
                tool=tool_name,
                reason_code="REVIEWER_ROLE_MISMATCH",
            )
            return

        if canon_role not in dispatchable:
            _engine.emit(
                "deny",
                f"Reviewer '{canon_role}' is not in dispatchable reviewers: {sorted(dispatchable)}.",
                tool=tool_name,
                reason_code="REVIEWER_ROSTER_EXTRA",
            )
            return

        if canon_role in actual:
            _engine.emit("deny", f"Reviewer batch contains duplicate reviewer: '{canon_role}'.", tool=tool_name, reason_code="DUPLICATE_REVIEWER")
            return
        actual.append(canon_role)

        if "Prompt" not in item:
            _engine.emit("deny", "Subagent entry missing mandatory Prompt.", tool=tool_name, reason_code="MISSING_SUBAGENT_PROMPT")
            return
        supplied_prompt = str(item["Prompt"]).replace("\r\n", "\n").strip()
        if not supplied_prompt:
            _engine.emit("deny", "Subagent entry missing mandatory Prompt.", tool=tool_name, reason_code="MISSING_SUBAGENT_PROMPT")
            return

        brief_val = briefs.get(canon_role)
        if brief_val and Path(str(brief_val)).is_file():
            expected_prompt = Path(str(brief_val)).read_text(encoding="utf-8").replace("\r\n", "\n").strip()
        elif isinstance(brief_val, str) and brief_val.strip():
            expected_prompt = brief_val.replace("\r\n", "\n").strip()
        else:
            _engine.emit("deny", f"Reviewer brief missing or unreadable for '{canon_role}'.", tool=tool_name, reason_code="REVIEW_PROFILE_BLOCKED")
            return

        from review_execution import pointer_matches
        phase_alt_paths: list[str] = []
        phase_prior_digs: list[str] = []
        try:
            from phase_review import phase_run_file as _prf
            from _vnext_common import task_dir as _ptd
            _t_id = str(plan.get("task_id") or "")
            if _t_id and phase_id:
                _tdir = _ptd(_engine.REPO, _t_id)
                phase_alt_paths.append(str(_tdir / "active-briefs" / f"phase-brief-{phase_id}-{r_role}.md"))
                _pr_f = _prf(_tdir, phase_id)
                if _pr_f.is_file():
                    _pr_doc = _engine.read_json(_pr_f)
                    _sb = str(((_pr_doc.get("short_briefs") or {}).get(r_role)) or "")
                    if _sb and _sb not in phase_alt_paths:
                        phase_alt_paths.append(_sb)
                    phase_prior_digs = list(((_pr_doc.get("accepted_prior_brief_digests") or {}).get(r_role)) or [])
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            pass
        if supplied_prompt != expected_prompt and not pointer_matches(
            supplied_prompt,
            r_role,
            str(brief_val),
            expected_prompt,
            alternate_paths=phase_alt_paths,
            accepted_digests=phase_prior_digs,
        ):
            _engine.emit(
                "deny",
                f"Reviewer prompt for '{r_role}' does not match the generated reviewer brief.",
                tool=tool_name,
                reason_code="REVIEWER_PROMPT_MISMATCH",
            )
            return

    actual_set = set(actual)
    disp_set = set(dispatchable)
    if actual_set != disp_set:
        missing = disp_set - actual_set
        extra = actual_set - disp_set
        if extra:
            _engine.emit(
                "deny",
                f"Reviewer batch contains extra reviewers: expected {sorted(disp_set)}, got {sorted(actual_set)}.",
                tool=tool_name,
                reason_code="REVIEWER_ROSTER_EXTRA",
            )
            return
        if missing and not is_single_top_level:
            _engine.emit(
                "deny",
                f"Reviewer batch incomplete: expected {len(disp_set)} reviewers ({sorted(disp_set)}), got {len(actual_set)} ({sorted(actual_set)}). All dispatchable reviewers must be launched in a single invoke_subagent call.",
                tool=tool_name,
                reason_code="REVIEWER_ROSTER_INCOMPLETE",
            )
            return

    try:
        from phase_review import record_phase_dispatch_batch
        record_phase_dispatch_batch(
            _engine.REPO,
            str(plan.get("task_id") or ""),
            phase_id,
            sorted(actual),
            host="antigravity",
            allow_single=is_single_top_level,
        )
    except Exception as exc:
        _engine.emit(
            "deny",
            f"[PHASE_REVIEW_RECEIPT_WRITE_FAILED] Failed creating phase reviewer dispatch receipt ({type(exc).__name__}): {exc}",
            tool=tool_name,
            reason_code="PHASE_REVIEW_RECEIPT_WRITE_FAILED",
        )
        return

    _engine.emit("allow", "Phase reviewer roster exactly matches the approved phase review plan.", tool=tool_name, reason_code="DISPATCH_PHASE_REVIEWERS_ALLOWED")
def _handle_run_workflow(name: str, args: dict) -> None:
    """Fail-closed governance for Antigravity `run_workflow` tool."""
    inline_keys = (
        "Script", "script",
        "code", "Code",
        "script_content", "scriptContent",
        "inline_script", "inlineScript",
        "python", "Python",
        "source", "Source",
    )
    for ik in inline_keys:
        val = args.get(ik)
        if isinstance(val, str) and val.strip():
            _engine.emit(
                "deny",
                "UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED: Inline `run_workflow` Python code (`Script`) is forbidden by the harness safety boundary. "
                "Only the checksum-verified `.agents/scripts/dynamic_review_workflow.py` script may execute via `ScriptPath` during `VERIFYING`.",
                tool=name,
                reason_code="UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED",
            )
            return

    raw_cwd = args.get("Cwd") or args.get("cwd")
    if isinstance(raw_cwd, str) and raw_cwd.strip():
        cwd_p = Path(raw_cwd.strip()).expanduser()
        cwd_res = cwd_p.resolve() if cwd_p.is_absolute() else (_engine.REPO / cwd_p).resolve()
        if not cwd_res.is_relative_to(_engine.REPO.resolve()):
            _engine.emit(
                "deny",
                f"UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED: `run_workflow` Cwd '{raw_cwd}' escapes repository root.",
                tool=name,
                reason_code="UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED",
            )
            return

    raw_script = ""
    for pk in ("ScriptPath", "scriptPath", "script_path", "WorkflowPath", "workflowPath", "workflow_path", "Path", "path", "File", "file"):
        cand = args.get(pk)
        if isinstance(cand, str) and cand.strip():
            raw_script = cand.strip()
            break
    if not raw_script:
        _engine.emit(
            "deny",
            "UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED: `run_workflow` must specify the governed `.agents/scripts/dynamic_review_workflow.py` via `ScriptPath`.",
            tool=name,
            reason_code="UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED",
        )
        return

    cand_path = Path(raw_script).expanduser()
    resolved = cand_path.resolve() if cand_path.is_absolute() else (_engine.REPO / cand_path).resolve()
    allowed_paths = {
        (_engine.REPO / ".agents" / "scripts" / "dynamic_review_workflow.py").resolve(),
        (_engine.REPO / "agents" / "scripts" / "dynamic_review_workflow.py").resolve(),
    }
    if resolved not in allowed_paths or not resolved.is_file() or resolved.is_symlink():
        _engine.emit(
            "deny",
            f"UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED: Untrusted workflow script '{raw_script}'. Only `.agents/scripts/dynamic_review_workflow.py` is authorized.",
            tool=name,
            reason_code="UNTRUSTED_DYNAMIC_WORKFLOW_BLOCKED",
        )
        return

    try:
        from dynamic_review_workflow import build_dynamic_review_plan
        spec = build_dynamic_review_plan(_engine.REPO)
    except Exception as exc:
        _engine.emit(
            "deny",
            f"DYNAMIC_WORKFLOW_NOT_READY: Governed dynamic review workflow requires an active VERIFYING V2 review wave ({exc}).",
            tool=name,
            reason_code="DYNAMIC_WORKFLOW_NOT_READY",
        )
        return

    _engine.emit(
        "allow",
        f"Verified governed V2 dynamic review workflow for task '{spec['task_id']}'.",
        tool=name,
        reason_code="DYNAMIC_WORKFLOW_REVIEW_ALLOWED",
    )


def _handle_subagent(name: str, args: dict, *, parent_conversation_id: str = "") -> None:
    if name == "run_workflow":
        _handle_run_workflow(name, args)
        return
    try:
        plan = _engine.active_plan(_engine.REPO)
    except _engine.ValidationError:
        plan = None
    try:
        from host_continuation import assert_execution_session
        if plan:
            assert_execution_session(_engine.REPO, plan.get("task_id"))
    except _engine.ValidationError as exc:
        _engine.emit("deny", str(exc), tool=name, reason_code="HOST_SESSION_MISMATCH")
        return

    # Zero-polling invariant: block busy-waiting loops while allowing list/kill in all states (including IDLE)
    if name == "manage_task":
        act = str(args.get("Action") or args.get("action") or "").strip().lower()
        if act == "status":
            _engine.emit("deny", "ZERO-POLLING INVARIANT: manage_task(Action='status') is blocked to prevent polling loops. Background tasks notify you reactively upon completion. Yield execution now without calling tools.", tool=name)
            return
        _engine.emit(
            "allow",
            f"Background task management (`Action='{act or 'list'}'`) is permitted across all task states.",
            tool=name,
            reason_code="MANAGE_TASK_ALLOWED",
        )
        return
    elif name == "manage_subagents":
        act = str(args.get("Action") or args.get("action") or "").strip().lower()
        if act in {"kill_all", "kill"}:
            unfinalized_rev, rev_detail = _engine._has_unfinalized_active_review_wave(_engine.REPO)
            if unfinalized_rev:
                _engine.emit(
                    "deny",
                    f"ACTIVE_REVIEW_WAVE_KILL_ALL_BLOCKED: Do NOT call `manage_subagents(Action='{act}')` while {rev_detail} is still unfinalized. "
                    "Killing subagents before `review complete-all` / `phase-review complete-all` corrupts Antigravity Desktop's subagent registry "
                    "(`not found` + `already exists` deadlock). Run `review complete-all` (or `task heal` if `REVIEW_ENV_BLOCKED`) first, and reap subagents only AFTER reviews finalize.",
                    tool=name,
                    reason_code="ACTIVE_REVIEW_WAVE_KILL_ALL_BLOCKED",
                )
                return
            _engine.emit(
                "allow",
                "ZOMBIE_SUBAGENT_REAP_ALLOWED (#199713): Reaping finished/idle subagents via manage_subagents(kill_all/kill) is permitted across all task states to prevent 6-23h zombie sessions and 255m reactive wakeups.",
                tool=name,
                reason_code="ZOMBIE_SUBAGENT_REAP_ALLOWED",
            )
            return
        _engine.emit(
            "deny",
            "ZERO-POLLING INVARIANT: manage_subagents(Action='list') is blocked to prevent polling loops. Subagents notify you reactively upon completion; call manage_subagents(Action='kill_all') once the subagent wave or task finishes (#199713).",
            tool=name,
            reason_code="ZERO_POLLING_MANAGE_SUBAGENTS",
        )
        return
    elif name == "schedule" or name.startswith("schedules:"):
        if str(_engine.os.environ.get("HARNESS_ALLOW_SCHEDULE_TOOL") or "").strip().lower() not in {"1", "true", "yes"}:
            _engine.emit(
                "deny",
                "ZERO-POLLING INVARIANT & ZOMBIE_SUBAGENT_SCHEDULE_WAKEUP_GUARD (#199713): Tool 'schedule' is blocked inside harness sessions to prevent busy-waiting and 255-minute reactive wakeup quota drain on idle subagents. Yield execution and await normal completion.",
                tool=name,
                reason_code="ZOMBIE_SUBAGENT_SCHEDULE_WAKEUP_GUARD",
            )
            return

    if plan and plan.get("task_id"):
        from reviewer_host import active_reviews, _load_ledger, lifecycle_action
        for run, ledger_path in active_reviews(_engine.REPO):
            if run.get("task_id") != str(plan["task_id"]) or not ledger_path.is_file():
                continue
            try:
                ledger = _load_ledger(run, ledger_path)
            except _engine.ValidationError:
                continue
            action = lifecycle_action(_engine.REPO, run, ledger.get("reviewers", {}))
            if action and action.get("code") in {"REVIEWER_CANCELLED", "RESUME_REVIEWER", "REVIEWER_RESUME_ENV_BLOCKED"}:
                if action["code"] != "RESUME_REVIEWER":
                    _engine.emit("deny", action["reason"], tool=name, reason_code="REVIEWER_CANCELLED")
                    return
                if name != "send_message":
                    _engine.emit("deny", "Resume the existing reviewer with the routed send_message.", tool=name, reason_code="REVIEWER_RESUME_REQUIRED")
                    return
                recipient = str(args.get("Recipient") or args.get("recipient") or "")
                message = str(args.get("Message") or args.get("message") or "")
                if recipient != action["recipient"] or message != action["message"]:
                    _engine.emit("deny", "Resume must target the same execution with the routed message.", tool=name, reason_code="REVIEWER_RESUME_MISMATCH")
                    return
                from reviewer_host import mark_resume_dispatched
                mark_resume_dispatched(_engine.REPO, str(plan["task_id"]), action["inputs"]["reviewer"], recipient)
                _engine.emit("allow", "Explicit reviewer resume decision recorded for this execution.", tool=name, reason_code="REVIEWER_RESUME_ALLOWED")
                return

    if name == "define_subagent":
        ok_def, reason_def, code_def = _engine._validate_define_subagent(args, name)
        _engine.emit("allow" if ok_def else "deny", reason_def, tool=name, reason_code=code_def)
        return

    if name == "invoke_subagent":
        _all_subs_chk, _ = _engine._normalize_subagent_items(args)
        if _all_subs_chk and any(
            isinstance(s, dict)
            and (
                _engine._canonical_subagent_role(str(s.get("TypeName") or s.get("typeName") or "").strip()) == "harness-worker-agent"
                or _engine._canonical_subagent_role(str(s.get("Role") or s.get("role") or "").strip()) == "harness-worker-agent"
            )
            for s in _all_subs_chk
        ):
            _engine.emit(
                "deny",
                "WORKER_AGENT_RETIRED_INLINE_LEAD_ONLY: `harness-worker-agent` has been retired because custom subagents inherit the parent model with a cold cache. "
                "Implement approved files and run `checkpoint-phase` / `verify-steps` directly on the warm Lead session (or via Web-Relay when Web mode is active).",
                tool=name,
                reason_code="WORKER_AGENT_RETIRED_INLINE_LEAD_ONLY",
            )
            return

    if name == "send_message" and (plan is None or str(plan.get("status") or "") not in {"IMPLEMENTING", "VERIFYING"}):
        ok_aux_msg, reason_aux_msg, code_aux_msg = _check_host_auxiliary_send_message(
            _engine.REPO, args, caller_conversation_id=parent_conversation_id,
        )
        if ok_aux_msg:
            _engine.emit("allow", reason_aux_msg, tool=name, reason_code=code_aux_msg)
            return
        if code_aux_msg == "SENSITIVE_SUBAGENT_PROMPT_BLOCKED":
            _engine.emit("deny", reason_aux_msg, tool=name, reason_code=code_aux_msg)
            return
        _engine.emit(
            "deny",
            "SUBAGENT_SEND_MESSAGE_FORBIDDEN: `send_message` is reserved exclusively for router-authorized reviewer protocol retries or resuming tracked host auxiliary subagents. "
            "If you are a subagent, output your final report directly as plain assistant text and end your turn.",
            tool=name,
            reason_code="SUBAGENT_SEND_MESSAGE_FORBIDDEN",
        )
        return

    if name == "invoke_subagent" and (plan is None or str(plan.get("status") or "") not in {"IMPLEMENTING", "VERIFYING"}):
        raw_subs, _ = _engine._normalize_subagent_items(args)
        if not raw_subs:
            _engine.emit("deny", "No subagent entry specified in invoke_subagent.", tool=name, reason_code="SUBAGENT_ROSTER_EMPTY")
            return
        if any(
            isinstance(s, dict) and _engine._canonical_subagent_role(str(s.get("TypeName") or s.get("typeName") or "").strip()) in _engine.CORE_UTILITY_AGENTS
            for s in raw_subs
        ):
            from delegation_policy import validate_utility_dispatch
            ok_u, reason_u, code_u = validate_utility_dispatch(
                _engine.REPO, plan, raw_subs, parent_conversation_id=parent_conversation_id,
            )
            _engine.emit("allow" if ok_u else "deny", reason_u, tool=name, reason_code=code_u)
            return
        if any(
            isinstance(s, dict)
            and (
                _engine._canonical_subagent_role(str(s.get("TypeName") or s.get("typeName") or "").strip()) in _engine.CORE_ROUTED_REVIEWERS
                or _engine._canonical_subagent_role(str(s.get("Role") or s.get("role") or "").strip()) in _engine.CORE_ROUTED_REVIEWERS
            )
            for s in raw_subs
        ):
            _engine.emit(
                "deny",
                f"PREMATURE_REVIEWER_DISPATCH_FORBIDDEN: Reviewer subagents cannot be dispatched while task status is {str((plan or {}).get('status') or 'IDLE')}.",
                tool=name,
                reason_code="PREMATURE_REVIEWER_DISPATCH_FORBIDDEN",
            )
            return
        if any(
            isinstance(s, dict)
            and (
                str(s.get("TypeName") or s.get("typeName") or "").strip().lower() == "self"
                or str(s.get("Role") or s.get("role") or "").strip().lower() == "self"
            )
            for s in raw_subs
        ):
            _engine.emit(
                "deny",
                "SELF_SUBAGENT_FORBIDDEN: Built-in `TypeName='self'` inherits full parent write/shell tools and cannot bypass approval or inline-lead boundaries.",
                tool=name,
                reason_code="SELF_SUBAGENT_FORBIDDEN",
            )
            return
        spec_flags = [
            isinstance(s, dict)
            and _engine._canonical_subagent_role(str(s.get("TypeName") or s.get("typeName") or s.get("Role") or s.get("role") or "").strip()) in _engine.ON_DEMAND_SPECIALIST_AGENTS
            for s in raw_subs
        ]
        if any(spec_flags):
            if not all(spec_flags):
                _engine.emit(
                    "deny",
                    "MIXED_SUBAGENT_ROSTER_FORBIDDEN: Do not mix harness specialists with other subagent types in a single `invoke_subagent` call.",
                    tool=name,
                    reason_code="MIXED_SUBAGENT_ROSTER_FORBIDDEN",
                )
                return
            if len(raw_subs) > 5:
                _engine.emit("deny", f"Subagent batch size {len(raw_subs)} exceeds the safety limit of 5.", tool=name)
                return
            _pre_offload, _pre_lead_fam = False, ""
            try:
                from delegation_policy import subagent_requires_universal_flash as _req_flash_pre
                _pre_offload, _pre_lead_fam = _req_flash_pre(
                    _engine.REPO,
                    plan=plan,
                    parent_conversation_id=parent_conversation_id,
                    allow_frontier_policy_inherit=True,
                )
            except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
                _pre_offload = False
            for s in raw_subs:
                canon_pre = _engine._canonical_subagent_role(str(s.get("TypeName") or s.get("typeName") or s.get("Role") or s.get("role") or "").strip())
                spec_m_pre = str(s.get("Model") or s.get("model") or "").strip()
                if _pre_offload:
                    if spec_m_pre != "flash":
                        _engine.emit(
                            "deny",
                            f"CARBON_SPECIALIST_QUOTA_OFFLOAD_REQUIRED: Always pass `Model='flash'` on `{canon_pre}` (routes natively in Antigravity to `gemini-4-hydrogen-tiered-high` `1x` regardless of main-chat model `{_pre_lead_fam}`; switch policy to explicit `inherit` only when Gemini quota is exhausted).",
                            tool=name,
                            reason_code="CARBON_SPECIALIST_QUOTA_OFFLOAD_REQUIRED",
                        )
                        return
                elif spec_m_pre and spec_m_pre.lower() != "inherit":
                    _engine.emit(
                        "deny",
                        f"SPECIALIST_MODEL_OVERRIDE_FORBIDDEN: Omit `Model` on `{canon_pre}` under explicit inherit/frontier policy (`INHERIT_PARENT_BY_OMISSION`; got `{spec_m_pre}`).",
                        tool=name,
                        reason_code="SPECIALIST_MODEL_OVERRIDE_FORBIDDEN",
                    )
                    return
            try:
                from delegation_policy import record_specialist_dispatch
                record_specialist_dispatch(_engine.REPO, plan, raw_subs, parent_conversation_id=parent_conversation_id)
            except (ImportError, OSError, ValueError, _engine.ValidationError):
                pass
            _engine.emit("allow", "Read-only specialist subagent is allowed for bounded consultation.", tool=name)
            return
        research_flags = [
            isinstance(s, dict) and str(s.get("TypeName") or s.get("typeName") or "").strip().lower() in _SCOUT_REDIRECT_ROLES
            for s in raw_subs
        ]
        if any(research_flags):
            if len(raw_subs) > 5:
                _engine.emit("deny", f"Subagent batch size {len(raw_subs)} exceeds the safety limit of 5.", tool=name)
                return
            from delegation_policy import is_utility_agent_unloaded_in_session
            if (_engine.REPO / ".agents" / "agents" / "harness-scout-agent" / "agent.md").is_file() and not is_utility_agent_unloaded_in_session(_engine.REPO, parent_conversation_id, "harness-scout-agent"):
                _engine.emit(
                    "deny",
                    "USE_HARNESS_SCOUT_AGENT: Built-in TypeName='research'/'explore' runs unpinned without Flash quota protection or Graph anchoring. "
                    "Re-invoke immediately with TypeName='harness-scout-agent', Role='harness-scout-agent', Workspace='inherit' "
                    "(split into 2-3 parallel `harness-scout-agent` entries in one call when investigating 3+ distinct subsystems).",
                    tool=name,
                    reason_code="USE_HARNESS_SCOUT_AGENT",
                )
                return
            if not all(research_flags):
                _engine.emit(
                    "deny",
                    "MIXED_SUBAGENT_ROSTER_FORBIDDEN: Do not mix `research`/`explore` with other subagent types in a single `invoke_subagent` call.",
                    tool=name,
                    reason_code="MIXED_SUBAGENT_ROSTER_FORBIDDEN",
                )
                return
            _engine.emit("allow", "Read-only research subagent is allowed for bounded codebase exploration.", tool=name)
            return
        _validate_and_allow_host_auxiliary(raw_subs, name, parent_conversation_id=parent_conversation_id)
        return

    try:
        plan = _engine.active_plan(_engine.REPO)
        status = str(plan.get("status") or "")
        if status == "IMPLEMENTING":
            task_id = str(plan.get("task_id") or "")
            if not task_id:
                state_dir = _engine.REPO / ".agents/state" if (_engine.REPO / ".agents").is_dir() else _engine.REPO / "agents/state"
                active_f = state_dir / "active-task.json"
                if active_f.is_file():
                    task_id = str(_engine.read_json(active_f).get("task_id") or "")
            from workflow import resolve_next_action
            act = resolve_next_action(_engine.REPO, task_id, plan)
            act_code = act.get("code")

            if act_code == "RETRY_PHASE_REVIEW_PROTOCOL":
                if name != "send_message":
                    _engine.emit(
                        "deny",
                        f"send_message is required to retry phase review protocol (got tool '{name}').",
                        tool=name,
                        reason_code="RETRY_PHASE_REVIEW_PROTOCOL_REQUIRED",
                    )
                    return
                expected_recipient = str(act.get("recipient") or "").strip()
                expected_msg = str(act.get("message") or "").strip()
                supplied_recipient = str(args.get("Recipient") or args.get("recipient") or "").strip()
                supplied_msg = str(args.get("Message") or args.get("message") or "").strip()
                if not supplied_recipient or supplied_recipient != expected_recipient:
                    _engine.emit(
                        "deny",
                        f"send_message recipient mismatch: expected '{expected_recipient}', got '{supplied_recipient}'.",
                        tool=name,
                        reason_code="RETRY_RECIPIENT_MISMATCH",
                    )
                    return
                if not supplied_msg or supplied_msg.replace("\r\n", "\n").strip() != expected_msg.replace("\r\n", "\n").strip():
                    _engine.emit(
                        "deny",
                        "send_message message does not match the required protocol retry prompt.",
                        tool=name,
                        reason_code="RETRY_MESSAGE_MISMATCH",
                    )
                    return
                _engine.emit("allow", "Protocol retry send_message matches router requirements.", tool=name, reason_code="RETRY_PHASE_REVIEW_PROTOCOL_ALLOWED")
                return

            if act_code == "DISPATCH_PHASE_REVIEWERS":
                if name == "define_subagent":
                    _engine.emit("allow", "Reviewer subagent definition is allowed before phase reviewer dispatch.", tool=name)
                    return
                if name != "invoke_subagent":
                    _engine.emit(
                        "deny",
                        f"invoke_subagent is required to dispatch phase reviewers (got tool '{name}').",
                        tool=name,
                        reason_code="DISPATCH_PHASE_REVIEWERS_REQUIRED",
                    )
                    return
                _engine._handle_phase_reviewer_dispatch(act, plan, args, name, parent_conversation_id=parent_conversation_id)
                return

            if act_code == "WAIT_FOR_PHASE_REVIEWERS" and name == "invoke_subagent":
                from phase_review import load_phase_ledger, phase_run_file
                from _vnext_common import task_dir as _tdir
                phase_id = str(act.get("inputs", {}).get("phase_id") or "")
                td = _tdir(_engine.REPO, task_id)
                prun_f = phase_run_file(td, phase_id)
                run_meta = _engine.read_json(prun_f) if prun_f.is_file() else {}
                ok, _, ledger = load_phase_ledger(td, phase_id, expected_run_id=run_meta.get("phase_review_run_id"))
                revs = (ledger or {}).get("reviewers") or {}
                if ok and revs and all(
                    d.get("state") == "DISPATCHED" and not d.get("execution_id")
                    for d in revs.values()
                ):
                    replay_act = {
                        **act,
                        "_unbound_replay": True,
                        "phase_id": phase_id,
                        "reviewers": sorted(run_meta.get("selected_reviewers") or list(revs.keys())),
                        "briefs": dict(run_meta.get("briefs") or {}),
                    }
                    _engine._handle_phase_reviewer_dispatch(replay_act, plan, args, name, parent_conversation_id=parent_conversation_id)
                    return

            if name in {"invoke_subagent", "send_message"} and act_code in {
                "WAIT_FOR_PHASE_REVIEWERS", "COMPLETE_REVIEWER", "PHASE_REVIEW_ENV_BLOCKED", "PHASE_REVIEW_PROTOCOL_BLOCKED",
            }:
                _engine.emit("deny", "Follow the existing phase review execution; no replacement or extra reviewer message is routed.",
                     tool=name, reason_code="PHASE_REVIEW_EXECUTION_ALREADY_STARTED")
                return

            if name == "send_message":
                ok_aux_msg, reason_aux_msg, code_aux_msg = _check_host_auxiliary_send_message(
                    _engine.REPO, args, caller_conversation_id=parent_conversation_id,
                )
                if ok_aux_msg:
                    _engine.emit("allow", reason_aux_msg, tool=name, reason_code=code_aux_msg)
                    return
                if code_aux_msg == "SENSITIVE_SUBAGENT_PROMPT_BLOCKED":
                    _engine.emit("deny", reason_aux_msg, tool=name, reason_code=code_aux_msg)
                    return
                _engine.emit(
                    "deny",
                    f"SUBAGENT_SEND_MESSAGE_FORBIDDEN: `send_message` is not permitted during IMPLEMENTING unless retrying phase review protocol or resuming a tracked host auxiliary subagent (current router action: {act_code}). "
                    "Advance directly on the warm Lead session with `python .agents/harness.py task checkpoint-phase --advance-all-ready` "
                    "or `python .agents/harness.py verify-steps --task-id " + task_id + " --host antigravity`.",
                    tool=name,
                    reason_code="SUBAGENT_SEND_MESSAGE_FORBIDDEN",
                )
                return
            norm_subs, _ = _engine._normalize_subagent_items(args)
            if name == "invoke_subagent" and norm_subs and any(
                isinstance(s, dict)
                and (
                    _engine._canonical_subagent_role(str(s.get("TypeName") or s.get("typeName") or "").strip()) in _engine.CORE_ROUTED_REVIEWERS
                    or _engine._canonical_subagent_role(str(s.get("Role") or s.get("role") or "").strip()) in _engine.CORE_ROUTED_REVIEWERS
                )
                for s in norm_subs
            ):
                busy_pid = _engine._detect_live_verification_or_build_owner(_engine.REPO, task_id)
                if busy_pid:
                    _engine.emit(
                        "deny",
                        f"CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS: Background verification/Gradle process (PID {busy_pid}) "
                        "is still actively running and review briefs are not ready yet. Do NOT speculatively dispatch reviewers while "
                        "`verify-steps` is running — output one short status sentence and end your turn with ZERO tool calls.",
                        tool=name,
                        reason_code="CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS",
                        task_id=task_id,
                    )
                    return
                _engine.emit(
                    "deny",
                    f"PREMATURE_REVIEWER_DISPATCH_FORBIDDEN: Reviewer subagents cannot be dispatched during IMPLEMENTING "
                    f"(current router action: {act_code}). Run `verify-steps` first to build immutable review briefs.",
                    tool=name,
                    reason_code="PREMATURE_REVIEWER_DISPATCH_FORBIDDEN",
                    task_id=task_id,
                )
                return
            if name == "invoke_subagent" and norm_subs and any(
                isinstance(s, dict) and _engine._canonical_subagent_role(str(s.get("TypeName") or s.get("typeName") or "").strip()) in _engine.CORE_UTILITY_AGENTS
                for s in norm_subs
            ):
                from delegation_policy import validate_utility_dispatch
                ok_u, reason_u, code_u = validate_utility_dispatch(
                    _engine.REPO, plan, norm_subs, parent_conversation_id=parent_conversation_id,
                )
                _engine.emit("allow" if ok_u else "deny", reason_u, tool=name, reason_code=code_u)
                return
            if len(norm_subs) > 5:
                _engine.emit("deny", f"Subagent batch size {len(norm_subs)} exceeds the safety limit of 5.", tool=name)
                return
            from delegation_policy import is_utility_agent_unloaded_in_session as _is_unloaded_u
            if name == "invoke_subagent":
                if not norm_subs:
                    _engine.emit("deny", "No subagent entry specified in invoke_subagent.", tool=name, reason_code="SUBAGENT_ROSTER_EMPTY")
                    return
                if any(
                    isinstance(s, dict) and str(s.get("TypeName") or s.get("typeName") or "").strip().lower() in {"research", "explore"}
                    for s in norm_subs
                ) and (_engine.REPO / ".agents" / "agents" / "harness-scout-agent" / "agent.md").is_file() and not _is_unloaded_u(_engine.REPO, parent_conversation_id, "harness-scout-agent"):
                    _engine.emit(
                        "deny",
                        "USE_HARNESS_SCOUT_AGENT: Built-in TypeName='research'/'explore' is blocked on Antigravity. "
                        "Use TypeName='harness-scout-agent', Role='harness-scout-agent', Workspace='inherit' instead.",
                        tool=name,
                        reason_code="USE_HARNESS_SCOUT_AGENT",
                    )
                    return
                blocked_impl_clones = {"self", "harness-worker-agent"}
                frontier_offload_spec, lead_fam_spec = False, ""
                try:
                    from delegation_policy import subagent_requires_universal_flash as _req_flash_spec
                    frontier_offload_spec, lead_fam_spec = _req_flash_spec(
                        _engine.REPO,
                        plan=plan,
                        parent_conversation_id=parent_conversation_id,
                        allow_frontier_policy_inherit=True,
                    )
                except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
                    frontier_offload_spec = False
                specialist_items: list[dict[str, Any]] = []
                auxiliary_items: list[dict[str, Any]] = []
                for s in norm_subs:
                    if not isinstance(s, dict):
                        _engine.emit("deny", "Each entry in Subagents array must be an object.", tool=name, reason_code="SUBAGENT_NOT_OBJECT")
                        return
                    raw_type_s, raw_role_s, canon_type_s, canon_role_s = _extract_subagent_type_and_role(s)
                    raw_t = raw_type_s or raw_role_s
                    canon_t = canon_type_s or canon_role_s
                    if any(
                        cand and cand.lower() in blocked_impl_clones
                        for cand in (raw_type_s, raw_role_s, canon_type_s, canon_role_s)
                    ):
                        _engine.emit(
                            "deny",
                            f"WORKER_SUBAGENT_FORBIDDEN_INLINE_LEAD_ONLY: Subagent '{raw_t}' is forbidden during IMPLEMENTING. Implement code inline on the warm Lead session (`INLINE_LEAD_DIRECT`), or use `harness-scout-agent` / read-only specialists.",
                            tool=name,
                            reason_code="WORKER_SUBAGENT_FORBIDDEN_INLINE_LEAD_ONLY",
                        )
                        return
                    if canon_t in _engine.ON_DEMAND_SPECIALIST_AGENTS:
                        spec_model_arg = str(s.get("Model") or s.get("model") or "").strip()
                        if frontier_offload_spec:
                            if spec_model_arg != "flash":
                                _engine.emit(
                                    "deny",
                                    f"CARBON_SPECIALIST_QUOTA_OFFLOAD_REQUIRED: Always pass `Model='flash'` on `{canon_t}` (routes natively in Antigravity to `gemini-4-hydrogen-tiered-high` `1x` regardless of main-chat model `{lead_fam_spec}`; switch policy to explicit `inherit` only when Gemini quota is exhausted).",
                                    tool=name,
                                    reason_code="CARBON_SPECIALIST_QUOTA_OFFLOAD_REQUIRED",
                                )
                                return
                        elif spec_model_arg and spec_model_arg.lower() != "inherit":
                            _engine.emit(
                                "deny",
                                f"SPECIALIST_MODEL_OVERRIDE_FORBIDDEN: Omit `Model` on `{canon_t}` under explicit inherit/frontier policy (`INHERIT_PARENT_BY_OMISSION`; got `{spec_model_arg}`).",
                                tool=name,
                                reason_code="SPECIALIST_MODEL_OVERRIDE_FORBIDDEN",
                            )
                            return
                        specialist_items.append(s)
                    else:
                        auxiliary_items.append(s)
                if specialist_items and auxiliary_items:
                    _engine.emit(
                        "deny",
                        "MIXED_SUBAGENT_ROSTER_FORBIDDEN: Do not mix harness specialists with host auxiliary subagents in a single `invoke_subagent` call.",
                        tool=name,
                        reason_code="MIXED_SUBAGENT_ROSTER_FORBIDDEN",
                    )
                    return
                if auxiliary_items:
                    _validate_and_allow_host_auxiliary(auxiliary_items, name, parent_conversation_id=parent_conversation_id)
                    return
                try:
                    from delegation_policy import record_specialist_dispatch
                    record_specialist_dispatch(_engine.REPO, plan, specialist_items, parent_conversation_id=parent_conversation_id)
                except (ImportError, OSError, ValueError, _engine.ValidationError):
                    pass
            _engine.emit("allow", "On-demand specialist action is inside the approved implementation.", tool=name)
            return
        if status != "VERIFYING":
            _engine.emit("deny", f"Subagent action is unavailable while task status is {status or 'missing'}.", tool=name)
            return
        if name == "send_message":
            state = _engine.REPO / ".agents/state" if (_engine.REPO / ".agents").is_dir() else _engine.REPO / "agents/state"
            active = _engine.read_json(state / "active-task.json")
            from workflow import resolve_next_action
            act = resolve_next_action(_engine.REPO, str(active["task_id"]), plan)
            if act.get("code") != "RETRY_REVIEW_PROTOCOL":
                ok_aux_msg, reason_aux_msg, code_aux_msg = _check_host_auxiliary_send_message(
                    _engine.REPO, args, caller_conversation_id=parent_conversation_id,
                )
                if ok_aux_msg:
                    _engine.emit("allow", reason_aux_msg, tool=name, reason_code=code_aux_msg)
                    return
                if code_aux_msg == "SENSITIVE_SUBAGENT_PROMPT_BLOCKED":
                    _engine.emit("deny", reason_aux_msg, tool=name, reason_code=code_aux_msg)
                    return
                _engine.emit(
                    "deny",
                    f"send_message is not permitted during VERIFYING unless retrying review protocol or resuming a tracked host auxiliary subagent (current router action: {act.get('code')}).",
                    tool=name,
                    reason_code="REVIEW_VERIFY_SEND_MESSAGE_FORBIDDEN",
                )
                return
            expected_recipient = str(act.get("recipient") or "").strip()
            expected_msg = str(act.get("message") or "").strip()
            supplied_recipient = str(args.get("Recipient") or args.get("recipient") or "").strip()
            supplied_msg = str(args.get("Message") or args.get("message") or "").strip()
            if not supplied_recipient or supplied_recipient != expected_recipient:
                _engine.emit(
                    "deny",
                    f"send_message recipient mismatch: expected '{expected_recipient}', got '{supplied_recipient}'.",
                    tool=name,
                    reason_code="RETRY_RECIPIENT_MISMATCH",
                )
                return
            if not supplied_msg or supplied_msg.replace("\r\n", "\n").strip() != expected_msg.replace("\r\n", "\n").strip():
                _engine.emit(
                    "deny",
                    "send_message message does not match the required protocol retry prompt.",
                    tool=name,
                    reason_code="RETRY_MESSAGE_MISMATCH",
                )
                return
            _engine.emit("allow", "Protocol retry send_message matches router requirements.", tool=name, reason_code="RETRY_REVIEW_PROTOCOL_ALLOWED")
            return

        if name != "invoke_subagent":
            _engine.emit("allow", "Reviewer management is allowed during verification.", tool=name)
            return

        ver_raw_subs, _ = _engine._normalize_subagent_items(args)
        if ver_raw_subs:
            policy_reviewers_peek: set[str] = set()
            try:
                _st_peek = _engine.REPO / ".agents/state" if (_engine.REPO / ".agents").is_dir() else _engine.REPO / "agents/state"
                _act_peek = _engine.read_json(_st_peek / "active-task.json")
                _cur_peek = _engine.read_json(_st_peek / "tasks" / str(_act_peek["task_id"]) / "current-run.json")
                _pol_peek = _engine.read_json(Path(_cur_peek["policy"]))
                policy_reviewers_peek = {str(r).strip() for r in (_pol_peek.get("reviewers") or []) if str(r).strip()}
            except Exception:
                policy_reviewers_peek = set()
            if not any(_item_touches_harness_or_denied(item, extra_reviewer_roles=policy_reviewers_peek) for item in ver_raw_subs):
                _validate_and_allow_host_auxiliary(ver_raw_subs, name, parent_conversation_id=parent_conversation_id)
                return

        ver_tid = str(plan.get("task_id") or "").strip()
        busy_pid = _engine._detect_live_verification_or_build_owner(_engine.REPO, ver_tid)
        if busy_pid:
            _engine.emit(
                "deny",
                f"CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS: Background verification/Gradle process (PID {busy_pid}) "
                "is still actively running and review briefs are not ready yet. Do NOT speculatively invoke reviewers while "
                "`verify-steps` is running — output one short status sentence and end your turn with ZERO tool calls.",
                tool=name,
                reason_code="CONCURRENT_BUILD_OR_VERIFICATION_IN_PROGRESS",
                task_id=ver_tid,
            )
            return

        try:
            state = _engine.REPO / ".agents/state" if (_engine.REPO / ".agents").is_dir() else _engine.REPO / "agents/state"
            active = _engine.read_json(state / "active-task.json")
            current = _engine.read_json(state / "tasks" / str(active["task_id"]) / "current-run.json")
            protocol = int(current.get("review_protocol_version") or 1)
            policy = _engine.read_json(Path(current["policy"]))
        except Exception:
            _engine.emit("deny", "Review execution profile resolution failed.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
            return
        required_reviewers = list(policy.get("reviewers") or [])

        raw_subs, is_single_top_level = _engine._normalize_subagent_items(args)

        # Determine dispatchable reviewers
        is_unbound_replay = False
        if protocol >= 2:
            from review_orchestrator import load_ledger, dispatchable_reviewers, ledger_file
            directory = state / "tasks" / str(active["task_id"])
            run_id_val = str(current.get("run_id") or "")
            l_path = ledger_file(directory, run_id_val)
            if l_path.is_file():
                ledger = load_ledger(directory, run_id_val)
                dispatchable = dispatchable_reviewers(ledger, required_reviewers)
                revs = ledger.get("reviewers") or {}
                if not dispatchable:
                    if revs and all(
                        d.get("state") == "DISPATCHED" and not d.get("execution_id")
                        for d in revs.values()
                    ):
                        dispatchable = list(required_reviewers)
                        is_unbound_replay = True
                if is_single_top_level and len(raw_subs) == 1 and isinstance(raw_subs[0], dict):
                    hint_role = _engine._canonical_subagent_role(str(raw_subs[0].get("Role") or raw_subs[0].get("TypeName") or "").strip())
                    rev_entry = revs.get(hint_role) or {}
                    if hint_role and hint_role not in dispatchable and rev_entry.get("state") == "DISPATCHED" and not rev_entry.get("execution_id"):
                        dispatchable.append(hint_role)
                        is_unbound_replay = True
            else:
                dispatchable = list(required_reviewers)
        else:
            dispatchable = list(required_reviewers)

        reviewer_routes = {}
        if protocol >= 2:
            try:
                from review_execution import pointer_matches, resolve_execution_profile
                review_host = str(current.get("review_host") or "").strip().lower()
                profile = resolve_execution_profile(_engine.REPO, str(active["task_id"]), host=review_host)
                if not isinstance(profile, dict) or not profile.get("reviewers"):
                    _engine.emit("deny", "Review execution profile is empty or invalid.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                    return
                reviewer_routes = profile.get("reviewers", {})
            except Exception:
                _engine.emit("deny", "Review execution profile resolution failed.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                return

            for r in dispatchable:
                r_info = reviewer_routes.get(r)
                if not r_info:
                    _engine.emit("deny", f"Reviewer '{r}' missing from execution profile.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                    return
                brief_p = Path(r_info.get("brief_path") or "")
                if not brief_p.is_file() or brief_p.stat().st_size == 0:
                    _engine.emit("deny", f"Reviewer brief missing or empty for '{r}'.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                    return
                brief_content = str(r_info.get("brief_content") or "").replace("\r\n", "\n").strip()
                if not brief_content:
                    _engine.emit("deny", f"Reviewer brief unreadable or empty for '{r}'.", tool=name, reason_code="REVIEW_PROFILE_BLOCKED")
                    return
        else:
            try:
                from review_execution import resolve_execution_profile
                review_host = str(current.get("review_host") or "").strip().lower()
                profile = resolve_execution_profile(_engine.REPO, str(active["task_id"]), host=review_host)
                reviewer_routes = profile.get("reviewers", {}) if isinstance(profile, dict) else {}
            except Exception:
                reviewer_routes = {}

        if not isinstance(raw_subs, list) or not raw_subs:
            _engine.emit("deny", "No reviewers specified in Subagents array.", tool=name, reason_code="REVIEWER_ROSTER_EMPTY")
            return

        # Check safety cap / round cap
        from review_budget import review_round_cap_action
        round_block = review_round_cap_action(_engine.REPO, plan, policy)
        if round_block:
            _engine.emit("deny", round_block["reason"], tool=name, reason_code=round_block["code"])
            return
        from review_budget import effective_review_calls_used
        used_calls = effective_review_calls_used(_engine.REPO, plan)
        from review_budget import effective_review_budget
        safety_cap = effective_review_budget(_engine.REPO, plan, policy)
        new_final_dispatches = 0 if is_unbound_replay else (len(raw_subs) if is_single_top_level else len(dispatchable))
        if used_calls + new_final_dispatches > safety_cap:
            _engine.emit(
                "deny",
                "Reviewer Call Safety Cap reached; developer decision is required.",
                tool=name,
                reason_code="REVIEWER_CALL_SAFETY_CAP_REACHED",
            )
            return

        allowed_keys_set = set(_engine.ANTIGRAVITY_SUBAGENT_ALLOWED_KEYS)
        final_run_models = ((current or {}).get("review_models") or {}).get("reviewers") or {}
        actual = []
        for item in raw_subs:
            if not isinstance(item, dict):
                _engine.emit("deny", "Each entry in Subagents array must be an object.", tool=name, reason_code="SUBAGENT_NOT_OBJECT")
                return

            r_role_hint = _engine._canonical_subagent_role(str(item.get("Role") or item.get("TypeName") or item.get("role") or item.get("typeName") or "").strip())
            sel_info = final_run_models.get(r_role_hint) if isinstance(final_run_models, dict) else None
            resolved_m = str((sel_info or {}).get("resolved_model") or "")
            from review_models import reviewer_requires_flash_offload
            needs_flash = reviewer_requires_flash_offload(
                _engine.REPO,
                sel_info if isinstance(sel_info, dict) else {"resolved_model": resolved_m},
                parent_conversation_id=parent_conversation_id,
            )
            allowed_native_model = "flash" if needs_flash else ("pro" if "pro" in resolved_m else None)

            if "model" in item or (not allowed_native_model and "Model" in item):
                bound_note = (
                    f"Reviewer '{r_role_hint}' is bound to '{resolved_m}' via .agents/agents/{r_role_hint}/agent.md frontmatter; omit 'Model' in invoke_subagent."
                    if resolved_m and resolved_m != "inherit"
                    else "Do not send 'model' or 'Model' in reviewer invocation. Reviewer model inheritance is achieved by omission."
                )
                _engine.emit(
                    "deny",
                    f"REVIEWER_MODEL_OVERRIDE_FORBIDDEN: {bound_note}",
                    tool=name,
                    reason_code="REVIEWER_MODEL_OVERRIDE_FORBIDDEN",
                )
                return
            if allowed_native_model == "flash" or "gemini-4-hydrogen" in resolved_m:
                from antigravity_runtime import detect_antigravity_remote_mode, remote_subagents_explicitly_allowed
                from platform_quirks import is_quirk_enabled
                rem_active, rem_signals = detect_antigravity_remote_mode()
                if is_quirk_enabled("198819", repo=_engine.REPO) and rem_active and not remote_subagents_explicitly_allowed():
                    _engine.emit(
                        "deny",
                        (
                            f"REMOTE_MODE_FLASH_QUOTA_LEAK_GUARD (#198819): Antigravity Remote Mode detected ({', '.join(rem_signals)}). "
                            f"Reviewer '{r_role_hint}' is configured for '{resolved_m}', which ignores fast-tier subagent overrides in Remote Mode on Frontier sessions and drains 3x Frontier quota. "
                            "Run reviews in Local Mode, switch reviewer policy to 'inherit' on a Carbon/Claude session, or set HARNESS_ALLOW_REMOTE_SUBAGENTS=1."
                        ),
                        tool=name,
                        reason_code="REMOTE_MODE_FLASH_QUOTA_LEAK_GUARD",
                    )
                    return
            if allowed_native_model and item.get("Model") != allowed_native_model:
                offload_ctx = (
                    " (routes natively to Gemini 4 Hydrogen High 1x regardless of main-chat model)"
                    if resolved_m.startswith(("gemini-4-hydrogen", "gemini-3.8-flash"))
                    else ""
                )
                _engine.emit(
                    "deny",
                    (
                        f"REVIEWER_MODEL_MISMATCH: Reviewer '{r_role_hint}' is configured for '{resolved_m}'{offload_ctx}; "
                        f"you MUST pass Model='{allowed_native_model}' in invoke_subagent."
                    ),
                    tool=name,
                    reason_code="REVIEWER_MODEL_MISMATCH",
                )
                return

            if protocol >= 2:
                if "Role" not in item:
                    _engine.emit("deny", "Subagent entry missing mandatory Role.", tool=name, reason_code="MISSING_SUBAGENT_ROLE")
                    return
                r_role = str(item["Role"]).strip()
                if not r_role:
                    _engine.emit("deny", "Subagent entry Role is empty.", tool=name, reason_code="MISSING_SUBAGENT_ROLE")
                    return

                if "TypeName" not in item:
                    _engine.emit("deny", "Subagent entry missing mandatory TypeName.", tool=name, reason_code="MISSING_SUBAGENT_TYPENAME")
                    return
                r_type = str(item["TypeName"]).strip()
                if not r_type:
                    _engine.emit("deny", "Subagent entry TypeName is empty.", tool=name, reason_code="MISSING_SUBAGENT_TYPENAME")
                    return

                canon_type = _engine._canonical_subagent_role(r_type)
                canon_role = _engine._canonical_subagent_role(r_role)
                if canon_type != canon_role:
                    _engine.emit(
                        "deny",
                        f"Reviewer invocation mismatch: TypeName '{r_type}' does not match Role '{r_role}'. Both must refer to the same reviewer.",
                        tool=name,
                        reason_code="REVIEWER_ROLE_MISMATCH",
                    )
                    return

                matched = canon_role
                if matched not in dispatchable:
                    _engine.emit(
                        "deny",
                        f"Reviewer '{matched}' is not in dispatchable reviewers: {sorted(dispatchable)}.",
                        tool=name,
                        reason_code="REVIEWER_ROSTER_EXTRA",
                    )
                    return
            else:
                r_role = str(item.get("Role") or item.get("role") or "").strip()
                r_type = str(item.get("TypeName") or item.get("typeName") or item.get("name") or "").strip()
                if not r_type and not r_role:
                    _engine.emit("deny", "Subagent entry missing TypeName/Role.", tool=name, reason_code="MISSING_SUBAGENT_ROLE")
                    return
                matched = r_type if r_type in dispatchable else (r_role if r_role in dispatchable else None)
                if not matched:
                    all_exp = set(required_reviewers)
                    matched = r_type if r_type in all_exp else (r_role if r_role in all_exp else (r_type or r_role))

            rev_info = reviewer_routes.get(matched, {})
            rev_reasoning = rev_info.get("reasoning", {}) if isinstance(rev_info, dict) else {}
            control = rev_reasoning.get("control")
            native_val = rev_reasoning.get("native_value")
            arg_name = rev_reasoning.get("argument_name")

            item_allowed_keys = set(allowed_keys_set) | ({"Model"} if allowed_native_model else set())
            if control == "SUPPORTED" and arg_name:
                item_allowed_keys.add(arg_name)

            supplied_reasoning_keys = [k for k in item if k in _engine.COMMON_REASONING_KEYS]
            if control != "SUPPORTED":
                if supplied_reasoning_keys:
                    _engine.emit(
                        "deny",
                        (
                            "This host does not expose trusted per-subagent reasoning control. "
                            "Omit reasoning override and inherit the parent setting."
                        ),
                        tool=name,
                    )
                    return
            else:
                if native_val is not None:
                    if arg_name not in item or str(item[arg_name]) != str(native_val):
                        _engine.emit(
                            "deny",
                            f"Reviewer reasoning override for '{matched}' must use '{arg_name}={native_val}'.",
                            tool=name,
                        )
                        return
                    other_keys = [k for k in supplied_reasoning_keys if k != arg_name]
                    if other_keys:
                        _engine.emit(
                            "deny",
                            f"Unexpected reasoning key '{other_keys[0]}' for '{matched}'. Expected '{arg_name}'.",
                            tool=name,
                        )
                        return
                else:
                    if supplied_reasoning_keys:
                        _engine.emit(
                            "deny",
                            (
                                "This host does not expose trusted per-subagent reasoning control. "
                                "Omit reasoning override and inherit the parent setting."
                            ),
                            tool=name,
                        )
                        return

            for k in item:
                if k not in item_allowed_keys:
                    _engine.emit(
                        "deny",
                        f"Unexpected key '{k}' in subagent invocation. Allowed keys: {sorted(item_allowed_keys)}.",
                        tool=name,
                        reason_code="UNEXPECTED_SUBAGENT_KEY",
                    )
                    return

            if matched in actual:
                _engine.emit("deny", f"Reviewer batch contains duplicate reviewer: '{matched}'.", tool=name, reason_code="DUPLICATE_REVIEWER")
                return
            actual.append(matched)

            if protocol >= 2:
                if "Prompt" not in item:
                    _engine.emit("deny", "Subagent entry missing mandatory Prompt.", tool=name, reason_code="MISSING_SUBAGENT_PROMPT")
                    return
                supplied_prompt = str(item["Prompt"]).replace("\r\n", "\n").strip()
                if not supplied_prompt:
                    _engine.emit("deny", "Subagent entry Prompt is empty.", tool=name, reason_code="MISSING_SUBAGENT_PROMPT")
                    return
                route = reviewer_routes[matched]
                expected_prompt = str(route.get("brief_content") or "").replace("\r\n", "\n").strip()
                alt_briefs = [str(p) for p in (route.get("short_brief_path"), route.get("canonical_brief_path")) if p]
                prior_digs = list(route.get("accepted_prior_brief_digests") or [])
                if supplied_prompt != expected_prompt and not pointer_matches(
                    supplied_prompt,
                    matched,
                    str(route.get("brief_path") or ""),
                    expected_prompt,
                    alternate_paths=alt_briefs,
                    accepted_digests=prior_digs,
                ):
                    _engine.emit(
                        "deny",
                        f"Reviewer prompt for '{matched}' does not match the generated reviewer brief. Pass the router's "
                        "`reviewer_prompts[role]` one-line pointer (preferred) or the exact current brief content.",
                        tool=name,
                        reason_code="REVIEWER_PROMPT_MISMATCH",
                    )
                    return

        # Exact batch check
        actual_set = set(actual)
        dispatchable_set = set(dispatchable)
        if actual_set != dispatchable_set:
            missing = dispatchable_set - actual_set
            extra = actual_set - dispatchable_set
            if extra:
                _engine.emit(
                    "deny",
                    f"Reviewer batch contains extra reviewers: expected {sorted(dispatchable_set)}, got {sorted(actual_set)}.",
                    tool=name,
                    reason_code="REVIEWER_ROSTER_EXTRA",
                )
                return
            if missing and not is_single_top_level:
                _engine.emit(
                    "deny",
                    f"Reviewer batch incomplete: expected {len(dispatchable_set)} reviewers ({sorted(dispatchable_set)}), got {len(actual_set)} ({sorted(actual_set)}). All dispatchable reviewers must be launched in a single invoke_subagent call.",
                    tool=name,
                    reason_code="REVIEWER_ROSTER_INCOMPLETE",
                )
                return

        # Persist reviewer dispatch receipts for provable independent execution
        try:
            task_id = str(active.get("task_id") or "")
            if not task_id:
                raise RuntimeError("active task_id is missing")
            run_id = _engine.validate_id(str(current.get("run_id") or ""), "run_id")
            manifest_p = str(current.get("manifest") or "").strip()
            if not manifest_p:
                raise RuntimeError("active run manifest is missing")
            manifest = _engine.read_json(Path(manifest_p))
            snapshot = str(manifest.get("delivery_snapshot_sha256") or "").strip()
            if not _engine.re.fullmatch(r"[0-9a-f]{64}", snapshot):
                raise RuntimeError("delivery snapshot identity is missing or invalid")
            package_path = _engine.active_review_package_path(_engine.REPO, current)
            if not package_path.is_file():
                raise RuntimeError("review package is missing")
            package_sha = _engine.sha256_file(package_path)
            if not _engine.re.fullmatch(r"[0-9a-f]{64}", package_sha):
                raise RuntimeError("review package digest is invalid")
            if protocol >= 2:
                from review_orchestrator import record_dispatch_batch
                review_host = str(current.get("review_host") or "").strip().lower()
                record_dispatch_batch(
                    _engine.REPO,
                    task_id,
                    sorted(actual),
                    host=review_host,
                    allow_single=is_single_top_level,
                )
            else:
                receipts_dir = state / "tasks" / task_id / "reviewer-dispatches"
                receipts_dir.mkdir(parents=True, exist_ok=True)
                from _vnext_common import atomic_write_json, canonical_sha256, utc_now
                for r in actual:
                    receipt_file = receipts_dir / f"{r}.json"
                    receipt_data = {
                        "schema_version": 1,
                        "task_id": task_id,
                        "run_id": run_id,
                        "reviewer": r,
                        "subagent_id": "",
                        "review_package_sha256": package_sha,
                        "dispatched_at": utc_now(),
                        "host": str(current.get("review_host") or "antigravity"),
                    }
                    receipt_data["receipt_sha256"] = canonical_sha256({
                        k: v for k, v in receipt_data.items() if k != "receipt_sha256"
                    })
                    atomic_write_json(receipt_file, receipt_data)
        except Exception as exc:
            _engine.emit(
                "deny",
                f"[REVIEW_RECEIPT_WRITE_FAILED] Failed creating reviewer dispatch receipt ({type(exc).__name__}).",
                tool=name,
            )
            return

        _engine.emit("allow", "Reviewer roster exactly matches the immutable adaptive policy.", tool=name)
    except Exception as exc:
        _engine.emit("deny", f"Reviewer policy validation failed closed: {exc}", tool=name)
def _canonical_subagent_role(raw_name: str) -> str:
    s = str(raw_name or "").strip()
    m = _engine.re.fullmatch(r"([a-z0-9-]+-agent)-(?:live|r[1-9])", s)
    if m:
        base = m.group(1)
        allowed = set(_engine.CORE_UTILITY_AGENTS) | set(_engine.CORE_ROUTED_REVIEWERS) | set(_engine.ON_DEMAND_SPECIALIST_AGENTS) | {"harness-worker-agent"}
        if base in allowed:
            return base
    return s
def _has_unfinalized_active_review_wave(repo: Path) -> tuple[bool, str]:
    """Return (True, detail) if an active VERIFYING or PHASE_REVIEWING run has unfinalized reviewers."""
    try:
        state_dir = repo / ".agents/state" if (repo / ".agents").is_dir() else repo / "agents/state"
        active_f = state_dir / "active-task.json"
        if not active_f.is_file():
            return (False, "")
        tid = str(_engine.read_json(active_f).get("task_id") or "").strip()
        if not tid:
            return (False, "")
        tdir = state_dir / "tasks" / tid
        plan_f = tdir / "plan.json"
        if not plan_f.is_file():
            return (False, "")
        plan = _engine.read_json(plan_f)
        status = str(plan.get("status") or "")
        if status == "VERIFYING":
            crun_f = tdir / "current-run.json"
            if crun_f.is_file():
                crun = _engine.read_json(crun_f)
                run_id = str(crun.get("run_id") or "")
                snap = str(crun.get("delivery_snapshot_sha256") or "")
                rev_ev = state_dir / "runs" / snap / run_id / "reviews.json"
                if run_id and not rev_ev.is_file():
                    ledger_f = tdir / "review-execution" / run_id / "ledger.json"
                    if ledger_f.is_file():
                        revs = (_engine.read_json(ledger_f).get("reviewers") or {})
                        if any(isinstance(v, dict) and v.get("state") in {"DISPATCHED", "ENV_BLOCKED", "PROTOCOL_RETRY_REQUIRED"} for v in revs.values()):
                            return (True, f"task `{tid}` final review `{run_id}`")
        elif status == "IMPLEMENTING":
            ps_f = tdir / "phase-state.json"
            if ps_f.is_file():
                ps = _engine.read_json(ps_f)
                cur_p = str(ps.get("current_phase_id") or "")
                p_substates = ps.get("phase_substates") or {}
                p_legacy = ps.get("phases") or {}
                sub_entry = p_substates.get(cur_p) if cur_p and isinstance(p_substates, dict) else None
                leg_entry = p_legacy.get(cur_p) if cur_p and isinstance(p_legacy, dict) else None
                eff_sub = str(
                    (sub_entry.get("substate") if isinstance(sub_entry, dict) else "")
                    or (leg_entry.get("substate") if isinstance(leg_entry, dict) else "")
                    or ps.get("substate")
                    or ""
                ).strip().upper()
                if eff_sub in {"REVIEWING", "PHASE_REVIEWING"}:
                    return (True, f"task `{tid}` phase `{cur_p or 'active'}` review")
    except Exception:
        return (False, "")
    return (False, "")
def _validate_define_subagent(args: dict, tool_name: str) -> tuple[bool, str, str]:
    raw_sub_name = str(args.get("Name") or args.get("name") or "").strip()
    sub_name = _engine._canonical_subagent_role(raw_sub_name)
    if sub_name == "harness-worker-agent":
        return (
            False,
            "WORKER_AGENT_RETIRED_INLINE_LEAD_ONLY: `harness-worker-agent` has been retired. Implement approved changes directly on the warm Lead session.",
            "WORKER_AGENT_RETIRED_INLINE_LEAD_ONLY",
        )
    allowed_all = set(_engine.CORE_UTILITY_AGENTS) | set(_engine.CORE_ROUTED_REVIEWERS) | set(_engine.ON_DEMAND_SPECIALIST_AGENTS)
    if sub_name not in allowed_all:
        return (
            False,
            f"Unsupported custom subagent definition '{raw_sub_name}'. Only harness-governed subagents {sorted(allowed_all)} (or `<role>-live` recovery aliases) may be registered.",
            "UNSUPPORTED_SUBAGENT_DEFINITION",
        )
    if bool(
        args.get("EnableSubagentTools")
        or args.get("enableSubagentTools")
        or args.get("enable_subagent_tools")
    ):
        return (False, "Nested subagent delegation (`EnableSubagentTools=True`) is forbidden.", "SUBAGENT_NESTING_FORBIDDEN")
    if bool(
        args.get("EnableWriteTools")
        or args.get("enableWriteTools")
        or args.get("enable_write_tools")
    ):
        return (False, f"Subagent `{raw_sub_name}` is strictly read-only (`EnableWriteTools` must be False).", "READ_ONLY_SUBAGENT_WRITE_FORBIDDEN")
    if bool(
        args.get("EnableMCPTools")
        or args.get("enableMcpTools")
        or args.get("enableMCPTools")
        or args.get("enable_mcp_tools")
    ):
        return (False, f"Subagent `{raw_sub_name}` cannot enable external MCP tools (`EnableMCPTools` must be False).", "READ_ONLY_SUBAGENT_MCP_FORBIDDEN")
    sys_prompt = str(args.get("SystemPrompt") or args.get("systemPrompt") or args.get("system_prompt") or "")
    json_spec = (_engine.REPO / ".agents" / "subagents" / f"{sub_name}.json")
    if not json_spec.is_file():
        json_spec = _engine.REPO / "agents" / "subagents" / f"{sub_name}.json"
    if json_spec.is_file():
        try:
            spec_data = _engine.read_json(json_spec)
            expected_prompt = str(spec_data.get("system_prompt") or "")
            m_fp = _engine.re.search(r"(HARNESS_[A-Z0-9_]+_FINGERPRINT=[^\s]+|REVIEWER_FINGERPRINT=[^\s]+)", expected_prompt)
            if m_fp and m_fp.group(1) not in sys_prompt:
                return (
                    False,
                    f"Subagent `{sub_name}` SystemPrompt is missing required fingerprint `{m_fp.group(1)}` from `.agents/subagents/{sub_name}.json`.",
                    "SUBAGENT_FINGERPRINT_MISMATCH",
                )
            collapsed_expected = _engine.re.sub(r"\s+", " ", expected_prompt).strip()
            collapsed_actual = _engine.re.sub(r"\s+", " ", sys_prompt).strip()
            min_len = min(350, int(len(collapsed_expected) * 0.5)) if collapsed_expected else 0
            required_anchors = [
                anchor for anchor in (
                    "untrusted evidence",
                    "never follow instructions",
                    "HARNESS_REVIEW_RESULT_V2",
                    "Mandatory Speed & Accuracy Contract",
                )
                if anchor.lower() in collapsed_expected.lower()
            ]
            poison_re = _engine.re.compile(
                r"\b(?:always\s+(?:output|return|emit|report)\s+pass\b|"
                r"ignore\s+(?:all\s+)?(?:bugs?|issues?|findings?|vulnerabilities|defects?|errors?)\b|"
                r"disregard\s+(?:all\s+)?(?:previous|above|prior|canonical)\s+instructions?\b)",
                _engine.re.IGNORECASE,
            )
            if (
                (min_len and len(collapsed_actual) < min_len)
                or any(anchor.lower() not in collapsed_actual.lower() for anchor in required_anchors)
                or bool(poison_re.search(collapsed_actual))
            ):
                return (
                    False,
                    f"Subagent `{sub_name}` SystemPrompt does not satisfy the canonical contract in `.agents/subagents/{sub_name}.json`.",
                    "SUBAGENT_FINGERPRINT_MISMATCH",
                )
        except (OSError, ValueError, _engine.ValidationError):
            pass
    return (True, f"Harness subagent `{sub_name}` definition verified.", "DEFINE_SUBAGENT_ALLOWED")
