"""Deterministic restore of managed Android Agent Harness files.

Verifies the installed kit against pinned release checksums, identifies missing,
modified, or corrupted managed files, restores only immutable engine files,
preserves developer-owned project context and task state byte-for-byte,
and verifies health with doctor.

Usage:
    python .agents/scripts/repair.py [--repo PATH] [--kit PATH] [--force] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import shutil
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print, step_progress, sublog  # noqa: E402
from _repo_files import REPO  # noqa: E402
from _vnext_common import (  # noqa: E402
    HarnessError,
    ValidationError,
    atomic_write_bytes,
    atomic_write_json,
    canonical_sha256,
    read_json,
    sha256_file,
    utc_now,
)
from doctor.engine import HarnessDoctor  # noqa: E402
from lifecycle import (  # noqa: E402
    ARCHITECTURE_MAJOR,
    OWNERSHIP_RELATIVE,
    PRESERVE_GLOBS,
    _snapshot_app_files,
    _verify_app_snapshot,
    _version_tuple,
)


# These files are installation-time configuration, not immutable engine bytes.
# Restoring their kit defaults would erase project identity or tracker wiring.
PRESERVED_MANAGED_FILES = frozenset({
    ".agents/scripts/_product.py",
    ".agents/mcp_config.json",
})


def _is_preserved_managed_file(rel_installed: str) -> bool:
    path = Path(rel_installed)
    return rel_installed in PRESERVED_MANAGED_FILES or any(path.match(pattern) for pattern in PRESERVE_GLOBS)


def _read_pinned_version(repo: Path) -> str:
    version_file = repo / ".agents" / "VERSION"
    if version_file.is_file():
        ver = version_file.read_text(encoding="utf-8").strip()
        if ver:
            return ver
    manifest_path = repo / OWNERSHIP_RELATIVE
    if manifest_path.is_file():
        try:
            data = read_json(manifest_path)
            ver = str(data.get("harness_version") or "").strip()
            if ver:
                return ver
        except Exception:
            pass
    raise ValidationError(f"Target repository {repo} does not contain an installed Android Agent Harness or valid VERSION.")


def _read_kit_version(kit: Path) -> str:
    path = kit / "agents" / "VERSION"
    if not path.is_file():
        raise ValidationError(f"Kit at {kit} is missing agents/VERSION.")
    return path.read_text(encoding="utf-8").strip()


def _verify_kit(kit: Path, expected_version: str) -> dict[str, str]:
    kit_ver = _read_kit_version(kit)
    if kit_ver != expected_version:
        raise ValidationError(
            f"Target repository is pinned to v{expected_version}, but kit is v{kit_ver}. "
            "Repair cannot silently repair from another version."
        )

    checksum_file = kit / "agents" / "release_checksums.json"
    if not checksum_file.is_file() or checksum_file.is_symlink():
        raise ValidationError("Kit release checksums manifest missing or symlink.")
    try:
        manifest = read_json(checksum_file)
    except Exception as exc:
        raise ValidationError(f"Kit release checksums manifest corrupt: {exc}")
    if not isinstance(manifest, dict):
        raise ValidationError("Kit release checksums manifest has an unsupported schema.")

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValidationError("Kit release checksums manifest files inventory is empty or malformed.")

    core_files = {"agents/VERSION", "agents/scripts/lifecycle.py"}
    missing_core = core_files - set(files)
    if missing_core:
        raise ValidationError(f"Kit release checksums manifest missing core files: {', '.join(sorted(missing_core))}")

    for rel, expected in files.items():
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValidationError(f"Suspicious path in release checksums: {rel}")
        target = kit / rel_path
        if not target.is_file() or target.is_symlink():
            raise ValidationError(f"Missing or symlinked kit file: {rel}")
        actual_sha = sha256_file(target)
        if actual_sha != expected:
            raise ValidationError(f"Kit release checksum mismatch for {rel}")

    return files


def _is_corrupted(path: Path) -> bool:
    try:
        if path.stat().st_size == 0:
            return True
    except OSError:
        return True

    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return True
    elif suffix == ".py":
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError:
            return True
    return False


def _check_active_task(repo: Path, force: bool) -> tuple[bool, str]:
    state_dir = repo / ".agents" / "state"
    task_file = state_dir / "active-task.json"
    if not task_file.is_file():
        return False, ""
    try:
        task_data = read_json(task_file)
        task_id = str(task_data.get("task_id") or "")
        plan_ref = str(task_data.get("plan_path") or "").strip()
        plan_path = Path(plan_ref) if plan_ref else state_dir / "tasks" / task_id / "plan.json"
        if not plan_path.is_absolute():
            plan_path = repo / plan_path
        plan_path = plan_path.resolve()
        if state_dir.resolve() not in plan_path.parents:
            raise ValidationError("Active task plan path escapes harness state; repair refused.")
        plan = read_json(plan_path)
        if str(plan.get("task_id") or "") != task_id:
            raise ValidationError("Active task identity mismatch; repair refused.")
        status = str(plan.get("status") or "UNKNOWN").upper()
        if status in {"CANCELLED", "DELIVERED"}:
            return False, ""
        if not force:
            raise ValidationError(
                f"Active task '{task_id}' ({status}) detected. Pass --force to repair while a task is active."
            )
        return True, task_id
    except ValidationError:
        raise
    except Exception as exc:
        if not force:
            raise ValidationError(f"Active task state is unreadable or incomplete; repair refused: {exc}")
        return True, ""


def repair_repository(repo: Path, kit: Path, *, force: bool = False) -> dict:
    """Executes deterministic repair of managed harness files in repo from pinned kit."""
    root = repo.resolve()
    kit_root = kit.resolve()

    pinned_version = _read_pinned_version(root)
    active_task_detected, active_task_id = _check_active_task(root, force)
    kit_files = _verify_kit(kit_root, pinned_version)

    # Snapshot application source code outside harness to guarantee immutability
    app_snapshot_before = _snapshot_app_files(root)

    # Record preserved developer-owned files
    preserved_records: list[str] = []
    for pattern in PRESERVE_GLOBS:
        for p in root.glob(pattern):
            if p.is_file():
                try:
                    rel_p = p.relative_to(root).as_posix()
                    preserved_records.append(rel_p)
                except ValueError:
                    pass

    context_dir = root / ".agents" / "project-context"
    if context_dir.is_dir():
        for p in context_dir.rglob("*"):
            if p.is_file():
                try:
                    rel_p = p.relative_to(root).as_posix()
                    if rel_p not in preserved_records:
                        preserved_records.append(rel_p)
                except ValueError:
                    pass

    tasks_dir = root / ".agents" / "tasks"
    if tasks_dir.is_dir():
        for p in tasks_dir.rglob("*"):
            if p.is_file():
                try:
                    rel_p = p.relative_to(root).as_posix()
                    if rel_p not in preserved_records:
                        preserved_records.append(rel_p)
                except ValueError:
                    pass

    preserved_records.sort()

    missing: list[str] = []
    modified: list[str] = []
    corrupted: list[str] = []
    restored: list[str] = []

    for rel, expected_sha in kit_files.items():
        if not rel.startswith("agents/"):
            continue
        rel_installed = "." + rel
        if _is_preserved_managed_file(rel_installed):
            continue
        dest = root / rel_installed
        src = kit_root / rel

        if not dest.is_file():
            missing.append(rel_installed)
        else:
            actual_sha = sha256_file(dest)
            if actual_sha != expected_sha:
                if _is_corrupted(dest):
                    corrupted.append(rel_installed)
                else:
                    modified.append(rel_installed)

    all_to_restore = sorted(set(missing + modified + corrupted))
    for rel_installed in all_to_restore:
        rel_kit = rel_installed.lstrip(".")
        src = kit_root / rel_kit
        dest = root / rel_installed
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_bytes()
        atomic_write_bytes(dest, content)
        if dest.suffix == ".py":
            try:
                dest.chmod(dest.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            except OSError:
                pass
        restored.append(rel_installed)

    # Restore project context facts if missing
    facts_file = root / ".agents" / "project-context" / "project-facts.json"
    if not facts_file.is_file() or facts_file.stat().st_size == 0:
        try:
            from project_context import extract_project_facts, render_project_context, write_project_context
            payload = extract_project_facts(root, in_memory_graph=True)
            views = render_project_context(payload)
            write_project_context(root, payload, views)
            restored.append(".agents/project-context/project-facts.json")
        except Exception:
            pass

    # Update ownership manifest if present
    ownership_file = root / OWNERSHIP_RELATIVE
    if ownership_file.is_file():
        try:
            manifest_data = read_json(ownership_file)
            entries = manifest_data.get("entries") or []
            updated = False
            for entry in entries:
                p = entry.get("path")
                if p in restored:
                    entry["post_install_sha256"] = sha256_file(root / p)
                    updated = True
            if updated:
                manifest_data["ownership_sha256"] = canonical_sha256({
                    k: v for k, v in manifest_data.items() if k != "ownership_sha256"
                })
                atomic_write_json(ownership_file, manifest_data)
        except Exception:
            pass

    # Verify zero application source code modified
    _verify_app_snapshot(root, app_snapshot_before, allowed_adapter_rels=set())

    # Re-run doctor to verify complete health
    doctor = HarnessDoctor(root, run_selftest=False, live_stream=False)
    results = doctor.run_all()
    pass_count = sum(1 for r in results if r.status == "PASS")
    warn_count = sum(1 for r in results if r.status == "WARN")
    fail_count = sum(1 for r in results if r.status == "FAIL")

    fail_details = [f"{r.name}: {r.message}" for r in results if r.status == "FAIL"]
    status = "PASS" if fail_count == 0 else "FAIL"
    return {
        "status": status,
        "pinned_version": pinned_version,
        "kit_version": _read_kit_version(kit_root),
        "restored": {
            "missing": sorted(missing),
            "modified": sorted(modified),
            "corrupted": sorted(corrupted),
            "total": len(restored),
            "files": sorted(restored),
        },
        "preserved_count": len(preserved_records),
        "preserved": preserved_records[:20],
        "active_task_detected": active_task_detected,
        "active_task_id": active_task_id,
        "doctor": {
            "passed": pass_count,
            "warnings": warn_count,
            "failures": fail_count,
            "failure_details": fail_details,
        },
    }


def main(argv: list[str] | None = None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(REPO), help="Path to Android repository root")
    parser.add_argument("--kit", default=None, help="Path to pinned harness kit")
    parser.add_argument("--force", action="store_true", help="Force repair even if an active task exists")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON report")
    args = parser.parse_args(argv)

    repo_path = Path(args.repo).resolve()
    if args.kit:
        kit_path = Path(args.kit).resolve()
    else:
        # Default kit resolution: repo if kit repo, else ~/.android-harness/kit
        kit_path = repo_path if (repo_path / "agents" / "VERSION").is_file() else Path.home() / ".android-harness" / "kit"

    try:
        report = repair_repository(repo_path, kit_path, force=args.force)
    except ValidationError as err:
        if args.json:
            print(json.dumps({"status": "FAIL", "error": str(err)}, indent=2))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        total = report["restored"]["total"]
        print(f"=== Android Agent Harness Repair: {report['status']} ===")
        print(f"  Pinned Version:  v{report['pinned_version']}")
        print(f"  Files Restored:  {total}")
        if report["restored"]["missing"]:
            print(f"    - Missing:     {len(report['restored']['missing'])}")
        if report["restored"]["modified"]:
            print(f"    - Modified:    {len(report['restored']['modified'])}")
        if report["restored"]["corrupted"]:
            print(f"    - Corrupted:   {len(report['restored']['corrupted'])}")
        print(f"  Preserved Files: {report['preserved_count']} (project context, notes, evidence)")
        print(f"  Doctor Checks:   {report['doctor']['passed']} passed, {report['doctor']['failures']} failures")
        if report["doctor"]["failures"] > 0:
            print("[FAIL] Doctor reported remaining issues after repair.")
            return 1
        print("[SUCCESS] Managed harness engine restored to pinned release perfection.")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
