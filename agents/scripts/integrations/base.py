"""Base interfaces and generic external_write safety primitives."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

DENIED_TERMINAL_STATUSES = frozenset({"done", "solved", "closed", "completed"})


class ExternalIntegration(ABC):
    """Abstract base class for external tool integrations (PM trackers, etc.)."""

    name: str = ""
    display_name: str = ""

    @abstractmethod
    def matches(self, server: str, tool_name: str) -> bool:
        """Return True if this integration handles the given server or tool."""
        raise NotImplementedError

    @abstractmethod
    def is_read_only(self, tool_name: str, args: Mapping[str, Any]) -> bool:
        """Return True if the tool invocation is a read-only operation."""
        raise NotImplementedError

    def validate_mutation(
        self,
        tool_name: str,
        args: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> tuple[bool, str]:
        """Validate an authorized mutation against integration-specific rules.

        Returns:
            (allowed: bool, reason: str)
        """
        return True, ""


def validate_external_write(
    integration: ExternalIntegration,
    tool_name: str,
    args: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> tuple[bool, str]:
    """Validate generic external write requirements against the active plan.

    Invariants:
    1. Plan authorization: Active status (IMPLEMENTING or READY_FOR_DELIVERY),
       matching single_use_nonce, and integration.name listed in external_writes.
    2. Idempotency requirement: Stable operation_id must be present.
    3. Terminal-state developer ownership: Reject terminal statuses.
    4. Integration-specific validation policy.
    """
    status = str(plan.get("status") or "")
    approval = plan.get("approval") or {}
    execution_nonce = plan.get("execution_nonce")
    single_use_nonce = approval.get("single_use_nonce") if isinstance(approval, dict) else None
    external_writes = set(plan.get("external_writes") or [])

    authorized = (
        status in {"IMPLEMENTING", "READY_FOR_DELIVERY"}
        and execution_nonce
        and execution_nonce == single_use_nonce
        and integration.name in external_writes
    )
    if not authorized:
        return False, f"{integration.display_name} mutation is not included in the active approved plan."

    operation_id = str(args.get("operation_id") or "").strip()
    if not operation_id:
        return False, f"{integration.display_name} mutations require a stable operation_id for idempotency."

    requested_status = str(args.get("status") or "").strip().lower()
    if requested_status in DENIED_TERMINAL_STATUSES:
        return False, "Terminal tracker states are developer-owned."

    return integration.validate_mutation(tool_name, args, plan)
