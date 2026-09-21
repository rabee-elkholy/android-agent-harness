"""CLI entry point for project context generation, status checking, and refreshing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_context import (  # noqa: E402
    ContextSourceChangedDuringExtraction,
    extract_consistent_project_context,
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
        print(json.dumps(payload if args.full else summarize_preview(payload), ensure_ascii=False, indent=2))
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


def summarize_preview(payload: dict) -> dict:
    """Return a bounded discovery summary; full facts stay local and opt-in."""
    facts = payload.get("facts") or {}
    architecture = facts.get("architecture") or {}
    advisory = payload.get("advisory_knowledge") or {}
    families = architecture.get("families") or []
    persistence = facts.get("persistence") or {}
    ui = facts.get("ui") or {}
    modules = facts.get("modules") or []
    return {
        "schema_version": payload.get("schema_version"),
        "extractor_version": payload.get("extractor_version"),
        "context_fingerprint_sha256": payload.get("context_fingerprint_sha256"),
        "source_fingerprint_sha256": payload.get("source_fingerprint_sha256"),
        "summary": {
            "modules": modules,
            "ui_framework": ui.get("framework", "unknown"),
            "room_databases": [
                {"symbol": item.get("symbol"), "version": item.get("version"), "path": item.get("path")}
                for item in (persistence.get("room_databases") or [])
            ],
            "architecture_family_count": len(families),
            "representative_families": [
                {
                    "id": item.get("id"), "label": item.get("label"),
                    "confidence": item.get("confidence"),
                    "exemplars": list(item.get("exemplars") or [])[:2],
                }
                for item in families[:8]
            ],
            "local_profile_count": len(advisory.get("local_profiles") or []),
            "convention_profile_count": len(advisory.get("convention_profiles") or []),
        },
        "full_payload_available": True,
        "full_payload_command": "context preview --full --json",
    }


def cmd_generate(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    try:
        payload = extract_consistent_project_context(repo, in_memory_graph=True)
    except ContextSourceChangedDuringExtraction as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
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

    try:
        new_payload = extract_consistent_project_context(repo, in_memory_graph=True)
    except ContextSourceChangedDuringExtraction as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
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


def cmd_instruct(args: argparse.Namespace) -> int:
    import hashlib
    import time
    repo = Path(args.repo).resolve()
    context_dir = repo / ".agents" / "project-context"
    inst_file = context_dir / "developer-instructions.json"
    if not context_dir.is_dir():
        context_dir.mkdir(parents=True, exist_ok=True)

    text = (getattr(args, "instruction", None) or getattr(args, "text", None) or "").strip()
    if not text:
        print("[ERROR] Instruction text cannot be empty.", file=sys.stderr)
        return 1

    source = getattr(args, "source", None)
    proof_ref = getattr(args, "proof_reference", None)
    if not source or source not in ("conversation", "developer_terminal", "host_native"):
        print("[ERROR] Mandatory --source must be one of: conversation, developer_terminal, host_native.", file=sys.stderr)
        return 1
    if not proof_ref or not str(proof_ref).strip():
        print("[ERROR] Mandatory --proof-reference cannot be empty.", file=sys.stderr)
        return 1

    raw_scope = (getattr(args, "scope", None) or "GLOBAL").strip()
    scope_val_arg = getattr(args, "scope_value", None)
    if scope_val_arg:
        scope_kind = raw_scope
        scope_val = str(scope_val_arg).strip()
    elif "::" in raw_scope:
        scope_kind, scope_val = raw_scope.split("::", 1)
    elif ":" in raw_scope and not raw_scope.startswith(":"):
        scope_kind, scope_val = raw_scope.split(":", 1)
    elif raw_scope.startswith(":"):
        scope_kind = "MODULE"
        scope_val = raw_scope
    elif raw_scope.upper() in ("GLOBAL", "*"):
        scope_kind = "GLOBAL"
        scope_val = "*"
    elif raw_scope.upper() in ("MODULE", "PACKAGE", "FEATURE", "SOURCE_SET", "ARCH_FAMILY", "PATH"):
        scope_kind = raw_scope.upper()
        scope_val = "*"
    else:
        scope_kind = "GLOBAL"
        scope_val = raw_scope

    scope_kind = scope_kind.upper()
    if scope_kind == "MODULE" and scope_val != "*" and not scope_val.startswith(":"):
        scope_val = f":{scope_val}"

    if scope_kind not in ("GLOBAL", "MODULE", "SOURCE_SET", "PACKAGE", "FEATURE", "ARCH_FAMILY", "PATH"):
        print(f"[ERROR] Unsupported scope kind: {scope_kind}", file=sys.stderr)
        return 1

    strength = (getattr(args, "strength", None) or "REQUIREMENT").strip().upper()
    if strength not in ("REQUIREMENT", "PREFERENCE"):
        strength = "REQUIREMENT"

    applies_to_raw = getattr(args, "applies_to", None) or "ANY"
    if isinstance(applies_to_raw, str):
        applies_to = [s.strip().upper() for s in applies_to_raw.split(",") if s.strip()]
    else:
        applies_to = list(applies_to_raw)
    if not applies_to:
        applies_to = ["ANY"]

    supersedes_id = getattr(args, "supersedes", None)

    existing_store: dict[str, Any] = {"schema_version": 1, "instructions": []}
    if inst_file.is_file():
        try:
            loaded = json.loads(inst_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("instructions"), list):
                existing_store = loaded
        except Exception:
            pass

    if supersedes_id:
        for old_inst in existing_store["instructions"]:
            if old_inst.get("id") == supersedes_id:
                old_inst["status"] = "SUPERSEDED"

    content_material = f"{scope_kind}:{scope_val}:{strength}:{','.join(sorted(applies_to))}:{text}"
    content_sha = hashlib.sha256(content_material.encode("utf-8")).hexdigest()
    inst_id = f"pi-{content_sha[:8]}"
    proof_sha = hashlib.sha256(str(proof_ref).encode("utf-8")).hexdigest()

    new_inst = {
        "id": inst_id,
        "text": text,
        "scope": {
            "kind": scope_kind,
            "value": scope_val,
        },
        "applies_to": applies_to,
        "strength": strength,
        "source": source,
        "proof_reference": str(proof_ref),
        "proof_reference_sha256": proof_sha,
        "sha256": content_sha,
        "created_at": time.time(),
        "status": "ACTIVE",
    }

    instructions = [i for i in existing_store["instructions"] if i.get("id") != inst_id]
    instructions.append(new_inst)
    existing_store["instructions"] = instructions

    from _vnext_common import atomic_write_json
    atomic_write_json(inst_file, existing_store)

    ret_payload = {"status": "PASS", "id": inst_id, "instruction": new_inst, "path": str(inst_file)}
    if getattr(args, "json", False):
        print(json.dumps(ret_payload, ensure_ascii=False))
    else:
        print(f"[INSTRUCT] Recorded persistent instruction '{inst_id}' for scope {scope_kind}:{scope_val}")
    return ret_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_prev = sub.add_parser("preview")
    p_prev.add_argument("--repo", default=".")
    p_prev.add_argument("--json", action="store_true")
    p_prev.add_argument("--full", action="store_true", help="Print the complete unbounded diagnostic payload")

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

    p_inst = sub.add_parser("instruct")
    p_inst.add_argument("text", nargs="?", default="", help="Instruction text")
    p_inst.add_argument("--instruction", default="", help="Instruction text")
    p_inst.add_argument("--scope", default="GLOBAL", help="Instruction scope (e.g. module::payments, package:com.example, global)")
    p_inst.add_argument("--scope-value", default=None, help="Instruction scope value")
    p_inst.add_argument("--source", choices=("conversation", "developer_terminal", "host_native"), default=None, help="Explicit developer authority source")
    p_inst.add_argument("--proof-reference", default="", help="Message or command reference proving developer request")
    p_inst.add_argument("--strength", choices=("REQUIREMENT", "PREFERENCE"), default="REQUIREMENT")
    p_inst.add_argument("--applies-to", default="ANY", help="Comma-separated applicable intents (ANY, PRESERVE, NEW, REFACTOR, MIGRATION)")
    p_inst.add_argument("--supersedes", default=None, help="Prior instruction ID to supersede")
    p_inst.add_argument("--repo", default=".")
    p_inst.add_argument("--json", action="store_true")

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
    if args.command == "instruct":
        ret = cmd_instruct(args)
        return 0 if (isinstance(ret, dict) and ret.get("status") == "PASS") or ret == 0 else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
