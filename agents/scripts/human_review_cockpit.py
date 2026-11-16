#!/usr/bin/env python3
"""Interactive Human Review Cockpit generator (`human-review.html` / `harness.py review-diff`).

Builds a self-contained, zero-dependency, Antigravity-Dark HTML5 review cockpit with:
- Instant 1-click Arabic (RTL) <-> English (LTR) UI toggle while keeping all code/diffs/paths strictly LTR.
- Concise plain-language "Why this changed" rationale on every file card and every diff hunk.
- Strict task isolation (excludes pre-existing dirty workspace files) and Clean Architecture narrative ordering.
- 3-tier attention triage (Hotspots, Unmodified Blast-Radius Callers radar, Auto-collapsed boilerplate/tests)
  plus interactive per-file "Reviewed" progress tracking and an inline surgical `task resume --reopen` composer.
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

# Pure-ASCII unicode escapes keep the repository Python source 100% ASCII-clean
# while rendering crisp native Arabic in the browser HTML output.
AR_STRINGS: dict[str, str] = {
    "app_title": "\u0644\u0648\u062d\u0629 \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629 \u0627\u0644\u0633\u0631\u064a\u0639\u0629",
    "lang_btn": "English (LTR)",
    "reviewed_progress": "\u062a\u0645\u062a \u0645\u0631\u0627\u062c\u0639\u0629",
    "of_word": "\u0645\u0646",
    "files_word": "\u0645\u0644\u0641\u0627\u062a",
    "filter_all": "\u0627\u0644\u0643\u0644",
    "filter_hotspot": "\u0628\u0624\u0631 \u0627\u0644\u0642\u0631\u0627\u0631",
    "filter_side_effect": "\u062a\u0639\u062f\u064a\u0644\u0627\u062a \u062c\u0627\u0646\u0628\u064a\u0629",
    "filter_ai_notes": "\u0645\u0644\u0627\u062d\u0638\u0627\u062a \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u064a\u0646",
    "expand_all": "\u0641\u062a\u062d \u0627\u0644\u0643\u0644",
    "collapse_boilerplate": "\u0637\u064a\u0651 \u0627\u0644\u0631\u0648\u062a\u064a\u0646\u064a",
    "sidebar_title": "\u062a\u0633\u0644\u0633\u0644 \u0627\u0644\u0645\u0639\u0645\u0627\u0631\u064a\u0629",
    "goal_label": "\u0647\u062f\u0641 \u0627\u0644\u0645\u0647\u0645\u0629 \u0627\u0644\u0645\u0639\u062a\u0645\u062f",
    "scope_label": "\u0646\u0637\u0627\u0642 \u0627\u0644\u062e\u0637\u0629",
    "side_effect_title": "\u062a\u0646\u0628\u064a\u0647: \u0645\u0644\u0641\u0627\u062a \u0639\u064f\u062f\u0651\u0644\u062a \u062e\u0627\u0631\u062c \u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u062e\u0637\u0629 \u0627\u0644\u0623\u0648\u0644\u0649",
    "blast_title": "\u0631\u0627\u062f\u0627\u0631 \u0627\u0644\u0645\u0633\u062a\u062f\u0639\u064a\u0646 \u063a\u064a\u0631 \u0627\u0644\u0645\u0639\u062f\u0651\u064e\u0644\u064a\u0646 (\u062a\u0623\u0643\u062f \u0645\u0646 \u0639\u062f\u0645 \u062a\u0623\u062b\u0631\u0647\u0645)",
    "blast_empty": "\u0644\u0627 \u062a\u0648\u062c\u062f \u0627\u0633\u062a\u062f\u0639\u0627\u0621\u0627\u062a \u062e\u0627\u0631\u062c\u064a\u0629 \u0641\u064a \u0645\u0644\u0641\u0627\u062a \u063a\u064a\u0631 \u0645\u0639\u062f\u0644\u0629.",
    "col_symbol": "\u0627\u0644\u0639\u0646\u0635\u0631 \u0627\u0644\u0645\u0639\u062f\u0651\u064e\u0644",
    "col_caller": "\u0645\u0643\u0627\u0646 \u0627\u0644\u0627\u0633\u062a\u062f\u0639\u0627\u0621 \u063a\u064a\u0631 \u0627\u0644\u0645\u0644\u0645\u0648\u0633",
    "col_snippet": "\u0633\u0637\u0631 \u0627\u0644\u0627\u0633\u062a\u062f\u0639\u0627\u0621",
    "col_action": "\u0641\u062a\u062d",
    "xray_title": "\u062e\u0644\u0627\u0635\u0629 \u0645\u0631\u0627\u062c\u0639\u0627\u062a \u0627\u0644\u0630\u0643\u0627\u0621 \u0627\u0644\u0627\u0635\u0637\u0646\u0627\u0639\u064a \u0639\u0628\u0631 \u0627\u0644\u062c\u0648\u0644\u0627\u062a",
    "why_label": "\u0633\u0628\u0628 \u0627\u0644\u062a\u0639\u062f\u064a\u0644 \u0628\u0627\u062e\u062a\u0635\u0627\u0631:",
    "mark_reviewed": "\u062a\u0645\u062a \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629",
    "open_ide": "\u0641\u062a\u062d \u0641\u064a IDE",
    "copy_path": "\u0646\u0633\u062e \u0627\u0644\u0645\u0633\u0627\u0631",
    "add_note": "+ \u062a\u0639\u0644\u064a\u0642",
    "badge_hotspot": "\u0628\u0624\u0631\u0629 \u0642\u0631\u0627\u0631",
    "badge_core": "\u062a\u0639\u062f\u064a\u0644 \u0623\u0633\u0627\u0633\u064a",
    "badge_collapsed": "\u0645\u0637\u0648\u064a \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b",
    "badge_side_effect": "\u062e\u0627\u0631\u062c \u0627\u0644\u062e\u0637\u0629 \u0627\u0644\u0623\u0648\u0644\u0649",
    "badge_resolved": "\u062d\u064f\u0644\u0651\u062a \u0641\u064a \u062c\u0648\u0644\u0629 \u0644\u0627\u062d\u0642\u0629",
    "badge_advisory": "\u0645\u0644\u0627\u062d\u0638\u0629 \u062a\u062d\u0633\u064a\u0646\u064a\u0629",
    "badge_active": "\u0645\u0644\u0627\u062d\u0638\u0629 \u0645\u0641\u062a\u0648\u062d\u0629",
    "dock_title": "\u0645\u062c\u0647\u0651\u0632 \u0627\u0644\u062a\u0639\u062f\u064a\u0644\u0627\u062a \u0627\u0644\u062c\u0631\u0627\u062d\u064a\u0629:",
    "dock_hint": "\u0627\u0636\u063a\u0637 + \u0628\u062c\u0627\u0646\u0628 \u0623\u064a \u0633\u0637\u0631 \u0644\u0643\u062a\u0627\u0628\u0629 \u0645\u0644\u0627\u062d\u0638\u062a\u0643\u060c \u062b\u0645 \u0627\u0646\u0633\u062e \u0627\u0644\u0623\u0645\u0631 \u062c\u0627\u0647\u0632\u0627\u064b \u0644\u0640 Antigravity.",
    "clear_notes": "\u0645\u0633\u062d \u0627\u0644\u062a\u0639\u0644\u064a\u0642\u0627\u062a",
    "copy_prompt": "\u0646\u0633\u062e \u0623\u0645\u0631 \u0627\u0644\u062a\u0639\u062f\u064a\u0644 \u0627\u0644\u062c\u0631\u0627\u062d\u064a",
    "copied_toast": "\u062a\u0645 \u0627\u0644\u0646\u0633\u062e!",
    "note_placeholder": "\u0627\u0643\u062a\u0628 \u0627\u0644\u062a\u0639\u062f\u064a\u0644 \u0627\u0644\u0645\u0637\u0644\u0648\u0628 \u0639\u0644\u0649 \u0647\u0630\u0627 \u0627\u0644\u0633\u0637\u0631...",
    "note_saved": "\u0645\u062d\u0641\u0648\u0638 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b",
    "remove_btn": "\u062d\u0630\u0641",
    "notes_count_suffix": "\u062a\u0639\u0644\u064a\u0642",
    "layer_DOMAIN": "1. \u0637\u0628\u0642\u0629 \u0627\u0644\u0646\u0637\u0627\u0642 \u0648\u0627\u0644\u0642\u0648\u0627\u0639\u062f (Domain & UseCases)",
    "layer_DATA": "2. \u0637\u0628\u0642\u0629 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0648\u0627\u0644\u0634\u0628\u0643\u0629 (Data & Repositories)",
    "layer_VIEWMODEL": "3. \u0625\u062f\u0627\u0631\u0629 \u0627\u0644\u062d\u0627\u0644\u0629 (ViewModel & State)",
    "layer_UI_NAV": "4. \u0627\u0644\u0634\u0627\u0634\u0627\u062a \u0648\u0627\u0644\u062a\u0646\u0642\u0644 (UI & Navigation)",
    "layer_RESOURCES_CONFIG": "5. \u0627\u0644\u0645\u0648\u0627\u0631\u062f \u0648\u0625\u0639\u062f\u0627\u062f\u0627\u062a \u0627\u0644\u0645\u0634\u0631\u0648\u0639 (Resources & Config)",
    "layer_TESTS": "6. \u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a \u0627\u0644\u0622\u0644\u064a\u0629 (Automated Tests)",
}

LAYER_DEFINITIONS: tuple[tuple[int, str, str], ...] = (
    (1, "DOMAIN", "1. Domain & Contracts"),
    (2, "DATA", "2. Data, Repository & Persistence"),
    (3, "VIEWMODEL", "3. Presentation State & ViewModel"),
    (4, "UI_NAV", "4. UI, Screens & Navigation"),
    (5, "RESOURCES_CONFIG", "5. Resources, Manifest & Build Config"),
    (6, "TESTS", "6. Automated Tests & Verification Suites"),
)

_HOTSPOT_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "Billing / Auth / Security",
        "\u062f\u0641\u0639 \u0648\u0635\u0644\u0627\u062d\u064a\u0627\u062a \u0648\u0623\u0645\u0627\u0646",
        re.compile(
            r"\b(billing|payment|purchase|subscription|price|token|secret|auth|biometric|PendingIntent|"
            r'exported\s*=\s*"true"|setJavaScriptEnabled|SharedPreferences|EncryptedSharedPreferences)\b',
            re.IGNORECASE,
        ),
    ),
    (
        "Navigation / Intent",
        "\u062a\u0646\u0642\u0644 \u0628\u064a\u0646 \u0627\u0644\u0634\u0627\u0634\u0627\u062a",
        re.compile(
            r"\b(findNavController|navigate\s*\(|popBackStack|Intent\s*\(|startActivity|setResult|"
            r"deepLink|NavHost|composable\s*\(|FragmentTransaction)\b",
        ),
    ),
    (
        "State / Coroutine Flow",
        "\u062a\u062d\u062f\u064a\u062b \u062d\u0627\u0644\u0629 \u0648\u0643\u0648\u0631\u0648\u062a\u064a\u0646",
        re.compile(
            r"\b(MutableStateFlow|MutableSharedFlow|_uiState|_state|update\s*\{|viewModelScope\.launch|"
            r"lifecycleScope\.launch|withContext|CancellationException|collectLatest|repeatOnLifecycle)\b",
        ),
    ),
    (
        "Persistence / Network Contract",
        "\u0639\u0642\u062f \u0634\u0628\u0643\u0629 \u0623\u0648 \u0642\u0627\u0639\u062f\u0629 \u0628\u064a\u0627\u0646\u0627\u062a",
        re.compile(
            r"(@Query|@Insert|@Update|@Delete|@Migration|@GET|@POST|@PUT|@DELETE|@PATCH|@Multipart|"
            r"RoomDatabase|DataStore|fetch[A-Z]\w*|sync[A-Z]\w*)",
        ),
    ),
    (
        "Control-Flow Decision",
        "\u0634\u0631\u0637 \u0648\u0645\u0633\u0627\u0631 \u0642\u0631\u0627\u0631",
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
    s_root = state_root(repo)
    active_file = s_root / "active-task.json"
    if active_file.is_file():
        try:
            active_tid = str(read_json(active_file).get("task_id") or "").strip()
            if active_tid:
                validate_id(active_tid, "task_id")
                return active_tid
        except (OSError, ValueError, KeyError, ValidationError):
            pass
    tasks_root = s_root / "tasks"
    if tasks_root.is_dir():
        candidates: list[tuple[float, str]] = []
        for child in tasks_root.iterdir():
            plan_p = child / "plan.json"
            if child.is_dir() and plan_p.is_file():
                try:
                    candidates.append((plan_p.stat().st_mtime, child.name))
                except OSError:
                    continue
        if candidates:
            candidates.sort(reverse=True)
            validate_id(candidates[0][1], "task_id")
            return candidates[0][1]
    raise ValidationError("No active or recent task found; pass --task-id <id> explicitly.")


def classify_architectural_layer(rel_path: str) -> tuple[int, str, str]:
    norm = rel_path.replace("\\", "/")
    low = norm.lower()
    name = Path(norm).name
    name_low = name.lower()

    if (
        "/src/test/" in low
        or "/src/androidtest/" in low
        or "/src/commontest/" in low
        or low.startswith("test/")
        or name_low.endswith(("test.kt", "tests.kt", "test.java", "spec.kt"))
    ):
        return LAYER_DEFINITIONS[5]

    if (
        low.endswith((".xml", ".gradle", ".gradle.kts", ".toml", ".pro", ".properties", ".json", ".yaml", ".yml"))
        or "/res/" in low
        or name_low == "androidmanifest.xml"
    ):
        if "/res/layout/" in low or "/res/navigation/" in low:
            return LAYER_DEFINITIONS[3]
        return LAYER_DEFINITIONS[4]

    if (
        "/domain/" in low
        or "/usecase" in low
        or "/interactor" in low
        or "/contract" in low
        or (name.endswith(("UseCase.kt", "UseCase.java", "Contract.kt", "Repository.kt")) and "/data/" not in low)
    ):
        return LAYER_DEFINITIONS[0]

    if (
        "/data/" in low
        or "/repository/" in low
        or "/remote/" in low
        or "/local/" in low
        or "/network/" in low
        or "/api/" in low
        or "/dao/" in low
        or "/room/" in low
        or "/database/" in low
        or name.endswith(("RepositoryImpl.kt", "Dao.kt", "Api.kt", "Service.kt", "Dto.kt", "Entity.kt", "Mapper.kt"))
    ):
        return LAYER_DEFINITIONS[1]

    if (
        "viewmodel" in name_low
        or "uistate" in name_low
        or "uievent" in name_low
        or "uiintent" in name_low
        or "sideeffect" in name_low
        or "/viewmodel/" in low
        or "/mvi/" in low
        or name.endswith(("State.kt", "Intent.kt", "Effect.kt", "Reducer.kt"))
    ):
        return LAYER_DEFINITIONS[2]

    if (
        name.endswith(("Fragment.kt", "Activity.kt", "Screen.kt", "Dialog.kt", "BottomSheet.kt", "Adapter.kt", "ViewHolder.kt"))
        or "/ui/" in low
        or "/presentation/" in low
        or "/feature/" in low
        or "/navigation/" in low
        or "/compose/" in low
    ):
        return LAYER_DEFINITIONS[3]

    return LAYER_DEFINITIONS[0]


def _parse_unified_diff(diff_text: str) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    current_path = ""
    current_old_path = ""
    current_hunk: dict[str, Any] | None = None
    old_ln = 0
    new_ln = 0
    hunk_header_re = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$")
    diff_git_re = re.compile(r'^diff --git (?:"a/([^"]+)"|a/(\S+)) (?:"b/([^"]+)"|b/(\S+))$')

    for raw_line in diff_text.splitlines():
        m_git = diff_git_re.match(raw_line)
        if m_git:
            a_p = m_git.group(1) or m_git.group(2) or ""
            b_p = m_git.group(3) or m_git.group(4) or ""
            current_path = b_p or a_p
            current_old_path = a_p if a_p != current_path else ""
            current_hunk = None
            files.setdefault(current_path, {
                "path": current_path,
                "old_path": current_old_path,
                "status": "M",
                "added": 0,
                "deleted": 0,
                "hunks": [],
            })
            continue
        if not current_path:
            continue
        entry = files[current_path]
        if raw_line.startswith("new file mode"):
            entry["status"] = "A"
            continue
        if raw_line.startswith("deleted file mode"):
            entry["status"] = "D"
            continue
        if raw_line.startswith("rename from "):
            entry["status"] = "R"
            entry["old_path"] = raw_line[len("rename from "):].strip()
            continue
        if raw_line.startswith(("index ", "--- ", "+++ ", "similarity index ")):
            continue
        m_hunk = hunk_header_re.match(raw_line)
        if m_hunk:
            old_ln = int(m_hunk.group(1))
            old_cnt = int(m_hunk.group(2) or "1")
            new_ln = int(m_hunk.group(3))
            new_cnt = int(m_hunk.group(4) or "1")
            current_hunk = {
                "header": raw_line,
                "context_label": m_hunk.group(5).strip(),
                "old_start": old_ln,
                "old_count": old_cnt,
                "new_start": new_ln,
                "new_count": new_cnt,
                "lines": [],
                "added": 0,
                "deleted": 0,
            }
            entry["hunks"].append(current_hunk)
            continue
        if current_hunk is None:
            continue
        if raw_line.startswith("+"):
            current_hunk["lines"].append({"kind": "add", "old_ln": None, "new_ln": new_ln, "text": raw_line[1:]})
            current_hunk["added"] += 1
            entry["added"] += 1
            new_ln += 1
        elif raw_line.startswith("-"):
            current_hunk["lines"].append({"kind": "del", "old_ln": old_ln, "new_ln": None, "text": raw_line[1:]})
            current_hunk["deleted"] += 1
            entry["deleted"] += 1
            old_ln += 1
        elif raw_line.startswith(" "):
            current_hunk["lines"].append({"kind": "ctx", "old_ln": old_ln, "new_ln": new_ln, "text": raw_line[1:]})
            old_ln += 1
            new_ln += 1
    return files


def _summarize_lines_bilingual(
    rel_path: str,
    layer_key: str,
    status: str,
    add_lines: list[str],
    del_lines: list[str],
    context_label: str = "",
) -> tuple[str, str]:
    """Synthesize a concise plain-language (English, Arabic) summary of WHY these lines changed."""
    low = rel_path.lower()
    stem = Path(rel_path).stem

    if status == "A":
        if layer_key == "TESTS":
            return (
                f"Added new test suite `{stem}` to verify behavior and prevent regressions.",
                f"\u0625\u0636\u0627\u0641\u0629 \u0645\u0644\u0641 \u0627\u062e\u062a\u0628\u0627\u0631 \u062c\u062f\u064a\u062f `{stem}` \u0644\u0644\u062a\u062d\u0642\u0642 \u0645\u0646 \u0627\u0644\u0633\u0644\u0648\u0643 \u0648\u0645\u0646\u0639 \u0627\u0644\u0627\u0646\u062d\u062f\u0627\u0631.",
            )
        return (
            f"Created `{stem}` to support the new task flow.",
            f"\u0625\u0646\u0634\u0627\u0621 `{stem}` \u0644\u062f\u0639\u0645 \u0627\u0644\u0645\u0633\u0627\u0631 \u0627\u0644\u062c\u062f\u064a\u062f \u0641\u064a \u0627\u0644\u0645\u0647\u0645\u0629.",
        )
    if status == "D":
        return (
            f"Removed obsolete file `{stem}` (`-{len(del_lines)}` lines).",
            f"\u062d\u0630\u0641 \u0627\u0644\u0645\u0644\u0641 \u063a\u064a\u0631 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 `{stem}` (\u062a\u0646\u0638\u064a\u0641 {len(del_lines)} \u0633\u0637\u0631).",
        )

    changed_all = add_lines + del_lines
    if changed_all and all(_IMPORT_OR_PKG_RE.match(t) for t in changed_all):
        return (
            "Cleaned up imports and package headers only (no runtime logic change).",
            "\u062a\u0646\u0638\u064a\u0641 \u062c\u0645\u0644 \u0627\u0644\u0627\u0633\u062a\u064a\u0631\u0627\u062f (imports) \u0641\u0642\u0637 \u0628\u062f\u0648\u0646 \u0623\u064a \u062a\u063a\u064a\u064a\u0631 \u0641\u064a \u0645\u0646\u0637\u0642 \u0627\u0644\u062a\u0634\u063a\u064a\u0644.",
        )

    # Extract primary touched symbol name
    touched_sym = ""
    for line in [context_label, *add_lines, *del_lines]:
        m = _DECL_SYMBOL_RE.match(line)
        if m:
            touched_sym = m.group(1)
            break
    sym_en = f" in `{touched_sym}`" if touched_sym else ""
    sym_ar = f" \u0641\u064a `{touched_sym}`" if touched_sym else ""

    if low.endswith(".xml") and "strings" in Path(low).name:
        keys: list[str] = []
        for l in add_lines + del_lines:
            mk = _STRING_RES_NAME_RE.search(l)
            if mk and mk.group(1) not in keys:
                keys.append(mk.group(1))
        k_desc = (", ".join(f"`{k}`" for k in keys[:3])) if keys else "UI copy"
        return (
            f"Updated localized string resource(s): {k_desc}.",
            f"\u062a\u062d\u062f\u064a\u062b \u0646\u0635\u0648\u0635 \u0627\u0644\u0648\u0627\u062c\u0647\u0629 \u0641\u064a \u0645\u0644\u0641 \u0627\u0644\u0645\u0648\u0627\u0631\u062f: {k_desc}.",
        )

    if layer_key == "TESTS":
        return (
            f"Updated unit test assertions{sym_en} to cover the modified behavior.",
            f"\u062a\u062d\u062f\u064a\u062b \u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a \u0627\u0644\u062a\u062d\u0642\u0642{sym_ar} \u0644\u062a\u063a\u0637\u064a\u0629 \u0627\u0644\u0633\u0644\u0648\u0643 \u0627\u0644\u0645\u0639\u062f\u0651\u064e\u0644.",
        )

    joined_add = "\n".join(add_lines)
    joined_del = "\n".join(del_lines)

    parts_en: list[str] = []
    parts_ar: list[str] = []

    if any(("fun " in l and "=" in l and "(" in l) for l in add_lines):
        parts_en.append(f"Adjusted function signature / default parameter{sym_en}")
        parts_ar.append(f"\u062a\u0639\u062f\u064a\u0644 \u062a\u0648\u0642\u064a\u0639 \u0627\u0644\u062f\u0627\u0644\u0629 \u0623\u0648 \u0642\u064a\u0645\u062a\u0647\u0627 \u0627\u0644\u0627\u0641\u062a\u0631\u0627\u0636\u064a\u0629{sym_ar}")

    if re.search(r"\bif\s*\([^)]*\)\s*return\b|IllegalArgumentException|Result\.failure", joined_add):
        parts_en.append("added early validation/guard check")
        parts_ar.append("\u0625\u0636\u0627\u0641\u0629 \u0634\u0631\u0637 \u062d\u0645\u0627\u064a\u0629 \u0648\u062a\u062d\u0642\u0642 \u0645\u0628\u0643\u0631 \u0644\u0644\u0645\u062f\u062e\u0644\u0627\u062a")
    elif re.search(r"\bif\s*\(|\bwhen\s*\(", joined_add) and not re.search(r"\bif\s*\(|\bwhen\s*\(", joined_del):
        parts_en.append("wrapped execution in a conditional guard")
        parts_ar.append("\u0625\u062d\u0627\u0637\u0629 \u0627\u0644\u0627\u0633\u062a\u062f\u0639\u0627\u0621 \u0628\u0634\u0631\u0637 \u062a\u062d\u0643\u0645 \u0644\u0645\u0646\u0639 \u0627\u0644\u062a\u0646\u0641\u064a\u0630 \u063a\u064a\u0631 \u0627\u0644\u0645\u0637\u0644\u0648\u0628")

    if re.search(r"MutableStateFlow|MutableSharedFlow|_uiState|viewModelScope\.launch|lifecycleScope\.launch", joined_add):
        parts_en.append(f"wired coroutine / UI state flow{sym_en}")
        parts_ar.append(f"\u062a\u062d\u062f\u064a\u062b \u062a\u062f\u0641\u0642 \u0627\u0644\u062d\u0627\u0644\u0629 \u0648\u0625\u0637\u0644\u0627\u0642 \u0627\u0644\u0643\u0648\u0631\u0648\u062a\u064a\u0646{sym_ar}")

    if re.search(r"findNavController|navigate\s*\(|Intent\s*\(|startActivity", joined_add):
        parts_en.append(f"updated screen navigation trigger{sym_en}")
        parts_ar.append(f"\u0631\u0628\u0637 \u0627\u0644\u0627\u0646\u062a\u0642\u0627\u0644 \u0628\u064a\u0646 \u0627\u0644\u0634\u0627\u0634\u0627\u062a{sym_ar}")

    if re.search(r"billing|payment|purchase|price|token|PendingIntent", joined_add, re.I):
        parts_en.append("updated sensitive billing/security logic")
        parts_ar.append("\u062a\u0639\u062f\u064a\u0644 \u0645\u0646\u0637\u0642 \u062d\u0633\u0627\u0633 \u0645\u0631\u062a\u0628\u0637 \u0628\u0627\u0644\u062f\u0641\u0639 \u0623\u0648 \u0627\u0644\u0623\u0645\u0627\u0646")

    if not parts_en:
        if len(del_lines) > len(add_lines) * 2 and len(del_lines) >= 3:
            parts_en.append(f"Removed unused/redundant code (`-{len(del_lines)}` lines){sym_en}")
            parts_ar.append(f"\u062d\u0630\u0641 \u0643\u0648\u062f \u0632\u0627\u0626\u062f \u0623\u0648 \u063a\u064a\u0631 \u0645\u0633\u062a\u062e\u062f\u0645 ({len(del_lines)} \u0633\u0637\u0631){sym_ar}")
        else:
            parts_en.append(f"Updated implementation logic{sym_en} (`+{len(add_lines)}/-{len(del_lines)}`)")
            parts_ar.append(f"\u062a\u062d\u062f\u064a\u062b \u0645\u0646\u0637\u0642 \u0627\u0644\u062a\u0646\u0641\u064a\u0630{sym_ar} (+{len(add_lines)}/-{len(del_lines)})")

    en_sentence = "; ".join(parts_en)
    en_sentence = en_sentence[0].upper() + en_sentence[1:] + "."
    ar_sentence = " \u060c \u0645\u0639 ".join(parts_ar) + "."
    return en_sentence, ar_sentence


def _classify_hunk_and_file_triage(
    rel_path: str,
    layer_key: str,
    status: str,
    hunks: list[dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    """Return (`HOTSPOT` | `STANDARD` | `AUTO_COLLAPSED`, reasons_en, reasons_ar)."""
    low = rel_path.lower()
    for hk in hunks:
        hk_add = [str(l["text"]) for l in (hk.get("lines") or []) if l["kind"] == "add"]
        hk_del = [str(l["text"]) for l in (hk.get("lines") or []) if l["kind"] == "del"]
        hk_en, hk_ar = _summarize_lines_bilingual(
            rel_path, layer_key, status, hk_add, hk_del, str(hk.get("context_label") or "")
        )
        hk["summary_en"] = hk_en
        hk["summary_ar"] = hk_ar

    if layer_key == "TESTS":
        return "AUTO_COLLAPSED", ["Automated test file"], ["\u0645\u0644\u0641 \u0627\u062e\u062a\u0628\u0627\u0631 \u0622\u0644\u064a"]
    if low.endswith(".xml") and "/res/values" in low and "strings" in Path(low).name:
        return "AUTO_COLLAPSED", ["Localization strings resource"], ["\u0645\u0644\u0641 \u0646\u0635\u0648\u0635 \u0648\u062a\u0631\u062c\u0645\u0627\u062a"]

    changed_lines = [
        str(ln["text"])
        for hk in hunks
        for ln in (hk.get("lines") or [])
        if ln["kind"] in ("add", "del")
    ]
    if changed_lines and all(_IMPORT_OR_PKG_RE.match(t) for t in changed_lines):
        return "AUTO_COLLAPSED", ["Imports & comments only"], ["\u0627\u0633\u062a\u064a\u0631\u0627\u062f\u0627\u062a \u0648\u062a\u0639\u0644\u064a\u0642\u0627\u062a \u0641\u0642\u0637"]

    reasons_en: list[str] = []
    reasons_ar: list[str] = []
    for hk in hunks:
        hk_en_list: list[str] = []
        hk_ar_list: list[str] = []
        for ln in hk.get("lines") or []:
            if ln["kind"] not in ("add", "del"):
                continue
            txt = str(ln["text"])
            for label_en, label_ar, rx in _HOTSPOT_PATTERNS:
                if rx.search(txt) and label_en not in hk_en_list:
                    hk_en_list.append(label_en)
                    hk_ar_list.append(label_ar)
            m_decl = _DECL_SYMBOL_RE.match(txt)
            if m_decl and "=" in txt and "(" in txt and "Default-Arg Signature" not in hk_en_list:
                hk_en_list.append("Default-Arg Signature")
                hk_ar_list.append("\u062a\u063a\u064a\u064a\u0631 \u0645\u0639\u0627\u0645\u0644 \u0627\u0641\u062a\u0631\u0627\u0636\u064a")
        hk["hotspot_reasons_en"] = hk_en_list
        hk["hotspot_reasons_ar"] = hk_ar_list
        for r_e, r_a in zip(hk_en_list, hk_ar_list):
            if r_e not in reasons_en:
                reasons_en.append(r_e)
                reasons_ar.append(r_a)

    if reasons_en:
        return "HOTSPOT", reasons_en, reasons_ar
    return "STANDARD", ["Core implementation update"], ["\u062a\u062d\u062f\u064a\u062b \u0645\u0646\u0637\u0642 \u0623\u0633\u0627\u0633\u064a"]


def _extract_modified_symbols(parsed_files: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    seen: set[str] = set()
    skip_names = {
        "if", "when", "for", "while", "return", "override", "invoke", "equals",
        "hashCode", "toString", "copy", "onCreate", "onViewCreated", "onDestroyView",
        "onResume", "onPause", "onStart", "onStop", "init", "build", "create",
    }
    for rel_path, fdata in parsed_files.items():
        _layer_idx, layer_key, _ = classify_architectural_layer(rel_path)
        if layer_key == "TESTS":
            continue
        stem = Path(rel_path).stem
        if stem and len(stem) >= 4 and stem[0].isupper() and stem not in seen and not stem.endswith("Test"):
            seen.add(stem)
            symbols.append({
                "symbol": stem,
                "defined_in": rel_path,
                "has_default_arg": any(
                    "=" in str(l["text"]) and "fun " in str(l["text"])
                    for hk in (fdata.get("hunks") or [])
                    for l in (hk.get("lines") or [])
                    if l["kind"] in ("add", "del")
                ),
                "kind": "type",
            })
        for hk in fdata.get("hunks") or []:
            ctx = str(hk.get("context_label") or "")
            for candidate_line in [ctx, *[str(l["text"]) for l in (hk.get("lines") or []) if l["kind"] in ("add", "del")]]:
                m = _DECL_SYMBOL_RE.match(candidate_line)
                if not m:
                    continue
                sym = m.group(1)
                if len(sym) < 4 or sym in skip_names or sym in seen:
                    continue
                seen.add(sym)
                symbols.append({
                    "symbol": sym,
                    "defined_in": rel_path,
                    "has_default_arg": ("=" in candidate_line and "(" in candidate_line),
                    "kind": "callable" if "fun " in candidate_line else "type",
                })
    return symbols[:24]


def _discover_unmodified_blast_radius_callers(
    repo: Path,
    touched_paths: set[str],
    modified_symbols: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    callers: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, int, str]] = set()
    norm_touched = {p.replace("\\", "/") for p in touched_paths}

    graph_candidate_files: list[str] = []
    try:
        from _graph_core import GraphEngine
        g_engine = GraphEngine(repo)
        g_engine.sync()
        for t_path in sorted(norm_touched):
            t_low = t_path.lower()
            for _nid, node in g_engine.graph.nodes.items():
                if node.file_path and node.file_path.replace("\\", "/").lower() == t_low:
                    for src_id in g_engine.graph.get_sources(node.id):
                        snode = g_engine.graph.nodes.get(src_id)
                        if snode and snode.file_path:
                            sf = snode.file_path.replace("\\", "/")
                            if sf not in norm_touched and sf not in graph_candidate_files:
                                graph_candidate_files.append(sf)
    except (ImportError, OSError, ValueError, RuntimeError, ValidationError):
        pass

    if not modified_symbols:
        return callers

    sym_map = {item["symbol"]: item for item in modified_symbols}
    escaped = "|".join(re.escape(s) for s in sym_map)
    sym_re = re.compile(rf"\b({escaped})\b")

    scan_paths: list[Path] = []
    visited_rels: set[str] = set()
    for gf in graph_candidate_files:
        gp = repo / gf
        if gp.is_file():
            scan_paths.append(gp)
            visited_rels.add(gf)

    excluded_dirs = {".git", ".agents", ".gradle", ".idea", "build", "out", "node_modules", "__pycache__", ".harness-setup"}
    budget = 600
    for root_dir, dirs, filenames in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        for fn in filenames:
            if not fn.endswith((".kt", ".java", ".xml")):
                continue
            full_p = Path(root_dir) / fn
            try:
                rel_p = full_p.relative_to(repo).as_posix()
            except ValueError:
                continue
            if rel_p in norm_touched or rel_p in visited_rels:
                continue
            if "/src/test/" in rel_p.lower() or "/src/androidtest/" in rel_p.lower():
                continue
            scan_paths.append(full_p)
            visited_rels.add(rel_p)
            budget -= 1
            if budget <= 0:
                break
        if budget <= 0:
            break

    for sp in scan_paths:
        try:
            rel_p = sp.relative_to(repo).as_posix()
            lines = sp.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, 1):
            if line.lstrip().startswith(("import ", "package ", "//", "*")):
                continue
            m = sym_re.search(line)
            if not m:
                continue
            sym_name = m.group(1)
            meta = sym_map[sym_name]
            key = (rel_p, idx, sym_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            callers.append({
                "caller_file": rel_p,
                "line": idx,
                "symbol": sym_name,
                "defined_in": meta["defined_in"],
                "has_default_arg": bool(meta.get("has_default_arg")),
                "from_project_graph": rel_p in graph_candidate_files,
                "snippet": line.strip()[:160],
            })
            if len(callers) >= 30:
                return callers
    return callers


def _collect_verified_gates(repo: Path, task_directory: Path, plan: dict[str, Any]) -> list[dict[str, str]]:
    gates: list[dict[str, str]] = []
    seen: set[str] = set()
    run_id = str(plan.get("ready_run_id") or plan.get("verification_run_id") or "")
    snap_sha = str(plan.get("ready_delivery_snapshot_sha256") or "")
    current_p = task_directory / "current-run.json"
    if current_p.is_file():
        try:
            cur = read_json(current_p)
            run_id = run_id or str(cur.get("run_id") or "")
            snap_sha = snap_sha or str(cur.get("delivery_snapshot_sha256") or "")
        except (OSError, ValueError, ValidationError):
            pass

    if snap_sha and run_id:
        try:
            from evidence_store import EvidenceStore
            store = EvidenceStore(state_root(repo))
            for gname in ("preflight", "unit_tests", "localization", "room", "roborazzi_ui", "maestro_e2e"):
                try:
                    rec = store.read(snap_sha, run_id, gname)
                except (OSError, ValueError, KeyError, ValidationError):
                    continue
                if isinstance(rec, dict) and str(rec.get("status") or "") == "PASS":
                    gates.append({"gate": gname, "status": "PASS"})
                    seen.add(gname)
        except (ImportError, OSError, ValueError, ValidationError):
            pass

    for fname, g_label in (
        ("compile-evidence.json", "compile"),
        ("preflight-evidence.json", "preflight"),
        ("test-evidence.json", "unit_tests"),
        ("localization-evidence.json", "check_strings"),
    ):
        fp = task_directory / fname
        if g_label not in seen and fp.is_file():
            try:
                doc = read_json(fp)
                st = str(doc.get("status") or ("PASS" if doc.get("passed") or doc.get("returncode") == 0 else ""))
                if st == "PASS":
                    gates.append({"gate": g_label, "status": "PASS"})
                    seen.add(g_label)
            except (OSError, ValueError, ValidationError):
                continue
    return gates


def _collect_ai_review_xray(task_directory: Path) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = []
    findings_by_file: dict[str, list[dict[str, Any]]] = {}
    all_findings: list[dict[str, Any]] = []

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
                rec = {
                    "round": round_idx,
                    "run_id": rdir.name,
                    "reviewer": reviewer,
                    "severity": sev,
                    "title": str(f_item.get("title") or f_item.get("id") or "Review observation"),
                    "message": str(f_item.get("description") or f_item.get("message") or f_item.get("remediation") or "")[:360],
                    "file": f_path,
                    "line": int(f_item.get("line") or 0) if str(f_item.get("line") or "").isdigit() else 0,
                    "state": "RESOLVED_IN_LATER_ROUND" if resolved_later else ("ADVISORY" if sev in ("LOW", "INFO") else "ACTIVE"),
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

    outcome_txt = str(plan.get("outcome") or plan.get("desired_outcome") or plan.get("goal") or "")
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
            "title": outcome_txt or task_directory.name,
            "expected_files": sorted(current_expected),
            "touched_files": matched,
            "added": sum(int(parsed_files[p].get("added") or 0) for p in matched),
            "deleted": sum(int(parsed_files[p].get("deleted") or 0) for p in matched),
        })

    return {
        "outcome": outcome_txt,
        "kind": str(plan.get("kind") or "FEATURE"),
        "status": str(plan.get("status") or "UNKNOWN"),
        "initial_expected_count": len(initial_expected),
        "current_expected_count": len(current_expected),
        "phases": phases_trace,
        "file_to_phase": file_to_phase,
        "side_effect_files": side_effect_files,
    }


def _enrich_file_rationale(
    fobj: dict[str, Any],
    traceability: dict[str, Any],
    file_findings: list[dict[str, Any]],
    side_effect_set: set[str],
) -> tuple[str, str]:
    rel_p = fobj["path"]
    all_add = [str(l["text"]) for hk in (fobj.get("hunks") or []) for l in (hk.get("lines") or []) if l["kind"] == "add"]
    all_del = [str(l["text"]) for hk in (fobj.get("hunks") or []) for l in (hk.get("lines") or []) if l["kind"] == "del"]
    core_en, core_ar = _summarize_lines_bilingual(
        rel_p, fobj["layer_key"], fobj.get("status", "M"), all_add, all_del
    )

    ph_info = traceability["file_to_phase"].get(rel_p)
    if rel_p in side_effect_set:
        scope_en = "[Side-effect outside initial plan] "
        scope_ar = "[\u062a\u0639\u062f\u064a\u0644 \u062c\u0627\u0646\u0628\u064a \u062e\u0627\u0631\u062c \u0627\u0644\u062e\u0637\u0629 \u0627\u0644\u0623\u0648\u0644\u0649] "
    elif ph_info:
        scope_en = f"[Phase {ph_info[0]}: {ph_info[1]}] "
        scope_ar = f"[\u0627\u0644\u0645\u0631\u062d\u0644\u0629 {ph_info[0]}: {ph_info[1]}] "
    else:
        scope_en = "[Approved Plan Scope] "
        scope_ar = "[\u0636\u0645\u0646 \u0646\u0637\u0627\u0642 \u0627\u0644\u062e\u0637\u0629 \u0627\u0644\u0645\u0639\u062a\u0645\u062f\u0629] "

    resolved_r1 = [ff for ff in file_findings if ff.get("state") == "RESOLVED_IN_LATER_ROUND"]
    fix_en = f" Also resolved Round {resolved_r1[0]['round']} review finding." if resolved_r1 else ""
    fix_ar = (
        f" (\u0648\u064a\u0639\u0627\u0644\u062c \u0645\u0644\u0627\u062d\u0638\u0629 \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629 \u0645\u0646 \u0627\u0644\u062c\u0648\u0644\u0629 {resolved_r1[0]['round']})."
        if resolved_r1
        else ""
    )
    return scope_en + core_en + fix_en, scope_ar + core_ar + fix_ar


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
    generated_at: str,
) -> str:
    esc = html.escape
    total_added = sum(int(f["added"]) for f in ordered_files)
    total_deleted = sum(int(f["deleted"]) for f in ordered_files)
    hotspot_count = sum(1 for f in ordered_files if f["triage"] == "HOTSPOT")
    collapsed_count = sum(1 for f in ordered_files if f["triage"] == "AUTO_COLLAPSED")
    side_effects = traceability["side_effect_files"]
    side_effect_set = {item["path"] for item in side_effects}

    gate_labels_ar = {
        "compile": "\u0627\u0644\u062a\u0631\u062c\u0645\u0629 PASS",
        "preflight": "\u0641\u062d\u0635 \u0627\u0644\u0643\u0648\u062f PASS",
        "unit_tests": "\u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a PASS",
        "localization": "\u0627\u0644\u062a\u0631\u062c\u0645\u0627\u062a PASS",
        "check_strings": "\u0627\u0644\u0646\u0635\u0648\u0635 PASS",
        "roborazzi_ui": "Roborazzi UI PASS",
        "maestro_e2e": "Maestro E2E PASS",
    }
    gate_badges_html = "".join(
        f'<span class="pill pill-pass">&#10003; '
        + _i18n_span(f'{g["gate"]} PASS', gate_labels_ar.get(g["gate"], f'{g["gate"]} PASS'))
        + "</span>"
        for g in gates
    ) or ('<span class="pill pill-neutral">' + _i18n_span("Local Snapshot", "\u0646\u0633\u062e\u0629 \u0645\u062d\u0644\u064a\u0629") + "</span>")

    phase_rows_html: list[str] = []
    for ph in traceability["phases"]:
        files_links = " ".join(
            f'<a href="#file-{idx}" class="chip-link ltr-code">{esc(Path(p).name)}</a>'
            for idx, f in enumerate(ordered_files)
            for p in [f["path"]]
            if p in ph["touched_files"]
        ) or '<span class="muted">-</span>'
        phase_rows_html.append(
            f'<div class="trace-row">'
            f'<div class="trace-title"><span class="pill pill-neutral ltr-code">{esc(ph["id"])}</span> {esc(ph["title"])}</div>'
            f'<div class="trace-files"><span class="ltr-code delta-inline">+{ph["added"]} / -{ph["deleted"]}</span> {files_links}</div>'
            f'</div>'
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
        # Keep exact English substring in data-en so selftest substring assertions always match
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
        blast_html = (
            '<details class="panel-card" id="blast-radius-panel" open>'
            '<summary class="panel-summary">'
            '<span>&#128225; '
            + _i18n_span(
                f"Unmodified Blast-Radius Callers ({len(blast_callers)})",
                f"{AR_STRINGS['blast_title']} ({len(blast_callers)})",
            )
            + '</span></summary>'
            '<div class="table-wrap"><table class="ag-table">'
            '<thead><tr>'
            '<th>' + _i18n_span("Modified Symbol", AR_STRINGS["col_symbol"]) + '</th>'
            '<th>' + _i18n_span("Unmodified Caller", AR_STRINGS["col_caller"]) + '</th>'
            '<th>' + _i18n_span("Call-Site Excerpt", AR_STRINGS["col_snippet"]) + '</th>'
            '<th>' + _i18n_span("IDE", AR_STRINGS["col_action"]) + '</th>'
            f'</tr></thead><tbody>{"".join(caller_rows_list)}</tbody></table></div></details>'
        )
    else:
        blast_html = (
            '<div class="panel-card panel-slim" id="blast-radius-panel">'
            '&#128225; '
            + _i18n_span("Unmodified Blast-Radius Callers (0)", AR_STRINGS["blast_empty"])
            + "</div>"
        )

    xray_rounds = xray["rounds"]
    xray_findings = xray["all_findings"]
    if xray_rounds or xray_findings:
        r_pills = " ".join(
            f'<span class="pill pill-info ltr-code">R{r["round"]}: '
            + ", ".join(f'{esc(v["reviewer"])}={esc(v["verdict"])}' for v in r["verdicts"])
            + "</span>"
            for r in xray_rounds
        )
        f_items_list: list[str] = []
        for f in xray_findings[:20]:
            is_res = f["state"] == "RESOLVED_IN_LATER_ROUND"
            p_cls = "pill-pass" if is_res else "pill-warn"
            st_ar = (
                AR_STRINGS["badge_resolved"]
                if is_res
                else (AR_STRINGS["badge_advisory"] if f["state"] == "ADVISORY" else AR_STRINGS["badge_active"])
            )
            loc_str = f":{f['line']}" if f["line"] else ""
            file_tag_html = f'<code class="ltr-code">{esc(f["file"])}{loc_str}</code> ' if f["file"] else ""
            f_items_list.append(
                f'<li><span class="pill {p_cls}">'
                + _i18n_span(f'{f["severity"]} - R{f["round"]} ({f["state"]})', f'R{f["round"]} {f["severity"]} - {st_ar}')
                + f'</span> <strong>{esc(f["title"])}</strong> {file_tag_html}&mdash; {esc(f["message"])}</li>'
            )
        xray_html = (
            '<details class="panel-card" id="xray-panel" open>'
            '<summary class="panel-summary">'
            '<span>&#128300; '
            + _i18n_span(
                f"AI Review X-Ray ({len(xray_rounds)} round(s), {len(xray_findings)} finding(s))",
                f"{AR_STRINGS['xray_title']} ({len(xray_rounds)} \u062c\u0648\u0644\u0627\u062a)",
            )
            + f'</span><span class="rounds-wrap">{r_pills}</span></summary>'
            + (f'<ul class="clean-list">{"".join(f_items_list)}</ul>' if f_items_list else "")
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

        why_en, why_ar = _enrich_file_rationale(fobj, traceability, file_findings, side_effect_set)
        fobj["why_en"] = why_en
        fobj["why_ar"] = why_ar

        pill_cls = (
            "pill-hotspot" if triage == "HOTSPOT"
            else ("pill-neutral" if triage == "AUTO_COLLAPSED" else "pill-info")
        )
        triage_en = "HOTSPOT" if triage == "HOTSPOT" else ("AUTO-COLLAPSED" if triage == "AUTO_COLLAPSED" else "CORE DIFF")
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

        reasons_en_str = ", ".join(fobj.get("triage_reasons") or [])
        reasons_ar_str = " \u060c ".join(fobj.get("triage_reasons_ar") or [])
        open_attr = "" if triage == "AUTO_COLLAPSED" else " open"

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
                    + _i18n_span(f'R{ff["round"]} {ff["severity"]} ({ff["state"]})', f'R{ff["round"]} {ff["severity"]} ({st_ar})')
                    + f'</span> <strong>{esc(ff["title"])}:</strong> {esc(ff["message"])}</div>'
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
                    f'<td class="act-col"><button type="button" class="line-note-btn" title="Add surgical note" '
                    f'onclick="toggleNoteBox(\'{note_id}\', \'{esc(rel_p)}\', {target_ln})">+</button></td>'
                    f'<td class="code-col"><pre>{prefix}{esc(ln_obj["text"])}</pre></td>'
                    f'</tr>'
                )
            hunks_html_parts.append(
                f'<div class="hunk-block">'
                f'<div class="hunk-bar">'
                f'<div class="hunk-bar-main">'
                f'<code class="hunk-hdr ltr-code">{esc(hk["header"])}</code> {hk_badge}'
                f'<span class="hunk-why">' + _i18n_span(hk_sum_en, hk_sum_ar) + '</span>'
                f'</div>'
                f'<div class="hunk-actions">'
                f'<a class="btn-sm" href="{esc(hk_ide)}">IDE :{first_ln}</a>'
                f'<button type="button" class="btn-sm" onclick="copyPathLine(\'{esc(rel_p)}:{first_ln}\', this)">'
                + _i18n_span("Copy", AR_STRINGS["copy_path"])
                + '</button>'
                f'<button type="button" class="btn-sm btn-accent-outline" onclick="toggleNoteBox(\'f{idx}_h{h_idx}\', \'{esc(rel_p)}\', {first_ln})">'
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
                f'<div class="muted pad-14">Binary or metadata-only task change ({esc(fobj.get("status", "M"))}).</div>'
            )

        side_badge = (
            '<span class="pill pill-warn">'
            + _i18n_span("SIDE-EFFECT", AR_STRINGS["badge_side_effect"])
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
            f'<div class="file-summary-left">'
            f'<span class="pill {pill_cls}">' + _i18n_span(triage_en, triage_ar) + f'</span> {side_badge}'
            f'<span class="file-path ltr-code"><span class="file-dir">{esc(dir_prefix)}</span><strong>{esc(Path(rel_p).name)}</strong></span>'
            f'<span class="triage-tags">' + _i18n_span(reasons_en_str, reasons_ar_str) + '</span>'
            f'</div>'
            f'<div class="file-summary-right">'
            f'<span class="ltr-code"><span class="delta-add">+{fobj["added"]}</span> <span class="delta-del">-{fobj["deleted"]}</span></span>'
            f'<button type="button" class="btn-sm btn-check" id="rev-btn-{idx}" onclick="event.stopPropagation(); toggleReviewed({idx})">'
            f'&#10003; ' + _i18n_span("Reviewed", AR_STRINGS["mark_reviewed"]) + '</button>'
            f'<a class="btn-sm" href="{esc(_ide_uri(repo, rel_p, 1))}" onclick="event.stopPropagation()">'
            + _i18n_span("Open IDE", AR_STRINGS["open_ide"])
            + '</a>'
            f'</div>'
            f'</summary>'
            f'<div class="why-banner">'
            f'<span class="why-icon">&#128161;</span> '
            f'<strong>' + _i18n_span("Why changed:", AR_STRINGS["why_label"]) + '</strong> '
            + _i18n_span(why_en, why_ar)
            + '</div>'
            f'{file_xray_html}'
            f'<div class="file-body">{"".join(hunks_html_parts)}</div>'
            f'</details>'
        )

    task_status = traceability["status"]
    reopen_cmd = f"python .agents/harness.py task resume --repo . --task-id {task_id} --reopen"
    i18n_js_json = json.dumps(AR_STRINGS, ensure_ascii=True)

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review Cockpit &mdash; {esc(task_id)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #090b0e;
  --surface: #101319;
  --surface-2: #161b23;
  --surface-3: #1d2430;
  --border: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.15);
  --text: #f3f5f9;
  --text-soft: #b2bccb;
  --muted: #768295;
  --accent: #5b9bff;
  --accent-bg: rgba(91, 155, 255, 0.13);
  --why-bg: rgba(91, 155, 255, 0.07);
  --why-border: rgba(91, 155, 255, 0.28);
  --add-bg: rgba(46, 160, 67, 0.14);
  --add-bar: #3fb950;
  --add-tx: #85e89d;
  --del-bg: rgba(248, 81, 73, 0.13);
  --del-bar: #f85149;
  --del-tx: #ffab9e;
  --hot-bg: rgba(255, 110, 100, 0.14);
  --hot-tx: #ff9992;
  --warn-bg: rgba(245, 165, 36, 0.13);
  --warn-tx: #ffd175;
  --pass-bg: rgba(46, 160, 67, 0.15);
  --pass-tx: #7ee787;
  --font-sans: 'IBM Plex Sans Arabic', 'Inter', 'Segoe UI', Tahoma, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Cascadia Code', Consolas, ui-monospace, monospace;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: var(--font-sans);
  font-size: 14.5px;
  background: var(--bg);
  color: var(--text);
  line-height: 1.65;
  padding-bottom: 94px;
  -webkit-font-smoothing: antialiased;
}}
.ltr-code, code, pre, .diff-table {{
  direction: ltr !important;
  unicode-bidi: isolate;
  font-family: var(--font-mono);
}}
a {{ color: var(--accent); text-decoration: none; }}
.topbar {{
  position: sticky; top: 0; z-index: 40;
  background: rgba(9, 11, 14, 0.90);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
  padding: 12px 22px;
  display: flex; flex-wrap: wrap; gap: 14px; align-items: center; justify-content: space-between;
}}
.brand-row {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
.brand-dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 12px var(--accent); }}
.brand-title {{ margin: 0; font-size: 17px; font-weight: 700; letter-spacing: -0.01em; }}
.subtitle {{ font-size: 12.5px; color: var(--muted); display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 2px; }}
.toolbar {{ display: flex; gap: 7px; flex-wrap: wrap; align-items: center; }}
.btn, .btn-sm {{
  font-family: var(--font-sans);
  background: var(--surface-2);
  color: var(--text-soft);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex; align-items: center; gap: 5px;
  transition: all 0.15s ease;
}}
.btn:hover, .btn-sm:hover {{ background: var(--surface-3); color: var(--text); border-color: var(--border-strong); }}
.btn.active {{ background: var(--accent-bg); border-color: rgba(91, 155, 255, 0.5); color: #9ec5ff; font-weight: 600; }}
.btn-lang {{ background: #1a2232; border-color: rgba(91, 155, 255, 0.45); color: #b8d4ff; font-weight: 700; }}
.btn-primary {{ background: #238636; border-color: #2ea043; color: #fff; font-weight: 600; }}
.btn-primary:hover {{ background: #2ea043; color: #fff; }}
.btn-sm {{ padding: 3px 9px; font-size: 12px; border-radius: 6px; }}
.btn-accent-outline {{ border-color: rgba(91, 155, 255, 0.35); color: #9ec5ff; }}
.btn-check.reviewed {{ background: var(--pass-bg); border-color: rgba(63, 185, 80, 0.5); color: var(--pass-tx); font-weight: 600; }}

.layout {{
  display: grid;
  grid-template-columns: 265px minmax(0, 1fr);
  gap: 20px;
  max-width: 1680px;
  margin: 0 auto;
  padding: 18px 22px;
}}
@media (max-width: 1040px) {{
  .layout {{ grid-template-columns: 1fr; }}
  .sidebar {{ position: static !important; max-height: none !important; }}
}}
.sidebar {{
  position: sticky; top: 76px; align-self: start;
  max-height: calc(100vh - 165px); overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
}}
.sidebar-hdr {{ font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }}
.toc-group {{ font-size: 11.5px; font-weight: 700; color: var(--accent); margin: 14px 0 6px; }}
.toc-group:first-child {{ margin-top: 2px; }}
.toc-item {{
  display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 6px 9px; border-radius: 7px; font-size: 12.5px; color: var(--text-soft); margin-bottom: 3px;
  border-inline-start: 3px solid transparent;
}}
.toc-item:hover {{ background: var(--surface-2); color: var(--text); }}
.toc-hotspot {{ border-inline-start-color: #f85149; }}
.toc-item.done-item {{ opacity: 0.55; border-inline-start-color: #3fb950; }}
.toc-name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.toc-delta {{ font-size: 11px; color: var(--muted); flex-shrink: 0; }}

.overview-grid {{ display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px; margin-bottom: 14px; }}
@media (max-width: 860px) {{ .overview-grid {{ grid-template-columns: 1fr; }} }}
.panel-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 18px;
  margin-bottom: 14px;
}}
.panel-slim {{ padding: 11px 18px; color: var(--muted); font-size: 13.5px; }}
.panel-summary {{ cursor: pointer; font-weight: 700; font-size: 14.5px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }}
.goal-text {{ font-size: 15px; font-weight: 500; color: var(--text); margin: 6px 0 10px; }}
.gates-row {{ display: flex; gap: 6px; flex-wrap: wrap; }}
.trace-row {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; padding: 7px 0; border-top: 1px solid var(--border); font-size: 13.5px; }}
.trace-files {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
.chip-link {{ background: var(--surface-2); border: 1px solid var(--border); padding: 2px 8px; border-radius: 6px; font-size: 12px; color: var(--text-soft); }}
.chip-link:hover {{ border-color: var(--accent); color: var(--text); }}
.delta-inline {{ font-size: 12px; color: var(--muted); }}

.alert-card {{
  border-radius: 12px; padding: 14px 18px; margin-bottom: 14px;
  border: 1px solid rgba(245, 165, 36, 0.4);
  background: var(--warn-bg); color: var(--warn-tx);
}}
.alert-hdr {{ font-weight: 700; font-size: 14.5px; margin-bottom: 6px; }}
.clean-list {{ margin: 8px 0 0; padding-inline-start: 20px; font-size: 13.5px; }}
.clean-list li {{ margin-bottom: 5px; }}

.pill {{ display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px; border-radius: 999px; font-size: 11.5px; font-weight: 600; }}
.pill-hotspot {{ background: var(--hot-bg); color: var(--hot-tx); border: 1px solid rgba(255, 110, 100, 0.32); }}
.pill-pass {{ background: var(--pass-bg); color: var(--pass-tx); border: 1px solid rgba(63, 185, 80, 0.32); }}
.pill-warn {{ background: var(--warn-bg); color: var(--warn-tx); border: 1px solid rgba(245, 165, 36, 0.35); }}
.pill-info {{ background: var(--accent-bg); color: #9ec5ff; border: 1px solid rgba(91, 155, 255, 0.3); }}
.pill-neutral {{ background: rgba(255, 255, 255, 0.06); color: var(--text-soft); }}

.layer-heading {{ font-size: 16px; font-weight: 700; color: var(--text); margin: 24px 0 12px; display: flex; align-items: center; gap: 8px; }}
.layer-heading::before {{ content: ""; width: 4px; height: 18px; border-radius: 2px; background: var(--accent); display: inline-block; }}

.file-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  margin-bottom: 14px;
  overflow: hidden;
  transition: border-color 0.15s ease;
}}
.file-card.triage-hotspot {{ border-color: rgba(248, 81, 73, 0.38); }}
.file-card.is-reviewed {{ border-color: rgba(63, 185, 80, 0.45); opacity: 0.82; }}
.file-summary {{
  cursor: pointer; padding: 12px 16px;
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
  background: var(--surface-2);
  list-style: none;
}}
.file-summary::-webkit-details-marker {{ display: none; }}
.file-summary-left, .file-summary-right {{ display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }}
.file-path {{ font-size: 13.5px; color: var(--text); }}
.file-dir {{ color: var(--muted); font-weight: 400; }}
.triage-tags {{ color: var(--muted); font-size: 12.5px; }}
.delta-add {{ color: var(--add-tx); font-size: 12.5px; font-weight: 700; }}
.delta-del {{ color: var(--del-tx); font-size: 12.5px; font-weight: 700; }}

.why-banner {{
  background: var(--why-bg);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  border-inline-start: 3px solid var(--accent);
  padding: 10px 16px;
  font-size: 14px;
  color: var(--text);
}}
.why-icon {{ margin-inline-end: 4px; }}

.xray-inline {{ background: rgba(245, 165, 36, 0.08); border-bottom: 1px solid var(--border); padding: 9px 16px; font-size: 13px; }}
.xray-inline-row {{ margin: 4px 0; }}

.hunk-block {{ border-top: 1px solid var(--border); }}
.hunk-bar {{
  background: #0d1016;
  padding: 8px 14px;
  font-size: 12.5px;
  display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;
}}
.hunk-bar-main {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
.hunk-hdr {{ color: var(--muted); font-size: 12px; }}
.hunk-why {{ color: var(--text-soft); font-size: 13px; font-weight: 500; }}
.hunk-actions {{ display: flex; gap: 6px; align-items: center; }}

.diff-scroll {{ overflow-x: auto; background: #0b0e13; }}
.diff-table {{ width: 100%; border-collapse: collapse; font-size: 13px; line-height: 1.6; }}
.diff-line td {{ padding: 1px 8px; vertical-align: top; }}
.ln-col {{ width: 46px; text-align: right; color: var(--muted); user-select: none; font-size: 11.5px; opacity: 0.7; }}
.act-col {{ width: 26px; text-align: center; user-select: none; }}
.line-note-btn {{
  opacity: 0; background: var(--accent); color: #090b0e; font-weight: 700;
  border: none; border-radius: 4px; width: 19px; height: 19px; font-size: 13px; line-height: 18px; cursor: pointer; padding: 0;
}}
.diff-line:hover .line-note-btn {{ opacity: 1; }}
.code-col pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font-family: var(--font-mono); }}
.diff-add {{ background: var(--add-bg); box-shadow: inset 3px 0 0 var(--add-bar); }}
.diff-add .code-col pre {{ color: var(--add-tx); }}
.diff-del {{ background: var(--del-bg); box-shadow: inset 3px 0 0 var(--del-bar); }}
.diff-del .code-col pre {{ color: var(--del-tx); }}

.note-box {{ background: #0e131d; border: 1px solid rgba(91, 155, 255, 0.5); border-radius: 10px; padding: 10px 12px; margin: 8px 14px; direction: rtl; }}
html[dir="ltr"] .note-box {{ direction: ltr; }}
.note-box textarea {{
  width: 100%; min-height: 64px; background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: 8px; padding: 8px 10px;
  font-size: 14px; font-family: var(--font-sans); line-height: 1.55;
}}
.note-box-bar {{ display: flex; justify-content: space-between; align-items: center; margin-top: 6px; font-size: 12px; color: var(--muted); }}

.table-wrap {{ overflow-x: auto; margin-top: 10px; }}
.ag-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.ag-table th, .ag-table td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: start; }}
.ag-table th {{ color: var(--muted); font-weight: 600; font-size: 12px; }}
.snippet-box {{ font-size: 12px; color: var(--text-soft); }}
.muted {{ color: var(--muted); }}
.pad-14 {{ padding: 14px; }}
.rounds-wrap {{ display: flex; gap: 6px; flex-wrap: wrap; }}

.dock {{
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 50;
  background: rgba(12, 15, 20, 0.96); backdrop-filter: blur(12px);
  border-top: 1px solid var(--border-strong);
  padding: 11px 22px;
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
}}
.toast {{ color: var(--pass-tx); font-size: 13px; font-weight: 600; display: none; margin-inline-start: 8px; }}
</style>
</head>
<body>
<header class="topbar">
  <div>
    <div class="brand-row">
      <span class="brand-dot"></span>
      <h1 class="brand-title">{_i18n_span("Interactive Review Cockpit", AR_STRINGS["app_title"])} &mdash; <code class="ltr-code">{esc(task_id)}</code></h1>
      <span class="pill pill-pass" id="reviewed-counter">0 / {len(ordered_files)} {esc(AR_STRINGS["files_word"])}</span>
    </div>
    <div class="subtitle">
      <span><strong>{esc(traceability["kind"])}</strong> &bull; {esc(task_status)}</span>
      <span class="ltr-code"><span class="delta-add">+{total_added}</span> / <span class="delta-del">-{total_deleted}</span></span>
      <span>{esc(generated_at)}</span>
    </div>
  </div>
  <div class="toolbar">
    <button type="button" class="btn active" onclick="applyFilter('ALL', this)">{_i18n_span("All", AR_STRINGS["filter_all"])} ({len(ordered_files)})</button>
    <button type="button" class="btn" onclick="applyFilter('HOTSPOT', this)">{_i18n_span("Hotspots", AR_STRINGS["filter_hotspot"])} ({hotspot_count})</button>
    <button type="button" class="btn" onclick="applyFilter('SIDE_EFFECT', this)">{_i18n_span("Side-Effects", AR_STRINGS["filter_side_effect"])} ({len(side_effects)})</button>
    <button type="button" class="btn" onclick="applyFilter('AI_NOTES', this)">{_i18n_span("AI Notes", AR_STRINGS["filter_ai_notes"])}</button>
    <button type="button" class="btn" onclick="expandAll(true)">{_i18n_span("Expand All", AR_STRINGS["expand_all"])}</button>
    <button type="button" class="btn" onclick="expandAll(false)">{_i18n_span("Collapse Routine", AR_STRINGS["collapse_boilerplate"])}</button>
    <button type="button" class="btn btn-lang" id="lang-toggle-btn" onclick="toggleLanguage()">English (LTR)</button>
  </div>
</header>

<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-hdr">
      {_i18n_span("Clean-Architecture Flow", AR_STRINGS["sidebar_title"])}
      <span class="muted ltr-code">{len(ordered_files)}</span>
    </div>
    {"".join(toc_items) or "<div class='muted'>-</div>"}
  </aside>

  <main>
    {side_effect_banner}
    <div class="overview-grid">
      <section class="panel-card" id="goal-panel" style="margin-bottom:0;">
        <div class="muted" style="font-size:12.5px;font-weight:600;">{_i18n_span("Approved Task Goal", AR_STRINGS["goal_label"])}</div>
        <div class="goal-text" dir="auto">{esc(traceability["outcome"] or task_id)}</div>
        <div class="gates-row">{gate_badges_html}</div>
      </section>
      <section class="panel-card" id="plan-traceability-panel" style="margin-bottom:0;">
        <div class="muted" style="font-size:12.5px;font-weight:600;margin-bottom:6px;">
          {_i18n_span("Plan-to-Diff Traceability", AR_STRINGS["scope_label"])}
          <span class="ltr-code">({traceability["initial_expected_count"]} &rarr; {traceability["current_expected_count"]})</span>
        </div>
        {"".join(phase_rows_html)}
      </section>
    </div>

    {blast_html}
    {xray_html}

    <section id="files-container">
      {"".join(file_cards) or '<div class="panel-card">No task-isolated diff changes detected yet.</div>'}
    </section>
  </main>
</div>

<footer class="dock">
  <div>
    <strong>{_i18n_span("Surgical Fix Composer:", AR_STRINGS["dock_title"])}</strong>
    <span id="note-counter" class="pill pill-info">0</span>
    <span class="muted">{_i18n_span("Click + beside any line to add surgical notes, then copy the ready Antigravity command.", AR_STRINGS["dock_hint"])}</span>
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
const TASK_ID = {json.dumps(task_id)};
const TASK_STATUS = {json.dumps(task_status)};
const TOTAL_FILES = {len(ordered_files)};
const REOPEN_CMD = {json.dumps(reopen_cmd)};

let currentLang = "ar";
let notesState = {{}};
let reviewedState = {{}};
try {{
  const savedLang = localStorage.getItem(LANG_STORAGE_KEY);
  if (savedLang === "en" || savedLang === "ar") currentLang = savedLang;
  notesState = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}") || {{}};
  reviewedState = JSON.parse(localStorage.getItem(REV_STORAGE_KEY) || "{{}}") || {{}};
}} catch (_e) {{}}

function applyLanguage(lang) {{
  currentLang = lang;
  document.documentElement.lang = lang;
  document.documentElement.dir = (lang === "ar") ? "rtl" : "ltr";
  const btn = document.getElementById("lang-toggle-btn");
  if (btn) btn.textContent = (lang === "ar") ? "English (LTR)" : "\u0639\u0631\u0628\u064a (RTL)";
  document.querySelectorAll("[data-en]").forEach(el => {{
    el.textContent = (lang === "ar") ? (el.getAttribute("data-ar") || el.getAttribute("data-en")) : el.getAttribute("data-en");
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
  container.innerHTML = `
    <div class="note-box">
      <div style="font-size:12px;color:#9ec5ff;margin-bottom:5px;"><code class="ltr-code">${{filePath}}:${{lineNum}}</code></div>
      <textarea dir="auto" placeholder="${{ph}}" oninput="updateNote('${{slotKey}}', '${{filePath}}', ${{lineNum}}, this.value)"></textarea>
      <div class="note-box-bar">
        <span>${{savedLbl}}</span>
        <button type="button" class="btn-sm" onclick="removeNote('${{slotKey}}')">${{rmLbl}}</button>
      </div>
    </div>`;
  const ta = container.querySelector("textarea");
  ta.value = existing;
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
      ? "\u0644\u0645 \u062a\u0643\u062a\u0628 \u0623\u064a \u062a\u0639\u0644\u064a\u0642\u0627\u062a \u0628\u0639\u062f. \u0627\u0636\u063a\u0637 + \u0628\u062c\u0627\u0646\u0628 \u0623\u064a \u0633\u0637\u0631 \u0623\u0648\u0644\u0627\u064b."
      : "No inline review notes entered yet. Click + beside any line first.";
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
  return lines.join("\\n");
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
  document.querySelectorAll(".topbar .toolbar .btn:not(.btn-lang)").forEach(b => b.classList.remove("active"));
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
    else if (card.dataset.triage === "AUTO_COLLAPSED") card.removeAttribute("open");
  }});
}}

Object.keys(reviewedState).forEach(k => {{
  if (reviewedState[k]) syncReviewedDom(k, true, false);
}});
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
) -> dict[str, Any]:
    """Generate task-isolated `human-review.html` and metadata JSON for `task_id`."""
    root = repo.resolve()
    resolved_tid = _resolve_target_task_id(root, task_id)
    t_dir = state_root(root) / "tasks" / resolved_tid
    plan_file = t_dir / "plan.json"
    if not plan_file.is_file():
        raise ValidationError(f"Task plan not found for '{resolved_tid}' at {plan_file}")
    plan = read_json(plan_file)

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
    xray = _collect_ai_review_xray(t_dir)
    traceability = _collect_plan_traceability(t_dir, plan, parsed_files)
    generated_at = utc_now()

    html_doc = _render_cockpit_html(
        repo=root,
        task_id=resolved_tid,
        ordered_files=enriched_files,
        blast_callers=blast_callers,
        gates=gates,
        xray=xray,
        traceability=traceability,
        generated_at=generated_at,
    )

    target_html = Path(output_path).resolve() if output_path else (t_dir / "human-review.html")
    target_html.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target_html, html_doc.encode("utf-8"))

    summary = {
        "schema_version": 1,
        "task_id": resolved_tid,
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
        description="Generate task-isolated Interactive Human Review Cockpit HTML (`human-review.html`).",
    )
    parser.add_argument("--repo", default=".", help="Repository root path.")
    parser.add_argument("--task-id", "--task", dest="task_id", default=None, help="Target task ID (defaults to active task).")
    parser.add_argument("--output", default=None, help="Optional custom output HTML file path.")
    parser.add_argument("--open", action="store_true", help="Open generated HTML cockpit in default desktop browser.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    args = parser.parse_args(argv)

    try:
        res = generate_human_review_cockpit(
            Path(args.repo),
            args.task_id,
            output_path=Path(args.output) if args.output else None,
            open_browser=bool(args.open),
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
            f"[OK] Generated Interactive Review Cockpit for `{res['task_id']}`: "
            f"{res['touched_files_count']} isolated file(s), "
            f"{res['hotspot_files_count']} hotspot(s), "
            f"{res['blast_radius_callers_count']} unmodified caller(s), "
            f"{res['side_effect_files_count']} side-effect file(s)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
