"""Fast Architecture Drift Verification Engine.

Conservative, deterministic enforcement of approved task architecture contracts
during Fast Preflight. Detects unauthorized family transitions without LLM calls,
without false positives, and with full support for compatibility bridges in NEW mode.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from _repo_files import REPO, changed_paths
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
) -> tuple[bool, str, list[str]]:
    """Checks the working tree against the approved architecture contract.

    Returns:
      (passed: bool, message: str, violations: list[str])
    """
    if not contract:
        return True, "No architecture contract bound; check exempted.", []

    mode = contract.get("mode", "PRESERVE")
    target_scope = contract.get("target_scope", "")
    violations: list[str] = []

    # Note: changed_paths requires keyword-only arguments
    modified_paths = [p for p in changed_paths(repo=repo) if p.is_file()]
    modified_kt_files = [p for p in modified_paths if p.suffix == ".kt"]

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
                is_legacy_base = source_base == "BaseViewModel" or "BaseViewModel" in str(contract.get("family_signature_sha256") or "")
                if is_legacy_base and "MviViewModel" in txt and "BaseViewModel" not in txt:
                    violations.append(
                        f"Unauthorized ViewModel base transition (BaseViewModel -> MviViewModel) in {rel} during {mode} mode"
                    )

                # Check LiveData -> StateFlow architectural transition
                is_livedata_stream = source_stream == "livedata" or "livedata" in str(contract.get("family_signature_sha256") or "")
                if is_livedata_stream and "MutableStateFlow" in txt and "LiveData" not in txt:
                    violations.append(
                        f"Unauthorized state stream transition (LiveData -> StateFlow) in {rel} during {mode} mode"
                    )

    elif mode == "NEW":
        expected_toolkit = target_dims.get("ui_toolkit", "compose")

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

    elif mode == "MIGRATE":
        # Migration is allowed ONLY within the approved target_scope
        if target_scope:
            norm_scope = target_scope.replace("\\", "/").strip("/")
            for p in modified_kt_files:
                rel = p.relative_to(repo).as_posix()
                if norm_scope not in rel:
                    txt = _safe_read(p)
                    # Check if an out-of-scope file experienced a family transition
                    if "MviViewModel" in txt and "BaseViewModel" in rel:
                        violations.append(
                            f"Architectural migration in {rel} escapes the approved target scope '{target_scope}'"
                        )

    if violations:
        return False, f"ARCHITECTURE_DRIFT: {'; '.join(violations)}", violations

    return True, "Architecture contract satisfied.", []
