#!/usr/bin/env python3
"""Read-only service execution adapter metadata contract."""

from __future__ import annotations

from core.execution_adapter import ExecutionAdapter


class ServiceAdapter(ExecutionAdapter):
    """Validate service-backed plugin metadata without controlling services."""

    adapter_type = "service"
    supported_executor = "service"
    delegates_to = ("receiver_manager", "existing_service_control")

    def validate(self) -> tuple[str, ...]:
        errors = list(super().validate())
        services = self.metadata.get("services")

        if not isinstance(services, list) or not services:
            errors.append("service-adapter vereist minimaal één service")
        elif any(not isinstance(item, str) or not item.strip() for item in services):
            errors.append("service-adapter bevat een ongeldige servicenaam")
        elif len(services) != len(set(services)):
            errors.append("service-adapter bevat dubbele services")

        return tuple(errors)
