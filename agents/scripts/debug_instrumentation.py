"""Task-owned diagnostic writes and whole-build delivery checks."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid

from _vnext_common import (HarnessError, ValidationError, atomic_write_json, git, read_json,
                           sha256_bytes, state_root, task_dir, utc_now)
from debug_source import make_insertion
from evidence_store import StateLock


def ledger_path(repo, plan):
    return task_dir(repo, plan["task_id"]) / "debug" / "ledger.json"


def ledger(repo, plan):
    path = ledger_path(repo, plan)
    return read_json(path) if path.exists() else {"entries": [], "attempts": []}


def source(repo, plan, relative):
    from delivery_manifest import live_task_plans, task_owned_files
    from pre_tool_safety import _safe_target
    lexical = repo / relative
    path = lexical.resolve()
    if any(part.is_symlink() for part in (lexical, *lexical.parents) if part != repo and part.is_relative_to(repo)):
        raise ValidationError("Diagnostic source through a symlink is unsupported")
    if not path.is_relative_to(repo) or path.suffix not in {".kt", ".java"}:
        raise ValidationError("Expected repository Kotlin or Java source")
    rel = path.relative_to(repo).as_posix()
    allowed, reason, external = _safe_target(str(path), repo)
    if not allowed or external or set(p.lower() for p in Path(rel).parts) & {".git", ".agents", "build", "generated"}:
        raise ValidationError(f"Protected diagnostic path: {rel} ({reason})")
    if len(live_task_plans(repo)) > 1 and os.path.normcase(rel) not in {
        os.path.normcase(p) for p in task_owned_files(repo, plan["task_id"], plan)
    }:
        raise ValidationError(f"ACTIVE_TASK_CONFLICT: {rel} is outside the focused task")
    return path


def replace_current(path, old, new):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        tmp = Path(temp.name)
    try:
        tmp.write_bytes(new)
        tmp.chmod(stat.S_IMODE(path.stat().st_mode))
        if path.read_bytes() != old:
            raise ValidationError(f"Source changed during debug edit: save and retry {path.name}")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def reconcile(repo, book):
    for entry in book["entries"]:
        if entry["state"] not in {"PENDING", "APPLIED"}:
            continue
        path = (repo / entry["path"]).resolve()
        if not path.is_relative_to(repo):
            raise ValidationError("Ledger path escapes repository")
        data = path.read_bytes() if path.is_file() else b""
        if entry["id"].encode() in data:
            entry["state"] = "APPLIED"
        else:
            entry["state"] = "REMOVED" if entry["state"] == "PENDING" else "LOST"


def add(repo, plan, relative, anchor, before, occurrence, label, values, hypothesis):
    dest = ledger_path(repo, plan)
    with StateLock(dest.parent):
        path = source(repo, plan, relative)
        book = ledger(repo, plan)
        reconcile(repo, book)
        attempts = book["attempts"]
        if not attempts or attempts[-1].get("read_at"):
            attempts.append({"id": f"a{len(attempts)+1}", "hypothesis": hypothesis, "opened_at": utc_now()})
        ident = uuid.uuid4().hex
        data = path.read_bytes()
        new, line, end = make_insertion(data, path, anchor, before, occurrence, label, values, ident)
        entry = {"id": ident, "attempt": attempts[-1]["id"], "path": path.relative_to(repo).as_posix(),
                 "line_text": line, "eol": end, "state": "PENDING",
                 "file_sha256_before": sha256_bytes(data), "file_sha256_after": sha256_bytes(new)}
        book["entries"].append(entry)
        atomic_write_json(dest, book)
        try:
            replace_current(path, data, new)
        except ValidationError:
            data = path.read_bytes()
            new, line, end = make_insertion(data, path, anchor, before, occurrence, label, values, ident)
            entry.update(line_text=line, eol=end, file_sha256_before=sha256_bytes(data), file_sha256_after=sha256_bytes(new))
            atomic_write_json(dest, book)
            replace_current(path, data, new)
        entry["state"] = "APPLIED"
        atomic_write_json(dest, book)
        return entry


def strip(repo, plan, attempt=None):
    dest = ledger_path(repo, plan)
    if not dest.is_file():
        return []
    with StateLock(dest.parent):
        book = ledger(repo, plan)
        for entry in book["entries"]:
            if entry["state"] == "REMOVED" or attempt and entry["attempt"] != attempt:
                continue
            path = source(repo, plan, entry["path"])
            data = path.read_bytes() if path.exists() else b""
            lines = data.splitlines(keepends=True)
            matches = [i for i, line in enumerate(lines) if entry["id"].encode() in line]
            if len(matches) == 1 and lines[matches[0]].strip() == entry["line_text"].encode().strip():
                del lines[matches[0]]
                replace_current(path, data, b"".join(lines))
            elif matches:
                entry["state"] = "CONFLICT"
                atomic_write_json(dest, book)
                continue
            entry["state"] = "REMOVED"
            atomic_write_json(dest, book)
        return [e["path"] for e in book["entries"] if e["state"] == "CONFLICT"]


def assert_clean(repo, plan):
    """Use all task ledgers; never clean a sibling's file."""
    for dest in (state_root(repo) / "tasks").glob("*/debug/ledger.json"):
        owner = dest.parents[1].name
        book = read_json(dest)
        # Inspect without modifying another task's ledger. A developer can resolve
        # a cancelled task's conflict manually without reopening that task.
        for entry in book["entries"]:
            if entry["state"] in {"APPLIED", "CONFLICT"}:
                path = (repo / entry["path"]).resolve()
                if path.is_relative_to(repo) and (not path.is_file() or entry["id"].encode() not in path.read_bytes()):
                    continue
            if entry["state"] in {"PENDING", "APPLIED", "CONFLICT"}:
                raise ValidationError(f"DEBUG_INSTRUMENTATION_PRESENT: {owner}: {entry['path']}. "
                                      f"Resolve in owner task {owner} with debug strip or manual cleanup.")
    specs = ["*.kt", "*.java"]
    base = plan.get("task_base_head") or (plan.get("repository") or {}).get("head")
    diff = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "-U0",
               *([base] if base else []), "--", *specs)
    marker = re.compile(rb"HARNESS-DEBUG|HarnessDbg")
    filename = ""
    number = 0
    for line in diff.splitlines():
        if line.startswith(b"+++ "):
            filename = line[4:].decode(errors="replace")
        elif line.startswith(b"@@"):
            number = int(re.match(rb"@@ -\d+(?:,\d+)? \+(\d+)", line)[1])
        elif line.startswith(b"+"):
            if marker.search(line):
                raise ValidationError(f"DEBUG_INSTRUMENTATION_PRESENT: {filename}:{number}. Remove manual marker.")
            number += 1
    for relative in git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", *specs).split(b"\0"):
        if relative:
            path = repo / os.fsdecode(relative)
            if path.is_symlink() or not path.is_file():
                continue
            for number, line in enumerate(path.read_bytes().splitlines(), 1):
                if marker.search(line):
                    raise ValidationError(f"DEBUG_INSTRUMENTATION_PRESENT: {os.fsdecode(relative)}:{number}. Remove manual marker.")


def regression_guard(repo, plan, manifest):
    book = ledger(repo, plan)
    if not book["entries"] or str(plan.get("task_kind") or plan.get("kind", "")).upper() == "BUG":
        return
    from _modules import is_kmp_or_android_test_path
    if any(is_kmp_or_android_test_path(e["path"]) and (repo / e["path"]).is_file() for e in manifest.get("task_changes", [])):
        return
    evidence = task_dir(repo, plan["task_id"]) / "debug-evidence.json"
    if evidence.exists() and any(e.get("kind") == "limited" and e.get("reference") and
                                 e.get("recorded_at", "") >= book["attempts"][-1]["opened_at"]
                                 for e in read_json(evidence)["entries"]):
        return
    raise ValidationError("DEBUG_REGRESSION_TEST_REQUIRED: add a regression test or record debug-evidence --kind limited with a reason")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    s = sub.add_parser("add")
    s.add_argument("--file", required=True)
    direction = s.add_mutually_exclusive_group(required=True)
    for arg in ("--before", "--after"):
        direction.add_argument(arg)
    s.add_argument("--label", required=True)
    s.add_argument("--occurrence", type=int)
    s.add_argument("--value", action="append", default=[])
    s.add_argument("--hypothesis", default="")
    sub.add_parser("strip").add_argument("--attempt")
    for name in ("logs", "arm", "install"):
        s = sub.add_parser(name)
        s.add_argument("--device")
        if name == "logs":
            s.add_argument("--all", action="store_true")
            s.add_argument("--max-lines", type=int)
            s.add_argument("--grep")
        if name == "install":
            s.add_argument("--allow-downgrade", action="store_true")
    args = parser.parse_args(argv)
    from mutation_guard import active_plan
    from plan_authority import require_mutation
    from host_continuation import assert_execution_session
    from delivery_manifest import assert_disjoint_task_scope
    repo = Path.cwd().resolve()
    plan = active_plan(repo, allow_missing=args.action in {"status", "logs"})
    if args.action in {"add", "strip", "install"}:
        require_mutation(plan)
        assert_disjoint_task_scope(repo, plan["task_id"], plan)
    if plan and args.action != "status":
        assert_execution_session(repo, plan["task_id"])
    if args.action == "status":
        result = ledger(repo, plan) if plan else {"entries": [], "attempts": []}
        reconcile(repo, result)
        if plan:
            session = ledger_path(repo, plan).parent / "session.json"
            result["last_session"] = read_json(session) if session.exists() else None
    elif args.action == "add":
        result = add(repo, plan, args.file, args.before or args.after, args.before is not None,
                     args.occurrence, args.label, args.value, args.hypothesis)
    elif args.action == "strip":
        result = strip(repo, plan, args.attempt)
        if result:
            raise ValidationError(f"CONFLICT: edit manually: {result}")
    else:
        from debug_device import device_action
        result = device_action(repo, plan, args)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HarnessError, OSError, UnicodeError, ValueError) as exc:
        from _vnext_common import redact_text
        sys.exit(redact_text(str(exc)))
