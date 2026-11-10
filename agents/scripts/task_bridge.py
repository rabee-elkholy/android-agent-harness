"""Smart Context Rotation & Task-to-Task Context Bridge (`task bridge`).

Standard library only. Provides:
1. Conversation bloat detection (`measure_conversation_health`, `evaluate_rotation_advisory`)
   using hook turn counters and Antigravity transcript tail inspection when available.
2. Task-to-Task & Mid-Task context bridging (`save_task_bridge`, `load_task_bridge`) that
   transfers architectural contracts, modified file scopes, plan notes, and a fresh
   conversation-local Discovery Receipt into a new chat with zero re-discovery overhead.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from _vnext_common import (
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    read_json,
    redact,
    repository_identity,
    state_root,
    task_dir,
    utc_now,
    validate_id,
)

BRIDGE_SCHEMA_VERSION = 1

# Post-task / follow-up boundary thresholds (recommend starting next task in a fresh bridged chat)
FOLLOW_UP_STEPS_THRESHOLD = 120
FOLLOW_UP_TOKENS_THRESHOLD = 80_000

# Mid-task clean checkpoint thresholds (phase boundary / pre-verification)
MID_TASK_STEPS_THRESHOLD = 220
MID_TASK_TOKENS_THRESHOLD = 110_000

DEFAULT_SNOOZE_STEPS = 120


def _active_conversation_file(repo: Path) -> Path:
    return state_root(repo) / "active-conversation.json"


def _snooze_file(repo: Path) -> Path:
    return state_root(repo) / "context-rotation-snooze.json"


def _bridge_file(repo: Path) -> Path:
    return state_root(repo) / "task-bridge.json"


def _bridges_queue_file(repo: Path) -> Path:
    return state_root(repo) / "task-bridges.json"


def _bridge_history_dir(repo: Path) -> Path:
    return state_root(repo) / "bridge-history"


def record_active_conversation_turn(repo: Path, conversation_id: str) -> dict[str, Any] | None:
    """Record a non-reviewer tool call in the active conversation tracker (best effort)."""
    conv_id = str(conversation_id or "").strip()
    if not conv_id:
        return None
    path = _active_conversation_file(repo)
    now_iso = utc_now()
    now_ts = time.time()
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = read_json(path)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError, ValidationError):
            data = {}
    if str(data.get("conversation_id") or "") != conv_id:
        record = {
            "conversation_id": conv_id,
            "started_at": now_iso,
            "started_at_epoch": now_ts,
            "updated_at": now_iso,
            "hook_calls": 1,
        }
    else:
        record = {
            "conversation_id": conv_id,
            "started_at": str(data.get("started_at") or now_iso),
            "started_at_epoch": float(data.get("started_at_epoch") or now_ts),
            "updated_at": now_iso,
            "hook_calls": int(data.get("hook_calls") or 0) + 1,
        }
    try:
        atomic_write_json(path, record)
    except OSError:
        pass
    return record


def _inspect_transcript_tail(transcript_path: Path) -> dict[str, int]:
    """Read only the tail of a JSONL transcript to extract step_index and token metrics."""
    metrics = {"steps": 0, "tokens": 0, "bytes": 0}
    try:
        if not transcript_path.is_file():
            return metrics
        st = transcript_path.stat()
        size = int(st.st_size)
        metrics["bytes"] = size
        read_len = min(size, 65536)
        with transcript_path.open("rb") as fh:
            if size > read_len:
                fh.seek(size - read_len)
            raw_tail = fh.read(read_len).decode("utf-8", errors="replace")
        lines = [ln.strip() for ln in raw_tail.splitlines() if ln.strip().startswith("{") and ln.strip().endswith("}")]
        max_step = 0
        latest_tokens = 0
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            step_idx = obj.get("step_index")
            if isinstance(step_idx, int) and step_idx > max_step:
                max_step = step_idx
            for usage_key in ("usage", "token_usage", "usageMetadata", "metadata"):
                u = obj.get(usage_key)
                if isinstance(u, dict):
                    cand = (
                        int(u.get("input_tokens") or u.get("promptTokenCount") or u.get("prompt_tokens") or 0)
                        + int(u.get("cache_read_tokens") or u.get("cachedContentTokenCount") or 0)
                    )
                    if not cand:
                        cand = int(u.get("total_tokens") or u.get("totalTokenCount") or 0)
                    if cand > latest_tokens:
                        latest_tokens = cand
            if max_step > 0 and latest_tokens > 0:
                break
        metrics["steps"] = max_step
        metrics["tokens"] = latest_tokens
    except OSError:
        pass
    return metrics


def measure_conversation_health(repo: Path) -> dict[str, Any]:
    """Measure active conversation steps and estimated context tokens without blocking."""
    conv_id = os.environ.get("HARNESS_CONVERSATION_ID", "").strip()
    hook_calls = 0
    started_at = ""
    conv_file = _active_conversation_file(repo)
    if conv_file.is_file():
        try:
            conv_data = read_json(conv_file)
            if isinstance(conv_data, dict):
                if not conv_id:
                    conv_id = str(conv_data.get("conversation_id") or "").strip()
                hook_calls = int(conv_data.get("hook_calls") or 0)
                started_at = str(conv_data.get("started_at") or "")
        except (OSError, ValueError, ValidationError):
            pass

    steps = hook_calls
    tokens = 0
    transcript_bytes = 0
    source = "hook_counter" if hook_calls > 0 else "none"

    if conv_id and re.fullmatch(r"[0-9a-fA-F-]{20,64}", conv_id):
        try:
            from antigravity_runtime import resolve_transcript
            transcript = resolve_transcript(conv_id)
            if isinstance(transcript, Path) and transcript.is_file():
                t_metrics = _inspect_transcript_tail(transcript)
                transcript_bytes = t_metrics["bytes"]
                if t_metrics["steps"] > steps:
                    steps = t_metrics["steps"]
                    source = "antigravity_transcript"
                if t_metrics["tokens"] > 0:
                    tokens = t_metrics["tokens"]
                    source = "antigravity_transcript"
        except (ImportError, OSError, ValueError):
            pass

    env_steps = os.environ.get("HARNESS_CONVERSATION_STEPS", "").strip()
    if env_steps.isdigit():
        steps = int(env_steps)
        source = "env_override"

    env_bytes = os.environ.get("HARNESS_CONVERSATION_BYTES", "").strip()
    if env_bytes.isdigit():
        transcript_bytes = int(env_bytes)
        if source != "env_override":
            source = "env_override"

    env_tokens = os.environ.get("HARNESS_CONVERSATION_TOKENS", "").strip()
    if env_tokens.isdigit():
        tokens = int(env_tokens)
        source = "env_override"

    if tokens <= 0:
        # Conservative estimation when exact token counters are not exposed in the compact log
        by_steps = steps * 680
        by_bytes = transcript_bytes // 6 if transcript_bytes > 0 else 0
        tokens = max(by_steps, by_bytes)

    return {
        "conversation_id": conv_id,
        "started_at": started_at,
        "steps": steps,
        "hook_calls": hook_calls,
        "estimated_context_tokens": tokens,
        "transcript_bytes": transcript_bytes,
        "source": source,
    }


def is_rotation_snoozed(repo: Path, health: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    """True when the developer snoozed context rotation advisories for the current conversation."""
    snooze_path = _snooze_file(repo)
    if not snooze_path.is_file():
        return False, {}
    try:
        snooze = read_json(snooze_path)
        if not isinstance(snooze, dict):
            return False, {}
    except (OSError, ValueError, ValidationError):
        return False, {}
    if health is None:
        health = measure_conversation_health(repo)
    cur_conv = str(health.get("conversation_id") or "")
    snooze_conv = str(snooze.get("conversation_id") or "")
    if snooze_conv and cur_conv and snooze_conv != cur_conv:
        return False, {}
    cur_steps = int(health.get("steps") or 0)
    until_steps = int(snooze.get("snooze_until_steps") or 0)
    if cur_steps < until_steps:
        return True, snooze
    return False, snooze


def evaluate_rotation_advisory(
    repo: Path,
    checkpoint_kind: str,
    *,
    task_id: str = "",
    plan: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a structured non-blocking rotation recommendation when conversation bloat exceeds thresholds."""
    health = measure_conversation_health(repo)
    steps = int(health.get("steps") or 0)
    tokens = int(health.get("estimated_context_tokens") or 0)
    if steps <= 0 and tokens <= 0:
        return None

    is_follow_up = checkpoint_kind in {"FOLLOW_UP_BOUNDARY", "FOLLOW_UP_TASK", "POST_TASK"}
    step_limit = FOLLOW_UP_STEPS_THRESHOLD if is_follow_up else MID_TASK_STEPS_THRESHOLD
    token_limit = FOLLOW_UP_TOKENS_THRESHOLD if is_follow_up else MID_TASK_TOKENS_THRESHOLD

    if steps < step_limit and tokens < token_limit:
        return None

    snoozed, _ = is_rotation_snoozed(repo, health)
    if snoozed:
        return None

    tid = str(task_id or (plan or {}).get("task_id") or "").strip()
    tid_arg = f" --task-id {tid}" if tid else ""
    mode = "FOLLOW_UP_TASK" if is_follow_up else "MID_TASK_HANDOFF"
    if is_follow_up:
        save_cmd = f'python .agents/harness.py task bridge --save{tid_arg} --next-outcome "<follow-up request>" --summary "<key decisions>"'
        reason = (
            f"Active conversation has grown large (~{steps} steps, ~{tokens:,} est. context tokens). "
            "If the developer wants to start a related follow-up task, bridging to a fresh chat preserves the "
            "completed task's architecture contract, modified files, and a fresh Discovery Receipt with zero re-explanation."
        )
        instructions = (
            "Mention briefly (or ask via `ask_question` when starting a follow-up task) that this chat has grown large "
            f"(~{steps} steps / ~{tokens:,} tokens) and offer to bridge context to a fresh chat (`{save_cmd}` then "
            "`python .agents/harness.py task bridge` in the new chat) or snooze (`python .agents/harness.py task bridge --snooze`)."
        )
    else:
        save_cmd = f'python .agents/harness.py task bridge --save{tid_arg} --summary "<current progress & next step>"'
        reason = (
            f"Active conversation has reached a high-context checkpoint (~{steps} steps, ~{tokens:,} est. context tokens). "
            "At this clean phase/verification boundary, the developer can optionally rotate to a fresh chat without losing "
            "task state, approval, or verification proof."
        )
        instructions = (
            "At this checkpoint, you may inform the developer that the conversation is large "
            f"(~{steps} steps / ~{tokens:,} tokens) and can be continued seamlessly in a new chat by running "
            f"`{save_cmd}` now and `python .agents/harness.py task bridge` in the new chat (or `--snooze` to stay here)."
        )

    return {
        "code": "CONTEXT_ROTATION_RECOMMENDED",
        "recommended": True,
        "mode": mode,
        "checkpoint_kind": checkpoint_kind,
        "conversation_steps": steps,
        "estimated_context_tokens": tokens,
        "threshold_steps": step_limit,
        "threshold_tokens": token_limit,
        "save_command": save_cmd,
        "load_command": "python .agents/harness.py task bridge",
        "snooze_command": "python .agents/harness.py task bridge --snooze",
        "reason": reason,
        "instructions": instructions,
    }


def _resolve_target_task(repo: Path, explicit_task_id: str = "") -> tuple[str, dict[str, Any] | None]:
    """Find the target task plan, falling back to the most recently updated/delivered task when active-task.json was cleared."""
    sroot = state_root(repo)
    tid = str(explicit_task_id or "").strip()
    if tid:
        validate_id(tid, "task_id")
        p_file = sroot / "tasks" / tid / "plan.json"
        if not p_file.is_file():
            raise ValidationError(f"task '{tid}' not found at {p_file}")
        return tid, read_json(p_file)

    active_file = sroot / "active-task.json"
    if active_file.is_file():
        try:
            active = read_json(active_file)
            cand_tid = str(active.get("task_id") or "").strip()
            if cand_tid:
                p_file = sroot / "tasks" / cand_tid / "plan.json"
                if p_file.is_file():
                    return cand_tid, read_json(p_file)
        except (OSError, ValueError, ValidationError):
            pass

    tasks_dir = sroot / "tasks"
    if not tasks_dir.is_dir():
        return "", None

    candidates: list[tuple[str, float, str, dict[str, Any]]] = []
    for sub in tasks_dir.iterdir():
        if not sub.is_dir():
            continue
        p_file = sub / "plan.json"
        if not p_file.is_file():
            continue
        try:
            plan = read_json(p_file)
            if not isinstance(plan, dict):
                continue
            c_tid = str(plan.get("task_id") or sub.name)
            ts_str = str(
                plan.get("delivered_at")
                or plan.get("ready_at")
                or plan.get("resumed_at")
                or plan.get("approved_at")
                or plan.get("created_at")
                or ""
            )
            mtime = p_file.stat().st_mtime
            candidates.append((ts_str, mtime, c_tid, plan))
        except (OSError, ValueError, ValidationError):
            continue

    if not candidates:
        return "", None

    # Prefer live tasks first if any exist; otherwise most recently touched/delivered task
    live_states = {"AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"}
    live = [item for item in candidates if str(item[3].get("status") or "") in live_states]
    pool = live if live else candidates
    pool.sort(key=lambda item: (item[1], item[0]), reverse=True)
    _, _, chosen_tid, chosen_plan = pool[0]
    return chosen_tid, chosen_plan


def _collect_task_modified_files(repo: Path, task_id: str, plan: dict[str, Any]) -> list[str]:
    """Extract task-modified or verified file paths from frozen manifests or live task delta."""
    if not task_id or not plan:
        return []
    tdir = task_dir(repo, task_id)
    paths: list[str] = []

    run_id = str(plan.get("ready_run_id") or plan.get("verification_run_id") or "")
    if not run_id and (tdir / "current-run.json").is_file():
        try:
            run_id = str(read_json(tdir / "current-run.json").get("run_id") or "")
        except (OSError, ValueError, ValidationError):
            run_id = ""

    if run_id:
        m_file = tdir / f"manifest-{run_id}.json"
        if m_file.is_file():
            try:
                man = read_json(m_file)
                changes = man.get("task_changes") if "task_changes" in man else man.get("changes")
                for item in changes or []:
                    p = str((item or {}).get("path") if isinstance(item, dict) else item or "").replace("\\", "/").strip("/")
                    if p and not p.startswith((".agents/", ".harness-")) and p not in paths:
                        paths.append(p)
            except (OSError, ValueError, ValidationError):
                pass

    if not paths:
        try:
            from delivery_snapshot import build_task_manifest, load_task_baseline
            baseline = load_task_baseline(repo, task_id)
            if baseline:
                man = build_task_manifest(repo, baseline, expected_files=plan.get("expected_files"))
                changes = man.get("task_changes") if "task_changes" in man else man.get("changes")
                for item in changes or []:
                    p = str((item or {}).get("path") if isinstance(item, dict) else item or "").replace("\\", "/").strip("/")
                    if p and not p.startswith((".agents/", ".harness-")) and p not in paths:
                        paths.append(p)
        except (ImportError, OSError, ValueError, ValidationError):
            pass

    for exp in plan.get("expected_files") or []:
        p = str(exp or "").replace("\\", "/").strip("/")
        if p and p not in paths:
            paths.append(p)
    for phase in plan.get("phases") or []:
        if isinstance(phase, dict):
            for exp in phase.get("expected_files") or []:
                p = str(exp or "").replace("\\", "/").strip("/")
                if p and p not in paths:
                    paths.append(p)
    return paths


_DECL_RE = re.compile(
    r"^\s*(?:@(?:Composable|JvmStatic|HiltViewModel|Inject)\s+)*"
    r"(?:(?:public|internal|protected|private|open|abstract|final|sealed|data|value|inline|suspend|override|actual|expect|external|operator|infix|tailrec|companion)\s+)*"
    r"(?P<kind>class|interface|object|enum\s+class|fun|func|struct|protocol|def|typealias)\s+"
    r"(?P<sig>[A-Za-z_][A-Za-z0-9_<>.,:\s?()*=\[\]]*)"
)


def _extract_interface_delta(repo: Path, paths: list[str], *, max_files: int = 12, max_decls_per_file: int = 8) -> list[dict[str, Any]]:
    """Extract compact top-level/member declaration signatures from modified/expected source files."""
    supported_exts = {".kt", ".java", ".swift", ".py"}
    results: list[dict[str, Any]] = []
    for rel in paths:
        if len(results) >= max_files:
            break
        norm = str(rel or "").replace("\\", "/").strip().strip("/")
        if not norm or norm.startswith((".agents/", ".harness-")):
            continue
        full = repo / norm
        if not full.is_file() or full.suffix.lower() not in supported_exts:
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        decls: list[str] = []
        in_block_comment = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if in_block_comment:
                if "*/" in line:
                    in_block_comment = False
                continue
            if line.startswith("/*"):
                if "*/" not in line:
                    in_block_comment = True
                continue
            if line.startswith(("//", "#", "*")):
                continue
            # Strip trailing inline comment and body brace
            clean = re.split(r"\s+//|\s+#", line, maxsplit=1)[0].strip()
            if "{" in clean:
                clean = clean.split("{", 1)[0].strip()
            if clean.endswith(":") and full.suffix.lower() == ".py":
                clean = clean[:-1].strip()
            m = _DECL_RE.match(clean)
            if not m:
                continue
            # Skip private declarations unless no public ones exist yet
            if re.search(r"\bprivate\b", clean) and len(decls) >= 2:
                continue
            compact_sig = re.sub(r"\s+", " ", clean).strip()
            if len(compact_sig) > 120:
                compact_sig = compact_sig[:117] + "..."
            if compact_sig and compact_sig not in decls:
                decls.append(compact_sig)
                if len(decls) >= max_decls_per_file:
                    break
        if decls:
            results.append({"path": norm, "declarations": decls})
    return results


def _build_task_snapshot(repo: Path, task_id: str, plan: dict[str, Any] | None) -> dict[str, Any]:
    if not task_id or not plan:
        return {
            "task_id": "",
            "status": "NONE",
            "task_kind": "",
            "planning_depth": "",
            "requested_outcome": "",
            "approach": "",
            "expected_files": [],
            "expected_modules": [],
            "expected_surfaces": [],
            "modified_files": [],
            "interface_delta": [],
            "architecture_contract": {},
            "phases_summary": [],
            "plan_notes": [],
            "delivery_commit_sha": "",
        }
    tdir = task_dir(repo, task_id)
    p_state_file = tdir / "phase-state.json"
    completed_phases: set[str] = set()
    current_phase_id = ""
    if p_state_file.is_file():
        try:
            ps = read_json(p_state_file)
            completed_phases = set(ps.get("completed_phases") or [])
            current_phase_id = str(ps.get("current_phase_id") or "")
        except (OSError, ValueError, ValidationError):
            pass

    phases_summary = []
    for ph in plan.get("phases") or []:
        if isinstance(ph, dict) and ph.get("id"):
            pid = str(ph["id"])
            phases_summary.append({
                "id": pid,
                "title": str(ph.get("title") or ph.get("description") or pid),
                "completed": pid in completed_phases,
                "active": pid == current_phase_id,
                "expected_files": list(ph.get("expected_files") or []),
            })

    notes_list: list[str] = []
    try:
        from plan_notes import load_plan_notes
        for n in load_plan_notes(tdir, plan):
            txt = str((n or {}).get("text") or "").strip()
            if txt and txt not in notes_list:
                notes_list.append(txt)
    except (ImportError, OSError, ValueError):
        pass

    arch = plan.get("architecture_contract") or {}
    compact_arch = {
        k: arch[k]
        for k in ("mode", "target_scope", "target_family_id", "source_set", "module")
        if k in arch and arch[k] not in (None, "")
    } if isinstance(arch, dict) else {}

    modified_files = _collect_task_modified_files(repo, task_id, plan)
    interface_delta = _extract_interface_delta(repo, modified_files)

    return {
        "task_id": task_id,
        "status": str(plan.get("status") or ""),
        "task_kind": str(plan.get("task_kind") or "AUTO"),
        "planning_depth": str(plan.get("planning_depth") or "BOUNDED"),
        "requested_outcome": str(redact(plan.get("requested_outcome") or "")),
        "approach": str(redact(plan.get("approach") or "")),
        "expected_files": [str(f) for f in (plan.get("expected_files") or []) if str(f).strip()],
        "expected_modules": [str(m) for m in (plan.get("expected_modules") or []) if str(m).strip()],
        "expected_surfaces": [str(s) for s in (plan.get("expected_surfaces") or []) if str(s).strip()],
        "modified_files": modified_files,
        "interface_delta": interface_delta,
        "architecture_contract": compact_arch,
        "phases_summary": phases_summary,
        "plan_notes": notes_list,
        "delivery_commit_sha": str(plan.get("delivery_commit_sha") or ""),
        "plan_sha256": str(plan.get("plan_sha256") or ""),
    }


def _bridge_canonical_fields(payload: dict[str, Any]) -> dict[str, Any]:
    excluded = {"bridge_sha256", "consumed_at", "consumed_count", "consumed_by_host", "pending_bridges_count"}
    return {k: v for k, v in payload.items() if k not in excluded}


def _load_bridge_queue(repo: Path) -> list[dict[str, Any]]:
    """Load the multi-bridge queue from `.agents/state/task-bridges.json`, falling back to `task-bridge.json`."""
    q_path = _bridges_queue_file(repo)
    bridges: list[dict[str, Any]] = []
    if q_path.is_file():
        try:
            raw = read_json(q_path)
            if isinstance(raw, dict) and isinstance(raw.get("bridges"), list):
                bridges = [b for b in raw["bridges"] if isinstance(b, dict) and b.get("bridge_id")]
        except (OSError, ValueError, ValidationError):
            bridges = []

    single_path = _bridge_file(repo)
    if single_path.is_file():
        try:
            single = read_json(single_path)
            if isinstance(single, dict) and single.get("bridge_id"):
                existing_ids = {str(b.get("bridge_id")) for b in bridges}
                if str(single["bridge_id"]) not in existing_ids:
                    bridges.append(single)
                else:
                    bridges = [single if str(b.get("bridge_id")) == str(single["bridge_id"]) else b for b in bridges]
        except (OSError, ValueError, ValidationError):
            pass
    return bridges


def _save_bridge_queue(repo: Path, bridges: list[dict[str, Any]]) -> None:
    """Persist the multi-bridge queue and sync `.agents/state/task-bridge.json` to the preferred/latest entry."""
    q_path = _bridges_queue_file(repo)
    single_path = _bridge_file(repo)
    if not bridges:
        q_path.unlink(missing_ok=True)
        single_path.unlink(missing_ok=True)
        return
    q_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(q_path, {"schema_version": BRIDGE_SCHEMA_VERSION, "bridges": bridges})
    unconsumed = [b for b in bridges if int(b.get("consumed_count") or 0) == 0]
    latest = unconsumed[-1] if unconsumed else bridges[-1]
    atomic_write_json(single_path, latest)


def _live_tasks_summary(repo: Path) -> list[dict[str, str]]:
    """Return a compact list of all live non-terminal tasks in the repository."""
    tasks_dir = state_root(repo) / "tasks"
    if not tasks_dir.is_dir():
        return []
    live_states = {"AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"}
    items: list[dict[str, str]] = []
    for sub in sorted(tasks_dir.iterdir()):
        if not sub.is_dir():
            continue
        p_file = sub / "plan.json"
        if not p_file.is_file():
            continue
        try:
            plan = read_json(p_file)
            if not isinstance(plan, dict):
                continue
            st = str(plan.get("status") or "").upper()
            if st in live_states:
                tid = str(plan.get("task_id") or sub.name)
                items.append({
                    "task_id": tid,
                    "status": st,
                    "requested_outcome": str(redact(plan.get("requested_outcome") or ""))[:100],
                })
        except (OSError, ValueError, ValidationError):
            continue
    return items


def _active_candidate_bridges(repo: Path, queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return unconsumed bridges excluding cancelled tasks, plus synthetic entries for unbridged sibling live tasks when >1 candidate exists."""
    valid_unconsumed: list[dict[str, Any]] = []
    covered_task_ids: set[str] = set()
    for b in queue:
        if not isinstance(b, dict) or int(b.get("consumed_count") or 0) > 0:
            continue
        snap = b.get("task_snapshot") or {}
        tid = str(snap.get("task_id") or "").strip()
        mode = str(b.get("mode") or "FOLLOW_UP_TASK").upper()
        if tid:
            covered_task_ids.add(tid)
            p_file = state_root(repo) / "tasks" / tid / "plan.json"
            if p_file.is_file():
                try:
                    live_p = read_json(p_file)
                    if isinstance(live_p, dict):
                        live_st = str(live_p.get("status") or "").upper()
                        # Drop MID_TASK_HANDOFF bridges for tasks that were cancelled after the bridge was saved
                        if live_st == "CANCELLED" and mode == "MID_TASK_HANDOFF":
                            continue
                except (OSError, ValueError, ValidationError):
                    pass
        valid_unconsumed.append(b)
    return valid_unconsumed


def save_task_bridge(args: argparse.Namespace) -> dict[str, Any]:
    """Save a Task-to-Task or Mid-Task Context Bridge artifact for instant pickup in a new chat."""
    repo = Path(getattr(args, "repo", ".") or ".").resolve()
    explicit_tid = str(getattr(args, "task_id", "") or "").strip()
    task_id, plan = _resolve_target_task(repo, explicit_tid)

    raw_mode = str(getattr(args, "mode", "auto") or "auto").strip().lower()
    next_outcome = str(getattr(args, "next_outcome", "") or "").strip()
    custom_summary = str(getattr(args, "summary", "") or "").strip()
    raw_extra_files = str(getattr(args, "expected_files", "") or "").strip()
    extra_files = [
        str(f).replace("\\", "/").strip("/")
        for f in raw_extra_files.split(",")
        if str(f).replace("\\", "/").strip("/")
    ]

    task_status = str((plan or {}).get("status") or "NONE").upper()
    if raw_mode in ("follow-up", "followup", "follow_up", "follow_up_task"):
        mode = "FOLLOW_UP_TASK"
    elif raw_mode in ("mid-task", "midtask", "mid_task", "mid_task_handoff"):
        mode = "MID_TASK_HANDOFF"
    else:
        if next_outcome or task_status in {"DELIVERED", "READY_FOR_DELIVERY", "CANCELLED", "NONE"}:
            mode = "FOLLOW_UP_TASK"
        else:
            mode = "MID_TASK_HANDOFF"

    if mode == "MID_TASK_HANDOFF" and not task_id:
        raise ValidationError("MID_TASK_HANDOFF requires an active task; pass --task-id <id> or use --mode follow-up.")

    snapshot = _build_task_snapshot(repo, task_id, plan)

    disc_paths: list[str] = []
    disc_modules: list[str] = []
    disc_symbols: list[str] = []
    try:
        from discovery_receipt import DISCOVERY_CACHE_SUBDIR
        latest_disc_file = repo / DISCOVERY_CACHE_SUBDIR / "latest-discovery.json"
        if latest_disc_file.is_file():
            latest_disc = read_json(latest_disc_file)
            if isinstance(latest_disc, dict):
                disc_paths = [str(p) for p in (latest_disc.get("resolved_paths") or []) if str(p).strip()]
                disc_modules = [str(m) for m in (latest_disc.get("resolved_modules") or []) if str(m).strip()]
                disc_symbols = [str(s) for s in (latest_disc.get("resolved_symbols") or []) if str(s).strip()]
    except (ImportError, OSError, ValueError, ValidationError):
        pass

    merged_paths: list[str] = []
    for candidate in [*extra_files, *(snapshot.get("modified_files") or []), *(snapshot.get("expected_files") or []), *disc_paths]:
        norm = str(candidate).replace("\\", "/").strip().strip("/")
        if norm and not norm.startswith((".agents/", ".harness-")) and norm not in merged_paths:
            merged_paths.append(norm)

    merged_modules: list[str] = []
    for mod in [*(snapshot.get("expected_modules") or []), *disc_modules]:
        m_str = str(mod).strip()
        if m_str and m_str not in merged_modules:
            merged_modules.append(m_str)

    target_scope = str((snapshot.get("architecture_contract") or {}).get("target_scope") or "").strip()
    if not target_scope and merged_paths:
        target_scope = str(Path(merged_paths[0]).parent.as_posix())
        if target_scope == ".":
            target_scope = merged_paths[0]

    if not custom_summary:
        parts: list[str] = []
        if snapshot.get("task_id"):
            parts.append(f"Task '{snapshot['task_id']}' ({snapshot.get('status') or 'UNKNOWN'}): {snapshot.get('requested_outcome') or 'no outcome recorded'}.")
        if snapshot.get("approach"):
            parts.append(f"Approach: {snapshot['approach']}")
        if merged_paths:
            parts.append(f"Key files ({len(merged_paths)}): {', '.join(merged_paths[:6])}" + (f" (+{len(merged_paths) - 6} more)" if len(merged_paths) > 6 else "") + ".")
        if snapshot.get("plan_notes"):
            parts.append("Refinements: " + "; ".join(snapshot["plan_notes"][:3]))
        custom_summary = " ".join(parts) if parts else "Context bridge saved for new conversation."

    from review_sources import detected_current_host
    source_host = str(getattr(args, "host", None) or detected_current_host() or "antigravity").strip().lower()
    source_session_id = ""
    if task_id:
        try:
            from host_continuation import load_session
            sess = load_session(repo, task_id)
            if isinstance(sess, dict):
                source_session_id = str(sess.get("session_id") or "")
        except (ImportError, OSError, ValueError, ValidationError):
            pass

    now_iso = utc_now()
    health = measure_conversation_health(repo)
    seed_hash = canonical_sha256({
        "task_id": task_id,
        "mode": mode,
        "created_at": now_iso,
        "next_outcome": next_outcome,
        "summary": custom_summary,
    })[:12]
    bridge_id = f"bridge-{seed_hash}"

    bootstrap_prompt = "python .agents/harness.py task bridge"
    clear_cmd = "python .agents/harness.py task bridge --clear"
    if next_outcome:
        copy_prompt = f"Run `{bootstrap_prompt}` and start the follow-up task: {redact(next_outcome)}"
    elif task_id:
        copy_prompt = f"Run `{bootstrap_prompt}` and continue from task '{task_id}'."
    else:
        copy_prompt = f"Run `{bootstrap_prompt}` and continue from the bridged context."
    optional_notice = (
        "Continuation in a new chat is 100% optional: if you open a new chat for a different topic, "
        "simply state your unrelated request and this bridge will stay untouched in the background "
        f"(or run `{clear_cmd}` to discard it)."
    )
    handoff_card = (
        f"BRIDGE_HANDOFF_CARD_BEGIN\n"
        f"- Bridge ID: `{bridge_id}` ({mode})\n"
        f"- To continue in a new chat (copy-paste): `{copy_prompt}`\n"
        f"- Non-forced: {optional_notice}\n"
        f"BRIDGE_HANDOFF_CARD_END"
    )
    payload: dict[str, Any] = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "status": "BRIDGE_SAVED",
        "bridge_id": bridge_id,
        "created_at": now_iso,
        "mode": mode,
        "repository": repository_identity(repo),
        "source_host": source_host,
        "source_session_id": source_session_id,
        "source_stopped": True,
        "source_conversation": health,
        "task_snapshot": snapshot,
        "discovery_seed": {
            "resolved_paths": merged_paths,
            "resolved_modules": merged_modules,
            "resolved_symbols": disc_symbols,
            "target_scope": target_scope,
        },
        "context_summary": str(redact(custom_summary)),
        "next_outcome": str(redact(next_outcome)),
        "new_chat_command": bootstrap_prompt,
        "clear_command": clear_cmd,
        "new_chat_prompt": copy_prompt,
        "optional_notice": optional_notice,
        "handoff_card": handoff_card,
    }
    payload["bridge_sha256"] = canonical_sha256(_bridge_canonical_fields(payload))

    queue = _load_bridge_queue(repo)
    # Replace an existing unconsumed entry for the same (task_id, mode, next_outcome), otherwise append
    replaced = False
    new_queue: list[dict[str, Any]] = []
    for item in queue:
        item_tid = str((item.get("task_snapshot") or {}).get("task_id") or "")
        item_mode = str(item.get("mode") or "")
        item_next = str(item.get("next_outcome") or "")
        if int(item.get("consumed_count") or 0) == 0 and item_tid == task_id and item_mode == mode and item_next == str(redact(next_outcome)):
            new_queue.append(payload)
            replaced = True
        else:
            new_queue.append(item)
    if not replaced:
        new_queue.append(payload)
    # Keep at most 10 entries in the queue
    new_queue = new_queue[-10:]
    _save_bridge_queue(repo, new_queue)

    hist_dir = _bridge_history_dir(repo)
    hist_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(hist_dir / f"{bridge_id}.json", payload)

    unconsumed_count = len([b for b in new_queue if int(b.get("consumed_count") or 0) == 0])
    return {**payload, "pending_bridges_count": unconsumed_count}


def _mint_bridge_discovery_receipt(repo: Path, bridge: dict[str, Any]) -> dict[str, Any]:
    """Mint and save a fresh conversation-local Discovery Receipt from the bridge's file and module scope."""
    from discovery_receipt import (
        compute_allowed_search_roots,
        create_discovery_receipt,
        current_graph_fingerprint,
        save_discovery_receipt,
    )

    seed = bridge.get("discovery_seed") or {}
    snap = bridge.get("task_snapshot") or {}
    raw_paths = list(seed.get("resolved_paths") or []) + list(snap.get("modified_files") or []) + list(snap.get("expected_files") or [])
    existing_paths: list[str] = []
    all_norm_paths: list[str] = []
    for p in raw_paths:
        norm = str(p).replace("\\", "/").strip().strip("/")
        if not norm or norm.startswith((".agents/", ".harness-")):
            continue
        if norm not in all_norm_paths:
            all_norm_paths.append(norm)
        if (repo / norm).is_file() and norm not in existing_paths:
            existing_paths.append(norm)

    modules = [str(m).strip() for m in (seed.get("resolved_modules") or snap.get("expected_modules") or []) if str(m).strip()]
    symbols = [str(s).strip() for s in (seed.get("resolved_symbols") or []) if str(s).strip()]
    target_scope = str(seed.get("target_scope") or (snap.get("architecture_contract") or {}).get("target_scope") or "").replace("\\", "/").strip().strip("/")

    primary_target = existing_paths[0] if existing_paths else (target_scope or (all_norm_paths[0] if all_norm_paths else "bridge-scope"))
    graph_fp = current_graph_fingerprint(repo)

    allowed_roots = compute_allowed_search_roots(existing_paths or all_norm_paths, modules, include_module_roots=bool(modules))
    for p in existing_paths or all_norm_paths:
        parent = str(Path(p).parent.as_posix()).strip().strip("/")
        if parent and parent != "." and parent not in allowed_roots:
            allowed_roots.append(parent)
    if target_scope and target_scope != "." and target_scope not in allowed_roots:
        allowed_roots.append(target_scope)

    resolved_for_receipt = existing_paths if existing_paths else all_norm_paths
    receipt = create_discovery_receipt(
        mode="task_bridge",
        query_kind="bridge",
        query_value=primary_target,
        graph_fingerprint=graph_fp,
        resolved_modules=modules,
        resolved_paths=resolved_for_receipt,
        resolved_symbols=symbols,
        allowed_search_roots=sorted(set(allowed_roots)),
    )
    save_discovery_receipt(repo, receipt)

    # Also refresh .agents/cache/last-task-context.json so draft target fallback works immediately
    if resolved_for_receipt:
        last_ctx_file = repo / ".agents" / "cache" / "last-task-context.json"
        try:
            last_ctx_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(last_ctx_file, {
                "file": resolved_for_receipt[0],
                "timestamp": time.time(),
                "source": "task_bridge",
                "bridge_id": str(bridge.get("bridge_id") or ""),
            })
        except OSError:
            pass

    return receipt


def _suggest_followup_task_id(prev_task_id: str, next_outcome: str) -> str:
    if next_outcome:
        words = [w.lower() for w in re.findall(r"[a-zA-Z0-9]+", next_outcome) if len(w) >= 3][:4]
        if words:
            slug = "-".join(words)[:40].strip("-")
            if slug and re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,60}", slug):
                if slug != prev_task_id:
                    return slug
    if prev_task_id:
        base = re.sub(r"-followup(?:-\d+)?$", "", prev_task_id)
        return f"{base}-followup"
    return "followup-task"


def _select_bridge_from_queue(
    repo: Path,
    queue: list[dict[str, Any]],
    *,
    requested_bridge_id: str = "",
    requested_task_id: str = "",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Select the target bridge from the queue or return a structured disambiguation response when multiple unconsumed bridges exist."""
    req_bid = str(requested_bridge_id or "").strip()
    req_tid = str(requested_task_id or "").strip()
    if req_bid:
        for b in reversed(queue):
            if str(b.get("bridge_id") or "") == req_bid:
                return b, None
        raise ValidationError(f"TASK_BRIDGE_NOT_FOUND: No saved bridge with --bridge-id '{req_bid}' found.")
    if req_tid:
        # Prefer unconsumed matching task_id first, then any matching task_id
        matches = [b for b in queue if str((b.get("task_snapshot") or {}).get("task_id") or "") == req_tid]
        if matches:
            unconsumed_m = [b for b in matches if int(b.get("consumed_count") or 0) == 0]
            if len(unconsumed_m) == 1:
                return unconsumed_m[0], None
            if len(unconsumed_m) == 0:
                return matches[-1], None
            # Multiple unconsumed bridges share this task_id; fall through to disambiguation filtered to unconsumed_m
            queue = unconsumed_m
        else:
            raise ValidationError(f"TASK_BRIDGE_NOT_FOUND: No saved bridge for --task-id '{req_tid}' found.")

    unconsumed = _active_candidate_bridges(repo, queue)
    if len(unconsumed) == 1:
        return unconsumed[0], None
    if len(unconsumed) > 1:
        choices = []
        options_list = []
        bridged_tids: set[str] = set()
        for idx, b in enumerate(unconsumed, 1):
            bid = str(b.get("bridge_id") or "")
            b_mode = str(b.get("mode") or "FOLLOW_UP_TASK")
            b_snap = b.get("task_snapshot") or {}
            b_tid = str(b_snap.get("task_id") or "")
            if b_tid:
                bridged_tids.add(b_tid)
            b_next = str(b.get("next_outcome") or "")
            b_sum = str(b.get("context_summary") or "")
            label = f"{b_tid or bid} ({b_mode}): {b_next or b_sum[:70]}"
            cmd = f"python .agents/harness.py task bridge --bridge-id {bid}"
            choices.append({
                "bridge_id": bid,
                "task_id": b_tid,
                "mode": b_mode,
                "next_outcome": b_next,
                "context_summary": b_sum,
                "load_command": cmd,
                "clear_command": f"python .agents/harness.py task bridge --clear --bridge-id {bid}",
            })
            prefix = "(Recommended) " if idx == len(unconsumed) else ""
            options_list.append(f"{prefix}{label}")
        live_tasks = _live_tasks_summary(repo)
        for lt in live_tasks:
            lt_id = str(lt.get("task_id") or "")
            if lt_id and lt_id not in bridged_tids:
                options_list.append(f"Live task '{lt_id}' ({lt.get('status')}): {lt.get('requested_outcome', '')}")
        options_list.append("Start a new unrelated task (keep saved bridges untouched)")
        return None, {
            "status": "MULTIPLE_BRIDGES_PENDING",
            "pending_bridges_count": len(unconsumed),
            "pending_bridges": choices,
            "live_tasks": live_tasks,
            "next_action": {
                "code": "SELECT_PENDING_BRIDGE",
                "kind": "DEVELOPER_ACTION",
                "tool": "ask_question",
                "command": choices[-1]["load_command"],
                "blocking": True,
                "reason": (
                    f"There are {len(unconsumed)} unconsumed task bridges waiting in the queue. "
                    "Ask the developer via `ask_question` which bridged task they want to continue now (or if they are starting a new unrelated topic), "
                    "then run the corresponding `load_command` (`python .agents/harness.py task bridge --bridge-id <id>`)."
                ),
                "inputs": {
                    "pending_bridges": choices,
                    "suggested_options": options_list,
                },
                "instructions": (
                    "Invoke `ask_question` in the developer's language listing each pending bridge (its task/topic and mode) "
                    "plus an option for an unrelated request. Once chosen, run `python .agents/harness.py task bridge --bridge-id <id>`."
                ),
            },
        }
    return (queue[-1] if queue else None), None


def load_task_bridge(args: argparse.Namespace) -> dict[str, Any]:
    """Load the saved Task Bridge in a fresh conversation, minting a fresh Discovery Receipt and resuming/bridging."""
    repo = Path(getattr(args, "repo", ".") or ".").resolve()
    queue = _load_bridge_queue(repo)
    if not queue:
        raise ValidationError(
            "TASK_BRIDGE_NOT_FOUND: No saved task bridge exists at .agents/state/task-bridge.json. "
            "Save one first with `python .agents/harness.py task bridge --save`."
        )

    req_bid = str(getattr(args, "bridge_id", "") or "").strip()
    req_tid = str(getattr(args, "task_id", "") or "").strip()
    bridge, multi_resp = _select_bridge_from_queue(
        repo,
        queue,
        requested_bridge_id=req_bid,
        requested_task_id=req_tid,
    )
    if multi_resp is not None:
        return multi_resp
    if not isinstance(bridge, dict):
        raise ValidationError("TASK_BRIDGE_CORRUPTED: .agents/state/task-bridge.json is not a JSON object.")

    expected_sha = canonical_sha256(_bridge_canonical_fields(bridge))
    if str(bridge.get("bridge_sha256") or "") != expected_sha:
        raise ValidationError("TASK_BRIDGE_INTEGRITY_ERROR: bridge_sha256 mismatch in .agents/state/task-bridge.json.")

    live_repo = repository_identity(repo)
    bridged_repo = bridge.get("repository") or {}
    if bridged_repo.get("root_sha256") and live_repo.get("root_sha256") != bridged_repo.get("root_sha256"):
        raise ValidationError("TASK_BRIDGE_REPO_MISMATCH: task-bridge.json belongs to a different repository root.")

    # Clear any old snooze marker when loading a bridge in a new chat
    _snooze_file(repo).unlink(missing_ok=True)

    # Mint fresh Discovery Receipt so bounded searches and `workflow.py draft` work immediately in this conversation
    fresh_receipt = _mint_bridge_discovery_receipt(repo, bridge)

    snap = dict(bridge.get("task_snapshot") or {})
    task_id = str(snap.get("task_id") or "").strip()
    mode = str(bridge.get("mode") or "FOLLOW_UP_TASK").upper()

    from review_sources import detected_current_host
    target_host = str(getattr(args, "host", None) or detected_current_host() or bridge.get("source_host") or "antigravity").strip().lower()

    # Check live plan state if task_id exists
    live_plan: dict[str, Any] | None = None
    if task_id:
        p_file = state_root(repo) / "tasks" / task_id / "plan.json"
        if p_file.is_file():
            try:
                live_plan = read_json(p_file)
            except (OSError, ValueError, ValidationError):
                live_plan = None

    # Update consumption metadata on bridge and sync queue (excluded from bridge_sha256 so repeated loads remain idempotent)
    bridge["consumed_at"] = utc_now()
    bridge["consumed_count"] = int(bridge.get("consumed_count") or 0) + 1
    bridge["consumed_by_host"] = target_host
    updated_queue = [bridge if str(b.get("bridge_id")) == str(bridge.get("bridge_id")) else b for b in queue]
    try:
        _save_bridge_queue(repo, updated_queue)
        if not req_bid and not req_tid:
            atomic_write_json(_bridge_file(repo), bridge)
    except OSError:
        pass

    from host_continuation import CONTINUABLE_STATES, continue_task

    if mode == "MID_TASK_HANDOFF" and task_id and live_plan:
        live_status = str(live_plan.get("status") or "").upper()
        if live_status in CONTINUABLE_STATES:
            cont_res = continue_task(
                argparse.Namespace(
                    repo=str(repo),
                    task_id=task_id,
                    host=target_host,
                    source_stopped=True,
                    expect_session=None,
                )
            )
            return {
                "status": "BRIDGE_CONTINUED",
                "mode": "MID_TASK_HANDOFF",
                "bridge_id": bridge.get("bridge_id"),
                "task_id": task_id,
                "task_state": live_status,
                "host": cont_res.get("host"),
                "session_id": cont_res.get("session_id"),
                "enforcement_tier": cont_res.get("enforcement_tier"),
                "context_summary": bridge.get("context_summary", ""),
                "previous_task": _build_task_snapshot(repo, task_id, live_plan),
                "discovery_receipt": {
                    "id": fresh_receipt.get("id"),
                    "resolved_paths": fresh_receipt.get("resolved_paths", []),
                    "allowed_search_roots": fresh_receipt.get("allowed_search_roots", []),
                },
                "brief": cont_res.get("brief"),
                "next_action": cont_res.get("next_action"),
            }
        elif live_status == "AWAITING_DEVELOPER_APPROVAL":
            from workflow import resolve_next_action
            atomic_write_json(
                state_root(repo) / "active-task.json",
                {"task_id": task_id, "plan_path": str(state_root(repo) / "tasks" / task_id / "plan.json"), "updated_at": utc_now()},
            )
            next_act = resolve_next_action(repo, task_id, live_plan, host=target_host)
            return {
                "status": "BRIDGE_LOADED",
                "mode": "MID_TASK_HANDOFF",
                "bridge_id": bridge.get("bridge_id"),
                "task_id": task_id,
                "task_state": live_status,
                "host": target_host,
                "context_summary": bridge.get("context_summary", ""),
                "previous_task": _build_task_snapshot(repo, task_id, live_plan),
                "discovery_receipt": {
                    "id": fresh_receipt.get("id"),
                    "resolved_paths": fresh_receipt.get("resolved_paths", []),
                    "allowed_search_roots": fresh_receipt.get("allowed_search_roots", []),
                },
                "next_action": next_act,
            }

    # FOLLOW_UP_TASK mode (or terminal task)
    if task_id and live_plan and str(live_plan.get("status") or "") == "READY_FOR_DELIVERY":
        # If the developer already committed the previous task before opening the new chat, reconcile it to DELIVERED
        try:
            from workflow import reconcile_delivery
            reconciled_plan, rec_status = reconcile_delivery(repo, task_id)
            if reconciled_plan is not None:
                live_plan = reconciled_plan
        except (ImportError, OSError, ValueError, ValidationError):
            pass

    if task_id and live_plan:
        snap = _build_task_snapshot(repo, task_id, live_plan)

    next_outcome = str(bridge.get("next_outcome") or "").strip()
    suggested_id = _suggest_followup_task_id(task_id, next_outcome)
    bridged_files = list(fresh_receipt.get("resolved_paths") or snap.get("modified_files") or snap.get("expected_files") or [])
    files_arg = f' --expected-files "{",".join(bridged_files[:12])}"' if bridged_files else ""
    outcome_arg = next_outcome if next_outcome else "<follow-up outcome>"
    suggested_draft_cmd = (
        f'python .agents/harness.py task draft --task-id {suggested_id} '
        f'--outcome "{outcome_arg}"{files_arg} --approach "<approach>"'
    )

    if next_outcome:
        next_act = {
            "code": "DRAFT_BRIDGED_FOLLOWUP_TASK",
            "kind": "HARNESS_COMMAND",
            "command": suggested_draft_cmd,
            "blocking": False,
            "reason": (
                f"Bridged context from '{task_id or 'previous session'}' is loaded with a fresh Discovery Receipt "
                f"({fresh_receipt.get('id')}). Draft the follow-up task plan directly without re-running broad repository discovery."
            ),
            "inputs": {
                "previous_task_id": task_id,
                "suggested_task_id": suggested_id,
                "next_outcome": next_outcome,
                "bridged_files": bridged_files,
                "discovery_id": fresh_receipt.get("id"),
            },
            "expected": {"success_statuses": ["AWAITING_DEVELOPER_APPROVAL"]},
        }
    else:
        next_act = {
            "code": "AWAIT_FOLLOWUP_OUTCOME_OR_DRAFT",
            "kind": "MODEL_ACTION",
            "command": suggested_draft_cmd,
            "blocking": False,
            "reason": (
                f"Bridged context from '{task_id or 'previous session'}' is loaded with a fresh Discovery Receipt "
                f"({fresh_receipt.get('id')}). When the developer states the follow-up request, run `{suggested_draft_cmd}` directly."
            ),
            "inputs": {
                "previous_task_id": task_id,
                "suggested_task_id": suggested_id,
                "bridged_files": bridged_files,
                "discovery_id": fresh_receipt.get("id"),
            },
            "expected": {},
        }

    return {
        "status": "BRIDGE_LOADED",
        "mode": "FOLLOW_UP_TASK",
        "bridge_id": bridge.get("bridge_id"),
        "host": target_host,
        "previous_task": snap,
        "context_summary": bridge.get("context_summary", ""),
        "next_outcome": next_outcome,
        "discovery_receipt": {
            "id": fresh_receipt.get("id"),
            "resolved_paths": fresh_receipt.get("resolved_paths", []),
            "allowed_search_roots": fresh_receipt.get("allowed_search_roots", []),
        },
        "suggested_draft_command": suggested_draft_cmd,
        "next_action": next_act,
    }


def snooze_rotation(args: argparse.Namespace) -> dict[str, Any]:
    """Snooze context rotation advisories for the current conversation."""
    repo = Path(getattr(args, "repo", ".") or ".").resolve()
    snooze_steps = max(20, int(getattr(args, "snooze_steps", DEFAULT_SNOOZE_STEPS) or DEFAULT_SNOOZE_STEPS))
    health = measure_conversation_health(repo)
    cur_steps = int(health.get("steps") or 0)
    payload = {
        "status": "ROTATION_SNOOZED",
        "conversation_id": str(health.get("conversation_id") or ""),
        "snoozed_at": utc_now(),
        "snoozed_at_steps": cur_steps,
        "snooze_steps": snooze_steps,
        "snooze_until_steps": cur_steps + snooze_steps,
    }
    atomic_write_json(_snooze_file(repo), payload)
    return payload


def bridge_status(args: argparse.Namespace) -> dict[str, Any]:
    """Read-only inspection of conversation health, rotation advisory, and saved task bridge queue."""
    repo = Path(getattr(args, "repo", ".") or ".").resolve()
    explicit_tid = str(getattr(args, "task_id", "") or "").strip()
    task_id, plan = _resolve_target_task(repo, explicit_tid)
    health = measure_conversation_health(repo)
    snoozed, snooze_data = is_rotation_snoozed(repo, health)

    task_state = str((plan or {}).get("status") or "NONE").upper()
    checkpoint_kind = "FOLLOW_UP_BOUNDARY" if task_state in {"DELIVERED", "READY_FOR_DELIVERY", "CANCELLED", "NONE"} else "MID_TASK_CHECKPOINT"
    advisory = evaluate_rotation_advisory(repo, checkpoint_kind, task_id=task_id, plan=plan)

    queue = _load_bridge_queue(repo)
    pending_bridges: list[dict[str, Any]] = []
    for item in queue:
        pending_bridges.append({
            "bridge_id": item.get("bridge_id"),
            "mode": item.get("mode"),
            "created_at": item.get("created_at"),
            "task_id": (item.get("task_snapshot") or {}).get("task_id", ""),
            "next_outcome": item.get("next_outcome", ""),
            "consumed_at": item.get("consumed_at"),
            "consumed_count": item.get("consumed_count", 0),
        })
    unconsumed = [b for b in pending_bridges if int(b.get("consumed_count") or 0) == 0]
    saved_bridge: dict[str, Any] | None = unconsumed[-1] if unconsumed else (pending_bridges[-1] if pending_bridges else None)

    return {
        "status": "READY",
        "task_id": task_id,
        "task_state": task_state,
        "conversation_health": health,
        "snoozed": snoozed,
        "snooze": snooze_data if snoozed else None,
        "context_rotation": advisory,
        "saved_bridge": saved_bridge,
        "pending_bridges": unconsumed,
        "all_bridges": pending_bridges,
        "live_tasks": _live_tasks_summary(repo),
    }


def clear_task_bridge(args: argparse.Namespace) -> dict[str, Any]:
    """Explicitly clear one or all saved bridges while keeping `.agents/state/bridge-history/<bridge_id>.json` archived."""
    repo = Path(getattr(args, "repo", ".") or ".").resolve()
    req_bid = str(getattr(args, "bridge_id", "") or "").strip()
    req_tid = str(getattr(args, "task_id", "") or "").strip()
    clear_all = bool(getattr(args, "all", False))
    queue = _load_bridge_queue(repo)
    if not queue:
        _bridge_file(repo).unlink(missing_ok=True)
        _bridges_queue_file(repo).unlink(missing_ok=True)
        return {
            "status": "BRIDGE_CLEARED",
            "bridge_id": "",
            "cleared_ids": [],
            "remaining_count": 0,
            "archived_in_history": False,
        }

    if clear_all or (not req_bid and not req_tid and len([b for b in queue if int(b.get("consumed_count") or 0) == 0]) <= 1):
        cleared_ids = [str(b.get("bridge_id") or "") for b in queue if b.get("bridge_id")]
        primary_id = cleared_ids[-1] if cleared_ids else ""
        _save_bridge_queue(repo, [])
        return {
            "status": "BRIDGE_CLEARED",
            "bridge_id": primary_id,
            "cleared_ids": cleared_ids,
            "remaining_count": 0,
            "archived_in_history": bool(primary_id and (_bridge_history_dir(repo) / f"{primary_id}.json").is_file()),
        }

    # Selective clear when --bridge-id or --task-id is passed (or multiple bridges exist and no --all was passed)
    cleared_ids = []
    remaining: list[dict[str, Any]] = []
    target_id_to_remove = req_bid
    if not target_id_to_remove and not req_tid:
        # Remove only the most recent unconsumed bridge
        unconsumed = [b for b in queue if int(b.get("consumed_count") or 0) == 0]
        target_id_to_remove = str((unconsumed[-1] if unconsumed else queue[-1]).get("bridge_id") or "")

    for b in queue:
        bid = str(b.get("bridge_id") or "")
        btid = str((b.get("task_snapshot") or {}).get("task_id") or "")
        if (target_id_to_remove and bid == target_id_to_remove) or (req_tid and btid == req_tid):
            cleared_ids.append(bid)
        else:
            remaining.append(b)

    _save_bridge_queue(repo, remaining)
    primary_id = cleared_ids[-1] if cleared_ids else ""
    return {
        "status": "BRIDGE_CLEARED",
        "bridge_id": primary_id,
        "cleared_ids": cleared_ids,
        "remaining_count": len([b for b in remaining if int(b.get("consumed_count") or 0) == 0]),
        "archived_in_history": bool(primary_id and (_bridge_history_dir(repo) / f"{primary_id}.json").is_file()),
    }


def pending_bridge_reminder(repo: Path) -> str:
    """Return a concise, strictly intent-conditional reminder when one or more unconsumed bridges exist."""
    try:
        queue = _load_bridge_queue(repo)
        unconsumed = _active_candidate_bridges(repo, queue)
        if not unconsumed:
            return ""
        live_tasks = _live_tasks_summary(repo)
        bridged_tids = {str((b.get("task_snapshot") or {}).get("task_id") or "") for b in unconsumed}
        extra_live = [lt for lt in live_tasks if lt.get("task_id") and lt.get("task_id") not in bridged_tids]
        extra_live_str = ", ".join(f"{lt.get('task_id')} [{lt.get('status')}]" for lt in extra_live[:3])
        extra_live_note = (
            f" (Also live in worktree: {extra_live_str}; use `task switch --task-id <id>` to focus.)"
            if extra_live else ""
        )
        if len(unconsumed) == 1 and not extra_live:
            bridge = unconsumed[0]
            b_id = str(bridge.get("bridge_id") or "bridge")
            mode = str(bridge.get("mode") or "FOLLOW_UP_TASK")
            snap = bridge.get("task_snapshot") or {}
            tid = str(snap.get("task_id") or "").strip()
            next_out = str(bridge.get("next_outcome") or "").strip()
            topic = f"'{next_out[:60]}'" if next_out else (f"task '{tid}'" if tid else "previous session")
            return (
                f" [Pending Task Bridge ({b_id}, mode={mode}, topic={topic}): "
                "OPTIONAL & INTENT-CONDITIONAL — If the developer's message asks to continue previous work or start the bridged follow-up, "
                "run `python .agents/harness.py task bridge` automatically. "
                "If the developer is asking about a DIFFERENT or UNRELATED topic, address their request directly without running or consuming `task bridge` "
                "(leave `task-bridge.json` intact in the background, or run `python .agents/harness.py task bridge --clear` only if they ask to discard it).]"
            )
        items_desc = []
        for b in unconsumed[:4]:
            bid = str(b.get("bridge_id") or "")
            bmode = str(b.get("mode") or "FOLLOW_UP_TASK")
            btid = str((b.get("task_snapshot") or {}).get("task_id") or "")
            bnext = str(b.get("next_outcome") or "").strip()
            btopic = bnext[:40] if bnext else (btid or bid)
            items_desc.append(f"{bid} ({bmode}: '{btopic}')")
        joined = "; ".join(items_desc)
        return (
            f" [Pending Task Bridges ({len(unconsumed)} waiting: {joined}){extra_live_note}: "
            "OPTIONAL & INTENT-CONDITIONAL — If the developer names a specific bridged task/topic, run `python .agents/harness.py task bridge --bridge-id <id>` (or `--task-id <id>`) for that bridge only. "
            "If the developer generally asks to continue without specifying which one, run `python .agents/harness.py task bridge` and ask via `ask_question` (`SELECT_PENDING_BRIDGE`). "
            "If the developer is asking about a DIFFERENT or UNRELATED topic, address their request directly without running or consuming any bridge.]"
        )
    except (OSError, ValueError, ValidationError):
        return ""


def cmd_task_bridge(args: argparse.Namespace) -> dict[str, Any]:
    """Entry point for `python .agents/harness.py task bridge`."""
    if getattr(args, "clear", False):
        return clear_task_bridge(args)
    if getattr(args, "snooze", False):
        return snooze_rotation(args)
    if getattr(args, "status", False):
        return bridge_status(args)
    if getattr(args, "save", False):
        return save_task_bridge(args)
    return load_task_bridge(args)
