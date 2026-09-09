"""Deterministic multi-label Android change-surface classifier."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import changed_files  # noqa: E402
from _vnext_common import canonical_sha256  # noqa: E402
from delivery_manifest import is_delivery_relevant  # noqa: E402


SCHEMA_VERSION = 1
SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
CRITICAL_SURFACES = {"BILLING", "AUTH", "SECURITY", "SENSITIVE_DATA", "CRYPTO"}
HIGH_SURFACES = {"ROOM_SCHEMA", "MANIFEST_PERMISSION", "BUILD_CONFIG", "PUBLIC_API", "NATIVE_CODE"}
DEVICE_SURFACES = {"COMPOSE_UI", "XML_UI", "DEVICE_API"}

PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("BILLING", re.compile(r"(?i)billingclient|purchase|subscription|productdetails"), "BILLING_PATTERN"),
    ("AUTH", re.compile(r"(?i)oauth|authentication|authorization|login|sign.?in|jwt"), "AUTH_PATTERN"),
    ("CRYPTO", re.compile(r"(?i)cipher|keystore|secretkey|encrypt|decrypt|messageDigest"), "CRYPTO_PATTERN"),
    ("SENSITIVE_DATA", re.compile(r"(?i)access.?token|refresh.?token|password|biometric|health.?data|location"), "SENSITIVE_PATTERN"),
    ("COROUTINES", re.compile(r"\b(suspend|CoroutineScope|Dispatchers\.|Flow<|StateFlow|SharedFlow|launch\s*\{|async\s*\{)"), "COROUTINE_PATTERN"),
    ("ROOM_SCHEMA", re.compile(r"@(Database|Entity|Embedded|Relation)|AutoMigration|Migration\s*\("), "ROOM_PATTERN"),
    ("PERSISTENCE", re.compile(r"(?i)datastore|sqldelight|sqlite(database|openhelper)?|realm(configuration)?"), "PERSISTENCE_PATTERN"),
    ("NETWORK", re.compile(r"(?i)retrofit|okhttp|ktor|httpclient|@GET\b|@POST\b|websocket"), "NETWORK_PATTERN"),
    ("SECURITY", re.compile(r"(?i)networksecurityconfig|certificatepinner|trustmanager|hostnameverifier|x509certificate"), "SECURITY_PATTERN"),
    ("DEVICE_API", re.compile(r"(?i)bluetooth|sensor|locationmanager|camera|notificationmanager|foregroundservice"), "DEVICE_API_PATTERN"),
)


def _add(result: dict, surface: str, path: str, reason: str) -> None:
    result.setdefault(surface, {"files": set(), "reasons": set()})
    result[surface]["files"].add(path)
    result[surface]["reasons"].add(reason)


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _head_text(repo: Path, relative: str) -> str:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{relative}"], cwd=str(repo), capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    return proc.stdout if proc.returncode == 0 and len(proc.stdout) <= 2 * 1024 * 1024 else ""


def _changed_line_count(repo: Path, changes: list) -> int:
    """Return a conservative diff-size bound without trusting file mtimes."""
    total = 0
    proc = subprocess.run(
        ["git", "diff", "--numstat", "HEAD", "--"], cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode == 0:
        for line in (proc.stdout or "").splitlines():
            fields = line.split("\t", 2)
            if len(fields) < 3:
                continue
            if "=>" not in fields[2] and not is_delivery_relevant(fields[2]):
                continue
            if fields[0] == "-" or fields[1] == "-":
                total += 100_000
            else:
                try:
                    total += int(fields[0]) + int(fields[1])
                except ValueError:
                    total += 100_000
    for changed in changes:
        if not changed.is_untracked or not changed.exists or not is_delivery_relevant(changed.rel_posix):
            continue
        try:
            data = changed.path.read_bytes()
            total += data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        except OSError:
            total += 100_000
    return total


def classify(repo: Path) -> dict:
    root = repo.resolve()
    found: dict[str, dict[str, set[str]]] = {}
    changes = changed_files(root, include_untracked=True)
    for changed in changes:
        rel = changed.rel_posix
        if not is_delivery_relevant(rel) and not (changed.old_rel_posix and is_delivery_relevant(changed.old_rel_posix)):
            continue
        lower = rel.lower()
        suffix = Path(lower).suffix
        text = _read_text(changed.path) if changed.exists else ""
        # Classification is the union of before and after content. Removing a
        # billing/auth/Room declaration is at least as risky as adding one.
        before_rel = changed.old_rel_posix or rel
        text = text + "\n" + _head_text(root, before_rel)
        test_path = "/test/" in f"/{lower}" or "/androidtest/" in f"/{lower}" or lower.endswith(("test.kt", "test.java"))
        if suffix in (".md", ".txt", ".rst"):
            _add(found, "DOCS", rel, "DOCUMENTATION_PATH")
        if "/res/values" in f"/{lower}" and suffix == ".xml":
            if Path(lower).name in ("strings.xml", "plurals.xml", "arrays.xml"):
                _add(found, "LOCALIZATION", rel, "LOCALIZED_RESOURCE")
            else:
                _add(found, "RESOURCE_UI", rel, "VALUES_RESOURCE")
        if "/res/layout" in f"/{lower}" and suffix == ".xml":
            _add(found, "XML_UI", rel, "LAYOUT_RESOURCE")
        if "/res/" in f"/{lower}" and suffix not in (".md", ".txt"):
            _add(found, "RESOURCE_UI", rel, "ANDROID_RESOURCE")
        if suffix in (".kt", ".kts") and ("@composable" in text.lower() or "androidx.compose" in text.lower()):
            _add(found, "COMPOSE_UI", rel, "COMPOSE_PATTERN")
        if suffix in (".kt", ".java") and not test_path:
            _add(found, "BUSINESS_LOGIC", rel, "SOURCE_CHANGE")
        if suffix in (".gradle", ".kts", ".toml", ".properties") or Path(lower).name in ("gradlew", "gradlew.bat"):
            _add(found, "BUILD_CONFIG", rel, "BUILD_FILE")
        if "androidmanifest.xml" in lower:
            surface = "MANIFEST_PERMISSION" if re.search(r"uses-permission|android:exported|provider|intent-filter", text, re.I) else "BUILD_CONFIG"
            _add(found, surface, rel, "MANIFEST_CHANGE")
        if suffix in (".aidl", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".so"):
            _add(found, "NATIVE_CODE", rel, "NATIVE_OR_AIDL_CHANGE")
        if test_path:
            _add(found, "TEST_ONLY", rel, "TEST_CHANGE")
        if not test_path and re.search(r"\b(public|protected)\s+(class|interface|fun|static|abstract)\b", text):
            _add(found, "PUBLIC_API", rel, "PUBLIC_DECLARATION")
        for surface, pattern, reason in PATTERNS:
            if not test_path and pattern.search(text):
                _add(found, surface, rel, reason)

    non_docs = set(found) - {"DOCS", "TEST_ONLY"}
    relevant_changes = [item for item in changes if is_delivery_relevant(item.rel_posix) or (item.old_rel_posix and is_delivery_relevant(item.old_rel_posix))]
    if not found and relevant_changes:
        _add(found, "UNKNOWN", relevant_changes[0].rel_posix, "UNCLASSIFIED_CHANGE")
    elif "TEST_ONLY" in found and not non_docs:
        pass
    elif "DOCS" in found and not non_docs:
        pass

    surfaces = sorted(found)
    if set(surfaces) & CRITICAL_SURFACES:
        severity = "CRITICAL"
    elif set(surfaces) & HIGH_SURFACES:
        severity = "HIGH"
    elif set(surfaces) & (DEVICE_SURFACES | {"BUSINESS_LOGIC", "NETWORK", "COROUTINES", "PERSISTENCE"}):
        severity = "MEDIUM"
    else:
        severity = "LOW"
    confidence = "LOW" if "UNKNOWN" in surfaces else "HIGH"
    details = {
        surface: {
            "files": sorted(info["files"]),
            "reasons": sorted(info["reasons"]),
        }
        for surface, info in sorted(found.items())
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "surfaces": surfaces,
        "severity": severity,
        "confidence": confidence,
        "details": details,
        "changed_files": len(relevant_changes),
        "changed_lines": _changed_line_count(root, relevant_changes),
        "has_delete_or_rename": any(item.status in {"D", "R"} for item in relevant_changes),
    }
    result["classification_sha256"] = canonical_sha256(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = classify(Path(args.repo))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"SURFACES={','.join(result['surfaces']) or 'NONE'}")
        print(f"SEVERITY={result['severity']}")
        print(f"CONFIDENCE={result['confidence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
