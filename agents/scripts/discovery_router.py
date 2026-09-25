"""Deterministic Discovery Mode Router for Graph-First Discovery.

Classifies task discovery intent into 4 deterministic modes (D0, D1, D2, D3)
without LLM / AI calls, returning authoritative anchor commands and guidance.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


NON_ARCH_EXTENSIONS = frozenset({
    ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".svg",
    ".xml",  # strings.xml, colors.xml etc.
    ".properties", ".pro",
})


def _is_exact_non_architectural_file(path: str) -> bool:
    if not path:
        return False
    norm = path.replace("\\", "/").strip().lower()
    p = Path(norm)
    suffix = p.suffix
    if suffix in {".md", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".properties", ".pro"}:
        return True
    if suffix == ".xml":
        # values/strings.xml, colors.xml, etc. are non-architectural
        # layout files like activity_main.xml or navigation graphs can be architectural
        # Match the resource directory segment (values-ar, drawable-hdpi, raw), not substrings of
        # file names such as layout/rawdata_view.xml.
        parts = norm.split("/")
        res_dir = parts[-2] if len(parts) >= 2 else ""
        if res_dir.split("-")[0] in {"values", "drawable", "mipmap", "font", "raw"}:
            return True
    return False


def classify_discovery_mode(
    *,
    task_description: str = "",
    target_file: str = "",
    target_symbol: str = "",
    kind: str = "AUTO",
    architecture_intent: str = "",
    expected_modules: str | list[str] = "",
    migration_refactor: bool = False,
) -> dict[str, Any]:
    """Classify discovery mode into D0, D1, D2, or D3."""
    desc = (task_description or "").strip()
    desc_lower = desc.lower()
    t_file = (target_file or "").strip()
    t_sym = (target_symbol or "").strip()
    k_upper = (kind or "AUTO").strip().upper()
    arch_intent = (architecture_intent or "").strip().upper()

    modules: list[str] = []
    if isinstance(expected_modules, list):
        modules = [str(m).strip() for m in expected_modules if str(m).strip()]
    elif isinstance(expected_modules, str) and expected_modules.strip():
        modules = [m.strip() for m in expected_modules.split(",") if m.strip()]

    # 1. D3 Check: Architectural / Cross-Module / Migration Scope
    # Every module id contains ':', so only a count of distinct modules marks a cross-module scope.
    is_multi_module = len({":" + m.strip(":").replace("/", ":") for m in modules}) > 1
    is_arch_intent = arch_intent in ("MIGRATION", "REFACTOR_STRUCTURAL", "CROSS_MODULE")
    has_arch_keywords = bool(re.search(
        r"\b(?:multi-module|migration|restructur|hilt\s+restructur|di\s+restructur|shared\s+contract|public\s+contract|cross-module|room\s+migration|clean\s+architecture\s+migration)\b",
        desc_lower,
    ))

    if migration_refactor or is_arch_intent or has_arch_keywords or (is_multi_module and not t_sym and not t_file):
        feature_match = re.search(r"\b(?:feature|flow|module|for)\s+([a-zA-Z0-9_-]+)\b", desc)
        feat_name = feature_match.group(1) if feature_match else ""
        if feat_name and feat_name.lower() not in {"the", "a", "all", "new", "this"}:
            cmd = f"python .agents/harness.py graph --feature {feat_name} --json"
        else:
            cmd = "python .agents/harness.py graph --arch --json"
        return {
            "discovery_mode": "ARCHITECTURAL_GRAPH",
            "reason_code": "BROAD_ARCHITECTURAL_OR_CROSS_MODULE_SCOPE",
            "required_anchor": {
                "code": "RUN_PROJECT_GRAPH",
                "kind": "HARNESS_COMMAND",
                "command": cmd,
            },
        }

    # 2. D0 Check: Exact Non-Architectural File
    if t_file and _is_exact_non_architectural_file(t_file) and not has_arch_keywords and k_upper not in ("REFACTOR",):
        return {
            "discovery_mode": "EXACT_FILE_DIRECT",
            "reason_code": "EXACT_KNOWN_FILE_NON_ARCHITECTURAL",
            "required_anchor": {
                "code": "DIRECT_FILE_READ",
                "kind": "HOST_TOOL",
                "command": f"view_file {t_file}",
            },
        }

    # Check if description mentions an exact trivial file directly (e.g. README.md, strings.xml)
    exact_file_match = re.search(r"\b([a-zA-Z0-9_\-/\\]+\.(?:md|txt|properties|png|xml))\b", desc)
    if exact_file_match and not t_sym:
        matched_file = exact_file_match.group(1).replace("\\", "/")
        if _is_exact_non_architectural_file(matched_file):
            return {
                "discovery_mode": "EXACT_FILE_DIRECT",
                "reason_code": "EXACT_KNOWN_FILE_NON_ARCHITECTURAL",
                "required_anchor": {
                    "code": "DIRECT_FILE_READ",
                    "kind": "HOST_TOOL",
                    "command": f"view_file {matched_file}",
                },
            }

    # 3. D1 Check: Exact Code Target Known (symbol or code file path)
    if t_sym:
        return {
            "discovery_mode": "TARGETED_GRAPH_CONTEXT",
            "reason_code": "EXACT_CODE_TARGET_KNOWN",
            "required_anchor": {
                "code": "RUN_TASK_CONTEXT",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py task-context --symbol {t_sym} --json",
            },
        }

    if t_file and (t_file.endswith(".kt") or t_file.endswith(".java") or t_file.endswith(".xml")):
        return {
            "discovery_mode": "TARGETED_GRAPH_CONTEXT",
            "reason_code": "EXACT_CODE_TARGET_KNOWN",
            "required_anchor": {
                "code": "RUN_TASK_CONTEXT",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py task-context --file {t_file} --json",
            },
        }

    # Check if a symbol name is named in description (CamelCase ending with ViewModel, Fragment, Screen, Repository, Service, UseCase, Activity)
    symbol_match = re.search(r"\b([A-Z][a-zA-Z0-9]*(?:ViewModel|Fragment|Screen|Repository|Service|UseCase|Activity|Dao|Database|Helper|Adapter|Manager|Client))\b", desc)
    if symbol_match:
        sym = symbol_match.group(1)
        return {
            "discovery_mode": "TARGETED_GRAPH_CONTEXT",
            "reason_code": "EXACT_CODE_TARGET_KNOWN",
            "required_anchor": {
                "code": "RUN_TASK_CONTEXT",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py task-context --symbol {sym} --json",
            },
        }

    # Check if asking for unknown code location / callers
    find_match = re.search(r"\b(?:where is|find all callers of|find|callers of)\s+([a-zA-Z0-9_]+)", desc, re.I)
    if find_match and not t_sym:
        found_target = find_match.group(1)
        return {
            "discovery_mode": "FEATURE_GRAPH",
            "reason_code": "UNKNOWN_LOCATION_SYMBOL_SEARCH",
            "required_anchor": {
                "code": "RUN_PROJECT_GRAPH",
                "kind": "HARNESS_COMMAND",
                "command": f"python .agents/harness.py graph --find {found_target} --json",
            },
        }

    # 4. D2 Check: Feature / Behavior Named (Unknown exact code target)
    feature_match = re.search(r"\b(?:feature|flow|module|in|for)\s+([a-zA-Z0-9_-]+)\b", desc_lower)
    feat_name = ""
    if feature_match:
        cand = feature_match.group(1)
        if cand not in {"the", "a", "all", "new", "this", "my", "any", "some"}:
            feat_name = cand

    if not feat_name:
        words = [w for w in re.split(r"[\s,._-]+", desc_lower) if len(w) >= 4 and w not in {
            "fix", "bug", "issue", "crash", "error", "update", "improve", "support",
            "make", "show", "user", "android", "test", "when", "does", "have", "with",
        }]
        feat_name = words[0] if words else "feature"

    return {
        "discovery_mode": "FEATURE_GRAPH",
        "reason_code": "FEATURE_TARGET_WITHOUT_EXACT_SYMBOL",
        "required_anchor": {
            "code": "RUN_PROJECT_GRAPH",
            "kind": "HARNESS_COMMAND",
            "command": f"python .agents/harness.py graph --feature {feat_name} --json",
        },
    }


DISCOVERY_D0_EXACT_FILE = "EXACT_FILE_DIRECT"
DISCOVERY_D1_TARGETED_GRAPH = "TARGETED_GRAPH_CONTEXT"
DISCOVERY_D2_FEATURE_GRAPH = "FEATURE_GRAPH"
DISCOVERY_D3_ARCHITECTURAL_GRAPH = "ARCHITECTURAL_GRAPH"

ANCHOR_DIRECT_FILE_READ = "DIRECT_FILE_READ"
ANCHOR_RUN_TASK_CONTEXT = "RUN_TASK_CONTEXT"
ANCHOR_RUN_PROJECT_GRAPH = "RUN_PROJECT_GRAPH"


from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveryDecision:
    mode: str
    reason_code: str
    required_anchor: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovery_mode": self.mode,
            "reason_code": self.reason_code,
            "required_anchor": self.required_anchor,
        }


def route_discovery(
    repo: Path | str | None = None,
    outcome: str = "",
    target_file: str = "",
    target_symbol: str = "",
    kind: str = "AUTO",
    architecture_intent: str = "",
    expected_modules: str | list[str] = "",
    migration_refactor: bool = False,
) -> DiscoveryDecision:
    res = classify_discovery_mode(
        task_description=outcome,
        target_file=target_file,
        target_symbol=target_symbol,
        kind=kind,
        architecture_intent=architecture_intent,
        expected_modules=expected_modules,
        migration_refactor=migration_refactor,
    )
    return DiscoveryDecision(
        mode=res["discovery_mode"],
        reason_code=res["reason_code"],
        required_anchor=res["required_anchor"],
    )
