#!/usr/bin/env python3
"""Optional Manual Web-Relay Mode (`web-pack` / `web-apply`) for Android Agent Harness.

Bridges local AST-scoped discovery & deterministic Gradle/EvidenceStore verification in
Antigravity with manual high-reasoning offload on Gemini Web — with zero GitHub OAuth
linking, zero full-repo uploads, and zero impact on the default Antigravity-only mode.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _modules import is_kmp_or_android_test_path  # noqa: E402
from _vnext_common import (  # noqa: E402
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    configure_utf8_output,
    git_text,
    read_json,
    repository_identity,
    state_root,
    task_dir,
    utc_now,
    validate_id,
)

WEB_MERGE_SCHEMA = "HARNESS_WEB_MERGE_V1"
TEXT_CLIPBOARD_MAX_BYTES = 45_000
POSIX_CLIPBOARD_MAX_BYTES = 512_000
DEFAULT_WEB_PACK_BATCH_SIZE = 40
MAX_WEB_PACK_TOTAL_FILES = 250
BINARY_ASSET_EXTENSIONS = frozenset({
    ".png", ".webp", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".heic", ".avif",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".mov",
    ".pdf", ".jar", ".aar", ".so", ".dylib", ".dll", ".exe", ".apk", ".aab",
    ".keystore", ".jks", ".p12", ".pfx", ".zip", ".tar", ".gz", ".7z", ".db", ".sqlite",
})


def _is_binary_asset(path_rel: str, raw_bytes: bytes | None = None) -> bool:
    sfx = Path(path_rel).suffix.lower()
    if sfx in BINARY_ASSET_EXTENSIONS:
        return True
    if raw_bytes is not None and b"\x00" in raw_bytes[:8192]:
        return True
    return False


def _android_resource_ref_for_path(rel_path: str) -> str:
    norm = rel_path.replace("\\", "/")
    stem = Path(norm).stem.split(".")[0]
    if "/res/drawable" in norm:
        return f"R.drawable.{stem}"
    if "/res/mipmap" in norm:
        return f"R.mipmap.{stem}"
    if "/res/font" in norm:
        return f"R.font.{stem}"
    if "/res/raw" in norm:
        return f"R.raw.{stem}"
    if "/composeresources/drawable" in norm.lower():
        return f"Res.drawable.{stem}"
    if "/composeresources/font" in norm.lower():
        return f"Res.font.{stem}"
    return stem


def _collect_module_resource_inventory(repo: Path, scope_files: list[str]) -> str:
    """Scan touched modules for existing `R.drawable.*`, `R.font.*`, and KMP `Res.drawable.*` IDs."""
    has_ui_or_code = any(f.endswith((".kt", ".java", ".xml", ".swift")) for f in scope_files)
    if not has_ui_or_code:
        return ""
    mod_roots: list[Path] = []
    seen_roots: set[Path] = set()
    for rel in scope_files:
        norm = rel.replace("\\", "/")
        cand_root = repo / norm.split("/src/", 1)[0] if "/src/" in norm else repo
        if cand_root.is_dir() and cand_root not in seen_roots:
            seen_roots.add(cand_root)
            mod_roots.append(cand_root)
    if not mod_roots and (repo / "app").is_dir():
        mod_roots.append(repo / "app")

    drawables: set[str] = set()
    fonts: set[str] = set()
    kmp_drawables: set[str] = set()
    for m_root in mod_roots[:6]:
        src_dir = m_root / "src"
        if not src_dir.is_dir():
            continue
        for res_d in src_dir.glob("*/res"):
            for d_folder in res_d.glob("drawable*"):
                if d_folder.is_dir():
                    for f_it in d_folder.iterdir():
                        if f_it.is_file() and not f_it.name.startswith("."):
                            drawables.add(f_it.stem.split(".")[0])
            for f_folder in res_d.glob("font*"):
                if f_folder.is_dir():
                    for f_it in f_folder.iterdir():
                        if f_it.is_file() and not f_it.name.startswith("."):
                            fonts.add(f_it.stem.split(".")[0])
        for cr_d in src_dir.glob("*/composeResources"):
            for d_folder in cr_d.glob("drawable*"):
                if d_folder.is_dir():
                    for f_it in d_folder.iterdir():
                        if f_it.is_file() and not f_it.name.startswith("."):
                            kmp_drawables.add(f_it.stem.split(".")[0])

    lines: list[str] = []
    if drawables:
        d_sorted = sorted(drawables)
        shown = ", ".join(f"`R.drawable.{n}`" for n in d_sorted[:70])
        more = f" (+{len(d_sorted) - 70} more)" if len(d_sorted) > 70 else ""
        lines.append(f"- **Existing Android Drawables ({len(d_sorted)})**: {shown}{more}")
    if kmp_drawables:
        kd_sorted = sorted(kmp_drawables)
        shown_k = ", ".join(f"`Res.drawable.{n}`" for n in kd_sorted[:50])
        more_k = f" (+{len(kd_sorted) - 50} more)" if len(kd_sorted) > 50 else ""
        lines.append(f"- **Existing KMP Compose Drawables ({len(kd_sorted)})**: {shown_k}{more_k}")
    if fonts:
        f_sorted = sorted(fonts)
        shown_f = ", ".join(f"`R.font.{n}`" for n in f_sorted[:25])
        lines.append(f"- **Existing Module Fonts ({len(f_sorted)})**: {shown_f}")
    return "\n".join(lines)


def _dag_sort_scope_files(files: list[str]) -> list[str]:
    """Order large multi-file scopes cleanly: core/domain/models -> data/db/network -> UI/ViewModel -> resources -> tests."""
    def _rank(rel: str) -> tuple[int, int, str]:
        low = rel.replace("\\", "/").lower()
        if is_kmp_or_android_test_path(rel):
            return (4, 1, low)
        if "/res/" in low or "/composeresources/" in low or low.endswith(".xml"):
            return (3, 0, low)
        mod_tier = 1
        if any(seg in low for seg in ("commonmain/", "core/", "domain/", "shared/", "model/", "entity/")):
            mod_tier = 0
        elif any(seg in low for seg in ("app/", "androidapp/", "wearapp/", "ui/", "screen", "fragment", "activity", "viewmodel")):
            mod_tier = 2
        return (mod_tier, 0, low)
    return sorted(files, key=_rank)

SECRET_FILE_MARKERS = (
    ".env",
    "keystore",
    ".jks",
    ".p12",
    ".pem",
    "local.properties",
    "google-services.json",
    "googleservice-info.plist",
    "service-account",
    "credentials",
    "secret",
)

PROTECTED_REL_PREFIXES = (
    ".agents/",
    "agents/scripts/",
    "agents/state/",
    ".harness-setup/",
    ".git/",
    ".gradle/",
    ".idea/",
)

INLINE_SECRET_PATTERNS = (
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"""(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|password|revenuecat[_-]?key)\s*[:=]\s*["']([^"'\s]{12,})["']"""),
)

LAZY_TRUNCATION_RE = re.compile(
    r"(?://|/\*+|\#)\s*(?:\.\.\.|…)?\s*(?:rest of (?:the )?(?:code|file|class|implementation)|"
    r"existing (?:code|implementation|methods)|remaining (?:code|methods|lines) unchanged|"
    r"unchanged (?:code|lines|methods)|keep existing code|باقي الكود كما هو|بقية الكود بدون تغيير)",
    re.IGNORECASE,
)


CONFLICT_MARKER_RE = re.compile(
    r"^(?:<<<<<<<\s+|=======\s*$|>>>>>>>\s+)",
    re.MULTILINE,
)


def _norm_rel(repo: Path, raw_path: str) -> str:
    cleaned = str(raw_path or "").strip().replace("\\", "/")
    p = Path(cleaned)
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError as exc:
            raise ValidationError(f"Path '{raw_path}' is outside repository root.") from exc
    else:
        rel = cleaned.lstrip("./")
        resolved = (repo / rel).resolve()
        try:
            rel = resolved.relative_to(repo.resolve()).as_posix()
        except ValueError as exc:
            raise ValidationError(f"Path traversal blocked for '{raw_path}'.") from exc
    if not rel or rel == ".":
        raise ValidationError("Empty repository-relative file path.")
    return rel


def _is_protected_or_secret_path(rel_path: str) -> tuple[bool, str]:
    low = rel_path.lower().strip("/")
    for pref in PROTECTED_REL_PREFIXES:
        p_clean = pref.strip("/")
        if low == p_clean or low.startswith(p_clean + "/"):
            return True, f"Protected harness/VCS path '{rel_path}' cannot be exported or modified via web-relay."
    name_low = Path(low).name
    if name_low == ".env" or name_low.startswith(".env."):
        return True, f"Secret environment file '{rel_path}' is excluded by Zero-Secret Gate."
    for marker in SECRET_FILE_MARKERS:
        if marker in low:
            return True, f"Sensitive/secret path '{rel_path}' matched '{marker}' and is excluded by Zero-Secret Gate."
    return False, ""


def _detect_eol(raw_bytes: bytes) -> str:
    return "crlf" if b"\r\n" in raw_bytes else "lf"


def _apply_eol(text: str, eol: str) -> bytes:
    lf_text = text.replace("\r\n", "\n").replace("\r", "\n")
    if eol == "crlf":
        return lf_text.replace("\n", "\r\n").encode("utf-8")
    return lf_text.encode("utf-8")


def _sha256_lf(text: str) -> str:
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _redact_inline_secrets(text: str, vault: dict[str, str]) -> str:
    reverse_vault = {v: k for k, v in vault.items()}

    def _sub_whole(match: re.Match[str]) -> str:
        full = match.group(0)
        if match.lastindex:
            secret_val = match.group(1)
            if secret_val.startswith("__HARNESS_REDACTED_SECRET_"):
                return full
            tok = reverse_vault.get(secret_val)
            if not tok:
                tok = f"__HARNESS_REDACTED_SECRET_{len(vault) + 1}__"
                vault[tok] = secret_val
                reverse_vault[secret_val] = tok
            return full.replace(secret_val, tok)
        if full.startswith("__HARNESS_REDACTED_SECRET_"):
            return full
        tok = reverse_vault.get(full)
        if not tok:
            tok = f"__HARNESS_REDACTED_SECRET_{len(vault) + 1}__"
            vault[tok] = full
            reverse_vault[full] = tok
        return tok

    out = text
    for pat in INLINE_SECRET_PATTERNS:
        out = pat.sub(_sub_whole, out)
    return out


def _restore_inline_secrets(text: str, vault: dict[str, str]) -> str:
    out = text
    for placeholder, real_val in (vault or {}).items():
        if placeholder in out:
            out = out.replace(placeholder, real_val)
    return out


def _web_relay_state_dir(repo: Path) -> Path:
    d = state_root(repo) / "web-relay"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _default_outbox_dir() -> Path:
    env_dir = (os.environ.get("HARNESS_WEB_RELAY_DIR") or os.environ.get("HARNESS_WEB_RELAY_OUTBOX") or "").strip()
    if env_dir:
        p = Path(env_dir).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    dl = Path.home() / "Downloads" / "Harness-Web-Relay"
    try:
        dl.mkdir(parents=True, exist_ok=True)
        probe = dl / f".write-probe-{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink(missing_ok=True)
        return dl
    except OSError:
        fb = Path(tempfile.gettempdir()).resolve() / "Harness-Web-Relay"
        fb.mkdir(parents=True, exist_ok=True)
        return fb


def _default_downloads_dirs() -> list[Path]:
    dirs: list[Path] = []
    for env_key in ("HARNESS_WEB_RELAY_DIR", "HARNESS_WEB_RELAY_OUTBOX", "HARNESS_WEB_RELAY_DOWNLOADS", "HARNESS_DOWNLOADS_DIR"):
        val = os.environ.get(env_key, "").strip()
        if val:
            p = Path(val).expanduser().resolve()
            if p not in dirs:
                dirs.append(p)
    try:
        home_dl = Path.home() / "Downloads"
        if home_dl.is_dir():
            for cand in (home_dl / "Harness-Web-Relay", home_dl):
                if cand not in dirs:
                    dirs.append(cand)
    except OSError:
        pass
    tmp_fb = Path(tempfile.gettempdir()).resolve() / "Harness-Web-Relay"
    if tmp_fb not in dirs and tmp_fb.is_dir():
        dirs.append(tmp_fb)
    return [d for d in dirs if d.is_dir()]


def _copy_to_clipboard(bundle_path: Path, bundle_text: str) -> dict[str, Any]:
    if os.environ.get("HARNESS_NO_CLIPBOARD") == "1":
        return {"copied": False, "mode": "disabled"}
    size_b = len(bundle_text.encode("utf-8"))
    try:
        if sys.platform == "win32":
            if size_b <= TEXT_CLIPBOARD_MAX_BYTES:
                ps_cmd = (
                    "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
                    "$inputText = [Console]::In.ReadToEnd(); "
                    "Set-Clipboard -Value $inputText"
                )
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                    input=bundle_text,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=6,
                    check=False,
                )
                if proc.returncode == 0:
                    return {"copied": True, "mode": "windows_utf8_text", "bytes": size_b}
            ps_file_cmd = f"Set-Clipboard -Path '{str(bundle_path).replace(chr(39), chr(39)*2)}'"
            proc_f = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_file_cmd],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=6,
                check=False,
            )
            if proc_f.returncode == 0:
                return {"copied": True, "mode": "windows_cf_hdrop_file", "bytes": size_b}
        elif sys.platform == "darwin":
            if shutil.which("pbcopy") and size_b <= POSIX_CLIPBOARD_MAX_BYTES:
                proc = subprocess.run(
                    ["pbcopy"],
                    input=bundle_text.encode("utf-8"),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                if proc.returncode == 0:
                    return {"copied": True, "mode": "macos_pbcopy", "bytes": size_b}
        elif size_b <= POSIX_CLIPBOARD_MAX_BYTES:
            linux_copy_cmds: list[tuple[str, list[str]]] = []
            if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
                linux_copy_cmds.append(("linux_wl_copy", ["wl-copy"]))
            if shutil.which("xclip"):
                linux_copy_cmds.append(("linux_xclip", ["xclip", "-selection", "clipboard"]))
            if shutil.which("xsel"):
                linux_copy_cmds.append(("linux_xsel", ["xsel", "--clipboard", "--input"]))
            if not os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
                linux_copy_cmds.append(("linux_wl_copy", ["wl-copy"]))
            for mode_lbl, cmd_vec in linux_copy_cmds:
                proc = subprocess.run(
                    cmd_vec,
                    input=bundle_text.encode("utf-8"),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=4,
                    check=False,
                )
                if proc.returncode == 0:
                    return {"copied": True, "mode": mode_lbl, "bytes": size_b}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"copied": False, "mode": "file_only", "file": str(bundle_path), "bytes": size_b}


def _read_clipboard_text() -> str:
    env_clip = os.environ.get("HARNESS_CLIPBOARD_FILE", "").strip()
    if env_clip and Path(env_clip).is_file():
        return Path(env_clip).read_text(encoding="utf-8", errors="replace")
    if os.environ.get("HARNESS_NO_CLIPBOARD") == "1":
        return ""
    try:
        if sys.platform == "win32":
            ps_cmd = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-Clipboard -Raw"
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                return proc.stdout or ""
        elif sys.platform == "darwin":
            if shutil.which("pbpaste"):
                proc = subprocess.run(["pbpaste"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False)
                if proc.returncode == 0:
                    return proc.stdout or ""
        else:
            linux_read_cmds: list[list[str]] = []
            if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
                linux_read_cmds.append(["wl-paste", "--no-newline"])
            if shutil.which("xclip"):
                linux_read_cmds.append(["xclip", "-selection", "clipboard", "-o"])
            if shutil.which("xsel"):
                linux_read_cmds.append(["xsel", "--clipboard", "--output"])
            if not os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
                linux_read_cmds.append(["wl-paste", "--no-newline"])
            for r_cmd in linux_read_cmds:
                proc = subprocess.run(r_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=4, check=False)
                if proc.returncode == 0 and (proc.stdout or "").strip():
                    return proc.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""
    return ""


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


DIRTY_SOURCE_SUFFIXES = frozenset({
    ".kt", ".java", ".xml", ".swift", ".kts", ".gradle", ".toml", ".sq", ".sqm", ".proto", ".graphql", ".graphqls", ".pro", ".json",
})


def _collect_git_dirty_source_files(
    repo: Path,
    rejected_secret_files: list[str] | None = None,
) -> list[str]:
    """Collect modified, staged, renamed, and untracked source/resource files from the Git working tree."""
    found: list[str] = []
    seen_d: set[str] = set()
    try:
        out = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uall"],
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
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
            rel = _norm_rel(repo, raw_p)
        except ValidationError:
            continue
        low_parts = rel.lower().split("/")
        if any(seg in {"build", ".gradle", ".idea", "out", "node_modules", "__pycache__"} for seg in low_parts[:-1]):
            continue
        blocked, _ = _is_protected_or_secret_path(rel)
        if blocked:
            if rejected_secret_files is not None and rel not in rejected_secret_files:
                rejected_secret_files.append(rel)
            continue
        fp = repo / rel
        if not fp.is_file() or Path(rel).suffix.lower() not in DIRTY_SOURCE_SUFFIXES:
            continue
        if _is_binary_asset(rel):
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
            rel = _norm_rel(repo, cand)
        except ValidationError:
            return
        blocked, _ = _is_protected_or_secret_path(rel)
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
        for d_rel in _collect_git_dirty_source_files(repo, rejected_secret_files):
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
            for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", prompt_text or ""):
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
        except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
            pass

    if not ordered and prompt_text:
        tokens = [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", prompt_text)]
        if tokens:
            try:
                tracked = subprocess.check_output(
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
            except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
                pass

    # Automatic IDLE Studio-to-Web fallback: if no explicit files or AST symbols matched yet, capture open Git working-tree edits!
    if not ordered and not active_plan_doc:
        for d_rel in _collect_git_dirty_source_files(repo, rejected_secret_files):
            _add(d_rel)
            if captured_dirty_out is not None and d_rel not in captured_dirty_out:
                captured_dirty_out.append(d_rel)

    # Auto-include git unmerged conflict paths if repository is in a merge/rebase conflict state
    try:
        from _vnext_common import unmerged_paths
        for u_rel in unmerged_paths(repo):
            _add(u_rel)
    except (ImportError, OSError, ValueError, ValidationError):
        pass

    try:
        tracked_all = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "ls-files"],
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except (OSError, subprocess.SubprocessError):
        tracked_all = []

    # Auto-include sibling localized `values-*/strings.xml` when `values/strings.xml` is in scope (works at any task size!)
    for cur_rel in list(ordered):
        if cur_rel.endswith("/res/values/strings.xml") or cur_rel == "res/values/strings.xml":
            res_parent = (repo / cur_rel).parent.parent
            if res_parent.is_dir():
                for sib in sorted(res_parent.glob("values-*/strings.xml")):
                    if sib.is_file() and len(ordered) < MAX_WEB_PACK_TOTAL_FILES:
                        _add(sib.relative_to(repo).as_posix())

    # Auto-include module `@Database` / `*DatabaseModule*.kt` when an `@Entity` file is in scope (single-pass Room migrations)
    has_room_entity = False
    entity_module_prefixes: set[str] = set()
    for cur_rel in list(ordered):
        fp_c = repo / cur_rel
        if fp_c.is_file() and cur_rel.endswith((".kt", ".java")) and not _is_binary_asset(cur_rel):
            c_txt = fp_c.read_text(encoding="utf-8", errors="replace")
            if "@Entity" in c_txt:
                has_room_entity = True
                if "/src/" in cur_rel:
                    entity_module_prefixes.add(cur_rel.split("/src/", 1)[0] + "/src/")
    if has_room_entity:
        db_added = 0
        for rel in tracked_all:
            if db_added >= 3 or len(ordered) >= MAX_WEB_PACK_TOTAL_FILES:
                break
            if not rel.endswith((".kt", ".java")) or is_kmp_or_android_test_path(rel) or rel in seen:
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
    stems = {Path(f).stem for f in list(ordered) if f.endswith((".kt", ".java")) and not is_kmp_or_android_test_path(f)}
    tests_added = 0
    for rel in tracked_all:
        if tests_added >= 12 or len(ordered) >= MAX_WEB_PACK_TOTAL_FILES:
            break
        if rel not in seen and is_kmp_or_android_test_path(rel) and any(Path(rel).stem.startswith(s + "Test") or Path(rel).stem == f"{s}Test" for s in stems):
            _add(rel)
            tests_added += 1

    return ordered[:MAX_WEB_PACK_TOTAL_FILES]


def _extract_neighbor_signatures(repo: Path, scope_files: list[str], vault: dict[str, str]) -> list[dict[str, str]]:
    """Extract compact read-only AST/declaration signatures for direct imported repo classes."""
    scope_set = set(scope_files)
    imported_simple_names: set[str] = set()
    pkg_re = re.compile(r"^\s*import\s+([A-Za-z0-9_.]+)\.([A-Z][A-Za-z0-9_]*)\s*$", re.MULTILINE)
    decl_line_re = re.compile(
        r"^\s*(?:@(?:Entity|Dao|Module|HiltViewModel|Composable|Serializable)\b[^\n]*\n\s*)*"
        r"(?:public\s+|internal\s+|abstract\s+|open\s+|sealed\s+|data\s+|enum\s+|value\s+)*"
        r"(?:class|interface|object|fun|val|var|typealias)\s+[^\n{=]+",
        re.MULTILINE,
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
        tracked = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "ls-files"],
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except (OSError, subprocess.SubprocessError):
        tracked = []

    for rel in tracked:
        if len(neighbors) >= 20:
            break
        if rel in scope_set or not rel.endswith((".kt", ".java", ".swift")):
            continue
        blocked, _ = _is_protected_or_secret_path(rel)
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
                "signatures": _redact_inline_secrets(skeleton[:1800], vault),
            })
    return neighbors


def _collect_active_diagnostics(repo: Path, task_id: str) -> str:
    chunks: list[str] = []
    if task_id:
        try:
            from delegation_policy import get_worker_handoff_capsule
            cap = get_worker_handoff_capsule(repo, task_id)
            if not cap:
                raw_hf = task_dir(repo, task_id) / "worker-handoff.json"
                if raw_hf.is_file():
                    hf_doc = read_json(raw_hf)
                    if str(hf_doc.get("status") or "").upper() not in {"RESOLVED", "CLEARED"}:
                        cap = hf_doc
            if cap:
                chunks.append("### Worker Handoff Capsule (Preserve Existing Progress — Do Not Restart From Scratch)\n" + json.dumps({
                    "takeover_trigger": cap.get("takeover_trigger"),
                    "last_failed_gate": cap.get("last_failed_gate"),
                    "completed_files_on_disk": cap.get("completed_files_on_disk"),
                    "passing_gates": cap.get("passing_gates"),
                    "failing_gates": cap.get("failing_gates"),
                    "attempt_history": cap.get("attempt_history"),
                    "summary_for_lead": cap.get("summary_for_lead") or cap.get("summary"),
                }, indent=2, ensure_ascii=False))
        except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
            pass
    res_dir = state_root(repo) / "results"
    if res_dir.is_dir():
        for r_file in sorted(res_dir.glob("*.json")):
            try:
                rdoc = read_json(r_file)
                if str(rdoc.get("status") or "").upper() == "FAIL":
                    chunks.append(
                        f"### Failing Local Gate: `{r_file.stem}`\n"
                        f"- Detail: {str(rdoc.get('detail') or rdoc.get('summary') or '')[:800]}\n"
                        f"- Output tail: {str(rdoc.get('output_tail') or rdoc.get('stderr_tail') or '')[:1000]}"
                    )
            except (OSError, ValueError, ValidationError):
                continue
    return "\n\n".join(chunks)


def _load_project_summary(repo: Path, vault: dict[str, str]) -> str:
    ctx_dir = repo / ".agents" / "project-context"
    parts: list[str] = []
    facts_f = ctx_dir / "project-facts.json"
    if facts_f.is_file():
        try:
            facts = read_json(facts_f)
            compact_facts = {k: facts.get(k) for k in ("architecture_family", "di_framework", "ui_toolkits", "modules", "min_sdk", "target_sdk", "locales") if k in facts}
            parts.append("Project Facts: " + json.dumps(compact_facts, ensure_ascii=False))
        except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
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
        except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
            notes_txt = notes_f.read_text(encoding="utf-8", errors="replace")
        if notes_txt.strip():
            parts.append("Project Notes:\n" + _redact_inline_secrets(notes_txt[:2500], vault))
    inst_f = ctx_dir / "developer-instructions.json"
    if inst_f.is_file():
        try:
            inst_raw = inst_f.read_text(encoding="utf-8", errors="replace")
            if inst_raw.strip():
                parts.append("Developer Instructions:\n" + _redact_inline_secrets(inst_raw[:1500], vault))
        except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
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
    no_clipboard: bool = False,
    allow_conflict_pack: bool = False,
    include_dirty: bool = False,
    batch_size: int = DEFAULT_WEB_PACK_BATCH_SIZE,
    all_in_one: bool = False,
    batch_index: int = 1,
    total_batches_hint: int = 0,
    remaining_batches_override: list[list[str]] | None = None,
) -> dict[str, Any]:
    active_doc: dict[str, Any] | None = None
    try:
        from mutation_guard import active_plan
        active_doc = active_plan(repo, allow_missing=True)
    except (ImportError, OSError, ValueError, ValidationError):
        active_doc = None

    eff_tid = str(task_id or (active_doc or {}).get("task_id") or "").strip()
    if eff_tid and active_doc is None:
        pf = task_dir(repo, eff_tid) / "plan.json"
        if pf.is_file():
            active_doc = read_json(pf)

    eff_prompt = str(prompt or (active_doc or {}).get("requested_outcome") or (active_doc or {}).get("outcome") or "").strip()
    if not eff_prompt:
        eff_prompt = "Analyze the scoped files, resolve the issue or implement the requested change, and include unit tests."
    eff_kind = _infer_task_kind(eff_prompt, kind or str((active_doc or {}).get("task_kind") or ""))

    prev_pack: dict[str, Any] | None = None
    latest_ptr = _web_relay_state_dir(repo) / "latest-pack.json"
    task_ptr = (task_dir(repo, eff_tid) / "latest-web-pack.json") if eff_tid and (state_root(repo) / "tasks" / eff_tid).is_dir() else None
    chosen_ptr = task_ptr if (task_ptr is not None and task_ptr.is_file()) else latest_ptr
    if (retry or add_files) and chosen_ptr.is_file():
        try:
            ptr = read_json(chosen_ptr)
            prev_f = _web_relay_state_dir(repo) / "packs" / f"{ptr.get('pack_id')}.json"
            if prev_f.is_file():
                prev_pack = read_json(prev_f)
        except (OSError, ValueError, ValidationError):
            prev_pack = None

    seed_files = list(files or [])
    retry_implicated_set: set[str] = set()
    if retry and not seed_files:
        diag_probe = _collect_active_diagnostics(repo, eff_tid)
        if diag_probe:
            cand_pool = set((active_doc or {}).get("expected_files") or [])
            for m_path in re.findall(r"([A-Za-z0-9_./-]+\.(?:kt|java|xml|swift|kts))", diag_probe):
                try:
                    norm_m = _norm_rel(repo, m_path)
                except ValidationError:
                    continue
                if (repo / norm_m).is_file() and (not cand_pool or norm_m in cand_pool or any(p.endswith("/" + norm_m) for p in cand_pool)):
                    resolved_m = norm_m if (not cand_pool or norm_m in cand_pool) else next(p for p in sorted(cand_pool) if p.endswith("/" + norm_m))
                    if resolved_m not in seed_files:
                        seed_files.append(resolved_m)
                        retry_implicated_set.add(resolved_m)
    if prev_pack and not files:
        for pf_k in (prev_pack.get("editable_files") or {}).keys():
            if pf_k not in seed_files:
                seed_files.append(pf_k)
    if add_files:
        for item in add_files:
            for sub in str(item).split(","):
                if sub.strip():
                    seed_files.append(sub.strip())

    rejected_secrets: list[str] = []
    captured_dirty: list[str] = []
    scope_files = _discover_scope_files(
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
        raise ValidationError(
            f"WEB_RELAY_SECRET_SCOPE_FALLBACK: All target file(s) ({', '.join(rejected_secrets)}) are protected by the "
            "Zero-Secret Gate and cannot be exported to Gemini Web. "
            "TOOL_CALL_REQUIRED=ask_question — Ask the developer via `ask_question` with a simple English choice: "
            "'Run this task locally in Normal mode (keep project Web default intact)' -> run "
            f"`{fallback_cmd}` and execute locally."
        )
    if not scope_files:
        raise ValidationError(
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
            raise ValidationError(
                f"WEB_RELAY_CONFLICT_LOCAL_RECOMMENDED ({conf_sig or eff_kind}): Git merge/rebase conflict resolution "
                "requires 3-way local Git context and runs locally in Antigravity (preserving any `web-project` default "
                "for subsequent tasks). Resolve locally via `task draft --kind CONFLICT`, or pass `--allow-conflict-pack` if intentional."
            )

    pack_id = f"wpack-{uuid.uuid4().hex[:12]}"
    repo_fp = repository_identity(repo)
    head_sha = git_text(repo, "rev-parse", "HEAD")
    vault: dict[str, str] = dict((prev_pack or {}).get("secret_vault") or {})
    binary_assets_meta: list[dict[str, Any]] = []
    text_scope_files: list[str] = []

    for rel in scope_files:
        fp = repo / rel
        if fp.is_file():
            raw_probe = fp.read_bytes()
            if _is_binary_asset(rel, raw_probe):
                binary_assets_meta.append({
                    "path": rel,
                    "bytes": len(raw_probe),
                    "resource_ref": _android_resource_ref_for_path(rel),
                })
                continue
        elif _is_binary_asset(rel, None):
            binary_assets_meta.append({
                "path": rel,
                "bytes": 0,
                "resource_ref": _android_resource_ref_for_path(rel),
            })
            continue
        text_scope_files.append(rel)

    if not text_scope_files and binary_assets_meta:
        refs = ", ".join(f"{b['path']} ({b['resource_ref']})" for b in binary_assets_meta[:8])
        raise ValidationError(
            f"WEB_PACK_BINARY_ONLY_SCOPE: Binary asset(s) ({refs}) stay local on disk and cannot be edited as text. "
            "Include the Kotlin/Java/XML source files that reference them in `--files`."
        )

    # Smart DAG batch sharding for massive refactors (`41–250` files), while keeping `1–40` file tasks in ONE single pack!
    eff_batch_size = max(5, int(batch_size or DEFAULT_WEB_PACK_BATCH_SIZE))
    pending_batches: list[list[str]] = []
    if remaining_batches_override is not None:
        active_batch_files = list(text_scope_files)
        pending_batches = [list(b) for b in remaining_batches_override if b]
        cur_batch_num = max(1, int(batch_index or 1))
        total_batches = max(cur_batch_num, int(total_batches_hint or (cur_batch_num + len(pending_batches))))
    elif not all_in_one and not retry and len(text_scope_files) > eff_batch_size:
        dag_ordered = _dag_sort_scope_files(text_scope_files)
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

    for rel in active_batch_files:
        fp = repo / rel
        if fp.is_file():
            raw_b = fp.read_bytes()
            eol = _detect_eol(raw_b)
            raw_txt = raw_b.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            sha = _sha256_lf(raw_txt)
            redacted_txt = _redact_inline_secrets(raw_txt, vault)
            editable_meta[rel] = {"exists": True, "sha256": sha, "eol": eol, "base_text": raw_txt}
            if not retry or rel in retry_implicated_set or (prev_pack and ((prev_pack.get("editable_files") or {}).get(rel) or {}).get("sha256") != sha) or (add_files and rel in (add_files or [])):
                ext = Path(rel).suffix.lstrip(".") or "txt"
                file_blocks_md.append(f"### FILE: `{rel}` (`sha256={sha[:12]}`, `{len(raw_txt.splitlines())}` lines)\n```{ext}\n{redacted_txt.rstrip()}\n```")
        else:
            editable_meta[rel] = {"exists": False, "sha256": "", "eol": "lf", "base_text": ""}
            file_blocks_md.append(f"### PLANNED NEW FILE: `{rel}` (does not exist yet)")

    neighbors = [] if retry else _extract_neighbor_signatures(repo, active_batch_files, vault)
    proj_summary = "" if retry else _load_project_summary(repo, vault)
    resource_inventory = "" if retry else _collect_module_resource_inventory(repo, active_batch_files)
    diagnostics = _collect_active_diagnostics(repo, eff_tid)

    suggested_tid = eff_tid or re.sub(r"[^a-z0-9-]+", "-", eff_prompt.lower())[:28].strip("-") or f"web-task-{pack_id[-6:]}"
    if len(suggested_tid) < 3:
        suggested_tid = f"web-{pack_id[-6:]}"

    schema_example = {
        "schema": WEB_MERGE_SCHEMA,
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
        "schema": WEB_MERGE_SCHEMA,
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

    md_sections = [
        f"# Android Agent Harness — Web-Relay Context Pack (`{pack_id}`)",
        "",
        "## 1. Mission & Output Contract (For Gemini Web)",
        f"- **Task Goal**: {eff_prompt}",
        f"- **Task Kind**: `{eff_kind}` | **Suggested Task ID**: `{suggested_tid}` | **Pack ID**: `{pack_id}`{batch_banner}",
        "- **Editing Freedom & Rules**:",
        "  1. Solve the task completely across all affected files in this pack: preserve Clean Architecture boundaries, maintain bilingual EN/AR string parity (`values/strings.xml` + `values-ar/strings.xml`) when adding user-visible strings, include Room `Migration`s when changing `@Entity` schemas, and include JUnit tests (for `BUG` tasks, ensure the test FAILS before your production fix and PASSES after).",
        "  2. **Compact Lossless `hunks` (Essential for `10–100` File Tasks)**: For `MODIFY` operations, ALWAYS prefer minimal `hunks` (`search` / `replace` with 2-3 surrounding context lines copied verbatim, or set `\"replace_all\": true` for repeated symbol/import/package renames across a file) instead of rewriting whole files. **NEVER** emit lazy truncation comments (`// ... rest of code unchanged`, `// existing code`).",
        "  3. **Full Freedom to Create, Rename, Delete & Patch Neighbors**: You may freely `CREATE` new classes, unit tests, or Android `<vector>` XML drawables (`res/drawable/ic_*.xml`), `DELETE` or `RENAME` (`old_path` -> `path`) scoped files, and apply surgical `hunks` to `READ_ONLY_NEIGHBOR_SIGNATURES` when updating shared interfaces/imports. Never blindly overwrite an unseen file with full `content` — emit `NEED_FILES` if you need a missing file's full body first.",
        "  4. **UI Screenshots & Drawables**: If the developer attached a UI design image/screenshot in chat alongside this pack, match its layout hierarchy, spacing, colors, typography, and RTL support faithfully, reusing existing `R.drawable.*` / `R.font.*` IDs listed in Section 2 (or `CREATE` new `<vector>` XML drawables as needed).",
        "  5. **Large Multi-File Replies (`PARTIAL` Continuation Supported)**: If your JSON output for a very large pack approaches message length limits, do NOT truncate code — emit valid JSON for the first subset with `\"status\": \"PARTIAL\"` so the developer can apply it and ask `Continue remaining files` in this same chat using the same `pack_id`.",
        "  6. Preserve any `__HARNESS_REDACTED_SECRET_N__` token verbatim (real values are restored locally). End your response with **one fenced ```json block** (or a downloadable file named "
        f"`harness-merge-{pack_id}.json`).",
        "",
        "### Required Output JSON Schema (`READY` / `PARTIAL` vs `NEED_FILES`)",
        "```json",
        json.dumps(schema_example, indent=2, ensure_ascii=False),
        "```",
        "*(If you must inspect the full source of additional repo file(s) before coding, return instead:)*",
        "```json",
        json.dumps(need_files_example, indent=2, ensure_ascii=False),
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
    out_dir = _default_outbox_dir()
    repo_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", repo.name).strip("-") or "android-repo"
    bundle_file = out_dir / f"{repo_slug}-{pack_id}.md"
    bundle_file.write_text(bundle_text, encoding="utf-8")

    packs_dir = _web_relay_state_dir(repo) / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    pack_record = {
        "schema_version": 1,
        "pack_id": pack_id,
        "created_at": utc_now(),
        "repo_fingerprint": repo_fp,
        "base_head": head_sha,
        "task_id": eff_tid,
        "suggested_task_id": suggested_tid,
        "kind": eff_kind,
        "prompt": eff_prompt,
        "retry": retry,
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
    atomic_write_json(packs_dir / f"{pack_id}.json", pack_record)
    ptr_payload = {"pack_id": pack_id, "task_id": eff_tid, "bundle_file": str(bundle_file), "created_at": pack_record["created_at"]}
    atomic_write_json(latest_ptr, ptr_payload)
    if eff_tid and (state_root(repo) / "tasks" / eff_tid).is_dir():
        atomic_write_json(task_dir(repo, eff_tid) / "latest-web-pack.json", ptr_payload)
    else:
        try:
            from execution_mode import record_pending_pack_link
            record_pending_pack_link(repo, pack_id)
        except (ImportError, OSError, ValueError, ValidationError):
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
                query_value=json.dumps(existing_resolved[:8], ensure_ascii=True),
                graph_fingerprint=g_fp,
                resolved_modules=mods_found,
                resolved_paths=existing_resolved,
                resolved_symbols=[],
            )
            save_discovery_receipt(repo, disc_rec)
            cache_dir = repo / ".agents" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(cache_dir / "last-task-context.json", {
                "context_id": disc_rec["id"],
                "file": existing_resolved[0],
                "module": mods_found[0] if mods_found else ":",
                "timestamp": _time.time(),
            })
    except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
        pass

    clip_info = {"copied": False, "mode": "skipped"} if no_clipboard else _copy_to_clipboard(bundle_file, bundle_text)
    return {
        "status": "OK",
        "pack_id": pack_id,
        "repo_fingerprint": repo_fp,
        "task_id": eff_tid or None,
        "suggested_task_id": suggested_tid,
        "kind": eff_kind,
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
    }


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


def _extract_merge_json_from_text(raw_text: str) -> dict[str, Any] | None:
    text = (raw_text or "").strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    for candidate_text in (text, _strip_trailing_json_commas(text)):
        try:
            obj = json.loads(candidate_text)
            if isinstance(obj, dict) and obj.get("schema") == WEB_MERGE_SCHEMA:
                return obj
        except ValueError:
            pass
        # Scan balanced JSON objects containing WEB_MERGE_SCHEMA (immune to inner ``` fences or trailing prose!)
        search_pos = 0
        matched_objs: list[dict[str, Any]] = []
        while True:
            idx = candidate_text.find(f'"{WEB_MERGE_SCHEMA}"', search_pos)
            if idx == -1:
                break
            brace_pos = candidate_text.rfind("{", 0, idx)
            while brace_pos != -1:
                try:
                    obj, _ = decoder.raw_decode(candidate_text, brace_pos)
                    if isinstance(obj, dict) and obj.get("schema") == WEB_MERGE_SCHEMA:
                        matched_objs.append(obj)
                        break
                except ValueError:
                    pass
                brace_pos = candidate_text.rfind("{", 0, brace_pos)
            search_pos = idx + len(WEB_MERGE_SCHEMA)
        if matched_objs:
            return matched_objs[-1]
    return None


def _resolve_incoming_merge_payload(repo: Path, explicit_file: str, use_stdin: bool) -> tuple[dict[str, Any], str]:
    if explicit_file:
        fp = Path(explicit_file).expanduser().resolve()
        if not fp.is_file():
            raise ValidationError(f"Merge payload file not found: {fp}")
        if fp.suffix.lower() == ".zip":
            import zipfile
            with zipfile.ZipFile(fp, "r") as zf:
                for name in zf.namelist():
                    if name.endswith(".json"):
                        parsed = _extract_merge_json_from_text(zf.read(name).decode("utf-8", errors="replace"))
                        if parsed:
                            return parsed, f"zip:{fp}"
            raise ValidationError(f"ZIP file '{fp}' does not contain a valid {WEB_MERGE_SCHEMA} JSON document.")
        parsed = _extract_merge_json_from_text(fp.read_text(encoding="utf-8", errors="replace"))
        if not parsed:
            raise ValidationError(f"File '{fp}' does not contain a valid `{WEB_MERGE_SCHEMA}` JSON payload.")
        return parsed, f"file:{fp}"

    if use_stdin:
        from _vnext_common import read_utf8_stdin
        parsed = _extract_merge_json_from_text(read_utf8_stdin())
        if not parsed:
            raise ValidationError(f"Standard input did not contain a valid `{WEB_MERGE_SCHEMA}` JSON payload.")
        return parsed, "stdin"

    packs_dir = _web_relay_state_dir(repo) / "packs"
    known_packs: set[str] = set()
    unapplied_packs: set[str] = set()
    if packs_dir.is_dir():
        for pf in packs_dir.glob("*.json"):
            known_packs.add(pf.stem)
            try:
                pmeta = json.loads(pf.read_text(encoding="utf-8", errors="replace"))
                if not pmeta.get("applied_at"):
                    unapplied_packs.add(pf.stem)
            except (OSError, ValueError):
                unapplied_packs.add(pf.stem)

    clip_fallback: dict[str, Any] | None = None
    clip_txt = _read_clipboard_text()
    if clip_txt:
        parsed = _extract_merge_json_from_text(clip_txt)
        if parsed:
            cpid = str(parsed.get("pack_id") or "")
            if not known_packs or cpid in known_packs:
                return parsed, "clipboard"
            clip_fallback = parsed

    candidates: list[tuple[int, float, dict[str, Any], Path]] = []
    for dl_dir in _default_downloads_dirs():
        for cand in dl_dir.iterdir():
            if not cand.is_file():
                continue
            if cand.suffix.lower() not in {".json", ".md", ".txt", ".zip"}:
                continue
            try:
                if cand.stat().st_size > 20 * 1024 * 1024:
                    continue
            except OSError:
                continue
            try:
                if cand.suffix.lower() == ".zip":
                    import zipfile
                    with zipfile.ZipFile(cand, "r") as zf:
                        for zn in zf.namelist():
                            if zn.endswith(".json"):
                                doc = _extract_merge_json_from_text(zf.read(zn).decode("utf-8", errors="replace"))
                                dpid = str((doc or {}).get("pack_id") or "")
                                if doc and dpid in known_packs:
                                    candidates.append((1 if dpid in unapplied_packs else 0, cand.stat().st_mtime, doc, cand))
                else:
                    doc = _extract_merge_json_from_text(cand.read_text(encoding="utf-8", errors="replace"))
                    dpid = str((doc or {}).get("pack_id") or "")
                    if doc and dpid in known_packs:
                        candidates.append((1 if dpid in unapplied_packs else 0, cand.stat().st_mtime, doc, cand))
            except OSError:
                continue
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, best_doc, best_path = candidates[0]
        return best_doc, f"downloads:{best_path}"

    if clip_fallback is not None:
        return clip_fallback, "clipboard"

    raise ValidationError(
        f"WEB_MERGE_PAYLOAD_NOT_FOUND: No `{WEB_MERGE_SCHEMA}` JSON found in Clipboard or Downloads. "
        "Copy the JSON block from Gemini Web (or click Download on `harness-merge-*.json`) and re-run `web-apply`."
    )


def _validate_code_integrity(rel_path: str, new_text: str, base_text: str = "") -> None:
    m_conf = CONFLICT_MARKER_RE.search(new_text)
    if m_conf:
        raise ValidationError(
            f"UNRESOLVED_CONFLICT_MARKERS_BLOCKED on '{rel_path}': leftover Git conflict marker `{m_conf.group(0).strip()}` detected."
        )
    m_trunc = LAZY_TRUNCATION_RE.search(new_text)
    if m_trunc:
        raise ValidationError(
            f"LAZY_TRUNCATION_BLOCKED on '{rel_path}': detected placeholder `{m_trunc.group(0).strip()}`. "
            "Gemini Web must return exact `hunks` (`search`/`replace`) or complete untruncated code."
        )
    if base_text:
        old_lines = len(base_text.splitlines())
        new_lines = len(new_text.splitlines())
        if old_lines >= 80 and new_lines < int(old_lines * 0.35):
            raise ValidationError(
                f"SUSPICIOUS_CONTENT_DROP_BLOCKED on '{rel_path}': line count dropped from {old_lines} to {new_lines} (>65% wipe). "
                "Use surgical `hunks` or pass explicit deletion if intentional."
            )
    if rel_path.endswith((".kt", ".java", ".swift")):
        stripped = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', "", new_text, flags=re.DOTALL)
        opens = stripped.count("{")
        closes = stripped.count("}")
        if opens != closes:
            raise ValidationError(
                f"UNBALANCED_BRACES_BLOCKED on '{rel_path}': `{opens}` '{{' vs `{closes}` '}}' after applying web changes."
            )


def _apply_hunks(rel_path: str, base_text: str, hunks: list[dict[str, Any]]) -> str:
    cur = base_text.replace("\r\n", "\n").replace("\r", "\n")
    for idx, h in enumerate(hunks, 1):
        if not isinstance(h, dict):
            raise ValidationError(f"Invalid hunk #{idx} on '{rel_path}': each hunk must be an object.")
        s_raw = h.get("search") if "search" in h else (h.get("find") if "find" in h else h.get("old"))
        r_raw = h.get("replace") if "replace" in h else h.get("new")
        if s_raw is None or r_raw is None:
            raise ValidationError(f"Invalid hunk #{idx} on '{rel_path}': each hunk requires 'search' and 'replace'.")
        s_txt = str(s_raw).replace("\r\n", "\n").replace("\r", "\n")
        r_txt = str(r_raw).replace("\r\n", "\n").replace("\r", "\n")
        if not s_txt:
            raise ValidationError(f"Empty 'search' string in hunk #{idx} on '{rel_path}'.")
        if s_txt in cur:
            count = cur.count(s_txt)
            if count > 1 and not h.get("replace_all"):
                raise ValidationError(
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
        raise ValidationError(
            f"HUNK_SEARCH_NOT_FOUND on '{rel_path}' hunk #{idx}: target snippet was not found in base file."
        )
    return cur


def _three_way_merge_if_needed(repo: Path, rel_path: str, current_disk: str, base_text: str, target_text: str) -> str:
    cur_norm = current_disk.replace("\r\n", "\n").replace("\r", "\n")
    base_norm = base_text.replace("\r\n", "\n").replace("\r", "\n")
    tgt_norm = target_text.replace("\r\n", "\n").replace("\r", "\n")
    if _sha256_lf(cur_norm) == _sha256_lf(base_norm) or cur_norm == tgt_norm:
        return tgt_norm
    with tempfile.TemporaryDirectory(prefix="web_3way_") as td:
        td_p = Path(td)
        f_cur = td_p / "current"
        f_base = td_p / "base"
        f_tgt = td_p / "web"
        f_cur.write_text(cur_norm, encoding="utf-8")
        f_base.write_text(base_norm, encoding="utf-8")
        f_tgt.write_text(tgt_norm, encoding="utf-8")
        proc = subprocess.run(
            ["git", "merge-file", "-p", str(f_cur), str(f_base), str(f_tgt)],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0 or "<<<<<<<" in (proc.stdout or ""):
            raise ValidationError(
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
) -> dict[str, Any]:
    eff_source = str(source or "").strip().lower()
    eff_proof = str(proof_reference or "").strip()
    if not dry_run:
        if eff_source not in {"conversation", "developer_terminal", "host_native"}:
            raise ValidationError(
                "WEB_APPLY_AUTHORITY_REQUIRED: Pass `--source conversation --proof-reference \"<developer phrase>\"` "
                "(or `--source developer_terminal` when run directly by the developer, or `--dry-run` for a read-only preview)."
            )
        if eff_source == "conversation" and not eff_proof:
            raise ValidationError("WEB_APPLY_PROOF_REQUIRED: `--proof-reference` with the developer's explicit instruction is required.")
        if eff_source == "developer_terminal" and not eff_proof:
            eff_proof = "developer_terminal_web_apply"

    # Handle applying pre-staged phase operations (`p2..pN`) on an active multi-phase task
    if staged_phase:
        from mutation_guard import active_plan
        plan_doc = active_plan(repo)
        tid = str(plan_doc.get("task_id") or "")
        phases = plan_doc.get("phases") or []
        p_idx = int(plan_doc.get("active_phase_index") or 0)
        if not phases or p_idx >= len(phases):
            raise ValidationError("No active phase found on current plan for `--staged-phase`.")
        pid = str(phases[p_idx].get("id") or "")
        staged_f = task_dir(repo, tid) / "staged-web-phases" / f"{pid}.json"
        if not staged_f.is_file():
            raise ValidationError(f"No staged web-relay operations found for phase '{pid}'.")
        staged_doc = read_json(staged_f)
        if isinstance(staged_doc, dict) and staged_doc.get("staged_sha256"):
            expected_st_sha = canonical_sha256({
                "task_id": str(staged_doc.get("task_id") or tid),
                "phase_id": str(staged_doc.get("phase_id") or pid),
                "writes": list(staged_doc.get("writes") or []),
                "deletes": list(staged_doc.get("deletes") or []),
            })
            if staged_doc.get("staged_sha256") != expected_st_sha:
                raise ValidationError(f"STAGED_PHASE_TAMPERED: Staged Web-Relay payload for phase '{pid}' failed SHA-256 verification.")
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
            dst.write_bytes(_apply_eol(wr["content"], wr.get("eol") or "lf"))
        for dl in staged_doc.get("deletes") or []:
            (repo / dl).unlink(missing_ok=True)
        staged_f.unlink(missing_ok=True)
        gate_env = {**os.environ, "HARNESS_REPO": str(repo), "PYTHONIOENCODING": "utf-8"}
        lint_script = (repo / ".agents" / "scripts" / "fast_kt_lint.py") if (repo / ".agents" / "scripts" / "fast_kt_lint.py").is_file() else (SCRIPTS_DIR / "fast_kt_lint.py")
        str_script = (repo / ".agents" / "scripts" / "check_strings.py") if (repo / ".agents" / "scripts" / "check_strings.py").is_file() else (SCRIPTS_DIR / "check_strings.py")
        st_lint_proc = subprocess.run([sys.executable, str(lint_script)], cwd=repo, env=gate_env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        st_str_proc = subprocess.run([sys.executable, str(str_script)], cwd=repo, env=gate_env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        st_lint_ok = st_lint_proc.returncode == 0
        st_str_ok = st_str_proc.returncode == 0
        try:
            from delivery_manifest import build_task_manifest, load_task_baseline
            st_manifest = build_task_manifest(repo, load_task_baseline(repo, tid), expected_files=plan_doc.get("expected_files"))
            atomic_write_json(task_dir(repo, tid) / "web-relay-receipt.json", {
                "schema_version": 1,
                "pack_id": f"staged-{pid}",
                "task_id": tid,
                "origin": f"staged-phase:{pid}",
                "applied_at": utc_now(),
                "change_set_sha256": str(st_manifest.get("change_set_sha256") or ""),
                "files_written": [w["path"] for w in staged_doc.get("writes") or []],
                "files_deleted": list(staged_doc.get("deletes") or []),
                "fast_kt_lint_ok": st_lint_ok,
                "check_strings_ok": st_str_ok,
            })
        except (ImportError, OSError, ValueError, ValidationError):
            st_manifest = {}
        return {
            "status": "APPLIED_STAGED_PHASE",
            "task_id": tid,
            "phase_id": pid,
            "files_written": [w["path"] for w in staged_doc.get("writes") or []],
            "fast_kt_lint_ok": st_lint_ok,
            "check_strings_ok": st_str_ok,
        }

    payload, payload_origin = _resolve_incoming_merge_payload(repo, merge_file, use_stdin)
    pack_id = str(payload.get("pack_id") or "").strip()
    if not pack_id or not re.fullmatch(r"wpack-[a-f0-9]{12}", pack_id):
        raise ValidationError(f"Invalid or missing `pack_id` in `{WEB_MERGE_SCHEMA}` payload: '{pack_id}'.")

    pack_path = _web_relay_state_dir(repo) / "packs" / f"{pack_id}.json"
    if not pack_path.is_file():
        raise ValidationError(
            f"PACK_REPO_MISMATCH: Pack `{pack_id}` does not belong to this repository (`{repo.name}`) or was not generated here."
        )
    pack_doc = read_json(pack_path)
    if pack_doc.get("repo_fingerprint") != repository_identity(repo):
        raise ValidationError(f"PACK_REPO_MISMATCH: Pack `{pack_id}` fingerprint does not match repository `{repo.name}`.")
    if pack_doc.get("applied") and not allow_reapply:
        raise ValidationError(f"PACK_ALREADY_APPLIED: Pack `{pack_id}` was already applied. Pass `--allow-reapply` only if intentional.")

    # Check active task alignment (`Safeguard #7`)
    active_doc: dict[str, Any] | None = None
    try:
        from mutation_guard import active_plan
        active_doc = active_plan(repo, allow_missing=True)
    except (ImportError, OSError, ValueError, ValidationError):
        active_doc = None
    if active_doc and active_doc.get("task_id") and str(active_doc.get("status") or "") not in {"", "DELIVERED", "CANCELLED"}:
        act_tid = str(active_doc.get("task_id") or "")
        pack_tid = str(pack_doc.get("task_id") or "")
        if pack_tid and act_tid and pack_tid != act_tid:
            raise ValidationError(
                f"ACTIVE_TASK_MISMATCH: Pack `{pack_id}` belongs to task `{pack_tid}`, while focused active task is `{act_tid}`."
            )

    # Short-circuit `NEED_FILES` expansion (`Scenario 4A`)
    raw_need_files = payload.get("need_files") or payload.get("needed_files") or []
    if str(payload.get("status") or "").upper() == "NEED_FILES" or raw_need_files:
        req_files = [str(f) for f in raw_need_files if str(f).strip()]
        if not req_files:
            raise ValidationError("`NEED_FILES` status received with empty `need_files` list.")
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
        for rf in req_files:
            try:
                nr = _norm_rel(repo, rf)
                if nr not in norm_req:
                    norm_req.append(nr)
            except ValidationError:
                if rf not in norm_req:
                    norm_req.append(rf)
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
        expanded = build_web_pack(
            repo,
            task_id=str(pack_doc.get("task_id") or ""),
            prompt=str(pack_doc.get("prompt") or ""),
            kind=str(pack_doc.get("kind") or ""),
            files=merged_active_files,
            add_files=norm_req,
            no_clipboard=(os.environ.get("HARNESS_NO_CLIPBOARD") == "1"),
            batch_size=max(len(merged_active_files), int(pack_doc.get("batch_size") or DEFAULT_WEB_PACK_BATCH_SIZE)),
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
        raise ValidationError("Merge payload contains no `operations` to apply.")

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
            raise ValidationError(f"Operation #{idx} must be an object.")
        action = str(op.get("action") or op.get("op") or "MODIFY").strip().upper()
        if action not in {"MODIFY", "CREATE", "DELETE", "RENAME"}:
            raise ValidationError(f"Unsupported operation action '{action}' in operation #{idx}.")
        rel_path = _norm_rel(repo, str(op.get("path") or op.get("file") or ""))
        blocked, b_msg = _is_protected_or_secret_path(rel_path)
        if blocked:
            raise ValidationError(b_msg)

        if action == "DELETE":
            if rel_path not in editable_files:
                raise ValidationError(f"UNSCOPED_DELETE_BLOCKED: Cannot delete '{rel_path}' because it was not in `EDITABLE_FILES` of pack `{pack_id}`.")
            planned_deletes.append(rel_path)
            _reg_scope(rel_path)
            continue

        if action == "RENAME":
            old_rel = _norm_rel(repo, str(op.get("old_path") or ""))
            b_old, b_old_msg = _is_protected_or_secret_path(old_rel)
            if b_old:
                raise ValidationError(b_old_msg)
            if old_rel not in editable_files:
                raise ValidationError(f"UNSCOPED_RENAME_BLOCKED: '{old_rel}' was not in `EDITABLE_FILES` of pack `{pack_id}`.")
            base_meta = editable_files[old_rel]
            base_txt = str(base_meta.get("base_text") or "")
            eol = str(base_meta.get("eol") or "lf")
            if op.get("hunks"):
                raw_new = _apply_hunks(old_rel, base_txt, list(op["hunks"]))
            elif "content" in op:
                raw_new = str(op["content"])
            else:
                raw_new = base_txt
            restored = _restore_inline_secrets(raw_new, vault)
            _validate_code_integrity(rel_path, restored, base_txt)
            planned_deletes.append(old_rel)
            planned_writes.append({"path": rel_path, "content": restored, "eol": eol, "is_test": is_kmp_or_android_test_path(rel_path)})
            _reg_scope(old_rel)
            _reg_scope(rel_path)
            continue

        disk_f = repo / rel_path
        if action == "CREATE" and not disk_f.exists():
            if "content" not in op:
                raise ValidationError(f"CREATE operation on '{rel_path}' requires 'content'.")
            restored = _restore_inline_secrets(str(op["content"]), vault)
            _validate_code_integrity(rel_path, restored, "")
            default_eol = "crlf" if any(m.get("eol") == "crlf" for m in editable_files.values()) else "lf"
            planned_writes.append({"path": rel_path, "content": restored, "eol": default_eol, "is_test": is_kmp_or_android_test_path(rel_path)})
            _reg_scope(rel_path)
            continue

        # MODIFY (or CREATE on a file that was already in editable_files / exists)
        if disk_f.exists() and rel_path not in editable_files:
            if not op.get("hunks"):
                raise ValidationError(
                    f"UNSCOPED_EXISTING_FILE_OVERWRITE_BLOCKED: Existing file '{rel_path}' was NOT included in `EDITABLE_FILES` of pack `{pack_id}`. "
                    "Use surgical `hunks` (`search`/`replace`) or return `NEED_FILES` to load its full source before replacing whole-file `content`."
                )
            # Safe surgical `hunks` on an existing non-secret repo file (e.g. neighbor interface/caller): verify directly against live disk!
            live_b = disk_f.read_bytes()
            if _is_binary_asset(rel_path, live_b):
                raise ValidationError(f"BINARY_FILE_TEXT_EDIT_BLOCKED: Cannot apply text hunks to binary asset '{rel_path}'.")
            live_eol = _detect_eol(live_b)
            live_txt = live_b.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            _redact_inline_secrets(live_txt, vault)
            base_meta = {"exists": True, "sha256": _sha256_lf(live_txt), "eol": live_eol, "base_text": live_txt}
        else:
            base_meta = editable_files.get(rel_path) or {"base_text": "", "eol": "lf"}
        base_txt = str(base_meta.get("base_text") or "")
        cur_disk_bytes = disk_f.read_bytes() if disk_f.is_file() else b""
        eol = _detect_eol(cur_disk_bytes) if cur_disk_bytes else str(base_meta.get("eol") or "lf")
        cur_disk_txt = cur_disk_bytes.decode("utf-8", errors="replace") if cur_disk_bytes else ""

        if op.get("hunks"):
            web_target_redacted = _apply_hunks(rel_path, _redact_inline_secrets(base_txt, dict(vault)), list(op["hunks"]))
            web_target = _restore_inline_secrets(web_target_redacted, vault)
        elif "content" in op:
            web_target = _restore_inline_secrets(str(op["content"]), vault)
        else:
            raise ValidationError(f"MODIFY operation on '{rel_path}' requires 'hunks' or 'content'.")

        _validate_code_integrity(rel_path, web_target, base_txt)
        merged_txt = _three_way_merge_if_needed(repo, rel_path, cur_disk_txt, base_txt, web_target) if disk_f.is_file() else web_target
        planned_writes.append({"path": rel_path, "content": merged_txt, "eol": eol, "is_test": is_kmp_or_android_test_path(rel_path)})
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
            was_3way = bool(existed and b_meta.get("base_text") is not None and _sha256_lf(before_txt) != _sha256_lf(str(b_meta.get("base_text") or "")))
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
                if re.search(r"^\s*import\s+[A-Za-z0-9_.]+\.\*\s*$", after_txt, re.MULTILINE):
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
        tid = validate_id(
            str(plan_spec.get("task_id") or pack_doc.get("suggested_task_id") or f"web-{pack_id[-6:]}"),
            "task_id",
        )
        t_kind = _infer_task_kind(str(plan_spec.get("outcome") or payload.get("summary") or pack_doc.get("prompt") or ""), str(plan_spec.get("kind") or payload.get("task_kind") or pack_doc.get("kind") or "FEATURE"))
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
        impl_paths = [p for p in cold_expected if Path(p).suffix.lower() not in doc_res_sfx and not is_kmp_or_android_test_path(p)]
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
                facts_doc = read_json(facts_f) if facts_f.is_file() else {}
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
            except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
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

        draft_ns = argparse.Namespace(
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
        plan_doc = read_json(task_dir(repo, tid) / "plan.json")
        approve_ns = argparse.Namespace(
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
        except (ImportError, OSError, ValueError, ValidationError):
            bind_pending_execution_mode_to_task = None
        active_doc = read_json(task_dir(repo, tid) / "plan.json")
    else:
        tid = str(active_doc.get("task_id") or "")
        st_cur = str(active_doc.get("status") or "").upper()
        import contextlib, io
        if st_cur in {"PLAN_DRAFTED", "AWAITING_DEVELOPER_APPROVAL"}:
            # Revise scope if needed before approving
            cur_exp = set(active_doc.get("expected_files") or [])
            merged_exp = sorted(cur_exp | set(all_scope_paths))
            if set(merged_exp) != cur_exp:
                rev_ns = argparse.Namespace(
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
                active_doc = read_json(task_dir(repo, tid) / "plan.json")
            app_ns = argparse.Namespace(
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
            active_doc = read_json(task_dir(repo, tid) / "plan.json")
        elif st_cur == "APPROVED":
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                wf.begin(argparse.Namespace(repo=str(repo), task_id=tid, json=True))
            active_doc = read_json(task_dir(repo, tid) / "plan.json")
        elif st_cur in {"VERIFYING", "BLOCKED", "READY_FOR_DELIVERY"}:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                wf.resume(argparse.Namespace(repo=str(repo), task_id=tid, reopen=(st_cur == "READY_FOR_DELIVERY"), json=True))
            active_doc = read_json(task_dir(repo, tid) / "plan.json")

        # Extend expected_files via canonical `wf.revise` + `wf.record_approval` so `plan_sha256` and `approval.plan_sha256` stay cryptographically aligned!
        cur_exp_list = list(active_doc.get("expected_files") or [])
        missing_exp = [p for p in all_scope_paths if p not in cur_exp_list]
        if missing_exp:
            merged_mid_exp = sorted(set(cur_exp_list) | set(missing_exp))
            phases_l = [dict(ph) for ph in (active_doc.get("phases") or []) if isinstance(ph, dict)]
            p_i = int(active_doc.get("active_phase_index") or 0)
            if not phases_l and str(active_doc.get("task_kind") or "").upper() != "CONFLICT":
                doc_sfx_m = {".md", ".txt", ".rst", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".xml", ".json", ".properties", ".pro", ".ico"}
                impl_mid = [p for p in merged_mid_exp if Path(p).suffix.lower() not in doc_sfx_m and not is_kmp_or_android_test_path(p)]
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
            rev_mid_ns = argparse.Namespace(
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
            revised_doc = read_json(task_dir(repo, tid) / "plan.json")
            app_mid_ns = argparse.Namespace(
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
            active_doc = read_json(task_dir(repo, tid) / "plan.json")

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
            title_mods = set(re.findall(r":[A-Za-z0-9_.:-]+", str(ph_obj.get("title") or "")))
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
            st_dir = task_dir(repo, tid) / "staged-web-phases"
            st_dir.mkdir(parents=True, exist_ok=True)
            st_file = st_dir / f"{f_pid}.json"
            if st_file.is_file():
                try:
                    prev_b = read_json(st_file)
                    if isinstance(prev_b, dict):
                        new_w_paths = {x["path"] for x in bucket["writes"]}
                        merged_w = [
                            x for x in (prev_b.get("writes") or [])
                            if isinstance(x, dict) and x.get("path") not in new_w_paths
                        ] + bucket["writes"]
                        merged_d = sorted((set(prev_b.get("deletes") or []) - new_w_paths) | set(bucket["deletes"]))
                        bucket = {"writes": merged_w, "deletes": merged_d}
                except (OSError, ValueError, ValidationError):
                    pass
            bucket = {
                "task_id": tid,
                "phase_id": f_pid,
                "writes": list(bucket.get("writes") or []),
                "deletes": list(bucket.get("deletes") or []),
            }
            bucket["staged_sha256"] = canonical_sha256({
                "task_id": tid,
                "phase_id": f_pid,
                "writes": bucket["writes"],
                "deletes": bucket["deletes"],
            })
            atomic_write_json(st_file, bucket)
            staged_phases_summary[f_pid] = [x["path"] for x in bucket["writes"]] + list(bucket["deletes"])
        active_writes = filtered_w
        active_deletes = filtered_d

    # Phase 4: Automatic `BUG` `RED -> GREEN` 2-Step Apply (`Collision #2`)
    tdir = task_dir(repo, tid)
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
            dst.write_bytes(_apply_eol(tw["content"], tw["eol"]))
        gate_env = {**os.environ, "HARNESS_REPO": str(repo), "PYTHONIOENCODING": "utf-8"}
        tests_script = (repo / ".agents" / "scripts" / "run_tests_gate.py") if (repo / ".agents" / "scripts" / "run_tests_gate.py").is_file() else (SCRIPTS_DIR / "run_tests_gate.py")
        proc_red = subprocess.run(
            [sys.executable, str(tests_script), "--capture-red"],
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
        dst.write_bytes(_apply_eol(w["content"], w["eol"]))
    for d_path in active_deletes:
        (repo / d_path).unlink(missing_ok=True)

    # Mark pack consumed (`Safeguard #7`) — or keep open for continuation when `status == "PARTIAL"`!
    is_partial_reply = str(payload.get("status") or "").strip().upper() in {"PARTIAL", "PARTIAL_BATCH", "CONTINUE"}
    if is_partial_reply:
        pack_doc["applied"] = False
        pack_doc["partial_batches_applied"] = int(pack_doc.get("partial_batches_applied") or 0) + 1
        pack_doc["last_partial_applied_at"] = utc_now()
        pack_doc["task_id"] = tid
        atomic_write_json(tdir / "latest-web-pack.json", {
            "pack_id": pack_id,
            "task_id": tid,
            "bundle_file": str(pack_doc.get("bundle_file") or ""),
            "created_at": str(pack_doc.get("created_at") or utc_now()),
        })
        # Refresh base_text/sha256 of modified files so subsequent continuation hunks apply cleanly
        ed_map = dict(pack_doc.get("editable_files") or {})
        for w in active_writes:
            w_norm = w["content"].replace("\r\n", "\n").replace("\r", "\n")
            ed_map[w["path"]] = {"exists": True, "sha256": _sha256_lf(w_norm), "eol": w["eol"], "base_text": w_norm}
        for d_p in active_deletes:
            ed_map.pop(d_p, None)
        pack_doc["editable_files"] = ed_map
    else:
        pack_doc["applied"] = True
        pack_doc["applied_at"] = utc_now()
        pack_doc["applied_task_id"] = tid
    atomic_write_json(pack_path, pack_doc)

    # Surface & Sensitive-Surface Check (`Safeguard #6`)
    detected_surfaces: list[str] = []
    sensitive_surfaces: list[str] = []
    t_manifest = {}
    try:
        from delivery_manifest import build_task_manifest, load_task_baseline
        t_manifest = build_task_manifest(repo, load_task_baseline(repo, tid), expected_files=active_doc.get("expected_files"))
    except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
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
            import contextlib, io
            merged_surfs = sorted(planned_surfs | set(detected_surfaces))
            arch_c = active_doc.get("architecture_contract") or {}
            rev_surf_ns = argparse.Namespace(
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
            rev_s_doc = read_json(task_dir(repo, tid) / "plan.json")
            app_surf_ns = argparse.Namespace(
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
            active_doc = read_json(task_dir(repo, tid) / "plan.json")
    except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
        pass

    # Run fast zero-token static checks (`fast_kt_lint` + `check_strings`) & write `Zero Re-Read` receipt (`Collision #6`)
    gate_env = {**os.environ, "HARNESS_REPO": str(repo), "PYTHONIOENCODING": "utf-8"}
    lint_script = (repo / ".agents" / "scripts" / "fast_kt_lint.py") if (repo / ".agents" / "scripts" / "fast_kt_lint.py").is_file() else (SCRIPTS_DIR / "fast_kt_lint.py")
    str_script = (repo / ".agents" / "scripts" / "check_strings.py") if (repo / ".agents" / "scripts" / "check_strings.py").is_file() else (SCRIPTS_DIR / "check_strings.py")
    lint_proc = subprocess.run(
        [sys.executable, str(lint_script)],
        cwd=repo,
        env=gate_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    str_proc = subprocess.run(
        [sys.executable, str(str_script)],
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
        next_batch_pack_info = build_web_pack(
            repo,
            task_id=tid,
            prompt=str(pack_doc.get("prompt") or ""),
            kind=str(pack_doc.get("kind") or ""),
            files=next_batch_files,
            no_clipboard=(os.environ.get("HARNESS_NO_CLIPBOARD") == "1"),
            batch_size=int(pack_doc.get("batch_size") or DEFAULT_WEB_PACK_BATCH_SIZE),
            batch_index=next_b_idx,
            total_batches_hint=tot_b,
            remaining_batches_override=rest_batches,
        )

    prev_written: list[str] = []
    prev_deleted: list[str] = []
    prev_rec_f = tdir / "web-relay-receipt.json"
    if prev_rec_f.is_file():
        try:
            pr_doc = read_json(prev_rec_f)
            if isinstance(pr_doc, dict) and str(pr_doc.get("task_id") or "") == tid:
                prev_written = [str(x) for x in (pr_doc.get("files_written") or []) if str(x).strip()]
                prev_deleted = [str(x) for x in (pr_doc.get("files_deleted") or []) if str(x).strip()]
        except (OSError, ValueError, ValidationError):
            pass

    cum_written = list(dict.fromkeys([*prev_written, *(w["path"] for w in active_writes)]))
    cum_deleted = list(dict.fromkeys([*(x for x in prev_deleted if x not in cum_written), *active_deletes]))
    receipt_doc = {
        "schema_version": 1,
        "pack_id": pack_id,
        "task_id": tid,
        "origin": payload_origin,
        "applied_at": utc_now(),
        "change_set_sha256": str((t_manifest or {}).get("change_set_sha256") or ""),
        "files_written": cum_written,
        "files_deleted": cum_deleted,
        "incomplete_continuation": bool(is_partial_reply or next_batch_pack_info is not None),
        "fast_kt_lint_ok": lint_proc.returncode == 0,
        "check_strings_ok": str_proc.returncode == 0,
    }
    atomic_write_json(prev_rec_f, receipt_doc)

    # Transition any unresolved `worker-handoff.json` capsule to RESOLVED so Lead/router know Web-Relay took over cleanly
    hf_file = tdir / "worker-handoff.json"
    if hf_file.is_file():
        try:
            hf_data = read_json(hf_file)
            if str(hf_data.get("status") or "").upper() not in {"RESOLVED", "CLEARED"}:
                hf_data["status"] = "RESOLVED"
                hf_data["resolved_by"] = "web_relay"
                hf_data["resolved_pack_id"] = pack_id
                hf_data["resolved_at"] = receipt_doc["applied_at"]
                atomic_write_json(hf_file, hf_data)
        except (OSError, ValueError, ValidationError):
            pass

    phases_now = active_doc.get("phases") or []
    p_idx_now = int(active_doc.get("active_phase_index") or 0)
    if is_partial_reply:
        next_cmd = 'Ask Gemini Web `Continue remaining files for this pack_id` and run `python .agents/harness.py web-apply --source conversation --proof-reference "<words>"`.'
    elif next_batch_pack_info is not None:
        next_cmd = (
            f"Batch {next_batch_pack_info['batch_index']}/{next_batch_pack_info['total_batches']} "
            f"(`{next_batch_pack_info['pack_id']}`) is now copied to Clipboard — paste into Gemini Web and run `web-apply`."
        )
    elif phases_now and 0 <= p_idx_now < len(phases_now):
        cur_pid = str(phases_now[p_idx_now].get("id") or "p1")
        next_cmd = f"python .agents/harness.py verify-steps --task-id {tid} --host antigravity  # (checkpoints {cur_pid} & runs verification gates)"
    else:
        next_cmd = f"python .agents/harness.py verify-steps --task-id {tid} --host antigravity"

    return {
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


def get_web_relay_status(repo: Path) -> dict[str, Any]:
    st_dir = _web_relay_state_dir(repo)
    latest_f = st_dir / "latest-pack.json"
    latest = read_json(latest_f) if latest_f.is_file() else None
    packs_count = len(list((st_dir / "packs").glob("*.json"))) if (st_dir / "packs").is_dir() else 0
    return {
        "status": "OK",
        "mode": "on_demand_stateless_relay",
        "default_antigravity_mode_intact": True,
        "packs_recorded": packs_count,
        "latest_pack": latest,
        "outbox_dir": str(_default_outbox_dir()),
    }


def main(argv: list[str] | None = None) -> int:
    configure_utf8_output()
    default_repo = os.environ.get("HARNESS_REPO") or "."
    parser = argparse.ArgumentParser(description="Optional Manual Web-Relay Bridge (`web-pack` / `web-apply`).")
    parser.add_argument("--repo", dest="top_repo", default=None, help="Android/KMP project root.")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_pack = sub.add_parser("pack", help="Build an AST-scoped, secret-scrubbed Context Pack for Gemini Web and copy to Clipboard.")
    p_pack.add_argument("--repo", default=None, help="Android/KMP project root.")
    p_pack.add_argument("--task-id", default="", help="Optional active task ID.")
    p_pack.add_argument("--prompt", default="", help="Task goal or bug description.")
    p_pack.add_argument("--kind", default="", choices=("", "FEATURE", "BUG", "REFACTOR", "CONFLICT"), help="Optional task kind override.")
    p_pack.add_argument("--file", "--files", dest="file", action="append", default=[], help="Explicit scope file(s); repeatable or comma-separated.")
    p_pack.add_argument("--dirty", "--from-git-dirty", dest="dirty", action="store_true", help="Include modified, staged, and untracked source/resource files from Git working tree.")
    p_pack.add_argument("--allow-conflict-pack", action="store_true", help="Allow packing files containing Git conflict markers.")
    p_pack.add_argument("--add-files", action="append", default=[], help="Expand most recent pack with additional requested file(s).")
    p_pack.add_argument("--feature", default="", help="Feature query for AST scope discovery.")
    p_pack.add_argument("--symbol", default="", help="Symbol query for AST scope discovery.")
    p_pack.add_argument("--retry", action="store_true", help="Emit compact retry delta with local gate/JUnit diagnostics.")
    p_pack.add_argument("--batch-size", type=int, default=DEFAULT_WEB_PACK_BATCH_SIZE, help="Max editable text files per batch before auto-sharding (default: 40).")
    p_pack.add_argument("--all-in-one", action="store_true", help="Pack all resolved files into a single Context Pack without batch sharding.")
    p_pack.add_argument("--no-clipboard", action="store_true", help="Write pack file without modifying system clipboard.")
    p_pack.add_argument("--json", action="store_true", help="Emit pure JSON output.")

    p_apply = sub.add_parser("apply", help="Apply a `HARNESS_WEB_MERGE_V1` payload from Clipboard, Downloads, or `--file` safely.")
    p_apply.add_argument("--repo", default=None, help="Android/KMP project root.")
    p_apply.add_argument("--file", default="", help="Explicit path to `harness-merge-*.json` / `.md` / `.zip`.")
    p_apply.add_argument("--stdin", action="store_true", help="Read merge payload from stdin.")
    p_apply.add_argument("--source", default="", choices=("", "conversation", "developer_terminal", "host_native"), help="Approval authority source (optional when `--dry-run` is passed).")
    p_apply.add_argument("--dry-run", action="store_true", help="Validate hunks, braces, 3-way merges, and line stats in memory without modifying files or consuming `pack_id`.")
    p_apply.add_argument("--proof-reference", default="", help="Exact developer instruction authorizing applying Web-Relay changes.")
    p_apply.add_argument("--allow-reapply", action="store_true", help="Allow re-applying an already consumed `pack_id`.")
    p_apply.add_argument("--approve-sensitive", action="store_true", help="Also record sensitive surface approval when T5 surfaces are present.")
    p_apply.add_argument("--staged-phase", action="store_true", help="Apply pre-staged operations for the newly activated phase (`p2..pN`).")
    p_apply.add_argument("--no-auto-red", action="store_true", help="Skip automatic 2-step `RED -> GREEN` test staging on BUG tasks.")
    p_apply.add_argument("--json", action="store_true", help="Emit pure JSON output.")

    p_status = sub.add_parser("status", help="Inspect Web-Relay outbox and latest pack status.")
    p_status.add_argument("--repo", default=None, help="Android/KMP project root.")
    p_status.add_argument("--json", action="store_true", help="Emit pure JSON output.")

    ns = parser.parse_args(argv)
    repo = Path(ns.repo or ns.top_repo or default_repo).resolve()

    try:
        if ns.subcommand == "pack":
            res = build_web_pack(
                repo,
                task_id=ns.task_id,
                prompt=ns.prompt,
                kind=ns.kind,
                files=ns.file,
                add_files=ns.add_files,
                feature=ns.feature,
                symbol=ns.symbol,
                retry=ns.retry,
                no_clipboard=ns.no_clipboard,
                allow_conflict_pack=ns.allow_conflict_pack,
                include_dirty=ns.dirty,
                batch_size=ns.batch_size,
                all_in_one=ns.all_in_one,
            )
            if ns.json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
            else:
                clip_mode = (res.get("clipboard") or {}).get("mode", "none")
                print(
                    f"[WEB-PACK READY] pack_id={res['pack_id']} | files={len(res['editable_files'])} | "
                    f"neighbors={res['neighbor_signatures_count']} | size={res['bundle_bytes']:,} B | clipboard={clip_mode}\n"
                    f"  Bundle file: {res['bundle_file']}\n"
                    f"  Next: Paste (`Ctrl+V`) into Gemini Web (`Carbon`), then copy/download its reply and run `web-apply`."
                )
            return 0

        if ns.subcommand == "apply":
            res = apply_web_merge(
                repo,
                merge_file=ns.file,
                use_stdin=ns.stdin,
                source=ns.source,
                proof_reference=ns.proof_reference,
                allow_reapply=ns.allow_reapply,
                approve_sensitive=ns.approve_sensitive,
                staged_phase=ns.staged_phase,
                auto_red_green=not ns.no_auto_red,
                dry_run=ns.dry_run,
            )
            if ns.json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
            elif res.get("dry_run"):
                summ = res.get("summary") or {}
                print(
                    f"[WEB-APPLY DRY-RUN] status={res['status']} | pack_id={res.get('pack_id')} | "
                    f"writes={summ.get('files_to_write', 0)} | deletes={summ.get('files_to_delete', 0)} | "
                    f"+{summ.get('total_added_lines', 0)} / -{summ.get('total_deleted_lines', 0)} lines (0 files modified on disk)"
                )
            elif res.get("status") == "NEED_FILES_EXPANDED":
                np_info = res["new_pack"]
                print(
                    f"[WEB-PACK EXPANDED] Added requested files {res['added_files']} -> new pack_id={np_info['pack_id']} "
                    f"({np_info['bundle_bytes']:,} B, clipboard={np_info['clipboard'].get('mode')}). Paste into Gemini Web."
                )
            else:
                print(
                    f"[WEB-APPLY OK] task_id={res['task_id']} | origin={res['origin']} | "
                    f"written={len(res.get('files_written') or [])} | deleted={len(res.get('files_deleted') or [])}\n"
                    f"  Zero-token gates: fast_kt_lint={res.get('zero_token_gates', {}).get('fast_kt_lint')}, "
                    f"check_strings={res.get('zero_token_gates', {}).get('check_strings')}\n"
                    f"  Next: {res.get('next_recommended_command')}"
                )
            return 0

        res = get_web_relay_status(repo)
        if ns.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"[WEB-RELAY STATUS] mode={res['mode']} | packs={res['packs_recorded']} | outbox={res['outbox_dir']}")
        return 0
    except ValidationError as exc:
        if getattr(ns, "json", False):
            print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
