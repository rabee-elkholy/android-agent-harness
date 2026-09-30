"""Stable repository-local entrypoint for an installed Android Agent Harness."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


AGENTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = AGENTS_ROOT.parent
SCRIPTS = AGENTS_ROOT / "scripts"
TASK_SUBCOMMANDS = frozenset({
    "draft", "revise", "checkpoint-phase", "begin-next-phase", "present-plan", "approve", "approve-sensitive",
    "begin", "debug-evidence", "validate-finding", "prepare-verification", "complete", "deliver", "cancel",
    "resume", "handoff", "reconcile-handoff", "reconcile-delivery", "status", "recover-stale", "recover-active",
})


def _run(script: str, args: list[str]) -> int:
    target = SCRIPTS / script
    if not target.is_file():
        print(f"[ERROR] Installed harness script is missing: {target}", file=sys.stderr)
        return 2
    proc = subprocess.run(
        [sys.executable, "-u", str(target), *args],
        cwd=str(REPO_ROOT),
        check=False,
    )
    return proc.returncode


# Commands after which the agent needs the next step. A real delivery called `task status --next --json`
# after each of them (six times from review finalize to ready), one extra model turn each.
# `verify` prints a JSON report and is left out so its output stays parseable.
NEXT_STEP_COMMANDS = frozenset({"preflight", "test", "assemble", "device", "review"})


def _print_next_step() -> None:
    """Print the active task's next action as NEXT_ACTION= / NEXT_REASON= (best effort, never fails)."""
    import contextlib
    import io

    try:
        sys.path.insert(0, str(SCRIPTS))
        from mutation_guard import active_plan

        plan = active_plan(REPO_ROOT) or {}
        task_id = str(plan.get("task_id") or "")
        if not task_id or str(plan.get("status") or "") in ("", "DELIVERED", "CANCELLED"):
            return
        from workflow import resolve_next_action

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            action = resolve_next_action(REPO_ROOT, task_id, plan)
    except Exception:
        return
    code = str(action.get("code") or "")
    if not code:
        return
    command = str(action.get("command") or "")
    if code.startswith("DISPATCH_") or code.startswith("RETRY_"):
        command = f"python .agents/harness.py task status --task-id {task_id} --next --json (for the exact payload)"
    print(f"NEXT_ACTION={code}: {command or '(no command: ' + str(action.get('kind') or 'action') + ')'}", flush=True)
    if action.get("reason"):
        print(f"NEXT_REASON={action['reason']}", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    code = _main(args)
    # Never after --json (the output must stay pure JSON) or help.
    if args and args[0] in NEXT_STEP_COMMANDS and not {"--json", "-h", "--help"} & set(args):
        _print_next_step()
    return code


def _main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in {"-h", "--help", "help"}:
        print(
            "Usage: python .agents/harness.py "
            "<context|task-context|graph|task|doctor|preflight|test|compile|assemble|review|phase-review|device|verify|zoho|version|update-info|commands> [args...]"
        )
        return 0

    command = args.pop(0)
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
            print("[ERROR] context requires preview, generate, status, refresh, or note", file=sys.stderr)
            return 2
        return _run("generate_project_context.py", [args[0], "--repo", str(REPO_ROOT), *args[1:]])
    if command == "task-context":
        return _run("task_context.py", ["--repo", str(REPO_ROOT), *args])
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
        if not forwarded:
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
        if args and args[0] == "package":
            return _run("review_package.py", args[1:])
        if args and args[0] == "profile":
            return _run("review_execution.py", args[1:])
        if args and args[0] == "ingest":
            return _run("record_review.py", args[1:])
        if args and args[0] in ("complete", "finalize", "dispatch", "dispatch-batch", "status"):
            return _run("review_orchestrator.py", args)
        return _run("record_review.py", args)
    if command == "phase-review":
        return _run("phase_review.py", args)
    if command == "device":
        return _run("run_device.py", args)
    if command == "verify":
        return _run("workflow.py", ["verify", "--repo", str(REPO_ROOT), *args])
    if command == "zoho":
        return _run("zoho_sync.py", args)

    print(f"[ERROR] Unknown installed harness command: {command}", file=sys.stderr)
    if command in TASK_SUBCOMMANDS:
        print(f"Did you mean: python .agents/harness.py task {command} {' '.join(args)}".rstrip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
