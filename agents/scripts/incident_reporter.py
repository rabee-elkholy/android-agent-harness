"""Automated Zero-PII Incident Reporter for Android Agent Harness.

Captures unexpected harness exceptions, routing contradictions, repeated step
failures, and automatic self-healing transitions into sanitized local incident
bundles under `.agents/state/incidents/` and optionally submits deduplicated
GitHub Issues to `rabee-elkholy/android-agent-harness` via `gh` CLI (or emits a
pre-filled GitHub Issue URL when `gh` is unavailable).

Standard library Python only. Public exports use allowlisted metadata only.
Local diagnostic text is best-effort redacted and may contain sensitive data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _vnext_common import atomic_write_json, canonical_sha256, read_json, redact, state_root, utc_now  # noqa: E402

UPSTREAM_REPO = "rabee-elkholy/android-agent-harness"
INCIDENT_LABEL = "auto-incident-report"
MAX_STORED_INCIDENTS = 50


def _incidents_dir(repo: Path) -> Path:
    root = state_root(repo) / "incidents"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _preferences_path(repo: Path) -> Path:
    return state_root(repo) / "incident-preferences.json"


def is_auto_submit_enabled(repo: Path) -> bool:
    """Return True only when the developer explicitly opted into automatic incident submission."""
    if os.environ.get("HARNESS_AUTO_SUBMIT_INCIDENTS") == "1":
        return True
    pref_file = _preferences_path(repo)
    if pref_file.is_file():
        try:
            data = read_json(pref_file)
            return bool(data.get("auto_submit_incidents") is True)
        except (OSError, ValueError):
            return False
    return False


def set_auto_submit_preference(repo: Path, enabled: bool) -> dict[str, Any]:
    """Persist the developer's preference for automatic anonymous incident submission."""
    pref_file = _preferences_path(repo)
    pref_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "auto_submit_incidents": bool(enabled),
        "updated_at": utc_now(),
    }
    atomic_write_json(pref_file, payload)
    return payload


def _strict_zero_pii_text(text: str, repo: Path | None = None) -> str:
    """Strictly scrub PII, paths, emails, phones, IPs, URLs, and tokens from local diagnostic strings."""
    cleaned = _sanitize_text(text, repo)
    # Scrub emails
    cleaned = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<REDACTED_EMAIL>", cleaned)
    # Scrub phone-like sequences (+country or 10-15 digits)
    cleaned = re.sub(r"\+[0-9][0-9\s-]{7,16}[0-9]", "<REDACTED_PHONE>", cleaned)
    # Scrub IPv4 addresses
    cleaned = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<REDACTED_IP>", cleaned)
    # Scrub Windows/Unix absolute paths that remain outside <REPO_ROOT> / <USER_HOME>
    cleaned = re.sub(r"[A-Za-z]:[\\/][^\s\"':,;<>|]+", "<LOCAL_PATH>", cleaned)
    return cleaned


def _installed_version(repo: Path) -> str:
    for candidate in (repo / ".agents" / "VERSION", repo / "agents" / "VERSION"):
        if candidate.is_file():
            try:
                val = candidate.read_text(encoding="utf-8").strip()
                if val:
                    return val
            except OSError:
                continue
    return "unknown"


def _sanitize_text(text: str, repo: Path | None = None) -> str:
    """Redact secrets, tokens, and replace local filesystem roots with placeholders."""
    cleaned = str(redact(str(text or "")))
    if repo is not None:
        try:
            repo_str = str(repo.resolve())
            cleaned = re.sub(re.escape(repo_str), "<REPO_ROOT>", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(re.escape(repo_str.replace("\\", "/")), "<REPO_ROOT>", cleaned, flags=re.IGNORECASE)
        except OSError:
            pass
    try:
        home_str = str(Path.home().resolve())
        cleaned = re.sub(re.escape(home_str), "<USER_HOME>", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(re.escape(home_str.replace("\\", "/")), "<USER_HOME>", cleaned, flags=re.IGNORECASE)
    except OSError:
        pass
    # Scrub generic Windows/Unix user paths
    cleaned = re.sub(r"[A-Za-z]:[\\/](?:Users|home)[\\/][^\\/\s\"']+", "<USER_HOME>", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"/(?:Users|home)/[^/\s\"']+", "<USER_HOME>", cleaned, flags=re.IGNORECASE)
    return cleaned


def _extract_engine_frames(traceback_text: str, repo: Path | None = None) -> list[str]:
    """Keep only stack frames originating from harness scripts, stripping client code."""
    if not traceback_text:
        return []
    sanitized = _sanitize_text(traceback_text, repo)
    lines = sanitized.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("File "):
            if any(marker in stripped for marker in (".agents", "agents/scripts", "agents\\scripts", "harness_cli.py", "harness.py")):
                # Normalize line to only relative engine path + line number + function
                kept.append(stripped)
        elif stripped and not stripped.startswith("Traceback ") and len(kept) < 25:
            # Keep exception type/message line or frame summary
            if any( stripped.startswith(prefix) for prefix in ("ValidationError", "RuntimeError", "ValueError", "KeyError", "TypeError", "OSError", "AssertionError", "[FAIL]", "ERROR:")):
                kept.append(stripped[:240])
    return kept[:20]


def compute_incident_fingerprint(
    *,
    code: str,
    command: str,
    task_state: str,
    engine_frames: list[str],
    message: str,
) -> str:
    """Deterministic fingerprint so identical incidents across runs/users deduplicate."""
    cmd_tokens = [tok for tok in str(command or "").split() if not tok.startswith("-") and "/" not in tok and "\\" not in tok]
    cmd_base = " ".join(cmd_tokens[:3]).lower()
    top_frame = engine_frames[-1] if engine_frames else ""
    # Normalize digits out of message for stable grouping
    norm_msg = re.sub(r"\b[0-9a-f]{8,64}\b", "<HASH>", str(message or "").lower())
    norm_msg = re.sub(r"'[^']*'", "'<VAL>'", norm_msg)[:160]
    payload = {
        "code": str(code or "UNKNOWN").upper(),
        "command_base": cmd_base,
        "task_state": str(task_state or "").upper(),
        "top_frame": top_frame,
        "norm_msg": norm_msg,
    }
    return canonical_sha256(payload)


def _public_incident(incident: dict[str, Any]) -> dict[str, Any]:
    """Export only bounded diagnostic metadata, including for old local reports.

    Redaction is best-effort for local logs; arbitrary strings never belong in
    automatic public reports. Rebuild the URL too: legacy URLs contain raw text.
    """
    def choice(key, allowed, default="unknown"):
        value = incident.get(key)
        return value if isinstance(value, str) and value in allowed else default

    def version(key):
        value = incident.get(key)
        return value if isinstance(value, str) and re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", value) else "unknown"

    fp = incident.get("fingerprint_sha256")
    if not isinstance(fp, str) or not re.fullmatch(r"[0-9a-f]{64}", fp):
        fp = "unknown"
    os_name = str(incident.get("os") or "").split("-", 1)[0]
    return {
        "fingerprint_sha256": fp,
        "harness_version": version("harness_version"),
        "python_version": version("python_version"),
        "host": choice("host", {"antigravity", "claude", "codex", "cli", "gemini"}),
        "os": os_name if os_name in {"Linux", "Windows", "Darwin"} else "unknown",
        "code": choice("code", {"HARNESS_CONTRADICTION", "AUTO_HEAL_TRIGGERED", "HARNESS_INCIDENT",
                                "UNEXPECTED_EXCEPTION", "MANUAL_REPORT"}, "HARNESS_INCIDENT"),
        "task_state": choice("task_state", {"DRAFT", "PENDING_APPROVAL", "APPROVED", "IMPLEMENTING",
                             "VERIFYING", "READY_FOR_DELIVERY", "DELIVERED", "CANCELLED"}, "UNKNOWN"),
        "healed": incident.get("healed") is True,
        "command": "harness",
    }


def build_github_issue_url(incident: dict[str, Any], target_repo: str = UPSTREAM_REPO) -> str:
    """Construct a pre-filled GitHub Issue URL for one-click developer or agent reporting."""
    incident = _public_incident(incident)
    fp_short = str(incident.get("fingerprint_sha256") or "")[:10]
    code = str(incident.get("code") or "INCIDENT")
    version = str(incident.get("harness_version") or "unknown")
    cmd = str(incident.get("command") or "harness")
    title = f"[Auto-Incident][v{version}] {code} in `{cmd}` ({fp_short})"
    body = format_issue_markdown(incident)
    params = urllib.parse.urlencode({
        "title": title[:200],
        "body": body[:6000],
        "labels": INCIDENT_LABEL,
    })
    return f"https://github.com/{target_repo}/issues/new?{params}"


def format_issue_markdown(incident: dict[str, Any]) -> str:
    """Render a clean, sanitized Markdown report suitable for GitHub Issues."""
    public = _public_incident(incident)
    return "\n".join([
        "### Harness Incident Metadata", "",
        f"- **Fingerprint**: `fingerprint:{public['fingerprint_sha256']}`",
        f"- **Harness Version**: `{public['harness_version']}`",
        f"- **Host / OS / Python**: `{public['host']}` / `{public['os']}` / `{public['python_version']}`",
        f"- **Code**: `{public['code']}`",
        f"- **Task State**: `{public['task_state']}`",
        f"- **Auto-Healed**: `{public['healed']}`", "",
        "Free-text diagnostics, command arguments, paths, timestamps and extra data remain local.",
        "Local logs may contain sensitive information; review them before sharing.", "",
    ])


def format_local_incident_markdown(incident: dict[str, Any]) -> str:
    """Render an organized, strictly Zero-PII Markdown summary for local inspection."""
    public = _public_incident(incident)
    lines = [
        f"# Harness Incident Report: `{incident.get('incident_id')}`",
        "",
        "## 1. Zero-PII Metadata",
        f"- **Incident ID**: `{incident.get('incident_id')}`",
        f"- **Fingerprint**: `{public['fingerprint_sha256']}`",
        f"- **Code**: `{public['code']}`",
        f"- **Harness Version**: `v{public['harness_version']}`",
        f"- **Host / OS / Python**: `{public['host']}` / `{public['os']}` / `{public['python_version']}`",
        f"- **Task State**: `{public['task_state']}`",
        f"- **Auto-Healed**: `{public['healed']}`",
        f"- **Created At (UTC)**: `{incident.get('created_at')}`",
        f"- **Sanitized Command**: `{incident.get('command')}`",
        "",
        "## 2. Sanitized Diagnostic Summary (Zero-PII)",
        f"```text",
        str(incident.get("message") or "No message recorded."),
        "```",
    ]
    frames = incident.get("engine_frames") or []
    if frames:
        lines.extend([
            "",
            "## 3. Harness Engine Frames (Client Code Stripped)",
            "```text",
            *frames,
            "```",
        ])
    lines.extend([
        "",
        "## 4. Reporting Actions",
        f"- **Submit once**: `python .agents/harness.py report-issue --submit --incident-id {incident.get('incident_id')}`",
        f"- **Submit & enable always-auto-submit**: `python .agents/harness.py report-issue --submit --incident-id {incident.get('incident_id')} --always-auto-submit`",
        f"- **Disable auto-submit**: `python .agents/harness.py report-issue --disable-auto-submit`",
        "",
    ])
    return "\n".join(lines)


def build_incident_question_guidance(incident: dict[str, Any]) -> dict[str, Any]:
    """Build structured ask_question guidance so the agent asks the developer whether to submit."""
    inc_id = str(incident.get("incident_id") or "")
    fp_short = str(incident.get("fingerprint_sha256") or "")[:10]
    code = str(incident.get("code") or "UNEXPECTED_EXCEPTION")
    msg = str(incident.get("message") or "")[:180]
    return {
        "code": "INCIDENT_REPORT_DECISION_REQUIRED",
        "kind": "DEVELOPER_ACTION",
        "tool": "ask_question",
        "incident_id": inc_id,
        "fingerprint_short": fp_short,
        "local_json": f".agents/state/incidents/{inc_id}.json",
        "local_markdown": f".agents/state/incidents/{inc_id}.md",
        "submit_once_command": f"python .agents/harness.py report-issue --submit --incident-id {inc_id}",
        "submit_always_command": f"python .agents/harness.py report-issue --submit --incident-id {inc_id} --always-auto-submit",
        "instructions": (
            f"An unexpected harness incident (`{inc_id}`, `{code}`) was saved locally with strict Zero-PII redaction at "
            f"`.agents/state/incidents/{inc_id}.md` (`{msg}`). "
            "Ask the developer via `ask_question` whether to submit this anonymous report to GitHub Issues with 3 options: "
            "1) `(Recommended) Submit anonymous report to GitHub` -> run `submit_once_command`, "
            "2) `Always auto-submit anonymous reports` -> run `submit_always_command`, "
            "3) `Keep local only (do not submit)` -> take no submission action."
        ),
    }


def _is_test_or_ci_environment() -> bool:
    if os.environ.get("HARNESS_FORCE_AUTO_REPORT") == "1":
        return False
    if os.environ.get("HARNESS_DISABLE_AUTO_REPORT") == "1":
        return True
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        return True
    if "unittest" in sys.modules:
        return True
    return False


def record_incident(
    repo: Path,
    *,
    code: str,
    command: str,
    message: str = "",
    error_message: str = "",
    title: str = "",
    task_id: str = "",
    task_state: str = "",
    task_status: str = "",
    next_action: str = "",
    traceback_text: str = "",
    healed: bool = False,
    heal_action: str = "",
    extra: dict[str, Any] | None = None,
    auto_submit: bool | None = None,
) -> dict[str, Any]:
    """Record a sanitized local incident report and optionally submit to GitHub Issues."""
    repo = Path(repo).resolve()
    inc_dir = _incidents_dir(repo)
    effective_msg = message or error_message or title
    effective_state = task_state or task_status
    clean_msg = _strict_zero_pii_text(effective_msg, repo)
    clean_cmd = _strict_zero_pii_text(command, repo)
    frames = _extract_engine_frames(traceback_text, repo)
    fp = compute_incident_fingerprint(
        code=code,
        command=clean_cmd,
        task_state=effective_state,
        engine_frames=frames,
        message=clean_msg,
    )
    index_path = inc_dir / "index.json"
    try:
        index_data = read_json(index_path) if index_path.is_file() else {"incidents": []}
        items = list(index_data.get("incidents") or [])
    except (OSError, ValueError):
        items = []

    for existing_item in reversed(items):
        if existing_item.get("fingerprint_sha256") == fp:
            existing_file = inc_dir / str(existing_item.get("path") or f"{existing_item.get('incident_id')}.json")
            if existing_file.is_file():
                try:
                    existing_payload = read_json(existing_file)
                    existing_payload["status"] = "DUPLICATE"
                    existing_payload["issue_url"] = build_github_issue_url(existing_payload)
                    existing_payload["ask_question_guidance"] = build_incident_question_guidance(existing_payload)
                    return existing_payload
                except (OSError, ValueError):
                    pass

    ts = int(time.time())
    incident_id = f"incident-{ts}-{fp[:8]}"
    host = (
        os.environ.get("HARNESS_HOST")
        or os.environ.get("HARNESS_HOOK_HOST")
        or ("antigravity" if (repo / "GEMINI.md").is_file() else "cli")
    )
    clean_extra: dict[str, Any] = {}
    if isinstance(extra, dict):
        for k, v in extra.items():
            clean_key = _strict_zero_pii_text(str(k), repo)
            if isinstance(v, (str, int, float, bool)) or v is None:
                clean_extra[clean_key] = _strict_zero_pii_text(str(v), repo) if isinstance(v, str) else v
            elif isinstance(v, (list, dict)):
                clean_extra[clean_key] = json.loads(_strict_zero_pii_text(json.dumps(v, ensure_ascii=False), repo))
    if title:
        clean_extra.setdefault("title", _strict_zero_pii_text(title, repo))
    if next_action:
        clean_extra.setdefault("next_action", str(next_action))

    incident: dict[str, Any] = {
        "schema_version": 1,
        "status": "RECORDED",
        "incident_id": incident_id,
        "fingerprint_sha256": fp,
        "code": str(code or "HARNESS_INCIDENT").upper(),
        "harness_version": _installed_version(repo),
        "host": host,
        "os": f"{platform.system()}-{platform.release()}",
        "python_version": platform.python_version(),
        "command": clean_cmd[:300],
        "task_id_hash": hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:12] if task_id else "",
        "task_state": str(effective_state or "").upper(),
        "message": clean_msg[:2000],
        "engine_frames": frames,
        "healed": bool(healed),
        "heal_action": str(heal_action or ""),
        "extra": clean_extra,
        "created_at": utc_now(),
        "epoch": ts,
    }
    incident["issue_url"] = build_github_issue_url(incident)
    incident["ask_question_guidance"] = build_incident_question_guidance(incident)

    incident_path = inc_dir / f"{incident_id}.json"
    atomic_write_json(incident_path, incident)
    try:
        md_path = inc_dir / f"{incident_id}.md"
        md_path.write_text(format_local_incident_markdown(incident), encoding="utf-8", newline="\n")
    except OSError:
        pass

    items.append({
        "incident_id": incident_id,
        "fingerprint_sha256": fp,
        "code": incident["code"],
        "command": incident["command"],
        "task_state": incident["task_state"],
        "healed": incident["healed"],
        "heal_action": incident["heal_action"],
        "created_at": incident["created_at"],
        "path": str(incident_path.name),
        "markdown_path": f"{incident_id}.md",
    })
    if len(items) > MAX_STORED_INCIDENTS:
        for stale in items[:-MAX_STORED_INCIDENTS]:
            stale_file = inc_dir / str(stale.get("path") or "")
            stale_md = inc_dir / str(stale.get("markdown_path") or f"{stale.get('incident_id')}.md")
            try:
                stale_file.unlink(missing_ok=True)
                stale_md.unlink(missing_ok=True)
            except OSError:
                pass
        items = items[-MAX_STORED_INCIDENTS:]
    atomic_write_json(index_path, {"schema_version": 1, "updated_at": utc_now(), "incidents": items})

    effective_auto_submit = is_auto_submit_enabled(repo) if auto_submit is None else bool(auto_submit)
    if effective_auto_submit and not _is_test_or_ci_environment():
        submit_res = submit_incident_to_github(repo, incident, timeout_seconds=4.0)
        incident["submission"] = submit_res
        atomic_write_json(incident_path, incident)

    return incident


def submit_incident_to_github(
    repo: Path,
    incident: dict[str, Any],
    *,
    target_repo: str = UPSTREAM_REPO,
    dry_run: bool = False,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """Submit an incident to GitHub Issues via `gh` CLI with fingerprint deduplication."""
    incident = _public_incident(incident)
    inc_dir = _incidents_dir(repo)
    reported_path = inc_dir / "reported-index.json"
    try:
        reported = read_json(reported_path) if reported_path.is_file() else {"reported": {}}
        reported_map = dict(reported.get("reported") or {})
    except (OSError, ValueError):
        reported_map = {}

    fp = str(incident.get("fingerprint_sha256") or "")
    if fp and fp in reported_map and not dry_run:
        return {
            "status": "ALREADY_REPORTED_LOCALLY",
            "fingerprint_sha256": fp,
            "issue_url": reported_map[fp].get("issue_url") or incident.get("issue_url", ""),
        }

    fp_short = fp[:10]
    code = str(incident.get("code") or "INCIDENT")
    version = str(incident.get("harness_version") or "unknown")
    cmd = str(incident.get("command") or "harness")
    title = f"[Auto-Incident][v{version}] {code} in {cmd} ({fp_short})"
    body = format_issue_markdown(incident)

    if dry_run:
        return {
            "status": "DRY_RUN",
            "target_repo": target_repo,
            "title": title,
            "fingerprint_sha256": fp,
            "prefilled_url": incident.get("issue_url") or build_github_issue_url(incident, target_repo),
            "body_preview": body,
        }

    gh_bin = shutil.which("gh")
    if not gh_bin:
        return {
            "status": "GH_CLI_UNAVAILABLE",
            "message": "GitHub CLI (gh) is not installed; use the pre-filled issue_url to report.",
            "issue_url": incident.get("issue_url") or build_github_issue_url(incident, target_repo),
        }

    try:
        # 1. Check if an issue with this fingerprint already exists upstream
        search_proc = subprocess.run(
            [
                gh_bin, "issue", "list",
                "--repo", target_repo,
                "--state", "all",
                "--search", f"fingerprint:{fp} in:body",
                "--json", "number,url,state",
                "--limit", "1",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if search_proc.returncode == 0 and (search_proc.stdout or "").strip():
            existing = json.loads(search_proc.stdout)
            if isinstance(existing, list) and existing:
                issue_url = str(existing[0].get("url") or "")
                reported_map[fp] = {
                    "reported_at": utc_now(),
                    "issue_url": issue_url,
                    "deduplicated": True,
                }
                atomic_write_json(reported_path, {"schema_version": 1, "reported": reported_map})
                return {
                    "status": "DEDUPLICATED_EXISTING_ISSUE",
                    "issue_url": issue_url,
                    "issue_number": existing[0].get("number"),
                    "fingerprint_sha256": fp,
                }

        # 2. Create the issue on the upstream repository
        create_proc = subprocess.run(
            [
                gh_bin, "issue", "create",
                "--repo", target_repo,
                "--title", title[:200],
                "--body", body,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if create_proc.returncode == 0:
            created_url = (create_proc.stdout or "").strip().splitlines()[-1].strip()
            reported_map[fp] = {
                "reported_at": utc_now(),
                "issue_url": created_url,
                "deduplicated": False,
            }
            atomic_write_json(reported_path, {"schema_version": 1, "reported": reported_map})
            return {
                "status": "REPORTED",
                "issue_url": created_url,
                "fingerprint_sha256": fp,
            }
        return {
            "status": "GH_SUBMIT_FAILED",
            "message": _sanitize_text((create_proc.stderr or create_proc.stdout or "").strip()[:300], repo),
            "issue_url": incident.get("issue_url") or build_github_issue_url(incident, target_repo),
        }
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "GH_SUBMIT_ERROR",
            "message": _sanitize_text(str(exc), repo),
            "issue_url": incident.get("issue_url") or build_github_issue_url(incident, target_repo),
        }


def list_incidents(repo: Path) -> list[dict[str, Any]]:
    inc_dir = _incidents_dir(repo)
    index_path = inc_dir / "index.json"
    if not index_path.is_file():
        return []
    try:
        data = read_json(index_path)
        return list(data.get("incidents") or [])
    except (OSError, ValueError):
        return []


def load_incident(repo: Path, incident_id: str | None = None) -> dict[str, Any] | None:
    inc_dir = _incidents_dir(repo)
    if incident_id:
        candidate = inc_dir / (incident_id if incident_id.endswith(".json") else f"{incident_id}.json")
        if candidate.is_file():
            try:
                incident = read_json(candidate)
                incident["issue_url"] = build_github_issue_url(incident)
                return incident
            except (OSError, ValueError):
                return None
    items = list_incidents(repo)
    if not items:
        return None
    latest_entry = items[-1]
    latest_path = inc_dir / str(latest_entry.get("path") or f"{latest_entry.get('incident_id')}.json")
    if latest_path.is_file():
        try:
            incident = read_json(latest_path)
            incident["issue_url"] = build_github_issue_url(incident)
            return incident
        except (OSError, ValueError):
            return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or submit sanitized harness incident reports.")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--list", action="store_true", help="List recorded local incidents")
    parser.add_argument("--latest", action="store_true", help="Inspect or report the most recent incident")
    parser.add_argument("--incident-id", default=None, help="Specific incident ID to inspect or submit")
    parser.add_argument("--submit", action="store_true", help="Submit the selected incident to GitHub Issues via gh CLI")
    parser.add_argument("--always-auto-submit", action="store_true", help="Enable automatic anonymous incident submission for future errors in this project")
    parser.add_argument("--disable-auto-submit", action="store_true", help="Disable automatic incident submission and always ask first")
    parser.add_argument("--dry-run", action="store_true", help="Preview the GitHub Issue payload without network submission")
    parser.add_argument("--target-repo", default=UPSTREAM_REPO, help="Upstream GitHub repository for issue submission")
    parser.add_argument("--record-message", default=None, help="Manually record a new incident with this diagnostic message")
    parser.add_argument("--code", default="MANUAL_REPORT", help="Incident code when using --record-message")
    parser.add_argument("--command", default="report-issue", help="Command context when using --record-message")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()

    if args.always_auto_submit:
        set_auto_submit_preference(repo, True)
    elif args.disable_auto_submit:
        pref = set_auto_submit_preference(repo, False)
        if not args.submit and not args.record_message and not args.list:
            if args.json:
                print(json.dumps(pref, indent=2, ensure_ascii=False))
            else:
                print("AUTO_SUBMIT_INCIDENTS=false")
            return 0

    if args.record_message:
        inc = record_incident(
            repo,
            code=args.code,
            command=args.command,
            message=args.record_message,
            auto_submit=args.submit and not args.dry_run,
        )
        if args.submit or args.dry_run:
            inc["submission"] = submit_incident_to_github(
                repo, inc, target_repo=args.target_repo, dry_run=args.dry_run
            )
        if args.json:
            print(json.dumps(inc, indent=2, ensure_ascii=False))
        else:
            print(f"INCIDENT_RECORDED={inc['incident_id']}")
            print(f"FINGERPRINT={inc['fingerprint_sha256']}")
            print(f"ISSUE_URL={inc['issue_url']}")
            if "submission" in inc:
                print(f"SUBMISSION_STATUS={inc['submission'].get('status')}")
        return 0

    if args.list:
        items = list_incidents(repo)
        if args.json:
            print(json.dumps({"incidents": items}, indent=2, ensure_ascii=False))
        else:
            if not items:
                print("No local harness incidents recorded.")
            for item in items:
                print(
                    f"{item.get('incident_id')} | {item.get('code')} | {item.get('command')} "
                    f"| healed={item.get('healed')} | {item.get('created_at')}"
                )
        return 0

    incident = load_incident(repo, args.incident_id)
    if incident is None:
        msg = {"status": "NO_INCIDENTS", "message": "No local harness incidents found to report."}
        if args.json:
            print(json.dumps(msg, indent=2, ensure_ascii=False))
        else:
            print("[OK] No local harness incidents found.")
        return 0

    if args.submit or args.dry_run:
        submission = submit_incident_to_github(
            repo,
            incident,
            target_repo=args.target_repo,
            dry_run=args.dry_run,
        )
        incident["submission"] = submission

    if args.json:
        print(json.dumps(incident, indent=2, ensure_ascii=False))
    else:
        print(f"INCIDENT_ID={incident.get('incident_id')}")
        print(f"CODE={incident.get('code')}")
        print(f"FINGERPRINT={incident.get('fingerprint_sha256')}")
        print(f"ISSUE_URL={incident.get('issue_url')}")
        if "submission" in incident:
            sub = incident["submission"]
            print(f"SUBMISSION_STATUS={sub.get('status')}")
            if sub.get("issue_url"):
                print(f"SUBMITTED_ISSUE_URL={sub.get('issue_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
