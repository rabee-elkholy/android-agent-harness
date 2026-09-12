"""Deterministic manual verification recipes for Android change surfaces."""
from __future__ import annotations

from typing import Any

VERIFICATION_RECIPES: dict[str, list[str]] = {
    "COMPOSE_UI": [
        "Open affected Compose screen or component.",
        "Verify visual hierarchy, layout, and state rendering.",
        "Trigger relevant user interactions (taps, inputs, state changes).",
        "Navigate away and return to verify state retention.",
        "Confirm no clipping, jank, or runtime exceptions.",
    ],
    "XML_UI": [
        "Open affected layout/view activity or fragment.",
        "Verify view bindings, styling, and resource resolution.",
        "Trigger relevant user interactions and verify view state updates.",
        "Rotate device or navigate away and back to verify state restoration.",
        "Confirm no View/Layout inflation crashes or clipping.",
    ],
    "NAVIGATION": [
        "Open starting screen.",
        "Navigate to changed destination and verify arguments/parameters.",
        "Press back button/gesture to verify back-stack restoration.",
        "Repeat deep-link or multi-stack navigation path if relevant.",
    ],
    "ROOM_SCHEMA": [
        "Preserve existing app database/version data before upgrading.",
        "Install upgrade build over prior database state (do not clear app data).",
        "Launch flow exercising migrated tables and entities.",
        "Confirm preexisting data is intact and queries succeed.",
        "Execute new read/write operations to verify schema compatibility.",
    ],
    "MANIFEST_PERMISSION": [
        "Test runtime denial path and verify app handles denial gracefully.",
        "Grant requested permission and verify functional feature path.",
        "Verify feature behavior persists across app process restart.",
    ],
    "FOREGROUND_SERVICE": [
        "Start foreground service flow and confirm notification is displayed.",
        "Background app or lock screen; verify service continues executing.",
        "Confirm notification actions and foreground channel behavior.",
        "Return to app and stop flow normally; verify notification dismisses.",
    ],
    "DEVICE_API": [
        "Exercise hardware or platform API interaction flow on active target.",
        "Verify runtime permission state, device availability, and success callback.",
        "Test failure or edge condition (e.g. sensor unavailable, connection drop).",
        "Confirm resources are released when exiting screen or backgrounding app.",
    ],
}


def get_verification_recipes(surfaces: list[str]) -> list[dict[str, Any]]:
    """Return deterministic 3-6 step verification recipes for relevant Android surfaces."""
    seen_surfaces: set[str] = set()
    result: list[dict[str, Any]] = []

    for surface in surfaces:
        target_keys: list[str] = []
        if surface in VERIFICATION_RECIPES:
            target_keys.append(surface)
        elif surface == "RESOURCE_UI":
            if "XML_UI" not in surfaces and "COMPOSE_UI" not in surfaces:
                target_keys.append("XML_UI")

        for key in target_keys:
            if key in VERIFICATION_RECIPES and key not in seen_surfaces:
                seen_surfaces.add(key)
                result.append({
                    "surface": key,
                    "steps": list(VERIFICATION_RECIPES[key]),
                })
    return result
