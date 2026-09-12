"""Room schema / migration gate for this Android app.

Fails a working-tree schema change when version was not incremented, when
Migration(old, new) is missing, when it is not registered with addMigrations,
or when fallbackToDestructiveMigration is still present on that database.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from _repo_files import REPO, changed_paths

VERSION_RE = re.compile(r"version\s*=\s*(\d+)")
MIGRATION_RE = re.compile(r"Migration\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)")
AUTO_MIGRATION_RE = re.compile(r"AutoMigration\s*\(\s*(?:from\s*=\s*)?(\d+)\s*,\s*(?:to\s*=\s*)?(\d+)")
ENTITY_REF_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)(?:::class|\.class)")
EMBEDDED_TYPE_RE = re.compile(r"@Embedded(?:\([^)]*\))?\s+(?:val|var)\s+\w+\s*:\s*([A-Z][A-Za-z0-9_]*)")
DESTRUCTIVE_RE = re.compile(r"fallbackToDestructiveMigration(?:OnDowngrade)?\s*\(")
ADD_MIGRATIONS_RE = re.compile(r"addMigrations\s*\((.*?)\)", re.DOTALL)
TYPE_DECL_RE = re.compile(
    r"\b(?:(?:public|internal|private|protected|open|abstract|inner|data|sealed|annotation|static|final)\s+)*"
    r"(?:class|record)\s+([A-Z][A-Za-z0-9_]*)"
)
IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
ADD_MIGRATIONS_KW = frozenset({"addMigrations"})

KT_VAR_RE = re.compile(
    r"(?:val|var)\s+([A-Za-z0-9_]+)\s*(?::\s*Migration)?\s*=\s*(?:object\s*:\s*)?Migration\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)"
)
JAVA_VAR_RE = re.compile(
    r"(?:(?:public|protected|private|static|final)\s+)*Migration\s+([A-Za-z0-9_]+)\s*=\s*new\s+Migration\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)"
)


def _extract_add_migrations_blocks(text: str, target_db_class: str = "") -> list[str]:
    blocks = []
    for m in re.finditer(r"\baddMigrations\s*\(", text):
        if target_db_class:
            preceding = text[: m.start()]
            builder_matches = list(
                re.finditer(
                    r"databaseBuilder\s*\([^,]+,\s*([A-Za-z0-9_]+)(?:::class|\.class)",
                    preceding,
                )
            )
            if builder_matches and builder_matches[-1].group(1) != target_db_class:
                continue
        start = m.end()
        depth = 1
        i = start
        n = len(text)
        while i < n and depth > 0:
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        if depth == 0:
            blocks.append(text[start : i - 1])
    return blocks


@dataclass(frozen=True)
class DatabaseDecl:
    rel: str
    class_name: str
    version: int | None
    entity_names: frozenset[str]
    migrations: frozenset[tuple[int, int]]
    registered: frozenset[str]
    has_add_migrations: bool
    destructive: bool


def git_head_text(rel_posix: str, repo: Path | None = None) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel_posix}"],
        cwd=repo or REPO,
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


def resolve_all_entity_types(root_entities: frozenset[str], repo: Path) -> frozenset[str]:
    all_types = set(root_entities)
    frontier = list(root_entities)
    visited_files = set()
    skip_parts = {".git", "build", ".gradle", ".idea", ".agents", ".harness-backup", ".harness-setup", "__pycache__"}
    while frontier:
        curr = frontier.pop(0)
        matching_files = [
            f for f in (list(repo.rglob(f"{curr}.kt")) + list(repo.rglob(f"{curr}.java")))
            if not (set(f.parts) & skip_parts)
        ]
        if not matching_files:
            class_decl = re.compile(rf"\bclass\s+{re.escape(curr)}\b")
            for f in (list(repo.rglob("*.kt")) + list(repo.rglob("*.java"))):
                if f.is_file() and not (set(f.parts) & skip_parts) and f not in visited_files:
                    try:
                        if class_decl.search(f.read_text(encoding="utf-8", errors="replace")):
                            matching_files.append(f)
                    except Exception:
                        pass
        for kt_file in matching_files:
            if kt_file in visited_files or not kt_file.is_file():
                continue
            visited_files.add(kt_file)
            try:
                content = kt_file.read_text(encoding="utf-8", errors="replace")
                for embedded in EMBEDDED_TYPE_RE.findall(content):
                    if embedded not in all_types:
                        all_types.add(embedded)
                        frontier.append(embedded)
            except Exception:
                continue
    return frozenset(all_types)


def is_migration_path_covered(start: int, end: int, migrations: frozenset[tuple[int, int]]) -> bool:
    if (start, end) in migrations:
        return True
    adj: dict[int, list[int]] = {}
    for u, v in migrations:
        adj.setdefault(u, []).append(v)
    visited = set()
    queue = [start]
    while queue:
        curr = queue.pop(0)
        if curr == end:
            return True
        if curr not in visited:
            visited.add(curr)
            queue.extend(adj.get(curr, []))
    return False


def parse_database_source(text: str, rel: str = "", repo: Path | None = None) -> DatabaseDecl:
    root = repo or REPO
    version_match = VERSION_RE.search(text)
    version = int(version_match.group(1)) if version_match else None
    class_match = re.search(r"\bclass\s+([A-Za-z0-9_]+)", text)
    class_name = class_match.group(1) if class_match else ""
    db_ann = re.search(r"@Database\s*\((.*?)\)\s*(?:@|\babstract\b)", text, re.DOTALL)
    header = db_ann.group(1) if db_ann else text.split("abstract class", 1)[0]
    raw_entities = frozenset(ENTITY_REF_RE.findall(header))
    entities = resolve_all_entity_types(raw_entities, root)
    auto_migrations = frozenset(
        (int(a), int(b)) for a, b in AUTO_MIGRATION_RE.findall(text)
    )
    registered: set[str] = set()
    add_blocks = _extract_add_migrations_blocks(text, target_db_class=class_name)
    for block in add_blocks:
        for token in IDENT_RE.findall(block):
            if token not in ADD_MIGRATIONS_KW:
                registered.add(token)
    return DatabaseDecl(
        rel=rel,
        class_name=class_name,
        version=version,
        entity_names=entities,
        migrations=auto_migrations,
        registered=frozenset(registered),
        has_add_migrations=bool(add_blocks) or bool(auto_migrations),
        destructive=bool(DESTRUCTIVE_RE.search(text)),
    )


def find_candidate_migration_files(db_path: Path, changed_src: list[Path], repo: Path | None = None) -> list[Path]:
    """Find candidate Kotlin/Java files likely to declare or register Room migrations."""
    root = repo or REPO
    candidates: list[Path] = []
    seen: set[Path] = {db_path}
    for p in changed_src:
        if p != db_path and p.is_file():
            candidates.append(p)
            seen.add(p)
    db_dir = db_path.parent
    if db_dir.is_dir():
        for p in db_dir.glob("*.kt"):
            if p not in seen and p.is_file():
                candidates.append(p)
                seen.add(p)
    module_dir = db_path.parent
    while module_dir != root and not (module_dir / "build.gradle").is_file() and not (module_dir / "build.gradle.kts").is_file():
        if module_dir.parent == module_dir:
            break
        module_dir = module_dir.parent
    scan_root = module_dir if module_dir.is_dir() else root
    skip_parts = {".git", "build", ".gradle", ".idea", ".agents", ".harness-backup", ".harness-setup", "__pycache__"}
    for pattern in ("*Migration*.kt", "*DatabaseModule*.kt", "*DbModule*.kt", "*AppModule*.kt", "*Module*.kt", "*Provider*.kt"):

        for p in scan_root.glob(f"**/{pattern}"):
            if not (set(p.parts) & skip_parts) and p not in seen and p.is_file():
                candidates.append(p)
                seen.add(p)
    for p in list(scan_root.glob("**/*.kt")) + list(scan_root.glob("**/*.java")):
        if not (set(p.parts) & skip_parts) and p not in seen and p.is_file():
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:4000]
                if "addMigrations" in head or "Migration(" in head:
                    candidates.append(p)
                    seen.add(p)
            except Exception:
                pass
    return candidates



def iter_database_files(repo: Path | None = None) -> list[Path]:
    root = repo or REPO
    skip_parts = {".git", "build", ".gradle", ".idea", ".agents", ".harness-backup", ".harness-setup", "__pycache__"}
    db_files: list[Path] = []
    for p in (list(root.rglob("*.kt")) + list(root.rglob("*.java"))):
        if p.is_file() and not (set(p.parts) & skip_parts):
            if p.name.endswith("Database.kt") or p.name.endswith("Database.java"):
                db_files.append(p)
            else:
                try:
                    head = p.read_text(encoding="utf-8", errors="replace")[:2000]
                    if "@Database" in head:
                        db_files.append(p)
                except Exception:
                    pass
    return db_files


def check_room_working_tree(modified_rels: list[str] | None = None, repo: Path | None = None) -> tuple[bool, str]:
    root = (repo or REPO).resolve()

    def _rel(path: Path) -> str:
        return path.relative_to(root).as_posix()

    paths = changed_paths(repo=root, include_deleted=True) if modified_rels is None else [root / r for r in modified_rels]
    changed_src = [p for p in paths if p.suffix in (".kt", ".java") and p.is_file()]
    changed_types = changed_kotlin_types(changed_src)
    changed_rels = {_rel(p) for p in changed_src}

    for p in paths:
        if p.suffix in (".kt", ".java") and not p.is_file():
            rel = _rel(p)
            changed_rels.add(rel)
            changed_types.add(p.stem)
            head_content = git_head_text(rel, root)
            if head_content:
                changed_types.update(declared_type_names(head_content))


    databases: list[tuple[Path, DatabaseDecl]] = []
    for path in iter_database_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        databases.append((path, parse_database_source(text, _rel(path), root)))

    affected: list[tuple[Path, DatabaseDecl, DatabaseDecl | None, str]] = []
    for path, decl in databases:
        reasons = []
        if decl.rel in changed_rels:
            reasons.append("database file changed")
        old_text = git_head_text(decl.rel, root)
        old_decl = parse_database_source(old_text, decl.rel, root) if old_text else None

        all_entities = set(decl.entity_names)
        if old_decl:
            all_entities.update(old_decl.entity_names)
            if old_decl.entity_names != decl.entity_names:
                reasons.append("entities membership changed")

        hit = sorted(all_entities & changed_types)
        if hit:
            reasons.append("entities changed: " + ", ".join(hit))

        candidate_files = find_candidate_migration_files(path, changed_src, root)
        candidate_rels = {_rel(p) for p in candidate_files}
        if candidate_rels & changed_rels:
            reasons.append("candidate migration files changed")

        if reasons:
            affected.append((path, decl, old_decl, "; ".join(reasons)))

    if not affected:
        return True, "No Room @Database or mapped @Entity changes in the working tree."

    failures: list[str] = []
    no_baseline = False
    for path, new_decl, old_decl, why in affected:
        old_ver = old_decl.version if old_decl else None
        new_ver = new_decl.version
        all_entities = set(new_decl.entity_names)
        if old_decl:
            all_entities.update(old_decl.entity_names)
        entity_hit = bool(all_entities & changed_types) or (old_decl is not None and old_decl.entity_names != new_decl.entity_names)
        if old_decl is None:
            no_baseline = True

        if new_ver is None:
            failures.append(f"{new_decl.rel}: @Database has no integer version ({why}).")
            continue

        if entity_hit and old_ver is not None and new_ver <= old_ver:
            failures.append(
                f"{new_decl.rel}: entity schema changed but version stayed {new_ver}. "
                f"Increment version and add Migration({old_ver}, {old_ver + 1}) or AutoMigration."
            )

        other_db_classes = {d.class_name for _, d in databases if d.class_name and d.class_name != new_decl.class_name}

        should_check_migrations = False
        target_start = 1
        if old_ver is not None and new_ver > old_ver:
            should_check_migrations = True
            target_start = old_ver
        elif "candidate migration files changed" in why and new_ver is not None and new_ver > 1:
            should_check_migrations = True
            target_start = None

        if should_check_migrations:
            all_migs = set(new_decl.migrations)
            has_add_migs = new_decl.has_add_migrations
            registered_tokens = set(new_decl.registered)
            candidate_files = find_candidate_migration_files(path, changed_src, root)
            candidate_texts: list[str] = []
            for c_path in candidate_files:
                try:
                    c_text = c_path.read_text(encoding="utf-8", errors="replace")
                    # If this candidate file has databaseBuilder calls for other databases and not this database, skip it
                    builder_dbs = set(re.findall(r"databaseBuilder\s*\([^,]+,\s*([A-Za-z0-9_]+)(?:::class|\.class)", c_text))
                    if builder_dbs and new_decl.class_name not in builder_dbs:
                        continue
                    # If this candidate file references another known database and does NOT reference this database, skip it
                    if other_db_classes and any(re.search(rf"\b{re.escape(odb)}\b", c_text) for odb in other_db_classes):
                        if not (new_decl.class_name and re.search(rf"\b{re.escape(new_decl.class_name)}\b", c_text)):
                            continue
                    candidate_texts.append(c_text)
                    for a, b in AUTO_MIGRATION_RE.findall(c_text):
                        all_migs.add((int(a), int(b)))
                    add_blocks = _extract_add_migrations_blocks(c_text, target_db_class=new_decl.class_name)
                    if add_blocks:
                        has_add_migs = True
                        for block in add_blocks:
                            for token in IDENT_RE.findall(block):
                                if token not in ADD_MIGRATIONS_KW:
                                    registered_tokens.add(token)
                except Exception:
                    continue

            body = path.read_text(encoding="utf-8", errors="replace")
            all_bodies = [body] + candidate_texts

            if target_start is None:
                all_candidate_edges: set[tuple[int, int]] = set()
                for b_text in all_bodies:
                    for _, a_str, b_str in KT_VAR_RE.findall(b_text) + JAVA_VAR_RE.findall(b_text):
                        all_candidate_edges.add((int(a_str), int(b_str)))
                    for a_str, b_str in re.findall(r"\bMIGRATION_(\d+)_(\d+)\b", b_text):
                        all_candidate_edges.add((int(a_str), int(b_str)))
                    for a_str, b_str in AUTO_MIGRATION_RE.findall(b_text):
                        all_candidate_edges.add((int(a_str), int(b_str)))
                    for add_block in _extract_add_migrations_blocks(b_text, target_db_class=new_decl.class_name):
                        for a_str, b_str in MIGRATION_RE.findall(add_block):
                            all_candidate_edges.add((int(a_str), int(b_str)))
                relevant_edges = [edge for edge in all_candidate_edges if edge[1] <= new_ver]
                if relevant_edges:
                    target_start = min(edge[0] for edge in relevant_edges)
                else:
                    should_check_migrations = False

            if should_check_migrations and target_start is not None:
                unregistered_candidates: list[tuple[str, int, int]] = []
                # Check for migration variables in candidate files and credit registered ones
                for b_text in all_bodies:
                    var_matches = KT_VAR_RE.findall(b_text) + JAVA_VAR_RE.findall(b_text)
                    for var_name, a_str, b_str in var_matches:
                        edge = (int(a_str), int(b_str))
                        if target_start <= edge[0] < edge[1] <= new_ver:
                            if var_name in registered_tokens or var_name in str(new_decl.registered):
                                all_migs.add(edge)
                            else:
                                unregistered_candidates.append((var_name, edge[0], edge[1]))

                    # Check named convention MIGRATION_A_B
                    for a_str, b_str in re.findall(r"\bMIGRATION_(\d+)_(\d+)\b", b_text):
                        edge = (int(a_str), int(b_str))
                        if target_start <= edge[0] < edge[1] <= new_ver:
                            c_name = f"MIGRATION_{edge[0]}_{edge[1]}"
                            if c_name in registered_tokens or c_name in str(new_decl.registered):
                                all_migs.add(edge)
                            else:
                                unregistered_candidates.append((c_name, edge[0], edge[1]))

                    # Direct inline Migration(a, b) calls inside addMigrations
                    for add_block in _extract_add_migrations_blocks(b_text, target_db_class=new_decl.class_name):
                        for a_str, b_str in MIGRATION_RE.findall(add_block):
                            all_migs.add((int(a_str), int(b_str)))

                if not is_migration_path_covered(target_start, new_ver, frozenset(all_migs)):
                    if unregistered_candidates:
                        for var_name, a_val, b_val in unregistered_candidates:
                            if not any(var_name in f for f in failures):
                                failures.append(
                                    f"{new_decl.rel}: migration variable '{var_name}' ({a_val} -> {b_val}) is defined but not registered in addMigrations(...)."
                                )
                    else:
                        failures.append(
                            f"{new_decl.rel}: version {target_start} -> {new_ver} but valid migration path is missing."
                        )
                if not has_add_migs:
                    failures.append(
                        f"{new_decl.rel}: version bumped but addMigrations(...) or autoMigrations is missing."
                    )



        if entity_hit and new_decl.destructive:
            failures.append(
                f"{new_decl.rel}: fallbackToDestructiveMigration() is forbidden on a schema change "
                "(zero data loss). Remove it and ship an explicit Migration."
            )

    if failures:
        return False, " ".join(failures)
    names = ", ".join(item[1].rel for item in affected)
    baseline_note = (
        " [WARN] no git baseline available (no commits?); version/migration comparison skipped."
        if no_baseline
        else ""
    )
    return True, f"Room migration gate passed for: {names}.{baseline_note}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Room migration and schema safety check.")
    parser.add_argument("--repo", default=None, help="Repository root path.")
    args = parser.parse_args()
    repo_path = Path(args.repo).resolve() if args.repo else REPO
    passed, msg = check_room_working_tree(repo=repo_path)
    if not passed:
        print(f"[FAIL] {msg}", file=sys.stderr)
        return 1
    print(f"[PASS] {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

