"""Universal Runtime Environment & Surface Detection for Android Agent Harness.

Lightweight, zero-dependency environment sensor that determines the active AI
assistant environment (Google Antigravity, Claude Code, Cursor, OpenAI Codex,
GitHub Copilot) and surface (Desktop 2.0, IDE, CLI).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AssistantEnv(str, Enum):
    ANTIGRAVITY = "antigravity"
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    CODEX = "codex"
    COPILOT = "copilot"
    GENERIC = "generic"


class AntigravitySurface(str, Enum):
    DESKTOP_2_0 = "desktop_2_0"
    IDE = "ide"
    CLI = "cli"
    NONE = "none"


@dataclass(frozen=True)
class RuntimeProfile:
    env: AssistantEnv
    surface: AntigravitySurface
    has_stop_hook: bool
    has_pre_tool_overwrite: bool
    has_interactive_modals: bool
    has_generative_ui: bool
    has_native_subagents: bool
    session_id: str


_CACHED_PROFILE: RuntimeProfile | None = None


def detect_runtime_profile(hook_payload: dict[str, Any] | None = None) -> RuntimeProfile:
    """Detect current AI assistant runtime profile and surface capabilities."""
    global _CACHED_PROFILE
    if hook_payload is None and _CACHED_PROFILE is not None:
        return _CACHED_PROFILE

    # 0. Test override
    test_env = os.environ.get("HARNESS_TEST_ENV", "").strip().lower()
    if test_env:
        for candidate in AssistantEnv:
            if candidate.value == test_env:
                profile = RuntimeProfile(
                    env=candidate,
                    surface=AntigravitySurface.DESKTOP_2_0 if candidate == AssistantEnv.ANTIGRAVITY else AntigravitySurface.NONE,
                    has_stop_hook=(candidate == AssistantEnv.ANTIGRAVITY),
                    has_pre_tool_overwrite=(candidate == AssistantEnv.ANTIGRAVITY),
                    has_interactive_modals=(candidate == AssistantEnv.ANTIGRAVITY),
                    has_generative_ui=(candidate == AssistantEnv.ANTIGRAVITY),
                    has_native_subagents=(candidate == AssistantEnv.ANTIGRAVITY),
                    session_id=f"{candidate.value}-test-session",
                )
                _CACHED_PROFILE = profile
                return profile

    # 1. Claude Code (Unique payload schema: tool_name / toolName)
    if (
        (hook_payload and ("tool_name" in hook_payload or "toolName" in hook_payload))
        or os.environ.get("CLAUDE_CODE") == "1"
        or os.environ.get("CLAUDE_CLI") == "1"
        or bool(os.environ.get("CLAUDE_SESSION_ID"))
    ):
        cc_session = (
            os.environ.get("CLAUDE_SESSION_ID")
            or (hook_payload.get("session_id") if hook_payload else None)
            or (hook_payload.get("sessionId") if hook_payload else None)
            or "claude-session"
        )
        profile = RuntimeProfile(
            env=AssistantEnv.CLAUDE_CODE,
            surface=AntigravitySurface.NONE,
            has_stop_hook=False,
            has_pre_tool_overwrite=False,
            has_interactive_modals=False,
            has_generative_ui=False,
            has_native_subagents=False,
            session_id=cc_session,
        )
        _CACHED_PROFILE = profile
        return profile

    # 2. OpenAI Codex CLI
    if os.environ.get("CODEX_CLI") == "1" or bool(os.environ.get("CODEX_SESSION_ID")):
        profile = RuntimeProfile(
            env=AssistantEnv.CODEX,
            surface=AntigravitySurface.NONE,
            has_stop_hook=False,
            has_pre_tool_overwrite=False,
            has_interactive_modals=False,
            has_generative_ui=False,
            has_native_subagents=False,
            session_id=os.environ.get("CODEX_SESSION_ID", "codex-session"),
        )
        _CACHED_PROFILE = profile
        return profile

    # 3. Cursor
    if (
        os.environ.get("CURSOR_AGENT") == "1"
        or bool(os.environ.get("CURSOR_WORKSPACE"))
        or "CURSOR" in os.environ.get("VSCODE_GIT_ASKPASS_NODE", "").upper()
    ):
        profile = RuntimeProfile(
            env=AssistantEnv.CURSOR,
            surface=AntigravitySurface.NONE,
            has_stop_hook=False,
            has_pre_tool_overwrite=False,
            has_interactive_modals=False,
            has_generative_ui=False,
            has_native_subagents=False,
            session_id=os.environ.get("CURSOR_CONVERSATION_ID", "cursor-session"),
        )
        _CACHED_PROFILE = profile
        return profile

    # 4. Google Antigravity
    # Indicators: ANTIGRAVITY_AGENT env var, or transcriptPath in hook payload, or ANTIGRAVITY_* metadata
    if (
        os.environ.get("ANTIGRAVITY_AGENT") == "1"
        or (hook_payload and ("transcriptPath" in hook_payload or "transcript_path" in hook_payload))
        or bool(os.environ.get("ANTIGRAVITY_CONVERSATION_ID"))
        or bool(os.environ.get("ANTIGRAVITY_AGENTAPI_EXE"))
    ):
        conv_id = (
            os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
            or (hook_payload.get("conversationId") if hook_payload else None)
            or (hook_payload.get("conversation_id") if hook_payload else None)
            or "unknown"
        )
        agentapi_exe = os.environ.get("ANTIGRAVITY_AGENTAPI_EXE", "").lower()
        if "antigravity-cli" in agentapi_exe:
            surface = AntigravitySurface.CLI
        elif "antigravity-ide" in agentapi_exe:
            surface = AntigravitySurface.IDE
        else:
            surface = AntigravitySurface.DESKTOP_2_0

        is_gui = surface in (AntigravitySurface.DESKTOP_2_0, AntigravitySurface.IDE)
        profile = RuntimeProfile(
            env=AssistantEnv.ANTIGRAVITY,
            surface=surface,
            has_stop_hook=True,
            has_pre_tool_overwrite=True,
            has_interactive_modals=is_gui,
            has_generative_ui=is_gui,
            has_native_subagents=True,
            session_id=conv_id,
        )
        _CACHED_PROFILE = profile
        return profile

    # 5. GitHub Copilot
    if (
        os.environ.get("GITHUB_COPILOT") == "1"
        or (hook_payload and "copilot" in str(hook_payload).lower())
    ):
        profile = RuntimeProfile(
            env=AssistantEnv.COPILOT,
            surface=AntigravitySurface.NONE,
            has_stop_hook=False,
            has_pre_tool_overwrite=False,
            has_interactive_modals=False,
            has_generative_ui=False,
            has_native_subagents=False,
            session_id="copilot-session",
        )
        _CACHED_PROFILE = profile
        return profile

    # 6. Fallback Generic
    profile = RuntimeProfile(
        env=AssistantEnv.GENERIC,
        surface=AntigravitySurface.NONE,
        has_stop_hook=False,
        has_pre_tool_overwrite=False,
        has_interactive_modals=False,
        has_generative_ui=False,
        has_native_subagents=False,
        session_id="generic-session",
    )
    _CACHED_PROFILE = profile
    return profile


def is_antigravity(hook_payload: dict[str, Any] | None = None) -> bool:
    return detect_runtime_profile(hook_payload).env == AssistantEnv.ANTIGRAVITY


def is_codex(hook_payload: dict[str, Any] | None = None) -> bool:
    return detect_runtime_profile(hook_payload).env == AssistantEnv.CODEX


def is_claude_code(hook_payload: dict[str, Any] | None = None) -> bool:
    return detect_runtime_profile(hook_payload).env == AssistantEnv.CLAUDE_CODE


def is_cursor(hook_payload: dict[str, Any] | None = None) -> bool:
    return detect_runtime_profile(hook_payload).env == AssistantEnv.CURSOR


def supports_generative_ui(hook_payload: dict[str, Any] | None = None) -> bool:
    return detect_runtime_profile(hook_payload).has_generative_ui


def supports_interactive_modals(hook_payload: dict[str, Any] | None = None) -> bool:
    return detect_runtime_profile(hook_payload).has_interactive_modals


def supports_stop_hook(hook_payload: dict[str, Any] | None = None) -> bool:
    return detect_runtime_profile(hook_payload).has_stop_hook


def supports_overwrite(hook_payload: dict[str, Any] | None = None) -> bool:
    return detect_runtime_profile(hook_payload).has_pre_tool_overwrite


def supports_parallel_subagents(hook_payload: dict[str, Any] | None = None) -> bool:
    return detect_runtime_profile(hook_payload).has_native_subagents


def get_session_id(hook_payload: dict[str, Any] | None = None) -> str:
    return detect_runtime_profile(hook_payload).session_id
