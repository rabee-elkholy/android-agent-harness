"""Antigravity reviewer identity and lifecycle observations behind the host boundary.

Observations never certify a verdict, launch a replacement, or spend review calls.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from _vnext_common import ValidationError, atomic_write_json, read_json, redact_text, state_root, task_dir, utc_now
from antigravity_runtime import resolve_transcript
from evidence_store import StateLock


def active_reviews(repo: Path):
    from phase_review import phase_run_file, phase_ledger_file
    for plan_file in (state_root(repo) / "tasks").glob("*/plan.json"):
        plan = read_json(plan_file)
        tdir = plan_file.parent
        if plan.get("status") == "VERIFYING" and (tdir / "current-run.json").is_file():
            run = read_json(tdir / "current-run.json")
            yield run, tdir / "review-execution" / str(run["run_id"]) / "ledger.json"
        elif plan.get("status") == "IMPLEMENTING" and (tdir / "phase-state.json").is_file():
            phase = str(read_json(tdir / "phase-state.json").get("current_phase_id") or "")
            path = phase_run_file(tdir, phase)
            if path.is_file():
                yield read_json(path), phase_ledger_file(tdir, phase)


def _steps(path: Path) -> list[dict]:
    # Transcript content is inspected only at its canonical trusted host location.
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValidationError("reviewer transcript exceeds bounded inspection size")
    raw = path.read_text(encoding="utf-8")
    rows = []
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            if index == len(lines) - 1 and not raw.endswith("\n"):
                break  # The host is still appending this line; it proves nothing yet.
            raise ValidationError("invalid reviewer host transcript")
    if any(not isinstance(row, dict) for row in rows):
        raise ValidationError("invalid reviewer host transcript")
    return rows


def _load_ledger(run: dict, path: Path) -> dict:
    if run.get("phase_id"):
        from phase_review import load_phase_ledger
        ok, reason, ledger = load_phase_ledger(path.parents[3], run["phase_id"], expected_run_id=run["phase_review_run_id"],
                                              expected_task_id=run["task_id"], expected_reviewers=run["selected_reviewers"])
        if not ok:
            raise ValidationError(f"reviewer identity requires a valid phase ledger: {reason}")
        return ledger
    from review_orchestrator import load_ledger
    ledger = load_ledger(path.parents[2], run["run_id"])
    if ledger.get("task_id") != run["task_id"]:
        raise ValidationError("reviewer ledger task identity mismatch")
    return ledger


def reviewer_context(repo: Path, execution_id: str, *, bind: bool = False) -> dict | None:
    transcript = resolve_transcript(execution_id)
    rows = _steps(transcript) if transcript is not None else []
    messages = [str(r.get("content") or "") for r in rows
                if r.get("source") == "SYSTEM_SDK" and r.get("type") == "SYSTEM_MESSAGE"][:8]
    pending_review = False
    from review_execution import pointer_matches
    for run, ledger_path in active_reviews(repo):
        if run.get("review_host") != "antigravity" or not ledger_path.is_file():
            continue
        ledger = _load_ledger(run, ledger_path)
        pending_review = pending_review or any(e.get("state") in {"DISPATCHED", "PROTOCOL_RETRY_REQUIRED"} for e in ledger.get("reviewers", {}).values())
        for role, entry in ledger.get("reviewers", {}).items():
            if entry.get("state") not in {"DISPATCHED", "PROTOCOL_RETRY_REQUIRED"}:
                continue
            brief_path = (run.get("briefs") or {}).get(role) or entry.get("brief")
            if not brief_path and run.get("run_id"):
                # Final briefs live in the execution profile, rather than the run metadata.
                from review_execution import resolve_execution_profile
                brief_path = resolve_execution_profile(repo, run["task_id"], "antigravity")["reviewers"][role]["brief_path"]
            if not brief_path or not Path(brief_path).is_file():
                continue
            expected = Path(brief_path).read_text(encoding="utf-8").replace("\r\n", "\n").strip()
            for content in messages:
                message = re.search(r'sender=([A-Za-z0-9_-]+) priority=MESSAGE_PRIORITY_HIGH content=([\s\S]+?)\n</SYSTEM_MESSAGE>', content)
                if not message:
                    continue
                prompt = message[2].replace("\r\n", "\n").strip()
                if prompt != expected and not pointer_matches(prompt, role, str(brief_path), expected):
                    continue
                if entry.get("execution_id") not in (None, "", execution_id):
                    raise ValidationError("reviewer execution identity conflicts with its bound receipt")
                context = {"run": run, "ledger_path": ledger_path, "role": role,
                           "execution_id": execution_id, "parent_execution_id": message[1]}
                if bind:
                    with StateLock(state_root(repo)):
                        current = _load_ledger(run, ledger_path)
                        current_entry = current["reviewers"][role]
                        if current_entry.get("execution_id") not in (None, "", execution_id):
                            raise ValidationError("reviewer execution is already bound")
                        if current_entry.get("execution_id") != execution_id or current_entry.get("parent_execution_id") != message[1]:
                            current_entry.update(execution_id=execution_id, parent_execution_id=message[1])
                            _save_ledger(ledger_path, current)
                return context
    if pending_review and not any(r.get("source") == "USER_EXPLICIT" and r.get("type") == "USER_INPUT" for r in rows[:8]):
        # Missing or stale reviewer transcripts cannot grant a general shell.
        # Main conversations have a native explicit-user origin; unbound child
        # actors stay read-only until their exact dispatched brief can be proved.
        return {"unverified_reviewer": True}
    return None


def _save_ledger(path: Path, ledger: dict) -> None:
    if "ledger_sha256" in ledger:
        from phase_review import compute_ledger_sha
        ledger["ledger_sha256"] = compute_ledger_sha(ledger)
    atomic_write_json(path, ledger)


def cancellation(entry: dict) -> str | None:
    parent = resolve_transcript(str(entry.get("parent_execution_id") or ""))
    execution_id = str(entry.get("execution_id") or "")
    if parent is None or not execution_id:
        return None
    latest = None
    for row in _steps(parent):
        content = str(row.get("content") or "")
        if row.get("source") != "SYSTEM_SDK" or row.get("type") != "SYSTEM_MESSAGE":
            continue
        if f'Subagent "{execution_id}" has been explicitly canceled by the user' in content and 'sender=system ' in content:
            stamp = re.search(r"timestamp=([^\s]+)", content)
            latest = stamp[1] if stamp else str(row.get("created_at") or "")
    return latest


def lifecycle_action(repo: Path, run: dict, reviewers: dict) -> dict | None:
    if run.get("review_host") != "antigravity":
        return None
    for role, entry in reviewers.items():
        if entry.get("state") not in {"DISPATCHED", "PROTOCOL_RETRY_REQUIRED"}:
            continue
        cancelled_at = cancellation(entry)
        if not cancelled_at:
            continue
        authority = entry.get("resume_authority") or {}
        inputs = {"task_id": run["task_id"], "phase_id": run.get("phase_id", ""), "reviewer": role,
                  "execution_id": entry["execution_id"], "cancelled_at": cancelled_at}
        if authority.get("cancelled_at") == cancelled_at:
            if authority.get("last_error"):
                return {"code": "REVIEWER_RESUME_ENV_BLOCKED", "kind": "HARNESS_DIAGNOSTIC", "blocking": True,
                        "command": "", "reason": f"Resuming {role} failed in the host: {authority['last_error']}. Resolve the host failure, then repeat the same authorized review resume command.",
                        "inputs": inputs, "expected": {}}
            if authority.get("dispatched_at"):
                continue
            prompt = "Resume this same review execution and finish the original brief. Preserve its task, run and package identity."
            return {"code": "RESUME_REVIEWER", "kind": "HOST_ACTION", "blocking": True,
                    "command": "send_message", "recipient": entry["execution_id"], "message": prompt,
                    "reason": f"The developer authorized resuming {role} in its existing execution.",
                    "inputs": {**inputs, "recipient": entry["execution_id"], "message": prompt,
                               "send_message": {"recipient": entry["execution_id"], "prompt": prompt}}, "expected": {}}
        command = f'python .agents/harness.py review resume --task-id {run["task_id"]} --reviewer {role}'
        if run.get("phase_id"):
            command += f' --phase-id {run["phase_id"]}'
        command += ' --source conversation --proof-reference "<developer resume request>"'
        return {"code": "REVIEWER_CANCELLED", "kind": "DEVELOPER_ACTION", "blocking": True,
                "command": command, "reason": f"The developer cancelled {role}; explicit resume authority is required. No replacement or extra call is authorized.",
                "inputs": inputs, "expected": {}}
    # A finished native reply is ready for ingestion, not an endless WAIT. The
    # existing completion command still validates protocol, snapshot and model.
    for role, entry in reviewers.items():
        if entry.get("state") != "DISPATCHED" or not entry.get("execution_id"):
            continue
        transcript = resolve_transcript(entry["execution_id"])
        if transcript is None:
            continue
        model_steps = [r for r in _steps(transcript) if r.get("source") == "MODEL" and r.get("type") == "PLANNER_RESPONSE"]
        last = model_steps[-1] if model_steps else {}
        if last.get("content") and not last.get("tool_calls"):
            if run.get("phase_id"):
                command = f"python .agents/harness.py phase-review complete --task-id {run['task_id']} --phase-id {run['phase_id']} --reviewer {role} --execution-id {entry['execution_id']} --host antigravity"
            else:
                command = f"python .agents/harness.py review complete --task-id {run['task_id']} --reviewer {role} --execution-id {entry['execution_id']} --host antigravity"
            return {"code": "COMPLETE_REVIEWER", "kind": "HARNESS_COMMAND", "blocking": True, "command": command,
                    "reason": f"Native reviewer {role} returned a reply; validate and ingest that same execution.",
                    "inputs": {"task_id": run["task_id"], "reviewer": role, "execution_id": entry["execution_id"]}, "expected": {}}
    return None


def authorize_resume(repo: Path, task: str, role: str, phase: str, source: str, proof: str) -> dict:
    if source != "conversation" or not proof.strip():
        raise ValidationError("reviewer resume requires an explicit conversation decision and proof-reference")
    with StateLock(state_root(repo)):
        for run, path in active_reviews(repo):
            if run.get("task_id") != task or str(run.get("phase_id") or "") != phase or not path.is_file():
                continue
            ledger = _load_ledger(run, path)
            entry = ledger.get("reviewers", {}).get(role)
            if not entry or entry.get("state") not in {"DISPATCHED", "PROTOCOL_RETRY_REQUIRED"}:
                raise ValidationError("only a cancelled dispatched execution can be resumed")
            cancelled_at = cancellation(entry)
            if not cancelled_at:
                raise ValidationError("no native user cancellation was observed for this execution")
            old = entry.get("resume_authority") or {}
            if old.get("cancelled_at") != cancelled_at or old.get("last_error"):
                entry["resume_authority"] = {"cancelled_at": cancelled_at, "source": source,
                                             "proof_reference": proof.strip(), "recorded_at": utc_now()}
                _save_ledger(path, ledger)
            return {"task_id": task, "reviewer": role, "execution_id": entry["execution_id"], "status": "RESUME_AUTHORIZED"}
    raise ValidationError("active reviewer execution not found")


def mark_resume_dispatched(repo: Path, task: str, role: str, execution: str) -> None:
    with StateLock(state_root(repo)):
        for run, path in active_reviews(repo):
            if run.get("task_id") == task and path.is_file():
                ledger = _load_ledger(run, path)
                entry = ledger.get("reviewers", {}).get(role, {})
                if entry.get("execution_id") == execution and entry.get("resume_authority"):
                    entry["resume_authority"]["dispatched_at"] = utc_now()
                    _save_ledger(path, ledger)
                    return
    raise ValidationError("reviewer resume identity no longer matches")


def mark_resume_failed(repo: Path, execution: str, error: str) -> None:
    with StateLock(state_root(repo)):
        for run, path in active_reviews(repo):
            if not path.is_file():
                continue
            ledger = _load_ledger(run, path)
            for entry in ledger.get("reviewers", {}).values():
                authority = entry.get("resume_authority") or {}
                if entry.get("execution_id") == execution and authority.get("dispatched_at"):
                    authority["last_error"] = redact_text(str(error).strip())[:500]
                    _save_ledger(path, ledger)
                    return


def discovery_command_allowed(command: str) -> bool:
    """The reviewer shell capability is restricted to two public discovery parsers."""
    import shlex
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if len(tokens) < 5 or tokens[:2] not in (["python", ".agents/harness.py"], ["py", ".agents/harness.py"]):
        return False
    action = tokens[2]
    valid = {"graph": {"--find", "--feature"}, "task-context": {"--file", "--symbol"}}.get(action)
    if valid is None:
        return False
    index, count = 3, 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            index += 1
        elif token in valid and index + 1 < len(tokens):
            value = tokens[index + 1]
            if not value or value.startswith("-") or re.search(r"[;&|`$\r\n]", value):
                return False
            if token == "--file" and (Path(value).is_absolute() or ".." in Path(value).parts):
                return False
            count += 1
            index += 2
        else:
            return False
    return 0 < count <= (8 if action == "task-context" else 1)
