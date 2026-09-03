"""Unified gate-result artifacts consumed by final_verdict.py.

Every delivery-gate script writes a small machine-readable result JSON into
<state>/results/<name>.json (atomic write, corruption-safe reads). The latest
run wins per gate name; Gradle results are keyed per task (gradle-<task>).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def results_dir() -> Path:
    override = os.environ.get("HARNESS_RESULTS_DIR")
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent
    return here.parent / "state" / "results"


def write_gate_result(
    name: str,
    data: dict,
    *,
    results_dir_override: Path | None = None,
) -> Path | None:
    directory = results_dir_override or results_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, target)
        return target
    except Exception:
        return None


def read_gate_result(
    name: str,
    *,
    results_dir_override: Path | None = None,
) -> dict | None:
    directory = results_dir_override or results_dir()
    try:
        path = directory / f"{name}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def sanitize_task(task: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", str(task).strip().strip(":")).strip("-")
    return cleaned.lower()[:80] or "gradle"


def gate_artifact_name(task: str) -> str:
    return f"gradle-{sanitize_task(task)}"


def current_head_sha() -> str:
    try:
        from _repo_files import REPO

        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        out = (proc.stdout or "").strip()
        return out if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", out) else ""
    except Exception:
        return ""
