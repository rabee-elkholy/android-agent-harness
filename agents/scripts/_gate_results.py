"""Gate-result bridge into append-only v1 evidence.

The mutable ``results`` files are diagnostic compatibility mirrors only. When
a verification run is active, delivery authority is written to its immutable
``EvidenceStore`` directory; final verification never trusts "latest wins".
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
        payload = dict(data)
        try:
            from delivery_manifest import build_manifest
            from _repo_files import REPO

            manifest = build_manifest(REPO)
            payload.setdefault("delivery_snapshot_sha256", manifest["delivery_snapshot_sha256"])
            payload.setdefault("change_set_sha256", manifest["change_set_sha256"])
            payload.setdefault("external_inputs_sha256", manifest["external_inputs_sha256"])
        except Exception as exc:
            if str(payload.get("status") or "").upper() == "PASS":
                payload["status"] = "FAIL"
                payload["exit_code"] = 1
                payload["detail"] = f"evidence identity unavailable: {type(exc).__name__}: {exc}"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, target)

        run_id = os.environ.get("HARNESS_RUN_ID", "").strip()
        if not run_id:
            # Gates discover the one active verification run, removing fragile
            # shell-environment coupling from normal use.
            try:
                from _repo_files import REPO
                from _vnext_common import read_json

                state_root = directory.parent
                active = read_json(state_root / "active-task.json")
                task_id = str(active.get("task_id") or "")
                plan = read_json(state_root / "tasks" / task_id / "plan.json")
                current = read_json(state_root / "tasks" / task_id / "current-run.json")
                if plan.get("status") == "VERIFYING":
                    run_id = str(current.get("run_id") or "")
            except Exception:
                run_id = ""
        if run_id and name != "device":
            from evidence_store import EvidenceStore
            from _vnext_common import ValidationError

            snapshot = str(payload.get("delivery_snapshot_sha256") or "")
            change_set = str(payload.get("change_set_sha256") or "")
            task = str(payload.get("task") or "")
            evidence_name = "assemble" if task and "assemble" in task.lower() else name
            if task and "test" in task.lower() and evidence_name != "unit_tests":
                return target
            producer_defaults = {
                "assemble": "run_gradle_task",
                "preflight": "preflight_check",
                "localization": "check_strings",
                "room": "room_guard",
                "unit_tests": "run_tests_gate",
                "device_install": "run_device",
                "device_launch": "run_device",
            }
            producer = str(payload.get("producer") or producer_defaults.get(evidence_name) or evidence_name).replace(".py", "").replace("-", "_")
            harness_version = os.environ.get("HARNESS_VERSION", "").strip()
            if not harness_version:
                version_file = directory.parent.parent / "VERSION"
                harness_version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "unknown"
            try:
                EvidenceStore(directory.parent).write(
                    snapshot=snapshot,
                    run_id=run_id,
                    name=evidence_name,
                    producer=producer,
                    harness_version=harness_version,
                    change_set=change_set,
                    status=str(payload.get("status") or "FAIL"),
                    evidence=payload,
                )
            except ValidationError:
                return None
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
