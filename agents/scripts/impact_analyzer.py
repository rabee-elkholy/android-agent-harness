"""Change Impact Analysis & Dependency Graph (Advisory Tool).

Usage:
  python .agents/scripts/impact_analyzer.py [--report] [--json] [--run]

Analyzes Kotlin and Java files in the repository to build a lightweight dependency graph:
  Repository/Data -> UseCase/Domain -> ViewModel/Presenter -> UI/Compose/Activity
  Symbols -> Tests

Identifies impacted application components and recommends focused unit tests and UI screens.
Safety invariant: This tool is strictly advisory — it is NEVER a blocking delivery gate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _repo_files import REPO, changed_paths  # noqa: E402

PACKAGE_PATTERN = re.compile(r"^\s*package\s+([a-zA-Z0-9_.]+)", re.MULTILINE)
IMPORT_PATTERN = re.compile(r"^\s*import\s+([a-zA-Z0-9_.*]+)", re.MULTILINE)
DECLARATION_PATTERN = re.compile(
    r"\b(?:class|interface|object|enum\s+class|sealed\s+class|sealed\s+interface|data\s+class)\s+([a-zA-Z0-9_]+)\b"
)
FUNCTION_PATTERN = re.compile(r"\bfun\s+(?:<[^>]+>\s+)?([a-zA-Z0-9_]+)\s*\(")

TEST_FILE_PATTERNS = [
    re.compile(r".*Test\.kt$", re.IGNORECASE),
    re.compile(r".*Tests\.kt$", re.IGNORECASE),
    re.compile(r".*TestCase\.kt$", re.IGNORECASE),
    re.compile(r".*Test\.java$", re.IGNORECASE),
]

UI_SURFACE_PATTERNS = [
    re.compile(r".*Screen\.kt$", re.IGNORECASE),
    re.compile(r".*Activity\.kt$", re.IGNORECASE),
    re.compile(r".*Fragment\.kt$", re.IGNORECASE),
    re.compile(r".*Dialog\.kt$", re.IGNORECASE),
    re.compile(r".*BottomSheet\.kt$", re.IGNORECASE),
]


def is_test_file(path: Path) -> bool:
    rel = path.as_posix()
    if "/test/" in rel or "/androidTest/" in rel or "/testDebug/" in rel:
        return True
    return any(p.match(path.name) for p in TEST_FILE_PATTERNS)


def is_ui_file(path: Path) -> bool:
    return any(p.match(path.name) for p in UI_SURFACE_PATTERNS)


class FileSymbols:
    def __init__(self, path: Path, rel_path: str):
        self.path = path
        self.rel_path = rel_path
        self.package: str = ""
        self.imports: set[str] = set()
        self.declarations: set[str] = set()
        self.functions: set[str] = set()
        self.is_test: bool = is_test_file(path)
        self.is_ui: bool = is_ui_file(path)


def parse_symbols(path: Path, repo: Path) -> FileSymbols:
    try:
        rel = path.relative_to(repo).as_posix()
    except ValueError:
        rel = path.as_posix()

    info = FileSymbols(path, rel)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return info

    pkg_match = PACKAGE_PATTERN.search(text)
    if pkg_match:
        info.package = pkg_match.group(1).strip()

    for m in IMPORT_PATTERN.finditer(text):
        info.imports.add(m.group(1).strip())

    for m in DECLARATION_PATTERN.finditer(text):
        info.declarations.add(m.group(1).strip())

    for m in FUNCTION_PATTERN.finditer(text):
        info.functions.add(m.group(1).strip())

    return info


def build_repo_index(repo: Path) -> dict[str, FileSymbols]:
    """Scan and index Kotlin and Java source files in the repository."""
    index: dict[str, FileSymbols] = {}
    extensions = (".kt", ".java")

    for ext in extensions:
        for p in repo.glob(f"**/*{ext}"):
            if any(part.startswith(".") for part in p.parts):
                continue
            if "build" in p.parts or ".gradle" in p.parts:
                continue
            try:
                rel = p.relative_to(repo).as_posix()
                index[rel] = parse_symbols(p, repo)
            except Exception:
                continue
    return index


def analyze_impact(
    repo: Path,
    changed: list[Path] | None = None,
    index: dict[str, FileSymbols] | None = None,
) -> dict:
    """Analyze the impact of changed files across the dependency index."""
    if index is None:
        index = build_repo_index(repo)

    target_files = changed if changed is not None else changed_paths()
    modified_rels: list[str] = []
    for f in target_files:
        try:
            rel = f.relative_to(repo).as_posix()
        except ValueError:
            rel = str(f)
        modified_rels.append(rel)

    # Collect modified symbols
    modified_symbols: set[str] = set()
    modified_packages: set[str] = set()
    for rel in modified_rels:
        sym = index.get(rel)
        if sym:
            modified_symbols.update(sym.declarations)
            if sym.package:
                modified_packages.add(sym.package)
        else:
            # For newly added or unindexed files
            base_name = Path(rel).stem
            modified_symbols.add(base_name)

    direct_dependents: set[str] = set()
    recommended_tests: set[str] = set()
    recommended_ui: set[str] = set()
    has_wildcard_import = False

    # Find matching tests and dependent files
    for rel, sym in index.items():
        if rel in modified_rels:
            if sym.is_test:
                recommended_tests.add(sym.path.stem)
            if sym.is_ui:
                recommended_ui.add(sym.path.stem)
            continue

        # Check imports for explicit symbol or package
        imports_modified = False
        for imp in sym.imports:
            if imp.endswith(".*"):
                pkg_part = imp[:-2]
                if pkg_part in modified_packages:
                    imports_modified = True
                    has_wildcard_import = True
            else:
                imp_symbol = imp.split(".")[-1]
                if imp_symbol in modified_symbols:
                    imports_modified = True

        if imports_modified:
            if sym.is_test:
                recommended_tests.add(sym.path.stem)
            else:
                direct_dependents.add(rel)
                if sym.is_ui:
                    recommended_ui.add(sym.path.stem)

    # Transitive expansion (depth 2): find UI surfaces & tests depending on direct dependents
    transitive_symbols: set[str] = set()
    transitive_packages: set[str] = set()
    for d_rel in direct_dependents:
        d_sym = index.get(d_rel)
        if d_sym:
            transitive_symbols.update(d_sym.declarations)
            if d_sym.package:
                transitive_packages.add(d_sym.package)

    if transitive_symbols:
        for rel, sym in index.items():
            if rel in modified_rels or rel in direct_dependents:
                continue
            for imp in sym.imports:
                imp_sym = imp.split(".")[-1]
                if imp_sym in transitive_symbols or (imp.endswith(".*") and imp[:-2] in transitive_packages):
                    if sym.is_test:
                        recommended_tests.add(sym.path.stem)
                    if sym.is_ui:
                        recommended_ui.add(sym.path.stem)

    # Also match tests by naming convention: e.g. PaymentRepository -> PaymentRepositoryTest
    for sym_name in (modified_symbols | transitive_symbols):
        test_candidate = f"{sym_name}Test"
        for rel, sym in index.items():
            if sym.is_test and (sym.path.stem == test_candidate or test_candidate in sym.path.stem):
                recommended_tests.add(sym.path.stem)

    confidence = "HIGH"
    if has_wildcard_import:
        confidence = "MEDIUM"
    if not modified_symbols and modified_rels:
        confidence = "LOW"

    return {
        "modified_files": modified_rels,
        "modified_symbols": sorted(modified_symbols),
        "direct_dependents": sorted(direct_dependents),
        "recommended_tests": sorted(recommended_tests),
        "recommended_ui_surfaces": sorted(recommended_ui),
        "confidence": confidence,
    }


def main(argv=None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Analyze change impact & recommended tests")
    parser.add_argument("--json", action="store_true", help="Output result in JSON format")
    parser.add_argument("--run", action="store_true", help="Run recommended unit tests via run_tests_gate")
    args = parser.parse_args(argv)

    target_files = changed_paths()
    if not target_files:
        live_print("[*] Clean working tree — no changed files to analyze.")
        return 0

    index = build_repo_index(REPO)
    report = analyze_impact(REPO, target_files, index)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    live_print("==================================================")
    live_print("[Impact] Change Impact Analysis Report")
    live_print("==================================================")
    live_print(f"Confidence: {report['confidence']}")
    live_print(f"Modified Files ({len(report['modified_files'])}):")
    for f in report["modified_files"][:10]:
        live_print(f"  - {f}")
    if len(report["modified_files"]) > 10:
        live_print(f"  ... and {len(report['modified_files']) - 10} more")

    if report["modified_symbols"]:
        live_print(f"Impacted Declarations ({len(report['modified_symbols'])}):")
        for s in report["modified_symbols"][:10]:
            live_print(f"  - {s}")

    if report["direct_dependents"]:
        live_print(f"Dependent Modules/Files ({len(report['direct_dependents'])}):")
        for d in report["direct_dependents"][:10]:
            live_print(f"  - {d}")

    if report["recommended_tests"]:
        live_print(f"Recommended Tests ({len(report['recommended_tests'])}):")
        for t in report["recommended_tests"]:
            live_print(f"  - {t}")
    else:
        live_print("Recommended Tests: None found (all unit tests recommended)")

    if report["recommended_ui_surfaces"]:
        live_print(f"Impacted UI Surfaces ({len(report['recommended_ui_surfaces'])}):")
        for ui in report["recommended_ui_surfaces"]:
            live_print(f"  - {ui}")

    if args.run:
        from run_tests_gate import main as run_gate_main
        live_print("\n[*] Running test gate...")
        return run_gate_main()

    return 0


if __name__ == "__main__":
    sys.exit(main())
