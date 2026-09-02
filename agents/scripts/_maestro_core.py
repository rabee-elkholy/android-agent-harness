"""Maestro Core engine for Android E2E QA.

Single source of truth for Maestro CLI detection, native flow validation,
scaffold generation, test execution, and failure forensics.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env_codes import CLASS_ENV, EXIT_ENV, FailureVerdict, emit_env_failure  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print, run_streaming  # noqa: E402
from _repo_files import REPO, first_adb_serial  # noqa: E402

MAESTRO_KNOWN_COMMANDS = {
    "launchApp", "stopApp", "clearState", "clearKeychain",
    "tapOn", "doubleTapOn", "longPressOn",
    "inputText", "eraseText", "inputRandomEmail", "inputRandomPersonName", "inputRandomNumber",
    "hideKeyboard", "dismissKeyguard",
    "scroll", "scrollUntilVisible", "swipe",
    "back", "pressKey",
    "assertVisible", "assertNotVisible", "assertTrue",
    "copyTextFrom", "pasteText", "openLink", "setLocation",
    "runFlow", "runScript", "repeat", "retry", "evalScript",
    "takeScreenshot", "extendedWaitUntil", "waitForAnimationToEnd",
}


def find_maestro_bin() -> str | None:
    """Resolve the absolute path or command for the Maestro executable."""
    found = shutil.which("maestro")
    if found:
        return found

    candidates: list[Path] = []
    user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", user_profile / "AppData" / "Local"))

    if sys.platform == "win32":
        candidates.extend([
            user_profile / ".maestro" / "bin" / "maestro.bat",
            user_profile / ".maestro" / "bin" / "maestro.exe",
            user_profile / ".maestro" / "bin" / "maestro",
            local_app_data / "Programs" / "maestro" / "bin" / "maestro.bat",
            local_app_data / "Programs" / "maestro" / "bin" / "maestro.exe",
        ])
    else:
        candidates.extend([
            Path.home() / ".maestro" / "bin" / "maestro",
            Path("/usr/local/bin/maestro"),
            Path("/opt/homebrew/bin/maestro"),
        ])

    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def get_maestro_install_instructions() -> str:
    if sys.platform == "win32":
        return (
            "Maestro is required for E2E testing on Android.\n"
            "To install Maestro on Windows (PowerShell):\n"
            "  powershell -c \"irm https://get.maestro.mobile.dev | iex\"\n"
            "Or via curl:\n"
            "  curl -fsSL \"https://get.maestro.mobile.dev\" | bash\n"
            "After installation, ensure ~/.maestro/bin is added to your PATH."
        )
    return (
        "Maestro is required for E2E testing on Android.\n"
        "To install Maestro on macOS / Linux:\n"
        "  curl -fsSL \"https://get.maestro.mobile.dev\" | bash\n"
        "Or on macOS via Homebrew:\n"
        "  brew tap mobile-dev-inc/tap && brew install maestro\n"
        "After installation, ensure ~/.maestro/bin is in your PATH."
    )


def _discover_java_bin() -> Path | None:
    java_home = os.environ.get("JAVA_HOME")
    if java_home and (Path(java_home) / "bin" / ("java.exe" if sys.platform == "win32" else "java")).is_file():
        return Path(java_home) / "bin"

    if sys.platform == "win32":
        candidates = [
            Path("C:/Program Files/Android/Android Studio/jbr/bin"),
            Path("C:/Program Files/Android/Android Studio/jre/bin"),
            Path("E:/Android/.gradle_windows/jdks/eclipse_adoptium-17-amd64-windows.2/bin"),
            Path("C:/Program Files/Eclipse Adoptium"),
            Path("C:/Program Files/Java"),
            Path("C:/Program Files/Amazon Corretto"),
            Path("C:/Program Files/Microsoft/jdk"),
        ]
        for c in candidates:
            if c.is_dir():
                if (c / "java.exe").is_file():
                    return c
                for sub in c.glob("*/bin"):
                    if (sub / "java.exe").is_file():
                        return sub
    return None


def install_maestro_cli() -> tuple[bool, str]:
    """Automates Maestro CLI installation cross-platform via direct release download."""
    import io
    import urllib.request
    import zipfile

    user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
    maestro_dir = user_profile / ".maestro"
    maestro_bin_dir = maestro_dir / "bin"
    maestro_url = "https://github.com/mobile-dev-inc/maestro/releases/latest/download/maestro.zip"

    try:
        req = urllib.request.Request(maestro_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()

        maestro_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for member in z.infolist():
                target_rel = member.filename
                if target_rel.startswith("maestro/"):
                    target_rel = target_rel[len("maestro/"):]
                if not target_rel:
                    continue
                target_path = maestro_dir / target_rel
                if member.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(z.read(member))
                    if sys.platform != "win32":
                        os.chmod(target_path, 0o755)

        if maestro_bin_dir.is_dir():
            os.environ["PATH"] = str(maestro_bin_dir) + os.pathsep + os.environ.get("PATH", "")

        ok, info, _ = ensure_maestro_installed()
        if ok:
            return True, f"Maestro installed successfully: {info}"
        return False, f"Maestro extracted to {maestro_dir} but execution check failed."
    except Exception as exc:
        return False, f"Failed to install Maestro: {exc}"


def ensure_maestro_installed() -> tuple[bool, str, str]:
    """Check if Maestro is available and return (is_ok, version_or_error, maestro_bin)."""
    bin_path = find_maestro_bin()
    if not bin_path:
        return False, "Maestro CLI binary not found in PATH or standard installation directories.", ""

    try:
        proc = subprocess.run(
            [bin_path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=15,
        )
        version_str = (proc.stdout or proc.stderr or "").strip()
        if proc.returncode == 0 or "maestro" in version_str.lower() or re.search(r"\d+\.\d+", version_str):
            return True, version_str or "Maestro (version detected)", bin_path
        return False, f"Maestro execution failed with return code {proc.returncode}: {version_str}", bin_path
    except Exception as exc:
        return False, f"Failed to execute Maestro: {exc}", bin_path


def validate_maestro_flow(flow_file: Path) -> tuple[bool, list[str]]:
    """Strictly validate a native Maestro YAML flow definition."""
    errors: list[str] = []
    if not flow_file.is_file():
        return False, [f"Flow file does not exist: {flow_file}"]

    try:
        content = flow_file.read_text(encoding="utf-8")
    except Exception as exc:
        return False, [f"Could not read {flow_file}: {exc}"]

    lines = content.splitlines()
    if not any(ln.strip().startswith("appId:") or ln.strip().startswith("app_id:") for ln in lines):
        errors.append(f"Missing required 'appId: <package>' header in {flow_file.name}")

    # Check command vocabulary
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("- "):
            cmd_part = stripped[2:].split(":")[0].strip()
            # If command has parameters or is an object
            if cmd_part and cmd_part not in MAESTRO_KNOWN_COMMANDS:
                # ignore comments or flow metadata
                if not cmd_part.startswith("#") and not cmd_part.startswith("-"):
                    errors.append(f"Line {idx}: Unknown Maestro action '{cmd_part}'. Known actions: {sorted(MAESTRO_KNOWN_COMMANDS)}")

    return (len(errors) == 0), errors


def generate_maestro_scaffold(task: str, output_dir: Path, app_id: str, diff_targets: list[str] | None = None) -> list[Path]:
    """Generate grounded multi-flow test cases scaffold for Maestro."""
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    targets_comment = ""
    if diff_targets:
        targets_comment = "# Blast radius targets: " + ", ".join(diff_targets) + "\n"

    # 1. Positive flow
    positive_file = output_dir / "TC01_positive_flow.yaml"
    positive_content = (
        f"# Test Case TC-01: Happy Path / Entry-to-Exit Positive Flow\n"
        f"{targets_comment}"
        f"appId: {app_id}\n"
        f"---\n"
        f"- launchApp:\n"
        f"    clearState: false\n"
        f"- assertVisible:\n"
        f"    text: \".*\"\n"
        f"# TODO (qa-e2e-planner-agent): add positive scenario assertions grounded in diff\n"
    )
    positive_file.write_text(positive_content, encoding="utf-8")
    created.append(positive_file)

    # 2. Negative flow
    negative_file = output_dir / "TC02_negative_flow.yaml"
    negative_content = (
        f"# Test Case TC-02: Negative Path / Error Handling Flow\n"
        f"{targets_comment}"
        f"appId: {app_id}\n"
        f"---\n"
        f"- launchApp\n"
        f"# TODO (qa-e2e-planner-agent): add invalid input / negative assertions\n"
    )
    negative_file.write_text(negative_content, encoding="utf-8")
    created.append(negative_file)

    # 3. Edge flow
    edge_file = output_dir / "TC03_edge_flow.yaml"
    edge_content = (
        f"# Test Case TC-03: Edge Condition / Navigation & Boundary Flow\n"
        f"{targets_comment}"
        f"appId: {app_id}\n"
        f"---\n"
        f"- launchApp\n"
        f"# TODO (qa-e2e-planner-agent): add rotation / back-press / boundary assertions\n"
    )
    edge_file.write_text(edge_content, encoding="utf-8")
    created.append(edge_file)

    return created


def parse_maestro_junit_xml(xml_path: Path) -> dict:
    """Parse JUnit XML report emitted by Maestro test run."""
    if not xml_path.is_file():
        return {
            "verdict": "FAIL",
            "passed": 0,
            "failed": 1,
            "total": 1,
            "cases": [{
                "name": "Maestro Execution",
                "status": "FAIL",
                "time": 0.0,
                "failure": f"JUnit XML report not found at {xml_path}",
            }],
        }

    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
    except Exception as exc:
        return {
            "verdict": "FAIL",
            "passed": 0,
            "failed": 1,
            "total": 1,
            "cases": [{
                "name": "XML Parse",
                "status": "FAIL",
                "time": 0.0,
                "failure": f"Failed to parse JUnit XML: {exc}",
            }],
        }

    cases: list[dict] = []
    total = 0
    failed = 0
    passed = 0

    # Handles both <testsuites> and <testsuite> root
    testcases = root.findall(".//testcase")
    for tc in testcases:
        total += 1
        name = tc.attrib.get("name", f"case_{total}")
        classname = tc.attrib.get("classname", "")
        time_sec = float(tc.attrib.get("time", "0.0") or "0.0")

        failure_elem = tc.find("failure")
        error_elem = tc.find("error")
        failure_msg = ""
        if failure_elem is not None:
            failure_msg = failure_elem.attrib.get("message") or failure_elem.text or "Test failed"
        elif error_elem is not None:
            failure_msg = error_elem.attrib.get("message") or error_elem.text or "Test error"

        if failure_msg:
            failed += 1
            cases.append({
                "id": name,
                "title": f"{classname}: {name}" if classname else name,
                "status": "FAIL",
                "duration_seconds": time_sec,
                "reason": failure_msg.strip(),
            })
        else:
            passed += 1
            cases.append({
                "id": name,
                "title": f"{classname}: {name}" if classname else name,
                "status": "PASS",
                "duration_seconds": time_sec,
                "reason": "",
            })

    overall_verdict = "PASS" if (failed == 0 and total > 0) else "FAIL"
    return {
        "verdict": overall_verdict,
        "passed": passed,
        "failed": failed,
        "total": total,
        "cases": cases,
    }


def capture_adb_forensics(serial: str | None, out_dir: Path) -> dict:
    """Capture failure screenshot and logcat crash forensics via ADB."""
    out_dir.mkdir(parents=True, exist_ok=True)
    serial_args = ["-s", serial] if serial else []
    screenshot_file = out_dir / "failure_screenshot.png"
    logcat_file = out_dir / "crash_logcat.txt"

    # Screenshot
    try:
        proc = subprocess.run(
            ["adb", *serial_args, "exec-out", "screencap", "-p"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if proc.stdout and proc.stdout.startswith(b"\x89PNG"):
            screenshot_file.write_bytes(proc.stdout)
    except Exception:
        pass

    # Logcat crash buffer
    crashes = ""
    try:
        proc = subprocess.run(
            ["adb", *serial_args, "logcat", "-d", "-b", "crash"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
        crashes = (proc.stdout or "").strip()
        if crashes:
            logcat_file.write_text(crashes, encoding="utf-8")
    except Exception:
        pass

    return {
        "screenshot": str(screenshot_file) if screenshot_file.is_file() else None,
        "logcat_crash": str(logcat_file) if logcat_file.is_file() else None,
        "has_crashes": bool(crashes),
    }


def execute_maestro_suite(
    target_path: Path,
    serial: str | None,
    package: str,
    reports_dir: Path,
    task_id: str = "default",
) -> dict:
    """Execute Maestro test suite on device, parse reports, and gather diagnostics."""
    is_ok, maestro_info, maestro_bin = ensure_maestro_installed()
    if not is_ok:
        return {
            "verdict": "ENV_FAILURE",
            "reason": maestro_info,
            "install_guide": get_maestro_install_instructions(),
            "cases": [],
            "passed": 0,
            "failed": 0,
            "total": 0,
        }

    task_reports_dir = reports_dir / task_id
    task_reports_dir.mkdir(parents=True, exist_ok=True)
    junit_xml = task_reports_dir / "maestro_junit.xml"

    cmd = [maestro_bin]
    if serial:
        cmd.extend(["--device", serial])
    cmd.extend(["test", str(target_path), "--format", "junit", "--output", str(junit_xml)])

    live_print(f"[*] Launching Maestro E2E Test Suite on {serial or 'default device'}...")
    live_print(f"[*] Command: {' '.join(cmd)}")

    code, stdout_lines, stderr_lines = run_streaming(
        cmd,
        cwd=str(REPO),
        heartbeat_sec=10.0,
        should_echo=lambda line: bool(line.strip()),
        label="maestro-test",
    )

    parsed = parse_maestro_junit_xml(junit_xml)
    parsed["exit_code"] = code
    parsed["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    parsed["target_path"] = str(target_path)
    parsed["task_id"] = task_id

    # If test failed, gather adb diagnostics
    if parsed["verdict"] != "PASS" or code != 0:
        forensics = capture_adb_forensics(serial, task_reports_dir)
        parsed["diagnostics"] = forensics

    # Write summary JSON
    summary_file = task_reports_dir / "summary.json"
    summary_file.write_text(json.dumps(parsed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    parsed["summary_path"] = str(summary_file)

    return parsed
