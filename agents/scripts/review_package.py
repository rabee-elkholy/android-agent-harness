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
    tree_code_fingerprint,
    write_verdict_record,
)
from _repo_files import changed_paths  # noqa: E402

enable_line_buffered_stdio()

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parents[1] / "state" / "packages"

HEADER_BEGIN = "# HARNESS_PACKAGE_HEADER v2"
PACKAGE_SHA_MARKER = "PACKAGE_SHA256="
PACKAGE_SHA_PENDING = "PACKAGE_SHA256=PENDING"


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
) -> list[str]:
    sha = git_head()
    return [
        HEADER_BEGIN,
        f"TASK_ID={task_id}",
        f"GIT_SHA={sha}",
        f"TREE_FINGERPRINT={fingerprint}",
        f"RISK_TIER={risk_tier}",
        f"CONTAINS_TESTS={'true' if contains_tests else 'false'}",
        f"TEST_FILES_COUNT={test_files_count}",
        f"REQUIRED_LEAVES={'6' if contains_tests else '5'}",
        f"GENERATED_AT={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    ]


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



def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write working-tree diff package for the 5 review leaves")
    parser.add_argument("paths", nargs="*", help="Optional paths to include (default: all unstaged)")
    parser.add_argument("--task", default=None, help="Task id recorded in the package header (default: $HARNESS_TASK_ID).")
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

    # Hard Pre-Gate: run diff-scoped fast_kt_lint before generating the review package
    fast_lint_script = Path(__file__).resolve().parent / "fast_kt_lint.py"
    if fast_lint_script.is_file():
        lint_proc = subprocess.run(
            [sys.executable, str(fast_lint_script)],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if lint_proc.returncode != 0:
            print(
                "[FAIL] Cannot generate review package: Fast Kotlin Lint detected violations on modified lines:",
                file=sys.stderr,
            )
            if lint_proc.stdout.strip():
                print(lint_proc.stdout.strip(), file=sys.stderr)
            if lint_proc.stderr.strip():
                print(lint_proc.stderr.strip(), file=sys.stderr)
            print("\n[!] Fix all lint violations above before generating a review package.", file=sys.stderr)
            return 1

    fingerprint = tree_code_fingerprint() or ""
    risk_tier, _ = classify_working_tree_risk(REPO, list(changed_paths()))
    files_map, total_changed = build_files_map()
    skipped_count = max(0, total_changed - len(files_map))
    test_files = [f for f in files_map.keys() if is_test_file(f)]
    contains_tests = len(test_files) > 0
    print(f"[*] Packaging review diff for {len(files_map)} file(s) (risk tier: {risk_tier})...", flush=True)
    files_json = json.dumps(files_map, ensure_ascii=False, separators=(",", ":"))
    chunks = [
        "\n".join([
            *build_header(
                task_id,
                fingerprint,
                risk_tier,
                contains_tests=contains_tests,
                test_files_count=len(test_files),
            ),
            f"FILES_SHA256={files_json}",
            PACKAGE_SHA_PENDING,
        ]) + "\n",
        f"# Harness review package (unstaged vs HEAD)\n# repo: {REPO}\n",
        "## git status\n",
        git(*status_cmd),
        "\n## git diff --stat\n",
        git(*diff_stat_cmd),
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
