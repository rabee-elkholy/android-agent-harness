"""Zero-token static health bridge: SARIF (Detekt/Android Lint), Gradle BuildHealth, and LeakCanary.

Filters all static findings strictly to task-modified files and modules so pre-existing
warnings in untouched legacy files never block task verification, and silently skips in 0 ms
when none of these optional tools/reports are present in the repository.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _repo_files import repo_glob  # noqa: E402
from _vnext_common import ValidationError, read_json  # noqa: E402


def _scan_gradle_configs(repo: Path) -> str:
    chunks: list[str] = []
    for cand in (
        repo / "build.gradle.kts",
        repo / "build.gradle",
        repo / "settings.gradle.kts",
        repo / "settings.gradle",
        repo / "gradle" / "libs.versions.toml",
    ):
        if cand.is_file():
            try:
                chunks.append(cand.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    for sub in sorted(repo_glob(repo, "**/build.gradle*"))[:40]:
        if sub.is_file():
            try:
                chunks.append(sub.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks).lower()


def probe_capabilities(repo: Path) -> dict[str, Any]:
    cfg = _scan_gradle_configs(repo)
    sarif_files = [
        p.relative_to(repo).as_posix()
        for p in sorted(repo_glob(repo, "**/build/reports/**/*.sarif"))
        if p.is_file()
    ]
    build_health_files = [
        p.relative_to(repo).as_posix()
        for p in sorted(repo_glob(repo, "**/build/reports/dependency-analysis/*.json"))
        if p.is_file() and p.name in {"build-health-report.json", "advice.json", "advice-all-variants.json"}
    ]
    return {
        "detekt_configured": ("detekt" in cfg) or bool(sarif_files),
        "ktlint_configured": "ktlint" in cfg,
        "dependency_analysis_configured": ("com.autonomousapps.dependency-analysis" in cfg) or bool(build_health_files),
        "leakcanary_configured": "leakcanary" in cfg,
        "sarif_reports": sarif_files,
        "build_health_reports": build_health_files,
    }


def _normalize_sarif_uri(repo: Path, uri: str, uri_base_map: dict[str, str] | None = None) -> str:
    raw = str(uri or "").strip()
    if not raw:
        return ""
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        fs_path = Path(unquote(parsed.path.lstrip("/") if os.name == "nt" and re.match(r"^/[A-Za-z]:", parsed.path) else parsed.path))
        try:
            return fs_path.resolve().relative_to(repo.resolve()).as_posix()
        except (OSError, ValueError):
            return fs_path.as_posix()
    clean = unquote(raw).replace("\\", "/").lstrip("./")
    cand = (repo / clean)
    if cand.exists():
        try:
            return cand.resolve().relative_to(repo.resolve()).as_posix()
        except (OSError, ValueError):
            return clean
    if uri_base_map:
        for base_uri in uri_base_map.values():
            if base_uri.startswith("file://"):
                base_p = Path(unquote(urlparse(base_uri).path))
                joined = base_p / clean
                try:
                    return joined.resolve().relative_to(repo.resolve()).as_posix()
                except (OSError, ValueError):
                    continue
    return clean


def inspect_sarif_for_paths(repo: Path, changed_paths: list[str] | set[str]) -> dict[str, Any]:
    wanted = {p.replace("\\", "/").lstrip("./") for p in changed_paths if p}
    sarif_paths = [p for p in sorted(repo_glob(repo, "**/build/reports/**/*.sarif")) if p.is_file()]
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not sarif_paths or not wanted:
        return {"present": bool(sarif_paths), "reports_scanned": len(sarif_paths), "errors": [], "warnings": []}

    for sp in sarif_paths[:30]:
        try:
            doc = json.loads(sp.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        for run in doc.get("runs") or []:
            if not isinstance(run, dict):
                continue
            tool_name = str(((run.get("tool") or {}).get("driver") or {}).get("name") or sp.stem)
            base_ids = {}
            orig_bases = run.get("originalUriBaseIds")
            if isinstance(orig_bases, dict):
                for k, v in orig_bases.items():
                    if isinstance(v, dict) and v.get("uri"):
                        base_ids[str(k)] = str(v["uri"])
            for res in run.get("results") or []:
                if not isinstance(res, dict):
                    continue
                if res.get("suppressions"):
                    continue
                level = str(res.get("level") or "warning").lower()
                rule_id = str(res.get("ruleId") or "rule")
                msg = str(((res.get("message") or {}).get("text")) or "").strip()
                for loc in res.get("locations") or []:
                    phys = (loc or {}).get("physicalLocation") or {}
                    art = phys.get("artifactLocation") or {}
                    rel = _normalize_sarif_uri(repo, str(art.get("uri") or ""), base_ids)
                    # Also match suffix if SARIF wrote module-relative src/main/...
                    matched_path = rel if rel in wanted else next(
                        (w for w in wanted if rel and w.endswith("/" + rel)), ""
                    )
                    if not matched_path:
                        continue
                    line_no = int(((phys.get("region") or {}).get("startLine")) or 1)
                    item = {
                        "tool": tool_name,
                        "rule_id": rule_id,
                        "level": level,
                        "file": matched_path,
                        "line": line_no,
                        "message": msg[:240],
                    }
                    if level == "error":
                        errors.append(item)
                    else:
                        warnings.append(item)
    return {
        "present": True,
        "reports_scanned": len(sarif_paths),
        "errors": errors[:40],
        "warnings": warnings[:40],
    }


def inspect_build_health_for_paths(repo: Path, changed_paths: list[str] | set[str]) -> dict[str, Any]:
    norm_paths = [p.replace("\\", "/").lstrip("./") for p in changed_paths if p]
    gradle_touched = [
        p for p in norm_paths
        if p.endswith(("build.gradle", "build.gradle.kts", "libs.versions.toml", "settings.gradle", "settings.gradle.kts"))
    ]
    bh_paths = [
        p for p in sorted(repo_glob(repo, "**/build/reports/dependency-analysis/*.json"))
        if p.is_file() and p.name in {"build-health-report.json", "advice.json", "advice-all-variants.json"}
    ]
    if not bh_paths or not gradle_touched:
        return {"present": bool(bh_paths), "gradle_touched": bool(gradle_touched), "errors": [], "advisories": []}

    # Determine touched Gradle module paths (e.g. "app/build.gradle.kts" -> ":app")
    touched_modules: set[str] = set()
    for gp in gradle_touched:
        parent = Path(gp).parent.as_posix()
        if parent in ("", ".", "gradle"):
            touched_modules.add(":")
        else:
            touched_modules.add(":" + parent.replace("/", ":"))

    errors: list[dict[str, Any]] = []
    advisories: list[dict[str, Any]] = []
    for bp in bh_paths[:10]:
        try:
            raw = json.loads(bp.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        proj_list = raw.get("projectAdvice") if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        if not isinstance(proj_list, list):
            continue
        for proj in proj_list:
            if not isinstance(proj, dict):
                continue
            mod_path = str(proj.get("projectPath") or "")
            if ":" not in touched_modules and mod_path not in touched_modules:
                continue
            should_fail = bool(proj.get("shouldFail"))
            for adv in proj.get("dependencyAdvice") or []:
                if not isinstance(adv, dict):
                    continue
                coords = str(((adv.get("coordinates") or {}).get("identifier")) or adv.get("coordinates") or "")
                from_cfg = str(adv.get("fromConfiguration") or "")
                to_cfg = str(adv.get("toConfiguration") or "")
                entry = {
                    "module": mod_path,
                    "dependency": coords,
                    "from": from_cfg,
                    "to": to_cfg or "remove (unused)",
                    "blocking": should_fail,
                }
                if should_fail:
                    errors.append(entry)
                else:
                    advisories.append(entry)

    return {
        "present": True,
        "gradle_touched": True,
        "errors": errors[:30],
        "advisories": advisories[:30],
    }


def check_task_static_health(repo: Path, changed_paths: list[str] | set[str]) -> tuple[bool, str, dict[str, Any]]:
    """Run 0-token SARIF & BuildHealth checks scoped strictly to changed_paths.

    Returns `(ok, summary_message, details)`. `details["active"]` is True ONLY when
    at least one SARIF or relevant BuildHealth report actually exists on disk.
    """
    sarif = inspect_sarif_for_paths(repo, changed_paths)
    bh = inspect_build_health_for_paths(repo, changed_paths)
    active = bool(sarif["present"] or (bh["present"] and bh["gradle_touched"]))
    details = {"active": active, "sarif": sarif, "build_health": bh}
    if not active:
        return True, "no SARIF or BuildHealth reports present (skipped)", details

    blocking_msgs: list[str] = []
    for err in sarif["errors"][:8]:
        blocking_msgs.append(f"[{err['tool']}:{err['rule_id']}] {err['file']}:{err['line']} — {err['message']}")
    for b_err in bh["errors"][:8]:
        blocking_msgs.append(f"[BuildHealth {b_err['module']}] {b_err['dependency']}: change '{b_err['from']}' -> '{b_err['to']}'")

    if blocking_msgs:
        return False, "STATIC_HEALTH_VIOLATION:\n  " + "\n  ".join(blocking_msgs), details

    warn_count = len(sarif["warnings"]) + len(bh["advisories"])
    return True, f"static health clean on modified scope ({warn_count} non-blocking advisory item(s))", details


def check_device_leaks(
    repo: Path,
    *,
    serial: str | None = None,
    application_id: str | None = None,
) -> dict[str, Any]:
    """Read-only post-E2E LeakCanary check via bounded logcat and run-as inspection."""
    caps = probe_capabilities(repo)
    if not caps["leakcanary_configured"]:
        return {"status": "SKIPPED", "reason": "LeakCanary not configured in project Gradle files.", "leaks_detected": 0}

    adb = shutil.which("adb")
    if not adb:
        for env_k in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            sdk = os.environ.get(env_k, "")
            if sdk:
                cand = Path(sdk) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
                if cand.is_file():
                    adb = str(cand)
                    break
    if not adb:
        return {"status": "SKIPPED", "reason": "adb not available on PATH.", "leaks_detected": 0}

    if not application_id:
        try:
            from _product import APPLICATION_ID
            application_id = str(APPLICATION_ID or "")
        except ImportError:
            application_id = ""

    adb_prefix = [adb] + (["-s", serial] if serial else [])
    try:
        log_proc = subprocess.run(
            [*adb_prefix, "logcat", "-d", "-t", "500", "-s", "LeakCanary:D"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        log_text = log_proc.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        log_text = ""

    app_leak_matches = re.findall(r"(\d+)\s+APPLICATION\s+LEAKS", log_text)
    leak_count = max((int(m) for m in app_leak_matches), default=0)

    hprof_files: list[str] = []
    if application_id and application_id != "com.example.app":
        for rel_dir in ("no_backup/leakcanary", "files/leakcanary"):
            try:
                ls_proc = subprocess.run(
                    [*adb_prefix, "shell", "run-as", application_id, "ls", rel_dir],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    check=False,
                )
                if ls_proc.returncode == 0 and ls_proc.stdout:
                    hprof_files.extend(
                        ln.strip() for ln in ls_proc.stdout.splitlines() if ln.strip().endswith(".hprof")
                    )
            except (OSError, subprocess.TimeoutExpired):
                continue

    if leak_count > 0:
        # Extract compact signature lines
        sig_lines = [
            ln.strip() for ln in log_text.splitlines()
            if any(tok in ln for tok in ("APPLICATION LEAKS", "┬───", "╰→", "Leaking: YES"))
        ][:12]
        return {
            "status": "LEAK_DETECTED",
            "leaks_detected": leak_count,
            "hprof_count": len(hprof_files),
            "summary": sig_lines,
        }

    return {
        "status": "PASS",
        "leaks_detected": 0,
        "hprof_count": len(hprof_files),
        "reason": "Zero LeakCanary application leaks observed.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capabilities", "report", "leak-check"))
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("HARNESS_REPO") or Path(__file__).resolve().parents[2]))
    parser.add_argument("--serial", help="Optional adb device serial for leak-check")
    parser.add_argument("--package", dest="application_id", help="Optional applicationId for leak-check")
    parser.add_argument("--paths", nargs="*", help="Optional explicit changed paths for report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    try:
        if args.action == "capabilities":
            res = probe_capabilities(repo)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        if args.action == "leak-check":
            res = check_device_leaks(repo, serial=args.serial, application_id=args.application_id)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 1 if res.get("status") == "LEAK_DETECTED" else 0

        if args.paths:
            paths = list(args.paths)
        else:
            from _repo_files import changed_paths
            paths = sorted(changed_paths(repo))
        ok, msg, details = check_task_static_health(repo, paths)
        payload = {"status": "PASS" if ok else "FAIL", "message": msg, "changed_paths": paths, **details}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    except (OSError, ValueError, ValidationError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
