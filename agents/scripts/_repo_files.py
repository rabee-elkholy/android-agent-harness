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


def changed_paths(*, include_untracked: bool = True, include_deleted: bool = False, repo: Path | None = None) -> list[Path]:
    """Working-tree files vs HEAD: staged, unstaged, and untracked (backward compatible)."""
    cfs = changed_files(repo=repo, include_untracked=include_untracked)
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


def adb_serial_is_emulator(serial: str) -> bool:
    if serial.startswith("emulator-"):
        return True
    try:
        probe = subprocess.run(
            ["adb", "-s", serial, "shell", "getprop", "ro.kernel.qemu"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=5,
        )
        return probe.returncode == 0 and (probe.stdout or "").strip() == "1"
    except (OSError, subprocess.TimeoutExpired):
        return serial.startswith(("localhost:", "127.0.0.1:"))


def first_adb_serial(*, allow_emulator: bool = True, policy: str | None = None) -> str | None:
    target_policy = policy or ("allow" if allow_emulator else "physical-only")
    if target_policy not in {"allow", "physical-only", "emulator-only"}:
        return None
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
    emulator: str | None = None
    for line in (proc.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        serial = parts[0]
        is_emu = adb_serial_is_emulator(serial)
        if is_emu:
            emulator = emulator or serial
            continue
        physical = physical or serial
    if target_policy == "physical-only":
        return physical
    if target_policy == "emulator-only":
        return emulator
    return physical or emulator


def first_physical_adb_serial() -> str | None:
    return first_adb_serial(allow_emulator=False)


HARNESS_INTERNAL_EXCLUSIONS = [
    ".agents/",
    ".harness-setup/",
    ".harness-backup/",
    ".harness-backups/",
    ".githooks/",
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


def _harness_adapter_exclusions(repo: Path) -> list[str]:
    """Return exact generated adapter paths; never hide a user's whole tool directory."""
    paths = {
        "AGENTS.md", "CLAUDE.md", "CODEX.md", "GEMINI.md", "QWEN.md",
        ".cursorrules", ".clinerules", ".windsurfrules", ".goosehints",
        ".cursor/rules/android-harness.mdc", ".cursor/mcp.json",
        ".claude/settings.json", ".github/copilot-instructions.md",
        ".github/instructions/android-harness.instructions.md",
        ".github/hooks/android-harness-pre-tool-use.json",
        ".windsurf/rules/android-harness.md", ".roo/rules/android-harness.md",
        ".amazonq/rules/android-harness.md", ".continue/rules/android-harness.md",
        ".junie/guidelines.md", ".kilocode/rules/android-harness.md",
    }
    agents_root = repo / ".agents"
    for template in (agents_root / "command-packs").glob("*.md.template"):
        name = template.name.removesuffix(".md.template")
        paths.update((f".claude/commands/{name}.md", f".github/prompts/{name}.prompt.md", f".codex/prompts/{name}.md"))
    for spec in (agents_root / "subagents").glob("*.json"):
        paths.add(f".claude/agents/{spec.stem}.md")
    return sorted(paths)


STRAY_CLEANUP_MARKERS = ("android-agent-harness", "android agent harness")


def _is_kit_generated_stray(path: Path) -> bool:
    """Only files the kit itself generated are ever cleaned up."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000].lower()
    except OSError:
        return False
    return any(marker in head for marker in STRAY_CLEANUP_MARKERS)


def ensure_local_git_privacy(target_repo: Path | None = None, *, clean_strays: bool = False) -> list[str]:
    """Write only the harness-owned local exclude block and internal hygiene.

    The vNext lifecycle never edits shared .gitignore, deletes filename-shaped
    client files, or hides tracked files with assume-unchanged. The deprecated
    clean_strays argument is intentionally ignored.
    """
    repo = (target_repo or REPO).resolve()
    logs: list[str] = []
    begin = "# BEGIN ANDROID AGENT HARNESS MANAGED BLOCK"
    end = "# END ANDROID AGENT HARNESS MANAGED BLOCK"
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=str(repo), capture_output=True, text=True, check=False,
        )
        raw_path = (proc.stdout or "").strip()
        exclude_path = Path(raw_path)
        if not exclude_path.is_absolute():
            exclude_path = repo / exclude_path
        text = exclude_path.read_text(encoding="utf-8", errors="replace") if exclude_path.is_file() else ""
        start, finish = text.find(begin), text.find(end)
        if start >= 0 and finish >= start:
            finish += len(end)
            text = (text[:start].rstrip() + "\n" + text[finish:].lstrip("\r\n")).strip("\n")
        exclusions = sorted(set((*HARNESS_INTERNAL_EXCLUSIONS, *_harness_adapter_exclusions(repo))))
        block = "\n".join((begin, *exclusions, end))
        new_text = f"{text.rstrip()}\n\n{block}\n" if text.strip() else f"{block}\n"
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_path.write_text(new_text, encoding="utf-8", newline="\n")
        logs.append("local git exclude -> managed harness block")
    except Exception:
        pass

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
    return logs
