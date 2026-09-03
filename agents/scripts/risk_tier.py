"""Risk Tier Classification and Approval Verification.

Usage:
  python .agents/scripts/risk_tier.py [--json]

Classifies the current working-tree diff into one of four Risk Tiers:
  CRITICAL : Billing, In-App Purchase, Security/Crypto/KeyStore, Proguard rules.
  HIGH     : Room Database / Migrations, AndroidManifest permissions / exported components, Gradle build scripts.
  MEDIUM   : Standard application code (ViewModels, UseCases, Repositories, Activities, Fragments, Compose screens).
  LOW      : Docs, strings/translations, UI layout dimensions/drawables, comments-only diffs.

Fail-safe rules:
- High-risk file types have a file-level floor: comments-only changes in a billing file remain CRITICAL.
- Unknown or ambiguous changes default to MEDIUM.
- HIGH and CRITICAL risk tiers require explicit human approval via approve_risk.py before preflight can pass.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_state import state_path, tree_code_fingerprint  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _repo_files import REPO, changed_paths  # noqa: E402
from fast_kt_lint import get_modified_lines_map  # noqa: E402

TIER_CRITICAL = "CRITICAL"
TIER_HIGH = "HIGH"
TIER_MEDIUM = "MEDIUM"
TIER_LOW = "LOW"

_TIER_ORDER = {
    TIER_LOW: 1,
    TIER_MEDIUM: 2,
    TIER_HIGH: 3,
    TIER_CRITICAL: 4,
}

# CRITICAL file patterns
CRITICAL_PATH_PATTERNS = [
    re.compile(r"[a-zA-Z0-9_-]*(?:billing|purchase|subscription|checkout|payment)[a-zA-Z0-9_-]*\.(?:kt|java)$", re.IGNORECASE),
    re.compile(r"[a-zA-Z0-9_-]*(?:crypto|keystore|security)[a-zA-Z0-9_-]*\.(?:kt|java)$", re.IGNORECASE),
    re.compile(r"(?:proguard-rules\.pro|consumer-rules\.pro|proguard\.cfg)$", re.IGNORECASE),
    re.compile(r"(?:^|/)(?:google-services\.json|[a-zA-Z0-9_.-]*\.(?:keystore|jks|key))$", re.IGNORECASE),
]

CRITICAL_CODE_PATTERNS = [
    re.compile(r"\b(?:BillingClient|PurchasesUpdatedListener|BillingFlowParams|consumeAsync|acknowledgePurchase)\b"),
    re.compile(r"\b(?:KeyStore|Cipher\.getInstance|SecretKey|KeyGenerator|KeyAgreement)\b"),
    re.compile(r"\b(?:TrustManager|HostnameVerifier|NetworkSecurityConfig)\b"),
]

# HIGH file patterns (build infrastructure & DB schema files)
HIGH_PATH_PATTERNS = [
    re.compile(r"(?:^|/)(?:build\.gradle|build\.gradle\.kts|settings\.gradle|settings\.gradle\.kts)$", re.IGNORECASE),
    re.compile(r"(?:^|/)gradle/libs\.versions\.toml$", re.IGNORECASE),
    re.compile(r"(?:^|/)(?:gradle\.properties|local\.properties)$", re.IGNORECASE),
    re.compile(r"(?:^|/)schemas/.*\.json$", re.IGNORECASE),
]

HIGH_CODE_PATTERNS = [
    re.compile(r"@(?:Database|Entity|TypeConverters|Dao|ProvidedTypeConverter)\b"),
    re.compile(r"\b(?:Migration|AutoMigration|fallbackToDestructiveMigration)\b"),
    re.compile(r"<(?:uses-permission|permission|permission-group|permission-tree)\b"),
    re.compile(r"android:exported\s*=\s*\"(?:true|false)\""),
]

# LOW file patterns
LOW_DOC_EXTENSIONS = {".md", ".txt", ".rst", ".adoc", ".json"}
LOW_RES_NAMES = {"strings.xml", "plurals.xml"}


def max_tier(t1: str, t2: str) -> str:
    return t1 if _TIER_ORDER.get(t1, 2) >= _TIER_ORDER.get(t2, 2) else t2


def _is_doc_or_metadata_file(rel_path: str) -> bool:
    path = Path(rel_path)
    lower_name = path.name.lower()
    if lower_name in ("google-services.json", "secrets.json", "credentials.json"):
        return False
    if lower_name in ("license", "notice", "version"):
        return True
    if path.suffix.lower() in LOW_DOC_EXTENSIONS:
        return True
    if rel_path.startswith(".github/") or rel_path.startswith("docs/"):
        return True
    return False


def _is_string_resource_file(rel_path: str) -> bool:
    path = Path(rel_path)
    if path.suffix.lower() == ".xml" and path.name.lower() in LOW_RES_NAMES:
        return True
    if "/values" in f"/{rel_path}" and path.suffix.lower() == ".xml":
        return True
    return False


def _is_comment_or_whitespace_only(lines: list[str]) -> bool:
    """True if all given line strings are empty or comments."""
    in_block = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if in_block:
            if "*/" in stripped:
                in_block = False
                remainder = stripped.split("*/", 1)[1].strip()
                if remainder and not remainder.startswith("//"):
                    return False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block = True
            continue
        if stripped.startswith("//"):
            continue
        if stripped.startswith("@Preview"):
            continue
        return False
    return not in_block


def classify_file_risk(path: Path, repo: Path, modified_lines: set[int] | None = None) -> tuple[str, list[str]]:
    """Classify risk for a single file."""
    try:
        rel = path.relative_to(repo).as_posix()
    except ValueError:
        rel = str(path).replace("\\", "/")

    reasons: list[str] = []

    # Check CRITICAL path matches (file-level floor)
    for pat in CRITICAL_PATH_PATTERNS:
        if pat.search(rel):
            reasons.append(f"critical path match: {rel}")
            return TIER_CRITICAL, reasons

    # Documentation and metadata files are LOW risk (do not match code patterns inside markdown prose)
    if _is_doc_or_metadata_file(rel):
        reasons.append(f"documentation/metadata: {rel}")
        return TIER_LOW, reasons

    # String resources are LOW risk
    if _is_string_resource_file(rel):
        reasons.append(f"strings/localization resource: {rel}")
        return TIER_LOW, reasons

    # Read file content if accessible
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        content = ""
    lines = content.splitlines()

    # Determine modified lines text
    if modified_lines is not None:
        mod_line_texts = [lines[i - 1] for i in modified_lines if 0 < i <= len(lines)]
    else:
        mod_line_texts = lines

    # Code pattern checks apply only to application code and build scripts
    is_code_file = path.suffix.lower() in (".kt", ".java", ".xml", ".kts", ".gradle", ".pro", ".aidl")
    combined_mod_text = "\n".join(mod_line_texts)

    if is_code_file:
        # Check CRITICAL code patterns
        for pat in CRITICAL_CODE_PATTERNS:
            m = pat.search(combined_mod_text)
            if m:
                reasons.append(f"critical code pattern '{m.group(0)}' in {rel}")
                return TIER_CRITICAL, reasons

    # Check HIGH path matches
    for pat in HIGH_PATH_PATTERNS:
        if pat.search(rel):
            reasons.append(f"high-risk configuration/manifest path: {rel}")
            return TIER_HIGH, reasons

    if is_code_file:
        # Check HIGH code patterns
        for pat in HIGH_CODE_PATTERNS:
            m = pat.search(combined_mod_text)
            if m:
                reasons.append(f"high-risk pattern '{m.group(0)}' in {rel}")
                return TIER_HIGH, reasons

    # Check if comments-only diff in Kotlin/Java/XML
    if path.suffix.lower() in (".kt", ".java", ".xml", ".kts"):
        if mod_line_texts and _is_comment_or_whitespace_only(mod_line_texts):
            reasons.append(f"comments/whitespace only: {rel}")
            return TIER_LOW, reasons
        reasons.append(f"application code modification: {rel}")
        return TIER_MEDIUM, reasons

    # Other files default to LOW or MEDIUM
    if path.suffix.lower() in (".png", ".svg", ".webp", ".xml"):
        reasons.append(f"drawable/resource asset: {rel}")
        return TIER_LOW, reasons

    reasons.append(f"standard change: {rel}")
    return TIER_MEDIUM, reasons


def classify_working_tree_risk(
    repo: Path | None = None,
    files: list[Path] | None = None,
) -> tuple[str, list[str]]:
    """Classify the entire working-tree diff into a single aggregated risk tier."""
    r = repo or REPO
    target_files = files if files is not None else changed_paths()
    if not target_files:
        return TIER_LOW, ["clean working tree (no changes)"]

    try:
        lines_map = get_modified_lines_map(r, target_files)
    except Exception:
        lines_map = {f: None for f in target_files}

    current_tier = TIER_LOW
    all_reasons: list[str] = []

    for f in target_files:
        f_tier, f_reasons = classify_file_risk(f, r, lines_map.get(f))
        all_reasons.extend(f_reasons)
        current_tier = max_tier(current_tier, f_tier)

    return current_tier, all_reasons


def risk_approval_path(repo: Path | None = None) -> Path:
    return state_path().with_name("risk_approval.json")


def load_risk_approval(repo: Path | None = None) -> dict | None:
    path = risk_approval_path(repo)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def check_risk_approval(repo: Path | None = None) -> tuple[bool, str, str]:
    """Check if the current working tree risk tier is approved by the developer.

    Returns:
      (is_approved, tier, detail_message)
    """
    r = repo or REPO
    tier, reasons = classify_working_tree_risk(r)
    if tier in (TIER_LOW, TIER_MEDIUM):
        return True, tier, f"Risk tier {tier} does not require developer approval."

    approval = load_risk_approval(r)
    if not approval:
        return False, tier, (
            f"Risk tier is {tier} ({'; '.join(reasons[:3])}). "
            "Developer approval required: prompt developer via ask_question modal in chat, then run 'python .agents/scripts/approve_risk.py --approve'."
        )

    current_fp = tree_code_fingerprint(r) or ""
    approved_fp = str(approval.get("tree_fingerprint") or "")
    if current_fp != approved_fp:
        return False, tier, (
            f"Risk approval is STALE: code changes occurred after approval "
            f"(approved fp: {approved_fp[:8]}, current fp: {current_fp[:8]}). "
            "Re-prompt developer or run 'python .agents/scripts/approve_risk.py --approve'."
        )

    approved_tier = str(approval.get("tier") or "")
    if _TIER_ORDER.get(approved_tier, 0) < _TIER_ORDER.get(tier, 0):
        return False, tier, (
            f"Risk tier increased to {tier} but approval was for {approved_tier}. "
            "Re-prompt developer or run 'python .agents/scripts/approve_risk.py --approve'."
        )

    return True, tier, f"Risk tier {tier} approved by developer at {approval.get('approved_at')}."


def write_risk_approval(
    tier: str,
    fingerprint: str,
    repo: Path | None = None,
    approved_by: str = "developer",
) -> Path | None:
    target = risk_approval_path(repo)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 1,
            "tier": tier,
            "tree_fingerprint": fingerprint,
            "approved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "approved_by": approved_by,
        }
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, target)
        return target
    except Exception:
        return None


def main(argv=None) -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description="Classify working-tree diff risk tier")
    parser.add_argument("--json", action="store_true", help="Output risk assessment in JSON format")
    args = parser.parse_args(argv)

    tier, reasons = classify_working_tree_risk(REPO)
    fp = tree_code_fingerprint(REPO) or ""
    is_approved, _, approval_msg = check_risk_approval(REPO)

    if args.json:
        payload = {
            "tier": tier,
            "tree_fingerprint": fp,
            "reasons": reasons,
            "is_approved": is_approved,
            "approval_detail": approval_msg,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    live_print(f"[*] Risk Tier: {tier}")
    live_print(f"    Tree Fingerprint: {fp[:12] if fp else '(clean)'}")
    if reasons:
        live_print("    Identified factors:")
        for r in reasons[:10]:
            live_print(f"      - {r}")
        if len(reasons) > 10:
            live_print(f"      ... and {len(reasons) - 10} more")
    live_print(f"[*] Approval Status: {'APPROVED' if is_approved else 'REQUIRES APPROVAL'}")
    live_print(f"    {approval_msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
