"""Resolve and hash one deterministic installable APK artifact set."""
from __future__ import annotations

import json
import re
from pathlib import Path

from _vnext_common import HarnessError, canonical_sha256, sha256_file


SCHEMA_VERSION = 1


def _task_parts(task: str) -> tuple[str, str]:
    normalized = str(task).strip()
    match = re.fullmatch(r"(?P<module>(?::[^:]+)*):assemble(?P<variant>[A-Za-z0-9_]+)", normalized)
    if not match:
        raise HarnessError(f"cannot derive module and variant from assemble task: {task}")
    module = match.group("module").lstrip(":").replace(":", "/")
    return module, match.group("variant")


def _metadata_candidates(repo: Path, module: str, variant: str) -> list[Path]:
    output_root = repo / module / "build" / "outputs" / "apk"
    if not output_root.is_dir():
        return []
    matched: list[Path] = []
    for metadata in output_root.rglob("output-metadata.json"):
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        recorded_variant = str(payload.get("variantName") or "")
        if recorded_variant and recorded_variant.lower() != variant.lower():
            continue
        for element in payload.get("elements") or []:
            if not isinstance(element, dict):
                continue
            output_file = str(element.get("outputFile") or "").strip()
            if not output_file:
                continue
            apk = (metadata.parent / output_file).resolve()
            if apk.is_file() and apk.suffix.lower() == ".apk":
                matched.append(apk)
    return sorted(set(matched), key=lambda item: item.as_posix())


def resolve_artifacts(repo: Path, task: str, configured_apk: str | None = None) -> list[Path]:
    root = repo.resolve()
    module, variant = _task_parts(task)
    candidates = _metadata_candidates(root, module, variant)
    if candidates:
        return candidates
    if configured_apk:
        configured = (root / configured_apk).resolve()
        if configured.is_file():
            return [configured]
    output_root = root / module / "build" / "outputs" / "apk"
    fallback = [
        item.resolve()
        for item in output_root.rglob("*.apk")
        if item.is_file()
        and not item.name.endswith("-androidTest.apk")
        and variant.lower() in item.as_posix().lower().replace("-", "")
    ] if output_root.is_dir() else []
    fallback = sorted(set(fallback), key=lambda item: item.as_posix())
    if len(fallback) == 1:
        return fallback
    if not fallback:
        raise HarnessError(f"no APK output resolved for {task}")
    raise HarnessError(
        f"ambiguous APK outputs for {task}; output-metadata.json or explicit project configuration is required"
    )


def build_artifact_set(repo: Path, task: str, paths: list[Path], *, application_id: str = "") -> dict:
    root = repo.resolve()
    metadata_ids: set[str] = set()
    for path in paths:
        metadata = path.resolve().parent / "output-metadata.json"
        if metadata.is_file():
            try:
                candidate = str(json.loads(metadata.read_text(encoding="utf-8")).get("applicationId") or "").strip()
                if candidate:
                    metadata_ids.add(candidate)
            except (OSError, json.JSONDecodeError):
                pass
    if len(metadata_ids) > 1:
        raise HarnessError("APK outputs disagree on applicationId")
    effective_application_id = next(iter(metadata_ids), application_id)
    members: list[dict[str, str | int]] = []
    for path in sorted({item.resolve() for item in paths}, key=lambda item: item.as_posix()):
        if not path.is_file() or path.suffix.lower() != ".apk":
            raise HarnessError(f"installable artifact is not an APK file: {path}")
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise HarnessError(f"APK output escapes repository: {path}") from exc
        members.append({"path": rel, "sha256": sha256_file(path), "size": path.stat().st_size})
    if not members:
        raise HarnessError("installable artifact set is empty")
    identity = {
        "task": task,
        "application_id": effective_application_id,
        "members": members,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        **identity,
        "artifact_set_sha256": canonical_sha256(identity),
    }


def verify_artifact_set(repo: Path, artifact_set: dict) -> list[Path]:
    identity = {
        "task": artifact_set.get("task"),
        "application_id": artifact_set.get("application_id") or "",
        "members": artifact_set.get("members") or [],
    }
    if canonical_sha256(identity) != artifact_set.get("artifact_set_sha256"):
        raise HarnessError("artifact-set identity mismatch")
    paths: list[Path] = []
    root = repo.resolve()
    for member in identity["members"]:
        path = (root / str(member.get("path") or "")).resolve()
        if root != path and root not in path.parents:
            raise HarnessError("artifact-set path escapes repository")
        if not path.is_file() or sha256_file(path) != member.get("sha256"):
            raise HarnessError(f"artifact-set member is missing or changed: {member.get('path')}")
        paths.append(path)
    return paths
