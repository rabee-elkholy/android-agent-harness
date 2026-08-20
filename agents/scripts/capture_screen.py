"""Physical device screen capture for this Android app.

Usage:
  python .agents/scripts/capture_screen.py
  python .agents/scripts/capture_screen.py -d <DEVICE_ID> --name <NAME>
"""
from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _repo_files import REPO, first_physical_adb_serial  # noqa: E402

enable_line_buffered_stdio()

SCREENSHOTS_DIR = REPO / ".agents" / "state" / "screenshots"


def capture_screenshot(device_id: str, name: str | None = None) -> Path | None:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{name}_{timestamp}.png" if name else f"device_{timestamp}.png"
    out_path = SCREENSHOTS_DIR / filename

    try:
        with open(out_path, "wb") as fp:
            proc = subprocess.run(
                ["adb", "-s", device_id, "exec-out", "screencap", "-p"],
                stdout=fp,
                stderr=subprocess.PIPE,
                check=False,
            )
        if proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 1000:
            return out_path
        if out_path.is_file():
            out_path.unlink()
        return None
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture screenshot from physical Android device")
    parser.add_argument("-d", "--device", default=None, help="Physical device serial (default: first non-emulator adb device)")
    parser.add_argument("-n", "--name", default="screen", help="Prefix name for screenshot")
    args = parser.parse_args()

    device_id = args.device or first_physical_adb_serial()
    if not device_id:
        print("[ERROR] No physical Android device detected via ADB.", file=sys.stderr)
        return 1
    if device_id.startswith("emulator-"):
        print("[ERROR] Emulator targeting is forbidden. Connect a physical device.", file=sys.stderr)
        return 1

    print(f"[*] Capturing screenshot from device: {device_id}...")
    saved_path = capture_screenshot(device_id, args.name)
    if saved_path:
        print("[SUCCESS] Screenshot saved successfully!")
        print(f"  -> Path: {saved_path}")
        print(f"  -> URI:  {saved_path.as_uri()}")
        return 0
    print("[ERROR] Failed to capture screenshot from device.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
