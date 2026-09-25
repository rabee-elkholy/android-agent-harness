"""Deterministic check for components a task newly exports without a permission.

A receiver, service or provider with android:exported="true" and no permission can be
invoked by any app on the device. A task that adds one, or turns an existing one into
one, fails preflight unless the element opts out with the Android Lint id for that
component (tools:ignore="ExportedReceiver", "ExportedService" or
"ExportedContentProvider"), which keeps the decision visible in the reviewed diff.
"""
from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID = "{http://schemas.android.com/apk/res/android}"
TOOLS = "{http://schemas.android.com/tools}"
LINT_IDS = {"receiver": "ExportedReceiver", "service": "ExportedService", "provider": "ExportedContentProvider"}
PERMISSION_ATTRS = ("permission", "readPermission", "writePermission")


def open_components(text: str) -> dict[tuple[str, str], bool]:
    """(tag, name) -> True when the component is exported without any permission."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    result: dict[tuple[str, str], bool] = {}
    for tag, lint_id in LINT_IDS.items():
        for element in root.iter(tag):
            name = element.get(f"{ANDROID}name") or ""
            exported = (element.get(f"{ANDROID}exported") or "").strip().lower() == "true"
            permitted = any(element.get(f"{ANDROID}{attr}") for attr in PERMISSION_ATTRS)
            ignored = lint_id in {item.strip() for item in (element.get(f"{TOOLS}ignore") or "").split(",")}
            result[(tag, name)] = exported and not permitted and not ignored
    return result


def _head_text(repo: Path, rel: str) -> str:
    proc = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(repo), capture_output=True, text=True, check=False)
    return proc.stdout if proc.returncode == 0 else ""


def newly_open_components(repo: Path, paths: list[str]) -> list[str]:
    findings: list[str] = []
    for rel in sorted(p for p in paths if p.endswith("AndroidManifest.xml")):
        path = repo / rel
        if not path.is_file():
            continue
        now = open_components(path.read_text(encoding="utf-8", errors="replace"))
        before = open_components(_head_text(repo, rel))
        for (tag, name), is_open in sorted(now.items()):
            if is_open and not before.get((tag, name)):
                findings.append(f"{rel}: <{tag} android:name=\"{name}\">")
    return findings


def check(repo: Path, paths: list[str]) -> tuple[bool, str]:
    findings = newly_open_components(repo, paths)
    if not findings:
        return True, "no newly exported component without a permission"
    return False, (
        "EXPORTED_COMPONENT_WITHOUT_PERMISSION: " + "; ".join(findings)
        + ". Any app can invoke these. Add android:permission (a signature-level permission for internal callers), "
        "set android:exported=\"false\", or, if public access is intended, record that decision on the element with "
        "tools:ignore=\"" + "/".join(LINT_IDS.values()) + "\" (the matching id) so reviewers see it in the diff."
    )
