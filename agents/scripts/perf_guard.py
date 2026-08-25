"""Performance, ANR, and Memory Leak static auditor for this Android app.
Usage: python .agents/scripts/perf_guard.py [--all] [--device <ID>]
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _product import APPLICATION_ID, ANDROID_SRC  # noqa: E402

enable_line_buffered_stdio()

REPO = Path(__file__).resolve().parents[2]
APP_DIR = REPO.joinpath(*ANDROID_SRC)


def get_git_modified_files() -> list[Path]:
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        files = []
        for line in (res.stdout or "").splitlines():
            if len(line) > 3:
                path_str = line[3:].strip()
                if " -> " in path_str:
                    path_str = path_str.split(" -> ")[1].strip()
                f_path = REPO / path_str
                if f_path.is_file() and f_path.suffix == ".kt":
                    files.append(f_path)
        return files
    except Exception:
        return []


def scan_file(file_path: Path) -> list[dict]:
    findings = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [{"file": str(file_path), "line": 1, "severity": "Warning", "message": f"Could not read file: {e}"}]

    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()

        # 1. runBlocking check
        if "runBlocking" in stripped and not stripped.startswith("//") and not stripped.startswith("/*"):
            # Exclude test files
            if "src/test" not in str(file_path).replace("\\", "/") and "src/androidTest" not in str(file_path).replace("\\", "/"):
                findings.append({
                    "file": str(file_path),
                    "line": idx,
                    "severity": "CRITICAL (ANR)",
                    "message": "Found 'runBlocking' on production code. This blocks threads and causes ANRs. Use coroutineScope or viewModelScope.launch instead."
                })

        # 2. Thread.sleep check
        if "Thread.sleep(" in stripped and not stripped.startswith("//"):
            findings.append({
                "file": str(file_path),
                "line": idx,
                "severity": "CRITICAL (ANR)",
                "message": "Found 'Thread.sleep()'. This halts thread execution. Use kotlinx.coroutines.delay() instead."
            })

        # 3. allowMainThreadQueries check
        if "allowMainThreadQueries" in stripped and not stripped.startswith("//"):
            findings.append({
                "file": str(file_path),
                "line": idx,
                "severity": "CRITICAL (ANR)",
                "message": "Found 'allowMainThreadQueries()'. Database operations on Main thread cause strict-mode violations and ANRs."
            })

        # 4. WakeLock acquire without timeout
        if re.search(r"wakeLock\s*\.\s*acquire\s*\(\s*\)", stripped) and not stripped.startswith("//"):
            findings.append({
                "file": str(file_path),
                "line": idx,
                "severity": "HIGH (Battery Drain)",
                "message": "WakeLock acquired without a timeout. Always specify a maximum timeout: wakeLock.acquire(timeoutMs)."
            })

        # 5. Contract State without @Immutable
        if "data class State(" in stripped:
            prev_lines = lines[max(0, idx - 5):idx - 1]
            has_immutable = any("@Immutable" in pl or "@Stable" in pl for pl in prev_lines)
            if not has_immutable:
                findings.append({
                    "file": str(file_path),
                    "line": idx,
                    "severity": "OPTIMIZATION (Recomposition)",
                    "message": "MVI/Compose State class missing @Immutable or @Stable. Import androidx.compose.runtime.Immutable and annotate the class."
                })

    return findings


def check_device_anrs(device_id: str | None = None) -> list[str]:
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(["shell", "dumpsys", "activity", "processes"])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        output = res.stdout or ""
        anrs = []
        if f"ANR in {APPLICATION_ID}" in output or "Recent ANR" in output:
            for line in output.splitlines():
                if APPLICATION_ID in line and ("ANR" in line or "error" in line.lower()):
                    anrs.append(line.strip())
        return anrs
    except Exception as e:
        return [f"Could not query device ANRs: {e}"]


def main():
    parser = argparse.ArgumentParser(description="Performance & ANR static auditor for this app")
    parser.add_argument("--all", action="store_true", help="Scan all Kotlin files in app/src/main")
    parser.add_argument("--device", help="Optional physical device ID to inspect recent ANRs via ADB")
    args = parser.parse_args()

    print("==================================================")
    print("  HARNESS PERFORMANCE & ANR GUARDIAN AUDITOR")
    print("==================================================")

    if args.all:
        try:
            from _modules import discover_source_roots

            roots = discover_source_roots(REPO)
        except Exception:
            roots = []
        if not roots:
            roots = [APP_DIR] if APP_DIR.is_dir() else [REPO]
        target_files = [
            p
            for root in roots
            for p in root.glob("**/*.kt")
        ]
        print(f"Scanning {len(target_files)} Kotlin file(s) across {len(roots)} module source root(s)...")
    else:
        target_files = get_git_modified_files()
        if not target_files:
            print("No modified Kotlin files found in git status (including untracked).")
            print("Audit Complete.")
            return 0
        print(f"Scanning {len(target_files)} target Kotlin files...")

    all_findings = []
    for tf in target_files:
        findings = scan_file(tf)
        all_findings.extend(findings)

    print()
    if all_findings:
        critical_count = sum(1 for f in all_findings if "CRITICAL" in f["severity"])
        print(f"Found {len(all_findings)} performance findings ({critical_count} critical):\n")
        for f in all_findings:
            rel = Path(f["file"]).relative_to(REPO) if str(REPO) in f["file"] else f["file"]
            print(f"[{f['severity']}] {rel}:{f['line']}")
            print(f"   ↳ {f['message']}\n")
    else:
        print("ZERO Main Thread blockages, unannotated states, or unsafe WakeLocks found.")

    if args.device:
        print(f"\n--- Checking Device ANR History for {args.device} ---")
        device_anrs = check_device_anrs(args.device)
        if device_anrs:
            print("Found recent ANR events on device:")
            for anr in device_anrs:
                print(f"   {anr}")
        else:
            print("No recent ANR events detected on connected device.")

    print("\nAudit Complete.")
    return 1 if any("CRITICAL" in f["severity"] for f in all_findings) else 0


if __name__ == "__main__":
    sys.exit(main())
