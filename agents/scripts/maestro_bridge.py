"""First-class Maestro YAML flow execution & `phone_e2e` -> `.maestro/*.yaml` exporter.

Binds Maestro execution strictly to the verified physical device (`phone_e2e._bound_device`)
and `delivery_snapshot_sha256`, blocks destructive YAML commands (`clearState`, `clearKeychain`,
`uninstallApp`) unless explicitly authorized by the developer with `--proof-reference`, runs
automatic post-flow `LeakCanary` checks when configured, and exports successful `phone_e2e`
sessions into repeatable `.maestro/<flow>.yaml` regression suites.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _vnext_common import ValidationError, atomic_write_bytes, read_json, state_root, utc_now, validate_id  # noqa: E402

DESTRUCTIVE_MAESTRO_RE = re.compile(
    r"^\s*-\s*(?:clearState|clearKeychain|uninstallApp)\b|clearState\s*:\s*true",
    re.I | re.M,
)


def maestro_executable() -> str | None:
    env_bin = os.environ.get("HARNESS_MAESTRO_BIN", "").strip()
    if env_bin and Path(env_bin).is_file():
        return env_bin
    found = shutil.which("maestro")
    if found:
        return found
    home_cand = Path.home() / ".maestro" / "bin" / ("maestro.bat" if os.name == "nt" else "maestro")
    if home_cand.is_file():
        return str(home_cand)
    return None


def discover_flows(repo: Path) -> list[str]:
    flows: list[str] = []
    for folder in (".maestro", "maestro", "e2e/maestro"):
        root = repo / folder
        if root.is_dir():
            for ext in ("*.yaml", "*.yml"):
                for fp in sorted(root.rglob(ext)):
                    if fp.is_file() and fp.name.lower() not in {"config.yaml", "config.yml"}:
                        flows.append(fp.relative_to(repo).as_posix())
    return flows[:60]


def probe_capabilities(repo: Path) -> dict[str, Any]:
    exe = maestro_executable()
    flows = discover_flows(repo)
    return {
        "maestro_cli_available": bool(exe),
        "maestro_executable": exe or "",
        "flows": flows,
        "flow_count": len(flows),
    }


def validate_maestro_yaml_safety(
    flow_path: Path,
    *,
    allow_clear_state: bool = False,
    source: str = "",
    proof_reference: str = "",
) -> None:
    """Enforce zero-destructive device data rules on Maestro YAML flows."""
    if not flow_path.is_file():
        raise ValidationError(f"Maestro flow file not found: {flow_path}")
    text = flow_path.read_text(encoding="utf-8", errors="replace")
    # Strip YAML comments before checking destructive directives
    uncommented = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    )
    hit = DESTRUCTIVE_MAESTRO_RE.search(uncommented)
    if hit:
        if not (allow_clear_state and source == "conversation" and proof_reference.strip()):
            raise ValidationError(
                f"MAESTRO_DESTRUCTIVE_COMMAND_FORBIDDEN: Flow '{flow_path.name}' contains '{hit.group(0).strip()}', "
                "which clears logged-in user data or uninstalls the app. Remove `clearState`/`uninstallApp` from the YAML "
                "or obtain explicit developer authorization (`--allow-clear-state --source conversation --proof-reference \"<phrase>\"`)."
            )


def _yaml_quote(val: str) -> str:
    escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_maestro_yaml_from_session(session: dict[str, Any]) -> str:
    """Convert a recorded `phone_e2e.py` session into an idiomatic, non-destructive Maestro YAML flow."""
    app_id = str(session.get("application_id") or "com.example.app")
    task_id = str(session.get("task_id") or "task")
    lines = [
        f"appId: {app_id}",
        f"# Auto-exported from Android Agent Harness phone_e2e session (task: {task_id})",
        "---",
        "- launchApp:",
        "    stopApp: false",
    ]
    for item in session.get("actions") or []:
        if not isinstance(item, dict):
            continue
        act = str(item.get("action") or "")
        if act == "tap":
            tgt = item.get("target")
            if isinstance(tgt, dict):
                if tgt.get("resource_id"):
                    rid = str(tgt["resource_id"]).split("/")[-1]
                    lines.extend(["- tapOn:", f"    id: {_yaml_quote(rid)}"])
                elif tgt.get("text"):
                    lines.extend(["- tapOn:", f"    text: {_yaml_quote(str(tgt['text']))}"])
                elif tgt.get("desc"):
                    lines.extend(["- tapOn:", f"    text: {_yaml_quote(str(tgt['desc']))}"])
                elif "x" in tgt and "y" in tgt:
                    pt = f"{tgt['x']},{tgt['y']}"
                    lines.extend(["- tapOn:", f"    point: {_yaml_quote(pt)}"])
            elif isinstance(tgt, str) and tgt:
                lines.append(f"- tapOn: {_yaml_quote(tgt)}")
        elif act == "type":
            txt_val = item.get("text_preview")
            if isinstance(txt_val, str) and txt_val:
                lines.append(f"- inputText: {_yaml_quote(txt_val)}")
            else:
                lines.append('# Redacted/omitted text input — supply `${MAESTRO_INPUT_TEXT}` env variable if needed')
        elif act == "key":
            kname = str(item.get("name") or "").upper()
            if kname == "BACK":
                lines.append("- back")
            elif kname == "ENTER":
                lines.append("- pressKey: Enter")
        elif act == "swipe":
            direction = str(item.get("direction") or "up").upper()
            lines.extend(["- swipe:", f"    direction: {direction}"])
        elif act == "wait":
            q = item.get("query") if isinstance(item.get("query"), dict) else {}
            if q.get("text"):
                lines.extend(["- extendedWaitUntil:", "    visible:", f"      text: {_yaml_quote(str(q['text']))}", "    timeout: 5000"])
            elif q.get("resource_id"):
                rid = str(q["resource_id"]).split("/")[-1]
                lines.extend(["- extendedWaitUntil:", "    visible:", f"      id: {_yaml_quote(rid)}", "    timeout: 5000"])
            else:
                lines.append("- waitForAnimationToEnd")
        elif act == "restart":
            lines.extend([
                "- stopApp",
                "- launchApp:",
                "    stopApp: false",
            ])

    for scen in session.get("scenarios") or []:
        if isinstance(scen, dict) and scen.get("status") == "PASS":
            lines.append(f"# Verified scenario {scen.get('id')}: {str(scen.get('title') or '')[:120]}")

    return "\n".join(lines) + "\n"


def _task_status(repo: Path, task_id: str) -> str:
    plan_file = state_root(repo) / "tasks" / validate_id(task_id, "task_id") / "plan.json"
    if not plan_file.is_file():
        return ""
    try:
        from _vnext_common import read_json
        return str(read_json(plan_file).get("status") or "").upper()
    except (OSError, ValueError, ValidationError):
        return ""


def _load_recorded_e2e_session(repo: Path, explicit_task_id: str | None) -> tuple[str, dict[str, Any]]:
    from _vnext_common import read_json
    tid = str(explicit_task_id or "").strip()
    if not tid:
        active_file = state_root(repo) / "active-task.json"
        if active_file.is_file():
            tid = str(read_json(active_file).get("task_id") or "").strip()
    if not tid:
        raise ValidationError("Pass `--task-id <id>` when no active task is open.")
    safe_tid = validate_id(tid, "task_id")
    tdir = state_root(repo) / "tasks" / safe_tid
    if not tdir.is_dir():
        raise ValidationError(f"Task '{safe_tid}' does not exist.")
    cand_runs: list[str] = []
    crun_file = tdir / "current-run.json"
    if crun_file.is_file():
        rid = str(read_json(crun_file).get("run_id") or "").strip()
        if rid:
            cand_runs.append(rid)
    plan_file = tdir / "plan.json"
    if plan_file.is_file():
        ready_rid = str(read_json(plan_file).get("ready_run_id") or "").strip()
        if ready_rid and ready_rid not in cand_runs:
            cand_runs.append(ready_rid)
    for rid in cand_runs:
        s_file = tdir / "e2e" / validate_id(rid, "run_id") / "session.json"
        if s_file.is_file():
            return safe_tid, read_json(s_file)
    e2e_root = tdir / "e2e"
    if e2e_root.is_dir():
        found = sorted(e2e_root.glob("*/session.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        if found:
            return safe_tid, read_json(found[0])
    raise ValidationError(f"No recorded phone E2E session found for task '{safe_tid}'.")


def cmd_export_e2e(repo: Path, args: argparse.Namespace) -> dict[str, Any]:
    task_id, session = _load_recorded_e2e_session(repo, args.task_id)
    safe_tid = validate_id(task_id, "task_id")
    yaml_text = render_maestro_yaml_from_session(session)
    status = _task_status(repo, task_id)
    snapshot_frozen = status in {"VERIFYING", "READY_FOR_DELIVERY"}

    if args.out:
        out_path = Path(args.out) if Path(args.out).is_absolute() else (repo / args.out)
        try:
            rel = out_path.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError as exc:
            raise ValidationError(f"Output path '{out_path}' must stay inside the repository.") from exc
        if snapshot_frozen and not rel.startswith(".agents/state/"):
            raise ValidationError(
                f"SNAPSHOT_FROZEN: Task '{task_id}' is in {status}; writing '{rel}' into the working tree "
                "would invalidate the frozen delivery snapshot and verification evidence. Omit `--out` to stage "
                f"under `.agents/state/tasks/{safe_tid}/maestro/{safe_tid}.yaml`, or export to `.maestro/` after `task deliver`."
            )
    elif snapshot_frozen:
        out_path = state_root(repo) / "tasks" / safe_tid / "maestro" / f"{safe_tid}.yaml"
        rel = out_path.resolve().relative_to(repo.resolve()).as_posix()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(out_path, yaml_text.encode("utf-8"))
        return {
            "status": "STAGED_IN_TASK_STATE",
            "task_id": task_id,
            "task_status": status,
            "flow_file": rel,
            "repo_target": f".maestro/{safe_tid}.yaml",
            "flow_sha256": hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()[:12],
            "action_count": len(session.get("actions") or []),
            "detail": (
                f"Staged inside `{rel}` so the frozen {status} delivery snapshot stays valid. "
                f"Run `python .agents/harness.py maestro export-e2e --task-id {safe_tid}` after `task deliver` to save to `.maestro/{safe_tid}.yaml`."
            ),
        }
    else:
        out_path = repo / ".maestro" / f"{safe_tid}.yaml"
        rel = out_path.resolve().relative_to(repo.resolve()).as_posix()

    from pre_tool_safety import check_write_safety
    safety = check_write_safety(repo, rel, tool_name="maestro_export")
    if safety.get("decision") != "ALLOW":
        raise ValidationError(f"PROTECTED_PATH: {safety.get('reason')}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(out_path, yaml_text.encode("utf-8"))
    return {
        "status": "EXPORTED",
        "task_id": task_id,
        "flow_file": rel,
        "flow_sha256": hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()[:12],
        "action_count": len(session.get("actions") or []),
    }


def cmd_run(repo: Path, args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from phone_e2e import _active_task, _bound_device
    task_id = _active_task(repo, args.task_id)
    raw_flow = Path(args.flow)
    flow_path = (raw_flow if raw_flow.is_absolute() else (repo / raw_flow)).resolve()
    if not flow_path.is_file() and not raw_flow.is_absolute():
        safe_tid = validate_id(task_id, "task_id")
        staged_cand = (state_root(repo) / "tasks" / safe_tid / "maestro" / raw_flow.name).resolve()
        if not staged_cand.suffix:
            staged_cand = staged_cand.with_suffix(".yaml")
        if staged_cand.is_file():
            flow_path = staged_cand
    validate_maestro_yaml_safety(
        flow_path,
        allow_clear_state=bool(args.allow_clear_state),
        source=str(args.source or ""),
        proof_reference=str(args.proof_reference or ""),
    )
    exe = maestro_executable()
    if not exe:
        raise ValidationError("ENV_BLOCKED: `maestro` CLI is not installed on PATH or ~/.maestro/bin/maestro.")

    _, current, serial, app = _bound_device(repo, task_id)
    out_dir = state_root(repo) / "tasks" / task_id / "maestro" / validate_id(str(current["run_id"]), "run_id")
    out_dir.mkdir(parents=True, exist_ok=True)
    junit_out = out_dir / f"{flow_path.stem}-junit.xml"

    proc = subprocess.run(
        [exe, "--device", serial, "test", str(flow_path), "--format", "junit", "--output", str(junit_out)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )

    from static_health_bridge import check_device_leaks
    leak_res = check_device_leaks(repo, serial=serial, application_id=str(app.get("application_id") or ""))

    flow_rel = flow_path.relative_to(repo).as_posix() if flow_path.is_relative_to(repo) else flow_path.name
    ok = (proc.returncode == 0) and (leak_res.get("status") != "LEAK_DETECTED")
    payload = {
        "schema_version": 1,
        "producer": "maestro_bridge",
        "status": "PASS" if ok else "FAIL",
        "exit_code": 0 if ok else 1,
        "git_sha": current_head_sha(repo),
        "task_id": task_id,
        "run_id": current["run_id"],
        "delivery_snapshot_sha256": current["delivery_snapshot_sha256"],
        "serial_sha256": hashlib.sha256(serial.encode("utf-8")).hexdigest(),
        "flow": flow_rel,
        "flow_sha256": hashlib.sha256(flow_path.read_bytes()).hexdigest(),
        "junit_report": str(junit_out) if junit_out.is_file() else "",
        "leak_check": leak_res,
        "recorded_at": utc_now(),
        "detail": (
            f"Maestro flow '{flow_rel}' passed on bound device ({leak_res.get('status')})"
            if ok else f"Maestro flow '{flow_rel}' failed (rc={proc.returncode}, leak={leak_res.get('status')})"
        ),
    }
    write_gate_result("maestro_e2e", payload)
    return (0 if ok else 1), payload


def walkthrough_maestro_hint(repo: Path, task_id: str) -> str:
    """Return optional walkthrough choice line when Maestro CLI or repo `.maestro` flows exist."""
    caps = probe_capabilities(repo)
    if not caps["maestro_cli_available"] and not caps["flows"]:
        return ""
    if caps["flows"]:
        sample = caps["flows"][0]
        return (
            f"[MAESTRO] Detected Maestro support ({caps['flow_count']} flow(s), e.g. `{sample}`). "
            f"Include an optional choice in `ask_question`: 'Run Maestro flow on phone' -> "
            f"`python .agents/harness.py maestro run --flow {sample} --task-id {task_id}`."
        )
    return (
        f"[MAESTRO] `maestro` CLI detected. After a successful `e2e` run, you can offer to save it as a repeatable YAML flow via "
        f"`python .agents/harness.py maestro export-e2e --task-id {task_id}`."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capabilities", "list", "run", "export-e2e"))
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("HARNESS_REPO") or Path(__file__).resolve().parents[2]))
    parser.add_argument("--task-id", "--task", dest="task_id")
    parser.add_argument("--flow", help="Path to `.maestro/<name>.yaml` flow for `run`")
    parser.add_argument("--out", help="Output `.yaml` path for `export-e2e`")
    parser.add_argument("--allow-clear-state", action="store_true")
    parser.add_argument("--source", default="")
    parser.add_argument("--proof-reference", dest="proof_reference", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.action == "run" and not args.flow:
        parser.error("run requires --flow <path.yaml>")

    repo = args.repo.resolve()
    try:
        if args.action in {"capabilities", "list"}:
            print(json.dumps(probe_capabilities(repo), ensure_ascii=False, indent=2))
            return 0
        if args.action == "export-e2e":
            res = cmd_export_e2e(repo, args)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        rc, res = cmd_run(repo, args)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return rc
    except (OSError, ValueError, subprocess.TimeoutExpired, ValidationError) as exc:
        msg = str(exc)
        is_env = msg.startswith("ENV_BLOCKED")
        print(json.dumps({"status": "ENV_BLOCKED" if is_env else "ERROR", "reason": msg}, ensure_ascii=False))
        return 30 if is_env else 1


if __name__ == "__main__":
    raise SystemExit(main())
