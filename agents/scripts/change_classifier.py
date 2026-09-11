"""Deterministic multi-label Android change-surface classifier."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import ChangedFile, changed_files  # noqa: E402
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


HUNK_LINE_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
DECL_RE = re.compile(r"\b(?:class|interface|object|fun|suspend\s+fun)\s+([A-Za-z0-9_]+)")
CLASS_DECL_RE = re.compile(r"\b(?:class|interface|object)\s+([A-Za-z0-9_]+)")
FUN_DECL_RE = re.compile(r"\b(?:fun|suspend\s+fun)\s+([A-Za-z0-9_]+)")


def _enclosing_structural_context(text: str, modified_line_numbers: list[int]) -> str:
    """Extract enclosing declaration (function or class) and leading annotations for modified lines."""
    if not text or not modified_line_numbers:
        return ""
    lines = text.splitlines()
    total = len(lines)
    blocks: list[str] = []
    seen_ranges: set[tuple[int, int]] = set()

    for line_num in modified_line_numbers:
        idx = min(max(0, line_num - 1), total - 1)
        start_scan = max(0, idx - 100)
        enclosing_idx = None
        for cur in range(idx, start_scan - 1, -1):
            if DECL_RE.search(lines[cur]):
                enclosing_idx = cur
                break
        if enclosing_idx is not None:
            decl_start = enclosing_idx
            while decl_start > 0 and lines[decl_start - 1].strip().startswith("@"):
                decl_start -= 1

            if FUN_DECL_RE.search(lines[enclosing_idx]):
                class_scan_limit = max(0, idx - 120)
                for c_cur in range(decl_start - 1, class_scan_limit - 1, -1):
                    if CLASS_DECL_RE.search(lines[c_cur]):
                        outer_start = c_cur
                        while outer_start > 0 and lines[outer_start - 1].strip().startswith("@"):
                            outer_start -= 1
                        outer_class_end = c_cur + 1
                        for scan_fwd in range(c_cur, min(c_cur + 5, total)):
                            outer_class_end = scan_fwd + 1
                            if "{" in lines[scan_fwd]:
                                break
                        class_range = (outer_start, outer_class_end)
                        if class_range not in seen_ranges:
                            seen_ranges.add(class_range)
                            class_lines = list(lines[outer_start:outer_class_end])
                            if class_lines and "{" in class_lines[-1]:
                                class_lines[-1] = class_lines[-1].split("{", 1)[0]
                            blocks.append("\n".join(class_lines))
                        break

            r = (decl_start, idx + 1)
            if r not in seen_ranges:
                seen_ranges.add(r)
                blocks.append("\n".join(lines[decl_start:idx + 1]))
    return "\n".join(blocks)



def _diff_content(repo: Path, changed: ChangedFile) -> tuple[str, str]:
    """Return added/removed diff text and bounded enclosing structural context."""
    if changed.is_untracked:
        content = _read_text(changed.path) if changed.exists else ""
        return content, ""
    before_rel = changed.old_rel_posix or changed.rel_posix
    if not changed.exists or changed.status == "D":
        return _head_text(repo, before_rel), ""

    diff_cmd = ["git", "diff", "-U0", "--no-ext-diff", "--find-renames", "HEAD", "--", changed.rel_posix]
    if changed.old_rel_posix and changed.old_rel_posix != changed.rel_posix:
        diff_cmd.append(changed.old_rel_posix)
    proc = subprocess.run(
        diff_cmd, cwd=str(repo), capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode != 0:
        text = _read_text(changed.path) if changed.exists else ""
        return text + "\n" + _head_text(repo, before_rel), ""

    lines: list[str] = []
    line_nums: list[int] = []
    for line in proc.stdout.splitlines():
        if line.startswith("@@"):
            m = HUNK_LINE_RE.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                line_nums.extend(range(start, start + max(1, count)))
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            lines.append(line[1:])
    diff_text = "\n".join(lines)
    context_text = ""
    if changed.exists and Path(changed.rel_posix.lower()).suffix in (".kt", ".java") and line_nums:
        context_text = _enclosing_structural_context(_read_text(changed.path), line_nums)
    return diff_text, context_text



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
        diff_text, context_text = _diff_content(root, changed)
        before_rel = changed.old_rel_posix or rel
        full_text = (_read_text(changed.path) if changed.exists else "") + "\n" + _head_text(root, before_rel)
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
        if suffix in (".kt", ".kts") and ("@composable" in full_text.lower() or "androidx.compose" in full_text.lower()):
            _add(found, "COMPOSE_UI", rel, "COMPOSE_PATTERN")
        if suffix in (".kt", ".java") and not test_path:
            _add(found, "BUSINESS_LOGIC", rel, "SOURCE_CHANGE")
        if suffix in (".gradle", ".kts", ".toml", ".properties") or Path(lower).name in ("gradlew", "gradlew.bat"):
            _add(found, "BUILD_CONFIG", rel, "BUILD_FILE")
        if "androidmanifest.xml" in lower:
            surface = "MANIFEST_PERMISSION" if re.search(r"uses-permission|android:exported|provider|intent-filter", diff_text, re.I) else "BUILD_CONFIG"
            _add(found, surface, rel, "MANIFEST_CHANGE")
        if suffix in (".aidl", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".so"):
            _add(found, "NATIVE_CODE", rel, "NATIVE_OR_AIDL_CHANGE")
        if test_path:
            _add(found, "TEST_ONLY", rel, "TEST_CHANGE")
        if not test_path and re.search(r"\b(public|protected)\s+(class|interface|fun|static|abstract)\b", diff_text):
            _add(found, "PUBLIC_API", rel, "PUBLIC_DECLARATION")
        if "network_security_config" in lower and suffix == ".xml":
            _add(found, "SECURITY", rel, "NETWORK_SECURITY_CONFIG")
        if Path(lower).name in ("consumer-rules.pro", "proguard-rules.pro"):
            _add(found, "BUILD_CONFIG", rel, "PROGUARD_RULES")
        if Path(lower).name == "baseline-prof.txt":
            _add(found, "BUILD_CONFIG", rel, "BASELINE_PROFILE")
        for surface, pattern, reason in PATTERNS:

            if not test_path:
                if pattern.search(diff_text):
                    _add(found, surface, rel, reason)
                elif context_text and pattern.search(context_text):
                    _add(found, surface, rel, f"{reason}_CONTEXT")

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
