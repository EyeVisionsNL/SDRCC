#!/usr/bin/env python3
"""Read-only execution metadata for the page-controlled HF Monitor."""

from __future__ import annotations

from typing import Any, Mapping

from core.execution_adapter import ExecutionAdapter
from core.execution_plan import ExecutionPlan, normalize_request


class HFMonitorAdapter(ExecutionAdapter):
    adapter_type = "hf_monitor"
    supported_executor = "hf_monitor"
    delegates_to = (
        "hf_monitor_controller",
        "receiver_manager",
        "existing_service_control",
        "librtlsdr_backend",
    )

    def validate(self) -> tuple[str, ...]:
        errors = list(super().validate())
        if self.metadata.get("services") not in ([], None):
            errors.append("HF Monitor adapter owns no persistent service")
        return tuple(errors)

    def build_plan(
        self,
        request: Mapping[str, Any] | None = None,
    ) -> ExecutionPlan:
        normalize_request(request)
        descriptor = self.describe()
        return ExecutionPlan(
            plugin_id=self.plugin_id,
            adapter_type=self.adapter_type,
            executor_type=self.supported_executor,
            launch_type="bounded_operator_session",
            target_type="operator_selected_receiver",
            targets=(),
            receiver_role=self.metadata.get("assignment_role"),
            receiver_type=self.metadata.get("receiver_type"),
            requirements=(
                "operator_receiver_selection",
                "receiver_available",
                "receiver_manager_handover",
                "librtlsdr_direct_sampling",
            ),
            delegates_to=self.delegates_to,
            executable=False,
            read_only=True,
            foundation_only=True,
            metadata_valid=descriptor.metadata_valid,
            validation_errors=descriptor.validation_errors,
        )
