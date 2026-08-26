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


_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def git_head() -> str:
    """Commit hash, or empty string when the checkout has no usable git HEAD."""
    out = git("rev-parse", "HEAD").strip()
    return out if _GIT_SHA_RE.fullmatch(out) else ""


def build_header(task_id: str, fingerprint: str) -> list[str]:
    sha = git_head()
    return [
        HEADER_BEGIN,
        f"TASK_ID={task_id}",
        f"GIT_SHA={sha}",
        f"TREE_FINGERPRINT={fingerprint}",
        f"GENERATED_AT={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    ]


def build_files_map(max_files: int = 200) -> dict[str, str]:
    """SHA-256 per changed working-tree file (rel path -> hex), capped."""
    files_map: dict[str, str] = {}
    for path in changed_paths():
        if len(files_map) >= max_files:
            break
        try:
            rel = path.relative_to(REPO).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            files_map[rel] = file_sha256(path)
        except Exception:
            continue
    return files_map


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
    fingerprint = tree_code_fingerprint() or ""
    files_map = build_files_map()
    files_json = json.dumps(files_map, ensure_ascii=False, separators=(",", ":"))
    chunks = [
        "\n".join([*build_header(task_id, fingerprint), f"FILES_SHA256={files_json}", PACKAGE_SHA_PENDING]) + "\n",
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
    for line in untracked.splitlines():
        rel = line.strip()
        if not rel:
            continue
        file_path = REPO / rel
        extra.append(f"\n## NEW FILE {rel}\n")
        try:
            extra.append(file_path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            extra.append(f"(could not read: {exc})\n")
    if extra:
        chunks.append("\n## untracked files\n")
        chunks.extend(extra)

    out.write_text("".join(chunks), encoding="utf-8", newline="\n")

    # PACKAGE_SHA256 covers every byte preceding its own line (header + body),
    # so the digest is computable post-write without a self-referential hash.
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

    git_sha = git_head()
    record_review_ledger(out, git_sha=git_sha)
    pkg12 = pre_digest[:12]
    pending = {
        "schema_version": 1,
        "task_id": task_id,
        "git_sha": git_sha,
        "package": {"path": str(out.resolve()), "sha256": pre_digest, "sha256_12": pkg12},
        "tree_fingerprint": fingerprint or None,
        "files": files_map,
        "dispatched_at": None,
        "completed_at": None,
        "verdict": "PENDING",
        "leaves": {},
        "checks": [],
        "findings": [],
    }
    write_verdict_record(pkg12, pending)
    print(f"HARNESS_REVIEW_PACKAGE={out}")
    print(f"HARNESS_PACKAGE_SHA256_12={pkg12}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
