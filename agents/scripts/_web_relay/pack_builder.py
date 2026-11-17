"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


def _infer_task_kind(prompt: str, explicit_kind: str | None) -> str:
    if explicit_kind:
        k = explicit_kind.strip().upper()
        if k in {"FEATURE", "BUG", "REFACTOR", "CONFLICT"}:
            return k
    low = (prompt or "").lower()
    bug_tokens = ("bug", "crash", "fix ", "broken", "off by", "leak", "exception", "باج", "بج", "مشكلة", "خطأ", "بيخصم", "بيضرب")
    if any(t in low for t in bug_tokens):
        return "BUG"
    conflict_tokens = ("merge conflict", "git conflict", "resolve conflict", "تعارض", "كونفليكت")
    if any(t in low for t in conflict_tokens):
        return "CONFLICT"
    ref_tokens = ("refactor", "rename", "extract", "cleanup", "إعادة هيكلة", "تنظيف")
    if any(t in low for t in ref_tokens):
        return "REFACTOR"
    return "FEATURE"
def _collect_git_dirty_source_files(
    repo: Path,
    rejected_secret_files: list[str] | None = None,
) -> list[str]:
    """Collect modified, staged, renamed, and untracked source/resource files from the Git working tree."""
    found: list[str] = []
    seen_d: set[str] = set()
    try:
        out = _engine.subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uall"],
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, _engine.subprocess.SubprocessError):
        return []
    for raw_ln in out.splitlines():
        if len(raw_ln) < 4:
            continue
        status_xy = raw_ln[:2]
        if "D" in status_xy:
            continue
        raw_p = raw_ln[3:].strip()
        if " -> " in raw_p:
            raw_p = raw_p.split(" -> ", 1)[1].strip()
        raw_p = raw_p.strip('"')
        try:
            rel = _engine._norm_rel(repo, raw_p)
        except _engine.ValidationError:
            continue
        low_parts = rel.lower().split("/")
        if any(seg in {"build", ".gradle", ".idea", "out", "node_modules", "__pycache__"} for seg in low_parts[:-1]):
            continue
        blocked, _ = _engine._is_protected_or_secret_path(rel)
        if blocked:
            if rejected_secret_files is not None and rel not in rejected_secret_files:
                rejected_secret_files.append(rel)
            continue
        fp = repo / rel
        if not fp.is_file() or Path(rel).suffix.lower() not in _engine.DIRTY_SOURCE_SUFFIXES:
            continue
        if _engine._is_binary_asset(rel):
            continue
        if rel not in seen_d:
            seen_d.add(rel)
            found.append(rel)
    return found
def _discover_scope_files(
    repo: Path,
    *,
    explicit_files: list[str],
    feature_query: str,
    symbol_query: str,
    prompt_text: str,
    active_plan_doc: dict[str, Any] | None,
    rejected_secret_files: list[str] | None = None,
    include_git_dirty: bool = False,
    captured_dirty_out: list[str] | None = None,
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(cand: str) -> None:
        try:
            rel = _engine._norm_rel(repo, cand)
        except _engine.ValidationError:
            return
        blocked, _ = _engine._is_protected_or_secret_path(rel)
        if blocked:
            if rejected_secret_files is not None and rel not in rejected_secret_files:
                rejected_secret_files.append(rel)
            return
        if rel in seen:
            return
        seen.add(rel)
        ordered.append(rel)

    for f in explicit_files:
        for part in str(f).split(","):
            if part.strip():
                _add(part.strip())

    if include_git_dirty:
        for d_rel in _engine._collect_git_dirty_source_files(repo, rejected_secret_files):
            before_n = len(ordered)
            _add(d_rel)
            if captured_dirty_out is not None and (len(ordered) > before_n or d_rel in seen) and d_rel not in captured_dirty_out:
                captured_dirty_out.append(d_rel)

    if active_plan_doc and not ordered:
        phases = active_plan_doc.get("phases") or []
        p_idx = int(active_plan_doc.get("active_phase_index") or 0)
        if phases and 0 <= p_idx < len(phases) and isinstance(phases[p_idx], dict):
            for f in phases[p_idx].get("expected_files") or []:
                _add(str(f))
        for f in active_plan_doc.get("expected_files") or []:
            _add(str(f))

    if not ordered:
        try:
            from _graph_core import GraphEngine
            ge = GraphEngine(repo)
            ge.ensure_loaded()
            queries: list[str] = []
            if symbol_query:
                queries.append(symbol_query.strip())
            if feature_query:
                queries.append(feature_query.strip())
            for tok in _engine.re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", prompt_text or ""):
                if tok not in queries:
                    queries.append(tok)
            for q in queries[:8]:
                res = ge.find_symbol(q, limit=6)
                for m in res.get("matches") or []:
                    fp = str(m.get("file_path") or "")
                    if fp:
                        _add(fp)
                if len(ordered) >= 10:
                    break
        except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
            pass

    if not ordered and prompt_text:
        tokens = [t.lower() for t in _engine.re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", prompt_text)]
        if tokens:
            try:
                tracked = _engine.subprocess.check_output(
                    ["git", "-c", "core.quotepath=false", "ls-files"],
                    cwd=repo,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
                scored: list[tuple[int, str]] = []
                for rel in tracked:
                    low = rel.lower()
                    if not low.endswith((".kt", ".java", ".xml", ".swift", ".kts")):
                        continue
                    hits = sum(2 if tok in Path(low).stem else (1 if tok in low else 0) for tok in tokens)
                    if hits > 0:
                        scored.append((hits, rel))
                scored.sort(key=lambda item: (-item[0], len(item[1])))
                for _, rel in scored[:8]:
                    _add(rel)
            except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
                pass

    # Automatic IDLE Studio-to-Web fallback: if no explicit files or AST symbols matched yet, capture open Git working-tree edits!
    if not ordered and not active_plan_doc:
        for d_rel in _engine._collect_git_dirty_source_files(repo, rejected_secret_files):
            _add(d_rel)
            if captured_dirty_out is not None and d_rel not in captured_dirty_out:
                captured_dirty_out.append(d_rel)

    # Auto-include git unmerged conflict paths if repository is in a merge/rebase conflict state
    try:
        from _vnext_common import unmerged_paths
        for u_rel in unmerged_paths(repo):
            _add(u_rel)
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        pass

    try:
        tracked_all = _engine.subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "ls-files"],
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except (OSError, _engine.subprocess.SubprocessError):
        tracked_all = []

    # Auto-include sibling localized `values-*/strings.xml` when `values/strings.xml` is in scope (works at any task size!)
    for cur_rel in list(ordered):
        if cur_rel.endswith("/res/values/strings.xml") or cur_rel == "res/values/strings.xml":
            res_parent = (repo / cur_rel).parent.parent
            if res_parent.is_dir():
                for sib in sorted(res_parent.glob("values-*/strings.xml")):
                    if sib.is_file() and len(ordered) < _engine.MAX_WEB_PACK_TOTAL_FILES:
                        _add(sib.relative_to(repo).as_posix())

    # Auto-include module `@Database` / `*DatabaseModule*.kt` when an `@Entity` file is in scope (single-pass Room migrations)
    has_room_entity = False
    entity_module_prefixes: set[str] = set()
    for cur_rel in list(ordered):
        fp_c = repo / cur_rel
        if fp_c.is_file() and cur_rel.endswith((".kt", ".java")) and not _engine._is_binary_asset(cur_rel):
            c_txt = fp_c.read_text(encoding="utf-8", errors="replace")
            if "@Entity" in c_txt:
                has_room_entity = True
                if "/src/" in cur_rel:
                    entity_module_prefixes.add(cur_rel.split("/src/", 1)[0] + "/src/")
    if has_room_entity:
        db_added = 0
        for rel in tracked_all:
            if db_added >= 3 or len(ordered) >= _engine.MAX_WEB_PACK_TOTAL_FILES:
                break
            if not rel.endswith((".kt", ".java")) or _engine.is_kmp_or_android_test_path(rel) or rel in seen:
                continue
            if entity_module_prefixes and not any(rel.startswith(pref) for pref in entity_module_prefixes):
                continue
            fp_db = repo / rel
            if fp_db.is_file():
                db_txt = fp_db.read_text(encoding="utf-8", errors="replace")
                if "@Database" in db_txt or "Room.databaseBuilder" in db_txt:
                    _add(rel)
                    db_added += 1

    # Auto-include existing companion unit test files (capped at +12 auto-tests so 100-file refactors stay focused)
    stems = {Path(f).stem for f in list(ordered) if f.endswith((".kt", ".java")) and not _engine.is_kmp_or_android_test_path(f)}
    tests_added = 0
    for rel in tracked_all:
        if tests_added >= 12 or len(ordered) >= _engine.MAX_WEB_PACK_TOTAL_FILES:
            break
        if rel not in seen and _engine.is_kmp_or_android_test_path(rel) and any(Path(rel).stem.startswith(s + "Test") or Path(rel).stem == f"{s}Test" for s in stems):
            _add(rel)
            tests_added += 1

    return ordered[:_engine.MAX_WEB_PACK_TOTAL_FILES]
def _extract_neighbor_signatures(repo: Path, scope_files: list[str], vault: dict[str, str]) -> list[dict[str, str]]:
    """Extract compact read-only AST/declaration signatures for direct imported repo classes."""
    scope_set = set(scope_files)
    imported_simple_names: set[str] = set()
    pkg_re = _engine.re.compile(r"^\s*import\s+([A-Za-z0-9_.]+)\.([A-Z][A-Za-z0-9_]*)\s*$", _engine.re.MULTILINE)
    decl_line_re = _engine.re.compile(
        r"^\s*(?:@(?:Entity|Dao|Module|HiltViewModel|Composable|Serializable)\b[^\n]*\n\s*)*"
        r"(?:public\s+|internal\s+|abstract\s+|open\s+|sealed\s+|data\s+|enum\s+|value\s+)*"
        r"(?:class|interface|object|fun|val|var|typealias)\s+[^\n{=]+",
        _engine.re.MULTILINE,
    )

    for rel in scope_files:
        fp = repo / rel
        if not fp.is_file() or not rel.endswith((".kt", ".java", ".swift")):
            continue
        txt = fp.read_text(encoding="utf-8", errors="replace")
        for m in pkg_re.finditer(txt):
            pkg_prefix = m.group(1)
            cls_name = m.group(2)
            if not pkg_prefix.startswith(("java.", "javax.", "kotlin.", "kotlinx.", "android.", "androidx.", "org.junit", "dagger.")):
                imported_simple_names.add(cls_name)

    if not imported_simple_names:
        return []

    neighbors: list[dict[str, str]] = []
    try:
        tracked = _engine.subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "ls-files"],
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except (OSError, _engine.subprocess.SubprocessError):
        tracked = []

    for rel in tracked:
        if len(neighbors) >= 20:
            break
        if rel in scope_set or not rel.endswith((".kt", ".java", ".swift")):
            continue
        blocked, _ = _engine._is_protected_or_secret_path(rel)
        if blocked:
            continue
        if Path(rel).stem not in imported_simple_names:
            continue
        fp = repo / rel
        if not fp.is_file():
            continue
        raw_txt = fp.read_text(encoding="utf-8", errors="replace")
        pkg_line = ""
        for ln in raw_txt.splitlines()[:10]:
            if ln.strip().startswith("package "):
                pkg_line = ln.strip()
                break
        sigs = [m.group(0).strip() for m in decl_line_re.finditer(raw_txt)][:24]
        if sigs:
            skeleton = (f"{pkg_line}\n" if pkg_line else "") + "\n".join(sigs)
            neighbors.append({
                "path": rel,
                "signatures": _engine._redact_inline_secrets(skeleton[:1800], vault),
            })
    return neighbors
def _collect_active_diagnostics(repo: Path, task_id: str, *, live_static_fallback: bool = False) -> str:
    chunks: list[str] = []
    seen_gates: set[str] = set()
    any_gradle_fail = False
    s_root = _engine.state_root(repo)

    # 1. Authoritative EvidenceStore run failures (`tasks/<task_id>/current-run.json`)
    if task_id:
        cur_run_f = s_root / "tasks" / task_id / "current-run.json"
        if cur_run_f.is_file():
            try:
                cur_doc = _engine.read_json(cur_run_f)
                snap = str(cur_doc.get("delivery_snapshot_sha256") or "").strip()
                run_id = str(cur_doc.get("run_id") or "").strip()
                run_dir = (s_root / "runs" / snap / run_id) if (snap and run_id) else None
                if run_dir is not None and run_dir.is_dir():
                    for ev_f in sorted(run_dir.glob("*.json")):
                        try:
                            ev_doc = _engine.read_json(ev_f)
                            att_dir = run_dir / "attempts" / ev_f.stem
                            if att_dir.is_dir():
                                att_files = sorted(att_dir.glob("*.json"))
                                if att_files:
                                    ev_doc = _engine.read_json(att_files[-1])
                            ev_body = ev_doc.get("evidence") if isinstance(ev_doc.get("evidence"), dict) else ev_doc
                            ev_st = str(ev_doc.get("status") or ev_body.get("status") or "").upper()
                            ev_vd = str(ev_body.get("verdict") or ev_doc.get("verdict") or "").upper()
                            if ev_st == "FAIL" or ev_vd == "BLOCK":
                                seen_gates.add(ev_f.stem)
                                if ev_f.stem in {"unit_tests", "assemble"} or ev_f.stem.startswith("gradle-"):
                                    any_gradle_fail = True
                                lines_ev = [f"### Failing Verification Gate: `{ev_f.stem}`"]
                                det = str(ev_body.get("detail") or ev_body.get("summary") or "").strip()
                                if det:
                                    lines_ev.append(f"- Detail: {det[:800]}")
                                regs = ev_body.get("new_regressions")
                                if isinstance(regs, list) and regs:
                                    lines_ev.append("- Regressions: " + ", ".join(str(x) for x in regs[:12]))
                                f_causes = ev_body.get("failure_causes")
                                if isinstance(f_causes, dict) and f_causes:
                                    for fk, fv in list(f_causes.items())[:8]:
                                        lines_ev.append(f"  - `{fk}`: {str(fv)[:300]}")
                                findings = ev_body.get("blocking_findings") or ev_body.get("findings")
                                if isinstance(findings, list) and findings:
                                    for fn in findings[:8]:
                                        lines_ev.append(f"  - Finding: {_engine.json.dumps(fn, ensure_ascii=False)[:350]}")
                                tail = str(ev_body.get("output_tail") or ev_body.get("stderr_tail") or "").strip()
                                if tail:
                                    lines_ev.append(f"- Output tail: {tail[:1000]}")
                                chunks.append("\n".join(lines_ev))
                        except (OSError, ValueError, _engine.ValidationError):
                            continue
            except (OSError, ValueError, _engine.ValidationError):
                pass

    # 2. Diagnostic mirror `.agents/state/results/*.json`
    res_dir = s_root / "results"
    if res_dir.is_dir():
        for r_file in sorted(res_dir.glob("*.json")):
            try:
                rdoc = _engine.read_json(r_file)
                if str(rdoc.get("status") or "").upper() == "FAIL":
                    if r_file.stem.startswith("gradle-") or r_file.stem in {"unit_tests", "assemble"}:
                        any_gradle_fail = True
                    if r_file.stem in seen_gates:
                        continue
                    seen_gates.add(r_file.stem)
                    r_lines = [f"### Failing Local Gate: `{r_file.stem}`"]
                    r_det = str(rdoc.get("detail") or rdoc.get("summary") or "").strip()
                    if r_det:
                        r_lines.append(f"- Detail: {r_det[:800]}")
                    r_regs = rdoc.get("new_regressions")
                    if isinstance(r_regs, list) and r_regs:
                        r_lines.append("- Regressions: " + ", ".join(str(x) for x in r_regs[:12]))
                    r_diag = rdoc.get("diagnostics")
                    if isinstance(r_diag, dict) and r_diag:
                        for dk, dv in list(r_diag.items())[:8]:
                            r_lines.append(f"  - `{dk}`: {str(dv)[:300]}")
                    r_tail = str(rdoc.get("output_tail") or rdoc.get("stderr_tail") or "").strip()
                    if r_tail:
                        r_lines.append(f"- Output tail: {r_tail[:1000]}")
                    chunks.append("\n".join(r_lines))
            except (OSError, ValueError, _engine.ValidationError):
                continue

    # 3. Phase checkpoint failures (`tasks/<task_id>/phases/*/checkpoint.json`)
    if task_id:
        ph_root = s_root / "tasks" / task_id / "phases"
        if ph_root.is_dir():
            for cp_file in sorted(ph_root.glob("*/checkpoint.json")):
                try:
                    cp_doc = _engine.read_json(cp_file)
                    cp_st = str(cp_doc.get("status") or "").upper()
                    comp_st = str(cp_doc.get("compile_status") or "").upper()
                    tst_st = str(cp_doc.get("test_status") or "").upper()
                    if cp_st == "FAIL" or comp_st == "FAIL" or tst_st == "FAIL":
                        any_gradle_fail = True
                        chunks.append(
                            f"### Failing Phase Checkpoint: `{cp_file.parent.name}`\n"
                            f"- compile={comp_st or 'N/A'}, test={tst_st or 'N/A'}: "
                            f"{str(cp_doc.get('detail') or cp_doc.get('reason') or '')[:600]}"
                        )
                except (OSError, ValueError, _engine.ValidationError):
                    continue

    # 4. Structured kotlinc / javac errors from `.agents/state/logs/gradle/*.log`
    if any_gradle_fail:
        g_log_dir = s_root / "logs" / "gradle"
        if g_log_dir.is_dir():
            try:
                from gradle_error_parser import format_errors, parse_compiler_errors
                logs_sorted = sorted(
                    g_log_dir.glob("*.log"),
                    key=lambda p: (p.stat().st_mtime_ns, p.name),
                    reverse=True,
                )
                for g_log in logs_sorted[:2]:
                    raw_g = g_log.read_text(encoding="utf-8", errors="replace")
                    parsed_errs = parse_compiler_errors(raw_g)
                    if parsed_errs:
                        chunks.append("### Compiler Diagnostics (`gradle_error_parser`)\n" + format_errors(parsed_errs[:20]))
                        break
                    if "FAILURE:" in raw_g or "* What went wrong:" in raw_g:
                        err_lines = [
                            ln.strip()
                            for ln in raw_g.splitlines()
                            if ln.strip() and any(tok in ln for tok in ("FAILURE:", "* What went wrong:", "Execution failed", "> ", "Exception", "Error:"))
                        ][:18]
                        if err_lines:
                            chunks.append("### Gradle Failure Summary\n" + "\n".join(err_lines)[:1200])
                            break
            except (ImportError, OSError, ValueError):
                pass

    # 5. Live zero-token static fallback (`fast_kt_lint` + `check_strings`) when retrying post-apply or pre-gate failures
    rec_lint_bad = False
    rec_str_bad = False
    if task_id:
        rec_f = s_root / "tasks" / task_id / "web-relay-receipt.json"
        if rec_f.is_file():
            try:
                rec_doc = _engine.read_json(rec_f)
                rec_lint_bad = rec_doc.get("fast_kt_lint_ok") is False
                rec_str_bad = rec_doc.get("check_strings_ok") is False
            except (OSError, ValueError, _engine.ValidationError):
                pass
    if live_static_fallback and (not chunks or rec_lint_bad or rec_str_bad):
        gate_env = {**_engine.os.environ, "HARNESS_REPO": str(repo), "PYTHONIOENCODING": "utf-8"}
        for g_label, g_name, should_probe in (
            ("fast_kt_lint", "fast_kt_lint.py", not chunks or rec_lint_bad),
            ("check_strings", "check_strings.py", not chunks or rec_str_bad),
        ):
            if not should_probe or g_label in seen_gates:
                continue
            g_script = (repo / ".agents" / "scripts" / g_name) if (repo / ".agents" / "scripts" / g_name).is_file() else (_engine.SCRIPTS_DIR / g_name)
            if not g_script.is_file():
                continue
            proc = _engine.subprocess.run(
                [_engine.sys.executable, str(g_script)],
                cwd=repo,
                env=gate_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if proc.returncode != 0:
                out_lines = [
                    ln.strip()
                    for ln in ((proc.stdout or "") + "\n" + (proc.stderr or "")).splitlines()
                    if ln.strip() and not ln.strip().startswith("[KDOC-ADVISORY]")
                ][:20]
                if out_lines:
                    chunks.append(f"### Failing Zero-Token Static Gate: `{g_label}`\n" + "\n".join(out_lines)[:1200])
    return "\n\n".join(chunks)


def _match_diag_path_to_scope(repo: Path, raw_path: str, pool: list[str]) -> str:
    cand = raw_path.strip().replace("\\", "/")
    cand = _engine.re.sub(r"^file:///?", "", cand)
    try:
        norm = _engine._norm_rel(repo, cand)
        if not pool or norm in pool:
            return norm
    except _engine.ValidationError:
        norm = ""
    cand_trim = cand.lstrip("/")
    for rel in pool:
        if cand == rel or cand.endswith("/" + rel) or rel.endswith("/" + cand_trim):
            return rel
    return ""


def _extract_surgical_failure_excerpts(
    repo: Path,
    active_batch_files: list[str],
    diagnostics: str,
    vault: dict[str, str],
) -> list[str]:
    """Extract compact `±6`-line verbatim excerpts around failing `file:line` or JUnit `#method` targets."""
    if not diagnostics:
        return []
    line_hits: dict[str, list[int]] = {}
    loc_patterns = (
        r"((?:[A-Za-z]:[\\/])?[A-Za-z0-9_./\\-]+\.(?:kt|java|xml|swift|kts)):(\d+)",
        r"((?:[A-Za-z]:[\\/])?[A-Za-z0-9_./\\-]+\.(?:kt|java|xml|swift|kts))\s*\(\s*line\s*(\d+)",
    )
    for pat in loc_patterns:
        for m_path, m_line in _engine.re.findall(pat, diagnostics):
            matched_rel = _match_diag_path_to_scope(repo, m_path, active_batch_files)
            if matched_rel:
                line_hits.setdefault(matched_rel, []).append(max(1, int(m_line)))

    junit_methods = set(_engine.re.findall(r"\b[A-Za-z0-9_.]+#([A-Za-z_][A-Za-z0-9_]*)\b", diagnostics))
    if junit_methods:
        for rel in active_batch_files:
            fp = repo / rel
            if not fp.is_file() or not rel.endswith((".kt", ".java", ".swift")):
                continue
            lines_probe = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            for idx_ln, ln_txt in enumerate(lines_probe, 1):
                if any(f"fun {m_name}" in ln_txt or f"void {m_name}" in ln_txt or f"`{m_name}`" in ln_txt for m_name in junit_methods):
                    line_hits.setdefault(rel, []).append(idx_ln)

    excerpts: list[str] = []
    for rel in active_batch_files:
        if len(excerpts) >= 8:
            break
        fp = repo / rel
        if not fp.is_file():
            continue
        raw_txt = fp.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        sha = _engine._sha256_lf(raw_txt)
        redacted_lines = _engine._redact_inline_secrets(raw_txt, vault).splitlines()
        if not redacted_lines:
            continue
        total_l = len(redacted_lines)
        ext = Path(rel).suffix.lstrip(".") or "txt"
        hits = sorted(set(line_hits.get(rel) or []))
        if hits:
            windows: list[list[int]] = []
            for h_ln in hits:
                s_ln = max(1, min(h_ln, total_l) - 6)
                e_ln = min(total_l, max(1, h_ln) + 6)
                if windows and s_ln <= windows[-1][1] + 2:
                    windows[-1][1] = max(windows[-1][1], e_ln)
                else:
                    windows.append([s_ln, e_ln])
            for s_ln, e_ln in windows[:3]:
                snippet = "\n".join(redacted_lines[s_ln - 1 : e_ln]).rstrip()
                excerpts.append(
                    f"### SURGICAL EXCERPT: `{rel}` (lines {s_ln}-{e_ln}, `sha256={sha[:12]}`)\n```{ext}\n{snippet}\n```"
                )
        elif rel.endswith(".xml") and (rel in diagnostics or Path(rel).name in diagnostics or "check_strings" in diagnostics or "localization" in diagnostics):
            s_ln = max(1, total_l - 11)
            snippet = "\n".join(redacted_lines[s_ln - 1 : total_l]).rstrip()
            excerpts.append(
                f"### SURGICAL EXCERPT: `{rel}` (tail lines {s_ln}-{total_l}, `sha256={sha[:12]}`)\n```{ext}\n{snippet}\n```"
            )
    return excerpts
def _load_project_summary(repo: Path, vault: dict[str, str]) -> str:
    ctx_dir = repo / ".agents" / "project-context"
    parts: list[str] = []
    facts_f = ctx_dir / "project-facts.json"
    if facts_f.is_file():
        try:
            facts = _engine.read_json(facts_f)
            compact_facts = {k: facts.get(k) for k in ("architecture_family", "di_framework", "ui_toolkits", "modules", "min_sdk", "target_sdk", "locales") if k in facts}
            parts.append("Project Facts: " + _engine.json.dumps(compact_facts, ensure_ascii=False))
        except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
            pass
    notes_f = ctx_dir / "project-notes.md"
    if notes_f.is_file():
        try:
            from project_context import load_code_relevant_project_notes
            notes_res = load_code_relevant_project_notes(repo)
            if isinstance(notes_res, dict):
                notes_txt = str(notes_res.get("content") or notes_res.get("text") or notes_res.get("excerpt") or "")
            else:
                notes_txt = str(notes_res or "")
            if not notes_txt.strip():
                notes_txt = notes_f.read_text(encoding="utf-8", errors="replace")
        except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
            notes_txt = notes_f.read_text(encoding="utf-8", errors="replace")
        if notes_txt.strip():
            parts.append("Project Notes:\n" + _engine._redact_inline_secrets(notes_txt[:2500], vault))
    inst_f = ctx_dir / "developer-instructions.json"
    if inst_f.is_file():
        try:
            inst_raw = inst_f.read_text(encoding="utf-8", errors="replace")
            if inst_raw.strip():
                parts.append("Developer Instructions:\n" + _engine._redact_inline_secrets(inst_raw[:1500], vault))
        except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
            pass
    return "\n\n".join(parts)
def build_web_pack(
    repo: Path,
    *,
    task_id: str = "",
    prompt: str = "",
    kind: str = "",
    files: list[str] | None = None,
    add_files: list[str] | None = None,
    feature: str = "",
    symbol: str = "",
    retry: bool = False,
    retry_failure: bool = False,
    no_clipboard: bool = False,
    allow_conflict_pack: bool = False,
    include_dirty: bool = False,
    batch_size: int = _engine.DEFAULT_WEB_PACK_BATCH_SIZE,
    all_in_one: bool = False,
    batch_index: int = 1,
    total_batches_hint: int = 0,
    remaining_batches_override: list[list[str]] | None = None,
) -> dict[str, Any]:
    eff_retry = bool(retry or retry_failure)
    active_doc: dict[str, Any] | None = None
    try:
        from mutation_guard import active_plan
        active_doc = active_plan(repo, allow_missing=True)
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        active_doc = None

    eff_tid = str(task_id or (active_doc or {}).get("task_id") or "").strip()
    if eff_tid and active_doc is None:
        pf = _engine.task_dir(repo, eff_tid) / "plan.json"
        if pf.is_file():
            active_doc = _engine.read_json(pf)

    eff_prompt = str(prompt or (active_doc or {}).get("requested_outcome") or (active_doc or {}).get("outcome") or "").strip()
    if not eff_prompt:
        eff_prompt = "Analyze the scoped files, resolve the issue or implement the requested change, and include unit tests."
    eff_kind = _engine._infer_task_kind(eff_prompt, kind or str((active_doc or {}).get("task_kind") or ""))

    prev_pack: dict[str, Any] | None = None
    latest_ptr = _engine._web_relay_state_dir(repo) / "latest-pack.json"
    task_ptr = (_engine.task_dir(repo, eff_tid) / "latest-web-pack.json") if eff_tid and (_engine.state_root(repo) / "tasks" / eff_tid).is_dir() else None
    had_prior_task_pack = bool(task_ptr is not None and task_ptr.is_file())
    chosen_ptr = task_ptr if had_prior_task_pack else latest_ptr
    if (eff_retry or add_files) and chosen_ptr.is_file():
        try:
            ptr = _engine.read_json(chosen_ptr)
            prev_f = _engine._web_relay_state_dir(repo) / "packs" / f"{ptr.get('pack_id')}.json"
            if prev_f.is_file():
                prev_pack = _engine.read_json(prev_f)
        except (OSError, ValueError, _engine.ValidationError):
            prev_pack = None

    receipt_written_files: list[str] = []
    post_apply_hashes: dict[str, str] = {}
    if eff_tid:
        rec_path = _engine.state_root(repo) / "tasks" / eff_tid / "web-relay-receipt.json"
        if rec_path.is_file():
            try:
                rec_doc = _engine.read_json(rec_path)
                if isinstance(rec_doc, dict) and str(rec_doc.get("task_id") or "") == eff_tid:
                    receipt_written_files = [str(x) for x in (rec_doc.get("files_written") or []) if str(x).strip()]
                    if isinstance(rec_doc.get("post_apply_sha256"), dict):
                        post_apply_hashes = {
                            str(k): str(v)
                            for k, v in rec_doc["post_apply_sha256"].items()
                            if str(k).strip() and str(v).strip()
                        }
            except (OSError, ValueError, _engine.ValidationError):
                pass

    diagnostics = _engine._collect_active_diagnostics(repo, eff_tid, live_static_fallback=bool(retry_failure))
    if retry_failure and not diagnostics and not prompt.strip():
        raise _engine.ValidationError(
            "WEB_PACK_NO_ACTIVE_FAILURE: No failing local build, test, lint, or review diagnostics found to retry. "
            "Pass `--prompt \"<runtime issue>\"` if describing a manual runtime bug."
        )

    seed_files = list(files or [])
    retry_implicated_set: set[str] = set()
    if eff_retry and not seed_files and diagnostics:
        cand_pool = sorted(set((active_doc or {}).get("expected_files") or []) | set(receipt_written_files))
        for m_path in _engine.re.findall(r"((?:[A-Za-z]:[\\/])?[A-Za-z0-9_./\\-]+\.(?:kt|java|xml|swift|kts))", diagnostics):
            resolved_m = _match_diag_path_to_scope(repo, m_path, cand_pool)
            if resolved_m and (repo / resolved_m).is_file():
                if resolved_m not in seed_files:
                    seed_files.append(resolved_m)
                retry_implicated_set.add(resolved_m)
    if prev_pack and not files:
        for pf_k in (prev_pack.get("editable_files") or {}).keys():
            if pf_k not in seed_files:
                seed_files.append(pf_k)
    if eff_retry and not files:
        for rw_k in receipt_written_files:
            if rw_k not in seed_files and (repo / rw_k).is_file():
                seed_files.append(rw_k)
    explicit_added_set: set[str] = set()
    if add_files:
        for item in add_files:
            for sub in str(item).split(","):
                if sub.strip():
                    seed_files.append(sub.strip())
                    try:
                        explicit_added_set.add(_engine._norm_rel(repo, sub.strip()))
                    except _engine.ValidationError:
                        explicit_added_set.add(sub.strip().replace("\\", "/"))

    rejected_secrets: list[str] = []
    captured_dirty: list[str] = []
    scope_files = _engine._discover_scope_files(
        repo,
        explicit_files=seed_files,
        feature_query=feature,
        symbol_query=symbol,
        prompt_text=eff_prompt,
        active_plan_doc=active_doc,
        rejected_secret_files=rejected_secrets,
        include_git_dirty=include_dirty,
        captured_dirty_out=captured_dirty,
    )
    if not scope_files and rejected_secrets:
        tid_arg = f"--task-id {eff_tid} " if eff_tid else ""
        fallback_cmd = (
            f'python .agents/harness.py execution-mode set {tid_arg}'
            f'--choice normal-task --source conversation --proof-reference "<developer answer>"'
        )
        raise _engine.ValidationError(
            f"WEB_RELAY_SECRET_SCOPE_FALLBACK: All target file(s) ({', '.join(rejected_secrets)}) are protected by the "
            "Zero-Secret Gate and cannot be exported to an external AI web chat. "
            "TOOL_CALL_REQUIRED=ask_question — Ask the developer via `ask_question` with a simple English choice: "
            "'Run this task locally in Normal mode (keep project Web default intact)' -> run "
            f"`{fallback_cmd}` and execute locally."
        )
    if not scope_files:
        raise _engine.ValidationError(
            "WEB_PACK_EMPTY_SCOPE: Could not resolve any target source files automatically. "
            "Pass `--file <path>` (`--files <csv>`) or `--feature <name>` or mention a symbol/class name in `--prompt`."
        )

    if not allow_conflict_pack:
        try:
            from execution_mode import has_conflict_signals
            is_conf, conf_sig = has_conflict_signals(repo, plan=active_doc, candidate_files=scope_files)
        except Exception:
            is_conf, conf_sig = (eff_kind in {"CONFLICT", "FIX_CONFLICT", "MERGE"}), f"kind={eff_kind}"
        if eff_kind in {"CONFLICT", "FIX_CONFLICT", "MERGE"} or is_conf:
            raise _engine.ValidationError(
                f"WEB_RELAY_CONFLICT_LOCAL_RECOMMENDED ({conf_sig or eff_kind}): Git merge/rebase conflict resolution "
                "requires 3-way local Git context and runs locally in Antigravity (preserving any `web-project` default "
                "for subsequent tasks). Resolve locally via `task draft --kind CONFLICT`, or pass `--allow-conflict-pack` if intentional."
            )

    pack_id = f"wpack-{_engine.uuid.uuid4().hex[:12]}"
    repo_fp = _engine.repository_identity(repo)
    head_sha = _engine.git_text(repo, "rev-parse", "HEAD")
    vault: dict[str, str] = dict((prev_pack or {}).get("secret_vault") or {})
    binary_assets_meta: list[dict[str, Any]] = []
    text_scope_files: list[str] = []

    for rel in scope_files:
        fp = repo / rel
        if fp.is_file():
            raw_probe = fp.read_bytes()
            if _engine._is_binary_asset(rel, raw_probe):
                binary_assets_meta.append({
                    "path": rel,
                    "bytes": len(raw_probe),
                    "resource_ref": _engine._android_resource_ref_for_path(rel),
                })
                continue
        elif _engine._is_binary_asset(rel, None):
            binary_assets_meta.append({
                "path": rel,
                "bytes": 0,
                "resource_ref": _engine._android_resource_ref_for_path(rel),
            })
            continue
        text_scope_files.append(rel)

    if not text_scope_files and binary_assets_meta:
        refs = ", ".join(f"{b['path']} ({b['resource_ref']})" for b in binary_assets_meta[:8])
        raise _engine.ValidationError(
            f"WEB_PACK_BINARY_ONLY_SCOPE: Binary asset(s) ({refs}) stay local on disk and cannot be edited as text. "
            "Include the Kotlin/Java/XML source files that reference them in `--files`."
        )

    # Smart DAG batch sharding for massive refactors (`41–250` files), while keeping `1–40` file tasks in ONE single pack!
    eff_batch_size = max(5, int(batch_size or _engine.DEFAULT_WEB_PACK_BATCH_SIZE))
    pending_batches: list[list[str]] = []
    if remaining_batches_override is not None:
        active_batch_files = list(text_scope_files)
        pending_batches = [list(b) for b in remaining_batches_override if b]
        cur_batch_num = max(1, int(batch_index or 1))
        total_batches = max(cur_batch_num, int(total_batches_hint or (cur_batch_num + len(pending_batches))))
    elif not all_in_one and not eff_retry and len(text_scope_files) > eff_batch_size:
        dag_ordered = _engine._dag_sort_scope_files(text_scope_files)
        chunks_all = [dag_ordered[i : i + eff_batch_size] for i in range(0, len(dag_ordered), eff_batch_size)]
        active_batch_files = chunks_all[0]
        pending_batches = chunks_all[1:]
        cur_batch_num = 1
        total_batches = len(chunks_all)
    else:
        active_batch_files = list(text_scope_files)
        cur_batch_num = 1
        total_batches = 1

    editable_meta: dict[str, dict[str, Any]] = {}
    file_blocks_md: list[str] = []
    prev_editable = (prev_pack.get("editable_files") or {}) if prev_pack else {}

    for rel in active_batch_files:
        fp = repo / rel
        if fp.is_file():
            raw_b = fp.read_bytes()
            eol = _engine._detect_eol(raw_b)
            raw_txt = raw_b.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            sha = _engine._sha256_lf(raw_txt)
            redacted_txt = _engine._redact_inline_secrets(raw_txt, vault)
            editable_meta[rel] = {"exists": True, "sha256": sha, "eol": eol, "base_text": raw_txt}
            if retry_failure:
                # Zero-reupload mode: `known_chat_sha` is the exact file state already present in the external AI chat
                # (`post_apply_hashes[rel]` if modified/created by `web-apply`, else `prev_editable[rel].sha256`).
                # Emit full body ONLY if manually edited since then, unseen in chat, or explicitly added via `--add-files`!
                known_chat_sha = post_apply_hashes.get(rel) or str((prev_editable.get(rel) or {}).get("sha256") or "")
                has_chat_baseline = bool(prev_pack or post_apply_hashes)
                include_full = bool(
                    rel in explicit_added_set
                    or (has_chat_baseline and known_chat_sha != sha)
                    or (not has_chat_baseline and rel not in retry_implicated_set and not diagnostics)
                )
            else:
                include_full = bool(
                    not retry
                    or rel in retry_implicated_set
                    or (prev_pack and (prev_editable.get(rel) or {}).get("sha256") != sha)
                    or rel in explicit_added_set
                )
            if include_full:
                ext = Path(rel).suffix.lstrip(".") or "txt"
                file_blocks_md.append(f"### FILE: `{rel}` (`sha256={sha[:12]}`, `{len(raw_txt.splitlines())}` lines)\n```{ext}\n{redacted_txt.rstrip()}\n```")
        else:
            editable_meta[rel] = {"exists": False, "sha256": "", "eol": "lf", "base_text": ""}
            if not retry_failure or rel in explicit_added_set:
                file_blocks_md.append(f"### PLANNED NEW FILE: `{rel}` (does not exist yet)")

    neighbors = [] if eff_retry else _engine._extract_neighbor_signatures(repo, active_batch_files, vault)
    proj_summary = "" if eff_retry else _engine._load_project_summary(repo, vault)
    resource_inventory = "" if eff_retry else _engine._collect_module_resource_inventory(repo, active_batch_files)
    surgical_excerpts = _extract_surgical_failure_excerpts(repo, active_batch_files, diagnostics, vault) if retry_failure else []

    suggested_tid = eff_tid or _engine.re.sub(r"[^a-z0-9-]+", "-", eff_prompt.lower())[:28].strip("-") or f"web-task-{pack_id[-6:]}"
    if len(suggested_tid) < 3:
        suggested_tid = f"web-{pack_id[-6:]}"

    schema_example = {
        "schema": _engine.WEB_MERGE_SCHEMA,
        "pack_id": pack_id,
        "status": "READY",
        "plan_spec": {
            "task_id": suggested_tid,
            "kind": eff_kind,
            "outcome": eff_prompt[:180],
            "approach": "Concise 1-2 sentence summary of root cause & architectural solution",
            "risks": "Key regression/edge-case risks",
        },
        "operations": [
            {
                "action": "MODIFY",
                "path": active_batch_files[0],
                "hunks": [
                    {"search": "exact existing lines from FILE block", "replace": "updated lines", "replace_all": False}
                ],
            },
            {
                "action": "CREATE",
                "path": "path/to/NewFileOrTestOrVectorDrawable.kt",
                "content": "full file content without truncation placeholders",
            },
        ],
    }
    need_files_example = {
        "schema": _engine.WEB_MERGE_SCHEMA,
        "pack_id": pack_id,
        "status": "NEED_FILES",
        "need_files": ["relative/path/to/MissingFile.kt"],
        "reason": "Why full body of this file is required before editing",
    }

    batch_banner = (
        f" | **Batch**: `{cur_batch_num} of {total_batches}` (`{len(active_batch_files)}` files in this pack; "
        f"`{sum(len(b) for b in pending_batches)}` queued for subsequent batches)"
        if total_batches > 1
        else f" | **Files in Pack**: `{len(active_batch_files)}`"
    )

    if retry_failure:
        scope_short = ", ".join(f"`{p}`" for p in active_batch_files[:12])
        if len(active_batch_files) > 12:
            scope_short += f" (+{len(active_batch_files) - 12} more)"
        md_sections = [
            f"# Android Agent Harness — Web-Relay Context Pack — Failure-Fix Delta (`{pack_id}`)",
            "",
            "## 1. Repair Contract (Same External AI Chat — Zero Full-File Re-Upload)",
            f"- **Task ID**: `{suggested_tid}` | **Kind**: `{eff_kind}` | **New Pack ID**: `{pack_id}` | **Editable Scope (`{len(editable_meta)}`)**: {scope_short}",
            f"- **Original Goal**: {eff_prompt}",
            "- **Instructions**: Fix every compiler, lint, string-parity, or unit-test failure below against the code already in this chat. "
            f"End your reply with **one fenced ```json block** using `\"schema\": \"{_engine.WEB_MERGE_SCHEMA}\"`, `\"pack_id\": \"{pack_id}\"`, `\"status\": \"READY\"`, "
            "and minimal `\"operations\"` (`MODIFY` with verbatim `hunks` `{\"search\": \"...\", \"replace\": \"...\"}`, `CREATE`, or `\"status\": \"NEED_FILES\"` with `\"need_files\": [...]` if you need an unseen file). "
            "Include concise English KDoc (`/** ... */`) on any newly added public/internal contract and never emit truncation comments (`// ...`).",
        ]
        if diagnostics:
            md_sections.extend(["", "## 2. Active Local Build / Test / Gate Failures", diagnostics])
        if surgical_excerpts:
            md_sections.extend(["", "## 3. Surgical Code Excerpts Around Failing Locations (Verbatim Lines for `hunks`)", *surgical_excerpts])
        if file_blocks_md:
            md_sections.extend(["", "## 4. Newly Added or Locally Modified Files Since Last Apply", *file_blocks_md])
    else:
        md_sections = [
            f"# Android Agent Harness — Web-Relay Context Pack (`{pack_id}`)",
            "",
            "## 1. Mission & Output Contract (External AI Web-Relay)",
            f"- **Task Goal**: {eff_prompt}",
            f"- **Task Kind**: `{eff_kind}` | **Suggested Task ID**: `{suggested_tid}` | **Pack ID**: `{pack_id}`{batch_banner}",
            "- **Editing Freedom & Rules**:",
            "  1. Solve the task completely across all affected files in this pack: preserve Clean Architecture boundaries, write concise English KDoc (`/** ... */` documenting responsibility, `@param`, and `@return`) on every newly created class/interface and every newly added public/internal method on `Repository`, `UseCase`, `ViewModel`, `DataSource`/`ApiService`, or public `@Composable` screen/component, maintain bilingual EN/AR string parity (`values/strings.xml` + `values-ar/strings.xml`) when adding user-visible strings, include Room `Migration`s when changing `@Entity` schemas, and include JUnit tests (for `BUG` tasks, ensure the test FAILS before your production fix and PASSES after).",
            "  2. **Compact Lossless `hunks` (Essential for `10–100` File Tasks)**: For `MODIFY` operations, ALWAYS prefer minimal `hunks` (`search` / `replace` with 2-3 surrounding context lines copied verbatim, or set `\"replace_all\": true` for repeated symbol/import/package renames across a file) instead of rewriting whole files. **NEVER** emit lazy truncation comments (`// ... rest of code unchanged`, `// existing code`).",
            "  3. **Full Freedom to Create, Rename, Delete & Patch Neighbors**: You may freely `CREATE` new classes, unit tests, or Android `<vector>` XML drawables (`res/drawable/ic_*.xml`), `DELETE` or `RENAME` (`old_path` -> `path`) scoped files, and apply surgical `hunks` to `READ_ONLY_NEIGHBOR_SIGNATURES` when updating shared interfaces/imports. Never blindly overwrite an unseen file with full `content` — emit `NEED_FILES` if you need a missing file's full body first.",
            "  4. **UI Screenshots & Drawables**: If the developer attached a UI design image/screenshot in chat alongside this pack, match its layout hierarchy, spacing, colors, typography, and RTL support faithfully, reusing existing `R.drawable.*` / `R.font.*` IDs listed in Section 2 (or `CREATE` new `<vector>` XML drawables as needed).",
            "  5. **Large Multi-File Replies (`PARTIAL` Continuation Supported)**: If your JSON output for a very large pack approaches message length limits, do NOT truncate code — emit valid JSON for the first subset with `\"status\": \"PARTIAL\"` so the developer can apply it and ask `Continue remaining files` in this same chat using the same `pack_id`.",
            "  6. Preserve any `__HARNESS_REDACTED_SECRET_N__` token verbatim (real values are restored locally). End your response with **one fenced ```json block** (or a downloadable file named "
            f"`harness-merge-{pack_id}.json`).",
            "",
            "### Required Output JSON Schema (`READY` / `PARTIAL` vs `NEED_FILES`)",
            "```json",
            _engine.json.dumps(schema_example, indent=2, ensure_ascii=False),
            "```",
            "*(If you must inspect the full source of additional repo file(s) before coding, return instead:)*",
            "```json",
            _engine.json.dumps(need_files_example, indent=2, ensure_ascii=False),
            "```",
        ]
        sec2_parts = [p for p in (proj_summary, resource_inventory) if p]
        if binary_assets_meta:
            bin_lines = "\n".join(
                f"- `{b['path']}` (`{b['bytes']:,}` bytes on disk — reference as `{b['resource_ref']}`)"
                for b in binary_assets_meta
            )
            sec2_parts.append(f"Read-Only Binary Assets Present on Disk:\n{bin_lines}")
        if sec2_parts:
            md_sections.extend(["", "## 2. Repository Architecture, Resources & Developer Rules", "\n\n".join(sec2_parts)])
        if diagnostics:
            md_sections.extend(["", "## 3. Active Local Gate Failures / Handoff Diagnostics", diagnostics])
        if pending_batches:
            upcoming_preview = []
            for b_idx, b_files in enumerate(pending_batches, cur_batch_num + 1):
                sample_f = ", ".join(f"`{x}`" for x in b_files[:8])
                extra_f = f" (+{len(b_files) - 8} more)" if len(b_files) > 8 else ""
                upcoming_preview.append(f"- **Upcoming Batch {b_idx}/{total_batches} ({len(b_files)} files — packed automatically after this batch applies)**: {sample_f}{extra_f}")
            md_sections.extend([
                "",
                f"## 4A. Multi-Batch Refactor Schedule (Batch `{cur_batch_num}/{total_batches}` Active Now)",
                "Focus your `operations` in this reply on the `EDITABLE_FILES` in Section 5 below (keep shared public contracts compatible with the upcoming batches):",
                "\n".join(upcoming_preview),
            ])
        if neighbors:
            md_sections.append("\n## 4. Read-Only Neighbor AST Signatures (`READ_ONLY_NEIGHBOR_SIGNATURES` — Surgical `hunks` allowed; use `NEED_FILES` if full body needed)")
            for nb in neighbors:
                md_sections.append(f"### NEIGHBOR SIGNATURE: `{nb['path']}`\n```kotlin\n{nb['signatures']}\n```")
        if file_blocks_md:
            md_sections.append(f"\n## 5. Editable Scope Files (`EDITABLE_FILES` — `{len(editable_meta)}` files)")
            md_sections.extend(file_blocks_md)
        else:
            md_sections.append(f"\n## 5. Retry Delta Mode (`{len(editable_meta)}` files unchanged from prior pack in this chat)")

    bundle_text = "\n\n".join(md_sections).strip() + "\n"
    out_dir = _engine._default_outbox_dir()
    repo_slug = _engine.re.sub(r"[^A-Za-z0-9._-]+", "-", repo.name).strip("-") or "android-repo"
    bundle_file = out_dir / f"{repo_slug}-{pack_id}.md"
    bundle_file.write_text(bundle_text, encoding="utf-8")

    packs_dir = _engine._web_relay_state_dir(repo) / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    pack_record = {
        "schema_version": 1,
        "pack_id": pack_id,
        "created_at": _engine.utc_now(),
        "repo_fingerprint": repo_fp,
        "base_head": head_sha,
        "task_id": eff_tid,
        "suggested_task_id": suggested_tid,
        "kind": eff_kind,
        "prompt": eff_prompt,
        "retry": eff_retry,
        "retry_failure": bool(retry_failure),
        "bundle_file": str(bundle_file),
        "bundle_bytes": len(bundle_text.encode("utf-8")),
        "editable_files": editable_meta,
        "binary_assets": binary_assets_meta,
        "neighbor_files": [n["path"] for n in neighbors],
        "batch_index": cur_batch_num,
        "total_batches": total_batches,
        "batch_size": eff_batch_size,
        "pending_batches": pending_batches,
        "partial_batches_applied": 0,
        "secret_vault": vault,
        "applied": False,
    }
    _engine.atomic_write_json(packs_dir / f"{pack_id}.json", pack_record)
    ptr_payload = {"pack_id": pack_id, "task_id": eff_tid, "bundle_file": str(bundle_file), "created_at": pack_record["created_at"]}
    _engine.atomic_write_json(latest_ptr, ptr_payload)
    if eff_tid and (_engine.state_root(repo) / "tasks" / eff_tid).is_dir():
        _engine.atomic_write_json(_engine.task_dir(repo, eff_tid) / "latest-web-pack.json", ptr_payload)
    else:
        try:
            from execution_mode import record_pending_pack_link
            record_pending_pack_link(repo, pack_id)
        except (ImportError, OSError, ValueError, _engine.ValidationError):
            record_pending_pack_link = None

    # Mint fresh Graph-First discovery receipt & last-task-context so PreToolUse / draft recognize Web-Pack AST scope
    try:
        import time as _time
        from _graph_core import GraphEngine
        from discovery_receipt import create_discovery_receipt, current_graph_fingerprint, save_discovery_receipt
        existing_resolved = [p for p in (list(scope_files) + [n["path"] for n in neighbors]) if (repo / p).is_file()]
        if existing_resolved:
            ge_sync = GraphEngine(repo)
            ge_sync.sync(persist=True, trust_stat=True)
            g_fp = current_graph_fingerprint(repo)
            mods_found = sorted({
                (":" + p.split("/src/", 1)[0].replace("/", ":")) if "/src/" in p else ":"
                for p in existing_resolved
            })
            disc_rec = create_discovery_receipt(
                mode="TARGETED_GRAPH_CONTEXT",
                query_kind="batch_files",
                query_value=_engine.json.dumps(existing_resolved[:8], ensure_ascii=True),
                graph_fingerprint=g_fp,
                resolved_modules=mods_found,
                resolved_paths=existing_resolved,
                resolved_symbols=[],
            )
            save_discovery_receipt(repo, disc_rec)
            cache_dir = repo / ".agents" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            _engine.atomic_write_json(cache_dir / "last-task-context.json", {
                "context_id": disc_rec["id"],
                "file": existing_resolved[0],
                "module": mods_found[0] if mods_found else ":",
                "timestamp": _time.time(),
            })
    except (ImportError, OSError, ValueError, KeyError, TypeError, _engine.ValidationError):
        pass

    clip_info = {"copied": False, "mode": "skipped"} if no_clipboard else _engine._copy_to_clipboard(bundle_file, bundle_text)
    new_chat_recommended = not bool(eff_retry or add_files or cur_batch_num > 1 or had_prior_task_pack)
    web_chat_instruction = (
        "Open a NEW external AI chat, attach or paste the Context Pack (Ctrl+V), and send."
        if new_chat_recommended
        else "Stay in the SAME external AI chat, attach or paste the pack (Ctrl+V), and send (open a NEW chat only for a new task)."
    )
    return {
        "status": "OK",
        "pack_id": pack_id,
        "repo_fingerprint": repo_fp,
        "task_id": eff_tid or None,
        "suggested_task_id": suggested_tid,
        "kind": eff_kind,
        "retry_failure": bool(retry_failure),
        "surgical_excerpts_count": len(surgical_excerpts),
        "editable_files": list(editable_meta.keys()),
        "git_dirty_files_included": captured_dirty,
        "binary_assets": binary_assets_meta,
        "batch_index": cur_batch_num,
        "total_batches": total_batches,
        "queued_remaining_files": sum(len(b) for b in pending_batches),
        "neighbor_signatures_count": len(neighbors),
        "redacted_secrets_count": len(vault),
        "bundle_file": str(bundle_file),
        "bundle_bytes": len(bundle_text.encode("utf-8")),
        "clipboard": clip_info,
        "new_chat_recommended": new_chat_recommended,
        "web_chat_instruction": web_chat_instruction,
        "recommended_gemini_web_mode": "Task",
        "gemini_web_instruction": web_chat_instruction,
    }
