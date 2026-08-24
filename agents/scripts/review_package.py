"""Write a working-tree review package (staged + unstaged + untracked vs HEAD). Inspection only. No git mutations."""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _hook_state import record_review_ledger  # noqa: E402

enable_line_buffered_stdio()

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parents[1] / "state" / "packages"


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write working-tree diff package for the 5 review leaves")
    parser.add_argument("paths", nargs="*", help="Optional paths to include (default: all unstaged)")
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

    chunks = [
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

    out.write_text("".join(chunks), encoding="utf-8")
    record_review_ledger(out)
    print(f"HARNESS_REVIEW_PACKAGE={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
