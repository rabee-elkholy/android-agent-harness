"""Physical-device install/launch with a live adb task log.

Usage:
  python .agents/scripts/run_device.py install
  python .agents/scripts/run_device.py start
  python .agents/scripts/run_device.py install-start
  python .agents/scripts/run_device.py uninstall
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio, live_print, run_streaming  # noqa: E402
from _product import (  # noqa: E402
    ALLOW_EMULATOR,
    APPLICATION_ID,
    ASSEMBLE_TASK,
    LAUNCHER,
    PRODUCT_NAME,
)
from _repo_files import REPO, first_adb_serial  # noqa: E402
from _variants import apk_relative, resolve_or_raise  # noqa: E402

DEFAULT_ACTIVITY = LAUNCHER


def require_serial(explicit: str | None) -> str:
    allow_emu = bool(ALLOW_EMULATOR)
    serial = explicit or first_adb_serial(allow_emulator=allow_emu)
    if not serial:
        live_print("[ERROR] No Android device detected via ADB.", err=True)
        sys.exit(1)
    if not allow_emu and serial.startswith("emulator-"):
        live_print("[ERROR] Emulator targeting is forbidden by project policy. Connect a physical device.", err=True)
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
    parser = argparse.ArgumentParser(description=f"Live adb install/start for {PRODUCT_NAME}")
    parser.add_argument("action", choices=["install", "start", "install-start", "uninstall"])
    parser.add_argument("-s", "--serial", default=None, help="Physical device serial")
    parser.add_argument(
        "--flavor",
        default=None,
        help="Build flavor for APK resolution (default: ACTIVE_FLAVOR in _product.py).",
    )
    parser.add_argument("--apk", default=None, help="Debug APK path (overrides --flavor resolution)")
    parser.add_argument("--activity", default=DEFAULT_ACTIVITY, help="Launch activity")
    parser.add_argument("--package", default=APPLICATION_ID, help="Package name to uninstall")
    args = parser.parse_args()

    try:
        active_flavor, _task = resolve_or_raise(args.flavor)
    except SystemExit as exc:
        live_print(str(exc), err=True)
        return 1

    apk = Path(args.apk) if args.apk else REPO / apk_relative()
    variant_note = f" (variant: {active_flavor})" if active_flavor else ""
    serial = require_serial(args.serial)
    live_print(f"[*] Physical device{variant_note}: {serial}")

    if args.action == "uninstall":
        live_print(f"[*] Uninstalling {args.package} from {serial}")
        code = run_adb(serial, ["uninstall", args.package], "adb uninstall")
        if code != 0:
            live_print(f"[!] adb uninstall failed (exit {code})", err=True)
            return code
        live_print(f"[+] Uninstall finished for {args.package}")
        return 0

    if args.action in ("install", "install-start"):
        apk = Path(args.apk)
        if not apk.is_file():
            live_print(f"[ERROR] APK not found: {apk}", err=True)
            live_print(f"Assemble debug first: python .agents/scripts/run_gradle_task.py {ASSEMBLE_TASK}", err=True)
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
