"""Validate release metadata, pinned prompts, docs, and publish inputs."""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import sys
import json
from pathlib import Path

from pin_prompt_docs import CHECKSUM_DOCS, URL_FILES, VERIFY_SENTENCE


RAW_PROMPT_RE = re.compile(
    r"android-agent-harness/(?P<ref>main|v\d+\.\d+\.\d+)/docs/(?!assets/)"
)
CHECKSUM_RE = re.compile(
    r"\*\*Kit version\*\*: `v(?P<version>\d+\.\d+\.\d+)`"
    r".*\*\*SHA-256\*\*: `(?P<digest>[0-9a-f]{64})`"
)
PINNED_ACTION_RE = re.compile(
    r"uses:\s*pypa/gh-action-pypi-publish@(?P<ref>[^\s#]+)"
)
ACTION_REF_RE = re.compile(r"^\s*-?\s*uses:\s*[^\s@]+@(?P<ref>[^\s#]+)", re.MULTILINE)
FIXED_SCRIPT_COUNT_RE = re.compile(r"\b\d+\s+core\s+(?:harness\s+)?scripts\b", re.IGNORECASE)
TEXT_EXTENSIONS = {
    ".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".xml",
    ".sh", ".bat", ".ps1", ".cff", ".gradle", ".kts", ".properties",
}



def pinned_url_errors(text: str, version: str, label: str) -> list[str]:
    """Report floating or stale raw prompt URLs in one release-controlled file."""
    matches = list(RAW_PROMPT_RE.finditer(text))
    if not matches:
        return []
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


def _extract_job_timeouts(yaml_text: str) -> dict[str, int]:
    """Extract job names and their timeout-minutes values from simple GitHub Actions workflow YAML."""
    jobs: dict[str, int] = {}
    lines = yaml_text.splitlines()
    in_jobs = False
    current_job: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if in_jobs and not line.startswith(" ") and not line.startswith("\t"):
            in_jobs = False
            current_job = None
            continue
        if in_jobs:
            indent = len(line) - len(line.lstrip())
            if indent == 2 and stripped.endswith(":"):
                current_job = stripped[:-1].strip()
                continue
            if current_job and "timeout-minutes:" in stripped:
                match = re.search(r"timeout-minutes:\s*(\d+)", stripped)
                if match:
                    jobs[current_job] = int(match.group(1))
    return jobs


def publish_workflow_errors(text: str) -> list[str]:
    """Require reproducible publish dependencies and an immutable upload action."""
    errors: list[str] = []
    action_match = PINNED_ACTION_RE.search(text)
    if not action_match:
        errors.append("publish workflow: PyPI publish action is missing")
    elif not re.fullmatch(r"[0-9a-f]{40}", action_match.group("ref")):
        errors.append("publish workflow: PyPI publish action must use a full commit SHA")

    if re.search(r"pip\s+install\s+--upgrade\s+pip", text):
        errors.append("publish workflow: unpinned pip upgrade is forbidden")

    install_lines = [line.strip() for line in text.splitlines() if "pip install" in line]
    dependency_line = next(
        (line for line in install_lines if re.search(r"\bbuild(?:==|\s|$)", line)),
        "",
    )
    try:
        dependency_tokens = shlex.split(dependency_line)
    except ValueError:
        dependency_tokens = []
    for tool in ("build==1.6.0", "twine==7.0.0", "setuptools==80.9.0", "wheel==0.45.1"):
        name = tool.split("==", 1)[0]
        observed = [token for token in dependency_tokens if re.fullmatch(rf"{re.escape(name)}(?:==[^\s]+)?", token)]
        if observed != [tool]:
            errors.append(f"publish workflow: {name} must be pinned to exact version ({tool})")

    if "python -m build --no-isolation" not in text:
        errors.append("publish workflow: package build must specify --no-isolation")

    if "id-token: write" not in text:
        errors.append("publish workflow: trusted-publishing id-token permission is missing")
    return errors


def workflow_integrity_errors(repo_root: Path) -> list[str]:
    """Lock immutable actions and the declared runtime/platform coverage."""
    errors: list[str] = []
    workflow_dir = repo_root / ".github" / "workflows"
    for path in sorted(workflow_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for match in ACTION_REF_RE.finditer(text):
            if not re.fullmatch(r"[0-9a-f]{40}", match.group("ref")):
                errors.append(
                    f"{path.relative_to(repo_root).as_posix()}: action references must use full commit SHAs"
                )
                break

    ci_path = workflow_dir / "ci.yml"
    ci = ci_path.read_text(encoding="utf-8")
    for version in ("3.10", "3.11", "3.12", "3.13", "3.14"):
        if f"python-version: '{version}'" not in ci:
            errors.append(f"CI does not exercise supported Python {version}")
    for runner in ("ubuntu-24.04", "windows-2025", "macos-15-intel"):
        if runner not in ci:
            errors.append(f"CI does not exercise supported runner {runner}")
    if not re.search(r"run:\s*python harness_cli\.py selftest(?!\s*--quick)", ci):
        errors.append("CI must run the canonical full selftest")
    if re.search(r"python-version:\s*\[[^\]]+\]", ci):
        errors.append(
            "CI must use an explicit compatibility matrix instead of multiplying the full suite across every platform/runtime pair"
        )

    # Permission checks: explicit top-level permissions: contents: read in ci.yml and release-check.yml
    for wf_name in ("ci.yml", "release-check.yml"):
        wf_path = workflow_dir / wf_name
        if wf_path.is_file():
            wf_text = wf_path.read_text(encoding="utf-8")
            if not re.search(r"^permissions:\s*\n\s+contents:\s*read", wf_text, re.MULTILINE):
                errors.append(f"{wf_name} must declare explicit top-level 'permissions: contents: read'")

    # Job timeout checks
    required_timeouts = {
        "ci.yml": {
            "selftest": 35,
            "performance": 10,
            "release-lifecycle": 15,
            "release-metadata": 5,
        },
        "release-check.yml": {
            "validate-tag": 10,
        },
        "publish-pypi.yml": {
            "pypi-publish": 20,
        },
    }
    for wf_name, jobs in required_timeouts.items():
        wf_path = workflow_dir / wf_name
        if not wf_path.is_file():
            continue
        wf_text = wf_path.read_text(encoding="utf-8")
        observed_timeouts = _extract_job_timeouts(wf_text)
        for job_name, req_timeout in jobs.items():
            actual_job = job_name
            if job_name == "selftest" and "full-selftest" in observed_timeouts:
                actual_job = "full-selftest"
            if actual_job not in observed_timeouts:
                errors.append(f"{wf_name}: job '{job_name}' is missing required timeout-minutes ({req_timeout})")
            elif observed_timeouts[actual_job] != req_timeout:
                errors.append(
                    f"{wf_name}: job '{actual_job}' has timeout-minutes {observed_timeouts[actual_job]}, expected {req_timeout}"
                )

    return errors


def answer_schema_drift_errors(repo_root: Path) -> list[str]:
    """Ensure all question keys in install-or-update-prompt.md are defined in ANSWER_SCHEMA."""
    prompt_path = repo_root / "docs" / "install-or-update-prompt.md"
    if not prompt_path.is_file():
        return ["docs/install-or-update-prompt.md is missing"]
    text = prompt_path.read_text(encoding="utf-8")

    wizard_dir = repo_root / "agents" / "scripts"
    if str(wizard_dir) not in sys.path:
        sys.path.insert(0, str(wizard_dir))
    from wizard.schema import ALLOWED_QUESTION_KEYS

    found_keys = re.findall(r"`(i\d+[a-z]?|b_[a-z]+)`", text)
    unknown = [k for k in found_keys if k not in ALLOWED_QUESTION_KEYS]
    if unknown:
        return [f"install-or-update-prompt.md contains unknown question keys: {', '.join(sorted(set(unknown)))}"]
    return []


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

    citation_path = repo_root / "CITATION.cff"
    citation = citation_path.read_text(encoding="utf-8") if citation_path.is_file() else ""
    if not re.search(r'^cff-version:[ \t]*[\"\']?1\.2\.0[\"\']?[ \t]*$', citation, re.MULTILINE):
        errors.append("CITATION.cff cff-version must be the supported schema 1.2.0")
    if not re.search(rf'^version:[ \t]*[\"\']?{re.escape(version)}[\"\']?[ \t]*$', citation, re.MULTILINE):
        errors.append("CITATION.cff software version must match agents/VERSION")

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

    prompt_path = repo_root / "docs" / "install-or-update-prompt.md"
    if prompt_path.is_file():
        prompt_content = prompt_path.read_text(encoding="utf-8")
        expected_branch = f"--branch v{version} --single-branch"
        if expected_branch not in prompt_content:
            errors.append(f"docs/install-or-update-prompt.md does not pin '{expected_branch}'")
        expected_detached = f"detached `v{version}`"
        if expected_detached not in prompt_content:
            errors.append(f"docs/install-or-update-prompt.md does not reference '{expected_detached}'")
        expected_version_header = f"> **Kit version**: `v{version}`"
        if expected_version_header not in prompt_content:
            errors.append(f"docs/install-or-update-prompt.md does not pin '{expected_version_header}'")

    errors.extend(answer_schema_drift_errors(repo_root))

    security = (repo_root / "SECURITY.md").read_text(encoding="utf-8")
    major, minor, _ = version.split(".")
    supported_line = f"| **v{major}.{minor}.x** | Yes |"
    if supported_line not in security:
        errors.append(f"SECURITY.md must support the current v{major}.{minor}.x release line")

    # License consistency checks (M4)
    license_path = repo_root / "LICENSE"
    if not license_path.is_file() or not license_path.read_text(encoding="utf-8").startswith("MIT License"):
        errors.append("LICENSE must be MIT License")
    if not re.search(r'^license:\s*["\']?MIT["\']?$', citation, re.MULTILINE):
        errors.append("CITATION.cff license must be MIT")
    if not re.search(r'^license\s*=\s*"MIT"', pyproject, re.MULTILINE):
        errors.append('pyproject.toml project.license must be "MIT"')
    if not re.search(r'license-files\s*=\s*\["LICENSE"\]', pyproject):
        errors.append('pyproject.toml must declare license-files = ["LICENSE"]')
    if re.search(r'license\s*=\s*\{', pyproject):
        errors.append("pyproject.toml must not use deprecated table format for project.license")

    # README checks (M4)
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    if not re.search(r"## License\s*\n+MIT License\.", readme):
        errors.append("README.md license section must state MIT License")
    if "```mermaid" in readme:
        errors.append("README.md must not contain a Mermaid fence (use static SVG instead)")
    link_matches = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', readme)
    for text_lbl, link_target in link_matches:
        link_target = link_target.strip()
        if link_target.startswith("#") or link_target.startswith("http://") or link_target.startswith("https://") or link_target.startswith("mailto:"):
            continue
        errors.append(f"README.md contains relative link [{text_lbl}]({link_target}) that cannot be resolved on PyPI; use absolute URL")

    for rel in ("docs/architecture.md", "docs/diagnostic-prompt.md"):
        text = (repo_root / rel).read_text(encoding="utf-8")
        if FIXED_SCRIPT_COUNT_RE.search(text):
            errors.append(f"{rel}: fixed core-script count must use the canonical inventory")

    architecture = (repo_root / "docs" / "architecture.md").read_text(encoding="utf-8")
    workflows = (repo_root / "docs" / "workflows.md").read_text(encoding="utf-8")
    for marker in ("AWAITING_DEVELOPER_APPROVAL", "delivery snapshot", "final verifier", "RULE_ENFORCED"):
        if marker not in architecture:
            errors.append(f"docs/architecture.md missing v1 contract marker: {marker}")
    for marker in ("explicit developer approval", "selected gates", "Read-only final verification"):
        if marker not in workflows:
            errors.append(f"docs/workflows.md missing v1 workflow marker: {marker}")

    checksum_path = repo_root / "agents" / "release_checksums.json"
    try:
        checksums = json.loads(checksum_path.read_text(encoding="utf-8"))
        if checksums.get("schema_version") != 1 or checksums.get("algorithm") != "sha256":
            errors.append("agents/release_checksums.json has an unsupported schema")
        expected_paths = {
            path.relative_to(repo_root).as_posix()
            for path in (repo_root / "agents").rglob("*")
            if path.is_file() and path != checksum_path
            and not {"state", "cache", "__pycache__"}.intersection(path.relative_to(repo_root / "agents").parts)
            and path.suffix not in {".pyc", ".pyo"}
        }
        files = checksums.get("files")
        if not isinstance(files, dict) or not files or set(files) != expected_paths:
            errors.append("release checksum inventory must cover the complete installable payload")
        for rel, expected in (files if isinstance(files, dict) else {}).items():
            if rel not in expected_paths:
                continue
            path = repo_root / rel
            if path.is_symlink() or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                errors.append(f"invalid release checksum entry: {rel}")
                continue
            if not path.is_file():
                errors.append(f"release checksum target missing: {rel}")
                continue
            raw_data = path.read_bytes()
            if path.suffix.lower() in TEXT_EXTENSIONS and b"\r\n" in raw_data:
                errors.append(f"release target contains Windows CRLF line endings: {rel}")
            elif hashlib.sha256(raw_data).hexdigest() != expected:
                errors.append(f"release checksum mismatch: {rel}")

    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"agents/release_checksums.json is missing or unreadable: {exc}")

    publish = (repo_root / ".github" / "workflows" / "publish-pypi.yml").read_text(encoding="utf-8")
    errors.extend(publish_workflow_errors(publish))
    errors.extend(workflow_integrity_errors(repo_root))
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
