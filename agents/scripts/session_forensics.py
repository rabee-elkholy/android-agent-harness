"""Read-only Session & Token Forensics (`harness.py diagnose-session`).

Inspired by `diagnosing-superpowers` and adapted for Android Agent Harness's hook-audit
and EvidenceStore telemetry. Inspects `.agents/cache/hook-audit.jsonl`, active task state,
and Antigravity JSONL transcripts (when present) to pinpoint exact root causes of hook
denial streaks, repeated out-of-scope reads, review round caps, or context token spikes,
with optional Zero-PII scrubbed diagnostic bundle export.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _vnext_common import ValidationError, atomic_write_json, read_json, state_root, utc_now  # noqa: E402


def _audit_log_candidates(repo: Path) -> list[Path]:
    cands: list[Path] = []
    env_p = os.environ.get("HARNESS_HOOK_STATE", "").strip()
    if env_p:
        cands.append(Path(env_p))
    cands.extend([
        state_root(repo) / "audit_log.jsonl",
        repo / ".agents" / "state" / "audit_log.jsonl",
        repo / ".agents" / "cache" / "hook-audit.jsonl",
        repo / ".agents" / "state" / "hook-audit.jsonl",
        Path.home() / ".android-harness" / "hook-audit.jsonl",
    ])
    return [p for p in cands if p.is_file()]


def _analyze_hook_audit(repo: Path) -> dict[str, Any]:
    paths = _audit_log_candidates(repo)
    if not paths:
        return {
            "audit_file": "",
            "total_events": 0,
            "allow_count": 0,
            "deny_count": 0,
            "denials_by_code": {},
            "max_consecutive_denials": 0,
            "denial_streaks": [],
            "out_of_scope_reads": [],
        }
    audit_path = paths[0]
    records: list[dict[str, Any]] = []
    try:
        raw_lines = audit_path.read_text(encoding="utf-8", errors="replace").splitlines()[-600:]
        for idx, ln in enumerate(raw_lines, start=1):
            if ln.strip():
                try:
                    obj = json.loads(ln)
                    if isinstance(obj, dict):
                        obj["_line"] = idx
                        records.append(obj)
                except ValueError:
                    continue
    except OSError:
        pass

    allow_cnt = 0
    deny_cnt = 0
    by_code: Counter[str] = Counter()
    out_of_scope: list[str] = []
    cur_streak: list[dict[str, Any]] = []
    streaks: list[dict[str, Any]] = []
    max_streak = 0

    for rec in records:
        dec = str(rec.get("decision") or "").lower()
        code = str(rec.get("reason_code") or "UNSPECIFIED")
        if dec == "deny":
            deny_cnt += 1
            by_code[code] += 1
            cur_streak.append({
                "line": rec.get("_line"),
                "tool": str(rec.get("tool") or ""),
                "reason_code": code,
                "reason": str(rec.get("reason") or "")[:160],
            })
            if len(cur_streak) > max_streak:
                max_streak = len(cur_streak)
        else:
            allow_cnt += 1
            if len(cur_streak) >= 2:
                streaks.append({
                    "length": len(cur_streak),
                    "start_line": cur_streak[0]["line"],
                    "end_line": cur_streak[-1]["line"],
                    "codes": [x["reason_code"] for x in cur_streak],
                    "sample_reason": cur_streak[0]["reason"],
                })
            cur_streak = []
            if code == "READ_OUTSIDE_SCOPE":
                out_of_scope.append(str(rec.get("reason") or "")[:140])

    if len(cur_streak) >= 2:
        streaks.append({
            "length": len(cur_streak),
            "start_line": cur_streak[0]["line"],
            "end_line": cur_streak[-1]["line"],
            "codes": [x["reason_code"] for x in cur_streak],
            "sample_reason": cur_streak[0]["reason"],
        })

    return {
        "audit_file": str(audit_path),
        "total_events": len(records),
        "allow_count": allow_cnt,
        "deny_count": deny_cnt,
        "denials_by_code": dict(by_code.most_common(12)),
        "max_consecutive_denials": max_streak,
        "denial_streaks": streaks[-6:],
        "out_of_scope_reads": out_of_scope[-10:],
    }


def _analyze_transcript(conversation_id: str) -> dict[str, Any]:
    if not conversation_id:
        return {"available": False, "conversation_id": ""}
    tp: Path | None = None
    try:
        from antigravity_runtime import prefer_full_transcript, resolve_transcript
        cand = prefer_full_transcript(resolve_transcript(conversation_id))
        if isinstance(cand, Path) and cand.is_file():
            tp = cand
    except (ImportError, OSError, ValueError):
        tp = None

    if tp is None:
        return {"available": False, "conversation_id": conversation_id}

    step_count = 0
    peak_tokens = 0
    peak_step = 0
    malformed_calls = 0
    http_503_retries = 0
    zero_quota_429_hits = 0
    hydrogen_entitlement_blocks = 0
    orchestrator_handoff_hits = 0
    tos_violation_403_hits = 0
    hydrogen_extra_leak_hits = 0
    hydrogen_medium_zero_thinking_hits = 0
    saw_workspace_read_tool = False
    session_seen_hydrogen_medium = False
    workspace_read_tools = frozenset({
        "read_file", "view_file", "view_file_outline", "view_code_item",
        "grep_search", "find_by_name", "list_dir",
    })
    turn3_cache_drop_hits = 0
    cache_regression_hits = 0
    long_wait_cache_ttl_drops = 0
    max_ttl_drop_wait_sec = 0.0
    prev_cached_tokens = 0
    prev_prompt_tokens = 0
    prev_usage_epoch: float | None = None
    inter_turn_tool_wait_sec = 0.0
    usage_turn_index = 0
    search_web_eof_stalls = 0
    max_search_web_sec = 0.0
    max_parallel_search_web = 0
    pending_search_web_ts: float | None = None
    iso_ts_re = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))")
    tool_counts: Counter[str] = Counter()

    def _parse_step_epoch(step_obj: dict[str, Any], raw_ln: str) -> float | None:
        from datetime import datetime as _dt
        ts_v = step_obj.get("created_at") or step_obj.get("timestamp") or step_obj.get("ts")
        if isinstance(ts_v, (int, float)) and ts_v > 1_000_000_000:
            return float(ts_v)
        m_t = iso_ts_re.search(str(ts_v or "") or raw_ln)
        if m_t:
            try:
                return _dt.fromisoformat(m_t.group(1).replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
        return None

    try:
        from antigravity_runtime import native_model_metadata
        n_meta = native_model_metadata(tp)
        if isinstance(n_meta, dict):
            hm_raw = str(n_meta.get("host_configured_model") or "").lower()
            if re.search(r"gemini-4-hydrogen-(?:tiered-)?medium\b|hydrogen[\s@(-]+medium\b", hm_raw):
                session_seen_hydrogen_medium = True
    except (ImportError, OSError, ValueError, ValidationError):
        session_seen_hydrogen_medium = False

    try:
        lines = tp.read_text(encoding="utf-8", errors="replace").splitlines()[-800:]
        for idx, ln in enumerate(lines, start=1):
            low = ln.lower()
            if "malformed function call" in low or "function call is empty" in low:
                malformed_calls += 1
            if "503" in low and ("unavailable" in low or "retry" in low or "backoff" in low or "overloaded" in low):
                http_503_retries += 1
            if "tos_violation" in low or (("403" in low or "permission_denied" in low) and ("suspended" in low or "flagged" in low or "tos_violation" in low)):
                tos_violation_403_hits += 1
            elif "hydrogen" in low and ("not available on your plan" in low or "model_not_found" in low or "model not found" in low or ("permission_denied" in low and "hydrogen" in low)):
                hydrogen_entitlement_blocks += 1
            elif ("429" in low or "resource_exhausted" in low) and ("limit: 0" in low or "0 requests per day" in low or "0 input tokens per minute" in low):
                zero_quota_429_hits += 1
            if "effort isn't adjustable for orchestrator" in low or ("orchestrator" in low and "handing control back to gemini 4 carbon" in low):
                orchestrator_handoff_hits += 1
            if "gemini-4-hydrogen-extra" in low or "gemini-4-hydrogen-xhigh" in low:
                hydrogen_extra_leak_hits += 1
            if (
                "gemini-4-hydrogen-medium" in low
                or "gemini-4-hydrogen-tiered-medium" in low
                or "gemini 4 hydrogen (medium)" in low
                or "hydrogen@medium" in low
            ):
                session_seen_hydrogen_medium = True
            if "search_web" in low and "unexpected eof" in low:
                search_web_eof_stalls += 1
            if not (ln.strip().startswith("{") and ln.strip().endswith("}")):
                continue
            try:
                obj = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            s_idx = obj.get("step_index")
            cur_step = int(s_idx) if isinstance(s_idx, int) else idx
            if cur_step > step_count:
                step_count = cur_step
            step_epoch = _parse_step_epoch(obj, ln)
            if pending_search_web_ts is not None and step_epoch is not None and step_epoch >= pending_search_web_ts:
                sw_elapsed = step_epoch - pending_search_web_ts
                if sw_elapsed > max_search_web_sec:
                    max_search_web_sec = sw_elapsed
                if sw_elapsed > 300.0 or "unexpected eof" in low:
                    search_web_eof_stalls += 1
                pending_search_web_ts = None
            elif pending_search_web_ts is not None and "unexpected eof" in low:
                search_web_eof_stalls += 1
                pending_search_web_ts = None

            step_had_workspace_read = False
            t_name = str(obj.get("tool_name") or ((obj.get("toolCall") or {}).get("name") if isinstance(obj.get("toolCall"), dict) else "") or "")
            if t_name:
                tool_counts[t_name] += 1
                if t_name in workspace_read_tools:
                    step_had_workspace_read = True
            t_calls_arr = obj.get("tool_calls") if isinstance(obj.get("tool_calls"), list) else []
            sw_in_turn = 0
            for tc_item in t_calls_arr:
                if isinstance(tc_item, dict):
                    tc_n = str(tc_item.get("name") or tc_item.get("tool_name") or ((tc_item.get("function") or {}).get("name") if isinstance(tc_item.get("function"), dict) else "") or "")
                    if tc_n:
                        tool_counts[tc_n] += 1
                        if tc_n == "search_web":
                            sw_in_turn += 1
                        if tc_n in workspace_read_tools:
                            step_had_workspace_read = True
            step_model_str = str(
                obj.get("model")
                or obj.get("model_name")
                or obj.get("modelName")
                or ((obj.get("metadata") or {}).get("model") if isinstance(obj.get("metadata"), dict) else "")
                or ""
            ).strip().lower()
            step_is_non_medium_model = bool(
                step_model_str
                and not (
                    "hydrogen-medium" in step_model_str
                    or "hydrogen-tiered-medium" in step_model_str
                    or "hydrogen (medium)" in step_model_str
                    or "hydrogen@medium" in step_model_str
                )
            )
            if t_name == "search_web":
                sw_in_turn = max(sw_in_turn, 1)
            if sw_in_turn > max_parallel_search_web:
                max_parallel_search_web = sw_in_turn
            step_dur_ms = obj.get("duration_ms") or obj.get("elapsed_ms")
            step_dur_sec = (
                (float(step_dur_ms) / 1000.0)
                if isinstance(step_dur_ms, (int, float))
                else float(obj.get("duration_seconds") or obj.get("elapsed_seconds") or 0.0)
            )
            if step_dur_sec > inter_turn_tool_wait_sec:
                inter_turn_tool_wait_sec = step_dur_sec
            if sw_in_turn > 0:
                if step_dur_sec > max_search_web_sec:
                    max_search_web_sec = step_dur_sec
                if step_dur_sec > 300.0:
                    search_web_eof_stalls += 1
                elif step_epoch is not None:
                    pending_search_web_ts = step_epoch
            compacted = "compaction" in low or "summariz" in low
            usage_candidates: list[dict[str, Any]] = []
            for u_key in ("usage", "token_usage", "usageMetadata", "metadata"):
                u_cand = obj.get(u_key)
                if isinstance(u_cand, dict):
                    usage_candidates.append(u_cand)
            if "input_tokens" in obj or "cache_read_tokens" in obj or "promptTokenCount" in obj:
                usage_candidates.append(obj)
            for u in usage_candidates:
                if isinstance(u, dict):
                    raw_prompt = int(u.get("promptTokenCount") or u.get("input_tokens") or u.get("prompt_tokens") or 0)
                    has_cache_field = "cachedContentTokenCount" in u or "cache_read_tokens" in u
                    cached_tok = int(u.get("cachedContentTokenCount") or u.get("cache_read_tokens") or 0)
                    # Note: in Gemini usageMetadata, promptTokenCount includes cachedContentTokenCount; avoid double-adding when promptTokenCount >= cachedContentTokenCount
                    if "promptTokenCount" in u and raw_prompt >= cached_tok:
                        tok = raw_prompt or int(u.get("totalTokenCount") or u.get("total_tokens") or 0)
                    else:
                        tok = (raw_prompt + cached_tok) or int(u.get("total_tokens") or u.get("totalTokenCount") or 0)
                    if tok > peak_tokens:
                        peak_tokens = tok
                        peak_step = cur_step
                    has_thinking_field = (
                        "thinking_tokens" in u
                        or "thoughtsTokenCount" in u
                        or "thought_tokens" in u
                    )
                    thinking_tok = int(
                        u.get("thinking_tokens")
                        if u.get("thinking_tokens") is not None
                        else (
                            u.get("thoughtsTokenCount")
                            if u.get("thoughtsTokenCount") is not None
                            else (u.get("thought_tokens") or 0)
                        )
                    )
                    out_tok = int(u.get("candidatesTokenCount") or u.get("output_tokens") or u.get("completion_tokens") or 0)
                    if (
                        saw_workspace_read_tool
                        and session_seen_hydrogen_medium
                        and not step_is_non_medium_model
                        and has_thinking_field
                        and thinking_tok == 0
                        and (raw_prompt > 0 or cached_tok > 0 or out_tok > 0)
                    ):
                        hydrogen_medium_zero_thinking_hits += 1
                    if raw_prompt > 0 or cached_tok > 0:
                        turn_gap_sec = inter_turn_tool_wait_sec
                        if (
                            step_epoch is not None
                            and prev_usage_epoch is not None
                            and step_epoch >= prev_usage_epoch
                            and (step_epoch - prev_usage_epoch) > turn_gap_sec
                        ):
                            turn_gap_sec = step_epoch - prev_usage_epoch
                        cache_zero_now = cached_tok == 0 and (not has_cache_field or u.get("cachedContentTokenCount", 0) == 0)
                        if (
                            not compacted
                            and turn_gap_sec >= 120.0
                            and cache_zero_now
                            and (prev_cached_tokens >= 4096 or (prev_prompt_tokens >= 4096 and raw_prompt >= 4096))
                        ):
                            long_wait_cache_ttl_drops += 1
                            if turn_gap_sec > max_ttl_drop_wait_sec:
                                max_ttl_drop_wait_sec = turn_gap_sec
                        elif not compacted and prev_cached_tokens >= 4096:
                            if cache_zero_now:
                                turn3_cache_drop_hits += 1
                            elif 0 < cached_tok < prev_cached_tokens:
                                cache_regression_hits += 1
                        elif (
                            not compacted
                            and usage_turn_index == 3
                            and cached_tok == 0
                            and prev_prompt_tokens >= 8192
                            and (raw_prompt - prev_prompt_tokens) >= 700
                        ):
                            turn3_cache_drop_hits += 1
                        prev_cached_tokens = cached_tok
                        prev_prompt_tokens = raw_prompt
                        if step_epoch is not None:
                            prev_usage_epoch = step_epoch
                        inter_turn_tool_wait_sec = 0.0
                        usage_turn_index += 1
                    break
            if step_had_workspace_read:
                saw_workspace_read_tool = True
    except OSError:
        pass

    return {
        "available": True,
        "conversation_id": conversation_id,
        "transcript_bytes": tp.stat().st_size if tp.is_file() else 0,
        "steps_observed": step_count,
        "peak_context_tokens": peak_tokens,
        "peak_token_step": peak_step,
        "malformed_tool_calls": malformed_calls,
        "http_503_retries": http_503_retries,
        "zero_quota_429_hits": zero_quota_429_hits,
        "hydrogen_entitlement_blocks": hydrogen_entitlement_blocks,
        "orchestrator_handoff_hits": orchestrator_handoff_hits,
        "tos_violation_403_hits": tos_violation_403_hits,
        "hydrogen_extra_leak_hits": hydrogen_extra_leak_hits,
        "hydrogen_medium_zero_thinking_hits": hydrogen_medium_zero_thinking_hits,
        "turn3_cache_drop_hits": turn3_cache_drop_hits,
        "cache_regression_hits": cache_regression_hits,
        "long_wait_cache_ttl_drops": long_wait_cache_ttl_drops,
        "max_ttl_drop_wait_sec": round(max_ttl_drop_wait_sec, 1),
        "search_web_eof_stalls": search_web_eof_stalls,
        "search_web_max_duration_sec": round(max_search_web_sec, 1),
        "search_web_max_parallel": max_parallel_search_web,
        "top_tools": dict(tool_counts.most_common(8)),
    }


def diagnose_session(
    repo: Path,
    *,
    conversation_id: str = "",
    task_id: str = "",
) -> dict[str, Any]:
    sroot = state_root(repo)
    conv_id = conversation_id.strip() or os.environ.get("HARNESS_CONVERSATION_ID", "").strip()
    if not conv_id:
        active_conv = sroot / "active-conversation.json"
        if active_conv.is_file():
            try:
                conv_id = str(read_json(active_conv).get("conversation_id") or "")
            except (OSError, ValueError, ValidationError):
                conv_id = ""

    plan: dict[str, Any] = {}
    if task_id:
        p_file = sroot / "tasks" / task_id / "plan.json"
        if p_file.is_file():
            try:
                plan = read_json(p_file)
            except (OSError, ValueError, ValidationError):
                plan = {}
    else:
        try:
            from mutation_guard import active_plan
            plan = active_plan(repo)
        except (ImportError, OSError, ValueError, ValidationError):
            plan = {}

    audit = _analyze_hook_audit(repo)
    transcript = _analyze_transcript(conv_id)

    findings: list[dict[str, Any]] = []
    denials = audit["denials_by_code"]
    if denials.get("DISCOVERY_ANCHOR_REQUIRED", 0) >= 2:
        findings.append({
            "code": "UNANCHORED_SEARCH_FRICTION",
            "severity": "MEDIUM",
            "evidence": f"{denials['DISCOVERY_ANCHOR_REQUIRED']} search/list calls blocked before discovery receipt.",
            "remedy": "Start new conversations with `python .agents/harness.py graph --feature <name> --json` or `task-context --file <path> --json`.",
        })
    if denials.get("BACKGROUND_TASK_LOG_POLLING_FORBIDDEN", 0) >= 1:
        findings.append({
            "code": "BACKGROUND_LOG_POLLING_ATTEMPT",
            "severity": "LOW",
            "evidence": f"{denials['BACKGROUND_TASK_LOG_POLLING_FORBIDDEN']} attempt(s) to read `.system_generated/tasks/*.log` intercepted.",
            "remedy": "Hook safely blocked partial log polling; yield turn with zero tool calls until background completion.",
        })
    if audit["max_consecutive_denials"] >= 3:
        findings.append({
            "code": "CONSECUTIVE_HOOK_DENIAL_STREAK",
            "severity": "HIGH",
            "evidence": f"Max consecutive hook denial streak = {audit['max_consecutive_denials']} (streaks: {audit['denial_streaks'][-2:]}).",
            "remedy": "Inspect the denied reason_code and query `python .agents/harness.py task status --next --brief --json` instead of retrying blocked tools.",
        })
    if len(audit["out_of_scope_reads"]) >= 4:
        findings.append({
            "code": "SCOPE_DRIFT_READ_SPRAWL",
            "severity": "MEDIUM",
            "evidence": f"{len(audit['out_of_scope_reads'])} source file reads occurred outside planned task scope.",
            "remedy": "Delegate broad exploration to `harness-scout-agent` on Flash or use `symbol read` on large files.",
        })
    if transcript.get("malformed_tool_calls", 0) > 0:
        findings.append({
            "code": "MALFORMED_EMPTY_TOOL_CALLS",
            "severity": "MEDIUM",
            "evidence": f"{transcript['malformed_tool_calls']} malformed/empty tool call error(s) detected in transcript.",
            "remedy": "Yield immediately with ZERO tool calls whenever background `unit tests` or subagents are still running.",
        })
    if int(plan.get("review_rounds") or 0) >= 2:
        findings.append({
            "code": "MULTI_ROUND_REVIEW_CHURN",
            "severity": "MEDIUM",
            "evidence": f"Task '{plan.get('task_id')}' required {plan.get('review_rounds')} review rounds (blocked: {plan.get('blocked_reviewers') or []}).",
            "remedy": "Use `risk-hybrid` preset so Round 2+ critical re-reviews escalate to the main frontier model automatically.",
        })
    if denials.get("ZOMBIE_SUBAGENT_SCHEDULE_WAKEUP_GUARD", 0) >= 1:
        findings.append({
            "code": "ZOMBIE_SUBAGENT_REACTIVE_WAKEUP",
            "severity": "HIGH",
            "evidence": f"{denials['ZOMBIE_SUBAGENT_SCHEDULE_WAKEUP_GUARD']} schedule wakeup call(s) intercepted (#199713).",
            "remedy": "Call `manage_subagents({'Action': 'kill_all'})` after every completed subagent wave or task to reap idle sessions.",
        })
    if denials.get("AGY_HEADLESS_LOOP_TOS_GUARD", 0) >= 1:
        findings.append({
            "code": "AGY_HEADLESS_LOOP_TOS_ATTEMPT",
            "severity": "HIGH",
            "evidence": f"{denials['AGY_HEADLESS_LOOP_TOS_GUARD']} `agy` / `antigravity` CLI subprocess or UI-injection command(s) blocked (#201582/#201491/#199748).",
            "remedy": "Never invoke `agy` as a subprocess from an AI agent (triggers automated Section 6 ToS 403 account suspension); validate rules via `python harness_cli.py selftest`.",
        })
    if denials.get("SEARCH_WEB_PARALLEL_CAP_REACHED", 0) >= 1:
        findings.append({
            "code": "SEARCH_WEB_PARALLEL_BURST_BLOCKED",
            "severity": "MEDIUM",
            "evidence": f"{denials['SEARCH_WEB_PARALLEL_CAP_REACHED']} excess parallel `search_web` call(s) intercepted before triggering #201621 17m hang.",
            "remedy": "Coalesce keywords into at most 1-2 `search_web` queries per turn after checking `.agents/project-context/`.",
        })
    if transcript.get("search_web_eof_stalls", 0) > 0 or float(transcript.get("search_web_max_duration_sec") or 0.0) > 300.0:
        findings.append({
            "code": "SEARCH_WEB_UPSTREAM_EOF_STALL",
            "severity": "HIGH",
            "evidence": (
                f"Upstream `search_web` timeout / `unexpected EOF` stall detected "
                f"(stalls={transcript.get('search_web_eof_stalls', 0)}, max_duration={transcript.get('search_web_max_duration_sec', 0.0)}s, "
                f"max_parallel_in_turn={transcript.get('search_web_max_parallel', 0)}) — upstream search service hang + client Parallel Barrier freeze (#201621), not a harness logic stall."
            ),
            "remedy": "Keep `search_web` to <=1-2 focused queries per turn (never 3+ parallel `search_web` calls or back-to-back waves) after exhausting `.agents/project-context/`.",
        })

    ls_health: dict[str, Any] = {"crash_loop_detected": False}
    try:
        from antigravity_runtime import inspect_language_server_acceptex_crashes
        ls_health = inspect_language_server_acceptex_crashes()
    except (ImportError, OSError, ValueError):
        ls_health = {"crash_loop_detected": False}
    if ls_health.get("crash_loop_detected"):
        findings.append({
            "code": "LANGUAGE_SERVER_ACCEPTEX_995_CRASH_LOOP",
            "severity": "HIGH",
            "evidence": (
                f"Detected Windows `language_server.exe` Exit Code 2 AcceptEx (Error 995) crash loop in `main.log` "
                f"(code2_crashes={ls_health.get('code2_crashes', 0)}, port_restarts={ls_health.get('port_restarts', 0)}, "
                f"zero_byte_crash_logs={ls_health.get('zero_byte_crash_logs', 0)}) (#200687/#199301/#200763)."
            ),
            "remedy": "Launch Antigravity on Windows 11 with `GOMEMLIMIT=8GiB` and `GOGC=200` (or `GOGC=off` paired with `GOMEMLIMIT=8GiB`), migrate stdio MCP servers to HTTP/SSE, and use consolidated `verify-steps`.",
        })
    pacer_info: dict[str, Any] = {"throttled_events": 0, "total_delay_ms": 0, "coalesced_parallel_calls": 0}
    pacer_file = repo / ".agents" / "cache" / "burst-pacer.json"
    if pacer_file.is_file():
        try:
            raw_p = read_json(pacer_file)
            if isinstance(raw_p, dict):
                pacer_info = {
                    "throttled_events": int(raw_p.get("throttled_events") or 0),
                    "total_delay_ms": int(raw_p.get("total_delay_ms") or 0),
                    "coalesced_parallel_calls": int(raw_p.get("coalesced_parallel_calls") or 0),
                }
        except (OSError, ValueError, ValidationError):
            pass

    if transcript.get("hydrogen_extra_leak_hits", 0) > 0:
        findings.append({
            "code": "HYDROGEN_EXTRA_ARGON_QUOTA_LEAK",
            "severity": "HIGH",
            "evidence": f"{transcript['hydrogen_extra_leak_hits']} reference(s) to `gemini-4-hydrogen-extra` / `xhigh` detected (#200467).",
            "remedy": "Switch Antigravity model selector from `Gemini 4 Hydrogen Extra` down to `Gemini 4 Hydrogen High` (1x) or `Carbon Medium` to stop silent 3x Argon weekly quota drain.",
        })
    quirk_1649_on = True
    try:
        from platform_quirks import is_quirk_enabled as _is_q1649
        quirk_1649_on = _is_q1649("1649", repo=repo)
    except ImportError:
        pass
    if quirk_1649_on and transcript.get("hydrogen_medium_zero_thinking_hits", 0) > 0:
        findings.append({
            "code": "HYDROGEN_MEDIUM_ZERO_THINKING_AFTER_TOOL",
            "severity": "HIGH",
            "evidence": (
                f"Detected {transcript['hydrogen_medium_zero_thinking_hits']} post-tool response(s) with `thinking_tokens=0` "
                "on `Gemini 4 Hydrogen (Medium)` after workspace file-read tool calls (#1649/#201731)."
            ),
            "remedy": (
                "Switch Antigravity model selector from `Gemini 4 Hydrogen (Medium)` to `Gemini 4 Hydrogen (High)` "
                "(same 1.00x quota cost, immune to #1649), pass `Model='flash'` on `harness-scout-agent`, and prefer "
                "`python .agents/harness.py symbol outline/read` or `task-context` over raw `read_file` calls."
            ),
        })
    if transcript.get("tos_violation_403_hits", 0) > 0:
        findings.append({
            "code": "HYDROGEN_403_TOS_FALSE_POSITIVE",
            "severity": "HIGH",
            "evidence": f"{transcript['tos_violation_403_hits']} false-positive 403 PERMISSION_DENIED (TOS_VIOLATION) event(s) detected (#200029/#199971).",
            "remedy": "Never use Antigravity's built-in Orchestrator mode; keep Harness HYDROGEN_ANTI_BURST_PACER enabled, batch parallel reads per turn, and file the official one-time Antigravity appeal if suspended.",
        })
    quirk_1623_on = True
    try:
        from platform_quirks import is_quirk_enabled
        quirk_1623_on = is_quirk_enabled("1623", repo=repo)
    except ImportError:
        pass
    if quirk_1623_on and transcript.get("long_wait_cache_ttl_drops", 0) > 0:
        findings.append({
            "code": "LONG_WAIT_KV_CACHE_TTL_EXPIRED",
            "severity": "HIGH",
            "evidence": (
                f"Detected {transcript.get('long_wait_cache_ttl_drops', 0)} parent KV prompt-cache TTL expiration drop(s) "
                f"(`cachedContentTokenCount=0`) after >=120s tool/subagent wait (max_wait={transcript.get('max_ttl_drop_wait_sec', 0.0)}s) (#1623/#171228)."
            ),
            "remedy": (
                "Keep implementation on warm-cache Lead (`INLINE_LEAD_DIRECT`), use `task quick-start` / `task ship` (`T0`/`T1` 0-reviewer fast path) "
                "and `--defer-gradle-to-final` with warm Gradle daemons (no routine `clean`), or route large multi-module tasks via `web-pack` (`Web-Relay`)."
            ),
        })
    if transcript.get("turn3_cache_drop_hits", 0) > 0 or transcript.get("cache_regression_hits", 0) >= 2:
        findings.append({
            "code": "GEMINI4_TURN3_CACHE_DROP_ANOMALY",
            "severity": "MEDIUM",
            "evidence": (
                f"Detected {transcript.get('turn3_cache_drop_hits', 0)} active cachedContentTokenCount=0 / Turn-3 +701 drop(s) "
                f"and {transcript.get('cache_regression_hits', 0)} multi-shard KV-cache regression(s) (#200026)."
            ),
            "remedy": "Prefer pure `agy` CLI (3.41% cache regression) over ACP IDE extensions (5.86%) on long Carbon sessions, keep Scout waves <=2 batched turns, or switch Scout to `safe-cache-project` (3.8 Flash = 0 cache drops).",
        })
    if pacer_info["throttled_events"] > 0:
        findings.append({
            "code": "HYDROGEN_BURST_PACER_SMOOTHED",
            "severity": "INFO",
            "evidence": (
                f"HYDROGEN_ANTI_BURST_PACER smoothed {pacer_info['throttled_events']} rapid sequential turn burst(s) "
                f"({pacer_info['total_delay_ms']}ms total human-cadence cooldown; {pacer_info['coalesced_parallel_calls']} same-turn parallel calls passed at 0ms)."
            ),
            "remedy": "Anti-ban burst pacing is operating normally (#200029/#199971 protection active).",
        })
    if transcript.get("hydrogen_entitlement_blocks", 0) > 0:
        findings.append({
            "code": "HYDROGEN_ROLLOUT_ENTITLEMENT_BLOCK",
            "severity": "HIGH",
            "evidence": f"{transcript['hydrogen_entitlement_blocks']} Gemini 4 Hydrogen entitlement/rollout block event(s) observed.",
            "remedy": "Switch project routing to `flash-argon-project` (or `flash-project`) until Gemini 4 Hydrogen finishes rolling out to this account.",
        })
    if transcript.get("orchestrator_handoff_hits", 0) > 0:
        findings.append({
            "code": "ORCHESTRATOR_DOUBLE_PLANNING_HAZARD",
            "severity": "MEDIUM",
            "evidence": f"{transcript['orchestrator_handoff_hits']} Antigravity Orchestrator internal handoff/effort event(s) observed.",
            "remedy": "Select explicit `Gemini 4 Carbon (Medium)` or `Gemini 4 Neon (High)` (or Argon/Claude 5.5) on the main chat instead of `Orchestrator` to avoid double-planning over Harness hooks.",
        })
    if transcript.get("zero_quota_429_hits", 0) > 0:
        findings.append({
            "code": "MANAGED_AGENT_ZERO_QUOTA_429",
            "severity": "HIGH",
            "evidence": f"{transcript['zero_quota_429_hits']} zero-quota HTTP 429 (`limit: 0`) error(s) on Argon/Carbon/Neon (#199769/#199770).",
            "remedy": "Switch reviewer/subagent routing to 100% Pure Gemini 4 Hydrogen (`hydrogen-dynamic-project`) or `flash-project` fallback.",
        })
    if transcript.get("http_503_retries", 0) > 0:
        findings.append({
            "code": "FLASH_503_CAPACITY_BACKOFF",
            "severity": "MEDIUM",
            "evidence": f"{transcript['http_503_retries']} silent Gemini 3.8 Flash HTTP 503 capacity retry event(s) detected (#198333).",
            "remedy": "Upgrade subagent routing to `hydrogen-dynamic-project` (`Gemini 4 Hydrogen`) and batch 4-8 `view_file` reads in a single turn.",
        })
    if not findings:
        findings.append({
            "code": "SESSION_HEALTHY",
            "severity": "INFO",
            "evidence": f"Evaluated {audit['total_events']} hook event(s) with {audit['deny_count']} denial(s) and zero stall streaks.",
            "remedy": "No workflow bottlenecks detected.",
        })

    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "task_id": str(plan.get("task_id") or task_id or ""),
        "task_status": str(plan.get("status") or "IDLE"),
        "hook_audit": audit,
        "burst_pacer": pacer_info,
        "language_server_health": ls_health,
        "transcript": transcript,
        "findings": findings,
    }


def export_scrubbed_bundle(repo: Path, report: dict[str, Any]) -> Path:
    from incident_reporter import _strict_zero_pii_text
    raw_json = json.dumps(report, ensure_ascii=False, indent=2)
    scrubbed_text = _strict_zero_pii_text(raw_json, repo=repo)
    scrubbed_obj = json.loads(scrubbed_text)
    inc_dir = state_root(repo) / "incidents"
    inc_dir.mkdir(parents=True, exist_ok=True)
    out_path = inc_dir / f"session-diagnosis-{int(time.time())}.json"
    atomic_write_json(out_path, scrubbed_obj)
    return out_path


def export_related_chat_bundle(
    repo: Path,
    *,
    conversation_id: str = "",
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Package the main Antigravity brain folder and all bound child subagent folders into a `.zip` archive
    by reading `.system_generated/subagents/*.json` metadata directly (zero raw transcript context reads).
    """
    from antigravity_runtime import candidate_brain_roots

    sroot = state_root(repo)
    conv_id = conversation_id.strip() or os.environ.get("HARNESS_CONVERSATION_ID", "").strip()
    if not conv_id:
        active_conv = sroot / "active-conversation.json"
        if active_conv.is_file():
            try:
                conv_id = str(read_json(active_conv).get("conversation_id") or "").strip()
            except (OSError, ValueError, ValidationError):
                conv_id = ""
    if not conv_id:
        raise ValidationError(
            "CHAT_BUNDLE_CONVERSATION_REQUIRED: Pass `--conversation-id <uuid>` (or run inside an active Antigravity conversation)."
        )

    main_dir: Path | None = None
    brain_root_found: Path | None = None
    for b_root in candidate_brain_roots():
        cand_dir = b_root / conv_id
        if cand_dir.is_dir():
            main_dir = cand_dir
            brain_root_found = b_root
            break
    if main_dir is None or brain_root_found is None:
        raise ValidationError(f"CHAT_BUNDLE_NOT_FOUND: Brain directory for conversation '{conv_id}' was not found.")

    related_ids: list[str] = [conv_id]
    sub_meta_dir = main_dir / ".system_generated" / "subagents"
    if sub_meta_dir.is_dir():
        for sf in sorted(sub_meta_dir.glob("*.json")):
            try:
                s_doc = json.loads(sf.read_text(encoding="utf-8", errors="replace"))
                cid_sub = str(s_doc.get("conversationId") or sf.stem).strip()
            except ValueError:
                cid_sub = sf.stem.strip()
            if cid_sub and cid_sub not in related_ids and (brain_root_found / cid_sub).is_dir():
                related_ids.append(cid_sub)

    short_id = conv_id.split("-", 1)[0]
    archive_prefix = f"chat-{short_id}-all-related"
    if out_path is not None:
        target_zip = Path(out_path).expanduser().resolve()
    else:
        dl_dir = Path.home() / "Downloads"
        base_out = dl_dir if dl_dir.is_dir() else (state_root(repo) / "incidents")
        base_out.mkdir(parents=True, exist_ok=True)
        target_zip = (base_out / f"{archive_prefix}.zip").resolve()

    target_zip.parent.mkdir(parents=True, exist_ok=True)
    entries_packed = 0
    with zipfile.ZipFile(target_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r_id in related_ids:
            src_folder = brain_root_found / r_id
            if not src_folder.is_dir():
                continue
            for root_d, dirs_d, files_d in os.walk(src_folder):
                dirs_d.sort()
                for fn in sorted(files_d):
                    fp = Path(root_d) / fn
                    if fp.resolve() == target_zip:
                        continue
                    rel_in_conv = fp.relative_to(src_folder).as_posix()
                    arcname = f"{archive_prefix}/{r_id}/{rel_in_conv}"
                    zf.write(fp, arcname)
                    entries_packed += 1

    return {
        "bundle_path": str(target_zip),
        "main_conversation_id": conv_id,
        "subagent_conversation_ids": related_ids[1:],
        "conversations_packed": len(related_ids),
        "entries_packed": entries_packed,
        "size_bytes": target_zip.stat().st_size if target_zip.is_file() else 0,
    }


def capture_auto_stall_summary(repo: Path, task_id: str = "") -> str:
    """Return a concise 1-line root-cause hint when consecutive hook denials or review caps occur."""
    try:
        diag = diagnose_session(repo, task_id=task_id)
        high = [f for f in diag["findings"] if f["severity"] in {"HIGH", "MEDIUM"}]
        if not high:
            return ""
        top = high[0]
        return f"[DIAGNOSE] {top['code']}: {top['evidence']} Remedy: {top['remedy']}"
    except (OSError, ValueError, KeyError, ValidationError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("HARNESS_REPO") or Path(__file__).resolve().parents[2]))
    parser.add_argument("--conversation-id", dest="conversation_id", default="")
    parser.add_argument("--task-id", "--task", dest="task_id", default="")
    parser.add_argument("--export-bundle", action="store_true", help="Write Zero-PII scrubbed JSON bundle under .agents/state/incidents/")
    parser.add_argument("--export-chat-bundle", action="store_true", help="Package main conversation and all bound subagent brain folders into a .zip archive")
    parser.add_argument("--out", dest="out_path", type=Path, default=None, help="Optional destination .zip path for --export-chat-bundle")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    try:
        report = diagnose_session(repo, conversation_id=args.conversation_id, task_id=args.task_id)
        if args.export_bundle:
            bundle_path = export_scrubbed_bundle(repo, report)
            report["exported_bundle"] = str(bundle_path)
        if args.export_chat_bundle:
            report["chat_bundle"] = export_related_chat_bundle(
                repo, conversation_id=args.conversation_id, out_path=args.out_path
            )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"# Session Forensics — Task `{report['task_id'] or 'IDLE'}` ({report['task_status']})")
            ha = report["hook_audit"]
            print(f"- Hook Events: {ha['total_events']} (allow={ha['allow_count']}, deny={ha['deny_count']}, max_streak={ha['max_consecutive_denials']})")
            tr = report["transcript"]
            if tr.get("available"):
                print(f"- Transcript: ~{tr['steps_observed']} steps, peak ~{tr['peak_context_tokens']:,} tokens, malformed_calls={tr['malformed_tool_calls']}")
            print("- Findings:")
            for f in report["findings"]:
                print(f"  * [{f['severity']}] {f['code']}: {f['evidence']} -> {f['remedy']}")
            if report.get("exported_bundle"):
                print(f"- Scrubbed Zero-PII Bundle: {report['exported_bundle']}")
            if report.get("chat_bundle"):
                cb = report["chat_bundle"]
                print(f"- Related Chat Archive: {cb['bundle_path']} ({cb['conversations_packed']} conversations, {cb['entries_packed']} files)")
        return 0
    except (OSError, ValueError, ValidationError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
