"""Optional Manual Web-Relay Mode (`web-pack` / `web-apply`) for Android Agent Harness.

Bridges local AST-scoped discovery & deterministic Gradle/EvidenceStore verification in
Antigravity with manual high-reasoning offload in any external AI web chat — with zero GitHub OAuth
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
import time
import uuid
from pathlib import Path

__file__ = str(Path(__file__).resolve().parents[1] / "web_relay.py")
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


def _recent_antigravity_user_uploaded_dirs() -> list[Path]:
    """Return recent Antigravity `.user_uploaded` attachment folders (newest first)."""
    explicit_up = os.environ.get("HARNESS_USER_UPLOADED_DIR", "").strip()
    if explicit_up:
        up_p = Path(explicit_up).expanduser().resolve()
        return [up_p] if up_p.is_dir() else []
    if any(
        os.environ.get(k, "").strip()
        for k in ("HARNESS_WEB_RELAY_DIR", "HARNESS_WEB_RELAY_OUTBOX", "HARNESS_WEB_RELAY_DOWNLOADS", "HARNESS_DOWNLOADS_DIR")
    ):
        return []
    roots: list[Path] = []
    ag_env = os.environ.get("ANTIGRAVITY_APP_DATA", "").strip()
    if ag_env:
        roots.append(Path(ag_env).expanduser() / "brain")
    try:
        roots.append(Path.home() / ".gemini" / "antigravity" / "brain")
    except (OSError, RuntimeError):
        pass
    found: list[tuple[float, Path]] = []
    now = time.time()
    for brain_root in roots:
        if not brain_root.is_dir():
            continue
        try:
            for conv_dir in brain_root.iterdir():
                up_dir = conv_dir / ".user_uploaded"
                if up_dir.is_dir():
                    mtime = up_dir.stat().st_mtime
                    if (now - mtime) <= 7200:
                        found.append((mtime, up_dir.resolve()))
        except OSError:
            continue
    found.sort(key=lambda item: item[0], reverse=True)
    out: list[Path] = []
    for _, d in found[:5]:
        if d not in out:
            out.append(d)
    return out


def _default_downloads_dirs() -> list[Path]:
    dirs: list[Path] = []
    for up_d in _recent_antigravity_user_uploaded_dirs():
        if up_d not in dirs:
            dirs.append(up_d)
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


DIRTY_SOURCE_SUFFIXES = frozenset({
    ".kt", ".java", ".xml", ".swift", ".kts", ".gradle", ".toml", ".sq", ".sqm", ".proto", ".graphql", ".graphqls", ".pro", ".json",
})


def get_web_relay_status(repo: Path, *, task_id: str = "") -> dict[str, Any]:
    st_dir = _web_relay_state_dir(repo)
    latest_f = st_dir / "latest-pack.json"
    if task_id and (state_root(repo) / "tasks" / task_id / "latest-web-pack.json").is_file():
        latest_f = state_root(repo) / "tasks" / task_id / "latest-web-pack.json"
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

    p_pack = sub.add_parser("pack", help="Build an AST-scoped, secret-scrubbed Context Pack for an external AI chat and copy to Clipboard.")
    p_pack.add_argument("--repo", default=None, help="Android/KMP project root.")
    p_pack.add_argument("--task-id", "--task", dest="task_id", default="", help="Optional active task ID.")
    p_pack.add_argument("--prompt", default="", help="Task goal or bug description.")
    p_pack.add_argument("--kind", default="", choices=("", "FEATURE", "BUG", "REFACTOR", "CONFLICT"), help="Optional task kind override.")
    p_pack.add_argument("--file", "--files", dest="file", action="append", default=[], help="Explicit scope file(s); repeatable or comma-separated.")
    p_pack.add_argument("--dirty", "--from-git-dirty", dest="dirty", action="store_true", help="Include modified, staged, and untracked source/resource files from Git working tree.")
    p_pack.add_argument("--allow-conflict-pack", action="store_true", help="Allow packing files containing Git conflict markers.")
    p_pack.add_argument("--add-files", action="append", default=[], help="Expand most recent pack with additional requested file(s).")
    p_pack.add_argument("--feature", default="", help="Feature query for AST scope discovery.")
    p_pack.add_argument("--symbol", default="", help="Symbol query for AST scope discovery.")
    p_pack.add_argument("--retry", action="store_true", help="Emit compact retry delta with local gate/JUnit diagnostics.")
    p_pack.add_argument(
        "--retry-failure",
        action="store_true",
        help="Emit ultra-compact failure-only delta (compiler/test/gate errors + surgical +-6-line excerpts, zero full-file re-upload) for the same external AI chat.",
    )
    p_pack.add_argument("--batch-size", type=int, default=DEFAULT_WEB_PACK_BATCH_SIZE, help="Max editable text files per batch before auto-sharding (default: 40).")
    p_pack.add_argument("--all-in-one", action="store_true", help="Pack all resolved files into a single Context Pack without batch sharding.")
    p_pack.add_argument("--no-clipboard", action="store_true", help="Write pack file without modifying system clipboard.")
    p_pack.add_argument("--json", action="store_true", help="Emit pure JSON output.")

    p_apply = sub.add_parser("apply", help="Apply a `HARNESS_WEB_MERGE_V1` payload from Clipboard, Downloads, or `--file` safely.")
    p_apply.add_argument("--repo", default=None, help="Android/KMP project root.")
    p_apply.add_argument("--task-id", "--task", dest="task_id", default="", help="Optional task ID hint.")
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
    p_status.add_argument("--task-id", "--task", dest="task_id", default="", help="Optional task ID hint.")
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
                retry_failure=ns.retry_failure,
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
                chat_step = (
                    "Open a NEW external AI chat"
                    if res.get("new_chat_recommended", True)
                    else "Stay in the SAME external AI chat"
                )
                compact_adv = (res.get("context_compact_advisory") or {}).get("advisory")
                compact_line = f"\n  [QUOTA SHIELD] {compact_adv}" if compact_adv else ""
                print(
                    f"[WEB-PACK READY] pack_id={res['pack_id']} | files={len(res['editable_files'])} | "
                    f"neighbors={res['neighbor_signatures_count']} | size={res['bundle_bytes']:,} B | clipboard={clip_mode}\n"
                    f"  Bundle file: {res['bundle_file']}\n"
                    f"  Next: {chat_step}, attach or paste (`Ctrl+V`), then copy/download its `HARNESS_WEB_MERGE_V1` reply and run `web-apply`."
                    f"{compact_line}"
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
                task_id=ns.task_id,
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
                    f"({np_info['bundle_bytes']:,} B, clipboard={np_info['clipboard'].get('mode')}). Stay in the SAME external AI chat and paste/attach the expanded pack."
                )
            else:
                kdoc_cli_block = ""
                if res.get("kdoc_advisories"):
                    kdoc_cli_block = "\n  KDoc reminders:\n    " + "\n    ".join(res["kdoc_advisories"][:8])
                if res.get("unused_advisories"):
                    kdoc_cli_block += "\n  Unused code reminders:\n    " + "\n    ".join(res["unused_advisories"][:8])
                print(
                    f"[WEB-APPLY OK] task_id={res['task_id']} | origin={res['origin']} | "
                    f"written={len(res.get('files_written') or [])} | deleted={len(res.get('files_deleted') or [])}\n"
                    f"  Zero-token gates: fast_kt_lint={res.get('zero_token_gates', {}).get('fast_kt_lint')}, "
                    f"check_strings={res.get('zero_token_gates', {}).get('check_strings')}"
                    f"{kdoc_cli_block}\n"
                    f"  Next: {res.get('next_recommended_command')}"
                )
            return 0

        res = get_web_relay_status(repo, task_id=getattr(ns, "task_id", ""))
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



from .pack_builder import (
    _infer_task_kind,
    _collect_git_dirty_source_files,
    _discover_scope_files,
    _extract_neighbor_signatures,
    _collect_active_diagnostics,
    _load_project_summary,
    build_web_pack,
)
from .merge_applier import (
    _strip_trailing_json_commas,
    _is_template_example_merge_obj,
    _is_outgoing_context_pack_text,
    _detect_truncated_merge_pack_id,
    _extract_merge_json_from_text,
    _resolve_incoming_merge_payload,
    _count_structural_braces,
    _validate_code_integrity,
    _apply_hunks,
    _three_way_merge_if_needed,
    apply_web_merge,
)

if __name__ == "__main__":
    raise SystemExit(main())
