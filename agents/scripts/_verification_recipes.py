"""Deterministic manual verification recipes for Android change surfaces."""
from __future__ import annotations

from typing import Any

VERIFICATION_RECIPES: dict[str, list[str]] = {
    "COMPOSE_UI": [
        "Open affected Compose screen or component.",
        "Verify visual hierarchy, layout, and state rendering across screen sizes.",
        "Check clipping, alignment, padding, and Arabic/English RTL/LTR behavior.",
        "Trigger relevant user interactions (taps, inputs, state changes).",
        "Navigate away and return to verify state retention and absence of jank.",
    ],
    "XML_UI": [
        "Open affected layout/view activity or fragment.",
        "Verify view bindings, styling, and resource resolution.",
        "Check view hierarchy, clipping, and styling across RTL/LTR.",
        "Trigger relevant user interactions and verify view state updates.",
        "Rotate device or navigate away and back to verify state restoration.",
    ],
    "RESOURCE_UI": [
        "Open affected layout/screen exercising modified resources.",
        "Verify localized strings, colors, dimensions, and drawable scaling.",
        "Check RTL layout alignment and Arabic text rendering.",
    ],
    "NAVIGATION": [
        "Open starting screen.",
        "Navigate to changed destination and verify arguments/parameters.",
        "Press back button/gesture to verify back-stack restoration.",
        "Repeat deep-link or multi-stack navigation return path if relevant.",
    ],
    "ROOM_SCHEMA": [
        "Preserve existing app database/version data before upgrading.",
        "Install upgrade build over prior database state (do not clear app data).",
        "Launch flow exercising migrated tables and entities.",
        "Confirm preexisting data is intact and queries succeed.",
        "Execute new read/write operations to verify schema compatibility across relaunches.",
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
    "BUSINESS_LOGIC": [
        "Open screen/flow exercising modified domain or business logic.",
        "Execute primary action and verify expected outcome.",
        "Test boundary or negative condition and verify correct error/fallback handling.",
        "Perform related flow to verify no regression in dependent state.",
    ],
}

APPLICATION_FALLBACK_RECIPE: list[str] = [
    "Launch the target activity on device/emulator.",
    "Navigate through the modified user journey and exercise the new or updated logic.",
    "Confirm visual stability, responsiveness, and lack of crashes or logcat errors.",
]


def generate_bounded_walkthrough(
    *,
    requested_outcome: str = "",
    surfaces: list[str] | None = None,
    changed_files: list[str] | None = None,
    activity: str = "",
) -> dict[str, list[str]]:
    """Generate deterministic, bounded mobile walkthrough with exactly 4 sections (Sections 75-76).

    Bounds:
    - Preconditions: 1..4 items
    - Main Happy Path: 2..6 items
    - Important Edge Cases: 1..4 items
    - Regression Checks: 1..3 items
    """
    surfs = set(surfaces or [])
    outcome = requested_outcome.strip() or "Verify modified functionality"
    act = activity or "Main Activity"

    # 1. Preconditions (1-4)
    preconditions = [f"Launch application on target device ({act})."]
    if any(s in surfs for s in ("AUTH", "SECURITY", "SENSITIVE_DATA")):
        preconditions.append("Ensure authenticated user session is active.")
    if "ROOM_SCHEMA" in surfs:
        preconditions.append("Retain preexisting local database state before launching.")
    if len(preconditions) < 2:
        preconditions.append("Ensure device network connectivity is available.")

    # 2. Main Happy Path (2-6)
    happy_path = [
        f"Navigate from {act} to the modified screen/feature.",
        f"Perform core user action: {outcome}.",
        "Verify expected visual feedback and state changes on screen.",
    ]
    if "NAVIGATION" in surfs:
        happy_path.append("Verify destination screen arguments and back stack navigation.")

    # 3. Important Edge Cases (1-4)
    edge_cases = []
    if any(s in surfs for s in ("COMPOSE_UI", "XML_UI", "RESOURCE_UI")):
        edge_cases.append("Verify RTL/LTR language alignment (Arabic and English).")
        edge_cases.append("Check device rotation and configuration change state retention.")
    if "DEVICE_API" in surfs or "MANIFEST_PERMISSION" in surfs:
        edge_cases.append("Test runtime permission denial or hardware unavailable fallback.")
    if "BUSINESS_LOGIC" in surfs:
        edge_cases.append("Test boundary or invalid input condition.")
    if not edge_cases:
        edge_cases.append("Test back navigation and app backgrounding/resumption.")

    # 4. Regression Checks (1-3)
    regression_checks = [
        "Verify directly related screens continue to function without crash.",
        "Check logcat output for unexpected exceptions or ANRs.",
    ]

    return {
        "preconditions": preconditions[:4],
        "happy_path": happy_path[:6],
        "edge_cases": edge_cases[:4],
        "regression_checks": regression_checks[:3],
    }


def get_verification_recipes(surfaces: list[str], *, fallback: bool = False) -> list[dict[str, Any]]:
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
    if not result and fallback:
        result.append({
            "surface": "APPLICATION",
            "steps": list(APPLICATION_FALLBACK_RECIPE),
        })
    return result
