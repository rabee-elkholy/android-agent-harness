"""Task execution ownership and recoverable cross-host continuation.

Host ownership is rule-enforced metadata, not proof of reviewer independence.
Approval, policy and evidence remain under their existing canonical authorities.
"""
from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import uuid

from _vnext_common import (ValidationError, atomic_write_json, canonical_sha256, read_json,
                          redact, repository_identity, state_root, utc_now, validate_id)
from evidence_store import EvidenceStore, StateLock
from review_sources import detected_current_host, has_trusted_review_source, resolve_review_host

CONTINUABLE_STATES = frozenset({"APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"})


def _directory(repo, task_id):
    return state_root(repo) / "tasks" / validate_id(task_id)


def _checked(path, hash_key):
    if path.is_symlink() or path.stat().st_size > 1048576:
        raise ValidationError("invalid host continuation record")
    data = read_json(path)
    if not isinstance(data, dict) or data.get(hash_key) != canonical_sha256({k: v for k, v in data.items() if k != hash_key}):
        raise ValidationError("host continuation record integrity mismatch")
    return data


def load_session(repo, task_id):
    path = _directory(repo, task_id) / "host-session.json"
    if not path.exists():
        return None
    data = _checked(path, "session_sha256")
    if data.get("schema_version") != 1 or data.get("task_id") != task_id:
        raise ValidationError("host session task identity mismatch")
    validate_id(str(data.get("session_id") or ""), "host session id")
    host = data.get("host")
    if not isinstance(host, str) or not host or resolve_review_host(repo, host) != host:
        raise ValidationError("invalid host session host")
    identity = repository_identity(repo)
    if any(data.get("repository", {}).get(k) != identity.get(k) for k in ("root_sha256", "git_common_dir_sha256")):
        raise ValidationError("host session repository identity mismatch")
    return data


def review_host_mismatch_action(repo, task_id, plan, host, session):
    """Route a recoverable mismatch before issuing a command for the wrong host."""
    directory = _directory(repo, task_id)
    if (directory / "host-transition.json").exists():
        pending = _checked(directory / "host-transition.json", "transition_sha256")
        if pending.get("status") == "PREPARED":
            return _continue_action(task_id, pending["to_host"], pending["before"].get("host-session.json"), "Recover the interrupted host transfer.")
    if plan.get("status") == "IMPLEMENTING":
        phases = plan.get("phases") or []
        index = int(plan.get("active_phase_index") or 0)
        if not phases or not 0 <= index < len(phases):
            return None
        pointer = directory / "phases" / validate_id(phases[index]["id"]) / "review/current-phase-run.json"
        if not pointer.exists() or read_json(pointer).get("review_host") == host:
            return None
        phase = _phase_context(repo, task_id, plan)
        if phase and phase["fresh"] and phase["state"] not in {"COMPLETE", "REVIEW_BLOCKED"} and phase["run"]["review_host"] != host:
            return _continue_action(task_id, host, session, "The open phase review belongs to another host; stop its executor and continue here.")
    elif plan.get("status") in {"VERIFYING", "BLOCKED"}:
        pointer = directory / "current-run.json"
        if pointer.exists():
            run = read_json(pointer)
            if run.get("review_host") != host:
                if session and session["host"] == host:
                    final = _final_context(repo, task_id, plan)
                    if (plan.get("status") != "VERIFYING" or not final["fresh"]
                            or final["reviews"] is not None or not final["policy"].get("reviewers")):
                        return None
                return _continue_action(task_id, host, session, "The active final verification belongs to another host; continue here without changing its proof.")
    return None


def _continue_action(task_id, host, session, reason):
    command = f"python .agents/harness.py task continue --repo . --task-id {task_id} --host {host} --source-stopped"
    if session:
        command += " --expect-session " + session["session_id"]
    return {"code": "CONTINUE_ON_CURRENT_HOST", "kind": "HARNESS_COMMAND", "blocking": True,
            "command": command, "reason": reason, "inputs": {"task_id": task_id, "host": host},
            "expected": {"success_statuses": ["CONTINUED"]}}


def assert_execution_session(repo, task_id=None, host=None):
    """Reject former executors and incomplete transfers; legacy tasks remain usable."""
    lock = StateLock(Path(repo) / ".harness-setup/lifecycle", timeout_seconds=0)
    if lock.path.exists():
        if lock._owner_live()[0]:
            raise ValidationError("HARNESS_UPDATE_PAUSED: execution is temporarily reserved for the harness update")
    journal = Path(repo) / ".harness-setup/update-journal.json"
    if journal.exists() and read_json(journal).get("status") == "PREPARED":
        raise ValidationError("HARNESS_UPDATE_INCOMPLETE: recover the interrupted update before task mutations")
    if not task_id:
        active = state_root(repo) / "active-task.json"
        if not active.exists():
            return
        task_id = validate_id(str(read_json(active).get("task_id") or ""))
    directory = _directory(repo, task_id)
    pending = directory / "host-transition.json"
    if pending.exists():
        transaction = _checked(pending, "transition_sha256")
        if transaction.get("status") == "PREPARED":
            raise ValidationError("HOST_TRANSFER_INCOMPLETE: repeat task continue on the receiving host")
    session = load_session(repo, task_id)
    if session is None:
        return
    actor = resolve_review_host(repo, host)
    actor_id = os.environ.get("CODEX_THREAD_ID", "").strip() if actor == "codex" else ""
    if session["host"] != actor or (actor_id and session.get("actor_id") and actor_id != session["actor_id"]):
        raise ValidationError(f"HOST_SESSION_MISMATCH: task is owned by {session['host']} session {session['session_id']}; "
                              "stop the former executor and use task continue to take over")


def _restore_transition(directory, transaction):
    """Restore canonical pointers after an interruption; keep new artifacts for diagnosis."""
    phase = transaction.get("phase_archive")
    if phase:
        phase_id, run_id = validate_id(phase["phase_id"]), validate_id(phase["run_id"])
        root = directory / "phases" / phase_id
        archive, current = root / "review-history" / run_id, root / "review"
        if archive.exists():
            if current.exists():
                failed = root / "review-history" / ("interrupted-" + validate_id(transaction["session_id"]))
                if failed.exists():
                    raise ValidationError("interrupted review archive already exists")
                current.rename(failed)
            archive.rename(current)
    for name, value in transaction["before"].items():
        if name not in {"plan.json", "phase-state.json", "current-run.json", "host-session.json"}:
            raise ValidationError("invalid host transition rollback path")
        path = directory / name
        if value is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write_json(path, value)


def _save_transition(directory, data):
    data["transition_sha256"] = canonical_sha256({k: v for k, v in data.items() if k != "transition_sha256"})
    archive = directory / "host-transition-history" / validate_id(data["session_id"]) / (validate_id(data["status"]) + ".json")
    if archive.exists() and read_json(archive) != data:
        raise ValidationError("host transition history is immutable")
    if not archive.exists():
        atomic_write_json(archive, data)
    atomic_write_json(directory / "host-transition.json", data)


def _validate_task(repo, task_id):
    from plan_authority import validate_plan_hash
    from workflow import assert_single_live_task
    assert_single_live_task(repo, allowed_task_id=task_id)
    plan = read_json(_directory(repo, task_id) / "plan.json")
    valid, _ = validate_plan_hash(plan)
    if (not valid or plan.get("task_id") != task_id or plan.get("status") not in CONTINUABLE_STATES
            or (plan.get("approval") or {}).get("plan_sha256") != plan.get("plan_sha256")
            or (plan.get("status") != "APPROVED" and (not plan.get("execution_nonce")
                or plan.get("execution_nonce") != (plan.get("approval") or {}).get("single_use_nonce")))):
        raise ValidationError("host continuation requires a valid approved active task")
    identity, approved = repository_identity(repo), plan.get("repository") or {}
    for key in ("root_sha256", "git_common_dir_sha256", "branch"):
        if approved.get(key) and approved[key] != identity.get(key):
            raise ValidationError(f"host continuation repository mismatch: {key}")
    if approved.get("head") and approved["head"] != identity["head"]:
        from task_git_lineage import is_valid_task_lineage
        ok, reason = is_valid_task_lineage(repo, task_id, identity["head"])
        if not ok:
            raise ValidationError("host continuation lineage mismatch: " + reason)
    return plan, identity


def _phase_context(repo, task_id, plan):
    from phase_review import get_phase_substate, phase_review_freshness, load_phase_ledger
    directory = _directory(repo, task_id)
    phases = plan.get("phases") or []
    if plan["status"] != "IMPLEMENTING" or not phases:
        return None
    index = int(plan.get("active_phase_index") or 0)
    if not 0 <= index < len(phases):
        raise ValidationError("invalid active phase index")
    phase_id = validate_id(phases[index]["id"])
    pointer = directory / "phases" / phase_id / "review/current-phase-run.json"
    if not pointer.exists():
        return None
    run = read_json(pointer)
    if (run.get("task_id") != task_id or run.get("phase_id") != phase_id
            or not isinstance(run.get("review_host"), str) or not run["review_host"]):
        raise ValidationError("phase review run identity mismatch")
    validate_id(str(run.get("phase_review_run_id") or ""))
    state = read_json(directory / "phase-state.json")
    substate = get_phase_substate(state, phase_id)
    fresh, _ = phase_review_freshness(repo, task_id, phase_id, run)
    ok, reason, ledger = load_phase_ledger(
        directory,
        phase_id,
        expected_run_id=run.get("phase_review_run_id"),
        expected_task_id=task_id,
    )
    if not ok:
        raise ValidationError("phase review ledger invalid: " + reason)
    return {"id": phase_id, "run": run, "state": substate, "fresh": fresh, "ledger": ledger}


def _final_context(repo, task_id, plan):
    from delivery_manifest import build_task_manifest, load_task_baseline
    from final_verifier import policy_integrity_error
    directory = _directory(repo, task_id)
    pointer = directory / "current-run.json"
    if plan["status"] not in {"VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"} or not pointer.exists():
        return None
    run = read_json(pointer)
    if run.get("task_id") != task_id or (plan.get("verification_run_id") and plan["verification_run_id"] != run.get("run_id")):
        raise ValidationError("active verification run identity mismatch")
    paths = [Path(run[key]).resolve() for key in ("manifest", "policy")]
    if any(not path.is_relative_to(directory.resolve()) for path in paths):
        raise ValidationError("verification artifact path escapes the task directory")
    manifest, policy = read_json(paths[0]), read_json(paths[1])
    validate_id(str(run.get("run_id") or ""), "verification run id")
    if any(run.get(key) != manifest.get(key) for key in ("delivery_snapshot_sha256", "change_set_sha256")):
        raise ValidationError("verification run and manifest identity mismatch")
    error = policy_integrity_error(policy, Path(run["policy"]))
    if error:
        raise ValidationError(error)
    live = build_task_manifest(repo, load_task_baseline(repo, task_id), expected_files=plan.get("expected_files"),
                               task_base_head=plan.get("task_base_head") or (plan.get("repository") or {}).get("head"))
    fresh = all(live.get(key) == manifest.get(key) for key in (
        "delivery_snapshot_sha256", "change_set_sha256", "external_inputs_sha256"))
    from workflow import verification_engine_freshness
    fresh = fresh and verification_engine_freshness(repo, task_id, run)["fresh"]
    store = EvidenceStore(state_root(repo))
    artifact = store.run_dir(run["delivery_snapshot_sha256"], run["run_id"]) / "reviews.json"
    reviews = store.read(run["delivery_snapshot_sha256"], run["run_id"], "reviews") if artifact.exists() else None
    return {"run": run, "manifest": manifest, "policy": policy, "reviews": reviews, "fresh": fresh}


def continue_task(args):
    from plan_authority import save_plan
    from workflow import resolve_next_action
    repo, task_id = Path(args.repo).resolve(), validate_id(args.task_id)
    directory = _directory(repo, task_id)
    host = resolve_review_host(repo, args.host)
    caller = detected_current_host()
    if caller and caller != host:
        raise ValidationError(f"HOST_CALLER_MISMATCH: run task continue from the receiving {host} host, not {caller}")
    with ExitStack() as locks:
        locks.enter_context(StateLock(state_root(repo), timeout_seconds=0))
        locks.enter_context(StateLock(directory / "execution", timeout_seconds=0))
        journal = directory / "host-transition.json"
        if journal.exists():
            pending = _checked(journal, "transition_sha256")
            if pending.get("status") == "PREPARED":
                if pending.get("task_id") != task_id or pending.get("to_host") != host:
                    raise ValidationError("HOST_TRANSFER_INCOMPLETE: recover on the recorded receiving host")
                _restore_transition(directory, pending)
                pending["status"] = "RECOVERED"
                _save_transition(directory, pending)
        plan, identity = _validate_task(repo, task_id)
        previous = load_session(repo, task_id)
        expected = getattr(args, "expect_session", None)
        if expected and (previous or {}).get("session_id") != expected:
            raise ValidationError("STALE_HOST_SESSION: another continuation already changed ownership")
        phase, final = _phase_context(repo, task_id, plan), _final_context(repo, task_id, plan)
        run_host = ((phase or {}).get("run") or (final or {}).get("run") or {}).get("review_host")
        source = (previous or {}).get("host") or run_host
        actor_id = os.environ.get("CODEX_THREAD_ID", "").strip() if host == "codex" else ""
        switching = bool(source and (source != host or (previous or {}).get("actor_id") not in (None, "", actor_id)))
        if switching and not getattr(args, "source_stopped", False):
            raise ValidationError("host transfer requires --source-stopped after stopping the previous executor")
        restart_phase = bool(phase and phase["fresh"] and phase["state"] not in {"COMPLETE", "REVIEW_BLOCKED"}
                             and phase["run"]["review_host"] != host)
        restart_final = bool(final and final["fresh"] and final["policy"].get("reviewers") and final["reviews"] is None and final["run"]["review_host"] != host
                             and plan["status"] == "VERIFYING")
        final_findings = _pending_final_findings(directory, final) if restart_final else []
        if final_findings:
            restart_final = False
        if previous and previous["host"] == host and previous.get("actor_id", "") == actor_id and not (restart_phase or restart_final or final_findings):
            return _result(repo, task_id, plan, previous, [], [])
        phase_findings = False
        if restart_phase:
            locks.enter_context(StateLock(directory / "phases" / phase["id"] / "review", timeout_seconds=0))
            if any(entry.get("verdict") == "FINDINGS" for entry in phase["ledger"]["reviewers"].values()):
                restart_phase = False
                phase_findings = True
            if restart_phase and int(phase["run"].get("host_restart_count") or 0) >= 3:
                raise ValidationError("host review restart limit reached; resolve the reviewer environment before retrying")
        session_id = "host-" + uuid.uuid4().hex
        transaction = {"schema_version": 1, "task_id": task_id, "session_id": session_id, "status": "PREPARED",
                       "from_host": source, "to_host": host, "before": {
                           name: read_json(directory / name) if (directory / name).exists() else None
                           for name in ("plan.json", "phase-state.json", "current-run.json", "host-session.json")}}
        if restart_phase:
            transaction["phase_archive"] = {"phase_id": phase["id"], "run_id": phase["run"]["phase_review_run_id"]}
        _save_transition(directory, transaction)
        restarted, reused = [], []
        try:
            if final_findings:
                plan["status"] = "BLOCKED"
                plan["blocked_reviewers"] = sorted(set(plan.get("blocked_reviewers") or []) | set(final_findings))
                from review_budget import settle_final_review_calls
                settle_final_review_calls(repo, plan)
                save_plan(directory / "plan.json", plan)
            if phase_findings:
                from phase_review import PHASE_REVIEW_BLOCKED, set_phase_substate
                set_phase_substate(directory, phase["id"], PHASE_REVIEW_BLOCKED)
            if restart_phase:
                from phase_review import build_phase_package, invalidate_phase_review, phase_ledger_file
                invalidate_phase_review(repo, task_id, phase["id"], lock=False)
                _, new = build_phase_package(repo, task_id, phase["id"], host=host)
                new["host_restart_count"] = int(phase["run"].get("host_restart_count") or 0) + 1
                new["supersedes_review_run"] = phase["run"]["phase_review_run_id"]
                atomic_write_json(directory / "phases" / phase["id"] / "review/current-phase-run.json", new)
                ledger = read_json(phase_ledger_file(directory, phase["id"]))
                from review_orchestrator import compute_ledger_sha
                for reviewer, entry in ledger["reviewers"].items():
                    prior = phase["ledger"]["reviewers"].get(reviewer) or {}
                    entry["protocol_attempts"] = prior.get("protocol_attempts", 0)
                    if prior.get("state") == "FAILED_PROTOCOL":
                        entry["state"] = prior["state"]
                        entry["last_error"] = prior.get("last_error")
                ledger["ledger_sha256"] = compute_ledger_sha(ledger)
                atomic_write_json(phase_ledger_file(directory, phase["id"]), ledger)
                restarted.append(new["phase_review_run_id"])
            if restart_final:
                reused, new_run = _restart_final(repo, task_id, plan, final, host, session_id)
                restarted.append(new_run)
            from delivery_manifest import build_manifest
            live = build_manifest(repo)
            session = {"schema_version": 1, "task_id": task_id, "session_id": session_id, "host": host,
                       "actor_id": actor_id, "repository": identity, "plan_sha256": plan["plan_sha256"],
                       "previous_session_sha256": (previous or {}).get("session_sha256"), "created_at": utc_now(),
                       "enforcement_tier": "RULE_ENFORCED", "source_stopped": bool(getattr(args, "source_stopped", False)),
                       "restarted_reviews": restarted, "reused_artifacts": reused}
            session["delivery_snapshot_sha256"] = live["delivery_snapshot_sha256"]
            session["change_set_sha256"] = live["change_set_sha256"]
            session["session_sha256"] = canonical_sha256(session)
            atomic_write_json(directory / "host-history" / (session_id + ".json"), session)
            atomic_write_json(directory / "host-session.json", session)
            transaction["status"] = "COMPLETED"
            _save_transition(directory, transaction)
        except Exception:
            _restore_transition(directory, transaction)
            transaction["status"] = "ROLLED_BACK"
            _save_transition(directory, transaction)
            raise
        return _result(repo, task_id, read_json(directory / "plan.json"), session, restarted, reused)


def _restart_final(repo, task_id, plan, final, host, session_id):
    from plan_authority import save_plan
    from review_orchestrator import init_ledger, save_ledger
    from review_budget import effective_review_budget
    directory, old = _directory(repo, task_id), final["run"]
    if int(old.get("host_restart_count") or 0) >= 3:
        raise ValidationError("host review restart limit reached")
    _, ledger = _interrupted_final_dispatches(directory, old)
    if ledger:
        if any(entry.get("state") == "FAILED_PROTOCOL" for entry in ledger["reviewers"].values()):
            raise ValidationError("REVIEW_PROTOCOL_BLOCKED: changing host cannot reset an exhausted protocol retry counter")
    from review_budget import settle_final_review_calls
    used = settle_final_review_calls(repo, plan)
    if used + len(final["policy"].get("reviewers") or []) > effective_review_budget(repo, plan, final["policy"]):
        raise ValidationError("REVIEW_BUDGET_EXHAUSTED: host transfer cannot reset reviewer spending; use task review-budget")
    new_run = "run-" + uuid.uuid4().hex
    atomic_write_json(directory / ("manifest-" + new_run + ".json"), final["manifest"])
    atomic_write_json(directory / ("policy-" + new_run + ".json"), final["policy"])
    current = {**old, "run_id": new_run, "review_host": host,
               "review_protocol_version": 2 if has_trusted_review_source(host) else 1,
               "manifest": str(directory / ("manifest-" + new_run + ".json")),
               "policy": str(directory / ("policy-" + new_run + ".json")), "created_at": utc_now(),
               "host_restart_count": int(old.get("host_restart_count") or 0) + 1,
               "supersedes_run_id": old["run_id"], "host_session_id": session_id}
    store, reused = EvidenceStore(state_root(repo)), []
    for name in ("preflight", "unit_tests", "localization", "room", "red_evidence"):
        if not (store.run_dir(old["delivery_snapshot_sha256"], old["run_id"]) / (name + ".json")).exists():
            continue
        record = store.read(old["delivery_snapshot_sha256"], old["run_id"], name)
        if record.get("change_set_sha256") != old["change_set_sha256"]:
            raise ValidationError("source gate evidence identity mismatch")
        if record["status"] == "PASS":
            store.reuse(snapshot=old["delivery_snapshot_sha256"], source_run_id=old["run_id"],
                        run_id=new_run, name=name, lock=False)
            reused.append(name)
    atomic_write_json(directory / "host-history" / (old["run_id"] + ".json"), old)
    atomic_write_json(directory / "current-run.json", current)
    if ledger:
        replacement = init_ledger(directory, task_id, new_run, old["delivery_snapshot_sha256"],
                                  old["change_set_sha256"], "", list(final["policy"]["reviewers"]))
        for reviewer, entry in replacement["reviewers"].items():
            entry["protocol_attempts"] = (ledger["reviewers"].get(reviewer) or {}).get("protocol_attempts", 0)
        save_ledger(directory, new_run, replacement)
    plan["verification_run_id"], plan["review_calls_used"] = new_run, used
    save_plan(directory / "plan.json", plan)
    return reused, new_run


def _interrupted_final_dispatches(directory, run):
    from review_orchestrator import ledger_file, load_ledger
    ledger = None
    roles = set()
    if ledger_file(directory, run["run_id"]).exists():
        ledger = load_ledger(directory, run["run_id"])
        if (ledger.get("task_id") != run["task_id"] or ledger.get("run_id") != run["run_id"]
                or ledger.get("delivery_snapshot_sha256") != run["delivery_snapshot_sha256"]
                or ledger.get("change_set_sha256") != run["change_set_sha256"]):
            raise ValidationError("interrupted review ledger identity mismatch")
        roles.update(reviewer for reviewer, entry in ledger["reviewers"].items()
                     if entry.get("state") != "NOT_DISPATCHED")
    roles.update(path.stem for path in (directory / "staged-reviews" / run["run_id"]).glob("*.json"))
    receipts = directory / "reviewer-dispatches"
    for path in receipts.glob("*.json"):
        if read_json(path).get("run_id") == run["run_id"]:
            roles.add(path.stem)
    roles.update(path.stem for path in (receipts / run["run_id"]).glob("*.json"))
    return len(roles), ledger


def _pending_final_findings(directory, final):
    """Partial reviewer findings survive a takeover before aggregation."""
    from review_orchestrator import ledger_file, load_ledger, result_file
    if not final:
        return []
    run_id = final["run"]["run_id"]
    paths = []
    if ledger_file(directory, run_id).exists():
        ledger = load_ledger(directory, run_id)
        for reviewer, entry in ledger.get("reviewers", {}).items():
            if entry.get("state") in {"COMPLETED", "INGESTED"}:
                paths.append((reviewer, result_file(directory, run_id, reviewer)))
    staged = directory / "staged-reviews" / run_id
    if staged.exists():
        paths.extend((path.stem, path) for path in staged.glob("*.json"))
    owners = []
    for reviewer, path in paths:
        data = read_json(path)
        result = data.get("result") or data
        if result.get("verdict") in {"FINDINGS", "FAIL"} or result.get("findings"):
            owners.append(reviewer)
    return sorted(set(owners))


def _result(repo, task_id, plan, session, restarted, reused):
    from workflow import resolve_next_action
    directory = _directory(repo, task_id)
    phase_state = read_json(directory / "phase-state.json") if (directory / "phase-state.json").exists() else {}
    return {"status": "CONTINUED", "task_id": task_id, "host": session["host"], "session_id": session["session_id"],
            "enforcement_tier": "RULE_ENFORCED", "restarted_reviews": restarted, "reused_artifacts": reused,
            "brief": redact({"outcome": str(plan.get("requested_outcome") or "")[:1000],
                              "approved_plan_sha256": plan.get("plan_sha256"), "task_state": plan["status"],
                              "current_phase": phase_state.get("current_phase_id"),
                              "completed_phases": phase_state.get("completed_phases") or [],
                              "review_calls_used": plan.get("review_calls_used", 0),
                              "review_rounds": plan.get("review_rounds", 0),
                              "expected_files": (plan.get("expected_files") or [])[:30],
                              "scope_truncated": len(plan.get("expected_files") or []) > 30,
                              "blocked_reviewers": plan.get("blocked_reviewers") or [],
                              "plan_path": str(directory / "plan.md"),
                              "developer_instructions_path": str(repo / ".agents/project-context/developer-instructions.json"),
                              "project_notes_path": str(repo / ".agents/project-context/project-notes.md")}),
            "next_action": resolve_next_action(repo, task_id, plan, host=session["host"])}
