"""Safe, plan-scoped repository file deletion under protected-root and mutation_guard enforcement.

Provides `harness.py file delete <path...>` so hosts without a native delete-file tool can
remove obsolete approved-scope repository files during `IMPLEMENTING` without bypassing
protected-root, symlink, or scope-drift invariants.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _vnext_common import ValidationError, state_root  # noqa: E402

MAX_DELETE_PATHS = 16

_ALWAYS_PROTECTED_ROOT_PREFIXES = (
    ".git/",
    ".agents/",
    "agents/",
    ".harness-setup/",
    ".harness-backup/",
    ".harness-recovery/",
    ".github/workflows/",
    "gradle/wrapper/",
    ".gradle/",
    ".idea/",
)
_ALWAYS_PROTECTED_BASENAMES = frozenset({
    "agents.md",
    "gemini.md",
    "claude.md",
    "codex.md",
    "qwen.md",
    "project_constitution.md",
    "gradlew",
    "gradlew.bat",
})


def _has_symlink_component(root: Path, target_raw: str) -> bool:
    """Reject symlinks anywhere along raw/resolved path inside the repository."""
    raw = Path(target_raw).expanduser()
    if raw.is_symlink():
        return True
    cand = raw if raw.is_absolute() else (root / raw)
    if cand.is_symlink():
        return True
    try:
        resolved_parent = cand.parent.resolve()
        if not resolved_parent.is_relative_to(root):
            return False
        cur = cand if cand.is_absolute() else (root / raw)
        # Walk non-resolved ancestor segments inside root to catch symlinked dirs.
        rel_parts = cand.relative_to(root).parts if cand.is_absolute() and cand.is_relative_to(root) else Path(target_raw).parts
        walker = root
        for part in rel_parts:
            if part in ("", "."):
                continue
            if part == "..":
                return True
            walker = walker / part
            if walker.is_symlink():
                return True
    except (OSError, ValueError):
        return True
    return False


def _is_unconditionally_protected(rel_posix: str) -> bool:
    rel_lower = rel_posix.lower().strip("/")
    if not rel_lower:
        return True
    for prefix in _ALWAYS_PROTECTED_ROOT_PREFIXES:
        stem = prefix.rstrip("/")
        if rel_lower == stem or rel_lower.startswith(prefix):
            return True
    return Path(rel_lower).name in _ALWAYS_PROTECTED_BASENAMES


def _pending_cancel_message(root: Path, task_id: str) -> str:
    if not task_id:
        return ""
    import time
    cancel_file = state_root(root) / "cancel-requested.json"
    try:
        data = json.loads(cancel_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    fresh = time.time() - float(data.get("requested_at") or 0) < 30 * 60
    if fresh and str(data.get("task_id") or "") == task_id:
        return f"Task '{task_id}' has a pending cancel request; cannot delete files."
    return ""


def delete_files(repo: Path, raw_paths: list[str]) -> dict[str, Any]:
    """Validate and delete 1..16 approved-scope repository files during IMPLEMENTING."""
    from mutation_guard import active_plan, file_mutation_allowed
    from plan_authority import require_mutation
    from _safety.path_and_read_guard import _safe_target

    root = repo.resolve()
    cleaned_inputs = [str(p or "").strip() for p in raw_paths]
    if not cleaned_inputs or any(not p for p in cleaned_inputs):
        raise ValidationError("file delete requires 1..16 non-empty repository file paths.")
    if len(cleaned_inputs) > MAX_DELETE_PATHS:
        raise ValidationError(f"file delete accepts at most {MAX_DELETE_PATHS} paths per invocation.")

    # Require an active IMPLEMENTING task unconditionally (do not allow idle/untracked doc bypass).
    plan = active_plan(root)
    require_mutation(plan)
    task_id = str(plan.get("task_id") or "")
    cancel_msg = _pending_cancel_message(root, task_id)
    if cancel_msg:
        raise ValidationError(cancel_msg)

    resolved_targets: list[Path] = []
    rel_targets: list[str] = []
    seen_rel: set[str] = set()

    for raw in cleaned_inputs:
        if _has_symlink_component(root, raw):
            raise ValidationError(f"PROTECTED_PATH: Refusing symlink target deletion: '{raw}'.")
        ok, detail, is_external = _safe_target(raw, root)
        if not ok or is_external:
            reason = detail if not ok else f"Target path '{raw}' is outside the writable repository scope."
            raise ValidationError(f"PROTECTED_PATH: {reason}")
        cand = Path(raw).expanduser()
        resolved = cand.resolve() if cand.is_absolute() else (root / cand).resolve()
        if resolved.is_symlink() or not resolved.is_relative_to(root) or resolved == root:
            raise ValidationError(f"PROTECTED_PATH: Target path '{raw}' escapes the repository boundary.")
        rel_posix = resolved.relative_to(root).as_posix()
        if _is_unconditionally_protected(rel_posix):
            raise ValidationError(
                f"PROTECTED_PATH: Cannot delete protected harness, Git, wrapper, or adapter file '{rel_posix}'."
            )
        if not resolved.exists():
            raise ValidationError(f"Target file does not exist: '{rel_posix}'.")
        if resolved.is_dir() or not resolved.is_file():
            raise ValidationError(f"Refusing non-regular-file deletion (directories are not allowed): '{rel_posix}'.")
        if rel_posix not in seen_rel:
            seen_rel.add(rel_posix)
            rel_targets.append(rel_posix)
            resolved_targets.append(resolved)

    allowed, reason, code = file_mutation_allowed(root, targets=rel_targets)
    if not allowed:
        raise ValidationError(f"{code}: {reason}" if code and not reason.startswith(code) else reason)

    deleted: list[str] = []
    for target, rel_posix in zip(resolved_targets, rel_targets):
        target.unlink()
        deleted.append(rel_posix)

    return {
        "schema_version": 1,
        "status": "DELETED",
        "task_id": task_id,
        "deleted": deleted,
        "count": len(deleted),
    }


def _resolve_repo(top_repo: str | None, sub_repo: str | None) -> Path:
    chosen = sub_repo or top_repo or os.environ.get("HARNESS_REPO", "").strip() or "."
    return Path(chosen).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely delete approved-scope repository files during IMPLEMENTING.")
    parser.add_argument("--repo", dest="top_repo", default=None, help="Target repository root")
    sub = parser.add_subparsers(dest="action", required=True)

    p_del = sub.add_parser("delete", help="Delete 1..16 approved-scope files inside the repository.")
    p_del.add_argument("paths", nargs="+", help="Repository-relative or contained file path(s) to delete.")
    p_del.add_argument("--repo", dest="sub_repo", default=None, help="Target repository root")
    p_del.add_argument("--json", action="store_true", help="Print JSON result.")

    args = parser.parse_args(argv)
    repo = _resolve_repo(getattr(args, "top_repo", None), getattr(args, "sub_repo", None))
    try:
        if args.action == "delete":
            payload = delete_files(repo, args.paths)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                for rel in payload["deleted"]:
                    print(f"[DELETE] Deleted {rel}")
            return 0
    except ValidationError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"status": "DENIED", "reason": str(exc)}, ensure_ascii=False))
        else:
            print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        else:
            print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
