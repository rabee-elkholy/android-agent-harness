"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


def _strip_trailing_json_commas(src: str) -> str:
    """Remove accidental trailing commas before `}` or `]` outside JSON string literals."""
    out: list[str] = []
    in_str = False
    esc = False
    n = len(src)
    i = 0
    while i < n:
        ch = src[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and src[j] in " \t\r\n":
                j += 1
            if j < n and src[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)
def _is_template_example_merge_obj(obj: dict[str, Any]) -> bool:
    """Reject schema documentation examples embedded inside outgoing Context Pack `.md` files."""
    raw_nf = obj.get("need_files") or obj.get("needed_files") or []
    if raw_nf == ["relative/path/to/MissingFile.kt"] or (
        str(obj.get("reason") or "").strip() == "Why full body of this file is required before editing"
    ):
        return True
    ops = obj.get("operations")
    if isinstance(ops, list) and ops:
        for op in ops:
            if not isinstance(op, dict):
                continue
            if op.get("path") == "path/to/NewFileOrTestOrVectorDrawable.kt":
                return True
            hunks = op.get("hunks")
            if isinstance(hunks, list) and any(
                isinstance(h, dict) and h.get("search") == "exact existing lines from FILE block"
                for h in hunks
            ):
                return True
    return False
def _is_outgoing_context_pack_text(raw_text: str) -> bool:
    stripped = (raw_text or "").lstrip()
    return stripped.startswith("# Android Agent Harness — Web-Relay")
def _detect_truncated_merge_pack_id(raw_text: str, known_packs: set[str]) -> str:
    """Detect a pasted/uploaded HARNESS_WEB_MERGE_V1 JSON snippet that was truncated mid-stream."""
    if not raw_text or _engine._is_outgoing_context_pack_text(raw_text):
        return ""
    if f'"{_engine.WEB_MERGE_SCHEMA}"' not in raw_text:
        return ""
    m_pid = _engine.re.search(r'"pack_id"\s*:\s*"(wpack-[a-f0-9]{12})"', raw_text)
    if not m_pid:
        return ""
    pid = m_pid.group(1)
    if known_packs and pid not in known_packs:
        return ""
    return pid
def _extract_merge_json_from_text(raw_text: str) -> dict[str, Any] | None:
    text = (raw_text or "").strip()
    if not text:
        return None
    decoder = _engine.json.JSONDecoder()
    for candidate_text in (text, _engine._strip_trailing_json_commas(text)):
        try:
            obj = _engine.json.loads(candidate_text)
            if isinstance(obj, dict) and obj.get("schema") == _engine.WEB_MERGE_SCHEMA and not _engine._is_template_example_merge_obj(obj):
                return obj
        except ValueError:
            pass
        # Scan balanced JSON objects containing WEB_MERGE_SCHEMA (immune to inner ``` fences or trailing prose!)
        search_pos = 0
        matched_objs: list[dict[str, Any]] = []
        while True:
            idx = candidate_text.find(f'"{_engine.WEB_MERGE_SCHEMA}"', search_pos)
            if idx == -1:
                break
            brace_pos = candidate_text.rfind("{", 0, idx)
            while brace_pos != -1:
                try:
                    obj, _ = decoder.raw_decode(candidate_text, brace_pos)
                    if (
                        isinstance(obj, dict)
                        and obj.get("schema") == _engine.WEB_MERGE_SCHEMA
                        and not _engine._is_template_example_merge_obj(obj)
                    ):
                        matched_objs.append(obj)
                        break
                except ValueError:
                    pass
                brace_pos = candidate_text.rfind("{", 0, brace_pos)
            search_pos = idx + len(_engine.WEB_MERGE_SCHEMA)
        if matched_objs:
            return matched_objs[-1]
    return None
def _resolve_incoming_merge_payload(repo: Path, explicit_file: str, use_stdin: bool) -> tuple[dict[str, Any], str]:
    if explicit_file:
        fp = Path(explicit_file).expanduser().resolve()
        if not fp.is_file():
            raise _engine.ValidationError(f"Merge payload file not found: {fp}")
        if fp.suffix.lower() == ".zip":
            import zipfile
            with zipfile.ZipFile(fp, "r") as zf:
                for name in zf.namelist():
                    if name.endswith(".json"):
                        parsed = _engine._extract_merge_json_from_text(zf.read(name).decode("utf-8", errors="replace"))
                        if parsed:
                            return parsed, f"zip:{fp}"
            raise _engine.ValidationError(f"ZIP file '{fp}' does not contain a valid {_engine.WEB_MERGE_SCHEMA} JSON document.")
        raw_fp = fp.read_text(encoding="utf-8", errors="replace")
        parsed = _engine._extract_merge_json_from_text(raw_fp)
        if not parsed:
            if _engine._detect_truncated_merge_pack_id(raw_fp, set()):
                raise _engine.ValidationError(
                    f"WEB_MERGE_JSON_TRUNCATED: File '{fp}' begins a `{_engine.WEB_MERGE_SCHEMA}` payload but is cut off before the closing JSON brace. "
                    "Download the complete `harness-merge-*.json` file from the external AI chat (or copy after generation finishes) and re-run `web-apply`."
                )
            raise _engine.ValidationError(f"File '{fp}' does not contain a valid `{_engine.WEB_MERGE_SCHEMA}` JSON payload.")
        return parsed, f"file:{fp}"

    if use_stdin:
        from _vnext_common import read_utf8_stdin
        raw_in = read_utf8_stdin()
        parsed = _engine._extract_merge_json_from_text(raw_in)
        if not parsed:
            if _engine._detect_truncated_merge_pack_id(raw_in, set()):
                raise _engine.ValidationError(
                    f"WEB_MERGE_JSON_TRUNCATED: Standard input begins a `{_engine.WEB_MERGE_SCHEMA}` payload but is truncated before JSON completion."
                )
            raise _engine.ValidationError(f"Standard input did not contain a valid `{_engine.WEB_MERGE_SCHEMA}` JSON payload.")
        return parsed, "stdin"

    packs_dir = _engine._web_relay_state_dir(repo) / "packs"
    known_packs: set[str] = set()
    unapplied_packs: set[str] = set()
    if packs_dir.is_dir():
        for pf in packs_dir.glob("*.json"):
            known_packs.add(pf.stem)
            try:
                pmeta = _engine.json.loads(pf.read_text(encoding="utf-8", errors="replace"))
                if not pmeta.get("applied_at"):
                    unapplied_packs.add(pf.stem)
            except (OSError, ValueError):
                unapplied_packs.add(pf.stem)

    truncated_sources: list[tuple[float, str, str]] = []
    clip_fallback: dict[str, Any] | None = None
    clip_txt = _engine._read_clipboard_text()
    if clip_txt and not _engine._is_outgoing_context_pack_text(clip_txt):
        parsed = _engine._extract_merge_json_from_text(clip_txt)
        if parsed:
            cpid = str(parsed.get("pack_id") or "")
            if not known_packs or cpid in known_packs:
                return parsed, "clipboard"
            clip_fallback = parsed
        else:
            t_pid = _engine._detect_truncated_merge_pack_id(clip_txt, unapplied_packs or known_packs)
            if t_pid:
                truncated_sources.append((_engine.time.time(), t_pid, "clipboard"))

    candidates: list[tuple[int, float, dict[str, Any], Path]] = []
    inbox_dir = _engine._web_relay_state_dir(repo) / "inbox"
    scan_dirs: list[Path] = ([inbox_dir] if inbox_dir.is_dir() else []) + _engine._default_downloads_dirs()
    for dl_dir in scan_dirs:
        for cand in dl_dir.iterdir():
            if not cand.is_file():
                continue
            if cand.suffix.lower() not in {".json", ".md", ".txt", ".zip"}:
                continue
            if _engine.re.search(r"-wpack-[a-f0-9]{12}\.md$", cand.name, _engine.re.I):
                continue
            try:
                st = cand.stat()
                if st.st_size > 20 * 1024 * 1024:
                    continue
            except OSError:
                continue
            try:
                if cand.suffix.lower() == ".zip":
                    import zipfile
                    with zipfile.ZipFile(cand, "r") as zf:
                        for zn in zf.namelist():
                            if zn.endswith(".json"):
                                doc = _engine._extract_merge_json_from_text(zf.read(zn).decode("utf-8", errors="replace"))
                                dpid = str((doc or {}).get("pack_id") or "")
                                if doc and dpid in known_packs:
                                    candidates.append((1 if dpid in unapplied_packs else 0, st.st_mtime, doc, cand))
                else:
                    raw_cand = cand.read_text(encoding="utf-8", errors="replace")
                    if _engine._is_outgoing_context_pack_text(raw_cand):
                        continue
                    doc = _engine._extract_merge_json_from_text(raw_cand)
                    dpid = str((doc or {}).get("pack_id") or "")
                    if doc and dpid in known_packs:
                        candidates.append((1 if dpid in unapplied_packs else 0, st.st_mtime, doc, cand))
                    elif not doc:
                        t_pid = _engine._detect_truncated_merge_pack_id(raw_cand, unapplied_packs or known_packs)
                        if t_pid:
                            truncated_sources.append((st.st_mtime, t_pid, str(cand)))
            except OSError:
                continue
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, best_doc, best_path = candidates[0]
        return best_doc, f"downloads:{best_path}"

    if clip_fallback is not None:
        return clip_fallback, "clipboard"

    if truncated_sources:
        truncated_sources.sort(key=lambda item: item[0], reverse=True)
        _, t_pid, t_src = truncated_sources[0]
        raise _engine.ValidationError(
            f"WEB_MERGE_JSON_TRUNCATED: Detected `{_engine.WEB_MERGE_SCHEMA}` for pack `{t_pid}` in `{t_src}`, "
            "but the JSON text was truncated mid-stream (likely chat input length cap or copying before generation finished). "
            f"Download `harness-merge-{t_pid}.json` into `Downloads` (or copy the full JSON block once generation completes) and re-run `web-apply`."
        )

    raise _engine.ValidationError(
        f"WEB_MERGE_PAYLOAD_NOT_FOUND: No `{_engine.WEB_MERGE_SCHEMA}` JSON found in Clipboard, `.user_uploaded`, or Downloads. "
        "Copy the JSON block from the external AI chat (or download `harness-merge-*.json`) and re-run `web-apply`."
    )
def _count_structural_braces(text: str, *, nested_comments: bool = True) -> tuple[int, int]:
    """Count structural `{` and `}` across Kotlin/Java/Swift while respecting raw `\"\"\"...\"\"\"` strings,
    `${...}` string templates, char literals `'{'`, line comments, and (optionally nested) block comments.
    """
    n = len(text)
    i = 0
    opens = 0
    closes = 0
    mode = "CODE"
    comment_depth = 0
    interp_stack: list[tuple[str, int]] = []

    while i < n:
        ch = text[i]
        if mode == "LINE_COMMENT":
            if ch == "\n":
                mode = "CODE"
            i += 1
        elif mode == "BLOCK_COMMENT":
            if nested_comments and text.startswith("/*", i):
                comment_depth += 1
                i += 2
            elif text.startswith("*/", i):
                comment_depth -= 1
                i += 2
                if comment_depth <= 0:
                    comment_depth = 0
                    mode = "CODE"
            else:
                i += 1
        elif mode == "RAW_STRING":
            if text.startswith("${", i):
                opens += 1
                interp_stack.append(("RAW_STRING", 1))
                mode = "CODE"
                i += 2
            elif text.startswith('"""', i):
                while i + 3 < n and text[i + 3] == '"':
                    i += 1
                i += 3
                mode = "CODE"
            else:
                i += 1
        elif mode == "STRING":
            if ch == "\\":
                i += 2
            elif text.startswith("${", i):
                opens += 1
                interp_stack.append(("STRING", 1))
                mode = "CODE"
                i += 2
            elif ch in ('"', "\n"):
                i += 1
                mode = "CODE"
            else:
                i += 1
        else:  # CODE
            if text.startswith("//", i):
                mode = "LINE_COMMENT"
                i += 2
            elif text.startswith("/*", i):
                mode = "BLOCK_COMMENT"
                comment_depth = 1
                i += 2
            elif text.startswith('"""', i):
                mode = "RAW_STRING"
                i += 3
            elif ch == '"':
                mode = "STRING"
                i += 1
            elif ch == "'":
                # Single-line char literal (`'{'`, `'}'`, `'\''`, `'\u007b'`)
                j = i + 1
                limit = min(n, i + 12)
                closed_at = -1
                while j < limit and text[j] != "\n":
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == "'":
                        closed_at = j
                        break
                    j += 1
                i = (closed_at + 1) if closed_at != -1 else (i + 1)
            elif ch == "{":
                opens += 1
                if interp_stack:
                    ret_m, depth = interp_stack[-1]
                    interp_stack[-1] = (ret_m, depth + 1)
                i += 1
            elif ch == "}":
                closes += 1
                if interp_stack:
                    ret_m, depth = interp_stack[-1]
                    if depth <= 1:
                        interp_stack.pop()
                        mode = ret_m
                    else:
                        interp_stack[-1] = (ret_m, depth - 1)
                i += 1
            else:
                i += 1
    return opens, closes
def _validate_code_integrity(rel_path: str, new_text: str, base_text: str = "") -> None:
    m_conf = _engine.CONFLICT_MARKER_RE.search(new_text)
    if m_conf:
        raise _engine.ValidationError(
            f"UNRESOLVED_CONFLICT_MARKERS_BLOCKED on '{rel_path}': leftover Git conflict marker `{m_conf.group(0).strip()}` detected."
        )
    m_trunc = _engine.LAZY_TRUNCATION_RE.search(new_text)
    if m_trunc:
        raise _engine.ValidationError(
            f"LAZY_TRUNCATION_BLOCKED on '{rel_path}': detected placeholder `{m_trunc.group(0).strip()}`. "
            "The external AI reply must return exact `hunks` (`search`/`replace`) or complete untruncated code."
        )
    if base_text:
        old_lines = len(base_text.splitlines())
        new_lines = len(new_text.splitlines())
        if old_lines >= 80 and new_lines < int(old_lines * 0.35):
            raise _engine.ValidationError(
                f"SUSPICIOUS_CONTENT_DROP_BLOCKED on '{rel_path}': line count dropped from {old_lines} to {new_lines} (>65% wipe). "
                "Use surgical `hunks` or pass explicit deletion if intentional."
            )
    if rel_path.endswith((".kt", ".java", ".swift")):
        nested_c = not rel_path.endswith(".java")
        opens, closes = _engine._count_structural_braces(new_text, nested_comments=nested_c)
        base_opens, base_closes = (
            _engine._count_structural_braces(base_text, nested_comments=nested_c) if base_text else (0, 0)
        )
        if opens != closes and (not base_text or (opens - closes) != (base_opens - base_closes)):
            raise _engine.ValidationError(
                f"UNBALANCED_BRACES_BLOCKED on '{rel_path}': `{opens}` '{{' vs `{closes}` '}}' after applying web changes."
            )
def _apply_hunks(rel_path: str, base_text: str, hunks: list[dict[str, Any]]) -> str:
    cur = base_text.replace("\r\n", "\n").replace("\r", "\n")
    for idx, h in enumerate(hunks, 1):
        if not isinstance(h, dict):
            raise _engine.ValidationError(f"Invalid hunk #{idx} on '{rel_path}': each hunk must be an object.")
        s_raw = h.get("search") if "search" in h else (h.get("find") if "find" in h else h.get("old"))
        r_raw = h.get("replace") if "replace" in h else h.get("new")
        if s_raw is None or r_raw is None:
            raise _engine.ValidationError(f"Invalid hunk #{idx} on '{rel_path}': each hunk requires 'search' and 'replace'.")
        s_txt = str(s_raw).replace("\r\n", "\n").replace("\r", "\n")
        r_txt = str(r_raw).replace("\r\n", "\n").replace("\r", "\n")
        if not s_txt:
            raise _engine.ValidationError(f"Empty 'search' string in hunk #{idx} on '{rel_path}'.")
        if s_txt in cur:
            count = cur.count(s_txt)
            if count > 1 and not h.get("replace_all"):
                raise _engine.ValidationError(
                    f"AMBIGUOUS_HUNK_MATCH on '{rel_path}' hunk #{idx}: 'search' matched {count} locations; include 2-3 surrounding lines."
                )
            cur = cur.replace(s_txt, r_txt) if h.get("replace_all") else cur.replace(s_txt, r_txt, 1)
            continue
        # Tolerate trailing whitespace differences per line
        s_lines = [ln.rstrip() for ln in s_txt.splitlines()]
        c_lines = cur.splitlines()
        matched_at = -1
        for i in range(len(c_lines) - len(s_lines) + 1):
            if [ln.rstrip() for ln in c_lines[i : i + len(s_lines)]] == s_lines:
                if matched_at != -1:
                    matched_at = -2
                    break
                matched_at = i
        if matched_at >= 0:
            c_lines[matched_at : matched_at + len(s_lines)] = r_txt.splitlines()
            cur = "\n".join(c_lines) + ("\n" if cur.endswith("\n") else "")
            continue
        raise _engine.ValidationError(
            f"HUNK_SEARCH_NOT_FOUND on '{rel_path}' hunk #{idx}: target snippet was not found in base file."
        )
    return cur
def _three_way_merge_if_needed(repo: Path, rel_path: str, current_disk: str, base_text: str, target_text: str) -> str:
    cur_norm = current_disk.replace("\r\n", "\n").replace("\r", "\n")
    base_norm = base_text.replace("\r\n", "\n").replace("\r", "\n")
    tgt_norm = target_text.replace("\r\n", "\n").replace("\r", "\n")
    if _engine._sha256_lf(cur_norm) == _engine._sha256_lf(base_norm) or cur_norm == tgt_norm:
        return tgt_norm
    with _engine.tempfile.TemporaryDirectory(prefix="web_3way_") as td:
        td_p = Path(td)
        f_cur = td_p / "current"
        f_base = td_p / "base"
        f_tgt = td_p / "web"
        f_cur.write_text(cur_norm, encoding="utf-8")
        f_base.write_text(base_norm, encoding="utf-8")
        f_tgt.write_text(tgt_norm, encoding="utf-8")
        proc = _engine.subprocess.run(
            ["git", "merge-file", "-p", str(f_cur), str(f_base), str(f_tgt)],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0 or "<<<<<<<" in (proc.stdout or ""):
            raise _engine.ValidationError(
                f"THREE_WAY_MERGE_CONFLICT on '{rel_path}': local file changed concurrently since `web-pack` and overlaps Web edits."
            )
        return proc.stdout
def apply_web_merge(
    repo: Path,
    *,
    merge_file: str = "",
    use_stdin: bool = False,
    source: str = "",
    proof_reference: str = "",
    allow_reapply: bool = False,
    approve_sensitive: bool = False,
    staged_phase: bool = False,
    auto_red_green: bool = True,
    dry_run: bool = False,
    task_id: str = "",
) -> dict[str, Any]:
    eff_source = str(source or "").strip().lower()
    eff_proof = str(proof_reference or "").strip()
    if not dry_run:
        if eff_source not in {"conversation", "developer_terminal", "host_native"}:
            raise _engine.ValidationError(
                "WEB_APPLY_AUTHORITY_REQUIRED: Pass `--source conversation --proof-reference \"<developer phrase>\"` "
                "(or `--source developer_terminal` when run directly by the developer, or `--dry-run` for a read-only preview)."
            )
        if eff_source == "conversation" and not eff_proof:
            raise _engine.ValidationError("WEB_APPLY_PROOF_REQUIRED: `--proof-reference` with the developer's explicit instruction is required.")
        if eff_source == "developer_terminal" and not eff_proof:
            eff_proof = "developer_terminal_web_apply"

    # Handle applying pre-staged phase operations (`p2..pN`) on an active multi-phase task
    if staged_phase:
        from mutation_guard import active_plan
        plan_doc = _engine.read_json(_engine.task_dir(repo, task_id) / "plan.json") if task_id and (_engine.task_dir(repo, task_id) / "plan.json").is_file() else active_plan(repo)
        tid = str(plan_doc.get("task_id") or "")
        phases = plan_doc.get("phases") or []
        p_idx = int(plan_doc.get("active_phase_index") or 0)
        if not phases or p_idx >= len(phases):
            raise _engine.ValidationError("No active phase found on current plan for `--staged-phase`.")
        pid = str(phases[p_idx].get("id") or "")
        staged_f = _engine.task_dir(repo, tid) / "staged-web-phases" / f"{pid}.json"
        if not staged_f.is_file():
            raise _engine.ValidationError(f"No staged web-relay operations found for phase '{pid}'.")
        staged_doc = _engine.read_json(staged_f)
        if isinstance(staged_doc, dict) and staged_doc.get("staged_sha256"):
            expected_st_sha = _engine.canonical_sha256({
                "task_id": str(staged_doc.get("task_id") or tid),
                "phase_id": str(staged_doc.get("phase_id") or pid),
                "writes": list(staged_doc.get("writes") or []),
                "deletes": list(staged_doc.get("deletes") or []),
            })
            if staged_doc.get("staged_sha256") != expected_st_sha:
                raise _engine.ValidationError(f"STAGED_PHASE_TAMPERED: Staged Web-Relay payload for phase '{pid}' failed SHA-256 verification.")
        if dry_run:
            return {
                "status": "DRY_RUN_STAGED_PHASE",
                "dry_run": True,
                "disk_modified": False,
                "task_id": tid,
                "phase_id": pid,
                "files_to_write": [w["path"] for w in staged_doc.get("writes") or []],
                "files_to_delete": list(staged_doc.get("deletes") or []),
            }
        for wr in staged_doc.get("writes") or []:
            dst = repo / wr["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(_engine._apply_eol(wr["content"], wr.get("eol") or "lf"))
        for dl in staged_doc.get("deletes") or []:
            (repo / dl).unlink(missing_ok=True)
        staged_f.unlink(missing_ok=True)
        gate_env = {**_engine.os.environ, "HARNESS_REPO": str(repo), "PYTHONIOENCODING": "utf-8"}
        lint_script = (repo / ".agents" / "scripts" / "fast_kt_lint.py") if (repo / ".agents" / "scripts" / "fast_kt_lint.py").is_file() else (_engine.SCRIPTS_DIR / "fast_kt_lint.py")
        str_script = (repo / ".agents" / "scripts" / "check_strings.py") if (repo / ".agents" / "scripts" / "check_strings.py").is_file() else (_engine.SCRIPTS_DIR / "check_strings.py")
        st_lint_proc = _engine.subprocess.run([_engine.sys.executable, str(lint_script)], cwd=repo, env=gate_env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        st_str_proc = _engine.subprocess.run([_engine.sys.executable, str(str_script)], cwd=repo, env=gate_env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        st_lint_ok = st_lint_proc.returncode == 0
        st_str_ok = st_str_proc.returncode == 0
        try:
            from delivery_manifest import build_task_manifest, load_task_baseline
            st_manifest = build_task_manifest(repo, load_task_baseline(repo, tid), expected_files=plan_doc.get("expected_files"))
            _engine.atomic_write_json(_engine.task_dir(repo, tid) / "web-relay-receipt.json", {
                "schema_version": 1,
                "pack_id": f"staged-{pid}",
                "task_id": tid,
                "origin": f"staged-phase:{pid}",
                "applied_at": _engine.utc_now(),
                "change_set_sha256": str(st_manifest.get("change_set_sha256") or ""),
                "files_written": [w["path"] for w in staged_doc.get("writes") or []],
                "files_deleted": list(staged_doc.get("deletes") or []),
                "fast_kt_lint_ok": st_lint_ok,
                "check_strings_ok": st_str_ok,
            })
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            st_manifest = {}
        return {
            "status": "APPLIED_STAGED_PHASE",
            "task_id": tid,
            "phase_id": pid,
            "files_written": [w["path"] for w in staged_doc.get("writes") or []],
            "fast_kt_lint_ok": st_lint_ok,
            "check_strings_ok": st_str_ok,
        }

    payload, payload_origin = _engine._resolve_incoming_merge_payload(repo, merge_file, use_stdin)
    pack_id = str(payload.get("pack_id") or "").strip()
    if not pack_id or not _engine.re.fullmatch(r"wpack-[a-f0-9]{12}", pack_id):
        raise _engine.ValidationError(f"Invalid or missing `pack_id` in `{_engine.WEB_MERGE_SCHEMA}` payload: '{pack_id}'.")

    pack_path = _engine._web_relay_state_dir(repo) / "packs" / f"{pack_id}.json"
    if not pack_path.is_file():
        raise _engine.ValidationError(
            f"PACK_REPO_MISMATCH: Pack `{pack_id}` does not belong to this repository (`{repo.name}`) or was not generated here."
        )
    pack_doc = _engine.read_json(pack_path)
    if pack_doc.get("repo_fingerprint") != _engine.repository_identity(repo):
        raise _engine.ValidationError(f"PACK_REPO_MISMATCH: Pack `{pack_id}` fingerprint does not match repository `{repo.name}`.")
    if pack_doc.get("applied") and not allow_reapply:
        raise _engine.ValidationError(f"PACK_ALREADY_APPLIED: Pack `{pack_id}` was already applied. Pass `--allow-reapply` only if intentional.")

    # Check active task alignment (`Safeguard #7`)
    active_doc: dict[str, Any] | None = None
    if task_id and (_engine.state_root(repo) / "tasks" / task_id / "plan.json").is_file():
        try:
            active_doc = _engine.read_json(_engine.state_root(repo) / "tasks" / task_id / "plan.json")
        except (OSError, ValueError, _engine.ValidationError):
            active_doc = None
    if active_doc is None:
        try:
            from mutation_guard import active_plan
            active_doc = active_plan(repo, allow_missing=True)
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            active_doc = None
    if active_doc and active_doc.get("task_id") and str(active_doc.get("status") or "") not in {"", "DELIVERED", "CANCELLED"}:
        act_tid = str(active_doc.get("task_id") or "")
        pack_tid = str(pack_doc.get("task_id") or "")
        if pack_tid and act_tid and pack_tid != act_tid:
            raise _engine.ValidationError(
                f"ACTIVE_TASK_MISMATCH: Pack `{pack_id}` belongs to task `{pack_tid}`, while focused active task is `{act_tid}`."
            )

    # Short-circuit `NEED_FILES` expansion (`Scenario 4A`)
    raw_need_files = payload.get("need_files") or payload.get("needed_files") or []
    if str(payload.get("status") or "").upper() == "NEED_FILES" or raw_need_files:
        req_files = [str(f) for f in raw_need_files if str(f).strip()]
        if not req_files:
            raise _engine.ValidationError("`NEED_FILES` status received with empty `need_files` list.")
        if dry_run:
            return {
                "status": "DRY_RUN_NEED_FILES",
                "dry_run": True,
                "disk_modified": False,
                "pack_consumed": False,
                "pack_id": pack_id,
                "origin": payload_origin,
                "requested_files": req_files,
            }
        norm_req: list[str] = []
        missing_req: list[str] = []
        for rf in req_files:
            try:
                nr = _engine._norm_rel(repo, rf)
                blocked_nf, _ = _engine._is_protected_or_secret_path(nr)
                if blocked_nf:
                    missing_req.append(rf)
                    continue
                if (repo / nr).is_file():
                    if nr not in norm_req:
                        norm_req.append(nr)
                else:
                    missing_req.append(rf)
            except _engine.ValidationError:
                missing_req.append(rf)
        if not norm_req:
            raise _engine.ValidationError(
                f"NEED_FILES_NOT_FOUND: Requested file(s) do not exist in repository `{repo.name}` (or are protected): {missing_req}. "
                "Do NOT apply template examples; copy or download the actual external AI reply and re-run `web-apply`."
            )
        cur_ed_keys = list((pack_doc.get("editable_files") or {}).keys())
        merged_active_files = list(dict.fromkeys(cur_ed_keys + norm_req))
        raw_prev_pending = pack_doc.get("pending_batches") or []
        dedup_pending = [
            [pf for pf in batch_l if pf not in set(merged_active_files)]
            for batch_l in raw_prev_pending
            if isinstance(batch_l, list)
        ]
        dedup_pending = [b for b in dedup_pending if b]
        prev_b_idx = int(pack_doc.get("batch_index") or 1)
        prev_tot_b = prev_b_idx + len(dedup_pending) if (int(pack_doc.get("total_batches") or 1) > 1 or dedup_pending) else 1
        expanded = _engine.build_web_pack(
            repo,
            task_id=str(pack_doc.get("task_id") or ""),
            prompt=str(pack_doc.get("prompt") or ""),
            kind=str(pack_doc.get("kind") or ""),
            files=merged_active_files,
            add_files=norm_req,
            no_clipboard=(_engine.os.environ.get("HARNESS_NO_CLIPBOARD") == "1"),
            batch_size=max(len(merged_active_files), int(pack_doc.get("batch_size") or _engine.DEFAULT_WEB_PACK_BATCH_SIZE)),
            batch_index=prev_b_idx,
            total_batches_hint=prev_tot_b,
            remaining_batches_override=dedup_pending,
        )
        return {
            "status": "NEED_FILES_EXPANDED",
            "origin": payload_origin,
            "added_files": req_files,
            "new_pack": expanded,
        }

    ops = payload.get("operations")
    if not isinstance(ops, list) or not ops:
        raise _engine.ValidationError("Merge payload contains no `operations` to apply.")

    vault: dict[str, str] = dict(pack_doc.get("secret_vault") or {})
    editable_files: dict[str, dict[str, Any]] = dict(pack_doc.get("editable_files") or {})

    # Phase 1: Validate & compute every target file IN MEMORY before touching disk or plan!
    planned_writes: list[dict[str, Any]] = []
    planned_deletes: list[str] = []
    all_scope_paths: list[str] = []

    def _reg_scope(p: str) -> None:
        if p not in all_scope_paths:
            all_scope_paths.append(p)

    for idx, op in enumerate(ops, 1):
        if not isinstance(op, dict):
            raise _engine.ValidationError(f"Operation #{idx} must be an object.")
        action = str(op.get("action") or op.get("op") or "MODIFY").strip().upper()
        if action not in {"MODIFY", "CREATE", "DELETE", "RENAME"}:
            raise _engine.ValidationError(f"Unsupported operation action '{action}' in operation #{idx}.")
        rel_path = _engine._norm_rel(repo, str(op.get("path") or op.get("file") or ""))
        blocked, b_msg = _engine._is_protected_or_secret_path(rel_path)
        if blocked:
            raise _engine.ValidationError(b_msg)

        if action == "DELETE":
            if rel_path not in editable_files:
                raise _engine.ValidationError(f"UNSCOPED_DELETE_BLOCKED: Cannot delete '{rel_path}' because it was not in `EDITABLE_FILES` of pack `{pack_id}`.")
            planned_deletes.append(rel_path)
            _reg_scope(rel_path)
            continue

        if action == "RENAME":
            old_rel = _engine._norm_rel(repo, str(op.get("old_path") or ""))
            b_old, b_old_msg = _engine._is_protected_or_secret_path(old_rel)
            if b_old:
                raise _engine.ValidationError(b_old_msg)
            if old_rel not in editable_files:
                raise _engine.ValidationError(f"UNSCOPED_RENAME_BLOCKED: '{old_rel}' was not in `EDITABLE_FILES` of pack `{pack_id}`.")
            if (repo / rel_path).exists() and rel_path != old_rel and rel_path not in planned_deletes:
                raise _engine.ValidationError(
                    f"RENAME_DESTINATION_EXISTS: Cannot rename '{old_rel}' onto existing file '{rel_path}' unless '{rel_path}' is explicitly deleted first."
                )
            base_meta = editable_files[old_rel]
            base_txt = str(base_meta.get("base_text") or "")
            old_disk_f = repo / old_rel
            cur_old_bytes = old_disk_f.read_bytes() if old_disk_f.is_file() else b""
            eol = _engine._detect_eol(cur_old_bytes) if cur_old_bytes else str(base_meta.get("eol") or "lf")
            cur_old_txt = cur_old_bytes.decode("utf-8", errors="replace") if cur_old_bytes else ""
            if op.get("hunks"):
                raw_new = _engine._apply_hunks(old_rel, _engine._redact_inline_secrets(base_txt, dict(vault)), list(op["hunks"]))
                web_target = _engine._restore_inline_secrets(raw_new, vault)
            elif "content" in op:
                web_target = _engine._restore_inline_secrets(str(op["content"]), vault)
            else:
                web_target = base_txt
            _engine._validate_code_integrity(rel_path, web_target, base_txt)
            restored = _engine._three_way_merge_if_needed(repo, old_rel, cur_old_txt, base_txt, web_target) if old_disk_f.is_file() else web_target
            planned_deletes.append(old_rel)
            planned_writes.append({"path": rel_path, "content": restored, "eol": eol, "is_test": _engine.is_kmp_or_android_test_path(rel_path)})
            _reg_scope(old_rel)
            _reg_scope(rel_path)
            continue

        disk_f = repo / rel_path
        if action == "CREATE" and not disk_f.exists():
            if "content" not in op:
                raise _engine.ValidationError(f"CREATE operation on '{rel_path}' requires 'content'.")
            restored = _engine._restore_inline_secrets(str(op["content"]), vault)
            _engine._validate_code_integrity(rel_path, restored, "")
            default_eol = "crlf" if any(m.get("eol") == "crlf" for m in editable_files.values()) else "lf"
            planned_writes.append({"path": rel_path, "content": restored, "eol": default_eol, "is_test": _engine.is_kmp_or_android_test_path(rel_path)})
            _reg_scope(rel_path)
            continue

        # MODIFY (or CREATE on a file that was already in editable_files / exists)
        if disk_f.exists() and rel_path not in editable_files:
            if not op.get("hunks"):
                raise _engine.ValidationError(
                    f"UNSCOPED_EXISTING_FILE_OVERWRITE_BLOCKED: Existing file '{rel_path}' was NOT included in `EDITABLE_FILES` of pack `{pack_id}`. "
                    "Use surgical `hunks` (`search`/`replace`) or return `NEED_FILES` to load its full source before replacing whole-file `content`."
                )
            # Safe surgical `hunks` on an existing non-secret repo file (e.g. neighbor interface/caller): verify directly against live disk!
            live_b = disk_f.read_bytes()
            if _engine._is_binary_asset(rel_path, live_b):
                raise _engine.ValidationError(f"BINARY_FILE_TEXT_EDIT_BLOCKED: Cannot apply text hunks to binary asset '{rel_path}'.")
            live_eol = _engine._detect_eol(live_b)
            live_txt = live_b.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            _engine._redact_inline_secrets(live_txt, vault)
            base_meta = {"exists": True, "sha256": _engine._sha256_lf(live_txt), "eol": live_eol, "base_text": live_txt}
        else:
            base_meta = editable_files.get(rel_path) or {"base_text": "", "eol": "lf"}
        base_txt = str(base_meta.get("base_text") or "")
        cur_disk_bytes = disk_f.read_bytes() if disk_f.is_file() else b""
        eol = _engine._detect_eol(cur_disk_bytes) if cur_disk_bytes else str(base_meta.get("eol") or "lf")
        cur_disk_txt = cur_disk_bytes.decode("utf-8", errors="replace") if cur_disk_bytes else ""

        if op.get("hunks"):
            web_target_redacted = _engine._apply_hunks(rel_path, _engine._redact_inline_secrets(base_txt, dict(vault)), list(op["hunks"]))
            web_target = _engine._restore_inline_secrets(web_target_redacted, vault)
        elif "content" in op:
            web_target = _engine._restore_inline_secrets(str(op["content"]), vault)
        else:
            raise _engine.ValidationError(f"MODIFY operation on '{rel_path}' requires 'hunks' or 'content'.")

        _engine._validate_code_integrity(rel_path, web_target, base_txt)
        merged_txt = _engine._three_way_merge_if_needed(repo, rel_path, cur_disk_txt, base_txt, web_target) if disk_f.is_file() else web_target
        planned_writes.append({"path": rel_path, "content": merged_txt, "eol": eol, "is_test": _engine.is_kmp_or_android_test_path(rel_path)})
        _reg_scope(rel_path)

    if dry_run:
        import difflib as _difflib
        file_previews: list[dict[str, Any]] = []
        tot_add = 0
        tot_del = 0
        merged_3way_files: list[str] = []
        static_warnings: list[str] = []
        for w_item in planned_writes:
            w_p = w_item["path"]
            d_f = repo / w_p
            existed = d_f.is_file()
            before_txt = d_f.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n") if existed else ""
            after_txt = w_item["content"].replace("\r\n", "\n").replace("\r", "\n")
            add_n = 0
            del_n = 0
            for d_ln in _difflib.unified_diff(before_txt.splitlines(), after_txt.splitlines(), lineterm=""):
                if d_ln.startswith("+++") or d_ln.startswith("---"):
                    continue
                if d_ln.startswith("+"):
                    add_n += 1
                elif d_ln.startswith("-"):
                    del_n += 1
            tot_add += add_n
            tot_del += del_n
            b_meta = editable_files.get(w_p) or {}
            was_3way = bool(existed and b_meta.get("base_text") is not None and _engine._sha256_lf(before_txt) != _engine._sha256_lf(str(b_meta.get("base_text") or "")))
            if was_3way:
                merged_3way_files.append(w_p)
            file_previews.append({
                "path": w_p,
                "action": "MODIFY" if existed else "CREATE",
                "added_lines": add_n,
                "deleted_lines": del_n,
                "three_way_merged": was_3way,
            })
            if w_p.endswith((".kt", ".java")) and not w_item.get("is_test"):
                if _engine.re.search(r"^\s*import\s+[A-Za-z0-9_.]+\.\*\s*$", after_txt, _engine.re.MULTILINE):
                    static_warnings.append(f"{w_p}: wildcard import (`.*`) detected")
                if "http://" in after_txt and "http://schemas.android.com" not in after_txt and "localhost" not in after_txt and "127.0.0.1" not in after_txt:
                    static_warnings.append(f"{w_p}: potential cleartext `http://` URL detected")
        for d_rel in planned_deletes:
            d_f = repo / d_rel
            del_cnt = len(d_f.read_text(encoding="utf-8", errors="replace").splitlines()) if d_f.is_file() else 0
            tot_del += del_cnt
            file_previews.append({"path": d_rel, "action": "DELETE", "added_lines": 0, "deleted_lines": del_cnt, "three_way_merged": False})
        return {
            "status": "DRY_RUN_OK",
            "dry_run": True,
            "disk_modified": False,
            "pack_consumed": False,
            "pack_id": pack_id,
            "task_id": str((active_doc or {}).get("task_id") or pack_doc.get("task_id") or pack_doc.get("suggested_task_id") or ""),
            "origin": payload_origin,
            "batch_index": int(pack_doc.get("batch_index") or 1),
            "total_batches": int(pack_doc.get("total_batches") or 1),
            "summary": {
                "files_to_write": len(planned_writes),
                "files_to_delete": len(planned_deletes),
                "total_added_lines": tot_add,
                "total_deleted_lines": tot_del,
                "three_way_merged_files": merged_3way_files,
            },
            "file_previews": file_previews,
            "static_preview_warnings": static_warnings,
            "next_apply_command": 'python .agents/harness.py web-apply --source conversation --proof-reference "<developer words>"',
        }

    # Phase 2: Ensure approved Harness Plan exists BEFORE writing a single byte to disk (`Collision #1`)!
    import workflow as wf
    plan_spec = payload.get("plan_spec") if isinstance(payload.get("plan_spec"), dict) else {}
    if not active_doc or not active_doc.get("task_id") or str(active_doc.get("status") or "") in {"", "DELIVERED", "CANCELLED"}:
        tid = _engine.validate_id(
            str(plan_spec.get("task_id") or pack_doc.get("suggested_task_id") or f"web-{pack_id[-6:]}"),
            "task_id",
        )
        t_kind = _engine._infer_task_kind(str(plan_spec.get("outcome") or payload.get("summary") or pack_doc.get("prompt") or ""), str(plan_spec.get("kind") or payload.get("task_kind") or pack_doc.get("kind") or "FEATURE"))
        outcome_str = str(plan_spec.get("outcome") or payload.get("summary") or pack_doc.get("prompt") or "Apply Web-Relay implementation")
        approach_str = str(plan_spec.get("approach") or payload.get("summary") or "Implemented via Harness Web-Relay pack with AST neighbor verification.")
        risks_str = str(plan_spec.get("risks") or "Verify compile, unit tests, and deterministic static gates locally.")
        # Resolve cold-start architecture intent/family & auto-phases so ROOM_SCHEMA, multi-module, and pure-CREATE tasks never choke
        queued_future_flat = [
            str(qf)
            for qb in (pack_doc.get("pending_batches") or [])
            if isinstance(qb, list)
            for qf in qb
            if str(qf).strip()
        ]
        def _mod_root_of(p_rel: str) -> str:
            n_p = p_rel.replace("\\", "/").strip("/")
            return n_p.split("/src/", 1)[0] if "/src/" in n_p else ":"

        touched_mods = {_mod_root_of(p) for p in (set(all_scope_paths) | set(queued_future_flat))}
        same_mod_companions = [
            ek for ek in editable_files.keys()
            if not touched_mods or _mod_root_of(ek) in touched_mods
        ]
        cold_expected = sorted(set(all_scope_paths) | set(queued_future_flat) | set(same_mod_companions))
        doc_res_sfx = {".md", ".txt", ".rst", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".xml", ".json", ".properties", ".pro", ".ico"}
        impl_paths = [p for p in cold_expected if Path(p).suffix.lower() not in doc_res_sfx and not _engine.is_kmp_or_android_test_path(p)]
        existing_impl = [p for p in impl_paths if (repo / p).is_file()]
        arch_intent_val = str(plan_spec.get("architecture_intent") or "").strip().upper()
        arch_scope_val = existing_impl[0] if existing_impl else (impl_paths[0] if impl_paths else (all_scope_paths[0] if all_scope_paths else None))
        arch_family_val = plan_spec.get("architecture_target_family")

        if not arch_intent_val:
            arch_intent_val = "EXISTING_CHANGE"
            try:
                from architecture_policy import read_architecture_policy
                from project_context import compute_source_fingerprint, extract_consistent_project_context
                facts_f = repo / ".agents" / "project-context" / "project-facts.json"
                live_sha = compute_source_fingerprint(repo)["source_fingerprint_sha256"]
                facts_doc = _engine.read_json(facts_f) if facts_f.is_file() else {}
                if not (isinstance(facts_doc, dict) and facts_doc.get("schema_version") == 2 and facts_doc.get("source_fingerprint_sha256") == live_sha):
                    facts_doc = extract_consistent_project_context(repo, in_memory_graph=True, include_advisory=False)
                fams = ((facts_doc.get("facts") or {}).get("architecture") or {}).get("families") or []
                if impl_paths and not existing_impl and fams:
                    arch_intent_val = "NEW_FEATURE"
                    pol_doc = read_architecture_policy(repo) or {}
                    pref_fam = pol_doc.get("preferred_new_code_family")
                    if pref_fam and any(f.get("id") == pref_fam for f in fams):
                        arch_family_val = pref_fam
                    else:
                        combined_new_code = "\n".join(w["content"] for w in planned_writes if not w.get("is_test"))
                        wants_compose = "@Composable" in combined_new_code
                        picked = None
                        for f_item in fams:
                            tk = str((f_item.get("dimensions") or {}).get("ui_toolkit") or "").lower()
                            if wants_compose and "compose" in tk:
                                picked = f_item.get("id")
                                break
                            if not wants_compose and ("xml" in tk or "view" in tk or "fragment" in tk):
                                picked = f_item.get("id")
                                break
                        arch_family_val = str(picked or fams[0].get("id") or "") or None
                elif len(fams) > 1 and not existing_impl and fams:
                    arch_family_val = str(fams[0].get("id") or "") or None
            except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
                pass

        # Auto-synthesize phases when planning.py requires them (ROOM_SCHEMA >=2 impl files, multi-module, or >8 impl files)
        cold_phases_arg: Any = plan_spec.get("phases")
        is_cold_auto_phased = False
        if not cold_phases_arg and t_kind != "CONFLICT":
            impl_mods: list[str] = []
            for p_im in impl_paths:
                parts_im = p_im.split("/")
                mod_key = "/".join(parts_im[: parts_im.index("src")]) if "src" in parts_im and parts_im.index("src") > 0 else (parts_im[0] if len(parts_im) > 1 else ":")
                if mod_key not in impl_mods:
                    impl_mods.append(mod_key)
            touches_room = any(
                "@Entity" in w["content"] or "@Database" in w["content"] or "Migration(" in w["content"]
                for w in planned_writes
            )
            if touches_room and "migration" not in approach_str.lower() and "schema" not in approach_str.lower():
                approach_str = f"{approach_str} (Includes explicit Room schema version & Migration coverage.)"
            if len(impl_mods) > 1:
                ordered_mods = sorted(impl_mods, key=lambda m: (1 if m in {"app", "wearApp", "androidApp"} else 0, m))
                cold_phases_arg = []
                for idx_m, m_prefix in enumerate(ordered_mods, 1):
                    m_files = [
                        p_all for p_all in cold_expected
                        if (m_prefix != ":" and (p_all == m_prefix or p_all.startswith(m_prefix + "/")))
                        or (m_prefix == ":" and "/" not in p_all)
                    ]
                    if m_files:
                        mod_lbl = ":" + m_prefix.replace("/", ":") if m_prefix != ":" else ":"
                        cold_phases_arg.append({
                            "id": f"p{idx_m}",
                            "title": f"Update {mod_lbl} contracts and implementation",
                            "expected_files": m_files,
                        })
                if len(cold_phases_arg) >= 2:
                    is_cold_auto_phased = True
                else:
                    cold_phases_arg = None
            elif len(impl_paths) > 8 or (touches_room and len(impl_paths) >= 2):
                cold_phases_arg = [{
                    "id": "p1",
                    "title": "Apply scoped implementation and Room/test updates",
                    "expected_files": list(cold_expected),
                }]
                is_cold_auto_phased = True

        # Pre-infer surfaces from in-memory `planned_writes` so newly created files (@Composable, Fragment, PendingIntent, etc.) register exact skills on draft
        inferred_surfs: set[str] = set()
        for w_it in planned_writes:
            wp_low = w_it["path"].lower()
            wc = w_it["content"]
            if w_it.get("is_test"):
                inferred_surfs.add("TEST_ONLY")
            elif wp_low.endswith("androidmanifest.xml"):
                inferred_surfs.add("MANIFEST_PERMISSION")
            elif "/res/values" in wp_low and wp_low.endswith(".xml"):
                inferred_surfs.add("LOCALIZATION")
            elif wp_low.endswith((".kt", ".java")):
                inferred_surfs.add("BUSINESS_LOGIC")
                if "@Composable" in wc or "androidx.compose." in wc:
                    inferred_surfs.add("COMPOSE_UI")
                if "Fragment" in wc or "ViewBinding" in wc or "_binding" in wc:
                    inferred_surfs.add("XML_UI")
                if "@Entity" in wc or "@Database" in wc or "Migration(" in wc:
                    inferred_surfs.update({"ROOM_SCHEMA", "PERSISTENCE"})
                if "PendingIntent" in wc or "SensorManager" in wc or "Bluetooth" in wc:
                    inferred_surfs.add("DEVICE_API")
                if "suspend fun " in wc or "CoroutineScope" in wc or "Flow<" in wc:
                    inferred_surfs.add("COROUTINES")
                if "Retrofit" in wc or "OkHttp" in wc or "http://" in wc or "https://" in wc:
                    inferred_surfs.add("NETWORK")
                if "NavHost" in wc or "Destinations" in wc or "deepLink" in wc:
                    inferred_surfs.add("NAVIGATION")

        draft_ns = _engine.argparse.Namespace(
            repo=str(repo),
            task_id=tid,
            outcome=outcome_str,
            kind=t_kind,
            expected_files=",".join(cold_expected),
            expected_modules=None,
            expected_surfaces=(",".join(sorted(inferred_surfs)) if inferred_surfs else None),
            approach=approach_str,
            risks=risks_str,
            rollback="git checkout -- <expected_files>",
            test_strategy="Run deterministic unit tests and preflight gates locally.",
            device_strategy="Follow project device verification policy.",
            phases=cold_phases_arg,
            architecture_intent=arch_intent_val,
            architecture_target_scope=arch_scope_val,
            architecture_target_family=arch_family_val,
            verification_contract=None,
            external_writes=None,
            zoho_item=None,
            planning_depth="BOUNDED",
            force=False,
            json=True,
        )
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            wf.draft(draft_ns)
        plan_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")
        approve_ns = _engine.argparse.Namespace(
            repo=str(repo),
            task_id=tid,
            source=eff_source,
            proof_reference=eff_proof,
            enforcement_tier="RULE_ENFORCED",
            plan_hash=str(plan_doc.get("plan_sha256") or ""),
            approval_token=None,
            json=True,
        )
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            wf.record_approval(approve_ns)
        try:
            from execution_mode import bind_pending_execution_mode_to_task
            bind_pending_execution_mode_to_task(repo, tid)
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            bind_pending_execution_mode_to_task = None
        active_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")
        initial_approval_in_this_apply = True
    else:
        tid = str(active_doc.get("task_id") or "")
        st_cur = str(active_doc.get("status") or "").upper()
        initial_approval_in_this_apply = False
        import contextlib, io
        if st_cur in {"PLAN_DRAFTED", "AWAITING_DEVELOPER_APPROVAL"}:
            initial_approval_in_this_apply = True
            # Revise scope if needed before approving
            cur_exp = set(active_doc.get("expected_files") or [])
            merged_exp = sorted(cur_exp | set(all_scope_paths))
            if set(merged_exp) != cur_exp:
                rev_ns = _engine.argparse.Namespace(
                    repo=str(repo),
                    task_id=tid,
                    outcome=active_doc.get("requested_outcome") or active_doc.get("outcome"),
                    kind=active_doc.get("task_kind") or "FEATURE",
                    expected_files=",".join(merged_exp),
                    expected_modules=None,
                    expected_surfaces=None,
                    approach=str(plan_spec.get("approach") or active_doc.get("test_strategy") or "Web-Relay implementation"),
                    risks=",".join(active_doc.get("risks") or ["Verify gates"]),
                    rollback=active_doc.get("rollback") or "git checkout",
                    test_strategy=active_doc.get("test_strategy") or "Unit tests",
                    device_strategy=active_doc.get("device_strategy") or "Manual",
                    phases=active_doc.get("phases"),
                    verification_contract=None,
                    external_writes=None,
                    material_change_reason="Include Web-Relay scope files",
                    json=True,
                )
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    wf.revise(rev_ns)
                active_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")
            app_ns = _engine.argparse.Namespace(
                repo=str(repo),
                task_id=tid,
                source=eff_source,
                proof_reference=eff_proof,
                enforcement_tier="RULE_ENFORCED",
                plan_hash=str(active_doc.get("plan_sha256") or ""),
                approval_token=None,
                json=True,
            )
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                wf.record_approval(app_ns)
            active_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")
        elif st_cur == "APPROVED":
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                wf.begin(_engine.argparse.Namespace(repo=str(repo), task_id=tid, json=True))
            active_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")
        elif st_cur in {"VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"}:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                wf.resume(_engine.argparse.Namespace(repo=str(repo), task_id=tid, reopen=(st_cur == "READY_FOR_DELIVERY"), json=True))
            active_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")

        # Extend expected_files via canonical `wf.revise` + `wf.record_approval` so `plan_sha256` and `approval.plan_sha256` stay cryptographically aligned!
        cur_exp_list = list(active_doc.get("expected_files") or [])
        missing_exp = [p for p in all_scope_paths if p not in cur_exp_list]
        if missing_exp:
            merged_mid_exp = sorted(set(cur_exp_list) | set(missing_exp))
            phases_l = [dict(ph) for ph in (active_doc.get("phases") or []) if isinstance(ph, dict)]
            p_i = int(active_doc.get("active_phase_index") or 0)
            if not phases_l and str(active_doc.get("task_kind") or "").upper() != "CONFLICT":
                doc_sfx_m = {".md", ".txt", ".rst", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".xml", ".json", ".properties", ".pro", ".ico"}
                impl_mid = [p for p in merged_mid_exp if Path(p).suffix.lower() not in doc_sfx_m and not _engine.is_kmp_or_android_test_path(p)]
                if len(impl_mid) >= 2:
                    mid_mods: list[str] = []
                    for pm_i in impl_mid:
                        pts_i = pm_i.split("/")
                        mk_i = "/".join(pts_i[: pts_i.index("src")]) if "src" in pts_i and pts_i.index("src") > 0 else (pts_i[0] if len(pts_i) > 1 else ":")
                        if mk_i not in mid_mods:
                            mid_mods.append(mk_i)
                    if len(mid_mods) > 1:
                        ord_mm = sorted(mid_mods, key=lambda m: (1 if m in {"app", "wearApp", "androidApp"} else 0, m))
                        phases_l = [
                            {
                                "id": f"p{idx_mm}",
                                "title": f"Update :{m_pf.replace('/', ':')} implementation" if m_pf != ":" else "Update root implementation",
                                "expected_files": [px for px in merged_mid_exp if (m_pf != ":" and (px == m_pf or px.startswith(m_pf + "/"))) or (m_pf == ":" and "/" not in px)],
                            }
                            for idx_mm, m_pf in enumerate(ord_mm, 1)
                        ]
                        phases_l = [ph for ph in phases_l if ph["expected_files"]]
                    else:
                        phases_l = [{"id": "p1", "title": "Apply scoped implementation and companion updates", "expected_files": list(merged_mid_exp)}]
            if phases_l and 0 <= p_i < len(phases_l):
                def _mod_pref(p_str: str) -> str:
                    norm_s = p_str.replace("\\", "/").strip("/")
                    return norm_s.split("/src/", 1)[0] if "/src/" in norm_s else ""

                ph_mod_sets = [
                    {_mod_pref(ef) for ef in (ph.get("expected_files") or []) if _mod_pref(ef)}
                    for ph in phases_l
                ]
                for mf in missing_exp:
                    mf_mod = _mod_pref(mf)
                    placed_idx = p_i
                    if mf_mod:
                        for cand_idx, mset in enumerate(ph_mod_sets):
                            if mf_mod in mset:
                                placed_idx = cand_idx
                                break
                    cur_ph_exp = list(phases_l[placed_idx].get("expected_files") or [])
                    if cur_ph_exp or len(phases_l) == 1:
                        phases_l[placed_idx]["expected_files"] = sorted(set(cur_ph_exp) | {mf})
            rev_mid_ns = _engine.argparse.Namespace(
                repo=str(repo),
                task_id=tid,
                outcome=active_doc.get("requested_outcome") or active_doc.get("outcome"),
                kind=active_doc.get("task_kind") or "FEATURE",
                expected_files=",".join(merged_mid_exp),
                expected_modules=None,
                expected_surfaces=None,
                approach=str(active_doc.get("approach") or "Web-Relay implementation"),
                risks=",".join(active_doc.get("risks") or ["Verify gates"]),
                rollback=active_doc.get("rollback") or "git checkout",
                test_strategy=active_doc.get("test_strategy") or "Unit tests",
                device_strategy=active_doc.get("device_strategy") or "Manual",
                phases=phases_l if phases_l else None,
                verification_contract=None,
                external_writes=None,
                material_change_reason="Include Web-Relay companion files under developer web-apply authorization",
                json=True,
            )
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                wf.revise(rev_mid_ns)
            revised_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")
            app_mid_ns = _engine.argparse.Namespace(
                repo=str(repo),
                task_id=tid,
                source=eff_source,
                proof_reference=eff_proof,
                enforcement_tier="RULE_ENFORCED",
                plan_hash=str(revised_doc.get("plan_sha256") or ""),
                approval_token=None,
                json=True,
            )
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                wf.record_approval(app_mid_ns)
            active_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")

    # Phase 3: Filter Multi-Phase operations if task has phases (`Collision #3`)
    phases = active_doc.get("phases") or []
    p_idx = int(active_doc.get("active_phase_index") or 0)
    staged_phases_summary: dict[str, list[str]] = {}
    active_writes = list(planned_writes)
    active_deletes = list(planned_deletes)
    if phases and 0 <= p_idx < len(phases):
        def _path_mod_id(rel_p: str) -> str:
            norm_p = rel_p.replace("\\", "/").strip("/")
            if "/src/" in norm_p:
                return ":" + norm_p.split("/src/", 1)[0].replace("/", ":")
            return ""

        def _phase_matches_path(ph_obj: dict[str, Any], rel_p: str) -> bool:
            exp_f = set(ph_obj.get("expected_files") or [])
            if rel_p in exp_f:
                return True
            if exp_f:
                return False
            mod_id = _path_mod_id(rel_p)
            if not mod_id:
                return False
            ph_mods = {str(m).strip() for m in (ph_obj.get("modules") or ph_obj.get("expected_modules") or [])}
            title_mods = set(_engine.re.findall(r":[A-Za-z0-9_.:-]+", str(ph_obj.get("title") or "")))
            return mod_id in (ph_mods | title_mods)

        cur_phase = phases[p_idx]
        future_map: dict[str, dict[str, list[Any]]] = {}
        filtered_w: list[dict[str, Any]] = []
        for w in planned_writes:
            matched_future = None
            if not _phase_matches_path(cur_phase, w["path"]):
                for f_ph in phases[p_idx + 1 :]:
                    if _phase_matches_path(f_ph, w["path"]):
                        matched_future = str(f_ph.get("id") or "")
                        break
            if matched_future:
                future_map.setdefault(matched_future, {"writes": [], "deletes": []})["writes"].append(w)
            else:
                filtered_w.append(w)
        filtered_d: list[str] = []
        for d_path in planned_deletes:
            matched_future_d = None
            if not _phase_matches_path(cur_phase, d_path):
                for f_ph in phases[p_idx + 1 :]:
                    if _phase_matches_path(f_ph, d_path):
                        matched_future_d = str(f_ph.get("id") or "")
                        break
            if matched_future_d:
                future_map.setdefault(matched_future_d, {"writes": [], "deletes": []})["deletes"].append(d_path)
            else:
                filtered_d.append(d_path)
        for f_pid, bucket in future_map.items():
            st_dir = _engine.task_dir(repo, tid) / "staged-web-phases"
            st_dir.mkdir(parents=True, exist_ok=True)
            st_file = st_dir / f"{f_pid}.json"
            if st_file.is_file():
                try:
                    prev_b = _engine.read_json(st_file)
                    if isinstance(prev_b, dict):
                        new_w_paths = {x["path"] for x in bucket["writes"]}
                        merged_w = [
                            x for x in (prev_b.get("writes") or [])
                            if isinstance(x, dict) and x.get("path") not in new_w_paths
                        ] + bucket["writes"]
                        merged_d = sorted((set(prev_b.get("deletes") or []) - new_w_paths) | set(bucket["deletes"]))
                        bucket = {"writes": merged_w, "deletes": merged_d}
                except (OSError, ValueError, _engine.ValidationError):
                    pass
            bucket = {
                "task_id": tid,
                "phase_id": f_pid,
                "writes": list(bucket.get("writes") or []),
                "deletes": list(bucket.get("deletes") or []),
            }
            bucket["staged_sha256"] = _engine.canonical_sha256({
                "task_id": tid,
                "phase_id": f_pid,
                "writes": bucket["writes"],
                "deletes": bucket["deletes"],
            })
            _engine.atomic_write_json(st_file, bucket)
            staged_phases_summary[f_pid] = [x["path"] for x in bucket["writes"]] + list(bucket["deletes"])
        active_writes = filtered_w
        active_deletes = filtered_d

    # Phase 4: Automatic `BUG` `RED -> GREEN` 2-Step Apply (`Collision #2`)
    tdir = _engine.task_dir(repo, tid)
    red_ev_file = tdir / "red-evidence.json"
    t_kind_upper = str(active_doc.get("task_kind") or "").upper()
    test_writes = [w for w in active_writes if w.get("is_test")]
    prod_writes = [w for w in active_writes if not w.get("is_test")]
    auto_red_result: dict[str, Any] | None = None

    if (
        auto_red_green
        and t_kind_upper == "BUG"
        and not red_ev_file.is_file()
        and test_writes
        and (prod_writes or active_deletes)
    ):
        for tw in test_writes:
            dst = repo / tw["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(_engine._apply_eol(tw["content"], tw["eol"]))
        gate_env = {**_engine.os.environ, "HARNESS_REPO": str(repo), "PYTHONIOENCODING": "utf-8"}
        tests_script = (repo / ".agents" / "scripts" / "run_tests_gate.py") if (repo / ".agents" / "scripts" / "run_tests_gate.py").is_file() else (_engine.SCRIPTS_DIR / "run_tests_gate.py")
        proc_red = _engine.subprocess.run(
            [_engine.sys.executable, str(tests_script), "--capture-red"],
            cwd=repo,
            env=gate_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        auto_red_result = {
            "attempted": True,
            "captured": red_ev_file.is_file(),
            "exit_code": proc_red.returncode,
        }

    # Write all active phase files & deletes onto disk
    for w in active_writes:
        dst = repo / w["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(_engine._apply_eol(w["content"], w["eol"]))
    for d_path in active_deletes:
        (repo / d_path).unlink(missing_ok=True)

    # Mark pack consumed (`Safeguard #7`) — or keep open for continuation when `status == "PARTIAL"`!
    is_partial_reply = str(payload.get("status") or "").strip().upper() in {"PARTIAL", "PARTIAL_BATCH", "CONTINUE"}
    if is_partial_reply:
        pack_doc["applied"] = False
        pack_doc["partial_batches_applied"] = int(pack_doc.get("partial_batches_applied") or 0) + 1
        pack_doc["last_partial_applied_at"] = _engine.utc_now()
        pack_doc["task_id"] = tid
        _engine.atomic_write_json(tdir / "latest-web-pack.json", {
            "pack_id": pack_id,
            "task_id": tid,
            "bundle_file": str(pack_doc.get("bundle_file") or ""),
            "created_at": str(pack_doc.get("created_at") or _engine.utc_now()),
        })
        # Refresh base_text/sha256 of modified files so subsequent continuation hunks apply cleanly
        ed_map = dict(pack_doc.get("editable_files") or {})
        for w in active_writes:
            w_norm = w["content"].replace("\r\n", "\n").replace("\r", "\n")
            ed_map[w["path"]] = {"exists": True, "sha256": _engine._sha256_lf(w_norm), "eol": w["eol"], "base_text": w_norm}
        for d_p in active_deletes:
            ed_map.pop(d_p, None)
        pack_doc["editable_files"] = ed_map
    else:
        pack_doc["applied"] = True
        pack_doc["applied_at"] = _engine.utc_now()
        pack_doc["applied_task_id"] = tid
    _engine.atomic_write_json(pack_path, pack_doc)

    # Surface & Sensitive-Surface Check (`Safeguard #6`)
    detected_surfaces: list[str] = []
    sensitive_surfaces: list[str] = []
    t_manifest = {}
    try:
        from delivery_manifest import build_task_manifest, load_task_baseline
        t_manifest = build_task_manifest(repo, load_task_baseline(repo, tid), expected_files=active_doc.get("expected_files"))
    except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
        pass
    try:
        from change_classifier import classify
        cls_res = classify(repo, task_id=tid, progress=False)
        detected_surfaces = list(cls_res.get("surfaces") or [])
        sensitive_surfaces = [s for s in detected_surfaces if s in {"AUTH", "BILLING", "CRYPTO", "SENSITIVE_DATA", "MANIFEST_PERMISSION"}]
        # If newly written file contents introduced surfaces/skills not visible before disk write (e.g. cold-start CREATE @Composable -> compose-inspector), sync plan + approval hash!
        planned_surfs = set(active_doc.get("expected_surfaces") or [])
        extra_surfs = set(detected_surfaces) - planned_surfs
        if extra_surfs and not staged_phases_summary:
            from policy_vocab import CRITICAL_SURFACES, HIGH_SURFACES
            escalating_surfs = extra_surfs & (
                set(CRITICAL_SURFACES) | set(HIGH_SURFACES) | {"ROOM_SCHEMA", "MANIFEST_PERMISSION", "PERSISTENCE", "NETWORK"}
            )
            if initial_approval_in_this_apply:
                import contextlib, io
                merged_surfs = sorted(planned_surfs | set(detected_surfaces))
                arch_c = active_doc.get("architecture_contract") or {}
                rev_surf_ns = _engine.argparse.Namespace(
                    repo=str(repo),
                    task_id=tid,
                    outcome=active_doc.get("requested_outcome") or active_doc.get("outcome"),
                    kind=active_doc.get("task_kind") or "FEATURE",
                    expected_files=",".join(active_doc.get("expected_files") or []),
                    expected_modules=",".join(active_doc.get("expected_modules") or []) or None,
                    expected_surfaces=",".join(merged_surfs),
                    approach=str(active_doc.get("approach") or "Web-Relay implementation"),
                    risks=",".join(active_doc.get("risks") or ["Verify gates"]),
                    rollback=active_doc.get("rollback") or "git checkout",
                    test_strategy=active_doc.get("test_strategy") or "Unit tests",
                    device_strategy=active_doc.get("device_strategy") or "Manual",
                    phases=active_doc.get("phases") or None,
                    architecture_intent=("NEW_FEATURE" if arch_c.get("mode") == "NEW" else None),
                    architecture_target_scope=arch_c.get("target_scope"),
                    architecture_target_family=arch_c.get("target_family_id"),
                    verification_contract=None,
                    external_writes=None,
                    material_change_reason="Sync detected surfaces and skills from applied Web-Relay files",
                    json=True,
                )
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    wf.revise(rev_surf_ns)
                rev_s_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")
                app_surf_ns = _engine.argparse.Namespace(
                    repo=str(repo),
                    task_id=tid,
                    source=eff_source,
                    proof_reference=eff_proof,
                    enforcement_tier="RULE_ENFORCED",
                    plan_hash=str(rev_s_doc.get("plan_sha256") or ""),
                    approval_token=None,
                    json=True,
                )
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    wf.record_approval(app_surf_ns)
                active_doc = _engine.read_json(_engine.task_dir(repo, tid) / "plan.json")
            elif not escalating_surfs and int(active_doc.get("review_rounds") or 0) == 0:
                from plan_authority import compute_plan_hash, save_plan
                old_sha = str(active_doc.get("plan_sha256") or "")
                active_doc["expected_surfaces"] = sorted(planned_surfs | set(detected_surfaces))
                if old_sha:
                    absorbed = list(active_doc.get("in_place_absorbed_plan_shas") or [])
                    if old_sha not in absorbed:
                        absorbed.append(old_sha)
                    active_doc["in_place_absorbed_plan_shas"] = absorbed
                    active_doc["supersedes_plan_sha256"] = old_sha
                new_sha = compute_plan_hash(active_doc)
                active_doc["plan_sha256"] = new_sha
                if isinstance(active_doc.get("approval"), dict):
                    active_doc["approval"]["plan_sha256"] = new_sha
                save_plan(_engine.task_dir(repo, tid) / "plan.json", active_doc)
    except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
        pass

    # Run fast zero-token static checks (`fast_kt_lint` + `check_strings`) & write `Zero Re-Read` receipt (`Collision #6`)
    gate_env = {**_engine.os.environ, "HARNESS_REPO": str(repo), "PYTHONIOENCODING": "utf-8"}
    lint_script = (repo / ".agents" / "scripts" / "fast_kt_lint.py") if (repo / ".agents" / "scripts" / "fast_kt_lint.py").is_file() else (_engine.SCRIPTS_DIR / "fast_kt_lint.py")
    str_script = (repo / ".agents" / "scripts" / "check_strings.py") if (repo / ".agents" / "scripts" / "check_strings.py").is_file() else (_engine.SCRIPTS_DIR / "check_strings.py")
    lint_proc = _engine.subprocess.run(
        [_engine.sys.executable, str(lint_script)],
        cwd=repo,
        env=gate_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    str_proc = _engine.subprocess.run(
        [_engine.sys.executable, str(str_script)],
        cwd=repo,
        env=gate_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    # Auto-advance queued multi-batch packs (`41–250` file refactors) automatically onto Clipboard!
    next_batch_pack_info: dict[str, Any] | None = None
    pending_batches_q = [list(b) for b in (pack_doc.get("pending_batches") or []) if b]
    if not is_partial_reply and pending_batches_q:
        next_batch_files = pending_batches_q[0]
        rest_batches = pending_batches_q[1:]
        next_b_idx = int(pack_doc.get("batch_index") or 1) + 1
        tot_b = int(pack_doc.get("total_batches") or (next_b_idx + len(rest_batches)))
        next_batch_pack_info = _engine.build_web_pack(
            repo,
            task_id=tid,
            prompt=str(pack_doc.get("prompt") or ""),
            kind=str(pack_doc.get("kind") or ""),
            files=next_batch_files,
            no_clipboard=(_engine.os.environ.get("HARNESS_NO_CLIPBOARD") == "1"),
            batch_size=int(pack_doc.get("batch_size") or _engine.DEFAULT_WEB_PACK_BATCH_SIZE),
            batch_index=next_b_idx,
            total_batches_hint=tot_b,
            remaining_batches_override=rest_batches,
        )

    prev_written: list[str] = []
    prev_deleted: list[str] = []
    prev_post_shas: dict[str, str] = {}
    prev_rec_f = tdir / "web-relay-receipt.json"
    if prev_rec_f.is_file():
        try:
            pr_doc = _engine.read_json(prev_rec_f)
            if isinstance(pr_doc, dict) and str(pr_doc.get("task_id") or "") == tid:
                prev_written = [str(x) for x in (pr_doc.get("files_written") or []) if str(x).strip()]
                prev_deleted = [str(x) for x in (pr_doc.get("files_deleted") or []) if str(x).strip()]
                if isinstance(pr_doc.get("post_apply_sha256"), dict):
                    prev_post_shas = {
                        str(k): str(v)
                        for k, v in pr_doc["post_apply_sha256"].items()
                        if str(k).strip() and str(v).strip()
                    }
        except (OSError, ValueError, _engine.ValidationError):
            pass

    cum_written = list(dict.fromkeys([*prev_written, *(w["path"] for w in active_writes)]))
    cum_deleted = list(dict.fromkeys([*(x for x in prev_deleted if x not in cum_written), *active_deletes]))
    post_apply_shas = {k: v for k, v in prev_post_shas.items() if k not in cum_deleted}
    for w in active_writes:
        w_lf = str(w["content"]).replace("\r\n", "\n").replace("\r", "\n")
        post_apply_shas[w["path"]] = _engine._sha256_lf(w_lf)
    if payload_origin.startswith("downloads:") or payload_origin.startswith("file:"):
        raw_orig_p = payload_origin.split(":", 1)[1]
        try:
            orig_p = Path(raw_orig_p).resolve()
            inbox_root = (_engine._web_relay_state_dir(repo) / "inbox").resolve()
            if orig_p.is_file() and orig_p.parent == inbox_root:
                orig_p.unlink(missing_ok=True)
        except OSError:
            pass
    receipt_doc = {
        "schema_version": 1,
        "pack_id": pack_id,
        "task_id": tid,
        "origin": payload_origin,
        "applied_at": _engine.utc_now(),
        "change_set_sha256": str((t_manifest or {}).get("change_set_sha256") or ""),
        "files_written": cum_written,
        "files_deleted": cum_deleted,
        "post_apply_sha256": post_apply_shas,
        "incomplete_continuation": bool(is_partial_reply or next_batch_pack_info is not None),
        "fast_kt_lint_ok": lint_proc.returncode == 0,
        "check_strings_ok": str_proc.returncode == 0,
    }
    _engine.atomic_write_json(prev_rec_f, receipt_doc)

    phases_now = active_doc.get("phases") or []
    p_idx_now = int(active_doc.get("active_phase_index") or 0)
    gate_findings: dict[str, list[str]] = {}
    kdoc_advisories = [
        ln.strip()
        for ln in (lint_proc.stdout or "").splitlines()
        if ln.strip().startswith("[KDOC-ADVISORY]")
    ][:20]
    if lint_proc.returncode != 0:
        lint_lines = [ln.strip() for ln in ((lint_proc.stdout or "") + "\n" + (lint_proc.stderr or "")).splitlines() if ln.strip()]
        if lint_lines:
            gate_findings["fast_kt_lint"] = lint_lines[:20]
    if str_proc.returncode != 0:
        str_lines = [ln.strip() for ln in ((str_proc.stdout or "") + "\n" + (str_proc.stderr or "")).splitlines() if ln.strip()]
        if str_lines:
            gate_findings["check_strings"] = str_lines[:20]

    ready_single_pass = False
    if phases_now and not is_partial_reply and next_batch_pack_info is None and not staged_phases_summary:
        try:
            from workflow import all_remaining_phases_ready_for_final
            ready_single_pass, _ = all_remaining_phases_ready_for_final(repo, tid, active_doc)
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            ready_single_pass = False

    kdoc_inline_hint = (
        f"First add concise English KDoc (`/** ... */`) on the {len(kdoc_advisories)} newly added contract(s) listed in `kdoc_advisories` via `edit_file`, then run: "
        if kdoc_advisories
        else ""
    )
    if is_partial_reply:
        next_cmd = 'Stay in the SAME external AI chat, ask `Continue remaining files for this pack_id`, and run `python .agents/harness.py web-apply --source conversation --proof-reference "<words>"`.'
    elif next_batch_pack_info is not None:
        next_cmd = (
            f"Batch {next_batch_pack_info['batch_index']}/{next_batch_pack_info['total_batches']} "
            f"(`{next_batch_pack_info['pack_id']}`) is now copied to Clipboard — stay in the SAME external AI chat, paste/attach the next batch, and run `web-apply`."
        )
    elif phases_now and 0 <= p_idx_now < len(phases_now) and not ready_single_pass:
        cur_pid = str(phases_now[p_idx_now].get("id") or "p1")
        if (
            len(phases_now) - p_idx_now > 1
            and not staged_phases_summary
            and not bool(active_doc.get("scoped_phase_review_enabled"))
        ):
            next_cmd = kdoc_inline_hint + f'python .agents/harness.py task checkpoint-phase --repo . --task-id {tid} --phase-id "{cur_pid}" --advance-all-ready'
        else:
            next_cmd = kdoc_inline_hint + f'python .agents/harness.py task checkpoint-phase --repo . --task-id {tid} --phase-id "{cur_pid}"'
    elif gate_findings:
        next_cmd = (
            f"Fix zero_token_gate_findings"
            + (" and `kdoc_advisories`" if kdoc_advisories else "")
            + f" via surgical edit_file (or run `python .agents/harness.py web-pack --task-id {tid} --retry-failure` for multi-line fixes), then run `python .agents/harness.py verify-steps --task-id {tid} --host antigravity`."
        )
    elif kdoc_advisories:
        next_cmd = (
            f"Add concise English KDoc (`/** ... */`) on the {len(kdoc_advisories)} newly added contract(s) in `kdoc_advisories` via surgical `edit_file`, "
            f"then run `python .agents/harness.py verify-steps --task-id {tid} --host antigravity`."
        )
    else:
        next_cmd = f"python .agents/harness.py verify-steps --task-id {tid} --host antigravity"

    ret_apply: dict[str, Any] = {
        "status": "APPLIED_PARTIAL_BATCH" if is_partial_reply else ("APPLIED_BATCH_NEXT_READY" if next_batch_pack_info else "APPLIED"),
        "pack_id": pack_id,
        "task_id": tid,
        "origin": payload_origin,
        "files_written": [w["path"] for w in active_writes],
        "files_deleted": active_deletes,
        "partial_continuation_open": is_partial_reply,
        "next_batch_pack": next_batch_pack_info,
        "staged_future_phases": staged_phases_summary,
        "auto_red_reproduction": auto_red_result,
        "detected_surfaces": detected_surfaces,
        "sensitive_surfaces_requiring_approval": sensitive_surfaces,
        "zero_token_gates": {
            "fast_kt_lint": "PASS" if lint_proc.returncode == 0 else "FINDINGS",
            "check_strings": "PASS" if str_proc.returncode == 0 else "FINDINGS",
        },
        "next_recommended_command": next_cmd,
    }
    if gate_findings:
        ret_apply["zero_token_gate_findings"] = gate_findings
    if kdoc_advisories:
        ret_apply["kdoc_advisories"] = kdoc_advisories
    return ret_apply
