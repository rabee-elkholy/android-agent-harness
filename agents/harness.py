"""Stable repository-local entrypoint for an installed Android Agent Harness."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


AGENTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = AGENTS_ROOT.parent
SCRIPTS = AGENTS_ROOT / "scripts"


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


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in {"-h", "--help", "help"}:
        print(
            "Usage: python .agents/harness.py "
            "<context|task-context|graph|task|doctor|preflight|test|assemble|review|device|verify|version|commands> [args...]"
        )
        return 0

    command = args.pop(0)
    if command == "version":
        version_file = AGENTS_ROOT / "VERSION"
        if not version_file.is_file():
            print("[ERROR] Installed harness VERSION is missing", file=sys.stderr)
            return 2
        print(version_file.read_text(encoding="utf-8").strip())
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
            try:
                from _variants import resolve_assemble_task
                task_str = resolve_assemble_task(REPO_ROOT)
            except Exception:
                task_str = ":app:assembleDebug"
            forwarded = [task_str]
        return _run("run_gradle_task.py", forwarded)
    if command == "review":
        if args and args[0] == "package":
            return _run("review_package.py", args[1:])
        if args and args[0] == "profile":
            return _run("review_execution.py", args[1:])
        if args and args[0] == "ingest":
            return _run("record_review.py", args[1:])
        return _run("record_review.py", args)
    if command == "device":
        return _run("run_device.py", args)
    if command == "verify":
        return _run("workflow.py", ["verify", "--repo", str(REPO_ROOT), *args])

    print(f"[ERROR] Unknown installed harness command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
