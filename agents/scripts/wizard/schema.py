"""Centralized Answer Schema for Android Agent Harness.

Provides the single source of truth for setup answer keys, allowable values,
and validation logic across the interactive wizard, non-interactive CLI (--answers-json),
and the self-contained chat installation prompt.
"""
from __future__ import annotations

import re
from typing import Any

from .i18n import PM_PROVIDER_IDS, SCHEMA, TOOL_IDS

ALLOWED_QUESTION_KEYS = {
    "i0",
    "i1",
    "i1_text",
    "i2",
    "i3",
    "i4",
    "i5",
    "i5_text",
    "i6",
    "i6_text",
    "i6b",
    "i6b_text",
    "i7",
    "i8",
    "i8_text",
    "i10",
    "i12",
    "i13",
    "i14",
    "i15",
    "i16",
    "i17",
    "i18",
    "i19",
    "i19_text",
    "i20",
    "i22",
    "b_platform",
    "b_arch",
    "b_di",
    "b_nav",
    "b_ui",
    "b_db",
    "b_net",
    "b_locales",
}

ALLOWED_NORMALIZED_KEYS = {
    "schema",
    "i0",
    "backup",
    "product",
    "py",
    "git_policy",
    "device_policy",
    "module",
    "application_id",
    "android_src",
    "project_kind",
    "assemble",
    "build_variant",
    "flavor_mode",
    "flavor",
    "assemble_tasks",
    "launcher",
    "apk",
    "apk_path",
    "architecture",
    "architecture_mode",
    "bootstrap_details",
    "di_framework",
    "ui_framework",
    "project_structure",
    "supported_locales",
    "locales",
    "scaffold",
    "install_confirm",
    "agents_git",
    "gemini_config",
    "assemble_now",
    "unit_tests",
    "zoho_mcp",
    "chat_language",
    "zoho_language",
    "pm_provider",
    "tools",
    "git_gate",
    "device_verification",
    "asked",
}

CANONICAL_PROMPT_KEYS = (
    "i0",
    "i1",
    "i5",
    "i19",
    "i15",
    "i4",
    "i14",
    "i20",
    "i17",
)


def validate_raw_answers(payload: Any) -> list[str]:
    """Validate a raw answers JSON dictionary against ANSWER_SCHEMA.

    Rejects unknown keys, malformed types, and ambiguous or out-of-range values.
    Returns a list of error strings; an empty list indicates full compliance.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["answers payload must be a JSON object"]

    # If payload is already a fully normalized answers dict
    if payload.get("schema") == SCHEMA and "product" in payload and "module" in payload:
        unknown_norm = set(payload.keys()) - ALLOWED_NORMALIZED_KEYS
        if unknown_norm:
            errors.append(f"unknown normalized answers keys: {', '.join(sorted(unknown_norm))}")
        return errors

    # Otherwise validate raw question keys
    unknown_keys = set(payload.keys()) - ALLOWED_QUESTION_KEYS
    if unknown_keys:
        errors.append(f"unknown question keys in answers payload: {', '.join(sorted(unknown_keys))}")

    # Validate i0 (Install & backup choice)
    if "i0" in payload:
        val = payload["i0"]
        if val not in ("yes", "skip", "no", True, False):
            errors.append("i0 must be one of 'yes', 'skip', 'no', or boolean")

    # Validate i14 / tools (must be valid tool IDs or 'all')
    if "i14" in payload:
        tools_val = payload["i14"]
        if isinstance(tools_val, str):
            tool_items = [x.strip() for x in tools_val.split(",") if x.strip()]
        elif isinstance(tools_val, list):
            tool_items = tools_val
        else:
            errors.append("i14 (tools) must be a list or comma-separated string")
            tool_items = []

        valid_tools = set(TOOL_IDS) | {"all"}
        for t_item in tool_items:
            if not isinstance(t_item, str) or t_item not in valid_tools:
                errors.append(f"invalid tool id '{t_item}' in i14; valid tools: {', '.join(TOOL_IDS)}")

    # Validate i20 (PM provider)
    if "i20" in payload:
        pm_val = str(payload["i20"]).strip()
        if pm_val not in PM_PROVIDER_IDS:
            errors.append(f"invalid pm_provider '{pm_val}' in i20; valid: {', '.join(PM_PROVIDER_IDS)}")

    # Validate i15 (Unit tests)
    if "i15" in payload:
        val = payload["i15"]
        if val not in ("yes", "no", True, False):
            errors.append("i15 (unit_tests) must be 'yes' or 'no'")

    # Validate i17 (Chat language)
    if "i17" in payload:
        val = payload["i17"]
        if val not in ("mirror", "en", "ar"):
            errors.append("i17 (chat_language) must be 'mirror', 'en', or 'ar'")

    # Validate i18 (Zoho language)
    if "i18" in payload:
        val = payload["i18"]
        if val not in ("en_titles_ar_comments", "all_en", "all_ar"):
            errors.append("i18 (zoho_language) must be 'en_titles_ar_comments', 'all_en', or 'all_ar'")

    # Validate i22 (Device verification)
    if "i22" in payload:
        val = payload["i22"]
        if val not in ("manual_only", "disabled"):
            errors.append("i22 (device_verification) must be 'manual_only' or 'disabled'")

    # Check for string length / safety
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > 2048:
            errors.append(f"value for key '{key}' exceeds maximum permitted length (2048 characters)")

    return errors
