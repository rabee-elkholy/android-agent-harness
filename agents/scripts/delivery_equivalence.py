"""Conservative post-ready source equivalence bound to the verified delivery tree.

This cache is supporting evidence, never a replacement for the frozen manifest.
Unknown syntax, resource changes, missing bindings and mode changes fail closed.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from _vnext_common import (
    HarnessError, ValidationError, atomic_write_bytes, atomic_write_json, canonical_sha256,
    git_text, read_json, sha256_bytes, state_root, utc_now, validate_id,
    validate_repo_path_containment,
)

SCHEMA_VERSION = 2
SOURCE_SUFFIXES = {".kt", ".java", ".kts"}
DATA_DIRECTORIES = {"assets", "res", "resources"}
REGULAR_FILE_MODES = {"100644", "100755"}
SECRET_PATH_MARKERS = (".env", "keystore", "jks", "secret", "token", "credentials", "local.properties")
IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
QUALIFIED = rf"{IDENTIFIER}(?:\.{IDENTIFIER})*"
PACKAGE = re.compile(rf"[ \t]*package[ \t]+{QUALIFIED}[ \t]*;?[ \t]*(?:\n|$)")
IMPORTS = {
    ".kt": re.compile(rf"[ \t]*import[ \t]+{QUALIFIED}(?:[ \t]+as[ \t]+{IDENTIFIER})?[ \t]*;?[ \t]*(?:\n|$)"),
    ".java": re.compile(rf"[ \t]*import[ \t]+(?:static[ \t]+)?{QUALIFIED}[ \t]*;[ \t]*(?:\n|$)"),
}


def task_dir(repo: Path, task_id: str) -> Path:
    return state_root(repo) / "tasks" / validate_id(task_id, "task id")


def _verified_dir(repo: Path, task_id: str, run_id: str) -> Path:
    return task_dir(repo, task_id) / "verified-files" / validate_id(run_id, "run id")


def _file_identities(manifest: dict) -> dict[str, dict]:
    if manifest.get("schema_version") != 1:
        raise ValidationError("unsupported delivery manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValidationError("verified manifest has no file identities")
    result = {}
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"] or item["path"] in result:
            raise ValidationError("invalid or duplicate manifest file")
        if not isinstance(item.get("content_identity"), str) or not isinstance(item.get("git_mode"), str):
            raise ValidationError("manifest file identity or mode is missing")
        result[item["path"]] = {key: item[key] for key in ("path", "content_identity", "git_mode", "worktree_git_mode") if key in item}
    if canonical_sha256(list(result.values())) != manifest.get("delivery_snapshot_sha256"):
        raise ValidationError("manifest file identities do not match its snapshot")
    return result


def _ready_manifest(repo: Path, task_id: str, plan: dict) -> tuple[str, dict, dict]:
    run_id = validate_id(str(plan.get("ready_run_id") or ""), "run id")
    manifest = read_json(task_dir(repo, task_id) / f"manifest-{run_id}.json")
    files = _file_identities(manifest)
    if plan.get("task_id") != task_id:
        raise ValidationError("task identity mismatch")
    for field, plan_field in (("delivery_snapshot_sha256", "ready_delivery_snapshot_sha256"), ("change_set_sha256", "ready_change_set_sha256")):
        if not plan.get(plan_field) or manifest.get(field) != plan[plan_field]:
            raise ValidationError(f"verified {field} binding mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(plan.get("plan_sha256") or "")):
        raise ValidationError("verified plan identity is missing")
    return run_id, manifest, files


def _bindings(task_id: str, run_id: str, plan: dict, manifest: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "task_id": task_id, "run_id": run_id,
        "plan_sha256": plan["plan_sha256"],
        "delivery_snapshot_sha256": manifest["delivery_snapshot_sha256"],
        "change_set_sha256": manifest["change_set_sha256"],
        "verified_manifest_sha256": canonical_sha256(manifest),
        "repository": manifest["repository"],
    }


def _content_identity(repo: Path, rel: str, content: bytes) -> str:
    return "git:" + git_text(repo, "hash-object", "--path", rel, "--stdin", input_bytes=content)


def _supports_source_equivalence(rel: str) -> bool:
    path = Path(rel.replace("\\", "/"))
    return path.suffix.lower() in SOURCE_SUFFIXES and not any(
        part.lower() in DATA_DIRECTORIES for part in path.parts[:-1]
    )


def snapshot_verified_files(repo: Path, task_id: str, plan: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Capture source bytes only if they still match the frozen, approved run."""
    root = repo.resolve()
    ready_run, manifest, identities = _ready_manifest(root, task_id, plan)
    if ready_run != run_id:
        raise ValidationError("snapshot run identity mismatch")
    from delivery_manifest import build_manifest
    live = build_manifest(root)
    if live["delivery_snapshot_sha256"] != manifest["delivery_snapshot_sha256"]:
        raise ValidationError("repository changed before verified source capture")
    if live["repository"] != manifest["repository"]:
        raise ValidationError("repository identity changed before verified source capture")
    directory = _verified_dir(root, task_id, run_id)
    manifest_path = directory / "verified-files-manifest.json"
    existing = read_json(manifest_path) if manifest_path.exists() else None
    changes = manifest.get("task_changes", manifest.get("changes", []))
    paths = {str(c["path"]) for c in changes if isinstance(c, dict) and c.get("path")}
    paths.update(str(p) for p in plan.get("expected_files") or [])
    records = {}
    for rel in sorted(paths):
        identity = identities.get(rel)
        if not identity or not _supports_source_equivalence(rel) or any(marker in rel.lower() for marker in SECRET_PATH_MARKERS):
            continue
        if identity["git_mode"] not in REGULAR_FILE_MODES or identity.get("worktree_git_mode", identity["git_mode"]) not in REGULAR_FILE_MODES:
            continue
        src = root / validate_repo_path_containment(root, rel)
        if not src.is_file() or src.is_symlink() or src.stat().st_size > 5 * 1024 * 1024:
            continue
        content = src.read_bytes()
        if _content_identity(root, rel, content) != identity["content_identity"]:
            raise ValidationError(f"source no longer matches verified identity: {rel}")
        if existing is not None:
            if (directory / rel).read_bytes() != content:
                raise ValidationError(f"immutable source cache differs: {rel}")
        else:
            atomic_write_bytes(directory / rel, content)
        records[rel] = {"sha256": sha256_bytes(content), "size": len(content), **identity}
    # Reject a concurrent edit rather than sealing a cache from an unverified tree.
    if build_manifest(root)["delivery_snapshot_sha256"] != manifest["delivery_snapshot_sha256"]:
        raise ValidationError("repository changed during verified source capture")
    record = {**_bindings(task_id, run_id, plan, manifest), "captured_at": utc_now(), "files": records}
    if existing is not None:
        if any(existing.get(key) != value for key, value in record.items() if key != "captured_at"):
            raise ValidationError("immutable source cache binding mismatch")
        return existing
    atomic_write_json(manifest_path, record)
    return record


def _skip_header_trivia(text: str, offset: int) -> int:
    """Skip leading comments without recognizing import-looking comment text."""
    while offset < len(text):
        if text[offset] in " \t\n":
            offset += 1
        elif text.startswith("//", offset):
            end = text.find("\n", offset)
            offset = len(text) if end < 0 else end + 1
        elif text.startswith("/*", offset):
            depth = 1
            offset += 2
            while offset < len(text) and depth:
                if text.startswith("/*", offset):
                    depth += 1
                    offset += 2
                elif text.startswith("*/", offset):
                    depth -= 1
                    offset += 2
                else:
                    offset += 1
            if depth:
                return len(text)
        else:
            break
    return offset


def _split_kotlin_java(text: str, suffix: str = ".kt") -> tuple[str, list[str], str]:
    """Recognize a simple real package/import prefix; leave unknown syntax intact."""
    offset = _skip_header_trivia(text, 0)
    package = PACKAGE.match(text, offset)
    if package:
        offset = _skip_header_trivia(text, package.end())
    first = offset
    imports = []
    pattern = IMPORTS[suffix]
    while True:
        match = pattern.match(text, offset)
        if not match:
            break
        imports.append(match.group().strip())
        offset = match.end()
        # Only empty lines may be discarded inside the import block.
        blanks = re.match(r"(?:[ \t]*\n)*", text[offset:])
        offset += blanks.end()
    if not imports:
        return "", [], text
    return text[:first], imports, text[offset:]


def _safe_source_whitespace(text: str) -> str | None:
    """Strip line tails only when outside ordinary source literals.

    Raw strings/text blocks are excluded by the caller. An unbalanced literal or
    an unsupported multiline template remains strict rather than guessed safe.
    """
    result = []
    block_depth = 0
    for line in text.split("\n"):
        quote = None
        i = 0
        while i < len(line):
            if block_depth:
                if line.startswith("/*", i):
                    block_depth += 1
                    i += 2
                elif line.startswith("*/", i):
                    block_depth -= 1
                    i += 2
                else:
                    i += 1
            elif quote:
                if line[i] == "\\":
                    i += 2
                elif line[i] == quote:
                    quote = None
                    i += 1
                else:
                    i += 1
            elif line.startswith("//", i):
                break
            elif line.startswith("/*", i):
                block_depth = 1
                i += 2
            elif line[i] in ('"', "'"):
                quote = line[i]
                i += 1
            else:
                i += 1
        if quote:
            return None
        result.append(line.rstrip(" \t"))
    if block_depth:
        return None
    return "\n".join(result).rstrip("\n")


def classify_file_equivalence(verified_bytes: bytes, live_bytes: bytes, rel_path: str) -> tuple[bool, str, str]:
    if verified_bytes == live_bytes:
        return True, "IDENTICAL", "File content is identical."
    suffix = Path(rel_path).suffix.lower()
    if not _supports_source_equivalence(rel_path):
        return False, "CONTENT_MODIFIED", "Resource, data or unsupported source content changed."
    try:
        before = verified_bytes.decode("utf-8")
        after = live_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return False, "BINARY_DIFF", "Non-UTF-8 source difference."
    if any(ch in before + after for ch in ("\0", "\v", "\f")):
        return False, "BINARY_DIFF", "Unsupported control character in source."
    if '"""' in before or '"""' in after:
        return False, "BODY_MODIFIED", "Raw strings/text blocks require exact verified bytes."
    before = before.replace("\r\n", "\n")
    after = after.replace("\r\n", "\n")
    if before == after:
        return True, "LINE_ENDINGS_ONLY", "Source line ending differences only."
    if suffix in IMPORTS:
        h1, imp1, b1 = _split_kotlin_java(before, suffix)
        h2, imp2, b2 = _split_kotlin_java(after, suffix)
        if sorted(imp1) != sorted(imp2):
            added, removed = sorted(set(imp2) - set(imp1)), sorted(set(imp1) - set(imp2))
            return False, "IMPORTS_MODIFIED", f"Import set/count modified (added: {added[:3]}; removed: {removed[:3]})."
        for a, b, label in ((h1, h2, "HEADER_MODIFIED"), (b1, b2, "BODY_MODIFIED")):
            clean_a, clean_b = _safe_source_whitespace(a), _safe_source_whitespace(b)
            if clean_a is None or clean_b is None or clean_a != clean_b:
                return False, label, "Non-import source content changed or syntax is unsupported."
        if imp1 != imp2:
            return True, "IMPORT_REORDER", f"Imports reordered ({len(imp1)} imports preserved in identical set)."
        return True, "TRAILING_WHITESPACE_OR_FORMATTING", "Source trailing whitespace/EOF newline or import spacing only."
    clean_before, clean_after = _safe_source_whitespace(before), _safe_source_whitespace(after)
    if clean_before is not None and clean_after is not None and clean_before == clean_after:
        return True, "TRAILING_WHITESPACE_OR_EOF_NEWLINE", "Source trailing whitespace or EOF newline only."
    return False, "CONTENT_MODIFIED", "Source content changed."


def evaluate_post_ready_changes(repo: Path, task_id: str, plan: dict[str, Any], live_manifest: dict[str, Any]) -> dict[str, Any]:
    def reject(reason: str, detail: str) -> dict:
        return {"is_benign": False, "reason": reason, "normalized_files": [], "diff_summary": detail}
    try:
        root = repo.resolve()
        run_id, ready, before = _ready_manifest(root, task_id, plan)
        after = _file_identities(live_manifest)
        for field in ("root_sha256", "git_common_dir_sha256", "branch"):
            if not ready["repository"].get(field) or ready["repository"][field] != live_manifest["repository"].get(field):
                return reject("REPOSITORY_IDENTITY_MISMATCH", f"Repository {field} differs from verified run.")
        changed = sorted(rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel))
        if not changed:
            return reject("NO_FILE_DIFF_DETECTED", "Snapshot divergence has no bound file difference.")
        directory = _verified_dir(root, task_id, run_id)
        cache = read_json(directory / "verified-files-manifest.json")
        for field, value in _bindings(task_id, run_id, plan, ready).items():
            if cache.get(field) != value:
                return reject("VERIFIED_CACHE_IDENTITY_MISMATCH", f"Verified cache {field} binding mismatch.")
        stored = cache.get("files")
        if not isinstance(stored, dict):
            return reject("VERIFIED_MANIFEST_CORRUPTED", "Verified file records are missing.")
        normalized = []
        for rel in changed:
            if rel not in before or rel not in after:
                return reject("FILE_SET_MODIFIED", f"Verified file added, deleted or renamed: {rel}")
            for field in ("git_mode", "worktree_git_mode"):
                if before[rel].get(field) != after[rel].get(field):
                    return reject("FILE_MODE_MODIFIED", f"Verified file mode changed: {rel}")
            if before[rel]["git_mode"] not in REGULAR_FILE_MODES or before[rel].get("worktree_git_mode", before[rel]["git_mode"]) not in REGULAR_FILE_MODES:
                return reject("UNSUPPORTED_FILE_MODE", f"Only regular source files support normalization: {rel}")
            record = stored.get(rel)
            if not isinstance(record, dict):
                return reject("VERIFIED_FILE_MISSING", f"Changed file has no bound verified source cache: {rel}")
            for field, value in before[rel].items():
                if record.get(field) != value:
                    return reject("VERIFIED_FILE_IDENTITY_MISMATCH", f"Cached source identity mismatch: {rel}")
            original = directory / validate_repo_path_containment(directory, rel)
            target = root / validate_repo_path_containment(root, rel)
            if original.is_symlink() or target.is_symlink() or not original.is_file() or not target.is_file():
                return reject("VERIFIED_FILE_MISSING", f"Source cache/live file is missing or a symlink: {rel}")
            original_bytes, live_bytes = original.read_bytes(), target.read_bytes()
            if record.get("sha256") != sha256_bytes(original_bytes) or record.get("size") != len(original_bytes):
                return reject("VERIFIED_FILE_INTEGRITY_MISMATCH", f"Cached source failed integrity check: {rel}")
            if _content_identity(root, rel, original_bytes) != before[rel]["content_identity"]:
                return reject("VERIFIED_FILE_IDENTITY_MISMATCH", f"Cached source differs from frozen Git identity: {rel}")
            if _content_identity(root, rel, live_bytes) != after[rel]["content_identity"]:
                return reject("LIVE_FILE_IDENTITY_MISMATCH", f"Live source changed during evaluation: {rel}")
            benign, classification, detail = classify_file_equivalence(original_bytes, live_bytes, rel)
            if not benign:
                return reject(classification, f"[{classification}] File '{rel}': {detail}")
            normalized.append({"path": rel, "classification": classification, "detail": detail,
                               "verified_sha256": sha256_bytes(original_bytes), "live_sha256": sha256_bytes(live_bytes)})
        return {"is_benign": True, "reason": "BENIGN_POST_READY_NORMALIZATION", "normalized_files": normalized,
                "diff_summary": ", ".join(f"{item['path']} ({item['classification']})" for item in normalized)}
    except (OSError, ValueError, KeyError, TypeError, HarnessError) as exc:
        return reject("VERIFIED_FILES_UNAVAILABLE", f"Cannot establish verified source equivalence: {exc}")
