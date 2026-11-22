"""CLI entry point for project context generation, status checking, and refreshing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_context import (  # noqa: E402
    ContextSourceChangedDuringExtraction,
    check_living_context_drift,
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


def _strip_backticks(value: str) -> str:
    return value.replace("`", "")


def _line_matches_note(stripped: str, raw_target: str, norm_target: str, *, strip_bt: bool = False) -> bool:
    norm_line = stripped.lstrip("-* ").strip()
    cmp_line = _strip_backticks(norm_line) if strip_bt else norm_line
    cmp_target = _strip_backticks(norm_target) if strip_bt else norm_target
    return (
        (not strip_bt and stripped == raw_target)
        or cmp_line == cmp_target
        or (len(cmp_target) >= 8 and cmp_target in cmp_line)
    )


def _resolve_note_section(content: str, requested: str) -> str:
    import re
    if re.search(rf"^##\s+{re.escape(requested)}[^\n]*$", content, flags=re.MULTILINE):
        return requested
    req_nb = _strip_backticks(requested).strip()
    headings = [m.strip() for m in re.findall(r"^##\s+([^\n]+)", content, flags=re.MULTILINE)]
    for heading in headings:
        if _strip_backticks(heading) == req_nb:
            return heading
    req_low = req_nb.lower()
    for heading in headings:
        if _strip_backticks(heading).lower() == req_low:
            return heading
    if len(req_low) >= 6:
        for heading in headings:
            if _strip_backticks(heading).lower().startswith(req_low):
                return heading
    return requested


def cmd_note(args: argparse.Namespace) -> int:
    import re
    from _vnext_common import atomic_write_text
    repo = Path(args.repo).resolve()
    context_dir = repo / ".agents" / "project-context"
    notes_file = context_dir / "project-notes.md"
    if not context_dir.is_dir():
        context_dir.mkdir(parents=True, exist_ok=True)
    remove_target = (getattr(args, "remove", None) or "").strip()
    replace_target = (getattr(args, "replace", None) or "").strip()
    text = (getattr(args, "note", None) or getattr(args, "text", None) or "").strip()
    note_file_arg = (getattr(args, "note_file", None) or "").strip()
    section = (getattr(args, "section", None) or "Domain Conventions & Context").strip()

    if note_file_arg:
        if text:
            print("[ERROR] Cannot pass both inline note text and --note-file in the same note command.", file=sys.stderr)
            return 1
        nf_path = Path(note_file_arg).expanduser()
        if not nf_path.is_absolute():
            nf_path = repo / nf_path
        if nf_path.is_symlink():
            print(f"[ERROR] Refusing symlink --note-file: {note_file_arg}", file=sys.stderr)
            return 1
        nf_resolved = nf_path.resolve()
        if nf_resolved.is_symlink() or not nf_resolved.is_file():
            print(f"[ERROR] Note file does not exist or is not a regular file: {note_file_arg}", file=sys.stderr)
            return 1
        text = nf_resolved.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()

    if remove_target and replace_target:
        print("[ERROR] Cannot pass both --remove and --replace in the same note command.", file=sys.stderr)
        return 1

    if remove_target:
        if not notes_file.is_file():
            print(f"[ERROR] Project notes file does not exist: {notes_file}", file=sys.stderr)
            return 1
        content = notes_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        new_lines = []
        removed_count = 0
        norm_target = remove_target.lstrip("-* ").strip()
        for strip_bt in (False, True):
            new_lines = []
            removed_count = 0
            for line in lines:
                if _line_matches_note(line.strip(), remove_target, norm_target, strip_bt=strip_bt):
                    removed_count += 1
                    continue
                new_lines.append(line)
            if removed_count > 0:
                break
        if removed_count == 0:
            if remove_target in content:
                updated = content.replace(remove_target, "").strip() + "\n"
                removed_count = 1
            elif _strip_backticks(remove_target) and _strip_backticks(remove_target) in _strip_backticks(content):
                print(f"[ERROR] Target note spans multiple formatting blocks cleanly; narrow --remove text: {remove_target}", file=sys.stderr)
                return 1
            else:
                print(f"[ERROR] Target note text not found in {notes_file}: {remove_target}", file=sys.stderr)
                return 1
        else:
            updated = "\n".join(new_lines).rstrip() + "\n"
        atomic_write_text(notes_file, updated)
        if getattr(args, "json", False):
            print(json.dumps({"status": "PASS", "action": "REMOVED", "path": str(notes_file), "removed": remove_target, "count": removed_count}, ensure_ascii=False))
        else:
            print(f"[NOTE] Removed {removed_count} note entry/entries matching '{remove_target}' from {notes_file}")
        return 0

    if replace_target:
        if not text:
            print("[ERROR] Replacement note text cannot be empty when using --replace.", file=sys.stderr)
            return 1
        if not notes_file.is_file():
            print(f"[ERROR] Project notes file does not exist: {notes_file}", file=sys.stderr)
            return 1
        content = notes_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        new_lines = []
        replaced_count = 0
        norm_target = replace_target.lstrip("-* ").strip()
        clean_replacement = text.lstrip("-* ").strip()
        for strip_bt in (False, True):
            new_lines = []
            replaced_count = 0
            for line in lines:
                stripped = line.strip()
                if replaced_count == 0 and _line_matches_note(stripped, replace_target, norm_target, strip_bt=strip_bt):
                    prefix = "- " if stripped.startswith(("-", "*")) or not text.startswith(("#", "-", "*")) else ""
                    new_lines.append(f"{prefix}{clean_replacement if prefix else text}")
                    replaced_count += 1
                else:
                    new_lines.append(line)
            if replaced_count > 0:
                break
        if replaced_count == 0:
            if replace_target in content:
                updated = content.replace(replace_target, text, 1)
                replaced_count = 1
            else:
                print(f"[ERROR] Target note text not found in {notes_file}: {replace_target}", file=sys.stderr)
                return 1
        else:
            updated = "\n".join(new_lines).rstrip() + "\n"
        atomic_write_text(notes_file, updated)
        if getattr(args, "json", False):
            print(json.dumps({"status": "PASS", "action": "REPLACED", "path": str(notes_file), "replaced": replace_target, "note": text}, ensure_ascii=False))
        else:
            print(f"[NOTE] Updated note in {notes_file}")
        return 0

    if not text:
        print("[ERROR] Note text cannot be empty.")
        return 1
    resolved_section = section
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
        atomic_write_text(notes_file, "\n".join(initial_content))
    else:
        content = notes_file.read_text(encoding="utf-8")
        resolved_section = _resolve_note_section(content, section)
        norm_new = text.lstrip("-* ").strip()
        sec_block_match = re.search(
            rf"(^##\s+{re.escape(resolved_section)}[^\n]*\n)(.*?)(?=^##\s+|\Z)",
            content,
            flags=re.MULTILINE | re.DOTALL,
        )
        if sec_block_match:
            existing_bullets = {
                ln.strip().lstrip("-* ").strip()
                for ln in sec_block_match.group(2).splitlines()
                if ln.strip().startswith(("-", "*"))
            }
            existing_nb = {_strip_backticks(b) for b in existing_bullets}
            if norm_new and (norm_new in existing_bullets or _strip_backticks(norm_new) in existing_nb):
                if getattr(args, "json", False):
                    print(json.dumps({"status": "PASS", "action": "UNCHANGED_DUPLICATE", "path": str(notes_file), "note": text, "section": resolved_section}, ensure_ascii=False))
                else:
                    print(f"[NOTE] Note already present in {notes_file} under section '{resolved_section}'")
                return 0
        sec_pattern = rf"(##\s+{re.escape(resolved_section)}[^\n]*\n)"
        if re.search(sec_pattern, content):
            updated = re.sub(sec_pattern, lambda m: f"{m.group(1)}- {norm_new}\n", content, count=1)
        else:
            updated = content.rstrip() + f"\n\n## {resolved_section}\n- {norm_new}\n"
        atomic_write_text(notes_file, updated)

    if getattr(args, "json", False):
        print(json.dumps({"status": "PASS", "action": "ADDED", "path": str(notes_file), "note": text, "section": resolved_section}, ensure_ascii=False))
    else:
        print(f"[NOTE] Added note to {notes_file} under section '{resolved_section}'")
    return 0


_VALID_INSTRUCTION_SCOPE_KINDS = (
    "GLOBAL",
    "MODULE",
    "SOURCE_SET",
    "PACKAGE",
    "FEATURE",
    "ARCH_FAMILY",
    "PATH",
)


def _parse_instruction_scope(raw_scope: str, scope_val_arg: str | None = None) -> tuple[str, str]:
    """Parse scope string and optional explicit value into canonical `(scope_kind, scope_value)`."""
    raw = str(raw_scope or "GLOBAL").strip() or "GLOBAL"
    if scope_val_arg is not None and str(scope_val_arg).strip():
        scope_kind = raw
        scope_val = str(scope_val_arg).strip()
    elif "::" in raw:
        scope_kind, scope_val = raw.split("::", 1)
    elif ":" in raw and not raw.startswith(":"):
        scope_kind, scope_val = raw.split(":", 1)
    elif raw.startswith(":"):
        scope_kind = "MODULE"
        scope_val = raw
    elif raw.upper() in ("GLOBAL", "*"):
        scope_kind = "GLOBAL"
        scope_val = "*"
    elif raw.upper() in ("MODULE", "PACKAGE", "FEATURE", "SOURCE_SET", "ARCH_FAMILY", "PATH"):
        scope_kind = raw.upper()
        scope_val = "*"
    else:
        scope_kind = "GLOBAL"
        scope_val = raw

    scope_kind = scope_kind.strip().upper()
    scope_val = scope_val.strip()
    if scope_kind == "MODULE" and scope_val != "*" and not scope_val.startswith(":"):
        scope_val = f":{scope_val}"
    if scope_kind not in _VALID_INSTRUCTION_SCOPE_KINDS:
        raise ValueError(f"Unsupported scope kind: {scope_kind}")
    return scope_kind, scope_val


def _looks_like_scope_prefix(candidate: str) -> bool:
    """True when `candidate` starts with a recognized instruction scope prefix."""
    c = str(candidate or "").strip()
    if not c:
        return False
    up = c.upper()
    if up in ("GLOBAL", "*") or c.startswith(":"):
        return True
    if "::" in c:
        head = c.split("::", 1)[0].strip().upper()
        return head in _VALID_INSTRUCTION_SCOPE_KINDS
    if ":" in c:
        head = c.split(":", 1)[0].strip().upper()
        return head in _VALID_INSTRUCTION_SCOPE_KINDS
    return up in _VALID_INSTRUCTION_SCOPE_KINDS


def _parse_batch_entry_string(raw: str, default_scope: str, default_scope_val: str | None) -> dict[str, Any]:
    """Parse `'SCOPE :: rule text'` or plain `'rule text'` into a normalized instruction dict."""
    s = str(raw or "").strip()
    if " :: " in s:
        left, right = s.split(" :: ", 1)
        if _looks_like_scope_prefix(left):
            return {"text": right.strip(), "scope": left.strip(), "scope_value": None}
    return {"text": s, "scope": default_scope, "scope_value": default_scope_val}


def _decode_batch_json_text(raw_json: str) -> Any:
    """Decode a JSON array or `{instructions: [...]}` string with PowerShell quote recovery."""
    s = str(raw_json or "").strip()
    for candidate in (
        s,
        (s[1:-1].strip() if ((s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"'))) else s),
    ):
        for attempt in (candidate, candidate.replace(r'\"', '"')):
            try:
                return json.loads(attempt)
            except ValueError:
                continue
    raise ValueError("Invalid JSON passed to --batch-json.")


def _load_batch_instructions(repo: Path, args: argparse.Namespace) -> list[dict[str, Any]] | None:
    """Load and normalize batch instruction specs from `--entry`, `--batch-json`, or `--batch-file`."""
    from _vnext_common import ValidationError, validate_repo_path_containment

    raw_entries = list(getattr(args, "entry", None) or [])
    raw_json = str(getattr(args, "batch_json", None) or "").strip()
    raw_file = str(getattr(args, "batch_file", None) or "").strip()
    if not raw_entries and not raw_json and not raw_file:
        return None

    default_scope = (getattr(args, "scope", None) or "GLOBAL").strip()
    default_scope_val = getattr(args, "scope_value", None)
    default_strength = (getattr(args, "strength", None) or "REQUIREMENT").strip().upper()
    default_applies_to = getattr(args, "applies_to", None) or "ANY"

    items: list[Any] = []
    for raw_e in raw_entries:
        items.append(_parse_batch_entry_string(raw_e, default_scope, default_scope_val))

    for label, payload in (("--batch-json", raw_json), ("--batch-file", raw_file)):
        if not payload:
            continue
        if label == "--batch-json":
            loaded = _decode_batch_json_text(payload)
        else:
            try:
                rel_posix = validate_repo_path_containment(repo, payload)
            except ValidationError as exc:
                raise ValueError(str(exc)) from exc
            bf_path = repo / rel_posix
            if not bf_path.is_file():
                raise ValueError(f"Batch instructions file not found: {payload}")
            try:
                loaded = json.loads(bf_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"Failed reading {payload}: {exc}") from exc
        if isinstance(loaded, dict) and isinstance(loaded.get("instructions"), list):
            loaded = loaded["instructions"]
        if not isinstance(loaded, list):
            raise ValueError(f"{label} must be a JSON array or an object containing an 'instructions' array.")
        items.extend(loaded)

    if not items:
        raise ValueError("Batch instruction input cannot be empty.")

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, str):
            spec = _parse_batch_entry_string(item, default_scope, default_scope_val)
        elif isinstance(item, dict):
            spec = dict(item)
        else:
            raise ValueError(f"Batch entry #{idx} must be a string or JSON object.")

        item_text = str(spec.get("text") or spec.get("instruction") or "").strip()
        if not item_text:
            raise ValueError(f"Batch entry #{idx} has empty instruction text.")

        has_explicit_scope = "scope" in spec and spec.get("scope") is not None and str(spec.get("scope")).strip() != ""
        raw_item_scope = str(spec.get("scope") or default_scope).strip()
        if "scope_value" in spec:
            item_scope_val = spec.get("scope_value")
        elif has_explicit_scope:
            item_scope_val = None
        else:
            item_scope_val = default_scope_val

        try:
            scope_kind, scope_val = _parse_instruction_scope(raw_item_scope, item_scope_val)
        except ValueError as exc:
            raise ValueError(f"Batch entry #{idx}: {exc}") from exc

        strength = str(spec.get("strength") or default_strength).strip().upper()
        if strength not in ("REQUIREMENT", "PREFERENCE"):
            strength = "REQUIREMENT"

        applies_raw = spec.get("applies_to", default_applies_to)
        if isinstance(applies_raw, str):
            applies_to = [s.strip().upper() for s in applies_raw.split(",") if s.strip()]
        elif isinstance(applies_raw, list):
            applies_to = [str(s).strip().upper() for s in applies_raw if str(s).strip()]
        else:
            applies_to = ["ANY"]
        if not applies_to:
            applies_to = ["ANY"]

        normalized.append({
            "text": item_text,
            "scope_kind": scope_kind,
            "scope_val": scope_val,
            "strength": strength,
            "applies_to": applies_to,
            "supersedes": str(spec.get("supersedes") or "").strip() or None,
            "rationale": str(spec.get("rationale") or "").strip(),
            "alternatives_rejected": str(spec.get("alternatives_rejected") or "").strip(),
        })
    return normalized


def _build_instruction_record(
    *,
    text: str,
    scope_kind: str,
    scope_val: str,
    strength: str,
    applies_to: list[str],
    source: str,
    proof_ref: str,
    created_at: float,
    rationale: str = "",
    alternatives_rejected: str = "",
) -> dict[str, Any]:
    import hashlib

    content_material = f"{scope_kind}:{scope_val}:{strength}:{','.join(sorted(applies_to))}:{text}"
    content_sha = hashlib.sha256(content_material.encode("utf-8")).hexdigest()
    inst_id = f"pi-{content_sha[:8]}"
    proof_sha = hashlib.sha256(str(proof_ref).encode("utf-8")).hexdigest()
    rec: dict[str, Any] = {
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
        "created_at": created_at,
        "status": "ACTIVE",
    }
    if rationale:
        rec["rationale"] = rationale
    if alternatives_rejected:
        rec["alternatives_rejected"] = alternatives_rejected
    return rec


def cmd_instruct(args: argparse.Namespace) -> int | dict[str, Any]:
    import time
    from _vnext_common import atomic_write_json
    from evidence_store import StateLock

    repo = Path(args.repo).resolve()
    context_dir = repo / ".agents" / "project-context"
    inst_file = context_dir / "developer-instructions.json"
    if not context_dir.is_dir():
        context_dir.mkdir(parents=True, exist_ok=True)

    remove_id = (getattr(args, "remove", None) or "").strip()
    text = (getattr(args, "instruction", None) or getattr(args, "text", None) or "").strip()
    has_batch_flags = bool(
        getattr(args, "entry", None)
        or (getattr(args, "batch_json", None) or "").strip()
        or (getattr(args, "batch_file", None) or "").strip()
    )

    source = getattr(args, "source", None)
    proof_ref = getattr(args, "proof_reference", None)
    if not source or source not in ("conversation", "developer_terminal", "host_native"):
        print("[ERROR] Mandatory --source must be one of: conversation, developer_terminal, host_native.", file=sys.stderr)
        return 1
    if not proof_ref or not str(proof_ref).strip():
        print("[ERROR] Mandatory --proof-reference cannot be empty.", file=sys.stderr)
        return 1

    if has_batch_flags and remove_id:
        print("[ERROR] Cannot combine --remove with batch flags (--entry, --batch-json, --batch-file).", file=sys.stderr)
        return 1
    if has_batch_flags and text:
        print("[ERROR] Cannot combine single instruction text with batch flags (--entry, --batch-json, --batch-file).", file=sys.stderr)
        return 1

    batch_specs: list[dict[str, Any]] | None = None
    if has_batch_flags:
        try:
            batch_specs = _load_batch_instructions(repo, args)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

    single_spec: dict[str, Any] | None = None
    if not remove_id and not batch_specs:
        if not text:
            print("[ERROR] Instruction text cannot be empty.", file=sys.stderr)
            return 1
        try:
            scope_kind, scope_val = _parse_instruction_scope(
                getattr(args, "scope", None) or "GLOBAL",
                getattr(args, "scope_value", None),
            )
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
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
        single_spec = {
            "text": text,
            "scope_kind": scope_kind,
            "scope_val": scope_val,
            "strength": strength,
            "applies_to": applies_to,
            "supersedes": getattr(args, "supersedes", None),
            "rationale": str(getattr(args, "rationale", None) or "").strip(),
            "alternatives_rejected": str(getattr(args, "alternatives_rejected", None) or "").strip(),
        }

    with StateLock(context_dir / "developer-instructions"):
        existing_store: dict[str, Any] = {"schema_version": 1, "instructions": []}
        if inst_file.is_file():
            try:
                loaded = json.loads(inst_file.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict) and isinstance(loaded.get("instructions"), list):
                    existing_store = loaded
            except (OSError, ValueError):
                pass

        if remove_id:
            found = None
            for old_inst in existing_store["instructions"]:
                if old_inst.get("id") == remove_id or (len(remove_id) >= 8 and remove_id.lower() in str(old_inst.get("text") or "").lower()):
                    old_inst["status"] = "REMOVED"
                    old_inst["removed_at"] = time.time()
                    old_inst["removed_source"] = source
                    old_inst["removed_proof_reference"] = str(proof_ref)
                    found = old_inst.get("id")
            if not found:
                print(f"[ERROR] Instruction '{remove_id}' not found in {inst_file}", file=sys.stderr)
                return 1
            atomic_write_json(inst_file, existing_store)
            ret_payload = {"status": "PASS", "action": "REMOVED", "id": found, "path": str(inst_file)}
            if getattr(args, "json", False):
                print(json.dumps(ret_payload, ensure_ascii=False))
            else:
                print(f"[INSTRUCT] Removed persistent instruction '{found}'")
            return ret_payload

        specs_to_write = batch_specs if batch_specs is not None else ([single_spec] if single_spec else [])
        now_ts = time.time()
        recorded: list[dict[str, Any]] = []
        instructions = list(existing_store["instructions"])
        for spec in specs_to_write:
            supersedes_id = spec.get("supersedes")
            if supersedes_id:
                for old_inst in instructions:
                    if old_inst.get("id") == supersedes_id:
                        old_inst["status"] = "SUPERSEDED"
            new_inst = _build_instruction_record(
                text=spec["text"],
                scope_kind=spec["scope_kind"],
                scope_val=spec["scope_val"],
                strength=spec["strength"],
                applies_to=spec["applies_to"],
                source=source,
                proof_ref=str(proof_ref),
                created_at=now_ts,
                rationale=spec.get("rationale", ""),
                alternatives_rejected=spec.get("alternatives_rejected", ""),
            )
            inst_id = new_inst["id"]
            instructions = [i for i in instructions if i.get("id") != inst_id]
            instructions.append(new_inst)
            recorded.append(new_inst)

        existing_store["instructions"] = instructions
        atomic_write_json(inst_file, existing_store)

    if batch_specs is not None:
        ids = [r["id"] for r in recorded]
        ret_payload = {
            "status": "PASS",
            "action": "BATCH_ADDED",
            "count": len(recorded),
            "ids": ids,
            "instructions": recorded,
            "path": str(inst_file),
        }
        if getattr(args, "json", False):
            print(json.dumps(ret_payload, ensure_ascii=False))
        else:
            print(f"[INSTRUCT] Recorded {len(recorded)} persistent instruction(s) in {inst_file}: {', '.join(ids)}")
        return ret_payload

    new_inst = recorded[0]
    inst_id = new_inst["id"]
    ret_payload = {"status": "PASS", "id": inst_id, "instruction": new_inst, "path": str(inst_file)}
    if getattr(args, "json", False):
        print(json.dumps(ret_payload, ensure_ascii=False))
    else:
        print(f"[INSTRUCT] Recorded persistent instruction '{inst_id}' for scope {new_inst['scope']['kind']}:{new_inst['scope']['value']}")
    return ret_payload


def cmd_drift_report(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    report = check_living_context_drift(repo)
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    status = report.get("status", "CLEAN")
    print(f"CONTEXT_DRIFT_STATUS={status}")
    print(f"FACTS_STATUS={report.get('facts_status', 'MISSING')} (fresh={report.get('facts_fresh', False)})")
    print(f"STALE_INSTRUCTIONS={report.get('stale_instructions_count', 0)} STALE_NOTES={report.get('stale_notes_count', 0)}")
    for item in report.get("stale_instructions") or []:
        healed = f" -> suggested: {item['suggested_replacement']}" if item.get("suggested_replacement") else ""
        print(f"  - [{item.get('kind')}] {item.get('id')}: {item.get('reference')}{healed}")
    for item in report.get("stale_notes") or []:
        healed = f" -> suggested: {item['suggested_replacement']}" if item.get("suggested_replacement") else ""
        print(f"  - [{item.get('kind')}] {item.get('reference')}{healed}")
    for rem in report.get("remediation") or []:
        print(f"REMEDIATION: {rem}")
    return 0


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
    p_note.add_argument("text", nargs="?", default="", help="Note text to append or replace with")
    p_note.add_argument("--note", default="", help="Note text to append or replace with")
    p_note.add_argument("--note-file", default="", help="UTF-8 file containing note text to append or replace with")
    p_note.add_argument("--replace", default="", help="Existing note text/bullet to replace in project-notes.md")
    p_note.add_argument("--remove", default="", help="Existing note text/bullet to delete from project-notes.md")
    p_note.add_argument("--section", default="Domain Conventions & Context", help="Section header to place note under")
    p_note.add_argument("--repo", default=".")
    p_note.add_argument("--json", action="store_true")

    p_inst = sub.add_parser("instruct")
    p_inst.add_argument("text", nargs="?", default="", help="Single instruction text")
    p_inst.add_argument("--instruction", default="", help="Single instruction text (alias for positional text)")
    p_inst.add_argument(
        "--entry",
        action="append",
        default=None,
        help="Repeatable batch instruction: 'SCOPE :: Rule text' (e.g. --entry 'GLOBAL:* :: Rule 1' --entry 'MODULE::shared :: Rule 2')",
    )
    p_inst.add_argument(
        "--batch-json",
        default="",
        help="Batch JSON array of strings or {text, scope?, scope_value?, strength?, applies_to?, supersedes?, rationale?} objects",
    )
    p_inst.add_argument(
        "--batch-file",
        default="",
        help="Repo-relative JSON file containing a batch array (or {instructions: [...]})",
    )
    p_inst.add_argument(
        "--scope",
        default="GLOBAL",
        help="Instruction scope kind/value: GLOBAL:* | MODULE::name | PACKAGE:pkg | FEATURE:name | PATH:rel | SOURCE_SET:name | ARCH_FAMILY:id",
    )
    p_inst.add_argument("--scope-value", default=None, help="Instruction scope value (optional when encoded in --scope)")
    p_inst.add_argument("--source", choices=("conversation", "developer_terminal", "host_native"), default=None, help="Explicit developer authority source")
    p_inst.add_argument("--proof-reference", default="", help="Message or command reference proving developer request")
    p_inst.add_argument("--strength", choices=("REQUIREMENT", "PREFERENCE"), default="REQUIREMENT")
    p_inst.add_argument("--applies-to", default="ANY", help="Comma-separated applicable intents (ANY, PRESERVE, NEW, REFACTOR, MIGRATION)")
    p_inst.add_argument("--supersedes", default=None, help="Prior instruction ID to supersede")
    p_inst.add_argument("--remove", default=None, help="Instruction ID or text substring to remove/deactivate")
    p_inst.add_argument("--rationale", default="", help="Optional decision rationale explaining why this instruction exists")
    p_inst.add_argument("--alternatives-rejected", default="", help="Optional alternatives considered and rejected")
    p_inst.add_argument("--repo", default=".")
    p_inst.add_argument("--json", action="store_true")

    p_drift = sub.add_parser("drift-report", help="Audit project-notes.md and developer-instructions.json for stale file/module references")
    p_drift.add_argument("--repo", default=".")
    p_drift.add_argument("--json", action="store_true")

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
    if args.command == "drift-report":
        return cmd_drift_report(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
