"""CLI entry point for project context generation, status checking, and refreshing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_context import (  # noqa: E402
    extract_project_facts,
    project_context_diff,
    project_context_status,
    render_project_context,
    write_project_context,
)


def cmd_preview(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    payload = extract_project_facts(repo, in_memory_graph=True)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    facts = payload.get("facts") or {}
    di = facts.get("di") or {}
    vm = facts.get("view_models") or {}
    pers = facts.get("persistence") or {}
    ui = facts.get("ui") or {}
    nav = facts.get("navigation") or {}
    caps = facts.get("capabilities") or {}

    print("==================================================")
    print("Project Context Preview (Read-Only)")
    print(f"  Target: {repo}")
    print("==================================================")
    print(f"  DI Framework      : {di.get('framework', 'unknown').upper()}")
    primary_vm = vm.get("primary")
    if primary_vm:
        print(f"  Primary BaseVM    : {primary_vm.get('symbol')} ({primary_vm.get('path')})")
    else:
        cands = vm.get("candidates") or []
        if cands:
            cand_names = ", ".join(c.get("symbol", "") for c in cands)
            print(f"  BaseVM Resolution : {vm.get('resolution')} (candidates: {cand_names})")
        else:
            print(f"  BaseVM Resolution : {vm.get('resolution')} (0 candidates)")

    dbs = pers.get("room_databases") or []
    if dbs:
        db_strs = [f"{d.get('symbol')} (v{d.get('version')})" for d in dbs]
        print(f"  Room Databases    : {', '.join(db_strs)}")
    else:
        print("  Room Databases    : None detected")

    print(f"  UI Paradigm       : {ui.get('framework', 'unknown').upper()}")
    themes = ui.get("themes") or []
    if themes:
        print(f"  Compose Themes    : {', '.join(t.get('symbol') for t in themes)}")

    arch = facts.get("architecture") or {}
    families = arch.get("families") or []
    if families:
        print(f"  Architecture Fam. : {len(families)} detected")
        for fam in families:
            print(f"    - {fam.get('id')}: {fam.get('label')} (conf: {fam.get('confidence')})")

    nav_elems = nav.get("elements") or []
    print(f"  Navigation Routes : {len(nav_elems)} element(s) indexed")

    detected_caps = [k for k, v in caps.items() if v.get("detected")]
    print(f"  Capabilities      : {', '.join(detected_caps) if detected_caps else 'Standard Android'}")
    print("==================================================")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    payload = extract_project_facts(repo, in_memory_graph=True)
    views = render_project_context(payload)
    out_dir = write_project_context(repo, payload, views)
    if args.json:
        print(json.dumps({"status": "PASS", "path": str(out_dir), "payload": payload}, ensure_ascii=False, indent=2))
    else:
        print(f"[SUCCESS] Project context generated at {out_dir}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    res = project_context_status(repo)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        status = res.get("status")
        msg = res.get("message", "")
        print(f"[{status}] {msg}")
    return 0 if res.get("status") == "CURRENT" else 1


def cmd_refresh(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    old_facts_file = repo / ".agents" / "project-context" / "project-facts.json"
    old_payload = {}
    if old_facts_file.is_file():
        try:
            old_payload = json.loads(old_facts_file.read_text(encoding="utf-8"))
        except Exception:
            old_payload = {}

    new_payload = extract_project_facts(repo, in_memory_graph=True)
    diff = project_context_diff(old_payload, new_payload) if old_payload else {"kind": "INITIAL", "has_drift": False, "details": []}
    views = render_project_context(new_payload)
    out_dir = write_project_context(repo, new_payload, views)

    if args.json:
        print(json.dumps({"status": "PASS", "diff": diff, "path": str(out_dir)}, ensure_ascii=False, indent=2))
    else:
        print(f"[REFRESH] Project context refreshed at {out_dir} (diff: {diff.get('kind')})")
        for d in diff.get("details", []):
            print(f"  - {d}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    import re
    repo = Path(args.repo).resolve()
    context_dir = repo / ".agents" / "project-context"
    notes_file = context_dir / "project-notes.md"
    if not context_dir.is_dir():
        context_dir.mkdir(parents=True, exist_ok=True)
    text = (getattr(args, "note", None) or getattr(args, "text", None) or "").strip()
    if not text:
        print("[ERROR] Note text cannot be empty.")
        return 1
    section = (getattr(args, "section", None) or "Domain Conventions & Context").strip()
    if not notes_file.is_file():
        initial_content = [
            "# Human-Authored Project Architectural Notes",
            "",
            "> This file is owned and maintained by the project engineering team.",
            "> When instructed by the developer, AI agents may append or update project notes and conventions here.",
            "",
            f"## {section}",
            f"- {text}",
            "",
        ]
        notes_file.write_text("\n".join(initial_content), encoding="utf-8")
    else:
        content = notes_file.read_text(encoding="utf-8")
        sec_pattern = rf"(##\s+{re.escape(section)}[^\n]*\n)"
        if re.search(sec_pattern, content):
            updated = re.sub(sec_pattern, rf"\1- {text}\n", content, count=1)
        else:
            updated = content.rstrip() + f"\n\n## {section}\n- {text}\n"
        notes_file.write_text(updated, encoding="utf-8")

    if getattr(args, "json", False):
        print(json.dumps({"status": "PASS", "path": str(notes_file), "note": text, "section": section}, ensure_ascii=False))
    else:
        print(f"[NOTE] Added note to {notes_file} under section '{section}'")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_prev = sub.add_parser("preview")
    p_prev.add_argument("--repo", default=".")
    p_prev.add_argument("--json", action="store_true")

    p_gen = sub.add_parser("generate")
    p_gen.add_argument("--repo", default=".")
    p_gen.add_argument("--json", action="store_true")

    p_stat = sub.add_parser("status")
    p_stat.add_argument("--repo", default=".")
    p_stat.add_argument("--json", action="store_true")

    p_ref = sub.add_parser("refresh")
    p_ref.add_argument("--repo", default=".")
    p_ref.add_argument("--json", action="store_true")

    p_note = sub.add_parser("note")
    p_note.add_argument("text", nargs="?", default="", help="Note text to append")
    p_note.add_argument("--note", default="", help="Note text to append")
    p_note.add_argument("--section", default="Domain Conventions & Context", help="Section header to place note under")
    p_note.add_argument("--repo", default=".")
    p_note.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "preview":
        return cmd_preview(args)
    if args.command == "generate":
        return cmd_generate(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "refresh":
        return cmd_refresh(args)
    if args.command == "note":
        return cmd_note(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
