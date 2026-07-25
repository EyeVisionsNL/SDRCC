#!/usr/bin/env python3
"""Execution-plan adapter for bounded wideband RTL-SDR IQ captures."""
from __future__ import annotations
from typing import Any, Mapping
from core.execution_adapter import ExecutionAdapter
from core.execution_plan import ExecutionPlan, normalize_request

class WidebandIQAdapter(ExecutionAdapter):
    adapter_type = "wideband_iq"
    supported_executor = "wideband_iq"
    delegates_to = (
        "mission_engine",
        "receiver_manager",
        "core.wideband_iq_recorder",
        "mission_history",
    )

    def validate(self) -> tuple[str, ...]:
        errors = list(super().validate())
        metadata = self.metadata
        capabilities = metadata.get("capabilities")
        if not isinstance(capabilities, list):
            errors.append("wideband_iq-adapter vereist een capabilitylijst")
        else:
            required = {"recording", "wideband_iq"}
            missing = sorted(required.difference(capabilities))
            if missing:
                errors.append("wideband_iq-adapter mist capabilities: " + ", ".join(missing))
        if metadata.get("services") not in ([], None):
            errors.append("wideband_iq-adapter mag geen services declareren")
        return tuple(errors)

    def build_plan(self, request: Mapping[str, Any] | None = None) -> ExecutionPlan:
        request_data = normalize_request(request)
        descriptor = self.describe()
        receiver_role = str(request_data.get("receiver_role") or self.metadata.get("assignment_role") or "").strip() or None
        target = str(request_data.get("target") or request_data.get("satellite") or "ISS (ZARYA)").strip()
        return ExecutionPlan(
            plugin_id=self.plugin_id,
            adapter_type=self.adapter_type,
            executor_type=self.supported_executor,
            launch_type="bounded_process",
            target_type="wideband_iq_capture",
            targets=(target,) if target else (),
            receiver_role=receiver_role,
            receiver_type=str(self.metadata.get("receiver_type") or "").strip() or None,
            requirements=(
                "mission_authority",
                "receiver_assignment_resolved",
                "receiver_reserved",
                "conflicting_services_stopped",
                "bounded_capture_duration",
                "output_directory_resolved",
            ),
            delegates_to=self.delegates_to,
            executable=False,
            read_only=True,
            foundation_only=True,
            metadata_valid=descriptor.metadata_valid,
            validation_errors=descriptor.validation_errors,
        )
