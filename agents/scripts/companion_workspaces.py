#!/usr/bin/env python3
"""Developer-authorized Companion Workspaces for multi-root IDE projects (e.g. Android + Backend).

Allows an Android Agent Harness repository to coexist seamlessly with one or more separate
sibling/backend folders opened in the same multi-root Antigravity workspace:

- Files and commands inside the primary Android repository (`REPO`) remain 100% governed by
  the Android Agent Harness lifecycle, plan scope, review gates, and safety boundaries.
- Files and non-destructive dev/server commands strictly scoped inside a developer-authorized
  companion workspace pass through cleanly without `PROTECTED_PATH` or Android-task blocks.
- Stored in `.agents/project-context/companion-workspaces.json` (immutable to model file tools,
  preserved across `harness update`, and signed with `record_sha256` to fail closed on tampering).

Zero external dependencies (Python 3.10+ stdlib only).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import (  # noqa: E402
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    configure_utf8_output,
    read_json,
    redact,
    state_root,
    utc_now,
)
from evidence_store import StateLock  # noqa: E402

SCHEMA_VERSION = 1

_FORBIDDEN_SYSTEM_SEGMENTS = (
    "/appdata/roaming",
    "/appdata/local/programs",
    "/appdata/local/microsoft",
    "/programdata",
    "/windows",
    "/system32",
    "/program files",
    "/program files (x86)",
    "/library",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/var",
    "/proc",
    "/sys",
    "/dev",
)

_SECRET_SEGMENTS = (
    "/.ssh/",
    "/.aws/",
    "/.gnupg/",
    "/.kube/",
    "/.netrc",
    "/etc/passwd",
    "/etc/shadow",
)

_DESTRUCTIVE_COMPANION_CMD_RE = re.compile(
    r"\brm\s+-[a-z]*r[a-z]*f\s+(?:/|~|\$HOME|[A-Za-z]:[\\/]\s*$)"
    r"|\bformat\s+[A-Za-z]:"
    r"|\bmkfs\."
    r"|\bdd\s+if=",
    re.I,
)


def companion_workspaces_file(repo: Path) -> Path:
    repo = Path(repo).resolve()
    base = repo / ".agents" if (repo / ".agents").is_dir() else repo / "agents"
    return base / "project-context" / "companion-workspaces.json"


def _compute_record_sha(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "record_sha256"}
    return canonical_sha256(body)


def _sign_record(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.pop("record_sha256", None)
    out["record_sha256"] = _compute_record_sha(out)
    return out


def _norm_path_key(p: Path) -> str:
    s = p.resolve().as_posix().rstrip("/")
    return s.lower() if os.name == "nt" else s


def _validate_companion_candidate(repo: Path, raw_path: str) -> Path:
    raw_str = str(raw_path or "").strip().strip("\"'")
    if not raw_str:
        raise ValidationError("COMPANION_WORKSPACE_INVALID: Companion workspace path cannot be empty.")
    cand = Path(raw_str).expanduser()
    if not cand.is_absolute():
        cand = repo.resolve().parent / cand
    try:
        if cand.is_symlink():
            raise ValidationError(
                f"COMPANION_WORKSPACE_INVALID: Refusing symlink companion path '{raw_str}'; pass the real directory path."
            )
    except OSError as exc:
        raise ValidationError(f"COMPANION_WORKSPACE_INVALID: Cannot inspect '{raw_str}': {exc}") from exc

    resolved = cand.resolve()
    if not resolved.is_dir():
        raise ValidationError(
            f"COMPANION_WORKSPACE_NOT_FOUND: Directory '{resolved}' does not exist."
        )

    # Refuse filesystem root (e.g. `C:\` or `/`) and user home directory
    if resolved == resolved.parent:
        raise ValidationError(f"COMPANION_WORKSPACE_INVALID: Cannot register filesystem root '{resolved}'.")
    home = Path.home().resolve()
    if resolved == home:
        raise ValidationError("COMPANION_WORKSPACE_INVALID: Cannot register user home directory as a companion workspace.")

    # Refuse temp directory and harness/Antigravity runtime roots
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if resolved == tmp_root:
        raise ValidationError("COMPANION_WORKSPACE_INVALID: Cannot register system temp root as a companion workspace.")
    for protected_root in (home / ".android-harness", home / ".gemini"):
        pr = protected_root.resolve()
        if resolved == pr or resolved.is_relative_to(pr) or pr.is_relative_to(resolved):
            raise ValidationError(
                f"COMPANION_WORKSPACE_INVALID: Companion workspace '{resolved}' cannot overlap protected root '{pr}'."
            )

    # Refuse OS/system directories
    posix_low = resolved.as_posix().lower()
    # Strip Windows drive letter (e.g. `c:/windows` -> `/windows`) for uniform matching
    no_drive = re.sub(r"^[a-z]:", "", posix_low)
    for seg in _FORBIDDEN_SYSTEM_SEGMENTS:
        if no_drive == seg or no_drive.startswith(seg + "/"):
            raise ValidationError(
                f"COMPANION_WORKSPACE_INVALID: System directory '{resolved}' cannot be registered as a companion workspace."
            )

    # Refuse primary repo itself, any parent of primary repo, or any subdirectory inside primary repo
    repo_root = repo.resolve()
    if resolved == repo_root or resolved.is_relative_to(repo_root) or repo_root.is_relative_to(resolved):
        raise ValidationError(
            f"COMPANION_WORKSPACE_OVERLAP: Companion workspace '{resolved}' cannot overlap primary Android repository '{repo_root}'."
        )

    return resolved


def load_companion_workspaces(repo: Path, *, strict: bool = False) -> list[dict[str, Any]]:
    """Return verified companion workspace entries; fails closed (empty list) on tampering or corruption."""
    repo = Path(repo).resolve()
    path = companion_workspaces_file(repo)
    if not path.is_file():
        return []
    try:
        raw = read_json(path)
    except (OSError, ValueError, ValidationError) as exc:
        if strict:
            raise ValidationError(f"COMPANION_WORKSPACES_CORRUPTED: {exc}") from exc
        return []
    if not isinstance(raw, dict):
        if strict:
            raise ValidationError("COMPANION_WORKSPACES_CORRUPTED: payload is not a JSON object.")
        return []
    recorded_sha = str(raw.get("record_sha256") or "").strip()
    expected_sha = _compute_record_sha(raw)
    if not recorded_sha or recorded_sha != expected_sha:
        if strict:
            raise ValidationError("COMPANION_WORKSPACES_TAMPERED: record_sha256 mismatch.")
        return []
    entries = raw.get("workspaces")
    if not isinstance(entries, list):
        return []
    verified: list[dict[str, Any]] = []
    repo_root = repo.resolve()
    for item in entries:
        if not isinstance(item, dict):
            continue
        raw_p = str(item.get("path") or "").strip()
        if not raw_p:
            continue
        try:
            cand = Path(raw_p)
            if not cand.is_absolute() or cand.is_symlink():
                continue
            resolved = cand.resolve()
            if not resolved.is_dir():
                continue
            if resolved == repo_root or resolved.is_relative_to(repo_root) or repo_root.is_relative_to(resolved):
                continue
            verified.append({
                "path": str(resolved),
                "label": str(item.get("label") or resolved.name),
                "added_at": str(item.get("added_at") or ""),
                "source": str(item.get("source") or ""),
            })
        except (OSError, ValueError):
            continue
    return verified


def companion_workspace_roots(repo: Path) -> list[Path]:
    return [Path(item["path"]).resolve() for item in load_companion_workspaces(repo)]


def match_companion_target(repo: Path, raw_target: str | Path) -> tuple[bool, Path | None, str]:
    """Check whether `raw_target` safely resolves inside a verified companion workspace.

    Returns `(is_allowed, companion_root, detail_or_error)`:
    - `(False, None, "")` when `raw_target` is NOT inside any registered companion workspace.
    - `(False, companion_root, error_reason)` when inside a companion workspace but targeting a
      protected subpath (`.git`, `.agents`, symlink escape, or OS secret path).
    - `(True, companion_root, resolved_str)` when safely inside a verified companion workspace.
    """
    raw_str = str(raw_target or "").strip()
    if not raw_str:
        return False, None, ""
    roots = companion_workspace_roots(repo)
    if not roots:
        return False, None, ""
    raw_p = Path(raw_str).expanduser()
    if not raw_p.is_absolute():
        return False, None, ""
    try:
        resolved = raw_p.resolve()
    except (OSError, ValueError):
        return False, None, ""

    matched_root: Path | None = None
    for croot in roots:
        if resolved == croot or resolved.is_relative_to(croot):
            matched_root = croot
            break
    if matched_root is None:
        return False, None, ""

    # Reject symlink escapes whose lexical path appears inside companion but resolves outside (already resolved)
    # AND reject direct symlink file mutations inside companion
    try:
        if raw_p.is_symlink():
            return False, matched_root, f"Refusing symlink target '{raw_str}' inside companion workspace."
    except OSError:
        pass

    rel = resolved.relative_to(matched_root).as_posix() if resolved != matched_root else ""
    rel_low = rel.lower()
    full_low = resolved.as_posix().lower()
    if any(seg in full_low for seg in _SECRET_SEGMENTS):
        return False, matched_root, f"Target path '{raw_str}' accesses a protected secret path."
    if rel_low == ".git" or rel_low.startswith(".git/"):
        return False, matched_root, "Git metadata inside companion workspace is developer-owned and immutable to agent file tools."
    if (
        (matched_root / ".agents" / "harness.py").is_file()
        and (rel_low == ".agents" or rel_low.startswith(".agents/") or rel_low == ".harness-setup" or rel_low.startswith(".harness-setup/"))
    ):
        return False, matched_root, "Harness engine and state inside companion workspace are immutable to agent file tools."
    return True, matched_root, str(resolved)


def _command_references_path(command: str, target_root: Path) -> bool:
    """Case-insensitive on Windows check whether `command` explicitly names `target_root`."""
    cmd_norm = str(command or "").replace("\\", "/")
    root_posix = target_root.resolve().as_posix().rstrip("/")
    if os.name == "nt":
        cmd_cmp = cmd_norm.lower()
        root_cmp = root_posix.lower()
    else:
        cmd_cmp = cmd_norm
        root_cmp = root_posix
    idx = 0
    while True:
        pos = cmd_cmp.find(root_cmp, idx)
        if pos < 0:
            return False
        end = pos + len(root_cmp)
        after_ok = (end == len(cmd_cmp)) or (cmd_cmp[end] in {"/", " ", "\t", '"', "'", ";", "&", "|", "\r", "\n", ")", ":"})
        before_ok = (pos == 0) or (cmd_cmp[pos - 1] in {" ", "\t", '"', "'", "=", ";", "&", "|", "\r", "\n", "("})
        if before_ok and after_ok:
            return True
        idx = pos + 1


def _command_touches_primary_or_secrets(repo: Path, command: str) -> str:
    """Return a denial reason if `command` references primary repo, harness roots, or OS secrets."""
    cmd_norm = str(command or "").replace("\\", "/")
    cmd_low = cmd_norm.lower()
    for seg in _SECRET_SEGMENTS:
        if seg in cmd_low:
            return f"Command references protected secret path ({seg})."
    if _DESTRUCTIVE_COMPANION_CMD_RE.search(command or ""):
        return "Catastrophic filesystem command is blocked even inside a companion workspace."
    repo_root = repo.resolve()
    if _command_references_path(command, repo_root):
        return (
            f"Command mixes companion workspace execution with primary Android repository '{repo_root}'; "
            "run Android commands directly on the primary repository."
        )
    if re.search(r"\.\.[/\\]", cmd_norm) and repo_root.name.lower() in cmd_low:
        return (
            f"Command traverses via `..` toward primary Android repository '{repo_root.name}'; "
            "run Android commands directly on the primary repository."
        )
    home = Path.home().resolve()
    for prot in (home / ".android-harness", home / ".gemini"):
        if _command_references_path(command, prot):
            return f"Command references protected harness/runtime root '{prot}'."
    if re.search(r"(?:^|[\s\"'=/\\])(?:\.agents|\.harness-setup)(?:[/\\]|$|\s|\"|')", command or "", re.I):
        return "Command references `.agents` or `.harness-setup` which cannot be accessed via companion pass-through."
    return ""


def evaluate_companion_command(
    repo: Path,
    command: str,
    *,
    cwd: Path | None = None,
) -> tuple[bool, Path | None, str]:
    """Determine if a shell command is cleanly scoped to an authorized companion workspace.

    Returns `(is_companion_allowed, matched_root, reason)`:
    - `(False, None, "")` when command is NOT targeting any registered companion workspace.
    - `(False, matched_root, denial_reason)` when targeting a companion workspace but violating
      anti-smuggling/safety checks (e.g. mixing primary repo or secret paths).
    - `(True, matched_root, allow_reason)` when cleanly scoped to the companion workspace.
    """
    roots = companion_workspace_roots(repo)
    if not roots:
        return False, None, ""

    matched_root: Path | None = None
    if cwd is not None:
        try:
            cwd_res = Path(cwd).resolve()
            for croot in roots:
                if cwd_res == croot or cwd_res.is_relative_to(croot):
                    matched_root = croot
                    break
        except (OSError, ValueError):
            matched_root = None

    if matched_root is None:
        # Check explicit directory switch or path targeting a companion root at command start / arguments
        # Only qualify when command explicitly references a companion root (and not the primary repo).
        for croot in roots:
            if _command_references_path(command, croot):
                matched_root = croot
                break

    if matched_root is None:
        return False, None, ""

    violation = _command_touches_primary_or_secrets(repo, command)
    if violation:
        return False, matched_root, violation

    return True, matched_root, f"Command cleanly scoped to authorized companion workspace '{matched_root.name}'."


def add_companion_workspace(
    repo: Path,
    target_path: str,
    *,
    label: str = "",
    source: str = "",
    proof_reference: str = "",
) -> dict[str, Any]:
    repo = Path(repo).resolve()
    norm_source = str(source or "").strip().lower()
    norm_proof = str(redact(str(proof_reference or "").strip()))
    if norm_source not in {"conversation", "developer_terminal"} or len(norm_proof) < 2:
        raise ValidationError(
            "DEVELOPER_AUTHORITY_REQUIRED: `workspace add` requires `--source conversation` (or `developer_terminal`) "
            "and a non-empty `--proof-reference \"<developer words>\"`."
        )
    if norm_proof.rstrip().endswith(("?", "\u061f")):
        raise ValidationError(
            "DEVELOPER_AUTHORITY_REQUIRED: `--proof-reference` appears to be an unanswered developer question."
        )

    resolved = _validate_companion_candidate(repo, target_path)
    lock_path = state_root(repo) / "locks" / "companion-workspaces.lock"
    with StateLock(lock_path, timeout_seconds=30.0):
        existing = load_companion_workspaces(repo, strict=False)
        key = _norm_path_key(resolved)
        updated: list[dict[str, Any]] = []
        already = False
        for item in existing:
            if _norm_path_key(Path(item["path"])) == key:
                already = True
                updated.append({
                    **item,
                    "label": str(label or item.get("label") or resolved.name).strip() or resolved.name,
                    "updated_at": utc_now(),
                    "source": norm_source,
                    "proof_reference": norm_proof[:240],
                })
            else:
                updated.append(item)
        if not already:
            updated.append({
                "path": str(resolved),
                "label": str(label or resolved.name).strip() or resolved.name,
                "added_at": utc_now(),
                "source": norm_source,
                "proof_reference": norm_proof[:240],
            })
        payload = _sign_record({
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now(),
            "workspaces": updated,
        })
        out_path = companion_workspaces_file(repo)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out_path, payload)
    return {
        "status": "COMPANION_WORKSPACE_UPDATED" if already else "COMPANION_WORKSPACE_ADDED",
        "path": str(resolved),
        "label": str(label or resolved.name).strip() or resolved.name,
        "count": len(updated),
        "workspaces": updated,
        "persisted_path": str(out_path.relative_to(repo)).replace("\\", "/"),
    }


def remove_companion_workspace(
    repo: Path,
    target_path: str = "",
    *,
    clear_all: bool = False,
    source: str = "",
    proof_reference: str = "",
) -> dict[str, Any]:
    repo = Path(repo).resolve()
    norm_source = str(source or "").strip().lower()
    norm_proof = str(redact(str(proof_reference or "").strip()))
    if norm_source not in {"conversation", "developer_terminal"} or len(norm_proof) < 2:
        raise ValidationError(
            "DEVELOPER_AUTHORITY_REQUIRED: `workspace remove` requires `--source conversation` (or `developer_terminal`) "
            "and a non-empty `--proof-reference \"<developer words>\"`."
        )
    if norm_proof.rstrip().endswith(("?", "\u061f")):
        raise ValidationError(
            "DEVELOPER_AUTHORITY_REQUIRED: `--proof-reference` appears to be an unanswered developer question."
        )

    lock_path = state_root(repo) / "locks" / "companion-workspaces.lock"
    with StateLock(lock_path, timeout_seconds=30.0):
        existing = load_companion_workspaces(repo, strict=False)
        if clear_all:
            remaining: list[dict[str, Any]] = []
            removed = list(existing)
        else:
            raw_s = str(target_path or "").strip().strip("\"'")
            if not raw_s:
                raise ValidationError("Pass a companion workspace path/label to remove, or `--all`.")
            cand = Path(raw_s).expanduser()
            target_key = _norm_path_key(cand) if cand.is_absolute() else ""
            raw_low = raw_s.lower()
            remaining = []
            removed = []
            for item in existing:
                item_key = _norm_path_key(Path(item["path"]))
                if (target_key and item_key == target_key) or str(item.get("label") or "").lower() == raw_low:
                    removed.append(item)
                else:
                    remaining.append(item)
        out_path = companion_workspaces_file(repo)
        if remaining:
            payload = _sign_record({
                "schema_version": SCHEMA_VERSION,
                "updated_at": utc_now(),
                "workspaces": remaining,
            })
            out_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(out_path, payload)
        else:
            out_path.unlink(missing_ok=True)
    return {
        "status": "COMPANION_WORKSPACE_REMOVED",
        "removed_count": len(removed),
        "remaining_count": len(remaining),
        "workspaces": remaining,
    }


def main(argv: list[str] | None = None) -> int:
    configure_utf8_output()
    parser = argparse.ArgumentParser(
        description="Manage developer-authorized Companion Workspaces for multi-root IDE projects."
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_list = sub.add_parser("list", help="List registered companion workspaces")
    p_list.add_argument("--repo", default=".", help="Primary Android repository root")
    p_list.add_argument("--json", action="store_true", help="Emit JSON output")

    p_add = sub.add_parser("add", help="Register a companion workspace directory")
    p_add.add_argument("path", help="Absolute or sibling directory path for the companion workspace")
    p_add.add_argument("--label", default="", help="Optional human-readable label (defaults to directory name)")
    p_add.add_argument("--repo", default=".", help="Primary Android repository root")
    p_add.add_argument("--source", choices=("conversation", "developer_terminal"), required=True)
    p_add.add_argument("--proof-reference", required=True, help="Developer's explicit confirmation")
    p_add.add_argument("--json", action="store_true", help="Emit JSON output")

    p_rm = sub.add_parser("remove", help="Remove a registered companion workspace")
    p_rm.add_argument("path", nargs="?", default="", help="Companion workspace path or label to remove")
    p_rm.add_argument("--all", dest="clear_all", action="store_true", help="Remove all registered companion workspaces")
    p_rm.add_argument("--repo", default=".", help="Primary Android repository root")
    p_rm.add_argument("--source", choices=("conversation", "developer_terminal"), required=True)
    p_rm.add_argument("--proof-reference", required=True, help="Developer's explicit confirmation")
    p_rm.add_argument("--json", action="store_true", help="Emit JSON output")

    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        if args.action == "list":
            items = load_companion_workspaces(repo, strict=False)
            payload = {"status": "OK", "count": len(items), "workspaces": items}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                if not items:
                    print("COMPANION_WORKSPACES=none")
                else:
                    print(f"COMPANION_WORKSPACES={len(items)}")
                    for item in items:
                        print(f"  - {item['label']}: {item['path']}")
            return 0
        if args.action == "add":
            res = add_companion_workspace(
                repo,
                args.path,
                label=args.label,
                source=args.source,
                proof_reference=args.proof_reference,
            )
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"{res['status']}={res['label']} ({res['path']})")
            return 0
        if args.action == "remove":
            res = remove_companion_workspace(
                repo,
                args.path,
                clear_all=bool(args.clear_all),
                source=args.source,
                proof_reference=args.proof_reference,
            )
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"{res['status']}: removed={res['removed_count']} remaining={res['remaining_count']}")
            return 0
    except ValidationError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
