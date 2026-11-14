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

from _vnext_common import ValidationError


class AuthoritativeEvidenceError(ValidationError):
    """An active verification run could not persist its delivery authority."""


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
            missing_hashes = not (
                payload.get("delivery_snapshot_sha256")
                and payload.get("change_set_sha256")
                and payload.get("external_inputs_sha256")
            )
            if missing_hashes:
                from delivery_manifest import build_manifest
                from _repo_files import REPO

                cand_repo = directory.parent.parent.parent if results_dir_override is not None else REPO
                target_repo = cand_repo if (cand_repo / ".git").exists() else REPO
                manifest = build_manifest(target_repo)
                payload.setdefault("delivery_snapshot_sha256", manifest["delivery_snapshot_sha256"])
                payload.setdefault("change_set_sha256", manifest["change_set_sha256"])
                payload.setdefault("external_inputs_sha256", manifest["external_inputs_sha256"])
        except Exception as exc:
            if str(payload.get("status") or "").upper() == "PASS":
                payload["status"] = "FAIL"
                payload["exit_code"] = 1
                payload["detail"] = f"evidence identity unavailable: {type(exc).__name__}: {exc}"
        run_id = os.environ.get("HARNESS_RUN_ID", "").strip()
        # A shell override cannot redirect evidence away from the active run.
        # Explicit run IDs remain supported when no verification task is active.
        try:
            from _repo_files import REPO
            from _vnext_common import read_json, validate_id

            state_root = directory.parent
            active_path = state_root / "active-task.json"
            try:
                active = read_json(active_path)
            except ValidationError as exc:
                # Absence is normal for standalone diagnostics. An unreadable
                # existing pointer must never downgrade a rerun to diagnostics.
                if not isinstance(exc.__cause__, FileNotFoundError):
                    raise
                active = None
            if active is not None:
                task_id = validate_id(str(active.get("task_id") or ""), "task_id")
                plan = read_json(state_root / "tasks" / task_id / "plan.json")
                if plan.get("status") in ("VERIFYING", "READY_FOR_DELIVERY"):
                    current = read_json(state_root / "tasks" / task_id / "current-run.json")
                    current_run_id = validate_id(str(current.get("run_id") or ""), "run_id")
                    if run_id and run_id != current_run_id:
                        raise ValidationError("explicit verification run identity mismatch")
                    run_id = current_run_id
                    expected_run_id = (
                        plan.get("ready_run_id") or plan.get("verification_run_id")
                        if plan.get("status") == "READY_FOR_DELIVERY"
                        else plan.get("verification_run_id")
                    )
                    if expected_run_id and expected_run_id != run_id:
                        raise ValidationError("active verification run identity mismatch")
                    if (
                        plan.get("status") == "READY_FOR_DELIVERY"
                        and current.get("delivery_snapshot_sha256") == payload.get("delivery_snapshot_sha256")
                        and current.get("change_set_sha256")
                    ):
                        payload["change_set_sha256"] = current["change_set_sha256"]
        except Exception as exc:
            raise AuthoritativeEvidenceError("authoritative evidence run discovery failed") from exc
        if run_id and name != "device":
            from evidence_store import EvidenceStore

            snapshot = str(payload.get("delivery_snapshot_sha256") or "")
            change_set = str(payload.get("change_set_sha256") or "")
            task = str(payload.get("task") or "")
            evidence_name = "assemble" if task and "assemble" in task.lower() else name
            if task and "test" in task.lower() and evidence_name != "unit_tests":
                run_id = ""
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
            if run_id:
                try:
                    harness_version = os.environ.get("HARNESS_VERSION", "").strip()
                    if not harness_version:
                        version_file = directory.parent.parent / "VERSION"
                        harness_version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "unknown"
                    EvidenceStore(directory.parent).write(
                        snapshot=snapshot,
                        run_id=run_id,
                        name=evidence_name,
                        producer=producer,
                        harness_version=harness_version,
                        change_set=change_set,
                        status=str(payload.get("status") or "FAIL"),
                        evidence=payload,
                        allow_pass_retry=True,
                    )
                except Exception as exc:
                    raise AuthoritativeEvidenceError(
                        f"authoritative evidence write failed for {evidence_name}: {exc}"
                    ) from exc

        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, target)

        # Native Harness Orchestrator: track worker verification pass/fail streaks during IMPLEMENTING
        try:
            g_low = str(name or "").lower()
            st_up = str(payload.get("status") or "").upper()
            env_cls = str(payload.get("env_class") or "").upper()
            tracked_gate = (
                g_low in {"unit_tests", "preflight"}
                or "compile" in g_low
                or "lint" in g_low
                or "roborazzi" in g_low
            )
            if tracked_gate and st_up in {"PASS", "FAIL"} and env_cls != "ENV":
                s_root = directory.parent
                act_f = s_root / "active-task.json"
                if act_f.is_file():
                    from _vnext_common import read_json as _rj
                    act_tid = str((_rj(act_f) or {}).get("task_id") or "").strip()
                    if act_tid:
                        p_f = s_root / "tasks" / act_tid / "plan.json"
                        if p_f.is_file():
                            pl_doc = _rj(p_f)
                            pl_status = str(pl_doc.get("status") or "").upper()
                            if pl_status == "IMPLEMENTING" or (pl_status in {"VERIFYING", "READY_FOR_DELIVERY"} and st_up == "PASS"):
                                repo_root = s_root.parent.parent
                                from delegation_policy import (
                                    is_worker_verification_context_active,
                                    record_worker_verification_outcome,
                                )
                                phases = pl_doc.get("phases") or []
                                pidx = int(pl_doc.get("active_phase_index") or 0)
                                pid = str(phases[pidx].get("id") or "") if (phases and 0 <= pidx < len(phases)) else ""
                                if (
                                    (pl_status == "IMPLEMENTING" and is_worker_verification_context_active(repo_root, act_tid, pid))
                                    or (st_up == "PASS" and (g_low in {"unit_tests", "preflight"} or "compile" in g_low))
                                ):
                                    record_worker_verification_outcome(
                                        repo_root,
                                        passed=(st_up == "PASS"),
                                        gate_name=g_low,
                                        detail=str(payload.get("detail") or ""),
                                        task_id=act_tid,
                                        phase_id=pid,
                                        is_wave_boundary=False,
                                    )
        except (ImportError, OSError, ValueError, KeyError, TypeError, ValidationError):
            target = target

        return target
    except AuthoritativeEvidenceError:
        raise
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


def current_head_sha(repo: Path | None = None) -> str:
    try:
        from _repo_files import REPO

        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo or REPO),
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
