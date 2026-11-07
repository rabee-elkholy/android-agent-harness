"""Performance, ANR, and Memory Leak static auditor for this Android app.
Usage: python .agents/scripts/perf_guard.py [--all] [--device <ID>]
"""
import argparse
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


from _repo_files import changed_paths, repo_glob  # noqa: E402


def get_git_modified_files() -> list[Path]:
    try:
        return [p for p in changed_paths() if p.suffix == ".kt"]
    except Exception:
        return []


def _has_real_match(line: str, pattern: re.Pattern[str]) -> bool:
    from fast_kt_lint import _in_string_or_comment
    return any(not _in_string_or_comment(line, m.start()) for m in pattern.finditer(line))


_RUNBLOCKING_RE = re.compile(r"\brunBlocking\s*(?:\(|\{)")
_THREAD_SLEEP_RE = re.compile(r"\bThread\s*\.\s*sleep\s*\(")
_ALLOW_MAIN_THREAD_RE = re.compile(r"\ballowMainThreadQueries\s*\(")
_WAKELOCK_ACQUIRE_RE = re.compile(r"\bwakeLock\s*\.\s*acquire\s*\(\s*\)")
_STATE_DATA_CLASS_RE = re.compile(r"\bdata\s+class\s+[A-Za-z0-9_]*(?:State|UiState)\b")


def scan_file(file_path: Path) -> list[dict]:
    findings = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [{"file": str(file_path), "line": 1, "severity": "Warning", "message": f"Could not read file: {e}"}]

    lines = content.splitlines()
    has_compose_context = any(
        "androidx.compose" in l or "org.jetbrains.compose" in l or "@Composable" in l
        for l in lines
    )
    in_block_comment = False
    in_triple_string = False

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()

        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped[2:]:
                in_block_comment = True
            continue
        if in_triple_string:
            if '"""' in line:
                in_triple_string = False
            continue
        if '"""' in stripped and stripped.count('"""') % 2 != 0:
            in_triple_string = True
            continue

        if stripped.startswith("//") or stripped.startswith("*"):
            continue

        # 1. runBlocking check
        if _has_real_match(line, _RUNBLOCKING_RE):
            # Exclude test files (Android & KMP test source sets)
            from _modules import is_kmp_or_android_test_path
            norm_fp = str(file_path).replace("\\", "/")
            if not is_kmp_or_android_test_path(norm_fp) and "src/test" not in norm_fp and "src/androidTest" not in norm_fp:
                findings.append({
                    "file": str(file_path),
                    "line": idx,
                    "severity": "CRITICAL (ANR)",
                    "message": "Found 'runBlocking' on production code. This blocks threads and causes ANRs. Use coroutineScope or viewModelScope.launch instead."
                })

        # 2. Thread.sleep check
        if _has_real_match(line, _THREAD_SLEEP_RE):
            findings.append({
                "file": str(file_path),
                "line": idx,
                "severity": "CRITICAL (ANR)",
                "message": "Found 'Thread.sleep()'. This halts thread execution. Use kotlinx.coroutines.delay() instead."
            })

        # 3. allowMainThreadQueries check
        if _has_real_match(line, _ALLOW_MAIN_THREAD_RE):
            findings.append({
                "file": str(file_path),
                "line": idx,
                "severity": "CRITICAL (ANR)",
                "message": "Found 'allowMainThreadQueries()'. Database operations on Main thread cause strict-mode violations and ANRs."
            })

        # 4. WakeLock acquire without timeout
        if _has_real_match(line, _WAKELOCK_ACQUIRE_RE):
            findings.append({
                "file": str(file_path),
                "line": idx,
                "severity": "HIGH (Battery Drain)",
                "message": "WakeLock acquired without a timeout. Always specify a maximum timeout: wakeLock.acquire(timeoutMs)."
            })

        # 5. Contract State without @Immutable (only in Compose files)
        if has_compose_context and _has_real_match(line, _STATE_DATA_CLASS_RE):
            has_immutable = "@Immutable" in line or "@Stable" in line
            if not has_immutable:
                lookback_idx = idx - 2
                in_kdoc = False
                while lookback_idx >= 0:
                    prev_line = lines[lookback_idx].strip()
                    if in_kdoc:
                        if "/*" in prev_line:
                            in_kdoc = False
                        lookback_idx -= 1
                        continue
                    if prev_line.endswith("*/") and not prev_line.startswith("/*"):
                        in_kdoc = True
                        lookback_idx -= 1
                        continue
                    if prev_line.startswith("@"):
                        if "@Immutable" in prev_line or "@Stable" in prev_line:
                            has_immutable = True
                            break
                        lookback_idx -= 1
                    elif not prev_line or prev_line.startswith("//") or prev_line.startswith("/*") or prev_line.startswith("*"):
                        lookback_idx -= 1
                    else:
                        break
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
            for p in repo_glob(root, "**/*.kt")
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
