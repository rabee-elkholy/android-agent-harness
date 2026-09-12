"""Deterministically select and validate on-demand Android skills."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import canonical_sha256, sha256_file  # noqa: E402


SCHEMA_VERSION = 1
KERNEL_COMPATIBLE_MAJOR = 1
ROUTES = {
    "BUSINESS_LOGIC": ("android-harness", "test-driven-development"),
    "PUBLIC_API": ("android-harness", "test-driven-development"),
    "COMPOSE_UI": ("compose-inspector", "android-harness"),
    "XML_UI": ("android-harness",),
    "RESOURCE_UI": ("android-harness",),
    "LOCALIZATION": ("android-harness",),
    "COROUTINES": ("kotlin-coroutines-expert",),
    "TEST_ONLY": ("test-driven-development",),
    "ROOM_SCHEMA": ("android-harness", "test-driven-development"),
    "PERSISTENCE": ("android-harness",),
    "BUILD_CONFIG": ("gradle-build-optimizer",),
    "NATIVE_CODE": ("android-harness",),
    "DEVICE_API": ("android-harness",),
    "NETWORK": ("systematic-debugging", "android-harness"),
    "BILLING": ("android-security-billing",),
    "AUTH": ("android-security-billing",),
    "SECURITY": ("android-security-billing",),
    "SENSITIVE_DATA": ("android-security-billing",),
    "CRYPTO": ("android-security-billing",),
    "UNKNOWN": ("android-harness",),
}


def _metadata(skill_file: Path) -> dict[str, str | int]:
    version = "1.0.0"
    compatible_major = KERNEL_COMPATIBLE_MAJOR
    try:
        for line in skill_file.read_text(encoding="utf-8", errors="replace").splitlines()[:30]:
            lowered = line.lower().strip()
            if lowered.startswith("version:"):
                version = line.split(":", 1)[1].strip().strip('"\'')
            elif lowered.startswith("kernel-major:"):
                compatible_major = int(line.split(":", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return {"version": version, "kernel_major": compatible_major}


def route(skills_root: Path, surfaces: list[str], *, kernel_major: int = KERNEL_COMPATIBLE_MAJOR, task_kind: str = "FEATURE") -> dict:
    selected_set = {skill for surface in surfaces for skill in ROUTES.get(surface, ())}
    if str(task_kind or "").upper() == "BUG":
        selected_set.add("systematic-debugging")
    selected_ids = sorted(selected_set)
    selected: list[dict] = []
    errors: list[str] = []
    seen_paths: set[Path] = set()
    for skill_id in selected_ids:
        skill_file = skills_root / skill_id / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"missing mandatory skill: {skill_id}")
            continue
        resolved = skill_file.resolve()
        if resolved in seen_paths:
            errors.append(f"duplicate mandatory skill path: {skill_id}")
            continue
        seen_paths.add(resolved)
        meta = _metadata(skill_file)
        if int(meta["kernel_major"]) != kernel_major:
            errors.append(
                f"incompatible skill {skill_id}: kernel major {meta['kernel_major']} != {kernel_major}"
            )
            continue
        selected.append(
            {
                "id": skill_id,
                "version": str(meta["version"]),
                "sha256": sha256_file(skill_file),
                "path": skill_file.relative_to(skills_root.parent).as_posix(),
                "kernel_major": kernel_major,
            }
        )
    result = {
        "schema_version": SCHEMA_VERSION,
        "kernel_major": kernel_major,
        "surfaces": sorted(set(surfaces)),
        "skills": selected,
        "status": "BLOCKED" if errors else "PASS",
        "errors": errors,
    }
    result["routing_sha256"] = canonical_sha256(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", default=str(Path(__file__).resolve().parents[1] / "skills"))
    parser.add_argument("--surfaces", required=True, help="Comma-separated surface labels")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = route(Path(args.skills_root), [item.strip().upper() for item in args.surfaces.split(",") if item.strip()])
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"SKILL_ROUTING={result['status']}")
        for skill in result["skills"]:
            print(f"SKILL={skill['id']}@{skill['version']}:{skill['sha256'][:12]}")
        for error in result["errors"]:
            print(f"[FAIL] {error}", file=sys.stderr)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
