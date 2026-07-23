#!/usr/bin/env python3
"""Read-only SatDump execution adapter metadata contract."""

from __future__ import annotations

from typing import Any, Mapping

from core.execution_adapter import ExecutionAdapter
from core.execution_plan import ExecutionPlan, normalize_request


class SatDumpAdapter(ExecutionAdapter):
    """Validate SatDump-backed metadata without starting a mission."""

    adapter_type = "satdump"
    supported_executor = "satdump"
    delegates_to = (
        "mission_engine",
        "receiver_manager",
        "core.satdump",
        "process_manager",
    )

    def validate(self) -> tuple[str, ...]:
        errors = list(super().validate())
        metadata = self.metadata
        capabilities = metadata.get("capabilities")
        services = metadata.get("services")

        if not isinstance(capabilities, list):
            errors.append("satdump-adapter vereist een capabilitylijst")
        else:
            required = {"recording", "decoding"}
            missing = sorted(required.difference(capabilities))
            if missing:
                errors.append(
                    "satdump-adapter mist capabilities: " + ", ".join(missing)
                )

        if services not in ([], None):
            errors.append("satdump-adapter mag geen systemd-services declareren")

        return tuple(errors)


    def build_plan(
        self,
        request: Mapping[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Describe delegation to existing mission and SatDump authorities."""
        normalized_request = normalize_request(request)
        descriptor = self.describe()
        receiver_role = str(
            normalized_request.get("receiver_role")
            or self.metadata.get("assignment_role")
            or ""
        ).strip() or None
        receiver_type = str(
            self.metadata.get("receiver_type") or ""
        ).strip() or None
        target = str(
            normalized_request.get("target")
            or normalized_request.get("satellite")
            or ""
        ).strip()

        targets = (target,) if target else ()

        return ExecutionPlan(
            plugin_id=self.plugin_id,
            adapter_type=self.adapter_type,
            executor_type=self.supported_executor,
            launch_type="mission",
            target_type="satdump_pipeline",
            targets=targets,
            receiver_role=receiver_role,
            receiver_type=receiver_type,
            requirements=(
                "mission_authority",
                "receiver_assignment_resolved",
                "receiver_locked",
                "satdump_pipeline_resolved",
            ),
            delegates_to=self.delegates_to,
            executable=False,
            read_only=True,
            foundation_only=True,
            metadata_valid=descriptor.metadata_valid,
            validation_errors=descriptor.validation_errors,
        )
