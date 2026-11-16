#!/usr/bin/env python3
"""Interactive Human Review Cockpit v3 (`human-review.html` / `harness.py review-diff`).

Builds a self-contained, zero-dependency, Antigravity-Dark HTML5 review cockpit with:
- High-legibility 1080p typography (`16px` base UI, `14px` code, live `A- / A+` font scaling).
- Model-authored bilingual human brief (`review-brief.json` via `review-diff --title-ar ...` or `task review-brief`)
  paired with a deep Android/Kotlin fallback synthesizer when no brief was supplied.
- Clean short task headline (never a raw slug or 50-word paragraph) + 3-column Executive Story Strip
  (Why / Problem, How It Was Solved, Quick Human Checklist).
- Always-visible plain-language explanation directly on every collapsed file header.
- Translated, auto-collapsed AI Review History & Unmodified Callers drawers so resolved walls of English text
  never clutter Arabic RTL review.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import webbrowser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import (  # noqa: E402
    ValidationError,
    atomic_write_bytes,
    atomic_write_json,
    configure_utf8_output,
    read_json,
    state_root,
    utc_now,
    validate_id,
)
from delivery_manifest import SECRET_PATH_MARKERS, build_task_diff, build_task_manifest  # noqa: E402

BINARY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ttf", ".otf",
    ".wav", ".mp3", ".ogg", ".mp4", ".jar", ".aar", ".so", ".apk", ".bin",
})

AR_STRINGS: dict[str, str] = {
    "app_badge": "\u0645\u0631\u0627\u062c\u0639\u0629 \u0627\u0644\u0643\u0648\u062f \u0627\u0644\u0646\u0647\u0627\u0626\u064a\u0629",
    "lang_btn": "English (LTR)",
    "reviewed_progress": "\u0631\u0627\u062c\u0639\u062a",
    "of_word": "\u0645\u0646",
    "files_word": "\u0645\u0644\u0641\u0627\u062a",
    "filter_all": "\u0627\u0644\u0643\u0644",
    "filter_hotspot": "\u0627\u0644\u0623\u0647\u0645 \u0644\u0644\u0645\u0631\u0627\u062c\u0639\u0629",
    "filter_side_effect": "\u062e\u0627\u0631\u062c \u0627\u0644\u0646\u0637\u0627\u0642 \u0627\u0644\u0623\u0648\u0644",
    "filter_ai_notes": "\u0645\u0644\u0627\u062d\u0638\u0627\u062a \u0627\u0644\u0641\u062d\u0635",
    "expand_all": "\u0641\u062a\u062d \u0627\u0644\u0643\u0644",
    "collapse_boilerplate": "\u0637\u064a\u0651 \u0627\u0644\u0631\u0648\u062a\u064a\u0646\u064a",
    "sidebar_title": "\u062a\u0631\u062a\u064a\u0628 \u0627\u0644\u0645\u0639\u0645\u0627\u0631\u064a\u0629",
    "story_problem": "1. \u0627\u0644\u0645\u0634\u0643\u0644\u0629 \u0648\u0627\u0644\u0647\u062f\u0641",
    "story_solution": "2. \u0625\u064a\u0647 \u0627\u0644\u0644\u064a \u0627\u062a\u0639\u0645\u0644 \u0628\u0627\u062e\u062a\u0635\u0627\u0631\u061f",
    "story_check": "3. \u0631\u0627\u062c\u0639 \u0628\u0639\u064a\u0646\u0643 \u0641\u064a \u062f\u0642\u064a\u0642\u062a\u064a\u0646",
    "side_effect_title": "\u062a\u0646\u0628\u064a\u0647: \u0645\u0644\u0641\u0627\u062a \u0639\u064f\u062f\u0651\u0644\u062a \u062e\u0627\u0631\u062c \u0627\u0644\u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u0645\u0628\u062f\u0626\u064a\u0629 \u0644\u0644\u062e\u0637\u0629",
    "blast_title": "\u0645\u0644\u0641\u0627\u062a \u0645\u0631\u062a\u0628\u0637\u0629 \u062a\u0633\u062a\u062f\u0639\u064a \u0627\u0644\u0643\u0648\u062f \u0627\u0644\u0645\u0639\u062f\u0651\u0644 \u0648\u0644\u0645 \u062a\u062a\u063a\u064a\u0631",
    "blast_sub": "\u0644\u0644\u062a\u0623\u0643\u062f \u0627\u0644\u0633\u0631\u064a\u0639 \u0623\u0646 \u062a\u0639\u062f\u064a\u0644\u0646\u0627 \u0644\u0645 \u064a\u0643\u0633\u0631 \u0623\u064a \u0634\u0627\u0634\u0629 \u0623\u062e\u0631\u0649 \u062a\u0639\u062a\u0645\u062f \u0639\u0644\u064a\u0647",
    "blast_empty": "\u0644\u0627 \u062a\u0648\u062c\u062f \u0627\u0633\u062a\u062f\u0639\u0627\u0621\u0627\u062a \u062e\u0627\u0631\u062c\u064a\u0629 \u0641\u064a \u0645\u0644\u0641\u0627\u062a \u063a\u064a\u0631 \u0645\u0639\u062f\u0651\u0644\u0629.",
    "col_symbol": "\u0627\u0644\u062f\u0627\u0644\u0629 / \u0627\u0644\u0643\u0644\u0627\u0633 \u0627\u0644\u0645\u0639\u062f\u0651\u0644",
    "col_caller": "\u0627\u0644\u0645\u0644\u0641 \u0627\u0644\u0645\u0633\u062a\u062f\u0639\u064a",
    "col_snippet": "\u0633\u0637\u0631 \u0627\u0644\u0627\u0633\u062a\u062f\u0639\u0627\u0621",
    "col_action": "\u0641\u062a\u062d",
    "xray_title": "\u0633\u062c\u0644 \u0641\u062d\u0635 \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u064a\u0646 \u0627\u0644\u0622\u0644\u064a\u064a\u0646",
    "xray_all_resolved": "\u0627\u062c\u062a\u0627\u0632 \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0648\u0646 \u0627\u0644\u062b\u0644\u0627\u062b\u0629 \u0628\u0646\u062c\u0627\u062d \u2014 \u062a\u0645 \u0631\u0635\u062f \u0648\u062d\u0644 \u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a \u0627\u0644\u0633\u0627\u0628\u0642\u0629 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b (\u0627\u0636\u063a\u0637 \u0644\u0644\u062a\u0641\u0627\u0635\u064a\u0644)",
    "xray_has_notes": "\u0645\u0644\u0627\u062d\u0638\u0627\u062a \u0645\u0646 \u062c\u0648\u0644\u0627\u062a \u0627\u0644\u0641\u062d\u0635 \u0627\u0644\u0622\u0644\u064a (\u0627\u0636\u063a\u0637 \u0644\u0644\u062a\u0641\u0627\u0635\u064a\u0644)",
    "why_label": "\u0627\u0644\u0647\u062f\u0641 \u0645\u0646 \u062a\u0639\u062f\u064a\u0644 \u0627\u0644\u0645\u0644\u0641:",
    "mark_reviewed": "\u062a\u0645\u062a \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629",
    "open_ide": "\u0641\u062a\u062d \u0641\u064a IDE",
    "copy_path": "\u0646\u0633\u062e \u0627\u0644\u0645\u0633\u0627\u0631",
    "add_note": "+ \u0645\u0644\u0627\u062d\u0638\u0629 \u062a\u0639\u062f\u064a\u0644",
    "badge_hotspot": "\u0645\u0647\u0645 \u0644\u0644\u0645\u0631\u0627\u062c\u0639\u0629",
    "badge_core": "\u062a\u0639\u062f\u064a\u0644 \u0623\u0633\u0627\u0633\u064a",
    "badge_collapsed": "\u0627\u062e\u062a\u0628\u0627\u0631 / \u0631\u0648\u062a\u064a\u0646\u064a",
    "badge_side_effect": "\u0625\u0636\u0627\u0641\u064a",
    "badge_resolved": "\u062a\u0645 \u062d\u0644\u0647\u0627 \u0642\u0628\u0644 \u0627\u0644\u062a\u0633\u0644\u064a\u0645",
    "badge_advisory": "\u0645\u0644\u0627\u062d\u0638\u0629 \u062a\u062d\u0633\u064a\u0646\u064a\u0629",
    "badge_active": "\u062a\u062d\u062a\u0627\u062c \u0627\u0646\u062a\u0628\u0627\u0647",
    "dock_title": "\u0645\u0637\u0644\u0648\u0628 \u062a\u0639\u062f\u064a\u0644 \u0625\u0636\u0627\u0641\u064a\u061f",
    "dock_hint": "\u0627\u0636\u063a\u0637 (+ \u0645\u0644\u0627\u062d\u0638\u0629 \u062a\u0639\u062f\u064a\u0644) \u0628\u062c\u0627\u0646\u0628 \u0623\u064a \u0633\u0637\u0631 \u0644\u0643\u062a\u0627\u0628\u0629 \u062a\u0639\u062f\u064a\u0644\u0643\u060c \u062b\u0645 \u0627\u0646\u0633\u062e \u0627\u0644\u0623\u0645\u0631 \u062c\u0627\u0647\u0632\u0627\u064b \u0644\u0644\u0635\u0642\u0647 \u0641\u064a Antigravity.",
    "clear_notes": "\u0645\u0633\u062d \u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a",
    "copy_prompt": "\u0646\u0633\u062e \u0623\u0645\u0631 \u0627\u0644\u062a\u0639\u062f\u064a\u0644 \u0644\u0640 Antigravity",
    "copied_toast": "\u062a\u0645 \u0646\u0633\u062e \u0627\u0644\u0623\u0645\u0631!",
    "note_placeholder": "\u0627\u0643\u062a\u0628 \u0627\u0644\u062a\u0639\u062f\u064a\u0644 \u0627\u0644\u0630\u064a \u062a\u0631\u064a\u062f\u0647 \u0641\u064a \u0647\u0630\u0627 \u0627\u0644\u0633\u0637\u0631...",
    "note_saved": "\u062a\u0645 \u0627\u0644\u062d\u0641\u0638 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b \u0641\u064a \u0627\u0644\u0645\u062a\u0635\u0641\u062d",
    "remove_btn": "\u062d\u0630\u0641",
    "notes_count_suffix": "\u0645\u0644\u0627\u062d\u0638\u0629",
    "zoom_in": "\u062a\u0643\u0628\u064a\u0631 \u0627\u0644\u062e\u0637",
    "zoom_out": "\u062a\u0635\u063a\u064a\u0631 \u0627\u0644\u062e\u0637",
    "layer_DOMAIN": "1. \u0627\u0644\u0646\u0637\u0627\u0642 \u0648\u062d\u0642\u0646 \u0627\u0644\u0627\u0639\u062a\u0645\u0627\u062f\u064a\u0627\u062a (Domain & DI)",
    "layer_DATA": "2. \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0648\u0627\u0644\u062e\u062f\u0645\u0627\u062a \u0627\u0644\u062e\u0644\u0641\u064a\u0629 (Data & Services)",
    "layer_VIEWMODEL": "3. \u0625\u062f\u0627\u0631\u0629 \u0627\u0644\u062d\u0627\u0644\u0629 (ViewModel & State)",
    "layer_UI_NAV": "4. \u0627\u0644\u0634\u0627\u0634\u0627\u062a \u0648\u0627\u0644\u062a\u0646\u0642\u0644 (UI & Screens)",
    "layer_RESOURCES_CONFIG": "5. \u0627\u0644\u0645\u0648\u0627\u0631\u062f \u0648\u0627\u0644\u0625\u0639\u062f\u0627\u062f\u0627\u062a (Resources & Config)",
    "layer_TESTS": "6. \u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a \u0627\u0644\u0622\u0644\u064a\u0629 (Unit Tests)",
}

LAYER_DEFINITIONS: tuple[tuple[int, str, str], ...] = (
    (1, "DOMAIN", "1. Domain & DI Contracts"),
    (2, "DATA", "2. Data, Repositories & Services"),
    (3, "VIEWMODEL", "3. Presentation State & ViewModel"),
    (4, "UI_NAV", "4. UI, Screens & Navigation"),
    (5, "RESOURCES_CONFIG", "5. Resources, Manifest & Build Config"),
    (6, "TESTS", "6. Automated Tests & Verification Suites"),
)

_SLUG_WORD_AR: dict[str, str] = {
    "fix": "\u0625\u0635\u0644\u0627\u062d",
    "resolve": "\u0645\u0639\u0627\u0644\u062c\u0629",
    "prevent": "\u0645\u0646\u0639",
    "remove": "\u0625\u0632\u0627\u0644\u0629",
    "add": "\u0625\u0636\u0627\u0641\u0629",
    "update": "\u062a\u062d\u062f\u064a\u062b",
    "refactor": "\u0625\u0639\u0627\u062f\u0629 \u0647\u064a\u0643\u0644\u0629",
    "optimize": "\u062a\u062d\u0633\u064a\u0646 \u0623\u062f\u0627\u0621",
    "harden": "\u062a\u0623\u0645\u064a\u0646",
    "sync": "\u0645\u0632\u0627\u0645\u0646\u0629",
    "location": "\u0627\u0644\u0645\u0648\u0642\u0639",
    "gps": "\u062a\u062d\u062f\u064a\u062f \u0627\u0644\u0645\u0648\u0642\u0639",
    "callback": "\u0645\u0633\u062a\u0645\u0639\u0627\u062a (Callback)",
    "callbacks": "\u0627\u0644\u0645\u0633\u062a\u0645\u0639\u0627\u062a",
    "leak": "\u062a\u0633\u0631\u064a\u0628 \u0627\u0644\u0645\u0648\u0627\u0631\u062f",
    "leaks": "\u062a\u0633\u0631\u064a\u0628\u0627\u062a \u0627\u0644\u0645\u0648\u0627\u0631\u062f",
    "memory": "\u0627\u0644\u0630\u0627\u0643\u0631\u0629",
    "battery": "\u0627\u0633\u062a\u0647\u0644\u0627\u0643 \u0627\u0644\u0628\u0637\u0627\u0631\u064a\u0629",
    "sensor": "\u062d\u0633\u0627\u0633 \u0627\u0644\u062e\u0637\u0648\u0627\u062a",
    "step": "\u0639\u062f\u0627\u062f \u0627\u0644\u062e\u0637\u0648\u0627\u062a",
    "steps": "\u0627\u0644\u062e\u0637\u0648\u0627\u062a",
    "onboarding": "\u0627\u0644\u062a\u0647\u064a\u0626\u0629 \u0627\u0644\u0623\u0648\u0644\u0649",
    "payment": "\u0627\u0644\u062f\u0641\u0639",
    "billing": "\u0627\u0644\u0627\u0634\u062a\u0631\u0627\u0643\u0627\u062a \u0648\u0627\u0644\u062f\u0641\u0639",
    "paywall": "\u0628\u0648\u0627\u0628\u0629 \u0627\u0644\u0627\u0634\u062a\u0631\u0627\u0643",
    "auth": "\u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644",
    "login": "\u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644",
    "token": "\u062c\u0644\u0633\u0629 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645",
    "crash": "\u0627\u0646\u0647\u064a\u0627\u0631 \u0627\u0644\u062a\u0637\u0628\u064a\u0642",
    "race": "\u062a\u062f\u0627\u062e\u0644 \u0627\u0644\u062e\u064a\u0648\u0637",
    "cache": "\u0627\u0644\u062a\u062e\u0632\u064a\u0646 \u0627\u0644\u0645\u0624\u0642\u062a",
    "caching": "\u0627\u0644\u062a\u062e\u0632\u064a\u0646 \u0627\u0644\u0645\u0624\u0642\u062a",
    "food": "\u0627\u0644\u062e\u0637\u0629 \u0627\u0644\u063a\u0630\u0627\u0626\u064a\u0629",
    "foodplan": "\u0627\u0644\u062e\u0637\u0629 \u0627\u0644\u063a\u0630\u0627\u0626\u064a\u0629",
    "foodplans": "\u0627\u0644\u062e\u0637\u0637 \u0627\u0644\u063a\u0630\u0627\u0626\u064a\u0629",
    "calories": "\u0627\u0644\u0633\u0639\u0631\u0627\u062a \u0627\u0644\u062d\u0631\u0627\u0631\u064a\u0629",
    "home": "\u0627\u0644\u0634\u0627\u0634\u0629 \u0627\u0644\u0631\u0626\u064a\u0633\u064a\u0629",
    "running": "\u0634\u0627\u0634\u0629 \u0627\u0644\u062c\u0631\u064a",
    "map": "\u0627\u0644\u062e\u0631\u064a\u0637\u0629",
    "viewmodel": "\u0625\u062f\u0627\u0631\u0629 \u0627\u0644\u062d\u0627\u0644\u0629",
    "navigation": "\u0627\u0644\u062a\u0646\u0642\u0644",
    "cockpit": "\u0644\u0648\u062d\u0629 \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629",
    "demo": "\u062a\u062c\u0631\u064a\u0628\u064a",
    "task": "\u0627\u0644\u0645\u0647\u0645\u0629",
}

_HOTSPOT_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "Billing / Auth / Security",
        "\u0645\u0646\u0637\u0642 \u062f\u0641\u0639 \u0623\u0648 \u062d\u0645\u0627\u064a\u0629",
        re.compile(
            r"\b(billing|payment|purchase|subscription|price|token|secret|auth|biometric|PendingIntent|"
            r'exported\s*=\s*"true"|setJavaScriptEnabled|SharedPreferences|EncryptedSharedPreferences)\b',
            re.IGNORECASE,
        ),
    ),
    (
        "Lifecycle & Resource Cleanup",
        "\u0625\u062f\u0627\u0631\u0629 \u062f\u0648\u0631\u0629 \u0627\u0644\u062d\u064a\u0627\u0629 \u0648\u0645\u0646\u0639 \u0627\u0644\u062a\u0633\u0631\u064a\u0628",
        re.compile(
            r"\b(onDestroy|onDestroyView|onCleared|removeLocationUpdates|removeUpdates|unregister|"
            r"removeCallbacksAndMessages|serviceJob\.cancel)\b",
        ),
    ),
    (
        "Concurrency & Thread Safety",
        "\u062a\u0632\u0627\u0645\u0646 \u0627\u0644\u062e\u064a\u0648\u0637 \u0648\u0645\u0646\u0639 \u0627\u0644\u062a\u0636\u0627\u0631\u0628",
        re.compile(
            r"\b(synchronized|Mutex|withLock|@Volatile|AtomicBoolean|Dispatchers\.IO|Dispatchers\.Main)\b",
        ),
    ),
    (
        "Navigation / Intent",
        "\u0627\u0646\u062a\u0642\u0627\u0644 \u0628\u064a\u0646 \u0627\u0644\u0634\u0627\u0634\u0627\u062a",
        re.compile(
            r"\b(findNavController|navigate\s*\(|popBackStack|Intent\s*\(|startActivity|setResult|"
            r"deepLink|NavHost|composable\s*\(|FragmentTransaction)\b",
        ),
    ),
    (
        "State / Coroutine Flow",
        "\u062a\u062d\u062f\u064a\u062b \u0627\u0644\u062d\u0627\u0644\u0629 \u0648\u0627\u0644\u0643\u0648\u0631\u0648\u062a\u064a\u0646",
        re.compile(
            r"\b(MutableStateFlow|MutableSharedFlow|_uiState|_state|update\s*\{|viewModelScope\.launch|"
            r"lifecycleScope\.launch|withContext|CancellationException|collectLatest|repeatOnLifecycle)\b",
        ),
    ),
    (
        "Persistence / Network Contract",
        "\u0642\u0627\u0639\u062f\u0629 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0623\u0648 \u0627\u0644\u0634\u0628\u0643\u0629",
        re.compile(
            r"(@Query|@Insert|@Update|@Delete|@Migration|@GET|@POST|@PUT|@DELETE|@PATCH|@Multipart|"
            r"RoomDatabase|DataStore|fetch[A-Z]\w*|sync[A-Z]\w*)",
        ),
    ),
    (
        "Decision Logic",
        "\u0634\u0631\u0637 \u062a\u062d\u0643\u0645 \u0641\u064a \u0627\u0644\u0645\u0633\u0627\u0631",
        re.compile(r"(^\s*(if|else\s+if|when)\s*\(|^\s*return\b|\?\:|\!\!)"),
    ),
)

_DECL_SYMBOL_RE = re.compile(
    r"^\s*(?:public\s+|internal\s+|protected\s+|private\s+|override\s+|suspend\s+|inline\s+|data\s+|sealed\s+|open\s+|abstract\s+)*"
    r"(?:fun|class|interface|object)\s+(?:<[^>]+>\s*)?([A-Za-z_][A-Za-z0-9_]*)"
)
_STRING_RES_NAME_RE = re.compile(r'<string\s+name="([^"]+)"')
_IMPORT_OR_PKG_RE = re.compile(r"^\s*(package\s+|import\s+|//|\*|/\*|\*/|$)")


def _resolve_target_task_id(repo: Path, explicit_task_id: str | None) -> str:
    if explicit_task_id and str(explicit_task_id).strip():
        tid = str(explicit_task_id).strip()
        validate_id(tid, "task_id")
        return tid
    active_file = state_root(repo) / "active-task.json"
    if active_file.is_file():
        try:
            tid = str(read_json(active_file).get("task_id") or "").strip()
            if tid:
                validate_id(tid, "task_id")
                return tid
        except (OSError, ValueError, ValidationError):
            pass
    tasks_dir = state_root(repo) / "tasks"
    if tasks_dir.is_dir():
        candidates: list[tuple[float, str]] = []
        for child in tasks_dir.iterdir():
            p_f = child / "plan.json"
            if child.is_dir() and p_f.is_file():
                try:
                    candidates.append((p_f.stat().st_mtime, child.name))
                except OSError:
                    continue
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
    raise ValidationError("No active or recent task found; pass `--task-id <id>`.")


def classify_architectural_layer(rel_path: str) -> tuple[int, str, str]:
    p = rel_path.replace("\\", "/")
    low = p.lower()
    name = Path(p).name.lower()

    if (
        "/test/" in low
        or "/androidtest/" in low
        or low.startswith("test/")
        or name.endswith(("test.kt", "tests.kt", "test.java", "spec.kt"))
    ):
        return LAYER_DEFINITIONS[5]

    if (
        low.endswith((".xml", ".json", ".pro", ".properties", ".toml", ".gradle", ".kts"))
        or "/res/" in low
        or name == "androidmanifest.xml"
    ):
        if "/res/layout/" in low or "/res/navigation/" in low:
            return LAYER_DEFINITIONS[3]
        return LAYER_DEFINITIONS[4]

    if any(tok in low for tok in ("/domain/", "/usecase", "/interactor", "/contract", "/model/", "/entity/", "/di/", "module.kt")):
        if "/data/" not in low or "/di/" in low or name.endswith("module.kt"):
            return LAYER_DEFINITIONS[0]

    if any(tok in low for tok in ("/data/", "/repository", "/repo/", "/datasource", "/network/", "/api/", "/dao", "/room/", "/local/", "/remote/", "/service", "/services/", "/worker")):
        return LAYER_DEFINITIONS[1]

    if any(tok in low for tok in ("viewmodel", "uistate", "intent", "reducer", "presenter", "/presentation/")):
        return LAYER_DEFINITIONS[2]

    if any(tok in low for tok in ("/ui/", "fragment", "activity", "screen", "dialog", "adapter", "composable", "navgraph", "navigation")):
        return LAYER_DEFINITIONS[3]

    return LAYER_DEFINITIONS[1]


def _parse_unified_diff(diff_text: str) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    current_path = ""
    old_path = ""
    current_hunk: dict[str, Any] | None = None
    old_ln = 0
    new_ln = 0

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            current_hunk = None
            m = re.match(r"^diff --git a/(.+?) b/(.+)$", raw)
            if m:
                old_path = m.group(1)
                current_path = m.group(2)
                if any(marker in current_path.lower() for marker in SECRET_PATH_MARKERS):
                    current_path = ""
                    continue
                files.setdefault(
                    current_path,
                    {
                        "path": current_path,
                        "old_path": old_path if old_path != current_path else "",
                        "status": "M",
                        "added": 0,
                        "deleted": 0,
                        "hunks": [],
                    },
                )
            continue
        if not current_path or current_path not in files:
            continue
        fobj = files[current_path]
        if raw.startswith("new file mode "):
            fobj["status"] = "A"
            continue
        if raw.startswith("deleted file mode "):
            fobj["status"] = "D"
            continue
        if raw.startswith("rename from "):
            fobj["status"] = "R"
            continue
        if raw.startswith(("--- ", "+++ ", "index ", "similarity index ", "Binary files ")):
            continue
        if raw.startswith("@@ "):
            mh = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$", raw)
            if mh:
                old_ln = int(mh.group(1))
                old_cnt = int(mh.group(2) or "1")
                new_ln = int(mh.group(3))
                new_cnt = int(mh.group(4) or "1")
                ctx_lbl = mh.group(5).strip()
            else:
                old_ln, old_cnt, new_ln, new_cnt, ctx_lbl = 1, 0, 1, 0, ""
            current_hunk = {
                "header": raw,
                "context_label": ctx_lbl,
                "old_start": old_ln,
                "old_count": old_cnt,
                "new_start": new_ln,
                "new_count": new_cnt,
                "lines": [],
                "added": 0,
                "deleted": 0,
            }
            fobj["hunks"].append(current_hunk)
            continue
        if current_hunk is None:
            continue
        if raw.startswith("+"):
            current_hunk["lines"].append({"kind": "add", "old_ln": None, "new_ln": new_ln, "text": raw[1:]})
            current_hunk["added"] += 1
            fobj["added"] += 1
            new_ln += 1
        elif raw.startswith("-"):
            current_hunk["lines"].append({"kind": "del", "old_ln": old_ln, "new_ln": None, "text": raw[1:]})
            current_hunk["deleted"] += 1
            fobj["deleted"] += 1
            old_ln += 1
        elif raw.startswith("\\"):
            continue
        else:
            txt = raw[1:] if raw.startswith(" ") else raw
            current_hunk["lines"].append({"kind": "ctx", "old_ln": old_ln, "new_ln": new_ln, "text": txt})
            old_ln += 1
            new_ln += 1
    return files


def _humanize_task_titles(task_id: str, outcome_txt: str, brief: dict[str, Any]) -> tuple[str, str]:
    """Produce a concise 3-7 word human title in (English, Arabic), never a raw slug or a 50-word sentence."""
    b_en = str(brief.get("title_en") or "").strip()
    b_ar = str(brief.get("title_ar") or "").strip()
    tokens = [t for t in re.split(r"[-_\s]+", task_id.strip()) if t]

    if not b_en:
        if outcome_txt and len(outcome_txt.split()) <= 8 and not outcome_txt.endswith("."):
            b_en = outcome_txt
        elif tokens:
            b_en = " ".join(w.upper() if w.lower() in ("ui", "di", "api", "gps", "io", "db", "rtl", "e2e") else w.capitalize() for w in tokens[:7])
        else:
            b_en = task_id

    if not b_ar:
        ar_words: list[str] = []
        for tok in tokens[:7]:
            low_t = tok.lower()
            mapped = _SLUG_WORD_AR.get(low_t)
            if mapped:
                if mapped not in ar_words:
                    ar_words.append(mapped)
            elif len(tok) > 2 and not tok.isdigit():
                ar_words.append(tok)
        if ar_words and any(not ch.isascii() for w in ar_words for ch in w):
            b_ar = " ".join(ar_words)
        elif outcome_txt and any(not ch.isascii() for ch in outcome_txt):
            words = outcome_txt.split()
            b_ar = " ".join(words[:8]) + ("..." if len(words) > 8 else "")
        else:
            b_ar = f"\u0645\u0631\u0627\u062c\u0639\u0629 \u062a\u0639\u062f\u064a\u0644\u0627\u062a: {b_en}"
    return b_en, b_ar


def _summarize_lines_bilingual(
    rel_path: str,
    layer_key: str,
    status: str,
    add_lines: list[str],
    del_lines: list[str],
    context_label: str = "",
) -> tuple[str, str]:
    """Synthesize a clear, senior-engineer plain-language (English, Arabic) explanation of WHY these lines changed."""
    low = rel_path.lower()
    stem = Path(rel_path).stem

    if status == "A":
        if layer_key == "TESTS":
            return (
                f"Added unit test suite `{stem}` to verify the new fix and guard against regressions.",
                f"\u0625\u0636\u0627\u0641\u0629 \u0645\u0644\u0641 \u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a `{stem}` \u0644\u0644\u062a\u0623\u0643\u062f \u0622\u0644\u064a\u0627\u064b \u0645\u0646 \u0635\u062d\u0629 \u0627\u0644\u0625\u0635\u0644\u0627\u062d \u0648\u0645\u0646\u0639 \u062a\u0643\u0631\u0627\u0631 \u0627\u0644\u0645\u0634\u0643\u0644\u0629 \u0645\u0633\u062a\u0642\u0628\u0644\u0627\u064b.",
            )
        return (
            f"Added new `{stem}` component required by the task implementation.",
            f"\u0625\u0646\u0634\u0627\u0621 \u0645\u0644\u0641 `{stem}` \u0627\u0644\u062c\u062f\u064a\u062f \u0644\u062f\u0639\u0645 \u0627\u0644\u0628\u0646\u064a\u0629 \u0627\u0644\u0645\u0637\u0644\u0648\u0628\u0629 \u0641\u064a \u0647\u0630\u0647 \u0627\u0644\u0645\u0647\u0645\u0629.",
        )
    if status == "D":
        return (
            f"Removed obsolete file `{stem}` (`-{len(del_lines)}` lines).",
            f"\u062d\u0630\u0641 \u0627\u0644\u0645\u0644\u0641 \u0627\u0644\u0642\u062f\u064a\u0645 `{stem}` \u0644\u0639\u062f\u0645 \u0627\u0644\u062d\u0627\u062c\u0629 \u0625\u0644\u064a\u0647 ({len(del_lines)} \u0633\u0637\u0631).",
        )

    changed_all = add_lines + del_lines
    if changed_all and all(_IMPORT_OR_PKG_RE.match(t) for t in changed_all):
        return (
            "Cleaned up imports only (zero runtime behavior change).",
            "\u062a\u0646\u0638\u064a\u0641 \u062c\u0645\u0644 \u0627\u0644\u0627\u0633\u062a\u064a\u0631\u0627\u062f (imports) \u0641\u0642\u0637 \u0628\u062f\u0648\u0646 \u0623\u064a \u062a\u063a\u064a\u064a\u0631 \u0641\u064a \u0633\u0644\u0648\u0643 \u0627\u0644\u0643\u0648\u062f.",
        )

    touched_sym = ""
    for line in [context_label, *add_lines, *del_lines]:
        m = _DECL_SYMBOL_RE.match(line)
        if m:
            touched_sym = m.group(1)
            break
    sym_en = f" in `{touched_sym}`" if touched_sym else ""
    sym_ar = f" \u062f\u0627\u062e\u0644 `{touched_sym}`" if touched_sym else ""

    if low.endswith(".xml") and "strings" in Path(low).name:
        keys: list[str] = []
        for l in add_lines + del_lines:
            mk = _STRING_RES_NAME_RE.search(l)
            if mk and mk.group(1) not in keys:
                keys.append(mk.group(1))
        k_desc = (", ".join(f"`{k}`" for k in keys[:3])) if keys else "UI text"
        return (
            f"Updated localized string resource(s): {k_desc}.",
            f"\u062a\u062d\u062f\u064a\u062b \u0646\u0635\u0648\u0635 \u0627\u0644\u062a\u0631\u062c\u0645\u0629 \u0641\u064a \u0645\u0644\u0641 \u0627\u0644\u0645\u0648\u0627\u0631\u062f: {k_desc}.",
        )

    if layer_key == "TESTS":
        return (
            f"Updated unit test cases{sym_en} to cover the modified lifecycle and edge cases.",
            f"\u062a\u062d\u062f\u064a\u062b \u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a \u0627\u0644\u0648\u062d\u062f\u0629{sym_ar} \u0644\u062a\u063a\u0637\u064a\u0629 \u0627\u0644\u062a\u0639\u062f\u064a\u0644\u0627\u062a \u0648\u0627\u0644\u062d\u0627\u0644\u0627\u062a \u0627\u0644\u062d\u062f\u064a\u0629 \u0627\u0644\u062c\u062f\u064a\u062f\u0629.",
        )

    joined_add = "\n".join(add_lines)
    joined_del = "\n".join(del_lines)

    parts_en: list[str] = []
    parts_ar: list[str] = []

    if "@Singleton" in joined_del and "@Singleton" not in joined_add:
        parts_en.append("Removed `@Singleton` scope so each screen/service gets an isolated instance without callback collisions")
        parts_ar.append("\u0625\u0632\u0627\u0644\u0629 `@Singleton` \u0644\u0625\u0639\u0637\u0627\u0621 \u0643\u0644 \u0634\u0627\u0634\u0629 \u0623\u0648 \u062e\u062f\u0645\u0629 \u0646\u0633\u062e\u0629 \u0645\u0633\u062a\u0642\u0644\u0629 \u0648\u0645\u0646\u0639 \u062a\u062f\u0627\u062e\u0644 \u0627\u0644\u0645\u0633\u062a\u0645\u0639\u0627\u062a \u0639\u0644\u0649 \u0646\u0641\u0633 \u0627\u0644\u0643\u0627\u0626\u0646")

    if re.search(r"removeLocationUpdates|removeUpdates|unregisterListener|unregisterReceiver", joined_add):
        parts_en.append(f"unregistered active listeners/callbacks cleanly{sym_en} to stop background leaks")
        parts_ar.append(f"\u0625\u0644\u063a\u0627\u0621 \u062a\u0633\u062c\u064a\u0644 \u0645\u0633\u062a\u0645\u0639\u0627\u062a \u0627\u0644\u0645\u0648\u0642\u0639 \u0648\u0627\u0644\u0645\u0648\u0627\u0631\u062f \u0628\u0646\u0638\u0627\u0641\u0629{sym_ar} \u0644\u0645\u0646\u0639 \u0627\u0644\u062a\u0633\u0631\u064a\u0628 \u0648\u0627\u0633\u062a\u0646\u0632\u0627\u0641 \u0627\u0644\u0628\u0637\u0627\u0631\u064a\u0629 \u0641\u064a \u0627\u0644\u062e\u0644\u0641\u064a\u0629")

    if re.search(r"\b(onDestroy|onDestroyView|onCleared)\b", joined_add + "\n" + context_label) and not parts_ar:
        parts_en.append(f"added lifecycle teardown cleanup{sym_en} when the component is destroyed")
        parts_ar.append(f"\u062a\u0646\u0638\u064a\u0641 \u0627\u0644\u0645\u0648\u0627\u0631\u062f \u0648\u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u0645\u0647\u0627\u0645 \u0627\u0644\u0645\u0639\u0644\u0642\u0629 \u0639\u0646\u062f \u0627\u0646\u062a\u0647\u0627\u0621 \u062f\u0648\u0631\u0629 \u0627\u0644\u062d\u064a\u0627\u0629{sym_ar}")

    if re.search(r"removeCallbacksAndMessages|removeCallbacks", joined_add):
        parts_en.append("cleared pending `Handler` retry callbacks on view teardown")
        parts_ar.append("\u0625\u064a\u0642\u0627\u0641 \u0645\u0624\u0642\u062a\u0627\u062a \u0625\u0639\u0627\u062f\u0629 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 (`Handler`) \u0627\u0644\u0645\u0639\u0644\u0642\u0629 \u0639\u0646\u062f \u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u0634\u0627\u0634\u0629")

    if re.search(r"\b(synchronized|Mutex|withLock|@Volatile|AtomicBoolean)\b", joined_add):
        parts_en.append("added thread-safety lock/guard to prevent IO-vs-Main race conditions")
        parts_ar.append("\u0625\u0636\u0627\u0641\u0629 \u0642\u0641\u0644 \u062a\u0632\u0627\u0645\u0646 \u0622\u0645\u0646 \u0644\u0645\u0646\u0639 \u062a\u0636\u0627\u0631\u0628 \u0627\u0644\u062e\u064a\u0648\u0637 (`Race Condition`) \u0628\u064a\u0646 \u0627\u0644\u062e\u0644\u0641\u064a\u0629 \u0648\u0627\u0644\u0648\u0627\u062c\u0647\u0629")

    if any(("fun " in l and "=" in l and "(" in l) for l in add_lines):
        parts_en.append(f"adjusted function signature / default parameter{sym_en}")
        parts_ar.append(f"\u062a\u0639\u062f\u064a\u0644 \u0645\u0639\u0627\u0645\u0644\u0627\u062a \u0627\u0644\u062f\u0627\u0644\u0629 \u0648\u0642\u064a\u0645\u0647\u0627 \u0627\u0644\u0627\u0641\u062a\u0631\u0627\u0636\u064a\u0629{sym_ar}")

    if not parts_ar and re.search(r"\bif\s*\([^)]*\)\s*return\b|IllegalArgumentException|Result\.failure", joined_add):
        parts_en.append(f"added early safety guard check{sym_en}")
        parts_ar.append(f"\u0625\u0636\u0627\u0641\u0629 \u0634\u0631\u0637 \u062d\u0645\u0627\u064a\u0629 \u0645\u0628\u0643\u0631 \u0642\u0628\u0644 \u0645\u062a\u0627\u0628\u0639\u0629 \u0627\u0644\u062a\u0646\u0641\u064a\u0630{sym_ar}")

    if re.search(r"MutableStateFlow|MutableSharedFlow|_uiState|viewModelScope\.launch|lifecycleScope\.launch|invokeOnCompletion", joined_add):
        if "invokeOnCompletion" in joined_add or "cancel(" in joined_add:
            parts_en.append(f"bound coroutine cancellation cleanup{sym_en}")
            parts_ar.append(f"\u0631\u0628\u0637 \u0625\u0644\u063a\u0627\u0621 \u0627\u0644\u0643\u0648\u0631\u0648\u062a\u064a\u0646 \u0628\u062a\u0646\u0638\u064a\u0641 \u0627\u0644\u0645\u0633\u062a\u0645\u0639\u0627\u062a \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b{sym_ar}")
        elif not parts_ar:
            parts_en.append(f"updated coroutine / state flow handling{sym_en}")
            parts_ar.append(f"\u062a\u062d\u062f\u064a\u062b \u062a\u062f\u0641\u0642 \u0627\u0644\u062d\u0627\u0644\u0629 \u0648\u0627\u0644\u0643\u0648\u0631\u0648\u062a\u064a\u0646{sym_ar}")

    if re.search(r"findNavController|navigate\s*\(|Intent\s*\(|startActivity", joined_add):
        parts_en.append(f"updated screen navigation flow{sym_en}")
        parts_ar.append(f"\u062a\u062d\u062f\u064a\u062b \u0645\u0633\u0627\u0631 \u0627\u0644\u0627\u0646\u062a\u0642\u0627\u0644 \u0628\u064a\u0646 \u0627\u0644\u0634\u0627\u0634\u0627\u062a{sym_ar}")

    if re.search(r"billing|payment|purchase|price|token|PendingIntent", joined_add, re.I):
        parts_en.append("hardened sensitive billing/security handling")
        parts_ar.append("\u062a\u0623\u0645\u064a\u0646 \u0645\u0646\u0637\u0642 \u0627\u0644\u062f\u0641\u0639 \u0623\u0648 \u0627\u0644\u0635\u0644\u0627\u062d\u064a\u0627\u062a \u0627\u0644\u062d\u0633\u0627\u0633\u0629")

    if not parts_en:
        if len(del_lines) > len(add_lines) * 2 and len(del_lines) >= 3:
            parts_en.append(f"Removed redundant code (`-{len(del_lines)}` lines){sym_en}")
            parts_ar.append(f"\u062a\u0646\u0638\u064a\u0641 \u0648\u062d\u0630\u0641 \u0643\u0648\u062f \u0645\u0643\u0631\u0631 \u0644\u0645 \u062a\u0639\u062f \u0644\u0647 \u062d\u0627\u062c\u0629 ({len(del_lines)} \u0633\u0637\u0631){sym_ar}")
        else:
            parts_en.append(f"Updated core logic{sym_en} to align with the task fix")
            parts_ar.append(f"\u062a\u062d\u062f\u064a\u062b \u0645\u0646\u0637\u0642 \u0627\u0644\u0639\u0645\u0644 \u0627\u0644\u0623\u0633\u0627\u0633\u064a{sym_ar} \u0644\u064a\u062a\u0648\u0627\u0641\u0642 \u0645\u0639 \u0625\u0635\u0644\u0627\u062d \u0627\u0644\u0645\u0647\u0645\u0629")

    en_sentence = "; ".join(parts_en[:3])
    en_sentence = en_sentence[0].upper() + en_sentence[1:] + "."
    ar_sentence = "\u060c \u0645\u0639 ".join(parts_ar[:3]) + "."
    return en_sentence, ar_sentence


def _translate_ai_finding_to_arabic(title: str, message: str, file_path: str, state: str) -> tuple[str, str]:
    """Translate raw English AI reviewer findings into concise, clear Arabic so RTL mode has zero English walls."""
    fname = Path(file_path).name if file_path else ""
    in_file = f" \u0641\u064a `{fname}`" if fname else ""
    low_all = f"{title} {message}".lower()

    if "race" in low_all or "unsynchronized" in low_all or ("io" in low_all and "ondestroy" in low_all):
        t_ar = f"\u062a\u0636\u0627\u0631\u0628 \u062a\u0632\u0627\u0645\u0646 (Race Condition) \u0628\u064a\u0646 \u062e\u064a\u0637 \u0627\u0644\u062e\u0644\u0641\u064a\u0629 \u0648\u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u062e\u062f\u0645\u0629{in_file}"
        m_ar = "\u0643\u0627\u0646 \u0645\u0646 \u0627\u0644\u0645\u0645\u0643\u0646 \u0623\u0646 \u064a\u0633\u062c\u0651\u0644 \u062e\u064a\u0637 \u0627\u0644\u062e\u0644\u0641\u064a\u0629 \u0645\u0633\u062a\u0645\u0639 \u0645\u0648\u0642\u0639 \u062c\u062f\u064a\u062f \u0628\u0639\u062f \u0627\u0633\u062a\u062f\u0639\u0627\u0621 \u062f\u0627\u0644\u0629 \u0627\u0644\u0625\u063a\u0644\u0627\u0642 \u0645\u0628\u0627\u0634\u0631\u0629\u064b\u061b \u062a\u0645 \u062a\u0623\u0645\u064a\u0646\u0647 \u0628\u0642\u0641\u0644 \u062a\u0632\u0627\u0645\u0646 \u0648\u0641\u062d\u0635 \u062d\u0627\u0644\u0629 \u0627\u0644\u0625\u064a\u0642\u0627\u0641."
    elif "collision" in low_all or "single-slot" in low_all or "shared" in low_all and "callback" in low_all:
        t_ar = f"\u062a\u0632\u0627\u062d\u0645 \u0645\u0633\u0627\u0631\u064e\u064a \u0637\u0644\u0628 \u0645\u0648\u0642\u0639 \u0639\u0644\u0649 \u0646\u0641\u0633 \u0627\u0644\u0643\u0627\u0626\u0646{in_file}"
        m_ar = "\u0627\u0633\u062a\u062e\u062f\u0627\u0645 \u0646\u0641\u0633 \u0627\u0644\u0646\u0633\u062e\u0629 \u0644\u0639\u0645\u0644\u064a\u062a\u064a\u0646 \u0645\u062a\u0632\u0627\u0645\u0646\u062a\u064a\u0646 \u0643\u0627\u0646 \u064a\u0644\u063a\u064a \u0627\u0644\u0645\u0633\u062a\u0645\u0639 \u0627\u0644\u0623\u0648\u0644 \u0642\u0628\u0644 \u0627\u0643\u062a\u0645\u0627\u0644\u0647\u061b \u062a\u0645 \u0641\u0635\u0644\u0647\u0645\u0627 \u0628\u0623\u0645\u0627\u0646."
    elif "leak" in low_all or "unregister" in low_all or "removelocationupdates" in low_all:
        t_ar = f"\u0627\u062d\u062a\u0645\u0627\u0644 \u0628\u0642\u0627\u0621 \u0645\u0633\u062a\u0645\u0639 \u0646\u0634\u0637 \u0628\u0639\u062f \u0627\u0646\u062a\u0647\u0627\u0621 \u062f\u0648\u0631\u0629 \u0627\u0644\u062d\u064a\u0627\u0629{in_file}"
        m_ar = "\u062a\u0645 \u0627\u0644\u062a\u0623\u0643\u062f \u0645\u0646 \u0625\u0644\u063a\u0627\u0621 \u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u0645\u0633\u062a\u0645\u0639\u0627\u062a \u0648\u062a\u0641\u0631\u064a\u063a \u0627\u0644\u0645\u0631\u0627\u062c\u0639 \u0639\u0646\u062f \u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u0634\u0627\u0634\u0629 \u0623\u0648 \u0627\u0644\u062e\u062f\u0645\u0629."
    elif "default" in low_all and ("flag" in low_all or "param" in low_all or "arg" in low_all):
        t_ar = f"\u0645\u0631\u0627\u062c\u0639\u0629 \u0627\u0644\u0642\u064a\u0645\u0629 \u0627\u0644\u0627\u0641\u062a\u0631\u0627\u0636\u064a\u0629 \u0644\u0644\u0645\u0639\u0627\u0645\u0644 \u0639\u0646\u062f \u0627\u0644\u0645\u0633\u062a\u062f\u0639\u064a\u0646{in_file}"
        m_ar = "\u0627\u0644\u062a\u0623\u0643\u062f \u0645\u0646 \u0623\u0646 \u0627\u0644\u0634\u0627\u0634\u0627\u062a \u0627\u0644\u0623\u062e\u0631\u0649 \u0627\u0644\u062a\u064a \u062a\u0633\u062a\u062f\u0639\u064a \u0627\u0644\u062f\u0627\u0644\u0629 \u0628\u062f\u0648\u0646 \u062a\u0645\u0631\u064a\u0631 \u0627\u0644\u0645\u0639\u0627\u0645\u0644 \u0627\u0644\u062c\u062f\u064a\u062f \u062a\u062d\u0627\u0641\u0638 \u0639\u0644\u0649 \u0633\u0644\u0648\u0643\u0647\u0627 \u0627\u0644\u0635\u062d\u064a\u062d."
    elif "kdoc" in low_all or "doc" in low_all or "comment" in low_all:
        t_ar = f"\u0627\u0642\u062a\u0631\u0627\u062d \u062a\u0648\u062b\u064a\u0642 \u0627\u062e\u062a\u064a\u0627\u0631\u064a \u0644\u0644\u0643\u0648\u062f{in_file}"
        m_ar = "\u0645\u0644\u0627\u062d\u0638\u0629 \u062a\u062d\u0633\u064a\u0646\u064a\u0629 \u0628\u0633\u064a\u0637\u0629 \u0644\u0625\u0636\u0627\u0641\u0629 \u062a\u0648\u0636\u064a\u062d \u062a\u0648\u062b\u064a\u0642\u064a \u0639\u0644\u0649 \u0627\u0644\u0645\u0639\u0627\u0645\u0644 \u0627\u0644\u062c\u062f\u064a\u062f \u0639\u0646\u062f \u0627\u0644\u062d\u0627\u062c\u0629."
    elif "null" in low_all or "npe" in low_all:
        t_ar = f"\u062d\u0645\u0627\u064a\u0629 \u0645\u0646 \u0627\u0644\u0642\u064a\u0645 \u0627\u0644\u0641\u0627\u0631\u063a\u0629 (Null Safety){in_file}"
        m_ar = "\u0627\u0644\u062a\u062d\u0642\u0642 \u0627\u0644\u0622\u0645\u0646 \u0645\u0646 \u0639\u062f\u0645 \u0641\u0631\u0627\u063a \u0627\u0644\u0643\u0627\u0626\u0646 \u0642\u0628\u0644 \u0627\u0633\u062a\u062e\u062f\u0627\u0645\u0647 \u0644\u062a\u0641\u0627\u062f\u064a \u0623\u064a \u0627\u0646\u0647\u064a\u0627\u0631 \u0645\u062d\u062a\u0645\u0644."
    else:
        t_ar = f"\u0645\u0644\u0627\u062d\u0638\u0629 \u0641\u062d\u0635 \u0647\u0646\u062f\u0633\u064a{in_file}"
        m_ar = (
            "\u0631\u0635\u062f\u0647\u0627 \u0627\u0644\u0645\u0631\u0627\u062c\u0639 \u0627\u0644\u0622\u0644\u064a \u0648\u062a\u0645 \u0627\u0644\u062a\u062d\u0642\u0642 \u0645\u0646\u0647\u0627 \u0648\u0645\u0639\u0627\u0644\u062c\u062a\u0647\u0627 \u0636\u0645\u0646 \u062c\u0648\u0644\u0627\u062a \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629."
            if state == "RESOLVED_IN_LATER_ROUND"
            else "\u0645\u0644\u0627\u062d\u0638\u0629 \u0641\u062d\u0635 \u0644\u0644\u0645\u0631\u0627\u062c\u0639\u0629 \u0627\u0644\u0633\u0631\u064a\u0639\u0629 \u0639\u0644\u0649 \u0647\u0630\u0627 \u0627\u0644\u0645\u0648\u0636\u0639."
        )
    return t_ar, m_ar


def _classify_hunk_and_file_triage(
    rel_path: str,
    layer_key: str,
    status: str,
    hunks: list[dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    low = rel_path.lower()
    if layer_key == "TESTS":
        for hk in hunks:
            add_l = [str(l["text"]) for l in (hk.get("lines") or []) if l["kind"] == "add"]
            del_l = [str(l["text"]) for l in (hk.get("lines") or []) if l["kind"] == "del"]
            s_en, s_ar = _summarize_lines_bilingual(rel_path, layer_key, status, add_l, del_l, str(hk.get("context_label") or ""))
            hk["summary_en"] = s_en
            hk["summary_ar"] = s_ar
        return "AUTO_COLLAPSED", ["Automated test suite"], ["\u0645\u0644\u0641 \u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a \u0622\u0644\u064a\u0629"]

    if low.endswith(".xml") and ("/res/values" in low or "strings" in Path(low).name):
        for hk in hunks:
            add_l = [str(l["text"]) for l in (hk.get("lines") or []) if l["kind"] == "add"]
            del_l = [str(l["text"]) for l in (hk.get("lines") or []) if l["kind"] == "del"]
            s_en, s_ar = _summarize_lines_bilingual(rel_path, layer_key, status, add_l, del_l, str(hk.get("context_label") or ""))
            hk["summary_en"] = s_en
            hk["summary_ar"] = s_ar
        return "AUTO_COLLAPSED", ["String / resource values"], ["\u0645\u0644\u0641 \u0646\u0635\u0648\u0635 \u0648\u0645\u0648\u0627\u0631\u062f"]

    changed_texts: list[str] = []
    reasons_en: list[str] = []
    reasons_ar: list[str] = []

    for hk in hunks:
        hk_en_list: list[str] = []
        hk_ar_list: list[str] = []
        add_l: list[str] = []
        del_l: list[str] = []
        for ln in hk.get("lines") or []:
            if ln["kind"] in ("add", "del"):
                txt = str(ln["text"])
                changed_texts.append(txt)
                if ln["kind"] == "add":
                    add_l.append(txt)
                else:
                    del_l.append(txt)
                for label_en, label_ar, pat in _HOTSPOT_PATTERNS:
                    if pat.search(txt):
                        if label_en not in hk_en_list:
                            hk_en_list.append(label_en)
                            hk_ar_list.append(label_ar)
                        if label_en not in reasons_en:
                            reasons_en.append(label_en)
                            reasons_ar.append(label_ar)
                m_decl = _DECL_SYMBOL_RE.match(txt)
                if m_decl and "=" in txt and "(" in txt and "Default-Arg Signature" not in hk_en_list:
                    hk_en_list.append("Default-Arg Signature")
                    hk_ar_list.append("\u062a\u0639\u062f\u064a\u0644 \u0645\u0639\u0627\u0645\u0644 \u0627\u0641\u062a\u0631\u0627\u0636\u064a")
                    if "Default-Arg Signature" not in reasons_en:
                        reasons_en.append("Default-Arg Signature")
                        reasons_ar.append("\u062a\u0639\u062f\u064a\u0644 \u0645\u0639\u0627\u0645\u0644 \u0627\u0641\u062a\u0631\u0627\u0636\u064a")
        hk["hotspot_reasons_en"] = hk_en_list
        hk["hotspot_reasons_ar"] = hk_ar_list
        s_en, s_ar = _summarize_lines_bilingual(rel_path, layer_key, status, add_l, del_l, str(hk.get("context_label") or ""))
        hk["summary_en"] = s_en
        hk["summary_ar"] = s_ar

    if changed_texts and all(_IMPORT_OR_PKG_RE.match(t) for t in changed_texts):
        return "AUTO_COLLAPSED", ["Imports only"], ["\u0627\u0633\u062a\u064a\u0631\u0627\u062f\u0627\u062a \u0641\u0642\u0637"]

    if reasons_en:
        return "HOTSPOT", reasons_en[:2], reasons_ar[:2]

    if layer_key in ("DOMAIN", "VIEWMODEL") and changed_texts:
        return "STANDARD", ["Core architecture"], ["\u062a\u0639\u062f\u064a\u0644 \u0623\u0633\u0627\u0633\u064a"]

    return "STANDARD", ["Implementation"], ["\u062a\u062d\u062f\u064a\u062b \u062a\u0646\u0641\u064a\u0630\u064a"]


def _extract_modified_symbols(parsed_files: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    skip_common = {
        "onCreate", "onStart", "onResume", "onPause", "onStop", "onDestroy",
        "onViewCreated", "onDestroyView", "onCleared", "invoke", "build", "create",
        "equals", "hashCode", "toString",
    }
    for rel_path, fobj in parsed_files.items():
        if classify_architectural_layer(rel_path)[1] == "TESTS":
            continue
        for hk in fobj.get("hunks") or []:
            ctx = hk.get("context_label") or ""
            mc = _DECL_SYMBOL_RE.search(ctx)
            if mc:
                sym = mc.group(1)
                if len(sym) >= 4 and sym not in skip_common:
                    seen.setdefault(sym, {"symbol": sym, "defined_in": rel_path, "has_default_arg": False})
            for ln in hk.get("lines") or []:
                if ln["kind"] in ("add", "del"):
                    ml = _DECL_SYMBOL_RE.match(str(ln["text"]))
                    if ml:
                        sym = ml.group(1)
                        if len(sym) >= 4 and sym not in skip_common:
                            entry = seen.setdefault(
                                sym,
                                {"symbol": sym, "defined_in": rel_path, "has_default_arg": False},
                            )
                            if "=" in str(ln["text"]) and "(" in str(ln["text"]):
                                entry["has_default_arg"] = True
        stem = Path(rel_path).stem
        if len(stem) >= 5 and stem[0].isupper() and not stem.endswith(("Test", "Tests")):
            seen.setdefault(stem, {"symbol": stem, "defined_in": rel_path, "has_default_arg": False})
    return list(seen.values())[:24]


def _discover_unmodified_blast_radius_callers(
    repo: Path,
    touched_paths: set[str],
    modified_symbols: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not modified_symbols:
        return []
    sym_map = {item["symbol"]: item for item in modified_symbols}
    escaped = [re.escape(sym) for sym in sym_map]
    combined = re.compile(r"\b(" + "|".join(escaped) + r")\b")

    candidate_files: list[Path] = []
    graph_cache = repo / ".agents" / "cache" / "project-graph.json"
    if graph_cache.is_file():
        try:
            gdata = read_json(graph_cache)
            nodes = gdata.get("files") or gdata.get("nodes") or {}
            if isinstance(nodes, dict):
                for rel_p in nodes:
                    rp = str(rel_p).replace("\\", "/")
                    if rp not in touched_paths and rp.endswith((".kt", ".java")):
                        fp = repo / rp
                        if fp.is_file():
                            candidate_files.append(fp)
        except (OSError, ValueError, ValidationError):
            candidate_files = []

    if not candidate_files:
        skip_dirs = {".git", ".gradle", ".agents", ".idea", "build", "node_modules", ".kotlin"}
        count = 0
        for root_dir, dirs, filenames in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for fn in filenames:
                if not fn.endswith((".kt", ".java")):
                    continue
                fp = Path(root_dir) / fn
                try:
                    rel_p = fp.relative_to(repo).as_posix()
                except ValueError:
                    continue
                if rel_p in touched_paths or "/test/" in rel_p.lower() or "/androidtest/" in rel_p.lower():
                    continue
                candidate_files.append(fp)
                count += 1
                if count >= 1200:
                    break
            if count >= 1200:
                break

    callers: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for fp in candidate_files:
        try:
            rel_p = fp.relative_to(repo).as_posix()
            if "/test/" in rel_p.lower() or "/androidtest/" in rel_p.lower():
                continue
            text = fp.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        if not combined.search(text):
            continue
        for idx, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import ", "package ", "//", "*")):
                continue
            m = combined.search(line)
            if not m:
                continue
            sym = m.group(1)
            pair = (rel_p, sym)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            meta = sym_map[sym]
            callers.append({
                "symbol": sym,
                "defined_in": meta["defined_in"],
                "has_default_arg": bool(meta.get("has_default_arg")),
                "caller_file": rel_p,
                "line": idx,
                "snippet": stripped[:140],
            })
            if len(callers) >= 30:
                return callers
    return callers


def _collect_verified_gates(repo: Path, task_directory: Path, plan: dict[str, Any]) -> list[dict[str, str]]:
    gates: list[dict[str, str]] = []
    run_doc_path = task_directory / "current-run.json"
    run_doc = read_json(run_doc_path) if run_doc_path.is_file() else {}
    snap = str(run_doc.get("delivery_snapshot_sha256") or "")
    run_id = str(run_doc.get("run_id") or "")

    ev_root = state_root(repo) / "evidence"
    if snap and run_id and (ev_root / snap / run_id).is_dir():
        run_ev_dir = ev_root / snap / run_id
        for gate_name in ("compile", "preflight", "unit_tests", "localization", "check_strings", "roborazzi_ui", "maestro_e2e"):
            gf = run_ev_dir / f"{gate_name}.json"
            if gf.is_file():
                try:
                    gd = read_json(gf)
                    ev = gd.get("evidence") if isinstance(gd.get("evidence"), dict) else gd
                    st = str(ev.get("status") or gd.get("status") or "PASS").upper()
                    gates.append({"gate": gate_name, "status": st})
                except (OSError, ValueError, ValidationError):
                    continue

    if not gates:
        for fallback_name in ("preflight", "unit_tests", "compile"):
            matches = sorted(ev_root.glob(f"*/*/{fallback_name}.json"), key=lambda p: p.stat().st_mtime, reverse=True) if ev_root.is_dir() else []
            for mf in matches[:3]:
                try:
                    gd = read_json(mf)
                    if str(gd.get("task_id") or "") == str(plan.get("task_id") or ""):
                        ev = gd.get("evidence") if isinstance(gd.get("evidence"), dict) else gd
                        gates.append({"gate": fallback_name, "status": str(ev.get("status") or "PASS").upper()})
                        break
                except (OSError, ValueError, ValidationError):
                    continue
    return gates


def _collect_ai_review_xray(task_directory: Path, brief: dict[str, Any] | None = None) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = []
    findings_by_file: dict[str, list[dict[str, Any]]] = {}
    all_findings: list[dict[str, Any]] = []
    finding_notes = (brief or {}).get("finding_notes") if isinstance((brief or {}).get("finding_notes"), dict) else {}

    exec_root = task_directory / "review-execution"
    run_dirs: list[tuple[str, float, str, Path]] = []
    if exec_root.is_dir():
        for child in exec_root.iterdir():
            if child.is_dir():
                try:
                    created_hint = ""
                    mf = task_directory / f"manifest-{child.name}.json"
                    lf = child / "ledger.json"
                    if mf.is_file():
                        created_hint = str(read_json(mf).get("created_at") or "")
                    elif lf.is_file():
                        created_hint = str(read_json(lf).get("created_at") or "")
                    run_dirs.append((created_hint, round(child.stat().st_mtime, 1), child.name, child))
                except (OSError, ValueError, ValidationError):
                    continue
    run_dirs.sort(key=lambda item: (item[0], item[1], item[2]))

    total_runs = len(run_dirs)
    for round_idx, (_chint, _mtime, _rname, rdir) in enumerate(run_dirs, 1):
        results_dir = rdir / "results"
        if not results_dir.is_dir():
            continue
        round_verdicts: list[dict[str, str]] = []
        is_latest_round = (round_idx == total_runs)
        for rf in sorted(results_dir.glob("*.json")):
            try:
                doc = read_json(rf)
            except (OSError, ValueError, ValidationError):
                continue
            reviewer = str(doc.get("reviewer") or rf.stem)
            res = doc.get("result") if isinstance(doc.get("result"), dict) else doc
            verdict = str(res.get("verdict") or "UNKNOWN")
            round_verdicts.append({"reviewer": reviewer, "verdict": verdict})
            for f_item in res.get("findings") or []:
                if not isinstance(f_item, dict):
                    continue
                sev = str(f_item.get("severity") or "INFO").upper()
                f_path = str(f_item.get("file") or f_item.get("path") or "").replace("\\", "/")
                resolved_later = (not is_latest_round) and sev in ("CRITICAL", "HIGH", "MEDIUM")
                st_code = "RESOLVED_IN_LATER_ROUND" if resolved_later else ("ADVISORY" if sev in ("LOW", "INFO") else "ACTIVE")
                title_en = str(f_item.get("title") or f_item.get("id") or "Review observation")
                msg_en = str(f_item.get("description") or f_item.get("message") or f_item.get("remediation") or "")[:360]
                auto_t_ar, auto_m_ar = _translate_ai_finding_to_arabic(title_en, msg_en, f_path, st_code)
                custom_fn = finding_notes.get(title_en) or finding_notes.get(Path(f_path).name if f_path else "") or {}
                rec = {
                    "round": round_idx,
                    "run_id": rdir.name,
                    "reviewer": reviewer,
                    "severity": sev,
                    "title": title_en,
                    "title_ar": str(custom_fn.get("ar") or auto_t_ar),
                    "message": msg_en,
                    "message_ar": str(custom_fn.get("message_ar") or auto_m_ar),
                    "file": f_path,
                    "line": int(f_item.get("line") or 0) if str(f_item.get("line") or "").isdigit() else 0,
                    "state": st_code,
                }
                all_findings.append(rec)
                if f_path:
                    findings_by_file.setdefault(f_path, []).append(rec)
        if round_verdicts:
            rounds.append({
                "round": round_idx,
                "run_id": rdir.name,
                "verdicts": round_verdicts,
            })

    return {
        "rounds": rounds,
        "all_findings": all_findings,
        "by_file": findings_by_file,
    }


def _collect_plan_traceability(
    task_directory: Path,
    plan: dict[str, Any],
    parsed_files: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    current_expected = {str(p).replace("\\", "/") for p in (plan.get("expected_files") or []) if p}
    initial_expected = set(current_expected)

    hist_dir = task_directory / "plan-history"
    if hist_dir.is_dir():
        hist_snapshots: list[tuple[float, set[str]]] = []
        for hf in hist_dir.glob("*.json"):
            try:
                hdoc = read_json(hf)
                ef = {str(p).replace("\\", "/") for p in (hdoc.get("expected_files") or []) if p}
                if ef:
                    hist_snapshots.append((hf.stat().st_mtime, ef))
            except (OSError, ValueError, ValidationError):
                continue
        if hist_snapshots:
            hist_snapshots.sort(key=lambda x: x[0])
            initial_expected = hist_snapshots[0][1]

    touched_set = {p.replace("\\", "/") for p in parsed_files}
    side_effect_files: list[dict[str, Any]] = []
    for rel_p in sorted(touched_set):
        if initial_expected and rel_p not in initial_expected:
            fd = parsed_files[rel_p]
            in_curr = rel_p in current_expected
            reason_en = (
                "Auto-reconciled into approved scope during verification"
                if in_curr
                else "Modified outside initial expected_files list"
            )
            reason_ar = (
                "\u0636\u064f\u0645\u0651 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b \u0644\u0646\u0637\u0627\u0642 \u0627\u0644\u0645\u0647\u0645\u0629 \u0623\u062b\u0646\u0627\u0621 \u0627\u0644\u062a\u062d\u0642\u0642"
                if in_curr
                else "\u0639\u064f\u062f\u0651\u0644 \u062e\u0627\u0631\u062c \u0642\u0627\u0626\u0645\u0629 \u0645\u0644\u0641\u0627\u062a \u0627\u0644\u062e\u0637\u0629 \u0627\u0644\u0623\u0648\u0644\u0649"
            )
            side_effect_files.append({
                "path": rel_p,
                "added": fd.get("added", 0),
                "deleted": fd.get("deleted", 0),
                "reason": reason_en,
                "reason_ar": reason_ar,
            })

    outcome_txt = str(
        plan.get("requested_outcome")
        or plan.get("outcome")
        or plan.get("desired_outcome")
        or plan.get("goal")
        or ""
    ).strip()
    approach_txt = str(plan.get("approach") or "").strip()
    phases_trace: list[dict[str, Any]] = []
    file_to_phase: dict[str, tuple[str, str]] = {}
    raw_phases = list(plan.get("phases") or [])
    if raw_phases:
        for ph in raw_phases:
            if not isinstance(ph, dict):
                continue
            ph_id = str(ph.get("id") or "phase")
            ph_title = str(ph.get("name") or ph.get("title") or ph.get("description") or ph_id)
            ph_expected = [str(p).replace("\\", "/") for p in (ph.get("expected_files") or []) if p]
            for pe in ph_expected:
                file_to_phase[pe] = (ph_id, ph_title)
            matched = [p for p in ph_expected if p in parsed_files]
            phases_trace.append({
                "id": ph_id,
                "title": ph_title,
                "expected_files": ph_expected,
                "touched_files": matched,
                "added": sum(int(parsed_files[p].get("added") or 0) for p in matched),
                "deleted": sum(int(parsed_files[p].get("deleted") or 0) for p in matched),
            })
    else:
        matched = [p for p in sorted(current_expected) if p in parsed_files]
        phases_trace.append({
            "id": "main",
            "title": "\u0646\u0637\u0627\u0642 \u0627\u0644\u062e\u0637\u0629 \u0627\u0644\u0645\u0639\u062a\u0645\u062f\u0629",
            "expected_files": sorted(current_expected),
            "touched_files": matched,
            "added": sum(int(parsed_files[p].get("added") or 0) for p in matched),
            "deleted": sum(int(parsed_files[p].get("deleted") or 0) for p in matched),
        })

    return {
        "outcome": outcome_txt,
        "approach": approach_txt,
        "kind": str(plan.get("kind") or "FEATURE"),
        "status": str(plan.get("status") or "UNKNOWN"),
        "initial_expected_count": len(initial_expected),
        "current_expected_count": len(current_expected),
        "phases": phases_trace,
        "file_to_phase": file_to_phase,
        "side_effect_files": side_effect_files,
    }


def load_review_brief(task_directory: Path) -> dict[str, Any]:
    bf = task_directory / "review-brief.json"
    if not bf.is_file():
        return {}
    try:
        doc = read_json(bf)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError, ValidationError):
        return {}


def save_review_brief_updates(task_directory: Path, updates: dict[str, Any]) -> dict[str, Any]:
    existing = load_review_brief(task_directory)
    merged = dict(existing)
    for key in ("title_ar", "title_en", "problem_ar", "problem_en", "solution_ar", "solution_en"):
        val = str(updates.get(key) or "").strip()
        if val:
            merged[key] = val
    for list_key in ("checks_ar", "checks_en"):
        items = updates.get(list_key)
        if isinstance(items, list) and items:
            merged[list_key] = [str(x).strip() for x in items if str(x).strip()]
    f_notes = dict(merged.get("file_notes") or {}) if isinstance(merged.get("file_notes"), dict) else {}
    for raw_fn in updates.get("file_notes_raw") or []:
        s = str(raw_fn or "").strip()
        if not s:
            continue
        if "::" in s:
            parts = [p.strip() for p in s.split("::", 2)]
            f_key = parts[0].replace("\\", "/")
            ar_v = parts[1] if len(parts) > 1 else ""
            en_v = parts[2] if len(parts) > 2 else ar_v
            if f_key and (ar_v or en_v):
                f_notes[f_key] = {"ar": ar_v or en_v, "en": en_v or ar_v}
        elif "|" in s:
            parts = [p.strip() for p in s.split("|", 2)]
            f_key = parts[0].replace("\\", "/")
            ar_v = parts[1] if len(parts) > 1 else ""
            en_v = parts[2] if len(parts) > 2 else ar_v
            if f_key and (ar_v or en_v):
                f_notes[f_key] = {"ar": ar_v or en_v, "en": en_v or ar_v}
        elif "=" in s:
            f_key, val = s.split("=", 1)
            f_key = f_key.strip().replace("\\", "/")
            val = val.strip()
            if f_key and val:
                f_notes[f_key] = {"ar": val, "en": val}
    if f_notes:
        merged["file_notes"] = f_notes
    crun_p = task_directory / "current-run.json"
    if crun_p.is_file():
        try:
            crun_doc = read_json(crun_p)
            if isinstance(crun_doc, dict) and crun_doc.get("run_id"):
                merged["run_id"] = str(crun_doc["run_id"])
        except (OSError, ValueError, ValidationError):
            _no_crun = True
    merged["updated_at"] = utc_now()
    task_directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(task_directory / "review-brief.json", merged)
    return merged


def _match_file_brief_note(rel_p: str, brief: dict[str, Any]) -> tuple[str, str]:
    f_notes = brief.get("file_notes")
    if not isinstance(f_notes, dict) or not f_notes:
        return "", ""
    norm = rel_p.replace("\\", "/")
    fname = Path(norm).name
    hit = f_notes.get(norm) or f_notes.get(fname)
    if not hit:
        for k, v in f_notes.items():
            if norm.endswith("/" + k.strip("/")) or k.strip("/").endswith("/" + fname):
                hit = v
                break
    if isinstance(hit, dict):
        return str(hit.get("en") or "").strip(), str(hit.get("ar") or "").strip()
    if isinstance(hit, str) and hit.strip():
        return hit.strip(), hit.strip()
    return "", ""


def _enrich_file_rationale(
    fobj: dict[str, Any],
    traceability: dict[str, Any],
    file_findings: list[dict[str, Any]],
    side_effect_set: set[str],
    brief: dict[str, Any],
) -> tuple[str, str]:
    rel_p = fobj["path"]
    b_en, b_ar = _match_file_brief_note(rel_p, brief)
    all_add = [str(l["text"]) for hk in (fobj.get("hunks") or []) for l in (hk.get("lines") or []) if l["kind"] == "add"]
    all_del = [str(l["text"]) for hk in (fobj.get("hunks") or []) for l in (hk.get("lines") or []) if l["kind"] == "del"]
    core_en, core_ar = _summarize_lines_bilingual(
        rel_p, fobj["layer_key"], fobj.get("status", "M"), all_add, all_del
    )
    use_en = b_en or core_en
    use_ar = b_ar or core_ar

    resolved_r1 = [ff for ff in file_findings if ff.get("state") == "RESOLVED_IN_LATER_ROUND"]
    fix_en = f" (Verified after Round {resolved_r1[0]['round']} review fix)" if (resolved_r1 and not b_en) else ""
    fix_ar = f" (\u0648\u062a\u0645 \u062a\u0623\u0645\u064a\u0646 \u0645\u0644\u0627\u062d\u0638\u0629 \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629 \u0639\u0644\u064a\u0647\u0627)" if (resolved_r1 and not b_ar) else ""
    return use_en + fix_en, use_ar + fix_ar


def _build_story_cards_content(
    task_id: str,
    title_en: str,
    title_ar: str,
    ordered_files: list[dict[str, Any]],
    traceability: dict[str, Any],
    brief: dict[str, Any],
) -> dict[str, Any]:
    outcome = traceability.get("outcome") or ""
    approach = traceability.get("approach") or ""

    prob_en = str(brief.get("problem_en") or outcome or f"Task `{task_id}` ({title_en}).").strip()
    if brief.get("problem_ar"):
        prob_ar = str(brief["problem_ar"]).strip()
    elif outcome and any(not ch.isascii() for ch in outcome):
        prob_ar = outcome
    else:
        prob_ar = f"\u0627\u0644\u0647\u062f\u0641 \u0645\u0646 \u0627\u0644\u0645\u0647\u0645\u0629: {title_ar} \u2014 \u0645\u0639\u0627\u0644\u062c\u0629 \u0627\u0644\u0633\u0628\u0628 \u0627\u0644\u062c\u0630\u0631\u064a \u0641\u064a \u0627\u0644\u0645\u0644\u0641\u0627\u062a \u0627\u0644\u0645\u062a\u0623\u062b\u0631\u0629 \u0648\u0636\u0645\u0627\u0646 \u0639\u062f\u0645 \u062d\u062f\u0648\u062b \u0623\u064a \u0622\u062b\u0627\u0631 \u062c\u0627\u0646\u0628\u064a\u0629 \u0639\u0644\u0649 \u0628\u0627\u0642\u064a \u0627\u0644\u0634\u0627\u0634\u0627\u062a."

    non_test_files = [f for f in ordered_files if f["layer_key"] != "TESTS"]
    test_files = [f for f in ordered_files if f["layer_key"] == "TESTS"]

    if brief.get("solution_en"):
        sol_en = str(brief["solution_en"]).strip()
    elif approach:
        sol_en = approach
    else:
        sol_en = " ".join(f"`{Path(f['path']).name}`: {f.get('why_en', '')}" for f in non_test_files[:3]) or "Applied scoped architectural changes."

    if brief.get("solution_ar"):
        sol_ar = str(brief["solution_ar"]).strip()
    else:
        ar_highlights = [f"\u0641\u064a `{Path(f['path']).name}`: {f.get('why_ar', '')}" for f in non_test_files[:3]]
        if test_files:
            ar_highlights.append(f"\u0645\u0639 \u062a\u063a\u0637\u064a\u0629 \u0627\u0644\u062a\u0639\u062f\u064a\u0644\u0627\u062a \u0641\u064a `{len(test_files)}` \u0645\u0644\u0641 \u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a \u0622\u0644\u064a\u0629.")
        sol_ar = " ".join(ar_highlights) if ar_highlights else "\u062a\u0637\u0628\u064a\u0642 \u0627\u0644\u062a\u0639\u062f\u064a\u0644\u0627\u062a \u0627\u0644\u0645\u0637\u0644\u0648\u0628\u0629 \u0648\u0641\u0642 \u062a\u0633\u0644\u0633\u0644 \u0627\u0644\u0645\u0639\u0645\u0627\u0631\u064a\u0629 \u0627\u0644\u0646\u0638\u064a\u0641\u0629."

    checks_en = list(brief.get("checks_en") or [])
    checks_ar = list(brief.get("checks_ar") or [])
    if not checks_ar or not checks_en:
        hotspots = [f for f in ordered_files if f["triage"] == "HOTSPOT"][:3] or non_test_files[:3]
        if not checks_en:
            checks_en = [f"Inspect `{Path(h['path']).name}` \u2014 {h.get('why_en', '')}" for h in hotspots]
        if not checks_ar:
            checks_ar = [f"\u0631\u0627\u062c\u0639 `{Path(h['path']).name}` \u2014 {h.get('why_ar', '')}" for h in hotspots]

    return {
        "problem_en": prob_en,
        "problem_ar": prob_ar,
        "solution_en": sol_en,
        "solution_ar": sol_ar,
        "checks_en": checks_en[:4],
        "checks_ar": checks_ar[:4],
    }


def _ide_uri(repo: Path, rel_path: str, line: int = 1) -> str:
    abs_posix = (repo / rel_path).resolve().as_posix()
    if not abs_posix.startswith("/"):
        abs_posix = "/" + abs_posix
    return f"vscode://file{abs_posix}:{max(1, line)}"


def _i18n_span(en_text: str, ar_text: str, cls: str = "") -> str:
    esc = html.escape
    cls_attr = f' class="{esc(cls)}"' if cls else ""
    return f'<span{cls_attr} data-en="{esc(en_text)}" data-ar="{esc(ar_text)}">{esc(ar_text)}</span>'


def _render_cockpit_html(
    repo: Path,
    task_id: str,
    ordered_files: list[dict[str, Any]],
    blast_callers: list[dict[str, Any]],
    gates: list[dict[str, str]],
    xray: dict[str, Any],
    traceability: dict[str, Any],
    brief: dict[str, Any],
    generated_at: str,
) -> str:
    esc = html.escape
    total_added = sum(int(f["added"]) for f in ordered_files)
    total_deleted = sum(int(f["deleted"]) for f in ordered_files)
    hotspot_count = sum(1 for f in ordered_files if f["triage"] == "HOTSPOT")
    side_effects = traceability["side_effect_files"]
    side_effect_set = {item["path"] for item in side_effects}

    title_en, title_ar = _humanize_task_titles(task_id, traceability["outcome"], brief)

    # First compute per-file why_en / why_ar so story cards can leverage them too
    for fobj in ordered_files:
        rel_p = fobj["path"]
        file_findings = xray["by_file"].get(rel_p, [])
        why_en, why_ar = _enrich_file_rationale(fobj, traceability, file_findings, side_effect_set, brief)
        fobj["why_en"] = why_en
        fobj["why_ar"] = why_ar

    story = _build_story_cards_content(task_id, title_en, title_ar, ordered_files, traceability, brief)

    gate_labels_ar = {
        "compile": "\u0627\u0644\u062a\u0631\u062c\u0645\u0629 \u0646\u0627\u062c\u062d\u0629",
        "preflight": "\u0641\u062d\u0635 \u0627\u0644\u0643\u0648\u062f \u0633\u0644\u064a\u0645",
        "unit_tests": "\u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a \u0646\u0627\u062c\u062d\u0629",
        "localization": "\u0627\u0644\u062a\u0631\u062c\u0645\u0627\u062a \u0633\u0644\u064a\u0645\u0629",
        "check_strings": "\u0627\u0644\u0646\u0635\u0648\u0635 \u0633\u0644\u064a\u0645\u0629",
        "roborazzi_ui": "\u0641\u062d\u0635 \u0627\u0644\u0648\u0627\u062c\u0647\u0627\u062a \u0646\u0627\u062c\u062d",
        "maestro_e2e": "\u0627\u062e\u062a\u0628\u0627\u0631 E2E \u0646\u0627\u062c\u062d",
    }
    gate_badges_html = "".join(
        f'<span class="pill pill-pass">&#10003; '
        + _i18n_span(f'{g["gate"]} PASS', gate_labels_ar.get(g["gate"], f'{g["gate"]} PASS'))
        + "</span>"
        for g in gates
    ) or ('<span class="pill pill-neutral">' + _i18n_span("Isolated Task Diff", "\u062a\u0639\u062f\u064a\u0644\u0627\u062a \u0627\u0644\u0645\u0647\u0645\u0629 \u0627\u0644\u0645\u0639\u0632\u0648\u0644\u0629") + "</span>")

    check_items_html: list[str] = []
    c_ar_list = story["checks_ar"]
    c_en_list = story["checks_en"]
    if brief.get("checks_ar") and not brief.get("checks_en"):
        c_en_list = c_en_list[:len(c_ar_list)]
    elif brief.get("checks_en") and not brief.get("checks_ar"):
        c_ar_list = c_ar_list[:len(c_en_list)]
    max_checks = max(len(c_ar_list), len(c_en_list))
    for c_i in range(max_checks):
        c_en = c_en_list[c_i] if c_i < len(c_en_list) else c_ar_list[c_i]
        c_ar = c_ar_list[c_i] if c_i < len(c_ar_list) else c_en
        check_items_html.append(f'<li>{_i18n_span(c_en, c_ar)}</li>')

    file_jump_chips = " ".join(
        f'<a href="#file-{idx}" class="chip-link ltr-code">{esc(Path(f["path"]).name)}</a>'
        for idx, f in enumerate(ordered_files)
        if f["layer_key"] != "TESTS"
    )

    side_effect_banner = ""
    if side_effects:
        items_html = "".join(
            f'<li><code class="ltr-code">{esc(se["path"])}</code> '
            f'<span class="ltr-code muted">(+{se["added"]}/-{se["deleted"]})</span> &mdash; '
            + _i18n_span(se["reason"], se["reason_ar"])
            + "</li>"
            for se in side_effects
        )
        side_effect_banner = (
            '<section class="alert-card" id="side-effects-panel">'
            '<div class="alert-hdr">&#9888; '
            + _i18n_span(
                f"Side-Effect / Extra-Scope Files Outside Initial Plan ({len(side_effects)})",
                f"{AR_STRINGS['side_effect_title']} ({len(side_effects)})",
            )
            + f'</div><ul class="clean-list">{items_html}</ul></section>'
        )

    if blast_callers:
        caller_rows_list: list[str] = []
        for c in blast_callers:
            def_badge = (
                ' <span class="pill pill-warn">'
                + _i18n_span("default-arg", "\u0645\u0639\u0627\u0645\u0644 \u0627\u0641\u062a\u0631\u0627\u0636\u064a")
                + "</span>"
                if c["has_default_arg"]
                else ""
            )
            ide_href = esc(_ide_uri(repo, c["caller_file"], c["line"]))
            caller_rows_list.append(
                f'<tr>'
                f'<td><code class="ltr-code">{esc(c["symbol"])}</code>{def_badge}</td>'
                f'<td><code class="ltr-code">{esc(c["caller_file"])}:{c["line"]}</code></td>'
                f'<td><code class="ltr-code snippet-box">{esc(c["snippet"])}</code></td>'
                f'<td><a class="btn-sm" href="{ide_href}">' + _i18n_span("Open IDE", AR_STRINGS["open_ide"]) + '</a></td>'
                f'</tr>'
            )
        blast_open = ""
        blast_html = (
            f'<details class="panel-card secondary-drawer" id="blast-radius-panel"{blast_open}>'
            '<summary class="panel-summary">'
            '<div class="drawer-title-group"><span>&#128279; '
            + _i18n_span(
                f"Unmodified Blast-Radius Callers ({len(blast_callers)})",
                f"{AR_STRINGS['blast_title']} ({len(blast_callers)})",
            )
            + '</span><span class="drawer-sub">'
            + _i18n_span(
                "Other files calling the modified functions \u2014 click to inspect if needed",
                AR_STRINGS["blast_sub"],
            )
            + '</span></div></summary>'
            '<div class="table-wrap"><table class="ag-table">'
            '<thead><tr>'
            '<th>' + _i18n_span("Modified Symbol", AR_STRINGS["col_symbol"]) + '</th>'
            '<th>' + _i18n_span("Unmodified Caller", AR_STRINGS["col_caller"]) + '</th>'
            '<th>' + _i18n_span("Call-Site Excerpt", AR_STRINGS["col_snippet"]) + '</th>'
            '<th>' + _i18n_span("IDE", AR_STRINGS["col_action"]) + '</th>'
            f'</tr></thead><tbody>{"".join(caller_rows_list)}</tbody></table></div></details>'
        )
    else:
        blast_html = ""

    xray_rounds = xray["rounds"]
    xray_findings = xray["all_findings"]
    active_unresolved = sum(1 for f in xray_findings if f["state"] == "ACTIVE")
    if xray_rounds or xray_findings:
        f_items_list: list[str] = []
        for f in xray_findings[:20]:
            is_res = f["state"] == "RESOLVED_IN_LATER_ROUND"
            p_cls = "pill-pass" if is_res else ("pill-info" if f["state"] == "ADVISORY" else "pill-warn")
            st_ar = (
                AR_STRINGS["badge_resolved"]
                if is_res
                else (AR_STRINGS["badge_advisory"] if f["state"] == "ADVISORY" else AR_STRINGS["badge_active"])
            )
            loc_str = f":{f['line']}" if f["line"] else ""
            short_file = Path(f["file"]).name if f["file"] else ""
            file_tag_html = f'<code class="ltr-code">{esc(short_file)}{loc_str}</code> ' if short_file else ""
            f_items_list.append(
                f'<li class="xray-item">'
                f'<div class="xray-item-hdr"><span class="pill {p_cls}">'
                + _i18n_span(f'{f["severity"]} - R{f["round"]} ({f["state"]})', f'\u062c\u0648\u0644\u0629 {f["round"]} - {st_ar}')
                + f'</span> {file_tag_html}'
                + f'<strong>{_i18n_span(f["title"], f["title_ar"])}</strong></div>'
                + f'<div class="xray-item-body">{_i18n_span(f["message"], f["message_ar"])}</div>'
                + "</li>"
            )
        xray_open = " open" if active_unresolved > 0 else ""
        xray_sub_ar = AR_STRINGS["xray_all_resolved"] if active_unresolved == 0 else AR_STRINGS["xray_has_notes"]
        xray_sub_en = (
            f"All final reviewers PASSED ({len(xray_findings)} prior note(s) resolved or advisory \u2014 click to expand)"
            if active_unresolved == 0
            else f"{active_unresolved} active review note(s) require attention"
        )
        status_pill_cls = "pill-pass" if active_unresolved == 0 else "pill-warn"
        xray_html = (
            f'<details class="panel-card secondary-drawer" id="xray-panel"{xray_open}>'
            '<summary class="panel-summary">'
            '<div class="drawer-title-group"><span>&#128737; '
            + _i18n_span(
                f"AI Review History ({len(xray_rounds)} round(s), {len(xray_findings)} note(s))",
                f"{AR_STRINGS['xray_title']} ({len(xray_rounds)} \u062c\u0648\u0644\u0627\u062a)",
            )
            + f'</span><span class="pill {status_pill_cls}">'
            + _i18n_span(xray_sub_en, xray_sub_ar)
            + '</span></div></summary>'
            + (f'<ul class="xray-list">{"".join(f_items_list)}</ul>' if f_items_list else "")
            + "</details>"
        )
    else:
        xray_html = ""

    toc_items: list[str] = []
    file_cards: list[str] = []
    current_layer_key = ""

    for idx, fobj in enumerate(ordered_files):
        rel_p = fobj["path"]
        triage = fobj["triage"]
        is_side = rel_p in side_effect_set
        file_findings = xray["by_file"].get(rel_p, [])
        has_ai_notes = "1" if file_findings else "0"
        l_key = fobj["layer_key"]
        l_title_en = fobj["layer_title"]
        l_title_ar = AR_STRINGS.get(f"layer_{l_key}", l_title_en)

        if l_key != current_layer_key:
            current_layer_key = l_key
            toc_items.append(f'<div class="toc-group">' + _i18n_span(l_title_en, l_title_ar) + "</div>")
            file_cards.append(f'<h2 class="layer-heading">' + _i18n_span(l_title_en, l_title_ar) + "</h2>")

        why_en = fobj["why_en"]
        why_ar = fobj["why_ar"]

        pill_cls = (
            "pill-hotspot" if triage == "HOTSPOT"
            else ("pill-neutral" if triage == "AUTO_COLLAPSED" else "pill-info")
        )
        triage_en = "PRIORITY REVIEW" if triage == "HOTSPOT" else ("TEST / ROUTINE" if triage == "AUTO_COLLAPSED" else "CORE CHANGE")
        triage_ar = (
            AR_STRINGS["badge_hotspot"]
            if triage == "HOTSPOT"
            else (AR_STRINGS["badge_collapsed"] if triage == "AUTO_COLLAPSED" else AR_STRINGS["badge_core"])
        )

        toc_items.append(
            f'<a class="toc-item toc-{triage.lower()}" href="#file-{idx}" id="toc-link-{idx}">'
            f'<span class="toc-name ltr-code">{esc(Path(rel_p).name)}</span>'
            f'<span class="toc-delta ltr-code">+{fobj["added"]}/-{fobj["deleted"]}</span>'
            f'</a>'
        )

        open_attr = " open" if triage == "HOTSPOT" else ""

        file_xray_html = ""
        if file_findings:
            fx_rows: list[str] = []
            for ff in file_findings:
                is_res = ff["state"] == "RESOLVED_IN_LATER_ROUND"
                p_c = "pill-pass" if is_res else "pill-warn"
                st_ar = AR_STRINGS["badge_resolved"] if is_res else AR_STRINGS["badge_advisory"]
                fx_rows.append(
                    f'<div class="xray-inline-row">'
                    f'<span class="pill {p_c}">'
                    + _i18n_span(f'R{ff["round"]} {ff["severity"]} ({ff["state"]})', f'\u062c\u0648\u0644\u0629 {ff["round"]} ({st_ar})')
                    + f'</span> <strong>{_i18n_span(ff["title"], ff["title_ar"])}:</strong> '
                    + _i18n_span(ff["message"], ff["message_ar"])
                    + "</div>"
                )
            file_xray_html = f'<div class="xray-inline">{"".join(fx_rows)}</div>'

        hunks_html_parts: list[str] = []
        for h_idx, hk in enumerate(fobj.get("hunks") or []):
            first_ln = int(hk.get("new_start") or hk.get("old_start") or 1)
            hk_ide = _ide_uri(repo, rel_p, first_ln)
            hk_r_en = ", ".join(hk.get("hotspot_reasons_en") or [])
            hk_r_ar = " \u060c ".join(hk.get("hotspot_reasons_ar") or [])
            hk_badge = (
                f'<span class="pill pill-hotspot">' + _i18n_span(hk_r_en, hk_r_ar) + "</span>"
                if hk_r_en
                else ""
            )
            hk_sum_en = str(hk.get("summary_en") or "")
            hk_sum_ar = str(hk.get("summary_ar") or "")

            rows_html: list[str] = []
            for l_idx, ln_obj in enumerate(hk.get("lines") or []):
                kind = ln_obj["kind"]
                o_s = str(ln_obj["old_ln"]) if ln_obj["old_ln"] is not None else ""
                n_s = str(ln_obj["new_ln"]) if ln_obj["new_ln"] is not None else ""
                target_ln = int(ln_obj["new_ln"] or ln_obj["old_ln"] or first_ln)
                prefix = "+" if kind == "add" else ("-" if kind == "del" else " ")
                note_id = f"f{idx}_h{h_idx}_l{l_idx}"
                rows_html.append(
                    f'<tr class="diff-line diff-{kind}" data-file="{esc(rel_p)}" data-line="{target_ln}" data-note-id="{note_id}">'
                    f'<td class="ln-col">{o_s}</td>'
                    f'<td class="ln-col">{n_s}</td>'
                    f'<td class="act-col"><button type="button" class="line-note-btn" title="Add note" '
                    f'data-slot="{esc(note_id)}" data-file="{esc(rel_p)}" data-line="{target_ln}" '
                    f'onclick="toggleNoteBoxFromBtn(this)">+</button></td>'
                    f'<td class="code-col"><pre>{prefix}{esc(ln_obj["text"])}</pre></td>'
                    f'</tr>'
                )
            hunks_html_parts.append(
                f'<div class="hunk-block">'
                f'<div class="hunk-bar">'
                f'<div class="hunk-bar-main">'
                f'<span class="pill pill-neutral ltr-code">Line {first_ln}</span> {hk_badge}'
                f'<span class="hunk-why">' + _i18n_span(hk_sum_en, hk_sum_ar) + '</span>'
                f'</div>'
                f'<div class="hunk-actions">'
                f'<a class="btn-sm" href="{esc(hk_ide)}">' + _i18n_span(f"Open :{first_ln}", f"\u0641\u062a\u062d \u0633\u0637\u0631 {first_ln}") + '</a>'
                f'<button type="button" class="btn-sm" data-ref="{esc(rel_p)}:{first_ln}" onclick="copyPathLine(this.getAttribute(\'data-ref\'), this)">'
                + _i18n_span("Copy", AR_STRINGS["copy_path"])
                + '</button>'
                f'<button type="button" class="btn-sm btn-accent-outline" data-slot="f{idx}_h{h_idx}" data-file="{esc(rel_p)}" data-line="{first_ln}" onclick="toggleNoteBoxFromBtn(this)">'
                + _i18n_span("+ Note", AR_STRINGS["add_note"])
                + '</button>'
                f'</div>'
                f'</div>'
                f'<div class="note-slot" id="slot-f{idx}_h{h_idx}"></div>'
                f'<div class="diff-scroll ltr-code"><table class="diff-table"><tbody>{"".join(rows_html)}</tbody></table></div>'
                f'</div>'
            )

        if not hunks_html_parts:
            hunks_html_parts.append(
                f'<div class="muted pad-14">' + _i18n_span(f'Binary or metadata-only task change ({fobj.get("status", "M")}).', f'\u062a\u0639\u062f\u064a\u0644 \u0645\u0644\u0641 \u062b\u0646\u0627\u0626\u064a \u0623\u0648 \u0628\u064a\u0627\u0646\u0627\u062a \u0648\u0635\u0641\u064a\u0629 ({fobj.get("status", "M")}).') + '</div>'
            )

        side_badge = (
            '<span class="pill pill-warn">'
            + _i18n_span("EXTRA SCOPE", AR_STRINGS["badge_side_effect"])
            + "</span>"
            if is_side
            else ""
        )
        parent_dir = str(Path(rel_p).parent.as_posix())
        dir_prefix = "" if parent_dir == "." else (parent_dir + "/")

        file_cards.append(
            f'<details class="file-card triage-{triage.lower()}" id="file-{idx}" data-file-idx="{idx}" '
            f'data-triage="{triage}" data-side-effect="{"1" if is_side else "0"}" data-ai-notes="{has_ai_notes}"{open_attr}>'
            f'<summary class="file-summary">'
            f'<div class="file-summary-top">'
            f'<div class="file-summary-left">'
            f'<span class="pill {pill_cls}">' + _i18n_span(triage_en, triage_ar) + f'</span> {side_badge}'
            f'<span class="file-name ltr-code">{esc(Path(rel_p).name)}</span>'
            f'<span class="file-dir ltr-code">{esc(dir_prefix)}</span>'
            f'</div>'
            f'<div class="file-summary-right">'
            f'<span class="ltr-code delta-box"><span class="delta-add">+{fobj["added"]}</span> <span class="delta-del">-{fobj["deleted"]}</span></span>'
            f'<button type="button" class="btn-sm btn-check" id="rev-btn-{idx}" onclick="event.stopPropagation(); toggleReviewed({idx})">'
            f'&#10003; ' + _i18n_span("Reviewed", AR_STRINGS["mark_reviewed"]) + '</button>'
            f'<a class="btn-sm" href="{esc(_ide_uri(repo, rel_p, 1))}" onclick="event.stopPropagation()">'
            + _i18n_span("Open IDE", AR_STRINGS["open_ide"])
            + '</a>'
            f'</div>'
            f'</div>'
            f'<div class="file-why-inline">'
            f'<span class="why-bullet">&#128161;</span> '
            + _i18n_span(why_en, why_ar)
            + '</div>'
            f'</summary>'
            f'{file_xray_html}'
            f'<div class="file-body">{"".join(hunks_html_parts)}</div>'
            f'</details>'
        )

    def _script_safe_json(val: Any) -> str:
        return json.dumps(val, ensure_ascii=True).replace("</", "<\\/")

    empty_files_html = "".join(file_cards) or (
        '<div class="panel-card">' + _i18n_span(
            "No task-isolated diff changes detected yet.",
            "\u0644\u0627 \u062a\u0648\u062c\u062f \u062a\u0639\u062f\u064a\u0644\u0627\u062a \u0643\u0648\u062f \u0645\u0633\u062c\u0651\u0644\u0629 \u0641\u064a \u0646\u0637\u0627\u0642 \u0647\u0630\u0647 \u0627\u0644\u0645\u0647\u0645\u0629 \u0628\u0639\u062f.",
        ) + "</div>"
    )
    task_status = traceability["status"]
    reopen_cmd = f"python .agents/harness.py task resume --repo . --task-id {task_id} --reopen"
    i18n_js_json = _script_safe_json(AR_STRINGS)

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title_ar)} &mdash; {esc(task_id)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@500;600;700;800&family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" media="print" onload="this.media='all'">
<style>
:root {{
  --ui-zoom: 1;
  --bg: #0b0e14;
  --surface: #121722;
  --surface-2: #181f2e;
  --surface-3: #20293c;
  --border: rgba(255, 255, 255, 0.10);
  --border-strong: rgba(255, 255, 255, 0.20);
  --text: #f8fafc;
  --text-soft: #d1d9e6;
  --muted: #94a3b8;
  --accent: #60a5fa;
  --accent-bg: rgba(96, 165, 250, 0.16);
  --why-tx: #dbeafe;
  --add-bg: rgba(34, 197, 94, 0.15);
  --add-bar: #22c55e;
  --add-tx: #bbf7d0;
  --del-bg: rgba(248, 113, 113, 0.15);
  --del-bar: #ef4444;
  --del-tx: #fecaca;
  --hot-bg: rgba(251, 113, 133, 0.18);
  --hot-tx: #fda4af;
  --warn-bg: rgba(251, 191, 36, 0.15);
  --warn-tx: #fde68a;
  --pass-bg: rgba(34, 197, 94, 0.18);
  --pass-tx: #86efac;
  --font-sans: 'Cairo', 'IBM Plex Sans Arabic', 'Inter', 'Segoe UI', Tahoma, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Cascadia Code', Consolas, ui-monospace, monospace;
}}
* {{ box-sizing: border-box; }}
html {{ font-size: calc(16px * var(--ui-zoom)); }}
body {{
  margin: 0;
  font-family: var(--font-sans);
  font-size: 1rem;
  background: var(--bg);
  color: var(--text);
  line-height: 1.7;
  padding-bottom: 100px;
  -webkit-font-smoothing: antialiased;
}}
.ltr-code, code, pre, .diff-table {{
  direction: ltr !important;
  unicode-bidi: isolate;
  font-family: var(--font-mono);
}}
.inline-code {{
  background: rgba(148, 163, 184, 0.16);
  color: #f1f5f9;
  padding: 1px 6px;
  border-radius: 5px;
  font-size: 0.88em;
  border: 1px solid rgba(255, 255, 255, 0.10);
}}
a {{ color: var(--accent); text-decoration: none; }}
.topbar {{
  position: sticky; top: 0; z-index: 40;
  background: rgba(11, 14, 20, 0.94);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
  padding: 14px 26px;
  display: flex; flex-wrap: wrap; gap: 16px; align-items: center; justify-content: space-between;
}}
.brand-row {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
.brand-dot {{ width: 12px; height: 12px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 14px var(--accent); }}
.brand-title {{ margin: 0; font-size: 1.35rem; font-weight: 800; color: var(--text); letter-spacing: -0.01em; }}
.task-slug-chip {{ font-size: 0.82rem; background: var(--surface-2); color: var(--muted); padding: 2px 9px; border-radius: 6px; border: 1px solid var(--border); }}
.subtitle {{ font-size: 0.90rem; color: var(--text-soft); display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-top: 4px; }}
.toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
.btn, .btn-sm {{
  font-family: var(--font-sans);
  background: var(--surface-2);
  color: var(--text-soft);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 7px 14px;
  font-size: 0.90rem;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px;
  transition: all 0.15s ease;
}}
.btn:hover, .btn-sm:hover {{ background: var(--surface-3); color: var(--text); border-color: var(--border-strong); }}
.btn.active {{ background: var(--accent-bg); border-color: rgba(96, 165, 250, 0.6); color: #bfdbfe; font-weight: 700; }}
.btn-lang {{ background: #1e293b; border-color: rgba(96, 165, 250, 0.55); color: #dbeafe; font-weight: 700; }}
.btn-zoom {{ padding: 6px 10px; font-weight: 800; }}
.btn-primary {{ background: #16a34a; border-color: #22c55e; color: #fff; font-weight: 700; }}
.btn-primary:hover {{ background: #22c55e; color: #fff; }}
.btn-sm {{ padding: 5px 11px; font-size: 0.84rem; border-radius: 7px; }}
.btn-accent-outline {{ border-color: rgba(96, 165, 250, 0.45); color: #bfdbfe; }}
.btn-check.reviewed {{ background: var(--pass-bg); border-color: rgba(34, 197, 94, 0.55); color: var(--pass-tx); font-weight: 700; }}

.layout {{
  display: grid;
  grid-template-columns: 295px minmax(0, 1fr);
  gap: 22px;
  max-width: 1760px;
  margin: 0 auto;
  padding: 20px 26px;
}}
@media (max-width: 1100px) {{
  .layout {{ grid-template-columns: 1fr; }}
  .sidebar {{ position: static !important; max-height: none !important; }}
}}
.sidebar {{
  position: sticky; top: 88px; align-self: start;
  max-height: calc(100vh - 180px); overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px;
}}
.sidebar-hdr {{ font-size: 0.98rem; font-weight: 800; color: var(--text); margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }}
.toc-group {{ font-size: 0.85rem; font-weight: 700; color: var(--accent); margin: 16px 0 7px; }}
.toc-group:first-child {{ margin-top: 2px; }}
.toc-item {{
  display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 8px; font-size: 0.88rem; color: var(--text-soft); margin-bottom: 4px;
  border-inline-start: 3px solid transparent;
}}
.toc-item:hover {{ background: var(--surface-2); color: var(--text); }}
.toc-hotspot {{ border-inline-start-color: #fb7185; background: rgba(251, 113, 133, 0.05); }}
.toc-item.done-item {{ opacity: 0.55; border-inline-start-color: #22c55e; }}
.toc-name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }}
.toc-delta {{ font-size: 0.78rem; color: var(--muted); flex-shrink: 0; }}

.story-grid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 18px;
}}
@media (max-width: 1180px) {{ .story-grid {{ grid-template-columns: 1fr; }} }}
.story-card {{
  background: linear-gradient(180deg, var(--surface-2) 0%, var(--surface) 100%);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 20px;
  display: flex; flex-direction: column; justify-content: space-between;
}}
.story-hdr {{ font-size: 0.92rem; font-weight: 800; color: var(--accent); margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }}
.story-body {{ font-size: 0.98rem; color: var(--text); line-height: 1.72; margin: 0 0 10px; }}
.story-list {{ margin: 0; padding-inline-start: 20px; font-size: 0.95rem; color: var(--text); line-height: 1.7; }}
.story-list li {{ margin-bottom: 5px; }}
.gates-row {{ display: flex; gap: 7px; flex-wrap: wrap; margin-top: 8px; }}
.chip-link {{ background: var(--surface-3); border: 1px solid var(--border); padding: 3px 9px; border-radius: 7px; font-size: 0.82rem; color: var(--text-soft); display: inline-block; margin-top: 4px; }}
.chip-link:hover {{ border-color: var(--accent); color: var(--text); }}

.panel-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 15px 20px;
  margin-bottom: 16px;
}}
.secondary-drawer {{ background: rgba(18, 23, 34, 0.78); }}
.panel-summary {{ cursor: pointer; font-weight: 700; font-size: 1rem; display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }}
.drawer-title-group {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
.drawer-sub {{ font-size: 0.88rem; font-weight: 500; color: var(--muted); }}

.alert-card {{
  border-radius: 14px; padding: 16px 20px; margin-bottom: 16px;
  border: 1px solid rgba(251, 191, 36, 0.45);
  background: var(--warn-bg); color: var(--warn-tx);
}}
.alert-hdr {{ font-weight: 800; font-size: 1.02rem; margin-bottom: 6px; }}
.clean-list {{ margin: 10px 0 0; padding-inline-start: 22px; font-size: 0.95rem; }}
.clean-list li {{ margin-bottom: 6px; }}

.xray-list {{ list-style: none; margin: 14px 0 0; padding: 0; display: grid; gap: 10px; }}
.xray-item {{ background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 12px 15px; }}
.xray-item-hdr {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 0.96rem; margin-bottom: 4px; }}
.xray-item-body {{ font-size: 0.92rem; color: var(--text-soft); line-height: 1.65; }}

.pill {{ display: inline-flex; align-items: center; gap: 5px; padding: 3px 11px; border-radius: 999px; font-size: 0.82rem; font-weight: 700; }}
.pill-hotspot {{ background: var(--hot-bg); color: var(--hot-tx); border: 1px solid rgba(251, 113, 133, 0.40); }}
.pill-pass {{ background: var(--pass-bg); color: var(--pass-tx); border: 1px solid rgba(34, 197, 94, 0.40); }}
.pill-warn {{ background: var(--warn-bg); color: var(--warn-tx); border: 1px solid rgba(251, 191, 36, 0.40); }}
.pill-info {{ background: var(--accent-bg); color: #bfdbfe; border: 1px solid rgba(96, 165, 250, 0.38); }}
.pill-neutral {{ background: rgba(255, 255, 255, 0.08); color: var(--text-soft); }}

.layer-heading {{ font-size: 1.15rem; font-weight: 800; color: var(--text); margin: 28px 0 14px; display: flex; align-items: center; gap: 10px; }}
.layer-heading::before {{ content: ""; width: 5px; height: 22px; border-radius: 3px; background: var(--accent); display: inline-block; }}

.file-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  margin-bottom: 16px;
  overflow: hidden;
  transition: border-color 0.15s ease;
}}
.file-card.triage-hotspot {{ border-color: rgba(251, 113, 133, 0.45); }}
.file-card.is-reviewed {{ border-color: rgba(34, 197, 94, 0.50); opacity: 0.80; }}
.file-summary {{
  cursor: pointer; padding: 14px 20px;
  display: flex; flex-direction: column; gap: 8px;
  background: var(--surface-2);
  list-style: none;
}}
.file-summary::-webkit-details-marker {{ display: none; }}
.file-summary-top {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; width: 100%; }}
.file-summary-left, .file-summary-right {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
.file-name {{ font-size: 1.05rem; font-weight: 700; color: var(--text); }}
.file-dir {{ font-size: 0.84rem; color: var(--muted); }}
.file-why-inline {{
  font-size: 0.96rem;
  font-weight: 500;
  color: var(--why-tx);
  background: rgba(96, 165, 250, 0.08);
  border-inline-start: 3px solid var(--accent);
  padding: 7px 12px;
  border-radius: 7px;
  line-height: 1.6;
}}
.why-bullet {{ margin-inline-end: 5px; }}
.delta-box {{ background: rgba(0, 0, 0, 0.25); padding: 3px 9px; border-radius: 7px; }}
.delta-add {{ color: var(--add-tx); font-size: 0.88rem; font-weight: 700; }}
.delta-del {{ color: var(--del-tx); font-size: 0.88rem; font-weight: 700; }}

.xray-inline {{ background: rgba(251, 191, 36, 0.08); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 10px 20px; font-size: 0.92rem; }}
.xray-inline-row {{ margin: 5px 0; }}

.hunk-block {{ border-top: 1px solid var(--border); }}
.hunk-bar {{
  background: #0e131d;
  padding: 10px 18px;
  font-size: 0.90rem;
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
}}
.hunk-bar-main {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
.hunk-why {{ color: var(--text); font-size: 0.93rem; font-weight: 600; }}
.hunk-actions {{ display: flex; gap: 7px; align-items: center; }}

.diff-scroll {{ overflow-x: auto; background: #0a0d14; }}
.diff-table {{ width: 100%; border-collapse: collapse; font-size: 0.90rem; line-height: 1.72; }}
.diff-line td {{ padding: 3px 10px; vertical-align: top; }}
.ln-col {{ width: 52px; text-align: right; color: var(--muted); user-select: none; font-size: 0.82rem; opacity: 0.8; }}
.act-col {{ width: 30px; text-align: center; user-select: none; }}
.line-note-btn {{
  opacity: 0; background: var(--accent); color: #090b0e; font-weight: 800;
  border: none; border-radius: 5px; width: 22px; height: 22px; font-size: 0.92rem; line-height: 20px; cursor: pointer; padding: 0;
}}
.diff-line:hover .line-note-btn {{ opacity: 1; }}
.code-col pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font-family: var(--font-mono); }}
.diff-add {{ background: var(--add-bg); box-shadow: inset 4px 0 0 var(--add-bar); }}
.diff-add .code-col pre {{ color: var(--add-tx); }}
.diff-del {{ background: var(--del-bg); box-shadow: inset 4px 0 0 var(--del-bar); }}
.diff-del .code-col pre {{ color: var(--del-tx); }}

.note-box {{ background: #101726; border: 1px solid rgba(96, 165, 250, 0.55); border-radius: 10px; padding: 12px 14px; margin: 10px 18px; direction: rtl; }}
html[dir="ltr"] .note-box {{ direction: ltr; }}
.note-box textarea {{
  width: 100%; min-height: 72px; background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: 8px; padding: 10px 12px;
  font-size: 0.96rem; font-family: var(--font-sans); line-height: 1.6;
}}
.note-box-bar {{ display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 0.85rem; color: var(--muted); }}

.table-wrap {{ overflow-x: auto; margin-top: 12px; }}
.ag-table {{ width: 100%; border-collapse: collapse; font-size: 0.90rem; }}
.ag-table th, .ag-table td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: start; }}
.ag-table th {{ color: var(--muted); font-weight: 700; font-size: 0.85rem; }}
.snippet-box {{ font-size: 0.84rem; color: var(--text-soft); }}
.muted {{ color: var(--muted); }}
.pad-14 {{ padding: 16px; }}

.dock {{
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 50;
  background: rgba(12, 16, 24, 0.96); backdrop-filter: blur(12px);
  border-top: 1px solid var(--border-strong);
  padding: 13px 26px;
  display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap;
}}
.toast {{ color: var(--pass-tx); font-size: 0.92rem; font-weight: 700; display: none; margin-inline-start: 8px; }}
</style>
</head>
<body>
<header class="topbar">
  <div>
    <div class="brand-row">
      <span class="brand-dot"></span>
      <h1 class="brand-title">{_i18n_span(title_en, title_ar)}</h1>
      <code class="task-slug-chip ltr-code">{esc(task_id)}</code>
      <span class="pill pill-pass" id="reviewed-counter">0 / {len(ordered_files)}</span>
    </div>
    <div class="subtitle">
      <span class="pill pill-info">{_i18n_span(traceability["kind"], AR_STRINGS["app_badge"])}</span>
      <span class="ltr-code"><span class="delta-add">+{total_added}</span> / <span class="delta-del">-{total_deleted}</span></span>
      <span class="muted">{esc(generated_at[:16].replace("T", " "))}</span>
    </div>
  </div>
  <div class="toolbar">
    <button type="button" class="btn active" onclick="applyFilter('ALL', this)">{_i18n_span("All", AR_STRINGS["filter_all"])} ({len(ordered_files)})</button>
    <button type="button" class="btn" onclick="applyFilter('HOTSPOT', this)">{_i18n_span("Priority", AR_STRINGS["filter_hotspot"])} ({hotspot_count})</button>
    <button type="button" class="btn" onclick="applyFilter('SIDE_EFFECT', this)">{_i18n_span("Extra Scope", AR_STRINGS["filter_side_effect"])} ({len(side_effects)})</button>
    <button type="button" class="btn" onclick="applyFilter('AI_NOTES', this)">{_i18n_span("AI Notes", AR_STRINGS["filter_ai_notes"])}</button>
    <button type="button" class="btn" onclick="expandAll(true)">{_i18n_span("Expand All", AR_STRINGS["expand_all"])}</button>
    <button type="button" class="btn" onclick="expandAll(false)">{_i18n_span("Collapse Routine", AR_STRINGS["collapse_boilerplate"])}</button>
    <button type="button" class="btn btn-zoom" title="Decrease font size" onclick="adjustZoom(-0.08)">A-</button>
    <button type="button" class="btn btn-zoom" title="Increase font size" onclick="adjustZoom(0.08)">A+</button>
    <button type="button" class="btn btn-lang" id="lang-toggle-btn" onclick="toggleLanguage()">English (LTR)</button>
  </div>
</header>

<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-hdr">
      {_i18n_span("Architecture Order", AR_STRINGS["sidebar_title"])}
      <span class="muted ltr-code">{len(ordered_files)}</span>
    </div>
    {"".join(toc_items) or "<div class='muted'>-</div>"}
  </aside>

  <main>
    {side_effect_banner}
    <section class="story-grid" id="story-panel">
      <div class="story-card">
        <div>
          <div class="story-hdr">&#127919; {_i18n_span("1. Problem & Goal", AR_STRINGS["story_problem"])}</div>
          <p class="story-body">{_i18n_span(story["problem_en"], story["problem_ar"])}</p>
        </div>
        <div class="gates-row">{gate_badges_html}</div>
      </div>
      <div class="story-card">
        <div>
          <div class="story-hdr">&#128736; {_i18n_span("2. What Changed Architecturally", AR_STRINGS["story_solution"])}</div>
          <p class="story-body">{_i18n_span(story["solution_en"], story["solution_ar"])}</p>
        </div>
        <div>{file_jump_chips}</div>
      </div>
      <div class="story-card">
        <div>
          <div class="story-hdr">&#128064; {_i18n_span("3. Quick 2-Minute Check", AR_STRINGS["story_check"])}</div>
          <ul class="story-list">{"".join(check_items_html)}</ul>
        </div>
      </div>
    </section>

    {xray_html}
    {blast_html}

    <section id="files-container">
      {empty_files_html}
    </section>
  </main>
</div>

<footer class="dock">
  <div>
    <strong>{_i18n_span("Need a tweak?", AR_STRINGS["dock_title"])}</strong>
    <span id="note-counter" class="pill pill-info">0</span>
    <span class="muted">{_i18n_span("Click (+ Note) beside any line to write adjustments, then copy the ready Antigravity command.", AR_STRINGS["dock_hint"])}</span>
    <span id="copy-toast" class="toast">&#10003; {_i18n_span("Copied!", AR_STRINGS["copied_toast"])}</span>
  </div>
  <div class="toolbar">
    <button type="button" class="btn" onclick="clearAllNotes()">{_i18n_span("Clear Notes", AR_STRINGS["clear_notes"])}</button>
    <button type="button" class="btn btn-primary" onclick="copySurgicalPrompt()">{_i18n_span("Copy Antigravity Surgical Fix Prompt", AR_STRINGS["copy_prompt"])}</button>
  </div>
</footer>

<script>
const AR = {i18n_js_json};
const STORAGE_KEY = "harness_review_notes_{esc(task_id)}";
const REV_STORAGE_KEY = "harness_reviewed_files_{esc(task_id)}";
const LANG_STORAGE_KEY = "harness_cockpit_lang";
const ZOOM_STORAGE_KEY = "harness_cockpit_zoom";
const TASK_ID = {_script_safe_json(task_id)};
const TASK_STATUS = {_script_safe_json(task_status)};
const TOTAL_FILES = {len(ordered_files)};
const REOPEN_CMD = {_script_safe_json(reopen_cmd)};

let currentLang = "ar";
let currentZoom = 1.0;
let notesState = {{}};
let reviewedState = {{}};
try {{
  const savedLang = localStorage.getItem(LANG_STORAGE_KEY);
  if (savedLang === "en" || savedLang === "ar") currentLang = savedLang;
  const savedZoom = parseFloat(localStorage.getItem(ZOOM_STORAGE_KEY) || "1");
  if (!isNaN(savedZoom) && savedZoom >= 0.85 && savedZoom <= 1.35) currentZoom = savedZoom;
  notesState = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}") || {{}};
  reviewedState = JSON.parse(localStorage.getItem(REV_STORAGE_KEY) || "{{}}") || {{}};
}} catch (_e) {{}}

function applyZoom(z) {{
  currentZoom = Math.min(1.35, Math.max(0.85, Math.round(z * 100) / 100));
  document.documentElement.style.setProperty("--ui-zoom", String(currentZoom));
  try {{ localStorage.setItem(ZOOM_STORAGE_KEY, String(currentZoom)); }} catch (_e) {{}}
}}

function adjustZoom(delta) {{
  applyZoom(currentZoom + delta);
}}

function applyLanguage(lang) {{
  currentLang = lang;
  document.documentElement.lang = lang;
  document.documentElement.dir = (lang === "ar") ? "rtl" : "ltr";
  const btn = document.getElementById("lang-toggle-btn");
  if (btn) btn.textContent = (lang === "ar") ? "English (LTR)" : "\u0639\u0631\u0628\u064a (RTL)";
  function fmtInlineCode(raw) {{
    const safe = String(raw || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    return safe.replace(
      /`([^`]+)`|(^|\\s)(@[A-Za-z_][A-Za-z0-9_]*|[A-Za-z0-9_]+\\.(?:kt|java|xml|kts|gradle|json|py)\\b)/g,
      function (_m, bt, lead, tok) {{
        if (bt !== undefined) return '<code class="inline-code ltr-code">' + bt + '</code>';
        return (lead || "") + '<code class="inline-code ltr-code">' + tok + '</code>';
      }}
    );
  }}
  document.querySelectorAll("[data-en]").forEach(el => {{
    const txt = (lang === "ar") ? (el.getAttribute("data-ar") || el.getAttribute("data-en")) : el.getAttribute("data-en");
    if (txt && (txt.indexOf("`") !== -1 || txt.indexOf("@") !== -1 || /\\.[a-z]{{2,4}}\\b/i.test(txt))) {{
      el.innerHTML = fmtInlineCode(txt);
    }} else {{
      el.textContent = txt;
    }}
  }});
  document.querySelectorAll(".note-box textarea").forEach(ta => {{
    ta.placeholder = (lang === "ar") ? AR.note_placeholder : "Write surgical adjustment for this line...";
  }});
  updateReviewedCounter();
  persistNotes();
  try {{ localStorage.setItem(LANG_STORAGE_KEY, lang); }} catch (_e) {{}}
}}

function toggleLanguage() {{
  applyLanguage(currentLang === "ar" ? "en" : "ar");
}}

function updateReviewedCounter() {{
  const doneCount = Object.values(reviewedState).filter(Boolean).length;
  const badge = document.getElementById("reviewed-counter");
  if (!badge) return;
  if (currentLang === "ar") {{
    badge.textContent = AR.reviewed_progress + " " + doneCount + " " + AR.of_word + " " + TOTAL_FILES;
  }} else {{
    badge.textContent = "Reviewed " + doneCount + " / " + TOTAL_FILES;
  }}
}}

function toggleReviewed(fileIdx) {{
  const next = !reviewedState[fileIdx];
  reviewedState[fileIdx] = next;
  try {{ localStorage.setItem(REV_STORAGE_KEY, JSON.stringify(reviewedState)); }} catch (_e) {{}}
  syncReviewedDom(fileIdx, next, true);
  updateReviewedCounter();
}}

function syncReviewedDom(fileIdx, isDone, autoCollapse) {{
  const card = document.getElementById("file-" + fileIdx);
  const btn = document.getElementById("rev-btn-" + fileIdx);
  const toc = document.getElementById("toc-link-" + fileIdx);
  if (card) {{
    card.classList.toggle("is-reviewed", Boolean(isDone));
    if (autoCollapse && isDone) card.removeAttribute("open");
    else if (autoCollapse && !isDone && card.dataset.triage !== "AUTO_COLLAPSED") card.setAttribute("open", "");
  }}
  if (btn) btn.classList.toggle("reviewed", Boolean(isDone));
  if (toc) toc.classList.toggle("done-item", Boolean(isDone));
}}

function persistNotes() {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(notesState)); }} catch (_e) {{}}
  const count = Object.values(notesState).filter(n => n && n.text && n.text.trim()).length;
  const el = document.getElementById("note-counter");
  if (el) {{
    el.textContent = (currentLang === "ar") ? (count + " " + AR.notes_count_suffix) : (count + (count === 1 ? " note" : " notes"));
  }}
}}

function toggleNoteBoxFromBtn(btn) {{
  if (!btn) return;
  const slotKey = btn.getAttribute("data-slot") || "";
  const filePath = btn.getAttribute("data-file") || "";
  const lineNum = parseInt(btn.getAttribute("data-line") || "1", 10) || 1;
  toggleNoteBox(slotKey, filePath, lineNum);
}}

function toggleNoteBox(slotKey, filePath, lineNum) {{
  let container = document.getElementById("slot-" + slotKey);
  if (!container) {{
    const row = document.querySelector('[data-note-id="' + slotKey + '"]');
    if (!row) return;
    const next = row.nextElementSibling;
    if (next && next.classList.contains("inline-note-row")) {{
      next.remove();
      return;
    }}
    const tr = document.createElement("tr");
    tr.className = "inline-note-row";
    const td = document.createElement("td");
    td.colSpan = 4;
    container = document.createElement("div");
    container.id = "slot-" + slotKey;
    td.appendChild(container);
    tr.appendChild(td);
    row.parentNode.insertBefore(tr, row.nextSibling);
  }} else if (container.innerHTML.trim() !== "") {{
    container.innerHTML = "";
    return;
  }}
  const existing = (notesState[slotKey] && notesState[slotKey].text) ? notesState[slotKey].text : "";
  const ph = (currentLang === "ar") ? AR.note_placeholder : "Write surgical adjustment for this line...";
  const savedLbl = (currentLang === "ar") ? AR.note_saved : "Saved automatically";
  const rmLbl = (currentLang === "ar") ? AR.remove_btn : "Remove";
  container.textContent = "";
  const box = document.createElement("div");
  box.className = "note-box";
  const hdr = document.createElement("div");
  hdr.style.cssText = "font-size:0.86rem;color:#bfdbfe;margin-bottom:6px;";
  const codeEl = document.createElement("code");
  codeEl.className = "ltr-code";
  codeEl.textContent = String(filePath) + ":" + String(lineNum);
  hdr.appendChild(codeEl);
  const ta = document.createElement("textarea");
  ta.setAttribute("dir", "auto");
  ta.placeholder = ph;
  ta.value = existing;
  ta.addEventListener("input", function () {{
    updateNote(slotKey, filePath, lineNum, ta.value);
  }});
  const bar = document.createElement("div");
  bar.className = "note-box-bar";
  const savedSpan = document.createElement("span");
  savedSpan.textContent = savedLbl;
  const rmBtn = document.createElement("button");
  rmBtn.type = "button";
  rmBtn.className = "btn-sm";
  rmBtn.textContent = rmLbl;
  rmBtn.addEventListener("click", function () {{
    removeNote(slotKey);
  }});
  bar.appendChild(savedSpan);
  bar.appendChild(rmBtn);
  box.appendChild(hdr);
  box.appendChild(ta);
  box.appendChild(bar);
  container.appendChild(box);
  ta.focus();
}}

function updateNote(slotKey, filePath, lineNum, text) {{
  if (!text || !text.trim()) delete notesState[slotKey];
  else notesState[slotKey] = {{ file: filePath, line: lineNum, text: text }};
  persistNotes();
}}

function removeNote(slotKey) {{
  delete notesState[slotKey];
  persistNotes();
  const c = document.getElementById("slot-" + slotKey);
  if (c) c.innerHTML = "";
}}

function clearAllNotes() {{
  notesState = {{}};
  persistNotes();
  document.querySelectorAll(".note-slot").forEach(el => {{ el.innerHTML = ""; }});
  document.querySelectorAll(".inline-note-row").forEach(el => el.remove());
}}

function copyText(text) {{
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
  }} else {{
    fallbackCopy(text);
  }}
}}

function fallbackCopy(text) {{
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try {{ document.execCommand("copy"); }} catch (_e) {{}}
  ta.remove();
}}

function copyPathLine(ref, btn) {{
  copyText(ref);
  if (!btn) return;
  const prev = btn.textContent;
  btn.textContent = "\u2713";
  setTimeout(() => {{ btn.textContent = prev; }}, 1200);
}}

function buildSurgicalPromptText() {{
  const entries = Object.values(notesState).filter(n => n && n.text && n.text.trim());
  if (!entries.length) {{
    return (currentLang === "ar")
      ? "\u0644\u0645 \u062a\u0643\u062a\u0628 \u0623\u064a \u0645\u0644\u0627\u062d\u0638\u0627\u062a \u0628\u0639\u062f. \u0627\u0636\u063a\u0637 (+ \u0645\u0644\u0627\u062d\u0638\u0629 \u062a\u0639\u062f\u064a\u0644) \u0628\u062c\u0627\u0646\u0628 \u0623\u064a \u0633\u0637\u0631 \u0623\u0648\u0644\u0627\u064b."
      : "No inline review notes entered yet. Click (+ Note) beside any line first.";
  }}
  entries.sort((a, b) => (a.file.localeCompare(b.file) || (a.line - b.line)));
  const lines = [];
  if (TASK_STATUS === "READY_FOR_DELIVERY" || TASK_STATUS === "VERIFYING") {{
    lines.push("Run `" + REOPEN_CMD + "` and apply ONLY the following surgical developer review adjustments on task `" + TASK_ID + "` without touching unrelated logic:");
  }} else {{
    lines.push("Apply ONLY the following surgical developer review adjustments on task `" + TASK_ID + "` without touching unrelated logic:");
  }}
  entries.forEach((item, i) => {{
    lines.push((i + 1) + ". `" + item.file + ":" + item.line + "` \u2014 " + item.text.trim());
  }});
  return lines.join(String.fromCharCode(10));
}}

function copySurgicalPrompt() {{
  copyText(buildSurgicalPromptText());
  const toast = document.getElementById("copy-toast");
  if (toast) {{
    toast.style.display = "inline";
    setTimeout(() => {{ toast.style.display = "none"; }}, 2400);
  }}
}}

function applyFilter(mode, btn) {{
  document.querySelectorAll(".topbar .toolbar .btn:not(.btn-lang):not(.btn-zoom)").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  document.querySelectorAll(".file-card").forEach(card => {{
    let show = true;
    if (mode === "HOTSPOT") show = card.dataset.triage === "HOTSPOT";
    else if (mode === "SIDE_EFFECT") show = card.dataset.sideEffect === "1";
    else if (mode === "AI_NOTES") show = card.dataset.aiNotes === "1";
    card.style.display = show ? "" : "none";
  }});
}}

function expandAll(openState) {{
  document.querySelectorAll(".file-card").forEach(card => {{
    if (openState) card.setAttribute("open", "");
    else if (card.dataset.triage !== "HOTSPOT") card.removeAttribute("open");
  }});
}}

Object.keys(reviewedState).forEach(k => {{
  if (reviewedState[k]) syncReviewedDom(k, true, false);
}});
applyZoom(currentZoom);
applyLanguage(currentLang);
</script>
</body>
</html>
"""


def generate_human_review_cockpit(
    repo: Path,
    task_id: str | None = None,
    *,
    output_path: Path | None = None,
    open_browser: bool = False,
    brief_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate task-isolated `human-review.html` v3 and metadata JSON for `task_id`."""
    root = repo.resolve()
    resolved_tid = _resolve_target_task_id(root, task_id)
    t_dir = state_root(root) / "tasks" / resolved_tid
    plan_file = t_dir / "plan.json"
    if not plan_file.is_file():
        raise ValidationError(f"Task plan not found for '{resolved_tid}' at {plan_file}")
    plan = read_json(plan_file)

    if brief_updates and any(brief_updates.values()):
        brief = save_review_brief_updates(t_dir, brief_updates)
    else:
        brief = load_review_brief(t_dir)

    manifest = build_task_manifest(root, resolved_tid)
    diff_text = build_task_diff(root, resolved_tid, manifest)
    parsed_files = _parse_unified_diff(diff_text)

    changes = manifest.get("task_changes") if "task_changes" in manifest else (manifest.get("changes") or [])
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        rel_p = str(ch.get("path") or "").replace("\\", "/")
        if not rel_p or any(m in rel_p.lower() for m in SECRET_PATH_MARKERS):
            continue
        if rel_p not in parsed_files:
            f_disk = root / rel_p
            st = str(ch.get("status") or "A")
            if f_disk.is_file() and f_disk.suffix.lower() not in BINARY_SUFFIXES:
                try:
                    raw_lines = f_disk.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    raw_lines = []
                parsed_files[rel_p] = {
                    "path": rel_p,
                    "old_path": "",
                    "status": st,
                    "added": len(raw_lines),
                    "deleted": 0,
                    "hunks": [{
                        "header": f"@@ -0,0 +1,{len(raw_lines)} @@ new file",
                        "context_label": "new file",
                        "old_start": 0,
                        "old_count": 0,
                        "new_start": 1,
                        "new_count": len(raw_lines),
                        "lines": [{"kind": "add", "old_ln": None, "new_ln": idx, "text": txt} for idx, txt in enumerate(raw_lines, 1)],
                        "added": len(raw_lines),
                        "deleted": 0,
                    }] if raw_lines else [],
                }
            else:
                parsed_files[rel_p] = {
                    "path": rel_p,
                    "old_path": "",
                    "status": st,
                    "added": 0,
                    "deleted": 0,
                    "hunks": [],
                }

    enriched_files: list[dict[str, Any]] = []
    for rel_p, fobj in parsed_files.items():
        layer_order, layer_key, layer_title = classify_architectural_layer(rel_p)
        triage, reasons_en, reasons_ar = _classify_hunk_and_file_triage(
            rel_p, layer_key, fobj.get("status", "M"), fobj.get("hunks") or []
        )
        triage_rank = 0 if triage == "HOTSPOT" else (1 if triage == "STANDARD" else 2)
        fobj["layer_order"] = layer_order
        fobj["layer_key"] = layer_key
        fobj["layer_title"] = layer_title
        fobj["triage"] = triage
        fobj["triage_reasons"] = reasons_en
        fobj["triage_reasons_ar"] = reasons_ar
        fobj["_sort_key"] = (layer_order, triage_rank, rel_p)
        enriched_files.append(fobj)

    enriched_files.sort(key=lambda item: item["_sort_key"])

    modified_symbols = _extract_modified_symbols(parsed_files)
    blast_callers = _discover_unmodified_blast_radius_callers(root, set(parsed_files.keys()), modified_symbols)
    gates = _collect_verified_gates(root, t_dir, plan)
    xray = _collect_ai_review_xray(t_dir, brief)
    traceability = _collect_plan_traceability(t_dir, plan, parsed_files)
    generated_at = utc_now()
    title_en, title_ar = _humanize_task_titles(resolved_tid, traceability["outcome"], brief)

    html_doc = _render_cockpit_html(
        repo=root,
        task_id=resolved_tid,
        ordered_files=enriched_files,
        blast_callers=blast_callers,
        gates=gates,
        xray=xray,
        traceability=traceability,
        brief=brief,
        generated_at=generated_at,
    )

    target_html = Path(output_path).resolve() if output_path else (t_dir / "human-review.html")
    target_html.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target_html, html_doc.encode("utf-8"))

    summary = {
        "schema_version": 2,
        "task_id": resolved_tid,
        "title_en": title_en,
        "title_ar": title_ar,
        "has_ai_brief": bool(brief),
        "html_path": str(target_html),
        "file_uri": target_html.as_uri(),
        "generated_at": generated_at,
        "touched_files_count": len(enriched_files),
        "hotspot_files_count": sum(1 for f in enriched_files if f["triage"] == "HOTSPOT"),
        "auto_collapsed_files_count": sum(1 for f in enriched_files if f["triage"] == "AUTO_COLLAPSED"),
        "blast_radius_callers_count": len(blast_callers),
        "side_effect_files_count": len(traceability["side_effect_files"]),
        "verified_gates": [g["gate"] for g in gates],
        "ordered_files": [
            {
                "path": f["path"],
                "layer": f["layer_key"],
                "triage": f["triage"],
                "why_en": f.get("why_en", ""),
                "why_ar": f.get("why_ar", ""),
                "added": f["added"],
                "deleted": f["deleted"],
            }
            for f in enriched_files
        ],
    }
    atomic_write_json(t_dir / "human-review-summary.json", summary)

    opened = False
    if open_browser and os.environ.get("HARNESS_NO_BROWSER") != "1":
        try:
            opened = bool(webbrowser.open(target_html.as_uri()))
        except OSError:
            opened = False
    summary["opened_in_browser"] = opened
    return summary


def main(argv: list[str] | None = None) -> int:
    configure_utf8_output()
    parser = argparse.ArgumentParser(
        prog="harness.py review-diff",
        description="Generate task-isolated Interactive Human Review Cockpit v3 (`human-review.html`) with optional AI bilingual brief.",
    )
    parser.add_argument("--repo", default=".", help="Repository root path.")
    parser.add_argument("--task-id", "--task", dest="task_id", default=None, help="Target task ID (defaults to active task).")
    parser.add_argument("--output", default=None, help="Optional custom output HTML file path.")
    parser.add_argument("--open", action="store_true", help="Open generated HTML cockpit in default desktop browser.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    parser.add_argument("--title-ar", default="", help="Concise 3-7 word Arabic task headline.")
    parser.add_argument("--title-en", default="", help="Concise 3-7 word English task headline.")
    parser.add_argument("--problem-ar", default="", help="Plain-Arabic explanation of the problem/goal.")
    parser.add_argument("--problem-en", default="", help="Plain-English explanation of the problem/goal.")
    parser.add_argument("--solution-ar", default="", help="Plain-Arabic summary of how the solution works.")
    parser.add_argument("--solution-en", default="", help="Plain-English summary of how the solution works.")
    parser.add_argument("--check-ar", action="append", default=[], help="Quick human review point in Arabic (`item1::item2` or repeatable).")
    parser.add_argument("--check-en", action="append", default=[], help="Quick human review point in English (`item1::item2` or repeatable).")
    parser.add_argument("--file-note", action="append", default=[], help="Per-file rationale `File.kt::Arabic::English` (repeatable; `|` also supported).")
    args = parser.parse_args(argv)

    def _split_checks(raw_list: list[str]) -> list[str]:
        out_items: list[str] = []
        for raw_item in raw_list or []:
            s_val = str(raw_item or "")
            sep = "::" if "::" in s_val else "|"
            for piece in s_val.split(sep):
                if piece.strip():
                    out_items.append(piece.strip())
        return out_items

    brief_updates = {
        "title_ar": args.title_ar,
        "title_en": args.title_en,
        "problem_ar": args.problem_ar,
        "problem_en": args.problem_en,
        "solution_ar": args.solution_ar,
        "solution_en": args.solution_en,
        "checks_ar": _split_checks(args.check_ar),
        "checks_en": _split_checks(args.check_en),
        "file_notes_raw": list(args.file_note or []),
    }

    try:
        res = generate_human_review_cockpit(
            Path(args.repo),
            args.task_id,
            output_path=Path(args.output) if args.output else None,
            open_browser=bool(args.open),
            brief_updates=brief_updates,
        )
    except ValidationError as exc:
        if args.json:
            print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=True))
        else:
            print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=True))
    else:
        print(f"HUMAN_REVIEW_COCKPIT={res['html_path']}")
        print(f"HUMAN_REVIEW_URI={res['file_uri']}")
        print(
            f"[OK] Generated Interactive Review Cockpit v3 for `{res['task_id']}` ({res['title_en']}): "
            f"{res['touched_files_count']} isolated file(s), "
            f"{res['hotspot_files_count']} priority file(s), "
            f"{res['blast_radius_callers_count']} unmodified caller(s), "
            f"{res['side_effect_files_count']} extra-scope file(s)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
