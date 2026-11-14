"""Stable repository-local entrypoint for an installed Android Agent Harness."""
from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


AGENTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = AGENTS_ROOT.parent
SCRIPTS = AGENTS_ROOT / "scripts"
TASK_SUBCOMMANDS = frozenset({
    "draft", "revise", "checkpoint-phase", "begin-next-phase", "present-plan", "approve", "approve-sensitive",
    "begin", "debug-evidence", "validate-finding", "prepare-verification", "complete", "deliver", "cancel",
    "resume", "handoff", "reconcile-handoff", "reconcile-delivery", "status", "recover-stale", "recover-active",
    "coverage", "bind-evidence", "metrics", "review-budget", "continue", "switch", "merge", "change-decision",
    "heal", "plan-check", "plan-note", "bridge",
})


def _run(script: str, args: list[str]) -> int:
    target = SCRIPTS / script
    if not target.is_file():
        print(f"[ERROR] Installed harness script is missing: {target}", file=sys.stderr)
        return 2
    from contextlib import nullcontext
    lease = nullcontext()
    sys.path.insert(0, str(SCRIPTS))
    from _vnext_common import ValidationError, read_json
    from host_continuation import assert_execution_session
    from evidence_store import StateLock
    read_only = script in {"project_graph.py", "task_context.py", "harness_doctor.py", "task_metrics.py", "review_policy.py", "delegation_policy.py", "android_inspect.py"}
    read_only = read_only or (script == "debug_instrumentation.py" and args[:1] == ["status"])
    read_only = read_only or (script == "run_device.py" and (args[:1] in (["status"], ["ios-status"]) or any(a in ("-h", "--help") for a in args)))
    read_only = read_only or (script == "workflow.py" and args[:1] in (["status"], ["coverage"], ["metrics"], ["continue"], ["plan-check"], ["bridge"]))
    read_only = read_only or (script == "generate_project_context.py" and args[:1] in (["preview"], ["status"], ["drift-report"]))
    read_only = read_only or (script == "pm_discovery.py" and args[:1] in (["discover"], ["status"]))
    read_only = read_only or script in {"incident_reporter.py", "repair.py", "execution_mode.py"}
    # Merge checks the execution sessions of every source before applying; preview is read-only.
    read_only = (
        read_only
        or (script == "workflow.py" and args[:1] == ["merge"])
        or (script == "symbol_edit.py" and args[:1] in (["outline"], ["read"]))
        or (script == "static_health_bridge.py")
        or (script == "roborazzi_gate.py" and args[:1] in (["capabilities"], ["inspect-tree"]))
        or (script == "maestro_bridge.py" and args[:1] in (["capabilities"], ["list"]))
        or (script == "session_forensics.py")
        or (script == "web_relay.py" and (args[:1] in (["pack"], ["status"]) or (args[:1] == ["apply"] and "--dry-run" in args)))
    )
    # The bounded verification runner owns its execution lease, including when
    # invoked directly; taking it here too would create a nested lock.
    if script != "verification_steps.py" and not read_only and not {"--help", "-h"} & set(args):
        active = AGENTS_ROOT / "state/active-task.json"
        task_id = ""
        for index, argument in enumerate(args):
            if argument == "--task-id" and index + 1 < len(args):
                task_id = args[index + 1]
            elif argument.startswith("--task-id="):
                task_id = argument.split("=", 1)[1]
        if not task_id and active.exists():
            task_id = str(read_json(active).get("task_id") or "")
        if task_id:
            try:
                assert_execution_session(REPO_ROOT, task_id)
                session = AGENTS_ROOT / "state/tasks" / task_id / "host-session.json"
                if session.exists():
                    lease = StateLock(session.parent / "execution", timeout_seconds=0)
            except ValidationError as exc:
                print(f"[FAIL] {exc}", file=sys.stderr)
                return 1
    in_process_ok = (
        os.environ.get("HARNESS_FORCE_SUBPROCESS") != "1"
        and (
            script in {"project_graph.py", "task_context.py", "delegation_policy.py", "review_policy.py", "session_forensics.py"}
            or (script == "static_health_bridge.py" and args[:1] in (["capabilities"], ["report"]))
            or (script == "symbol_edit.py" and args[:1] in (["outline"], ["read"]))
            or (script == "workflow.py" and args[:1] == ["status"])
            or (script == "web_relay.py" and args[:1] == ["status"])
            or (script == "execution_mode.py" and (not args or args[:1] == ["show"]))
        )
    )
    if in_process_ok:
        import importlib
        import inspect
        mod_name = target.stem
        existing_mod = sys.modules.get(mod_name)
        existing_file = Path(getattr(existing_mod, "__file__", "") or "") if existing_mod is not None else None
        if existing_mod is None or (existing_file is not None and existing_file.is_file() and existing_file.resolve() == target.resolve()):
            prev_argv = sys.argv[:]
            prev_cwd = Path.cwd()
            try:
                with lease:
                    os.chdir(REPO_ROOT)
                    sys.path.insert(0, str(SCRIPTS))
                    mod = existing_mod if existing_mod is not None else importlib.import_module(mod_name)
                    main_fn = getattr(mod, "main")
                    sys.argv = [str(target), *args]
                    sig = inspect.signature(main_fn)
                    rc = main_fn(args) if len(sig.parameters) >= 1 else main_fn()
                    return int(rc) if isinstance(rc, int) else 0
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else (0 if exc.code is None else 1)
            except ValidationError as exc:
                print(f"[FAIL] {exc}", file=sys.stderr)
                return 1
            finally:
                sys.argv = prev_argv
                try:
                    os.chdir(prev_cwd)
                except OSError:
                    pass
    try:
        with lease:
            proc = subprocess.run([sys.executable, "-u", str(target), *args], cwd=str(REPO_ROOT), check=False,
                                  env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except ValidationError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return proc.returncode


# Commands after which the agent needs the next step. A real delivery called `task status --next --json`
# after each of them (six times from review finalize to ready), one extra model turn each.
# `verify` prints a JSON report and is left out so its output stays parseable.
NEXT_STEP_COMMANDS = frozenset({"preflight", "test", "assemble", "device", "review", "phase-review"})
NEXT_STEP_TASK_ACTIONS = frozenset({"prepare-verification", "approve-sensitive", "complete", "resume"})


def _print_next_step(*, step_args: list[str] | None = None, exit_code: int = 0) -> None:
    """Print the active task's next action as NEXT_ACTION= / NEXT_REASON= (best effort, never fails)."""
    import contextlib
    import io
    import json

    if step_args and step_args[0] == "device" and (
        exit_code != 0 or step_args[1:2] in (["install-start"], ["start"])
    ):
        return

    try:
        sys.path.insert(0, str(SCRIPTS))
        from mutation_guard import active_plan

        plan = active_plan(REPO_ROOT) or {}
        task_id = str(plan.get("task_id") or "")
        if not task_id or str(plan.get("status") or "") in ("", "DELIVERED", "CANCELLED"):
            return
        from workflow import _compact_for_host, resolve_next_action

        is_verify_gate_step = bool(
            step_args
            and (
                step_args[0] in ("preflight", "test")
                or (len(step_args) > 1 and step_args[0] == "task" and step_args[1] == "prepare-verification")
            )
        )
        step_host = os.environ.get("HARNESS_HOST", "").strip().lower() or None
        if step_args:
            for idx_arg, tok_arg in enumerate(step_args):
                if tok_arg == "--host" and idx_arg + 1 < len(step_args):
                    step_host = step_args[idx_arg + 1].strip().lower() or step_host
                elif tok_arg.startswith("--host="):
                    step_host = tok_arg.split("=", 1)[1].strip().lower() or step_host
        if not step_host:
            from _vnext_common import read_json as _rj
            t_state_dir = AGENTS_ROOT / "state" / "tasks" / task_id
            for cand_name, key_name in (("current-run.json", "review_host"), ("host-session.json", "host")):
                cand_p = t_state_dir / cand_name
                if cand_p.is_file():
                    try:
                        val_h = str(_rj(cand_p).get(key_name) or "").strip().lower()
                        if val_h:
                            step_host = val_h
                            break
                    except (OSError, ValueError):
                        continue
        host_kw = {"host": step_host} if step_host else {}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            action = resolve_next_action(REPO_ROOT, task_id, plan, **host_kw)
            if (
                exit_code == 0
                and is_verify_gate_step
                and isinstance(action, dict)
                and action.get("code") == "BUILD_REVIEW_PACKAGE"
            ):
                try:
                    from review_package import build_package
                    build_package(REPO_ROOT, task_id)
                    action = resolve_next_action(REPO_ROOT, task_id, plan, **host_kw)
                except (OSError, ValueError, ImportError):
                    pass
    except Exception:
        return
    if not isinstance(action, dict):
        return
    code = str(action.get("code") or "")
    if not code:
        return
    command = str(action.get("command") or "")
    if code.startswith("DISPATCH_") or code.startswith("RETRY_"):
        if code in {"DISPATCH_REVIEWERS", "DISPATCH_PHASE_REVIEWERS"} and action.get("inputs"):
            command = "follow NEXT_ACTION_INPUTS below"
        else:
            command = f"python .agents/harness.py task status --task-id {task_id} --next --brief --json (for the exact payload)"
    elif not command and action.get("tool") == "ask_question":
        command = "invoke ask_question tool in this turn (DEVELOPER_ACTION)"
    print(f"NEXT_ACTION={code}: {command or '(no command: ' + str(action.get('kind') or 'action') + ')'}", flush=True)
    if action.get("reason"):
        print(f"NEXT_REASON={action['reason']}", flush=True)
    if action.get("suggested_commit"):
        print(f"SUGGESTED_COMMIT={action['suggested_commit']}", flush=True)
    if action.get("instructions") and (action.get("tool") == "ask_question" or action.get("kind") == "DEVELOPER_ACTION"):
        print(f"NEXT_INSTRUCTIONS={action['instructions']}", flush=True)
    rot = action.get("context_rotation")
    if isinstance(rot, dict) and rot.get("recommended"):
        emit_rot = True
        try:
            from task_bridge import should_emit_cli_rotation_advisory
            emit_rot = should_emit_cli_rotation_advisory(REPO_ROOT, rot)
        except (ImportError, OSError, ValueError):
            emit_rot = True
        if emit_rot:
            print(f"CONTEXT_ROTATION_RECOMMENDED={rot.get('mode')}: {rot.get('save_command')}", flush=True)
            print(f"CONTEXT_ROTATION_REASON={rot.get('reason')}", flush=True)
            if rot.get("instructions"):
                print(f"CONTEXT_ROTATION_INSTRUCTIONS={rot.get('instructions')}", flush=True)
    if code in {"DISPATCH_REVIEWERS", "DISPATCH_PHASE_REVIEWERS"} and action.get("inputs"):
        try:
            compact_inputs = _compact_for_host(action["inputs"])
        except Exception:
            compact_inputs = action["inputs"]
        print("NEXT_ACTION_INPUTS=" + json.dumps(compact_inputs, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(SCRIPTS))
    from _vnext_common import configure_utf8_output
    configure_utf8_output()
    args = list(argv if argv is not None else sys.argv[1:])
    import os
    import time
    started = time.time()
    monotonic = time.monotonic()
    from task_metrics import metric_task_id
    metric_owner = metric_task_id(REPO_ROOT, args)
    try:
        code = _main(args)
    except Exception as exc:
        import traceback
        tb_text = traceback.format_exc()
        try:
            from incident_reporter import record_incident
            inc = record_incident(
                REPO_ROOT,
                code="UNEXPECTED_EXCEPTION",
                command=f"harness.py {' '.join(args[:2])}".strip(),
                message=f"{type(exc).__name__}: {exc}",
                task_id=metric_owner or "",
                traceback_text=tb_text,
            )
            inc_id = inc.get("incident_id", "")
            guidance = inc.get("ask_question_guidance") or {}
            sub = inc.get("submission") or {}
            print(f"[FAIL] Unexpected harness exception ({type(exc).__name__}: {exc})", file=sys.stderr)
            print(f"INCIDENT_RECORDED={inc_id}", file=sys.stderr)
            print(f"INCIDENT_LOCAL_REPORT=.agents/state/incidents/{inc_id}.md", file=sys.stderr)
            if sub.get("status") in {"REPORTED", "DEDUPLICATED_EXISTING_ISSUE"}:
                print(f"INCIDENT_AUTO_SUBMITTED={sub.get('issue_url', '')}", file=sys.stderr)
            elif guidance:
                print("TOOL_CALL_REQUIRED=ask_question", file=sys.stderr)
                print(f"INCIDENT_SUBMIT_ONCE={guidance.get('submit_once_command', '')}", file=sys.stderr)
                print(f"INCIDENT_SUBMIT_ALWAYS={guidance.get('submit_always_command', '')}", file=sys.stderr)
                print(f"NEXT_INSTRUCTIONS={guidance.get('instructions', '')}", file=sys.stderr)
        except Exception:
            print(tb_text, file=sys.stderr)
        return 1
    # Explicit opt-in: feature-off does not read tasks or scan metrics history.
    if os.environ.get("HARNESS_LOCAL_METRICS") == "1" and args and args[0] in {"task", "task-context", "verify-steps", "phase-review", "preflight", "test", "assemble", "compile", "device", "review", "journey"}:
        try:
            sys.path.insert(0, str(SCRIPTS))
            from task_metrics import record_operation
            actions = {"task": TASK_SUBCOMMANDS,
                       "device": {"install-start", "signoff", "skip-validation", "validate-automatically"},
                       "review": {"package", "profile", "ingest", "complete", "complete-all", "finalize", "dispatch", "dispatch-batch", "status"},
                       "journey": {"validate", "list", "run"}}
            operation = args[0]
            if len(args) > 1 and args[1] in actions.get(args[0], ()):
                operation += "-" + args[1]
            if operation not in {"task-metrics", "task-coverage", "task-status", "task-plan-check", "task-bridge", "journey-list", "journey-validate", "review-status", "review-profile"}:
                task_id = metric_owner
                if task_id:
                    record_operation(REPO_ROOT, task_id, operation, time.monotonic() - monotonic, code, started)
        except (OSError, ValueError, ImportError):
            pass
    # Never after --json (the output must stay pure JSON) or help.
    step = args[0] in NEXT_STEP_COMMANDS if args else False
    # Real app: after `task approve-sensitive`, `task complete` and `task prepare-verification` the agent
    # still queried status for the next step; those lifecycle steps print it too.
    step = step or (len(args) > 1 and args[0] == "task" and args[1] in NEXT_STEP_TASK_ACTIONS)
    if step and not {"--json", "-h", "--help"} & set(args):
        try:
            _print_next_step(step_args=args, exit_code=code)
        except (OSError, UnicodeError, ValueError):
            # Advisory printing cannot change the completed operation's exit code.
            pass
    return code


def _main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in {"-h", "--help", "help"}:
        print(
            "Usage: python .agents/harness.py "
            "<context|task-context|graph|symbol|task|doctor|repair|diagnose-session|health|policy|delegate-plan|execution-mode|web-relay|web-pack|web-apply|verify-steps|preflight|test|roborazzi|compile|assemble|review|phase-review|device|debug|android-ui|android-inspect|journey|e2e|maestro|verify|pm|zoho|report-issue|version|update-info|commands> [args...]"
        )
        return 0

    command = args.pop(0)
    if command == "debug":
        return _run("debug_instrumentation.py", args)
    if command == "android-inspect":
        return _run("android_inspect.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "android-ui":
        return _run("android_ui.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "policy":
        return _run("review_policy.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "verify-steps":
        return _run("verification_steps.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "task" and args and args[0] in {"coverage", "bind-evidence", "metrics"}:
        return _run("workflow.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "journey":
        return _run("journey_runner.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "e2e":
        return _run("phone_e2e.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "version":
        version_file = AGENTS_ROOT / "VERSION"
        if not version_file.is_file():
            print("[ERROR] Installed harness VERSION is missing", file=sys.stderr)
            return 2
        print(version_file.read_text(encoding="utf-8").strip())
        sys.path.insert(0, str(AGENTS_ROOT / "scripts"))
        try:
            from check_kit_update import pending_update_note
            pending = pending_update_note(REPO_ROOT)
        except Exception:
            pending = ""
        if pending:
            print(f"[WARN] {pending} See: python .agents/harness.py update-info", file=sys.stderr)
        return 0

    if command == "update-info":
        sys.path.insert(0, str(AGENTS_ROOT / "scripts"))
        from check_kit_update import update_instructions
        print(update_instructions(REPO_ROOT, force="--offline" not in args))
        return 0

    if command == "context":
        if not args:
            print("[ERROR] context requires preview, generate, status, refresh, note, instruct, or drift-report", file=sys.stderr)
            return 2
        return _run("generate_project_context.py", [args[0], "--repo", str(REPO_ROOT), *args[1:]])
    if command == "task-context":
        return _run("task_context.py", ["--repo", str(REPO_ROOT), *args])
    if command == "delegate-plan":
        return _run("delegation_policy.py", ["--repo", str(REPO_ROOT), *args])
    if command == "execution-mode":
        if not args:
            return _run("execution_mode.py", ["show", "--repo", str(REPO_ROOT)])
        if args[0] in {"-h", "--help", "help"}:
            return _run("execution_mode.py", ["--help"])
        if args[0] in {"show", "set"}:
            sub_c, rest_c = args[0], list(args[1:])
            if not {"-h", "--help"} & set(rest_c) and "--repo" not in rest_c and not any(a.startswith("--repo=") for a in rest_c):
                rest_c = ["--repo", str(REPO_ROOT), *rest_c]
            return _run("execution_mode.py", [sub_c, *rest_c])
        forwarded_em = list(args)
        if not {"-h", "--help"} & set(forwarded_em) and "--repo" not in forwarded_em and not any(a.startswith("--repo=") for a in forwarded_em):
            forwarded_em = ["--repo", str(REPO_ROOT), *forwarded_em]
        return _run("execution_mode.py", ["show", *forwarded_em])
    if command == "symbol":
        return _run("symbol_edit.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "health":
        return _run("static_health_bridge.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "roborazzi":
        return _run("roborazzi_gate.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "maestro":
        return _run("maestro_bridge.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "diagnose-session":
        return _run("session_forensics.py", [*args, "--repo", str(REPO_ROOT)])
    if command == "web-pack":
        forwarded = list(args)
        if not {"-h", "--help"} & set(forwarded) and "--repo" not in forwarded and not any(a.startswith("--repo=") for a in forwarded):
            forwarded = ["--repo", str(REPO_ROOT), *forwarded]
        return _run("web_relay.py", ["pack", *forwarded])
    if command == "web-apply":
        forwarded = list(args)
        if not {"-h", "--help"} & set(forwarded) and "--repo" not in forwarded and not any(a.startswith("--repo=") for a in forwarded):
            forwarded = ["--repo", str(REPO_ROOT), *forwarded]
        return _run("web_relay.py", ["apply", *forwarded])
    if command == "web-relay":
        if not args or args[0] in {"-h", "--help", "help"}:
            return _run("web_relay.py", ["--help"])
        sub_cmd, rest_args = args[0], list(args[1:])
        if not {"-h", "--help"} & set(rest_args) and "--repo" not in rest_args and not any(a.startswith("--repo=") for a in rest_args):
            rest_args = ["--repo", str(REPO_ROOT), *rest_args]
        return _run("web_relay.py", [sub_cmd, *rest_args])
    if command == "graph":
        forwarded = list(args)
        if "--repo" not in forwarded:
            forwarded.extend(["--repo", str(REPO_ROOT)])
        return _run("project_graph.py", forwarded)
    if command == "task":
        forwarded = list(args)
        if "--repo" not in forwarded:
            forwarded.extend(["--repo", str(REPO_ROOT)])
        return _run("workflow.py", forwarded)
    if command == "doctor":
        return _run("harness_doctor.py", ["--repo", str(REPO_ROOT), *args])
    if command == "repair":
        forwarded = list(args)
        if "--repo" not in forwarded and not any(a.startswith("--repo=") for a in forwarded):
            forwarded = ["--repo", str(REPO_ROOT), *forwarded]
        return _run("repair.py", forwarded)
    if command == "preflight":
        return _run("preflight_check.py", args)
    if command == "test":
        return _run("run_tests_gate.py", args)
    if command == "commands":
        sys.path.insert(0, str(SCRIPTS))
        import json
        from _public_commands import get_public_commands
        print(json.dumps(get_public_commands(), indent=2, ensure_ascii=False))
        return 0
    if command == "assemble":
        forwarded = list(args)
        if not forwarded or (len(forwarded) == 1 and forwarded[0] in ("--repo", ".")):
            sys.path.insert(0, str(SCRIPTS))
            from _variants import resolve_assemble_task
            task_str = resolve_assemble_task(REPO_ROOT)
            forwarded = [task_str]
        return _run("run_gradle_task.py", forwarded)
    if command == "compile":
        forwarded = list(args)
        if forwarded == ["--ios"]:
            sys.path.insert(0, str(SCRIPTS))
            from _variants import resolve_ios_compile_task
            task_str, note = resolve_ios_compile_task(REPO_ROOT)
            if not task_str:
                print(f"[WARN] {note}", file=sys.stderr)
                return 3
            print(f"[*] {note}")
            forwarded = [task_str]
        elif not forwarded:
            sys.path.insert(0, str(SCRIPTS))
            from _variants import resolve_compile_task
            task_str, note = resolve_compile_task(REPO_ROOT)
            if not task_str:
                print(f"[WARN] {note}", file=sys.stderr)
                return 3
            print(f"[*] {note}")
            forwarded = [task_str]
        return _run("run_gradle_task.py", forwarded)
    if command == "review":
        sys.path.insert(0, str(AGENTS_ROOT))
        from harness_shared.commands import review_command
        script, forward = review_command(args)
        return _run(script, forward)
    if command == "phase-review":
        return _run("phase_review.py", args)
    if command == "device":
        return _run("run_device.py", args)
    if command == "verify":
        return _run("workflow.py", ["verify", "--repo", str(REPO_ROOT), *args])
    if command == "pm":
        if not args or args[0] in {"-h", "--help"}:
            return _run("pm_discovery.py", args or ["--help"])
        forwarded = list(args)
        if "--repo" not in forwarded:
            forwarded = [forwarded[0], "--repo", str(REPO_ROOT), *forwarded[1:]]
        return _run("pm_discovery.py", forwarded)
    if command == "report-issue":
        forwarded = list(args)
        if "--repo" not in forwarded:
            forwarded = ["--repo", str(REPO_ROOT), *forwarded]
        return _run("incident_reporter.py", forwarded)
    if command == "zoho":
        return _run("zoho_sync.py", args)

    print(f"[ERROR] Unknown installed harness command: {command}", file=sys.stderr)
    if command in TASK_SUBCOMMANDS:
        print(f"Did you mean: python .agents/harness.py task {command} {' '.join(args)}".rstrip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
