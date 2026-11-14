#!/usr/bin/env python3
"""Interactive Execution Mode Selector & Tamper-Evident State Engine.

Manages per-task and per-project execution mode routing between:
- `normal` (100% local Antigravity execution with Hydrogen/Carbon orchestration)
- `web`    (Manual Web-Relay clipboard pack/apply workflow via `gemini.google.com`)

Supports all 4 canonical developer choices (`normal-task`, `normal-project`,
`web-task`, `web-project`) plus `ask-every-task` reset, with strict precedence:
  1. Live Task Override (`.agents/state/tasks/<task_id>/execution-mode.json`)
  2. Pending Pre-Draft Single-Task Choice (`.agents/state/pending-task-execution-mode.json`)
  3. Project-Wide Default (`.agents/state/execution-mode.json`)
  4. Unset (`selection_required = True` at the start of a new implementation task)

Zero external dependencies (Python 3.10+ stdlib only).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import (  # noqa: E402
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    configure_utf8_output,
    read_json,
    redact,
    state_root,
    task_dir,
    utc_now,
    validate_id,
)
from evidence_store import StateLock  # noqa: E402

SCHEMA_VERSION = 1
PENDING_CHOICE_TTL_SECONDS = 6 * 3600
TERMINAL_TASK_STATES = frozenset({"DELIVERED", "CANCELLED"})
_MODE_THREAD_LOCK = threading.RLock()
CONFLICT_TASK_KINDS = frozenset({"CONFLICT", "FIX_CONFLICT", "MERGE"})
_CONFLICT_MARKER_RE = re.compile(r"^(?:<{7}\s|={7}\s*$|>{7}\s)", re.MULTILINE)
AUTO_WEB_FILE_THRESHOLD = 12
AUTO_CRITICAL_SURFACES = frozenset({"AUTH", "BILLING", "CRYPTO", "SECURITY", "SENSITIVE_DATA", "MANIFEST_PERMISSION"})

EXECUTION_MODE_CHOICES: dict[str, dict[str, str]] = {
    "auto-project": {
        "mode": "auto",
        "scope": "project",
        "label": "Smart Auto — always for this project (Normal for small tasks, Web for large/complex)",
        "label_en": "Smart Auto — always for this project (Normal for small tasks, Web for large/complex)",
        "description": "Save Smart Auto routing project-wide: small single-module tasks (<12 files) run locally in Antigravity; large (12+ files), multi-module, T5 critical, or 2-Strike tasks route to Gemini Web.",
    },
    "auto-task": {
        "mode": "auto",
        "scope": "task",
        "label": "Smart Auto — this task only (route automatically by task size & complexity)",
        "label_en": "Smart Auto — this task only (route automatically by task size & complexity)",
        "description": "Route this task automatically between Normal mode and Web-Relay based on file count, modules, risk tier, and handoff state.",
    },
    "normal-task": {
        "mode": "normal",
        "scope": "task",
        "label": "Normal mode — this task only (run locally in Antigravity)",
        "label_en": "Normal mode — this task only (run locally in Antigravity)",
        "description": "Run planning, coding, and verification locally inside Antigravity for this task only; ask again on the next new task.",
    },
    "normal-project": {
        "mode": "normal",
        "scope": "project",
        "label": "Normal mode — always for this project (run locally in Antigravity)",
        "label_en": "Normal mode — always for this project (run locally in Antigravity)",
        "description": "Save local Antigravity execution as the project default and stop asking on future tasks.",
    },
    "web-task": {
        "mode": "web",
        "scope": "task",
        "label": "Web mode — this task only (copy Context Pack for Gemini Web to save quota)",
        "label_en": "Web mode — this task only (copy Context Pack for Gemini Web to save quota)",
        "description": "Scope files locally and build a Clipboard Context Pack via `web-pack` for Gemini Web on this task only.",
    },
    "web-project": {
        "mode": "web",
        "scope": "project",
        "label": "Web mode — always for this project (use Gemini Web by default)",
        "label_en": "Web mode — always for this project (use Gemini Web by default)",
        "description": "Save Manual Web-Relay mode as the project default and stop asking on future tasks.",
    },
    "ask-every-task": {
        "mode": "unset",
        "scope": "reset",
        "label": "Ask on every new task (clear project default)",
        "label_en": "Ask on every new task (clear project default)",
        "description": "Clear any saved project default so the harness asks at the start of each new task.",
    },
}

_CHOICE_ALIASES: dict[str, str] = {
    "normal-always": "normal-project",
    "antigravity-project": "normal-project",
    "local-project": "normal-project",
    "antigravity-always": "normal-project",
    "antigravity-task": "normal-task",
    "local-task": "normal-task",
    "web-always": "web-project",
    "web-relay-project": "web-project",
    "web-relay-always": "web-project",
    "gemini-web-project": "web-project",
    "web-relay-task": "web-task",
    "gemini-web-task": "web-task",
    "auto": "auto-project",
    "smart": "auto-project",
    "smart-auto": "auto-project",
    "auto-always": "auto-project",
    "smart-project": "auto-project",
    "smart-task": "auto-task",
    "reset": "ask-every-task",
    "unset": "ask-every-task",
    "clear": "ask-every-task",
    "ask": "ask-every-task",
}


def project_mode_file(repo: Path) -> Path:
    return state_root(repo) / "execution-mode.json"


def pending_task_mode_file(repo: Path) -> Path:
    return state_root(repo) / "pending-task-execution-mode.json"


def task_mode_file(repo: Path, task_id: str) -> Path:
    return task_dir(repo, task_id) / "execution-mode.json"


def _compute_record_sha(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "record_sha256"}
    return canonical_sha256(body)


def _sign_record(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.pop("record_sha256", None)
    out["record_sha256"] = _compute_record_sha(out)
    return out


def _read_verified_record(path: Path, *, strict: bool = False) -> tuple[dict[str, Any] | None, str]:
    if not path.is_file():
        return None, ""
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return None, ""
    except (OSError, ValueError, ValidationError) as exc:
        if not path.exists() or "No such file or directory" in str(exc):
            return None, ""
        msg = f"EXECUTION_MODE_CORRUPTED: Failed reading {path.name}: {exc}"
        if strict:
            raise ValidationError(msg) from exc
        return None, msg
    if not isinstance(raw, dict):
        msg = f"EXECUTION_MODE_CORRUPTED: {path.name} is not a JSON object."
        if strict:
            raise ValidationError(msg)
        return None, msg
    recorded_sha = str(raw.get("record_sha256") or "").strip()
    expected_sha = _compute_record_sha(raw)
    if not recorded_sha or recorded_sha != expected_sha:
        msg = f"EXECUTION_MODE_TAMPERED: record_sha256 mismatch in {path.name}."
        if strict:
            raise ValidationError(msg)
        return None, msg
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in {"normal", "web", "auto"}:
        msg = f"EXECUTION_MODE_INVALID: Unsupported mode '{mode}' in {path.name}."
        if strict:
            raise ValidationError(msg)
        return None, msg
    return raw, ""


def _parse_iso_epoch(ts: str) -> float | None:
    txt = str(ts or "").strip()
    if not txt:
        return None
    try:
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _is_pending_expired(record: dict[str, Any]) -> bool:
    epoch = record.get("updated_at_epoch")
    if isinstance(epoch, (int, float)) and epoch > 0:
        return (time.time() - float(epoch)) > PENDING_CHOICE_TTL_SECONDS
    parsed = _parse_iso_epoch(str(record.get("updated_at") or ""))
    if parsed is not None:
        return (time.time() - parsed) > PENDING_CHOICE_TTL_SECONDS
    return False


def normalize_choice(
    choice: str | None = None,
    mode: str | None = None,
    scope: str | None = None,
) -> tuple[str, str, str]:
    raw_choice = str(choice or "").strip().lower()
    raw_mode = str(mode or "").strip().lower()
    raw_scope = str(scope or "").strip().lower()

    if raw_choice in _CHOICE_ALIASES:
        raw_choice = _CHOICE_ALIASES[raw_choice]

    if raw_choice in EXECUTION_MODE_CHOICES:
        meta = EXECUTION_MODE_CHOICES[raw_choice]
        return raw_choice, meta["mode"], meta["scope"]

    if raw_choice in {"normal", "antigravity", "local"} and not raw_mode:
        raw_mode = "normal"
        raw_choice = ""
    elif raw_choice in {"web", "web-relay", "gemini-web"} and not raw_mode:
        raw_mode = "web"
        raw_choice = ""
    elif raw_choice in {"auto", "smart", "smart-auto"} and not raw_mode:
        raw_mode = "auto"
        raw_choice = ""

    if raw_choice:
        valid = ", ".join(EXECUTION_MODE_CHOICES.keys())
        raise ValidationError(
            f"INVALID_EXECUTION_MODE_CHOICE: Unknown choice '{choice}'. Valid choices: {valid}."
        )

    if raw_mode in {"unset", "reset", "clear", "ask"} or raw_scope == "reset":
        return "ask-every-task", "unset", "reset"

    if raw_mode in {"antigravity", "local"}:
        raw_mode = "normal"
    elif raw_mode in {"web-relay", "gemini-web"}:
        raw_mode = "web"
    elif raw_mode in {"smart", "smart-auto"}:
        raw_mode = "auto"

    if raw_mode not in {"normal", "web", "auto"}:
        valid = ", ".join(EXECUTION_MODE_CHOICES.keys())
        raise ValidationError(
            f"MISSING_EXECUTION_MODE_CHOICE: Provide `--choice <{valid}>` (or `--mode <auto|normal|web> --scope <task|project>`)."
        )

    if not raw_scope:
        raw_scope = "task"
    if raw_scope in {"always", "repo", "global"}:
        raw_scope = "project"
    elif raw_scope in {"once", "single", "current"}:
        raw_scope = "task"

    if raw_scope not in {"task", "project"}:
        raise ValidationError(
            f"INVALID_EXECUTION_MODE_SCOPE: Unknown scope '{scope}'. Expected `task`, `project`, or `reset`."
        )

    composed = f"{raw_mode}-{raw_scope}"
    meta = EXECUTION_MODE_CHOICES[composed]
    return composed, meta["mode"], meta["scope"]


def has_conflict_signals(
    repo: Path,
    plan: dict[str, Any] | None = None,
    candidate_files: list[str] | None = None,
) -> tuple[bool, str]:
    """Read-only check for Git merge/rebase conflict tasks or conflict markers in scoped files."""
    if isinstance(plan, dict):
        kind = str(plan.get("task_kind") or plan.get("kind") or "").strip().upper()
        if kind in CONFLICT_TASK_KINDS:
            return True, f"task_kind={kind}"

    files_to_scan: list[str] = []
    if candidate_files:
        files_to_scan.extend(str(f) for f in candidate_files if str(f).strip())
    elif isinstance(plan, dict):
        files_to_scan.extend(str(f) for f in (plan.get("expected_files") or []) if str(f).strip())

    for rel in files_to_scan[:250]:
        clean = rel.replace("\\", "/").lstrip("/")
        full = (repo / clean).resolve()
        try:
            full.relative_to(repo.resolve())
        except ValueError:
            continue
        if not full.is_file():
            continue
        try:
            if full.stat().st_size > 512 * 1024:
                continue
            txt = full.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "<<<<<<< " in txt and "=======" in txt and ">>>>>>> " in txt and _CONFLICT_MARKER_RE.search(txt):
            return True, f"conflict_markers_in={clean}"
    return False, ""


def build_execution_mode_prompt(repo: Path, task_id: str = "") -> dict[str, Any]:
    tid_flag = f"--task-id {task_id} " if str(task_id or "").strip() else ""
    options = []
    for cid in ("auto-project", "normal-task", "normal-project", "web-task", "web-project"):
        meta = EXECUTION_MODE_CHOICES[cid]
        options.append({
            "id": cid,
            "mode": meta["mode"],
            "scope": meta["scope"],
            "label": meta["label"],
            "label_en": meta["label_en"],
            "command": (
                f'python .agents/harness.py execution-mode set {tid_flag}'
                f'--choice {cid} --source conversation --proof-reference "<developer answer>"'
            ),
        })
    return {
        "code": "SELECT_EXECUTION_MODE",
        "tool": "ask_question",
        "blocking": True,
        "question": "How would you like to run this task?",
        "question_en": "How would you like to run this task?",
        "options": options,
        "command_template": (
            f'python .agents/harness.py execution-mode set {tid_flag}'
            f'--choice <auto-project|normal-task|normal-project|web-task|web-project> '
            f'--source conversation --proof-reference "<exact developer answer>"'
        ),
        "reset_command_template": (
            'python .agents/harness.py execution-mode set --choice ask-every-task '
            '--source conversation --proof-reference "<exact developer answer>"'
        ),
        "instructions": (
            "Invoke `ask_question` IMMEDIATELY (zero pre-tool prose), translating the question and 5 options naturally "
            "into the developer's active conversation language (in RTL languages, start every line and option with a word "
            "in that language and wrap CLI/English terms in backticks). Once answered, run "
            '`python .agents/harness.py execution-mode set ... --source conversation --proof-reference "<answer>"`: '
            "if `auto-*` or `normal-*` was chosen, proceed with `task draft` (Smart Auto promotes heavy/complex plans to Web automatically); if `web-*` was chosen, scope target files with "
            '`graph`/`task-context` and run `python .agents/harness.py web-pack --files <csv> --prompt "<goal>"` directly.'
        ),
    }


def _resolve_target_task_and_plan(
    repo: Path,
    task_id: str | None = None,
    plan: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    if isinstance(plan, dict) and plan.get("task_id"):
        return str(plan["task_id"]).strip(), plan
    req_tid = str(task_id or "").strip()
    if req_tid:
        p_path = task_dir(repo, req_tid) / "plan.json"
        if p_path.is_file():
            try:
                loaded = read_json(p_path)
                if isinstance(loaded, dict):
                    return req_tid, loaded
            except (OSError, ValueError, ValidationError):
                pass
        return req_tid, None
    try:
        from mutation_guard import active_plan
        live = active_plan(repo)
        if isinstance(live, dict) and live.get("task_id"):
            return str(live["task_id"]).strip(), live
    except (ImportError, OSError, ValueError, ValidationError):
        return "", None
    return "", None


def evaluate_smart_auto_routing(
    repo: Path,
    tid: str,
    plan: dict[str, Any] | None,
    candidate_files: list[str] | None = None,
) -> tuple[str, str, bool]:
    """Deterministically resolve Smart Auto (`auto-*`) into `('normal' | 'web', trigger_code, conflict_override)`."""
    is_conflict, conflict_sig = has_conflict_signals(repo, plan=plan, candidate_files=candidate_files)
    if is_conflict:
        return ("normal", f"CONFLICT_AUTO_LOCAL_OVERRIDE ({conflict_sig})", True)

    plan_status = str((plan or {}).get("status") or "").strip().upper()
    is_live = bool(tid and isinstance(plan, dict) and plan_status and plan_status not in TERMINAL_TASK_STATES)
    if is_live and isinstance(plan, dict):
        # 1. Unresolved 2-Strike Worker handoff capsule -> offload to Gemini Web Carbon!
        hf_f = task_dir(repo, tid) / "worker-handoff.json"
        if hf_f.is_file():
            try:
                hf_doc = read_json(hf_f)
                if isinstance(hf_doc, dict) and str(hf_doc.get("status") or "").upper() not in {"RESOLVED", "CLEARED"}:
                    return ("web", "AUTO_WEB_2_STRIKE_HANDOFF", False)
            except (OSError, ValueError, ValidationError):
                pass
        # 2. If task already has active Web-Relay state (pack or receipt), keep it on `web` cleanly
        tdir = task_dir(repo, tid)
        if (tdir / "web-relay-receipt.json").is_file() or (tdir / "latest-web-pack.json").is_file():
            t_ptr = tdir / "latest-web-pack.json"
            superseded = False
            if t_ptr.is_file():
                try:
                    superseded = bool((read_json(t_ptr) or {}).get("superseded_by_normal_mode"))
                except (OSError, ValueError, ValidationError):
                    superseded = False
            if not superseded:
                return ("web", "AUTO_WEB_EXISTING_PACK_CONTINUITY", False)
        # 3. Critical T5 surfaces (`AUTH`, `BILLING`, `CRYPTO`, `SECURITY`, `SENSITIVE_DATA`, `MANIFEST_PERMISSION`)
        surfs = {str(s).strip().upper() for s in (plan.get("expected_surfaces") or []) if str(s).strip()}
        ra_tier = str((plan.get("readiness_assessment") or {}).get("risk_tier") or "").strip().upper()
        if (surfs & AUTO_CRITICAL_SURFACES) or ra_tier == "T5_CRITICAL":
            return ("web", "AUTO_WEB_CRITICAL_T5_SURFACE", False)
        # 4. Multi-phase (`p1 -> p2`) or multi-module (`>= 2` non-root modules)
        phases = [p for p in (plan.get("phases") or []) if isinstance(p, dict)]
        mods = [str(m).strip() for m in (plan.get("expected_modules") or []) if str(m).strip() and str(m).strip() != ":"]
        if len(phases) >= 2 or len(set(mods)) >= 2:
            return ("web", "AUTO_WEB_MULTI_MODULE_OR_PHASE", False)
        # 5. Large file scope (`>= 12` planned files)
        exp_files = [str(f).strip() for f in (plan.get("expected_files") or []) if str(f).strip()]
        if len(exp_files) >= AUTO_WEB_FILE_THRESHOLD:
            return ("web", f"AUTO_WEB_LARGE_SCOPE_{len(exp_files)}_FILES", False)
        return ("normal", f"AUTO_NORMAL_COMPACT_SCOPE_{len(exp_files)}_FILES", False)

    # Pre-plan / IDLE evaluation
    cands = [str(f).strip() for f in (candidate_files or []) if str(f).strip()]
    if len(cands) >= AUTO_WEB_FILE_THRESHOLD:
        return ("web", f"AUTO_WEB_LARGE_CANDIDATE_SCOPE_{len(cands)}_FILES", False)
    return ("normal", "AUTO_IDLE_EVALUATES_ON_PLAN", False)


def resolve_effective_execution_mode(
    repo: Path,
    task_id: str | None = None,
    plan: dict[str, Any] | None = None,
    *,
    candidate_files: list[str] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Pure read-only resolution of effective execution mode (zero disk writes)."""
    with _MODE_THREAD_LOCK:
        return _resolve_effective_execution_mode_unlocked(
            repo,
            task_id=task_id,
            plan=plan,
            candidate_files=candidate_files,
            strict=strict,
        )


def _resolve_effective_execution_mode_unlocked(
    repo: Path,
    task_id: str | None = None,
    plan: dict[str, Any] | None = None,
    *,
    candidate_files: list[str] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    repo = Path(repo).resolve()
    tid, resolved_plan = _resolve_target_task_and_plan(repo, task_id=task_id, plan=plan)
    plan_status = str((resolved_plan or {}).get("status") or "").strip().upper()
    is_live_task = bool(tid and resolved_plan and plan_status not in TERMINAL_TASK_STATES)

    integrity_errors: list[str] = []

    proj_rec, proj_err = _read_verified_record(project_mode_file(repo), strict=strict)
    if proj_err:
        integrity_errors.append(proj_err)
    proj_mode = str((proj_rec or {}).get("mode") or "")
    proj_choice = str((proj_rec or {}).get("choice") or "")

    # 1. Task-scoped override on a live task (highest precedence)
    if is_live_task:
        t_rec, t_err = _read_verified_record(task_mode_file(repo, tid), strict=strict)
        if t_err:
            integrity_errors.append(t_err)
        if t_rec is not None:
            cfg_m = str(t_rec.get("mode") or "normal")
            ch = str(t_rec.get("choice") or f"{cfg_m}-task")
            auto_trig = ""
            conf_over = False
            if cfg_m == "auto":
                eff_m, auto_trig, conf_over = evaluate_smart_auto_routing(repo, tid, resolved_plan, candidate_files)
            else:
                eff_m = cfg_m
            return {
                "mode": eff_m,
                "configured_mode": cfg_m,
                "auto_routed": (cfg_m == "auto"),
                "auto_route_trigger": auto_trig,
                "choice": ch,
                "effective_scope": "task",
                "selection_required": False,
                "task_id": tid,
                "task_status": plan_status,
                "project_default": proj_mode or None,
                "project_choice": proj_choice or None,
                "conflict_auto_local_override": conf_over,
                "conflict_signal": (auto_trig if conf_over else ""),
                "integrity_error": "; ".join(integrity_errors),
                "updated_at": str(t_rec.get("updated_at") or ""),
                "reason": (f"Smart Auto (`{ch}`) routed task `{tid}` to `{eff_m}` ({auto_trig})." if cfg_m == "auto" else f"Task-scoped execution mode `{ch}` (`{eff_m}`) active for task `{tid}`."),
                "prompt_contract": None,
            }

    # 2. Pending pre-draft single-task choice (when starting a new task or matching intended_task_id)
    pend_rec, pend_err = _read_verified_record(pending_task_mode_file(repo), strict=strict)
    if pend_err:
        integrity_errors.append(pend_err)
    if pend_rec is not None and not _is_pending_expired(pend_rec):
        intended_tid = str(pend_rec.get("intended_task_id") or "").strip()
        if (not is_live_task and (not tid or not intended_tid or intended_tid == tid)) or (
            tid and intended_tid == tid
        ):
            cfg_pm = str(pend_rec.get("mode") or "normal")
            ch = str(pend_rec.get("choice") or f"{cfg_pm}-task")
            auto_ptrig = ""
            p_conf = False
            if cfg_pm == "auto":
                eff_pm, auto_ptrig, p_conf = evaluate_smart_auto_routing(repo, tid or intended_tid, resolved_plan, candidate_files)
            else:
                eff_pm = cfg_pm
            return {
                "mode": eff_pm,
                "configured_mode": cfg_pm,
                "auto_routed": (cfg_pm == "auto"),
                "auto_route_trigger": auto_ptrig,
                "choice": ch,
                "effective_scope": "pending_task",
                "selection_required": False,
                "task_id": tid or intended_tid,
                "task_status": plan_status,
                "project_default": proj_mode or None,
                "project_choice": proj_choice or None,
                "conflict_auto_local_override": False,
                "conflict_signal": "",
                "integrity_error": "; ".join(integrity_errors),
                "updated_at": str(pend_rec.get("updated_at") or ""),
                "reason": f"Pending single-task choice `{ch}` (`{eff_pm}`) ready to bind to upcoming task.",
                "prompt_contract": None,
            }

    # 3. Project-wide default (`auto-project`, `normal-project`, or `web-project` + CONFLICT safety override)
    if proj_rec is not None:
        m = str(proj_rec.get("mode") or "normal")
        ch = str(proj_rec.get("choice") or f"{m}-project")
        if m == "auto":
            eff_auto_m, auto_trig_p, auto_conf = evaluate_smart_auto_routing(repo, tid, resolved_plan, candidate_files)
            return {
                "mode": eff_auto_m,
                "configured_mode": "auto",
                "auto_routed": True,
                "auto_route_trigger": auto_trig_p,
                "choice": ch,
                "effective_scope": "project",
                "selection_required": False,
                "task_id": tid,
                "task_status": plan_status,
                "project_default": "auto",
                "project_choice": ch,
                "conflict_auto_local_override": auto_conf,
                "conflict_signal": (auto_trig_p if auto_conf else ""),
                "integrity_error": "; ".join(integrity_errors),
                "updated_at": str(proj_rec.get("updated_at") or ""),
                "reason": f"Smart Auto (`{ch}`) resolved `{eff_auto_m}` mode ({auto_trig_p}).",
                "prompt_contract": None,
            }
        if m == "web":
            is_conflict, conflict_sig = has_conflict_signals(repo, plan=resolved_plan, candidate_files=candidate_files)
            if is_conflict:
                return {
                    "mode": "normal",
                    "configured_mode": "web",
                    "choice": ch,
                    "effective_scope": "project",
                    "selection_required": False,
                    "task_id": tid,
                    "task_status": plan_status,
                    "project_default": proj_mode,
                    "project_choice": proj_choice,
                    "conflict_auto_local_override": True,
                    "conflict_signal": conflict_sig,
                    "integrity_error": "; ".join(integrity_errors),
                    "updated_at": str(proj_rec.get("updated_at") or ""),
                    "reason": (
                        f"CONFLICT_AUTO_LOCAL_OVERRIDE ({conflict_sig}): Git conflict resolution runs locally in "
                        "Antigravity while keeping `web-project` intact for subsequent tasks."
                    ),
                    "prompt_contract": None,
                }
        return {
            "mode": m,
            "configured_mode": m,
            "choice": ch,
            "effective_scope": "project",
            "selection_required": False,
            "task_id": tid,
            "task_status": plan_status,
            "project_default": proj_mode,
            "project_choice": proj_choice,
            "conflict_auto_local_override": False,
            "conflict_signal": "",
            "integrity_error": "; ".join(integrity_errors),
            "updated_at": str(proj_rec.get("updated_at") or ""),
            "reason": f"Project-wide execution mode `{ch}` (`{m}`) active.",
            "prompt_contract": None,
        }

    # 4. If an in-progress live task already exists on disk (e.g., created in CLI/legacy chat before selector),
    # treat its implicit mode cleanly without blocking mid-task resume, UNLESS no live task exists yet.
    if is_live_task:
        has_web_state = (
            (task_dir(repo, tid) / "web-relay-receipt.json").is_file()
            or (task_dir(repo, tid) / "latest-web-pack.json").is_file()
        )
        inferred = "web" if has_web_state else "normal"
        return {
            "mode": inferred,
            "configured_mode": "unset",
            "choice": "unset",
            "effective_scope": "inferred_active_task",
            "selection_required": False,
            "task_id": tid,
            "task_status": plan_status,
            "project_default": None,
            "project_choice": None,
            "conflict_auto_local_override": False,
            "conflict_signal": "",
            "integrity_error": "; ".join(integrity_errors),
            "updated_at": "",
            "reason": f"Active in-progress task `{tid}` ({plan_status}) continues on `{inferred}` mode without re-prompting.",
            "prompt_contract": None,
        }

    # 5. Unset on IDLE / pre-draft new task -> prompt required before starting a new task
    return {
        "mode": "unset",
        "configured_mode": "unset",
        "choice": "unset",
        "effective_scope": "unset",
        "selection_required": True,
        "task_id": tid,
        "task_status": plan_status,
        "project_default": None,
        "project_choice": None,
        "conflict_auto_local_override": False,
        "conflict_signal": "",
        "integrity_error": "; ".join(integrity_errors),
        "updated_at": "",
        "reason": "No execution mode selected yet; ask the developer via `ask_question` before starting a new implementation task.",
        "prompt_contract": build_execution_mode_prompt(repo, task_id=tid),
    }


def _supersede_unapplied_web_pack_on_normal_switch(repo: Path, tid: str) -> list[str]:
    """Mark unapplied web-pack pointers superseded when switching mid-task from `web` to `normal`."""
    superseded_ids: list[str] = []
    t_ptr = task_dir(repo, tid) / "latest-web-pack.json"
    if t_ptr.is_file():
        try:
            ptr_data = read_json(t_ptr)
            if isinstance(ptr_data, dict):
                pid = str(ptr_data.get("pack_id") or "").strip()
                pack_file = state_root(repo) / "web-relay" / "packs" / f"{pid}.json"
                is_applied = False
                if pid and pack_file.is_file():
                    p_rec = read_json(pack_file)
                    is_applied = bool(isinstance(p_rec, dict) and p_rec.get("applied"))
                if not is_applied and not ptr_data.get("superseded_by_normal_mode"):
                    ptr_data["superseded_by_normal_mode"] = True
                    ptr_data["superseded_at"] = utc_now()
                    atomic_write_json(t_ptr, ptr_data)
                    if pid:
                        superseded_ids.append(pid)
        except (OSError, ValueError, ValidationError):
            pass

    g_ptr = state_root(repo) / "web-relay" / "latest-pack.json"
    if g_ptr.is_file():
        try:
            g_data = read_json(g_ptr)
            if isinstance(g_data, dict) and str(g_data.get("task_id") or "") == tid:
                if not g_data.get("superseded_by_normal_mode"):
                    g_data["superseded_by_normal_mode"] = True
                    g_data["superseded_at"] = utc_now()
                    atomic_write_json(g_ptr, g_data)
        except (OSError, ValueError, ValidationError):
            pass
    return superseded_ids


def _restore_web_pack_visibility_on_web_switch(repo: Path, tid: str) -> None:
    t_ptr = task_dir(repo, tid) / "latest-web-pack.json"
    if t_ptr.is_file():
        try:
            ptr_data = read_json(t_ptr)
            if isinstance(ptr_data, dict) and ptr_data.get("superseded_by_normal_mode"):
                ptr_data.pop("superseded_by_normal_mode", None)
                ptr_data.pop("superseded_at", None)
                atomic_write_json(t_ptr, ptr_data)
        except (OSError, ValueError, ValidationError):
            pass


def set_execution_mode(
    repo: Path,
    *,
    choice: str | None = None,
    mode: str | None = None,
    scope: str | None = None,
    task_id: str | None = None,
    new_task: bool = False,
    source: str = "",
    proof_reference: str = "",
) -> dict[str, Any]:
    repo = Path(repo).resolve()
    norm_source = str(source or "").strip().lower()
    norm_proof = str(redact(str(proof_reference or "").strip()))
    if norm_source != "conversation" or len(norm_proof) < 2:
        raise ValidationError(
            "DEVELOPER_AUTHORITY_REQUIRED: `execution-mode set` requires `--source conversation` "
            "and a non-empty `--proof-reference \"<developer words>\"`."
        )

    canonical_choice, resolved_mode, resolved_scope = normalize_choice(choice=choice, mode=mode, scope=scope)
    explicit_tid = validate_id(task_id, "task id") if str(task_id or "").strip() else ""

    lock_path = state_root(repo) / "locks" / "execution-mode.lock"
    with _MODE_THREAD_LOCK, StateLock(lock_path, timeout_seconds=30.0):
        now_iso = utc_now()
        now_epoch = round(time.time(), 3)

        if resolved_scope == "reset":
            removed: list[str] = []
            p_file = project_mode_file(repo)
            if p_file.is_file():
                p_file.unlink(missing_ok=True)
                removed.append(str(p_file.relative_to(repo)))
            pend_file = pending_task_mode_file(repo)
            if pend_file.is_file():
                pend_file.unlink(missing_ok=True)
                removed.append(str(pend_file.relative_to(repo)))
            if explicit_tid:
                t_file = task_mode_file(repo, explicit_tid)
                if t_file.is_file():
                    t_file.unlink(missing_ok=True)
                    removed.append(str(t_file.relative_to(repo)))
            eff = resolve_effective_execution_mode(repo, task_id=explicit_tid or None)
            return {
                "status": "RESET_TO_ASK_EVERY_TASK",
                "choice": canonical_choice,
                "mode": eff["mode"],
                "scope": "reset",
                "cleared_files": removed,
                "effective": eff,
            }

        base_record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "choice": canonical_choice,
            "mode": resolved_mode,
            "scope": resolved_scope,
            "source": "conversation",
            "proof_reference": norm_proof[:240],
            "updated_at": now_iso,
            "updated_at_epoch": now_epoch,
        }

        if resolved_scope == "project":
            proj_record = _sign_record(base_record)
            p_file = project_mode_file(repo)
            p_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(p_file, proj_record)
            # Clear stale pre-draft pending single-task choice so project choice takes clean effect
            pending_task_mode_file(repo).unlink(missing_ok=True)

            superseded_packs: list[str] = []
            bound_tid = ""
            if explicit_tid and (task_dir(repo, explicit_tid) / "plan.json").is_file():
                bound_tid = explicit_tid
                t_rec = _sign_record({**base_record, "scope": "task", "task_id": explicit_tid})
                atomic_write_json(task_mode_file(repo, explicit_tid), t_rec)
            elif not new_task:
                live_tid, live_plan = _resolve_target_task_and_plan(repo)
                if live_tid and live_plan and str(live_plan.get("status") or "").upper() not in TERMINAL_TASK_STATES:
                    bound_tid = live_tid
                    # Remove any prior single-task override so the new project choice governs immediately
                    task_mode_file(repo, live_tid).unlink(missing_ok=True)
            if bound_tid:
                if resolved_mode == "normal":
                    superseded_packs = _supersede_unapplied_web_pack_on_normal_switch(repo, bound_tid)
                elif resolved_mode == "web":
                    _restore_web_pack_visibility_on_web_switch(repo, bound_tid)

            eff = resolve_effective_execution_mode(repo, task_id=explicit_tid or None)
            out: dict[str, Any] = {
                "status": "EXECUTION_MODE_SAVED",
                "choice": canonical_choice,
                "mode": eff["mode"],
                "configured_mode": resolved_mode,
                "scope": "project",
                "persisted_path": str(p_file.relative_to(repo)).replace("\\", "/"),
                "record_sha256": proj_record["record_sha256"],
                "effective": eff,
            }
            if superseded_packs:
                out["superseded_web_packs"] = superseded_packs
            if resolved_mode == "web":
                out["next_step_hint"] = (
                    f"python .agents/harness.py web-pack --task-id {bound_tid}"
                    if bound_tid
                    else "Scope target files via `graph` / `task-context`, then run `python .agents/harness.py web-pack --files <csv> --prompt \"<request>\"`."
                )
            return out

        # Task-scoped choice (`normal-task` or `web-task`)
        target_tid = ""
        if not new_task:
            if explicit_tid:
                if (task_dir(repo, explicit_tid) / "plan.json").is_file():
                    target_tid = explicit_tid
            else:
                live_tid, live_plan = _resolve_target_task_and_plan(repo)
                if live_tid and live_plan and str(live_plan.get("status") or "").upper() not in TERMINAL_TASK_STATES:
                    target_tid = live_tid

        if target_tid:
            t_file = task_mode_file(repo, target_tid)
            t_file.parent.mkdir(parents=True, exist_ok=True)
            t_record = _sign_record({**base_record, "task_id": target_tid})
            atomic_write_json(t_file, t_record)
            pending_task_mode_file(repo).unlink(missing_ok=True)

            superseded_packs = []
            if resolved_mode == "normal":
                superseded_packs = _supersede_unapplied_web_pack_on_normal_switch(repo, target_tid)
            elif resolved_mode == "web":
                _restore_web_pack_visibility_on_web_switch(repo, target_tid)

            eff = resolve_effective_execution_mode(repo, task_id=target_tid)
            res: dict[str, Any] = {
                "status": "EXECUTION_MODE_SAVED",
                "choice": canonical_choice,
                "mode": eff["mode"],
                "configured_mode": resolved_mode,
                "scope": "task",
                "task_id": target_tid,
                "persisted_path": str(t_file.relative_to(repo)).replace("\\", "/"),
                "record_sha256": t_record["record_sha256"],
                "project_default_preserved": eff.get("project_choice"),
                "effective": eff,
            }
            if superseded_packs:
                res["superseded_web_packs"] = superseded_packs
            if resolved_mode == "web":
                res["next_step_command"] = f"python .agents/harness.py web-pack --task-id {target_tid}"
            return res

        # Pre-draft / cold-start pending single-task choice
        pend_file = pending_task_mode_file(repo)
        pend_file.parent.mkdir(parents=True, exist_ok=True)
        pend_record = _sign_record({
            **base_record,
            "intended_task_id": explicit_tid,
        })
        atomic_write_json(pend_file, pend_record)
        eff = resolve_effective_execution_mode(repo, task_id=explicit_tid or None)
        res = {
            "status": "EXECUTION_MODE_PENDING_FOR_NEXT_TASK",
            "choice": canonical_choice,
            "mode": eff["mode"],
            "configured_mode": resolved_mode,
            "scope": "pending_task",
            "intended_task_id": explicit_tid,
            "persisted_path": str(pend_file.relative_to(repo)).replace("\\", "/"),
            "record_sha256": pend_record["record_sha256"],
            "project_default_preserved": eff.get("project_choice"),
            "effective": eff,
        }
        if resolved_mode == "web":
            res["next_step_hint"] = (
                "Scope target files via `graph` / `task-context`, then run "
                "`python .agents/harness.py web-pack --files <csv> --prompt \"<request>\"`."
            )
        return res


def bind_pending_execution_mode_to_task(repo: Path, task_id: str) -> dict[str, Any] | None:
    """Promote `.agents/state/pending-task-execution-mode.json` into `.agents/state/tasks/<task_id>/execution-mode.json`."""
    repo = Path(repo).resolve()
    tid = str(task_id or "").strip()
    if not tid:
        return None
    pend_file = pending_task_mode_file(repo)
    if not pend_file.is_file():
        return None
    lock_path = state_root(repo) / "locks" / "execution-mode.lock"
    with _MODE_THREAD_LOCK, StateLock(lock_path, timeout_seconds=30.0):
        pend_rec, err = _read_verified_record(pend_file, strict=False)
        if err or pend_rec is None or _is_pending_expired(pend_rec):
            pend_file.unlink(missing_ok=True)
            return None
        intended_tid = str(pend_rec.get("intended_task_id") or "").strip()
        if intended_tid and intended_tid != tid:
            return None
        t_file = task_mode_file(repo, tid)
        if t_file.is_file():
            existing, ex_err = _read_verified_record(t_file, strict=False)
            if existing is not None and not ex_err:
                pend_file.unlink(missing_ok=True)
                return existing
        bound = _sign_record({
            "schema_version": SCHEMA_VERSION,
            "choice": str(pend_rec.get("choice") or f"{pend_rec.get('mode', 'normal')}-task"),
            "mode": str(pend_rec.get("mode") or "normal"),
            "scope": "task",
            "task_id": tid,
            "bound_from_pending": True,
            "source": str(pend_rec.get("source") or "conversation"),
            "proof_reference": str(pend_rec.get("proof_reference") or ""),
            "updated_at": utc_now(),
            "updated_at_epoch": round(time.time(), 3),
        })
        t_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(t_file, bound)
        pend_file.unlink(missing_ok=True)
        return bound


def record_pending_pack_link(repo: Path, pack_id: str) -> None:
    """Refresh pending pre-draft `web-task` TTL when cold-start `web-pack` runs before `web-apply` creates `task_id`."""
    repo = Path(repo).resolve()
    pend_file = pending_task_mode_file(repo)
    if not pend_file.is_file():
        return
    lock_path = state_root(repo) / "locks" / "execution-mode.lock"
    with _MODE_THREAD_LOCK, StateLock(lock_path, timeout_seconds=30.0):
        pend_rec, err = _read_verified_record(pend_file, strict=False)
        if err or pend_rec is None or str(pend_rec.get("mode") or "") not in {"web", "auto"}:
            return
        pend_rec["last_pack_id"] = str(pack_id or "").strip()
        pend_rec["updated_at"] = utc_now()
        pend_rec["updated_at_epoch"] = round(time.time(), 3)
        atomic_write_json(pend_file, _sign_record(pend_rec))


def inspect_web_phase_progress(
    repo: Path,
    plan: dict[str, Any] | None,
    target_files: list[str] | None = None,
) -> dict[str, Any]:
    """Check whether the active phase of a `web`-mode task has staged or applied Web-Relay changes."""
    repo = Path(repo).resolve()
    if not isinstance(plan, dict):
        return {"phase_id": "", "has_staged_phase": False, "has_applied_web_changes": False}
    tid = str(plan.get("task_id") or "").strip()
    if not tid:
        return {"phase_id": "", "has_staged_phase": False, "has_applied_web_changes": False}

    tdir = task_dir(repo, tid)
    phase_id = ""
    phase_files: list[str] = []
    phases = plan.get("phases")
    completed_phases: set[str] = set()
    pstate_f = tdir / "phase-state.json"
    pstate_cur = ""
    if pstate_f.is_file():
        try:
            ps_doc = read_json(pstate_f)
            if isinstance(ps_doc, dict):
                pstate_cur = str(ps_doc.get("current_phase_id") or "").strip()
                completed_phases = {str(x).strip() for x in (ps_doc.get("completed_phases") or []) if str(x).strip()}
        except (OSError, ValueError, ValidationError):
            pstate_cur = ""

    if isinstance(phases, list) and phases:
        chosen_ph: dict[str, Any] | None = None
        if pstate_cur:
            for ph in phases:
                if isinstance(ph, dict) and str(ph.get("id") or ph.get("phase_id") or "").strip() == pstate_cur:
                    if pstate_cur not in completed_phases and str(ph.get("status") or "").upper() != "COMPLETED":
                        chosen_ph = ph
                    break
        if chosen_ph is None:
            try:
                act_idx = int(plan.get("active_phase_index") or 0)
            except (TypeError, ValueError):
                act_idx = 0
            if 0 <= act_idx < len(phases) and isinstance(phases[act_idx], dict):
                cand_ph = phases[act_idx]
                cand_id = str(cand_ph.get("id") or cand_ph.get("phase_id") or "").strip()
                if cand_id not in completed_phases and str(cand_ph.get("status") or "").upper() != "COMPLETED":
                    chosen_ph = cand_ph
        if chosen_ph is None:
            for ph in phases:
                if not isinstance(ph, dict):
                    continue
                pid_c = str(ph.get("id") or ph.get("phase_id") or "").strip()
                if pid_c in completed_phases or str(ph.get("status") or "").upper() == "COMPLETED":
                    continue
                chosen_ph = ph
                break
        if chosen_ph is not None:
            phase_id = str(chosen_ph.get("id") or chosen_ph.get("phase_id") or "").strip()
            raw_pf = chosen_ph.get("expected_files") or chosen_ph.get("files") or []
            phase_files = [str(f).replace("\\", "/").lstrip("/") for f in raw_pf if str(f).strip()]

    if not phase_files:
        src_list = target_files if target_files is not None else (plan.get("expected_files") or [])
        phase_files = [str(f).replace("\\", "/").lstrip("/") for f in src_list if str(f).strip()]

    has_staged = bool(phase_id and (tdir / "staged-web-phases" / f"{phase_id}.json").is_file())
    # If an unapplied continuation batch pack (`Batch 2/3` or `PARTIAL` open pack) is waiting on this task, stay in WEB_RELAY_ACTIVE!
    latest_tp = tdir / "latest-web-pack.json"
    if latest_tp.is_file():
        try:
            tp_doc = read_json(latest_tp)
            if isinstance(tp_doc, dict) and not tp_doc.get("superseded_by_normal_mode"):
                pid_ptr = str(tp_doc.get("pack_id") or "").strip()
                p_meta_f = state_root(repo) / "web-relay" / "packs" / f"{pid_ptr}.json"
                if pid_ptr and p_meta_f.is_file():
                    p_meta = read_json(p_meta_f)
                    if isinstance(p_meta, dict) and not p_meta.get("applied") and (
                        int(p_meta.get("batch_index") or 1) > 1 or int(p_meta.get("partial_batches_applied") or 0) > 0
                    ):
                        return {
                            "phase_id": phase_id,
                            "has_staged_phase": has_staged,
                            "has_applied_web_changes": False,
                            "pending_continuation_pack_id": pid_ptr,
                            "batch_index": int(p_meta.get("batch_index") or 1),
                            "total_batches": int(p_meta.get("total_batches") or 1),
                        }
        except (OSError, ValueError, ValidationError):
            pass
    wr_rec_p = tdir / "web-relay-receipt.json"
    if not wr_rec_p.is_file():
        return {"phase_id": phase_id, "has_staged_phase": has_staged, "has_applied_web_changes": False}

    has_applied = False
    try:
        wr_doc = read_json(wr_rec_p)
        if isinstance(wr_doc, dict) and wr_doc.get("incomplete_continuation"):
            return {"phase_id": phase_id, "has_staged_phase": has_staged, "has_applied_web_changes": False, "has_prior_web_round": True}
        # If task was resumed (`--reopen` from READY_FOR_DELIVERY or `resume` from BLOCKED/VERIFYING),
        # check deterministic receipt flags + change_set_sha256 so same-second CLI calls have zero clock race!
        if isinstance(wr_doc, dict) and (wr_doc.get("stale_after_reopen") or wr_doc.get("resumed_from_verification")):
            decisions_l = plan.get("change_decisions") or []
            has_accept = not plan.get("blocked_reviewers") and any(
                isinstance(d, dict) and d.get("mode") == "accept-edits" for d in decisions_l
            )
            if wr_doc.get("stale_after_reopen") or not has_accept:
                rec_cs = str(wr_doc.get("change_set_sha256") or "").strip()
                if rec_cs:
                    from delivery_manifest import build_task_manifest, load_task_baseline
                    live_tm = build_task_manifest(repo, load_task_baseline(repo, tid), expected_files=plan.get("expected_files"))
                    if str(live_tm.get("change_set_sha256") or "") == rec_cs:
                        needs_retry = bool(wr_doc.get("resumed_from_verification") or plan.get("blocked_reviewers") or plan.get("review_rounds"))
                        return {
                            "phase_id": phase_id,
                            "has_staged_phase": has_staged,
                            "has_applied_web_changes": False,
                            "has_prior_web_round": True,
                            "needs_retry_pack": needs_retry,
                        }
        rec_phase = str((wr_doc or {}).get("phase_id") or "").strip() if isinstance(wr_doc, dict) else ""
        rec_touched = {
            str(x).replace("\\", "/").lstrip("/")
            for x in (((wr_doc or {}).get("files_written") or []) + ((wr_doc or {}).get("files_deleted") or []))
            if str(x).strip()
        } if isinstance(wr_doc, dict) else set()
        phase_set = set(phase_files)
        if phase_id and rec_phase == phase_id:
            has_applied = True
        elif phase_set and (rec_touched & phase_set):
            has_applied = True
        else:
            from workflow import build_task_manifest, load_task_baseline
            ph_base_f = tdir / "phases" / phase_id / "baseline.json" if phase_id else None
            base_data = read_json(ph_base_f) if (ph_base_f and ph_base_f.is_file()) else load_task_baseline(repo, tid)
            tm = build_task_manifest(repo, base_data, expected_files=phase_files or plan.get("expected_files"))
            raw_changes = tm.get("task_changes") if "task_changes" in tm else tm.get("changes")
            changed_paths: set[str] = set()
            if isinstance(raw_changes, dict):
                changed_paths = {str(k).replace("\\", "/").lstrip("/") for k in raw_changes.keys()}
            elif isinstance(raw_changes, list):
                for item in raw_changes:
                    if isinstance(item, dict) and item.get("path"):
                        changed_paths.add(str(item["path"]).replace("\\", "/").lstrip("/"))
                    elif isinstance(item, str):
                        changed_paths.add(item.replace("\\", "/").lstrip("/"))
            has_applied = bool(changed_paths & phase_set) if phase_set else bool(changed_paths)
    except (ImportError, OSError, ValueError, ValidationError):
        has_applied = not bool(phase_id and has_staged)

    return {
        "phase_id": phase_id,
        "has_staged_phase": has_staged,
        "has_applied_web_changes": has_applied,
    }

def verify_execution_mode_integrity(repo: Path) -> tuple[bool, list[str]]:
    """Inspect project, pending, and live-task `execution-mode.json` files for tamper/schema integrity (`doctor`)."""
    repo = Path(repo).resolve()
    errors: list[str] = []
    with _MODE_THREAD_LOCK:
        for candidate in (project_mode_file(repo), pending_task_mode_file(repo)):
            if candidate.is_file():
                _, err = _read_verified_record(candidate, strict=False)
                if err:
                    errors.append(err)
        tasks_root = state_root(repo) / "tasks"
        if tasks_root.is_dir():
            for tdir in sorted(tasks_root.iterdir()):
                if not tdir.is_dir():
                    continue
                tm = tdir / "execution-mode.json"
                if tm.is_file():
                    _, err = _read_verified_record(tm, strict=False)
                    if err:
                        errors.append(f"{tdir.name}/{err}")
    return (len(errors) == 0), errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="execution_mode.py",
        description="Show or persist per-task / per-project execution mode (`normal` vs `web`).",
    )
    parser.add_argument("--repo", default=".", help="Repository root.")
    parser.add_argument("--task-id", default="", help="Optional task identifier.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    sub = parser.add_subparsers(dest="subcommand")

    p_show = sub.add_parser("show", help="Resolve and show the effective execution mode (read-only).")
    p_show.add_argument("--repo", default=".", help="Repository root.")
    p_show.add_argument("--task-id", default="", help="Optional task identifier.")
    p_show.add_argument("--json", action="store_true", help="Emit JSON output.")

    p_set = sub.add_parser("set", help="Record developer's execution-mode choice (`--source conversation` required).")
    p_set.add_argument("--repo", default=".", help="Repository root.")
    p_set.add_argument("--task-id", default="", help="Optional task identifier.")
    p_set.add_argument(
        "--new-task",
        action="store_true",
        help="Stage a single-task choice for the next upcoming task without modifying an existing live task.",
    )
    p_set.add_argument(
        "--choice",
        default="",
        help="Canonical choice: `auto-project`, `auto-task`, `normal-task`, `normal-project`, `web-task`, `web-project`, or `ask-every-task`.",
    )
    p_set.add_argument("--mode", default="", help="Alternative mode selector (`auto`, `normal`, `web`, or `unset`).")
    p_set.add_argument("--scope", default="", help="Alternative scope selector (`task`, `project`, or `reset`).")
    p_set.add_argument("--source", required=True, help="Authority source (must be `conversation`).")
    p_set.add_argument("--proof-reference", required=True, help="Exact developer phrase authorizing this mode choice.")
    p_set.add_argument("--json", action="store_true", help="Emit JSON output.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo = Path(getattr(args, "repo", ".") or ".").resolve()
    tid = str(getattr(args, "task_id", "") or "").strip() or None
    subcmd = str(getattr(args, "subcommand", "") or "show").strip().lower()

    try:
        if subcmd in ("", "show"):
            result = resolve_effective_execution_mode(repo, task_id=tid)
            configure_utf8_output()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if subcmd == "set":
            result = set_execution_mode(
                repo,
                choice=getattr(args, "choice", ""),
                mode=getattr(args, "mode", ""),
                scope=getattr(args, "scope", ""),
                task_id=tid,
                new_task=bool(getattr(args, "new_task", False)),
                source=getattr(args, "source", ""),
                proof_reference=getattr(args, "proof_reference", ""),
            )
            configure_utf8_output()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        raise ValidationError(f"Unknown execution-mode subcommand: {subcmd}")
    except ValidationError as exc:
        configure_utf8_output()
        print(json.dumps({"status": "ERROR", "error": str(exc)}, indent=2, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
