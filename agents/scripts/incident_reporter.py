"""Automated Zero-PII Incident Reporter for Android Agent Harness.

Captures unexpected harness exceptions, routing contradictions, repeated step
failures, and automatic self-healing transitions into sanitized local incident
bundles under `.agents/state/incidents/` and optionally submits deduplicated
GitHub Issues to `rabee-elkholy/android-agent-harness` via `gh` CLI (or emits a
pre-filled GitHub Issue URL when `gh` is unavailable).

Standard library Python only. Never includes project source code, user secrets,
or unredacted absolute filesystem paths.
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


def build_github_issue_url(incident: dict[str, Any], target_repo: str = UPSTREAM_REPO) -> str:
    """Construct a pre-filled GitHub Issue URL for one-click developer or agent reporting."""
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
    fp = str(incident.get("fingerprint_sha256") or "")
    lines = [
        "### Automated Harness Incident Report",
        "",
        f"- **Fingerprint**: `fingerprint:{fp}`",
        f"- **Incident ID**: `{incident.get('incident_id', '')}`",
        f"- **Harness Version**: `{incident.get('harness_version', 'unknown')}`",
        f"- **Host / OS / Python**: `{incident.get('host', 'unknown')}` / `{incident.get('os', 'unknown')}` / `{incident.get('python_version', 'unknown')}`",
        f"- **Code**: `{incident.get('code', 'UNKNOWN')}`",
        f"- **Command**: `{incident.get('command', '')}`",
        f"- **Task State**: `{incident.get('task_state', 'NONE')}`",
        f"- **Auto-Healed**: `{incident.get('healed', False)}` ({incident.get('heal_action', 'none')})",
        f"- **Recorded At (UTC)**: `{incident.get('created_at', '')}`",
        "",
        "#### Diagnostic Summary",
        "```text",
        str(incident.get("message") or "").strip()[:1500],
        "```",
    ]
    frames = incident.get("engine_frames") or []
    if frames:
        lines.extend([
            "",
            "#### Sanitized Engine Frames",
            "```text",
            "\n".join(str(f) for f in frames[:15]),
            "```",
        ])
    extra = incident.get("extra")
    if isinstance(extra, dict) and extra:
        lines.extend([
            "",
            "#### Additional Context",
            "```json",
            json.dumps(extra, indent=2, ensure_ascii=False)[:1500],
            "```",
        ])
    return "\n".join(lines) + "\n"


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
    auto_submit: bool = True,
) -> dict[str, Any]:
    """Record a sanitized local incident report and optionally submit to GitHub Issues."""
    repo = Path(repo).resolve()
    inc_dir = _incidents_dir(repo)
    effective_msg = message or error_message or title
    effective_state = task_state or task_status
    clean_msg = _sanitize_text(effective_msg, repo)
    clean_cmd = _sanitize_text(command, repo)
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
            if isinstance(v, (str, int, float, bool)) or v is None:
                clean_extra[str(k)] = _sanitize_text(str(v), repo) if isinstance(v, str) else v
            elif isinstance(v, (list, dict)):
                clean_extra[str(k)] = json.loads(_sanitize_text(json.dumps(v, ensure_ascii=False), repo))
    if title:
        clean_extra.setdefault("title", _sanitize_text(title, repo))
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

    incident_path = inc_dir / f"{incident_id}.json"
    atomic_write_json(incident_path, incident)

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
    })
    if len(items) > MAX_STORED_INCIDENTS:
        for stale in items[:-MAX_STORED_INCIDENTS]:
            stale_file = inc_dir / str(stale.get("path") or "")
            try:
                stale_file.unlink(missing_ok=True)
            except OSError:
                pass
        items = items[-MAX_STORED_INCIDENTS:]
    atomic_write_json(index_path, {"schema_version": 1, "updated_at": utc_now(), "incidents": items})

    if auto_submit and not _is_test_or_ci_environment():
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
                return read_json(candidate)
            except (OSError, ValueError):
                return None
    items = list_incidents(repo)
    if not items:
        return None
    latest_entry = items[-1]
    latest_path = inc_dir / str(latest_entry.get("path") or f"{latest_entry.get('incident_id')}.json")
    if latest_path.is_file():
        try:
            return read_json(latest_path)
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
    parser.add_argument("--dry-run", action="store_true", help="Preview the GitHub Issue payload without network submission")
    parser.add_argument("--target-repo", default=UPSTREAM_REPO, help="Upstream GitHub repository for issue submission")
    parser.add_argument("--record-message", default=None, help="Manually record a new incident with this diagnostic message")
    parser.add_argument("--code", default="MANUAL_REPORT", help="Incident code when using --record-message")
    parser.add_argument("--command", default="report-issue", help="Command context when using --record-message")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()

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
