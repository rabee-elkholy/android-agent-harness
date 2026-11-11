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
        from antigravity_runtime import resolve_transcript
        cand = resolve_transcript(conversation_id)
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
    tool_counts: Counter[str] = Counter()

    try:
        lines = tp.read_text(encoding="utf-8", errors="replace").splitlines()[-800:]
        for idx, ln in enumerate(lines, start=1):
            low = ln.lower()
            if "malformed function call" in low or "function call is empty" in low:
                malformed_calls += 1
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
            t_name = str(obj.get("tool_name") or ((obj.get("toolCall") or {}).get("name") if isinstance(obj.get("toolCall"), dict) else "") or "")
            if t_name:
                tool_counts[t_name] += 1
            for u_key in ("usage", "token_usage", "usageMetadata", "metadata"):
                u = obj.get(u_key)
                if isinstance(u, dict):
                    tok = (
                        int(u.get("input_tokens") or u.get("promptTokenCount") or u.get("prompt_tokens") or 0)
                        + int(u.get("cache_read_tokens") or u.get("cachedContentTokenCount") or 0)
                    ) or int(u.get("total_tokens") or u.get("totalTokenCount") or 0)
                    if tok > peak_tokens:
                        peak_tokens = tok
                        peak_step = cur_step
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
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    try:
        report = diagnose_session(repo, conversation_id=args.conversation_id, task_id=args.task_id)
        if args.export_bundle:
            bundle_path = export_scrubbed_bundle(repo, report)
            report["exported_bundle"] = str(bundle_path)
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
        return 0
    except (OSError, ValueError, ValidationError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
