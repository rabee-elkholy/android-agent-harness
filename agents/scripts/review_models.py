"""Developer-owned reviewer model choices and immutable native dispatch settings.

This selects models, never reviewers, risk levels, providers or review proof.
Claude aliases and Antigravity subagent frontmatter models are documented native
contracts, not an account entitlement probe.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from _vnext_common import (
    ValidationError,
    active_review_package_path,
    atomic_write_bytes,
    atomic_write_json,
    canonical_sha256,
    read_json,
    sha256_file,
    state_root,
    task_dir,
    utc_now,
)
from evidence_store import StateLock
from policy_vocab import CORE_ROUTED_REVIEWERS

CLAUDE_MODEL_CHOICES = ("inherit", "sonnet", "opus", "haiku")
ANTIGRAVITY_MODEL_CHOICES = (
    "inherit",
    "hydrogen-argon-hybrid",
    "safe-cache-hybrid",
    "hydrogen-dynamic",
    "hydrogen-risk-hybrid",
    "gemini-4-hydrogen",
    "gemini-4-hydrogen-low",
    "gemini-4-hydrogen-medium",
    "gemini-4-hydrogen-high",
    "gemini-4-hydrogen-xhigh",
    "gemini-4-hydrogen-extra",
    "hydrogen",
    "flash-argon-hybrid",
    "risk-hybrid",
    "flash-dynamic",
    "gemini-3.8-flash",
    "gemini-3.8-flash-fast",
    "gemini-3.8-flash-low",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-high",
    "flash",
    "argon-dynamic",
    "gemini-4-argon",
    "gemini-4-argon-low",
    "gemini-4-argon-medium",
    "gemini-4-argon-high",
    "argon",
    "carbon-dynamic",
    "gemini-4-carbon",
    "gemini-4-carbon-low",
    "gemini-4-carbon-medium",
    "gemini-4-carbon-high",
    "carbon",
    "gemini-3.1-pro",
    "gemini-3.1-pro-low",
    "gemini-3.1-pro-high",
    "pro",
)
ANTIGRAVITY_META_PRESETS = (
    "inherit",
    "hydrogen-argon-hybrid",
    "safe-cache-hybrid",
    "hydrogen-dynamic",
    "hydrogen-risk-hybrid",
    "flash-argon-hybrid",
    "risk-hybrid",
    "flash-dynamic",
    "argon-dynamic",
    "carbon-dynamic",
    "hybrid-smart",
)
_COMPLEXITY_AWARE_PRESETS = (
    "hydrogen-argon-hybrid",
    "safe-cache-hybrid",
    "hydrogen-dynamic",
    "flash-argon-hybrid",
)
MODEL_CHOICES = tuple(dict.fromkeys((*CLAUDE_MODEL_CHOICES, *ANTIGRAVITY_MODEL_CHOICES)))
CLAUDE_MODEL_SOURCE = "https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields"
ANTIGRAVITY_MODEL_SOURCE = "https://antigravity.google/docs/subagents/#frontmatter-configuration-yaml"

CRITICAL_HYBRID_REVIEWERS = (
    "bug-test-reviewer-agent",
    "security-perf-reviewer-agent",
)

ANTIGRAVITY_INTERACTIVE_CHOICES: dict[str, dict[str, Any]] = {
    "hydrogen-argon-project": {
        "id": "hydrogen-argon-project",
        "index": 1,
        "scope": "project",
        "preset": "hydrogen-argon-hybrid",
        "label_ar": "تثبيت هجين الجيل الرابع الذكي للمشروع كله (hydrogen-argon-project) — موصى به: Hydrogen Medium للبسيط، وHydrogen High + Medium للمركب، وArgon Medium للأمان واللوجيك الحرج (T5) دون تكرار السؤال",
        "label_en": "Complexity-Adaptive Hydrogen + Argon Hybrid for entire project (Recommended — Hydrogen Medium on simple; Hydrogen High + Medium on complex; Argon Medium for critical T5 security/logic + Hydrogen High structural; stop asking each task)",
        "policy": {"schema_version": 1, "default": "hydrogen-argon-hybrid", "overrides": {}},
    },
    "hydrogen-argon-task": {
        "id": "hydrogen-argon-task",
        "index": 2,
        "scope": "task",
        "preset": "hydrogen-argon-hybrid",
        "label_ar": "هجين الجيل الرابع الذكي لهذه المهمة (hydrogen-argon-task) — Hydrogen Medium للبسيط، وHydrogen High + Medium للمركب، وArgon Medium للأمان واللوجيك الحرج (T5)",
        "label_en": "Complexity-Adaptive Hydrogen + Argon Medium Hybrid (Hydrogen Medium on simple; Hydrogen High + Medium on complex; Argon Medium for critical T5 security/logic + Hydrogen High structural) — for this task",
        "policy": {"schema_version": 1, "default": "hydrogen-argon-hybrid", "overrides": {}},
    },
    "hydrogen-dynamic-project": {
        "id": "hydrogen-dynamic-project",
        "index": 3,
        "scope": "project",
        "preset": "hydrogen-dynamic",
        "label_ar": "تثبيت Hydrogen الصافي للمشروع كله (hydrogen-dynamic-project) — صفر استهلاك لكوتا Argon/Carbon (Medium للبسيط، وسقف High للمركب والحرج بدون هدر xHigh)",
        "label_en": "100% Pure Gemini 4 Hydrogen for entire project (Zero Argon/Carbon subagent quota — Medium on simple, capped at High on complex & critical T5; stop asking each task)",
        "policy": {"schema_version": 1, "default": "hydrogen-dynamic", "overrides": {}},
    },
    "hydrogen-risk-project": {
        "id": "hydrogen-risk-project",
        "index": 4,
        "scope": "project",
        "preset": "hydrogen-risk-hybrid",
        "label_ar": "تثبيت هجين Hydrogen مع موديل المحادثة للمشروع (hydrogen-risk-project) — Hydrogen Medium للعادي وموديل المحادثة (Carbon) تلقائياً للحرج (T4/T5)",
        "label_en": "Risk-Adaptive Hydrogen + Chat Hybrid for entire project (Hydrogen Medium on T1-T3; Chat model on DEEP/MAX T4-T5; stop asking each task)",
        "policy": {"schema_version": 1, "default": "hydrogen-risk-hybrid", "overrides": {}},
    },
    "inherit-task": {
        "id": "inherit-task",
        "index": 5,
        "scope": "task",
        "preset": "inherit",
        "label_ar": "نفس موديل المحادثة للمهمة (inherit-task) — استخدام الموديل الأساسي لكل المراجعين",
        "label_en": "Current chat model (Inherit) — for this task",
        "policy": {"schema_version": 1, "default": "inherit", "overrides": {}},
    },
    "hydrogen-argon-once": {
        "id": "hydrogen-argon-once",
        "index": 6,
        "scope": "run",
        "preset": "hydrogen-argon-hybrid",
        "label_ar": "هجين الجيل الرابع (Hydrogen + Argon Medium) لهذه المرة فقط (hydrogen-argon-once)",
        "label_en": "Complexity-Adaptive Hydrogen + Argon Medium Hybrid — this review only",
        "policy": {"schema_version": 1, "default": "hydrogen-argon-hybrid", "overrides": {}},
    },
    "hydrogen-dynamic-task": {
        "id": "hydrogen-dynamic-task",
        "index": 7,
        "scope": "task",
        "preset": "hydrogen-dynamic",
        "label_ar": "موديل Hydrogen الصافي لهذه المهمة (hydrogen-dynamic-task) — Medium للبسيط وسقف High للمركب والحرج",
        "label_en": "100% Pure Gemini 4 Hydrogen (Medium/High ceiling) — for this task",
        "policy": {"schema_version": 1, "default": "hydrogen-dynamic", "overrides": {}},
    },
    "hydrogen-dynamic-once": {
        "id": "hydrogen-dynamic-once",
        "index": 8,
        "scope": "run",
        "preset": "hydrogen-dynamic",
        "label_ar": "موديل Hydrogen الصافي لهذه المرة فقط (hydrogen-dynamic-once)",
        "label_en": "100% Pure Gemini 4 Hydrogen (Medium/High ceiling) — this review only",
        "policy": {"schema_version": 1, "default": "hydrogen-dynamic", "overrides": {}},
    },
    "hydrogen-risk-task": {
        "id": "hydrogen-risk-task",
        "index": 9,
        "scope": "task",
        "preset": "hydrogen-risk-hybrid",
        "label_ar": "هجين Hydrogen مع موديل المحادثة لهذه المهمة (hydrogen-risk-task)",
        "label_en": "Risk-Adaptive Hydrogen + Chat Hybrid (Hydrogen Medium on T1-T3; Chat model on DEEP/MAX) — for this task",
        "policy": {"schema_version": 1, "default": "hydrogen-risk-hybrid", "overrides": {}},
    },
    "hydrogen-risk-once": {
        "id": "hydrogen-risk-once",
        "index": 10,
        "scope": "run",
        "preset": "hydrogen-risk-hybrid",
        "label_ar": "هجين Hydrogen مع موديل المحادثة لهذه المرة فقط (hydrogen-risk-once)",
        "label_en": "Risk-Adaptive Hydrogen + Chat Hybrid — this review only",
        "policy": {"schema_version": 1, "default": "hydrogen-risk-hybrid", "overrides": {}},
    },
    "flash-argon-project": {
        "id": "flash-argon-project",
        "index": 11,
        "scope": "project",
        "preset": "flash-argon-hybrid",
        "label_ar": "تثبيت الهجين الكلاسيكي للمشروع كله (flash-argon-project) — احتياطي: Flash 3.8 للبسيط، وArgon Low + Flash للمعقد، وسقف Argon Low للحرج",
        "label_en": "Legacy Complexity-Adaptive Flash 3.8 + Argon Low Hybrid for entire project (Fallback when Hydrogen is unavailable)",
        "policy": {"schema_version": 1, "default": "flash-argon-hybrid", "overrides": {}},
    },
    "flash-argon-task": {
        "id": "flash-argon-task",
        "index": 12,
        "scope": "task",
        "preset": "flash-argon-hybrid",
        "label_ar": "الهجين الكلاسيكي لهذه المهمة (flash-argon-task) — Flash 3.8 للبسيط، وArgon Low + Flash للمعقد، وسقف Argon Low للحرج",
        "label_en": "Legacy Complexity-Adaptive Flash 3.8 + Argon Low Hybrid — for this task",
        "policy": {"schema_version": 1, "default": "flash-argon-hybrid", "overrides": {}},
    },
    "flash-argon-once": {
        "id": "flash-argon-once",
        "index": 13,
        "scope": "run",
        "preset": "flash-argon-hybrid",
        "label_ar": "الهجين الكلاسيكي (Flash 3.8 + Argon Low) لهذه المرة فقط (flash-argon-once)",
        "label_en": "Legacy Complexity-Adaptive Flash 3.8 + Argon Low Hybrid — this review only",
        "policy": {"schema_version": 1, "default": "flash-argon-hybrid", "overrides": {}},
    },
    "risk-hybrid-project": {
        "id": "risk-hybrid-project",
        "index": 14,
        "scope": "project",
        "preset": "risk-hybrid",
        "label_ar": "تثبيت الهجين مع موديل المحادثة بـ Flash للمشروع (risk-hybrid-project) — Flash Medium للعادي وموديل المحادثة تلقائياً للحرج (T4/T5)",
        "label_en": "Risk-Adaptive Flash + Chat Hybrid for entire project (Flash Medium on T1-T3; Chat model on DEEP/MAX T4-T5)",
        "policy": {"schema_version": 1, "default": "risk-hybrid", "overrides": {}},
    },
    "risk-hybrid-task": {
        "id": "risk-hybrid-task",
        "index": 15,
        "scope": "task",
        "preset": "risk-hybrid",
        "label_ar": "الهجين حسب الخطورة بـ Flash للمهمة (risk-hybrid-task) — Flash Medium للعادي وموديل المحادثة تلقائياً للحرج (T4/T5)",
        "label_en": "Risk-Adaptive Flash + Chat Hybrid (Flash Medium on standard T1-T3; Chat model on DEEP/MAX T4-T5) — for this task",
        "policy": {"schema_version": 1, "default": "risk-hybrid", "overrides": {}},
    },
    "risk-hybrid-once": {
        "id": "risk-hybrid-once",
        "index": 16,
        "scope": "run",
        "preset": "risk-hybrid",
        "label_ar": "الهجين التكيفي بـ Flash لهذه المرة فقط (risk-hybrid-once)",
        "label_en": "Risk-Adaptive Flash + Chat Hybrid — this review only",
        "policy": {"schema_version": 1, "default": "risk-hybrid", "overrides": {}},
    },
    "flash-project": {
        "id": "flash-project",
        "index": 17,
        "scope": "project",
        "preset": "flash-dynamic",
        "label_ar": "تثبيت Flash 3.8 الصافي للمشروع كله (flash-project) — احتياطي كامل بدون Gemini 4",
        "label_en": "Pure Gemini 3.8 Flash (Dynamic Medium/High thinking) for entire project",
        "policy": {"schema_version": 1, "default": "flash-dynamic", "overrides": {}},
    },
    "flash-dynamic-task": {
        "id": "flash-dynamic-task",
        "index": 18,
        "scope": "task",
        "preset": "flash-dynamic",
        "label_ar": "النظام السريع بـ Flash للمهمة (flash-dynamic-task) — توفير السرعة والتوكنز بـ Flash 3.8 فقط",
        "label_en": "Gemini 3.8 Flash (Dynamic Medium/High thinking) — for this task",
        "policy": {"schema_version": 1, "default": "flash-dynamic", "overrides": {}},
    },
    "flash-dynamic-once": {
        "id": "flash-dynamic-once",
        "index": 19,
        "scope": "run",
        "preset": "flash-dynamic",
        "label_ar": "النظام السريع بـ Flash لهذه المرة فقط (flash-dynamic-once)",
        "label_en": "Gemini 3.8 Flash (Dynamic Medium/High thinking) — this review only",
        "policy": {"schema_version": 1, "default": "flash-dynamic", "overrides": {}},
    },
    "inherit-once": {
        "id": "inherit-once",
        "index": 20,
        "scope": "run",
        "preset": "inherit",
        "label_ar": "نفس موديل المحادثة لهذه المرة فقط (inherit-once)",
        "label_en": "Current chat model (Inherit) — this review only",
        "policy": {"schema_version": 1, "default": "inherit", "overrides": {}},
    },
    "hybrid-smart-task": {
        "id": "hybrid-smart-task",
        "index": 21,
        "scope": "task",
        "preset": "hybrid-smart",
        "label_ar": "النظام الهجين الذكي بـ Flash للمهمة (hybrid-smart-task) — سريع للفحص العادي وموديل المحادثة للحرج",
        "label_en": "Smart Hybrid (Flash dynamic for standard + Chat model for critical) — for this task",
        "policy": {
            "schema_version": 1,
            "default": "flash-dynamic",
            "overrides": {role: "inherit" for role in CRITICAL_HYBRID_REVIEWERS},
        },
    },
    "hybrid-smart-once": {
        "id": "hybrid-smart-once",
        "index": 22,
        "scope": "run",
        "preset": "hybrid-smart",
        "label_ar": "النظام الهجين الذكي بـ Flash لهذه المرة فقط (hybrid-smart-once)",
        "label_en": "Smart Hybrid (Flash dynamic for standard + Chat model for critical) — this review only",
        "policy": {
            "schema_version": 1,
            "default": "flash-dynamic",
            "overrides": {role: "inherit" for role in CRITICAL_HYBRID_REVIEWERS},
        },
    },
    "safe-cache-project": {
        "id": "safe-cache-project",
        "index": 23,
        "scope": "project",
        "preset": "safe-cache-hybrid",
        "label_ar": "تثبيت الهجين المحصن للكاش للمشروع (safe-cache-project) — Flash للاستكشاف الطويل (صفر سقوط كاش #200026) مع Hydrogen وArgon Medium للمراجعة والتنفيذ",
        "label_en": "Cache-Shielded Hybrid for entire project (#200026 — 3.8 Flash on multi-turn Scout sweeps; Hydrogen + Argon Medium on T5 V2 Reviewers & paced Worker)",
        "policy": {"schema_version": 1, "default": "safe-cache-hybrid", "overrides": {}},
    },
    "safe-cache-task": {
        "id": "safe-cache-task",
        "index": 24,
        "scope": "task",
        "preset": "safe-cache-hybrid",
        "label_ar": "الهجين المحصن للكاش لهذه المهمة (safe-cache-task) — Flash للاستكشاف مع Hydrogen وArgon Medium للمراجعة والتنفيذ",
        "label_en": "Cache-Shielded Hybrid (#200026 — 3.8 Flash Scout + Hydrogen/Argon Medium Reviewers & Worker) — for this task",
        "policy": {"schema_version": 1, "default": "safe-cache-hybrid", "overrides": {}},
    },
    "safe-cache-once": {
        "id": "safe-cache-once",
        "index": 25,
        "scope": "run",
        "preset": "safe-cache-hybrid",
        "label_ar": "الهجين المحصن للكاش لهذه المرة فقط (safe-cache-once)",
        "label_en": "Cache-Shielded Hybrid (#200026) — this review only",
        "policy": {"schema_version": 1, "default": "safe-cache-hybrid", "overrides": {}},
    },
}

_SHORTHAND_MAP = {
    "hydrogen@hybrid": "hydrogen-argon-hybrid",
    "hydrogen-argon": "hydrogen-argon-hybrid",
    "argon-hydrogen-hybrid": "hydrogen-argon-hybrid",
    "hydrogen@argon": "hydrogen-argon-hybrid",
    "argon@hydrogen": "hydrogen-argon-hybrid",
    "safe-cache": "safe-cache-hybrid",
    "hydrogen@safe-cache": "safe-cache-hybrid",
    "safe@cache": "safe-cache-hybrid",
    "hydrogen@dynamic": "hydrogen-dynamic",
    "hydrogen@auto": "hydrogen-dynamic",
    "gemini-4-hydrogen@dynamic": "hydrogen-dynamic",
    "gemini-4-hydrogen@auto": "hydrogen-dynamic",
    "hydrogen@risk": "hydrogen-risk-hybrid",
    "hydrogen-risk": "hydrogen-risk-hybrid",
    "hydrogen@low": "gemini-4-hydrogen-low",
    "hydrogen@medium": "gemini-4-hydrogen-medium",
    "hydrogen@high": "gemini-4-hydrogen-high",
    "hydrogen@xhigh": "gemini-4-hydrogen-xhigh",
    "hydrogen@extra": "gemini-4-hydrogen-xhigh",
    "gemini-4-hydrogen-extra": "gemini-4-hydrogen-xhigh",
    "gemini-4-hydrogen@low": "gemini-4-hydrogen-low",
    "gemini-4-hydrogen@medium": "gemini-4-hydrogen-medium",
    "gemini-4-hydrogen@high": "gemini-4-hydrogen-high",
    "gemini-4-hydrogen@xhigh": "gemini-4-hydrogen-xhigh",
    "gemini-4-hydrogen@extra": "gemini-4-hydrogen-xhigh",
    "argon@hybrid": "flash-argon-hybrid",
    "flash@argon": "flash-argon-hybrid",
    "argon-flash-hybrid": "flash-argon-hybrid",
    "flash-argon": "flash-argon-hybrid",
    "risk@hybrid": "risk-hybrid",
    "hybrid@risk": "risk-hybrid",
    "flash@dynamic": "flash-dynamic",
    "flash@auto": "flash-dynamic",
    "gemini-3.8-flash@dynamic": "flash-dynamic",
    "gemini-3.8-flash@auto": "flash-dynamic",
    "flash@fast": "gemini-3.8-flash-fast",
    "flash@low": "gemini-3.8-flash-low",
    "flash@medium": "gemini-3.8-flash-medium",
    "flash@high": "gemini-3.8-flash-high",
    "gemini-3.8-flash@fast": "gemini-3.8-flash-fast",
    "gemini-3.8-flash@low": "gemini-3.8-flash-low",
    "gemini-3.8-flash@medium": "gemini-3.8-flash-medium",
    "gemini-3.8-flash@high": "gemini-3.8-flash-high",
    "argon@dynamic": "argon-dynamic",
    "argon@auto": "argon-dynamic",
    "gemini-4-argon@dynamic": "argon-dynamic",
    "gemini-4-argon@auto": "argon-dynamic",
    "argon@low": "gemini-4-argon-low",
    "argon@medium": "gemini-4-argon-medium",
    "argon@high": "gemini-4-argon-high",
    "gemini-4-argon@low": "gemini-4-argon-low",
    "gemini-4-argon@medium": "gemini-4-argon-medium",
    "gemini-4-argon@high": "gemini-4-argon-high",
    "carbon@dynamic": "carbon-dynamic",
    "carbon@auto": "carbon-dynamic",
    "gemini-4-carbon@dynamic": "carbon-dynamic",
    "gemini-4-carbon@auto": "carbon-dynamic",
    "carbon@low": "gemini-4-carbon-low",
    "carbon@medium": "gemini-4-carbon-medium",
    "carbon@high": "gemini-4-carbon-high",
    "gemini-4-carbon@low": "gemini-4-carbon-low",
    "gemini-4-carbon@medium": "gemini-4-carbon-medium",
    "gemini-4-carbon@high": "gemini-4-carbon-high",
    "pro@low": "gemini-3.1-pro-low",
    "pro@high": "gemini-3.1-pro-high",
    "gemini-3.1-pro@low": "gemini-3.1-pro-low",
    "gemini-3.1-pro@high": "gemini-3.1-pro-high",
}


def normalize_model_token(token: object) -> object:
    if not isinstance(token, str):
        return token
    cleaned = token.strip().lower()
    return _SHORTHAND_MAP.get(cleaned, cleaned)


def choice_to_policy(choice_id: str) -> tuple[dict, str]:
    return resolve_interactive_choice(choice_id)


def resolve_interactive_choice(choice: str) -> tuple[dict, str]:
    raw = str(choice or "").strip()
    lower = raw.lower()
    if lower in ANTIGRAVITY_INTERACTIVE_CHOICES:
        entry = ANTIGRAVITY_INTERACTIVE_CHOICES[lower]
        return dict(entry["policy"]), str(entry["scope"])
    by_index = {str(v["index"]): v for v in ANTIGRAVITY_INTERACTIVE_CHOICES.values()}
    if lower in by_index:
        entry = by_index[lower]
        return dict(entry["policy"]), str(entry["scope"])
    for entry in ANTIGRAVITY_INTERACTIVE_CHOICES.values():
        if raw == entry["label_ar"] or lower == entry["label_en"].lower() or entry["id"] in lower:
            return dict(entry["policy"]), str(entry["scope"])
    raise ValidationError(
        f"unknown reviewer model choice '{choice}'; supported choices: "
        + ", ".join(sorted(ANTIGRAVITY_INTERACTIVE_CHOICES))
    )


def resolve_preset_policy(preset: str) -> dict:
    norm = str(preset or "").strip().lower()
    if norm in ("hydrogen-argon-hybrid", "argon-hydrogen-hybrid", "hydrogen-argon", "hydrogen-hybrid"):
        return {"schema_version": 1, "default": "hydrogen-argon-hybrid", "overrides": {}}
    if norm in ("safe-cache-hybrid", "safe-cache", "hydrogen-safe-cache"):
        return {"schema_version": 1, "default": "safe-cache-hybrid", "overrides": {}}
    if norm in ("hydrogen-dynamic", "hydrogen"):
        return {"schema_version": 1, "default": "hydrogen-dynamic", "overrides": {}}
    if norm in ("hydrogen-risk-hybrid", "hydrogen-risk"):
        return {"schema_version": 1, "default": "hydrogen-risk-hybrid", "overrides": {}}
    if norm in ("flash-argon-hybrid", "argon-flash-hybrid", "flash-argon", "argon-hybrid"):
        return {"schema_version": 1, "default": "flash-argon-hybrid", "overrides": {}}
    if norm in ("flash-dynamic", "flash"):
        return {"schema_version": 1, "default": "flash-dynamic", "overrides": {}}
    if norm == "inherit":
        return default_policy()
    if norm in ("risk-hybrid", "adaptive-hybrid"):
        return {"schema_version": 1, "default": "risk-hybrid", "overrides": {}}
    if norm in ("hybrid-smart", "hybrid"):
        return {
            "schema_version": 1,
            "default": "flash-dynamic",
            "overrides": {role: "inherit" for role in CRITICAL_HYBRID_REVIEWERS},
        }
    raise ValidationError(
        f"unknown reviewer model preset '{preset}'; use hydrogen-argon-hybrid, hydrogen-dynamic, hydrogen-risk-hybrid, flash-argon-hybrid, flash-dynamic, risk-hybrid, inherit, or hybrid-smart"
    )


def resolve_antigravity_model(
    requested: str,
    role: str,
    effort_intent: str = "NORMAL",
    *,
    complexity_tier: str = "SIMPLE",
) -> tuple[str, str]:
    """Resolve an Antigravity model choice and dynamic thinking level for a specific reviewer role.

    Standard NORMAL-effort reviews run on medium thinking (preventing 10-minute Flash High
    overthinking loops); high thinking or parent escalation activates strictly on DEEP/MAX effort.
    For `flash-argon-hybrid`, resolution adapts deterministically across 3 complexity bands
    with a strict hard ceiling of `gemini-4-argon-low` (never escalating to `argon-medium`/`high`):
      - SIMPLE   -> 100% `gemini-3.8-flash-medium` (zero Argon quota burn on simple features/UI)
      - COMPLEX  -> `gemini-4-argon-low` for logic/security-perf (`CRITICAL_HYBRID_REVIEWERS`) and any
                    `DEEP`-effort specialist; `gemini-3.8-flash-medium` for NORMAL structural reviewers
      - CRITICAL -> `gemini-4-argon-low` across all routed specialists (Lead writes core production code)
    """
    req = str(normalize_model_token(requested) or "inherit")
    intent = str(effort_intent or "NORMAL").upper()
    tier = str(complexity_tier or "SIMPLE").strip().upper()
    if tier not in ("SIMPLE", "COMPLEX", "CRITICAL"):
        tier = "SIMPLE"
    is_deep = intent in ("DEEP", "MAX")
    if req == "inherit":
        return "inherit", "inherit"
    if req in ("hydrogen-argon-hybrid", "safe-cache-hybrid"):
        if tier == "CRITICAL" or intent == "MAX":
            if role in CRITICAL_HYBRID_REVIEWERS or intent == "MAX":
                return "gemini-4-argon-medium", "medium"
            return "gemini-4-hydrogen-high", "high"
        if tier == "COMPLEX" or intent == "DEEP":
            if role in CRITICAL_HYBRID_REVIEWERS or intent == "DEEP":
                return "gemini-4-hydrogen-high", "high"
            return "gemini-4-hydrogen-medium", "medium"
        return "gemini-4-hydrogen-medium", "medium"
    if req == "hydrogen-dynamic":
        if tier == "CRITICAL" or intent == "MAX":
            return "gemini-4-hydrogen-high", "high"
        if tier == "COMPLEX" or intent == "DEEP":
            if role in CRITICAL_HYBRID_REVIEWERS or intent == "DEEP":
                return "gemini-4-hydrogen-high", "high"
            return "gemini-4-hydrogen-medium", "medium"
        return "gemini-4-hydrogen-medium", "medium"
    if req == "hydrogen-risk-hybrid":
        return ("inherit", "inherit") if is_deep else ("gemini-4-hydrogen-medium", "medium")
    if req in ("gemini-4-hydrogen", "hydrogen"):
        return "gemini-4-hydrogen-high", "high"
    if req == "flash-argon-hybrid":
        if tier == "CRITICAL" or intent == "MAX":
            return "gemini-4-argon-low", "low"
        if tier == "COMPLEX" or intent == "DEEP":
            if role in CRITICAL_HYBRID_REVIEWERS or intent == "DEEP":
                return "gemini-4-argon-low", "low"
            return "gemini-3.8-flash-medium", "medium"
        return "gemini-3.8-flash-medium", "medium"
    if req == "risk-hybrid":
        return ("inherit", "inherit") if is_deep else ("gemini-3.8-flash-medium", "medium")
    if req in ("flash-dynamic", "gemini-3.8-flash", "flash"):
        return ("gemini-3.8-flash-high", "high") if is_deep else ("gemini-3.8-flash-medium", "medium")
    if req in ("argon-dynamic", "gemini-4-argon", "argon"):
        return ("gemini-4-argon-high", "high") if is_deep else ("gemini-4-argon-medium", "medium")
    if req in ("carbon-dynamic", "gemini-4-carbon", "carbon"):
        return ("gemini-4-carbon-high", "high") if is_deep else ("gemini-4-carbon-medium", "medium")
    if req in ("gemini-3.1-pro", "pro"):
        return "gemini-3.1-pro-high", "high"
    for suffix in ("xhigh", "fast", "low", "medium", "high"):
        if req.endswith(f"-{suffix}"):
            return req, suffix
    return req, "medium"


def validate_policy(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"schema_version", "default", "overrides"}:
        raise ValidationError("review_model_policy requires schema_version, default and overrides only")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationError("review_model_policy schema_version must be 1")
    default_val = normalize_model_token(value["default"]) if isinstance(value["default"], str) else value["default"]
    if not isinstance(default_val, str) or default_val not in MODEL_CHOICES:
        raise ValidationError(
            "review_model_policy default must be a supported model choice "
            "(inherit, sonnet, opus, haiku, flash-dynamic, gemini-3.8-flash-*, gemini-4-argon-*, gemini-4-carbon-*, gemini-3.1-pro-*)"
        )
    overrides = value["overrides"]
    if not isinstance(overrides, dict):
        raise ValidationError("review_model_policy overrides must map canonical reviewer roles to supported choices")
    normalized_overrides: dict[str, str] = {}
    for role, model in overrides.items():
        norm_model = normalize_model_token(model) if isinstance(model, str) else model
        if role not in CORE_ROUTED_REVIEWERS or not isinstance(norm_model, str) or norm_model not in MODEL_CHOICES:
            raise ValidationError("review_model_policy overrides must map canonical reviewer roles to supported choices")
        normalized_overrides[role] = norm_model
    return {"schema_version": 1, "default": default_val, "overrides": dict(sorted(normalized_overrides.items()))}


def default_policy() -> dict:
    return {"schema_version": 1, "default": "inherit", "overrides": {}}


def host_capability(host: str) -> dict:
    host = str(host).strip().lower()
    if host == "claude":
        return {
            "host": host,
            "supports_override": True,
            "choices": list(CLAUDE_MODEL_CHOICES),
            "argument_name": "model",
            "source": CLAUDE_MODEL_SOURCE,
            "availability": "HOST_ACCOUNT_DEPENDENT",
            "enforcement": "RULE_ENFORCED",
        }
    if host == "antigravity":
        return {
            "host": host,
            "supports_override": True,
            "choices": list(ANTIGRAVITY_MODEL_CHOICES),
            "interactive_choices": [
                {
                    "id": item["id"],
                    "scope": item["scope"],
                    "preset": item["preset"],
                    "label_ar": item["label_ar"],
                    "label_en": item["label_en"],
                }
                for item in sorted(ANTIGRAVITY_INTERACTIVE_CHOICES.values(), key=lambda x: int(x["index"]))
                if item["index"] in (1, 2, 3, 4, 5)
            ],
            "argument_name": None,
            "agent_frontmatter_field": "model",
            "source": ANTIGRAVITY_MODEL_SOURCE,
            "availability": "HOST_ACCOUNT_DEPENDENT",
            "enforcement": "FRONTMATTER_ENFORCED",
        }
    return {
        "host": host,
        "supports_override": False,
        "choices": ["inherit"],
        "argument_name": None,
        "source": "no_supported_native_model_override",
        "availability": "INHERIT_ONLY",
        "enforcement": "UNSUPPORTED",
    }


def validate_for_host(policy: dict, host: str) -> dict:
    policy = validate_policy(policy)
    cap = host_capability(host)
    selected = {policy["default"], *policy["overrides"].values()}
    if not selected.issubset(cap["choices"]):
        raise ValidationError(
            f"REVIEW_MODEL_UNSUPPORTED: host '{host}' does not support model choice(s) {sorted(selected - set(cap['choices']))}; "
            f"choose inherit explicitly or use a supported native model for this host (for a single task on '{host}' without changing your project policy, "
            f"run: python .agents/harness.py review models set --task-id <id> --host {host} --scope task --default inherit --source conversation --proof-reference '<reason>'). "
            "No fallback was applied."
        )
    return policy


def _policy_file(repo: Path, task_id: str | None, *, scope: str = "task") -> Path:
    root = task_dir(repo, task_id) if task_id else state_root(repo)
    filename = "review-models-run.json" if (task_id and scope == "run") else "review-models.json"
    path = root / filename
    if path.is_symlink() or not path.resolve().is_relative_to(state_root(repo).resolve()):
        raise ValidationError("review model configuration escapes harness state")
    return path


def _active_run_identifiers(repo: Path, task_id: str) -> set[str]:
    """Return active run IDs (final verification run_id and/or active phase_review_run_id) for task_id."""
    active_ids: set[str] = set()
    tdir = task_dir(repo, task_id)
    crun = tdir / "current-run.json"
    if crun.is_file():
        try:
            rid = str(read_json(crun).get("run_id") or "").strip()
            if rid:
                active_ids.add(rid)
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            pass
    pstate_f = tdir / "phase-state.json"
    if pstate_f.is_file():
        try:
            pstate = read_json(pstate_f)
            cur_phase = str(pstate.get("current_phase_id") or "").strip()
            if cur_phase:
                from phase_review import phase_run_file
                prun_f = phase_run_file(tdir, cur_phase)
                if prun_f.is_file():
                    prid = str(read_json(prun_f).get("phase_review_run_id") or "").strip()
                    if prid:
                        active_ids.add(prid)
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            pass
    return active_ids


def load_policy(
    repo: Path,
    task_id: str | None = None,
    *,
    run_id: str | None = None,
    consume_next_run: bool = False,
) -> tuple[dict, str]:
    # 1. Run-scoped ("this review only") configuration takes highest precedence for its bound run_id.
    if task_id:
        run_path = _policy_file(repo, task_id, scope="run")
        if run_path.exists():
            record = read_json(run_path)
            if not isinstance(record, dict) or record.get("scope") != "run" or record.get("task_id") != task_id:
                raise ValidationError("review model run configuration scope mismatch")
            if record.get("record_sha256") != canonical_sha256({k: v for k, v in record.items() if k != "record_sha256"}):
                raise ValidationError("review model configuration checksum mismatch")
            bound_run = str(record.get("bound_run_id") or "")
            if bound_run == "next_run":
                if consume_next_run and run_id:
                    record["bound_run_id"] = run_id
                    record["record_sha256"] = canonical_sha256({k: v for k, v in record.items() if k != "record_sha256"})
                    atomic_write_json(run_path, record)
                return validate_policy(record.get("policy")), "run"
            if run_id and bound_run == run_id:
                return validate_policy(record.get("policy")), "run"
            if run_id is None and bound_run and bound_run in _active_run_identifiers(repo, task_id):
                return validate_policy(record.get("policy")), "run"

    # 2. Task-scoped and Project-scoped configuration.
    for scope, identity in (("task", task_id), ("project", None)):
        if scope == "task" and not task_id:
            continue
        path = _policy_file(repo, identity, scope=scope)
        if path.exists():
            record = read_json(path)
            if not isinstance(record, dict) or record.get("scope") != scope or record.get("task_id") != identity:
                raise ValidationError("review model configuration scope mismatch")
            if record.get("record_sha256") != canonical_sha256({k: v for k, v in record.items() if k != "record_sha256"}):
                raise ValidationError("review model configuration checksum mismatch")
            return validate_policy(record.get("policy")), scope
    answers = repo / ".harness-setup" / "answers.json"
    if answers.exists():
        data = read_json(answers)
        if "review_model_policy" in data:
            return validate_policy(data["review_model_policy"]), "setup"
    return default_policy(), "default"


def _compute_efforts_by_role(
    repo: Path,
    task_id: str | None,
    reviewers: list[str],
    policy_data: dict | None = None,
    plan: dict | None = None,
) -> dict[str, str]:
    efforts: dict[str, str] = {}
    if task_id and (policy_data is None or plan is None):
        tdir = task_dir(repo, task_id)
        if plan is None and (tdir / "plan.json").is_file():
            try:
                plan = read_json(tdir / "plan.json")
            except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
                plan = {}
        if policy_data is None:
            crun = tdir / "current-run.json"
            if crun.is_file():
                try:
                    pol_p = Path(str(read_json(crun).get("policy") or ""))
                    if pol_p.is_file():
                        policy_data = read_json(pol_p)
                except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
                    policy_data = {}
            elif (tdir / "policy.json").is_file():
                try:
                    policy_data = read_json(tdir / "policy.json")
                except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
                    policy_data = {}
            elif (tdir / "phase-state.json").is_file():
                try:
                    cur_phase = str(read_json(tdir / "phase-state.json").get("current_phase_id") or "").strip()
                    ckpt_f = tdir / "phases" / cur_phase / "checkpoint.json"
                    if cur_phase and ckpt_f.is_file():
                        ckpt = read_json(ckpt_f)
                        reserve = ckpt.get("final_review_reserve") or {}
                        ckpt_surfaces = ckpt.get("surfaces") or reserve.get("surfaces") or []
                        if ckpt_surfaces:
                            policy_data = {
                                "surfaces": ckpt_surfaces,
                                "severity": "CRITICAL" if set(ckpt_surfaces) & {"AUTH", "BILLING", "SECURITY", "CRYPTO", "SENSITIVE_DATA"} else "MEDIUM",
                            }
                except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
                    policy_data = {}
    explicit_efforts = (policy_data or {}).get("reviewer_efforts") if isinstance(policy_data, dict) else None
    try:
        from review_policy import reviewer_effort_for
        surfaces = (policy_data or {}).get("surfaces") or (plan or {}).get("expected_surfaces") or []
        critical_set = {"AUTH", "BILLING", "SECURITY", "CRYPTO", "SENSITIVE_DATA"}
        default_sev = "CRITICAL" if (set(surfaces) & critical_set) else "MEDIUM"
        severity = (policy_data or {}).get("severity") or default_sev
        round_number = int((policy_data or {}).get("review_round") or (((plan or {}).get("review_rounds") or 0) + 1))
        finding_owners = set(((policy_data or {}).get("later_round_source") or {}).get("finding_owners") or [])
        planning_depth = str((plan or {}).get("planning_depth") or "BOUNDED")
        raw_mods = (plan or {}).get("changed_modules") or (plan or {}).get("expected_modules") or []
        mod_count = len(raw_mods) if isinstance(raw_mods, list) and raw_mods else 1
        for role in reviewers:
            if isinstance(explicit_efforts, dict) and str(explicit_efforts.get(role) or "").upper() in ("NORMAL", "DEEP", "MAX"):
                efforts[role] = str(explicit_efforts[role]).upper()
            else:
                efforts[role] = reviewer_effort_for(
                    role,
                    surfaces=surfaces,
                    severity=severity,
                    round_number=round_number,
                    is_finding_owner=(role in finding_owners),
                    planning_depth=planning_depth,
                    changed_modules_count=mod_count,
                )
    except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
        for role in reviewers:
            efforts[role] = "DEEP" if role == "security-perf-reviewer-agent" else "NORMAL"
    return efforts


_CRITICAL_COMPLEXITY_SURFACES = frozenset({"AUTH", "BILLING", "SECURITY", "CRYPTO", "SENSITIVE_DATA"})
_COMPLEX_TECHNICAL_SURFACES = frozenset({
    "COROUTINES",
    "NETWORK",
    "ROOM_SCHEMA",
    "DATABASE",
    "PUBLIC_API",
    "DEVICE_API",
    "NATIVE_CODE",
    "BUILD_CONFIG",
    "MANIFEST_PERMISSIONS",
    "MANIFEST_PERMISSION",
})


def _is_test_path(raw_path: str) -> bool:
    norm = str(raw_path or "").replace("\\", "/").strip().lstrip("./").lower()
    if not norm:
        return False
    if any(seg in norm for seg in ("/src/test/", "/src/androidtest/", "/src/commontest/", "/src/jvmtest/", "/src/iostest/")):
        return True
    if norm.startswith(("src/test/", "src/androidtest/", "src/commontest/")):
        return True
    stem = Path(norm).stem
    return stem.endswith(("test", "tests", "spec", "fake", "mock")) and ("test" in norm or "spec" in norm)


def compute_task_complexity_tier(
    repo: Path,
    task_id: str | None,
    policy_data: dict | None = None,
    plan: dict | None = None,
) -> str:
    """Classify a task or active review slice into SIMPLE, COMPLEX, or CRITICAL for adaptive model routing."""
    cls_doc: dict[str, Any] = {}
    if task_id:
        try:
            tdir = task_dir(repo, task_id)
            if plan is None and (tdir / "plan.json").is_file():
                plan = read_json(tdir / "plan.json")
            if policy_data is None:
                crun = tdir / "current-run.json"
                if crun.is_file():
                    pol_p = Path(str(read_json(crun).get("policy") or ""))
                    if pol_p.is_file():
                        policy_data = read_json(pol_p)
                elif (tdir / "policy.json").is_file():
                    policy_data = read_json(tdir / "policy.json")
                elif (tdir / "phase-state.json").is_file():
                    cur_phase = str(read_json(tdir / "phase-state.json").get("current_phase_id") or "").strip()
                    ckpt_f = tdir / "phases" / cur_phase / "checkpoint.json"
                    if cur_phase and ckpt_f.is_file():
                        ckpt = read_json(ckpt_f)
                        reserve = ckpt.get("final_review_reserve") or {}
                        ckpt_surfaces = ckpt.get("surfaces") or reserve.get("surfaces") or []
                        if ckpt_surfaces:
                            policy_data = {
                                "surfaces": ckpt_surfaces,
                                "severity": "CRITICAL" if (set(ckpt_surfaces) & _CRITICAL_COMPLEXITY_SURFACES) else "MEDIUM",
                            }
            if (tdir / "classification.json").is_file():
                raw_cls = read_json(tdir / "classification.json")
                if isinstance(raw_cls, dict):
                    cls_doc = raw_cls
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            pass

    pol = policy_data if isinstance(policy_data, dict) else {}
    pl = plan if isinstance(plan, dict) else {}

    phases = pl.get("phases") if isinstance(pl.get("phases"), list) else []
    active_idx = int(pl.get("active_phase_index") or 0)
    phase_surfaces: list[str] = []
    phase_files: list[str] = []
    if phases and 0 <= active_idx < len(phases) and isinstance(phases[active_idx], dict):
        phase_surfaces = list(phases[active_idx].get("surfaces") or [])
        phase_files = list(phases[active_idx].get("expected_files") or [])

    raw_surfaces = pol.get("surfaces") or cls_doc.get("surfaces") or phase_surfaces or pl.get("expected_surfaces") or []
    surfaces_set = {str(s).strip().upper() for s in raw_surfaces if str(s).strip()}

    severity = str(pol.get("severity") or cls_doc.get("severity") or "").strip().upper()
    risk_tier = str(pol.get("risk_tier") or pl.get("risk_tier") or "").strip().upper()
    round_number = int(pol.get("review_round") or ((int(pl.get("review_rounds") or 0)) + 1))
    task_kind = str(pl.get("task_kind") or pl.get("kind") or "FEATURE").strip().upper()
    planning_depth = str(pol.get("planning_depth") or pl.get("planning_depth") or "BOUNDED").strip().upper()

    raw_mods = pol.get("changed_modules") or pl.get("changed_modules") or pl.get("expected_modules") or []
    modules_count = len(raw_mods) if isinstance(raw_mods, list) and raw_mods else 1

    candidate_files: list[str] = []
    if isinstance(cls_doc.get("task_changes"), list) and cls_doc["task_changes"]:
        for item in cls_doc["task_changes"]:
            p = item.get("path") if isinstance(item, dict) else item
            if p:
                candidate_files.append(str(p))
    elif phase_files:
        candidate_files = [str(p) for p in phase_files if p]
    elif isinstance(pl.get("expected_files"), list):
        candidate_files = [str(p) for p in pl["expected_files"] if p]

    if candidate_files:
        non_test_file_count = sum(1 for p in candidate_files if not _is_test_path(p))
    else:
        non_test_file_count = int(pol.get("changed_files") or cls_doc.get("changed_files") or 0)

    changed_lines = int(pol.get("changed_lines") or cls_doc.get("changed_lines") or 0)

    # Band 3: CRITICAL
    if (
        severity == "CRITICAL"
        or risk_tier in {"T4_SENSITIVE", "T5_CRITICAL"}
        or bool(surfaces_set & _CRITICAL_COMPLEXITY_SURFACES)
        or round_number >= 3
    ):
        return "CRITICAL"

    # Band 2: COMPLEX
    if (
        round_number == 2
        or task_kind == "BUG"
        or planning_depth == "ARCHITECTURAL"
        or len(phases) >= 2
        or modules_count >= 2
        or risk_tier in {"T3_SUBSYSTEM", "T4_DATA_DEVICE"}
        or non_test_file_count >= 4
        or changed_lines > 90
        or bool(surfaces_set & _COMPLEX_TECHNICAL_SURFACES)
        or ("NAVIGATION" in surfaces_set and non_test_file_count >= 2)
    ):
        return "COMPLEX"

    # Band 1: SIMPLE
    return "SIMPLE"


def sync_antigravity_agent_models(repo: Path, selections: dict[str, dict] | None = None) -> list[str]:
    """Synchronize resolved Antigravity reviewer models into .agents/agents/<role>/agent.md frontmatter."""
    agents_base = repo / ".agents" / "agents"
    subagents_base = repo / ".agents" / "subagents"
    if not subagents_base.is_dir():
        kit_subagents = Path(__file__).resolve().parents[1] / "subagents"
        if kit_subagents.is_dir():
            subagents_base = kit_subagents
    if not agents_base.is_dir() or not subagents_base.is_dir():
        return []
    try:
        from install_tool_adapters import antigravity_agent_markdown, with_managed_marker
    except ImportError:
        return []

    updated: list[str] = []
    selections = selections or {}
    from reviewer_host import active_reviews, _load_ledger
    for run, ledger_file in active_reviews(repo):
        if run.get("review_host") != "antigravity" or not ledger_file.is_file():
            continue
        for role, entry in _load_ledger(run, ledger_file).get("reviewers", {}).items():
            if role not in selections or entry.get("state") != "DISPATCHED" or entry.get("execution_id"):
                continue
            pending = frozen_models(run).get(role, {})
            expected = pending.get("agent_frontmatter_model") or pending.get("resolved_model")
            desired = selections[role].get("agent_frontmatter_model") or selections[role].get("resolved_model")
            if expected != desired:
                raise ValidationError(f"REVIEW_MODEL_LAUNCH_PENDING: {role} still needs execution binding in task {run['task_id']}; its launch settings cannot change")
    for role in selections:
        if role not in CORE_ROUTED_REVIEWERS:
            raise ValidationError(f"unknown reviewer role '{role}'")
        json_path = subagents_base / f"{role}.json"
        dest = agents_base / role / "agent.md"
        if not json_path.is_file() or not dest.parent.is_dir():
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            continue
        sel = selections[role]
        fm_model = sel.get("agent_frontmatter_model") or sel.get("resolved_model")
        if fm_model == "inherit":
            fm_model = None
        rendered = with_managed_marker(antigravity_agent_markdown(data, model=fm_model))
        rendered_bytes = rendered.encode("utf-8")
        try:
            current_bytes = dest.read_bytes() if dest.is_file() else None
        except OSError:
            current_bytes = None
        if current_bytes != rendered_bytes:
            dest.write_bytes(rendered_bytes)
            updated.append(f".agents/agents/{role}/agent.md")

    ownership_file = repo / ".harness-setup" / "ownership-v1.json"
    if updated and ownership_file.is_file():
        try:
            manifest = read_json(ownership_file)
            entries = manifest.get("entries")
            if isinstance(entries, list):
                changed = False
                updated_set = set(updated)
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("path") in updated_set:
                        target = repo / str(entry["path"])
                        if target.is_file():
                            entry["post_install_sha256"] = sha256_file(target)
                            changed = True
                if changed:
                    manifest["ownership_sha256"] = canonical_sha256(
                        {k: v for k, v in manifest.items() if k != "ownership_sha256"}
                    )
                    atomic_write_json(ownership_file, manifest)
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            pass
    return updated


def freeze_models(
    repo: Path,
    task_id: str,
    host: str,
    reviewers: list[str],
    *,
    run_id: str | None = None,
    policy_data: dict | None = None,
    plan: dict | None = None,
) -> dict:
    policy, source = load_policy(repo, task_id, run_id=run_id, consume_next_run=bool(run_id))
    efforts = _compute_efforts_by_role(repo, task_id, reviewers, policy_data=policy_data, plan=plan)
    complexity_tier = compute_task_complexity_tier(repo, task_id, policy_data=policy_data, plan=plan)
    frozen = _resolve_policy(policy, source, host, reviewers, efforts_by_role=efforts, complexity_tier=complexity_tier)
    if str(host).strip().lower() == "antigravity":
        sync_antigravity_agent_models(repo, frozen.get("reviewers") or {})
    return frozen


def _resolve_policy(
    policy: dict,
    source: str,
    host: str,
    reviewers: list[str],
    *,
    efforts_by_role: dict[str, str] | None = None,
    complexity_tier: str = "SIMPLE",
) -> dict:
    host_norm = str(host).strip().lower()
    policy = validate_for_host(policy, host_norm)
    efforts = efforts_by_role or {}
    tier_norm = str(complexity_tier or "SIMPLE").strip().upper()
    if tier_norm not in ("SIMPLE", "COMPLEX", "CRITICAL"):
        tier_norm = "SIMPLE"
    uses_adaptive_argon = (
        policy.get("default") in _COMPLEXITY_AWARE_PRESETS
        or any(v in _COMPLEXITY_AWARE_PRESETS for v in (policy.get("overrides") or {}).values())
    )
    selections = {}
    for role in reviewers:
        if role not in CORE_ROUTED_REVIEWERS:
            raise ValidationError(f"unknown reviewer role '{role}'")
        requested = policy["overrides"].get(role, policy["default"])
        if host_norm == "antigravity" and requested != "inherit":
            default_intent = "NORMAL" if requested in _COMPLEXITY_AWARE_PRESETS else ("DEEP" if role == "security-perf-reviewer-agent" else "NORMAL")
            effort_intent = efforts.get(role) or default_intent
            resolved_model, thinking_level = resolve_antigravity_model(
                requested,
                role,
                effort_intent,
                complexity_tier=tier_norm,
            )
            inherited_escalation = resolved_model == "inherit"
            sel_entry = {
                "requested_model": requested,
                "resolved_model": resolved_model,
                "thinking_level": thinking_level,
                "reasoning_intent": effort_intent,
                "model_policy": "INHERIT_PARENT_BY_OMISSION" if inherited_escalation else "DEVELOPER_SELECTED_NATIVE",
                "model_argument": None,
                "native_arguments": {},
                "agent_frontmatter_model": None if inherited_escalation else resolved_model,
                "actual_model": None,
                "actual_model_status": "UNOBSERVED",
            }
            if requested in _COMPLEXITY_AWARE_PRESETS:
                sel_entry["complexity_tier"] = tier_norm
            selections[role] = sel_entry
        else:
            selections[role] = {
                "requested_model": requested,
                "model_policy": "INHERIT_PARENT_BY_OMISSION" if requested == "inherit" else "DEVELOPER_SELECTED_NATIVE",
                "model_argument": None if requested == "inherit" else "model",
                "native_arguments": {} if requested == "inherit" else {"model": requested},
                "actual_model": None,
                "actual_model_status": "UNOBSERVED",
            }
    frozen = {"schema_version": 1, "host": host_norm, "source": source, "policy": policy, "reviewers": selections}
    if host_norm == "antigravity":
        frozen["selection_required"] = source == "default"
        if uses_adaptive_argon:
            frozen["complexity_tier"] = tier_norm
    frozen["sha256"] = canonical_sha256(frozen)
    return frozen


def transfer_models(run: dict, host: str, reviewers: list[str], *, plan: dict | None = None) -> dict:
    """A host continuation preserves the original choice, never a live default."""
    frozen_models(run)
    old = run.get("review_models") or {}
    old_efforts = {
        role: str(sel.get("reasoning_intent") or ("NORMAL" if sel.get("requested_model") in _COMPLEXITY_AWARE_PRESETS else ("DEEP" if role == "security-perf-reviewer-agent" else "NORMAL")))
        for role, sel in (old.get("reviewers") or {}).items()
        if isinstance(sel, dict)
    }
    old_tier = str(old.get("complexity_tier") or "SIMPLE")
    return _resolve_policy(
        old.get("policy") or default_policy(),
        old.get("source") or "default",
        host,
        reviewers,
        efforts_by_role=old_efforts,
        complexity_tier=old_tier,
    )


def frozen_models(run: dict) -> dict:
    frozen = run.get("review_models")
    if frozen is None:
        return {}  # Historical runs retain inheritance, never read live config.
    if not isinstance(frozen, dict) or frozen.get("sha256") != canonical_sha256({k: v for k, v in frozen.items() if k != "sha256"}):
        raise ValidationError("frozen reviewer model settings checksum mismatch")
    if frozen.get("host") != run.get("review_host"):
        raise ValidationError("frozen reviewer model host mismatch")
    host_norm = str(frozen["host"]).strip().lower()
    policy = validate_for_host(frozen.get("policy"), host_norm)
    reviewers = frozen.get("reviewers")
    if not isinstance(reviewers, dict):
        raise ValidationError("invalid frozen reviewer model roster")
    for role, selection in reviewers.items():
        requested = policy["overrides"].get(role, policy["default"])
        if role not in CORE_ROUTED_REVIEWERS or not isinstance(selection, dict) or selection.get("requested_model") != requested:
            raise ValidationError("invalid frozen reviewer model selection")
        expected_args = {} if (requested == "inherit" or host_norm == "antigravity") else {"model": requested}
        if selection.get("native_arguments") != expected_args:
            raise ValidationError("invalid frozen native model arguments")
        if host_norm == "antigravity" and requested != "inherit":
            default_intent = "NORMAL" if requested in _COMPLEXITY_AWARE_PRESETS else ("DEEP" if role == "security-perf-reviewer-agent" else "NORMAL")
            intent = str(selection.get("reasoning_intent") or default_intent)
            sel_tier = str(selection.get("complexity_tier") or frozen.get("complexity_tier") or "SIMPLE")
            exp_resolved, exp_thinking = resolve_antigravity_model(requested, role, intent, complexity_tier=sel_tier)
            if selection.get("resolved_model") != exp_resolved or selection.get("thinking_level") != exp_thinking:
                raise ValidationError("invalid frozen Antigravity resolved model or thinking level")
    return reviewers


def _antigravity_frontmatter_model(repo: Path | None, role: str) -> str | None:
    if repo is None:
        return None
    agent_file = Path(repo) / ".agents" / "agents" / role / "agent.md"
    if not agent_file.is_file():
        return None
    try:
        text = agent_file.read_text(encoding="utf-8", errors="replace")
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if line.strip().startswith("model:"):
                    raw_val = line.split(":", 1)[1].strip().strip('"').strip("'")
                    return raw_val or None
    except OSError:
        return None
    return None


def model_evidence(run: dict, role: str, transcript_identity: dict | None = None) -> dict:
    selection = frozen_models(run).get(role, {"requested_model": "inherit"})
    requested = selection["requested_model"]
    host_norm = str(run.get("review_host") or "").strip().lower()
    identity = transcript_identity or {}

    if host_norm == "antigravity":
        from antigravity_runtime import native_model_metadata
        expected_resolved = selection.get("resolved_model")
        effective_inherits = requested == "inherit" or expected_resolved == "inherit"
        try:
            observed = native_model_metadata(Path(identity["transcript_path"])) if identity.get("transcript_path") else {}
        except ValidationError:
            if not effective_inherits:
                raise
            observed = {}  # Parent inheritance requires no invented native proof.
        if not effective_inherits:
            if not observed:
                raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: {role} requires native execution model metadata; frontmatter is configuration only")
            if not _matches_antigravity_native_model(
                str(expected_resolved or ""),
                selection.get("thinking_level"),
                observed.get("host_configured_model"),
                observed.get("host_reported_models", []),
            ):
                raise ValidationError(f"REVIEW_MODEL_MISMATCH: {role} native execution does not match {expected_resolved}")
        return {
            "requested_model": requested,
            "resolved_model": expected_resolved,
            "thinking_level": selection.get("thinking_level"),
            "actual_model": (observed.get("host_reported_models") or [None])[-1],
            "actual_model_status": "NATIVE_METADATA_OBSERVED" if observed else "UNOBSERVED",
            **observed,
            "settings_sha256": (run.get("review_models") or {}).get("sha256"),
        }

    if host_norm == "claude" and identity.get("transcript_path"):
        from review_sources import read_claude_subagent_transcript
        _, observed = read_claude_subagent_transcript(Path(identity["transcript_path"]))
        if observed["transcript_sha256"] != identity.get("transcript_sha256"):
            raise ValidationError("reviewer transcript changed after ingestion")
        identity = observed
    else:
        identity = {}  # A report's own model claim is never native evidence.
    actual = identity.get("host_reported_model") if host_norm == "claude" else None
    if not isinstance(actual, str) or not actual:
        actual = None
    # Aliases identify families, not fixed versions. Only compare an observed
    # native model ID, never a model name supplied in the review response body.
    observed_models = identity.get("host_reported_models") or ([actual] if actual else [])
    pattern = r"claude-(?:[0-9]+(?:-[0-9]+)*-)?" + re.escape(requested) + r"(?:-|$)"
    if actual and requested != "inherit" and any(not re.match(pattern, model) for model in observed_models):
        raise ValidationError(f"REVIEW_MODEL_MISMATCH: {role} requested {requested}, host reported {actual}")
    if requested != "inherit" and not actual:
        raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: {role} requires its unchanged Claude transcript with native model metadata")
    return {
        "requested_model": requested,
        "actual_model": actual,
        "actual_model_status": "HOST_REPORTED_UNVERIFIED" if actual else "UNOBSERVED",
        "settings_sha256": (run.get("review_models") or {}).get("sha256"),
    }


def _matches_antigravity_native_model(
    expected_resolved: str,
    thinking_level: object,
    host_configured: object,
    host_reported_models: object,
) -> bool:
    """Validate observed Antigravity SQLite protobuf model metadata against the frozen reviewer selection.

    Supports all four Gemini 4 Hydrogen thinking levels (`low`, `medium`, `high`, `xhigh`/`extra`)
    and official Hydrogen backend/alias identifiers while strictly rejecting cross-family leaks
    (such as a parent Carbon/Argon/Claude model or legacy 3.8 Flash running instead of Hydrogen).
    """
    if not expected_resolved or not isinstance(host_configured, str) or not isinstance(host_reported_models, list) or not host_reported_models:
        return False
    family = re.sub(r"-(?:fast|low|medium|high|xhigh|extra|tiered)$", "", str(expected_resolved))
    lvl = str(thinking_level or "").strip().lower()
    valid_configured = {expected_resolved, family, f"{family}-tiered"}
    if lvl == "xhigh":
        valid_configured.add(f"{family}-extra")
    if family == "gemini-4-hydrogen":
        valid_configured.update({"gemini-4-flash", "gemini-4-flash-tiered"})
        if lvl:
            valid_configured.add(f"gemini-4-flash-{lvl}")
        if lvl == "xhigh":
            valid_configured.add("gemini-4-flash-extra")
        reported_re = re.compile(
            r"(?:gemini-4-hydrogen|gemini-4-flash)(?:-(?:n|fast|low|medium|high|xhigh|extra|tiered|preview(?:-[a-z0-9]+)*|[0-9]{3}))?"
        )
    else:
        reported_re = re.compile(
            re.escape(family) + r"(?:-(?:n|fast|low|medium|high|xhigh|extra|tiered|preview(?:-[a-z0-9]+)*|[0-9]{3}))?"
        )
    if host_configured not in valid_configured:
        return False
    for item in host_reported_models:
        if not isinstance(item, str) or (not reported_re.fullmatch(item) and item != expected_resolved):
            return False
    return True


def validate_model_evidence(run: dict, role: str, evidence: object) -> None:
    selection = frozen_models(run).get(role)
    if not selection or selection["requested_model"] == "inherit" or selection.get("resolved_model") == "inherit":
        return
    host_norm = str(run.get("review_host") or "").strip().lower()
    if host_norm == "antigravity":
        if not isinstance(evidence, dict) or (
            evidence.get("settings_sha256") != run["review_models"]["sha256"]
            or evidence.get("requested_model") != selection["requested_model"]
            or evidence.get("resolved_model") != selection.get("resolved_model")
            or evidence.get("thinking_level") != selection.get("thinking_level")
            or evidence.get("actual_model_status") != "NATIVE_METADATA_OBSERVED"
            or not evidence.get("native_metadata_sha256")
            or not evidence.get("execution_id")
            or not evidence.get("host_reported_models")
            or not _matches_antigravity_native_model(
                str(selection.get("resolved_model") or ""),
                selection.get("thinking_level"),
                evidence.get("host_configured_model"),
                evidence.get("host_reported_models"),
            )
        ):
            raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: missing or mismatched frozen Antigravity model evidence for {role}")
        native = {key: evidence[key] for key in ("execution_id", "host_configured_model", "host_reported_models", "native_metadata_source") if key in evidence}
        if evidence["native_metadata_sha256"] != canonical_sha256(native):
            raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: native model evidence integrity mismatch for {role}")
        return

    if not isinstance(evidence, dict) or (
        evidence.get("settings_sha256") != run["review_models"]["sha256"]
        or evidence.get("requested_model") != selection["requested_model"]
        or evidence.get("actual_model_status") != "HOST_REPORTED_UNVERIFIED"
        or not isinstance(evidence.get("actual_model"), str)
        or not re.match(r"claude-(?:[0-9]+(?:-[0-9]+)*-)?" + re.escape(selection["requested_model"]) + r"(?:-|$)", evidence["actual_model"])
    ):
        raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: missing or mismatched frozen model evidence for {role}")


def sync_specialist_agent_models(repo: Path, *, policy: dict | None = None, complexity_tier: str = "SIMPLE") -> list[str]:
    """Synchronize ON_DEMAND_SPECIALIST_AGENTS (`qa-diagnostics-agent`, `android-ui-expert-agent`) frontmatter models while preserving pure Antigravity scout tools."""
    agents_base = repo / ".agents" / "agents"
    subagents_base = repo / ".agents" / "subagents"
    if not subagents_base.is_dir():
        kit_subagents = Path(__file__).resolve().parents[1] / "subagents"
        if kit_subagents.is_dir():
            subagents_base = kit_subagents
    if not agents_base.is_dir() or not subagents_base.is_dir():
        return []
    try:
        from install_tool_adapters import with_managed_marker
        from policy_vocab import ANTIGRAVITY_SCOUT_TOOLS, ON_DEMAND_SPECIALIST_AGENTS
    except ImportError:
        return []
    pol = policy
    if pol is None:
        pol, src_scope = load_policy(repo, None)
        if src_scope == "default":
            pol = {"default": "inherit", "overrides": {}}
    updated: list[str] = []
    for sp_role in ON_DEMAND_SPECIALIST_AGENTS:
        sp_json = subagents_base / f"{sp_role}.json"
        dest = agents_base / sp_role / "agent.md"
        if not sp_json.is_file() or not dest.parent.is_dir():
            continue
        try:
            sp_data = json.loads(sp_json.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        req_m = (pol.get("overrides") or {}).get(sp_role, pol.get("default", "inherit"))
        fm_model = None
        if req_m and req_m != "inherit":
            resolved_m, _ = resolve_antigravity_model(str(req_m), sp_role, "NORMAL", complexity_tier=complexity_tier)
            if resolved_m and resolved_m != "inherit":
                fm_model = resolved_m
        sp_name = json.dumps(sp_role, ensure_ascii=False)
        sp_desc = json.dumps(str(sp_data.get("description") or sp_role).strip(), ensure_ascii=False)
        sp_tools = "\n".join(f"  - {t}" for t in ANTIGRAVITY_SCOUT_TOOLS)
        sp_prompt = str(sp_data.get("system_prompt") or "").strip()
        sp_model_line = f"model: {json.dumps(fm_model, ensure_ascii=False)}\n" if fm_model else ""
        sp_md = (
            f"---\nname: {sp_name}\ndescription: {sp_desc}\nmainAgent: false\nsubagent: true\n"
            f"{sp_model_line}tools:\n{sp_tools}\n---\n\n{sp_prompt}\n"
        )
        rendered_bytes = with_managed_marker(sp_md).encode("utf-8")
        if not dest.is_file() or dest.read_bytes() != rendered_bytes:
            from _vnext_common import atomic_write_bytes
            atomic_write_bytes(dest, rendered_bytes)
            updated.append(f".agents/agents/{sp_role}/agent.md")
    ownership_file = repo / ".harness-setup" / "ownership-v1.json"
    if updated and ownership_file.is_file():
        try:
            manifest = read_json(ownership_file)
            entries = manifest.get("entries")
            if isinstance(entries, list):
                changed = False
                updated_set = set(updated)
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("path") in updated_set:
                        target = repo / str(entry["path"])
                        if target.is_file():
                            entry["post_install_sha256"] = sha256_file(target)
                            changed = True
                if changed:
                    manifest["ownership_sha256"] = canonical_sha256(
                        {k: v for k, v in manifest.items() if k != "ownership_sha256"}
                    )
                    atomic_write_json(ownership_file, manifest)
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            pass
    return updated


def effective_reviewer_model(selection: dict | None) -> str:
    """Return a concise human-readable model label for a reviewer selection."""
    if not isinstance(selection, dict):
        return "inherit"
    resolved = str(selection.get("resolved_model") or selection.get("agent_frontmatter_model") or "").strip()
    requested = str(selection.get("requested_model") or "inherit").strip() or "inherit"
    actual = str(selection.get("actual_model") or "").strip()
    if resolved and resolved != "inherit":
        return resolved
    if requested not in ANTIGRAVITY_META_PRESETS:
        return actual or requested
    if actual:
        return f"inherit ({actual})"
    return "inherit"


def reviewer_model_map(run_or_profile: dict | None, reviewers: list[str] | None = None) -> dict[str, str]:
    """Map each reviewer role to its effective model label."""
    if not isinstance(run_or_profile, dict):
        return {role: "inherit" for role in (reviewers or [])}
    rev_source: dict[str, Any] = {}
    if isinstance(run_or_profile.get("review_models"), dict):
        rev_source = run_or_profile["review_models"].get("reviewers") or {}
    elif isinstance(run_or_profile.get("reviewers"), dict):
        rev_source = run_or_profile["reviewers"]
    roles = list(reviewers) if reviewers is not None else sorted(rev_source.keys())
    return {role: effective_reviewer_model(rev_source.get(role)) for role in roles}


def format_reviewers_with_models(run_or_profile: dict | None, reviewers: list[str]) -> str:
    """Format a list of reviewer roles with their active model in brackets."""
    mapping = reviewer_model_map(run_or_profile, reviewers)
    return ", ".join(f"{role} [{mapping.get(role, 'inherit')}]" for role in reviewers)


def antigravity_dispatch_model_hint(run_or_profile: dict | None, reviewers: list[str]) -> str:
    """Return an explicit per-reviewer `Model` parameter hint for Antigravity `invoke_subagent` calls."""
    mapping = reviewer_model_map(run_or_profile, reviewers)
    flash_roles = [r for r in reviewers if "flash" in str(mapping.get(r) or "")]
    pro_roles = [r for r in reviewers if "pro" in str(mapping.get(r) or "")]
    omit_roles = [r for r in reviewers if r not in flash_roles and r not in pro_roles]
    parts: list[str] = []
    if flash_roles:
        parts.append(f"pass Model='flash' for [{', '.join(flash_roles)}]")
    if pro_roles:
        parts.append(f"pass Model='pro' for [{', '.join(pro_roles)}]")
    if omit_roles:
        parts.append(f"omit Model for [{', '.join(omit_roles)}] (bound via agent.md frontmatter for hydrogen/argon/carbon or inherit)")
    return (" In invoke_subagent: " + "; ".join(parts) + ".") if parts else ""


def model_choice_summary(repo: Path, task_id: str) -> str:
    policy, source = load_policy(repo, task_id)
    overrides = ", ".join(f"{r}={m}" for r, m in sorted(policy["overrides"].items()))
    return (f"Reviewer model: {policy['default']} (source: {source})"
            + (f"; overrides: {overrides}" if overrides else "")
            + ". Model selection is separate from plan approval; an unresolved Antigravity choice is asked once before first dispatch.")


def build_antigravity_model_prompt(
    repo: Path,
    task_id: str,
    reviewers: list[str],
    *,
    run_id: str = "",
    phase_id: str = "",
    efforts_by_role: dict[str, str] | None = None,
) -> dict:
    """Build the 5-option developer prompt shown before the first review in a task/run on Antigravity."""
    efforts = efforts_by_role or _compute_efforts_by_role(repo, task_id, reviewers)
    complexity_tier = compute_task_complexity_tier(repo, task_id)
    hydrogen_argon_preview = {
        role: resolve_antigravity_model(
            "hydrogen-argon-hybrid",
            role,
            efforts.get(role, "NORMAL"),
            complexity_tier=complexity_tier,
        )[0]
        for role in reviewers
    }
    hydrogen_dynamic_preview = {
        role: resolve_antigravity_model(
            "hydrogen-dynamic",
            role,
            efforts.get(role, "NORMAL"),
            complexity_tier=complexity_tier,
        )[0]
        for role in reviewers
    }
    hydrogen_risk_preview = {
        role: resolve_antigravity_model("hydrogen-risk-hybrid", role, efforts.get(role, "NORMAL"))[0]
        for role in reviewers
    }
    flash_argon_preview = {
        role: resolve_antigravity_model(
            "flash-argon-hybrid",
            role,
            efforts.get(role, "NORMAL"),
            complexity_tier=complexity_tier,
        )[0]
        for role in reviewers
    }
    flash_preview = {
        role: resolve_antigravity_model("flash-dynamic", role, efforts.get(role, "NORMAL"))[0]
        for role in reviewers
    }
    hybrid_preview = {
        role: (
            "inherit"
            if role in CRITICAL_HYBRID_REVIEWERS
            else resolve_antigravity_model("flash-dynamic", role, efforts.get(role, "NORMAL"))[0]
        )
        for role in reviewers
    }
    options = []
    risk_hybrid_preview = {
        role: resolve_antigravity_model("risk-hybrid", role, efforts.get(role, "NORMAL"))[0]
        for role in reviewers
    }
    for key in (
        "hydrogen-argon-project",
        "hydrogen-argon-task",
        "hydrogen-dynamic-project",
        "hydrogen-risk-project",
        "inherit-task",
    ):
        item = ANTIGRAVITY_INTERACTIVE_CHOICES[key]
        options.append({
            "id": item["id"],
            "label_ar": item["label_ar"],
            "label_en": item["label_en"],
            "scope": item["scope"],
            "command": (
                f'python .agents/harness.py review models set --task-id {task_id} --host antigravity '
                f'--choice {item["id"]} --source conversation --proof-reference "<developer answer>"'
            ),
        })
    return {
        "code": "SELECT_REVIEW_MODEL",
        "tool": "ask_question",
        "task_id": task_id,
        "run_id": run_id,
        "phase_id": phase_id,
        "complexity_tier": complexity_tier,
        "reviewers": list(reviewers),
        "question_ar": "اختر موديل ومستوى تفكير المراجعين قبل بدء المراجعة:",
        "question_en": "Choose the reviewer model and thinking level before launching reviewers:",
        "hydrogen_argon_resolution": hydrogen_argon_preview,
        "hydrogen_dynamic_resolution": hydrogen_dynamic_preview,
        "hydrogen_risk_resolution": hydrogen_risk_preview,
        "flash_argon_resolution": flash_argon_preview,
        "flash_dynamic_resolution": flash_preview,
        "hybrid_smart_resolution": hybrid_preview,
        "risk_hybrid_resolution": risk_hybrid_preview,
        "options": options,
        "choices": options,
    }


def _is_undispatched_final_run(tdir: Path, current: dict) -> bool:
    run_id = str(current.get("run_id") or "")
    if not run_id:
        return False
    ledger_p = tdir / "review-execution" / run_id / "ledger.json"
    if ledger_p.is_file():
        try:
            ledger = read_json(ledger_p)
            for info in (ledger.get("reviewers") or {}).values():
                if isinstance(info, dict) and info.get("state") not in (None, "NOT_DISPATCHED"):
                    return False
        except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
            return False
    disp_dir = tdir / "reviewer-dispatches"
    if disp_dir.is_dir():
        for f in disp_dir.glob("*.json"):
            try:
                if str(read_json(f).get("run_id") or "") in ("", run_id):
                    return False
            except (OSError, ValueError, RuntimeError, KeyError, ImportError, ValidationError):
                return False
        if (disp_dir / run_id).is_dir() and any((disp_dir / run_id).glob("*.json")):
            return False
    staged_dir = tdir / "staged-reviews" / run_id
    if staged_dir.is_dir() and any(staged_dir.glob("*.json")):
        return False
    return True


def assert_dispatch_ready(repo: Path, run: dict, roles: list[str]) -> None:
    """Validate publication and bind shared native controls before spending calls.

    Callers hold the repository state lock through receipt publication. A pending
    launch keeps its native settings until its execution has been identified.
    """
    if (state_root(repo) / "review-model-update.json").exists():
        raise ValidationError("REVIEW_MODEL_UPDATE_INCOMPLETE: repeat the recorded model choice to finish publication")
    selections = frozen_models(run)
    if (run.get("review_models") or {}).get("selection_required"):
        raise ValidationError("SELECT_REVIEW_MODEL: record the developer's model choice before dispatch; plan approval is separate")
    if str(run.get("review_host") or "").lower() == "antigravity":
        active_policy, source = load_policy(repo, run.get("task_id"), run_id=run.get("phase_review_run_id") or run.get("run_id"))
        if source in {"task", "run"} and ((run.get("review_models") or {}).get("source") != source or (run.get("review_models") or {}).get("policy") != active_policy):
            raise ValidationError("REVIEW_MODEL_SELECTION_STALE: the active run does not bind the recorded task/run choice")
        sync_antigravity_agent_models(repo, {r: selections[r] for r in roles if r in selections})
        for role in roles:
            selection = selections.get(role, {})
            expected = selection.get("agent_frontmatter_model") or selection.get("resolved_model")
            expected = None if expected == "inherit" else expected
            if _antigravity_frontmatter_model(repo, role) != expected:
                raise ValidationError(f"REVIEW_MODEL_CONFIGURATION_UNAVAILABLE: {role} native configuration is not synchronized")


def _is_undispatched_phase_run(tdir: Path, phase_id: str) -> tuple[bool, Path | None]:
    from phase_review import phase_run_file, phase_ledger_file, load_phase_ledger, phase_review_dir
    prun_f = phase_run_file(tdir, phase_id)
    if not prun_f.is_file():
        return True, None
    run = read_json(prun_f)
    ok, reason, ledger = load_phase_ledger(tdir, phase_id, expected_run_id=run.get("phase_review_run_id"))
    if not ok:
        raise ValidationError(f"phase review ledger cannot establish an unstarted review: {reason}")
    if any(info.get("state") != "NOT_DISPATCHED" for info in ledger["reviewers"].values()):
        return False, prun_f
    if any((phase_review_dir(tdir, phase_id) / "dispatch" / str(run["phase_review_run_id"])).glob("*.json")):
        return False, prun_f
    return True, prun_f


def _refresh_undispatched_runs(repo: Path, task_id: str, host: str) -> dict[str, Any]:
    """Refresh active undispatched final or phase review run and regenerate briefs when model choice changes."""
    tdir = task_dir(repo, task_id)
    plan_f = tdir / "plan.json"
    if not plan_f.is_file():
        return {}
    plan = read_json(plan_f)
    refreshed: dict[str, Any] = {}

    # 1. Check active phase review run if in IMPLEMENTING
    pstate_f = tdir / "phase-state.json"
    if plan.get("status") == "IMPLEMENTING" and pstate_f.is_file():
        pstate = read_json(pstate_f)
        phase_id = str(pstate.get("current_phase_id") or "")
        ok_phase, prun_f = _is_undispatched_phase_run(tdir, phase_id)
        if ok_phase and prun_f:
            from phase_review import refresh_undispatched_phase_models
            run_meta = refresh_undispatched_phase_models(repo, task_id, phase_id)
            refreshed["phase_review_run_id"] = run_meta["phase_review_run_id"]
            refreshed["active_run_models"] = run_meta["review_models"]["reviewers"]

    # 2. Check active final verification run if in VERIFYING
    crun_f = tdir / "current-run.json"
    if plan.get("status") == "VERIFYING" and crun_f.is_file():
        current = read_json(crun_f)
        if _is_undispatched_final_run(tdir, current):
            pol_p = Path(str(current.get("policy") or ""))
            policy_data = read_json(pol_p) if pol_p.is_file() else {}
            roster = list(policy_data.get("reviewers") or [])
            run_id = str(current.get("run_id") or "")
            run_host = str(current.get("review_host") or host)
            frozen = freeze_models(
                repo, task_id, run_host, roster, run_id=run_id, policy_data=policy_data, plan=plan
            )
            current["review_models"] = frozen
            atomic_write_json(crun_f, current)
            pkg_path = active_review_package_path(repo, current)
            if pkg_path.is_file():
                pkg_dir = pkg_path.parent
                pkg_path.unlink(missing_ok=True)
                for b_file in pkg_dir.glob("brief-*.md"):
                    b_file.unlink(missing_ok=True)
                ledger_p = tdir / "review-execution" / run_id / "ledger.json"
                ledger_p.unlink(missing_ok=True)
                from review_package import build_package
                build_package(repo, task_id)
            refreshed["run_id"] = run_id
            refreshed["active_run_models"] = frozen.get("reviewers") or {}

    return refreshed


def set_policy(
    repo: Path,
    policy: dict,
    *,
    task_id: str | None,
    host: str,
    source: str,
    proof_reference: str,
    scope: str | None = None,
) -> dict:
    if source not in ("conversation", "developer_terminal") or not proof_reference.strip():
        raise ValidationError("review model changes require explicit developer source and proof-reference")
    policy = validate_for_host(policy, host)
    resolved_scope = scope or ("task" if task_id else "project")
    if resolved_scope not in ("project", "task", "run"):
        raise ValidationError("scope must be project, task, or run")
    if resolved_scope in ("task", "run") and not task_id:
        raise ValidationError(f"scope '{resolved_scope}' requires --task-id")

    with StateLock(state_root(repo)):
        pending_file = state_root(repo) / "review-model-update.json"
        operation = {"task_id": task_id, "scope": resolved_scope, "host": host, "policy": policy}
        if pending_file.exists() and read_json(pending_file) != operation:
            raise ValidationError("REVIEW_MODEL_UPDATE_INCOMPLETE: repeat the pending model choice before making another change")

        def already_applied(run: dict) -> dict | None:
            path = _policy_file(repo, task_id, scope=resolved_scope)
            if pending_file.exists() or not path.is_file():
                return None
            existing = read_json(path)
            if existing.get("record_sha256") != canonical_sha256({k: v for k, v in existing.items() if k != "record_sha256"}):
                raise ValidationError("review model configuration checksum mismatch")
            frozen_models(run)
            if (existing.get("policy") == policy and existing.get("scope") == resolved_scope
                    and existing.get("validated_host") == host
                    and (run.get("review_models") or {}).get("policy") == policy
                    and (run.get("review_models") or {}).get("source") == resolved_scope):
                return {**existing, "already_applied": True}
            return None
        bound_run_id = None
        if task_id:
            tdir = task_dir(repo, task_id)
            plan_path = tdir / "plan.json"
            if not plan_path.is_file():
                raise ValidationError(f"task '{task_id}' has no plan.json")
            plan = read_json(plan_path)
            status = str(plan.get("status") or "")
            if status == "VERIFYING":
                crun_f = tdir / "current-run.json"
                if not crun_f.is_file() or not _is_undispatched_final_run(tdir, read_json(crun_f)):
                    previous = already_applied(read_json(crun_f)) if crun_f.is_file() else None
                    if previous:
                        return previous
                    raise ValidationError("task model choices require an unstarted review; resume implementation before changing future runs")
                bound_run_id = str(read_json(crun_f).get("run_id") or "next_run")
            elif status == "IMPLEMENTING":
                pstate_f = tdir / "phase-state.json"
                if pstate_f.is_file():
                    pstate = read_json(pstate_f)
                    cur_phase = str(pstate.get("current_phase_id") or "")
                    if cur_phase:
                        ok_phase, prun_f = _is_undispatched_phase_run(tdir, cur_phase)
                        if not ok_phase:
                            previous = already_applied(read_json(prun_f)) if prun_f else None
                            if previous:
                                return previous
                            raise ValidationError("phase review already dispatched; finish or re-checkpoint before changing reviewer models")
                        if prun_f and prun_f.is_file():
                            bound_run_id = str(read_json(prun_f).get("phase_review_run_id") or "next_run")
                if not bound_run_id:
                    bound_run_id = "next_run"
            elif status in ("AWAITING_DEVELOPER_APPROVAL", "APPROVED"):
                bound_run_id = "next_run"
            else:
                raise ValidationError("task model choices require an unstarted review; resume implementation before changing future runs")

        record: dict[str, Any] = {
            "schema_version": 1,
            "scope": resolved_scope,
            "task_id": task_id if resolved_scope in ("task", "run") else None,
            "policy": policy,
            "validated_host": host,
            "source": source,
            "proof_reference": proof_reference.strip(),
            "updated_at": utc_now(),
        }
        if resolved_scope == "run":
            record["bound_run_id"] = bound_run_id or "next_run"
        record["record_sha256"] = canonical_sha256(record)
        target_file = _policy_file(repo, task_id if resolved_scope in ("task", "run") else None, scope=resolved_scope)
        atomic_write_json(pending_file, operation)
        # The marker survives interruption. Dispatch remains blocked until the same
        # explicit operation has repaired all derived artifacts under this lock.
        atomic_write_json(target_file, record)

        if resolved_scope == "task" and task_id:
            # A task-wide choice supersedes any prior one-time run file on this task.
            _policy_file(repo, task_id, scope="run").unlink(missing_ok=True)

        if str(host).strip().lower() == "antigravity":
            efforts = _compute_efforts_by_role(repo, task_id, list(CORE_ROUTED_REVIEWERS))
            complexity_tier = compute_task_complexity_tier(repo, task_id)
            resolved_all = _resolve_policy(
                policy,
                resolved_scope,
                host,
                list(CORE_ROUTED_REVIEWERS),
                efforts_by_role=efforts,
                complexity_tier=complexity_tier,
            )
            sync_antigravity_agent_models(repo, resolved_all.get("reviewers") or {})
            sync_specialist_agent_models(repo, policy=policy, complexity_tier=complexity_tier)
            try:
                from delegation_policy import sync_utility_agent_models
                sync_utility_agent_models(repo, task_id=task_id)
                unloaded_cache = state_root(repo) / "cache" / "unloaded-utility-agents.json"
                unloaded_cache.unlink(missing_ok=True)
            except (ImportError, OSError, ValueError, RuntimeError, ValidationError):
                pass

        if task_id:
            refreshed = _refresh_undispatched_runs(repo, task_id, host)
            if refreshed:
                record["refreshed_run"] = refreshed

        pending_file.unlink()
        return record


def main(argv: list[str] | None = None) -> int:
    from _vnext_common import configure_utf8_output
    configure_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("show", "set"), nargs="?", default="show")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", "--task-id", dest="task")
    parser.add_argument("--host")
    parser.add_argument("--choice", "--mode", dest="choice", help="Interactive choice ID (e.g. hydrogen-argon-project, hydrogen-argon-task, hydrogen-dynamic-project, hydrogen-risk-project, flash-argon-project, inherit-task)")
    parser.add_argument("--preset", choices=("hydrogen-argon-hybrid", "argon-hydrogen-hybrid", "hydrogen-argon", "hydrogen-hybrid", "safe-cache-hybrid", "safe-cache", "hydrogen-safe-cache", "hydrogen-dynamic", "hydrogen", "hydrogen-risk-hybrid", "hydrogen-risk", "flash-argon-hybrid", "argon-flash-hybrid", "flash-argon", "flash-dynamic", "risk-hybrid", "adaptive-hybrid", "inherit", "hybrid-smart", "flash", "hybrid"), help="Preset reviewer model profile")
    parser.add_argument("--scope", choices=("project", "task", "run"), default=None, help="Policy persistence scope (project, task, or run/once)")
    parser.add_argument("--default", default="inherit", help="Default reviewer model or model@effort")
    parser.add_argument("--reviewer", action="append", default=[], metavar="ROLE=MODEL")
    parser.add_argument("--source", choices=("conversation", "developer_terminal"))
    parser.add_argument("--proof-reference", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        from review_sources import resolve_review_host
        host = resolve_review_host(repo, args.host)
        if args.action == "set":
            scope = args.scope
            if args.choice:
                policy, choice_scope = resolve_interactive_choice(args.choice)
                scope = scope or choice_scope
            elif args.preset:
                policy = resolve_preset_policy(args.preset)
            else:
                overrides = {}
                for item in args.reviewer:
                    role, sep, model = item.partition("=")
                    if not sep or role in overrides:
                        raise ValidationError("--reviewer requires unique ROLE=MODEL entries")
                    overrides[role] = normalize_model_token(model)
                policy = {
                    "schema_version": 1,
                    "default": normalize_model_token(args.default),
                    "overrides": overrides,
                }
            result = set_policy(
                repo,
                policy,
                task_id=args.task,
                host=host,
                source=args.source,
                proof_reference=args.proof_reference,
                scope=scope,
            )
            result["applies_to"] = (
                "current review run only; subsequent review runs will prompt again"
                if result.get("scope") == "run"
                else "all review runs in this task"
                if result.get("scope") == "task"
                else "future review runs across the project; existing runs are unchanged"
            )
            if str(host).strip().lower() == "antigravity":
                result["dispatch_hint"] = (
                    "When calling invoke_subagent, pass Model='flash' ONLY for legacy 3.8-flash reviewers whose model in reviewer_models contains 'flash', "
                    "pass Model='pro' for reviewers whose model contains 'pro', "
                    "and omit Model (INHERIT_PARENT_BY_OMISSION / bound via .agents/agents/<role>/agent.md frontmatter) for inherit, gemini-4-hydrogen-*, gemini-4-argon-*, or gemini-4-carbon-* reviewers."
                )
        else:
            policy, source = load_policy(repo, args.task)
            result = {"policy": policy, "source": source, "capability": host_capability(host)}
            if args.task:
                path = task_dir(repo, args.task) / "current-run.json"
                if path.is_file():
                    run = read_json(path)
                    result["active_run_models"] = frozen_models(run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValidationError, OSError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
