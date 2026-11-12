"""PostToolUse hook reconciler for invoke_subagent bindings, wave completion, and failures."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
from _vnext_common import ValidationError as _ExpectedArtifactError, read_json
from antigravity_runtime import candidate_brain_roots, is_trusted_antigravity_path
from evidence_store import StateLock
from review_orchestrator import REVIEW_DISPATCHED, REVIEW_ENV_BLOCKED, load_ledger, save_ledger
from workflow import state_root, task_dir


def _resolve_hook_repo(payload: dict) -> Path:
    """Resolve repository root reliably even when Antigravity invokes hooks with cwd=.agents."""
    env_repo = os.environ.get("HARNESS_REPO", "").strip()
    if env_repo:
        return Path(env_repo).resolve()
    workspaces = payload.get("workspacePaths") or payload.get("workspace_paths") or []
    if isinstance(workspaces, list):
        for raw_ws in workspaces:
            if isinstance(raw_ws, str) and raw_ws.strip():
                try:
                    ws = Path(raw_ws.strip()).expanduser().resolve()
                    if (ws / ".agents").is_dir() or (ws / "agents" / "VERSION").is_file():
                        return ws
                except (OSError, RuntimeError, ValueError):
                    continue
    if _SCRIPTS_DIR.parent.name in {".agents", "agents"}:
        return _SCRIPTS_DIR.parent.parent.resolve()
    return Path.cwd().resolve()


def _bind_candidates_from_brain(repo: Path, payload: dict) -> None:
    """Bind newly spawned reviewer or utility executions when PostToolUse omits toolResult on stdin."""
    from reviewer_host import reviewer_context

    parent_cid = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()
    transcript_raw = str(payload.get("transcriptPath") or payload.get("transcript_path") or "").strip()
    roots: list[Path] = []
    if transcript_raw and is_trusted_antigravity_path(transcript_raw):
        try:
            tp = Path(transcript_raw).expanduser().resolve()
            for br in candidate_brain_roots():
                if br in tp.parents:
                    roots.append(br)
                    break
        except (OSError, RuntimeError, ValueError):
            pass
    for br in candidate_brain_roots():
        if br not in roots and br.is_dir():
            roots.append(br)

    cutoff = time.time() - 120.0
    for brain_root in roots:
        if not brain_root.is_dir():
            continue
        recent_dirs: list[tuple[float, str]] = []
        try:
            for entry in brain_root.iterdir():
                if not entry.is_dir() or entry.is_symlink() or entry.name == parent_cid:
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if mtime >= cutoff:
                    recent_dirs.append((mtime, entry.name))
        except OSError:
            continue
        recent_dirs.sort(reverse=True)
        for _, child_id in recent_dirs[:12]:
            try:
                reviewer_context(repo, child_id, bind=True)
            except Exception:
                continue


def main() -> int:
    from _vnext_common import configure_utf8_output
    configure_utf8_output()
    try:
        raw = __import__('_vnext_common').read_utf8_stdin()
        if not raw.strip():
            print(json.dumps({}))
            return 0
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            print(json.dumps({}))
            return 0

        repo = _resolve_hook_repo(payload)
        call = payload.get("toolCall") or payload.get("tool_call") or {}
        call_name = str(call.get("name") or payload.get("toolName") or "").strip()
        call_name_low = call_name.lower()
        err = payload.get("error")
        if not err:
            # Host result shapes vary. IDs are merely candidates until the
            # canonical child transcript matches a dispatched brief.
            from reviewer_host import reviewer_context

            output = json.dumps(
                payload.get("toolResult")
                or payload.get("tool_response")
                or payload.get("toolOutput")
                or payload.get("output")
                or payload.get("result")
                or ""
            )
            matched_ids = set(re.findall(r'conversationId[\"\s:]+([A-Za-z0-9_-]{4,128})', output))
            for execution_id in matched_ids:
                reviewer_context(repo, execution_id, bind=True)
            if call_name_low in {"invoke_subagent", ""}:
                try:
                    from delegation_policy import bind_utility_from_post_tool, utility_subagent_context
                    for execution_id in matched_ids:
                        utility_subagent_context(repo, execution_id, bind=True)
                    bind_utility_from_post_tool(repo, payload)
                except (ImportError, OSError, ValueError, KeyError, _ExpectedArtifactError):
                    pass
            if not matched_ids and call_name_low in {"invoke_subagent", ""}:
                _bind_candidates_from_brain(repo, payload)
            print(json.dumps({}))
            return 0

        args = call.get("args") or payload.get("toolArgs") or payload.get("tool_input") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}

        if call_name_low == "send_message":
            from reviewer_host import mark_resume_failed

            recipient = str(args.get("Recipient") or args.get("recipient") or "")
            mark_resume_failed(repo, recipient, str(err))
            print(json.dumps({}))
            return 0

        subagents = args.get("Subagents") or args.get("subagents") or []
        roles = []
        if isinstance(subagents, list):
            for sa in subagents:
                if isinstance(sa, dict):
                    r = sa.get("TypeName") or sa.get("typeName") or sa.get("Role") or sa.get("role")
                    if r:
                        roles.append(str(r).strip())
        if not roles and isinstance(args, dict):
            top_r = args.get("TypeName") or args.get("typeName") or args.get("Role") or args.get("role")
            if top_r:
                roles.append(str(top_r).strip())

        err_text = str(err or "").lower()
        if call_name_low == "invoke_subagent" and ("not found" in err_text or "not allowed to be invoked" in err_text):
            try:
                from delegation_policy import CORE_UTILITY_AGENTS, record_unloaded_utility_agent
                parent_cid = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()
                for r in roles:
                    if r in CORE_UTILITY_AGENTS:
                        record_unloaded_utility_agent(repo, parent_cid, r)
            except (ImportError, OSError, ValueError, KeyError, _ExpectedArtifactError):
                logger_noop = None

        st_root = state_root(repo)
        active_task_file = st_root / "active-task.json"
        if not active_task_file.is_file():
            print(json.dumps({}))
            return 0

        active_data = read_json(active_task_file)
        task_id = str(active_data.get("task_id") or "")
        if not task_id:
            print(json.dumps({}))
            return 0

        tdir = task_dir(repo, task_id)
        current_run_file = tdir / "current-run.json"
        if not current_run_file.is_file():
            plan_f = tdir / "plan.json"
            plan = read_json(plan_f) if plan_f.is_file() else {}
            status = str(plan.get("status") or "")
            phases = plan.get("phases") or []
            phase_state_f = tdir / "phase-state.json"

            if status == "IMPLEMENTING" and phases and phase_state_f.is_file():
                from phase_review import (
                    PHASE_REVIEWING,
                    compute_ledger_sha,
                    get_phase_substate,
                    load_phase_ledger,
                    phase_ledger_file,
                    phase_review_dir,
                    phase_run_file,
                )

                p_state = read_json(phase_state_f)
                phase_id = str(p_state.get("current_phase_id") or "")
                if not phase_id:
                    active_idx = int(plan.get("active_phase_index") or 0)
                    if 0 <= active_idx < len(phases):
                        phase_id = str(phases[active_idx].get("id") or "")
                substate = get_phase_substate(p_state, phase_id)
                if substate == PHASE_REVIEWING:
                    rdir = phase_review_dir(tdir, phase_id)
                    prun_f = phase_run_file(tdir, phase_id)
                    run_id = read_json(prun_f).get("phase_review_run_id", "") if prun_f.is_file() else ""
                    target_roles = set(roles)
                    sanitized_err = str(err).strip()[:1000]

                    try:
                        with StateLock(st_root):
                            ok, err_msg, ledger = load_phase_ledger(tdir, phase_id, expected_run_id=run_id or None)
                            if not ok or not ledger:
                                raise RuntimeError(f"Corrupt phase ledger: {err_msg}")
                            reviewers = ledger.get("reviewers", {})
                            to_transition = []
                            for r_name, r_data in reviewers.items():
                                if r_data.get("state") == REVIEW_DISPATCHED and not r_data.get("execution_id"):
                                    if target_roles:
                                        if r_name in target_roles:
                                            to_transition.append(r_name)
                                    else:
                                        to_transition.append(r_name)
                            if not to_transition and not target_roles:
                                to_transition = [
                                    r_name
                                    for r_name, r_data in reviewers.items()
                                    if r_data.get("state") == REVIEW_DISPATCHED and not r_data.get("execution_id")
                                ]
                            for r in to_transition:
                                reviewers[r]["state"] = REVIEW_ENV_BLOCKED
                                reviewers[r]["last_error"] = sanitized_err

                            ledger["ledger_sha256"] = compute_ledger_sha(ledger)
                            from _vnext_common import atomic_write_json

                            atomic_write_json(phase_ledger_file(tdir, phase_id), ledger)
                    except Exception as exc:
                        try:
                            from _vnext_common import atomic_write_json, utc_now

                            marker_data = {
                                "schema_version": 1,
                                "task_id": task_id,
                                "phase_id": phase_id,
                                "run_id": run_id,
                                "error_type": type(exc).__name__,
                                "error_code": "POST_TOOL_RECONCILE_FAILED",
                                "occurred_at": utc_now(),
                            }
                            marker_file1 = rdir / "post-tool-reconcile-error.json"
                            marker_file1.parent.mkdir(parents=True, exist_ok=True)
                            atomic_write_json(marker_file1, marker_data)
                            if run_id:
                                marker_file2 = rdir / run_id / "post-tool-reconcile-error.json"
                                marker_file2.parent.mkdir(parents=True, exist_ok=True)
                                atomic_write_json(marker_file2, marker_data)
                        except (OSError, ValueError, ImportError, _ExpectedArtifactError):
                            pass

            print(json.dumps({}))
            return 0

        current_run = read_json(current_run_file)
        run_id = str(current_run.get("run_id") or "")
        if not run_id:
            print(json.dumps({}))
            return 0

        sanitized_err = str(err).strip()[:1000]
        target_roles = set(roles)
        try:
            with StateLock(st_root):
                ledger = load_ledger(tdir, run_id)
                reviewers = ledger.get("reviewers", {})
                to_transition = []
                for r_name, r_data in reviewers.items():
                    if r_data.get("state") == REVIEW_DISPATCHED and not r_data.get("execution_id"):
                        if target_roles:
                            if r_name in target_roles:
                                to_transition.append(r_name)
                        else:
                            to_transition.append(r_name)

                if not to_transition:
                    to_transition = [
                        r_name
                        for r_name, r_data in reviewers.items()
                        if r_data.get("state") == REVIEW_DISPATCHED and not r_data.get("execution_id")
                    ]

                for r in to_transition:
                    reviewers[r]["state"] = REVIEW_ENV_BLOCKED
                    reviewers[r]["last_error"] = sanitized_err

                save_ledger(tdir, run_id, ledger)
        except Exception as exc:
            try:
                marker_file = tdir / "review-execution" / run_id / "post-tool-reconcile-error.json"
                marker_file.parent.mkdir(parents=True, exist_ok=True)
                from _vnext_common import atomic_write_json, utc_now

                atomic_write_json(
                    marker_file,
                    {
                        "schema_version": 1,
                        "task_id": task_id,
                        "run_id": run_id,
                        "error_type": type(exc).__name__,
                        "error_code": "POST_TOOL_RECONCILE_FAILED",
                        "occurred_at": utc_now(),
                    },
                )
            except (OSError, ValueError, ImportError, _ExpectedArtifactError):
                pass

        print(json.dumps({}))
        return 0
    except Exception:
        print(json.dumps({}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
