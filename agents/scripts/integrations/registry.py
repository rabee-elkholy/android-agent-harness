"""Integration registry for external tools."""
from __future__ import annotations

from typing import Iterable
from integrations.base import ExternalIntegration


class IntegrationRegistry:
    """Registry maintaining active external tool integrations."""

    def __init__(self, integrations: Iterable[ExternalIntegration] | None = None) -> None:
        self._integrations: list[ExternalIntegration] = list(integrations or [])

    def register(self, integration: ExternalIntegration) -> None:
        self._integrations = [i for i in self._integrations if i.name != integration.name]
        self._integrations.append(integration)

    def resolve(self, server: str, tool_name: str) -> ExternalIntegration | None:
        for integration in self._integrations:
            if integration.matches(server, tool_name):
                return integration
        return None

    def get(self, name: str) -> ExternalIntegration | None:
        for integration in self._integrations:
            if integration.name == name:
                return integration
        return None

    def all(self) -> list[ExternalIntegration]:
        return list(self._integrations)


registry = IntegrationRegistry()

try:
    from integrations.zoho_sprints.integration import ZohoSprintsIntegration
    registry.register(ZohoSprintsIntegration())
except ImportError:
    pass
