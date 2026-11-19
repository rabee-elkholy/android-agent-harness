"""Extract crash logs, ANRs, and sensor events from a connected physical device.

Usage:
  python .agents/scripts/logcat_doctor.py
  python .agents/scripts/logcat_doctor.py --device <SERIAL> --lines 1000
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
try:
    from _product import DEVICE_TARGET_POLICY  # type: ignore[attr-defined]  # noqa: E402
except ImportError:
    DEVICE_TARGET_POLICY = "allow" if ALLOW_EMULATOR else "physical-only"
from _repo_files import adb_serial_is_emulator, first_adb_serial  # noqa: E402

enable_line_buffered_stdio()

_THREADTIME_OR_EPOCH_RE = re.compile(
    r"^\s*(?:(?:\d{4}-)?\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+|\d+\.\d+)\s+(\d+)\s+\d+\s+[VDIWEFA]\s+([^:]+?):\s?(.*)$"
)
_BRIEF_RE = re.compile(r"^\s*[VDIWEFA]/([^(:]+)\(\s*(\d+)\):\s?(.*)$")
_STACK_CONT_RE = re.compile(
    r"^(?:\s*at\s+[A-Za-z0-9_$.]+|\s*Caused by:|\s*Suppressed:|\s*\.\.\.\s+\d+\s+more\b|"
    r"Process:\s*|PID:\s*|[A-Za-z0-9_$.]+(?:Exception|Error|Throwable)\b|"
    r"\s*#\d+\s+pc\b|\s*(?:Build fingerprint|Revision|ABI|Timestamp|pid:|tid:|uid:|signal |Abort message:|backtrace:))"
)
_MAX_FATAL_LINES = 80


def _parse_logcat_line(line: str) -> tuple[str, str, str]:
    """Return `(pid, tag, message_payload)` across threadtime, epoch, brief, or raw log lines."""
    m_tt = _THREADTIME_OR_EPOCH_RE.match(line)
    if m_tt:
        return m_tt.group(1), m_tt.group(2).strip(), m_tt.group(3)
    m_br = _BRIEF_RE.match(line)
    if m_br:
        return m_br.group(2), m_br.group(1).strip(), m_br.group(3)
    return "", "", line


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
    except (OSError, subprocess.SubprocessError) as e:
        return f"Failed to fetch logcat: {e}"


def filter_forensics(raw_logs: str, *, app_id: str | None = None, pkg_prefix: str | None = None) -> dict:
    eff_app_id = str(APPLICATION_ID if app_id is None else app_id).strip()
    eff_pkg_prefix = str(PACKAGE_PREFIX if pkg_prefix is None else pkg_prefix).strip()
    enforce_pkg_owner = bool(eff_app_id and eff_app_id != "com.example.app")

    new_block_starters = [
        re.compile(r"FATAL EXCEPTION", re.IGNORECASE),
        re.compile(r"AndroidRuntime:\s*FATAL", re.IGNORECASE),
        re.compile(r"CoroutineExceptionHandler", re.IGNORECASE),
        re.compile(rf"ANR in {re.escape(eff_app_id)}", re.IGNORECASE) if eff_app_id else re.compile(r"(?!)"),
        re.compile(r"Fatal signal\s+\d+", re.IGNORECASE),
        re.compile(r"DEBUG\s*:\s*\*\*\*", re.IGNORECASE),
    ]
    proc_line_re = re.compile(r"\bProcess:\s*([^,\s]+)")
    tombstone_pkg_re = re.compile(r">>>\s*([^\s<]+)\s*<<<")

    warning_patterns = [
        re.compile(r"Choreographer.*Skipped \d+ frames", re.IGNORECASE),
        re.compile(r"OutOfMemoryError", re.IGNORECASE),
        re.compile(r"SQLiteException", re.IGNORECASE),
        re.compile(r"NetworkOnMainThreadException", re.IGNORECASE),
        re.compile(r"StrictMode", re.IGNORECASE),
    ]

    fatal_blocks: list[str] = []
    warning_logs: list[str] = []
    app_logs: list[str] = []

    in_fatal = False
    fatal_pid = ""
    fatal_tag = ""
    fatal_foreign_pkg = False
    current_fatal: list[str] = []

    def _flush_fatal() -> None:
        nonlocal in_fatal, fatal_pid, fatal_tag, fatal_foreign_pkg, current_fatal
        if current_fatal and not fatal_foreign_pkg:
            fatal_blocks.append("\n".join(current_fatal))
        in_fatal = False
        fatal_pid = ""
        fatal_tag = ""
        fatal_foreign_pkg = False
        current_fatal = []

    for line in raw_logs.splitlines():
        pid, tag, payload = _parse_logcat_line(line)
        is_starter = any(rx.search(line) for rx in new_block_starters)
        is_own_proc_line = bool(eff_app_id and re.search(rf"Process:\s*{re.escape(eff_app_id)}\b", line))

        if is_starter:
            # Keep `DEBUG : ***` attached right after `Fatal signal` if no frames were collected yet
            is_tombstone_after_signal = (
                in_fatal
                and len(current_fatal) <= 2
                and "Fatal signal" in current_fatal[0]
                and ("DEBUG" in tag or "DEBUG" in line)
            )
            if in_fatal and not is_tombstone_after_signal:
                _flush_fatal()
            in_fatal = True
            if pid and not fatal_pid:
                fatal_pid = pid
            if tag:
                fatal_tag = tag
            current_fatal.append(line)
        elif in_fatal:
            same_crash_stream = bool(
                tag
                and tag in {"AndroidRuntime", "DEBUG", "System.err", "ActivityManager"}
                and (not fatal_pid or not pid or pid == fatal_pid or tag == "DEBUG")
                and (not fatal_tag or tag == fatal_tag or (fatal_tag == "libc" and tag == "DEBUG"))
            )
            is_cont = (
                same_crash_stream
                or bool(_STACK_CONT_RE.search(payload))
                or (bool(eff_pkg_prefix) and bool(re.search(rf"\bat\s+{re.escape(eff_pkg_prefix)}\.", payload)))
                or (not tag and line.startswith((" ", "\t")))
            )
            if is_cont and len(current_fatal) < _MAX_FATAL_LINES:
                current_fatal.append(line)
                m_proc = proc_line_re.search(payload)
                if m_proc and enforce_pkg_owner:
                    crash_pkg = m_proc.group(1).split(":", 1)[0]
                    if crash_pkg != eff_app_id:
                        fatal_foreign_pkg = True
                m_tomb = tombstone_pkg_re.search(payload)
                if m_tomb and enforce_pkg_owner:
                    tomb_pkg = m_tomb.group(1).split(":", 1)[0]
                    if tomb_pkg != eff_app_id:
                        fatal_foreign_pkg = True
            else:
                _flush_fatal()
                if is_own_proc_line:
                    in_fatal = True
                    fatal_pid = pid
                    fatal_tag = tag
                    current_fatal.append(line)
        elif is_own_proc_line:
            in_fatal = True
            fatal_pid = pid
            fatal_tag = tag
            current_fatal.append(line)

        if any(rx.search(line) for rx in warning_patterns):
            warning_logs.append(line)

        if eff_app_id and eff_app_id in line:
            app_logs.append(line)

    if current_fatal:
        _flush_fatal()

    return {
        "fatals": fatal_blocks,
        "warning_logs": warning_logs[-20:],
        "app_logs": app_logs[-50:],
        "app_logs_count": len(app_logs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Logcat Doctor & Crash Triage for this Android app")
    parser.add_argument("-d", "--device", default=None, help="Physical device serial (default: first non-emulator adb device)")
    parser.add_argument("--lines", type=int, default=1000, help="Number of logcat lines to fetch")
    parser.add_argument("-e", "--grep", default=None, help="Case-insensitive regex pattern to filter recent logcat lines")
    parser.add_argument("-t", "--tag", default=None, help="Filter recent logcat lines by tag substring")
    args = parser.parse_args()

    policy = str(DEVICE_TARGET_POLICY)
    serial = args.device or first_adb_serial(policy=policy)
    if not serial:
        print("[!] No Android device connected via ADB.")
        return 1
    is_emulator = adb_serial_is_emulator(serial)
    if policy == "physical-only" and is_emulator:
        print("[!] Emulator targeting is forbidden by project policy. Connect a physical device.")
        return 1
    if policy == "emulator-only" and not is_emulator:
        print("[!] Physical-device targeting is forbidden by project policy. Start an emulator.")
        return 1

    print(f"[*] Connected Device: {serial}")
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

    if forensics["warning_logs"]:
        print(f"\n[*] Recent ANR & StrictMode Diagnostics ({len(forensics['warning_logs'])}):")
        for item in forensics["warning_logs"]:
            print(f"   {item}")

    print(f"\n[*] Total {PRODUCT_NAME} app log entries: {forensics['app_logs_count']}")
    if args.grep or args.tag:
        matched = raw.splitlines()
        if args.tag:
            matched = [line for line in matched if args.tag.lower() in line.lower()]
        if args.grep:
            pattern = re.compile(args.grep, re.IGNORECASE)
            matched = [line for line in matched if pattern.search(line)]
        print(f"\n[*] Filtered Logcat Matches ({len(matched)} total, showing last {min(len(matched), 100)}):")
        for line in matched[-100:]:
            print(f"   {line}")
    elif forensics.get("app_logs"):
        print(f"\n[*] Recent {PRODUCT_NAME} App Logs (last {len(forensics['app_logs'])}):")
        for line in forensics["app_logs"]:
            print(f"   {line}")
    print("==================================================")
    return 0 if not forensics["fatals"] else 2


if __name__ == "__main__":
    sys.exit(main())
