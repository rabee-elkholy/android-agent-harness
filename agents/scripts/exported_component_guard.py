"""Deterministic check for components a task newly exports without a permission.

A receiver, service or provider with android:exported="true" and no permission can be
invoked by any app on the device. A task that adds one, or turns an existing one into
one, fails preflight until it gets a permission, stops being exported, or the developer
accepts the public exposure from their own terminal:

    python .agents/scripts/exported_component_guard.py --accept <android:name> \
        --source developer_terminal --proof-reference "<why it must be public>"

The acceptance is stored with the active task. tools:ignore="ExportedReceiver" (and the
service/provider ids) only silences Android Lint; it is not a waiver, because the agent
could add it to the diff on its own (certification N7). The safety hook denies the
acceptance command to agents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ANDROID = "{http://schemas.android.com/apk/res/android}"
COMPONENT_TAGS = ("receiver", "service", "provider")
PERMISSION_ATTRS = ("permission", "readPermission", "writePermission")
ACCEPTANCE_FILE = "exported-components-accepted.json"


def open_components(text: str) -> dict[tuple[str, str], bool]:
    """(tag, name) -> True when the component is exported without any permission."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    result: dict[tuple[str, str], bool] = {}
    for tag in COMPONENT_TAGS:
        for element in root.iter(tag):
            name = element.get(f"{ANDROID}name") or ""
            exported = (element.get(f"{ANDROID}exported") or "").strip().lower() == "true"
            permitted = any(element.get(f"{ANDROID}{attr}") for attr in PERMISSION_ATTRS)
            result[(tag, name)] = exported and not permitted
    return result


def _head_text(repo: Path, rel: str) -> str:
    proc = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(repo), capture_output=True, text=True, check=False)
    return proc.stdout if proc.returncode == 0 else ""


def newly_open_components(repo: Path, paths: list[str], accepted: set[str] | None = None) -> list[str]:
    findings: list[str] = []
    for rel in sorted(p for p in paths if p.endswith("AndroidManifest.xml")):
        path = repo / rel
        if not path.is_file():
            continue
        now = open_components(path.read_text(encoding="utf-8", errors="replace"))
        before = open_components(_head_text(repo, rel))
        for (tag, name), is_open in sorted(now.items()):
            if is_open and not before.get((tag, name)) and name not in (accepted or set()):
                findings.append(f"{rel}: <{tag} android:name=\"{name}\">")
    return findings


def accepted_names(task_directory: Path) -> set[str]:
    path = task_directory / ACCEPTANCE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {
        str(item.get("name"))
        for item in data.get("accepted") or []
        if isinstance(item, dict) and item.get("source") == "developer_terminal" and item.get("name")
    }


def record_acceptance(task_directory: Path, names: list[str], *, source: str, proof_reference: str) -> None:
    if source != "developer_terminal":
        raise ValueError("public exposure of an exported component is accepted only with --source developer_terminal")
    if not proof_reference.strip():
        raise ValueError("--proof-reference must say why the component must be public")
    path = task_directory / ACCEPTANCE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"schema_version": 1, "accepted": []}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proof_sha = hashlib.sha256(proof_reference.encode("utf-8")).hexdigest()
    for name in names:
        data["accepted"].append({"name": name, "source": source, "proof_reference_sha256": proof_sha, "accepted_at": now})
    task_directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _active_task_directory(repo: Path) -> Path | None:
    try:
        from mutation_guard import active_plan
        from workflow import task_dir
        task_id = str(active_plan(repo).get("task_id") or "")
        return task_dir(repo, task_id) if task_id else None
    except Exception:
        return None


def check(repo: Path, paths: list[str], accepted: set[str] | None = None) -> tuple[bool, str]:
    if accepted is None:
        directory = _active_task_directory(repo)
        accepted = accepted_names(directory) if directory else set()
    findings = newly_open_components(repo, paths, accepted)
    if not findings:
        return True, "no newly exported component without a permission"
    return False, (
        "EXPORTED_COMPONENT_WITHOUT_PERMISSION: " + "; ".join(findings)
        + ". Any app can invoke these. Add android:permission (a signature-level permission for internal callers) "
        "or set android:exported=\"false\". If public access is intended, that is the developer's decision: stop and ask "
        "the developer to run, in their own terminal, `python .agents/scripts/exported_component_guard.py --accept "
        "<android:name> --source developer_terminal --proof-reference \"<why it must be public>\"`. The agent must not "
        "run it, and tools:ignore does not waive this check."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Developer acceptance of a publicly exported component")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--accept", action="append", required=True, help="android:name of the component, e.g. .RefreshReceiver")
    parser.add_argument("--source", required=True)
    parser.add_argument("--proof-reference", required=True)
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    directory = _active_task_directory(repo)
    if directory is None:
        print("[FAIL] no active task to record the acceptance for", file=sys.stderr)
        return 1
    try:
        record_acceptance(directory, args.accept, source=args.source, proof_reference=args.proof_reference)
    except ValueError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"[OK] Public exposure accepted by the developer for: {', '.join(args.accept)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
