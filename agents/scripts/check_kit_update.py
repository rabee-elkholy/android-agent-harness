"""Lightweight, non-blocking check for newer Android Agent Harness releases on GitHub.

Supports 24h caching, release notes fetching, "Remind me tomorrow" snoozing, and a
once-a-day notice that the turn-start reminder shows to the agent. Set
HARNESS_UPDATE_CHECK=off to disable every network check (selftests do).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GITHUB_REPO = "rabee-elkholy/android-agent-harness"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
CACHE_TTL_SECONDS = 6 * 3600  # a release shows up within hours; one unauthenticated API call per 6 h per project
RETRY_AFTER_FAILURE_SECONDS = 3600  # an offline or rate-limited check retries after an hour
NOTICE_INTERVAL_SECONDS = 86400  # the agent is told about a given release at most once a day
NETWORK_TIMEOUT_SECONDS = 2.5
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def get_current_version() -> str:
    v_file = Path(__file__).resolve().parent.parent / "VERSION"
    if v_file.is_file():
        return v_file.read_text(encoding="utf-8").strip()
    return "0.1.0"


def get_cache_file() -> Path:
    state_dir = Path(__file__).resolve().parent.parent / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "update_cache.json"


def checks_disabled() -> bool:
    return os.environ.get("HARNESS_UPDATE_CHECK", "").strip().lower() in {"0", "off", "false", "no"}


def parse_semver(v: str) -> tuple[int, ...]:
    v = v.lstrip("v").strip()
    parts = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _read_cache() -> dict:
    cache_path = get_cache_file()
    if cache_path.is_file():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _write_cache(data: dict) -> None:
    try:
        get_cache_file().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def snooze(days: float = 1.0) -> None:
    data = _read_cache()
    data["snoozed_until"] = time.time() + (days * 86400)
    _write_cache(data)


def is_snoozed() -> bool:
    try:
        return time.time() < float(_read_cache().get("snoozed_until", 0) or 0)
    except (TypeError, ValueError):
        return False


def _fetch_latest(current_ver: str) -> dict | None:
    """Latest published release as {version, html_url, notes}, or None on any failure."""
    req = urllib.request.Request(API_URL, headers={"User-Agent": f"AndroidHarnessKit/{current_ver}"})
    try:
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    tag = str(data.get("tag_name") or "").strip().lstrip("v")
    if not VERSION_RE.fullmatch(tag):
        return None
    html_url = str(data.get("html_url") or "")
    if not html_url.startswith(f"https://github.com/{GITHUB_REPO}/"):
        html_url = f"https://github.com/{GITHUB_REPO}/releases/tag/v{tag}"
    return {"version": tag, "html_url": html_url, "notes": str(data.get("body") or "")}


def _result(current_ver: str, cache: dict, snoozed: bool) -> dict:
    latest_ver = str(cache.get("latest_version") or current_ver)
    if not VERSION_RE.fullmatch(latest_ver):
        latest_ver = current_ver
    has_up = parse_semver(latest_ver) > parse_semver(current_ver)
    return {
        "has_update": has_up and not snoozed,
        "raw_has_update": has_up,
        "current": current_ver,
        "latest": latest_ver,
        "notes": str(cache.get("notes") or ""),
        "html_url": str(cache.get("html_url") or ""),
        "snoozed": snoozed,
    }


def check_for_update(force: bool = False) -> dict:
    """Returns dict: {has_update, raw_has_update, current, latest, notes, html_url, snoozed}."""
    current_ver = get_current_version()
    cache = _read_cache()
    snoozed = is_snoozed()
    now = time.time()
    if checks_disabled():
        return _result(current_ver, cache, snoozed)
    try:
        fresh = now < float(cache.get("next_check_at", 0) or 0)
    except (TypeError, ValueError):
        fresh = False
    if force or not fresh:
        latest = _fetch_latest(current_ver)
        if latest is not None:
            cache.update(
                latest_version=latest["version"],
                html_url=latest["html_url"],
                notes=latest["notes"],
                timestamp=now,
                next_check_at=now + CACHE_TTL_SECONDS,
            )
        else:
            # Keep the last known release and the snooze; only postpone the next attempt.
            cache["next_check_at"] = now + RETRY_AFTER_FAILURE_SECONDS
        _write_cache(cache)
    return _result(current_ver, cache, snoozed)


def install_prompt_url(version: str) -> str:
    tag = str(version or "").strip().lstrip("v") or "main"
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/v{tag}/docs/install-or-update-prompt.md"


def pending_update_note(repo: Path) -> str:
    """Non-empty when an update was interrupted and never recorded (O59)."""
    journal_path = Path(repo) / ".harness-setup" / "update-journal.json"
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if str(journal.get("status") or "") == "COMPLETED" or str(journal.get("stage") or "") == "COMPLETED":
        return ""
    target = str(journal.get("to_version") or "?")
    if str(journal.get("status") or "") == "ROLLED_BACK":
        return f"The update to v{target} was rolled back; the installed engine is the previous one. Run the update again."
    return f"An update to v{target} was interrupted before it was recorded; run the update again (it recovers first)."


def update_instructions(repo: Path, *, force: bool = True) -> str:
    """How to update this installation, for `harness.py update-info` (O56)."""
    res = check_for_update(force=force)
    lines = [f"Installed harness: v{res['current']}. Latest release: v{res['latest']}."]
    pending = pending_update_note(repo)
    if pending:
        lines.append(f"[WARN] {pending}")
    if res["raw_has_update"] or pending:
        target = res["latest"] if res["raw_has_update"] else res["current"]
        lines += [
            "How to update (the developer's decision; finish or cancel an active task first):",
            f"  1. In a NEW chat at the project root, send: Read {install_prompt_url(target)} and follow all instructions.",
            "  2. Or in the developer's own terminal: python <kit-dir>/harness_cli.py update --repo <app-root> --kit <kit-dir>",
            "Never update the harness any other way (no package manager, no copying files).",
        ]
    else:
        lines.append("Up to date. Nothing to do.")
    return "\n".join(lines)


def update_banner() -> str:
    res = check_for_update(force=False)
    if res["has_update"]:
        return (
            f"[HARNESS UPDATE AVAILABLE] v{res['latest']} is out (installed: v{res['current']})!\n"
            f"   To upgrade your project harness, paste {install_prompt_url(res['latest'])} in a new chat."
        )
    return ""


def update_notice() -> str:
    """One-line notice for the agent at the start of a conversation, at most once a day per release.

    Never raises; empty when there is no newer release, it is snoozed, checks are disabled, or the
    developer was already told about this release in the last day.
    """
    try:
        res = check_for_update(force=False)
        if not res["has_update"]:
            return ""
        cache = _read_cache()
        now = time.time()
        told = str(cache.get("notified_version") or "")
        told_at = float(cache.get("notified_at", 0) or 0)
        if told == res["latest"] and now - told_at < NOTICE_INTERVAL_SECONDS:
            return ""
        cache["notified_version"] = res["latest"]
        cache["notified_at"] = now
        _write_cache(cache)
        return (
            f"Harness update available: v{res['latest']} (installed v{res['current']}). Tell the developer once, "
            f"and offer the update prompt {install_prompt_url(res['latest'])} for a new chat; never update without "
            "the developer's request, and finish or cancel an active task first. To pause this notice: "
            "`python .agents/scripts/check_kit_update.py --snooze 7`."
        )
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for Android Agent Harness updates.")
    parser.add_argument("--snooze", type=float, metavar="DAYS", help="Snooze update reminders for N days (e.g. 1.0).")
    parser.add_argument("--show-changes", action="store_true", help="Print latest release notes / changelog.")
    parser.add_argument("--force", action="store_true", help="Force network check ignoring cache TTL.")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format.")
    args = parser.parse_args()

    if args.snooze is not None:
        snooze(args.snooze)
        print(f"[OK] Update reminders snoozed for {args.snooze} day(s).")
        return 0

    res = check_for_update(force=args.force)

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.show_changes:
        print(f"=== Release Notes for Android Agent Harness v{res['latest']} ===")
        print(res["notes"] or "(No release notes provided)")
        print(f"\nRelease URL: {res['html_url']}")
        return 0

    print(f"Android Agent Harness installed version: v{res['current']}")
    if res["raw_has_update"]:
        if res["snoozed"]:
            print(f"[INFO] Newer version v{res['latest']} is available, but currently snoozed.")
        else:
            print(f"\n[!] A new version is available: v{res['latest']}")
            print(f"    Release details: {res['html_url']}")
            print(f"    To upgrade, paste {install_prompt_url(res['latest'])} in a new chat.")
    else:
        print("[OK] You are running the latest version.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
