"""Validate release metadata, pinned prompts, docs, and publish inputs."""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

from pin_prompt_docs import CHECKSUM_DOCS, URL_FILES, VERIFY_SENTENCE


RAW_PROMPT_RE = re.compile(
    r"android-agent-harness/(?P<ref>main|v\d+\.\d+\.\d+)/docs/"
)
CHECKSUM_RE = re.compile(
    r"\*\*Kit version\*\*: `v(?P<version>\d+\.\d+\.\d+)`"
    r".*\*\*SHA-256\*\*: `(?P<digest>[0-9a-f]{64})`"
)
PINNED_ACTION_RE = re.compile(
    r"uses:\s*pypa/gh-action-pypi-publish@(?P<ref>[^\s#]+)"
)
FIXED_SCRIPT_COUNT_RE = re.compile(r"\b\d+\s+core\s+(?:harness\s+)?scripts\b", re.IGNORECASE)


def pinned_url_errors(text: str, version: str, label: str) -> list[str]:
    """Report floating or stale raw prompt URLs in one release-controlled file."""
    matches = list(RAW_PROMPT_RE.finditer(text))
    if not matches:
        return [f"{label}: no versioned raw prompt URL found"]
    expected = f"v{version}"
    return [
        f"{label}: raw prompt URL uses {match.group('ref')}, expected {expected}"
        for match in matches
        if match.group("ref") != expected
    ]


def checksum_doc_error(data: bytes, version: str, label: str) -> str | None:
    """Validate a prompt version/checksum header against its exact byte payload."""
    lines = data.splitlines(keepends=True)
    header_index = next(
        (index for index, line in enumerate(lines) if line.startswith(b"> **Kit version**:")),
        None,
    )
    if header_index is None:
        return f"{label}: missing Kit version and SHA-256 header"
    header = lines[header_index].decode("utf-8", errors="replace")
    match = CHECKSUM_RE.search(header)
    if not match:
        return f"{label}: malformed Kit version or SHA-256 header"
    if match.group("version") != version:
        return f"{label}: checksum header version {match.group('version')} != {version}"
    payload = b"".join(lines[header_index + 1 :])
    actual = hashlib.sha256(payload).hexdigest()
    if match.group("digest") != actual:
        return f"{label}: SHA-256 header is stale"
    if VERIFY_SENTENCE[:40].encode("utf-8") not in payload:
        return f"{label}: tamper-verification instruction is missing"
    return None


def publish_workflow_errors(text: str) -> list[str]:
    """Require reproducible publish dependencies and an immutable upload action."""
    errors: list[str] = []
    action_match = PINNED_ACTION_RE.search(text)
    if not action_match:
        errors.append("publish workflow: PyPI publish action is missing")
    elif not re.fullmatch(r"[0-9a-f]{40}", action_match.group("ref")):
        errors.append("publish workflow: PyPI publish action must use a full commit SHA")

    install_lines = [line.strip() for line in text.splitlines() if "pip install" in line]
    dependency_line = next(
        (line for line in install_lines if re.search(r"\bbuild(?:==|\s|$)", line)),
        "",
    )
    if not re.search(r"\bbuild==\d+\.\d+\.\d+\b", dependency_line):
        errors.append("publish workflow: build must be pinned to an exact version")
    if not re.search(r"\btwine==\d+\.\d+\.\d+\b", dependency_line):
        errors.append("publish workflow: twine must be pinned to an exact version")
    if "id-token: write" not in text:
        errors.append("publish workflow: trusted-publishing id-token permission is missing")
    return errors


def validate_release(repo_root: Path, tag: str) -> list[str]:
    errors: list[str] = []
    version_file = repo_root / "agents" / "VERSION"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return [f"agents/VERSION could not be read: {exc}"]

    if tag and version != tag:
        errors.append(f"agents/VERSION ({version}) does not match tag ({tag})")

    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    if not re.search(rf'^version\s*=\s*"{re.escape(version)}"\s*$', pyproject, re.MULTILINE):
        errors.append(f"pyproject.toml version does not match agents/VERSION ({version})")

    changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## \[{re.escape(version)}\]", changelog, re.MULTILINE):
        errors.append(f"Version {version} not found as a CHANGELOG.md release heading")

    for rel in URL_FILES:
        path = repo_root / rel
        if not path.is_file():
            errors.append(f"{rel}: pinned URL file is missing")
            continue
        errors.extend(pinned_url_errors(path.read_text(encoding="utf-8"), version, rel))

    for rel in CHECKSUM_DOCS:
        path = repo_root / rel
        if not path.is_file():
            errors.append(f"{rel}: checksum prompt is missing")
            continue
        checksum_issue = checksum_doc_error(path.read_bytes(), version, rel)
        if checksum_issue:
            errors.append(checksum_issue)

    security = (repo_root / "SECURITY.md").read_text(encoding="utf-8")
    major, minor, _ = version.split(".")
    supported_line = f"| **v{major}.{minor}.x** | Yes |"
    if supported_line not in security:
        errors.append(f"SECURITY.md must support the current v{major}.{minor}.x release line")

    for rel in ("docs/architecture.md", "docs/diagnostic-prompt.md"):
        text = (repo_root / rel).read_text(encoding="utf-8")
        if FIXED_SCRIPT_COUNT_RE.search(text):
            errors.append(f"{rel}: fixed core-script count must use the canonical inventory")

    architecture = (repo_root / "docs" / "architecture.md").read_text(encoding="utf-8")
    workflows = (repo_root / "docs" / "workflows.md").read_text(encoding="utf-8")
    if "Preflight --> ReviewPackage" not in architecture or "ReviewPackage --> ReviewGate" not in architecture:
        errors.append("docs/architecture.md must place preflight before review packaging")
    if "D -- Tests Pass --> E[\"4. Preflight Gate\"]" not in workflows or "E -- PASS --> F[\"5. Review Package\"]" not in workflows:
        errors.append("docs/workflows.md must place preflight before review packaging")

    quickstart = (repo_root / "docs" / "quickstart.md").read_text(encoding="utf-8")
    if "Exit codes: 0 PASS, 1 FAIL, 2 STALE/incomplete." not in quickstart:
        errors.append("docs/quickstart.md must document the verified 0/1/2 exit-code contract")

    publish = (repo_root / ".github" / "workflows" / "publish-pypi.yml").read_text(encoding="utf-8")
    errors.extend(publish_workflow_errors(publish))
    return errors


def main() -> int:
    ref_name = os.environ.get("REF_NAME", "")
    if not ref_name and len(sys.argv) > 1:
        ref_name = sys.argv[1]
    tag = ref_name.lstrip("v")
    if tag and not re.fullmatch(r"\d+\.\d+\.\d+", tag):
        print(f"[FAIL] Invalid release tag: {ref_name}", file=sys.stderr)
        return 1

    repo_root = Path(__file__).resolve().parent.parent
    errors = validate_release(repo_root, tag)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        return 1

    version = (repo_root / "agents" / "VERSION").read_text(encoding="utf-8").strip()
    print(f"Release version {version} is valid and aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
