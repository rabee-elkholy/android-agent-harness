"""Lightweight, non-blocking check for newer Android Harness Kit releases on GitHub.

Supports 24h caching, release notes fetching, and "Remind me tomorrow" snoozing.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GITHUB_REPO = "rabee-elkholy/android-harness-kit"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
CACHE_TTL_SECONDS = 86400  # 24 hours


def get_current_version() -> str:
    v_file = Path(__file__).resolve().parent.parent / "VERSION"
    if v_file.is_file():
        return v_file.read_text(encoding="utf-8").strip()
    return "0.1.0"


def get_cache_file() -> Path:
    state_dir = Path(__file__).resolve().parent.parent / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "update_cache.json"


def parse_semver(v: str) -> tuple[int, ...]:
    v = v.lstrip("v").strip()
    parts = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def snooze(days: float = 1.0) -> None:
    cache_path = get_cache_file()
    now = time.time()
    snooze_until = now + (days * 86400)
    data = {}
    if cache_path.is_file():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["snoozed_until"] = snooze_until
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_snoozed() -> bool:
    cache_path = get_cache_file()
    if cache_path.is_file():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return time.time() < data.get("snoozed_until", 0)
        except Exception:
            pass
    return False


def check_for_update(force: bool = False) -> dict:
    """Returns dict: {has_update, current, latest, notes, html_url, snoozed}."""
    current_ver = get_current_version()
    cache_path = get_cache_file()
    now = time.time()
    snoozed = is_snoozed()

    if not force and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if now - cached.get("timestamp", 0) < CACHE_TTL_SECONDS:
                latest_ver = cached.get("latest_version", current_ver)
                html_url = cached.get("html_url", "")
                notes = cached.get("notes", "")
                has_up = parse_semver(latest_ver) > parse_semver(current_ver)
                return {
                    "has_update": has_up and not snoozed,
                    "raw_has_update": has_up,
                    "current": current_ver,
                    "latest": latest_ver,
                    "notes": notes,
                    "html_url": html_url,
                    "snoozed": snoozed,
                }
        except Exception:
            pass

    req = urllib.request.Request(
        API_URL,
        headers={"User-Agent": f"AndroidHarnessKit/{current_ver}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                latest_tag = data.get("tag_name", "").lstrip("v")
                html_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}")
                notes = data.get("body", "")
                
                # Keep existing snooze timestamp if present
                existing_snooze = 0
                if cache_path.is_file():
                    try:
                        existing_snooze = json.loads(cache_path.read_text(encoding="utf-8")).get("snoozed_until", 0)
                    except Exception:
                        pass

                cache_path.write_text(
                    json.dumps(
                        {
                            "timestamp": now,
                            "latest_version": latest_tag,
                            "html_url": html_url,
                            "notes": notes,
                            "snoozed_until": existing_snooze,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                has_up = parse_semver(latest_tag) > parse_semver(current_ver)
                return {
                    "has_update": has_up and not snoozed,
                    "raw_has_update": has_up,
                    "current": current_ver,
                    "latest": latest_tag,
                    "notes": notes,
                    "html_url": html_url,
                    "snoozed": snoozed,
                }
    except Exception:
        pass

    return {
        "has_update": False,
        "raw_has_update": False,
        "current": current_ver,
        "latest": current_ver,
        "notes": "",
        "html_url": "",
        "snoozed": snoozed,
    }


def update_banner() -> str:
    res = check_for_update(force=False)
    if res["has_update"]:
        return (
            f"[HARNESS UPDATE AVAILABLE] v{res['latest']} is out (installed: v{res['current']})!\n"
            f"   To upgrade your project harness, paste docs/update-prompt.md in a new chat."
        )
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for Android Harness Kit updates.")
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
        print(f"=== Release Notes for Android Harness Kit v{res['latest']} ===")
        print(res["notes"] or "(No release notes provided)")
        print(f"\nRelease URL: {res['html_url']}")
        return 0

    print(f"Android Harness Kit installed version: v{res['current']}")
    if res["raw_has_update"]:
        if res["snoozed"]:
            print(f"[INFO] Newer version v{res['latest']} is available, but currently snoozed.")
        else:
            print(f"\n[!] A new version is available: v{res['latest']}")
            print(f"    Release details: {res['html_url']}")
            print("    To upgrade, paste docs/update-prompt.md in a new chat.")
    else:
        print("[OK] You are running the latest version.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
