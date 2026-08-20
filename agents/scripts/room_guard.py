"""Room schema / migration gate for Rashaqa Android.

Fails a working-tree schema change when version was not incremented, when
Migration(old, new) is missing, when it is not registered with addMigrations,
or when fallbackToDestructiveMigration is still present on that database.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from _repo_files import REPO, changed_paths

VERSION_RE = re.compile(r"version\s*=\s*(\d+)")
MIGRATION_RE = re.compile(r"Migration\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)")
ENTITY_REF_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)::class")
DESTRUCTIVE_RE = re.compile(r"fallbackToDestructiveMigration(?:OnDowngrade)?\s*\(")
ADD_MIGRATIONS_RE = re.compile(r"addMigrations\s*\((.*?)\)", re.DOTALL)
TYPE_DECL_RE = re.compile(
    r"\b(?:(?:public|internal|private|protected|open|abstract|inner|data|sealed|annotation)\s+)*"
    r"class\s+([A-Z][A-Za-z0-9_]*)"
)
IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
ADD_MIGRATIONS_KW = frozenset({"addMigrations"})


@dataclass(frozen=True)
class DatabaseDecl:
    rel: str
    version: int | None
    entity_names: frozenset[str]
    migrations: frozenset[tuple[int, int]]
    registered: frozenset[str]
    has_add_migrations: bool
    destructive: bool


def git_head_text(rel_posix: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel_posix}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def declared_type_names(text: str) -> set[str]:
    """Kotlin class names declared in a source file (including inner/data classes)."""
    return set(TYPE_DECL_RE.findall(text))


def changed_kotlin_types(paths: list[Path]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        names.add(path.stem)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        names.update(declared_type_names(text))
    return names


def parse_database_source(text: str, rel: str = "") -> DatabaseDecl:
    version_match = VERSION_RE.search(text)
    version = int(version_match.group(1)) if version_match else None
    db_ann = re.search(r"@Database\s*\((.*?)\)\s*(?:@|\babstract\b)", text, re.DOTALL)
    header = db_ann.group(1) if db_ann else text.split("abstract class", 1)[0]
    entities = frozenset(ENTITY_REF_RE.findall(header))
    migrations = frozenset(
        (int(a), int(b)) for a, b in MIGRATION_RE.findall(text)
    )
    registered: set[str] = set()
    add_blocks = ADD_MIGRATIONS_RE.findall(text)
    for block in add_blocks:
        for token in IDENT_RE.findall(block):
            if token not in ADD_MIGRATIONS_KW:
                registered.add(token)
    return DatabaseDecl(
        rel=rel,
        version=version,
        entity_names=entities,
        migrations=migrations,
        registered=frozenset(registered),
        has_add_migrations=bool(add_blocks),
        destructive=bool(DESTRUCTIVE_RE.search(text)),
    )


def iter_database_files() -> list[Path]:
    root = REPO / "app"
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*Database.kt") if p.is_file()]


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def check_room_working_tree(modified_rels: list[str] | None = None) -> tuple[bool, str]:
    paths = changed_paths() if modified_rels is None else [REPO / r for r in modified_rels]
    changed_kt = [p for p in paths if p.suffix == ".kt" and p.is_file()]
    changed_types = changed_kotlin_types(changed_kt)
    changed_rels = {_rel(p) for p in changed_kt}

    databases: list[tuple[Path, DatabaseDecl]] = []
    for path in iter_database_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        databases.append((path, parse_database_source(text, _rel(path))))

    affected: list[tuple[Path, DatabaseDecl, str]] = []
    for path, decl in databases:
        reasons = []
        if decl.rel in changed_rels:
            reasons.append("database file changed")
        hit = sorted(decl.entity_names & changed_types)
        if hit:
            reasons.append("entities changed: " + ", ".join(hit))
        if reasons:
            affected.append((path, decl, "; ".join(reasons)))

    if not affected:
        return True, "No Room @Database or mapped @Entity changes in the working tree."

    failures: list[str] = []
    for path, new_decl, why in affected:
        old_text = git_head_text(new_decl.rel)
        old_decl = parse_database_source(old_text, new_decl.rel) if old_text else None
        old_ver = old_decl.version if old_decl else None
        new_ver = new_decl.version
        entity_hit = bool(new_decl.entity_names & changed_types)

        if new_ver is None:
            failures.append(f"{new_decl.rel}: @Database has no integer version ({why}).")
            continue

        if entity_hit and old_ver is not None and new_ver <= old_ver:
            failures.append(
                f"{new_decl.rel}: entity schema changed but version stayed {new_ver}. "
                f"Increment version and add Migration({old_ver}, {old_ver + 1})."
            )

        if old_ver is not None and new_ver > old_ver:
            needed = (old_ver, new_ver)
            if needed not in new_decl.migrations:
                failures.append(
                    f"{new_decl.rel}: version {old_ver} -> {new_ver} but Migration{needed} is missing."
                )
            if not new_decl.has_add_migrations:
                failures.append(
                    f"{new_decl.rel}: version bumped but addMigrations(...) is missing."
                )
            expected_name = f"MIGRATION_{old_ver}_{new_ver}"
            body = path.read_text(encoding="utf-8", errors="replace")
            if expected_name in body and expected_name not in new_decl.registered:
                failures.append(
                    f"{new_decl.rel}: {expected_name} exists but is not passed to addMigrations(...)."
                )

        if entity_hit and new_decl.destructive:
            failures.append(
                f"{new_decl.rel}: fallbackToDestructiveMigration() is forbidden on a schema change "
                "(zero data loss). Remove it and ship an explicit Migration."
            )

    if failures:
        return False, " ".join(failures)
    names = ", ".join(d.rel for _, d, _ in affected)
    return True, f"Room migration gate passed for: {names}."
