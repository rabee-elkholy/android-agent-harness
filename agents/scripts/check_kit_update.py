"""Lightweight, non-blocking check for newer Android Harness Kit releases on GitHub.

Caches check results in .agents/state/update_cache.json for 24 hours to avoid network calls.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

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


def check_for_update(force: bool = False) -> tuple[bool, str, str]:
    """Returns (has_update, latest_version, html_url)."""
    current_ver = get_current_version()
    cache_path = get_cache_file()
    now = time.time()

    if not force and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if now - cached.get("timestamp", 0) < CACHE_TTL_SECONDS:
                latest_ver = cached.get("latest_version", current_ver)
                html_url = cached.get("html_url", "")
                has_up = parse_semver(latest_ver) > parse_semver(current_ver)
                return has_up, latest_ver, html_url
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
                cache_path.write_text(
                    json.dumps(
                        {
                            "timestamp": now,
                            "latest_version": latest_tag,
                            "html_url": html_url,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                has_up = parse_semver(latest_tag) > parse_semver(current_ver)
                return has_up, latest_tag, html_url
    except Exception:
        pass

    return False, current_ver, ""


def update_banner() -> str:
    has_up, latest, url = check_for_update(force=False)
    if has_up:
        curr = get_current_version()
        return (
            f"💡 [HARNESS UPDATE AVAILABLE] v{latest} is out (current: v{curr})!\n"
            f"   To upgrade your project harness, paste docs/update-prompt.md in a new chat."
        )
    return ""


def main() -> int:
    current = get_current_version()
    print(f"Android Harness Kit installed version: v{current}")
    has_up, latest, url = check_for_update(force=True)
    if has_up:
        print(f"\n[!] A new version is available: v{latest}")
        print(f"    Release details: {url}")
        print("    To upgrade, paste docs/update-prompt.md in a new chat.")
        return 0
    print("[OK] You are running the latest version.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
