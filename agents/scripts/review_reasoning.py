"""Host capability resolver and reasoning effort mapper."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HostReasoningCapability:
    host: str
    supported: bool
    argument_name: str | None
    ordered_levels: tuple[str, ...]
    current_level: str | None
    source: str


def _valid_levels(
    levels: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    normalized = tuple(
        str(item).strip()
        for item in levels
        if str(item).strip()
    )

    if len(normalized) != len(levels):
        return ()

    if len(set(normalized)) != len(normalized):
        return ()

    return normalized


def capability_for_host(host: str) -> HostReasoningCapability:
    """Resolve trusted per-subagent reasoning capability for the target host.

    Resolved dynamically per review execution profile; never globally cached.
    """
    host_norm = str(host or "").lower().strip()
    if host_norm == "antigravity":
        return HostReasoningCapability(
            host="antigravity",
            supported=False,
            argument_name=None,
            ordered_levels=(),
            current_level=None,
            source="antigravity_invoke_subagent_no_per_subagent_effort",
        )
    return HostReasoningCapability(
        host=host,
        supported=False,
        argument_name=None,
        ordered_levels=(),
        current_level=None,
        source="no_trusted_per_subagent_reasoning_adapter",
    )


def resolve_reasoning(
    capability: HostReasoningCapability,
    intent: str,
) -> dict:
    """Map an abstract review effort intent to host-native reasoning controls."""
    if not capability.supported:
        return {
            "intent": intent,
            "control": "UNAVAILABLE",
            "argument_name": None,
            "native_value": None,
            "resolution": "HOST_CONTROL_UNAVAILABLE",
            "source": capability.source,
        }

    valid_levels = _valid_levels(capability.ordered_levels)
    arg_name = str(capability.argument_name or "").strip() if capability.argument_name else ""
    if not valid_levels or not arg_name or not capability.current_level or capability.current_level not in valid_levels:
        return {
            "intent": intent,
            "control": "UNAVAILABLE",
            "argument_name": None,
            "native_value": None,
            "resolution": "INVALID_HOST_CAPABILITY",
            "source": capability.source,
        }


    if intent == "NORMAL":
        return {
            "intent": intent,
            "control": "SUPPORTED",
            "argument_name": None,
            "native_value": None,
            "resolution": "INHERIT_CURRENT_REASONING",
            "source": capability.source,
        }

    if intent == "DEEP":
        curr_idx = valid_levels.index(capability.current_level)
        if curr_idx + 1 < len(valid_levels):
            return {
                "intent": intent,
                "control": "SUPPORTED",
                "argument_name": capability.argument_name,
                "native_value": valid_levels[curr_idx + 1],
                "resolution": "HOST_NATIVE_OVERRIDE",
                "source": capability.source,
            }
        return {
            "intent": intent,
            "control": "SUPPORTED",
            "argument_name": None,
            "native_value": None,
            "resolution": "ALREADY_AT_MAX",
            "source": capability.source,
        }

    if intent == "MAX":
        if valid_levels[-1] == capability.current_level:
            return {
                "intent": intent,
                "control": "SUPPORTED",
                "argument_name": None,
                "native_value": None,
                "resolution": "ALREADY_AT_MAX",
                "source": capability.source,
            }
        return {
            "intent": intent,
            "control": "SUPPORTED",
            "argument_name": capability.argument_name,
            "native_value": valid_levels[-1],
            "resolution": "HOST_NATIVE_OVERRIDE",
            "source": capability.source,
        }

    return {
        "intent": intent,
        "control": "SUPPORTED",
        "argument_name": None,
        "native_value": None,
        "resolution": "INHERIT_CURRENT_REASONING",
        "source": capability.source,
    }
