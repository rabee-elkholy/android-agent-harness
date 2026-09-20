"""Fast Architecture Drift Verification Engine.

Conservative, deterministic enforcement of approved task architecture contracts
during Fast Preflight and standalone CLI checks. Detects unauthorized family transitions
without LLM calls, using conservative deterministic checks designed to minimize false positives,
and with full support for compatibility bridges in NEW mode.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import REPO, changed_paths
from _vnext_common import read_json
from project_context import _safe_read


def _lookup_family(repo: Path, family_id: str | None) -> dict[str, Any] | None:
    if not family_id:
        return None
    facts_file = repo / ".agents" / "project-context" / "project-facts.json"
    if not facts_file.is_file():
        return None
    try:
        data = json.loads(facts_file.read_text(encoding="utf-8"))
        arch = (data.get("facts") or data).get("architecture") or {}
        for fam in arch.get("families") or []:
            if fam.get("id") == family_id:
                return fam
    except Exception:
        pass
    return None


def check_architecture_drift(
    repo: Path,
    contract: dict[str, Any] | None,
    target_family: dict[str, Any] | None = None,
    task_id: str | None = None,
    task_changes: list | None = None,
) -> tuple[bool, str, list[str]]:
    """Checks the working tree against the approved architecture contract.

    Returns:
      (passed: bool, message: str, violations: list[str])
    """
    if not contract:
        return True, "No architecture contract bound; check exempted.", []

    # Fail closed on corrupted contract hash if modern contract specifies one
    if "contract_sha256" in contract:
        from architecture_resolver import compute_contract_hash
        expected_hash = compute_contract_hash(contract)
        if contract.get("contract_sha256") != expected_hash:
            return False, "ARCHITECTURE_DRIFT: architecture contract hash is invalid or corrupted", ["contract_sha256 mismatch"]

    mode = contract.get("mode", "PRESERVE")
    target_scope = contract.get("target_scope", "")
    violations: list[str] = []

    def _extract_drift_path(c: Any) -> str:
        if isinstance(c, dict):
            return str(c.get("path") or "")
        return str(c or "")

    # Resolve target paths using task delta if available, otherwise changed_paths
    if task_changes is not None:
        paths_set = {repo / _extract_drift_path(c) for c in task_changes if _extract_drift_path(c)}
        modified_paths = [p for p in paths_set if p.is_file()]
    elif task_id:
        try:
            from delivery_manifest import build_task_manifest, load_task_baseline
            base_data = load_task_baseline(repo, task_id)
            plan_exp = None
            try:
                from workflow import _load_plan
                plan_obj = _load_plan(repo, task_id)
                plan_exp = plan_obj.get("expected_files")
            except Exception:
                pass
            man = build_task_manifest(repo, base_data, expected_files=plan_exp)
            t_changes = man.get("task_changes") or man.get("changes") or []
            paths_set = {repo / _extract_drift_path(c) for c in t_changes if _extract_drift_path(c)}
            modified_paths = [p for p in paths_set if p.is_file()]
        except Exception:
            modified_paths = [p for p in changed_paths(repo=repo) if p.is_file()]
    else:
        modified_paths = [p for p in changed_paths(repo=repo) if p.is_file()]

    modified_kt_files = [p for p in modified_paths if p.suffix == ".kt"]
    modified_xml_files = [p for p in modified_paths if p.suffix == ".xml"]

    # Resolve dimensions
    source_dims = contract.get("source_dimensions")
    if not source_dims and contract.get("source_family_id"):
        src_fam = _lookup_family(repo, contract.get("source_family_id"))
        if src_fam:
            source_dims = src_fam.get("dimensions")
    source_dims = source_dims or {}

    target_dims = contract.get("target_dimensions")
    if not target_dims and target_family:
        target_dims = target_family.get("dimensions")
    if not target_dims and contract.get("target_family_id"):
        tgt_fam = _lookup_family(repo, contract.get("target_family_id"))
        if tgt_fam:
            target_dims = tgt_fam.get("dimensions")
        elif (repo / ".agents" / "project-context" / "project-facts.json").is_file():
            return False, f"ARCHITECTURE_DRIFT: target family '{contract.get('target_family_id')}' not found in project facts", [f"unknown target family {contract.get('target_family_id')}"]
    target_dims = target_dims or {}

    if mode in ("PRESERVE", "REFACTOR"):
        source_toolkit = source_dims.get("ui_toolkit")
        source_stream = source_dims.get("state_stream")
        source_base = source_dims.get("state_holder_base")

        for p in modified_kt_files:
            rel = p.relative_to(repo).as_posix()
            txt = _safe_read(p)
            if not txt:
                continue

            # 1. Check XML -> Compose unauthorized transition on an existing Fragment/Activity
            # Only enforce if source family was XML or explicitly configured as XML
            if source_toolkit == "xml":
                is_fragment_target = "fragment" in p.stem.lower() or "activity" in p.stem.lower() or ("class " in txt and ("Fragment" in txt or "Activity" in txt))
                if is_fragment_target:
                    has_comp_content = "@Composable" in txt or "setContent" in txt
                    has_xml_binding = "inflate(" in txt or "binding" in txt or "R.layout." in txt
                    if has_comp_content and not has_xml_binding:
                        violations.append(
                            f"Unauthorized UI toolkit transition (XML -> Compose) in {rel} during {mode} mode"
                        )

            # 2. Check ViewModel base family replacement (e.g. BaseViewModel -> MviViewModel)
            if "class " in txt and "ViewModel" in txt:
                is_legacy_base = source_base == "BaseViewModel"
                if is_legacy_base and "MviViewModel" in txt and "BaseViewModel" not in txt:
                    violations.append(
                        f"Unauthorized ViewModel base transition (BaseViewModel -> MviViewModel) in {rel} during {mode} mode"
                    )

                # Check LiveData -> StateFlow architectural transition
                is_livedata_stream = source_stream == "livedata"
                if is_livedata_stream and "MutableStateFlow" in txt and "LiveData" not in txt:
                    violations.append(
                        f"Unauthorized state stream transition (LiveData -> StateFlow) in {rel} during {mode} mode"
                    )

    elif mode == "NEW":
        expected_toolkit = target_dims.get("ui_toolkit", "compose")
        target_nav = target_dims.get("navigation", "")

        for p in modified_kt_files:
            rel = p.relative_to(repo).as_posix()
            txt = _safe_read(p)
            if not txt:
                continue

            is_bridge = (
                ("Fragment" in p.stem or "Fragment" in txt)
                and ("ComposeView" in txt or "setContent" in txt)
            )

            # A bridge fragment hosting Compose is explicitly ALLOWED in NEW mode
            if is_bridge:
                continue

            # If expected toolkit is compose, but a newly added screen is pure XML
            if expected_toolkit == "compose":
                is_xml_screen = (
                    ("Fragment" in p.stem or "Activity" in p.stem)
                    and ("class " in txt and ("Fragment" in txt or "Activity" in txt))
                    and ("R.layout." in txt or "inflate(" in txt)
                    and not ("@Composable" in txt or "ComposeView" in txt or "setContent" in txt)
                )
                if is_xml_screen:
                    violations.append(
                        f"New screen in {rel} built with XML layouts instead of preferred Compose family"
                    )

        if expected_toolkit == "compose":
            for p in modified_xml_files:
                posix_p = p.as_posix().replace("\\", "/")
                if "/res/layout" in posix_p:
                    violations.append(
                        f"Newly added XML layout in {p.relative_to(repo).as_posix()} violates Compose target family"
                    )
        if target_nav in ("compose_navigation", "nav_host"):
            for p in modified_xml_files:
                posix_p = p.as_posix().replace("\\", "/")
                if "/res/navigation" in posix_p:
                    violations.append(
                        f"Newly added XML navigation graph in {p.relative_to(repo).as_posix()} violates Compose navigation target family"
                    )

    elif mode == "MIGRATE":
        # Migration is allowed ONLY within the approved target_scope
        if target_scope:
            norm_scope = target_scope.replace("\\", "/").strip("/")
            for p in modified_kt_files:
                rel = p.relative_to(repo).as_posix()
                if norm_scope not in rel:
                    txt = _safe_read(p)
                    # Check if an out-of-scope file experienced a family transition
                    source_base = source_dims.get("state_holder_base", "")
                    if "MviViewModel" in txt and (source_base == "BaseViewModel" or "BaseViewModel" in txt):
                        violations.append(
                            f"Architectural migration in {rel} escapes the approved target scope '{target_scope}'"
                        )

    if violations:
        remediation = ""
        if any("violates Compose" in v for v in violations):
            remediation = (
                " Remediation Advice: If this task is modifying an EXISTING XML screen or fragment, "
                "do NOT delete your XML layouts! The task plan was drafted with mode=NEW (Compose). "
                "To fix: update your task contract to preserve the existing screen via: "
                "`python .agents/scripts/workflow.py draft --repo . --task-id <id> --outcome \"...\" --kind FEATURE --architecture-target-scope <screen_file.kt> --force` "
                "then approve and resume. "
                "Only delete XML layouts if this task was genuinely meant to build a new screen purely with Jetpack Compose."
            )
        return False, f"ARCHITECTURE_DRIFT: {'; '.join(violations)}.{remediation}".strip(), violations

    return True, "Architecture contract satisfied.", []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository root path")
    parser.add_argument("--task-id", default="", help="Task ID (defaults to active task)")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    task_id = args.task_id
    if not task_id:
        from workflow import state_root
        active_file = state_root(repo) / "active-task.json"
        if active_file.is_file():
            try:
                task_id = read_json(active_file).get("task_id", "")
            except Exception:
                pass
    plan = None
    if task_id:
        from workflow import task_dir
        plan_file = task_dir(repo, task_id) / "plan.json"
        if plan_file.is_file():
            try:
                plan = read_json(plan_file)
            except Exception:
                pass
    contract = plan.get("architecture_contract") if plan else None
    if not contract:
        print("[OK] Architecture drift check exempted (legacy plan or no contract bound).")
        return 0
    passed, msg, viols = check_architecture_drift(repo, contract, task_id=task_id)
    if passed:
        print(f"[PASS] {msg}")
        return 0
    else:
        print(f"[FAIL] {msg}", file=sys.stderr)
        for v in viols:
            print(f"  - {v}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
