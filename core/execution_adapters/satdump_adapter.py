#!/usr/bin/env python3
"""Read-only SatDump execution adapter metadata contract."""

from __future__ import annotations

from core.execution_adapter import ExecutionAdapter


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
