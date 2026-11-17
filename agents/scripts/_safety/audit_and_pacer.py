"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


def _audit_path() -> Path:
    override = _engine.os.environ.get("HARNESS_HOOK_STATE")
    base = Path(override) if override else Path(__file__).resolve().parent.parent / "state" / "hook-state.json"
    return base.with_name("audit_log.jsonl")
def _audit(
    decision: str,
    reason: str,
    tool: str,
    command: str,
    *,
    reason_code: str = "",
    conv_hint: str = "",
    task_id: str = "",
    mcp_fingerprint: str = "",
) -> None:
    try:
        path = _engine._audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import time
        cmd_hash = _engine.hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest()[:12] if command else ""
        code = reason_code or ("DENIED" if decision == "deny" else "ALLOWED")
        record = {
            "schema_version": 1,
            "ts": time.time(),
            "decision": decision,
            "tool": tool[:80],
            "reason_code": code,
            "reason_short": reason[:160],
            "reason": reason[:160],
            "cmd_sha256_12": cmd_hash,
            "command_sha256_12": cmd_hash,
            "conv_hint": conv_hint,
        }
        if task_id:
            record["task_id"] = task_id
        if mcp_fingerprint:
            record["mcp_fingerprint"] = mcp_fingerprint
        from evidence_store import StateLock
        # Separate from the task lock: audit may be called while task state is
        # locked. Serialize append/rotation so concurrent reviewers lose no rows.
        with StateLock(path.parent / ".audit-lock"):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(_engine.json.dumps(record, sort_keys=True) + "\n")
            if path.stat().st_size > _engine.AUDIT_ROTATE_BYTES:
                # Read only a bounded tail, and amortize rotation across calls.
                with path.open("rb") as handle:
                    handle.seek(max(0, path.stat().st_size - _engine.AUDIT_ROTATE_BYTES // 2))
                    handle.readline()  # discard the possibly partial first row
                    tail = handle.read().splitlines()[-_engine.AUDIT_MAX_RECORDS:]
                from _vnext_common import atomic_write_bytes
                atomic_write_bytes(path, b"\n".join(tail) + b"\n")
    except (OSError, ValueError, ImportError, _engine.ValidationError):
        pass
def _burst_pacer_default_mode() -> str:
    explicit = _engine.os.environ.get("HARNESS_BURST_PACER_MODE", "").strip().lower()
    if explicit in {"off", "0", "false", "disabled"}:
        return "off"
    if explicit in {"enforce", "live"}:
        return "enforce"
    if explicit == "record_only":
        return "record_only"
    if _engine.os.environ.get("HARNESS_HOOK_SELFTEST_ACTIVE") == "1" or "unittest" in _engine.sys.modules:
        return "record_only"
    return "enforce"
def _model_exempt_from_hydrogen_burst_pacer(model_name: str) -> bool:
    """Antigravity hooks pass `modelName` on stdin (https://antigravity.google/docs/hooks/).
    Slow Frontier models (Carbon, Argon, Claude 5.5, 3.1 Pro) never trigger Hydrogen's 190 tok/s burst filter,
    whereas Hydrogen, Orchestrator, and untagged sessions require anti-burst protection.
    """
    m = str(model_name or "").strip().lower()
    if not m or "hydrogen" in m or "orchestrator" in m or "gemini-4-flash" in m:
        return False
    return any(tok in m for tok in ("carbon", "argon", "claude", "sonnet", "opus", "3.1-pro", "gpt-oss", "gpt-5", "gpt-6"))
def check_and_apply_hydrogen_burst_pacer(
    repo: Path,
    conversation_id: str,
    *,
    tool_name: str = "",
    model_name: str = "",
    mode: str | None = None,
    pacer_path_override: Path | None = None,
    now_fn=None,
    sleep_fn=None,
) -> dict[str, object]:
    """Smooth rapid sequential multi-turn bursts (#200029 / #199971) without delaying parallel batches."""
    import hashlib as _hashlib
    import time as _time

    eff_mode = (mode or _engine._burst_pacer_default_mode()).strip().lower()
    cid = str(conversation_id or "").strip()
    try:
        from platform_quirks import is_quirk_enabled
        if mode is None and not is_quirk_enabled("200029", repo=repo):
            return {"applied": False, "delay_sec": 0.0, "coalesced_parallel": False, "turns_in_window": 0, "mode": "quirk_disabled"}
    except ImportError:
        pass
    if eff_mode == "off" or not cid:
        return {"applied": False, "delay_sec": 0.0, "coalesced_parallel": False, "turns_in_window": 0, "mode": eff_mode}
    if mode is None and _engine._model_exempt_from_hydrogen_burst_pacer(model_name):
        return {"applied": False, "delay_sec": 0.0, "coalesced_parallel": False, "turns_in_window": 0, "mode": "exempt_frontier_model"}

    is_raw_kit = (repo / "harness_cli.py").is_file() and (repo / "agents" / "VERSION").is_file() and not (repo / ".agents").is_dir()
    if is_raw_kit and pacer_path_override is None:
        return {"applied": False, "delay_sec": 0.0, "coalesced_parallel": False, "turns_in_window": 0, "mode": eff_mode}

    clock = now_fn or _time.time
    sleeper = sleep_fn or _time.sleep
    pacer_path = pacer_path_override or (repo / ".agents" / "cache" / "burst-pacer.json")

    now = float(clock())
    delay_sec = 0.0
    coalesced = False
    turns_in_window = 1

    try:
        from evidence_store import StateLock
        pacer_path.parent.mkdir(parents=True, exist_ok=True)
        with StateLock(pacer_path.parent / ".burst-pacer-lock"):
            store: dict[str, object] = {}
            if pacer_path.is_file():
                try:
                    loaded = _engine.json.loads(pacer_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        store = loaded
                except (OSError, ValueError):
                    store = {}

            sessions_raw = store.get("sessions")
            sessions: dict[str, dict[str, object]] = dict(sessions_raw) if isinstance(sessions_raw, dict) else {}
            sessions = {
                str(k): dict(v)
                for k, v in list(sessions.items())[-32:]
                if isinstance(v, dict) and (now - float(v.get("last_call_epoch") or 0.0)) <= 3600.0
            }

            rec = sessions.get(cid)
            if not isinstance(rec, dict):
                rec = {"turn_anchors": [], "last_call_epoch": 0.0, "throttled_count": 0, "coalesced_count": 0}

            last_call = float(rec.get("last_call_epoch") or 0.0)
            raw_anchors = rec.get("turn_anchors")
            anchors = [
                float(ts) for ts in (raw_anchors if isinstance(raw_anchors, list) else [])
                if isinstance(ts, (int, float)) and (now - float(ts)) <= _engine.BURST_WINDOW_SEC
            ]

            if last_call > 0.0 and 0.0 <= (now - last_call) <= _engine.BURST_COALESCE_PARALLEL_SEC:
                coalesced = True
                rec["coalesced_count"] = int(rec.get("coalesced_count") or 0) + 1
                if not anchors:
                    anchors.append(now)
                turns_in_window = len(anchors)
            else:
                anchors.append(now)
                turns_in_window = len(anchors)
                if turns_in_window >= _engine.BURST_TURN_THRESHOLD:
                    extra_turns = turns_in_window - _engine.BURST_TURN_THRESHOLD
                    jitter_seed = _hashlib.sha256(f"{cid}:{turns_in_window}:{tool_name}".encode("utf-8")).digest()[0]
                    jitter = (jitter_seed / 255.0) * 0.12
                    delay_sec = round(min(_engine.BURST_MAX_DELAY_SEC, _engine.BURST_BASE_DELAY_SEC + extra_turns * _engine.BURST_STEP_DELAY_SEC + jitter), 3)
                    rec["throttled_count"] = int(rec.get("throttled_count") or 0) + 1
                    store["throttled_events"] = int(store.get("throttled_events") or 0) + 1
                    store["total_delay_ms"] = int(store.get("total_delay_ms") or 0) + int(round(delay_sec * 1000))
                    store["last_throttled_tool"] = str(tool_name or "")
                    store["last_throttled_epoch"] = now

            effective_epoch = now + (delay_sec if (delay_sec > 0.0 and eff_mode == "enforce") else 0.0)
            rec["turn_anchors"] = anchors[-16:]
            rec["last_call_epoch"] = effective_epoch
            sessions[cid] = rec
            store["schema_version"] = 1
            store["coalesced_parallel_calls"] = int(store.get("coalesced_parallel_calls") or 0) + (1 if coalesced else 0)
            store["sessions"] = sessions

            tmp = pacer_path.with_suffix(f".{_engine.os.getpid()}.tmp")
            tmp.write_text(_engine.json.dumps(store), encoding="utf-8")
            _engine.os.replace(tmp, pacer_path)

        if delay_sec > 0.0 and eff_mode == "enforce":
            sleeper(delay_sec)
    except (OSError, _engine.ValidationError):
        return {"applied": False, "delay_sec": 0.0, "coalesced_parallel": coalesced, "turns_in_window": turns_in_window, "mode": eff_mode}

    return {
        "applied": delay_sec > 0.0,
        "delay_sec": delay_sec,
        "coalesced_parallel": coalesced,
        "turns_in_window": turns_in_window,
        "mode": eff_mode,
    }
def emit(
    decision: str,
    reason: str,
    *,
    tool: str = "",
    command: str = "",
    reason_code: str = "",
    conv_hint: str = "",
    task_id: str = "",
    mcp_fingerprint: str = "",
) -> None:
    eff_conv = conv_hint or _engine._ACTIVE_HOOK_CONVERSATION_ID
    if decision == "allow" and eff_conv:
        _engine.check_and_apply_hydrogen_burst_pacer(_engine.REPO, eff_conv, tool_name=tool, model_name=_engine._ACTIVE_HOOK_MODEL_NAME)
    _engine._audit(decision, reason, tool, command, reason_code=reason_code, conv_hint=eff_conv, task_id=task_id, mcp_fingerprint=mcp_fingerprint)
    # Antigravity decodes hook stdout with protojson and rejects unknown fields, so the
    # result carries only its schema; reason codes and fingerprints live in the audit log.
    print(_engine.json.dumps({"decision": decision, "reason": reason}, ensure_ascii=False))
def _enforce_search_web_parallel_cap(conv_key: str) -> bool:
    """Block 3+ parallel `search_web` calls or back-to-back multi-call bursts (#201621 17m `unexpected EOF` hang)."""
    try:
        from platform_quirks import is_quirk_enabled
        if not is_quirk_enabled("201621", repo=_engine.REPO):
            return False
    except ImportError:
        pass
    key = str(conv_key or "default").strip() or "default"
    cache_dir = (_engine.REPO / ".agents" / "cache") if (_engine.REPO / ".agents").is_dir() else (_engine.REPO / "agents" / "state" / "cache")
    guard_path = cache_dir / "search-web-guard.json"
    lock_base = (_engine.REPO / ".agents" / "state") if (_engine.REPO / ".agents").is_dir() else (_engine.REPO / "agents" / "state")
    now = _engine.time.time()
    try:
        from _vnext_common import atomic_write_json
        from evidence_store import StateLock
        lock_base.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        with StateLock(lock_base):
            store: dict[str, Any] = {}
            if guard_path.is_file():
                try:
                    loaded = _engine.read_json(guard_path)
                    if isinstance(loaded, dict):
                        store = loaded
                except (OSError, ValueError, _engine.ValidationError):
                    store = {}
            pruned_store: dict[str, list[float]] = {}
            for ck, stamps in store.items():
                if isinstance(stamps, list):
                    kept = [float(t) for t in stamps if isinstance(t, (int, float)) and 0.0 <= (now - float(t)) <= _engine.SEARCH_WEB_WAVE_WINDOW_SEC]
                    if kept:
                        pruned_store[str(ck)] = kept
            cur_stamps = pruned_store.get(key, [])
            in_burst = [t for t in cur_stamps if (now - t) <= _engine.SEARCH_WEB_BURST_WINDOW_SEC]
            if len(in_burst) >= _engine.SEARCH_WEB_MAX_PARALLEL_CALLS or len(cur_stamps) >= _engine.SEARCH_WEB_MAX_WAVE_CALLS:
                _engine.emit(
                    "deny",
                    "SEARCH_WEB_PARALLEL_CAP_REACHED (#201621): Do NOT issue 3+ parallel `search_web` calls in one turn "
                    "or back-to-back multi-call waves (exhausts the Windows cloud search pool and freezes the turn for 17 minutes "
                    "with `unexpected EOF`). Check `.agents/project-context/` first and coalesce keywords into 1-2 focused queries.",
                    tool="search_web",
                    reason_code="SEARCH_WEB_PARALLEL_CAP_REACHED",
                )
                return True
            cur_stamps.append(now)
            pruned_store[key] = cur_stamps[-8:]
            atomic_write_json(guard_path, pruned_store)
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        return False
    return False
