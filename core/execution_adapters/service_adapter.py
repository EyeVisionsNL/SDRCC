#!/usr/bin/env python3
"""Read-only service execution adapter metadata contract."""

from __future__ import annotations

from typing import Any, Mapping

from core.execution_adapter import ExecutionAdapter
from core.execution_plan import ExecutionPlan, normalize_request


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


    def build_plan(
        self,
        request: Mapping[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Describe delegation to existing service-control authority."""
        normalized_request = normalize_request(request)
        descriptor = self.describe()
        services = tuple(descriptor.services)
        receiver_role = str(
            normalized_request.get("receiver_role")
            or self.metadata.get("assignment_role")
            or ""
        ).strip() or None
        receiver_type = str(
            self.metadata.get("receiver_type") or ""
        ).strip() or None

        return ExecutionPlan(
            plugin_id=self.plugin_id,
            adapter_type=self.adapter_type,
            executor_type=self.supported_executor,
            launch_type="persistent_service",
            target_type="systemd_service",
            targets=services,
            receiver_role=receiver_role,
            receiver_type=receiver_type,
            requirements=(
                "receiver_assignment_resolved",
                "receiver_available",
                "service_control_authority",
            ),
            delegates_to=self.delegates_to,
            executable=False,
            read_only=True,
            foundation_only=True,
            metadata_valid=descriptor.metadata_valid,
            validation_errors=descriptor.validation_errors,
        )
