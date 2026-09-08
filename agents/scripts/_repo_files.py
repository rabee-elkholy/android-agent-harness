"""Repo-relative git/adb helpers shared by harness scripts."""
from __future__ import annotations

import os
import subprocess
import hashlib
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
# HARNESS_REPO lets the android-harness CLI run a kit script against a client
# checkout whose location differs from the script's own location.
_env_repo = os.environ.get("HARNESS_REPO", "").strip()
REPO = Path(_env_repo).resolve() if _env_repo else SCRIPTS_DIR.parent.parent

_CODE_SUFFIXES = {".kt", ".java", ".kts", ".cpp", ".c", ".h", ".hpp", ".aidl", ".pro"}


def _unquote_git_path(raw: str) -> str:
    """Decode C-style quoted and octal-escaped Git porcelain path."""
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        inner = raw[1:-1]
        try:
            return inner.encode("latin1").decode("unicode_escape").encode("latin1").decode("utf-8")
        except Exception:
            return inner
    return raw


@dataclass(frozen=True)
class ChangedFile:
    path: Path
    rel_posix: str
    status: str  # e.g., "M", "A", "D", "R", "??"
    old_path: Path | None = None
    old_rel_posix: str | None = None
    exists: bool = True
    is_untracked: bool = False
    content_sha256: str | None = None


def changed_files(repo: Path | None = None, *, include_untracked: bool = True) -> list[ChangedFile]:
    """Parse git status --porcelain=v2 -z to discover working-tree changes precisely."""
    r = repo or REPO
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v2", "-z", "-u", "--untracked-files=all"],
            cwd=r,
            capture_output=True,
            check=False,
        )
    except Exception:
        return []

    raw = proc.stdout or b""
    entries = raw.split(b"\x00")
    results: list[ChangedFile] = []
    idx = 0
    while idx < len(entries):
        chunk = entries[idx]
        idx += 1
        if not chunk:
            continue
        try:
            line = chunk.decode("utf-8", errors="replace")
        except Exception:
            continue

        if line.startswith("1 "):
            # 1 <xy> <sub> <mH> <mI> <mW> <hH> <hI> <path>
            parts = line.split(" ", 8)
            if len(parts) < 9:
                continue
            xy = parts[1]
            rel_path = parts[8]
            full_path = r / rel_path
            exists = full_path.is_file()
            c_sha = None
            if exists:
                try:
                    c_sha = hashlib.sha256(full_path.read_bytes()).hexdigest()
                except Exception:
                    pass
            status = "D" if "D" in xy else ("A" if "A" in xy else "M")
            results.append(
                ChangedFile(
                    path=full_path,
                    rel_posix=rel_path.replace("\\", "/"),
                    status=status,
                    exists=exists,
                    is_untracked=False,
                    content_sha256=c_sha,
                )
            )
        elif line.startswith("2 "):
            # 2 <xy> <sub> <mH> <mI> <mW> <hH> <hI> <X><score> <path> -> next chunk is origPath
            parts = line.split(" ", 8)
            if len(parts) < 9:
                continue
            rel_path = parts[8]
            orig_rel_path = ""
            if idx < len(entries):
                orig_rel_path = entries[idx].decode("utf-8", errors="replace")
                idx += 1
            full_path = r / rel_path
            old_path = (r / orig_rel_path) if orig_rel_path else None
            exists = full_path.is_file()
            c_sha = None
            if exists:
                try:
                    c_sha = hashlib.sha256(full_path.read_bytes()).hexdigest()
                except Exception:
                    pass
            results.append(
                ChangedFile(
                    path=full_path,
                    rel_posix=rel_path.replace("\\", "/"),
                    status="R",
                    old_path=old_path,
                    old_rel_posix=orig_rel_path.replace("\\", "/") if orig_rel_path else None,
                    exists=exists,
                    is_untracked=False,
                    content_sha256=c_sha,
                )
            )
        elif line.startswith("? "):
            if not include_untracked:
                continue
            rel_path = line[2:]
            full_path = r / rel_path
            exists = full_path.is_file()
            c_sha = None
            if exists:
                try:
                    c_sha = hashlib.sha256(full_path.read_bytes()).hexdigest()
                except Exception:
                    pass
            results.append(
                ChangedFile(
                    path=full_path,
                    rel_posix=rel_path.replace("\\", "/"),
                    status="??",
                    exists=exists,
                    is_untracked=True,
                    content_sha256=c_sha,
                )
            )
        elif line.startswith("u "):
            parts = line.split(" ", 10)
            if len(parts) >= 11:
                rel_path = parts[10]
                full_path = r / rel_path
                exists = full_path.is_file()
                c_sha = None
                if exists:
                    try:
                        c_sha = hashlib.sha256(full_path.read_bytes()).hexdigest()
                    except Exception:
                        pass
                results.append(
                    ChangedFile(
                        path=full_path,
                        rel_posix=rel_path.replace("\\", "/"),
                        status="U",
                        exists=exists,
                        is_untracked=False,
                        content_sha256=c_sha,
                    )
                )
    return results


def changed_paths(*, include_untracked: bool = True, include_deleted: bool = False) -> list[Path]:
    """Working-tree files vs HEAD: staged, unstaged, and untracked (backward compatible)."""
    cfs = changed_files(include_untracked=include_untracked)
    seen: dict[str, Path] = {}
    for cf in cfs:
        if not include_deleted and not cf.exists:
            continue
        key = cf.rel_posix
        seen[key] = cf.path
    return list(seen.values())


def working_tree_fingerprint(repo: Path | None = None) -> str | None:
    """Hash every staged, unstaged, and untracked working-tree change.

    The fingerprint includes status, path, rename source, and current content.
    None is returned when Git or file hashing cannot be trusted so callers
    fail closed instead of reusing a stale gate result.
    """
    r = repo or REPO
    try:
        status_proc = subprocess.run(
            ["git", "status", "--porcelain=v2", "-z", "-u", "--untracked-files=all"],
            cwd=r,
            capture_output=True,
            check=False,
        )
    except Exception:
        return None
    if status_proc.returncode != 0:
        return None

    items: list[str] = []
    for changed in changed_files(r, include_untracked=True):
        if changed.exists and not changed.content_sha256:
            return None
        content_marker = changed.content_sha256 or "deleted"
        old_marker = changed.old_rel_posix or ""
        items.append(
            f"{changed.status}\0{changed.rel_posix}\0{old_marker}\0{content_marker}"
        )
    return hashlib.sha256("\n".join(sorted(items)).encode("utf-8")).hexdigest()


def has_non_doc_code_changes() -> bool:
    """True when the working tree has Kotlin/Java/Gradle or non-string XML edits."""
    for cf in changed_files(include_untracked=True):
        rel = cf.rel_posix
        suffix = cf.path.suffix.lower()
        if suffix in _CODE_SUFFIXES:
            return True
        if suffix == ".xml":
            lower_name = cf.path.name.lower()
            if lower_name in ("strings.xml", "plurals.xml") or "/values" in f"/{rel}":
                continue
            return True
    return False


def first_adb_serial(*, allow_emulator: bool = True) -> str | None:
    try:
        proc = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return None
    physical: str | None = None
    for line in (proc.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        serial = parts[0]
        is_emu = (
            serial.startswith("emulator-")
            or serial.startswith("localhost:")
            or serial.startswith("127.0.0.1:")
        )
        if is_emu:
            if allow_emulator and physical is None:
                physical = serial
            continue
        # A physical device is always preferred over an emulator.
        return serial
    return physical


def first_physical_adb_serial() -> str | None:
    return first_adb_serial(allow_emulator=False)


HARNESS_LOCAL_EXCLUSIONS = [
    ".agents/",
    ".harness-setup/",
    ".harness-backup/",
    ".harness-backups/",
    ".githooks/",
    "AGENTS.md",
    "GEMINI.md",
    "CLAUDE.md",
    "CODEX.md",
    "QWEN.md",
    ".cursor/",
    ".cursorrules",
    ".windsurf/",
    ".windsurfrules",
    ".claude/",
    ".clinerules",
    ".amazonq/",
    ".continue/",
    ".junie/",
    ".kilocode/",
    ".roo/",
    ".goosehints",
    "*.diff",
    "*.patch",
    "*.secret",
    "*.tmp",
    "*.json.tmp",
    "*.wizard_questions.json",
    ".wizard_questions.json",
    "scratch_*.py",
    "android-agent-harness/",
    "fix_product.py",
    "script_step*.py",
    "update_worker.py",
]


STRAY_CLEANUP_MARKERS = ("android-agent-harness", "android agent harness")


def _is_kit_generated_stray(path: Path) -> bool:
    """Only files the kit itself generated are ever cleaned up."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000].lower()
    except OSError:
        return False
    return any(marker in head for marker in STRAY_CLEANUP_MARKERS)


def ensure_local_git_privacy(target_repo: Path | None = None, *, clean_strays: bool = False) -> list[str]:
    """Ensure all harness rules are in .git/info/exclude (local to this PC) and clean shared .gitignore.

    `clean_strays` deletes legacy setup scratch scripts (script_step*.py,
    fix_product.py, update_worker.py) — setup-time only and content-gated so
    client files with the same names are never touched by checks.
    """
    repo = (target_repo or REPO).resolve()
    logs: list[str] = []

    # 1. Populate .git/info/exclude (100% private to local machine, never tracked in Git)
    exclude_path = repo / ".git" / "info" / "exclude"
    if (repo / ".git").is_dir() or exclude_path.is_file():
        try:
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            text = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""
            lines = [ln.strip() for ln in text.splitlines()]
            added: list[str] = []
            for pat in HARNESS_LOCAL_EXCLUSIONS:
                if pat not in lines and pat.rstrip("/") not in lines:
                    added.append(pat)
            if added:
                with exclude_path.open("a", encoding="utf-8", newline="\n") as f:
                    if text and not text.endswith("\n"):
                        f.write("\n")
                    f.write("# Android Agent Harness — Local AI Manifests & Transient State (Private to this machine)\n")
                    for pat in added:
                        f.write(f"{pat}\n")
                logs.append(f"local git exclude -> .git/info/exclude ({len(added)} patterns registered)")
        except Exception:
            pass

    # 2. Ensure .agents/.gitignore has internal hygiene rules
    agents_gi = repo / ".agents" / ".gitignore"
    if (repo / ".agents").is_dir():
        try:
            ag_extra = [
                "state/",
                "cache/",
                "__pycache__/",
                "scripts/__pycache__/",
                "mcp/*/__pycache__/",
                "mcp/zoho_sprints/__pycache__/",
                "mcp/zoho_sprints/zoho_config.json",
                "*zoho*token*",
                "*.secret",
            ]
            ag_lines = agents_gi.read_text(encoding="utf-8").splitlines() if agents_gi.is_file() else []
            ag_added = False
            for line in ag_extra:
                if line not in ag_lines:
                    ag_lines.append(line)
                    ag_added = True
            if ag_added or not agents_gi.is_file():
                agents_gi.write_text("\n".join(ag_lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    # 3. Clean .gitignore: prune any harness rules from shared .gitignore so it remains clean
    is_raw_kit = (
        ((repo / "harness_cli.py").is_file() and (repo / "scripts_dev" / "release_version.py").is_file())
        or ((repo / "agents" / "VERSION").is_file() and not (repo / ".agents").is_dir())
    )
    gi = repo / ".gitignore"
    if not is_raw_kit and (repo / ".git").is_dir() and gi.is_file():
        try:
            raw_gi_lines = gi.read_text(encoding="utf-8").splitlines()
            cleaned_gi_lines: list[str] = []
            modified = False
            for ln in raw_gi_lines:
                s = ln.strip()
                if (
                    s in {pat.strip() for pat in HARNESS_LOCAL_EXCLUSIONS}
                    or s in {pat.strip().rstrip("/") for pat in HARNESS_LOCAL_EXCLUSIONS}
                    or s.startswith(".agents/")
                    or s in ("# Android AI Harness Kit", "# Android Agent Harness")
                ):
                    modified = True
                    continue
                cleaned_gi_lines.append(ln)

            if modified:
                while cleaned_gi_lines and not cleaned_gi_lines[-1].strip():
                    cleaned_gi_lines.pop()
                new_text = "\n".join(cleaned_gi_lines) + ("\n" if cleaned_gi_lines else "")
                gi.write_text(new_text, encoding="utf-8")
                logs.append("cleaned shared .gitignore (harness exclusions moved to .git/info/exclude)")
                diff_proc = subprocess.run(
                    ["git", "diff", "--name-only", ".gitignore"],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                )
                if not (diff_proc.stdout or "").strip():
                    subprocess.run(["git", "checkout", "--", ".gitignore"], cwd=str(repo), capture_output=True)
        except Exception:
            pass

    # 4. Clean stray scratch scripts from repo root (setup-time only, content-gated)
    if clean_strays:
        for stray_file in repo.glob("script_step*.py"):
            if not _is_kit_generated_stray(stray_file):
                continue
            try:
                stray_file.unlink()
                logs.append(f"removed stray kit scratch {stray_file.name}")
            except OSError:
                pass
        for stray_name in ("fix_product.py", "update_worker.py"):
            stray = repo / stray_name
            if stray.is_file() and _is_kit_generated_stray(stray):
                try:
                    stray.unlink()
                    logs.append(f"removed stray kit scratch {stray_name}")
                except OSError:
                    pass

    # 5. Assume unchanged for tracked adapter candidates in client apps only
    if not is_raw_kit:
        for tracked_cand in ["AGENTS.md", "GEMINI.md", "CLAUDE.md"]:
            if (repo / tracked_cand).is_file():
                subprocess.run(
                    ["git", "update-index", "--assume-unchanged", tracked_cand],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                )

    return logs

