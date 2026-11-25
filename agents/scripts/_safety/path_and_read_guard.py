"""Extracted modular implementation slice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import engine as _engine


def _is_ide_artifact(resolved: Path) -> bool:
    try:
        from antigravity_runtime import _is_invalid_conversation_id, candidate_brain_roots
        for root in candidate_brain_roots():
            if resolved.is_relative_to(root):
                parts = resolved.relative_to(root).parts
                if len(parts) >= 2 and parts[-1] in {"implementation_plan.md", "task.md", "walkthrough.md"}:
                    conv_id = "/".join(parts[:-1])
                    return not _is_invalid_conversation_id(conv_id)
        return False
    except Exception:
        return False
def _is_external_user_doc(raw: Path, resolved: Path) -> bool:
    """Allow standalone documentation/notes files outside the repository when explicitly targeted by absolute path."""
    if not raw.is_absolute():
        return False
    try:
        if raw.is_symlink() or resolved.is_symlink():
            return False
    except OSError:
        return False
    if resolved.suffix.lower() not in {".md", ".txt", ".rst", ".adoc"}:
        return False
    if resolved.name.lower() in _engine.IMMUTABLE_ADAPTER_FILES or resolved.name.lower() in {
        "cmakelists.txt", "baseline-prof.txt", "startup-prof.txt",
        "requirements.txt", "constraints.txt", "runtime.txt", "version.txt",
    }:
        return False
    if any(part.startswith(".") for part in raw.parts) or any(part.startswith(".") for part in resolved.parts):
        return False
    resolved_str = str(resolved).replace("\\", "/").lower()
    if any(
        seg in resolved_str
        for seg in (
            "/appdata/roaming/",
            "/appdata/local/programs/",
            "/appdata/local/microsoft/",
            "/programdata/",
            "/windows/",
            "/system32/",
            "/program files/",
            "/program files (x86)/",
            "/library/",
        )
    ):
        return False
    try:
        for parent in (resolved.parent, *resolved.parents):
            if (
                (parent / ".git").exists()
                or (parent / ".harness-setup").exists()
                or (parent / ".agents" / "harness.py").exists()
                or (parent / ".agents" / "VERSION").exists()
                or (parent / ".agents" / "state").exists()
            ):
                return False
    except OSError:
        return False
    return True
def _safe_target(raw_target: str, repo: Path | None = None) -> tuple[bool, str, bool]:
    root = (repo or _engine.REPO).resolve()
    if not raw_target.strip():
        return False, "Mutating file tool did not expose a target path; refusing an unscoped write.", False
    raw = Path(raw_target).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    user_harness = (Path.home() / ".android-harness").resolve()
    if resolved == user_harness or user_harness in resolved.parents:
        return False, "User-level Android Harness configuration and model routes are developer-owned and immutable to model file tools.", False
    # Check native evidence BEFORE the generic temporary JSON exception: test
    # and custom host roots may themselves live under the temporary directory.
    from antigravity_runtime import candidate_runtime_roots
    if any(resolved == native or native in resolved.parents for native in candidate_runtime_roots()):
        if _engine._is_ide_artifact(resolved):
            return True, str(resolved), True
        return False, "Antigravity native transcripts, metadata and runtime evidence are immutable to agent file tools.", False
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError:
        temp_dir = Path(_engine.tempfile.gettempdir()).resolve()
        if (resolved == temp_dir or temp_dir in resolved.parents) and resolved.suffix.lower() == ".json":
            return True, str(resolved), True
        if _engine._is_ide_artifact(resolved) or _engine._is_external_user_doc(raw, resolved):
            return True, str(resolved), True
        try:
            from companion_workspaces import match_companion_target
            ok_comp, comp_root, comp_detail = match_companion_target(root, raw)
            if comp_root is not None:
                if ok_comp:
                    return True, comp_detail, True
                return False, comp_detail, False
        except (ImportError, OSError, ValueError):
            pass
        return False, f"Target path '{raw_target}' is outside the repository boundary.", False
    rel_lower = relative.lower()
    if (
        rel_lower == ".agents/project-context/project-notes.md"
        or rel_lower == ".agents/project-context/developer-instructions.json"
        or rel_lower == ".agents/project-context/architecture-policy.json"
        or rel_lower == ".agents/project-context/companion-workspaces.json"
        or rel_lower == ".agents/project-context/quirks.json"
        or rel_lower == "agents/project-context/quirks.json"
        or rel_lower.startswith(".agents/project-context/legacy-overrides/")
    ):
        return False, "Project context notes, instructions, and architecture policies are developer-owned and immutable to model file tools to prevent context poisoning.", False
    if (
        rel_lower.startswith(".agents/state/web-relay/inbox/")
        and len(Path(relative).parts) == 5
        and resolved.suffix.lower() in {".json", ".md", ".txt", ".patch"}
        and not resolved.is_symlink()
        and not resolved.parent.is_symlink()
    ):
        return True, str(resolved), True
    if (
        rel_lower.startswith(".agents/cache/")
        and len(Path(relative).parts) == 3
        and _engine.re.fullmatch(r"tmp-[a-z0-9_.-]+\.json", Path(relative).name.lower())
        and not resolved.is_symlink()
        and not resolved.parent.is_symlink()
    ):
        return True, str(resolved), True
    if any(rel_lower == r.lower() or rel_lower.startswith(r.lower() + "/") for r in _engine.PROTECTED_ROOTS):
        return False, "Harness engine, state, and ownership evidence are immutable to agent file tools.", False
    is_kit_dev = (root / "harness_cli.py").is_file() and (root / "scripts_dev").is_dir()
    if not is_kit_dev:
        rel_name = Path(relative).name.lower()
        if (
            rel_name in _engine.IMMUTABLE_ADAPTER_FILES
            or rel_lower.startswith(".github/workflows/")
            or rel_name in {"gradlew", "gradlew.bat"}
            or rel_lower.startswith("gradle/wrapper/")
        ):
            return False, "Root harness instructions, agent adapters, CI workflows, and Gradle wrappers are developer-owned and immutable during task execution.", False
    if _engine.EPHEMERAL_GENERATED_RE.search(relative):
        return False, f"Cannot mutate generated build output '{relative}'. Generated code is diagnostic evidence only; edit the source entity/DAO/contract or generator configuration instead.", False
    return True, relative, False
def _normalize_crlf_for_edit(repo: Path, targets: list[str], args: dict, *, env: dict[str, str] | None = None) -> None:
    """Normalize CRLF to LF on authorized edit targets for legacy (<1.5.1) Antigravity CLI hosts.

    Antigravity CLI 1.5.1+ (and 1.5.10+ for append) natively handles CRLF targets without
    requiring PreToolUse disk normalization. When CLI >= 1.5.1 (or App >= 2.33.0 / IDE >= 2.7.1)
    is declared—or `AGY_WIN_CRLF_EDIT_NORMALIZATION` is disabled—files stay untouched on disk.
    """
    target_chunks: list[str] = []
    for key in ("Target", "target", "TargetContent", "targetContent", "old_string", "OldString", "old_str", "OldStr"):
        val = args.get(key)
        if isinstance(val, str) and val:
            target_chunks.append(val)
    for key in ("ReplacementChunks", "replacementChunks", "Replacements", "replacements", "chunks", "edits"):
        items = args.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    for subkey in ("Target", "target", "TargetContent", "targetContent", "OldStr", "old_str", "old_string", "OldString"):
                        subval = item.get(subkey)
                        if isinstance(subval, str) and subval:
                            target_chunks.append(subval)
    multiline_lf_targets = [
        chunk.encode("utf-8", errors="surrogateescape")
        for chunk in target_chunks
        if "\n" in chunk and "\r\n" not in chunk
    ]
    if not multiline_lf_targets:
        return
    from antigravity_runtime import should_normalize_crlf_for_edit
    if not should_normalize_crlf_for_edit(repo=repo, env=env):
        return
    from _vnext_common import atomic_write_bytes
    for t in targets:
        if not t:
            continue
        try:
            cand = Path(t) if Path(t).is_absolute() else (repo / t)
            if not cand.is_file() or cand.is_symlink():
                continue
            data = cand.read_bytes()
            if b"\r\n" in data and b"\x00" not in data:
                lf_data = data.replace(b"\r\n", b"\n")
                if any(chunk in lf_data for chunk in multiline_lf_targets):
                    atomic_write_bytes(cand, lf_data)
        except OSError:
            pass
def check_write_safety(repo: Path | str, target: str, tool_name: str = "write_to_file") -> dict[str, Any]:
    safe, detail, is_temp = _engine._safe_target(str(target), repo=Path(repo))
    if not safe:
        return {"decision": "DENY", "reason": detail, "reason_code": "PROTECTED_PATH"}
    return {"decision": "ALLOW", "reason": detail, "reason_code": "TEMP_WRITE_ALLOWED" if is_temp else "PATH_ALLOWED"}
def _is_within_repo(repo: Path, raw: str) -> bool:
    clean = str(raw or "").strip().replace("\\", "/")
    if not clean or clean in {".", "./"}:
        return True
    try:
        root = repo.resolve()
        path = Path(clean)
        resolved = (path if path.is_absolute() else root / path).resolve()
        return resolved == root or resolved.is_relative_to(root)
    except (OSError, ValueError, RuntimeError):
        return False
def _get_active_task_scope(repo: Path, plan: dict) -> tuple[set[str], set[str]]:
    from discovery_receipt import source_search_root
    roots: set[str] = set()
    files: set[str] = set()

    from change_decision import reserved_files
    for ef in set(plan.get("expected_files") or []) | reserved_files(plan):
        norm = str(ef).replace("\\", "/").strip().lstrip("/")
        if not norm:
            continue
        files.add(norm.lower())
        parent = source_search_root(norm).lower()
        if parent:
            roots.add(parent)

    prov = plan.get("discovery_provenance") or {}
    for r in prov.get("allowed_search_roots") or []:
        norm_r = str(r).replace("\\", "/").strip().lstrip("/").lower().rstrip("/")
        if norm_r:
            roots.add(norm_r)
    for p in prov.get("resolved_paths") or []:
        norm_p = str(p).replace("\\", "/").strip().lstrip("/").lower()
        if norm_p:
            files.add(norm_p)
            parent = source_search_root(norm_p).lower()
            if parent:
                roots.add(parent)

    try:
        from discovery_receipt import load_latest_discovery_receipt, load_discovery_receipt, check_discovery_freshness
        rec_id = str(prov.get("discovery_id") or "")
        receipts_to_check = []
        if rec_id:
            r = load_discovery_receipt(repo, rec_id)
            if r:
                receipts_to_check.append(r)
        latest = load_latest_discovery_receipt(repo)
        if latest and latest not in receipts_to_check:
            receipts_to_check.append(latest)

        for rec in receipts_to_check:
            if not check_discovery_freshness(repo, rec)[0]:
                continue
            for r in rec.get("allowed_search_roots") or []:
                norm_r = str(r).replace("\\", "/").strip().lstrip("/").lower().rstrip("/")
                if norm_r:
                    roots.add(norm_r)
            for p in rec.get("resolved_paths") or []:
                norm_p = str(p).replace("\\", "/").strip().lstrip("/").lower()
                if norm_p:
                    files.add(norm_p)
                    parent = source_search_root(norm_p).lower()
                    if parent:
                        roots.add(parent)
            for er in rec.get("expanded_roots") or []:
                norm_er = str(er).replace("\\", "/").strip().lstrip("/").lower().rstrip("/")
                if norm_er:
                    roots.add(norm_er)
    except (OSError, ValueError, ImportError, _engine.ValidationError):
        pass

    arch = plan.get("architecture_contract") or {}
    arch_scope = str(arch.get("target_scope") or "").replace("\\", "/").strip().lstrip("/")
    if arch_scope:
        files.add(arch_scope.lower())
        parent = source_search_root(arch_scope).lower()
        if parent:
            roots.add(parent)

    return roots, files
def _is_path_in_active_scope(repo: Path, target_path: str, plan: dict) -> bool:
    target_str = str(target_path or "").replace("\\", "/").strip().rstrip("/")
    if not target_str or target_str in {".", "./"}:
        return False
    from discovery_receipt import relative_search_target
    rel = relative_search_target(repo, target_str)
    if rel is None:
        return False

    try:
        from discovery_router import _is_exact_non_architectural_file
        if _is_exact_non_architectural_file(target_str):
            return True
    except (OSError, ValueError, ImportError, _engine.ValidationError):
        pass

    roots, files = _engine._get_active_task_scope(repo, plan)
    if not roots and not files:
        try:
            from discovery_receipt import load_latest_discovery_receipt, is_path_in_discovery_scope, check_discovery_freshness
            rec = load_latest_discovery_receipt(repo)
            if rec and check_discovery_freshness(repo, rec)[0] and is_path_in_discovery_scope(repo, target_str, rec):
                return True
        except (OSError, ValueError, ImportError, _engine.ValidationError):
            pass
        return False

    if rel in files:
        return True
    for r in roots:
        if not r:
            continue
        if rel == r or rel.startswith(r + "/"):
            return True

    return False
def _enforce_lead_anti_reread(conversation: str, name: str, args: dict) -> bool:
    """Return True if a denial was emitted due to post-subagent or post-reviewer anti-reread cap."""
    if not conversation:
        return False
    try:
        from delegation_policy import check_and_record_lead_post_subagent_read, check_post_reviewer_reread_guard
        ok_pr, reason_pr, code_pr = check_post_reviewer_reread_guard(_engine.REPO, conversation, tool_name=name, args=args)
        if not ok_pr:
            _engine.emit("deny", reason_pr, tool=name, reason_code=code_pr)
            return True
        ok_ps, reason_ps, code_ps = check_and_record_lead_post_subagent_read(_engine.REPO, conversation, tool_name=name, args=args)
        if not ok_ps:
            _engine.emit("deny", reason_ps, tool=name, reason_code=code_ps)
            return True
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        return False
    return False
def _handle_list_dir(name: str, args: dict, *, conversation: str = "", is_utility_subagent: bool = False) -> None:
    plan: dict = {}
    try:
        plan = _engine.active_plan(_engine.REPO)
        status = str(plan.get("status") or "")
    except Exception:
        status = ""

    dir_target = str(args.get("DirectoryPath") or args.get("directoryPath") or args.get("path") or ".")
    if not _engine._is_within_repo(_engine.REPO, dir_target):
        try:
            from companion_workspaces import match_companion_target
            ok_comp, comp_root, comp_detail = match_companion_target(_engine.REPO, dir_target)
            if comp_root is not None:
                if ok_comp:
                    _engine.emit("allow", f"Directory listing permitted inside authorized companion workspace '{comp_root.name}'.", tool=name, reason_code="COMPANION_WORKSPACE_ALLOWED")
                    return
                _engine.emit("deny", comp_detail, tool=name, reason_code="PROTECTED_PATH")
                return
        except (ImportError, OSError, ValueError):
            pass
        _engine.emit("deny", "Directory target is outside the repository root.", tool=name, reason_code="PROTECTED_PATH")
        return

    if is_utility_subagent:
        _engine.emit("allow", "Bounded directory listing permitted inside isolated utility subagent.", tool=name, reason_code="LIST_DIR_ALLOWED")
        return

    if status in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"):
        if _engine._enforce_lead_anti_reread(conversation, name, args):
            return
        _engine.emit("allow", "Directory listing is allowed during active task lifecycle.", tool=name, reason_code="LIST_DIR_ALLOWED")
        return

    try:
        from discovery_receipt import load_latest_discovery_receipt, check_discovery_freshness
        receipt = load_latest_discovery_receipt(_engine.REPO)
        if receipt:
            fresh, _ = check_discovery_freshness(_engine.REPO, receipt)
            if fresh:
                if _engine._enforce_lead_anti_reread(conversation, name, args):
                    return
                _engine.emit("allow", "Directory listing is allowed after initial discovery anchor.", tool=name, reason_code="LIST_DIR_ALLOWED")
                return
    except Exception:
        receipt = None

    rel = dir_target.replace("\\", "/").strip().rstrip("/")
    try:
        p = Path(dir_target)
        if p.is_absolute():
            rel = p.resolve().relative_to(_engine.REPO.resolve()).as_posix().lower()
        else:
            rel = _engine.re.sub(r"^(?:\./)+", "", rel).lstrip("/").lower()
    except Exception:
        rel = _engine.re.sub(r"^(?:\./)+", "", rel).lstrip("/").lower()

    parts = [part for part in rel.split("/") if part]

    consecutive_list_dirs = 0
    try:
        audit_file = _engine._audit_path()
        if audit_file.exists():
            with audit_file.open("rb") as handle:
                size = audit_file.stat().st_size
                handle.seek(max(0, size - 16384))
                if size > 16384:
                    handle.readline()
                lines = handle.read().decode("utf-8", errors="replace").splitlines()
            records = [_engine.json.loads(line) for line in lines if line.strip()]
            for rec in reversed(records[-10:]):
                t = rec.get("tool", "")
                if t == "list_dir":
                    consecutive_list_dirs += 1
                elif t in ("run_command", "write_to_file", "replace_file_content"):
                    break
    except Exception:
        consecutive_list_dirs = 0

    if len(parts) >= 2 or consecutive_list_dirs >= 2:
        _engine.emit(
            "deny",
            "DISCOVERY_ANCHOR_REQUIRED: Directory traversal cascade detected before architectural discovery. "
            "Anchor discovery with 'python .agents/harness.py task-context --file <path> --json' "
            "or 'python .agents/harness.py graph --feature <name> --json'.",
            tool=name,
            reason_code="DISCOVERY_ANCHOR_REQUIRED",
        )
        return

    if _engine._enforce_lead_anti_reread(conversation, name, args):
        return
    _engine.emit("allow", "Minimal repository orientation directory listing permitted.", tool=name, reason_code="LIST_DIR_ALLOWED")
def _handle_search(name: str, args: dict, *, conversation: str = "", is_utility_subagent: bool = False) -> None:
    plan: dict = {}
    try:
        plan = _engine.active_plan(_engine.REPO)
        status = str(plan.get("status") or "")
    except Exception:
        status = ""

    target = ""
    query = ""
    if name == "grep_search":
        target = str(args.get("SearchPath") or args.get("searchPath") or "")
        query = str(args.get("Query") or args.get("query") or "")
    elif name == "find_by_name":
        target = str(args.get("SearchDirectory") or args.get("searchDirectory") or "")
        query = str(args.get("Pattern") or args.get("pattern") or "")

    if target and not _engine._is_within_repo(_engine.REPO, target):
        try:
            from companion_workspaces import match_companion_target
            ok_comp, comp_root, comp_detail = match_companion_target(_engine.REPO, target)
            if comp_root is not None:
                if ok_comp:
                    _engine.emit("allow", f"Search permitted inside authorized companion workspace '{comp_root.name}'.", tool=name, reason_code="COMPANION_WORKSPACE_ALLOWED")
                    return
                _engine.emit("deny", comp_detail, tool=name, reason_code="PROTECTED_PATH")
                return
        except (ImportError, OSError, ValueError):
            pass
        _engine.emit("deny", "Search target is outside the repository root.", tool=name, reason_code="PROTECTED_PATH")
        return

    if is_utility_subagent:
        _engine.emit("allow", "Bounded search permitted inside isolated utility subagent.", tool=name, reason_code="SEARCH_ALLOWED")
        return

    if status == "VERIFYING":
        if _engine._enforce_lead_anti_reread(conversation, name, args):
            return
        _engine.emit("allow", "Search is allowed during verification.", tool=name, reason_code="VERIFIER_SEARCH_ALLOWED")
        return

    if status in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED", "IMPLEMENTING", "READY_FOR_DELIVERY"):
        if _engine._enforce_lead_anti_reread(conversation, name, args):
            return
        _engine.emit("allow", "Search is allowed during active task lifecycle.", tool=name, reason_code="SEARCH_ALLOWED")
        return

    # In Discovery Phase: Check if a fresh discovery receipt exists
    receipt = None
    try:
        from discovery_receipt import load_latest_discovery_receipt, check_discovery_freshness
        receipt = load_latest_discovery_receipt(_engine.REPO)
    except Exception:
        receipt = None

    if receipt:
        fresh, _ = check_discovery_freshness(_engine.REPO, receipt)
        if fresh:
            if _engine._enforce_lead_anti_reread(conversation, name, args):
                return
            _engine.emit("allow", "Search is allowed after initial discovery anchor.", tool=name, reason_code="SEARCH_ALLOWED")
            return

    # 3. No discovery receipt yet: Check exact file exceptions (D0)
    try:
        from discovery_router import _is_exact_non_architectural_file
        if target and _is_exact_non_architectural_file(target):
            if _engine._enforce_lead_anti_reread(conversation, name, args):
                return
            _engine.emit("allow", "Exact non-architectural file search allowed under D0.", tool=name, reason_code="SEARCH_ALLOWED")
            return
    except (OSError, ValueError, ImportError, _engine.ValidationError):
        pass

    if name == "grep_search" and target:
        try:
            cand_file = Path(target) if Path(target).is_absolute() else (_engine.REPO / target)
            if cand_file.is_file() and not _engine._installed_engine_target(target, recursive=False):
                if _engine._enforce_lead_anti_reread(conversation, name, args):
                    return
                _engine.emit("allow", "Single-file grep_search allowed on exact existing source file under D0.", tool=name, reason_code="SEARCH_ALLOWED")
                return
        except OSError:
            pass

    # Deny initial code search without discovery anchor
    clean_q = query.strip()
    is_symbol_q = bool(_engine.re.match(r"^[A-Z][a-zA-Z0-9_]+$", clean_q))
    target_clean = target.replace("\\", "/").strip().lower()
    feature_match = _engine.re.search(r"\b(?:feature|features|flow)/([a-zA-Z0-9_-]+)", target_clean)
    if not feature_match:
        feature_match = _engine.re.search(r"([a-zA-Z0-9_-]+)(?:ViewModel|Screen|Fragment|Repository|Service)", clean_q)

    if is_symbol_q:
        anchor_cmd = f"python .agents/harness.py task-context --symbol {clean_q} --json"
    elif feature_match:
        feat = feature_match.group(1).lower()
        anchor_cmd = f"python .agents/harness.py graph --feature {feat} --json"
    else:
        anchor_cmd = "python .agents/harness.py graph --feature <name> --json or python .agents/harness.py task-context --file <path> --json"

    _engine.emit(
        "deny",
        f"DISCOVERY_ANCHOR_REQUIRED: Search cannot be the initial discovery mechanism for code tasks. "
        f"Anchor discovery first with '{anchor_cmd}'.",
        tool=name,
        reason_code="DISCOVERY_ANCHOR_REQUIRED",
    )
def _conversation_started_at(payload: dict) -> float | None:
    """First time this hook saw the calling conversation; None when the host sends no identity."""
    conversation = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()
    if not conversation:
        return None
    try:
        import time
        from _vnext_common import atomic_write_json
        from evidence_store import StateLock
        path = _engine._audit_path().with_name("hook-conversations.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with StateLock(path.parent / ".hook-conversations-lock"):
            try:
                seen = _engine.json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(seen, dict):
                    seen = {}
            except (OSError, ValueError):
                seen = {}
            if conversation in seen:
                return float(seen[conversation])
            seen[conversation] = time.time()
            newest = sorted(seen.items(), key=lambda item: float(item[1]))[-_engine.CONVERSATION_LIMIT:]
            atomic_write_json(path, dict(newest))
            return float(seen[conversation])
    except Exception:
        return None
def _flag_out_of_scope_read(name: str, args: dict) -> None:
    """Audit a code read outside the task or discovery scope. Reads are never blocked."""
    try:
        target = str(args.get("AbsolutePath") or args.get("absolutePath") or _engine._target(args) or "").replace("\\", "/")
        if not target.lower().endswith(_engine.CODE_READ_SUFFIXES):
            return
        path = Path(target)
        rel = (
            path.resolve().relative_to(_engine.REPO.resolve()).as_posix()
            if path.is_absolute()
            else _engine.re.sub(r"^(?:\./)+", "", target).lstrip("/")
        )
        if rel.startswith(".agents/"):
            return
        try:
            plan = _engine.active_plan(_engine.REPO)
        except Exception:
            plan = {}
        if plan.get("status") in ("IMPLEMENTING", "VERIFYING", "READY_FOR_DELIVERY"):
            in_scope = _engine._is_path_in_active_scope(_engine.REPO, rel, plan)
        else:
            from discovery_receipt import check_discovery_freshness, is_path_in_discovery_scope, load_latest_discovery_receipt
            receipt = load_latest_discovery_receipt(_engine.REPO)
            if not receipt or not check_discovery_freshness(_engine.REPO, receipt)[0]:
                return
            in_scope = is_path_in_discovery_scope(_engine.REPO, rel, receipt)
        if not in_scope:
            _engine._audit("allow", f"READ_OUTSIDE_SCOPE: {rel}", name, "", reason_code="READ_OUTSIDE_SCOPE", task_id=str(plan.get("task_id") or ""))
    except Exception:
        return
def _installed_engine_target(raw: str, *, recursive: bool = False) -> bool:
    """Managed implementation only; rules, plans, evidence and application source remain readable."""
    try:
        path = Path(str(raw).strip().replace("\\", "/"))
        path = path if path.is_absolute() else _engine.REPO / path
        # Check both lexical and canonical paths: a symlink cannot hide managed
        # implementation, or expose it through an application-looking alias.
        candidates = (Path(_engine.os.path.abspath(path)), path.resolve())
        for candidate in candidates:
            try:
                relative = candidate.relative_to((_engine.REPO / ".agents").resolve())
            except ValueError:
                continue
            if not relative.parts:
                return recursive
            first = relative.parts[0].lower()
            if first in {"scripts", "mcp"} or relative.as_posix().lower() == "harness.py":
                return True
            if recursive and any(mark in first for mark in "*?["):
                return True
        return False
    except (ValueError, OSError):
        return False
def _is_raw_graph_cache_read_target(raw_target: str) -> bool:
    norm = str(raw_target or "").strip().strip('"').strip("'").replace("\\", "/").lower()
    if not norm:
        return False
    return any(
        norm.endswith(suffix)
        for suffix in (
            "/.agents/cache/project_graph.json",
            ".agents/cache/project_graph.json",
            "/agents/cache/project_graph.json",
            "agents/cache/project_graph.json",
            "/.agents/cache/type_index.json",
            ".agents/cache/type_index.json",
            "/.agents/cache/graph-cache.json",
            ".agents/cache/graph-cache.json",
        )
    )
def _is_native_transcript_read_target(raw_target: str) -> bool:
    norm = str(raw_target or "").strip().replace("\\", "/")
    if not norm:
        return False
    low = norm.lower()
    base_name = low.rsplit("/", 1)[-1]
    if base_name in {"transcript.jsonl", "transcript_full.jsonl"} or "/.system_generated/logs/" in low:
        try:
            raw_p = Path(raw_target).expanduser()
            resolved = raw_p.resolve() if raw_p.is_absolute() else (_engine.REPO / raw_p).resolve()
            if _engine._is_ide_artifact(resolved):
                return False
            from antigravity_runtime import candidate_runtime_roots
            if any(resolved == rt or rt in resolved.parents for rt in candidate_runtime_roots()):
                return True
        except OSError:
            pass
        if "/.system_generated/logs/" in low and base_name.endswith(".jsonl"):
            return True
    return False
def _is_background_task_log_target(raw_target: str) -> bool:
    norm = str(raw_target or "").strip().replace("\\", "/")
    if not norm or not norm.lower().endswith(".log"):
        return False
    low = norm.lower()
    if "/.system_generated/tasks/" in low or low.startswith(".system_generated/tasks/"):
        return True
    if _engine.re.search(r"(?:^|/)tasks/task-[0-9a-z_-]+\.log$", low):
        try:
            resolved = (Path(raw_target).expanduser().resolve() if Path(raw_target).expanduser().is_absolute() else (_engine.REPO / raw_target).resolve())
            from antigravity_runtime import candidate_runtime_roots
            if any(resolved == rt or rt in resolved.parents for rt in candidate_runtime_roots()):
                return True
        except OSError:
            return False
    return False
def _deny_engine_read(tool: str, command: str = "") -> None:
    _engine.emit("deny", "HARNESS_IMPLEMENTATION_BOUNDARY: use documented commands and their diagnostics first. "
         "For an unexpected command failure, contract violation, Doctor issue or explicit developer request, "
         "use python .agents/harness.py doctor --inspect-file scripts/<exact-file>.py "
         "--inspection-reason <reason> --reference <concrete-output-or-request> "
         "--inspect-start-line <line> --inspect-lines <1-200>. "
         "Inspect only the relevant excerpt; do not browse dependencies recursively or patch the installed engine.",
         tool=tool, command=command, reason_code="HARNESS_IMPLEMENTATION_BOUNDARY")
def _is_large_step_output_paginated_read(raw_target: str, args: dict) -> bool:
    norm = str(raw_target or "").strip().replace("\\", "/")
    if not norm:
        return False
    low = norm.lower()
    if not (_engine.re.search(r"(?:^|/)\.system_generated/steps/\d+/output\.txt$", low)):
        return False
    raw_offset = args.get("ByteOffset")
    if raw_offset is None:
        raw_offset = args.get("byteOffset")
    if raw_offset is None:
        raw_offset = args.get("byte_offset")
    try:
        offset_val = int(raw_offset or 0)
    except (TypeError, ValueError):
        offset_val = 0
    if offset_val <= 0:
        return False
    try:
        cand = Path(raw_target).expanduser()
        resolved = cand.resolve() if cand.is_absolute() else (_engine.REPO / cand).resolve()
        if resolved.is_file():
            return resolved.stat().st_size > 24576
    except OSError:
        return offset_val >= 24576
    return offset_val >= 24576


def _is_large_build_artifact_paginated_read(raw_target: str, args: dict) -> bool:
    """True when `read_file`/`view_file` paginates (`ByteOffset > 0`) a `> 48 KB` file inside repository `build/` directories."""
    norm = str(raw_target or "").strip().strip('"').strip("'").replace("\\", "/")
    if not norm:
        return False
    raw_offset = args.get("ByteOffset")
    if raw_offset is None:
        raw_offset = args.get("byteOffset")
    if raw_offset is None:
        raw_offset = args.get("byte_offset")
    try:
        offset_val = int(raw_offset or 0)
    except (TypeError, ValueError):
        offset_val = 0
    if offset_val <= 0:
        return False
    try:
        cand = Path(norm).expanduser()
        resolved = cand.resolve() if cand.is_absolute() else (_engine.REPO / cand).resolve()
        rel = resolved.relative_to(_engine.REPO.resolve()).as_posix().lower()
    except (OSError, ValueError):
        return False
    if not (rel.startswith("build/") or "/build/" in f"/{rel}"):
        return False
    try:
        if resolved.is_file():
            return resolved.stat().st_size > 49152
    except OSError:
        return offset_val >= 46080
    return offset_val >= 46080


_IMAGE_READ_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_JPEG_READ_SUFFIXES = (".jpg", ".jpeg")


def _normalize_image_read_target(raw_target: str) -> str:
    """Normalize local paths and `file://` URIs (including MCP-offloaded `media_*.webp` paths #1828)."""
    norm = str(raw_target or "").strip().strip('"').strip("'")
    if not norm:
        return ""
    if norm.lower().startswith("file://"):
        from urllib.parse import unquote, urlparse
        parsed = urlparse(norm)
        path_part = unquote(parsed.path or "")
        if len(path_part) >= 3 and path_part[0] == "/" and path_part[2] == ":" and path_part[1].isalpha():
            path_part = path_part[1:]
        return path_part
    return norm.split("?", 1)[0].split("#", 1)[0]


def _check_jpeg_integrity(raw_target: str) -> tuple[bool, str]:
    """Validate JPEG SOI (FFD8) and EOI (FFD9) markers before host image reads (#1667 400 INVALID_ARGUMENT)."""
    norm = _normalize_image_read_target(raw_target)
    if not norm or not norm.lower().endswith(_JPEG_READ_SUFFIXES):
        return True, ""
    try:
        from platform_quirks import is_quirk_enabled
        if not is_quirk_enabled("1667", repo=_engine.REPO):
            return True, ""
    except ImportError:
        pass
    try:
        cand = Path(norm).expanduser()
        resolved = cand.resolve() if cand.is_absolute() else (_engine.REPO / cand).resolve()
        if not resolved.is_file() or resolved.is_symlink():
            return True, ""
        size = resolved.stat().st_size
        if size < 4:
            return (
                False,
                f"CORRUPT_JPEG_IMAGE_BLOCKED (#1667): '{norm}' is empty or truncated ({size} bytes) and lacks JPEG SOI/EOI markers (FFD8..FFD9). "
                "Reading malformed JPEG files permanently poisons Antigravity conversations with HTTP 400 INVALID_ARGUMENT (-2011). "
                "Verify or re-export the asset before calling read_file/view_file.",
            )
        with resolved.open("rb") as fh:
            head = fh.read(4)
            tail_offset = max(0, size - 64)
            fh.seek(tail_offset)
            tail = fh.read(64)
        if not head.startswith(b"\xff\xd8") or b"\xff\xd9" not in tail:
            return (
                False,
                f"CORRUPT_JPEG_IMAGE_BLOCKED (#1667): '{norm}' is missing valid JPEG SOI/EOI markers (FFD8..FFD9). "
                "Reading truncated or corrupt JPEG files permanently poisons Antigravity conversations with HTTP 400 INVALID_ARGUMENT (-2011). "
                "Inspect or re-export the asset before calling read_file/view_file.",
            )
    except OSError:
        return True, ""
    return True, ""


def _enforce_image_read_parallel_cap(raw_target: str, conv_key: str) -> bool:
    """Cap parallel image reads at <=6 per burst window (#1691 silent copyright/recitation filter hang, including MCP-offloaded media_*.webp #1828)."""
    norm = _normalize_image_read_target(raw_target)
    if not norm or not norm.lower().endswith(_IMAGE_READ_SUFFIXES):
        return False
    try:
        from platform_quirks import is_quirk_enabled
        if not is_quirk_enabled("1691", repo=_engine.REPO):
            return False
    except ImportError:
        pass
    key = str(conv_key or "default").strip() or "default"
    cache_dir = (_engine.REPO / ".agents" / "cache") if (_engine.REPO / ".agents").is_dir() else (_engine.REPO / "agents" / "state" / "cache")
    guard_path = cache_dir / "image-read-guard.json"
    lock_base = (_engine.REPO / ".agents" / "state") if (_engine.REPO / ".agents").is_dir() else (_engine.REPO / "agents" / "state")
    now = _engine.time.time()
    try:
        from _vnext_common import atomic_write_json
        from evidence_store import StateLock
        lock_base.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        with StateLock(lock_base):
            store: dict[str, Any] = {}
            if guard_path.is_file():
                try:
                    loaded = _engine.read_json(guard_path)
                    if isinstance(loaded, dict):
                        store = loaded
                except (OSError, ValueError, _engine.ValidationError):
                    store = {}
            pruned_store: dict[str, list[float]] = {}
            for ck, stamps in store.items():
                if isinstance(stamps, list):
                    kept = [float(t) for t in stamps if isinstance(t, (int, float)) and 0.0 <= (now - float(t)) <= _engine.IMAGE_READ_BURST_WINDOW_SEC]
                    if kept:
                        pruned_store[str(ck)] = kept
            cur_stamps = pruned_store.get(key, [])
            if len(cur_stamps) >= _engine.IMAGE_READ_MAX_PARALLEL_CALLS:
                _engine.emit(
                    "deny",
                    f"IMAGE_READ_PARALLEL_CAP_REACHED (#1691): Do NOT read more than {_engine.IMAGE_READ_MAX_PARALLEL_CALLS} images in a single parallel batch "
                    "(reading large PNG/image batches in one step triggers silent 4.5-7m copyright/recitation safety filter hangs on agy CLI v1.5.13). "
                    "Split image inspection into small batches (<=4-6 images per turn).",
                    tool="read_file",
                    reason_code="IMAGE_READ_PARALLEL_CAP_REACHED",
                )
                return True
            cur_stamps.append(now)
            pruned_store[key] = cur_stamps[-12:]
            atomic_write_json(guard_path, pruned_store)
    except (ImportError, OSError, ValueError, _engine.ValidationError):
        return False
    return False

