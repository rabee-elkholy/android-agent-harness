"""Physical-device install/launch with a live adb task log.

Usage:
  python .agents/scripts/run_device.py install
  python .agents/scripts/run_device.py start
  python .agents/scripts/run_device.py install-start
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print, run_streaming  # noqa: E402
from _repo_files import REPO, first_physical_adb_serial  # noqa: E402

DEFAULT_APK = REPO / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
DEFAULT_ACTIVITY = "com.madarsoft.fitness/.features.splash.SplashActivity"


def require_serial(explicit: str | None) -> str:
    serial = explicit or first_physical_adb_serial()
    if not serial:
        live_print("[ERROR] No physical Android device detected via ADB.", err=True)
        sys.exit(1)
    if serial.startswith("emulator-"):
        live_print("[ERROR] Emulator targeting is forbidden. Connect a physical device.", err=True)
        sys.exit(1)
    return serial


def run_adb(serial: str, adb_args: list[str], label: str) -> int:
    live_print(f"[*] adb -s {serial} {' '.join(adb_args)}")
    code, _, _ = run_streaming(
        ["adb", "-s", serial, *adb_args],
        cwd=str(REPO),
        heartbeat_sec=10.0,
        should_echo=lambda line: bool(line.strip()),
        label=label,
    )
    return code


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Live adb install/start for Rashaqa")
    parser.add_argument("action", choices=["install", "start", "install-start"])
    parser.add_argument("-s", "--serial", default=None, help="Physical device serial")
    parser.add_argument("--apk", default=str(DEFAULT_APK), help="Debug APK path")
    parser.add_argument("--activity", default=DEFAULT_ACTIVITY, help="Launch activity")
    args = parser.parse_args()

    serial = require_serial(args.serial)
    live_print(f"[*] Physical device: {serial}")

    if args.action in ("install", "install-start"):
        apk = Path(args.apk)
        if not apk.is_file():
            live_print(f"[ERROR] APK not found: {apk}", err=True)
            live_print("Assemble debug first: python .agents/scripts/run_gradle_task.py :app:assembleDebug", err=True)
            return 1
        size_mb = apk.stat().st_size / (1024 * 1024)
        live_print(f"[*] Installing {apk.as_posix()} ({size_mb:.1f} MB)")
        code = run_adb(serial, ["install", "-r", "-d", str(apk)], "adb install")
        if code != 0:
            live_print(f"[!] adb install failed (exit {code})", err=True)
            return code
        live_print("[+] Install finished")

    if args.action in ("start", "install-start"):
        code = run_adb(
            serial,
            ["shell", "am", "start", "-n", args.activity],
            "am start",
        )
        if code != 0:
            live_print(f"[!] am start failed (exit {code})", err=True)
            return code
        live_print(f"[+] Launched {args.activity}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
