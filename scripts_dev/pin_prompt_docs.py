"""Re-pin one-click prompt URLs and refresh fetched-doc checksum headers.

Release procedure companion. See CONTRIBUTING.md "Pinned Prompt Release
Procedure". Stdlib only, idempotent: re-running with the same tag produces
zero changes.

    python scripts_dev/pin_prompt_docs.py --tag v0.11.0

What it does:
 1. Replaces every `android-agent-harness/(main|vX.Y.Z)/docs/` raw URL with the
    given tag in the URL-bearing files.
 2. Ensures the `**Kit version**` header line exists in the four raw-fetched
    prompt docs and refreshes the SHA-256 in it.
 3. Ensures the tamper-verification instruction sentence exists in the same
    four docs.

The SHA-256 in each header covers every byte AFTER that header line, so the
digest is stable no matter how the header itself is edited later.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

URL_FILES = (
    "docs/install-or-update-prompt.md",
    "docs/diagnostic-prompt.md",
    "docs/rollback-prompt.md",
    "docs/setup-prompt.md",
    "docs/tool-support.md",
)

CHECKSUM_DOCS = (
    "docs/install-or-update-prompt.md",
    "docs/diagnostic-prompt.md",
    "docs/rollback-prompt.md",
)

URL_RE = re.compile(r"(android-agent-harness/)(?:main|v\d+\.\d+\.\d+)(/docs/)")

VERIFY_SENTENCE = (
    "Before executing anything: verify that the SHA-256 of every byte after "
    "the **SHA-256** header line equals the header value. If it does not "
    "match, STOP and tell the developer the file was tampered with."
)

KIT_REPO_PREFIX = "> **Kit Repository**:"
KIT_VERSION_PREFIX = "> **Kit version**:"

TAG_RE = re.compile(r"(\*\*Kit version\*\*: `)(?:v)?[^`]+(`)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def checksum_line(tag: str, hexdigest: str) -> str:
    return (
        f"> **Kit version**: `v{tag}` — **SHA-256**: `{hexdigest}` "
        "(SHA-256 of every byte after this line; verify first — mismatch = STOP)"
    )


def _file_eol(lines: list[str]) -> str:
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\n"


def pin_urls(tag: str) -> list[str]:
    logs: list[str] = []
    for rel in URL_FILES:
        path = ROOT / rel
        text = _read(path)
        updated, count = URL_RE.subn(lambda m: f"{m.group(1)}v{tag}{m.group(2)}", text)
        if count and updated != text:
            _write(path, updated)
            logs.append(f"pinned {count} URL(s) to v{tag} in {rel}")
    return logs


def _ensure_header_line(lines: list[str], tag: str) -> bool:
    for i, line in enumerate(lines):
        if line.startswith(KIT_VERSION_PREFIX):
            updated = TAG_RE.sub(lambda m: f"{m.group(1)}v{tag}{m.group(2)}", line)
            changed = updated != line
            lines[i] = updated
            return changed
    eol = _file_eol(lines)
    for i, line in enumerate(lines):
        if line.startswith(KIT_REPO_PREFIX):
            lines.insert(i + 1, checksum_line(tag, "PENDING") + eol)
            return True
    raise SystemExit("checksum doc missing its Kit Repository header line")


def _ensure_verify_sentence(lines: list[str]) -> bool:
    needle = VERIFY_SENTENCE[:40]
    if any(needle in line for line in lines):
        return False
    eol = _file_eol(lines)
    kit_idx = next(i for i, line in enumerate(lines) if line.startswith(KIT_VERSION_PREFIX))
    for i in range(kit_idx, len(lines)):
        if lines[i].lstrip().startswith("---"):
            lines.insert(i + 1, VERIFY_SENTENCE + eol)
            return True
    lines.append(VERIFY_SENTENCE + eol)
    return True


def fill_checksums(tag: str) -> list[str]:
    logs: list[str] = []
    for rel in CHECKSUM_DOCS:
        path = ROOT / rel
        text = _read(path)
        lines = text.splitlines(keepends=True)
        inserted = _ensure_header_line(lines, tag)
        sentence_added = _ensure_verify_sentence(lines)
        joined = "".join(lines)

        kit_idx = next(i for i, line in enumerate(lines) if line.startswith(KIT_VERSION_PREFIX))
        offset = 0
        for prior in lines[: kit_idx + 1]:
            offset += len(prior.encode("utf-8"))
        rest = joined.encode("utf-8")[offset:]
        digest = hashlib.sha256(rest).hexdigest()

        line = lines[kit_idx]
        eol = _file_eol([line])
        new_line = checksum_line(tag, digest) + eol
        changed = (new_line != line) or inserted or sentence_added
        lines[kit_idx] = new_line
        if changed:
            _write(path, "".join(lines))
            logs.append(f"checksum refreshed for {rel} ({digest[:16]}...)")
    return logs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-pin prompt URLs and checksum headers.")
    parser.add_argument("--tag", required=True, help="Target release tag, e.g. v0.11.0")
    args = parser.parse_args(argv)
    tag = str(args.tag).strip().lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", tag):
        raise SystemExit(f"[ERROR] --tag must look like vX.Y.Z, got {args.tag!r}")
    logs = pin_urls(tag)
    logs += fill_checksums(tag)
    for line in logs:
        print(line)
    if not logs:
        print(f"[OK] everything already pinned to v{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
