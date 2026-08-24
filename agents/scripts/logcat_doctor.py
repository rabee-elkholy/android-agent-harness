"""Extract crash logs, ANRs, and sensor events from a connected physical device.

Usage:
  python .agents/scripts/logcat_doctor.py
  python .agents/scripts/logcat_doctor.py --device <SERIAL> --lines 1000
  python .agents/scripts/logcat_doctor.py --clear
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _product import ALLOW_EMULATOR, APPLICATION_ID, PACKAGE_PREFIX, PRODUCT_NAME  # noqa: E402
from _repo_files import first_adb_serial, first_physical_adb_serial  # noqa: E402

enable_line_buffered_stdio()



def fetch_logcat(serial: str, num_lines: int = 1000) -> str:
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, "logcat", "-d", "-t", str(num_lines)],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.stdout or ""
    except Exception as e:
        return f"Failed to fetch logcat: {e}"


def filter_forensics(raw_logs: str) -> dict:
    crash_patterns = [
        r"FATAL EXCEPTION",
        rf"Process:\s*{re.escape(APPLICATION_ID)}",
        r"AndroidRuntime:\s*FATAL",
        r"CoroutineExceptionHandler",
        rf"ANR in {re.escape(APPLICATION_ID)}",
    ]
    sensor_patterns = [
        r"SensorManager",
        r"StepCounter",
        r"ActivityRecognition",
        r"Pedometer",
    ]

    fatal_blocks = []
    sensor_logs = []
    app_logs = []

    lines = raw_logs.splitlines()
    in_fatal = False
    current_fatal = []

    for line in lines:
        if any(re.search(p, line, re.IGNORECASE) for p in crash_patterns):
            in_fatal = True
            current_fatal.append(line)
        elif in_fatal:
            if re.search(rf"^\s*at\s+{re.escape(PACKAGE_PREFIX)}\.", line) or re.search(r"^\s*Caused by:", line) or re.search(r"^\s*at\s+android\.", line):
                current_fatal.append(line)
            elif current_fatal and len(current_fatal) < 30 and line.startswith(" "):
                current_fatal.append(line)
            else:
                fatal_blocks.append("\n".join(current_fatal))
                current_fatal = []
                in_fatal = False

        if any(re.search(p, line, re.IGNORECASE) for p in sensor_patterns):
            sensor_logs.append(line)

        if APPLICATION_ID in line:
            app_logs.append(line)

    if current_fatal:
        fatal_blocks.append("\n".join(current_fatal))

    return {
        "fatals": fatal_blocks,
        "sensor_logs": sensor_logs[-20:],
        "app_logs_count": len(app_logs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Logcat Doctor & Crash Triage for this Android app")
    parser.add_argument("-d", "--device", default=None, help="Physical device serial (default: first non-emulator adb device)")
    parser.add_argument("--lines", type=int, default=1000, help="Number of logcat lines to fetch")
    parser.add_argument("--clear", action="store_true", help="Clear logcat buffer on device")
    args = parser.parse_args()

    allow_emu = bool(ALLOW_EMULATOR)
    serial = args.device or first_adb_serial(allow_emulator=allow_emu)
    if not serial:
        print("[!] No Android device connected via ADB.")
        return 1
    if not allow_emu and serial.startswith("emulator-"):
        print("[!] Emulator targeting is forbidden by project policy. Connect a physical device.")
        return 1

    print(f"[*] Connected Device: {serial}")


    if args.clear:
        subprocess.run(["adb", "-s", serial, "logcat", "-c"], check=False)
        print("[OK] Logcat buffer cleared.")
        return 0

    print(f"[*] Fetching last {args.lines} lines from {serial}...")
    raw = fetch_logcat(serial, args.lines)
    forensics = filter_forensics(raw)

    print("\n==================================================")
    print(f"[Forensics] {PRODUCT_NAME} Crash & Forensic Triage Report")
    print("==================================================")

    if forensics["fatals"]:
        print(f"\n[FATAL] CRASHES DETECTED ({len(forensics['fatals'])}):")
        for i, crash in enumerate(forensics["fatals"], 1):
            print(f"\n--- Crash #{i} ---")
            print(crash)
    else:
        print("\n[OK] No Fatal Exceptions detected in recent logs.")

    if forensics["sensor_logs"]:
        print(f"\n[*] Recent Sensor & Pedometer Events ({len(forensics['sensor_logs'])}):")
        for item in forensics["sensor_logs"]:
            print(f"   {item}")

    print(f"\n[*] Total {PRODUCT_NAME} app log entries: {forensics['app_logs_count']}")
    print("==================================================")
    return 0 if not forensics["fatals"] else 2


if __name__ == "__main__":
    sys.exit(main())
