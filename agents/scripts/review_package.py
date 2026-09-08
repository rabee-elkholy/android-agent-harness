"""Write a working-tree review package (staged + unstaged + untracked vs HEAD). Inspection only. No git mutations."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _hook_state import (  # noqa: E402
    file_sha256,
    record_review_ledger,
    record_review_round_local,
    round_cap_warning,
    semantic_code_snapshot,
    tree_code_fingerprint,
    write_verdict_record,
)
from _gate_results import read_gate_result  # noqa: E402
from _repo_files import changed_paths, working_tree_fingerprint  # noqa: E402

enable_line_buffered_stdio()

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parents[1] / "state" / "packages"

HEADER_BEGIN = "# HARNESS_PACKAGE_HEADER v2"
PACKAGE_SHA_MARKER = "PACKAGE_SHA256="
PACKAGE_SHA_PENDING = "PACKAGE_SHA256=PENDING"
PREFLIGHT_ARTIFACT_SCHEMA = 2


def preflight_cache_is_valid(
    record: dict | None,
    *,
    git_sha: str,
    working_tree_fingerprint: str,
) -> bool:
    """Return true only for a complete PASS bound to this exact tree state."""
    if not isinstance(record, dict):
        return False
    if record.get("schema_version") != PREFLIGHT_ARTIFACT_SCHEMA:
        return False
    if record.get("status") != "PASS" or record.get("exit_code") != 0:
        return False
    if not git_sha or record.get("git_sha") != git_sha:
        return False
    if not working_tree_fingerprint or record.get("working_tree_fingerprint") != working_tree_fingerprint:
        return False

    steps = record.get("steps")
    if not isinstance(steps, dict):
        return False
    return (
        type(steps.get("hook_selftest")) is int
        and steps.get("hook_selftest") == 0
        and type(steps.get("string_parity")) is int
        and steps.get("string_parity") == 0
        and steps.get("room_migrations") is True
        and type(steps.get("fast_kt_lint")) is int
        and steps.get("fast_kt_lint") == 0
        and steps.get("risk_approval") is True
    )


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    return (proc.stdout or "") + (proc.stderr or "")


_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def git_head() -> str:
    """Commit hash, or empty string when the checkout has no usable git HEAD."""
    out = git("rev-parse", "HEAD").strip()
    return out if _GIT_SHA_RE.fullmatch(out) else ""


def is_test_file(path_str: str) -> bool:
    p = path_str.replace("\\", "/").lower()
    return (
        "/test/" in p
        or "/androidtest/" in p
        or "/sharedtest/" in p
        or p.endswith("test.kt")
        or p.endswith("tests.kt")
        or p.endswith("test.java")
        or p.endswith("tests.java")
    )


from risk_tier import classify_working_tree_risk  # noqa: E402


def build_header(
    task_id: str,
    fingerprint: str,
    risk_tier: str = "MEDIUM",
    contains_tests: bool = False,
    test_files_count: int = 0,
    snapshot: str | None = None,
) -> list[str]:
    sha = git_head()
    hdr = [
        HEADER_BEGIN,
        f"TASK_ID={task_id}",
        f"GIT_SHA={sha}",
        f"TREE_FINGERPRINT={fingerprint}",
    ]
    if snapshot:
        hdr.append(f"WORKSPACE_SNAPSHOT={snapshot}")
    hdr.extend([
        f"RISK_TIER={risk_tier}",
        f"CONTAINS_TESTS={'true' if contains_tests else 'false'}",
        f"TEST_FILES_COUNT={test_files_count}",
        f"REQUIRED_LEAVES={'6' if contains_tests else '5'}",
        f"GENERATED_AT={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    ])
    return hdr


DEFAULT_MAX_REVIEW_FILES = 500


def _configured_max_files() -> int:
    env_val = os.environ.get("HARNESS_MAX_REVIEW_FILES")
    if env_val:
        try:
            return max(50, int(env_val.strip()))
        except ValueError:
            pass
    return DEFAULT_MAX_REVIEW_FILES


def build_files_map(max_files: int | None = None) -> tuple[dict[str, str], int]:
    """SHA-256 per changed working-tree file (rel path -> hex), capped, with total count."""
    effective_max = max_files if max_files is not None else _configured_max_files()
    files_map: dict[str, str] = {}
    all_changed = list(changed_paths())
    for path in all_changed:
        if len(files_map) >= effective_max:
            break
        try:
            rel = path.relative_to(REPO).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            files_map[rel] = file_sha256(path)
        except Exception:
            continue
    return files_map, len(all_changed)



def build_graph_topology_summary() -> str:
    try:
        from impact_analyzer import analyze_impact, build_repo_index
        target_files = list(changed_paths())
        if not target_files:
            return ""
        index = build_repo_index(REPO)
        report = analyze_impact(REPO, target_files, index)
        lines = [
            "\n## ARCHITECTURAL GRAPH TOPOLOGY & BLAST RADIUS",
            f"# Confidence: {report.get('confidence', 'MEDIUM')}",
        ]
        syms = report.get("modified_symbols", [])
        if syms:
            lines.append(f"- Impacted Declarations ({len(syms)}): " + ", ".join(syms[:15]))
        deps = report.get("direct_dependents", [])
        if deps:
            lines.append(f"- Direct Dependents / Callers ({len(deps)}): " + ", ".join(deps[:15]))
        uis = report.get("recommended_ui_surfaces", [])
        if uis:
            lines.append(f"- Impacted UI Surfaces ({len(uis)}): " + ", ".join(uis[:10]))
        tests = report.get("recommended_tests", [])
        if tests:
            lines.append(f"- Recommended Unit Tests ({len(tests)}): " + ", ".join(tests[:10]))
        lines.append("")
        return "\n".join(lines)
    except Exception:
        return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write working-tree diff package for the 5 review leaves")
    parser.add_argument("paths", nargs="*", help="Optional paths to include (default: all unstaged)")
    parser.add_argument("--task", default=None, help="Task id recorded in the package header (default: $HARNESS_TASK_ID).")
    parser.add_argument(
        "--force-preflight",
        action="store_true",
        help="Run preflight even when an exact matching PASS artifact exists.",
    )
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"review-{stamp}.diff"

    paths = args.paths
    status_cmd = ["status", "--short", "--branch"]
    diff_stat_cmd = ["diff", "HEAD", "--stat"]
    diff_cmd = ["diff", "HEAD", "-U10"]
    if paths:
        status_cmd.extend(["--", *paths])
        diff_stat_cmd.extend(["--", *paths])
        diff_cmd.extend(["--", *paths])

    task_id = (args.task or os.environ.get("HARNESS_TASK_ID") or "").strip()
    cap_note = round_cap_warning(task_id)
    if cap_note:
        print(cap_note, file=sys.stderr)
    if not git_head():
        print(
            "[!] This checkout has no git HEAD (no commits yet). A review package "
            "against an empty HEAD is meaningless and the review barrier would pass "
            "silently. Create an initial commit before requesting reviews.",
            file=sys.stderr,
        )
        return 1

    # Hard Pre-Gate: reuse only a complete PASS bound to this exact HEAD and tree.
    preflight_script = Path(__file__).resolve().parent / "preflight_check.py"
    current_fingerprint = working_tree_fingerprint(REPO)
    cached_preflight = read_gate_result("preflight")
    reuse_preflight = (
        not args.force_preflight
        and preflight_cache_is_valid(
            cached_preflight,
            git_sha=git_head(),
            working_tree_fingerprint=current_fingerprint or "",
        )
    )
    if reuse_preflight:
        print("[*] Reusing cached preflight PASS for unchanged HEAD and working tree.", flush=True)
    elif preflight_script.is_file():
        print("[*] Running preflight verification...", flush=True)
        preflight_proc = subprocess.run(
            [sys.executable, str(preflight_script), "--skip-hook-selftest"],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if preflight_proc.returncode != 0:
            print(
                "[FAIL] Cannot generate review package: Preflight verification detected violations:",
                file=sys.stderr,
            )
            if preflight_proc.stdout.strip():
                print(preflight_proc.stdout.strip(), file=sys.stderr)
            if preflight_proc.stderr.strip():
                print(preflight_proc.stderr.strip(), file=sys.stderr)
            print(
                "\n[!] Fix all preflight issues (strings, Room migrations, lint, risk approvals) before generating a review package.",
                file=sys.stderr,
            )
            return 1
    else:
        print(
            "[FAIL] Cannot generate review package: preflight_check.py is missing.",
            file=sys.stderr,
        )
        return 1

    fingerprint = tree_code_fingerprint() or ""
    snapshot = semantic_code_snapshot() or ""
    risk_tier, _ = classify_working_tree_risk(REPO, list(changed_paths()))
    files_map, total_changed = build_files_map()
    skipped_count = max(0, total_changed - len(files_map))
    test_files = [f for f in files_map.keys() if is_test_file(f)]
    contains_tests = len(test_files) > 0
    print(f"[*] Packaging review diff for {len(files_map)} file(s) (risk tier: {risk_tier})...", flush=True)
    files_json = json.dumps(files_map, ensure_ascii=False, separators=(",", ":"))
    graph_topology = build_graph_topology_summary()
    chunks = [
        "\n".join([
            *build_header(
                task_id,
                fingerprint,
                risk_tier,
                contains_tests=contains_tests,
                test_files_count=len(test_files),
                snapshot=snapshot,
            ),
            f"FILES_SHA256={files_json}",
            PACKAGE_SHA_PENDING,
        ]) + "\n",
        f"# Harness review package (unstaged vs HEAD)\n# repo: {REPO}\n",
        "## git status\n",
        git(*status_cmd),
        "\n## git diff --stat\n",
        git(*diff_stat_cmd),
        *(["\n" + graph_topology] if graph_topology else []),
        "\n## git diff -U10\n",
        git(*diff_cmd),
    ]

    untracked = git("ls-files", "--others", "--exclude-standard", *(["--", *paths] if paths else []))
    extra = []
    binary_extensions = {
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico",
        ".apk", ".aab", ".jar", ".aar", ".so", ".dylib", ".dll",
        ".zip", ".tar", ".gz", ".7z", ".keystore", ".jks",
        ".mp3", ".mp4", ".wav", ".ogg", ".pdf", ".class",
    }
    max_untracked_bytes = 256 * 1024

    for line in untracked.splitlines():
        rel = line.strip()
        if not rel:
            continue
        file_path = REPO / rel
        extra.append(f"\n## NEW FILE {rel}\n")
        suffix = Path(rel).suffix.lower()
        if suffix in binary_extensions:
            extra.append(f"[Binary file excluded: {rel}]\n")
            continue
        try:
            st = file_path.stat()
            if st.st_size > max_untracked_bytes:
                extra.append(f"[Large file excluded ({st.st_size / 1024:.1f} KB > 256 KB): {rel}]\n")
                continue
            content_bytes = file_path.read_bytes()
            if b"\0" in content_bytes[:8192]:
                extra.append(f"[Binary content excluded: {rel}]\n")
                continue
            extra.append(content_bytes.decode("utf-8", errors="replace"))
        except Exception as exc:
            extra.append(f"(could not read: {exc})\n")
    if extra:
        chunks.append("\n## untracked files\n")
        chunks.extend(extra)

    out.write_text("".join(chunks), encoding="utf-8", newline="\n")

    data = out.read_bytes()
    marker_pos = data.find(PACKAGE_SHA_MARKER.encode("utf-8"))
    if marker_pos < 0:
        raise SystemExit("[ERROR] package header marker missing after write")
    pre_digest = hashlib.sha256(data[:marker_pos]).hexdigest()
    out.write_bytes(
        data.replace(
            PACKAGE_SHA_PENDING.encode("utf-8"),
            f"{PACKAGE_SHA_MARKER}{pre_digest}".encode("utf-8"),
            1,
        )
    )

    file_digest = file_sha256(out)
    pkg12 = file_digest[:12]
    git_sha = git_head()
    record_review_ledger(out, git_sha=git_sha)
    pending = {
        "schema_version": 2,
        "task_id": task_id,
        "git_sha": git_sha,
        "package": {"path": str(out.resolve()), "sha256": file_digest, "sha256_12": pkg12},
        "tree_fingerprint": fingerprint or None,
        "workspace_snapshot": snapshot or None,
        "files": files_map,
        "reviewed_files": len(files_map),
        "skipped_files": skipped_count,
        "is_truncated": skipped_count > 0,
        "contains_tests": contains_tests,
        "test_files": test_files,
        "required_leaves_count": 6 if contains_tests else 5,
        "dispatched_at": None,
        "completed_at": None,
        "verdict": "PENDING",
        "leaves": {},
        "checks": [],
        "findings": [],
    }
    write_verdict_record(pkg12, pending)
    record_review_round_local(task_id, pkg12)
    if skipped_count > 0:
        print(f"[!] Warning: Working tree has {total_changed} files; {skipped_count} files were skipped in review package.")
    if contains_tests:
        print(f"[*] TEST FILES DETECTED IN DIFF ({len(test_files)} file(s)):")
        for tf in test_files[:5]:
            print(f"    - {tf}")
        if len(test_files) > 5:
            print(f"    ... and {len(test_files) - 5} more.")
        print(f"    [!] Smart Test Promotion ACTIVE: Exactly 6 parallel subagents required (+ test-quality-reviewer-agent -> TEST_PASS).")
    print(f"HARNESS_REVIEW_PACKAGE={out}")
    print(f"HARNESS_PACKAGE_SHA256_12={pkg12}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
