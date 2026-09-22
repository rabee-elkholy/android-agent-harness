"""Transactional install, compatible update, and ownership-safe uninstall."""
from __future__ import annotations

import argparse
import base64
import gc
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import (  # noqa: E402
    enable_line_buffered_stdio,
    live_print,
    step_progress,
    sublog,
)
from _vnext_common import (  # noqa: E402
    HarnessError,
    ValidationError,
    atomic_write_json,
    canonical_sha256,
    read_json,
    sha256_file,
    atomic_write_bytes,
    utc_now,
)


SCHEMA_VERSION = 1
ARCHITECTURE_MAJOR = 1
OWNERSHIP_RELATIVE = Path(".harness-setup") / "ownership-v1.json"
EXCLUDE_BEGIN = "# BEGIN ANDROID AGENT HARNESS MANAGED BLOCK"
EXCLUDE_END = "# END ANDROID AGENT HARNESS MANAGED BLOCK"
INTERNAL_EXCLUDE_PATTERNS = (
    ".agents/",
    ".harness-setup/",
    ".harness-backup/",
    ".harness-recovery/",
)
PRESERVE_GLOBS = (
    ".agents/project-context/project-notes.md",
    ".agents/project-context/architecture-policy.json",
    ".agents/project-context/project-facts.json",
    ".agents/project-context/views/*",
    ".agents/project-context/legacy-overrides/*",
    ".agents/mcp/zoho_sprints/workflow_defaults.json",
)


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for part in value.strip().lstrip("v").split(".")[:3]:
        digits = "".join(char for char in part if char.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0, 0])[:3])


def _read_version(root: Path, relative: str = "agents/VERSION") -> str:
    path = root / relative
    if not path.is_file():
        raise ValidationError(f"version file is missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _assert_kit_outside_repo(repo: Path, kit: Path) -> None:
    repo_r = repo.resolve()
    kit_r = kit.resolve()
    if kit_r == repo_r or _is_within(kit_r, repo_r):
        raise ValidationError(
            f"Harness kit checkout must live outside target Android repository: {kit_r} inside {repo_r}"
        )


def _find_nested_kit_checkouts(repo: Path) -> list[Path]:
    found: list[Path] = []
    try:
        for child in repo.iterdir():
            if (
                child.is_dir()
                and (child / ".git").exists()
                and (child / "harness_cli.py").is_file()
                and (child / "agents" / "VERSION").is_file()
                and (child / "agents" / "scripts" / "lifecycle.py").is_file()
            ):
                found.append(child.resolve())
    except (OSError, PermissionError):
        pass
    return sorted(found)


def _validate_repo(repo: Path) -> Path:
    root = repo.resolve()
    if not (root / ".git").exists():
        raise ValidationError("target must be a Git checkout or worktree")
    if not ((root / "gradlew").is_file() or (root / "gradlew.bat").is_file()):
        raise ValidationError("target is outside the supported Gradle Wrapper boundary")
    nested = _find_nested_kit_checkouts(root)
    if nested:
        raise ValidationError(
            "full harness kit checkout is nested inside target Android repository: "
            + ", ".join(str(p) for p in nested)
        )
    return root


def _validate_kit(kit: Path) -> tuple[Path, str]:
    root = kit.resolve()
    if not (root / "agents" / "scripts" / "lifecycle.py").is_file():
        raise ValidationError("kit does not contain the vNext lifecycle engine")
    version = _read_version(root)
    if _version_tuple(version)[0] != ARCHITECTURE_MAJOR:
        raise ValidationError(f"kit v{version} is not architecture major {ARCHITECTURE_MAJOR}")
    checksum_file = root / "agents" / "release_checksums.json"
    if not checksum_file.is_file() or checksum_file.is_symlink():
        raise ValidationError("kit release checksums manifest missing or symlink")
    checksums = read_json(checksum_file)
    if not isinstance(checksums, dict):
        raise ValidationError("kit release checksums manifest has an unsupported schema")
    files = checksums.get("files")
    if not isinstance(files, dict) or not files:
        raise ValidationError("kit release checksums manifest files inventory is empty or malformed")
    core_files = {"agents/VERSION", "agents/scripts/lifecycle.py"}
    missing_core = core_files - set(files)
    if missing_core:
        raise ValidationError(f"kit release checksums manifest missing core files: {', '.join(sorted(missing_core))}")

    agents_dir = root / "agents"
    if not agents_dir.is_dir() or agents_dir.is_symlink():
        raise ValidationError("kit agents directory missing or symlink")
    actual_files: set[str] = set()
    ignored_parts = {"state", "cache", "__pycache__"}
    for p in sorted(agents_dir.rglob("*")):
        if p.is_symlink():
            rel_sym = p.relative_to(root).as_posix()
            raise ValidationError(f"symlink rejected in kit payload: {rel_sym}")
        if not p.is_file():
            continue
        rel_from_agents = p.relative_to(agents_dir)
        if rel_from_agents.as_posix() == "release_checksums.json":
            continue
        if ignored_parts.intersection(rel_from_agents.parts):
            continue
        if p.suffix.lower() in {".pyc", ".pyo"}:
            continue
        actual_files.add(p.relative_to(root).as_posix())

    manifest_keys = set(files.keys())
    if actual_files != manifest_keys:
        missing = sorted(manifest_keys - actual_files)
        unexpected = sorted(actual_files - manifest_keys)
        details = []
        if missing:
            details.append(f"missing ({len(missing)}): {', '.join(missing[:10])}")
        if unexpected:
            details.append(f"unexpected ({len(unexpected)}): {', '.join(unexpected[:10])}")
        raise ValidationError(f"kit release checksums inventory mismatch: {'; '.join(details)}")

    for rel, expected in files.items():
        rel_path = Path(str(rel))
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValidationError(f"suspicious path in release checksums: {rel}")
        path = root / rel_path
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise ValidationError(f"kit release checksum mismatch: {rel}")
    return root, version


def _load_answers(repo: Path) -> dict:
    path = repo / ".harness-setup" / "answers.json"
    data = read_json(path)
    from wizard.i18n import SCHEMA
    if isinstance(data, dict) and data.get("schema") not in (None, SCHEMA):
        raise ValidationError(
            "Existing setup answers use an unsupported schema.\n"
            "Clean setup required. Remove/reset .harness-setup and rerun installer."
        )
    return data


def _hash_or_none(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() and not path.is_symlink() else None


def _snapshot_files(repo: Path, paths: list[Path]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for path in paths:
        try:
            rel = path.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            continue
        result[rel] = _hash_or_none(path)
    return result


def _snapshot_app_files(repo: Path) -> dict[str, str]:
    """Cryptographically snapshot all Android product and build files outside harness."""
    snapshot: dict[str, str] = {}
    skip_dir_names = {".git", ".agents", ".gradle", ".idea", "build"}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [
            d for d in dirs
            if d not in skip_dir_names
            and not d.startswith(".harness")
            and not d.startswith((".agents.previous-", ".agents-stage-"))
        ]
        root_path = Path(root)
        for name in files:
            if name.endswith(".lock"):
                continue
            path = root_path / name
            if path.is_symlink():
                continue
            try:
                rel = path.resolve().relative_to(repo.resolve()).as_posix()
            except ValueError:
                continue
            digest = sha256_file(path)
            if digest:
                snapshot[rel] = digest
    return snapshot


def _verify_app_snapshot(repo: Path, before: dict[str, str], allowed_adapter_rels: set[str]) -> None:
    """Ensure zero application source or build files were modified during setup."""
    after = _snapshot_app_files(repo)
    modified_or_new: list[str] = []
    for rel, digest in before.items():
        if rel in allowed_adapter_rels:
            continue
        current_digest = after.get(rel)
        if current_digest != digest:
            modified_or_new.append(f"{rel} (modified or deleted)")

    for rel in after:
        if rel in allowed_adapter_rels or rel in before:
            continue
        modified_or_new.append(f"{rel} (newly created)")

    if modified_or_new:
        raise ValidationError(
            "Application files outside harness boundary were modified: "
            + ", ".join(modified_or_new[:10])
        )


def _candidate_adapter_paths(repo: Path) -> list[Path]:
    candidates = [
        "AGENTS.md", "CLAUDE.md", "CODEX.md", "GEMINI.md", "QWEN.md",
        ".cursorrules", ".clinerules", ".windsurfrules", ".goosehints",
        ".cursor/rules/android-harness.mdc", ".cursor/mcp.json",
        ".claude/settings.json", ".github/copilot-instructions.md",
        ".github/instructions/android-harness.instructions.md",
        ".github/hooks/android-harness-pre-tool-use.json",
        ".windsurf/rules/android-harness.md", ".roo/rules/android-harness.md",
        ".amazonq/rules/android-harness.md", ".continue/rules/android-harness.md",
        ".junie/guidelines.md", ".kilocode/rules/android-harness.md",
    ]
    command_names = [path.name.removesuffix(".md.template") for path in (Path(__file__).resolve().parents[1] / "command-packs").glob("*.md.template")]
    for name in command_names:
        candidates.extend((f".claude/commands/{name}.md", f".github/prompts/{name}.prompt.md", f".codex/prompts/{name}.md"))
    for path in (Path(__file__).resolve().parents[1] / "subagents").glob("*.json"):
        candidates.append(f".claude/agents/{path.stem}.md")
        candidates.append(f".agents/agents/{path.stem}/agent.md")
    result = [repo / rel for rel in sorted(set(candidates))]
    hooks = repo / ".githooks"
    if hooks.is_dir():
        markers = ("managed-by: android-agent-harness", "managed-by: android-harness-kit")
        for hook in sorted(path for path in hooks.rglob("*") if path.is_file()):
            try:
                head = hook.read_text(encoding="utf-8", errors="replace")[:4096].lower()
            except OSError:
                continue
            if any(marker in head for marker in markers):
                result.append(hook)
    return result


def _rollback_adapters(repo: Path, backup: Path, before: dict[str, str | None]) -> None:
    for path in _candidate_adapter_paths(repo):
        rel = path.relative_to(repo).as_posix()
        if rel not in before and path.is_file():
            path.unlink(missing_ok=True)
    _restore_paths_from_backup(repo, backup, before)


def _managed_exclude(repo: Path, *, remove: bool = False) -> None:
    path = _git_exclude_path(repo)
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    start = text.find(EXCLUDE_BEGIN)
    end = text.find(EXCLUDE_END)
    if remove and (start < 0 or end < start):
        return
    if start >= 0 and end >= start:
        end += len(EXCLUDE_END)
        text = (text[:start].rstrip() + "\n" + text[end:].lstrip("\r\n")).strip("\n")
    if not remove:
        adapter_paths = tuple(path.relative_to(repo).as_posix() for path in _candidate_adapter_paths(repo))
        patterns = tuple(sorted(set((*INTERNAL_EXCLUDE_PATTERNS, *adapter_paths))))
        block = "\n".join((EXCLUDE_BEGIN, *patterns, EXCLUDE_END))
        text = f"{text.rstrip()}\n\n{block}\n" if text.strip() else f"{block}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, text.encode("utf-8"))


def _git_exclude_path(repo: Path) -> Path:
    raw_path = subprocess_git(repo, "rev-parse", "--git-path", "info/exclude")
    path = Path(raw_path)
    return path if path.is_absolute() else (repo / path).resolve()


def subprocess_git(repo: Path, *args: str) -> str:
    import subprocess

    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ValidationError((proc.stderr or proc.stdout or "git failed").strip())
    return (proc.stdout or "").strip()


def _git_config_value(repo: Path, key: str) -> str | None:
    import subprocess

    proc = subprocess.run(["git", "config", "--get", key], cwd=str(repo), capture_output=True, text=True, check=False)
    return (proc.stdout or "").strip() if proc.returncode == 0 else None


def _restore_git_config(repo: Path, key: str, value: str | None) -> None:
    import subprocess

    args = ["git", "config", "--unset-all", key] if value is None else ["git", "config", key, value]
    proc = subprocess.run(args, cwd=str(repo), capture_output=True, text=True, check=False)
    if value is not None and proc.returncode != 0:
        raise ValidationError((proc.stderr or proc.stdout or f"failed restoring git config {key}").strip())


def _migrate_legacy_references(repo: Path, recovery: Path) -> list[str]:
    """Migrates genuinely customized legacy references into .agents/project-context/legacy-overrides."""
    migrated: list[str] = []
    refs_dir = repo / ".agents" / "skills" / "android-harness" / "references"
    if not refs_dir.is_dir():
        return migrated
    inventory = repo / ".agents" / "release_checksums.json"
    defaults = read_json(inventory).get("files") or {} if inventory.is_file() else {}
    ownership_file = repo / OWNERSHIP_RELATIVE
    ownership_entries = {}
    if ownership_file.is_file():
        try:
            for entry in read_json(ownership_file).get("entries") or []:
                p = entry.get("path")
                h = entry.get("post_install_sha256")
                if p and h:
                    ownership_entries[p] = h
        except Exception:
            pass
    overrides_dir = recovery / ".agents" / "project-context" / "legacy-overrides"
    for ref_file in refs_dir.glob("*.md"):
        if not ref_file.is_file():
            continue
        curr_hash = _hash_or_none(ref_file)
        rel_key = f"agents/skills/android-harness/references/{ref_file.name}"
        rel_managed = f".agents/skills/android-harness/references/{ref_file.name}"
        orig_hash = defaults.get(rel_key) or ownership_entries.get(rel_managed)
        # If baseline hash is absent (legacy replacement) or hash differs from previous installed baseline:
        if orig_hash is None or curr_hash != orig_hash:
            overrides_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ref_file, overrides_dir / ref_file.name)
            rel_path = f".agents/project-context/legacy-overrides/{ref_file.name}"
            migrated.append(rel_path)
    return migrated


def _copy_preserved(repo: Path, recovery: Path, *, refresh_defaults: bool = False) -> list[str]:
    preserved: list[str] = []
    for pattern in PRESERVE_GLOBS:
        for source in repo.glob(pattern):
            if not source.is_file():
                continue
            rel = source.relative_to(repo)
            target = recovery / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            preserved.append(rel.as_posix())
    migrated = _migrate_legacy_references(repo, recovery)
    for m in migrated:
        if m not in preserved:
            preserved.append(m)
    return preserved


def _restore_preserved(repo: Path, recovery: Path, preserved: list[str]) -> None:
    for rel in preserved:
        source = recovery / rel
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _legacy_preserved_paths(kit: Path, preserved: list[str]) -> list[str]:
    """Keep project-specific legacy references without replacing current kit files."""
    result: list[str] = []
    for rel in preserved:
        if (
            rel == ".agents/mcp/zoho_sprints/workflow_defaults.json"
            or rel.startswith(".agents/project-context/")
        ):
            result.append(rel)
            continue
        kit_rel = Path(rel).relative_to(".agents")
        if not (kit / "agents" / kit_rel).exists():
            result.append(rel)
    return result


def _write_ownership(
    repo: Path,
    *,
    version: str,
    before: dict[str, str | None],
    backup: Path | None,
    previous: dict | None = None,
    git_config_before: dict[str, str | None] | None = None,
) -> dict:
    owned_paths = [
        path
        for path in (repo / ".agents").rglob("*")
        if path.is_file()
        and not ({"state", "cache", "__pycache__"} & set(path.relative_to(repo / ".agents").parts))
        and path.suffix not in {".pyc", ".pyo"}
    ]
    owned_paths.extend(path for path in _candidate_adapter_paths(repo) if path.is_file())
    after = _snapshot_files(repo, owned_paths)
    previous_entries = {str(item.get("path") or ""): item for item in (previous or {}).get("entries") or []}
    entries = []
    for rel, post_hash in sorted(after.items()):
        if not rel.startswith(".agents/") and rel not in previous_entries and before.get(rel) == post_hash:
            continue
        original_hash = previous_entries.get(rel, {}).get("pre_install_sha256", before.get(rel))
        entries.append({
            "path": rel,
            "pre_install_sha256": original_hash,
            "post_install_sha256": post_hash,
            "ownership": "created" if original_hash is None else "managed",
        })
    for rel, original_hash in sorted(before.items()):
        if rel in after or original_hash is None:
            continue
        entries.append({
            "path": rel,
            "pre_install_sha256": original_hash,
            "post_install_sha256": None,
            "ownership": "removed_legacy",
        })
    previous_git_config = (previous or {}).get("git_config") or {}
    git_config = {
        key: {"before": values.get("before"), "after": _git_config_value(repo, key)}
        for key, values in previous_git_config.items()
        if isinstance(values, dict)
    }
    if not git_config:
        git_config = {
            key: {"before": value, "after": _git_config_value(repo, key)}
            for key, value in (git_config_before or {}).items()
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "architecture_major": ARCHITECTURE_MAJOR,
        "harness_version": version,
        "installed_at": utc_now(),
        "install_backup": (previous or {}).get("install_backup") or (backup.relative_to(repo).as_posix() if backup else None),
        "latest_backup": backup.relative_to(repo).as_posix() if backup else None,
        "managed_exclude_block": {"begin": EXCLUDE_BEGIN, "end": EXCLUDE_END},
        "git_config": git_config,
        "entries": entries,
    }
    manifest["ownership_sha256"] = canonical_sha256({key: value for key, value in manifest.items() if key != "ownership_sha256"})
    atomic_write_json(repo / OWNERSHIP_RELATIVE, manifest)
    return manifest


def _read_ownership(repo: Path) -> dict:
    manifest = read_json(repo / OWNERSHIP_RELATIVE)
    expected = canonical_sha256({key: value for key, value in manifest.items() if key != "ownership_sha256"})
    if manifest.get("ownership_sha256") != expected:
        raise ValidationError("ownership manifest integrity mismatch")
    if manifest.get("architecture_major") != ARCHITECTURE_MAJOR:
        raise ValidationError("ownership manifest belongs to an unsupported architecture")
    return manifest


def _backup(repo: Path, manifest: dict | None, label: str, extra_paths: list[Path] | None = None) -> Path:
    root = repo / ".harness-backup"
    target = root / f"{label}-{utc_now().replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:8]}"
    target.mkdir(parents=True, exist_ok=False)
    paths: set[str] = {".agents", ".harness-setup/answers.json", OWNERSHIP_RELATIVE.as_posix()}
    if manifest:
        paths.update(str(entry.get("path") or "") for entry in manifest.get("entries") or [])
    for path in extra_paths or []:
        try:
            paths.add(path.resolve().relative_to(repo.resolve()).as_posix())
        except ValueError:
            continue
    for rel in sorted(path for path in paths if path):
        source = repo / rel
        dest = target / rel
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
        elif source.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    return target


def _restore_paths_from_backup(repo: Path, backup: Path, before: dict[str, str | None]) -> None:
    for rel, original_hash in before.items():
        target = repo / rel
        source = backup / rel
        if original_hash is None:
            if target.is_file() or target.is_symlink():
                target.unlink(missing_ok=True)
            continue
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _configure(repo: Path, kit: Path, answers: dict) -> None:
    from _installer_config import configure_adapters_and_mcp, generate_product_py

    generate_product_py(repo, answers)
    configure_adapters_and_mcp(repo, answers)
    _managed_exclude(repo)


def _safe_replace_dir(src: Path, dst: Path, *, retries: int = 5, delay: float = 0.15, fallback_copy: bool = True) -> None:
    """Move or replace src directory into dst with retry and Windows locking resilience."""
    for attempt in range(retries):
        gc.collect()
        try:
            os.replace(src, dst)
            return
        except (PermissionError, OSError) as exc:
            if attempt == retries - 1:
                if not fallback_copy:
                    raise
                try:
                    gc.collect()
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    shutil.rmtree(src, ignore_errors=True)
                    return
                except Exception:
                    raise exc
            time.sleep(delay * (attempt + 1))


def _safe_restore_from_backup(backup_agents: Path, target_agents: Path) -> None:
    """Safely restore .agents directory from backup without destructive loss."""
    if not backup_agents.is_dir():
        return
    gc.collect()
    if target_agents.exists():
        shutil.rmtree(target_agents, ignore_errors=True)
    shutil.copytree(backup_agents, target_agents, dirs_exist_ok=True)


def _install_engine(repo: Path, kit: Path, answers: dict, *, init_context: bool = False) -> None:
    def ignored(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in {"state", "cache", "__pycache__"} or name.endswith((".pyc", ".pyo"))}

    required = sum(
        path.stat().st_size for path in (kit / "agents").rglob("*")
        if path.is_file() and not ({"state", "cache", "__pycache__"} & set(path.relative_to(kit / "agents").parts)) and path.suffix not in {".pyc", ".pyo"}
    )
    if shutil.disk_usage(repo).free < max(required * 3, 16 * 1024 * 1024):
        raise ValidationError("insufficient free space for staged install and rollback")
    staging = Path(tempfile.mkdtemp(prefix=".agents-stage-", dir=str(repo)))
    try:
        shutil.copytree(kit / "agents", staging / ".agents", ignore=ignored)
        state = staging / ".agents" / "state"
        if state.exists():
            shutil.rmtree(state)
        state.mkdir(parents=True)
        (state / ".gitkeep").touch()
        _safe_replace_dir(staging / ".agents", repo / ".agents", fallback_copy=True)
        _configure(repo, kit, answers)
        if init_context:
            sublog("extracting project facts & architectural views...")
            from project_context import extract_consistent_project_context, render_project_context, write_project_context
            facts_payload = extract_consistent_project_context(repo, in_memory_graph=True)
            views = render_project_context(facts_payload)
            write_project_context(repo, facts_payload, views)
            from architecture_policy import create_architecture_policy, write_architecture_policy
            pref_family = answers.get("preferred_new_code_family")
            target_family = None if (not pref_family or pref_family == "none") else pref_family
            write_architecture_policy(
                repo,
                create_architecture_policy(preferred_new_code_family=target_family),
                overwrite=True,
            )
        sublog("validating installed Python scripts...")
        for source in (repo / ".agents" / "scripts").rglob("*.py"):
            try:
                compile(source.read_bytes(), str(source), "exec")
            except (OSError, SyntaxError) as exc:
                raise ValidationError(f"installed Python script failed syntax validation: {source.name}") from exc
        required_paths = [
            repo / ".agents" / "VERSION",
            repo / ".agents" / "rules" / "harness-rules.md",
            repo / ".agents" / "scripts" / "_product.py",
        ]
        if init_context:
            required_paths.extend([
                repo / ".agents" / "project-context" / "project-facts.json",
                repo / ".agents" / "project-context" / "architecture-policy.json",
            ])
        for required_path in required_paths:
            if not required_path.is_file():
                raise ValidationError(f"installed harness is incomplete: {required_path.relative_to(repo)}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _warm_project_graph(repo: Path) -> tuple[bool, str | None]:
    try:
        from _graph_core import GraphEngine
        engine = GraphEngine(repo)
        engine.sync(force_full=True)
        engine.save_cache()
        return True, None
    except Exception as exc:
        sanitized = (
            f"Graph cache warm-up failed ({type(exc).__name__}). "
            "Run: python .agents/harness.py doctor --json"
        )
        print(f"[WARN] {sanitized}")
        return False, sanitized


def _uninstall_journal_path(repo: Path) -> Path:
    return repo / ".harness-setup" / "uninstall-journal.json"


def _resolve_uninstall_backup(repo: Path, raw: str) -> Path:
    if not raw:
        raise ValidationError("uninstall recovery journal is missing its backup path")
    candidate = Path(raw)
    candidate = candidate.resolve() if candidate.is_absolute() else (repo / candidate).resolve()
    backup_root = (repo / ".harness-backup").resolve()
    try:
        candidate.relative_to(backup_root)
    except ValueError as exc:
        raise ValidationError("uninstall recovery backup escapes .harness-backup") from exc
    if not candidate.is_dir():
        raise ValidationError("uninstall recovery backup is missing; refusing lifecycle mutation")
    return candidate


def _restore_git_exclude(repo: Path, journal: dict) -> None:
    path = _git_exclude_path(repo)
    encoded = journal.get("git_exclude_base64")
    if encoded is None:
        path.unlink(missing_ok=True)
        return
    try:
        payload = base64.b64decode(str(encoded), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValidationError("uninstall recovery journal contains invalid Git exclude data") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, payload)


def recover_interrupted_uninstall(repo: Path) -> dict | None:
    """Finish a committed uninstall or restore the exact pre-uninstall harness state."""
    journal_path = _uninstall_journal_path(repo)
    if not journal_path.is_file():
        return None
    try:
        journal = read_json(journal_path)
    except Exception as exc:
        raise ValidationError(f"uninstall recovery journal is unreadable; refusing lifecycle mutation: {exc}") from exc
    if journal.get("schema_version") != 1:
        raise ValidationError("uninstall recovery journal has an unsupported schema")

    stage = str(journal.get("stage") or "")
    if stage == "UNINSTALLED":
        backup_root = repo / ".harness-backup"
        setup_root = repo / ".harness-setup"
        if backup_root.exists():
            shutil.rmtree(backup_root)
        if setup_root.exists():
            shutil.rmtree(setup_root)
        return {"status": "RECOVERED", "action": "completed_uninstall"}

    backup = _resolve_uninstall_backup(repo, str(journal.get("backup") or ""))
    before = journal.get("before")
    if not isinstance(before, dict):
        raise ValidationError("uninstall recovery journal is missing its file snapshot")
    git_config = journal.get("git_config")
    if not isinstance(git_config, dict):
        raise ValidationError("uninstall recovery journal is missing its Git configuration snapshot")

    if (backup / ".agents").is_dir():
        _safe_restore_from_backup(backup / ".agents", repo / ".agents")
    _restore_paths_from_backup(repo, backup, before)
    _restore_git_exclude(repo, journal)
    for key, value in git_config.items():
        _restore_git_config(repo, str(key), None if value is None else str(value))
    recovery_raw = str(journal.get("recovery") or "")
    if recovery_raw:
        recovery = (repo / recovery_raw).resolve()
        try:
            recovery.relative_to((repo / ".harness-recovery").resolve())
        except ValueError as exc:
            raise ValidationError("uninstall recovery path escapes .harness-recovery") from exc
        shutil.rmtree(recovery, ignore_errors=True)
        recovery_root = repo / ".harness-recovery"
        if recovery_root.is_dir() and not any(recovery_root.iterdir()):
            recovery_root.rmdir()
    shutil.rmtree(backup)
    journal_path.unlink(missing_ok=True)
    return {"status": "RECOVERED", "action": "restored_pre_uninstall_state"}


def recover_interrupted_update(repo: Path) -> dict | None:
    journal_path = repo / ".harness-setup" / "update-journal.json"
    if not journal_path.is_file():
        return None
    try:
        journal = read_json(journal_path)
    except Exception as exc:
        raise ValidationError(f"update recovery journal is unreadable; refusing lifecycle mutation: {exc}") from exc
    status = str(journal.get("status") or "")
    stage = str(journal.get("stage") or "")
    prev_dirs = sorted(repo.glob(".agents.previous-*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    agents_dir = repo / ".agents"
    target_version = str(journal.get("to_version") or "")

    is_agents_complete = (
        agents_dir.is_dir()
        and (agents_dir / "VERSION").is_file()
        and (agents_dir / "scripts" / "_product.py").is_file()
        and (agents_dir / "rules" / "harness-rules.md").is_file()
    )
    if status == "COMPLETED" or stage == "COMPLETED":
        return None
    if not (repo / OWNERSHIP_RELATIVE).is_file():
        return None
    if (status == "ROLLED_BACK" or stage == "ROLLED_BACK") and is_agents_complete:
        return None

    if stage == "PREPARED" and is_agents_complete:
        journal["status"] = "ROLLED_BACK"
        journal["stage"] = "ROLLED_BACK"
        journal["recovered_at"] = utc_now()
        atomic_write_json(journal_path, journal)
        preserve_root = journal.get("preserve_root")
        if preserve_root:
            shutil.rmtree(repo / preserve_root, ignore_errors=True)
        return {"status": "RECOVERED", "action": "aborted_prepared_update"}

    forward_valid = False
    if stage == "OWNERSHIP_WRITTEN" and is_agents_complete:
        try:
            version_file = agents_dir / "VERSION"
            version_matches = version_file.read_text(encoding="utf-8").strip() == target_version
            if version_matches:
                own_data = _read_ownership(repo)
                if own_data.get("harness_version") == target_version:
                    journal_own_sha = journal.get("ownership_after_sha256")
                    if not journal_own_sha or own_data.get("ownership_sha256") == journal_own_sha:
                        forward_valid = True
        except Exception:
            forward_valid = False

    if forward_valid:
        journal["status"] = "COMPLETED"
        journal["stage"] = "COMPLETED"
        journal["recovered_at"] = utc_now()
        atomic_write_json(journal_path, journal)
        for p in prev_dirs:
            shutil.rmtree(p, ignore_errors=True)
        preserve_root = journal.get("preserve_root")
        if preserve_root:
            shutil.rmtree(repo / preserve_root, ignore_errors=True)
        return {"status": "RECOVERED", "action": "completed_new_engine"}
    old_target = None
    if journal.get("old_agents_path"):
        cand = repo / str(journal["old_agents_path"])
        if cand.is_dir():
            old_target = cand
    if not old_target and prev_dirs:
        old_target = prev_dirs[0]

    backup_raw = str(journal.get("backup") or "")
    if not old_target and backup_raw:
        backup_cand = (repo / backup_raw).resolve() if not Path(backup_raw).is_absolute() else Path(backup_raw)
        if (backup_cand / ".agents").is_dir():
            old_target = backup_cand / ".agents"

    if old_target:
        if agents_dir.exists():
            shutil.rmtree(agents_dir, ignore_errors=True)
        if old_target.name.startswith(".agents.previous-"):
            _safe_replace_dir(old_target, agents_dir, fallback_copy=True)
        else:
            _safe_restore_from_backup(old_target, agents_dir)
        journal["status"] = "ROLLED_BACK"
        journal["stage"] = "ROLLED_BACK"
        journal["recovered_at"] = utc_now()
        atomic_write_json(journal_path, journal)
        for p in prev_dirs:
            if p != old_target:
                shutil.rmtree(p, ignore_errors=True)
        preserve_root = journal.get("preserve_root")
        if preserve_root:
            shutil.rmtree(repo / preserve_root, ignore_errors=True)
        return {"status": "RECOVERED", "action": "restored_previous_engine"}
    return None


def install(repo: Path, kit: Path) -> dict:
    repo = _validate_repo(repo)
    _assert_kit_outside_repo(repo, kit)
    recover_interrupted_uninstall(repo)
    recover_interrupted_update(repo)
    kit, version = _validate_kit(kit)
    if (repo / ".agents").exists() or (repo / OWNERSHIP_RELATIVE).exists():
        raise ValidationError("target already contains a harness; uninstall it before the clean vNext install")
    answers = _load_answers(repo)
    git_config_before = {"core.hooksPath": _git_config_value(repo, "core.hooksPath")}
    with step_progress("1. Creating pre-install application snapshot"):
        app_before = _snapshot_app_files(repo)
        before = _snapshot_files(repo, _candidate_adapter_paths(repo))
        backup = _backup(repo, None, "install", _candidate_adapter_paths(repo))
    try:
        with step_progress("2. Installing harness engine files"):
            _install_engine(repo, kit, answers, init_context=True)
        with step_progress("3. Verifying application integrity"):
            allowed_adapters = set(before) | {p.relative_to(repo).as_posix() for p in _candidate_adapter_paths(repo)}
            _verify_app_snapshot(repo, app_before, allowed_adapters)
        with step_progress("4. Recording ownership manifest"):
            ownership = _write_ownership(
                repo, version=version, before=before, backup=backup, git_config_before=git_config_before,
            )
        with step_progress("5. Warming project graph cache"):
            graph_cache_warmed, graph_cache_warning = _warm_project_graph(repo)
    except Exception:
        if (repo / ".agents").exists():
            shutil.rmtree(repo / ".agents", ignore_errors=True)
        _rollback_adapters(repo, backup, before)
        for key, value in git_config_before.items():
            _restore_git_config(repo, key, value)
        _managed_exclude(repo, remove=True)
        raise
    result = {
        "status": "PASS",
        "action": "install",
        "version": version,
        "ownership": ownership,
        "backup": str(backup),
        "app_snapshot_verified": True,
        "graph_cache_warmed": graph_cache_warmed,
    }
    if not graph_cache_warmed and graph_cache_warning:
        result["graph_cache_warning"] = graph_cache_warning
    return result


def require_update_idle(repo: Path) -> None:
    """Retained terminal pointers are history; uncertain or live tasks block update."""
    root = repo.resolve()
    state = root / ".agents/state"
    pointer = state / "active-task.json"
    if not pointer.exists() and not pointer.is_symlink():
        return
    active = read_json(pointer)
    task_id = str(active.get("task_id") or "")
    reference = str(active.get("plan_path") or "")
    if not task_id or not reference:
        raise ValidationError("active task identity is incomplete; update refused")
    path = Path(reference)
    path = (path if path.is_absolute() else root / path).resolve()
    if state.resolve() not in path.parents:
        raise ValidationError("active plan path escapes harness state; update refused")
    plan = read_json(path)
    if plan.get("task_id") != task_id:
        raise ValidationError("active task identity mismatch; update refused")
    if plan.get("status") not in {"CANCELLED", "DELIVERED"}:
        raise ValidationError(
            f"compatible update refused while active task '{task_id}' exists; "
            f"finish or cancel the task before updating (run: python .agents/scripts/workflow.py cancel --repo . --task-id {task_id})"
        )


def update(repo: Path, kit: Path, answers: dict | None = None) -> dict:
    repo = _validate_repo(repo)
    _assert_kit_outside_repo(repo, kit)
    answers = dict(answers or {})
    recover_interrupted_uninstall(repo)
    recover_interrupted_update(repo)
    require_update_idle(repo)
    kit, target_version = _validate_kit(kit)
    ownership = _read_ownership(repo)
    git_config_transaction_before = {"core.hooksPath": _git_config_value(repo, "core.hooksPath")}
    current_version = str(ownership.get("harness_version") or "")
    if _version_tuple(current_version)[0] != ARCHITECTURE_MAJOR:
        raise ValidationError("legacy in-place migration is unsupported; perform a clean reinstall")
    if _version_tuple(target_version) < _version_tuple(current_version):
        raise ValidationError("downgrade refused: compatible downgrade metadata is unavailable")
    conflicts = []
    legacy_ref_prefix = ".agents/skills/android-harness/references/"
    for entry in ownership.get("entries") or []:
        rel = str(entry.get("path") or "")
        path = repo / rel
        current_hash = _hash_or_none(path)
        if current_hash != entry.get("post_install_sha256") and not any(Path(rel).match(pattern) for pattern in PRESERVE_GLOBS):
            if rel.startswith(legacy_ref_prefix):
                continue
            conflicts.append(rel)
    if conflicts:
        raise ValidationError(
            "user-modified managed files require clean recovery "
            "(run 'python harness_cli.py uninstall --apply' then 'python harness_cli.py init --answers-json <answers.json>'): "
            + ", ".join(conflicts[:10])
        )
    loaded_answers = _load_answers(repo)
    if answers:
        loaded_answers.update(answers)
    answers = loaded_answers
    with step_progress("1. Creating pre-update snapshot & backup"):
        app_before = _snapshot_app_files(repo)
        before = _snapshot_files(repo, _candidate_adapter_paths(repo))
        backup = _backup(repo, ownership, "update", _candidate_adapter_paths(repo))
        preserve_root = repo / ".harness-recovery" / f"preserve-{uuid.uuid4().hex}"
        preserved = _copy_preserved(repo, preserve_root, refresh_defaults=True)
        legacy_migrated = [
            rel for rel in preserved
            if rel.startswith(".agents/project-context/legacy-overrides/")
        ]
        old_agents = repo / f".agents.previous-{uuid.uuid4().hex}"
        journal = {
            "schema_version": 1,
            "transaction_id": uuid.uuid4().hex,
            "status": "PREPARED",
            "stage": "PREPARED",
            "from_version": current_version,
            "to_version": target_version,
            "old_agents_path": str(old_agents.relative_to(repo).as_posix()),
            "preserve_root": str(preserve_root.relative_to(repo).as_posix()),
            "backup": str(backup),
            "ownership_before_sha256": ownership.get("ownership_sha256"),
            "ownership_after_sha256": None,
            "legacy_reference_migrated": legacy_migrated,
            "started_at": utc_now(),
        }
        journal_path = repo / ".harness-setup" / "update-journal.json"
        atomic_write_json(journal_path, journal)

    def _set_stage(st: str) -> None:
        journal["stage"] = st
        journal["updated_at"] = utc_now()
        atomic_write_json(journal_path, journal)

    try:
        with step_progress("2. Installing updated harness engine"):
            _safe_replace_dir(repo / ".agents", old_agents, fallback_copy=True)
            _set_stage("OLD_ENGINE_MOVED")

            _install_engine(repo, kit, answers, init_context=False)
            _set_stage("NEW_ENGINE_INSTALLED")

            if (old_agents / "state").is_dir():
                shutil.copytree(old_agents / "state", repo / ".agents/state", dirs_exist_ok=True)
            _set_stage("STATE_RESTORED")

            _restore_preserved(repo, preserve_root, preserved)

            mode = str(answers.get("update_context_mode") or "preserve").lower()
            if mode not in {"preserve", "refresh", "auto"}:
                mode = "preserve"

            if mode == "preserve":
                facts_file = repo / ".agents" / "project-context" / "project-facts.json"
                if not facts_file.is_file():
                    raise ValidationError("CONTEXT_REFRESH_REQUIRED: missing project-facts.json")
                try:
                    facts = read_json(facts_file)
                    if facts.get("schema_version") not in (1, 2):
                        raise ValidationError("CONTEXT_REFRESH_REQUIRED: incompatible project-facts.json schema")
                except Exception as exc:
                    raise ValidationError(f"CONTEXT_REFRESH_REQUIRED: {exc}")
            elif mode in ("refresh", "auto"):
                from project_context import extract_consistent_project_context, render_project_context, write_project_context
                fresh_facts = extract_consistent_project_context(repo, in_memory_graph=True)
                fresh_views = render_project_context(fresh_facts)
                write_project_context(repo, fresh_facts, fresh_views)
                from architecture_policy import read_architecture_policy, compute_policy_hash, write_architecture_policy
                curr_pol = read_architecture_policy(repo)
                if curr_pol:
                    pref_family = curr_pol.get("preferred_new_code_family") or curr_pol.get("default_family")
                    if pref_family and pref_family != "none":
                        arch_obj = fresh_facts.get("facts", {}).get("architecture") or fresh_facts.get("architecture") or {}
                        existing_fam_ids = {f.get("id") for f in arch_obj.get("families") or []}
                        if pref_family not in existing_fam_ids:
                            curr_pol["status"] = "ARCHITECTURE_DECISION_REQUIRED"
                            curr_pol["decision_reason"] = f"previously preferred family '{pref_family}' is no longer detected after refresh"
                            curr_pol["policy_sha256"] = compute_policy_hash(curr_pol)
                            write_architecture_policy(repo, curr_pol, overwrite=True)
            _set_stage("CONTEXT_RESTORED")

        with step_progress("3. Verifying application integrity"):
            allowed_adapters = set(before) | {p.relative_to(repo).as_posix() for p in _candidate_adapter_paths(repo)}
            _verify_app_snapshot(repo, app_before, allowed_adapters)
            _set_stage("APP_SNAPSHOT_VERIFIED")

        with step_progress("4. Updating ownership manifest"):
            new_ownership = _write_ownership(repo, version=target_version, before=before, backup=backup, previous=ownership)
            journal["ownership_after_sha256"] = new_ownership.get("ownership_sha256")
            _set_stage("OWNERSHIP_WRITTEN")

        with step_progress("5. Warming project graph cache"):
            graph_cache_warmed, graph_cache_warning = _warm_project_graph(repo)
            journal["status"] = "COMPLETED"
            _set_stage("COMPLETED")
            journal["completed_at"] = utc_now()
            atomic_write_json(journal_path, journal)
            shutil.rmtree(old_agents, ignore_errors=True)
    except Exception:
        if old_agents.exists():
            shutil.rmtree(repo / ".agents", ignore_errors=True)
            _safe_replace_dir(old_agents, repo / ".agents", fallback_copy=True)
        elif backup and (backup / ".agents").is_dir() and not (repo / ".agents" / "VERSION").is_file():
            _safe_restore_from_backup(backup / ".agents", repo / ".agents")
        _rollback_adapters(repo, backup, before)
        for key, value in git_config_transaction_before.items():
            _restore_git_config(repo, key, value)
        journal["status"] = "ROLLED_BACK"
        journal["stage"] = "ROLLED_BACK"
        journal["rolled_back_at"] = utc_now()
        atomic_write_json(journal_path, journal)
        raise
    finally:
        shutil.rmtree(preserve_root, ignore_errors=True)
    if legacy_migrated:
        print("[MIGRATE] Preserved legacy reference customizations in .agents/project-context/legacy-overrides/: " + ", ".join(Path(m).name for m in legacy_migrated))
    result = {
        "status": "PASS",
        "action": "update",
        "from_version": current_version,
        "version": target_version,
        "ownership": new_ownership,
        "backup": str(backup),
        "app_snapshot_verified": True,
        "legacy_reference_migrated": legacy_migrated,
        "graph_cache_warmed": graph_cache_warmed,
    }
    if not graph_cache_warmed and graph_cache_warning:
        result["graph_cache_warning"] = graph_cache_warning
    return result


def replace_legacy(repo: Path, kit: Path) -> dict:
    """Atomically replace a pre-v1 engine in one process with rollback."""
    repo = _validate_repo(repo)
    _assert_kit_outside_repo(repo, kit)
    recover_interrupted_uninstall(repo)
    recover_interrupted_update(repo)
    kit, target_version = _validate_kit(kit)
    if not (repo / ".agents").is_dir():
        raise ValidationError("legacy replacement requires an existing .agents directory")
    if (repo / OWNERSHIP_RELATIVE).exists():
        raise ValidationError("managed v1 installations must use same-major update, not legacy replacement")
    answers = _load_answers(repo)
    git_config_before = {"core.hooksPath": _git_config_value(repo, "core.hooksPath")}
    with step_progress("1. Creating pre-replacement snapshot & backup"):
        app_before = _snapshot_app_files(repo)
        adapters = _candidate_adapter_paths(repo)
        before = _snapshot_files(repo, adapters)
        backup = _backup(repo, None, "replace-legacy", adapters)
        preserve_root = repo / ".harness-recovery" / f"legacy-preserve-{uuid.uuid4().hex}"
        preserved = _legacy_preserved_paths(kit, _copy_preserved(repo, preserve_root))
        old_agents = repo / f".agents.previous-{uuid.uuid4().hex}"
        has_prior_facts = (repo / ".agents" / "project-context" / "project-facts.json").is_file()
    try:
        with step_progress("2. Installing replacement harness engine"):
            _safe_replace_dir(repo / ".agents", old_agents, fallback_copy=True)
            _install_engine(repo, kit, answers, init_context=(not has_prior_facts))
            _restore_preserved(repo, preserve_root, preserved)
        with step_progress("3. Verifying application integrity"):
            allowed_adapters = set(before) | {p.relative_to(repo).as_posix() for p in adapters}
            _verify_app_snapshot(repo, app_before, allowed_adapters)
        with step_progress("4. Recording ownership manifest"):
            ownership = _write_ownership(
                repo, version=target_version, before=before, backup=backup, git_config_before=git_config_before,
            )
        with step_progress("5. Warming project graph cache"):
            graph_cache_warmed, graph_cache_warning = _warm_project_graph(repo)
            shutil.rmtree(old_agents, ignore_errors=True)
    except Exception:
        if old_agents.exists():
            shutil.rmtree(repo / ".agents", ignore_errors=True)
            _safe_replace_dir(old_agents, repo / ".agents", fallback_copy=True)
        elif backup and (backup / ".agents").is_dir() and not (repo / ".agents" / "VERSION").is_file():
            _safe_restore_from_backup(backup / ".agents", repo / ".agents")
        _rollback_adapters(repo, backup, before)
        for key, value in git_config_before.items():
            _restore_git_config(repo, key, value)
        _managed_exclude(repo, remove=True)
        (repo / OWNERSHIP_RELATIVE).unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(preserve_root, ignore_errors=True)
    result = {
        "status": "PASS",
        "action": "replace-legacy",
        "version": target_version,
        "ownership": ownership,
        "backup": str(backup),
        "preserved": preserved,
        "app_snapshot_verified": True,
        "graph_cache_warmed": graph_cache_warmed,
    }
    if not graph_cache_warmed and graph_cache_warning:
        result["graph_cache_warning"] = graph_cache_warning
    return result


def uninstall(repo: Path, *, apply: bool = False, legacy: bool = False) -> dict:
    repo = _validate_repo(repo)
    recovered_uninstall = recover_interrupted_uninstall(repo)
    if recovered_uninstall and recovered_uninstall.get("action") == "completed_uninstall":
        return {
            "status": "PASS", "action": "uninstall", "removed": [], "preserved": [],
            "backup": None, "recovery": None, "recovered": True,
        }
    recover_interrupted_update(repo)
    ownership = None
    try:
        ownership = _read_ownership(repo)
    except ValidationError:
        if not legacy:
            raise
    paths = [str(entry.get("path") or "") for entry in (ownership or {}).get("entries") or []]
    if legacy:
        generated = []
        for path in _candidate_adapter_paths(repo):
            try:
                head = path.read_text(encoding="utf-8", errors="replace")[:2000].lower()
            except OSError:
                continue
            if "managed-by: android-harness-kit" in head or "android agent harness" in head:
                generated.append(path.relative_to(repo).as_posix())
        paths = [".agents", *generated]
    preview = sorted(set(path for path in paths if path))
    if not apply:
        actions = [
            {
                "path": rel,
                "action": "restore" if next(
                    (entry.get("pre_install_sha256") for entry in (ownership or {}).get("entries") or [] if entry.get("path") == rel),
                    None,
                ) else "remove",
            }
            for rel in preview
        ]
        actions.extend([
            {"path": ".harness-setup", "action": "remove-owned-state"},
            {"path": ".harness-backup", "action": "remove-owned-backups"},
        ])
        return {"status": "DRY_RUN", "action": "uninstall", "paths": preview, "actions": actions, "legacy": legacy}
    adapters = _candidate_adapter_paths(repo)
    transaction_paths = [*adapters, repo / OWNERSHIP_RELATIVE, repo / ".harness-setup" / "answers.json"]
    before = _snapshot_files(repo, transaction_paths)
    backup = _backup(repo, ownership, "uninstall", transaction_paths)
    recovery = repo / ".harness-recovery" / f"uninstall-{uuid.uuid4().hex}"
    git_keys = {"core.hooksPath", *(((ownership or {}).get("git_config") or {}).keys())}
    git_config_current = {str(key): _git_config_value(repo, str(key)) for key in sorted(git_keys)}
    exclude_path = _git_exclude_path(repo)
    exclude_bytes = exclude_path.read_bytes() if exclude_path.is_file() else None
    journal = {
        "schema_version": 1,
        "transaction_id": uuid.uuid4().hex,
        "status": "PREPARED",
        "stage": "PREPARED",
        "backup": str(backup.relative_to(repo).as_posix()),
        "recovery": str(recovery.relative_to(repo).as_posix()),
        "before": before,
        "git_config": git_config_current,
        "git_exclude_base64": base64.b64encode(exclude_bytes).decode("ascii") if exclude_bytes is not None else None,
        "started_at": utc_now(),
    }
    journal_path = _uninstall_journal_path(repo)
    atomic_write_json(journal_path, journal)
    removed: list[str] = []
    preserved: list[str] = []
    try:
        if legacy and (repo / ".agents").is_dir():
            shutil.copytree(repo / ".agents", recovery / ".agents", dirs_exist_ok=True)
            shutil.rmtree(repo / ".agents")
            removed.append(".agents")
            for rel in preview:
                if rel == ".agents":
                    continue
                path = repo / rel
                if path.is_file():
                    path.unlink()
                    removed.append(rel)
        else:
            for entry in sorted((ownership or {}).get("entries") or [], key=lambda item: len(str(item.get("path") or "")), reverse=True):
                rel = str(entry.get("path") or "")
                path = repo / rel
                original_hash = entry.get("pre_install_sha256")
                post_hash = entry.get("post_install_sha256")
                if not path.is_file() and not (original_hash and post_hash is None):
                    continue
                modified = _hash_or_none(path) != post_hash
                if modified:
                    target = recovery / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                    preserved.append(rel)
                install_backup_raw = str((ownership or {}).get("install_backup") or "")
                backup_root = (repo / install_backup_raw).resolve() if install_backup_raw and not Path(install_backup_raw).is_absolute() else Path(install_backup_raw)
                original = backup_root / rel if install_backup_raw else None
                if original_hash and original and original.is_file():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, path)
                else:
                    path.unlink(missing_ok=True)
                removed.append(rel)
            agents = repo / ".agents"
            if agents.is_dir():
                shutil.rmtree(agents)
        _managed_exclude(repo, remove=True)
        for key, values in ((ownership or {}).get("git_config") or {}).items():
            if isinstance(values, dict):
                _restore_git_config(repo, str(key), values.get("before"))
        (repo / OWNERSHIP_RELATIVE).unlink(missing_ok=True)
        (repo / ".harness-setup" / "update-journal.json").unlink(missing_ok=True)
        journal["status"] = "COMPLETED"
        journal["stage"] = "UNINSTALLED"
        journal["completed_at"] = utc_now()
        atomic_write_json(journal_path, journal)
    except Exception:
        recover_interrupted_uninstall(repo)
        raise

    shutil.rmtree(repo / ".harness-backup")
    shutil.rmtree(repo / ".harness-setup")
    if not preserved and not legacy:
        shutil.rmtree(recovery, ignore_errors=True)
        recovery_root = repo / ".harness-recovery"
        if recovery_root.is_dir() and not any(recovery_root.iterdir()):
            recovery_root.rmdir()
    return {"status": "PASS", "action": "uninstall", "removed": removed, "preserved": preserved, "backup": None, "recovery": str(recovery) if preserved or legacy else None}


def main(argv: list[str] | None = None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("install", "update", "replace-legacy"):
        command = sub.add_parser(name)
        command.add_argument("--repo", required=True)
        command.add_argument("--kit", required=True)
    command = sub.add_parser("recover-interrupted-update")
    command.add_argument("--repo", required=True)
    command = sub.add_parser("uninstall")
    command.add_argument("--repo", required=True)
    command.add_argument("--apply", action="store_true")
    command.add_argument("--legacy", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "install":
            result = install(Path(args.repo), Path(args.kit))
        elif args.action == "update":
            result = update(Path(args.repo), Path(args.kit))
        elif args.action == "replace-legacy":
            result = replace_legacy(Path(args.repo), Path(args.kit))
        elif args.action == "recover-interrupted-update":
            result = recover_interrupted_update(Path(args.repo)) or {"status": "PASS", "action": "recover-interrupted-update", "recovered": False}
        else:
            result = uninstall(Path(args.repo), apply=args.apply, legacy=args.legacy)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result.get("status") == "DRY_RUN":
            print(f"[DRY_RUN] {result['action']}")
            for item in result.get("actions") or []:
                print(f"  - {item['action']}: {item['path']}")
        else:
            print(f"[{result['status']}] {result['action']}")
        return 0
    except (HarnessError, OSError, RuntimeError, shutil.Error) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
